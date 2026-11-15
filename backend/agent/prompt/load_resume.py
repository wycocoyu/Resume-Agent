"""Prompt helpers for fast load-resume intent responses."""

from backend.agent.prompt.greeting import GREETING_STYLE_GUIDANCE


LOAD_RESUME_FAST_PATH_PROMPT_TEMPLATE = """你是 resume agent 的“加载简历快速响应模式”。

系统已确定用户意图为“加载简历”，并会立即调用工具：{tool_name}。
{tool_hint}

请只输出两行：
Thought: <一句简短思考>
Response: <给用户的简短回应>

硬性约束（必须遵守）：
1) 只输出 Thought 和 Response 两行，不要额外 Markdown。
2) Response 1-2 句，总长度不超过 65 个中文字符。
3) 风格保持自然友好、简洁明确：
{style}
4) 不要要求用户重复输入已提供的信息。
5) 不要承诺“已完成”，只能说明“正在处理/请选择”。
6) 不要触发其他工具建议，不展开分析。
"""


def build_load_resume_fast_path_prompt(tool_name: str, file_path: str = "") -> str:
    """Build strict prompt for LOAD_RESUME fast-path natural response."""
    if tool_name == "cv_reader_agent":
        hint = (
            f"用户已给出路径：{file_path or '(未解析到路径)'}；"
            "Response 需说明正在按路径加载。"
        )
    else:
        hint = (
            "Response 需简明介绍三种上手方式：说说经历我帮你生成、导入现成简历、或说「选择已有简历」加载已保存简历。"
        )
    return LOAD_RESUME_FAST_PATH_PROMPT_TEMPLATE.format(
        tool_name=tool_name,
        tool_hint=hint,
        style=GREETING_STYLE_GUIDANCE,
    )

