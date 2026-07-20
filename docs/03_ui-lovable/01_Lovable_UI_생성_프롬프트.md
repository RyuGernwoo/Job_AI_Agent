# Lovable UI 생성 프롬프트 정리

대상 서비스: LessonPack AI
API Base URL: `http://34.47.92.210:8000`
작성 목적: Lovable에서 외부 사용자가 이용할 수 있는 웹 UI를 생성하기 위한 입력 프롬프트와 첨부 파일 정리

## 0. 현재 연동 상태

Lovable repository는 `lessonpack-ai/` 폴더에 별도 저장소로 clone되어 있다. 부모 백엔드 저장소에서는 해당 폴더를 `.gitignore`에 추가해 실수로 함께 commit하지 않도록 한다.

백엔드는 Lovable 배포 도메인과 preview/project 도메인을 CORS 기본 허용 목록에 포함하도록 수정한다. 다만 mixed content 차단은 CORS만으로 해결되지 않으므로, Lovable 배포 UI에서 실제 API를 호출하려면 `VITE_API_BASE_URL`을 HTTPS API 주소로 설정해야 한다.

---

## 1. Lovable에 입력할 메인 프롬프트

아래 내용을 Lovable 첫 입력 프롬프트로 사용한다.

```text
LessonPack AI라는 직업훈련 강의 운영 보조 AI 서비스의 웹 UI를 만들어 주세요.

이 서비스는 직업훈련 강사가 과정명, 차시명, 학습자 수준, 학습목표, NCS 능력단위, 교재 파일을 입력하면 교안, 실습 과제, 평가 문항 초안을 생성하고, 강사가 검수한 뒤 DOCX/PPTX로 내려받을 수 있게 돕는 MVP입니다.

목표 사용자는 일반 직업훈련 강사입니다. 사용자는 우리가 이미 배포한 API 서버를 이용하기만 하며, OpenAI, Gemini, Supabase, Langfuse 같은 개발 설정을 직접 다루지 않습니다.

프론트엔드는 React + TypeScript 기반으로 만들어 주세요. 스타일은 교육기관 업무 도구처럼 조용하고 신뢰감 있게 구성해 주세요. 마케팅 랜딩 페이지가 아니라, 접속하면 바로 강의 패키지를 생성하는 작업 화면이 보여야 합니다.

API 서버는 다음 URL을 사용합니다.

- API Base URL: http://34.47.92.210:8000

단, API 주소는 코드에 하드코딩하지 말고 환경변수로 분리해 주세요.

- 권장 환경변수명: VITE_API_BASE_URL
- 기본값: http://34.47.92.210:8000

구현할 핵심 화면은 다음과 같습니다.

1. 프로젝트 입력 화면
- 과정명 입력
- 차시명 입력
- 학습자 수준/선수 지식 입력
- 학습목표 여러 줄 입력
- NCS 능력단위 입력
  - unit_code
  - unit_name
  - elements 여러 줄 입력
- 다음 단계 버튼

2. 교재 업로드 화면
- TXT, MD, PDF 파일 업로드
- 업로드 진행 상태 표시
- 업로드 완료 후 chunk 수와 파일명을 표시
- 업로드된 chunk 일부를 접어서 확인할 수 있게 표시

3. 근거 검색 화면
- 검색 query 입력
- top_k 선택, 기본값 5
- 검색 실행 버튼
- 검색 결과 chunk 목록 표시
  - chunk_id
  - source_name
  - source_type
  - text preview
  - metadata.section 또는 tags가 있으면 표시
- 생성에 사용할 chunk를 체크박스로 선택 가능하게 해 주세요.
- 기본적으로 검색 결과 전체를 생성 입력으로 사용합니다.

4. 강의 패키지 생성 화면
- 선택된 retrieved_chunks를 POST /api/projects/{project_id}/generate에 전달
- 생성 중 로딩 상태 표시
- 생성 결과를 다음 섹션으로 표시
  - 교안 lesson_plan
  - 실습 practice
  - 평가 assessment
  - citation_ids
- citation ID는 눈에 잘 띄는 작은 badge로 표시해 주세요.

5. 강사 검수 화면
- 현재 package status 표시
- reviewed, approved 상태로 변경할 수 있는 버튼 제공
- reviewer_notes 입력
- PATCH /api/packages/{package_id}/review 호출
- approved 이전에는 export 버튼을 비활성화하거나, 클릭 시 승인 필요 안내를 표시해 주세요.

6. 다운로드 화면
- approved 상태에서 DOCX 다운로드 버튼
- approved 상태에서 PPTX 다운로드 버튼
- GET /api/packages/{package_id}/export.docx
- GET /api/packages/{package_id}/export.pptx
- 생성 로그 보기 버튼
- GET /api/packages/{package_id}/generation-log 결과를 접이식 패널로 표시

API 계약은 다음과 같습니다.

Health check:
GET /health
응답 예시:
{
  "status": "ok",
  "service": "lessonpack-ai"
}

프로젝트 생성:
POST /api/projects
Request JSON:
{
  "course_title": "생성형 AI 활용 기초",
  "lesson_title": "Python 함수와 자료구조 기반 자동화 실습",
  "learner_profile": "Python 기초를 학습한 직업훈련 수강생",
  "learning_objectives": [
    "Python 함수의 정의와 호출 방식을 설명할 수 있다",
    "list와 dictionary를 활용해 간단한 자동화 실습을 수행할 수 있다"
  ],
  "ncs_units": [
    {
      "unit_code": "LM2001020231",
      "unit_name": "프로그래밍 언어 활용",
      "elements": ["스크립트 언어 활용", "구조적 프로그래밍 언어 활용"]
    }
  ]
}

교재 업로드:
POST /api/projects/{project_id}/materials
Content-Type: multipart/form-data
Form field name: file
지원 파일: pdf, txt, md

검색:
POST /api/projects/{project_id}/retrieve
Request JSON:
{
  "query": "Python 함수와 list append pop을 활용한 실습을 설계하라",
  "top_k": 5
}

생성:
POST /api/projects/{project_id}/generate
Request JSON:
{
  "retrieved_chunks": [MaterialChunk 배열]
}

패키지 조회:
GET /api/packages/{package_id}

생성 로그 조회:
GET /api/packages/{package_id}/generation-log

검수 상태 변경:
PATCH /api/packages/{package_id}/review
Request JSON:
{
  "status": "approved",
  "reviewer_notes": "강사가 검토 후 승인함"
}
status 가능한 값:
- draft
- reviewed
- approved
- exported
- regenerated
- needs_revision

DOCX 다운로드:
GET /api/packages/{package_id}/export.docx

PPTX 다운로드:
GET /api/packages/{package_id}/export.pptx

UI 요구사항:
- 전체 화면은 단계형 workflow로 구성합니다.
- 좌측에는 진행 단계 사이드바를 둡니다.
- 상단에는 API 연결 상태를 표시합니다.
- Health check 실패 시 사용자가 알 수 있게 오류 배너를 보여 주세요.
- 모든 API 오류는 조용히 실패하지 말고 사용자에게 이해 가능한 한국어 메시지로 보여 주세요.
- 생성 결과는 긴 텍스트가 많으므로 카드 안에 너무 많은 텍스트를 욱여넣지 말고, 섹션별 접기/펼치기와 스크롤 영역을 사용해 주세요.
- 버튼에는 아이콘을 사용해 주세요.
- 업무 도구 느낌의 차분한 UI를 원합니다. 과한 랜딩 페이지, 큰 히어로 섹션, 장식용 그래픽은 만들지 마세요.
- 모바일보다 데스크톱 사용성을 우선하되, 태블릿 크기에서도 깨지지 않게 반응형으로 만들어 주세요.

기술 요구사항:
- React + TypeScript
- API client는 별도 파일로 분리
- API base URL은 VITE_API_BASE_URL 환경변수 사용
- 파일 다운로드는 blob으로 처리
- 상태 관리는 복잡한 전역 상태보다 화면 단위 state로 단순하게 유지
- 타입은 첨부한 schemas.py 또는 API 문서를 참고해 정의
- 테스트용 샘플 입력값을 UI에 “샘플 채우기” 버튼으로 제공

중요한 운영 주의사항:
- 현재 API가 http://34.47.92.210:8000 으로 제공되므로, Lovable 배포 페이지가 HTTPS라면 브라우저의 mixed content 정책 때문에 직접 호출이 막힐 수 있습니다.
- 이 경우 API 서버에 HTTPS를 붙이거나, 같은 HTTPS 도메인의 reverse proxy를 사용해야 합니다.
- API 서버가 CORS를 허용하지 않으면 브라우저 호출이 실패할 수 있습니다. CORS 오류가 발생하면 백엔드에서 Lovable 배포 도메인을 allow origin에 추가해야 합니다.
```

