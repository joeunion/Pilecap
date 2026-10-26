"""Search's test world: core's `build_world` with a widget at three nodes, and two planted kinds.

One kind org-scoped, one tenant-scoped: a single shape cannot tell a correct filter injection.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from django.core.cache import cache

from apps.conftest import organ
from apps.core.actor import actor_for
from apps.core.models import Organization
from apps.core.tests.permissions_world import World as World
from apps.core.tests.permissions_world import build_world
from apps.example.models import Widget
from apps.example.services import create_widget
from apps.search import registry
from apps.search.types import RecordingEngine, Searchable

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


@pytest.fixture(autouse=True)
def _a_closed_circuit() -> Iterator[None]:
    """Every search test starts and ends with the circuit closed: its state lives in the cache."""
    from apps.search import selectors

    keys = [selectors.COOLDOWN_KEY, selectors.DEGRADED_KEY]
    cache.delete_many(keys)
    yield
    cache.delete_many(keys)


@pytest.fixture
def world() -> World:
    """Core's world (`root → A → A1 → A1X`, sibling `B`) with one widget at the root, A and B."""
    built = build_world()
    homes = (("root", built.owner, built.root), ("A", built.admin_at_a, built.a))
    for label, who, org in (*homes, ("B", built.owner, built.b)):
        acting = actor_for(user=who.user, tenant=built.tenant, org=org)
        create_widget(tenant=built.tenant, actor=acting, name=f"Widget at {label}")
    return built


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
