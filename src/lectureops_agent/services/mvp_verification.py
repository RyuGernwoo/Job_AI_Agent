from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from lectureops_agent.models.schemas import NCSUnit, ProjectCreate
from lectureops_agent.services.dataset_loader import DEFAULT_DATASET_PROJECT_ID, load_processed_chunks
from lectureops_agent.services.generation_evaluation import evaluate_lesson_package, load_generation_gold
from lectureops_agent.services.generation_service import generate_lesson_package_with_log
from lectureops_agent.services.llm_provider import LLMProvider, create_llm_provider_from_env
from lectureops_agent.services.llm_provider_readiness import check_llm_provider_readiness
from lectureops_agent.services.mvp_demo_runner import run_mvp_demo
from lectureops_agent.services.retrieval_evaluation import evaluate_retrieval_gold, load_retrieval_gold


def run_mvp_verification(
    *,
    data_dir: Path | str,
    output_dir: Path | str,
    project_id: str = DEFAULT_DATASET_PROJECT_ID,
    retrieval_top_k: int = 3,
    chunks_per_source: int = 2,
    demo_case_id: str = "g003",
    min_retrieval_hit_rate: float = 0.7,
    min_generation_case_pass_rate: float = 1.0,
    require_real_llm: bool = False,
    llm_provider: LLMProvider | None = None,
    validation_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from scripts.validate_mvp_dataset import validate_dataset

    data_dir = Path(data_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = f"mvp-verification-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    validation = validation_report or validate_dataset(data_dir)
    provider_readiness = check_llm_provider_readiness()
    thresholds = {
        "min_retrieval_hit_rate": min_retrieval_hit_rate,
        "min_generation_case_pass_rate": min_generation_case_pass_rate,
        "require_real_llm": require_real_llm,
    }

    provider_gate = bool(provider_readiness["ready"]) and (
        not require_real_llm or bool(provider_readiness["real_provider_ready"])
    )
    gates = {
        "dataset_valid": not validation["errors"],
        "provider_ready": bool(provider_readiness["ready"]),
        "real_provider_ready_if_required": not require_real_llm or bool(provider_readiness["real_provider_ready"]),
        "retrieval_passed": False,
        "generation_passed": False,
        "demo_passed": False,
    }

    retrieval_report: dict[str, Any]
    generation_report: dict[str, Any]
    demo_report: dict[str, Any]

    if validation["errors"]:
        retrieval_report = _skipped_report("dataset validation failed")
        generation_report = _skipped_report("dataset validation failed")
        demo_report = _skipped_report("dataset validation failed")
    else:
        chunks = load_processed_chunks(data_dir, project_id=project_id)
        retrieval_report = _run_retrieval_eval(
            data_dir=data_dir,
            chunks=chunks,
            top_k=retrieval_top_k,
            min_hit_rate=min_retrieval_hit_rate,
        )
        gates["retrieval_passed"] = bool(retrieval_report["passed_min_hit_rate"])

        if provider_gate:
            provider = llm_provider or create_llm_provider_from_env()
            generation_report = _run_generation_eval(
                data_dir=data_dir,
                chunks=chunks,
                project_id=project_id,
                chunks_per_source=chunks_per_source,
                min_case_pass_rate=min_generation_case_pass_rate,
                llm_provider=provider,
            )
            gates["generation_passed"] = bool(generation_report["passed_min_case_pass_rate"])
            demo_report = _run_demo_eval(
                data_dir=data_dir,
                output_dir=output_dir / "demo",
                case_id=demo_case_id,
                chunks_per_source=chunks_per_source,
                llm_provider=provider,
            )
            gates["demo_passed"] = bool(demo_report["passed"])
        else:
            generation_report = _skipped_report("LLM provider is not ready")
            demo_report = _skipped_report("LLM provider is not ready")

    report = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data_dir": str(data_dir),
        "output_dir": str(output_dir),
        "thresholds": thresholds,
        "passed": all(gates.values()),
        "gates": gates,
        "validation": validation,
        "provider_readiness": provider_readiness,
        "retrieval": retrieval_report,
        "generation": generation_report,
        "demo": demo_report,
    }
    return report


def render_mvp_verification_markdown(report: dict[str, Any]) -> str:
    validation = report["validation"]
    provider = report["provider_readiness"]
    retrieval = report["retrieval"]
    generation = report["generation"]
    demo = report["demo"]
    status = "PASS" if report["passed"] else "FAIL"

    lines = [
        "# LessonPack AI MVP Verification Report",
        "",
        f"- Run ID: `{report['run_id']}`",
        f"- Status: **{status}**",
        f"- Data Dir: `{report['data_dir']}`",
        f"- Output Dir: `{report['output_dir']}`",
        "",
        "## Gates",
        "",
        "| Gate | Result |",
        "|---|---:|",
    ]
    for gate, passed in report["gates"].items():
        lines.append(f"| `{gate}` | {'PASS' if passed else 'FAIL'} |")

    lines.extend(
        [
            "",
            "## Dataset",
            "",
            f"- Errors: {len(validation['errors'])}",
            f"- Warnings: {len(validation['warnings'])}",
            f"- Counts: `{validation['counts']}`",
            "",
            "## Provider",
            "",
            f"- Provider: `{provider.get('provider')}`",
            f"- Model: `{provider.get('model')}`",
            f"- Ready: `{provider.get('ready')}`",
            f"- Real Provider Ready: `{provider.get('real_provider_ready')}`",
            "",
            "## Retrieval",
            "",
            f"- Total Queries: {retrieval.get('total_queries', 0)}",
            f"- Hit Rate: {retrieval.get('hit_rate', 0)}",
            f"- Mean Reciprocal Rank: {retrieval.get('mean_reciprocal_rank', 0)}",
            f"- Average Context Precision: {retrieval.get('average_context_precision', 0)}",
            f"- Average Context Recall: {retrieval.get('average_context_recall', 0)}",
            "",
            "## Generation",
            "",
            f"- Total Cases: {generation.get('total_cases', 0)}",
            f"- Case Pass Rate: {generation.get('case_pass_rate', 0)}",
            f"- Average Score: {generation.get('average_score', 0)}",
            f"- Average Citation Coverage: {generation.get('average_citation_coverage', 0)}",
            "",
            "## Demo Artifacts",
            "",
            f"- Demo Passed: `{demo.get('passed', False)}`",
            f"- DOCX: `{demo.get('docx_path', '')}`",
            f"- PPTX: `{demo.get('pptx_path', '')}`",
            f"- Report: `{demo.get('report_path', '')}`",
            "",
        ]
    )
    if validation["errors"]:
        lines.extend(["## Dataset Errors", ""])
        lines.extend(f"- {error}" for error in validation["errors"])
        lines.append("")
    if provider.get("next_steps"):
        lines.extend(["## Provider Next Steps", ""])
        lines.extend(f"- {step}" for step in provider["next_steps"])
        lines.append("")
    return "\n".join(lines)


def _run_retrieval_eval(
    *,
    data_dir: Path,
    chunks,
    top_k: int,
    min_hit_rate: float,
) -> dict[str, Any]:
    gold_rows = load_retrieval_gold(data_dir / "gold" / "retrieval_gold.jsonl")
    report = evaluate_retrieval_gold(chunks=chunks, gold_rows=gold_rows, top_k=top_k)
    report["passed_min_hit_rate"] = report["hit_rate"] >= min_hit_rate
    return report


def _run_generation_eval(
    *,
    data_dir: Path,
    chunks,
    project_id: str,
    chunks_per_source: int,
    min_case_pass_rate: float,
    llm_provider: LLMProvider,
) -> dict[str, Any]:
    generation_gold = load_generation_gold(data_dir / "gold" / "generation_gold.yaml")
    curriculum = _read_yaml(data_dir / "raw" / "curriculum" / "curriculum_python_prompt_automation.yaml")
    ncs_data = _read_yaml(data_dir / "raw" / "ncs" / "ncs_application_sw_programming.yaml")
    case_reports = []
    passed_cases = 0
    score_sum = 0.0
    citation_coverage_sum = 0.0

    for case in generation_gold["cases"]:
        case_id = str(case["case_id"])
        selected_chunks = _select_chunks_for_case(
            chunks=chunks,
            source_ids=case["input"].get("source_ids", []),
            chunks_per_source=chunks_per_source,
        )
        if not selected_chunks:
            evaluation = {"passed": False, "score": 0.0, "error": "no chunks selected for case"}
            package_id = None
            retrieved_chunk_ids: list[str] = []
        else:
            project = _project_from_case(
                case=case,
                curriculum=curriculum,
                ncs_data=ncs_data,
                project_id=f"{project_id}-{case_id}",
            )
            result = generate_lesson_package_with_log(
                project=project,
                retrieved_chunks=selected_chunks,
                package_id=f"package-{case_id}",
                llm_provider=llm_provider,
            )
            retrieved_chunk_ids = [chunk.chunk_id for chunk in selected_chunks]
            evaluation = evaluate_lesson_package(
                package=result.package,
                expected=case["expected"],
                retrieved_chunk_ids=retrieved_chunk_ids,
            )
            package_id = result.package.package_id

        if evaluation["passed"]:
            passed_cases += 1
        score_sum += float(evaluation.get("score", 0.0))
        citation_coverage = evaluation.get("citation_coverage") or {}
        citation_coverage_sum += float(citation_coverage.get("coverage", 0.0))
        case_reports.append(
            {
                "case_id": case_id,
                "package_id": package_id,
                "source_ids": case["input"].get("source_ids", []),
                "retrieved_chunk_ids": retrieved_chunk_ids,
                "evaluation": evaluation,
            }
        )

    total_cases = len(case_reports)
    case_pass_rate = round(passed_cases / total_cases, 4) if total_cases else 0.0
    return {
        "total_cases": total_cases,
        "passed_cases": passed_cases,
        "case_pass_rate": case_pass_rate,
        "average_score": round(score_sum / total_cases, 4) if total_cases else 0.0,
        "average_citation_coverage": round(citation_coverage_sum / total_cases, 4) if total_cases else 0.0,
        "passed_min_case_pass_rate": case_pass_rate >= min_case_pass_rate,
        "cases": case_reports,
    }


def _run_demo_eval(
    *,
    data_dir: Path,
    output_dir: Path,
    case_id: str,
    chunks_per_source: int,
    llm_provider: LLMProvider,
) -> dict[str, Any]:
    report = run_mvp_demo(
        data_dir=data_dir,
        output_dir=output_dir,
        case_id=case_id,
        chunks_per_source=chunks_per_source,
        llm_provider=llm_provider,
    )
    docx_path = Path(report["docx_path"])
    pptx_path = Path(report["pptx_path"])
    report["docx_exists"] = docx_path.exists()
    report["pptx_exists"] = pptx_path.exists()
    report["passed"] = bool(report["evaluation"]["passed"] and report["docx_exists"] and report["pptx_exists"])
    return report


def _project_from_case(
    *,
    case: dict[str, Any],
    curriculum: dict[str, Any],
    ncs_data: dict[str, Any],
    project_id: str,
):
    ncs_unit_id = str(case["input"].get("ncs_unit_id", ""))
    return ProjectCreate(
        course_title=curriculum.get("course_title", "Generative AI Python Basics"),
        lesson_title=curriculum.get("lesson_title", f"LessonPack AI evaluation case {case['case_id']}"),
        learner_profile=curriculum.get("learner_profile", "Job training learners"),
        learning_objectives=curriculum.get("learning_objectives") or ["Create a grounded lesson package draft."],
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


def _skipped_report(reason: str) -> dict[str, Any]:
    return {
        "skipped": True,
        "reason": reason,
    }
