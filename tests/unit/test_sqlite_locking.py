"""Regression tests for `sqlite3.OperationalError: database is locked`.

Every state store in the API points at the same handful of SQLite files, so a
writer that keeps a transaction open across an LLM round-trip locks out every
other write (login, chat-history saves) until it finishes.  These tests pin the
two properties that prevent that: WAL + a real busy timeout on every connection,
and an ingestion tool loop that never leaves a transaction open.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from apps.api import sqlite_support
from apps.api.agentic_ingestion.runtime import WriteIngestionAgentRuntime
from apps.api.config import get_settings


@pytest.fixture(autouse=True)
def _clear_caches() -> Iterator[None]:
    sqlite_support.reset_caches()
    yield
    get_settings.cache_clear()
    sqlite_support.reset_caches()


def _set_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'workspace-state.db'}")
    monkeypatch.setenv("MODEL_PROVIDER_URL", "http://localhost:11434")
    monkeypatch.setenv("AI_API_KEY", "test-ai-key")
    monkeypatch.setenv("AI_MODEL", "deepseek-chat")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    get_settings.cache_clear()


def test_connect_applies_wal_and_busy_timeout(tmp_path: Path) -> None:
    conn = sqlite_support.connect(tmp_path / "state.sqlite3", create_parents=True)
    try:
        assert str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"
        assert int(conn.execute("PRAGMA busy_timeout").fetchone()[0]) == (
            sqlite_support.DEFAULT_BUSY_TIMEOUT_MS
        )
        assert conn.row_factory is sqlite3.Row
    finally:
        conn.close()


def test_busy_timeout_follows_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _set_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SQLITE_BUSY_TIMEOUT_MS", "2500")
    get_settings.cache_clear()

    conn = sqlite_support.connect(tmp_path / "state.sqlite3")
    try:
        assert int(conn.execute("PRAGMA busy_timeout").fetchone()[0]) == 2500
    finally:
        conn.close()


def test_reader_is_not_blocked_by_an_open_write_transaction(tmp_path: Path) -> None:
    """WAL lets a reader through while a writer holds an uncommitted transaction.

    Under the default rollback journal this is exactly the shape that produced
    the 500s in production.
    """
    db_path = tmp_path / "state.sqlite3"
    writer = sqlite_support.connect(db_path, create_parents=True)
    reader = sqlite_support.connect(db_path)
    try:
        writer.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        writer.execute("INSERT INTO t (id, v) VALUES (1, 'committed')")
        writer.commit()

        writer.execute("INSERT INTO t (id, v) VALUES (2, 'uncommitted')")
        assert writer.in_transaction

        # The reader sees the committed snapshot immediately, no lock error.
        assert reader.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
    finally:
        writer.close()
        reader.close()


def test_busy_timeout_waits_instead_of_failing_immediately(tmp_path: Path) -> None:
    """A second writer waits for the busy timeout rather than erroring at once."""
    db_path = tmp_path / "state.sqlite3"
    setup = sqlite_support.connect(db_path, create_parents=True)
    setup.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    setup.commit()
    setup.close()

    holding = threading.Event()
    released = threading.Event()

    # SQLite connections are thread-bound, so the holder opens, writes, and
    # commits entirely inside its own thread.
    def _hold_then_release() -> None:
        holder = sqlite_support.connect(db_path)
        try:
            holder.execute("INSERT INTO t (id, v) VALUES (1, 'held')")
            assert holder.in_transaction
            holding.set()
            time.sleep(0.4)
            holder.commit()
        finally:
            holder.close()
        released.set()

    thread = threading.Thread(target=_hold_then_release)
    thread.start()
    try:
        assert holding.wait(timeout=5)
        second = sqlite_support.connect(db_path)
        try:
            started = time.perf_counter()
            # Without a busy timeout this raises "database is locked" instantly.
            second.execute("INSERT INTO t (id, v) VALUES (2, 'waited')")
            second.commit()
            waited = time.perf_counter() - started
        finally:
            second.close()
    finally:
        thread.join()

    assert released.is_set()
    assert waited >= 0.2


def _runtime_with_job(tmp_path: Path) -> tuple[WriteIngestionAgentRuntime, sqlite3.Connection]:
    """A runtime plus a connection carrying just the table `_run_tool` writes to."""
    conn = sqlite_support.connect(tmp_path / "events.sqlite3", create_parents=True)
    conn.execute(
        """
        CREATE TABLE ingestion_events (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return WriteIngestionAgentRuntime(), conn


def test_run_tool_leaves_no_open_transaction_on_success(tmp_path: Path) -> None:
    runtime, conn = _runtime_with_job(tmp_path)
    trace: list[dict[str, object]] = []
    try:
        def handler() -> dict[str, object]:
            # A tool that writes, like create_catalog_entry does.
            conn.execute(
                "INSERT INTO ingestion_events (id, job_id, event_type, payload, created_at)"
                " VALUES ('tool-write', 'job-1', 'tool_side_effect', '{}', 'now')"
            )
            assert conn.in_transaction
            return {"ok": True}

        result = runtime._run_tool(  # noqa: SLF001
            conn=conn,
            job_id="job-1",
            trace=trace,
            name="get_workspace_catalog",
            arguments={"workspace_id": "ws-1"},
            handler=handler,
        )

        assert result == {"ok": True}
        # The lock is gone before the caller resumes the model.
        assert not conn.in_transaction

        rows = conn.execute(
            "SELECT event_type FROM ingestion_events ORDER BY rowid"
        ).fetchall()
        assert [str(row[0]) for row in rows] == [
            "tool_use",
            "tool_side_effect",
            "tool_result",
        ]
    finally:
        conn.close()


def test_run_tool_leaves_no_open_transaction_on_failure(tmp_path: Path) -> None:
    runtime, conn = _runtime_with_job(tmp_path)
    trace: list[dict[str, object]] = []
    try:
        def handler() -> dict[str, object]:
            conn.execute(
                "INSERT INTO ingestion_events (id, job_id, event_type, payload, created_at)"
                " VALUES ('partial', 'job-1', 'partial_write', '{}', 'now')"
            )
            raise RuntimeError("tool blew up")

        with pytest.raises(RuntimeError):
            runtime._run_tool(  # noqa: SLF001
                conn=conn,
                job_id="job-1",
                trace=trace,
                name="create_catalog_entry",
                arguments={"workspace_id": "ws-1"},
                handler=handler,
            )

        assert not conn.in_transaction

        rows = conn.execute(
            "SELECT event_type FROM ingestion_events ORDER BY rowid"
        ).fetchall()
        # tool_use survived (committed up front); the failed handler's partial
        # write was rolled back; the error was recorded.
        assert [str(row[0]) for row in rows] == ["tool_use", "tool_error"]
        assert trace[-1]["error"]["error"] == "tool blew up"  # type: ignore[index]
    finally:
        conn.close()
