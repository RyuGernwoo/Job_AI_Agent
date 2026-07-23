# LessonPack AI 데이터셋 운영 문서

이 문서는 LessonPack AI MVP에서 사용하는 데이터셋의 구조, 전처리 방법, 검증 및 Supabase 적재 절차를 정리합니다.

## 1. 데이터셋 목적

MVP 데이터셋은 직업훈련 강의 운영 보조 AI가 다음 흐름을 실제 자료 기반으로 수행할 수 있는지 검증하기 위해 사용합니다.

- NCS 능력단위와 수업 주제 연결
- 교재/NCS 근거 chunk 검색
- 검색 근거 기반 교안·실습·평가 생성
- citation 기반 생성 결과 검증
- 사람 평가 루브릭을 통한 HITL 검토

## 2. 현재 구조

```text
data/
  raw/             # MVP 재생성에 필요한 선별 원문만 유지, Git 미포함
  processed/       # 기본 MVP 43개 chunk와 manifest, Git 미포함
  gold/            # 작은 합성 평가 fixture, Git 포함
  main_image.png
  README_DATASET.md
```

2026-07-23 로컬 정리에서 Supabase 적재가 끝난 `NCS_raw/`, NCS 확장 Markdown·chunk·catalog 사본, 중복 NCS PDF/XLS, 전체 Python/Pandas 문서 복사본을 제거했다. 현재 로컬 데이터는 MVP 검증과 43개 기본 chunk 재생성에 필요한 최소 자료만 보존한다.

### Git 추적 정책

| 경로 | Git 포함 | 이유 |
| --- | --- | --- |
| `data/raw/` | 아니오 | 선별 원문은 라이선스·재배포 이슈가 있어 로컬에만 유지 |
| `data/NCS_raw/` | 아니오 | 2026-07-23 제거. 확장 데이터는 Supabase와 공식 API 동기화로 운영 |
| `data/processed/` | 아니오 | 기본 MVP 산출물만 유지하며 `scripts/prepare_mvp_dataset.py`로 재생성 가능 |
| `data/gold/` | 예 | 테스트와 평가 기준 공유에 필요한 작은 합성 fixture |
| `outputs/` | 아니오 | 검증 리포트, 데모 산출물, export 파일은 실행 결과물 |

## 3. 현재 MVP 데이터셋

`dataset_manifest.json` 기준 현재 데이터셋은 다음과 같습니다.

| 항목 | 값 |
| --- | ---: |
| Dataset version | `mvp-dataset-v0.1` |
| 선별 원천 자료 | 6개 |
| 처리 chunk | 43개 |
| retrieval gold query | 10개 |
| generation gold case | 3개 |
| NCS 능력단위 | 3개 |

선별 원천 자료는 다음 6개입니다.

| Source ID | 자료 | 용도 |
| --- | --- | --- |
| `python-functions` | Python 공식 튜토리얼 함수 섹션 | 교안, 실습, 평가, 검색 gold |
| `python-data-structures` | Python 공식 튜토리얼 자료구조 섹션 | 교안, 실습, 평가, 검색 gold |
| `pandas-10min` | pandas 10 minutes 튜토리얼 | 선택 확장 자료 |
| `ncs-programming-language-use` | NCS 프로그래밍 언어 활용 | NCS 정합성, 실습, 평가 |
| `ncs-programming-language-application` | NCS 프로그래밍 언어 응용 | NCS 정합성, 실습, 평가 |
| `ncs-data-structure-use` | NCS 자료구조 활용 | NCS 정합성, 검색 gold, 평가 |

### NCS 분야 확장 데이터셋 운영 실적

2026-07-22에 `data/NCS_raw/`의 사업관리, 경영·회계·사무, 금융·보험 자료를 별도 확장 데이터셋으로 처리했다. 2026-07-23 Supabase 수량과 검색을 재검증한 뒤 대용량 로컬 원본과 중간 산출물은 제거했다.

| 항목 | 값 |
| --- | ---: |
| PDF | 197개, 19,771쪽 |
| XLS 능력단위 보고서 | 21개, 능력단위 404개 |
| 코드 기준 정규화 catalog | 고유 능력단위 202개, 수행준거 2,452개 |
| 정확 중복 PDF | 1개, RAG 제외 |
| 변환 Markdown | 218개 |
| RAG chunk | 19,103개 |
| PDF / XLS chunk | 18,019 / 1,084개 |
| 변환 오류 | 0건 |

