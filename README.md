# LessonPack AI

직업훈련 강의 패키지 생성 보조 AI Agent MVP 저장소입니다.

이 프로젝트는 직업훈련 강사가 강의 준비 과정에서 반복적으로 작성하는 교안, 실습 과제, 평가 문항 초안을 AI로 생성하고, 사람이 검토한 뒤 문서 산출물로 저장하는 서비스를 목표로 합니다. 현재 저장소는 기획 문서와 FastAPI 기반 MVP 구현을 함께 포함합니다.

## 프로젝트 목표

- 1개월 안에 구현 가능한 MVP 범위를 유지합니다.
- 개인 프로젝트 수준에 맞게 기능을 좁혀 end-to-end 흐름을 먼저 만듭니다.
- RAG 기반 교안·실습·평가 생성, HITL 검토, DOCX/PPTX 산출을 핵심 흐름으로 둡니다.
- Mock provider로 테스트 가능성을 유지하고, LiteLLM으로 실제 모델 실증을 분리합니다.

## 현재 구현 상태

2026-07-20 기준 구현된 범위는 다음과 같습니다.

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
- `GET /api/packages/{package_id}/export.pptx`
- Pydantic 기반 Project, MaterialChunk, LessonPackage schema
- TXT/MD/PDF 업로드 텍스트 추출 및 chunk 생성
- 업로드된 chunk 대상 metadata-aware keyword retrieval
- Supabase(pgvector) 확장을 위한 VectorStore 경계
- Supabase RPC 기반 VectorStore adapter 검증
- mock LLM provider 기반 교안·실습·평가 패키지 생성
- `draft -> reviewed -> approved` 검토 상태 전환
- approved 패키지 DOCX/PPTX export endpoint
- generation log 조회 endpoint
- `config.example.yaml` 및 `config.yaml` 기반 명시 설정 로더
- `http_chat` 외부 LLM provider adapter
- LiteLLM provider adapter
- OpenAI primary + Gemini fallback 모델 라우팅 설정
- Langfuse OTEL callback 연동 설정
- `.env.example` 기반 로컬 비밀값 주입 구조
- `scripts/prepare_mvp_dataset.py` 기반 MVP 데이터셋 준비 자동화
- `data/processed/chunks.jsonl` 로더
- processed dataset VectorStore ingest 스크립트
- retrieval Gold Set 기반 검색 품질 평가 스크립트와 ID 기반 context precision/recall
- generation Gold Set 기반 생성 품질 평가 스크립트와 citation coverage
- LLM provider readiness check와 실제 provider 평가 게이트
- MVP end-to-end 데모 실행 스크립트와 DOCX/PPTX 산출물 생성
- MVP 검증 프로토콜 JSON/Markdown 리포트 생성 스크립트
- 합성 Gold Set과 사람 평가 루브릭 초안
- Streamlit 데모 UI
- `unittest` 기반 회귀 테스트

아직 구현하지 않은 범위는 실제 API 키 기반 장시간 품질 실증, LiteLLM Proxy/팀별 예산 관리, RAGAS 평가 자동화입니다.

## 실행 방법

Python 3.11 이상을 기준으로 합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
$env:PYTHONPATH="src"

# 권장: 로컬 설정 파일을 복사한 뒤 .env를 기준으로 실행합니다.
Copy-Item .env.example .env
Copy-Item config.example.yaml config.yaml

# 실제 LLMOps 실증 시 .env에 OPENAI_API_KEY, GEMINI_API_KEY,
# LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY를 채웁니다.
# config.yaml 기본값은 llm.provider=litellm, primary=gpt-4o-mini,
# fallback=gemini/gemini-2.0-flash, callback=langfuse_otel입니다.

python -m uvicorn lectureops_agent.app.main:app --reload
python -m streamlit run src/lectureops_agent/ui/streamlit_app.py --server.port 8501
```

서버 실행 후 다음 주소에서 Swagger UI를 확인합니다.

```text
http://127.0.0.1:8000/docs
```

## LLMOps 설정

기본 운영 경로는 LiteLLM SDK입니다. `LESSONPACK_CONFIG=config.yaml`이 설정되어 있으면 `config.yaml`의 `llm.provider`가 우선 적용됩니다.

```yaml
llm:
  provider: litellm
  model: gpt-4o-mini
  fallback_models:
    - gemini/gemini-2.0-flash
  timeout_seconds: 30
  callbacks:
    - langfuse_otel
