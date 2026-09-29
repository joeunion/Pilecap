"""The machine door onto comms — every capability the REST door has, no exemption.

Door parity (house rule 17): every capability `api.py` offers a person,
`mcp.py` offers a machine, over the *same* selectors, the *same* service and
the *same* schemas. `tests/test_mcp.py` diffs the two answers for the same row
so a divergence is a failing test rather than a review note.

**And the same words** (ADR api-1, house rule 41): every `description=` below is
`contract_of(<the REST route>)` — the contract half of the very docstring the
OpenAPI document describes that route with — so one capability cannot be
explained two ways. A description typed here would be the first place the doors
drift, and prose drifts long before behaviour does.

The consent wall is the reason this matters more here than anywhere else in the
template. An agent is exactly the kind of caller that will happily send a
thousand messages, and there is deliberately no tool that sends without going
through `services.send` — so quiet hours, consent and suppression apply to the
machine door by construction rather than by an agent remembering them.

`send_message` returns a `MessageOut` whose `status` may be `suppressed`, and
that is not an error: a tool that raised there would teach an agent to retry,
which is the one response to "this person opted out" that must never happen.

The management half is C1-1b's, and the two shapes it keeps are the ones an
agent is most likely to try to go around. **`revise_template` publishes a new
version and there is no tool that edits one** — an agent asked to "fix a typo in
the receipt" gets a v2 and the words already sent stay readable. **Consent is
five verbs and no settable column**: `PreferenceOut` reports
`marketing_consented_at` and `suppressed_at`, and nothing on this door accepts
them, so an agent cannot write a consent record on somebody's behalf by naming
a timestamp.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from apps.comms.api import (
    ENGAGEMENT_ORDERING,
    ORDERING,
    POLICY_ORDERING,
    RECIPIENT_ORDERING,
    TEMPLATE_ORDERING,
    archive_recipient_route,
    cancel_message_route,
    create_policy_route,
    create_recipient_route,
    create_template_route,
    grant_consent_route,
    list_message_engagement_route,
    list_messages_route,
    list_policies_route,
    list_preferences_route,
    list_recipients_route,
    list_templates_route,
    register_device_route,
    restore_recipient_route,
    retire_device_route,
    retire_policy_route,
    retire_template_route,
    retrieve_message,
    retrieve_policy,
    retrieve_recipient,
    retrieve_template,
    revise_policy_route,
    revise_template_route,
    revoke_consent_route,
    send_message_route,
    set_quiet_hours_route,
    suppress_recipient_route,
    unsuppress_recipient_route,
    update_recipient_route,
)
from apps.comms.models import (
    Category,
    Channel,
    ChannelPreference,
    DeliveryPolicy,
    Device,
    Message,
    MessageEngagement,
    MessageTemplate,
    Recipient,
)
from apps.comms.schemas import (
    DeviceOut,
    MessageEngagementOut,
    MessageEngagementPage,
    MessageFilter,
    MessageOut,
    MessagePage,
    PolicyFilter,
    PolicyOut,
    PolicyPage,
    PolicyStepIn,
    PreferenceOut,
    PreferencePage,
    RecipientFilter,
    RecipientOut,
    RecipientPage,
    RecipientShow,
    TemplateFilter,
    TemplateOut,
    TemplatePage,
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
from apps.core.api import ordered_by
from apps.core.api.docs import contract_of
from apps.core.api.pagination import cursor_page
from apps.core.mcp import acting_tenant, tool_call
from apps.core.verbs import with_allowed_acts


def register(server: MCPServer[Any]) -> None:
    """Contribute this app's tools. `config.mcp` discovers and calls this."""

    @server.tool(
        name="list_messages",
        description=contract_of(list_messages_route),
    )
    def list_messages_tool(
        ctx: Context[Any],
        status: str | None = None,
        channel: str | None = None,
        template: str | None = None,
        ordering: str = "-created_at",
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> MessagePage:
        with tool_call(ctx) as acting:
            # Scoped first and only narrowed after — the type widens from
            # `ScopedQuerySet` to `QuerySet` because filtering returns the plain
            # one, and narrowing a queryset cannot widen its tenant.
            messages: QuerySet[Message] = MessageFilter(
                status=status, channel=channel, template=template
            ).filter(list_messages(tenant=acting.tenant, org=acting.org, actor=acting.actor()))
            messages = ordered_by(messages, ordering, allowed=ORDERING, default="-created_at")
            page = cursor_page(
                messages,
                tenant=acting.tenant,
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )
            return MessagePage(
                items=[MessageOut.from_orm(message) for message in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(
        name="get_message",
        description=contract_of(retrieve_message),
    )
    def get_message_tool(ctx: Context[Any], message_id: UUID) -> MessageOut:
        with tool_call(ctx) as acting:
            # A message in another tenant is `not_found`, exactly as it is over
            # HTTP: a refusal that distinguished the two would tell the caller
            # the row exists, which is the fact the scoping was hiding.
            return MessageOut.from_orm(
                get_message(
                    tenant=acting.tenant,
                    message_id=message_id,
                    org=acting.org,
                    actor=acting.actor(),
                )
            )

    @server.tool(
        name="send_message",
        description=contract_of(send_message_route),
    )
    def send_message_tool(
        ctx: Context[Any],
        recipient_id: UUID,
        template: str = "",
        context: dict[str, Any] | None = None,
        channel: str = "",
        policy: str = "",
        send_at: datetime | None = None,
    ) -> MessageOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            recipient = get_recipient(
                tenant=tenant, recipient_id=recipient_id, org=acting.org, actor=acting.actor()
            )
            return MessageOut.from_orm(
                send(
                    recipient=recipient,
                    template=template,
                    context=dict(context or {}),
                    channel=channel,
                    policy=policy,
                    send_at=send_at,
                    tenant=tenant,
                    actor=acting.actor(),
                )
            )

    @server.tool(
        name="cancel_message",
        description=contract_of(cancel_message_route),
    )
    def cancel_message_tool(ctx: Context[Any], message_id: UUID) -> MessageOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            message = get_message(
                tenant=tenant, message_id=message_id, org=acting.org, actor=acting.actor()
            )
            return MessageOut.from_orm(
                cancel_message(tenant=tenant, actor=acting.actor(), message=message)
            )

    @server.tool(
        name="list_engagements",
        description=contract_of(list_message_engagement_route),
    )
    def list_engagements_tool(
        ctx: Context[Any],
        message_id: UUID,
        ordering: str = "-occurred_at",
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> MessageEngagementPage:
        with tool_call(ctx) as acting:
            # The message is resolved through the same selector the REST door
            # uses, so a message this hat cannot see is `not_found` here too —
            # and the engagement list never becomes a way to learn that
            # somebody else's message exists.
            message = get_message(
                tenant=acting.tenant, message_id=message_id, org=acting.org, actor=acting.actor()
            )
            rows: QuerySet[MessageEngagement] = list_engagements(
                tenant=acting.tenant, message=message, org=acting.org, actor=acting.actor()
            )
            rows = ordered_by(rows, ordering, allowed=ENGAGEMENT_ORDERING, default="-occurred_at")
            page = cursor_page(
                rows,
                tenant=acting.tenant,
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )
            return MessageEngagementPage(
                items=[MessageEngagementOut.from_orm(row) for row in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    # --- devices: the push address book -------------------------------------
    #
    # **There is no `list_devices` tool, because there is no list ROUTE** — T3
    # shipped a registration door and a retirement door and no read, so
    # `devices:read` derives into the vocabulary and reaches nothing (the
    # `usage:write` shape, recorded in `apps/core/api/scopes.py`). House rule 17
    # compares the two doors' capabilities, and adding a machine-only read here
    # would be the disagreement it exists to refuse — in the direction nobody
    # checks, because an agent would have a capability a person does not.

    @server.tool(
        name="register_device",
        description=contract_of(register_device_route),
    )
    def register_device_tool(
        ctx: Context[Any],
        recipient_id: UUID,
        platform: str,
        push_token: str,
        label: str = "",
    ) -> DeviceOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            recipient = get_recipient(
                tenant=tenant, recipient_id=recipient_id, org=acting.org, actor=acting.actor()
            )
            return DeviceOut.from_orm(
                register_device(
                    tenant=tenant,
                    actor=acting.actor(),
                    recipient=recipient,
                    platform=platform,
                    push_token=push_token,
                    label=label,
                )
            )

    @server.tool(
        name="retire_device",
        description=contract_of(retire_device_route),
    )
    def retire_device_tool(ctx: Context[Any], device_id: UUID) -> DeviceOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            device: Device = get_device(
                tenant=tenant, device_id=device_id, org=acting.org, actor=acting.actor()
            )
            return DeviceOut.from_orm(
                retire_device(tenant=tenant, actor=acting.actor(), device=device)
            )

    # --- templates ---------------------------------------------------------

    @server.tool(
        name="list_templates",
        description=contract_of(list_templates_route),
    )
    def list_templates_tool(
        ctx: Context[Any],
        name: str | None = None,
        channel: str | None = None,
        category: str | None = None,
        ordering: str = "name",
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> TemplatePage:
        with tool_call(ctx) as acting:
            templates: QuerySet[MessageTemplate] = TemplateFilter(
                name=name, channel=channel, category=category
            ).filter(list_templates(tenant=acting.tenant, actor=acting.actor()))
            templates = ordered_by(templates, ordering, allowed=TEMPLATE_ORDERING, default="name")
            page = cursor_page(
                templates,
                tenant=acting.tenant,
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )
            return TemplatePage(
                items=[TemplateOut.from_orm(row) for row in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(
        name="get_template",
        description=contract_of(retrieve_template),
    )
    def get_template_tool(ctx: Context[Any], name: str) -> TemplateOut:
        with tool_call(ctx) as acting:
            return TemplateOut.from_orm(
                get_template(tenant=acting.tenant, name=name, actor=acting.actor())
            )

    @server.tool(
        name="create_template",
        description=contract_of(create_template_route),
    )
    def create_template_tool(
        ctx: Context[Any],
        name: str,
        body: str,
        subject: str = "",
        channel: str = Channel.EMAIL.value,
        category: str = Category.TRANSACTIONAL.value,
        context_schema: dict[str, Any] | None = None,
    ) -> TemplateOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            return TemplateOut.from_orm(
                create_template(
                    tenant=tenant,
                    actor=acting.actor(),
                    name=name,
                    body=body,
                    subject=subject,
                    channel=channel,
                    category=category,
                    context_schema=dict(context_schema or {}),
                )
            )

    @server.tool(
        name="revise_template",
        description=contract_of(revise_template_route),
    )
    def revise_template_tool(
        ctx: Context[Any],
        name: str,
        body: str,
        subject: str = "",
        category: str | None = None,
        context_schema: dict[str, Any] | None = None,
    ) -> TemplateOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            return TemplateOut.from_orm(
                revise_template(
                    tenant=tenant,
                    actor=acting.actor(),
                    name=name,
                    body=body,
                    subject=subject,
                    category=category,
                    context_schema=context_schema,
                )
            )

    @server.tool(
        name="retire_template",
        description=contract_of(retire_template_route),
    )
    def retire_template_tool(ctx: Context[Any], name: str) -> TemplateOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            template = get_template(tenant=tenant, name=name, actor=acting.actor())
            return TemplateOut.from_orm(
                retire_template(tenant=tenant, actor=acting.actor(), template=template)
            )

    # --- recipients --------------------------------------------------------

    # --- delivery policies: the five twins of the five routes ---------------------

    @server.tool(
        name="list_policies",
        description=contract_of(list_policies_route),
    )
    def list_policies_tool(
        ctx: Context[Any],
        name: str | None = None,
        ordering: str = "name",
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> PolicyPage:
        with tool_call(ctx) as acting:
            policies: QuerySet[DeliveryPolicy] = PolicyFilter(name=name).filter(
                list_policies(tenant=acting.tenant, actor=acting.actor())
            )
            policies = ordered_by(policies, ordering, allowed=POLICY_ORDERING, default="name")
            page = cursor_page(
                policies,
                tenant=acting.tenant,
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )
            return PolicyPage(
                items=[PolicyOut.from_orm(row) for row in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(
        name="get_policy",
        description=contract_of(retrieve_policy),
    )
    def get_policy_tool(ctx: Context[Any], name: str) -> PolicyOut:
        with tool_call(ctx) as acting:
            return PolicyOut.from_orm(
                get_policy(tenant=acting.tenant, name=name, actor=acting.actor())
            )

    @server.tool(
        name="create_policy",
        description=contract_of(create_policy_route),
    )
    def create_policy_tool(
        ctx: Context[Any],
        name: str,
        steps: list[PolicyStepIn],
    ) -> PolicyOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            return PolicyOut.from_orm(
                create_policy(
                    tenant=tenant,
                    actor=acting.actor(),
                    name=name,
                    steps=[step.model_dump() for step in steps],
                )
            )

    @server.tool(
        name="revise_policy",
        description=contract_of(revise_policy_route),
    )
    def revise_policy_tool(
        ctx: Context[Any],
        name: str,
        steps: list[PolicyStepIn],
    ) -> PolicyOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            return PolicyOut.from_orm(
                revise_policy(
                    tenant=tenant,
                    actor=acting.actor(),
                    name=name,
                    steps=[step.model_dump() for step in steps],
                )
            )

    @server.tool(
        name="retire_policy",
        description=contract_of(retire_policy_route),
    )
    def retire_policy_tool(ctx: Context[Any], name: str) -> PolicyOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            policy = get_policy(tenant=tenant, name=name, actor=acting.actor())
            return PolicyOut.from_orm(
                retire_policy(tenant=tenant, actor=acting.actor(), policy=policy)
            )

    @server.tool(
        name="list_recipients",
        description=contract_of(list_recipients_route),
    )
    def list_recipients_tool(
        ctx: Context[Any],
        email: str | None = None,
        show: RecipientShow = "live",
        ordering: str = "email",
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> RecipientPage:
        with tool_call(ctx) as acting:
            actor = acting.actor()
            recipients: QuerySet[Recipient] = RecipientFilter(email=email).filter(
                list_recipients(
                    tenant=acting.tenant,
                    org=acting.org,
                    show=show,
                    actor=actor,
                )
            )
            recipients = ordered_by(
                recipients, ordering, allowed=RECIPIENT_ORDERING, default="email"
            )
            # `actor=` is what makes this the family's page: every contact's
            # `allowed_acts` and the list's own, from the seam the REST door's
            # `ActsPagination` calls, so the two doors cannot disagree about
            # who may do what.
            page = cursor_page(
                recipients,
                tenant=acting.tenant,
                cursor=cursor,
                limit=limit,
                include_count=include_count,
                actor=actor,
            )
            return RecipientPage(
                items=[RecipientOut.from_orm(row) for row in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
                allowed_acts=list(page.allowed_acts or ()),
            )

    @server.tool(
        name="get_recipient",
        description=contract_of(retrieve_recipient),
    )
    def get_recipient_tool(ctx: Context[Any], recipient_id: UUID) -> RecipientOut:
        with tool_call(ctx) as acting:
            actor = acting.actor()
            recipient = get_recipient(
                tenant=acting.tenant, recipient_id=recipient_id, org=acting.org, actor=actor
            )
            return RecipientOut.from_orm(with_allowed_acts([recipient], actor)[0])

    @server.tool(
        name="create_recipient",
        description=contract_of(create_recipient_route),
    )
    def create_recipient_tool(
        ctx: Context[Any],
        email: str,
        display_name: str = "",
        phone: str = "",
        chat_handle: str = "",
    ) -> RecipientOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            created = create_recipient(
                tenant=tenant,
                actor=actor,
                email=email,
                display_name=display_name,
                phone=phone,
                chat_handle=chat_handle,
            )
            return RecipientOut.from_orm(with_allowed_acts([created], actor)[0])

    @server.tool(
        name="update_recipient",
        description=contract_of(update_recipient_route),
    )
    def update_recipient_tool(
        ctx: Context[Any],
        recipient_id: UUID,
        email: str | None = None,
        display_name: str | None = None,
        phone: str | None = None,
        chat_handle: str | None = None,
    ) -> RecipientOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            recipient = get_recipient(
                tenant=tenant, recipient_id=recipient_id, org=acting.org, actor=actor
            )
            updated = update_recipient(
                tenant=tenant,
                actor=actor,
                recipient=recipient,
                email=email,
                display_name=display_name,
                phone=phone,
                chat_handle=chat_handle,
            )
            return RecipientOut.from_orm(with_allowed_acts([updated], actor)[0])

    @server.tool(
        name="archive_recipient",
        description=contract_of(archive_recipient_route),
    )
    def archive_recipient_tool(ctx: Context[Any], recipient_id: UUID) -> RecipientOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            recipient = get_recipient(
                tenant=tenant, recipient_id=recipient_id, org=acting.org, actor=actor
            )
            pressed = archive_recipient(tenant=tenant, actor=actor, recipient=recipient)
            return RecipientOut.from_orm(with_allowed_acts([pressed], actor)[0])

    @server.tool(
        name="restore_recipient",
        description=contract_of(restore_recipient_route),
    )
    def restore_recipient_tool(ctx: Context[Any], recipient_id: UUID) -> RecipientOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            recipient = get_recipient(
                tenant=tenant, recipient_id=recipient_id, org=acting.org, actor=actor
            )
            pressed = restore_recipient(tenant=tenant, actor=actor, recipient=recipient)
            return RecipientOut.from_orm(with_allowed_acts([pressed], actor)[0])

    # --- preferences: five verbs, no settable column ------------------------

    @server.tool(
        name="list_preferences",
        description=contract_of(list_preferences_route),
    )
    def list_preferences_tool(
        ctx: Context[Any],
        recipient_id: UUID,
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> PreferencePage:
        with tool_call(ctx) as acting:
            recipient = get_recipient(
                tenant=acting.tenant,
                recipient_id=recipient_id,
                org=acting.org,
                actor=acting.actor(),
            )
            preferences: QuerySet[ChannelPreference] = list_preferences(
                tenant=acting.tenant, recipient=recipient, org=acting.org, actor=acting.actor()
            )
            page = cursor_page(
                preferences,
                tenant=acting.tenant,
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )
            return PreferencePage(
                items=[PreferenceOut.from_orm(row) for row in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(
        name="grant_consent",
        description=contract_of(grant_consent_route),
    )
    def grant_consent_tool(
        ctx: Context[Any], recipient_id: UUID, channel: str = Channel.EMAIL.value
    ) -> PreferenceOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            recipient = get_recipient(
                tenant=tenant, recipient_id=recipient_id, org=acting.org, actor=acting.actor()
            )
            return PreferenceOut.from_orm(
                grant_consent(
                    tenant=tenant, actor=acting.actor(), recipient=recipient, channel=channel
                )
            )

    @server.tool(
        name="revoke_consent",
        description=contract_of(revoke_consent_route),
    )
    def revoke_consent_tool(
        ctx: Context[Any], recipient_id: UUID, channel: str = Channel.EMAIL.value
    ) -> PreferenceOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            recipient = get_recipient(
                tenant=tenant, recipient_id=recipient_id, org=acting.org, actor=acting.actor()
            )
            return PreferenceOut.from_orm(
                revoke_consent(
                    tenant=tenant, actor=acting.actor(), recipient=recipient, channel=channel
                )
            )

    @server.tool(
        name="set_quiet_hours",
        description=contract_of(set_quiet_hours_route),
    )
    def set_quiet_hours_tool(
        ctx: Context[Any],
        recipient_id: UUID,
        channel: str = Channel.EMAIL.value,
        start: time | None = None,
        end: time | None = None,
        timezone_name: str = "UTC",
    ) -> PreferenceOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            recipient = get_recipient(
                tenant=tenant, recipient_id=recipient_id, org=acting.org, actor=acting.actor()
            )
            return PreferenceOut.from_orm(
                set_quiet_hours(
                    tenant=tenant,
                    actor=acting.actor(),
                    recipient=recipient,
                    channel=channel,
                    start=start,
                    end=end,
                    timezone_name=timezone_name,
                )
            )

    @server.tool(
        name="suppress_recipient",
        description=contract_of(suppress_recipient_route),
    )
    def suppress_recipient_tool(
        ctx: Context[Any], recipient_id: UUID, channel: str = Channel.EMAIL.value
    ) -> PreferenceOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            recipient = get_recipient(
                tenant=tenant, recipient_id=recipient_id, org=acting.org, actor=acting.actor()
            )
            return PreferenceOut.from_orm(
                suppress_recipient(
                    tenant=tenant, actor=acting.actor(), recipient=recipient, channel=channel
                )
            )

    @server.tool(
        name="unsuppress_recipient",
        description=contract_of(unsuppress_recipient_route),
    )
    def unsuppress_recipient_tool(
        ctx: Context[Any], recipient_id: UUID, channel: str = Channel.EMAIL.value
    ) -> PreferenceOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            recipient = get_recipient(
                tenant=tenant, recipient_id=recipient_id, org=acting.org, actor=acting.actor()
            )
            return PreferenceOut.from_orm(
                unsuppress_recipient(
                    tenant=tenant, actor=acting.actor(), recipient=recipient, channel=channel
                )
            )
