from __future__ import annotations

import re
from collections import OrderedDict
from pathlib import Path

from docx import Document
from pptx import Presentation

from lectureops_agent.models.schemas import CourseType, CitationDetail, LessonPackage, NCSAlignment


_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_FILENAME_SEPARATOR = re.compile(r"[\s_]+")


def export_lesson_package_docx(*, package: LessonPackage, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    document = Document()
    document.add_heading(package.lesson_plan.title, level=0)
    document.add_paragraph(f"템플릿 버전: {package.template_metadata.template_version}")
    if package.template_metadata.lesson_duration_min:
        document.add_paragraph(f"수업 시간: {package.template_metadata.lesson_duration_min}분")
    training_plan = _training_plan_summary(package)
    if training_plan:
        document.add_paragraph(training_plan)

    document.add_heading("학습 목표", level=1)
    for objective in package.lesson_plan.learning_objectives:
        document.add_paragraph(objective, style="List Bullet")
    if package.course_type == CourseType.GENERAL:
        document.add_heading("학습목표-활동-평가 연결", level=1)
        for objective in package.lesson_plan.learning_objectives:
            document.add_paragraph(
                f"{objective} → 교안 설명 → 실습 수행 → 객관식·수행평가 확인",
                style="List Bullet",
            )

    document.add_heading("교안", level=1)
    for flow in package.lesson_plan.lecture_flow:
        document.add_heading(flow.section, level=2)
        if flow.duration_min:
            document.add_paragraph(f"예상 시간: {flow.duration_min}분")
        document.add_paragraph(flow.content)
        _add_alignment_paragraph(document, flow.ncs_alignment)

    document.add_heading("실습 과제", level=1)
    document.add_paragraph(_without_label(package.practice.scenario, "실습 시나리오"))
    document.add_heading("수행 절차", level=2)
    for step in package.practice.steps:
        document.add_paragraph(_without_label(step, "수행 절차"), style="List Number")
    document.add_heading("제출물", level=2)
    document.add_paragraph(_without_label(package.practice.submission, "제출물"))
    document.add_heading("실습 루브릭", level=2)
    for item in package.practice.rubric:
        document.add_paragraph(_without_label(item, "평가 기준"), style="List Bullet")
    _add_alignment_paragraph(document, package.practice.ncs_alignment)

    document.add_heading("평가 문항", level=1)
    for index, question in enumerate(package.assessment.multiple_choice, start=1):
        document.add_paragraph(f"문항 {index}. {question.question}")
        for option_index, option in enumerate(question.options, start=1):
            document.add_paragraph(f"{option_index}. {option}", style="List Bullet")
        document.add_paragraph(f"정답: {question.answer_index + 1}")
        document.add_paragraph(f"해설: {question.explanation}")
        _add_alignment_paragraph(document, question.ncs_alignment)

    task = package.assessment.performance_task
    document.add_heading("수행평가", level=2)
    document.add_paragraph(task.title)
    document.add_paragraph(task.description)
    for item in task.rubric:
        document.add_paragraph(_without_label(item, "평가 기준"), style="List Bullet")
    _add_alignment_paragraph(document, task.ncs_alignment)

    _add_ncs_coverage_section(document, package)
    _add_evidence_section(document, package)

    document.save(output_path)
    return output_path


def export_lesson_package_pptx(*, package: LessonPackage, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    presentation = Presentation()

    cover = presentation.slides.add_slide(presentation.slide_layouts[0])
    cover.shapes.title.text = package.lesson_plan.title
    training_plan = _training_plan_summary(package)
    cover.placeholders[1].text = "\n".join(
        value for value in ["LessonPack AI 강의 패키지", training_plan] if value
    )

    _add_bullet_slide(presentation, "학습 목표", package.lesson_plan.learning_objectives)
    if package.course_type == CourseType.GENERAL:
        _add_bullet_slide(
            presentation,
            "학습목표-활동-평가 연결",
            [
                f"{objective} → 교안 → 실습 → 평가"
                for objective in package.lesson_plan.learning_objectives
            ],
        )

    for flow in package.lesson_plan.lecture_flow:
        bullets = []
        if flow.duration_min:
            bullets.append(f"예상 시간: {flow.duration_min}분")
        bullets.append(flow.content)
        bullets.extend(_alignment_bullets(flow.ncs_alignment))
        _add_bullet_slide(presentation, f"교안 - {flow.section}", bullets)

    _add_bullet_slide(
        presentation,
        "실습 과제 개요",
        [
            _without_label(package.practice.scenario, "실습 시나리오"),
            f"제출물: {_without_label(package.practice.submission, '제출물')}",
        ],
    )
    _add_bullet_slide(
        presentation,
        "실습 수행 절차",
        [_without_label(step, "수행 절차") for step in package.practice.steps],
    )
    _add_bullet_slide(
        presentation,
        "실습 루브릭",
        [
            *[_without_label(item, "평가 기준") for item in package.practice.rubric],
            *_alignment_bullets(package.practice.ncs_alignment),
        ],
    )

    task = package.assessment.performance_task
    _add_bullet_slide(
        presentation,
        "평가 개요",
        [
            f"객관식 문항 수: {len(package.assessment.multiple_choice)}",
            f"수행평가: {task.title}",
            task.description,
        ],
    )
    for index, question in enumerate(package.assessment.multiple_choice[:3], start=1):
        _add_bullet_slide(
            presentation,
            f"평가 문항 {index}",
            [
                question.question,
                f"정답: {question.answer_index + 1}",
                f"해설: {question.explanation}",
            ],
        )

    if package.ncs_coverage is not None:
        _add_bullet_slide(
            presentation,
            "NCS 수행준거 커버리지",
            _ncs_coverage_bullets(package),
        )

    # 근거는 발표 흐름을 방해하지 않도록 마지막 출처 슬라이드에만 표시한다.
    _add_bullet_slide(presentation, "근거 출처", _compact_evidence_bullets(package))

    presentation.save(output_path)
    return output_path


def build_export_filename(package: LessonPackage, extension: str) -> str:
    normalized_extension = extension.casefold().lstrip(".")
    if normalized_extension not in {"docx", "pptx"}:
        raise ValueError(f"unsupported export extension: {extension}")

    title = _INVALID_FILENAME_CHARS.sub(" ", package.lesson_plan.title)
    title = _FILENAME_SEPARATOR.sub("_", title).strip("._ ")
    title = title[:48].rstrip("._ ") or "LessonPack"
    suffix = "교안" if normalized_extension == "docx" else "강의자료"
    return f"{title}_{suffix}.{normalized_extension}"


def _training_plan_summary(package: LessonPackage) -> str:
    metadata = package.template_metadata
    if (
        metadata.total_training_hours is None
        or metadata.total_lessons is None
        or metadata.theory_ratio_percent is None
        or metadata.practice_ratio_percent is None
    ):
        return ""
    return (
        f"훈련 운영: 총 {metadata.total_training_hours:g}시간 · {metadata.total_lessons}차시 · "
        f"이론 {metadata.theory_ratio_percent}% · 실습 {metadata.practice_ratio_percent}%"
    )


def _add_alignment_paragraph(document: Document, alignments: list[NCSAlignment]) -> None:
    if not alignments:
        return
    for alignment in alignments:
        document.add_paragraph(f"NCS 연계: {alignment.unit_code} {alignment.unit_name}")


def _add_ncs_coverage_section(document: Document, package: LessonPackage) -> None:
    report = package.ncs_coverage
    if report is None:
        return
    document.add_heading("NCS 수행준거 커버리지", level=1)
    document.add_paragraph(
        f"설계 커버리지 {report.covered_criteria_count}/{report.target_criteria_count} "
        f"({report.coverage * 100:.0f}%), 평가 커버리지 "
        f"{report.assessment_criteria_count}/{report.target_criteria_count} "
        f"({report.assessment_coverage * 100:.0f}%)"
    )
    for item in report.items:
        locations = [*item.lesson_sections]
        if item.practice:
            locations.append("실습")
        locations.extend(item.assessment_items)
        document.add_paragraph(
            f"{item.unit_code} {item.performance_criterion} | "
            f"연결: {', '.join(locations) if locations else '없음'}",
            style="List Bullet",
        )
    for warning in report.warnings:
        document.add_paragraph(f"주의: {warning}")


def _add_evidence_section(document: Document, package: LessonPackage) -> None:
    document.add_heading("근거 출처", level=1)
    document.add_paragraph("본문에서 사용한 근거를 출처별로 정리했습니다.")
    for item in _grouped_evidence_bullets(package, include_url=True):
        document.add_paragraph(item, style="List Bullet")


def _collect_citation_ids(package: LessonPackage) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()

    def add_many(citation_ids: list[str]) -> None:
        for citation_id in citation_ids:
            if citation_id not in seen:
                seen.add(citation_id)
                ordered.append(citation_id)

    for flow in package.lesson_plan.lecture_flow:
        add_many(flow.citation_ids)
    add_many(package.practice.citation_ids)
    for question in package.assessment.multiple_choice:
        add_many(question.citation_ids)
    add_many(package.assessment.performance_task.citation_ids)
    return ordered


def _evidence_details(package: LessonPackage) -> list[CitationDetail]:
    citation_ids = _collect_citation_ids(package)
    details_by_id = {detail.chunk_id: detail for detail in package.evidence_sources}
    return [
        details_by_id.get(
            citation_id,
            CitationDetail(
                chunk_id=citation_id,
                source_name="출처 정보 미기재",
                excerpt="원문 발췌 정보가 패키지에 저장되지 않았습니다.",
            ),
        )
        for citation_id in citation_ids
    ]


def _alignment_bullets(alignments: list[NCSAlignment]) -> list[str]:
    if not alignments:
        return []
    return [f"NCS 연계: {alignment.unit_code} {alignment.unit_name}" for alignment in alignments]


def _ncs_coverage_bullets(package: LessonPackage) -> list[str]:
    report = package.ncs_coverage
    if report is None:
        return []
    bullets = [
        f"설계 커버리지: {report.covered_criteria_count}/{report.target_criteria_count} "
        f"({report.coverage * 100:.0f}%)",
        f"평가 커버리지: {report.assessment_criteria_count}/{report.target_criteria_count} "
        f"({report.assessment_coverage * 100:.0f}%)",
    ]
    bullets.extend(
        f"{item.unit_code}: {item.performance_criterion}"
        for item in report.items[:3]
    )
    bullets.extend(f"주의: {warning}" for warning in report.warnings)
    return bullets


def _compact_evidence_bullets(package: LessonPackage) -> list[str]:
    return _grouped_evidence_bullets(package, include_url=False)


def _grouped_evidence_bullets(package: LessonPackage, *, include_url: bool) -> list[str]:
    grouped: OrderedDict[str, dict[str, object]] = OrderedDict()
    for detail in _evidence_details(package):
        group = grouped.setdefault(
            detail.source_name,
            {"chunk_ids": [], "source_url": detail.source_url, "license": detail.license},
        )
        chunk_ids = group["chunk_ids"]
        assert isinstance(chunk_ids, list)
        chunk_ids.append(detail.chunk_id)
        if not group["source_url"] and detail.source_url:
            group["source_url"] = detail.source_url
        if not group["license"] and detail.license:
            group["license"] = detail.license

    bullets: list[str] = []
    for source_name, values in grouped.items():
        chunk_ids = ", ".join(str(value) for value in values["chunk_ids"])
        text = f"{source_name} | 사용 청크: {chunk_ids}"
        if include_url and values["source_url"]:
            text += f" | URL: {values['source_url']}"
        if values["license"]:
            text += f" | 라이선스: {values['license']}"
        elif not include_url and values["source_url"]:
            text += f" | {values['source_url']}"
        bullets.append(text)
    return bullets or ["사용된 근거 출처가 없습니다."]


def _without_label(value: str, label: str) -> str:
    normalized = value.strip()
    prefix = f"{label}:"
    if normalized.startswith(prefix):
        return normalized[len(prefix) :].strip()
    return normalized


def _add_bullet_slide(presentation: Presentation, title: str, bullets: list[str]) -> None:
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = title
    body = slide.placeholders[1].text_frame
    body.clear()
    for index, bullet in enumerate(_split_bullets(bullets)):
        paragraph = body.paragraphs[0] if index == 0 else body.add_paragraph()
        paragraph.text = _truncate(bullet)
        paragraph.level = 0


def _split_bullets(bullets: list[str], *, max_items: int = 6) -> list[str]:
    flattened: list[str] = []
    for bullet in bullets:
        normalized = " ".join(str(bullet).split())
        if normalized:
            flattened.append(normalized)
    if len(flattened) <= max_items:
        return flattened
    return [*flattened[: max_items - 1], f"외 {len(flattened) - max_items + 1}개 항목은 DOCX에서 확인"]


def _truncate(value: str, max_length: int = 180) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 3].rstrip() + "..."
