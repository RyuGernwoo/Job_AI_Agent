# LessonPack AI Langfuse Trace 보완 검증 결과

## 0. 2026-07-23 최종 재검증

- smoke marker: `lessonpack-smoke-6cfc2a77d66f4423ad33dfe90fa5a8ea`
- provider: `litellm:gpt-4o-mini -> gemini/gemini-3.5-flash`
- observation type: `GENERATION`
- model: `gpt-4o-mini-2024-07-18`
- latency: 7.637초
- usage: input 51, output 376, total 427 tokens
- cost: 0.000233249999 USD
- Public API 탐지: 5번째 polling에서 성공

| 검사 | 결과 |
| --- | --- |
| trace name | PASS |
| Input | PASS |
| Output | PASS |
| model | PASS |
| latency | PASS |
| usage | PASS |
| cost | PASS |

Langfuse Observations API v2 기준 rich field가 모두 확인됐다. 같은 날 최종 실제 MVP 생성 검증도 3건 모두 `structured_output_applied=true`로 통과했다.

아래 내용은 2026-07-21 최초 보완 검증 기록이다.

- 최초 검증일: 2026-07-21
- 대상: LiteLLM 실제 호출 및 Langfuse Cloud JP OTEL 수집
- 판정: **PASS**

## 1. 발견된 문제

기존 trace는 OTEL 전송 자체는 성공했지만 LLM 호출이 끝난 뒤 별도 span을 생성했다. 이 때문에 Input/Output이 비어 있고 latency가 0초에 가깝게 표시되며, token usage와 cost가 수집되지 않았다. Trace·session 관련 속성도 Langfuse 공식 OTEL 이름이 아닌 사용자 정의 이름을 사용했다.

실제 재검증 과정에서는 다음 설정 문제도 확인했다.

- OpenAI JSON mode 요청에 JSON 반환 지시가 없어 smoke test가 HTTP 400으로 실패했다.
- `gemini-2.0-flash`가 종료되어 fallback 요청이 HTTP 404로 실패했다.
- LiteLLM의 Gemini 오류 traceback URL에 API key query 값이 포함될 수 있었다.

## 2. 반영 내용

- 실제 API 요청 시작·종료 시각을 OTEL span에 적용해 latency를 측정한다.
- `langfuse.trace.name`, `langfuse.session.id`, `langfuse.trace.tags`를 사용한다.
- observation type을 `generation`으로 명시한다.
- Input/Output 필드는 기본적으로 원문 대신 메시지 수, 문자 수, 완료 상태를 기록한다.
- 실제 응답 모델과 모델 파라미터를 기록한다.
- LiteLLM usage의 input/output/total token을 기록한다.
- LiteLLM 계산 비용을 `cost_details.total`로 기록한다.
- 실패 예외의 URL key와 주요 secret 값을 trace·진단 리포트 저장 전에 마스킹한다.
- OpenAI JSON mode용 system prompt를 보완한다.
- Gemini fallback을 안정 모델 `gemini/gemini-3.5-flash`로 변경한다.

## 3. 실제 검증 결과

검증 observation:

| 항목 | 결과 |
|---|---|
| Observation type | `GENERATION` |
| Observation ID | `abf33e544274ab92` |
| Trace ID | `ed33f689bda475601c4463c939e9e69e` |
| Trace name | smoke test별 고유 `lessonpack-ai-langfuse-smoke-*` |
| Session ID | smoke test별 고유 `lessonpack-ai-smoke-*` |
| 실제 모델 | `gpt-4o-mini-2024-07-18` |
| Latency | `9.084초` |
| Input | 존재, 원문 비수집 요약 |
| Output | 존재, 원문 비수집 요약 |
| Input tokens | `51` |
| Output tokens | `463` |
| Total tokens | `514` |
| Total cost | `$0.00028545` |

Langfuse Observations API v2의 rich field 자동 검사는 generation type, trace name, Input, Output, model, latency, usage, cost 전 항목에서 통과했으며 최종 스크립트 종료 코드는 `0`이었다.

`providedModelName`은 Langfuse v2 변환 결과에서 비어 있었지만 공식 OTEL 속성 `langfuse.observation.model.name`과 `gen_ai.response.model`은 raw metadata에 정상 수집되었다. 진단 스크립트는 공식 필드를 우선 사용하고, 비어 있으면 해당 OTEL metadata를 사용한다.

## 4. 재현 명령

```powershell
python scripts\check_langfuse_trace.py `
  --poll-seconds 120 `
  --poll-interval 5 `
  --output outputs\eval\langfuse_trace_rich.json
```

스크립트는 trace 존재 여부만 확인하지 않고 Input/Output, model, latency, usage, cost를 모두 검사한다. 하나라도 누락되면 종료 코드 1을 반환한다.

## 5. 운영 설정

기본 설정은 다음과 같다.

```dotenv
LESSONPACK_LITELLM_FALLBACK_MODELS=gemini/gemini-3.5-flash
LESSONPACK_LANGFUSE_CAPTURE_CONTENT=false
```

`LESSONPACK_LANGFUSE_CAPTURE_CONTENT=false`에서도 Input/Output 필드는 표시되지만 원문은 문자 수와 상태 정보로 대체된다. 교재 원문과 사용자 입력을 외부 Langfuse 프로젝트로 전송할 권한과 동의를 확인한 경우에만 `true`를 사용한다.

GitHub Secret `LESSONPACK_LITELLM_FALLBACK_MODELS`가 등록되어 있으면 workflow 기본값보다 우선한다. 기존 값이 남아 있다면 `gemini/gemini-3.5-flash`로 변경해야 한다.

## 6. 즉시 필요한 보안 조치

첫 실패 검증에서 LiteLLM traceback의 Gemini 요청 URL에 API key가 포함되었다. 코드에는 후속 오류 마스킹을 적용했지만 이미 출력된 key는 폐기하고 Google AI Studio에서 새 key를 발급한 뒤 로컬 `.env`, GitHub Secret, GCE 배포 환경을 갱신한다.
