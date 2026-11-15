"""Wave 2a-S2 golden 捕获脚本（一次性）：迁移前录制 prompt 组合矩阵输出。

用法：.venv/bin/python backend/tests/capture_prompt_golden.py
产出：backend/tests/fixtures/prompt_golden.json
迁移后 test_prompt_builder.py 对同一矩阵断言输出与 fixture 逐字符一致。
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.core.logger import setup_logging
setup_logging(False, "INFO", "logs/test")

from backend.agent.pi_core.resume_domain import ResumeDomainRuntime
from backend.agent.memory import Intent
from backend.agent.tool.resume_data_store import ResumeDataStore

SESSION = "golden-prompt-session"
RESUME = {
    "basic": {"name": "张三", "email": "z@t.com"},
    "experience": [
        {"company": "美团", "position": "后端实习生", "date": "2023.01-2023.06",
         "details": "<ul class=\"custom-list\"><li>负责订单系统</li></ul>"}
    ],
    "projects": [],
}

CASES = [
    {"key": "no_resume_plain", "resume": False, "input": "帮我优化简历", "intent": "UNKNOWN"},
    {"key": "no_resume_readonly", "resume": False, "input": "看看我的简历第一段经历", "intent": "UNKNOWN"},
    {"key": "resume_plain", "resume": True, "input": "帮我优化简历", "intent": "UNKNOWN"},
    {"key": "resume_readonly", "resume": True, "input": "看看我的简历第一段经历", "intent": "UNKNOWN"},
    {"key": "resume_add_exp", "resume": True, "input": "帮我加一段在字节跳动的实习经历", "intent": "UNKNOWN"},
    {"key": "resume_office_pdf", "resume": True, "input": "帮我把简历处理成 pdf 文档", "intent": "UNKNOWN"},
    {"key": "greeting_next_step", "resume": True, "input": "你好", "intent": "GREETING"},
    # 与 test_prompt_builder.py 矩阵对齐:有 current_resume_path 的组合
    {"key": "resume_with_path", "resume": True, "input": "帮我优化简历",
     "intent": "UNKNOWN", "resume_path": "/tmp/my_resume.pdf"},
]


async def main():
    out = {}
    for case in CASES:
        ResumeDataStore.clear_data(SESSION)
        agent = ResumeDomainRuntime(session_id=SESSION)
        if case["resume"]:
            ResumeDataStore.set_data(dict(RESUME), session_id=SESSION)
            agent._conversation_state.update_resume_loaded(True)
        if case.get("resume_path"):
            agent._current_resume_path = case["resume_path"]
        intent = getattr(Intent, case["intent"])
        system_prompt, next_step = await agent._generate_dynamic_prompts(
            case["input"], intent
        )
        out[case["key"]] = {"system": system_prompt, "next_step": next_step}
        ResumeDataStore.clear_data(SESSION)

    os.makedirs(os.path.join(os.path.dirname(__file__), "fixtures"), exist_ok=True)
    path = os.path.join(os.path.dirname(__file__), "fixtures", "prompt_golden.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"golden saved: {path}, cases={len(out)}")


if __name__ == "__main__":
    asyncio.run(main())
