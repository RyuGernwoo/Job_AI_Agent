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

    checks = {
        "lesson_sections": not missing_lesson_sections,
        "practice_items": not missing_practice_items,
        "assessment": assessment_passed,
        "citations": not missing_citation_items,
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


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
