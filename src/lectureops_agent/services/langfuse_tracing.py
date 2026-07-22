from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from typing import Any, MutableMapping, Sequence


LANGFUSE_OTEL_CALLBACK = "langfuse_otel"
DEFAULT_LANGFUSE_OTEL_HOST = "https://us.cloud.langfuse.com"
INGESTION_VERSION_HEADER = "x-langfuse-ingestion-version=4"
_TRACER_PROVIDER: Any | None = None


@dataclass(frozen=True)
class LangfuseOtelConfigResult:
    enabled: bool
    endpoint: str | None
    host: str | None
    headers_configured: bool
    protocol: str | None


def configure_langfuse_otel_env(
    callbacks: Sequence[str],
    *,
    env: MutableMapping[str, str] | None = None,
) -> LangfuseOtelConfigResult:
    """Configure OTLP trace exporter env vars for Langfuse when requested."""
    target_env = env if env is not None else os.environ
    callback_names = {callback.strip().casefold() for callback in callbacks}
    if LANGFUSE_OTEL_CALLBACK not in callback_names:
        return LangfuseOtelConfigResult(
            enabled=False,
            endpoint=target_env.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or target_env.get("OTEL_EXPORTER_OTLP_ENDPOINT"),
            host=_resolve_langfuse_host(target_env),
            headers_configured=bool(target_env.get("OTEL_EXPORTER_OTLP_TRACES_HEADERS") or target_env.get("OTEL_EXPORTER_OTLP_HEADERS")),
            protocol=target_env.get("OTEL_EXPORTER_OTLP_TRACES_PROTOCOL") or target_env.get("OTEL_EXPORTER_OTLP_PROTOCOL") or target_env.get("OTEL_EXPORTER"),
        )

    host = _resolve_langfuse_host(target_env)
    endpoint = _normalize_trace_endpoint(
        target_env.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or target_env.get("OTEL_EXPORTER_OTLP_ENDPOINT") or _endpoint_from_host(host)
    )
    if endpoint:
        target_env["OTEL_EXPORTER_OTLP_ENDPOINT"] = endpoint
        target_env.setdefault("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", endpoint)
    target_env.setdefault("OTEL_EXPORTER_OTLP_PROTOCOL", "otlp_http")
    target_env.setdefault("OTEL_EXPORTER_OTLP_TRACES_PROTOCOL", "http/protobuf")
    target_env.setdefault("OTEL_SERVICE_NAME", "lessonpack-ai")

    headers_configured = _configure_otel_headers(target_env)
    return LangfuseOtelConfigResult(
        enabled=True,
        endpoint=target_env.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or target_env.get("OTEL_EXPORTER_OTLP_ENDPOINT"),
        host=host,
        headers_configured=headers_configured,
        protocol=target_env.get("OTEL_EXPORTER_OTLP_TRACES_PROTOCOL") or target_env.get("OTEL_EXPORTER_OTLP_PROTOCOL") or target_env.get("OTEL_EXPORTER"),
    )


def litellm_callbacks_for_runtime(callbacks: Sequence[str]) -> list[str]:
    """Keep broken SDK-only OTEL callback out of LiteLLM and export spans directly."""
    return [callback for callback in callbacks if callback.strip().casefold() != LANGFUSE_OTEL_CALLBACK]


