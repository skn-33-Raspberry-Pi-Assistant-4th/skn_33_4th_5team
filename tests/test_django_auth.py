"""Database-backed authentication tests for PiCare's default Django User flow."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch


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
from django.test import Client, SimpleTestCase, TestCase

from picare_web.settings import _database_config


STRONG_PASSWORD = "PiCare-Safe-Password-2026!"

DB_ENV_NAMES = (
    "DJANGO_DB_ENGINE",
    "DJANGO_DB_NAME",
    "DJANGO_DB_USER",
    "DJANGO_DB_PASSWORD",
    "DJANGO_DB_HOST",
    "DJANGO_DB_PORT",
    "DJANGO_SQLITE_PATH",
    "MYSQL_DATABASE",
    "MYSQL_USER",
    "MYSQL_PASSWORD",
    "MYSQL_HOST",
    "MYSQL_PORT",
)


class DatabaseSettingsTests(SimpleTestCase):
    @staticmethod
    def database_config(**overrides):
        values = dict.fromkeys(DB_ENV_NAMES, "")
        values.update(overrides)
        with patch.dict(os.environ, values):
            return _database_config()

    def test_mysql_settings_fall_back_to_mysql_environment(self):
        config = self.database_config(
            DJANGO_DB_ENGINE="django.db.backends.mysql",
            MYSQL_DATABASE="mysql_database",
            MYSQL_USER="mysql_user",
            MYSQL_PASSWORD="mysql_password",
            MYSQL_HOST="mysql_host",
            MYSQL_PORT="3307",
        )

        self.assertEqual(
            config,
            {
                "ENGINE": "django.db.backends.mysql",
                "NAME": "mysql_database",
                "USER": "mysql_user",
                "PASSWORD": "mysql_password",
                "HOST": "mysql_host",
                "PORT": "3307",
            },
        )

    def test_django_mysql_settings_take_priority(self):
        config = self.database_config(
            DJANGO_DB_ENGINE="django.db.backends.mysql",
            DJANGO_DB_NAME="django_database",
            DJANGO_DB_USER="django_user",
            DJANGO_DB_PASSWORD="django_password",
            DJANGO_DB_HOST="django_host",
            DJANGO_DB_PORT="3308",
            MYSQL_DATABASE="mysql_database",
            MYSQL_USER="mysql_user",
            MYSQL_PASSWORD="mysql_password",
            MYSQL_HOST="mysql_host",
            MYSQL_PORT="3307",
        )

        self.assertEqual(
            config,
            {
                "ENGINE": "django.db.backends.mysql",
                "NAME": "django_database",
                "USER": "django_user",
                "PASSWORD": "django_password",
                "HOST": "django_host",
                "PORT": "3308",
            },
        )

    def test_sqlite_name_takes_priority_over_sqlite_path(self):
        config = self.database_config(
            DJANGO_DB_ENGINE="django.db.backends.sqlite3",
            DJANGO_DB_NAME="preferred.sqlite3",
            DJANGO_SQLITE_PATH="fallback.sqlite3",
            MYSQL_DATABASE="ignored_mysql_database",
        )

        self.assertEqual(config["NAME"], "preferred.sqlite3")

    def test_sqlite_path_is_used_when_name_is_empty(self):
        config = self.database_config(
            DJANGO_DB_ENGINE="django.db.backends.sqlite3",
            DJANGO_SQLITE_PATH=":memory:",
            MYSQL_DATABASE="ignored_mysql_database",
        )

        self.assertEqual(config["NAME"], ":memory:")


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

    def test_login_preserves_safe_next_and_rejects_external_next(self):
        User.objects.create_user("member", "member@example.com", STRONG_PASSWORD)
        credentials = {"username": "member", "password": STRONG_PASSWORD}

        safe_client = Client()
        safe_response = safe_client.post(
            "/accounts/login/",
            {**credentials, "next": "/accounts/profile/edit/"},
        )
        self.assertRedirects(safe_response, "/accounts/profile/edit/")

        external_client = Client()
        external_response = external_client.post(
            "/accounts/login/",
            {**credentials, "next": "https://attacker.example/steal-session"},
        )
        self.assertRedirects(external_response, "/")

    def test_legacy_login_link_preserves_next_for_accounts_login(self):
        response = self.client.get("/login/", {"next": "/command-lab/"})

        self.assertRedirects(
            response,
            "/accounts/login/?next=%2Fcommand-lab%2F",
            fetch_redirect_response=False,
        )

    def test_logout_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        user = User.objects.create_user("member", "member@example.com", STRONG_PASSWORD)
        client.force_login(user)

        response = client.post("/accounts/logout/")

        self.assertEqual(response.status_code, 403)
