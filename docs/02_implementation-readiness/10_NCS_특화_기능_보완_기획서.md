# NCS 특화 기능 보완 기획서

> 작성일: 2026-07-22  
> 대상: LessonPack AI FastAPI 백엔드, Lovable 웹 UI, Supabase RAG  
> 목적: 강의 유형을 NCS 기반과 일반 강의로 명확히 구분하고, NCS 기반 강의의 설계·근거·평가 정합성을 자동 검증한다.

## 구현 현황

2026-07-22 기준 1차 코드 구현과 로컬 회귀 검증을 완료했다.

| 영역 | 구현 결과 |
| --- | --- |
| 입력·계약 | `course_type` 필수 선택, NCS/일반 입력 상호 배타 검증, 공식·사용자 제공·확인 필요 출처 상태 적용 |
| Catalog | XLS 변환 Markdown에서 고유 능력단위 202개와 수행준거 2,452개 생성, 검색·상세 API 구현 |
| RAG | NCS 모드는 능력단위·대상 수행준거를 query에 포함하고, 일반 모드는 baseline NCS chunk를 제외 |
| 생성 | 산출물별 `ncs_criteria` 허용 목록·누락·평가 연결 검증과 일반 강의 NCS 오표기 차단 적용 |
| UI | 첫 단계 강의 유형 선택, catalog 검색, 대상 수행준거 선택, coverage·경고 표시 구현 |
| Export | NCS 수행준거 연결표와 일반 학습목표 연결표로 DOCX/PPTX 분기 |
| 평가 | 수행준거 커버리지 90%, 평가 커버리지 100% 게이트와 일반 모드 회귀 테스트 추가 |

로컬 검증은 backend `119 passed, 3 subtests passed`, frontend lint 오류 0건 및 production build 성공, mock provider 기반 MVP 품질 게이트 전체 PASS다. catalog 전처리는 고유 능력단위 202개, 수행준거 2,452개, 수행준거 누락 능력단위 0개로 재현했다. 실제 LiteLLM·운영 Supabase를 이용한 NCS 특화 실증은 migration과 catalog 업로드 후 별도로 수행한다.

운영 반영에는 [`006_ncs_course_specialization.sql`](../../supabase/migrations/006_ncs_course_specialization.sql) 적용과 `python scripts/prepare_ncs_catalog.py --upload` 실행이 필요하다. 이 외부 Supabase 변경은 로컬 코드 구현과 분리해 배포 담당자가 수행한다. 적용 전에는 기존 RAG는 동작하지만 catalog 검색과 새 프로젝트 영속화 readiness를 통과하지 못한다.

아직 남은 범위는 NCS·일반 강의 분야별 실증 3건 이상, NCS 강사 2명 이상 평가, 안정적인 `criterion_id` 영속 계약, catalog 버전 이력·변경 자동 감지, P2 성취 포트폴리오다. 1~3주차의 핵심 MVP 흐름은 구현했지만, 아래 상세 설계 중 별도 `NCSProfile`, criterion ID, catalog version table은 기존 `ncs_units` 호환성을 유지하기 위해 후속 hardening 범위로 남긴다. 4주차 운영 실증은 진행 전이다.

## 1. 배경과 문제 정의

현재 LessonPack AI는 `ncs_units` 입력, NCS 확장 RAG chunk, 산출물별 `ncs_alignment`, NCS 연결률 평가를 이미 지원한다. 또한 `data/NCS_raw/`에서 변환한 218개 Markdown과 19,103개 chunk를 Supabase에 적재해 사업관리, 경영·회계·사무, 금융·보험 분야를 검색할 수 있다.

다만 현재 프로젝트 입력은 NCS 강의인지 일반 강의인지 명시하지 않는다. 따라서 다음 문제가 남아 있다.