def record_langfuse_llm_span(
    *,
    callbacks: Sequence[str],
    provider_name: str,
    model: str,
    fallback_models: Sequence[str],
    input_payload: Any,
    response: Any | None,
    response_text: str | None,
    metadata: dict[str, Any],
    started_at_ns: int,
    ended_at_ns: int,
    model_parameters: dict[str, Any] | None = None,
    response_cost: float | None = None,
    error: BaseException | None = None,
) -> bool:
    config = configure_langfuse_otel_env(callbacks)
    if not config.enabled or not config.endpoint or not config.headers_configured:
        return False

    tracer_provider = _ensure_tracer_provider(config)
    if tracer_provider is None:
        return False

    tracer = tracer_provider.get_tracer("lessonpack-ai")
    span_name = str(metadata.get("generation_name") or "lessonpack-ai-generation")
    span = tracer.start_span(span_name, start_time=started_at_ns)
    try:
        environment = os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "development"
        actual_model = _response_field(response, "model") or model
        trace_name = str(metadata.get("trace_name") or "lessonpack-ai-mvp")
        session_id = metadata.get("session_id")
        tags = [str(tag) for tag in metadata.get("tags") or []]

        span.set_attribute("service.name", os.getenv("OTEL_SERVICE_NAME", "lessonpack-ai"))
        span.set_attribute("deployment.environment", environment)
        span.set_attribute("gen_ai.system", "litellm")
        span.set_attribute("gen_ai.request.model", model)
        span.set_attribute("gen_ai.response.model", str(actual_model))
        span.set_attribute("llm.model_name", str(actual_model))
        span.set_attribute("model", str(actual_model))
        span.set_attribute("llm.provider_name", provider_name)
        span.set_attribute("llm.fallback_models", ",".join(fallback_models))
        span.set_attribute("langfuse.observation.type", "generation")
        span.set_attribute("langfuse.observation.model.name", str(actual_model))
        span.set_attribute("langfuse.trace.name", trace_name)
        span.set_attribute("langfuse.environment", environment)
        if session_id:
            span.set_attribute("langfuse.session.id", str(session_id))
        if tags:
            span.set_attribute("langfuse.trace.tags", tags)

        parameters = model_parameters or {}
        if parameters:
            span.set_attribute(
                "langfuse.observation.model.parameters",
                _json_attribute(parameters),
            )

        input_value, output_value = _safe_io_values(input_payload, response_text)
        span.set_attribute("langfuse.observation.input", _json_attribute(input_value))
        span.set_attribute("langfuse.trace.input", _json_attribute(input_value))
        span.set_attribute("langfuse.observation.output", _json_attribute(output_value))
        span.set_attribute("langfuse.trace.output", _json_attribute(output_value))

        span.set_attribute("llm.prompt.length", len(_json_attribute(input_payload)))
        span.set_attribute("llm.response.length", len(response_text or ""))

        usage_details = _extract_usage_details(response)
        if usage_details:
            span.set_attribute(
                "langfuse.observation.usage_details",
                _json_attribute(usage_details),
            )
        if response_cost is not None and response_cost >= 0:
            span.set_attribute(
                "langfuse.observation.cost_details",
                _json_attribute({"total": response_cost}),
            )
            span.set_attribute("gen_ai.usage.cost", response_cost)

        _set_filterable_metadata(
            span,
            metadata=metadata,
            provider_name=provider_name,
            fallback_models=fallback_models,
        )
        if error is not None:
            safe_error = RuntimeError(redact_trace_error_message(str(error)))
            span.record_exception(safe_error, timestamp=ended_at_ns)
            span.set_attribute("langfuse.observation.level", "ERROR")
            span.set_attribute("langfuse.observation.status_message", str(safe_error))
            _set_error_status(span, safe_error)
    finally:
        span.end(end_time=max(started_at_ns + 1, ended_at_ns))
    return True


def flush_langfuse_otel() -> bool:
    """Force flush OpenTelemetry spans for short-lived CLI evaluation runs."""
    flushed = False
    if _TRACER_PROVIDER is not None:
        flushed = _force_flush_provider(_TRACER_PROVIDER) or flushed

    try:
        from opentelemetry import trace
    except ModuleNotFoundError:
        return flushed

    provider = trace.get_tracer_provider()
    return _force_flush_provider(provider) or flushed


def _ensure_tracer_provider(config: LangfuseOtelConfigResult) -> Any | None:
    global _TRACER_PROVIDER
    if _TRACER_PROVIDER is not None:
        return _TRACER_PROVIDER
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ModuleNotFoundError:
        return None

    exporter = OTLPSpanExporter(endpoint=config.endpoint, headers=_parse_otel_headers(os.environ.get("OTEL_EXPORTER_OTLP_TRACES_HEADERS") or os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "")))
    resource = Resource.create(
        {
            "service.name": os.getenv("OTEL_SERVICE_NAME", "lessonpack-ai"),
            "deployment.environment": os.getenv("APP_ENV", "development"),
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter, schedule_delay_millis=100))
    _TRACER_PROVIDER = provider
    return provider


def _force_flush_provider(provider: Any) -> bool:
    force_flush = getattr(provider, "force_flush", None)
    if force_flush is None:
        return False
    try:
        result = force_flush(timeout_millis=10000)
    except TypeError:
        result = force_flush()
    return bool(result) if result is not None else True


def _resolve_langfuse_host(env: MutableMapping[str, str]) -> str:
    for key in ("LANGFUSE_OTEL_HOST", "LANGFUSE_BASE_URL", "LANGFUSE_HOST"):
        value = env.get(key)
        if value and value.strip():
            return value.strip().rstrip("/")
    return DEFAULT_LANGFUSE_OTEL_HOST


def _endpoint_from_host(host: str | None) -> str | None:
    if not host:
        return None
    normalized = host.rstrip("/")
    if normalized.endswith("/api/public/otel/v1/traces"):
        return normalized
    if normalized.endswith("/api/public/otel"):
        return f"{normalized}/v1/traces"
    return f"{normalized}/api/public/otel/v1/traces"


def _normalize_trace_endpoint(endpoint: str | None) -> str | None:
    if not endpoint:
        return None
    normalized = endpoint.rstrip("/")
    if normalized.endswith("/api/public/otel/v1/traces"):
        return normalized
    if normalized.endswith("/api/public/otel"):
        return f"{normalized}/v1/traces"
    return normalized


