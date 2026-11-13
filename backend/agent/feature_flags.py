"""Agent 运行时功能开关。

开关按调用时读取环境变量，便于测试和灰度切换；未显式开启的实验能力默认关闭。
"""

import os


_TRUE_VALUES = {"1", "true", "yes", "on", "enabled"}


def is_asking_mode_enabled() -> bool:
    """Asking 选择框是否启用。默认关闭，但保留完整实现供后续灰度。"""

    return (
        os.getenv("AGENT_ASKING_MODE_ENABLED", "false").strip().lower()
        in _TRUE_VALUES
    )


def is_pi_core_enabled() -> bool:
    """Whether the experimental linear pi-core stream is enabled.

    The legacy OpenManus stream remains the default until the new adapter has
    completed end-to-end regression (approval, resume patches and PDF flows).
    """

    return (
        os.getenv("RESUME_AGENT_PI_CORE", "false").strip().lower() in _TRUE_VALUES
    )


ASKING_MODE_DISABLED_PROMPT = """
## Asking 模式当前关闭（运行时强制）

- `ask_user_question` 当前不可用，不要尝试调用、描述或等待这个工具。
- 教育经历、GPA、奖项、日期、量化结果等信息缺失时，把它记入诊断问题；不要因此中断诊断或整份优化流程。
- 只使用简历现有事实完成诊断与可安全执行的优化，绝不为补齐空字段而编造内容。
""".strip()
