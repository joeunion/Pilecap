"""Reads are permissions, in `events`: every door read asks, and the machine ones say why.

The app's half of ADR core-27. `test_authz_sweep.py` beside this file drives the
WRITE algebra (what a role holds); this drives the READ SEAM — that each public
selector actually asks, that the one machine read says in its own source why it
does not, and that the flat product still reads everything it read.

**The grammar under test, in one line** (§C8, reach before capability): a row in
another tenant is `not_found`, a row in this one without `<kind>.read` is
`forbidden`, and a list without the key is `forbidden` because a list has no row
to hide. The ORDER is asserted by the two exception types rather than described.

**Three kinds, three keys, and that is the point of asking per kind** (rule 54
(e)): an endpoint is where a tenant's data is SENT, an event is what happened,
and a delivery is the attempt. A tenant that wants its support staff to read
deliveries without reading the subscription list needs three words to say it
with, and until reads became permissions it had none — every membership
read all three.

The over-the-wire half of the both-doors claim is
`test_doors_over_the_wire.py`'s rule-46 case, which drives the real ASGI
application with a real bearer token; this module drives the door functions,
where the same claim can be parametrised cheaply.

Raw `Grant` rows, because the services that hand permissions out are a later
rung's and the criteria say a raw create is legal until they land.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from django.db import models
from django.test import Client
from django.utils.timezone import now

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.authz import kind_of, refusal_sentence
from apps.core.exceptions import Forbidden, NotFound
from apps.core.models import Grant, Membership, Organization, Tenant
from apps.core.services import add_membership, create_organization, root_organization
from apps.events import selectors as event_selectors
from apps.events.models import Delivery, Event, WebhookEndpoint
from apps.events.selectors import (
    get_delivery,
    get_endpoint,
    get_event,
    list_dead_letters,
    list_deliveries,
    list_endpoints,
    list_endpoints_for,
    list_events,
)

pytestmark = pytest.mark.django_db

ENDPOINTS_URL = "/api/v1/webhook-endpoints/"
DELIVERIES_URL = "/api/v1/deliveries/"
DEAD_LETTERS_URL = "/api/v1/dead-letters/"

#: A literal long enough for Django's validators, spelled HERE rather than
#: imported from `apps/conftest.py`: that module imports `apps.workflows`, so
#: an import of it from this app's tests is this app importing a SIBLING —
#: which the layer contract refuses, and which the hook catches at the commit.
BRANCH_PASSWORD = "a-long-enough-password-for-validators"  # noqa: S105 — a throwaway password a test user is made with  # pragma: allowlist secret

#: **`list_events`/`get_event` have no door at all** — checked while writing this
#: module, and worth writing down rather than discovering twice: this app
#: publishes endpoints, deliveries, dead letters and the event-type catalogue,
#: and the event rows themselves are reached only by the dispatch activities and
#: by `services`. They ask `event.read` anyway, which is the point: a read that
#: starts asking only once somebody publishes it is a read that is free in
#: exactly the window nobody is looking.
EVENT_ROUTES: tuple[str, ...] = ()

#: The valve rule 54 (d) reads for a selector nobody's door calls. Spelled here
#: so the derivation below looks for the same string the gate looks for.
READ_OPEN = "# read-open:"


@dataclass(frozen=True)
class Reads:
    """One tenant with one of each row, a foreign tenant, and a plain member."""

    tenant: Tenant
    other_tenant: Tenant
    reader: User
    reader_membership: Membership
    endpoint: WebhookEndpoint
    foreign_endpoint: WebhookEndpoint
    event: Event
    foreign_event: Event
    delivery: Delivery

    def actor(self) -> Actor:
        """A fresh actor — fresh because the memo's TTL is the instance."""
        return actor_for(user=self.reader, tenant=self.tenant)


@pytest.fixture
def reads(tenant: Tenant, other_tenant: Tenant, member: User) -> Reads:
    endpoint = WebhookEndpoint.objects.create(
        tenant=tenant,
        url="https://ours.example/hook",
        secret="s-ours",  # noqa: S106 — a signing secret the test both signs and verifies with  # pragma: allowlist secret
    )
    foreign_endpoint = WebhookEndpoint.objects.create(
        tenant=other_tenant,
        url="https://theirs.example/hook",
        secret="s-theirs",  # noqa: S106 — a signing secret the test both signs and verifies with  # pragma: allowlist secret
    )
    event = Event.objects.create(
        tenant=tenant, name="example.widget.created", payload={}, occurred_at=now()
    )
    foreign_event = Event.objects.create(
        tenant=other_tenant, name="example.widget.created", payload={}, occurred_at=now()
    )
    delivery = Delivery.objects.create(
        endpoint=endpoint, event=event, status=Delivery.Status.PENDING
    )
    return Reads(
        tenant=tenant,
        other_tenant=other_tenant,
        reader=member,
        reader_membership=Membership.objects.get(user=member, tenant=tenant),
        endpoint=endpoint,
        foreign_endpoint=foreign_endpoint,
        event=event,
        foreign_event=foreign_event,
        delivery=delivery,
    )


