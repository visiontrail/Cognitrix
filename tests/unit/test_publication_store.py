from __future__ import annotations

from pathlib import Path

from apps.api.published_pages import PublishedPageStore, build_public_url


def _make_store(tmp_path: Path) -> PublishedPageStore:
    return PublishedPageStore(db_path=tmp_path / "published_pages.sqlite3")


def _create_page(store: PublishedPageStore, *, workspace_id: str, version: int):
    return store.create(
        workspace_id=workspace_id,
        version=version,
        published_by="alice",
        manifest_path=Path(f"/tmp/manifest-{version}.json"),
    )


def test_create_or_refresh_reuses_active_token(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    page1 = _create_page(store, workspace_id="ws-1", version=1)
    pub1 = store.upsert_publication(workspace_id="ws-1", active_page_id=page1.id, version=1)
    assert pub1.is_active is True
    assert pub1.token

    page2 = _create_page(store, workspace_id="ws-1", version=2)
    pub2 = store.upsert_publication(workspace_id="ws-1", active_page_id=page2.id, version=2)

    # Refresh in place: token is stable, but the active page/version advance.
    assert pub2.token == pub1.token
    assert pub2.active_page_id == page2.id
    assert pub2.version == 2


def test_tokens_are_unique_across_workspaces(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    a = store.upsert_publication(workspace_id="ws-a", active_page_id="page-a", version=1)
    b = store.upsert_publication(workspace_id="ws-b", active_page_id="page-b", version=1)
    assert a.token != b.token
    # Tokens are high entropy and not derivable from ids/version.
    assert "ws-a" not in a.token
    assert len(a.token) >= 20


def test_revoke_disables_token_resolution(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    pub = store.upsert_publication(workspace_id="ws-1", active_page_id="page-1", version=1)
    assert store.resolve_active_publication(token=pub.token) is not None

    store.revoke_publication(workspace_id="ws-1")
    assert store.resolve_active_publication(token=pub.token) is None

    status = store.get_publication(workspace_id="ws-1")
    assert status is not None
    assert status.is_active is False
    assert status.revoked_at is not None


def test_republish_after_revoke_mints_new_token(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    first = store.upsert_publication(workspace_id="ws-1", active_page_id="page-1", version=1)
    store.revoke_publication(workspace_id="ws-1")
    second = store.upsert_publication(workspace_id="ws-1", active_page_id="page-2", version=2)

    # The old revoked link must never come back to life.
    assert second.token != first.token
    assert store.resolve_active_publication(token=first.token) is None
    assert store.resolve_active_publication(token=second.token) is not None


def test_publications_are_independent_per_canvas_kind(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    web = store.upsert_publication(
        workspace_id="ws-1", active_page_id="page-web", version=1, canvas_kind="web_page"
    )
    free = store.upsert_publication(
        workspace_id="ws-1", active_page_id="page-free", version=2, canvas_kind="free_layout"
    )
    fixed = store.upsert_publication(
        workspace_id="ws-1", active_page_id="page-fixed", version=3, canvas_kind="fixed_size"
    )

    # One workspace, three canvas kinds, three distinct live tokens.
    assert len({web.token, free.token, fixed.token}) == 3
    for pub in (web, free, fixed):
        assert store.resolve_active_publication(token=pub.token) is not None

    assert {p.canvas_kind for p in store.list_publications(workspace_id="ws-1")} == {
        "web_page",
        "free_layout",
        "fixed_size",
    }

    # Refreshing one kind keeps its token and never touches the others.
    free_again = store.upsert_publication(
        workspace_id="ws-1", active_page_id="page-free-2", version=4, canvas_kind="free_layout"
    )
    assert free_again.token == free.token
    assert free_again.active_page_id == "page-free-2"

    # Revoking one kind leaves the other kinds resolvable.
    store.revoke_publication(workspace_id="ws-1", canvas_kind="free_layout")
    assert store.resolve_active_publication(token=free.token) is None
    assert store.resolve_active_publication(token=web.token) is not None
    assert store.resolve_active_publication(token=fixed.token) is not None
    assert store.get_publication(workspace_id="ws-1", canvas_kind="web_page") is not None


def test_legacy_single_pk_table_migrates_to_composite_key(tmp_path: Path) -> None:
    import sqlite3

    db_path = tmp_path / "published_pages.sqlite3"
    # Recreate the pre-migration shape: one publication row per workspace.
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE workspace_publications (
            workspace_id TEXT PRIMARY KEY,
            token TEXT NOT NULL UNIQUE,
            active_page_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            published_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            revoked_at TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO workspace_publications VALUES (?, ?, ?, ?, 1, ?, ?, NULL)",
        ("ws-legacy", "legacy-token", "page-legacy", 1, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    # Opening the store triggers the in-place migration.
    store = PublishedPageStore(db_path=db_path)

    # The legacy row survives with its token and now resolves under a kind bucket.
    assert store.resolve_active_publication(token="legacy-token") is not None
    legacy = store.get_publication(workspace_id="ws-legacy", canvas_kind="web_page")
    assert legacy is not None
    assert legacy.token == "legacy-token"

    # And a second canvas kind can now be published independently.
    free = store.upsert_publication(
        workspace_id="ws-legacy", active_page_id="page-free", version=2, canvas_kind="free_layout"
    )
    assert free.token != "legacy-token"
    assert store.resolve_active_publication(token="legacy-token") is not None


def test_unknown_token_resolves_to_none(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    assert store.resolve_active_publication(token="does-not-exist") is None
    assert store.resolve_active_publication(token="") is None


def test_build_public_url_uses_configured_base(monkeypatch, tmp_path: Path) -> None:
    from apps.api.config import get_settings

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'x.db'}")
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://share.example.com")
    get_settings.cache_clear()
    try:
        url = build_public_url("tok123", request_base_url="http://ignored")
        assert url == "https://share.example.com/p/tok123"
        # Falls back to request base when no configured base url.
        monkeypatch.setenv("PUBLIC_BASE_URL", "")
        get_settings.cache_clear()
        assert build_public_url("tok123", request_base_url="http://req.local") == "http://req.local/p/tok123"
    finally:
        get_settings.cache_clear()
