import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lectureops_agent.env import load_env_file
from lectureops_agent.services.llm_provider import HTTPChatCompletionsProvider, create_llm_provider_from_env
from lectureops_agent.services.llm_provider_readiness import check_llm_provider_readiness


class EnvLoadingTests(unittest.TestCase):
    def test_load_env_file_sets_values_without_overriding_existing_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "# comment",
                        "LESSONPACK_CONFIG=config.yaml",
                        "LESSONPACK_HTTP_API_KEY=from-file",
                        "QUOTED_VALUE=\"hello world\"",
                        "INLINE_COMMENT=value # comment",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"LESSONPACK_HTTP_API_KEY": "from-env"}, clear=True):
                loaded = load_env_file(env_path)

                self.assertEqual(os.environ["LESSONPACK_CONFIG"], "config.yaml")
                self.assertEqual(os.environ["LESSONPACK_HTTP_API_KEY"], "from-env")
                self.assertEqual(os.environ["QUOTED_VALUE"], "hello world")
                self.assertEqual(os.environ["INLINE_COMMENT"], "value")
                self.assertNotIn("LESSONPACK_HTTP_API_KEY", loaded)

    def test_create_llm_provider_from_env_loads_config_and_api_key_from_env_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = tmp_path / "config.yaml"
            env_path = tmp_path / ".env"
            config_path.write_text(
                "\n".join(
                    [
                        "chunk_size_chars: 800",
                        "chunk_overlap_chars: 120",
                        "retrieval_top_k: 5",
                        "llm:",
                        "  provider: http_chat",
                        "  model: test-model",
                        "  base_url: http://127.0.0.1:1/v1/chat/completions",
                        "  api_key_env: LESSONPACK_HTTP_API_KEY",
                        "  timeout_seconds: 3",
                        "vector_store:",
                        "  provider: memory",
                    ]
                ),
                encoding="utf-8",
            )
            env_path.write_text(
                f"LESSONPACK_CONFIG={config_path}\nLESSONPACK_HTTP_API_KEY=secret-from-env-file\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"LESSONPACK_ENV_FILE": str(env_path)}, clear=True):
                provider = create_llm_provider_from_env()

        self.assertIsInstance(provider, HTTPChatCompletionsProvider)
        self.assertEqual(provider.name, "http_chat:test-model")

    def test_readiness_loads_env_file_when_explicit_env_mapping_is_not_provided(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = tmp_path / "config.yaml"
            env_path = tmp_path / ".env"
            config_path.write_text(
                "\n".join(
                    [
                        "chunk_size_chars: 800",
                        "chunk_overlap_chars: 120",
                        "retrieval_top_k: 5",
                        "llm:",
                        "  provider: http_chat",
                        "  model: test-model",
                        "  base_url: http://127.0.0.1:1/v1/chat/completions",
                        "  api_key_env: LESSONPACK_HTTP_API_KEY",
                        "  timeout_seconds: 30",
                        "vector_store:",
                        "  provider: memory",
                    ]
                ),
                encoding="utf-8",
            )
            env_path.write_text(
                f"LESSONPACK_CONFIG={config_path}\nLESSONPACK_HTTP_API_KEY=secret-from-env-file\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"LESSONPACK_ENV_FILE": str(env_path)}, clear=True):
                report = check_llm_provider_readiness()

        self.assertTrue(report["ready"])
        self.assertTrue(report["real_provider_ready"])
        self.assertEqual(report["provider"], "http_chat")


if __name__ == "__main__":
    unittest.main()
