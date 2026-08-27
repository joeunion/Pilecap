

# The same hole, a different app and a different model — the rule is not one
# app's habit. Here the row is written through the manager rather than through
# the instance, so the write witness is the other one.
@service
def _canary_retag_recipient(*, tenant: Tenant, actor: Actor, recipient: Recipient, tag: str) -> Recipient:
    require(actor, "recipient.update", recipient)
    Recipient.objects.filter(pk=recipient.pk).update(external_id=tag)
    return recipient
