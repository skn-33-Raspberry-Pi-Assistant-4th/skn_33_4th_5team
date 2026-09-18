import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("portal", "0003_recommendationrecord"),
    ]

    operations = [
        migrations.CreateModel(
            name="AiJob",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("session_hash", models.CharField(max_length=64)),
                ("kind", models.CharField(choices=[("qa", "Q&A"), ("recommendation", "Recommendation"), ("quiz", "Quiz")], max_length=20)),
                ("status", models.CharField(default="queued", max_length=24)),
                ("input_payload", models.JSONField()),
                ("result_payload", models.JSONField(blank=True, null=True)),
                ("error_code", models.CharField(blank=True, max_length=40)),
                ("is_current", models.BooleanField(default=True)),
                ("cancel_requested", models.BooleanField(default=False)),
                ("finalized_at", models.DateTimeField(blank=True, null=True)),
                ("deadline_at", models.DateTimeField()),
                ("expires_at", models.DateTimeField()),
                ("quiz_id", models.UUIDField(blank=True, null=True)),
                ("save_token", models.UUIDField(default=uuid.uuid4, editable=False)),
                ("owner", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                ("question_record", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="portal.questionrecord")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["session_hash", "kind", "is_current"], name="portal_ai_current_idx"),
                    models.Index(fields=["expires_at"], name="portal_ai_expiry_idx"),
                ],
            },
        ),
    ]
