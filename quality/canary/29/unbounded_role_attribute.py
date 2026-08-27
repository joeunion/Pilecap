

# The same defect through the OTHER role position: an attribute assignment
# rather than a constructor keyword. A promotion is a grant with an extra step,
# and a rule that watched only constructors would have caught `add_membership`
# and missed `set_role` — half a wall is not a wall.
@service
def _canary_promote_person(
    *, tenant: Tenant, actor: Actor, membership: Membership, role: str
) -> Membership:
    require(actor, "membership.update", membership)
    membership.role = role
    membership.save(update_fields=["role", "updated_at"])
    return membership
