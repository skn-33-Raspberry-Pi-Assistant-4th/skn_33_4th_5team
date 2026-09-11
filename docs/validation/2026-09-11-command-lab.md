# 2026-09-11 B 명령어 실험실 검증

- 시작 브랜치: `origin/fix/dev`, commit `17c0f53aaf85969fae9f289a5702ee045c2bc1bd`
- 작업 브랜치: `fix/dev-labatory`
- A 자료: 명령어 100개(approved 8, draft 92), 챌린지 10개
- 공식 원문 commit: `75331a79fbf32d2403b7547729ddccf553873b09`

## 데이터 및 검색

초기 로컬 manifest는 18문서·270청크라 추가된 근거 ID를 찾지 못했다.
고정 원문에서 23문서·381청크를 재생성한 뒤 A 명령·챌린지 테스트 3개가 통과했다.
명령 카탈로그 보완 후 `python -m src.services.command_lab_cli --audit` 결과는
`total=100, approved=8, draft=92, errors=[]`다.

E5 (`intfloat/multilingual-e5-base`)로 381청크를 Chroma `rpi_official`에 색인했다.
실제 색인 metadata는 다음과 같다.

```json
{
  "manifest_checksum": "sha256:67ccf79a304034bacde3c479804b59446d00532103a367ec367fba1e3d74fffb",
  "indexed_at": "2026-09-11T02:05:40.774334+00:00",
  "indexed_chunk_count": 381
}
```

같은 고정 원문으로 재생성해도 수집 시각 등으로 파일 checksum은 달라질 수 있다.
재생성 후 반드시 해당 manifest와 색인을 함께 사용한다.

실제 Hybrid QA CLI에 `Raspberry Pi에서 SSH를 활성화하려면?`을 입력했다.
`status=answered`, 근거 5개, `citation_validation=passed`,
`citation_repair=not_needed`를 확인했다. 답변 생성은 `template`이며 Qwen 추론 측정이 아니다.

## 자동 검증

```bash
python -m pytest tests -q --tb=short
```

전체 결과: **301 passed, 1 skipped**. Windows symlink 권한이 필요한 기존 테스트 1건이 제외됐다.
새 실험실 테스트 30개는 승인 항목 제한, 전체 승인 명령 왕복 분석, SSH 값 변경,
입력 오류·명령 삽입 차단, 근거 변경·누락 차단, 제품 ID 검증, 서랍 복원 시 변경 탐지,
실제 Streamlit AppTest의 편집·서랍·Q&A 이동을 포함한다.

추가 문서를 연결하며 발견된 한국어 출처 라벨 누락을 수정했다.
로컬 `.env`가 있는 상태에서도 설정 단위 테스트가 독립적으로 실행되도록
테스트 fixture의 미디어·거리 환경변수를 초기화했다.

## 범위 및 한계

- 로컬 실험실: `http://127.0.0.1:8511/?page=lab`
- 명령 분석은 등록된 승인 템플릿에 한정하며 실제 쉘 명령을 실행하지 않는다.
- 92개 draft의 의미 검수·공개 승인은 이번 구현에서 수행하지 않았다.
- E의 회원 DB·Django 프로젝트가 아직 저장소에 없어 서랍 영구 저장 대신 서비스 계약과 임시 UI를 제공한다.
- 기존 추천 서비스 호출 규격은 유지한다. Qwen/LoRA 모델 정확도·GPU 성능은 이번에 측정하지 않았다.
- ID 추가에 따른 QLoRA 재학습은 수행하지 않았다. 필요한 E5 임베딩 재색인은 완료했다.

상세 실행·E/D 인수인계 규격은 `docs/data-contracts/command-lab.md`를 참고한다.
