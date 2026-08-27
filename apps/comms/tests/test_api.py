"""The comms API, end to end — and the door's half of the consent story.

The load-bearing test in this file is the pair
`test_a_marketing_send_without_consent_is_201_and_suppressed` /
`…_and_the_same_send_goes_once_they_consent`: a refusal comes back **201 with a
row**, not as an error, and the identical request after consent delivers. One
without the other proves nothing — the first alone would pass if the door
suppressed everything.

Everything else is the shape every list endpoint in a product owes: anonymous
is refused, the envelope is paginated, the rows are scoped to the acting tenant
*and* the acting hat, a second tenant's rows are absent, a sibling branch's are
absent, and the query count is pinned so an N+1 is a failure rather than a slow
page.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.services import issue_token
from apps.comms.models import Message, MessageTemplate, Recipient
from apps.comms.tests.conftest import Branches, make_preference, make_recipient, make_template

# The shared fixtures' own password, imported rather than restated: a second
# copy of a credential-shaped string is a second thing to keep out of the
# secrets baseline, and this test needs the same one those fixtures use.
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.audit import AuditEntry
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import add_membership, root_organization
from apps.events.models import Event

pytestmark = pytest.mark.django_db

MESSAGES_URL = "/api/v1/messages/"
JSON = "application/json"

# Measured, not guessed, at ten rows: the session row + the user row (session
# authentication) + 1 SAVEPOINT (ATOMIC_REQUESTS) + the membership lookup
# TenantMiddleware makes for the tenant + the membership lookup it makes for the
# acting org + the page + 1 RELEASE SAVEPOINT.
#
# `select_related("recipient", "organization")` is what keeps the page at one
# query no matter how many rows come back — `MessageOut` walks both for every
# row. Take either out and this is what fails.
# ADR core-18 took one statement OFF this pin: the default list issues no
# COUNT any more — `has_more` comes from fetching one row more than asked
# for. `?include_count=true` puts it back, and costs exactly one more.
LIST_QUERY_BUDGET = 7


def _body(response: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(response.content)
    return parsed


def _send_body(recipient: Recipient, template: str = "receipt", **context: Any) -> str:
    return json.dumps(
        {
            "recipient_id": str(recipient.pk),
            "template": template,
            "context": context or {"name": "Ada"},
            "channel": "email",
        }
    )


# --- the routes are where the router put them ---------------------------------


def test_the_routes_are_where_the_router_put_them() -> None:
    assert reverse("api:message-list") == MESSAGES_URL
    assert reverse("api:message-send") == MESSAGES_URL
    assert reverse("api:message-detail", kwargs={"message_id": "x" * 36}).startswith(MESSAGES_URL)


def test_anonymous_cannot_list(api: Client) -> None:
    assert api.get(MESSAGES_URL).status_code == 401


def test_anonymous_cannot_send(api: Client, recipient: Recipient) -> None:
    assert api.post(MESSAGES_URL, data=_send_body(recipient), content_type=JSON).status_code == 401


# --- sending -------------------------------------------------------------------


def test_a_transactional_send_is_201_and_queued(
    api: Client, owner: User, recipient: Recipient, receipt: MessageTemplate
) -> None:
    api.force_login(owner)
    response = api.post(MESSAGES_URL, data=_send_body(recipient), content_type=JSON)
    assert response.status_code == 201, response.content
    body = _body(response)
    assert body["status"] == Message.Status.QUEUED
    assert body["suppressed_reason"] == ""
    assert body["template_name"] == "receipt"
    assert body["template_version"] == 1
    assert body["subject"] == "Your receipt, Ada"
    assert body["recipient_email"] == recipient.email


def test_a_marketing_send_without_consent_is_201_and_suppressed(
    api: Client, owner: User, recipient: Recipient, newsletter: MessageTemplate
) -> None:
    """**Not an error.** The product did what was asked; the answer was no."""
    api.force_login(owner)
    response = api.post(
        MESSAGES_URL, data=_send_body(recipient, template="newsletter"), content_type=JSON
    )
    assert response.status_code == 201, response.content
    body = _body(response)
    assert body["status"] == Message.Status.SUPPRESSED
    assert body["suppressed_reason"] == Message.SuppressedReason.NO_CONSENT


def test_the_same_marketing_send_goes_once_they_consent(
    api: Client,
    owner: User,
    owner_actor: Actor,
    recipient: Recipient,
    newsletter: MessageTemplate,
) -> None:
    """The other half of the pair. Without this, suppressing everything would pass."""
    make_preference(actor=owner_actor, recipient=recipient, consented=True)
    api.force_login(owner)
    response = api.post(
        MESSAGES_URL, data=_send_body(recipient, template="newsletter"), content_type=JSON
    )
    assert response.status_code == 201, response.content
    assert _body(response)["status"] == Message.Status.QUEUED


def test_a_context_missing_a_required_variable_is_400_and_writes_no_row(
    api: Client, tenant: Tenant, owner: User, recipient: Recipient, receipt: MessageTemplate
) -> None:
    api.force_login(owner)
    response = api.post(
        MESSAGES_URL,
        data=json.dumps(
            {
                "recipient_id": str(recipient.pk),
                "template": "receipt",
                "context": {},
                "channel": "email",
            }
        ),
        content_type=JSON,
    )
    assert response.status_code == 400, response.content
    body = _body(response)
    assert body["code"] == "invalid"
    assert "name" in body["errors"]
    assert not Message.objects.for_tenant(tenant).exists()


def test_a_template_the_tenant_does_not_have_is_404(
    api: Client, owner: User, recipient: Recipient
) -> None:
    api.force_login(owner)
    response = api.post(
        MESSAGES_URL, data=_send_body(recipient, template="nope"), content_type=JSON
    )
    assert response.status_code == 404
    assert _body(response)["code"] == "not_found"


def test_the_same_send_twice_under_one_idempotency_key_happens_once(
    api: Client, tenant: Tenant, owner: User, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """A client that timed out and retried must not email the person twice."""
    api.force_login(owner)
    first = api.post(
        MESSAGES_URL,
        data=_send_body(recipient),
        content_type=JSON,
        headers={"idempotency-key": "one-send"},
    )
    second = api.post(
        MESSAGES_URL,
        data=_send_body(recipient),
        content_type=JSON,
        headers={"idempotency-key": "one-send"},
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert _body(second) == _body(first)
    assert Message.objects.for_tenant(tenant).count() == 1


# --- reading -------------------------------------------------------------------


def test_the_list_is_paginated_and_scoped_to_the_acting_tenant(
    api: Client,
    tenant: Tenant,
    other_tenant: Tenant,
    other_root_org: Organization,
    owner: User,
    stranger: User,
    recipient: Recipient,
    receipt: MessageTemplate,
) -> None:
    """The sibling that makes the first assertion mean something."""
    from apps.comms.services import send

    mine = send(
        recipient=recipient,
        template="receipt",
        context={"name": "Ada"},
        channel="email",
        tenant=tenant,
        actor=actor_for(user=owner, tenant=tenant, org=root_organization(tenant=tenant)),
    )
    their_actor = actor_for(user=stranger, tenant=other_tenant, org=other_root_org)
    theirs_recipient = make_recipient(actor=their_actor, email="them@example.com")
    make_template(actor=their_actor)
    send(
        recipient=theirs_recipient,
        template="receipt",
        context={"name": "Grace"},
        channel="email",
        tenant=other_tenant,
        actor=their_actor,
    )

    api.force_login(owner)
    response = api.get(MESSAGES_URL)
    assert response.status_code == 200
    body = _body(response)
    assert [row["id"] for row in body["items"]] == [str(mine.pk)]
    assert len(body["items"]) == 1


def test_suppressed_messages_are_in_the_list(
    api: Client, owner: User, recipient: Recipient, newsletter: MessageTemplate
) -> None:
    """A list that hid the refusals would make "why no email?" unanswerable."""
    api.force_login(owner)
    api.post(MESSAGES_URL, data=_send_body(recipient, template="newsletter"), content_type=JSON)
    body = _body(api.get(f"{MESSAGES_URL}?status=suppressed"))
    assert len(body["items"]) == 1
    assert body["items"][0]["suppressed_reason"] == Message.SuppressedReason.NO_CONSENT


def test_another_tenants_message_is_not_found_rather_than_forbidden(
    api: Client,
    other_tenant: Tenant,
    other_root_org: Organization,
    owner: User,
    stranger: User,
) -> None:
    from apps.comms.services import send

    their_actor = actor_for(user=stranger, tenant=other_tenant, org=other_root_org)
    make_template(actor=their_actor)
    theirs = send(
        recipient=make_recipient(actor=their_actor, email="them@example.com"),
        template="receipt",
        context={"name": "Grace"},
        channel="email",
        tenant=other_tenant,
        actor=their_actor,
    )
    api.force_login(owner)
    response = api.get(f"{MESSAGES_URL}{theirs.pk}/")
    assert response.status_code == 404
    assert _body(response)["code"] == "not_found"


def test_list_query_budget(
    api: Client,
    tenant: Tenant,
    owner: User,
    recipient: Recipient,
    receipt: MessageTemplate,
    django_assert_num_queries: Any,
) -> None:
    """Ten rows, and the count must not move with them."""
    from apps.comms.services import send

    acting = actor_for(user=owner, tenant=tenant, org=root_organization(tenant=tenant))
    for index in range(10):
        send(
            recipient=recipient,
            template="receipt",
            context={"name": f"Reader {index}"},
            channel="email",
            tenant=tenant,
            actor=acting,
        )
    api.force_login(owner)
    with django_assert_num_queries(LIST_QUERY_BUDGET):
        api.get(MESSAGES_URL)


# --- the audit trail ------------------------------------------------------------


def test_a_send_through_the_door_leaves_one_audit_row_joined_to_the_event(
    api: Client, tenant: Tenant, owner: User, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """One correlation id joins the request, the audit row, the message and the event."""
    AuditEntry.objects.all().delete()
    api.force_login(owner)
    response = api.post(MESSAGES_URL, data=_send_body(recipient), content_type=JSON)
    assert response.status_code == 201, response.content

    entry = AuditEntry.objects.for_tenant(tenant).get(action="comms.send")
    assert entry.door == "rest"
    assert entry.actor_kind == "human"
    assert entry.actor_user_id == owner.pk
    assert entry.outcome == "ok"
    assert entry.correlation_id

    message = Message.objects.for_tenant(tenant).get(pk=_body(response)["id"])
    event = Event.objects.for_tenant(tenant).get(name="comms.message.queued")
    assert message.correlation_id == entry.correlation_id
    assert event.correlation_id == entry.correlation_id


def test_the_audit_row_does_not_copy_the_context_into_itself(
    api: Client, tenant: Tenant, owner: User, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """`context` is the customer's data. The allow-list is what keeps it out."""
    AuditEntry.objects.all().delete()
    api.force_login(owner)
    api.post(MESSAGES_URL, data=_send_body(recipient, name="Ada Lovelace"), content_type=JSON)
    entry = AuditEntry.objects.for_tenant(tenant).get(action="comms.send")
    assert entry.input["context"] == "[redacted]"
    assert entry.input["template"] == "receipt"


