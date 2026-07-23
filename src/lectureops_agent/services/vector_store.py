from __future__ import annotations

import hashlib
import logging
import math
import os
import time
from dataclasses import dataclass, replace
from typing import Any, Protocol

from lectureops_agent.config import VectorStoreConfig
from lectureops_agent.env import load_env_file
from lectureops_agent.models.schemas import MaterialChunk
from lectureops_agent.services.embedding_provider import (
    EmbeddingProvider,
    HashEmbeddingProvider,
    create_embedding_provider,
)
from lectureops_agent.services.retrieval_service import expanded_query_terms, retrieve_chunks

_INTERNAL_METADATA_KEYS = {"project_id", "document_id", "source_name", "source_type", "page"}
_BASELINE_MIN_COMBINED_SCORE = 0.20
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VectorSearchResult:
    chunk: MaterialChunk
    vector_similarity: float
    lexical_overlap: float
    score: float
    scope: str = "project"
    strategy: str = "hybrid"


class VectorStore(Protocol):
    def upsert(self, *, project_id: str, chunks: list[MaterialChunk]) -> None:
        ...

    def query(self, *, project_id: str, query: str, top_k: int) -> list[MaterialChunk]:
        ...

    def list_chunks(self, *, project_id: str, limit: int) -> list[MaterialChunk]:
        ...

    def query_scoped(
        self,
        *,
        project_id: str,
        baseline_project_id: str,
        query: str,
        top_k: int,
        candidate_k: int,
        include_baseline: bool,
    ) -> list[VectorSearchResult]:
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

    def list_chunks(self, *, project_id: str, limit: int) -> list[MaterialChunk]:
        if limit <= 0:
            raise ValueError("limit must be greater than 0")
        chunks = self._chunks_by_project.get(project_id, {}).values()
        return sorted(chunks, key=lambda chunk: chunk.chunk_id)[:limit]

    def query_with_scores(self, *, project_id: str, query: str, top_k: int) -> list[VectorSearchResult]:
        chunks = self.query(project_id=project_id, query=query, top_k=top_k)
        return [
            VectorSearchResult(
                chunk=chunk,
                vector_similarity=_lexical_overlap(query, chunk),
                lexical_overlap=_lexical_overlap(query, chunk),
                score=_lexical_overlap(query, chunk),
            )
            for chunk in chunks
        ]

    def query_scoped(
        self,
        *,
        project_id: str,
        baseline_project_id: str,
        query: str,
        top_k: int,
        candidate_k: int,
        include_baseline: bool,
    ) -> list[VectorSearchResult]:
        return _query_scoped(
            store=self,
            project_id=project_id,
            baseline_project_id=baseline_project_id,
            query=query,
            top_k=top_k,
            candidate_k=candidate_k,
            include_baseline=include_baseline,
        )


