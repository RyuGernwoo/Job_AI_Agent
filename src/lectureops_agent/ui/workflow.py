"""UI workflow helpers shared by Streamlit and tests."""

from dataclasses import dataclass

from lectureops_agent.models.schemas import LessonPackage, MaterialChunk, PackageStatus, Project, ProjectCreate
from lectureops_agent.services.chunk_service import chunk_text
from lectureops_agent.services.generation_service import generate_lesson_package
from lectureops_agent.services.retrieval_service import retrieve_chunks

DEFAULT_CHUNK_SIZE_CHARS = 800
DEFAULT_CHUNK_OVERLAP_CHARS = 120


@dataclass(frozen=True)
class UiWorkflowResult:
    project: Project
    chunks: list[MaterialChunk]
    retrieved_chunks: list[MaterialChunk]
    package: LessonPackage


def parse_multiline_items(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def run_text_material_workflow(
    *,
    project_input: ProjectCreate,
    material_name: str,
    source_type: str,
    text: str,
    retrieval_query: str,
    top_k: int,
) -> UiWorkflowResult:
    project = project_input.to_project()
    chunks = chunk_text(
        project_id=project.project_id,
        document_id="doc001",
        source_name=material_name,
        source_type=source_type,
        text=text,
        chunk_size_chars=DEFAULT_CHUNK_SIZE_CHARS,
        chunk_overlap_chars=DEFAULT_CHUNK_OVERLAP_CHARS,
        metadata={"created_by": "streamlit_ui"},
    )
    retrieved_chunks = retrieve_chunks(query=retrieval_query, chunks=chunks, top_k=top_k)
    if not retrieved_chunks:
        raise ValueError("retrieval returned no chunks; adjust the query or upload richer material")
    package = generate_lesson_package(project=project, retrieved_chunks=retrieved_chunks)
    return UiWorkflowResult(project=project, chunks=chunks, retrieved_chunks=retrieved_chunks, package=package)


def approve_package(package: LessonPackage) -> LessonPackage:
    return package.model_copy(update={"status": PackageStatus.APPROVED})


def mark_reviewed(package: LessonPackage) -> LessonPackage:
    return package.model_copy(update={"status": PackageStatus.REVIEWED})
