"""M3 — identity and the doors, measured at the declared scale (ADR perf-1).

What this module measures, and why these four and not others: **every door
calls `core.middleware.resolve_org`**, every machine door calls
`accounts.services.authenticate_token`, and the MCP door calls
`accounts.oauth`. Those three functions are the per-request identity tax the
whole platform pays, so the envelope's identity rows have to be numbers rather
than confidence. The list endpoint rides along because rule 5's pin was
measured at ten rows and the envelope claims it at a hundred thousand.

**The instruments are the four in `perf/measure.py` and nothing else** — a
query count, an EXPLAIN plan shape, a flat-under-doubling
comparison, a cache-hit count. No assertion in this file is phrased in time,
and `perf/conftest.py` refuses one at import if it ever is.

## How flatness is proven across two worlds

A doubling run is a *different seeded world* (`scripts/perf.sh --double
<axis>` re-seeds), so a single pytest process never sees both. The comparison
is therefore made against the **declared budget**, which is a literal in this
file: at S every measure asserts `measured == BUDGET`; in a doubled world the
same measure hands `flat_under_doubling(base=BUDGET, doubled=measured, ...)`
the same literal, so a count that grew under doubling raises with both numbers
and the finding grammar. `_pin()` below is that fork, in one place.

The world names itself — `perf/conftest.py`'s `spec` fixture reads the stamp —
so nothing here is passed a flag.

## The declared budgets (measured, then written down; see
the retired `perf-identity-measurement.md` for the triples and the EXPLAIN
excerpts)

Every constant below is a query count at the seeded scale. They are the
platform's stated identity envelope; E1 is the rung that pins them in the gate.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

import pytest

from perf.measure import (
    assert_index_scan,
    call_counter,
    count_queries,
    explain,
    flat_under_doubling,
    postgres_server_version,
)
from perf.seed import DEFAULT_SPEC, DOUBLING_AXES, HEAVY_ORG_SLUG, ScaleSpec, hat_emails

pytestmark = pytest.mark.django_db

# --- The declared budgets -----------------------------------------------------

#: `authenticate_token` on a tenant-pinned token, first use in the touch
#: window: the indexed `key_hash` read, then the throttled `last_used_at`
#: write. Two, and neither of them depends on how many tokens exist.
TOKEN_AUTH_COLD = 2

#: The same call inside the touch window: the write is suppressed (N6's fix),
#: so the hottest read in the API is a read.
TOKEN_AUTH_WARM = 1

#: How many calls the throttle measure makes; only the first may write.
TOUCH_STORM = 50

#: `resolve_org` with no `X-Org`: one indexed read of "which memberships does
#: this person hold in this tenant", from which the default hat is answered.
RESOLVE_ORG_DEFAULT = 1

#: `resolve_org` with `X-Org`: the same membership read, plus the one lookup of
#: the organization the header named. **This is the revalidation path** — it is
#: re-run from rows on every request, never cached, and this is its price.
RESOLVE_ORG_REVALIDATED = 2

#: `resolve_tenant` — the step before the hat, for completeness of the seam.
RESOLVE_TENANT_DEFAULT = 1

#: **The many-hats person** (M3 FINDING F2, closed by F1d). `resolve_org`
#: materialises *every* membership the person holds in the tenant before it
#: tests the header against them, and the seeded world used to give every
#: person exactly one — so the measurement priced a population of 1 and the
#: envelope stated a number about a shape the platform explicitly supports and
#: had never measured. `perf/seed.py` now seeds one person holding
#: `spec.many_hats` memberships along the spine chain, and these are its
#: prices. They are the SAME two numbers as the one-hat person's: the read is
#: one indexed query whatever it returns, and the "holds a role over it" test
#: is a prefix comparison in Python over rows already in hand. **That
#: sameness is the claim** — what F2 warned about is the row count, not the
#: statement count, and pinning both hat shapes at the same budget is what
#: makes a future regression to a per-hat query visible.
RESOLVE_ORG_MANY_HATS_DEFAULT = 1
RESOLVE_ORG_MANY_HATS_REVALIDATED = 2

#: A session-authenticated `GET /api/v1/widgets/` at the loaded tenant.
#: session + user + SAVEPOINT + tenant membership + hat membership + COUNT +
#: page + RELEASE. Rule 5's pin (`apps/example/tests/test_api.py`,
#: LIST_QUERY_BUDGET = 8) re-proven against 100,000 rows instead of ten.
LIST_SESSION = 8

#: The same request carrying `X-Org`: + the named organization's lookup.
LIST_SESSION_WITH_ORG = 9

#: The same list through the machine door, first use in the touch window:
#: SAVEPOINT + token + touch + hat membership + COUNT + page + RELEASE.
LIST_TOKEN_COLD = 7

#: ...and inside the touch window, where the touch write is suppressed.
LIST_TOKEN_WARM = 6

#: `oauth.authenticate_bearer` per validated access token: the subject lookup
#: and the membership read `resolve_tenant` makes. No token row is written —
#: an OAuth caller holds no `ApiToken` — so this is the whole database cost.
OAUTH_PER_VALIDATION = 2

#: The storm: 1,000 sequential validations.
JWKS_STORM = 1_000

#: ...against which the cache-hit criterion is: our fetch seam is entered at
#: most once per cache window, for the JWKS and for the discovery document
#: alike.
JWKS_FETCHES_PER_WINDOW = 1

#: The spine node the depth measure wears as a hat. `spine_depth = 12`
#: segments means the deepest spine node's `path_depth` is 11.
DEEP_SPINE_SLUG = "spine-11"


# --- The two-world fork -------------------------------------------------------


def doubled_axis(spec: ScaleSpec) -> str | None:
    """Which axis this world has at x2, or `None` for the base world."""
    for axis in DOUBLING_AXES:
        try:
            if DEFAULT_SPEC.doubled(axis) == spec:
                return axis
        except Exception:  # noqa: BLE001, S112 — an axis the platform refuses to double
            continue
    return None


def _pin(spec: ScaleSpec, *, what: str, measured: int, budget: int) -> None:
    """The declared budget at S; the flatness comparator in a doubled world."""
    axis = doubled_axis(spec)
    if axis is None:
        if measured != budget:
            raise AssertionError(
                f"{what}: measured {measured} queries at the declared scale, "
                f"budget is {budget}. A number that moved is a FINDING — record "
                "it with its EXPLAIN pair in the retired perf-identity-measurement.md."
            )
        return
    flat_under_doubling(base=budget, doubled=measured, axis=axis, what=what)


def _report(what: str, **numbers: Any) -> None:
    """The doc's raw material. Printed, never asserted — see `-s` in the doc."""
    rendered = " · ".join(f"{name}={value}" for name, value in numbers.items())
    print(f"\n[M3] {what}: {rendered}")


