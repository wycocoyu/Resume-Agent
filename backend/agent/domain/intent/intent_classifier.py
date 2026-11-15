"""
Intent Classifier - 意图分类器

两阶段分类策略：
1. 基于规则的快速匹配（关键词 + 正则）
2. LLM 增强分类（当规则匹配置信度不够时）

参考相关实现，适配 resume agent 的工具系统。
"""

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from backend.core.logger import get_logger

logger = get_logger(__name__)
from backend.agent.domain.intent.rule_matcher import RuleMatcher
from backend.agent.domain.intent.tool_registry import ToolRegistry, get_tool_registry
from backend.agent.domain.intent.weights import IntentScoreWeights


class IntentType(Enum):
    """意图类型"""

    TOOL_SPECIFIC = "tool_specific"  # 明确需要某个工具
    GENERAL_CHAT = "general_chat"    # 普通对话（问候、闲聊）
    GREETING = "greeting"            # 问候（特殊处理）
    UNKNOWN = "unknown"              # 未知意图


@dataclass
class IntentResult:
    """意图识别结果"""

    intent_type: IntentType
    # 匹配的工具名称（如果有）
    matched_tools: List[str] = None
    # 置信度 (0.0-1.0)
    confidence: float = 0.0
    # 推理过程
    reasoning: str = ""

    def __post_init__(self):
        if self.matched_tools is None:
            self.matched_tools = []


