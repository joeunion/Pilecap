

# Legal: every bulleted code is one the operation's `x-refusal-codes` carries.
from typing import Any as _AnyCarried47
from uuid import UUID as _UUIDCarried47

from apps.core.requests import TenantRequest as _TenantRequestCarried47


@router.get(
    "/negative-bullet/{widget_id}/", response={200: dict}, url_name="widget_negative_bullet-detail"
)
def negative_probe_bulleted_route(
    request: _TenantRequestCarried47, widget_id: _UUIDCarried47
) -> _AnyCarried47:
    """Read a carried probe widget

    Read a carried probe widget.

    Refusals you can get here:

    * `404 not_found` — no widget your acting organization can see has that id.
    """
    return {}
