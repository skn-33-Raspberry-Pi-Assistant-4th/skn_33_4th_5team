# PiCare Command Lab 데이터 검증 가이드 — B 양원

## 목적

Command Lab이 사용하는 명령 카탈로그 100개의 **기술적 데이터 정합성**을 확인한다.
이 문서는 Mini Challenge 문제은행을 다루지 않으며, 실제 셸 명령을 실행하지 않는다.

## 확인 대상

- 명령 카탈로그: `data/products/command_catalog.json`
- 공식 근거 manifest: `document_pipeline/data/manifest_v3.json`
- 서비스 로직: `src/services/command_lab_service.py`

현재 기준 데이터는 전체 100개이며, `approved` 8개와 `draft` 92개로 구성된다.
`draft`는 서비스 화면·API에 노출되지 않는 후보 데이터이며, 이 검증만으로 공개 승인되지는 않는다.

## 실행

프로젝트 루트에서 프로젝트 가상환경을 사용한다.

```bash
.venv/bin/python -m src.services.command_lab_cli --audit

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
  "approved": 8,
  "draft": 92,
  "errors": []
}
```

테스트는 현재 `32 passed`가 기대값이다.

이 검증은 다음을 보장한다.

- 모든 명령의 `parts` 재조합 결과가 `canonical_command`와 일치한다.
- 편집 가능 입력값 계약이 명령 구성 요소와 일치한다.
- 근거 ID와 checksum이 현재 공식 manifest와 일치한다.
- 근거 문서가 공식 Raspberry Pi URL이고 승인 상태다.
- 모든 항목이 `display_only` 정책을 지키며, 승인 항목만 서비스에서 분석·재조합된다.

## 결과 보고 양식

```text
[B Command Lab 데이터 검증]
- audit: total=100, approved=8, draft=92, errors=[]
- tests: 32 passed
- 결론: 기술적 데이터 정합성 이상 없음 / 오류 항목: <없음 또는 template_id와 원인>
- 비고: draft 92개는 의미·주제·설명 검수 전이므로 사용자 공개 대상이 아님
```

`errors`가 하나라도 있거나 테스트가 실패하면, 해당 `template_id`와 오류 메시지를 공유하고
카탈로그 또는 공식 근거 연결을 수정한 뒤 같은 검증을 다시 실행한다.