# --- The world, resolved once per test ----------------------------------------


@pytest.fixture()
def loaded(loaded_tenants: list[Any]) -> Any:
    """The first loaded twin. The two are identical worlds; one is the subject."""
    return loaded_tenants[0]


@pytest.fixture()
def hats(loaded: Any) -> dict[str, Any]:
    """The three named hat users of the loaded tenant, by position."""
    from apps.accounts.models import User

    emails = hat_emails(loaded.slug)
    people = {
        email: user
        for email, user in User.objects.filter(email__in=emails.values())
        .in_bulk(field_name="email")
        .items()
    }
    return {position: people[email] for position, email in emails.items()}


@pytest.fixture()
def orgs(loaded: Any) -> dict[str, Any]:
    """Root, the deep spine node, and the heavy partner — by slug."""
    from apps.core.models import Organization

    wanted = {"root": loaded.slug, "spine": DEEP_SPINE_SLUG, "heavy": HEAVY_ORG_SLUG}
    found = Organization.objects.for_tenant(loaded).filter(slug__in=wanted.values())
    by_slug = {org.slug: org for org in found}
    resolved = {name: by_slug.get(slug) for name, slug in wanted.items()}
    if resolved["root"] is None:
        # `create_tenant` names the root after the tenant; fall back to the
        # structural truth rather than to a guess about the naming.
        resolved["root"] = Organization.objects.for_tenant(loaded).get(parent__isnull=True)
    return resolved


