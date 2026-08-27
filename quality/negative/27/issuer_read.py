

def _negative_issuer_read() -> str:
    """A different ZITADEL_* setting, read outside the client. Legal.

    W2-R3's RP paths and W2-R4's resource-server validation read the issuer
    from settings all over. The issuer is public — it is the first line of the
    discovery document — and this rule's subject is the credential and the
    client, not the word "zitadel".
    """
    from django.conf import settings as _negative_settings

    return str(_negative_settings.ZITADEL_ISSUER)
