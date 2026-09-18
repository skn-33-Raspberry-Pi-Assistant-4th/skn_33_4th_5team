from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("portal", "0004_aijob"),
    ]

    operations = [
        migrations.AddField(
            model_name="questionrecord",
            name="question_title",
            field=models.CharField(blank=True, max_length=200, null=True),
        ),
        migrations.AddField(
            model_name="questionrecord",
            name="question_title_status",
            field=models.CharField(blank=True, max_length=32, null=True),
        ),
        migrations.AddField(
            model_name="questionrecord",
            name="answer_summary",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="questionrecord",
            name="answer_summary_status",
            field=models.CharField(blank=True, max_length=32, null=True),
        ),
    ]
