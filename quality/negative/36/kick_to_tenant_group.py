

# NEGATIVE (rule 36): the tenant kick — a group_send to `tenant_group` carrying
# an INSTRUCTION TO HANG UP and no payload at all. This is the shape the rule's
# statement was widened for in R4-F3: the rule refuses an org-bearing PAYLOAD on
# the bare tenant group, and a `KICK_TYPE` frame is the one message that
# legitimately goes to every socket in a tenant.
async def _negative_kick_tenant(tenant_id, reason):
    await _layer().group_send(
        tenant_group(tenant_id),
        {"type": KICK_TYPE, "reason": reason},
    )
