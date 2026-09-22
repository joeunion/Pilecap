"""A read is a permission on this door too: what a hat may READ, it may hear.

`test_hierarchy.py` proves the **rows** half — a connection joins its hat's
subtree, so a branch-B socket never hears a branch-A row. That was one of the
two questions the REST door asks and it was the only one this door asked. The
other is ADR core-27's: `list_widgets` refuses a member whose `widget.read` was
withheld, while the socket went on pushing `example.widget.created` to them for
the life of the connection. Two doors, one question, two answers — the
disagreement `architecture.md` calls a finding, and rule 46 is the rule it
breaks.

**The shape that closes it.** A connection computes `read_kinds(user, tenant,
hat)` once, at connect, beside the subtree read — the *second* of the two reads
this door makes, and both are made once — and holds it as `self.reads`. A frame
is delivered when the kind its name is about is in that set. The narrowing is
per **hat** and not per org × kind (Overrule 1, ratified 2026-09-15): REST asks
once at the hat through `where_of`, so a per-org socket set would disagree with
the list the same client just fetched.

**The group set does not move**, and that is the load-bearing half of the trade:
`tenant + one org group per subtree id + user` is what it was, so a flat product
still joins three groups and the connect cost is still `1 + |subtree| + 1`.
Kinds are decided per frame, in Python, against a frozenset — no query, which is
what `test_a_withheld_read_costs_no_query_per_frame` pins.

**An event with no kind behind it is heard by everybody in the tenant.**
`search.engine.degraded` is a fact about the deployment's search engine and
there is no row anybody could hold a read on; `apps/search/events.py` says so in
its `EVENT_KINDS` with the reason beside it, and the census below is what makes
that declaration compulsory rather than optional.

Everything here drives the **real chain** — `emit()` → the spine's
`push_realtime` activity → `core.bridge` → the channel layer → the consumer →
the wire — for the reason `test_spine_end_to_end.py` gives: the hops between
those arrows are where a rename goes unnoticed until a customer notices first.
"""

from __future__ import annotations

import importlib
import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core import authz, bridge
from apps.core.actor import actor_for, system_actor
from apps.core.asyncdb import run_db
from apps.core.models import Grant, Membership, Organization, Role, RolePermission, Tenant
from apps.core.services import add_membership, set_role
from apps.realtime.bridge import kind_of_event, org_group, tenant_group, user_group
from apps.realtime.tests.test_hierarchy import (
    EVENT_NAME,
    PASSWORD,
    Network,
    _build_network,
    _emit_and_push,
    hat,
    in_branch,
)
from apps.realtime.tests.websocket import Socket
from apps.usage.events import THRESHOLD_CROSSED

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

#: A kind-bearing event from a second app, so "hears one kind and not another"
#: is provable on ONE socket with the group held constant — the shape
#: `test_socket_scopes.py` uses for the ceiling, applied to the read set.
MESSAGE_EVENT = "comms.message.sent"

#: The event with no kind behind it: a deployment-wide fact about the search
#: engine, org-less, mapped to `None` in `apps/search/events.py`. It is the
#: non-vacuity control everywhere below — a socket that hears this one is a
#: socket that is alive, so its silence about a widget is a decision.
ENGINE_EVENT = "search.engine.degraded"


@dataclass(frozen=True)
class Readers:
    """Two `member` hats on the same branch, alike in everything but one key.

    They sit at `branch_a` and the rows are written at `leaf_a1`, which is
    inside both their subtrees — so the GROUP is held constant and the only
    thing that can separate them is the read set. A pair rather than one socket
    and an assertion: "nobody received it" and "the right one did not receive
    it" are different claims, and only the second one is the property.
    """

    network: Network
    allowed: User
    withheld: User


@pytest.fixture
def network(tenant: Tenant, owner: User) -> Network:
    """The tree `test_hierarchy` builds, from the same builder."""
    return _build_network(tenant=tenant, owner=owner)


