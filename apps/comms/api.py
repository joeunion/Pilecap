"""The comms doors: send, the log, what may be said — each door calls the service (ADR comms-1)."""

# No `from __future__ import annotations`: ninja resolves route signatures at import.

from uuid import UUID

from django.db.models import QuerySet
from ninja import Query, Router, Status
from ninja.pagination import paginate

from apps.accounts.auth import API_AUTH
from apps.comms.models import (
    ChannelPreference,
    DeliveryPolicy,
    Device,
    Message,
    MessageEngagement,
    MessageTemplate,
    Recipient,
)
from apps.comms.schemas import (
    DeviceIn,
    DeviceOut,
    MessageEngagementOut,
    MessageFilter,
    MessageIn,
    MessageOut,
    PolicyFilter,
    PolicyIn,
    PolicyOut,
    PolicyRevisionIn,
    PreferenceIn,
    PreferenceOut,
    QuietHoursIn,
    RecipientFilter,
    RecipientIn,
    RecipientOut,
    RecipientPatch,
    TemplateFilter,
    TemplateIn,
    TemplateOut,
    TemplateRevisionIn,
)
from apps.comms.selectors import (
    get_device,
    get_message,
    get_policy,
    get_recipient,
    get_template,
    list_engagements,
    list_messages,
    list_policies,
    list_preferences,
    list_recipients,
    list_templates,
)
from apps.comms.services import (
    archive_recipient,
    cancel_message,
    create_policy,
    create_recipient,
    create_template,
    grant_consent,
    register_device,
    restore_recipient,
    retire_device,
    retire_policy,
    retire_template,
    revise_policy,
    revise_template,
    revoke_consent,
    send,
    set_quiet_hours,
    suppress_recipient,
    unsuppress_recipient,
    update_recipient,
)
from apps.core.api import CursorPagination, ordered_by
from apps.core.api.acting import acting
from apps.core.api.docs import Tag, also_refuses, refuses
from apps.core.api.pagination import ActsPagination
from apps.core.api.query import ARCHIVED_SWITCH, RetiredQuery, refuse_retired_query
from apps.core.requests import TenantRequest
from apps.core.schemas import Show
from apps.core.verbs import with_allowed_acts

# The first path segment names a resource, never the app (ADR api-2, rule 32).
PREFIX = ""

# What `?ordering=` may name, and nothing else.
ORDERING = ("created_at", "updated_at", "sent_at", "status")
TEMPLATE_ORDERING = ("name", "version", "created_at", "updated_at")
RECIPIENT_ORDERING = ("email", "display_name", "created_at", "updated_at")
POLICY_ORDERING = ("name", "version", "created_at", "updated_at")
# The provider's moment and ours; nothing else on an engagement is an order.
ENGAGEMENT_ORDERING = ("occurred_at", "created_at")

# The tags this app's routes carry, described where they are owned (ADR api-1, rule 41).
TAGS = {
    "messaging": Tag(
        "Messaging & contacts",
        "Sending, and everything that decides whether a send is allowed to happen: "
        "the message log, versioned templates and delivery policies, the contact "
        "book, and per-person consent, quiet hours and suppression. Consent, quiet "
        "hours and suppression are applied to every message this API sends, so a "
        "send to somebody who has opted out is refused rather than delivered.",
        plane="everyday",
        plane_note=(
            "sending a message to somebody, and the contact book that records who may be "
            "contacted and how."
        ),
    ),
    # Its own family: keeping the push address book is not the trust of contacting a person.
    "devices": Tag(
        "Devices",
        "The push address book: the handsets and browsers a contact has let this "
        "product notify. Registering a device says the product CAN reach it and "
        "never that it MAY — consent, quiet hours and suppression for the `push` "
        "channel live with the other consent verbs under Messaging & contacts, and "
        "every notification is checked against them. Registration tokens are stored "
        "encrypted and are never published on any door or in any event.",
        plane="everyday",
        plane_note=(
            "the push address book: the handsets and browsers a contact has let this product "
            "notify. Its own section rather than a corner of `messaging`, because the two are "
            "not the same trust — a client trusted to register the phone it is running on is not "
            "thereby trusted to mail everybody in the contact book, and a mobile app's token can "
            "hold this section's write half and nothing else. Registering says the product "
            "**can** reach a "
            "handset and never that it **may**: consent, quiet hours and suppression for the "
            "`push` channel live with the other consent verbs under `messaging`, and every "
            "notification is checked against them. Write-only in practice — a registration door "
            "and a retirement door, both addressed by the id the first hands back — so this "
            "section's read half reaches nothing, exactly as Usage's write half does."
        ),
    ),
}

# `?archived=` is the retired spelling of `?show=`, refused rather than ignored.
RETIRED_QUERY: dict[str, RetiredQuery] = {"archived": ARCHIVED_SWITCH}

# `auth` restated so this file says what calling these routes takes.
router = Router(tags=["messaging"], auth=API_AUTH)


