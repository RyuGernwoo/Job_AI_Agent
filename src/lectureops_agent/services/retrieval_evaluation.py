from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
    chunks: list[MaterialChunk],
    gold_rows: list[dict[str, Any]],
    top_k: int,
) -> dict[str, Any]:
    if top_k <= 0:
        raise ValueError("top_k must be greater than 0")

    cases: list[dict[str, Any]] = []
    hit_count = 0
    empty_result_count = 0
    reciprocal_rank_sum = 0.0
    context_precision_sum = 0.0
    context_recall_sum = 0.0

    for row in gold_rows:
        expected_ids = [str(chunk_id) for chunk_id in row.get("expected_chunk_ids", [])]
        retrieved = retrieve_chunks(query=str(row["query"]), chunks=chunks, top_k=top_k)
        retrieved_ids = [chunk.chunk_id for chunk in retrieved]
        first_rank = _first_relevant_rank(retrieved_ids, expected_ids)
        context_precision = _context_precision(retrieved_ids, expected_ids)
        context_recall = _context_recall(retrieved_ids, expected_ids)
        hit = first_rank is not None

        if hit:
            hit_count += 1
            reciprocal_rank_sum += 1 / first_rank
        if not retrieved_ids:
            empty_result_count += 1
        context_precision_sum += context_precision
        context_recall_sum += context_recall

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
                "required_concepts": row.get("required_concepts", []),
            }
        )

    total_queries = len(gold_rows)
    return {
        "total_queries": total_queries,
        "top_k": top_k,
        "hit_count": hit_count,
        "hit_rate": round(hit_count / total_queries, 4) if total_queries else 0.0,
        "empty_result_count": empty_result_count,
        "mean_reciprocal_rank": round(reciprocal_rank_sum / total_queries, 4) if total_queries else 0.0,
        "average_context_precision": round(context_precision_sum / total_queries, 4) if total_queries else 0.0,
        "average_context_recall": round(context_recall_sum / total_queries, 4) if total_queries else 0.0,
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
