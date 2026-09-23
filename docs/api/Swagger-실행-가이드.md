# PiCare Swagger 실행·운영 가이드

> 대상: PiCare Django API 명세를 확인·시험하거나 AWS에 배포하는 팀원<br>
> 기준일: 2026-09-23<br>
> 현재 상태: **Swagger UI 구현 완료, Django 관리자 전용 접근**

## 1. 접속 주소

| 구분 | 경로 | 용도 | 권한 |
| --- | --- | --- | --- |
| Swagger UI | `/api/docs/` | API 목록, 요청, 응답 확인 | Django 관리자 |
| OpenAPI YAML | `/api/schema/` | Swagger UI가 읽는 OpenAPI 3.0.3 명세 | Django 관리자 |

로컬:

```text
http://127.0.0.1:8001/api/docs/
http://127.0.0.1:8001/api/schema/
```

AWS EC2:

```text
http://<EC2-공인-IP-또는-도메인>/api/docs/
http://<EC2-공인-IP-또는-도메인>/api/schema/
```

현재 팀 EC2 IP를 사용한 예시:

```text
http://3.35.142.194/api/docs/
```

EC2에 Elastic IP가 없으면 인스턴스 정지·재시작 후 공인 IP가 바뀐 수 있다. EC2 콘솔의 **공인 IPv4 주소**를 기준으로 접속한다.

> `/api/docs/runpod/`과 `/api/schema/runpod/`는 현재 구현된 경로가 아니다. Swagger는 AWS Django 웹 서버에서 제공하며, Django가 `AI_API_URL`과 `AI_API_TOKEN`으로 RunPod API를 호출한다.

## 2. 관련 파일

| 파일 | 역할 |
| --- | --- |
| [`docs/openapi/web-api.yaml`](../openapi/web-api.yaml) | OpenAPI 3.0.3 API 명세 |
| [`web_app/templates/portal/swagger_ui.html`](../../web_app/templates/portal/swagger_ui.html) | Swagger UI 화면·CSRF 처리 |
| [`web_app/portal/views.py`](../../web_app/portal/views.py) | YAML 응답·Swagger UI 렌더링·관리자 권한 |
| [`web_app/portal/urls.py`](../../web_app/portal/urls.py) | `/api/docs/`, `/api/schema/` URL 등록 |

Swagger UI는 `swagger-ui-dist` 5.21.0을 jsDelivr CDN에서 로드한다. API 명세가 정상인데 화면이 비어 있다면 브라우저의 `cdn.jsdelivr.net` 차단 여부를 확인한다.

## 3. 관리자 전용 접근

`/api/docs/`와 `/api/schema/`는 모두 `staff_member_required`로 보호한다.

1. 브라우저에서 `/api/docs/`를 연다.
2. 비로그인 상태에서 `/admin/login/?next=/api/docs/`로 이동한다.
3. `is_active=True`, `is_staff=True`인 계정으로 로그인한다.
4. 로그인 성공 후 Swagger UI로 돌아온다.

일반 회원은 PiCare에 로그인했더라도 `is_staff=False`면 Swagger에 접근할 수 없다. UI만 보호하고 YAML을 공개하지 않도록 두 함수 모두에 데코레이터를 적용한다.

```python
from django.contrib.admin.views.decorators import staff_member_required


@staff_member_required
@require_GET
def openapi_schema(request):
    ...


@staff_member_required
@require_GET
def swagger_docs(request):
    ...
```

## 4. 로컬 서버 실행

### macOS / Linux (Bash)

```bash
cd /path/to/skn_33_4th_5team
python3 scripts/init.py
source .venv/bin/activate
python web_app/manage.py check
python web_app/manage.py runserver 127.0.0.1:8001
```

### Windows (PowerShell)

```powershell
Set-Location '<저장소-경로>\skn_33_4th_5team'
py -3.12 scripts/init.py
.\.venv\Scripts\Activate.ps1
python web_app\manage.py check
python web_app\manage.py runserver 127.0.0.1:8001
```

`Starting development server at http://127.0.0.1:8001/`가 보이면 브라우저에서 `/api/docs/`를 연다. 서버를 종료할 때는 실행 중인 터미널에서 `Ctrl+C`를 누른다.

Swagger만 확인할 때는 RunPod GPU 모델을 실행할 필요가 없다. AI 작업 API를 실제 실행할 때는 RunPod가 준비되어야 한다.

## 5. 관리자 계정 생성

### 로컬 대화형 생성

```bash
python web_app/manage.py createsuperuser --username admin
```

비밀번호는 소스코드, `.env`, OpenAPI 예시, 문서에 기록하지 않는다.

### EC2 Docker 컨테이너

EC2 터미널에서 `createsuperuser`가 한글 입력 인코딩으로 `UnicodeDecodeError`를 내면 다음 방식으로 생성·갱신한다.

