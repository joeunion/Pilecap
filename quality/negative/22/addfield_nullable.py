"""Negative: the expand shape — nullable first."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("example", "{{leaf:example}}")]
    operations = [
        migrations.AddField(
            model_name="widget",
            name="neg_note",
            field=models.CharField(max_length=8, null=True),
        ),
    ]
