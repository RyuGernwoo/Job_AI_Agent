from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from lectureops_agent.models.schemas import NCSUnit, ProjectCreate
from lectureops_agent.services.dataset_loader import DEFAULT_DATASET_PROJECT_ID, load_processed_chunks
from lectureops_agent.services.generation_evaluation import evaluate_lesson_package, load_generation_gold
from lectureops_agent.services.generation_service import generate_lesson_package_with_log
from lectureops_agent.services.llm_provider import LLMProvider, create_llm_provider_from_env
from lectureops_agent.services.llm_provider_readiness import check_llm_provider_readiness
from lectureops_agent.services.mvp_demo_runner import run_mvp_demo
from lectureops_agent.services.retrieval_evaluation import evaluate_retrieval_gold, load_retrieval_gold
from lectureops_agent.services.vector_store import create_vector_store_from_env


def run_mvp_verification(
    *,
    data_dir: Path | str,
    output_dir: Path | str,
    project_id: str = DEFAULT_DATASET_PROJECT_ID,
    retrieval_top_k: int = 3,
    retrieval_candidate_k: int = 20,
    chunks_per_source: int = 2,
    demo_case_id: str = "g003",
    min_retrieval_hit_rate: float = 0.7,
    min_retrieval_mrr: float = 0.7,
    min_context_precision: float = 0.6,
    min_context_recall: float = 0.6,
    min_required_concept_coverage: float = 0.7,
    max_duplicate_ratio: float = 0.2,
    min_generation_case_pass_rate: float = 1.0,
    min_generation_quality_score: float = 0.9,
    min_citation_coverage: float = 0.9,
    min_ncs_alignment_coverage: float = 0.8,
    min_ncs_criterion_coverage: float = 0.9,
    min_ncs_assessment_coverage: float = 1.0,
    min_source_metadata_coverage: float = 0.9,
    min_assessment_quality: float = 1.0,
    min_duration_alignment: float = 0.9,
    min_structured_output_rate: float = 1.0,
    min_trace_id_coverage: float = 1.0,
    require_real_llm: bool = False,
    require_live_rag: bool = False,
    llm_provider: LLMProvider | None = None,
    validation_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from scripts.validate_mvp_dataset import validate_dataset

    data_dir = Path(data_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = f"mvp-verification-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    validation = validation_report or validate_dataset(data_dir)
    provider_readiness = check_llm_provider_readiness()
    thresholds = {
        "min_retrieval_hit_rate": min_retrieval_hit_rate,
        "retrieval_candidate_k": retrieval_candidate_k,
        "min_retrieval_mrr": min_retrieval_mrr,
        "min_context_precision": min_context_precision,
        "min_context_recall": min_context_recall,
        "min_required_concept_coverage": min_required_concept_coverage,
        "max_duplicate_ratio": max_duplicate_ratio,
        "min_generation_case_pass_rate": min_generation_case_pass_rate,
        "min_generation_quality_score": min_generation_quality_score,
        "min_citation_coverage": min_citation_coverage,
        "min_ncs_alignment_coverage": min_ncs_alignment_coverage,
        "min_ncs_criterion_coverage": min_ncs_criterion_coverage,
        "min_ncs_assessment_coverage": min_ncs_assessment_coverage,
        "min_source_metadata_coverage": min_source_metadata_coverage,
        "min_assessment_quality": min_assessment_quality,
        "min_duration_alignment": min_duration_alignment,
        "min_structured_output_rate": min_structured_output_rate,
        "min_trace_id_coverage": min_trace_id_coverage,
        "require_real_llm": require_real_llm,
        "require_live_rag": require_live_rag,
    }

    provider_gate = bool(provider_readiness["ready"]) and (
        not require_real_llm or bool(provider_readiness["real_provider_ready"])
    )
    gates = {
        "dataset_valid": not validation["errors"],
        "provider_ready": bool(provider_readiness["ready"]),
        "real_provider_ready_if_required": not require_real_llm or bool(provider_readiness["real_provider_ready"]),
        "live_rag_ready_if_required": not require_live_rag,
        "retrieval_passed": False,
        "generation_passed": False,
        "demo_passed": False,
    }

    retrieval_report: dict[str, Any]
    generation_report: dict[str, Any]
    demo_report: dict[str, Any]

    if validation["errors"]:
        retrieval_report = _skipped_report("dataset validation failed")
        generation_report = _skipped_report("dataset validation failed")
        demo_report = _skipped_report("dataset validation failed")
    else:
        chunks = load_processed_chunks(data_dir, project_id=project_id)
        try:
            vector_store = create_vector_store_from_env() if require_live_rag else None
            retrieval_report = _run_retrieval_eval(
                data_dir=data_dir,
                chunks=chunks,
                project_id=project_id,
                top_k=retrieval_top_k,
                candidate_k=retrieval_candidate_k,
                vector_store=vector_store,
                thresholds=thresholds,
            )
            gates["live_rag_ready_if_required"] = not require_live_rag or retrieval_report["backend"].startswith(
                "live:"
            )
            gates["retrieval_passed"] = bool(retrieval_report["passed_quality_gate"])
        except Exception as exc:
            retrieval_report = _skipped_report(f"retrieval evaluation failed: {type(exc).__name__}: {exc}")
            gates["live_rag_ready_if_required"] = False

        if provider_gate:
            provider = llm_provider or create_llm_provider_from_env()
            try:
                generation_report = _run_generation_eval(
                    data_dir=data_dir,
                    chunks=chunks,
                    project_id=project_id,
                    chunks_per_source=chunks_per_source,
                    min_case_pass_rate=min_generation_case_pass_rate,
                    llm_provider=provider,
                    thresholds=thresholds,
                    require_structured_output=require_real_llm,
                )
                gates["generation_passed"] = bool(generation_report["passed_quality_gate"])
            except Exception as exc:
                generation_report = _skipped_report(
                    f"generation evaluation failed: {type(exc).__name__}: {exc}"
                )

            try:
                demo_report = _run_demo_eval(
                    data_dir=data_dir,
                    output_dir=output_dir / "demo",
                    case_id=demo_case_id,
                    chunks_per_source=chunks_per_source,
                    llm_provider=provider,
                )
                gates["demo_passed"] = bool(demo_report["passed"])
            except Exception as exc:
                demo_report = _skipped_report(f"demo evaluation failed: {type(exc).__name__}: {exc}")
        else:
            generation_report = _skipped_report("LLM provider is not ready")
            demo_report = _skipped_report("LLM provider is not ready")

    report = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data_dir": str(data_dir),
        "output_dir": str(output_dir),
        "thresholds": thresholds,
        "passed": all(gates.values()),
        "gates": gates,
        "validation": validation,
        "provider_readiness": provider_readiness,
        "retrieval": retrieval_report,
        "generation": generation_report,
        "demo": demo_report,
    }
    return report


def render_mvp_verification_markdown(report: dict[str, Any]) -> str:
    validation = report["validation"]
    provider = report["provider_readiness"]
    retrieval = report["retrieval"]
    generation = report["generation"]
    demo = report["demo"]
    status = "PASS" if report["passed"] else "FAIL"

    lines = [
        "# LessonPack AI MVP 품질 평가 결과",
        "",
        f"- 실행 ID: `{report['run_id']}`",
        f"- 실행 시각(UTC): `{report['created_at']}`",
        f"- 종합 판정: **{status}**",
        f"- 데이터 경로: `{report['data_dir']}`",
        f"- 산출물 경로: `{report['output_dir']}`",
        "",
        "## 1. 평가 범위",
        "",
        "이번 평가는 고정 gold set을 사용해 데이터 무결성, 검색 품질, 생성 품질, DOCX/PPTX 산출물 생성을 측정한다. ",
        "`require_live_rag=true`이면 Supabase pgvector 검색 결과를 사용하고, `require_real_llm=true`이면 실제 LiteLLM 응답의 구조화 적용까지 통과 조건으로 둔다.",
        "",
        "## 2. 품질 게이트",
        "",
        "| 게이트 | 결과 |",
        "|---|---:|",
    ]
    for gate, passed in report["gates"].items():
        lines.append(f"| `{gate}` | {'PASS' if passed else 'FAIL'} |")

    lines.extend(
        [
            "",
            "## 3. 측정 기준",
            "",
            "| 기준 | 값 |",
            "|---|---:|",
        ]
    )
    for threshold, value in report["thresholds"].items():
        lines.append(f"| `{threshold}` | `{value}` |")

    lines.extend(
        [
            "",
            "## 4. 데이터셋",
            "",
            f"- 오류: {len(validation['errors'])}건",
            f"- 경고: {len(validation['warnings'])}건",
            f"- 데이터 수량: `{validation['counts']}`",
            "",
            "## 5. 실행 환경",
            "",
            f"- LLM provider: `{provider.get('provider')}`",
            f"- 기본 모델: `{provider.get('model')}`",
            f"- provider 준비 상태: `{provider.get('ready')}`",
            f"- 실제 provider 준비 상태: `{provider.get('real_provider_ready')}`",
            f"- 검색 backend: `{retrieval.get('backend', '실행 실패')}`",
            f"- 실제 LLM 필수: `{report['thresholds'].get('require_real_llm')}`",
            f"- 실제 RAG 필수: `{report['thresholds'].get('require_live_rag')}`",
            "",
            "## 6. 검색 품질",
            "",
            "| 지표 | 결과 |",
            "|---|---:|",
            f"| 평가 query | {retrieval.get('total_queries', 0)} |",
            f"| Hit Rate@K | {retrieval.get('hit_rate', 0)} |",
            f"| MRR | {retrieval.get('mean_reciprocal_rank', 0)} |",
            f"| Context Precision | {retrieval.get('average_context_precision', 0)} |",
            f"| Context Recall | {retrieval.get('average_context_recall', 0)} |",
            f"| nDCG@K | {retrieval.get('average_ndcg_at_k', 0)} |",
            f"| 필수 개념 충족률 | {retrieval.get('average_required_concept_coverage', 0)} |",
            f"| 중복 chunk 비율 | {retrieval.get('average_duplicate_ratio', 0)} |",
            f"| 빈 검색률 | {retrieval.get('empty_result_rate', 0)} |",
            "",
            "### 검색 게이트별 판정",
            "",
            "| 검사 | 결과 |",
            "|---|---:|",
        ]
    )
    for check, passed in retrieval.get("quality_checks", {}).items():
        lines.append(f"| `{check}` | {'PASS' if passed else 'FAIL'} |")

    lines.extend(
        [
            "",
            "## 7. 생성 품질",
            "",
            "| 지표 | 결과 |",
            "|---|---:|",
            f"| 평가 case | {generation.get('total_cases', 0)} |",
            f"| case 통과율 | {generation.get('case_pass_rate', 0)} |",
            f"| 종합 자동 점수 | {generation.get('average_score', 0)} |",
            f"| citation 연결률 | {generation.get('average_citation_coverage', 0)} |",
            f"| citation-source 해소율 | {generation.get('average_citation_source_resolution', 0)} |",
            f"| NCS 연결률 | {generation.get('average_ncs_alignment_coverage', 0)} |",
            f"| NCS 수행준거 커버리지 | {generation.get('average_ncs_criterion_coverage', 0)} |",
            f"| NCS 평가 커버리지 | {generation.get('average_ncs_assessment_coverage', 0)} |",
            f"| 출처 메타데이터 완성도 | {generation.get('average_source_metadata_coverage', 0)} |",
            f"| 평가 문항 구조 완성도 | {generation.get('average_assessment_quality', 0)} |",
            f"| 수업시간 일치도 | {generation.get('average_duration_alignment', 0)} |",
            f"| 객관식 문항 고유성 | {generation.get('average_mcq_uniqueness', 0)} |",
            f"| 실제 LLM 구조화 출력 적용률 | {generation.get('structured_output_rate', 0)} |",
            f"| generation log trace ID 보존율 | {generation.get('trace_id_coverage', 0)} |",
            f"| 평균 LLM 생성 시도 횟수 | {generation.get('average_generation_attempts', 0)} |",
            f"| schema repair 성공 case | {generation.get('repaired_case_count', 0)} |",
            f"| 설정된 provider chain | `{generation.get('provider_names', [])}` |",
            "",
            "### 생성 게이트별 판정",
            "",
            "| 검사 | 결과 |",
            "|---|---:|",
        ]
    )
    for check, passed in generation.get("quality_checks", {}).items():
        lines.append(f"| `{check}` | {'PASS' if passed else 'FAIL'} |")

    lines.extend(
        [
            "",
            "### 생성 case별 결과",
            "",
            "| Case | Provider | 시도 | 구조화 출력 | 점수 | 판정 |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for case in generation.get("cases", []):
        evaluation = case.get("evaluation", {})
        lines.append(
            f"| `{case.get('case_id')}` | `{case.get('provider_name')}` | "
            f"{case.get('generation_attempts', 0)} | {case.get('structured_output_applied', False)} | "
            f"{evaluation.get('score', 0)} | "
            f"{'PASS' if evaluation.get('passed') else 'FAIL'} |"
        )

    lines.extend(
        [
            "",
            "## 8. 산출물 검증",
            "",
            f"- demo 통과: `{demo.get('passed', False)}`",
            f"- DOCX: `{demo.get('docx_path', '')}`",
            f"- PPTX: `{demo.get('pptx_path', '')}`",
            f"- 상세 JSON: `{demo.get('report_path', '')}`",
            f"- DOCX/PPTX 외형 품질: `{'PASS' if (demo.get('export_quality') or {}).get('passed') else 'FAIL'}`",
            "",
            "## 9. 실패 상세",
            "",
        ]
    )
    failed_retrieval_cases = [
        case
        for case in retrieval.get("cases", [])
        if not case.get("hit") or (case.get("required_concepts") or {}).get("coverage", 0) < 1.0
    ]
    if failed_retrieval_cases:
        lines.append("### 검색 실패 또는 개념 누락 query")
        lines.append("")
        for case in failed_retrieval_cases:
            missing_concepts = (case.get("required_concepts") or {}).get("missing", [])
            lines.append(
                f"- `{case.get('query_id')}`: hit=`{case.get('hit')}`, "
                f"retrieved=`{case.get('retrieved_chunk_ids', [])}`, missing_concepts=`{missing_concepts}`"
            )
        lines.append("")

    failed_generation_cases = [
        case
        for case in generation.get("cases", [])
        if not (case.get("evaluation") or {}).get("passed") or not case.get("structured_output_applied")
    ]
    if failed_generation_cases:
        lines.append("### 생성 실패 또는 fallback 적용 case")
        lines.append("")
        for case in failed_generation_cases:
            evaluation = case.get("evaluation") or {}
            lines.append(
                f"- `{case.get('case_id')}`: structured_output=`{case.get('structured_output_applied')}`, "
                f"attempts=`{case.get('generation_attempts', 0)}`, "
                f"missing_practice_items=`{evaluation.get('missing_practice_items', [])}`, "
                f"schema_errors=`{case.get('schema_validation_errors', [])}`"
            )
        lines.append("")

    if not failed_retrieval_cases and not failed_generation_cases:
        lines.extend(["- 실패 또는 필수 개념 누락 case 없음.", ""])

    lines.extend(["## 10. 후속 조치", ""])
    if report["passed"]:
        lines.extend(
            [
                "1. 현재 자동 품질 게이트를 CI 또는 정기 운영 검증에 고정해 회귀를 감지한다.",
                "2. retrieval gold와 generation gold를 다른 직무 분야로 확장해 일반화 범위를 넓힌다.",
                "3. 최소 2명의 강사·예비 강사에게 사람 평가 루브릭을 적용한다.",
            ]
        )
    else:
        lines.extend(
            [
                "1. 실패 query의 source/NCS 필터와 lexical reranking을 조정한다.",
                "2. 실습 산출물에 gold 핵심 개념이 포함되도록 생성 프롬프트와 후처리 검사를 보완한다.",
                "3. schema 오류 기록을 분석하고 JSON repair 재시도 규칙을 조정한다.",
                "4. generation log의 trace ID로 Langfuse 대시보드 수집 여부를 확인한다.",
                "5. 자동 게이트 통과 후 최소 2명의 강사·예비 강사에게 사람 평가 루브릭을 적용한다.",
            ]
        )
    lines.extend(
        [
            "",
            "## 11. 해석 및 한계",
            "",
            "- 자동 평가는 구조, 검색 gold 일치, 근거 ID 유효성, NCS/출처 필드 완성도를 측정한다.",
            "- 문장의 교육적 정확성, 난이도 적절성, 현장 활용성은 강사 또는 예비 강사 평가를 추가해야 확정할 수 있다.",
            "- gold set은 현재 retrieval query 10건과 generation case 3건 규모이므로 다른 직무 분야로 일반화할 수 없다.",
            "- 사람 평가 루브릭은 준비되어 있지만 이번 자동 실행의 사람 평가는 `미실시`로 기록한다.",
            "",
        ]
    )
    if validation["errors"]:
        lines.extend(["## 데이터셋 오류", ""])
        lines.extend(f"- {error}" for error in validation["errors"])
        lines.append("")
    if provider.get("next_steps"):
        lines.extend(["## Provider 후속 조치", ""])
        lines.extend(f"- {step}" for step in provider["next_steps"])
        lines.append("")
    return "\n".join(lines)


def _run_retrieval_eval(
    *,
    data_dir: Path,
    chunks,
    project_id: str,
    top_k: int,
    candidate_k: int,
    vector_store,
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    gold_rows = load_retrieval_gold(data_dir / "gold" / "retrieval_gold.jsonl")
    retrieve_fn = None
    if vector_store is not None:
        retrieve_fn = lambda query, limit: [
            result.chunk
            for result in vector_store.query_scoped(
                project_id=project_id,
                baseline_project_id=project_id,
                query=query,
                top_k=limit,
                candidate_k=candidate_k,
                include_baseline=False,
            )
        ]
    report = evaluate_retrieval_gold(
        chunks=chunks,
        gold_rows=gold_rows,
        top_k=top_k,
        retrieve_fn=retrieve_fn,
    )
    report["backend"] = f"live:{type(vector_store).__name__}" if vector_store is not None else "local:lexical"
    quality_checks = {
        "hit_rate": report["hit_rate"] >= thresholds["min_retrieval_hit_rate"],
        "mean_reciprocal_rank": report["mean_reciprocal_rank"] >= thresholds["min_retrieval_mrr"],
        "context_precision": report["average_context_precision"] >= thresholds["min_context_precision"],
        "context_recall": report["average_context_recall"] >= thresholds["min_context_recall"],
        "required_concept_coverage": (
            report["average_required_concept_coverage"] >= thresholds["min_required_concept_coverage"]
        ),
        "duplicate_ratio": report["average_duplicate_ratio"] <= thresholds["max_duplicate_ratio"],
        "non_empty_results": report["empty_result_rate"] == 0.0,
    }
    report["quality_checks"] = quality_checks
    report["passed_quality_gate"] = all(quality_checks.values())
    return report


def _run_generation_eval(
    *,
    data_dir: Path,
    chunks,
    project_id: str,
    chunks_per_source: int,
    min_case_pass_rate: float,
    llm_provider: LLMProvider,
    thresholds: dict[str, Any],
    require_structured_output: bool,
) -> dict[str, Any]:
    generation_gold = load_generation_gold(data_dir / "gold" / "generation_gold.yaml")
    curriculum = _read_yaml(data_dir / "raw" / "curriculum" / "curriculum_python_prompt_automation.yaml")
    ncs_data = _read_yaml(data_dir / "raw" / "ncs" / "ncs_application_sw_programming.yaml")
    case_reports = []
    passed_cases = 0
    score_sum = 0.0
    citation_coverage_sum = 0.0
    ncs_alignment_sum = 0.0
    ncs_criterion_sum = 0.0
    ncs_assessment_sum = 0.0
    source_metadata_sum = 0.0
    assessment_quality_sum = 0.0
    duration_alignment_sum = 0.0
    citation_resolution_sum = 0.0
    mcq_uniqueness_sum = 0.0
    structured_output_count = 0
    trace_id_count = 0
    generation_attempt_sum = 0
    repaired_case_count = 0
    provider_names: set[str] = set()

    for case in generation_gold["cases"]:
        case_id = str(case["case_id"])
        selected_chunks = _select_chunks_for_case(
            chunks=chunks,
            source_ids=case["input"].get("source_ids", []),
            chunks_per_source=chunks_per_source,
        )
        if not selected_chunks:
            evaluation = {"passed": False, "score": 0.0, "error": "no chunks selected for case"}
            package_id = None
            retrieved_chunk_ids: list[str] = []
        else:
            project = _project_from_case(
                case=case,
                curriculum=curriculum,
                ncs_data=ncs_data,
                project_id=f"{project_id}-{case_id}",
            )
            result = generate_lesson_package_with_log(
                project=project,
                retrieved_chunks=selected_chunks,
                package_id=f"package-{case_id}",
                llm_provider=llm_provider,
            )
            retrieved_chunk_ids = [chunk.chunk_id for chunk in selected_chunks]
            evaluation = evaluate_lesson_package(
                package=result.package,
                expected=case["expected"],
                retrieved_chunk_ids=retrieved_chunk_ids,
            )
            package_id = result.package.package_id
            provider_names.add(result.log.provider_name)
            structured_output_count += int(result.log.structured_output_applied)
            trace_id_count += int(bool(result.log.trace_id))
            generation_attempt_sum += result.log.generation_attempts
            repaired_case_count += int(result.log.structured_output_applied and result.log.generation_attempts > 1)

        if evaluation["passed"]:
            passed_cases += 1
        score_sum += float(evaluation.get("score", 0.0))
        citation_coverage = evaluation.get("citation_coverage") or {}
        citation_coverage_sum += float(citation_coverage.get("coverage", 0.0))
        ncs_alignment_sum += float((evaluation.get("ncs_alignment_coverage") or {}).get("coverage", 0.0))
        ncs_criterion = evaluation.get("ncs_criterion_coverage") or {}
        ncs_criterion_sum += float(ncs_criterion.get("coverage", 0.0))
        ncs_assessment_sum += float(ncs_criterion.get("assessment_coverage", 0.0))
        source_metadata_sum += float((evaluation.get("source_metadata_coverage") or {}).get("coverage", 0.0))
        assessment_quality_sum += float((evaluation.get("assessment_quality") or {}).get("coverage", 0.0))
        duration_alignment_sum += float((evaluation.get("duration_alignment") or {}).get("score", 0.0))
        citation_resolution_sum += float(
            (evaluation.get("citation_source_resolution") or {}).get("coverage", 0.0)
        )
        mcq_uniqueness_sum += float((evaluation.get("mcq_uniqueness") or {}).get("coverage", 0.0))
        case_reports.append(
            {
                "case_id": case_id,
                "package_id": package_id,
                "source_ids": case["input"].get("source_ids", []),
                "retrieved_chunk_ids": retrieved_chunk_ids,
                "provider_name": result.log.provider_name if selected_chunks else None,
                "structured_output_applied": result.log.structured_output_applied if selected_chunks else False,
                "trace_id": result.log.trace_id if selected_chunks else None,
                "generation_attempts": result.log.generation_attempts if selected_chunks else 0,
                "schema_validation_errors": result.log.schema_validation_errors if selected_chunks else [],
                "evaluation": evaluation,
            }
        )

    total_cases = len(case_reports)
    case_pass_rate = round(passed_cases / total_cases, 4) if total_cases else 0.0
    metric = lambda total: round(total / total_cases, 4) if total_cases else 0.0
    report = {
        "total_cases": total_cases,
        "passed_cases": passed_cases,
        "case_pass_rate": case_pass_rate,
        "average_score": metric(score_sum),
        "average_citation_coverage": metric(citation_coverage_sum),
        "average_ncs_alignment_coverage": metric(ncs_alignment_sum),
        "average_ncs_criterion_coverage": metric(ncs_criterion_sum),
        "average_ncs_assessment_coverage": metric(ncs_assessment_sum),
        "average_source_metadata_coverage": metric(source_metadata_sum),
        "average_assessment_quality": metric(assessment_quality_sum),
        "average_duration_alignment": metric(duration_alignment_sum),
        "average_citation_source_resolution": metric(citation_resolution_sum),
        "average_mcq_uniqueness": metric(mcq_uniqueness_sum),
        "structured_output_rate": round(structured_output_count / total_cases, 4) if total_cases else 0.0,
        "trace_id_coverage": round(trace_id_count / total_cases, 4) if total_cases else 0.0,
        "average_generation_attempts": (
            round(generation_attempt_sum / total_cases, 4) if total_cases else 0.0
        ),
        "repaired_case_count": repaired_case_count,
        "provider_names": sorted(provider_names),
        "passed_min_case_pass_rate": case_pass_rate >= min_case_pass_rate,
        "cases": case_reports,
    }
    quality_checks = {
        "case_pass_rate": report["case_pass_rate"] >= thresholds["min_generation_case_pass_rate"],
        "quality_score": report["average_score"] >= thresholds["min_generation_quality_score"],
        "citation_coverage": report["average_citation_coverage"] >= thresholds["min_citation_coverage"],
        "citation_source_resolution": report["average_citation_source_resolution"] >= 1.0,
        "ncs_alignment": report["average_ncs_alignment_coverage"] >= thresholds["min_ncs_alignment_coverage"],
        "ncs_criterion_coverage": (
            report["average_ncs_criterion_coverage"] >= thresholds["min_ncs_criterion_coverage"]
        ),
        "ncs_assessment_coverage": (
            report["average_ncs_assessment_coverage"] >= thresholds["min_ncs_assessment_coverage"]
        ),
        "source_metadata": report["average_source_metadata_coverage"] >= thresholds["min_source_metadata_coverage"],
        "assessment_quality": report["average_assessment_quality"] >= thresholds["min_assessment_quality"],
        "duration_alignment": report["average_duration_alignment"] >= thresholds["min_duration_alignment"],
        "mcq_uniqueness": report["average_mcq_uniqueness"] >= 1.0,
        "structured_output": (
            not require_structured_output
            or report["structured_output_rate"] >= thresholds["min_structured_output_rate"]
        ),
        "trace_id_recording": (
            not require_structured_output
            or report["trace_id_coverage"] >= thresholds["min_trace_id_coverage"]
        ),
    }
    report["quality_checks"] = quality_checks
    report["passed_quality_gate"] = all(quality_checks.values())
    return report


def _run_demo_eval(
    *,
    data_dir: Path,
    output_dir: Path,
    case_id: str,
    chunks_per_source: int,
    llm_provider: LLMProvider,
) -> dict[str, Any]:
    from scripts.inspect_export_quality import inspect_exports

    report = run_mvp_demo(
        data_dir=data_dir,
        output_dir=output_dir,
        case_id=case_id,
        chunks_per_source=chunks_per_source,
        llm_provider=llm_provider,
    )
    docx_path = Path(report["docx_path"])
    pptx_path = Path(report["pptx_path"])
    report["docx_exists"] = docx_path.exists()
    report["pptx_exists"] = pptx_path.exists()
    report["export_quality"] = inspect_exports(
        docx_path=docx_path if report["docx_exists"] else None,
        pptx_path=pptx_path if report["pptx_exists"] else None,
    )
    report["passed"] = bool(
        report["evaluation"]["passed"]
        and report["docx_exists"]
        and report["pptx_exists"]
        and report["export_quality"]["passed"]
    )
    return report


def _project_from_case(
    *,
    case: dict[str, Any],
    curriculum: dict[str, Any],
    ncs_data: dict[str, Any],
    project_id: str,
):
    ncs_unit_id = str(case["input"].get("ncs_unit_id", ""))
    return ProjectCreate(
        course_type="ncs",
        course_title=curriculum.get("course_title", "Generative AI Python Basics"),
        lesson_title=curriculum.get("lesson_title", f"LessonPack AI evaluation case {case['case_id']}"),
        learner_profile=curriculum.get("learner_profile", "Job training learners"),
        learning_objectives=curriculum.get("learning_objectives") or ["Create a grounded lesson package draft."],
        ncs_units=[_ncs_unit_from_data(ncs_unit_id=ncs_unit_id, ncs_data=ncs_data)],
    ).to_project(project_id=project_id)


def _ncs_unit_from_data(*, ncs_unit_id: str, ncs_data: dict[str, Any]) -> NCSUnit:
    selected_units = ncs_data.get("selected_units", []) if isinstance(ncs_data, dict) else []
    for unit in selected_units:
        if str(unit.get("unit_code")) == ncs_unit_id:
            return NCSUnit(
                unit_code=ncs_unit_id,
                unit_name=str(unit.get("unit_name", ncs_unit_id)),
                elements=[str(topic) for topic in unit.get("learning_topics", [])],
            )
    return NCSUnit(
        unit_code=ncs_unit_id or "MVP-NCS",
        unit_name=ncs_unit_id or "MVP NCS",
        elements=["차시 학습목표에 해당하는 수행 결과를 설명할 수 있다."],
    )


def _select_chunks_for_case(*, chunks, source_ids: list[str], chunks_per_source: int):
    selected = []
    for source_id in source_ids:
        matching = [chunk for chunk in chunks if chunk.metadata.get("source_id") == source_id]
        selected.extend(matching[:chunks_per_source])
    return selected


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    return data if isinstance(data, dict) else {}


def _skipped_report(reason: str) -> dict[str, Any]:
    return {
        "skipped": True,
        "reason": reason,
    }