def _token_plaintext(tenant_slug: str, index: int = 0) -> str:
    """The seed's deterministic token material (`perf/seed.py::_seed_tokens`)."""
    return f"perf:{tenant_slug}:{index}"


# --- 1. token -> actor --------------------------------------------------------


def test_token_auth_costs_two_queries_cold_and_one_warm(loaded: Any, spec: ScaleSpec) -> None:
    """The machine door's identity tax at `api_tokens` tokens in the tenant.

    Cold is the indexed hash read plus the throttled `last_used_at` write;
    warm is the read alone. Neither depends on how many tokens exist — that is
    what the token-doubling run proves.
    """
    from apps.accounts.services import authenticate_token

    plaintext = _token_plaintext(loaded.slug)

    with count_queries() as cold:
        resolved = authenticate_token(plaintext=plaintext, requested_slug=loaded.slug)
    assert resolved is not None, "the seeded token did not authenticate"
    assert resolved[1].pk == loaded.pk, "a pinned token resolved to another tenant"

    with count_queries() as warm:
        again = authenticate_token(plaintext=plaintext, requested_slug=loaded.slug)
    assert again is not None

    _report(
        "token auth",
        tokens=spec.api_tokens,
        cold=cold.count,
        warm=warm.count,
        server=postgres_server_version(),
    )
    _pin(spec, what="authenticate_token (cold)", measured=cold.count, budget=TOKEN_AUTH_COLD)
    _pin(spec, what="authenticate_token (warm)", measured=warm.count, budget=TOKEN_AUTH_WARM)


def test_the_token_lookup_is_an_index_read_not_a_scan(loaded: Any) -> None:
    """`key_hash` is unique and the read has to use it — at 500 rows a Seq Scan
    would still be fast, which is exactly why a count cannot catch it and the
    plan shape must."""
    from apps.accounts.models import ApiToken
    from apps.accounts.services import hash_token

    queryset = ApiToken.objects.filter(
        key_hash=hash_token(_token_plaintext(loaded.slug)), revoked_at__isnull=True
    )
    plan = assert_index_scan(queryset, "accounts_apitoken_key_hash")
    _report("token lookup EXPLAIN", plan=plan.replace("\n", " | "))


def test_the_last_used_at_throttle_suppresses_the_write_at_scale(
    loaded: Any, spec: ScaleSpec
) -> None:
    """N6's fix, observed holding: `TOUCH_STORM` uses, exactly one write.

    The instrument is a query count of UPDATE statements over the storm, which
    is the only honest way to say "the hottest read in the API is a read": a
    per-request write serialises concurrent machine traffic on one row.
    """
    from apps.accounts.services import authenticate_token

    plaintext = _token_plaintext(loaded.slug, index=1)
    with count_queries() as storm:
        for _ in range(TOUCH_STORM):
            authenticate_token(plaintext=plaintext, requested_slug=loaded.slug)
    writes = [
        query
        for query in storm.captured_queries
        if query["sql"].lstrip().upper().startswith("UPDATE")
    ]
    _report(
        "last_used_at throttle",
        uses=TOUCH_STORM,
        queries=storm.count,
        writes=len(writes),
        tokens=spec.api_tokens,
    )
    _pin(
        spec,
        what=f"touch writes over {TOUCH_STORM} uses",
        measured=len(writes),
        budget=1,
    )
    _pin(
        spec,
        what=f"queries over {TOUCH_STORM} token authentications",
        measured=storm.count,
        budget=TOKEN_AUTH_COLD + (TOUCH_STORM - 1) * TOKEN_AUTH_WARM,
    )


# --- 2. resolve_org: the one function all four doors call ---------------------


