

# Planted: a refusal bullet the operation's `x-refusal-codes` does not carry.
from typing import Any as _AnyBullet47
from uuid import UUID as _UUIDBullet47

from apps.core.requests import TenantRequest as _TenantRequestBullet47


@router.get(
    "/canary-bullet/{widget_id}/", response={200: dict}, url_name="widget_canary_bullet-detail"
)
def canary_probe_bulleted_route(
    request: _TenantRequestBullet47, widget_id: _UUIDBullet47
) -> _AnyBullet47:
    """Read a bulleted probe widget

    Read a bulleted probe widget.

    Refusals you can get here:

    * `409 conflict` — a refusal this operation's document does not carry.
    """
    return {}
