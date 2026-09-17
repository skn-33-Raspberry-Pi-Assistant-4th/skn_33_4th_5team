from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("portal", "0002_questionrecord"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RecommendationRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("request_id", models.CharField(db_index=True, max_length=120)),
                ("title", models.CharField(max_length=200)),
                ("question", models.TextField()),
                ("answer", models.TextField()),
                ("status", models.CharField(max_length=32)),
                ("input_payload", models.JSONField()),
                ("response_payload", models.JSONField()),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="recommendation_records", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at", "-id"],
                "indexes": [models.Index(fields=["owner", "-created_at", "-id"], name="portal_rec_owner_recent")],
            },
        ),
    ]
