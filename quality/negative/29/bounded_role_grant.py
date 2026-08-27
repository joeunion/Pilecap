

# The wall, used — `set_role`'s real shape. The verb is authorized AND the role
# being granted is measured against the granter's own effective one, which are
# two different questions and both have to be asked.
@service
def _neg_promote_person(
    *, tenant: Tenant, actor: Actor, membership: Membership, role: str
) -> Membership:
    require(actor, "membership.update", membership)
    _refuse_escalation(
        granter=actor.user if actor is not None else None,
        tenant=tenant,
        organization=membership.organization,
        role=role,
    )
    membership.role = role
    membership.save(update_fields=["role", "updated_at"])
    return membership
