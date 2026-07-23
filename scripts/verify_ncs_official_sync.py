"""Verify official NCS API synchronization state in Supabase and optional RAG retrieval."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lectureops_agent.env import load_env_file
from lectureops_agent.services.vector_store import (
    SupabaseVectorStore,
    create_vector_store_from_env,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify official NCS API sync tables and baseline RAG chunks."
    )
    parser.add_argument(
        "--mode",
        choices=("catalog", "detail"),
        default="detail",
    )
    parser.add_argument("--min-source-records", type=int, default=1)
    parser.add_argument("--min-modules", type=int, default=0)
    parser.add_argument(
        "--max-stale-days",
        type=int,
        default=_env_int("LESSONPACK_NCS_SYNC_STALE_DAYS", 7),
    )
    parser.add_argument("--query", help="Optional live baseline RAG smoke query.")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args(argv)
    if (
        args.min_source_records < 0
        or args.min_modules < 0
        or args.max_stale_days <= 0
    ):
        parser.error(
            "minimum counts must not be negative and --max-stale-days must be positive"
        )
    if args.top_k <= 0:
        parser.error("--top-k must be greater than 0")

    load_env_file()
    client = _create_supabase_client()
    source_count = _count(client, "lessonpack_ncs_source_records")
    catalog_count = _count(client, "lessonpack_ncs_catalog")
    module_count = _count(client, "lessonpack_ncs_modules")
    successful_runs = _rows(
        client.table("lessonpack_ncs_sync_runs")
        .select(
            "run_id,mode,status,request_count,received_count,changed_count,"
            "chunk_upsert_count,started_at,finished_at"
        )
        .in_("status", ["completed", "partial"])
        .eq("mode", args.mode)
        .order("started_at", desc=True)
        .limit(1)
        .execute()
    )
    chunk_count = _count(
        client,
        os.getenv("LESSONPACK_SUPABASE_TABLE", "lessonpack_chunks"),
        json_filter={"metadata": {"dataset": "ncs_official_api"}},
    )
    latest_run = successful_runs[0] if successful_runs else None
    run_age_days = _run_age_days(latest_run)
    checks = {
        "catalog": catalog_count > 0,
        "modules": module_count >= args.min_modules,
        "successful_run": latest_run is not None,
        "fresh_run": (
            run_age_days is not None
            and run_age_days <= args.max_stale_days
        ),
    }
    if args.mode == "detail":
        checks["source_records"] = source_count >= args.min_source_records
        checks["rag_chunks"] = chunk_count > 0
    report: dict[str, Any] = {
        "ready": False,
        "counts": {
            "source_records": source_count,
            "catalog": catalog_count,
            "modules": module_count,
            "rag_chunks": chunk_count,
        },
        "latest_successful_run": latest_run,
        "latest_run_age_days": (
            round(run_age_days, 3) if run_age_days is not None else None
        ),
        "checks": checks,
    }
    if args.query:
        store = create_vector_store_from_env()
        if not isinstance(store, SupabaseVectorStore):
            raise RuntimeError("LECTUREOPS_VECTOR_STORE must be supabase for live retrieval")
        project_id = os.getenv("LESSONPACK_NCS_SYNC_PROJECT_ID", "mvp-dataset")
        started = time.perf_counter()
        chunks = store.query(project_id=project_id, query=args.query, top_k=args.top_k)
        elapsed = time.perf_counter() - started
        official_hits = [
            chunk
            for chunk in chunks
            if chunk.metadata.get("dataset") == "ncs_official_api"
        ]
        checks["sample_retrieval"] = bool(official_hits)
        report["sample_retrieval"] = {
            "query": args.query,
            "latency_seconds": round(elapsed, 3),
            "result_count": len(chunks),
            "official_hit_count": len(official_hits),
            "results": [
                {
                    "chunk_id": chunk.chunk_id,
                    "source_name": chunk.source_name,
                    "unit_code": chunk.metadata.get("ncs_unit_code"),
                    "chunk_type": chunk.metadata.get("chunk_type"),
                }
                for chunk in chunks
            ],
        }
    report["ready"] = all(checks.values())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ready"] else 1


def _create_supabase_client() -> Any:
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
    try:
        from supabase import create_client
    except ModuleNotFoundError as exc:
        raise RuntimeError("supabase is not installed") from exc
    return create_client(url, key)


def _count(
    client: Any,
    table: str,
    *,
    json_filter: dict[str, Any] | None = None,
) -> int:
    query = client.table(table).select("*", count="exact").limit(1)
    if json_filter:
        for column, value in json_filter.items():
            query = query.contains(column, value)
    response = query.execute()
    _raise_for_error(response)
    return int(getattr(response, "count", None) or 0)


def _rows(response: Any) -> list[dict[str, Any]]:
    _raise_for_error(response)
    data = getattr(response, "data", None)
    return data if isinstance(data, list) else []


def _raise_for_error(response: Any) -> None:
    error = getattr(response, "error", None)
    if error:
        raise RuntimeError(f"Supabase verification request failed: {error}")


def _run_age_days(run: dict[str, Any] | None) -> float | None:
    if not run:
        return None
    raw_timestamp = run.get("finished_at") or run.get("started_at")
    if not raw_timestamp:
        return None
    try:
        timestamp = datetime.fromisoformat(
            str(raw_timestamp).replace("Z", "+00:00")
        )
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return max(
        0.0,
        (datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds()
        / 86400,
    )


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    return int(value) if value else default


if __name__ == "__main__":
    sys.exit(main())
