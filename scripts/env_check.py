#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, Iterable, List

REQUIRED_KEYS = {
    "web": [
        "NEXT_PUBLIC_API_BASE_URL",
        "NEXTAUTH_URL",
        "NEXTAUTH_SECRET",
        "LOG_LEVEL",
    ],
    "api": [
        "DATABASE_URL",
        "MODEL_PROVIDER_URL",
        "AUTH_SECRET",
        "LOG_LEVEL",
        "UPLOAD_DIR",
    ],
}

# Additional keys required only when a feature flag is enabled. Each tuple is
# (flag_name, required_var) — when flag_name's value is truthy, required_var
# must be non-empty in the same env file.
CONDITIONAL_REQUIRED_KEYS = {
    "api": [
        ("AGENT_SKILLS_ENABLED", "AGENT_SKILLS_MAX_UPLOAD_MB"),
    ],
}

OPTIONAL_WARNINGS = {
    "api": {
        "AI_API_KEY": "AI_API_KEY is not set; Agent chat will return an LLM configuration error until a key is provided.",
    },
}

_TRUTHY = {"1", "true", "yes", "on"}


def _is_truthy(value: str) -> bool:
    return value.strip().lower() in _TRUTHY


def parse_env_file(path: Path) -> Dict[str, str]:
    data: Dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def missing_keys(values: Dict[str, str], required: Iterable[str]) -> List[str]:
    return [key for key in required if not values.get(key)]


def conditional_missing_keys(kind: str, values: Dict[str, str]) -> List[str]:
    missing: List[str] = []
    for flag_name, required_var in CONDITIONAL_REQUIRED_KEYS.get(kind, []):
        if _is_truthy(values.get(flag_name, "")) and not values.get(required_var):
            missing.append(f"{required_var} (required when {flag_name}=true)")
    return missing


def validate_file(kind: str, path: Path) -> List[str]:
    if not path.exists():
        return [f"file_not_found:{path}"]
    values = parse_env_file(path)
    return missing_keys(values, REQUIRED_KEYS[kind]) + conditional_missing_keys(kind, values)


def warning_messages(kind: str, path: Path) -> List[str]:
    if not path.exists():
        return []
    values = parse_env_file(path)
    warnings = OPTIONAL_WARNINGS.get(kind, {})
    return [message for key, message in warnings.items() if not values.get(key)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Cognitrix environment variables")
    parser.add_argument("--web-env-file", default="apps/web/.env", type=Path)
    parser.add_argument("--api-env-file", default="apps/api/.env", type=Path)
    args = parser.parse_args()

    errors: List[str] = []

    for kind, path in (("web", args.web_env_file), ("api", args.api_env_file)):
        missing = validate_file(kind, path)
        if missing:
            formatted = ", ".join(missing)
            print(f"[ERROR] {kind} env check failed for {path}: {formatted}")
            errors.extend([f"{kind}:{item}" for item in missing])
        else:
            print(f"[OK] {kind} env check passed for {path}")
        for message in warning_messages(kind, path):
            print(f"[WARN] {kind} env check warning for {path}: {message}")

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
