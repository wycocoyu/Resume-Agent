from __future__ import annotations

import asyncio
import json
import math
import os
from typing import AsyncIterator, Awaitable, Callable, Dict, List, Optional, Union

import tiktoken
import httpx
from openai import (
    APIError,
    APIConnectionError,
    AsyncAzureOpenAI,
    AsyncOpenAI,
    AuthenticationError,
    OpenAIError,
    RateLimitError,
)
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from backend.agent.bedrock import BedrockClient
from backend.agent.config import LLMSettings, NetworkConfig, config
from backend.agent.exceptions import TokenLimitExceeded
from backend.agent.llm_streaming.tool_call_assembler import ToolCallAssembler
from backend.agent.pi_core.types import AssistantChunk, ModelTurn, ToolCall as CoreToolCall
from backend.core.logger import get_logger  # Assuming a logger is set up in your app

logger = get_logger(__name__)
from backend.agent.schema import (
    ROLE_VALUES,
    TOOL_CHOICE_TYPE,
    TOOL_CHOICE_VALUES,
    Message,
    ToolChoice,
)


REASONING_MODELS = ["o1", "o3-mini"]


def _one_tool_per_step_enabled() -> bool:
    """是否强制 ReAct 一步一工具(parallel_tool_calls=False)。

    机制级保证"每步只调一个工具"的丝滑节奏,不靠 prompt 祈祷(UP简历对标)。
    默认开启;若中转/兼容接口不认 parallel_tool_calls 参数而报错,
    可 export AGENT_DISABLE_PARALLEL_TOOLS=false 逃生(退回并行=旧行为)。
    """
    return os.getenv("AGENT_DISABLE_PARALLEL_TOOLS", "true").strip().lower() != "false"
MULTIMODAL_MODELS = [
    "gpt-4-vision-preview",
    "gpt-4o",
    "gpt-4o-mini",
    "claude-3-opus-20240229",
    "claude-3-sonnet-20240229",
    "claude-3-haiku-20240307",
]

_tiktoken_cache: Dict[str, tiktoken.Encoding] = {}


def _get_tiktoken_encoding(model: str) -> Optional[tiktoken.Encoding]:
    """Get tiktoken encoding with caching and network configuration."""
    cache_key = f"model:{model}"
    if cache_key in _tiktoken_cache:
        return _tiktoken_cache[cache_key]

    # Use network configuration manager instead of temporary proxy disabling
    network_config = config.network or NetworkConfig()
    with network_config.without_proxy():
        try:
            encoding = tiktoken.encoding_for_model(model)
            _tiktoken_cache[cache_key] = encoding
            return encoding
        except KeyError:
            pass
        except Exception as exc:
            logger.warning(f"[LLM] Failed to load model encoding: {exc}")

        try:
            if "cl100k_base" not in _tiktoken_cache:
                _tiktoken_cache["cl100k_base"] = tiktoken.get_encoding("cl100k_base")
            return _tiktoken_cache["cl100k_base"]
        except Exception as exc:
            logger.warning(f"[LLM] Failed to load fallback encoding: {exc}")
            return None