@router.get("/messages/", response=list[MessageOut], url_name="message-list")
@paginate(CursorPagination)
def list_messages_route(
    request: TenantRequest,
    filters: Query[MessageFilter],
    ordering: str = "-created_at",
) -> QuerySet[Message]:
    """List messages

    List messages your acting organization has sent, newest first.

    Narrow with `status`, `channel` or `template` (each an exact match; the
    template one matches the template's name). Sort with `ordering`, which
    accepts `created_at`, `updated_at`, `sent_at` or `status`, each optionally
    prefixed with `-`; the default is `-created_at` and any other value is
    refused with `400 invalid`. Paged with `?cursor=` and `?limit=` (50 by
    default, 200 at most); the body is
    `{"items": [...], "has_more": ..., "next_cursor": ...}` — follow
    `next_cursor` while `has_more` is true. `count` is `null` unless you ask
    with `?include_count=true`.

    **Messages that were never sent are in this list too.** A message the
    product refused to deliver — because consent was withdrawn, quiet hours were
    in force, or the address was suppressed — is here with
    `status: "suppressed"` and a `suppressed_reason`. That is the point of the
    list: "why did they not get the email" is answered here, and would not be if
    the refusals were hidden.

    Which messages you see depends on the organization you are acting as (the
    `X-Org` header) — its own and those of organizations beneath it.

    Refusals you can get here:

    * `400 invalid` — `?ordering=` named a field this list does not accept, or
      a filter value was malformed. The response says what you may sort by.
    * `403 forbidden` — your membership here does not allow you to read this.
    * `403 no_acting_scope` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    messages: QuerySet[Message] = list_messages(tenant=tenant, org=actor.org, actor=actor)
    messages = filters.filter(messages)
    return ordered_by(messages, ordering, allowed=ORDERING, default="-created_at")


@router.post("/messages/", response={201: MessageOut}, url_name="message-send")
def send_message_route(request: TenantRequest, payload: MessageIn) -> Status[Message]:
    """Send a message

    Send one message to one contact.

    Send `recipient_id`, then **one** of two things:

    * a `template` name, optionally with `channel` (defaults to `email`) — one
      message, once; or
    * a `policy` name — an escalation the product runs for you, whose own first
      step already decides the template and the channel.

    Sending `template` or `channel` **alongside** `policy` is refused with
    `400 invalid` naming the offending field, rather than resolved one way.

    `template` is a name, not an id: ask for `"invoice-reminder"` and the latest
    live version of it is used. There is no way to pin an older one.

    `context` is the object of variables the template fills in. It is checked
    against that template's declared shape first, so a missing or wrong-typed
    variable is a `400 invalid` naming the field and **nothing is sent**.

    **`send_at` schedules it.** Give a timezone-aware moment and the answer is
    `201` with `status: "queued"` immediately, while the message itself waits.
    Three things are worth knowing before you rely on it:

    * consent is checked **twice** — now, and again the moment it goes out. A
      send scheduled for next week to somebody who unsubscribes on Tuesday does
      not go. Scheduling is not a way to bank permission;
    * a moment **already past** sends now. It is not an error, because your
      clock and ours disagreeing by a second must not be one;
    * a moment with **no timezone** is refused with `400 invalid`. There is no
      default zone and there will not be one: a scheduled send is a promise
      about an instant, and guessing whose midnight you meant is the one
      mistake that cannot be recovered from afterwards.

    There is no way to cancel or re-schedule one yet, and no list of what is
    pending — a scheduled message reads as `queued` like any other. Both are
    named gaps rather than oversights.

    **`201` does not mean the message went out.** Read `status` on the answer:

    * `queued` — accepted, and delivery has started. Poll
      `GET /api/v1/messages/{message_id}/` for where it got to.
    * `suppressed` — nothing was sent. `suppressed_reason` says why:
      `suppressed` (this address is blocked on this channel and even
      transactional mail stops), `no_consent` (this is a marketing message and
      nobody has agreed to it on this channel), or `quiet_hours` (a marketing
      message inside the person's quiet window — it is dropped, not delayed).
      The consent routes under `/recipients/{recipient_id}/` are where each of
      those is changed. If you sent a `policy` with more than one step, its
      later steps still run; each is consent-checked again at its own send time.

    Both are `201`, because both are the product working correctly. A client
    that treats any 2xx as "delivered" will be wrong; read the row.

    Refusals you can get here:

    * `400 invalid` — you sent `template` or `channel` alongside `policy`,
      sent neither, named a template or policy that has no live version, the
      `context` did not match the template's declared variables, or `send_at`
      carried no timezone. `errors` names the field and nothing is sent.
    * `403 forbidden` — your membership here does not allow this.
    * `403 no_acting_scope` — the request resolved no tenant or no acting
      organization.
    * `404 not_found` — no contact your acting organization can address has
      that id. A contact in a branch you hold no membership over answers
      this too.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    recipient = get_recipient(
        tenant=tenant, recipient_id=payload.recipient_id, org=actor.org, actor=actor
    )
    message = send(
        recipient=recipient,
        template=payload.template,
        context=payload.context,
        channel=payload.channel,
        policy=payload.policy,
        send_at=payload.send_at,
        tenant=tenant,
        actor=actor,
    )
    return Status(201, message)


@router.get("/messages/{message_id}/", response=MessageOut, url_name="message-detail")
def retrieve_message(request: TenantRequest, message_id: UUID) -> Message:
    """Retrieve a message

    Fetch one message by id, and where its delivery has got to.

    This is how you follow a `queued` message: `status` moves on after the send
    returned, so poll here rather than trusting the answer you got at send time.
    `sent_at`, `delivered_at` and `bounced_at` are filled in as each happens, and
    `error` and `bounce_kind` say what went wrong when something did.

    The row is a record of what was **attempted**. Even `delivered` is the
    provider's word for it, not proof anybody read it.

    A message your acting organization cannot see, or an id that names nothing,
    answers `404 not_found`.

    Refusals you can get here:

    * `404 not_found` — no message your acting organization can see has that
      id.
    * `403 forbidden` — your membership here does not allow you to read this.
    * `403 no_acting_scope` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    return get_message(tenant=tenant, message_id=message_id, org=actor.org, actor=actor)


@router.get(
    "/messages/{message_id}/engagement/",
    response=list[MessageEngagementOut],
    # `engagement-list`: rule 17 derives the tool name from the last hyphen.
    url_name="engagement-list",
)
@also_refuses("invalid")
@paginate(CursorPagination)
def list_message_engagement_route(
    request: TenantRequest,
    message_id: UUID,
    ordering: str = "-occurred_at",
) -> QuerySet[MessageEngagement]:
    """List what a message's reader did

    List the opens and clicks a provider has reported for one message.

    **These are a provider's inferences, not facts about delivery.** An open is
    recorded when something requested the tracking image in the message, and on
    Apple Mail Privacy Protection that request is made for every message a
    person receives whether they look at it or not — so a message can show opens
    nobody made. A click is stronger, because a person's own action caused it.
    Neither says the message arrived: `GET /api/v1/messages/{message_id}/` is
    where delivery lives, and nothing on this list moves it.

    Newest first by when the *provider* says it happened, which is not when we
    heard: `occurred_at` is the provider's moment and `created_at` is ours, and
    a webhook that arrived an hour late does not sort as an hour-late open. Sort
    with `ordering`, which accepts `occurred_at` or `created_at`, each
    optionally prefixed with `-`. Paged with `?cursor=` and `?limit=`; `count`
    is `null` unless you ask with `?include_count=true`.

    `kind` is `opened` or `clicked` and there is no third value. A spam
    complaint is deliberately not here: it is news about consent, it suppresses
    the address, and it arrives as the `comms.message.complained` event. `url`
    is the link on a click and is empty on an open.

    **There is no way to add a row through this API, on purpose.** An engagement
    is something a transport told us about a person, and a door that accepted
    one would let a client mint "opened" facts about somebody else into a record
    whose whole value is that it was witnessed. The only writer is the
    signature-verified provider webhook.

    Refusals you can get here:

    * `400 invalid` — `?ordering=` named a field this list does not accept.
    * `403 forbidden` — your membership here does not allow you to read this.
    * `403 no_acting_scope` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `404 not_found` — no message your acting organization can see has that
      id, or `?cursor=` did not come from this list.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    message = get_message(tenant=tenant, message_id=message_id, org=actor.org, actor=actor)
    rows: QuerySet[MessageEngagement] = list_engagements(
        tenant=tenant, message=message, org=actor.org, actor=actor
    )
    return ordered_by(rows, ordering, allowed=ENGAGEMENT_ORDERING, default="-occurred_at")


@router.post("/messages/{message_id}/cancel/", response=MessageOut, url_name="message-cancel")
def cancel_message_route(request: TenantRequest, message_id: UUID) -> Message:
    """Cancel a message

    Take a message back out of the queue, before anything has been sent.

    Send no body. Use it for a scheduled send you have changed your mind about —
    `send_at` on the message tells you whether there is still time.

    **Only a message that is still `queued` can be cancelled**, and that is the
    whole safety of it. Once `status` reaches `sending` a transport has it in
    hand at that moment, and anything past that has already happened to
    somebody. Those all answer `409 conflict` naming the status, rather than
    quietly doing nothing — a caller who believes a sent message was stopped is
    worse off than one who is told.

    The answer is the message with `status: "cancelled"`. That is its own
    status and not a suppression: `suppressed` is this product refusing on the
    **recipient's** behalf — they opted out, they were suppressed, it was their
    quiet hours — and counting a sender's change of mind among those would put
    an opt-out in your reports that nobody made.

    **Cancelling twice is a `409`, not a shrug.** The first one settled it;
    the second is a caller who believes something that is not true.

    Refusals you can get here:

    * `403 forbidden` — your membership here does not allow this.
    * `403 no_acting_scope` — the request resolved no tenant or no acting
      organization.
    * `404 not_found` — no message your acting organization can see has that
      id. A message in a branch you hold no membership over answers this too.
    * `409 conflict` — that message is past the point of being cancelled. The
      detail names the status it is in.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    message = get_message(tenant=tenant, message_id=message_id, org=actor.org, actor=actor)
    return cancel_message(tenant=tenant, actor=actor, message=message)


# --- templates: written once, revised, never edited; addressed by name -------------


@router.get("/templates/", response=list[TemplateOut], url_name="template-list")
@paginate(CursorPagination)
def list_templates_route(
    request: TenantRequest,
    filters: Query[TemplateFilter],
    ordering: str = "name",
) -> QuerySet[MessageTemplate]:
    """List message templates

    List message templates — **every version, including retired ones.**

    A template name has many versions and this returns all of them, so expect
    several rows sharing one `name` with different `version` numbers. `is_active`
    marks the one a send under that name would use right now. Retired versions
    stay in the list because a message sent in March records the version it went
    out with, and you need to be able to read those exact words back.

    Narrow with `name`, `channel` or `category` (each exact). Sort with
    `ordering`, which accepts `name`, `version`, `created_at` or `updated_at`,
    each optionally prefixed with `-`; the default is `name` and any other value
    is refused with `400 invalid`. Paged with `?cursor=` and `?limit=`; the
    body is `{"items": [...], "has_more": ..., "next_cursor": ...}`, and
    `count` arrives only with `?include_count=true`.

    Templates belong to the whole tenant, not to one organization within it.

    Refusals you can get here:

    * `400 invalid` — `?ordering=` named a field this list does not accept, or
      a filter value was malformed. The response says what you may sort by.
    * `403 forbidden` — your membership here does not allow you to read this.
    * `403 no_acting_scope` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    templates: QuerySet[MessageTemplate] = list_templates(tenant=tenant, actor=actor)
    templates = filters.filter(templates)
    return ordered_by(templates, ordering, allowed=TEMPLATE_ORDERING, default="name")


@router.post("/templates/", response={201: TemplateOut}, url_name="template-create")
def create_template_route(request: TenantRequest, payload: TemplateIn) -> Status[MessageTemplate]:
    """Create a message template

    Create a new template at version 1.

    Send `name` (how you will refer to it when sending) and `body` (the text,
    with `{{ variable }}` placeholders). Optionally `subject`, `channel`
    (defaults to `email`), `category` (`transactional` or `marketing` — this is
    what decides whether consent and quiet hours can stop a send), and
    `context_schema`, an object declaring the variables the body expects so that
    a send with the wrong ones is refused rather than delivered half-filled.

    A `name` this tenant already has answers `409 conflict`. Use
    `POST /api/v1/templates/{name}/versions/` to change one instead.

    Fields not on this shape are rejected with `400 invalid` naming them, rather
    than accepted and ignored.

    Owner or administrator of the tenant only. Answers `201` with the new template.

    Refusals you can get here:

    * `400 invalid` — a field is missing or malformed, or `channel` or
      `category` is not one this product knows. `errors` names the fields
      and nothing is created.
    * `403 forbidden` — you are not an owner or an administrator of the
      tenant.
    * `403 no_acting_scope` — the request resolved no tenant or no acting
      organization.
    * `409 conflict` — a template already exists under that name. Publish a
      new version of it instead.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    template = create_template(
        tenant=tenant,
        actor=actor,
        name=payload.name,
        body=payload.body,
        subject=payload.subject,
        channel=payload.channel,
        category=payload.category,
        context_schema=payload.context_schema,
    )
    return Status(201, template)


@router.post("/templates/{name}/versions/", response={201: TemplateOut}, url_name="template-revise")
def revise_template_route(
    request: TenantRequest, name: str, payload: TemplateRevisionIn
) -> Status[MessageTemplate]:
    """Publish a new template version

    Publish the next version of a template.

    Put the template's `name` in the path and the new `body` in the body, plus
    optionally `subject`, `category` and `context_schema`.

    `category` and `context_schema` carry over from the current version when you
    omit them. **`subject` does not** — omit it and the new version has an empty
    subject, so send it every time even when it is unchanged.

    **This does not edit anything.** You get `201` and a *new* template — a new
    `id`, at `version + 1` — and every earlier version stays exactly as it was.
    That is deliberate: messages already sent record the version they went out
    with, and rewriting one would change the record of what somebody was told.
    There is no route anywhere in this API that edits a template.

    **The channel cannot change across versions** and there is no field here to
    change it: an email template stays an email template for ever, because
    moving it would silently re-target every send that names it. Sending on
    another channel means a new template with a new name.

    New sends under this name start using the new version immediately. An
    escalation already running keeps the version it started with.

    A `name` this tenant does not have answers `404 not_found`. Requires an
    owner or admin role.

    Refusals you can get here:

    * `400 invalid` — a field is missing or malformed. `errors` names the
      fields and no version is published.
    * `403 forbidden` — you are not an owner or an administrator of the
      tenant.
    * `403 no_acting_scope` — the request resolved no tenant or no acting
      organization.
    * `404 not_found` — no template of this tenant's has that name.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    template = revise_template(
        tenant=tenant,
        actor=actor,
        name=name,
        body=payload.body,
        subject=payload.subject,
        category=payload.category,
        context_schema=payload.context_schema,
    )
    return Status(201, template)


