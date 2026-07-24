# LessonPack AI PPT 템플릿 기반 강의자료 생성 기획서

작성일: 2026-07-23
최종 갱신: 2026-07-24
대상 기능: 사용자 업로드 PowerPoint 템플릿을 적용한 강의자료 PPTX 생성

## 0. 구축 반영 상태

2026-07-23 기준 코드 구축은 완료했다.

| 영역 | 반영 상태 |
| --- | --- |
| 백엔드 | 템플릿 업로드·조회·레이아웃 매핑·삭제 API 구현 |
| 저장소 | 로컬 테스트용 메모리 저장소와 Supabase Storage/Postgres 저장소 구현 |
| 보안 검사 | `.pptx`, ZIP 구조, 압축 해제 크기, macro, 외부 관계 검사 구현 |
| PPTX export | 원본 슬라이드 역할 분류·복제, 배경·이미지·도형 유지, 샘플 문구 교체, 내용량 기반 분할, 마지막 출처 슬라이드 검증 구현 |
| 프론트엔드 | 사용 권한 확인, 업로드·교체·삭제, 원본 디자인/마스터 레이아웃 구분, 자동 매핑 확인·수정 구현 |
| fallback | 템플릿 조회·다운로드·생성 실패 시 기본 PPTX 생성 및 응답 헤더로 결과 표시 |
| 남은 운영 작업 | `009_ppt_template_storage.sql` 적용, GCE 재배포 |

## 1. 목적

강사가 기관·과정별로 보유한 PowerPoint 템플릿을 업로드하면 LessonPack AI가 해당 템플릿의 테마, 슬라이드 마스터, 레이아웃, 글꼴·색상 설정을 최대한 유지한 강의자료를 생성한다.

기본 PPTX export는 빈 `Presentation()`에서 표지·학습목표·교안·실습·평가·근거 출처 슬라이드를 새로 만든다. 사용자 템플릿을 등록하면 원본 슬라이드를 역할별 디자인 후보로 분석하고, 생성 내용을 해당 디자인에 배치한다.

```text
프로젝트 정보 입력
→ PPT 템플릿 업로드·레이아웃 확인(선택)
→ 교재 업로드·RAG 기반 패키지 생성
→ 템플릿 레이아웃에 교안·실습·평가 배치
→ 템플릿 적용 PPTX 다운로드
```

템플릿 업로드는 선택 사항이며, 업로드하지 않으면 기본 PPTX export를 그대로 사용한다.

## 2. 범위와 원칙

| 구분 | MVP 적용 | 제외 또는 후순위 |
| --- | --- | --- |
| 지원 형식 | `.pptx` | `.ppt`, `.pot`, `.pptm`, Google Slides 직접 연동 |
| 적용 범위 | 재사용 가능한 원본 슬라이드의 배경·이미지·도형·텍스트 스타일, 테마, 마스터 레이아웃 | 애니메이션·전환 효과·매크로·차트 데이터의 완전 복제 |
| 템플릿 단위 | 프로젝트별 1개 활성 템플릿 | 기관 공용 템플릿 라이브러리, 사용자별 권한 관리 |
| 생성 방식 | semantic slide type을 원본 슬라이드 디자인 또는 마스터 레이아웃에 매핑하여 생성 | 원본 샘플 문구를 그대로 유지하는 단순 복사 |
| 저장소 | Supabase Storage 비공개 bucket + Postgres metadata | GCE 컨테이너 로컬 영구 저장 |

- 능동 콘텐츠가 포함될 수 있는 `pptm`과 구형 바이너리 `ppt`는 받지 않는다. `ppt`는 PowerPoint에서 `.pptx`로 변환한 뒤 업로드한다.
- 템플릿 파일은 교재가 아니므로 RAG parsing, chunking, embedding, 근거 검색 대상에서 제외한다.
- 기본 export와 템플릿 export의 산출물 내용·근거 출처 규칙은 동일하다. 근거는 마지막 출처 슬라이드에만 표시한다.
- 템플릿의 저작권·사용권은 업로드자가 보유하거나 교육 목적으로 사용할 수 있어야 하며, 업로드 화면에서 확인을 받는다.

