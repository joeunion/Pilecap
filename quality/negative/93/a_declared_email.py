from uuid import UUID

from ninja import Schema


# Legal: a lexicon hit that is not a person's, declared with its reason.
class ThingOut(Schema):
    id: UUID
    # not-personal: the shared inbox of a team, never one person's address
    email: str
