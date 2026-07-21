# LessonPack AI RAG 구축 및 연동 기획서

작성일: 2026-07-21
대상: LessonPack AI 직업훈련 강의 운영 보조 MVP
관련 문서: [구현명세서](01_구현명세서.md), [데이터셋 운영 문서](../../data/README_DATASET.md), [검증 프로토콜](03_검증_프로토콜.md), [체크포인트 보완 기획서](06_체크포인트_보완_기획서.md)

---

## 0. 구현 반영 상태

2026-07-21 기준 다음 항목이 코드에 반영되었다.

| 항목 | 상태 | 구현 위치 |
| --- | --- | --- |
| 서버 주도 검색·생성 | 완료 | `/rag/retrieve`, `/rag/generate`, `/api/retrieval-runs/{run_id}` |
| 프로젝트·문서·검색·생성 run 영속 모델 | 완료 | `services/rag_repository.py`, `002_rag_persistence.sql` |
| 프로젝트 자료 + `mvp-dataset` scope 검색 | 완료 | `services/rag_service.py`, `services/vector_store.py` |
| 검색 run·생성 로그·Langfuse trace ID 연결 | 완료 | `GenerationLog`, `llm_trace_context` |
| 임베딩 provider와 차원 검증 | 완료 | hash 호환 모드, LiteLLM 임베딩 모드 |
| 자동 검증 | 완료 | RAG API, scoped 검색, 임베딩, Supabase repository 테스트 |
| 외부 Supabase migration 적용 | 완료 | `002_rag_persistence.sql` 적용 및 persistence table 확인 |
| 1536차원 semantic embedding 재색인 | 완료 | 43개 baseline chunk를 LiteLLM/OpenAI `text-embedding-3-small`으로 `embedding_v2`에 upsert, live query 확인 |
| Lovable UI 신규 endpoint 전환 | 별도 UI 저장소 작업 필요 | 현재 백엔드 API 계약과 UI 프롬프트 문서 제공 |

기존 `/retrieve`, `/generate`는 호환성을 위해 유지하지만 운영 UI는 `/rag/retrieve`, `/rag/generate`를 사용해야 한다.

## 1. 목적과 완료 기준

이 문서는 강사 질의와 업로드 교재를 근거로 교안·실습·평가를 생성하는 **서버 주도 RAG**를 구축하기 위한 실행 계획이다. 목표는 단순히 Supabase에 chunk를 저장하는 것이 아니라, 검색 결과가 생성 프롬프트와 최종 출처 표기로 추적되는 흐름을 완성하는 것이다.

완료된 RAG는 다음 조건을 만족해야 한다.

1. 강사 질의 또는 차시 정보로 Supabase `lessonpack_chunks`를 검색한다.
2. 검색된 chunk만 생성 프롬프트의 근거로 전달한다.
3. 생성 항목의 citation ID는 실제 검색 결과의 chunk ID 집합 안에만 존재한다.
4. 기본 데이터셋과 강사 업로드 자료를 권한·프로젝트 범위에 맞게 함께 검색한다.
5. 검색 조건, 결과 ID, 점수, 생성에 사용된 근거를 Langfuse와 생성 로그에서 추적할 수 있다.

MVP 범위는 1개 차시와 최대 5개 근거 chunk의 생성이다. 다중 테넌트 권한 관리, 전체 과정 자동 생성, 웹 크롤링 기반 지식 수집은 이번 범위에서 제외한다.

---

## 2. 현재 상태와 문제 정의

### 2.1 구현되어 있는 요소

