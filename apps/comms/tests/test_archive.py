"""The contact book's archive road: `Recipient` declares `Archivable`.

Closing a contact used to be a hand-built half — a column, a service that set
it, a route, a boolean list filter — with no way back. It is the family's road
now (`core.models.Archivable`, `core.verbs.archive_row` / `restore_row`,
`core.policies.may_archive`), and this module proves the road over the wire and
the one promise the old half made that the family must not break:

* **the road** — archive keeps its first date and its archiver, restore puts
  the contact back, `?show=` is the one way to ask for the closed ones, the
  retired `?archived=` is refused naming `show`, an archived contact reads
  read-only and refuses every other change with `archived`;
* **who may press it** — the node's administration where the contact lives; a
  member is refused with the key's own sentence, a sibling branch's admin
  cannot see the contact at all, and the product acting for itself is refused
  (`@refuses_system`);
* **the promise** — archiving is not a consent decision: a send to a closed
  contact still goes out, every read that names who a message went to still
  resolves the closed contact, and the consent verbs `suppress` and
  `unsuppress` still answer on it — the one exemption from "an archived
  contact reads read-only", because they write the preference row, never the
  contact.

The archive-then-read test at the top is the one that matters most and the
easiest to lose: once the model is `Archivable`, `for_tenant()` hides a closed
contact FIRST, and any read that "includes archived rows" by not filtering the
column answers the live book alone, with no error. Only the queryset's own
widenings bring the row back.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.comms.api import RETIRED_QUERY
from apps.comms.models import Channel, ChannelPreference, Message, MessageTemplate, Recipient
from apps.comms.selectors import get_recipient, list_recipients
from apps.comms.services import archive_recipient, send
from apps.comms.tests.conftest import Branches, make_recipient
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.exceptions import Forbidden
from apps.core.models import Tenant
from apps.core.tests.test_retired_query import strict_query_seam
from apps.events.models import Event, Outbox

pytestmark = pytest.mark.django_db

JSON = "application/json"
RECIPIENTS_URL = "/api/v1/recipients/"
MESSAGES_URL = "/api/v1/messages/"
ARCHIVED = "comms.recipient.archived"
RESTORED = "comms.recipient.restored"


def _body(response: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(response.content)
    return parsed


def _ids(response: Any) -> set[str]:
    assert response.status_code == 200, response.content
    return {str(item["id"]) for item in _body(response)["items"]}


# --- the widenings: an archived contact is read back, never filtered back ------


def test_an_archived_contact_is_read_back_through_the_querysets_own_widenings(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient
) -> None:
    """Archive, then read it back every way a door reads a contact.

    RED on a converted model whose selector still hand-filters `archived_at`:
    `for_tenant()` has already dropped the row, so the detail read is
    `NotFound` and the archived cut is empty — no error anywhere.
    """
    live = make_recipient(actor=owner_actor, email="live@example.com")
    archive_recipient(tenant=tenant, actor=owner_actor, recipient=recipient)

    # The detail — what a message's detail and every consent verb resolve through.
    found = get_recipient(
        tenant=tenant, recipient_id=recipient.pk, org=owner_actor.org, actor=owner_actor
    )
    assert found.pk == recipient.pk
    assert found.archived_at is not None

    def listed(show: str) -> set[Any]:
        rows = list_recipients(tenant=tenant, org=owner_actor.org, show=show, actor=owner_actor)
        return {row.pk for row in rows}

    assert listed("live") == {live.pk}
    assert listed("archived") == {recipient.pk}
    assert listed("all") == {live.pk, recipient.pk}


# --- the road, over the wire ---------------------------------------------------


def test_restore_puts_an_archived_contact_back_in_the_book(
    api: Client, owner: User, recipient: Recipient
) -> None:
    api.force_login(owner)
    assert api.post(f"{RECIPIENTS_URL}{recipient.pk}/archive/").status_code == 200
    assert str(recipient.pk) not in _ids(api.get(RECIPIENTS_URL))

    restored = api.post(f"{RECIPIENTS_URL}{recipient.pk}/restore/")
    assert restored.status_code == 200, restored.content
    body = _body(restored)
    assert body["archived_at"] is None
    assert body["archived_by"] is None
    assert str(recipient.pk) in _ids(api.get(RECIPIENTS_URL))

    # Pressing it again is the same answer, and says nothing new.
    again = api.post(f"{RECIPIENTS_URL}{recipient.pk}/restore/")
    assert again.status_code == 200, again.content
    assert _body(again) == body
    assert Event.objects.for_tenant(recipient.tenant).filter(name=RESTORED).count() == 1


def test_a_second_archive_keeps_the_first_date_and_archiver_and_emits_once(
    api: Client, owner: User, recipient: Recipient
) -> None:
    api.force_login(owner)
    first = api.post(f"{RECIPIENTS_URL}{recipient.pk}/archive/")
    assert first.status_code == 200, first.content
    second = api.post(f"{RECIPIENTS_URL}{recipient.pk}/archive/")
    assert second.status_code == 200, second.content

    assert _body(first)["archived_at"] is not None
    assert _body(second)["archived_at"] == _body(first)["archived_at"]
    assert _body(first)["archived_by"]["id"] == str(owner.pk)
    assert _body(second)["archived_by"] == _body(first)["archived_by"]

    events = Event.objects.for_tenant(recipient.tenant).filter(name=ARCHIVED)
    assert events.count() == 1
    assert Outbox.objects.filter(event__in=events).count() == 1


def test_show_is_the_one_way_to_ask_for_the_archived_cut(
    api: Client, owner: User, owner_actor: Actor, recipient: Recipient
) -> None:
    live = make_recipient(actor=owner_actor, email="live@example.com")
    api.force_login(owner)
    assert api.post(f"{RECIPIENTS_URL}{recipient.pk}/archive/").status_code == 200

    assert _ids(api.get(RECIPIENTS_URL)) == {str(live.pk)}
    assert _ids(api.get(f"{RECIPIENTS_URL}?show=live")) == {str(live.pk)}
    assert _ids(api.get(f"{RECIPIENTS_URL}?show=archived")) == {str(recipient.pk)}
    assert _ids(api.get(f"{RECIPIENTS_URL}?show=all")) == {str(live.pk), str(recipient.pk)}


@pytest.mark.parametrize("seam", ["bare", "behind a strict-query seam"])
@pytest.mark.parametrize("query", ["archived=true", "archived=false", "show=x"])
def test_the_retired_parameter_and_an_unknown_cut_are_refused_naming_show(
    api: Client, owner: User, recipient: Recipient, query: str, seam: str, settings: Any
) -> None:
    """`?archived=` answered the live book or the whole table; it is refused now,
    loudly, naming the parameter to ask with instead — never silently ignored.

    Driven both ways: bare, and behind a product's strict-query seam that defers
    to the list's `RETIRED_QUERY` (`retired_query_of`). The retired parameter is
    answered in the declaration's own sentence either way."""
    if seam != "bare":
        strict_query_seam(settings)
    api.force_login(owner)
    response = api.get(f"{RECIPIENTS_URL}?{query}")
    assert response.status_code == 400, response.content
    body = _body(response)
    assert body["code"] == "invalid"
    assert "show" in body["errors"], body
    if query.startswith("archived="):
        assert body["errors"] == {"show": [RETIRED_QUERY["archived"].reason]}, body


