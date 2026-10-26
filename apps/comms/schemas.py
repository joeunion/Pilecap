"""The wire shapes. Pydantic, and therefore the same shapes every door uses.

`MessageOut` is the message log's public face and it is also the **event
payload**: `comms.message.queued`, `.sent`, `.failed` and `.suppressed` all
carry exactly this object, so a webhook subscriber and a REST client see the
same fields for the same message rather than two shapes that drift.
`MessageEngagementOut` is the same arrangement one table over, for
`comms.message.opened` and `.clicked` — and it is a SEPARATE shape rather than
more fields on `MessageOut` because an engagement is a different fact about a
different moment (ADR comms-9), and a client reading delivery truth must not
have to skip past a read inference to find it.

What is deliberately *not* here is the rendered body. The log keeps the subject
because that is what a human scanning it reads; the body is re-rendered from
the immutable template version at delivery time, and a read door that handed it
back would make every message list a copy of the customer's outgoing mail.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Annotated, Any
from uuid import UUID

from ninja import FilterLookup, FilterSchema, Schema
from pydantic import ConfigDict, Field

from apps.comms.models import Category, Channel
from apps.core.schemas import (
    ActsOut,
    ActsPage,
    ArchivedOut,
    ListPage,
    StrictIn,
    example,
    personal,
)


class MessageIn(StrictIn):
    """What a client may ask us to send.

    `template` is a **name**, not an id: the caller asks for "the invoice
    reminder", and `send()` resolves the latest active version for the tenant.
    A caller that could name a version could pin a retired one for ever.

    `context` is free-form by nature — it is the template's variables — and it
    is validated against that template's `context_schema` inside `send()`,
    before anything is written.

    **Either a template or a policy, never both** (C2-comms-b). `policy` names
    an escalation — *text them, wait, then email* — and its first step already
    says which template on which channel, so naming one alongside it is a
    caller who means two different things at once and is refused by name rather
    than silently resolved one way. The three are optional *on the schema* and
    the pairing is decided in `send()`, in one place, so the machine door and a
    management command get the same refusal as the HTTP door.

    `channel` therefore no longer defaults to `"email"` here — it defaults in
    `send()`, which is where it always meant something. A body that omits it
    still sends email, exactly as before.
    """

    # **A CLASS-level example, because the defect was about the WHOLE.**
    # Every field below is individually plausible, and the object composed out
    # of them was a request this door will never accept: `template`, `channel`
    # AND `policy` together, which `send()` refuses by design ("Policy X already
    # says which template and channel each step uses"). Schema-valid,
    # vocabulary-dead, and no per-field example can fix
    # it, because no field is wrong.
    #
    # `apps.core.api.docs.add_examples` skips a component that already carries
    # one, which is the seam that makes this work: the composed object is only
    # synthesised for a schema that declared nothing. So the class publishes one
    # legal combination and `policy` is left OUT rather than shown empty — an
    # example is a thing people paste, and the pasted body should be the shorter
    # true one. The escalation form is documented in the route's own contract,
    # where a reader meets it with the sentence that explains it.
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "recipient_id": "0195f1d4-6b33-7d24-9e35-3c4d5e6f7a8b",
                "template": "invoice-reminder",
                "context": {"invoice_number": "INV-1042", "due_on": "2026-09-01"},
                "channel": "email",
            }
        }
    )

    recipient_id: UUID
    template: str = Field(default="", max_length=100, json_schema_extra=example("invoice-reminder"))
    context: dict[str, Any] = Field(
        default_factory=dict,
        json_schema_extra=example({"invoice_number": "INV-1042", "due_on": "2026-09-01"}),
    )
    channel: str = Field(default="", max_length=16, json_schema_extra=example("email"))
    policy: str = Field(default="", max_length=100, json_schema_extra=example("dunning"))
    #: When to send it, if not now (T4). **Timezone-aware, or refused**: a
    #: moment with no offset is a moment in somebody's assumption, and a
    #: scheduled send is the one operation that cannot afford to guess whose.
    #: A moment already past sends now rather than refusing — a client's clock
    #: being a second behind must not become an error. Absent is every send made
    #: before this field existed and behaves identically.
    send_at: datetime | None = Field(
        default=None, json_schema_extra=example("2026-09-01T09:00:00Z")
    )


class MessageFilter(FilterSchema):
    """The narrowings a client may ask for, declared rather than improvised."""

    status: Annotated[str | None, FilterLookup(q="status")] = None
    channel: Annotated[str | None, FilterLookup(q="channel")] = None
    template: Annotated[str | None, FilterLookup(q="template_name")] = None


class MessageOut(Schema):
    """One message, as every door reports it."""

    # No field aliases anywhere on this schema, deliberately. The MCP transport
    # serialises a tool result **by alias**, so an aliased field answers with a
    # different key at the machine door than at the human one — the same row in
    # two shapes, which is a door-parity disagreement a value-by-value test
    # never sees. `recipient_email` and `organization_slug` are properties on
    # `Message` instead (see the note there), so `from_attributes` finds them
    # under one name and both doors say the same thing.
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(json_schema_extra=example("0195f1d4-8a11-7b02-9c3d-1e2f3a4b5c6d"))
    recipient_id: UUID = Field(json_schema_extra=example("0195f1d4-6b33-7d24-9e35-3c4d5e6f7a8b"))
    recipient_email: str = Field(json_schema_extra=personal(example("dana@example.com")))
    # Which part of the tenant sent it. A client wearing the group's hat sees
    # rows from several branches at once and has no other way to tell them
    # apart — the slug as well as the id, because the slug is what `X-Org`
    # names.
    organization_id: UUID = Field(json_schema_extra=example("0195f1d4-7c00-7a13-8b24-2d3e4f5a6b7c"))
    organization_slug: str = Field(json_schema_extra=example("northern-branch"))
    template_name: str = Field(json_schema_extra=example("invoice-reminder"))
    template_version: int = Field(json_schema_extra=example(3))
    channel: str = Field(json_schema_extra=example("email"))
    category: str = Field(json_schema_extra=example("transactional"))
    status: str = Field(json_schema_extra=example("sent"))
    #: Empty unless `status` is `suppressed`, and never empty when it is — the
    #: database holds that as a check constraint, because "we refused and
    #: cannot say why" is the one unacceptable answer.
    suppressed_reason: str = Field(json_schema_extra=example(""))
    provider: str = Field(json_schema_extra=example("console"))
    provider_message_id: str = Field(
        json_schema_extra=example("0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f21")
    )
    subject: str = Field(json_schema_extra=example("Invoice INV-1042 is due on 1 September"))
    error: str = Field(json_schema_extra=example(""))
    #: The request that asked for this. The same id is on the `AuditEntry` and
    #: on every `comms.message.*` event for this message, so one value joins
    #: the door, the audit trail, the spine and the log.
    correlation_id: str = Field(json_schema_extra=example("0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f21"))
    created_at: datetime = Field(json_schema_extra=example("2026-09-01T09:14:00Z"))
    sent_at: datetime | None = Field(
        default=None, json_schema_extra=example("2026-09-01T09:14:02Z")
    )
    #: What the transport said afterwards. Both stay `None` on a message no
    #: provider has reported on — which is most of them, most of the time, and
    #: is a different answer from "it bounced". A client that wants "did it
    #: arrive" reads `status`; these two are when.
    delivered_at: datetime | None = Field(
        default=None, json_schema_extra=example("2026-09-01T09:14:09Z")
    )
    bounced_at: datetime | None = Field(default=None, json_schema_extra=example(None))
    #: When this message is due to go out, or `None` for one that went at once.
    #: **This is what makes a scheduled send visible**: before the
    #: column existed a support agent could not tell a message waiting six hours
    #: from one waiting six seconds, because both read `queued` and the schedule
    #: lived only on the Temporal run. Set for a message the quiet-hours wall
    #: deferred too — the same question with the same answer.
    send_at: datetime | None = Field(default=None, json_schema_extra=example(None))
    #: `hard` or `soft` when the transport reported a bounce, and `None`
    #: otherwise — including on a bounce recorded before ADR comms-9, and on one
    #: whose provider did not classify it. Published because "why is this
    #: address not suppressed when it bounced" is the first question the split
    #: creates, and a support agent who cannot answer it from the message log
    #: answers it from a shell.
    bounce_kind: str | None = Field(default=None, json_schema_extra=example(None))


class MessagePage(ListPage):
    """A page of messages — the list envelope, for a door with no query string.

    REST gets this shape from ninja's `@paginate` and never has to name it; the
    MCP tool returns a value rather than a response, so the same envelope has to
    be a schema it can declare. Deliberately the *same* envelope, so a machine
    client that has learned to unwrap the REST list does not learn a second one.
    """

    items: list[MessageOut]


class MessageEngagementOut(Schema):
    """One thing a provider says a person did with a message.

    The read shape of a `MessageEngagement` row, and the payload of
    `comms.message.opened` and `comms.message.clicked` — the same shape at both,
    for the reason `MessageOut` is: a webhook subscriber and a REST client
    reading the same fact should not be reading two shapes that drift.

    No field aliases, for `MessageOut`'s reason (see the note there): the MCP
    transport serialises by alias, so an aliased field answers with a different
    key at the machine door than at the human one.

    `organization_id` is on it because house rule 38 requires it of every `Out`
    of an `OrgScopedModel` — the socket fan-out narrows on that key and nothing
    else, so a shape that omitted it would emit an event no branch owns and the
    bridge would deliver it to every socket in the tenant. Here it is also the
    load-bearing one: the row's organization is the MESSAGE's branch and not the
    root the webhook acted at, which is `derive_org_from` doing its job all the
    way out to the wire.

    **`status` is deliberately not on this shape**, and its absence is the
    contract: an engagement says nothing about whether the message arrived, so a
    client that wants delivery truth reads `MessageOut`. Two shapes, because
    they are two facts (ADR comms-9).
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(json_schema_extra=example("0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f21"))
    message_id: UUID = Field(json_schema_extra=example("0195f1d4-8a11-7b02-9c3d-1e2f3a4b5c6d"))
    organization_id: UUID = Field(json_schema_extra=example("0195f1d4-7c00-7a13-8b24-2d3e4f5a6b7c"))
    kind: str = Field(json_schema_extra=example("opened"))
    #: Which link, on a click; empty on an open, which the database holds as a
    #: check constraint.
    url: str = Field(json_schema_extra=example(""))
    #: When the PROVIDER says it happened. `created_at` is when we heard, and
    #: the two differ by however long the webhook took.
    occurred_at: datetime = Field(json_schema_extra=example("2026-09-01T09:31:04Z"))
    provider_event_id: str = Field(json_schema_extra=example("msg_2abc3def4ghi5jkl6mno"))
    created_at: datetime = Field(json_schema_extra=example("2026-09-01T09:31:57Z"))


