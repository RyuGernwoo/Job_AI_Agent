# LessonPack AI 데이터셋 운영 문서

이 문서는 LessonPack AI MVP에서 사용하는 로컬 데이터셋의 역할, 생성 절차, 검증 기준을 정리합니다.

## 1. 데이터셋 목적

MVP 데이터셋은 직업훈련 강의 운영 보조 AI Agent가 다음 흐름을 실제 자료 기반으로 수행할 수 있는지 검증하기 위해 사용합니다.

- NCS 능력단위와 수업 주제 연결
- 교안, 실습, 평가 문항 생성을 위한 근거 chunk 검색
- 검색 결과 기반 생성 품질 평가
- 사람 평가 루브릭을 통한 HITL 검토

## 2. 디렉터리 역할

```text
data/
  raw/            # 로컬 원천 데이터, Git 미포함
  processed/      # 전처리 산출물, Git 미포함, 재생성 가능
  vector_store/   # Chroma 등 벡터 저장소, Git 미포함
  gold/           # 작은 합성 평가 fixture, Git 포함
  README_DATASET.md
```

## 3. Git 추적 정책

- `data/raw/`: PDF, MD, XLS 등 원천 자료를 보관합니다. 용량과 라이선스 이슈 때문에 Git에 포함하지 않습니다.
- `data/processed/`: `prepare_mvp_dataset.py`로 다시 만들 수 있는 산출물이므로 Git에 포함하지 않습니다.
- `data/vector_store/`: 로컬 인덱스와 임베딩 저장소이므로 Git에 포함하지 않습니다.
- `data/gold/`: 작고 재현 가능한 합성 평가 데이터입니다. 테스트와 검증 기준 공유를 위해 Git에 포함합니다.

## 4. 현재 MVP 데이터셋 구성

| 구분 | 파일 | 용도 |
| --- | --- | --- |
| 커리큘럼 샘플 | `data/raw/curriculum/curriculum_python_prompt_automation.yaml` | 차시 정보, 학습자 수준, 학습목표 정의 |
| NCS 요약 | `data/raw/ncs/ncs_application_sw_programming.yaml` | 능력단위, 수행준거, 지식·기술·태도 연결 |
| 실습 예시 | `data/raw/synthetic/practice_examples.yaml` | 임의 생성 실습 시나리오 seed |
| 검색 chunk | `data/processed/chunks.jsonl` | RAG 검색 입력 corpus |
| chunk 색인 | `data/processed/chunk_index.csv` | chunk 품질 점검과 사람이 읽는 색인 |
| 원천 매핑 | `data/processed/source_file_map.csv` | 원본 파일명과 정리된 파일명 추적 |
| 선별 자료 | `data/processed/selected_sources.yaml` | MVP에 실제 사용하는 자료 목록 |
| manifest | `data/processed/dataset_manifest.json` | 데이터셋 버전, count, 품질 기준 |
| 검색 Gold | `data/gold/retrieval_gold.jsonl` | 검색 평가용 query와 기대 chunk |
| 생성 Gold | `data/gold/generation_gold.yaml` | 교안·실습·평가 생성 평가 case |
| 사람 평가 | `data/gold/human_eval_rubric.yaml` | 수동 품질 검토 기준 |

## 5. 재생성 절차

원천 NCS 자료와 공개 문서 샘플이 `data/raw/materials/` 아래에 준비되어 있어야 합니다.

```powershell
python scripts\prepare_mvp_dataset.py
```

성공 시 `data/processed/`와 `data/gold/` 산출물이 갱신됩니다.

## 6. 검증 절차

전처리 산출물이 생성된 뒤 다음 명령으로 구조 검증을 수행합니다.

```powershell
python scripts\validate_mvp_dataset.py
```

리포트를 파일로 남기려면 다음과 같이 실행합니다.

```powershell
python scripts\validate_mvp_dataset.py --report outputs\eval\dataset_validation_report.json
```

검증 스크립트는 다음 항목을 확인합니다.

- 필수 파일 존재 여부
- chunk 필수 필드, 중복 ID, 비어 있는 본문 여부
- `chunk_index.csv`와 `chunks.jsonl`의 ID 일치 여부
- `retrieval_gold.jsonl`의 기대 chunk ID가 실제 chunk에 존재하는지 여부
- `generation_gold.yaml`의 source ID가 선별 자료에 존재하는지 여부
- `dataset_manifest.json`의 count와 실제 산출물 count 일치 여부
- manifest의 최소 품질 기준 충족 여부
- 사람 평가 루브릭의 필수 항목 존재 여부

