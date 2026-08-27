"""`InboundWebhook` learns the sender's own id for a delivery (rung W6).

ADR connections-1. `x-delivery-id` has been kept and stored on every row since
this app landed and read by nothing, so a provider retry made a second row and a
second hand-off.

**Expand only — there is nothing to contract and nothing to backfill**, which is
what makes this the cheap half of house rule 22. The column is nullable, so
every existing row takes NULL; the constraint is unique over
`(connection, delivery_id)`, and Postgres treats every NULL as distinct, so
every one of those rows satisfies it the moment it is added. No `RunPython`, no
window where the table is half-converted, and both operations reverse by
themselves.

The rows that predate this migration keep NULL for ever, and that is honest
rather than a gap: nobody recorded what those senders called their deliveries,
and inventing an id now would claim knowledge this product never had.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("connections", "0001_initial"),
        ("core", "0012_membership_organization_required"),
    ]

    operations = [
        migrations.AddField(
            model_name="inboundwebhook",
            name="delivery_id",
            field=models.CharField(blank=True, max_length=200, null=True),
        ),
        migrations.AddConstraint(
            model_name="inboundwebhook",
            constraint=models.UniqueConstraint(
                fields=("connection", "delivery_id"),
                name="inboundwebhook_unique_delivery_per_connection",
            ),
        ),
    ]
