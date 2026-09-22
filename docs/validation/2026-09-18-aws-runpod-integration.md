# 2026-09-18 AWS–RunPod 통합 검증 기록

## 현재 검증 결과

| 항목 | 결과 | 근거 |
|---|---|---|
| 고정 작업 계약 | 통과 | `job_id`, `kind`, `payload` 이외 필드 거부, 동일 ID 재요청·충돌 검사 |
| 상태·취소·오류 모의 API | 통과 | 성공, 지연, 실패, 취소, 인증 실패와 재시작 시 작업 소실 흐름 |
| 기존 응답 계약 | 통과 | 완료된 Q&A/추천은 `ChatResponse`, 퀴즈는 `QuizResponse`로 재검증 |
| 문서·색인 정합성 | 통과 | 공식 문서 23개, manifest 381개, 색인 381개, manifest 체크섬 일치 |
| 제품·명령 카탈로그 | 통과 | 제품 5개, 승인된 명령 템플릿 100개 |
| LoRA 어댑터 | 실서버 확인 필요 | 로컬 저장소에는 운영 어댑터가 없으며 RunPod 영속 볼륨에서 검증해야 함 |
| 실제 RunPod GPU 추론 | 실서버 확인 필요 | Pod 주소와 접근 권한이 없는 로컬 검증 범위 밖 |
| 실제 AWS·MySQL·브라우저 | 실서버 확인 필요 | EC2 주소와 접근 권한이 없는 로컬 검증 범위 밖 |

검증된 manifest SHA-256은 `a7c8334cb03f5ce1b6e21feaa3bc52e0f45430adcb8ee548498b6d4a42022a96`, 명령 카탈로그 SHA-256은 `f6f586f5f54dfe9bb6974705045a5d9cc059eb086e1a51fbcefc735f7c510b05`다. 배포 시 값이 다르면 자산 버전이 달라진 것이므로 그대로 승인하지 않고 색인 metadata와 함께 다시 검토한다.

## 재현 명령

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
  tests/test_remote_ai_contract.py tests/test_deployment_assets.py

python scripts/verify_deployment_assets.py --target all --skip-adapter
```

명령은 프로젝트 가상환경의 Python(`.venv/bin/python`)으로 실행했다. RunPod API 기본 포트는 이미지·진입점·운영서 모두 `8000`이며 자산 검증기가 이 값을 확인한다. `AI_API_TOKEN`은 실제 서버와 모의 서버 모두 32자 이상이어야 한다.

`--skip-adapter` 결과는 CPU 로컬 검증 기록에만 해당한다. RunPod 인수 시에는 반드시 `--adapter-path`를 넘겨 실제 설정과 weight 파일을 확인한다.

## 최종 로컬 재검증

- Django 인증·화면 회귀: **80 tests passed** (`manage.py test`)
- RunPod 작업·배포 자산·기존 AI 서비스 회귀: **58 passed**
- AWS 클라이언트와 모의 RunPod HTTP 계약: **8 passed**
- `git diff --check`, Django `check`, `makemigrations --check`: 통과
- `verify_deployment_assets.py --target all --skip-adapter`: 문서 23개·청크 381개·제품 5개·명령 템플릿 100개 확인

실제 GPU 모델 로딩, LoRA weight, AWS EC2·MySQL·브라우저 검수는 해당 인프라 자격 증명이 준비된 뒤 운영서의 인수 절차로 수행한다.

## 실환경 인수 시 채울 증적

- 배포 Git commit과 AWS·RunPod 이미지 태그
- Pod ID를 노출하지 않은 `live`/`ready` 결과와 자산 검증 JSON
- Q&A·추천·퀴즈 각각의 job ID, 최종 상태, 소요 시간
- 실행 중 취소 후 다음 작업 성공 결과
- 다른 사용자·세션 접근 차단 결과
- RunPod 재시작 전후 진행 작업 만료 및 MySQL 저장 기록 유지 결과

운영 절차와 장애 복구 기준은 `docs/deployment/CI-CD-실행-설정-API-명세서.md`를 따른다.
