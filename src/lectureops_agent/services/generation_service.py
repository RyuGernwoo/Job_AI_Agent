from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from lectureops_agent.models.schemas import (
    Assessment,
    CitationDetail,
    GenerationLog,
    LessonPackage,
    LessonPlan,
    LectureFlowItem,
    MaterialChunk,
    MultipleChoiceQuestion,
    NCSAlignment,
    PackageStatus,
    PerformanceTask,
    Practice,
    Project,
    StandardTemplateMetadata,
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
    evidence_text = "\n".join(
        f"[{chunk.chunk_id}] {chunk.source_name} / {chunk.metadata.get('section', 'section unknown')}: {chunk.text}"
        for chunk in retrieved_chunks
    )
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
        "Return a JSON object only when possible. The object should contain lesson_plan, practice, "
        "assessment, citation_ids, and ncs_alignment. Do not introduce proper nouns, numbers, laws, "
        "or certifications that are not present in the evidence chunks. Every core item must stay "
        "traceable to citation IDs and require instructor review."
    )


def _build_package(
    *,
    project: Project,
    retrieved_chunks: list[MaterialChunk],
    package_id: str,
    provider_response: str,
) -> LessonPackage:
    citation_ids = _citation_ids(retrieved_chunks)
    intro_citations = _citation_ids_for(retrieved_chunks, preferred_index=0, limit=1)
    development_citations = _citation_ids_for(retrieved_chunks, preferred_index=1, limit=2)
    closing_citations = _citation_ids_for(retrieved_chunks, preferred_index=2, limit=1)
    practice_citations = _citation_ids_for(retrieved_chunks, preferred_index=0, limit=3)
    alignments = _ncs_alignments(project)
    primary_alignment = alignments[:1]
    alignment_text = _alignment_summary(primary_alignment)
    objective_text = " / ".join(project.learning_objectives)
    evidence_summary = _evidence_summary(retrieved_chunks)
    practice_keywords = _practice_keywords(project=project, retrieved_chunks=retrieved_chunks)
    practice_keyword_text = ", ".join(practice_keywords)

    lesson_plan = LessonPlan(
        title=project.lesson_title,
        learning_objectives=project.learning_objectives,
        lecture_flow=[
            LectureFlowItem(
                section="도입",
                duration_min=15,
                content=(
                    f"{project.course_title} 과정 맥락에서 오늘 차시 목표를 안내한다. "
                    f"학습자는 {objective_text}를 수행해야 하며, NCS 연계는 {alignment_text}이다."
                ),
                citation_ids=intro_citations,
                ncs_alignment=primary_alignment,
            ),
            LectureFlowItem(
                section="전개",
                duration_min=75,
                content=(
                    f"검색 근거에서 확인된 핵심 개념을 예제와 함께 설명한다. 핵심 근거: {evidence_summary}. "
                    f"강사는 설명 중 {practice_keyword_text}를 차례로 연결한다."
                ),
                citation_ids=development_citations,
                ncs_alignment=alignments,
            ),
            LectureFlowItem(
                section="정리",
                duration_min=30,
                content="학습자가 작성한 코드, 실행 결과, 개념 설명을 기준으로 학습목표와 NCS 수행 기준 충족 여부를 점검한다.",
                citation_ids=closing_citations,
                ncs_alignment=primary_alignment,
            ),
        ],
    )

    practice = Practice(
        scenario=(
            f"실습 시나리오: {project.lesson_title} 내용을 활용해 직업훈련 수업용 자동화 예제를 만든다. "
            f"핵심 실습 요소는 {practice_keyword_text}이다."
        ),
        steps=[
            f"수행 절차: 근거 자료에서 {practice_keyword_text}와 관련된 개념을 3개 추출한다.",
            "수행 절차: 추출한 개념을 함수, 입력값, 반환값 또는 자료구조 처리 코드로 구현한다.",
            "수행 절차: 실행 결과를 캡처하고 학습목표 및 NCS 수행 기준과 연결해 설명한다.",
        ],
        submission=f"제출물: 실습 코드와 실행 결과, 핵심 개념 설명 3문장. 반영 요소: {practice_keyword_text}.",
        rubric=[
            f"평가 기준: 근거 자료와 NCS 수행 기준을 정확히 반영했다. 확인 요소: {practice_keyword_text}.",
            "평가 기준: 실습 절차가 재현 가능하다.",
            "평가 기준: 학습 목표와 제출물이 연결된다.",
        ],
        citation_ids=practice_citations,
        ncs_alignment=alignments,
    )

    rotated_citations = [
        _citation_ids_for(retrieved_chunks, preferred_index=index, limit=1)
        for index in range(5)
    ]
    assessment = Assessment(
        multiple_choice=[
            MultipleChoiceQuestion(
                question=f"{project.lesson_title} 실습에서 학습목표 달성 여부를 가장 잘 보여주는 증거는 무엇인가?",
                options=[
                    "실습 코드, 실행 결과, 개념 설명이 함께 제출된 결과",
                    "근거 없이 복사한 긴 설명문",
                    "수업 목표와 무관한 도구 목록",
                    "정답 없이 제출한 빈 파일",
                ],
                answer_index=0,
                explanation="실습형 수업은 코드 결과와 설명이 학습목표를 함께 입증해야 한다.",
                citation_ids=rotated_citations[0],
                ncs_alignment=primary_alignment,
            ),
            MultipleChoiceQuestion(
                question=f"NCS {primary_alignment[0].unit_name if primary_alignment else '능력단위'}와 가장 직접적으로 연결되는 활동은 무엇인가?",
                options=[
                    "근거 자료의 개념을 활용해 재현 가능한 실습 절차를 작성한다.",
                    "수업과 무관한 고급 이론만 암기한다.",
                    "평가 기준 없이 결과만 제출한다.",
                    "출처를 제거하고 문장을 다시 작성한다.",
                ],
                answer_index=0,
                explanation="NCS 기반 산출물은 수행 가능한 활동과 평가 기준으로 연결되어야 한다.",
                citation_ids=rotated_citations[1],
                ncs_alignment=primary_alignment,
            ),
            MultipleChoiceQuestion(
                question="list 또는 dictionary를 활용한 자동화 실습에서 가장 적절한 평가 기준은 무엇인가?",
                options=[
                    "입력 데이터를 자료구조로 저장하고 필요한 값을 정확히 처리한다.",
                    "자료구조를 쓰지 않고 결과를 임의로 적는다.",
                    "실행하지 않은 코드를 제출한다.",
                    "학습목표와 무관한 화면 꾸미기만 수행한다.",
                ],
                answer_index=0,
                explanation="자료구조 활용 수업에서는 데이터 저장, 접근, 처리의 정확성이 핵심 평가 기준이다.",
                citation_ids=rotated_citations[2],
                ncs_alignment=alignments,
            ),
            MultipleChoiceQuestion(
                question="근거 자료 기반 수업 초안을 검수할 때 가장 먼저 확인해야 할 사항은 무엇인가?",
                options=[
                    "핵심 설명과 평가 문항이 citation으로 추적되는지 확인한다.",
                    "citation을 모두 삭제해 문서를 짧게 만든다.",
                    "근거와 다른 수치를 임의로 추가한다.",
                    "검수 없이 바로 배포한다.",
                ],
                answer_index=0,
                explanation="근거 추적은 RAG 기반 생성물의 할루시네이션을 줄이고 강사 검수를 돕는다.",
                citation_ids=rotated_citations[3],
                ncs_alignment=primary_alignment,
            ),
            MultipleChoiceQuestion(
                question="수행평가 루브릭에 반드시 포함해야 할 요소로 가장 적절한 것은 무엇인가?",
                options=[
                    "학습목표, 근거 자료, 제출물 품질을 함께 판단하는 기준",
                    "강사 이름만 확인하는 기준",
                    "문서 분량만 평가하는 기준",
                    "수강생의 배경지식과 무관한 기준",
                ],
                answer_index=0,
                explanation="루브릭은 수행 결과가 목표와 근거에 맞는지 확인할 수 있어야 한다.",
                citation_ids=rotated_citations[4],
                ncs_alignment=primary_alignment,
            ),
        ],
        performance_task=PerformanceTask(
            title=f"{project.lesson_title} 수행평가",
            description="함수 또는 자료구조를 활용해 간단한 자동화 코드를 작성하고, 실행 결과와 근거 개념 설명을 함께 제출한다.",
            rubric=[
                "근거 자료의 핵심 개념을 코드와 설명에 정확히 반영했다.",
                "실습 절차와 실행 결과가 재현 가능하다.",
                "제출물이 학습목표와 NCS 수행 기준을 검증할 수 있다.",
            ],
            citation_ids=practice_citations,
            ncs_alignment=alignments,
        ),
    )

    return LessonPackage(
        package_id=package_id,
        project_id=project.project_id,
        status=PackageStatus.DRAFT,
        lesson_plan=lesson_plan,
        practice=practice,
        assessment=assessment,
        evidence_sources=_citation_details(retrieved_chunks),
        template_metadata=StandardTemplateMetadata(lesson_duration_min=120),
    )


