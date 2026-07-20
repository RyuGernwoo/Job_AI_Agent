# LessonPack AI GCE Docker CI/CD 배포 기획서

작성일: 2026-07-20
대상 프로젝트: LessonPack AI
기준 Repository: https://github.com/RyuGernwoo/CI-CD-Guide
배포 대상: Google Compute Engine VM + Docker Compose
CI/CD 도구: GitHub Actions + GHCR + SSH 배포

## 0. 현재 구축 상태

2026-07-20 기준 Docker image build, GitHub Actions CI/CD, GCE Docker 실배포, `/health` 배포 검증이 완료되었다. 이 문서는 구축 전 계획서의 역할도 유지하지만, 현재는 운영 재현과 점검 기준 문서로 사용한다.

현재 운영 의존성은 Supabase, OpenAI, Gemini, Langfuse이며, GCE 컨테이너는 외부 API로 outbound HTTPS 호출을 수행한다.

## 1. 문서 목적

이 문서는 LessonPack AI MVP를 GCE 기반 Docker 서비스로 배포하고, GitHub Actions 기반 CI/CD를 적용하기 위한 구현 전 계획서이다. CI/CD 구조는 `CI-CD-Guide`의 FastAPI 예시 서비스인 `release-notes-api` 흐름을 기준으로 하되, LessonPack AI의 실제 구조에 맞게 endpoint, 실행 명령, 테스트 명령, 환경변수, 외부 의존성을 조정한다.

이번 계획의 목표는 다음과 같다.

- `main` 브랜치에 병합되기 전 자동 검증을 수행한다.
- 검증된 commit만 Docker image로 빌드한다.
- 빌드된 image를 GHCR에 push한다.
- GCE VM은 GHCR image를 pull하여 Docker Compose로 재기동한다.
- 배포 후 `GET /health`로 정상 상태를 확인한다.
- 실패 시 직전 image로 rollback할 수 있게 한다.

## 2. 적용 범위

### 2.1 1차 적용 범위

| 구분 | 적용 내용 |
| --- | --- |
| API 배포 | FastAPI 앱 `lectureops_agent.app.main:app` 컨테이너화 |
| 실행 포트 | 컨테이너 내부 `8000`, 외부 `${SERVICE_PORT:-8000}` |
| Health check | `GET /health` |
| CI | Python 설치, 의존성 설치, compile/test/config 검증 |
| CD | Docker buildx, GHCR push, GCE SSH 배포, health check, rollback |
| 비밀값 관리 | GitHub Actions Secrets와 GCE 서버 `.env` |
| Vector Store | Supabase Postgres + pgvector managed service 사용 |
| LLMOps | LiteLLM SDK, OpenAI primary, Gemini fallback, Langfuse tracing |

### 2.2 1차 제외 범위

| 제외 항목 | 제외 사유 | 후속 단계 |
| --- | --- | --- |
| Streamlit UI 배포 | API 안정화가 우선이며 포트와 인증 정책이 분리되어야 함 | 2차 배포에서 별도 container 또는 reverse proxy로 분리 |
| HTTPS와 도메인 | GCE 단일 VM 배포 흐름 검증이 우선 | Nginx 적용 |
| Load Balancer | 개인 MVP 규모에서는 과함 | 사용자 실증 이후 검토 |
| Blue/Green, Canary | 1개월 MVP 범위를 초과 | rollback 안정화 후 확장 |
| GKE, Cloud Run | 현재 요구사항은 GCE Docker 배포 | 별도 운영 고도화 단계에서 비교 |
| LiteLLM Proxy 서버 | 현재는 LiteLLM SDK 기반 호출 구조 | 팀별 budget/rate-limit 필요 시 별도 서비스화 |

## 3. 현재 프로젝트 기준점

LessonPack AI는 2026-07-20 기준 다음 구조를 가진다.

| 항목 | 현재 값 |
| --- | --- |
| 앱 프레임워크 | FastAPI |
| 앱 import path | `lectureops_agent.app.main:app` |
| 소스 루트 | `src/` |
| health endpoint | `GET /health` |
| 로컬 실행 | `python -m uvicorn lectureops_agent.app.main:app --reload` |
| 테스트 | `python -m unittest discover -s tests` |
| 의존성 파일 | `requirements.txt`, `pyproject.toml` |
| 설정 파일 | `.env.example`, `config.example.yaml`, `config.yaml` |
| LLM provider | `litellm` 기본, `mock` 로컬 대체 가능 |
| Vector Store | Supabase provider adapter, memory provider 테스트 기본값 |
| Supabase migration | `supabase/migrations/001_lessonpack_vectors.sql` |