- 일반 기관 교육에도 빈 NCS alignment가 포함될 수 있어 사용자와 외부 평가자가 강의의 근거 성격을 혼동할 수 있다.
- NCS 강의에서 입력한 코드·명칭이 공식 catalog에 존재하는지, 어떤 수행준거를 이번 차시에 다룰지 확인하지 않는다.
- 생성된 교안·실습·평가가 선택한 수행준거를 얼마나 빠짐없이 다뤘는지 사람이 별도로 확인해야 한다.
- NCS 자료가 없는 신규 분야에서는 업로드 자료 fallback이 동작하지만, 이것이 공식 NCS 근거인지 사용자 제공 근거인지 구분하는 제품 표지가 부족하다.

이 기획의 핵심은 **NCS 모드는 기준을 검증하고, 일반 모드는 NCS를 주장하지 않는다**는 원칙이다.

## 2. 목표와 비목표

### 2.1 목표

1. 프로젝트 생성 첫 단계에서 `NCS 기반 강의`와 `일반 강의` 중 하나를 반드시 선택한다.
2. NCS 기반 강의는 능력단위 코드, 능력단위요소, 수행준거, 평가기준을 생성·검증 흐름에 연결한다.
3. NCS 기준의 출처 상태를 `공식 catalog 확인`, `사용자 제공 기준`, `확인 필요`로 구분한다.
4. 교안·실습·평가의 수행준거 커버리지를 자동 계산하고 누락을 경고한다.
5. 일반 강의는 학습목표와 업로드 교재를 근거로 생성하되 NCS 정합성·NCS 출처 표기를 표시하지 않는다.
6. 전체 NCS 분류 및 전체 능력단위 종류 등의 NCS 관련 공식 정보는 NCS 포털이나 외부 사이트를 크롤링하거나 수집하여 적용한다. 
7. 기능 구현이 모두 완료되면, 전체적인 UI/UX를 점검하고 개선한다. 

### 2.2 비목표

- 하나의 차시에서 선택 능력단위 전체를 반드시 완주하도록 강제하지 않는다. 이번 차시에 다룰 `대상 수행준거`만 선택한다.
- 자동 채점, 훈련생 이력 관리, 기관별 권한 관리는 이번 기능 범위에 포함하지 않는다.
- 사용자 업로드 자료만으로 공식 NCS 적합성을 확정하지 않는다.

## 3. 도메인 원칙

NCS 능력단위는 능력단위요소, 수행준거, 지식·기술·태도(KSA), 적용범위·작업상황, 평가지침, 직업기초능력으로 구성된다. NCS 학습모듈은 이 능력단위를 교육훈련에 활용할 수 있도록 학습목표, 학습내용, 교수학습방법, 평가와 피드백으로 구성한 자료다. 따라서 LessonPack AI의 NCS 특화는 문서 이름을 인용하는 기능이 아니라 **수행준거가 학습활동과 평가에 실제로 연결되는지 확인하는 기능**이어야 한다.

공식 NCS 자료에 포함된 제3자 도표·사진·삽화 등은 별도 권리 확인이 필요하다. 서비스는 텍스트 근거, 원문 위치, 출처 URL, 라이선스 주의문을 보존하고, 원문 이미지의 재배포를 자동화하지 않는다.

## 4. 입력 단계 UX와 분기

### 4.1 첫 입력: 강의 유형 선택

프로젝트 생성 화면의 첫 항목에 필수 세그먼트 컨트롤을 둔다. 기본값을 두지 않아 사용자가 강의 성격을 명시적으로 선택하게 한다.

| 선택값 | 화면 문구 | 생성·검증 정책 |
| --- | --- | --- |
| `ncs` | NCS 기반 강의 | 능력단위와 대상 수행준거를 입력하고 NCS 정합성 검증을 실행한다. |
| `general` | 일반 강의 | 자체 커리큘럼·기관 교육·비직업훈련 강의로 생성한다. NCS 입력과 NCS 정합성 표시는 사용하지 않는다. |

