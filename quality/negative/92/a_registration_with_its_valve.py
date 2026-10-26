from django.db import transaction


# Legal: a registration that carries the rule's valve, and a docstring that only names the call.
def negative_valved_hook() -> None:
    """Quote `transaction.on_commit(hook)` in prose; the prose is not a site."""

    def hook_on_commit() -> None:
        return None

    # rule-92: a scratch hook in the self-test's negative corpus, declared here on purpose
    transaction.on_commit(hook_on_commit, robust=True)