CI-CD-Guide의 예시 값과 달라지는 핵심 항목은 다음이다.

| CI-CD-Guide 예시 | LessonPack AI 적용값 |
| --- | --- |
| 서비스명 `release-notes-api` | `lessonpack-api` 또는 `lessonpack-ai-api` |
| 앱 import `app.main:app` | `lectureops_agent.app.main:app` |
| health `/api/v1/health/` | `/health` |
| 테스트 `uv run pytest` | 1차 `python -m unittest discover -s tests` |
| dependency `uv.lock` 중심 | 1차 `requirements.txt` 중심, 후속 `uv` 전환 검토 |
| 단순 예시 secret `APP_TOKEN` | LLM, Langfuse, Supabase secret 포함 |

## 4. 목표 아키텍처

```text
Developer
  -> feature branch
  -> Pull Request
  -> GitHub Actions CI
       - dependency install
       - static/compile check
       - unit test
       - config/env readiness check
       - optional Docker build check
  -> main merge
  -> GitHub Actions CD
       - Docker buildx build
       - GHCR push
       - SSH to GCE
       - write .env on server
       - docker compose up -d --force-recreate
       - GET /health
       - rollback on failure
  -> GCE VM
       - lessonpack-api container
       - outbound API calls to OpenAI/Gemini/Langfuse/Supabase
```

운영 의존성은 다음처럼 분리한다.

| 구성요소 | 위치 | 비고 |
| --- | --- | --- |
| FastAPI API | GCE Docker container | 사용자가 호출하는 핵심 서비스 |
| Supabase Postgres/pgvector | Supabase managed project | GCE 내부 DB를 두지 않음 |
| OpenAI API | 외부 API | primary LLM |
| Gemini API | 외부 API | fallback LLM |
| Langfuse | Langfuse Cloud 또는 self-hosted endpoint | trace와 LLMOps 관측 |
| GHCR | GitHub Packages Container registry | Docker image registry |
| GitHub Actions | GitHub hosted runner | CI/CD 실행 |

## 5. 산출물 목록

다음 파일을 단계적으로 추가 또는 수정한다.

| 산출물 | 경로 | 목적 |
| --- | --- | --- |
| Dockerfile | `Dockerfile` | production image build |
| Docker ignore | `.dockerignore` | image에 불필요한 데이터와 비밀값 제외 |
| Compose 파일 | `docker-compose.yml` | 로컬과 GCE에서 동일한 실행 단위 관리 |
| CI workflow | `.github/workflows/ci.yml` | PR/push 검증 자동화 |
| CD workflow | `.github/workflows/cd.yml` | GHCR build/push와 GCE 배포 자동화 |
| 배포 문서 | `docs/02_implementation-readiness/05_GCE_Docker_CICD_배포_계획서.md` | 구현 기준 문서 |
| 환경변수 예시 | `.env.example` | 배포에 필요한 key 정리 |
| README 보강 | `README.md` | Docker/GCE/CI-CD 실행 안내 추가 |
| 서버 점검 스크립트 | 선택: `scripts/check_deployment.py` | `/health`와 핵심 endpoint smoke test |

## 6. Docker 설계

### 6.1 Dockerfile 기준

1차 Dockerfile은 현재 프로젝트의 `requirements.txt`를 사용한다. `CI-CD-Guide`는 `uv` 기반 multi-stage build를 사용하지만, LessonPack AI는 이미 `requirements.txt` 중심 설치와 `unittest` 검증 체인이 안정화되어 있으므로 1차 배포에서는 도구 전환을 배포 리스크로 만들지 않는다.

권장 구성은 다음과 같다.

| 항목 | 기준 |
| --- | --- |
| base image | `python:3.11-slim` |
| workdir | `/app` |
| dependency install | `pip install --no-cache-dir -r requirements.txt` |
| source copy | `src/`, `config.example.yaml`, 필요한 `scripts/` 일부 |
| python path | `PYTHONPATH=/app/src` |
| user | non-root user `lessonpack` |
| expose | `8000` |
| healthcheck | `http://127.0.0.1:8000/health` |
| command | `uvicorn lectureops_agent.app.main:app --host 0.0.0.0 --port 8000` |

