"""M1 — the hierarchy at seeded scale, measured with machine-invariant instruments.

Rung M1 of cycle P3 ("fast at scale").
Zero production edits: this module and the retired `perf-hierarchy-measurement.md`
are the whole rung. What it measures, and with which instrument (ADR perf-1 —
query counts, EXPLAIN plan shape, flat-under-doubling; **never** wall-clock,
which `perf/measure.refuse_wall_clock_assertions` refuses structurally):

* **prefix scans** over the 1,200-org tree (`path__startswith`) — the read the
  whole materialized-path design exists to make cheap;
* **`visible_to`** at five hat positions — root, region, the heavy leaf, the
  **200-wide** node and the **depth-12 spine** tip — query count flat across
  hat position, and the resolved row share equal to the spec's own arithmetic
  (correctness rides along with cost);
* **`governing()`** — upward config resolution off the deepest legal node: one
  query, no tree walk, an ancestor list decomposed in Python;
* **`resolve_org`** — the middleware seam all four doors call, with and without
  an `X-Org` slug;
* **the 200-wide node's children listing**, paginated.

## The depth axis is dead, and this module is where that is recorded

The cycle plan asked for `governing()` "flat under depth-doubling to 24". H1
found that line unbuildable and the PM re-cut it: **`PATH_MAX_DEPTH = 12` is
the platform's own ceiling** (`apps/core/models.py:51`), `child_path` refuses a
thirteenth segment, and `perf/seed.py` rightly raises rather than faking a tree
the product could not hold. So the measurement is taken **at** the ceiling — the
seeded depth-12 spine is the deepest tree that can exist — flatness is proven
under **org-doubling** instead, and the ceiling itself is recorded as the
envelope's declared bound. A platform that refuses to go deeper does not need a
flatness proof past its own refusal; it needs the refusal stated in the
envelope, which is what `MAX_LEGAL_DEPTH` below and the measurement doc do.

## How one module proves flatness across two worlds

A doubling comparison needs two numbers from two databases, and a pytest run
sees one. So every query count is **declared** here as its S-value in
`DECLARED_QUERY_COUNTS`, and every test compares its measurement against that
declaration through `measure.flat_under_doubling`. In the base world that pins
the S number; in the `--double orgs` (or `--double memberships`) world the very
same comparison **is** the doubling proof, because the declared value is the S
count and the measured one is the x2 count. The world names itself — the stamp
tenant's slug carries the ScaleSpec hash and `perf/conftest.py`'s `spec` fixture
hands it over — so nothing has to be passed in and no environment variable has
to agree with anything.

Row counts are **not** declared here: they are recomputed from the world's own
spec through `perf/seed.py`'s arithmetic helpers, because a doubled org tree
legitimately holds more rows. A row count that moves is correct; a query count
that moves is the finding.

Every plan and every observation is appended to a report file under the system
temp directory (`REPORT_PATH`), from which the measurement doc is written. It
is deliberately outside the repository: a reader rung writes no files into the
tree beyond its two.
"""

from __future__ import annotations

import dataclasses
import tempfile
from pathlib import Path
from typing import Any

import pytest

from perf import measure
from perf.seed import (
    DEFAULT_SPEC,
    HEAVY_ORG_SLUG,
    REGION_HAT_SLUG,
    ScaleSpec,
    expected_region_widgets,
    hat_emails,
    widget_allocation,
)

pytestmark = [pytest.mark.django_db]


#: The platform's own ceiling, read off the module that owns it. The envelope's
#: declared bound for tree depth: `child_path` refuses a deeper path, so no
#: measurement past this point describes a tree the product can hold.
def _max_legal_depth() -> int:
    from apps.core.models import PATH_MAX_DEPTH

    return int(PATH_MAX_DEPTH)


