"""The request type every door types against.

`TenantMiddleware` puts the acting tenant **and the hat** on the
request. `HttpRequest` has no such attributes, so the annotations live here and
code that reads `request.tenant` or `request.org` declares this type instead of
reaching for `getattr`.
"""

from __future__ import annotations

from django.http import HttpRequest

from apps.core.models import Organization, Tenant


class TenantRequest(HttpRequest):
    """An `HttpRequest` after `TenantMiddleware` has run."""

    tenant: Tenant | None
    #: The hat — which node of `tenant`'s tree this request acts as.
    #: `None` when no tenant resolved, or when `X-Org` named somewhere the user
    #: holds no role over. Every org-scoped read made with `None` is empty.
    org: Organization | None