@router.post("/templates/{name}/retire/", response=TemplateOut, url_name="template-retire")
def retire_template_route(request: TenantRequest, name: str) -> MessageTemplate:
    """Retire a template

    Retire the live version of a template, by name.

    Takes no body. Put the template's `name` in the path — the same name you
    revise with and the same name you send with. It retires whichever version is
    currently live under that name: `is_active` becomes false and sends stop
    choosing it, but the name keeps working and now resolves to the highest
    version still active, so retiring v3 puts v2 back into service. Retiring the
    only version leaves the name with nothing to resolve to, and a send naming
    it fails.

    Nothing is deleted. Every retired version stays readable through
    `GET /api/v1/templates/?name=<name>`, and every message that used one still
    records the name and version it went out with.

    **Safe to retry** under an `Idempotency-Key`: the replay answers with the
    first call's result rather than retiring a second version. Without a key,
    a second call is a second retirement — it takes out whatever is live now.

    A `name` this tenant does not have, or one whose every version is already
    retired, answers `404 not_found`. Owner or administrator of the tenant only.
    Answers `200` with the template.

    Refusals you can get here:

    * `403 forbidden` — you are not an owner or an administrator of the
      tenant.
    * `403 no_acting_scope` — the request resolved no tenant or no acting
      organization.
    * `404 not_found` — no template of this tenant's has that name, or it has
      no live version to retire.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    A POST on a sub-path rather than a PATCH that sets `is_active`, for the same
    reason consent is five verbs: a flag a door can set is a flag a door can set
    back, and this one decides what every future `send()` under the name will
    use. `is_active` is the only column on a template that moves after it is
    written, and this verb is the only thing that moves it.
    """
    actor, tenant = acting(request)
    template = get_template(tenant=tenant, name=name, actor=actor)
    return retire_template(tenant=tenant, actor=actor, template=template)


