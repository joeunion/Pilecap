

# The shape rule 29 exists for, and it is the defect exactly: a role
# arrives from a door and lands on a membership with nothing in between. The
# `require` runs — and answers a different question. `require` asks "may this
# actor act on this object"; a grant also has a ROLE BEING GRANTED, and the
# refusal is about the relationship between that role and the granter's own
# effective one. An admin who may pass "owner" becomes an owner, and the audit
# row says they meant to.
@service
def _canary_enrol_person(*, tenant: Tenant, actor: Actor, user: User, role: str) -> Membership:
    require(actor, "membership.create", tenant)
    membership = Membership(user_id=user.pk, tenant=tenant, role=role)
    membership.full_clean()
    membership.save()
    return membership
