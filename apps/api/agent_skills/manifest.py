"""SKILL.md frontmatter parser.

A skill manifest is a Markdown file with YAML frontmatter::

    ---
    name: anthropic/xlsx
    description: Tools for reading and writing Excel workbooks
    version: 1.2.0
    ---

    # Skill documentation in markdown after the frontmatter.

We require ``name`` and ``description``. ``version`` is optional (defaults to an
empty string, which the registry stores as-is). The parser does NOT pull in
PyYAML — frontmatter for skills is intentionally a simple key/value-per-line
format so the validation surface stays small.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ManifestError(Exception):
    code: str = "manifest_invalid"


class MissingFieldError(ManifestError):
    code = "manifest_missing_field"

    def __init__(self, field: str) -> None:
        super().__init__(f"SKILL.md is missing required field: {field}")
        self.field = field


class MalformedFrontmatterError(ManifestError):
    code = "manifest_malformed"


@dataclass(slots=True)
class SkillManifest:
    name: str
    description: str
    version: str = ""
    extras: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "version": self.version,
        }
        if self.extras:
            payload.update(self.extras)
        return payload


_FRONTMATTER_DELIMITER = "---"


def parse_manifest(content: str) -> SkillManifest:
    """Parse a SKILL.md ``content`` string and return a :class:`SkillManifest`.

    Raises :class:`MalformedFrontmatterError` if the document does not begin with
    a frontmatter block, and :class:`MissingFieldError` if a required key is
    missing or blank.
    """
    text = content.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    # Skip a possible BOM and leading blank lines.
    cursor = 0
    while cursor < len(lines) and lines[cursor].strip() == "":
        cursor += 1
    if cursor >= len(lines) or lines[cursor].strip() != _FRONTMATTER_DELIMITER:
        raise MalformedFrontmatterError(
            "SKILL.md must begin with a YAML-style frontmatter block delimited by '---'"
        )
    cursor += 1
    block_start = cursor
    while cursor < len(lines) and lines[cursor].strip() != _FRONTMATTER_DELIMITER:
        cursor += 1
    if cursor >= len(lines):
        raise MalformedFrontmatterError("SKILL.md frontmatter block is not closed with '---'")

    block_lines = lines[block_start:cursor]
    fields: dict[str, str] = {}
    for raw in block_lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise MalformedFrontmatterError(
                f"frontmatter line is not a 'key: value' pair: {raw!r}"
            )
        key, _, value = line.partition(":")
        key = key.strip()
        if not key:
            raise MalformedFrontmatterError(f"frontmatter key is blank: {raw!r}")
        fields[key.lower()] = _unquote(value.strip())

    name = fields.get("name", "").strip()
    description = fields.get("description", "").strip()
    version = fields.get("version", "").strip()

    if not name:
        raise MissingFieldError("name")
    if not description:
        raise MissingFieldError("description")

    extras = {
        k: v for k, v in fields.items() if k not in {"name", "description", "version"}
    } or None

    return SkillManifest(name=name, description=description, version=version, extras=extras)


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value