```

`.env`에는 실제 키만 로컬로 입력합니다. `.env.example`은 placeholder만 포함하며 Git에 커밋하지 않는 `.env`를 만드는 기준 파일입니다.

```powershell
OPENAI_API_KEY=...
GEMINI_API_KEY=...
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
LANGFUSE_OTEL_HOST=https://jp.cloud.langfuse.com
LANGFUSE_BASE_URL=https://jp.cloud.langfuse.com
```

- OpenAI primary 모델은 `OPENAI_API_KEY`를 사용합니다.
- Gemini fallback은 Google AI Studio API key를 `GEMINI_API_KEY`로 주입하고, LiteLLM 모델명에는 `gemini/` prefix를 사용합니다.
- Langfuse는 `callbacks: [langfuse_otel]`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_OTEL_HOST`로 tracing을 활성화합니다. 이 프로젝트는 JP 리전 기준으로 `https://jp.cloud.langfuse.com`을 사용합니다.
- 로컬 오프라인 개발이 필요하면 `config.yaml`에서 `llm.provider: mock`, `model: lessonpack-mock`, `fallback_models: []`, `callbacks: []`로 잠시 바꿉니다.

## Supabase Vector Store 설정

운영형 영속 저장소는 Supabase Postgres + pgvector를 사용합니다. 로컬 단위 테스트는 `memory` provider로 유지하고, 실제 배포 또는 실증에서는 `config.yaml`과 `.env`를 다음처럼 전환합니다.

```yaml
vector_store:
  provider: supabase
  table_name: lessonpack_chunks
  match_function: match_lessonpack_chunks
  match_threshold: 0.0
```

```powershell
LECTUREOPS_VECTOR_STORE=supabase
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
LESSONPACK_SUPABASE_TABLE=lessonpack_chunks
LESSONPACK_SUPABASE_MATCH_FUNCTION=match_lessonpack_chunks
LESSONPACK_SUPABASE_MATCH_THRESHOLD=0.0
```

Supabase 프로젝트에서는 먼저 `supabase/migrations/001_lessonpack_vectors.sql`을 SQL Editor에서 실행합니다. 이 migration은 `vector` extension, `lessonpack_chunks` table, HNSW cosine index, `match_lessonpack_chunks` RPC 함수를 생성합니다. `SUPABASE_SERVICE_ROLE_KEY`는 서버 전용 비밀키이므로 브라우저나 공개 저장소에 노출하지 않습니다.

## 테스트 방법

현재 테스트는 표준 라이브러리 `unittest`로 실행합니다. 로컬/CI 테스트에는 TestClient 의존성인 `httpx`가 포함된 `requirements-dev.txt` 사용을 권장합니다.

```powershell
pip install -r requirements-dev.txt
python -m compileall src scripts tests
python -m unittest discover -s tests
python scripts\check_llm_provider.py --config config.example.yaml
# 실제 LLM/Langfuse trace smoke는 .env 키 설정 후 실행합니다.
python scripts\check_langfuse_trace.py --output outputs\eval\langfuse_trace_smoke.json
```

## Docker 실행

API 서버는 `lessonpack-api` 단일 컨테이너로 실행합니다. Streamlit UI는 1차 GCE 배포 범위에서 제외하고, FastAPI API를 먼저 안정화합니다.

```powershell
Copy-Item .env.example .env
# .env에 필요한 OPENAI_API_KEY, GEMINI_API_KEY, LANGFUSE_*, SUPABASE_* 값을 입력합니다.
docker compose up -d --build
curl.exe -fL http://localhost:8000/health
python scripts\check_deployment.py http://localhost:8000
docker compose ps
docker compose logs lessonpack-api --tail 100
docker compose down
```

## GCE Docker CI/CD 배포

배포 계획과 구현 기준은 [GCE Docker CI/CD 배포 계획서](docs/02_implementation-readiness/05_GCE_Docker_CICD_배포_계획서.md)를 따릅니다.

구축된 CI/CD 산출물은 다음과 같습니다.

- `Dockerfile`: FastAPI production image build
- `.dockerignore`: 비밀값, 로컬 데이터, 생성 산출물 image 제외
- `docker-compose.yml`: 로컬 및 GCE 서버 실행 단위
- `.github/workflows/ci.yml`: compile, provider config check, unittest, Docker build check
- `.github/workflows/cd.yml`: GHCR image push, GCE SSH 배포, `/health` 검증, rollback
- `scripts/check_deployment.py`: 배포된 API health smoke check

