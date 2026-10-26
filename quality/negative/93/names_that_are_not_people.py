from uuid import UUID

from ninja import Schema


# Legal: an exempt `*_name`, a bare `name` on a thing, and a write shape.
class ThingOut(Schema):
    id: UUID
    name: str
    tag_name: str
    email_domains: list[str]


class ThingIn(Schema):
    email: str
