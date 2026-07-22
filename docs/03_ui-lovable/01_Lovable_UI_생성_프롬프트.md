# LessonPack AI Lovable UI 연동 명세

## 1. 목적

직업훈련 강사가 교재와 NCS 근거를 바탕으로 교안·실습·평가 패키지를 생성하고, 필요한 경우 자연어로 새 버전을 만든 뒤 DOCX/PPTX로 내려받는 업무형 웹 UI를 구축한다.

배포 UI:

```text
https://lessonpack-ai.lovable.app/
```

기본 HTTPS API:

```text
https://34.47.92.210.nip.io
```

운영 환경에서는 `VITE_API_BASE_URL`로 API 주소를 설정한다. HTTPS UI에서 HTTP API를 호출하지 않는다.

## 2. 사용자 흐름

```text
1. 프로젝트
2. 교재 업로드 및 자동 생성
3. 패키지 결과 및 자연어 수정
4. 다운로드
```

강사 검수 및 승인 단계는 사용하지 않는다. 최초 생성 또는 자연어 재생성이 완료되면 즉시 다운로드 단계로 이동할 수 있다.

## 3. 화면 요구사항

### 프로젝트

- 과정명, 차시명, 학습자 수준, 총 훈련시간, 총 차시, 이론·실습 비율, 학습목표를 입력한다.
- 이론·실습 비율은 각각 0~100이며 합계 100으로 검증한다.
- NCS 능력단위 코드, 명칭, 수행 요소를 입력할 수 있다.
- 근거 검색어를 1~5개 입력·추가·삭제할 수 있다.
- 프로젝트 생성 성공 후 다음 단계로 이동한다.

### 교재 업로드

- PDF, Markdown, TXT 파일을 업로드한다.
- 파일명, 생성 chunk 수, 업로드 성공 여부를 표시한다.
- 모든 파일 업로드가 끝나면 프로젝트의 검색어 목록으로 RAG 검색과 패키지 생성을 자동 실행한다.
- 자동 생성 중에는 진행 상태를 표시하고 중복 요청을 막는다.
- 자동 생성 실패 시 같은 화면에서 근거 재검색·생성을 실행할 수 있다.

### 패키지 생성 및 자연어 수정

- 선택된 근거로 교안, 실습, 평가 패키지를 생성한다.
- 최초 생성 상태는 `generated`다.
- 교안은 제목, 학습목표, 도입·전개·정리 흐름을 표시한다.
- 실습은 시나리오, 수행 절차, 제출물, 평가 기준을 표시한다.
- 평가는 객관식 5문항과 수행평가를 표시한다.
- 근거 출처는 결과 마지막 영역에 모아서 표시한다.
- 자연어 수정 입력란과 수정 요청 버튼을 제공한다.
- 수정 요청은 현재 패키지를 덮어쓰지 않고 새 `package_id`를 반환한다.
- 재생성 상태는 `regenerated`다.
- 재생성 완료 후 현재 화면을 새 패키지로 교체한다.

### 다운로드

- 생성 또는 재생성 직후 DOCX/PPTX 버튼을 활성화한다.
- `approved` 상태를 요구하지 않는다.
- 서버 `Content-Disposition` 파일명을 사용한다.
- 생성 로그를 필요할 때 조회할 수 있다.

## 4. API 계약

### 상태 확인

```http
GET /health
```

### 프로젝트 생성

```http
POST /api/projects
Content-Type: application/json
```

```json
{
  "course_title": "생성형 AI 활용 Python 기초",
  "lesson_title": "함수와 반환값",
  "learner_profile": "Python 입문 직업훈련생",
  "total_training_hours": 8,
  "total_lessons": 4,
  "theory_ratio_percent": 30,
  "practice_ratio_percent": 70,
  "learning_objectives": ["함수의 입력과 반환값을 설명할 수 있다."],
  "ncs_units": [
    {
      "unit_code": "MVP-NCS-001",
      "unit_name": "프로그래밍 기초",
      "elements": ["요구사항에 맞는 함수를 작성한다."]
    }
  ],
  "retrieval_queries": [
    "함수 입력과 반환값을 설명하는 교안 근거",
    "초급 학습자를 위한 함수 작성 실습",
    "함수 활용 능력을 평가하는 문항 기준"
  ]
}
```

### 자료 업로드

