

def _canary_pat_read() -> str:
    """Planted violation: the credential named outside the client and settings."""
    from django.conf import settings as _canary_settings

    return str(_canary_settings.ZITADEL_PAT)
