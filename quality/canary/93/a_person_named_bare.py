from uuid import UUID

from ninja import Schema


# Planted: a bare `name` on a shape whose noun is a person.
class ThingOwnerOut(Schema):
    id: UUID
    name: str | None = None
