"""The hot-path probes — how rule 35 reaches each registry entry's real read.

Each probe **imports and runs the real dotted path** the registry names, so a
planted change to the production selector is a changed probe — that is what
makes the canaries honest ("through the real scope"). A probe that copied the
query would measure the copy; M1-2 closed that seam for the counts ("read them
from the module, not retype them") and this module holds it for the plans.

Run only by `quality/hotpath_probe.py`, in a subprocess the gate starts, against
the gate's own `_hp` probe database (schema migrated, the fixed world below,
`ANALYZE` run — the statistics assumption rule 35 declares, following the
seeder's precedent: `perf/seed.py::seed_scale` → `analyze_world`, F1d). Nothing
in the default suite or in `perf/` imports this module.

Probes are read-shaped; the two that reach a write path (`authenticate_token`'s
touch) run inside a transaction the runner rolls back, so the cached probe
database never drifts.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

# A fixed world, keyed on constants, so the probe database is idempotent: the
# same rows every run, created once, reused forever (`ensure_world`).
TENANT_SLUG = "gate-hot-paths"
TENANT_NAME = "Gate hot paths (probe world)"
ROOT_SLUG = "gate-root"
BRANCH_SLUG = "gate-branch"
LEAF_SLUG = "gate-leaf"
USER_EMAIL = "gate-hotpaths@example.invalid"
BRANCH_USER_EMAIL = "gate-hotpaths-branch@example.invalid"
RAW_TOKEN = "gate-hotpaths-probe-token"  # noqa: S105 # probe credential, probe DB only

# --- why the world is no longer three organizations (P3 F2, P-1) --------------
#
# `lookup_columns` (rule 35) asserts that a named column's predicate is an
# `Index Cond`/`Recheck Cond` rather than a `Filter`. That assertion is only
# meaningful in a world where the narrowing plan is the plan the PLANNER would
# choose: with three organizations in the tenant, reading all three and
# filtering is genuinely cheaper than a bitmap over `path`, so the subtree read
# rode the `for_tenant` leg's Index Cond and evaluated the path predicate as a
# Filter — and rule 35 called that index-served, because *an* Index Cond
# existed. That is P-1, and a probe world too small for the pinned shape cannot
# assert plan shape at all; it can only assert the loader.
#
# So the tenant gets FILLER_ORGS siblings of the probed branch.
#
# WHAT THE MARGIN ACTUALLY IS, MEASURED (corrected by (d), from ).
# This paragraph used to justify the size as a SHARE: 2 of 403 rows is 0.5%, an
# order of magnitude below `perf/measure_realtime.py::PREFIX_INDEX_SHARE_CEILING`
# (5%), the share below which the harness asserts a path-index narrowing. That
# reasoning does not survive its own sweep. The per-filler runs, each against an
# isolated database, go GREEN from 20 fillers on — and at 20 the probed subtree
# is 2 of 23 rows, **8.7%, comfortably ABOVE the 5% ceiling**. If the share were
# the term, 20 would be red.
#
# The flip follows ABSOLUTE ROWS at this scale, not the ratio: below about a
# dozen rows a sequential-ish walk of the whole tenant is cheaper than building
# a bitmap however small the answer is, and once the table is big enough for the
# bitmap to pay, the plan stops moving. Measured: RED at 3 fillers, green at
# 20 / 50 / 100 / 200 / 400 / 800, and from 20 on it is the same BitmapOr whose
# Index Conds name `path`. 400 is chosen for the margin above the red edge, not
# for the ratio underneath it.
#
# The SHARE ceiling is still the harness's instrument and still right there: it
# governs planner choice at VOLUME, where selectivity is what moves a decision
# (M4 FINDING 1 lost the prefix index at 16% of a 201-org hat and kept it at
# 8.8%; F1e's re-measure puts that flip between 16% and 27.6%). Two different
# regimes, two different terms — quoting the volume regime's number to justify
# a 403-row world was the error.
#
# `quality/hotpath_probe.py` now emits the row count and the predicate's share
# for EVERY declared lookup column, so this argument is a measurement on every
# run rather than a paragraph: the four declarations that sit on 0–2-row tables
# report themselves as `lookup_columns_unproven`, ratcheted in
# `quality/budgets.yaml`.
#
# WIDGETS exists for the same reason one level up: `probe_list_widgets` renders
# every row it fetched through `WidgetOut` (see its docstring), and a page of
# zero rows renders nothing — a stripped `select_related` would cost the probe
# nothing at all, which is exactly what 's done-line item 2(c)
# found.
# --- and why there is now a SECOND TENANT (CORE-11, ADR core-11) -------------
#
# `list_widgets`' page statement pins `lookup_columns: {example_widget:
# [tenant_id]}` — the assertion that `tenant_id` is what REACHES the rows, an
# `Index Cond` on `widget_recency` rather than a `Filter` over somebody else's.
# its falsifiability doctrine says an assertion whose world cannot falsify it
# is `lookup_columns_unproven`, not green, and this world could not falsify it
# twice over:
#
# 1. THE TABLE WAS TOO SMALL. Three rows is below
# `hotpath_probe.LOOKUP_PROOF_MIN_ROWS` (100), the size at which the
# planner has a choice to get wrong; under `enable_seqscan = off` the
# assertion would have held by construction and measured the setting.
# 2. THERE WAS NOTHING TO BE BLIND TO. Every widget belonged to the probed
# tenant, so "the predicate narrows to this tenant" narrowed to the whole
# table. The pre-CORE-11 defect was a page walking backwards down a
# TENANT-BLIND `created_at` index through OTHER TENANTS' rows (F1a: 102,300
# of them per page) — a world with one tenant in it cannot show that plan
# being avoided, because that plan and the right one fetch the same rows.
#
# So the world gains a foreign tenant whose widgets are created LAST and are
# therefore the MOST RECENT — exactly the rows the bare index would have walked
# first and discarded. The probed tenant's page is now a minority of the recent
# end of `example_widget`, the planner genuinely had the blind option, and
# `tenant_id` in the `Index Cond` is a measurement rather than a tautology.
#
# The foreign tenant is otherwise inert: no membership the probed user holds, no
# probe reads it. It exists to be skipped.
FILLER_ORGS = 400
# 120 probed + 400 foreign = 520 rows in `example_widget`, past
# LOOKUP_PROOF_MIN_ROWS with margin, and the probed tenant is 23% of the table
# while owning none of the newest 400 rows.
WIDGETS = 120
FILLER_SLUG_PREFIX = "gate-filler-"
WIDGET_NAME_PREFIX = "Gate probe widget "
FOREIGN_TENANT_SLUG = "gate-hot-paths-foreign"
FOREIGN_TENANT_NAME = "Gate hot paths (foreign tenant, CORE-11)"
FOREIGN_USER_EMAIL = "gate-hotpaths-foreign@example.invalid"
FOREIGN_ROOT_SLUG = "gate-foreign-root"
FOREIGN_WIDGETS = 400
FOREIGN_WIDGET_NAME_PREFIX = "Foreign tenant widget "


@dataclass
class World:
    """The rows every probe shares. Filled by `ensure_world`."""

    tenant: object = None
    root: object = None
    branch: object = None
    leaf: object = None
    user: object = None
    branch_user: object = None


@dataclass
class ProbeResult:
    """What one probe did: extra findings beyond the runner's own clauses."""

    findings: list[str] = field(default_factory=list)


