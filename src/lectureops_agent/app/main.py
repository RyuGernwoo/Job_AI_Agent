import hashlib
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from lectureops_agent.config import LessonPackConfig, load_config
from lectureops_agent.env import load_env_file
from lectureops_agent.models.schemas import (
    CourseType,
    GenerateRequest,
    GenerationLog,
    GenerationRun,
    LessonPackage,
    MaterialChunk,
    MaterialDocument,
    MaterialIngestResult,
    NCSCatalogUnit,
    NCSCoverageReport,
    NCSSourceStatus,
    NCSUnit,
    PackageRegenerateRequest,
    PackageRegenerateResponse,
    Project,
    ProjectCreate,
    RAGGenerateRequest,
    RAGGenerateResponse,
    RAGRetrieveRequest,
    RAGRetrieveResponse,
    RetrieveRequest,
    RetrievedEvidence,
    RetrievalRun,
)
from lectureops_agent.services.chunk_service import chunk_text
from lectureops_agent.services.export_service import (
    build_export_filename,
    export_lesson_package_docx,
    export_lesson_package_pptx,
)
from lectureops_agent.services.generation_service import generate_lesson_package_with_log
from lectureops_agent.services.llm_provider import (
    LLMProvider,
    create_llm_provider_from_config,
    create_llm_provider_from_env,
    llm_trace_context,
)
from lectureops_agent.services.parser_service import decode_text_material
from lectureops_agent.services.rag_repository import (
    RAGRepository,
    create_rag_repository_for_vector_store,
)
from lectureops_agent.services.rag_service import (
    retrieve_evidence,
    retrieve_evidence_for_queries,
    retrieval_response,
)
from lectureops_agent.services.vector_store import (
    VectorStore,
    create_vector_store_from_config,
    create_vector_store_from_env,
)

