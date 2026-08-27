

def _canary_promote(membership):
    membership.role = "owner"
    membership.save(update_fields=["role"])
    Membership.objects.filter(pk=membership.pk).update(role="admin")
