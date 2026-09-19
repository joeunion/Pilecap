

def _canary_record(user, cleaned):
    """The audited writer, where it lives. Silent, or the rule forbids its own answer."""
    user.zitadel_sub = cleaned
    user.save(update_fields=["zitadel_sub"])
    return user