후속으로 `uv`를 도입할 경우 다음 조건을 만족한 뒤 전환한다.

- `uv.lock` 생성 및 commit
- CI와 Dockerfile 설치 명령을 `uv sync --frozen`으로 통일
- Windows 로컬 개발과 GitHub Actions runner에서 동일하게 통과 확인
- 기존 `requirements.txt`와의 중복 관리 정책 결정

### 6.2 `.dockerignore` 기준

Docker image에는 실행에 필요한 최소 파일만 포함한다.

포함하지 않을 항목:

```text
.env
.venv/
.git/
__pycache__/
.pytest_cache/
.ruff_cache/
outputs/
data/raw/
data/processed/
*.pdf
*.docx
*.pptx
```

주의할 점:

- `data/gold/`는 CI 평가에 필요할 수 있으나 production image에는 기본적으로 포함하지 않는다.
- 실제 운영에서 검색용 데이터는 Supabase에 ingest된 상태여야 하며, 원천 데이터 파일을 image에 넣지 않는다.
- `config.yaml`에는 로컬 설정이 들어갈 수 있으므로 image에는 `config.example.yaml`만 포함하고, 서버에서는 `.env`로 `LESSONPACK_CONFIG` 사용 여부를 결정한다.

### 6.3 Docker Compose 기준

서비스명은 `lessonpack-api`로 둔다.

권장 실행 값:

| 항목 | 값 |
| --- | --- |
| compose project name | `lessonpack-ai` |
| service | `lessonpack-api` |
| container_name | `lessonpack-api` |
| image | `${APP_IMAGE:-lessonpack-ai:local}` |
| port | `${SERVICE_PORT:-8000}:8000` |
| env_file | `.env` |
| restart | `unless-stopped` |
| healthcheck | `GET /health` |

서버 compose는 CD workflow가 배포 디렉터리에 생성하거나, repository의 `docker-compose.yml`을 그대로 전송해서 사용한다. 1차 구현은 CI-CD-Guide처럼 CD workflow 내부에서 서버용 compose를 생성하는 방식을 따른다. 이렇게 하면 GCE 서버에 git clone을 둘 필요가 없고, 서버에는 `.env`, `docker-compose.yml`, `.current_image`, `.previous_image`만 남는다.

## 7. 환경변수 및 Secret 설계

### 7.1 GitHub Actions Secrets

GCE 배포와 운영 실행에 필요한 값을 GitHub Repository Secrets에 등록한다.

| Secret | 필수 | 용도 |
| --- | --- | --- |
| `GCE_HOST` | 예 | GCE VM 외부 IP 또는 도메인 |
| `GCE_USERNAME` | 예 | SSH 접속 사용자명 |
| `GCE_SSH_KEY` | 예 | SSH 개인키 전체 내용 |
| `SERVICE_PORT` | 선택 | 외부 노출 포트, 기본 `8000` |
| `LESSONPACK_CORS_ALLOW_ORIGINS` | 선택 | Lovable 배포/preview/project origin. 쉼표로 여러 origin 지정 |
| `LESSONPACK_CORS_ALLOW_CREDENTIALS` | 선택 | CORS credential 허용 여부, 기본 `false` |
| `LESSONPACK_PUBLIC_API_HOST` | 선택 | Caddy HTTPS reverse proxy용 public host. 예: `api.example.com` |
| `OPENAI_API_KEY` | 예 | LiteLLM primary OpenAI 호출 |
| `GEMINI_API_KEY` | 예 | Gemini fallback 호출 |
| `LANGFUSE_PUBLIC_KEY` | 예 | Langfuse trace public key |
| `LANGFUSE_SECRET_KEY` | 예 | Langfuse trace secret key |
| `LANGFUSE_OTEL_HOST` | 예 | Langfuse 리전 host. JP 예: `https://jp.cloud.langfuse.com` |
| `SUPABASE_URL` | 예 | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | 예 | Supabase server-side key |
| `LESSONPACK_SUPABASE_TABLE` | 선택 | 기본 `lessonpack_chunks` |
| `LESSONPACK_SUPABASE_MATCH_FUNCTION` | 선택 | 기본 `match_lessonpack_chunks` |
| `LESSONPACK_SUPABASE_MATCH_THRESHOLD` | 선택 | 기본 `0.0` |
| `LESSONPACK_CONFIG` | 선택 | 서버에서 config 파일을 쓸 경우 `config.yaml` |
| `LESSONPACK_LLM_PROVIDER` | 선택 | env-only fallback, 기본 `litellm` |
| `LESSONPACK_LITELLM_MODEL` | 선택 | 기본 `gpt-4o-mini` |
| `LESSONPACK_LITELLM_FALLBACK_MODELS` | 선택 | 기본 `gemini/gemini-2.0-flash` |
| `LESSONPACK_LITELLM_CALLBACKS` | 선택 | 기본 `langfuse_otel` |

