"""Skill bundle validator.

Validates an uploaded zip against the safety rules in
``openspec/changes/add-agent-skills-management/design.md``:

- Size limit (configured by ``AGENT_SKILLS_MAX_UPLOAD_MB``)
- Zip-only format
- No path traversal (every entry must resolve under the destination root)
- No absolute-path entries
- No symlinks
- A top-level ``SKILL.md`` must be present

Validation is performed without extracting any file to the destination — we walk
the zip's central directory metadata only. Extraction is the installer's job and
runs only after this module returns successfully.
"""

from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath


# Unix file-mode constants stored in ``ZipInfo.external_attr`` (high 16 bits).
# The relevant chunk for us is the type field:
#   S_IFLNK == 0o120000  → symbolic link
S_IFMT = 0o170000
S_IFLNK = 0o120000


class SkillBundleError(Exception):
    """Base class for bundle validation failures."""

    code: str = "invalid_bundle"


class BundleTooLargeError(SkillBundleError):
    code = "bundle_too_large"


class BundleNotAZipError(SkillBundleError):
    code = "not_a_zip"


class PathTraversalError(SkillBundleError):
    code = "path_traversal"


class AbsolutePathError(SkillBundleError):
    code = "absolute_path_entry"


class SymlinkError(SkillBundleError):
    code = "symlink_entry"


class MissingManifestError(SkillBundleError):
    code = "missing_skill_md"


@dataclass(slots=True)
class ValidationReport:
    skill_md_arcname: str
    entry_count: int


def validate_zip_bytes(data: bytes, *, max_size_bytes: int) -> ValidationReport:
    """Validate a raw zip byte string. Raises ``SkillBundleError`` on rejection."""
    if len(data) > max_size_bytes:
        raise BundleTooLargeError(
            f"upload size {len(data)} exceeds limit {max_size_bytes}"
        )

    try:
        zf = zipfile.ZipFile(_BytesIOSeekable(data))
    except zipfile.BadZipFile as exc:
        raise BundleNotAZipError("file is not a valid zip archive") from exc

    skill_md: str | None = None
    entries = zf.infolist()
    for info in entries:
        name = info.filename
        # Reject absolute paths regardless of whether they would resolve outside.
        if name.startswith("/") or name.startswith("\\"):
            raise AbsolutePathError(f"absolute path entry not allowed: {name!r}")
        # On Windows-style absolute paths.
        if len(name) >= 2 and name[1] == ":":
            raise AbsolutePathError(f"absolute path entry not allowed: {name!r}")

        # Reject symlinks via Unix mode bits in external_attr.
        unix_mode = (info.external_attr >> 16) & 0xFFFF
        if (unix_mode & S_IFMT) == S_IFLNK:
            raise SymlinkError(f"symlink entry not allowed: {name!r}")

        # Path-traversal guard: resolve the posix path against an imaginary root
        # ``/dest`` and ensure it stays inside.
        resolved = os.path.normpath(os.path.join("/dest", name))
        if not (resolved == "/dest" or resolved.startswith("/dest/")):
            raise PathTraversalError(f"entry escapes destination: {name!r}")

        # Detect SKILL.md as a top-level (no directory) entry.
        posix = PurePosixPath(name)
        if (
            len(posix.parts) == 1
            and posix.name.lower() == "skill.md"
            and not info.is_dir()
        ):
            skill_md = info.filename

    if skill_md is None:
        raise MissingManifestError("zip is missing a top-level SKILL.md")

    return ValidationReport(skill_md_arcname=skill_md, entry_count=len(entries))


class _BytesIOSeekable:
    """Thin wrapper to expose bytes as a seekable stream for zipfile."""

    def __init__(self, data: bytes) -> None:
        from io import BytesIO

        self._buffer = BytesIO(data)

    def read(self, n: int = -1) -> bytes:
        return self._buffer.read(n)

    def seek(self, offset: int, whence: int = 0) -> int:
        return self._buffer.seek(offset, whence)

    def tell(self) -> int:
        return self._buffer.tell()

    def close(self) -> None:
        self._buffer.close()