def withhold(membership: Membership, permission: str) -> Grant:
    """A raw `withhold` row. Legal until the hand-out services land."""
    return Grant.objects.create(
        tenant=membership.tenant,
        membership=membership,
        permission=permission,
        effect=Grant.Effect.WITHHOLD,
    )


# --- the population, derived from the module ----------------------------------


def _returned_model(function: Callable[..., Any]) -> type[models.Model] | None:
    """The model a selector's RETURN ANNOTATION names, or `None`.

    Read off the annotation TEXT, the way rule 54 (d)/(e) reads it, and NOT with
    `typing.get_type_hints`: Django's `QuerySet.__class_getitem__` returns the
    class itself, so `ScopedQuerySet[Event]` evaluates to `ScopedQuerySet` and
    the model is erased — a resolver that trusted it would report this app's list
    selectors as outside the population and go quietly blind.
    """
    raw = function.__annotations__.get("return")
    if not isinstance(raw, str):
        return None
    namespace = vars(inspect.getmodule(function) or event_selectors)
    for name in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", raw):
        candidate = namespace.get(name)
        if isinstance(candidate, type) and issubclass(candidate, models.Model):
            return candidate
    return None


def door_selectors() -> dict[str, Callable[..., Any]]:
    """Every public `get_`/`list_` in this app's `selectors.py` over a kind."""
    found: dict[str, Callable[..., Any]] = {}
    for name, function in vars(event_selectors).items():
        if name.startswith("_") or not name.startswith(("get_", "list_")):
            continue
        if not inspect.isfunction(function) or function.__module__ != event_selectors.__name__:
            continue
        model = _returned_model(function)
        if model is None or kind_of(model) is None:
            continue
        found[name] = function
    return found


def test_every_door_selector_asks_or_says_why() -> None:
    """Each one takes `actor`, or carries the valve with its reason (rule 54 (d)).

    **The instrument answers something when the thing is absent**: the
    population is derived and its names asserted first, so a derivation that
    stopped finding selectors reds here instead of passing over an empty set.

    The machine reads ask nothing; each says why in its own source.
    """
    selectors = door_selectors()
    assert sorted(selectors) == [
        "get_delivery",
        "get_endpoint",
        "get_event",
        "list_active_endpoints_everywhere",
        "list_dead_letters",
        "list_deliveries",
        "list_endpoints",
        "list_endpoints_for",
        "list_events",
        "list_outbox_to_replay",
        "list_stranded_outbox",
        "list_undispatched_outbox",
    ], sorted(selectors)

    asking = {
        "get_delivery",
        "get_endpoint",
        "get_event",
        "list_dead_letters",
        "list_deliveries",
        "list_endpoints",
        "list_events",
    }
    for name, function in sorted(selectors.items()):
        signature = inspect.signature(function)
        source = inspect.getsource(function)
        if name in asking:
            parameter = signature.parameters["actor"]
            assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, name
            assert parameter.default is inspect.Parameter.empty, (
                f"{name}: `actor` has a default, so a caller that forgets it reads for free"
            )
        else:
            assert "actor" not in signature.parameters, name
            assert READ_OPEN in source, name


def test_the_machine_reads_stay_open_and_the_door_reads_do_not(reads: Reads) -> None:
    """The dispatch's machine read answers under a withhold; the door read over those rows refuses.

    A door reaching the valved `list_endpoints_for` instead of `list_endpoints` reads for free.
    """
    withhold(reads.reader_membership, "endpoint.read")

    assert [row.pk for row in list_endpoints_for(tenant=reads.tenant, name=reads.event.name)] == [
        reads.endpoint.pk
    ]
    with pytest.raises(Forbidden):
        list_endpoints(tenant=reads.tenant, actor=reads.actor())


