"""The management surface: templates, contacts and consent, at both doors.

Three properties carry this file, and each one is a *pair* — the thing the door
does, and the thing it refuses — because either half alone would pass against a
door that did nothing:

* **a template is never edited.** `POST /templates/{name}/versions/` answers
  201 with a **new row** at `version + 1`, v1 comes back byte for byte
  afterwards, and there is no PATCH anywhere in this app that could have moved
  it. The crafted body that tries anyway is a 400 naming the field.
* **consent is five verbs and no settable column.** Granting, revoking, quiet
  hours, suppressing and lifting each change what `send()` does next, which is
  how this file proves they are real rather than decorative — the assertion is
  always on the message, never only on the preference row.
* **both doors say the same thing.** Every capability here exists on MCP with
  the same schema, and the parity table in `test_mcp.py` is what makes a
  missing one a failure. The tools are exercised here against the same rows.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.comms.models import (
    Channel,
    ChannelPreference,
    Message,
    MessageTemplate,
    Recipient,
)
from apps.comms.selectors import get_template
from apps.comms.services import archive_recipient, create_recipient, send
from apps.comms.tests.conftest import (
    Branches,
    make_next_version,
    make_recipient,
    make_template,
)

# The machine door's call harness, imported rather than rebuilt: a second copy
# of "what a tool call looks like without a transport" is a second thing to keep
# true, and `test_mcp.py` is where the parity table it belongs to lives.
from apps.comms.tests.test_mcp import context_for, tool
from apps.core.actor import Actor, actor_for
from apps.core.audit import AuditEntry
from apps.core.exceptions import Conflict, Forbidden, NotFound
from apps.core.models import Tenant

pytestmark = pytest.mark.django_db

JSON = "application/json"
TEMPLATES_URL = "/api/v1/templates/"
RECIPIENTS_URL = "/api/v1/recipients/"

# Measured at ten rows, not guessed. The session row + the user row + the
# SAVEPOINT (ATOMIC_REQUESTS) + TenantMiddleware's tenant membership + its
# acting-org membership + COUNT + the page + the RELEASE. `MessageOut`'s
# `select_related` has no equivalent here — neither `TemplateOut` nor
# `RecipientOut` walks a relation — so this is the floor a list route costs at
# this door, and it must not move with the row count.
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
TEMPLATE_LIST_BUDGET = 10
# The contact list is a family noun's page now (`ActsPagination`): every row's
# `allowed_acts` and the list's own. Measured at ten rows: the ten above, the
# actor's collection at the rows' node (memberships, grants, role keys — 3),
# and nothing per row: `recipient.update` and `recipient.create` are answered
# by `policies.can_send`, whose `_is_member` asks `authz.membership_for`, and
# `membership_for` reads the memberships the actor already memoizes for
# `effective_permissions` — so the per-row term that made this 24 at ten rows
# (34 at twenty) is gone, and the list is 13 statements at 5, 20 and 50 rows.
RECIPIENT_LIST_BUDGET = 13


def _body(response: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(response.content)
    return parsed


# --- the routes are where the router put them ------------------------------------


def test_the_management_routes_are_where_the_router_put_them() -> None:
    assert reverse("api:template-list") == TEMPLATES_URL
    assert reverse("api:template-create") == TEMPLATES_URL
    assert reverse("api:recipient-list") == RECIPIENTS_URL
    assert reverse("api:recipient-create") == RECIPIENTS_URL
    # One resource, ONE address key. All three of revise, retire and detail
    # take the template's NAME — the key `send()`, a policy step and a `Message`
    # row already speak — and `reverse()` is asserted with `name=` on each,
    # so a route that went back to a `{template_id}` would fail here by
    # signature rather than by a 404 somebody has to notice.
    assert reverse("api:template-revise", kwargs={"name": "receipt"}) == (
        f"{TEMPLATES_URL}receipt/versions/"
    )
    assert reverse("api:template-retire", kwargs={"name": "receipt"}) == (
        f"{TEMPLATES_URL}receipt/retire/"
    )
    assert reverse("api:template-detail", kwargs={"name": "receipt"}) == (
        f"{TEMPLATES_URL}receipt/"
    )
    assert reverse("api:consent-grant", kwargs={"recipient_id": "x" * 36}).endswith(
        "/grant-consent/"
    )
    assert reverse("api:consent-revoke", kwargs={"recipient_id": "x" * 36}).endswith(
        "/revoke-consent/"
    )
    assert reverse("api:quiet_hours-set", kwargs={"recipient_id": "x" * 36}).endswith(
        "/quiet-hours/"
    )
    assert reverse("api:recipient-suppress", kwargs={"recipient_id": "x" * 36}).endswith(
        "/suppress/"
    )
    assert reverse("api:recipient-unsuppress", kwargs={"recipient_id": "x" * 36}).endswith(
        "/unsuppress/"
    )
    assert reverse("api:recipient-archive", kwargs={"recipient_id": "x" * 36}).endswith("/archive/")
    assert reverse("api:recipient-restore", kwargs={"recipient_id": "x" * 36}).endswith("/restore/")
    assert reverse("api:preference-list", kwargs={"recipient_id": "x" * 36}).endswith(
        "/preferences/"
    )


# --- templates: a new version, never an edit -------------------------------------


def test_a_revision_is_a_new_row_and_the_old_one_is_untouched(
    tenant: Tenant, owner_actor: Actor, receipt: MessageTemplate
) -> None:
    """C1b-4's first half. The words v1 was sent with survive v2 being published."""
    first_subject, first_body = receipt.subject, receipt.body
    second = make_next_version(actor=owner_actor)

    assert second.pk != receipt.pk
    assert second.version == 2
    assert second.name == receipt.name
    receipt.refresh_from_db()
    assert (receipt.subject, receipt.body, receipt.version) == (first_subject, first_body, 1)
    assert MessageTemplate.objects.for_tenant(tenant).filter(name="receipt").count() == 2


