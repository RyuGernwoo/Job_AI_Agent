from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from lectureops_agent.models.schemas import LessonPackage


def load_generation_gold(path: Path | str) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    if not isinstance(data, dict):
        raise ValueError("generation gold must be a YAML mapping")
    if not isinstance(data.get("cases"), list):
        raise ValueError("generation gold must contain cases")
    return data


def evaluate_lesson_package(
    *,
    package: LessonPackage,
    expected: dict[str, Any],
    retrieved_chunk_ids: list[str],
) -> dict[str, Any]:
    expected_sections = [str(section) for section in expected.get("lesson_plan_sections", [])]
    actual_sections = [item.section for item in package.lesson_plan.lecture_flow]
    missing_lesson_sections = [section for section in expected_sections if section not in actual_sections]

    practice_text = _practice_text(package)
    missing_practice_items = [
        item for item in expected.get("practice_required", []) if not _practice_item_present(str(item), practice_text)
    ]

    assessment_required = expected.get("assessment_required", {})
    required_mcq_count = _int_or_zero(assessment_required.get("mcq_count"))
    required_performance_count = _int_or_zero(assessment_required.get("performance_task_count"))
    actual_mcq_count = len(package.assessment.multiple_choice)
    actual_performance_count = 1 if package.assessment.performance_task else 0
    assessment_passed = actual_mcq_count >= required_mcq_count and actual_performance_count >= required_performance_count

    missing_citation_items: list[str] = []
    citation_coverage = None
    if expected.get("citation_required"):
        missing_citation_items = _missing_citation_items(package, set(retrieved_chunk_ids))
        citation_coverage = _citation_coverage(package, set(retrieved_chunk_ids))

    ncs_alignment_coverage = _ncs_alignment_coverage(package)
    source_metadata_coverage = _source_metadata_coverage(package)
    citation_diversity = _citation_diversity(package)
    citation_source_resolution = _citation_source_resolution(package)
    assessment_quality = _assessment_quality(package)
    duration_alignment = _duration_alignment(
        package,
        expected_duration_min=_int_or_zero(
            expected.get("expected_duration_min", package.template_metadata.lesson_duration_min)
        ),
    )
    mcq_uniqueness = _mcq_uniqueness(package)

    checks = {
        "lesson_sections": not missing_lesson_sections,
        "practice_items": not missing_practice_items,
        "assessment": assessment_passed,
        "citations": not missing_citation_items,
        "ncs_alignment": (
            ncs_alignment_coverage["coverage"] >= float(expected.get("min_ncs_alignment_coverage", 0.0))
            if expected.get("ncs_alignment_required")
            else True
        ),
        "source_metadata": (
            source_metadata_coverage["coverage"] >= float(expected.get("min_source_metadata_coverage", 0.0))
            if expected.get("source_metadata_required")
            else True
        ),
        "citation_diversity": citation_diversity["unique_chunk_count"] >= int(expected.get("min_unique_citation_chunks", 1)),
        "citation_source_resolution": (
            citation_source_resolution["coverage"]
            >= float(expected.get("min_citation_source_resolution", 1.0))
        ),
        "assessment_quality": assessment_quality["coverage"] >= float(expected.get("min_assessment_quality", 1.0)),
        "duration_alignment": duration_alignment["score"] >= float(expected.get("min_duration_alignment", 0.9)),
        "mcq_uniqueness": mcq_uniqueness["coverage"] >= float(expected.get("min_mcq_uniqueness", 1.0)),
    }
    passed_checks = sum(1 for value in checks.values() if value)
    total_checks = len(checks)

    return {
        "passed": all(checks.values()),
        "score": round(passed_checks / total_checks, 4),
        "checks": checks,
        "missing_lesson_sections": missing_lesson_sections,
        "missing_practice_items": missing_practice_items,
        "assessment": {
            "required_mcq_count": required_mcq_count,
            "actual_mcq_count": actual_mcq_count,
            "required_performance_task_count": required_performance_count,
            "actual_performance_task_count": actual_performance_count,
        },
        "citation_coverage": citation_coverage,
        "ncs_alignment_coverage": ncs_alignment_coverage,
        "source_metadata_coverage": source_metadata_coverage,
        "citation_diversity": citation_diversity,
        "citation_source_resolution": citation_source_resolution,
        "assessment_quality": assessment_quality,
        "duration_alignment": duration_alignment,
        "mcq_uniqueness": mcq_uniqueness,
        "missing_citation_items": missing_citation_items,
    }