`GITHUB_TOKEN`은 GitHub Actions가 자동 제공하므로 별도 secret으로 등록하지 않는다. GHCR push에는 workflow `permissions.packages: write`가 필요하다.

### 7.2 GCE 서버 `.env`

CD workflow는 GCE 배포 디렉터리의 `.env`를 매 배포마다 갱신한다. 예시:

```env
APP_NAME=lessonpack-ai
APP_ENV=production
DEBUG=false
SERVICE_PORT=8000
APP_IMAGE=ghcr.io/ryugernwoo/job_ai_agent/lessonpack-api:sha-xxxxxxxxxxxx
PYTHONPATH=/app/src
LESSONPACK_CONFIG=
LESSONPACK_LLM_PROVIDER=litellm
LESSONPACK_LITELLM_MODEL=gpt-4o-mini
LESSONPACK_LITELLM_FALLBACK_MODELS=gemini/gemini-2.0-flash
LESSONPACK_LITELLM_CALLBACKS=langfuse_otel
OPENAI_API_KEY=<github-secret>
GEMINI_API_KEY=<github-secret>
LANGFUSE_PUBLIC_KEY=<github-secret>
LANGFUSE_SECRET_KEY=<github-secret>
LANGFUSE_OTEL_HOST=https://jp.cloud.langfuse.com
LANGFUSE_BASE_URL=https://jp.cloud.langfuse.com
LESSONPACK_LANGFUSE_TRACE_NAME=lessonpack-ai-mvp
LESSONPACK_LANGFUSE_GENERATION_NAME=lessonpack-ai-generation
LESSONPACK_LANGFUSE_SESSION_ID=lessonpack-ai-production
LESSONPACK_LANGFUSE_FLUSH_WAIT_SECONDS=1.0
SUPABASE_URL=<github-secret>
SUPABASE_SERVICE_ROLE_KEY=<github-secret>
LESSONPACK_SUPABASE_TABLE=lessonpack_chunks
LESSONPACK_SUPABASE_MATCH_FUNCTION=match_lessonpack_chunks
LESSONPACK_SUPABASE_MATCH_THRESHOLD=0.0
LECTUREOPS_VECTOR_STORE=supabase
```

원칙:

- `.env`는 Git에 commit하지 않는다.
- GCE 서버의 `.env`도 repository에서 pull하지 않고 GitHub Actions가 생성한다.
- Langfuse trace가 대시보드에 보이지 않으면 먼저 `LANGFUSE_OTEL_HOST`가 실제 프로젝트 리전과 같은지 확인하고, `python scripts/check_langfuse_trace.py --output outputs/eval/langfuse_trace_smoke.json`로 synthetic trace를 조회한다.
- `SUPABASE_SERVICE_ROLE_KEY`는 browser, Streamlit client, public log에 노출하지 않는다.
- workflow log에 secret 값이 출력되지 않도록 `printf`, base64 전달, GitHub secret masking을 사용한다.

## 8. CI 계획

### 8.1 Trigger

CI는 다음 이벤트에서 실행한다.

```yaml
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:
```

권장 `paths` 조건:

```text
src/**
scripts/**
tests/**
data/gold/**
supabase/migrations/**
requirements.txt
pyproject.toml
config.example.yaml
.env.example
Dockerfile
docker-compose.yml
.github/workflows/**
```

문서만 변경하는 PR에서는 CI를 생략할 수 있지만, 배포 관련 문서와 workflow를 함께 수정하는 경우에는 수동 실행으로 검증한다.

