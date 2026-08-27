"""Put every existing widget on its tenant's root organization.

The honest backfill: a widget written before the tenant had a tree belonged to
the whole tenant, and the root is exactly that statement in the new shape. A
tenant whose tree is still one node deep sees no change at all — everyone who
could read a widget before can read it now — which is what makes org-scoping
the example app safe to do to a product mid-flight.

A product with a real network runs its OWN data migration here instead, mapping
each row to the seller that owns it; this one is the template's, and it is
correct precisely because the template has no network yet.

**Reversible**: the reverse clears the column, which is where 0006 left it.
"""

from django.db import migrations


def place_on_root(apps, schema_editor):
    Widget = apps.get_model("example", "Widget")
    Organization = apps.get_model("core", "Organization")
    roots = {
        organization.tenant_id: organization.pk
        for organization in Organization.objects.filter(parent__isnull=True)
    }
    placed = []
    for widget in Widget.objects.filter(organization__isnull=True):
        root_id = roots.get(widget.tenant_id)
        if root_id is None:
            raise RuntimeError(
                f"Widget {widget.pk} belongs to tenant {widget.tenant_id}, which has no root "
                "organization. Run core's 0010_organization_roots first."
            )
        widget.organization_id = root_id
        placed.append(widget)
    Widget.objects.bulk_update(placed, ["organization"], batch_size=500)


def clear(apps, schema_editor):
    Widget = apps.get_model("example", "Widget")
    Widget.objects.update(organization=None)


class Migration(migrations.Migration):

    dependencies = [
        ("example", "0006_widget_organization"),
    ]

    operations = [
        migrations.RunPython(place_on_root, clear),
    ]
