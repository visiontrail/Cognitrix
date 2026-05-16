"""Integration tests for the vendored xlsx-skill bootstrap (section 8).

Verifies install, idempotency, sha256 mismatch fail-loud-but-not-crash, and
that the installed skill is assigned to WriteIngestionAgent.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path
from typing import Iterator

import pytest


SKILL_MD = """---
name: anthropic/xlsx
description: Tools for reading and writing Excel workbooks
version: 1.2.0
---

# xlsx skill
"""


def _build_xlsx_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("SKILL.md", SKILL_MD.encode("utf-8"))
        zf.writestr("assets/note.txt", b"placeholder")
    return buffer.getvalue()


def _write_versions_md(vendor_dir: Path, *, version: str, sha256: str) -> None:
    (vendor_dir / "VERSIONS.md").write_text(
        "# Vendored Skill Bundles\n\n"
        "## anthropic/xlsx\n\n"
        f"- **File:** `anthropic-xlsx-{version}.zip`\n"
        "- **Upstream:** https://mcpservers.org/agent-skills/anthropic/xlsx\n"
        f"- **Version:** {version}\n"
        f"- **Upstream sha256:** {sha256}\n",
        encoding="utf-8",
    )


@pytest.fixture()
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'state.db'}")
    monkeypatch.setenv("MODEL_PROVIDER_URL", "http://localhost:11434")
    monkeypatch.setenv("AUTH_SECRET", "test-secret-bootstrap")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("AGENT_SKILLS_ENABLED", "true")
    monkeypatch.setenv("AGENT_SKILLS_DIR", str(tmp_path / "skills"))
    monkeypatch.setenv("AGENT_SKILLS_MAX_UPLOAD_MB", "5")

    from apps.api.config import get_settings
    from apps.api.agent_skills.registry import clear_skill_registry_cache
    from apps.api.agent_skills.loader import invalidate_skill_loader_cache
    from apps.api.audit import clear_audit_logger_cache

    get_settings.cache_clear()
    clear_skill_registry_cache()
    invalidate_skill_loader_cache()
    clear_audit_logger_cache()

    yield tmp_path


def _vendor_dir(tmp_path: Path, *, version: str = "1.2.0") -> tuple[Path, bytes]:
    vendor = tmp_path / "vendor"
    vendor.mkdir(parents=True, exist_ok=True)
    payload = _build_xlsx_zip()
    sha = hashlib.sha256(payload).hexdigest()
    (vendor / f"anthropic-xlsx-{version}.zip").write_bytes(payload)
    _write_versions_md(vendor, version=version, sha256=sha)
    return vendor, payload


def test_first_run_installs_and_assigns_to_write_ingestion_agent(env: Path) -> None:
    from apps.api.agent_skills import get_skill_registry
    from apps.api.agent_skills.agents import WRITE_INGESTION_AGENT
    from apps.api.agent_skills.bootstrap import bootstrap_vendored_xlsx_skill

    vendor, _ = _vendor_dir(env)
    record = bootstrap_vendored_xlsx_skill(vendor_dir=vendor)
    assert record is not None
    assert record.name == "anthropic/xlsx"

    reg = get_skill_registry()
    assignments = reg.list_assignments_for_agent(WRITE_INGESTION_AGENT)
    assert any(a.skill_id == record.id for a in assignments)


def test_bootstrap_is_idempotent_on_second_run(env: Path) -> None:
    from apps.api.agent_skills import get_skill_registry
    from apps.api.agent_skills.agents import WRITE_INGESTION_AGENT
    from apps.api.agent_skills.bootstrap import bootstrap_vendored_xlsx_skill

    vendor, _ = _vendor_dir(env)
    first = bootstrap_vendored_xlsx_skill(vendor_dir=vendor)
    second = bootstrap_vendored_xlsx_skill(vendor_dir=vendor)
    assert first is not None and second is not None
    assert first.id == second.id

    reg = get_skill_registry()
    assignments = reg.list_assignments_for_agent(WRITE_INGESTION_AGENT)
    # No duplicate assignment row.
    matching = [a for a in assignments if a.skill_id == first.id]
    assert len(matching) == 1


def test_sha256_mismatch_does_not_install_and_does_not_crash(env: Path) -> None:
    from apps.api.agent_skills import get_skill_registry
    from apps.api.agent_skills.bootstrap import bootstrap_vendored_xlsx_skill

    vendor = env / "vendor"
    vendor.mkdir(parents=True, exist_ok=True)
    payload = _build_xlsx_zip()
    (vendor / "anthropic-xlsx-1.2.0.zip").write_bytes(payload)
    # Record a wrong sha256.
    _write_versions_md(vendor, version="1.2.0", sha256="0" * 64)

    record = bootstrap_vendored_xlsx_skill(vendor_dir=vendor)
    assert record is None  # Not installed
    assert get_skill_registry().get_by_name("anthropic/xlsx") is None


def test_missing_zip_skips_quietly(env: Path) -> None:
    from apps.api.agent_skills.bootstrap import bootstrap_vendored_xlsx_skill

    vendor = env / "vendor"
    vendor.mkdir(parents=True, exist_ok=True)
    _write_versions_md(vendor, version="1.2.0", sha256="0" * 64)

    # No zip on disk at all.
    record = bootstrap_vendored_xlsx_skill(vendor_dir=vendor)
    assert record is None


def test_placeholder_versions_md_skips(env: Path) -> None:
    from apps.api.agent_skills.bootstrap import bootstrap_vendored_xlsx_skill

    vendor = env / "vendor"
    vendor.mkdir(parents=True, exist_ok=True)
    payload = _build_xlsx_zip()
    (vendor / "anthropic-xlsx-1.2.0.zip").write_bytes(payload)
    # Placeholder values — bootstrap should treat this as "not vendored yet".
    (vendor / "VERSIONS.md").write_text(
        "## anthropic/xlsx\n\n"
        "- **Version:** _to be filled in after the bundle is vendored_\n"
        "- **Upstream sha256:** _to be filled in after the bundle is vendored_\n",
        encoding="utf-8",
    )

    assert bootstrap_vendored_xlsx_skill(vendor_dir=vendor) is None


def test_feature_flag_off_skips_bootstrap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'state.db'}")
    monkeypatch.setenv("MODEL_PROVIDER_URL", "http://localhost:11434")
    monkeypatch.setenv("AUTH_SECRET", "test-secret-bootstrap")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("AGENT_SKILLS_ENABLED", "false")

    from apps.api.config import get_settings
    from apps.api.agent_skills.registry import clear_skill_registry_cache
    from apps.api.agent_skills.bootstrap import bootstrap_vendored_xlsx_skill

    get_settings.cache_clear()
    clear_skill_registry_cache()

    vendor, _ = _vendor_dir(tmp_path)
    assert bootstrap_vendored_xlsx_skill(vendor_dir=vendor) is None
