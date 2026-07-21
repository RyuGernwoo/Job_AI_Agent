# LessonPack AI MVP 품질 평가 결과

- 실행 ID: `mvp-verification-20260721T064211Z`
- 실행 시각(UTC): `2026-07-21T06:43:24.836456+00:00`
- 종합 판정: **PASS**
- 데이터 경로: `C:\Users\qesad\OneDrive\Desktop\job_ai_agent\data`
- 산출물 경로: `outputs\eval-live`

## 1. 평가 범위

이번 평가는 고정 gold set을 사용해 데이터 무결성, 검색 품질, 생성 품질, DOCX/PPTX 산출물 생성을 측정한다. 
`require_live_rag=true`이면 Supabase pgvector 검색 결과를 사용하고, `require_real_llm=true`이면 실제 LiteLLM 응답의 구조화 적용까지 통과 조건으로 둔다.

## 2. 품질 게이트

| 게이트 | 결과 |
|---|---:|
| `dataset_valid` | PASS |
| `provider_ready` | PASS |
| `real_provider_ready_if_required` | PASS |
| `live_rag_ready_if_required` | PASS |
| `retrieval_passed` | PASS |
| `generation_passed` | PASS |
| `demo_passed` | PASS |

## 3. 측정 기준

| 기준 | 값 |
|---|---:|
| `min_retrieval_hit_rate` | `0.7` |
| `retrieval_candidate_k` | `20` |
| `min_retrieval_mrr` | `0.7` |
| `min_context_precision` | `0.6` |
| `min_context_recall` | `0.6` |
| `min_required_concept_coverage` | `0.7` |
| `max_duplicate_ratio` | `0.2` |
| `min_generation_case_pass_rate` | `1.0` |
| `min_generation_quality_score` | `0.9` |
| `min_citation_coverage` | `0.9` |
| `min_ncs_alignment_coverage` | `0.8` |
| `min_source_metadata_coverage` | `0.9` |
| `min_assessment_quality` | `1.0` |
| `min_duration_alignment` | `0.9` |
| `min_structured_output_rate` | `1.0` |
| `min_trace_id_coverage` | `1.0` |
| `require_real_llm` | `True` |
| `require_live_rag` | `True` |

## 4. 데이터셋

- 오류: 0건
- 경고: 0건
- 데이터 수량: `{'chunks': 43, 'chunk_index_rows': 43, 'selected_sources': 6, 'source_file_map_rows': 49, 'retrieval_gold': 10, 'generation_gold': 3}`

## 5. 실행 환경

- LLM provider: `litellm`
- 기본 모델: `gpt-4o-mini`
- provider 준비 상태: `True`
- 실제 provider 준비 상태: `True`
- 검색 backend: `live:SupabaseVectorStore`
- 실제 LLM 필수: `True`
- 실제 RAG 필수: `True`

## 6. 검색 품질

| 지표 | 결과 |
|---|---:|
| 평가 query | 10 |
| Hit Rate@K | 1.0 |
| MRR | 1.0 |
| Context Precision | 0.8333 |
| Context Recall | 0.8333 |
| nDCG@K | 0.8642 |
| 필수 개념 충족률 | 1.0 |
| 중복 chunk 비율 | 0.0 |
| 빈 검색률 | 0.0 |

### 검색 게이트별 판정

| 검사 | 결과 |
|---|---:|
| `hit_rate` | PASS |
| `mean_reciprocal_rank` | PASS |
| `context_precision` | PASS |
| `context_recall` | PASS |
| `required_concept_coverage` | PASS |
| `duplicate_ratio` | PASS |
| `non_empty_results` | PASS |

## 7. 생성 품질

| 지표 | 결과 |
|---|---:|
| 평가 case | 3 |
| case 통과율 | 1.0 |
| 종합 자동 점수 | 1.0 |
| citation 연결률 | 1.0 |
| citation-source 해소율 | 1.0 |
| NCS 연결률 | 1.0 |
| 출처 메타데이터 완성도 | 1.0 |
| 평가 문항 구조 완성도 | 1.0 |
| 수업시간 일치도 | 1.0 |
| 객관식 문항 고유성 | 1.0 |
| 실제 LLM 구조화 출력 적용률 | 1.0 |
| generation log trace ID 보존율 | 1.0 |
| 평균 LLM 생성 시도 횟수 | 1.0 |
| schema repair 성공 case | 0 |
| 설정된 provider chain | `['litellm:gpt-4o-mini -> gemini/gemini-2.0-flash']` |

### 생성 게이트별 판정

| 검사 | 결과 |
|---|---:|
| `case_pass_rate` | PASS |
| `quality_score` | PASS |
| `citation_coverage` | PASS |
| `citation_source_resolution` | PASS |
| `ncs_alignment` | PASS |
| `source_metadata` | PASS |
| `assessment_quality` | PASS |
| `duration_alignment` | PASS |
| `mcq_uniqueness` | PASS |
| `structured_output` | PASS |
| `trace_id_recording` | PASS |

### 생성 case별 결과

| Case | Provider | 시도 | 구조화 출력 | 점수 | 판정 |
|---|---|---:|---:|---:|---:|
| `g001` | `litellm:gpt-4o-mini -> gemini/gemini-2.0-flash` | 1 | True | 1.0 | PASS |
| `g002` | `litellm:gpt-4o-mini -> gemini/gemini-2.0-flash` | 1 | True | 1.0 | PASS |
| `g003` | `litellm:gpt-4o-mini -> gemini/gemini-2.0-flash` | 1 | True | 1.0 | PASS |

## 8. 산출물 검증

- demo 통과: `True`
- DOCX: `outputs\eval-live\demo\g003_lesson_package.docx`
- PPTX: `outputs\eval-live\demo\g003_lesson_package.pptx`
- 상세 JSON: `outputs\eval-live\demo\g003_demo_report.json`
- DOCX/PPTX 외형 품질: `PASS`

## 9. 실패 상세

- 실패 또는 필수 개념 누락 case 없음.

## 10. 후속 조치

1. 현재 자동 품질 게이트를 CI 또는 정기 운영 검증에 고정해 회귀를 감지한다.
2. retrieval gold와 generation gold를 다른 직무 분야로 확장해 일반화 범위를 넓힌다.
3. 최소 2명의 강사·예비 강사에게 사람 평가 루브릭을 적용한다.

## 11. 해석 및 한계

- 자동 평가는 구조, 검색 gold 일치, 근거 ID 유효성, NCS/출처 필드 완성도를 측정한다.
- 문장의 교육적 정확성, 난이도 적절성, 현장 활용성은 강사 또는 예비 강사 평가를 추가해야 확정할 수 있다.
- gold set은 현재 retrieval query 10건과 generation case 3건 규모이므로 다른 직무 분야로 일반화할 수 없다.
- 사람 평가 루브릭은 준비되어 있지만 이번 자동 실행의 사람 평가는 `미실시`로 기록한다.

