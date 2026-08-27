"""An invitation records the node it was sent from (ADR core-20, INV-1).

The placement law: a grant comes from where you sent it. `Invitation` becomes
org-scoped, so the acting hat at grant time is written on the row and every
authority question about that row — issue, supersede, revoke, the escalation
wall — is asked at that node rather than at the tenant's root.

**EXPAND / CONTRACT, in the order house rule 22 requires**, and every step is
reversible:

1. the tenant-wide pending constraint comes off FIRST. It is the narrower of
   the two — one live offer per address per TENANT — and the new one is
   strictly wider, so no row can be in violation at any point between them;
2. the column arrives **nullable**, because a non-nullable `AddField` on a
   populated table is the thing rule 22 exists to refuse;
3. it is backfilled, and the backfill's meaning is stated below;
4. only then is it made required, which is the shape `OrgScopedModel` declares;
5. the per-node constraint goes on last, once every row has a node.

**WHAT THE BACKFILL MEANS, said out loud because it is a reading of history and
not a mechanical fill.** Every invitation already in the table was issued before
placement existed, by a service that asked its authority questions at the
tenant's root and landed its membership there. **The root is therefore not a
default — it is what those rows already meant**, written down in the new shape.
Nobody's outstanding offer changes what it will do when it is accepted: it made
a root membership yesterday and it makes a root membership tomorrow. This is the
same reading, and the same sentence, as `0011_membership_organization_backfill`
gave for memberships one rung of the hierarchy earlier.

The reverse clears the column, which is where step 2 left it.

**No product data moves and no visibility changes.** A flat product is a
depth-one tree, so root-placed invitations in a flat tenant are exactly the rows
it had; a tenant with a real tree keeps every existing offer at the root, which
is the widest node and therefore the one nobody is surprised *wider* by.
"""

from django.db import migrations, models
import django.db.models.deletion


def place_on_root(apps, schema_editor):
    """Every invitation written before placement existed meant "the root"."""
    Invitation = apps.get_model("core", "Invitation")
    Organization = apps.get_model("core", "Organization")
    roots = {
        organization.tenant_id: organization.pk
        for organization in Organization.objects.filter(parent__isnull=True)
    }
    placed = []
    for invitation in Invitation.objects.filter(organization__isnull=True):
        root_id = roots.get(invitation.tenant_id)
        if root_id is None:
            # 0010 gives every tenant a root. An invitation whose tenant has
            # none means that migration was skipped or a row was written around
            # it; saying so here is better than leaving a null for step 4 to
            # refuse with a constraint error nobody can read.
            raise RuntimeError(
                f"Invitation {invitation.pk} belongs to tenant {invitation.tenant_id}, "
                "which has no root organization. Run 0010_organization_roots first."
            )
        invitation.organization_id = root_id
        placed.append(invitation)
    Invitation.objects.bulk_update(placed, ["organization"], batch_size=500)


def clear(apps, schema_editor):
    Invitation = apps.get_model("core", "Invitation")
    Invitation.objects.update(organization=None)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0015_subtree_read_takes_a_tenant_prefix"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="invitation",
            name="invitation_one_pending_per_email_per_tenant",
        ),
        migrations.AddField(
            model_name="invitation",
            name="organization",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="%(app_label)s_%(class)s_set",
                to="core.organization",
            ),
        ),
        migrations.RunPython(place_on_root, clear),
        migrations.AlterField(
            model_name="invitation",
            name="organization",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="%(app_label)s_%(class)s_set",
                to="core.organization",
            ),
        ),
        migrations.AddConstraint(
            model_name="invitation",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status", "pending")),
                fields=("tenant", "organization", "email"),
                name="invitation_one_pending_per_email_per_org",
            ),
        ),
    ]
