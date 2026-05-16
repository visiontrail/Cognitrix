from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT_DIR / "scripts" / "env_check.py"


def run_env_check(web_env: Path, api_env: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--web-env-file",
            str(web_env),
            "--api-env-file",
            str(api_env),
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def test_env_check_passes(tmp_path: Path) -> None:
    web_env = tmp_path / "web.env"
    web_env.write_text(
        "\n".join(
            [
                "NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000",
                "NEXTAUTH_URL=http://127.0.0.1:3000",
                "NEXTAUTH_SECRET=secret",
                "LOG_LEVEL=INFO",
            ]
        ),
        encoding="utf-8",
    )

    api_env = tmp_path / "api.env"
    api_env.write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql://user:pass@localhost:5432/db",
                "MODEL_PROVIDER_URL=http://localhost:11434",
                "AUTH_SECRET=secret",
                "LOG_LEVEL=INFO",
                "UPLOAD_DIR=./uploads",
            ]
        ),
        encoding="utf-8",
    )

    result = run_env_check(web_env, api_env)
    assert result.returncode == 0
    assert "[OK] web env check passed" in result.stdout
    assert "[OK] api env check passed" in result.stdout


def test_env_check_requires_skill_vars_when_flag_enabled(tmp_path: Path) -> None:
    web_env = tmp_path / "web.env"
    web_env.write_text(
        "\n".join(
            [
                "NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000",
                "NEXTAUTH_URL=http://127.0.0.1:3000",
                "NEXTAUTH_SECRET=secret",
                "LOG_LEVEL=INFO",
            ]
        ),
        encoding="utf-8",
    )

    api_env = tmp_path / "api.env"
    api_env.write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql://user:pass@localhost:5432/db",
                "MODEL_PROVIDER_URL=http://localhost:11434",
                "AUTH_SECRET=secret",
                "LOG_LEVEL=INFO",
                "UPLOAD_DIR=./uploads",
                "AGENT_SKILLS_ENABLED=true",
                # AGENT_SKILLS_MAX_UPLOAD_MB intentionally omitted
            ]
        ),
        encoding="utf-8",
    )

    result = run_env_check(web_env, api_env)
    assert result.returncode == 1
    assert "AGENT_SKILLS_MAX_UPLOAD_MB" in result.stdout


def test_env_check_skips_skill_vars_when_flag_disabled(tmp_path: Path) -> None:
    web_env = tmp_path / "web.env"
    web_env.write_text(
        "\n".join(
            [
                "NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000",
                "NEXTAUTH_URL=http://127.0.0.1:3000",
                "NEXTAUTH_SECRET=secret",
                "LOG_LEVEL=INFO",
            ]
        ),
        encoding="utf-8",
    )

    api_env = tmp_path / "api.env"
    api_env.write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql://user:pass@localhost:5432/db",
                "MODEL_PROVIDER_URL=http://localhost:11434",
                "AUTH_SECRET=secret",
                "LOG_LEVEL=INFO",
                "UPLOAD_DIR=./uploads",
                "AGENT_SKILLS_ENABLED=false",
            ]
        ),
        encoding="utf-8",
    )

    result = run_env_check(web_env, api_env)
    assert result.returncode == 0


def test_env_check_fails_when_key_missing(tmp_path: Path) -> None:
    web_env = tmp_path / "web.env"
    web_env.write_text(
        "\n".join(
            [
                "NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000",
                "NEXTAUTH_URL=http://127.0.0.1:3000",
                "NEXTAUTH_SECRET=secret",
            ]
        ),
        encoding="utf-8",
    )

    api_env = tmp_path / "api.env"
    api_env.write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql://user:pass@localhost:5432/db",
                "MODEL_PROVIDER_URL=http://localhost:11434",
                "AUTH_SECRET=secret",
                "LOG_LEVEL=INFO",
                "UPLOAD_DIR=./uploads",
            ]
        ),
        encoding="utf-8",
    )

    result = run_env_check(web_env, api_env)
    assert result.returncode == 1
    assert "LOG_LEVEL" in result.stdout
