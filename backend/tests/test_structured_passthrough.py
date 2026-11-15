"""structured 通用透传测试:名单外工具零注册直达、坏数据不炸有日志、老工具行为不回归;
Wave 1.1:ToolResult.structured_data 显式通道优先于 system JSON 旁路(兼容迁移)"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.core.logger import setup_logging
setup_logging(False, "INFO", "logs/test")

import backend.agent.pi_core.resume_agent  # noqa: F401  先初始化包,避开循环导入
from backend.agent.pi_core.resume_domain import ResumeDomainRuntime
from backend.agent.tool.base import ToolResult


def make_agent():
    return ResumeDomainRuntime(session_id="s-structured-test")


def test_unknown_tool_with_typed_system_passes_through():
    agent = make_agent()
    result = ToolResult(
        output="ok",
        system=json.dumps({"type": "approval_request", "payload": {"x": 1}}),
    )
    agent._store_structured_tool_result("call_1", "some_future_tool", result)
    stored = agent.get_structured_tool_result("call_1")
    assert stored == {"type": "approval_request", "payload": {"x": 1}}


def test_invalid_json_system_is_dropped_not_crashed():
    agent = make_agent()
    result = ToolResult(output="ok", system="not-json{{")
    agent._store_structured_tool_result("call_2", "some_future_tool", result)
    assert agent.get_structured_tool_result("call_2") is None


def test_system_without_type_is_dropped():
    agent = make_agent()
    result = ToolResult(output="ok", system=json.dumps({"payload": 1}))
    agent._store_structured_tool_result("call_3", "some_future_tool", result)
    assert agent.get_structured_tool_result("call_3") is None


def test_no_system_is_noop():
    agent = make_agent()
    result = ToolResult(output="plain text only")
    agent._store_structured_tool_result("call_4", "some_future_tool", result)
    assert agent.get_structured_tool_result("call_4") is None


def test_legacy_cv_editor_type_gate_preserved():
    """老工具行为不变:cv_editor 非白名单 type 仍被丢弃(不走通用路径)"""
    agent = make_agent()
    result = ToolResult(
        output="ok", system=json.dumps({"type": "weird_type", "x": 1})
    )
    agent._store_structured_tool_result("call_5", "cv_editor_agent", result)
    assert agent.get_structured_tool_result("call_5") is None

    ok = ToolResult(
        output="ok",
        system=json.dumps({"type": "resume_edit_diff", "before": "a", "after": "b"}),
    )
    agent._store_structured_tool_result("call_6", "cv_editor_agent", ok)
    stored = agent.get_structured_tool_result("call_6")
    assert stored is not None and stored["type"] == "resume_edit_diff"
    assert stored["source"] == "cv_editor_agent"  # 元数据注入保留


# ---------- Wave 1.1: structured_data 显式通道 ----------

def test_explicit_structured_data_wins_over_system():
    """显式字段优先:structured_data 与 system 同时存在时消费前者,不再解析 JSON"""
    agent = make_agent()
    result = ToolResult(
        output="ok",
        system=json.dumps({"type": "from_system", "x": 1}),
        structured_data={"type": "from_field", "x": 2},
    )
    agent._store_structured_tool_result("call_7", "some_future_tool", result)
    assert agent.get_structured_tool_result("call_7") == {"type": "from_field", "x": 2}


def test_explicit_structured_data_for_cv_editor_gets_intent_meta():
    """显式通道保持与 legacy 分支同款的意图元信息补齐"""
    agent = make_agent()
    result = ToolResult(
        output="ok",
        structured_data={"type": "resume_patch", "patch_id": "p1"},
    )
    agent._store_structured_tool_result("call_8", "cv_editor_agent", result)
    stored = agent.get_structured_tool_result("call_8")
    assert stored is not None and stored["type"] == "resume_patch"
    assert stored["source"] == "cv_editor_agent"
    assert "trigger" in stored and "intent_source" in stored


def test_structured_data_without_type_falls_back_to_system():
    """显式字段缺 type 不生效,回落到 system JSON 解析(兼容迁移安全网)"""
    agent = make_agent()
    result = ToolResult(
        output="ok",
        system=json.dumps({"type": "approval_request", "payload": 1}),
        structured_data={"payload": 2},  # 无 type
    )
    agent._store_structured_tool_result("call_9", "some_future_tool", result)
    assert agent.get_structured_tool_result("call_9") == {
        "type": "approval_request",
        "payload": 1,
    }


def test_explicit_structured_data_is_copied_not_aliased():
    """存入的是拷贝:后续对存储结果的修改不能污染工具返回的原 dict"""
    agent = make_agent()
    original = {"type": "resume_generated", "resume": {"basic": {"name": "张三"}}}
    result = ToolResult(output="ok", structured_data=original)
    agent._store_structured_tool_result("call_10", "generate_resume", result)
    stored = agent.get_structured_tool_result("call_10")
    stored["mutated"] = True
    assert "mutated" not in original


def test_toolresult_add_keeps_structured_data():
    """ToolResult.__add__ 不丢 structured_data(与 base64_image 同款不可拼接语义)"""
    a = ToolResult(output="a", structured_data={"type": "t", "v": 1})
    b = ToolResult(output="b")
    combined = a + b
    assert combined.structured_data == {"type": "t", "v": 1}
    assert combined.output == "ab"
