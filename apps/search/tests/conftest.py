"""The world every search test is measured against.

Two shapes have to exist before any assertion here means anything.

**A tree, and a neighbour.** `visible_to` is downward-only, so the smallest
world in which "the scope leaked" can *fail* is a hat with a child beneath it, a
sibling beside it and a second tenant next door. A single flat tenant would let
both leaks through while every assertion passed.

**Two kinds, one org-scoped and one not.** The injected filter is per-kind — an
org-scoped kind gets `tenant_id AND org_id IN [...]` and a tenant-scoped one
gets `tenant_id` — and a world with only one shape cannot tell a correct
injection from a one-shape-fits-all that goes org-blind on the scoped half. That
is that class, and it is the reason `kinds` here is two and not one.

`apps/example` declares one real kind (`widgets`, over `Widget`), and
these tests still **plant** their two through the registry's one seam rather
than reading the live population. That is deliberate rather than left over: the
tenant-scoped half of the pair has no adopter in the tree, a suite that read the
live registry would change shape the day any app declared a kind, and a planted
declaration is also what lets a test hand the reconcile a digest it controls.
The live adoption is asserted where it belongs — in the adopting app's own
`apps/example/tests/test_search_adoption.py`.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pytest
from django.core.cache import cache

from apps.accounts.models import User
from apps.conftest import organ
from apps.core.actor import Actor, actor_for
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import add_membership, create_organization
from apps.example.models import Widget
from apps.example.services import create_widget
from apps.search import registry
from apps.search.types import RecordingEngine, Searchable

#: A literal handed to `create_user`, long enough to clear Django's validators
#: and nothing else. Allow-listed because it is exactly what the scanner is
#: right to look at, and exactly what a reader should see is fake.
PASSWORD = "a-long-enough-password-for-validators"  # pragma: allowlist secret

#: The org-scoped kind: `Widget` carries an `organization`, so its filter is the
#: two-clause one.
WIDGETS = Searchable(
    model=Widget,
    label="widgets",
    fields=[("name", "A")],
    display="name",
)

#: The tenant-scoped kind: `Organization` carries a tenant and no `organization`
#: column, so its filter is `tenant_id` alone. Using a real model rather than a
#: stub is deliberate — `is_org_scoped` reads the model, and a stub would let
#: this test agree with a registry that had stopped reading anything.
ORGS = Searchable(
    model=Organization,
    label="orgs",
    fields=[("name", "A")],
    display="name",
)


@dataclass(frozen=True)
class World:
    """One tenant shaped like a customer, plus a neighbour to leak into."""

    tenant: Tenant
    root: Organization
    region: Organization
    branch: Organization
    sibling: Organization
    owner: User
    region_admin: User
    owner_actor: Actor
    region_actor: Actor


@pytest.fixture(autouse=True)
def _a_closed_circuit() -> Iterator[None]:
    """Every search test starts and ends with the circuit closed.

    The circuit's state lives in the cache, not in the database, so nothing in
    the test harness rolls it back: one test that fails over would otherwise
    leave the cooldown key set for whatever ran next in that process, and the
    next test would silently prove its assertion against the FALLBACK while
    believing it had asked the primary. That is the worst shape a leak can take
    — a green test measuring the wrong engine — so it is cleaned in both
    directions rather than only after.

    Autouse and unconditional: a fixture the degradation tests had to remember
    to request is a fixture the tests that are not about degradation would never
    request, and those are precisely the ones a stale key would mislead.
    """
    from apps.search import selectors

    keys = [selectors.COOLDOWN_KEY, selectors.DEGRADED_KEY]
    cache.delete_many(keys)
    yield
    cache.delete_many(keys)


@pytest.fixture
def world(tenant: Tenant, owner: User, root_org: Organization) -> World:
    """A tenant with a three-node tree and a person acting at each of two levels."""
    acting = actor_for(user=owner, tenant=tenant, org=root_org)
    region = create_organization(
        tenant=tenant, parent=root_org, name="Region", slug="region", actor=acting
    )
    branch = create_organization(
        tenant=tenant, parent=region, name="Branch", slug="branch", actor=acting
    )
    sibling = create_organization(
        tenant=tenant, parent=root_org, name="Sibling", slug="sibling", actor=acting
    )
    from apps.accounts.services import create_user

    region_admin = create_user(email="region-admin@acme.com", password=PASSWORD)
    add_membership(
        user=region_admin,
        tenant=tenant,
        organization=region,
        is_default=True,
        role=Membership.Role.ADMIN,
        actor=acting,
    )
    region_acting = actor_for(user=region_admin, tenant=tenant, org=region)
    for org, who in ((root_org, acting), (region, region_acting), (sibling, acting)):
        create_widget(tenant=tenant, actor=who, name=f"Widget at {org.slug}")
    return World(
        tenant=tenant,
        root=root_org,
        region=region,
        branch=branch,
        sibling=sibling,
        owner=owner,
        region_admin=region_admin,
        owner_actor=acting,
        region_actor=region_acting,
    )


@pytest.fixture
def declared(monkeypatch: pytest.MonkeyPatch) -> tuple[Searchable, ...]:
    """Two kinds declared, through the one seam an app declares through.

    Patched at `registry.declarations` rather than by writing a module into
    `apps/example`, because the point of the fixture is that discovery has ONE
    entry point: everything else in the registry (`labels`, `by_label`,
    `resolve_kinds`) is derived from it, so patching here exercises the
    derivation instead of bypassing it.
    """
    declarations = (WIDGETS, ORGS)
    monkeypatch.setattr(registry, "declarations", lambda: declarations)
    return declarations


@pytest.fixture
def recording(monkeypatch: pytest.MonkeyPatch) -> RecordingEngine:
    """A `SearchEngine` that records what it was handed and indexes nothing.

    The filter probe reads `engine.filters`: **what the engine RECEIVED is the
    only honest evidence about what the chokepoint injected.** Asserting on the
    selector's own local variable would be asserting that a line of code is the
    line of code above it.
    """
    engine = RecordingEngine()
    from apps.search import engine as engine_module

    # Patched at `engine.engine` — the ONE factory both the chokepoint and the
    # reconcile call — rather than at each caller. A double installed per caller
    # is a double that can be installed at one caller and forgotten at the
    # other, which is how a test proves the half nobody was worried about.
    monkeypatch.setattr(engine_module, "engine", lambda: engine)
    return engine


@pytest.fixture
@organ("meili")
def live_meili(settings: Any) -> str:
    """Arm the REAL compose Meilisearch **for this test only**, and skip without one.

    `config/settings/test.py` pins `MEILI_URL` at port 1 — a refusal, not a
    world — so the ambient suite has no search index whatever this checkout's
    `.env` says (before that pin the engine read
    `os.environ` and every test dialled the developer's own address, which is
    how a black-holed `.env` came to hang the machinery suite for 22 seconds).

    A test whose SUBJECT is the real engine therefore has to say so, and this is
    where it says it: the environment is read **here, in a fixture**, and put on
    settings for the duration. That is the same shape
    `apps/files/tests/conftest.py::bucket` uses for MinIO, and the reason
    `config/settings/test.py` gives for the pattern — a test that wants the
    world names it, instead of inheriting whichever one it woke up in.

    Reading `os.environ` in a test module is outside house rule 33's fence by
    the rule's own scope (it walks `apps/` and `config/` for *production*
    modules and allow-lists `apps/search/tests/`), and it is the only way left
    to ask "does this checkout have an organ at all" now that settings will
    never say so.

    **And it asks the engine rather than trusting the variables.** An address
    alone is not an organ: the compose container runs WITH a master key, so a
    checkout that sets
    `MEILI_URL` and leaves `MEILI_MASTER_KEY` empty gets a reachable engine that
    refuses every request with `401 invalid_api_key` — and the live tests then
    fail six different ways that all look like product defects and none of which
    are. Measured: six failures and two errors across this app on exactly that
    configuration. A credential the checkout does not hold is the same fact as
    an organ the checkout does not have, so it is the same skip, with a message
    that says which half is missing.
    """
    url = os.environ.get("MEILI_URL", "").strip()
    if not url:
        pytest.skip("no MEILI_URL — the search organ is not configured for this checkout")
    settings.MEILI_URL = url
    settings.MEILI_MASTER_KEY = os.environ.get("MEILI_MASTER_KEY", "").strip()

    from apps.search import engine as engine_module
    from apps.search.types import EngineUnavailable

    try:
        # A missing index answers `exists=False` and is not an error, so this
        # asks exactly one question — "will this engine talk to us at all" —
        # and nothing about any index. An auth refusal is the failure it is
        # here to catch, and an unreachable address is caught by the same call.
        engine_module.MeiliEngine().state(label="djb-organ-probe")
    except EngineUnavailable as refused:
        pytest.skip(
            f"MEILI_URL is set to {url} but the engine refused a read ({refused}). "
            "The compose container runs with a master key — set MEILI_MASTER_KEY "
            "in this checkout's .env (see .env.example) or unset MEILI_URL."
        )
    return url


@pytest.fixture
@organ("meili")
def live_label(live_meili: str) -> str:
    """A kind name no other test or worker can collide with.

    **An organ fixture** (`apps/conftest.py`): asking for a label nothing else
    can collide with is how a test says it is about to index into the REAL
    compose Meilisearch, so every test that reaches this is derived into the
    `--loop` slow tier and runs at push instead of in the rung.

    It depends on `live_meili`, which is what actually arms the engine — so
    every live test in this app got the arming with no edit of its own when the
    settings pin landed. That is deliberate: six modules each remembering to arm
    it is six places to forget, and the one they all already ask for is here.

    The index prefix is derived from `DATABASE_NAME`, which every xdist worker
    in a checkout shares — so two workers reconciling `widgets` at the same
    instant would be two rebuilds of one index. A per-test label makes the live
    tests as parallel-safe as the rest of the suite.
    """
    return f"probe{uuid4().hex[:12]}"
