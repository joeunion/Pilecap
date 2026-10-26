from uuid import UUID

from ninja import Schema


# Planted: the valve with no sentence a reviewer could disagree with.
class ThingOut(Schema):
    id: UUID
    # not-personal: ok
    email: str
