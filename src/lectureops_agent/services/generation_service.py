from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from lectureops_agent.models.schemas import (
    Assessment,
    GenerationLog,
    LessonPackage,
    LessonPlan,
    LectureFlowItem,
    MaterialChunk,
    MultipleChoiceQuestion,
    PackageStatus,
    PerformanceTask,
    Practice,
    Project,
)
from lectureops_agent.services.llm_provider import LLMProvider, MockLLMProvider


@dataclass(frozen=True)
class GeneratedLessonPackageResult:
    package: LessonPackage
    log: GenerationLog


def generate_lesson_package(
    *,
    project: Project,
    retrieved_chunks: list[MaterialChunk],
    package_id: str | None = None,
    llm_provider: LLMProvider | None = None,
) -> LessonPackage:
    return generate_lesson_package_with_log(
        project=project,
        retrieved_chunks=retrieved_chunks,
        package_id=package_id,
        llm_provider=llm_provider,
    ).package


def generate_lesson_package_with_log(
    *,
    project: Project,
    retrieved_chunks: list[MaterialChunk],
    package_id: str | None = None,
    llm_provider: LLMProvider | None = None,
) -> GeneratedLessonPackageResult:
    if not retrieved_chunks:
        raise ValueError("retrieved_chunks must not be empty")

    provider = llm_provider or MockLLMProvider()
    prompt = build_generation_prompt(project=project, retrieved_chunks=retrieved_chunks)
    provider_response = provider.generate(prompt=prompt).strip()
    if not provider_response:
        raise ValueError("llm provider returned empty response")

    package_id = package_id or str(uuid4())
    package = _build_package(
        project=project,
        retrieved_chunks=retrieved_chunks,
        package_id=package_id,
        provider_response=provider_response,
    )
    citation_ids = _citation_ids(retrieved_chunks)
    log = GenerationLog(
        log_id=str(uuid4()),
        package_id=package.package_id,
        project_id=project.project_id,
        provider_name=provider.name,
        prompt=prompt,
        response_text=provider_response,
        citation_ids=citation_ids,
        retrieved_chunk_ids=[chunk.chunk_id for chunk in retrieved_chunks],
        created_at=datetime.now(timezone.utc),
    )
    return GeneratedLessonPackageResult(package=package, log=log)


def build_generation_prompt(*, project: Project, retrieved_chunks: list[MaterialChunk]) -> str:
    objective_text = "\n".join(f"- {objective}" for objective in project.learning_objectives)
    ncs_text = "\n".join(
        f"- {unit.unit_code} {unit.unit_name}: {', '.join(unit.elements) if unit.elements else '세부 요소 미기재'}"
        for unit in project.ncs_units
    )
    evidence_text = "\n".join(f"[{chunk.chunk_id}] {chunk.text}" for chunk in retrieved_chunks)
    return (
        "LessonPack AI generation request\n"
        f"Course: {project.course_title}\n"
        f"Lesson: {project.lesson_title}\n"
        f"Learners: {project.learner_profile}\n"
        "Learning objectives:\n"
        f"{objective_text}\n"
        "NCS units:\n"
        f"{ncs_text or '- NCS unit not provided'}\n"
        "Retrieved evidence chunks:\n"
        f"{evidence_text}\n"
        "Create a grounded lesson plan, practice scenario, and assessment draft. "
        "Every core item must stay traceable to citation IDs and require instructor review."
    )