def _configure_otel_headers(env: MutableMapping[str, str]) -> bool:
    existing = (env.get("OTEL_EXPORTER_OTLP_TRACES_HEADERS") or env.get("OTEL_EXPORTER_OTLP_HEADERS") or "").strip()
    if existing:
        if "x-langfuse-ingestion-version" not in existing:
            existing = f"{existing},{INGESTION_VERSION_HEADER}"
        env.setdefault("OTEL_EXPORTER_OTLP_HEADERS", existing)
        env.setdefault("OTEL_EXPORTER_OTLP_TRACES_HEADERS", existing)
        return True

    public_key = env.get("LANGFUSE_PUBLIC_KEY", "").strip()
    secret_key = env.get("LANGFUSE_SECRET_KEY", "").strip()
    if not public_key or not secret_key:
        return False

    auth = base64.b64encode(f"{public_key}:{secret_key}".encode("utf-8")).decode("ascii")
    headers = f"Authorization=Basic {auth},{INGESTION_VERSION_HEADER}"
    env["OTEL_EXPORTER_OTLP_HEADERS"] = headers
    env["OTEL_EXPORTER_OTLP_TRACES_HEADERS"] = headers
    return True


def _parse_otel_headers(value: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for item in value.split(","):
        if "=" not in item:
            continue
        key, header_value = item.split("=", 1)
        key = key.strip()
        if key:
            headers[key] = header_value.strip()
    return headers


def _safe_io_values(input_payload: Any, response_text: str | None) -> tuple[Any, Any]:
    if _capture_content_enabled():
        return input_payload, {"content": response_text} if response_text is not None else None
    return (
        {
            "content_capture": "redacted",
            "message_count": len(input_payload) if isinstance(input_payload, list) else None,
            "prompt_characters": len(_json_attribute(input_payload)),
            "messages": _message_structure(input_payload),
        },
        {
            "content_capture": "redacted",
            "response_characters": len(response_text or ""),
            "status": "completed" if response_text is not None else "failed",
            **_response_structure(response_text),
        },
    )


def _capture_content_enabled() -> bool:
    value = os.getenv("LESSONPACK_LANGFUSE_CAPTURE_CONTENT", "false").strip().casefold()
    return value in {"1", "true", "yes", "on"}


def _message_structure(input_payload: Any) -> list[dict[str, Any]]:
    if not isinstance(input_payload, list):
        return []
    structure: list[dict[str, Any]] = []
    for item in input_payload:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        structure.append(
            {
                "role": str(item.get("role") or "unknown"),
                "content_characters": len(content) if isinstance(content, str) else 0,
            }
        )
    return structure


def _response_structure(response_text: str | None) -> dict[str, Any]:
    if not response_text:
        return {}
    try:
        payload = json.loads(response_text)
    except (json.JSONDecodeError, TypeError):
        return {"response_format": "text"}
    if isinstance(payload, dict):
        return {
            "response_format": "json_object",
            "top_level_fields": sorted(str(key) for key in payload),
        }
    return {"response_format": type(payload).__name__}


def _json_attribute(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _response_field(response: Any | None, name: str) -> Any | None:
    if response is None:
        return None
    if isinstance(response, dict):
        return response.get(name)
    return getattr(response, name, None)


def _extract_usage_details(response: Any | None) -> dict[str, Any]:
    usage = _response_field(response, "usage")
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        usage = usage.model_dump(exclude_none=True)
    elif not isinstance(usage, dict):
        usage = {
            key: getattr(usage, key, None)
            for key in (
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "prompt_tokens_details",
                "completion_tokens_details",
            )
        }
    if not isinstance(usage, dict):
        return {}

    allowed_keys = (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "prompt_tokens_details",
        "completion_tokens_details",
    )
    return {
        key: _json_compatible(usage[key])
        for key in allowed_keys
        if usage.get(key) is not None
    }


def _json_compatible(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_none=True)
    if isinstance(value, dict):
        return {key: _json_compatible(item) for key, item in value.items() if item is not None}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]
    return value


def _set_filterable_metadata(
    span: Any,
    *,
    metadata: dict[str, Any],
    provider_name: str,
    fallback_models: Sequence[str],
) -> None:
    span.set_attribute("langfuse.observation.metadata.provider_name", provider_name)
    if fallback_models:
        span.set_attribute(
            "langfuse.observation.metadata.fallback_models",
            ",".join(fallback_models),
        )
    ignored = {"generation_name", "trace_name", "session_id", "tags"}
    for key, value in metadata.items():
        if key in ignored or value is None:
            continue
        attribute_key = "".join(char if char.isalnum() or char in "_-" else "_" for char in str(key))
        if isinstance(value, (str, bool, int, float)):
            span.set_attribute(f"langfuse.observation.metadata.{attribute_key}", value)
        else:
            span.set_attribute(
                f"langfuse.observation.metadata.{attribute_key}",
                _json_attribute(value),
            )


def _set_error_status(span: Any, error: BaseException) -> None:
    try:
        from opentelemetry.trace import Status, StatusCode
    except ModuleNotFoundError:
        return
    span.set_status(Status(StatusCode.ERROR, str(error)))


def redact_trace_error_message(message: str) -> str:
    redacted = re.sub(r"(?i)([?&](?:key|api_key|token)=)[^&\s]+", r"\1[REDACTED]", message)
    for env_name in (
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
    ):
        secret = os.getenv(env_name, "")
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted
