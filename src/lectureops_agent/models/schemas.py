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


class CourseType(str, Enum):
    NCS = "ncs"
    GENERAL = "general"


class NCSSourceStatus(str, Enum):
    VERIFIED = "verified"
    USER_PROVIDED = "user_provided"
    NEEDS_REVIEW = "needs_review"


class NCSUnit(BaseModel):
    unit_code: str = Field(min_length=1)
    unit_name: str = Field(min_length=1)
    elements: list[str] = Field(default_factory=list)
    target_criteria: list[str] = Field(default_factory=list)
    source_status: NCSSourceStatus = NCSSourceStatus.NEEDS_REVIEW
    catalog_version: str | None = None
    classification: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize_unit(self) -> "NCSUnit":
        self.unit_code = " ".join(self.unit_code.split())
        self.unit_name = " ".join(self.unit_name.split())
        self.elements = _normalize_unique_strings(self.elements)
        self.target_criteria = _normalize_unique_strings(self.target_criteria or self.elements)
        self.catalog_version = (
            " ".join(self.catalog_version.split()) if self.catalog_version else None
        )
        self.classification = {
            str(key).strip(): " ".join(str(value).split())
            for key, value in self.classification.items()
            if str(key).strip() and str(value).strip()
        }
        return self


class NCSCatalogCriterion(BaseModel):
    criterion_code: str = Field(min_length=1)
    element_code: str | None = None
    element_name: str | None = None
    text: str = Field(min_length=1)


class NCSCatalogUnit(BaseModel):
    unit_code: str = Field(min_length=1)
    unit_name: str = Field(min_length=1)
    definition: str | None = None
    classification: dict[str, str] = Field(default_factory=dict)
    level: int | None = Field(default=None, ge=1, le=8)
    catalog_version: str | None = None
    source_url: str | None = None
    criteria: list[NCSCatalogCriterion] = Field(default_factory=list)


class NCSAlignment(BaseModel):
    unit_code: str = Field(min_length=1)
    unit_name: str = Field(min_length=1)
    performance_criteria: list[str] = Field(default_factory=list)
    source_md: str | None = None


class NCSCriterionCoverage(BaseModel):
    unit_code: str = Field(min_length=1)
    unit_name: str = Field(min_length=1)
    performance_criterion: str = Field(min_length=1)
    lesson_sections: list[str] = Field(default_factory=list)
    practice: bool = False
    assessment_items: list[str] = Field(default_factory=list)
    covered: bool = False


class NCSCoverageReport(BaseModel):
    target_criteria_count: int = Field(ge=0)
    covered_criteria_count: int = Field(ge=0)
    assessment_criteria_count: int = Field(ge=0)
    coverage: float = Field(ge=0.0, le=1.0)
    assessment_coverage: float = Field(ge=0.0, le=1.0)
    source_statuses: list[NCSSourceStatus] = Field(default_factory=list)
    items: list[NCSCriterionCoverage] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CitationDetail(BaseModel):
    chunk_id: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    source_url: str | None = None
    license: str | None = None
    source_file: str | None = None
    page: int | None = Field(default=None, ge=1)
    excerpt: str = Field(min_length=1)
    evidence_origin: str | None = None
    evidence_authority: str | None = None


class StandardTemplateMetadata(BaseModel):
    template_version: str = "lessonpack-mvp-v0.2"
    lesson_duration_min: int | None = Field(default=None, ge=1)
    total_training_hours: float | None = Field(default=None, gt=0)
    total_lessons: int | None = Field(default=None, ge=1)
    theory_ratio_percent: int | None = Field(default=None, ge=0, le=100)
    practice_ratio_percent: int | None = Field(default=None, ge=0, le=100)
    generation_scope: str = "single_lesson_mvp"


