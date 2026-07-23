# NCS 확장 데이터셋 처리 및 RAG 검증 결과

> 수행일: 2026-07-22
> 대상: `data/NCS_raw/`
> Supabase 기준 프로젝트: `mvp-dataset`

> 2026-07-23 운영 재검증에서 원격 19,103개 chunk와 세 분야 검색 성공을 확인했다. 이후 대용량 로컬 원본·Markdown·chunk 사본은 제거했으며, 이 문서의 로컬 경로는 처리 당시의 감사 기록이다.

## 1. 결과 요약

`NCS_raw`의 사업관리, 경영·회계·사무, 금융·보험 자료를 모두 Markdown으로 먼저 변환한 뒤, Markdown만을 입력으로 RAG chunk를 생성했습니다. 외부 OpenAI 임베딩과 Supabase pgvector 적재 및 실제 검색까지 완료했습니다.

| 검증 항목 | 결과 |
| --- | --- |
| PDF → Markdown 선행 | 통과, 197개 |
| XLS → Markdown 보강 | 통과, 21개 |
| 변환 오류 | 0건 |
| 정확 중복 처리 | 1개 식별, RAG 제외 |
| 로컬 chunk 품질 | 통과, 19,103개 |
| Supabase 적재 수 일치 | 통과, 19,103개 |
| 세 분야 실제 RAG 검색 | 통과 |
| 전체 회귀 테스트 | `92 passed, 3 subtests passed` |

## 2. 원본 분석

| 항목 | 값 |
| --- | ---: |
| PDF | 197개 |
| PDF 용량 | 2,054,930,863 bytes |
| PDF 총 페이지 | 19,771쪽 |
| XLS | 21개 |
| XLS 능력단위 | 404개 |
| 고유 PDF 해시 | 196개 |
| 정확 중복 PDF | 1개 |

PDF 전체에 대해 텍스트 추출 가능성을 감사했습니다. 첫 페이지 표본에서 텍스트가 적었던 8개 문서도 전체 페이지를 확인하면 본문 텍스트가 충분했고, 대표 페이지 렌더링에서 한글 본문과 표가 정상적으로 보였습니다. 따라서 이번 데이터에는 OCR을 사용하지 않았습니다. 본문이 없는 표지·간지 성격의 페이지 2,092쪽은 Markdown에 페이지 위치를 남기고 chunk에서는 제외했습니다.

## 3. 전처리 방식

전처리는 [prepare_ncs_raw_dataset.py](../../scripts/prepare_ncs_raw_dataset.py)로 재현할 수 있습니다.

1. 원본 파일별 SHA-256과 NCS 폴더 계층을 기록합니다.
2. PDF는 PyMuPDF의 정렬 텍스트 추출을 사용해 페이지별 `## Page N` Markdown을 생성합니다.
3. 반복 머리말·꼬리말과 독립 페이지 번호를 제거하고, 빈 페이지를 표시합니다.
4. XLS는 `xlrd`로 읽어 분류번호, 능력단위 명칭·정의, 수행준거, 지식·기술·태도를 능력단위별 Markdown으로 변환합니다.
5. 모든 변환이 끝난 뒤 생성된 Markdown을 다시 읽어 chunk를 만듭니다. PDF는 페이지 경계, XLS는 능력단위 경계를 넘지 않습니다.
6. 최대 1,400자, overlap 160자를 적용하고 원본 경로, 페이지, 능력단위 코드, NCS 계층, 버전 연도, 출처와 라이선스 주의문을 메타데이터로 보존합니다.
7. 동일 콘텐츠 PDF는 Markdown까지 생성하지만 canonical 문서만 chunk로 만듭니다.

## 4. 생성 산출물

| 경로 | 역할 |
| --- | --- |
| `data/raw/ncs_expansion/converted_md/` | PDF/XLS Markdown 218개 |
| `data/processed/ncs_expansion/chunks.jsonl` | Supabase 적재 대상 19,103개 |
| `data/processed/ncs_expansion/source_manifest.jsonl` | 파일별 해시·버전·중복·변환 상태 |
| `data/processed/ncs_expansion/dataset_manifest.json` | 전체 수량과 처리 계약 |
| `data/processed/ncs_expansion/conversion_errors.jsonl` | 변환 오류, 현재 0건 |

원본과 처리 산출물은 용량·라이선스·재생성 가능성을 이유로 Git에서 제외합니다. 스크립트, 검증 코드와 이 결과 문서만 추적합니다.

## 5. Chunk 품질 감사

| 지표 | 결과 |
| --- | ---: |
| 총 chunk | 19,103 |
| 고유 chunk ID | 19,103 |
| RAG 포함 문서 | 217 |
| 정확 중복 텍스트 | 0 |
| 빈 텍스트 | 0 |
| 깨진 대체 문자 포함 | 0 |
| PDF 페이지 메타데이터 누락 | 0 |
| 길이 최소 / 중앙값 / P95 / 최대 | 81 / 782 / 1,459 / 1,493자 |