def test_an_archived_contact_reads_read_only(
    api: Client, owner: User, recipient: Recipient
) -> None:
    api.force_login(owner)
    assert api.post(f"{RECIPIENTS_URL}{recipient.pk}/archive/").status_code == 200

    detail = api.get(f"{RECIPIENTS_URL}{recipient.pk}/")
    assert detail.status_code == 200, detail.content
    assert _body(detail)["archived_at"] is not None

    patched = api.patch(
        f"{RECIPIENTS_URL}{recipient.pk}/",
        data=json.dumps({"display_name": "Changed"}),
        content_type=JSON,
    )
    assert patched.status_code == 409, patched.content
    body = _body(patched)
    assert body["code"] == "archived"
    assert {"label": "Restore it first", "destination": "route:recipient-restore"} in body[
        "remedies"
    ]
    recipient.refresh_from_db()
    assert recipient.display_name != "Changed"


# --- who may press it -----------------------------------------------------------


def test_a_member_is_refused_with_the_keys_own_sentence(
    api: Client, member: User, owner_actor: Actor, recipient: Recipient
) -> None:
    api.force_login(member)
    refused = api.post(f"{RECIPIENTS_URL}{recipient.pk}/archive/")
    assert refused.status_code == 403, refused.content
    assert _body(refused)["code"] == "forbidden"
    assert _body(refused)["detail"] == "You may not archive this organization's contacts."

    archive_recipient(tenant=recipient.tenant, actor=owner_actor, recipient=recipient)
    refused = api.post(f"{RECIPIENTS_URL}{recipient.pk}/restore/")
    assert refused.status_code == 403, refused.content
    assert _body(refused)["detail"] == "You may not restore this organization's contacts."


