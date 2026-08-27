"""Planted: a violation claiming an override with no reason."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("example", "{{leaf:example}}")]
    operations = [
        # rule-22
        migrations.AddField(
            model_name="widget",
            name="canary_code2",
            field=models.CharField(max_length=8),
        ),
    ]
