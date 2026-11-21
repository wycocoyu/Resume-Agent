"""CVSuggestions Agent Tool - 基于已有诊断单独生成/展示逐条修改建议（只读）。

2026-07-16 诊断/建议拆分：诊断轮只出打分与诊断发现（快），逐条修改建议在
用户点「查看修改建议」时由本工具单独生成——grounding 复用 shared_state 里
的 assessment，不重跑诊断；生成结果回写 assessment，重复查看缓存命中零
LLM 调用。本工具只读，不修改简历。
"""

from typing import Any, Optional

from pydantic import Field

from backend.agent.tool.base import BaseTool, ToolResult
from backend.agent.tool.resume_data_store import ResumeDataStore
from backend.core.logger import get_logger

logger = get_logger(__name__)


class CVSuggestionsAgentTool(BaseTool):
    """展示当前诊断的逐条修改建议（只读，不修改简历）。"""

    name: str = "cv_suggestions_agent"
    description: str = """Show the concrete improvement suggestions for the current resume diagnosis.

Use this tool when the user asks to:
- "查看修改建议" (view the improvement suggestions)
- "看看这次诊断的建议" (show me the suggestions from this diagnosis)
- "给我看具体建议" (show me the concrete suggestions)

Requires a completed diagnosis (cv_analyzer_agent) in this session. This tool is
READ-ONLY: it presents suggestions as a card and never edits the resume."""

    parameters: dict = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The user's request for viewing suggestions",
            }
        },
        "required": ["question"],
    }
    llm: Optional[Any] = Field(default=None, exclude=True)

    class Config:
        arbitrary_types_allowed = True

    async def execute(self, question: str) -> ToolResult:
        assessment = (
            self.shared_state.get("resume_guidance_assessment")
            if self.shared_state is not None
            else None
        )
        if not isinstance(assessment, dict):
            return ToolResult(
                output=(
                    "当前会话还没有诊断结果。请先用 cv_analyzer_agent 完成简历诊断，"
                    "再查看修改建议。"
                )
            )

        resume_data = ResumeDataStore.get_data(self.session_id)
        if not isinstance(resume_data, dict):
            return ToolResult(
                output="No resume data loaded. Please load a resume first."
            )

        from backend.agent.application.resume_diagnosis_engine import (
            ResumeGuidanceModule,
        )

        cached = (assessment.get("details") or {}).get("suggestions") or []
        if cached:
            # 重复查看：建议已生成并回写过，直接展示，零 LLM 调用
            logger.info(
                "[cv_suggestions_agent] serving {} cached suggestions", len(cached)
            )
            envelope = ResumeGuidanceModule.present(assessment, "suggestions")
        else:
            guidance = ResumeGuidanceModule(llm=self.llm)
            envelope = await guidance.suggest(resume_data, assessment)
            # suggest() 已把建议回写进 assessment；存回 shared_state 让下次
            # 查看缓存命中（以及后续轮次可引用建议内容）
            if self.shared_state is not None:
                self.shared_state.set("resume_guidance_assessment", assessment)

        suggestions = (envelope.get("payload") or {}).get("suggestions") or []
        if not suggestions:
            return ToolResult(
                output=(
                    "本次诊断没有可展示的修改建议（简历各模块结构完整）。"
                    "如需针对性优化，可以直接说明想改哪个模块。"
                )
            )

        structured = {"type": "resume_suggestions", **envelope}
        return ToolResult(
            output=f"已整理 {len(suggestions)} 条修改建议，结果见建议卡。本轮未修改简历。",
            structured_data=structured,
        )
