# PiCare Django Web App

`web_app`은 PiCare의 Django 프론트엔드와 웹 요청 경계를 담당한다. 화면에서 받은 값은
이 디렉터리에서 검증·표시용으로 변환한 뒤, 팀이 구현한 `src/` 도메인 서비스에 전달한다.
RAG, 제품 추천 정책, 명령어 검증, 문제 채점 로직을 템플릿이나 JavaScript에 복제하지 않는다.

## 실행

로컬 MySQL 및 회원가입 실행 방법은 [로컬 Django + MySQL 가이드](../docs/local-django-mysql-setup.md)를
따른다.

처음 clone한 팀원은 아래 한 명령으로 `.env` 생성, `.venv` 생성, 의존성 설치, Docker MySQL
기동, Django 마이그레이션을 순서대로 실행할 수 있다. 기존 `.env`와 Docker DB volume은 덮어쓰거나
삭제하지 않는다.

```bash
python scripts/init.py
```

새 `.env`가 없으면 이 스크립트는 로컬 개발용 비밀번호와 `DJANGO_SECRET_KEY`를 자동 생성한다.
생성된 값은 `.env`에만 저장되며 Git에 포함되지 않는다.

```bash
python web_app/manage.py migrate
python web_app/manage.py runserver 8001
```

개발 서버에서 PiCare CSS를 제공하려면 `.env`의 `DJANGO_DEBUG=true`가 필요하다.

## 요청 흐름

```text
브라우저 폼 / 템플릿
  → portal.views 또는 accounts.views
  → portal.services의 서비스 조립 함수
  → src/ 또는 streamlit_app/runtime.py의 팀 도메인 기능
  → 검증된 결과를 Django 템플릿 또는 JSON으로 반환
```

`portal.services`의 함수에는 `lru_cache`가 적용되어 있으므로, 무거운 RAG·추천 서비스는
각 Django 워커에서 한 번만 조립해 재사용한다.

## 화면과 팀 기능 연결

| 화면/URL | Django View | 호출 함수 | 팀 기능과 역할 |
|---|---|---|---|
| `/recommend/` | `recommend()` | `RecommendationFormInput.from_widget_values()` | Django 폼의 한국어 선택값을 추천 서비스의 표준 입력 계약으로 변환한다. |
| `/recommend/` | `recommend()` | `get_recommendation_service().answer_form()` | sLLM 조건 추출 → 제품 카탈로그 후보 선정 → Hybrid RAG 근거 검색 → 추천 답변을 처리한다. |
| `/qa/` | `qa()` | `get_qa_service().answer()` | 입력 안전성 검사, Hybrid RAG 검색, 인용 검증, 근거 기반 Q&A 답변 생성을 처리한다. |
| `/qa/` 출처 카드 | `_response_context()` | `get_citation_presenter().present()` | 팀 RAG 결과의 인용을 문서명·섹션·태그가 포함된 화면용 카드 데이터로 변환한다. |
| `/qa/` Mini Challenge | `qa()` | `get_challenge_service().start_inline()` | Q&A 인용의 `document_id`가 SSH 또는 OS 설치일 때만 검수 문제 1개를 시작한다. |
| `/api/qa/mini-challenge/submit` | `inline_challenge_submit_api()` | `ChallengeService.submit_inline()` | 서버에서 정답을 채점한 뒤에만 해설과 공식 근거를 반환한다. |
| `/lab/` | `lab()` | `CommandLabService.list_templates()` | 검수 완료된 명령 템플릿만 라이브러리에 표시한다. |
| `/lab/` | `lab()` | `CommandLabService.analyze()` | 직접 입력한 명령이 승인된 템플릿과 일치하는지 검사하고 분석한다. 실제 실행은 하지 않는다. |
| `/lab/` | `lab()` | `CommandLabService.compose()` | 허용된 편집 값만 반영해 명령을 재조합하고 근거·주의사항을 반환한다. |
| `/challenge/` | `challenge()` | `ChallengeService.start()` | 승인된 문제은행에서 3문제를 무작위로 시작한다. 최초 응답에는 정답·해설을 넣지 않는다. |
| `/challenge/` | `challenge()` | `ChallengeService.submit()` | 현재 문제만 서버에서 채점하고, 제출 후 해설·공식 근거를 반환한다. |
| `/health/` | `health()` | `get_runtime_readiness()` | `.env`, Chroma 색인 등 RAG 런타임의 최소 준비 상태를 확인한다. |

## 서비스 조립 함수

`portal/services.py`는 Django와 팀 도메인 코드의 유일한 조립 경계다.

| 함수 | 가져오는 기능 | 용도 |
|---|---|---|
| `get_runtime_readiness()` | `streamlit_app.runtime.check_runtime_readiness()` | 모델을 로드하지 않고 RAG 실행 준비 상태를 반환한다. |
| `get_qa_service()` | `streamlit_app.runtime.build_qa_service()` | `RagQaService`를 조립해 Q&A 화면에 제공한다. |
| `get_recommendation_service()` | `streamlit_app.runtime.build_recommendation_service()` | `RecommendationRagService`를 조립해 제품 추천 화면에 제공한다. |
| `get_citation_presenter()` | `src.presentation.load_citation_presenter()` | 인용 메타데이터의 표시 이름과 태그를 만든다. 실패해도 원본 인용은 표시한다. |
| `get_command_lab_service()` | `src.services.command_lab_service.CommandLabService` | 명령어 카탈로그 검증·분석·재조합 기능을 제공한다. |
| `get_challenge_service()` | `src.services.challenge_service.ChallengeService` | 문제은행 검증·문제 출제·채점 기능을 제공한다. |

## Django가 담당하는 부분

- `accounts/views.py`: Django 기본 `User`로 회원가입·로그인·POST 로그아웃을 처리한다.
- `portal/forms.py`: 사용자 입력 길이와 선택값을 검증한다.
- `portal/views.py`: HTTP 요청을 도메인 함수에 연결하고, 도메인 결과에서 브라우저에 허용할 필드만 선택한다.
- `templates/`: 표시만 담당한다. 정답·checksum·승인되지 않은 명령 정보는 템플릿에 전달하지 않는다.
- `settings.py`: MySQL, DB 세션, CSRF, 인증 설정을 담당한다.

## 안전 경계

- 명령어 실험실은 `CommandLabService`의 승인된 템플릿만 사용하며, 명령을 실행하지 않는다.
- 챌린지는 시작 HTML과 세션에 정답·해설을 저장하지 않고, 제출 후에만 반환한다.
- 공식 근거는 제목·섹션·URL만 화면에 전달하며 checksum은 노출하지 않는다.
- 로그아웃과 인라인 챌린지 제출은 CSRF 보호 POST 요청만 허용한다.

## 새 기능 연결 방법

1. `src/`에 도메인 서비스와 입력·출력 계약을 구현한다.
2. `portal/services.py`에 캐시된 조립 함수를 추가한다.
3. `portal/views.py`에서 폼 입력을 검증하고 서비스 함수를 호출한다.
4. 도메인 응답 전체가 아니라 화면에 필요한 안전한 필드만 context 또는 JSON으로 만든다.
5. 템플릿과 Django 테스트를 추가한다.

새 도메인 기능을 템플릿에서 직접 import하거나, JavaScript로 정답·비밀 검증값을 다루지 않는다.