def test_resolve_org_costs_one_query_without_a_header(
    loaded: Any, hats: dict[str, Any], spec: ScaleSpec
) -> None:
    """The default hat: one indexed membership read, at 3,000 memberships."""
    from apps.core.middleware import resolve_org, resolve_tenant

    person = hats["root"]
    with count_queries() as tenant_side:
        tenant = resolve_tenant(user=person, requested_slug=loaded.slug)
    assert tenant is not None

    with count_queries() as counted:
        org = resolve_org(user=person, tenant=loaded, requested_slug=None)
    assert org is not None, "the root hat resolved to nothing"

    _report(
        "resolve_org (default hat)",
        memberships=spec.memberships,
        orgs=spec.orgs_per_loaded_tenant,
        resolve_tenant=tenant_side.count,
        resolve_org=counted.count,
    )
    _pin(spec, what="resolve_tenant", measured=tenant_side.count, budget=RESOLVE_TENANT_DEFAULT)
    _pin(spec, what="resolve_org (no header)", measured=counted.count, budget=RESOLVE_ORG_DEFAULT)


def test_the_x_org_revalidation_path_costs_two_queries(
    loaded: Any, hats: dict[str, Any], orgs: dict[str, Any], spec: ScaleSpec
) -> None:
    """`X-Org` is revalidated from rows on every request — never from a session.

    Two queries: the person's memberships in this tenant, and the organization
    the header named. The "holds a role over it" test is then a prefix
    comparison in Python over rows already in hand, which is why the price does
    not move with the tree.
    """
    from apps.core.middleware import resolve_org

    with count_queries() as counted:
        org = resolve_org(user=hats["root"], tenant=loaded, requested_slug=orgs["heavy"].slug)
    assert org is not None and org.slug == HEAVY_ORG_SLUG

    _report(
        "resolve_org (X-Org revalidation)",
        memberships=spec.memberships,
        orgs=spec.orgs_per_loaded_tenant,
        queries=counted.count,
    )
    _pin(spec, what="resolve_org (X-Org)", measured=counted.count, budget=RESOLVE_ORG_REVALIDATED)


def test_the_many_hats_person_costs_the_same_as_the_one_hat_person(
    loaded: Any, hats: dict[str, Any], orgs: dict[str, Any], spec: ScaleSpec
) -> None:
    """One person, `many_hats` memberships in one tenant — M3 FINDING F2, priced.

    F2 was a **fixture** blind spot, not a code one: `resolve_org` reads
    `list(Membership.objects.filter(user_id=..., tenant=...))`, and every
    person in the seeded world held exactly one membership, so "1 query, 1
    row" was measured and only the first half of it was a statement about the
    platform. `perf/seed.py::many_hats_organizations` now seeds the shape the
    model's own docstring names — a person over several organizations — along
    the spine chain, so the hats are nested inside one another and the "holds
    a role over it" prefix test has real work to compare.

    The claim: **the statement count does not move.** Both the header-less and
    the `X-Org` paths cost what the one-hat person costs, at `many_hats` rows
    instead of one, because the extra rows arrive in the same query and the
    role test is Python over rows already in hand. What F2 said would grow —
    the rows materialised — grows, and is recorded rather than asserted: it is
    a row count, and row counts move legitimately when an axis doubles.

    The failure this catches: a refactor that asks the database once per hat
    (or once per ancestor) would leave the one-hat measures above green and
    turn this one red at `many_hats` queries.
    """
    from apps.core.middleware import resolve_org
    from apps.core.models import Membership

    person = hats["many"]
    held = Membership.objects.filter(user_id=person.pk, tenant=loaded).count()
    assert held == spec.many_hats, (
        f"the many-hats person holds {held} memberships, the spec declares "
        f"{spec.many_hats} — the world is not the world this measure describes"
    )

    with count_queries() as without_header:
        default_hat = resolve_org(user=person, tenant=loaded, requested_slug=None)
    assert default_hat is not None, "the many-hats person resolved to no default hat"

    with count_queries() as with_header:
        named = resolve_org(user=person, tenant=loaded, requested_slug=orgs["spine"].slug)
    assert named is not None and named.slug == orgs["spine"].slug, (
        "the many-hats person holds a hat ON the deepest spine node and must "
        "resolve it; a None here is the seeder's chain broken, not a cost finding"
    )

    _report(
        "resolve_org (the many-hats person)",
        hats_held=held,
        one_hat_person_holds=1,
        resolve_org_no_header=without_header.count,
        resolve_org_x_org=with_header.count,
    )
    _pin(
        spec,
        what="resolve_org, many hats (no header)",
        measured=without_header.count,
        budget=RESOLVE_ORG_MANY_HATS_DEFAULT,
    )
    _pin(
        spec,
        what="resolve_org, many hats (X-Org)",
        measured=with_header.count,
        budget=RESOLVE_ORG_MANY_HATS_REVALIDATED,
    )


