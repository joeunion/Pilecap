"""The socket door at scale: what a connect costs, and who hears a push.

Rung M4 (cycle P3). Owns this module and the retired `perf-realtime-measurement.md`;
writes nothing in `apps/`. Every instrument is `perf/measure.py`'s — query
counts, EXPLAIN plan shapes, doubling comparators — plus one more of the same
family that this door needs and no other does: **channel-layer counts** (group
sends per emit, group memberships per connection, frames delivered per push).
All of them are machine-invariant. Wall-clock appears nowhere, not even as a
comparison; `perf/conftest.py` refuses a module that forgets.

## The one number this module exists to deliver

ADR realtime-2 adopted **subtree-group join** and *recorded* ancestor-chain
publish as the rejected alternative, with an explicit trigger:

    "RECORDED, with M4's measured join count at the 1,200-org hat as the
     trigger to revisit."

The join count at the widest hats of the seeded tree is
`test_the_trigger_number`, and it is the first line of the measurement doc. The
rung's job is to measure it and hand it to the PM beside the quoted trigger —
**delivered, not fixed** (the cycle's own declared blind spot).

## What is measured, and how each thing is instrumented

* **connect-time subtree resolution** — `list_subtree_org_ids` at six hat
  shapes (root, region, leaf, the 200-wide node, the top of the spine and its
  depth-11 tip): the *query count* (the N+1 instrument, flat under doubling),
  the *plan shape* (EXPLAIN, the index instrument) and the *join count* the
  resolution returns, which is the ADR's trigger number.
* **group memberships per connection** — driven through the **real consumer**
  and read off the **real channel layer** as a before/after delta, so the
  number is what `TenantEventsConsumer.connect` actually joined, never this
  module's arithmetic about what it should have.
* **publish fan-out under the chosen topology** — group *sends* per emit
  (`call_counter` on the layer's `group_send`) and frames *delivered* per emit
  at 500 connections, against the OLD tenant-group topology measured on the
  same population through the still-existing `tenant_group` primitive.
* **the delivery census** — a region emit reaches exactly the hats whose
  subtree contains that branch: RT2's correctness property, re-proven at 500
  sockets instead of four.
* **the kick** — one user, 50 sockets, one send, fifty closes.
* **connection doubling 500 -> 1,000** — the `sockets` axis is declared, not
  seeded (`ScaleSpec.sockets`; connections are runtime), so this module doubles
  it in-process rather than through a re-seed.

## Two methodology notes, stated rather than buried

**Scope injection.** The consumer is driven by the raw-ASGI `Socket` client with
`user` / `tenant` / `org` placed in the scope directly, which is what
`AuthMiddlewareStack` + `TenantMiddlewareASGI` + `resolve_org` would have placed
there. The auth stack is deliberately *not* in the loop: its cost is
`resolve_org`, which is M1's measure at this same seeded scale, and measuring it
here as well would double-count it into the socket's number. What *is* in the
loop is every line of `TenantEventsConsumer.connect` — the real selector, the
real group derivation, the real `group_add`.

**Three of the six hat shapes have no seeded membership.** `perf/seed.py` seeds
named hats at the root, `region-00` and `r00-p00` only, and it is FROZEN for the
M-rungs. The wide node and the two spine positions are therefore measured as
*hat positions* — real seeded organizations, resolved by the real selector —
rather than as people who could sign in today. The cost of a hat at a 200-wide
node is a real cost a product pays the day it puts a recruiter there; what this
module does not claim is that such a membership exists in the seeded world.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from channels.layers import get_channel_layer
from django.db import connection

from apps.accounts.models import User
from apps.core.asgi_middleware import ORG_SCOPE_KEY
from apps.core.asgi_middleware import SCOPE_KEY as TENANT_SCOPE_KEY
from apps.core.models import PATH_SEPARATOR, Organization
from apps.core.time import now
from apps.realtime import consumers as consumers_module
from apps.realtime.bridge import KICK_TYPE, MESSAGE_TYPE, push_event, tenant_group, user_group
from apps.realtime.consumers import TenantEventsConsumer
from apps.realtime.schemas import CLOSE_KICKED, EventMessage
from apps.realtime.selectors import list_subtree_org_ids
from apps.realtime.tests.websocket import Socket
from perf.measure import (
    call_counter,
    count_queries,
    explain,
    explain_as_executed,
    flat_under_doubling,
    postgres_server_version,
)
from perf.seed import (
    DEFAULT_SPEC,
    HEAVY_ORG_SLUG,
    REGION_HAT_SLUG,
    ScaleSpec,
    hat_emails,
    partner_slugs,
)

pytestmark = [pytest.mark.django_db]

# The event name `apps/example/events.py` declares. A literal, as the RT2 tests
# use one, and for the same reason: `apps.realtime` may not import the app that
# declared it, and neither may a module measuring `apps.realtime`.
EVENT_NAME = "example.widget.created"

# How long the loop is given to settle after a `group_send` before the census
# reads each socket. It is a *quiesce*, never an instrument: nothing here
# compares it, budgets it or asserts on it, since wall-clock is never a
# criterion. The census's numbers
# are frame COUNTS, and a settle too short shows up as a census that does not
# match its arithmetic — a loud failure, never a flaky pass.
SETTLE = 0.5

# The measured counts at S, declared so a doubled-axis run has something to
# compare against inside one process (`flat_under_doubling` takes two ints, and
# one `perf.sh` invocation sees one world). Both are structural rather than
# lucky: `list_subtree_org_ids` is one prefix scan by construction, and the
# consumer calls it once per connection and never again.
SUBTREE_QUERIES_AT_S = 1
SELECTOR_CALLS_PER_CONNECT_AT_S = 1

# The socket population the fixture contract declares (`ScaleSpec.sockets` = 500)
# and the mix of hats it declares them at. The shares mirror
# `seed.membership_position`'s own distribution — ~0.3% root, ~20% region, the
# bulk on partners — so the measured world is the seeded world's people online
# rather than a flattering sample.
ROOT_SOCKET_SHARE = 0.004
REGION_SOCKET_SHARE = 0.20

# The three indexes on `core_organization` a subtree read can narrow by.
#
# `TENANT_PREFIX_INDEX` is F1e's, and it is the one this read should take: a
# composite `(tenant_id, path varchar_pattern_ops)`, so BOTH legs of the
# selector's `OR` become tenant-qualified index conditions on one index and the
# scan never touches another tenant's entries. `PREFIX_INDEX` is the older
# tenant-less one, still declared because `visible_to()` reaches this table
# through a JOIN carrying no tenant predicate on the organization side;
# `EXACT_PATH_INDEX` is the per-tenant uniqueness constraint, which answered the
# equality leg before F1e.
#
# Both of the older two are kept named here rather than deleted, because the
# planner may legitimately choose either and the measurement's job is to say
# WHICH — a plan that narrows by any of the three is a narrowed plan.
TENANT_PREFIX_INDEX = "organization_tenant_prefix"
PREFIX_INDEX = "organization_path_prefix"
EXACT_PATH_INDEX = "organization_unique_path_per_tenant"
PATH_INDEXES = (TENANT_PREFIX_INDEX, PREFIX_INDEX, EXACT_PATH_INDEX)


def narrows_by_a_path_index(plan: str) -> bool:
    """Whether the plan reaches the subtree through an index on `path`.

    The question every plan measure here actually asks. Naming one index would
    make the measurement a fact about which of three interchangeable narrowings
    the planner picked in one world — exactly the brittleness M4's FINDING 1
    told E1 to keep out of rule 35.

    **It is the `Index Cond` that is read, not the index name**, and that is the
    whole point rather than a detail. Two of these three indexes lead with
    `tenant_id`, so the planner can name one while using it purely as a
    tenant-range scan and evaluating the path predicate as a `Filter` over the
    tenant's every organization row — which is FINDING 1's failing shape wearing
    the passing shape's name. (`perf/measure_hierarchy.py`'s measure 14 is a
    live instance of exactly that substitution on this table, on an axis M1 did
    not declare.) A narrowing is a plan where the *path predicate itself* is an
    index condition; anything else walks the tenant.
    """
    if not any(index in plan for index in PATH_INDEXES):
        return False
    return any(
        line.strip().startswith("Index Cond:") and "path" in line for line in plan.splitlines()
    )


# Below this share of the tenant's organizations, a path-index narrowing is
# ASSERTED: a planner that stopped narrowing a hat this small would be a real
# regression and the rung should fail. At or above it the plan is RECORDED
# instead, because reading the tenant's rows and filtering may well be the
# cheaper plan there and asserting an index scan would be asserting that the
# planner is wrong.
#
# **F1e moved the flip and this number deliberately did not follow it.** Before
# F1e the narrowing was lost at 16% of a tenant (the wide hat at S); with the
# tenant-local composite in place the same hat narrows, and the flip now sits
# somewhere between 16% and 27.6% (the retired `perf-realtime-measurement.md` §5).
# Raising the ceiling to the new measured flip would make the assertion a fact
# about one seeded world again — the mistake M4 declined to make in the other
# direction. It stays below every measured flip in every world, so it asserts
# only what has held everywhere; where the flip actually falls is the FINDING's
# business, and the finding prints the share it measured every time it fires.
PREFIX_INDEX_SHARE_CEILING = 0.05


# --- The world, read off its stamp -------------------------------------------


def axis_of(spec: ScaleSpec) -> str:
    """Which single axis (if any) this world has at x2. For the doc's headings."""
    if spec == DEFAULT_SPEC:
        return "S"
    for field in sorted(spec.__dataclass_fields__):
        if getattr(spec, field) != getattr(DEFAULT_SPEC, field):
            return f"x2:{field}"
    return "x2:unknown"