### 8.2 Job 구성

| Job | 목적 | 명령 |
| --- | --- | --- |
| `Code Quality` | Python 문법과 import 가능성 확인 | `python -m compileall src scripts tests` |
| `Unit Tests` | 회귀 테스트 | `python -m unittest discover -s tests` |
| `Config Check` | 설정 파일과 provider readiness 확인 | `python scripts/check_llm_provider.py --config config.yaml` |
| `Dataset Check` | Gold Set과 처리 산출물 참조 검증 | `python scripts/validate_mvp_dataset.py` |
| `Docker Build Check` | image build 가능성 확인 | `docker build -t lessonpack-ai:ci .` |
| `Report Status` | PR에 결과 요약 comment 작성 | GitHub CLI `gh pr comment` |

1차 필수 status check는 다음 3개로 둔다.

- `Code Quality`
- `Unit Tests`
- `Docker Build Check`

`Dataset Check`는 데이터 파일 크기와 실행 시간에 따라 필수 여부를 결정한다. 현재 `data/raw/`, `data/processed/`는 Git 제외 대상이므로 CI에서 재생성이 어려운 경우 `data/gold/` 무결성 위주로 낮춘다.

### 8.3 CI 환경

| 항목 | 기준 |
| --- | --- |
| runner | `ubuntu-latest` |
| Python | `3.11` |
| dependency | `pip install -r requirements.txt` |
| `PYTHONPATH` | `src` |
| 외부 API key | CI 기본 검증에는 사용하지 않음 |
| 실제 LLM probe | manual workflow 또는 별도 nightly로 분리 |

실제 API key가 필요한 테스트는 일반 PR CI에 넣지 않는다. 비용과 rate limit이 걸릴 수 있으므로 `workflow_dispatch` 또는 별도 evaluation workflow로 분리한다.

## 9. CD 계획

### 9.1 Trigger

CD는 CI 성공 뒤 자동 실행하거나 수동으로 실행한다.

```yaml
on:
  workflow_run:
    workflows:
      - LessonPack AI CI
    types: [completed]
    branches: [main]
  workflow_dispatch:
    inputs:
      mode:
        type: choice
        options: [deploy, rollback]
      image:
        required: false
```

정책:

- `workflow_run` 이벤트에서 CI 결과가 `success`가 아니면 build/deploy를 건너뛴다.
- `deploy`는 현재 commit SHA 기반 image를 build/push한다.
- `rollback`은 image 입력값이 있으면 해당 image를 사용하고, 없으면 서버의 `.previous_image`를 사용한다.

### 9.2 Image naming

권장 image:

```text
ghcr.io/ryugernwoo/job_ai_agent/lessonpack-api:sha-<12자리_sha>
ghcr.io/ryugernwoo/job_ai_agent/lessonpack-api:main
```

주의:

- GHCR image 이름은 lowercase로 정규화한다.
- 운영 배포는 `main` tag가 아니라 SHA tag를 `.current_image`에 기록한다.
- `main` tag는 최신 확인용 보조 tag로만 사용한다.

### 9.3 Build & Push

CD build job은 다음을 수행한다.

1. 배포 대상 commit checkout
2. GHCR login
3. Docker Buildx 준비
4. Docker image build
5. SHA tag와 `main` tag push
6. GitHub step summary에 image digest와 tag 기록

권장 권한:

```yaml
permissions:
  contents: read
  packages: write
```

### 9.4 GCE Deploy

Deploy job은 다음을 수행한다.

1. 필수 secret 존재 확인
2. SSH key 파일 생성
3. `ssh-keyscan`으로 known_hosts 등록
4. 배포 디렉터리 `/home/${GCE_USERNAME}/lessonpack-ai` 생성
5. 서버 `.env` 생성
6. 서버 `docker-compose.yml` 생성 또는 갱신
7. GHCR login
8. 새 image pull
9. `docker compose up -d --force-recreate`
10. `curl -fsS http://127.0.0.1:${SERVICE_PORT}/health` 반복 확인
11. 성공 시 `.current_image`와 `.previous_image` 갱신
12. 실패 시 이전 image로 rollback 시도
13. `docker compose ps`, `docker logs lessonpack-api --tail 100` 요약 출력

