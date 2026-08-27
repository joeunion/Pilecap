"""The subtree read gets a tenant-local prefix index (M4's FINDING 1, rung F1e).

**Expand only** — one `AddIndex`, nothing dropped, nothing altered. The existing
tenant-less `organization_path_prefix` stays: `visible_to()` reaches this table
through a JOIN whose organization side carries no tenant predicate, and that is
the index it takes.

The measurement that justifies this, before it landed, is
`quality/perf-realtime-measurement.md` §5 FINDING 1 — six hat shapes, three
seeded worlds, five candidate index shapes swept with the planner's own verdict
read off `EXPLAIN`. No hat in any world plans worse with this index present.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_audit_trail_reads_tenant_first"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="organization",
            index=models.Index(
                fields=["tenant", "path"],
                name="organization_tenant_prefix",
                opclasses=["", "varchar_pattern_ops"],
            ),
        ),
    ]