공통 입력은 과정명, 차시명, 학습자 수준, 선수지식, 총 훈련시간, 총 차시, 이론·실습 비율, 학습목표, 근거 검색어, 업로드 교재다.

### 4.2 NCS 기반 강의 입력

`ncs` 선택 시 아래 블록을 추가로 표시한다.

| 필드 | 입력 방식 | 검증 |
| --- | --- | --- |
| NCS 분류 | 대분류·중분류·소분류·세분류 탐색 또는 검색 | catalog 값이면 선택값을 저장 |
| 능력단위 | 코드·명칭 자동완성, 최대 5개 | 코드 중복 금지 |
| 대상 수행준거 | 능력단위별 체크박스, 이번 차시에 다룰 항목만 선택 | 최소 1개 필수 |
| 기준 출처 | `공식 catalog`, `사용자 제공 NCS 문서` 중 선택 | 사용자 제공이면 자료 업로드와 연결 |
| 버전·적용연도 | catalog 자동 표시, 불명확하면 사용자 확인 | 오래되었거나 불명확하면 경고 |

공식 catalog에서 발견한 능력단위는 `verified`로 저장한다. catalog에 없는 코드이지만 기관 문서와 수행준거가 업로드된 경우에는 `user_provided`로 생성할 수 있으나, 결과와 export에 `사용자 제공 기준: 공식 NCS 확인 필요`를 표시한다. 코드도 수행준거도 없는 NCS 강의는 생성 요청을 `422`로 거절한다.

### 4.3 일반 강의 입력

`general` 선택 시 NCS 블록을 숨기고 다음을 사용한다.

- 학습목표와 핵심 개념·기술 태그
- 기관 자체 역량기준 또는 강의계획서 업로드 여부
- 선택형 교육 프레임워크 태그(예: 사내 교육, 대학 교과, 자격 대비)
- 평가 기준 또는 루브릭의 자유 서술

일반 강의 산출물에서는 NCS 능력단위, 수행준거, NCS alignment, NCS 커버리지 점수를 저장·표시·export하지 않는다. 대신 학습목표와 업로드 자료 근거의 연결을 검증한다.

### 4.4 유형 변경 규칙

업로드 자료나 패키지가 이미 생성된 프로젝트에서는 강의 유형을 직접 변경하지 않는다. 사용자는 프로젝트 복제를 통해 새 유형의 프로젝트를 만들고 다시 검색·생성해야 한다. 이 규칙은 NCS 근거와 일반 교재 근거가 동일 retrieval run 또는 산출물에 섞이는 것을 막는다.

## 5. 데이터·API 설계

### 5.1 프로젝트 스키마 확장

```text
ProjectCreate / Project
  course_type: "ncs" | "general"                 # 필수
  ncs_profile: NCSProfile | null

NCSProfile
  source_status: "verified" | "user_provided" | "needs_review"
  catalog_version: string | null
  units: NCSUnitSelection[]

NCSUnitSelection
  unit_code: string
  unit_name: string
  classification: { major, middle, minor, detailed }
  level: number | null
  target_criteria: NCSPersonCriteria[]             # 이번 차시 대상만 저장
  evidence_document_ids: string[]                  # user_provided일 때 필수
```

기존 `ncs_units`는 마이그레이션 기간에 읽기 호환용으로 유지하고, 새 API에서는 `course_type=ncs`일 때만 `ncs_profile.units`에서 파생한다. 기존 프로젝트는 `ncs_units`가 비어 있으면 `general`, 하나 이상이면 `ncs`와 `needs_review`로 이관한다.

### 5.2 catalog 저장소

Supabase에 `lessonpack_ncs_catalog`과 `lessonpack_ncs_criteria`를 추가한다. PDF chunk와 별도로 구조화된 XLS 능력단위 보고서에서 아래 필드를 추출한다.

