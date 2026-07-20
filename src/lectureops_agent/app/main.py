import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from lectureops_agent.config import LessonPackConfig, load_config
from lectureops_agent.env import load_env_file
from lectureops_agent.models.schemas import (
    GenerateRequest,
    GenerationLog,
    LessonPackage,
    MaterialChunk,
    MaterialIngestResult,
    PackageEditPatch,
    Project,
    ProjectCreate,
    RetrieveRequest,
    ReviewEvent,
    ReviewPatch,
)
from lectureops_agent.services.chunk_service import chunk_text
from lectureops_agent.services.export_service import export_lesson_package_docx, export_lesson_package_pptx
from lectureops_agent.services.generation_service import generate_lesson_package_with_log
from lectureops_agent.services.llm_provider import LLMProvider, create_llm_provider_from_config, create_llm_provider_from_env
from lectureops_agent.services.parser_service import decode_text_material
from lectureops_agent.services.review_service import apply_package_edit, apply_review_patch
from lectureops_agent.services.vector_store import VectorStore, create_vector_store_from_config, create_vector_store_from_env

CHUNK_SIZE_CHARS = 800
CHUNK_OVERLAP_CHARS = 120
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
DEFAULT_CORS_ALLOW_ORIGINS = (
    "https://7f62cef5-bc4c-473e-a8d2-5f1847df5736.lovableproject.com",
    "https://id-preview--7f62cef5-bc4c-473e-a8d2-5f1847df5736.lovable.app",
    "https://lessonpack-ai.lovable.app",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


def create_app(
    vector_store: VectorStore | None = None,
    llm_provider: LLMProvider | None = None,
    app_config: LessonPackConfig | None = None,
) -> FastAPI:
    load_env_file()
    app = FastAPI(
        title="LessonPack AI",
        description="Job training lesson package generation assistant MVP",
        version="0.1.0",
    )
    _configure_cors(app)
    config = app_config or _load_config_from_env()
    chunk_size_chars = config.chunk_size_chars if config else CHUNK_SIZE_CHARS
    chunk_overlap_chars = config.chunk_overlap_chars if config else CHUNK_OVERLAP_CHARS
    projects: dict[str, Project] = {}
    vector_store = vector_store or (create_vector_store_from_config(config.vector_store) if config else create_vector_store_from_env())
    if llm_provider is None:
        llm_provider = create_llm_provider_from_config(config) if config else create_llm_provider_from_env()
    project_document_counts: dict[str, int] = {}
    packages: dict[str, LessonPackage] = {}
    generation_logs: dict[str, GenerationLog] = {}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "lessonpack-ai"}

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
            chunk_size_chars=chunk_size_chars,
            chunk_overlap_chars=chunk_overlap_chars,
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

        result = generate_lesson_package_with_log(
            project=project,
            retrieved_chunks=payload.retrieved_chunks,
            llm_provider=llm_provider,
        )
        packages[result.package.package_id] = result.package
        generation_logs[result.package.package_id] = result.log
        return result.package

    @app.get("/api/packages/{package_id}", response_model=LessonPackage)
    def get_package(package_id: str) -> LessonPackage:
        package = packages.get(package_id)
        if package is None:
            raise HTTPException(status_code=404, detail="package not found")
        return package

    @app.get("/api/packages/{package_id}/generation-log", response_model=GenerationLog)
    def get_generation_log(package_id: str) -> GenerationLog:
        log = generation_logs.get(package_id)
        if log is None:
            raise HTTPException(status_code=404, detail="generation log not found")
        return log

    @app.patch("/api/packages/{package_id}", response_model=LessonPackage)
    def edit_package(package_id: str, payload: PackageEditPatch) -> LessonPackage:
        package = packages.get(package_id)
        if package is None:
            raise HTTPException(status_code=404, detail="package not found")
        try:
            updated = apply_package_edit(package, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        packages[package_id] = updated
        return updated

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

    @app.get("/api/packages/{package_id}/review-history", response_model=list[ReviewEvent])
    def get_review_history(package_id: str) -> list[ReviewEvent]:
        package = packages.get(package_id)
        if package is None:
            raise HTTPException(status_code=404, detail="package not found")
        return package.review_history

    @app.get("/api/packages/{package_id}/export.docx")
    def export_docx(package_id: str) -> FileResponse:
        package = packages.get(package_id)
        if package is None:
            raise HTTPException(status_code=404, detail="package not found")
        output_path = Path(tempfile.gettempdir()) / "lessonpack_ai_exports" / f"{package_id}.docx"
        try:
            export_lesson_package_docx(package=package, output_path=output_path)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return FileResponse(
            path=output_path,
            media_type=DOCX_MEDIA_TYPE,
            filename=f"{package_id}.docx",
        )

    @app.get("/api/packages/{package_id}/export.pptx")
    def export_pptx(package_id: str) -> FileResponse:
        package = packages.get(package_id)
        if package is None:
            raise HTTPException(status_code=404, detail="package not found")
        output_path = Path(tempfile.gettempdir()) / "lessonpack_ai_exports" / f"{package_id}.pptx"
        try:
            export_lesson_package_pptx(package=package, output_path=output_path)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return FileResponse(
            path=output_path,
            media_type=PPTX_MEDIA_TYPE,
            filename=f"{package_id}.pptx",
        )

    return app


def _configure_cors(app: FastAPI) -> None:
    allow_origins = _cors_allow_origins_from_env()
    if not allow_origins:
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=_env_flag("LESSONPACK_CORS_ALLOW_CREDENTIALS", default=False),
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )


def _cors_allow_origins_from_env() -> list[str]:
    value = os.getenv("LESSONPACK_CORS_ALLOW_ORIGINS")
    if value is None:
        return list(DEFAULT_CORS_ALLOW_ORIGINS)
    return [origin.strip() for origin in value.split(",") if origin.strip()]


def _env_flag(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def _load_config_from_env() -> LessonPackConfig | None:
    config_path = os.getenv("LESSONPACK_CONFIG")
    if not config_path:
        return None
    return load_config(config_path)

app = create_app()