```bash
read -rsp "새 관리자 비밀번호: " PICARE_ADMIN_PASSWORD
echo

docker exec \
  -e PICARE_ADMIN_PASSWORD="$PICARE_ADMIN_PASSWORD" \
  picare-aws-web-1 \
  python web_app/manage.py shell -c '
import os
from django.contrib.auth import get_user_model

User = get_user_model()
user, created = User.objects.get_or_create(
    username="admin",
    defaults={"email": ""},
)
user.is_active = True
user.is_staff = True
user.is_superuser = True
user.set_password(os.environ["PICARE_ADMIN_PASSWORD"])
user.save()
print("admin created" if created else "admin updated")
'

unset PICARE_ADMIN_PASSWORD
```

`read -rsp` 후 비밀번호가 화면에 표시되지 않는 것이 정상이다. `PICARE_ADMIN_PASSWORD`라는 문자열을 비밀번호로 교체하지 않는다.

## 6. 관리자 권한 확인

### EC2 Docker

```bash
docker exec picare-aws-web-1 \
  python web_app/manage.py shell -c '
from django.contrib.auth import get_user_model
u = get_user_model().objects.get(username="admin")
print("username:", u.username)
print("is_active:", u.is_active)
print("is_staff:", u.is_staff)
print("is_superuser:", u.is_superuser)
'
```

예상 결과:

```text
username: admin
is_active: True
is_staff: True
is_superuser: True
```

계정은 RDS MySQL에 저장되므로 일반적인 웹 컨테이너 재배포 후에도 유지된다. DB를 교체·초기화한 경우에는 다시 생성해야 한다.

## 7. 접근 테스트

서버를 실행한 터미널은 열어 두고 다른 터미널에서 확인한다.

### macOS / Linux

```bash
curl -I http://127.0.0.1:8001/api/docs/
curl -I http://127.0.0.1:8001/api/schema/
```

### Windows PowerShell

```powershell
curl.exe -I http://127.0.0.1:8001/api/docs/
curl.exe -I http://127.0.0.1:8001/api/schema/
```

비로그인 상태의 정상 응답:

```text
HTTP/1.1 302 Found
Location: /admin/login/?next=/api/docs/
```

`302 Found`는 오류가 아니라 관리자 로그인으로 이동시키는 정상 응답이다. `/api/schema/`를 열었을 때 YAML이 텍스트로 나오거나 파일로 다운로드되는 것도 정상이다.

## 8. Swagger API 그룹

| 그룹 | 주요 기능 |
| --- | --- |
| Health | Django 웹 서버와 AI 연결 준비 상태 |
| Command Lab | 명령어 템플릿 조회, 분석, 조합 |
| AI Job | RunPod AI 작업 상태 조회, 취소 |
| Mini Challenge | Q&A 기반 미니 챌린지 생성, 조회, 취소, 채점 |

`Command Lab`은 명령어를 실제로 실행하지 않고 안전 규칙에 따라 분석한다. `AI Job`과 `Mini Challenge`는 브라우저 세션을 사용하므로 현재 세션이 만들지 않은 작업 ID는 조회할 수 없다. Mini Challenge 실행 전에 같은 세션에서 Q&A를 완료해야 한다.

## 9. Try it out과 CSRF

Swagger UI는 같은 출처의 Django 세션 쿠키를 사용한다. `POST` 요청 시 `requestInterceptor`가 `csrftoken` 쿠키를 `X-CSRFToken` 헤더에 넣는다.

1. 관리자로 로그인한다.
2. API를 펼친 뒤 **Try it out**을 누른다.
3. 파라미터 또는 JSON 본문을 입력한다.
4. **Execute**를 누르고 상태 코드와 응답을 확인한다.

`403 CSRF verification failed`가 나오면 관리자 로그인과 Swagger를 같은 호스트·포트에서 실행했는지, `csrftoken` 쿠키가 생성됐는지 확인한다.

## 10. GitHub Actions로 AWS 배포

Swagger 파일을 `main` 브랜치에 push하면 AWS CI/CD가 Docker 이미지를 빌드하고 EC2에 배포한다.

```bash
cd /path/to/skn_33_4th_5team

git add \
  docs/openapi/web-api.yaml \
  docs/api/Swagger-실행-가이드.md \
  web_app/portal/views.py \
  web_app/portal/urls.py \
  web_app/templates/portal/swagger_ui.html

git status --short
git commit -m "2026-09-23/최지흠/feat(main): 관리자 전용 Swagger API 문서 추가"
git push origin main
```

배포 확인:

1. GitHub **Actions → AWS CI/CD**를 연다.
2. `Test and validate deployment image`가 녹색 체크인지 확인한다.
3. `Publish and release to EC2`가 녹색 체크인지 확인한다.
4. 현재 EC2 공인 IP의 `/api/docs/`를 연다.

Swagger는 AWS 웹 컨테이너에 포함되므로 Swagger만 변경했다면 RunPod `git pull`·모델 재시작은 필요 없다.

## 11. EC2 접속 안 될 때 순서대로 확인

### 11.1 EC2 인스턴스와 IP

AWS 콘솔의 **EC2 → 인스턴스**에서 다음을 확인한다.

