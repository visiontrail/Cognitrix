"""Runtime loader for assigned, enabled skills.

The agent runtime calls :func:`load_skills_for_agent` at the start of every turn
to discover which skill bundle directories should be exposed to the Claude
Agent SDK. Reads from SQLite are cheap but the runtime is on the hot path, so a
short TTL cache is layered on top. Admin writes call
:func:`invalidate_skill_loader_cache` to expire the cache immediately rather
than wait for TTL.

Each per-skill load attempt is independently guarded: if a skill's bundle is
missing on disk or fails an existence check, the failure is persisted into the
registry's ``load_error`` column (so it surfaces in ``/admin/skills``) and the
skill is dropped from the returned list. A broken skill MUST NOT crash the
agent — that's the spec's hard requirement.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ..config import get_settings
from .agents import NAMED_AGENTS
from .registry import (
    AgentSkillRecord,
    SkillRegistry,
    get_skill_registry,
)

logger = logging.getLogger("cognitrix.agent_skills.loader")

# 30s TTL matches the design doc; bust on admin writes.
_TTL_SECONDS = 30.0


@dataclass(slots=True)
class _CacheEntry:
    expires_at: float
    paths: list[Path]


_cache_lock = threading.Lock()
_cache: dict[str, _CacheEntry] = {}


def load_skills_for_agent(
    agent_name: str,
    *,
    registry: SkillRegistry | None = None,
    now: float | None = None,
) -> list[Path]:
    """Return filesystem paths for all enabled skills assigned to ``agent_name``.

    Honors :data:`Settings.agent_skills_enabled` — returns an empty list when
    the feature flag is off, regardless of registry state. Caches per-agent
    results for ``_TTL_SECONDS`` seconds. Skips bundles whose directory has
    disappeared on disk and records a ``load_error`` against the skill so the
    admin UI surfaces the problem.
    """

    settings = get_settings()
    if not settings.agent_skills_enabled:
        return []

    normalized = agent_name.strip()
    if normalized not in NAMED_AGENTS:
        return []

    current_time = now if now is not None else time.monotonic()
    with _cache_lock:
        cached = _cache.get(normalized)
        if cached is not None and cached.expires_at > current_time:
            return list(cached.paths)

    reg = registry or get_skill_registry()
    assignments = reg.list_assignments_for_agent(normalized)
    paths: list[Path] = []
    for assignment in assignments:
        try:
            record = reg.get(assignment.skill_id)
        except KeyError:
            continue
        if record.status != "enabled":
            continue
        bundle_dir = Path(record.bundle_dir)
        if not bundle_dir.is_dir():
            error = f"bundle_dir missing on disk: {bundle_dir}"
            try:
                reg.set_load_error(record.id, error)
            except Exception:
                pass
            logger.warning(
                "skill_bundle_missing skill_id=%s agent=%s bundle_dir=%s",
                record.id,
                normalized,
                bundle_dir,
            )
            continue
        manifest_path = bundle_dir / "SKILL.md"
        if not manifest_path.is_file():
            error = f"SKILL.md missing under {bundle_dir}"
            try:
                reg.set_load_error(record.id, error)
            except Exception:
                pass
            logger.warning(
                "skill_manifest_missing skill_id=%s agent=%s bundle_dir=%s",
                record.id,
                normalized,
                bundle_dir,
            )
            continue
        # Clear any prior load error for this skill — it loaded fine this turn.
        if record.load_error:
            try:
                reg.set_load_error(record.id, None)
            except Exception:
                pass
        paths.append(bundle_dir)

    with _cache_lock:
        _cache[normalized] = _CacheEntry(
            expires_at=current_time + _TTL_SECONDS,
            paths=list(paths),
        )
    return paths


def invalidate_skill_loader_cache() -> None:
    """Bust the per-agent skill-path cache.

    Called from every admin write so a toggle in the admin UI is visible on the
    next turn rather than after the TTL elapses.
    """
    with _cache_lock:
        _cache.clear()


def _build_plugin_configs(skill_paths: list[Path]) -> list[dict[str, str]]:
    """Helper for SDK runtimes — converts skill dirs to local-plugin configs.

    The Claude Agent SDK accepts ``plugins=[{"type": "local", "path": ...}]``
    in ``ClaudeAgentOptions``. Surfacing each enabled skill bundle as a local
    plugin entry is the most direct mechanism for the SDK to discover SKILL.md
    inside.
    """
    return [{"type": "local", "path": str(path)} for path in skill_paths]


def load_skill_plugins_for_agent(agent_name: str) -> list[dict[str, str]]:
    """Return SDK plugin config dicts for the assigned, enabled skills."""
    return _build_plugin_configs(load_skills_for_agent(agent_name))


__all__ = [
    "invalidate_skill_loader_cache",
    "load_skill_plugins_for_agent",
    "load_skills_for_agent",
]


# ----------------------------------------------------------------------
# Test helpers
# ----------------------------------------------------------------------


def _peek_cached_paths(agent_name: str) -> list[Path] | None:
    """For tests: read the cached entry without mutating it."""
    with _cache_lock:
        entry = _cache.get(agent_name)
        return list(entry.paths) if entry else None
