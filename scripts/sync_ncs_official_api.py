"""Synchronize official HRDKorea NCS API records into Supabase and baseline RAG."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lectureops_agent.env import load_env_file
from lectureops_agent.services.ncs_official_api import NCSOfficialAPIClient
from lectureops_agent.services.ncs_sync_service import (
    InMemoryNCSOfficialSyncStore,
    NCSOfficialSyncOptions,
    NCSOfficialSyncService,
    SupabaseNCSOfficialSyncStore,
)
from lectureops_agent.services.vector_store import (
    SupabaseVectorStore,
    create_vector_store_from_env,
)


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    parser = argparse.ArgumentParser(
        description="Synchronize official HRDKorea NCS API data into LessonPack AI."
    )
    parser.add_argument(
        "--mode",
        choices=("catalog", "detail", "modules", "all"),
        default="all",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=_env_int("LESSONPACK_NCS_SYNC_PAGE_SIZE", 100),
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        default=_env_int("LESSONPACK_NCS_SYNC_MAX_REQUESTS", 5000),
    )
    parser.add_argument("--limit", type=int, help="Maximum records for a smoke run.")
    parser.add_argument("--unit-code", help="Restrict detail operations to one NCS code.")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--embed", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--embedding-batch-size", type=int, default=32)
    args = parser.parse_args(argv)

    if not _env_bool("LESSONPACK_NCS_API_ENABLED", False):
        raise RuntimeError(
            "Set LESSONPACK_NCS_API_ENABLED=true before calling the official NCS API"
        )
    service_key = os.getenv("DATA_GO_KR_SERVICE_KEY", "").strip()
    if not service_key:
        raise RuntimeError("DATA_GO_KR_SERVICE_KEY is required")

    api_client = NCSOfficialAPIClient(
        service_key=service_key,
        base_url=os.getenv(
            "LESSONPACK_NCS_API_BASE_URL",
            "https://apis.data.go.kr/B490007/ncsInfo",
        ),
        module_url=os.getenv(
            "LESSONPACK_NCS_MODULE_API_URL",
            "https://apis.data.go.kr/B490007/ncsStudyModule/openapi21",
        ),
        reference_base_url=os.getenv(
            "LESSONPACK_NCS_REFERENCE_API_BASE_URL",
            "https://apis.data.go.kr/B490007/hrdkapi",
        ),
        requests_per_second=_env_float(
            "LESSONPACK_NCS_SYNC_REQUESTS_PER_SECOND",
            2.0,
        ),
    )
    supabase_configured = bool(
        os.getenv("SUPABASE_URL", "").strip()
        and os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    )
    if not args.dry_run and not supabase_configured:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required outside dry-run"
        )
    if supabase_configured:
        supabase_client = _create_supabase_client()
        store: Any = SupabaseNCSOfficialSyncStore(client=supabase_client)
    else:
        store = InMemoryNCSOfficialSyncStore()

    vector_store = None
    if args.embed and not args.dry_run:
        vector_store = create_vector_store_from_env()
        if not isinstance(vector_store, SupabaseVectorStore):
            raise RuntimeError(
                "LECTUREOPS_VECTOR_STORE=supabase is required when --embed is enabled"
            )

    service = NCSOfficialSyncService(
        api_client=api_client,
        store=store,
        vector_store=vector_store,
        project_id=os.getenv("LESSONPACK_NCS_SYNC_PROJECT_ID", "mvp-dataset"),
    )
    report = service.sync(
        NCSOfficialSyncOptions(
            mode=args.mode,
            page_size=args.page_size,
            max_requests=args.max_requests,
            record_limit=args.limit,
            unit_code=args.unit_code,
            resume=args.resume,
            embed=args.embed,
            dry_run=args.dry_run,
            embedding_batch_size=args.embedding_batch_size,
        )
    )
    print(json.dumps(report.model_dump(), ensure_ascii=False, indent=2))
    return 0 if report.status in {"completed", "partial"} else 1


def _create_supabase_client() -> Any:
    try:
        from supabase import create_client
    except ModuleNotFoundError as exc:
        raise RuntimeError("supabase is not installed") from exc
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    return int(value) if value else default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    return float(value) if value else default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name, "").strip().casefold()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    sys.exit(main())