| 영역 | 현재 상태 | 근거 코드/자산 |
| --- | --- | --- |
| 벡터 저장 | Supabase `lessonpack_chunks`, pgvector HNSW index, `match_lessonpack_chunks` RPC 구현 | `supabase/migrations/001_lessonpack_vectors.sql` |
| 데이터 적재 | 전처리 데이터 43개 chunk가 `mvp-dataset` 프로젝트 ID로 외부 Supabase에 적재됨 | `data/README_DATASET.md` |
| 검색 어댑터 | `SupabaseVectorStore.query()`가 RPC를 호출해 `MaterialChunk` 목록으로 변환 | `services/vector_store.py` |
| 생성 근거 | `generate_lesson_package_with_log()`가 전달받은 chunk를 프롬프트와 citation 검증에 사용 | `services/generation_service.py` |
| 배포 환경 | CI/CD가 `LECTUREOPS_VECTOR_STORE=supabase`를 GCE `.env`에 기록 | `.github/workflows/cd.yml` |

### 2.2 보완해야 할 문제

| ID | 문제 | 영향 | 개선 방향 |
| --- | --- | --- | --- |
| RAG-01 | 로컬 `config.yaml`의 저장소가 `memory`여서 `.env`의 Supabase 설정과 충돌 가능 | 실행 환경에 따라 검색 대상이 달라짐 | 개발/운영 설정을 분리하고 설정 우선순위를 단일화 |
| RAG-02 | `/generate`는 이미 선택된 `retrieved_chunks`를 받으며 Query로 검색하지 않음 | 클라이언트가 임의 근거를 주입할 수 있고 RAG 사용이 강제되지 않음 | 서버가 검색과 생성을 연속 수행하는 API 추가 |
| RAG-03 | API 프로젝트 정보는 프로세스 메모리에만 존재 | 재시작 후 `mvp-dataset`과 기존 프로젝트를 정상 조회할 수 없음 | 프로젝트·문서 메타데이터를 Supabase에 영속화 |
| RAG-04 | 기본 데이터셋은 `mvp-dataset`에 적재됐지만 일반 프로젝트 검색은 해당 ID만 검색 | 사전 적재 43개 chunk가 신규 UI 프로젝트에 활용되지 않음 | 기본 자료와 프로젝트 자료를 함께 검색하는 scope 설계 |
| RAG-05 | 초기 임베딩은 64차원 토큰 해시 방식 | 한국어 의미 유사도와 동의어 검색 성능이 제한됨 | 1536차원 단일 외부 임베딩 모델로 재색인 완료, legacy vector는 호환성 보존 |
| RAG-06 | 검색 결과와 생성 결과의 연결은 클라이언트 요청에 의존 | 실증·감사 시 근거 추적이 약함 | retrieval run과 generation run을 동일한 trace/run ID로 저장 |

---

## 3. 목표 아키텍처

```text
강사 입력: 과정/차시/NCS/질의/업로드 교재
              |
              v
프로젝트 및 문서 메타데이터 영속화 (Supabase Postgres)
              |
              v
문서 파싱 -> chunking -> 임베딩 생성 -> lessonpack_chunks upsert
              |
              v
Query Builder (차시명 + 학습목표 + NCS + 강사 질의)
              |
              v
Supabase pgvector + metadata filter + lexical rerank
              |
              v
상위 5개 근거 chunk / retrieval run 기록
              |
              v
LiteLLM 생성 (OpenAI primary, Gemini fallback)
              |
              v
Pydantic 구조 검증 + citation allow-list 검증
              |
              v
HITL 검수 -> 최종 근거 단원 포함 DOCX/PPTX export
```

### 3.1 책임 분리

| 계층 | 책임 | 금지 사항 |
| --- | --- | --- |
| UI | 질의 입력, 검색 결과 미리보기, 생성 요청, 강사 검수 | 검색 결과를 임의로 조작해 생성 근거로 제출하지 않음 |
| FastAPI | 프로젝트 확인, 검색 범위 결정, retrieval 실행, 생성 호출, 로그 저장 | 클라이언트가 보낸 임의 chunk를 운영 생성의 근거로 신뢰하지 않음 |
| RAG service | query 구성, 임베딩, 검색, 재순위화, threshold 적용 | 모델 응답 생성·검수 상태 변경을 담당하지 않음 |
| Supabase | chunk, 문서, 프로젝트, 검색 실행 이력의 영속화 | 서비스 역할 key를 브라우저로 노출하지 않음 |
| LLM service | 검색 근거를 이용한 구조화 생성과 fallback | 검색되지 않은 출처 ID를 생성하지 않음 |

