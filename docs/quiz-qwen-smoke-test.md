# Qwen 기반 QuizGenerator smoke test 기록

실행일: 2026-09-12  
범위: 고정된 `QuizGenerationRequest`를 사용한
`answer + evidence → Qwen → parser → validator → QuizResponse` 경로

## 실행 환경

- RunPod NVIDIA A40 GPU, CUDA 사용 가능
- 모델: `Qwen/Qwen3-4B-Instruct-2507`
- 생성 경로: `HuggingFaceAnswerGenerator.generate_structured()`
- 4-bit loading, `do_sample=False`, 문항 생성 요청당 모델 호출 1회
- Chroma/Retriever 재호출 없음

## 케이스와 기준

- SSH 또는 OS 설치 근거를 사용한 고정 케이스 10건
- JSON parser 통과율 80% 이상
- evidence allowlist 위반 0건
- supporting quote 원문 매칭률 100%
- 유효 문항 1개 이상 생성 케이스 70% 이상

## 결과

| 측정 항목 | 결과 |
| --- | ---: |
| JSON parser 통과 | 10/10 (100%) |
| evidence allowlist 위반 | 0건 |
| supporting quote 원문 매칭 | 10/10 (100%) |
| 유효 문항 1개 이상 | 10/10 (100%) |
| 첫 케이스 시간 (모델 로딩 포함) | 22.8초 |
| 이후 9건 평균 생성 시간 | 10.2초 |
| 전체 평균 시간 | 11.5초 |

실패 케이스는 없었다. GPU smoke를 제외한 기존 unit test도 RunPod에서
`393 passed`로 통과했다.

## 재실행 전제

smoke test는 Chroma index가 없어도 실행할 수 있다. 전체 RAG 테스트는 현재
4차 `manifest_v3.json` 기준으로 Chroma index를 새로 생성한 뒤 별도로 진행한다.
