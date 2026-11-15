"""Small append-only session journal used by the pi-core runtime.

The store intentionally keeps two separate concerns:

* ``Entry`` records are immutable facts appended to a JSONL journal.
* ``Document`` is the latest materialized session snapshot written atomically.

This is the same durability shape as pi-durable without introducing another
database dependency.  The document remains human-readable and the journal
provides recovery/audit data when a process crashes between writes.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator


@dataclass(frozen=True)
class Entry:
    entry_id: str
    sequence: int
    kind: str
    payload: dict[str, Any]
    created_at: float


@dataclass(frozen=True)
class Document:
    document_id: str
    revision: int
    content: dict[str, Any]
    updated_at: float


class DurableSessionStore:
    """Append-only journal plus atomic JSON document snapshots."""

    def __init__(self, root: str = "data/pi-durable") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()

    def _lock_for(self, document_id: str) -> threading.RLock:
        with self._locks_guard:
            return self._locks.setdefault(document_id, threading.RLock())

    def _journal_path(self, document_id: str) -> Path:
        return self.root / f"{document_id}.journal.jsonl"

    def _document_path(self, document_id: str) -> Path:
        return self.root / f"{document_id}.document.json"

    def _next_sequence(self, document_id: str) -> int:
        path = self._journal_path(document_id)
        if not path.exists():
            return 1
        last = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                last = max(last, int(json.loads(line).get("sequence", 0)))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return last + 1

    def append(self, document_id: str, kind: str, payload: dict[str, Any]) -> Entry:
        with self._lock_for(document_id):
            return self._append_unlocked(document_id, kind, payload)

    def _append_unlocked(self, document_id: str, kind: str, payload: dict[str, Any]) -> Entry:
        entry = Entry(
            entry_id=uuid.uuid4().hex,
            sequence=self._next_sequence(document_id),
            kind=kind,
            payload=dict(payload),
            created_at=time.time(),
        )
        path = self._journal_path(document_id)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return entry

    def entries(self, document_id: str) -> list[Entry]:
        path = self._journal_path(document_id)
        if not path.exists():
            return []
        result: list[Entry] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                raw = json.loads(line)
                result.append(Entry(**raw))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return result

    def write_document(
        self,
        document_id: str,
        content: dict[str, Any],
        *,
        revision: int | None = None,
    ) -> Document:
        current = self.read_document(document_id)
        next_revision = revision if revision is not None else (current.revision + 1 if current else 1)
        document = Document(
            document_id=document_id,
            revision=next_revision,
            content=dict(content),
            updated_at=time.time(),
        )
        path = self._document_path(document_id)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(asdict(document), handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return document

    def read_document(self, document_id: str) -> Document | None:
        path = self._document_path(document_id)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return Document(**raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    def delete(self, document_id: str) -> None:
        """Remove a session journal and snapshot after the caller's auth check."""

        with self._lock_for(document_id):
            for path in (self._journal_path(document_id), self._document_path(document_id)):
                if path.exists():
                    path.unlink()

    @contextmanager
    def transaction(self, document_id: str) -> Iterator["DurableTransaction"]:
        with self._lock_for(document_id):
            transaction = DurableTransaction(self, document_id)
            try:
                yield transaction
                transaction.commit()
            except Exception:
                transaction.rollback()
                raise


class DurableTransaction:
    def __init__(self, store: DurableSessionStore, document_id: str) -> None:
        self.store = store
        self.document_id = document_id
        self._entries: list[tuple[str, dict[str, Any]]] = []
        self._document: dict[str, Any] | None = None
        self._closed = False

    def append(self, kind: str, payload: dict[str, Any]) -> None:
        self._entries.append((kind, dict(payload)))

    def set_document(self, content: dict[str, Any]) -> None:
        self._document = dict(content)

    def commit(self) -> None:
        if self._closed:
            return
        journal_path = self.store._journal_path(self.document_id)
        document_path = self.store._document_path(self.document_id)
        original_journal = journal_path.read_bytes() if journal_path.exists() else b""
        original_document = document_path.read_bytes() if document_path.exists() else None
        try:
            for kind, payload in self._entries:
                self.store._append_unlocked(self.document_id, kind, payload)
            if self._document is not None:
                self.store.write_document(self.document_id, self._document)
        except Exception:
            if original_journal:
                journal_path.write_bytes(original_journal)
            elif journal_path.exists():
                journal_path.unlink()
            if original_document is not None:
                document_path.write_bytes(original_document)
            elif document_path.exists():
                document_path.unlink()
            raise
        finally:
            self._closed = True

    def rollback(self) -> None:
        self._entries.clear()
        self._document = None
        self._closed = True