@pytest.fixture
def readers(network: Network) -> Readers:
    system = system_actor(tenant=network.tenant)

    def build() -> Readers:
        people: list[User] = []
        for email in ("allowed@example.com", "withheld@example.com"):
            person = create_user(email=email, password=PASSWORD)
            add_membership(
                user=person,
                tenant=network.tenant,
                organization=network.branch_a,
                is_default=True,
                role=Membership.Role.MEMBER,
                actor=system,
            )
            people.append(person)
        # A raw `withhold` row: the services that hand permissions out are P4's,
        # and the criteria say a raw create is legal until they land. The key is
        # `widget.read` and nothing else — `message.read` stays held, which is
        # what makes the second frame below a control rather than a repeat.
        Grant.objects.create(
            tenant=network.tenant,
            membership=Membership.objects.get(user=people[1], tenant=network.tenant),
            permission="widget.read",
            effect=Grant.Effect.WITHHOLD,
        )
        return Readers(network=network, allowed=people[0], withheld=people[1])

    return build()


def _approver(tenant: Tenant) -> str:
    """A custom role whose collection holds one WRITE key and no reads at all.

    The same role `apps/core/tests/test_reads_ask.py` builds, built here rather
    than imported for `test_credential_parity.py`'s reason: a function call in
    this module is a dependency a reader can follow, where a helper resolved out
    of another app's test namespace is not.
    """
    Role.objects.create(tenant=tenant, key="approver", name="Approver")
    RolePermission.objects.create(
        tenant=tenant,
        role_key="approver",
        permission="widget.approve",
        effect=RolePermission.Effect.INCLUDE,
    )
    return "approver"


async def _push(*, network: Network, name: str, organization: Organization | None) -> None:
    """One emit, one dispatch hop, one `group_send` — the chain, not a stand-in."""
    acting = await run_db(
        actor_for, user=network.manager, tenant=network.tenant, org=network.branch_a
    )
    await run_db(
        _emit_and_push,
        tenant=network.tenant,
        actor=acting,
        payload=in_branch(organization),
        name=name,
    )


async def _heard(socket: Socket) -> str:
    return str((await socket.receive_json())["name"])


# --- PR3.1 · the read set, computed at the hat and checked per frame ----------------


@pytest.mark.usefixtures("recorded_workflow_starts")
async def test_a_socket_hears_only_the_kinds_it_may_read(readers: Readers) -> None:
    """**The finding, as a test.** Two members of one branch, one withheld key.

    Both sockets wear the same hat, joined the same three-plus groups and are
    reached by the same single `group_send`. The only difference between them is
    a `withhold` row on `widget.read`, which is exactly what the REST door reads
    when it refuses one of them `list_widgets` and answers the other.

    Two frames, because one proves nothing on its own:

    * `example.widget.created` at `leaf_a1` — the allowed reader hears it, the
      withheld one does not. That is the leak closed.
    * `comms.message.sent` at the same node — **both** hear it. That is what
      stops the fix being "the withheld socket hears nothing at all", which
      would pass the first assertion and break the door.
    """
    network = readers.network

    async with (
        hat(user=readers.allowed, org=network.branch_a) as (allowed, allowed_handshake),
        hat(user=readers.withheld, org=network.branch_a) as (withheld, withheld_handshake),
    ):
        assert [allowed_handshake.accepted, withheld_handshake.accepted] == [True, True]

        await _push(network=network, name=EVENT_NAME, organization=network.leaf_a1)
        assert await _heard(allowed) == EVENT_NAME
        assert await withheld.received_nothing() is True

        await _push(network=network, name=MESSAGE_EVENT, organization=network.leaf_a1)
        assert await _heard(allowed) == MESSAGE_EVENT
        assert await _heard(withheld) == MESSAGE_EVENT


