#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlparse

ROOT_DIR = Path(__file__).resolve().parents[2]
APPS_API_DIR = ROOT_DIR / "apps" / "api"
DEFAULT_API_ENV_FILE = APPS_API_DIR / ".env"

STATIC_TEST_ARTIFACTS = (
    ROOT_DIR / ".coverage",
    ROOT_DIR / ".pytest_cache",
    ROOT_DIR / ".mypy_cache",
    ROOT_DIR / ".ruff_cache",
    ROOT_DIR / "htmlcov",
    ROOT_DIR / "logs" / "dev-local",
    ROOT_DIR / "apps" / "web" / ".next",
    ROOT_DIR / "apps" / "web" / "coverage",
    ROOT_DIR / "apps" / "web" / "playwright-report",
    ROOT_DIR / "apps" / "web" / "test-results",
    ROOT_DIR / "infra" / "docker" / ".docker-data",
)

SKIP_WALK_DIRS = {".git", ".venv", "node_modules"}
POSTGRES_SCHEMAS_RESET_SQL = """
DROP SCHEMA IF EXISTS public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO CURRENT_USER;
GRANT ALL ON SCHEMA public TO PUBLIC;
""".strip()


class ResetError(RuntimeError):
    pass


@dataclass(slots=True)
class ResetConfig:
    env_file: Path
    upload_dir: Path
    database_url: str


@dataclass(slots=True)
class DbTarget:
    scheme: str
    database_url: str
    display_name: str
    sqlite_path: Path | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clear Cognitrix local runtime data, runtime databases, and test artifacts."
    )
    parser.add_argument(
        "--api-env-file",
        type=Path,
        default=Path(os.environ.get("API_ENV_FILE", DEFAULT_API_ENV_FILE)),
        help="Path to the API env file. Defaults to apps/api/.env or API_ENV_FILE if set.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the cleanup plan without deleting anything.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt.",
    )
    parser.add_argument(
        "--with-db-reset",
        action="store_true",
        help="Also reset the database referenced by DATABASE_URL. Disabled by default.",
    )
    parser.add_argument(
        "--include-docker-volumes",
        action="store_true",
        help="Also run `docker compose down --remove-orphans --volumes` in the repo root.",
    )
    return parser.parse_args()


def load_config(env_file: Path) -> ResetConfig:
    if not env_file.exists():
        raise ResetError(
            f"API env file not found: {env_file}. "
            "Pass --api-env-file or create apps/api/.env first."
        )

    env_values = parse_dotenv(env_file)
    upload_dir_raw = env_values.get("UPLOAD_DIR")
    database_url = (env_values.get("DATABASE_URL") or "").strip()

    if not upload_dir_raw:
        raise ResetError(f"UPLOAD_DIR is missing in {env_file}")
    if not database_url:
        raise ResetError(f"DATABASE_URL is missing in {env_file}")

    upload_dir = resolve_upload_dir(upload_dir_raw)
    return ResetConfig(
        env_file=env_file.resolve(),
        upload_dir=upload_dir,
        database_url=database_url,
    )


def parse_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def resolve_upload_dir(raw_value: str) -> Path:
    candidate = Path(raw_value).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (APPS_API_DIR / candidate).resolve()


def build_db_target(database_url: str) -> DbTarget:
    parsed = urlparse(database_url)
    scheme = parsed.scheme.lower()

    if scheme in {"postgresql", "postgres"}:
        host = parsed.hostname or "localhost"
        port = parsed.port or 5432
        database = (parsed.path or "/").lstrip("/")
        if not database:
            raise ResetError("DATABASE_URL must include a PostgreSQL database name")
        user = unquote(parsed.username or "")
        user_part = f"{user}@" if user else ""
        display_name = f"{scheme}://{user_part}{host}:{port}/{database}"
        return DbTarget(
            scheme=scheme,
            database_url=database_url,
            display_name=display_name,
        )

    if scheme == "sqlite":
        sqlite_path = Path(unquote(parsed.path))
        if not sqlite_path.is_absolute():
            sqlite_path = (APPS_API_DIR / sqlite_path).resolve()
        return DbTarget(
            scheme=scheme,
            database_url=database_url,
            display_name=f"sqlite:///{sqlite_path}",
            sqlite_path=sqlite_path,
        )

    raise ResetError(f"Unsupported DATABASE_URL scheme: {scheme or '<empty>'}")


