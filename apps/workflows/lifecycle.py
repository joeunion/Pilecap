"""How `django_session`'s rows die — declared by the app that sweeps them.

`django.contrib.sessions.models.Session` is not our model and will never grow a
`lifecycle` ClassVar, so it is declared through the third-party hook
(`apps.core.lifecycle.LifecycleRegistry`, ADR core-13): whichever app **owns the
concern** declares it, in its own `lifecycle.py`, discovered and never listed.

## Why this app owns it, and not `apps/accounts`

Rule 31's own `does_not_cover` says this out loud, and it is the reason this
section exists rather than a one-line `register()`:

> AND THE THIRD-PARTY HALF IS AN OWNERSHIP CLAIM: this rule sees that SOME app
> declared `django_session`, never that the right one did.

So the check cannot tell a considered claim from a land grab, and the argument
has to be written where a reader will meet it. `apps/accounts` is the obvious
rival — it owns the person, the login and allauth's own two tables — and it is
the wrong owner here for three reasons, in increasing order of how hard they are
to argue with:

1. **A session is not an identity row.** `EmailAddress` and `SocialAccount` are
   facts about who somebody is, which is `accounts`' subject, and `accounts`
   declares those in its own `lifecycle.py` — whatever kind that app judges
   them to be is that app's call, not asserted from here. A session row is not
   a fact about anybody; it is a server-side artifact carrying its own
   `expire_date`, and what happens to it is a question about *machinery*, not
   about identity.

2. **The purge IS a workflow**, which is this app's whole subject. The rows die
   on a schedule; a schedule in this repository is a `ScheduleDeclaration` that
   `apps.workflows.client.discovered_schedules` hands to the engine, run by this
   app's worker on this app's task queue. Declaring retention in one app while
   the machinery that enforces it lives in another is precisely the split ADR
   core-13 set out to close — the declaration lives where the person who would
   change it is already standing, and for this table that person is editing
   `apps/workflows/activities.py`.

3. **`accounts` could not write the chain even if it wanted to.** Rule 31 is
   satisfied by a callable an activity reaches, a workflow that executes it and
   a `ScheduleDeclaration` that names the workflow. `apps/accounts` sits *below*
   this app in the fixed layer contract (`core` <- `accounts` <- platform <-
   domain, held by `import-linter`), so it cannot name a workflow class, a task
   queue or `SCHEDULES` at all. An `accounts` declaration would be a promise
   whose keeper had to live in another app's territory — which is the
   cross-app coupling the schema discipline exists to prevent, and it would put
   the declaration and its sweeper in two different rungs of a parallel wave.

`LifecycleRegistry.declare` refuses a *second* opinion about the same table
loudly rather than resolving it by import order, so this claim is exclusive: the
day another app thinks it owns `django_session`, the disagreement is a refusal
at startup and a conversation in a plan, not whichever module happened to load
last.

## What is NOT declared here

Only the table this app sweeps. `auth`, `admin`, `contenttypes`, `sites`,
`account` and `socialaccount` are other apps' concerns and other rungs' classes
in rule 31's per-app backlog; declaring a neighbour's table from here would be
the land grab this module's first section argues against.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.sessions.models import Session

from apps.core.lifecycle import Lifecycle, LifecycleKind

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.core.lifecycle import LifecycleRegistry


def register(registry: LifecycleRegistry) -> None:
    """Declare `django_session` purged. Called by `apps.core.lifecycle`'s discovery.

    `purged_by` names `apps.workflows.activities.purge_expired_sessions`, which
    is the **activity itself** rather than a service behind one — the one place
    in this tree where the sweeper is the activity. That activity's docstring
    carries the reason in full: the rows belong to `django.contrib.sessions`,
    the only supported way to remove one is the configured session engine's own
    `SessionStore.clear_expired()`, and wrapping somebody else's storage backend
    in a `@service` would claim an ownership of the table that this declaration
    is careful not to claim.

    Rule 31 walks outwards from the dotted path — callable, to the activity that
    references it (here, the same object), to the `ScheduleDeclaration` whose
    workflow executes it — and finds `workflows.purge-expired-sessions` ->
    `PurgeExpiredSessionsWorkflow` -> `purge_expired_sessions`. What that check
    proves is that the chain is WRITTEN DOWN; whether the schedule is live on a
    server is the lifecycle census's job and never this rule's, which is why the daily
    cadence is stated in `activities.PURGE_EVERY` where an operator can read it.

    **What this closes**: `django_session` was never cleared
    anywhere in this tree — no cron entry, no management command in any
    deployment path, no schedule — so every login since day zero left a row that
    nothing would ever remove, expired or not.
    """
    registry.declare(
        Session,
        Lifecycle(
            kind=LifecycleKind.PURGED,
            purged_by="apps.workflows.activities.purge_expired_sessions",
            reason=(
                "a session past its `expire_date` cannot authenticate anybody, so "
                "keeping it buys nothing and costs a row per login for ever — plus a "
                "standing pile of session data about people who have long since "
                "logged out."
            ),
        ),
        source="apps.workflows.lifecycle",
    )
