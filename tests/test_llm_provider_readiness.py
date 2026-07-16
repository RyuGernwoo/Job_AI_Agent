import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lectureops_agent.services.llm_provider_readiness import check_llm_provider_readiness


class LLMProviderReadinessTests(unittest.TestCase):
    def test_mock_provider_is_ready_but_not_real_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "chunk_size_chars: 800",
                        "chunk_overlap_chars: 120",
                        "retrieval_top_k: 5",
                        "llm:",
                        "  provider: mock",
                        "  model: lessonpack-mock",
                        "vector_store:",
                        "  provider: memory",
                    ]
                ),
                encoding="utf-8",
            )

            report = check_llm_provider_readiness(config_path=config_path, env={})

        self.assertTrue(report["ready"])
        self.assertFalse(report["real_provider_ready"])
        self.assertEqual(report["provider"], "mock")
        self.assertEqual(report["missing"], [])

    def test_http_chat_reports_missing_api_key_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "chunk_size_chars: 800",
                        "chunk_overlap_chars: 120",
                        "retrieval_top_k: 5",
                        "llm:",
                        "  provider: http_chat",
                        "  model: test-model",
                        "  base_url: https://api.example.test/v1/chat/completions",
                        "  api_key_env: LESSONPACK_TEST_API_KEY",
                        "  timeout_seconds: 30",
                        "vector_store:",
                        "  provider: memory",
                    ]
                ),
                encoding="utf-8",
            )

            report = check_llm_provider_readiness(config_path=config_path, env={})

        self.assertFalse(report["ready"])
        self.assertFalse(report["real_provider_ready"])
        self.assertEqual(report["provider"], "http_chat")
        self.assertIn("LESSONPACK_TEST_API_KEY", report["missing"])

    def test_uses_lessonpack_config_env_when_config_path_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "chunk_size_chars: 800",
                        "chunk_overlap_chars: 120",
                        "retrieval_top_k: 5",
                        "llm:",
                        "  provider: http_chat",
                        "  model: test-model",
                        "  base_url: https://api.example.test/v1/chat/completions",
                        "  api_key_env: LESSONPACK_TEST_API_KEY",
                        "  timeout_seconds: 30",
                        "vector_store:",
                        "  provider: memory",
                    ]
                ),
                encoding="utf-8",
            )
            env = {
                "LESSONPACK_CONFIG": str(config_path),
                "LESSONPACK_TEST_API_KEY": "secret",
            }

            with patch.dict(os.environ, env, clear=True):
                report = check_llm_provider_readiness()

        self.assertTrue(report["ready"])
        self.assertTrue(report["real_provider_ready"])
        self.assertEqual(report["model"], "test-model")


if __name__ == "__main__":
    unittest.main()
