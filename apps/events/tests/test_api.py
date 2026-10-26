"""The spine's HTTP door: endpoints, the catalogue, deliveries, dead letters.

The three properties this module exists to hold, in the order they matter:

* **the signing key is answered exactly once.** `test_no_read_of_an_endpoint_ever
  _carries_the_secret_again` drives every other shape a client can reach an
  endpoint through — get, list, patch, pause, resume — and asserts the minted
  plaintext appears in none of them, by key *and* by substring. The substring
  half is the one that catches a future field somebody adds under a different
  name.
* **the catalogue is a census, not a list.** It is compared against
  `events.declared_names()` — the same registry `emit` validates against — so
  the day another app declares an event this test is what says the door already
  serves it.
* **not-there and not-yours are one answer.** Another tenant's endpoint id is
  `not_found`, with the same body a nonexistent id gets.

The wire proof — that the key a subscriber is handed actually verifies the
signature on a real delivery — is `test_signed_delivery.py`, because it needs
real commits and a real socket.
"""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.core.actor import Actor, system_actor
from apps.core.audit import AuditEntry
from apps.core.idempotency import HEADER, REPLAYED_HEADER
from apps.core.models import Tenant
from apps.events import services
from apps.events.events import declared_names
from apps.events.models import Delivery, WebhookEndpoint
from apps.example.events import WIDGET_CREATED

pytestmark = pytest.mark.django_db

ENDPOINTS_URL = "/api/v1/webhook-endpoints/"
CATALOGUE_URL = "/api/v1/event-types/"
DELIVERIES_URL = "/api/v1/deliveries/"
DEAD_LETTERS_URL = "/api/v1/dead-letters/"
JSON = "application/json"

# Measured at twelve endpoints, not guessed, and re-measured when this file
# changes: the page, its COUNT, the session row, the membership resolution and
# the savepoints the test client's transaction opens. An N+1 in the endpoint
# list would move this number, which is the whole point of pinning it.
# ADR core-18 took one statement OFF this pin: the default list issues no
# COUNT any more — `has_more` comes from fetching one row more than asked
# for. `?include_count=true` puts it back, and costs exactly one more.
#
# **+3 since Phase R** (ADR core-27, rule 5): the selector asks its kind's
# `read` at the acting hat, and resolution reads three tables — this person's
# memberships in the tenant, the grants on them, and the role deltas for the
# roles on the chain. It is paid ONCE per actor instance whatever the number
# of `require`s (the PR0 memo), so a route that asked twice would still be +3
# and not +6. `CATALOGUE_QUERY_BUDGET` does NOT move: `GET /event-types/`
# reads the declared vocabulary of event names and no kind at all.
#
# **House rule 55 put a root read on this path; the register took it off again,
# and these two numbers did not move.** The kind is TENANT-WIDE and names no
# organization, so the selector used to resolve the tenant's ROOT to ask at.
# Since PR5.5 sight is the ACTING HAT's — the read asks with no node and
# `where_of` answers where the caller is standing — and the write half is
# untouched: a tenant-wide kind is still WRITTEN at the root, which is why a
# branch's people can see the tenant's endpoints and not change them.
#
# **11 -> 10 -> 10, and the middle number is the one worth reading.** The memo on
# the tenant instance (`core.models.Tenant`) had already taken the root read off
# a request whose hat IS the root, which is what these two make (they send no
# `X-Org` and land on the owner's default membership at the root). So dropping
# the root read entirely changed nothing HERE — it changed the number a request
# under a BRANCH hat pays, which used to be one more, once per request, and is
# now the same as this one. The hat these budgets run under is the root, and
# that sentence is the pin's own, not an inference (build-contract.md).
ENDPOINT_LIST_QUERY_BUDGET = 8
DELIVERY_LIST_QUERY_BUDGET = 8
CATALOGUE_QUERY_BUDGET = 4


def register(api: Client, url: str = "https://subscriber.example/hook", **body: Any) -> Any:
    """Create one endpoint over the door, the way a subscriber would."""
    return api.post(
        ENDPOINTS_URL,
        data=json.dumps({"url": url, **body}),
        content_type=JSON,
    )


