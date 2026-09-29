"""The self-case's schema block: the Out inherits the archive shape."""

# golden: archive begin
from uuid import UUID

from pydantic import ConfigDict, Field

from apps.core.schemas import ArchivedOut, ListPage, example


class WidgetOut(ArchivedOut):
    """A widget, archived or live — the two archive fields come from the base."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d41"))
    name: str = Field(json_schema_extra=example("Bench press #4"))
    organization_id: UUID = Field(json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d42"))


class WidgetPage(ListPage):
    """A page of widgets, for the door with no query string."""

    items: list[WidgetOut]


# golden: archive end
