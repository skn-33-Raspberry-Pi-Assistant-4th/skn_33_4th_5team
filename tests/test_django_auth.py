"""Database-backed authentication tests for PiCare's default Django User flow."""

from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_APP = ROOT / "web_app"
if str(WEB_APP) not in sys.path:
    sys.path.insert(0, str(WEB_APP))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "picare_web.settings")
os.environ.setdefault("DJANGO_DB_ENGINE", "django.db.backends.sqlite3")
os.environ.setdefault("DJANGO_SQLITE_PATH", ":memory:")

import django

django.setup()

from django.contrib.auth.models import User
from django.test import Client, TestCase


STRONG_PASSWORD = "PiCare-Safe-Password-2026!"


class AccountFlowTests(TestCase):
    def signup(self, **overrides):
        data = {
            "username": "picare_user",
            "email": "picare@example.com",
            "password1": STRONG_PASSWORD,
            "password2": STRONG_PASSWORD,
        }
        data.update(overrides)
        return self.client.post("/accounts/signup/", data)

    def test_signup_creates_hashed_user_and_logs_in(self):
        response = self.signup()

        self.assertRedirects(response, "/")
        user = User.objects.get(username="picare_user")
        self.assertEqual(user.email, "picare@example.com")
        self.assertNotEqual(user.password, STRONG_PASSWORD)
        self.assertTrue(user.check_password(STRONG_PASSWORD))
        self.assertEqual(self.client.get("/").wsgi_request.user, user)

    def test_signup_rejects_duplicate_username_and_email_case_insensitively(self):
        User.objects.create_user("existing", "member@example.com", STRONG_PASSWORD)

        username_response = self.signup(username="existing", email="other@example.com")
        email_response = self.signup(username="other", email="MEMBER@example.com")

        self.assertContains(username_response, "이미 사용 중인 아이디")
        self.assertContains(email_response, "이미 가입된 이메일입니다.")
        self.assertEqual(User.objects.count(), 1)

    def test_signup_rejects_weak_or_mismatched_password(self):
        response = self.signup(password1="12345678", password2="12345679")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.count(), 0)
        self.assertContains(response, "비밀번호")

    def test_login_and_post_only_logout(self):
        user = User.objects.create_user("member", "member@example.com", STRONG_PASSWORD)
        login_response = self.client.post("/accounts/login/", {"username": "member", "password": STRONG_PASSWORD})

        self.assertRedirects(login_response, "/")
        self.assertEqual(self.client.get("/").wsgi_request.user, user)
        self.assertEqual(self.client.get("/accounts/logout/").status_code, 405)

        logout_response = self.client.post("/accounts/logout/")
        self.assertRedirects(logout_response, "/")
        self.assertFalse(self.client.get("/").wsgi_request.user.is_authenticated)

    def test_logout_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        user = User.objects.create_user("member", "member@example.com", STRONG_PASSWORD)
        client.force_login(user)

        response = client.post("/accounts/logout/")

        self.assertEqual(response.status_code, 403)
