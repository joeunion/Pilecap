"""Escalation as data: the management surface, the closed sets, and the kinds.

The policy CRUD is deliberately the *template* CRUD again — created once,
revised into a new row, retired rather than edited — and these tests say so by
asserting the same properties: a second create under one name is a `409`, a
revision is a `201` with a **new** id beside the old row, and retiring puts the
previous version back in service. A management surface that looked like the
templates' but behaved differently would be worse than one that looked
different.

What is new, and is most of this file, is the **closed sets**. A policy is JSON
in a column, so the only thing standing between a typo and an escalation that
does nothing at 3am is `services._policy_steps` — and it is checked here from
both sides: through the door, where a bad step must be a `400` naming
`steps.<n>.<field>`, and through the service, where a caller that skipped the
schema entirely gets the same refusal.

The walk itself — one run, the waits, the escalation, consent per step — is in
`test_escalation.py`, against a real Temporal server. This file never starts a
run: `recorded_workflow_starts` is why a `send()` here can commit without one.
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from typing import Any

import pytest
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.comms import providers
from apps.comms.models import (
    Category,
    Channel,
    DeliveryPolicy,
    Message,
    MessageTemplate,
    Recipient,
    SuppressionSurge,
)
from apps.comms.policies import ACTION_PROSE
from apps.comms.providers import STATUS_PROVIDER
from apps.comms.selectors import get_policy, list_policies
from apps.comms.services import (
    SURGE_THRESHOLD,
    close_suppression_surge,
    create_policy,
    create_template,
    retire_policy,
    retire_template,
    revise_policy,
    revise_template,
    send,
    start_suppression_surge,
)
from apps.comms.tests.conftest import Branches, make_recipient, make_template
from apps.connections.models import Connection
from apps.connections.services import create_connection
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.exceptions import Conflict, Forbidden, Invalid, NotFound
from apps.core.models import Tenant
from config.api import as_the_door_renders

pytestmark = pytest.mark.django_db

JSON = "application/json"
LIST_URL = "/api/v1/delivery-policies/"
TEMPLATE_LIST_URL = "/api/v1/templates/"

#: Measured at ten policy rows, not guessed: the session row + the user row +
#: 1 SAVEPOINT (ATOMIC_REQUESTS) + the membership lookup TenantMiddleware makes
#: + the acting-org lookup beside it + COUNT + the page + 1 RELEASE SAVEPOINT.
#: `DeliveryPolicy` is tenant-scoped and its steps are a column, so there is no
#: relation to follow and no N+1 to hide — which is exactly what this pin is
#: here to keep true if somebody later makes steps a table.
# ADR core-18 took one statement OFF this pin: the default list issues no
# COUNT any more — `has_more` comes from fetching one row more than asked
# for. `?include_count=true` puts it back, and costs exactly one more.
# PR4.b (ADR core-27) adds exactly THREE: a read is a permission now, so the
# selector behind this door calls `require(actor, "<kind>.read", ...)` once,
# and the first `require` of a request reads the actor's three permission
# tables — the memberships on the chain, their grants, and the delta rows for
# the role keys those name. Three and not six because PR0's memo rides on the
# actor: a second `require` in the same request costs nothing, which is what a
# route that fetches through a `get_` and then calls a service is standing on.
LIST_QUERY_BUDGET = 10


def body(response: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(response.content)
    return parsed


def steps(**overrides: Any) -> list[dict[str, Any]]:
    """The worked two-step escalation: text them, wait, then email them."""
    first = {
        "channel": "sms",
        "template": "texted",
        "wait_seconds": 600,
        "escalate_when": "delivered",
    }
    second = {"channel": "email", "template": "receipt", "wait_seconds": 0, "escalate_when": "none"}
    first.update(overrides)
    return [first, second]


@pytest.fixture
def templates(owner_actor: Actor) -> None:
    """The two templates every policy in this module names."""
    make_template(actor=owner_actor)
    make_template(
        actor=owner_actor,
        name="texted",
        channel=Channel.SMS,
        subject="",
        body="Hello {{ name }}, please look at your account.",
    )


# --- C2b-1: the management surface ------------------------------------------------


def test_the_policy_routes_are_where_the_router_put_them() -> None:
    assert reverse("api:policies-list") == LIST_URL
    assert reverse("api:policy-create") == LIST_URL


def test_create_revise_get_list_and_retire_over_the_wire(
    api: Client, tenant: Tenant, owner: User, templates: None
) -> None:
    """C2b-1. The whole surface, through the door a person uses."""
    api.force_login(owner)

    created = api.post(
        LIST_URL, data=json.dumps({"name": "oncall", "steps": steps()}), content_type=JSON
    )
    assert created.status_code == 201
    first = body(created)
    assert first["name"] == "oncall"
    assert first["version"] == 1
    assert first["is_active"] is True
    assert first["steps"] == [
        {"channel": "sms", "template": "texted", "wait_seconds": 600, "escalate_when": "delivered"},
        {"channel": "email", "template": "receipt", "wait_seconds": 0, "escalate_when": "none"},
    ]

    # A second create under the name is a conflict, not a silent v2.
    assert (
        api.post(
            LIST_URL, data=json.dumps({"name": "oncall", "steps": steps()}), content_type=JSON
        ).status_code
        == 409
    )

    revised = api.post(
        f"{LIST_URL}oncall/versions/",
        data=json.dumps({"steps": steps(wait_seconds=60)}),
        content_type=JSON,
    )
    assert revised.status_code == 201
    second = body(revised)
    assert second["version"] == 2
    assert second["id"] != first["id"], "a revision is a new row, never an edit"
    assert second["steps"][0]["wait_seconds"] == 60

    # v1 is still exactly where it was, and the list is newest version first
    # within the name — which the route restates because `ordered_by` replaces
    # the ordering outright. Pinned, so that ordering stops being whatever the
    # database felt like.
    assert len(api.get(LIST_URL).json()["items"]) == 2
    assert [row["version"] for row in api.get(LIST_URL).json()["items"]] == [2, 1]

    # The name resolves to the live version.
    live = api.get(f"{LIST_URL}oncall/")
    assert live.status_code == 200
    assert body(live)["version"] == 2

    retired = api.post(f"{LIST_URL}oncall/retire/", content_type=JSON)
    assert retired.status_code == 200
    assert body(retired)["is_active"] is False
    # …and the name falls back to v1, which is what retiring means.
    assert body(api.get(f"{LIST_URL}oncall/"))["version"] == 1


def test_the_policy_list_is_paginated_and_costs_what_it_was_measured_at(
    api: Client,
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    templates: None,
    django_assert_num_queries: Any,
) -> None:
    """C2b-1's pin. Ten rows cost the same as one, or this fails."""
    for index in range(10):
        create_policy(tenant=tenant, actor=owner_actor, name=f"policy-{index}", steps=steps())
    api.force_login(owner)
    with django_assert_num_queries(LIST_QUERY_BUDGET):
        response = api.get(LIST_URL)
    assert response.status_code == 200
    assert len(body(response)["items"]) == 10


