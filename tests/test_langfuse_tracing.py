import base64
import json
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.check_langfuse_trace import _detected_result
from lectureops_agent.services.langfuse_tracing import (
    configure_langfuse_otel_env,
    record_langfuse_llm_span,
    redact_trace_error_message,
)
from lectureops_agent.services.llm_provider import LiteLLMProvider


class LangfuseTracingTests(unittest.TestCase):
    def test_configure_langfuse_otel_env_derives_endpoint_and_headers(self):
        env = {
            "LANGFUSE_PUBLIC_KEY": "pk-test",
            "LANGFUSE_SECRET_KEY": "sk-test",
            "LANGFUSE_OTEL_HOST": "https://jp.cloud.langfuse.com",
        }

        result = configure_langfuse_otel_env(["langfuse_otel"], env=env)

        expected_auth = base64.b64encode(b"pk-test:sk-test").decode("ascii")
        self.assertTrue(result.enabled)
        self.assertEqual(result.host, "https://jp.cloud.langfuse.com")
        self.assertEqual(result.endpoint, "https://jp.cloud.langfuse.com/api/public/otel/v1/traces")
        self.assertEqual(result.protocol, "http/protobuf")
        self.assertTrue(result.headers_configured)
        self.assertEqual(env["OTEL_EXPORTER_OTLP_PROTOCOL"], "otlp_http")
        self.assertEqual(env["OTEL_EXPORTER_OTLP_ENDPOINT"], "https://jp.cloud.langfuse.com/api/public/otel/v1/traces")
        self.assertIn(f"Authorization=Basic {expected_auth}", env["OTEL_EXPORTER_OTLP_HEADERS"])
        self.assertIn("x-langfuse-ingestion-version=4", env["OTEL_EXPORTER_OTLP_HEADERS"])

    def test_configure_langfuse_otel_env_appends_ingestion_header_to_existing_headers(self):
        env = {
            "LANGFUSE_PUBLIC_KEY": "pk-test",
            "LANGFUSE_SECRET_KEY": "sk-test",
            "LANGFUSE_BASE_URL": "https://cloud.langfuse.com",
            "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=Basic existing",
        }

        result = configure_langfuse_otel_env(["langfuse_otel"], env=env)

        self.assertTrue(result.enabled)
        self.assertEqual(result.endpoint, "https://cloud.langfuse.com/api/public/otel/v1/traces")
        self.assertEqual(env["OTEL_EXPORTER_OTLP_TRACES_HEADERS"], "Authorization=Basic existing,x-langfuse-ingestion-version=4")

    def test_litellm_provider_configures_otel_metadata_and_flushes(self):
        captured: dict = {}

        def fake_completion(**request):
            captured.update(request)
            return {
                "model": "gpt-4o-mini-2024-07-18",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
            }

        fake_litellm = types.SimpleNamespace(
            callbacks=[],
            completion=fake_completion,
            completion_cost=lambda **_: 0.000012,
        )
        env = {
            "LANGFUSE_PUBLIC_KEY": "pk-test",
            "LANGFUSE_SECRET_KEY": "sk-test",
            "LANGFUSE_OTEL_HOST": "https://jp.cloud.langfuse.com",
            "LESSONPACK_LANGFUSE_TRACE_ID": "trace-test-001",
            "LESSONPACK_LANGFUSE_SESSION_ID": "session-test",
            "LESSONPACK_LANGFUSE_FLUSH_WAIT_SECONDS": "0",
            "APP_ENV": "test",
        }
        provider = LiteLLMProvider(model="gpt-4o-mini", callbacks=["langfuse_otel"])

        with patch.dict(sys.modules, {"litellm": fake_litellm}), patch.dict(os.environ, env, clear=True), patch(
            "lectureops_agent.services.llm_provider.record_langfuse_llm_span",
            return_value=True,
        ) as record, patch(
            "lectureops_agent.services.llm_provider.flush_langfuse_otel",
            return_value=True,
        ) as flush:
            result = provider.generate(prompt="synthetic trace test")
            otel_endpoint = os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"]
            otel_headers = os.environ["OTEL_EXPORTER_OTLP_HEADERS"]

        self.assertEqual(result, "ok")
        self.assertEqual(fake_litellm.callbacks, [])
        self.assertEqual(captured["metadata"]["trace_id"], "trace-test-001")
        self.assertEqual(captured["metadata"]["session_id"], "session-test")
        self.assertEqual(captured["metadata"]["tags"], ["lessonpack-ai", "test"])
        self.assertEqual(captured["response_format"], {"type": "json_object"})
        self.assertEqual(captured["temperature"], 0.1)
        self.assertEqual(otel_endpoint, "https://jp.cloud.langfuse.com/api/public/otel/v1/traces")
        self.assertIn("x-langfuse-ingestion-version=4", otel_headers)
        record.assert_called_once()
        trace_call = record.call_args.kwargs
        self.assertEqual(trace_call["input_payload"], captured["messages"])
        self.assertEqual(trace_call["response_cost"], 0.000012)
        self.assertIsNone(trace_call["error"])
        self.assertLessEqual(trace_call["started_at_ns"], trace_call["ended_at_ns"])
        flush.assert_called_once_with()

    def test_record_langfuse_span_maps_rich_generation_fields_without_raw_content(self):
        fake_span = _FakeSpan()
        fake_provider = _FakeTracerProvider(fake_span)
        env = {
            "LANGFUSE_PUBLIC_KEY": "pk-test",
            "LANGFUSE_SECRET_KEY": "sk-test",
            "LANGFUSE_OTEL_HOST": "https://jp.cloud.langfuse.com",
            "LESSONPACK_LANGFUSE_CAPTURE_CONTENT": "false",
            "APP_ENV": "test",
        }

        with patch.dict(os.environ, env, clear=True), patch(
            "lectureops_agent.services.langfuse_tracing._ensure_tracer_provider",
            return_value=fake_provider,
        ):
            recorded = record_langfuse_llm_span(
                callbacks=["langfuse_otel"],
                provider_name="litellm:gpt-4o-mini",
                model="gpt-4o-mini",
                fallback_models=["gemini/gemini-3.5-flash"],
                input_payload=[{"role": "user", "content": "private lesson material"}],
                response={
                    "model": "gpt-4o-mini-2024-07-18",
                    "usage": {
                        "prompt_tokens": 20,
                        "completion_tokens": 5,
                        "total_tokens": 25,
                    },
                },
                response_text="private generated lesson",
                metadata={
                    "trace_name": "lessonpack-ai-mvp",
                    "generation_name": "lessonpack-ai-generation",
                    "session_id": "session-test",
                    "trace_id": "external-trace-id",
                    "project_id": "project-test",
                    "tags": ["lessonpack-ai", "test"],
                },
                started_at_ns=1_000,
                ended_at_ns=5_000,
                model_parameters={"temperature": 0.1},
                response_cost=0.000123,
            )

        self.assertTrue(recorded)
        self.assertEqual(fake_span.start_time, 1_000)
        self.assertEqual(fake_span.end_time, 5_000)
        self.assertEqual(fake_span.attributes["langfuse.trace.name"], "lessonpack-ai-mvp")
        self.assertEqual(fake_span.attributes["langfuse.session.id"], "session-test")
        self.assertEqual(fake_span.attributes["langfuse.observation.type"], "generation")
        self.assertEqual(
            fake_span.attributes["langfuse.observation.model.name"],
            "gpt-4o-mini-2024-07-18",
        )
        self.assertEqual(fake_span.attributes["llm.model_name"], "gpt-4o-mini-2024-07-18")
        self.assertEqual(fake_span.attributes["model"], "gpt-4o-mini-2024-07-18")
        input_value = json.loads(fake_span.attributes["langfuse.observation.input"])
        output_value = json.loads(fake_span.attributes["langfuse.observation.output"])
        self.assertEqual(input_value["content_capture"], "redacted")
        self.assertNotIn("private lesson material", fake_span.attributes["langfuse.observation.input"])
        self.assertEqual(output_value["content_capture"], "redacted")
        self.assertNotIn("private generated lesson", fake_span.attributes["langfuse.observation.output"])
        self.assertEqual(
            json.loads(fake_span.attributes["langfuse.observation.usage_details"])["total_tokens"],
            25,
        )
        self.assertEqual(
            json.loads(fake_span.attributes["langfuse.observation.cost_details"])["total"],
            0.000123,
        )
        self.assertEqual(
            fake_span.attributes["langfuse.observation.metadata.project_id"],
            "project-test",
        )

    def test_trace_diagnostic_accepts_model_from_otel_metadata(self):
        result = _detected_result(
            attempts=1,
            api="test",
            observations=[
                {
                    "id": "observation-1",
                    "traceId": "trace-1",
                    "name": "generation-1",
                    "traceName": "lessonpack-ai-mvp",
                    "type": "GENERATION",
                    "sessionId": "session-1",
                    "input": '{"content_capture":"redacted"}',
                    "output": '{"content_capture":"redacted"}',
                    "latency": 1.25,
                    "usageDetails": {"total": 12},
                    "costDetails": {"total": 0.0001},
                    "providedModelName": None,
                    "metadata": {
                        "attributes.langfuse.observation.model.name": "gpt-4o-mini-2024-07-18"
                    },
                }
            ],
        )

        self.assertTrue(result["rich_fields_complete"])
        self.assertEqual(result["observation"]["model"], "gpt-4o-mini-2024-07-18")
        self.assertEqual(result["observation"]["model_mapping"], "otel_metadata")

    def test_trace_error_redaction_removes_query_key_and_environment_secrets(self):
        env = {"GEMINI_API_KEY": "secret-gemini-value"}
        message = "request failed: https://example.test?key=secret-gemini-value&mode=test"

        with patch.dict(os.environ, env, clear=True):
            redacted = redact_trace_error_message(message)

        self.assertNotIn("secret-gemini-value", redacted)
        self.assertIn("key=[REDACTED]", redacted)


class _FakeSpan:
    def __init__(self) -> None:
        self.attributes: dict[str, object] = {}
        self.start_time: int | None = None
        self.end_time: int | None = None

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value

    def record_exception(self, *_args, **_kwargs) -> None:
        return

    def set_status(self, *_args, **_kwargs) -> None:
        return

    def end(self, *, end_time: int) -> None:
        self.end_time = end_time


class _FakeTracer:
    def __init__(self, span: _FakeSpan) -> None:
        self.span = span

    def start_span(self, _name: str, *, start_time: int) -> _FakeSpan:
        self.span.start_time = start_time
        return self.span


class _FakeTracerProvider:
    def __init__(self, span: _FakeSpan) -> None:
        self.span = span

    def get_tracer(self, _name: str) -> _FakeTracer:
        return _FakeTracer(self.span)


if __name__ == "__main__":
    unittest.main()
