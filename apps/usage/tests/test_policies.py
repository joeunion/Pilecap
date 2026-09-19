"""Narrowing the bill is DATA now, and this module is where that becomes true.

**What this module used to be, and why it changed shape.** An owner ruling
(`design-agreements.md` § Usage visibility) found that a plain member wearing the
root hat read the tenant-wide bill *because of an argument in a docstring*, and
ruled: do not narrow it — DECLARE it, so the default is a line somebody can find
and change. `apps/usage/policies.py` grew a `DeclaredPermission` to carry that,
and these tests pinned it.

P20 answered the same question for the whole platform, one layer down, so the
declaration's job is now the vocabulary's and the narrowing's job is now a
tenant's own rows. The ruling is kept in every respect that mattered and
strengthened in the one that mattered most:

* **the default is still visible** — `usage_entry.read` is a derived key, `member`
  is declared `("*.read",)`, and `manage.py introspect` prints both. Nothing is
  argued in a docstring;
* **narrowing is no longer a fork, an edit or a deploy.** It was "a product edits
  one line in `policies.py`"; it is now "a tenant's administrator writes a row",
  through the role editor's own doors, in a running deployment, audited, per
  tenant instead of per deployment. That is what the tests below drive.

The two properties still pull against each other and both are still asserted: a
fresh clone behaves exactly as it always did, AND a narrowing bites at the door.
The import-refusal tests retired with the class they guarded — a typo in a
narrowing is now `Invalid` from `core`'s own `_refuse_undeclared_permissions`,
which is `apps/core/tests/test_handing_out.py`'s subject and not this app's.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import Client

from apps.accounts.services import create_user, issue_token
from apps.core.actor import actor_for
from apps.core.authz import collection, defaults_for, vocabulary
from apps.core.exceptions import Forbidden
from apps.core.models import Membership, RolePermission
from apps.core.services import add_membership, set_role_collection
from apps.usage.api import _window
from apps.usage.selectors import get_usage
from apps.usage.tests.conftest import PASSWORD, World
from apps.usage.types import PeriodKind

pytestmark = pytest.mark.django_db

URL = "/api/v1/usage/"

#: The key the report is read under. A literal, deliberately: a test that
#: imported the name the selector uses could not tell a rename from a typo.
READ_KEY = "usage_entry.read"


def _bearer(plaintext: str) -> dict[str, str]:
    return {"authorization": f"Bearer {plaintext}"}


def _body(response: Any) -> dict[str, Any]:
    return dict(json.loads(response.content))


def _member(world: World, email: str) -> Any:
    person = create_user(email=email, password=PASSWORD)
    add_membership(
        user=person,
        tenant=world.tenant,
        organization=world.root,
        is_default=True,
        role=Membership.Role.MEMBER,
        actor=world.root_actor,
    )
    return person


# --- 1 · the key is the row's, and it is derived ------------------------------


def test_the_read_is_the_derived_key_of_the_row_the_report_totals() -> None:
    """One key, derived from `UsageEntry`, with this app's sentence on it.

    `decided_by == "derived"` is the assertion that matters: an `ACTION_PROSE`
    entry for a key the registry already produced is a SENTENCE OVERRIDE, not a
    second declaration — so the app still owns what a refused caller reads and
    owns nothing about who holds it.
    """
    word = vocabulary()[READ_KEY]

    assert word.decided_by == "derived"
    assert word.kind == "usage_entry"
    assert word.conforms
    assert "usage" in word.sentence.lower()
    assert word.renamed_from == ("usage.read_report",)


def test_the_old_key_still_answers_as_the_new_one(world: World) -> None:
    """The alias, driven rather than asserted about the table.

    A product still calling `require(actor, "usage.read_report")` — or holding a
    `Grant` row that names it — gets exactly the answer it got before, because
    `allows` resolves the rename one line BEFORE the policy lookup. The cost of
    the whole rename is the one line in `policies.py` that says so.
    """
    from apps.core.authz import allows, renamed_permissions

    assert renamed_permissions()["usage.read_report"] == READ_KEY
    acting = actor_for(user=_member(world, "alias@acme.com"), tenant=world.tenant, org=world.root)
    assert allows(acting, "usage.read_report") is allows(acting, READ_KEY) is True


# --- 2 · a fresh clone behaves exactly as today -------------------------------


@pytest.mark.parametrize(
    "role", [Membership.Role.OWNER, Membership.Role.ADMIN, Membership.Role.MEMBER]
)
def test_a_fresh_clone_lets_every_role_read_the_report(
    world: World, role: str, a_declared_meter: str
) -> None:
    """**The parity pin**, kept verbatim through the re-key. Every role reads.

    Parametrized over the three roles by name rather than looped over a derived
    set, deliberately: a product that adds a fourth role should have to come here
    and say what it decided about the bill, and a test that walked the set would
    silently answer for them.
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


