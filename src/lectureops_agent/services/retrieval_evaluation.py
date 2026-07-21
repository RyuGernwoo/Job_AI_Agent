from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable

from lectureops_agent.models.schemas import MaterialChunk
from lectureops_agent.services.retrieval_service import retrieve_chunks


def load_retrieval_gold(path: Path | str) -> list[dict[str, Any]]:
    gold_path = Path(path)
    rows: list[dict[str, Any]] = []
    with gold_path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{gold_path.name} line {line_number} must be a JSON object")
            rows.append(row)
    return rows


def evaluate_retrieval_gold(
    *,
    chunks: list[MaterialChunk] | None,
    gold_rows: list[dict[str, Any]],
    top_k: int,
    retrieve_fn: Callable[[str, int], list[MaterialChunk]] | None = None,
) -> dict[str, Any]:
    if top_k <= 0:
        raise ValueError("top_k must be greater than 0")

    cases: list[dict[str, Any]] = []
    hit_count = 0
    empty_result_count = 0
    reciprocal_rank_sum = 0.0
    context_precision_sum = 0.0
    context_recall_sum = 0.0
    ndcg_sum = 0.0
    concept_coverage_sum = 0.0
    duplicate_ratio_sum = 0.0

    for row in gold_rows:
        expected_ids = [str(chunk_id) for chunk_id in row.get("expected_chunk_ids", [])]
        query = str(row["query"])
        if retrieve_fn is not None:
            retrieved = retrieve_fn(query, top_k)
        else:
            retrieved = retrieve_chunks(query=query, chunks=chunks or [], top_k=top_k)
        retrieved_ids = [chunk.chunk_id for chunk in retrieved]
        first_rank = _first_relevant_rank(retrieved_ids, expected_ids)
        context_precision = _context_precision(retrieved_ids, expected_ids)
        context_recall = _context_recall(retrieved_ids, expected_ids)
        ndcg = _ndcg_at_k(retrieved_ids, expected_ids, top_k)
        concept_coverage = _required_concept_coverage(retrieved, row.get("required_concepts", []))
        duplicate_ratio = _duplicate_ratio(retrieved)
        hit = first_rank is not None

        if hit:
            hit_count += 1
            reciprocal_rank_sum += 1 / first_rank
        if not retrieved_ids:
            empty_result_count += 1
        context_precision_sum += context_precision
        context_recall_sum += context_recall
        ndcg_sum += ndcg
        concept_coverage_sum += concept_coverage["coverage"]
        duplicate_ratio_sum += duplicate_ratio

        cases.append(
            {
                "query_id": row.get("query_id"),
                "query": row.get("query"),
                "expected_chunk_ids": expected_ids,
                "retrieved_chunk_ids": retrieved_ids,
                "hit": hit,
                "first_relevant_rank": first_rank,
                "context_precision": context_precision,
                "context_recall": context_recall,
                "ndcg_at_k": ndcg,
                "required_concepts": concept_coverage,
                "duplicate_ratio": duplicate_ratio,
            }
        )

    total_queries = len(gold_rows)
    return {
        "total_queries": total_queries,
        "top_k": top_k,
        "hit_count": hit_count,
        "hit_rate": round(hit_count / total_queries, 4) if total_queries else 0.0,
        "empty_result_count": empty_result_count,
        "empty_result_rate": round(empty_result_count / total_queries, 4) if total_queries else 0.0,
        "mean_reciprocal_rank": round(reciprocal_rank_sum / total_queries, 4) if total_queries else 0.0,
        "average_context_precision": round(context_precision_sum / total_queries, 4) if total_queries else 0.0,
        "average_context_recall": round(context_recall_sum / total_queries, 4) if total_queries else 0.0,
        "average_ndcg_at_k": round(ndcg_sum / total_queries, 4) if total_queries else 0.0,
        "average_required_concept_coverage": (
            round(concept_coverage_sum / total_queries, 4) if total_queries else 0.0
        ),
        "average_duplicate_ratio": round(duplicate_ratio_sum / total_queries, 4) if total_queries else 0.0,
        "cases": cases,
    }


def _first_relevant_rank(retrieved_ids: list[str], expected_ids: list[str]) -> int | None:
    expected = set(expected_ids)
    for index, chunk_id in enumerate(retrieved_ids, start=1):
        if chunk_id in expected:
            return index
    return None


def _context_precision(retrieved_ids: list[str], expected_ids: list[str]) -> float:
    if not retrieved_ids:
        return 0.0
    expected = set(expected_ids)
    relevant_count = sum(1 for chunk_id in retrieved_ids if chunk_id in expected)
    return round(relevant_count / len(retrieved_ids), 4)


def _context_recall(retrieved_ids: list[str], expected_ids: list[str]) -> float:
    if not expected_ids:
        return 0.0
    retrieved = set(retrieved_ids)
    expected = set(expected_ids)
    return round(len(retrieved & expected) / len(expected), 4)


def _ndcg_at_k(retrieved_ids: list[str], expected_ids: list[str], top_k: int) -> float:
    expected = set(expected_ids)
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, chunk_id in enumerate(retrieved_ids[:top_k], start=1)
        if chunk_id in expected
    )
    ideal_count = min(len(expected), top_k)
    if ideal_count == 0:
        return 0.0
    ideal_dcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
    return round(dcg / ideal_dcg, 4)


def _required_concept_coverage(
    retrieved: list[MaterialChunk],
    required_concepts: list[str],
) -> dict[str, Any]:
    concepts = [str(concept).strip() for concept in required_concepts if str(concept).strip()]
    searchable = " ".join(_chunk_search_text(chunk) for chunk in retrieved).casefold()
    matched = [concept for concept in concepts if concept.casefold() in searchable]
    missing = [concept for concept in concepts if concept not in matched]
    return {
        "expected": concepts,
        "matched": matched,
        "missing": missing,
        "coverage": round(len(matched) / len(concepts), 4) if concepts else 1.0,
    }


def _chunk_search_text(chunk: MaterialChunk) -> str:
    metadata = chunk.metadata or {}
    tags = metadata.get("tags", [])
    if not isinstance(tags, list):
        tags = [str(tags)]
    return " ".join(
        [
            chunk.text,
            chunk.source_name,
            str(metadata.get("section", "")),
            " ".join(str(tag) for tag in tags),
        ]
    )


def _duplicate_ratio(retrieved: list[MaterialChunk]) -> float:
    if not retrieved:
        return 0.0
    content_keys = {" ".join(chunk.text.split()).casefold() for chunk in retrieved}
    return round(1.0 - (len(content_keys) / len(retrieved)), 4)
