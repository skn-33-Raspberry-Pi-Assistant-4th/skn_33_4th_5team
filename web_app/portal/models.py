"""Persistent E-team data models for accounts and community features."""

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
