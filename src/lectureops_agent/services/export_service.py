from pathlib import Path

from docx import Document
from pptx import Presentation

from lectureops_agent.models.schemas import CitationDetail, LessonPackage, NCSAlignment, PackageStatus


def export_lesson_package_docx(*, package: LessonPackage, output_path: Path) -> Path:
    _ensure_exportable(package)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    document = Document()
    document.add_heading(package.lesson_plan.title, level=0)
    document.add_paragraph(f"패키지 ID: {package.package_id}")
    document.add_paragraph(f"프로젝트 ID: {package.project_id}")
    document.add_paragraph(f"상태: {package.status.value}")
    document.add_paragraph(f"템플릿 버전: {package.template_metadata.template_version}")
    if package.template_metadata.lesson_duration_min:
        document.add_paragraph(f"수업 시간: {package.template_metadata.lesson_duration_min}분")

    document.add_heading("학습 목표", level=1)
    for objective in package.lesson_plan.learning_objectives:
        document.add_paragraph(objective, style="List Bullet")

    document.add_heading("교안", level=1)
    for flow in package.lesson_plan.lecture_flow:
        document.add_heading(flow.section, level=2)
        if flow.duration_min:
            document.add_paragraph(f"예상 시간: {flow.duration_min}분")
        document.add_paragraph(flow.content)
        _add_alignment_paragraph(document, flow.ncs_alignment)
        document.add_paragraph(f"근거: {', '.join(flow.citation_ids)}")

    document.add_heading("실습 과제", level=1)
    document.add_paragraph(package.practice.scenario)
    document.add_heading("수행 절차", level=2)
    for step in package.practice.steps:
        document.add_paragraph(step, style="List Number")
    document.add_heading("제출물", level=2)
    document.add_paragraph(package.practice.submission)
    document.add_heading("실습 루브릭", level=2)
    for item in package.practice.rubric:
        document.add_paragraph(item, style="List Bullet")
    _add_alignment_paragraph(document, package.practice.ncs_alignment)
    document.add_paragraph(f"근거: {', '.join(package.practice.citation_ids)}")

    document.add_heading("평가 문항", level=1)
    for index, question in enumerate(package.assessment.multiple_choice, start=1):
        document.add_paragraph(f"문항 {index}. {question.question}")
        for option_index, option in enumerate(question.options, start=1):
            document.add_paragraph(f"{option_index}. {option}", style="List Bullet")
        document.add_paragraph(f"정답: {question.answer_index + 1}")
        document.add_paragraph(f"해설: {question.explanation}")
        _add_alignment_paragraph(document, question.ncs_alignment)
        document.add_paragraph(f"근거: {', '.join(question.citation_ids)}")

    task = package.assessment.performance_task
    document.add_heading("수행평가", level=2)
    document.add_paragraph(task.title)
    document.add_paragraph(task.description)
    for item in task.rubric:
        document.add_paragraph(item, style="List Bullet")
    _add_alignment_paragraph(document, task.ncs_alignment)
    document.add_paragraph(f"근거: {', '.join(task.citation_ids)}")

    _add_review_section(document, package)
    _add_evidence_section(document, package)

    document.save(output_path)
    return output_path


def export_lesson_package_pptx(*, package: LessonPackage, output_path: Path) -> Path:
    _ensure_exportable(package)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    presentation = Presentation()

    cover = presentation.slides.add_slide(presentation.slide_layouts[0])
    cover.shapes.title.text = package.lesson_plan.title
    cover.placeholders[1].text = (
        "LessonPack AI 강의 패키지\n"
        f"패키지 ID: {package.package_id}\n"
        f"프로젝트 ID: {package.project_id}"
    )

    _add_bullet_slide(presentation, "학습 목표", package.lesson_plan.learning_objectives)

    for flow in package.lesson_plan.lecture_flow:
        bullets = []
        if flow.duration_min:
            bullets.append(f"예상 시간: {flow.duration_min}분")
        bullets.append(flow.content)
        bullets.extend(_alignment_bullets(flow.ncs_alignment))
        bullets.append(f"근거: {', '.join(flow.citation_ids)}")
        _add_bullet_slide(presentation, f"교안 - {flow.section}", bullets)

    _add_bullet_slide(
        presentation,
        "실습 과제 개요",
        [
            package.practice.scenario,
            f"제출물: {package.practice.submission}",
            f"근거: {', '.join(package.practice.citation_ids)}",
        ],
    )
    _add_bullet_slide(presentation, "실습 수행 절차", package.practice.steps)
    _add_bullet_slide(presentation, "실습 루브릭", [*package.practice.rubric, *_alignment_bullets(package.practice.ncs_alignment)])

    task = package.assessment.performance_task
    _add_bullet_slide(
        presentation,
        "평가 개요",
        [
            f"객관식 문항 수: {len(package.assessment.multiple_choice)}",
            f"수행평가: {task.title}",
            task.description,
            f"근거: {', '.join(task.citation_ids)}",
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
                f"근거: {', '.join(question.citation_ids)}",
            ],
        )

    if package.review_history or package.reviewer_notes:
        _add_bullet_slide(presentation, "검수 이력", _review_bullets(package))

    _add_bullet_slide(presentation, "근거 출처", _evidence_bullets(package))

    presentation.save(output_path)
    return output_path