def test_the_machine_door_records_the_token_it_came_in_on(
    api: Client, tenant: Tenant, owner: User, recipient: Recipient, receipt: MessageTemplate
) -> None:
    token, plaintext = issue_token(
        user=owner, tenant=tenant, name="ci", actor=actor_for(user=owner, tenant=tenant)
    )
    AuditEntry.objects.all().delete()
    response = api.post(
        MESSAGES_URL,
        data=_send_body(recipient),
        content_type=JSON,
        headers={"authorization": f"Bearer {plaintext}"},
    )
    assert response.status_code == 201, response.content
    entry = AuditEntry.objects.for_tenant(tenant).get(action="comms.send")
    assert entry.actor_kind == "agent"
    assert entry.actor_token_id == token.pk


# --- the hierarchy --------------------------------------------------------------


def _seed_branches(branches: Branches, template: MessageTemplate) -> dict[str, Message]:
    """One message sent from each node, each addressed to that node's own contact."""
    from apps.comms.services import send

    def one(user: User, org: Organization, label: str) -> Message:
        acting = actor_for(user=user, tenant=branches.tenant, org=org)
        return send(
            recipient=make_recipient(actor=acting, email=f"{label}@example.com"),
            template="receipt",
            context={"name": label},
            channel="email",
            tenant=branches.tenant,
            actor=acting,
        )

    return {
        "a": one(branches.manager, branches.seller_a, "a"),
        "a1": one(branches.clerk, branches.sub_a1, "a1"),
        "b": one(branches.owner, branches.seller_b, "b"),
    }


