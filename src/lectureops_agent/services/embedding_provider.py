from __future__ import annotations

import math
import re
from typing import Any, Protocol


_TOKEN_PATTERN = re.compile(r"[0-9A-Za-z\uac00-\ud7a3_]+")


class EmbeddingProvider(Protocol):
    name: str
    dimensions: int

    def embed(self, *, text: str) -> list[float]:
        ...

    def embed_many(self, *, texts: list[str]) -> list[list[float]]:
        ...


class HashEmbeddingProvider:
    def __init__(self, *, dimensions: int = 64, model: str = "lessonpack-hash-v1") -> None:
        if dimensions <= 0:
            raise ValueError("embedding dimensions must be greater than 0")
        self.dimensions = dimensions
        self.model = model
        self.name = f"hash:{model}"

    def embed(self, *, text: str) -> list[float]:
        if not text.strip():
            raise ValueError("embedding text must not be empty")
        vector = [0.0] * self.dimensions
        for token in _TOKEN_PATTERN.findall(text.casefold()):
            index = sum(ord(char) for char in token) % self.dimensions
            vector[index] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

    def embed_many(self, *, texts: list[str]) -> list[list[float]]:
        return [self.embed(text=text) for text in texts]


class LiteLLMEmbeddingProvider:
    def __init__(self, *, model: str, dimensions: int) -> None:
        if not model.strip():
            raise ValueError("embedding model is required")
        if dimensions <= 0:
            raise ValueError("embedding dimensions must be greater than 0")
        self.model = model
        self.dimensions = dimensions
        self.name = f"litellm:{model}"

    def embed(self, *, text: str) -> list[float]:
        return self.embed_many(texts=[text])[0]

    def embed_many(self, *, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if any(not text.strip() for text in texts):
            raise ValueError("embedding text must not be empty")
        try:
            import litellm
        except ModuleNotFoundError as exc:
            raise RuntimeError("litellm is not installed; run pip install -r requirements.txt") from exc

        response = litellm.embedding(model=self.model, input=texts, dimensions=self.dimensions)
        vectors = _extract_embeddings(response)
        if len(vectors) != len(texts):
            raise RuntimeError(
                f"embedding count mismatch: expected {len(texts)}, received {len(vectors)}"
            )
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise RuntimeError(
                    f"embedding dimensions mismatch: expected {self.dimensions}, received {len(vector)}"
                )
        return vectors


def create_embedding_provider(*, provider: str, model: str, dimensions: int) -> EmbeddingProvider:
    provider_name = provider.strip().casefold()
    if provider_name == "hash":
        return HashEmbeddingProvider(dimensions=dimensions, model=model)
    if provider_name == "litellm":
        return LiteLLMEmbeddingProvider(model=model, dimensions=dimensions)
    raise ValueError(f"unsupported embedding provider: {provider}")


def _extract_embedding(response: Any) -> list[float]:
    return _extract_embeddings(response)[0]


def _extract_embeddings(response: Any) -> list[list[float]]:
    data = response.get("data") if isinstance(response, dict) else getattr(response, "data", None)
    if not isinstance(data, list) or not data:
        raise RuntimeError("embedding provider response missing data[0].embedding")
    indexed: list[tuple[int, Any]] = []
    for fallback_index, item in enumerate(data):
        index_value = item.get("index") if isinstance(item, dict) else getattr(item, "index", None)
        index = fallback_index if index_value is None else int(index_value)
        indexed.append((index, item))
    indexed.sort(key=lambda pair: pair[0])

    vectors: list[list[float]] = []
    for _, item in indexed:
        vector = item.get("embedding") if isinstance(item, dict) else getattr(item, "embedding", None)
        if not isinstance(vector, list) or not vector:
            raise RuntimeError("embedding provider response missing data[0].embedding")
        try:
            vectors.append([float(value) for value in vector])
        except (TypeError, ValueError) as exc:
            raise RuntimeError("embedding provider returned a non-numeric vector") from exc
    return vectors
