from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from lectureops_agent.config import LessonPackConfig, load_config
from lectureops_agent.env import load_env_file
from lectureops_agent.services.langfuse_tracing import configure_langfuse_otel_env


HTTP_PROVIDER_NAMES = {"http_chat", "openai_compatible"}
LITELLM_PROVIDER_NAMES = {"litellm"}
LANGFUSE_CALLBACK_NAMES = {"langfuse", "langfuse_otel"}


def check_llm_provider_readiness(
    *,
    config_path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    require_secrets: bool = True,
) -> dict:
    if env is None:
        load_env_file()
    env = env if env is not None else os.environ
    resolved_config_path = Path(config_path) if config_path is not None else _config_path_from_env(env)
    errors: list[str] = []
    missing: list[str] = []
    next_steps: list[str] = []

    if resolved_config_path is None:
        provider = env.get("LESSONPACK_LLM_PROVIDER", "mock").strip().casefold() or "mock"
        if provider == "litellm":
            model = env.get("LESSONPACK_LITELLM_MODEL", "gpt-4o-mini")
            fallback_models = _split_env_list(env.get("LESSONPACK_LITELLM_FALLBACK_MODELS", "gemini/gemini-2.0-flash"))
            callbacks = _split_env_list(
                env.get("LESSONPACK_LITELLM_CALLBACKS")
                or env.get("LESSONPACK_LITELLM_SUCCESS_CALLBACKS", "langfuse_otel")
            )
            _validate_litellm_config(
                model=model,
                fallback_models=fallback_models,
                callbacks=callbacks,
                env=env,
                missing=missing,
                errors=errors,
                next_steps=next_steps,
                require_secrets=require_secrets,
            )
            ready = _ready(missing=missing, errors=errors, require_secrets=require_secrets)
            return {
                "ready": ready,
                "real_provider_ready": ready if require_secrets else False,
                "secret_check": _secret_check(require_secrets),
                "config_path": None,
                "config_loaded": False,
                "provider": "litellm",
                "model": model,
                "fallback_models": fallback_models,
                "callbacks": callbacks,
                "langfuse_otel": _langfuse_otel_report(callbacks=callbacks, env=env),
                "missing": missing,
                "errors": errors,
                "next_steps": next_steps,
            }
        next_steps.extend(
            [
                "Copy config.example.yaml to config.yaml.",
                "Set LESSONPACK_CONFIG=config.yaml in .env.",
                "Use llm.provider=litellm for OpenAI primary + Gemini fallback through LiteLLM.",
            ]
        )
        return {
            "ready": True,
            "real_provider_ready": False,
            "secret_check": _secret_check(require_secrets),
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
            "secret_check": _secret_check(require_secrets),
            "config_path": str(resolved_config_path),
            "config_loaded": False,
            "provider": None,
            "model": None,
            "missing": [],
            "errors": [str(exc)],
            "next_steps": ["Fix the config file and rerun the provider readiness check."],
        }

    callbacks = _configured_callbacks(config)
    _validate_provider_config(
        config,
        callbacks=callbacks,
        env=env,
        missing=missing,
        errors=errors,
        next_steps=next_steps,
        require_secrets=require_secrets,
    )
    real_provider = config.llm.provider in (HTTP_PROVIDER_NAMES | LITELLM_PROVIDER_NAMES)
    ready = _ready(missing=missing, errors=errors, require_secrets=require_secrets)
    return {
        "ready": ready,
        "real_provider_ready": ready and real_provider if require_secrets else False,
        "secret_check": _secret_check(require_secrets),
        "config_path": str(resolved_config_path),
        "config_loaded": True,
        "provider": config.llm.provider,
        "model": config.llm.model,
        "base_url": config.llm.base_url,
        "api_key_env": config.llm.api_key_env,
        "fallback_models": config.llm.fallback_models,
        "callbacks": callbacks,
        "langfuse_otel": _langfuse_otel_report(callbacks=callbacks, env=env),
        "missing": missing,
        "errors": errors,
        "next_steps": next_steps,
    }



def _langfuse_otel_report(*, callbacks: list[str], env: Mapping[str, str]) -> dict:
    result = configure_langfuse_otel_env(callbacks, env=dict(env))
    return {
        "enabled": result.enabled,
        "host": result.host,
        "endpoint": result.endpoint,
        "protocol": result.protocol,
        "headers_configured": result.headers_configured,
    }


