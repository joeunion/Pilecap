

# NEGATIVE (rule 36): the real push shape — the group is group_for's answer,
# never a bare tenant_group(...) at the push site. Must stay silent (M4 §8's
# first proposed negative).
async def _negative_push_via_group_for(tenant_id, event):
    await _layer().group_send(
        group_for(tenant_id=tenant_id, event=event),
        {"type": MESSAGE_TYPE, "message": event.model_dump(mode="json")},
    )
