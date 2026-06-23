"""Config/script guards for the isolated Docker storage container.

These tests assert the Compose topology owns persistence through a dedicated
`storage` service and that the normal lifecycle scripts never request volume
deletion. They are pure file/config assertions so they run without Docker.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT_DIR = Path(__file__).resolve().parents[2]
COMPOSE_FILES = (
    ROOT_DIR / "docker-compose.yml",
    ROOT_DIR / "infra" / "docker" / "docker-compose.yml",
)
RESTART_SCRIPT = ROOT_DIR / "scripts" / "docker_restart.sh"
UP_SCRIPT = ROOT_DIR / "scripts" / "docker_up.sh"
START_SCRIPT = ROOT_DIR / "scripts" / "docker_start.sh"
DOWN_SCRIPT = ROOT_DIR / "scripts" / "docker_down.sh"
RESET_SCRIPT = ROOT_DIR / "scripts" / "maintenance" / "reset_local_data.py"

VOLUME_KEY = "cognitrix_upload_data"
NON_DESTRUCTIVE_SCRIPTS = (RESTART_SCRIPT, UP_SCRIPT, START_SCRIPT, DOWN_SCRIPT)


def load_compose(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("compose_path", COMPOSE_FILES, ids=lambda p: p.name)
def test_compose_defines_storage_service(compose_path: Path) -> None:
    config = load_compose(compose_path)
    services = config.get("services", {})
    assert "storage" in services, f"{compose_path} must define a `storage` service"

    storage = services["storage"]
    mounts = storage.get("volumes", [])
    assert any(
        isinstance(mount, str) and mount.startswith(f"{VOLUME_KEY}:")
        for mount in mounts
    ), f"storage service in {compose_path} must mount {VOLUME_KEY}"


@pytest.mark.parametrize("compose_path", COMPOSE_FILES, ids=lambda p: p.name)
def test_storage_initializes_state_and_has_healthcheck(compose_path: Path) -> None:
    storage = load_compose(compose_path)["services"]["storage"]
    command = storage.get("command")
    command_text = "\n".join(command) if isinstance(command, list) else str(command)
    assert "mkdir -p" in command_text and "/storage/uploads/state" in command_text, (
        f"storage service in {compose_path} must create the state directory"
    )

    healthcheck = storage.get("healthcheck", {})
    test = healthcheck.get("test")
    test_text = " ".join(test) if isinstance(test, list) else str(test)
    assert "/storage/uploads/state" in test_text and "-w" in test_text, (
        f"storage healthcheck in {compose_path} must verify state/ is writable"
    )


@pytest.mark.parametrize("compose_path", COMPOSE_FILES, ids=lambda p: p.name)
def test_api_waits_for_healthy_storage(compose_path: Path) -> None:
    api = load_compose(compose_path)["services"]["api"]
    depends_on = api.get("depends_on", {})
    assert "storage" in depends_on, (
        f"api in {compose_path} must depend on the storage service"
    )
    assert depends_on["storage"].get("condition") == "service_healthy", (
        f"api in {compose_path} must wait for storage service_healthy"
    )

    # API still consumes the same persistent volume at the app path.
    mounts = api.get("volumes", [])
    assert any(
        isinstance(mount, str) and mount == f"{VOLUME_KEY}:/app/data/uploads"
        for mount in mounts
    ), f"api in {compose_path} must mount {VOLUME_KEY} at /app/data/uploads"


@pytest.mark.parametrize("compose_path", COMPOSE_FILES, ids=lambda p: p.name)
def test_persistent_volume_key_is_preserved(compose_path: Path) -> None:
    volumes = load_compose(compose_path).get("volumes", {})
    assert VOLUME_KEY in volumes, (
        f"{compose_path} must keep the {VOLUME_KEY} volume key to preserve data"
    )


@pytest.mark.parametrize("script", NON_DESTRUCTIVE_SCRIPTS, ids=lambda p: p.name)
def test_lifecycle_scripts_never_request_volume_deletion(script: Path) -> None:
    text = script.read_text(encoding="utf-8")
    assert "--volumes" not in text, f"{script} must not pass --volumes"
    # Lifecycle scripts must not invoke the reset entrypoint as part of their flow.
    # They may *mention* it in operator guidance `echo` output, but never run it.
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("echo"):
            continue
        assert "reset_local_data.py" not in stripped, (
            f"{script} must not execute reset logic in its workflow"
        )


def test_only_reset_script_deletes_docker_volumes() -> None:
    reset_text = RESET_SCRIPT.read_text(encoding="utf-8")
    assert "--remove-orphans" in reset_text and "--volumes" in reset_text, (
        "reset_local_data.py is expected to own the docker volume deletion path"
    )
    assert "--include-docker-volumes" in reset_text, (
        "volume deletion must be gated behind --include-docker-volumes"
    )

    # No lifecycle script may contain the destructive `down --volumes` pattern.
    for script in NON_DESTRUCTIVE_SCRIPTS:
        text = script.read_text(encoding="utf-8")
        assert "down --remove-orphans --volumes" not in text
        assert "--volumes" not in text


def test_restart_and_down_scripts_announce_preservation() -> None:
    for script in (RESTART_SCRIPT, DOWN_SCRIPT):
        text = script.read_text(encoding="utf-8")
        assert "preserved" in text.lower(), (
            f"{script} should tell the operator storage is preserved"
        )
        assert "reset_local_data.py --include-docker-volumes" in text, (
            f"{script} should name the explicit reset command path"
        )