## 3. 사용자 경험

### 3.1 입력 화면

프로젝트 생성 후 교재 업로드 단계 상단에 `PPT 템플릿(선택)` 영역을 둔다.

1. 사용자가 `.pptx` 파일을 선택하거나 드래그 앤 드롭한다.
2. 서버가 파일 안전성, 슬라이드 수, 원본 슬라이드 역할·내용 수용량, 마스터 레이아웃과 placeholder를 분석한다.
3. UI는 템플릿명, 슬라이드 수, 재사용 가능한 원본 디자인 수와 마스터 레이아웃 수를 표시한다.
4. 자동 매핑 결과를 확인하고 필요하면 역할별로 `원본 슬라이드 디자인` 또는 `마스터 레이아웃`을 선택한다.
5. 교재 업로드와 패키지 생성은 기존 흐름대로 진행한다.

템플릿 분석이 실패하면 사용자는 파일을 교체하거나 `기본 디자인으로 생성`을 선택할 수 있다. 템플릿 오류가 RAG 기반 패키지 생성을 막아서는 안 된다.

### 3.2 다운로드 화면

- 템플릿명·적용 일시·fallback 발생 여부를 표시한다.
- 개별 슬라이드의 미리보기 편집은 MVP에서 제공하지 않는다. 생성 파일을 내려받아 PowerPoint에서 최종 편집한다.

## 4. 템플릿 계약과 레이아웃 매핑

시스템은 아래 semantic slide type을 사용한다. 원본 슬라이드에 제목·본문 placeholder가 없어도 텍스트 상자 구조와 면적을 분석해 디자인 후보로 사용할 수 있으며, 적절한 원본 후보가 없으면 마스터 레이아웃 또는 기본 디자인으로 대체한다.

| Semantic slide type | 생성 내용 | 우선 레이아웃 | 부족할 때 fallback |
| --- | --- | --- | --- |
| `cover` | 강의 제목, 과정·훈련 계획 요약 | 표지 레이아웃 | 기본 표지 |
| `objectives` | 학습목표 | 제목+본문 | 기본 글머리표 |
| `lesson` | 도입·전개·정리 교안 | 제목+본문 | 기본 글머리표 |
| `practice` | 실습 개요·절차·루브릭 | 제목+본문 또는 2단 | 기본 글머리표 |
| `assessment` | 평가 개요·객관식·수행평가 | 제목+본문 | 기본 글머리표 |
| `ncs_coverage` | NCS 수행준거 커버리지 | 제목+본문 | 기본 글머리표 |
| `sources` | 원천명·URL·license·page | 출처 레이아웃 | 기본 출처 슬라이드 |

자동 매핑은 원본 슬라이드의 제목·전체 문구, 표·차트 여부, 텍스트 영역 수와 면적을 분석한다. `Contents`, `Timeline`, `Quiz`, `Skills`, `References` 같은 신호를 역할별로 점수화하고, 표지 외 역할은 서로 다른 원본 디자인을 우선 배정한다. 명시적인 출처 디자인이 없으면 충분한 본문 공간을 가진 콘텐츠 디자인을 재사용한다. 사용자는 자동 결과를 semantic slide type별로 수정할 수 있다.

MVP 템플릿 제작 가이드:

- 표지·목차·본문·실습·평가·요약처럼 목적이 다른 예시 슬라이드를 준비하면 자동 매핑 정확도가 높아진다.
- 원본 슬라이드에는 제목과 내용을 교체할 수 있는 텍스트 상자를 각각 한 개 이상 둔다.
- 출처용 예시 슬라이드에는 `Sources` 또는 `References`처럼 역할을 식별할 수 있는 제목을 사용한다.
- 로고·배경·이미지·도형은 원본 슬라이드에 직접 배치해도 유지된다.
- 글꼴은 수신 환경에 설치된 글꼴을 사용하거나 기관 배포용 폰트를 별도 안내한다.