분야별 chunk는 사업관리 4,696개, 경영·회계·사무 6,503개, 금융·보험 7,904개다. 기존 43개 MVP chunk와 같은 `mvp-dataset` 범위로 Supabase에 적재되어 서비스 검색 시 함께 사용된다. 로컬 재구축이 필요하면 공식 NCS API 동기화를 우선 사용하고, 원문 PDF/XLS 재처리는 별도 원본을 다시 확보한 경우에만 수행한다.

## 4. 전처리 산출물

| 파일 | 역할 |
| --- | --- |
| `data/processed/chunks.jsonl` | RAG 검색과 Supabase 적재에 사용하는 본문 chunk |
| `data/processed/chunk_index.csv` | 사람이 확인하기 쉬운 chunk 색인 |
| `data/processed/selected_sources.yaml` | MVP에 실제 사용한 원천 자료 목록 |
| `data/processed/source_file_map.csv` | NCS 원본 파일과 정리된 alias 파일 매핑 |
| `data/processed/dataset_manifest.json` | 데이터셋 버전, 수량, 품질 기준 |
| `data/gold/retrieval_gold.jsonl` | 검색 평가용 query와 기대 chunk ID |
| `data/gold/generation_gold.yaml` | 생성 평가용 case와 필수 조건 |
| `data/gold/human_eval_rubric.yaml` | 사람 평가 루브릭 |
| Supabase `lessonpack_chunks` | 분야 확장 RAG chunk 19,103개와 임베딩의 운영 저장소 |
| Supabase NCS catalog/criteria 테이블 | 능력단위·수행준거의 운영 저장소 |
| `lessonpack_ncs_source_records` | 공식 API 증분 동기화 원본과 hash의 운영 저장소 |

## 5. 적용한 전처리 방법

전처리는 [prepare_mvp_dataset.py](../scripts/prepare_mvp_dataset.py)에서 수행합니다.

1. NCS 파일 정리
   `data/raw/materials/ncs/`의 원본 PDF, Markdown, report 파일을 `data/raw/ncs/` 아래로 역할별 복사하고, 자동화에 안정적인 파일명 alias를 부여합니다.

2. PDF 변환본 우선 사용
   NCS PDF는 직접 분석하지 않고, 먼저 Markdown으로 변환한 `data/raw/ncs/converted_md/` 파일을 처리 대상으로 사용합니다.

3. 원천 자료 선별
   전체 Python/pandas/NCS 자료를 모두 사용하지 않고, MVP의 1개 차시 생성에 필요한 6개 원천만 `selected_sources.yaml`로 고정합니다.

4. 텍스트 정제
   Markdown/RST 문법, 과도한 공백, 불필요한 코드블록, 페이지 표식 일부를 정리합니다. NCS 자료는 `능력단위`, `학습`, `필요 지식`, `수행 내용`, `교수`, `평가` 등 교육 설계에 필요한 문맥만 추출합니다.

5. Chunk 분할
   대략 800자 목표로 문단을 묶고, 너무 긴 문단은 문장 단위로 분할합니다. 너무 짧은 chunk는 제외하며, 원천별 최대 chunk 수를 제한합니다.

6. 메타데이터 부여
   각 chunk에 `chunk_id`, `source_id`, `source_name`, `source_url`, `license`, `section`, `source_file`, `tags`, `char_count`, `token_estimate`, `review_status`를 부여합니다.

7. Gold set 생성
   검색 평가용 query 10개와 생성 평가용 case 3개를 생성하고, 기대 chunk ID와 필수 개념을 연결합니다.

### NCS_raw 확장 전처리

[prepare_ncs_raw_dataset.py](../scripts/prepare_ncs_raw_dataset.py)는 다음 순서를 강제합니다.

1. 모든 PDF와 XLS의 SHA-256을 계산하고 정확 중복을 식별합니다.
2. PDF는 PyMuPDF 정렬 텍스트 추출로 페이지별 Markdown을 먼저 생성합니다. 전체 감사 결과 OCR이 필요한 문서는 없었으며, 본문이 없는 앞표지·간지는 chunk에서 제외합니다.
3. XLS는 `xlrd`로 셀을 읽어 능력단위 코드별 Markdown으로 변환합니다.
4. 생성된 Markdown을 다시 읽어 PDF는 페이지 경계, XLS는 능력단위 경계로 최대 1,400자·160자 overlap chunk를 생성합니다.
5. 각 chunk에 원본 경로, 페이지, NCS 계층, 능력단위 코드, 출처 URL, 라이선스 주의문, 버전 연도를 보존합니다.

### NCS 구조화 catalog 전처리

