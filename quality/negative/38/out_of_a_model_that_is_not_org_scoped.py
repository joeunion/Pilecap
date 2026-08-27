

# NEGATIVE (rule 38): a read shape that pairs with no org-scoped model at all.
# `WidgetStatsOut` is the standing instance of this in the tree — an aggregate
# has no single row and therefore no branch — and demanding a narrowing key here
# would be demanding a field with nothing to put in it. Must stay silent.
class BeaconOut(Schema):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    seen_at: datetime
