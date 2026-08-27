

@service
def announce_widget_onboarded(*, tenant: Tenant, actor: Actor | None = None, note: str) -> Widget:
    """**An enumerated absence is an absence — never a licence to default.**

    Deliberately re-declares a name that IS on rule 49's absence list
    (`example.announce_widget_onboarded`, core-22 absence 6), so the planted
    form arrives already exempt. It must fire anyway.

    The list excuses a service for taking NO actor: that is a claim a reviewer
    can read and the ADR grounds it. It cannot excuse a DEFAULT, because a
    default is not a claim about anything — it is a signature that says the
    service records a person and a call site that quietly says otherwise, and no
    absence in core-22 describes that. Without this canary the list would be a
    way to buy silence for the exact shape the rule was written to catch.

    Appending shadows the module-level name, which is what makes an allow-listed
    service plantable at all: the probe reads `vars(module)`, so the last
    definition is the one the census sees.
    """
    return Widget.objects.create(tenant=tenant, name=note)
