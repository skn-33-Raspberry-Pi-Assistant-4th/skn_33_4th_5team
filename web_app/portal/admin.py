"""Django admin registrations for portal persistence models."""

from django.contrib import admin

from .models import Comment, DrawerItem, Post, PostLike, QuestionRecord, UserProfile, WrongNote


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at", "updated_at")
    search_fields = ("user__username", "user__email")
    list_select_related = ("user",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ("title", "author", "created_at", "updated_at")
    list_filter = ("created_at",)
    search_fields = ("title", "content", "author__username")
    list_select_related = ("author",)
    raw_id_fields = ("author",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("post", "author", "created_at", "updated_at")
    list_filter = ("created_at",)
    search_fields = ("content", "author__username", "post__title")
    list_select_related = ("post", "author")
    raw_id_fields = ("post", "author")
    readonly_fields = ("created_at", "updated_at")


@admin.register(PostLike)
class PostLikeAdmin(admin.ModelAdmin):
    list_display = ("post", "user", "created_at")
    list_filter = ("created_at",)
    search_fields = ("post__title", "user__username")
    list_select_related = ("post", "user")
    raw_id_fields = ("post", "user")
    readonly_fields = ("created_at",)


@admin.register(DrawerItem)
class DrawerItemAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "owner", "created_at", "updated_at")
    list_filter = ("kind", "created_at")
    search_fields = ("title", "owner__username")
    list_select_related = ("owner",)
    raw_id_fields = ("owner",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(WrongNote)
class WrongNoteAdmin(admin.ModelAdmin):
    list_display = ("question_id", "owner", "selected_choice_id", "correct_choice_id", "created_at")
    list_filter = ("created_at",)
    search_fields = ("question_id", "question", "owner__username")
    list_select_related = ("owner",)
    raw_id_fields = ("owner",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(QuestionRecord)
class QuestionRecordAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "status", "is_public", "created_at", "published_at")
    list_filter = ("status", "is_public", "created_at")
    search_fields = ("title", "question", "answer", "owner__username")
    list_select_related = ("owner",)
    raw_id_fields = ("owner",)
    readonly_fields = ("created_at", "updated_at", "request_id", "response_payload")
