"""Planted: a RunPython nobody can roll back."""

from django.db import migrations


def forwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("example", "{{leaf:example}}")]
    operations = [migrations.RunPython(forwards)]
