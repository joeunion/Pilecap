"""Every refusal on the sign-in road leaves the tree exactly as it found it.

**A census, not a list.** The sign-in surface has two branches and a service
behind one of them, and between them they can turn somebody away for a dozen
different reasons. Writing a case per reason by hand is how the thirteenth one
ships with no case at all — nobody notices an absence — so the population here
is DERIVED: an `ast` walk of the two modules that refuse, finding every call to
this app's own `refusal_response` and every `raise SsoRefused(...)`.

Two tests come off that population and they fail in opposite directions:

* `test_every_refusal_site_has_a_driver` reds when a refusal exists that nothing
  here provokes — the day somebody adds one — and reds again when a driver names
  a site that no longer exists, so a deleted refusal cannot leave a test quietly
  exercising nothing;
* `test_every_refusal_leaves_the_tree_unchanged` drives each one and asserts the
  rows either side are identical — **and that the driver reached the refusal it
  names**. The second half is not decoration: two drivers here refused for a
  reason other than their own for a whole cycle (V-R2F), which is a case that
  passes while the site it claims to cover has never once been executed. A spy
  on the refusal's own caller line answers "which one fired" from the running
  process rather than from the driver's name.

**`AuditEntry` is unwatched BY DESIGN, and it is the only table that is.** A
refusal raised *inside* a `@service` — `SsoRefused` from
`provision_sso_identity` — writes its own error row on the way out, and that row
is the refusal's receipt rather than a write the refusal failed to prevent.
Excluding it is what lets this belt say something sharp about every other table
instead of something vague about all of them. `WATCHED` below is the population
this belt speaks for; a table that is neither in it nor named here is one
nobody has decided about, which is what R2F2.3 found: `EmailAddress` — the row
allauth's signup step writes — sat outside the census, so a refusal that ran
after it moved nothing this belt could see.

**What a refusal that ran too late looks like here.** `sociallogin.connect`
writes a `SocialAccount`; allauth's signup step writes a `User` and an
`EmailAddress`; the invitation join writes a `Membership` and moves an
`Invitation`. A refusal placed after any of them shows up as a non-zero delta in
exactly that table, which is how this belt would have caught the deactivated
person's sign-in writing a membership before it was turned away.
"""

from __future__ import annotations

import ast
import pathlib
import sys
from collections.abc import Callable
from types import FrameType
from typing import Any, NamedTuple

import pytest
from allauth.account.models import EmailAddress
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.models import SocialAccount

from apps.accounts.adapter import SocialAccountAdapter
from apps.accounts.models import SsoConnection, SsoIdentity, User
from apps.accounts.selectors import get_platform_provider_id
from apps.accounts.services import create_user, disable_sso_connection, provision_sso_identity
from apps.accounts.tests.conftest import assertion, join
from apps.core.actor import system_actor
from apps.core.exceptions import DomainError
from apps.core.models import Invitation, Membership, Organization, Tenant
from apps.core.services import add_membership

pytestmark = pytest.mark.django_db

WORKFORCE_DOMAIN = "builders.example"

# The two modules that turn somebody away on the sign-in road. Named here rather
# than discovered, because "which modules refuse" is a statement about the
# surface's shape that a reader should be able to check against the app map —
# what is derived is every refusal INSIDE them.
REFUSING_MODULES = ("apps/accounts/adapter.py", "apps/accounts/services.py")

# `apps/core/api/docs.py` has a function of the same name and is a different
# thing entirely; the population is by module, which is why it is not in the
# tuple above.
REFUSAL_CALL = "refusal_response"
REFUSAL_RAISE = "SsoRefused"


class Site(NamedTuple):
    """One refusal, addressed so a human can find it and a rename cannot hide it.

    Deliberately NOT the line number: a line moves every time somebody edits a
    docstring above it, and a population keyed on line numbers would red on
    every unrelated commit. The ordinal within the enclosing function is stable
    under everything except adding or removing a refusal — which is exactly the
    change this population exists to notice.
    """

    module: str
    function: str
    ordinal: int