class ProjectCreate(BaseModel):
    course_type: CourseType
    course_title: str = Field(min_length=1)
    lesson_title: str = Field(min_length=1)
    learner_profile: str = Field(min_length=1)
    total_training_hours: float = Field(default=2.0, gt=0, le=10000)
    total_lessons: int = Field(default=1, ge=1, le=1000)
    theory_ratio_percent: int = Field(default=30, ge=0, le=100)
    practice_ratio_percent: int = Field(default=70, ge=0, le=100)
    learning_objectives: list[str] = Field(min_length=1)
    ncs_units: list[NCSUnit] = Field(default_factory=list, max_length=5)
    retrieval_queries: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def validate_training_plan(self) -> "ProjectCreate":
        if self.theory_ratio_percent + self.practice_ratio_percent != 100:
            raise ValueError("theory_ratio_percent and practice_ratio_percent must total 100")
        if self.total_training_hours * 60 / self.total_lessons < 15:
            raise ValueError("average lesson duration must be at least 15 minutes")
        self.learning_objectives = _normalize_unique_strings(self.learning_objectives)
        if not self.learning_objectives:
            raise ValueError("learning_objectives must include at least one non-empty value")
        self.retrieval_queries = _normalize_unique_strings(self.retrieval_queries)
        if self.course_type == CourseType.NCS:
            if not self.ncs_units:
                raise ValueError("ncs course requires at least one NCS unit")
            unit_codes: set[str] = set()
            for unit in self.ncs_units:
                key = unit.unit_code.casefold()
                if key in unit_codes:
                    raise ValueError("ncs unit codes must be unique")
                unit_codes.add(key)
                if not unit.target_criteria:
                    raise ValueError(
                        f"NCS unit {unit.unit_code} requires at least one target criterion"
                    )
        elif self.ncs_units:
            raise ValueError("general course must not include NCS units")
        return self

    @property
    def lesson_duration_minutes(self) -> int:
        return max(1, round(self.total_training_hours * 60 / self.total_lessons))

    def to_project(self, project_id: str | None = None) -> "Project":
        return Project(
            project_id=project_id or str(uuid4()),
            course_type=self.course_type,
            course_title=self.course_title,
            lesson_title=self.lesson_title,
            learner_profile=self.learner_profile,
            total_training_hours=self.total_training_hours,
            total_lessons=self.total_lessons,
            theory_ratio_percent=self.theory_ratio_percent,
            practice_ratio_percent=self.practice_ratio_percent,
            learning_objectives=self.learning_objectives,
            ncs_units=self.ncs_units,
            retrieval_queries=self.retrieval_queries,
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
    strategy: Literal["hybrid", "project_material_fallback"] = "hybrid"


class RetrievalRun(BaseModel):
    run_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    normalized_query: str = Field(min_length=1)
    course_type: CourseType = CourseType.GENERAL
    ncs_unit_codes: list[str] = Field(default_factory=list)
    catalog_versions: list[str] = Field(default_factory=list)
    evidence: list[RetrievedEvidence] = Field(default_factory=list)
    created_at: datetime


class RAGRetrieveResponse(BaseModel):
    retrieval_run_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    course_type: CourseType = CourseType.GENERAL
    ncs_unit_codes: list[str] = Field(default_factory=list)
    evidence: list[RetrievedEvidence] = Field(default_factory=list)
    created_at: datetime


class RAGGenerateRequest(BaseModel):
    query: str | None = Field(default=None, min_length=1)
    queries: list[str] | None = Field(default=None, min_length=1, max_length=5)
    top_k: int | None = Field(default=None, ge=1, le=20)
    include_baseline: bool = True
    retrieval_run_id: str | None = Field(default=None, min_length=1)
    selected_chunk_ids: list[str] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_generation_source(self) -> "RAGGenerateRequest":
        source_count = sum(
            value is not None
            for value in (self.query, self.queries, self.retrieval_run_id)
        )
        if source_count != 1:
            raise ValueError("exactly one of query, queries, or retrieval_run_id is required")
        if self.selected_chunk_ids is not None and self.retrieval_run_id is None:
            raise ValueError("selected_chunk_ids requires retrieval_run_id")
        if self.queries is not None:
            self.queries = _normalize_unique_strings(self.queries)
            if not self.queries:
                raise ValueError("queries must include at least one non-empty value")
        return self


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
    course_type: CourseType = CourseType.GENERAL
    status: PackageStatus = PackageStatus.GENERATED
    lesson_plan: LessonPlan
    practice: Practice
    assessment: Assessment
    evidence_sources: list[CitationDetail] = Field(default_factory=list)
    ncs_coverage: NCSCoverageReport | None = None
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
    instruction: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=20)
    include_baseline: bool = True

    @model_validator(mode="after")
    def validate_instruction(self) -> "PackageRegenerateRequest":
        self.instruction = " ".join(self.instruction.split())
        if sum(character.isalnum() for character in self.instruction) < 2:
            raise ValueError("instruction must contain a meaningful natural-language request")
        return self


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


def _normalize_unique_strings(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = " ".join(value.split())
        key = item.casefold()
        if item and key not in seen:
            normalized.append(item)
            seen.add(key)
    return normalized