---

## 4. 데이터·검색 설계

### 4.1 검색 범위

MVP는 다음 두 범위를 합쳐 검색한다.

| 범위 | project ID | 용도 | 우선순위 |
| --- | --- | --- | --- |
| 기본 검증 자료 | `mvp-dataset` | Python·NCS 등 사전 검수된 공통 예시 자료 | 보조 근거 |
| 강사 프로젝트 자료 | 현재 `project_id` | 강사가 업로드한 교재, 기관별 커리큘럼, NCS 매핑 | 최우선 근거 |

동일한 내용을 두 범위에서 찾은 경우 프로젝트 자료를 우선한다. 검색 결과에는 `scope` (`project` 또는 `baseline`)를 추가해 UI와 로그에서 구별한다.

### 4.2 영속 데이터 모델

기존 `lessonpack_chunks`는 유지하고, 다음 migration으로 메타데이터와 실행 이력을 보완한다.

| 테이블 | 핵심 열 | 목적 |
| --- | --- | --- |
| `lessonpack_projects` | `project_id`, 과정명, 차시명, 학습목표, NCS JSON, `created_at` | 재시작 이후에도 프로젝트 식별과 검색 범위를 유지 |
| `lessonpack_documents` | `document_id`, `project_id`, 파일명, SHA-256, 라이선스, source URL, 상태 | 중복 적재 방지, 저작권 정보 보존 |
| `lessonpack_chunks` | 기존 열 + `scope`, `embedding_model`, `embedding_version`, `content_hash` | 근거와 임베딩 버전 추적 |
| `lessonpack_retrieval_runs` | `run_id`, `project_id`, 원 질의, 정규화 질의, 선택 chunk IDs, scores, trace ID | 검색 재현·평가 |
| `lessonpack_generation_runs` | `package_id`, `retrieval_run_id`, 모델, fallback 여부, citation IDs, 상태 | 생성과 검색의 연결 |

`lessonpack_chunks`의 기존 `project_id` 필터는 유지한다. 여러 범위 검색을 위해 `match_lessonpack_chunks`를 `match_project_ids text[]` 입력을 받는 새 RPC로 확장하거나, 별도 `match_lessonpack_chunks_scoped` RPC를 추가한다. 기존 RPC는 하위 호환성을 위해 제거하지 않는다.

### 4.3 임베딩 정책

운영 RAG에는 LiteLLM을 통해 호출하는 **단일 임베딩 모델**을 사용한다. 기본 제안은 `text-embedding-3-small`이며, 모델명과 차원은 환경변수와 DB에 같이 저장한다.

```dotenv
LESSONPACK_EMBEDDING_PROVIDER=litellm
LESSONPACK_EMBEDDING_MODEL=text-embedding-3-small
LESSONPACK_EMBEDDING_DIMENSIONS=1536
LESSONPACK_SUPABASE_EMBEDDING_COLUMN=embedding_v2
LESSONPACK_SUPABASE_MATCH_FUNCTION=match_lessonpack_chunks_v2
LESSONPACK_EMBEDDING_VERSION=v2
LESSONPACK_RETRIEVAL_CANDIDATE_K=20
LESSONPACK_RETRIEVAL_TOP_K=5
LESSONPACK_RETRIEVAL_MIN_SCORE=0.45
```

- OpenAI 생성 모델의 Gemini fallback은 **생성 단계**에만 적용한다.
- 서로 다른 임베딩 모델의 벡터를 같은 column에 혼합하지 않는다.
- 임베딩 모델·차원이 바뀌면 새 column/collection을 만들거나 전체 chunk를 재색인한다.
- API quota 오류 시 다른 차원의 Gemini 임베딩으로 조용히 대체하지 않는다. 검색을 실패로 반환하고 재시도·운영 알림을 남긴다.
- 개발용 64차원 토큰 해시 임베딩은 `memory` provider의 단위 테스트 전용으로 유지하며, 운영 Supabase에는 사용하지 않는다.

