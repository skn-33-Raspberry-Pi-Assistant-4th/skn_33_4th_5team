# Dynamic Mini Challenge MVP 검증 기록

실행일: 2026-09-12  
평가셋: `eval/quiz_generation_cases.v1.jsonl` (20건)  
실행 경로: 고정 `answer + evidence → Qwen → parser → validator → QuizResponse`

## 범위와 측정 원칙

- Commit 14 평가셋의 20개 fixture를 실제 Qwen으로 케이스당 1회씩 실행했다.
- 모델은 `Qwen/Qwen3-4B-Instruct-2507`, 4-bit CUDA, `do_sample=False`, retry 없음으로 실행했다.
- Retriever/Chroma는 호출하지 않았다.
- Commit 13의 짧은 smoke fixture 수치는 이 문서의 평가 수치에 섞지 않았다.
- 사람 검수는 아직 수행하지 않았으므로 사람 검수 지표는 `미측정`으로 남긴다.

## Initial evaluation — 개선 전

`generate_structured()`의 상한이 512 tokens이고, 기존 prompt를 사용한 초기 실행이다.

| 지표 | 실제 결과 | 상태 |
| --- | ---: | --- |
| JSON 통과율 | 5/20 (25.0%) | 보류 |
| 구조 통과율 | 0/0 (미측정) | 미측정 |
| evidence 정확성 | 0/0 (미측정) | 미측정 |
| 유효 문항 제공률 | 0/15 (0.0%) | 미달 |
| 평균 유효 문항 수 | 0.0개 | 미달 |
| allowlist 위반 | 0건 (후보 문항 없음) | 보류 |
| supporting quote 불일치 | 0건 (후보 문항 없음) | 보류 |
| generation_failed | 15건 | 기록 완료 |
| insufficient_content | 5건 | 기록 완료 |
| 평균 생성 시간 | 15.4초 | 기록 완료 |

positive 15건의 raw output 중 13건은 507~512 generated tokens에서 JSON이 닫히기 전에 끝났다. 나머지 2건은 각각 JSON 문법 오류와 `supporting_quotes` scalar schema 오류였다.

## Token budget evaluation — 1024 tokens 및 기존 prompt

이번 실행은 `generate_structured()`에만 1024 tokens 상한을 적용했다. 기존 Q&A `generate()`의 512 정책, parser, contracts, validation 규칙은 변경하지 않았다. prompt에는 기본 1문항, 독립 사실이 충분할 때만 추가 문항, `supporting_quotes` 배열 및 15~240자 연속 인용 조건을 명확히 추가했다.

| 지표 | 계산 기준 | 실제 결과 | 상태 |
| --- | --- | ---: | --- |
| JSON 통과율 | parser 통과 케이스 / 전체 케이스 | 20/20 (100.0%) | 통과 |
| 구조 통과율 | 구조 검증 통과 문항 / parser 통과 후보 문항 | 16/16 (100.0%) | 통과 |
| evidence 정확성 | evidence 검증 통과 문항 / parser 통과 후보 문항 | 10/16 (62.5%) | 미달 |
| allowlist 위반 | 허용되지 않은 evidence ID를 가진 후보 문항 수 | 0건 | 통과 |
| supporting quote 불일치 | evidence 원문과 매칭되지 않은 후보 문항 수 | 1건 | 미달 |
| supporting quote 길이 위반 | 정규화 후 15~240자 범위를 벗어난 후보 문항 수 | 5건 | 미달 |
| 유효 문항 제공률 | positive 15건 중 `available`이며 문항이 1개 이상인 케이스 | 9/15 (60.0%) | 미달 |
| 평균 유효 문항 수 | 최종 유효 문항 수 / positive 15건 | 10/15 = 0.67개 | 미달 |
| generation_failed | 최종 `generation_failed` 케이스 수 | 0건 | 통과 |
| insufficient_content | 최종 `insufficient_content` 케이스 수 | 11건 | 기록 완료 |
| 평균 생성 시간 | 20개 structured generation의 평균 | 11.2초 | 기록 완료 |

첫 케이스는 모델 lazy loading을 포함해 27.6초였고, 이후 19건의 평균 generation 시간은 10.4초였다. 가장 긴 출력도 787 generated tokens여서 1024 상한에서 truncation은 재발하지 않았다.

## Initial / token budget 비교

| 지표 | Initial | Token budget |
| --- | ---: | ---: |
| JSON parser 통과율 | 25.0% | 100.0% |
| 구조 통과율 | 미측정 (0/0) | 100.0% (16/16) |
| evidence 정확성 | 미측정 (0/0) | 62.5% (10/16) |
| 유효 문항 제공률 | 0.0% (0/15) | 60.0% (9/15) |
| 평균 유효 문항 수 | 0.00 | 0.67 |
| allowlist 위반 | 0건 (후보 없음) | 0건 |
| supporting quote 불일치 | 0건 (후보 없음) | 1건 |
| quote 길이 위반 | 미측정 | 5건 |
| generation_failed | 15건 | 0건 |
| insufficient_content | 5건 | 11건 |
| 평균 generation 시간 | 15.4초 | 11.2초 |