## 5. 백엔드 설계

### 5.1 저장 구조

Supabase Storage에 비공개 bucket `lessonpack-ppt-templates`를 만들고, Postgres에 템플릿 metadata를 저장한다. GCE Docker 컨테이너의 로컬 파일은 배포 교체 시 사라질 수 있으므로 영구 저장소로 사용하지 않는다.

```sql
create table lessonpack_ppt_templates (
  template_id text primary key,
  project_id text not null unique references lessonpack_projects(project_id),
  storage_path text not null unique,
  original_filename text not null,
  content_hash text not null,
  file_size_bytes bigint not null,
  source_slide_count integer not null,
  slide_width bigint not null,
  slide_height bigint not null,
  layout_manifest jsonb not null,
  layout_mapping jsonb not null,
  warnings jsonb not null,
  status text not null check (status = 'ready'),
  created_at timestamptz not null,
  updated_at timestamptz not null
);
```

- `layout_manifest`: 원본 슬라이드 또는 마스터 layout index, 이름, 역할 후보, 텍스트 수용량, placeholder 정보
- `layout_mapping`: semantic slide type과 선택된 layout index의 대응
- 프로젝트당 활성 템플릿은 하나만 허용한다. 새 파일 저장이 끝나면 이전 Storage object를 제거한다.
- export 응답의 `X-LessonPack-PPT-Template-Mode` 헤더로 `custom`, `default`, `default-fallback`을 구분한다.

### 5.2 API 계약

| Method | Endpoint | 역할 |
| --- | --- | --- |
| `POST` | `/api/projects/{project_id}/ppt-template` | `.pptx` 업로드, 안전성 검사, manifest 생성 |
| `GET` | `/api/projects/{project_id}/ppt-template` | 활성 템플릿 metadata와 매핑 조회 |
| `PUT` | `/api/projects/{project_id}/ppt-template/mapping` | 사용자가 고른 semantic layout mapping 저장 |
| `DELETE` | `/api/projects/{project_id}/ppt-template` | 활성 템플릿 연결 해제 및 storage 삭제 |
| `GET` | `/api/packages/{package_id}/export.pptx` | 프로젝트 활성 템플릿이 있으면 적용, 없으면 기본 export |

기존 다운로드 endpoint의 URL은 유지한다. 템플릿의 존재 여부는 프로젝트 및 export metadata로 해석하며, 클라이언트가 임의의 storage path를 전달하지 않게 한다.

### 5.3 Export 구현

1. 패키지의 프로젝트와 활성 `template_id`를 조회한다.
2. Storage에서 템플릿을 임시 경로로 내려받고 SHA-256을 다시 확인한다.
3. `python-pptx`의 `Presentation(template_path)`로 파일을 연다.
4. 원본 슬라이드의 역할·내용 수용량을 분석하고 semantic slide type별 자동 매핑을 계산한다. 기존에 마스터 레이아웃만 저장된 템플릿도 export 시 새 원본 디자인 매핑으로 자동 보정한다.
5. 매핑된 원본 슬라이드는 배경·이미지·도형과 내부 관계를 복제하되 외부 링크와 슬라이드 이동 링크는 제거한다. 마스터 레이아웃 매핑은 새 슬라이드를 생성한다.
6. 원본 샘플 문구를 제거하고 제목·본문·표에 검증된 패키지 텍스트를 넣는다. 여러 슬라이드에 반복되는 브랜드 문구는 유지한다.
7. 텍스트 영역의 개수·면적에 맞춰 내용을 분배하고, 작은 카드에는 요약문을 넣으며 긴 내용은 다음 슬라이드로 분할한다.
8. 제목과 본문 영역이 겹치면 본문을 제목 아래 가용 영역으로 재배치하고 글자 크기를 제한한다.
9. 마지막 `sources` 슬라이드에만 compact evidence를 배치한다.
10. 원본 donor 슬라이드를 제거하고 저장한 결과를 다시 열어 슬라이드 수·필수 제목·ZIP 구조를 검증한 뒤 다운로드한다.

