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

**And since Phase R every door read ASKS** (ADR core-27, architect §C6). `actor`
is a required keyword on every selector a door reaches — never optional, because
an `actor=None` default is a read that fails open the first time a caller
forgets — and the selector calls `require(actor, "<kind>.read", ...)` exactly
once. **Two questions, two owners, and they are never merged** (rule 24, BVB-4):
`for_tenant`/`visible_to` decide WHICH rows, and `require` decides WHETHER this
kind, here. Nothing below filters rows by permission.

**Where the question is asked differs between a list and a get, and the order is
the rule** (reach before capability — the ruling `architecture.md` records):

* a `list_` asks at the **acting hat** (`obj=None` → `where_of` → `actor.org`)
  BEFORE it builds the queryset. A list has no row to hide, so the only honest
  answers are the page and `forbidden`.
* a `get_` asks **after the scoped fetch**, with `obj=row`, at the row's own
  node. Outside the subtree the fetch has already raised `NotFound` and the
  capability is never consulted — "not there" and "not yours" stay one answer
  (§C8); inside it, without the key, the answer is `Forbidden`.

**The `_<noun>_in` helpers are the rows without the capability**, and they exist
so that a `get_` built on a `list_` asks once rather than twice: core's
`_organizations_in` is the worked example and this is the same shape one app
over. They are private, so rule 54 (d)'s population — public `get_`/`list_`
selectors over a kind — does not include them, which is the same line the rule
reads.

**Three reads here are MACHINE reads and each carries `# read-open:` with its
reason.** A provider's status webhook and a re-registering device resolve a row
before any actor exists, and the push transport lists a contact's devices as the
system. A valve is a sentence somebody wrote and a reviewer can disagree with,
it sits in the selector it excuses, and the gate counts and prints every one.

A `system` actor passes at `allows` step 1, so the activities, the workflows and
the seed are untouched.
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
from apps.core.actor import Actor
from apps.core.authz import require
from apps.core.exceptions import Invalid, NotFound
from apps.core.models import ScopedQuerySet, Tenant

# --- messages -------------------------------------------------------------------


def _messages_in(*, tenant: Tenant | None, org: Any = None) -> ScopedQuerySet[Message]:
    """The messages this hat may see, with the relations `MessageOut` reads.

    **The rows, without the capability.** Private on purpose: the two public
    reads below each ask `message.read` exactly once, and building one of them
    on the other would ask twice — a second, quieter copy of a decision one
    layer up already made.

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


def list_messages(
    *, tenant: Tenant | None, org: Any = None, actor: Actor
) -> ScopedQuerySet[Message]:
    """The messages this hat may see, newest first."""
    # THE CAPABILITY, at the hat, BEFORE the queryset: a list has no row to
    # hide, so somebody without `message.read` here hears that rather than an
    # empty page that looks like an organization that has never sent anything.
    require(actor, "message.read")
    return _messages_in(tenant=tenant, org=org)


def get_message(
    *, tenant: Tenant | None, message_id: UUID, org: Any = None, actor: Actor
) -> Message:
    """One message this hat may see, or `NotFound`."""
    message = _messages_in(tenant=tenant, org=org).filter(pk=message_id).first()
    if message is None:
        raise NotFound()
    # REACH FIRST, then capability: the fetch above is what makes a sibling
    # branch `not_found`, and this line is what makes a message inside the
    # subtree `forbidden` when the actor holds no `message.read` at its node.
    require(actor, "message.read", message)
    return message


def get_message_by_provider_id(
    *,
    tenant: Tenant | None,
    provider_message_id: str,
    org: Any = None,
) -> Message:
    """The message a transport is talking about, or `NotFound`.

    # read-open: a provider's signed status webhook resolves the message its
    # payload names before any person is in the picture — the caller is the
    # transport, authenticated by signature, and there is no membership to ask
    # about. The tenancy wall below is the whole of the authorization here, and
    # the service that calls this asks `message.record_status` for the WRITE.

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
        _messages_in(tenant=tenant, org=org)
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
    actor: Actor,
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

    **`message_engagement.read` is its own key and not the message's.** Who may
    read a message is one question and who may read what a provider reported
    about the person who received it is another; a product withholding the
    second from a support role and keeping the first is exactly the shape ADR
    core-27 exists to make expressible.

    Ordered by `occurred_at` rather than by `created_at`: the caller's question
    is when the person did the thing, and a webhook that arrived an hour late
    must not sort as an hour-late open. `-created_at` is the tiebreak so the
    order is total (two providers can report one moment).
    """
    require(actor, "message_engagement.read")
    return (
        MessageEngagement.objects.for_tenant(tenant)
        .visible_to(org)
        .filter(message=message)
        .order_by("-occurred_at", "-created_at")
    )


# --- devices --------------------------------------------------------------------


def list_devices(
    *,
    tenant: Tenant | None,
    org: Any = None,
    recipient: Recipient | None = None,
    include_retired: bool = False,
) -> ScopedQuerySet[Device]:
    """The devices this hat may push to. **Retired ones are out by default.**

    # read-open: the push transport's own read, made as the system while it is
    # delivering a message — `providers.py`'s `_devices_for` is the one caller
    # and it holds a message rather than an actor. There is no door on this
    # list: a person reads one device at a time through `get_device`, which
    # asks, and `apps/comms/tests/test_reads_ask.py` pins that there is no
    # route or tool behind this name.

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


