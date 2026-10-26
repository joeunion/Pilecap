from uuid import UUID

from ninja import Field, Schema

from apps.core.schemas import example, personal


# Legal: the person's field declares itself.
class ThingOut(Schema):
    id: UUID
    email: str = Field(json_schema_extra=personal(example("dana@example.com")))
