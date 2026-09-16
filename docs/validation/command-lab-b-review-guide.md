# PiCare Command Lab 데이터 검증 가이드 — B 양원

## 목적

Command Lab이 사용하는 명령 카탈로그 100개의 **기술적 데이터 정합성**을 확인한다.
이 문서는 Mini Challenge 문제은행을 다루지 않으며, 실제 셸 명령을 실행하지 않는다.

## 확인 대상

- 명령 카탈로그: `data/products/command_catalog.json`
- 공식 근거 manifest: `document_pipeline/data/manifest_v3.json`
- 서비스 로직: `src/services/command_lab_service.py`

현재 기준 데이터는 전체 100개이며 모두 `approved`다. 최초 draft 92개는 데이터 담당자의
최종 검수 완료·사용 승인 기록을 `command_review_ledger.json`에 남긴 뒤 공개 상태로 동기화했다.

## 실행

프로젝트 루트에서 프로젝트 가상환경을 사용한다.

```bash
.venv/bin/python -m src.services.command_lab_cli --audit
.venv/bin/python -m scripts.command_review --audit

.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_command_catalog.py \
  tests/test_command_lab_service.py \
  tests/test_command_lab_ui.py
```

## 성공 기준

audit 출력은 아래 상태여야 한다.

```json
{
  "total": 100,
  "approved": 100,
  "draft": 0,
  "errors": []
}
```

관련 테스트는 모두 통과해야 한다.

이 검증은 다음을 보장한다.

- 모든 명령의 `parts` 재조합 결과가 `canonical_command`와 일치한다.
- 편집 가능 입력값 계약이 명령 구성 요소와 일치한다.
- 근거 ID와 checksum이 현재 공식 manifest와 일치한다.
- 근거 문서가 공식 Raspberry Pi URL이고 승인 상태다.
- 모든 항목이 `display_only` 정책을 지키며, 100개 전체가 서비스에서 분석·재조합된다.
- 데이터 담당자 승인 범위와 카탈로그의 `reviewed_by`·`reviewed_at`이 일치한다.

## 결과 보고 양식

```text
[B Command Lab 데이터 검증]
- audit: total=100, approved=100, draft=0, errors=[]
- review ledger: candidates=92, approved_after_data_owner_review=92, errors=[]
- tests: all passed
- 결론: 기술적 데이터 정합성 이상 없음 / 오류 항목: <없음 또는 template_id와 원인>
- 비고: 모든 명령은 display-only이며 실제 셸에서 실행하지 않음
```

`errors`가 하나라도 있거나 테스트가 실패하면, 해당 `template_id`와 오류 메시지를 공유하고
카탈로그 또는 공식 근거 연결을 수정한 뒤 같은 검증을 다시 실행한다.