def ensure_world(world: World) -> None:
    """Create (or find) the fixed probe world. Idempotent by construction.

    Bare ORM on purpose: this is gate infrastructure seeding its own probe
    database, the same trust class as a test fixture — rule 8/10/13 scopes are
    `apps/` and `config/`, and nothing here is a door.
    """
    from django.contrib.auth import get_user_model

    from apps.accounts.models import ApiToken
    from apps.accounts.services import hash_token
    from apps.core.models import Membership, Organization, Tenant, encode_path_segment
    from apps.example.models import Widget

    tenant, _ = Tenant.objects.get_or_create(slug=TENANT_SLUG, defaults={"name": TENANT_NAME})
    root, _ = Organization.objects.get_or_create(
        tenant=tenant, path="0000", defaults={"slug": ROOT_SLUG, "name": "Root", "parent": None}
    )
    branch, _ = Organization.objects.get_or_create(
        tenant=tenant,
        path="0000.0000",
        defaults={"slug": BRANCH_SLUG, "name": "Branch", "parent": root},
    )
    leaf, _ = Organization.objects.get_or_create(
        tenant=tenant,
        path="0000.0000.0000",
        defaults={"slug": LEAF_SLUG, "name": "Leaf", "parent": branch},
    )
    User = get_user_model()
    user, _ = User.objects.get_or_create(email=USER_EMAIL)
    branch_user, _ = User.objects.get_or_create(email=BRANCH_USER_EMAIL)
    Membership.objects.get_or_create(
        user=user, tenant=tenant, organization=root, defaults={"is_default": True}
    )
    Membership.objects.get_or_create(
        user=branch_user, tenant=tenant, organization=branch, defaults={"is_default": True}
    )
    ApiToken.objects.get_or_create(
        key_hash=hash_token(RAW_TOKEN),
        defaults={"user": user, "tenant": tenant, "name": "gate probe token"},
    )
    # The siblings that make the probed hat a small share of its tenant, so the
    # narrowing rule 35 pins is the plan the planner would pick anyway. Counted
    # first and bulk-created once: the probe database is cached, so the ordinary
    # run pays one COUNT for the whole block.
    existing = Organization.objects.filter(
        tenant=tenant, slug__startswith=FILLER_SLUG_PREFIX
    ).count()
    if existing < FILLER_ORGS:
        Organization.objects.bulk_create(
            [
                Organization(
                    tenant=tenant,
                    parent=root,
                    slug=f"{FILLER_SLUG_PREFIX}{index:04d}",
                    name=f"Filler {index}",
                    # Index 0 under the root is `branch`; the fillers take the
                    # rest, so none of them is inside the probed subtree.
                    path=f"{root.path}.{encode_path_segment(index + 1)}",
                    depth=1,
                )
                for index in range(existing, FILLER_ORGS)
            ],
            ignore_conflicts=True,
        )
    # Rows for the rendering probe to render. Owned by `user` and living in
    # `branch`, so `list_widgets(tenant, org=branch)` returns all of them.
    # Counted first and bulk-created once, like the organizations above.
    #
    # THESE ARE CREATED BEFORE THE FOREIGN TENANT'S, and the order is the point:
    # `created_at` is `auto_now_add`, so the foreign rows below end up the most
    # RECENT in the table — the ones a tenant-blind `created_at` index would
    # have walked first and thrown away (ADR core-11).
    probed_widgets = Widget.objects.filter(
        tenant=tenant, name__startswith=WIDGET_NAME_PREFIX
    ).count()
    if probed_widgets < WIDGETS:
        Widget.objects.bulk_create(
            [
                Widget(
                    tenant=tenant,
                    organization=branch,
                    owner=user,
                    name=f"{WIDGET_NAME_PREFIX}{index}",
                )
                for index in range(probed_widgets, WIDGETS)
            ],
            ignore_conflicts=True,
        )
    # --- the foreign tenant (CORE-11) ----------------------------------------
    #
    # What the probed page must NOT examine. Nothing reads these rows; they are
    # the thing `tenant_id` has to narrow AWAY, and without them the narrowing
    # is a tautology (see the header above).
    foreign_tenant, _ = Tenant.objects.get_or_create(
        slug=FOREIGN_TENANT_SLUG, defaults={"name": FOREIGN_TENANT_NAME}
    )
    foreign_root, _ = Organization.objects.get_or_create(
        tenant=foreign_tenant,
        path="0000",
        defaults={"slug": FOREIGN_ROOT_SLUG, "name": "Foreign root", "parent": None},
    )
    foreign_user, _ = User.objects.get_or_create(email=FOREIGN_USER_EMAIL)
    Membership.objects.get_or_create(
        user=foreign_user,
        tenant=foreign_tenant,
        organization=foreign_root,
        defaults={"is_default": True},
    )
    foreign_widgets = Widget.objects.filter(tenant=foreign_tenant).count()
    if foreign_widgets < FOREIGN_WIDGETS:
        Widget.objects.bulk_create(
            [
                Widget(
                    tenant=foreign_tenant,
                    organization=foreign_root,
                    owner=foreign_user,
                    name=f"{FOREIGN_WIDGET_NAME_PREFIX}{index}",
                )
                for index in range(foreign_widgets, FOREIGN_WIDGETS)
            ],
            ignore_conflicts=True,
        )
    world.tenant, world.root, world.branch, world.leaf = tenant, root, branch, leaf
    world.user, world.branch_user = user, branch_user


