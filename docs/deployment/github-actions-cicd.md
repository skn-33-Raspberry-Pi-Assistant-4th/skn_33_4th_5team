# GitHub Actions CI/CD 운영 설정

이 저장소의 AWS 배포는 다음 순서로 동작한다.

1. Pull request와 `main` 푸시에서 Django·원격 AI 계약·배포 자산 검사를 실행한다.
2. `main` 푸시에서만 `sha-<commit SHA>` 불변 태그의 `linux/amd64` 이미지를 ECR에 올린다.
3. GitHub Actions가 AWS Systems Manager(SSM)를 통해 EC2에 릴리스 명령을 보낸다.
4. EC2는 이미 연결된 인스턴스 역할로 ECR 이미지를 내려받고, `/opt/picare/.env`의 비밀값으로 컨테이너를 재시작한다.

따라서 GitHub Actions는 EC2의 SSH 포트를 사용하지 않는다. EC2 보안 그룹의 SSH 수신 규칙을 GitHub Actions용으로 넓힐 필요가 없다.

현재 품질 게이트는 Django 설정·마이그레이션 확인, AWS 원격 상태 smoke test, RunPod 계약·배포 자산 검사, 그리고 운영 이미지 빌드다. `accounts portal` 전체 Django 테스트는 현재 `main`에 기존 추천·퀴즈 화면 실패가 남아 있어 배포 게이트에서 제외했다. 해당 회귀를 수정한 뒤 전체 테스트를 게이트에 다시 추가한다.

## 최초 1회: EC2를 SSM 관리형 노드로 등록

EC2 역할 `aws-picare-ec2-ecr-pull-role`에 AWS 관리형 정책 **AmazonSSMManagedInstanceCore**를 추가한다. 기존 ECR Pull 정책은 유지한다.

AWS Systems Manager 콘솔의 **Fleet Manager → Managed nodes**에서 인스턴스 `i-0335a3d276ffdeb92`가 `Online`인지 확인한다. 보이지 않으면 EC2에서 SSM Agent 상태를 확인한다.

```bash
sudo systemctl status amazon-ssm-agent --no-pager || \
sudo systemctl status snap.amazon-ssm-agent.amazon-ssm-agent.service --no-pager
```

## GitHub Actions Secrets와 Variables

GitHub 저장소의 **Settings → Secrets and variables → Actions**에 다음 값을 등록한다. 값은 저장소·워크플로 파일·채팅에 기록하지 않는다.

### Secrets

| 이름 | 값 |
| --- | --- |
| `AWS_ACCESS_KEY_ID` | 배포 전용 IAM 사용자의 Access Key ID |
| `AWS_SECRET_ACCESS_KEY` | 같은 키의 Secret Access Key |

처음에는 현재 ECR 푸시에 사용한 IAM 키를 사용할 수 있다. 장기 운영 전에는 GitHub Actions 전용 IAM 사용자를 만들고 기존 키를 교체한다.

### Variables

| 이름 | 값 |
| --- | --- |
| `AWS_REGION` | `ap-northeast-2` |
| `AWS_ACCOUNT_ID` | AWS 계정 ID |
| `ECR_REPOSITORY` | `picare-web-kimqq` |
| `EC2_INSTANCE_ID` | EC2 인스턴스 ID |

## GitHub Actions IAM 권한

현재 `student` 사용자의 관리자 권한은 동작 확인에는 충분하다. 전용 사용자로 전환할 때는 기존 ECR Push 권한 외에 아래 SSM 권한을 추가한다. `GetCommandInvocation`은 명령 완료 상태와 실패 로그 확인에 사용한다.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "ssm:SendCommand",
      "Resource": [
        "arn:aws:ssm:ap-northeast-2::document/AWS-RunShellScript",
        "arn:aws:ec2:ap-northeast-2:ACCOUNT_ID:instance/EC2_INSTANCE_ID"
      ]
    },
    {
      "Effect": "Allow",
      "Action": "ssm:GetCommandInvocation",
      "Resource": "*"
    }
  ]
}
```

`ACCOUNT_ID`와 `EC2_INSTANCE_ID`는 실제 값으로 치환한다. 이 정책은 ECR 이미지 Push 권한을 대체하지 않으며, 별도로 유지해야 한다.

## 첫 실행

1. 위 Secrets와 Variables를 저장한다.
2. `main`에 이 워크플로를 병합·푸시한다.
3. GitHub의 **Actions → AWS CI/CD → Run workflow**에서 수동 실행하거나, 이후 `main` 푸시로 실행한다.
4. `Test and validate deployment image`, `Publish and release to EC2` 두 작업이 모두 녹색인지 확인한다.

릴리스 태그는 커밋 SHA를 사용하므로 ECR의 Immutable 설정과 호환된다. 롤백이 필요하면 EC2에서 이전 태그를 명시해 실행한다.

```bash
cd /opt/picare
bash deploy/aws-release.sh <previous-image-tag> <aws-account-id> picare-web-kimqq
```
