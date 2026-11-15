"""Turn-level tool guards shared by the Pi Core adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class TurnPolicySnapshot:
    """Public, immutable view of tool guards for one prepared turn."""

    read_only: bool = False
    view_suggestions: bool = False
    diagnosis_only: bool = False
    diagnosis_apply: bool = False
    diagnosis_gap_collect: bool = False

    @classmethod
    def from_turn(cls, turn: Any) -> "TurnPolicySnapshot":
        if turn is None:
            return cls()
        return cls(
            read_only=bool(getattr(turn, "read_only", False)),
            view_suggestions=bool(getattr(turn, "view_suggestions", False)),
            diagnosis_only=bool(getattr(turn, "diagnosis_only", False)),
            diagnosis_apply=bool(getattr(turn, "diagnosis_apply", False)),
            diagnosis_gap_collect=bool(
                getattr(turn, "diagnosis_gap_collect", False)
            ),
        )


def blocked_tool_reason(turn: Any, tool_name: str) -> Optional[str]:
    """Return the legacy-compatible guard message for one tool call."""

    if turn is None:
        return None

    rules = (
        (
            "read_only",
            {"cv_editor_agent", "str_replace_editor"},
            "错误：本轮为只读查看请求，禁止修改简历。",
        ),
        (
            "view_suggestions",
            {
                "cv_editor_agent",
                "str_replace_editor",
                "cv_analyzer_agent",
                "ask_human",
                "ask_user_question",
            },
            "错误：本轮只展示诊断建议，不修改简历。",
        ),
        (
            "diagnosis_only",
            {"cv_editor_agent", "str_replace_editor", "ask_user_question"},
            "错误：本轮只做简历诊断，不修改简历。",
        ),
        (
            "diagnosis_apply",
            {"ask_human", "ask_user_question"},
            (
                "本轮为一次性应用诊断建议：缺少真实信息的建议直接跳过，"
                "不向用户提问。"
            ),
        ),
        (
            "diagnosis_gap_collect",
            {"cv_editor_agent", "str_replace_editor"},
            "错误：本轮只收集缺失信息，不修改简历。",
        ),
    )
    for flag_name, protected_tools, reason in rules:
        if bool(getattr(turn, flag_name, False)) and tool_name in protected_tools:
            return reason
    return None