async def test_a_flat_product_still_joins_three_groups(
    other_tenant: Tenant, stranger: User
) -> None:
    """The `architecture.md` sentence, asserted at the seam the read set touched.

    "A flat product pays nothing": a depth-one tree's root hat joins the
    tenant's group, that one branch's, and its own — three, a constant. The read
    set is computed **beside** the subtree rather than folded into the group
    names, and this is the assertion that says so: had the rung narrowed by org
    × kind the way the blueprint first sketched, a flat tenant would be joining
    one group per readable kind and this number would be thirty-odd.

    Asserted as the exact set and not as a count, for `test_hierarchy.py`'s
    reason: a count still passes when the consumer joins the right NUMBER of
    wrong groups, and the group names are the security property.
    """
    from channels.layers import get_channel_layer

    from apps.core.services import root_organization

    root = await run_db(root_organization, tenant=other_tenant)

    async with hat(user=stranger, org=root) as (_, handshake):
        assert handshake.accepted is True
        layer = get_channel_layer()
        joined = {name for name, channels in layer.groups.items() if channels}

    assert joined == {
        tenant_group(other_tenant.pk),
        org_group(other_tenant.pk, root.pk),
        user_group(stranger.pk),
    }
    assert len(joined) == 3


@pytest.mark.usefixtures("recorded_workflow_starts")
async def test_an_org_less_event_with_no_kind_is_heard_by_everyone_in_the_tenant(
    readers: Readers,
) -> None:
    """`search.engine.degraded`: no branch owns it and no row is behind it.

    The engine being down is a fact about the deployment, not about anything a
    membership could hold a read on — `apps/search/events.py` maps its noun to
    `None` and says why. So the frame goes to the bare tenant group and every
    connection in the tenant is told, including the one whose `widget.read` was
    taken away.

    This is the case that would be silently lost by a fail-closed default: a
    read set that had to CONTAIN a kind for every frame would drop every
    org-less announcement in the product, and the first anybody would know is an
    operator asking why the outage banner never appeared.
    """
    network = readers.network

    async with (
        hat(user=readers.allowed, org=network.branch_a) as (allowed, allowed_handshake),
        hat(user=readers.withheld, org=network.branch_a) as (withheld, withheld_handshake),
        hat(user=network.rival, org=network.branch_b) as (beside, beside_handshake),
    ):
        assert [
            allowed_handshake.accepted,
            withheld_handshake.accepted,
            beside_handshake.accepted,
        ] == [True, True, True]

        await _push(network=network, name=ENGINE_EVENT, organization=None)

        for socket in (allowed, withheld, beside):
            assert await _heard(socket) == ENGINE_EVENT


