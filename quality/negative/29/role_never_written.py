

# A role-named parameter that never reaches a role position: it narrows a
# lookup and grants nothing. Reading this as a grant would make every service
# that so much as filters by role a finding, and a rule ratcheted into noise is
# a rule nobody reads.
@service
def _neg_count_by_role(*, tenant: Tenant, actor: Actor, role: str) -> int:
    require(actor, "membership.list", tenant)
    return Membership.objects.for_tenant(tenant).filter(role=role).count()
