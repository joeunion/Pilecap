"""The comms API: send one message, read the log, keep what may be said.

Two halves. **The send door** — `POST /messages/` and the two reads beside it —
is C1-1a's and is the point of the app. **The management surface** below it is
C1-1b's: templates that are versioned rather than edited, a contact book, and
five consent verbs. The asymmetry `policies.py` states runs right through it —
anybody in the tenant may send and may keep contacts; only an owner or an admin
changes what the product is allowed to say.

Two shapes are worth reading for, because they are the difference between a
management door and a set of columns:

* **a template is never PATCHed.** `POST /templates/{name}/versions/` answers
  `201` with a new row at `version + 1`; the words a message was sent with stay
  exactly where they were.
* **consent is five verbs, not five fields.** `grant-consent`, `revoke-consent`,
  `quiet-hours`, `suppress`, `unsuppress` — each a POST on its own sub-path. A
  column a door can set is a column a door can set back, and `PreferenceOut`
  reports the timestamps that nothing accepts.

The shape of the send route is the whole point of this app.
`POST /api/v1/messages/` is **not** a create endpoint that happens to
send an email: it is `send()` behind a door, so a consent refusal comes back as
`201` with `status="suppressed"` and a reason rather than as an error. A client
that treats 2xx as "it went out" is reading the status code where it should be
reading the row — which is why `status` and `suppressed_reason` are on the
schema and not hidden behind a second call.

The route never says 404 either. `selectors.get_message` raises `NotFound` and
`config/api.py` is the only module that turns that into a number, so the MCP
tool over the same selector refuses identically without repeating the rule.
"""

# NOTE: no `from __future__ import annotations` in this module, and that is
# deliberate. ninja builds a Pydantic model out of a route's signature at import
# time; with postponed evaluation every annotation is a string, and a
# `FilterSchema` parameter comes out as an unresolvable forward reference.

from uuid import UUID

from django.db.models import QuerySet
from ninja import Query, Router, Status
from ninja.errors import HttpError
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
from apps.core.actor import Actor, actor_from_request
from apps.core.api import CursorPagination, ordered_by
from apps.core.api.docs import Tag
from apps.core.models import Tenant
from apps.core.requests import TenantRequest

# **The root of `/api/v1/`** (ADR api-2, the owner's 2026-08-24 ruling): the
# first path segment names a RESOURCE, never an app. `comms` is what this
# module is called, not what any caller wants; `/messages/`, `/templates/` and
# `/recipients/` are. The one collision the flatten exposed resolves by a
# BETTER NAME rather than by a prefix: `policies` alone says nothing on a wire
# that also has authorization policies, so these are `/delivery-policies/` —
# which is what they have always been. House rule 32 refuses the regression.
PREFIX = ""

# What `?ordering=` may name, and nothing else. Straight into `.order_by()` it
# would let a client sort by any column and traverse any relation.
ORDERING = ("created_at", "updated_at", "sent_at", "status")
TEMPLATE_ORDERING = ("name", "version", "created_at", "updated_at")
RECIPIENT_ORDERING = ("email", "display_name", "created_at", "updated_at")
POLICY_ORDERING = ("name", "version", "created_at", "updated_at")
# Two columns and deliberately not four. `occurred_at` is when the PROVIDER says
# the person acted and `created_at` is when we heard; a client sorting an
# engagement list wants one of those, and nothing else on the row is an order
# anybody has a question about.
ENGAGEMENT_ORDERING = ("occurred_at", "created_at")

# What each tag on this app's routers is FOR, in the app that owns the tag.
# `config/api.py` collects these by discovery into the OpenAPI document's `tags`
# section, so a reader meets the group before the routes in it (ADR api-1); an
# undescribed tag is a house-rule-41 violation, not a blank heading.
# The key is `messaging`, not `comms` (the owner's 2026-08-24 ruling, ruled
# before N162a freezes tag keys as the credential vocabulary): `comms` was this
# app's directory name, and a caller narrowing a token to a family should be
# reading the word for the thing, not for the folder it happens to live in. The
# display name did not move.
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
    # T3. Its own family rather than a corner of `messaging`, because the two
    # are not the same trust: `messaging:write` is "may contact a person" and
    # `devices:write` is "may keep the push address book", which reaches nobody
    # by itself. RUL-1 ratified the key before the door shipped, which is the
    # order a frozen vocabulary has to be decided in.
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

# `auth` is restated here rather than inherited from the API default, so that
# reading this one file tells you what it takes to call these routes.
router = Router(tags=["messaging"], auth=API_AUTH)


