"""The identity realm adapters, and the one reader of which one this deployment runs.

Each module here implements `apps.accounts.realm.IdentityRealm` over one
vendor. `current()` is how every caller gets the deployment's: the activities
and the reconciler ask it, never import an adapter by name, so the day a second
adapter is real the change is one setting rather than a sweep of call sites.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from apps.accounts.realm import IdentityRealm

#: The adapter a deployment runs when `IDENTITY_REALM_ADAPTER` names none.
DEFAULT_ADAPTER = "apps.accounts.realms.zitadel.ZitadelRealm"


def current() -> IdentityRealm:
    """This deployment's identity realm adapter — `IDENTITY_REALM_ADAPTER`, default Zitadel.

    Refuses at the first call, naming the setting, when the path names
    something that does not answer the port: a typo that fell back to the
    default would run the wrong vendor silently, and an object missing an
    operation would fail on the first tenant whose run reached it.
    """
    path = str(getattr(settings, "IDENTITY_REALM_ADAPTER", "") or DEFAULT_ADAPTER)
    try:
        adapter = import_string(path)()
    except ImportError as error:
        raise ImproperlyConfigured(
            f"IDENTITY_REALM_ADAPTER names {path!r}, which does not import: {error}"
        ) from error
    if not isinstance(adapter, IdentityRealm):
        raise ImproperlyConfigured(
            f"IDENTITY_REALM_ADAPTER names {path!r}, which does not answer "
            "apps.accounts.realm.IdentityRealm; an adapter implements every one of "
            "its operations."
        )
    return adapter
