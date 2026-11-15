"""
Intent Enhancer - 意图增强器

在 agent 执行前，通过意图识别增强 user query，以引导 agent 使用合适的工具。

参考 AgentIntentEnhancer 实现，适配 resume agent 的工具系统。
"""

import re
from typing import Any, Dict, Optional, Tuple

from backend.core.logger import get_logger

logger = get_logger(__name__)
from backend.agent.domain.intent.intent_classifier import IntentClassifier, IntentResult, IntentType

# 用户显式指定 tool 的正则模式：/[tool:xxx]
EXPLICIT_TOOL_PATTERN = re.compile(r"/\[tool:([^\]]+)\]", re.IGNORECASE)


class AgentIntentEnhancer:
    """
    Agent 意图增强器

    功能：
    1. 在 agent 执行前分析用户 query 的意图
    2. 根据意图匹配结果，在 query 前添加 /[tool:xxx] 标记
    3. 提供意图摘要用于日志和前端展示

    简化设计：
    - 只增强 query（添加 tool 标记），不修改 prompt
    - Agent 通过 /[tool:xxx] 标记知道应该使用哪个工具
    """

    def __init__(
        self,
        classifier: Optional[IntentClassifier] = None,
        use_llm: bool = True,
    ):
        """
        初始化 Agent 意图增强器

        Args:
            classifier: 意图分类器实例（如果提供，会使用提供的实例）
            use_llm: 是否使用 LLM 进行意图分类（默认开启）
        """
        self.classifier = classifier or IntentClassifier(use_llm=use_llm)

    def _has_explicit_tool_tag(self, user_query: str) -> Optional[str]:
        """
        检查用户 query 是否已包含显式 tool 标记

        格式: /[tool:tool-name]

        Returns:
            匹配到的 tool 名称，或 None
        """
        match = EXPLICIT_TOOL_PATTERN.search(user_query)
        if match:
            return match.group(1).strip()
        return None

    def _build_tool_tag(self, tool_name: str) -> str:
        """构建 tool 标记"""
        return f"/[tool:{tool_name}]"

    async def enhance_query(
        self,
        user_query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, Optional[IntentResult]]:
        """
        增强 user query

        Args:
            user_query: 用户输入
            context: 上下文信息

        Returns:
            tuple[str, Optional[IntentResult]]: (增强后的 query, 意图识别结果)
        """
        if not user_query or not user_query.strip():
            return user_query, None

        # 检查是否已有显式 tool 标记，有则跳过意图识别
        explicit_tool = self._has_explicit_tool_tag(user_query)
        if explicit_tool:
            logger.debug(f"发现显式工具标记: {explicit_tool}，跳过意图识别")
            return user_query, None

        try:
            # 进行意图识别
            intent_result = await self.classifier.classify(user_query, context)

            logger.debug(
                f"意图识别: type={intent_result.intent_type.value}, "
                f"tools={intent_result.matched_tools}, "
                f"confidence={intent_result.confidence:.2f}"
            )

            # 如果识别到特定工具，在 query 前添加 tool 标记
            if intent_result.intent_type == IntentType.TOOL_SPECIFIC:
                if intent_result.matched_tools:
                    top_tool = intent_result.matched_tools[0]
                    enhanced_query = f"{self._build_tool_tag(top_tool)} {user_query}"
                    logger.info(f"增强查询: {enhanced_query}")
                    return enhanced_query, intent_result

            return user_query, intent_result

        except Exception as e:
            logger.warning(f"意图增强失败: {e}")
            return user_query, None

    def enhance_query_sync(
        self,
        user_query: str,
    ) -> Tuple[str, Optional[IntentResult]]:
        """
        同步增强 user query（仅使用规则，不调用 LLM）

        Args:
            user_query: 用户输入

        Returns:
            tuple[str, Optional[IntentResult]]: (增强后的 query, 意图识别结果)
        """
        if not user_query or not user_query.strip():
            return user_query, None

        # 检查是否已有显式 tool 标记
        explicit_tool = self._has_explicit_tool_tag(user_query)
        if explicit_tool:
            logger.debug(f"发现显式工具标记: {explicit_tool}，跳过意图识别")
            return user_query, None

        try:
            # 使用同步分类（仅规则匹配）
            intent_result = self.classifier.classify_sync(user_query)

            logger.debug(
                f"同步意图识别: type={intent_result.intent_type.value}, "
                f"tools={intent_result.matched_tools}, "
                f"confidence={intent_result.confidence:.2f}"
            )

            # 如果识别到特定工具，在 query 前添加 tool 标记
            if intent_result.intent_type == IntentType.TOOL_SPECIFIC:
                if intent_result.matched_tools:
                    top_tool = intent_result.matched_tools[0]
                    enhanced_query = f"{self._build_tool_tag(top_tool)} {user_query}"
                    logger.info(f"同步增强查询: {enhanced_query}")
                    return enhanced_query, intent_result

            return user_query, intent_result

        except Exception as e:
            logger.warning(f"同步意图增强失败: {e}")
            return user_query, None










