"""The resolution invariants, as three DERIVED censuses rather than three cases.

**Why these are pytest and not house rules.** Each one is a claim about what
`core.authz` and `core.middleware` ANSWER, over a world that exists — rows, a
database, a request. A house rule reads the tree; none of these can be read off
it. They live beside `flat_product_census` for the same reason it does.

**What each derives its population from, said once:**

* (a) `role_declarations()` — every role this deployment declares — PLUS a
  write-only role this test plants through the same discovery walk, because on
  a template carrying only `admin` (`("*",)`) and `member` (`("*.read",)`) the
  assertion is nearly vacuous: two roles whose patterns cover the vocabulary
  cannot show a key held beyond the declaration. The plant is what makes it
  falsifiable.
* (b) `dataclasses.fields(World)` — every field typed `Actor` is an actor, every
  field typed `Organization` is a node. A world that grows a seventh person is
  in the cross product on the run it grows one, and nobody edits a list here.
* (c) `Tenant.Status` minus `ACTIVE`, times the credential kinds, times the
  doors — and the doors are IMPORTED from `test_addressing_headers.DOOR_COVERAGE`
  rather than re-typed, so a door added tomorrow is in this census too.

**What they do NOT see, declared:**

* (a) judges the SHAPE of a collection, never whether a declared role's
  patterns are the right patterns — that is the product's own taste.
* (b) drives two worlds in ONE deployment. A person holding memberships in two
  tenants is a different question (`effective_permissions` takes one tenant),
  named here and not driven.
* (c) drives the session and the two bearer kinds at the REST and MCP doors.
  The SOCKET doors (`apps/core/asgi_middleware.py`, `apps/realtime/middleware.py`)
  are named in `DOOR_COVERAGE` and are driven in
  `apps/realtime/tests/test_addressing_headers.py`, whose harness owns the
  channels transport; this module asserts the RESOLVER both of them call and
  says so rather than pretending to a coverage it does not have. The
  OAuth-JWT credential kind is the standing UNDRIVEN cell of the addressing
  census, for its reason, and it is undriven here too.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.services import authenticate_token, issue_token
from apps.core import authz
from apps.core.authz import (
    OWNER_ROLE,
    DeclaredRole,
    collection,
    defaults_for,
    effective_permissions,
    effective_role,
    read_kinds,
    role_declarations,
    vocabulary,
)
from apps.core.middleware import resolve_tenant
from apps.core.models import Tenant
from apps.core.tests.permissions_world import World, build_world
from apps.core.tests.test_addressing_headers import DOOR_COVERAGE

pytestmark = pytest.mark.django_db

JSON = "application/json"

#: The role this test splices in: it holds a WRITE and no read, which is the
#: one shape neither template role has and the only shape that can show a
#: residue that is not simply "everything".
PLANTED_ROLE = "canary_scribe"


def _predicate_keys() -> set[str]:
    """Every key whose answer is also a question about a ROW.

    The keys whose answer a predicate narrows beyond the collection. Derived from
    the vocabulary, never listed; the compat residue that once added these to
    every role's collection is retired.
    """
    return {key for key, word in vocabulary().items() if word.predicate is not None}


def test_every_declared_role_holds_its_declaration_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(a) A role holds what it was declared, and nothing else.

    Two claims in one census, and the second is the one that pays: for every
    key that has NO predicate, `collection` and `defaults_for` agree exactly.
    A key that appeared in one and not the other would be a capability a role
    holds that nobody declared, or one it was declared and does not hold — and
    both were live defects before the pair became a belt.
    """
    from apps.core import roles as core_roles

    monkeypatch.setitem(
        core_roles.ROLES,
        PLANTED_ROLE,
        DeclaredRole(
            key=PLANTED_ROLE,
            name="Scribe",
            permissions=("widget.create", "widget.update"),
            description="Planted: a role that writes and reads nothing.",
        ),
    )
    authz.reset_policies()
    try:
        predicates = _predicate_keys()
        words = vocabulary()
        declared_roles = sorted(role_declarations())
        assert PLANTED_ROLE in declared_roles, (
            "the plant did not reach the discovery walk, so this census is measuring "
            "the template's two roles and cannot fail"
        )
        for key in [*declared_roles, OWNER_ROLE]:
            held = collection(None, key)
            declared = defaults_for(key)
            residue = held - declared
            print(
                f"role {key}: holds {len(held)} · declared {len(declared)} · "
                f"residue {len(residue)} -> {sorted(residue)[:8]}"
            )
            assert residue == set(), (
                f"the role {key!r} holds {sorted(residue)} that nothing declared — "
                "a capability arriving from outside the declaration is one nobody can trace"
            )
            for action in sorted(words):
                if action in predicates:
                    continue
                assert (action in held) == (action in declared), (
                    f"{key!r} and {action!r}: collection says {action in held} and "
                    f"defaults_for says {action in declared}. For a key with no predicate "
                    "the two are the same sentence read twice, and a disagreement is one "
                    "of them being wrong about what a role may do"
                )
        # NON-VACUITY: the planted role's own residue is not the whole vocabulary,
        # which is what a role holding `("*",)` would show and what makes the
        # template's two roles unable to fail this.
        planted = collection(None, PLANTED_ROLE)
        assert "widget.create" in planted
        assert "organization.create" not in planted
    finally:
        monkeypatch.undo()
        authz.reset_policies()


