from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "apps" / "api" / "config.py"

# Env names that Settings reads AND that an Anthropic-tooling shell exports.
# Without scrubbing them, a developer's shell silently changes what the app under
# test is configured with: an exported ANTHROPIC_BASE_URL / API_TIMEOUT_MS made
# provider-config assertions fail on that machine only. Tests must depend on what
# they set via monkeypatch, never on the ambient environment.
_ALWAYS_SCRUBBED = (
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL",
    "API_TIMEOUT_MS",
)


def _settings_env_names() -> frozenset[str]:
    """Every env var name Settings binds, read straight from config.py."""
    return frozenset(re.findall(r'alias="([A-Z0-9_]+)"', CONFIG_PATH.read_text(encoding="utf-8")))


@pytest.fixture(autouse=True)
def _hermetic_app_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove ambient app configuration before every test.

    Scrubs the provider vars above plus any other Settings-bound name that the
    shell happens to export, so the suite behaves the same in a bare shell, in
    an Anthropic-tooling shell, and in CI.
    """
    for name in sorted(set(_ALWAYS_SCRUBBED) | _settings_env_names()):
        if name in os.environ:
            monkeypatch.delenv(name, raising=False)
