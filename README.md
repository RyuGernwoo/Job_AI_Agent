# Job AI Agent

직업훈련 강의 운영 보조 AI Agent MVP 저장소입니다.

이 프로젝트는 직업훈련 강사가 강의 준비 과정에서 반복적으로 작성하는 교안, 실습 과제, 평가 문항 초안을 AI로 생성하고, 사람이 검토한 뒤 문서 산출물로 저장하는 서비스를 목표로 합니다. 현재 저장소는 기획 문서와 1단계 FastAPI 구현 골격을 함께 포함합니다.

## 프로젝트 목표

- 1개월 안에 구현 가능한 MVP 범위를 유지합니다.
- 개인 프로젝트 수준에 맞게 기능을 좁혀 end-to-end 흐름을 먼저 만듭니다.
- RAG 기반 교안·실습·평가 생성, HITL 검토, DOCX 산출을 핵심 흐름으로 둡니다.
- 실제 구현은 mock provider와 검증 가능한 schema부터 시작합니다.

## 현재 구현 상태

2026-07-07 기준 구현된 범위는 다음과 같습니다.

- FastAPI 앱 skeleton
- `GET /health`
- `POST /api/projects`
- `POST /api/projects/{project_id}/materials`
- `POST /api/projects/{project_id}/retrieve`
- `POST /api/projects/{project_id}/generate`
- `GET /api/packages/{package_id}`
- `PATCH /api/packages/{package_id}/review`
- `GET /api/packages/{package_id}/export.docx`
- Pydantic 기반 Project, MaterialChunk, LessonPackage schema
- TXT/MD/PDF 업로드 텍스트 추출 및 chunk 생성
- 업로드된 chunk 대상 in-memory keyword retrieval
- Chroma 확장을 위한 VectorStore 경계
- mock generation service 기반 교안·실습·평가 패키지 생성
- `draft -> reviewed -> approved` 검토 상태 전환
- approved 패키지 DOCX export endpoint
- Streamlit 데모 UI
- `unittest` 기반 회귀 테스트

아직 구현하지 않은 범위는 실제 Chroma 런타임 검증, 실제 LLM provider, RAGAS 평가 자동화입니다.

## 실행 방법

Python 3.11 이상을 기준으로 합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
$env:PYTHONPATH="src"
python -m uvicorn lectureops_agent.app.main:app --reload
python -m streamlit run src/lectureops_agent/ui/streamlit_app.py --server.port 8501
```

서버 실행 후 다음 주소에서 Swagger UI를 확인합니다.

```text
http://127.0.0.1:8000/docs
```

## 테스트 방법

현재 테스트는 추가 설치 없이 표준 라이브러리 `unittest`로 실행합니다.

```powershell
python -m unittest discover -s tests
```

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

- API 서버: FastAPI
- 구조화 검증: Pydantic
- 문서 처리: pypdf, python-docx, python-pptx 순차 적용 예정
- Vector DB: Chroma 적용 예정
- UI: Swagger UI 우선, 이후 Streamlit 확장
- 평가: 자체 Gold Set과 사람 평가 루브릭 우선, 이후 RAGAS 검토

## 작성자

- Name: RyuGernwoo
- Email: qesadgun@gmail.com