#: Query counts at S, per measure. A count equal to its declaration in the
#: doubled world is the flatness proof (see the module docstring).
DECLARED_QUERY_COUNTS: dict[str, int] = {
    "prefix_scan_region_subtree": 1,
    "prefix_scan_root_subtree": 1,
    "visible_to_page_root": 1,
    "visible_to_page_region": 1,
    "visible_to_page_leaf": 1,
    "visible_to_page_wide": 1,
    "visible_to_page_spine": 1,
    "visible_to_count_root": 1,
    "visible_to_count_region": 1,
    "visible_to_count_leaf": 1,
    "visible_to_count_wide": 1,
    "visible_to_count_spine": 1,
    "governing_at_ceiling": 1,
    "governing_ancestor_lookup": 1,
    "resolve_org_default_hat": 1,
    "resolve_org_named_slug": 2,
    "resolve_org_refused_slug": 2,
    "wide_children_page": 1,
}

#: Per measure: the index whose presence in the plan is the shape claim, whether
#: the rung ASSERTS it, and — where it does not — the reason, measured rather
#: than assumed. A recorded-only verdict is not a shrug: it is a plan shape this
#: rung found and E1 must not pin, with the finding named.
PLAN_EXPECTATIONS: dict[str, tuple[str, bool, str]] = {
    "prefix_scan_region_subtree": (
        # F1e (the retired `perf-realtime-measurement.md` §5) added
        # `organization_tenant_prefix` — `(tenant_id, path varchar_pattern_ops)`
        # — and this read, which is `for_tenant(t).filter(path__startswith=...)`,
        # is exactly the shape it was built for. The plan improved as well as
        # changed: it was a bitmap over the tenant-less prefix index with a
        # recheck, and it is now a single index scan whose `Index Cond` carries
        # both the tenant and the prefix range, so the scan never touches
        # another tenant's entries. The assertion follows the plan the platform
        # now has; the old index is still declared and still asserted below,
        # where `visible_to` reaches this table through a JOIN carrying no
        # tenant predicate on the organization side.
        "organization_tenant_prefix",
        True,
        "",
    ),
    # --- the paginated page: `LIMIT 50`, the statement the door serves --------
    # RE-CUT BY F1d (REMIT 5) against F1a's finding. M1 read these verdicts off
    # the UNSLICED selector; every door reads a page. Under `LIMIT` the planner
    # can walk the recency index and stop as soon as it has 50 rows, evaluating
    # the path predicate per row through a memoized pkey lookup — no path index
    # in the plan at all. M1 attributed that shape to the root hat alone
    # (FINDING M1-A). It is not a root-hat property: the **region and wide hats
    # do the same thing**, and their ✅ was unearned.
    #
    # WHICH recency index changed under these pins on 2026-08-24 (CORE-11, ADR
    # core-11) and NONE OF THEM MOVED. The walk was
    # `example_widget_created_at_dd8678ab` — tenant-blind, so `tenant_id` was a
    # Filter and the page examined 102,300 other tenants' entries (F1a). It is
    # now `widget_recency` — `(tenant_id, created_at DESC)` — whose `Index Cond`
    # carries the tenant, so the range cannot reach another tenant at all.
    # These pins are about `organization_path_prefix` and are indifferent to
    # that: the page still does not use the path index, before or after. No pin
    # flipped; only the names in these comments needed correcting, which is why
    # they are corrected rather than re-cited. The re-measure and its EXPLAIN
    # are in the retired perf-hierarchy-measurement.md § RE-MEASURE.
    "visible_to_page_root": (
        "organization_path_prefix",
        False,
        "FINDING M1-A, generalised by F1d: under the paginator's LIMIT the "
        "planner reads the recency index backwards (since CORE-11 that is "
        "widget_recency, whose Index Cond carries the tenant) and evaluates "
        "the path predicate per row through a memoized pkey lookup, so the "
        "path index is absent. Cost-correct (the ordering index stops early); "
        "rule 35 must not require the path index on any paginated page.",
    ),
    "visible_to_page_region": (
        "organization_path_prefix",
        False,
        "**RE-PINNED True -> False by F1d (REMIT 5 / F1a).** M1 recorded a ✅ "
        "here, taken on the unsliced queryset. The page the door actually "
        "issues takes the same backward created_at walk as the root hat's: "
        "`organization_path_prefix` is absent from it. Nothing regressed — the "
        "instrument was measuring a query no door issues. The count() below "
        "does ride the path index, which is why the two are pinned separately.",
    ),
    "visible_to_page_leaf": ("organization_path_prefix", True, ""),
    "visible_to_page_wide": (
        "organization_path_prefix",
        False,
        "**RE-PINNED True -> False by F1d (REMIT 5 / F1a).** Same correction as "
        "the region hat: the page is a backward created_at walk with the path "
        "predicate as a per-row filter, and the index M1 ticked is not in it. "
        "Separately, **M1-B's DISPOSITION is falsified**: F1a swept four index "
        "shapes including the composite M1 proposed and none moves the plan — "
        "the lever is `eqjoinsel`, a join-strategy estimate, not an access "
        "path. Platform-wide. A wide hat's plan, page or count must not require "
        "this index.",
    ),
    "visible_to_page_spine": ("organization_path_prefix", True, ""),
    # --- the paginator's OTHER statement: COUNT(*), measured for the first
    # time by F1d (REMIT 5). It plans differently from the page by
    # construction: there is no LIMIT for an ordering index to stop early on,
    # so the path index is reachable here even where the page abandons it.
    # A tick on one is not evidence about the other — that is F1a's finding in
    # one sentence, and it is why these carry their own entries.
    "visible_to_count_root": (
        "organization_path_prefix",
        False,
        "NEW MEASURE (F1d). The root hat's count hash-joins the tenant's whole "
        "widget slice against a **Seq Scan on core_organization** — the root "
        "subtree IS the tenant, so the planner reads every org rather than "
        "probing an index for them. Correct at 1,253 orgs and the only plan "
        "here with a Seq Scan in it. Recorded, not asserted: E1 must pin "
        "neither an index nor the absence of a scan on this shape.",
    ),
    "visible_to_count_region": ("organization_path_prefix", True, ""),
    "visible_to_count_leaf": ("organization_path_prefix", True, ""),
    "visible_to_count_wide": (
        "organization_path_prefix",
        True,
        "NEW MEASURE (F1d). **This is where FINDING M1-B's hash join actually "
        "lives.** The count has no LIMIT, so the planner hash-joins the "
        "tenant's entire widget slice (100,307 rows) against the hat's 401-org "
        "subtree to answer a hat that owns zero widgets. The path index IS in "
        "the plan — it builds the hash side — so the index assertion holds and "
        "says nothing about the finding, which is the blindness this measure is about. "
        "Asserted because the index claim is true and stable; the join "
        "strategy is deliberately not asserted.",
    ),
    "visible_to_count_spine": ("organization_path_prefix", True, ""),
    "governing_ancestor_lookup": (
        "organization_unique_path_per_tenant",
        False,
        "FINDING M1-C (plan shape is scale-dependent, and self-corrects upward). "
        "The ancestor `path IN (...)` under a tenant filter is SARGABLE against "
        "the (tenant, path) unique index — at 2,293 orgs per tenant the planner "
        "uses it with a 12-probe ScalarArrayOp Index Cond. At 1,253 it does not: "
        "the tenant-only index wins on cost and the tenant's whole org slice is "
        "scanned and filtered. Both plans are one query, so the count instrument "
        "sees nothing either way. The direction is benign (the shape improves as "
        "the tree grows), but it means **rule 35 must not pin a plan shape here**: "
        "the same query legitimately answers two ways on either side of a planner "
        "cost crossover. This is E1's `does_not_cover: planner choice at scale`, "
        "with a measured instance rather than a hypothesised one.",
    ),
    "resolve_org_membership_lookup": (
        "membership_unique_user_per_organization",
        True,
        "",
    ),
    "resolve_org_slug_lookup": ("organization_unique_slug_per_tenant", True, ""),
    "wide_children_page": ("core_organization_parent_id", True, ""),
    "wide_children_count": (
        "core_organization_parent_id",
        True,
        "NEW MEASURE (F1d): the second statement the same paginated listing "
        "issues. It holds the index too, which is what a listing keyed on a "
        "plain FK should do at any breadth.",
    ),
}

