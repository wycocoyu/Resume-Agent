"""CVAnalyzer Agent Tool - 输出可直接渲染的结构化简历诊断。"""

from typing import TYPE_CHECKING, Any, Optional

from pydantic import Field

from backend.agent.tool.base import BaseTool, ToolProgress, ToolResult
from backend.agent.tool.resume_data_store import ResumeDataStore
from backend.core.logger import get_logger

logger = get_logger(__name__)

DIAGNOSIS_PROGRESS_STAGES = (
    "结构完整度",
    "成果证据",
    "面试风险",
    "岗位匹配",
    "汇总建议",
)

if TYPE_CHECKING:
    from backend.agent.application.resume_diagnosis_engine import DiagnosisProgress


class CVAnalyzerAgentTool(BaseTool):
    """CVAnalyzer Agent 工具

    这是一个特殊的工具，它内部使用 CVAnalyzer Agent 来处理简历深度分析任务。
    Manus 可以委托简历分析任务给这个工具，CVAnalyzer 会以 Agent 的方式处理。

    使用场景：
    - 用户要求分析简历质量（深度分析）
    - 用户要求找出简历需要优化的地方
    - 用户要求使用 STAR 法则分析经历
    """

    name: str = "cv_analyzer_agent"
    description: str = """Delegate CV/Resume deep analysis to the CVAnalyzer Agent.

Use this tool when the user asks to:
- "分析我的简历" (analyze my resume)
- "帮我分析一下简历" (help me analyze my resume)
- "找出简历需要优化的地方" (find areas that need improvement)
- "深度分析简历" (deeply analyze the resume)

The CVAnalyzer Agent will:
1. Check completeness (empty/missing fields)
2. Analyze content quality using STAR methodology
3. Identify skills that need better description
4. Provide structured optimization suggestions

此工具用于深度分析求职者的简历内容质量。"""

    parameters: dict = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The analysis question or request"
            }
        },
        "required": ["question"]
    }
    llm: Optional[Any] = Field(default=None, exclude=True)

    class Config:
        arbitrary_types_allowed = True

    async def _report_progress(self, update: "DiagnosisProgress") -> None:
        logger.info(
            "[cv_analyzer_agent] diagnosis progress {}/{}",
            update.index + 1,
            update.total,
        )
        await self.emit_progress(
            ToolProgress(
                content=update.content,
                phase="diagnosis_progress",
                node_id=f"stage-{update.index + 1}",
                current=update.index + 1,
                total=update.total,
                label=DIAGNOSIS_PROGRESS_STAGES[update.index],
                stages=DIAGNOSIS_PROGRESS_STAGES,
            )
        )

    async def execute(self, question: str) -> ToolResult:
        """执行简历深度分析

        内部创建 CVAnalyzer Agent 并运行它来处理分析任务
        """
        resume_data = ResumeDataStore.get_data(self.session_id)
        if not resume_data:
            return ToolResult(
                output="No resume data loaded. Please use cv_reader_agent tool first to read resume data."
            )

        if not isinstance(resume_data, dict):
            return ToolResult(
                error=f"Invalid resume data type: {type(resume_data)}. Expected dict."
            )

        from backend.agent.application.resume_diagnosis_engine import (
            ResumeGuidanceModule,
        )

        guidance = ResumeGuidanceModule(llm=self.llm)
        structured = await guidance.assess(
            resume_data,
            question,
            on_progress=self._report_progress,
        )
        diagnosis_source = (structured.get("details") or {}).get("diagnosis_source")
        resume_id = str(
            resume_data.get("resume_id")
            or resume_data.get("id")
            or (resume_data.get("_meta") or {}).get("resume_id")
            or ""
        )
        if self.shared_state is not None:
            self.shared_state.set("resume_guidance_assessment", structured)
            if diagnosis_source == "llm":
                self.shared_state.set("resume_diagnosis_completed_for", resume_id)

        output = (
            "深度 LLM 诊断暂时未完成，已生成一版四维基础检查，结果见诊断卡。"
            if diagnosis_source == "heuristic_fallback"
            else (
                "已从结构完整度、成果证据、面试风险和岗位匹配四个维度完成诊断，"
                "结果见诊断卡。"
            )
        )
        return ToolResult(output=output, structured_data=structured)