### 9.5 Rollback

서버 배포 디렉터리에 다음 파일을 둔다.

| 파일 | 역할 |
| --- | --- |
| `.current_image` | 현재 실행 중인 image |
| `.previous_image` | 직전 정상 image |

Rollback 절차:

1. 새 image health check 실패
2. `old_image`가 있으면 `.env`의 `APP_IMAGE`를 old image로 재작성
3. `docker pull old_image`
4. `docker compose up -d --force-recreate`
5. `/health` 재확인
6. rollback 결과를 GitHub Actions summary에 기록

수동 rollback은 GitHub Actions `workflow_dispatch`에서 `mode=rollback`으로 실행한다.

## 10. GCE 서버 구축 계획

### 10.1 VM 기준값

| 항목 | 권장값 |
| --- | --- |
| VM 이름 | `lessonpack-ai-server` |
| Region | `asia-northeast3` |
| Zone | `asia-northeast3-a` |
| OS | `Ubuntu 22.04 LTS` 또는 `Ubuntu 24.04 LTS` |
| Machine type | 최소 `e2-small`, 권장 `e2-medium` |
| Boot disk | `20GB` 이상 |
| Network tag | `lessonpack-ai-server` |
| Service port | `8000` |
| Deploy dir | `/home/<GCE_USERNAME>/lessonpack-ai` |

MVP는 외부 LLM API와 Supabase를 사용하므로 GPU VM은 필요하지 않다. 문서 변환과 export 작업이 늘어나면 CPU/RAM 사용량을 보고 `e2-medium` 이상으로 조정한다.

### 10.2 방화벽

1차 실증에서는 `tcp:8000`을 허용한다.

```bash
gcloud compute firewall-rules create allow-lessonpack-api-8000 \
  --network="default" \
  --direction="INGRESS" \
  --priority="1000" \
  --action="ALLOW" \
  --rules="tcp:8000" \
  --source-ranges="0.0.0.0/0" \
  --target-tags="lessonpack-ai-server"
```

운영 고도화 시에는 다음 방향으로 바꾼다.

- 외부에는 `80/443`만 노출
- Nginx/Caddy reverse proxy에서 HTTPS 종료
- API container는 VM 내부 `127.0.0.1:8000` 또는 Docker network에만 노출
- 필요 시 Cloud Armor, IAP, VPN 검토

### 10.3 Docker 설치

Ubuntu VM에서 Docker Engine과 Compose plugin을 설치한다. CI-CD-Guide와 같이 서버에서 image를 build하지 않고 GHCR에서 pull하므로, 서버에는 Docker runtime과 compose plugin만 있으면 된다.

검증 명령:

```bash
docker run hello-world
docker version
docker compose version
```

### 10.4 서버 준비 완료 기준

- `GCE_HOST`로 SSH 접속 가능
- `whoami` 결과를 `GCE_USERNAME`으로 등록
- `docker` 명령을 sudo 없이 실행 가능
- `/home/<GCE_USERNAME>/lessonpack-ai` 디렉터리 생성 가능
- GCE firewall에서 `tcp:8000` 접근 가능
- Caddy reverse proxy를 사용하려면 `tcp:80`, `tcp:443` 접근 가능
- `LESSONPACK_PUBLIC_API_HOST`가 GCE 외부 IP를 가리키는 DNS 이름으로 설정됨
- GitHub Actions에서 사용할 SSH private key가 등록됨

## 11. Supabase 준비 계획

GCE 배포 전에 Supabase project에서 migration을 먼저 실행한다.

필수 작업:

1. Supabase project 생성
2. SQL Editor에서 `supabase/migrations/001_lessonpack_vectors.sql` 실행
3. `lessonpack_chunks` table 생성 확인
4. `match_lessonpack_chunks` RPC 함수 생성 확인
5. HNSW cosine index 생성 확인
6. 로컬 또는 수동 스크립트로 processed chunks ingest
7. GitHub Secrets에 `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` 등록

운영 원칙:

- Supabase service role key는 서버 전용 secret으로만 사용한다.
- RLS 정책은 공개 client 접근을 허용하지 않는 방향으로 설계한다.
- GCE container health check에는 Supabase 연결 검사를 포함하지 않는다. 외부 의존성 장애로 container가 계속 재시작되는 상황을 피하기 위해 `/health`는 앱 프로세스 상태 확인으로 제한한다.
- 별도 readiness endpoint가 필요하면 후속으로 `/api/readiness`를 추가하고 Supabase/LLM 연결 상태를 확인한다.