#: M1-2, made machine-readable: what E1 should put in the hot-path registry
#: (`hot_path_query_counts:` in `quality/budgets.yaml`, selectors in
#: `quality/rules.yaml`). Per entry: the dotted selector path, the index rule 35
#: should require in the plan (or `None` for "do not pin a plan shape here, and
#: the reason is in PLAN_EXPECTATIONS"), and the query count rule 5 should pin.
#: The counts are gate-scale counts precisely because they are flat: that is
#: what the doubling runs certify and what makes a cheap `assertNumQueries` at
#: fixture scale a statement about a million rows.
HOT_PATH_PROPOSALS: dict[str, dict[str, Any]] = {
    "apps.example.selectors.list_widgets": {
        "queries": 1,
        "index": "organization_path_prefix",
        "note": "one page, select_related('owner', 'organization'). Pin the COUNT "
        "everywhere. **Do NOT pin a plan shape** — earlier verdicts were "
        "taken on the unsliced queryset and every door reads a `@paginate`d "
        "page plus a COUNT(*) (the CORRECTION block in "
        "the retired perf-hierarchy-measurement.md). Off-root the page still rides "
        "the path index, but the root hat and the wide hat "
        "do not, and no index can make the wide hat.",
    },
    "apps.core.middleware.resolve_org": {
        "queries": 2,
        "index": "membership_unique_user_per_organization",
        "note": "2 with an X-Org slug (memberships + the slug lookup), 1 without. "
        "Pin the 2 — the header is the request shape a door actually sends, and "
        "the 1 is the same path with one lookup skipped.",
    },
    "apps.core.models.ScopedQuerySet.governing": {
        "queries": 1,
        "index": None,
        "note": "1 query at the depth ceiling, and 1 is the whole claim: the "
        "ancestor chain is decomposed in Python. Do NOT pin a plan shape until "
        "FINDING M1-C is dispositioned — pinning today would ratchet the scan in.",
    },
}

