"""Put every existing membership on its tenant's root.

The honest backfill for a tenancy that had no tree: everybody who belonged to a
tenant belonged to all of it, and the root is exactly that statement in the new
shape. Nobody gains or loses a row's visibility — a depth-one tree is the flat
model — which is what makes this migration safe to run against a live product.

**Reversible**: the reverse clears the column, which is where 0009 left it.
"""

from django.db import migrations


def place_on_root(apps, schema_editor):
    Membership = apps.get_model("core", "Membership")
    Organization = apps.get_model("core", "Organization")
    roots = {
        organization.tenant_id: organization.pk
        for organization in Organization.objects.filter(parent__isnull=True)
    }
    placed = []
    for membership in Membership.objects.filter(organization__isnull=True):
        root_id = roots.get(membership.tenant_id)
        if root_id is None:
            # 0010 gives every tenant a root; a membership whose tenant has
            # none means that migration was skipped or a row was written around
            # it. Saying so is better than leaving a null the next migration
            # will refuse with a constraint error nobody can read.
            raise RuntimeError(
                f"Membership {membership.pk} belongs to tenant {membership.tenant_id}, "
                "which has no root organization. Run 0010_organization_roots first."
            )
        membership.organization_id = root_id
        placed.append(membership)
    Membership.objects.bulk_update(placed, ["organization"], batch_size=500)


def clear(apps, schema_editor):
    Membership = apps.get_model("core", "Membership")
    Membership.objects.update(organization=None)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0010_organization_roots"),
    ]

    operations = [
        migrations.RunPython(place_on_root, clear),
    ]
