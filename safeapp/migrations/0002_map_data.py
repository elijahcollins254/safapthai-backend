from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("safeapp", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="MapPerson",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=128)),
                ("phone", models.CharField(blank=True, max_length=32)),
                ("details", models.TextField(blank=True)),
                ("latitude", models.FloatField()),
                ("longitude", models.FloatField()),
                ("status", models.CharField(choices=[("safe", "Safe"), ("at_risk", "At risk")], default="safe", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="MapZone",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=128)),
                ("zone_type", models.CharField(choices=[("safe", "Safe"), ("at_risk", "At risk"), ("hazard", "Hazard")], max_length=16)),
                ("details", models.TextField(blank=True)),
                ("coordinates", models.JSONField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]