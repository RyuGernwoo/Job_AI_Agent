# NCS 공식 API 기반 RAG 자동 동기화 기획서

작성일: 2026-07-23

대상: LessonPack AI NCS 카탈로그 및 공통 RAG 데이터

## 0. 구현 반영 상태

2026-07-23 기준 다음 항목을 구현했다.

| 항목 | 상태 | 구현 위치 |
| --- | --- | --- |
| 공식 API XML/JSON client, service key 이중 인코딩 방지 | 완료 | `services/ncs_official_api.py` |
| 재시도, 속도 제한, 페이지 순회, 할당량 상한 | 완료 | `services/ncs_official_api.py`, `services/ncs_sync_service.py` |
| canonical 변환, payload hash 변경 감지 | 완료 | `services/ncs_rag_chunk_builder.py` |
| catalog·criteria·module upsert, KSA source/RAG 적재 | 완료 | `services/ncs_sync_service.py` |
| 결정적 chunk ID, 기존 chunk 교체, 삭제 source 비활성화 | 완료 | `services/ncs_rag_chunk_builder.py`, `services/ncs_sync_service.py` |
| LiteLLM 임베딩과 `mvp-dataset` baseline 적재 | 완료 | 기존 `vector_store.py` 연동 |
| sync run, checkpoint, raw staging, module migration | 코드 완료 | `008_ncs_official_api_sync.sql` |
| catalog·detail·module 정기 실행과 검증 artifact | 코드 완료 | `.github/workflows/ncs-sync.yml` |
| fixture, KSA 병합, 멱등성, 재개·삭제 검증 | 완료 | `tests/test_ncs_official_api.py`, `tests/test_ncs_official_sync.py` |
| 공식 `dataInfo`·`data/row` 응답 및 상세 API 필수 파라미터 반영 | 완료 | API parser와 동적 detail target |
| 운영 Supabase migration 적용 | 운영 반영 | `008_ncs_official_api_sync.sql` 기준 |
| 공식 API 연결·catalog 동기화 | 운영 반영 | 전체 코드·명칭 검색에 사용 |
| detail 수행준거·학습모듈 백필 | 진행 중 | API 할당량 안에서 반복 `--resume` 실행 |

공공데이터포털 service key와 운영 Supabase 연결은 완료되었지만, API 연결 자체가 전체 수행준거 적재 완료를 의미하지는 않는다. `catalog` 작업은 능력단위 코드·명칭을 갱신하고 `detail` 작업은 능력단위요소·수행준거·KSA·평가지침과 RAG chunk를 보완한다. 현재 검색 결과에서 다수 항목이 `수행준거 0개`로 보이는 것은 상세 백필이 진행 중인 상태와 일치한다.

현재 자동 테스트 기준은 전체 `154 passed, 3 subtests passed`다. 동기화 전용 테스트에는 공식 `dataInfo/data/row` 파싱, 상세 필수 키 전달, catalog 이후 detail target 자동 생성, 멱등성, 체크포인트 재개와 삭제 source 정리가 포함된다. 외부 API와 Supabase의 최신 수량은 테스트 수치가 아니라 `ncs-sync-report.json`과 `verify_ncs_official_sync.py` 결과로 판정한다.

### 0.1 운영 상태 판정

| 관찰 결과 | 의미 | 조치 |
| --- | --- | --- |
| 코드·명칭은 검색되고 수행준거가 0개 | catalog 완료, detail 미완료 | `detail --resume --embed` 반복 |
| 최신 sync가 `partial` | 요청 상한 또는 작업 범위 때문에 중단 지점 저장 | 동일 옵션으로 재개 |
| `criteria_upsert_count=0` | 상세 응답·target·파싱 경로 확인 필요 | sync artifact와 실패 source 확인 |
| criteria는 있으나 RAG hit가 없음 | chunk 또는 embedding 적재 불완전 | `chunk_upsert_count`와 검증 query 확인 |
| 특정 단위만 긴급 보완 | 전체 백필을 기다릴 필요 없음 | `--unit-code <code>` 제한 실행 |

