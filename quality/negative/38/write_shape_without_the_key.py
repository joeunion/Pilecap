

# NEGATIVE (rule 38): an IN shape for an org-scoped model, with no
# `organization_id` — and its absence is the enforcement, not an oversight. A
# field a door can send is a field a door can use to write a row into somebody
# else's branch (see `ContactIn` in apps/comms/schemas.py, which says so at
# length). The rule is about what leaves, never about what arrives, and a rule
# that could not tell the two apart would demand the leak it exists to prevent.
class EntryIn(Schema):
    widget_id: UUID
    note: str