async def test_a_withheld_read_costs_no_query_per_frame(
    readers: Readers,
    django_assert_num_queries: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The decision is a frozenset lookup, and this is what keeps it one.

    A connection lives for hours and a tenant can have a thousand of them on one
    event. A `visible_to`-per-push design was rejected in ADR realtime-2 for
    exactly this reason (a DB read per event per connection — the N+1 the push
    design exists to avoid), and a read set resolved per FRAME instead of per
    CONNECTION would reintroduce it one layer up.

    **Two instruments, because neither one can see the whole road on its own.**
    `django_assert_num_queries` cannot be opened from an async test at all — its
    `CaptureQueriesContext` touches the connection synchronously and Django
    refuses that inside a running loop (`SynchronousOnlyOperation`, the red this
    test was first written into). So the query pin goes around the DECISION,
    called the way the consumer calls it, where a per-frame resolution really
    would issue a query and this fixture really would see it. The wire half then
    runs the same frame down a real connection with a counter on
    `apps.realtime.consumers.run_db` — the only road a consumer HAS to the
    database, since it cannot query from its own coroutine — so a per-frame read
    moved off the loop is caught there rather than hidden by the fixture's
    blindness to worker threads.

    **Neither number is zero by construction.** The pin is around a call that
    resolves a kind and asks a frozenset; the counter is around a delivery that
    the connect already paid two `run_db` calls for, so "0 more" is a claim about
    this frame and not about the connection.
    """
    from apps.core.authz import read_kinds
    from apps.realtime.bridge import push_event
    from apps.realtime.consumers import TenantEventsConsumer
    from apps.realtime.schemas import EventMessage

    network = readers.network
    frame = EventMessage(
        name=EVENT_NAME,
        v=1,
        payload={"id": "8f14e45f-ea1e-7c2b-8000-000000000004", "name": "A widget"},
        correlation_id="c0ffee",
        organization_id=network.leaf_a1.pk,
        occurred_at=timezone.now(),
    )
    held = await run_db(read_kinds, readers.withheld, network.tenant, network.branch_a)
    decider = TenantEventsConsumer()
    decider.reads = held

    def decide() -> tuple[bool, bool]:
        with django_assert_num_queries(0):
            return decider.may_hear(EVENT_NAME), decider.may_hear(MESSAGE_EVENT)

    # Non-vacuous: the same connection's set says no to one kind and yes to
    # another, and neither answer cost a statement.
    assert await run_db(decide) == (False, True)

    async with hat(user=readers.withheld, org=network.branch_a) as (withheld, handshake):
        assert handshake.accepted is True

        through_the_db: list[str] = []

        async def counted(func: Any, *args: Any, **kwargs: Any) -> Any:
            through_the_db.append(getattr(func, "__name__", repr(func)))
            return await run_db(func, *args, **kwargs)

        # The consumer's ONE road to the database, named where it imported it.
        monkeypatch.setattr("apps.realtime.consumers.run_db", counted)

        await push_event(tenant_id=network.tenant.pk, event=frame)
        assert await withheld.received_nothing() is True
        assert through_the_db == []


# --- PR3.2 · every noun resolves, and the census is the closed question -------------


def test_every_event_noun_maps_to_a_kind_or_a_declared_none() -> None:
    """A closed question over `introspect.events`: no noun is left undecided.

    **The population is derived, never listed.** Every name every installed app
    declares is what `manage.py introspect` reports and what `emit` validates
    against, so this walks that registry rather than a list in this file — the
    §I clause "a hand list is legal only where the rung names what re-derives
    it", answered by not having one.

    Each noun is one of three things and the third is a defect: it IS an
    authorization kind (`widget`, `message`, `connection`); its app maps it to
    one (`suppression` → `suppression_surge`, because the surge announcement is
    about the `SuppressionSurge` row); or its app maps it to `None` with the
    reason beside it (`engine`). Anything else and the socket has no way to
    decide who may hear it — which is why `kind_of_event` raises rather than
    guessing, and why the planted case below is red rather than silent.

    **The population is `introspect.events` itself**, read from the command that
    builds it rather than from `apps.events` — which this app may not import
    (the two are siblings in the layer contract, and the import-linter contract
    is what says so; the hook caught exactly that import while this test was
    being written). `_events_payload` lives in `core`, which realtime does
    depend on, and it is the same function whose output `manage.py introspect`
    prints — so the census walks the published list and not a second derivation
    of it.

    **The failure NAMES THE GATE, because the gate carries the fix.** Since the
    rule-59 amendment (SIGNED by the owner 2026-09-21) an undecided noun
    no longer raises out of `emit()` — the write commits and the socket drops
    the frame — so this census is the runtime half of a refusal whose STATIC
    half prints the `EVENT_KINDS` line to paste. A reader who gets here is one
    `--explain 59` away from that line, and the refusal below says so rather
    than leaving them to find out that the two are the same subject.

    **Absent:** before ADR core-27 reached this door there was no mapping at all
    and `kind_of_event` did not exist; the six nouns that are not kinds had no
    answer.
    """
    from apps.core.management.commands.introspect import _events_payload

    names = sorted({str(entry["name"]) for entry in _events_payload()})
    assert len(names) >= 30, names

    resolved: dict[str, str | None] = {}
    undecided: dict[str, str] = {}
    for name in names:
        try:
            resolved[name] = kind_of_event(name)
        except ImproperlyConfigured as refusal:
            undecided[name] = str(refusal)
    assert not undecided, (
        "these declared event names have no authorization kind and no EVENT_KINDS "
        f"entry: {sorted(undecided)}. Since the rule-59 amendment `emit()` commits "
        "the write and logs `events.emit.kind_undecided`, and the socket drops every "
        "frame of them (`consumers._may_read`) — so nobody is told these happened. "
        "The gate refuses the tree once per noun and PRINTS THE LINE TO PASTE: run "
        "`uv run python -m quality.gate --explain 59`, or read rule 59's "
        "`undecided_noun` findings in the gate output.\n"
        + "\n".join(f"  {name}: {detail}" for name, detail in sorted(undecided.items()))
    )
    assert set(resolved) == set(names)

    # Non-vacuity, both ways: at least one noun answers with a kind and at least
    # one answers `None`. A census where everything resolved to `None` would be
    # a census that had stopped deciding anything.
    assert any(kind is not None for kind in resolved.values())
    assert any(kind is None for kind in resolved.values())


def test_an_unmapped_noun_is_refused_by_name() -> None:
    """The planted case: a noun nobody mapped names itself in the refusal.

    A census that cannot say WHICH noun is undecided sends the next builder
    reading nine `events.py` files. `zzz.gizmo.polished` is an app that does not
    exist, so the refusal has to come from the noun and not from the app
    registry — and `gizmo` is the word that must be in it.
    """
    with pytest.raises(ImproperlyConfigured) as refused:
        kind_of_event("zzz.gizmo.polished")

    assert "gizmo" in str(refused.value)
    assert "EVENT_KINDS" in str(refused.value)


def test_a_declared_none_is_not_the_same_answer_as_an_unmapped_noun() -> None:
    """`None` is a DECIDED answer, and the instrument says so in the negative case.

    Two nouns from one app would otherwise be indistinguishable to a reader of
    this test: `engine` resolves to `None` and is heard by everyone, while a
    noun nobody declared raises. A check that returned `None` for both would be
    a check that cannot fail — the shape §I exists to refuse.
    """
    assert kind_of_event(ENGINE_EVENT) is None
    assert kind_of_event(EVENT_NAME) == "widget"
    assert kind_of_event(MESSAGE_EVENT) == "message"
    assert kind_of_event("connections.webhook.received") == "inbound_webhook"
    with pytest.raises(ImproperlyConfigured):
        kind_of_event("search.gizmo.polished")


def test_a_frame_whose_noun_is_undecided_is_dropped(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The socket's half of the undecided noun: one frame lost, never a connection.

    `apps/events/tests/test_emit_undecided.py` cites this test by name as the
    proof of the other half of C1's amendment — `emit()` no longer raises on a
    noun nobody decided about, and what makes that safe is that the SOCKET goes
    on refusing to deliver it. The citation was written and the test was not,
    which is a claim wearing a status; this is the artifact it named.

    **Why a drop and not a raise.** `kind_of_event` refuses an undecided noun,
    and a raise inside a channel-layer handler takes the CONNECTION down — one
    undecided noun, emitted once, would disconnect every socket in the tenant.
    `_may_read` catches it, answers False, and says `realtime.frame.kind_undecided`
    at ERROR: the failure stays on the frame and an operator finds the line.

    **Non-vacuous by construction.** The same consumer, the same read set and
    the same noun are driven twice — once with `apps/usage`'s real
    `EVENT_KINDS`, where `threshold` resolves to `usage_entry` and the frame IS
    heard, and once with nobody deciding it, where it is not. A test that only
    ever saw the second half could not tell "dropped because undecided" from
    "dropped because this hat holds nothing".
    """
    from apps.realtime.consumers import TenantEventsConsumer

    decider = TenantEventsConsumer()
    decider.reads = frozenset({"usage_entry"})

    # The control: the declaration is there, the noun resolves, the frame lands.
    assert kind_of_event(THRESHOLD_CROSSED) == "usage_entry"
    assert decider._may_read(THRESHOLD_CROSSED) is True
    assert decider.may_hear(THRESHOLD_CROSSED) is True

    # And with nobody deciding the noun — the shape `emit()` now COMMITS under.
    # Patched at `core.authz`, where `kind_of_event` looks the function up, for
    # the reason `test_emit_undecided.py`'s own fixture gives: deleting the real
    # declaration would also change the tree the gate measures.
    monkeypatch.setattr(authz, "event_kinds_of", lambda app_label: {})
    caplog.clear()
    with caplog.at_level(logging.ERROR):
        assert decider._may_read(THRESHOLD_CROSSED) is False
        assert decider.may_hear(THRESHOLD_CROSSED) is False

    lines = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.getMessage().startswith("{")
    ]
    dropped = [line for line in lines if line.get("event") == "realtime.frame.kind_undecided"]
    # Two calls above, two lines: the refusal is per FRAME and says so every
    # time, rather than once per connection where nobody would ever see it.
    assert len(dropped) == 2, lines
    assert dropped[0]["event_name"] == THRESHOLD_CROSSED
    # The detail is `kind_of_event`'s own refusal, so the log line names the
    # noun and the file that must decide about it and is actionable alone.
    assert "threshold" in dropped[0]["detail"]
    assert "EVENT_KINDS" in dropped[0]["detail"]