# --- The secret is said once ---------------------------------------------------


def test_registering_an_endpoint_answers_the_secret_exactly_once(
    api: Client, owner: User, tenant: Tenant
) -> None:
    """The create response carries the key; it is the only response that ever will."""
    api.force_login(owner)
    response = register(api, description="the billing integration")
    assert response.status_code == 201, response.content

    body = response.json()
    assert set(body) == {"endpoint", "secret"}
    assert body["secret"], "the create response is the one moment the key exists on the wire"
    assert body["endpoint"]["url"] == "https://subscriber.example/hook"
    assert body["endpoint"]["is_active"] is True
    # The key on the wire is the key in the (encrypted) column: what the
    # subscriber was handed is what the delivery will be signed with.
    endpoint = WebhookEndpoint.objects.get(pk=body["endpoint"]["id"])
    assert endpoint.secret == body["secret"]


def test_no_read_of_an_endpoint_ever_carries_the_secret_again(
    api: Client, owner: User, tenant: Tenant
) -> None:
    """Every other shape a client can reach an endpoint through, checked at once.

    By key and by substring: the key check catches a `secret` field somebody
    adds back, the substring check catches one added under any other name.
    """
    api.force_login(owner)
    created = register(api).json()
    endpoint_id = created["endpoint"]["id"]
    minted = created["secret"]
    detail = f"{ENDPOINTS_URL}{endpoint_id}/"

    reads = {
        "detail": api.get(detail),
        "list": api.get(ENDPOINTS_URL),
        "patch": api.patch(detail, data=json.dumps({"description": "renamed"}), content_type=JSON),
        "pause": api.post(f"{detail}pause/"),
        "resume": api.post(f"{detail}resume/"),
    }
    for where, response in reads.items():
        assert response.status_code == 200, (where, response.content)
        raw = response.content.decode()
        assert minted not in raw, f"{where} handed the signing key back"
        assert "secret" not in raw, f"{where} has a field named for one"

    listed = reads["list"].json()["items"]
    assert [set(item) for item in listed] == [
        {
            "id",
            "url",
            "is_active",
            "event_names",
            "description",
            "created_at",
            "updated_at",
        }
    ]


def test_issuing_a_new_secret_answers_it_once_and_it_is_a_different_one(
    api: Client, owner: User, tenant: Tenant
) -> None:
    """Rotation is a replacement: a new key, said once, and the old one is gone."""
    api.force_login(owner)
    created = register(api).json()
    endpoint_id = created["endpoint"]["id"]

    rotated = api.post(f"{ENDPOINTS_URL}{endpoint_id}/secret/")
    assert rotated.status_code == 200, rotated.content
    body = rotated.json()
    assert set(body) == {"endpoint", "secret"}
    assert body["secret"] != created["secret"]

    # And the row now holds the new one and nothing of the old.
    endpoint = WebhookEndpoint.objects.get(pk=endpoint_id)
    assert endpoint.secret == body["secret"]

    # The reads still have nowhere to put it.
    detail = api.get(f"{ENDPOINTS_URL}{endpoint_id}/")
    assert body["secret"] not in detail.content.decode()
    assert created["secret"] not in detail.content.decode()


# --- "Can an end user create a signed webhook?" — still no ---------------------


def test_a_plain_member_cannot_register_an_endpoint(
    api: Client, member: User, tenant: Tenant
) -> None:
    """An endpoint is a credential-bearing egress route; a member is not an admin.

    The owner's standing question. Registering one means deciding where a copy
    of everything that happens in the tenant is sent, so `policies.py` puts it
    at owner-or-admin and the door does not soften that.
    """
    api.force_login(member)
    response = register(api)
    assert response.status_code == 403, response.content
    assert response.json()["code"] == "forbidden"
    assert not WebhookEndpoint.objects.exists()


def test_a_person_of_no_tenant_is_refused_no_acting_scope_and_nothing_is_written(
    api: Client, nomad: User
) -> None:
    """The door's one resolver answers an absent tenant with the registry's code, not a bare 403."""
    api.force_login(nomad)
    response = register(api)
    assert response.status_code == 403, response.content
    assert response.json()["code"] == "no_acting_scope"
    assert not WebhookEndpoint.objects.exists()


