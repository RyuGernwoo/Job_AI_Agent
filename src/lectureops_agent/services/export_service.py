from __future__ import annotations

import io
import re
from collections import OrderedDict
from pathlib import Path

from docx import Document
from pptx import Presentation
from pptx.enum.text import MSO_AUTO_SIZE
from pptx.util import Inches, Pt

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


def export_lesson_package_pptx(
    *,
    package: LessonPackage,
    output_path: Path,
    template_content: bytes | None = None,
    layout_mapping: dict[str, int] | None = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    presentation = (
        Presentation(io.BytesIO(template_content))
        if template_content is not None
        else Presentation()
    )
    if template_content is not None:
        _remove_source_slides(presentation)
    mapping = layout_mapping or {}

    # 표지
    cover = presentation.slides.add_slide(
        _resolve_layout(presentation, mapping, "cover", fallback_index=0)
    )
    _set_slide_title(presentation, cover, package.lesson_plan.title, is_cover=True)
    training_plan = _training_plan_summary(package)
    _set_slide_bullets(
        presentation,
        cover,
        [(value, 0) for value in ["LessonPack AI 강의 패키지", training_plan] if value],
        prefer_subtitle=True,
    )

    # 학습 목표
    _add_bullet_slides(
        presentation,
        "학습 목표",
        [(objective, 0) for objective in package.lesson_plan.learning_objectives],
        semantic_type="objectives",
        layout_mapping=mapping,
    )
    if package.course_type == CourseType.GENERAL:
        _add_bullet_slides(
            presentation,
            "학습목표 · 활동 · 평가 연결",
            [
                (f"{objective} → 교안 → 실습 → 평가", 0)
                for objective in package.lesson_plan.learning_objectives
            ],
            semantic_type="objectives",
            layout_mapping=mapping,
        )

    # 교안 (섹션별, 본문을 문장 단위 불릿으로 분해해 가독성 확보)
    for flow in package.lesson_plan.lecture_flow:
        blocks: list[tuple[str, int]] = []
        if flow.duration_min:
            blocks.append((f"예상 시간 {flow.duration_min}분", 0))
        blocks.extend((sentence, 0) for sentence in _sentence_bullets(flow.content))
        blocks.extend((item, 0) for item in _alignment_bullets(flow.ncs_alignment))
        _add_bullet_slides(
            presentation,
            f"교안 · {flow.section}",
            blocks,
            semantic_type="lesson",
            layout_mapping=mapping,
        )

    # 실습
    practice = package.practice
    _add_bullet_slides(
        presentation,
        "실습 개요",
        [
            *[(s, 0) for s in _sentence_bullets(_without_label(practice.scenario, "실습 시나리오"))],
            (f"제출물: {_without_label(practice.submission, '제출물')}", 0),
        ],
        semantic_type="practice",
        layout_mapping=mapping,
    )
    _add_bullet_slides(
        presentation,
        "실습 수행 절차",
        [
            (f"{index}. {_without_label(step, '수행 절차')}", 0)
            for index, step in enumerate(practice.steps, start=1)
        ],
        semantic_type="practice",
        layout_mapping=mapping,
    )
    _add_bullet_slides(
        presentation,
        "실습 평가 기준(루브릭)",
        [
            *[(_without_label(item, "평가 기준"), 0) for item in practice.rubric],
            *[(item, 0) for item in _alignment_bullets(practice.ncs_alignment)],
        ],
        semantic_type="practice",
        layout_mapping=mapping,
    )

    # 평가 개요
    task = package.assessment.performance_task
    _add_bullet_slides(
        presentation,
        "평가 개요",
        [
            (f"객관식 문항 {len(package.assessment.multiple_choice)}개 · 수행평가 1개", 0),
            (f"수행평가: {task.title}", 0),
            *[(s, 0) for s in _sentence_bullets(task.description)],
        ],
        semantic_type="assessment",
        layout_mapping=mapping,
    )
    # 객관식 전 문항: 보기(선택지)와 정답·해설을 한 문항당 한 슬라이드로 제시한다.
    for index, question in enumerate(package.assessment.multiple_choice, start=1):
        blocks = [(question.question, 0)]
        blocks.extend(
            (f"{option_index}. {option}", 1)
            for option_index, option in enumerate(question.options, start=1)
        )
        blocks.append((f"정답: {question.answer_index + 1}번", 0))
        blocks.append((f"해설: {question.explanation}", 0))
        _add_bullet_slides(
            presentation,
            f"평가 문항 {index}",
            blocks,
            semantic_type="assessment",
            layout_mapping=mapping,
            paginate=False,
        )

    # 수행평가 상세
    _add_bullet_slides(
        presentation,
        "수행평가",
        [
            (task.title, 0),
            *[(s, 0) for s in _sentence_bullets(task.description)],
            *[(_without_label(item, "평가 기준"), 0) for item in task.rubric],
            *[(item, 0) for item in _alignment_bullets(task.ncs_alignment)],
        ],
        semantic_type="assessment",
        layout_mapping=mapping,
    )

    if package.ncs_coverage is not None:
        _add_bullet_slides(
            presentation,
            "NCS 수행준거 커버리지",
            [(bullet, 0) for bullet in _ncs_coverage_bullets(package)],
            semantic_type="ncs_coverage",
            layout_mapping=mapping,
        )

    # 근거는 발표 흐름을 방해하지 않도록 마지막 출처 슬라이드에만 표시한다.
    _add_bullet_slides(
        presentation,
        "근거 출처",
        [(bullet, 0) for bullet in _compact_evidence_bullets(package)],
        semantic_type="sources",
        layout_mapping=mapping,
    )

    presentation.save(output_path)
    _validate_exported_pptx(output_path)
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


# 한 슬라이드에 담을 최대 블록 수. autofit과 함께 가독성을 유지한다.
_SLIDE_BLOCK_CAPACITY = 8
_BODY_PLACEHOLDER_TYPES = {"BODY", "OBJECT", "SUBTITLE", "VERTICAL_BODY", "VERTICAL_OBJECT"}
# 채우지 않으면 "텍스트를 입력하십시오" 안내가 남는 placeholder 유형 (슬라이드에서 제거한다).
_REMOVABLE_PLACEHOLDER_TYPES = _BODY_PLACEHOLDER_TYPES | {"PICTURE", "CONTENT"}
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+|(?<=다\.)\s+|(?<=요\.)\s+|(?<=음\.)\s+")

Block = tuple[str, int]


def _sentence_bullets(text: str, *, max_len: int = 220) -> list[str]:
    """긴 본문 문단을 문장 단위 불릿으로 분해해 슬라이드 가독성을 높인다."""
    normalized = str(text or "").strip()
    if not normalized:
        return []
    bullets: list[str] = []
    for part in re.split(r"\n+", normalized):
        part = part.strip()
        if not part:
            continue
        buffer = ""
        for sentence in _SENTENCE_BOUNDARY.split(part):
            sentence = sentence.strip()
            if not sentence:
                continue
            if buffer and len(buffer) + len(sentence) + 1 > max_len:
                bullets.append(buffer)
                buffer = sentence
            else:
                buffer = f"{buffer} {sentence}".strip()
        if buffer:
            bullets.append(buffer)
    return bullets


def _normalize_blocks(blocks: list) -> list[Block]:
    normalized: list[Block] = []
    for block in blocks:
        text, level = block if isinstance(block, tuple) else (block, 0)
        text = " ".join(str(text).split())
        if text:
            normalized.append((text, int(level)))
    return normalized


def _add_bullet_slides(
    presentation: Presentation,
    title: str,
    bullets: list,
    *,
    semantic_type: str,
    layout_mapping: dict[str, int],
    paginate: bool = True,
) -> None:
    normalized = _normalize_blocks(bullets)
    if not normalized:
        normalized = [("내용이 없습니다.", 0)]
    if paginate:
        groups = [
            normalized[index : index + _SLIDE_BLOCK_CAPACITY]
            for index in range(0, len(normalized), _SLIDE_BLOCK_CAPACITY)
        ]
    else:
        groups = [normalized]
    for index, group in enumerate(groups):
        slide = presentation.slides.add_slide(
            _resolve_layout(presentation, layout_mapping, semantic_type, fallback_index=1)
        )
        continued_title = title if index == 0 else f"{title} (계속)"
        _set_slide_title(presentation, slide, continued_title)
        _set_slide_bullets(presentation, slide, group)


def _set_slide_title(
    presentation: Presentation,
    slide,
    title: str,
    *,
    is_cover: bool = False,
) -> None:
    if slide.shapes.title is not None:
        slide.shapes.title.text = _truncate(title, max_length=100)
        return
    box = slide.shapes.add_textbox(
        Inches(0.7),
        Inches(0.55),
        presentation.slide_width - Inches(1.4),
        Inches(1.0),
    )
    paragraph = box.text_frame.paragraphs[0]
    paragraph.text = _truncate(title, max_length=100)
    paragraph.font.size = Pt(30 if is_cover else 26)
    paragraph.font.bold = True


def _set_slide_bullets(
    presentation: Presentation,
    slide,
    bullets: list,
    *,
    prefer_subtitle: bool = False,
) -> None:
    body = _prepare_body_frame(slide, prefer_subtitle=prefer_subtitle)
    fallback_font = body is None
    if body is None:
        box = slide.shapes.add_textbox(
            Inches(0.8),
            Inches(1.6),
            presentation.slide_width - Inches(1.6),
            presentation.slide_height - Inches(2.2),
        )
        body = box.text_frame
    body.word_wrap = True
    try:
        # 본문이 넘칠 경우 자동으로 글자 크기를 줄여 잘림을 방지한다.
        body.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    except (ValueError, NotImplementedError):
        pass
    body.clear()
    for index, (text, level) in enumerate(_normalize_blocks(bullets)):
        paragraph = body.paragraphs[0] if index == 0 else body.add_paragraph()
        paragraph.text = _truncate(text, max_length=500)
        paragraph.level = min(max(level, 0), 4)
        if fallback_font:
            paragraph.font.size = Pt(18 if level == 0 else 16)


def _prepare_body_frame(slide, *, prefer_subtitle: bool):
    """본문 placeholder를 하나 선택하고, 나머지 빈 본문 placeholder는 제거해 깔끔한 슬라이드를 만든다."""
    title_shape = slide.shapes.title
    candidates: list[tuple[str, object]] = []
    for placeholder in list(slide.placeholders):
        if title_shape is not None and placeholder is title_shape:
            continue
        placeholder_type = getattr(
            placeholder.placeholder_format.type,
            "name",
            str(placeholder.placeholder_format.type),
        )
        candidates.append((placeholder_type, placeholder))

    preferred = (
        {"SUBTITLE"}
        if prefer_subtitle
        else {"BODY", "OBJECT", "VERTICAL_BODY", "VERTICAL_OBJECT"}
    )
    chosen = None
    for placeholder_type, placeholder in candidates:
        if placeholder.has_text_frame and placeholder_type in preferred:
            chosen = placeholder
            break
    if chosen is None:
        for placeholder_type, placeholder in candidates:
            if placeholder.has_text_frame and placeholder_type in _BODY_PLACEHOLDER_TYPES:
                chosen = placeholder
                break

    for placeholder_type, placeholder in candidates:
        if placeholder is chosen:
            continue
        if placeholder_type in _REMOVABLE_PLACEHOLDER_TYPES:
            element = placeholder._element
            element.getparent().remove(element)

    return chosen.text_frame if chosen is not None else None


def _resolve_layout(
    presentation: Presentation,
    layout_mapping: dict[str, int],
    semantic_type: str,
    *,
    fallback_index: int,
):
    if not presentation.slide_layouts:
        raise ValueError("PPT presentation does not contain any slide layouts")
    layout_index = layout_mapping.get(semantic_type, fallback_index)
    if layout_index < 0 or layout_index >= len(presentation.slide_layouts):
        layout_index = min(fallback_index, len(presentation.slide_layouts) - 1)
    return presentation.slide_layouts[layout_index]


def _remove_source_slides(presentation: Presentation) -> None:
    slide_ids = presentation.slides._sldIdLst
    for slide_id in list(slide_ids):
        presentation.part.drop_rel(slide_id.rId)
        slide_ids.remove(slide_id)


def _validate_exported_pptx(output_path: Path) -> None:
    try:
        exported = Presentation(str(output_path))
    except Exception as exc:
        raise ValueError("Generated PPTX could not be reopened.") from exc
    if not exported.slides:
        raise ValueError("Generated PPTX does not contain any slides.")
    final_slide_text = [
        shape.text
        for shape in exported.slides[-1].shapes
        if hasattr(shape, "text")
    ]
    if "근거 출처" not in final_slide_text:
        raise ValueError("Generated PPTX is missing the final evidence slide.")


def _truncate(value: str, max_length: int = 180) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 3].rstrip() + "..."