# --- PR3.3 · the kick, and what the reconnect computes ------------------------------


@pytest.mark.usefixtures("recorded_workflow_starts")
async def test_a_kick_then_reconnect_hears_less(readers: Readers) -> None:
    """The New Enemy window, closed at both ends: hang up, then recompute.

    BVB-3's problem is not that the old connection is wrong — it is that nothing
    ever told it so. The kick is the first half and it is asserted in
    `test_authorization_kick.py`; this is the **second**, and without it a kick
    that closed the socket and let it come back holding exactly the same set
    would look identical on the wire.

    The narrowing is strict and it is measured as such. Before: this member
    hears `example.widget.created` and `comms.message.sent`. After the demotion
    to `approver` — one include row, `widget.approve`, no reads at all — the
    reconnected socket hears neither, and still hears `search.engine.degraded`,
    which is what makes the two silences a decision rather than a dead socket.
    """
    network = readers.network
    system = await run_db(system_actor, tenant=network.tenant, org=network.hq)

    async with hat(user=readers.allowed, org=network.branch_a) as (before, handshake):
        assert handshake.accepted is True
        await _push(network=network, name=EVENT_NAME, organization=network.leaf_a1)
        assert await _heard(before) == EVENT_NAME
        await _push(network=network, name=MESSAGE_EVENT, organization=network.leaf_a1)
        assert await _heard(before) == MESSAGE_EVENT

        def demote() -> None:
            role = _approver(network.tenant)
            membership = Membership.objects.get(user=readers.allowed, tenant=network.tenant)
            set_role(tenant=network.tenant, membership=membership, role=role, actor=system)

        await run_db(demote)

    async with hat(user=readers.allowed, org=network.branch_a) as (after, reconnected):
        assert reconnected.accepted is True

        await _push(network=network, name=EVENT_NAME, organization=network.leaf_a1)
        assert await after.received_nothing() is True
        await _push(network=network, name=MESSAGE_EVENT, organization=network.leaf_a1)
        assert await after.received_nothing() is True

        # Alive, and still told what nobody holds a read on: the two silences
        # above are the read set answering, not a connection that died quietly.
        await _push(network=network, name=ENGINE_EVENT, organization=None)
        assert await _heard(after) == ENGINE_EVENT


