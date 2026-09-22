# 이전 배포 문서 보관함

이 폴더는 현재 운영 기준과 중복되거나 과거 인프라 가정을 전제로 한 배포 문서를 보관한다. 새 배포·복구·CI/CD 작업은 상위 폴더의 [CI/CD 실행·설정·API 명세서](../../deployment/CI-CD-실행-설정-API-명세서.md)를 기준으로 한다.

보관 문서는 과거 결정과 작업 이력을 참고할 때만 사용한다. 일부 문서는 현재 구성과 다를 수 있다. 예를 들어 현재 운영은 RDS MySQL, ECR, SSM 자동 배포를 사용하며, 과거 문서에는 Docker MySQL 선택지나 SSH 터널 중심 절차가 포함되어 있다.

| 문서 | 보관 이유 |
| --- | --- |
| `AWS-통합-설정-및-실행-가이드.md` | 통합 운영 문서와 중복 |
| `github-actions-cicd.md` | 통합 CI/CD 문서와 중복, 과거 테스트 기준 포함 |
| `초기설정가이드-AWS.md` | 과거 DB 선택지 포함 |
| `초기설정가이드-RUNPOD.md` | RunPod 초기 설정의 이전 절차 |
| `aws-runpod-operations.md` | SSH 터널 중심의 과거 운영 절차 |
| `picare-aws-rds-compose.md` | 수동 배포 절차의 이전 버전 |