REPORT_PATH_TEMPLATE = "djb-perf-hierarchy-{world}.md"


# --- The world names itself ---------------------------------------------------


def world_axis(spec: ScaleSpec) -> str:
    """Which single axis this world doubled, or `"S"` for the declared base.

    Derived by diffing the world's spec against `DEFAULT_SPEC`, so it needs no
    flag and cannot disagree with the database it is describing.
    """
    base = dataclasses.asdict(DEFAULT_SPEC)
    here = dataclasses.asdict(spec)
    moved = sorted(name for name, value in here.items() if base[name] != value)
    return "S" if not moved else "+".join(moved)


@pytest.fixture(scope="session")
def world(spec: ScaleSpec) -> str:
    return world_axis(spec)


@pytest.fixture(scope="session")
def report(world: str) -> Path:
    """A fresh report file for this world, outside the repository."""
    path = Path(tempfile.gettempdir()) / REPORT_PATH_TEMPLATE.format(world=world)
    path.write_text(f"# M1 hierarchy measurements — world `{world}`\n", encoding="utf-8")
    return path


@pytest.fixture()
def note(report: Path) -> Any:
    """Append a section to the report the measurement doc is written from."""

    def _note(title: str, body: str) -> None:
        with report.open("a", encoding="utf-8") as handle:
            handle.write(f"\n## {title}\n\n{body.rstrip()}\n")

    return _note


@pytest.fixture()
def flat(world: str) -> Any:
    """Compare a measured query count against its declared S-value.

    In the base world this pins the number; in a doubled world it is the
    `flat_under_doubling` comparison itself, with the declaration standing in
    for the S run (the module docstring says why one run can only hold one).
    """

    def _flat(name: str, measured: int) -> None:
        measure.flat_under_doubling(
            base=DECLARED_QUERY_COUNTS[name],
            doubled=measured,
            axis=world,
            what=name,
        )

    return _flat


@pytest.fixture()
def tenant(loaded_tenants: list[Any]) -> Any:
    """The first loaded twin, `perf-a`."""
    return loaded_tenants[0]