class MessageEngagementPage(ListPage):
    """A page of engagement rows on one message — the same envelope as every other.

    `MessagePage`'s reason, one table over: REST gets the shape from ninja's
    `@paginate` and the MCP tool has to name it, and a machine client that has
    learned to unwrap one list here must not learn a second.
    """

    items: list[MessageEngagementOut]


# --- the push address book -------------------------------------------------------


class DeviceIn(StrictIn):
    """A device to push to. **The organization is not on this shape** and never is.

    `RecipientIn`'s rule, and here it is not even a choice the door could make:
    a `Device` declares `derive_org_from = "recipient"`, so the row lands
    wherever the contact lives and the landing gate in `OrgScopedModel.clean()`
    refuses anything else.

    `push_token` is the platform's registration token, exactly as the client
    received it — an FCM registration id, an APNs device token, a web-push
    subscription. It is **not** validated into shape here for `Recipient.phone`'s
    reason: the format is the gateway's and it changes when the gateway does, so
    a validator here would refuse a real registration to enforce a guess. It is
    stored encrypted and never comes back out on any door.

    Re-sending an existing token is the **normal** case rather than an error —
    a mobile client re-registers on every launch — so this is one route that
    answers `200` with the row it found rather than `409`. See the route's own
    contract.
    """

    recipient_id: UUID = Field(json_schema_extra=example("0195f1d4-6b33-7d24-9e35-3c4d5e6f7a8b"))
    platform: str = Field(max_length=16, json_schema_extra=example("ios"))
    push_token: str = Field(
        min_length=1,
        max_length=4096,
        # **No ellipsis, and never again one.** This example used to end
        # in U+2026 — a truncation mark somebody wrote to mean "and so on". It
        # is a legal `str`, so it validated; the encrypted round trip then
        # encoded it as ASCII and the door answered **500**. A pasted example
        # that CRASHES the door tells a caller nothing at all, which is the
        # worst outcome an example can have — worse than a refusal, because a
        # refusal at least names a field.
        #
        # So this one is shorter than a real registration token and entirely
        # ASCII, and it says out loud that it is a placeholder instead of
        # trailing off into one.
        # `apps/core/tests/test_published_examples_at_the_door.py` pastes it at
        # the real door on every run.
        json_schema_extra=example("fzt9Q1u2S0aB3cD4eF5gH6-APA91bHnotarealtoken"),
    )
    label: str = Field(default="", max_length=100, json_schema_extra=example("Ada's iPhone"))