`python-pptx`는 원본 슬라이드의 XML과 내부 이미지 관계를 복제하는 데 활용한다. SmartArt, 차트 데이터, 애니메이션, 전환 효과는 MVP 보존 대상이 아니며 차트가 포함된 원본 슬라이드는 자동 디자인 후보에서 제외한다.

## 6. 보안과 운영 제한

| 항목 | 기준 |
| --- | --- |
| 파일 형식 | `.pptx` 확장자, Office Open XML ZIP signature, `python-pptx` 열기 성공을 모두 확인 |
| 파일 크기 | 최초 기본값 25 MB, 운영 환경에서 설정값으로 조정 |
| 압축 공격 방지 | ZIP entry 수와 압축 해제 예상 크기 상한 검사 |
| 매크로 | `vbaProject.bin`이 포함된 파일 거부 |
| 외부 참조 | 외부 관계·원격 링크는 경고로 기록하고 export 본문에는 복사하지 않음 |
| 저장 권한 | 비공개 Storage bucket, 서버 service role만 원본 접근 |
| 수명 주기 | 프로젝트 삭제 또는 템플릿 교체 시 연결·storage object 동시 정리 |
| 관찰성 | 업로드·분석 오류와 export fallback을 서버 로그에 기록하고 응답 헤더로 적용 상태 전달 |

현재 MVP에는 계정·기관별 권한 모델이 없다. 공개 서비스로 확장하기 전에는 project ID만으로 템플릿에 접근할 수 없는 인증·인가 계층을 먼저 도입해야 한다.

## 7. 프론트엔드 설계

- `MaterialsStep`에 교재 업로드 카드와 구분되는 템플릿 전용 업로드 카드를 추가한다.
- 허용 형식은 `.pptx`만 표시하고, 교재 업로드의 `.txt/.md/.pdf` 허용 목록과 절대 공유하지 않는다.
- 서버 분석 결과에서 재사용 가능한 원본 디자인 수, 마스터 레이아웃 수와 mapping 상태를 표시한다.
- semantic slide type별 layout selector는 자동 매핑 성공 시 접힌 고급 설정으로 제공한다.
- selector는 `원본 슬라이드 디자인`과 `마스터 레이아웃`을 그룹으로 나누고 원본 항목에 슬라이드 번호를 표시한다.
- 템플릿 파일명, 교체, 제거, 기본 디자인 복귀를 명확한 상태로 제공한다.
- export 단계는 `기본 PPTX` 또는 `템플릿 적용 PPTX` 상태와 fallback 경고를 표시한다.

## 8. 단계별 구현 계획

| 단계 | 작업 | 완료 기준 |
| --- | --- | --- |
| 1 | migration, Storage bucket, Pydantic schema, template repository 구현 | 구현 완료 |
| 2 | PPTX 파일 검사와 layout manifest 추출 | 구현 완료 |
| 3 | 템플릿 업로드·mapping API와 UI 구현 | 구현 완료 |
| 4 | template-aware export service 구현 | 구현 완료 |
| 5 | fallback과 적용 상태 응답 추가 | 구현 완료 |
| 6 | 자동 검증 | 구현 완료, 전체 회귀 테스트로 최종 확인 |
| 7 | 실제 Supabase migration·기관 템플릿 시각 검증·GCE 배포 | 템플릿 3종 시각 검증 완료, migration·GCE 재배포 필요 |

## 9. 검증 프로토콜

### 자동 테스트