### 4.4 Query Builder와 재순위화

생성 검색 질의는 다음 필드를 결합한다.

```text
{강사 자유 질의}
과정: {course_title}
차시: {lesson_title}
학습목표: {learning_objectives}
NCS: {unit_code} {unit_name} {performance_criteria}
```

검색 순서는 다음과 같다.

1. 빈 질의·길이·프로젝트 접근 범위를 검증한다.
2. 프로젝트 자료와 `mvp-dataset`에서 벡터 후보를 각각 최대 20개 검색한다.
3. 문서 상태, 라이선스, source URL, NCS code, 자료 유형으로 metadata filter를 적용한다.
4. 벡터 유사도와 키워드 일치도를 결합해 재순위화한다.
5. 중복 문서와 거의 같은 chunk를 제거하고 최대 5개를 선택한다.
6. threshold 미만이면 생성하지 않고 “근거 자료를 추가하거나 질의를 구체화”하도록 반환한다.

MVP의 재순위 점수는 다음처럼 단순하고 재현 가능하게 시작한다.

```text
final_score = 0.75 * vector_similarity + 0.20 * lexical_overlap + 0.05 * project_scope_bonus
```

### 4.5 출처·저작권 처리

- `source_name`, `source_url`, `license`, `source_file`, `page`를 chunk metadata 필수값으로 유지한다.
- 라이선스가 없거나 검수 상태가 `blocked`인 자료는 생성 검색 대상에서 제외한다.
- 본문에는 citation ID를 반복 노출하지 않고, 실제 사용된 근거만 원천별로 묶어 최종 DOCX/PPTX 근거 단원에 표시한다.
- Langfuse에는 원문 전체보다 chunk ID, source ID, 점수, 길이, hash를 우선 기록한다. 민감하거나 저작권 제약이 있는 본문은 tracing 입력 마스킹 정책을 적용한다.

---

## 5. API 및 서비스 연동 계획

### 5.1 신규 운영 API

기존 `/retrieve`, `/generate`는 개발·디버그 호환성을 위해 유지한다. 운영 UI는 아래 서버 주도 API를 사용하도록 전환한다.

| Method | Endpoint | 요청 | 응답 | 역할 |
| --- | --- | --- | --- | --- |
| POST | `/api/projects` | 프로젝트 정보 | 영속 프로젝트 | 프로젝트 생성·저장 |
| POST | `/api/projects/{project_id}/materials` | 파일·출처 metadata | 문서·chunk 요약 | 파싱, chunking, 임베딩, upsert |
| POST | `/api/projects/{project_id}/rag/retrieve` | `query`, `top_k` | `retrieval_run_id`, 근거 목록, 점수 | 서버 검색 및 검색 이력 저장 |
| POST | `/api/projects/{project_id}/rag/generate` | `query`, 선택 정책 | `LessonPackage`, `retrieval_run_id` | 검색과 생성의 원자적 연결 |
| GET | `/api/retrieval-runs/{run_id}` | 없음 | 질의, 결과 ID, 점수, trace ID | 근거 재현·감사 |

`/rag/generate`의 요청에는 `retrieved_chunks` 본문을 허용하지 않는다. 서버가 생성한 `retrieval_run_id`를 사용하거나 내부에서 즉시 검색하여, 클라이언트 근거 주입을 차단한다.

### 5.2 서비스 함수

```text
create_project()             -> lessonpack_projects upsert
ingest_material()            -> documents upsert -> chunks upsert -> embedding 기록
retrieve_evidence()          -> scoped RPC -> rerank -> retrieval_run 저장
generate_from_query()        -> retrieve_evidence -> LLM -> citation 검증 -> generation_run 저장
```

