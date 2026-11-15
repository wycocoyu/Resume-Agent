"""Agent 会话生命周期回归测试（Wave 0 + Wave 0.5）:
1. ResumeDataStore.clear_data 必须完整清理会话态（含 _jd_by_session，防 JD 泄漏到复用同 id 的新会话）
2. 会话 TTL 回收按 last_accessed（活跃时间）判定，而非 created_at——
   活跃长会话不被误回收 / 当前会话不会在自己的 finally 里被清掉 / 旧格式会话回退 created_at
3. session_manager façade：discard_session / clear_sessions_for_user 必须同步清理
   ResumeDataStore（原 history.py 直接 del 条目会漏掉，造成简历/JD 泄漏）
"""
import sys
import os
from datetime import datetime, timedelta
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.core.logger import setup_logging
setup_logging(False, "INFO", "logs/test")

import pytest

# 先导入 manus 完成 agent 包初始化,避开 backend.agent.tool.__init__ 的循环导入
import backend.agent.pi_core.resume_agent  # noqa: F401
from backend.agent.agent.shared_state import AgentSharedState
from backend.agent.tool.resume_data_store import ResumeDataStore
from backend.agent.web import session_manager
from backend.agent.web.routes import stream as stream_module

SESSION_ID = "test-lifecycle-session"
RESUME = {"basic": {"name": "张三"}, "experience": [], "projects": []}


@pytest.fixture(autouse=True)
def _clean_state():
    yield
    ResumeDataStore._data_by_session.pop(SESSION_ID, None)
    ResumeDataStore._meta_by_session.pop(SESSION_ID, None)
    ResumeDataStore._jd_by_session.pop(SESSION_ID, None)
    ResumeDataStore._shared_state_by_session.pop(SESSION_ID, None)
    session_manager._active_sessions.clear()


# ---------- Wave 0.1: clear_data 完整性 ----------

def test_clear_data_removes_session_jd():
    """clear_data(session_id) 必须连 JD 一起清，否则 JD 泄漏到复用同 id 的下一个会话"""
    shared_state = AgentSharedState(SESSION_ID)
    ResumeDataStore.set_shared_state(SESSION_ID, shared_state)
    ResumeDataStore.set_data(dict(RESUME), session_id=SESSION_ID)
    ResumeDataStore.set_session_jd(SESSION_ID, "后端工程师，要求精通 Python")

    ResumeDataStore.clear_data(SESSION_ID)

    assert ResumeDataStore.get_data(SESSION_ID) is None
    assert ResumeDataStore.get_session_jd(SESSION_ID) == ""
    assert SESSION_ID not in ResumeDataStore._jd_by_session
    assert SESSION_ID not in ResumeDataStore._meta_by_session
    assert SESSION_ID not in ResumeDataStore._shared_state_by_session


def test_clear_data_global_keeps_session_entries():
    """无 session_id 的 clear_data 只清全局 _data，不影响会话级数据"""
    ResumeDataStore.set_data(dict(RESUME), session_id=SESSION_ID)
    ResumeDataStore.set_session_jd(SESSION_ID, "算法工程师")

    ResumeDataStore.clear_data()

    assert ResumeDataStore.get_data(SESSION_ID) is not None
    assert ResumeDataStore.get_session_jd(SESSION_ID) == "算法工程师"


# ---------- Wave 0.2: TTL 按活跃时间回收 ----------

def _seed_session(cid: str, created_delta: timedelta, accessed_delta: timedelta | None):
    """向 _active_sessions 植入一个测试会话；accessed_delta=None 模拟旧格式（无 last_accessed）"""
    now = datetime.now()
    session = {
        "agent": None,
        "chat_history": None,
        "resume_path": None,
        "created_at": now - created_delta,
        "user_id": "uLifecycleBaIdAaaa000000000001",
    }
    if accessed_delta is not None:
        session["last_accessed"] = now - accessed_delta
    session_manager._active_sessions[cid] = session
    return session


def test_cleanup_keeps_active_long_session():
    """核心回归：created_at 超 TTL 但最近仍活跃的会话不能被回收（旧代码按 created_at 误杀）"""
    _seed_session(SESSION_ID, created_delta=timedelta(hours=2), accessed_delta=timedelta(minutes=1))
    ResumeDataStore.set_data(dict(RESUME), session_id=SESSION_ID)

    stream_module._cleanup_session("some-other-session")

    assert SESSION_ID in session_manager._active_sessions
    assert ResumeDataStore.get_data(SESSION_ID) is not None


def test_cleanup_evicts_idle_session():
    """真正闲置（last_accessed 超 TTL）的会话被回收，且 ResumeDataStore 一并清理"""
    _seed_session(SESSION_ID, created_delta=timedelta(hours=2), accessed_delta=timedelta(hours=2))
    ResumeDataStore.set_data(dict(RESUME), session_id=SESSION_ID)
    ResumeDataStore.set_session_jd(SESSION_ID, "前端工程师")

    stream_module._cleanup_session("some-other-session")

    assert SESSION_ID not in session_manager._active_sessions
    assert ResumeDataStore.get_data(SESSION_ID) is None
    assert ResumeDataStore.get_session_jd(SESSION_ID) == ""


