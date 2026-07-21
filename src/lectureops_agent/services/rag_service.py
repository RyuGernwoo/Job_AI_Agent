from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import uuid4

from lectureops_agent.models.schemas import (
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
        f"{unit.unit_code} {unit.unit_name} {' '.join(unit.elements)}" for unit in project.ncs_units
    )
    fields = [
        normalized,
        f"과정 {project.course_title}",
        f"차시 {project.lesson_title}",
        f"학습목표 {' '.join(project.learning_objectives)}",
    ]
    if ncs_text.strip():
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
    normalized_query = build_retrieval_query(project=project, query=query)
    results = vector_store.query_scoped(
        project_id=project.project_id,
        baseline_project_id=baseline_project_id,
        query=normalized_query,
        top_k=top_k,
        candidate_k=candidate_k,
        include_baseline=include_baseline,
    )
    evidence = [
        RetrievedEvidence(
            chunk=result.chunk,
            score=result.score,
            vector_similarity=result.vector_similarity,
            lexical_overlap=result.lexical_overlap,
            scope=result.scope,
        )
        for result in results
    ]
    run = RetrievalRun(
        run_id=str(uuid4()),
        trace_id=uuid4().hex,
        project_id=project.project_id,
        query=_normalize_query(query),
        normalized_query=normalized_query,
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
        evidence=run.evidence,
        created_at=run.created_at,
    )


def _normalize_query(value: str) -> str:
    normalized = _WHITESPACE_PATTERN.sub(" ", value).strip()
    if not normalized:
        raise ValueError("query must include at least one term")
    return normalized
