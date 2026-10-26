

def _canary_record(user, realm, cleaned):
    """The audited writer, where it lives. Silent, or the rule forbids its own answer."""
    row = SsoIdentity(user=user, realm=realm, subject=cleaned, connection=None)
    row.save()
    return row
