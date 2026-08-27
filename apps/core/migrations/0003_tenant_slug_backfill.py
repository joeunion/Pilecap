"""Give every existing tenant a slug before the column is made required.

A data migration is its own file, uses `apps.get_model` rather than importing
the model class, and states its reverse deliberately — going back only makes
the column optional again, so there is nothing to undo.
"""

from django.db import migrations
from django.utils.text import slugify


def backfill_slugs(apps, schema_editor):  # type: ignore[no-untyped-def]
    Tenant = apps.get_model("core", "Tenant")
    taken = set(
        Tenant.objects.exclude(slug=None).values_list("slug", flat=True),
    )
    for tenant in Tenant.objects.filter(slug=None).order_by("created_at"):
        base = slugify(tenant.name) or f"tenant-{tenant.pk.hex[:8]}"
        slug = base
        suffix = 2
        while slug in taken:
            slug = f"{base}-{suffix}"
            suffix += 1
        taken.add(slug)
        tenant.slug = slug
        tenant.save(update_fields=["slug"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_tenant_slug_and_membership"),
    ]

    operations = [
        migrations.RunPython(backfill_slugs, migrations.RunPython.noop),
    ]