def test_a_send_uses_the_new_version_and_the_row_records_which(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """C1b-4: versions 1 and 2 exist, the send uses 2, and v1 is still readable."""
    make_next_version(actor=owner_actor, subject="v2 for {{ name }}")
    message = send(
        recipient=recipient,
        template="receipt",
        context={"name": "Ada"},
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )
    assert message.template_version == 2
    assert message.subject == "v2 for Ada"
    # And the version it did NOT use is still there, still readable, still v1.
    v1 = MessageTemplate.objects.for_tenant(tenant).get(name="receipt", version=1)
    assert v1.subject == "Your receipt, {{ name }}"
    assert v1.is_active is True


def test_a_retired_version_puts_the_previous_one_back_in_service(
    tenant: Tenant, owner_actor: Actor, receipt: MessageTemplate
) -> None:
    make_next_version(actor=owner_actor, retired=True)
    assert get_template(tenant=tenant, name="receipt", actor=owner_actor).version == 1


def test_a_name_is_claimed_once(
    tenant: Tenant, owner_actor: Actor, receipt: MessageTemplate
) -> None:
    """A second create under a live name is a conflict, not a silent second row."""
    with pytest.raises(Conflict):
        make_template(actor=owner_actor)


def test_revising_a_template_that_does_not_exist_is_not_found(
    tenant: Tenant, owner_actor: Actor
) -> None:
    with pytest.raises(NotFound):
        make_next_version(actor=owner_actor, name="nothing-here")


def test_only_a_privileged_role_changes_what_the_tenant_may_say(
    tenant: Tenant, member_actor: Actor, receipt: MessageTemplate
) -> None:
    """A member may send all day. What they may not do is change the words."""
    with pytest.raises(Forbidden):
        make_template(actor=member_actor, name="theirs")
    with pytest.raises(Forbidden):
        make_next_version(actor=member_actor)


def test_a_template_revision_over_the_wire_is_201_with_a_new_id(
    api: Client, owner: User, receipt: MessageTemplate
) -> None:
    api.force_login(owner)
    response = api.post(
        f"{TEMPLATES_URL}receipt/versions/",
        data=json.dumps({"subject": "v2 for {{ name }}", "body": "Second words, {{ name }}."}),
        content_type=JSON,
    )
    assert response.status_code == 201, response.content
    body = _body(response)
    assert body["version"] == 2
    assert body["id"] != str(receipt.pk)
    assert body["channel"] == receipt.channel

    # The name now resolves to the new version...
    live = _body(api.get(f"{TEMPLATES_URL}receipt/"))
    assert live["version"] == 2
    assert live["id"] == body["id"]

    # ...and the first version is still readable, with its own words, through
    # the list — which is where every version lives (the detail route
    # answers "what would a send use", the list answers "what did v1 say").
    listed = _body(api.get(f"{TEMPLATES_URL}?name=receipt"))["items"]
    versions = {row["version"]: row for row in listed}
    assert versions[1]["subject"] == "Your receipt, {{ name }}"
    assert versions[1]["id"] == str(receipt.pk)


def test_the_template_list_shows_every_version_including_retired_ones(
    api: Client, owner: User, owner_actor: Actor, receipt: MessageTemplate
) -> None:
    make_next_version(actor=owner_actor, retired=True)
    api.force_login(owner)
    body = _body(api.get(f"{TEMPLATES_URL}?name=receipt"))
    assert len(body["items"]) == 2
    assert {row["version"] for row in body["items"]} == {1, 2}
    assert {row["is_active"] for row in body["items"]} == {True, False}


def test_there_is_no_route_that_edits_a_template(
    api: Client, owner: User, receipt: MessageTemplate
) -> None:
    """The strongest form of "never edited in place": the door does not exist.

    A 405 rather than a 200-that-ignored-the-body, because the method is not
    routed at all — which is what makes "a template is immutable" a property of
    the URL map instead of a promise in a docstring.
    """
    api.force_login(owner)
    response = api.patch(
        f"{TEMPLATES_URL}receipt/",
        data=json.dumps({"subject": "rewritten"}),
        content_type=JSON,
    )
    assert response.status_code == 405
    receipt.refresh_from_db()
    assert receipt.subject == "Your receipt, {{ name }}"


# --- one address key, and the old spelling says so --------------------------


def test_retiring_by_name_takes_the_live_version_out_and_the_name_falls_back(
    api: Client, owner: User, owner_actor: Actor, receipt: MessageTemplate
) -> None:
    """The user story raised for this: revise by name, retire by name.

    No list in between to learn an id — which was the whole complaint. And the
    fallback is the retire verb's actual meaning: v2 out, the name resolves to
    v1 again, and v2 is still there to read.
    """
    second = make_next_version(actor=owner_actor, subject="v2 for {{ name }}")
    api.force_login(owner)

    response = api.post(f"{TEMPLATES_URL}receipt/retire/", content_type=JSON)
    assert response.status_code == 200, response.content
    body = _body(response)
    assert body["id"] == str(second.pk)
    assert body["is_active"] is False

    assert get_template(tenant=receipt.tenant, name="receipt", actor=owner_actor).version == 1
    assert _body(api.get(f"{TEMPLATES_URL}receipt/"))["version"] == 1
    assert len(_body(api.get(f"{TEMPLATES_URL}?name=receipt"))["items"]) == 2


def test_retiring_a_name_with_no_live_version_is_a_json_404(
    api: Client, owner: User, owner_actor: Actor, receipt: MessageTemplate
) -> None:
    """The pair. `get_template` answers only with a LIVE version, so the second
    retirement of a one-version name is `not_found` rather than a silent 200.
    """
    api.force_login(owner)
    assert api.post(f"{TEMPLATES_URL}receipt/retire/", content_type=JSON).status_code == 200

    response = api.post(f"{TEMPLATES_URL}receipt/retire/", content_type=JSON)
    assert response.status_code == 404, response.content
    assert response["Content-Type"].startswith(JSON)
    assert _body(response)["code"] == "not_found"


@pytest.mark.parametrize("suffix", ["", "retire/"])
def test_the_id_addressed_spelling_answers_the_apis_own_refusal(
    api: Client, owner: User, receipt: MessageTemplate, suffix: str
) -> None:
    """The retired spellings, pinned the way `test_resource_first_urls.py` pins
    the ADR api-2 renames: a move nobody can observe is a move that will be
    half-made.

    It is pinned HERE rather than in that file's `RETIRED` tuple because the
    mechanism is different and the difference matters. Those spellings stopped
    ROUTING; these still route — a UUID is a perfectly good string, so
    `/api/v1/templates/<uuid>/` now matches the `{name}` route and asks "is
    there a live template called `0198…`". There is not, so the answer is the
    API's own JSON `not_found`, from the selector rather than from the URL map.
    Same observable refusal, and no dual-serving: the id is not a second key,
    it is just a name nobody has.
    """
    api.force_login(owner)
    path = f"{TEMPLATES_URL}{receipt.pk}/{suffix}"
    response = api.post(path, content_type=JSON) if suffix else api.get(path)
    assert response.status_code == 404, (path, response.content)
    assert response["Content-Type"].startswith(JSON), response["Content-Type"]
    assert _body(response)["code"] == "not_found"
    receipt.refresh_from_db()
    assert receipt.is_active is True


def test_the_machine_door_retires_by_name_too(
    tenant: Tenant, owner: User, owner_actor: Actor, receipt: MessageTemplate
) -> None:
    """Door parity on the KEY, not only on the tool name.

    Rule 17 pairs `template-retire` with `retire_template` and would have passed
    while one took a name and the other a UUID — which is exactly how the split
    survived five cycles of review. This is the assertion that would not.
    """
    second = make_next_version(actor=owner_actor, subject="v2 for {{ name }}")
    out = tool("retire_template")(context_for(owner, tenant), name="receipt")
    assert out.id == second.pk
    assert out.is_active is False
    assert tool("get_template")(context_for(owner, tenant), name="receipt").version == 1


# --- the crafted body: what a Patch schema does NOT carry ------------------------


def test_a_patch_naming_version_is_400_and_the_field_is_named(
    api: Client, owner: User, recipient: Recipient
) -> None:
    """C1b-2. `version` is absent from every write shape in this app.

    The crafted body is the one a client writes when it has read the *read*
    schema and assumed the write shape matches. It does not, and being told so
    is the difference between "the version did not move" and "the version did
    not move and nobody knows".
    """
    api.force_login(owner)
    response = api.patch(
        f"{RECIPIENTS_URL}{recipient.pk}/",
        data=json.dumps({"display_name": "Ada L.", "version": 4}),
        content_type=JSON,
    )
    # 422 and `invalid_body` since SB-1: strictness moved from this app's own
    # `StrictIn` (a `model_validator` raising `Invalid`) to the platform's one
    # seam, `core.schemas.RequestSchema`, recomposed by the one mapper. The
    # property this test asserts is unchanged — the field is named and the row
    # did not move — and what changed is that every other door in the product
    # now answers a crafted body the same way this one already did.
    assert response.status_code == 422, response.content
    body = _body(response)
    assert body["code"] == "invalid_body"
    assert "version" in body["errors"]
    recipient.refresh_from_db()
    assert recipient.display_name == "A Reader"


def test_a_patch_naming_suppressed_at_is_400_and_nothing_is_suppressed(
    api: Client, owner: User, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """The other half of C1b-2: a consent column is not reachable from a PATCH."""
    api.force_login(owner)
    response = api.patch(
        f"{RECIPIENTS_URL}{recipient.pk}/",
        data=json.dumps({"suppressed_at": "2026-01-01T00:00:00Z"}),
        content_type=JSON,
    )
    assert response.status_code == 422, response.content
    assert "suppressed_at" in _body(response)["errors"]
    assert not ChannelPreference.objects.for_tenant(recipient.tenant).exists()


def test_a_create_naming_version_is_400_too(api: Client, owner: User) -> None:
    """The same wall on the create shape — a template cannot be born at v7."""
    api.force_login(owner)
    response = api.post(
        TEMPLATES_URL,
        data=json.dumps({"name": "invoice", "body": "Hi {{ name }}", "version": 7}),
        content_type=JSON,
    )
    assert response.status_code == 422, response.content
    assert "version" in _body(response)["errors"]
    assert not MessageTemplate.objects.filter(name="invoice").exists()


def test_the_fields_the_patch_does_carry_still_work(
    api: Client, owner: User, recipient: Recipient
) -> None:
    """The pair. Without it, a door that 400'd on everything would pass above."""
    api.force_login(owner)
    response = api.patch(
        f"{RECIPIENTS_URL}{recipient.pk}/",
        data=json.dumps({"display_name": "Ada L."}),
        content_type=JSON,
    )
    assert response.status_code == 200, response.content
    recipient.refresh_from_db()
    assert recipient.display_name == "Ada L."


# --- recipients: the contact book ------------------------------------------------


def test_a_contact_is_created_in_the_acting_hats_branch(api: Client, branches: Branches) -> None:
    """No `organization` on the write shape: the hat decides, and only the hat."""
    api.force_login(branches.clerk)
    response = api.post(
        RECIPIENTS_URL,
        data=json.dumps({"email": "New@Example.com", "display_name": "New"}),
        content_type=JSON,
    )
    assert response.status_code == 201, response.content
    body = _body(response)
    assert body["organization_id"] == str(branches.sub_a1.pk)
    # Lower-cased on the way in, because an address that differs only in case is
    # the same person and the unique constraint has to be able to say so.
    assert body["email"] == "new@example.com"


def test_an_archived_contact_leaves_the_list_and_stays_readable(
    api: Client, owner: User, recipient: Recipient
) -> None:
    api.force_login(owner)
    assert len(_body(api.get(RECIPIENTS_URL))["items"]) == 1

    archived = api.post(f"{RECIPIENTS_URL}{recipient.pk}/archive/")
    assert archived.status_code == 200, archived.content
    assert _body(archived)["archived_at"] is not None

    assert len(_body(api.get(RECIPIENTS_URL))["items"]) == 0
    assert len(_body(api.get(f"{RECIPIENTS_URL}?show=archived"))["items"]) == 1
    # Still fetchable by id — the message log has to be able to name who it
    # went to, and un-archiving something you cannot fetch is impossible.
    assert _body(api.get(f"{RECIPIENTS_URL}{recipient.pk}/"))["id"] == str(recipient.pk)


def test_archiving_is_not_a_consent_decision(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """The honest negative, and the one somebody will be surprised by.

    Archiving closes a *contact record*. It deliberately does not stand in for
    consent: two walls that could disagree would be one wall too many, and the
    one that decides whether a message goes out is `suppress_recipient`.
    """
    archive_recipient(tenant=tenant, actor=owner_actor, recipient=recipient)
    message = send(
        recipient=recipient,
        template="receipt",
        context={"name": "Ada"},
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )
    assert message.status == Message.Status.QUEUED


def test_a_member_may_keep_contacts_but_not_close_one(
    tenant: Tenant, member_actor: Actor, recipient: Recipient
) -> None:
    """The asymmetry, at the contact book: adding is ordinary, closing is not."""
    created = create_recipient(tenant=tenant, actor=member_actor, email="new@example.com")
    assert created.pk is not None
    with pytest.raises(Forbidden):
        archive_recipient(tenant=tenant, actor=member_actor, recipient=recipient)


def test_a_sibling_branchs_contact_is_not_found_rather_than_forbidden(
    api: Client, branches: Branches
) -> None:
    theirs = make_recipient(
        actor=actor_for(user=branches.owner, tenant=branches.tenant, org=branches.seller_b),
        email="b-contact@example.com",
    )
    api.force_login(branches.clerk)
    response = api.get(f"{RECIPIENTS_URL}{theirs.pk}/")
    assert response.status_code == 404
    assert _body(response)["code"] == "not_found"


# --- consent: five verbs, each proved by what a send does next -------------------


def test_granting_consent_over_the_wire_lets_the_next_campaign_out(
    api: Client,
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    recipient: Recipient,
    newsletter: MessageTemplate,
) -> None:
    """The verb is only real if `send()` changes its mind. This is that assertion."""
    before = send(
        recipient=recipient,
        template="newsletter",
        context={"name": "Ada"},
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )
    assert before.suppressed_reason == Message.SuppressedReason.NO_CONSENT

    api.force_login(owner)
    granted = api.post(
        f"{RECIPIENTS_URL}{recipient.pk}/grant-consent/",
        data=json.dumps({"channel": "email"}),
        content_type=JSON,
    )
    assert granted.status_code == 200, granted.content
    assert _body(granted)["has_marketing_consent"] is True

    after = send(
        recipient=recipient,
        template="newsletter",
        context={"name": "Ada"},
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )
    assert after.status == Message.Status.QUEUED


def test_revoking_keeps_the_earlier_consent_on_the_row(
    api: Client, owner: User, recipient: Recipient
) -> None:
    """ "Agreed in March, withdrew in June" is the history a regulator asks for."""
    api.force_login(owner)
    api.post(
        f"{RECIPIENTS_URL}{recipient.pk}/grant-consent/",
        data=json.dumps({}),
        content_type=JSON,
    )
    revoked = _body(
        api.post(
            f"{RECIPIENTS_URL}{recipient.pk}/revoke-consent/",
            data=json.dumps({}),
            content_type=JSON,
        )
    )
    assert revoked["has_marketing_consent"] is False
    assert revoked["marketing_consented_at"] is not None
    assert revoked["marketing_revoked_at"] is not None


def test_suppression_stops_transactional_mail_and_lifting_it_lets_it_through(
    api: Client,
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
) -> None:
    """Both halves, because either alone would pass against a door that did nothing."""
    api.force_login(owner)
    suppressed = api.post(
        f"{RECIPIENTS_URL}{recipient.pk}/suppress/", data=json.dumps({}), content_type=JSON
    )
    assert suppressed.status_code == 200, suppressed.content
    assert _body(suppressed)["suppressed_at"] is not None

    refused = send(
        recipient=recipient,
        template="receipt",
        context={"name": "Ada"},
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )
    assert refused.suppressed_reason == Message.SuppressedReason.SUPPRESSED

    lifted = api.post(
        f"{RECIPIENTS_URL}{recipient.pk}/unsuppress/", data=json.dumps({}), content_type=JSON
    )
    assert _body(lifted)["suppressed_at"] is None
    delivered = send(
        recipient=recipient,
        template="receipt",
        context={"name": "Ada"},
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )
    assert delivered.status == Message.Status.QUEUED


def test_lifting_a_suppression_does_not_restore_marketing_consent(
    api: Client,
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    recipient: Recipient,
    newsletter: MessageTemplate,
) -> None:
    """The negative that keeps the two facts separate."""
    api.force_login(owner)
    api.post(f"{RECIPIENTS_URL}{recipient.pk}/suppress/", data=json.dumps({}), content_type=JSON)
    api.post(f"{RECIPIENTS_URL}{recipient.pk}/unsuppress/", data=json.dumps({}), content_type=JSON)
    message = send(
        recipient=recipient,
        template="newsletter",
        context={"name": "Ada"},
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )
    assert message.suppressed_reason == Message.SuppressedReason.NO_CONSENT


def test_quiet_hours_are_set_and_cleared_through_the_same_verb(
    api: Client, owner: User, recipient: Recipient
) -> None:
    api.force_login(owner)
    url = f"{RECIPIENTS_URL}{recipient.pk}/quiet-hours/"
    body = _body(
        api.post(
            url,
            data=json.dumps(
                {"start": "22:00:00", "end": "07:00:00", "timezone_name": "Europe/London"}
            ),
            content_type=JSON,
        )
    )
    assert body["quiet_hours_start"] == "22:00:00"
    assert body["quiet_hours_timezone"] == "Europe/London"

    cleared = _body(api.post(url, data=json.dumps({}), content_type=JSON))
    assert cleared["quiet_hours_start"] is None
    assert cleared["quiet_hours_end"] is None


def test_a_half_open_quiet_window_is_refused_with_the_field_named(
    api: Client, owner: User, recipient: Recipient
) -> None:
    api.force_login(owner)
    response = api.post(
        f"{RECIPIENTS_URL}{recipient.pk}/quiet-hours/",
        data=json.dumps({"start": "22:00:00"}),
        content_type=JSON,
    )
    assert response.status_code == 400, response.content
    assert "quiet_hours" in _body(response)["errors"]


def test_a_timezone_nobody_has_heard_of_is_refused(
    api: Client, owner: User, recipient: Recipient
) -> None:
    api.force_login(owner)
    response = api.post(
        f"{RECIPIENTS_URL}{recipient.pk}/quiet-hours/",
        data=json.dumps({"start": "22:00:00", "end": "07:00:00", "timezone_name": "Mars/Olympus"}),
        content_type=JSON,
    )
    assert response.status_code == 400
    assert "timezone_name" in _body(response)["errors"]


def test_a_channel_this_product_does_not_know_is_refused(
    api: Client, owner: User, recipient: Recipient
) -> None:
    api.force_login(owner)
    response = api.post(
        f"{RECIPIENTS_URL}{recipient.pk}/grant-consent/",
        data=json.dumps({"channel": "carrier-pigeon"}),
        content_type=JSON,
    )
    assert response.status_code == 400
    assert "channel" in _body(response)["errors"]


def test_only_a_privileged_role_touches_consent(
    api: Client, member: User, recipient: Recipient
) -> None:
    api.force_login(member)
    response = api.post(
        f"{RECIPIENTS_URL}{recipient.pk}/grant-consent/",
        data=json.dumps({}),
        content_type=JSON,
    )
    assert response.status_code == 403
    assert _body(response)["code"] == "forbidden"


def test_the_preference_list_answers_channel_by_channel(
    api: Client, owner: User, recipient: Recipient
) -> None:
    """A channel with no row is not missing data — it is "nobody has said anything"."""
    api.force_login(owner)
    api.post(
        f"{RECIPIENTS_URL}{recipient.pk}/grant-consent/",
        data=json.dumps({"channel": "email"}),
        content_type=JSON,
    )
    body = _body(api.get(f"{RECIPIENTS_URL}{recipient.pk}/preferences/"))
    assert len(body["items"]) == 1
    assert body["items"][0]["channel"] == Channel.EMAIL.value
    assert body["items"][0]["has_marketing_consent"] is True


# --- the audit trail names the verb, not the column ------------------------------


def test_every_consent_verb_writes_its_own_audit_row(
    api: Client, tenant: Tenant, owner: User, recipient: Recipient
) -> None:
    """What `@service` buys, said out loud: the trail reads as decisions.

    `comms.grant_consent` and `comms.revoke_consent` are two different actions
    with two different rows — which is exactly what a PATCH that moved
    `marketing_revoked_at` could never produce.
    """
    api.force_login(owner)
    api.post(
        f"{RECIPIENTS_URL}{recipient.pk}/grant-consent/", data=json.dumps({}), content_type=JSON
    )
    api.post(
        f"{RECIPIENTS_URL}{recipient.pk}/revoke-consent/", data=json.dumps({}), content_type=JSON
    )
    actions = set(
        AuditEntry.objects.for_tenant(tenant)
        .filter(action__startswith="comms.")
        .values_list("action", flat=True)
    )
    assert {"comms.grant_consent", "comms.revoke_consent"} <= actions
    granted = AuditEntry.objects.for_tenant(tenant).get(action="comms.grant_consent")
    assert granted.door == "rest"
    assert granted.outcome == "ok"


# --- query budgets ---------------------------------------------------------------


def test_the_template_list_query_budget(
    api: Client, owner: User, owner_actor: Actor, django_assert_num_queries: Any
) -> None:
    for index in range(10):
        make_template(actor=owner_actor, name=f"template-{index}")
    api.force_login(owner)
    with django_assert_num_queries(TEMPLATE_LIST_BUDGET):
        assert len(_body(api.get(TEMPLATES_URL))["items"]) == 10


def test_the_recipient_list_query_budget(
    api: Client, owner: User, owner_actor: Actor, django_assert_num_queries: Any
) -> None:
    for index in range(10):
        make_recipient(actor=owner_actor, email=f"reader-{index}@example.com")
    api.force_login(owner)
    with django_assert_num_queries(RECIPIENT_LIST_BUDGET):
        assert len(_body(api.get(RECIPIENTS_URL))["items"]) == 10


# --- the machine door says the same thing ----------------------------------------


def test_the_machine_door_revises_a_template_and_never_edits_one(
    tenant: Tenant, owner: User, receipt: MessageTemplate
) -> None:
    out = tool("revise_template")(
        context_for(owner, tenant), name="receipt", body="Machine words, {{ name }}.", subject="v2"
    )
    assert out.version == 2
    assert out.id != receipt.pk
    receipt.refresh_from_db()
    assert receipt.body == "Hello {{ name }}, here is your receipt."


def test_the_machine_door_grants_consent_with_the_same_shape(
    tenant: Tenant, owner: User, recipient: Recipient
) -> None:
    out = tool("grant_consent")(context_for(owner, tenant), recipient_id=recipient.pk)
    assert out.has_marketing_consent is True
    assert out.recipient_id == recipient.pk
    assert out.suppressed_at is None


def test_the_machine_door_archives_a_contact_and_the_list_agrees(
    tenant: Tenant, owner: User, recipient: Recipient
) -> None:
    tool("archive_recipient")(context_for(owner, tenant), recipient_id=recipient.pk)
    assert len(tool("list_recipients")(context_for(owner, tenant)).items) == 0
    assert len(tool("list_recipients")(context_for(owner, tenant), show="archived").items) == 1
    # Still fetchable, exactly as it is over HTTP.
    assert tool("get_recipient")(context_for(owner, tenant), recipient_id=recipient.pk).archived_at


def test_the_machine_door_cannot_reach_another_tenants_template(
    tenant: Tenant, owner: User, stranger_actor: Actor
) -> None:
    from mcp.server.mcpserver.exceptions import ToolError

    make_template(actor=stranger_actor, name="theirs")
    with pytest.raises(ToolError) as raised:
        tool("get_template")(context_for(owner, tenant), name="theirs")
    assert "not_found" in str(raised.value)


def test_a_member_is_refused_at_the_machine_door_too(
    tenant: Tenant, member: User, recipient: Recipient
) -> None:
    """Parity is not only which tools exist — it is what they refuse."""
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError) as raised:
        tool("grant_consent")(context_for(member, tenant), recipient_id=recipient.pk)
    assert "forbidden" in str(raised.value)