```http
POST /api/projects/{project_id}/materials
Content-Type: multipart/form-data
```

form field 이름은 `file`이다.

### 근거 검색 API

운영 UI에서는 별도 검색 단계를 제공하지 않는다. 다음 API는 진단 또는 외부 클라이언트 호환용으로 유지한다.

```http
POST /api/projects/{project_id}/rag/retrieve
Content-Type: application/json
```

```json
{
  "query": "함수 입력 반환값 실습",
  "top_k": 5,
  "include_baseline": true
}
```

### 최초 패키지 생성

교재 업로드가 모두 끝나면 프로젝트에 저장한 검색어 목록을 전달한다. 서버는 query별 RAG 결과를 병합해 하나의 retrieval run과 패키지를 생성한다.

```http
POST /api/projects/{project_id}/rag/generate
Content-Type: application/json
```

```json
{
  "queries": [
    "함수 입력과 반환값을 설명하는 교안 근거",
    "초급 학습자를 위한 함수 작성 실습",
    "함수 활용 능력을 평가하는 문항 기준"
  ],
  "top_k": 5,
  "include_baseline": true
}
```

`query` 단일 검색과 `retrieval_run_id` 기반 생성은 하위 호환용이다. 운영 UI에서는 클라이언트가 chunk 본문을 직접 보내거나 별도 검색 결과를 수동 선택하지 않는다. `strategy=project_material_fallback`은 공통 NCS 데이터가 없는 분야에서 프로젝트 업로드 자료를 근거로 사용한 경우다.

### 자연어 패키지 재생성

```http
POST /api/packages/{package_id}/regenerate
Content-Type: application/json
```

```json
{
  "instruction": "실습 난이도를 낮추고 도입 설명을 쉽게 바꿔 주세요.",
  "top_k": 5,
  "include_baseline": true
}
```

프론트는 응답의 `package`를 현재 패키지로 교체한다. `source_package_id`는 수정 전 패키지와 같고, 새 `package.package_id`는 반드시 달라야 한다.

### 다운로드 및 로그

```http
GET /api/packages/{package_id}/export.docx
GET /api/packages/{package_id}/export.pptx
GET /api/packages/{package_id}/generation-log
```

## 5. 프론트 상태 모델

```ts
type PackageStatus = "generated" | "regenerated" | "exported";
```

`draft`, `reviewed`, `approved`, `needs_revision`, `autoApprove`, review history 관련 상태와 호출은 제거한다.

## 6. 오류 처리

- 네트워크 오류: CORS, mixed content, API 주소를 확인할 수 있는 메시지를 표시한다.
- 404: 원본 패키지가 없으므로 최초 생성부터 다시 진행하도록 안내한다.
- 422: 자료 추가 또는 검색·수정 지시 구체화를 안내한다.
- 502: LLM 수정 결과 검증 실패를 알리고 기존 패키지를 유지한다.
- 503: Supabase 등 서버 저장소 오류로 안내한다.

## 7. CORS 설정

백엔드 허용 origin:

```text
https://7f62cef5-bc4c-473e-a8d2-5f1847df5736.lovableproject.com
https://id-preview--7f62cef5-bc4c-473e-a8d2-5f1847df5736.lovable.app
https://lessonpack-ai.lovable.app
http://localhost:5173
http://127.0.0.1:5173
```

파일 다운로드명 사용을 위해 `Content-Disposition` 응답 헤더를 노출한다.

## 8. 완료 조건

- 4단계 사이드바에 별도 근거 검색·검수 단계가 없다.
- 프로젝트 화면에서 근거 검색어를 여러 개 입력할 수 있다.
- 교재 업로드 완료 후 RAG 검색과 최초 패키지 생성이 자동 실행된다.
- 생성 성공 후 다운로드 단계 버튼이 즉시 활성화된다.
- 자연어 수정이 전용 `/regenerate` API를 호출한다.
- 새 패키지 ID와 `regenerated` 상태가 화면에 반영된다.
- 원본 패키지는 변경되지 않는다.
- 승인 API를 호출하지 않는다.
- DOCX/PPTX 다운로드가 `generated` 상태에서 성공한다.
- 다운로드 파일명에 UUID가 노출되지 않는다.
- HTTPS 배포 UI에서 CORS 및 mixed content 오류가 없다.
