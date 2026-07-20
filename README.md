# LessonPack AI

직업훈련 강사가 교안, 실습 과제, 평가 문항 초안을 빠르게 만들고 검수한 뒤 DOCX/PPTX로 내려받을 수 있도록 돕는 AI 서비스 MVP입니다.

LessonPack AI는 강사를 대체하는 서비스가 아닙니다. 교재와 NCS 근거를 바탕으로 “검수 가능한 초안”을 만들고, 최종 판단과 수정은 강사가 수행하는 흐름을 전제로 합니다.

## 일반 사용자를 위한 안내

### 어떤 서비스인가요?

LessonPack AI는 직업훈련 강의 준비에 필요한 산출물을 한 번에 묶어 생성합니다.

- 강의 교안 초안
- 실습 시나리오와 수행 절차
- 객관식 평가 문항
- 실습형 평가 과제와 루브릭
- 생성 근거가 된 교재/NCS 출처
- 최종 DOCX/PPTX 산출물

### 언제 쓰면 좋은가요?

- 새 차시의 강의안을 빠르게 초안화해야 할 때
- 교재 내용과 NCS 능력단위를 함께 반영해야 할 때
- 실습과 평가 문항을 같은 수업 목표에 맞춰 구성해야 할 때
- AI가 만든 결과를 바로 쓰기보다, 강사가 검수할 초안이 필요할 때

### 사용 흐름

1. 과정명, 차시명, 학습 대상, 학습목표, NCS 능력단위를 입력합니다.
2. 수업에 사용할 교재 파일이나 텍스트 자료를 업로드합니다.
3. 서비스가 관련 근거 문단을 검색합니다.
4. 검색 근거를 바탕으로 교안, 실습, 평가 초안을 생성합니다.
5. 강사가 내용을 검토하고 수정한 뒤 승인합니다.
6. 승인된 강의 패키지를 DOCX 또는 PPTX로 내려받습니다.

### 사용자가 준비할 것

- 강의 과정명과 차시명
- 학습자 수준 또는 선수 지식
- 학습목표
- 관련 NCS 능력단위 또는 핵심 수행 내용
- 수업 근거로 사용할 교재, Markdown, TXT, PDF 자료

배포된 서비스 주소는 운영자가 별도로 공유합니다. 일반 사용자는 API key, Supabase, Langfuse 같은 개발 설정을 직접 다루지 않아도 됩니다.

## 외부 개발자를 위한 안내

### 현재 구현 상태

2026-07-20 기준 MVP의 핵심 end-to-end 흐름은 구현되어 있습니다.

- FastAPI API 서버
- Streamlit 데모 UI
- 프로젝트 생성, 자료 업로드, chunking, 검색, 생성, 검수, export API
- DOCX/PPTX 산출물 생성
- LiteLLM 기반 LLM provider
- OpenAI primary 모델과 Gemini fallback 모델 설정
- Langfuse tracing 연동
- Supabase Postgres + pgvector vector store
- GCE Docker 배포 및 GitHub Actions CI/CD
- MVP 데이터셋 43개 chunk와 retrieval/generation gold set
- unittest 기반 회귀 테스트와 MVP 검증 스크립트

### 기술 구성

세부 구현은 문서와 코드에 분리되어 있습니다. README에서는 전체 구조만 요약합니다.

| 영역 | 사용 기술 |
| --- | --- |
| API | FastAPI, Pydantic |
| UI | Streamlit |
| LLMOps | LiteLLM, OpenAI API, Gemini API, Langfuse |
| Vector Store | Supabase Postgres + pgvector |
| Export | python-docx, python-pptx |
| 배포 | Docker, Docker Compose, GCE, GitHub Actions, GHCR |
| 테스트 | unittest, 자체 retrieval/generation 검증 스크립트 |

### 로컬 실행

Python 3.11 이상을 기준으로 합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements-dev.txt
$env:PYTHONPATH="src"

