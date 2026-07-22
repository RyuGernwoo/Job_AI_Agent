from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PackageStatus(str, Enum):
    GENERATED = "generated"
    EXPORTED = "exported"
    REGENERATED = "regenerated"


class NCSUnit(BaseModel):
    unit_code: str = Field(min_length=1)
    unit_name: str = Field(min_length=1)
    elements: list[str] = Field(default_factory=list)


class NCSAlignment(BaseModel):
    unit_code: str = Field(min_length=1)
    unit_name: str = Field(min_length=1)
    performance_criteria: list[str] = Field(default_factory=list)
    source_md: str | None = None


class CitationDetail(BaseModel):
    chunk_id: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    source_url: str | None = None
    license: str | None = None
    source_file: str | None = None
    page: int | None = Field(default=None, ge=1)
    excerpt: str = Field(min_length=1)


class StandardTemplateMetadata(BaseModel):
    template_version: str = "lessonpack-mvp-v0.2"
    lesson_duration_min: int | None = Field(default=None, ge=1)
    total_training_hours: float | None = Field(default=None, gt=0)
    total_lessons: int | None = Field(default=None, ge=1)
    theory_ratio_percent: int | None = Field(default=None, ge=0, le=100)
    practice_ratio_percent: int | None = Field(default=None, ge=0, le=100)
    generation_scope: str = "single_lesson_mvp"


class ProjectCreate(BaseModel):
    course_title: str = Field(min_length=1)
    lesson_title: str = Field(min_length=1)
    learner_profile: str = Field(min_length=1)
    total_training_hours: float = Field(default=2.0, gt=0, le=10000)
    total_lessons: int = Field(default=1, ge=1, le=1000)
    theory_ratio_percent: int = Field(default=30, ge=0, le=100)
    practice_ratio_percent: int = Field(default=70, ge=0, le=100)
    learning_objectives: list[str] = Field(min_length=1)
    ncs_units: list[NCSUnit] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_training_plan(self) -> "ProjectCreate":
        if self.theory_ratio_percent + self.practice_ratio_percent != 100:
            raise ValueError("theory_ratio_percent and practice_ratio_percent must total 100")
        if self.total_training_hours * 60 / self.total_lessons < 15:
            raise ValueError("average lesson duration must be at least 15 minutes")
        return self

    @property
    def lesson_duration_minutes(self) -> int:
        return max(1, round(self.total_training_hours * 60 / self.total_lessons))

    def to_project(self, project_id: str | None = None) -> "Project":
        return Project(
            project_id=project_id or str(uuid4()),
            course_title=self.course_title,
            lesson_title=self.lesson_title,
            learner_profile=self.learner_profile,
            total_training_hours=self.total_training_hours,
            total_lessons=self.total_lessons,
            theory_ratio_percent=self.theory_ratio_percent,
            practice_ratio_percent=self.practice_ratio_percent,
            learning_objectives=self.learning_objectives,
            ncs_units=self.ncs_units,
            created_at=datetime.now(timezone.utc),
        )


class Project(ProjectCreate):
    project_id: str = Field(min_length=1)
    created_at: datetime


class MaterialChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    source_type: Literal["pdf", "txt", "md"]
    page: int | None = Field(default=None, ge=1)
    text: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MaterialIngestResult(BaseModel):
    project_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    source_type: Literal["pdf", "txt", "md"]
    chunk_count: int = Field(ge=1)
    chunks: list[MaterialChunk] = Field(min_length=1)


class MaterialDocument(BaseModel):
    document_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    source_type: Literal["pdf", "txt", "md"]
    content_hash: str = Field(min_length=1)
    chunk_count: int = Field(ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class RetrieveRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(ge=1, le=20)


class RAGRetrieveRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=20)
    include_baseline: bool = True