def test_another_tenants_policies_are_absent(
    api: Client,
    tenant: Tenant,
    other_tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    stranger_actor: Actor,
    templates: None,
) -> None:
    """The sibling every list test here owes: scoping, not filtering."""
    make_template(actor=stranger_actor)
    create_policy(tenant=tenant, actor=owner_actor, name="ours", steps=[steps()[1]])
    create_policy(tenant=other_tenant, actor=stranger_actor, name="theirs", steps=[steps()[1]])
    api.force_login(owner)
    assert [row["name"] for row in api.get(LIST_URL).json()["items"]] == ["ours"]
    assert api.get(f"{LIST_URL}theirs/").status_code == 404


def test_the_mcp_twins_answer_with_the_same_body(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor, templates: None
) -> None:
    """C2b-1's second half: door parity, proved by shape and not by existence.

    The tools are called as functions against a fake context, which is how every
    MCP test in this repository is written — and the assertion is that the
    machine door hands back the *same object* the human door does, key for key.
    """
    from apps.comms.tests.test_mcp import context_for, tool

    created = create_policy(tenant=tenant, actor=owner_actor, name="oncall", steps=steps())
    ctx = context_for(owner, tenant, owner_actor.org)

    api.force_login(owner)
    over_http = body(api.get(f"{LIST_URL}oncall/"))
    over_mcp = tool("get_policy")(ctx, name="oncall").model_dump(mode="json")
    # THE ONE ENCODER. This used to call a local `_to_the_millisecond`
    # that reimplemented the truncation rule; the machine side now goes through
    # the same `config/api.py` encoder the HTTP door renders with, which is what
    # `config/mcp.py` puts every real answer through. `over_http` needs no call:
    # it IS the door's output. Equality is exact on every key, timestamps
    # included — the relationship no longer has to be pinned because there is no
    # longer a relationship, only one rendering.
    assert as_the_door_renders(json.loads(json.dumps(over_mcp, default=str))) == over_http, (
        "one row, one shape, both doors"
    )
    assert str(over_mcp["id"]) == str(created.pk)

    listed = tool("list_policies")(ctx)
    assert len(listed.items) == 1
    assert listed.items[0].name == "oncall"


