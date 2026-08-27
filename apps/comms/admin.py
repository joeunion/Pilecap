"""The staff door onto comms. Reading only.

House rule 21: every `ModelAdmin` on a scoped model inherits
`core.admin.ServiceModelAdmin`, which filters to the acting tenant and routes
every write through a service. All four tables here are **read-only from the
admin**, and that is the design rather than a shortcut:

* a `Message` is the record of what was said. Editing one would be editing
  history, and a support agent flipping a `suppressed` row to `sent` would be
  telling the product a lie it can never detect;
* a `MessageTemplate` is versioned and never edited in place — a change is a
  new row at `version + 1`, which is `services.revise_template`, not a form;
* a `ChannelPreference` is somebody's answer about being contacted. Granting
  consent from a staff form, with no record of the person actually agreeing, is
  the single worst write this app could offer. It is five **verb services**
  with an audit row each (`grant_consent`, `revoke_consent`, `set_quiet_hours`,
  `suppress_recipient`, `unsuppress_recipient`), and never a text field;
* a `Recipient` is contact data whose write door is `create_recipient` /
  `update_recipient` / `archive_recipient`.

C1-1b built all of those and this file stayed read-only, which is the point
worth stating: the services exist and the admin still does not offer them. A
form that granted consent would be a consent record with no consenting person
behind it, and the audit row it wrote would say a staff member's name.

So this file is what the admin is for here: finding out what happened.
"""

from __future__ import annotations

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from apps.comms.models import (
    ChannelPreference,
    DeliveryPolicy,
    Message,
    MessageTemplate,
    Recipient,
)
from apps.core.admin import ReadOnlyModelAdmin


@admin.register(Message)
class MessageAdmin(ReadOnlyModelAdmin[Message]):
    """What was said, to whom, and what happened to it."""

    list_display = (
        "created_at",
        "template_name",
        "template_version",
        "recipient",
        "channel",
        "status",
        "suppressed_reason",
    )
    list_filter = ("status", "channel", "category", "suppressed_reason")
    search_fields = (
        "template_name",
        "subject",
        "recipient__email",
        "provider_message_id",
        "correlation_id",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    def get_queryset(self, request: HttpRequest) -> QuerySet[Message]:
        return (
            super()
            .get_queryset(request)
            .select_related("tenant", "organization", "recipient", "template")
        )


@admin.register(MessageTemplate)
class MessageTemplateAdmin(ReadOnlyModelAdmin[MessageTemplate]):
    """Every version of every template, newest first."""

    list_display = ("name", "version", "channel", "category", "is_active", "updated_at")
    list_filter = ("channel", "category", "is_active")
    search_fields = ("name", "subject")
    ordering = ("name", "-version")

    def get_queryset(self, request: HttpRequest) -> QuerySet[MessageTemplate]:
        return super().get_queryset(request).select_related("tenant")


@admin.register(DeliveryPolicy)
class DeliveryPolicyAdmin(ReadOnlyModelAdmin[DeliveryPolicy]):
    """Every version of every escalation, newest first.

    Read-only like everything else here (house rule 21): a policy decides how
    hard the product chases people, and an admin form that could edit `steps` in
    place would be an escalation changed without an actor, an audit row, or a
    new version for the messages that already ran under the old one.
    """

    list_display = ("name", "version", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
    ordering = ("name", "-version")

    def get_queryset(self, request: HttpRequest) -> QuerySet[DeliveryPolicy]:
        return super().get_queryset(request).select_related("tenant")


@admin.register(Recipient)
class RecipientAdmin(ReadOnlyModelAdmin[Recipient]):
    """Who this tenant can address."""

    list_display = ("email", "display_name", "organization", "user", "archived_at", "created_at")
    list_filter = ("archived_at",)
    search_fields = ("email", "display_name")
    ordering = ("-created_at",)

    def get_queryset(self, request: HttpRequest) -> QuerySet[Recipient]:
        return super().get_queryset(request).select_related("tenant", "organization", "user")


@admin.register(ChannelPreference)
class ChannelPreferenceAdmin(ReadOnlyModelAdmin[ChannelPreference]):
    """What each person has agreed to hear. Read-only — see the module docstring."""

    list_display = (
        "recipient",
        "channel",
        "marketing_consented_at",
        "marketing_revoked_at",
        "suppressed_at",
    )
    list_filter = ("channel",)
    search_fields = ("recipient__email",)
    ordering = ("-updated_at",)

    def get_queryset(self, request: HttpRequest) -> QuerySet[ChannelPreference]:
        return super().get_queryset(request).select_related("tenant", "organization", "recipient")
