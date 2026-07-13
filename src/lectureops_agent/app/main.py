import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from lectureops_agent.models.schemas import (
    GenerateRequest,
    LessonPackage,
    MaterialChunk,
    MaterialIngestResult,
    Project,
    ProjectCreate,
    RetrieveRequest,
    ReviewPatch,
)
from lectureops_agent.services.chunk_service import chunk_text
from lectureops_agent.services.export_service import export_lesson_package_docx
from lectureops_agent.services.generation_service import generate_lesson_package
from lectureops_agent.services.parser_service import decode_text_material
from lectureops_agent.services.review_service import apply_review_patch
from lectureops_agent.services.vector_store import VectorStore, create_vector_store_from_env

CHUNK_SIZE_CHARS = 800
CHUNK_OVERLAP_CHARS = 120
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def create_app(vector_store: VectorStore | None = None) -> FastAPI:
    app = FastAPI(
        title="LectureOps Agent",
        description="Job training lecture operation assistant AI Agent MVP",
        version="0.1.0",
    )
    projects: dict[str, Project] = {}
    vector_store = vector_store or create_vector_store_from_env()
    project_document_counts: dict[str, int] = {}
    packages: dict[str, LessonPackage] = {}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "lectureops-agent"}

    @app.post("/api/projects", response_model=Project)
    def create_project(payload: ProjectCreate) -> Project:
        project = payload.to_project()
        projects[project.project_id] = project
        project_document_counts[project.project_id] = 0
        return project

    @app.post("/api/projects/{project_id}/materials", response_model=MaterialIngestResult)
    async def upload_material(project_id: str, file: UploadFile = File(...)) -> MaterialIngestResult:
        project = projects.get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        content = await file.read()
        try:
            text, source_type = decode_text_material(file.filename or "uploaded.txt", content)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        project_document_counts[project_id] += 1
        document_id = f"doc{project_document_counts[project_id]:03d}"
        chunks = chunk_text(
            project_id=project_id,
            document_id=document_id,
            source_name=file.filename or "uploaded.txt",
            source_type=source_type,
            text=text,
            chunk_size_chars=CHUNK_SIZE_CHARS,
            chunk_overlap_chars=CHUNK_OVERLAP_CHARS,
            metadata={"content_type": file.content_type or "application/octet-stream"},
        )
        vector_store.upsert(project_id=project_id, chunks=chunks)
        return MaterialIngestResult(
            project_id=project_id,
            document_id=document_id,
            source_name=file.filename or "uploaded.txt",
            source_type=source_type,
            chunk_count=len(chunks),
            chunks=chunks,
        )

    @app.post("/api/projects/{project_id}/retrieve", response_model=list[MaterialChunk])
    def retrieve(project_id: str, payload: RetrieveRequest) -> list[MaterialChunk]:
        project = projects.get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        try:
            return vector_store.query(project_id=project_id, query=payload.query, top_k=payload.top_k)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/generate", response_model=LessonPackage)
    def generate(project_id: str, payload: GenerateRequest) -> LessonPackage:
        project = projects.get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        package = generate_lesson_package(project=project, retrieved_chunks=payload.retrieved_chunks)
        packages[package.package_id] = package
        return package

    @app.get("/api/packages/{package_id}", response_model=LessonPackage)
    def get_package(package_id: str) -> LessonPackage:
        package = packages.get(package_id)
        if package is None:
            raise HTTPException(status_code=404, detail="package not found")
        return package

    @app.patch("/api/packages/{package_id}/review", response_model=LessonPackage)
    def review_package(package_id: str, payload: ReviewPatch) -> LessonPackage:
        package = packages.get(package_id)
        if package is None:
            raise HTTPException(status_code=404, detail="package not found")
        try:
            updated = apply_review_patch(package, payload)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        packages[package_id] = updated
        return updated

    @app.get("/api/packages/{package_id}/export.docx")
    def export_docx(package_id: str) -> FileResponse:
        package = packages.get(package_id)
        if package is None:
            raise HTTPException(status_code=404, detail="package not found")
        output_path = Path(tempfile.gettempdir()) / "lectureops_agent_exports" / f"{package_id}.docx"
        try:
            export_lesson_package_docx(package=package, output_path=output_path)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return FileResponse(
            path=output_path,
            media_type=DOCX_MEDIA_TYPE,
            filename=f"{package_id}.docx",
        )

    return app


app = create_app()