def test_a_plain_member_may_read_the_subscription_surface_and_the_document_says_so(
    api: Client, owner: User, member: User, owner_actor: Actor, tenant: Tenant
) -> None:
    """N193c: the reads are reads, on the wire and in the prose, together.

    `policies.py` decided this when the door was built and wrote the reason
    down: "a read of a dead letter is a read, and sending it again is not."
    `POLICIES` holds six actions and every one of them is a write; the reads
    call no `require` and take no actor at all — they read `request.tenant`
    rather than going through `_acting`, which is the construction and not an
    omission. The docstrings said otherwise on every route in the file,
    including the catalogue, which is the same for every customer — a blanket
    transcription of the door-shape superset (`derived_refusals` gives every
    authenticated route a `forbidden`), not a decision anybody made per route.
    So the prose was corrected, not the door.

    The population is derived from the document rather than listed here: every
    GET this app publishes is driven as a plain member and must answer, and none
    of them may promise a role they do not check. A read added here tomorrow is
    in this test the moment it is mounted.
    """
    from config.api import api as mounted

    endpoint = services.register_endpoint(
        tenant=tenant, actor=owner_actor, url="https://subscriber.example/hook"
    )
    document = mounted.get_openapi_schema()
    reads = {
        path: methods["get"]
        for path, methods in document["paths"].items()
        if "get" in methods and "events" in methods["get"].get("tags", [])
    }
    assert len(reads) == 5, sorted(reads)

    api.force_login(member)
    for path, operation in reads.items():
        url = re.sub(r"\{[^}]+\}", str(endpoint.pk), path)
        assert api.get(url).status_code == 200, url
        assert "owner or an administrator" not in operation["description"], path


def test_a_plain_member_cannot_rotate_pause_or_replay(
    api: Client, owner: User, member: User, tenant: Tenant, owner_actor: Actor
) -> None:
    """The whole subscription surface is one permission, not create alone."""
    endpoint = services.register_endpoint(
        tenant=tenant, actor=owner_actor, url="https://subscriber.example/hook"
    )
    api.force_login(member)
    detail = f"{ENDPOINTS_URL}{endpoint.pk}/"
    for path in (f"{detail}secret/", f"{detail}pause/", f"{detail}resume/"):
        assert api.post(path).status_code == 403, path
    assert (
        api.patch(detail, data=json.dumps({"description": "x"}), content_type=JSON).status_code
        == 403
    )


# --- The catalogue is the census ----------------------------------------------


def test_the_catalogue_is_exactly_the_declared_population(
    api: Client, owner: User, tenant: Tenant
) -> None:
    """The door serves what the apps declare — not a list anybody maintains.

    Compared against `declared_names()`, which reads the installed apps' own
    `events.py` modules. A hand-listed catalogue would pass this the day it was
    written and be wrong the morning after the next app declared an event; this
    one cannot be, because there is nothing to update.
    """
    api.force_login(owner)
    response = api.get(f"{CATALOGUE_URL}?limit=200")
    assert response.status_code == 200, response.content
    body = response.json()

    declared = {
        (name, app_label) for app_label, names in declared_names().items() for name in names
    }
    served = {(item["name"], item["app"]) for item in body["items"]}
    assert served == declared
    assert len(body["items"]) == len(declared)
    assert WIDGET_CREATED in {item["name"] for item in body["items"]}


def test_the_catalogue_is_sorted_so_paging_over_it_is_stable(
    api: Client, owner: User, tenant: Tenant
) -> None:
    """Two pages of an unordered census can overlap and drop entries alike."""
    api.force_login(owner)
    names = [item["name"] for item in api.get(f"{CATALOGUE_URL}?limit=200").json()["items"]]
    assert names == sorted(names)


def test_subscribing_to_an_event_nobody_declares_is_refused_naming_the_field(
    api: Client, owner: User, tenant: Tenant
) -> None:
    """A typo is a subscription that silently never fires. It is refused instead."""
    api.force_login(owner)
    response = register(api, event_names=["example.widget.creted"])
    assert response.status_code == 400, response.content
    body = response.json()
    assert body["code"] == "invalid"
    assert "event_names" in body["errors"]
    assert "event-types" in body["errors"]["event_names"][0]
    assert not WebhookEndpoint.objects.exists()


