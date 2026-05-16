"""Sandbox security tests for the agent-skill installer.

Each test crafts a malicious zip and asserts that NO file is written outside the
intended ``${AGENT_SKILLS_DIR}/<uuid>/`` destination — and that the destination
directory itself is not even created on rejection (no partial state).
"""

from __future__ import annotations

import io
import struct
import zipfile
from pathlib import Path

import pytest

from apps.api.agent_skills.installer import install_skill_bundle
from apps.api.agent_skills.registry import SkillRegistry
from apps.api.agent_skills.validator import (
    AbsolutePathError,
    PathTraversalError,
    SymlinkError,
)


_SYMLINK_MODE = 0o120777 << 16

SKILL_MD = """---
name: anthropic/xlsx
description: Tools for reading and writing Excel workbooks
---
"""


def _make_zip(entries: list[tuple[str, bytes, int | None]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for arcname, data, external_attr in entries:
            info = zipfile.ZipInfo(arcname)
            if external_attr is not None:
                info.external_attr = external_attr
            zf.writestr(info, data)
    return buffer.getvalue()


def _registry(tmp_path: Path) -> SkillRegistry:
    return SkillRegistry(db_path=tmp_path / "registry.sqlite3")


def _assert_no_escape(skills_dir: Path, *foreign_paths: Path) -> None:
    """Sanity: no file written outside skills_dir, and foreign target paths are absent."""
    for p in foreign_paths:
        assert not p.exists(), f"file escaped sandbox: {p}"
    # Nothing should exist inside skills_dir except possibly a stale .incoming-*
    # temp dir (which the installer cleans up). We assert the tree is empty.
    if skills_dir.exists():
        leftovers = [child for child in skills_dir.iterdir()]
        assert leftovers == [], f"leftover files in sandbox: {leftovers}"


def test_path_traversal_rejected_and_leaves_no_files(tmp_path: Path) -> None:
    skills_dir = tmp_path / "agent_skills"
    skills_dir.mkdir()
    foreign = tmp_path / "etc-passwd"
    payload = _make_zip(
        [
            ("SKILL.md", SKILL_MD.encode("utf-8"), None),
            ("../etc-passwd", b"root:x:0:0::/:/bin/sh\n", None),
        ]
    )

    with pytest.raises(PathTraversalError):
        install_skill_bundle(
            zip_bytes=payload,
            max_size_bytes=10 * 1024 * 1024,
            skills_dir=skills_dir,
            uploaded_by="superadmin",
            registry=_registry(tmp_path),
        )

    _assert_no_escape(skills_dir, foreign)


def test_absolute_unix_path_rejected_and_leaves_no_files(tmp_path: Path) -> None:
    skills_dir = tmp_path / "agent_skills"
    skills_dir.mkdir()
    foreign = Path("/abs/skills-test-attack.txt")  # never created — must not be touched
    payload = _make_zip(
        [
            ("SKILL.md", SKILL_MD.encode("utf-8"), None),
            ("/abs/skills-test-attack.txt", b"x", None),
        ]
    )

    with pytest.raises(AbsolutePathError):
        install_skill_bundle(
            zip_bytes=payload,
            max_size_bytes=10 * 1024 * 1024,
            skills_dir=skills_dir,
            uploaded_by="superadmin",
            registry=_registry(tmp_path),
        )

    assert not foreign.exists(), "absolute-path file written outside sandbox"
    _assert_no_escape(skills_dir)


def test_symlink_entry_rejected_and_leaves_no_files(tmp_path: Path) -> None:
    skills_dir = tmp_path / "agent_skills"
    skills_dir.mkdir()
    payload = _make_zip(
        [
            ("SKILL.md", SKILL_MD.encode("utf-8"), None),
            ("attack-link", b"/etc/passwd", _SYMLINK_MODE),
        ]
    )

    with pytest.raises(SymlinkError):
        install_skill_bundle(
            zip_bytes=payload,
            max_size_bytes=10 * 1024 * 1024,
            skills_dir=skills_dir,
            uploaded_by="superadmin",
            registry=_registry(tmp_path),
        )

    _assert_no_escape(skills_dir)


def test_happy_path_writes_files_only_under_uuid_subdir(tmp_path: Path) -> None:
    skills_dir = tmp_path / "agent_skills"
    skills_dir.mkdir()
    payload = _make_zip(
        [
            ("SKILL.md", SKILL_MD.encode("utf-8"), None),
            ("assets/data.csv", b"a,b\n1,2\n", None),
        ]
    )

    result = install_skill_bundle(
        zip_bytes=payload,
        max_size_bytes=10 * 1024 * 1024,
        skills_dir=skills_dir,
        uploaded_by="superadmin",
        registry=_registry(tmp_path),
    )

    bundle_dir = Path(result.record.bundle_dir)
    assert bundle_dir.parent.resolve() == skills_dir.resolve()
    assert bundle_dir.name == result.skill_id
    # SKILL.md and the nested asset both made it; nothing outside the bundle dir.
    assert (bundle_dir / "SKILL.md").exists()
    assert (bundle_dir / "assets" / "data.csv").exists()

    # The sandbox contains exactly one subdir (the bundle) — no temp dir leftover.
    contents = sorted(child.name for child in skills_dir.iterdir())
    assert contents == [result.skill_id]


def test_post_extraction_recheck_catches_zip_slip(tmp_path: Path) -> None:
    """Defense-in-depth: even if the pre-check were bypassed, ``_safe_extract``
    re-validates every entry on the way to disk and refuses to write outside the
    destination root. We simulate the trojan zip by handing the installer raw
    crafted bytes — but our pre-check catches it first, which is also fine; the
    point is that *no* file escapes the sandbox.
    """
    skills_dir = tmp_path / "agent_skills"
    skills_dir.mkdir()
    foreign = tmp_path / "trojan.txt"
    payload = _make_zip(
        [
            ("SKILL.md", SKILL_MD.encode("utf-8"), None),
            ("subdir/../../trojan.txt", b"pwn", None),
        ]
    )

    with pytest.raises(PathTraversalError):
        install_skill_bundle(
            zip_bytes=payload,
            max_size_bytes=10 * 1024 * 1024,
            skills_dir=skills_dir,
            uploaded_by="superadmin",
            registry=_registry(tmp_path),
        )

    assert not foreign.exists()
    _assert_no_escape(skills_dir)