| 테이블 | 핵심 열 | 용도 |
| --- | --- | --- |
| `lessonpack_ncs_catalog` | `unit_code`, `unit_name`, 분류 계층, 수준, 정의, 버전, source URL | 입력 자동완성·코드 검증 |
| `lessonpack_ncs_criteria` | `unit_code`, `element_code`, 요소명, `criterion_code`, 수행준거, KSA, 평가지침 | 대상 수행준거 선택·커버리지 검사 |
| `lessonpack_ncs_catalog_versions` | import 일시, 원본 해시, 적용연도, 상태 | 변경 감지·감사 |

현재 NCS 확장 전처리에서 XLS를 능력단위 경계 Markdown으로 변환하고 코드·계층·출처·버전을 보존하므로, catalog 적재는 이 변환 결과를 재사용한다. PDF 본문 검색은 학습모듈 설명과 교수·학습 근거에 사용하고, 코드 검증은 구조화 catalog를 우선한다.

### 5.3 API 계약

| API | 역할 | 주요 규칙 |
| --- | --- | --- |
| `GET /api/ncs/catalog/search` | 코드·명칭·분류 자동완성 | 공개 baseline catalog만 검색 |
| `GET /api/ncs/catalog/{unit_code}` | 요소·수행준거·버전 조회 | `verified` 결과만 반환 |
| `POST /api/projects` | 유형별 프로젝트 생성 | `ncs`는 대상 수행준거 필수, `general`은 NCS payload 금지 |
| `GET /api/projects/{id}/ncs-coverage` | 생성 패키지의 수행준거 커버리지 | `ncs` 프로젝트에서만 제공 |
| `POST /api/projects/{id}/generate` | 유형별 RAG·프롬프트·검증 실행 | 유형 전환 또는 혼합 근거 거절 |

## 6. RAG·생성·export 동작

```text
강의 유형 선택
  ├─ NCS 기반: catalog 검증 → 대상 수행준거 선택 → NCS query + 교재 query 검색
  │             → 수행준거 정렬 생성 → coverage 검사 → NCS 근거표 포함 export
  └─ 일반 강의: 학습목표 + 교재 query 검색 → 일반 강의 생성 → 목표·근거 검사 → 일반 export
```

### 6.1 NCS 기반 RAG

1. Query Builder는 과정명, 차시명, 학습목표, 능력단위 코드·명칭, 대상 수행준거를 분리된 query로 만든다.
2. 공식 catalog와 NCS 학습모듈 chunk에는 `unit_code`, `source_year`, `source_url`, `license_notice` metadata filter를 적용한다.
3. 프로젝트 업로드 자료는 항상 우선 검색한다. catalog에 없는 분야는 업로드 자료 fallback을 사용하되 `evidence_authority=user_provided`를 남긴다.
4. 공식 NCS 근거가 없으면 모델이 수행준거를 새로 만들지 못하게 하고, 입력된 사용자 기준 또는 교재 범위 안에서만 생성한다.
5. retrieval run에는 `course_type`, catalog 버전, 대상 수행준거 코드, 근거 권한을 저장한다.

### 6.2 NCS 기반 생성 규칙

- 각 교안 흐름, 실습 단계, 객관식 문항, 수행평가 루브릭은 하나 이상의 대상 수행준거에 연결한다.
- 수행평가는 수행준거와 평가지침을 우선하고, 객관식은 지식·기술·태도를 보조 검증한다.
- 생성 JSON에는 `criterion_ids`, `ncs_alignment`, `evidence_source_ids`를 분리 저장한다.
- 동일 수행준거만 반복 연결하거나, 선택하지 않은 수행준거를 새로 선언하면 schema validation에서 거절한다.
- 마지막 출처 단원에는 능력단위·수행준거별 근거표를 묶어 표시하고, 본문에는 짧은 연결 라벨만 사용한다.

