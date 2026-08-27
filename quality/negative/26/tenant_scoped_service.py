

# A tenant-scoped write, taking a tenant-scoped reference. Rule 26 is one level
# down from rule 8 and this is rule 8's floor, not its ceiling: every member of
# the tenant may see this row, so "could you have reached it" has no branch in
# it to answer about. Reading this as a finding would make every service in the
# product one.
@service
def _neg_retire_template(*, tenant: Tenant, actor: Actor, template: MessageTemplate) -> MessageTemplate:
    require(actor, "message_template.retire", template)
    template.retired_at = timezone.now()
    template.save(update_fields=["retired_at", "updated_at"])
    return template
