# KOSENA 06. 개발 로드맵·PRD

프로젝트명: **LessonPack AI MVP**
목표: 한 달 안에 1개 차시 강의 패키지를 생성·자연어 수정·다운로드할 수 있는 MVP를 완성한다.

---

## 0. 현재 구현 상태

2026-07-21 기준 이 로드맵의 핵심 Must Have 범위는 구현 완료 상태다. FastAPI API, Lovable 웹 UI 연동, Supabase 기반 vector store, LiteLLM 기반 LLM provider, Langfuse tracing, DOCX/PPTX export, Docker/GCE CI/CD가 적용되어 있다. 이후 로드맵은 품질 실증, 사용자 검증, UI 개선, semantic embedding 고도화를 중심으로 재해석한다.

---

## 1. PRD 요약

| 항목 | 내용 |
|---|---|
| Product | LessonPack AI MVP |
| Target User | 직업훈련 강사, 교육 운영 담당자 |
| Problem | 교안·실습·평가 산출물을 반복 작성하고, NCS·교재 근거를 수작업으로 맞춰야 함 |
| Goal | 1개 차시 강의 패키지를 근거 기반으로 생성하고, 필요 시 자연어로 조정한 뒤 DOCX/PPTX로 저장 |
| Non-goal | LMS 운영, 자동 채점, 기관 계정 관리, 전체 과정 자동 생성 |
| Primary Flow | 입력 → 교재 업로드 → RAG 검색 → 생성 → 자연어 수정(선택) → 다운로드 |
| Success Metric | end-to-end 시연 성공, citation 연결률, DOCX 생성 성공률, 강사 수정 가능성 |
| Risk | 저작권, 할루시네이션, 범위 과대, RAG 품질 편차 |

---

## 2. MVP 정의: MOSCOW

### Must Have

| 기능 | 설명 |
|---|---|
| 커리큘럼/NCS 입력 폼 | 과정명, 차시명, 학습목표, NCS 능력단위 입력 |
| 교재 업로드 | PDF/DOCX/TXT 중 최소 1~2개 형식 지원 |
| RAG 기반 근거 검색 | 업로드 자료에서 관련 문단 검색 |
| 교안 초안 생성 | 목표, 준비물, 강의 흐름, 핵심 설명 포함 |
| 실습 시나리오 생성 | 문제 상황, 수행 절차, 제출물, 평가 기준 포함 |
| 평가 문항 생성 | 객관식 5문항 + 실습형 1문항 |
| 근거 출처 표시 | 각 생성 항목에 문서명·chunk ID 표시 |
| 자연어 수정 화면 | 기존 패키지를 바탕으로 새 버전 생성 |
| DOCX 다운로드 | 최종 산출물 문서화 |

### Should Have

- PPTX 다운로드
- 생성 이력 저장
- 난이도 조절
- 평가 루브릭

### Could Have

- Lovable 웹 UI 고도화
- 생성 결과 비교 보기
- 문항 난이도 자동 분석
- NCS 능력단위 자동 추천
- 다중 차시 일괄 생성

### Won't Have

- 정식 LMS 연동
- 자동 채점 운영
- 기관 단위 사용자 권한
- 전체 과정 자동 생성
- NCS 공식 DB 자동 크롤링
- 완전 자동 게시

---

## 3. Kano 모델 기준

| Kano 유형 | 기능 | 해석 |
|---|---|---|
| Basic | 교재 업로드, 교안 생성, DOCX 다운로드 | 없으면 서비스라고 보기 어려운 기본 기능 |
| Performance | RAG 근거 검색, 평가 문항 생성, 자연어 수정 | 품질이 높을수록 만족도가 상승 |
| Excitement | PPTX 요약, 생성 로그, citation 하이라이트 | 없어도 MVP는 가능하지만 발표 설득력 상승 |
| 제외 | LMS 연동, 자동 채점, 기관 권한 관리 | 한 달 MVP에서는 비용 대비 위험이 큼 |

