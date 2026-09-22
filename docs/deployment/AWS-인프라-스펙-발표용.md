# PiCare AWS 인프라 스펙 — 발표용

## 한 줄 요약

PiCare는 **EC2 웹 서버 + RDS MySQL 데이터베이스 + ECR 컨테이너 저장소 + RunPod GPU AI 서버**를 분리한 구조로 구성했다. 개발·시연 규모에 맞춰 비용을 낮추면서, DB와 AI 추론을 웹 서버와 분리해 확장 가능성을 확보했다.

## 아키텍처

```text
사용자 브라우저
     │ HTTP :80
     ▼
Elastic IP ── EC2 (Nginx + Django/Gunicorn, Docker)
                         │
                         ├── RDS MySQL (VPC 내부 :3306)
                         │
                         └── RunPod GPU AI API (HTTPS :8000)

개발 PC / GitHub Actions ── ECR ── EC2 이미지 Pull
```

## AWS 리소스 사양

| 영역 | 서비스 | 현재 구성 | 선택 이유 |
| --- | --- | --- | --- |
| 리전 | AWS Region | 서울 `ap-northeast-2` | 국내 사용자 대상, 낮은 네트워크 지연 |
| 웹 서버 | Amazon EC2 | `t3.small` | 개발·시연 규모의 Django 웹 서버에 적합 |
| EC2 CPU/메모리 | Amazon EC2 | 2 vCPU, 2 GiB RAM | Nginx와 Django 단일 Gunicorn worker 운영 기준 |
| 운영체제 | EC2 AMI | Ubuntu Server 24.04 LTS, x86_64 | Docker·AWS CLI·Python 운영 환경 |
| 웹 스토리지 | Amazon EBS | gp3 20 GiB, 기본 3,000 IOPS | 운영체제·Docker 이미지·로그 저장 |
| 고정 웹 주소 | Elastic IP | EC2에 연결한 고정 퍼블릭 IPv4 | 인스턴스 재시작 후에도 접속 주소 유지 |
| 데이터베이스 | Amazon RDS for MySQL | MySQL 8.4 | 사용자·게시글·추천 기록 영속화 |
| RDS 인스턴스 | Amazon RDS | `db.t4g.micro` | 2 vCPU, 1 GiB RAM의 개발/테스트용 DB |
| RDS 구성 | Amazon RDS | Single-AZ, gp3 20 GiB, 자동 백업 1일 | 시연 환경의 비용·복구 균형 |
| 컨테이너 저장소 | Amazon ECR | Private Repository, AES-256 암호화 | Django 웹 이미지를 안전하게 배포 |
| ECR 태그 정책 | Amazon ECR | Immutable | 같은 태그의 이미지 덮어쓰기 방지, 롤백 용이 |
| AI 추론 | RunPod GPU Pod | AWS 외부 GPU 서버, API 포트 8000 | GPU 모델·LoRA·RAG 색인을 웹 서버와 분리 |

## 네트워크 및 보안 구성

| 대상 | 인바운드 규칙 | 의미 |
| --- | --- | --- |
| EC2 보안 그룹 | HTTP 80: `0.0.0.0/0` | 누구나 웹 페이지 접근 가능 |
| EC2 보안 그룹 | SSH 22: 관리자 공인 IP `/32`만 | 관리자 접속 범위 제한 |
| RDS 보안 그룹 | MySQL 3306: **EC2 보안 그룹만** | DB는 EC2 앱에서만 접근 가능 |
| RDS 퍼블릭 액세스 | 비활성화 | 인터넷에서 DB 직접 접근 차단 |
| Django 웹 포트 | 8000 외부 비공개 | Nginx만 Django에 내부 연결 |

RDS 비밀번호, Django Secret Key, RunPod API Token, IAM Access Key, SSH PEM 키는 AWS 콘솔·EC2의 비밀 환경 파일에서만 관리하며 Git 저장소에는 포함하지 않는다.

## 배포 방식

```text
소스 코드 변경
  → Docker linux/amd64 이미지 빌드
  → Amazon ECR Private Repository Push
  → EC2가 IAM 역할로 이미지 Pull
  → Docker Compose로 Nginx + Django 재시작
  → /health/ 상태 확인
```

현재 CI/CD는 GitHub Actions에서 테스트 후 ECR에 불변 태그 이미지를 올리고, AWS Systems Manager(SSM)를 통해 EC2 릴리스를 실행하는 방식으로 준비되어 있다.

## 현재 사용하지 않은 AWS 서비스

| 서비스 | 현재 미사용 이유 | 향후 사용 시점 |
| --- | --- | --- |
| Amazon S3 | 사용자 업로드 파일·대용량 첨부 기능이 아직 없음 | 프로필 이미지, 첨부파일, 백업 파일 저장 추가 시 |
| Amazon CloudFront | 단일 EC2 시연 환경에서 CDN 캐시가 필요하지 않음 | 정적 파일 전송 최적화, 대규모 사용자, 도메인 기반 배포 시 |
| Application Load Balancer | EC2 한 대 구성 | EC2 다중화·오토스케일링·ACM HTTPS 종료 시 |
| Route 53 / ACM | 현재 Elastic IP 기반 HTTP 시연 환경 | 보유 도메인 연결 및 HTTPS 적용 시 |
| ElastiCache | 단일 웹 서버와 RDS로 충분 | 세션·캐시·비동기 작업 규모 증가 시 |

## 설계 판단

- 웹, DB, AI 추론을 분리해 GPU 작업이 웹 화면 응답을 막지 않게 했다.
- DB는 RDS의 사설 네트워크 접근으로 보호하고, EC2 보안 그룹만 MySQL 접속을 허용했다.
- ECR의 Immutable 태그를 사용해 배포 이미지 버전을 명확히 하고 이전 태그로 롤백할 수 있게 했다.
- 사용자 업로드가 없는 현재 범위에서는 S3·CloudFront를 제외해 구성과 비용을 줄였다.
- 현재는 시연용 HTTP 구성이다. 운영 확장 단계에서는 도메인, ACM 인증서, ALB, HTTPS, EBS 암호화를 우선 적용한다.

## 발표용 설명 문구

> PiCare는 EC2에서 웹 서비스와 사용자 기능을 제공하고, RDS에서 데이터를 안전하게 관리하며, GPU가 필요한 AI 추론은 RunPod으로 분리했습니다. 웹 서버는 t3.small, 데이터베이스는 db.t4g.micro를 사용해 개발·시연 규모에 적합한 비용 효율적 인프라를 구성했습니다. 또한 ECR 기반 컨테이너 배포 구조를 적용해 이미지 버전 관리와 롤백이 가능하도록 설계했습니다.

## 발표 시 함께 언급할 향후 확장 계획

1. 보유 도메인을 연결하고 ACM 인증서와 ALB를 사용해 HTTPS 적용
2. 사용자 업로드 파일을 S3로 이전
3. CloudFront로 정적 파일과 이미지 전송 가속
4. EC2 다중화 및 Auto Scaling
5. RDS Multi-AZ, 백업 보존 기간 확대, 모니터링·알림 적용