## 12. LLMOps 준비 계획

현재 기본 모델 운영 방향은 다음이다.

| 항목 | 값 |
| --- | --- |
| Provider | `litellm` |
| Primary model | `gpt-4o-mini` |
| Fallback model | `gemini/gemini-2.0-flash` |
| Trace callback | `langfuse_otel` |

배포 전 확인:

```powershell
python scripts\check_llm_provider.py --config config.yaml --require-real
```

실제 API 호출 probe는 비용이 발생할 수 있으므로 일반 CI에는 넣지 않고 수동 검증으로 둔다.

```powershell
python scripts\check_llm_provider.py --config config.yaml --require-real --probe
```

GCE 서버에서는 `.env`에 OpenAI, Gemini, Langfuse key를 주입하고 container가 outbound HTTPS를 통해 외부 API를 호출한다.

## 13. 검증 계획

### 13.1 로컬 검증

```powershell
python -m compileall src scripts tests
python -m unittest discover -s tests
python scripts\check_llm_provider.py --config config.yaml
python scripts\validate_mvp_dataset.py
```

### 13.2 로컬 Docker 검증

```powershell
Copy-Item .env.example .env
docker compose up -d --build
curl.exe -fL http://localhost:8000/health
docker compose ps
docker compose logs lessonpack-api --tail 100
docker compose down
```

성공 기준:

- Docker image build 성공
- container status `healthy`
- `GET /health` HTTP 200
- container log에 import error, missing env fatal error 없음

### 13.3 GitHub CI 검증

성공 기준:

- Pull Request에서 `Code Quality` success
- Pull Request에서 `Unit Tests` success
- Pull Request에서 `Docker Build Check` success
- Branch Ruleset이 실패 check의 main merge를 차단
- PR comment 또는 step summary에서 실패 원인 확인 가능

### 13.4 GitHub CD 검증

성공 기준:

- main merge 후 CD 자동 실행
- GHCR에 SHA tag image 생성
- GCE 서버의 `/home/<GCE_USERNAME>/lessonpack-ai/.current_image`가 새 SHA tag로 갱신
- `curl http://<GCE_HOST>:8000/health` HTTP 200
- `docker compose ps`에서 `lessonpack-api` healthy
- Langfuse에서 실제 generation 요청 trace 확인 가능

### 13.5 Rollback 검증

수동으로 이전 image rollback을 검증한다.

```text
GitHub Actions -> LessonPack AI CD -> Run workflow
mode: rollback
image: 비워두기 또는 특정 GHCR image 입력
```

성공 기준:

- `.previous_image`를 읽어 재배포 가능
- rollback 후 `/health` HTTP 200
- GitHub Actions summary에 rollback 대상 image와 결과 표시

## 14. 보안 계획

| 위험 | 대응 |
| --- | --- |
| `.env` commit | `.gitignore`, `.dockerignore`, CI secret scan 체크 |
| SSH private key 노출 | GitHub Secrets에만 저장, workflow log 출력 금지 |
| Supabase service role key 노출 | 서버 env 전용, client/UI 미전달 |
| GHCR private image pull 실패 | deploy job에서 `GITHUB_TOKEN`으로 docker login |
| 외부 포트 과다 노출 | 1차 `8000`만, 후속 reverse proxy에서 `443` 중심 전환 |
| LLM API 비용 폭증 | 실제 provider 테스트를 manual로 분리, Langfuse 관측 |
| 장애 시 원인 파악 어려움 | health, docker logs, GitHub summary, Langfuse trace 사용 |

## 15. 단계별 구현 로드맵

### Phase 0. 사전 정리

- `config.example.yaml`과 `.env.example`에 배포용 변수 누락 여부 확인
- `GET /health` 테스트가 존재하는지 확인, 없으면 추가
- Supabase migration 실행 절차와 ingest 절차 확인
- 현재 CI에서 사용할 테스트 명령 확정

완료 기준:

- 로컬 `python -m unittest discover -s tests` 통과
- `.env.example`에 배포 secret placeholder 존재
- README에 Docker/CI-CD 진행 예정 위치 확인

