"""Reads for the comms app.

House rule 12: `selectors.py` never writes. House rule 24: every read of an
org-scoped row is `for_tenant(...).visible_to(...)` — both halves, always,
because `Message`, `Recipient`, `ChannelPreference`, `MessageEngagement` and
`Device` belong to one *part* of a tenant and a read that stopped after the
first half would hand a dealer the group's correspondence.

`MessageTemplate` is the exception, and it is a tenant-scoped model rather than
an org-scoped one on purpose: templates are the tenant's house style and every
branch sends from the same ones. It is read with `for_tenant` alone, which is
what `visible_to` would refuse to be chained onto anyway.

**`get_template` is where "the latest active version" is decided**, once, so
that `send()`, a preview door and a test all resolve the same row. Highest
version wins among the active ones; a retired version stays readable through
every `Message` that points at it and stops being what a name resolves to.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.comms.models import (
    ChannelPreference,
    DeliveryPolicy,
    Device,
    Message,
    MessageEngagement,
    MessageTemplate,
    Recipient,
)
from apps.core.exceptions import NotFound
from apps.core.models import ScopedQuerySet, Tenant


def list_messages(*, tenant: Tenant | None, org: Any = None) -> ScopedQuerySet[Message]:
    """The messages this hat may see, with the relations `MessageOut` reads.

    `select_related` is the contract rather than an optimisation: `MessageOut`
    walks `recipient` and `organization` for every row, so without it a page of
    fifty is a hundred and one queries. The query pin in `tests/test_api.py` is
    what turns removing it into a failure rather than a slow page.
    """
    return (
        Message.objects.for_tenant(tenant)
        .visible_to(org)
        .select_related("recipient", "organization")
    )


def get_message(*, tenant: Tenant | None, message_id: UUID, org: Any = None) -> Message:
    """One message this hat may see, or `NotFound`."""
    message = list_messages(tenant=tenant, org=org).filter(pk=message_id).first()
    if message is None:
        raise NotFound()
    return message


def get_message_by_provider_id(
    *,
    tenant: Tenant | None,
    provider_message_id: str,
    org: Any = None,
) -> Message:
    """The message a transport is talking about, or `NotFound`.

    **This is the cross-tenant wall on the status webhook**, and it is the whole
    of it: a provider's payload names a message by the id *that provider* gave
    us, and an id is a string somebody else's server chose. Reading it back
    through `for_tenant(...).visible_to(...)` means a delivery posted at one
    tenant's connection can only ever touch that tenant's rows — a payload
    naming another tenant's message id finds nothing and the caller logs it.
    Nothing about the answer distinguishes "not yours" from "does not exist",
    which is the same refusal `get_message` makes for the same reason.

    **An empty id is `NotFound`, checked first.** Every message that has not yet
    been accepted by a transport carries `provider_message_id=""`, so a filter
    on the empty string would match a whole queue of unrelated rows and the
    first one would be marked delivered. That is the bug this branch exists for,
    not a defensive habit.

    Newest first when two rows somehow share an id: this template's
    `EmailChannel` mints one per message primary key so it cannot happen, but a
    product's provider may reuse ids across resends, and the most recent send is
    the one a status is about.
    """
    handle = str(provider_message_id or "").strip()
    if not handle:
        raise NotFound()
    message = (
        list_messages(tenant=tenant, org=org)
        .filter(provider_message_id=handle)
        .order_by("-created_at")
        .first()
    )
    if message is None:
        raise NotFound()
    return message


def list_engagements(
    *,
    tenant: Tenant | None,
    message: Message,
    org: Any = None,
) -> ScopedQuerySet[MessageEngagement]:
    """What a provider says was done with one message, most recent first.

    **Takes the resolved `Message` and not an id, deliberately.** The row this
    hat may not see is `not_found` at `get_message`, once, in the door — so a
    caller that reached this selector has already been told no if it was going
    to be. Taking an id here would put a second, quieter copy of that decision
    in a read whose refusal nobody would notice was missing.

    The scoping is still both halves and not a formality: the engagement row's
    organization is the MESSAGE's branch (`derive_org_from`), so a hat that can
    see the message can see its engagements and a sibling branch's hat sees
    nothing — which is what `for_tenant(...).visible_to(...)` says here even
    though `message.pk` has already narrowed the set.

    Ordered by `occurred_at` rather than by `created_at`: the caller's question
    is when the person did the thing, and a webhook that arrived an hour late
    must not sort as an hour-late open. `-created_at` is the tiebreak so the
    order is total (two providers can report one moment).
    """
    return (
        MessageEngagement.objects.for_tenant(tenant)
        .visible_to(org)
        .filter(message=message)
        .order_by("-occurred_at", "-created_at")
    )


def list_devices(
    *,
    tenant: Tenant | None,
    org: Any = None,
    recipient: Recipient | None = None,
    include_retired: bool = False,
) -> ScopedQuerySet[Device]:
    """The devices this hat may push to. **Retired ones are out by default.**

    `list_recipients`' shape and its reason: retiring an install is what a
    product does when a token stops working, and a read that still returned it
    would make the verb do nothing. The rows are never deleted, because a
    message that went to that handset is still in the log.

    `recipient=` narrows to one contact and is what the transport asks for. It
    takes the resolved row rather than an id for `list_engagements`' reason: the
    caller has already been refused if it was going to be.
    """
    rows = Device.objects.for_tenant(tenant).visible_to(org).select_related("organization")
    if recipient is not None:
        rows = rows.filter(recipient=recipient)
    return rows if include_retired else rows.filter(retired_at__isnull=True)


def get_device(*, tenant: Tenant | None, device_id: UUID, org: Any = None) -> Device:
    """One device this hat may reach, or `NotFound`.

    **Retired rows resolve here**, unlike in the list, and the asymmetry is
    `get_recipient`'s: retiring an already-retired device has to be able
    to answer with the row it found rather than with a 404 that reads as "that
    device never existed".
    """
    device = list_devices(tenant=tenant, org=org, include_retired=True).filter(pk=device_id).first()
    if device is None:
        raise NotFound()
    return device


def get_device_by_token_hash(
    *,
    tenant: Tenant | None,
    push_token_hash: str,
    org: Any = None,
) -> Device | None:
    """The row a re-registration should update, or `None` for a new install.

    **`None` rather than `NotFound`**, because not finding one is the ordinary
    answer for a device nobody has registered before — this is the read behind
    `register_device`'s upsert, not a door's fetch.

    An empty digest is `None` before any query runs, for
    `get_message_by_provider_id`'s reason: a filter on the empty string would
    match whatever rows a bug had left with a blank column and hand the first
    one back as "the device this token belongs to".
    """
    digest = str(push_token_hash or "").strip()
    if not digest:
        return None
    return (
        list_devices(tenant=tenant, org=org, include_retired=True)
        .filter(push_token_hash=digest)
        .first()
    )


def list_recipients(
    *,
    tenant: Tenant | None,
    org: Any = None,
    include_archived: bool = False,
) -> ScopedQuerySet[Recipient]:
    """The people this hat may address. **Archived contacts are out by default.**

    Archiving is what a product does when a contact is closed, and the point of
    it is that the working contact book stops showing them; a list that included
    them would make the verb do nothing. `include_archived=True` is how the
    door's `?archived=` filter and `get_recipient` ask for the whole table —
    the rows are never deleted, because every `Message` ever sent points at one.
    """
    rows = Recipient.objects.for_tenant(tenant).visible_to(org).select_related("organization")
    return rows if include_archived else rows.filter(archived_at__isnull=True)


def get_recipient(*, tenant: Tenant | None, recipient_id: UUID, org: Any = None) -> Recipient:
    """One recipient this hat may address, or `NotFound`.

    The same `NotFound` for a recipient in another tenant, in a sibling branch,
    or one that does not exist. A refusal that distinguished them would tell the
    caller that somebody else's customer exists, which is the fact the scoping
    was hiding.

    **Archived rows resolve here**, unlike in the list, and the asymmetry is
    deliberate: a message detail has to be able to name who it went to, and
    un-archiving a contact you cannot fetch would be impossible. Archiving hides
    somebody from the contact book; it does not make them unreadable.
    """
    recipient = (
        list_recipients(tenant=tenant, org=org, include_archived=True)
        .filter(pk=recipient_id)
        .first()
    )
    if recipient is None:
        raise NotFound()
    return recipient


def list_templates(*, tenant: Tenant | None) -> ScopedQuerySet[MessageTemplate]:
    """Every version of every template this tenant has, newest version first."""
    return MessageTemplate.objects.for_tenant(tenant).order_by("name", "-version")


def get_template_by_id(*, tenant: Tenant | None, template_id: UUID) -> MessageTemplate:
    """One template version by id, or `NotFound`.

    By id rather than by name, because this is the read behind a detail door and
    a *retired* version has to stay readable: `get_template` below answers "what
    would `send()` use", which is a different question and deliberately a
    different function.
    """
    template = MessageTemplate.objects.for_tenant(tenant).filter(pk=template_id).first()
    if template is None:
        raise NotFound()
    return template


def get_template(*, tenant: Tenant | None, name: str) -> MessageTemplate:
    """The latest **active** version of a named template, or `NotFound`.

    This is the only place a template name becomes a row. A caller naming a
    template the tenant does not have gets `not_found` — not a 500 from a
    `None`, and not a silent fall back to some other tenant's copy.
    """
    template = (
        MessageTemplate.objects.for_tenant(tenant)
        .filter(name=name.strip(), is_active=True)
        .order_by("-version")
        .first()
    )
    if template is None:
        raise NotFound(f"No active template named {name!r}.")
    return template


# --- delivery policies ------------------------------------------------------------


def list_policies(*, tenant: Tenant | None) -> ScopedQuerySet[DeliveryPolicy]:
    """Every version of every policy this tenant has, newest version first.

    Retired versions included, and that is the point: "what did the escalation
    look like when this message went out in March" is a question the message row
    asks by name and number, and a list that showed only the live version could
    not answer it.

    Tenant-scoped and not org-scoped, because `DeliveryPolicy` is — see the
    model. `visible_to` would raise on it rather than narrow it.
    """
    return DeliveryPolicy.objects.for_tenant(tenant).order_by("name", "-version")


def get_policy(*, tenant: Tenant | None, name: str) -> DeliveryPolicy:
    """The latest **active** version of a named policy, or `NotFound`.

    The exact shape of `get_template`, and for the exact reason: this is the one
    place a policy *name* becomes a row, so `send(policy="oncall")`, the detail
    door and a test all resolve the same version. Highest version wins among the
    active ones; retiring v2 puts v1 back in service.

    A retired version stays readable through `list_policies` — every `Message`
    that ran under it records the name and the number — but stops being what a
    name resolves to, which is the whole difference between retiring and
    deleting.
    """
    policy = (
        DeliveryPolicy.objects.for_tenant(tenant)
        .filter(name=str(name).strip(), is_active=True)
        .order_by("-version")
        .first()
    )
    if policy is None:
        raise NotFound(f"No active policy named {str(name).strip()!r}.")
    return policy


def list_preferences(
    *,
    tenant: Tenant | None,
    recipient: Recipient,
    org: Any = None,
) -> ScopedQuerySet[ChannelPreference]:
    """What one person has agreed to, channel by channel.

    A list rather than a single row because a preference is per channel and the
    absence of a row is itself an answer: a person with one email preference and
    nothing for SMS has consented to nothing on SMS, and the page says so by
    not carrying a row for it.
    """
    return (
        ChannelPreference.objects.for_tenant(tenant)
        .visible_to(org)
        .filter(recipient=recipient)
        .select_related("recipient")
        .order_by("channel")
    )


def get_preference(
    *,
    tenant: Tenant | None,
    recipient: Recipient,
    channel: str,
    org: Any = None,
) -> ChannelPreference | None:
    """What this person has agreed to on this channel, or `None`.

    `None` rather than a refusal, because **the absence of a row is an answer**:
    nobody has consented, nobody has set quiet hours, and nothing is suppressed.
    `send()` reads that as "transactional yes, marketing no", which is the
    fail-closed default for the half that needs consent and the fail-open
    default for the half the person's own action asked for.
    """
    return (
        ChannelPreference.objects.for_tenant(tenant)
        .visible_to(org)
        .filter(recipient=recipient, channel=channel)
        .first()
    )
