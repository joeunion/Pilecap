from django.db import transaction


# Planted: a hook registered outside every declared seam.
def canary_hand_registered_hook() -> None:
    """Register a hook by hand."""

    def hook_on_commit() -> None:
        return None

    transaction.on_commit(hook_on_commit, robust=True)