def _ready(*, missing: list[str], errors: list[str], require_secrets: bool) -> bool:
    return not errors and (not require_secrets or not missing)


def _secret_check(require_secrets: bool) -> str:
    return "required" if require_secrets else "skipped"


def _config_path_from_env(env: Mapping[str, str]) -> Path | None:
    value = env.get("LESSONPACK_CONFIG")
    if value is None or not value.strip():
        return None
    return Path(value)


def _configured_callbacks(config: LessonPackConfig) -> list[str]:
    return list(config.llm.callbacks or config.llm.success_callbacks)


def _validate_provider_config(
    config: LessonPackConfig,
    *,
    callbacks: list[str],
    env: Mapping[str, str],
    missing: list[str],
    errors: list[str],
    next_steps: list[str],
    require_secrets: bool,
) -> None:
    if config.llm.provider == "mock":
        next_steps.append("Switch llm.provider to litellm for real LLMOps proof.")
        return

    if config.llm.provider in HTTP_PROVIDER_NAMES:
        _validate_http_provider_config(
            config,
            env=env,
            missing=missing,
            errors=errors,
            next_steps=next_steps,
            require_secrets=require_secrets,
        )
        return

    if config.llm.provider == "litellm":
        _validate_litellm_config(
            model=config.llm.model,
            fallback_models=config.llm.fallback_models,
            callbacks=callbacks,
            env=env,
            missing=missing,
            errors=errors,
            next_steps=next_steps,
            require_secrets=require_secrets,
        )
        return

    errors.append(f"Unsupported provider: {config.llm.provider}")


def _validate_http_provider_config(
    config: LessonPackConfig,
    *,
    env: Mapping[str, str],
    missing: list[str],
    errors: list[str],
    next_steps: list[str],
    require_secrets: bool,
) -> None:
    if not config.llm.base_url:
        _append_missing(missing, "llm.base_url")
        next_steps.append("Set llm.base_url to an OpenAI-compatible chat completions endpoint.")
    if not config.llm.api_key_env:
        _append_missing(missing, "llm.api_key_env")
        next_steps.append("Set llm.api_key_env to the name of the API key environment variable.")
    elif require_secrets and not env.get(config.llm.api_key_env, "").strip():
        _append_missing(missing, config.llm.api_key_env)
        next_steps.append(f"Set ${config.llm.api_key_env} before running real provider evaluation.")
    if config.llm.timeout_seconds is None:
        _append_missing(missing, "llm.timeout_seconds")
        next_steps.append("Set llm.timeout_seconds to a positive number.")


def _validate_litellm_config(
    *,
    model: str,
    fallback_models: list[str],
    callbacks: list[str],
    env: Mapping[str, str],
    missing: list[str],
    errors: list[str],
    next_steps: list[str],
    require_secrets: bool,
) -> None:
    if not model.strip():
        _append_missing(missing, "llm.model")
        next_steps.append("Set llm.model to the primary LiteLLM model, e.g. gpt-4o-mini.")
        return

    if not require_secrets:
        return

    required_env_vars = _required_key_envs_for_models([model, *fallback_models])
    for env_name in required_env_vars:
        if not env.get(env_name, "").strip():
            _append_missing(missing, env_name)
            next_steps.append(f"Set ${env_name} in .env before running LiteLLM provider evaluation.")

    if LANGFUSE_CALLBACK_NAMES.intersection({callback.casefold() for callback in callbacks}):
        for env_name in ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"]:
            if not env.get(env_name, "").strip():
                _append_missing(missing, env_name)
        if "LANGFUSE_PUBLIC_KEY" in missing or "LANGFUSE_SECRET_KEY" in missing:
            next_steps.append("Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in .env for Langfuse tracing.")


def _required_key_envs_for_models(models: list[str]) -> list[str]:
    required: list[str] = []
    for model in models:
        normalized = model.casefold().strip()
        env_name = None
        if normalized.startswith("openai/") or normalized.startswith("gpt-") or _is_openai_o_series(normalized):
            env_name = "OPENAI_API_KEY"
        elif normalized.startswith("gemini/"):
            env_name = "GEMINI_API_KEY"
        if env_name and env_name not in required:
            required.append(env_name)
    return required


def _is_openai_o_series(model: str) -> bool:
    return len(model) > 1 and model[0] == "o" and model[1].isdigit()


def _append_missing(missing: list[str], value: str) -> None:
    if value not in missing:
        missing.append(value)


def _split_env_list(value: str | None) -> list[str]:
    if value is None:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]
