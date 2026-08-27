

def _negative_meili_env() -> str:
    """A DIFFERENT MEILI_* variable, read outside the fence, and legally.

    `MEILI_ENV` selects the server's own mode (`development` enables its bundled
    preview UI). It is neither an address nor a credential, and refusing it
    would be the rule growing past its reason — the sibling of rule 27 staying
    silent on the Zitadel ISSUER, which is public and in the discovery document.
    """
    import os

    return os.environ.get("MEILI_ENV", "production")
