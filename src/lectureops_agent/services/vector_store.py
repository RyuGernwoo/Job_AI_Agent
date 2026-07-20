from __future__ import annotations

import math
import os
import re
from typing import Any, Protocol

from lectureops_agent.config import VectorStoreConfig
from lectureops_agent.env import load_env_file
from lectureops_agent.models.schemas import MaterialChunk
from lectureops_agent.services.retrieval_service import retrieve_chunks

_VECTOR_DIMENSIONS = 64
_TOKEN_PATTERN = re.compile(r"[0-9A-Za-z\uac00-\ud7a3_]+")
_INTERNAL_METADATA_KEYS = {"project_id", "document_id", "source_name", "source_type", "page"}


class VectorStore(Protocol):
    def upsert(self, *, project_id: str, chunks: list[MaterialChunk]) -> None:
        ...

    def query(self, *, project_id: str, query: str, top_k: int) -> list[MaterialChunk]:
        ...


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._chunks_by_project: dict[str, dict[str, MaterialChunk]] = {}

    def upsert(self, *, project_id: str, chunks: list[MaterialChunk]) -> None:
        project_chunks = self._chunks_by_project.setdefault(project_id, {})
        for chunk in chunks:
            project_chunks[chunk.chunk_id] = chunk

    def query(self, *, project_id: str, query: str, top_k: int) -> list[MaterialChunk]:
        project_chunks = list(self._chunks_by_project.get(project_id, {}).values())
        return retrieve_chunks(query=query, chunks=project_chunks, top_k=top_k)


class SupabaseVectorStore:
    def __init__(
        self,
        *,
        url: str,
        key: str,
        table_name: str = "lessonpack_chunks",
        match_function: str = "match_lessonpack_chunks",
        match_threshold: float = 0.0,
        client: Any | None = None,
    ) -> None:
        if not url.strip():
            raise ValueError("Supabase URL is required")
        if not key.strip():
            raise ValueError("Supabase key is required")
        if not table_name.strip():
            raise ValueError("Supabase table_name is required")
        if not match_function.strip():
            raise ValueError("Supabase match_function is required")
        self.table_name = table_name
        self.match_function = match_function
        self.match_threshold = match_threshold
        if client is None:
            try:
                from supabase import create_client
            except ModuleNotFoundError as exc:
                raise RuntimeError("supabase is not installed; run pip install -r requirements.txt") from exc
            client = create_client(url, key)
        self._client = client

    def upsert(self, *, project_id: str, chunks: list[MaterialChunk]) -> None:
        if not chunks:
            return
        rows = [_chunk_to_supabase_row(project_id=project_id, chunk=chunk) for chunk in chunks]
        response = self._client.table(self.table_name).upsert(rows, on_conflict="chunk_id").execute()
        _raise_for_supabase_error(response)

    def query(self, *, project_id: str, query: str, top_k: int) -> list[MaterialChunk]:
        params = {
            "query_embedding": _embed_text(query),
            "match_project_id": project_id,
            "match_count": top_k,
            "match_threshold": self.match_threshold,
        }
        response = self._client.rpc(self.match_function, params).execute()
        _raise_for_supabase_error(response)
        return [_supabase_row_to_chunk(row) for row in _response_data(response)]


def create_vector_store_from_config(config: VectorStoreConfig) -> VectorStore:
    store_type = config.provider.casefold()
    if store_type in {"memory", "inmemory", "in-memory"}:
        return InMemoryVectorStore()
    if store_type == "supabase":
        return SupabaseVectorStore(
            url=_get_required_env("SUPABASE_URL"),
            key=_get_required_env("SUPABASE_SERVICE_ROLE_KEY"),
            table_name=config.table_name,
            match_function=config.match_function,
            match_threshold=config.match_threshold,
        )
    raise ValueError(f"unsupported vector store: {config.provider}")


def create_vector_store_from_env() -> VectorStore:
    load_env_file()
    store_type = os.getenv("LECTUREOPS_VECTOR_STORE", "memory").strip().casefold()
    if store_type in {"", "memory", "inmemory", "in-memory"}:
        return InMemoryVectorStore()
    if store_type == "supabase":
        return SupabaseVectorStore(
            url=_get_required_env("SUPABASE_URL"),
            key=_get_required_env("SUPABASE_SERVICE_ROLE_KEY"),
            table_name=os.getenv("LESSONPACK_SUPABASE_TABLE", "lessonpack_chunks"),
            match_function=os.getenv("LESSONPACK_SUPABASE_MATCH_FUNCTION", "match_lessonpack_chunks"),
            match_threshold=_optional_float_env("LESSONPACK_SUPABASE_MATCH_THRESHOLD", default=0.0),
        )
    raise ValueError(f"unsupported vector store: {store_type}")


def _get_required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise ValueError(f"{name} is required when LECTUREOPS_VECTOR_STORE=supabase")
    return value


def _optional_float_env(name: str, *, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return float(value)


def _embed_text(text: str) -> list[float]:
    vector = [0.0] * _VECTOR_DIMENSIONS
    for token in _tokenize(text):
        index = sum(ord(char) for char in token) % _VECTOR_DIMENSIONS
        vector[index] += 1.0
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def _tokenize(text: str) -> list[str]:
    return _TOKEN_PATTERN.findall(text.casefold())


def _chunk_to_supabase_row(*, project_id: str, chunk: MaterialChunk) -> dict[str, Any]:
    return {
        "chunk_id": chunk.chunk_id,
        "project_id": project_id,
        "document_id": chunk.document_id,
        "source_name": chunk.source_name,
        "source_type": chunk.source_type,
        "page": chunk.page,
        "content": chunk.text,
        "metadata": _external_metadata(chunk.metadata),
        "embedding": _embed_text(chunk.text),
    }


def _supabase_row_to_chunk(row: dict[str, Any]) -> MaterialChunk:
    return MaterialChunk(
        chunk_id=str(row["chunk_id"]),
        project_id=str(row["project_id"]),
        document_id=str(row.get("document_id", "unknown")),
        source_name=str(row.get("source_name", "unknown")),
        source_type=str(row.get("source_type", "txt")),
        page=_parse_optional_page(row.get("page")),
        text=str(row.get("content") or row.get("text") or ""),
        metadata=_external_metadata(row.get("metadata") or {}),
    )


def _external_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metadata.items() if key not in _INTERNAL_METADATA_KEYS}


def _response_data(response: Any) -> list[dict[str, Any]]:
    data = getattr(response, "data", None)
    if data is None and isinstance(response, dict):
        data = response.get("data")
    if data is None:
        return []
    if not isinstance(data, list):
        raise RuntimeError("Supabase response data must be a list")
    return data


def _raise_for_supabase_error(response: Any) -> None:
    error = getattr(response, "error", None)
    if error is None and isinstance(response, dict):
        error = response.get("error")
    if error:
        raise RuntimeError(f"Supabase vector store request failed: {error}")


def _parse_optional_page(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)