@router.get("/templates/{name}/", response=TemplateOut, url_name="template-detail")
def retrieve_template(request: TenantRequest, name: str) -> MessageTemplate:
    """Retrieve the live template

    The version a send under this name would use right now.

    By name, not by id, because that is the question worth asking before you
    send: a name has many versions and this answers with the live one, `body`
    and `subject` and all.

    To see the others — including the retired ones — list
    `/api/v1/templates/?name=<name>` and pick the `version` you want. That is
    how you read back the exact words a message went out with: a message records
    `template_name` and `template_version`, never an id.

    A name this tenant does not have, or one whose every version is retired,
    answers `404 not_found`.

    Refusals you can get here:

    * `404 not_found` — no template of this tenant's has that name, or none of
      its versions is live.
    * `403 forbidden` — your membership here does not allow you to read this.
    * `403 no_acting_scope` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    return get_template(tenant=tenant, name=name, actor=actor)


# --- delivery policies: how hard to try, as data -------------------------------


def ordered_policies(rows: QuerySet[DeliveryPolicy], ordering: str) -> QuerySet[DeliveryPolicy]:
    """`ordering` over policies, newest version first within a name — both doors' list order."""
    ordered = ordered_by(rows, ordering, allowed=POLICY_ORDERING, default="name")
    return ordered.order_by(*ordered.query.order_by, "-version")


@router.get("/delivery-policies/", response=list[PolicyOut], url_name="policies-list")
@paginate(CursorPagination)
def list_policies_route(
    request: TenantRequest,
    filters: Query[PolicyFilter],
    ordering: str = "name",
) -> QuerySet[DeliveryPolicy]:
    """List delivery policies

    List delivery policies — **every version, including retired ones.**

    A delivery policy is an escalation plan: an ordered list of `steps` the
    product works through when you name the policy on a send instead of a
    template. Each step says which `channel` to try, which `template` to use,
    how many `wait_seconds` to wait for the provider to report back, and
    `escalate_when` — `"delivered"` to try the next step if this one was not
    delivered, `"none"` to stop here. A step that is delivered always ends the
    chain, whatever the plan said next.

    Like templates, a policy name has many versions and all of them are here, so
    expect several rows sharing one `name`. `is_active` marks the one a send
    under that name would run now. Retired versions stay because a message
    records the policy name and version it ran under, and reading back what an
    escalation actually did in March needs the steps as they were then.

    Narrow with `name` (exact). Sort with `ordering`, which accepts `name`,
    `version`, `created_at` or `updated_at`, each optionally prefixed with `-`;
    the default is `name`, with the newest version of each name first, and any
    other value is refused with `400 invalid`. Paged with `?cursor=` and
    `?limit=`; the body is `{"items": [...], "has_more": ..., "next_cursor": ...}`,
    and `count` arrives only with `?include_count=true`.

    Policies belong to the whole tenant, not to one organization within it.

    Refusals you can get here:

    * `400 invalid` — `?ordering=` named a field this list does not accept, or
      a filter value was malformed. The response says what you may sort by.
    * `403 forbidden` — your membership here does not allow you to read this.
    * `403 no_acting_scope` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    policies: QuerySet[DeliveryPolicy] = list_policies(tenant=tenant, actor=actor)
    policies = filters.filter(policies)
    return ordered_policies(policies, ordering)


@router.post("/delivery-policies/", response={201: PolicyOut}, url_name="policy-create")
def create_policy_route(request: TenantRequest, payload: PolicyIn) -> Status[DeliveryPolicy]:
    """Create a delivery policy

    Create a new delivery policy at version 1.

    Send `name` and `steps` — at least one, in the order they should be tried.
    Each step needs `channel` and `template`, and takes `wait_seconds` (default
    0, meaning move on without waiting for a provider status) and
    `escalate_when`, which is `"delivered"` (try the next step if this one was
    not delivered) or `"none"` (stop here, the default).

    Each step's `template` must already exist **and be on that step's channel**;
    a mismatch is `400 invalid` with the offending step and field named, and
    nothing is created. So is an `escalate_when` that is neither of the two
    values, and so is any field not on this shape.

    A `name` this tenant already has answers `409 conflict`. Use
    `POST /api/v1/delivery-policies/{name}/versions/` to change one instead.

    Owner or administrator of the tenant only. Answers `201` with the new policy.

    Refusals you can get here:

    * `400 invalid` — a field is missing or malformed, or a step names a
      template or channel this product does not know. `errors` names the
      fields and nothing is created.
    * `403 forbidden` — you are not an owner or an administrator of the
      tenant.
    * `403 no_acting_scope` — the request resolved no tenant or no acting
      organization.
    * `409 conflict` — a policy already exists under that name. Publish a new
      version of it instead.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    policy = create_policy(
        tenant=tenant,
        actor=actor,
        name=payload.name,
        steps=[step.model_dump() for step in payload.steps],
    )
    return Status(201, policy)


