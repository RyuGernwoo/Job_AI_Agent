from __future__ import annotations

import math
import os
import re
import warnings
from pathlib import Path
from typing import Any, Protocol

from lectureops_agent.models.schemas import MaterialChunk
from lectureops_agent.services.retrieval_service import retrieve_chunks

_VECTOR_DIMENSIONS = 64
_TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣_]+")
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


class ChromaVectorStore:
    def __init__(self, *, persist_path: str, collection_name: str) -> None:
        if not persist_path:
            raise ValueError("persist_path is required for ChromaVectorStore")
        if not collection_name:
            raise ValueError("collection_name is required for ChromaVectorStore")

        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r".*asyncio\.iscoroutinefunction.*",
                category=DeprecationWarning,
            )
            try:
                import chromadb
            except ModuleNotFoundError as exc:
                raise RuntimeError("chromadb is not installed; run pip install -r requirements.txt") from exc

            self._client = chromadb.PersistentClient(path=str(Path(persist_path)))
            self._collection = self._client.get_or_create_collection(collection_name)

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            close()

    def upsert(self, *, project_id: str, chunks: list[MaterialChunk]) -> None:
        if not chunks:
            return
        self._collection.upsert(
            ids=[chunk.chunk_id for chunk in chunks],
            documents=[chunk.text for chunk in chunks],
            embeddings=[_embed_text(chunk.text) for chunk in chunks],
            metadatas=[_to_chroma_metadata(project_id, chunk) for chunk in chunks],
        )

    def query(self, *, project_id: str, query: str, top_k: int) -> list[MaterialChunk]:
        result = self._collection.query(
            query_embeddings=[_embed_text(query)],
            n_results=top_k,
            where={"project_id": project_id},
            include=["documents", "metadatas", "distances"],
        )
        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        chunks: list[MaterialChunk] = []
        for chunk_id, document, metadata in zip(ids, documents, metadatas, strict=False):
            metadata = dict(metadata)
            chunks.append(
                MaterialChunk(
                    chunk_id=chunk_id,
                    project_id=project_id,
                    document_id=str(metadata.get("document_id", "unknown")),
                    source_name=str(metadata.get("source_name", "unknown")),
                    source_type=str(metadata.get("source_type", "txt")),
                    page=_parse_optional_page(metadata.get("page")),
                    text=document,
                    metadata=_from_chroma_metadata(metadata),
                )
            )
        return chunks


def create_vector_store_from_env() -> VectorStore:
    store_type = os.getenv("LECTUREOPS_VECTOR_STORE", "memory").strip().casefold()
    if store_type in {"", "memory", "inmemory", "in-memory"}:
        return InMemoryVectorStore()
    if store_type == "chroma":
        persist_path = _get_required_env("LECTUREOPS_CHROMA_PATH")
        collection_name = _get_required_env("LECTUREOPS_CHROMA_COLLECTION")
        return ChromaVectorStore(persist_path=persist_path, collection_name=collection_name)
    raise ValueError(f"unsupported vector store: {store_type}")


def _get_required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise ValueError(f"{name} is required when LECTUREOPS_VECTOR_STORE=chroma")
    return value


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


def _to_chroma_metadata(project_id: str, chunk: MaterialChunk) -> dict[str, str | int | float | bool]:
    metadata: dict[str, str | int | float | bool] = {
        "project_id": project_id,
        "document_id": chunk.document_id,
        "source_name": chunk.source_name,
        "source_type": chunk.source_type,
    }
    if chunk.page is not None:
        metadata["page"] = chunk.page
    for key, value in chunk.metadata.items():
        if key in _INTERNAL_METADATA_KEYS:
            continue
        if isinstance(value, str | int | float | bool):
            metadata[key] = value
        elif value is not None:
            metadata[key] = str(value)
    return metadata


def _from_chroma_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metadata.items() if key not in _INTERNAL_METADATA_KEYS}


def _parse_optional_page(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)