## 1. 목적

공공데이터포털의 한국산업인력공단 공식 API를 주기적으로 호출해 NCS 능력단위 상세정보와 학습모듈 정보를 Supabase에 동기화하고, 변경된 내용만 임베딩하여 LessonPack 공통 RAG에 반영한다.

완료된 동기화 기능은 다음 조건을 충족해야 한다.

1. 능력단위 코드·명칭뿐 아니라 능력단위요소, 수행준거, KSA, 평가지침을 구조화해 저장한다.
2. 공식 API에 상세정보가 있는 능력단위는 기존 `수행준거 0개` 상태를 자동으로 해소한다.
3. 학습모듈 API가 제공하는 번호·명칭·내용을 검색 근거로 사용할 수 있게 한다.
4. 원문이 제공되지 않은 학습모듈 내용을 전체 교재로 오인하지 않는다.
5. API 할당량과 일시 장애에 대응해 중단 지점부터 재개할 수 있어야 한다.
6. 내용이 바뀐 레코드만 다시 임베딩하며 동일 작업을 반복해도 중복 row와 chunk를 만들지 않는다.
7. 모든 chunk에 공식 출처, 조회 시각, NCS 코드와 데이터 범위를 기록한다.

## 2. 현재 상태

| 영역 | 현재 상태 | 목표 상태 |
| --- | --- | --- |
| NCS 전체 목록 | 공식 CSV 기반 13,442개 능력단위 적재 | API 기준 최신 상태로 정기 갱신 |
| 상세 수행준거 | 전처리 문서 기반 202개 능력단위, 2,452개 수행준거 | 공식 API 상세정보를 단계적으로 백필 |
| 학습모듈 | 사용자가 제공하거나 내려받은 PDF/XLS 원문을 전처리 | API 메타데이터·내용 자동 동기화 + 원문 전처리 병행 |
| RAG 적재 | 수동 스크립트와 JSONL 기반 | 변경 감지, 자동 임베딩, 검증까지 하나의 동기화 작업으로 실행 |
| 운영 이력 | 적재 스크립트 표준 출력 중심 | Supabase sync run, 체크포인트, 실패 원인 영속화 |

현재 검색의 기준 목록은 유지한다. API 동기화는 공식 CSV 목록을 대체 삭제하는 작업이 아니라 코드별 상세정보를 보완하고 최신 변경을 반영하는 작업이다.

## 3. 공식 데이터 소스

### 3.1 국가직무능력표준 정보_GW

- 공식 페이지: https://www.data.go.kr/data/15157547/openapi.do
- Base URL: `https://apis.data.go.kr/B490007/ncsInfo`
- 형식: REST/XML
- 업데이트: 실시간
- 개발계정: 자동승인, 일 10,000건
- 운영계정: 활용사례 등록 후 심의 및 증량 신청

| Operation | 적재 대상 | LessonPack 활용 |
| --- | --- | --- |
| `ncsCdInfo` | NCS 분류체계 | 카탈로그 분류 보완 |
| `ncsDutyInfo` | 직무정보 | 직무·능력단위 관계 |
| `ncsCompeUnitInfo` | 능력단위 | 코드, 명칭, 정의, 수준 |
| `ncsCompeUnitFactrInfo` | 능력단위요소 | 요소 코드·명칭 |
| `ncsKsaInfo` | 수행준거와 KSA | 교안·실습·평가 생성의 핵심 근거 |
| `ncsScopeInfo` | 적용범위 | 실습 상황과 필요 장비 근거 |
| `ncsEvalInfo` | 평가지침 | 평가문항·루브릭 생성 근거 |
| `ncsjobInfo` | 직업기초능력 | 선수지식·보조 역량 |
| `ncsFusInfo` | 연관 능력단위 | 선수·후속 단위 추천 |
| `ncsTrainCsdrInfo` | 훈련기준 고려사항 | 과정 편성 제약 |
| `ncsCompeTrainInfo` | 능력단위 훈련기준 | 권장 시간·훈련 구성 |
| `ncsSetqInfo` | 출제기준 | 평가 범위와 문항 설계 |

