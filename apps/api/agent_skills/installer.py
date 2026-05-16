"""Skill bundle installer.

Glues the validator, manifest parser, and registry together:

1. Validate the raw zip bytes against the safety rules.
2. Stream-extract into a temp directory.
3. Re-validate after extraction (defense in depth — no symlinks, nothing escapes).
4. Parse the top-level ``SKILL.md`` for the manifest.
5. Atomically move the validated tree into ``${AGENT_SKILLS_DIR}/<uuid>/``.
6. Upsert the registry row and return its ``skill_id``.

The installer never writes outside ``AGENT_SKILLS_DIR``. Failed installs leave no
partial state behind: temp dir is cleaned up on every exit path; the destination
directory is only published via ``os.replace`` after every check has passed.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .manifest import SkillManifest, parse_manifest
from .registry import AgentSkillRecord, SkillRegistry, get_skill_registry
from .validator import (
    AbsolutePathError,
    PathTraversalError,
    SymlinkError,
    validate_zip_bytes,
)

logger = logging.getLogger("cognitrix.agent_skills.installer")


@dataclass(slots=True)
class InstallResult:
    skill_id: str
    record: AgentSkillRecord
    manifest: SkillManifest


def install_skill_bundle(
    *,
    zip_bytes: bytes,
    max_size_bytes: int,
    skills_dir: Path,
    uploaded_by: str,
    registry: SkillRegistry | None = None,
) -> InstallResult:
    """Install a skill bundle. See module docstring for the pipeline."""
    reg = registry or get_skill_registry()
    report = validate_zip_bytes(zip_bytes, max_size_bytes=max_size_bytes)
    sha256 = hashlib.sha256(zip_bytes).hexdigest()
    skills_dir.mkdir(parents=True, exist_ok=True)

    skill_id = uuid.uuid4().hex
    final_dir = (skills_dir / skill_id).resolve()
    # ``mkdtemp`` returns a unique sibling directory we'll extract into; we move
    # it into place once everything is validated.
    temp_dir = Path(tempfile.mkdtemp(prefix=".incoming-", dir=skills_dir))

    try:
        _safe_extract(zip_bytes, dest=temp_dir)
        manifest_path = temp_dir / report.skill_md_arcname
        if not manifest_path.is_file():
            from .validator import MissingManifestError

            raise MissingManifestError("SKILL.md missing after extraction")
        manifest_text = manifest_path.read_text(encoding="utf-8")
        manifest = parse_manifest(manifest_text)

        # Publish atomically: rename the temp dir to the final location.
        os.replace(temp_dir, final_dir)
        published = True
    except Exception:
        published = False
        raise
    finally:
        if not published and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)

    record = reg.upsert(
        skill_id=skill_id,
        name=manifest.name,
        version=manifest.version,
        sha256=sha256,
        uploaded_by=uploaded_by,
        bundle_dir=str(final_dir),
        manifest=manifest.to_dict(),
    )
    logger.info(
        "skill_installed id=%s name=%s version=%s bundle_dir=%s",
        skill_id,
        manifest.name,
        manifest.version,
        final_dir,
    )
    return InstallResult(skill_id=skill_id, record=record, manifest=manifest)


def _safe_extract(zip_bytes: bytes, *, dest: Path) -> None:
    """Extract ``zip_bytes`` into ``dest`` re-checking every entry.

    The pre-check in :mod:`validator` already guards against malicious archives,
    but we recheck at extraction time so an attacker who could somehow bypass the
    pre-check (e.g. via a Trojan zip with diverging central directory and local
    file headers) still cannot escape ``dest``.
    """
    from io import BytesIO

    dest_resolved = dest.resolve()
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            name = info.filename
            if name.startswith("/") or name.startswith("\\"):
                raise AbsolutePathError(f"absolute path entry not allowed: {name!r}")
            if len(name) >= 2 and name[1] == ":":
                raise AbsolutePathError(f"absolute path entry not allowed: {name!r}")
            unix_mode = (info.external_attr >> 16) & 0xFFFF
            if (unix_mode & 0o170000) == 0o120000:
                raise SymlinkError(f"symlink entry not allowed: {name!r}")

            target_path = (dest_resolved / name).resolve()
            try:
                target_path.relative_to(dest_resolved)
            except ValueError as exc:
                raise PathTraversalError(f"entry escapes destination: {name!r}") from exc

            if info.is_dir():
                target_path.mkdir(parents=True, exist_ok=True)
                continue

            target_path.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info, "r") as src, open(target_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
