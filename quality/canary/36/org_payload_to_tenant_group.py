

# CANARY (rule 36): M4 §8's proposed shape, verbatim — an org-bearing message
# pushed to the bare tenant group. Every socket in the tenant hears one
# branch's rows: the org-blind push the socket probe found, 495 wrong-branch frames per
# 500 sockets at the declared scale.
async def _canary_push_org_payload(tenant_id, organization_id):  # planted violation
    await _layer().group_send(
        tenant_group(tenant_id),
        {
            "type": MESSAGE_TYPE,
            "message": {"name": "widgets.widget.created", "organization_id": str(organization_id)},
        },
    )