class SupabaseVectorStore:
    def __init__(
        self,
        *,
        url: str,
        key: str,
        table_name: str = "lessonpack_chunks",
        match_function: str = "match_lessonpack_chunks",
        match_threshold: float = 0.0,
        baseline_project_id: str = "mvp-dataset",
        embedding_provider: EmbeddingProvider | None = None,
        embedding_column: str = "embedding",
        embedding_version: str = "v1",
        upsert_timeout_retries: int = 2,
        upsert_timeout_retry_delay_seconds: float = 0.5,
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
        if not embedding_column.strip():
            raise ValueError("Supabase embedding_column is required")
        if not embedding_version.strip():
            raise ValueError("Supabase embedding_version is required")
        if upsert_timeout_retries < 0:
            raise ValueError("upsert_timeout_retries must be greater than or equal to 0")
        if upsert_timeout_retry_delay_seconds < 0:
            raise ValueError(
                "upsert_timeout_retry_delay_seconds must be greater than or equal to 0"
            )
        self.table_name = table_name
        self.match_function = match_function
        self.match_threshold = match_threshold
        self.baseline_project_id = baseline_project_id
        self.embedding_provider = embedding_provider or HashEmbeddingProvider()
        self.embedding_column = embedding_column
        self.embedding_version = embedding_version
        self.upsert_timeout_retries = upsert_timeout_retries
        self.upsert_timeout_retry_delay_seconds = upsert_timeout_retry_delay_seconds
        if self.embedding_column == "embedding_v2" and self.embedding_provider.dimensions != 1536:
            raise ValueError("embedding_v2 requires a 1536-dimensional embedding provider")
        if self.embedding_version == "v2" and self.embedding_column != "embedding_v2":
            raise ValueError("embedding version v2 requires the embedding_v2 column")
        if client is None:
            try:
                from supabase import create_client
            except ModuleNotFoundError as exc:
                raise RuntimeError("supabase is not installed; run pip install -r requirements.txt") from exc
            client = create_client(url, key)
        self._client = client

    @property
    def client(self) -> Any:
        return self._client

    def upsert(self, *, project_id: str, chunks: list[MaterialChunk]) -> None:
        if not chunks:
            return
        embeddings = _embed_many(self.embedding_provider, [chunk.text for chunk in chunks])
        rows = [
            _chunk_to_supabase_row(
                project_id=project_id,
                chunk=chunk,
                embedding=embedding,
                embedding_column=self.embedding_column,
                embedding_model=self.embedding_provider.name,
                embedding_version=self.embedding_version,
                scope="baseline" if project_id == self.baseline_project_id else "project",
            )
            for chunk, embedding in zip(chunks, embeddings, strict=True)
        ]
        self._upsert_rows_with_timeout_recovery(rows)

    def _upsert_rows_with_timeout_recovery(self, rows: list[dict[str, Any]]) -> None:
        """Retry a timed-out write, then split the batch to preserve sync progress."""
        last_timeout: Exception | None = None
        for attempt in range(self.upsert_timeout_retries + 1):
            try:
                response = (
                    self._client.table(self.table_name)
                    .upsert(rows, on_conflict="chunk_id")
                    .execute()
                )
                _raise_for_supabase_error(response)
                return
            except Exception as exc:
                if not _is_statement_timeout(exc):
                    raise
                last_timeout = exc
                if attempt >= self.upsert_timeout_retries:
                    break
                delay = self.upsert_timeout_retry_delay_seconds * (2**attempt)
                logger.warning(
                    "Supabase chunk upsert timed out for %d rows; retrying in %.2fs (%d/%d)",
                    len(rows),
                    delay,
                    attempt + 1,
                    self.upsert_timeout_retries,
                )
                if delay:
                    time.sleep(delay)

        if len(rows) == 1:
            raise RuntimeError(
                "Supabase chunk upsert timed out for one row after retries; "
                "check database load and statement timeout settings"
            ) from last_timeout

        midpoint = len(rows) // 2
        logger.warning(
            "Supabase chunk upsert timed out for %d rows after retries; splitting into %d and %d rows",
            len(rows),
            midpoint,
            len(rows) - midpoint,
        )
        self._upsert_rows_with_timeout_recovery(rows[:midpoint])
        self._upsert_rows_with_timeout_recovery(rows[midpoint:])

    def query(self, *, project_id: str, query: str, top_k: int) -> list[MaterialChunk]:
        return [result.chunk for result in self.query_with_scores(project_id=project_id, query=query, top_k=top_k)]

    def list_chunks(self, *, project_id: str, limit: int) -> list[MaterialChunk]:
        if limit <= 0:
            raise ValueError("limit must be greater than 0")
        columns = "chunk_id,project_id,document_id,source_name,source_type,page,content,metadata"
        response = (
            self._client.table(self.table_name)
            .select(columns)
            .eq("project_id", project_id)
            .limit(limit)
            .execute()
        )
        _raise_for_supabase_error(response)
        return [_supabase_row_to_chunk(row) for row in _response_data(response)]

    def query_with_scores(self, *, project_id: str, query: str, top_k: int) -> list[VectorSearchResult]:
        params = {
            "query_embedding": self.embedding_provider.embed(text=query),
            "match_project_id": project_id,
            "match_count": top_k,
            "match_threshold": self.match_threshold,
        }
        response = self._client.rpc(self.match_function, params).execute()
        _raise_for_supabase_error(response)
        rows = _response_data(response)
        if not rows:
            rows = self._exact_project_fallback(
                project_id=project_id,
                query_embedding=params["query_embedding"],
                top_k=top_k,
            )
        results: list[VectorSearchResult] = []
        for row in rows:
            chunk = _supabase_row_to_chunk(row)
            similarity = _bounded(float(row.get("similarity", 0.0)), minimum=-1.0, maximum=1.0)
            lexical = _lexical_overlap(query, chunk)
            results.append(
                VectorSearchResult(
                    chunk=chunk,
                    vector_similarity=similarity,
                    lexical_overlap=lexical,
                    score=_combined_score(similarity, lexical, project_scope=False),
                )
            )
        return results

    def _exact_project_fallback(
        self,
        *,
        project_id: str,
        query_embedding: list[float],
        top_k: int,
    ) -> list[dict[str, Any]]:
        columns = (
            "chunk_id,project_id,document_id,source_name,source_type,page,content,metadata,"
            f"{self.embedding_column}"
        )
        response = (
            self._client.table(self.table_name)
            .select(columns)
            .eq("project_id", project_id)
            .limit(1000)
            .execute()
        )
        _raise_for_supabase_error(response)
        scored_rows: list[dict[str, Any]] = []
        for row in _response_data(response):
            embedding = _parse_embedding(row.get(self.embedding_column))
            if not embedding or len(embedding) != len(query_embedding):
                continue
            similarity = _cosine_similarity(query_embedding, embedding)
            if similarity < self.match_threshold:
                continue
            scored_rows.append({**row, "similarity": similarity})
        scored_rows.sort(key=lambda item: float(item["similarity"]), reverse=True)
        return scored_rows[:top_k]

    def query_scoped(
        self,
        *,
        project_id: str,
        baseline_project_id: str,
        query: str,
        top_k: int,
        candidate_k: int,
        include_baseline: bool,
    ) -> list[VectorSearchResult]:
        return _query_scoped(
            store=self,
            project_id=project_id,
            baseline_project_id=baseline_project_id,
            query=query,
            top_k=top_k,
            candidate_k=candidate_k,
            include_baseline=include_baseline,
        )


def create_vector_store_from_config(config: VectorStoreConfig) -> VectorStore:
    store_type = config.provider.casefold()
    if store_type in {"memory", "inmemory", "in-memory"}:
        return InMemoryVectorStore()
    if store_type == "supabase":
        embedding_provider = create_embedding_provider(
            provider=config.embedding_provider,
            model=config.embedding_model,
            dimensions=config.embedding_dimensions,
        )
        return SupabaseVectorStore(
            url=_get_required_env("SUPABASE_URL"),
            key=_get_required_env("SUPABASE_SERVICE_ROLE_KEY"),
            table_name=config.table_name,
            match_function=config.match_function,
            match_threshold=config.match_threshold,
            baseline_project_id=config.baseline_project_id,
            embedding_provider=embedding_provider,
            embedding_column=config.embedding_column,
            embedding_version=config.embedding_version,
        )
    raise ValueError(f"unsupported vector store: {config.provider}")


def create_vector_store_from_env() -> VectorStore:
    load_env_file()
    store_type = os.getenv("LECTUREOPS_VECTOR_STORE", "memory").strip().casefold()
    if store_type in {"", "memory", "inmemory", "in-memory"}:
        return InMemoryVectorStore()
    if store_type == "supabase":
        embedding_column = os.getenv("LESSONPACK_SUPABASE_EMBEDDING_COLUMN", "embedding")
        embedding_version = resolve_embedding_version(
            embedding_column=embedding_column,
            configured_version=os.getenv("LESSONPACK_EMBEDDING_VERSION"),
        )
        embedding_provider = create_embedding_provider(
            provider=os.getenv("LESSONPACK_EMBEDDING_PROVIDER", "hash"),
            model=os.getenv("LESSONPACK_EMBEDDING_MODEL", "lessonpack-hash-v1"),
            dimensions=_optional_int_env("LESSONPACK_EMBEDDING_DIMENSIONS", default=64),
        )
        return SupabaseVectorStore(
            url=_get_required_env("SUPABASE_URL"),
            key=_get_required_env("SUPABASE_SERVICE_ROLE_KEY"),
            table_name=os.getenv("LESSONPACK_SUPABASE_TABLE", "lessonpack_chunks"),
            match_function=os.getenv("LESSONPACK_SUPABASE_MATCH_FUNCTION", "match_lessonpack_chunks"),
            match_threshold=_optional_float_env("LESSONPACK_SUPABASE_MATCH_THRESHOLD", default=0.0),
            baseline_project_id=os.getenv("LESSONPACK_BASELINE_PROJECT_ID", "mvp-dataset"),
            embedding_provider=embedding_provider,
            embedding_column=embedding_column,
            embedding_version=embedding_version,
            upsert_timeout_retries=_optional_int_env(
                "LESSONPACK_SUPABASE_UPSERT_TIMEOUT_RETRIES",
                default=2,
            ),
            upsert_timeout_retry_delay_seconds=_optional_float_env(
                "LESSONPACK_SUPABASE_UPSERT_TIMEOUT_RETRY_DELAY_SECONDS",
                default=0.5,
            ),
        )
    raise ValueError(f"unsupported vector store: {store_type}")


def resolve_embedding_version(*, embedding_column: str, configured_version: str | None = None) -> str:
    value = (configured_version or "").strip()
    if value:
        return value
    return "v2" if embedding_column == "embedding_v2" else "v1"


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


def _optional_int_env(name: str, *, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return int(value)


def _chunk_to_supabase_row(
    *,
    project_id: str,
    chunk: MaterialChunk,
    embedding: list[float],
    embedding_column: str,
    embedding_model: str,
    embedding_version: str,
    scope: str,
) -> dict[str, Any]:
    row = {
        "chunk_id": chunk.chunk_id,
        "project_id": project_id,
        "document_id": chunk.document_id,
        "source_name": chunk.source_name,
        "source_type": chunk.source_type,
        "page": chunk.page,
        "content": chunk.text,
        "metadata": _external_metadata(chunk.metadata),
        "scope": scope,
        "embedding_model": embedding_model,
        "embedding_version": embedding_version,
        "content_hash": hashlib.sha256(chunk.text.encode("utf-8")).hexdigest(),
    }
    row[embedding_column] = embedding
    return row


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


def _is_statement_timeout(exc: Exception) -> bool:
    if str(getattr(exc, "code", "")) == "57014":
        return True
    for detail in exc.args:
        if isinstance(detail, dict) and str(detail.get("code", "")) == "57014":
            return True
    message = str(exc).casefold()
    return "statement timeout" in message or "canceling statement due to statement timeout" in message


def _parse_optional_page(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _query_scoped(
    *,
    store: Any,
    project_id: str,
    baseline_project_id: str,
    query: str,
    top_k: int,
    candidate_k: int,
    include_baseline: bool,
) -> list[VectorSearchResult]:
    if top_k <= 0:
        raise ValueError("top_k must be greater than 0")
    if candidate_k < top_k:
        candidate_k = top_k

    project_candidates: list[VectorSearchResult] = []
    project_query_error: Exception | None = None
    try:
        project_results = store.query_with_scores(project_id=project_id, query=query, top_k=candidate_k)
    except Exception as exc:
        project_results = []
        project_query_error = exc
        logger.warning(
            "Project semantic retrieval failed (%s); trying uploaded-material fallback",
            type(exc).__name__,
        )

    for result in project_results:
        project_candidates.append(
            _with_retrieval_metadata(
                replace(
                    result,
                    scope="project",
                    score=_combined_score(result.vector_similarity, result.lexical_overlap, project_scope=True),
                ),
                scope="project",
                strategy=result.strategy,
            )
        )

    if not project_candidates:
        fallback_scan_limit = min(max(candidate_k * 20, candidate_k), 1000)
        try:
            project_chunks = store.list_chunks(project_id=project_id, limit=fallback_scan_limit)
        except Exception:
            if project_query_error is not None:
                raise project_query_error
            raise
        project_candidates = [
            _with_retrieval_metadata(
                VectorSearchResult(
                    chunk=chunk,
                    vector_similarity=0.0,
                    lexical_overlap=0.0,
                    score=0.05,
                    scope="project",
                    strategy="project_material_fallback",
                ),
                scope="project",
                strategy="project_material_fallback",
            )
            for chunk in _representative_chunks(project_chunks, limit=candidate_k)
        ]
        if project_candidates:
            logger.info(
                "Using %d uploaded project chunks as retrieval fallback for project %s",
                len(project_candidates),
                project_id,
            )
        elif project_query_error is not None:
            raise project_query_error

    baseline_candidates: list[VectorSearchResult] = []
    uses_project_material_fallback = bool(project_candidates) and all(
        result.strategy == "project_material_fallback" for result in project_candidates
    )
    if (
        include_baseline
        and not uses_project_material_fallback
        and baseline_project_id
        and baseline_project_id != project_id
    ):
        try:
            baseline_results = store.query_with_scores(
                project_id=baseline_project_id,
                query=query,
                top_k=candidate_k,
            )
        except Exception as exc:
            if not project_candidates:
                raise
            baseline_results = []
            logger.warning(
                "Baseline retrieval failed (%s); continuing with project evidence",
                type(exc).__name__,
            )
        for result in baseline_results:
            scored_result = replace(
                result,
                scope="baseline",
                score=_combined_score(
                    result.vector_similarity,
                    result.lexical_overlap,
                    project_scope=False,
                ),
            )
            if scored_result.score < _BASELINE_MIN_COMBINED_SCORE:
                continue
            baseline_candidates.append(
                _with_retrieval_metadata(
                    scored_result,
                    scope="baseline",
                    strategy=result.strategy,
                )
            )

    # Project uploads are the primary source. Baseline evidence only fills the
    # remaining slots, so an unrelated common dataset cannot displace a user's
    # material for a newly introduced NCS field.
    return _deduplicate_and_rank(
        project_candidates=project_candidates,
        baseline_candidates=baseline_candidates,
        top_k=top_k,
    )


def _with_retrieval_metadata(
    result: VectorSearchResult,
    *,
    scope: str,
    strategy: str,
) -> VectorSearchResult:
    metadata = dict(result.chunk.metadata)
    metadata.setdefault(
        "evidence_origin",
        "project_material" if scope == "project" else "baseline_dataset",
    )
    metadata.setdefault(
        "evidence_authority",
        "user_provided" if scope == "project" else "curated_baseline",
    )
    metadata["retrieval_scope"] = scope
    metadata["retrieval_strategy"] = strategy
    return replace(
        result,
        chunk=result.chunk.model_copy(update={"metadata": metadata}),
        scope=scope,
        strategy=strategy,
    )


def _representative_chunks(chunks: list[MaterialChunk], *, limit: int) -> list[MaterialChunk]:
    """Select a stable, document-diverse fallback set without vector scores."""
    by_document: dict[str, list[MaterialChunk]] = {}
    for chunk in sorted(chunks, key=lambda item: (item.document_id, item.chunk_id)):
        by_document.setdefault(chunk.document_id, []).append(chunk)

    selected: list[MaterialChunk] = []
    document_ids = sorted(by_document)
    while document_ids and len(selected) < limit:
        remaining: list[str] = []
        for document_id in document_ids:
            document_chunks = by_document[document_id]
            if document_chunks and len(selected) < limit:
                selected.append(document_chunks.pop(0))
            if document_chunks:
                remaining.append(document_id)
        document_ids = remaining
    return selected


def _deduplicate_and_rank(
    *,
    project_candidates: list[VectorSearchResult],
    baseline_candidates: list[VectorSearchResult],
    top_k: int,
) -> list[VectorSearchResult]:
    selected: list[VectorSearchResult] = []
    seen_chunk_ids: set[str] = set()
    seen_content: set[str] = set()
    for candidates in (project_candidates, baseline_candidates):
        ranked = sorted(
            candidates,
            key=lambda item: (
                item.score,
                item.vector_similarity,
                item.lexical_overlap,
                item.chunk.chunk_id,
            ),
            reverse=True,
        )
        for result in ranked:
            content_key = hashlib.sha256(
                " ".join(result.chunk.text.split()).casefold().encode("utf-8")
            ).hexdigest()
            if result.chunk.chunk_id in seen_chunk_ids or content_key in seen_content:
                continue
            selected.append(result)
            seen_chunk_ids.add(result.chunk.chunk_id)
            seen_content.add(content_key)
            if len(selected) >= top_k:
                return selected
    return selected


def _combined_score(vector_similarity: float, lexical_overlap: float, *, project_scope: bool) -> float:
    score = 0.55 * max(0.0, vector_similarity) + 0.40 * lexical_overlap
    if project_scope:
        score += 0.05
    return _bounded(score, minimum=0.0, maximum=1.0)


def _lexical_overlap(query: str, chunk: MaterialChunk) -> float:
    query_terms = set(expanded_query_terms(query))
    if not query_terms:
        raise ValueError("query must include at least one term")
    metadata_text = " ".join(str(value) for value in chunk.metadata.values())
    chunk_text = f"{chunk.chunk_id} {chunk.document_id} {chunk.source_name} {chunk.text} {metadata_text}".casefold()
    matched_terms = sum(1 for term in query_terms if term in chunk_text)
    return matched_terms / len(query_terms)


def _bounded(value: float, *, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _parse_embedding(value: Any) -> list[float]:
    if isinstance(value, list):
        return [float(item) for item in value]
    if isinstance(value, str):
        stripped = value.strip().removeprefix("[").removesuffix("]")
        if not stripped:
            return []
        return [float(item) for item in stripped.split(",")]
    return []


def _embed_many(provider: EmbeddingProvider, texts: list[str]) -> list[list[float]]:
    embed_many = getattr(provider, "embed_many", None)
    if callable(embed_many):
        vectors = embed_many(texts=texts)
    else:
        vectors = [provider.embed(text=text) for text in texts]
    if len(vectors) != len(texts):
        raise RuntimeError(f"embedding count mismatch: expected {len(texts)}, received {len(vectors)}")
    return vectors


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)
