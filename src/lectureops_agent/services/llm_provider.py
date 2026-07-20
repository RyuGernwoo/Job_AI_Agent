from __future__ import annotations

import json
import os
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from lectureops_agent.config import LessonPackConfig
from lectureops_agent.env import load_env_file


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
            "the retrieved evidence and require instructor review before approval."
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
                    "content": "You generate grounded lesson package outlines for LessonPack AI.",
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
    ) -> None:
        if not model.strip():
            raise ValueError("model is required")
        self.model = model
        self.fallback_models = fallback_models or []
        self.timeout_seconds = timeout_seconds
        self.callbacks = callbacks or []
        fallback_label = f" -> {', '.join(self.fallback_models)}" if self.fallback_models else ""
        self.name = f"litellm:{model}{fallback_label}"

    def generate(self, *, prompt: str) -> str:
        if not prompt.strip():
            raise ValueError("prompt must not be empty")
        try:
            import litellm
        except ModuleNotFoundError as exc:
            raise RuntimeError("litellm is not installed; run pip install -r requirements.txt") from exc

        if self.callbacks:
            litellm.callbacks = list(self.callbacks)

        request: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You generate grounded lesson package outlines for LessonPack AI.",
                },
                {"role": "user", "content": prompt},
            ],
        }
        if self.fallback_models:
            request["fallbacks"] = list(self.fallback_models)
        if self.timeout_seconds is not None:
            request["timeout"] = self.timeout_seconds

        response = litellm.completion(**request)
        return _extract_message_content(response)


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
            fallback_models=_split_env_list(os.getenv("LESSONPACK_LITELLM_FALLBACK_MODELS", "gemini/gemini-2.0-flash")),
            timeout_seconds=_optional_float_env("LESSONPACK_LITELLM_TIMEOUT_SECONDS"),
            callbacks=_split_env_list(
                os.getenv("LESSONPACK_LITELLM_CALLBACKS")
                or os.getenv("LESSONPACK_LITELLM_SUCCESS_CALLBACKS", "langfuse_otel")
            ),
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
