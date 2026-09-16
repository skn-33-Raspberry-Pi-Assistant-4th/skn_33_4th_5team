# PiCare Mini Challenge 데이터 검증 가이드 — C 나은

## 목적

Mini Challenge가 사용하는 문제은행 10개의 **문제·정답·공식 근거 연결과 서버 채점 안전성**을 확인한다.
이 문서는 Command Lab 명령 100개 카탈로그를 다루지 않으며, 실제 명령을 실행하지 않는다.

## 확인 대상

- 문제은행: `data/products/challenge_bank.json`
- 공식 근거 manifest: `document_pipeline/data/manifest_v3.json`
- 서비스 로직: `src/services/challenge_service.py`

현재 문제은행은 총 10문제다.

- `os_installation`: 5문제
- `remote_access`: 5문제
- 모든 문제: `approved`

## 실행

프로젝트 루트에서 프로젝트 가상환경을 사용한다.

```bash
.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_challenge_bank.py \
  tests/test_challenge_service.py
```

## 성공 기준

테스트는 현재 `5 passed`가 기대값이다.

이 검증은 다음을 보장한다.

- 각 문제의 선택지 4개, 정답 ID, 해설, 공식 근거 ID와 checksum이 일치한다.
- 승인된 문제와 승인된 공식 근거만 출제된다.
- 문제 시작 HTML과 브라우저 세션에 정답·해설이 노출되지 않는다.
- 제출 후 서버가 현재 문제만 채점하고, 그 뒤에 해설과 공식 근거를 반환한다.
- Q&A 인라인 문제는 지원 문서에 연결된 한 문제만 사용한다.

## 결과 보고 양식

```text
[C Mini Challenge 데이터 검증]
- question bank: total=10, os_installation=5, remote_access=5, approved=10
- tests: 5 passed
- 결론: 문제은행·근거·서버 채점 안전성 이상 없음 / 오류 항목: <없음 또는 question_id와 원인>
- 비고: Command Lab 명령 카탈로그 100개와는 별도 데이터·별도 서비스임
```

테스트가 실패하면 해당 `question_id`, 선택지·정답·근거 연결 중 문제가 난 지점을 공유하고,
문제은행 또는 근거 연결을 수정한 뒤 같은 검증을 다시 실행한다.