def confirm_or_exit(config: ResetConfig, db_target: DbTarget, args: argparse.Namespace) -> None:
    print(f"[reset] Env file: {config.env_file}")
    print(f"[reset] Upload dir: {config.upload_dir}")
    if args.with_db_reset:
        print(f"[reset] Database target: {db_target.display_name}")
    else:
        print("[reset] Database reset: skipped by default")
    print("[reset] Local state to clear:")
    print("  - uploaded raw files and metadata")
    print("  - DuckDB runtime databases")
    print("  - SQLite state databases and view/audit files under UPLOAD_DIR/state")
    print("  - auth overrides and audit logs under UPLOAD_DIR")
    for item in STATIC_TEST_ARTIFACTS:
        print(f"  - {item}")
    print("  - all __pycache__ directories under the repo")
    if args.include_docker_volumes:
        print("  - docker compose volumes for this repository")

    if args.dry_run or args.yes:
        return

    response = input("Proceed with deleting local runtime/test data? [y/N] ").strip().lower()
    if response not in {"y", "yes"}:
        raise SystemExit(1)


def clear_directory_contents(path: Path, *, dry_run: bool) -> list[str]:
    actions: list[str] = []
    if not path.exists():
        if dry_run:
            actions.append(f"would ensure directory exists: {path}")
        else:
            path.mkdir(parents=True, exist_ok=True)
            actions.append(f"ensured directory exists: {path}")
        return actions

    for child in sorted(path.iterdir(), key=lambda item: item.name):
        actions.extend(remove_path(child, dry_run=dry_run))

    if dry_run:
        actions.append(f"would clear directory contents: {path}")
    else:
        path.mkdir(parents=True, exist_ok=True)
        actions.append(f"cleared directory contents: {path}")
    return actions


def remove_path(path: Path, *, dry_run: bool) -> list[str]:
    if not path.exists() and not path.is_symlink():
        return []

    if dry_run:
        return [f"would remove: {path}"]

    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    else:
        shutil.rmtree(path)
    return [f"removed: {path}"]


def discover_pycache_dirs(root: Path) -> list[Path]:
    matches: list[Path] = []
    for current_root, dirnames, _filenames in os.walk(root):
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if dirname not in SKIP_WALK_DIRS
        ]
        for dirname in list(dirnames):
            if dirname == "__pycache__":
                matches.append(Path(current_root) / dirname)
                dirnames.remove(dirname)
    return sorted(matches)


def dedupe_paths(paths: Iterable[Path]) -> list[Path]:
    seen: set[str] = set()
    unique_paths: list[Path] = []
    for path in paths:
        key = str(path.resolve(strict=False))
        if key in seen:
            continue
        seen.add(key)
        unique_paths.append(path)
    return unique_paths


def is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


def reset_database(db_target: DbTarget, *, dry_run: bool) -> list[str]:
    if db_target.scheme == "sqlite":
        return reset_sqlite_database(db_target, dry_run=dry_run)
    if db_target.scheme in {"postgresql", "postgres"}:
        return reset_postgres_database(db_target, dry_run=dry_run)
    raise ResetError(f"Unsupported database scheme: {db_target.scheme}")


def reset_sqlite_database(db_target: DbTarget, *, dry_run: bool) -> list[str]:
    if db_target.sqlite_path is None:
        raise ResetError("SQLite reset requested without a sqlite_path")

    targets = [
        db_target.sqlite_path,
        Path(f"{db_target.sqlite_path}-wal"),
        Path(f"{db_target.sqlite_path}-shm"),
    ]
    actions: list[str] = []
    for target in dedupe_paths(targets):
        actions.extend(remove_path(target, dry_run=dry_run))
    return actions


