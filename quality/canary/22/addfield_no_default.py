"""Planted: a non-nullable AddField with no default."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("example", "{{leaf:example}}")]
    operations = [
        migrations.AddField(
            model_name="widget",
            name="canary_code",
            field=models.CharField(max_length=8),
        ),
    ]
