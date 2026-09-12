# Dynamic Mini Challenge MVP 검증 기록

실행일: 2026-09-12  
평가셋: `eval/quiz_generation_cases.v1.jsonl` (20건)  
실행 경로: 고정 `answer + evidence → Qwen → parser → validator → QuizResponse`

## 범위와 측정 원칙

- Commit 14 평가셋의 20개 fixture를 실제 Qwen으로 케이스당 1회씩 실행했다.
- Qwen 모델은 `Qwen/Qwen3-4B-Instruct-2507`이며 `do_sample=False`, retry 없음으로 실행했다.
- Retriever/Chroma를 호출하지 않았다.
- 이 문서의 수치는 Commit 14 평가 실행 결과만 사용한다. Commit 13 smoke test 수치는 포함하지 않는다.
- 사람 검수는 아직 수행하지 않았으므로 사람 검수 지표는 `미측정`으로 남긴다.

## 자동 측정 결과

| 지표 | 계산 기준 | 실제 결과 | 상태 |
| --- | --- | ---: | --- |
| JSON 통과율 | parser 통과 케이스 / 전체 케이스 | 5/20 (25.0%) | 보류 |
| 구조 통과율 | 구조 검증 통과 문항 / parser 통과 후보 문항 | 0/0 (미측정) | 미측정 |
| evidence 정확성 | evidence 검증 통과 문항 / parser 통과 후보 문항 | 0/0 (미측정) | 미측정 |
| allowlist 위반 | 허용되지 않은 evidence ID를 가진 후보 문항 수 | 0건 (후보 0건) | 보류 |
| supporting quote 불일치 | evidence 원문과 매칭되지 않은 후보 문항 수 | 0건 (후보 0건) | 보류 |
| 유효 문항 제공률 | positive 15건 중 `available`이며 문항이 1개 이상인 케이스 | 0/15 (0.0%) | 미달 |
| 평균 문항 수 | 최종 유효 문항 수 / positive 15건 | 0.0개 | 미달 |
| 기대 상태 일치율 | positive=`available`, 부족 근거=`insufficient_content` 일치 케이스 / 전체 | 5/20 (25.0%) | 보류 |
| 평균 생성 시간 | 20개 structured generation의 평균 | 15.4초 | 기록 완료 |

`구조 통과율`과 `evidence 정확성`은 parser 통과 후 생성된 후보 문항이 있어야 계산할 수 있다. 이번 실행에서는 parser를 통과한 5건이 모두 `insufficient_content`였으므로 후보 문항이 없었고, 두 지표를 0%로 표기하지 않았다.

## 사람 검수 결과

| 지표 | 실제 결과 | 상태 |
| --- | --- | --- |
| 사람 검수 승인율 | 미측정 (`pending`) | 미측정 |
| 근거 밖 문제 수 | 미측정 | 미측정 |
| 정답 모호 문제 수 | 미측정 | 미측정 |

## 케이스별 요약과 실패 원인

- OS 설치 5건: 모두 `generation_failed` (parser 실패)
- SSH/원격 접속 5건: 모두 `generation_failed` (parser 실패)
- 카메라 설치 5건: 모두 `generation_failed` (parser 실패)
- 짧은 답변·근거 부족 5건: 모두 `insufficient_content`로 반환되어 기대 상태와 일치

따라서 이번 실행의 실패 원인은 positive 15건에서 구조화 JSON parser를 통과하지 못한 것이다. parser, prompt, validator 기준은 평가 통과를 위해 변경하지 않았다.

## MVP 기준 판정

| MVP 기준 | 결과 | 판정 |
| --- | ---: | --- |
| allowlist 위반 0건 | 0건, 단 후보 문항 0건 | 보류 |
| supporting quote 불일치 0건 | 0건, 단 후보 문항 0건 | 보류 |
| 근거 밖 문제 0건 목표 | 사람 검수 미측정 | 미측정 |
| 정답 모호 문항 0건 목표 | 사람 검수 미측정 | 미측정 |
| 유효 문항 제공률 70% 이상 | 0.0% | 미달 |
| 평균 문항 수 1개 이상 | 0.0개 | 미달 |

현재 Commit 14 평가셋 기준 MVP는 **통과하지 못했다**. 다음 평가 전에는 positive fixture의 raw 모델 출력이 parser에서 탈락한 원인을 분석하고, 별도의 사람 검수를 통해 근거 범위와 정답 명확성을 판정해야 한다.