class TokenCounter:
    # Token constants
    BASE_MESSAGE_TOKENS = 4
    FORMAT_TOKENS = 2
    LOW_DETAIL_IMAGE_TOKENS = 85
    HIGH_DETAIL_TILE_TOKENS = 170

    # Image processing constants
    MAX_SIZE = 2048
    HIGH_DETAIL_TARGET_SHORT_SIDE = 768
    TILE_SIZE = 512

    def __init__(self, tokenizer):
        self.tokenizer = tokenizer

    def count_text(self, text: str) -> int:
        """Calculate tokens for a text string"""
        return 0 if not text else len(self.tokenizer.encode(text))

    def count_image(self, image_item: dict) -> int:
        """
        Calculate tokens for an image based on detail level and dimensions

        For "low" detail: fixed 85 tokens
        For "high" detail:
        1. Scale to fit in 2048x2048 square
        2. Scale shortest side to 768px
        3. Count 512px tiles (170 tokens each)
        4. Add 85 tokens
        """
        detail = image_item.get("detail", "medium")

        # For low detail, always return fixed token count
        if detail == "low":
            return self.LOW_DETAIL_IMAGE_TOKENS

        # For medium detail (default in OpenAI), use high detail calculation
        # OpenAI doesn't specify a separate calculation for medium

        # For high detail, calculate based on dimensions if available
        if detail == "high" or detail == "medium":
            # If dimensions are provided in the image_item
            if "dimensions" in image_item:
                width, height = image_item["dimensions"]
                return self._calculate_high_detail_tokens(width, height)

        return (
            self._calculate_high_detail_tokens(1024, 1024) if detail == "high" else 1024
        )

    def _calculate_high_detail_tokens(self, width: int, height: int) -> int:
        """Calculate tokens for high detail images based on dimensions"""
        # Step 1: Scale to fit in MAX_SIZE x MAX_SIZE square
        if width > self.MAX_SIZE or height > self.MAX_SIZE:
            scale = self.MAX_SIZE / max(width, height)
            width = int(width * scale)
            height = int(height * scale)

        # Step 2: Scale so shortest side is HIGH_DETAIL_TARGET_SHORT_SIDE
        scale = self.HIGH_DETAIL_TARGET_SHORT_SIDE / min(width, height)
        scaled_width = int(width * scale)
        scaled_height = int(height * scale)

        # Step 3: Count number of 512px tiles
        tiles_x = math.ceil(scaled_width / self.TILE_SIZE)
        tiles_y = math.ceil(scaled_height / self.TILE_SIZE)
        total_tiles = tiles_x * tiles_y

        # Step 4: Calculate final token count
        return (
            total_tiles * self.HIGH_DETAIL_TILE_TOKENS
        ) + self.LOW_DETAIL_IMAGE_TOKENS

    def count_content(self, content: Union[str, List[Union[str, dict]]]) -> int:
        """Calculate tokens for message content"""
        if not content:
            return 0

        if isinstance(content, str):
            return self.count_text(content)

        token_count = 0
        for item in content:
            if isinstance(item, str):
                token_count += self.count_text(item)
            elif isinstance(item, dict):
                if "text" in item:
                    token_count += self.count_text(item["text"])
                elif "image_url" in item:
                    token_count += self.count_image(item)
        return token_count

    def count_tool_calls(self, tool_calls: List[dict]) -> int:
        """Calculate tokens for tool calls"""
        token_count = 0
        for tool_call in tool_calls:
            if "function" in tool_call:
                function = tool_call["function"]
                token_count += self.count_text(function.get("name", ""))
                token_count += self.count_text(function.get("arguments", ""))
        return token_count

    def count_message_tokens(self, messages: List[dict]) -> int:
        """Calculate the total number of tokens in a message list"""
        total_tokens = self.FORMAT_TOKENS  # Base format tokens

        for message in messages:
            tokens = self.BASE_MESSAGE_TOKENS  # Base tokens per message

            # Add role tokens
            tokens += self.count_text(message.get("role", ""))

            # Add content tokens
            if "content" in message:
                tokens += self.count_content(message["content"])

            # Add tool calls tokens
            if "tool_calls" in message:
                tokens += self.count_tool_calls(message["tool_calls"])

            # Add name and tool_call_id tokens
            tokens += self.count_text(message.get("name", ""))
            tokens += self.count_text(message.get("tool_call_id", ""))

            total_tokens += tokens

        return total_tokens


