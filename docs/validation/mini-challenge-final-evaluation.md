# Dynamic Mini Challenge 최종 정량 평가

실행일: 2026-09-12  
결과 원본: `eval/results/quiz_generation_final.v1.json`  
사람 검수표: `eval/results/quiz_human_review.v1.csv`

## 1. 평가 환경

- 모델: `Qwen/Qwen3-4B-Instruct-2507`
- 실행: RunPod GPU, 4-bit CUDA
- 생성: `do_sample=False`, `max_new_tokens=1024`, fixture당 1회, Quiz retry 없음
- 범위: `ChatResponse → adapter → prompt → Qwen structured generation → parser → validation → finalizer → QuizResponse`
- RAG/Retriever/Chroma 호출: 0회
- 모델 cold load: 14.23초. 이 시간은 아래 warm generation latency와 분리했다.

이 문서의 메인 수치는 quote 후보 ID 선택 계약이 적용된 **최종 구현 버전**의 재실행 결과다. 512-token 구조 변경 전 수치와 섞지 않는다.

## 2. 평가 데이터셋 구성

`eval/quiz_generation_cases.v1.jsonl`의 고정 answer + evidence fixture 25건을 사용했다.

| Gold label | 건수 | 구성 |
| --- | ---: | --- |
| `available` | 20 | OS 설치 7, SSH/원격 접속 6, 카메라 7 |
| `insufficient_content` | 5 | evidence가 없는 근거 부족 사례 |

positive fixture는 각각 1문항 생성을 기대하도록 `max_questions=1`로 실행했다. 따라서 이 결과는 다문항 품질을 대표하지 않으며, 다문항은 별도 회귀 평가로 관리한다.

## 3. 지표 정의

- JSON Parse Success Rate: 실제 Qwen 호출 결과 중 draft JSON parser 통과 비율
- Structure/Evidence Validation Pass Rate: parser 통과 후 materialize된 문항 중 해당 validator 통과 비율
- Valid Quiz Provision Rate: gold `available` 20건 중 최종 `available`이며 기대 문항 수를 만족한 비율
- Supporting Quote Match Rate: 최종 문항의 quote가 연결된 evidence 원문에 15~240자 범위로 존재한 비율
- Duplicate Question Rate: 최종 반환 문항 중 finalizer 중복 기준을 위반한 문항 비율
- Latency: 모델 cold load를 제외한 `generate_structured()` 시간. p50/p95는 nearest-rank 방식이다.

`evidence_ids`의 allowlist 및 quote 후보 ID 매핑은 자동 검증 가능하다. 반면 “가장 적절한 evidence를 선택했는가”의 semantic Evidence F1은 독립 gold evidence annotation이 없으므로 **측정 불가**다.

## 4. 전체 정량 결과

| 지표 | 결과 |
| --- | ---: |
| JSON Parse Success Rate | 18/20 = **90.0%** |
| Structure Validation Pass Rate | 18/18 = **100.0%** |
| Evidence Validation Pass Rate | 18/18 = **100.0%** |
| Valid Quiz Provision Rate | 18/20 = **90.0%** |
| 평균 유효 문항 수 / positive case | **0.90개** |
| Allowlist Violation Rate | 0/18 = **0.0%** |
| Quote 후보 ID/원문 매핑 실패 | 0/18 = **0.0%** |
| Supporting Quote Match Rate | 18/18 = **100.0%** |
| 최종 반환 중복 문항 | 0/18 = **0.0%** |
| finalizer가 제거한 중복 후보 | 0건 |
| `generation_failed` Rate | 2/25 = **8.0%** |
| `insufficient_content` 응답 | 5/25 = **20.0%** |

구조/evidence 100%는 parser를 통과해 materialize된 문항을 분모로 한다. JSON parser가 거부한 2건은 구조/evidence 단계 이전에 종료됐다.

## 5. available / insufficient_content 분류 성능

`available`을 positive class로 계산했다. `generation_failed`는 `available`이 아닌 결과이므로 positive의 false negative로 처리했다.

| Gold \ Predicted | available | insufficient_content | generation_failed |
| --- | ---: | ---: | ---: |
| available (20) | 18 | 0 | 2 |
| insufficient_content (5) | 0 | 5 | 0 |