- 인스턴스 상태: `실행 중`
- 상태 검사: `2/2 통과`
- 현재 공인 IPv4: 브라우저에 입력한 IP와 일치

인스턴스가 정지됐다면 시작한 후 상태 검사가 통과할 때까지 기다린다.

### 11.2 EC2 내부의 Docker·Nginx

SSH 접속 후:

```bash
cd /opt/picare
docker compose -f deploy/compose.aws.yaml ps
docker logs picare-aws-web-1 --tail 100
docker logs picare-aws-nginx-1 --tail 100
curl -I http://127.0.0.1/
curl -I http://127.0.0.1/api/docs/
sudo ss -lntp | grep ':80'
```

`docker compose ps`에서 `web`, `nginx`가 모두 `Healthy`여야 한다. 내부 `curl` 도 실패하면 컨테이너 및 Nginx 문제다.

필요하면 최신 배포를 다시 실행한다.

```bash
cd /opt/picare
bash deploy/aws-release.sh <정상-이미지-태그> 415309297100 picare-web-kimqq
```

### 11.3 보안 그룹

EC2 내부 `curl` 은 성공하지만 다른 PC에서 접속하지 못하면 EC2 보안 그룹 인바운드 규칙을 확인한다.

| 유형 | 프로토콜 | 포트 | 소스 |
| --- | --- | --- | --- |
| HTTP | TCP | 80 | 팀 공인 IP 또는 필요한 범위 |
| SSH | TCP | 22 | 관리자 공인 IP |

`0.0.0.0/0`은 모든 인터넷 사용자에게 공개하므로 임시 테스트 외에는 팀 IP로 제한한다.

### 11.4 판별 기준

| 확인 결과 | 판단 |
| --- | --- |
| `/`, `/health/`, `/api/docs/` 모두 연결 불가 | Swagger 문제가 아니라 EC2·IP·Nginx·보안 그룹 문제 |
| `/`는 정상, `/api/docs/`만 404 | 최신 Swagger 코드가 미배포됐거나 URL 등록 누락 |
| `/api/docs/`가 500 | 템플릿·YAML 파일 누락 또는 Django 렌더링 오류 |
| `/api/docs/`가 302 로그인 이동 | 관리자 보호 정상 |
| 로그인 후 Swagger 200 | 전체 정상 |

## 12. 자주 발생하는 문제

| 증상 | 확인·해결 |
| --- | --- |
| `ERR_CONNECTION_REFUSED` | 로컬은 `runserver`, AWS는 EC2 실행·공인 IP·80번 포트·Nginx를 확인한다. |
| `/api/docs/` 404 | `portal/urls.py`와 GitHub Actions 최신 배포를 확인한다. |
| `/api/docs/` 500 | `web_app/templates/portal/swagger_ui.html`과 Django 로그를 확인한다. |
| `/api/schema/`가 다운로드됨 | YAML 응답이므로 정상이다. |
| 로그인 후에도 다시 로그인 화면 | 운영 DB의 계정인지, `is_active`, `is_staff`를 확인한다. |
| Swagger 화면이 비어 있음 | 브라우저 Network·Console에서 `cdn.jsdelivr.net`을 확인한다. |
| `POST` 403 | 같은 호스트에서 로그인했는지, `csrftoken`과 `X-CSRFToken`을 확인한다. |
| AI API 실패 | RunPod `/health/ready`, AWS `AI_API_URL`, `AI_API_TOKEN`을 값 노출 없이 확인한다. |

## 13. 보안 주의사항

- 관리자 비밀번호, `AI_API_TOKEN`, AWS Access Key, DB 비밀번호를 Git·OpenAPI 예시·스크린샷에 넣지 않는다.
- `http://<EC2-IP>`는 로그인 정보를 TLS로 암호화하지 않는다. 외부 운영 전에 도메인·HTTPS를 적용한다.
- HTTPS 전에는 EC2 보안 그룹의 80번 포트를 팀의 공인 IP로 제한하는 것을 권장한다.
- 이미 공유된 초기 관리자 비밀번호는 접속 확인 후 즉시 변경한다.

## 14. 최종 점검표

- [ ] `python web_app/manage.py check`가 성공한다.
- [ ] `/api/docs/`와 `/api/schema/`가 비로그인 상태에서 관리자 로그인으로 이동한다.
- [ ] 관리자 로그인 후 Swagger UI와 Schemas가 표시된다.
- [ ] Health, Command Lab, AI Job, Mini Challenge 그룹이 표시된다.
- [ ] GitHub Actions의 테스트와 EC2 배포가 모두 성공한다.
- [ ] EC2 인스턴스가 실행 중이고 현재 공인 IP가 일치한다.
- [ ] EC2의 `web`, `nginx` 컨테이너가 모두 `Healthy`다.
- [ ] 관리자 계정의 `is_active`, `is_staff`, `is_superuser`가 의도한 값이다.
- [ ] 관리자 정보와 API 토큰이 소스·문서·로그에 노출되지 않는다.