class DeviceOut(Schema):
    """One registered device, as every door reports it.

    **No token material, of any kind, in any field** — not the token, not a
    prefix, not a digest. That is the contract and not an omission: a push
    registration token is the capability to put a notification on somebody's
    lock screen, `Device.push_token` is encrypted at rest for that reason, and a
    read shape that handed a fragment back would undo the encryption for every
    caller who can list. This schema is also the payload of
    `comms.device.registered` and `comms.device.retired`, so it travels to
    every webhook endpoint a tenant has configured — which is the wire that
    makes the rule non-negotiable rather than tidy.

    A client that has just registered gets `id` back and addresses the device by
    it from then on. `push_token_hash` is the database's identity for the row
    and is deliberately not published either: it is a digest of a live
    credential, and publishing one lets a holder of the token confirm which
    tenant's contact it belongs to.

    No field aliases, for `MessageOut`'s reason: the MCP transport serialises by
    alias and an aliased field answers with a different key at the machine door.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(json_schema_extra=example("0195f1d4-5a44-7e35-8f46-4d5e6f7a8b9c"))
    recipient_id: UUID = Field(json_schema_extra=example("0195f1d4-6b33-7d24-9e35-3c4d5e6f7a8b"))
    #: House rule 38, and here it is the branch the CONTACT lives in rather than
    #: the hat that registered — `derive_org_from` doing its job out to the wire.
    organization_id: UUID = Field(json_schema_extra=example("0195f1d4-7c00-7a13-8b24-2d3e4f5a6b7c"))
    platform: str = Field(json_schema_extra=example("ios"))
    label: str = Field(json_schema_extra=example("Ada's iPhone"))
    #: Set when this install stopped being reachable, `None` while it is. A
    #: timestamp rather than a boolean because "when did we stop being able to
    #: reach this handset" is the question a support agent actually has, and a
    #: flag answers a narrower one.
    retired_at: datetime | None = Field(default=None, json_schema_extra=example(None))
    created_at: datetime = Field(json_schema_extra=example("2026-08-30T14:02:11Z"))
    updated_at: datetime = Field(json_schema_extra=example("2026-09-01T08:15:40Z"))


# NO `DevicePage`, and the absence is a decision recorded rather than
# an oversight. The route list is `POST /devices/` and
# `POST /devices/{id}/retire/` — a registration door and a retirement door,
# both addressed by the id the first one hands back — and there is no list
# route, so `devices:read` derives into the vocabulary and reaches nothing. That
# is exactly the shape `usage:write` already has (`apps/core/api/scopes.py`
# records it), and it is written down here rather than left to be discovered:
# the day a read door lands it brings this envelope with it, in the same commit
# as the route that returns it. A `Page` schema with no door to return it is a
# reader built ahead of its writer, which is rule 30's defect pointed the other
# way.


# --- the management shapes: templates, recipients, preferences ------------------


# `StrictIn` was BORN here, as a `model_validator(mode="before")` that walked
# the raw body and raised `Invalid` for any key `model_fields` did not hold. It
# was right about the danger and it was in the wrong PLACE: one app's management
# door was strict while every other door in the product shrugged, and it said
# `invalid` where a door-decided refusal now says `invalid_body`. The owner's
# ruling of 2026-08-24 made strictness the platform's, at one seam — the class
# kept its name and moved to `apps.core.schemas`, where it is one line of
# `model_config` instead of a validator, and where every request body in the
# tree inherits it. `MessageIn`, which used to be exempted here as a shipped
# contract, joined with the rest: the ruling is the pre-production free window
# being spent, deliberately, on all of it at once.


class TemplateIn(StrictIn):
    """Version 1 of a template. **`version` is not on this shape.**

    It never will be: a version is what the service counts, and a caller that
    could name one could overwrite the words a message was already sent with.
    """

    name: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1)
    subject: str = Field(default="", max_length=255)
    channel: str = Field(default=Channel.EMAIL.value, min_length=1, max_length=16)
    category: str = Field(default=Category.TRANSACTIONAL.value, min_length=1, max_length=16)
    context_schema: dict[str, Any] = Field(default_factory=dict)


class TemplateRevisionIn(StrictIn):
    """The next version of a template — the words, and nothing structural.

    No `name` (it is in the path), no `version` (the service counts), no
    `channel`: a template's channel is part of what it is, and one that changed
    at v2 would silently re-target every `send()` that names it.
    """

    body: str = Field(min_length=1)
    subject: str = Field(default="", max_length=255)
    category: str | None = Field(default=None, max_length=16)
    context_schema: dict[str, Any] | None = None


class TemplateFilter(FilterSchema):
    """The narrowings a client may ask for over the template versions."""

    name: Annotated[str | None, FilterLookup(q="name")] = None
    channel: Annotated[str | None, FilterLookup(q="channel")] = None
    category: Annotated[str | None, FilterLookup(q="category")] = None


class TemplateOut(Schema):
    """One template version, as every door reports it.

    The body is here, unlike on `MessageOut`: a template is the tenant's own
    words about to go out, which whoever manages them has to be able to read
    back, where a message's body is a rendered copy of the customer's data.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    version: int
    channel: str
    category: str
    subject: str
    body: str
    context_schema: dict[str, Any]
    is_active: bool
    created_at: datetime


