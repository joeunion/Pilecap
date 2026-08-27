

@service
def canary_negative_unaudited(*, note: str) -> str:
    """A `@service` that declares NO tenant — outside the population entirely.

    `core.service._declares_tenant` is the one seam that decides who writes a
    row, and a service that never claims to be about a tenant's rows is not
    made into one by this rule. `accounts.create_user`, `core.create_tenant` and
    `workflows.record_run_id` are the live members. If this fires, the rule has
    stopped reading the seam and started censusing every service in the tree.
    """
    return note.strip()