def test_cleanup_never_evicts_current_session():
    """当前会话的 stream 刚结束即是活跃证据：即使时间戳过旧也先 touch、不回收"""
    session = _seed_session(
        SESSION_ID, created_delta=timedelta(hours=3), accessed_delta=timedelta(hours=3)
    )

    stream_module._cleanup_session(SESSION_ID)

    assert SESSION_ID in session_manager._active_sessions
    # touch 生效：last_accessed 已刷新
    assert (datetime.now() - session["last_accessed"]).total_seconds() < 5


def test_cleanup_falls_back_to_created_at_for_legacy_sessions():
    """旧格式会话（无 last_accessed）回退用 created_at 判定，超 TTL 仍可回收"""
    _seed_session(SESSION_ID, created_delta=timedelta(hours=2), accessed_delta=None)

    stream_module._cleanup_session("some-other-session")

    assert SESSION_ID not in session_manager._active_sessions


def test_get_or_create_touches_last_accessed_on_reuse(monkeypatch):
    """复用已有会话时必须 touch last_accessed（持续对话保持活跃）"""
    session = _seed_session(
        SESSION_ID, created_delta=timedelta(hours=2), accessed_delta=timedelta(hours=1)
    )
    fake_user = SimpleNamespace(id="uLifecycleBaIdAaaa000000000001", role="user")
    # 会话无 owner 记录 → 放行；storage 中消息仍在 → 走复用分支
    monkeypatch.setattr(
        stream_module.conversation_manager, "get_session_owner", lambda cid: None
    )
    monkeypatch.setattr(
        stream_module.storage,
        "load_messages",
        lambda cid, user_id=None, is_admin=False: [{"role": "user", "content": "hi"}],
    )

    result = stream_module._get_or_create_session(SESSION_ID, fake_user)

    assert result is session
    assert (datetime.now() - session["last_accessed"]).total_seconds() < 5
    # created_at 保留不动（仍作诊断用）
    assert (datetime.now() - session["created_at"]).total_seconds() > 3600


# ---------- Wave 0.5: session_manager façade 泄漏修复 ----------

def test_discard_session_clears_resume_data():
    """discard_session 默认同步清理 ResumeDataStore（原 history.py 直接 del 会漏掉）"""
    _seed_session(SESSION_ID, created_delta=timedelta(minutes=1), accessed_delta=timedelta(minutes=1))
    ResumeDataStore.set_data(dict(RESUME), session_id=SESSION_ID)
    ResumeDataStore.set_session_jd(SESSION_ID, "测试岗位")

    assert session_manager.discard_session(SESSION_ID) is True

    assert SESSION_ID not in session_manager._active_sessions
    assert ResumeDataStore.get_data(SESSION_ID) is None
    assert ResumeDataStore.get_session_jd(SESSION_ID) == ""


def test_discard_session_clears_data_even_without_entry():
    """条目已被回收但类级字典仍留存数据时，discard 也要清（返回 False 表示条目不存在）"""
    ResumeDataStore.set_data(dict(RESUME), session_id=SESSION_ID)

    assert session_manager.discard_session(SESSION_ID) is False
    assert ResumeDataStore.get_data(SESSION_ID) is None


def test_discard_session_can_keep_resume_data():
    """文件被删原地重建的路径：clear_resume_data=False 保留简历数据，只移除条目"""
    _seed_session(SESSION_ID, created_delta=timedelta(minutes=1), accessed_delta=timedelta(minutes=1))
    ResumeDataStore.set_data(dict(RESUME), session_id=SESSION_ID)

    assert session_manager.discard_session(SESSION_ID, clear_resume_data=False) is True

    assert SESSION_ID not in session_manager._active_sessions
    assert ResumeDataStore.get_data(SESSION_ID) is not None


def test_clear_sessions_for_user_clears_resume_data():
    """按用户清会话必须连 ResumeDataStore 一起清（原实现只删条目，简历/JD 泄漏）"""
    _seed_session(SESSION_ID, created_delta=timedelta(minutes=1), accessed_delta=timedelta(minutes=1))
    other_sid = "other-user-session"
    session_manager._active_sessions[other_sid] = {"agent": None, "user_id": "uLifecycleBaIdBbbb000000000002"}
    ResumeDataStore.set_data(dict(RESUME), session_id=SESSION_ID)
    ResumeDataStore.set_session_jd(SESSION_ID, "数据工程师")

    cleared = session_manager.clear_sessions_for_user("uLifecycleBaIdAaaa000000000001")

    assert cleared == 1
    assert SESSION_ID not in session_manager._active_sessions
    assert ResumeDataStore.get_data(SESSION_ID) is None
    assert ResumeDataStore.get_session_jd(SESSION_ID) == ""
    # 其它用户的会话不受影响
    assert other_sid in session_manager._active_sessions
    session_manager._active_sessions.pop(other_sid, None)