def get_device(*, tenant: Tenant | None, device_id: UUID, org: Any = None, actor: Actor) -> Device:
    """One device this hat may reach, or `NotFound`.

    **Retired rows resolve here**, unlike in the list, and the asymmetry is
    `get_recipient`'s: retiring an already-retired device has to be able
    to answer with the row it found rather than with a 404 that reads as "that
    device never existed".
    """
    device = list_devices(tenant=tenant, org=org, include_retired=True).filter(pk=device_id).first()
    if device is None:
        raise NotFound()
    require(actor, "device.read", device)
    return device


def get_device_by_token_hash(
    *,
    tenant: Tenant | None,
    push_token_hash: str,
    org: Any = None,
) -> Device | None:
    """The row a re-registration should update, or `None` for a new install.

    # read-open: the upsert read behind `register_device`, not a door's fetch.
    # The caller has already been authorized to WRITE a device
    # (`require(actor, "device.create", recipient)` immediately above it in the
    # service), and asking `device.read` here would let a product that withheld
    # reading devices turn every re-registration into a duplicate row.

    **`None` rather than `NotFound`**, because not finding one is the ordinary
    answer for a device nobody has registered before.

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


# --- recipients -----------------------------------------------------------------


#: The three cuts of the contact book `show` may ask for, in the order a
#: refusal names them.
RECIPIENT_SHOWS: tuple[str, ...] = ("live", "archived", "all")


def _recipients_in(
    *,
    tenant: Tenant | None,
    org: Any = None,
    show: str = "live",
) -> ScopedQuerySet[Recipient]:
    """The rows, without the capability. `_messages_in`'s shape and its reason.

    **The cut is the queryset's own widening, never a filter on `archived_at`.**
    `Recipient` is `Archivable`, so `for_tenant()` has already taken the closed
    contacts out before anything here runs; a hand filter on the column after it
    (`archived_at__isnull=False`) answers an empty book with no error, and one
    that "includes" archived rows by not filtering answers the live book alone.
    `.including_archived()` and `.archived_only()` are the only two ways back
    in. `archived_by` rides the same join as the organization, because every
    read shape of a contact names who closed it.
    """
    rows = (
        Recipient.objects.for_tenant(tenant)
        .visible_to(org)
        .select_related("organization", "archived_by")
    )
    if show == "live":
        return rows
    if show == "archived":
        return rows.archived_only()
    if show == "all":
        return rows.including_archived()
    raise Invalid({"show": [f"Show one of: {', '.join(RECIPIENT_SHOWS)}."]})


def list_recipients(
    *,
    tenant: Tenant | None,
    org: Any = None,
    show: str = "live",
    actor: Actor,
) -> ScopedQuerySet[Recipient]:
    """The people this hat may address. **Archived contacts are out by default.**

    Archiving is what a product does when a contact is closed, and the point of
    it is that the working contact book stops showing them; a list that included
    them would make the verb do nothing. `show="archived"` is the closed
    contacts alone and `show="all"` both — the rows are never deleted, because
    every `Message` ever sent points at one. Any other value is `Invalid`
    naming `show`.
    """
    require(actor, "recipient.read")
    return _recipients_in(tenant=tenant, org=org, show=show)


def get_recipient(
    *, tenant: Tenant | None, recipient_id: UUID, org: Any = None, actor: Actor
) -> Recipient:
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
    recipient = _recipients_in(tenant=tenant, org=org, show="all").filter(pk=recipient_id).first()
    if recipient is None:
        raise NotFound()
    require(actor, "recipient.read", recipient)
    return recipient


# --- templates ------------------------------------------------------------------


def _templates_in(*, tenant: Tenant | None) -> ScopedQuerySet[MessageTemplate]:
    """The rows, without the capability. `_messages_in`'s shape and its reason."""
    return MessageTemplate.objects.for_tenant(tenant).order_by("name", "-version")


