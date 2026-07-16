from pathlib import Path

from docx import Document
from pptx import Presentation

from lectureops_agent.models.schemas import LessonPackage, PackageStatus


def export_lesson_package_docx(*, package: LessonPackage, output_path: Path) -> Path:
    _ensure_exportable(package)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    document = Document()
    document.add_heading(package.lesson_plan.title, level=0)
    document.add_paragraph(f"Package ID: {package.package_id}")
    document.add_paragraph(f"Project ID: {package.project_id}")
    document.add_paragraph(f"Status: {package.status.value}")

    document.add_heading("Learning Objectives", level=1)
    for objective in package.lesson_plan.learning_objectives:
        document.add_paragraph(objective, style="List Bullet")

    document.add_heading("Lesson Plan", level=1)
    for flow in package.lesson_plan.lecture_flow:
        document.add_heading(flow.section, level=2)
        document.add_paragraph(flow.content)
        document.add_paragraph(f"Citations: {', '.join(flow.citation_ids)}")

    document.add_heading("Practice", level=1)
    document.add_paragraph(package.practice.scenario)
    document.add_heading("Practice Steps", level=2)
    for step in package.practice.steps:
        document.add_paragraph(step, style="List Number")
    document.add_paragraph(f"Submission: {package.practice.submission}")
    document.add_heading("Practice Rubric", level=2)
    for item in package.practice.rubric:
        document.add_paragraph(item, style="List Bullet")
    document.add_paragraph(f"Citations: {', '.join(package.practice.citation_ids)}")

    document.add_heading("Assessment", level=1)
    for index, question in enumerate(package.assessment.multiple_choice, start=1):
        document.add_paragraph(f"Q{index}. {question.question}")
        for option_index, option in enumerate(question.options, start=1):
            document.add_paragraph(f"{option_index}. {option}", style="List Bullet")
        document.add_paragraph(f"Answer: {question.answer_index + 1}")
        document.add_paragraph(f"Explanation: {question.explanation}")
        document.add_paragraph(f"Citations: {', '.join(question.citation_ids)}")

    task = package.assessment.performance_task
    document.add_heading("Performance Task", level=2)
    document.add_paragraph(task.title)
    document.add_paragraph(task.description)
    for item in task.rubric:
        document.add_paragraph(item, style="List Bullet")
    document.add_paragraph(f"Citations: {', '.join(task.citation_ids)}")

    citation_ids = _collect_citation_ids(package)
    document.add_heading("Evidence Sources", level=1)
    for citation_id in citation_ids:
        document.add_paragraph(citation_id, style="List Bullet")

    document.save(output_path)
    return output_path


def export_lesson_package_pptx(*, package: LessonPackage, output_path: Path) -> Path:
    _ensure_exportable(package)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    presentation = Presentation()

    cover = presentation.slides.add_slide(presentation.slide_layouts[0])
    cover.shapes.title.text = package.lesson_plan.title
    cover.placeholders[1].text = (
        "LessonPack AI generated lesson package\n"
        f"Package ID: {package.package_id}\n"
        f"Project ID: {package.project_id}"
    )

    _add_bullet_slide(
        presentation,
        "Learning Objectives",
        package.lesson_plan.learning_objectives,
    )

    for flow in package.lesson_plan.lecture_flow:
        bullets = [_truncate(flow.content), f"Citations: {', '.join(flow.citation_ids)}"]
        if flow.duration_min:
            bullets.insert(0, f"Duration: {flow.duration_min} min")
        _add_bullet_slide(presentation, f"Lesson Plan - {flow.section}", bullets)

    _add_bullet_slide(
        presentation,
        "Practice",
        [
            _truncate(package.practice.scenario),
            *package.practice.steps,
            f"Submission: {package.practice.submission}",
            f"Citations: {', '.join(package.practice.citation_ids)}",
        ],
    )

    task = package.assessment.performance_task
    _add_bullet_slide(
        presentation,
        "Assessment",
        [
            f"Multiple choice questions: {len(package.assessment.multiple_choice)}",
            f"Performance task: {task.title}",
            _truncate(task.description),
            f"Citations: {', '.join(task.citation_ids)}",
        ],
    )

    _add_bullet_slide(presentation, "Evidence Sources", _collect_citation_ids(package))

    presentation.save(output_path)
    return output_path


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


def _ensure_exportable(package: LessonPackage) -> None:
    if package.status != PackageStatus.APPROVED:
        raise ValueError("only approved packages can be exported")


def _add_bullet_slide(presentation: Presentation, title: str, bullets: list[str]) -> None:
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = title
    body = slide.placeholders[1].text_frame
    body.clear()
    for index, bullet in enumerate(bullets):
        paragraph = body.paragraphs[0] if index == 0 else body.add_paragraph()
        paragraph.text = _truncate(bullet)
        paragraph.level = 0


def _truncate(value: str, max_length: int = 240) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 3].rstrip() + "..."