[prepare_ncs_catalog.py](../scripts/prepare_ncs_catalog.py)는 XLS 변환 Markdown을 읽어 같은 능력단위 코드를 하나로 합치고, 능력단위 명칭·정의·분류·버전과 능력단위요소별 수행준거를 구조화합니다. 현재 입력 404개 능력단위 행은 코드 기준 고유 능력단위 202개와 수행준거 2,452개로 정규화되며, 수행준거가 없는 능력단위는 0개입니다. 이 catalog는 RAG 본문 chunk와 분리해 입력 자동완성 및 코드·수행준거 검증에 사용합니다.

## 6. 재생성 절차

원천 자료가 준비된 상태에서 다음 명령을 실행합니다.

```powershell
python scripts\prepare_mvp_dataset.py
```

성공하면 `data/processed/`와 `data/gold/` 산출물이 갱신됩니다.

`prepare_ncs_raw_dataset.py`는 원문 PDF/XLS를 다시 확보했을 때 사용하는 보존용 전처리 도구다. 현재 로컬에는 `NCS_raw/`가 없으므로 아래 명령은 원문을 별도 복원한 경우에만 실행한다.

```powershell
pip install -r requirements-data.txt
python scripts\prepare_ncs_raw_dataset.py --force
python scripts\prepare_ncs_catalog.py
```

일반 운영에서는 공식 API 증분 동기화를 사용한다.

```powershell
python scripts\sync_ncs_official_api.py --mode all --resume --embed
python scripts\verify_ncs_official_sync.py
```

## 7. 검증 절차

```powershell
python scripts\validate_mvp_dataset.py
```

리포트를 파일로 남기려면 다음처럼 실행합니다.

```powershell
python scripts\validate_mvp_dataset.py --report outputs\eval\dataset_validation_report.json
```

검증 항목은 다음과 같습니다.

- 필수 파일 존재 여부
- chunk 필수 필드와 중복 ID
- 빈 본문 여부
- `chunk_index.csv`와 `chunks.jsonl`의 ID 일치
- retrieval gold의 기대 chunk ID 존재 여부
- generation gold의 source ID 존재 여부
- manifest count와 실제 count 일치 여부
- 최소 품질 기준 충족 여부

현재 검증 기준 수량은 다음과 같습니다.

```json
{
  "chunks": 43,
  "chunk_index_rows": 43,
  "selected_sources": 6,
  "source_file_map_rows": 49,
  "retrieval_gold": 10,
  "generation_gold": 3
}
```

## 8. Supabase 적재

운영형 vector store는 Supabase Postgres + pgvector를 사용합니다. Supabase 프로젝트에서 먼저 다음 migration을 실행합니다.

```text
supabase/migrations/001_lessonpack_vectors.sql
supabase/migrations/002_rag_persistence.sql
supabase/migrations/003_training_plan_fields.sql
supabase/migrations/004_vector_search_performance.sql
supabase/migrations/005_project_retrieval_queries.sql
supabase/migrations/006_ncs_course_specialization.sql
```

`.env`에는 다음 값이 필요합니다.

```powershell
LECTUREOPS_VECTOR_STORE=supabase
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
LESSONPACK_SUPABASE_TABLE=lessonpack_chunks
LESSONPACK_SUPABASE_MATCH_FUNCTION=match_lessonpack_chunks
LESSONPACK_SUPABASE_MATCH_THRESHOLD=0.0
LESSONPACK_BASELINE_PROJECT_ID=mvp-dataset
LESSONPACK_RETRIEVAL_CANDIDATE_K=20
LESSONPACK_RETRIEVAL_TOP_K=5
LESSONPACK_EMBEDDING_PROVIDER=litellm
LESSONPACK_EMBEDDING_MODEL=text-embedding-3-small
LESSONPACK_EMBEDDING_DIMENSIONS=1536
LESSONPACK_SUPABASE_EMBEDDING_COLUMN=embedding_v2
LESSONPACK_SUPABASE_MATCH_FUNCTION=match_lessonpack_chunks_v2
LESSONPACK_EMBEDDING_VERSION=v2
```

전처리된 chunk를 Supabase에 적재하고 검색 smoke test를 수행합니다.

```powershell
python scripts\ingest_processed_dataset.py --query "Python 함수 return" --top-k 3
python scripts\check_rag_readiness.py --check-schema --query "Python 함수 return" --top-k 3
```

2026-07-21에 기존 43개 `mvp-dataset` chunk를 위 구성으로 재적재해 `embedding_v2`와 `embedding_version=v2`를 확인했다. 이후 데이터셋을 변경하면 같은 명령으로 해당 chunk를 갱신한다. 기존 `embedding` 값은 호환성 확인 전까지 유지한다.