def list_templates(*, tenant: Tenant | None, actor: Actor) -> ScopedQuerySet[MessageTemplate]:
    """Every version of every template this tenant has, newest version first."""
    # hat-scoped: a template is TENANT-scoped and names no branch — it is the
    # tenant's house style and every organization sends from the same ones.
    # There is no node on the row to ask at, so the acting hat is not a
    # fallback here, it is the only node the question has; asking at the root
    # instead would make a branch's read answer for authority it does not act
    # with, and asking at a row that has no organization is the shape this
    # rule exists to name.
    # DATED, 2026-09-17, the v2.1 stopgap: reads of a tenant-wide kind are the
    # hat's on every door until v2.2 gives these kinds a home, and the rung that
    # homes this model deletes this valve
    # (the universal-homing proposal, 2026-09-17 — every record homed at a node).
    require(actor, "message_template.read")
    return _templates_in(tenant=tenant)


def get_template_by_id(
    *, tenant: Tenant | None, template_id: UUID, actor: Actor
) -> MessageTemplate:
    """One template version by id, or `NotFound`.

    By id rather than by name, because this is the read behind a detail door and
    a *retired* version has to stay readable: `get_template` below answers "what
    would `send()` use", which is a different question and deliberately a
    different function.
    """
    template = _templates_in(tenant=tenant).filter(pk=template_id).first()
    if template is None:
        raise NotFound()
    # hat-scoped: a template is TENANT-scoped and names no branch — it is the
    # tenant's house style and every organization sends from the same ones.
    # There is no node on the row to ask at, so the acting hat is not a
    # fallback here, it is the only node the question has; asking at the root
    # instead would make a branch's read answer for authority it does not act
    # with, and asking at a row that has no organization is the shape this
    # rule exists to name.
    # DATED, 2026-09-17, the v2.1 stopgap: reads of a tenant-wide kind are the
    # hat's on every door until v2.2 gives these kinds a home, and the rung that
    # homes this model deletes this valve
    # (the universal-homing proposal, 2026-09-17 — every record homed at a node).
    require(actor, "message_template.read")
    return template


def get_template(*, tenant: Tenant | None, name: str, actor: Actor) -> MessageTemplate:
    """The latest **active** version of a named template, or `NotFound`.

    This is the only place a template name becomes a row. A caller naming a
    template the tenant does not have gets `not_found` — not a 500 from a
    `None`, and not a silent fall back to some other tenant's copy.

    **A template is TENANT-scoped**, so the row names no branch and
    `where_of(actor, template)` falls back to the acting hat — the same node the
    list asks at, which is what keeps the two doors' answers in step.
    """
    template = (
        _templates_in(tenant=tenant)
        .filter(name=name.strip(), is_active=True)
        .order_by("-version")
        .first()
    )
    if template is None:
        raise NotFound(f"No active template named {name!r}.")
    # hat-scoped: a template is TENANT-scoped and names no branch — it is the
    # tenant's house style and every organization sends from the same ones.
    # There is no node on the row to ask at, so the acting hat is not a
    # fallback here, it is the only node the question has; asking at the root
    # instead would make a branch's read answer for authority it does not act
    # with, and asking at a row that has no organization is the shape this
    # rule exists to name.
    # DATED, 2026-09-17, the v2.1 stopgap: reads of a tenant-wide kind are the
    # hat's on every door until v2.2 gives these kinds a home, and the rung that
    # homes this model deletes this valve
    # (the universal-homing proposal, 2026-09-17 — every record homed at a node).
    require(actor, "message_template.read")
    return template


# --- delivery policies ------------------------------------------------------------


def _policies_in(*, tenant: Tenant | None) -> ScopedQuerySet[DeliveryPolicy]:
    """The rows, without the capability. `_messages_in`'s shape and its reason."""
    return DeliveryPolicy.objects.for_tenant(tenant).order_by("name", "-version")


