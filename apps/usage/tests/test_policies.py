"""The named permission: declared once, consulted by `can()`, narrowed by an edit.

**Owner-ruled** (`design-agreements.md` § Usage visibility).
An earlier finding found that a plain member wearing the root hat reads the
tenant-wide bill, and that this was true because of an argument in a docstring
rather than a decision anybody could find or change. The ruling was not "narrow
it" — it was "declare it": the default stays exactly as it was, and a product
that wants a different bar edits one line instead of forking `policies.py`.

So there are two properties here and they pull against each other, which is why
both are asserted:

* **a fresh clone behaves exactly as today** — every role this deployment has
  reads the report. If this ever goes red on a template checkout, somebody has
  narrowed the platform's default, which is a product decision the platform is
  not allowed to make for anybody;
* **a narrowing works, end to end, at the door** — flip the declaration's roles
  and a member is refused over the wire while an owner is not. Without this half
  the declaration could be a decoration `can()` never reads, which is the exact
  shape of the defect this closes.

The narrowing test edits the declaration the way a product would — the module
attribute, then `core.authz.reset_policies()` because the registry is discovered
once and cached — rather than by calling the predicate directly. A test that
called `can()` itself would prove the dataclass works and nothing about whether
`require` reaches it.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import Client

from apps.accounts.services import create_user, issue_token
from apps.core.actor import actor_for
from apps.core.authz import ROLE_RANK, reset_policies
from apps.core.exceptions import Forbidden
from apps.core.models import Membership
from apps.core.services import add_membership
from apps.usage import policies
from apps.usage.api import _window
from apps.usage.policies import ALL_ROLES, USAGE_READ_REPORT, declared_permission
from apps.usage.selectors import get_usage
from apps.usage.tests.conftest import PASSWORD, World
from apps.usage.types import PeriodKind

pytestmark = pytest.mark.django_db

URL = "/api/v1/usage/"


@pytest.fixture(autouse=True)
def _registry_restored() -> Iterator[None]:
    """The policy registry is process-wide and cached. Drop it around every test.

    Without this a narrowing planted by one test is the bar every later test in
    the session is measured against — and the failure would land in somebody
    else's module, which is the worst place for it to land.
    """
    reset_policies()
    yield
    reset_policies()


def _bearer(plaintext: str) -> dict[str, str]:
    return {"authorization": f"Bearer {plaintext}"}


def _body(response: Any) -> dict[str, Any]:
    return dict(json.loads(response.content))


# --- 1 · the declaration itself -----------------------------------------------


def test_the_read_is_one_named_permission_and_the_name_is_declared_once() -> None:
    """One action, spelled in one place, and the app publishes it as its policy.

    The action name is asserted as a literal here and NOWHERE else in the app:
    `selectors.get_usage` names the declaration rather than the string, which is
    what makes a rename a one-line change instead of a silent hole.
    """
    assert USAGE_READ_REPORT.action == "usage.read_report"
    assert set(policies.POLICIES) == {USAGE_READ_REPORT.action}
    assert set(policies.ACTION_PROSE) == {USAGE_READ_REPORT.action}


def test_all_roles_is_derived_from_the_one_place_roles_are_ranked() -> None:
    """`ALL_ROLES` is the role vocabulary, not a copy of it.

    A hand-listed tuple would be the second spelling of the same set, and the
    day a product added a fourth role the quieter one would win: the new role
    would silently be outside "all".
    """
    assert ALL_ROLES == frozenset(ROLE_RANK)
    assert USAGE_READ_REPORT.roles == ALL_ROLES


@pytest.mark.parametrize("bad", [(), ("wizard",), ("owner", "wizard")])
def test_a_declaration_this_deployment_cannot_satisfy_refuses_at_import(
    bad: tuple[str, ...],
) -> None:
    """A narrowing nobody can satisfy fails loudly rather than refusing everybody.

    Both shapes: a role that does not exist (a typo in a product's edit) and the
    empty set (deleting the capability by declaration instead of by deleting the
    door). Either one would otherwise be a route answering 403 to every caller
    with nothing in the tree saying why.
    """
    with pytest.raises(ImproperlyConfigured):
        declared_permission(action="usage.read_report", default_roles=bad)


# --- 2 · a fresh clone behaves exactly as today -------------------------------


@pytest.mark.parametrize(
    "role", [Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.MEMBER]
)
def test_a_fresh_clone_lets_every_role_read_the_report(
    world: World, role: str, a_declared_meter: str
) -> None:
    """**The parity pin.** Every role reads, exactly as before the declaration.

    Parametrized over the three roles by name rather than looped over
    `ALL_ROLES`, deliberately: a product that adds a fourth role should have to
    come here and say what it decided about the bill, and a test that walked the
    set would silently answer for them.
    """
    person = create_user(email=f"{role}-reads@acme.com", password=PASSWORD)
    add_membership(
        user=person,
        tenant=world.tenant,
        organization=world.root,
        is_default=True,
        role=role,
        actor=world.root_actor,
    )

    report = get_usage(
        tenant=world.tenant,
        actor=actor_for(user=person, tenant=world.tenant, org=world.root),
        period=_window(period=PeriodKind.MONTH, on=None),
    )

    assert report == {}, "an empty ledger is the answer; being REFUSED is not"


def test_the_roles_are_the_declaration_and_not_a_membership_check(world: World) -> None:
    """`can()` consults the declaration — proved by narrowing it and watching it bite.

    At the predicate level first, because the wire test below can only fail one
    way and this one says which: the member still holds the identical membership
    and is refused anyway, so what changed is the declared set and nothing else.
    """
    member = create_user(email="narrowed-member@acme.com", password=PASSWORD)
    add_membership(
        user=member,
        tenant=world.tenant,
        organization=world.root,
        is_default=True,
        role=Membership.Role.MEMBER,
        actor=world.root_actor,
    )
    acting = actor_for(user=member, tenant=world.tenant, org=world.root)

    assert USAGE_READ_REPORT.can(acting) is True
    narrowed = declared_permission(
        action=USAGE_READ_REPORT.action,
        default_roles=(Membership.Role.OWNER, Membership.Role.ADMIN),
    )
    assert narrowed.can(acting) is False


# --- 3 · the narrowing reaches the door ---------------------------------------


def test_a_product_narrows_by_editing_the_declaration_and_the_door_obeys(
    api: Client, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole of that promise, driven at the door a customer uses.

    A product narrows `USAGE_READ_REPORT` to owners and admins — one line in
    `policies.py`, no fork, no `core` edit — and from that moment a member is
    refused the bill over the wire while an owner still reads it. Both halves,
    because a narrowing that refused everybody would pass the first assertion
    alone.

    The refusal is the app's own declared sentence and never the action name:
    `usage.read_report` is a key a service asks a question with, and a caller
    told to go and read our source is the plain-language finding FT-1 booked.
    """
    member = create_user(email="member-at-the-door@acme.com", password=PASSWORD)
    add_membership(
        user=member,
        tenant=world.tenant,
        organization=world.root,
        is_default=True,
        role=Membership.Role.MEMBER,
        actor=world.root_actor,
    )
    _, member_token = issue_token(
        user=member,
        tenant=world.tenant,
        name="member",
        scopes=["usage:read"],
        actor=actor_for(user=member, tenant=world.tenant),
    )
    _, owner_token = issue_token(
        user=world.owner,
        tenant=world.tenant,
        name="owner",
        scopes=["usage:read"],
        actor=actor_for(user=world.owner, tenant=world.tenant),
    )

    narrowed = declared_permission(
        action=USAGE_READ_REPORT.action,
        default_roles=(Membership.Role.OWNER, Membership.Role.ADMIN),
    )
    monkeypatch.setattr(policies, "USAGE_READ_REPORT", narrowed)
    monkeypatch.setattr(policies, "POLICIES", {narrowed.action: narrowed.can})
    reset_policies()

    refused = api.get(URL, headers=_bearer(member_token))
    allowed = api.get(URL, headers=_bearer(owner_token))

    assert refused.status_code == 403, refused.content
    body = _body(refused)
    assert body["code"] == "forbidden"
    assert USAGE_READ_REPORT.action not in body["detail"], body
    assert "usage" in body["detail"].lower(), body
    assert allowed.status_code == 200, allowed.content


def test_a_narrowed_declaration_refuses_the_selector_and_not_only_the_door(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusal is `require`'s, reached through the real registry.

    The door test above proves the status code; this one proves WHERE it comes
    from — `selectors.get_usage` asks `require(actor, USAGE_READ_REPORT.action)`
    and the discovered registry hands back the narrowed predicate. A door that
    had grown its own role check would still answer 403 up there and would leave
    this green for the wrong reason, so both are asserted.
    """
    member = create_user(email="member-in-the-selector@acme.com", password=PASSWORD)
    add_membership(
        user=member,
        tenant=world.tenant,
        organization=world.root,
        is_default=True,
        role=Membership.Role.MEMBER,
        actor=world.root_actor,
    )
    narrowed = declared_permission(
        action=USAGE_READ_REPORT.action, default_roles=(Membership.Role.OWNER,)
    )
    monkeypatch.setattr(policies, "POLICIES", {narrowed.action: narrowed.can})
    reset_policies()

    with pytest.raises(Forbidden):
        get_usage(
            tenant=world.tenant,
            actor=actor_for(user=member, tenant=world.tenant, org=world.root),
            period=_window(period=PeriodKind.MONTH, on=None),
        )