# --- R4-F2 · the crossing that rode the bare tenant group ---------------------

#: `apps/usage`'s own name, as a literal. `apps/realtime` is a PLATFORM app and
#: `apps/usage` is a domain one, so importing the constant would be the upward
#: import the layer contract exists to refuse — the same reason `EVENT_NAME`
#: above is a literal rather than `apps.example.events.WIDGET_CREATED`.
CROSSING_EVENT = "usage.threshold.crossed"


def _a_crossing_with_the_branch_only_inside(organization: Organization) -> dict[str, Any]:
    """The body `usage.threshold.crossed` carried BEFORE R4-F2 — the leak itself.

    `ThresholdCrossingOut`'s top level had no `organization_id`; the branch was
    one level down, on the org-scoped `UsageEntryOut` it names as `crossed_by`.
    `_subject_organization` reads the TOP level only, so this resolved to NULL
    and `group_for` read NULL as tenant-wide.
    """
    return {
        "meter": "files.bytes.stored",
        "period": "month",
        "threshold": "50",
        "crossed_by": {
            "id": "8f14e45f-ea1e-7c2b-8000-000000000007",
            "organization_id": str(organization.pk),
        },
    }


@pytest.mark.usefixtures("recorded_workflow_starts")
async def test_a_sibling_branch_never_hears_a_threshold_crossing(network: Network) -> None:
    """**R4's F4/D5, re-made: a rival at branch B heard branch A's ledger row.**

    Two halves, because closing one without the other leaves the hole:

    * **the shape that leaked can no longer be emitted at all.** A body whose
      only branch is nested under `crossed_by` resolves to NULL at
      `_subject_organization`, and NULL is tenant-wide at `group_for` — so
      `emit` refuses it (house rule 59's runtime belt) rather than broadcasting
      the subject's own row. Nothing is written and nothing is pushed.
    * **the shape that replaced it reaches the owning branch and nobody beside
      it.** `ThresholdCrossingOut` now carries the entry's `organization_id` at
      the top level, so the crossing is an ordinary org-bearing event and the
      hierarchy answers it the way it answers every other one.

    The rival's socket is the control, and it is a *branch* control rather than
    a tenant one: both connections are in the same tenant, joined to the same
    tenant group, and the only thing between them is the branch on the frame.
    """
    from apps.core.exceptions import Invalid

    acting = await run_db(
        actor_for, user=network.manager, tenant=network.tenant, org=network.branch_a
    )

    async with (
        hat(user=network.manager, org=network.branch_a) as (mine, first),
        hat(user=network.rival, org=network.branch_b) as (theirs, second),
    ):
        assert [first.accepted, second.accepted] == [True, True]

        def emit_the_old_shape() -> None:
            emit = bridge.get(bridge.EMIT)
            emit(
                name=CROSSING_EVENT,
                tenant=network.tenant,
                payload=_a_crossing_with_the_branch_only_inside(network.leaf_a1),
                actor=acting,
            )

        with pytest.raises(Invalid):
            await run_db(emit_the_old_shape)

        assert await mine.received_nothing() is True
        assert await theirs.received_nothing() is True

        await _push(network=network, name=CROSSING_EVENT, organization=network.leaf_a1)
        assert await _heard(mine) == CROSSING_EVENT
        assert await theirs.received_nothing() is True


