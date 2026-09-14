# Portal persistence model contract

`portal`은 Django 기본 `User`를 인증 주체로 사용한다. 소유자와 작성자는 이후 view가
클라이언트 입력이 아닌 인증된 `request.user`에서 결정한다.

## Relationships

- `UserProfile`은 `User`와 1:1이고, 현재는 사용자명·이메일을 중복 저장하지 않는다.
- `Post`는 한 명의 `author`가 작성하며, `Comment`와 `PostLike`는 각각 글과 사용자에 연결된다.
- `DrawerItem`과 `WrongNote`는 모두 한 명의 `owner`에게 속한다.
- 사용자 또는 글을 삭제하면 관련 프로필·게시물·댓글·추천·서랍·오답노트도 함께 삭제된다.

## JSON data preservation

`DrawerItem.payload`는 `CommandLabService.drawer_payload()`가 생성한 JSON을 변경 없이
저장한다. 현재 `schema_version`, `kind`, `template_id`, `catalog_version`, `values`,
`product_id`, `command_snapshot`, `command_checksum`, `evidence_ids`,
`evidence_checksums`를 포함하며 사용자 ID는 payload에 넣지 않는다.

`WrongNote`는 `QuizQuestion`의 `question_id`, `question`, `choices`,
`correct_choice_id`, `explanation`, `evidence_ids`, `supporting_quotes`와 사용자가 고른
`selected_choice_id`를 보존한다. 모든 생성 퀴즈는 저장하지 않으며, 사용자가 오답노트로
선택한 항목만 저장한다.

## Constraints and query support

- `PostLike(post, user)`는 데이터베이스 `UniqueConstraint`로 중복 추천을 차단한다.
- 시간순 조회, 작성자별 글·댓글·추천, 소유자별 서랍·오답노트 조회를 위한 복합 인덱스를 둔다.
- 별도 활동 로그나 퀴즈 시도 모델은 두지 않는다.