def _citation_ids(chunks: list[MaterialChunk], *, limit: int = 3) -> list[str]:
    return [chunk.chunk_id for chunk in chunks[: max(1, limit)]]


def _citation_ids_for(chunks: list[MaterialChunk], *, preferred_index: int, limit: int) -> list[str]:
    if not chunks:
        return []
    ordered: list[MaterialChunk] = []
    preferred = chunks[preferred_index % len(chunks)]
    ordered.append(preferred)
    for chunk in chunks:
        if chunk.chunk_id != preferred.chunk_id:
            ordered.append(chunk)
        if len(ordered) >= limit:
            break
    return [chunk.chunk_id for chunk in ordered[:limit]]


def _citation_details(chunks: list[MaterialChunk]) -> list[CitationDetail]:
    details: list[CitationDetail] = []
    for chunk in chunks:
        details.append(
            CitationDetail(
                chunk_id=chunk.chunk_id,
                source_name=chunk.source_name,
                source_url=_optional_metadata(chunk, "source_url"),
                license=_optional_metadata(chunk, "license"),
                source_file=_optional_metadata(chunk, "source_file"),
                page=chunk.page,
                excerpt=_truncate_words(chunk.text, max_chars=240),
            )
        )
    return details


def _optional_metadata(chunk: MaterialChunk, key: str) -> str | None:
    value = chunk.metadata.get(key)
    if value is None or value == "":
        return None
    return str(value)


