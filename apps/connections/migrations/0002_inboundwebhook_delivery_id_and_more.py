"""`InboundWebhook` learns the sender's own id for a delivery (ADR connections-1).

Expand only (rule 22): the column is nullable and Postgres treats every NULL as
distinct, so existing rows satisfy the unique `(connection, delivery_id)` at once.
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
