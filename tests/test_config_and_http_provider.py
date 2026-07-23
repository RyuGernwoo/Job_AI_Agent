import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fastapi.testclient import TestClient

from lectureops_agent.app.main import create_app
from lectureops_agent.config import LessonPackConfig, load_config
from lectureops_agent.models.schemas import NCSUnit, ProjectCreate
from lectureops_agent.services.vector_store import InMemoryVectorStore
from lectureops_agent.services.llm_provider import (
    HTTPChatCompletionsProvider,
    LiteLLMProvider,
    create_llm_provider_from_config,
)


class ChatCompletionHandler(BaseHTTPRequestHandler):
    received_headers: dict[str, str] = {}
    received_payload: dict = {}

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)
        type(self).received_headers = dict(self.headers)
        type(self).received_payload = json.loads(body.decode("utf-8"))
        response = {
            "choices": [
                {
                    "message": {
                        "content": "HTTP provider outline: structure the lesson package from evidence."
                    }
                }
            ]
        }
        response_bytes = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)

    def log_message(self, format: str, *args) -> None:
        return


class ConfigAndHTTPProviderTests(unittest.TestCase):
    def test_load_config_reads_explicit_yaml_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "chunk_size_chars: 900",
                        "chunk_overlap_chars: 150",
                        "retrieval_top_k: 4",
                        "llm:",
                        "  provider: mock",
                        "  model: lessonpack-mock",
                        "vector_store:",
                        "  provider: memory",
                    ]
                ),
                encoding="utf-8",
            )

            config = load_config(config_path)

        self.assertEqual(config.chunk_size_chars, 900)
        self.assertEqual(config.chunk_overlap_chars, 150)
        self.assertEqual(config.retrieval_top_k, 4)
        self.assertEqual(config.llm.provider, "mock")
        self.assertEqual(config.llm.model, "lessonpack-mock")
        self.assertEqual(config.llm.fallback_models, [])
        self.assertEqual(config.llm.callbacks, [])
        self.assertEqual(config.vector_store.provider, "memory")
        self.assertEqual(config.vector_store.baseline_project_id, "mvp-dataset")
        self.assertEqual(config.vector_store.candidate_k, 20)
        self.assertEqual(config.vector_store.embedding_provider, "hash")
        self.assertEqual(config.vector_store.embedding_dimensions, 64)

    def test_load_config_reads_litellm_routing_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "chunk_size_chars: 800",
                        "chunk_overlap_chars: 120",
                        "retrieval_top_k: 5",
                        "llm:",
                        "  provider: litellm",
                        "  model: gpt-4o-mini",
                        "  fallback_models:",
                        "    - gemini/gemini-3.5-flash",
                        "  timeout_seconds: 30",
                        "  callbacks:",
                        "    - langfuse_otel",
                        "vector_store:",
                        "  provider: memory",
                    ]
                ),
                encoding="utf-8",
            )

            config = load_config(config_path)

        self.assertEqual(config.llm.provider, "litellm")
        self.assertEqual(config.llm.model, "gpt-4o-mini")
        self.assertEqual(config.llm.fallback_models, ["gemini/gemini-3.5-flash"])
        self.assertEqual(config.llm.callbacks, ["langfuse_otel"])

    def test_create_app_uses_configured_chunk_size_for_uploads(self):
        config = LessonPackConfig.model_validate(
            {
                "chunk_size_chars": 40,
                "chunk_overlap_chars": 5,
                "retrieval_top_k": 2,
                "llm": {"provider": "mock", "model": "lessonpack-mock"},
                "vector_store": {"provider": "memory"},
            }
        )
        client = TestClient(create_app(app_config=config))
        project_payload = ProjectCreate(
            course_type="ncs",
            course_title="Generative AI Python Basics",
            lesson_title="Python functions",
            learner_profile="Beginner learners",
            learning_objectives=["Explain function inputs and returns."],
            ncs_units=[
                NCSUnit(
                    unit_code="MVP-NCS-001",
                    unit_name="AI basics",
                    elements=["Explain basic AI concepts."],
                )
            ],
        ).model_dump()
        created = client.post("/api/projects", json=project_payload)
        project_id = created.json()["project_id"]

        uploaded = client.post(
            f"/api/projects/{project_id}/materials",
            files={"file": ("sample.md", "Functions return output. " * 10, "text/markdown")},
        )

        self.assertEqual(uploaded.status_code, 200)
        self.assertGreater(uploaded.json()["chunk_count"], 1)

    def test_create_llm_provider_from_config_builds_http_chat_provider(self):
        config = LessonPackConfig.model_validate(
            {
                "chunk_size_chars": 800,
                "chunk_overlap_chars": 120,
                "retrieval_top_k": 5,
                "llm": {
                    "provider": "http_chat",
                    "base_url": "http://127.0.0.1:1/v1/chat/completions",
                    "api_key_env": "LESSONPACK_TEST_API_KEY",
                    "model": "test-model",
                    "timeout_seconds": 3,
                },
                "vector_store": {"provider": "memory"},
            }
        )

        with patch.dict(os.environ, {"LESSONPACK_TEST_API_KEY": "secret-key"}, clear=False):
            provider = create_llm_provider_from_config(config)

        self.assertIsInstance(provider, HTTPChatCompletionsProvider)
        self.assertEqual(provider.name, "http_chat:test-model")

    def test_create_llm_provider_from_config_builds_litellm_provider(self):
        config = LessonPackConfig.model_validate(
            {
                "chunk_size_chars": 800,
                "chunk_overlap_chars": 120,
                "retrieval_top_k": 5,
                "llm": {
                    "provider": "litellm",
                    "model": "gpt-4o-mini",
                    "fallback_models": ["gemini/gemini-3.5-flash"],
                    "timeout_seconds": 30,
                    "callbacks": ["langfuse_otel"],
                },
                "vector_store": {"provider": "memory"},
            }
        )

        provider = create_llm_provider_from_config(config)

        self.assertIsInstance(provider, LiteLLMProvider)
        self.assertEqual(provider.model, "gpt-4o-mini")
        self.assertEqual(provider.fallback_models, ["gemini/gemini-3.5-flash"])
        self.assertEqual(provider.callbacks, ["langfuse_otel"])
        self.assertEqual(provider.schema_retries, 1)
        # Revisions must run hotter than first-pass generation by default so a natural-language
        # edit diverges from the source package, but moderate enough to keep the schema valid.
        self.assertEqual(provider.temperature, 0.1)
        self.assertEqual(provider.revision_temperature, 0.3)
        self.assertGreater(provider.revision_temperature, provider.temperature)

    def test_create_llm_provider_from_config_uses_configured_temperatures(self):
        config = LessonPackConfig.model_validate(
            {
                "chunk_size_chars": 800,
                "chunk_overlap_chars": 120,
                "retrieval_top_k": 5,
                "llm": {
                    "provider": "litellm",
                    "model": "gpt-4o-mini",
                    "timeout_seconds": 30,
                    "temperature": 0.2,
                    "revision_temperature": 0.9,
                },
                "vector_store": {"provider": "memory"},
            }
        )

        provider = create_llm_provider_from_config(config)

        self.assertIsInstance(provider, LiteLLMProvider)
        self.assertEqual(provider.temperature, 0.2)
        self.assertEqual(provider.revision_temperature, 0.9)

    def test_http_chat_provider_posts_prompt_and_returns_message_content(self):
        server = HTTPServer(("127.0.0.1", 0), ChatCompletionHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/v1/chat/completions"
        provider = HTTPChatCompletionsProvider(
            base_url=url,
            api_key="secret-key",
            model="test-model",
            timeout_seconds=3,
        )

        try:
            result = provider.generate(prompt="Create a grounded lesson package.")
        finally:
            server.shutdown()
            server.server_close()

        self.assertEqual(result, "HTTP provider outline: structure the lesson package from evidence.")
        self.assertEqual(ChatCompletionHandler.received_headers["Authorization"], "Bearer secret-key")
        self.assertEqual(ChatCompletionHandler.received_payload["model"], "test-model")
        self.assertEqual(
            ChatCompletionHandler.received_payload["messages"][-1]["content"],
            "Create a grounded lesson package.",
        )

    def test_create_llm_provider_from_config_requires_api_key_env(self):
        config = LessonPackConfig.model_validate(
            {
                "chunk_size_chars": 800,
                "chunk_overlap_chars": 120,
                "retrieval_top_k": 5,
                "llm": {
                    "provider": "http_chat",
                    "base_url": "http://127.0.0.1:1/v1/chat/completions",
                    "api_key_env": "LESSONPACK_MISSING_API_KEY",
                    "model": "test-model",
                    "timeout_seconds": 3,
                },
                "vector_store": {"provider": "memory"},
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            missing_env_file = Path(tmpdir) / "missing.env"
            with patch.dict(os.environ, {"LESSONPACK_ENV_FILE": str(missing_env_file)}, clear=True):
                with self.assertRaisesRegex(ValueError, "LESSONPACK_MISSING_API_KEY"):
                    create_llm_provider_from_config(config)


if __name__ == "__main__":
    unittest.main()