def test_hat_resolution_costs_the_same_at_depth_eleven_as_at_the_root(
    loaded: Any, hats: dict[str, Any], orgs: dict[str, Any], spec: ScaleSpec
) -> None:
    """The depth measure the plan names: a depth-11 spine hat vs a root hat.

    The root hat may wear any node beneath it, so the same person names the
    root and then the deepest spine node. If depth cost anything, the second
    count would be larger — a tree walk, an ancestor query per level. It is
    not: the check is `is_descendant_path`, a string prefix test over the
    memberships already read.
    """
    from apps.core.middleware import resolve_org
    from apps.core.models import path_depth

    root, spine = orgs["root"], orgs["spine"]
    assert spine is not None, f"{DEEP_SPINE_SLUG} is not in the seeded tree"

    with count_queries() as at_root:
        shallow = resolve_org(user=hats["root"], tenant=loaded, requested_slug=root.slug)
    with count_queries() as at_depth:
        deep = resolve_org(user=hats["root"], tenant=loaded, requested_slug=spine.slug)

    assert shallow is not None and deep is not None
    assert path_depth(deep.path) == spec.spine_depth - 1, "the spine hat is not where it should be"

    _report(
        "hat resolution by depth",
        root_depth=path_depth(shallow.path),
        root_queries=at_root.count,
        spine_depth=path_depth(deep.path),
        spine_queries=at_depth.count,
    )
    flat_under_doubling(
        base=at_root.count,
        doubled=at_depth.count,
        axis="hat depth (root -> depth 11)",
        what="resolve_org at depth",
    )
    _pin(
        spec,
        what="resolve_org at depth 11",
        measured=at_depth.count,
        budget=RESOLVE_ORG_REVALIDATED,
    )


def test_a_hat_the_person_does_not_hold_fails_closed_at_the_same_price(
    loaded: Any, hats: dict[str, Any], orgs: dict[str, Any], spec: ScaleSpec
) -> None:
    """The refusal costs what the grant costs — no cheap path, no slow path.

    A leaf hat naming the deep spine node holds no role over it (nothing
    inherits upward or sideways), so it resolves to `None`. The correctness
    rides along with the number: an unresolved hat reads an empty table.
    """
    from apps.core.middleware import resolve_org

    with count_queries() as counted:
        refused = resolve_org(user=hats["leaf"], tenant=loaded, requested_slug=orgs["spine"].slug)
    assert refused is None, "a leaf hat was granted a node it holds no role over"

    _report("resolve_org (refused hat)", queries=counted.count)
    _pin(spec, what="resolve_org (refused)", measured=counted.count, budget=RESOLVE_ORG_REVALIDATED)


#: The index `resolve_org`'s organization lookup rides **once the database has
#: statistics**. Three tenant-leading indexes can satisfy the query and only
#: this one carries `slug`, so which one the planner picks is the difference
#: between a one-row `Index Cond` and reading every organization in the tenant
#: with `slug` applied as a `Filter`. See FINDING M3-F3.
ORG_LOOKUP_INDEX = "organization_unique_slug_per_tenant"


def _refuse_a_scan(plan: str) -> None:
    """The invariant, separately from the finding: never a Seq Scan."""
    if "Seq Scan" in plan:
        raise AssertionError(f"a Seq Scan appears where an index read must be:\n{plan}")


def _column_is_an_index_cond(plan: str, column: str) -> bool:
    """Whether `column` is narrowing the index read or merely filtering it.

    The difference the name of the index cannot tell you: `Index Cond:
    ((tenant_id = …) AND ((slug)::text = …))` is a lookup, while `Index Cond:
    (tenant_id = …)` with `Filter: ((slug)::text = …)` reads the whole tenant
    and throws most of it away. Both are "an index scan"; only one is cheap.
    """
    return any(column in line for line in plan.splitlines() if "Index Cond" in line)