@pytest.mark.parametrize(
    ("kind", "selector"),
    [("endpoint", list_endpoints), ("event", list_events), ("delivery", list_deliveries)],
)
def test_a_list_without_the_key_is_forbidden_and_says_the_keys_own_sentence(
    reads: Reads, kind: str, selector: Callable[..., Any]
) -> None:
    """A list has no row to hide, so the only honest answers are the page and 403.

    Then the withhold is lifted and the same call answers, which is what stops
    this from being a test that would pass with the selectors refusing everybody.
    """
    key = f"{kind}.read"
    withhold(reads.reader_membership, key)

    with pytest.raises(Forbidden) as refused:
        selector(tenant=reads.tenant, actor=reads.actor())
    assert str(refused.value.args[0]) == refusal_sentence(key)

    Grant.objects.filter(membership=reads.reader_membership, permission=key).delete()
    assert selector(tenant=reads.tenant, actor=reads.actor()).exists()


def test_the_three_kinds_are_three_keys(reads: Reads) -> None:
    """Rule 54 (e): each selector asks for the kind IT returns, not a neighbour's.

    A withhold of `endpoint.read` must not silence the event list, and a
    withhold of `event.read` must not silence the endpoint list. Before the
    sweep there was one answer for all three — any membership read everything —
    so this is the property the flip actually adds, and the one a selector that
    asked the wrong kind would break while every happy path stayed green.
    """
    withhold(reads.reader_membership, "endpoint.read")
    assert list_events(tenant=reads.tenant, actor=reads.actor()).exists()
    assert list_deliveries(tenant=reads.tenant, actor=reads.actor()).exists()
    with pytest.raises(Forbidden):
        list_endpoints(tenant=reads.tenant, actor=reads.actor())

    Grant.objects.filter(membership=reads.reader_membership).delete()
    withhold(reads.reader_membership, "event.read")
    assert list_endpoints(tenant=reads.tenant, actor=reads.actor()).exists()
    with pytest.raises(Forbidden):
        list_events(tenant=reads.tenant, actor=reads.actor())


def test_a_row_in_another_tenant_is_not_found_and_one_here_without_the_key_is_forbidden(
    reads: Reads,
) -> None:
    """Reach before capability, asserted by the two exception TYPES (§C8)."""
    withhold(reads.reader_membership, "endpoint.read")
    withhold(reads.reader_membership, "event.read")

    with pytest.raises(NotFound):
        get_endpoint(
            tenant=reads.tenant, endpoint_id=reads.foreign_endpoint.pk, actor=reads.actor()
        )
    with pytest.raises(Forbidden) as refused_endpoint:
        get_endpoint(tenant=reads.tenant, endpoint_id=reads.endpoint.pk, actor=reads.actor())
    assert str(refused_endpoint.value.args[0]) == refusal_sentence("endpoint.read")

    with pytest.raises(NotFound):
        get_event(tenant=reads.tenant, event_id=reads.foreign_event.pk, actor=reads.actor())
    with pytest.raises(Forbidden) as refused_event:
        get_event(tenant=reads.tenant, event_id=reads.event.pk, actor=reads.actor())
    assert str(refused_event.value.args[0]) == refusal_sentence("event.read")

    Grant.objects.filter(membership=reads.reader_membership).delete()
    assert (
        get_endpoint(tenant=reads.tenant, endpoint_id=reads.endpoint.pk, actor=reads.actor()).pk
        == reads.endpoint.pk
    )
    assert (
        get_event(tenant=reads.tenant, event_id=reads.event.pk, actor=reads.actor()).pk
        == reads.event.pk
    )


def test_the_dead_letter_list_asks_the_same_key_the_delivery_list_asks(reads: Reads) -> None:
    """A narrowing is not a second question (rule 54 (e), the other direction).

    `list_dead_letters` is `list_deliveries` with a filter on it, and it goes through
    that selector rather than round the side — so a `delivery.read` withhold
    reaches both. A door that could read the dead letters without being able to
    read the deliveries would be the same surface with a filter on it.
    """
    withhold(reads.reader_membership, "delivery.read")
    with pytest.raises(Forbidden) as refused:
        list_dead_letters(tenant=reads.tenant, actor=reads.actor())
    assert str(refused.value.args[0]) == refusal_sentence("delivery.read")


