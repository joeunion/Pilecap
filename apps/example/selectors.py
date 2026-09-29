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

**And since Phase R every one of them ASKS** (ADR core-27, §C6). `actor` is a
required keyword — never optional, because an `actor=None` default is a read
that fails open the first time a caller forgets — and each selector calls
`require(actor, "<kind>.read", ...)` exactly once. **Two questions, two owners,
and they are never merged** (rule 24, BVB-4): `for_tenant`/`visible_to` decide
WHICH rows, `require` decides WHETHER this kind, here. Nothing below filters
rows by permission.

Where the question is asked differs between a list and a get, and the order is
the rule: a `list_` asks at the **acting hat** before it builds the queryset,
because a list has no row to hide; a `get_` asks **after the scoped fetch**,
with the row, at the row's own node — so outside the subtree the fetch has
already said `not_found` and the capability is never consulted. A `system` actor
passes at `allows` step 1, so the onboarding activities are untouched.

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

# golden: archive version move bulk history duplicate attach merge import begin
from typing import Any, Literal
from uuid import UUID

from apps.core.actor import Actor
from apps.core.authz import require
from apps.core.exceptions import NotFound
from apps.core.models import ScopedQuerySet, Tenant
from apps.example.models import Widget

# golden: archive version move bulk history duplicate attach merge import end
# isort: split
# golden: merge import begin
from apps.core.exceptions import Invalid
from apps.core.verbs import Repointed, merge_counts

# golden: merge import end
# isort: split
# golden: attach merge import begin
from apps.tags.models import Tag
from apps.tags.selectors import list_tag_links

# golden: attach merge import end
# isort: split
from apps.example.models import WidgetEntry, WidgetPolicy

# golden: archive version move bulk history duplicate attach merge import begin
#: Which cut of the book a list reads: the live rows (the default), the archived
#: ones alone, or both. The list door publishes it as `?show=`, an enum.
Show = Literal["live", "archived", "all"]


def _archive_cut(rows: ScopedQuerySet[Any], show: Show) -> ScopedQuerySet[Any]:
    """Widen the live book to the cut `show` names — never the tenant or the hat.

    Applied AFTER `for_tenant(...).visible_to(...)`: both widenings only take
    `for_tenant()`'s live exclusion back out, so the tenant and the hat narrow
    the archived cut exactly as they narrow the live one.
    """
    if show == "archived":
        return rows.archived_only()
    if show == "all":
        return rows.including_archived()
    return rows


def _widgets_in(*, tenant: Tenant | None, org: Any, show: Show = "live") -> ScopedQuerySet[Widget]:
    """The scoped read, without the capability. Private, and nothing calls it raw.

    **Why it exists rather than `get_widget` reaching through `list_widgets`.**
    Before Phase R a `get_` was a `list_` with one more filter, and that was
    exactly right: one scoping rule, written once. The two now ask the
    capability at DIFFERENT nodes — a list at the hat, a get at the row — so a
    `get_` reaching through its `list_` would ask twice and ask the first one in
    the wrong place, turning a row a branch may read into a refusal about the
    hat. The SCOPING is still written once; it is this function.
    """
    rows = _archive_cut(Widget.objects.for_tenant(tenant).visible_to(org), show)
    # `archived_by` is selected because the read shape names the archiver on
    # every row; without it an archived page is one query per row.
    return rows.select_related("owner", "organization", "archived_by")


