

# CANARY (rule 38), the population half: a BRAND NEW org-scoped model, and its
# read shape. Nobody edited quality/rules.yaml, so if the population were a
# hand-list this schema would be unguarded from the day it landed — which is
# exactly the hand-list-goes-stale class the misses ledger carries. The model is
# planted beside it (extra_files) so the pairing runs through the real registry
# walk, not through a name the fixture invented.
class SprocketOut(Schema):  # planted violation
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