Copy-Item .env.example .env
Copy-Item config.example.yaml config.yaml
```

로컬에서 실제 API를 쓰지 않고 기능 흐름만 확인하려면 `config.yaml`의 `llm.provider`를 `mock`으로 바꿉니다. 실제 LLM 실증은 `.env`에 `OPENAI_API_KEY`, `GEMINI_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`를 설정한 뒤 실행합니다.

FastAPI 서버:

```powershell
python -m uvicorn lectureops_agent.app.main:app --reload
```

Swagger UI:

```text
http://127.0.0.1:8000/docs
```

Streamlit UI:

```powershell
python -m streamlit run src/lectureops_agent/ui/streamlit_app.py --server.port 8501
```

### Docker 실행

```powershell
Copy-Item .env.example .env
# .env에 필요한 값을 입력합니다.
docker compose up -d --build
python scripts\check_deployment.py http://localhost:8000
docker compose down
```

### 데이터셋 준비와 Supabase 적재

원천 데이터는 `data/raw/`에 로컬로 보관하며 Git에 포함하지 않습니다. MVP 검증에 필요한 작은 gold set만 `data/gold/`에 포함합니다.

```powershell
python scripts\prepare_mvp_dataset.py
python scripts\validate_mvp_dataset.py
python scripts\ingest_processed_dataset.py --query "Python 함수 return" --top-k 3
```

현재 MVP 데이터셋은 6개 원천 자료에서 생성한 43개 chunk를 사용합니다. Supabase 적재 전에는 `supabase/migrations/001_lessonpack_vectors.sql`을 Supabase SQL Editor에서 먼저 실행해야 합니다.

자세한 내용은 [데이터셋 운영 문서](data/README_DATASET.md)를 참고하십시오.

### 검증

```powershell
python -m compileall src scripts tests
python -m unittest discover -s tests
python scripts\check_llm_provider.py --config config.example.yaml
python scripts\run_mvp_verification.py --output-dir outputs\eval --demo-case-id g003
```

실제 LLM, Langfuse, Supabase까지 포함한 검증은 `.env`에 운영 key를 설정한 뒤 수행합니다.

### 주요 API

| Method | Endpoint | 설명 |
| --- | --- | --- |
| GET | `/health` | 서비스 상태 확인 |
| POST | `/api/projects` | 과정/차시 프로젝트 생성 |
| POST | `/api/projects/{project_id}/materials` | 교재 업로드 및 chunk 생성 |
| POST | `/api/projects/{project_id}/retrieve` | 근거 chunk 검색 |
| POST | `/api/projects/{project_id}/generate` | 강의 패키지 생성 |
| PATCH | `/api/packages/{package_id}/review` | 검수 상태 변경 |
| GET | `/api/packages/{package_id}/export.docx` | DOCX 다운로드 |
| GET | `/api/packages/{package_id}/export.pptx` | PPTX 다운로드 |
| GET | `/api/packages/{package_id}/generation-log` | 생성 로그 조회 |

### 문서

- [문서 안내](docs/README.md)
- [MVP 통합 기획서](docs/00_project-brief/01_MVP_통합_기획서.md)
- [구현명세서](docs/02_implementation-readiness/01_구현명세서.md)
- [데이터셋 운영 문서](data/README_DATASET.md)
- [검증 프로토콜](docs/02_implementation-readiness/03_검증_프로토콜.md)
- [GCE Docker CI/CD 배포 계획서](docs/02_implementation-readiness/05_GCE_Docker_CICD_배포_계획서.md)

### 보안 주의

`.env`에는 실제 API key와 service role key가 들어갑니다. 이 파일은 Git에 커밋하지 않습니다. Supabase `SERVICE_ROLE_KEY`는 서버 전용 key이며 브라우저, 프론트엔드, 공개 로그에 노출하면 안 됩니다.

## 작성자

- Name: RyuGernwoo
- Email: qesadgun@gmail.com