def _fields_typed(name: str) -> list[str]:
    """Every `World` field annotated `name`. The population, derived.

    Read as the ANNOTATION STRING because the module carries
    `from __future__ import annotations`, so the dataclass holds the text a
    person wrote rather than a class object. That is the honest read: what the
    world DECLARES a field to be is what makes it an actor or a node here.
    """
    return [field.name for field in dataclasses.fields(World) if field.type == name]


def test_a_foreign_tenant_node_holds_nothing_for_every_actor() -> None:
    """(b) Nobody holds anything at a node of a tenant they are not in.

    The whole cross product, derived: every actor of one world against every
    node of the other. It is the assertion tenancy is supposed to make and the
    one nothing was making — `effective_permissions` narrows by membership, and
    a membership is per tenant, so the answer is the empty set for structural
    reasons. Structural reasons are exactly the ones that stop being true
    quietly.
    """
    mine = build_world()
    theirs = build_world()
    actor_fields = _fields_typed("Actor")
    node_fields = _fields_typed("Organization")
    assert actor_fields and node_fields, "the world grew no actors or no nodes"
    print(f"cross product: {len(actor_fields)} actor(s) x {len(node_fields)} foreign node(s)")

    for actor_name in actor_fields:
        actor = getattr(mine, actor_name)
        for node_name in node_fields:
            node = getattr(theirs, node_name)
            held = effective_permissions(actor.user, theirs.tenant, node)
            assert held == frozenset(), (
                f"{actor_name} of one tenant holds {sorted(held)[:5]} at {node_name} of "
                "another — a permission across a tenant boundary is the one thing "
                "tenancy exists to make impossible"
            )
            assert effective_role(actor.user, theirs.tenant, node) is None, (
                f"{actor_name} resolves a ROLE at {node_name} of a foreign tenant"
            )
            assert read_kinds(actor.user, theirs.tenant, node) == frozenset(), (
                f"{actor_name} may read kinds at {node_name} of a foreign tenant"
            )

    # NON-VACUITY, in the same shape: the HOME cell is not empty, so a census
    # that had stopped resolving anything at all could not pass this.
    at_home = effective_permissions(mine.owner.user, mine.tenant, mine.root)
    assert at_home, "the owner holds nothing at their own root — this census resolves nothing"


#: Every status that is not the live one, derived from the enum rather than
#: listed: a product that adds a fourth is in this census on the run it adds it.
NON_ACTIVE_STATUSES = [s for s in Tenant.Status if s != Tenant.Status.ACTIVE]