def test_a_sibling_branchs_admin_cannot_see_the_contact_and_a_parents_admin_may_close_it(
    api: Client, branches: Branches
) -> None:
    owner_at = {
        org: actor_for(user=branches.owner, tenant=branches.tenant, org=org)
        for org in (branches.seller_b, branches.sub_a1)
    }
    theirs = make_recipient(actor=owner_at[branches.seller_b], email="b@example.com")
    below = make_recipient(actor=owner_at[branches.sub_a1], email="a1@example.com")

    api.force_login(branches.manager)  # an admin at Seller A
    assert api.post(f"{RECIPIENTS_URL}{theirs.pk}/archive/").status_code == 404
    assert api.post(f"{RECIPIENTS_URL}{theirs.pk}/restore/").status_code == 404
    closed = api.post(f"{RECIPIENTS_URL}{below.pk}/archive/")
    assert closed.status_code == 200, closed.content
    assert _body(closed)["archived_by"]["id"] == str(branches.manager.pk)


def test_the_product_acting_for_itself_may_not_close_a_contact(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient
) -> None:
    """`@refuses_system`: a workflow does not close a person's contact on its own say-so."""
    acting_for_itself = system_actor(tenant=tenant, org=owner_actor.org)
    with pytest.raises(Forbidden):
        archive_recipient(tenant=tenant, actor=acting_for_itself, recipient=recipient)
    recipient.refresh_from_db()
    assert recipient.archived_at is None


# --- the promise the old half made ---------------------------------------------


def test_a_send_to_an_archived_contact_still_goes_out_and_its_message_names_them(
    api: Client,
    owner: User,
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
) -> None:
    """Archiving is not a consent decision: the send door still resolves the
    closed contact, and the message's detail still names who it went to."""
    before = send(
        recipient=recipient,
        template="receipt",
        context={"name": "Ada"},
        channel="email",
        tenant=tenant,
        actor=owner_actor,
    )
    archive_recipient(tenant=tenant, actor=owner_actor, recipient=recipient)

    api.force_login(owner)
    sent = api.post(
        MESSAGES_URL,
        data=json.dumps(
            {
                "recipient_id": str(recipient.pk),
                "template": "receipt",
                "context": {"name": "Ada"},
                "channel": "email",
            }
        ),
        content_type=JSON,
    )
    assert sent.status_code == 201, sent.content
    assert _body(sent)["status"] == Message.Status.QUEUED

    detail = api.get(f"{MESSAGES_URL}{before.pk}/")
    assert detail.status_code == 200, detail.content
    assert _body(detail)["recipient_id"] == str(recipient.pk)
    assert _body(detail)["recipient_email"] == recipient.email


@pytest.mark.parametrize("verb", ["suppress", "unsuppress"])
def test_the_consent_verbs_are_exempt_from_the_archived_contacts_read_only_rule(
    api: Client, owner: User, owner_actor: Actor, recipient: Recipient, verb: str
) -> None:
    """The archive road's exemption, named: `suppress` and `unsuppress` write the
    contact's PREFERENCE row, never the contact, so they do not ask the contact
    to be live. Closing somebody in the contact book must never stop a bounce or
    a "leave me alone" from being recorded, nor a lift of one."""
    archived_at = archive_recipient(
        tenant=recipient.tenant, actor=owner_actor, recipient=recipient
    ).archived_at
    assert archived_at is not None
    api.force_login(owner)
    channel = json.dumps({"channel": Channel.EMAIL})
    if verb == "unsuppress":
        first = api.post(
            f"{RECIPIENTS_URL}{recipient.pk}/suppress/", data=channel, content_type=JSON
        )
        assert first.status_code == 200, first.content

    pressed = api.post(f"{RECIPIENTS_URL}{recipient.pk}/{verb}/", data=channel, content_type=JSON)
    assert pressed.status_code == 200, pressed.content
    preference = ChannelPreference.objects.get(recipient=recipient, channel=Channel.EMAIL)
    assert (preference.suppressed_at is not None) is (verb == "suppress")
    # The contact itself is untouched: still archived, first date kept.
    recipient.refresh_from_db()
    assert recipient.archived_at == archived_at