`ncsClposInfo` 등 직접 생성에 사용하지 않는 정보도 raw staging에는 보존하되, MVP RAG chunk 생성 대상에서는 제외할 수 있다.

공식 Swagger 계약에 따라 목록·상세 호출을 구분한다.

- `ncsCdInfo`, `ncsDutyInfo`, `ncsCompeUnitInfo`, `ncsCompeUnitFactrInfo`는 페이지 단위로 조회한다.
- `ncsKsaInfo`는 카탈로그에서 확보한 `dutyCd`별로 조회한다.
- `ncsClposInfo`, `ncsFusInfo`, `ncsTrainCsdrInfo`는 `dutyCd`가 필수다.
- `ncsScopeInfo`, `ncsEvalInfo`, `ncsjobInfo`, `ncsCompeTrainInfo`, `ncsSetqInfo`는 `dutyCd`와 `compUnitCd`가 모두 필수다.
- API 응답의 상태·페이지 정보는 `dataInfo`, 실제 레코드는 `data/row`를 우선 해석한다.
- 상세 모드는 저장된 `ncsCompeUnitInfo` 원본에서 필수 키를 읽으므로 최초 1회 catalog sync가 선행되어야 한다.

### 3.2 NCS 기준정보 조회

- 공식 페이지: https://www.data.go.kr/data/15128213/openapi.do
- Base URL: `https://apis.data.go.kr/B490007/hrdkapi`
- 형식: REST/JSON
- 주요 Operation: `NCS001`~`NCS007`

전체 분류 순회, 능력단위 코드·요소 확인, 키워드 검색에 사용한다. `국가직무능력표준 정보_GW`가 일시적으로 실패할 때 상세 내용을 임의로 대체하지 않고, 목록 식별과 변경 후보 탐색에만 사용한다.

### 3.3 NCS 학습모듈정보

- 공식 페이지: https://www.data.go.kr/data/15086442/openapi.do
- Endpoint: `https://apis.data.go.kr/B490007/ncsStudyModule/openapi21`
- 형식: REST/XML
- 입력: 대분류코드, 학습모듈명, 페이지
- 출력: 학습모듈 번호, 명칭, 내용, NCS 대·중·소·세분류

공개 응답 명세에는 PDF/HWP 다운로드 URL이 없다. `learnModulText`는 학습모듈의 공식 내용 정보로 저장하되 전체 원문 교재로 표시하지 않는다. 전체 원문은 NCS 공식 사이트에서 확보한 파일을 별도 PDF/HWP → Markdown 파이프라인으로 처리한다.

### 3.4 출처 및 이용 기준

- 데이터 공급기관을 `한국산업인력공단`으로 기록한다.
- 검색 근거에 공공데이터포털 데이터셋 URL과 조회일을 남긴다.
- 학습모듈은 교육 목적으로 사용하되 출처를 표시한다.
- API 응답에 없는 내용을 공식 정보처럼 보완하거나 추정하지 않는다.
- API 키, Supabase service role key는 서버와 CI secret에서만 사용한다.

NCS 구성 및 학습모듈 이용 안내: https://www.ncs.go.kr/th01/TH-102-001-03.scdo

## 4. 목표 아키텍처

```text
GitHub Actions schedule / GCE 수동 실행
                  |
                  v
        NCS Official API Client
       JSON/XML 파싱 + 페이지 순회
                  |
                  v
      Raw staging + SHA-256 비교
                  |
          변경된 레코드만 선별
           /                 \
          v                   v
NCS catalog/criteria      RAG chunk builder
구조화 upsert             출처·범위 metadata
                              |
                              v
                  LiteLLM embedding provider
                              |
                              v
             Supabase lessonpack_chunks upsert
                              |
                              v
                 검색 smoke test + sync report
```

