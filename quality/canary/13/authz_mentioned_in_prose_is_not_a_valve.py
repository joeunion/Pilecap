

# Planted: a docstring that MENTIONS the valve inside a sentence. The marker is
# spelled, never opened, so it is prose and not a valve — and rule 13 once read
# it as one, because it tested for the marker as a substring of the function.
@service
def canary_valve_mentioned_in_prose(*, tenant: Tenant, actor: Actor) -> None:
    """Frob it.

    Prose that mentions `# authz: handled upstream` is not a comment line.
    """
    return None