### Phase 1. Docker 실행 환경 구축

- `Dockerfile` 작성
- `.dockerignore` 작성
- `docker-compose.yml` 작성
- 로컬 Docker build/run 검증
- README에 Docker 실행 방법 추가

완료 기준:

- `docker compose up -d --build` 성공
- `curl http://localhost:8000/health` 성공
- container health status `healthy`

### Phase 2. CI workflow 구축

- `.github/workflows/ci.yml` 작성
- Python dependency install
- compile check, unittest, config check, Docker build check 구성
- PR comment 또는 step summary 추가
- Branch Ruleset에서 필수 status check 등록

완료 기준:

- PR에서 CI 자동 실행
- 실패 시 main merge 차단
- 성공 시 merge 가능

### Phase 3. GCE 서버 준비

- GCE VM 생성
- firewall rule 생성
- Docker Engine 및 Compose plugin 설치
- SSH key 준비
- GitHub Secrets 등록
- 배포 디렉터리 생성

완료 기준:

- GitHub Actions runner에서 SSH 접속 가능
- 서버에서 `docker compose version` 확인
- 외부에서 `tcp:8000` 접근 가능

### Phase 4. CD workflow 구축

- `.github/workflows/cd.yml` 작성
- GHCR build/push 구성
- GCE SSH 배포 script 작성
- `.env` 생성 로직 작성
- `/health` 기반 배포 검증 추가
- rollback 로직 추가

완료 기준:

- main merge 후 GHCR image 생성
- GCE에서 새 image 실행
- `/health` HTTP 200
- `.current_image`, `.previous_image` 기록

### Phase 5. 운영 고도화

- HTTPS와 domain 연결
- reverse proxy 적용
- readiness endpoint 추가
- Langfuse trace dashboard 점검
- 실제 사용자 실증 시나리오 실행
- 배포 실패와 rollback 시나리오 리허설

완료 기준:

- HTTPS URL로 API 접근 가능
- 실제 LLM/Supabase 기반 데모 요청 성공
- 장애 발생 시 rollback 절차를 문서 없이 수행 가능

## 16. 최종 인수 기준

| 범주 | 인수 기준 |
| --- | --- |
| 로컬 앱 | `python -m unittest discover -s tests` 통과 |
| 로컬 Docker | `docker compose up -d --build` 후 `/health` 성공 |
| CI | PR에서 필수 status check 통과 전 main merge 불가 |
| Registry | GHCR에 SHA tag image push 확인 |
| GCE 배포 | `http://<GCE_HOST>:8000/health` HTTP 200 |
| Secret 관리 | `.env`, SSH key, service role key가 Git에 없음 |
| Supabase | migration 적용 및 검색 chunk ingest 완료 |
| LLMOps | OpenAI primary, Gemini fallback, Langfuse trace 수동 실증 완료 |
| Rollback | 이전 image로 재배포 가능 |

## 17. 구현 시 주의사항

- CI-CD-Guide의 파일을 그대로 복사하지 말고 LessonPack AI의 endpoint와 실행 경로로 치환한다.
- `/api/v1/health/`가 아니라 `/health`를 사용한다.
- `app.main:app`가 아니라 `lectureops_agent.app.main:app`를 사용한다.
- 운영 image에 `data/raw/`, `outputs/`, `.env`를 포함하지 않는다.
- GCE 서버에는 git repository를 clone하지 않는 배포 방식을 우선한다.
- 서버에서 직접 build하지 않고 GHCR에서 pull한다.
- 실제 LLM 호출 검증은 일반 CI가 아니라 수동 evaluation gate로 분리한다.
- Supabase service role key는 절대 frontend나 공개 로그로 전달하지 않는다.

## 18. 참고 자료

- CI-CD-Guide: https://github.com/RyuGernwoo/CI-CD-Guide
- GitHub Actions Docs: https://docs.github.com/en/actions
- GitHub Actions Secrets: https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets
- GitHub Container Registry: https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry
- GitHub Docker image publishing: https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images
- Google Compute Engine container deployment: https://cloud.google.com/compute/docs/containers/deploying-containers
- Docker Engine on Ubuntu: https://docs.docker.com/engine/install/ubuntu/
- Docker Compose: https://docs.docker.com/compose/
