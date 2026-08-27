"""Feature flags: per tenant, in the tenant's own row, and no third party.

    if is_enabled(tenant, "new_billing"):
        ...

`architecture.md` ruled this: `Tenant.settings` JSON plus one function, and no
flag service. A flag service is a network call on a code path that must not
fail, a second place the truth lives, and a bill; a JSON column is a row the
product already reads on every request.

Resolution, in order:

1. the tenant's own `settings["flags"][name]`, when it names the flag;
2. `settings.FEATURE_FLAGS[name]` — the deployment-wide default;
3. `False`.

**Off is the default and there is no "on for everyone" shortcut.** A flag that
defaults on is a flag that does nothing until somebody remembers to turn it
off, which is the opposite of what it is for. `None` for the tenant means
"inherit", not "off", so a deployment-wide rollout still reaches tenants that
have never been touched.

Flags are **not** authorization. "May this user do this" is `core.authz`;
"does this tenant have this feature yet" is here. Using one for the other is
how a rollout becomes a security boundary nobody tested.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings as django_settings

from apps.core.models import Tenant

FLAGS_KEY = "flags"


def defaults() -> dict[str, bool]:
    """The deployment-wide flag values, from settings."""
    configured = getattr(django_settings, "FEATURE_FLAGS", {}) or {}
    return {str(name): bool(value) for name, value in dict(configured).items()}


def tenant_flags(tenant: Tenant | None) -> dict[str, Any]:
    """What this tenant's row says about flags. Never `None`."""
    if tenant is None:
        return {}
    stored = (tenant.settings or {}).get(FLAGS_KEY)
    return dict(stored) if isinstance(stored, dict) else {}


def is_enabled(tenant: Tenant | None, name: str) -> bool:
    """Whether a feature is on for this tenant.

    A tenant of `None` (an unauthenticated request, a job with no tenant) gets
    the deployment default: there is no tenant to have an opinion, and failing
    closed on a *feature* flag would turn every anonymous page into the old
    behaviour long after the rollout finished.
    """
    override = tenant_flags(tenant).get(name)
    if override is not None:
        return bool(override)
    return defaults().get(name, False)


def enabled_for(tenant: Tenant | None) -> dict[str, bool]:
    """Every known flag and its value for this tenant. For `introspect` and the UI."""
    names = set(defaults()) | set(tenant_flags(tenant))
    return {name: is_enabled(tenant, name) for name in sorted(names)}