운영 생성 요청에서 외부 API를 직접 호출하지 않는다. API 동기화와 사용자 검색을 분리해 공식 API 장애가 LessonPack 생성 요청의 장애로 전파되지 않도록 한다.

## 5. 데이터 모델

### 5.1 기존 테이블 활용

| 테이블 | 변경 방향 |
| --- | --- |
| `lessonpack_ncs_catalog` | 능력단위 코드 기준 upsert, 정의·분류·수준·버전·API 조회 시각 보완 |
| `lessonpack_ncs_criteria` | 능력단위·요소·수행준거 순번으로 만든 결정적 코드 기준 upsert, 요소·KSA·평가지침 보완 |
| `lessonpack_chunks` | 결정적 chunk ID로 공식 API 근거를 `mvp-dataset` baseline에 upsert |

### 5.2 신규 테이블

`008_ncs_official_api_sync.sql`에서 다음 테이블을 추가한다.

#### `lessonpack_ncs_source_records`

| 열 | 설명 |
| --- | --- |
| `source_key` | `operation:official_id` 형식의 기본키 |
| `operation` | 공식 API Operation |
| `entity_type` | classification, unit, element, criterion, module 등 |
| `unit_code` | 연결 가능한 능력단위 코드, 없으면 null |
| `payload` | 원본 응답을 보존한 JSONB |
| `payload_hash` | 정규화된 payload의 SHA-256 |
| `fetched_at` | 실제 조회 시각 |
| `active` | 최신 전체 동기화에서 존재하는지 여부 |

#### `lessonpack_ncs_sync_runs`

| 열 | 설명 |
| --- | --- |
| `run_id` | 동기화 실행 ID |
| `mode` | catalog, detail, modules, all |
| `status` | running, partial, completed, failed |
| `checkpoint` | operation, page, 마지막 unit code |
| `request_count` | 공식 API 요청 수 |
| `received_count` | 수신 레코드 수 |
| `changed_count` | hash가 변경된 레코드 수 |
| `chunk_upsert_count` | 임베딩·upsert한 chunk 수 |
| `error_count` | 실패 건수 |
| `started_at`, `finished_at` | 실행 시간 |
| `error_summary` | 비밀정보를 제거한 오류 요약 |

#### `lessonpack_ncs_modules`

| 열 | 설명 |
| --- | --- |
| `module_id` | 공식 학습모듈 번호 |
| `module_name` | 학습모듈명 |
| `module_text` | API가 제공한 내용 |
| `classification` | 대·중·소·세분류 JSONB |
| `unit_code` | 연결이 검증된 경우만 저장, 아니면 null |
| `link_status` | exact, candidate, unresolved |
| `source_url` | 공공데이터포털 공식 페이지 |
| `payload_hash`, `fetched_at` | 변경 추적 |

학습모듈 API에 능력단위 코드가 없으므로 이름이 유사하다는 이유만으로 자동 확정하지 않는다. 정규화된 명칭과 세분류가 모두 일치할 때만 `exact`, 나머지는 `candidate` 또는 `unresolved`로 저장한다.

공식 응답의 수행준거 식별자가 전역에서 유일하다고 보장되지 않으면 `criterion_code`는 `{unit_code}:{element_code}:{criterion_number}` 형식으로 생성한다. 표시 문구가 바뀌어도 동일 수행준거의 이력을 추적할 수 있도록 본문 hash를 기본키로 사용하지 않는다.

## 6. RAG chunk 설계

### 6.1 chunk 종류

