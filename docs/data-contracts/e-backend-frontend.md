# E 백엔드 · 프론트 화면 계약

## 공통 규칙

- 모든 마이페이지 데이터는 인증된 `request.user`만 기준으로 조회한다. URL이나 form으로 사용자 ID를 받지 않는다.
- 아래 GET 화면은 모두 로그인 필수다. 비로그인 요청은 `/accounts/login/?next=<현재 경로>`로 redirect된다.
- 목록의 선택적 query parameter는 `page`(양의 정수)뿐이다. 잘못된 값이나 범위를 벗어난 값은 Django `Paginator.get_page()`가 유효한 페이지로 처리한다.
- GET 조회 화면에는 form 필드가 없다. 삭제 버튼은 CSRF 토큰을 포함한 POST form으로만 제공한다.

## 마이페이지와 활동 목록

| 화면 / URL name | Method · 로그인 | context 변수 | 빈 상태 / 버튼 |
| --- | --- | --- | --- |
| `GET /mypage/` (`mypage`) | GET · 필수 | `member`(현재 User), `activity_counts`(`posts`, `comments`, `likes`, `drawer_items`, `wrong_notes`), `recent_posts`, `recent_comments`, `recent_likes`, `recent_drawer_items`, `recent_wrong_notes` (각 최대 5건) | 각 최근 목록은 비어 있으면 안내 문구를 표시한다. 회원정보 수정·전체 보기는 모두 GET 링크다. |
| `GET /mypage/posts/?page=` (`mypage_posts`) | GET · 필수 | `page_obj`: 현재 사용자가 작성한 `Post` 페이지. 각 항목은 `like_count`, `comment_count` 포함 | `작성한 게시글이 없습니다.`. 게시글 상세 버튼은 `GET community_post_detail`. |
| `GET /mypage/comments/?page=` (`mypage_comments`) | GET · 필수 | `page_obj`: 현재 사용자가 작성한 `Comment` 페이지. `comment.post`와 `comment.post.author`가 준비됨 | `작성한 댓글이 없습니다.`. 게시글 제목/버튼은 `GET community_post_detail`. |
| `GET /mypage/likes/?page=` (`mypage_likes`) | GET · 필수 | `page_obj`: 현재 사용자의 `PostLike` 페이지. `like.post`, `like.post.author`가 준비됨 | `추천한 게시글이 없습니다.`. 게시글 버튼은 `GET community_post_detail`. |
| `GET /drawer/?page=` (`drawer_list`) | GET · 필수 | 기존 `items`와 `page_obj`: 현재 사용자의 `DrawerItem` 페이지 | `저장한 명령어 결과가 없습니다.`. 상세는 `GET drawer_detail`, 삭제는 CSRF `POST drawer_delete`. |
| `GET /wrong-notes/?page=` (`wrong_note_list`) | GET · 필수 | 기존 `notes`와 `page_obj`: 현재 사용자의 `WrongNote` 페이지 | `저장한 오답노트가 없습니다.`. 상세는 `GET wrong_note_detail`, 삭제는 CSRF `POST wrong_note_delete`. |

`page_obj`는 Django `Page` 객체다. `page_obj.object_list`, `page_obj.number`, `page_obj.paginator.num_pages`, `page_obj.has_previous`, `page_obj.has_next`를 사용한다. 현재 페이지당 항목 수는 10개다.

## 관련 기존 화면과 HTTP method

| 동작 | URL name | method | form 필드 |
| --- | --- | --- |
| 회원정보 수정 화면 이동 | `profile_edit` | GET | 없음 |
| 회원정보 저장 | `profile_edit` | POST | `username`, `email` |
| 게시글 상세 | `community_post_detail` | GET | 없음 |
| 서랍장 상세 | `drawer_detail` | GET | 없음 |
| 서랍장 삭제 | `drawer_delete` | POST | CSRF token |
| 오답노트 상세 | `wrong_note_detail` | GET | 없음 |
| 오답노트 삭제 | `wrong_note_delete` | POST | CSRF token |

목록·상세·삭제 조회는 모두 소유자 조건을 포함한다. 다른 회원의 개인 항목 ID를 직접 요청하면 상세와 삭제는 404가 반환된다.