현재 MVP provider 계약은 stable ID 전환 전 단계로 `ncs_criteria`에 선택 수행준거 문장을 정확히 반환하게 한다. 백엔드는 각 산출물의 값이 선택 목록에 속하는지, 모든 항목이 기준을 갖는지, 모든 대상 기준이 평가에 연결됐는지 검증한다. 검증된 값을 내부 `ncs_alignment`와 coverage로 변환한다. catalog의 `criterion_code`를 프로젝트 선택과 generation log에 직접 영속하는 작업은 후속 hardening에서 수행한다.

### 6.3 일반 강의 생성 규칙

- 학습목표, 수준, 선수지식, 시간, 교재 근거를 생성 제약으로 사용한다.
- 평가 문항은 학습목표와 연결하지만 `NCS alignment` 필드는 비어 있는 것이 아니라 응답 schema에서 제외한다.
- export에는 NCS 근거표 대신 `학습목표-활동-평가 연결표`와 교재 출처 목록을 제공한다.

## 7. NCS 특화 사용자 기능

| 우선순위 | 기능 | 사용자 가치 | 완료 기준 |
| --- | --- | --- | --- |
| P0 | NCS/일반 강의 유형 선택 | 강의 성격과 생성 기준을 명확히 구분 | 유형 미선택 시 생성 불가 |
| P0 | NCS catalog 검색·코드 검증 | 잘못된 코드와 임의 명칭을 예방 | 선택 코드의 catalog 확인 상태 표시 |
| P0 | 대상 수행준거 선택 | 한 차시 범위를 현실적으로 제한 | 최소 1개 기준을 선택해야 생성 가능 |
| P1 | 수행준거 커버리지 매트릭스 | 교안·실습·평가의 누락을 즉시 확인 | 기준별 교안/실습/평가 연결 현황 제공 |
| P1 | 평가 blueprint·루브릭 | 수행평가가 직무 기준에 맞게 구성 | 대상 수행준거마다 평가 근거 1개 이상 |
| P1 | NCS 기준 출처표 | 감사·기관 제출에 필요한 근거 제공 | export 마지막 단원에 출처·버전·권한 표시 |
| P2 | 버전 변경 경고 | 개정된 NCS로 인한 낡은 패키지 예방 | catalog 버전 차이와 재생성 안내 |
| P2 | 훈련생 성취 포트폴리오 | 차시 결과를 수행준거별로 축적 | 이번 범위에서는 설계만, 별도 승인 후 구현 |

## 8. 커버리지·품질 검증

### 8.1 NCS 모드 지표

| 지표 | 계산 | MVP 기준 |
| --- | --- | --- |
| catalog 확인율 | `verified unit / 선택 unit` | 공식 선택 모드 100% |
| 수행준거 커버리지 | 교안·실습·평가 중 하나 이상에 연결된 대상 기준 / 대상 기준 | 90% 이상, 미달 시 경고 |
| 평가 커버리지 | 평가에 연결된 대상 기준 / 대상 기준 | 100% 또는 명시적 제외 사유 |
| 근거 권한 표기율 | 선택 NCS 근거에 authority·source URL·version이 있는 비율 | 100% |
| 허위 정렬률 | catalog/사용자 기준에 없는 criterion ID 연결 수 | 0건 |
| 시간 정합성 | 차시 활동 시간 합계와 입력 차시 시간의 차이 | ±10% 이내 |

### 8.2 일반 모드 지표

| 지표 | 기준 |
| --- | --- |
| 학습목표 연결률 | 교안·실습·평가 항목이 하나 이상의 학습목표에 연결 |
| 교재 근거 커버리지 | 주요 산출물에 유효 citation 존재 |
| NCS 오표기 | `ncs_alignment`, NCS 코드, NCS 출처 단원이 0건 |
| 유형 혼합 방지 | non-NCS retrieval run에 baseline NCS chunk가 생성 근거로 포함되지 않음 |

### 8.3 자동·사람 검증