CHUNK_SIZE_CHARS = 800
CHUNK_OVERLAP_CHARS = 120
DEFAULT_MAX_UPLOAD_MB = 20
UPLOAD_READ_CHUNK_BYTES = 1024 * 1024
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
logger = logging.getLogger(__name__)
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
    rag_repository: RAGRepository | None = None,
) -> FastAPI:
    load_env_file()
    explicit_app_config = app_config is not None
    app = FastAPI(
        title="LessonPack AI",
        description="Job training lesson package generation assistant MVP",
        version="0.1.0",
    )
    _configure_cors(app)

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(request: Request, exc: Exception) -> JSONResponse:
        # FastAPI's ServerErrorMiddleware is outside user middleware, so its
        # fallback response must carry CORS headers explicitly.
        logger.exception("Unhandled API exception", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "An unexpected server error occurred. Please try again shortly."},
            headers=_cors_response_headers(request),
        )

    config = app_config or _load_config_from_env()
    chunk_size_chars = config.chunk_size_chars if config else CHUNK_SIZE_CHARS
    chunk_overlap_chars = config.chunk_overlap_chars if config else CHUNK_OVERLAP_CHARS
    max_upload_mb = _runtime_int(
        "LESSONPACK_MAX_UPLOAD_MB",
        config.max_upload_mb if config else DEFAULT_MAX_UPLOAD_MB,
    )
    max_upload_bytes = max_upload_mb * 1024 * 1024
    retrieval_top_k = _runtime_int(
        "LESSONPACK_RETRIEVAL_TOP_K",
        config.retrieval_top_k if config else 5,
    )
    candidate_k = _runtime_int(
        "LESSONPACK_RETRIEVAL_CANDIDATE_K",
        config.vector_store.candidate_k if config else 20,
    )
    baseline_project_id = os.getenv(
        "LESSONPACK_BASELINE_PROJECT_ID",
        config.vector_store.baseline_project_id if config else "mvp-dataset",
    )
    vector_store = vector_store or _create_runtime_vector_store(
        config,
        allow_env_override=not explicit_app_config,
    )
    rag_repository = rag_repository or create_rag_repository_for_vector_store(vector_store)
    if llm_provider is None:
        llm_provider = create_llm_provider_from_config(config) if config else create_llm_provider_from_env()

    packages: dict[str, LessonPackage] = {}
    generation_logs: dict[str, GenerationLog] = {}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "lessonpack-ai"}

    @app.get("/health/rag")
    def rag_health() -> dict:
        persistence = rag_repository.readiness()
        return {
            "status": "ok" if persistence["ready"] else "not_ready",
            "vector_store": type(vector_store).__name__,
            "repository": type(rag_repository).__name__,
            "baseline_project_id": baseline_project_id,
            "retrieval_top_k": retrieval_top_k,
            "persistence": persistence,
        }

    @app.get("/api/ncs/catalog/search", response_model=list[NCSCatalogUnit])
    def search_ncs_catalog(
        q: str = Query(min_length=2, max_length=100),
        limit: int = Query(default=10, ge=1, le=30),
    ) -> list[NCSCatalogUnit]:
        try:
            return rag_repository.search_ncs_catalog(q, limit=limit)
        except Exception as exc:
            logger.exception("NCS catalog search failed")
            raise HTTPException(
                status_code=503,
                detail="NCS catalog search is temporarily unavailable.",
            ) from exc

    @app.get("/api/ncs/catalog/{unit_code}", response_model=NCSCatalogUnit)
    def get_ncs_catalog_unit(unit_code: str) -> NCSCatalogUnit:
        try:
            unit = rag_repository.get_ncs_catalog_unit(unit_code)
        except Exception as exc:
            logger.exception("NCS catalog lookup failed")
            raise HTTPException(
                status_code=503,
                detail="NCS catalog lookup is temporarily unavailable.",
            ) from exc
        if unit is None:
            raise HTTPException(status_code=404, detail="NCS unit not found")
        return unit

    @app.post("/api/projects", response_model=Project)
    def create_project(payload: ProjectCreate) -> Project:
        payload = _resolve_verified_ncs_units(payload=payload, repository=rag_repository)
        project = payload.to_project()
        try:
            rag_repository.save_project(project)
        except Exception as exc:
            # PostgREST raises APIError rather than RuntimeError for schema and
            # connectivity failures.  Do not expose it as an unhandled 500.
            logger.exception("Project persistence failed")
            raise HTTPException(
                status_code=503,
                detail="Project persistence is temporarily unavailable. Please try again shortly.",
            ) from exc
        return project

    @app.post("/api/projects/{project_id}/materials", response_model=MaterialIngestResult)
    async def upload_material(project_id: str, file: UploadFile = File(...)) -> MaterialIngestResult:
        _require_project(rag_repository, project_id)
        content = await _read_upload_content(
            file,
            max_upload_bytes=max_upload_bytes,
            max_upload_mb=max_upload_mb,
        )
        try:
            text, source_type = decode_text_material(file.filename or "uploaded.txt", content)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        document_id = rag_repository.next_document_id(project_id)
        metadata = {
            "content_type": file.content_type or "application/octet-stream",
            "evidence_origin": "user_upload",
            "evidence_authority": "user_provided",
        }
        chunks = chunk_text(
            project_id=project_id,
            document_id=document_id,
            source_name=file.filename or "uploaded.txt",
            source_type=source_type,
            text=text,
            chunk_size_chars=chunk_size_chars,
            chunk_overlap_chars=chunk_overlap_chars,
            metadata=metadata,
        )
        try:
            vector_store.upsert(project_id=project_id, chunks=chunks)
            rag_repository.save_document(
                MaterialDocument(
                    document_id=document_id,
                    project_id=project_id,
                    source_name=file.filename or "uploaded.txt",
                    source_type=source_type,
                    content_hash=hashlib.sha256(content).hexdigest(),
                    chunk_count=len(chunks),
                    metadata=metadata,
                    created_at=datetime.now(timezone.utc),
                )
            )
        except Exception as exc:
            logger.exception("Material indexing failed for project %s", project_id)
            raise HTTPException(
                status_code=503,
                detail="Material indexing is temporarily unavailable. Please try again shortly.",
            ) from exc
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
        _require_project(rag_repository, project_id)
        try:
            return vector_store.query(project_id=project_id, query=payload.query, top_k=payload.top_k)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/rag/retrieve", response_model=RAGRetrieveResponse)
    def rag_retrieve(project_id: str, payload: RAGRetrieveRequest) -> RAGRetrieveResponse:
        project = _require_project(rag_repository, project_id)
        run = _retrieve_for_request(
            project=project,
            query=payload.query,
            top_k=payload.top_k or retrieval_top_k,
            include_baseline=payload.include_baseline,
            vector_store=vector_store,
            rag_repository=rag_repository,
            candidate_k=candidate_k,
            baseline_project_id=baseline_project_id,
        )
        return retrieval_response(run)

    @app.get("/api/retrieval-runs/{run_id}", response_model=RetrievalRun)
    def get_retrieval_run(run_id: str) -> RetrievalRun:
        try:
            run = rag_repository.get_retrieval_run(run_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if run is None:
            raise HTTPException(status_code=404, detail="retrieval run not found")
        return run

    @app.post("/api/projects/{project_id}/rag/generate", response_model=RAGGenerateResponse)
    def rag_generate(project_id: str, payload: RAGGenerateRequest) -> RAGGenerateResponse:
        project = _require_project(rag_repository, project_id)
        if payload.retrieval_run_id is not None:
            retrieval_run = _require_retrieval_run(
                repository=rag_repository,
                run_id=payload.retrieval_run_id,
                project_id=project_id,
            )
            selected_evidence = _select_retrieval_evidence(
                retrieval_run,
                selected_chunk_ids=payload.selected_chunk_ids,
            )
        elif payload.queries is not None:
            retrieval_run = _retrieve_for_queries(
                project=project,
                queries=payload.queries,
                top_k=payload.top_k or retrieval_top_k,
                include_baseline=payload.include_baseline,
                vector_store=vector_store,
                rag_repository=rag_repository,
                candidate_k=candidate_k,
                baseline_project_id=baseline_project_id,
            )
            selected_evidence = retrieval_run.evidence
        else:
            if payload.query is None:
                raise HTTPException(
                    status_code=422,
                    detail="exactly one of query, queries, or retrieval_run_id is required",
                )
            retrieval_run = _retrieve_for_request(
                project=project,
                query=payload.query,
                top_k=payload.top_k or retrieval_top_k,
                include_baseline=payload.include_baseline,
                vector_store=vector_store,
                rag_repository=rag_repository,
                candidate_k=candidate_k,
                baseline_project_id=baseline_project_id,
            )
            selected_evidence = retrieval_run.evidence
        if not selected_evidence:
            raise HTTPException(
                status_code=422,
                detail="검색 근거가 없습니다. 자료를 추가하거나 질의를 구체화하십시오.",
            )
        _validate_ncs_generation_evidence(project, selected_evidence)

        with llm_trace_context(
            {
                "trace_id": retrieval_run.trace_id,
                "retrieval_run_id": retrieval_run.run_id,
                "project_id": project_id,
                "course_type": project.course_type.value,
                "ncs_unit_codes": [unit.unit_code for unit in project.ncs_units],
            }
        ):
            result = generate_lesson_package_with_log(
                project=project,
                retrieved_chunks=[item.chunk for item in selected_evidence],
                llm_provider=llm_provider,
                retrieval_run_id=retrieval_run.run_id,
                trace_id=retrieval_run.trace_id,
            )
        packages[result.package.package_id] = result.package
        generation_logs[result.package.package_id] = result.log
        try:
            rag_repository.save_generation_run(
                GenerationRun(
                    package_id=result.package.package_id,
                    project_id=project_id,
                    retrieval_run_id=retrieval_run.run_id,
                    trace_id=retrieval_run.trace_id,
                    provider_name=result.log.provider_name,
                    structured_output_applied=result.log.structured_output_applied,
                    citation_ids=result.log.citation_ids,
                    created_at=result.log.created_at,
                )
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return RAGGenerateResponse(
            package=result.package,
            retrieval_run_id=retrieval_run.run_id,
            trace_id=retrieval_run.trace_id,
        )

    @app.post("/api/projects/{project_id}/generate", response_model=LessonPackage)
    def generate(project_id: str, payload: GenerateRequest) -> LessonPackage:
        project = _require_project(rag_repository, project_id)
        _validate_ncs_generation_chunks(project, payload.retrieved_chunks)
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

    @app.get(
        "/api/projects/{project_id}/ncs-coverage",
        response_model=NCSCoverageReport,
    )
    def get_project_ncs_coverage(project_id: str) -> NCSCoverageReport:
        project = _require_project(rag_repository, project_id)
        if project.course_type != CourseType.NCS:
            raise HTTPException(status_code=409, detail="NCS coverage is available only for NCS courses")
        package = next(
            (
                item
                for item in reversed(list(packages.values()))
                if item.project_id == project_id and item.ncs_coverage is not None
            ),
            None,
        )
        if package is None or package.ncs_coverage is None:
            raise HTTPException(status_code=404, detail="NCS coverage report not found")
        return package.ncs_coverage

    @app.get("/api/packages/{package_id}/generation-log", response_model=GenerationLog)
    def get_generation_log(package_id: str) -> GenerationLog:
        log = generation_logs.get(package_id)
        if log is None:
            raise HTTPException(status_code=404, detail="generation log not found")
        return log

    @app.post("/api/packages/{package_id}/regenerate", response_model=PackageRegenerateResponse)
    def regenerate_package(
        package_id: str,
        payload: PackageRegenerateRequest,
    ) -> PackageRegenerateResponse:
        source_package = packages.get(package_id)
        if source_package is None:
            raise HTTPException(status_code=404, detail="package not found")
        project = _require_project(rag_repository, source_package.project_id)
        retrieval_run = _retrieve_for_request(
            project=project,
            query=payload.instruction,
            top_k=payload.top_k or retrieval_top_k,
            include_baseline=payload.include_baseline,
            vector_store=vector_store,
            rag_repository=rag_repository,
            candidate_k=candidate_k,
            baseline_project_id=baseline_project_id,
        )
        if not retrieval_run.evidence:
            raise HTTPException(
                status_code=422,
                detail="수정 요청을 뒷받침할 검색 근거가 없습니다. 자료를 추가하거나 요청을 구체화하십시오.",
            )
        _validate_ncs_generation_evidence(project, retrieval_run.evidence)
        revision_chunks = _merge_revision_evidence_chunks(
            source_package=source_package,
            retrieved_chunks=[item.chunk for item in retrieval_run.evidence],
            project_id=project.project_id,
        )

        try:
            with llm_trace_context(
                {
                    "trace_id": retrieval_run.trace_id,
                    "retrieval_run_id": retrieval_run.run_id,
                    "project_id": project.project_id,
                    "source_package_id": source_package.package_id,
                    "course_type": project.course_type.value,
                    "ncs_unit_codes": [unit.unit_code for unit in project.ncs_units],
                }
            ):
                result = generate_lesson_package_with_log(
                    project=project,
                    retrieved_chunks=revision_chunks,
                    llm_provider=llm_provider,
                    retrieval_run_id=retrieval_run.run_id,
                    trace_id=retrieval_run.trace_id,
                    source_package=source_package,
                    revision_instruction=payload.instruction,
                )
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Lesson package regeneration failed")
            raise HTTPException(
                status_code=502,
                detail="Lesson package regeneration is temporarily unavailable. Please try again shortly.",
            ) from exc

        packages[result.package.package_id] = result.package
        generation_logs[result.package.package_id] = result.log
        try:
            rag_repository.save_generation_run(
                GenerationRun(
                    package_id=result.package.package_id,
                    project_id=project.project_id,
                    retrieval_run_id=retrieval_run.run_id,
                    trace_id=retrieval_run.trace_id,
                    provider_name=result.log.provider_name,
                    structured_output_applied=result.log.structured_output_applied,
                    citation_ids=result.log.citation_ids,
                    created_at=result.log.created_at,
                )
            )
        except Exception as exc:
            logger.exception("Regenerated package persistence failed")
            raise HTTPException(
                status_code=503,
                detail="Package persistence is temporarily unavailable. Please try again shortly.",
            ) from exc
        return PackageRegenerateResponse(
            package=result.package,
            source_package_id=source_package.package_id,
            retrieval_run_id=retrieval_run.run_id,
            trace_id=retrieval_run.trace_id,
        )

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
            filename=build_export_filename(package, "docx"),
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
            filename=build_export_filename(package, "pptx"),
        )

    return app


def _merge_revision_evidence_chunks(
    *,
    source_package: LessonPackage,
    retrieved_chunks: list[MaterialChunk],
    project_id: str,
) -> list[MaterialChunk]:
    """Make original citations available while adding evidence found for the edit request."""
    merged: list[MaterialChunk] = []
    seen: set[str] = set()
    for index, citation in enumerate(source_package.evidence_sources, start=1):
        if citation.chunk_id in seen:
            continue
        source_type = _revision_source_type(citation.source_file or citation.source_name)
        merged.append(
            MaterialChunk(
                chunk_id=citation.chunk_id,
                project_id=project_id,
                document_id=f"revision-source-{index:03d}",
                source_name=citation.source_name,
                source_type=source_type,
                page=citation.page,
                text=citation.excerpt,
                metadata={
                    key: value
                    for key, value in {
                        "source_url": citation.source_url,
                        "license": citation.license,
                        "source_file": citation.source_file,
                        "evidence_origin": citation.evidence_origin,
                        "evidence_authority": citation.evidence_authority,
                        "revision_source": True,
                    }.items()
                    if value is not None
                },
            )
        )
        seen.add(citation.chunk_id)
    for chunk in retrieved_chunks:
        if chunk.chunk_id not in seen:
            merged.append(chunk)
            seen.add(chunk.chunk_id)
    return merged


def _revision_source_type(value: str) -> str:
    suffix = Path(value).suffix.casefold()
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".txt":
        return "txt"
    return "md"


def _retrieve_for_request(
    *,
    project: Project,
    query: str,
    top_k: int,
    include_baseline: bool,
    vector_store: VectorStore,
    rag_repository: RAGRepository,
    candidate_k: int,
    baseline_project_id: str,
) -> RetrievalRun:
    try:
        return retrieve_evidence(
            project=project,
            query=query,
            vector_store=vector_store,
            repository=rag_repository,
            top_k=top_k,
            candidate_k=candidate_k,
            baseline_project_id=baseline_project_id,
            include_baseline=include_baseline,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Evidence retrieval failed")
        raise HTTPException(
            status_code=503,
            detail="Evidence retrieval is temporarily unavailable. Please try again shortly.",
        ) from exc


def _retrieve_for_queries(
    *,
    project: Project,
    queries: list[str],
    top_k: int,
    include_baseline: bool,
    vector_store: VectorStore,
    rag_repository: RAGRepository,
    candidate_k: int,
    baseline_project_id: str,
) -> RetrievalRun:
    try:
        return retrieve_evidence_for_queries(
            project=project,
            queries=queries,
            vector_store=vector_store,
            repository=rag_repository,
            top_k=top_k,
            candidate_k=candidate_k,
            baseline_project_id=baseline_project_id,
            include_baseline=include_baseline,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Multi-query evidence retrieval failed")
        raise HTTPException(
            status_code=503,
            detail="Evidence retrieval is temporarily unavailable. Please try again shortly.",
        ) from exc


def _require_project(repository: RAGRepository, project_id: str) -> Project:
    try:
        project = repository.get_project(project_id)
    except Exception as exc:
        logger.exception("Project lookup failed")
        raise HTTPException(
            status_code=503,
            detail="Project persistence is temporarily unavailable. Please try again shortly.",
        ) from exc
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def _resolve_verified_ncs_units(
    *,
    payload: ProjectCreate,
    repository: RAGRepository,
) -> ProjectCreate:
    if payload.course_type != CourseType.NCS:
        return payload
    resolved_units: list[NCSUnit] = []
    for unit in payload.ncs_units:
        if unit.source_status == NCSSourceStatus.USER_PROVIDED:
            resolved_units.append(unit)
            continue
        try:
            catalog_unit = repository.get_ncs_catalog_unit(unit.unit_code)
        except Exception as exc:
            logger.exception("NCS unit verification failed")
            raise HTTPException(
                status_code=503,
                detail="NCS catalog verification is temporarily unavailable.",
            ) from exc
        if catalog_unit is None and unit.source_status == NCSSourceStatus.VERIFIED:
            raise HTTPException(
                status_code=422,
                detail=f"공식 NCS catalog에서 능력단위 {unit.unit_code}를 확인할 수 없습니다.",
            )
        if catalog_unit is None:
            resolved_units.append(unit)
            continue
        if not catalog_unit.criteria:
            resolved_units.append(
                unit.model_copy(
                    update={
                        "unit_name": catalog_unit.unit_name,
                        "source_status": NCSSourceStatus.NEEDS_REVIEW,
                        "catalog_version": catalog_unit.catalog_version,
                        "classification": catalog_unit.classification,
                    }
                )
            )
            continue
        if unit.source_status != NCSSourceStatus.VERIFIED:
            resolved_units.append(unit)
            continue
        available_criteria = {item.text for item in catalog_unit.criteria}
        unavailable_criteria = [
            criterion for criterion in unit.target_criteria if criterion not in available_criteria
        ]
        if unavailable_criteria:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "선택한 수행준거가 NCS catalog와 일치하지 않습니다.",
                    "unit_code": unit.unit_code,
                    "unavailable_criteria": unavailable_criteria,
                },
            )
        resolved_units.append(
            unit.model_copy(
                update={
                    "unit_name": catalog_unit.unit_name,
                    "classification": catalog_unit.classification,
                    "catalog_version": catalog_unit.catalog_version,
                    "source_status": NCSSourceStatus.VERIFIED,
                }
            )
        )
    return payload.model_copy(update={"ncs_units": resolved_units})


def _validate_ncs_generation_evidence(
    project: Project,
    evidence: list[RetrievedEvidence],
) -> None:
    _validate_ncs_generation_chunks(project, [item.chunk for item in evidence])


def _validate_ncs_generation_chunks(project: Project, chunks: list[MaterialChunk]) -> None:
    if project.course_type != CourseType.NCS:
        return
    requires_user_evidence = any(
        unit.source_status != NCSSourceStatus.VERIFIED for unit in project.ncs_units
    )
    if not requires_user_evidence:
        return
    has_user_evidence = any(
        chunk.project_id == project.project_id
        or str(chunk.metadata.get("evidence_origin", "")).casefold() == "user_upload"
        or str(chunk.metadata.get("evidence_authority", "")).casefold() == "user_provided"
        for chunk in chunks
    )
    if not has_user_evidence:
        raise HTTPException(
            status_code=422,
            detail=(
                "공식 확인 전 NCS 기준을 사용하는 강의에는 능력단위와 수행준거를 포함한 "
                "사용자 자료 업로드가 필요합니다."
            ),
        )


def _require_retrieval_run(
    *,
    repository: RAGRepository,
    run_id: str,
    project_id: str,
) -> RetrievalRun:
    try:
        run = repository.get_retrieval_run(run_id)
    except Exception as exc:
        logger.exception("Retrieval run lookup failed")
        raise HTTPException(
            status_code=503,
            detail="Retrieval persistence is temporarily unavailable. Please try again shortly.",
        ) from exc
    if run is None or run.project_id != project_id:
        raise HTTPException(status_code=404, detail="retrieval run not found")
    return run


def _select_retrieval_evidence(
    run: RetrievalRun,
    *,
    selected_chunk_ids: list[str] | None,
) -> list[RetrievedEvidence]:
    if selected_chunk_ids is None:
        return run.evidence
    requested = set(selected_chunk_ids)
    available = {item.chunk.chunk_id for item in run.evidence}
    unavailable = sorted(requested - available)
    if unavailable:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "selected_chunk_ids must belong to the referenced retrieval run",
                "unavailable_chunk_ids": unavailable,
            },
        )
    return [item for item in run.evidence if item.chunk.chunk_id in requested]


