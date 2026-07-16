from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from lectureops_agent.config import LessonPackConfig, load_config


def check_llm_provider_readiness(
    *,
    config_path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict:
    env = env if env is not None else os.environ
    resolved_config_path = Path(config_path) if config_path is not None else _config_path_from_env(env)
    errors: list[str] = []
    missing: list[str] = []
    next_steps: list[str] = []

    if resolved_config_path is None:
        next_steps.extend(
            [
                "Copy config.example.yaml to config.yaml.",
                "Set LESSONPACK_CONFIG=config.yaml.",
                "Use llm.provider=http_chat and set the configured API key environment variable.",
            ]
        )
        return {
            "ready": True,
            "real_provider_ready": False,
            "config_path": None,
            "config_loaded": False,
            "provider": "mock",
            "model": "lessonpack-mock",
            "missing": [],
            "errors": [],
            "next_steps": next_steps,
        }

    try:
        config = load_config(resolved_config_path)
    except Exception as exc:  # noqa: BLE001 - this is a diagnostic boundary.
        return {
            "ready": False,
            "real_provider_ready": False,
            "config_path": str(resolved_config_path),
            "config_loaded": False,
            "provider": None,
            "model": None,
            "missing": [],
            "errors": [str(exc)],
            "next_steps": ["Fix the config file and rerun the provider readiness check."],
        }

    _validate_provider_config(config, env=env, missing=missing, errors=errors, next_steps=next_steps)
    real_provider = config.llm.provider in {"http_chat", "openai_compatible"}
    ready = not missing and not errors
    return {
        "ready": ready,
        "real_provider_ready": ready and real_provider,
        "config_path": str(resolved_config_path),
        "config_loaded": True,
        "provider": config.llm.provider,
        "model": config.llm.model,
        "base_url": config.llm.base_url,
        "api_key_env": config.llm.api_key_env,
        "missing": missing,
        "errors": errors,
        "next_steps": next_steps,
    }


def _config_path_from_env(env: Mapping[str, str]) -> Path | None:
    value = env.get("LESSONPACK_CONFIG")
    if value is None or not value.strip():
        return None
    return Path(value)


def _validate_provider_config(
    config: LessonPackConfig,
    *,
    env: Mapping[str, str],
    missing: list[str],
    errors: list[str],
    next_steps: list[str],
) -> None:
    if config.llm.provider == "mock":
        next_steps.append("Switch llm.provider to http_chat for real LLM proof.")
        return

    if config.llm.provider not in {"http_chat", "openai_compatible"}:
        errors.append(f"Unsupported provider: {config.llm.provider}")
        return

    if not config.llm.base_url:
        missing.append("llm.base_url")
        next_steps.append("Set llm.base_url to an OpenAI-compatible chat completions endpoint.")
    if not config.llm.api_key_env:
        missing.append("llm.api_key_env")
        next_steps.append("Set llm.api_key_env to the name of the API key environment variable.")
    elif not env.get(config.llm.api_key_env, "").strip():
        missing.append(config.llm.api_key_env)
        next_steps.append(f"Set ${config.llm.api_key_env} before running real provider evaluation.")
    if config.llm.timeout_seconds is None:
        missing.append("llm.timeout_seconds")
        next_steps.append("Set llm.timeout_seconds to a positive number.")