def report(section: str, rows: Iterable[tuple[str, object]]) -> None:
    """Print one labelled block. `perf.sh` is run with `-s`; the doc quotes this."""
    print(f"\n--- {section} " + "-" * max(0, 62 - len(section)))
    for label, value in rows:
        print(f"    {label:<54} {value}")


@dataclass(frozen=True)
class Hat:
    """One hat position: a real seeded organization and what its subtree costs."""

    label: str
    org: Organization
    expected_subtree: int


@dataclass(frozen=True)
class World:
    """Everything read out of the database once, so no async test touches the ORM.

    Django refuses ORM calls from a running event loop (`SynchronousOnlyOperation`)
    and it is right to: the connection is not the loop's to use. Rather than
    scatter `sync_to_async` through the measurements, every row a measurement
    needs is fetched here, in a synchronous fixture, and the async tests work on
    the objects. The one database read that DOES happen inside the loop is the
    one being measured — the consumer's, on its own thread, through `run_db`.
    """

    spec: ScaleSpec
    tenant: Any
    hats: list[Hat]
    users: dict[str, User]
    root: Organization
    regions: list[Organization]
    partners: list[Organization]
    org_count: int

    @property
    def axis(self) -> str:
        return axis_of(self.spec)


@pytest.fixture()
def world(spec: ScaleSpec, loaded_tenants: list[Any]) -> World:
    """The first loaded twin, and every row the measurements need. Read once."""
    tenant = loaded_tenants[0]
    orgs = Organization.objects.for_tenant(tenant)
    root = orgs.get(parent__isnull=True)
    deepest_spine = f"spine-{spec.spine_depth - 1:02d}"
    hats = [
        Hat("root", root, spec.orgs_per_loaded_tenant),
        Hat("region", orgs.get(slug=REGION_HAT_SLUG), 1 + spec.partners_per_region),
        Hat("leaf", orgs.get(slug=HEAVY_ORG_SLUG), 1),
        Hat("wide", orgs.get(slug="wide"), 1 + spec.wide_children),
        Hat("spine-top", orgs.get(slug="spine-01"), spec.spine_depth - 1),
        Hat("spine-tip", orgs.get(slug=deepest_spine), 1),
    ]
    emails = hat_emails(tenant.slug)
    return World(
        spec=spec,
        tenant=tenant,
        hats=hats,
        users={position: User.objects.get(email=email) for position, email in emails.items()},
        root=root,
        regions=list(orgs.filter(slug__startswith="region-").order_by("slug")),
        partners=list(orgs.filter(slug__in=partner_slugs(spec)).order_by("slug")),
        org_count=orgs.count(),
    )