def _add_alignment_paragraph(document: Document, alignments: list[NCSAlignment]) -> None:
    if not alignments:
        document.add_paragraph("NCS 연계: 강사 검수 단계에서 확인 필요")
        return
    for alignment in alignments:
        criteria = "; ".join(alignment.performance_criteria) if alignment.performance_criteria else "수행준거 미기재"
        document.add_paragraph(f"NCS 연계: {alignment.unit_code} {alignment.unit_name} - {criteria}")


def _add_review_section(document: Document, package: LessonPackage) -> None:
    document.add_heading("검수 이력", level=1)
    if package.reviewer_notes:
        document.add_paragraph(f"최근 검수 메모: {package.reviewer_notes}")
    if not package.review_history:
        document.add_paragraph("검수 이력: export 시점에 저장된 이력이 없습니다.")
        return
    for event in package.review_history:
        changed = ", ".join(event.changed_fields) if event.changed_fields else "status"
        reviewer = event.reviewer_name or "미기재"
        document.add_paragraph(
            f"{event.created_at.isoformat()} | {event.from_status.value} -> {event.to_status.value} | "
            f"검수자: {reviewer} | 변경: {changed} | 메모: {event.reviewer_notes}",
            style="List Bullet",
        )


def _add_evidence_section(document: Document, package: LessonPackage) -> None:
    document.add_heading("근거 출처", level=1)
    for detail in _evidence_details(package):
        document.add_paragraph(_format_evidence_detail(detail), style="List Bullet")


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
    if package.evidence_sources:
        return package.evidence_sources
    return [
        CitationDetail(
            chunk_id=citation_id,
            source_name="출처 정보 미기재",
            excerpt="원문 발췌 정보가 패키지에 저장되어 있지 않습니다.",
        )
        for citation_id in _collect_citation_ids(package)
    ]


def _format_evidence_detail(detail: CitationDetail) -> str:
    parts = [
        detail.chunk_id,
        f"원천: {detail.source_name}",
    ]
    if detail.source_url:
        parts.append(f"URL: {detail.source_url}")
    if detail.source_file:
        parts.append(f"파일: {detail.source_file}")
    if detail.license:
        parts.append(f"라이선스: {detail.license}")
    if detail.page:
        parts.append(f"페이지: {detail.page}")
    parts.append(f"발췌: {detail.excerpt}")
    return " | ".join(parts)


def _alignment_bullets(alignments: list[NCSAlignment]) -> list[str]:
    if not alignments:
        return ["NCS 연계: 강사 검수 단계에서 확인 필요"]
    return [
        f"NCS 연계: {alignment.unit_code} {alignment.unit_name}"
        for alignment in alignments
    ]


def _review_bullets(package: LessonPackage) -> list[str]:
    bullets: list[str] = []
    if package.reviewer_notes:
        bullets.append(f"최근 검수 메모: {package.reviewer_notes}")
    for event in package.review_history[-5:]:
        reviewer = event.reviewer_name or "미기재"
        bullets.append(
            f"{event.from_status.value} -> {event.to_status.value} / 검수자: {reviewer} / 메모: {event.reviewer_notes}"
        )
    return bullets or ["검수 이력 없음"]


def _evidence_bullets(package: LessonPackage) -> list[str]:
    return [_format_evidence_detail(detail) for detail in _evidence_details(package)]


def _ensure_exportable(package: LessonPackage) -> None:
    if package.status != PackageStatus.APPROVED:
        raise ValueError("only approved packages can be exported")


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
