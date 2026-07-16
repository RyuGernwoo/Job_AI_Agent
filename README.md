# LessonPack AI

직업훈련 강의 패키지 생성 보조 AI Agent MVP 저장소입니다.

이 프로젝트는 직업훈련 강사가 강의 준비 과정에서 반복적으로 작성하는 교안, 실습 과제, 평가 문항 초안을 AI로 생성하고, 사람이 검토한 뒤 문서 산출물로 저장하는 서비스를 목표로 합니다. 현재 저장소는 기획 문서와 1단계 FastAPI 구현 골격을 함께 포함합니다.

## 프로젝트 목표

- 1개월 안에 구현 가능한 MVP 범위를 유지합니다.
- 개인 프로젝트 수준에 맞게 기능을 좁혀 end-to-end 흐름을 먼저 만듭니다.
- RAG 기반 교안·실습·평가 생성, HITL 검토, DOCX 산출을 핵심 흐름으로 둡니다.
- 실제 구현은 mock provider와 검증 가능한 schema부터 시작합니다.

## 현재 구현 상태

2026-07-16 기준 구현된 범위는 다음과 같습니다.

- FastAPI 앱 skeleton
- `GET /health`
- `POST /api/projects`
- `POST /api/projects/{project_id}/materials`
- `POST /api/projects/{project_id}/retrieve`
- `POST /api/projects/{project_id}/generate`
- `GET /api/packages/{package_id}`
- `GET /api/packages/{package_id}/generation-log`
- `PATCH /api/packages/{package_id}/review`
- `GET /api/packages/{package_id}/export.docx`
- Pydantic 기반 Project, MaterialChunk, LessonPackage schema
- TXT/MD/PDF 업로드 텍스트 추출 및 chunk 생성
- 업로드된 chunk 대상 metadata-aware keyword retrieval
- Chroma 확장을 위한 VectorStore 경계
- Chroma PersistentClient 런타임 검증
- mock LLM provider 기반 교안·실습·평가 패키지 생성
- `draft -> reviewed -> approved` 검토 상태 전환
- approved 패키지 DOCX export endpoint
- generation log 조회 endpoint
- `config.example.yaml` 기반 명시 설정 로더
- `http_chat` 외부 LLM provider adapter
- `scripts/prepare_mvp_dataset.py` 기반 MVP 데이터셋 준비 자동화
- `data/processed/chunks.jsonl` 로더
- processed dataset VectorStore ingest 스크립트
- retrieval Gold Set 기반 검색 품질 평가 스크립트
- generation Gold Set 기반 생성 품질 평가 스크립트
- 합성 Gold Set과 사람 평가 루브릭 초안
- Streamlit 데모 UI
- `unittest` 기반 회귀 테스트

아직 구현하지 않은 범위는 실제 API 키 기반 LLM 실증, RAGAS 평가 자동화, PPTX export입니다.

## 실행 방법

Python 3.11 이상을 기준으로 합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
$env:PYTHONPATH="src"

# 권장: config.example.yaml을 config.yaml로 복사한 뒤 명시 설정으로 실행합니다.
Copy-Item config.example.yaml config.yaml
$env:LESSONPACK_CONFIG="config.yaml"

# http_chat provider 사용 시 config.yaml의 llm.api_key_env에 맞춰 API key를 설정합니다.
# $env:LESSONPACK_HTTP_API_KEY="..."

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

## 데이터셋 준비

원천 데이터는 `data/raw/` 아래의 로컬 파일로 관리하며 Git에 포함하지 않습니다. 작은 합성 검증 데이터인 `data/gold/`만 커밋 대상으로 둡니다.

MVP 데이터셋 산출물은 다음 명령으로 재생성합니다.

```powershell
python scripts\prepare_mvp_dataset.py
```

현재 스크립트는 선별된 Python 문서, pandas 10분 튜토리얼, NCS 응용SW엔지니어링 학습모듈 MD를 입력으로 사용해 다음을 생성합니다.

- `data/raw/curriculum/curriculum_python_prompt_automation.yaml`
- `data/raw/ncs/ncs_application_sw_programming.yaml`
- `data/raw/synthetic/practice_examples.yaml`
- `data/processed/chunks.jsonl`
- `data/processed/chunk_index.csv`
- `data/processed/selected_sources.yaml`
- `data/processed/source_file_map.csv`
- `data/processed/dataset_manifest.json`
- `data/gold/retrieval_gold.jsonl`
- `data/gold/generation_gold.yaml`
- `data/gold/human_eval_rubric.yaml`

전처리 산출물 구조와 Gold Set 참조 무결성은 다음 명령으로 검증합니다.

```powershell
python scripts\validate_mvp_dataset.py
```

리포트 파일이 필요하면 다음처럼 실행합니다.

```powershell
python scripts\validate_mvp_dataset.py --report outputs\eval\dataset_validation_report.json
```

데이터셋 디렉터리별 역할과 Git 추적 정책은 [데이터셋 운영 문서](data/README_DATASET.md)를 참고합니다.

전처리된 chunk를 현재 VectorStore 경계에 적재하고 검색 스모크 테스트를 수행하려면 다음 명령을 실행합니다.

```powershell
python scripts\ingest_processed_dataset.py --query "Python 함수 return" --top-k 3
```

retrieval Gold Set 기준 검색 품질은 다음 명령으로 평가합니다.

```powershell
python scripts\evaluate_retrieval.py --top-k 3 --min-hit-rate 1.0 --report outputs\eval\retrieval_report.json
```

`--min-hit-rate`를 지정하면 기준 미달 시 종료 코드 `1`로 실패 처리할 수 있습니다.
현재 MVP Gold Set 기준 baseline은 top-3 hit rate `1.0`입니다.

generation Gold Set 기준 생성 품질은 다음 명령으로 평가합니다.

```powershell
python scripts\evaluate_generation.py --min-case-pass-rate 1.0 --report outputs\eval\generation_report.json
```

현재 mock provider 기준 baseline은 case pass rate `1.0`입니다.

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
  90_reference/
    KOSENA_AI_서비스기획.md
```

## 핵심 문서

- [프로젝트 주제](docs/00_project-brief/00_프로젝트_주제.md)
- [MVP 통합 기획서](docs/00_project-brief/01_MVP_통합_기획서.md)
- [구현명세서](docs/02_implementation-readiness/01_구현명세서.md)
- [데이터셋 선정 계획서](docs/02_implementation-readiness/02_데이터셋_선정_계획서.md)
- [검증 프로토콜](docs/02_implementation-readiness/03_검증_프로토콜.md)
- [데이터셋 활용 및 전처리 계획서](docs/02_implementation-readiness/04_데이터셋_활용_전처리_계획서.md)

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
- 문서 처리: PyMuPDF 기반 PDF 추출, python-docx DOCX 산출, python-pptx는 추후 적용
- Vector DB: InMemory 기본값, Chroma PersistentClient adapter 검증 완료
- 검색: 본문, source metadata, section, tags, 한국어/영어 개념 동의어 기반 keyword scoring
- LLM: provider adapter 경계, mock provider, `http_chat` provider, generation log 우선
- UI: Swagger UI 우선, 이후 Streamlit 확장
- 평가: 자체 Gold Set, retrieval hit rate, generation case pass rate, 사람 평가 루브릭 우선, 이후 RAGAS 검토

## 작성자

- Name: RyuGernwoo
- Email: qesadgun@gmail.com
