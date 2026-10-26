"""The product's fixture drawer."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core import context
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import add_membership, create_tenant, root_organization
from apps.testing._hub import PASSWORD


# --- the product's fixture drawer -------------------------------------------
#
# WHAT THIS IS FOR. This file is template-owned (`quality/partition.yaml`
# class C2): a product that edits it invalidates the platform partition, and
# the first consumer of this template added 609 lines of its own fixtures here
# because there was nowhere else to put a fixture every one of its apps needs.
# `apps/<x>/tests/conftest.py` is scoped by directory ancestry, so it cannot
# serve a product-wide fixture; the root conftest can, and it is mine.
#
# So: `apps/conftest_local.py` is the drawer. It is product-owned and it is
# DISCOVERED — the template never writes it and a product never edits this
# line. The template must never SHIP one either: the publication manifest's
# reserved-path rule is where that is enforced, and this exact path belongs
# on it.
#
# ABSENT IS BYTE-IDENTICAL: no module, no `pytest_plugins`, the collected set
# unchanged.
#
# PRESENT, IT MOVES THE PARTITION KEY, and that is honest rather than
# unfortunate. `pytest_plugins` loads the drawer for the WHOLE session, so an
# `autouse=True` fixture in it runs inside every PLATFORM test as well as the
# product's own — measured: a drawer autouse fixture errors
# `apps/core/tests/test_refusals.py`. A product's drawer can therefore change
# what the platform suite answers, so class C2 names this path as a member and
# a drawer invalidates a banked verdict exactly as an edit to THIS file does.
# The design's "never invalidates a banked verdict" could not be honoured
# honestly and is withdrawn.
#
# ON A NAME CLASH, THIS FILE WINS AND SAYS NOTHING. A conftest's own fixtures
# take precedence over a plugin's, so a drawer fixture sharing a name with one
# below is silently ignored — no warning, no error, the template's version
# used. Give a drawer fixture a name this file does not use.
#
# ONE KNOWN EDGE, since it is pytest's and not ours. `pytest_plugins` in a
# conftest that is not the ROOTDIR's is refused by pytest — but only when that
# conftest is loaded after configure, which happens when the rootdir itself is
# the argument (`pytest .`). Every way this tree is actually run makes
# `apps/conftest.py` an INITIAL conftest and is unaffected: a bare `pytest`
# (`testpaths = ["apps"]`), any `pytest apps/...`, `scripts/test.sh`, and both
# gate legs. A product that runs `pytest .` and has a drawer will see that
# refusal; it runs `pytest apps` instead.
#
# WHY `find_spec` AND NOT A BARE `try: import ... except ImportError: pass`.
# The two disagree exactly when the drawer is BROKEN. A try/except around the
# import cannot tell "there is no drawer" from "the drawer raised ImportError
# on line 40", so a product whose fixtures stopped loading would see every one
# of its tests fail with `fixture not found` and nothing naming the cause.
# `find_spec` answers only the question we are actually asking — does the
# module exist — and then pytest imports it, so a broken drawer is a LOUD
# ImportError (or SyntaxError) naming `apps/conftest_local.py`, never a silent
# absence. `find_spec` locates; it does not execute, and it does not compile.
def __getattr__(name: str) -> list[str]:
    """`pytest_plugins` names the drawer iff it exists; absent, the attribute is absent too."""
    # rule-88: the drawer is a test module beside the harness, never an installed app
    if name == "pytest_plugins" and importlib.util.find_spec("apps.conftest_local") is not None:
        return ["apps.conftest_local"]
    raise AttributeError(name)


# --- the shared fixtures: the context, the Temporal guard, tenants, users, actors ---


@pytest.fixture(autouse=True)
def _clean_context() -> Iterator[None]:
    """No test inherits the last one's ambient context.

    `contextvars` are per-task and pytest runs every test on the same one, so a
    test that drives a middleware directly (rather than through the client)
    would otherwise leave `tenant_id` and `door` bound for whatever runs next —
    and a test that passes because of the previous test is worse than one that
    fails.

    **And a test stands where a door stands.** A correlation chain is bound at
    a door and never minted below one (`core.context.child_of_current` refuses
    with `ContextUnbound`), and a test that calls a service directly IS the
    door of that call — so each test starts with a fresh chain bound, exactly
    as `core.management.BaseCommand` binds one for a command. A test proving
    the unbound refusal clears the context itself.
    """
    context.clear()
    context.bind(request_id=context.new_id(), correlation_id=context.new_correlation_id())
    yield
    context.clear()


@pytest.fixture(autouse=True)
def _no_dialling_temporal(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test reaches a Temporal server it did not start itself.

    `start_workflow_on_commit` registers an `on_commit` hook that builds a
    client from settings and starts a durable run. In a `transaction=True` test
    that commit is real, so the hook fired against the **development server**:
    the cycle-0 verifier measured twenty executions leaked per gate run and 275
    stuck RUNNING, each one a worker somewhere retrying an activity against a
    row that only ever existed inside a test (queue V3).

    Making it impossible rather than discouraged is the point. The factory is
    replaced with one that refuses and says what to do instead; a test that
    genuinely needs a server starts its own time-skipping
    `WorkflowEnvironment` and points the factory at *that*, which is the
    existing per-module pattern (`apps/example/tests/test_workflows.py`,
    `apps/workflows/tests/test_services.py`) and is now also the opt-in: their
    `monkeypatch.setattr` runs inside the test body, after this fixture, and
    replaces the refusal.

    `config/settings/test.py` points `TEMPORAL_ADDRESS` at a dead port as the
    second layer, for anything that builds a client without going through here.

    **The on-commit hook is intercepted too, so the refusal is quiet there.** A
    `transaction=True` test whose service starts a workflow commits for real,
    and the hook's dial met the refusal inside Django's `robust` handler — which
    swallowed it and logged an ERROR per start, the noise the second pytest
    pass's log carried. Every module that bound `apps.core.asyncdb.run_async`
    (the hooks' one way into a loop) gets a wrapper here that answers a
    `TemporalNotDialled` as "nothing was started" and re-raises anything else;
    a direct `await get_client()` outside a hook still raises it, loudly.
    """
    from apps.core import asyncdb
    from apps.workflows import client as workflow_client

    async def refuse(*args: object, **kwargs: object) -> object:
        raise TemporalNotDialled(
            "tests must not dial Temporal — use the time-skipping env or monkeypatch start"
        )

    monkeypatch.setattr(workflow_client, "get_client", refuse)

    blocking = asyncdb.run_async

    def run_async_undialled(make_coroutine: Callable[[], Any]) -> Any:
        """`run_async`, where a refused dial is a start that did not happen."""
        try:
            return blocking(make_coroutine)
        except TemporalNotDialled:
            return None

    for name, module in list(sys.modules.items()):
        if name.startswith("apps.") and getattr(module, "run_async", None) is blocking:
            monkeypatch.setattr(module, "run_async", run_async_undialled)


class TemporalNotDialled(RuntimeError):
    """A test reached for the deployment's Temporal client; `_no_dialling_temporal` refuses it."""


@pytest.fixture
def recorded_workflow_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Commit work that starts a workflow, without a Temporal server.

    The opt-in for a `transaction=True` test whose subject is **not** the
    workflow — a service that happens to call `start_workflow_on_commit`, an
    `emit()` whose dispatch is proved elsewhere. The `WorkflowRun` row is still
    written in the caller's transaction and the `on_commit` hook still fires;
    what does not happen is the client call at the end of it.

    A test whose subject *is* the workflow does the other thing instead: it
    starts a time-skipping `WorkflowEnvironment` and points the factory at it
    (`apps/example/tests/test_workflows.py`, `apps/workflows/tests/test_services.py`),
    which proves the start rather than skipping it. Pick by what the test is
    about; neither of them reaches the development server.

    The seam is `run_async`, which is the one thing the on-commit hook does
    that a test cannot want: give the client call its own event loop. Everything
    above it — the id check, the `WorkflowRun` row, the hook being registered on
    the right transaction — still runs, so what this skips is exactly the dial.
    """
    from apps.workflows import services as workflow_services

    def do_not_dispatch(_coroutine_factory: Callable[[], Any]) -> None:
        return None

    monkeypatch.setattr(workflow_services, "run_async", do_not_dispatch)


@pytest.fixture
def api() -> Client:
    return Client()


@pytest.fixture
def tenant(db: None) -> Tenant:
    return create_tenant(name="Acme", slug="acme", actor=system_actor())


@pytest.fixture
def other_tenant(db: None) -> Tenant:
    return create_tenant(name="Globex", slug="globex", actor=system_actor())


@pytest.fixture
def root_org(tenant: Tenant) -> Organization:
    """The tenant's root node — made by `create_tenant`, never by a test."""
    return root_organization(tenant=tenant)


