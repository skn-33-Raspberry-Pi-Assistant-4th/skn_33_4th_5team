"""Authentication flow tests for the Django presentation layer."""

import json
import uuid
from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from unittest.mock import Mock, patch

from .models import Comment, DrawerItem, Post, PostLike, QuestionRecord, UserProfile, WrongNote
from src.contracts import ChatCitation, ChatResponse, QuizChoice, QuizQuestion, QuizResponse
from src.services.command_lab_service import CommandLabError, CommandLabService


class AccountFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="existing_user",
            email="existing@example.com",
            password="ExistingPass123!",
        )

    def test_signup_creates_and_authenticates_user(self):
        response = self.client.post(
            reverse("accounts:signup"),
            {
                "username": "new_user",
                "email": "new@example.com",
                "password1": "SignupPass123!",
                "password2": "SignupPass123!",
            },
        )

        self.assertRedirects(response, reverse("about"))
        user = get_user_model().objects.get(username="new_user")
        self.assertEqual(user.email, "new@example.com")
        self.assertTrue(user.check_password("SignupPass123!"))
        self.assertEqual(self.client.get(reverse("profile_edit")).status_code, 200)

    def test_signup_rejects_invalid_password(self):
        response = self.client.post(
            reverse("accounts:signup"),
            {
                "username": "invalid_password_user",
                "email": "invalid@example.com",
                "password1": "short",
                "password2": "short",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("password2", response.context["form"].errors)
        self.assertFalse(get_user_model().objects.filter(username="invalid_password_user").exists())

    def test_signup_requires_csrf_token(self):
        csrf_client = Client(enforce_csrf_checks=True)
        response = csrf_client.post(
            reverse("accounts:signup"),
            {
                "username": "csrf_user",
                "email": "csrf@example.com",
                "password1": "CsrfPass123!",
                "password2": "CsrfPass123!",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(get_user_model().objects.filter(username="csrf_user").exists())

    def test_signup_rejects_duplicate_username(self):
        response = self.client.post(
            reverse("accounts:signup"),
            {
                "username": self.user.username,
                "email": "another@example.com",
                "password1": "AnotherPass123!",
                "password2": "AnotherPass123!",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("username", response.context["form"].errors)
        self.assertEqual(get_user_model().objects.filter(username=self.user.username).count(), 1)

    def test_login_succeeds_with_valid_credentials(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": self.user.username, "password": "ExistingPass123!"},
        )

        self.assertRedirects(response, reverse("about"))
        self.assertEqual(self.client.get(reverse("profile_edit")).status_code, 200)

    def test_login_rejects_invalid_credentials(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": self.user.username, "password": "wrong-password"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].non_field_errors())

    def test_logout_requires_post_and_ends_session(self):
        self.client.force_login(self.user)

        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        response = self.client.post(reverse("accounts:logout"))

        self.assertRedirects(response, reverse("about"))
        protected_response = self.client.get(reverse("profile_edit"))
        self.assertRedirects(protected_response, f"{reverse('accounts:login')}?next={reverse('profile_edit')}")

    def test_profile_edit_updates_only_basic_account_fields(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("profile_edit"),
            {"username": "updated_user", "email": "updated@example.com"},
        )

        self.assertRedirects(response, reverse("profile_edit"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "updated_user")
        self.assertEqual(self.user.email, "updated@example.com")
        self.assertTrue(self.user.check_password("ExistingPass123!"))

    def test_profile_edit_allows_current_users_email_case_insensitively(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("profile_edit"),
            {"username": self.user.username, "email": "EXISTING@EXAMPLE.COM"},
        )

        self.assertRedirects(response, reverse("profile_edit"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "existing@example.com")

    def test_profile_edit_rejects_another_users_email_case_insensitively(self):
        get_user_model().objects.create_user(
            username="another_user",
            email="another@example.com",
            password="AnotherPass123!",
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("profile_edit"),
            {"username": "changed_user", "email": "ANOTHER@EXAMPLE.COM"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["form"].errors)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "existing_user")
        self.assertEqual(self.user.email, "existing@example.com")

    def test_profile_edit_redirects_anonymous_users_to_login(self):
        response = self.client.get(reverse("profile_edit"))

        self.assertRedirects(response, f"{reverse('accounts:login')}?next={reverse('profile_edit')}")


class PortalModelTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username="model_owner",
            email="owner@example.com",
            password="OwnerPass123!",
        )
        self.author = get_user_model().objects.create_user(
            username="post_author",
            email="author@example.com",
            password="AuthorPass123!",
        )

    def test_model_relationships_and_string_representations(self):
        profile = UserProfile.objects.create(user=self.owner)
        post = Post.objects.create(author=self.author, title="SSH 설정", content="공식 문서를 확인합니다.")
        comment = Comment.objects.create(post=post, author=self.owner, content="도움이 됐습니다.")
        like = PostLike.objects.create(post=post, user=self.owner)

        self.assertEqual(self.owner.profile, profile)
        self.assertEqual(list(self.author.posts.all()), [post])
        self.assertEqual(list(post.comments.all()), [comment])
        self.assertEqual(list(post.likes.all()), [like])
        self.assertEqual(str(post), "SSH 설정")
        self.assertIn(str(post.pk), str(comment))
        self.assertIn(self.owner.username, str(profile))
        self.assertIn(self.owner.username, str(like))

    def test_post_like_unique_constraint_blocks_duplicates(self):
        post = Post.objects.create(author=self.author, title="게시글", content="내용")
        PostLike.objects.create(post=post, user=self.owner)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PostLike.objects.create(post=post, user=self.owner)

        self.assertEqual(PostLike.objects.filter(post=post, user=self.owner).count(), 1)

    def test_json_fields_store_and_restore_contract_payloads(self):
        drawer_payload = {
            "schema_version": "1.0.0",
            "kind": "command_lab",
            "template_id": "cmd-remote-access-004",
            "catalog_version": "2026-09-11-command-lab-v2.1",
            "values": {"part-02": "pi@host"},
            "product_id": "raspberry-pi-5",
            "command_snapshot": "ssh pi@host",
            "command_checksum": "sha256:example",
            "evidence_ids": ["rpi-doc-remote-access-ssh-001"],
            "evidence_checksums": ["sha256:evidence"],
        }
        choices = [
            {"id": "A", "text": "기본적으로 비활성화"},
            {"id": "B", "text": "기본적으로 활성화"},
            {"id": "C", "text": "설치 중에만 활성화"},
            {"id": "D", "text": "네트워크 연결 시에만 활성화"},
        ]
        drawer = DrawerItem.objects.create(
            owner=self.owner,
            title="SSH 원격 접속",
            kind=drawer_payload["kind"],
            payload=drawer_payload,
        )
        wrong_note = WrongNote.objects.create(
            owner=self.owner,
            question_id="generated_001",
            question="Raspberry Pi OS에서 SSH의 기본 상태는 무엇인가요?",
            choices=choices,
            selected_choice_id="B",
            correct_choice_id="A",
            explanation="SSH는 기본적으로 비활성화되어 있습니다.",
            evidence_ids=["C1"],
            supporting_quotes=["SSH is disabled by default on Raspberry Pi OS."],
        )
        qa_record = QuestionRecord.objects.create(
            owner=self.owner,
            request_id="qa-model-test-001",
            title="SSH 설정 질문",
            question="SSH를 어떻게 설정하나요?",
            answer="공식 문서를 확인해 설정하세요.",
            status="answered",
            response_payload={"schema_version": "1.2.0", "answer": "공식 문서를 확인해 설정하세요."},
        )

        drawer.refresh_from_db()
        wrong_note.refresh_from_db()
        self.assertEqual(drawer.payload, drawer_payload)
        self.assertEqual(wrong_note.choices, choices)
        self.assertEqual(wrong_note.evidence_ids, ["C1"])
        self.assertEqual(wrong_note.supporting_quotes, ["SSH is disabled by default on Raspberry Pi OS."])
        self.assertEqual(qa_record.response_payload["schema_version"], "1.2.0")
        self.assertIn(self.owner.username, str(drawer))
        self.assertIn("generated_001", str(wrong_note))
        self.assertIn(self.owner.username, str(qa_record))

    def test_cascade_deletes_post_children_and_user_owned_records(self):
        profile = UserProfile.objects.create(user=self.owner)
        post = Post.objects.create(author=self.author, title="삭제 대상", content="내용")
        comment = Comment.objects.create(post=post, author=self.owner, content="댓글")
        like = PostLike.objects.create(post=post, user=self.owner)
        post.delete()

        self.assertFalse(Comment.objects.filter(pk=comment.pk).exists())
        self.assertFalse(PostLike.objects.filter(pk=like.pk).exists())

        drawer = DrawerItem.objects.create(owner=self.owner, title="서랍", kind="command_lab", payload={"schema_version": "1.0.0"})
        wrong_note = WrongNote.objects.create(
            owner=self.owner,
            question_id="generated_002",
            question="질문",
            choices=[],
            selected_choice_id="A",
            correct_choice_id="B",
            explanation="설명",
            evidence_ids=[],
            supporting_quotes=[],
        )
        qa_record = QuestionRecord.objects.create(
            owner=self.owner,
            request_id="qa-cascade-test-001",
            title="질문 기록",
            question="질문",
            answer="답변",
            status="answered",
            response_payload={},
        )
        self.owner.delete()

        self.assertFalse(UserProfile.objects.filter(pk=profile.pk).exists())
        self.assertFalse(DrawerItem.objects.filter(pk=drawer.pk).exists())
        self.assertFalse(WrongNote.objects.filter(pk=wrong_note.pk).exists())
        self.assertFalse(QuestionRecord.objects.filter(pk=qa_record.pk).exists())


class CommunityViewTests(TestCase):
    def setUp(self):
        self.author = get_user_model().objects.create_user(
            username="community_author",
            email="community-author@example.com",
            password="AuthorPass123!",
        )
        self.other_user = get_user_model().objects.create_user(
            username="community_other",
            email="community-other@example.com",
            password="OtherPass123!",
        )
        self.post = Post.objects.create(author=self.author, title="기존 게시글", content="기존 내용")

    def test_public_list_detail_and_pagination(self):
        self.assertEqual(self.client.get(reverse("community_list")).status_code, 200)
        detail_response = self.client.get(reverse("community_post_detail", args=[self.post.pk]))
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, self.post.title)

        for index in range(10):
            Post.objects.create(author=self.author, title=f"페이지 게시글 {index}", content="내용")

        first_page = self.client.get(reverse("community_list"))
        second_page = self.client.get(reverse("community_list"), {"page": 2})
        self.assertEqual(len(first_page.context["page_obj"]), 10)
        self.assertTrue(first_page.context["page_obj"].has_next())
        self.assertEqual(len(second_page.context["page_obj"]), 1)
        self.assertEqual(second_page.context["page_obj"].number, 2)

    def test_post_crud_assigns_authenticated_user_as_author(self):
        self.client.force_login(self.author)
        create_response = self.client.post(
            reverse("community_post_create"),
            {"title": "새 게시글", "content": "새 게시글 내용", "author": self.other_user.pk},
        )
        created_post = Post.objects.get(title="새 게시글")
        self.assertRedirects(create_response, reverse("community_post_detail", args=[created_post.pk]))
        self.assertEqual(created_post.author, self.author)

        edit_response = self.client.post(
            reverse("community_post_edit", args=[created_post.pk]),
            {"title": "수정된 게시글", "content": "수정된 내용"},
        )
        self.assertRedirects(edit_response, reverse("community_post_detail", args=[created_post.pk]))
        created_post.refresh_from_db()
        self.assertEqual(created_post.title, "수정된 게시글")

        self.assertEqual(self.client.get(reverse("community_post_delete", args=[created_post.pk])).status_code, 405)
        delete_response = self.client.post(reverse("community_post_delete", args=[created_post.pk]))
        self.assertRedirects(delete_response, reverse("community_list"))
        self.assertFalse(Post.objects.filter(pk=created_post.pk).exists())

    def test_post_authorization_hides_other_users_post_controls(self):
        self.client.force_login(self.other_user)

        self.assertEqual(self.client.get(reverse("community_post_edit", args=[self.post.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("community_post_delete", args=[self.post.pk])).status_code, 404)
        self.assertTrue(Post.objects.filter(pk=self.post.pk).exists())

    def test_comment_create_edit_and_delete_enforce_author(self):
        self.client.force_login(self.other_user)
        create_response = self.client.post(
            reverse("community_comment_create", args=[self.post.pk]),
            {"content": "첫 댓글"},
        )
        comment = Comment.objects.get(post=self.post)
        self.assertRedirects(create_response, reverse("community_post_detail", args=[self.post.pk]))
        self.assertEqual(comment.author, self.other_user)

        self.client.force_login(self.author)
        self.assertEqual(self.client.get(reverse("community_comment_edit", args=[self.post.pk, comment.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("community_comment_delete", args=[self.post.pk, comment.pk])).status_code, 404)

        self.client.force_login(self.other_user)
        edit_response = self.client.post(
            reverse("community_comment_edit", args=[self.post.pk, comment.pk]),
            {"content": "수정한 댓글"},
        )
        self.assertRedirects(edit_response, reverse("community_post_detail", args=[self.post.pk]))
        comment.refresh_from_db()
        self.assertEqual(comment.content, "수정한 댓글")

        delete_response = self.client.post(reverse("community_comment_delete", args=[self.post.pk, comment.pk]))
        self.assertRedirects(delete_response, reverse("community_post_detail", args=[self.post.pk]))
        self.assertFalse(Comment.objects.filter(pk=comment.pk).exists())

    def test_like_toggles_with_post_only_and_never_duplicates(self):
        self.client.force_login(self.other_user)
        like_url = reverse("community_post_like", args=[self.post.pk])

        self.assertEqual(self.client.get(like_url).status_code, 405)
        self.assertRedirects(self.client.post(like_url), reverse("community_post_detail", args=[self.post.pk]))
        self.assertEqual(PostLike.objects.filter(post=self.post, user=self.other_user).count(), 1)
        self.assertRedirects(self.client.post(like_url), reverse("community_post_detail", args=[self.post.pk]))
        self.assertEqual(PostLike.objects.filter(post=self.post, user=self.other_user).count(), 0)
        self.client.post(like_url)
        self.assertEqual(PostLike.objects.filter(post=self.post, user=self.other_user).count(), 1)

    def test_anonymous_users_cannot_mutate_community_content(self):
        create_url = reverse("community_post_create")
        comment_url = reverse("community_comment_create", args=[self.post.pk])
        like_url = reverse("community_post_like", args=[self.post.pk])

        self.assertRedirects(self.client.get(create_url), f"{reverse('accounts:login')}?next={create_url}")
        self.assertRedirects(self.client.post(comment_url, {"content": "댓글"}), f"{reverse('accounts:login')}?next={comment_url}")
        self.assertRedirects(self.client.post(like_url), f"{reverse('accounts:login')}?next={like_url}")
        self.assertEqual(Comment.objects.count(), 0)
        self.assertEqual(PostLike.objects.count(), 0)


class FakeCommandLabService:
    """Catalog-service boundary double; it intentionally has no execute operation."""

    template_id = "cmd-remote-access-004"
    default_target = "learner@raspberrypi.local"

    def list_templates(self):
        return [
            {
                "template_id": self.template_id,
                "effect_ko": "SSH 원격 접속을 위한 명령입니다.",
                "execution_context": "Raspberry Pi OS 터미널",
                "risk_level": "configuration",
                "review_status": "approved",
                "execution_policy": "display_only",
            }
        ]

    def compose(self, template_id, values=None, *, product_id=None):
        if template_id != self.template_id:
            raise CommandLabError("검수 완료된 명령어를 선택해 주세요.")
        if values is None:
            values = {}
        if not isinstance(values, dict) or set(values) - {"part-02"}:
            raise CommandLabError("고정 구성 요소나 알 수 없는 필드는 수정할 수 없습니다.")
        target = values.get("part-02", self.default_target)
        if not isinstance(target, str) or not target or target.startswith("-") or any(symbol in target for symbol in (";", "|", "&", "\n")):
            raise CommandLabError("입력값 형식이 올바르지 않습니다.")
        if product_id not in {None, "raspberry-pi-5"}:
            raise CommandLabError("등록되지 않은 제품입니다.")
        return {
            "schema_version": "1.0.0",
            "template_id": template_id,
            "catalog_version": "test-catalog-v1",
            "execution_policy": "display_only",
            "command": f"ssh {target}",
            "parts": [
                {"part_id": "part-01", "label_ko": "명령", "description_ko": "SSH", "value": "ssh", "editable": False},
                {"part_id": "part-02", "label_ko": "접속 대상", "description_ko": "사용자명@호스트", "value": target, "editable": True},
            ],
            "effect_ko": "SSH 원격 접속을 위한 명령입니다.",
            "execution_context": "Raspberry Pi OS 터미널",
            "risk_level": "configuration",
            "risk_notice_ko": "이 화면은 설명만 제공합니다.",
            "limitations_ko": "명령을 실제로 실행하지 않습니다.",
            "evidence": [{"chunk_id": "rpi-doc-remote-access-ssh-001"}],
            "product": None if product_id is None else {"product_id": product_id, "name": "Raspberry Pi 5"},
            "values": dict(values),
        }

    def analyze(self, command):
        if command == f"ssh {self.default_target}":
            return self.compose(self.template_id)
        if isinstance(command, str) and command.startswith("ssh "):
            return self.compose(self.template_id, {"part-02": command[4:]})
        raise CommandLabError("검수된 템플릿과 일치하지 않습니다. 명령어 목록에서 선택해 주세요.")

    def drawer_payload(self, template_id, values=None, *, product_id=None):
        result = self.compose(template_id, values, product_id=product_id)
        return {
            "schema_version": "1.0.0",
            "kind": "command_lab",
            "template_id": template_id,
            "catalog_version": result["catalog_version"],
            "values": result["values"],
            "product_id": product_id,
            "command_snapshot": result["command"],
            "command_checksum": f"sha256:{result['command']}",
            "evidence_ids": ["rpi-doc-remote-access-ssh-001"],
            "evidence_checksums": ["sha256:evidence"],
        }

    def restore_drawer(self, saved):
        if not isinstance(saved, dict) or saved.get("catalog_version") != "test-catalog-v1":
            raise CommandLabError("저장 이후 명령 또는 근거가 변경되었습니다. 실험실에서 다시 확인해 주세요.")
        current = self.drawer_payload(saved.get("template_id"), saved.get("values"), product_id=saved.get("product_id"))
        for key in ("command_checksum", "command_snapshot", "evidence_ids", "evidence_checksums"):
            if saved.get(key) != current[key]:
                raise CommandLabError("저장 이후 명령 또는 근거가 변경되었습니다. 실험실에서 다시 확인해 주세요.")
        return self.compose(saved["template_id"], saved.get("values"), product_id=saved.get("product_id"))


class CommandLabAndDrawerTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username="drawer_owner",
            email="drawer-owner@example.com",
            password="DrawerOwner123!",
        )
        self.other_user = get_user_model().objects.create_user(
            username="drawer_other",
            email="drawer-other@example.com",
            password="DrawerOther123!",
        )
        self.service = FakeCommandLabService()
        self.service_patch = patch("portal.views.get_command_lab_service", return_value=self.service)
        self.service_patch.start()
        self.addCleanup(self.service_patch.stop)

    def test_api_lists_analyzes_and_composes_display_only_results(self):
        templates_response = self.client.get(reverse("api_lab_templates"))
        self.assertEqual(templates_response.status_code, 200)
        self.assertEqual(templates_response.json()["templates"][0]["template_id"], FakeCommandLabService.template_id)

        analyze_response = self.client.post(
            reverse("api_lab_analyze"),
            data=json.dumps({"command": "ssh pi@host"}),
            content_type="application/json",
        )
        self.assertEqual(analyze_response.status_code, 200)
        self.assertEqual(analyze_response.json()["command"], "ssh pi@host")
        self.assertEqual(analyze_response.json()["execution_policy"], "display_only")

        compose_response = self.client.post(
            reverse("api_lab_compose"),
            data=json.dumps({"template_id": FakeCommandLabService.template_id, "values": {"part-02": "pi@host"}}),
            content_type="application/json",
        )
        self.assertEqual(compose_response.status_code, 200)
        self.assertEqual(compose_response.json()["command"], "ssh pi@host")

        lab_response = self.client.post(
            reverse("command_lab"),
            {"action": "compose", "template_id": FakeCommandLabService.template_id, "value_part-02": "pi@host"},
        )
        self.assertContains(lab_response, "ssh pi@host")

    def test_unknown_commands_and_draft_templates_return_4xx(self):
        unknown_response = self.client.post(
            reverse("api_lab_analyze"),
            data=json.dumps({"command": "rm -rf /"}),
            content_type="application/json",
        )
        draft_response = self.client.post(
            reverse("api_lab_compose"),
            data=json.dumps({"template_id": "cmd-camera-001", "values": {}}),
            content_type="application/json",
        )

        self.assertEqual(unknown_response.status_code, 400)
        self.assertEqual(draft_response.status_code, 400)
        self.assertIn("error", unknown_response.json())
        self.assertIn("error", draft_response.json())

    def test_drawer_save_uses_server_generated_payload_and_authenticated_owner(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("drawer_save"),
            {
                "template_id": FakeCommandLabService.template_id,
                "value_part-02": "pi@server",
                "command_snapshot": "rm -rf /",
                "command_checksum": "sha256:forged",
                "owner": self.other_user.pk,
            },
        )

        item = DrawerItem.objects.get()
        self.assertRedirects(response, reverse("drawer_detail", args=[item.pk]))
        self.assertEqual(item.owner, self.owner)
        self.assertEqual(item.kind, "command_lab")
        self.assertEqual(item.title, "ssh pi@server")
        self.assertEqual(item.payload["command_snapshot"], "ssh pi@server")
        self.assertNotEqual(item.payload["command_snapshot"], "rm -rf /")
        self.assertNotEqual(item.payload["command_checksum"], "sha256:forged")

    def test_drawer_owner_scope_blocks_other_user_detail_and_delete(self):
        payload = self.service.drawer_payload(FakeCommandLabService.template_id, {"part-02": "pi@owner"})
        item = DrawerItem.objects.create(owner=self.owner, title=payload["command_snapshot"], kind=payload["kind"], payload=payload)
        self.client.force_login(self.other_user)

        self.assertEqual(self.client.get(reverse("drawer_detail", args=[item.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("drawer_delete", args=[item.pk])).status_code, 404)
        self.assertTrue(DrawerItem.objects.filter(pk=item.pk).exists())

    def test_drawer_requires_login_and_returns_reconfirmation_state_when_changed(self):
        self.assertRedirects(self.client.get(reverse("drawer_list")), f"{reverse('accounts:login')}?next={reverse('drawer_list')}")
        self.assertRedirects(
            self.client.post(reverse("drawer_save"), {"template_id": FakeCommandLabService.template_id}),
            f"{reverse('accounts:login')}?next={reverse('drawer_save')}",
        )

        payload = self.service.drawer_payload(FakeCommandLabService.template_id, {"part-02": "pi@owner"})
        changed_payload = deepcopy(payload)
        changed_payload["catalog_version"] = "changed-catalog-version"
        item = DrawerItem.objects.create(owner=self.owner, title=payload["command_snapshot"], kind=payload["kind"], payload=changed_payload)
        self.client.force_login(self.owner)
        response = self.client.get(reverse("drawer_detail", args=[item.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["needs_reconfirmation"])
        self.assertContains(response, "재확인이 필요합니다")

    def test_command_lab_has_no_execution_operation(self):
        self.assertFalse(hasattr(CommandLabService, "execute"))
        response = self.client.post(
            reverse("api_lab_compose"),
            data=json.dumps({"template_id": FakeCommandLabService.template_id, "values": {}}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["execution_policy"], "display_only")


class DynamicQuizAndWrongNoteTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username="quiz_owner",
            email="quiz-owner@example.com",
            password="QuizOwner123!",
        )
        self.other_user = get_user_model().objects.create_user(
            username="quiz_other",
            email="quiz-other@example.com",
            password="QuizOther123!",
        )
        self.quiz_question = QuizQuestion(
            question_id="generated_001",
            question="Raspberry Pi OS에서 SSH의 기본 상태는 무엇인가요?",
            choices=[
                QuizChoice(id="A", text="기본적으로 비활성화"),
                QuizChoice(id="B", text="기본적으로 활성화"),
                QuizChoice(id="C", text="설치 중에만 활성화"),
                QuizChoice(id="D", text="네트워크 연결 시에만 활성화"),
            ],
            correct_choice_id="A",
            explanation="SSH는 기본적으로 비활성화되어 있습니다.",
            evidence_ids=["C1"],
            supporting_quotes=["SSH is disabled by default on Raspberry Pi OS."],
        )
        self.qa_service = Mock()
        self.qa_patch = patch("portal.views.get_qa_service", return_value=self.qa_service)
        self.readiness_patch = patch(
            "portal.views.get_runtime_readiness",
            return_value=SimpleNamespace(ready=True, message="ready"),
        )
        self.presenter_patch = patch("portal.views.get_citation_presenter", return_value=None)
        self.qa_patch.start()
        self.readiness_patch.start()
        self.presenter_patch.start()
        self.addCleanup(self.qa_patch.stop)
        self.addCleanup(self.readiness_patch.stop)
        self.addCleanup(self.presenter_patch.stop)

    @staticmethod
    def _chat_response(*, answered: bool = True, with_citation: bool = True) -> ChatResponse:
        citations = []
        status = "answered" if answered else "insufficient_evidence"
        answer = "Raspberry Pi OS에서 SSH는 기본적으로 비활성화되어 있습니다. [C1]" if with_citation else "공식 근거가 부족합니다."
        if with_citation:
            citations = [
                ChatCitation(
                    citation_id="C1",
                    document_id="rpi-doc-remote-access-ssh",
                    chunk_id="rpi-doc-remote-access-ssh-001",
                    title="Remote access",
                    publisher="Raspberry Pi Ltd",
                    section="SSH",
                    source_url="https://www.raspberrypi.com/documentation/computers/remote-access.html",
                    source_anchor=None,
                    document_version=None,
                    published_at=None,
                    updated_at=None,
                    collected_at=date(2026, 9, 12),
                    license="CC BY-SA 4.0",
                    quote="SSH is disabled by default on Raspberry Pi OS.",
                )
            ]
        return ChatResponse(
            schema_version="1.2.0",
            request_id="qa-quiz-test-001",
            status=status,
            language="ko",
            answer=answer,
            conditions=None,
            citations=citations,
            products=[],
            media=[],
            clarification_questions=[],
            warnings=[],
        )

    def _submit_qa(self, response: ChatResponse):
        self.qa_service.answer.return_value = response
        result = self.client.post(reverse("qa"), {"question": "SSH 기본 상태가 무엇인가요?"})
        self.assertEqual(result.status_code, 200)
        return result

    def _start_job(self, *, task_id: str):
        task = Mock()
        task.delay.return_value = SimpleNamespace(id=task_id)
        task_patch = patch("portal.views.get_quiz_generation_task", return_value=task)
        task_patch.start()
        self.addCleanup(task_patch.stop)
        result = self.client.post(
            reverse("mini_challenge_start_api"),
            data=json.dumps({"max_questions": 3}),
            content_type="application/json",
        )
        return result, task

    def test_answered_response_queues_the_same_session_response(self):
        chat_response = self._chat_response()
        qa_result = self._submit_qa(chat_response)
        self.assertContains(qa_result, "DYNAMIC MINI CHALLENGE")

        result, task = self._start_job(task_id=str(uuid.uuid4()))

        self.assertEqual(result.status_code, 202)
        self.assertEqual(result.json()["status"], "pending")
        task.delay.assert_called_once_with(chat_response.model_dump(mode="json"), max_questions=3)

    def test_response_without_citation_does_not_queue_a_task(self):
        qa_result = self._submit_qa(self._chat_response(answered=False, with_citation=False))
        self.assertNotContains(qa_result, "DYNAMIC MINI CHALLENGE")

        result, task = self._start_job(task_id=str(uuid.uuid4()))

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["status"], "insufficient_content")
        task.delay.assert_not_called()

    def test_status_hides_answer_key_then_submit_reveals_it_and_saves_wrong_note(self):
        self.client.force_login(self.owner)
        self._submit_qa(self._chat_response())
        task_id = str(uuid.uuid4())
        started, _ = self._start_job(task_id=task_id)
        self.assertEqual(started.status_code, 202)
        async_result = Mock(state="SUCCESS", result=QuizResponse(status="available", questions=[self.quiz_question]).model_dump(mode="json"))
        with patch("portal.views.get_quiz_async_result", return_value=async_result):
            status_result = self.client.get(reverse("mini_challenge_job_api", args=[task_id]))

        self.assertEqual(status_result.status_code, 200)
        public_question = status_result.json()["quiz"]["questions"][0]
        self.assertNotIn("correct_choice_id", public_question)
        self.assertNotIn("explanation", public_question)
        quiz_id = status_result.json()["quiz_id"]
        submit_result = self.client.post(
            reverse("mini_challenge_submit_api", args=[quiz_id]),
            data=json.dumps({"question_id": self.quiz_question.question_id, "selected_choice_id": "B"}),
            content_type="application/json",
        )

        submission = submit_result.json()
        self.assertFalse(submission["is_correct"])
        self.assertEqual(submission["correct_choice_id"], "A")
        self.assertIn("explanation", submission)
        save_result = self.client.post(
            reverse("wrong_note_save", args=[quiz_id]),
            {
                "question_id": self.quiz_question.question_id,
                "question": "클라이언트가 위조한 문제",
                "correct_choice_id": "B",
                "evidence_ids": "forged",
            },
        )

        note = WrongNote.objects.get()
        self.assertRedirects(save_result, reverse("wrong_note_detail", args=[note.pk]))
        self.assertEqual(note.owner, self.owner)
        self.assertEqual(note.question, self.quiz_question.question)
        self.assertEqual(note.selected_choice_id, "B")
        self.assertEqual(note.correct_choice_id, "A")
        self.assertEqual(note.evidence_ids, ["C1"])
        self.assertEqual(note.supporting_quotes, ["SSH is disabled by default on Raspberry Pi OS."])

    def test_cancel_api_revokes_only_the_session_task_and_discards_late_result(self):
        self._submit_qa(self._chat_response())
        task_id = str(uuid.uuid4())
        self._start_job(task_id=task_id)
        async_result = Mock()

        with patch("portal.views.get_quiz_async_result", return_value=async_result):
            cancelled = self.client.post(reverse("mini_challenge_cancel_api", args=[task_id]))
            late_status = self.client.get(reverse("mini_challenge_job_api", args=[task_id]))

        self.assertEqual(cancelled.status_code, 202)
        async_result.revoke.assert_called_once_with(terminate=True, signal="SIGTERM")
        self.assertEqual(late_status.json()["status"], "cancelled")

    def test_job_owner_scope_and_csrf_protection(self):
        self._submit_qa(self._chat_response())
        task_id = str(uuid.uuid4())
        self._start_job(task_id=task_id)
        self.assertEqual(Client().get(reverse("mini_challenge_job_api", args=[task_id])).status_code, 404)

        csrf_client = Client(enforce_csrf_checks=True)
        self.assertEqual(
            csrf_client.post(
                reverse("mini_challenge_start_api"),
                data=json.dumps({"max_questions": 3}),
                content_type="application/json",
            ).status_code,
            403,
        )

    def test_wrong_note_owner_scope_and_delete(self):
        note = WrongNote.objects.create(
            owner=self.owner,
            question_id="generated_001",
            question="질문",
            choices=[{"id": "A", "text": "선택지"}],
            selected_choice_id="A",
            correct_choice_id="B",
            explanation="해설",
            evidence_ids=["C1"],
            supporting_quotes=["검증된 근거 문장입니다."],
        )
        self.client.force_login(self.other_user)
        self.assertEqual(self.client.get(reverse("wrong_note_detail", args=[note.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("wrong_note_delete", args=[note.pk])).status_code, 404)

        self.client.force_login(self.owner)
        delete_result = self.client.post(reverse("wrong_note_delete", args=[note.pk]))
        self.assertRedirects(delete_result, reverse("wrong_note_list"))
        self.assertFalse(WrongNote.objects.filter(pk=note.pk).exists())


class MyPageTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username="mypage_owner",
            email="mypage-owner@example.com",
            password="MyPageOwner123!",
        )
        self.other_user = get_user_model().objects.create_user(
            username="mypage_other",
            email="mypage-other@example.com",
            password="MyPageOther123!",
        )
        self.own_post = Post.objects.create(author=self.owner, title="내 게시글", content="내가 작성한 내용")
        self.other_post = Post.objects.create(author=self.other_user, title="다른 회원 게시글", content="다른 회원의 내용")
        self.liked_post = Post.objects.create(author=self.other_user, title="내가 추천한 게시글", content="추천 대상")
        self.other_liked_post = Post.objects.create(author=self.other_user, title="다른 회원 추천 게시글", content="다른 추천 대상")
        Comment.objects.create(post=self.own_post, author=self.owner, content="내 댓글")
        Comment.objects.create(post=self.other_post, author=self.other_user, content="다른 회원 댓글")
        PostLike.objects.create(post=self.liked_post, user=self.owner)
        PostLike.objects.create(post=self.other_liked_post, user=self.other_user)
        DrawerItem.objects.create(owner=self.owner, title="내 서랍 항목", kind="command_lab", payload={"kind": "command_lab"})
        DrawerItem.objects.create(owner=self.other_user, title="다른 회원 서랍 항목", kind="command_lab", payload={"kind": "command_lab"})
        WrongNote.objects.create(
            owner=self.owner,
            question_id="owner-note",
            question="내 오답노트 질문",
            choices=[{"id": "A", "text": "선택지"}],
            selected_choice_id="A",
            correct_choice_id="B",
            explanation="내 해설",
            evidence_ids=["C1"],
            supporting_quotes=["내 근거"],
        )
        WrongNote.objects.create(
            owner=self.other_user,
            question_id="other-note",
            question="다른 회원 오답노트 질문",
            choices=[{"id": "A", "text": "선택지"}],
            selected_choice_id="A",
            correct_choice_id="B",
            explanation="다른 해설",
            evidence_ids=["C2"],
            supporting_quotes=["다른 근거"],
        )
        QuestionRecord.objects.create(
            owner=self.owner,
            request_id="mypage-owner-qa",
            title="내 질문 기록",
            question="내 질문",
            answer="내 답변",
            status="answered",
            response_payload={},
        )
        QuestionRecord.objects.create(
            owner=self.other_user,
            request_id="mypage-other-qa",
            title="다른 회원 질문 기록",
            question="다른 질문",
            answer="다른 답변",
            status="answered",
            response_payload={},
        )

    def test_mypage_aggregates_only_the_current_users_activity(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("mypage"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["activity_counts"],
            {"posts": 1, "comments": 1, "likes": 1, "drawer_items": 1, "wrong_notes": 1, "qa_records": 1},
        )
        self.assertContains(response, "내 게시글")
        self.assertContains(response, "내 댓글")
        self.assertContains(response, "내 서랍 항목")
        self.assertContains(response, "내 오답노트 질문")
        self.assertContains(response, "내 질문 기록")
        self.assertNotContains(response, "다른 회원 댓글")
        self.assertNotContains(response, "다른 회원 서랍 항목")
        self.assertNotContains(response, "다른 회원 오답노트 질문")
        self.assertNotContains(response, "다른 회원 질문 기록")

    def test_activity_lists_are_owner_scoped_and_paginated(self):
        for index in range(10):
            Post.objects.create(author=self.owner, title=f"추가 게시글 {index}", content="내용")

        self.client.force_login(self.owner)
        posts_response = self.client.get(reverse("mypage_posts"), {"page": 2})
        comments_response = self.client.get(reverse("mypage_comments"))
        likes_response = self.client.get(reverse("mypage_likes"))
        drawer_response = self.client.get(reverse("drawer_list"))
        wrong_notes_response = self.client.get(reverse("wrong_note_list"))
        questions_response = self.client.get(reverse("mypage_questions"))

        self.assertEqual(posts_response.context["page_obj"].number, 2)
        self.assertEqual(len(posts_response.context["page_obj"].object_list), 1)
        self.assertContains(posts_response, "내 게시글")
        self.assertNotContains(posts_response, "다른 회원 게시글")
        self.assertContains(comments_response, "내 댓글")
        self.assertNotContains(comments_response, "다른 회원 댓글")
        self.assertContains(likes_response, "내가 추천한 게시글")
        self.assertNotContains(likes_response, "다른 회원 추천 게시글")
        self.assertContains(drawer_response, "내 서랍 항목")
        self.assertNotContains(drawer_response, "다른 회원 서랍 항목")
        self.assertContains(wrong_notes_response, "내 오답노트 질문")
        self.assertNotContains(wrong_notes_response, "다른 회원 오답노트 질문")
        self.assertContains(questions_response, "내 질문 기록")
        self.assertNotContains(questions_response, "다른 회원 질문 기록")

    def test_mypage_shows_empty_activity_states(self):
        empty_user = get_user_model().objects.create_user(
            username="mypage_empty",
            email="mypage-empty@example.com",
            password="MyPageEmpty123!",
        )
        self.client.force_login(empty_user)

        response = self.client.get(reverse("mypage"))

        self.assertEqual(
            response.context["activity_counts"],
            {"posts": 0, "comments": 0, "likes": 0, "drawer_items": 0, "wrong_notes": 0, "qa_records": 0},
        )
        self.assertContains(response, "작성한 게시글이 없습니다.")
        self.assertContains(response, "저장한 오답노트가 없습니다.")
        self.assertContains(response, "저장한 질문 기록이 없습니다.")

    def test_mypage_and_activity_lists_require_login(self):
        for url_name in ("mypage", "mypage_posts", "mypage_comments", "mypage_likes", "mypage_questions", "drawer_list", "wrong_note_list"):
            url = reverse(url_name)
            response = self.client.get(url)
            self.assertRedirects(response, f"{reverse('accounts:login')}?next={url}")


class QuestionRecordViewTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username="qa_owner",
            email="qa-owner@example.com",
            password="QaOwner123!",
        )
        self.other_user = get_user_model().objects.create_user(
            username="qa_other",
            email="qa-other@example.com",
            password="QaOther123!",
        )

    @staticmethod
    def _response(*, status: str = "answered") -> ChatResponse:
        citations = []
        answer = "공식 문서 근거가 부족합니다."
        clarification_questions = []
        if status == "answered":
            answer = "Raspberry Pi OS에서 SSH는 기본적으로 비활성화되어 있습니다. [C1]"
            citations = [
                ChatCitation(
                    citation_id="C1",
                    document_id="rpi-doc-remote-access-ssh",
                    chunk_id="rpi-doc-remote-access-ssh-001",
                    title="Remote access",
                    publisher="Raspberry Pi Ltd",
                    section="SSH",
                    source_url="https://www.raspberrypi.com/documentation/computers/remote-access.html",
                    source_anchor=None,
                    document_version=None,
                    published_at=None,
                    updated_at=None,
                    collected_at=date(2026, 9, 12),
                    license="CC BY-SA 4.0",
                    quote="SSH is disabled by default on Raspberry Pi OS.",
                )
            ]
        return ChatResponse(
            schema_version="1.2.0",
            request_id=f"qa-record-{status}",
            status=status,
            language="ko",
            answer=answer,
            conditions=None,
            citations=citations,
            products=[],
            media=[],
            clarification_questions=clarification_questions,
            warnings=["internal record data"],
        )

    def _submit_qa(self, response: ChatResponse):
        service = Mock()
        service.answer.return_value = response
        with (
            patch("portal.views.get_runtime_readiness", return_value=SimpleNamespace(ready=True, message="ready")),
            patch("portal.views.get_qa_service", return_value=service),
            patch("portal.views.get_citation_presenter", return_value=None),
        ):
            return self.client.post(reverse("qa"), {"question": "SSH를 어떻게 설정하나요? 두 번째 문장입니다."})

    def _record(self, *, owner=None, public=False) -> QuestionRecord:
        response = self._response()
        return QuestionRecord.objects.create(
            owner=owner or self.owner,
            request_id=response.request_id,
            title="SSH를 어떻게 설정하나요?",
            question="SSH를 어떻게 설정하나요?",
            answer=response.answer,
            status=response.status,
            response_payload=response.model_dump(mode="json"),
            is_public=public,
        )

    def test_logged_in_qa_saves_full_response_snapshot_and_guest_qa_does_not(self):
        response = self._response()
        self.client.force_login(self.owner)
        saved_page = self._submit_qa(response)

        record = QuestionRecord.objects.get()
        self.assertEqual(record.owner, self.owner)
        self.assertEqual(record.title, "SSH를 어떻게 설정하나요?")
        self.assertEqual(record.status, "answered")
        self.assertEqual(record.response_payload, response.model_dump(mode="json"))
        self.assertContains(saved_page, "답변을 내 질문 기록에 저장했습니다")

        self.client.logout()
        self._submit_qa(self._response(status="insufficient_evidence"))
        self.assertEqual(QuestionRecord.objects.count(), 1)

    def test_non_answered_valid_response_is_saved_for_logged_in_user(self):
        self.client.force_login(self.owner)
        self._submit_qa(self._response(status="insufficient_evidence"))

        record = QuestionRecord.objects.get()
        self.assertEqual(record.status, "insufficient_evidence")
        self.assertEqual(record.answer, "공식 문서 근거가 부족합니다.")

    def test_private_records_are_owner_only_and_public_records_appear_in_archive(self):
        record = self._record()
        self.assertNotContains(self.client.get(reverse("questions")), record.title)
        self.assertEqual(self.client.get(reverse("question_detail", args=[record.pk])).status_code, 404)

        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("mypage_question_detail", args=[record.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("mypage_question_visibility", args=[record.pk])).status_code, 405)

        self.client.force_login(self.other_user)
        self.assertEqual(self.client.get(reverse("mypage_question_detail", args=[record.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("mypage_question_visibility", args=[record.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("mypage_question_delete", args=[record.pk])).status_code, 404)

        self.client.force_login(self.owner)
        toggle_response = self.client.post(reverse("mypage_question_visibility", args=[record.pk]))
        self.assertRedirects(toggle_response, reverse("mypage_question_detail", args=[record.pk]))
        record.refresh_from_db()
        self.assertTrue(record.is_public)
        self.assertIsNotNone(record.published_at)

        public_list = self.client.get(reverse("questions"))
        public_detail = self.client.get(reverse("question_detail", args=[record.pk]))
        self.assertContains(public_list, record.title)
        self.assertContains(public_detail, record.answer)
        self.assertNotContains(public_detail, "internal record data")

        for index in range(10):
            QuestionRecord.objects.create(
                owner=self.owner,
                request_id=f"qa-public-page-{index}",
                title=f"공개 질문 {index}",
                question="질문",
                answer="답변",
                status="answered",
                response_payload={},
                is_public=True,
                published_at=record.published_at,
            )
        first_page = self.client.get(reverse("questions"))
        second_page = self.client.get(reverse("questions"), {"page": 2})
        self.assertEqual(len(first_page.context["page_obj"]), 10)
        self.assertEqual(second_page.context["page_obj"].number, 2)

        delete_response = self.client.post(reverse("mypage_question_delete", args=[record.pk]))
        self.assertRedirects(delete_response, reverse("mypage_questions"))
        self.assertFalse(QuestionRecord.objects.filter(pk=record.pk).exists())
        self.assertEqual(self.client.get(reverse("question_detail", args=[record.pk])).status_code, 404)


class SecurityRegressionTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username="security_owner",
            email="security-owner@example.com",
            password="SecurityOwner123!",
        )
        self.other_user = get_user_model().objects.create_user(
            username="security_other",
            email="security-other@example.com",
            password="SecurityOther123!",
        )
        self.post = Post.objects.create(author=self.owner, title="보안 점검 게시글", content="내용")
        self.comment = Comment.objects.create(post=self.post, author=self.owner, content="보안 점검 댓글")
        self.drawer_item = DrawerItem.objects.create(
            owner=self.owner,
            title="보안 점검 서랍",
            kind="command_lab",
            payload={"kind": "command_lab"},
        )
        self.wrong_note = WrongNote.objects.create(
            owner=self.owner,
            question_id="security-note",
            question="보안 점검 질문",
            choices=[{"id": "A", "text": "선택지"}],
            selected_choice_id="A",
            correct_choice_id="B",
            explanation="해설",
            evidence_ids=["C1"],
            supporting_quotes=["근거"],
        )

    def test_state_changing_endpoints_require_post_and_csrf(self):
        self.client.force_login(self.owner)
        post_only_urls = (
            reverse("accounts:logout"),
            reverse("community_post_delete", args=[self.post.pk]),
            reverse("community_comment_delete", args=[self.post.pk, self.comment.pk]),
            reverse("community_post_like", args=[self.post.pk]),
            reverse("drawer_save"),
            reverse("drawer_delete", args=[self.drawer_item.pk]),
            reverse("wrong_note_delete", args=[self.wrong_note.pk]),
            reverse("mini_challenge_start_api"),
        )
        for url in post_only_urls:
            self.assertEqual(self.client.get(url).status_code, 405)

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        self.assertEqual(csrf_client.post(reverse("profile_edit"), {"username": "changed", "email": "changed@example.com"}).status_code, 403)
        self.assertEqual(csrf_client.post(reverse("community_post_like", args=[self.post.pk])).status_code, 403)
        self.assertEqual(csrf_client.post(reverse("accounts:logout")).status_code, 403)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.username, "security_owner")
        self.assertEqual(PostLike.objects.filter(post=self.post, user=self.owner).count(), 0)

    def test_login_does_not_follow_an_external_next_url(self):
        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": self.owner.username,
                "password": "SecurityOwner123!",
                "next": "https://attacker.example/steal-session",
            },
        )

        self.assertRedirects(response, reverse("about"))

    def test_community_forms_reject_overlong_content(self):
        self.client.force_login(self.owner)
        post_count = Post.objects.count()
        post_response = self.client.post(
            reverse("community_post_create"),
            {"title": "긴 글", "content": "x" * 10_001},
        )
        comment_response = self.client.post(
            reverse("community_comment_create", args=[self.post.pk]),
            {"content": "x" * 2_001},
        )

        self.assertEqual(post_response.status_code, 200)
        self.assertIn("content", post_response.context["form"].errors)
        self.assertEqual(comment_response.status_code, 302)
        self.assertEqual(Post.objects.count(), post_count)
        self.assertFalse(Comment.objects.filter(post=self.post, content="x" * 2_001).exists())

    def test_runtime_errors_are_logged_without_user_secret_disclosure(self):
        readiness = SimpleNamespace(ready=True, message="ready")
        with (
            patch("portal.views.get_runtime_readiness", return_value=readiness),
            patch("portal.views.get_qa_service", side_effect=RuntimeError("QA_INTERNAL_SECRET")),
        ):
            qa_response = self.client.post(reverse("qa"), {"question": "SSH 설정 방법"})
        with (
            patch("portal.views.get_runtime_readiness", return_value=readiness),
            patch("portal.views.get_recommendation_service", side_effect=RuntimeError("RECOMMEND_INTERNAL_SECRET")),
        ):
            recommendation_response = self.client.post(reverse("recommend"), {"purpose": "홈 서버"})
        with patch("portal.views.get_command_lab_service", side_effect=RuntimeError("LAB_INTERNAL_SECRET")):
            lab_response = self.client.get(reverse("api_lab_templates"))

        self.assertContains(qa_response, "서비스를 일시적으로 이용할 수 없습니다")
        self.assertNotContains(qa_response, "QA_INTERNAL_SECRET")
        self.assertContains(recommendation_response, "제품 추천 서비스를 일시적으로 이용할 수 없습니다")
        self.assertNotContains(recommendation_response, "RECOMMEND_INTERNAL_SECRET")
        self.assertEqual(lab_response.status_code, 503)
        self.assertNotIn("LAB_INTERNAL_SECRET", lab_response.json()["error"])

    def test_unready_runtime_message_is_safe_for_pages_and_health(self):
        unready = SimpleNamespace(ready=False, message="RUNTIME_INTERNAL_SECRET")
        with patch("portal.views.get_runtime_readiness", return_value=unready):
            about_response = self.client.get(reverse("about"))
            health_response = self.client.get(reverse("health"))

        self.assertContains(about_response, "RAG 실행 환경을 준비하지 못했습니다")
        self.assertNotContains(about_response, "RUNTIME_INTERNAL_SECRET")
        self.assertEqual(health_response.status_code, 200)
        self.assertEqual(health_response.json()["status"], "not_ready")
        self.assertNotIn("RUNTIME_INTERNAL_SECRET", health_response.json()["message"])