def _sites(relative: str) -> dict[Site, range]:
    """Every refusal in one module, in source order, with the lines it spans.

    The span is what the spy resolves a caller's line through. It is NOT part of
    the site's identity — `Site` is deliberately line-free, for the reason its
    own docstring gives — so a docstring edit above a refusal moves the span and
    changes nothing a test is keyed on.
    """
    tree = ast.parse(pathlib.Path(relative).read_text())
    found: list[tuple[str, int, int]] = []
    enclosing: list[str] = []

    class Walk(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            enclosing.append(node.name)
            self.generic_visit(node)
            enclosing.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            enclosing.append(node.name)
            self.generic_visit(node)
            enclosing.pop()

        def visit_Call(self, node: ast.Call) -> None:
            if isinstance(node.func, ast.Name) and node.func.id == REFUSAL_CALL:
                found.append(
                    (enclosing[-1] if enclosing else "<module>", node.lineno, node.end_lineno or 0)
                )
            self.generic_visit(node)

        def visit_Raise(self, node: ast.Raise) -> None:
            raised = node.exc
            if (
                isinstance(raised, ast.Call)
                and isinstance(raised.func, ast.Name)
                and raised.func.id == REFUSAL_RAISE
            ):
                found.append(
                    (
                        enclosing[-1] if enclosing else "<module>",
                        raised.lineno,
                        raised.end_lineno or 0,
                    )
                )
            self.generic_visit(node)

    Walk().visit(tree)
    seen: dict[str, int] = {}
    sites: dict[Site, range] = {}
    for function, line, end in sorted(found, key=lambda triple: triple[1]):
        ordinal = seen.get(function, 0)
        seen[function] = ordinal + 1
        sites[Site(relative, function, ordinal)] = range(line, max(end, line) + 1)
    return sites


SITE_SPANS: dict[Site, range] = {
    site: span for relative in REFUSING_MODULES for site, span in _sites(relative).items()
}
REFUSAL_SITES: frozenset[Site] = frozenset(SITE_SPANS)


# --- the world each driver is given, and the snapshot taken around it ---------


# does-not-cover: `build_world` builds no sign-in request or SSO connection — one consumer;
# a second consumer is the trigger to lift it into `build_world` (principle 11).
class World(NamedTuple):
    """A sign-in refusal's world: a request, a connection, two people and a second tenant."""

    request: Any
    tenant: Tenant
    connection: SsoConnection
    resident: User
    other: User
    elsewhere: Tenant
    elsewhere_root: Organization


# **Every table a refused sign-in could move, and `EmailAddress` is one of them.**
# It is allauth's own row for "this address is proven", written by the signup
# step — the same step that writes the `User` — so a refusal that ran one line
# too late writes it exactly as it writes the rest. It was outside this tuple for
# a whole cycle and a plant inside a refusal's own footprint went unnoticed
# (R2F2.3): a census that names four of the five tables a path writes is a
# census that reads as complete and is not.
WATCHED = (User, SocialAccount, EmailAddress, SsoIdentity, Membership, Invitation)


def snapshot() -> dict[str, Any]:
    """The rows a refusal must not have moved.

    Counts catch a creation; the two vectors catch an EDIT that keeps the count
    — a re-pointed identity join and an invitation flipped to `accepted` are
    both changes a count alone would sleep through, and both are exactly what
    this surface got wrong.
    """
    return {
        **{model.__name__: model.objects.count() for model in WATCHED},
        "users": sorted(User.objects.values_list("pk", "is_active")),
        "joins": sorted(
            SsoIdentity.objects.filter(connection__isnull=True).values_list(
                "user_id", "realm", "subject"
            )
        ),
        "invitations": sorted(Invitation.objects.values_list("pk", "status")),
    }


def refused(call: Callable[[], object]) -> None:
    """Run a driver and insist it refused. A driver that succeeds proves nothing."""
    with pytest.raises((ImmediateHttpResponse, DomainError)):
        call()


# --- which refusal actually fired --------------------------------------------
#
# A driver's NAME says which site it provokes; only the running process knows.
# Two of the sixteen here disagreed with their own name for a cycle — a driver
# refused earlier, for a different reason, and its case passed on a site that
# had never been executed. The spy below answers the question from the caller's
# own line: both refusal forms are reached through a module-global name
# (`refusal_response(...)` in the adapter, `raise SsoRefused(...)` in the
# service), so replacing that name for the length of one case records where the
# call came from and changes nothing else.


def _site_at(frame: FrameType) -> Site | None:
    """The refusal site whose source span contains this caller's line, if any."""
    filename = frame.f_code.co_filename
    for site, span in SITE_SPANS.items():
        if filename.endswith(site.module) and frame.f_lineno in span:
            return site
    return None


@pytest.fixture
def fired(monkeypatch: pytest.MonkeyPatch) -> list[Site]:
    """Every refusal site reached during this case, in the order it was reached.

    A door refusal that renders a service's own is two entries — the service's
    `raise` and then the door's `refusal_response` — which is why the test below
    asserts about the LAST one: the site a driver names is the refusal its
    caller actually gets, and the earlier entries are how it got there.
    """
    from apps.accounts import adapter as adapter_module
    from apps.accounts import services as services_module

    reached: list[Site] = []

    def record() -> None:
        site = _site_at(sys._getframe(2))
        if site is not None:
            reached.append(site)

    real_response = adapter_module.refusal_response

    def spied_response(request: Any, reason: str) -> Any:
        record()
        return real_response(request, reason)

    real_refusal = services_module.SsoRefused

    def spied_refusal(*args: Any, **kwargs: Any) -> Any:
        # A factory rather than a subclass: `DomainError.__init_subclass__`
        # refuses a class whose code is not registered, and a spy has no
        # business declaring a refusal code. What is raised is the real class.
        record()
        return real_refusal(*args, **kwargs)

    monkeypatch.setattr(adapter_module, "refusal_response", spied_response)
    monkeypatch.setattr(services_module, "SsoRefused", spied_refusal)
    return reached


def adapter(world: World) -> SocialAccountAdapter:
    return SocialAccountAdapter(world.request)


def platform(email: str, subject: str = "sub-1", verified: bool = True) -> Any:
    return assertion(
        provider=get_platform_provider_id(), subject=subject, email=email, verified=verified
    )


# --- one driver per site -----------------------------------------------------
#
# Each entry provokes EXACTLY the refusal its key names. They are hand-written
# on purpose: a driver derived from the source would be the same mistake the
# source made, checked by itself.

A = "apps/accounts/adapter.py"
S = "apps/accounts/services.py"


def _platform_unverified(world: World) -> Callable[[], object]:
    return lambda: adapter(world).pre_social_login(
        world.request, platform("nobody@example.com", verified=False)
    )


def _platform_claim_dormant(world: World) -> Callable[[], object]:
    """A staff-realm sign-in at a domain a switched-off connection still claims."""
    disable_sso_connection(
        tenant=world.tenant, actor=system_actor(world.tenant), connection=world.connection
    )
    return lambda: adapter(world).pre_social_login(
        world.request, platform("someone@acme.com", subject="sub-dormant")
    )


def _platform_subject_address_disagree(world: World) -> Callable[[], object]:
    join(world.resident, "sub-held")
    return lambda: adapter(world).pre_social_login(
        world.request, platform(world.other.email, subject="sub-held")
    )


def _platform_subject_mismatch(world: World) -> Callable[[], object]:
    join(world.resident, "sub-original")
    return lambda: adapter(world).pre_social_login(
        world.request, platform(world.resident.email, subject="sub-fresh")
    )


def _platform_inactive(world: World) -> Callable[[], object]:
    world.resident.is_active = False
    world.resident.save(update_fields=["is_active"])
    return lambda: adapter(world).pre_social_login(
        world.request, platform(world.resident.email, subject="sub-fresh")
    )


def _platform_writer_refused(world: World) -> Callable[[], object]:
    """The writer's own `Conflict`, surfaced by the door.

    **The one live road, and it is a normalisation seam.** The door compares the
    subject exactly as the issuer asserted it — that is the string allauth would
    match its own row on — while `record_identity` strips before it
    writes and before it looks. So an assertion carrying `" sub-z "` for a
    subject stored as `"sub-z"` misses every lookup this door makes (our column
    holds no padded string; allauth holds no row for one), is introduced by the
    address of somebody who holds no join at all, and meets the writer's
    `Conflict` on the stripped form — which is this site.

    The driver that stood here before reached `_platform_login`'s DISAGREE
    refusal two branches earlier instead (V-R2F): it put the subject in our
    column, which the door resolves on first, so the service was never called.
    """
    join(world.other, "sub-z")
    return lambda: adapter(world).pre_social_login(
        world.request, platform(world.resident.email, subject=" sub-z ")
    )


def _platform_domain_not_allowed(world: World) -> Callable[[], object]:
    """The workforce wall: a stranger nobody vouched for, from nobody's domain.

    Verified, holding no subject of ours, at an address no account and no
    customer's `SsoDomain` claims, with no invitation standing — the one person
    the platform would otherwise mint. It is the site the retired direct Google
    road's wrong-domain refusal moved to; that road's unverified and inactive
    refusals are the platform branch's own sites 0 and 4.
    """
    return lambda: adapter(world).pre_social_login(
        world.request, platform("stranger@gmail.com", subject="sub-stranger")
    )


def _customer_service_refused(world: World) -> Callable[[], object]:
    """The service refuses; the door turns it into a page.

    **A VERIFIED address, on a domain the connection claims.** The driver that
    stood here asserted an unverified one, which `_platform_login`'s very first
    refusal catches before the router ever runs — so this site was named by a
    case that never executed it (V-R2F). What reaches the service with an
    assertion the door is willing to route is a person who exists at a claimed
    address and is switched off: `provision_sso_identity` refuses with the
    inactive sentence, and this site is where the door renders it.
    """
    resident = create_user(email="person@acme.com", password=None)
    resident.is_active = False
    resident.save(update_fields=["is_active"])
    return lambda: adapter(world).pre_social_login(
        world.request, platform(resident.email, subject="sub-c1")
    )


def _customer_writer_refused(world: World) -> Callable[[], object]:
    """The second refusal on the customer branch: the identity joined, the subject taken."""
    join(world.other, "sub-c2")
    resident = create_user(email="person@acme.com", password=None)
    # SET-UP: the identity exists before the call that must refuse.
    provision_sso_identity(
        tenant=world.tenant,
        actor=system_actor(world.tenant),
        connection=world.connection,
        subject="sub-c2",
        email=resident.email,
        email_verified=True,
    )
    return lambda: adapter(world).pre_social_login(
        world.request, platform(resident.email, subject="sub-c2")
    )


def _service(world: World, **overrides: Any) -> Callable[[], object]:
    """The customer branch's service call, with one field bent per case."""
    kwargs: dict[str, Any] = {
        "tenant": world.tenant,
        "actor": system_actor(world.tenant),
        "connection": world.connection,
        "subject": "sub-s",
        "email": "person@acme.com",
        "email_verified": True,
    }
    kwargs.update(overrides)
    return lambda: provision_sso_identity(**kwargs)


def _service_unverified(world: World) -> Callable[[], object]:
    return _service(world, email_verified=False)


def _service_no_address(world: World) -> Callable[[], object]:
    return _service(world, email="")


def _service_outside_domains(world: World) -> Callable[[], object]:
    return _service(world, email="person@elsewhere.example")


def _service_identity_inactive(world: World) -> Callable[[], object]:
    """The identity already exists; its person is then switched off."""
    resident = create_user(email="person@acme.com", password=None)
    _service(world)()
    resident.is_active = False
    resident.save(update_fields=["is_active"])
    return _service(world)


def _service_address_inactive(world: World) -> Callable[[], object]:
    resident = create_user(email="person@acme.com", password=None)
    resident.is_active = False
    resident.save(update_fields=["is_active"])
    return _service(world)


def _service_elsewhere(world: World) -> Callable[[], object]:
    resident = create_user(email="person@acme.com", password=None)
    add_membership(
        user=resident,
        tenant=world.elsewhere,
        organization=world.elsewhere_root,
        role=Membership.Role.MEMBER,
        actor=system_actor(tenant=world.elsewhere),
    )
    return _service(world)


DRIVERS: dict[Site, Callable[[World], Callable[[], object]]] = {
    Site(A, "_platform_login", 0): _platform_unverified,
    Site(A, "_platform_login", 1): _platform_claim_dormant,
    Site(A, "_platform_login", 2): _platform_subject_address_disagree,
    Site(A, "_platform_login", 3): _platform_subject_mismatch,
    Site(A, "_platform_login", 4): _platform_domain_not_allowed,
    Site(A, "_platform_login", 5): _platform_inactive,
    Site(A, "_platform_login", 6): _platform_writer_refused,
    Site(A, "_customer_login", 0): _customer_service_refused,
    Site(A, "_customer_login", 1): _customer_writer_refused,
    Site(S, "provision_sso_identity", 0): _service_unverified,
    Site(S, "provision_sso_identity", 1): _service_no_address,
    Site(S, "provision_sso_identity", 2): _service_outside_domains,
    Site(S, "provision_sso_identity", 3): _service_identity_inactive,
    Site(S, "provision_sso_identity", 4): _service_address_inactive,
    Site(S, "provision_sso_identity", 5): _service_elsewhere,
}


def test_every_refusal_site_has_a_driver() -> None:
    """The census and the drivers are the same set, and say so when they are not.

    This is the test that makes the belt hold in the future rather than only
    today: the fifteenth builder's new refusal reds it by name, and so does a
    driver left behind by a refusal somebody removed.
    """
    missing = sorted(REFUSAL_SITES - set(DRIVERS))
    stale = sorted(set(DRIVERS) - REFUSAL_SITES)
    assert not missing, f"refusals with no driver: {missing}"
    assert not stale, f"drivers for refusals that no longer exist: {stale}"


@pytest.fixture
def world(
    login_request: Any,
    settings: Any,
    tenant: Tenant,
    sso_connection: SsoConnection,
    other_tenant: Tenant,
    other_root_org: Organization,
) -> World:
    """One world per case, with both doors configured so every driver can reach its site.

    The workforce settings are here rather than in a second fixture because a
    parametrised belt gets ONE fixture set for every member: a driver whose door
    was not configured would refuse for the wrong reason and the case would pass
    while proving nothing about the site it names.
    """
    settings.GOOGLE_OAUTH_CLIENT_ID = "google-client-id"
    settings.GOOGLE_OAUTH_CLIENT_SECRET = "google-client-secret"  # noqa: S105 — a fake IdP client secret the test world configures  # pragma: allowlist secret
    settings.GOOGLE_WORKSPACE_DOMAINS = [WORKFORCE_DOMAIN]
    return World(
        request=login_request,
        tenant=tenant,
        connection=sso_connection,
        resident=create_user(email="resident@example.com", password=None),
        other=create_user(email="other@example.com", password=None),
        elsewhere=other_tenant,
        elsewhere_root=other_root_org,
    )


@pytest.mark.parametrize("site", sorted(REFUSAL_SITES))
def test_every_refusal_leaves_the_tree_unchanged(
    site: Site, world: World, fired: list[Site]
) -> None:
    """Drive one refusal, insist it is THE one, and that the rows either side match.

    **Two phases, and the split is what makes the assertion honest.** A driver
    builds whatever world its refusal needs and RETURNS the one call that must
    refuse; the snapshot is taken between the two, so what is compared is the
    refusal's own footprint and never its preparation. A single-phase driver
    would have to snapshot before its own set-up, and every case would then be
    asserting that set-up wrote nothing — which is not the property.

    **The identity assertion comes first, deliberately.** "Nothing moved" is
    true of a driver that refused at some *other* site too, so without it every
    stale driver reads as a healthy case — which is exactly how two of them
    survived a review (V-R2F). The last entry is the refusal the caller gets;
    anything before it is the path that produced it.
    """
    provoke = DRIVERS[site](world)

    fired.clear()
    before = snapshot()
    refused(provoke)
    after = snapshot()

    assert fired, f"{site} refused without reaching any refusal site this belt knows"
    assert fired[-1] == site, f"{site}'s driver reached {fired[-1]} instead"
    assert after == before, f"{site} moved rows on its way to refusing"


def test_what_allauth_writes_after_an_accepted_verdict(
    api: Any, stub_issuer: Any, owner: User
) -> None:
    """The rows that appear AFTER the adapter says yes, measured and pinned.

    These are allauth's writes, not ours, and the adapter's refusals all run
    before every one of them — which is the property the belt above measures. A
    refusal that had run after `sociallogin.connect` would show a
    `SocialAccount` delta of 1 there and red it.

    Two paths through the platform door, which is the one this deployment
    actually uses: a person who does not exist yet, and one who does. The
    workforce and customer branches reach the same allauth machinery by the same
    call, and their own accepted paths are pinned by `test_a9_matrix.py`.
    """
    from allauth.account.models import EmailAddress

    from apps.accounts.tests.test_rp_login import sign_in

    def deltas(run: Callable[[], Any]) -> dict[str, int]:
        before = {
            model.__name__: model.objects.count() for model in (User, SocialAccount, EmailAddress)
        }
        run()
        return {
            model.__name__: model.objects.count() - before[model.__name__]
            for model in (User, SocialAccount, EmailAddress)
        }

    stub_issuer.email = "newcomer@example.com"
    assert deltas(lambda: sign_in(api)) == {
        "User": 1,
        "SocialAccount": 1,
        "EmailAddress": 1,
    }

    api.logout()
    stub_issuer.email = owner.email
    stub_issuer.subject = "sub-for-the-owner"
    # MEASURED, not assumed: allauth writes no second `EmailAddress` for a
    # person it linked rather than created — the address row is the signup
    # step's, and the signup step did not run.
    assert deltas(lambda: sign_in(api)) == {
        "User": 0,
        "SocialAccount": 1,
        "EmailAddress": 0,
    }