def test_a_sub_seller_sees_only_its_own_correspondence(
    api: Client, branches: Branches, receipt: MessageTemplate
) -> None:
    seeded = _seed_branches(branches, receipt)
    api.force_login(branches.clerk)
    body = _body(api.get(MESSAGES_URL))
    assert {row["id"] for row in body["items"]} == {str(seeded["a1"].pk)}


def test_a_seller_sees_its_own_and_its_sub_sellers(
    api: Client, branches: Branches, receipt: MessageTemplate
) -> None:
    """Visibility flows downwards. Never sideways, never up."""
    seeded = _seed_branches(branches, receipt)
    api.force_login(branches.manager)
    body = _body(api.get(MESSAGES_URL))
    assert {row["id"] for row in body["items"]} == {
        str(seeded["a"].pk),
        str(seeded["a1"].pk),
    }


def test_the_hat_switches_which_rows_come_back(
    api: Client, branches: Branches, receipt: MessageTemplate
) -> None:
    """One person, two `X-Org` headers, two answers."""
    seeded = _seed_branches(branches, receipt)
    add_membership(
        user=branches.manager,
        tenant=branches.tenant,
        organization=branches.sub_a1,
        role=Membership.Role.MEMBER,
        actor=system_actor(tenant=branches.tenant),
    )
    api.force_login(branches.manager)
    wide = _body(api.get(MESSAGES_URL, headers={"x-org": branches.seller_a.slug}))
    narrow = _body(api.get(MESSAGES_URL, headers={"x-org": branches.sub_a1.slug}))
    assert {row["id"] for row in wide["items"]} == {
        str(seeded["a"].pk),
        str(seeded["a1"].pk),
    }
    assert {row["id"] for row in narrow["items"]} == {str(seeded["a1"].pk)}


def test_a_sub_seller_cannot_address_a_sibling_branchs_contact(
    api: Client, branches: Branches, receipt: MessageTemplate
) -> None:
    """404, not 403: a refusal that said "forbidden" would say the contact exists."""
    theirs = make_recipient(
        actor=actor_for(user=branches.owner, tenant=branches.tenant, org=branches.seller_b),
        email="b-contact@example.com",
    )
    api.force_login(branches.clerk)
    response = api.post(MESSAGES_URL, data=_send_body(theirs), content_type=JSON)
    assert response.status_code == 404
    assert _body(response)["code"] == "not_found"
