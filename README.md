# LessonPack AI

직업훈련 강사가 교안, 실습 과제, 평가 문항을 빠르게 만들고 DOCX/PPTX로 내려받을 수 있도록 돕는 AI 서비스 MVP입니다.

LessonPack AI는 교재와 NCS 근거를 바탕으로 강의 패키지를 생성합니다. 사용자는 자연어로 수정할 내용을 입력해 새 버전을 만들거나, 생성 직후 파일을 내려받을 수 있습니다.

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
- 생성 결과의 난이도, 표현, 실습 구성을 자연어로 조정하고 싶을 때

### 사용 흐름

1. 과정명, 차시명, 학습 대상, 학습목표, NCS 능력단위를 입력합니다.
2. 수업에 사용할 교재 파일이나 텍스트 자료를 업로드합니다.
3. 서비스가 관련 근거 문단을 검색합니다.
4. 검색 근거를 바탕으로 교안, 실습, 평가 초안을 생성합니다.
5. 필요한 경우 자연어로 수정 사항을 입력해 새 패키지를 생성합니다.
6. 생성된 강의 패키지를 DOCX 또는 PPTX로 내려받습니다.

### 사용자가 준비할 것

- 강의 과정명과 차시명
- 학습자 수준 또는 선수 지식
- 학습목표
- 관련 NCS 능력단위 또는 핵심 수행 내용
- 수업 근거로 사용할 교재, Markdown, TXT, PDF 자료

배포된 서비스 주소는 운영자가 별도로 공유합니다. 일반 사용자는 API key, Supabase, Langfuse 같은 개발 설정을 직접 다루지 않아도 됩니다.

## 외부 개발자를 위한 안내

### 현재 구현 상태

2026-07-21 기준 MVP의 핵심 end-to-end 흐름은 구현되어 있습니다.

- FastAPI API 서버
- Lovable 기반 웹 UI 연동
- 프로젝트 생성, 자료 업로드, chunking, 검색, 생성, 자연어 재생성, export API
- NCS 연계와 마지막 단원에 통합된 근거 출처가 포함된 DOCX/PPTX 산출물 생성
- 수업 제목 기반의 짧은 다운로드 파일명과 구조화 LLM JSON 검증·fallback 처리
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
| UI | Lovable (React + TypeScript) |
| LLMOps | LiteLLM, OpenAI API, Gemini API, Langfuse |
| Vector Store | Supabase Postgres + pgvector |
| Export | python-docx, python-pptx |
| 배포 | Docker, Docker Compose, GCE, GitHub Actions, GHCR |
| 테스트 | pytest/unittest, 자체 retrieval/generation 검증 스크립트 |

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

운영 UI는 Lovable 배포 페이지에서 이용합니다. UI 연동 계약과 환경 변수는 [Lovable UI 연동 문서](docs/03_ui-lovable/01_Lovable_UI_생성_프롬프트.md)를 참고합니다.

### Docker 실행

```powershell
Copy-Item .env.example .env
# .env에 필요한 값을 입력합니다.
docker compose up -d --build
python scripts\check_deployment.py http://localhost:8000
docker compose down
```

### Lovable UI 연동

Lovable 배포 UI는 다음 주소를 기준으로 준비되어 있습니다.

```text
https://lessonpack-ai.lovable.app/
```

브라우저 보안 정책상 HTTPS 페이지에서 `http://34.47.92.210:8000` API를 직접 호출하면 mixed content로 차단될 수 있습니다. 실제 외부 UI 연동에는 HTTPS API 주소가 필요합니다.

백엔드는 Lovable 도메인을 CORS 허용 origin에 포함합니다.

```powershell
LESSONPACK_CORS_ALLOW_ORIGINS=https://7f62cef5-bc4c-473e-a8d2-5f1847df5736.lovableproject.com,https://id-preview--7f62cef5-bc4c-473e-a8d2-5f1847df5736.lovable.app,https://lessonpack-ai.lovable.app
LESSONPACK_CORS_ALLOW_CREDENTIALS=false
```

GCE 배포에서 HTTPS reverse proxy를 함께 올리려면 GitHub Secret에 `LESSONPACK_PUBLIC_API_HOST`를 등록합니다. 이 값은 raw IP가 아니라 인증서 발급 가능한 도메인이어야 합니다. 예: `api.example.com` 또는 GCE IP를 가리키는 `sslip.io`/`nip.io` 계열 테스트 도메인.