class TemplatePage(ListPage):
    """A page of template versions — the same envelope `@paginate` produces."""

    items: list[TemplateOut]


# --- delivery policies: escalation as data ---------------------------------------


class PolicyStepIn(StrictIn):
    """One rung a caller asks for. **The service still decides it is legal.**

    Pydantic checks the *shape* — the four fields, the types, a non-negative
    wait — and `services._policy_steps` checks the *meaning*: that the channel
    is a kind this product knows, that the template exists and is on that
    channel, and that `escalate_when` is one of the closed two. Both, and not
    one: the schema refusal is what makes a typo a 400 with the field named, and
    the service refusal is what makes a policy written by a management command
    or a test just as safe as one written through the door.
    """

    channel: str = Field(min_length=1, max_length=16)
    template: str = Field(min_length=1, max_length=100)
    wait_seconds: int = Field(default=0, ge=0)
    escalate_when: str = Field(default="none", min_length=1, max_length=16)


class PolicyStepOut(Schema):
    """One rung, as every door reports it. The same four fields, read back."""

    model_config = ConfigDict(from_attributes=True)

    channel: str
    template: str
    wait_seconds: int
    escalate_when: str


class PolicyIn(StrictIn):
    """Version 1 of a policy. **`version` is not on this shape**, like a template's."""

    name: str = Field(min_length=1, max_length=100)
    steps: list[PolicyStepIn] = Field(min_length=1)


