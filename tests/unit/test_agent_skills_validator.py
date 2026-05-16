from __future__ import annotations

import io
import zipfile

import pytest

from apps.api.agent_skills.manifest import (
    MalformedFrontmatterError,
    MissingFieldError,
    parse_manifest,
)
from apps.api.agent_skills.validator import (
    AbsolutePathError,
    BundleNotAZipError,
    BundleTooLargeError,
    MissingManifestError,
    PathTraversalError,
    SymlinkError,
    validate_zip_bytes,
)


# Mode constant for "symlink" entries in zip external_attr.
_SYMLINK_MODE = 0o120777 << 16


SKILL_MD = """---
name: anthropic/xlsx
description: Tools for reading and writing Excel workbooks
version: 1.2.0
---

# xlsx skill
"""


def _make_zip(entries: list[tuple[str, bytes, int | None]]) -> bytes:
    """Build a zip in-memory.

    Each tuple is ``(arcname, data, external_attr_or_None)``. When
    ``external_attr_or_None`` is set, it overrides the entry's external_attr
    (used for the symlink test). ``data`` is the file body for non-dir entries.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for arcname, data, external_attr in entries:
            info = zipfile.ZipInfo(arcname)
            if external_attr is not None:
                info.external_attr = external_attr
            zf.writestr(info, data)
    return buffer.getvalue()


# ----------------------------------------------------------------------
# Validator
# ----------------------------------------------------------------------


def test_validator_accepts_well_formed_bundle() -> None:
    payload = _make_zip(
        [
            ("SKILL.md", SKILL_MD.encode("utf-8"), None),
            ("assets/data.csv", b"a,b\n1,2\n", None),
        ]
    )
    report = validate_zip_bytes(payload, max_size_bytes=10 * 1024 * 1024)
    assert report.skill_md_arcname == "SKILL.md"
    assert report.entry_count == 2


def test_validator_rejects_oversized_upload() -> None:
    payload = _make_zip([("SKILL.md", SKILL_MD.encode("utf-8"), None)])
    with pytest.raises(BundleTooLargeError):
        validate_zip_bytes(payload, max_size_bytes=10)


def test_validator_rejects_non_zip_bytes() -> None:
    with pytest.raises(BundleNotAZipError):
        validate_zip_bytes(b"hello world", max_size_bytes=1024)


def test_validator_rejects_path_traversal_entry() -> None:
    payload = _make_zip(
        [
            ("SKILL.md", SKILL_MD.encode("utf-8"), None),
            ("../etc/passwd", b"root:x:0:0::/:/bin/sh\n", None),
        ]
    )
    with pytest.raises(PathTraversalError):
        validate_zip_bytes(payload, max_size_bytes=1024 * 1024)


def test_validator_rejects_unix_absolute_path() -> None:
    payload = _make_zip(
        [
            ("SKILL.md", SKILL_MD.encode("utf-8"), None),
            ("/abs/file.txt", b"x", None),
        ]
    )
    with pytest.raises(AbsolutePathError):
        validate_zip_bytes(payload, max_size_bytes=1024 * 1024)


def test_validator_rejects_windows_absolute_path() -> None:
    payload = _make_zip(
        [
            ("SKILL.md", SKILL_MD.encode("utf-8"), None),
            ("C:/Windows/system32/evil.dll", b"x", None),
        ]
    )
    with pytest.raises(AbsolutePathError):
        validate_zip_bytes(payload, max_size_bytes=1024 * 1024)


def test_validator_rejects_symlink_entry() -> None:
    payload = _make_zip(
        [
            ("SKILL.md", SKILL_MD.encode("utf-8"), None),
            ("link-to-passwd", b"/etc/passwd", _SYMLINK_MODE),
        ]
    )
    with pytest.raises(SymlinkError):
        validate_zip_bytes(payload, max_size_bytes=1024 * 1024)


def test_validator_rejects_missing_skill_md() -> None:
    payload = _make_zip([("README.md", b"hi", None)])
    with pytest.raises(MissingManifestError):
        validate_zip_bytes(payload, max_size_bytes=1024 * 1024)


def test_validator_rejects_skill_md_inside_subdirectory() -> None:
    payload = _make_zip(
        [
            ("nested/SKILL.md", SKILL_MD.encode("utf-8"), None),
        ]
    )
    with pytest.raises(MissingManifestError):
        validate_zip_bytes(payload, max_size_bytes=1024 * 1024)


# ----------------------------------------------------------------------
# Manifest parser
# ----------------------------------------------------------------------


def test_manifest_parser_happy_path() -> None:
    manifest = parse_manifest(SKILL_MD)
    assert manifest.name == "anthropic/xlsx"
    assert manifest.description.startswith("Tools for reading")
    assert manifest.version == "1.2.0"


def test_manifest_parser_strips_quotes() -> None:
    text = """---
name: "anthropic/xlsx"
description: 'Excel toolkit'
---

body
"""
    manifest = parse_manifest(text)
    assert manifest.name == "anthropic/xlsx"
    assert manifest.description == "Excel toolkit"


def test_manifest_parser_rejects_missing_name() -> None:
    text = """---
description: only a description
---
"""
    with pytest.raises(MissingFieldError) as exc:
        parse_manifest(text)
    assert exc.value.field == "name"


def test_manifest_parser_rejects_missing_description() -> None:
    text = """---
name: anthropic/xlsx
---
"""
    with pytest.raises(MissingFieldError) as exc:
        parse_manifest(text)
    assert exc.value.field == "description"


def test_manifest_parser_rejects_missing_frontmatter() -> None:
    text = "no frontmatter here\n"
    with pytest.raises(MalformedFrontmatterError):
        parse_manifest(text)


def test_manifest_parser_rejects_unclosed_frontmatter() -> None:
    text = "---\nname: a\ndescription: b\n"
    with pytest.raises(MalformedFrontmatterError):
        parse_manifest(text)


def test_manifest_parser_rejects_malformed_kv_line() -> None:
    text = """---
name: a
description: b
just_a_key_no_colon
---
"""
    with pytest.raises(MalformedFrontmatterError):
        parse_manifest(text)


def test_manifest_parser_preserves_extras() -> None:
    text = """---
name: anthropic/xlsx
description: Excel toolkit
author: Anthropic
license: MIT
---
"""
    manifest = parse_manifest(text)
    assert manifest.extras == {"author": "Anthropic", "license": "MIT"}
    payload = manifest.to_dict()
    assert payload["author"] == "Anthropic"
