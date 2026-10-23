"""In-memory processing sessions (not persisted to SQLite)."""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from gheymatyar.domain.product import PioneersProduct
from gheymatyar.domain.supplier_item import SupplierPriceItem
from gheymatyar.domain.update_candidate import UpdateCandidate
from gheymatyar.parsers.pioneers_excel_parser import InvalidProductRow


@dataclass
class ProcessingSession:
    """Temporary working state for one Excel + PDF price-update run."""

    session_id: str
    created_at: float
    supplier_key: str | None = None
    supplier_display_name: str | None = None
    #: True only after the user (or an explicit API supplier_key upload) confirms.
    supplier_confirmed: bool = False
    pioneers_filename: str | None = None
    pioneers_path: Path | None = None
    pdf_filename: str | None = None
    pdf_path: Path | None = None
    products: list[PioneersProduct] = field(default_factory=list)
    invalid_rows: list[InvalidProductRow] = field(default_factory=list)
    duplicate_codes: dict[str, tuple[int, ...]] = field(default_factory=dict)
    supplier_items: list[SupplierPriceItem] = field(default_factory=list)
    parse_warnings: list[str] = field(default_factory=list)
    candidates: list[UpdateCandidate] = field(default_factory=list)
    matched_count: int = 0
    unmatched_count: int = 0
    ambiguous_count: int = 0
    ignored_count: int = 0
    output_path: Path | None = None
    work_dir: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def conflicted_row_numbers(self) -> frozenset[int]:
        rows: set[int] = set()
        for row_tuple in self.duplicate_codes.values():
            rows.update(row_tuple)
        return frozenset(rows)

    def get_candidate(self, candidate_id: str) -> UpdateCandidate | None:
        for candidate in self.candidates:
            if candidate.candidate_id == candidate_id:
                return candidate
        return None

    def replace_candidate(self, updated: UpdateCandidate) -> None:
        for index, candidate in enumerate(self.candidates):
            if candidate.candidate_id == updated.candidate_id:
                self.candidates[index] = updated
                return
        raise KeyError(updated.candidate_id)


class SessionStore:
    """Thread-safe in-memory session map with temp-file cleanup.

    In addition to the map lock, each session has a dedicated ``RLock`` so
    mutating operations (review, confirm, match, upload, export) are serialized
    per session even across concurrent HTTP requests.
    """

    def __init__(self, *, ttl_seconds: int = 6 * 60 * 60) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.RLock()
        self._sessions: dict[str, ProcessingSession] = {}
        self._session_locks: dict[str, threading.RLock] = {}

    def create(self) -> ProcessingSession:
        self.cleanup_expired()
        session_id = str(uuid4())
        work_dir = Path(tempfile.mkdtemp(prefix=f"gheymatyar-{session_id}-"))
        session = ProcessingSession(
            session_id=session_id,
            created_at=time.time(),
            work_dir=work_dir,
        )
        with self._lock:
            self._sessions[session_id] = session
            self._session_locks[session_id] = threading.RLock()
        return session

    def get(self, session_id: str) -> ProcessingSession | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if time.time() - session.created_at > self._ttl:
                self._delete_unlocked(session_id)
                return None
            return session

    def require(self, session_id: str) -> ProcessingSession:
        session = self.get(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def snapshot(self) -> list[ProcessingSession]:
        """Return live sessions without holding the map lock."""
        with self._lock:
            return list(self._sessions.values())

    def session_lock(self, session_id: str) -> threading.RLock:
        """Return the per-session mutation lock (creates nothing if missing)."""
        with self._lock:
            lock = self._session_locks.get(session_id)
            if lock is None:
                # Session may have expired; still return a throwaway lock so
                # callers that fail on require() don't deadlock.
                if session_id not in self._sessions:
                    return threading.RLock()
                lock = threading.RLock()
                self._session_locks[session_id] = lock
            return lock

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._delete_unlocked(session_id)

    def cleanup_expired(self) -> None:
        now = time.time()
        with self._lock:
            expired = [
                sid
                for sid, session in self._sessions.items()
                if now - session.created_at > self._ttl
            ]
            for sid in expired:
                self._delete_unlocked(sid)

    def _delete_unlocked(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        self._session_locks.pop(session_id, None)
        if session and session.work_dir and session.work_dir.exists():
            shutil.rmtree(session.work_dir, ignore_errors=True)


_STORE: SessionStore | None = None


def get_session_store() -> SessionStore:
    global _STORE
    if _STORE is None:
        _STORE = SessionStore()
    return _STORE