## Revised evaluation — supporting quote prompt 보완 후

동일 모델, 4-bit CUDA, `do_sample=False`, `max_new_tokens=1024`, 케이스당 1회, retry 없음, RAG 미호출 조건에서 supporting quote 지시만 보완해 다시 실행했다.

| 지표 | 계산 기준 | 실제 결과 | 상태 |
| --- | --- | ---: | --- |
| JSON 통과율 | parser 통과 케이스 / 전체 케이스 | 19/20 (95.0%) | 보류 |
| 구조 통과율 | 구조 검증 통과 문항 / parser 통과 후보 문항 | 12/13 (92.3%) | 보류 |
| evidence 정확성 | evidence 검증 통과 문항 / parser 통과 후보 문항 | 10/13 (76.9%) | 보류 |
| allowlist 위반 | 허용되지 않은 evidence ID를 가진 후보 문항 수 | 0건 | 통과 |
| supporting quote 불일치 | evidence 원문과 매칭되지 않은 후보 문항 수 | 1건 | 미달 |
| supporting quote 길이 위반 | 정규화 후 15~240자 범위를 벗어난 후보 문항 수 | 2건 | 보류 |
| 유효 문항 제공률 | positive 15건 중 `available`이며 문항이 1개 이상인 케이스 | 10/15 (66.7%) | 미달 |
| 평균 유효 문항 수 | 최종 유효 문항 수 / positive 15건 | 10/15 = 0.67개 | 미달 |
| generation_failed | 최종 `generation_failed` 케이스 수 | 1건 | 보류 |
| insufficient_content | 최종 `insufficient_content` 케이스 수 | 9건 | 기록 완료 |
| 평균 생성 시간 | 20개 structured generation의 평균 | 8.8초 | 기록 완료 |

### Token budget / quote prompt 비교

| 지표 | Token budget | Quote prompt |
| --- | ---: | ---: |
| JSON parser 통과율 | 100.0% | 95.0% |
| evidence 정확성 | 62.5% (10/16) | 76.9% (10/13) |
| quote 길이 위반 | 5건 | 2건 |
| quote 원문 불일치 | 1건 | 1건 |
| 유효 문항 제공률 | 60.0% | 66.7% |
| 평균 유효 문항 수 | 0.67 | 0.67 |
| allowlist 위반 | 0건 | 0건 |
| 평균 generation 시간 | 11.2초 | 8.8초 |

## Quote prompt evaluation의 남은 실패 유형

- quote 길이 초과: 2문항. 모델이 여전히 evidence 전체 또는 긴 문단을 복사했다.
- quote 원문 불일치: 1문항. 목록 원문을 인용하면서 일부 구두점을 생략해, 공백만 정규화하는 원문 포함 검증에서 탈락했다.
- 구조 오류: 카메라 1건에서 선택지 텍스트가 중복됐다.
- parser 오류: OS 1건에서 supporting quote 문자열 안에 제어 문자가 포함돼 JSON parser가 거부했다. truncation은 아니었다.
- 모델 자발적 `insufficient_content`: 카메라 positive 1건은 유효 JSON이지만 빈 문항으로 반환됐다.

이번 실행에서 1024 token truncation은 없었다. quote 품질 오류와 별도로 parser 오류 1건이 발생했지만, 이번 범위에서는 parser/validator를 완화하거나 자동 보정하지 않았다.

## 사람 검수 결과

| 지표 | 실제 결과 | 상태 |
| --- | --- | --- |
| 사람 검수 승인율 | 미측정 (`pending`) | 미측정 |
| 근거 밖 문제 수 | 미측정 | 미측정 |
| 정답 모호 문제 수 | 미측정 | 미측정 |

## MVP 기준 판정

| MVP 기준 | Quote prompt 결과 | 판정 |
| --- | ---: | --- |
| allowlist 위반 0건 | 0건 | 통과 |
| supporting quote 불일치 0건 | 1건 | 미달 |
| 근거 밖 문제 0건 목표 | 사람 검수 미측정 | 미측정 |
| 정답 모호 문항 0건 목표 | 사람 검수 미측정 | 미측정 |
| 유효 문항 제공률 70% 이상 | 66.7% | 미달 |
| 평균 문항 수 1개 이상 | 0.67개 | 미달 |

quote 지시 보완으로 길이 위반은 5건에서 2건으로 줄고 유효 문항 제공률은 60.0%에서 66.7%로 올랐다. 다만 현재 Commit 14 평가셋 기준 MVP는 **아직 통과하지 못했다**. 다음 개선은 validation 완화가 아니라, 짧은 원문 인용을 출력하는 행동을 더 안정화하는 별도 실험으로 판단해야 한다.
