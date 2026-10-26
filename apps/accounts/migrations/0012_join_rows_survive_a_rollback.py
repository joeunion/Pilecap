"""A rollback past 0011 keeps a tenant-realm person's realm, so rolling forward re-homes them.

Forward is a no-op on a database that never rolled back: it touches only suffixed subjects.
Reverse records the realm and tenant in `User.zitadel_sub`, the one column 0010 keeps (rule 22).
"""

from django.db import migrations

#: The staff realm as the join spells it — `apps.accounts.models.STAFF_REALM`, restated.
STAFF_REALM = "staff"
#: How the reverse records a tenant realm's row in `User.zitadel_sub`; 0010 had no tenant realm.
REALM_MARK = "#realm="
TENANT_MARK = "#tenant="


def _unmark(marked: str) -> tuple[str, str, str]:
    """`subject#realm=<id>#tenant=<uuid>` as its three parts; the realm is "" when unmarked."""
    subject, _, rest = marked.strip().partition(REALM_MARK)
    realm, _, tenant_id = rest.partition(TENANT_MARK)
    return subject, realm, tenant_id


def rehome_marked_subjects(apps, schema_editor):
    """Every person a rollback marked goes back to their realm, from a join row or the column."""
    SsoIdentity = apps.get_model("accounts", "SsoIdentity")
    User = apps.get_model("accounts", "User")
    for row in SsoIdentity.objects.filter(connection__isnull=True, subject__contains=REALM_MARK):
        subject, realm, tenant_id = _unmark(row.subject)
        if not realm:
            continue
        row.subject = subject
        row.realm = realm
        row.tenant_id = tenant_id or None
        row.save(update_fields=["subject", "realm", "tenant", "updated_at"])
    # A one-step rollback (0012 -> 0011) leaves the mark on the column and no join row at all.
    for user in User.objects.filter(zitadel_sub__contains=REALM_MARK):
        subject, realm, tenant_id = _unmark(user.zitadel_sub)
        joined = SsoIdentity.objects.filter(connection__isnull=True, user=user, realm=realm)
        if not realm or joined.exists():
            continue
        SsoIdentity.objects.create(
            user=user,
            realm=realm,
            subject=subject,
            tenant_id=tenant_id or None,
            connection=None,
            email=user.email,
        )


def record_realms_for_rollback(apps, schema_editor):
    """Each person joined only in tenant realms: their subject written back with its realm."""
    User = apps.get_model("accounts", "User")
    SsoIdentity = apps.get_model("accounts", "SsoIdentity")
    joined = SsoIdentity.objects.filter(connection__isnull=True)
    staffed = set(joined.filter(realm=STAFF_REALM).values_list("user_id", flat=True))
    recorded: set = set()
    for row in joined.exclude(realm=STAFF_REALM).order_by("created_at"):
        if row.user_id in staffed or row.user_id in recorded:
            continue
        marked = f"{row.subject}{REALM_MARK}{row.realm}{TENANT_MARK}{row.tenant_id or ''}"
        User.objects.filter(pk=row.user_id).update(zitadel_sub=marked)
        recorded.add(row.user_id)
    joined.filter(user_id__in=recorded).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0011_identity_home_and_join")]

    operations = [migrations.RunPython(rehome_marked_subjects, record_realms_for_rollback)]