@pytest_asyncio.fixture()
async def layer() -> AsyncIterator[Any]:
    """The configured channel layer, empty before and after.

    `config/settings/test.py` makes this the in-memory layer, which is the
    declared blind spot the cycle already states: this module measures OUR
    counts — sends, memberships, frames — and Redis under real network latency
    is P4's staging territory. Every count here is layer-agnostic by
    construction; not one of them would read differently on Redis.
    """
    channel_layer = get_channel_layer()
    await channel_layer.flush()
    try:
        yield channel_layer
    finally:
        await channel_layer.flush()


# --- The queries, and the sockets --------------------------------------------


def subtree_plan(*, tenant: Any, org: Organization) -> str:
    """The plan for the statement `list_subtree_org_ids` ACTUALLY issued.

    **This replaced a mirror, and an earlier verification pass is why.**
    `list_subtree_org_ids` returns a list and a list has no plan, so this
    module used to rebuild the selector's queryset line for line and EXPLAIN
    the rebuild, with
    `test_the_mirror_is_the_selector` pinning the two together by result
    equality. That pin cannot see the failure it exists to prevent: re-spelling
    the selector's predicate as `Q(path__iexact=…) | Q(path__istartswith=…)`
    returns **exactly the same rows** on a base36 materialized path, so the
    equality held, the mirror kept the old spelling, and every plan measure in
    this module went on describing a query the platform had stopped running —
    F1d's class ("EXPLAIN of a query no door issues") one seam up.

    So the statement is captured rather than rebuilt: run the real selector,
    take the SQL Django emitted, EXPLAIN that (`perf/measure.explain_as_executed`,
    F1d's own instrument, and the same capture `quality/hotpath_probe.py` uses).
    There is nothing left to keep in step, which is why the equality pin is gone
    and `test_the_captured_statement_is_the_selectors` stands in its place: it
    holds the ONE property the capture still needs to be true.
    """
    plans = subtree_statement_plans(tenant=tenant, org=org)
    assert len(plans) == 1, (
        f"the connect read issued {len(plans)} SELECT statements, not one — every plan "
        "measure below assumes it is EXPLAINing THE statement of the connect read, and "
        "with more than one there is no such thing."
    )
    return plans[0]


def subtree_statement_plans(*, tenant: Any, org: Organization) -> list[str]:
    """One plan per SELECT the connect read issued, in execution order."""
    return explain_as_executed(lambda: list_subtree_org_ids(tenant=tenant, org=org))


@pytest.fixture(scope="session", autouse=True)
def analyzed_world(django_db_setup: None, django_db_blocker: Any) -> None:
    """`ANALYZE` before anything is measured. **A workaround, not a fix.**

    `scripts/perf.sh` drops, re-creates, migrates and bulk-seeds the world, and
    nothing in that sequence runs `ANALYZE` — so for the first minutes of a new
    world's life the planner chooses plans with **no statistics at all**, and it
    chooses differently. A run of this suite watched `organization_path_prefix` go unused
    at *every* hat on the freshly-seeded `--double orgs` world, including a leaf
    hat resolving one row out of 2,293; minutes later, autovacuum having caught
    up, the same query at the same hat used it. Neither observation is wrong
    about what Postgres did — the first is simply not about the platform,
    because no production table is unanalyzed.

    M2 and M3 hit the same wall independently (M2 watched a selector flip from
    Memoize + index to Hash Join + Seq Scan; M3 watched the X-Org lookup drop
    `slug` from an `Index Cond` to a `Filter`), and all three rungs work around
    it the same way so that the three measurement docs are comparable.
    **The fix belongs in the seeder** — `perf/seed.py` should analyze what it
    just bulk-loaded — and that is **M2's finding F**, landing in a parallel
    rung. This fixture comes out when it lands.

    Without it, every EXPLAIN in this module would be measuring autovacuum's
    timing rather than the schema. `require_analyzed` below then asserts the
    fixture actually took, so a silent regression here cannot quietly turn the
    plan measurements back into noise.
    """
    with django_db_blocker.unblock(), connection.cursor() as cursor:
        cursor.execute("ANALYZE")