자동 테스트는 Pydantic schema, catalog resolver, RAG metadata filter, coverage 계산, export 분기, 기존 패키지 호환성을 검사한다. 사람 평가는 NCS 훈련 경험이 있는 강사 2명 이상이 수행준거 적합성, 실습 현실성, 평가 가능성, 근거 정확성을 5점 척도로 평가한다. NCS 모드 평균 4.0점 미만이면 해당 분야의 prompt·catalog·학습모듈 chunk를 재검토한다.

## 9. 구현 순서

### 1주차: 강의 유형과 데이터 계약

1. `course_type`과 `NCSProfile` schema를 추가한다.
2. Lovable 입력 화면에 유형 선택과 조건부 NCS 블록을 추가한다.
3. 기존 프로젝트를 읽기 호환 방식으로 이관하고, 유형 변경 시 프로젝트 복제를 유도한다.
4. NCS/일반 모드 fixture와 API validation test를 추가한다.

### 2주차: 구조화 catalog와 입력 검증

1. XLS 변환 결과에서 `lessonpack_ncs_catalog`, `lessonpack_ncs_criteria` 적재 스크립트와 migration을 만든다.
2. 코드·명칭 검색 API와 수행준거 조회 API를 구현한다.
3. 공식·사용자 제공·확인 필요 상태와 버전 표시를 UI에 연결한다.

### 3주차: RAG·생성·coverage 분기

1. 유형별 query builder와 metadata filter를 구현한다.
2. 생성 schema와 prompt를 NCS/일반 모드로 분리한다.
3. 수행준거-교안-실습-평가 매트릭스와 자동 경고를 구현한다.
4. DOCX/PPTX를 NCS 근거표형과 일반 목표 연결표형으로 분기한다.

### 4주차: 실증과 운영 보완

1. NCS 3개 분야와 일반 강의 3개 분야의 gold case를 작성한다.
2. Supabase 실제 검색, 생성, export, 자연어 재생성 회귀 테스트를 수행한다.
3. 강사 평가와 오류 사례를 반영해 threshold·prompt·chunk metadata를 보정한다.
4. NCS 원본 해시·버전 변경 감시와 저작권 고지 점검을 문서화한다.

## 10. 수용 기준

다음 조건을 모두 충족하면 1차 구현을 완료로 본다.

1. 사용자는 프로젝트 생성 전에 NCS 기반 또는 일반 강의를 선택해야 한다.
2. NCS 기반 강의는 대상 수행준거 없이 생성할 수 없고, 공식 여부를 화면과 export에서 확인할 수 있다.
3. 일반 강의 결과에는 NCS 코드·NCS alignment·NCS 근거표가 포함되지 않는다.
4. NCS 패키지는 선택 수행준거별 교안·실습·평가 연결 표와 누락 경고를 제공한다.
5. 생성·재생성·다운로드 후에도 `course_type`, catalog 버전, coverage 결과, 근거 권한이 유지된다.
6. 기존 NCS 프로젝트·일반 프로젝트·업로드 자료 fallback·DOCX/PPTX export 회귀 테스트가 통과한다.

## 11. 참고 자료

- [NCS 구성: 능력단위·수행준거·KSA·평가지침](https://www.ncs.go.kr/mobile/rm01/TH10200103.do)
- [NCS 학습모듈 개념과 교수·학습·평가 연결](https://www.ncs.go.kr/th01/TH-102-002-01.scdo)
- [NCS 기반 훈련과정 편성·평가도구 활용 매뉴얼](https://ncs.go.kr/vt/guide/ncsTrainGuide.pdf)
- [NCS 학습모듈 활용·저작권 안내](https://ncs.go.kr/unity/th03/ncsModuleFileSearch.do)
- [NCS 확장 데이터셋 처리 및 RAG 검증 결과](09_NCS_확장_데이터셋_처리_검증_결과.md)
- [RAG 구축 및 연동 기획서](07_RAG_구축_연동_기획서.md)