@router.post(
    "/delivery-policies/{name}/versions/", response={201: PolicyOut}, url_name="policy-revise"
)
def revise_policy_route(
    request: TenantRequest, name: str, payload: PolicyRevisionIn
) -> Status[DeliveryPolicy]:
    """Publish a new policy version

    Publish the next version of a delivery policy.

    Put the policy's `name` in the path and the complete new `steps` list in the
    body — steps are replaced wholesale, not merged, so send every step you want
    the new version to have.

    **This does not edit anything.** You get `201` and a *new* policy at
    `version + 1`; earlier versions stay exactly as they were, so what an
    escalation did in the past stays readable. There is no route that edits a
    policy in place.

    **Safe to publish while an escalation is running.** An escalation already
    under way — including one part-way through a wait — keeps running the
    version it started with; it cannot be changed underneath itself. Sends
    started after this call use the new version.

    Each step is validated as it is on create: the `template` must exist and be
    on that step's `channel`, or you get `400 invalid` naming the step and field
    and nothing is created. A `name` this tenant does not have answers
    `404 not_found`.

    Owner or administrator of the tenant only.

    Refusals you can get here:

    * `400 invalid` — a field is missing or malformed. `errors` names the
      fields and no version is published.
    * `403 forbidden` — you are not an owner or an administrator of the
      tenant.
    * `403 no_acting_scope` — the request resolved no tenant or no acting
      organization.
    * `404 not_found` — no policy of this tenant's has that name.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    policy = revise_policy(
        tenant=tenant,
        actor=actor,
        name=name,
        steps=[step.model_dump() for step in payload.steps],
    )
    return Status(201, policy)


@router.post("/delivery-policies/{name}/retire/", response=PolicyOut, url_name="policy-retire")
def retire_policy_route(request: TenantRequest, name: str) -> DeliveryPolicy:
    """Retire a delivery policy

    Retire the live version of a policy, by name.

    Takes no body. It retires whichever version is currently live under that
    name — the name keeps working and now resolves to the highest version still
    active, so retiring v3 puts v2 back into service. Retiring the only version
    leaves the name with nothing to resolve to, and a send naming it fails.

    Escalations already running are untouched: each keeps the plan it started
    with. So are the messages that recorded it.

    **Safe to retry.** Retiring when the live version is already retired answers
    `200` and changes nothing, rather than conflicting.

    A `name` this tenant does not have answers `404 not_found`. Requires an
    owner or admin role.

    Refusals you can get here:

    * `403 forbidden` — you are not an owner or an administrator of the
      tenant.
    * `403 no_acting_scope` — the request resolved no tenant or no acting
      organization.
    * `404 not_found` — no policy of this tenant's has that name, or it has no
      live version to retire.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---
    A POST on a sub-path rather than a PATCH that sets `is_active`, for the same
    reason consent is five verbs: a flag a door can set is a flag a door can set
    back, and this one decides what every future `send(policy=…)` will do.
    """
    actor, tenant = acting(request)
    policy = get_policy(tenant=tenant, name=name, actor=actor)
    return retire_policy(tenant=tenant, actor=actor, policy=policy)


@router.get("/delivery-policies/{name}/", response=PolicyOut, url_name="policy-detail")
def retrieve_policy(request: TenantRequest, name: str) -> DeliveryPolicy:
    """Retrieve the live delivery policy

    The policy a send under this name would run right now.

    By name, not by id, because that is the question worth asking before you
    send: a name has many versions and this answers with the live one, `steps`
    and all. To see the others — including the retired ones — list
    `/api/v1/delivery-policies/?name=<name>`.

    A name this tenant does not have, or one whose every version is retired,
    answers `404 not_found`.

    Refusals you can get here:

    * `404 not_found` — no policy of this tenant's has that name, or none of
      its versions is live.
    * `403 forbidden` — your membership here does not allow you to read this.
    * `403 no_acting_scope` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    return get_policy(tenant=tenant, name=name, actor=actor)


# --- recipients: the contact book ------------------------------------------------


@router.get("/recipients/", response=list[RecipientOut], url_name="recipient-list")
@paginate(ActsPagination)
def list_recipients_route(
    request: TenantRequest,
    filters: Query[RecipientFilter],
    show: Show = "live",
    ordering: str = "email",
) -> QuerySet[Recipient]:
    """List contacts

    List the contacts your acting organization can address.

    Narrow with `email` (case-insensitive substring). Sort with `ordering`,
    which accepts `email`, `display_name`, `created_at` or `updated_at`, each
    optionally prefixed with `-`; the default is `email` and any other value is
    refused with `400 invalid`. Paged with `?cursor=` and `?limit=`; the body
    is `{"items": [...], "has_more": ..., "next_cursor": ...}`, and `count`
    arrives only with `?include_count=true`.

    **Archived contacts are left out.** `?show=archived` lists only the
    archived ones and `?show=all` lists both; the default is `?show=live`.
    There is no `?archived=` — it is refused with `400 invalid` naming `show`,
    the parameter to ask with instead, rather than ignored.

    Which contacts you see depends on the organization you are acting as (the
    `X-Org` header) — its own and those of organizations beneath it. The same
    person may exist as a separate contact in a different part of the tenant,
    and you will not see that one.

    Every contact carries `allowed_acts` — the acts you may take on that
    contact as it stands — and the page carries its own `allowed_acts`, which
    holds `create` when you may add a contact where you are acting.

    Refusals you can get here:

    * `400 invalid` — `?ordering=` named a field this list does not accept,
      `?show=` named a cut other than `live`, `archived` or `all`, you sent
      `?archived=`, or a filter value was malformed. `errors` names the
      parameter and what it accepts.
    * `403 forbidden` — your membership here does not allow you to read this.
    * `403 no_acting_scope` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    refuse_retired_query(request, RETIRED_QUERY)
    actor, tenant = acting(request)
    recipients: QuerySet[Recipient] = list_recipients(
        tenant=tenant, org=actor.org, show=show, actor=actor
    )
    recipients = filters.filter(recipients)
    return ordered_by(recipients, ordering, allowed=RECIPIENT_ORDERING, default="email")


@router.post("/recipients/", response={201: RecipientOut}, url_name="recipient-create")
def create_recipient_route(request: TenantRequest, payload: RecipientIn) -> Status[Recipient]:
    """Add a contact

    Add a contact your acting organization can address.

    Send `email` — it is the contact's identity here and is lower-cased — and
    optionally `display_name`, `phone` and `chat_handle`.

    A contact is not a user account: they never sign in, and creating one gives
    nobody access to anything.

    **They arrive having consented to nothing.** Transactional messages will
    reach them straight away; anything marketing is refused until you grant
    consent per channel with
    `POST /api/v1/recipients/{recipient_id}/grant-consent/`.

    The contact is created in the organization you are acting as (the `X-Org`
    header), and that is what decides who else in the tenant can see them. There
    is no field that names a different one. An email that organization already
    holds answers `409 conflict` — but the same email in another part of the
    tenant is a separate contact and does not clash.

    Answers `201` with the contact.

    Refusals you can get here:

    * `400 invalid` — a field is missing or malformed. `errors` names the
      fields and nothing is created.
    * `403 forbidden` — your membership here does not allow this.
    * `403 no_acting_scope` — the request resolved no tenant or no acting
      organization.
    * `409 conflict` — this organization already has a contact at that
      address.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    recipient = create_recipient(
        tenant=tenant,
        actor=actor,
        email=payload.email,
        display_name=payload.display_name,
        phone=payload.phone,
        chat_handle=payload.chat_handle,
    )
    return Status(201, with_allowed_acts([recipient], actor)[0])