def test_the_system_actor_reads_everything_the_scope_shows(reads: Reads) -> None:
    """`system` passes at step 1, so the dispatch activities are untouched.

    Asserted with a withhold on the reader in place, so the pass is the actor
    KIND and not an accident of there being nothing to refuse. This is the
    property the whole spine stands on: the fan-out resolves an endpoint and an
    event by id on every attempt, and a read gate that reached it would stop
    every delivery in the deployment.
    """
    for key in ("endpoint.read", "event.read", "delivery.read"):
        withhold(reads.reader_membership, key)
    system = system_actor(reads.tenant)
    assert list_endpoints(tenant=reads.tenant, actor=system).exists()
    assert list_events(tenant=reads.tenant, actor=system).exists()
    assert list_deliveries(tenant=reads.tenant, actor=system).exists()
    assert (
        get_endpoint(tenant=reads.tenant, endpoint_id=reads.endpoint.pk, actor=system).pk
        == reads.endpoint.pk
    )
    assert (
        get_delivery(tenant=reads.tenant, delivery_id=reads.delivery.pk, actor=system).pk
        == reads.delivery.pk
    )


# --- the flat product observes nothing, and the wire says the same words ------


def test_the_plain_member_still_reads_every_route_this_app_publishes(
    api: Client, reads: Reads
) -> None:
    """Principle 13: a product that customised nothing sees the answers it saw.

    The member holds `("*.read",)` by declaration, so every read route in this
    app answers 200 with no permission row anywhere. This is the half that would
    catch a flip that refused everybody — a seam test whose every case is a
    refusal cannot tell "asks correctly" from "asks and always says no".
    """
    api.force_login(reads.reader)
    for url in (ENDPOINTS_URL, DELIVERIES_URL, DEAD_LETTERS_URL, *EVENT_ROUTES):
        response = api.get(url)
        assert response.status_code == 200, (url, response.content)
    # The event rows have no route (see `EVENT_ROUTES`), so the member's read of
    # them is asserted at the selector rather than over the wire.
    assert list_events(tenant=reads.tenant, actor=reads.actor()).exists()


def test_a_withheld_read_is_forbidden_on_the_wire_with_the_keys_own_sentence(
    api: Client, reads: Reads
) -> None:
    """The refusal a real client meets, not the one the selector raises.

    A row in another tenant stays 404 — the half Phase R does not touch — and it
    is asserted here so that "the door renders the refusal" covers the answer it
    gives for a row the caller could never have reached.
    """
    withhold(reads.reader_membership, "endpoint.read")
    sentence = refusal_sentence("endpoint.read")
    api.force_login(reads.reader)

    listed = api.get(ENDPOINTS_URL)
    assert listed.status_code == 403, listed.content
    assert listed.json()["code"] == "forbidden"
    assert listed.json()["detail"] == sentence

    detail = api.get(f"{ENDPOINTS_URL}{reads.endpoint.pk}/")
    assert detail.status_code == 403, detail.content
    assert detail.json()["detail"] == sentence

    foreign = api.get(f"{ENDPOINTS_URL}{reads.foreign_endpoint.pk}/")
    assert foreign.status_code == 404, foreign.content

    # The event catalogue reads no kind, so it is untouched by this withhold —
    # the route that would have been easiest to gate by accident.
    catalogue = api.get("/api/v1/event-types/")
    assert catalogue.status_code == 200, catalogue.content


# --- the branch member, and the one population a sweep SHRINKS ----------------


@dataclass(frozen=True)
class Branch:
    """A member whose only membership is at a branch, and a sibling branch's row.

    The tenant's tree is `root → a1` and `root → b`, and the reader's single
    membership sits at `a1`. That is the shape the register question is about:
    every kind this app reads is TENANT-wide, so the node the read resolves at
    is either the tenant's root — which this person holds nothing at — or the
    hat they are actually wearing.
    """

    tenant: Tenant
    reader: User
    membership: Membership
    a1: Organization
    b: Organization
    endpoint: WebhookEndpoint
    delivery: Delivery
    event: Event
    sibling_event: Event
    homeless_event: Event


