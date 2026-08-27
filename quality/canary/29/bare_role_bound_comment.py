

# The valve with nothing in it. An escape hatch nobody has to justify is an off
# switch — the gate says so about its own `# rule-<id>` overrides and about
# `# reach:`, and it says so here. A reason a reviewer cannot disagree with is
# not a reason.
@service
def _canary_waive_the_wall(
    *,
    tenant: Tenant,
    actor: Actor,
    user: User,
    # role-bound:
    role: str,
) -> Membership:
    require(actor, "membership.create", tenant)
    membership = Membership(user_id=user.pk, tenant=tenant, role=role)
    membership.save()
    return membership
