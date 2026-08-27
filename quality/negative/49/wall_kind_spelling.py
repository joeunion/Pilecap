

@service
def canary_negative_rekeyed_wall(*, tenant: Tenant, actor: Actor, note: str) -> Widget:
    """The re-keyed wall's spelling, which the rule must not mistake for a hole.

    ADR core-22's L1 ruling replaced `actor is None` with `actor.kind ==
    "system"` everywhere the escalation wall and the authorization gates read an
    altitude — an exemption becoming a NAMED audited altitude the row records.
    Every one of those services takes a required actor and simply asks it a
    question. A rule that pattern-matched on the words rather than on the
    signature would fire on the fix and call it the defect.
    """
    if actor.kind == "system":
        return Widget.objects.create(tenant=tenant, name=note)
    require(actor, "widget.create")
    return Widget.objects.create(tenant=tenant, name=note)