def list_policies(*, tenant: Tenant | None, actor: Actor) -> ScopedQuerySet[DeliveryPolicy]:
    """Every version of every policy this tenant has, newest version first.

    Retired versions included, and that is the point: "what did the escalation
    look like when this message went out in March" is a question the message row
    asks by name and number, and a list that showed only the live version could
    not answer it.

    Tenant-scoped and not org-scoped, because `DeliveryPolicy` is — see the
    model. `visible_to` would raise on it rather than narrow it.
    """
    # hat-scoped: a delivery policy is TENANT-scoped and names no branch — it is the
    # tenant's house style and every organization escalates from the same ones.
    # There is no node on the row to ask at, so the acting hat is not a
    # fallback here, it is the only node the question has; asking at the root
    # instead would make a branch's read answer for authority it does not act
    # with, and asking at a row that has no organization is the shape this
    # rule exists to name.
    # DATED, 2026-09-17, the v2.1 stopgap: reads of a tenant-wide kind are the
    # hat's on every door until v2.2 gives these kinds a home, and the rung that
    # homes this model deletes this valve
    # (the universal-homing proposal, 2026-09-17 — every record homed at a node).
    require(actor, "delivery_policy.read")
    return _policies_in(tenant=tenant)


def get_policy(*, tenant: Tenant | None, name: str, actor: Actor) -> DeliveryPolicy:
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
        _policies_in(tenant=tenant)
        .filter(name=str(name).strip(), is_active=True)
        .order_by("-version")
        .first()
    )
    if policy is None:
        raise NotFound(f"No active policy named {str(name).strip()!r}.")
    # hat-scoped: a delivery policy is TENANT-scoped and names no branch — it is the
    # tenant's house style and every organization escalates from the same ones.
    # There is no node on the row to ask at, so the acting hat is not a
    # fallback here, it is the only node the question has; asking at the root
    # instead would make a branch's read answer for authority it does not act
    # with, and asking at a row that has no organization is the shape this
    # rule exists to name.
    # DATED, 2026-09-17, the v2.1 stopgap: reads of a tenant-wide kind are the
    # hat's on every door until v2.2 gives these kinds a home, and the rung that
    # homes this model deletes this valve
    # (the universal-homing proposal, 2026-09-17 — every record homed at a node).
    require(actor, "delivery_policy.read")
    return policy


# --- consent --------------------------------------------------------------------


def _preferences_in(
    *,
    tenant: Tenant | None,
    recipient: Recipient,
    org: Any = None,
) -> ScopedQuerySet[ChannelPreference]:
    """The rows, without the capability. `_messages_in`'s shape and its reason."""
    return (
        ChannelPreference.objects.for_tenant(tenant)
        .visible_to(org)
        .filter(recipient=recipient)
        .select_related("recipient")
        .order_by("channel")
    )


def list_preferences(
    *,
    tenant: Tenant | None,
    recipient: Recipient,
    org: Any = None,
    actor: Actor,
) -> ScopedQuerySet[ChannelPreference]:
    """What one person has agreed to, channel by channel.

    A list rather than a single row because a preference is per channel and the
    absence of a row is itself an answer: a person with one email preference and
    nothing for SMS has consented to nothing on SMS, and the page says so by
    not carrying a row for it.
    """
    require(actor, "channel_preference.read")
    return _preferences_in(tenant=tenant, recipient=recipient, org=org)


def get_preference(
    *,
    tenant: Tenant | None,
    recipient: Recipient,
    channel: str,
    org: Any = None,
    actor: Actor,
) -> ChannelPreference | None:
    """What this person has agreed to on this channel, or `None`.

    `None` rather than a refusal, because **the absence of a row is an answer**:
    nobody has consented, nobody has set quiet hours, and nothing is suppressed.
    `send()` reads that as "transactional yes, marketing no", which is the
    fail-closed default for the half that needs consent and the fail-open
    default for the half the person's own action asked for.

    **Where the capability is asked when there is no row.** A missing row has no
    node of its own, so the question is asked at the acting hat — the same node
    `list_preferences` asks at. Asking only when a row turns up would make
    "consented to nothing" the one consent answer a withheld reader could still
    get, which is the half that matters most.
    """
    row = (
        _preferences_in(tenant=tenant, recipient=recipient, org=org).filter(channel=channel).first()
    )
    require(actor, "channel_preference.read", row)
    return row
