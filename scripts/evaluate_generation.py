"""Evaluate LessonPack AI package generation against the generation Gold Set."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from lectureops_agent.models.schemas import NCSUnit, ProjectCreate
from lectureops_agent.services.dataset_loader import DEFAULT_DATASET_PROJECT_ID, load_processed_chunks
from lectureops_agent.services.generation_evaluation import evaluate_lesson_package, load_generation_gold
from lectureops_agent.services.generation_service import generate_lesson_package_with_log
from lectureops_agent.services.llm_provider import create_llm_provider_from_env
from scripts.validate_mvp_dataset import validate_dataset


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate LessonPack AI package generation quality.")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data", help="Path to the data directory.")
    parser.add_argument("--project-id", default=DEFAULT_DATASET_PROJECT_ID, help="Base project id for evaluation cases.")
    parser.add_argument("--chunks-per-source", type=int, default=2, help="Number of chunks selected per source id.")
    parser.add_argument("--min-case-pass-rate", type=float, default=0.0, help="Optional minimum case pass rate gate.")
    parser.add_argument("--report", type=Path, help="Optional JSON report output path.")
    args = parser.parse_args(argv)

    validation = validate_dataset(args.data_dir)
    if validation["errors"]:
        print(json.dumps({"validation": validation}, ensure_ascii=False, indent=2))
        return 1

    chunks = load_processed_chunks(args.data_dir, project_id=args.project_id)
    generation_gold = load_generation_gold(args.data_dir / "gold" / "generation_gold.yaml")
    curriculum = _read_yaml(args.data_dir / "raw" / "curriculum" / "curriculum_python_prompt_automation.yaml")
    ncs_data = _read_yaml(args.data_dir / "raw" / "ncs" / "ncs_application_sw_programming.yaml")
    provider = create_llm_provider_from_env()

    case_reports = []
    passed_cases = 0
    score_sum = 0.0
    for case in generation_gold["cases"]:
        case_id = str(case["case_id"])
        project = _project_from_case(
            case=case,
            curriculum=curriculum,
            ncs_data=ncs_data,
            project_id=f"{args.project_id}-{case_id}",
        )
        selected_chunks = _select_chunks_for_case(
            chunks=chunks,
            source_ids=case["input"].get("source_ids", []),
            chunks_per_source=args.chunks_per_source,
        )
        if not selected_chunks:
            evaluation = {
                "passed": False,
                "score": 0.0,
                "error": "no chunks selected for case",
            }
            log_provider_name = provider.name
            package_id = None
            retrieved_chunk_ids: list[str] = []
        else:
            result = generate_lesson_package_with_log(
                project=project,
                retrieved_chunks=selected_chunks,
                package_id=f"package-{case_id}",
                llm_provider=provider,
            )
            retrieved_chunk_ids = [chunk.chunk_id for chunk in selected_chunks]
            evaluation = evaluate_lesson_package(
                package=result.package,
                expected=case["expected"],
                retrieved_chunk_ids=retrieved_chunk_ids,
            )
            log_provider_name = result.log.provider_name
            package_id = result.package.package_id

        if evaluation["passed"]:
            passed_cases += 1
        score_sum += float(evaluation.get("score", 0.0))
        case_reports.append(
            {
                "case_id": case_id,
                "package_id": package_id,
                "provider_name": log_provider_name,
                "source_ids": case["input"].get("source_ids", []),
                "retrieved_chunk_ids": retrieved_chunk_ids,
                "evaluation": evaluation,
            }
        )

    total_cases = len(case_reports)
    case_pass_rate = round(passed_cases / total_cases, 4) if total_cases else 0.0
    report = {
        "total_cases": total_cases,
        "passed_cases": passed_cases,
        "case_pass_rate": case_pass_rate,
        "average_score": round(score_sum / total_cases, 4) if total_cases else 0.0,
        "passed_min_case_pass_rate": case_pass_rate >= args.min_case_pass_rate,
        "data_dir": str(args.data_dir),
        "validation": validation,
        "cases": case_reports,
    }

    output = json.dumps(report, ensure_ascii=False, indent=2)
    print(output)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")

    return 0 if report["passed_min_case_pass_rate"] else 1


def _project_from_case(
    *,
    case: dict[str, Any],
    curriculum: dict[str, Any],
    ncs_data: dict[str, Any],
    project_id: str,
):
    ncs_unit_id = str(case["input"].get("ncs_unit_id", ""))
    return ProjectCreate(
        course_title=curriculum.get("course_title", "생성형 AI 활용 Python 기초"),
        lesson_title=curriculum.get("lesson_title", f"LessonPack AI 평가 케이스 {case['case_id']}"),
        learner_profile=curriculum.get("learner_profile", "직업훈련 수강생"),
        learning_objectives=curriculum.get("learning_objectives") or ["근거 자료 기반 수업 초안을 생성할 수 있다."],
        ncs_units=[_ncs_unit_from_data(ncs_unit_id=ncs_unit_id, ncs_data=ncs_data)],
    ).to_project(project_id=project_id)


def _ncs_unit_from_data(*, ncs_unit_id: str, ncs_data: dict[str, Any]) -> NCSUnit:
    selected_units = ncs_data.get("selected_units", []) if isinstance(ncs_data, dict) else []
    for unit in selected_units:
        if str(unit.get("unit_code")) == ncs_unit_id:
            return NCSUnit(
                unit_code=ncs_unit_id,
                unit_name=str(unit.get("unit_name", ncs_unit_id)),
                elements=[str(topic) for topic in unit.get("learning_topics", [])],
            )
    return NCSUnit(unit_code=ncs_unit_id or "MVP-NCS", unit_name=ncs_unit_id or "MVP NCS", elements=[])


def _select_chunks_for_case(*, chunks, source_ids: list[str], chunks_per_source: int):
    selected = []
    for source_id in source_ids:
        matching = [chunk for chunk in chunks if chunk.metadata.get("source_id") == source_id]
        selected.extend(matching[:chunks_per_source])
    return selected


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    return data if isinstance(data, dict) else {}


if __name__ == "__main__":
    sys.exit(main())