# --- the probes, one per probed registry entry --------------------------------
# Signature: probe(world) -> ProbeResult. The runner captures every statement
# the probe issues, EXPLAINs each SELECT under `enable_seqscan = off`, applies
# the entry's clauses from rules.yaml, and checks the statement count against
# quality/budgets.yaml `hot_path_query_counts`.


def probe_list_widgets(world: World) -> ProbeResult:
    """The paginator's pair — the page and the COUNT — **and the render**.

    M1 rows 3–8, as re-cut by F1d: the page and the count are different
    statements and plan differently; both are captured here. No index is
    demanded (M1-A / F1a /); the clause is `example_widget` never
    sequentially scanned, which held at every hat in every measured world.

    **Every row is dereferenced through the door's own `Out` schema**, and that
    is the whole point of this probe rather than a flourish. Until P3 F2 it
    fetched the page and counted it and never touched a row, so a stripped
    `select_related("owner", "organization")` — the canonical N+1, and the one
    thing `list_widgets`' docstring says the pin exists to catch — cost the
    probe zero statements and rule 35's count pin stayed green
    (done-line item 2(c)). `WidgetOut.from_orm` is the same call
    `apps/example/api.py` makes on every row it returns, and `WidgetOut` walks
    `owner` and `organization` through model properties, so the statements
    counted here are the door's.

    **A probe that does not render is the same hole again.** A product
    registering its own hot path owes its probe the dereference: fetching a
    queryset proves the query, and only rendering proves the page.
    """
    from apps.example.schemas import WidgetOut
    from apps.example.selectors import list_widgets

    qs = list_widgets(tenant=world.tenant, org=world.branch)
    rows = list(qs[:50])
    for widget in rows:
        WidgetOut.from_orm(widget)
    qs.count()
    result = ProbeResult()
    if not rows:
        result.findings.append(
            "list_widgets probe: the page was empty, so nothing was rendered and a "
            "stripped select_related would cost this probe nothing — the probe world "
            "is wrong, not the selector (quality/hotpaths.py::WIDGETS)"
        )
    return result


