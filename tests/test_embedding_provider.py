import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lectureops_agent.services.embedding_provider import (
    HashEmbeddingProvider,
    LiteLLMEmbeddingProvider,
)


class EmbeddingProviderTests(unittest.TestCase):
    def test_hash_embedding_is_deterministic_and_normalized(self):
        provider = HashEmbeddingProvider(dimensions=64)

        first = provider.embed(text="Python function return output")
        second = provider.embed(text="Python function return output")

        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)
        self.assertAlmostEqual(sum(value * value for value in first), 1.0)

    def test_hash_embedding_supports_batches(self):
        provider = HashEmbeddingProvider(dimensions=64)

        vectors = provider.embed_many(texts=["first text", "second text"])

        self.assertEqual(len(vectors), 2)
        self.assertTrue(all(len(vector) == 64 for vector in vectors))

    def test_litellm_embedding_validates_dimensions(self):
        fake_litellm = SimpleNamespace(
            embedding=lambda **kwargs: {"data": [{"embedding": [0.1, 0.2, 0.3]}]}
        )
        provider = LiteLLMEmbeddingProvider(model="text-embedding-test", dimensions=3)

        with patch.dict(sys.modules, {"litellm": fake_litellm}):
            vector = provider.embed(text="Python function")

        self.assertEqual(vector, [0.1, 0.2, 0.3])

    def test_litellm_embedding_rejects_wrong_dimensions(self):
        fake_litellm = SimpleNamespace(
            embedding=lambda **kwargs: {"data": [{"embedding": [0.1, 0.2]}]}
        )
        provider = LiteLLMEmbeddingProvider(model="text-embedding-test", dimensions=3)

        with patch.dict(sys.modules, {"litellm": fake_litellm}):
            with self.assertRaisesRegex(RuntimeError, "dimensions mismatch"):
                provider.embed(text="Python function")

    def test_litellm_embedding_sends_one_batch_and_orders_by_index(self):
        calls = []

        def fake_embedding(**kwargs):
            calls.append(kwargs)
            return {
                "data": [
                    {"index": 1, "embedding": [0.4, 0.5, 0.6]},
                    {"index": 0, "embedding": [0.1, 0.2, 0.3]},
                ]
            }

        provider = LiteLLMEmbeddingProvider(model="text-embedding-test", dimensions=3)

        with patch.dict(sys.modules, {"litellm": SimpleNamespace(embedding=fake_embedding)}):
            vectors = provider.embed_many(texts=["first", "second"])

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["input"], ["first", "second"])
        self.assertEqual(vectors, [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])


if __name__ == "__main__":
    unittest.main()
