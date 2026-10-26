"""The fixture contract, stated once, and the seeder that makes it true.

`ScaleSpec` below is **the** statement of the ratified volumes (ADR perf-1;
the cycle plan's table is ratified prose, this dataclass is the artifact).
`seed_scale(spec)` builds the world **through the models, never raw SQL**:
BaseModel uuid7 pks, scoped FKs, real materialized paths built with the same
`child_path`/`encode_path_segment` grammar `core.services` uses, rows that
`for_tenant(...).visible_to(...)` can actually see. Seeding is
`bulk_create`-batched, so ~1.5M rows land in minutes, not hours.

Per-axis semantics, stated so nobody has to guess:

* **per loaded tenant** — orgs, memberships, widgets, events (and their outbox
  rows), api tokens. The two loaded tenants are identical worlds.
* **totals across the deployment** — endpoints, deliveries, audit entries
  (incl. the platform NULL-tenant slice), workflow runs (spread over all
  tenants — the ledger the reconciler sweeps), comms recipients/messages.
* **declared, not seeded** — `sockets`: connections are runtime, opened at
  serve time and not seed time; the axis lives here so the doubling grammar
  covers it.

**The events seed stamps `Event.organization` through the real seam** — the
body-carried envelope (ADR realtime-2a): each org-bearing payload carries
`organization_id` exactly as an `Out` schema would, and the stamp is derived
by calling `apps.events.services._subject_organization` on that payload. The
derivation is memoized per organization id (it is a pure scoped read, so the
memo changes nothing but the query count of the *seeding* run); org-less
payloads stay NULL, which means tenant-wide.

**Reuse and invalidation** ride on the stamp tenant: its slug embeds the
active spec's hash (`perf-stamp-<hash12>`), so an unchanged spec is a stamp
hit (no re-seed) and any one-line spec change is a stamp miss —
`scripts/perf.sh` then resets the `_perf` database and seeds the new world.

Known refusal, stated: `doubled("depth")` yields `spine_depth = 24`, and the
platform's own path grammar refuses it (`PATH_MAX_DEPTH = 12` — the ceiling
an early scale proposal called ample). The seeder raises `PathOverflow` rather
than faking a tree the product could not hold; measuring beyond the ceiling
means raising the ceiling first, which is a lead decision, not a seed option.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

# Everything Django is imported lazily, inside the functions that need it, so
# `ScaleSpec` and the hash/stamp helpers are importable from anywhere (the
# measurement modules, conftest, `python -m perf.seed`) before `django.setup()`.

BATCH = 5_000
STAMP_PREFIX = "perf-stamp-"
LOADED_SLUGS = ("perf-a", "perf-b")
HEAVY_ORG_SLUG = "r00-p00"
REGION_HAT_SLUG = "region-00"
EVENT_NAME = "example.widget.created"  # apps/example/events.py declares it

# Which spec fields double together when one axis is stressed (the doubling
# tier is per-axis, never a giant double-everything world — ADR perf-1).
DOUBLING_AXES: dict[str, tuple[str, ...]] = {
    "tenants": ("tenants",),
    "orgs": ("regions",),
    "depth": ("spine_depth",),
    "breadth": ("wide_children",),
    "memberships": ("memberships", "many_hats"),
    "widgets": ("widgets", "widget_heaviest"),
    "events": ("events", "events_pending"),
    "endpoints": ("endpoints",),
    "deliveries": ("deliveries",),
    "audit": ("audit_entries", "audit_platform"),
    "runs": ("workflow_runs", "workflow_runs_platform"),
    "comms": ("recipients", "messages"),
    "tokens": ("api_tokens",),
    "sockets": ("sockets",),
}


@dataclass(frozen=True)
class ScaleSpec:
    """The declared reference-real-scale volumes. ADR perf-1's numbers."""

    # 25 tenants: 2 loaded twins, the rest background (1 root org,
    # `background_members` members, `background_widgets` rows each).
    tenants: int = 25
    loaded_tenants: int = 2

    # The org tree per loaded tenant: root -> `regions` regions ->
    # `partners_per_region` partner orgs each; plus one spine chain to
    # `spine_depth` segments (the platform's own "deep" vocabulary: the root
    # path is 1 segment, so the deepest spine node has `spine_depth` segments
    # and `path_depth == spine_depth - 1`); plus one node with
    # `wide_children` direct children (the breadth stressor).
    regions: int = 40
    partners_per_region: int = 25
    spine_depth: int = 12
    wide_children: int = 200

    # Memberships per loaded tenant; the three hat positions (root, one
    # region whose subtree is 1 + partners_per_region orgs, one leaf) are
    # seeded as named users — see `hat_emails`.
    memberships: int = 3_000

    # **One person wearing many hats in one tenant** — the shape `Membership`'s
    # own docstring names ("a regional manager over two branches") and the one
    # the 3,000 above do not contain, because each of those people holds
    # exactly one. `resolve_org` materialises every membership the person
    # holds in the tenant, and with one-per-person a seeded world priced a
    # population of 1 — a blind spot worth seeding around. These hats sit on
    # the **spine chain** (root
    # first, then each spine node) so they share one ancestor line, which is
    # what makes effective-role resolution over them interesting; when the
    # axis doubles past the chain the overflow lands on unrelated partner
    # branches. Additional to `memberships`, never carved out of it.
    many_hats: int = 12

    # Org-scoped rows (example.Widget, the proxy for the 51 doctypes) per
    # loaded tenant, skewed: the heaviest org holds `widget_heaviest`.
    widgets: int = 100_000
    widget_heaviest: int = 5_000

    # Events (and their outbox rows) per loaded tenant; `events_pending` of
    # them sit in the retry-pending slice (`next_attempt_at` set). The
    # org-bearing share carries `organization_id` in the payload and is
    # stamped through the real seam.
    events: int = 200_000
    events_pending: int = 10_000
    org_bearing_percent: int = 80

    # Webhook fan-out at subscriber scale: totals across the loaded pair.
    endpoints: int = 25
    deliveries: int = 100_000

    # The audit ledger: total, including the platform NULL-tenant slice.
    audit_entries: int = 500_000
    audit_platform: int = 10_000

    # The run ledger the reconciler sweeps: total, spread over all tenants —
    # including the platform (NULL-tenant) slice ADR workflows-3 declares as a
    # first-class population. Held at the same
    # 2% share of the ledger the audit trail's platform slice carries, so the
    # two declared null populations are proportioned alike.
    workflow_runs: int = 50_000
    workflow_runs_platform: int = 1_000

    # Campaign-scale comms against the wall: totals across the loaded pair;
    # `suppressed_percent` of messages are SUPPRESSED rows and the same share
    # of recipients carry a suppressed email ChannelPreference.
    recipients: int = 10_000
    messages: int = 100_000
    suppressed_percent: int = 2

    # Machine doors at fleet scale: per loaded tenant.
    api_tokens: int = 500

    # Declared for the runtime axis (concurrent connections are runtime, not rows).
    sockets: int = 500

    background_members: int = 3
    background_widgets: int = 100

    def doubled(self, axis: str) -> ScaleSpec:
        """This spec with exactly one axis at x2. Everything else unchanged."""
        try:
            fields = DOUBLING_AXES[axis]
        except KeyError:
            known = ", ".join(sorted(DOUBLING_AXES))
            raise ValueError(f"unknown doubling axis {axis!r}; one of: {known}") from None
        return dataclasses.replace(self, **{name: getattr(self, name) * 2 for name in fields})

    @property
    def orgs_per_loaded_tenant(self) -> int:
        """Root + regions + partners + spine nodes + the wide node + its children."""
        return (
            1
            + self.regions
            + self.regions * self.partners_per_region
            + (self.spine_depth - 1)
            + 1
            + self.wide_children
        )

    @property
    def background_tenants(self) -> int:
        return self.tenants - self.loaded_tenants