def test_subscribing_to_a_declared_event_is_kept_verbatim(
    api: Client, owner: User, tenant: Tenant
) -> None:
    api.force_login(owner)
    created = register(api, event_names=[WIDGET_CREATED]).json()
    assert created["endpoint"]["event_names"] == [WIDGET_CREATED]


# --- Tenant walls --------------------------------------------------------------


def test_another_tenants_endpoint_is_not_found_not_forbidden(
    api: Client,
    owner: User,
    tenant: Tenant,
    other_tenant: Tenant,
    stranger_actor: Actor,
) -> None:
    """Not-there and not-yours are one answer, byte for byte.

    A refusal that told them apart would confirm the row exists, which is the
    fact the tenancy was hiding.
    """
    theirs = services.register_endpoint(
        tenant=other_tenant, actor=stranger_actor, url="https://elsewhere.example/hook"
    )
    api.force_login(owner)

    over_the_wall = api.get(f"{ENDPOINTS_URL}{theirs.pk}/")
    never_existed = api.get(f"{ENDPOINTS_URL}{uuid4()}/")
    assert over_the_wall.status_code == never_existed.status_code == 404
    assert over_the_wall.content == never_existed.content
    assert over_the_wall.json()["code"] == "not_found"


def test_the_endpoint_list_holds_only_this_tenants_rows(
    api: Client,
    owner: User,
    owner_actor: Actor,
    tenant: Tenant,
    other_tenant: Tenant,
    stranger_actor: Actor,
) -> None:
    mine = services.register_endpoint(
        tenant=tenant, actor=owner_actor, url="https://mine.example/hook"
    )
    services.register_endpoint(
        tenant=other_tenant, actor=stranger_actor, url="https://theirs.example/hook"
    )
    api.force_login(owner)
    listed = api.get(ENDPOINTS_URL).json()
    assert [item["id"] for item in listed["items"]] == [str(mine.pk)]
    assert len(listed["items"]) == 1


def test_another_tenants_delivery_cannot_be_replayed(
    api: Client,
    owner: User,
    tenant: Tenant,
    other_tenant: Tenant,
    stranger_actor: Actor,
) -> None:
    theirs = _dead_letter(other_tenant, stranger_actor)
    api.force_login(owner)
    response = api.post(f"{DEAD_LETTERS_URL}{theirs.pk}/replay/")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


# --- Pausing, and what a paused endpoint is not -------------------------------


def test_pausing_takes_an_endpoint_out_of_the_fan_out_and_resuming_puts_it_back(
    api: Client, owner: User, owner_actor: Actor, tenant: Tenant
) -> None:
    """`list_endpoints_for` is what the dispatch loads, and it reads the active ones."""
    api.force_login(owner)
    endpoint_id = register(api).json()["endpoint"]["id"]
    detail = f"{ENDPOINTS_URL}{endpoint_id}/"

    assert api.post(f"{detail}pause/").json()["is_active"] is False
    from apps.events.selectors import list_endpoints_for

    assert list_endpoints_for(tenant=tenant, name=WIDGET_CREATED) == []

    assert api.post(f"{detail}resume/").json()["is_active"] is True
    assert [e.pk for e in list_endpoints_for(tenant=tenant, name=WIDGET_CREATED)] == [
        WebhookEndpoint.objects.get(pk=endpoint_id).pk
    ]


def test_a_paused_endpoint_is_still_listed_because_that_is_the_question(
    api: Client, owner: User, tenant: Tenant
) -> None:
    """Why an integration went quiet is what this list exists to answer."""
    api.force_login(owner)
    endpoint_id = register(api).json()["endpoint"]["id"]
    api.post(f"{ENDPOINTS_URL}{endpoint_id}/pause/")

    listed = api.get(ENDPOINTS_URL).json()["items"]
    assert [item["id"] for item in listed] == [endpoint_id]
    assert listed[0]["is_active"] is False
    assert len(api.get(f"{ENDPOINTS_URL}?is_active=false").json()["items"]) == 1
    assert len(api.get(f"{ENDPOINTS_URL}?is_active=true").json()["items"]) == 0