| `chunk_type` | 단위 | 포함 내용 |
| --- | --- | --- |
| `ncs_unit_overview` | 능력단위 1개 | 코드, 명칭, 정의, 수준, 분류 |
| `ncs_element_criteria` | 능력단위요소 1개 | 요소와 수행준거, KSA |
| `ncs_scope` | 능력단위 1개 | 적용범위, 작업상황, 장비 |
| `ncs_evaluation` | 능력단위 1개 | 평가지침, 평가방법 |
| `ncs_training_standard` | 능력단위 1개 | 훈련시간, 고려사항, 출제기준 |
| `ncs_learning_module_summary` | 학습모듈 1개 | 모듈 번호·명칭·API 제공 내용 |

하나의 chunk가 1,200~1,800자를 초과하면 항목 경계를 보존해 분리한다. 공식 응답에 수행준거 식별자가 함께 제공된 KSA만 해당 수행준거에 병합한다. 명시적 연결 키가 없는 KSA는 임의로 연결하지 않고 동일 능력단위요소의 독립 source/RAG 근거로 보존한다.

### 6.2 결정적 식별자

```text
chunk_id = ncs-api:{operation}:{unit_code_or_module_id}:{section}:{content_hash_12}
document_id = ncs-api:{unit_code_or_module_id}
project_id = mvp-dataset
scope = baseline
```

내용이 같으면 같은 `chunk_id`가 생성된다. 내용이 변경되면 새 chunk를 upsert한 후, 해당 source의 이전 hash chunk를 비활성화하거나 삭제한다. 삭제는 전체 operation 동기화가 성공한 뒤에만 수행한다.

### 6.3 필수 metadata

```json
{
  "dataset": "ncs_official_api",
  "provider": "한국산업인력공단",
  "operation": "ncsKsaInfo",
  "chunk_type": "ncs_element_criteria",
  "unit_code": "0101010101_17v2",
  "unit_name": "공적개발원조사업 개발전략수립",
  "element_code": "optional",
  "catalog_version": "17v2",
  "content_scope": "structured_detail",
  "source_url": "https://www.data.go.kr/data/15157547/openapi.do",
  "fetched_at": "ISO-8601",
  "payload_hash": "sha256"
}
```

학습모듈 API chunk에는 `content_scope=module_api_summary`를 사용해 원문 기반 chunk와 구별한다.

## 7. 동기화 처리 흐름

### 7.1 실행 모드

```powershell
python scripts/sync_ncs_official_api.py --mode catalog --resume
python scripts/sync_ncs_official_api.py --mode detail --resume
python scripts/sync_ncs_official_api.py --mode modules --resume
python scripts/sync_ncs_official_api.py --mode all --resume --embed
```

`--dry-run`, `--limit`, `--unit-code`, `--max-requests`, `--resume`을 지원한다. `--unit-code`는 catalog에 저장된 정확한 NCS 능력단위 코드와 일치하는 상세 작업만 선택한다.

### 7.2 순서

1. sync run을 생성하고 이전 체크포인트를 읽는다.
2. 분류·능력단위 목록을 페이지 단위로 수집한다.
3. XML/JSON을 공통 canonical schema로 정규화한다.
4. API 키를 포함하지 않은 정규화 payload와 hash를 staging에 upsert한다.
5. 이전 hash와 다른 레코드만 상세 테이블과 chunk 생성 대상으로 보낸다.
6. catalog와 criteria를 결정적 기본키로 순차 upsert해 재실행 가능한 상태를 유지한다.
7. 변경된 chunk만 현재 `text-embedding-3-small`, 1536차원 설정으로 임베딩한다.
8. `lessonpack_chunks`에 batch upsert한다.
9. source row 수, 공식 chunk 수, 최근 성공 작업의 신선도와 선택적 RAG query를 검증한다.
10. 각 operation을 처음부터 끝까지 조회한 경우에만 누락 source를 비활성화하고 기존 chunk를 삭제한다.

### 7.3 할당량과 백필

개발계정의 일 10,000회 한도를 전체 상세 endpoint × 전체 능력단위 방식으로 한 번에 소진하면 안 된다.