def probe_resolve_org(world: World) -> ProbeResult:
    """The revalidation path (M1 rows 11–13; M3 measures 5–9), plus the oracle pin.

    The named hat costs 2 statements; the probe also runs the *refused* shape
    (a branch hat naming the root — upward, refused) and holds the two counts
    equal: a cheaper refusal is a timing oracle (M3's own criterion).
    """
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from apps.core.middleware import resolve_org

    result = ProbeResult()
    resolved = resolve_org(user=world.user, tenant=world.tenant, requested_slug=BRANCH_SLUG)
    if resolved is None:
        result.findings.append(
            "resolve_org probe: the root hat naming a descendant resolved None — "
            "the probe world is wrong, not the middleware"
        )
    with CaptureQueriesContext(connection) as refused:
        refused_org = resolve_org(
            user=world.branch_user, tenant=world.tenant, requested_slug=ROOT_SLUG
        )
    if refused_org is not None:
        result.findings.append("resolve_org probe: an upward hat was granted — refusal broken")
    if len(refused.captured_queries) != 2:
        result.findings.append(
            f"resolve_org: the REFUSED hat cost {len(refused.captured_queries)} statements "
            "against the granted hat's 2 — refusing must not be cheaper or dearer than "
            "allowing (a timing oracle; M3 measures 7–9)"
        )
    return result


def probe_resolve_tenant(world: World) -> ProbeResult:
    """The default-membership read — 1 statement (M3 measure 5)."""
    from apps.core.middleware import resolve_tenant

    resolve_tenant(user=world.user, requested_slug=None)
    return ProbeResult()


def probe_governing(world: World) -> ProbeResult:
    """Upward config resolution — 1 statement, the ancestor chain decomposed in
    Python (M1 rows 9–10). No plan clause: FINDING M1-C, cited in
    `does_not_cover`."""
    from apps.example.models import WidgetPolicy

    list(WidgetPolicy.objects.for_tenant(world.tenant).governing(world.leaf))
    return ProbeResult()


