"""Bootstrap routine for vendored skill bundles.

Currently installs Anthropic's ``anthropic/xlsx`` skill from
``apps/api/vendor/skills/anthropic-xlsx-<version>.zip`` and assigns it to the
``WriteIngestionAgent``.

The routine is **idempotent**: on subsequent startups it sees a registry row
named ``anthropic/xlsx`` and exits without reinstalling. It is also
**fail-loud-but-not-crash**: a sha256 mismatch, missing vendored file, or
checksum-not-yet-recorded state logs an error, surfaces it via the registry
``load_error`` column when a row already exists, and returns — the API still
boots so a super-admin can upload a correct bundle through the admin console.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from ..audit import get_audit_logger
from ..config import get_settings
from .agents import WRITE_INGESTION_AGENT
from .installer import install_skill_bundle
from .registry import (
    AgentSkillRecord,
    SkillRegistry,
    get_skill_registry,
)

logger = logging.getLogger("cognitrix.agent_skills.bootstrap")


VENDOR_DIR_NAME = "vendor/skills"
ANTHROPIC_XLSX_SKILL_NAME = "anthropic/xlsx"


_VERSION_LINE_RE = re.compile(r"^-\s*\*\*Version:\*\*\s*(?P<value>.+)\s*$")
_SHA256_LINE_RE = re.compile(r"^-\s*\*\*Upstream sha256:\*\*\s*(?P<value>.+)\s*$")
_PLACEHOLDER_TOKENS = {"", "_to be filled in after the bundle is vendored_"}


@dataclass(slots=True)
class _XlsxVendorEntry:
    version: str
    sha256: str


def _vendor_dir() -> Path:
    return (Path(__file__).resolve().parent.parent / VENDOR_DIR_NAME).resolve()


def _parse_versions_md(text: str) -> _XlsxVendorEntry | None:
    """Pull the recorded version + sha256 for anthropic/xlsx out of VERSIONS.md.

    Returns ``None`` if the section is missing or still holds placeholder values.
    """
    # Find the anthropic/xlsx section header, then scan lines until the next
    # `## ` header (or EOF).
    lines = text.splitlines()
    cursor = 0
    while cursor < len(lines):
        if lines[cursor].strip() == "## anthropic/xlsx":
            cursor += 1
            break
        cursor += 1
    else:
        return None

    version: str | None = None
    sha256: str | None = None
    while cursor < len(lines):
        line = lines[cursor]
        if line.startswith("## "):
            break
        match_v = _VERSION_LINE_RE.match(line.strip())
        if match_v:
            value = match_v.group("value").strip().strip("`")
            if value not in _PLACEHOLDER_TOKENS:
                version = value
        match_s = _SHA256_LINE_RE.match(line.strip())
        if match_s:
            value = match_s.group("value").strip().strip("`")
            if value not in _PLACEHOLDER_TOKENS:
                sha256 = value.lower()
        cursor += 1

    if not version or not sha256:
        return None
    return _XlsxVendorEntry(version=version, sha256=sha256)


def _select_xlsx_zip(vendor_dir: Path, *, version: str) -> Path | None:
    """Pick the on-disk zip whose filename embeds the recorded version.

    Filenames follow ``anthropic-xlsx-<version>.zip``. We prefer an exact
    version match. If none matches but a single candidate exists we fall back
    to it (and rely on sha256 verification to catch the wrong version).
    """
    if not vendor_dir.is_dir():
        return None
    exact = vendor_dir / f"anthropic-xlsx-{version}.zip"
    if exact.is_file():
        return exact
    candidates = sorted(vendor_dir.glob("anthropic-xlsx-*.zip"))
    return candidates[0] if candidates else None


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 16), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _audit_bootstrap(
    *,
    status: str,
    severity: str,
    detail: dict[str, object],
) -> None:
    get_audit_logger().log(
        event_type="agent_skills",
        action="skill_bootstrap_install",
        status=status,
        severity=severity,
        user_id="bootstrap",
        project_id="default",
        resource="admin.skills.bootstrap",
        detail=detail,
    )


def bootstrap_vendored_xlsx_skill(
    *,
    registry: SkillRegistry | None = None,
    vendor_dir: Path | None = None,
) -> AgentSkillRecord | None:
    """Install the vendored xlsx skill and assign it to WriteIngestionAgent.

    Returns the installed (or already-present) registry record, or ``None`` if
    the bootstrap was skipped (feature flag off, missing file, sha mismatch).
    """
    settings = get_settings()
    if not settings.agent_skills_enabled:
        return None

    reg = registry or get_skill_registry()
    existing = reg.get_by_name(ANTHROPIC_XLSX_SKILL_NAME)
    target_dir = vendor_dir or _vendor_dir()
    versions_md = target_dir / "VERSIONS.md"

    if not versions_md.is_file():
        logger.warning("xlsx_bootstrap_skip reason=versions_md_missing path=%s", versions_md)
        return existing

    entry = _parse_versions_md(versions_md.read_text(encoding="utf-8"))
    if entry is None:
        logger.warning(
            "xlsx_bootstrap_skip reason=versions_md_placeholder path=%s", versions_md
        )
        return existing

    zip_path = _select_xlsx_zip(target_dir, version=entry.version)
    if zip_path is None:
        logger.warning(
            "xlsx_bootstrap_skip reason=vendored_zip_missing dir=%s version=%s",
            target_dir,
            entry.version,
        )
        return existing

    actual_sha = _sha256(zip_path)
    if actual_sha.lower() != entry.sha256.lower():
        logger.error(
            "xlsx_bootstrap_checksum_mismatch path=%s expected=%s actual=%s",
            zip_path,
            entry.sha256,
            actual_sha,
        )
        _audit_bootstrap(
            status="failed",
            severity="ALERT",
            detail={
                "reason": "sha256_mismatch",
                "expected": entry.sha256,
                "actual": actual_sha,
                "path": str(zip_path),
            },
        )
        if existing is not None:
            try:
                reg.set_load_error(
                    existing.id,
                    f"vendored bundle sha256 mismatch (expected {entry.sha256}, got {actual_sha})",
                )
            except Exception:
                pass
        return existing

    if existing is not None:
        # Idempotent: skill is already installed under this name. Just ensure
        # the WriteIngestionAgent assignment exists.
        already_assigned = any(
            a.agent_name == WRITE_INGESTION_AGENT
            for a in reg.list_assignments_for_skill(existing.id)
        )
        if not already_assigned:
            reg.assign(
                skill_id=existing.id,
                agent_name=WRITE_INGESTION_AGENT,
                assigned_by="bootstrap",
            )
            _audit_bootstrap(
                status="success",
                severity="INFO",
                detail={
                    "skill_id": existing.id,
                    "agent_name": WRITE_INGESTION_AGENT,
                    "reason": "assigned_existing",
                },
            )
        return existing

    zip_bytes = zip_path.read_bytes()
    max_bytes = settings.agent_skills_max_upload_mb * 1024 * 1024
    result = install_skill_bundle(
        zip_bytes=zip_bytes,
        max_size_bytes=max_bytes,
        skills_dir=settings.resolved_agent_skills_dir,
        uploaded_by="bootstrap",
        registry=reg,
    )

    reg.assign(
        skill_id=result.skill_id,
        agent_name=WRITE_INGESTION_AGENT,
        assigned_by="bootstrap",
    )
    _audit_bootstrap(
        status="success",
        severity="INFO",
        detail={
            "skill_id": result.skill_id,
            "name": result.manifest.name,
            "version": result.manifest.version,
            "agent_name": WRITE_INGESTION_AGENT,
            "sha256": result.record.sha256,
        },
    )
    logger.info(
        "xlsx_bootstrap_installed skill_id=%s version=%s sha256=%s",
        result.skill_id,
        result.manifest.version,
        result.record.sha256,
    )
    return result.record


__all__ = [
    "ANTHROPIC_XLSX_SKILL_NAME",
    "bootstrap_vendored_xlsx_skill",
]
