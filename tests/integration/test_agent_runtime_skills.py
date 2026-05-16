"""Loader integration tests (section 7 of OpenSpec change).

Verifies the contract the agent runtime relies on: an assigned, enabled skill
appears in the loaded path list; a disabled skill is skipped even when assigned;
a broken skill (bundle dir missing on disk) is dropped without raising and a
load error is persisted into the registry so it surfaces in the admin UI.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterator

import pytest


SKILL_BODY = """---
name: cognitrix/loader-fixture
description: Skill bundle used by loader integration tests
version: 0.0.1
---

# fixture
"""


@pytest.fixture()
def configured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'state.db'}")
    monkeypatch.setenv("MODEL_PROVIDER_URL", "http://localhost:11434")
    monkeypatch.setenv("AUTH_SECRET", "test-secret-runtime-skills")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("AGENT_SKILLS_ENABLED", "true")
    monkeypatch.setenv("AGENT_SKILLS_DIR", str(tmp_path / "skills"))
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_EMAIL", "")
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMIN_PASSWORD", "")
    monkeypatch.setenv("AUTH_BOOTSTRAP_SUPERADMIN_EMAIL", "")

    from apps.api.config import get_settings
    from apps.api.agent_skills.registry import clear_skill_registry_cache
    from apps.api.agent_skills.loader import invalidate_skill_loader_cache

    get_settings.cache_clear()
    clear_skill_registry_cache()
    invalidate_skill_loader_cache()

    yield tmp_path

    invalidate_skill_loader_cache()


def _install_skill(name: str, *, skills_root: Path) -> Path:
    bundle_dir = skills_root / name.replace("/", "_")
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "SKILL.md").write_text(SKILL_BODY, encoding="utf-8")
    return bundle_dir


def _register(skill_id: str, *, bundle_dir: Path, status: str = "enabled") -> None:
    from apps.api.agent_skills import get_skill_registry

    reg = get_skill_registry()
    reg.upsert(
        skill_id=skill_id,
        name=f"cognitrix/{skill_id}",
        version="0.0.1",
        sha256="0" * 64,
        uploaded_by="test",
        bundle_dir=str(bundle_dir),
        manifest={"name": f"cognitrix/{skill_id}", "description": "fixture"},
        status=status,
    )


def test_assigned_enabled_skill_is_loaded(configured: Path) -> None:
    from apps.api.agent_skills import get_skill_registry
    from apps.api.agent_skills.agents import WRITE_INGESTION_AGENT
    from apps.api.agent_skills.loader import (
        invalidate_skill_loader_cache,
        load_skills_for_agent,
    )

    skills_root = configured / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)
    bundle = _install_skill("first", skills_root=skills_root)
    _register("first", bundle_dir=bundle, status="enabled")
    get_skill_registry().assign(
        skill_id="first",
        agent_name=WRITE_INGESTION_AGENT,
        assigned_by="test",
    )

    invalidate_skill_loader_cache()
    loaded = load_skills_for_agent(WRITE_INGESTION_AGENT)
    assert bundle.resolve() in {p.resolve() for p in loaded}


def test_disabled_skill_is_skipped(configured: Path) -> None:
    from apps.api.agent_skills import get_skill_registry
    from apps.api.agent_skills.agents import WRITE_INGESTION_AGENT
    from apps.api.agent_skills.loader import (
        invalidate_skill_loader_cache,
        load_skills_for_agent,
    )

    skills_root = configured / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)
    bundle = _install_skill("second", skills_root=skills_root)
    _register("second", bundle_dir=bundle, status="disabled")
    get_skill_registry().assign(
        skill_id="second",
        agent_name=WRITE_INGESTION_AGENT,
        assigned_by="test",
    )

    invalidate_skill_loader_cache()
    loaded = load_skills_for_agent(WRITE_INGESTION_AGENT)
    assert bundle.resolve() not in {p.resolve() for p in loaded}


def test_broken_skill_does_not_crash_and_records_load_error(configured: Path) -> None:
    from apps.api.agent_skills import get_skill_registry
    from apps.api.agent_skills.agents import WRITE_INGESTION_AGENT
    from apps.api.agent_skills.loader import (
        invalidate_skill_loader_cache,
        load_skills_for_agent,
    )

    skills_root = configured / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)
    bundle = _install_skill("third", skills_root=skills_root)
    _register("third", bundle_dir=bundle, status="enabled")
    get_skill_registry().assign(
        skill_id="third",
        agent_name=WRITE_INGESTION_AGENT,
        assigned_by="test",
    )
    # Now remove the bundle dir to simulate corruption.
    shutil.rmtree(bundle)

    invalidate_skill_loader_cache()
    loaded = load_skills_for_agent(WRITE_INGESTION_AGENT)
    assert all(p.resolve() != bundle.resolve() for p in loaded)

    record = get_skill_registry().get("third")
    assert record.load_error is not None
    assert "missing" in record.load_error.lower()


def test_disabled_feature_flag_returns_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'state.db'}")
    monkeypatch.setenv("MODEL_PROVIDER_URL", "http://localhost:11434")
    monkeypatch.setenv("AUTH_SECRET", "test-secret-runtime-skills")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("AGENT_SKILLS_ENABLED", "false")

    from apps.api.config import get_settings
    from apps.api.agent_skills.loader import (
        invalidate_skill_loader_cache,
        load_skills_for_agent,
    )
    from apps.api.agent_skills.agents import WRITE_INGESTION_AGENT

    get_settings.cache_clear()
    invalidate_skill_loader_cache()
    assert load_skills_for_agent(WRITE_INGESTION_AGENT) == []


def test_unknown_agent_returns_empty(configured: Path) -> None:
    from apps.api.agent_skills.loader import load_skills_for_agent

    assert load_skills_for_agent("MysteryAgent") == []


def test_cache_busts_on_invalidate(configured: Path) -> None:
    from apps.api.agent_skills import get_skill_registry
    from apps.api.agent_skills.agents import QUERY_AGENT
    from apps.api.agent_skills.loader import (
        invalidate_skill_loader_cache,
        load_skills_for_agent,
        _peek_cached_paths,
    )

    skills_root = configured / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)
    bundle_a = _install_skill("alpha", skills_root=skills_root)
    _register("alpha", bundle_dir=bundle_a, status="enabled")
    get_skill_registry().assign(
        skill_id="alpha",
        agent_name=QUERY_AGENT,
        assigned_by="test",
    )

    invalidate_skill_loader_cache()
    first = load_skills_for_agent(QUERY_AGENT)
    assert _peek_cached_paths(QUERY_AGENT) is not None

    # Add a second skill — without invalidation the cache should still return
    # only the first one.
    bundle_b = _install_skill("beta", skills_root=skills_root)
    _register("beta", bundle_dir=bundle_b, status="enabled")
    get_skill_registry().assign(
        skill_id="beta",
        agent_name=QUERY_AGENT,
        assigned_by="test",
    )
    cached = load_skills_for_agent(QUERY_AGENT)
    assert cached == first

    invalidate_skill_loader_cache()
    refreshed = load_skills_for_agent(QUERY_AGENT)
    assert {p.resolve() for p in refreshed} == {bundle_a.resolve(), bundle_b.resolve()}
