"""Build and optionally upload the structured LessonPack NCS catalog."""

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
from lectureops_agent.services.ncs_catalog_dataset import (
    build_ncs_catalog,
    catalog_row,
    criterion_rows,
    load_official_ncs_catalog,
    merge_ncs_catalogs,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare the structured LessonPack NCS catalog.")
    parser.add_argument(
        "--markdown-root",
        type=Path,
        default=ROOT / "data" / "raw" / "ncs_expansion" / "converted_md" / "xls",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "processed" / "ncs_catalog.jsonl",
    )
    parser.add_argument(
        "--official-csv",
        type=Path,
        help=(
            "HRDKorea official NCS CSV containing 분류번호, 명칭, 수준, 훈련시간. "
            "Units absent from local RAG data are retained with zero criteria."
        ),
    )
    parser.add_argument("--upload", action="store_true", help="Upsert catalog rows into Supabase.")
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args(argv)
    if args.batch_size <= 0:
        parser.error("--batch-size must be greater than 0")

    detailed_units = (
        build_ncs_catalog(args.markdown_root.resolve())
        if args.markdown_root.exists()
        else []
    )
    official_units = (
        load_official_ncs_catalog(args.official_csv.resolve())
        if args.official_csv is not None
        else []
    )
    units = merge_ncs_catalogs(
        official_units=official_units,
        detailed_units=detailed_units,
    )
    if not units:
        raise RuntimeError(
            "No NCS catalog units found. Provide --official-csv or a valid --markdown-root."
        )
    rows = [catalog_row(unit) for unit in units]
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )

    criteria = criterion_rows(units)
    if args.upload:
        _upload_catalog(rows=rows, criteria=criteria, batch_size=args.batch_size)

    result = {
        "markdown_root": str(args.markdown_root.resolve()),
        "official_csv": (
            str(args.official_csv.resolve()) if args.official_csv is not None else None
        ),
        "output": str(output),
        "unit_count": len(units),
        "official_unit_count": len(official_units),
        "criterion_count": len(criteria),
        "rag_available_unit_count": sum(bool(unit.criteria) for unit in units),
        "units_without_criteria": sum(not unit.criteria for unit in units),
        "uploaded": args.upload,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _upload_catalog(*, rows: list[dict[str, Any]], criteria: list[dict[str, Any]], batch_size: int) -> None:
    load_env_file()
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not supabase_url or not service_role_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for --upload")
    from supabase import create_client

    client = create_client(supabase_url, service_role_key)
    for batch in _batches(rows, batch_size):
        client.table("lessonpack_ncs_catalog").upsert(batch, on_conflict="unit_code").execute()
    for batch in _batches(criteria, batch_size):
        client.table("lessonpack_ncs_criteria").upsert(
            batch,
            on_conflict="criterion_code",
        ).execute()


def _batches(rows: list[dict[str, Any]], size: int):
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


if __name__ == "__main__":
    sys.exit(main())