## 2. 첨부할 파일 우선순위

Lovable에는 너무 많은 파일을 넣기보다 UI/API 이해에 필요한 파일만 첨부한다.

### 필수 첨부

| 파일 | 이유 |
| --- | --- |
| `README.md` | 서비스 목적, 사용자/개발자 안내, 핵심 기능 요약 |
| `src/lectureops_agent/app/main.py` | 실제 API endpoint와 호출 흐름 확인 |
| `src/lectureops_agent/models/schemas.py` | request/response TypeScript 타입 작성 기준 |
| `docs/README.md` | 문서 구조와 현재 구현 상태 요약 |
| `data/README_DATASET.md` | 데이터셋, chunk, Supabase 적재 구조 이해 |

### 권장 첨부

| 파일 | 이유 |
| --- | --- |
| `src/lectureops_agent/ui/workflow.py` | 기존 Streamlit workflow의 단계 흐름 참고 |
| `docs/02_implementation-readiness/01_구현명세서.md` | 기능 범위와 API 의도 확인 |
| `docs/02_implementation-readiness/03_검증_프로토콜.md` | 검증 흐름과 품질 기준 확인 |
| `docs/01_kosena-service-planning/05_서비스_컨셉_기능_정의서.md` | 사용자 가치와 기능 정의 참고 |