def test_the_five_policy_tools_are_in_introspect() -> None:
    """C2b-9. The machine door's map has to show them, or an agent cannot find them."""
    out = io.StringIO()
    call_command("introspect", stdout=out)
    payload = json.loads(out.getvalue())
    tools = {str(one["name"]) for one in payload["tools"]}
    assert {
        "list_policies",
        "get_policy",
        "create_policy",
        "revise_policy",
        "retire_policy",
    } <= tools


# --- C2b-2: the closed sets -------------------------------------------------------


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"escalate_when": "opened"}, "steps.0.escalate_when"),
        ({"escalate_when": "clicked"}, "steps.0.escalate_when"),
        ({"channel": "carrier-pigeon"}, "steps.0.channel"),
        ({"template": "no-such-template"}, "steps.0.template"),
    ],
)
def test_a_step_outside_the_closed_sets_is_a_400_naming_the_field(
    api: Client, tenant: Tenant, owner: User, templates: None, override: Any, field: str
) -> None:
    """C2b-2. Every refusal names `steps.<n>.<field>`, so a caller can fix it.

    `opened` and `clicked` are in here on purpose rather than as arbitrary bad
    input: they are the obvious next two escalation triggers and they are a
    **named deferral** — they ship with the tracking rung that can observe them.
    Until then an escalation that waited for them would never escalate, so the
    set refuses them by name.
    """
    api.force_login(owner)
    response = api.post(
        LIST_URL,
        data=json.dumps({"name": "wrong", "steps": steps(**override)}),
        content_type=JSON,
    )
    assert response.status_code == 400
    detail = body(response)
    assert detail["code"] == "invalid"
    assert field in detail["errors"]
    assert not DeliveryPolicy.objects.for_tenant(tenant).exists()


def test_a_step_naming_a_template_on_another_channel_is_refused(
    tenant: Tenant, owner_actor: Actor, templates: None
) -> None:
    """C2b-2's third case, at the service: the mismatch, not the absence.

    `receipt` exists and is an email template; asking for it on the SMS step is
    a policy that would have rendered an email body into a text message. Caught
    when the policy is *written*, which is the only time anybody is looking.
    """
    with pytest.raises(Invalid) as raised:
        create_policy(
            tenant=tenant,
            actor=owner_actor,
            name="mismatched",
            steps=[{"channel": "sms", "template": "receipt", "escalate_when": "none"}],
        )
    assert "steps.0.template" in raised.value.errors
    assert "email" in raised.value.errors["steps.0.template"][0]


def test_every_bad_step_is_reported_at_once(
    tenant: Tenant, owner_actor: Actor, templates: None
) -> None:
    """Three mistakes come back as three complaints, not as three round trips."""
    with pytest.raises(Invalid) as raised:
        create_policy(
            tenant=tenant,
            actor=owner_actor,
            name="all-wrong",
            steps=[
                {"channel": "pigeon", "template": "texted", "escalate_when": "opened"},
                {"channel": "email", "template": "missing", "escalate_when": "none"},
            ],
        )
    assert set(raised.value.errors) == {
        "steps.0.channel",
        "steps.0.escalate_when",
        "steps.1.template",
    }


def test_a_policy_with_no_steps_reaches_nobody_and_is_refused(
    tenant: Tenant, owner_actor: Actor, templates: None
) -> None:
    with pytest.raises(Invalid) as raised:
        create_policy(tenant=tenant, actor=owner_actor, name="empty", steps=[])
    assert "steps" in raised.value.errors