@router.get("/recipients/{recipient_id}/", response=RecipientOut, url_name="recipient-detail")
def retrieve_recipient(request: TenantRequest, recipient_id: UUID) -> Recipient:
    """Retrieve a contact

    Fetch one contact by id.

    Archived contacts resolve here even though they are out of the list, so a
    message you found in the log can always be traced to who it went to. An
    archived contact reads read-only: `archived_at` and `archived_by` say when
    and by whom, and every change other than
    `POST /api/v1/recipients/{recipient_id}/restore/` is refused with
    `409 archived`.

    A contact your acting organization cannot see, or an id that names nothing,
    answers `404 not_found`.

    `allowed_acts` names the acts you may take on this contact as it stands: an
    archived contact offers only `restore`.

    Consent is not on this shape. Read it at
    `GET /api/v1/recipients/{recipient_id}/preferences/`.

    Refusals you can get here:

    * `404 not_found` — no contact your acting organization can address has
      that id. A contact in a branch you hold no membership over answers
      this too.
    * `403 forbidden` — your membership here does not allow you to read this.
    * `403 no_acting_scope` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    recipient = get_recipient(tenant=tenant, recipient_id=recipient_id, org=actor.org, actor=actor)
    return with_allowed_acts([recipient], actor)[0]


@router.patch("/recipients/{recipient_id}/", response=RecipientOut, url_name="recipient-update")
@refuses(
    "invalid_body",
    "invalid",
    "forbidden",
    "no_acting_scope",
    "insufficient_scope",
    "not_found",
    "archived",
    "conflict",
    "idempotency_key_reuse",
    "in_progress",
)
def update_recipient_route(
    request: TenantRequest, recipient_id: UUID, payload: RecipientPatch
) -> Recipient:
    """Update a contact

    Correct a contact's details.

    Four fields can be changed and no others: `email`, `display_name`, `phone`
    and `chat_handle`. Send only the ones you want to change; anything you omit
    is left alone.

    **A body naming any other field is refused with `400 invalid` and the field
    named** — nothing is accepted and silently ignored here, so if this call
    succeeds, everything you sent took effect.

    In particular you cannot change through this route: whether the contact is
    archived (use `POST .../archive/`), which organization holds them, or
    anything about their consent, quiet hours or suppression (those are the
    routes under `/recipients/{recipient_id}/` named for each verb). Those are
    separate operations because each is a decision somebody made at a moment,
    recorded as such, rather than a column to be overwritten.

    Answers `200` with the contact as it now stands.

    Refusals you can get here:

    * `400 invalid` — a field you sent is malformed. `errors` names it and
      nothing is changed.
    * `403 forbidden` — your membership here does not allow this.
    * `403 no_acting_scope` — the request resolved no tenant or no acting
      organization.
    * `404 not_found` — no contact your acting organization can address has
      that id. A contact in a branch you hold no membership over answers
      this too.
    * `409 archived` — the contact is archived and reads read-only. Restore it
      with `POST /api/v1/recipients/{recipient_id}/restore/` first.
    * `409 conflict` — this organization already has a contact at that
      address.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    recipient = get_recipient(tenant=tenant, recipient_id=recipient_id, org=actor.org, actor=actor)
    updated = update_recipient(
        tenant=tenant,
        actor=actor,
        recipient=recipient,
        email=payload.email,
        display_name=payload.display_name,
        phone=payload.phone,
        chat_handle=payload.chat_handle,
    )
    return with_allowed_acts([updated], actor)[0]


@router.post(
    "/recipients/{recipient_id}/archive/", response=RecipientOut, url_name="recipient-archive"
)
@refuses(
    "archive_blocked",
    "forbidden",
    "no_acting_scope",
    "not_found",
    "idempotency_key_reuse",
    "in_progress",
)
def archive_recipient_route(request: TenantRequest, recipient_id: UUID) -> Recipient:
    """Archive a contact

    Archive a contact.

    Takes no body. The contact drops out of `GET /api/v1/recipients/`
    (`?show=archived` lists them again), stays fetchable by id, and stays
    named on every message already sent to them. Nothing is deleted, and
    `POST /api/v1/recipients/{recipient_id}/restore/` puts them back.

    **This is not a "do not contact" instruction and it does not stop sends.**
    A send to an archived contact still goes out. To stop messages reaching
    somebody, use `POST /api/v1/recipients/{recipient_id}/suppress/`,
    which is checked at send time; archiving is only about your contact book.

    **Safe to retry.** Archiving an archived contact answers `200` and keeps the
    original `archived_at` and `archived_by`, rather than conflicting or moving
    the date.

    An administrator of the organization the contact belongs to, or of one
    above it. Answers `200` with the contact.

    Refusals you can get here:

    * `403 forbidden` — you do not administer the organization this contact
      belongs to.
    * `403 no_acting_scope` — the request resolved no tenant or no acting
      organization.
    * `404 not_found` — no contact your acting organization can address has
      that id. A contact in a branch you hold no membership over answers
      this too.
    * `409 archive_blocked` — something your product declared still holds
      this contact. `blocking` names each thing and where to close it; nothing
      was changed.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    recipient = get_recipient(tenant=tenant, recipient_id=recipient_id, org=actor.org, actor=actor)
    archived = archive_recipient(tenant=tenant, actor=actor, recipient=recipient)
    return with_allowed_acts([archived], actor)[0]


@router.post(
    "/recipients/{recipient_id}/restore/", response=RecipientOut, url_name="recipient-restore"
)
@refuses(
    "restore_blocked",
    "forbidden",
    "no_acting_scope",
    "not_found",
    "idempotency_key_reuse",
    "in_progress",
)
def restore_recipient_route(request: TenantRequest, recipient_id: UUID) -> Recipient:
    """Restore a contact

    Put an archived contact back in the contact book.

    Takes no body. The contact is listed by `GET /api/v1/recipients/` again,
    and `archived_at` and `archived_by` are cleared. What they have agreed to
    receive is untouched: a suppression recorded while they were archived
    still stands.

    **Safe to retry.** Restoring a contact that is not archived answers `200`
    with the contact unchanged.

    An administrator of the organization the contact belongs to, or of one
    above it — whoever may archive a contact may restore it. Answers `200` with
    the contact.

    Refusals you can get here:

    * `403 forbidden` — you do not administer the organization this contact
      belongs to.
    * `403 no_acting_scope` — the request resolved no tenant or no acting
      organization.
    * `404 not_found` — no contact your acting organization can address has
      that id. A contact in a branch you hold no membership over answers
      this too.
    * `409 restore_blocked` — something your product declared stops this
      contact coming back. `blocking` names each thing and where to resolve
      it; nothing was changed.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    recipient = get_recipient(tenant=tenant, recipient_id=recipient_id, org=actor.org, actor=actor)
    restored = restore_recipient(tenant=tenant, actor=actor, recipient=recipient)
    return with_allowed_acts([restored], actor)[0]


# --- preferences: five verbs, and no column a door can set -----------------------


