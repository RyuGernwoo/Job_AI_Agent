from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from uuid import uuid4

from lectureops_agent.models.schemas import (
    CourseType,
    Project,
    RAGRetrieveResponse,
    RetrievedEvidence,
    RetrievalRun,
)
from lectureops_agent.services.rag_repository import RAGRepository
from lectureops_agent.services.vector_store import VectorStore


_WHITESPACE_PATTERN = re.compile(r"\s+")


def build_retrieval_query(*, project: Project, query: str) -> str:
    normalized = _normalize_query(query)
    ncs_text = " ".join(
        f"{unit.unit_code} {unit.unit_name} {' '.join(unit.elements)} "
        f"{' '.join(unit.target_criteria)}"
        for unit in project.ncs_units
    )
    fields = [
        normalized,
        f"과정 {project.course_title}",
        f"차시 {project.lesson_title}",
        f"학습목표 {' '.join(project.learning_objectives)}",
    ]
    if project.course_type == CourseType.NCS and ncs_text.strip():
        fields.append(f"NCS {ncs_text}")
    return _normalize_query(" ".join(fields))


def retrieve_evidence(
    *,
    project: Project,
    query: str,
    vector_store: VectorStore,
    repository: RAGRepository,
    top_k: int,
    candidate_k: int,
    baseline_project_id: str,
    include_baseline: bool,
) -> RetrievalRun:
    return retrieve_evidence_for_queries(
        project=project,
        queries=[query],
        vector_store=vector_store,
        repository=repository,
        top_k=top_k,
        candidate_k=candidate_k,
        baseline_project_id=baseline_project_id,
        include_baseline=include_baseline,
    )


def retrieve_evidence_for_queries(
    *,
    project: Project,
    queries: list[str],
    vector_store: VectorStore,
    repository: RAGRepository,
    top_k: int,
    candidate_k: int,
    baseline_project_id: str,
    include_baseline: bool,
) -> RetrievalRun:
    normalized_queries = _normalize_queries(queries)
    evidence_groups: list[list[RetrievedEvidence]] = []
    expanded_queries: list[str] = []
    for query in normalized_queries:
        expanded_query = build_retrieval_query(project=project, query=query)
        expanded_queries.append(expanded_query)
        results = vector_store.query_scoped(
            project_id=project.project_id,
            baseline_project_id=baseline_project_id,
            query=expanded_query,
            top_k=top_k,
            candidate_k=candidate_k,
            include_baseline=include_baseline,
        )
        results = _filter_results_for_course_type(project=project, results=results)
        evidence_groups.append(
            [
                RetrievedEvidence(
                    chunk=result.chunk.model_copy(
                        update={
                            "metadata": {
                                **result.chunk.metadata,
                                "matched_queries": [query],
                            }
                        }
                    ),
                    score=result.score,
                    vector_similarity=result.vector_similarity,
                    lexical_overlap=result.lexical_overlap,
                    scope=result.scope,
                    strategy=result.strategy,
                )
                for result in results
            ]
        )
    evidence = _merge_query_evidence(evidence_groups, top_k=top_k)
    run = RetrievalRun(
        run_id=str(uuid4()),
        trace_id=uuid4().hex,
        project_id=project.project_id,
        query=" | ".join(normalized_queries),
        normalized_query=" | ".join(expanded_queries),
        course_type=project.course_type,
        ncs_unit_codes=[unit.unit_code for unit in project.ncs_units],
        catalog_versions=list(
            dict.fromkeys(
                unit.catalog_version for unit in project.ncs_units if unit.catalog_version
            )
        ),
        evidence=evidence,
        created_at=datetime.now(timezone.utc),
    )
    repository.save_retrieval_run(run)
    return run


def retrieval_response(run: RetrievalRun) -> RAGRetrieveResponse:
    return RAGRetrieveResponse(
        retrieval_run_id=run.run_id,
        trace_id=run.trace_id,
        project_id=run.project_id,
        query=run.query,
        course_type=run.course_type,
        ncs_unit_codes=run.ncs_unit_codes,
        evidence=run.evidence,
        created_at=run.created_at,
    )


def _normalize_query(value: str) -> str:
    normalized = _WHITESPACE_PATTERN.sub(" ", value).strip()
    if not normalized:
        raise ValueError("query must include at least one term")
    return normalized


def _normalize_queries(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        query = _normalize_query(value)
        key = query.casefold()
        if key not in seen:
            normalized.append(query)
            seen.add(key)
    if not normalized:
        raise ValueError("queries must include at least one term")
    return normalized


def _merge_query_evidence(
    evidence_groups: list[list[RetrievedEvidence]],
    *,
    top_k: int,
) -> list[RetrievedEvidence]:
    selected: list[RetrievedEvidence] = []
    selected_indexes: dict[str, int] = {}
    content_indexes: dict[str, int] = {}
    max_group_size = max((len(group) for group in evidence_groups), default=0)

    for rank in range(max_group_size):
        for group in evidence_groups:
            if rank >= len(group):
                continue
            item = group[rank]
            content_key = hashlib.sha256(
                " ".join(item.chunk.text.split()).casefold().encode("utf-8")
            ).hexdigest()
            existing_index = selected_indexes.get(item.chunk.chunk_id)
            if existing_index is None:
                existing_index = content_indexes.get(content_key)
            if existing_index is not None:
                selected[existing_index] = _merge_evidence_metadata(selected[existing_index], item)
                continue
            if len(selected) >= top_k:
                continue
            selected_indexes[item.chunk.chunk_id] = len(selected)
            content_indexes[content_key] = len(selected)
            selected.append(item)
        if len(selected) >= top_k:
            break
    return selected


def _merge_evidence_metadata(
    current: RetrievedEvidence,
    candidate: RetrievedEvidence,
) -> RetrievedEvidence:
    current_queries = current.chunk.metadata.get("matched_queries", [])
    candidate_queries = candidate.chunk.metadata.get("matched_queries", [])
    merged_queries = list(dict.fromkeys([*current_queries, *candidate_queries]))
    best = candidate if candidate.score > current.score else current
    return best.model_copy(
        update={
            "chunk": best.chunk.model_copy(
                update={
                    "metadata": {
                        **best.chunk.metadata,
                        "matched_queries": merged_queries,
                    }
                }
            )
        }
    )


def _filter_results_for_course_type(*, project: Project, results: list) -> list:
    if project.course_type == CourseType.GENERAL:
        return [
            result
            for result in results
            if result.scope != "baseline" or not _is_ncs_chunk(result.chunk.metadata)
        ]
    selected_unit_codes = {unit.unit_code.casefold() for unit in project.ncs_units}
    return [
        result
        for result in results
        if result.scope != "baseline"
        or not result.chunk.metadata.get("ncs_unit_code")
        or str(result.chunk.metadata["ncs_unit_code"]).casefold() in selected_unit_codes
    ]


def _is_ncs_chunk(metadata: dict) -> bool:
    if metadata.get("ncs_unit_code") or metadata.get("ncs_hierarchy"):
        return True
    tags = metadata.get("tags", [])
    if isinstance(tags, list) and any(str(tag).casefold() == "ncs" for tag in tags):
        return True
    return str(metadata.get("dataset_version", "")).casefold().startswith("ncs-")
