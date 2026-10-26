"""The `accounts` read sweep: three selectors that answered for free now ask.

`apps/accounts/selectors.py` held the last three reads in this tree that
returned a registry kind and asked nothing — `get_member` (a `User`),
`list_sso_connections` and `get_connection_for_email` (both `SsoConnection`).
A read that never asks is a read every door inherits for free: whoever can
reach the route gets the rows, and the only wall left is the tenancy filter,
which answers "whose rows" and never "may you".

Two of them now ask; the third cannot, and says so in a valve rather than in
silence:

* **`get_member` asks `user.read`, REACH FIRST.** The membership filter is what
  makes somebody else's tenant's person `not_found`; the ask is what makes a
  person inside the acting tenant `forbidden` to a hat holding no read. The two
  refusals are different facts and a door that collapsed them would answer
  "does this account exist" to anybody with a session and a supply of ids —
  which is why the order is fetch, then ask, and never the other way round.
* **`list_sso_connections` asks `sso_connection.read` at the HAT.** A list names
  no row, so there is nothing to hide behind an empty page: somebody without
  the read hears that, rather than reading a tenant with an identity provider
  as a tenant with none.
* **`get_connection_for_email` carries `# read-open:`.** It answers the
  home-realm question for a stranger at the login box — before any principal
  exists — so there is nobody to ask, and the valve names the two callers.

**The negatives this file also owes.** Every pre-authentication lookup beside
it is the same shape, and a sweep that gave one of them an `actor` would have
broken the login box for everybody; the census at the bottom reads the valves
off the module rather than trusting that nobody did.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any

import pytest

from apps.accounts import selectors
from apps.accounts.selectors import get_connection_for_email, get_member, list_sso_connections
from apps.core.actor import Actor, actor_for
from apps.core.exceptions import Forbidden, NotFound
from apps.core.models import Grant, Membership
from apps.core.services import add_membership, root_organization

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.core.tests.permissions_world import World

pytestmark = pytest.mark.django_db

#: The pre-authentication lookups, by name. Each answers before anybody has
#: signed in, so each carries `# read-open:` with the caller it serves — and
#: the list is here so that a sweep which quietly gave one of them an `actor`
#: parameter reds with that name rather than with a login box that stopped
#: working in an environment nobody tests by hand.
PRE_AUTH_READS: tuple[str, ...] = (
    "get_connection_for_email",
    "get_realm_for_email",
    "get_enforcing_connection_for",
)


@pytest.fixture
def tree(db: None) -> World:
    from apps.core.tests.permissions_world import build_world

    return build_world()


def _person(actor: Actor) -> Any:
    """The user behind an actor `permissions_world` built. **Never `None` here.**

    `Actor.user` is `AbstractBaseUser | None` because a request can resolve
    nobody; every actor in the world is somebody the builder created.
    """
    assert actor.user is not None
    return actor.user


def _withhold(membership: Membership, permission: str) -> Grant:
    """A raw withhold, for a SET-UP that is not the subject of the test.

    `create_grant` is P4's audited service with its own reach wall; what these
    tests are about is the SELECTOR, so the row is written directly — the same
    shape `apps/core/tests/test_handing_out.py::_grant` uses for the same
    reason.
    """
    return Grant.objects.create(
        tenant=membership.tenant,
        membership=membership,
        permission=permission,
        effect=Grant.Effect.WITHHOLD,
    )


# --- get_member ---------------------------------------------------------------


def test_a_member_may_still_resolve_a_person_in_their_own_tenant(tree: World) -> None:
    """The control. `member` holds `*.read`, so nothing a member could do moved."""
    other = tree.member_membership.user
    assert get_member(tenant=tree.tenant, user_id=other.pk, actor=tree.member) == other


def test_a_hat_with_the_read_withheld_gets_forbidden_inside_and_not_found_outside(
    tree: World,
) -> None:
    """The two refusals, and they are different facts.

    A withhold of `user.read` on this person's own membership takes the
    capability away without touching their reach — so a person INSIDE the
    acting tenant is `forbidden` (you may not read people) and a person outside
    it is still `not_found` (there is no such person here). Collapsing the two
    would answer "does this account exist" to anybody holding a session.
    """
    _withhold(tree.member_membership, "user.read")
    inside = tree.owner_membership.user

    with pytest.raises(Forbidden):
        get_member(tenant=tree.tenant, user_id=inside.pk, actor=tree.member)

    from apps.accounts.services import create_user
    from apps.core.tests.permissions_world import PASSWORD

    stranger = create_user(email="stranger-reads-ask@example.com", password=PASSWORD)
    with pytest.raises(NotFound):
        get_member(tenant=tree.tenant, user_id=stranger.pk, actor=tree.member)


def test_the_reach_is_read_before_the_capability(tree: World) -> None:
    """Order matters, and this is the assertion that pins it.

    The same actor, refused two ways: a person they cannot see is `not_found`
    EVEN THOUGH they also lack the read. Asking first would turn every
    unreachable id into a `forbidden`, which tells a caller that the id exists
    somewhere — the not-there ≡ not-yours rule, one layer up.
    """
    _withhold(tree.roleless_membership, "user.read")
    from apps.accounts.services import create_user
    from apps.core.tests.permissions_world import PASSWORD

    stranger = create_user(email="ordering-reads-ask@example.com", password=PASSWORD)
    with pytest.raises(NotFound):
        get_member(tenant=tree.tenant, user_id=stranger.pk, actor=tree.roleless)


def test_a_roleless_membership_may_not_resolve_anybody(tree: World) -> None:
    """The roleless person holds nothing, and `user.read` is now part of nothing.

    Before the sweep this read was free, so a membership carrying no role at all
    resolved every person in the tenant and handed them to a service that then
    refused the verb — which is a wall one step later than it should be, and one
    that leaked the existence of every account on the way.
    """
    inside = tree.owner_membership.user
    with pytest.raises(Forbidden):
        get_member(tenant=tree.tenant, user_id=inside.pk, actor=tree.roleless)


# --- list_sso_connections ------------------------------------------------------


def test_the_list_is_asked_at_the_root_so_a_branch_admin_cannot_read_it(tree: World) -> None:
    """**The node is the ROOT, and a branch hat is refused there** (PM ruling).

    `sso_connection` names no organization, so it is a tenant-wide kind and
    rule 55's law applies: asked at the acting hat, a branch administrator's
    `*` would answer it — and the answer is the tenant's whole federation
    posture, every provider and every domain each one claims. That is the
    configuration itself, which R1-F1 put at the root for the four writing
    keys; reading it belongs at the same node.

    Three actors, three different reasons, so the test says which is which:
    `owner` holds everything at the root; `member` holds `*.read` and its
    membership IS at the root; `admin_at_a` holds `*` at `A` and nothing at the
    root, which is the case this pin exists for and the one an earlier draft
    got wrong.
    """
    assert list(list_sso_connections(tenant=tree.tenant, actor=tree.owner)) == []
    assert list(list_sso_connections(tenant=tree.tenant, actor=tree.member)) == []

    with pytest.raises(Forbidden):
        list_sso_connections(tenant=tree.tenant, actor=tree.admin_at_a)


def test_a_root_admin_may_read_the_list(tree: World) -> None:
    """The other side of the same node: `admin` AT THE ROOT is admitted.

    Without this the pin above would be satisfied by a wall that refuses every
    administrator, which is a different (and wrong) rule. `admin` holds `*` —
    everything but ownership — so at the root it holds `sso_connection.read`
    and the only thing separating it from `admin_at_a` is where its membership
    sits.
    """
    admin_at_root = add_membership(
        user=_person(tree.roleless),
        tenant=tree.tenant,
        organization=tree.root,
        role="admin",
        actor=tree.owner,
    )
    acting = actor_for(user=admin_at_root.user, tenant=tree.tenant, org=tree.root)

    assert list(list_sso_connections(tenant=tree.tenant, actor=acting)) == []


def test_a_hat_without_the_read_hears_it_rather_than_an_empty_page(tree: World) -> None:
    """The whole point of asking at all: silence and refusal are not the same.

    An empty list reads as "this tenant has no identity provider", which is a
    fact about the tenant. A refusal reads as "you may not see this", which is a
    fact about the caller. Returning the first when the second is true is how a
    customer concludes their SSO was never configured.
    """
    _withhold(tree.member_membership, "sso_connection.read")
    with pytest.raises(Forbidden):
        list_sso_connections(tenant=tree.tenant, actor=tree.member)


def test_the_list_is_still_scoped_to_the_acting_tenant(tree: World) -> None:
    """The capability is a second wall, never a replacement for the first.

    `for_tenant` decides WHICH rows and `require` decides WHETHER — rule 24's
    split — and a sweep that swapped one for the other would have made
    `sso_connection.read` at a hat a licence to read every tenant's providers.
    """
    root = root_organization(tenant=tree.tenant)
    assert root.tenant_id == tree.tenant.pk
    rows = list_sso_connections(tenant=tree.tenant, actor=tree.owner)
    assert all(row.tenant_id == tree.tenant.pk for row in rows)


# --- the valves ----------------------------------------------------------------


def test_get_connection_for_email_takes_no_actor_and_answers_before_anybody_signs_in() -> None:
    """The pre-auth read, and why it cannot ask.

    It is the home-realm question — "whose person is this address" — asked of a
    stranger typing into a login box. There is no session, no tenant and no
    membership, so `sso_connection.read` has nothing to be asked against, and a
    sweep that grew this one an `actor` parameter would have closed the front
    door. The valve is what makes that a recorded decision rather than an
    omission.
    """
    assert "actor" not in inspect.signature(get_connection_for_email).parameters
    assert get_connection_for_email("nobody@nowhere.invalid") is None


def test_every_pre_authentication_read_takes_no_actor() -> None:
    """The reads before a principal exists take no actor; rule 54(d) reads their valves."""
    for name in PRE_AUTH_READS:
        function = getattr(selectors, name)
        assert "actor" not in inspect.signature(function).parameters, name
