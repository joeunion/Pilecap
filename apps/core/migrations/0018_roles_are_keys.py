"""A role becomes a key, and the three tables that give a tenant its own.

EXPAND ONLY (house rule 22). Two columns widen and lose their `choices`; three
tables arrive; no row is rewritten. The forward `RunPython` writes nothing
either — it is a CENSUS, and its whole job is to refuse rather than to repair.

**Why a census and not a repair.** `Membership.role` and `Invitation.role`
carried `choices` until this migration, so on the template every value is one of
three and the census is a formality. On a product that added a fourth enum
value, it is the opposite: after this migration the column accepts any string,
and a value no `roles.py` declares and no `core.Role` row names would silently
become a role that holds NOTHING — a person who could administer a tenant
yesterday and can do nothing today, with no error anywhere. The census turns
that into a refused `migrate` that names the tenant, the value and how many rows
carry it, and the CHANGELOG says the fix: declare it in a `roles.py`, or create
it as data first. A repair could not be written, because only the product knows
what the fourth value was supposed to mean.

**The reverse is a no-op, and the schema reversal is exact** (principle 6):
`0018` backwards restores `0017`'s columns byte for byte and drops the three
tables. What that LOSES is data and it is named here rather than discovered: a
tenant's custom roles, its deltas on declared roles, and every per-person grant
go with the tables. Nothing else in the tree reads them, so a reversal is safe
for the schema and irreversible for the rows — the ordinary shape of a drop, and
the reason this migration creates rather than converts.
"""

from typing import Any

import django.db.models.deletion
from django.db import migrations, models

import apps.core.ids


def census(apps, schema_editor):  # type: ignore[no-untyped-def]
    """Refuse a membership or a pending invitation naming a role nothing knows.

    The allowed set is the same three layers `add_membership` validates against,
    read at THIS migration's state: `owner` (the platform's one role), every key
    an app declares in its `roles.py`, every `core.Role` row THAT TENANT owns,
    and `""` — the roleless membership, which is a legal state of the column.

    Read-only, so it is idempotent by construction (principle 16): running it
    twice refuses twice or passes twice, and it can never half-apply.

    `role_declarations()` is imported here rather than at module scope because a
    migration module is imported by `makemigrations` in states where the app
    registry is not the live one; inside the function the declarations are the
    deployment's own, which is what the refusal is about.
    """
    from apps.core.authz import OWNER_ROLE, role_declarations

    Membership = apps.get_model("core", "Membership")
    Invitation = apps.get_model("core", "Invitation")
    Role = apps.get_model("core", "Role")
    Tenant = apps.get_model("core", "Tenant")

    declared = set(role_declarations())
    custom: dict[object, set[str]] = {}
    for tenant_id, key in Role.objects.values_list("tenant_id", "key"):
        custom.setdefault(tenant_id, set()).add(str(key))

    # (tenant_id, value) -> count, over both columns at once. One message per
    # pair, because "this tenant has four memberships on `viceroy`" is the
    # sentence an operator can act on; four messages naming one row each is the
    # same fact spread out until it stops reading as one problem.
    offenders: dict[tuple[object, str], int] = {}

    def look(rows: Any) -> None:
        for tenant_id, value in rows:
            role = str(value or "")
            allowed = {OWNER_ROLE, ""} | declared | custom.get(tenant_id, set())
            if role in allowed:
                continue
            offenders[(tenant_id, role)] = offenders.get((tenant_id, role), 0) + 1

    look(Membership.objects.values_list("tenant_id", "role").iterator(chunk_size=2000))
    look(
        Invitation.objects.filter(status="pending")
        .values_list("tenant_id", "role")
        .iterator(chunk_size=2000)
    )
    if not offenders:
        return

    slugs = dict(Tenant.objects.values_list("id", "slug"))
    lines = [
        f"  tenant {slugs.get(tenant_id, tenant_id)!s}: role {role!r} on {count} row(s)"
        for (tenant_id, role), count in sorted(
            offenders.items(), key=lambda item: (str(slugs.get(item[0][0], "")), item[0][1])
        )
    ]
    raise RuntimeError(
        "core.0018 refuses: a role is a KEY from this migration on, and these values name "
        "no role this deployment has — not `owner`, not a key any app declares in its "
        "`roles.py`, and not a `core.Role` row the tenant owns:\n"
        + "\n".join(lines)
        + "\n\nAfter this migration the column would accept them and they would hold "
        "NOTHING, which is a person losing every capability with no error anywhere. "
        "Declare it in a `roles.py` or create it as data first, then migrate again."
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0017_tenant_leading_recency_composite"),
    ]

    operations = [
        migrations.AlterField(
            model_name="invitation",
            name="role",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AlterField(
            model_name="membership",
            name="role",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.CreateModel(
            name="Grant",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=apps.core.ids.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("permission", models.CharField(max_length=255)),
                (
                    "effect",
                    models.CharField(
                        choices=[("allow", "Allow"), ("withhold", "Withhold")],
                        default="allow",
                        max_length=8,
                    ),
                ),
                (
                    "membership",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="grants",
                        to="core.membership",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(app_label)s_%(class)s_set",
                        to="core.tenant",
                    ),
                ),
            ],
            options={
                "verbose_name": "grant",
                "verbose_name_plural": "grants",
                "ordering": ["-created_at"],
                "abstract": False,
                "indexes": [models.Index(fields=["tenant", "-created_at"], name="grant_recency")],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("membership", "permission"),
                        name="grant_unique_permission_per_membership",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="Role",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=apps.core.ids.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("key", models.SlugField(max_length=64)),
                ("name", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True)),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(app_label)s_%(class)s_set",
                        to="core.tenant",
                    ),
                ),
            ],
            options={
                "verbose_name": "role",
                "verbose_name_plural": "roles",
                "ordering": ["-created_at"],
                "abstract": False,
                "indexes": [models.Index(fields=["tenant", "-created_at"], name="role_recency")],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("tenant", "key"), name="role_unique_key_per_tenant"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="RolePermission",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=apps.core.ids.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("role_key", models.CharField(max_length=64)),
                ("permission", models.CharField(max_length=255)),
                (
                    "effect",
                    models.CharField(
                        choices=[("include", "Include"), ("exclude", "Exclude")],
                        default="include",
                        max_length=8,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(app_label)s_%(class)s_set",
                        to="core.tenant",
                    ),
                ),
            ],
            options={
                "verbose_name": "role permission",
                "verbose_name_plural": "role permissions",
                "ordering": ["-created_at"],
                "abstract": False,
                "indexes": [
                    models.Index(fields=["tenant", "-created_at"], name="rolepermission_recency")
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("tenant", "role_key", "permission"),
                        name="rolepermission_unique_per_role",
                    )
                ],
            },
        ),
        # LAST, and that is the point: the census reads `core.Role` rows, so it
        # has to run at a state where that table exists. Reverse is a no-op —
        # there is nothing to undo about a read.
        migrations.RunPython(census, migrations.RunPython.noop),
    ]
