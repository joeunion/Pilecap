from uuid import UUID

from ninja import Schema


# Planted: a person's address on a published shape, neither marked nor declared.
class ThingOut(Schema):
    id: UUID
    email: str