---

## 4. 시스템 아키텍처

```text
[강사 입력 화면]
  ├─ 과정 정보 입력
  ├─ NCS 능력단위 입력
  └─ 교재 파일 업로드
        ↓
[FastAPI Backend]
  ├─ 파일 파싱
  ├─ 문서 chunking
  ├─ embedding 생성
  ├─ vector DB 검색
  ├─ LLM 생성 요청
  ├─ 패키지 버전 관계 저장
  └─ DOCX/PPTX export
        ↓
[RAG / Agent Layer]
  ├─ 교안 생성 템플릿
  ├─ 실습 생성 템플릿
  ├─ 평가 문항 생성 템플릿
  └─ 근거 출처 매핑
        ↓
[산출물]
  ├─ 강의 교안 DOCX
  ├─ 실습 과제 DOCX
  ├─ 평가 문항 DOCX
  └─ 선택: PPTX 요약본
```

---

## 5. API 초안

| Method | Endpoint | 설명 |
|---|---|---|
| POST | `/api/projects` | 과정·차시·NCS 정보 등록 |
| POST | `/api/projects/{project_id}/materials` | 교재 파일 업로드 |
| POST | `/api/projects/{project_id}/retrieve` | 관련 근거 문단 검색 |
| POST | `/api/projects/{project_id}/generate` | 교안·실습·평가 생성 |
| GET | `/api/packages/{package_id}` | 생성 패키지 조회 |
| POST | `/api/packages/{package_id}/regenerate` | 자연어 지시 기반 새 패키지 생성 |
| GET | `/api/packages/{package_id}/export.docx` | DOCX 다운로드 |
| GET | `/api/packages/{package_id}/export.pptx` | PPTX 다운로드, 선택 기능 |
| GET | `/api/packages/{package_id}/generation-log` | 생성 로그 조회 |

---

## 6. 화면 구성

| 화면 | 주요 요소 |
|---|---|
| 프로젝트 입력 | 과정명, 차시명, 학습 대상, 선수 지식, NCS 능력단위, 학습목표, 교재 업로드 |
| 생성 설정 | 생성 항목 선택, 문항 수 입력, 난이도 선택, 참고 교재 범위 선택 |
| 패키지 생성 | 생성 결과, 근거 출처, 자연어 수정 입력, 다운로드 이동 버튼 |
| 다운로드 | DOCX 다운로드, 선택 PPTX 다운로드, 생성 로그 다운로드 |

---

## 7. 1개월 개발 로드맵

### Week 1: 기획·데이터·RAG 최소 골격

| 작업 | 산출물 |
|---|---|
| 요구사항 확정 | MVP 범위표, 제외 기능표 |
| 샘플 데이터 준비 | 커리큘럼 1개, NCS 텍스트 1개, 교재 일부 |
| 파일 파싱 구현 | PDF/DOCX/TXT 중 최소 TXT + PDF |
| chunking 구현 | chunk ID, 원문 위치, 문서명 저장 |
| vector DB 연결 | Supabase(pgvector) vector store |
| retrieval test | 차시명 입력 시 관련 문단 검색 결과 |

완료 기준:

- 파일 업로드 후 관련 문단 3~5개를 검색할 수 있다.
- 검색 결과에 문서명과 chunk ID가 포함된다.

### Week 2: 생성 Agent 구현

| 작업 | 산출물 |
|---|---|
| 프롬프트 템플릿 설계 | 교안, 실습, 평가별 템플릿 |
| 구조화 출력 설계 | JSON schema |
| LLM 호출 연결 | 선택한 모델 API 연동 |
| 교안 생성 | 도입·전개·정리 구조 |
| 실습 생성 | 시나리오·절차·제출물·루브릭 |
| 평가 생성 | 객관식 5문항 + 실습형 1개 |

완료 기준:

- 같은 입력에서 교안·실습·평가가 한 번에 생성된다.
- 생성 결과에 citation ID가 포함된다.

### Week 3: 자연어 재생성과 Export

