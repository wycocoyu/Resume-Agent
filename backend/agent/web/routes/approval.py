"""运行时确认端点:用户在确认卡中批准/取消 requires_approval 工具的挂起调用。

批准时允许携带编辑后的参数(仅限工具声明的 approval_editable_fields),
合并后同步执行工具并返回结果——不复活 SSE 流,前端直接用响应更新卡片。
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.agent import approval as approval_store
from backend.agent.schema import Message
from backend.agent.web.routes.stream import get_active_agent
from backend.core.logger import get_logger
from backend.middleware.auth import get_current_user
from backend.middleware.auth import AppUser

logger = get_logger(__name__)

router = APIRouter(tags=["Agent"])


class ApprovalActionRequest(BaseModel):
    approval_id: str
    action: str  # approve | cancel
    params: Optional[Dict[str, Any]] = None


def _write_back_to_agent_memory(session_id: str, text: str) -> None:
    """把审批结果增量追加进对应会话的 agent 记忆:否则用户之后问「刚才那封
    发出去了吗/发的什么」,模型上下文里完全没有依据(审查 #24)。
    agent 可能已被 TTL 回收——回收即跳过,不影响本次响应。"""
    try:
        agent = get_active_agent(session_id)
        if agent is not None:
            agent.memory.add_message(Message.system_message(text))
    except Exception:
        logger.warning(f"[approval] 结果回写 agent 记忆失败(忽略): session={session_id}")


def _build_tool(tool_name: str, pending: Dict[str, Any]):
    """按挂起记录重建工具实例并注入上下文。邮件功能下线后当前无 requires_approval
    工具消费者,通用审批端点保留休眠;新增敏感工具时在此登记执行侧映射。"""
    return None


@router.post("/approval")
async def handle_approval(
    payload: ApprovalActionRequest,
    current_user: AppUser = Depends(get_current_user),
):
    pending = approval_store.get_valid(payload.approval_id)
    if not pending:
        raise HTTPException(status_code=404, detail="确认请求不存在或已过期,请重新发起。")
    if pending["user_id"] is not None and pending["user_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="无权操作该确认请求。")

    if payload.action == "cancel":
        approval_store.pop(payload.approval_id)
        _write_back_to_agent_memory(
            pending["session_id"],
            f"[邮件发送结果] 用户取消了这次发送(收件人 {pending['args'].get('to_email', '?')}),邮件未发出。",
        )
        return {"ok": True, "message": "已取消发送。"}

    if payload.action != "approve":
        raise HTTPException(status_code=400, detail="未知操作。")

    tool = _build_tool(pending["tool_name"], pending)
    if tool is None:
        approval_store.pop(payload.approval_id)
        raise HTTPException(status_code=400, detail=f"未知的待确认工具:{pending['tool_name']}")

    # 合并用户编辑:只接受工具声明为可编辑的字段,其余以挂起时的原参数为准
    args = dict(pending["args"])
    editable = set(getattr(tool, "approval_editable_fields", []))
    for key, value in (payload.params or {}).items():
        if key in editable:
            args[key] = value

    approval_store.pop(payload.approval_id)  # 单次有效:执行前即失效,防重放
    try:
        result = await tool.execute(**args)
    except Exception as exc:
        logger.exception(f"[approval] 执行 {pending['tool_name']} 失败")
        return {"ok": False, "message": f"执行失败:{exc}"}

    error = getattr(result, "error", None)
    body_brief = str(args.get("body", ""))[:120]
    if error:
        _write_back_to_agent_memory(
            pending["session_id"],
            f"[邮件发送结果] 发送失败:{error}",
        )
        return {"ok": False, "message": str(error)}
    _write_back_to_agent_memory(
        pending["session_id"],
        f"[邮件发送结果] 已成功发送给 {args.get('to_email', '?')},"
        f"主题「{args.get('subject') or '(默认)'}」,正文开头:{body_brief}…"
        "(用户可能在确认卡中编辑过内容,以上为最终发出的版本)",
    )
    return {"ok": True, "message": str(getattr(result, "output", None) or "已完成。")}
