"""Agent 运行时功能开关。

开关按调用时读取环境变量，便于测试和灰度切换；未显式开启的实验能力默认关闭。
"""

import os
import hashlib


_TRUE_VALUES = {"1", "true", "yes", "on", "enabled"}


def is_asking_mode_enabled() -> bool:
    """Asking 选择框是否启用。默认关闭，但保留完整实现供后续灰度。"""

    return (
        os.getenv("AGENT_ASKING_MODE_ENABLED", "false").strip().lower()
        in _TRUE_VALUES
    )


def is_pi_core_enabled(session_id: str | None = None) -> bool:
    """Whether the linear pi-core stream is enabled.

    Pi Core is now the default production path.  The flag remains available
    for controlled rollout and emergency disablement.
    """

    if os.getenv("RESUME_AGENT_PI_CORE", "true").strip().lower() not in _TRUE_VALUES:
        return False
    raw_percent = os.getenv("RESUME_AGENT_PI_CORE_ROLLOUT_PERCENT", "100")
    try:
        percent = max(0, min(100, int(raw_percent)))
    except ValueError:
        percent = 100
    if percent >= 100 or not session_id:
        return True
    if percent <= 0:
        return False
    bucket = int(
        hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:8],
        16,
    ) % 100
    return bucket < percent


ASKING_MODE_DISABLED_PROMPT = """
## Asking 模式当前关闭（运行时强制）

- `ask_user_question` 当前不可用，不要尝试调用、描述或等待这个工具。
- 教育经历、GPA、奖项、日期、量化结果等信息缺失时，把它记入诊断问题；不要因此中断诊断或整份优化流程。
- 只使用简历现有事实完成诊断与可安全执行的优化，绝不为补齐空字段而编造内容。
""".strip()
