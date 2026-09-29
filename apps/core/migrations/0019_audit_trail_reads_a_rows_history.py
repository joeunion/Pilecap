from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    # NON-ATOMIC, and it has to be: Postgres refuses `CREATE INDEX CONCURRENTLY`
    # inside a transaction block. The audit trail is the product's largest table
    # and every write in the product appends to it, so the plain form's SHARE
    # lock would stall every service in every tenant for as long as the build
    # takes. `CONCURRENTLY` builds beside live writes. House rule 22: expand-only
    # — one index added, nothing dropped, nothing rewritten; a failed build
    # leaves an INVALID index that a re-run of this migration replaces.
    atomic = False

    dependencies = [
        ("core", "0018_roles_are_keys"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="auditentry",
            index=models.Index(
                condition=models.Q(("object_id__isnull", False)),
                fields=["tenant", "object_id", "-created_at"],
                name="auditentry_object_history",
            ),
        ),
    ]