# --- Deliveries and dead letters ----------------------------------------------


def _dead_letter(tenant: Tenant, actor: Actor) -> Delivery:
    """One endpoint, one event, one delivery that spent every retry."""
    endpoint = services.register_endpoint(
        tenant=tenant, actor=actor, url=f"https://sub-{uuid4().hex[:8]}.example/hook"
    )
    event = services.record_event(tenant=tenant, name=WIDGET_CREATED, payload={"v": 1}, actor=actor)
    services.record_delivery_attempt(
        tenant=tenant,
        endpoint_id=endpoint.pk,
        event_id=event.pk,
        status=Delivery.Status.FAILED,
        code=503,
        error="Service Unavailable",
    )
    return services.dead_letter_delivery(
        tenant=tenant, endpoint_id=endpoint.pk, event_id=event.pk, error="spent every retry"
    )


def test_a_dead_letter_is_listed_with_the_reason_it_gave_up(
    api: Client, owner: User, owner_actor: Actor, tenant: Tenant
) -> None:
    dead = _dead_letter(tenant, owner_actor)
    api.force_login(owner)

    listed = api.get(DEAD_LETTERS_URL).json()
    assert [item["id"] for item in listed["items"]] == [str(dead.pk)]
    row = listed["items"][0]
    assert row["status"] == "dead"
    assert row["dead_lettered_at"] is not None
    assert row["last_code"] == 503
    assert row["event_name"] == WIDGET_CREATED
    assert row["attempts"] == 1


def test_the_deliveries_list_holds_the_failures_too_and_narrows_on_status(
    api: Client, owner: User, owner_actor: Actor, tenant: Tenant
) -> None:
    dead = _dead_letter(tenant, owner_actor)
    api.force_login(owner)
    assert len(api.get(DELIVERIES_URL).json()["items"]) == 1
    assert len(api.get(f"{DELIVERIES_URL}?status=dead").json()["items"]) == 1
    assert len(api.get(f"{DELIVERIES_URL}?status=delivered").json()["items"]) == 0
    assert len(api.get(f"{DELIVERIES_URL}?endpoint_id={dead.endpoint_id}").json()["items"]) == 1


def test_replaying_a_dead_letter_enqueues_the_event_again(
    api: Client,
    owner: User,
    owner_actor: Actor,
    tenant: Tenant,
    recorded_workflow_starts: None,
) -> None:
    """The events-3 resume path, reached from the door instead of from a shell.

    What is asserted is what the door owns: the outbox row is back in the queue
    with its attempt counter advanced, which is what makes the replay's workflow
    id a new one rather than the finished run's. That the run then delivers is
    the dispatch workflow's own tested property.
    """
    from apps.events.models import Outbox

    dead = _dead_letter(tenant, owner_actor)
    outbox = Outbox.objects.get(event=dead.event)
    before = outbox.attempts

    api.force_login(owner)
    response = api.post(f"{DEAD_LETTERS_URL}{dead.pk}/replay/")
    assert response.status_code == 200, response.content
    assert response.json()["id"] == str(dead.pk)

    outbox.refresh_from_db()
    assert outbox.attempts == before + 1
    assert outbox.status == Outbox.Status.PENDING
    assert outbox.next_attempt_at is not None


def test_replaying_something_that_never_gave_up_is_refused(
    api: Client, owner: User, owner_actor: Actor, tenant: Tenant
) -> None:
    """A pending delivery is still being retried; a replay would be a duplicate."""
    endpoint = services.register_endpoint(
        tenant=tenant, actor=owner_actor, url="https://subscriber.example/hook"
    )
    event = services.record_event(
        tenant=tenant, name=WIDGET_CREATED, payload={"v": 1}, actor=system_actor(tenant=tenant)
    )
    pending = services.record_delivery_attempt(
        tenant=tenant,
        endpoint_id=endpoint.pk,
        event_id=event.pk,
        status=Delivery.Status.PENDING,
    )
    api.force_login(owner)
    response = api.post(f"{DEAD_LETTERS_URL}{pending.pk}/replay/")
    assert response.status_code == 400, response.content
    assert response.json()["code"] == "invalid"
    assert "delivery" in response.json()["errors"]


