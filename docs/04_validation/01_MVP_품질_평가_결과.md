# LessonPack AI MVP 품질 평가 결과

- 최종 재검증일: 2026-07-23
- 실환경 실행 ID: `mvp-verification-20260723T125224Z`
- 원시 리포트: `outputs/eval-20260723-all-pass-live/`
- 종합 판정: **PASS**

## 1. 평가 범위

이번 평가는 mock 결과만으로 통과시키지 않고 다음 실제 연동 경로를 포함했다.

1. 전체 Python 회귀 테스트와 정적 컴파일
2. 고정 평가 데이터셋 무결성
3. 외부 Supabase pgvector 실제 검색
4. LiteLLM의 OpenAI 실제 구조화 생성과 Gemini fallback 설정
5. NCS 수행준거, 평가, citation 정합성
6. DOCX/PPTX 생성물 내용·형식 검사
7. NCS 공식 API 동기화 상태와 표본 검색
8. Langfuse Input, Output, latency, usage, cost
9. GCE 배포 health와 Docker 이미지 빌드
10. Lovable 프론트엔드 lint와 production build

실환경 평가는 다음 명령으로 수행했다.

```powershell
python scripts\run_mvp_verification.py `
  --require-live-rag `
  --require-real-llm `
  --output-dir outputs\eval-20260723-final-live