#: The meter the case below spends. A meter's first segment is the label of the
#: app that DECLARES it, so this one belongs to the worked example — the same
#: name `apps/usage/tests/conftest.py` uses, spelled here rather than imported
#: for `CROSSING_EVENT`'s reason.
CROSSING_METER = "example.widgets.count"

#: The key `apps/usage/types.py` reads its lines out of `Tenant.settings` under.
CROSSING_SETTING = "usage_thresholds"


def _cross_the_line(*, network: Network, org: Organization, quantity: str) -> Any:
    """Spend past a configured line for real, then run the dispatch's push hop.

    **The whole chain and not a stand-in**: `record_usage` writes the ledger row
    at the acting hat, decides the straddle itself, builds `ThresholdCrossingOut`
    itself and emits through the real `emit`; only the Temporal *transport* is
    replaced, exactly as `_emit_and_push` replaces it, by setting the principal
    contextvar directly and calling the activity. Every hop that could drift —
    the schema's own stamp, the outbox row, `_subject_organization`, `group_for`,
    the envelope and the group send — is the shipped one.

    Reached through `importlib`, the way this module's neighbours reach the
    spine: `apps/realtime` is a platform app and a static import of a domain
    app's service would be a dependency taken where the test only needs a
    caller.
    """
    usage = importlib.import_module("apps.usage.services")
    usage_events = importlib.import_module("apps.usage.events")
    events_models = importlib.import_module("apps.events.models")
    context = importlib.import_module("apps.workflows.context")
    activities = importlib.import_module("apps.events.activities")
    types = importlib.import_module("apps.events.types")

    acting = actor_for(user=network.manager, tenant=network.tenant, org=org)
    usage.record_usage(
        tenant=network.tenant,
        actor=acting,
        meter=CROSSING_METER,
        quantity=Decimal(quantity),
        # The row that caused it. Any row will do — `record_usage` stores its
        # label and pk the way an audit row stores an object — and the branch
        # this test is about comes from the ACTING HAT, never from the ref.
        ref=org,
        idempotency_key=f"crossing-{quantity}",
    )
    event = (
        events_models.Event.objects.for_tenant(network.tenant)
        .filter(name=usage_events.THRESHOLD_CROSSED)
        .latest("created_at")
    )
    context.set_principal(tenant_id=str(network.tenant.pk), user_id=None)
    assert activities.push_realtime(types.PushRealtime(event_id=str(event.pk))) is True
    return event