- 기본 요청 예산: 일 5,000회
- 기본 속도: 초당 2회, 환경변수로 조정
- HTTP 429·5xx와 네트워크 오류: 지수 backoff로 최대 5회 재시도
- 재시도할 수 없는 4xx·스키마 오류: run을 `failed`로 기록하고 체크포인트에서 운영자가 재개
- 단일 코드 긴급 보완: `--unit-code`로 제한 실행
- 수행준거 0개 우선순위 큐와 dead-letter는 운영 고도화 단계에서 추가
- 상세 백필: 체크포인트를 사용해 여러 날에 걸쳐 진행
- 페이지 크기: API 허용 최대치를 Swagger에서 확인한 뒤 설정
- 운영 전 실제 활용사례를 등록해 트래픽 증량 신청

API가 수정일 필터를 제공하지 않으면 주 1회 목록을 순회하고 hash가 같은 상세 레코드는 임베딩하지 않는다.

## 8. 환경변수와 Secret

`.env.example`에 다음 항목을 추가한다.

```dotenv
LESSONPACK_NCS_API_ENABLED=false
DATA_GO_KR_SERVICE_KEY=
LESSONPACK_NCS_API_BASE_URL=https://apis.data.go.kr/B490007/ncsInfo
LESSONPACK_NCS_REFERENCE_API_BASE_URL=https://apis.data.go.kr/B490007/hrdkapi
LESSONPACK_NCS_MODULE_API_URL=https://apis.data.go.kr/B490007/ncsStudyModule/openapi21
LESSONPACK_NCS_SYNC_PROJECT_ID=mvp-dataset
LESSONPACK_NCS_SYNC_PAGE_SIZE=100
LESSONPACK_NCS_SYNC_REQUESTS_PER_SECOND=2
LESSONPACK_NCS_SYNC_MAX_REQUESTS=5000
LESSONPACK_NCS_SYNC_STALE_DAYS=7
```

`DATA_GO_KR_SERVICE_KEY`는 GitHub Actions secret과 GCE 서버 `.env`에만 저장한다. 로그, sync run payload, Langfuse metadata에 키를 기록하지 않는다.

## 9. 구현 구성

| 파일 | 역할 |
| --- | --- |
| `services/ncs_official_api.py` | 인증, 요청, XML/JSON 파싱, 페이지 순회, retry |
| `services/ncs_sync_service.py` | canonical 변환, hash 비교, 체크포인트, upsert 조정 |
| `services/ncs_rag_chunk_builder.py` | 구조화 레코드를 RAG chunk로 변환 |
| `scripts/sync_ncs_official_api.py` | dry-run, resume, mode, quota를 제공하는 CLI |
| `scripts/verify_ncs_official_sync.py` | DB row, 상세정보, 검색, RAG smoke test |
| `008_ncs_official_api_sync.sql` | staging, modules, sync runs 및 인덱스 |
| `.github/workflows/ncs-sync.yml` | 수동 실행, 카탈로그·상세·모듈 분리 schedule, 자동 검증 |

FastAPI 공개 엔드포인트에서 동기화를 시작하지 않는다. 운영자가 GitHub Actions `workflow_dispatch` 또는 GCE CLI로 실행하도록 하고, 추후 관리자 인증과 작업 큐가 준비되면 비공개 admin endpoint를 검토한다.

## 10. 스케줄과 운영

| 작업 | 주기 | 내용 |
| --- | --- | --- |
| catalog sync | 매주 월요일 03:00 KST | 분류·능력단위 변경 감지 |
| detail backfill | 매일 03:30 KST | 요청 예산 범위에서 수행준거 0개 항목 보완 |
| module sync | 매주 화요일 03:00 KST | 학습모듈 메타데이터·내용 갱신 |
| verification | 각 sync 직후 | 코드/명칭 검색, row 수, RAG query 검증 |
| full audit | 매월 1회 | 비활성 source와 orphan chunk 점검 |