@router.get(
    "/recipients/{recipient_id}/preferences/",
    response=list[PreferenceOut],
    url_name="preference-list",
)
@paginate(CursorPagination)
def list_preferences_route(
    request: TenantRequest, recipient_id: UUID
) -> QuerySet[ChannelPreference]:
    """List a contact's channel preferences

    What one contact has agreed to, channel by channel.

    One row per channel anybody has ever said anything about, carrying
    `has_marketing_consent` (the yes-or-no answer, already accounting for a
    later revocation), the `marketing_consented_at` and `marketing_revoked_at`
    dates behind it, the quiet-hours window, and `suppressed_at`.

    **A channel with no row here is not missing data.** It means nobody has said
    anything about that channel, and that is a meaningful state: transactional
    messages go, marketing ones do not. So an empty list is a complete answer,
    not an error.

    Paged with `?cursor=` and `?limit=`; the body is
    `{"items": [...], "has_more": ..., "next_cursor": ...}`, and `count`
    arrives only with `?include_count=true`.

    Refusals you can get here:

    * `404 not_found` — no contact your acting organization can address has
      that id. A contact in a branch you hold no membership over answers
      this too.
    * `403 insufficient_scope` — the token you sent does not carry the scope
      this read needs. Reading is not role-gated: anybody who can address the
      contact may see what it has agreed to. Granting and revoking consent,
      setting quiet hours and suppressing an address are the
      owner-or-administrator acts.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    recipient = get_recipient(tenant=tenant, recipient_id=recipient_id, org=actor.org, actor=actor)
    preferences: QuerySet[ChannelPreference] = list_preferences(
        tenant=tenant, recipient=recipient, org=actor.org, actor=actor
    )
    return preferences


@router.post(
    "/recipients/{recipient_id}/grant-consent/",
    response=PreferenceOut,
    url_name="consent-grant",
)
def grant_consent_route(
    request: TenantRequest, recipient_id: UUID, payload: PreferenceIn
) -> ChannelPreference:
    """Grant marketing consent

    Record that this contact agreed to marketing on one channel.

    Send `channel` (defaults to `email`). Consent is per channel: agreeing to
    email says nothing about SMS.

    This is what unblocks **marketing** messages. Transactional ones were never
    blocked by consent. Every send checks it at the moment of sending, so this
    takes effect on the next one; it does not release anything already refused.

    Each call stamps `marketing_consented_at` with the time it was made, so
    calling it again moves that date forward. That is how somebody who
    previously withdrew consent opts back in: the later of the consent and
    revocation dates is the one that counts, and neither is ever erased.

    Owner or administrator of the tenant only. Answers `200` with the preference for that
    channel, creating the row if this is the first thing anybody has said about
    it. A contact your acting organization cannot see answers `404 not_found`.

    Refusals you can get here:

    * `400 invalid` — `channel` is not one this product knows. `errors` names
      it and nothing is recorded.
    * `403 forbidden` — you are not an owner or an administrator of the
      tenant.
    * `403 no_acting_scope` — the request resolved no tenant or no acting
      organization.
    * `404 not_found` — no contact your acting organization can address has
      that id. A contact in a branch you hold no membership over answers
      this too.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    recipient = get_recipient(tenant=tenant, recipient_id=recipient_id, org=actor.org, actor=actor)
    return grant_consent(tenant=tenant, actor=actor, recipient=recipient, channel=payload.channel)


@router.post(
    "/recipients/{recipient_id}/revoke-consent/",
    response=PreferenceOut,
    url_name="consent-revoke",
)
def revoke_consent_route(
    request: TenantRequest, recipient_id: UUID, payload: PreferenceIn
) -> ChannelPreference:
    """Revoke marketing consent

    Withdraw this contact's marketing consent on one channel.

    Send `channel` (defaults to `email`).

    **This stops marketing only.** Messages the person is owed — a receipt, a
    password reset, anything sent with a `transactional` template — still go.
    If you need to stop everything reaching an address, that is
    `POST /api/v1/recipients/{recipient_id}/suppress/`.

    Neither date is erased: `marketing_consented_at` stays beside
    `marketing_revoked_at`, and `has_marketing_consent` reflects whichever is
    later. So "they agreed in March and withdrew in June" stays legible, and
    granting again afterwards re-opts them in.

    Revoking when nothing was ever granted is allowed and writes the row: "we
    asked and they said no" is worth recording.

    Owner or administrator of the tenant only. Answers `200` with the preference.

    Refusals you can get here:

    * `400 invalid` — `channel` is not one this product knows.
    * `403 forbidden` — you are not an owner or an administrator of the
      tenant.
    * `403 no_acting_scope` — the request resolved no tenant or no acting
      organization.
    * `404 not_found` — no contact your acting organization can address has
      that id. A contact in a branch you hold no membership over answers
      this too.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    recipient = get_recipient(tenant=tenant, recipient_id=recipient_id, org=actor.org, actor=actor)
    return revoke_consent(tenant=tenant, actor=actor, recipient=recipient, channel=payload.channel)


# `quiet_hours-set`: rule 17 splits the url_name on its last hyphen.
@router.post(
    "/recipients/{recipient_id}/quiet-hours/",
    response=PreferenceOut,
    url_name="quiet_hours-set",
)
def set_quiet_hours_route(
    request: TenantRequest, recipient_id: UUID, payload: QuietHoursIn
) -> ChannelPreference:
    """Set quiet hours

    Set or clear the hours in which this contact is not to be marketed to.

    Send `channel` (defaults to `email`), `start` and `end` as times of day
    (`"22:00:00"`), and `timezone_name`, an IANA name such as
    `"Europe/London"` (defaults to `"UTC"`). The window is read in the
    **contact's** timezone, not the server's, and one that runs past midnight
    (`22:00` to `07:00`) is fine.

    **Send both ends or neither.** One without the other is refused with
    `400 invalid` on `quiet_hours`. Sending neither is how you turn quiet hours
    off. A `timezone_name` that is not a real IANA name is refused with
    `400 invalid` naming that field rather than quietly falling back to UTC.

    A marketing message **sent** during the window is refused outright: the send
    route answers `201` with `status: "suppressed"` and
    `suppressed_reason: "quiet_hours"`, and nothing is queued for later. Send it
    again after the window closes. A message that was already on its way when
    the window opened is held instead, and goes out when it closes.

    Transactional messages ignore the window entirely.

    Owner or administrator of the tenant only. Answers `200` with the preference.

    Refusals you can get here:

    * `400 invalid` — a time was not `HH:MM`, only one end of the window was
      sent, or the timezone is not one this product recognises. `errors`
      names the field and nothing is changed.
    * `403 forbidden` — you are not an owner or an administrator of the
      tenant.
    * `403 no_acting_scope` — the request resolved no tenant or no acting
      organization.
    * `404 not_found` — no contact your acting organization can address has
      that id. A contact in a branch you hold no membership over answers
      this too.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    recipient = get_recipient(tenant=tenant, recipient_id=recipient_id, org=actor.org, actor=actor)
    return set_quiet_hours(
        tenant=tenant,
        actor=actor,
        recipient=recipient,
        channel=payload.channel,
        start=payload.start,
        end=payload.end,
        timezone_name=payload.timezone_name,
    )