분야 및 소스 유형 분포는 다음과 같습니다.

| 구분 | Chunk 수 |
| --- | ---: |
| 사업관리 | 4,696 |
| 경영·회계·사무 | 6,503 |
| 금융·보험 | 7,904 |
| PDF 학습모듈 | 18,019 |
| XLS 능력단위 보고서 | 1,084 |

버전 연도는 코드와 파일명에서 2013~2024년으로 추론했습니다. `PB영업/최종본_6_고객제안실행_1차+출처검토_완료.pdf` 1개는 연도를 확정할 코드가 없어 `needs_review` 상태로 남겼습니다.

## 6. Supabase 적재

적재 설정은 다음과 같습니다.

| 항목 | 값 |
| --- | --- |
| Vector store | Supabase Postgres + pgvector |
| Embedding provider | LiteLLM |
| Embedding model | `text-embedding-3-small` |
| 차원 | 1,536 |
| 열 / 버전 | `embedding_v2` / `v2` |
| 기준 프로젝트 | `mvp-dataset` |
| 배치 크기 | 32 |

외부 적재 결과는 로컬 매니페스트와 정확히 일치했습니다.

| 소스 | 로컬 기대 수 | Supabase 수 |
| --- | ---: | ---: |
| PDF | 18,019 | 18,019 |
| XLS | 1,084 | 1,084 |
| 합계 | 19,103 | 19,103 |

적재 중 일시적인 Supabase `APIError`는 지수 백오프 재시도로 복구했습니다. 청크 ID가 콘텐츠 해시와 페이지·구간에 대해 결정적이므로 같은 명령을 다시 실행해도 중복 삽입이 아닌 upsert가 수행됩니다.

## 7. 검색 성능 보완

대량 적재 직후 기존 `match_lessonpack_chunks_v2`는 HNSW 인덱스가 있어도 generic prepared plan에서 11초 이상 걸려 PostgREST의 8초 제한을 초과했습니다.

[004_vector_search_performance.sql](../../supabase/migrations/004_vector_search_performance.sql)에서 다음을 적용했습니다.

- 64차원·1,536차원 HNSW 인덱스 존재 보장
- 검색 함수를 PL/pgSQL 동적 쿼리로 변경
- 요청 벡터마다 custom HNSW plan 생성
- `ANALYZE public.lessonpack_chunks` 실행

고정 벡터 PostgREST RPC는 수정 후 2.446초에 5개 결과를 반환했습니다. 외부 Supabase에는 `003_training_plan_fields.sql`과 `004_vector_search_performance.sql`을 모두 적용했으며, 영속화 테이블 4종 준비도 검사도 통과했습니다.

## 8. 실제 RAG 검증

[verify_ncs_expansion_rag.py](../../scripts/verify_ncs_expansion_rag.py)로 세 분야를 검증했습니다.

| 분야 | Query | 지연시간 | 결과 |
| --- | --- | ---: | --- |
| 사업관리 | 공적개발원조사업 개발전략수립 협력대상국 | 6.034초 | 관련 PDF 페이지 5개 |
| 경영·회계·사무 | 인터뷰 정성조사 FGI 조사 설계 | 0.887초 | 관련 PDF 페이지 5개 |
| 금융·보험 | 보험상품 개발 위험률 보험료 산출 | 1.153초 | 관련 PDF 페이지 5개 |

첫 쿼리는 외부 임베딩 및 DB cold cache를 포함한 값입니다. 모든 결과의 `chunk_id`가 새 `ncs-pdf-*` 형식이고, 기대한 `top_category`, 자료명, 페이지가 반환되어 현재 애플리케이션의 `mvp-dataset` RAG 후보에 포함됐음을 확인했습니다.

## 9. 재현 명령

```powershell
pip install -r requirements-data.txt
python scripts\prepare_ncs_raw_dataset.py --force

python scripts\ingest_processed_dataset.py `
  --chunks-file data\processed\ncs_expansion\chunks.jsonl `
  --project-id mvp-dataset `
  --batch-size 32 `
  --max-retries 7 `
  --retry-delay 3

python scripts\verify_ncs_expansion_rag.py --project-id mvp-dataset --top-k 5
python scripts\check_rag_readiness.py --check-schema
```

## 10. 남은 품질 관리

- NCS 원본에는 과거 법령·통계·표준이 포함될 수 있으므로 생성 시 `source_year`를 표시하고 최신성 검토를 유지합니다.
- NCS 자료의 교육 목적 활용과 출처 표기는 준수하되, 포함된 제3자 도표·사진의 재배포 권리는 별도로 확인해야 합니다.
- 표와 복잡한 레이아웃은 텍스트 구조가 단순화될 수 있습니다. 표 수치가 핵심인 과정은 별도 표 구조화 검증이 필요합니다.
- 향후 스캔 PDF가 추가되면 텍스트 페이지 비율 감사 후 OCR 분기를 추가합니다. 이번 197개 PDF에는 OCR이 필요하지 않았습니다.