def test_only_an_owner_or_an_admin_writes_a_policy(
    tenant: Tenant, member_actor: Actor, templates: None
) -> None:
    """A policy decides how hard the product chases people. That takes a role.

    The same asymmetry `policies.py` draws for templates and consent: anybody in
    the tenant may *send*, and only a privileged member changes what the product
    is allowed to say or how insistently it says it.
    """
    from apps.core.exceptions import Forbidden

    with pytest.raises(Forbidden):
        create_policy(tenant=tenant, actor=member_actor, name="nope", steps=[steps()[1]])


def test_revising_a_policy_that_does_not_exist_is_not_found(
    tenant: Tenant, owner_actor: Actor, templates: None
) -> None:
    with pytest.raises(NotFound):
        revise_policy(tenant=tenant, actor=owner_actor, name="ghost", steps=[steps()[1]])


def test_retiring_twice_is_a_no_op_rather_than_a_conflict(
    tenant: Tenant, owner_actor: Actor, templates: None
) -> None:
    """A client retrying a request it never saw the answer to is not told it collided."""
    policy = create_policy(tenant=tenant, actor=owner_actor, name="oncall", steps=steps())
    once = retire_policy(tenant=tenant, actor=owner_actor, policy=policy)
    twice = retire_policy(tenant=tenant, actor=owner_actor, policy=once)
    assert (once.is_active, twice.is_active) == (False, False)


def test_a_name_with_no_active_version_stops_resolving(
    tenant: Tenant, owner_actor: Actor, templates: None
) -> None:
    """Retire the only version and the name is `NotFound` — fail closed, not fall back."""
    policy = create_policy(tenant=tenant, actor=owner_actor, name="oncall", steps=steps())
    retire_policy(tenant=tenant, actor=owner_actor, policy=policy)
    with pytest.raises(NotFound):
        get_policy(tenant=tenant, name="oncall", actor=owner_actor)
    assert list_policies(tenant=tenant, actor=owner_actor).filter(name="oncall").count() == 1, (
        "still readable"
    )


def test_creating_a_second_policy_under_one_name_is_a_conflict(
    tenant: Tenant, owner_actor: Actor, templates: None
) -> None:
    create_policy(tenant=tenant, actor=owner_actor, name="oncall", steps=steps())
    with pytest.raises(Conflict):
        create_policy(tenant=tenant, actor=owner_actor, name="oncall", steps=steps())


# --- C2b-7: the edges around send(policy=) ----------------------------------------


def test_naming_a_policy_and_a_channel_at_once_is_refused(
    api: Client,
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    recipient: Recipient,
    templates: None,
    recorded_workflow_starts: None,
) -> None:
    """C2b-7. Two different instructions in one body is a 400 naming both."""
    create_policy(tenant=tenant, actor=owner_actor, name="oncall", steps=steps())
    api.force_login(owner)
    response = api.post(
        "/api/v1/messages/",
        data=json.dumps(
            {
                "recipient_id": str(recipient.pk),
                "policy": "oncall",
                "channel": "email",
                "template": "receipt",
                "context": {"name": "Ada"},
            }
        ),
        content_type=JSON,
    )
    assert response.status_code == 400
    detail = body(response)
    assert set(detail["errors"]) == {"channel", "template"}
    assert not Message.objects.for_tenant(tenant).exists()


def test_a_send_that_names_neither_a_template_nor_a_policy_is_refused(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, templates: None
) -> None:
    with pytest.raises(Invalid) as raised:
        send(
            recipient=recipient,
            context={"name": "Ada"},
            tenant=tenant,
            actor=owner_actor,
        )
    assert "template" in raised.value.errors


