

def _negative_behavioural_setting() -> int:
    """A storage-adjacent setting that dials nothing, read outside the fence.

    `AWS_QUERYSTRING_EXPIRE` is neither a bucket, an address nor a credential: it
    configures how long django-storages' own signatures last. Naming it in the
    wrong file is configuration drift, not a second door, and a rule that refused
    it would be growing past its reason — the sibling of rule 33 staying silent
    on `MEILI_ENV` and rule 27 on the Zitadel issuer.
    """
    from django.conf import settings

    return int(settings.AWS_QUERYSTRING_EXPIRE)