@pytest.fixture
def branch(tenant: Tenant, owner: User) -> Branch:
    system = system_actor(tenant=tenant)
    hq = root_organization(tenant=tenant)
    acting = actor_for(user=owner, tenant=tenant, org=hq)
    a1 = create_organization(tenant=tenant, parent=hq, name="Leaf A1", slug="leaf-a1", actor=acting)
    b = create_organization(
        tenant=tenant, parent=hq, name="Branch B", slug="branch-b", actor=acting
    )

    reader = create_user(email="branch-member@example.com", password=BRANCH_PASSWORD)
    add_membership(
        user=reader,
        tenant=tenant,
        organization=a1,
        is_default=True,
        role=Membership.Role.MEMBER,
        actor=system,
    )
    endpoint = WebhookEndpoint.objects.create(
        tenant=tenant,
        url="https://branch.example/hook",
        secret="s-branch",  # noqa: S106 — a signing secret the test both signs and verifies with  # pragma: allowlist secret
    )
    event = Event.objects.create(
        tenant=tenant, name="example.widget.created", payload={}, occurred_at=now()
    )
    sibling_event = Event.objects.create(
        tenant=tenant,
        name="example.widget.created",
        payload={},
        occurred_at=now(),
        organization=b,
    )
    homeless_event = Event.objects.create(
        tenant=tenant, name="search.engine.degraded", payload={}, occurred_at=now()
    )
    delivery = Delivery.objects.create(
        endpoint=endpoint, event=event, status=Delivery.Status.PENDING
    )
    return Branch(
        tenant=tenant,
        reader=reader,
        membership=Membership.objects.get(user=reader, tenant=tenant),
        a1=a1,
        b=b,
        endpoint=endpoint,
        delivery=delivery,
        event=event,
        sibling_event=sibling_event,
        homeless_event=homeless_event,
    )


def test_a_branch_member_reads_the_tenants_shared_rows_at_their_hat(
    api: Client, branch: Branch
) -> None:
    """**The 403 population SHRINKS** — the reverse of every other sweep here.

    A `member` whose one membership is at `leaf-a1` holds `("*.read",)` there and
    holds nothing at the tenant's root. Under the root form this person was
    refused every endpoint, delivery and event in the tenant while their socket
    went on delivering `events.endpoint.registered` frames — two doors, one
    question, two answers, which is the disagreement rule 46 is named after.

    Sight is the hat's: a tenant-wide kind is READ at the acting hat and still
    WRITTEN at the tenant's root, so a branch's people see the tenant's shared
    configuration and cannot change it. The dated valve on each site says so,
    and the rung that gives these kinds a home deletes it.

    *States driven:* a branch member with `*.read` at their own hat · the same
    person with ONE kind withheld (the door closes, and only that door) · an
    event homed in a SIBLING branch (the row's node answers, and it refuses) ·
    an event with no branch at all (the hat answers) · `system`. *Not driven:*
    a person with two memberships — P3's blind spot, unchanged.
    """
    actor = actor_for(user=branch.reader, tenant=branch.tenant, org=branch.a1)

    assert list_endpoints(tenant=branch.tenant, actor=actor).exists()
    assert list_deliveries(tenant=branch.tenant, actor=actor).exists()
    assert list_events(tenant=branch.tenant, actor=actor).exists()
    assert (
        get_endpoint(tenant=branch.tenant, endpoint_id=branch.endpoint.pk, actor=actor).pk
        == branch.endpoint.pk
    )
    assert (
        get_delivery(tenant=branch.tenant, delivery_id=branch.delivery.pk, actor=actor).pk
        == branch.delivery.pk
    )

    api.force_login(branch.reader)
    hat = {"x-org": branch.a1.slug}
    for url in (ENDPOINTS_URL, DELIVERIES_URL, DEAD_LETTERS_URL):
        response = api.get(url, headers=hat)
        assert response.status_code == 200, (url, response.content)
    detail = api.get(f"{ENDPOINTS_URL}{branch.endpoint.pk}/", headers=hat)
    assert detail.status_code == 200, detail.content

    # ONE key, ONE door: the withhold closes the endpoint list and nothing else.
    withhold(branch.membership, "endpoint.read")
    closed = api.get(ENDPOINTS_URL, headers=hat)
    assert closed.status_code == 403, closed.content
    assert closed.json()["detail"] == refusal_sentence("endpoint.read")
    still_open = api.get(DELIVERIES_URL, headers=hat)
    assert still_open.status_code == 200, still_open.content
    Grant.objects.filter(membership=branch.membership).delete()

    # The ROW's node answers when the row has one. An event homed in the sibling
    # branch is refused where this person holds nothing; one with no branch at
    # all falls back to the hat, which is where they hold `*.read`.
    with pytest.raises(Forbidden) as refused:
        get_event(tenant=branch.tenant, event_id=branch.sibling_event.pk, actor=actor)
    assert str(refused.value.args[0]) == refusal_sentence("event.read")
    assert (
        get_event(tenant=branch.tenant, event_id=branch.homeless_event.pk, actor=actor).pk
        == branch.homeless_event.pk
    )

    system = system_actor(branch.tenant)
    assert list_endpoints(tenant=branch.tenant, actor=system).exists()