DEFAULT_SPEC = ScaleSpec()


def spec_for_stamp(slug: str) -> ScaleSpec | None:
    """The spec a stamp slug names, or None for a slug no declared spec hashes to.

    The recognizable population is closed: the default spec and every
    single-axis doubling of it. The seeded world is therefore self-describing
    — measurement runs read WHICH world they are in off the stamp, and no
    environment variable has to agree with anything (the plan's settled "no
    new env vars" holds: the axis travels as a CLI argument to the seeder,
    and the database itself tells the fixtures).
    """
    candidates = [DEFAULT_SPEC] + [DEFAULT_SPEC.doubled(axis) for axis in DOUBLING_AXES]
    for candidate in candidates:
        if stamp_slug(candidate) == slug:
            return candidate
    return None


def seeded_spec() -> ScaleSpec:
    """The spec of the world actually in the database. Fails closed.

    Raises when there is no stamp (unseeded), more than one (a world nothing
    declared), or a stamp no declared spec hashes to (a stale ScaleSpec
    edit): every one of those is a world whose numbers would describe
    nothing, and the refusal names the way out.
    """
    from apps.core.models import Tenant

    stamps = list(
        Tenant.objects.filter(slug__startswith=STAMP_PREFIX).values_list("slug", flat=True)
    )
    if len(stamps) == 1:
        spec = spec_for_stamp(stamps[0])
        if spec is not None:
            return spec
    raise RuntimeError(
        f"the perf database holds no recognizable world (stamps: {stamps or 'none'}); "
        "re-seed through scripts/perf.sh."
    )