Lovable 프론트의 `VITE_API_BASE_URL`은 최종 HTTPS API 주소로 설정해야 합니다.
### 데이터셋 준비와 Supabase 적재

원천 데이터는 `data/raw/`에 로컬로 보관하며 Git에 포함하지 않습니다. MVP 검증에 필요한 작은 gold set만 `data/gold/`에 포함합니다.

```powershell
python scripts\prepare_mvp_dataset.py
python scripts\validate_mvp_dataset.py
python scripts\ingest_processed_dataset.py --query "Python 함수 return" --top-k 3
python scripts\check_rag_readiness.py --check-schema --query "Python 함수 return" --top-k 3
```

현재 MVP 데이터셋은 6개 원천 자료에서 생성한 43개 chunk를 사용합니다. Supabase에는 `002_rag_persistence.sql` 적용 후 LiteLLM을 통한 `text-embedding-3-small` 1536차원 벡터가 `embedding_v2`에 재적재되어 있습니다. 데이터셋을 변경하면 적재 명령을 다시 실행해 semantic 벡터를 갱신합니다. 운영 API는 신규 프로젝트 자료와 `mvp-dataset` 근거를 함께 검색하며, 검색 실행 ID를 생성 로그와 연결합니다.

자세한 내용은 [데이터셋 운영 문서](data/README_DATASET.md)를 참고하십시오.

### 검증

```powershell
python -m compileall src scripts tests
python -m pytest -q
python scripts\check_llm_provider.py --config config.example.yaml
python scripts\run_mvp_demo.py --provider mock --output-dir outputs\demo
python scripts\run_mvp_verification.py --output-dir outputs\eval --demo-case-id g003
python scripts\inspect_export_quality.py --docx outputs\demo\g003_lesson_package.docx --pptx outputs\demo\g003_lesson_package.pptx
```

실제 LLM, Langfuse, Supabase까지 포함한 검증은 `.env`에 운영 key를 설정한 뒤 수행합니다.

### 주요 API

| Method | Endpoint | 설명 |
| --- | --- | --- |
| GET | `/health` | 서비스 상태 확인 |
| GET | `/health/rag` | RAG 저장소·검색 설정 확인 |
| POST | `/api/projects` | 과정/차시 프로젝트 생성 |
| POST | `/api/projects/{project_id}/materials` | 교재 업로드 및 chunk 생성 |
| POST | `/api/projects/{project_id}/rag/retrieve` | 서버 주도 프로젝트·baseline 근거 검색 |
| POST | `/api/projects/{project_id}/rag/generate` | 검색과 생성이 연결된 강의 패키지 생성 |
| POST | `/api/packages/{package_id}/regenerate` | 기존 패키지와 자연어 지시를 기반으로 새 패키지 생성 |
| GET | `/api/retrieval-runs/{run_id}` | 검색 질의·점수·선택 근거 조회 |
| POST | `/api/projects/{project_id}/retrieve` | 호환용 프로젝트 근거 검색 |
| POST | `/api/projects/{project_id}/generate` | 호환용 chunk 직접 전달 생성 |
| GET | `/api/packages/{package_id}/export.docx` | DOCX 다운로드 |
| GET | `/api/packages/{package_id}/export.pptx` | PPTX 다운로드 |
| GET | `/api/packages/{package_id}/generation-log` | 생성 로그 조회 |

### 문서

- [문서 안내](docs/README.md)
- [MVP 통합 기획서](docs/00_project-brief/01_MVP_통합_기획서.md)
- [구현명세서](docs/02_implementation-readiness/01_구현명세서.md)
- [데이터셋 운영 문서](data/README_DATASET.md)
- [RAG 구축 및 연동 기획서](docs/02_implementation-readiness/07_RAG_구축_연동_기획서.md)
- [자연어 패키지 재생성 구현서](docs/02_implementation-readiness/08_자연어_패키지_재생성_구현서.md)
- [검증 프로토콜](docs/02_implementation-readiness/03_검증_프로토콜.md)
- [GCE Docker CI/CD 배포 계획서](docs/02_implementation-readiness/05_GCE_Docker_CICD_배포_계획서.md)

### 보안 주의

`.env`에는 실제 API key와 service role key가 들어갑니다. 이 파일은 Git에 커밋하지 않습니다. Supabase `SERVICE_ROLE_KEY`는 서버 전용 key이며 브라우저, 프론트엔드, 공개 로그에 노출하면 안 됩니다.

## 작성자

- Name: RyuGernwoo
- Email: qesadgun@gmail.com