def _practice_text(package: LessonPackage) -> str:
    values = [
        package.practice.scenario,
        package.practice.submission,
        *package.practice.steps,
        *package.practice.rubric,
    ]
    return " ".join(values).casefold()


def _practice_item_present(item: str, practice_text: str) -> bool:
    normalized = item.casefold()
    structural_items = {
        "실습 시나리오": "scenario",
        "수행 절차": "steps",
        "제출물": "submission",
        "평가 기준": "rubric",
    }
    if normalized in structural_items:
        return True
    if " 또는 " in normalized:
        return any(part.strip() in practice_text for part in normalized.split(" 또는 "))
    return normalized in practice_text


def _missing_citation_items(package: LessonPackage, retrieved_chunk_ids: set[str]) -> list[str]:
    missing: list[str] = []
    for item in package.lesson_plan.lecture_flow:
        if not _valid_citations(item.citation_ids, retrieved_chunk_ids):
            missing.append(f"lesson_plan.{item.section}")
    if not _valid_citations(package.practice.citation_ids, retrieved_chunk_ids):
        missing.append("practice")
    for index, question in enumerate(package.assessment.multiple_choice, start=1):
        if not _valid_citations(question.citation_ids, retrieved_chunk_ids):
            missing.append(f"assessment.mcq.{index}")
    if not _valid_citations(package.assessment.performance_task.citation_ids, retrieved_chunk_ids):
        missing.append("assessment.performance_task")
    return missing


def _valid_citations(citation_ids: list[str], retrieved_chunk_ids: set[str]) -> bool:
    if not citation_ids:
        return False
    return all(citation_id in retrieved_chunk_ids for citation_id in citation_ids)


def _citation_coverage(package: LessonPackage, retrieved_chunk_ids: set[str]) -> dict[str, int | float]:
    citation_groups = [item.citation_ids for item in package.lesson_plan.lecture_flow]
    citation_groups.append(package.practice.citation_ids)
    citation_groups.extend(question.citation_ids for question in package.assessment.multiple_choice)
    citation_groups.append(package.assessment.performance_task.citation_ids)

    total = len(citation_groups)
    valid = sum(1 for citation_ids in citation_groups if _valid_citations(citation_ids, retrieved_chunk_ids))
    return {
        "valid_items": valid,
        "total_items": total,
        "coverage": round(valid / total, 4) if total else 0.0,
    }


def _ncs_alignment_coverage(package: LessonPackage) -> dict[str, int | float]:
    groups = [item.ncs_alignment for item in package.lesson_plan.lecture_flow]
    groups.append(package.practice.ncs_alignment)
    groups.extend(question.ncs_alignment for question in package.assessment.multiple_choice)
    groups.append(package.assessment.performance_task.ncs_alignment)
    total = len(groups)
    aligned = sum(1 for group in groups if group)
    return {
        "aligned_items": aligned,
        "total_items": total,
        "coverage": round(aligned / total, 4) if total else 0.0,
    }


def _source_metadata_coverage(package: LessonPackage) -> dict[str, int | float]:
    total = len(package.evidence_sources)
    complete = 0
    for detail in package.evidence_sources:
        has_source = bool(detail.source_name.strip())
        has_location = bool(detail.source_url or detail.source_file or detail.license)
        has_excerpt = bool(detail.excerpt.strip())
        if has_source and has_location and has_excerpt:
            complete += 1
    return {
        "complete_sources": complete,
        "total_sources": total,
        "coverage": round(complete / total, 4) if total else 0.0,
    }