# --- The house contract: idempotency, audit, budgets ---------------------------


def test_a_repeated_idempotency_key_replays_the_first_registration(
    api: Client, owner: User, tenant: Tenant
) -> None:
    """A retried create makes one endpoint, and answers the first key again.

    Which matters more here than on most writes: a create that ran twice would
    be two endpoints holding two different signing keys, and the caller would
    have kept the second answer.
    """
    api.force_login(owner)
    first = api.post(
        ENDPOINTS_URL,
        data=json.dumps({"url": "https://subscriber.example/hook"}),
        content_type=JSON,
        headers={HEADER: "endpoint-1"},
    )
    second = api.post(
        ENDPOINTS_URL,
        data=json.dumps({"url": "https://subscriber.example/hook"}),
        content_type=JSON,
        headers={HEADER: "endpoint-1"},
    )
    assert first.status_code == second.status_code == 201
    assert second.content == first.content
    assert second[REPLAYED_HEADER] == "true"
    assert WebhookEndpoint.objects.count() == 1


def test_the_audit_trail_names_the_act_and_the_door(
    api: Client, owner: User, tenant: Tenant
) -> None:
    """G3: every act on this surface, by name, with `door="rest"`.

    The MCP door's value is `mcp` and is stamped by `config/mcp.py`'s mount
    rather than by a tool body, which is why it is proved there and named here
    instead of re-proved: a tool called as a function has no mount around it.
    """
    api.force_login(owner)
    endpoint_id = register(api).json()["endpoint"]["id"]
    detail = f"{ENDPOINTS_URL}{endpoint_id}/"
    api.post(f"{detail}secret/")
    api.post(f"{detail}pause/")
    api.post(f"{detail}resume/")
    api.patch(detail, data=json.dumps({"description": "named"}), content_type=JSON)

    rows = AuditEntry.objects.for_tenant(tenant).filter(action__startswith="events.")
    by_action = {row.action: row for row in rows}
    for action in (
        "events.register_endpoint",
        "events.issue_endpoint_secret",
        "events.deactivate_endpoint",
        "events.resume_endpoint",
        "events.update_endpoint",
    ):
        assert action in by_action, sorted(by_action)
        assert by_action[action].door == "rest"
        assert by_action[action].outcome == "ok"
        assert by_action[action].actor_user_id == owner.pk


def test_the_audit_row_never_carries_the_secret(api: Client, owner: User, tenant: Tenant) -> None:
    """`LOG_KEYS` is an allow-list, and `secret` is not on it and never will be."""
    api.force_login(owner)
    minted = register(api).json()["secret"]
    for row in AuditEntry.objects.for_tenant(tenant):
        assert minted not in json.dumps(row.input)
        assert "secret" not in json.dumps(row.input)


def test_the_replay_is_audited_as_the_act_it_is(
    api: Client,
    owner: User,
    owner_actor: Actor,
    tenant: Tenant,
    recorded_workflow_starts: None,
) -> None:
    dead = _dead_letter(tenant, owner_actor)
    api.force_login(owner)
    api.post(f"{DEAD_LETTERS_URL}{dead.pk}/replay/")
    row = AuditEntry.objects.for_tenant(tenant).filter(action="events.enqueue_replay").first()
    assert row is not None
    assert row.door == "rest"
    assert row.actor_user_id == owner.pk


# --- Query pins (house rule 5) -------------------------------------------------


def test_the_endpoint_list_query_budget(
    api: Client,
    owner: User,
    owner_actor: Actor,
    tenant: Tenant,
    django_assert_num_queries: Any,
) -> None:
    """Twelve endpoints cost what one does. Measured, not guessed."""
    for index in range(12):
        services.register_endpoint(
            tenant=tenant, actor=owner_actor, url=f"https://sub-{index}.example/hook"
        )
    api.force_login(owner)
    with django_assert_num_queries(ENDPOINT_LIST_QUERY_BUDGET):
        assert api.get(ENDPOINTS_URL).status_code == 200