@pytest.mark.usefixtures("recorded_workflow_starts")
async def test_a_usage_threshold_frame_reaches_the_branch_it_names_and_no_other(
    network: Network, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same crossing as the case above, driven from `record_usage` outward.

    The case above pushes a body this module BUILT. That proves the door, and it
    cannot prove the producer: the stamp that puts `organization_id` at the top
    level of `ThresholdCrossingOut` lives in `apps/usage`, and a test that hands
    the door a correct body never asks whether the service still writes one. So
    this drives the real seam end to end — a tenant configures a line, somebody
    at branch A spends past it, and the frame that comes out the socket is the
    one `record_usage` produced.

    **Three assertions, and each is a different failure.** The A socket receives
    the crossing AND the branch on the frame is A's — an event delivered to the
    right group with the wrong branch on it is what a hat-stamped payload would
    look like, and the group would not notice. The B socket receives nothing —
    the branch control, a sibling in the same tenant joined to the same tenant
    group, which is the only thing a top-level key that went missing could
    still be told apart by. And an org-less announcement reaches both — the
    non-vacuity half: two silent sockets and a dead connection read the same.

    *States driven:* a branch hat spending past a line · a sibling branch
    hearing nothing · both sockets hearing the deployment-wide fact. *Not
    driven:* the root hat (its subtree holds every branch, so nothing could be
    absent from it), and a second crossing in the same period, which
    `apps/usage/tests/test_services.py` owns.
    """
    meters = importlib.import_module("apps.usage.meters")
    monkeypatch.setattr(meters, "declared_meters", lambda: {"example": frozenset({CROSSING_METER})})

    def configure() -> None:
        from apps.core.services import update_tenant_settings

        update_tenant_settings(
            tenant=network.tenant,
            values={
                CROSSING_SETTING: [{"meter": CROSSING_METER, "period": "month", "quantity": "150"}]
            },
            actor=system_actor(tenant=network.tenant),
        )
        network.tenant.refresh_from_db()

    await run_db(configure)

    async with (
        hat(user=network.manager, org=network.branch_a) as (mine, first),
        hat(user=network.rival, org=network.branch_b) as (theirs, second),
    ):
        assert [first.accepted, second.accepted] == [True, True]

        await run_db(_cross_the_line, network=network, org=network.branch_a, quantity="200")

        frame = await mine.receive_json()
        assert frame["name"] == CROSSING_EVENT
        assert frame["organization_id"] == str(network.branch_a.pk)
        assert frame["payload"]["organization_id"] == str(network.branch_a.pk)
        assert frame["payload"]["crossed_by"]["organization_id"] == str(network.branch_a.pk)
        assert await theirs.received_nothing() is True

        await _push(network=network, name=ENGINE_EVENT, organization=None)
        assert await _heard(mine) == ENGINE_EVENT
        assert await _heard(theirs) == ENGINE_EVENT
