from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from lectureops_agent.models.schemas import NCSUnit, PackageStatus, ProjectCreate, ReviewPatch
from lectureops_agent.services.dataset_loader import DEFAULT_DATASET_PROJECT_ID, load_processed_chunks
from lectureops_agent.services.export_service import export_lesson_package_docx, export_lesson_package_pptx
from lectureops_agent.services.generation_evaluation import evaluate_lesson_package, load_generation_gold
from lectureops_agent.services.generation_service import generate_lesson_package_with_log
from lectureops_agent.services.llm_provider import LLMProvider, MockLLMProvider
from lectureops_agent.services.review_service import apply_review_patch


def run_mvp_demo(
    *,
    data_dir: Path | str,
    output_dir: Path | str,
    case_id: str | None = None,
    chunks_per_source: int = 2,
    project_id: str = DEFAULT_DATASET_PROJECT_ID,
    llm_provider: LLMProvider | None = None,
) -> dict[str, Any]:
    data_dir = Path(data_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    chunks = load_processed_chunks(data_dir, project_id=project_id)
    generation_gold = load_generation_gold(data_dir / "gold" / "generation_gold.yaml")
    case = _select_generation_case(generation_gold["cases"], case_id=case_id)
    case_id = str(case["case_id"])
    curriculum = _read_yaml(data_dir / "raw" / "curriculum" / "curriculum_python_prompt_automation.yaml")
    ncs_data = _read_yaml(data_dir / "raw" / "ncs" / "ncs_application_sw_programming.yaml")
    project = _project_from_case(case=case, curriculum=curriculum, ncs_data=ncs_data, project_id=f"{project_id}-{case_id}")
    selected_chunks = _select_chunks_for_case(
        chunks=chunks,
        source_ids=case["input"].get("source_ids", []),
        chunks_per_source=chunks_per_source,
    )
    if not selected_chunks:
        raise ValueError(f"no chunks selected for generation case: {case_id}")

    provider = llm_provider or MockLLMProvider()
    result = generate_lesson_package_with_log(
        project=project,
        retrieved_chunks=selected_chunks,
        package_id=f"demo-{case_id}",
        llm_provider=provider,
    )
    retrieved_chunk_ids = [chunk.chunk_id for chunk in selected_chunks]
    evaluation = evaluate_lesson_package(
        package=result.package,
        expected=case["expected"],
        retrieved_chunk_ids=retrieved_chunk_ids,
    )
    reviewed = apply_review_patch(
        result.package,
        ReviewPatch(status=PackageStatus.REVIEWED, reviewer_notes="MVP demo auto-review passed."),
    )
    approved = apply_review_patch(
        reviewed,
        ReviewPatch(status=PackageStatus.APPROVED, reviewer_notes="MVP demo package approved for export."),
    )

    docx_path = output_dir / f"{case_id}_lesson_package.docx"
    export_lesson_package_docx(package=approved, output_path=docx_path)
    pptx_path = output_dir / f"{case_id}_lesson_package.pptx"
    export_lesson_package_pptx(package=approved, output_path=pptx_path)

    report_path = output_dir / f"{case_id}_demo_report.json"
    report = {
        "case_id": case_id,
        "project_id": project.project_id,
        "package_id": approved.package_id,
        "package_status": approved.status.value,
        "provider_name": result.log.provider_name,
        "retrieved_chunk_ids": retrieved_chunk_ids,
        "evaluation": evaluation,
        "docx_path": str(docx_path),
        "pptx_path": str(pptx_path),
        "report_path": str(report_path),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _select_generation_case(cases: list[dict[str, Any]], *, case_id: str | None) -> dict[str, Any]:
    if not cases:
        raise ValueError("generation gold must contain at least one case")
    if case_id is None:
        return cases[0]
    for case in cases:
        if str(case.get("case_id")) == case_id:
            return case
    raise ValueError(f"generation case not found: {case_id}")


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
        lesson_title=curriculum.get("lesson_title", f"LessonPack AI 데모 케이스 {case['case_id']}"),
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