class PolicyRevisionIn(StrictIn):
    """The next version of a policy — the steps, and nothing else.

    No `name` (it is in the path) and no `version` (the service counts), for the
    same reasons `TemplateRevisionIn` has neither.
    """

    steps: list[PolicyStepIn] = Field(min_length=1)


class PolicyFilter(FilterSchema):
    """The narrowings a client may ask for over the policy versions."""

    name: Annotated[str | None, FilterLookup(q="name")] = None


class PolicyOut(Schema):
    """One policy version, as every door reports it.

    The steps are here in full, for the same reason a template's body is: a
    policy *is* its steps, and a management surface that made you fetch them
    separately would be a surface nobody could review.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    version: int
    is_active: bool
    steps: list[PolicyStepOut]
    created_at: datetime


class PolicyPage(ListPage):
    """A page of policy versions — the same envelope `@paginate` produces."""

    items: list[PolicyOut]


class RecipientIn(StrictIn):
    """A new contact. The **organization is not on this shape** and never is.

    Where a contact lands is decided by the acting hat the door resolved, not by
    the caller: an `organization` field here would let a client write a row into
    a branch it holds no membership over.
    """

    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(default="", max_length=200)
    #: The other two ways to reach this person. Optional and unvalidated in
    #: shape — a phone number is E.164 in one product and seven digits in
    #: another, and the transport that dials it is what knows.
    phone: str = Field(default="", max_length=32)
    chat_handle: str = Field(default="", max_length=255)


class RecipientPatch(StrictIn):
    """A partial correction: absent means "leave it alone", not "set it to null".

    Four fields, and the absences are still the design. `archived_at` is not
    here — closing a contact is `POST .../archive/` and reopening it
    `POST .../restore/`, verbs, so the audit row says what happened rather than
    which column moved — and neither is anything
    on the person's preferences, which is the consent surface and is only
    reachable through its own five verbs.

    `phone` and `chat_handle` are here because they are **addresses, not
    consent**: knowing somebody's number is not permission to text them, and an
    escalation that reaches for SMS still meets the whole wall at that step's
    own send time.
    """

    email: str | None = Field(default=None, min_length=3, max_length=254)
    display_name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=32)
    chat_handle: str | None = Field(default=None, max_length=255)


class RecipientFilter(FilterSchema):
    """The narrowings a client may ask for over the contact book."""

    email: Annotated[str | None, FilterLookup(q="email__icontains")] = None


class RecipientOut(ArchivedOut, ActsOut):
    """One contact, as every door reports it — and as `comms.recipient.archived`
    and `comms.recipient.restored` carry it, less its `allowed_acts`.

    `archived_at` and `archived_by` are inherited from `ArchivedOut`, never
    re-declared: null unless the contact has been closed, and on the read shape
    because "why is this person not in my list any more, and who closed them"
    is the question they answer.

    `allowed_acts` is inherited from `ActsOut`: the verbs THIS viewer may press
    on this contact as it stands, set by `core.verbs.with_allowed_acts` on the
    two viewer doors (a list page through `ActsPagination`, every other answer
    for its one row). It describes the viewer, not the contact, so an event
    payload never carries it — a subscriber is somebody else.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str = Field(json_schema_extra=personal())
    display_name: str = Field(json_schema_extra=personal())
    #: Set when this contact also has an account; null for the contacts, leads
    #: and customers who never signed in — which is most of them.
    user_id: UUID | None = None
    organization_id: UUID
    created_at: datetime
    phone: str = Field(json_schema_extra=personal())
    chat_handle: str = Field(json_schema_extra=personal())


