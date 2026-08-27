"""The admin is a door, and every door in the product obeys the same rules.

House rule 21, checked over the real registry rather than by reading files: a
raw `ModelAdmin` on a tenant-scoped model is the one place tenancy would not
hold, and "staff act across tenants" is exactly the exemption that makes a
support tool the leak.
"""

from __future__ import annotations

from django.contrib import admin
from django.test import RequestFactory

from apps.core.admin import ServiceModelAdmin
from apps.core.models import ScopedManager


def test_every_registered_admin_inherits_the_house_base() -> None:
    """Read from `admin.site`, so an admin registered anywhere is covered."""
    registered = [
        (model, site_admin)
        for model, site_admin in admin.site._registry.items()
        if model.__module__.startswith("apps.")
    ]
    assert registered, "no product admins registered — the check would pass vacuously"

    for model, site_admin in registered:
        assert isinstance(site_admin, ServiceModelAdmin), (
            f"{type(site_admin).__name__} for {model.__name__} is a raw ModelAdmin"
        )


def test_every_scoped_models_admin_reads_through_for_tenant() -> None:
    """The narrowing is in the base, so this proves the base is actually in play.

    An admin whose `get_queryset` bypassed `ServiceModelAdmin`'s would show one
    tenant's rows to another, and nothing else in the product would notice.

    No database is needed and that is not an accident: `for_tenant(None)` is
    `.none()`, which answers `count()` without a query. Fails closed, provably.
    """
    request = RequestFactory().get("/admin/")
    request.user = None  # type: ignore[assignment]

    for model, site_admin in admin.site._registry.items():
        if not model.__module__.startswith("apps."):
            continue
        if not isinstance(model._default_manager, ScopedManager):
            continue
        # No acting tenant resolves to None, and a scoped read of None is empty.
        assert site_admin.get_queryset(request).count() == 0, (
            f"{model.__name__}'s admin is not narrowed to the acting tenant"
        )
