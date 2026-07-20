from __future__ import annotations

import base64
import os
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
    prompt: str,
    response_text: str,
    metadata: dict[str, Any],
) -> bool:
    config = configure_langfuse_otel_env(callbacks)
    if not config.enabled or not config.endpoint or not config.headers_configured:
        return False

    tracer_provider = _ensure_tracer_provider(config)
    if tracer_provider is None:
        return False

    tracer = tracer_provider.get_tracer("lessonpack-ai")
    span_name = str(metadata.get("generation_name") or "lessonpack-ai-generation")
    with tracer.start_as_current_span(span_name) as span:
        span.set_attribute("service.name", os.getenv("OTEL_SERVICE_NAME", "lessonpack-ai"))
        span.set_attribute("deployment.environment", os.getenv("APP_ENV", "development"))
        span.set_attribute("gen_ai.system", "litellm")
        span.set_attribute("gen_ai.request.model", model)
        span.set_attribute("llm.provider_name", provider_name)
        span.set_attribute("llm.fallback_models", ",".join(fallback_models))
        span.set_attribute("llm.prompt.length", len(prompt))
        span.set_attribute("llm.response.length", len(response_text))
        for key in ("trace_name", "trace_id", "session_id", "generation_name"):
            value = metadata.get(key)
            if value:
                span.set_attribute(f"langfuse.{key}", str(value))
        tags = metadata.get("tags") or []
        if tags:
            span.set_attribute("langfuse.tags", ",".join(str(tag) for tag in tags))
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