오류가 하나라도 있으면 CLI 종료 코드는 `1`이 됩니다.

## 7. VectorStore 적재

전처리된 chunk를 현재 VectorStore 경계에 적재하려면 다음 명령을 실행합니다.

```powershell
python scripts\ingest_processed_dataset.py --query "Python 함수 return" --top-k 3
```

기본 VectorStore는 in-memory입니다. Chroma에 적재하려면 다음 환경변수를 설정한 뒤 같은 명령을 실행합니다.

```powershell
$env:LECTUREOPS_VECTOR_STORE="chroma"
$env:LECTUREOPS_CHROMA_PATH="data\vector_store\chroma"
$env:LECTUREOPS_CHROMA_COLLECTION="lessonpack_mvp"
python scripts\ingest_processed_dataset.py --query "Python 함수 return" --top-k 3
```

## 8. 검색 평가

retrieval Gold Set 기준 검색 품질은 다음 명령으로 평가합니다.

```powershell
python scripts\evaluate_retrieval.py --top-k 3 --min-hit-rate 1.0 --report outputs\eval\retrieval_report.json
```

주요 지표는 다음과 같습니다.

- `hit_rate`: 기대 chunk가 top-k 검색 결과에 하나 이상 포함된 질의 비율
- `mean_reciprocal_rank`: 첫 번째 정답 chunk 순위의 역수 평균
- `empty_result_count`: 검색 결과가 비어 있는 질의 수

품질 게이트가 필요하면 `--min-hit-rate`를 지정합니다.

```powershell
python scripts\evaluate_retrieval.py --top-k 3 --min-hit-rate 0.5
```

현재 MVP Gold Set 기준 baseline은 top-3 hit rate `1.0`, MRR `0.95`입니다.

## 9. 생성 평가

generation Gold Set 기준 생성 품질은 다음 명령으로 평가합니다.

```powershell
python scripts\evaluate_generation.py --min-case-pass-rate 1.0 --report outputs\eval\generation_report.json
```

주요 지표는 다음과 같습니다.

- `case_pass_rate`: 전체 generation case 중 모든 검증 항목을 통과한 case 비율
- `average_score`: 교안 섹션, 실습 필수 요소, 평가 문항 수, citation 검증 항목의 평균 점수
- `missing_practice_items`: 생성 결과에서 누락된 실습 필수 요소
- `missing_citation_items`: citation이 없거나 검색 chunk ID와 연결되지 않은 항목

현재 mock provider 기준 baseline은 case pass rate `1.0`, average score `1.0`입니다.

실제 LLM provider 실증 전에는 다음 명령으로 준비 상태를 확인합니다.

```powershell
python scripts\check_llm_provider.py --config config.yaml --require-real
```

실제 provider로 generation Gold Set을 평가할 때는 `LESSONPACK_CONFIG`와 API key 환경변수를 지정한 뒤 실행합니다.

```powershell
$env:LESSONPACK_CONFIG="config.yaml"
$env:LESSONPACK_HTTP_API_KEY="..."
python scripts\evaluate_generation.py --require-real-llm --min-case-pass-rate 1.0 --report outputs\eval\generation_real_llm_report.json
```

`--require-real-llm`은 mock provider가 사용되는 상황을 실패로 처리합니다.

## 10. 품질 기준

현재 MVP 기준은 다음과 같습니다.

- 최소 chunk 수: 30개
- 검색 Gold Set: 10개 이상
- 생성 Gold Case: 3개 이상
- 모든 Gold의 참조 ID는 실제 데이터셋에 존재해야 함
- NCS 자료는 출처와 교육 목적 활용 조건을 명시해야 함
- 검색 품질은 top-3 hit rate 1.0을 현재 Gold Set 기준으로 유지합니다.
- 생성 품질은 mock provider 기준 generation case pass rate 1.0을 유지합니다.
- 실제 LLM 실증 시에도 generation case pass rate 1.0을 목표로 하되, 실패 case는 사람 검토 대상으로 기록합니다.

## 11. 현재 한계와 보완 예정

- 원천 데이터 라이선스 검토는 문서화 수준이며, 자동 판정은 하지 않습니다.
- 실제 강사 검토 데이터는 아직 없습니다. MVP 실증 단계에서 3명 내외의 사용자 평가를 수집해야 합니다.
- 검색 평가는 metadata-aware keyword retrieval baseline입니다. 이후 실제 LLM 생성 품질과 citation coverage 평가로 확장합니다.
- 실제 LLM 생성 품질 평가는 `http_chat` provider 연결 후 같은 generation Gold Set으로 추가 수행해야 합니다.
