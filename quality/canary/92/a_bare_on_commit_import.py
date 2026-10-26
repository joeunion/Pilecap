from django.db.transaction import on_commit


# Planted: the bare-name spelling of the same registration.
def canary_bare_registered_hook() -> None:
    """Register a hook by the imported name."""

    def hook_on_commit() -> None:
        return None

    on_commit(hook_on_commit, robust=True)