def _citation_diversity(package: LessonPackage) -> dict[str, int]:
    citation_ids: set[str] = set()
    source_names: set[str] = set()
    for item in package.lesson_plan.lecture_flow:
        citation_ids.update(item.citation_ids)
    citation_ids.update(package.practice.citation_ids)
    for question in package.assessment.multiple_choice:
        citation_ids.update(question.citation_ids)
    citation_ids.update(package.assessment.performance_task.citation_ids)
    for detail in package.evidence_sources:
        if detail.chunk_id in citation_ids:
            source_names.add(detail.source_name)
    return {
        "unique_chunk_count": len(citation_ids),
        "unique_source_count": len(source_names),
    }


def _citation_source_resolution(package: LessonPackage) -> dict[str, int | float | list[str]]:
    cited_ids = _all_citation_ids(package)
    evidence_ids = {detail.chunk_id for detail in package.evidence_sources}
    missing_ids = sorted(cited_ids - evidence_ids)
    resolved = len(cited_ids) - len(missing_ids)
    return {
        "resolved_citations": resolved,
        "total_citations": len(cited_ids),
        "missing_chunk_ids": missing_ids,
        "coverage": round(resolved / len(cited_ids), 4) if cited_ids else 0.0,
    }


def _assessment_quality(package: LessonPackage) -> dict[str, int | float | list[str]]:
    checks: list[tuple[str, bool]] = []
    for index, question in enumerate(package.assessment.multiple_choice, start=1):
        normalized_options = [option.strip().casefold() for option in question.options]
        checks.extend(
            [
                (f"mcq.{index}.question", bool(question.question.strip())),
                (f"mcq.{index}.four_options", len(question.options) == 4),
                (f"mcq.{index}.unique_options", len(set(normalized_options)) == 4),
                (f"mcq.{index}.answer_index", 0 <= question.answer_index < len(question.options)),
                (f"mcq.{index}.explanation", bool(question.explanation.strip())),
            ]
        )

    task = package.assessment.performance_task
    checks.extend(
        [
            ("performance_task.title", bool(task.title.strip())),
            ("performance_task.description", bool(task.description.strip())),
            ("performance_task.rubric", len(task.rubric) >= 3),
        ]
    )
    failed = [name for name, passed in checks if not passed]
    passed_count = len(checks) - len(failed)
    return {
        "passed_checks": passed_count,
        "total_checks": len(checks),
        "failed_checks": failed,
        "coverage": round(passed_count / len(checks), 4) if checks else 0.0,
    }


def _duration_alignment(package: LessonPackage, *, expected_duration_min: int) -> dict[str, int | float]:
    durations = [item.duration_min for item in package.lesson_plan.lecture_flow]
    populated = sum(1 for duration in durations if duration is not None)
    actual_duration = sum(duration or 0 for duration in durations)
    completeness = round(populated / len(durations), 4) if durations else 0.0
    if expected_duration_min <= 0:
        alignment = 1.0 if actual_duration > 0 else 0.0
    else:
        deviation = abs(actual_duration - expected_duration_min) / expected_duration_min
        alignment = max(0.0, 1.0 - deviation)
    return {
        "expected_duration_min": expected_duration_min,
        "actual_duration_min": actual_duration,
        "duration_field_coverage": completeness,
        "score": round(alignment * completeness, 4),
    }


def _mcq_uniqueness(package: LessonPackage) -> dict[str, int | float]:
    questions = [question.question.strip().casefold() for question in package.assessment.multiple_choice]
    unique_count = len(set(questions))
    return {
        "unique_questions": unique_count,
        "total_questions": len(questions),
        "coverage": round(unique_count / len(questions), 4) if questions else 0.0,
    }


def _all_citation_ids(package: LessonPackage) -> set[str]:
    citation_ids: set[str] = set()
    for item in package.lesson_plan.lecture_flow:
        citation_ids.update(item.citation_ids)
    citation_ids.update(package.practice.citation_ids)
    for question in package.assessment.multiple_choice:
        citation_ids.update(question.citation_ids)
    citation_ids.update(package.assessment.performance_task.citation_ids)
    return citation_ids


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
