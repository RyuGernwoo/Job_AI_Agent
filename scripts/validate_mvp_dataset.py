"""Validate the local LessonPack AI MVP dataset artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "data"


def validate_dataset(data_dir: Path | str = DEFAULT_DATA_DIR) -> dict[str, Any]:
    data_dir = Path(data_dir)
    processed = data_dir / "processed"
    gold = data_dir / "gold"
    errors: list[str] = []
    warnings: list[str] = []

    chunks = read_jsonl(processed / "chunks.jsonl", errors)
    chunk_ids = validate_chunks(chunks, errors, warnings)

    chunk_index_rows = read_csv_rows(processed / "chunk_index.csv", errors)
    validate_chunk_index(chunk_index_rows, chunk_ids, errors)

    selected_sources = read_yaml(processed / "selected_sources.yaml", errors)
    source_ids = validate_selected_sources(selected_sources, errors)

    source_file_map_rows = read_csv_rows(processed / "source_file_map.csv", errors)
    if not source_file_map_rows:
        errors.append("source_file_map.csv must contain at least one row.")

    manifest = read_json(processed / "dataset_manifest.json", errors)

    retrieval_gold = read_jsonl(gold / "retrieval_gold.jsonl", errors)
    validate_retrieval_gold(retrieval_gold, chunk_ids, errors)

    generation_gold = read_yaml(gold / "generation_gold.yaml", errors)
    generation_cases = validate_generation_gold(generation_gold, source_ids, errors)

    rubric = read_yaml(gold / "human_eval_rubric.yaml", errors)
    validate_human_eval_rubric(rubric, errors)

    counts = {
        "chunks": len(chunks),
        "chunk_index_rows": len(chunk_index_rows),
        "selected_sources": len(source_ids),
        "source_file_map_rows": len(source_file_map_rows),
        "retrieval_gold": len(retrieval_gold),
        "generation_gold": len(generation_cases),
    }
    validate_manifest(manifest, counts, errors)

    return {
        "data_dir": str(data_dir),
        "counts": counts,
        "errors": errors,
        "warnings": warnings,
    }


def validate_chunks(rows: list[dict[str, Any]], errors: list[str], warnings: list[str]) -> set[str]:
    required_fields = {
        "chunk_id",
        "source_id",
        "source_name",
        "source_url",
        "license",
        "section",
        "source_file",
        "text",
        "char_count",
        "token_estimate",
        "tags",
        "review_status",
    }
    chunk_ids: set[str] = set()
    for index, row in enumerate(rows, start=1):
        missing = sorted(required_fields - set(row))
        if missing:
            errors.append(f"chunks.jsonl row {index} is missing fields: {', '.join(missing)}")
            continue
        chunk_id = str(row["chunk_id"])
        if chunk_id in chunk_ids:
            errors.append(f"chunks.jsonl has duplicate chunk_id: {chunk_id}")
        chunk_ids.add(chunk_id)
        if not str(row.get("text", "")).strip():
            errors.append(f"chunk {chunk_id} has empty text.")
        if int_or_zero(row.get("char_count")) <= 0:
            errors.append(f"chunk {chunk_id} has non-positive char_count.")
        if int_or_zero(row.get("token_estimate")) <= 0:
            errors.append(f"chunk {chunk_id} has non-positive token_estimate.")
        if not isinstance(row.get("tags"), list) or not row["tags"]:
            errors.append(f"chunk {chunk_id} must have one or more tags.")
        actual_char_count = len(str(row.get("text", "")))
        declared_char_count = int_or_zero(row.get("char_count"))
        if declared_char_count and abs(actual_char_count - declared_char_count) > 10:
            warnings.append(
                f"chunk {chunk_id} char_count differs from text length "
                f"({declared_char_count} vs {actual_char_count})."
            )
    if not rows:
        errors.append("chunks.jsonl must contain at least one chunk.")
    return chunk_ids


def validate_chunk_index(rows: list[dict[str, Any]], chunk_ids: set[str], errors: list[str]) -> None:
    indexed_ids = {row.get("chunk_id") for row in rows if row.get("chunk_id")}
    missing_from_index = sorted(chunk_ids - indexed_ids)
    unknown_in_index = sorted(indexed_ids - chunk_ids)
    if missing_from_index:
        errors.append(f"chunk_index.csv is missing chunk ids: {', '.join(missing_from_index[:5])}")
    if unknown_in_index:
        errors.append(f"chunk_index.csv contains unknown chunk ids: {', '.join(unknown_in_index[:5])}")


def validate_selected_sources(data: dict[str, Any], errors: list[str]) -> set[str]:
    sources = data.get("sources", []) if isinstance(data, dict) else []
    source_ids: set[str] = set()
    required_fields = {"source_id", "path", "source_name", "source_url", "license", "use_for"}
    for index, source in enumerate(sources, start=1):
        if not isinstance(source, dict):
            errors.append(f"selected_sources.yaml source {index} must be a mapping.")
            continue
        missing = sorted(required_fields - set(source))
        if missing:
            errors.append(f"selected_sources.yaml source {index} is missing fields: {', '.join(missing)}")
        source_id = str(source.get("source_id", "")).strip()
        if not source_id:
            errors.append(f"selected_sources.yaml source {index} has empty source_id.")
        elif source_id in source_ids:
            errors.append(f"selected_sources.yaml has duplicate source_id: {source_id}")
        else:
            source_ids.add(source_id)
        if not isinstance(source.get("use_for"), list) or not source.get("use_for"):
            errors.append(f"selected source {source_id or index} must have one or more use_for values.")
    if not sources:
        errors.append("selected_sources.yaml must contain at least one source.")
    return source_ids


def validate_retrieval_gold(rows: list[dict[str, Any]], chunk_ids: set[str], errors: list[str]) -> None:
    required_fields = {"query_id", "query", "expected_chunk_ids", "required_concepts"}
    for index, row in enumerate(rows, start=1):
        missing = sorted(required_fields - set(row))
        if missing:
            errors.append(f"retrieval_gold.jsonl row {index} is missing fields: {', '.join(missing)}")
            continue
        expected_ids = row.get("expected_chunk_ids")
        if not isinstance(expected_ids, list) or not expected_ids:
            errors.append(f"retrieval_gold.jsonl row {index} must have expected_chunk_ids.")
            continue
        unknown_ids = sorted(set(expected_ids) - chunk_ids)
        if unknown_ids:
            errors.append(
                f"retrieval_gold.jsonl row {index} references unknown chunk ids: "
                f"{', '.join(unknown_ids)}"
            )
    if not rows:
        errors.append("retrieval_gold.jsonl must contain at least one case.")


def validate_generation_gold(data: dict[str, Any], source_ids: set[str], errors: list[str]) -> list[dict[str, Any]]:
    cases = data.get("cases", []) if isinstance(data, dict) else []
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            errors.append(f"generation_gold.yaml case {index} must be a mapping.")
            continue
        case_id = case.get("case_id", f"case {index}")
        case_input = case.get("input", {})
        expected = case.get("expected", {})
        if not isinstance(case_input, dict):
            errors.append(f"generation case {case_id} input must be a mapping.")
            continue
        unknown_sources = sorted(set(case_input.get("source_ids", [])) - source_ids)
        if unknown_sources:
            errors.append(f"generation case {case_id} references unknown source_ids: {', '.join(unknown_sources)}")
        if not expected.get("lesson_plan_sections"):
            errors.append(f"generation case {case_id} must define lesson_plan_sections.")
        if not expected.get("practice_required"):
            errors.append(f"generation case {case_id} must define practice_required.")
        assessment = expected.get("assessment_required", {})
        if int_or_zero(assessment.get("mcq_count")) <= 0:
            errors.append(f"generation case {case_id} must define positive mcq_count.")
        if int_or_zero(assessment.get("performance_task_count")) <= 0:
            errors.append(f"generation case {case_id} must define positive performance_task_count.")
    if not cases:
        errors.append("generation_gold.yaml must contain at least one case.")
    return cases


def validate_human_eval_rubric(data: dict[str, Any], errors: list[str]) -> None:
    criteria = data.get("criteria", []) if isinstance(data, dict) else []
    if not criteria:
        errors.append("human_eval_rubric.yaml must contain criteria.")
        return
    for index, criterion in enumerate(criteria, start=1):
        if not isinstance(criterion, dict):
            errors.append(f"human_eval_rubric.yaml criterion {index} must be a mapping.")
            continue
        if not criterion.get("name"):
            errors.append(f"human_eval_rubric.yaml criterion {index} must have name.")
        if int_or_zero(criterion.get("pass_score")) <= 0:
            errors.append(f"human_eval_rubric.yaml criterion {index} must have positive pass_score.")
        if not criterion.get("description"):
            errors.append(f"human_eval_rubric.yaml criterion {index} must have description.")


def validate_manifest(manifest: dict[str, Any], counts: dict[str, int], errors: list[str]) -> None:
    if not manifest:
        errors.append("dataset_manifest.json must be a non-empty object.")
        return
    expected_counts = {
        "chunk_count": counts["chunks"],
        "retrieval_gold_count": counts["retrieval_gold"],
        "generation_gold_count": counts["generation_gold"],
        "raw_sources": counts["selected_sources"],
    }
    for field, actual in expected_counts.items():
        declared = manifest.get(field)
        if declared != actual:
            errors.append(f"dataset_manifest.json {field} is {declared}, expected {actual}.")

    thresholds = manifest.get("quality_thresholds", {})
    threshold_map = {
        "min_chunks": counts["chunks"],
        "min_retrieval_gold": counts["retrieval_gold"],
        "min_generation_gold": counts["generation_gold"],
    }
    for threshold_name, actual in threshold_map.items():
        threshold = int_or_zero(thresholds.get(threshold_name))
        if threshold and actual < threshold:
            errors.append(f"{threshold_name} threshold is {threshold}, actual count is {actual}.")


def read_jsonl(path: Path, errors: list[str]) -> list[dict[str, Any]]:
    if not path.exists():
        errors.append(f"Missing required file: {path.as_posix()}")
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"{path.name} line {line_number} is invalid JSON: {exc.msg}")
                continue
            if not isinstance(value, dict):
                errors.append(f"{path.name} line {line_number} must be a JSON object.")
                continue
            rows.append(value)
    return rows


def read_json(path: Path, errors: list[str]) -> dict[str, Any]:
    if not path.exists():
        errors.append(f"Missing required file: {path.as_posix()}")
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"{path.name} is invalid JSON: {exc.msg}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{path.name} must be a JSON object.")
        return {}
    return value


def read_yaml(path: Path, errors: list[str]) -> dict[str, Any]:
    if not path.exists():
        errors.append(f"Missing required file: {path.as_posix()}")
        return {}
    with path.open("r", encoding="utf-8") as file:
        value = yaml.safe_load(file) or {}
    if not isinstance(value, dict):
        errors.append(f"{path.name} must be a YAML mapping.")
        return {}
    return value


def read_csv_rows(path: Path, errors: list[str]) -> list[dict[str, str]]:
    if not path.exists():
        errors.append(f"Missing required file: {path.as_posix()}")
        return []
    with path.open("r", encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate LessonPack AI MVP dataset artifacts.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="Path to the data directory.")
    parser.add_argument("--report", type=Path, help="Optional JSON report output path.")
    args = parser.parse_args(argv)

    report = validate_dataset(args.data_dir)
    output = json.dumps(report, ensure_ascii=False, indent=2)
    print(output)

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")

    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
