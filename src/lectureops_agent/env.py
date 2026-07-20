from __future__ import annotations

import os
from pathlib import Path


DEFAULT_ENV_FILE = ".env"
ENV_FILE_ENV_VAR = "LESSONPACK_ENV_FILE"


def load_env_file(path: str | Path | None = None, *, override: bool = False) -> dict[str, str]:
    env_path = _resolve_env_path(path)
    if not env_path.exists():
        return {}

    loaded: dict[str, str] = {}
    for line_number, line in enumerate(env_path.read_text(encoding="utf-8").splitlines(), start=1):
        parsed = _parse_env_line(line, line_number=line_number)
        if parsed is None:
            continue
        key, value = parsed
        if override or key not in os.environ:
            os.environ[key] = value
            loaded[key] = value
    return loaded


def _resolve_env_path(path: str | Path | None) -> Path:
    if path is not None:
        return Path(path)
    configured = os.getenv(ENV_FILE_ENV_VAR)
    if configured and configured.strip():
        return Path(configured)
    return Path(__file__).resolve().parents[2] / DEFAULT_ENV_FILE


def _parse_env_line(line: str, *, line_number: int) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].strip()
    if "=" not in stripped:
        raise ValueError(f".env line {line_number} must use KEY=VALUE format")

    key, raw_value = stripped.split("=", 1)
    key = key.strip()
    if not key:
        raise ValueError(f".env line {line_number} has an empty key")
    if not key.replace("_", "").isalnum() or key[0].isdigit():
        raise ValueError(f".env line {line_number} has an invalid key: {key}")
    return key, _clean_value(raw_value)


def _clean_value(raw_value: str) -> str:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    if " #" in value:
        return value.split(" #", 1)[0].rstrip()
    return value