def require_analyzed(table: str) -> str:
    """The `analyzed_world` fixture took, and this is when it took.

    A precondition rather than a courtesy: the plan-shape measures are the two
    that would silently become measurements of autovacuum timing if the fixture
    above ever stopped running, and a plan read on an unanalyzed table is not
    evidence. Query counts, group counts and the delivery census do not depend
    on statistics and are not gated by this.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT last_analyze, last_autoanalyze FROM pg_stat_user_tables WHERE relname = %s",
            [table],
        )
        row = cursor.fetchone()
    if row is None or (row[0] is None and row[1] is None):
        pytest.fail(
            f"{table} has no statistics, so every plan below would be a plan "
            "Postgres made without any — a measurement about this minute of this "
            "database rather than about the platform.\n"
            "The `analyzed_world` session fixture in this module exists to prevent "
            "exactly that and did not take. It is a workaround for M2's finding F "
            "(scripts/perf.sh seeds and measures with no ANALYZE between them; the "
            "fix belongs in perf/seed.py, which the M-rungs may not edit).",
            pytrace=False,
        )
    return str(row[0] or row[1])


def memberships(layer: Any) -> int:
    """Total (group, channel) pairs the layer is holding. The join-cost meter."""
    return sum(len(channels) for channels in layer.groups.values())


def scoped_app(*, user: User, tenant: Any, org: Organization | None) -> Any:
    """`TenantEventsConsumer`, with the scope the middleware stack would have set.

    See the module docstring's methodology note: the auth stack is out of the
    loop deliberately (its cost is `resolve_org`, which is M1's measure), and
    every line of `connect` is in it.
    """
    inner = TenantEventsConsumer.as_asgi()

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> Any:
        scope = dict(scope)
        scope["user"] = user
        scope[TENANT_SCOPE_KEY] = tenant
        scope[ORG_SCOPE_KEY] = org
        return await inner(scope, receive, send)

    return app


@asynccontextmanager
async def connected(sockets: Sequence[Socket]) -> AsyncIterator[Sequence[Socket]]:
    """Open every socket, hand them over, always hang up."""
    try:
        for socket in sockets:
            handshake = await socket.open()
            assert handshake.accepted, handshake
        yield sockets
    finally:
        for socket in sockets:
            await socket.close()


def message(*, organization_id: UUID | None) -> EventMessage:
    """One event on the wire. Org-bearing or tenant-wide; nothing else varies."""
    return EventMessage(
        name=EVENT_NAME,
        v=1,
        payload={"id": "00000000-0000-0000-0000-000000000000"},
        organization_id=organization_id,
        occurred_at=now(),
    )


async def census(sockets: Sequence[Socket]) -> list[int]:
    """Frames each socket received since the last census. Counted, never timed.

    Every socket is drained concurrently, so the settle is paid once for the
    whole population rather than once per connection.
    """
    await asyncio.sleep(SETTLE)

    async def drain(socket: Socket) -> int:
        frames = 0
        while True:
            try:
                message = await socket.output(timeout=0.01)
            except TimeoutError:
                return frames
            if message["type"] == "websocket.send":
                frames += 1

    return list(await asyncio.gather(*(drain(socket) for socket in sockets)))


# --- 1. THE TRIGGER NUMBER ----------------------------------------------------


def test_the_trigger_number(world: World) -> None:
    """The join count at the widest hats. ADR realtime-2's trigger reads this.

    Quoted verbatim from the ADR, because a number without the sentence it
    answers is a number somebody has to go and look up:

        Rejected: ancestor-chain publish (cheaper joins, but the fan-out cost
        rides every emit including the socketless majority, where subtree-join
        cost rides only connected sockets) - RECORDED, with M4's measured join
        count at the 1,200-org hat as the trigger to revisit.

    Two hats answer to "widest" and the doc carries both: the **root** hat, whose
    subtree is the whole tree (the ADR's "1,200-org hat"), and the **200-wide
    node**, the breadth stressor the fixture contract seeds for exactly this. A
    connection joins its subtree plus two constants — the tenant group for
    org-less events and its own user group — so the group count is the join
    count plus two.
    """
    rows: list[tuple[str, object]] = [("world", world.axis)]
    for hat in world.hats:
        resolved = list_subtree_org_ids(tenant=world.tenant, org=hat.org)
        assert len(resolved) == hat.expected_subtree, (
            f"{hat.label}: the seeded tree resolved {len(resolved)} orgs where the "
            f"spec's arithmetic says {hat.expected_subtree} — the world is not the "
            "world this measurement describes."
        )
        rows.append(
            (
                f"{hat.label:<10} subtree orgs -> groups joined",
                f"{len(resolved):>6} -> {len(resolved) + 2:>6}",
            )
        )
    report("THE TRIGGER NUMBER (ADR realtime-2: join count at the widest hat)", rows)


def test_the_captured_statement_is_the_selectors(world: World) -> None:
    """One statement per connect, and the plans below are ITS plan.

    The predecessor of this test pinned a hand-written mirror to the selector by
    result equality, and a verification pass walked straight through it: `iexact`
    returns the same rows, so equality held while the plans diverged. Capturing
    the statement removes the divergence by construction — there is no second
    query to keep in step — and what is left to assert is the assumption the
    capture makes: that the connect read is exactly ONE statement at every hat,
    so "the plan" is a thing there is one of.

    It is the same number `test_subtree_resolution_is_one_query_at_every_hat`
    measures, asserted here for a different reason: there it is the N+1
    instrument, here it is the precondition of every plan measure below.
    """
    for hat in world.hats:
        plans = subtree_statement_plans(tenant=world.tenant, org=hat.org)
        assert len(plans) == 1, (
            f"{hat.label}: the connect read issued {len(plans)} SELECT statements — "
            "every EXPLAIN below names one of them and cannot say which."
        )


# --- 2. CONNECT-TIME SUBTREE RESOLUTION: count, plan, doubling ----------------


def test_subtree_resolution_is_one_query_at_every_hat(world: World) -> None:
    """One prefix scan per connect, whatever the hat's shape, at S and at x2.

    The count is the instrument; `flat_under_doubling` compares it against the
    declared count at S, so the `--double orgs` run is the same module making
    the same claim about a bigger world. A count that grew would mean the
    selector had learned to walk the tree, which is the N+1 the whole push
    design exists to refuse.
    """
    rows: list[tuple[str, object]] = [("world", world.axis)]
    for hat in world.hats:
        with count_queries() as counted:
            resolved = list_subtree_org_ids(tenant=world.tenant, org=hat.org)
        flat_under_doubling(
            base=SUBTREE_QUERIES_AT_S,
            doubled=counted.count,
            axis=world.axis,
            what=f"list_subtree_org_ids at the {hat.label} hat",
        )
        rows.append(
            (f"{hat.label:<10} queries -> orgs resolved", f"{counted.count} -> {len(resolved)}")
        )
    report("CONNECT-TIME SUBTREE RESOLUTION (query count)", rows)


def test_subtree_resolution_plan_shape(world: World) -> None:
    """The plan at every hat, recorded; a path-index narrowing asserted where it wins.

    **The finding a measurement pass returned, and what was done about it.**
    At a narrow hat the planner narrows by an index on `path` and touches only the subtree.
    Above a measured share of the tenant's organizations it stops: the plan
    becomes the tenant FK index plus a `Filter`, which reads **every
    organization row the tenant has** and discards the ones outside the hat —
    so the cost of one hat's connect followed the TENANT's org count rather
    than the hat's. The 200-wide node was on the wrong side of that line at 16%
    of its tenant and on the right side at 8.8%, which is what identified the
    lever as selectivity.

    F1e landed `organization_tenant_prefix` — the same prefix scan made
    tenant-local — and the wide hat at S crossed back over. The flip is not
    abolished and this measure does not pretend it is: at 100% of a tenant the
    planner still reads the tenant index and is right to, and the doc's §5
    carries where the flip now falls.

    **The assertion names no single index, deliberately.** Three indexes can
    narrow this read and the planner may legitimately pick any of them; M4's own
    advice to E1 was that rule 35 must pin plan SHAPE, never an index name.
    `narrows_by_a_path_index` is that shape, and the recorded verdict prints
    which one the planner actually chose so a change of mind is visible without
    being a failure.

    No `Seq Scan` appears at any hat, and that is asserted everywhere: the
    tenant index always holds, so a lost narrowing is never a lost index.
    """
    version = postgres_server_version()
    analyzed = require_analyzed("core_organization")
    rows: list[tuple[str, object]] = [
        ("world", world.axis),
        ("postgres", version),
        ("core_organization last analyzed", analyzed),
    ]
    plans: dict[str, str] = {}
    findings: list[str] = []
    for hat in world.hats:
        share = hat.expected_subtree / world.org_count
        plans[hat.label] = subtree_plan(tenant=world.tenant, org=hat.org)
        plan = plans[hat.label]
        assert "Seq Scan" not in plan, (
            f"{hat.label}: a Seq Scan on core_organization at connect time.\n{plan}"
        )
        chosen = " + ".join(index for index in PATH_INDEXES if index in plan) or "none"
        if share <= PREFIX_INDEX_SHARE_CEILING:
            # A hat this narrow must reach its subtree through an index on
            # `path`; a planner that read the tenant's whole organization table
            # to return one row in a thousand would be a real regression.
            assert narrows_by_a_path_index(plan), (
                f"{hat.label}: at {share:.1%} of the tenant's organizations the plan "
                f"narrows by no path index at all — none of {PATH_INDEXES} appears, so "
                f"the read walks the tenant to find its subtree.\n{plan}"
            )
            verdict = f"narrowed — {chosen} (asserted)"
        else:
            verdict = f"recorded — {chosen}"
            if not narrows_by_a_path_index(plan):
                findings.append(
                    f"{hat.label} hat ({hat.expected_subtree} of {world.org_count} orgs, "
                    f"{share:.0%}): no path index used; the plan reads the tenant's "
                    f"{world.org_count} organization rows and filters."
                )
        rows.append((f"{hat.label:<10} share {share:>6.1%}  plan", verdict))
    report("CONNECT-TIME SUBTREE RESOLUTION (plan shape)", rows)
    if findings:
        report("FINDING — the path narrowing stops above a share", enumerate(findings, 1))
    for label, plan in plans.items():
        print(f"\n    EXPLAIN [{label} hat, {world.axis}, postgres {version}]")
        for line in plan.splitlines():
            print(f"        {line}")


def test_the_or_is_not_what_costs_the_wide_hat_its_index(world: World) -> None:
    """The contrast that keeps FINDING 1 from being blamed on the wrong line.

    The selector's filter is an `OR` — `path = prefix` OR `path LIKE 'prefix.%'`
    — and the obvious reading of the wide hat's plan is that the `OR` is what
    defeated the index. It is not, and this measures the difference so nobody
    "fixes" it by removing the separator.

    The contrast is a bare `path__startswith=prefix`: one leg, no `OR`, the form
    that *would* be the natural single-index query. At the wide and root hats
    its plan is the same tenant-index-plus-`Filter` shape, so the flip is about
    **selectivity**, not about the shape of the predicate.

    And the bare form is not available anyway: the separator in the real
    selector is load-bearing, and `apps/realtime/selectors.py` says why in its
    own docstring — with fixed-width segments a bare prefix cannot go wrong
    today, and the day somebody widens a segment is the day it starts quietly
    returning the sibling branch's group. This measurement exists so the doc can
    say "not the OR" with an artifact behind it, never as a recommendation.
    """
    rows: list[tuple[str, object]] = [
        ("world", world.axis),
        ("core_organization last analyzed", require_analyzed("core_organization")),
    ]
    for hat in world.hats:
        bare = Organization.objects.for_tenant(world.tenant).filter(path__startswith=hat.org.path)
        bare_narrows = narrows_by_a_path_index(explain(bare))
        or_narrows = narrows_by_a_path_index(subtree_plan(tenant=world.tenant, org=hat.org))
        rows.append(
            (
                f"{hat.label:<10} narrowed by a path index — OR form / bare form",
                f"{or_narrows} / {bare_narrows}",
            )
        )
        assert bare_narrows == or_narrows, (
            f"{hat.label}: the OR form and the bare form disagree about whether the "
            f"plan narrows by one of {PATH_INDEXES} — FINDING 1 would then be about "
            "the predicate shape after all, and the doc says it is about selectivity."
        )
    report("CONTRAST — the OR is not what costs the wide hat its index", rows)


def test_the_connect_read_is_not_sorted(world: World) -> None:
    """M4's OBSERVATION 1, now a pin: no connect sorts its subtree.

    `Organization.Meta.ordering = ["path"]`, and until F1f `list_subtree_org_ids`
    did not clear it, so every plan above carried a `Sort` node — 1,253 rows
    sorted at the root hat, on every connection, to produce a list whose only
    use is a loop of `group_add` calls that could not care less what order they
    arrive in. M4 recorded it (that rung wrote nothing in `apps/`); F1f put
    `.order_by()` on the selector's queryset, which removes the node and changes
    no behaviour — every group assertion in this repository is a set.

    Asserted rather than reported, because the node comes back the moment
    somebody drops the `.order_by()` or adds an ordered `.filter()` above it,
    and nothing else in the suite would notice.
    """
    sorted_at: list[str] = []
    for hat in world.hats:
        plan = subtree_plan(tenant=world.tenant, org=hat.org)
        if any(line.strip().startswith("Sort") for line in plan.splitlines()):
            sorted_at.append(f"{hat.label} ({hat.expected_subtree} rows)")
    report(
        "M4 OBSERVATION 1, CLOSED — the connect read no longer sorts",
        [
            ("world", world.axis),
            ("hats whose plan carries a Sort node", f"{len(sorted_at)} of {len(world.hats)}"),
            ("hats", ", ".join(sorted_at) or "none"),
            ("the line that removed it", "list_subtree_org_ids: .order_by() on the queryset"),
        ],
    )
    assert not sorted_at, (
        "the connect read is sorting again — `Meta.ordering` has come back "
        f"through the selector at: {', '.join(sorted_at)}"
    )


# --- 3. GROUP MEMBERSHIPS PER HAT SHAPE, through the real consumer ------------


@pytest.mark.asyncio
async def test_group_memberships_per_hat_shape(world: World, layer: Any) -> None:
    """What one connection actually joins, read off the layer, per hat shape.

    The delta in the layer's own (group, channel) pairs across one connect — not
    this module's arithmetic about what `connect` ought to have done. The
    expected value is `subtree + 2`: one tenant group for org-less events, one
    org group per organization in the subtree, one user group for the kick.

    This is the cost side of ADR realtime-2's trade, measured: what the adopted
    topology spends at connect so that it can spend nothing at publish.
    """
    rows: list[tuple[str, object]] = [("world", world.axis)]
    for hat in world.hats:
        before = memberships(layer)
        socket = Socket(
            scoped_app(user=world.users["root"], tenant=world.tenant, org=hat.org), "/ws/events/"
        )
        async with connected([socket]):
            joined = memberships(layer) - before
        assert joined == hat.expected_subtree + 2, (
            f"{hat.label}: joined {joined} groups; expected the subtree "
            f"({hat.expected_subtree}) plus the tenant group plus the user group."
        )
        rows.append((f"{hat.label:<10} groups joined at connect", joined))
    report("GROUP MEMBERSHIPS PER CONNECTION (real consumer, real layer)", rows)


@pytest.mark.asyncio
async def test_the_connect_makes_one_read_per_connection(world: World, layer: Any) -> None:
    """One subtree read per connection, none per message. Flat under doubling.

    The consumer's read happens on a worker thread (`run_db`), where a
    `CaptureQueriesContext` on this thread's connection cannot see it. So the
    instrument is the *call* count on the seam instead — `list_subtree_org_ids`
    as `consumers.py` holds it — and the query count is
    `test_subtree_resolution_is_one_query_at_every_hat`'s: one call, one query,
    one connection. Multiplying those two is the whole database cost of the
    socket door, and it is what makes 500 connections affordable at all.

    Measured at the root hat deliberately: if any hat were going to turn a
    connect into a walk, it would be the one whose subtree is the whole tree.
    """
    root = world.hats[0]
    sockets = [
        Socket(
            scoped_app(user=world.users["root"], tenant=world.tenant, org=root.org), "/ws/events/"
        )
        for _ in range(10)
    ]
    with call_counter(consumers_module, "list_subtree_org_ids") as calls:
        async with connected(sockets):
            joined = memberships(layer)
            with call_counter(consumers_module, "list_subtree_org_ids") as after_connect:
                await push_event(
                    tenant_id=world.tenant.pk, event=message(organization_id=root.org.pk)
                )
                await census(sockets)

    flat_under_doubling(
        base=SELECTOR_CALLS_PER_CONNECT_AT_S,
        doubled=calls.count // len(sockets),
        axis=world.axis,
        what="subtree reads per connection",
    )
    assert after_connect.count == 0, (
        f"{after_connect.count} subtree reads happened while delivering ONE event to "
        f"{len(sockets)} connections — the N+1 the push design exists to refuse."
    )
    report(
        "THE CONNECT READ (calls to list_subtree_org_ids)",
        [
            ("world", world.axis),
            ("connections opened at the root hat", len(sockets)),
            ("subtree reads during connect", calls.count),
            ("subtree reads per connection", calls.count // len(sockets)),
            ("subtree reads while pushing one event to all of them", after_connect.count),
            ("group memberships held for those connections", joined),
        ],
    )


# --- 4. THE 500-SOCKET WORLD: fan-out, census, both topologies ----------------


@dataclass(frozen=True)
class Population:
    """The declared socket world: who is online, at which org, on which socket."""

    sockets: list[Socket]
    orgs: list[Organization]
    root_count: int
    region_count: int
    leaf_count: int

    def hearers(self, target: Organization) -> int:
        """How many of these hats have `target` in their subtree.

        Arithmetic over the seeded paths, computed independently of the channel
        layer — so the measured census has something it can be wrong against.
        """
        return sum(
            1
            for org in self.orgs
            if target.path == org.path or target.path.startswith(org.path + PATH_SEPARATOR)
        )


def population(*, world: World, size: int) -> Population:
    """`size` connections, hats mixed root/region/leaf as the fixture contract says.

    Leaf connections are spread deterministically across every partner org and
    region connections across every region. A census whose leaf sockets all sat
    in one org could not tell "the subtree heard it" from "everybody heard it",
    which is the whole property being re-proven at scale.
    """
    root_count = max(1, round(size * ROOT_SOCKET_SHARE))
    region_count = round(size * REGION_SOCKET_SHARE)
    leaf_count = size - root_count - region_count

    chosen: list[tuple[str, Organization]] = [("root", world.root)] * root_count
    chosen += [("region", world.regions[i % len(world.regions)]) for i in range(region_count)]
    chosen += [("leaf", world.partners[i % len(world.partners)]) for i in range(leaf_count)]

    sockets = [
        Socket(scoped_app(user=world.users[position], tenant=world.tenant, org=org), "/ws/events/")
        for position, org in chosen
    ]
    return Population(sockets, [org for _, org in chosen], root_count, region_count, leaf_count)


@pytest.mark.asyncio
async def test_fan_out_and_census_at_500_sockets(world: World, layer: Any) -> None:
    """The chosen topology at the declared socket scale: one send, a narrow census.

    Three numbers, and the third is the one RT2 proved at four sockets:

    * **sends per emit** — one, always. The narrowing already happened, at
      connect, so the publish side does not fan out at all. This is the half of
      the trade ADR realtime-2 bought with the join cost, and it is the half the
      rejected alternative would have sold back.
    * **frames delivered** — the recipients, and nobody else.
    * **the census** — measured recipients equal the arithmetic over the seeded
      paths. A region emit reaches the root hats and that region's own hats; the
      other 39 regions' sockets and every partner hat below hear nothing, at 500
      connections exactly as at four.

    The OLD topology is measured on the same population through the still-live
    `tenant_group` primitive, which is what makes the comparison a measurement
    rather than a memory of what the code used to do.
    """
    crowd = population(world=world, size=world.spec.sockets)
    region = world.regions[0]
    leaf = world.partners[0]

    async with connected(crowd.sockets):
        joined = memberships(layer)
        results: dict[str, tuple[int, int, int]] = {}
        for label, target in (("region emit", region), ("leaf emit", leaf)):
            with call_counter(layer, "group_send") as sends:
                await push_event(
                    tenant_id=world.tenant.pk, event=message(organization_id=target.pk)
                )
            frames = await census(crowd.sockets)
            expected = crowd.hearers(target)
            assert sends.count == 1, f"{label}: {sends.count} group sends for one emit"
            assert max(frames) <= 1, f"{label}: a socket got {max(frames)} copies of one emit"
            assert sum(frames) == expected, (
                f"{label}: {sum(frames)} sockets heard it; the seeded paths say {expected}"
            )
            results[label] = (sends.count, sum(frames), expected)

        # The OLD topology, on the same population: one send to the bare tenant
        # group, which every connection still joins for org-less events.
        with call_counter(layer, "group_send") as old_sends:
            await layer.group_send(
                tenant_group(world.tenant.pk),
                {
                    "type": MESSAGE_TYPE,
                    "message": message(organization_id=region.pk).model_dump(mode="json"),
                },
            )
        old_frames = await census(crowd.sockets)

        # And the org-less event's tenant-wide path, unchanged by any of this.
        with call_counter(layer, "group_send") as wide_sends:
            await push_event(tenant_id=world.tenant.pk, event=message(organization_id=None))
        wide_frames = await census(crowd.sockets)

    assert sum(old_frames) == len(crowd.sockets), "the old topology did not reach everybody"
    assert wide_sends.count == 1 and sum(wide_frames) == len(crowd.sockets), (
        "an org-less event is tenant-wide and must still reach every connection"
    )

    region_sends, region_frames, region_expected = results["region emit"]
    leaf_sends, leaf_frames, leaf_expected = results["leaf emit"]
    report(
        f"PUBLISH FAN-OUT AT {len(crowd.sockets)} SOCKETS ({world.axis})",
        [
            (
                "population (root / region / leaf hats)",
                f"{crowd.root_count} / {crowd.region_count} / {crowd.leaf_count}",
            ),
            ("group memberships held by the layer", joined),
            ("memberships per connection (mean)", f"{joined / len(crowd.sockets):.1f}"),
            (
                "NEW region emit: sends / frames / expected",
                f"{region_sends}/{region_frames}/{region_expected}",
            ),
            (
                "NEW leaf emit:   sends / frames / expected",
                f"{leaf_sends}/{leaf_frames}/{leaf_expected}",
            ),
            (
                "OLD region emit: sends / frames (bare tenant group)",
                f"{old_sends.count}/{sum(old_frames)}",
            ),
            ("frames the fix stops delivering to a wrong branch", sum(old_frames) - region_frames),
            (
                "org-less emit: sends / frames (must stay tenant-wide)",
                f"{wide_sends.count}/{sum(wide_frames)}",
            ),
        ],
    )


@pytest.mark.asyncio
async def test_frames_per_recipient_flat_under_connection_doubling(
    world: World, layer: Any
) -> None:
    """500 -> 1,000 connections: one frame each, total linear in recipients.

    The `sockets` axis is declared, not seeded (`ScaleSpec.sockets`) — connections
    are runtime — so the doubling happens here, in-process, rather than through
    `perf.sh --double sockets`. The plan states the expected shape: **flat per
    recipient, total linear in recipients**. Both halves are measured. The
    per-recipient half is the criterion, because a per-recipient count that grew
    would be duplicate delivery; the linear half is the arithmetic that follows
    from one frame each, and it is recorded so the envelope can quote it.
    """
    region = world.regions[0]
    measured: dict[int, tuple[int, int, int, int]] = {}
    for size in (world.spec.sockets, world.spec.sockets * 2):
        await layer.flush()
        crowd = population(world=world, size=size)
        async with connected(crowd.sockets):
            held = memberships(layer)
            with call_counter(layer, "group_send") as sends:
                await push_event(
                    tenant_id=world.tenant.pk, event=message(organization_id=region.pk)
                )
            frames = await census(crowd.sockets)
        recipients = sum(1 for count in frames if count)
        assert max(frames) <= 1, f"{size}: a socket received {max(frames)} copies of one emit"
        assert recipients == crowd.hearers(region), f"{size}: census does not match the paths"
        measured[size] = (sends.count, recipients, sum(frames), held)

    base_sends, base_recipients, base_frames, base_held = measured[world.spec.sockets]
    twin_sends, twin_recipients, twin_frames, twin_held = measured[world.spec.sockets * 2]
    flat_under_doubling(
        base=base_sends, doubled=twin_sends, axis="sockets", what="group sends per emit"
    )
    flat_under_doubling(
        base=base_frames // base_recipients,
        doubled=twin_frames // twin_recipients,
        axis="sockets",
        what="frames delivered per recipient",
    )
    report(
        f"CONNECTION DOUBLING ({world.spec.sockets} -> {world.spec.sockets * 2})",
        [
            ("world", world.axis),
            (
                f"{world.spec.sockets:>5} sends / recipients / frames / memberships",
                f"{base_sends} / {base_recipients} / {base_frames} / {base_held}",
            ),
            (
                f"{world.spec.sockets * 2:>5} sends / recipients / frames / memberships",
                f"{twin_sends} / {twin_recipients} / {twin_frames} / {twin_held}",
            ),
            (
                "frames per recipient",
                f"{base_frames // base_recipients} -> {twin_frames // twin_recipients}",
            ),
            ("memberships per connection (mean)", f"{base_held / world.spec.sockets:.1f}"),
        ],
    )


# --- 5. THE KICK AT SCALE -----------------------------------------------------


@pytest.mark.asyncio
async def test_kick_closes_every_socket_one_person_holds(world: World, layer: Any) -> None:
    """One user, 50 sockets, one send, fifty closes — and nobody else touched.

    The primitive A1 calls on revocation and erasure. The measure is the *send*
    count (one, to the user group) against the *close* count (all fifty),
    because a kick that cost one send per socket would be the fan-out this
    design spent the join cost to avoid, and a kick that closed some of them
    would be a revocation that did not revoke.
    """
    leaf = world.partners[0]
    mine = [
        Socket(scoped_app(user=world.users["leaf"], tenant=world.tenant, org=leaf), "/ws/events/")
        for _ in range(50)
    ]
    theirs = [
        Socket(scoped_app(user=world.users["region"], tenant=world.tenant, org=leaf), "/ws/events/")
        for _ in range(10)
    ]

    async with connected([*mine, *theirs]):
        with call_counter(layer, "group_send") as sends:
            await layer.group_send(
                user_group(world.users["leaf"].pk), {"type": KICK_TYPE, "reason": "measured"}
            )
        await asyncio.sleep(SETTLE)
        closes = [await close_code(socket) for socket in mine]
        untouched = [await close_code(socket) for socket in theirs]

    assert sends.count == 1, f"{sends.count} sends to close {len(mine)} sockets"
    assert closes == [CLOSE_KICKED] * len(mine), closes
    assert untouched == [None] * len(theirs), untouched
    report(
        "KICK AT SCALE (one person, fifty sockets)",
        [
            ("world", world.axis),
            ("sockets held by the kicked user", len(mine)),
            ("group sends to close all of them", sends.count),
            (f"sockets closed with {CLOSE_KICKED}", sum(1 for c in closes if c == CLOSE_KICKED)),
            ("another user's sockets closed", sum(1 for c in untouched if c is not None)),
        ],
    )


async def close_code(socket: Socket) -> int | None:
    """The close frame this socket was sent, or None if it is still open."""
    try:
        frame = await socket.output(timeout=0.01)
    except TimeoutError:
        return None
    return int(frame.get("code")) if frame.get("type") == "websocket.close" else None


# --- 6. THE REJECTED ALTERNATIVE, PRICED --------------------------------------


def test_the_alternatives_price(world: World) -> None:
    """What ancestor-chain publish would have cost, on this world's arithmetic.

    Recorded so the trigger number has the other side of its trade beside it.
    Under the rejected shape a subscriber joins ONE org group and the publisher
    sends to the row-org's whole ancestor chain: the join cost collapses to a
    constant and the send cost becomes `depth + 1` per emit, paid on **every**
    emit whether or not anybody is connected.

    This is arithmetic over the seeded paths, not a second implementation. The
    ADR asked for the join count; this is the number it would be traded against,
    and the PM needs both on one line to fire the trigger or leave it standing.
    """
    paths = list(Organization.objects.for_tenant(world.tenant).values_list("path", flat=True))
    depths = [path.count(PATH_SEPARATOR) + 1 for path in paths]
    mean_chain = sum(depths) / len(depths)
    emits = world.spec.events  # the fixture contract's own per-tenant volume
    report(
        "THE REJECTED ALTERNATIVE, PRICED (ancestor-chain publish)",
        [
            ("world", world.axis),
            (
                "CHOSEN  joins at the root hat, once per connection",
                world.hats[0].expected_subtree + 2,
            ),
            (
                "CHOSEN  joins at the 200-wide hat, once per connection",
                world.hats[3].expected_subtree + 2,
            ),
            ("CHOSEN  sends per emit", 1),
            ("ALT     joins per connection", 3),
            ("ALT     sends per emit (mean / deepest)", f"{mean_chain:.1f} / {max(depths)}"),
            (
                "ALT     extra sends per seeded year of events",
                f"{int((mean_chain - 1) * emits):,}",
            ),
            ("CHOSEN  extra joins per seeded socket population", f"{world.spec.sockets} x subtree"),
        ],
    )
