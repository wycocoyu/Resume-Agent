from __future__ import annotations

import json

import pytest

from backend.agent.pi_core.durable import DurableSessionStore


def test_transaction_commits_entries_and_document_atomically(tmp_path):
    store = DurableSessionStore(str(tmp_path))

    with store.transaction("session-1") as transaction:
        transaction.append("user_message", {"content": "hello"})
        transaction.set_document({"messages": [{"role": "user", "content": "hello"}]})

    entries = store.entries("session-1")
    document = store.read_document("session-1")
    assert len(entries) == 1
    assert entries[0].kind == "user_message"
    assert document is not None
    assert document.revision == 1
    assert document.content["messages"][0]["content"] == "hello"


def test_transaction_rolls_back_journal_and_document_on_failure(tmp_path, monkeypatch):
    store = DurableSessionStore(str(tmp_path))
    store.append("session-1", "before", {"ok": True})
    store.write_document("session-1", {"version": 1})

    original_write = store.write_document

    def fail_write(*args, **kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(store, "write_document", fail_write)
    with pytest.raises(OSError, match="simulated disk failure"):
        with store.transaction("session-1") as transaction:
            transaction.append("after", {"ok": False})
            transaction.set_document({"version": 2})

    monkeypatch.setattr(store, "write_document", original_write)
    assert [entry.kind for entry in store.entries("session-1")] == ["before"]
    assert store.read_document("session-1").content == {"version": 1}


def test_journal_is_jsonl_and_revisions_increment(tmp_path):
    store = DurableSessionStore(str(tmp_path))
    first = store.write_document("session-1", {"value": 1})
    second = store.write_document("session-1", {"value": 2})

    assert first.revision == 1
    assert second.revision == 2
    lines = (tmp_path / "session-1.document.json").read_text(encoding="utf-8")
    assert json.loads(lines)["revision"] == 2
