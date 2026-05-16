"""Section 9 integration test: WriteIngestionAgent prompt + plugin wiring.

A full ingestion-lifecycle test (uploads → plan → approve → execute) would
require a real LLM endpoint and the actual vendored Anthropic xlsx skill zip on
disk — neither is available in the unit-test sandbox. Instead this test
exercises the wiring contract: when ``LEGACY_XLSX_PARSER_ENABLED=false`` and the
xlsx skill is installed + assigned to ``WriteIngestionAgent``, the SDK options
builder reflects both the augmented prompt and the skill plugin path.

The end-to-end lifecycle is covered by ``tests/smoke/run_smoke_flow.py``
with the ``--with-skills`` flag (added in section 12) once the operator has
vendored the real xlsx zip.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest


SKILL_MD = """---
name: anthropic/xlsx
description: Tools for reading and writing Excel workbooks
version: 1.2.0
---

# xlsx skill
"""


@pytest.fixture()
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'state.db'}")
    monkeypatch.setenv("MODEL_PROVIDER_URL", "http://localhost:11434")
    monkeypatch.setenv("AUTH_SECRET", "test-secret-section9")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("AGENT_SKILLS_ENABLED", "true")
    monkeypatch.setenv("AGENT_SKILLS_DIR", str(tmp_path / "skills"))
    monkeypatch.setenv("LEGACY_XLSX_PARSER_ENABLED", "false")

    from apps.api.config import get_settings
    from apps.api.agent_skills.registry import clear_skill_registry_cache
    from apps.api.agent_skills.loader import invalidate_skill_loader_cache

    get_settings.cache_clear()
    clear_skill_registry_cache()
    invalidate_skill_loader_cache()
    return tmp_path


def _install_xlsx_skill(tmp_path: Path) -> Path:
    skills_root = tmp_path / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)
    bundle = skills_root / "xlsx-bundle"
    bundle.mkdir()
    (bundle / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")

    from apps.api.agent_skills import get_skill_registry
    from apps.api.agent_skills.agents import WRITE_INGESTION_AGENT

    registry = get_skill_registry()
    registry.upsert(
        skill_id="xlsx-skill-id",
        name="anthropic/xlsx",
        version="1.2.0",
        sha256="0" * 64,
        uploaded_by="bootstrap",
        bundle_dir=str(bundle),
        manifest={"name": "anthropic/xlsx", "description": "xlsx"},
        status="enabled",
    )
    registry.assign(
        skill_id="xlsx-skill-id",
        agent_name=WRITE_INGESTION_AGENT,
        assigned_by="bootstrap",
    )
    return bundle


def test_legacy_off_includes_xlsx_skill_suffix_in_prompt(env: Path) -> None:
    from apps.api.agentic_ingestion.runtime import (
        INGESTION_AGENT_SYSTEM_PROMPT,
        XLSX_SKILL_PROMPT_SUFFIX,
        build_ingestion_system_prompt,
    )

    prompt = build_ingestion_system_prompt()
    assert prompt.startswith(INGESTION_AGENT_SYSTEM_PROMPT)
    assert prompt.endswith(XLSX_SKILL_PROMPT_SUFFIX)
    assert "xlsx skill" in prompt.lower()


def test_legacy_on_omits_xlsx_skill_suffix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'state.db'}")
    monkeypatch.setenv("MODEL_PROVIDER_URL", "http://localhost:11434")
    monkeypatch.setenv("AUTH_SECRET", "test-secret-section9")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("AGENT_SKILLS_ENABLED", "true")
    monkeypatch.setenv("LEGACY_XLSX_PARSER_ENABLED", "true")

    from apps.api.config import get_settings

    get_settings.cache_clear()

    from apps.api.agentic_ingestion.runtime import (
        XLSX_SKILL_PROMPT_SUFFIX,
        build_ingestion_system_prompt,
    )

    prompt = build_ingestion_system_prompt()
    assert XLSX_SKILL_PROMPT_SUFFIX not in prompt


def test_assigned_skill_path_flows_to_load_skill_plugins_for_agent(env: Path) -> None:
    bundle = _install_xlsx_skill(env)

    from apps.api.agent_skills.agents import WRITE_INGESTION_AGENT
    from apps.api.agent_skills.loader import (
        invalidate_skill_loader_cache,
        load_skill_plugins_for_agent,
    )

    invalidate_skill_loader_cache()
    plugins = load_skill_plugins_for_agent(WRITE_INGESTION_AGENT)
    assert plugins, "expected the xlsx skill to be loaded for WriteIngestionAgent"
    assert any(Path(p["path"]).resolve() == bundle.resolve() for p in plugins)
    assert all(p["type"] == "local" for p in plugins)


def test_disabled_skill_is_excluded_even_with_legacy_off(env: Path) -> None:
    _install_xlsx_skill(env)

    from apps.api.agent_skills import get_skill_registry
    from apps.api.agent_skills.agents import WRITE_INGESTION_AGENT
    from apps.api.agent_skills.loader import (
        invalidate_skill_loader_cache,
        load_skill_plugins_for_agent,
    )

    get_skill_registry().set_status("xlsx-skill-id", "disabled")
    invalidate_skill_loader_cache()
    assert load_skill_plugins_for_agent(WRITE_INGESTION_AGENT) == []