@pytest.fixture
def other_root_org(other_tenant: Tenant) -> Organization:
    return root_organization(tenant=other_tenant)


@pytest.fixture
def owner(tenant: Tenant) -> User:
    """The tenant's owner, said out loud.

    `add_membership` defaults the *first* membership of a tenant to `owner` and
    everybody after it to `member` (`core.services`), which is the right
    default for a product and the wrong one for a fixture: whether this user
    came out an owner would depend on whether a test happened to ask for
    `member` or `admin_member` first, and pytest builds fixtures in the order a
    signature names them. A test that passes because of its argument order is a
    test nobody can move. So every fixture here names its role, and the default
    keeps its own test (`core/tests/test_authz.py`) instead of being proved by
    accident here.
    """
    user = create_user(email="owner@example.com", password=PASSWORD)
    add_membership(
        user=user,
        tenant=tenant,
        is_default=True,
        role=Membership.Role.OWNER,
        actor=system_actor(tenant=tenant),
    )
    return user


@pytest.fixture
def stranger(other_tenant: Tenant) -> User:
    """The owner of the *other* tenant — same reasoning, same explicit role."""
    user = create_user(email="stranger@example.com", password=PASSWORD)
    add_membership(
        user=user,
        tenant=other_tenant,
        is_default=True,
        role=Membership.Role.OWNER,
        actor=system_actor(tenant=other_tenant),
    )
    return user


@pytest.fixture
def nomad(db: None) -> User:
    """A real, active user who belongs to no tenant at all."""
    return create_user(email="nomad@example.com", password=PASSWORD)


@pytest.fixture
def root(db: None) -> User:
    """A superuser with no membership. Tenancy has no exemption for it."""
    return create_user(email="root@example.com", password=PASSWORD, is_superuser=True)


@pytest.fixture
def member(tenant: Tenant) -> User:
    """A second person in the same tenant, with the least privileged role.

    The pair is what every authorization test needs: the same tenant, the same
    rows, two different answers — and which is which does not depend on the
    order the test's signature happens to name them in.
    """
    user = create_user(email="member@example.com", password=PASSWORD)
    add_membership(
        user=user,
        tenant=tenant,
        is_default=True,
        role=Membership.Role.MEMBER,
        actor=system_actor(tenant=tenant),
    )
    return user


@pytest.fixture
def admin_member(tenant: Tenant) -> User:
    """Someone in the tenant with the `admin` role."""
    user = create_user(email="admin@example.com", password=PASSWORD)
    add_membership(
        user=user,
        tenant=tenant,
        is_default=True,
        role=Membership.Role.ADMIN,
        actor=system_actor(tenant=tenant),
    )
    return user


@pytest.fixture
def owner_actor(owner: User, tenant: Tenant, root_org: Organization) -> Actor:
    """The owner, wearing the tenant's root as their hat.

    Every actor fixture names its hat for the same reason each names its role:
    an actor with `org=None` reads nothing from an org-scoped table, so a test
    that forgot would pass or fail for a reason it never stated.
    """
    return actor_for(user=owner, tenant=tenant, org=root_org)


@pytest.fixture
def member_actor(member: User, tenant: Tenant, root_org: Organization) -> Actor:
    return actor_for(user=member, tenant=tenant, org=root_org)


@pytest.fixture
def admin_actor(admin_member: User, tenant: Tenant, root_org: Organization) -> Actor:
    return actor_for(user=admin_member, tenant=tenant, org=root_org)


@pytest.fixture
def stranger_actor(stranger: User, other_tenant: Tenant, other_root_org: Organization) -> Actor:
    return actor_for(user=stranger, tenant=other_tenant, org=other_root_org)