def test_the_template_hands_the_bill_to_member_by_declaration_and_not_by_residue(
    world: World,
) -> None:
    """*Why* a member reads, said where somebody narrowing it would look.

    `member` is `("*.read",)` in `apps/core/roles.py` — the product-editable
    file — so the bill is held by a PATTERN a product can edit, not by the
    compat residue that carries un-swept keys through the transition. Asserted
    because the two look identical from the door and behave differently the day
    a tenant writes a row: the residue is not in `defaults_for`, and a role's
    delta is computed against `defaults_for`.
    """
    assert READ_KEY in defaults_for("member")
    assert READ_KEY in collection(world.tenant, "member")


# --- 3 · the narrowing is a row, and it reaches the door ----------------------


def test_a_tenant_narrows_the_bill_with_an_exclude_row_and_the_door_obeys(
    api: Client, world: World
) -> None:
    """The whole of the ruling's promise, in the form it takes now.

    An administrator takes the bill away from `member` — one `exclude` row on a
    declared role, written by `set_role_collection` through the role editor's
    own service — and from that moment a member is refused over the wire while
    an owner still reads it. Both halves, because a narrowing that refused
    everybody would pass the first assertion alone.

    The refusal is the app's own declared sentence and never the action name:
    `usage_entry.read` is a key a service asks a question with, and a caller
    told to go and read our source is the plain-language finding FT-1 booked.
    """
    member = _member(world, "member-at-the-door@acme.com")
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

    set_role_collection(
        tenant=world.tenant,
        actor=world.root_actor,
        role_key="member",
        permissions=sorted(defaults_for("member") - {READ_KEY}),
    )

    assert (
        RolePermission.objects.for_tenant(world.tenant)
        .filter(role_key="member", permission=READ_KEY, effect=RolePermission.Effect.EXCLUDE)
        .exists()
    ), "the narrowing is a row somebody wrote, not an edit somebody shipped"
    assert READ_KEY not in collection(world.tenant, "member")

    refused = api.get(URL, headers=_bearer(member_token))
    allowed = api.get(URL, headers=_bearer(owner_token))

    assert refused.status_code == 403, refused.content
    body = _body(refused)
    assert body["code"] == "forbidden"
    assert READ_KEY not in body["detail"], body
    assert "usage" in body["detail"].lower(), body
    assert allowed.status_code == 200, allowed.content


def test_the_narrowing_refuses_the_selector_and_not_only_the_door(world: World) -> None:
    """The refusal is `require`'s, reached through the real resolution.

    The door test above proves the status code; this one proves WHERE it comes
    from — `selectors.get_usage` asks `require(actor, "usage_entry.read")` and
    the three layers hand back the tenant's own exclude. A door that had grown
    its own role check would still answer 403 up there and would leave this
    green for the wrong reason, so both are asserted.
    """
    member = _member(world, "member-in-the-selector@acme.com")
    set_role_collection(
        tenant=world.tenant,
        actor=world.root_actor,
        role_key="member",
        permissions=sorted(defaults_for("member") - {READ_KEY}),
    )

    with pytest.raises(Forbidden):
        get_usage(
            tenant=world.tenant,
            actor=actor_for(user=member, tenant=world.tenant, org=world.root),
            period=_window(period=PeriodKind.MONTH, on=None),
        )


def test_a_narrowing_is_per_tenant_and_not_per_deployment(world: World, tenant: Any) -> None:
    """The property the declaration could never have had, asserted as a difference.

    A `RolePermission` row belongs to ONE tenant, so a customer who wanted the
    bill kept to their owners gets that without changing what every other
    customer of the same deployment sees. Under the old shape both tenants were
    narrowed by one edit to one file, and neither could ask for anything else.
    """
    from apps.accounts.services import create_user as make_user
    from apps.core.actor import system_actor
    from apps.core.models import Tenant
    from apps.core.services import create_tenant, root_organization

    other = create_tenant(name="Beta", slug="beta-usage", actor=system_actor())
    assert isinstance(other, Tenant)
    other_root = root_organization(tenant=other)
    neighbour = make_user(email="neighbour@beta.com", password=PASSWORD)
    add_membership(
        user=neighbour,
        tenant=other,
        organization=other_root,
        is_default=True,
        role=Membership.Role.MEMBER,
        actor=system_actor(tenant=other, org=other_root),
    )
    narrowed = _member(world, "narrowed@acme.com")

    set_role_collection(
        tenant=world.tenant,
        actor=world.root_actor,
        role_key="member",
        permissions=sorted(defaults_for("member") - {READ_KEY}),
    )

    with pytest.raises(Forbidden):
        get_usage(
            tenant=world.tenant,
            actor=actor_for(user=narrowed, tenant=world.tenant, org=world.root),
            period=_window(period=PeriodKind.MONTH, on=None),
        )
    assert (
        get_usage(
            tenant=other,
            actor=actor_for(user=neighbour, tenant=other, org=other_root),
            period=_window(period=PeriodKind.MONTH, on=None),
        )
        == {}
    ), "the neighbour tenant wrote no row and reads exactly as before"