@pytest.fixture()
def hats(tenant: Any, spec: ScaleSpec) -> dict[str, Any]:
    """The five measured positions in the tree, by the slugs the seeder used."""
    from apps.core.models import Organization

    orgs = Organization.objects.for_tenant(tenant)
    return {
        "root": orgs.get(parent__isnull=True),
        "region": orgs.get(slug=REGION_HAT_SLUG),
        "leaf": orgs.get(slug=HEAVY_ORG_SLUG),
        "wide": orgs.get(slug="wide"),
        "spine": orgs.get(slug=f"spine-{spec.spine_depth - 1:02d}"),
    }


def _subtree_size(tenant: Any, org: Any) -> int:
    """How many organizations this hat's `visible_to` prefix covers, itself included."""
    from apps.core.models import PATH_SEPARATOR, Organization

    descendants = (
        Organization.objects.for_tenant(tenant)
        .filter(path__startswith=org.path + PATH_SEPARATOR)
        .count()
    )
    return descendants + 1


#: The page every list door actually serves. `@paginate`'s default page size is
#: the number the plan must be read at, because a `LIMIT` is a planner input.
PAGE = 50


def _verdict_block(name: str, plan: str, what: str) -> str:
    """The markdown for one plan, plus the assertion `PLAN_EXPECTATIONS` declares.

    The assertion is made against **this** plan string, never by re-EXPLAINing
    a queryset: see `measure.assert_index_in` for why re-compiling substitutes
    a different query.
    """
    index_name, asserted, reason = PLAN_EXPECTATIONS[name]
    uses_index = index_name in plan
    seq_scan = "Seq Scan" in plan
    block = (
        f"**{what}** — index `{index_name}` in plan: **{uses_index}** · "
        f"Seq Scan present: **{seq_scan}** · asserted here: **{asserted}**"
    )
    if reason:
        block += f"\n\n> {reason}"
    block += f"\n\n```\n{plan.strip()}\n```"
    if asserted:
        measure.assert_index_in(plan, index_name, forbid_seq_scan=True)
    return block


def plan_verdict(name: str, queryset: Any) -> str:
    """EXPLAIN this queryset as compiled, record the verdict, assert where declared.

    For a read that is **not** a paginated door — a single-row lookup, an
    ancestor `count()`, a slice built by the caller — the queryset as compiled
    *is* the statement that runs, and this is the honest instrument.

    For a list door it is not: see `paginated_verdict`.
    """
    return _verdict_block(name, measure.explain(queryset), "as compiled")


def paginated_verdict(page_name: str, count_name: str, queryset: Any) -> str:
    """The two plans a paginated door actually issues, EXPLAINed as executed.

    **F1a's finding, made structural (REMIT 5).** `plan_verdict` above EXPLAINs
    the queryset it is handed, and M1 handed it the *unsliced* selector while
    every door reads through `@paginate`. Those are different queries with
    different plans: under `LIMIT 50` the planner may walk an ordering index
    and stop early, where the unsliced form has to resolve the whole set. A
    verdict taken on the unsliced query therefore describes a query no door
    issues — and an index tick earned there is not earned.

    So both statements the paginator emits are run and EXPLAINed verbatim
    (`measure.explain_as_executed`): the **page of `PAGE`** and the
    **`COUNT(*)`**. Each carries its own entry in `PLAN_EXPECTATIONS`, because
    they legitimately plan differently and pretending otherwise is how the
    first verdict went wrong.
    """
    page_plans = measure.explain_as_executed(lambda: list(queryset[:PAGE]))
    count_plans = measure.explain_as_executed(queryset.count)
    assert len(page_plans) == 1, f"{page_name}: expected one page statement, got {len(page_plans)}"
    assert len(count_plans) == 1, (
        f"{count_name}: expected one count statement, got {len(count_plans)}"
    )
    return (
        _verdict_block(page_name, page_plans[0], f"the page of {PAGE}, as executed")
        + "\n\n"
        + _verdict_block(count_name, count_plans[0], "the paginator's count(), as executed")
    )


# --- The measures -------------------------------------------------------------