class RecipientPage(ActsPage):
    """A page of contacts — the same envelope `@paginate(ActsPagination)` produces,
    the list's own `allowed_acts` included."""

    items: list[RecipientOut]


class PreferenceIn(StrictIn):
    """Which channel a consent verb is about. The verb is the route, not a field.

    There is no `suppressed_at`, no `marketing_consented_at` and no
    `marketing_revoked_at` here — a column a door can set is a column a door can
    set *back*, and a consent timestamp somebody typed is not a consent record.
    """

    channel: str = Field(default=Channel.EMAIL.value, min_length=1, max_length=16)


class QuietHoursIn(StrictIn):
    """The window, in the person's own timezone. Both ends, or neither.

    Neither is how quiet hours are turned off; one is a window nobody can
    evaluate, and the service refuses it with the field named.
    """

    channel: str = Field(default=Channel.EMAIL.value, min_length=1, max_length=16)
    start: time | None = None
    end: time | None = None
    timezone_name: str = Field(default="UTC", min_length=1, max_length=64)


class PreferenceOut(Schema):
    """What one person has agreed to on one channel, as every door reports it.

    `has_marketing_consent` is a property on the model rather than a field here,
    so the "yes and not since revoked" comparison is made in one place and both
    timestamps stay on the shape beside it — a client that has to prove consent
    to a regulator needs the dates, and one that has to decide whether to show a
    checkbox needs the answer.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    recipient_id: UUID
    #: Which part of the tenant this preference belongs to — inherited from the
    #: recipient (`ChannelPreference.derive_org_from`), never chosen here. It is
    #: on the read shape because it is the key the socket fan-out narrows on:
    #: `events.services._subject_organization` reads the subject's `Out` schema
    #: and nothing else, so an org-scoped shape that omits it emits an event no
    #: branch owns, and `realtime.bridge.group_for` reads that as tenant-wide.
    #: House rule 38 holds this for every `Out` of an `OrgScopedModel`.
    organization_id: UUID
    channel: str
    has_marketing_consent: bool
    marketing_consented_at: datetime | None = None
    marketing_revoked_at: datetime | None = None
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None
    quiet_hours_timezone: str
    #: Set means nothing at all goes to this address on this channel,
    #: transactional included. It is only ever moved by `suppress_recipient` /
    #: `unsuppress_recipient` — there is no shape a door could send that sets it.
    suppressed_at: datetime | None = None
    created_at: datetime


class PreferencePage(ListPage):
    """A page of preferences — the same envelope `@paginate` produces."""

    items: list[PreferenceOut]
