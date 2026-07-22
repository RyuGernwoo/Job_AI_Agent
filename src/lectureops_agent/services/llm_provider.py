from __future__ import annotations

import json
import logging
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from lectureops_agent.config import LessonPackConfig
from lectureops_agent.env import load_env_file
from lectureops_agent.services.langfuse_tracing import (
    configure_langfuse_otel_env,
    flush_langfuse_otel,
    litellm_callbacks_for_runtime,
    record_langfuse_llm_span,
)


_LLM_TRACE_CONTEXT: ContextVar[dict[str, Any]] = ContextVar("lessonpack_llm_trace_context", default={})
_LOGGER = logging.getLogger(__name__)


class LLMProvider(Protocol):
    name: str

    def generate(self, *, prompt: str) -> str:
        ...


class MockLLMProvider:
    name = "mock"

    def generate(self, *, prompt: str) -> str:
        if not prompt.strip():
            raise ValueError("prompt must not be empty")
        return (
            "Mock provider outline: align lesson plan, practice, and assessment with "
            "the retrieved evidence and make the generated package ready for download."
        )


class HTTPChatCompletionsProvider:
    def __init__(self, *, base_url: str, api_key: str, model: str, timeout_seconds: int | float) -> None:
        if not base_url.strip():
            raise ValueError("base_url is required")
        if not api_key.strip():
            raise ValueError("api_key is required")
        if not model.strip():
            raise ValueError("model is required")
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.name = f"http_chat:{model}"

    def generate(self, *, prompt: str) -> str:
        if not prompt.strip():
            raise ValueError("prompt must not be empty")
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You generate grounded lesson packages for LessonPack AI. "
                        "Return exactly one JSON object matching the schema in the user request."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }
        data = json.dumps(payload).encode("utf-8")
        request = Request(
            self.base_url,
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM provider request failed with HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"LLM provider request failed: {exc.reason}") from exc

        return _extract_message_content(response_payload)


class LiteLLMProvider:
    def __init__(
        self,
        *,
        model: str,
        fallback_models: list[str] | None = None,
        timeout_seconds: int | float | None = None,
        callbacks: list[str] | None = None,
        schema_retries: int = 1,
        temperature: float = 0.1,
        revision_temperature: float = 0.6,
    ) -> None:
        if not model.strip():
            raise ValueError("model is required")
        self.model = model
        self.fallback_models = fallback_models or []
        self.timeout_seconds = timeout_seconds
        self.callbacks = callbacks or []
        self.schema_retries = max(0, schema_retries)
        self.temperature = temperature
        self.revision_temperature = revision_temperature
        fallback_label = f" -> {', '.join(self.fallback_models)}" if self.fallback_models else ""
        self.name = f"litellm:{model}{fallback_label}"

    def generate(self, *, prompt: str) -> str:
        if not prompt.strip():
            raise ValueError("prompt must not be empty")
        try:
            import litellm
        except ModuleNotFoundError as exc:
            raise RuntimeError("litellm is not installed; run pip install -r requirements.txt") from exc

        otel_config = configure_langfuse_otel_env(self.callbacks)
        runtime_callbacks = litellm_callbacks_for_runtime(self.callbacks)
        if runtime_callbacks:
            litellm.callbacks = runtime_callbacks

        metadata = _litellm_metadata()
        # Revisions run hotter than first-pass generation so the requested natural-language
        # edit visibly diverges from the source package instead of being reproduced verbatim.
        is_revision = _LLM_TRACE_CONTEXT.get().get("operation") == "package_revision"
        temperature = self.revision_temperature if is_revision else self.temperature
        request: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You generate grounded lesson package outlines for LessonPack AI. "
                        "Return exactly one valid JSON object."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "metadata": metadata,
            "response_format": {"type": "json_object"},
            "temperature": temperature,
            "drop_params": True,
        }
        if self.fallback_models:
            request["fallbacks"] = list(self.fallback_models)
        if self.timeout_seconds is not None:
            request["timeout"] = self.timeout_seconds

        response: Any | None = None
        response_text: str | None = None
        response_cost: float | None = None
        error: Exception | None = None
        started_at_ns = time.time_ns()
        try:
            response = litellm.completion(**request)
            response_text = _extract_message_content(response)
            response_cost = _calculate_completion_cost(litellm, response)
        except Exception as exc:
            error = exc
            raise
        finally:
            ended_at_ns = time.time_ns()
            if otel_config.enabled:
                _record_langfuse_trace_safely(
                    callbacks=self.callbacks,
                    provider_name=self.name,
                    model=self.model,
                    fallback_models=self.fallback_models,
                    input_payload=request["messages"],
                    response=response,
                    response_text=response_text,
                    metadata=metadata,
                    started_at_ns=started_at_ns,
                    ended_at_ns=ended_at_ns,
                    model_parameters={
                        "temperature": request["temperature"],
                        "response_format": request["response_format"],
                        "fallbacks": request.get("fallbacks", []),
                    },
                    response_cost=response_cost,
                    error=error,
                )
        if response_text is None:
            raise RuntimeError("LLM provider returned no response text")
        return response_text


HTTP_PROVIDER_NAMES = {"http_chat", "openai_compatible"}


