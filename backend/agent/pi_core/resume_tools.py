"""Resume-domain tool composition shared by the Pi Core runtime."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Iterable, Optional

from backend.agent.agent.capability import CapabilityRegistry, ResumeCapability
from backend.agent.agent.shared_state import AgentSharedState
from backend.agent.feature_flags import is_asking_mode_enabled
from backend.core.logger import get_logger

if TYPE_CHECKING:
    from backend.agent.tool import ToolCollection

logger = get_logger(__name__)


async def execute_resume_tool_native(
    tools: "ToolCollection",
    call: Any,
    *,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    owner_key: Optional[str] = None,
    store_structured: Optional[Callable[[str, str, Any], None]] = None,
    mark_pending_approval: Optional[Callable[[], None]] = None,
    progress_sink: Optional[Callable[[Any], None]] = None,
) -> str:
    """Execute a resume tool without entering the legacy agent step loop.

    The pi-core scheduler already owns ordering, blocking and termination.  This
    helper therefore contains only the tool-boundary concerns required by the
    scheduler: argument normalization, approval suspension, tool invocation
    and structured-result capture.
    """

    from backend.agent import approval as approval_store
    from backend.agent.tool.base import ToolResult

    name = str(getattr(call, "name", "") or "")
    call_id = str(getattr(call, "id", "") or "")
    raw_arguments = getattr(call, "arguments", {})
    args = dict(raw_arguments) if isinstance(raw_arguments, dict) else {}
    args.pop("_approved", None)
    args.pop("_noargs", None)

    tool = tools.get_tool(name)
    if tool is None:
        return f"Error: Unknown tool '{name}'"

    if getattr(tool, "requires_approval", False):
        try:
            validation_error = tool.validate_before_approval(**args)
        except Exception as exc:
            logger.exception(
                f"Approval validation failed for tool {name} (call_id={call_id})"
            )
            validation_error = f"发送前校验失败:{exc}"
        if validation_error:
            return f"Error: {validation_error}"
        approval_id = approval_store.create(
            session_id=session_id or "default",
            user_id=getattr(tool, "user_id", None) or user_id,
            tool_name=name,
            args=args,
            owner_key=owner_key,
        )
        payload = {
            "approval_id": approval_id,
            "tool_name": name,
            "args": args,
            "editable_fields": list(
                getattr(tool, "approval_editable_fields", [])
            ),
        }
        try:
            payload.update(tool.approval_preview(**args) or {})
        except Exception:
            logger.exception(
                f"Approval preview failed for tool {name} (call_id={call_id})"
            )
        if store_structured:
            store_structured(
                call_id,
                name,
                ToolResult(
                    output=(
                        "已生成发送请求并展示确认卡,等待用户确认或修改。"
                        "本轮到此结束,不要再调用任何工具。"
                    ),
                    structured_data={
                        "type": "approval_request",
                        "payload": payload,
                    },
                ),
            )
        if mark_pending_approval:
            mark_pending_approval()
        return (
            "已生成发送请求并展示确认卡,等待用户确认或修改。"
            "本轮到此结束,不要再调用任何工具。"
        )

    progress_token = None
    if progress_sink is not None and hasattr(tool, "set_progress_callback"):
        async def _capture_progress(update: Any) -> None:
            progress_sink(update)

        progress_token = tool.set_progress_callback(_capture_progress)
    try:
        result = await tools.execute(name=name, tool_input=args)
    except Exception as exc:
        logger.exception(
            f"Resume tool execution failed for {name} (call_id={call_id})"
        )
        return f"⚠️ Tool '{name}' encountered a problem: {exc}"
    finally:
        if progress_token is not None:
            tool.clear_progress_callback(progress_token)
    if store_structured:
        store_structured(call_id, name, result)

    if isinstance(result, ToolResult):
        text = str(result)
    else:
        text = str(result or "")
    return (
        f"Observed output of cmd `{name}` executed:\n{text}"
        if text
        else f"Cmd `{name}` completed with no output"
    )


def build_resume_tool_collection(
    capability_name: Optional[str] = None,
) -> ToolCollection:
    """Build the resume-only tool set without depending on an agent class."""

    # Keep tool imports lazy.  The SSE route should be importable before the
    # application's logging bootstrap has run, and tests should be able to
    # construct the runtime facade without importing every optional tool.
    from backend.agent.tool import (
        AskUserQuestionTool,
        CVAnalyzerAgentTool,
        CVEditorAgentTool,
        CVReaderAgentTool,
        CVSuggestionsAgentTool,
        GenerateResumeTool,
        GetResumeDetailTool,
        ListResumesTool,
        ShowResumeTool,
        Terminate,
        ToolCollection,
    )
    from backend.agent.tool.ask_human import AskHuman

    base_tools = [AskHuman(), Terminate()]
    domain_tools = [
        CVReaderAgentTool(),
        ListResumesTool(),
        GetResumeDetailTool(),
        ShowResumeTool(),
        CVAnalyzerAgentTool(),
        CVSuggestionsAgentTool(),
        CVEditorAgentTool(),
        GenerateResumeTool(),
    ]
    if is_asking_mode_enabled():
        domain_tools.append(AskUserQuestionTool())

    capability: ResumeCapability = CapabilityRegistry.get(capability_name)
    if not capability.tool_whitelist:
        return ToolCollection(*base_tools, *domain_tools)

    whitelisted = [
        tool for tool in domain_tools if tool.name in capability.tool_whitelist
    ]
    return ToolCollection(*base_tools, *whitelisted)


def inject_resume_tool_context(
    tools: Iterable[Any],
    *,
    session_id: Optional[str],
    user_id: Optional[str],
    shared_state: Optional[AgentSharedState],
    llm: Optional[Any] = None,
) -> None:
    """Attach session-scoped context to tools that declare the matching fields."""

    for tool in tools:
        if hasattr(tool, "session_id"):
            tool.session_id = session_id
        if hasattr(tool, "shared_state"):
            tool.shared_state = shared_state
        if hasattr(tool, "user_id"):
            tool.user_id = user_id
        if llm is not None and hasattr(tool, "llm"):
            tool.llm = llm