### 선택 첨부

| 파일 | 이유 |
| --- | --- |
| `config.example.yaml` | LLM/Supabase 설정 구조 참고. UI에는 직접 노출하지 않음 |
| `.env.example` | 환경변수 이름 참고. 실제 key는 절대 첨부하지 않음 |
| `supabase/migrations/001_lessonpack_vectors.sql` | Supabase 구조 참고. UI 구현에는 필수 아님 |

## 3. 첨부하지 말아야 할 파일

| 파일/폴더 | 이유 |
| --- | --- |
| `.env` | 실제 API key와 service role key가 포함될 수 있음 |
| `data/raw/` | 원천 자료, 용량/라이선스 이슈 |
| `data/processed/` | 로컬 처리 산출물. UI 생성에는 불필요 |
| `outputs/` | 검증/데모 결과물. UI 생성에는 불필요 |
| `.git/` | 저장소 내부 정보 |

## 4. Lovable 생성 후 확인할 항목

1. `GET /health` 호출 성공 여부
2. 프로젝트 생성 성공 여부
3. 파일 업로드 시 multipart field name이 `file`인지 확인
4. 검색 결과의 `MaterialChunk[]`가 생성 요청에 그대로 전달되는지 확인
5. `approved` 이전 export 버튼 비활성화 여부
6. DOCX/PPTX 다운로드가 blob으로 처리되는지 확인
7. CORS 오류 또는 mixed content 오류 발생 여부

## 5. 백엔드 보완 가능성이 높은 항목

Lovable UI가 외부 브라우저에서 API를 호출하려면 다음 백엔드 보완이 필요할 수 있다.

- FastAPI CORS middleware 추가
- Lovable preview/deploy 도메인을 allow origin에 등록
- GCE API에 HTTPS 적용
- `http://34.47.92.210:8000` 대신 HTTPS 도메인 제공
- 장시간 LLM 생성 중 timeout이 발생하면 UI timeout과 backend timeout 조정


## 6. 현재 Lovable CORS 허용 origin

`	ext
https://7f62cef5-bc4c-473e-a8d2-5f1847df5736.lovableproject.com,https://id-preview--7f62cef5-bc4c-473e-a8d2-5f1847df5736.lovable.app,https://lessonpack-ai.lovable.app
`
