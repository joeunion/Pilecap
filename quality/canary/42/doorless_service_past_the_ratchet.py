

# Planted into an app that already sits at a recorded ratchet, so this also
# demonstrates the backlog refusing to grow: comms may keep the three doorless
# services the census found and may not add a fourth.


@service
def merge_recipients(*, tenant: Tenant, actor: Actor, recipient: Recipient) -> Recipient:
    """Fold one contact into another. No door reaches this."""
    recipient.display_name = recipient.display_name.strip()
    recipient.save(update_fields=["display_name", "updated_at"])
    return recipient
