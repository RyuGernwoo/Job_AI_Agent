# Job AI Agent

직업훈련 강의 운영 보조 AI Agent MVP 기획 저장소입니다.

이 프로젝트는 직업훈련 강사가 강의 준비 과정에서 반복적으로 작성하는 교안, 실습 과제, 평가 문항 초안을 AI로 생성하고, 사람이 검토한 뒤 문서 산출물로 저장하는 서비스를 목표로 합니다. 현재 저장소는 구현 착수 전 단계의 서비스 기획서, 구현명세서, 데이터셋 선정 계획서, 검증 프로토콜을 정리한 문서 중심 저장소입니다.

## 프로젝트 목표

- 1개월 안에 구현 가능한 MVP 범위를 정의합니다.
- 개인 프로젝트 수준에 맞게 서비스 범위를 좁힙니다.
- 실제 오픈소스와 상용 서비스 사례를 참고해 구현 방향을 정리합니다.
- RAG 기반 교안·실습·평가 생성, HITL 검토, DOCX 산출을 핵심 흐름으로 둡니다.

## 주요 기능 범위

MVP에서 다루는 핵심 기능은 다음과 같습니다.

- 커리큘럼과 NCS 기반 강의 목표 입력
- PDF/TXT 교재 업로드 및 chunk 처리
- Vector DB 기반 근거 검색
- 교안, 실습 과제, 평가 문항 초안 생성
- 사람이 검토하고 수정하는 승인 흐름
- 승인된 결과의 DOCX export
- Retrieval Gold Set과 Generation Gold Set 기반 검증

MVP에서 제외하는 범위는 LMS 연동, 자동 채점, 학습자 계정 관리, 대규모 기관 운영 기능입니다.

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
  90_reference/
    KOSENA_AI_서비스기획.md
```

## 핵심 문서

- [프로젝트 주제](docs/00_project-brief/00_프로젝트_주제.md)
- [MVP 통합 기획서](docs/00_project-brief/01_MVP_통합_기획서.md)
- [구현명세서](docs/02_implementation-readiness/01_구현명세서.md)
- [데이터셋 선정 계획서](docs/02_implementation-readiness/02_데이터셋_선정_계획서.md)
- [검증 프로토콜](docs/02_implementation-readiness/03_검증_프로토콜.md)

## KOSENA 산출물

- [01 산업·서비스 분석 보고서](docs/01_kosena-service-planning/01_산업_서비스_분석_보고서.md)
- [02 Lean Canvas](docs/01_kosena-service-planning/02_Lean_Canvas.md)
- [03 고객 리서치 패키지](docs/01_kosena-service-planning/03_고객_리서치_패키지.md)
- [04 시장·경쟁사 분석](docs/01_kosena-service-planning/04_시장_경쟁사_분석.md)
- [05 서비스 컨셉·기능 정의서](docs/01_kosena-service-planning/05_서비스_컨셉_기능_정의서.md)
- [06 개발 로드맵·PRD](docs/01_kosena-service-planning/06_개발_로드맵_PRD.md)
- [07 최종 발표자료](docs/01_kosena-service-planning/07_최종_발표자료.md)

## 구현 방향

구현 후보 플랫폼은 다음을 기준으로 정리했습니다.

- API 서버: FastAPI
- UI: Streamlit 또는 FastAPI Swagger UI
- Vector DB: Chroma
- 문서 파싱: pypdf, python-docx, python-pptx
- 구조화 검증: Pydantic
- 평가: RAGAS 지표, 자체 Gold Set, 사람 평가 루브릭

## 현재 상태

- 서비스 기획 문서 작성 완료
- KOSENA 산출물 7종 작성 완료
- 구현명세서, 데이터셋 선정 계획서, 검증 프로토콜 작성 완료
- 실제 애플리케이션 코드는 아직 작성 전 단계

## 작성자

- Name: RyuGernwoo
- Email: qesadgun@gmail.com