def probe_audit_for_tenant(world: World) -> ProbeResult:
    """Page one of the tenant's own trail (M2 measures 10–11, red before F1b)."""
    from apps.core.audit import AuditEntry

    list(AuditEntry.objects.for_tenant(world.tenant)[:50])
    return ProbeResult()


def probe_audit_for_platform(world: World) -> ProbeResult:
    """Page one of the platform population (M2 measure 12, fixed by F1b)."""
    from apps.core.audit import AuditEntry

    list(AuditEntry.objects.for_platform()[:50])
    return ProbeResult()


def probe_list_stranded_outbox(world: World) -> ProbeResult:
    """Rule 30's reader, bounded by F1c — 1 statement with or without the batch."""
    from django.utils import timezone

    from apps.events.selectors import list_stranded_outbox

    list(list_stranded_outbox(before=timezone.now(), limit=500, already_seen=0))
    return ProbeResult()


def probe_endpoints_for(world: World) -> ProbeResult:
    """The fan-out's subscriber read — 1 statement (M2 measure 4)."""
    from apps.events.selectors import endpoints_for

    endpoints_for(tenant=world.tenant, name="gate.probe.ran")
    return ProbeResult()


def probe_authenticate_token(world: World) -> ProbeResult:
    """The machine door's cold path — the key_hash SELECT plus the touch UPDATE.

    Runs inside the runner's rolled-back transaction, so the probe database
    stays cold and every run measures the 2-statement cold path (M3 measures
    1–4; N6's throttle is the warm half, held by the harness).
    """
    from apps.accounts.services import authenticate_token

    result = ProbeResult()
    authenticated = authenticate_token(plaintext=RAW_TOKEN)
    if authenticated is None:
        result.findings.append(
            "authenticate_token probe: the seeded probe token did not authenticate — "
            "the probe world is wrong, not the service"
        )
    return result


def probe_list_subtree_org_ids(world: World) -> ProbeResult:
    """The socket door's connect read — 1 statement at any hat (M4 §2)."""
    from apps.realtime.selectors import list_subtree_org_ids

    list_subtree_org_ids(tenant=world.tenant, org=world.branch)
    return ProbeResult()


def probe_push_event(world: World) -> ProbeResult:
    """A push reads nothing — the zero-query pin (M4 §8).

    This is the one number whose regression would turn every emit into an N+1
    across every connected socket, so it is executed, not recorded. The runner
    asserts the captured statement count against the recorded 0.
    """
    from asgiref.sync import async_to_sync

    from apps.realtime.bridge import push_event
    from apps.realtime.schemas import EventMessage

    message = EventMessage(
        name="gate.probe.ran",
        v=1,
        payload={},
        occurred_at=datetime(2026, 8, 22, tzinfo=UTC),
        organization_id=None,
    )
    async_to_sync(push_event)(tenant_id=getattr(world.tenant, "pk", ""), event=message)
    return ProbeResult()


# : dotted registry path -> probe. The registry (quality/rules.yaml, rule 35)
# : names which entries are probed; an entry marked `pin: probe` with no probe
# : here — or a probe here for no registry entry — is a gate finding, so the two
# : cannot drift apart silently.
PROBES: dict[str, Callable[[World], ProbeResult]] = {
    "apps.example.selectors.list_widgets": probe_list_widgets,
    "apps.core.middleware.resolve_org": probe_resolve_org,
    "apps.core.middleware.resolve_tenant": probe_resolve_tenant,
    "apps.core.models.ScopedQuerySet.governing": probe_governing,
    "apps.core.audit.AuditEntry.objects.for_tenant": probe_audit_for_tenant,
    "apps.core.audit.AuditEntry.objects.for_platform": probe_audit_for_platform,
    "apps.events.selectors.list_stranded_outbox": probe_list_stranded_outbox,
    "apps.events.selectors.endpoints_for": probe_endpoints_for,
    "apps.accounts.services.authenticate_token": probe_authenticate_token,
    "apps.realtime.selectors.list_subtree_org_ids": probe_list_subtree_org_ids,
    "apps.realtime.bridge.push_event": probe_push_event,
}