def _build_package(
    *,
    project: Project,
    retrieved_chunks: list[MaterialChunk],
    package_id: str,
    provider_response: str,
) -> LessonPackage:
    primary_chunk = retrieved_chunks[0]
    citation_ids = _citation_ids(retrieved_chunks)
    objective_text = " / ".join(project.learning_objectives)
    evidence_summary = primary_chunk.text[:120]
    provider_summary = provider_response[:180]

    lesson_plan = LessonPlan(
        title=project.lesson_title,
        learning_objectives=project.learning_objectives,
        lecture_flow=[
            LectureFlowItem(
                section="도입",
                duration_min=None,
                content=f"{project.course_title} 과정 맥락에서 오늘 차시 목표를 안내한다: {objective_text}",
                citation_ids=citation_ids,
            ),
            LectureFlowItem(
                section="전개",
                duration_min=None,
                content=(
                    "핵심 개념을 근거 자료와 provider 생성 요약에 맞춰 설명한다. "
                    f"근거 요약: {evidence_summary} / 생성 요약: {provider_summary}"
                ),
                citation_ids=citation_ids,
            ),
            LectureFlowItem(
                section="정리",
                duration_min=None,
                content="학습자가 직접 작성한 결과물을 기준으로 개념 이해와 적용 여부를 점검한다.",
                citation_ids=citation_ids,
            ),
        ],
    )

    practice = Practice(
        scenario=f"{project.lesson_title} 내용을 활용해 직업훈련 수업용 자동화 예제를 만든다.",
        steps=[
            "제공된 근거 자료에서 핵심 개념을 3개 추출한다.",
            "추출한 개념을 활용해 간단한 실습 코드를 작성한다.",
            "작성한 결과를 학습 목표와 연결해 설명한다.",
        ],
        submission="실습 코드와 실행 결과, 핵심 개념 설명 3문장",
        rubric=[
            "근거 자료의 개념을 정확히 반영했다.",
            "실습 절차가 재현 가능하다.",
            "학습 목표와 제출물이 연결된다.",
        ],
        citation_ids=citation_ids,
    )

    assessment = Assessment(
        multiple_choice=[
            MultipleChoiceQuestion(
                question=f"{project.lesson_title} 수업에서 가장 먼저 확인해야 할 항목은 무엇인가?",
                options=[
                    "학습 목표와 수강생 수준",
                    "무관한 고급 알고리즘",
                    "수업과 관계없는 도구 목록",
                    "평가 없이 진행하는 실습",
                ],
                answer_index=0,
                explanation="강의 패키지는 학습 목표와 수강생 수준을 기준으로 구성해야 한다.",
                citation_ids=citation_ids,
            ),
            MultipleChoiceQuestion(
                question="생성 결과에 citation ID를 붙이는 주된 이유는 무엇인가?",
                options=[
                    "근거 추적과 사람 검토를 가능하게 하기 위해",
                    "문서 길이를 임의로 늘리기 위해",
                    "파일명을 숨기기 위해",
                    "평가 문항을 제거하기 위해",
                ],
                answer_index=0,
                explanation="citation ID는 생성 내용이 어떤 근거 chunk에서 나왔는지 확인하는 장치다.",
                citation_ids=citation_ids,
            ),
            MultipleChoiceQuestion(
                question="MVP 단계에서 적합한 검토 흐름은 무엇인가?",
                options=[
                    "draft 생성 후 사람이 검토하고 승인한다.",
                    "검토 없이 자동 배포한다.",
                    "학습자 계정 관리를 먼저 구현한다.",
                    "LMS 연동을 필수로 만든다.",
                ],
                answer_index=0,
                explanation="문서 기준 MVP는 HITL 검토와 승인 흐름을 우선한다.",
                citation_ids=citation_ids,
            ),
            MultipleChoiceQuestion(
                question="검색된 chunk가 생성 프롬프트에 들어가는 이유는 무엇인가?",
                options=[
                    "생성 결과를 근거 자료 범위 안에 묶기 위해",
                    "외부 사실을 임의로 만들기 위해",
                    "모든 PDF 페이지를 그대로 복사하기 위해",
                    "검증을 생략하기 위해",
                ],
                answer_index=0,
                explanation="RAG 흐름은 검색 근거를 바탕으로 생성 범위를 제한한다.",
                citation_ids=citation_ids,
            ),
            MultipleChoiceQuestion(
                question="1개월 MVP에서 제외하는 것이 적절한 기능은 무엇인가?",
                options=[
                    "대규모 LMS 계정 관리",
                    "교안 초안 생성",
                    "실습 과제 초안 생성",
                    "평가 문항 초안 생성",
                ],
                answer_index=0,
                explanation="MVP는 1개 차시 패키지 생성에 집중하고 LMS 운영 기능은 제외한다.",
                citation_ids=citation_ids,
            ),
        ],
        performance_task=PerformanceTask(
            title="강의 패키지 검토 과제",
            description="생성된 교안, 실습, 평가 문항이 학습 목표와 근거 자료에 맞는지 검토한다.",
            rubric=[
                "citation ID가 모든 핵심 항목에 연결되어 있다.",
                "실습 제출물이 학습 목표를 검증할 수 있다.",
                "평가 문항의 정답과 해설이 일관된다.",
            ],
            citation_ids=citation_ids,
        ),
    )

    return LessonPackage(
        package_id=package_id,
        project_id=project.project_id,
        status=PackageStatus.DRAFT,
        lesson_plan=lesson_plan,
        practice=practice,
        assessment=assessment,
    )


def _citation_ids(chunks: list[MaterialChunk]) -> list[str]:
    return [chunks[0].chunk_id]