GitHub Actions schedule은 UTC 기준으로 작성한다. 동시 실행은 `concurrency`로 1개만 허용하고, 이전 실행이 진행 중이면 새 작업을 취소하지 않고 대기 또는 종료한다.

## 11. 검증 계획

### 11.1 단위 테스트

- XML namespace 유무와 빈 필드 파싱
- JSON/XML 오류 응답 식별
- service key가 로그와 예외에 노출되지 않음
- 페이지 종료 조건과 중복 제거
- 동일 payload의 hash 안정성
- 수행준거·KSA canonical 매핑
- 학습모듈 `exact/candidate/unresolved` 연결
- 결정적 chunk ID와 metadata

공식 응답에서 개인정보와 키를 제거한 fixture를 저장해 외부 API 없이 CI에서 테스트한다.

### 11.2 통합 테스트

1. `--dry-run --limit 10`으로 API 응답과 canonical schema를 확인한다.
2. 테스트 Supabase에 능력단위 100개를 적재한다.
3. 같은 작업을 두 번 실행해 두 번째 `changed_count=0`, `chunk_upsert_count=0`을 확인한다.
4. fixture 하나를 변경해 해당 source chunk만 재임베딩되는지 확인한다.
5. 중간에 실패시킨 후 `--resume`으로 다음 page부터 재개한다.
6. 실제 코드·명칭 검색과 `criteria` 반환을 확인한다.
7. 대표 질의로 `ncs_official_api` chunk가 top-k에 포함되는지 확인한다.

### 11.3 운영 완료 기준

- 공식 API의 능력단위 총계와 catalog upsert 결과가 일치한다.
- `lessonpack_ncs_catalog`의 중복 코드가 0건이다.
- API 상세정보가 확보된 단위는 criteria가 1개 이상이다.
- 상세정보가 없는 단위만 `수행준거 0개`로 남는다.
- 공식 API chunk의 출처 누락이 0건이다.
- 동일 sync 재실행 시 중복 chunk가 0건이다.
- 실패 작업이 체크포인트에서 재개된다.
- 임베딩 모델·차원·버전이 운영 설정과 일치한다.
- 코드 검색, 명칭 검색, 대표 RAG query 검증이 모두 통과한다.

## 12. 단계별 로드맵

### 1단계: API 탐색과 fixture 확보

- 공공데이터포털 활용신청과 service key 발급
- Operation별 필수 파라미터·페이지 최대값 확인
- 대표 코드 응답 fixture 저장
- XML/JSON 공통 오류 모델 정의

### 2단계: 수집·정규화 구현

- API client, retry, rate limit
- canonical schema와 raw staging
- sync run과 checkpoint
- catalog·criteria upsert

### 3단계: RAG 변환·증분 임베딩

- chunk builder와 결정적 ID
- payload hash 변경 감지
- 기존 LiteLLM embedding provider 연결
- 이전 chunk 정리 정책 구현

### 4단계: 학습모듈·자동화

- 학습모듈 API 동기화
- 보수적인 능력단위 연결
- GitHub Actions 수동·주간 workflow
- GCE/GitHub secret 전달

### 5단계: 실증·운영 전환

- 100개 샘플 적재와 검색 평가
- 수행준거 0개 우선 백필
- 전체 백필 시작과 일일 리포트
- 운영계정 트래픽 증량 신청

## 13. 범위 제외

- NCS 사이트 화면을 비공식 크롤링하는 기능
- API가 제공하지 않는 학습모듈 PDF/HWP 원문의 자동 다운로드
- 이름 유사도만으로 학습모듈과 능력단위를 확정하는 기능
- 서로 다른 차원의 임베딩을 동일 vector column에 혼합하는 기능
- 공식 API 장애 시 LLM으로 수행준거를 만들어 공식 데이터로 저장하는 기능