```

## 2. 개선 및 반복 검증

### 2.1 첫 재검증 실패

선택 동기화 후 첫 검색 평가는 Context Precision과 Recall이 각각 `0.5667`로 기준 `0.6000`을 충족하지 못했다. Supabase RPC가 `top_k`만큼의 벡터 후보만 반환했고, 애플리케이션에서 계산한 하이브리드 점수를 실제 정렬에 사용하지 않은 것이 원인이었다.

첫 실 LLM 재검증에서는 3건 중 2건만 실제 JSON이 적용됐다. `g002`가 실습 개념 `함수화`를 선택되지 않은 NCS 수행준거로 출력해 구조화 적용률이 `0.6667`이었다.

### 2.2 반영한 보완

- Supabase에서 최소 200개 벡터 후보를 조회한 뒤 vector similarity와 lexical overlap의 하이브리드 점수로 재정렬한다.
- 상위 결과가 의미상 유사한 한 출처에 편중될 때를 대비해 최고 lexical-overlap 후보를 최소 한 개 보존한다.
- 허용된 citation ID와 NCS 수행준거를 생성·복구 프롬프트에 JSON 배열로 명시한다.
- LLM schema 복구 기본 횟수를 1회에서 2회로 늘려 최초 호출 포함 최대 3회 시도한다.
- 모델의 NCS 매핑에서 허용 목록 밖 값을 제거하고, 누락 항목은 사용자가 선택한 수행준거 안에서만 보충한다.
- 모든 선택 수행준거가 최소 한 개의 평가 문항에 연결되도록 백엔드에서 다시 검증한다.

임계값을 낮추거나 실패 gold case를 삭제하지 않았다.

## 3. 최종 자동 검증

| 영역 | 결과 | 근거 |
| --- | --- | --- |
| 전체 Python 테스트 | PASS | `162 passed, 3 subtests passed` |
| 정적 컴파일 | PASS | `src`, `scripts`, `tests` compileall 성공 |
| 데이터셋 무결성 | PASS | 오류 0건, 경고 0건 |
| 실 Supabase 검색 | PASS | 모든 검색 품질 게이트 충족 |
| 실 LLM 생성 | PASS | 3/3 실제 JSON 적용 |
| DOCX/PPTX | PASS | 파일 및 내용·형식 검사 통과 |
| Supabase schema | PASS | 필수 4개 persistence table 확인 |
| NCS 공식 동기화 | PASS | 완료 run, 데이터, 표본 검색 확인 |
| Langfuse rich fields | PASS | 8개 검사 전부 통과 |
| GCE 배포 | PASS | `/health`, `/health/rag` HTTP 200 |
| Docker | PASS | Python 3.11 이미지 build/load 및 앱 import 성공 |
| 프론트엔드 | PASS | ESLint 오류 0건, production build 성공 |

## 4. RAG 검색 결과

- backend: `live:SupabaseVectorStore`
- embedding: `text-embedding-3-small`, 1536차원
- column/version: `embedding_v2` / `v2`
- 평가 query: 10건
- 반환 Top K: 3
- 재정렬 후보: 최소 200개

| 지표 | 결과 | 기준 | 판정 |
| --- | ---: | ---: | --- |
| Hit Rate@3 | 1.0000 | 0.7000 이상 | PASS |
| MRR | 0.9333 | 0.7000 이상 | PASS |
| Context Precision | 0.7000 | 0.6000 이상 | PASS |
| Context Recall | 0.7000 | 0.6000 이상 | PASS |
| nDCG@3 | 0.7408 | 관찰 지표 | PASS |
| 필수 개념 충족률 | 1.0000 | 0.7000 이상 | PASS |
| 중복 chunk 비율 | 0.0000 | 0.2000 이하 | PASS |
| 빈 검색률 | 0.0000 | 0.0000 | PASS |

RAG readiness 표본 `Python 함수 정의와 def 키워드`는 `python-functions-c001`, `c003`, `c004`를 순서대로 반환했다.
10개 gold query 모두 expected chunk를 검색했고 필수 개념 누락은 0건이었다.

## 5. 실제 LLM 생성 결과

- primary: `gpt-4o-mini`
- 실제 응답 모델: `gpt-4o-mini-2024-07-18`
- fallback: `gemini/gemini-3.5-flash`
- case: `g001`, `g002`, `g003`

| 지표 | 결과 | 기준 | 판정 |
| --- | ---: | ---: | --- |
| case 통과율 | 1.0000 | 1.0000 | PASS |
| 평균 품질 점수 | 1.0000 | 0.9000 이상 | PASS |
| citation 연결률 | 1.0000 | 0.9000 이상 | PASS |
| citation-source 해소율 | 1.0000 | 1.0000 | PASS |
| NCS 항목 연결률 | 1.0000 | 0.8000 이상 | PASS |
| NCS 수행준거 커버리지 | 1.0000 | 0.9000 이상 | PASS |
| NCS 평가 연결률 | 1.0000 | 1.0000 | PASS |
| 출처 메타데이터 완성도 | 1.0000 | 0.9000 이상 | PASS |
| 평가 문항 완성도 | 1.0000 | 1.0000 | PASS |
| 수업시간 일치도 | 1.0000 | 0.9000 이상 | PASS |
| 문항 고유성 | 1.0000 | 1.0000 | PASS |
| 실제 구조화 출력 적용률 | 1.0000 | 1.0000 | PASS |
| trace ID 보존율 | 1.0000 | 1.0000 | PASS |

세 case 모두 첫 시도에 통과했으며 schema validation error는 없었다.

## 6. 운영 연동 결과

### 6.1 Supabase와 NCS

| 항목 | 결과 |
| --- | ---: |
| MVP 처리 chunk | 43 |
| NCS catalog | 13,304 |
| 선택 NCS source record | 82 |
| 선택 NCS RAG chunk | 82 |
| 최근 detail sync 상태 | `completed` |
| 최근 detail sync request | 16 |
| NCS 표본 검색 공식 근거 | 5/5 |

`lessonpack_projects`, `lessonpack_documents`, `lessonpack_retrieval_runs`, `lessonpack_generation_runs` 테이블의 존재와 접근을 확인했다.

### 6.2 Langfuse

- smoke marker: `lessonpack-smoke-6cfc2a77d66f4423ad33dfe90fa5a8ea`
- observation type: `GENERATION`
- model: `gpt-4o-mini-2024-07-18`
- latency: 7.637초
- usage: input 51, output 376, total 427 tokens
- cost: 0.000233249999 USD
- trace name, Input, Output, model, latency, usage, cost: 전부 PASS

### 6.3 배포·빌드

- GCE `https://34.47.92.210.nip.io/health`: HTTP 200
- GCE `/health/rag`: HTTP 200, Supabase store/repository 및 persistence ready
- Docker `python:3.11-slim` 이미지 build/load 성공
- 이미지 내부 `create_app()` 결과: `LessonPack AI`
- 프론트엔드 production build 성공

## 7. 비차단 관찰 사항

- NCS 공식 표본 검색 한 건에서 27.936초가 측정됐다. 정확성 게이트는 통과했지만 운영 latency 계측과 임계값 설정이 필요하다.
- 로컬 Python 3.14에서 LiteLLM 1.93.0 종료 시 logging worker RuntimeWarning이 발생했다. 실제 생성과 Langfuse 전송은 PASS이며 배포 이미지는 Python 3.11이다.
- 프론트엔드 ESLint는 오류 0건이지만 Fast Refresh 파일 export 관련 warning 7건을 보고했다. production build에는 영향이 없다.

## 8. 한계와 다음 검증

- retrieval gold 10건과 generation gold 3건으로 표본이 작다.
- 현재 gold는 Python 및 응용SW NCS 중심이므로 다른 직무 분야를 대표하지 않는다.
- 자동 평가는 현장 강사의 난이도 적합성·표현 만족도를 대신하지 않는다.
- 다음 단계에서는 직무 분야별 gold set 확대, RAG P95 latency 기준 도입, 실제 사용자 실증을 수행한다.