def test_a_send_with_no_policy_is_what_it_always_was(
    api: Client,
    tenant: Tenant,
    owner: User,
    recipient: Recipient,
    templates: None,
    recorded_workflow_starts: None,
) -> None:
    """C2b-7's second half. **The no-policy body, field for field.**

    Pinned as an exact key set and exact values rather than "it still works",
    because "unchanged" is the claim and a claim about a wire shape is only as
    good as the pin under it. The three policy columns exist on the row and are
    deliberately **not** on `MessageOut` — see the note in `test_the_row`.
    """
    api.force_login(owner)
    response = api.post(
        "/api/v1/messages/",
        data=json.dumps(
            {
                "recipient_id": str(recipient.pk),
                "template": "receipt",
                "context": {"name": "Ada"},
            }
        ),
        content_type=JSON,
    )
    assert response.status_code == 201
    sent = body(response)
    assert set(sent) == {
        "id",
        "recipient_id",
        "recipient_email",
        "organization_id",
        "organization_slug",
        "template_name",
        "template_version",
        "channel",
        "category",
        "status",
        "suppressed_reason",
        "provider",
        "provider_message_id",
        "subject",
        "error",
        "correlation_id",
        "created_at",
        # When it is DUE to go out, `None` for one that went at once.
        # On the wire because a support agent who cannot tell a message waiting
        # six hours from one waiting six seconds reads the Temporal UI instead,
        # which is not a product surface.
        "send_at",
        "sent_at",
        "delivered_at",
        "bounced_at",
        # ADR comms-9: which kind of bounce, when there was one. On the wire
        # because "it bounced and we did not suppress" is the first question the
        # hard/soft split creates, and a support agent who cannot answer it from
        # the message log answers it from a shell.
        "bounce_kind",
    }
    assert sent["channel"] == "email", "an omitted channel still means email"
    assert sent["status"] == "queued"
    assert sent["template_name"] == "receipt"

    row = Message.objects.for_tenant(tenant).get()
    assert (row.policy_name, row.policy_version, row.policy_step) == ("", None, None)


def test_the_row_records_which_step_of_which_policy_it_was(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    templates: None,
    recorded_workflow_starts: None,
) -> None:
    """C2b-3's row half, without a worker: step 1 carries its provenance.

    The three columns are on the **row** and not on `MessageOut`, which is a
    decision rather than an omission: C2b-7 pins the no-policy REST body as
    unchanged, and C2b-10's budget list names only `PolicyOut`. Publishing the
    provenance on the message log is a real gap and it is named here rather than
    smuggled in — a client cannot yet see that a message was step 2 of `oncall`.
    """
    recipient.phone = "+15550001111"
    recipient.save(update_fields=["phone"])
    create_policy(tenant=tenant, actor=owner_actor, name="oncall", steps=steps())
    message = send(
        recipient=recipient,
        context={"name": "Ada"},
        tenant=tenant,
        actor=owner_actor,
        policy="oncall",
    )
    assert message.channel == "sms", "step 1 decides the channel, not the caller"
    assert message.template_name == "texted"
    assert (message.policy_name, message.policy_version, message.policy_step) == ("oncall", 1, 1)
    assert message.delivery_workflow_id, "one run, and the row points at it"


# --- C2b-8: kinds, not vendors ----------------------------------------------------


def test_slack_is_nowhere_in_the_channel_kinds() -> None:
    """C2b-8, ADR comms-6. **A vendor's name must not be a column value.**

    Both halves: the kinds are exactly four and `slack` is not among them, and
    the word appears nowhere in the whole `introspect` payload — the map the
    field test and every agent read. The second assertion is the one that would
    have caught a half-done rename: a `Channel` member gone but a template, a
    tool description or a policy step still saying `slack` is a product that has
    two names for one thing.
    """
    assert {choice[0] for choice in Channel.choices} == {"email", "sms", "chat", "push"}
    assert "slack" not in Channel.values

    out = io.StringIO()
    call_command("introspect", stdout=out)
    assert "slack" not in out.getvalue().lower()