# Statistics are the seeder's job, not a measurement's: `perf/seed.py::seed_scale`
# runs `ANALYZE` at the end of every seed and re-seed (M2 FINDING F / M3-F3,
# fixed by F1d), so every plan below is taken against an analyzed database and
# the module no longer runs `ANALYZE` of its own.


def test_the_membership_read_and_the_org_lookup_are_index_scans(
    loaded: Any, hats: dict[str, Any], orgs: dict[str, Any]
) -> None:
    """`resolve_org`'s two statements, by plan shape rather than by count.

    Both are unique-constraint reads and both must stay that way: at 3,000
    memberships and 1,253 organizations a sequential scan is still quick, so
    only the plan can tell the truth about what happens at ten times this.

    The organization lookup used to be measured **twice** — as the planner saw
    it on arrival, and again after this module ran its own `ANALYZE` — because
    on a freshly bulk-loaded database the two were not the same plan (FINDING
    M3-F3). F1d moved the `ANALYZE` into `perf/seed.py::seed_scale`, where it
    belongs, so there is one plan again and the as-found reading **is** the
    analyzed one. That makes this test the seeder's canary as well as
    `resolve_org`'s: if the seeder ever stopped analyzing, `slug` would fall
    back into the `Filter` and the assertion below would say so.
    """
    from apps.core.models import Membership, Organization

    named = Organization.objects.for_tenant(loaded).filter(slug=orgs["spine"].slug)

    memberships = Membership.objects.filter(user_id=hats["root"].pk, tenant=loaded).select_related(
        "organization"
    )
    membership_plan = assert_index_scan(memberships, "membership_unique_user_per_organization")

    analyzed = explain(named)
    _refuse_a_scan(analyzed)
    assert ORG_LOOKUP_INDEX in analyzed, (
        f"with current statistics the organization lookup must ride "
        f"{ORG_LOOKUP_INDEX!r}:\n{analyzed}"
    )
    assert _column_is_an_index_cond(analyzed, "slug"), (
        "`slug` is a Filter, not an Index Cond — the X-Org lookup is reading "
        f"the whole tenant's tree. On a seeded world this means `seed_scale` "
        f"did not ANALYZE:\n{analyzed}"
    )

    _report(
        "resolve_org EXPLAIN",
        memberships=membership_plan.replace("\n", " | "),
        organization=analyzed.replace("\n", " | "),
        slug_narrowed_as_found=True,
    )


# --- 3. the door tier: the same seam through the full middleware stack --------


#: The list route's path. Literal, as `apps/example/tests/test_api.py` has it:
#: `config/urls.py` owns the version segment and the app's label is the prefix,
#: and a measurement that reversed the name would be measuring the router.
LIST_URL = "/api/v1/widgets/"


@pytest.fixture()
def client() -> Any:
    from django.test import Client

    return Client()


def test_the_rest_door_pays_the_hierarchy_once_per_request(
    client: Any, loaded: Any, hats: dict[str, Any], orgs: dict[str, Any], spec: ScaleSpec
) -> None:
    """M1's `resolve_org` number, confirmed end-to-end through the door.

    Rule 5's pin (LIST_QUERY_BUDGET = 8, measured at ten rows) is re-proven
    here against `widgets` rows and `orgs` organizations, and the `X-Org`
    variant shows the revalidation costing exactly the one extra read it costs
    when called directly. The page itself is one query however many rows come
    back — `select_related("owner", "organization")` is the contract, not an
    optimisation.
    """
    client.force_login(hats["root"])
    headers = {"HTTP_X_TENANT": loaded.slug}

    with count_queries() as plain:
        response = client.get(LIST_URL, **headers)
    assert response.status_code == 200, response.content[:400]
    body = response.json()
    assert body["count"] == spec.widgets, "the root hat does not see the whole tenant"

    with count_queries() as with_org:
        scoped = client.get(LIST_URL, **headers, HTTP_X_ORG=orgs["heavy"].slug)
    assert scoped.status_code == 200, scoped.content[:400]

    _report(
        "REST list (session)",
        widgets=spec.widgets,
        orgs=spec.orgs_per_loaded_tenant,
        plain=plain.count,
        with_x_org=with_org.count,
        rows_visible=body["count"],
        rows_visible_scoped=scoped.json()["count"],
    )
    _pin(spec, what="GET /api/v1/widgets/ (session)", measured=plain.count, budget=LIST_SESSION)
    _pin(
        spec,
        what="GET /api/v1/widgets/ (session + X-Org)",
        measured=with_org.count,
        budget=LIST_SESSION_WITH_ORG,
    )


