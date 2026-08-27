

# The valve with a real reason in it — `ensure_membership`'s shape, which is the
# tree's one measured exception. Nobody is granting here: an identity provider
# asserted an identity, so the wall has no granter to measure and would
# short-circuit anyway. The ceiling that would otherwise be missing is applied
# where a person actually acted, on the connection itself. The reason is written
# at the call site, where a reviewer meets it, and it is counted and printed.
@service
def _neg_ensure_person(
    *,
    tenant: Tenant,
    user: User,
    # role-bound: no granter on this path — an IdP asserted the identity, so the
    # wall short-circuits by design and the ceiling lives on the connection.
    role: str,
) -> Membership:
    membership = Membership(user_id=user.pk, tenant=tenant, role=role)
    membership.save()
    return membership