@pytest.mark.parametrize("status", NON_ACTIVE_STATUSES, ids=lambda s: str(s.value))
def test_every_non_active_status_resolves_nowhere_at_every_door(status: Any) -> None:
    """(c) A dark tenant resolves nowhere, through every credential kind.

    Suspension is an operator's act that takes a tenant dark, and a credential
    that kept working into it would make the act a suggestion. The three kinds
    are driven because they resolve by three different paths: a session through
    `resolve_tenant`, an UNPINNED token through the same, and a PINNED token
    through `authenticate_token`, which authenticates and then resolves nowhere
    — authenticated-then-refused, never a false 401 over a live credential.
    """
    world = build_world()
    # `Actor.user` is typed `AbstractBaseUser | None` and the column is the
    # concrete model; the narrowing is real at runtime and unprovable here,
    # which is what this assert and the ignore below say between them.
    owner_user = world.owner.user
    assert isinstance(owner_user, User)
    _row, plaintext = issue_token(
        user=owner_user,
        tenant=world.tenant,
        name="census",
        actor=world.owner,
        scopes=["roles:read"],
    )
    # THE CONTROL, ASSERTED BEFORE THE FLIP, and it is not a formality: with
    # `requested_slug=None` this resolver reads the DEFAULT membership, and the
    # world's memberships carry no default — so that branch answers `None` for
    # an active tenant too and an assertion built on it would pass whatever the
    # status was. Measured, not assumed: the severed probe that should have
    # reddened on an ACTIVE tenant passed. The slug branch is the one with a
    # control, so the control is taken first and the census is self-checking.
    assert resolve_tenant(user=world.owner.user, requested_slug=world.tenant.slug) is not None, (
        "the control failed: an ACTIVE tenant does not resolve for its own owner by slug, "
        "so the assertion below could not tell a dark tenant from a vacuous one"
    )
    before = authenticate_token(plaintext=plaintext)
    assert before is not None and before.tenant is not None, (
        "the control failed: a pinned token to an ACTIVE tenant resolves nowhere"
    )

    Tenant.objects.filter(pk=world.tenant.pk).update(status=status)
    world.tenant.refresh_from_db()
    assert not world.tenant.is_active

    # THE RESOLVER BOTH SESSION DOORS CALL, and the one the socket doors call
    # too — which is what lets this module assert about doors it does not drive.
    assert resolve_tenant(user=world.owner.user, requested_slug=world.tenant.slug) is None, (
        f"a {status.value} tenant still resolves when asked for by slug"
    )
    assert resolve_tenant(user=world.owner.user, requested_slug=None) is None, (
        f"a {status.value} tenant still resolves through the default membership"
    )

    # THE PINNED BEARER: authenticated, and nowhere.
    authenticated = authenticate_token(plaintext=plaintext)
    assert authenticated is not None, (
        "a live token to a dark tenant must AUTHENTICATE — a 401 over a real "
        "credential belonging to a real user is a false sentence (E9)"
    )
    assert authenticated.tenant is None, (
        f"a token pinned to a {status.value} tenant still resolves it"
    )

    # AND OVER THE WIRE, once per door this module can reach. The two socket
    # doors in DOOR_COVERAGE are driven in apps/realtime's own addressing
    # module; they are named here so the gap is a sentence and not a silence.
    driven = {"apps/core/middleware.py", "apps/accounts/auth.py", "config/mcp.py"}
    undriven = sorted(set(DOOR_COVERAGE) - driven)
    print(f"doors driven here: {sorted(driven)}; resolver-only: {undriven}")
    assert driven <= set(DOOR_COVERAGE), (
        "a door this census drives is no longer in the addressing census's own map — "
        "the two have come apart and one of them is wrong"
    )

    rest = Client()
    answer = rest.get(reverse("api:role-list"), headers={"Authorization": f"Bearer {plaintext}"})
    assert answer.status_code in (401, 403), (
        f"the REST bearer door answered {answer.status_code} for a {status.value} tenant"
    )
    body = json.loads(answer.content or b"{}")
    assert world.tenant.slug not in json.dumps(body), (
        "the refusal named the tenant — a dark tenant must not be confirmed to exist "
        "by the words of its own refusal (ADR core-21)"
    )