def test_the_machine_door_pays_the_same_hierarchy_and_one_token_read(
    client: Any, loaded: Any, spec: ScaleSpec
) -> None:
    """The token door end-to-end, cold and warm.

    Same hat resolution, same page; what differs is the credential — the token
    read instead of the session pair, and the throttled touch on first use.
    """
    plaintext = _token_plaintext(loaded.slug, index=2)
    headers = {"HTTP_AUTHORIZATION": f"Bearer {plaintext}"}

    with count_queries() as cold:
        response = client.get(LIST_URL, **headers)
    assert response.status_code == 200, response.content[:400]

    with count_queries() as warm:
        again = client.get(LIST_URL, **headers)
    assert again.status_code == 200

    _report(
        "REST list (token)",
        tokens=spec.api_tokens,
        widgets=spec.widgets,
        cold=cold.count,
        warm=warm.count,
    )
    _pin(
        spec, what="GET /api/v1/widgets/ (token, cold)", measured=cold.count, budget=LIST_TOKEN_COLD
    )
    _pin(
        spec, what="GET /api/v1/widgets/ (token, warm)", measured=warm.count, budget=LIST_TOKEN_WARM
    )


def test_the_list_page_plan_is_recorded_at_a_hundred_thousand_rows(
    loaded: Any, orgs: dict[str, Any]
) -> None:
    """The page's plan, recorded rather than asserted — and the reason.

    A root hat's `visible_to` prefix matches every row in the tenant, so the
    planner is right to read the table; asserting an index there would pin a
    plan the data shape, not the code, decides. The narrow hat is the case
    where the index has to earn its keep, and that one is M1's subject (the
    hierarchy's own rung owns `organization_path_prefix`). Both plans go into
    the doc as observations so E1 can see what it is pinning.
    """
    from apps.core.actor import system_actor
    from apps.example.selectors import list_widgets

    # The system actor, for the reason `measure_hierarchy.py` gives at its own
    # call site: a seeded perf world has no membership, and what is being read
    # here is a query PLAN.
    wide = explain(
        list_widgets(tenant=loaded, org=orgs["root"], actor=system_actor(loaded, orgs["root"]))[:50]
    )
    narrow = explain(
        list_widgets(tenant=loaded, org=orgs["heavy"], actor=system_actor(loaded, orgs["heavy"]))[
            :50
        ]
    )
    _report(
        "list page EXPLAIN",
        server=postgres_server_version(),
        root_hat=wide.replace("\n", " | "),
        heavy_partner=narrow.replace("\n", " | "),
    )


# --- 4. the JWKS storm --------------------------------------------------------


@pytest.fixture()
def resource_server(settings: Any) -> Any:
    """A real OpenID Connect issuer on loopback, and this deployment pointed at
    it — the suite's own `stub_issuer`, reused rather than reinvented.

    `config/settings/test.py` pins the issuer at a dead port and the audience
    empty, which `oauth.configured()` reads as "there is no door". A
    measurement of the door has to arm it, and arming it here says which
    deployment state these numbers describe.
    """
    from apps.accounts import oauth
    from apps.accounts.tests.stub_issuer import running_issuer

    with running_issuer() as issuer:
        settings.ZITADEL_ISSUER = issuer.base_url
        settings.ZITADEL_MCP_AUDIENCE = ["djb-mcp"]
        oauth.reset_caches()
        try:
            yield issuer
        finally:
            oauth.reset_caches()


