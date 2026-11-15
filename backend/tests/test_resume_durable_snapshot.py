from __future__ import annotations

from backend.core.logger import setup_logging

setup_logging(False, "INFO", "logs/test")

from backend.agent.cltp.storage.conversation_storage import FileConversationStorage
from backend.agent.schema import Message
from backend.agent.tool.resume_data_store import ResumeDataStore


def test_conversation_snapshot_round_trips_resume_state(tmp_path):
    session_id = "durable-resume-state"
    resume = {
        "resume_id": "resume-1",
        "user_id": "user-1",
        "basic": {"name": "张三"},
        "experience": [],
    }
    ResumeDataStore.set_data(resume, session_id=session_id)
    ResumeDataStore.set_session_jd(session_id, "后端工程师")
    progress = ResumeDataStore.init_progress(session_id, resume)

    storage = FileConversationStorage(
        base_dir=str(tmp_path / "sessions"),
        durable_root=str(tmp_path / "durable"),
    )
    storage.save_session(
        session_id,
        [Message.user_message("继续优化")],
        user_id="user-1",
    )

    ResumeDataStore.clear_data(session_id)
    assert ResumeDataStore.get_data(session_id) is None

    loaded = storage.load_session(session_id, user_id="user-1")

    assert loaded is not None
    assert ResumeDataStore.get_data(session_id) == resume
    assert ResumeDataStore.get_session_jd(session_id) == "后端工程师"
    assert ResumeDataStore.get_progress(session_id)["task_id"] == progress["task_id"]
