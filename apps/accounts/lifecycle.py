"""How allauth's tables die, declared by the app that owns the concern.

Five tables in two Django apps — `account` and `socialaccount` — that this
product never wrote a line of and can never put a `lifecycle` ClassVar on. They
are declared here rather than in a central dictionary for the reason
`apps.core.lifecycle` gives at length: a shared `THIRD_PARTY_LIFECYCLES` file is
one file every app in a parallel wave has to edit, which is the collision the
whole template is shaped around avoiding. `register(registry)` is discovered,
exactly as `SCHEDULES` and `INSTALLED_APPS` are.

**Why accounts and not somebody else.** `LifecycleRegistry.declare` refuses a
second opinion about the same table rather than letting import order settle it,
so "which app owns this concern" has to be a real answer. It is this one: allauth
is mounted for the sign-in path this app owns end to end (`adapter.py`,
`auth.py`, `oauth.py`, `services.provision_sso_identity`), the rows below are
written by that path and by nothing else, and `services.erase_user` is what
takes a person out of them. `django_session` is deliberately NOT here — it is
`apps/realtime`'s W1 rung, which owns the purge that empties it.

**Bounded, all five, and it is not a shrug.** Every one of these tables hangs off
`accounts.User` or off a row that does, by a CASCADE that allauth declares, so
the population cannot outlive the person — which is what `BOUNDED` says. What
that does *not* say is that a row survives an erasure untouched: it does not.
`erase_user` DELETES the `EmailAddress` and `SocialAccount` rows outright (their
children cascade from there), because a row whose entire content is "this address
belongs to this account" has nothing left to say once the address is gone. The
two facts are compatible and both worth writing down: the cascade is what happens
when the person's row goes, and the sweep is what happens while it stays.

`SocialApp` is the odd one out and its declaration says so.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from allauth.account.models import EmailAddress, EmailConfirmation
from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken

from apps.core.lifecycle import Lifecycle, LifecycleKind

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.core.lifecycle import LifecycleRegistry

#: Named once so every `declare` below says the same thing about where these
#: came from — the registry prints it in the census when two apps disagree.
SOURCE = "apps/accounts/lifecycle.py"


def register(registry: LifecycleRegistry) -> None:
    """Declare allauth's five tables. Discovered by `apps.core.lifecycle`."""
    registry.declare(
        EmailAddress,
        Lifecycle(kind=LifecycleKind.BOUNDED),
        source=SOURCE,
    )
    registry.declare(
        EmailConfirmation,
        Lifecycle(kind=LifecycleKind.BOUNDED),
        source=SOURCE,
    )
    registry.declare(
        SocialAccount,
        Lifecycle(kind=LifecycleKind.BOUNDED),
        source=SOURCE,
    )
    registry.declare(
        SocialToken,
        Lifecycle(kind=LifecycleKind.BOUNDED),
        source=SOURCE,
    )
    registry.declare(
        SocialApp,
        Lifecycle(
            kind=LifecycleKind.UNBOUNDED,
            reason=(
                "the deployment's configured identity providers, not anybody's "
                "data: one row per provider, written by an operator and read on "
                "every login. It hangs off no person and no tenant, so nothing "
                "bounds it — and there is nothing in it to age out. On this tree "
                "the provider is configured from settings rather than from this "
                "table, so the population is usually zero."
            ),
            trigger=(
                "2026-08-24 — a deployment that starts registering providers "
                "per tenant through this table instead of through settings, "
                "which would make it grow with the customer list."
            ),
        ),
        source=SOURCE,
    )
