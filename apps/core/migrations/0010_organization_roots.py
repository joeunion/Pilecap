"""Give every existing tenant its root node.

From here on, `create_tenant` makes one; this is the one-off for the tenants
that predate the hierarchy. **Every tenant is a tree**, and a tenant without a
root is a tenant whose every org-scoped read returns nothing and whose
memberships have nowhere to sit — so this runs before 0011 fills those in and
before 0012 makes them required.

The root takes the tenant's own name and slug, which is what `create_tenant`
does for a new one: `X-Org: acme` and `X-Tenant: acme` name the same place in
a flat product, and a networked one grows downward from there.

**Reversible**, like every data migration here (house rule 22): the reverse
deletes the roots it made. It refuses to delete a root that has grown children
or memberships, because unwinding a tree that has been used is not a migration,
it is a decision.
"""

from django.db import migrations

# `apps.core.models.ROOT_SEGMENT`, written out rather than imported: a
# migration is a historical record and must not change meaning because a
# constant did.
ROOT_PATH = "0000"


def create_roots(apps, schema_editor):
    Tenant = apps.get_model("core", "Tenant")
    Organization = apps.get_model("core", "Organization")
    with_roots = set(
        Organization.objects.filter(parent__isnull=True).values_list("tenant_id", flat=True)
    )
    Organization.objects.bulk_create(
        [
            Organization(
                tenant=tenant,
                parent=None,
                name=tenant.name,
                slug=tenant.slug,
                path=ROOT_PATH,
                depth=0,
            )
            for tenant in Tenant.objects.exclude(pk__in=with_roots)
        ]
    )


def drop_roots(apps, schema_editor):
    Organization = apps.get_model("core", "Organization")
    Organization.objects.filter(
        parent__isnull=True,
        path=ROOT_PATH,
        children__isnull=True,
        memberships__isnull=True,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_organization"),
    ]

    operations = [
        migrations.RunPython(create_roots, drop_roots),
    ]
