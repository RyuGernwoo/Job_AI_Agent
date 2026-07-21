"""Check LessonPack AI RAG runtime configuration and optional live retrieval."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lectureops_agent.env import load_env_file
from lectureops_agent.services.vector_store import SupabaseVectorStore, create_vector_store_from_env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check LessonPack AI RAG readiness.")
    parser.add_argument("--project-id", default="mvp-dataset", help="Project scope for live retrieval.")
    parser.add_argument("--query", help="Run a live retrieval query when supplied.")
    parser.add_argument("--top-k", type=int, default=3, help="Number of live results.")
    parser.add_argument(
        "--allow-memory",
        action="store_true",
        help="Treat the in-memory provider as ready for local development.",
    )
    parser.add_argument(
        "--check-schema",
        action="store_true",
        help="Check the four Supabase RAG persistence tables with read-only requests.",
    )
    args = parser.parse_args(argv)
    load_env_file()

    report: dict = {
        "ready": False,
        "provider": os.getenv("LECTUREOPS_VECTOR_STORE", "memory"),
        "table": os.getenv("LESSONPACK_SUPABASE_TABLE", "lessonpack_chunks"),
        "match_function": os.getenv(
            "LESSONPACK_SUPABASE_MATCH_FUNCTION",
            "match_lessonpack_chunks",
        ),
        "baseline_project_id": os.getenv("LESSONPACK_BASELINE_PROJECT_ID", "mvp-dataset"),
        "embedding_provider": os.getenv("LESSONPACK_EMBEDDING_PROVIDER", "hash"),
        "embedding_model": os.getenv("LESSONPACK_EMBEDDING_MODEL", "lessonpack-hash-v1"),
        "embedding_dimensions": int(os.getenv("LESSONPACK_EMBEDDING_DIMENSIONS", "64")),
        "embedding_column": os.getenv("LESSONPACK_SUPABASE_EMBEDDING_COLUMN", "embedding"),
        "credentials": {
            "supabase_url_set": bool(os.getenv("SUPABASE_URL", "").strip()),
            "service_role_key_set": bool(os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()),
        },
        "errors": [],
    }

    try:
        store = create_vector_store_from_env()
        report["runtime_store"] = type(store).__name__
        report["ready"] = isinstance(store, SupabaseVectorStore) or args.allow_memory
        if args.check_schema:
            if isinstance(store, SupabaseVectorStore):
                schema = _check_persistence_schema(store)
                report["persistence_schema"] = schema
                report["ready"] = report["ready"] and schema["ready"]
            else:
                report["persistence_schema"] = {"ready": args.allow_memory, "tables": {}}
        if args.query:
            chunks = store.query(
                project_id=args.project_id,
                query=args.query,
                top_k=args.top_k,
            )
            report["live_query"] = {
                "project_id": args.project_id,
                "query": args.query,
                "result_count": len(chunks),
                "chunk_ids": [chunk.chunk_id for chunk in chunks],
            }
            report["ready"] = report["ready"] and bool(chunks)
    except Exception as exc:  # CLI boundary: report SDK/network failures without a traceback.
        report["errors"].append(str(exc))
        report["ready"] = False

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ready"] else 1


def _check_persistence_schema(store: SupabaseVectorStore) -> dict:
    tables = {
        "lessonpack_projects": "project_id",
        "lessonpack_documents": "document_id",
        "lessonpack_retrieval_runs": "run_id",
        "lessonpack_generation_runs": "package_id",
    }
    result: dict = {"ready": True, "tables": {}}
    for table_name, id_column in tables.items():
        try:
            response = store.client.table(table_name).select(id_column, count="exact").limit(1).execute()
            result["tables"][table_name] = {
                "exists": True,
                "count": getattr(response, "count", None),
            }
        except Exception as exc:  # CLI boundary: table absence is reported as readiness data.
            result["tables"][table_name] = {
                "exists": False,
                "error_type": type(exc).__name__,
            }
            result["ready"] = False
    return result


if __name__ == "__main__":
    sys.exit(main())