def test_the_delivery_list_query_budget(
    api: Client,
    owner: User,
    owner_actor: Actor,
    tenant: Tenant,
    django_assert_num_queries: Any,
) -> None:
    """`event_name` is read off the relation, so this is where an N+1 would show."""
    for _ in range(12):
        _dead_letter(tenant, owner_actor)
    api.force_login(owner)
    with django_assert_num_queries(DELIVERY_LIST_QUERY_BUDGET):
        assert api.get(DELIVERIES_URL).status_code == 200


def test_the_catalogue_costs_no_query_at_all(
    api: Client, owner: User, tenant: Tenant, django_assert_num_queries: Any
) -> None:
    """It is derived from modules, not from rows — the count is the session's only."""
    api.force_login(owner)
    with django_assert_num_queries(CATALOGUE_QUERY_BUDGET):
        assert api.get(CATALOGUE_URL).status_code == 200


# --- The document says all of this --------------------------------------------


def test_every_route_here_is_in_the_openapi_document_with_its_own_prose(
    api: Client, owner: User
) -> None:
    """House rule 41 from this app's seat: the contract is the document.

    The rule's own check is the authority; this asserts the outcome a reader
    meets — that the group is described and that no operation is sitting there
    with ninja's prettified function name for a summary.
    """
    from config.api import api as mounted

    document = mounted.get_openapi_schema()
    tags = {tag["name"]: tag["description"] for tag in document.get("tags", [])}
    assert tags.get("events"), "the events tag has no description"

    ours = [
        operation
        for path, methods in document["paths"].items()
        if path.startswith("/api/v1/")
        for operation in methods.values()
    ]
    assert ours, "no events operation reached the document"
    for operation in ours:
        summary = operation["summary"]
        assert summary and operation["description"]
        # ninja's default is `view_func.__name__.title().replace("_", " ")` —
        # `List Endpoints Route`. A summary that is Title Case throughout is
        # that default wearing a hat; a real sentence is not.
        assert summary != summary.title(), summary
        # Every operation enumerates the refusals it can answer with, and the
        # codes come from the registry rather than from prose written per route.
        assert any(
            "x-refusal-codes" in response
            for status, response in operation["responses"].items()
            if not str(status).startswith("2")
        ), summary


# --- No target in private space ------------------------------------------------


@pytest.mark.parametrize("verb", ["create", "update"])
def test_the_metadata_address_is_refused_at_the_door_naming_the_class(
    api: Client, owner: User, tenant: Tenant, verb: str
) -> None:
    """The box's credential endpoint: 400 `invalid` on `url`, and nothing is written."""
    api.force_login(owner)
    target = "https://169.254.169.254/latest/meta-data/"
    if verb == "create":
        response = register(api, url=target)
    else:
        endpoint_id = register(api).json()["endpoint"]["id"]
        response = api.patch(
            f"{ENDPOINTS_URL}{endpoint_id}/", data=json.dumps({"url": target}), content_type=JSON
        )

    assert response.status_code == 400, response.content
    body = response.json()
    assert body["code"] == "invalid"
    assert body["errors"]["url"] == ["The host is or resolves to a link-local address."]
    assert "169.254" not in response.content.decode()
    assert not WebhookEndpoint.objects.for_tenant(tenant).filter(url=target).exists()


def test_a_name_that_resolves_privately_is_refused_at_the_door(
    api: Client, owner: User, tenant: Tenant, resolved_hosts: dict[str, list[str]]
) -> None:
    api.force_login(owner)
    resolved_hosts["inside.example.com"] = ["10.9.8.7"]
    response = register(api, url="https://inside.example.com/hook")
    assert response.status_code == 400, response.content
    assert response.json()["errors"]["url"] == ["The host is or resolves to a private address."]
    assert "10.9.8.7" not in response.content.decode()


def test_the_laptop_valve_lets_the_door_take_plain_http_to_localhost(
    api: Client, owner: User, tenant: Tenant, settings: Any
) -> None:
    settings.WEBHOOK_PRIVATE_TARGETS_ALLOWED = True
    api.force_login(owner)
    response = register(api, url="http://localhost:9000/hook")
    assert response.status_code == 201, response.content