# --- names are not strings, in Python too (the second strike) ------------
#
# The CLASS: an identifier cannot be a parameter, so it is the one thing a
# caller has to interpolate — and every place that does it by hand is one quote
# away from composing statements. SEC-1 closed the class in `scripts/db.sh`
# (`db_valid_name` + psql's `:"x"` variables, shared by `db_sweep.sh`); this is
# its Python twin, and `scripts/db.sh` names it back. The rule is deliberately
# IDENTICAL in both languages — `[A-Za-z0-9_]`, at most 63 bytes — so there is
# one shape to remember and one place per language to change it.
#
# WHY IT MATTERS HERE, given the name is operator input and not wire-reachable.
# `DATABASE_NAME` reaching `ensure_database` used to be pasted into
# `CREATE DATABASE "{name}"`, and a name carrying a quote composed its own
# statement: `djb_x"; DROP DATABASE "djb_victim` builds
# `CREATE DATABASE "djb_x"; DROP DATABASE "djb_victim_hp"`. What stopped that
# executing was psycopg's implicit transaction, in which `CREATE DATABASE` will
# not run — the same accident that protected `db_sweep.sh`, and the same
# accident SEC-1 refused to rely on. A tool whose refusals are described in its
# own header as load-bearing refuses by CONSTRUCTION.
#
# TWO LAYERS, each sufficient alone: this gate before any SQL is built, and
# `psycopg.sql.Identifier` at the statement, which quotes whatever it is given.
IDENTIFIER_MAX_BYTES = 63
_IDENTIFIER = re.compile(r"\A[A-Za-z0-9_]+\Z")


class UnsafeIdentifier(ValueError):
    """A name that may not be interpolated into SQL. Raised, never sanitised.

    Sanitising is how two different names become one database: the point of
    refusing is that the caller finds out.
    """


def guarded_identifier(name: str, *, what: str = "database name") -> str:
    """`name`, or `UnsafeIdentifier`. The one door for a Python-side identifier.

    The twin of `db_valid_name` in `scripts/db.sh`, to the byte: every name this
    repository derives is already `[A-Za-z0-9_]` and inside Postgres's budget
    (`db_name`, Django's `test_` prefix, xdist's `_gwN`, the `_hp` suffix here),
    so the gate costs a legitimate caller nothing and turns an injection attempt
    into a sentence instead of a puzzling Postgres error.
    """
    if not isinstance(name, str) or not name:
        raise UnsafeIdentifier(f"an empty {what} is not a name")
    encoded = name.encode("utf-8", "surrogatepass")
    if len(encoded) > IDENTIFIER_MAX_BYTES:
        raise UnsafeIdentifier(
            f"the {what} {name!r} is {len(encoded)} bytes; Postgres allows "
            f"{IDENTIFIER_MAX_BYTES} and TRUNCATES rather than refusing, so two names that "
            "differ only past the limit would become one database"
        )
    if not _IDENTIFIER.match(name):
        raise UnsafeIdentifier(
            f"refusing the {what} {name!r} — a database name here is [A-Za-z0-9_], at most "
            f"{IDENTIFIER_MAX_BYTES} bytes, which is the shape this repository derives "
            "(scripts/db.sh). Nothing legitimate is outside it, and a name that is not one "
            "is a name that can compose SQL"
        )
    return name


def probe_database_name(base: str) -> str:
    """`<base>_hp`, kept inside Postgres's 63-byte identifier budget.

    `scripts/db.sh` caps the derived name at 51 bytes, so the ordinary result
    is ≤ 54 and never truncates. A base that IS a legal identifier but whose
    `_hp` form would overflow (52–63 bytes) is hashed down instead of silently
    truncated — two long names that differ only past byte 63 must not become
    one database.

    The base goes through `guarded_identifier` first: until then this
    validated LENGTH only, so a name carrying a quote passed straight through
    into `CREATE DATABASE "{name}"`. A base longer than the budget is now
    REFUSED rather than hashed, which is not a narrowing of anything real: such
    a base could not be a Postgres identifier in the first place, and every name
    reaching here comes from `scripts/db.sh`, Django's `test_` prefix or xdist.
    The answer is guarded too — it is derived and so always passes, and checking
    it is what makes this the one door rather than the first of two.
    """
    guarded_identifier(base)
    name = f"{base}_hp"
    if len(name) <= IDENTIFIER_MAX_BYTES:
        return guarded_identifier(name)
    digest = hashlib.sha256(base.encode()).hexdigest()[:8]
    return guarded_identifier(f"{base[:50]}_{digest}_hp")
