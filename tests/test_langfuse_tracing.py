import base64
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lectureops_agent.services.langfuse_tracing import configure_langfuse_otel_env
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
            return {"choices": [{"message": {"content": "ok"}}]}

        fake_litellm = types.SimpleNamespace(callbacks=[], completion=fake_completion)
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
        flush.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
