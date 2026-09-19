"""The push address book: `Device`, its two doors, and what never leaves on the wire.

ADR comms-9's push half. Five claims, and every test here is one:

* **the address is a table, and it lands where the CONTACT lives.** `Device`
  declares `derive_org_from = "recipient"`, so a registration made under the
  tenant's root hat lands in the branch that owns the contact rather than at the
  root — and the branch can therefore read its own devices. The landing gate in
  `OrgScopedModel.clean()` is what makes that a refusal rather than a
  convention;
* **re-registration is the normal case.** A mobile client hands its token back
  on every launch; the second call updates the row it finds and answers `200`,
  and it brings a retired device back, because that is what re-registering
  means;
* **retirement is a state, never a delete**, and it is idempotent — the second
  call keeps the first timestamp and announces nothing, so a retrying client
  does not publish a transition that did not happen;
* **the token never leaves.** It is an `EncryptedCharField` at rest, and no
  door, no event payload and no log line carries it or any fragment of it. That
  is asserted against the raw column and against every wire shape, because "we
  encrypted it" and "we do not publish it" are two different promises and only
  the second is about the API;
* **`devices` is its own scope family**, ratified before the door shipped
  (RUL-1) and frozen the day it did. The ceiling probe drives both halves: a
  token scoped elsewhere is refused and told which scope, and a token holding
  `devices:write` and nothing else registers.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest
from django.db import connection as db_connection
from django.test import Client

from apps.accounts.models import User
from apps.accounts.services import issue_token
from apps.comms import services
from apps.comms.models import Device, Recipient
from apps.comms.services import hash_push_token
from apps.comms.tests.conftest import Branches, make_recipient
from apps.core.actor import Actor, actor_for
from apps.core.exceptions import Invalid, NotFound
from apps.core.models import Tenant
from apps.events.models import Event

pytestmark = pytest.mark.django_db

DEVICES_URL = "/api/v1/devices/"
JSON = "application/json"

#: A token that is visibly a placeholder rather than a plausible credential —
#: `core.schemas.example`'s rule applied to a fixture, so nothing here reads as
#: a secret somebody has to rotate and nothing trips the secrets leg.
A_TOKEN = "not-a-real-registration-token-0001"
ANOTHER_TOKEN = "not-a-real-registration-token-0002"


def _body(response: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(response.content)
    return parsed


def _bearer(plaintext: str) -> dict[str, str]:
    return {"authorization": f"Bearer {plaintext}"}


def _register_body(recipient: Recipient, token: str = A_TOKEN, **extra: Any) -> str:
    return json.dumps(
        {
            "recipient_id": str(recipient.pk),
            "platform": "ios",
            "push_token": token,
            **extra,
        }
    )


def _raw_column(device: Device) -> str:
    """What Postgres actually holds in `push_token`, read past the ORM.

    Through a cursor rather than through the model, deliberately: the field
    decrypts on the way out, so a read through Django would show the plaintext
    whether the column held ciphertext or not — which is the assertion passing
    for the wrong reason.
    """
    with db_connection.cursor() as cursor:
        cursor.execute("SELECT push_token FROM comms_device WHERE id = %s", [str(device.pk)])
        row = cursor.fetchone()
    return str(row[0])


# --- the model, born declared ----------------------------------------------------


def test_the_model_is_born_declared_and_derives_its_branch() -> None:
    """House rule 31 and C9, in one assertion each, off the class.

    Both are read off declarations rather than off a list somewhere, which is
    why `quality/rules.yaml` is untouched here: the table joined
    rule 31's population the moment it existed. `tests/test_lifecycle.py` holds
    the KIND that was argued for; this holds that the two declarations a door
    depends on are there at all.

    *Absent:* the class carries neither and the gate says nothing, because a
    model that never declared is not in the population.
    """
    from apps.core.lifecycle import lifecycle_of

    declared = lifecycle_of(Device)
    assert declared is not None
    assert declared.reason.strip()
    assert declared.trigger.strip()
    assert Device.derive_org_from == "recipient"


def test_the_token_is_ciphertext_in_the_column(tenant: Tenant, owner_actor: Actor) -> None:
    """House rule 15's secret-at-rest clause, met rather than waived.

    Read through a raw cursor, because the field decrypts on the way out of the
    ORM: a `device.push_token == A_TOKEN` assertion is true either way and
    proves nothing about the column.

    *Absent:* the column holds the token and a `pg_dump` handed to a contractor
    is a set of live push capabilities.
    """
    recipient = make_recipient(actor=owner_actor, email="ada@example.com")
    device = services.register_device(
        tenant=tenant,
        actor=owner_actor,
        recipient=recipient,
        platform="ios",
        push_token=A_TOKEN,
    )
    stored = _raw_column(device)
    assert A_TOKEN not in stored
    assert stored.startswith("gAAAAA")  # Fernet's own version byte, base64
    # And it really does come back, so the test above is not passing because
    # nothing was stored.
    assert Device.objects.for_tenant(tenant).get(pk=device.pk).push_token == A_TOKEN
    assert device.push_token_hash == hash_push_token(A_TOKEN)


# --- registration ----------------------------------------------------------------


def test_a_registration_lands_in_the_contacts_branch_not_the_acting_hat(
    branches: Branches,
) -> None:
    """C9 at the row. The hat registering is the ROOT; the contact is in a branch.

    This is the whole reason `Device` derives its organization: an app server
    registering a device on a person's behalf commonly acts wide, and a row
    stamped from that hat would land at the root where the branch that owns the
    contact could never read it — which is the same defect `MessageEngagement`
    closes one table over for a webhook.

    *Absent:* the device lands on `hq` and the clerk who owns the contact reads
    an empty address book.
    """
    at_root = actor_for(user=branches.owner, tenant=branches.tenant, org=branches.hq)
    in_branch = actor_for(user=branches.clerk, tenant=branches.tenant, org=branches.sub_a1)
    contact = make_recipient(actor=in_branch, email="in-a1@example.com")

    device = services.register_device(
        tenant=branches.tenant,
        actor=at_root,
        recipient=contact,
        platform="android",
        push_token=A_TOKEN,
    )

    assert device.organization_id == branches.sub_a1.pk
    assert device.organization_id != branches.hq.pk
    # And the branch really can read it, which is the consequence the id is for.
    from apps.comms.selectors import list_devices

    visible = list_devices(tenant=branches.tenant, org=branches.sub_a1)
    assert [row.pk for row in visible] == [device.pk]


def test_a_sibling_branch_cannot_reach_the_device(branches: Branches) -> None:
    """Downward only. Seller B holds no membership over A1 and sees nothing.

    Two halves, because either alone passes vacuously: the list is empty for B,
    and the direct fetch by id is `NotFound` rather than `Forbidden` — not-there
    and not-yours are one answer, deliberately.
    """
    from apps.comms.selectors import get_device, list_devices

    in_branch = actor_for(user=branches.clerk, tenant=branches.tenant, org=branches.sub_a1)
    contact = make_recipient(actor=in_branch, email="in-a1@example.com")
    device = services.register_device(
        tenant=branches.tenant,
        actor=in_branch,
        recipient=contact,
        platform="ios",
        push_token=A_TOKEN,
    )

    assert list(list_devices(tenant=branches.tenant, org=branches.seller_b)) == []
    with pytest.raises(NotFound):
        get_device(
            tenant=branches.tenant,
            device_id=device.pk,
            org=branches.seller_b,
            actor=actor_for(user=branches.owner, tenant=branches.tenant, org=branches.seller_b),
        )
    # The manager one level up DOES see it — otherwise the assertion above
    # would pass on a read that returns nothing to anybody.
    assert [row.pk for row in list_devices(tenant=branches.tenant, org=branches.seller_a)] == [
        device.pk
    ]


def test_re_registering_the_same_token_updates_one_row(tenant: Tenant, owner_actor: Actor) -> None:
    """Architect C4 at the door a client calls most often. One row, not two.

    A phone re-registers on every launch. The second call is not an error and it
    is not a second device: it is the same install saying the same thing.

    *Absent:* two rows, and a notification delivered twice to one handset.
    """
    recipient = make_recipient(actor=owner_actor, email="ada@example.com")
    first = services.register_device(
        tenant=tenant,
        actor=owner_actor,
        recipient=recipient,
        platform="ios",
        push_token=A_TOKEN,
        label="Ada's iPhone",
    )
    second = services.register_device(
        tenant=tenant,
        actor=owner_actor,
        recipient=recipient,
        platform="ios",
        push_token=A_TOKEN,
        label="Ada's new iPhone",
    )

    assert second.pk == first.pk
    assert Device.objects.for_tenant(tenant).count() == 1
    assert second.label == "Ada's new iPhone"


def test_re_registering_brings_a_retired_device_back(tenant: Tenant, owner_actor: Actor) -> None:
    """Because that is what re-registering means.

    A person who signed out and signed back in is reachable again, and the
    alternative — a permanently dead row plus a unique-constraint collision on
    the next registration — is a client that can never recover.
    """
    recipient = make_recipient(actor=owner_actor, email="ada@example.com")
    device = services.register_device(
        tenant=tenant,
        actor=owner_actor,
        recipient=recipient,
        platform="ios",
        push_token=A_TOKEN,
    )
    services.retire_device(tenant=tenant, actor=owner_actor, device=device)

    again = services.register_device(
        tenant=tenant,
        actor=owner_actor,
        recipient=recipient,
        platform="ios",
        push_token=A_TOKEN,
    )

    assert again.pk == device.pk
    assert again.retired_at is None


def test_an_unknown_platform_is_refused_by_name(tenant: Tenant, owner_actor: Actor) -> None:
    """A closed vocabulary, checked before a row is built.

    *Absent:* a `platform` the rest of the product cannot read lands in the
    column, and whichever transport reads it later fails at delivery time
    instead of at registration time.
    """
    recipient = make_recipient(actor=owner_actor, email="ada@example.com")
    with pytest.raises(Invalid) as raised:
        services.register_device(
            tenant=tenant,
            actor=owner_actor,
            recipient=recipient,
            platform="blackberry",
            push_token=A_TOKEN,
        )
    assert "platform" in raised.value.errors


def test_an_empty_token_is_refused(tenant: Tenant, owner_actor: Actor) -> None:
    """Fail closed. A device row with no address is a device nothing can reach.

    It matters more here than it looks: the digest of the empty string is a
    perfectly good hex value, so without this branch every contact whose client
    sent nothing would collide on one row.
    """
    recipient = make_recipient(actor=owner_actor, email="ada@example.com")
    with pytest.raises(Invalid) as raised:
        services.register_device(
            tenant=tenant,
            actor=owner_actor,
            recipient=recipient,
            platform="ios",
            push_token="   ",
        )
    assert "push_token" in raised.value.errors


def test_a_contact_in_another_tenant_is_not_found(
    tenant: Tenant, owner_actor: Actor, stranger_actor: Actor, other_tenant: Tenant
) -> None:
    """House rule 26 at the reference. `recipient` came off the wire as an id."""
    theirs = make_recipient(actor=stranger_actor, email="theirs@example.com")
    with pytest.raises(NotFound):
        services.register_device(
            tenant=tenant,
            actor=owner_actor,
            recipient=theirs,
            platform="ios",
            push_token=A_TOKEN,
        )


# --- retirement ----------------------------------------------------------------


def test_retirement_is_a_state_and_is_idempotent(tenant: Tenant, owner_actor: Actor) -> None:
    """The row stays, the timestamp does not move, and the second call is silent.

    Three claims in one test because they are one property: retiring a device
    twice is not two events. A client retrying a `POST` must not publish a
    transition that did not happen.

    *Absent:* the row is deleted (and the message that went to it points at
    nothing), or `comms.device.retired` is announced once per retry and a
    subscriber counts a fleet churning that is not.
    """
    recipient = make_recipient(actor=owner_actor, email="ada@example.com")
    device = services.register_device(
        tenant=tenant,
        actor=owner_actor,
        recipient=recipient,
        platform="ios",
        push_token=A_TOKEN,
    )
    first = services.retire_device(tenant=tenant, actor=owner_actor, device=device)
    at = first.retired_at
    assert at is not None

    second = services.retire_device(tenant=tenant, actor=owner_actor, device=first)

    assert second.retired_at == at
    assert Device.objects.for_tenant(tenant).filter(pk=device.pk).exists()
    assert len(list(Event.objects.for_tenant(tenant).filter(name="comms.device.retired"))) == 1


def test_both_writes_announce_themselves_without_the_token(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """The events exist, and the payload carries nothing anybody could push with.

    The second half is the one that matters: an event is delivered to every
    webhook endpoint the tenant has configured, so a token on that wire is a
    live capability sitting in somebody else's log. Asserted over the whole
    serialised payload rather than field by field, because the failure being
    guarded against is a field somebody adds later.
    """
    recipient = make_recipient(actor=owner_actor, email="ada@example.com")
    device = services.register_device(
        tenant=tenant,
        actor=owner_actor,
        recipient=recipient,
        platform="ios",
        push_token=A_TOKEN,
    )
    services.retire_device(tenant=tenant, actor=owner_actor, device=device)

    announced = list(Event.objects.for_tenant(tenant).filter(name__startswith="comms.device."))
    assert sorted(event.name for event in announced) == [
        "comms.device.registered",
        "comms.device.retired",
    ]
    for event in announced:
        rendered = json.dumps(event.payload)
        assert A_TOKEN not in rendered
        assert hash_push_token(A_TOKEN) not in rendered
        assert "push_token" not in rendered


# --- the doors -------------------------------------------------------------------


def test_the_register_door_answers_the_row_and_never_the_token(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """The wire shape, asserted as a key set rather than field by field.

    A key set is what could actually fail: a future `DeviceOut` field that
    happened to carry a fragment of the token would pass every value assertion
    in this file and fail this one.
    """
    recipient = make_recipient(actor=owner_actor, email="ada@example.com")
    api.force_login(owner)
    response = api.post(DEVICES_URL, data=_register_body(recipient), content_type=JSON)

    assert response.status_code == 200, response.content
    body = _body(response)
    assert set(body) == {
        "id",
        "recipient_id",
        "organization_id",
        "platform",
        "label",
        "retired_at",
        "created_at",
        "updated_at",
    }
    assert body["recipient_id"] == str(recipient.pk)
    assert body["retired_at"] is None
    assert A_TOKEN not in json.dumps(body)


def test_the_register_door_is_safe_to_call_twice(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """The property a mobile client depends on, over the wire this time."""
    recipient = make_recipient(actor=owner_actor, email="ada@example.com")
    api.force_login(owner)
    first = api.post(DEVICES_URL, data=_register_body(recipient), content_type=JSON)
    second = api.post(DEVICES_URL, data=_register_body(recipient), content_type=JSON)

    assert first.status_code == second.status_code == 200
    assert _body(first)["id"] == _body(second)["id"]
    assert Device.objects.for_tenant(tenant).count() == 1


def test_the_retire_door_retires_one_install(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    recipient = make_recipient(actor=owner_actor, email="ada@example.com")
    api.force_login(owner)
    created = _body(api.post(DEVICES_URL, data=_register_body(recipient), content_type=JSON))

    response = api.post(f"{DEVICES_URL}{created['id']}/retire/", content_type=JSON)

    assert response.status_code == 200, response.content
    assert _body(response)["retired_at"] is not None


def test_an_unknown_body_field_is_refused_by_name(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """`StrictIn`, at this door. A misspelled field is never a silent success.

    *Absent:* `{"token": ...}` instead of `{"push_token": ...}` answers `200`
    with a device registered against nothing, which is the exact shape SB-1 was
    written for.
    """
    recipient = make_recipient(actor=owner_actor, email="ada@example.com")
    api.force_login(owner)
    response = api.post(
        DEVICES_URL,
        data=json.dumps({"recipient_id": str(recipient.pk), "platform": "ios", "token": A_TOKEN}),
        content_type=JSON,
    )

    # 422 and not 400, which is the tree's own settled answer rather than a
    # guess: `config/api.py`'s `STATUS_FOR` records the argument (SB-1, RFC 9110
    # §15.5.21) — 400 is "a rule about your data did not hold", 422 is "this is
    # not the shape this operation accepts", decided before any route ran.
    assert response.status_code == 422, response.content
    body = _body(response)
    assert body["code"] == "invalid_body"
    assert "token" in json.dumps(body)


def test_an_unknown_device_id_is_not_found(api: Client, owner: User) -> None:
    api.force_login(owner)
    response = api.post(f"{DEVICES_URL}{uuid4()}/retire/", content_type=JSON)
    assert response.status_code == 404, response.content
    assert _body(response)["code"] == "not_found"


# --- the ceiling -----------------------------------------------------------------


def test_a_token_scoped_elsewhere_is_refused_and_told_which_scope(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """The ceiling probe, half one: `messaging:write` does not reach this door.

    Which is the whole argument for `devices` being its own family. A token
    trusted to contact people is not thereby trusted to keep the address book,
    and — read the other way, which is the direction that matters — a mobile
    client's token can hold `devices:write` and be unable to mail anybody.

    *Absent:* the two capabilities are one string and there is no narrow
    credential to give a phone.
    """
    recipient = make_recipient(actor=owner_actor, email="ada@example.com")
    _, plaintext = issue_token(
        user=owner,
        tenant=tenant,
        name="elsewhere",
        scopes=["messaging:write"],
        actor=actor_for(user=owner, tenant=tenant),
    )

    response = api.post(
        DEVICES_URL,
        data=_register_body(recipient),
        content_type=JSON,
        headers=_bearer(plaintext),
    )

    assert response.status_code == 403, response.content
    body = _body(response)
    assert body["code"] == "insufficient_scope"
    assert "devices:write" in body["detail"], body
    assert body["remedies"], "a refusal with no way out is a dead end with a status code"


def test_a_token_scoped_for_devices_registers(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """The other half. Without it the test above would pass on a door that
    refused everybody."""
    recipient = make_recipient(actor=owner_actor, email="ada@example.com")
    _, plaintext = issue_token(
        user=owner,
        tenant=tenant,
        name="the phone",
        scopes=["devices:write"],
        actor=actor_for(user=owner, tenant=tenant),
    )

    response = api.post(
        DEVICES_URL,
        data=_register_body(recipient),
        content_type=JSON,
        headers=_bearer(plaintext),
    )

    assert response.status_code == 200, response.content


def test_the_family_key_is_frozen() -> None:
    """`devices` joined the census in the commit that shipped the door.

    The census is written by hand and pinned equal to the live vocabulary by
    `apps/accounts/tests/test_scopes.py`; this is the same claim said in the app
    that shipped the key, so a reader of comms finds out that renaming its tag
    kills every token holding it.
    """
    from apps.core.api import scopes

    assert "devices" in scopes.FROZEN_FAMILIES
    assert "devices:write" in scopes.vocabulary()


# --- what was deliberately not built -----------------------------------


def test_there_is_no_read_door_for_devices() -> None:
    """The absence, asserted, so it reads as a decision rather than an omission.

    The route list was a registration door and a retirement door. There is no
    list, so `devices:read` derives into the vocabulary and reaches nothing —
    exactly the shape `usage:write` has, and recorded in
    `apps/core/api/scopes.py` beside the key.

    Fails the day a read door lands: at which point that rung owes the
    `DevicePage` envelope, the MCP twin, a query pin and a sibling-branch test,
    and this test is where that obligation is written down for the person about
    to add it.
    """
    from config.api import api as ninja_api

    document = ninja_api.get_openapi_schema()
    tagged: list[tuple[str, str]] = []
    for path, node in (document.get("paths") or {}).items():
        for method, operation in node.items():
            if "devices" in (operation.get("tags") or []):
                tagged.append((method.upper(), path))

    assert sorted(tagged) == [
        ("POST", "/api/v1/devices/"),
        ("POST", "/api/v1/devices/{device_id}/retire/"),
    ], tagged
    # Read off the published document rather than off this module, so the claim
    # is about what a client can actually call. The list above being exactly
    # these two is both halves: no GET (the absence being asserted) and the
    # family really is on the wire (so the absence is not passing because
    # nothing is tagged `devices` at all).
