# LessonPack AI 문서 안내

이 디렉터리는 LessonPack AI의 기획, 구현, 검증, 배포 문서를 역할별로 정리한 공간입니다.

## 먼저 읽을 문서

### 일반 사용자 관점

서비스가 무엇을 하는지 빠르게 이해하려면 다음 순서로 읽습니다.

1. [README](../README.md)
2. [MVP 통합 기획서](00_project-brief/01_MVP_통합_기획서.md)
3. [서비스 컨셉·기능 정의서](01_kosena-service-planning/05_서비스_컨셉_기능_정의서.md)
4. [최종 발표자료](01_kosena-service-planning/07_최종_발표자료.md)

### 외부 개발자 관점

설치, 실행, 데이터셋, 배포 구조를 이해하려면 다음 순서로 읽습니다.

1. [구현명세서](02_implementation-readiness/01_구현명세서.md)
2. [데이터셋 운영 문서](../data/README_DATASET.md)
3. [RAG 구축 및 연동 기획서](02_implementation-readiness/07_RAG_구축_연동_기획서.md)
4. [검증 프로토콜](02_implementation-readiness/03_검증_프로토콜.md)
5. [GCE Docker CI/CD 배포 계획서](02_implementation-readiness/05_GCE_Docker_CICD_배포_계획서.md)
6. [체크포인트 보완 기획서](02_implementation-readiness/06_체크포인트_보완_기획서.md)

## 문서 구조

```text
docs/
  00_project-brief/
    00_프로젝트_주제.md
    01_MVP_통합_기획서.md
  01_kosena-service-planning/
    01_산업_서비스_분석_보고서.md
    02_Lean_Canvas.md
    03_고객_리서치_패키지.md
    04_시장_경쟁사_분석.md
    05_서비스_컨셉_기능_정의서.md
    06_개발_로드맵_PRD.md
    07_최종_발표자료.md
  02_implementation-readiness/
    01_구현명세서.md
    02_데이터셋_선정_계획서.md
    03_검증_프로토콜.md
    04_데이터셋_활용_전처리_계획서.md
    05_GCE_Docker_CICD_배포_계획서.md
    06_체크포인트_보완_기획서.md
    07_RAG_구축_연동_기획서.md
  03_ui-lovable/
    01_Lovable_UI_생성_프롬프트.md
  90_reference/
    KOSENA_AI_서비스기획.md
```

## 현재 구현 기준

2026-07-21 기준 문서는 다음 구현 상태를 기준으로 정리되어 있습니다.

| 영역 | 상태 |
| --- | --- |
| API | FastAPI MVP 구현 |
| UI | Streamlit 데모 UI 구현 |
| 데이터셋 | 6개 선별 원천, 43개 chunk, retrieval gold 10개, generation gold 3개 |
| Vector Store | Supabase Postgres + pgvector, 프로젝트·retrieval/generation run 영속화 migration 구현 |
| LLMOps | LiteLLM, OpenAI primary, Gemini fallback, Langfuse tracing 적용 |
| Export | DOCX/PPTX export 구현 |
| 배포 | Docker, GCE, GitHub Actions CI/CD 적용 및 실배포 확인 |
| 검증 | unittest, 서버 주도 RAG API 테스트, retrieval/generation 평가, readiness script 구성 |
| 품질 보완 | 실제 DOCX/PPTX 테스트 산출물 분석 기반 보완 계획 추가 |

## 문서별 역할

| 문서 | 역할 |
| --- | --- |
| `00_project-brief/` | 프로젝트 주제, MVP 범위, 핵심 흐름 정리 |
| `01_kosena-service-planning/` | KOSENA 서비스 기획 산출물 7종 |
| `02_implementation-readiness/` | 구현, 데이터셋, 검증, 배포 준비 문서 |
| `03_ui-lovable/` | Lovable UI 생성 및 외부 배포 UI 연동 문서 |
| `90_reference/` | 원본 수업 자료와 참고 문서 |

## 갱신 원칙

- README는 외부 사용자가 빠르게 이해할 수 있도록 간결하게 유지합니다.
- 상세 기술 설명은 `02_implementation-readiness/` 문서에 둡니다.
- 원천 데이터와 생성 산출물은 Git에 포함하지 않고, 재현 명령과 검증 결과를 문서화합니다.
- 새로운 배포 방식이나 외부 의존성을 추가하면 `.env.example`, `config.example.yaml`, 관련 문서를 함께 갱신합니다.