def _create_runtime_vector_store(
    config: LessonPackConfig | None,
    *,
    allow_env_override: bool,
) -> VectorStore:
    env_provider = os.getenv("LECTUREOPS_VECTOR_STORE", "").strip()
    if allow_env_override and env_provider:
        return create_vector_store_from_env()
    if config:
        return create_vector_store_from_config(config.vector_store)
    return create_vector_store_from_env()


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


def _cors_response_headers(request: Request) -> dict[str, str]:
    origin = request.headers.get("origin", "").strip()
    allow_origins = _cors_allow_origins_from_env()
    if not origin or ("*" not in allow_origins and origin not in allow_origins):
        return {}
    headers = {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Expose-Headers": "Content-Disposition",
        "Vary": "Origin",
    }
    if _env_flag("LESSONPACK_CORS_ALLOW_CREDENTIALS", default=False):
        headers["Access-Control-Allow-Credentials"] = "true"
    return headers


async def _read_upload_content(
    file: UploadFile,
    *,
    max_upload_bytes: int,
    max_upload_mb: int,
) -> bytes:
    content = bytearray()
    while chunk := await file.read(UPLOAD_READ_CHUNK_BYTES):
        if len(content) + len(chunk) > max_upload_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File size must not exceed {max_upload_mb}MB.",
            )
        content.extend(chunk)
    return bytes(content)


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


def _runtime_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be greater than 0")
    return parsed


def _load_config_from_env() -> LessonPackConfig | None:
    config_path = os.getenv("LESSONPACK_CONFIG")
    if not config_path:
        return None
    return load_config(config_path)


app = create_app()
