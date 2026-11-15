from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.logger import setup_logging

setup_logging(False, "INFO", "logs/test")

from backend.agent.cltp.storage import db_conversation_storage as storage_module
from backend.agent.cltp.storage.db_conversation_storage import DBConversationStorage
from backend.agent.schema import Message
from backend.agent.tool.resume_data_store import ResumeDataStore
from backend.database import Base
from backend.models import AgentConversation, AgentMessage


def _configure_test_database(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'conversation.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[AgentConversation.__table__, AgentMessage.__table__],
    )
    session_local = sessionmaker(autoflush=False, bind=engine)
    monkeypatch.setattr(storage_module, "engine", engine)
    monkeypatch.setattr(storage_module, "SessionLocal", session_local)
    monkeypatch.setattr(DBConversationStorage, "_supports_message_hash", None)
    return engine


def test_db_storage_round_trips_resume_state_through_durable_sidecar(
    monkeypatch, tmp_path
):
    engine = _configure_test_database(monkeypatch, tmp_path)
    session_id = "db-durable-round-trip"
    resume = {
        "basic": {"name": "实习生"},
        "experience": [{"company": "示例公司"}],
        "_meta": {"resume_id": "resume-1", "user_id": "user-1"},
    }
    ResumeDataStore.set_data(resume, session_id=session_id)
    ResumeDataStore.set_session_jd(session_id, "后端开发实习生")
    progress = ResumeDataStore.init_progress(session_id, resume)

    storage = DBConversationStorage(durable_root=str(tmp_path / "durable"))
    storage.save_session(
        session_id,
        [Message.user_message("优化我的简历")],
        user_id="user-1",
    )

    ResumeDataStore.clear_data(session_id)
    loaded = storage.load_session(session_id, user_id="user-1")

    assert loaded is not None
    assert loaded["resume_state"]["resume_data"] == resume
    assert ResumeDataStore.get_data(session_id) == resume
    assert ResumeDataStore.get_session_jd(session_id) == "后端开发实习生"
    assert ResumeDataStore.get_progress(session_id)["task_id"] == progress["task_id"]

    ResumeDataStore.clear_data(session_id)
    storage.delete_session(session_id, user_id="user-1")
    assert storage._durable.read_document(session_id) is None
    engine.dispose()


def test_db_legacy_schema_path_restores_durable_resume_state(monkeypatch, tmp_path):
    engine = _configure_test_database(monkeypatch, tmp_path)
    session_id = "db-durable-legacy"
    resume = {"basic": {"name": "兼容路径"}}
    ResumeDataStore.set_data(resume, session_id=session_id)

    storage = DBConversationStorage(durable_root=str(tmp_path / "durable"))
    storage._supports_message_hash = False
    storage.save_session(
        session_id,
        [Message.user_message("检查兼容路径")],
        user_id="user-2",
    )

    ResumeDataStore.clear_data(session_id)
    loaded = storage.load_session(session_id, user_id="user-2")

    assert loaded is not None
    assert loaded["resume_state"]["resume_data"] == resume
    assert ResumeDataStore.get_data(session_id) == resume
    engine.dispose()


def test_db_load_repairs_stale_durable_snapshot(monkeypatch, tmp_path):
    engine = _configure_test_database(monkeypatch, tmp_path)
    session_id = "db-durable-repair"
    storage = DBConversationStorage(durable_root=str(tmp_path / "durable"))
    storage.save_session(
        session_id,
        [Message.user_message("第一轮")],
        user_id="user-3",
    )

    document = storage._durable.read_document(session_id)
    assert document is not None
    storage._durable.write_document(
        session_id,
        {
            **document.content,
            "message_count": 999,
            "updated_at": "stale",
        },
    )

    loaded = storage.load_session(session_id, user_id="user-3")
    assert loaded is not None
    repaired = storage._durable.read_document(session_id)
    assert repaired is not None
    assert repaired.content["message_count"] == 1
    assert repaired.content["updated_at"] == loaded["updated_at"]
    engine.dispose()