class IntentClassifier:
    """
    意图分类器

    采用两阶段分类策略：
    1. 基于规则的快速匹配（关键词 + 正则）
    2. LLM 增强分类（当规则匹配置信度不够时）
    """

    # 置信度阈值
    HIGH_CONFIDENCE_THRESHOLD = 0.7  # 高置信度，直接使用规则结果
    MIN_CONFIDENCE_THRESHOLD = 0.3   # 最低置信度，低于此值不考虑

    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
        rule_matcher: Optional[RuleMatcher] = None,
        weights: Optional[IntentScoreWeights] = None,
        use_llm: bool = True,
        llm_client = None,
    ):
        """
        初始化意图分类器

        Args:
            registry: 工具注册表
            rule_matcher: 规则匹配器（如果提供，会使用提供的实例）
            weights: 评分权重配置
            use_llm: 是否使用 LLM 进行增强分类
            llm_client: LLM 客户端（用于增强分类）
        """
        self.registry = registry or get_tool_registry()
        self.weights = weights or IntentScoreWeights()
        self.use_llm = use_llm
        self.llm_client = llm_client

        # 创建规则匹配器
        if rule_matcher:
            self.rule_matcher = rule_matcher
        else:
            self.rule_matcher = RuleMatcher(
                registry=self.registry,
                weights=self.weights,
                min_confidence=self.MIN_CONFIDENCE_THRESHOLD
            )

    def classify_sync(self, query: str) -> IntentResult:
        """
        同步分类（仅使用规则，不调用 LLM）

        Args:
            query: 用户输入

        Returns:
            IntentResult: 意图识别结果
        """
        if not query or not query.strip():
            return IntentResult(
                intent_type=IntentType.GENERAL_CHAT,
                reasoning="Empty query",
            )

        # 检查是否是问候
        if self._is_greeting(query):
            return IntentResult(
                intent_type=IntentType.GREETING,
                confidence=0.95,
                reasoning="Detected greeting pattern",
            )

        # 基于规则的快速匹配
        rule_matches = self.rule_matcher.match(query)

        if rule_matches:
            return self._build_result(rule_matches, "rule_match")

        # 无匹配
        return IntentResult(
            intent_type=IntentType.GENERAL_CHAT,
            reasoning="No tool matched",
        )

    async def classify(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> IntentResult:
        """
        对用户 query 进行意图分类（异步，支持 LLM 增强）

        Args:
            query: 用户输入
            context: 上下文信息（历史对话、附件、模式等）

        Returns:
            IntentResult: 意图识别结果
        """
        if not query or not query.strip():
            return IntentResult(
                intent_type=IntentType.GENERAL_CHAT,
                reasoning="Empty query",
            )

        # Step 1: 检查是否是问候
        if self._is_greeting(query):
            return IntentResult(
                intent_type=IntentType.GREETING,
                confidence=0.95,
                reasoning="Detected greeting pattern",
            )

        # Step 2: 基于规则的快速匹配
        rule_matches = self.rule_matcher.match(query)

        logger.debug(f"规则匹配结果: {rule_matches}")

        # Step 3: 判断是否需要 LLM 增强
        if rule_matches and rule_matches[0][1] >= self.HIGH_CONFIDENCE_THRESHOLD:
            # 高置信度，直接使用规则结果
            return self._build_result(rule_matches, "high_confidence_rule_match")

        # Step 4: 使用 LLM 增强分类（如果启用）
        if self.use_llm and self.llm_client:
            if not rule_matches or rule_matches[0][1] < self.HIGH_CONFIDENCE_THRESHOLD:
                try:
                    llm_result = await self._llm_classify(query, rule_matches, context)
                    return llm_result
                except Exception as e:
                    logger.warning(f"LLM 分类失败，回退到规则匹配: {e}")

        # Step 5: 回退到规则结果
        if rule_matches:
            return self._build_result(rule_matches, "rule_match_fallback")

        # 无匹配
        return IntentResult(
            intent_type=IntentType.GENERAL_CHAT,
            reasoning="No tool matched",
        )

    def _is_greeting(self, query: str) -> bool:
        """检查是否是问候语"""
        query_lower = query.strip().lower()

        # 中文问候
        chinese_greetings = {
            "你好", "您好", "hello", "hi", "hey",
            "早上好", "下午好", "晚上好",
            "再见", "拜拜", "bye",
            "谢谢", "感谢", "thanks", "thank you",
        }

        # 简单检查：如果查询很短且匹配问候词，认为是问候
        if len(query_lower) <= 20:
            for greeting in chinese_greetings:
                if greeting in query_lower:
                    return True

        return False

    def _build_result(
        self,
        rule_matches: List[tuple],
        reasoning_prefix: str = ""
    ) -> IntentResult:
        """从规则匹配结果构建 IntentResult"""
        if not rule_matches:
            return IntentResult(
                intent_type=IntentType.GENERAL_CHAT,
                reasoning=f"{reasoning_prefix}: No matches",
            )

        tool_name, confidence = rule_matches[0]
        matched_tools = [name for name, _ in rule_matches]

        reasoning = f"{reasoning_prefix}: Matched {tool_name} (confidence: {confidence:.2f})"
        if len(matched_tools) > 1:
            reasoning += f", also matched: {', '.join(matched_tools[1:])}"

        return IntentResult(
            intent_type=IntentType.TOOL_SPECIFIC,
            matched_tools=matched_tools,
            confidence=confidence,
            reasoning=reasoning,
        )

    async def _llm_classify(
        self,
        query: str,
        rule_matches: List[tuple],
        context: Optional[Dict[str, Any]] = None,
    ) -> IntentResult:
        """
        使用 LLM 进行增强分类

        Args:
            query: 用户输入
            rule_matches: 规则匹配结果（可能为空）
            context: 上下文信息

        Returns:
            IntentResult: LLM 分类结果
        """
        if not self.llm_client:
            raise ValueError("LLM client not available")

        # 构建提示词
        tools_summary = self.registry.get_tools_summary()

        prompt = f"""你是一个意图分类助手。分析用户输入，判断用户想要使用哪个工具。

可用工具：
{tools_summary}

用户输入：{query}

规则匹配结果（仅供参考）：
{self._format_rule_matches(rule_matches) if rule_matches else "无匹配"}

请分析用户意图，返回 JSON 格式：
{{
    "intent_type": "tool_specific" | "general_chat" | "greeting",
    "matched_tools": ["tool_name1", "tool_name2"],  // 如果 intent_type 是 tool_specific
    "confidence": 0.0-1.0,
    "reasoning": "推理过程"
}}

只返回 JSON，不要其他内容。"""

        try:
            # 调用 LLM（使用 resume agent 的 ask 方法）
            content = await self.llm_client.ask(
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                temperature=0.1,  # 低温度，确保分类稳定
            )

            # 解析响应
            content = content.strip() if content else ""

            # 尝试提取 JSON
            json_start = content.find("{")
            json_end = content.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                json_str = content[json_start:json_end]
                result = json.loads(json_str)

                # 转换为 IntentResult
                intent_type_str = result.get("intent_type", "general_chat")
                intent_type = IntentType.GENERAL_CHAT
                if intent_type_str == "tool_specific":
                    intent_type = IntentType.TOOL_SPECIFIC
                elif intent_type_str == "greeting":
                    intent_type = IntentType.GREETING

                return IntentResult(
                    intent_type=intent_type,
                    matched_tools=result.get("matched_tools", []),
                    confidence=float(result.get("confidence", 0.5)),
                    reasoning=f"LLM classification: {result.get('reasoning', '')}",
                )
            else:
                raise ValueError("No JSON found in LLM response")

        except Exception as e:
            logger.error(f"LLM 分类失败: {e}")
            raise

    def _format_rule_matches(self, rule_matches: List[tuple]) -> str:
        """格式化规则匹配结果用于提示词"""
        if not rule_matches:
            return "无匹配"

        lines = []
        for tool_name, confidence in rule_matches:
            lines.append(f"- {tool_name}: {confidence:.2f}")
        return "\n".join(lines)