아래 명령은 2026-07-22 확장 데이터 최초 적재에 사용한 이력이다. 로컬 `ncs_expansion` 산출물을 제거했으므로 같은 파일을 다시 확보하지 않는 한 재실행하지 않는다.

```powershell
python scripts\ingest_processed_dataset.py `
  --chunks-file data\processed\ncs_expansion\chunks.jsonl `
  --project-id mvp-dataset --batch-size 32

python scripts\verify_ncs_expansion_rag.py --project-id mvp-dataset --top-k 5
python scripts\prepare_ncs_catalog.py --upload
```

2026-07-23 재검증에서도 PDF 18,019개, XLS 1,084개, 합계 19,103개가 Supabase에 존재했고 세 분야 대표 검색이 모두 성공했다. 로컬 매니페스트는 정리되었으며 운영 검증은 Supabase count와 검색 smoke test를 기준으로 한다. `004_vector_search_performance.sql`은 PostgREST의 generic prepared plan이 전체 벡터를 순차 비교하지 않도록 검색 함수 내부에서 쿼리별 HNSW custom plan을 생성합니다.

`006_ncs_course_specialization.sql`은 강의 유형, 검색 실행의 NCS 메타데이터, `lessonpack_ncs_catalog`, `lessonpack_ncs_criteria`를 추가합니다. 운영 반영은 migration 적용 후 `prepare_ncs_catalog.py --upload` 순서로 진행하며, service role key는 서버 환경에서만 사용합니다.

## 9. 검색 평가

```powershell
python scripts\evaluate_retrieval.py --top-k 3 --min-hit-rate 1.0 --report outputs\eval\retrieval_report.json
```

주요 지표는 다음과 같습니다.

| 지표 | 의미 |
| --- | --- |
| `hit_rate` | 기대 chunk가 top-k 검색 결과에 하나 이상 포함된 질의 비율 |
| `mean_reciprocal_rank` | 첫 번째 정답 chunk 순위의 역수 평균 |
| `average_context_precision` | 검색 결과 중 기대 chunk 비율 |
| `average_context_recall` | 기대 chunk 중 검색 결과에 포함된 비율 |

현재 MVP gold set 기준 baseline은 top-3 hit rate `1.0`입니다.

## 10. 생성 평가

```powershell
python scripts\evaluate_generation.py --min-case-pass-rate 1.0 --report outputs\eval\generation_report.json
```

실제 LLM provider를 사용하려면 `.env`에 OpenAI, Gemini, Langfuse key를 설정한 뒤 실행합니다.

```powershell
python scripts\evaluate_generation.py --require-real-llm --min-case-pass-rate 1.0 --report outputs\eval\generation_real_llm_report.json
```

NCS 생성 평가는 LLM이 산출물별로 반환한 `ncs_criteria`가 선택 수행준거의 정확한 값인지 먼저 검증한 뒤, 대상 수행준거 커버리지 90% 이상과 평가 커버리지 100%를 별도 게이트로 측정합니다. 일반 강의는 `ncs_criteria`가 비어 있고 NCS 근거·코드·수행준거가 포함되지 않는지 회귀 테스트로 검사합니다. 이 지표는 구조적 연결을 측정하며, 문장 내용이 수행준거를 교육적으로 충족하는지는 강사 평가로 별도 확인합니다.

## 11. MVP 전체 검증

```powershell
python scripts\run_mvp_verification.py --output-dir outputs\eval --demo-case-id g003
```

검증 스크립트는 데이터셋 검증, provider 준비 상태, retrieval 평가, generation 평가, 데모 export 생성을 한 번에 수행합니다.

## 12. 현재 한계

- semantic embedding은 LiteLLM을 통해 OpenAI `text-embedding-3-small`을 사용한다. 외부 API 비용과 rate limit을 고려해 전체 재색인은 데이터셋 변경 시에만 수행한다.
- 실제 강사 사용성 평가는 별도 수집이 필요합니다.
- 원천 자료 라이선스는 문서화되어 있지만 자동 판정하지 않습니다.
- NCS PDF의 표, 이미지, 복잡한 레이아웃은 Markdown 변환 과정에서 일부 손실될 수 있습니다.
- Supabase에 적재된 기존 확장 chunk에는 2013~2024년 자료가 혼재한다. 신규·변경 정보는 공식 API 동기화로 보완하고, 법령·지침·통계는 생성 전에 최신성을 별도로 확인해야 한다.
- 대용량 확장 원문과 중간 산출물은 로컬에 유지하지 않는다. 원문 기반 재처리가 필요하면 NCS 공식 출처에서 자료를 다시 확보해야 한다.