def reset_postgres_database(db_target: DbTarget, *, dry_run: bool) -> list[str]:
    parsed = urlparse(db_target.database_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    database = (parsed.path or "/").lstrip("/")
    username = unquote(parsed.username or "")
    password = unquote(parsed.password or "")

    if not database:
        raise ResetError("DATABASE_URL must include a PostgreSQL database name")

    psql = shutil.which("psql")
    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password

    if psql:
        command = [
            psql,
            "-v",
            "ON_ERROR_STOP=1",
            "-h",
            host,
            "-p",
            str(port),
            "-d",
            database,
            "-c",
            POSTGRES_SCHEMAS_RESET_SQL,
        ]
        if username:
            command.extend(["-U", username])
        description = f"reset PostgreSQL schema via psql ({db_target.display_name})"
        return run_command(command, env=env, dry_run=dry_run, description=description)

    docker = shutil.which("docker")
    if not docker:
        raise ResetError(
            "PostgreSQL reset requires either `psql` in PATH or Docker installed."
        )

    container_host = host
    docker_args: list[str] = []
    if host in {"localhost", "127.0.0.1"}:
        container_host = "host.docker.internal"
        docker_args.extend(["--add-host", "host.docker.internal:host-gateway"])

    command = [
        docker,
        "run",
        "--rm",
        *docker_args,
        "-e",
        f"PGPASSWORD={password}",
        "postgres:16-alpine",
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
        "-h",
        container_host,
        "-p",
        str(port),
        "-d",
        database,
        "-c",
        POSTGRES_SCHEMAS_RESET_SQL,
    ]
    if username:
        command.extend(["-U", username])

    description = f"reset PostgreSQL schema via Docker ({db_target.display_name})"
    return run_command(command, env=None, dry_run=dry_run, description=description)


def run_command(
    command: list[str],
    *,
    env: dict[str, str] | None,
    dry_run: bool,
    description: str,
) -> list[str]:
    if dry_run:
        return [f"would run: {description}"]

    completed = subprocess.run(
        command,
        cwd=ROOT_DIR,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
        raise ResetError(f"{description} failed: {stderr}")
    return [f"completed: {description}"]


def cleanup_docker_volumes(*, dry_run: bool) -> list[str]:
    docker = shutil.which("docker")
    if not docker:
        raise ResetError("Docker volume cleanup requested, but `docker` is not installed")
    command = [docker, "compose", "down", "--remove-orphans", "--volumes"]
    return run_command(
        command,
        env=None,
        dry_run=dry_run,
        description="docker compose down --remove-orphans --volumes",
    )


def main() -> int:
    args = parse_args()
    try:
        config = load_config(args.api_env_file.expanduser().resolve())
        db_target = build_db_target(config.database_url)
        confirm_or_exit(config, db_target, args)

        actions: list[str] = []

        actions.extend(clear_directory_contents(config.upload_dir, dry_run=args.dry_run))

        artifact_paths = list(STATIC_TEST_ARTIFACTS)
        artifact_paths.extend(discover_pycache_dirs(ROOT_DIR))

        if (
            args.with_db_reset
            and db_target.scheme == "sqlite"
            and db_target.sqlite_path is not None
            and not is_within(db_target.sqlite_path, config.upload_dir)
        ):
            artifact_paths.append(db_target.sqlite_path)
            artifact_paths.append(Path(f"{db_target.sqlite_path}-wal"))
            artifact_paths.append(Path(f"{db_target.sqlite_path}-shm"))

        for artifact in dedupe_paths(artifact_paths):
            actions.extend(remove_path(artifact, dry_run=args.dry_run))

        if args.with_db_reset:
            actions.extend(reset_database(db_target, dry_run=args.dry_run))

        if args.include_docker_volumes:
            actions.extend(cleanup_docker_volumes(dry_run=args.dry_run))

        removed_count = sum(
            1
            for action in actions
            if action.startswith("removed:")
            or action.startswith("cleared directory contents:")
            or action.startswith("completed:")
            or action.startswith("ensured directory exists:")
        )
        planned_count = sum(
            1
            for action in actions
            if action.startswith("would remove:")
            or action.startswith("would clear directory contents:")
            or action.startswith("would run:")
            or action.startswith("would ensure directory exists:")
        )

        print("[reset] Summary")
        for action in actions:
            print(f"  - {action}")
        if args.dry_run:
            print(f"[reset] Dry run complete. Planned operations: {planned_count}")
        else:
            print(f"[reset] Cleanup complete. Applied operations: {removed_count}")
        print("[reset] Done")
        return 0
    except ResetError as exc:
        print(f"[reset] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
