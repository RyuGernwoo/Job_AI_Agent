from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class PackageStatus(str, Enum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    EXPORTED = "exported"
    REGENERATED = "regenerated"
    NEEDS_REVISION = "needs_revision"


class NCSUnit(BaseModel):
    unit_code: str = Field(min_length=1)
    unit_name: str = Field(min_length=1)
    elements: list[str] = Field(default_factory=list)


class ProjectCreate(BaseModel):
    course_title: str = Field(min_length=1)
    lesson_title: str = Field(min_length=1)
    learner_profile: str = Field(min_length=1)
    learning_objectives: list[str] = Field(min_length=1)
    ncs_units: list[NCSUnit] = Field(default_factory=list)

    def to_project(self, project_id: str | None = None) -> "Project":
        return Project(
            project_id=project_id or str(uuid4()),
            course_title=self.course_title,
            lesson_title=self.lesson_title,
            learner_profile=self.learner_profile,
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
    source_type: Literal["txt", "md"]
    chunk_count: int = Field(ge=1)
    chunks: list[MaterialChunk] = Field(min_length=1)


class RetrieveRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(ge=1, le=20)


class LectureFlowItem(BaseModel):
    section: str = Field(min_length=1)
    duration_min: int | None = Field(default=None, ge=1)
    content: str = Field(min_length=1)
    citation_ids: list[str] = Field(min_length=1)


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


class MultipleChoiceQuestion(BaseModel):
    question: str = Field(min_length=1)
    options: list[str] = Field(min_length=4, max_length=4)
    answer_index: int = Field(ge=0, le=3)
    explanation: str = Field(min_length=1)
    citation_ids: list[str] = Field(min_length=1)


class PerformanceTask(BaseModel):
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    rubric: list[str] = Field(min_length=1)
    citation_ids: list[str] = Field(min_length=1)


class Assessment(BaseModel):
    multiple_choice: list[MultipleChoiceQuestion] = Field(min_length=1)
    performance_task: PerformanceTask


class LessonPackage(BaseModel):
    package_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    status: PackageStatus = PackageStatus.DRAFT
    lesson_plan: LessonPlan
    practice: Practice
    assessment: Assessment


class GenerateRequest(BaseModel):
    retrieved_chunks: list[MaterialChunk] = Field(min_length=1)


class ReviewPatch(BaseModel):
    status: PackageStatus
    reviewer_notes: str = Field(min_length=1)
