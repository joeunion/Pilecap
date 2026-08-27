

# CANARY (rule 36): the same leak through the envelope — the serialised
# EventMessage (which carries organization_id) pushed tenant-wide instead of
# through group_for's decision. This is exactly what push_event looked like
# before RT2, and nothing refused it then.
async def _canary_push_envelope(tenant_id, event):  # planted violation
    await _layer().group_send(
        tenant_group(tenant_id),
        {"type": MESSAGE_TYPE, "message": event.model_dump(mode="json")},
    )
