

# CANARY (rule 38): a second read shape for an existing OrgScopedModel
# (`WidgetEntry`), written by somebody who did not know the fan-out narrows on
# `organization_id`. The payload built from this shape carries no branch, and
# `bridge.group_for` reads no-branch as TENANT-WIDE — every socket in the tenant
# hears the entry. This is the seam rule 36 structurally cannot see: there is no
# bad push here, only a missing field.
class EntryOut(Schema):  # planted violation
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    widget_id: UUID
    note: str
    created_at: datetime