class LLM:
    _instances: Dict[str, "LLM"] = {}

    def __new__(
        cls, config_name: str = "default", llm_config: Optional[LLMSettings] = None
    ):
        if config_name not in cls._instances:
            instance = super().__new__(cls)
            instance.__init__(config_name, llm_config)
            cls._instances[config_name] = instance
        return cls._instances[config_name]

    @classmethod
    def create_isolated(
        cls, config_name: str = "default", llm_config: Optional[LLMSettings] = None
    ) -> "LLM":
        """Create a fresh, session-isolated LLM instance without touching _instances."""
        instance = super().__new__(cls)
        instance.__init__(config_name, llm_config)
        return instance

    def __init__(
        self, config_name: str = "default", llm_config: Optional[LLMSettings] = None
    ):
        if not hasattr(self, "client"):  # Only initialize if not already initialized
            llm_config = llm_config or config.llm
            llm_config = llm_config.get(config_name, llm_config["default"])
            self.model = llm_config.model
            self.max_tokens = llm_config.max_tokens
            # 供应商特有请求参数(如 DashScope enable_thinking=false: 推理模型
            # 关闭思考模式才支持 tool_choice=required)，经 openai SDK extra_body 透传
            self.extra_body = getattr(llm_config, "extra_body", None) or None
            self.temperature = llm_config.temperature
            self.api_type = llm_config.api_type
            self.api_key = llm_config.api_key
            self.api_version = llm_config.api_version
            self.base_url = llm_config.base_url

            # Add token counting related attributes
            self.total_input_tokens = 0
            self.total_completion_tokens = 0
            self.max_input_tokens = (
                llm_config.max_input_tokens
                if hasattr(llm_config, "max_input_tokens")
                else None
            )

            # Initialize tokenizer with cache + proxy guard
            self.tokenizer = _get_tiktoken_encoding(self.model)

            if self.api_type == "azure":
                self.client = AsyncAzureOpenAI(
                    base_url=self.base_url,
                    api_key=self.api_key,
                    api_version=self.api_version,
                )
            elif self.api_type == "aws":
                self.client = BedrockClient()
            else:
                # 配置超时和重试，解决 APIConnectionError
                timeout = httpx.Timeout(
                    connect=30.0,  # 连接超时 30 秒
                    read=300.0,    # 读取超时 300 秒（5 分钟）
                    write=30.0,    # 写入超时 30 秒
                    pool=30.0,      # 连接池超时 30 秒
                )
                self.client = AsyncOpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url,
                    timeout=timeout,
                    max_retries=3,  # 最大重试 3 次
                )

            if self.tokenizer is not None:
                self.token_counter = TokenCounter(self.tokenizer)
            else:
                self.token_counter = None

    def update_model(
        self,
        model: str,
        base_url: str,
        api_key: str,
        extra_body: Optional[dict] = None,
    ) -> None:
        """运行时切换模型 + 通道（base_url / api_key / client 全部重建）。

        用于 agent 对话按用户选择的模型动态切通道：
        - deepseek-* / qwen-* → DashScope
        - claude-* → RuoLi 中转

        extra_body 随模型切换（如 deepseek-flash 需 thinking.type=disabled
        才支持 tool_choice=required；其它模型不带该参数，避免误传 400）。
        注意：DashScope 时代的 enable_thinking=false 在 DeepSeek 官方端被静默忽略。

        ask / ask_tool / ask_tool_stream 每次调用读 self.model 和 self.client，
        所以切换后下一次调用即时生效。
        """
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.extra_body = extra_body or None
        timeout = httpx.Timeout(
            connect=30.0, read=300.0, write=30.0, pool=30.0,
        )
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=3,
        )

    def count_tokens(self, text: str) -> int:
        """Calculate the number of tokens in a text"""
        if not text:
            return 0
        if self.tokenizer is None:
            return 0
        return len(self.tokenizer.encode(text))

    def count_message_tokens(self, messages: List[dict]) -> int:
        if self.token_counter is None:
            return 0
        return self.token_counter.count_message_tokens(messages)

    def count_tool_calls(self, tool_calls: List[dict]) -> int:
        """Calculate tokens consumed by tool call payloads."""
        if self.token_counter is None:
            return 0
        return self.token_counter.count_tool_calls(tool_calls)

    def update_token_count(self, input_tokens: int, completion_tokens: int = 0) -> None:
        """Update token counts"""
        # Only track tokens if max_input_tokens is set
        self.total_input_tokens += input_tokens
        self.total_completion_tokens += completion_tokens
        logger.info(
            f"Token usage: Input={input_tokens}, Completion={completion_tokens}, "
            f"Cumulative Input={self.total_input_tokens}, Cumulative Completion={self.total_completion_tokens}, "
            f"Total={input_tokens + completion_tokens}, Cumulative Total={self.total_input_tokens + self.total_completion_tokens}"
        )

    def check_token_limit(self, input_tokens: int) -> bool:
        """Check if token limits are exceeded"""
        if self.max_input_tokens is not None:
            return (self.total_input_tokens + input_tokens) <= self.max_input_tokens
        # If max_input_tokens is not set, always return True
        return True

    def get_limit_error_message(self, input_tokens: int) -> str:
        """Generate error message for token limit exceeded"""
        if (
            self.max_input_tokens is not None
            and (self.total_input_tokens + input_tokens) > self.max_input_tokens
        ):
            return f"Request may exceed input token limit (Current: {self.total_input_tokens}, Needed: {input_tokens}, Max: {self.max_input_tokens})"

        return "Token limit exceeded"

    @staticmethod
    def format_messages(
        messages: List[Union[dict, Message]], supports_images: bool = False
    ) -> List[dict]:
        """
        Format messages for LLM by converting them to OpenAI message format.

        ✅ 复刻 LangChain 上下文机制：
        1. 保留所有 AIMessage（含 tool_calls）
        2. 保留所有 ToolMessage（通过 tool_call_id 关联）
        3. LLM 能看到完整的工具调用历史，避免重复调用工具

        OpenAI API 要求: tool_calls 后面必须紧跟对应的 tool 消息（通过 tool_call_id 匹配）

        Args:
            messages: List of messages that can be either dict or Message objects
            supports_images: Flag indicating if the target model supports image inputs

        Returns:
            List[dict]: List of formatted messages in OpenAI format

        Raises:
            ValueError: If messages are invalid or missing required fields
            TypeError: If unsupported message types are provided

        Examples:
            >>> msgs = [
            ...     Message.system_message("You are a helpful assistant"),
            ...     {"role": "user", "content": "Hello"},
            ...     Message.user_message("How are you?")
            ... ]
            >>> formatted = LLM.format_messages(msgs)
        """
        formatted_messages = []

        # 🔍 DEBUG: 记录输入消息
        logger.debug("=" * 80)
        logger.debug(f"🔍 [DEBUG] format_messages() - 输入消息 (共 {len(messages)} 条):")
        for i, msg in enumerate(messages):
            if isinstance(msg, Message):
                role = msg.role.value if hasattr(msg.role, 'value') else str(msg.role)
                content_preview = (msg.content[:100] if msg.content else '')
                tool_calls_info = f" [tool_calls: {len(msg.tool_calls)}]" if msg.tool_calls else ""
                tool_call_id_info = f" [tool_call_id: {msg.tool_call_id}]" if msg.tool_call_id else ""
                logger.debug(f"  [{i}] {role}{tool_calls_info}{tool_call_id_info}: {content_preview}...")
            elif isinstance(msg, dict):
                role = msg.get('role', 'unknown')
                content_preview = (msg.get('content', '')[:100] if msg.get('content') else '')
                tool_calls_info = f" [tool_calls: {len(msg.get('tool_calls', []))}]" if msg.get('tool_calls') else ""
                tool_call_id_info = f" [tool_call_id: {msg.get('tool_call_id')}]" if msg.get('tool_call_id') else ""
                logger.debug(f"  [{i}] {role}{tool_calls_info}{tool_call_id_info}: {content_preview}...")

        for message in messages:
            # Convert Message objects to dictionaries
            if isinstance(message, Message):
                message = message.to_dict()

            if isinstance(message, dict):
                # If message is a dict, ensure it has required fields
                if "role" not in message:
                    raise ValueError("Message dict must contain 'role' field")

                # Create a copy to avoid modifying the original
                message = message.copy()

                # ✅ 保留 tool 消息 - LLM 需要看到工具执行结果
                # ✅ 保留 assistant 消息的 tool_calls - LLM 需要知道已调用的工具

                # Remove internal base64_image field (not part of OpenAI API)
                if "base64_image" in message:
                    # Process base64 images if present and model supports images
                    if supports_images and message.get("base64_image"):
                        # Initialize or convert content to appropriate format
                        if not message.get("content"):
                            message["content"] = []
                        elif isinstance(message["content"], str):
                            message["content"] = [
                                {"type": "text", "text": message["content"]}
                            ]
                        elif isinstance(message["content"], list):
                            # Convert string items to proper text objects
                            message["content"] = [
                                (
                                    {"type": "text", "text": item}
                                    if isinstance(item, str)
                                    else item
                                )
                                for item in message["content"]
                            ]

                        # Add the image to content
                        message["content"].append(
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{message['base64_image']}"
                                },
                            }
                        )
                    # Remove the base64_image field
                    del message["base64_image"]

                # Add message if it has content or tool_calls or is a tool message
                if ("content" in message and message["content"]) or message.get("tool_calls") or message.get("role") == "tool":
                    formatted_messages.append(message)
                    # 🔍 DEBUG: 记录被添加的消息
                    if message.get("role") == "tool":
                        logger.debug(f"  ✅ 添加 tool 消息: tool_call_id={message.get('tool_call_id')}, content长度={len(str(message.get('content', '')))}")
                # else: do not include the message
            else:
                raise TypeError(f"Unsupported message type: {type(message)}")

        # Validate all messages have required fields
        for msg in formatted_messages:
            if msg["role"] not in ROLE_VALUES:
                raise ValueError(f"Invalid role: {msg['role']}")

        # Remove orphan tool messages (tool role without preceding assistant+tool_calls).
        # Also deduplicate: duplicate assistant+tool_calls and duplicate tool messages
        # both cause API rejections on Doubao/Ark with "No tool calls but found tool output".
        valid_tool_call_ids: set[str] = set()
        for msg in formatted_messages:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                    if tc_id:
                        valid_tool_call_ids.add(tc_id)
        # Deduplicate assistant messages that share the same tool_call_ids (keep last only,
        # since the last one will have a matching tool response after dedup).
        seen_assistant_call_sets: list[frozenset] = []
        deduped_assistant: list[dict] = []
        for msg in formatted_messages:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                tc_ids = frozenset(
                    (tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None))
                    for tc in msg["tool_calls"]
                )
                if tc_ids in seen_assistant_call_sets:
                    logger.warning(f"[LLM] Dropping duplicate assistant+tool_calls message tc_ids={tc_ids}")
                    continue
                seen_assistant_call_sets.append(tc_ids)
            deduped_assistant.append(msg)
        formatted_messages = deduped_assistant
        # Deduplicate tool messages with the same tool_call_id (keep first occurrence only).
        seen_tool_call_ids: set[str] = set()
        cleaned: list[dict] = []
        for msg in formatted_messages:
            if msg.get("role") == "tool":
                tc_id = msg.get("tool_call_id")
                if not tc_id or tc_id not in valid_tool_call_ids:
                    logger.warning(f"[LLM] Dropping orphan tool message tool_call_id={tc_id}")
                    continue
                if tc_id in seen_tool_call_ids:
                    logger.warning(f"[LLM] Dropping duplicate tool message tool_call_id={tc_id}")
                    continue
                seen_tool_call_ids.add(tc_id)
            cleaned.append(msg)
        formatted_messages = cleaned

        # 🔍 DEBUG: 记录格式化后的消息
        logger.debug(f"🔍 [DEBUG] format_messages() - 格式化后消息 (共 {len(formatted_messages)} 条):")
        for i, msg in enumerate(formatted_messages):
            role = msg.get('role', 'unknown')
            content_preview = (msg.get('content', '')[:100] if msg.get('content') else '')
            tool_calls_info = f" [tool_calls: {len(msg.get('tool_calls', []))}]" if msg.get('tool_calls') else ""
            tool_call_id_info = f" [tool_call_id: {msg.get('tool_call_id')}]" if msg.get('tool_call_id') else ""
            logger.debug(f"  [{i}] {role}{tool_calls_info}{tool_call_id_info}: {content_preview}...")
        logger.debug("=" * 80)

        return formatted_messages

    @retry(
        wait=wait_random_exponential(min=1, max=10),  # 优化：缩短等待时间
        stop=stop_after_attempt(3),  # 优化：减少重试次数
        retry=retry_if_exception_type(
            (OpenAIError, Exception, ValueError)
        ),  # Don't retry TokenLimitExceeded
    )
    async def ask(
        self,
        messages: List[Union[dict, Message]],
        system_msgs: Optional[List[Union[dict, Message]]] = None,
        stream: bool = True,
        temperature: Optional[float] = None,
    ) -> str:
        """
        Send a prompt to the LLM and get the response.

        Args:
            messages: List of conversation messages
            system_msgs: Optional system messages to prepend
            stream (bool): Whether to stream the response
            temperature (float): Sampling temperature for the response

        Returns:
            str: The generated response

        Raises:
            TokenLimitExceeded: If token limits are exceeded
            ValueError: If messages are invalid or response is empty
            OpenAIError: If API call fails after retries
            Exception: For unexpected errors
        """
        try:
            # Check if the model supports images
            supports_images = self.model in MULTIMODAL_MODELS

            # Format system and user messages with image support check
            if system_msgs:
                system_msgs = self.format_messages(system_msgs, supports_images)
                messages = system_msgs + self.format_messages(messages, supports_images)
            else:
                messages = self.format_messages(messages, supports_images)

            # Calculate input token count
            input_tokens = self.count_message_tokens(messages)

            # Check if token limits are exceeded
            if not self.check_token_limit(input_tokens):
                error_message = self.get_limit_error_message(input_tokens)
                # Raise a special exception that won't be retried
                raise TokenLimitExceeded(error_message)

            params = {
                "model": self.model,
                **({"extra_body": self.extra_body} if self.extra_body else {}),
                "messages": messages,
            }

            if self.model in REASONING_MODELS:
                params["max_completion_tokens"] = self.max_tokens
            else:
                params["max_tokens"] = self.max_tokens
                params["temperature"] = (
                    temperature if temperature is not None else self.temperature
                )

            if not stream:
                # Non-streaming request
                response = await self.client.chat.completions.create(
                    **params, stream=False
                )

                if not response.choices or not response.choices[0].message.content:
                    raise ValueError("Empty or invalid response from LLM")

                # Update token counts
                self.update_token_count(
                    response.usage.prompt_tokens, response.usage.completion_tokens
                )

                return response.choices[0].message.content

            # Streaming request, For streaming, update estimated token count before making the request
            self.update_token_count(input_tokens)

            response = await self.client.chat.completions.create(**params, stream=True)

            collected_messages = []
            completion_text = ""
            async for chunk in response:
                chunk_message = chunk.choices[0].delta.content or ""
                collected_messages.append(chunk_message)
                completion_text += chunk_message
                print(chunk_message, end="", flush=True)

            print()  # Newline after streaming
            full_response = "".join(collected_messages).strip()
            if not full_response:
                raise ValueError("Empty response from streaming LLM")

            # estimate completion tokens for streaming response
            completion_tokens = self.count_tokens(completion_text)
            logger.info(
                f"Estimated completion tokens for streaming response: {completion_tokens}"
            )
            self.total_completion_tokens += completion_tokens

            return full_response

        except TokenLimitExceeded:
            # Re-raise token limit errors without logging
            raise
        except ValueError:
            logger.exception(f"Validation error")
            raise
        except OpenAIError as oe:
            logger.exception(f"OpenAI API error")
            if isinstance(oe, APIConnectionError):
                logger.error(f"API connection failed: {oe}. Check network connection and API endpoint.")
                logger.error(f"Base URL: {self.base_url}, Model: {self.model}")
            elif isinstance(oe, AuthenticationError):
                logger.error("Authentication failed. Check API key.")
            elif isinstance(oe, RateLimitError):
                logger.error("Rate limit exceeded. Consider increasing retry attempts.")
            elif isinstance(oe, APIError):
                logger.error(f"API error: {oe}")
            raise
        except Exception:
            logger.exception(f"Unexpected error in ask")
            raise

    @retry(
        wait=wait_random_exponential(min=1, max=10),  # 优化：缩短等待时间
        stop=stop_after_attempt(3),  # 优化：减少重试次数
        retry=retry_if_exception_type(
            (OpenAIError, Exception, ValueError)
        ),  # Don't retry TokenLimitExceeded
    )
    async def ask_with_images(
        self,
        messages: List[Union[dict, Message]],
        images: List[Union[str, dict]],
        system_msgs: Optional[List[Union[dict, Message]]] = None,
        stream: bool = False,
        temperature: Optional[float] = None,
    ) -> str:
        """
        Send a prompt with images to the LLM and get the response.

        Args:
            messages: List of conversation messages
            images: List of image URLs or image data dictionaries
            system_msgs: Optional system messages to prepend
            stream (bool): Whether to stream the response
            temperature (float): Sampling temperature for the response

        Returns:
            str: The generated response

        Raises:
            TokenLimitExceeded: If token limits are exceeded
            ValueError: If messages are invalid or response is empty
            OpenAIError: If API call fails after retries
            Exception: For unexpected errors
        """
        try:
            # For ask_with_images, we always set supports_images to True because
            # this method should only be called with models that support images
            if self.model not in MULTIMODAL_MODELS:
                raise ValueError(
                    f"Model {self.model} does not support images. Use a model from {MULTIMODAL_MODELS}"
                )

            # Format messages with image support
            formatted_messages = self.format_messages(messages, supports_images=True)

            # Ensure the last message is from the user to attach images
            if not formatted_messages or formatted_messages[-1]["role"] != "user":
                raise ValueError(
                    "The last message must be from the user to attach images"
                )

            # Process the last user message to include images
            last_message = formatted_messages[-1]

            # Convert content to multimodal format if needed
            content = last_message["content"]
            multimodal_content = (
                [{"type": "text", "text": content}]
                if isinstance(content, str)
                else content
                if isinstance(content, list)
                else []
            )

            # Add images to content
            for image in images:
                if isinstance(image, str):
                    multimodal_content.append(
                        {"type": "image_url", "image_url": {"url": image}}
                    )
                elif isinstance(image, dict) and "url" in image:
                    multimodal_content.append({"type": "image_url", "image_url": image})
                elif isinstance(image, dict) and "image_url" in image:
                    multimodal_content.append(image)
                else:
                    raise ValueError(f"Unsupported image format: {image}")

            # Update the message with multimodal content
            last_message["content"] = multimodal_content

            # Add system messages if provided
            if system_msgs:
                all_messages = (
                    self.format_messages(system_msgs, supports_images=True)
                    + formatted_messages
                )
            else:
                all_messages = formatted_messages

            # Calculate tokens and check limits
            input_tokens = self.count_message_tokens(all_messages)
            if not self.check_token_limit(input_tokens):
                raise TokenLimitExceeded(self.get_limit_error_message(input_tokens))

            # Set up API parameters
            params = {
                "model": self.model,
                **({"extra_body": self.extra_body} if self.extra_body else {}),
                "messages": all_messages,
                "stream": stream,
            }

            # Add model-specific parameters
            if self.model in REASONING_MODELS:
                params["max_completion_tokens"] = self.max_tokens
            else:
                params["max_tokens"] = self.max_tokens
                params["temperature"] = (
                    temperature if temperature is not None else self.temperature
                )

            # Handle non-streaming request
            if not stream:
                response = await self.client.chat.completions.create(**params)

                if not response.choices or not response.choices[0].message.content:
                    raise ValueError("Empty or invalid response from LLM")

                self.update_token_count(response.usage.prompt_tokens)
                return response.choices[0].message.content

            # Handle streaming request
            self.update_token_count(input_tokens)
            response = await self.client.chat.completions.create(**params)

            collected_messages = []
            async for chunk in response:
                chunk_message = chunk.choices[0].delta.content or ""
                collected_messages.append(chunk_message)
                print(chunk_message, end="", flush=True)

            print()  # Newline after streaming
            full_response = "".join(collected_messages).strip()

            if not full_response:
                raise ValueError("Empty response from streaming LLM")

            return full_response

        except TokenLimitExceeded:
            raise
        except ValueError as ve:
            logger.error(f"Validation error in ask_with_images: {ve}")
            raise
        except OpenAIError as oe:
            logger.error(f"OpenAI API error: {oe}")
            if isinstance(oe, APIConnectionError):
                logger.error(f"API connection failed: {oe}. Check network connection and API endpoint.")
                logger.error(f"Base URL: {self.base_url}, Model: {self.model}")
            elif isinstance(oe, AuthenticationError):
                logger.error("Authentication failed. Check API key.")
            elif isinstance(oe, RateLimitError):
                logger.error("Rate limit exceeded. Consider increasing retry attempts.")
            elif isinstance(oe, APIError):
                logger.error(f"API error: {oe}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in ask_with_images: {e}")
            raise

    @retry(
        wait=wait_random_exponential(min=1, max=10),  # 优化：缩短等待时间
        stop=stop_after_attempt(3),  # 优化：减少重试次数
        retry=retry_if_exception_type(
            (OpenAIError, Exception, ValueError)
        ),  # Don't retry TokenLimitExceeded
    )
    async def ask_tool(
        self,
        messages: List[Union[dict, Message]],
        system_msgs: Optional[List[Union[dict, Message]]] = None,
        timeout: int = 300,
        tools: Optional[List[dict]] = None,
        tool_choice: TOOL_CHOICE_TYPE = ToolChoice.AUTO,  # type: ignore
        temperature: Optional[float] = None,
        **kwargs,
    ) -> ChatCompletionMessage | None:
        """
        Ask LLM using functions/tools and return the response.

        Args:
            messages: List of conversation messages
            system_msgs: Optional system messages to prepend
            timeout: Request timeout in seconds
            tools: List of tools to use
            tool_choice: Tool choice strategy
            temperature: Sampling temperature for the response
            **kwargs: Additional completion arguments

        Returns:
            ChatCompletionMessage: The model's response

        Raises:
            TokenLimitExceeded: If token limits are exceeded
            ValueError: If tools, tool_choice, or messages are invalid
            OpenAIError: If API call fails after retries
            Exception: For unexpected errors
        """
        try:
            # Validate tool_choice
            if tool_choice not in TOOL_CHOICE_VALUES:
                raise ValueError(f"Invalid tool_choice: {tool_choice}")

            # Check if the model supports images
            supports_images = self.model in MULTIMODAL_MODELS

            # Format messages
            if system_msgs:
                system_msgs = self.format_messages(system_msgs, supports_images)
                messages = system_msgs + self.format_messages(messages, supports_images)
            else:
                messages = self.format_messages(messages, supports_images)

            # Calculate input token count
            input_tokens = self.count_message_tokens(messages)

            # If there are tools, calculate token count for tool descriptions
            tools_tokens = 0
            if tools:
                for tool in tools:
                    tools_tokens += self.count_tokens(str(tool))

            input_tokens += tools_tokens

            # Check if token limits are exceeded
            if not self.check_token_limit(input_tokens):
                error_message = self.get_limit_error_message(input_tokens)
                # Raise a special exception that won't be retried
                raise TokenLimitExceeded(error_message)

            # Validate tools if provided
            if tools:
                for tool in tools:
                    if not isinstance(tool, dict) or "type" not in tool:
                        raise ValueError("Each tool must be a dict with 'type' field")

            # Set up the completion request
            params = {
                "model": self.model,
                **({"extra_body": self.extra_body} if self.extra_body else {}),
                "messages": messages,
                "tools": tools,
                "tool_choice": tool_choice,
                "timeout": timeout,
                **kwargs,
            }
            # ReAct 一步一工具:机制级保证,不靠 prompt(见 _one_tool_per_step_enabled)
            if tools and _one_tool_per_step_enabled():
                params["parallel_tool_calls"] = False

            if self.model in REASONING_MODELS:
                params["max_completion_tokens"] = self.max_tokens
            else:
                params["max_tokens"] = self.max_tokens
                params["temperature"] = (
                    temperature if temperature is not None else self.temperature
                )

            params["stream"] = False  # Always use non-streaming for tool requests
            response: ChatCompletion = await self.client.chat.completions.create(
                **params
            )

            # Check if response is valid
            if not response.choices or not response.choices[0].message:
                print(response)
                # raise ValueError("Invalid or empty response from LLM")
                return None

            # Update token counts
            self.update_token_count(
                response.usage.prompt_tokens, response.usage.completion_tokens
            )

            return response.choices[0].message

        except TokenLimitExceeded:
            # Re-raise token limit errors without logging
            raise
        except ValueError as ve:
            logger.error(f"Validation error in ask_tool: {ve}")
            raise
        except OpenAIError as oe:
            logger.error(f"OpenAI API error: {oe}")
            if isinstance(oe, APIConnectionError):
                logger.error(f"API connection failed: {oe}. Check network connection and API endpoint.")
                logger.error(f"Base URL: {self.base_url}, Model: {self.model}")
            elif isinstance(oe, AuthenticationError):
                logger.error("Authentication failed. Check API key.")
            elif isinstance(oe, RateLimitError):
                logger.error("Rate limit exceeded. Consider increasing retry attempts.")
            elif isinstance(oe, APIError):
                logger.error(f"API error: {oe}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in ask_tool: {e}")
            raise

    @staticmethod
    def _build_chat_completion_message(payload: dict) -> ChatCompletionMessage:
        """Build ChatCompletionMessage in a version-compatible way."""
        try:
            return ChatCompletionMessage.model_validate(payload)
        except AttributeError:
            return ChatCompletionMessage(**payload)

    async def stream_tool_response(
        self,
        messages: List[Union[dict, Message]],
        system_msgs: Optional[List[Union[dict, Message]]] = None,
        timeout: int = 300,
        tools: Optional[List[dict]] = None,
        tool_choice: TOOL_CHOICE_TYPE = ToolChoice.AUTO,  # type: ignore
        temperature: Optional[float] = None,
        cancel_event: Optional[asyncio.Event] = None,
        **kwargs,
    ) -> AsyncIterator[AssistantChunk]:
        """Yield provider-neutral assistant chunks without an intermediary queue."""
        try:
            if tool_choice not in TOOL_CHOICE_VALUES:
                raise ValueError(f"Invalid tool_choice: {tool_choice}")

            supports_images = self.model in MULTIMODAL_MODELS
            if system_msgs:
                system_msgs = self.format_messages(system_msgs, supports_images)
                messages = system_msgs + self.format_messages(messages, supports_images)
            else:
                messages = self.format_messages(messages, supports_images)

            input_tokens = self.count_message_tokens(messages)
            if tools:
                for tool in tools:
                    if not isinstance(tool, dict) or "type" not in tool:
                        raise ValueError("Each tool must be a dict with 'type' field")
                    input_tokens += self.count_tokens(str(tool))

            if not self.check_token_limit(input_tokens):
                raise TokenLimitExceeded(self.get_limit_error_message(input_tokens))

            params = {
                "model": self.model,
                **({"extra_body": self.extra_body} if self.extra_body else {}),
                "messages": messages,
                "tools": tools,
                "tool_choice": tool_choice,
                "timeout": timeout,
                "stream": True,
                **kwargs,
            }
            if tools and _one_tool_per_step_enabled():
                params["parallel_tool_calls"] = False

            if self.model in REASONING_MODELS:
                params["max_completion_tokens"] = self.max_tokens
            else:
                params["max_tokens"] = self.max_tokens
                params["temperature"] = (
                    temperature if temperature is not None else self.temperature
                )

            self.update_token_count(input_tokens)
            stream = await self.client.chat.completions.create(**params)

            finish_reason: Optional[str] = None
            content = ""
            thinking = ""
            assembler = ToolCallAssembler()

            async for chunk in stream:
                if cancel_event and cancel_event.is_set():
                    raise asyncio.CancelledError("Cancelled while streaming tool response")
                if not chunk.choices:
                    continue

                choice = chunk.choices[0]
                if choice.finish_reason:
                    finish_reason = choice.finish_reason

                delta = choice.delta
                if delta is None:
                    continue

                piece = getattr(delta, "content", None)
                if piece:
                    content += piece
                    yield AssistantChunk(kind="text_delta", content=piece)

                thinking_piece = (
                    getattr(delta, "reasoning_content", None)
                    or getattr(delta, "reasoning", None)
                    or getattr(delta, "thinking", None)
                )
                if thinking_piece:
                    thinking += thinking_piece
                    yield AssistantChunk(kind="thinking_delta", content=thinking_piece)

                tool_call_deltas = getattr(delta, "tool_calls", None)
                if tool_call_deltas:
                    assembler.ingest(tool_call_deltas)

            raw_tool_calls = assembler.build()
            if raw_tool_calls and not assembler.is_ready(finish_reason):
                logger.warning(
                    "Tool calls streamed but assembler is incomplete; "
                    "the execution layer must reject them"
                )

            completion_tokens = self.count_tokens(content) + self.count_tool_calls(raw_tool_calls)
            self.total_completion_tokens += completion_tokens

            core_tool_calls: list[CoreToolCall] = []
            for raw_call in raw_tool_calls:
                raw_arguments = raw_call["function"].get("arguments", "{}")
                try:
                    arguments = json.loads(raw_arguments)
                    if not isinstance(arguments, dict):
                        arguments = {"_raw": raw_arguments}
                except json.JSONDecodeError:
                    arguments = {"_raw": raw_arguments}
                core_tool_calls.append(
                    CoreToolCall(
                        id=raw_call.get("id", ""),
                        name=raw_call["function"].get("name", ""),
                        arguments=arguments,
                    )
                )

            yield AssistantChunk(
                kind="done",
                turn=ModelTurn(
                    content=content,
                    thinking=thinking,
                    tool_calls=tuple(core_tool_calls),
                    stop_reason=finish_reason,
                ),
            )
        except asyncio.CancelledError:
            logger.info("stream_tool_response cancelled")
            raise
        except (TokenLimitExceeded, ValueError):
            raise
        except OpenAIError:
            raise
        except Exception as exc:
            logger.error(f"Unexpected error in stream_tool_response: {exc}")
            raise

    @retry(
        wait=wait_random_exponential(min=1, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((OpenAIError, Exception, ValueError)),
    )
    async def ask_tool_stream(
        self,
        messages: List[Union[dict, Message]],
        system_msgs: Optional[List[Union[dict, Message]]] = None,
        timeout: int = 300,
        tools: Optional[List[dict]] = None,
        tool_choice: TOOL_CHOICE_TYPE = ToolChoice.AUTO,  # type: ignore
        temperature: Optional[float] = None,
        on_content_delta: Optional[Callable[[str], Awaitable[None]]] = None,
        cancel_event: Optional[asyncio.Event] = None,
        **kwargs,
    ) -> ChatCompletionMessage | None:
        """Backward-compatible wrapper around :meth:`stream_tool_response`."""
        completed: ModelTurn | None = None
        async for chunk in self.stream_tool_response(
            messages=messages,
            system_msgs=system_msgs,
            timeout=timeout,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
            cancel_event=cancel_event,
            **kwargs,
        ):
            if chunk.kind == "text_delta" and on_content_delta:
                await on_content_delta(chunk.content)
            elif chunk.kind == "done":
                completed = chunk.turn

        if completed is None:
            return None
        payload: dict = {
            "role": "assistant",
            "content": completed.content if completed.content else None,
            "finish_reason": completed.stop_reason,
        }
        if completed.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in completed.tool_calls
            ]
        return self._build_chat_completion_message(payload)