def test_a_thousand_validations_fetch_the_key_set_once(
    resource_server: Any, loaded: Any, hats: dict[str, Any], spec: ScaleSpec
) -> None:
    """The cache-hit criterion (discipline clause (c)), not a stopwatch.

    1,000 sequential access-token validations enter our fetch seam at most
    once per cache window — once for the discovery document, once for the key
    set. The counters are `call_counter` on `PyJWKClient.fetch_data` (the seam
    we own into pyjwt) corroborated by the issuer's own request log, which is
    ground truth about what crossed the socket.

    The per-validation database cost is measured alongside: the subject lookup
    and the membership read `resolve_tenant` makes. There is no token row and
    nothing is written, so those two are the whole of it.
    """
    import jwt

    from apps.accounts import oauth
    from apps.accounts.tests.stub_issuer import sign_jwt

    person = hats["root"]
    subject = f"perf-{loaded.slug}-storm"
    type(person).objects.filter(pk=person.pk).update(zitadel_sub=subject)

    issued_at = int(time.time())
    token = sign_jwt(
        {
            "iss": resource_server.base_url,
            "aud": "djb-mcp",
            "sub": subject,
            "iat": issued_at,
            "exp": issued_at + 3600,
        }
    )

    with call_counter(jwt.PyJWKClient, "fetch_data") as fetches:
        with count_queries() as storm:
            for _ in range(JWKS_STORM):
                principal = oauth.authenticate_bearer(token=token, requested_slug=loaded.slug)
    assert principal.subject == subject
    assert principal.tenant is not None and principal.tenant.pk == loaded.pk

    over_the_wire = [path for method, path in resource_server.requests if method == "GET"]
    jwks_requests = over_the_wire.count("/jwks")
    discovery_requests = over_the_wire.count("/.well-known/openid-configuration")

    _report(
        "JWKS storm",
        validations=JWKS_STORM,
        fetch_data_calls=fetches.count,
        jwks_over_the_wire=jwks_requests,
        discovery_over_the_wire=discovery_requests,
        queries=storm.count,
        queries_per_validation=storm.count / JWKS_STORM,
    )
    _pin(
        spec,
        what="PyJWKClient.fetch_data over the storm",
        measured=fetches.count,
        budget=JWKS_FETCHES_PER_WINDOW,
    )
    _pin(
        spec,
        what="JWKS requests over the wire",
        measured=jwks_requests,
        budget=JWKS_FETCHES_PER_WINDOW,
    )
    _pin(
        spec,
        what="discovery requests over the wire",
        measured=discovery_requests,
        budget=JWKS_FETCHES_PER_WINDOW,
    )
    _pin(
        spec,
        what="queries over the storm",
        measured=storm.count,
        budget=OAUTH_PER_VALIDATION * JWKS_STORM,
    )


def test_the_oauth_subject_lookup_is_an_index_read(loaded: Any, hats: dict[str, Any]) -> None:
    """`zitadel_sub` is unique, and the MCP door's first statement reads it."""
    person = hats["root"]
    subject = f"perf-{loaded.slug}-storm"
    type(person).objects.filter(pk=person.pk).update(zitadel_sub=subject)

    queryset = type(person).objects.filter(zitadel_sub=subject, is_active=True)
    plan = assert_index_scan(queryset, "accounts_user_zitadel_sub")
    _report("oauth subject EXPLAIN", plan=plan.replace("\n", " | "))


# --- The stamp on every run ---------------------------------------------------


def test_the_world_these_numbers_describe_is_the_declared_one(spec: ScaleSpec) -> None:
    """Not a measurement — the sentence every number above needs beside it.

    A count is meaningless without the world it was taken in, so the run states
    the world: the declared spec, or the one axis this run has at x2.
    """
    axis = doubled_axis(spec)
    _report(
        "world",
        axis=axis or "none (the declared spec)",
        tenants=spec.tenants,
        orgs_per_loaded_tenant=spec.orgs_per_loaded_tenant,
        memberships=spec.memberships,
        widgets=spec.widgets,
        api_tokens=spec.api_tokens,
        postgres=postgres_server_version(),
    )
    known = hashlib.sha256(repr(spec).encode()).hexdigest()[:12]
    assert known, "the spec did not hash — the world cannot name itself"