def test_a_recipient_patch_sets_the_phone_it_will_be_texted_on(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """C2b-8. An address is contact data, and the only PATCH in the app carries it."""
    recipient = make_recipient(actor=owner_actor, email="ada@example.com")
    api.force_login(owner)
    response = api.patch(
        f"/api/v1/recipients/{recipient.pk}/",
        data=json.dumps({"phone": "+15550001111", "chat_handle": "@ada"}),
        content_type=JSON,
    )
    assert response.status_code == 200
    assert body(response)["phone"] == "+15550001111"
    assert body(response)["chat_handle"] == "@ada"
    recipient.refresh_from_db()
    assert recipient.phone == "+15550001111"


def test_the_fake_sms_transport_carries_a_text_and_says_it_was_fake(
    tenant: Tenant, owner_actor: Actor, templates: None
) -> None:
    """C2b-8. The SMS path end to end, with no vendor, no account and no network.

    `provider="fake-sms"` on the returned handle is the property that matters:
    no message log in any deployment ever claims a real vendor sent something
    this class sent.
    """
    providers.fake_sms_outbox.clear()
    recipient = make_recipient(actor=owner_actor, email="ada@example.com")
    recipient.phone = "+15550001111"
    recipient.save(update_fields=["phone"])
    message = Message(
        tenant=tenant,
        organization=owner_actor.org,
        recipient=recipient,
        template=make_template(actor=owner_actor, name="second-text", channel=Channel.SMS),
        template_name="second-text",
        template_version=1,
        channel=Channel.SMS,
        category=Category.TRANSACTIONAL,
    )
    sent = providers.get_channel("sms").send(message=message, subject="", body="Please look.")
    assert sent.provider == "fake-sms"
    assert providers.fake_sms_outbox[-1].to == "+15550001111"
    assert providers.fake_sms_outbox[-1].body == "Please look."


def test_the_fake_refuses_a_recipient_with_no_number(
    tenant: Tenant, owner_actor: Actor, templates: None
) -> None:
    """Fail closed: a text with no number is a message that went nowhere."""
    recipient = make_recipient(actor=owner_actor, email="ada@example.com")
    message = Message(
        tenant=tenant,
        organization=owner_actor.org,
        recipient=recipient,
        template=make_template(actor=owner_actor, name="third-text", channel=Channel.SMS),
        template_name="third-text",
        template_version=1,
        channel=Channel.SMS,
        category=Category.TRANSACTIONAL,
    )
    with pytest.raises(Invalid) as raised:
        providers.get_channel("sms").send(message=message, subject="", body="Please look.")
    assert "phone" in raised.value.errors


# --- W55-comms: a tenant-wide WRITE is asked at the ROOT ---------------------------
#
# Rule 55's founding class, in the app it was measured in. A `message_template`, a
# `delivery_policy` and a `suppression_surge` carry no `organization` column: they
# are the TENANT's, not a branch's. So a `require` that names no node — or names
# the row, which carries none — resolves at the ACTING HAT, and an administrator
# of one branch holds `*` there. That administrator could therefore write the
# words the whole tenant sends, the escalations it runs and the tripwire's own
# memory, over the wire, from a leaf they administer.
#
# The eight sites now pass `root_organization(tenant=tenant)`, and these two tests
# are what that sentence means: the same eight acts, by an administrator whose
# only membership is at `Seller A`, refused with each key's own sentence — and
# unchanged for everybody who was already right, at the root and below it.


#: The two surge verbs, named because they are the pair whose answer does NOT
#: move: `can_record_surge` refuses every membership (ADR comms-9 — a
#: surge is observed, never declared), so a branch admin was already refused
#: there and is refused for a second reason now. They are driven anyway, because
#: "this key is unreachable to a person" is a property that has to be asserted
#: rather than assumed, and because the node they ask at is what moved.
SURGE_KEYS = ("suppression_surge.create",)


#: This module's own shared secret for the ESP connection, on a line of its own
#: so the pragma stays ON it — an inline pragma after a `credentials={...}` dict
#: is a pragma `ruff format` moves onto the closing brace, where the scanner does
#: not read it. `test_suppression_wall.py`'s shape, and its reason: the baseline
#: is a shared file at the root of the tree and this app owns neither it nor the
#: right to conflict four other lanes on it.
ESP_SECRET = "w55-comms-signs-with-its-own-string"  # pragma: allowlist secret


@pytest.fixture
def esp(tenant: Tenant, owner_actor: Actor) -> Connection:
    """The tenant's email provider connection — what a surge names."""
    return create_connection(
        tenant=tenant,
        actor=owner_actor,
        provider=STATUS_PROVIDER,
        name="Transactional email",
        credentials={"webhook_secret": ESP_SECRET},
    )


def branch_admin_of(branches: Branches) -> Actor:
    """The administrator of `Seller A`, and of nothing above it.

    `conftest.branches` gives this person an `admin` membership at a CHILD of the
    root. They administer that branch: everything in it, nothing over it.
    """
    return actor_for(user=branches.manager, tenant=branches.tenant, org=branches.seller_a)


def the_eight_tenant_wide_writes(
    *,
    tenant: Tenant,
    actor: Actor,
    template: MessageTemplate,
    policy: DeliveryPolicy,
    connection: Connection,
    surge: SuppressionSurge,
    suffix: str,
) -> tuple[tuple[str, str, Callable[[], Any]], ...]:
    """The eight sites rule 55 counted, as (service name, key, one call).

    Built as thunks rather than driven inline so the same list is used for the
    refusals and for the acts that must still land — one list, two directions,
    and no chance of the positive half drifting to seven.
    """
    return (
        (
            "create_template",
            "message_template.create",
            lambda: create_template(
                tenant=tenant, actor=actor, name=f"new-{suffix}", body="Hello {{ name }}."
            ),
        ),
        (
            "revise_template",
            "message_template.create",
            lambda: revise_template(
                tenant=tenant, actor=actor, name=template.name, body="Rewritten by {{ name }}."
            ),
        ),
        (
            "retire_template",
            "message_template.retire",
            lambda: retire_template(tenant=tenant, actor=actor, template=template),
        ),
        (
            "create_policy",
            "delivery_policy.create",
            lambda: create_policy(
                tenant=tenant, actor=actor, name=f"escalation-{suffix}", steps=[steps()[1]]
            ),
        ),
        (
            "revise_policy",
            "delivery_policy.create",
            lambda: revise_policy(tenant=tenant, actor=actor, name=policy.name, steps=[steps()[1]]),
        ),
        (
            "retire_policy",
            "delivery_policy.retire",
            lambda: retire_policy(tenant=tenant, actor=actor, policy=policy),
        ),
        (
            "start_suppression_surge",
            "suppression_surge.create",
            lambda: start_suppression_surge(
                tenant=tenant, actor=actor, connection=connection, count=SURGE_THRESHOLD
            ),
        ),
        (
            "close_suppression_surge",
            "suppression_surge.create",
            lambda: close_suppression_surge(tenant=tenant, actor=actor, surge=surge, count=0),
        ),
    )


def test_a_branch_administrator_may_not_configure_the_tenants_templates_policies_or_surges(
    tenant: Tenant,
    branches: Branches,
    owner_actor: Actor,
    admin_actor: Actor,
    member_actor: Actor,
    esp: Connection,
    templates: None,
) -> None:
    """Eight acts on the tenant's own configuration, by an administrator of one branch.

    Each refusal is asserted against `ACTION_PROSE[key]` rather than a quoted
    string, so the test says "the key's own sentence" and cannot come to mean
    "these words" — and a bare `pytest.raises(Forbidden)` would pass on any wall,
    including a `Conflict` mis-typed as one.

    **Five states, and the two positives are not the same two everywhere.** For
    the six template and policy acts the row comes back for a ROOT admin and for
    the owner. For the two surge acts it comes back for **`system` only**:
    `can_record_surge` refuses every membership, so the answer for the owner and
    the root admin is `Forbidden` there and always was. That asymmetry is asserted
    rather than worked around, because a test that let the surge pair quietly fall
    out of the positive half would stop measuring six of the eight sites the day
    somebody moved them.

    A plain `member` at the root is refused throughout, unchanged.
    """
    branch_admin = branch_admin_of(branches)
    system = system_actor(tenant=tenant, org=branches.hq)

    template = make_template(actor=owner_actor, name="house-style")
    policy = create_policy(tenant=tenant, actor=owner_actor, name="oncall", steps=[steps()[1]])
    surge = start_suppression_surge(
        tenant=tenant, actor=system, connection=esp, count=SURGE_THRESHOLD
    )

    def attempts(actor: Actor, suffix: str) -> tuple[tuple[str, str, Callable[[], Any]], ...]:
        return the_eight_tenant_wide_writes(
            tenant=tenant,
            actor=actor,
            template=template,
            policy=policy,
            connection=esp,
            surge=surge,
            suffix=suffix,
        )

    # THE BRANCH ADMINISTRATOR — all eight refused, each with its own sentence.
    for name, key, attempt in attempts(branch_admin, "branch"):
        with pytest.raises(Forbidden) as refused:
            attempt()
        assert refused.value.detail == ACTION_PROSE[key], name

    # A PLAIN MEMBER at the root — refused throughout, and refused before.
    for name, key, attempt in attempts(member_actor, "member"):
        with pytest.raises(Forbidden) as refused_member:
            attempt()
        assert refused_member.value.detail == ACTION_PROSE[key], name

    # NOTHING MOVED. A refusal that arrived after the write would leave the
    # branch admin's rewrite standing and the test green on the sentence alone.
    template.refresh_from_db()
    policy.refresh_from_db()
    surge.refresh_from_db()
    assert template.is_active is True
    assert template.body == "Hello {{ name }}, here is your receipt."
    assert policy.is_active is True
    assert surge.ended_at is None
    assert MessageTemplate.objects.for_tenant(tenant).filter(name="new-branch").count() == 0
    assert DeliveryPolicy.objects.for_tenant(tenant).filter(name="escalation-branch").count() == 0

    # THE ROOT ADMIN and THE OWNER still get the row for the six that are a
    # person's to do; `system` gets it for the two that are not.
    for actor, suffix in ((admin_actor, "root-admin"), (owner_actor, "owner")):
        for name, key, attempt in attempts(actor, suffix):
            if key in SURGE_KEYS:
                with pytest.raises(Forbidden) as observed_only:
                    attempt()
                assert observed_only.value.detail == ACTION_PROSE[key], name
                continue
            assert attempt() is not None, name
        # Each pass retires the pair, so the next actor gets them back.
        template = revise_template(
            tenant=tenant,
            actor=owner_actor,
            name="house-style",
            body="Hello {{ name }}, here is your receipt.",
        )
        policy = create_policy(
            tenant=tenant, actor=owner_actor, name=f"oncall-{suffix}", steps=[steps()[1]]
        )

    # SYSTEM — the tripwire's own two, which nobody else may reach.
    closed = close_suppression_surge(tenant=tenant, actor=system, surge=surge, count=0)
    assert closed.ended_at is not None
    reopened = start_suppression_surge(
        tenant=tenant, actor=system, connection=esp, count=SURGE_THRESHOLD
    )
    assert reopened.pk != surge.pk


def test_a_branch_administrator_is_refused_the_configuration_routes_at_both_doors(
    api: Client,
    tenant: Tenant,
    branches: Branches,
    owner_actor: Actor,
    templates: None,
) -> None:
    """The same wall through the two doors a caller actually holds.

    REST and MCP, because rule 46's promise is that the two answer identically —
    and because the review that named this class drove the REST door and got a
    `201`. The MCP door renders a refusal as one line of text rather than as a
    JSON body (`core.mcp.tool_call`), so the assertion there is that the key's
    own sentence is in that line, which is the same claim in the shape that wire
    carries.
    """
    from mcp.server.mcpserver.exceptions import ToolError

    from apps.comms.tests.test_mcp import context_for, tool

    branch_admin = branch_admin_of(branches)
    api.force_login(branches.manager)

    created = api.post(
        TEMPLATE_LIST_URL,
        data=json.dumps({"name": "captured", "body": "Hello {{ name }}."}),
        content_type=JSON,
    )
    assert created.status_code == 403, created.content
    assert body(created)["code"] == "forbidden"
    assert body(created)["detail"] == ACTION_PROSE["message_template.create"]

    policy_created = api.post(
        LIST_URL,
        data=json.dumps({"name": "captured", "steps": [steps()[1]]}),
        content_type=JSON,
    )
    assert policy_created.status_code == 403, policy_created.content
    assert body(policy_created)["detail"] == ACTION_PROSE["delivery_policy.create"]

    ctx = context_for(branches.manager, tenant, branch_admin.org)
    with pytest.raises(ToolError) as over_mcp:
        tool("create_template")(ctx, name="captured", body="Hello {{ name }}.")
    assert ACTION_PROSE["message_template.create"] in str(over_mcp.value)

    with pytest.raises(ToolError) as policy_over_mcp:
        tool("create_policy")(ctx, name="captured", steps=[])
    assert ACTION_PROSE["delivery_policy.create"] in str(policy_over_mcp.value)

    # Nothing was written by either door.
    assert not MessageTemplate.objects.for_tenant(tenant).filter(name="captured").exists()
    assert not DeliveryPolicy.objects.for_tenant(tenant).filter(name="captured").exists()