`generate_from_query()`는 다음 불변 조건을 강제한다.

1. `retrieval_run.project_id == request project_id`
2. `retrieved_chunk_ids`가 해당 retrieval run의 선택 ID와 일치
3. 모든 citation ID가 선택 ID의 부분집합
4. 출처 metadata 누락 chunk는 생성 결과의 최종 근거 단원에 포함하지 않음
5. 검색 결과가 없으면 LLM을 호출하지 않음

### 5.3 설정 우선순위 정리

현재처럼 YAML이 `memory`인데 `.env`가 `supabase`인 혼선을 없애기 위해 다음 중 하나만 채택한다.

| 환경 | 설정 파일 | vector store | 용도 |
| --- | --- | --- | --- |
| 단위 테스트 | `config.test.yaml` 또는 주입 객체 | `memory` | 네트워크 없는 테스트 |
| 로컬 Supabase 통합 테스트 | `config.local.yaml` | `supabase` | 실제 검색 확인 |
| GCE 운영 | `config.production.yaml` 또는 환경변수 전용 | `supabase` | 배포 서비스 |

권장 방식은 운영 환경에서 환경변수 전용을 유지하되, `LESSONPACK_CONFIG`가 설정되면 `vector_store.provider`도 명시적으로 `supabase`여야만 기동되도록 검증하는 것이다. 기동 로그에는 provider, table, match function, embedding model만 기록하며 key·URL 전체는 기록하지 않는다.

---

## 6. 단계별 구축 계획

| 단계 | 작업 | 산출물 | 완료 기준 |
| --- | --- | --- | --- |
| 1. 설정 정리 | 개발/운영 config 분리, 기동 시 provider 충돌 검증 | config 파일, readiness check | 운영 기동 로그가 `supabase`를 표시 |
| 2. 스키마 확장 | project/document/run tables와 scoped RPC migration 작성 | `002_rag_persistence.sql` | migration 적용 및 rollback 절차 확인 |
| 3. 임베딩 교체 | LiteLLM embedding client, 모델/차원 metadata, 43개 chunk 재색인 | ingestion script, 재색인 보고서 | 모든 chunk의 embedding version 일치 |
| 4. 검색 서비스 | query builder, scope 검색, rerank, threshold, retrieval run 저장 | `rag_service.py`, 단위 테스트 | top-k, score, scope가 재현됨 |
| 5. 생성 연동 | `/rag/generate`, citation allow-list, generation run 연결 | FastAPI endpoint, API 테스트 | 임의 chunk 주입 없이 생성 가능 |
| 6. UI 전환 | Lovable UI가 retrieve preview와 server-side generate를 사용 | UI API client 수정 | 검색 결과와 최종 출처가 일치 |
| 7. 실증·운영 | Gold set 평가, Langfuse trace, 오류/권한 테스트 | 검증 리포트, 운영 runbook | 아래 품질 기준 통과 |

단계 1~3은 데이터 모델 변경이므로 개발 Supabase 프로젝트에서 먼저 수행한다. 운영 테이블을 직접 삭제하지 않으며, 재색인은 새 `embedding_v2`와 version metadata만 같은 `chunk_id`에 upsert해 legacy `embedding`을 보존한다.

---

## 7. 검증 계획

### 7.1 자동 테스트

| 구분 | 검증 | 통과 기준 |
| --- | --- | --- |
| 단위 | query builder, metadata filter, citation allow-list | 전부 통과 |
| Supabase 통합 | 43개 chunk upsert, scoped RPC, top-k, 프로젝트 격리 | 결과 ID와 scope 일치 |
| API | `/rag/generate`가 내부 검색 결과만 생성에 사용 | 임의 `retrieved_chunks` 요청 거부 |
| 회귀 | 기존 `/retrieve`, `/generate`, export, HITL | 전체 테스트 통과 |
| 관측성 | retrieval run과 Langfuse trace가 동일 run ID를 가짐 | trace 1개 이상 확인 |

