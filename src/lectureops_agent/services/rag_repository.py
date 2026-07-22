from __future__ import annotations

from typing import Any, Protocol
from uuid import uuid4

from lectureops_agent.models.schemas import (
    GenerationRun,
    MaterialDocument,
    Project,
    RetrievalRun,
)


class RAGRepository(Protocol):
    def readiness(self) -> dict[str, Any]:
        ...

    def save_project(self, project: Project) -> None:
        ...

    def get_project(self, project_id: str) -> Project | None:
        ...

    def next_document_id(self, project_id: str) -> str:
        ...

    def save_document(self, document: MaterialDocument) -> None:
        ...

    def save_retrieval_run(self, run: RetrievalRun) -> None:
        ...

    def get_retrieval_run(self, run_id: str) -> RetrievalRun | None:
        ...

    def save_generation_run(self, run: GenerationRun) -> None:
        ...


class InMemoryRAGRepository:
    def __init__(self) -> None:
        self.projects: dict[str, Project] = {}
        self.documents: dict[str, MaterialDocument] = {}
        self.retrieval_runs: dict[str, RetrievalRun] = {}
        self.generation_runs: dict[str, GenerationRun] = {}
        self._document_counts: dict[str, int] = {}

    def readiness(self) -> dict[str, Any]:
        return {"ready": True, "tables": {}}

    def save_project(self, project: Project) -> None:
        self.projects[project.project_id] = project
        self._document_counts.setdefault(project.project_id, 0)

    def get_project(self, project_id: str) -> Project | None:
        return self.projects.get(project_id)

    def next_document_id(self, project_id: str) -> str:
        count = self._document_counts.get(project_id, 0) + 1
        self._document_counts[project_id] = count
        return f"doc{count:03d}"

    def save_document(self, document: MaterialDocument) -> None:
        self.documents[document.document_id] = document

    def save_retrieval_run(self, run: RetrievalRun) -> None:
        self.retrieval_runs[run.run_id] = run

    def get_retrieval_run(self, run_id: str) -> RetrievalRun | None:
        return self.retrieval_runs.get(run_id)

    def save_generation_run(self, run: GenerationRun) -> None:
        self.generation_runs[run.package_id] = run


class SupabaseRAGRepository:
    def __init__(
        self,
        *,
        client: Any,
        projects_table: str = "lessonpack_projects",
        documents_table: str = "lessonpack_documents",
        retrieval_runs_table: str = "lessonpack_retrieval_runs",
        generation_runs_table: str = "lessonpack_generation_runs",
    ) -> None:
        self._client = client
        self.projects_table = projects_table
        self.documents_table = documents_table
        self.retrieval_runs_table = retrieval_runs_table
        self.generation_runs_table = generation_runs_table

    def readiness(self) -> dict[str, Any]:
        tables = {
            self.projects_table: (
                "project_id,total_training_hours,total_lessons,"
                "theory_ratio_percent,practice_ratio_percent,retrieval_queries"
            ),
            self.documents_table: "document_id",
            self.retrieval_runs_table: "run_id",
            self.generation_runs_table: "package_id",
        }
        result: dict[str, Any] = {"ready": True, "tables": {}}
        for table_name, required_columns in tables.items():
            try:
                self._client.table(table_name).select(required_columns).limit(1).execute()
                result["tables"][table_name] = {"exists": True}
            except Exception as exc:
                result["tables"][table_name] = {
                    "exists": False,
                    "error_type": type(exc).__name__,
                }
                result["ready"] = False
        return result

    def save_project(self, project: Project) -> None:
        row = {
            "project_id": project.project_id,
            "course_title": project.course_title,
            "lesson_title": project.lesson_title,
            "learner_profile": project.learner_profile,
            "total_training_hours": project.total_training_hours,
            "total_lessons": project.total_lessons,
            "theory_ratio_percent": project.theory_ratio_percent,
            "practice_ratio_percent": project.practice_ratio_percent,
            "learning_objectives": project.learning_objectives,
            "ncs_units": [item.model_dump(mode="json") for item in project.ncs_units],
            "retrieval_queries": project.retrieval_queries,
            "created_at": project.created_at.isoformat(),
        }
        self._upsert(self.projects_table, row, on_conflict="project_id")

    def get_project(self, project_id: str) -> Project | None:
        response = (
            self._client.table(self.projects_table)
            .select("*")
            .eq("project_id", project_id)
            .limit(1)
            .execute()
        )
        rows = _response_data(response)
        return Project.model_validate(rows[0]) if rows else None

    def next_document_id(self, project_id: str) -> str:
        return f"doc-{uuid4().hex[:12]}"

    def save_document(self, document: MaterialDocument) -> None:
        row = document.model_dump(mode="json")
        self._upsert(self.documents_table, row, on_conflict="document_id")

    def save_retrieval_run(self, run: RetrievalRun) -> None:
        row = {
            "run_id": run.run_id,
            "trace_id": run.trace_id,
            "project_id": run.project_id,
            "query": run.query,
            "normalized_query": run.normalized_query,
            "evidence": [item.model_dump(mode="json") for item in run.evidence],
            "selected_chunk_ids": [item.chunk.chunk_id for item in run.evidence],
            "created_at": run.created_at.isoformat(),
        }
        self._upsert(self.retrieval_runs_table, row, on_conflict="run_id")

    def get_retrieval_run(self, run_id: str) -> RetrievalRun | None:
        response = (
            self._client.table(self.retrieval_runs_table)
            .select("*")
            .eq("run_id", run_id)
            .limit(1)
            .execute()
        )
        rows = _response_data(response)
        return RetrievalRun.model_validate(rows[0]) if rows else None

    def save_generation_run(self, run: GenerationRun) -> None:
        self._upsert(
            self.generation_runs_table,
            run.model_dump(mode="json"),
            on_conflict="package_id",
        )

    def _upsert(self, table_name: str, row: dict[str, Any], *, on_conflict: str) -> None:
        response = self._client.table(table_name).upsert(row, on_conflict=on_conflict).execute()
        _raise_for_supabase_error(response)


def create_rag_repository_for_vector_store(vector_store: Any) -> RAGRepository:
    from lectureops_agent.services.vector_store import SupabaseVectorStore

    if isinstance(vector_store, SupabaseVectorStore):
        return SupabaseRAGRepository(client=vector_store.client)
    return InMemoryRAGRepository()


def _response_data(response: Any) -> list[dict[str, Any]]:
    error = getattr(response, "error", None)
    if error:
        raise RuntimeError(f"Supabase RAG repository request failed: {error}")
    data = getattr(response, "data", None)
    if data is None and isinstance(response, dict):
        if response.get("error"):
            raise RuntimeError(f"Supabase RAG repository request failed: {response['error']}")
        data = response.get("data")
    if data is None:
        return []
    if not isinstance(data, list):
        raise RuntimeError("Supabase RAG repository response data must be a list")
    return data


def _raise_for_supabase_error(response: Any) -> None:
    error = getattr(response, "error", None)
    if error is None and isinstance(response, dict):
        error = response.get("error")
    if error:
        raise RuntimeError(f"Supabase RAG repository request failed: {error}")