| 지표 | 결과 |
| --- | ---: |
| Available precision | **100.0%** (18/18) |
| Available recall | **90.0%** (18/20) |
| Available F1 | **94.7%** |
| Accuracy | **92.0%** (23/25) |
| Insufficient-content precision / recall / F1 | **100.0% / 100.0% / 100.0%** (5/5) |

근거 부족 5건은 quote 후보가 없어 LLM을 호출하지 않고 정상적으로 `insufficient_content`를 반환했다.

## 6. Generation / grounding 품질

- 최종 문항 18개는 모두 choice 4개, 단일 정답 ID, evidence ID 1개, quote 1개 조건을 통과했다.
- 모든 최종 quote는 서버가 candidate ID로부터 원문 그대로 materialize했으므로 quote 원문 불일치와 길이 위반은 0건이다.
- automatic grounding 지표는 **근거 ID·quote의 기계적 정합성**을 뜻한다. 선택지가 evidence 밖 지식을 요구하지 않는지, 정답이 실제로 하나로 명확한지는 사람 검수 없이는 확정할 수 없다.

## 7. Latency 결과

Qwen 호출 20건 기준:

| 지표 | 결과 |
| --- | ---: |
| 평균 structured generation | **10.73초** |
| p50 structured generation | **9.99초** |
| p95 structured generation | **15.43초** |
| 전체 25 fixture pipeline 평균 | **8.58초** |
| 전체 25 fixture pipeline p50 / p95 | **9.63초 / 15.43초** |

전체 pipeline 평균은 LLM 호출이 없는 `insufficient_content` 5건을 포함하므로 structured generation 평균보다 낮다.

## 8. 사람 검수가 필요한 항목

`eval/results/quiz_human_review.v1.csv`에는 실제 생성된 18문항을 아래 rubric으로 검수할 수 있게 준비했다. 나머지 positive 2건은 JSON parser 실패로 문항이 없어 검수 대상이 아니다.

| CSV 열 | 판정 기준 |
| --- | --- |
| `qa_relevance` | 질문이 fixture answer의 핵심 사실을 묻는가 |
| `single_clear_answer` | 선택지 중 정답이 하나로 명확한가 |
| `answer_directly_supported` | 정답과 해설이 supporting quote/evidence로 직접 뒷받침되는가 |
| `outside_knowledge_required` | 정답 또는 선택지 판단에 evidence 밖 지식이 필요한가 (`no`가 통과) |
| `choice_quality` | 오답 보기가 중복·모호·정답과 동치가 아닌가 |
| `duplicate_fact` | 다른 문항과 동일 사실을 반복하지 않는가 |

사람 검수 승인율, semantic evidence precision/recall/F1, 근거 밖 선택지 수, 정답 모호 문항 수는 아직 `pending`이며 수치를 임의로 기입하지 않는다.

## 9. 실패 케이스 분석

| case_id | 결과 | 직접 원인 |
| --- | --- | --- |
| `quiz-os-001` | generation_failed | choices 배열의 마지막 항목 뒤 trailing comma로 JSON parser 거부 |
| `quiz-camera-006` | generation_failed | choices 배열의 마지막 항목 뒤 trailing comma로 JSON parser 거부 |

두 실패 모두 token truncation, evidence allowlist, supporting quote 매핑, 구조 validator 문제는 아니었다. parser/validator는 완화하지 않았으며, 이 평가는 현행 엄격한 계약 기준의 결과다.

## 10. 포트폴리오에 사용할 수 있는 대표 수치

아래 수치는 조건을 함께 명시할 때 사용 가능하다.

- Qwen3-4B 4-bit 환경의 고정 grounded fixture 25건에서 **JSON 구조화 출력 성공률 90.0% (18/20 모델 호출)**
- parser 통과 문항 기준 **structure validation 및 evidence validation 통과율 100.0% (18/18)**
- gold positive 20건 기준 **검증된 Quiz 제공률 90.0% (18/20)**
- 최종 반환 문항 기준 **evidence allowlist 위반 0건, supporting quote 원문 매칭률 100.0% (18/18)**
- warm structured generation **평균 10.73초, p50 9.99초, p95 15.43초**

사람 검수 전에는 “선택지 품질 100%”나 “근거 밖 지식 0건”처럼 semantic 품질을 단정하는 수치는 사용하지 않는다.
