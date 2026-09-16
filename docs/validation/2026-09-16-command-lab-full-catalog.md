# 2026-09-16 Command Lab 100개 전체 공개 검증

## 승인 근거

- 데이터 담당 A(최지흠)가 명령 카탈로그 100개의 최종 검수 완료와 사용 승인을 전달했다.
- 기존 승인 8개는 유지했다.
- 최초 draft 92개는 `data/products/command_review_ledger.json`의 데이터 담당자 일괄 승인으로 기록했다.
- B/C의 개별 검수 기록을 임의 생성하지 않았으며 기존 이중 검수 경로는 이후 개별 변경에 사용할 수 있다.

## 구현 내용

- 카탈로그 100개를 모두 `approved`로 동기화했다.
- 서비스의 주제 필터, 직접 분석, 구성 요소 설명, 입력값 변경, 재조합, 제품·Q&A·서랍 연결을 100개에 적용했다.
- 편집 가능한 URL·주소 템플릿은 `rtsp`, `tcp`, `udp` 같은 고정 형식을 유지하도록 검증한다.
- 직접 입력 분석은 먼저 정확히 같은 명령을 찾고, 이후 편집 가능 형식을 비교한다. 따라서 비슷한 VLC·ffplay 템플릿이 서로 잘못 선택되지 않는다.
- Django 명령어 라이브러리에 전체 개수, 주제별 개수와 명령·설명 검색을 추가했다.

## 성공 기준

```text
Command Lab audit: total=100, approved=100, draft=0, errors=[]
Review ledger: candidates=92, pending=0, approved_after_data_owner_review=92, errors=[]
```

모든 명령은 `execution_policy=display_only`이며 실제 셸 실행 기능은 없다.

## 검증 결과

- Command Lab 카탈로그·서비스·Streamlit·승인 원장: **40 passed**
- Django 포털 정식 테스트 러너: **42 passed**, system check 오류 0개
- Django API 직접 테스트: **12 passed**
- 전체 회귀 중 현재 변경과 관련된 실행 범위: **423 passed, 1 skipped, 3 deselected**

제외한 3건은 최신 main 자체의 로그인 후 이동 경로와 기존 테스트 기대값이 다른 2건,
로컬 환경에 `torch`가 없어 실행할 수 없는 CUDA Qwen smoke 1건이다. 이번 변경 파일과 겹치지 않는다.