def _acting(request: TenantRequest) -> tuple[Actor, Tenant]:
    """The actor and tenant a send happens as.

    Authentication has already guaranteed the user; nothing has guaranteed the
    tenant. A send with no tenant is refused rather than guessed at.

    **Whether the actor may send is not decided here** — `services.send` calls
    `authz.require`. A permission check in this function would be a second copy
    of the rule, one per door.
    """
    if request.tenant is None:
        raise HttpError(403, "No tenant for this request.")
    return actor_from_request(request), request.tenant


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
    * `403 forbidden` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    messages: QuerySet[Message] = list_messages(tenant=request.tenant, org=request.org)
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
    * `403 forbidden` — you hold no membership in this tenant, or the request
      resolved no tenant or no acting organization.
    * `404 not_found` — no contact your acting organization can address has
      that id. A contact in a branch you hold no membership over answers
      this too.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    recipient = get_recipient(tenant=tenant, recipient_id=payload.recipient_id, org=actor.org)
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
    * `403 forbidden` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    return get_message(tenant=request.tenant, message_id=message_id, org=request.org)


@router.get(
    "/messages/{message_id}/engagement/",
    response=list[MessageEngagementOut],
    # `engagement-list`, not `message-engagement-list`: house rule 17 derives
    # the MCP tool name from the `url_name` by splitting on the last hyphen, so
    # the longer spelling would have demanded a tool called
    # `list_message-engagements` — a hyphen inside a machine-door name, in an
    # app whose every other tool is a plain identifier. The path already says
    # which resource this hangs off.
    url_name="engagement-list",
)
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
    * `403 forbidden` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `404 not_found` — no message your acting organization can see has that
      id, or `?cursor=` did not come from this list.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    message = get_message(tenant=request.tenant, message_id=message_id, org=request.org)
    rows: QuerySet[MessageEngagement] = list_engagements(
        tenant=request.tenant, message=message, org=request.org
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

    * `403 forbidden` — you hold no membership in this tenant, or the request
      resolved no tenant or no acting organization.
    * `404 not_found` — no message your acting organization can see has that
      id. A message in a branch you hold no membership over answers this too.
    * `409 conflict` — that message is past the point of being cancelled. The
      detail names the status it is in.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    message = get_message(tenant=tenant, message_id=message_id, org=actor.org)
    return cancel_message(tenant=tenant, actor=actor, message=message)


# --- templates: written once, revised, never edited ------------------------------
#
# **One resource, one address key: the NAME.** A template used to answer to
# two — `{name}` to revise, the UUID to retire and to read — so a caller who had
# just revised "welcome" by name could not retire it by name; it had to list
# first to learn an id. That is a versioned-and-named resource, and this tree has
# exactly one other, `/delivery-policies/` below: it is name-addressed on all
# three of revise, retire and detail, and templates now match it.
#
# The name is also the key the rest of the product speaks. `send(template=...)`
# takes a name, a policy step names a template by name, and a `Message` records
# `template_name` + `template_version` rather than an id — so the id was only
# ever reachable by listing, and nothing but these two routes asked for it.
#
# What the id bought was reaching a RETIRED version directly, and the list is
# where that lives now — `GET /templates/?name=<name>` returns every version,
# which is what the detail route's own prose already told callers to do. The
# `url_name`s did not move, so no MCP tool name moved with the paths (rule 17
# derives tool names from `url_name`, never from paths).


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
    * `403 forbidden` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    templates: QuerySet[MessageTemplate] = list_templates(tenant=request.tenant)
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
      tenant, or the request resolved no tenant or no acting organization.
    * `409 conflict` — a template already exists under that name. Publish a
      new version of it instead.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
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
      tenant, or the request resolved no tenant or no acting organization.
    * `404 not_found` — no template of this tenant's has that name.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
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
      tenant, or the request resolved no tenant or no acting organization.
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
    actor, tenant = _acting(request)
    template = get_template(tenant=tenant, name=name)
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
    * `403 forbidden` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    return get_template(tenant=request.tenant, name=name)


# --- delivery policies: how hard to try, as data ---------------------------------
#
# Five routes and five MCP twins, and the `url_name`s are worth a note because
# they look inconsistent and are not. House rule 17 pairs a REST capability with
# a tool by deriving candidate names from `<noun>-<verb>`, so `policies-list`
# is what produces `list_policies` — the name the selector already has — while
# the other four read best with the singular noun they act on. The alternative
# was a tool called `list_policys`.


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
    * `403 forbidden` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    policies: QuerySet[DeliveryPolicy] = list_policies(tenant=request.tenant)
    policies = filters.filter(policies)
    ordered = ordered_by(policies, ordering, allowed=POLICY_ORDERING, default="name")
    # `ordered_by` **replaces** the ordering outright, so "newest version first
    # within a name" — which `list_policies` promises and this door repeats —
    # has to be restated or two versions of one policy come back in whatever
    # order the database felt like that day. Restated here rather than fixed in
    # `core.api.ordered_by`, which this app does not own; the template list
    # beside this one has the same gap and it is reported rather than patched
    # from a lane that cannot test the blast radius.
    return ordered.order_by(*ordered.query.order_by, "-version")


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
      tenant, or the request resolved no tenant or no acting organization.
    * `409 conflict` — a policy already exists under that name. Publish a new
      version of it instead.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
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
      tenant, or the request resolved no tenant or no acting organization.
    * `404 not_found` — no policy of this tenant's has that name.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
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
      tenant, or the request resolved no tenant or no acting organization.
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
    actor, tenant = _acting(request)
    policy = get_policy(tenant=tenant, name=name)
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
    * `403 forbidden` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    return get_policy(tenant=request.tenant, name=name)


# --- recipients: the contact book ------------------------------------------------


@router.get("/recipients/", response=list[RecipientOut], url_name="recipient-list")
@paginate(CursorPagination)
def list_recipients_route(
    request: TenantRequest,
    filters: Query[RecipientFilter],
    archived: bool = False,
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

    **Archived contacts are left out.** Pass `?archived=true` to include them.

    Which contacts you see depends on the organization you are acting as (the
    `X-Org` header) — its own and those of organizations beneath it. The same
    person may exist as a separate contact in a different part of the tenant,
    and you will not see that one.

    Refusals you can get here:

    * `400 invalid` — `?ordering=` named a field this list does not accept, or
      a filter value was malformed. The response says what you may sort by.
    * `403 forbidden` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    recipients: QuerySet[Recipient] = list_recipients(
        tenant=request.tenant, org=request.org, include_archived=archived
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
    * `403 forbidden` — you hold no membership in this tenant, or the request
      resolved no tenant or no acting organization.
    * `409 conflict` — this organization already has a contact at that
      address.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    recipient = create_recipient(
        tenant=tenant,
        actor=actor,
        email=payload.email,
        display_name=payload.display_name,
        phone=payload.phone,
        chat_handle=payload.chat_handle,
    )
    return Status(201, recipient)


@router.get("/recipients/{recipient_id}/", response=RecipientOut, url_name="recipient-detail")
def retrieve_recipient(request: TenantRequest, recipient_id: UUID) -> Recipient:
    """Retrieve a contact

    Fetch one contact by id.

    Archived contacts resolve here even though they are out of the list, so a
    message you found in the log can always be traced to who it went to.

    A contact your acting organization cannot see, or an id that names nothing,
    answers `404 not_found`.

    Consent is not on this shape. Read it at
    `GET /api/v1/recipients/{recipient_id}/preferences/`.

    Refusals you can get here:

    * `404 not_found` — no contact your acting organization can address has
      that id. A contact in a branch you hold no membership over answers
      this too.
    * `403 forbidden` — the request resolved no tenant or no acting
      organization. Send `X-Tenant` and `X-Org` naming ones you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    return get_recipient(tenant=request.tenant, recipient_id=recipient_id, org=request.org)


@router.patch("/recipients/{recipient_id}/", response=RecipientOut, url_name="recipient-update")
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
    * `403 forbidden` — you hold no membership in this tenant, or the request
      resolved no tenant or no acting organization.
    * `404 not_found` — no contact your acting organization can address has
      that id. A contact in a branch you hold no membership over answers
      this too.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    recipient = get_recipient(tenant=tenant, recipient_id=recipient_id, org=actor.org)
    return update_recipient(
        tenant=tenant,
        actor=actor,
        recipient=recipient,
        email=payload.email,
        display_name=payload.display_name,
        phone=payload.phone,
        chat_handle=payload.chat_handle,
    )


@router.post(
    "/recipients/{recipient_id}/archive/", response=RecipientOut, url_name="recipient-archive"
)
def archive_recipient_route(request: TenantRequest, recipient_id: UUID) -> Recipient:
    """Archive a contact

    Archive a contact.

    Takes no body. The contact drops out of `GET /api/v1/recipients/`
    (pass `?archived=true` to see them again), stays fetchable by id, and stays
    named on every message already sent to them. Nothing is deleted.

    **This is not a "do not contact" instruction and it does not stop sends.**
    A send to an archived contact still goes out. To stop messages reaching
    somebody, use `POST /api/v1/recipients/{recipient_id}/suppress/`,
    which is checked at send time; archiving is only about your contact book.

    **Safe to retry.** Archiving an archived contact answers `200` and keeps the
    original `archived_at`, rather than conflicting or moving the date.

    Owner or administrator of the tenant only. Answers `200` with the contact.

    Refusals you can get here:

    * `403 forbidden` — you are not an owner or an administrator of the
      tenant, or the request resolved no tenant or no acting organization.
    * `404 not_found` — no contact your acting organization can address has
      that id. A contact in a branch you hold no membership over answers
      this too.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    recipient = get_recipient(tenant=tenant, recipient_id=recipient_id, org=actor.org)
    return archive_recipient(tenant=tenant, actor=actor, recipient=recipient)


# --- preferences: five verbs, and no column a door can set -----------------------
#
# Every one of these is a POST on a sub-path rather than a field on a PATCH, for
# the reason `services.py` states: a column a door can set is a column a door can
# set back, and "they consented on the 3rd and withdrew on the 9th" is a history,
# not a checkbox. `PreferenceOut` reports the timestamps; nothing accepts them.


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
    recipient = get_recipient(tenant=request.tenant, recipient_id=recipient_id, org=request.org)
    preferences: QuerySet[ChannelPreference] = list_preferences(
        tenant=request.tenant, recipient=recipient, org=request.org
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
      tenant, or the request resolved no tenant or no acting organization.
    * `404 not_found` — no contact your acting organization can address has
      that id. A contact in a branch you hold no membership over answers
      this too.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    recipient = get_recipient(tenant=tenant, recipient_id=recipient_id, org=actor.org)
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
      tenant, or the request resolved no tenant or no acting organization.
    * `404 not_found` — no contact your acting organization can address has
      that id. A contact in a branch you hold no membership over answers
      this too.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    recipient = get_recipient(tenant=tenant, recipient_id=recipient_id, org=actor.org)
    return revoke_consent(tenant=tenant, actor=actor, recipient=recipient, channel=payload.channel)


# `quiet_hours-set` rather than `quiet-hours-set`, and the underscore is
# load-bearing: house rule 17 splits a url_name on its LAST hyphen into a noun
# and a verb, and looks for `<verb>_<noun>` on the machine door. A hyphen inside
# the noun would make the pair it looks for `set_quiet-hours`, which is not a
# name Python can carry — so the parity check would report a capability with no
# tool, for a tool that is right there.
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
      tenant, or the request resolved no tenant or no acting organization.
    * `404 not_found` — no contact your acting organization can address has
      that id. A contact in a branch you hold no membership over answers
      this too.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    recipient = get_recipient(tenant=tenant, recipient_id=recipient_id, org=actor.org)
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
      tenant, or the request resolved no tenant or no acting organization.
    * `404 not_found` — no contact your acting organization can address has
      that id. A contact in a branch you hold no membership over answers
      this too.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    recipient = get_recipient(tenant=tenant, recipient_id=recipient_id, org=actor.org)
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
      tenant, or the request resolved no tenant or no acting organization.
    * `404 not_found` — no contact your acting organization can address has
      that id. A contact in a branch you hold no membership over answers
      this too.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    recipient = get_recipient(tenant=tenant, recipient_id=recipient_id, org=actor.org)
    return unsuppress_recipient(
        tenant=tenant, actor=actor, recipient=recipient, channel=payload.channel
    )


# --- devices: the push address book ----------------------------------------------
#
# **Its own scope family, on the same router.** `tags=["devices"]` is declared
# per route rather than on a second `Router`, because ninja ACCUMULATES a nested
# router's tags downward (`Router.set_api_instance`) and this app's mount already
# carries `messaging` — a nested router would put two tags on every device
# operation, which house rule 41 refuses and which makes the app appear twice in
# the navigation (the shape `apps/accounts/api.py`'s mount note records). A tag
# declared on the operation REPLACES the router's, so these two carry exactly
# one each.
#
# Why a family of its own rather than `messaging` (RUL-1, ratified): the two
# capabilities are not the same trust. `messaging:write` is "may contact a
# person"; `devices:write` is "may add or retire a handset in the address book",
# which reaches nobody by itself — a registration is not a send and not a
# consent — and an agent trusted to keep an address book is not thereby trusted
# to mail everybody in it. The key is frozen from the day it ships
# (`apps/core/api/scopes.py`).


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
    * `403 forbidden` — you hold no membership in this tenant, or the request
      resolved no tenant or no acting organization.
    * `404 not_found` — no contact your acting organization can address has
      that `recipient_id`. A contact in a branch you hold no membership over
      answers this too.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    recipient = get_recipient(tenant=tenant, recipient_id=payload.recipient_id, org=actor.org)
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

    * `403 forbidden` — you hold no membership in this tenant, or the request
      resolved no tenant or no acting organization.
    * `404 not_found` — no device your acting organization can reach has that
      id. A device belonging to a contact in a branch you hold no membership
      over answers this too.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    device = get_device(tenant=tenant, device_id=device_id, org=actor.org)
    return retire_device(tenant=tenant, actor=actor, device=device)