| 작업 | 산출물 |
|---|---|
| 자연어 수정 UI 구현 | 현재 패키지 기반 재생성 화면 |
| 버전 관계 저장 | source package ID와 새 package ID 기록 |
| DOCX 템플릿 구성 | 표지, 교안, 실습, 평가 섹션 |
| DOCX export | 다운로드 파일 |
| 생성 로그 저장 | 입력, 검색 문단, 프롬프트, 결과 |

완료 기준:

- 강사가 결과를 수정하고 승인할 수 있다.
- 승인된 결과가 DOCX로 다운로드된다.
- 생성 로그 파일이 남는다.

### Week 4: 품질 개선·발표 준비

| 작업 | 산출물 |
|---|---|
| PPTX export 선택 구현 | 시간이 남을 때만 |
| 근거 누락 검사 | citation 없는 항목 표시 |
| 결과 품질 평가 | 평가표와 예시 결과 |
| README 정리 | 실행 방법, 환경, 한계 |
| 발표 자료 구성 | 5분 데모 흐름 |

완료 기준:

- 1개 샘플 과정으로 end-to-end 시연이 가능하다.
- 문서 산출물과 로그가 저장된다.
- 한계와 추후 계획이 명시된다.

---

## 8. Epic — User Story — Acceptance Criteria

| Epic | User Story | Acceptance Criteria |
|---|---|---|
| 교재 기반 근거 검색 | 강사로서 교재를 업로드하고 싶다. 그래야 내 자료를 근거로 생성할 수 있다. | Given 교재 파일이 업로드되었을 때, When 차시명을 입력하고 검색하면, Then 관련 문단과 문서명이 표시된다. |
| 강의 패키지 자동 생성 | 강사로서 차시 정보를 입력하면 교안·실습·평가 초안을 받고 싶다. | Given 차시 정보와 검색 문단이 있을 때, When 생성을 실행하면, Then 교안·실습·객관식 5문항·실습형 평가 1개가 생성된다. |
| 근거 출처 확인 | 운영 담당자로서 생성 결과의 근거를 확인하고 싶다. | Given 생성 결과가 표시될 때, When 각 항목을 확인하면, Then 연결된 문서명과 chunk ID가 보인다. |
| 자연어 패키지 수정 | 강사로서 AI 패키지를 자연어로 수정하고 싶다. | Given 생성 결과가 있을 때, When 수정 지시를 입력하면, Then 원본은 유지되고 새 package ID의 regenerated 결과가 저장된다. |
| 문서 다운로드 | 강사로서 생성된 결과를 DOCX로 내려받고 싶다. | Given 패키지가 generated 또는 regenerated 상태일 때, When DOCX 다운로드를 누르면, Then 교안·실습·평가가 포함된 파일이 생성된다. |

---

## 9. 마일스톤 KPI

| KPI | 측정 방식 | MVP 목표 |
|---|---|---|
| E2E 성공률 | 업로드→생성→자연어 수정→DOCX 다운로드 완료 여부 | 데모 시나리오 1개 성공 |
| 근거 연결률 | 생성 항목 중 citation ID가 붙은 항목 비율 | 핵심 항목 90% 이상 |
| 문서 생성 성공률 | generated/regenerated 패키지에서 DOCX 파일 생성 여부 | 100% |
| 수정 가능성 | 자연어 지시로 새 버전을 저장할 수 있는지 | 원본 보존과 새 package ID 확인 |
| 발표 적합성 | 5분 발표에서 문제→해결→데모→로드맵 설명 가능 여부 | 7장 내외 발표 구성 가능 |

---

## 10. 결론

개발 로드맵은 기능을 넓히는 것이 아니라 **1개 차시 end-to-end 성공**을 중심으로 설계한다. MVP가 보여줘야 할 핵심은 “AI가 그럴듯한 텍스트를 만든다”가 아니라, “근거 기반 생성 → 자연어 수정 → 운영 문서화” 흐름이다.