### 7.2 검색·생성 품질 기준

| 지표 | 측정 방식 | MVP 기준 |
| --- | --- | --- |
| Hit Rate@5 | retrieval gold 정답 chunk가 top-5에 1개 이상 포함 | 0.80 이상 |
| Context Precision@5 | 검색 결과 중 정답 chunk 비율 | 0.60 이상 |
| Context Recall@5 | 정답 chunk 회수 비율 | 0.70 이상 |
| Citation Validity | citation ID가 retrieval run 선택 ID에 포함되는 비율 | 1.00 |
| Source Metadata Coverage | 최종 근거의 URL·라이선스·원천명 충족 비율 | 1.00 |
| Unsupported Claim | 강사 루브릭에서 근거 없는 단정으로 판정된 핵심 주장 비율 | 10% 이하 |
| Retrieval Trace Coverage | 생성 run 중 retrieval run과 trace ID가 저장된 비율 | 1.00 |

### 7.3 실증 시나리오

1. `mvp-dataset`만 이용해 Python 함수·자료구조 질의 10개를 검색한다.
2. 신규 프로젝트에 강사 자료를 업로드하고, 같은 주제에서 프로젝트 자료가 기본 자료보다 우선되는지 확인한다.
3. 라이선스가 누락된 자료와 허용되지 않은 project ID를 검색 대상에서 제외하는지 확인한다.
4. 검색 결과가 없는 질의에서 LLM 호출 없이 안내 메시지를 반환하는지 확인한다.
5. 생성 결과의 citation과 최종 DOCX/PPTX 근거 단원이 retrieval run과 정확히 일치하는지 확인한다.
6. OpenAI 생성 실패 시 Gemini fallback이 수행돼도 retrieval run과 citation이 유지되는지 확인한다.

---

## 8. 운영·보안 원칙

- `SUPABASE_SERVICE_ROLE_KEY`, LLM key, Langfuse secret은 GCE `.env`와 GitHub Secrets에만 둔다. Lovable UI에는 어떤 key도 전달하지 않는다.
- Supabase RLS 정책은 브라우저 직접 접근이 아니라 FastAPI service role 접근을 전제로 설계한다. 이후 사용자 인증을 도입하면 `owner_id` 기준 RLS를 별도 설계한다.
- 업로드 파일은 content hash로 중복을 확인하고, 원문·추출본·embedding은 보존 기간과 삭제 요청 정책을 문서화한다.
- `mvp-dataset`은 읽기 전용 baseline으로 취급한다. 강사 업로드 자료가 baseline row를 덮어쓰지 않도록 `chunk_id`에 project/document namespace를 사용한다.
- query, score, chunk ID, 모델명, latency, fallback 여부를 구조화 로그로 남긴다. 원문 전체와 개인정보가 포함된 질의는 마스킹한다.

---

## 9. 완료 후 운영 절차

1. `/rag/retrieve`와 `/rag/generate` 통합 테스트를 실제 Supabase·LLM 환경에서 실행한다.
2. Langfuse에서 retrieval span, generation span, `retrieval_run_id`를 확인한다.
3. GCE에 새 환경변수를 반영하고 `/health/rag` 및 semantic retrieval을 재검증한다.
4. Lovable UI를 `/rag/retrieve`, `/rag/generate` endpoint 계약으로 전환한다.
5. GCE에 배포한 뒤 Lovable UI에서 업로드 → 검색 미리보기 → 생성 → 검수 → export를 수행한다.
6. 운영 Supabase에 migration을 적용하고, 배포 후 동일 smoke test를 다시 실행한다.

이 절차가 끝나기 전에는 “Supabase 데이터 저장”과 “운영 RAG 완성”을 같은 의미로 취급하지 않는다. 운영 RAG 완료 판정은 검색·생성·citation·trace가 하나의 retrieval run으로 연결됐을 때만 내린다.
