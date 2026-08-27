"""Reads for the example app.

House rule 12: **reads and writes are separate.** `selectors.py` never writes,
and `services.py` never hands a queryset back for display. The reason is the
doors: the REST route, the MCP tool and (later) the socket consumer all need
the same "one widget, in this tenant, visible to this hat, or a refusal", and a
selector is where that lives once instead of three times, slightly differently.

**Every read is `for_tenant(...).visible_to(...)`** — both halves, always,
because `Widget` is org-scoped (house rule 24, canaried). `for_tenant` answers
*whose data*; `visible_to` answers *which part of their network*, and a read
that stops after the first half hands a sub-seller the whole tenant.

Both halves fail closed: `for_tenant(None)` and `visible_to(None)` each return
nothing, so an unresolved tenant or an unresolved hat reads an empty table
rather than the table. `get_widget` raises `NotFound` rather than returning
`None`, and raises exactly the same `NotFound` for a row in another tenant, in
a sibling branch, or one level *up* the tree as for a row that does not exist —
a 403 there would tell the caller the row exists, which is the fact the scoping
was hiding.

**There is exactly one exception in this module and it is not a widening.**
`get_governing_widget_policy` reads `for_tenant(...).governing(org)` — the rows
on the acting node's *ancestor chain*, nearest first — because `WidgetPolicy`
declared `InheritedDownward` and config is inherited downwards, so a branch is
governed by its parent's policy whether or not it can see it. That is upward
**config resolution**; `visible_to` is untouched by it and stays downward-only,
which is why `list_widget_policies` right beside it shows a branch nothing of
its parent's. A list is a discovery surface and this is not: the caller either
already holds the reference, or is asking the one question whose answer they
are already living under.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.core.exceptions import NotFound
from apps.core.models import ScopedQuerySet, Tenant
from apps.example.models import Widget, WidgetEntry, WidgetPolicy


def list_widgets(*, tenant: Tenant | None, org: Any = None) -> ScopedQuerySet[Widget]:
    """The widgets this hat may see, with the owner the schema reads.

    `org` is the acting organization — `request.org` at the REST door,
    `principal.org` at the machine door, the workflow context in an activity —
    or anything carrying one on `.org` (an `Actor` does). It is a required part
    of the answer and not an optional narrowing: leaving it out returns nothing.

    `select_related("owner", "organization")` is not an optimisation here, it is
    the contract: `WidgetOut` walks both relations for every row, so without it
    a page of fifty is a hundred and one queries. The query pin in the tests is
    what turns removing it into a failure rather than a slow page.

    Filtering, searching and ordering are the route's (`api.py`), from declared
    allow-lists. A selector that took a `**filters` dict would be the same
    unbounded query surface with a tidier name.
    """
    return Widget.objects.for_tenant(tenant).visible_to(org).select_related("owner", "organization")


def get_widget(*, tenant: Tenant | None, widget_id: UUID, org: Any = None) -> Widget:
    """One widget this hat may see, or `NotFound`."""
    widget = list_widgets(tenant=tenant, org=org).filter(pk=widget_id).first()
    if widget is None:
        raise NotFound()
    return widget


def list_widget_policies(*, tenant: Tenant | None, org: Any = None) -> ScopedQuerySet[WidgetPolicy]:
    """The policies this hat may **see**. Downward only, like every other list.

    This is one half of the pair that makes `InheritedDownward` mean something,
    and the half people expect to be widened. It is not. A sub-seller listing
    policies sees the ones set at its own node and at the nodes beneath it, and
    nothing at all from its parent — even though its parent's policy is the one
    that governs it, and even though `get_governing_widget_policy` below will
    hand that very row back.

    **Upward config resolution, never upward visibility** (ADR core-3). The
    distinction is not pedantry: a list is a discovery surface, so widening it
    would tell a branch what its parent has and what it is called, and a hole
    with no edges is the leak. Resolution is not a discovery surface, because
    the caller has to already be holding the reference — or be asking the one
    question ("what governs me?") whose answer they are already living under.
    """
    return WidgetPolicy.objects.for_tenant(tenant).visible_to(org).select_related("organization")


def get_governing_widget_policy(
    *, tenant: Tenant | None, org: Any = None, policy_id: UUID | None = None
) -> WidgetPolicy:
    """The policy that governs this org — the nearest one on its ancestor chain.

    Two questions, one answer, and they are the same question asked with and
    without a name:

    * `policy_id=None` — *what governs me?* The nearest row walking up from the
      acting node to the root. A sub-seller under a seller under HQ resolves the
      seller's policy when there is one and HQ's when there is not, which is
      what "inherited downwards" means when you read it from underneath.
    * `policy_id=<id>` — *does this particular policy govern me?* The same
      chain, narrowed to one row. This is how a door turns an id a client sent
      into a row it may name: a policy at the caller's own node or at any
      ancestor resolves; a **sibling's** does not exist here, and the caller is
      told `not_found` rather than `forbidden`, because not-there and not-yours
      are one answer.

    **`governing()` rather than `visible_to()`, and it is legal here only
    because `WidgetPolicy` declared `InheritedDownward`** — the marker is the
    opt-in, one class attribute wide, and `ScopedQuerySet.governing` raises
    `TypeError` on a model that has not declared it. It is one indexed `IN` over
    the ancestor paths decomposed out of `org.path` in Python, ordered by
    `-organization__depth`, so "nearest wins" is the ordering and not a loop.

    `org=None` resolves nothing, the same fail-closed shape the rest of this
    module has. `NotFound` rather than `None` for the same reason `get_widget`
    raises it: a caller that has to remember to check a `None` is a caller that
    will one day not.
    """
    policies = WidgetPolicy.objects.for_tenant(tenant).governing(org).select_related("organization")
    if policy_id is not None:
        policies = policies.filter(pk=policy_id)
    policy = policies.first()
    if policy is None:
        raise NotFound()
    return policy


def list_widget_entries(
    *, tenant: Tenant | None, org: Any = None, widget_id: UUID | None = None
) -> ScopedQuerySet[WidgetEntry]:
    """The ledger lines this hat may see, newest first, optionally for one widget.

    Scoped exactly as the widgets are — `for_tenant` then `visible_to` — and
    that is not a copied habit: an entry's organization is *derived* from its
    widget's (`WidgetEntry.derive_org_from`), so the two are the same branch by
    construction and a hat that cannot see the widget cannot see its ledger.
    The sibling test in `test_network.py` is what keeps that from being merely
    plausible.

    `select_related("organization")` for the slug the schema reads; the widget
    is not selected, because `WidgetEntryOut` publishes `widget_id` and not the
    row — a ledger line naming its subject's id is a reference, and embedding
    the subject would put a second copy of the widget on every line.
    """
    entries = WidgetEntry.objects.for_tenant(tenant).visible_to(org).select_related("organization")
    if widget_id is not None:
        entries = entries.filter(widget_id=widget_id)
    return entries
