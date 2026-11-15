"""Pure helpers for the Pi Core SSE adapter."""
from __future__ import annotations

import asyncio
import re
from typing import Optional, Tuple

import openai
from tenacity import RetryError

from backend.agent.schema import Message
from backend.agent.utils.optimize_progress import strip_module_done_markers


def unwrap_retry_error(exc: BaseException) -> BaseException:
    if isinstance(exc, RetryError):
        try:
            inner = exc.last_attempt.exception()
        except Exception:
            inner = None
        if inner is not None:
            return inner
    return exc


def user_facing_error_message(exc: BaseException) -> Tuple[str, str]:
    cause = unwrap_retry_error(exc)
    if isinstance(cause, openai.APIError):
        return ("AI 服务暂时不可用（上游接口异常），请稍等片刻再试一次。", type(cause).__name__)
    if isinstance(cause, (asyncio.TimeoutError, ConnectionError, OSError)):
        return ("网络连接不稳定，这一步没有完成，请稍后重试。", type(cause).__name__)
    return ("刚才这一步运行出了点问题，请稍后重试。", type(cause).__name__)


def _parse_thought_response(content: str) -> tuple[Optional[str], Optional[str]]:
    if not content or not content.strip():
        return None, None
    patterns = [
        (r"(?:^|\n)\s*(?:Thought|思考)[:：]\s*(.*?)(?=\s*(?:Response|回复|Answer|Final\s*Answer|最终回复)[:：]|$)", r"(?:^|\n|\s)(?:Response|回复|Answer|Final\s*Answer|最终回复)[:：]\s*(.*)"),
        (r"(?:^|\n)\s*\*\*Thought\*\*[:：]\s*(.*?)(?=\n\s*\*\*Response\*\*[:：]|$)", r"(?:^|\n)\s*\*\*Response\*\*[:：]\s*(.*)"),
    ]
    for thought_pattern, response_pattern in patterns:
        thought_match = re.search(thought_pattern, content, re.DOTALL | re.IGNORECASE | re.MULTILINE)
        response_match = re.search(response_pattern, content, re.DOTALL | re.IGNORECASE | re.MULTILINE)
        if thought_match or response_match:
            return (
                thought_match.group(1).strip() if thought_match else None,
                response_match.group(1).strip() if response_match else None,
            )
    return None, content


def merge_visible_piece(parts: list[str], piece: str) -> None:
    if not piece:
        return
    if parts:
        last = parts[-1]
        if piece == last or piece in last:
            return
        if piece.startswith(last):
            parts[-1] = piece
            return
    if piece not in parts:
        parts.append(piece)


def is_tool_error_content(content: str | None) -> bool:
    return bool(content and content.lstrip().startswith("Error:"))


def split_turn_messages(messages: list[Message]) -> tuple[list[str], list[str]]:
    narrations: list[str] = []
    answer_parts: list[str] = []
    for msg in messages:
        role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
        if role != "assistant" or not msg.content:
            continue
        thought, response = _parse_thought_response(msg.content)
        cleaned = (response or (msg.content if not thought else "")).strip()
        cleaned = strip_module_done_markers(cleaned)
        if not cleaned:
            continue
        if getattr(msg, "tool_calls", None):
            if not narrations or narrations[-1] != cleaned:
                narrations.append(cleaned)
        else:
            merge_visible_piece(answer_parts, cleaned)
    return narrations, answer_parts