def test_server_version_and_ceiling(note: Any, spec: ScaleSpec, world: str) -> None:
    """The header every plan excerpt is read against, plus the declared bound."""
    ceiling = _max_legal_depth()
    note(
        "world",
        f"- postgres server version: `{measure.postgres_server_version()}`\n"
        f"- world: `{world}`\n"
        f"- orgs per loaded tenant (spec arithmetic): {spec.orgs_per_loaded_tenant}\n"
        f"- spine depth seeded: {spec.spine_depth} segments "
        f"(deepest node `path_depth` = {spec.spine_depth - 1})\n"
        f"- **PATH_MAX_DEPTH (the platform's ceiling): {ceiling}** — "
        "`child_path` refuses a deeper path; the envelope's declared bound.",
    )
    # The seeded spine sits exactly at the ceiling in every declared world: the
    # `depth` axis is the one axis that cannot double, which is the finding
    # this measure exists around.
    assert spec.spine_depth == ceiling


def test_the_registry_this_rung_hands_e1(note: Any) -> None:
    """M1-2 as an artifact rather than as prose: the proposed hot-path entries.

    E1 writes `hot_path_query_counts:` in `quality/budgets.yaml` and rule 5/35's
    dotted selectors in `quality/rules.yaml`. It should read them off here, not
    re-derive them from a document: a registry re-derived by hand is the seam
    the criterion exists to close.
    """
    rows = ["| dotted path | queries | index rule 35 may require | note |", "|---|---|---|---|"]
    for path, entry in HOT_PATH_PROPOSALS.items():
        index = f"`{entry['index']}`" if entry["index"] else "**none — see the note**"
        rows.append(f"| `{path}` | {entry['queries']} | {index} | {entry['note']} |")
    note("proposed hot-path registry (for E1)", "\n".join(rows))
    # Every proposal names a count this module actually measured, so the
    # registry cannot drift from the measurements in the same file.
    assert (
        HOT_PATH_PROPOSALS["apps.example.selectors.list_widgets"]["queries"]
        == (DECLARED_QUERY_COUNTS["visible_to_page_leaf"])
    )
    assert (
        HOT_PATH_PROPOSALS["apps.core.middleware.resolve_org"]["queries"]
        == (DECLARED_QUERY_COUNTS["resolve_org_named_slug"])
    )
    assert (
        HOT_PATH_PROPOSALS["apps.core.models.ScopedQuerySet.governing"]["queries"]
        == (DECLARED_QUERY_COUNTS["governing_at_ceiling"])
    )


def test_prefix_scan_over_the_tree(
    tenant: Any, hats: dict[str, Any], spec: ScaleSpec, note: Any, flat: Any
) -> None:
    """`path__startswith` — one indexed prefix scan, no recursion, no tree walk."""
    from apps.core.models import PATH_SEPARATOR, Organization

    region = hats["region"]
    subtree = Organization.objects.for_tenant(tenant).filter(
        path__startswith=region.path + PATH_SEPARATOR
    )
    with measure.count_queries() as counted:
        rows = subtree.count()
    flat("prefix_scan_region_subtree", counted.count)
    assert rows == spec.partners_per_region

    root_subtree = Organization.objects.for_tenant(tenant).filter(
        path__startswith=hats["root"].path + PATH_SEPARATOR
    )
    with measure.count_queries() as counted_root:
        root_rows = root_subtree.count()
    flat("prefix_scan_root_subtree", counted_root.count)
    assert root_rows == spec.orgs_per_loaded_tenant - 1

    note(
        "prefix scan — a region's subtree",
        f"- rows: {rows} (spec: `partners_per_region` = {spec.partners_per_region})\n"
        f"- queries: {counted.count}\n"
        f"- root subtree rows: {root_rows} "
        f"(spec: `orgs_per_loaded_tenant - 1` = {spec.orgs_per_loaded_tenant - 1}), "
        f"queries: {counted_root.count}\n\n" + plan_verdict("prefix_scan_region_subtree", subtree),
    )


