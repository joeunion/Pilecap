

# NEGATIVE (rule 38): the RIGHT shape — a second read shape for `WidgetEntry`
# that declares the narrowing key. Must stay silent, or the rule is a tax on
# adding a schema rather than a rule about the fan-out.
class EntryOut(Schema):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    widget_id: UUID
    note: str
