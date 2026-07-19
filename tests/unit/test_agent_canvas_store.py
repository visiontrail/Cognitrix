from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from apps.api.agent_canvas import (
    RUN_STATUS_AWAITING_APPROVAL,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_RUNNING,
    AgentCanvasRunStore,
    block_id_for,
    page_id_for,
)
from apps.api.agent_runtime import AgentSessionStore
from apps.api.config import get_settings


def _make_store(tmp_path: Path) -> AgentCanvasRunStore:
    return AgentCanvasRunStore(db_path=tmp_path / "state" / "agent_sessions.sqlite3")


def _table_names(db_path: Path) -> set[str]:
    if not db_path.exists():
        return set()
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row[0]) for row in rows}


def test_run_crud_roundtrip(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    run = store.create_run(
        conversation_id="conv-1",
        workspace_id="ws-1",
        user_id="alice",
        canvas_format="web-design",
        confirmation_id="dash-abc",
        outline={"title": "Sales overview", "sections": []},
    )

    assert run["status"] == RUN_STATUS_AWAITING_APPROVAL
    assert run["page_id"] == page_id_for(run["run_id"])
    assert run["outline"] == {"title": "Sales overview", "sections": []}

    loaded = store.get_run(run["run_id"])
    assert loaded is not None
    assert loaded["confirmation_id"] == "dash-abc"

    by_confirmation = store.get_run_by_confirmation("dash-abc")
    assert by_confirmation is not None
    assert by_confirmation["run_id"] == run["run_id"]

    store.update_status(run["run_id"], RUN_STATUS_RUNNING)
    active = store.get_active_run(workspace_id="ws-1", user_id="alice")
    assert active is not None
    assert active["run_id"] == run["run_id"]
    assert active["status"] == RUN_STATUS_RUNNING

    store.update_status(
        run["run_id"],
        RUN_STATUS_COMPLETED,
        summary={"placed": 3, "failed": 0},
    )
    assert store.get_active_run(workspace_id="ws-1", user_id="alice") is None
    latest = store.get_latest_run(workspace_id="ws-1", user_id="alice")
    assert latest is not None
    assert latest["status"] == RUN_STATUS_COMPLETED
    assert latest["summary"] == {"placed": 3, "failed": 0}

    # Other scopes never see this run.
    assert store.get_latest_run(workspace_id="ws-2", user_id="alice") is None
    assert store.get_latest_run(workspace_id="ws-1", user_id="bob") is None


def test_ops_append_and_replay(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    run = store.create_run(
        conversation_id="conv-1",
        workspace_id="ws-1",
        user_id="alice",
        canvas_format="web-design",
    )
    run_id = run["run_id"]

    first = store.append_op(
        run_id=run_id,
        op_type="create_page",
        payload=lambda seq: {"page_id": run["page_id"], "block_id": block_id_for(run_id, seq)},
    )
    second = store.append_op(
        run_id=run_id,
        op_type="add_section",
        payload=lambda seq: {"block_id": block_id_for(run_id, seq), "title": "概览"},
    )

    assert first["seq"] == 1
    assert second["seq"] == 2
    assert second["payload"]["block_id"] == block_id_for(run_id, 2)

    all_ops = store.list_ops_after(run_id=run_id, after_seq=0)
    assert [op["seq"] for op in all_ops] == [1, 2]
    assert all_ops[0]["op_type"] == "create_page"

    tail = store.list_ops_after(run_id=run_id, after_seq=1)
    assert [op["seq"] for op in tail] == [2]

    assert store.count_ops(run_id=run_id) == 2
    assert store.count_ops(run_id=run_id, op_type="add_section") == 1


def test_seq_monotonic_under_concurrent_appends(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    run = store.create_run(
        conversation_id="conv-1",
        workspace_id="ws-1",
        user_id="alice",
        canvas_format="web-design",
    )
    run_id = run["run_id"]

    def append(index: int) -> int:
        op = store.append_op(
            run_id=run_id,
            op_type="add_text_block",
            payload={"index": index},
        )
        return int(op["seq"])

    with ThreadPoolExecutor(max_workers=8) as pool:
        seqs = sorted(pool.map(append, range(40)))

    # Strictly increasing with no gaps, regardless of write interleaving.
    assert seqs == list(range(1, 41))
    stored = store.list_ops_after(run_id=run_id, after_seq=0)
    assert [op["seq"] for op in stored] == list(range(1, 41))


def test_tables_created_lazily(tmp_path: Path) -> None:
    db_path = tmp_path / "state" / "agent_sessions.sqlite3"
    store = AgentCanvasRunStore(db_path=db_path)

    # Constructing the store must not touch the database.
    assert "agent_canvas_runs" not in _table_names(db_path)

    store.create_run(
        conversation_id="conv-1",
        workspace_id="ws-1",
        user_id="alice",
        canvas_format="web-design",
    )
    names = _table_names(db_path)
    assert "agent_canvas_runs" in names
    assert "agent_canvas_ops" in names


def test_flag_off_leaves_session_store_untouched(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'views.db'}")
    monkeypatch.setenv("MODEL_PROVIDER_URL", "https://api.deepseek.com")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.agent_canvas_mode_enabled is False
        assert settings.agent_mode_max_steps == 40
        assert settings.agent_mode_timeout_seconds == 600.0
        assert settings.agent_mode_max_charts == 12

        # Normal session-store usage (flag off) never creates the canvas tables.
        db_path = settings.upload_dir / "state" / "agent_sessions.sqlite3"
        AgentSessionStore(db_path=db_path)
        names = _table_names(db_path)
        assert "agent_sessions" in names
        assert "agent_canvas_runs" not in names
        assert "agent_canvas_ops" not in names
    finally:
        get_settings.cache_clear()
