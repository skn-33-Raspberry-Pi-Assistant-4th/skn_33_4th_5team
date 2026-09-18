"""Persistent E-team data models for accounts and community features."""

import uuid

from django.conf import settings
from django.db import models


class TimestampedModel(models.Model):
    """Shared creation and modification timestamps without a separate table."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UserProfile(TimestampedModel):
    """Extension point for a Django User without duplicating account fields."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")

    class Meta:
        ordering = ["user_id"]

    def __str__(self) -> str:
        return f"{self.user.get_username()} profile"


class Post(TimestampedModel):
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="posts")
    title = models.CharField(max_length=200)
    content = models.TextField()

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["-created_at", "-id"], name="portal_post_recent_idx"),
            models.Index(fields=["author", "-created_at"], name="portal_post_author_recent_idx"),
        ]

    def __str__(self) -> str:
        return self.title


class Comment(TimestampedModel):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="comments")
    content = models.TextField()

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["post", "created_at"], name="p_comment_post_created"),
            models.Index(fields=["author", "-created_at"], name="p_comment_author_recent"),
        ]

    def __str__(self) -> str:
        return f"Comment {self.pk} on post {self.post_id}"


class PostLike(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="likes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="post_likes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["post", "user"], name="portal_unique_post_like"),
        ]
        indexes = [
            models.Index(fields=["user", "-created_at"], name="portal_like_user_recent_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user.get_username()} likes post {self.post_id}"


class DrawerItem(TimestampedModel):
    """A user-owned, server-generated CommandLab drawer payload."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="drawer_items")
    title = models.CharField(max_length=200)
    kind = models.CharField(max_length=50)
    payload = models.JSONField()

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["owner", "kind", "-created_at"], name="portal_drawer_owner_kind_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.owner.get_username()}: {self.kind} - {self.title}"


class WrongNote(TimestampedModel):
    """A quiz answer a user explicitly chose to retain as a wrong-note entry."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wrong_notes")
    question_id = models.CharField(max_length=100)
    question = models.TextField()
    choices = models.JSONField()
    selected_choice_id = models.CharField(max_length=16)
    correct_choice_id = models.CharField(max_length=16)
    explanation = models.TextField()
    evidence_ids = models.JSONField()
    supporting_quotes = models.JSONField()

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["owner", "-created_at"], name="p_wrong_owner_recent"),
            models.Index(fields=["owner", "question_id"], name="p_wrong_owner_question"),
        ]

    def __str__(self) -> str:
        return f"{self.owner.get_username()}: {self.question_id}"


class RecommendationRecord(TimestampedModel):
    """A member's recommendation snapshot, independent of the live catalog.

    input_payload holds RecommendationFormInput.model_dump(mode="json");
    response_payload holds the original ChatResponse.model_dump(mode="json").
    Explicit UI values (including None versus False) and extracted conditions
    are retained separately so the original recommendation can be reproduced.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recommendation_records"
    )
    request_id = models.CharField(max_length=120, db_index=True)
    title = models.CharField(max_length=200)
    question = models.TextField()
    answer = models.TextField()
    status = models.CharField(max_length=32)
    input_payload = models.JSONField()
    response_payload = models.JSONField()

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["owner", "-created_at", "-id"], name="portal_rec_owner_recent"),
        ]

    def __str__(self) -> str:
        return f"{self.owner.get_username()}: {self.title}"


class QuestionRecord(TimestampedModel):
    """An immutable, user-owned snapshot of a completed Q&A response."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="qa_records")
    request_id = models.CharField(max_length=100)
    title = models.CharField(max_length=200)
    question = models.TextField()
    answer = models.TextField()
    status = models.CharField(max_length=32)
    response_payload = models.JSONField()
    is_public = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["owner", "-created_at"], name="portal_qa_owner_recent"),
            models.Index(fields=["is_public", "-published_at"], name="portal_qa_public_recent"),
        ]

    def __str__(self) -> str:
        return f"{self.owner.get_username()}: {self.title}"


class AiJob(TimestampedModel):
    """Session-owned remote work; terminal results are finalized exactly once."""

    class Kind(models.TextChoices):
        QA = "qa", "Q&A"
        RECOMMENDATION = "recommendation", "Recommendation"
        QUIZ = "quiz", "Quiz"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE)
    session_hash = models.CharField(max_length=64)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    status = models.CharField(max_length=24, default="queued")
    input_payload = models.JSONField()
    result_payload = models.JSONField(null=True, blank=True)
    error_code = models.CharField(max_length=40, blank=True)
    is_current = models.BooleanField(default=True)
    cancel_requested = models.BooleanField(default=False)
    finalized_at = models.DateTimeField(null=True, blank=True)
    deadline_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    question_record = models.ForeignKey(QuestionRecord, null=True, blank=True, on_delete=models.SET_NULL)
    quiz_id = models.UUIDField(null=True, blank=True)
    save_token = models.UUIDField(default=uuid.uuid4, editable=False)

    class Meta:
        indexes = [
            models.Index(fields=["session_hash", "kind", "is_current"], name="portal_ai_current_idx"),
            models.Index(fields=["expires_at"], name="portal_ai_expiry_idx"),
        ]