GitHub Repository Secrets에는 다음 값을 등록합니다.

| Secret | 용도 |
| --- | --- |
| `GCE_HOST` | GCE VM 외부 IP 또는 도메인 |
| `GCE_USERNAME` | SSH 접속 사용자명 |
| `GCE_SSH_KEY` | SSH 개인키 전체 내용 |
| `SERVICE_PORT` | 선택, 기본 `8000` |
| `OPENAI_API_KEY` | OpenAI primary model 호출 |
| `GEMINI_API_KEY` | Gemini fallback model 호출 |
| `LANGFUSE_PUBLIC_KEY` | Langfuse tracing public key |
| `LANGFUSE_SECRET_KEY` | Langfuse tracing secret key |
| `LANGFUSE_OTEL_HOST` | 필수, Langfuse 리전 host. JP 예: `https://jp.cloud.langfuse.com` |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase server-side service role key |
| `LESSONPACK_SUPABASE_TABLE` | 선택, 기본 `lessonpack_chunks` |
| `LESSONPACK_SUPABASE_MATCH_FUNCTION` | 선택, 기본 `match_lessonpack_chunks` |
| `LESSONPACK_SUPABASE_MATCH_THRESHOLD` | 선택, 기본 `0.0` |

GCE 서버는 Ubuntu VM에 Docker Engine과 Docker Compose plugin이 설치되어 있어야 합니다. CD workflow는 서버의 `/home/<GCE_USERNAME>/lessonpack-ai` 디렉터리에 `.env`, `docker-compose.yml`, `.current_image`, `.previous_image`를 관리하고, 서버에서 직접 build하지 않고 GHCR image를 pull합니다.
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

실제 LiteLLM provider 실증 전에는 다음 명령으로 설정과 API key 환경변수 준비 상태를 확인합니다.

```powershell
python scripts\check_llm_provider.py --config config.yaml --require-real
python scripts\check_llm_provider.py --config config.yaml --require-real --probe
```

실제 provider로 generation Gold Set을 평가할 때는 다음처럼 실행합니다.

```powershell
# .env에서 LESSONPACK_CONFIG, OPENAI_API_KEY, GEMINI_API_KEY, LANGFUSE_* 값을 설정합니다.
python scripts\evaluate_generation.py --require-real-llm --min-case-pass-rate 1.0 --report outputs\eval\generation_real_llm_report.json
```

API key는 `.env` 또는 OS 환경변수로만 주입하고 Git에 커밋하지 않습니다.

발표/실증용 MVP 데모 산출물은 다음 명령으로 생성합니다.

```powershell
python scripts\run_mvp_demo.py --case-id g003 --output-dir outputs\demo
```

성공 시 `outputs/demo/g003_lesson_package.docx`, `outputs/demo/g003_lesson_package.pptx`, `outputs/demo/g003_demo_report.json`이 생성됩니다.
실제 LLM으로 데모 산출물을 만들 때는 `--require-real-llm` 옵션을 추가합니다.

데이터셋, 검색, 생성, provider 준비 상태, 데모 export를 한 번에 검증하려면 다음 명령을 실행합니다.

```powershell
python scripts\run_mvp_verification.py --output-dir outputs\eval --demo-case-id g003
```

성공 시 `outputs/eval/mvp_verification_report.json`과 `outputs/eval/mvp_verification_report.md`가 생성됩니다.

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
- [GCE Docker CI/CD 배포 계획서](docs/02_implementation-readiness/05_GCE_Docker_CICD_배포_계획서.md)

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
- 문서 처리: PyMuPDF 기반 PDF 추출, python-docx DOCX 산출, python-pptx PPTX 산출
- Vector DB: InMemory 테스트 기본값, Supabase(pgvector) 운영 adapter 검증
- 검색: 본문, source metadata, section, tags, 한국어/영어 개념 동의어 기반 keyword scoring
- LLM: provider adapter 경계, mock provider, `http_chat` provider, LiteLLM provider, OpenAI primary + Gemini fallback, Langfuse tracing, generation log 우선
- UI: Swagger UI 우선, 이후 Streamlit 확장
- 평가: 자체 Gold Set, retrieval hit rate, ID 기반 context precision/recall, generation case pass rate, citation coverage, 사람 평가 루브릭 우선, 이후 RAGAS 검토

## 작성자

- Name: RyuGernwoo
- Email: qesadgun@gmail.com