- 유효한 `.pptx` 업로드 후 manifest와 mapping 저장 검증
- `.ppt`, `.pptm`, 손상 ZIP, 매크로 포함 파일, 용량 초과 파일 거절 검증
- 템플릿 적용 export의 slide count, 제목, 역할별 원본 디자인, 다운로드 MIME 검증
- 템플릿 없는 기존 export 회귀 검증
- placeholder 없는 layout에서 텍스트 상자 fallback 검증
- 템플릿 교체 뒤 이전 template이 새 export에 사용되지 않는지 검증
- Storage 실패 시 기본 export 또는 명확한 오류 계약 검증

### 시각 검증

기관 템플릿 최소 3종(표준 제목+본문, 로고/배경 포함, 2단 레이아웃)을 사용한다. 각 결과를 PowerPoint 또는 LibreOffice로 열어 다음을 확인한다.

- 마스터 배경·로고·색상이 유지되는가
- 제목과 본문이 placeholder 범위를 벗어나지 않는가
- 제목과 본문 텍스트 상자가 서로 겹치지 않는가
- 긴 실습 절차와 출처가 분할되어 가독성을 유지하는가
- 마지막 출처 슬라이드에만 근거가 표시되는가
- 한국어 글꼴 대체로 의미가 훼손되지 않는가

### 2026-07-24 실제 템플릿 검증 결과

루트의 `template_1.pptx`, `template_2.pptx`, `template_3.pptx`를 동일한 17장 강의 패키지에 적용하고 PowerPoint로 전체 슬라이드를 렌더링했다.

| 템플릿 | 원본 슬라이드 | 역할별 원본 디자인 매핑(1부터 시작) | 샘플 문구 유입 | 텍스트 넘침 | 텍스트 겹침 | 결과 |
| --- | ---: | --- | ---: | ---: | ---: | --- |
| `template_1.pptx` | 14 | 표지 1, 목표 2, 교안 4, 실습 3, 평가 10, NCS 11, 출처 2 | 0건 | 0건 | 0건 | PASS |
| `template_2.pptx` | 11 | 표지 1, 목표 10, 교안 3, 실습 7, 평가 5, NCS 6, 출처 3 | 0건 | 0건 | 0건 | PASS |
| `template_3.pptx` | 10 | 표지 1, 목표 2, 교안 4, 실습 7, 평가 8, NCS 3, 출처 4 | 0건 | 0건 | 0건 | PASS |

각 결과는 17장 전체를 PowerPoint PNG로 렌더링했다. 원본 배경·도형·사진이 표지뿐 아니라 학습목표, 교안, 실습, 평가, NCS, 출처 슬라이드에도 유지됨을 확인했다. 원본 샘플 문구는 제거했고, `template_2`의 모든 슬라이드에 반복되는 브랜드 문구 `BASIC & SIMPLE PRESENTATION`만 의도적으로 유지했다. PowerPoint `TextFrame2` 기준 텍스트 넘침과 텍스트 상자 교차를 전체 슬라이드에서 검사해 모두 0건임을 확인했다.

## 10. 완료 조건과 후속 확장

MVP 완료 조건은 유효한 사용자 `.pptx` 3종에서 역할별 원본 슬라이드 디자인을 유지한 PPTX를 생성하고, 샘플 콘텐츠 유입·텍스트 넘침·텍스트 겹침 및 기존 기본 export 회귀 없이 자동 테스트와 시각 검증을 통과하는 것이다.

후속 확장 후보는 기관 공용 템플릿 라이브러리, 템플릿 썸네일 미리보기, 슬라이드별 사용자 편집, 이미지 placeholder 자동 삽입, PowerPoint Add-in 연동이다. 이들은 계정·권한·저장 정책이 정리된 뒤 별도 범위로 진행한다.

## 11. 관련 자료

- [현재 PPTX export 서비스](../../src/lectureops_agent/services/export_service.py)
- [FastAPI export endpoint](../../src/lectureops_agent/app/main.py)
- [구현명세서](01_구현명세서.md)
- [체크포인트 보완 기획서](06_체크포인트_보완_기획서.md)
- [python-pptx Quickstart](https://python-pptx.readthedocs.io/en/latest/user/quickstart.html)