@pytest.mark.parametrize("position", ["root", "region", "leaf", "wide", "spine"])
def test_visible_to_at_every_hat_position(
    position: str,
    tenant: Any,
    hats: dict[str, Any],
    spec: ScaleSpec,
    note: Any,
    flat: Any,
) -> None:
    """One query per page at every hat, and the row share the spec predicts.

    The query count is the scale-free instrument; the row share is correctness
    riding along, recomputed from this world's own spec rather than declared.
    """
    from apps.core.actor import system_actor
    from apps.example.selectors import list_widgets

    org = hats[position]
    # The system actor: this harness measures the QUERY, and since Phase R the
    # selector asks `widget.read` at the hat first. A seeded perf world has no
    # membership to answer with, and `allows` passes `system` at step 1.
    actor = system_actor(tenant, org)
    page = list_widgets(tenant=tenant, org=org, actor=actor)[:50]
    with measure.count_queries() as counted_page:
        materialized = list(page)
    flat(f"visible_to_page_{position}", counted_page.count)

    with measure.count_queries() as counted_total:
        visible = list_widgets(tenant=tenant, org=org, actor=actor).count()
    flat(f"visible_to_count_{position}", counted_total.count)

    allocation = widget_allocation(spec)
    expected = {
        "root": spec.widgets,
        "region": expected_region_widgets(spec),
        "leaf": allocation[HEAVY_ORG_SLUG],
        "wide": 0,
        "spine": 0,
    }[position]
    subtree_orgs = _subtree_size(tenant, org)
    verdict = paginated_verdict(
        f"visible_to_page_{position}",
        f"visible_to_count_{position}",
        list_widgets(tenant=tenant, org=org, actor=actor),
    )
    breadth_note = ""
    if "Hash Join" in verdict:
        breadth_note = (
            "\n> **FINDING M1-B (plan-shape flip, breadth-driven).** At this hat the "
            "planner abandons the nested loop over the hat's subtree and hash-joins "
            "against a scan of the tenant's *entire* widget table. The trigger is the "
            "estimated size of the org subtree, so it is the wide node that crosses "
            "it: the count instrument stays at 1 and sees nothing. This is precisely "
            "the shape rule 35 exists to catch.\n"
        )
    note(
        f"visible_to — {position} hat (`{org.slug}`, path depth {org.depth})",
        f"- rows visible: {visible} (spec arithmetic: {expected})\n"
        f"- orgs in this hat's subtree: {subtree_orgs}\n"
        f"- queries, first page of 50: {counted_page.count} "
        f"(rows returned: {len(materialized)})\n"
        f"- queries, count(): {counted_total.count}\n" + breadth_note + "\n" + verdict,
    )
    assert visible == expected, (
        f"{position} hat resolves {visible} widgets; the spec's arithmetic says {expected}"
    )


def test_governing_at_the_depth_ceiling(
    tenant: Any, hats: dict[str, Any], spec: ScaleSpec, note: Any, flat: Any
) -> None:
    """Upward config resolution off the deepest node the platform allows.

    Measured **at** the ceiling rather than past it: `PATH_MAX_DEPTH` is 12 and
    the seeder refuses a deeper tree, so this is the worst case that can exist.
    The claim is that resolution costs one query and one `IN` list whose length
    is the node's own depth — no per-level round trip, no recursive CTE.
    """
    from apps.core.models import Organization, ancestor_paths
    from apps.example.models import WidgetPolicy

    deepest = hats["spine"]
    chain = ancestor_paths(deepest.path)
    ceiling = _max_legal_depth()

    with measure.count_queries() as counted:
        resolved = list(WidgetPolicy.objects.for_tenant(tenant).governing(deepest)[:1])
    flat("governing_at_ceiling", counted.count)

    # The predicate `governing()` puts on the joined organization, measured on
    # its own so the plan is read against a populated table: `WidgetPolicy` is
    # not seeded (declared limitation, recorded in the doc), and an EXPLAIN over
    # an empty table describes nothing.
    ancestors = Organization.objects.for_tenant(tenant).filter(path__in=chain)
    with measure.count_queries() as counted_ancestors:
        found = ancestors.count()
    flat("governing_ancestor_lookup", counted_ancestors.count)

    orgs_in_tenant = Organization.objects.for_tenant(tenant).count()
    note(
        "governing() at the depth ceiling",
        f"- deepest legal node: `{deepest.slug}`, path `{deepest.path}`, "
        f"`depth` = {deepest.depth}, segments = {len(chain)}\n"
        f"- **PATH_MAX_DEPTH = {ceiling}** — the declared bound; a 13th segment is "
        "refused by `child_path`, so the depth axis cannot be doubled and this "
        "measurement is the platform's worst case by construction\n"
        f"- ancestor chain length: {len(chain)} (decomposed in Python, zero queries)\n"
        f"- `governing()` queries: {counted.count}; rows resolved: {len(resolved)} "
        "(WidgetPolicy is unseeded — see the limitation below)\n"
        f"- ancestor-path lookup queries: {counted_ancestors.count}, rows: {found}\n"
        f"- orgs in this tenant (the slice the plan below actually scans): "
        f"{orgs_in_tenant}\n\n" + plan_verdict("governing_ancestor_lookup", ancestors),
    )
    assert len(chain) == deepest.depth + 1 == spec.spine_depth
    assert found == len(chain), "every ancestor path resolves to exactly one row"


