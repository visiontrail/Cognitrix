from __future__ import annotations

import subprocess
from pathlib import Path
from shlex import quote

ROOT_DIR = Path(__file__).resolve().parents[2]
ENV_LIB_PATH = ROOT_DIR / "scripts" / "lib" / "env.sh"


def run_bash(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", script],
        text=True,
        capture_output=True,
        check=False,
    )


def test_load_env_file_overrides_inherited_values(tmp_path: Path) -> None:
    env_file = tmp_path / "api.env"
    env_file.write_text(
        "\n".join(
            [
                "# Local API env",
                "DATABASE_URL=sqlite:///./data/uploads/state/ai_views.sqlite3",
                "UPLOAD_DIR=./data/uploads",
                'QUOTED_VALUE="hello world"',
            ]
        ),
        encoding="utf-8",
    )

    result = run_bash(
        "\n".join(
            [
                "set -euo pipefail",
                f"source {quote(str(ENV_LIB_PATH))}",
                "export DATABASE_URL=sqlite:////data/uploads/state/ai_views.sqlite3",
                f"load_env_file {quote(str(env_file))}",
                'printf "%s\\n" "$DATABASE_URL"',
                'printf "%s\\n" "$UPLOAD_DIR"',
                'printf "%s\\n" "$QUOTED_VALUE"',
            ]
        )
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "sqlite:///./data/uploads/state/ai_views.sqlite3",
        "./data/uploads",
        "hello world",
    ]


def test_load_env_file_rejects_invalid_keys(tmp_path: Path) -> None:
    env_file = tmp_path / "api.env"
    env_file.write_text("INVALID-KEY=value\n", encoding="utf-8")

    result = run_bash(
        "\n".join(
            [
                "set -euo pipefail",
                f"source {quote(str(ENV_LIB_PATH))}",
                f"load_env_file {quote(str(env_file))}",
            ]
        )
    )

    assert result.returncode == 1
    assert "Invalid env key" in result.stderr


DOCKER_LIB_PATH = ROOT_DIR / "scripts" / "lib" / "docker.sh"


def test_compose_drops_host_env_that_shadows_project_env() -> None:
    """A shell exporting ANTHROPIC_* must not override the project .env.

    Compose interpolation prefers the invoking shell, so a leaked
    ANTHROPIC_BASE_URL used to send the container's agent SDK to the wrong
    endpoint (HTTP 401 on every agent turn).
    """
    result = run_bash(
        "\n".join(
            [
                "set -euo pipefail",
                f"source {quote(str(DOCKER_LIB_PATH))}",
                "export ANTHROPIC_BASE_URL=https://leaked.example.com",
                "export API_TIMEOUT_MS=999999",
                # Stub the compose binary with a child that reports its own env and
                # ignores the trailing `-f <compose file>` arguments.
                "COMPOSE=(bash -c 'echo CHILD_BASE_URL=${ANTHROPIC_BASE_URL:-unset};"
                " echo CHILD_TIMEOUT=${API_TIMEOUT_MS:-unset}' stub)",
                "compose config",
                "warn_shadowed_host_env",
            ]
        )
    )

    assert result.returncode == 0, result.stderr
    assert "CHILD_BASE_URL=unset" in result.stdout
    assert "CHILD_TIMEOUT=unset" in result.stdout
    assert "leaked.example.com" not in result.stdout
    assert "999999" not in result.stdout
    assert "Ignoring host env ANTHROPIC_BASE_URL" in result.stderr
    assert "Ignoring host env API_TIMEOUT_MS" in result.stderr