def _ncs_alignments(project: Project) -> list[NCSAlignment]:
    alignments: list[NCSAlignment] = []
    for unit in project.ncs_units:
        criteria = unit.elements or [f"{unit.unit_name} 능력단위와 차시 학습목표를 연결한다."]
        alignments.append(
            NCSAlignment(
                unit_code=unit.unit_code,
                unit_name=unit.unit_name,
                performance_criteria=criteria,
            )
        )
    return alignments


def _alignment_summary(alignments: list[NCSAlignment]) -> str:
    if not alignments:
        return "강사 검수 단계에서 NCS 능력단위 추가 확인 필요"
    return "; ".join(f"{item.unit_code} {item.unit_name}" for item in alignments)


def _evidence_summary(chunks: list[MaterialChunk]) -> str:
    summaries: list[str] = []
    for chunk in chunks[:3]:
        section = chunk.metadata.get("section") or chunk.source_name
        summaries.append(f"{chunk.chunk_id} {section}: {_truncate_words(chunk.text, max_chars=90)}")
    return " / ".join(summaries)


def _practice_keywords(*, project: Project, retrieved_chunks: list[MaterialChunk]) -> list[str]:
    text = _practice_source_text(project=project, retrieved_chunks=retrieved_chunks)
    keywords = ["실행 결과 검증"]
    candidates = [
        ("라이브러리 활용", ["라이브러리", "library", "pandas", "dataframe", "series"]),
        ("함수화", ["함수", "function", "def"]),
        ("list 또는 dictionary", ["list", "dictionary"]),
        ("정렬 또는 탐색", ["정렬", "탐색", "sort", "search"]),
    ]
    for keyword, triggers in candidates:
        if any(trigger in text for trigger in triggers):
            keywords.append(keyword)
    return keywords


def _truncate_words(value: str, *, max_chars: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 3].rstrip() + "..."


def _practice_source_text(*, project: Project, retrieved_chunks: list[MaterialChunk]) -> str:
    values: list[str] = [
        project.course_title,
        project.lesson_title,
        " ".join(project.learning_objectives),
    ]
    for unit in project.ncs_units:
        values.extend([unit.unit_code, unit.unit_name, " ".join(unit.elements)])
    for chunk in retrieved_chunks:
        values.extend(
            [
                chunk.chunk_id,
                chunk.document_id,
                chunk.source_name,
                chunk.text,
                " ".join(str(value) for value in chunk.metadata.values()),
            ]
        )
    return " ".join(values).casefold()