def test_resolve_org_at_the_middleware_seam(
    tenant: Any, hats: dict[str, Any], note: Any, flat: Any
) -> None:
    """The one function all four doors call, per request, with and without `X-Org`."""
    from apps.accounts.models import User
    from apps.core.middleware import resolve_org
    from apps.core.models import Membership, Organization

    root_user = User.objects.get(email=hat_emails(tenant.slug)["root"])
    leaf_user = User.objects.get(email=hat_emails(tenant.slug)["leaf"])

    with measure.count_queries() as counted_default:
        default_hat = resolve_org(user=root_user, tenant=tenant, requested_slug=None)
    flat("resolve_org_default_hat", counted_default.count)
    assert default_hat is not None and default_hat.parent_id is None

    with measure.count_queries() as counted_named:
        named = resolve_org(user=root_user, tenant=tenant, requested_slug=HEAVY_ORG_SLUG)
    flat("resolve_org_named_slug", counted_named.count)
    assert named is not None and named.slug == HEAVY_ORG_SLUG

    # Fail-closed costs the same as success: the leaf hat may not wear the root.
    with measure.count_queries() as counted_refused:
        refused = resolve_org(user=leaf_user, tenant=tenant, requested_slug=REGION_HAT_SLUG)
    flat("resolve_org_refused_slug", counted_refused.count)
    assert refused is None

    membership_lookup = Membership.objects.filter(user_id=root_user.pk, tenant=tenant)
    slug_lookup = Organization.objects.for_tenant(tenant).filter(slug=HEAVY_ORG_SLUG)
    memberships_in_tenant = Membership.objects.filter(tenant=tenant).count()
    note(
        "resolve_org — the middleware seam",
        f"- default hat (no `X-Org`): {counted_default.count} queries, "
        f"resolved `{default_hat.slug}`\n"
        f"- named hat (`X-Org: {HEAVY_ORG_SLUG}`): {counted_named.count} queries\n"
        f"- refused hat (leaf asking for `{REGION_HAT_SLUG}`): "
        f"{counted_refused.count} queries, resolved `None` (fails closed)\n"
        f"- memberships in this tenant: {memberships_in_tenant} "
        "(the membership-doubling axis; the seam reads one user's, not the tenant's)\n\n"
        "### the membership lookup\n\n"
        + plan_verdict("resolve_org_membership_lookup", membership_lookup)
        + "\n\n### the slug lookup\n\n"
        + plan_verdict("resolve_org_slug_lookup", slug_lookup),
    )


def test_wide_node_children_listing(
    tenant: Any, hats: dict[str, Any], spec: ScaleSpec, note: Any, flat: Any
) -> None:
    """The 200-wide node, listed a page at a time: one query, breadth-independent."""
    from apps.core.models import Organization

    wide = hats["wide"]
    children = Organization.objects.for_tenant(tenant).filter(parent=wide)
    with measure.count_queries() as counted:
        page = list(children[:50])
    flat("wide_children_page", counted.count)
    assert len(page) == 50

    total = children.count()
    note(
        "the 200-wide node's children, paginated",
        f"- direct children: {total} (spec: `wide_children` = {spec.wide_children})\n"
        f"- queries for a page of 50: {counted.count}\n\n"
        + paginated_verdict("wide_children_page", "wide_children_count", children),
    )
    assert total == spec.wide_children