def spec_hash(spec: ScaleSpec) -> str:
    """Twelve hex characters over the spec's field values. Stable by content."""
    payload = json.dumps(dataclasses.asdict(spec), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def stamp_slug(spec: ScaleSpec) -> str:
    return f"{STAMP_PREFIX}{spec_hash(spec)}"


def hat_emails(tenant_slug: str) -> dict[str, str]:
    """The named hat users a measurement module resolves by email.

    The first three are the three visibility workloads (root, a region whose
    subtree is one region's worth, a leaf). `many` is the fourth and it is a
    *person* shape rather than a position: one user holding `many_hats`
    memberships in this tenant — the blind spot a one-hat-per-person world
    would otherwise hide, seeded so it can be priced.
    """
    return {
        "root": f"root-hat@{tenant_slug}.example.invalid",
        "region": f"region-hat@{tenant_slug}.example.invalid",
        "leaf": f"leaf-hat@{tenant_slug}.example.invalid",
        "many": f"many-hats@{tenant_slug}.example.invalid",
    }


# --- The deterministic allocations (arithmetic a spot-check can recompute) ---


def partner_slugs(spec: ScaleSpec) -> list[str]:
    """Every partner org slug, in (region, partner) order: r00-p00, r00-p01, ..."""
    return [
        f"r{region:02d}-p{partner:02d}"
        for region in range(spec.regions)
        for partner in range(spec.partners_per_region)
    ]


def widget_allocation(spec: ScaleSpec) -> dict[str, int]:
    """Widgets per org slug, per loaded tenant. Skewed, deterministic.

    The heaviest org (`r00-p00`) holds exactly `widget_heaviest`; the rest is
    spread evenly over the other partners, remainder to the earliest slugs.
    A subtree's expected share is the sum of this dict over its members,
    which is what the census's `visible_to` spot-check recomputes.
    """
    slugs = partner_slugs(spec)
    others = [slug for slug in slugs if slug != HEAVY_ORG_SLUG]
    rest = spec.widgets - spec.widget_heaviest
    base, remainder = divmod(rest, len(others))
    allocation = {HEAVY_ORG_SLUG: spec.widget_heaviest}
    for index, slug in enumerate(others):
        allocation[slug] = base + (1 if index < remainder else 0)
    return allocation


def expected_region_widgets(spec: ScaleSpec, region: int = 0) -> int:
    """The widget count a region hat's `visible_to` must resolve to."""
    allocation = widget_allocation(spec)
    prefix = f"r{region:02d}-p"
    return sum(count for slug, count in allocation.items() if slug.startswith(prefix))


def membership_position(spec: ScaleSpec, index: int) -> tuple[str, int]:
    """Where the index-th membership of a loaded tenant sits.

    Returns ("root", 0) | ("region", r) | ("partner", p). The first three are
    the named hats; the rest spread ~0.3% root, ~20% regions, the bulk on
    partners — thousands of reps across a network.
    """
    if index == 0:
        return ("root", 0)
    if index == 1:
        return ("region", 0)
    if index == 2:
        return ("partner", 0)  # the leaf hat sits on the heavy partner
    position = index % 300
    if position == 0:
        return ("root", 0)
    if position < 60:
        return ("region", index % spec.regions)
    return ("partner", index % (spec.regions * spec.partners_per_region))


def many_hats_organizations(spec: ScaleSpec, tree: dict[str, Any]) -> list[Any]:
    """Where the many-hats person's `many_hats` memberships sit, in order.

    The **spine chain first** — root, then each spine node — because that is
    one ancestor line and it is the shape that makes upward role resolution
    and `resolve_org`'s membership read say something: the person's hats are
    nested inside each other. Past the chain's length (which is `spine_depth`)
    the overflow lands on partner orgs in slug order: unrelated branches, the
    other half of `Membership`'s own "a regional manager over two branches".
    Arithmetic the census recomputes rather than reads off the rows.
    """
    chain = [tree["root"], *tree["spine"]]
    overflow = [tree["partners"][slug] for slug in partner_slugs(spec)]
    return (chain + overflow)[: spec.many_hats]


def spine_chain_organizations(tree: dict[str, Any]) -> list[Any]:
    """Root plus every spine node — the ancestor chain of the deepest legal node.

    The population `WidgetPolicy` rows are seeded onto, so `governing()` has a
    populated path to resolve at the depth ceiling (a declared limitation:
    an EXPLAIN over an empty policy table describes nothing).
    """
    return [tree["root"], *tree["spine"]]


def workflow_run_status(spec: ScaleSpec, index: int, tenant_count: int) -> int:
    """Which of the five status buckets row `index` falls in. 0-2 done, 3 failed, 4 running.

    **The bucket is derived from the row's position *within its tenant***, not
    from the row index itself. A prior scheme, `index % tenant_count` picking
    the tenant and `index % 5` picking the bucket, locked the two together
    with 25 tenants — every run a tenant owned had the same status, five
    tenants held every RUNNING row, and `perf-a` (the tenant every other
    measure uses) held none. Dividing by the tenant count first gives each
    tenant its own 0,1,2,3,4,0,… sequence, i.e. the intended 60/20/20 mix, for
    any tenant count.
    """
    return (index // tenant_count) % 5


# --- Guards ------------------------------------------------------------------


class PerfDatabaseRefused(RuntimeError):
    """The configured database is not a `_perf` database. Fail closed."""


def require_perf_database() -> str:
    """Refuse to touch a database whose name does not end in `_perf`.

    The belt to `scripts/perf.sh`'s brace: seeding is destructive-adjacent
    (`perf.sh` drops and re-creates on a stamp miss), so a mis-exported
    DATABASE_NAME must refuse here too, not only at the script.
    """
    from django.conf import settings

    name = str(settings.DATABASES["default"]["NAME"])
    if not name.endswith("_perf"):
        raise PerfDatabaseRefused(
            f"database {name!r} does not end in '_perf'. The harness only ever "
            "touches the per-checkout perf database; run it through scripts/perf.sh."
        )
    return name


def stamp_state(spec: ScaleSpec) -> tuple[bool, str]:
    """(fresh, detail): whether the seeded world matches this spec's stamp."""
    from apps.core.models import Tenant

    wanted = stamp_slug(spec)
    stamps = list(
        Tenant.objects.filter(slug__startswith=STAMP_PREFIX).values_list("slug", flat=True)
    )
    if wanted in stamps:
        return True, f"stamp hit: {wanted}"
    if stamps:
        return False, f"stamp miss: wanted {wanted}, found {', '.join(sorted(stamps))}"
    return False, f"stamp miss: wanted {wanted}, found none"


# --- Seeding -----------------------------------------------------------------


def _bulk(manager: Any, rows: list[Any]) -> None:
    if rows:
        manager.bulk_create(rows, batch_size=BATCH)
        rows.clear()


def _seed_tree(spec: ScaleSpec, tenant: Any) -> dict[str, Any]:
    """The org tree, with real paths: parents precede children in insert order.

    Pks are client-minted uuid7s, so every child can name its parent before a
    single row is inserted; `bulk_create` inserts in list order inside the
    seed transaction, so the FK is always satisfied.
    """
    from apps.core.models import Organization, child_path, path_depth

    root = Organization.objects.for_tenant(tenant).get(parent__isnull=True)

    def node(parent: Any, index: int, name: str, slug: str) -> Any:
        path = child_path(parent.path, index)
        return Organization(
            tenant=tenant,
            parent=parent,
            name=name,
            slug=slug,
            path=path,
            depth=path_depth(path),
        )

    ordered: list[Any] = []
    regions = [node(root, r, f"Region {r:02d}", f"region-{r:02d}") for r in range(spec.regions)]
    ordered.extend(regions)
    spine: list[Any] = []
    parent = root
    for level in range(1, spec.spine_depth):
        parent = node(
            parent, spec.regions if level == 1 else 0, f"Spine {level:02d}", f"spine-{level:02d}"
        )
        spine.append(parent)
        ordered.append(parent)
    wide = node(root, spec.regions + 1, "Wide", "wide")
    ordered.append(wide)
    ordered.extend(
        node(wide, c, f"Wide child {c:03d}", f"wide-{c:03d}") for c in range(spec.wide_children)
    )
    partners: dict[str, Any] = {}
    for r, region in enumerate(regions):
        for p in range(spec.partners_per_region):
            slug = f"r{r:02d}-p{p:02d}"
            partner = node(region, p, f"Partner {slug}", slug)
            partners[slug] = partner
            ordered.append(partner)
    Organization.objects.bulk_create(ordered, batch_size=BATCH)
    return {"root": root, "regions": regions, "partners": partners, "spine": spine, "wide": wide}


def _seed_people(spec: ScaleSpec, tenant: Any, tree: dict[str, Any]) -> list[Any]:
    """One user per membership; the three named hats first, then the many-hats person.

    Returns the users, the many-hats person last. Its `many_hats` memberships
    are additional to `spec.memberships` — the declared rep population keeps
    its number and the one-person-many-hats shape is a named addition beside
    it, so a reader of the census can tell which population a count is about.
    """
    from apps.accounts.models import User
    from apps.core.models import Membership

    hats = hat_emails(tenant.slug)
    users: list[Any] = []
    for index in range(spec.memberships):
        if index == 0:
            email = hats["root"]
        elif index == 1:
            email = hats["region"]
        elif index == 2:
            email = hats["leaf"]
        else:
            email = f"perf-{tenant.slug}-{index:04d}@example.invalid"
        users.append(User(email=email, password="!", is_active=True))  # noqa: S106 — Django's unusable-password marker, so the seeded user cannot sign in
    User.objects.bulk_create(users, batch_size=BATCH)

    partner_list = partner_slugs(spec)
    memberships: list[Any] = []
    for index, user in enumerate(users):
        kind, which = membership_position(spec, index)
        if kind == "root":
            organization = tree["root"]
        elif kind == "region":
            organization = tree["regions"][which]
        else:
            organization = tree["partners"][partner_list[which]]
        role = Membership.Role.ADMIN if index in (0, 1) else Membership.Role.MEMBER
        memberships.append(
            Membership(
                user=user,
                tenant=tenant,
                organization=organization,
                is_default=True,
                role=role,
            )
        )
    Membership.objects.bulk_create(memberships, batch_size=BATCH)

    # The many-hats person — the seeded blind-spot case. One user,
    # `many_hats` memberships in this one tenant. `is_default` is unique per
    # USER across the whole
    # deployment (`membership_one_default_per_user`), so exactly the first hat
    # carries it and the rest are non-default — which is also the true shape:
    # a person has one home and several places they also work.
    many = User(email=hats["many"], password="!", is_active=True)  # noqa: S106 — Django's unusable-password marker, so the seeded user cannot sign in
    many.save()
    Membership.objects.bulk_create(
        [
            Membership(
                user=many,
                tenant=tenant,
                organization=organization,
                is_default=(position == 0),
                role=Membership.Role.MEMBER,
            )
            for position, organization in enumerate(many_hats_organizations(spec, tree))
        ],
        batch_size=BATCH,
    )
    users.append(many)
    return users


def _seed_widgets(spec: ScaleSpec, tenant: Any, tree: dict[str, Any], owner: Any) -> None:
    from apps.example.models import Widget

    rows: list[Any] = []
    for slug, count in widget_allocation(spec).items():
        organization = tree["partners"][slug]
        for n in range(count):
            rows.append(
                Widget(
                    tenant=tenant,
                    organization=organization,
                    owner=owner,
                    name=f"w-{slug}-{n:05d}",
                )
            )
            if len(rows) >= BATCH:
                _bulk(Widget.objects, rows)
    _bulk(Widget.objects, rows)


def _seed_policies(spec: ScaleSpec, tenant: Any, tree: dict[str, Any]) -> None:
    """One `WidgetPolicy` per node on the spine's ancestor chain.

    Recorded as a declared limitation rather than a finding: an earlier
    seeder created `Widget` rows and no policies, so
    `WidgetPolicy.objects.for_tenant(t).governing(org)` resolved zero rows at
    every hat and the plan it took described an empty table. That seeder worked around
    it by reading the plan off the ancestor-path predicate against
    `core_organization` instead, and said the fix belonged to whoever next
    owned `perf/seed.py`. This is that.

    One row per ancestor, not a volume: `governing()` is upward *config*
    resolution and the interesting number is the chain's length, which is
    bounded by `PATH_MAX_DEPTH`. Every row carries the same `name` on a
    different organization, which is legal (the uniqueness is per
    organization) and is exactly the case `governing()` resolves nearest-first.
    """
    from apps.example.models import WidgetPolicy

    _bulk(
        WidgetPolicy.objects,
        [
            WidgetPolicy(
                tenant=tenant,
                organization=organization,
                name="perf-governing",
                body=f"seeded at {organization.slug}",
            )
            for organization in spine_chain_organizations(tree)
        ],
    )


def _seed_events(spec: ScaleSpec, tenant: Any, tree: dict[str, Any]) -> list[Any]:
    """Events + outbox rows. The org stamp goes through the real seam.

    Returns the event pks (needed by the delivery fan-out).
    """
    from apps.core.time import now
    from apps.events.models import Event, Outbox
    from apps.events.services import _subject_organization

    base_now = now()
    all_orgs = list(tree["partners"].values()) + tree["spine"] + [tree["wide"]]
    memo: dict[str, Any] = {}

    def stamped(payload: dict[str, Any]) -> Any:
        """The body-carried envelope, memoized per organization id.

        The seam is a pure scoped read, so memoizing changes nothing but the
        seeding run's own query count; every distinct org id is still derived
        by the production function, not by this module's loop variable.
        """
        key = str(payload.get("organization_id", ""))
        if not key:
            return None
        if key not in memo:
            memo[key] = _subject_organization(tenant=tenant, payload=payload)
        return memo[key]

    events: list[Any] = []
    outboxes: list[Any] = []
    pks: list[Any] = []
    for index in range(spec.events):
        if index % 100 < spec.org_bearing_percent:
            subject = all_orgs[index % len(all_orgs)]
            payload: dict[str, Any] = {"v": 1, "organization_id": str(subject.pk)}
        else:
            payload = {"v": 1}
        occurred_at = base_now - timedelta(
            days=(index * 365) // max(spec.events, 1), minutes=index % 1440
        )
        event = Event(
            tenant=tenant,
            name=EVENT_NAME,
            v=1,
            payload=payload,
            organization=stamped(payload),
            occurred_at=occurred_at,
        )
        pks.append(event.pk)
        events.append(event)
        if index < spec.events_pending:
            outboxes.append(
                Outbox(
                    event=event,
                    status=Outbox.Status.PENDING,
                    attempts=1,
                    next_attempt_at=base_now + timedelta(minutes=index % 60),
                )
            )
        else:
            outboxes.append(
                Outbox(
                    event=event,
                    status=Outbox.Status.DISPATCHED,
                    attempts=1,
                    dispatched_at=occurred_at,
                )
            )
        if len(events) >= BATCH:
            _bulk(Event.objects, events)
            _bulk(Outbox.objects, outboxes)
    _bulk(Event.objects, events)
    _bulk(Outbox.objects, outboxes)
    return pks


def _seed_deliveries(spec: ScaleSpec, loaded: list[Any], event_pks: dict[str, list[Any]]) -> None:
    from apps.core.time import now
    from apps.events.models import Delivery, WebhookEndpoint

    base_now = now()
    endpoints: list[Any] = []
    for index in range(spec.endpoints):
        tenant = loaded[index % len(loaded)]
        endpoints.append(
            WebhookEndpoint(
                tenant=tenant,
                url=f"https://perf.example.invalid/hook/{index:03d}",
                secret=f"perf-endpoint-{index:03d}",
                is_active=True,
            )
        )
    WebhookEndpoint.objects.bulk_create(endpoints, batch_size=BATCH)

    rows: list[Any] = []
    for index in range(spec.deliveries):
        endpoint = endpoints[index % len(endpoints)]
        pks = event_pks[endpoint.tenant.slug]
        rows.append(
            Delivery(
                endpoint=endpoint,
                event_id=pks[index % len(pks)],
                status=Delivery.Status.DELIVERED,
                attempts=1,
                last_code=200,
                delivered_at=base_now - timedelta(minutes=index % 1440),
            )
        )
        if len(rows) >= BATCH:
            _bulk(Delivery.objects, rows)
    _bulk(Delivery.objects, rows)


def _seed_workflow_runs(spec: ScaleSpec, tenants: list[Any]) -> None:
    """The run ledger, statuses spread across **every** tenant.

    The tenant is still `index % len(tenants)`; the status bucket is now
    `workflow_run_status`, which divides by the tenant count first. The two
    used to be `index % len(tenants)` and `index % 5`, locked together at 25
    tenants, so each tenant held exactly one status.
    """
    from apps.core.time import now
    from apps.workflows.models import WorkflowRun

    base_now = now()
    rows: list[Any] = []
    for index in range(spec.workflow_runs):
        tenant = tenants[index % len(tenants)]
        bucket = workflow_run_status(spec, index, len(tenants))
        started_at = base_now - timedelta(minutes=30 + index % 10_000)
        if bucket < 3:
            status, finished_at, error = WorkflowRun.Status.COMPLETED, started_at, ""
        elif bucket == 3:
            status, finished_at, error = WorkflowRun.Status.FAILED, started_at, "perf: seeded"
        else:
            status, finished_at, error = WorkflowRun.Status.RUNNING, None, ""
        rows.append(
            WorkflowRun(
                tenant=tenant,
                workflow_id=f"{tenant.slug}:perf:run:{index:06d}",
                type="PerfSeededWorkflow",
                status=status,
                started_at=started_at,
                finished_at=finished_at,
                error=error,
            )
        )
        if len(rows) >= BATCH:
            _bulk(WorkflowRun.objects, rows)
    _bulk(WorkflowRun.objects, rows)


def _seed_platform_runs(spec: ScaleSpec) -> None:
    """The NULL-tenant run population, which had no axis at all.

    `WorkflowRun.objects.for_platform()` is a declared, first-class population
    (ADR workflows-3, rule 8's platform half) and the seeded world gave it
    zero rows, so every plan taken over it described an empty table and the
    envelope stated nothing about it. The ids carry the reserved `platform:`
    segment the unique constraint `workflowrun_unique_platform_workflow_id`
    fences — a tenant may not borrow it, which is what makes the population a
    population rather than an accident.

    Same 60/20/20 mix as the tenant slice, on its own row index, so the
    platform's running slice is non-empty for whatever sweeps it.
    """
    from apps.core.time import now
    from apps.workflows.models import WorkflowRun

    base_now = now()
    rows: list[Any] = []
    for index in range(spec.workflow_runs_platform):
        bucket = index % 5
        started_at = base_now - timedelta(minutes=30 + index % 10_000)
        if bucket < 3:
            status, finished_at, error = WorkflowRun.Status.COMPLETED, started_at, ""
        elif bucket == 3:
            status, finished_at, error = WorkflowRun.Status.FAILED, started_at, "perf: seeded"
        else:
            status, finished_at, error = WorkflowRun.Status.RUNNING, None, ""
        rows.append(
            WorkflowRun(
                tenant=None,
                workflow_id=f"platform:perf:run:{index:06d}",
                type="PerfSeededPlatformWorkflow",
                status=status,
                started_at=started_at,
                finished_at=finished_at,
                error=error,
            )
        )
        if len(rows) >= BATCH:
            _bulk(WorkflowRun.objects, rows)
    _bulk(WorkflowRun.objects, rows)


def _seed_comms(spec: ScaleSpec, loaded: list[Any], trees: dict[str, dict[str, Any]]) -> None:
    from apps.comms.models import (
        Category,
        Channel,
        ChannelPreference,
        Message,
        MessageTemplate,
        Recipient,
    )
    from apps.core.time import now

    base_now = now()
    suppress_every = max(100 // max(spec.suppressed_percent, 1), 1)
    templates = {
        tenant.slug: MessageTemplate(
            tenant=tenant,
            name="perf-template",
            version=1,
            channel=Channel.EMAIL,
            category=Category.TRANSACTIONAL,
            subject="perf",
            body="perf body",
        )
        for tenant in loaded
    }
    MessageTemplate.objects.bulk_create(list(templates.values()))

    recipients_per = spec.recipients // len(loaded)
    messages_per = spec.messages // len(loaded)
    for tenant in loaded:
        partners = list(trees[tenant.slug]["partners"].values())
        recipients: list[Any] = []
        for index in range(recipients_per):
            recipients.append(
                Recipient(
                    tenant=tenant,
                    organization=partners[index % len(partners)],
                    email=f"perf-r{index:05d}@example.invalid",
                    display_name=f"Perf recipient {index:05d}",
                )
            )
        Recipient.objects.bulk_create(recipients, batch_size=BATCH)
        preferences = [
            ChannelPreference(
                tenant=tenant,
                organization=recipient.organization,
                recipient=recipient,
                channel=Channel.EMAIL,
                suppressed_at=base_now if index % suppress_every == 0 else None,
            )
            for index, recipient in enumerate(recipients)
        ]
        ChannelPreference.objects.bulk_create(preferences, batch_size=BATCH)

        template = templates[tenant.slug]
        rows: list[Any] = []
        for index in range(messages_per):
            recipient = recipients[index % len(recipients)]
            suppressed = index % suppress_every == 0
            rows.append(
                Message(
                    tenant=tenant,
                    organization=recipient.organization,
                    recipient=recipient,
                    template=template,
                    template_name=template.name,
                    template_version=template.version,
                    channel=Channel.EMAIL,
                    category=Category.MARKETING if index % 5 == 0 else Category.TRANSACTIONAL,
                    status=Message.Status.SUPPRESSED if suppressed else Message.Status.SENT,
                    suppressed_reason=(Message.SuppressedReason.SUPPRESSED if suppressed else ""),
                    suppressed_at=base_now if suppressed else None,
                    sent_at=None if suppressed else base_now - timedelta(minutes=index % 1440),
                )
            )
            if len(rows) >= BATCH:
                _bulk(Message.objects, rows)
        _bulk(Message.objects, rows)


def _seed_tokens(spec: ScaleSpec, tenant: Any, users: list[Any]) -> None:
    from apps.accounts.models import ApiToken

    rows = [
        ApiToken(
            user=users[index % len(users)],
            tenant=tenant,
            name=f"perf-token-{index:03d}",
            key_hash=hashlib.sha256(f"perf:{tenant.slug}:{index}".encode()).hexdigest(),
        )
        for index in range(spec.api_tokens)
    ]
    ApiToken.objects.bulk_create(rows, batch_size=BATCH)


def _seed_background(spec: ScaleSpec) -> list[Any]:
    from apps.accounts.models import User
    from apps.core.actor import system_actor
    from apps.core.models import Membership, Organization
    from apps.core.services import create_tenant
    from apps.example.models import Widget

    tenants: list[Any] = []
    for index in range(1, spec.background_tenants + 1):
        tenant = create_tenant(
            name=f"Perf background {index:02d}", slug=f"perf-bg-{index:02d}", actor=system_actor()
        )
        tenants.append(tenant)
        root = Organization.objects.for_tenant(tenant).get(parent__isnull=True)
        users = [
            User(email=f"bg-{tenant.slug}-{n}@example.invalid", password="!")  # noqa: S106 — Django's unusable-password marker, so the seeded user cannot sign in
            for n in range(spec.background_members)
        ]
        User.objects.bulk_create(users)
        Membership.objects.bulk_create(
            Membership(
                user=user,
                tenant=tenant,
                organization=root,
                is_default=True,
                role=Membership.Role.MEMBER,
            )
            for user in users
        )
        Widget.objects.bulk_create(
            [
                Widget(
                    tenant=tenant,
                    organization=root,
                    owner=users[0],
                    name=f"bg-w-{n:03d}",
                )
                for n in range(spec.background_widgets)
            ],
            batch_size=BATCH,
        )
    return tenants


def _seed_audit(spec: ScaleSpec, loaded: list[Any], trees: dict[str, dict[str, Any]]) -> None:
    """Top the ledger up to *exactly* the declared totals.

    Seeding services (create_tenant is `@service`) may have written a handful
    of rows already; the census demands exact numbers, so this counts what
    exists and seeds the difference — never a duplicate ledger beside it.
    """
    from apps.core.audit import AuditEntry

    per_tenant_target = (spec.audit_entries - spec.audit_platform) // len(loaded)
    for tenant in loaded:
        existing = AuditEntry.objects.for_tenant(tenant).count()
        orgs = list(trees[tenant.slug]["partners"].values())
        rows: list[Any] = []
        for index in range(max(per_tenant_target - existing, 0)):
            rows.append(
                AuditEntry(
                    tenant=tenant,
                    acting_org=orgs[index % len(orgs)],
                    action="perf.widget.seeded",
                    object_type="example.Widget",
                )
            )
            if len(rows) >= BATCH:
                _bulk(AuditEntry.objects, rows)
        _bulk(AuditEntry.objects, rows)
    existing_platform = AuditEntry.objects.for_platform().count()
    rows = [
        AuditEntry(tenant=None, action="perf.platform.seeded")
        for _ in range(max(spec.audit_platform - existing_platform, 0))
    ]
    _bulk(AuditEntry.objects, rows)


def analyze_world() -> None:
    """Give the planner statistics for the world that was just written.

    **Fixed here rather than in the measurements.** `seed_scale`
    bulk-inserts ~1.5M rows; until autovacuum reaches them Postgres plans
    against *default* statistics (`core_tenant` estimated at the built-in 50
    rows whatever it holds), so the same query in the same world gets a
    different plan depending on when you ask. One measurement pass saw exactly
    that — a `Seq Scan on core_tenant` minutes after seeding where the settled
    world takes `core_tenant_pkey` — and another saw the `X-Org` lookup drop
    `slug` out of its `Index Cond` in the same window. Both worked around it
    with their own `ANALYZE`, which is a measurement fixing the seeder's
    omission; that fix moved here.

    Statistics are part of "the world is seeded", not something autovacuum
    gets round to. `ANALYZE` writes no rows the census counts — it updates
    `pg_statistic` — so this changes nothing any axis measures, and it runs
    **after** the seed transaction commits so the statistics describe a world
    that exists.
    """
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("ANALYZE")


def seed_scale(spec: ScaleSpec) -> None:
    """Build the whole world, atomically, then ANALYZE it.

    The stamp commits with the world or not at all; the statistics are taken
    once it has committed (`analyze_world`, and the reason it is not optional).
    """
    from django.db import transaction

    from apps.core.actor import system_actor
    from apps.core.models import Tenant
    from apps.core.services import create_tenant

    require_perf_database()
    if Tenant.objects.exists():
        raise RuntimeError(
            "this perf database already holds a world but no current stamp; "
            "reset it first (scripts/perf.sh does this on a stamp miss)."
        )
    with transaction.atomic():
        loaded = [
            create_tenant(name=f"Perf loaded {slug}", slug=slug, actor=system_actor())
            for slug in LOADED_SLUGS
        ][: spec.loaded_tenants]
        trees: dict[str, dict[str, Any]] = {}
        event_pks: dict[str, list[Any]] = {}
        users_by_tenant: dict[str, list[Any]] = {}
        for tenant in loaded:
            trees[tenant.slug] = _seed_tree(spec, tenant)
            users_by_tenant[tenant.slug] = _seed_people(spec, tenant, trees[tenant.slug])
            _seed_widgets(spec, tenant, trees[tenant.slug], users_by_tenant[tenant.slug][0])
            _seed_policies(spec, tenant, trees[tenant.slug])
            event_pks[tenant.slug] = _seed_events(spec, tenant, trees[tenant.slug])
            _seed_tokens(spec, tenant, users_by_tenant[tenant.slug])
        _seed_deliveries(spec, loaded, event_pks)
        background = _seed_background(spec)
        _seed_workflow_runs(spec, loaded + background)
        _seed_platform_runs(spec)
        _seed_comms(spec, loaded, trees)
        create_tenant(
            name=f"Perf stamp {spec_hash(spec)}", slug=stamp_slug(spec), actor=system_actor()
        )
        _seed_audit(spec, loaded, trees)
    analyze_world()


# --- The census (verification, not prose) ------------------------------------


def census(spec: ScaleSpec) -> list[str]:
    """One ORM count per fixture-contract axis, checked against the spec.

    Returns the printed lines; raises RuntimeError listing every mismatch, so
    the census is an assertion about the world, never a description of it.
    """
    from django.db.models import Count, Max

    from apps.accounts.models import ApiToken, User
    from apps.comms.models import ChannelPreference, Message, Recipient
    from apps.core.audit import AuditEntry
    from apps.core.models import Membership, Organization, Tenant
    from apps.events.models import Delivery, Event, Outbox, WebhookEndpoint
    from apps.example.models import Widget, WidgetPolicy
    from apps.workflows.models import WorkflowRun

    require_perf_database()
    lines: list[str] = []
    problems: list[str] = []

    def check(label: str, got: Any, want: Any) -> None:
        ok = got == want
        lines.append(f"  {label}: {got} (expected {want}) {'OK' if ok else 'MISMATCH'}")
        if not ok:
            problems.append(f"{label}: got {got}, expected {want}")

    tenant_total = Tenant.objects.count()
    stamps = list(
        Tenant.objects.filter(slug__startswith=STAMP_PREFIX).values_list("slug", flat=True)
    )
    lines.append(f"spec hash: {spec_hash(spec)}")
    check("tenants (product + stamp)", tenant_total, spec.tenants + 1)
    check("stamp tenant", stamps, [stamp_slug(spec)])

    loaded = list(Tenant.objects.filter(slug__in=LOADED_SLUGS).order_by("slug"))
    check("loaded tenants", len(loaded), spec.loaded_tenants)
    suppress_every = max(100 // max(spec.suppressed_percent, 1), 1)
    for tenant in loaded:
        prefix = f"[{tenant.slug}]"
        orgs = Organization.objects.for_tenant(tenant)
        check(f"{prefix} orgs", orgs.count(), spec.orgs_per_loaded_tenant)
        check(
            f"{prefix} max path depth (root=0; segments = depth+1)",
            orgs.aggregate(m=Max("depth"))["m"],
            spec.spine_depth - 1,
        )
        breadth = (
            orgs.exclude(parent__isnull=True)
            .values("parent")
            .annotate(n=Count("id"))
            .aggregate(m=Max("n"))["m"]
        )
        check(f"{prefix} max direct children", breadth, spec.wide_children)
        check(
            f"{prefix} memberships (reps + the many-hats person)",
            Membership.objects.filter(tenant=tenant).count(),
            spec.memberships + spec.many_hats,
        )
        many = User.objects.get(email=hat_emails(tenant.slug)["many"])
        check(
            f"{prefix} many-hats person's memberships in this tenant",
            Membership.objects.filter(tenant=tenant, user=many).count(),
            spec.many_hats,
        )
        spine_slugs = [tenant.slug] + [f"spine-{n:02d}" for n in range(1, spec.spine_depth)]
        check(
            f"{prefix} many-hats person's hats on the spine chain (one ancestor line)",
            Membership.objects.filter(
                tenant=tenant, user=many, organization__slug__in=spine_slugs
            ).count(),
            min(spec.many_hats, spec.spine_depth),
        )
        check(
            f"{prefix} many-hats person's default hats (the constraint allows one)",
            Membership.objects.filter(tenant=tenant, user=many, is_default=True).count(),
            1,
        )
        policies = WidgetPolicy.objects.for_tenant(tenant)
        check(
            f"{prefix} widget policies (one per spine ancestor — governing()'s path)",
            policies.count(),
            spec.spine_depth,
        )
        check(
            f"{prefix} policies governing() resolves at the depth ceiling",
            policies.governing(orgs.get(slug=f"spine-{spec.spine_depth - 1:02d}")).count(),
            spec.spine_depth,
        )
        widgets = Widget.objects.for_tenant(tenant)
        check(f"{prefix} widgets", widgets.count(), spec.widgets)
        check(
            f"{prefix} widgets in heaviest org ({HEAVY_ORG_SLUG})",
            widgets.filter(organization__slug=HEAVY_ORG_SLUG).count(),
            spec.widget_heaviest,
        )
        region_hat = Organization.objects.for_tenant(tenant).get(slug=REGION_HAT_SLUG)
        check(
            f"{prefix} widgets visible_to(region hat {REGION_HAT_SLUG})",
            Widget.objects.for_tenant(tenant).visible_to(region_hat).count(),
            expected_region_widgets(spec),
        )
        events = Event.objects.for_tenant(tenant)
        check(f"{prefix} events", events.count(), spec.events)
        expected_bearing = sum(1 for i in range(spec.events) if i % 100 < spec.org_bearing_percent)
        check(
            f"{prefix} events org-bearing",
            events.exclude(organization=None).count(),
            expected_bearing,
        )
        check(
            f"{prefix} events org-less (NULL = tenant-wide)",
            events.filter(organization=None).count(),
            spec.events - expected_bearing,
        )
        sample = events.exclude(organization=None).order_by("occurred_at").first()
        seam_ok = sample is not None and str(sample.organization_id) == str(
            sample.payload.get("organization_id")
        )
        check(f"{prefix} seam: sampled event org == payload organization_id", seam_ok, True)
        check(
            f"{prefix} outbox pending (next_attempt_at set)",
            Outbox.objects.filter(
                event__tenant=tenant,
                status=Outbox.Status.PENDING,
                next_attempt_at__isnull=False,
            ).count(),
            spec.events_pending,
        )
        check(
            f"{prefix} api tokens", ApiToken.objects.filter(tenant=tenant).count(), spec.api_tokens
        )
        for kind, email in hat_emails(tenant.slug).items():
            check(f"{prefix} {kind} hat user", User.objects.filter(email=email).count(), 1)

    check("webhook endpoints (total)", WebhookEndpoint.objects.count(), spec.endpoints)
    check("deliveries (total)", Delivery.objects.count(), spec.deliveries)
    check("audit entries (total)", AuditEntry.objects.count(), spec.audit_entries)
    check(
        "audit entries (platform NULL-tenant)",
        AuditEntry.objects.for_platform().count(),
        spec.audit_platform,
    )
    check(
        "workflow runs (tenant-owned total)",
        WorkflowRun.objects.exclude(tenant=None).count(),
        spec.workflow_runs,
    )
    # The status bucket is derived per tenant, so every tenant holds the
    # intended mix and the census asserts the mix rather than the total.
    # Recomputed from the same arithmetic the seeder used.
    tenant_count = spec.tenants
    buckets = [
        workflow_run_status(spec, index, tenant_count) for index in range(spec.workflow_runs)
    ]
    check(
        "workflow runs completed / failed / running (tenant-owned)",
        [
            sum(1 for bucket in buckets if bucket < 3),
            sum(1 for bucket in buckets if bucket == 3),
            sum(1 for bucket in buckets if bucket == 4),
        ],
        [
            WorkflowRun.objects.exclude(tenant=None).filter(status="completed").count(),
            WorkflowRun.objects.exclude(tenant=None).filter(status="failed").count(),
            WorkflowRun.objects.exclude(tenant=None).filter(status="running").count(),
        ],
    )
    check(
        "tenants holding at least one RUNNING run (was 5 of 25 — FINDING D)",
        WorkflowRun.objects.filter(status="running")
        .exclude(tenant=None)
        .values("tenant")
        .distinct()
        .count(),
        spec.tenants,
    )
    # The platform (NULL-tenant) population, which had no axis of its own.
    check(
        "workflow runs (platform NULL-tenant)",
        WorkflowRun.objects.for_platform().count(),
        spec.workflow_runs_platform,
    )
    check(
        "workflow runs (platform, running — the slice a sweep reads)",
        WorkflowRun.objects.for_platform().filter(status="running").count(),
        len(range(4, spec.workflow_runs_platform, 5)),
    )
    check("comms recipients (total)", Recipient.objects.count(), spec.recipients)
    check("comms messages (total)", Message.objects.count(), spec.messages)
    expected_suppressed = sum(
        len(range(0, spec.messages // spec.loaded_tenants, suppress_every))
        for _ in range(spec.loaded_tenants)
    )
    check(
        "comms messages suppressed",
        Message.objects.filter(status="suppressed").count(),
        expected_suppressed,
    )
    expected_pref = sum(
        len(range(0, spec.recipients // spec.loaded_tenants, suppress_every))
        for _ in range(spec.loaded_tenants)
    )
    check(
        "comms suppressed email preferences",
        ChannelPreference.objects.filter(suppressed_at__isnull=False).count(),
        expected_pref,
    )
    background = Tenant.objects.filter(slug__startswith="perf-bg-")
    check("background tenants", background.count(), spec.background_tenants)
    sample_bg = background.order_by("slug").first()
    if sample_bg is not None:
        check(
            "[background sample] widgets",
            Widget.objects.for_tenant(sample_bg).count(),
            spec.background_widgets,
        )
        check(
            "[background sample] memberships",
            Membership.objects.filter(tenant=sample_bg).count(),
            spec.background_members,
        )
    lines.append(f"  sockets: declared {spec.sockets} (runtime axis — opened at serve; not rows)")
    if problems:
        raise RuntimeError("census mismatches:\n" + "\n".join(problems))
    return lines


# --- The CLI `scripts/perf.sh` drives ----------------------------------------


def main(argv: list[str]) -> int:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
    import django

    django.setup()

    args = list(argv)
    spec = DEFAULT_SPEC
    if "--double" in args:
        at = args.index("--double")
        try:
            axis = args[at + 1]
        except IndexError:
            sys.stderr.write("--double needs an axis name\n")
            return 2
        del args[at : at + 2]
        try:
            spec = spec.doubled(axis)
        except ValueError as refusal:
            sys.stderr.write(f"{refusal}\n")
            return 2
    command = args[0] if args else "status"
    if command == "status":
        require_perf_database()
        fresh, detail = stamp_state(spec)
        sys.stdout.write(detail + "\n")
        return 0 if fresh else 3
    if command == "seed":
        seed_scale(spec)
        for line in census(spec):
            sys.stdout.write(line + "\n")
        return 0
    if command == "census":
        for line in census(spec):
            sys.stdout.write(line + "\n")
        return 0
    sys.stderr.write(f"unknown command {command!r}: one of status, seed, census\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