@router.post(
    "/recipients/{recipient_id}/suppress/",
    response=PreferenceOut,
    url_name="recipient-suppress",
)
def suppress_recipient_route(
    request: TenantRequest, recipient_id: UUID, payload: PreferenceIn
) -> ChannelPreference:
    """Suppress a channel

    Block one channel for this contact — transactional messages included.

    Send `channel` (defaults to `email`). This is the strongest instruction this
    API takes: no message of any kind goes out on that channel afterwards. Use
    it for a hard bounce, a spam complaint, or somebody asking to be left alone.
    To stop only marketing, use
    `POST /api/v1/recipients/{recipient_id}/revoke-consent/` instead.

    The product also sets this itself when a provider reports that the address
    hard-bounced. There is no difference between the two, and
    `POST .../unsuppress/` lifts either.

    **Safe to retry.** Suppressing an already-suppressed channel answers `200`
    and keeps the original `suppressed_at`.

    Owner or administrator of the tenant only. Answers `200` with the preference.

    Refusals you can get here:

    * `400 invalid` — `channel` is not one this product knows.
    * `403 forbidden` — you are not an owner or an administrator of the
      tenant.
    * `403 no_acting_scope` — the request resolved no tenant or no acting
      organization.
    * `404 not_found` — no contact your acting organization can address has
      that id. A contact in a branch you hold no membership over answers
      this too.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    recipient = get_recipient(tenant=tenant, recipient_id=recipient_id, org=actor.org, actor=actor)
    return suppress_recipient(
        tenant=tenant, actor=actor, recipient=recipient, channel=payload.channel
    )


@router.post(
    "/recipients/{recipient_id}/unsuppress/",
    response=PreferenceOut,
    url_name="recipient-unsuppress",
)
def unsuppress_recipient_route(
    request: TenantRequest, recipient_id: UUID, payload: PreferenceIn
) -> ChannelPreference:
    """Unsuppress a channel

    Unblock a channel for this contact. Marketing consent is not restored.

    Send `channel` (defaults to `email`). Transactional messages can reach the
    address again immediately.

    **It does not opt anybody back in.** Suppression and marketing consent are
    two separate facts and this touches only the first, so somebody who was
    suppressed by a bounce and never consented to marketing ends up exactly
    where they started: transactional yes, marketing no. To restore marketing,
    call `POST /api/v1/recipients/{recipient_id}/grant-consent/` as well —
    and only if they really did agree.

    **Safe to retry.** Lifting a suppression that is not there answers `200` and
    changes nothing.

    Owner or administrator of the tenant only. Answers `200` with the preference.

    Refusals you can get here:

    * `400 invalid` — `channel` is not one this product knows.
    * `403 forbidden` — you are not an owner or an administrator of the
      tenant.
    * `403 no_acting_scope` — the request resolved no tenant or no acting
      organization.
    * `404 not_found` — no contact your acting organization can address has
      that id. A contact in a branch you hold no membership over answers
      this too.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    recipient = get_recipient(tenant=tenant, recipient_id=recipient_id, org=actor.org, actor=actor)
    return unsuppress_recipient(
        tenant=tenant, actor=actor, recipient=recipient, channel=payload.channel
    )


# --- devices: the push address book, tagged per route (a nested router doubles tags) --


@router.post("/devices/", response=DeviceOut, url_name="device-register", tags=["devices"])
def register_device_route(request: TenantRequest, payload: DeviceIn) -> Device:
    """Register a device for push

    Remember a handset or browser one of your contacts will accept
    notifications on.

    Send `recipient_id`, the `platform` (`ios`, `android` or `web`), and the
    `push_token` your client received from the platform. `label` is optional and
    is only ever shown to a human — "Ada's iPhone".

    **Re-registering the same token is the normal case, not an error.** A mobile
    client hands its token back on every launch, after every reinstall, and
    whenever the platform rotates it. So this answers `200` with the row it
    already had — updated with whatever you just sent, and brought back if it
    had been retired — rather than `409`. Send it as often as your client
    likes.

    Where the device lands is decided by the **contact**, not by the
    organization you are acting as: a device belongs wherever its contact
    belongs, so the branch that owns the contact is the branch that can reach
    the device. There is no `organization` field on the body and there will not
    be one.

    **This is not consent.** Registering a device says the product *can* reach
    this handset; whether it *may* is the contact's `push` preference, which is
    checked inside every send. A marketing notification to somebody who has not
    agreed is still refused, and
    `POST /api/v1/recipients/{recipient_id}/grant-consent/` with
    `{"channel": "push"}` is where that is changed.

    **The token never comes back out.** It is stored encrypted and no response
    and no event carries it, or any part of it. Address the device by the `id`
    in this answer.

    Refusals you can get here:

    * `400 invalid` — `platform` is not one this product pushes to, or
      `push_token` was empty.
    * `422 invalid_body` — the body carried a field this operation does not
      have, or was missing one it needs. Bodies are strict here: a misspelled
      field name is refused by name rather than dropped in silence.
    * `403 forbidden` — your membership here does not allow this.
    * `403 no_acting_scope` — the request resolved no tenant or no acting
      organization.
    * `404 not_found` — no contact your acting organization can address has
      that `recipient_id`. A contact in a branch you hold no membership over
      answers this too.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    recipient = get_recipient(
        tenant=tenant, recipient_id=payload.recipient_id, org=actor.org, actor=actor
    )
    return register_device(
        tenant=tenant,
        actor=actor,
        recipient=recipient,
        platform=payload.platform,
        push_token=payload.push_token,
        label=payload.label,
    )


@router.post(
    "/devices/{device_id}/retire/",
    response=DeviceOut,
    url_name="device-retire",
    tags=["devices"],
)
def retire_device_route(request: TenantRequest, device_id: UUID) -> Device:
    """Retire a device

    Stop pushing to one install. The record stays; the address book loses it.

    Send no body. Use it when somebody signs out, when a handset is replaced, or
    when the platform tells you a token is dead. The row is not deleted — a
    notification that went to that device is still in the message log pointing
    at it — and `retired_at` on the answer says when it left.

    **It does not stop notifications to the person**, only to that install. If
    they have two devices registered, the other one still receives. "Stop
    pushing to this person" is
    `POST /api/v1/recipients/{recipient_id}/suppress/` with
    `{"channel": "push"}`, which is a consent decision and lives with the other
    consent verbs.

    **Safe to retry.** Retiring a retired device answers `200` and keeps the
    original `retired_at`. Registering the same token again brings it back.

    Refusals you can get here:

    * `403 forbidden` — your membership here does not allow this.
    * `403 no_acting_scope` — the request resolved no tenant or no acting
      organization.
    * `404 not_found` — no device your acting organization can reach has that
      id. A device belonging to a contact in a branch you hold no membership
      over answers this too.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    device = get_device(tenant=tenant, device_id=device_id, org=actor.org, actor=actor)
    return retire_device(tenant=tenant, actor=actor, device=device)
