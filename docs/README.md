# LessonPack AI 문서 안내

이 디렉터리는 서비스 기획, 구현 계약, 운영 절차와 검증 근거를 보관합니다. 실제 실행 방식이 문서와 다를 경우 `README.md`, `.env.example`, `config.example.yaml`, 현재 `src/` 코드와 최신 Supabase migration을 우선합니다.

## 빠른 탐색

### 서비스를 이해하려는 사용자

1. [프로젝트 README](../README.md)
2. [MVP 통합 기획서](00_project-brief/01_MVP_통합_기획서.md)
3. [서비스 컨셉·기능 정의서](01_kosena-service-planning/05_서비스_컨셉_기능_정의서.md)
4. [최종 발표자료](01_kosena-service-planning/07_최종_발표자료.md)

### 개발·운영 담당자

1. [구현명세서](02_implementation-readiness/01_구현명세서.md)
2. [WBS](03_architecture/01_WBS.md)
3. [시퀀스 다이어그램](03_architecture/02_시퀀스_다이어그램.md)
4. [배치 다이어그램](03_architecture/03_배치_다이어그램.md)
5. [데이터셋 안내](../data/README_DATASET.md)
6. [RAG 구축·연동](02_implementation-readiness/07_RAG_구축_연동_기획서.md)
7. [검증 프로토콜](02_implementation-readiness/03_검증_프로토콜.md)
8. [GCE·Docker·CI/CD](02_implementation-readiness/05_GCE_Docker_CICD_배포_계획서.md)
9. [NCS 전체 카탈로그](02_implementation-readiness/11_NCS_전체_카탈로그_검색_구축.md)
10. [NCS 공식 API 동기화](02_implementation-readiness/12_NCS_공식_API_RAG_자동_동기화_기획서.md)
11. [PPT 템플릿 생성](02_implementation-readiness/13_PPT_템플릿_기반_강의자료_생성_기획서.md)

### 품질 결과를 확인하려는 평가자

1. [MVP 품질 평가 결과](04_validation/01_MVP_품질_평가_결과.md)
2. [Langfuse Trace 검증 결과](04_validation/02_Langfuse_trace_검증_결과.md)
3. [NCS 확장 데이터 처리·검증](02_implementation-readiness/09_NCS_확장_데이터셋_처리_검증_결과.md)
4. [체크포인트 보완 결과](02_implementation-readiness/06_체크포인트_보완_기획서.md)

## 현재 기준

2026-07-23 기준 구현과 문서는 다음 상태를 전제로 합니다.

| 영역 | 현재 상태 |
| --- | --- |
| 사용자 흐름 | NCS 기반 강의 기본 선택 → 정보 입력 → 템플릿·교재 업로드 → 자동 생성 → 자연어 재생성 → 다운로드 |
| 이전 단계 조회 | 패키지 생성 후 강의 정보와 업로드 상태를 조회 전용으로 유지 |
| RAG | 프로젝트 업로드 자료 우선, 공통 baseline 보조, Supabase pgvector 의미 검색 |
| NCS 카탈로그 | 공식 능력단위 코드·명칭 전체 검색과 상세 수행준거 적재 상태 분리 |
| NCS 상세 백필 | 공식 API 연결 및 증분 동기화 구현, 수행준거 0개 항목은 `detail` 작업으로 단계적 보완 |
| LLMOps | LiteLLM, OpenAI primary, Gemini fallback, Langfuse trace |
| Export | DOCX, 기본 PPTX, 사용자 PPTX 템플릿과 레이아웃 매핑 |
| 배포 | Docker, GCE, GitHub Actions CI/CD |
| 자동 검증 | 백엔드 전체 테스트, 프론트엔드 lint·production build, RAG·LLM·배포 점검 스크립트 |

`수행준거 0개`는 공식 능력단위가 없다는 뜻이 아니라 상세 수행준거가 LessonPack RAG에 아직 적재되지 않았다는 뜻입니다. 카탈로그 동기화와 상세 RAG 동기화의 완료 여부를 따로 확인합니다.

## 디렉터리 구조

```text
docs/
├─ 00_project-brief/                 프로젝트 주제와 MVP 범위
├─ 01_kosena-service-planning/       KOSENA 서비스 기획 산출물 7종
├─ 02_implementation-readiness/      구현·데이터·RAG·NCS·배포 운영 문서
├─ 03_architecture/                  WBS·시퀀스·운영 배치 구조
├─ 04_validation/                    실제 검증 결과와 품질 기준
├─ 90_reference/                     원본 수업 자료와 참고 문서
└─ README.md                         현재 문서 인덱스
```

초기 Lovable 생성 프롬프트처럼 현재 코드와 계약이 다른 일회성 문서는 제거했습니다. 프론트엔드 실행·구조·환경변수는 별도 [lessonpack-ai 저장소](https://github.com/RyuGernwoo/lessonpack-ai)의 README에서 관리합니다.

## 문서별 상태

### 현재 운영 기준

| 문서 | 역할 |
| --- | --- |
| `02/01_구현명세서` | 현재 API와 서비스 구성의 기준 |
| `02/03_검증_프로토콜` | 자동·실증 검증 방법 |
| `02/05_GCE_Docker_CICD_배포_계획서` | 배포와 장애 대응 |
| `02/07_RAG_구축_연동_기획서` | 검색·영속화·fallback 계약 |
| `02/08_자연어_패키지_재생성_구현서` | 승인 없는 재생성·다운로드 흐름 |
| `02/11_NCS_전체_카탈로그_검색_구축` | 카탈로그와 상세 RAG의 구분 |
| `02/12_NCS_공식_API_RAG_자동_동기화_기획서` | 공식 API 백필·스케줄·검증 |
| `02/13_PPT_템플릿_기반_강의자료_생성_기획서` | 템플릿 저장·매핑·fallback |
| `03_architecture/01_WBS` | 전체 작업 분해·상태·의존관계 |
| `03_architecture/02_시퀀스_다이어그램` | 생성·재생성·다운로드·NCS 동기화 순서 |
| `03_architecture/03_배치_다이어그램` | 운영 노드·외부 연동·CI/CD 배치 |
| `04_validation/` | 특정 시점의 실행 결과와 후속 조치 |

### 기획 및 의사결정 기록

- `00_project-brief/`: 문제 정의와 MVP 범위
- `01_kosena-service-planning/`: 시장·고객·서비스·로드맵 산출물
- `02/02`, `02/04`: 데이터셋 선정과 전처리 계획
- `02/06`, `02/09`, `02/10`: 체크포인트와 NCS 확장 구현 과정
- `90_reference/`: KOSENA 수업 원본 참고 자료

기획 기록의 과거 수치와 일정은 당시 의사결정 근거이며, 최신 운영 수치로 해석하지 않습니다.

## 관리 원칙

- README에는 외부 사용자가 필요한 목적, 사용 순서와 최소 실행 방법만 둡니다.
- 상세 구현과 운영 절차는 `02_implementation-readiness/`에서 관리합니다.
- 검증 결과 문서는 실행 시각과 환경을 보존하며 과거 결과를 최신 결과처럼 덮어쓰지 않습니다.
- 원천 데이터, 전처리 산출물, export 파일과 비밀값은 Git에 포함하지 않습니다.
- 기능이나 외부 의존성이 바뀌면 코드, `.env.example`, migration, README와 관련 운영 문서를 함께 갱신합니다.
- 삭제 가능한 문서는 현재 코드·README·다른 문서에서 참조되지 않는 일회성 생성물로 제한합니다.
