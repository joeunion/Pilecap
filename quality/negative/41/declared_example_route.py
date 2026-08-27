

# A NEW schema that declares an example on every field it owns. The census
# counts declarations, so this adds nothing to the backlog and the ratchet stays
# where it was — which is what "new schemas must declare" has to mean if the
# rule is a ratchet rather than a tax. Firing here would make the only way to
# add a schema be to add debt.

from ninja import Schema
from pydantic import Field

from apps.core.schemas import example


class CanaryBaubleOut(Schema):
    """A bauble, as the probe app would return one."""

    channel: str = Field(json_schema_extra=example("email"))
    status: str = Field(json_schema_extra=example("sent"))
    attempts: int = Field(json_schema_extra=example(1))


@router.get("/bauble/{bauble_id}/", response=CanaryBaubleOut, url_name="bauble-detail")
def canary_bauble_detail(request, bauble_id: str):
    """Retrieve a bauble

    One bauble by id, from the caller's tenant.
    """
    return CanaryBaubleOut(channel="email", status="sent", attempts=1)
