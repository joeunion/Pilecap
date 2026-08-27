"""Planted: a merge migration — two parents in one app."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("example", "0004_uuid7_primary_key"),
        ("example", "0005_widget_onboarded_at"),
    ]
    operations = []