def create_llm_provider_from_config(config: LessonPackConfig) -> LLMProvider:
    load_env_file()
    provider_name = config.llm.provider.casefold()
    if provider_name == "mock":
        return MockLLMProvider()
    if provider_name in HTTP_PROVIDER_NAMES:
        if not config.llm.base_url:
            raise ValueError("llm.base_url is required for http_chat provider")
        if not config.llm.api_key_env:
            raise ValueError("llm.api_key_env is required for http_chat provider")
        if config.llm.timeout_seconds is None:
            raise ValueError("llm.timeout_seconds is required for http_chat provider")
        api_key = os.getenv(config.llm.api_key_env)
        if api_key is None or not api_key.strip():
            raise ValueError(f"{config.llm.api_key_env} is required for http_chat provider")
        return HTTPChatCompletionsProvider(
            base_url=config.llm.base_url,
            api_key=api_key,
            model=config.llm.model,
            timeout_seconds=config.llm.timeout_seconds,
        )
    if provider_name == "litellm":
        return LiteLLMProvider(
            model=config.llm.model,
            fallback_models=config.llm.fallback_models,
            timeout_seconds=config.llm.timeout_seconds,
            callbacks=_configured_callbacks(config),
            schema_retries=config.llm.schema_retries,
            temperature=config.llm.temperature,
            revision_temperature=config.llm.revision_temperature,
        )
    raise ValueError(f"unsupported LLM provider: {config.llm.provider}")


def create_llm_provider_from_env() -> LLMProvider:
    load_env_file()
    config_path = os.getenv("LESSONPACK_CONFIG")
    if config_path:
        from lectureops_agent.config import load_config

        return create_llm_provider_from_config(load_config(config_path))

    provider_name = os.getenv("LESSONPACK_LLM_PROVIDER", "mock").strip().casefold()
    if provider_name in {"", "mock"}:
        return MockLLMProvider()
    if provider_name == "litellm":
        return LiteLLMProvider(
            model=os.getenv("LESSONPACK_LITELLM_MODEL", "gpt-4o-mini"),
            fallback_models=_split_env_list(os.getenv("LESSONPACK_LITELLM_FALLBACK_MODELS", "gemini/gemini-3.5-flash")),
            timeout_seconds=_optional_float_env("LESSONPACK_LITELLM_TIMEOUT_SECONDS"),
            callbacks=_split_env_list(
                os.getenv("LESSONPACK_LITELLM_CALLBACKS")
                or os.getenv("LESSONPACK_LITELLM_SUCCESS_CALLBACKS", "langfuse_otel")
            ),
            schema_retries=_optional_int_env("LESSONPACK_LLM_SCHEMA_RETRIES", default=1),
            temperature=_optional_float_env("LESSONPACK_LITELLM_TEMPERATURE") or 0.1,
            revision_temperature=_optional_float_env("LESSONPACK_LITELLM_REVISION_TEMPERATURE") or 0.6,
        )
    raise ValueError(f"unsupported LLM provider without LESSONPACK_CONFIG: {provider_name}")


def _configured_callbacks(config: LessonPackConfig) -> list[str]:
    return list(config.llm.callbacks or config.llm.success_callbacks)


def _extract_message_content(response: Any) -> str:
    content = None
    if isinstance(response, dict):
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("LLM provider response missing choices[0].message.content") from exc
    else:
        try:
            message = response.choices[0].message
            content = message.get("content") if isinstance(message, dict) else message.content
        except (AttributeError, IndexError, TypeError) as exc:
            raise RuntimeError("LLM provider response missing choices[0].message.content") from exc
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("LLM provider returned empty content")
    return content.strip()


def _litellm_metadata() -> dict[str, Any]:
    app_env = os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "development"
    metadata: dict[str, Any] = {
        "generation_name": os.getenv("LESSONPACK_LANGFUSE_GENERATION_NAME", "lessonpack-ai-generation"),
        "trace_name": os.getenv("LESSONPACK_LANGFUSE_TRACE_NAME", "lessonpack-ai-mvp"),
        "session_id": os.getenv("LESSONPACK_LANGFUSE_SESSION_ID", "lessonpack-ai"),
        "tags": ["lessonpack-ai", app_env],
    }
    trace_id = os.getenv("LESSONPACK_LANGFUSE_TRACE_ID", "").strip()
    if trace_id:
        metadata["trace_id"] = trace_id
    metadata.update(_LLM_TRACE_CONTEXT.get())
    return metadata


@contextmanager
def llm_trace_context(metadata: dict[str, Any]) -> Iterator[None]:
    merged = dict(_LLM_TRACE_CONTEXT.get())
    merged.update({key: value for key, value in metadata.items() if value is not None})
    token = _LLM_TRACE_CONTEXT.set(merged)
    try:
        yield
    finally:
        _LLM_TRACE_CONTEXT.reset(token)


def _wait_before_otel_flush() -> None:
    value = os.getenv("LESSONPACK_LANGFUSE_FLUSH_WAIT_SECONDS", "1.0").strip()
    try:
        seconds = float(value)
    except ValueError:
        seconds = 1.0
    if seconds > 0:
        time.sleep(seconds)


def _calculate_completion_cost(litellm_module: Any, response: Any) -> float | None:
    calculator = getattr(litellm_module, "completion_cost", None)
    if calculator is None:
        return None
    try:
        value = calculator(completion_response=response)
    except Exception:  # noqa: BLE001 - cost telemetry must not fail generation.
        return None
    if isinstance(value, (int, float)) and value >= 0:
        return float(value)
    return None


def _record_langfuse_trace_safely(**kwargs: Any) -> None:
    try:
        record_langfuse_llm_span(**kwargs)
        _wait_before_otel_flush()
        flush_langfuse_otel()
    except Exception as exc:  # noqa: BLE001 - observability must not break LLM generation.
        _LOGGER.warning("Langfuse OTEL trace export failed: %s", exc)


def _split_env_list(value: str | None) -> list[str]:
    if value is None:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _optional_float_env(name: str) -> int | float | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    parsed = float(value)
    return int(parsed) if parsed.is_integer() else parsed


def _optional_int_env(name: str, *, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return int(value)