def list_widgets(
    *, tenant: Tenant | None, org: Any = None, actor: Actor, show: Show = "live"
) -> ScopedQuerySet[Widget]:
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

    `show` is the one archive widening a list may ask for: the live book by
    default, `archived` for the archived cut alone, `all` for both.
    """
    # THE CAPABILITY, at the hat, BEFORE the queryset: a list has no row to
    # hide, so somebody without `widget.read` here hears that rather than an
    # empty page that looks like an empty branch.
    require(actor, "widget.read")
    return _widgets_in(tenant=tenant, org=org, show=show)


def get_widget(*, tenant: Tenant | None, widget_id: UUID, org: Any = None, actor: Actor) -> Widget:
    """One widget this hat may see, or `NotFound`.

    **Reach before capability** (ADR core-27, §C8). The scoped fetch is what
    makes a widget in a sibling branch `not_found`; the `require` below is what
    makes one INSIDE the subtree `forbidden` when the hat holds no
    `widget.read`. Asking the other way round would answer `forbidden` for a row
    the caller could never have reached, which tells them it exists.

    The fetch does not go through `list_widgets`: that would ask `widget.read`
    at the HAT, and this asks it at the ROW's node, which is a different
    question the moment a tenant withholds the key on one branch.

    **Archived rows are found too** (`show="all"`): an archived widget answers
    its detail read-only, and the restore and every refused write have to find
    the row before they can say what it is.
    """
    widget = _widgets_in(tenant=tenant, org=org, show="all").filter(pk=widget_id).first()
    if widget is None:
        raise NotFound()
    require(actor, "widget.read", widget)
    return widget


# golden: archive version move bulk history duplicate attach end
def get_widget_merge_preview(
    *, tenant: Tenant | None, actor: Actor, widget: Widget, into: Widget
) -> tuple[Repointed, ...]:
    """What merging `widget` into `into` WOULD move, per owning app. Writes nothing.

    The dry run a person reads before confirming: each repointer's title and
    how many of its rows would leave the loser. Asked as the merge itself is —
    `widget.merge` on both records — because the counts describe two records
    only somebody who may merge them has any business comparing.
    """
    if widget.pk == into.pk:
        raise Invalid({"into": ["A record cannot be merged into itself."]})
    require(actor, "widget.merge", widget)
    require(actor, "widget.merge", into)
    return merge_counts(tenant=tenant, loser=widget, noun="widget")


# golden: attach begin
def list_widget_tags(*, tenant: Tenant | None, actor: Actor, widget: Widget) -> list[Tag]:
    """The words on this widget, as this hat sees them — what its detail answers.

    Read through the tags app's own selector — the subject resolved and the
    read asked there — so the detail answers exactly what `/tag-links/?subject=`
    would. Archived words are included: the link stands, the word is read-only.
    """
    # The words are tags: reading them is `tag.read`; the links under them are
    # asked `tag_link.read` by the tags app's own selector.
    # hat-scoped: a word is tenant-wide and read where the reader stands, exactly
    # as the tags app's own list of words asks it.
    require(actor, "tag.read")
    links = list_tag_links(tenant=tenant, actor=actor, subject=f"widget:{widget.pk}")
    return [link.tag for link in links]


# golden: attach merge import end


def list_widget_policies(
    *, tenant: Tenant | None, org: Any = None, actor: Actor, show: Show = "live"
) -> ScopedQuerySet[WidgetPolicy]:
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
    require(actor, "widget_policy.read")
    rows = _archive_cut(WidgetPolicy.objects.for_tenant(tenant).visible_to(org), show)
    return rows.select_related("organization", "archived_by")


def get_widget_policy(
    *, tenant: Tenant | None, policy_id: UUID, org: Any = None, actor: Actor
) -> WidgetPolicy:
    """One policy this hat may SEE — its own node's or one beneath — archived or not.

    The downward read, not `get_governing_widget_policy`'s upward one: this is
    the row an archive or a restore acts on, and only the node that set a
    policy (or one above it) may take it out of the book. A policy that merely
    governs this hat from above is `not_found` here, exactly as it is absent
    from `list_widget_policies`.
    """
    policy = (
        WidgetPolicy.objects.for_tenant(tenant)
        .including_archived()
        .visible_to(org)
        .select_related("organization", "archived_by")
        .filter(pk=policy_id)
        .first()
    )
    if policy is None:
        raise NotFound()
    require(actor, "widget_policy.read", policy)
    return policy


def get_governing_widget_policy(
    *, tenant: Tenant | None, org: Any = None, policy_id: UUID | None = None, actor: Actor
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

    **This is the one `get_` in the app that asks at the HAT rather than at the
    row**, and the reason is the same one that makes `governing()` legal here.
    The row this returns lives on an ANCESTOR node, where the caller holds
    nothing at all — config resolves upward, visibility never does (ADR core-3,
    §A5c) — so asking `widget_policy.read` at the row would refuse everybody
    who is governed by a parent's policy, which is precisely the population the
    function exists to answer. The question asked is therefore the acting hat's:
    may you read widget policies where you are standing.
    """
    require(actor, "widget_policy.read")
    policies = WidgetPolicy.objects.for_tenant(tenant).governing(org).select_related("organization")
    if policy_id is not None:
        policies = policies.filter(pk=policy_id)
    policy = policies.first()
    if policy is None:
        raise NotFound()
    return policy


def list_widget_entries(
    *, tenant: Tenant | None, org: Any = None, widget_id: UUID | None = None, actor: Actor
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
    require(actor, "widget_entry.read")
    entries = WidgetEntry.objects.for_tenant(tenant).visible_to(org).select_related("organization")
    if widget_id is not None:
        # A merged survivor's ledger is its own lines AND its losers': a merge
        # keeps each line where it was written (`Widget.merge_keeps`), and
        # `Widget.lineage` is the one widening that reads them together.
        subject = (
            Widget.objects.for_tenant(tenant)
            .including_archived()
            .visible_to(org)
            .filter(pk=widget_id)
            .first()
        )
        entries = entries.filter(
            widget_id__in=[widget_id] if subject is None else Widget.lineage(subject)
        )
    return entries
