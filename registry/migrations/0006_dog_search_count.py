from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("registry", "0005_moderation_intelligence"),
    ]

    operations = [
        migrations.AddField(
            model_name="dog",
            name="search_count",
            field=models.PositiveBigIntegerField(db_index=True, default=0),
        ),
    ]
