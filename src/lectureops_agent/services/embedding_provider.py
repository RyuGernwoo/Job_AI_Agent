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
        if not text.strip():
            raise ValueError("embedding text must not be empty")
        try:
            import litellm
        except ModuleNotFoundError as exc:
            raise RuntimeError("litellm is not installed; run pip install -r requirements.txt") from exc

        response = litellm.embedding(model=self.model, input=[text], dimensions=self.dimensions)
        vector = _extract_embedding(response)
        if len(vector) != self.dimensions:
            raise RuntimeError(
                f"embedding dimensions mismatch: expected {self.dimensions}, received {len(vector)}"
            )
        return vector


def create_embedding_provider(*, provider: str, model: str, dimensions: int) -> EmbeddingProvider:
    provider_name = provider.strip().casefold()
    if provider_name == "hash":
        return HashEmbeddingProvider(dimensions=dimensions, model=model)
    if provider_name == "litellm":
        return LiteLLMEmbeddingProvider(model=model, dimensions=dimensions)
    raise ValueError(f"unsupported embedding provider: {provider}")


def _extract_embedding(response: Any) -> list[float]:
    data = response.get("data") if isinstance(response, dict) else getattr(response, "data", None)
    if not isinstance(data, list) or not data:
        raise RuntimeError("embedding provider response missing data[0].embedding")
    first = data[0]
    vector = first.get("embedding") if isinstance(first, dict) else getattr(first, "embedding", None)
    if not isinstance(vector, list) or not vector:
        raise RuntimeError("embedding provider response missing data[0].embedding")
    try:
        return [float(value) for value in vector]
    except (TypeError, ValueError) as exc:
        raise RuntimeError("embedding provider returned a non-numeric vector") from exc