class RetrievedEvidence(BaseModel):
    chunk: MaterialChunk
    score: float = Field(ge=0.0, le=1.0)
    vector_similarity: float = Field(ge=-1.0, le=1.0)
    lexical_overlap: float = Field(ge=0.0, le=1.0)
    scope: Literal["project", "baseline"]


class RetrievalRun(BaseModel):
    run_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    normalized_query: str = Field(min_length=1)
    evidence: list[RetrievedEvidence] = Field(default_factory=list)
    created_at: datetime


class RAGRetrieveResponse(BaseModel):
    retrieval_run_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    evidence: list[RetrievedEvidence] = Field(default_factory=list)
    created_at: datetime


class RAGGenerateRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=20)
    include_baseline: bool = True


class LectureFlowItem(BaseModel):
    section: str = Field(min_length=1)
    duration_min: int | None = Field(default=None, ge=1)
    content: str = Field(min_length=1)
    citation_ids: list[str] = Field(min_length=1)
    ncs_alignment: list[NCSAlignment] = Field(default_factory=list)


class LessonPlan(BaseModel):
    title: str = Field(min_length=1)
    learning_objectives: list[str] = Field(min_length=1)
    lecture_flow: list[LectureFlowItem] = Field(min_length=1)


class Practice(BaseModel):
    scenario: str = Field(min_length=1)
    steps: list[str] = Field(min_length=1)
    submission: str = Field(min_length=1)
    rubric: list[str] = Field(min_length=1)
    citation_ids: list[str] = Field(min_length=1)
    ncs_alignment: list[NCSAlignment] = Field(default_factory=list)


class MultipleChoiceQuestion(BaseModel):
    question: str = Field(min_length=1)
    options: list[str] = Field(min_length=4, max_length=4)
    answer_index: int = Field(ge=0, le=3)
    explanation: str = Field(min_length=1)
    citation_ids: list[str] = Field(min_length=1)
    ncs_alignment: list[NCSAlignment] = Field(default_factory=list)


class PerformanceTask(BaseModel):
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    rubric: list[str] = Field(min_length=1)
    citation_ids: list[str] = Field(min_length=1)
    ncs_alignment: list[NCSAlignment] = Field(default_factory=list)


class Assessment(BaseModel):
    multiple_choice: list[MultipleChoiceQuestion] = Field(min_length=1)
    performance_task: PerformanceTask


class LessonPackage(BaseModel):
    package_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    status: PackageStatus = PackageStatus.GENERATED
    lesson_plan: LessonPlan
    practice: Practice
    assessment: Assessment
    evidence_sources: list[CitationDetail] = Field(default_factory=list)
    template_metadata: StandardTemplateMetadata = Field(default_factory=StandardTemplateMetadata)


class GenerationLog(BaseModel):
    log_id: str = Field(min_length=1)
    package_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    provider_name: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    response_text: str = Field(min_length=1)
    structured_output_applied: bool = False
    generation_attempts: int = Field(default=1, ge=1)
    schema_validation_errors: list[str] = Field(default_factory=list)
    retrieval_run_id: str | None = None
    trace_id: str | None = None
    source_package_id: str | None = None
    revision_instruction: str | None = None
    citation_ids: list[str] = Field(min_length=1)
    retrieved_chunk_ids: list[str] = Field(min_length=1)
    created_at: datetime


class GenerateRequest(BaseModel):
    retrieved_chunks: list[MaterialChunk] = Field(min_length=1)


class RAGGenerateResponse(BaseModel):
    package: LessonPackage
    retrieval_run_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)


class PackageRegenerateRequest(BaseModel):
    instruction: str = Field(min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=20)
    include_baseline: bool = True


class PackageRegenerateResponse(BaseModel):
    package: LessonPackage
    source_package_id: str = Field(min_length=1)
    retrieval_run_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)


class GenerationRun(BaseModel):
    package_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    retrieval_run_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    provider_name: str = Field(min_length=1)
    structured_output_applied: bool = False
    citation_ids: list[str] = Field(default_factory=list)
    created_at: datetime
