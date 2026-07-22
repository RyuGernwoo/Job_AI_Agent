"""Verify NCS expansion row counts and live Supabase RAG retrieval."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lectureops_agent.env import load_env_file
from lectureops_agent.services.vector_store import SupabaseVectorStore, create_vector_store_from_env


DEFAULT_MANIFEST = ROOT / "data" / "processed" / "ncs_expansion" / "dataset_manifest.json"
VERIFICATION_QUERIES = [
    {
        "category": "사업관리",
        "query": "공적개발원조사업 개발전략수립 협력대상국",
    },
    {
        "category": "경영_회계_사무",
        "query": "인터뷰 정성조사 FGI 조사 설계",
    },
    {
        "category": "금융_보험",
        "query": "보험상품 개발 위험률 보험료 산출",
    },
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the uploaded NCS expansion RAG dataset.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--project-id", default="mvp-dataset")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args(argv)
    if args.top_k <= 0:
        parser.error("--top-k must be greater than 0")

    load_env_file()
    store = create_vector_store_from_env()
    if not isinstance(store, SupabaseVectorStore):
        raise RuntimeError("LECTUREOPS_VECTOR_STORE must be supabase for live verification")

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    expected = manifest["counts"]
    remote_counts = {
        "pdf": count_prefix(store, project_id=args.project_id, pattern="ncs-pdf-%"),
        "xls": count_prefix(store, project_id=args.project_id, pattern="ncs-xls-%"),
    }
    remote_counts["total"] = remote_counts["pdf"] + remote_counts["xls"]

    retrieval_checks: list[dict[str, Any]] = []
    for case in VERIFICATION_QUERIES:
        started = time.perf_counter()
        chunks = store.query(
            project_id=args.project_id,
            query=case["query"],
            top_k=args.top_k,
        )
        elapsed = time.perf_counter() - started
        results = [
            {
                "chunk_id": chunk.chunk_id,
                "source_name": chunk.source_name,
                "page": chunk.page,
                "section": chunk.metadata.get("section"),
                "top_category": chunk.metadata.get("top_category"),
            }
            for chunk in chunks
        ]
        retrieval_checks.append(
            {
                **case,
                "latency_seconds": round(elapsed, 3),
                "result_count": len(results),
                "category_hit": any(
                    result["top_category"] == case["category"]
                    and result["chunk_id"].startswith(("ncs-pdf-", "ncs-xls-"))
                    for result in results
                ),
                "results": results,
            }
        )

    counts_match = (
        remote_counts["pdf"] == expected["chunks_by_source_kind"]["pdf"]
        and remote_counts["xls"] == expected["chunks_by_source_kind"]["xls"]
        and remote_counts["total"] == expected["chunks"]
    )
    ready = counts_match and all(check["category_hit"] for check in retrieval_checks)
    report = {
        "ready": ready,
        "project_id": args.project_id,
        "vector_store": type(store).__name__,
        "embedding_provider": store.embedding_provider.name,
        "embedding_dimensions": store.embedding_provider.dimensions,
        "embedding_column": store.embedding_column,
        "embedding_version": store.embedding_version,
        "expected_counts": {
            "pdf": expected["chunks_by_source_kind"]["pdf"],
            "xls": expected["chunks_by_source_kind"]["xls"],
            "total": expected["chunks"],
        },
        "remote_counts": remote_counts,
        "counts_match": counts_match,
        "retrieval_checks": retrieval_checks,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ready else 1


def count_prefix(store: SupabaseVectorStore, *, project_id: str, pattern: str) -> int:
    response = (
        store.client.table(store.table_name)
        .select("chunk_id", count="exact")
        .eq("project_id", project_id)
        .like("chunk_id", pattern)
        .limit(1)
        .execute()
    )
    return int(response.count or 0)


if __name__ == "__main__":
    sys.exit(main())
