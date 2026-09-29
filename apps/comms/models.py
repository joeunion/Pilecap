"""What this product has said to a person, and what it is allowed to say.

Four tables carry the message, and the split between them is the whole design
(`DeliveryPolicy` and `SuppressionSurge` sit beside them — how hard to try, and
a note on the one occasion the wall stopped behaving):

* **`Recipient`** — somebody a message can be addressed to. A `User` is not
  enough: most people a product emails are contacts, leads and customers who
  have never signed in, and the `user` foreign key is nullable precisely so
  that the *same* row survives a contact becoming an account. Closed contacts
  are `archived_at`, never deleted: every `Message` ever sent points here.
* **`MessageTemplate`** — what gets said, per tenant, **versioned**. A template
  is never edited in place (C1-1b): a change is a new row at `version + 1`, so
  a message sent in March can still be read back exactly as it was sent.
* **`ChannelPreference`** — what this person has agreed to hear on this
  channel: marketing consent, quiet hours, and a suppression that refuses
  everything. It is a row per recipient per channel, and its **absence** is
  itself an answer (no consent yet, no quiet hours, not suppressed).
* **`Message`** — the per-attempt log. One row per `send()`, including the ones
  that were refused, because "we did not email them, and here is why" is a
  question a support agent and an auditor both ask.
* **`MessageEngagement`** — what a provider says a person then DID with a
  message: opened it, clicked something in it. Append-only, and deliberately a
  second population rather than more columns on `Message` (ADR comms-9): a
  delivery is witnessed, an open is *inferred*, and one table holding both
  would launder the inference into a fact.
* **`Device`** — a handset or a browser a person has let this product push to.
  The push channel's address book, and a table rather than a column on
  `Recipient` because push is the one kind of reach a person has *several* of
  at once: a phone, a tablet, a laptop browser, each with its own registration
  token, each rotated by the platform without anybody asking.

**Scoping.** `Recipient`, `ChannelPreference` and `Message` are `OrgScopedModel`
— a message belongs to the part of the tenant that sent it, and a dealer must
not read the group's correspondence. The cost is stated rather than discovered:
cross-branch messaging fails closed, so a product that genuinely wants one
tenant-wide contact book asks for a named policy rather than a widened read.
`MessageEngagement` is org-scoped too and takes its branch from the message it
hangs off rather than from the hat that recorded it (`derive_org_from`), which
matters because the hat a status webhook acts under is the tenant's root.
`Device` does the same one table further out, from the `Recipient` it belongs
to: a device belongs wherever the contact belongs, and a registration made
under the root hat must not land where the branch that owns the contact cannot
read it.
`MessageTemplate`, `DeliveryPolicy` and `SuppressionSurge` are
`TenantScopedModel`: templates and policies are the tenant's house style and
every branch sends under the same ones, and a surge is a fact about one of the
tenant's transports rather than about a branch.

**Status transitions live in `services.py`** and nowhere else — not in `save()`,
not in a signal, not in the admin. `delivered` and `bounced` are the two the
product cannot observe on its own: they arrive afterwards, from the transport,
through the status webhook C2-comms-a landed, and `record_delivery_status` is
the only function that writes them.

**Retention (house rule 31, ADR core-13).** Seven of the eight tables here
declare `unbounded`, and that near-uniformity is a finding rather than a shrug
— it is what this app's foreign keys already said, written down where a check
can read it. (`MessageEngagement` is the seventh and declares `append_only`,
which is a statement about rewriting rather than about ageing; its own note
says why `bounded` is the near-miss it is not.)
Every scoped model in this tree PROTECTs off `Tenant` and `Organization`, and
inside comms `Message` PROTECTs both `Recipient` and `MessageTemplate` and
`Device` PROTECTs `Recipient` for the same reason, so
**there is no cascade anywhere in this app for a `bounded` declaration to name**
that hangs off a row which actually dies (the two CASCADEs,
`ChannelPreference.recipient` and `MessageEngagement.message`, both hang off
rows that archive or stay rather than die). Nothing here is `purged` either, and that is a
decision with a date on it: the retention ruling for a sending record does not
exist yet — that is a standing open item — and building a sweeper ahead of
the ruling is the defect rule 30 exists to catch pointed the other way. Each
declaration below therefore carries the sentence a reviewer can disagree with
and the dated trigger that would reopen it.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import ClassVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.db import models

from apps.core.fields import EncryptedCharField
from apps.core.lifecycle import Lifecycle, LifecycleKind
from apps.core.log import get_logger
from apps.core.models import Archivable, OrgScopedModel, TenantScopedModel

log = get_logger("apps.comms.models")


class Channel(models.TextChoices):
    """The ways this product can reach a person.

    Module level rather than nested on one model, because three tables use the
    same set and a `ChannelPreference.channel` that could drift from a
    `Message.channel` would be a consent check that quietly matched nothing.

    Only `EMAIL` is built in. The others are named here because the *preference*
    exists before the transport does — a person can tell you not to text them
    before you have an SMS provider — and `send()` refuses any channel with no
    registered transport, so naming one costs nothing and hides nothing.

    **`CHAT`, not `SLACK`** (ADR comms-6). A channel is a *kind* of reach, and
    the kind is "a message in the chat tool this person's company lives in".
    Slack, Teams and Google Chat are three vendors of one kind, and a member
    named after one of them would have forced a fourth column the first time a
    product used Teams — or, worse, a Teams message filed under `slack`, which
    is a consent row that means nothing. Vendors are `Connection` rows and
    provider slugs; kinds are this enum, and it stays short.
    """

    EMAIL = "email", "Email"
    SMS = "sms", "SMS"
    CHAT = "chat", "Chat"
    PUSH = "push", "Push"


class BounceKind(models.TextChoices):
    """Whether a bounce is a fact about the **address** or about the weather.

    ADR comms-8 collapsed `bounced`, `complained` and `rejected` onto one status
    because all three mean *stop mailing this address*, and one suppression rule
    could then read one column. But that collapse had a cost:
    a *soft* bounce — a full mailbox, a greylisting server, an ESP that retried
    for a day and gave up — silenced a healthy recipient tenant-wide, for ever,
    on the strength of a bad afternoon. And because the status arrives over a
    webhook, that made the wall a weapon.

    So the record keeps the collapse and the **action** splits: `HARD` is a fact
    about the address and suppresses it; `SOFT` is recorded, is readable on the
    message log, and acts on nothing. The retry-budget half — "twelve softs in a
    week is a hard" — stays ADR comms-8's trigger, now narrower.

    Module level rather than nested on `Message` for the same reason `Channel`
    is: `providers.py` maps a transport's vocabulary onto it and `services.py`
    decides on it, and a kind nested inside the row would be imported through
    the row by both.
    """

    HARD = "hard", "Hard"
    SOFT = "soft", "Soft"


class Category(models.TextChoices):
    """Why this message is being sent, which is what consent turns on.

    The line is not a marketing preference, it is a legal one: a transactional
    message is one the person's own action asked for (a receipt, a password
    reset, an invitation they are expecting) and it goes out by default;
    anything else needs them to have said yes.
    """

    TRANSACTIONAL = "transactional", "Transactional"
    MARKETING = "marketing", "Marketing"


# --- the quiet window, as arithmetic rather than as columns ----------------------
#
# **Three module-level functions, and they moved here at T4 rather than being
# copied.** `ChannelPreference` has carried this window since ADR comms-10 and
# is still its only *column* holder; what changed is that a SECOND caller
# appeared — the tenant quiet-hours seam (`services.tenant_quiet_window`, RUL-2's
# empty seam) asks the same two questions of a window that has no row at all.
#
# A second implementation is the drift `SENDABLE` had to come back and fix once
# already and that `ChannelPreference`'s own note above records. So the
# arithmetic is here, keyed on nothing but three values and an instant, and both
# holders call it — which is what makes "the tenant's window and the person's
# window mean the same thing" a fact rather than a claim. The DST clause, the
# exclusive end, the wrap across midnight and the round-up to the whole second
# are all decided once, below, and their reasons travel with them.


def quiet_zone(name: str, *, where: str = "") -> ZoneInfo:
    """One timezone name, resolved — falling back to UTC rather than raising.

    An unknown name must not make the product unable to send at all: a bad
    string in one row (or in one product's seam) is a misconfiguration to log,
    not an outage. `where` is what the log line names, so a reader can tell a
    preference row from a tenant window.
    """
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        log.warning("comms.quiet_hours.unknown_timezone", where=where, zone=str(name))
        return ZoneInfo("UTC")


def is_quiet_at(*, start: time | None, end: time | None, zone: ZoneInfo, at: datetime) -> bool:
    """Whether `at` falls inside the window, in the window's own timezone.

    A window that wraps midnight (22:00 → 07:00) is the normal case and is why
    this is not a single comparison. `start == end` is not a zero-length window
    and not an all-day one: it is a window nobody meant to configure, and it is
    read as no window at all.
    """
    if start is None or end is None or start == end:
        return False
    local: time = at.astimezone(zone).time()
    if start < end:
        return start <= local < end
    return local >= start or local < end


def quiet_opens_in(
    *, start: time | None, end: time | None, zone: ZoneInfo, at: datetime
) -> timedelta:
    """How long until the window ends. **Zero when it is not shut.**

    The arithmetic half of ADR comms-10: quiet hours became a delay, and a delay
    needs a duration. `at` is the moment the wall judged and the answer is
    measured from it, so the refusal's timestamp and the timer's length describe
    the same instant.

    **Zero is a real answer**, not a failure: the window closed between the
    wall's judgement and this call. A zero-length deferral makes the run
    re-judge immediately rather than inventing a wait — the same self-correction
    the post-sleep recheck performs a moment later.

    Declared limit, stated where it is created: a closing hour that falls in a
    DST fold resolves to the first of the two local instants (`fold=0`). Once a
    year, in the zones that do it, a deferral can end an hour early — at which
    point the post-sleep wall refuses again, temporally, and the run records
    that it did rather than mailing anybody inside the window.
    """
    if end is None or not is_quiet_at(start=start, end=end, zone=zone, at=at):
        return timedelta(0)
    local = at.astimezone(zone)
    # The next occurrence of the window's closing hour. `end` is exclusive, and
    # a wrapping window (22:00 → 07:00) judged at 22:30 closes tomorrow morning
    # while the same window judged at 03:00 closes this morning — which is why
    # this is a date decision and not a subtraction.
    day = local.date() if local.time() < end else local.date() + timedelta(days=1)
    remaining = datetime.combine(day, end, tzinfo=zone) - at
    if remaining <= timedelta(0):
        return timedelta(0)
    # **Rounded up to the whole second, and it is not cosmetic.** The caller
    # turns this into an integer number of seconds for a Temporal timer, and
    # truncation would wake the run a fraction of a second before the window
    # closes — where the wall refuses again and the deferral is spent on
    # nothing. Late by up to a second is invisible; early by a microsecond is a
    # message that never goes out.
    return timedelta(seconds=-(-remaining // timedelta(seconds=1)))


class Recipient(OrgScopedModel, Archivable):
    """Somebody this product can address. Not necessarily a user.

    Written only by `services.create_recipient` / `update_recipient` /
    `archive_recipient` / `restore_recipient` — never by a door and never by the
    bare manager outside a fixture, which is what makes the audit row and the
    org-scoping unavoidable rather than customary.

    **Archivable** (`core.models.Archivable`): closing a contact is
    `archived_at` + `archived_by`, and `for_tenant()` leaves a closed contact
    out of every read that does not widen with `.including_archived()` /
    `.archived_only()`. It is **not** a consent decision and it does not stop a
    send — "stop contacting this person" is `ChannelPreference.suppressed_at`,
    which is per-channel and is enforced inside `send()` where no caller can
    reach around it. Archiving a recipient a product still emails would be a
    consent wall in a second place, disagreeing with the first.
    """

    #: ADR core-13. **Archived, never deleted — so the table is unbounded and
    #: says so.** `bounded` would be the tempting kind and it is the wrong one:
    #: `tenant` and `organization` are both PROTECT (`core.models`), and every
    #: `Message` PROTECTs off this row, so nothing cascades here from anywhere
    #: and there is no parent whose death takes these rows with it. Closing a
    #: contact is `archived_at`, a status transition, exactly as closing a
    #: tenant is — the same argument `core.Tenant` makes about itself.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.UNBOUNDED,
        reason=(
            "the contact book, including the contacts nobody writes to any more. "
            "Every `Message` ever sent points at this row and PROTECTs it, so "
            "'who did we email in March' is unanswerable from a deleted recipient; "
            "leaving the working contact book is `archived_at`, never a delete."
        ),
        trigger=(
            "2026-08-24 — the same one `Message` carries, and for the same reason: "
            "first tenant past 100k messages, or the first compliance ask. A "
            "recipient cannot be swept while a message points at it, so whatever "
            "ruling lands on the message log decides this table too, in that order."
        ),
    )

    email = models.EmailField(max_length=254)
    #: The addresses the other channel *kinds* reach. Blank rather than
    #: nullable, and deliberately not validated into shape here: a phone number
    #: is E.164 in one country's product and seven digits in another's, and the
    #: transport that dials it is the thing that knows. What the product
    #: guarantees is one row per person carrying every way to reach them, so a
    #: policy that escalates from SMS to email is reading one contact and not
    #: joining two. An empty address is a fail-closed refusal at send time
    #: (`providers.ConnectionChannel`), never a message sent to nowhere.
    phone = models.CharField(max_length=32, blank=True, default="")
    chat_handle = models.CharField(max_length=255, blank=True, default="")
    #: Set when this person also has an account. Nullable and `SET_NULL`:
    #: deleting an account must not delete the record of what was sent to the
    #: person, and a contact who never signs up still needs a row.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="comms_recipients",
    )
    display_name = models.CharField(max_length=200, blank=True)

    class Meta(OrgScopedModel.Meta):
        verbose_name = "recipient"
        verbose_name_plural = "recipients"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "organization", "email"],
                name="comms_recipient_unique_email_per_org",
            ),
        ]

    def __str__(self) -> str:
        return self.display_name or self.email


class MessageTemplate(TenantScopedModel):
    """What gets said — per tenant, per channel, versioned, never edited.

    `context_schema` is a small JSON-Schema object (`{"required": [...],
    "properties": {"name": {"type": "string"}}}`) and `send()` validates the
    caller's context against it *before* anything is written. A template whose
    body reads `{{ invoice_number }}` and a caller who forgot to pass one is a
    400 with the field named, not an email that says "Invoice None".
    """

    #: ADR core-13, D9. **Versioned config: a retired version stays readable BY
    #: DESIGN, so the reason writes itself.** `retire_template` moves
    #: `is_active` and nothing else, `revise_template` writes a new row at
    #: `version + 1`, and every `Message` PROTECTs the row it was rendered from.
    #: A sweeper over retired versions would delete the only copy of what was
    #: actually said to somebody — which is the whole point of versioning.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.UNBOUNDED,
        reason=(
            "versioned config, and the version is the archive. 'What did the March "
            "receipt actually say' is answered by re-reading the row a March "
            "`Message` still points at; a retired version is retired from "
            "`send(template=…)` resolution, never from the table. Growth is one row "
            "per revision per tenant — bounded by how often a human edits copy."
        ),
        trigger=(
            "2026-08-24 — the first tenant whose template history is large enough to "
            "be a cost (a product generating versions from a UI rather than from a "
            "person), or a ruling that a version no live `Message` references may be "
            "archived; either turns this into a `purged` declaration with a callable "
            "and a `ScheduleDeclaration` behind it."
        ),
    )

    name = models.CharField(max_length=100)
    version = models.PositiveIntegerField(default=1)
    channel = models.CharField(max_length=16, choices=Channel.choices, default=Channel.EMAIL)
    category = models.CharField(
        max_length=16, choices=Category.choices, default=Category.TRANSACTIONAL
    )
    subject = models.CharField(max_length=255, blank=True)
    body = models.TextField()
    context_schema = models.JSONField(default=dict, blank=True)
    #: A retired version stays readable — every `Message` that used it points at
    #: it — but stops being what `send(template="…")` resolves to.
    is_active = models.BooleanField(default=True)

    class Meta(TenantScopedModel.Meta):
        verbose_name = "message template"
        verbose_name_plural = "message templates"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "name", "version"],
                name="comms_template_unique_version_per_name_per_tenant",
            ),
        ]
        indexes = [
            # Re-added by hand: this list SHADOWS `TenantScopedModel.Meta`'s
            # inherited composite (Django does not merge Meta.indexes down an
            # inheritance chain), and the model's default ordering is still
            # `-created_at`. ADR core-11; rule 37's coverage edge.
            models.Index(fields=["tenant", "-created_at"], name="messagetemplate_recency"),
            models.Index(fields=["tenant", "name", "-version"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} v{self.version}"


class DeliveryPolicy(TenantScopedModel):
    """How hard to try, and on what, before giving up. **Escalation as data.**

    A policy is an ordered list of steps — *text this person, wait ten minutes,
    then email them* — and it is a row rather than a branch in `send()` because
    the product people who decide "ten minutes" are not the people who deploy.
    `send(policy="oncall")` reads it; `workflows.DeliverMessageWorkflow`
    interprets a **snapshot** of it (rule 9), so revising a policy never reaches
    into a run already in flight.

    `TenantScopedModel` and not `OrgScopedModel`, the same call `MessageTemplate`
    makes and for the same reason: a policy is the tenant's house style for how
    urgently it chases people, and a branch that could write its own would be a
    branch that could decide to text customers at midnight. The *messages* a
    policy produces are org-scoped, because those belong to whoever sent them.

    **Versioned like a template, never edited.** `revise_policy` writes a new
    row at `version + 1`; `retire_policy` moves `is_active` and nothing else.
    Every `Message` records the name and version it was sent under, so "what did
    the escalation look like in March" survives every change since.

    `steps` is JSON rather than a table, and that is a real trade with a stated
    reason: a step has no identity of its own — nothing points at one, nothing
    queries across them, and a step list is read whole or not at all. What JSON
    costs is validation, so `services._policy_steps` is the one place a step is
    checked and every write goes through it. What a table would have cost is a
    join on the send path and a second versioning story for the rows.
    """

    #: ADR core-13, D9. **The same declaration `MessageTemplate` carries, for
    #: the same reason** — this is the other half of the versioned-config pair.
    #: `revise_policy` writes `version + 1`, `retire_policy` moves `is_active`,
    #: and a `Message` records the policy name and version it ran under. The
    #: difference from the template is that nothing PROTECTs a policy row, so
    #: the promise here rests on the *reason* alone rather than on a foreign
    #: key — which is exactly the case a declaration exists to make visible.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.UNBOUNDED,
        reason=(
            "versioned config, and the version is the archive. 'What did the "
            "escalation look like in March' is answered by reading the row the "
            "March `Message` names by name and number — and unlike a template, no "
            "foreign key holds this one in place, so deleting a retired policy "
            "would silently strand that answer rather than refuse."
        ),
        trigger=(
            "2026-08-24 — the first tenant whose policy history is large enough to "
            "be a cost, or a ruling that a version no `Message` names may be swept; "
            "either one turns this into a `purged` declaration, and the sweeper it "
            "then needs has to read `Message.policy_name`/`policy_version` rather "
            "than `is_active`, because retired is not the same as unreferenced."
        ),
    )

    name = models.CharField(max_length=100)
    version = models.PositiveIntegerField(default=1)
    #: A retired version stays readable — every `Message` that ran under it
    #: points at it by name and number — and stops being what
    #: `send(policy="…")` resolves to.
    is_active = models.BooleanField(default=True)
    #: `[{"channel": …, "template": …, "wait_seconds": …, "escalate_when": …}]`,
    #: in order. Written only through the services, which validate every field
    #: against the closed sets before the row is saved.
    steps = models.JSONField(default=list, blank=True)

    class Meta(TenantScopedModel.Meta):
        verbose_name = "delivery policy"
        verbose_name_plural = "delivery policies"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "name", "version"],
                name="comms_policy_unique_version_per_name_per_tenant",
            ),
        ]
        indexes = [
            # Re-added by hand: this list SHADOWS `TenantScopedModel.Meta`'s
            # inherited composite (Django does not merge Meta.indexes down an
            # inheritance chain), and the model's default ordering is still
            # `-created_at`. ADR core-11; rule 37's coverage edge.
            models.Index(fields=["tenant", "-created_at"], name="deliverypolicy_recency"),
            models.Index(fields=["tenant", "name", "-version"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} v{self.version}"


class ChannelPreference(OrgScopedModel):
    """What this person has agreed to hear on this channel.

    Three independent facts, deliberately not collapsed into one status column:

    * **consent** — `marketing_consented_at` with `marketing_revoked_at` after
      it meaning "they changed their mind". Two timestamps rather than a
      boolean, because "when did they agree" is the question a regulator asks
      and a boolean cannot answer it;
    * **quiet hours** — a local window in which nothing but transactional
      traffic goes out. Stored with its own timezone name, because the window
      belongs to the *person*, not to the server;
    * **suppression** — `suppressed_at`, which refuses everything on this
      channel including transactional. A hard bounce, a spam complaint or a
      person asking to be left alone entirely.
    """

    #: ADR core-13. **This table IS the compliance mechanism, so deleting a row
    #: is not retention — it is the re-send.** `suppressed_at` and the consent
    #: pair are read inside `send()`, where no caller can reach around them, and
    #: the *absence* of a row is itself an answer ("not suppressed"). A sweeper
    #: over old preference rows is therefore a machine for re-emailing people
    #: who asked to be left alone, and it would leave no trace that it had.
    #:
    #: `bounded` is the near-miss and it is worth naming: `recipient` really is
    #: CASCADE, so these rows cannot outlive their `Recipient`. But `Recipient`
    #: is itself unbounded and archives rather than dies, so that cascade is a
    #: lifecycle that never fires — declaring `bounded` here would say the
    #: question is settled by a parent's death that never comes, and would have
    #: nowhere to put the sentence above.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.UNBOUNDED,
        reason=(
            "consent and suppression are enforced by the PRESENCE of this row, so "
            "deleting one grants a permission nobody granted: a swept "
            "`suppressed_at` is how a product starts emailing somebody who said "
            "stop, and a swept `marketing_revoked_at` is how it forgets that they "
            "did. 'When did they agree' is the question a regulator asks, and it is "
            "unanswerable from a deleted row. Growth is one row per recipient per "
            "channel and is bounded by the contact book, not by traffic."
        ),
        trigger=(
            "2026-08-24 — a ruling that an erased person's suppression may go with "
            "them, which is a genuine conflict between two obligations (erase me / "
            "do not contact me) and is settled by a lawyer, not by a sweeper. Until "
            "then the only legal way out is the `recipient` CASCADE, and "
            "`Recipient` does not take it."
        ),
    )

    recipient = models.ForeignKey(
        Recipient,
        on_delete=models.CASCADE,
        related_name="preferences",
    )
    channel = models.CharField(max_length=16, choices=Channel.choices)

    marketing_consented_at = models.DateTimeField(null=True, blank=True)
    marketing_revoked_at = models.DateTimeField(null=True, blank=True)

    quiet_hours_start = models.TimeField(null=True, blank=True)
    quiet_hours_end = models.TimeField(null=True, blank=True)
    quiet_hours_timezone = models.CharField(max_length=64, default="UTC")

    #: Nothing at all goes to this address on this channel. Set by a hard
    #: bounce, a spam complaint, or the person asking.
    suppressed_at = models.DateTimeField(null=True, blank=True)

    class Meta(OrgScopedModel.Meta):
        verbose_name = "channel preference"
        verbose_name_plural = "channel preferences"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "recipient", "channel"],
                name="comms_preference_unique_channel_per_recipient",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(quiet_hours_start__isnull=True, quiet_hours_end__isnull=True)
                    | models.Q(quiet_hours_start__isnull=False, quiet_hours_end__isnull=False)
                ),
                name="comms_preference_quiet_hours_are_a_window",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.recipient} · {self.channel}"

    @property
    def has_marketing_consent(self) -> bool:
        """Whether they have said yes and not since said no."""
        if self.marketing_consented_at is None:
            return False
        if self.marketing_revoked_at is None:
            return True
        return self.marketing_revoked_at < self.marketing_consented_at

    # --- the quiet window, read off its own three columns -------------------
    #
    # Derived properties over this row's own fields, which is what the model
    # layer is for and where `has_marketing_consent` — the consent half of the
    # same wall — already lives. They moved here from `services.py` with ADR
    # comms-10, when a second question about the window appeared: quiet hours
    # stopped being a kill switch and became a delay, so *when does it open* now
    # matters as much as *is it shut*, and two answers derived from three
    # columns in two modules is the drift SEC-R1b had to come back and fix in
    # `SENDABLE`. One row, one definition, and no way for the refusal and the
    # deferral to disagree about which clock they are measured on.

    def _quiet_zone(self) -> ZoneInfo:
        """The timezone this person's window is written in.

        An unknown name falls back to UTC rather than raising: a bad string in
        one preference row must not make the product unable to send at all.
        """
        return quiet_zone(self.quiet_hours_timezone, where=f"preference {self.pk}")

    def is_quiet_at(self, at: datetime) -> bool:
        """Whether `at` falls inside this person's quiet window, in their timezone.

        The window belongs to the person, not to the server. A window that wraps
        midnight (22:00 → 07:00) is the normal case and is why this is not a
        single comparison.
        """
        return is_quiet_at(
            start=self.quiet_hours_start,
            end=self.quiet_hours_end,
            zone=self._quiet_zone(),
            at=at,
        )

    def quiet_opens_in(self, at: datetime) -> timedelta:
        """How long until the window ends. **Zero when it is not shut.**

        The arithmetic half of ADR comms-10: quiet hours became a delay, and a
        delay needs a duration. `at` is the moment the wall judged and the
        answer is measured from it, so the refusal's timestamp and the timer's
        length describe the same instant.

        **Zero is a real answer**, not a failure: the window closed between the
        wall's judgement and this call. A zero-length deferral makes the run
        re-judge immediately rather than inventing a wait — the same
        self-correction the post-sleep recheck performs a moment later.

        Declared limit, stated where it is created: a closing hour that falls in
        a DST fold resolves to the first of the two local instants (`fold=0`).
        Once a year, in the zones that do it, a deferral can end an hour early —
        at which point the post-sleep wall refuses again, temporally, and the
        run records that it did rather than mailing anybody inside the window.
        """
        return quiet_opens_in(
            start=self.quiet_hours_start,
            end=self.quiet_hours_end,
            zone=self._quiet_zone(),
            at=at,
        )


class Message(OrgScopedModel):
    """One attempt to say one thing to one person. **Including the refusals.**

    A refused send is a row here with `status=suppressed` and a
    `suppressed_reason`, not an exception and not a silence: the product needs
    to be able to answer "did we email them?" with "no, and here is why" rather
    than with nothing at all.

    The template is recorded three times over — the foreign key, the name and
    the version — and that is not redundancy. The key is how the body is
    re-rendered for delivery; the name and version are the durable answer to
    "what did we send", readable after a template is retired and without a join.
    """

    #: ADR core-13 — **the dated residual this declaration closes as a
    #: declaration and deliberately not as a build.** It has been open since
    #: `comms.Message` was found to have no retention policy; what
    #: was missing was never the sweeper, it was the RULING about how long a
    #: sending record is kept, and building a purge before that ruling exists
    #: would be rule 30's defect in the other direction — a reader for a policy
    #: nobody has written. So the trigger below is the residual's own, verbatim from
    #: `docs/product/queue.md`, carrying the date the decision was taken; the
    #: purge build stays on it ("declaration
    #: only; the purge build stays on the dated trigger").
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.UNBOUNDED,
        reason=(
            "the sending record is the product's evidence, including the refusals. "
            "'Did we email them?' answered with 'no, and here is why' is a row here "
            "with `status=suppressed`; a retention window on this table makes the "
            "oldest of those questions unanswerable, and a support agent and an "
            "auditor both ask them. Growth is real and is the largest in this app: "
            "one row per attempt, which is why the trigger below is a size as well "
            "as a ruling, and why the `Meta` indexes are what keep a big table's "
            "reads cheap in the meantime."
        ),
        trigger=(
            "2026-08-24 — first tenant past 100k messages, or the "
            "first compliance ask. Whichever arrives first is the day a retention "
            "ruling exists, and it turns this into a `purged` declaration with a "
            "callable and a `ScheduleDeclaration` behind it. Note the ordering "
            "`Recipient` and `MessageTemplate` impose: both are PROTECTed by this "
            "table, so nothing upstream can be swept until this one can."
        ),
    )

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENDING = "sending", "Sending"
        #: The transport accepted it. The furthest this product can see alone.
        SENT = "sent", "Sent"
        #: The transport says it arrived. Only `record_delivery_status` writes
        #: this, and only from a signed provider webhook.
        DELIVERED = "delivered", "Delivered"
        #: The transport says it did not arrive and will not: a hard bounce, a
        #: rejection, a spam complaint.
        BOUNCED = "bounced", "Bounced"
        FAILED = "failed", "Failed"
        SUPPRESSED = "suppressed", "Suppressed"
        #: Somebody changed their mind before it went out. Its own value
        #: rather than a `SuppressedReason`, and the distinction is the point:
        #: `suppressed` is the product refusing on the RECIPIENT's behalf —
        #: consent, quiet hours, a hard bounce — and a campaign report counting
        #: a cancelled send among those would be reporting an opt-out that never
        #: happened. This is the SENDER changing their mind, and only a message
        #: no transport has seen can reach it. Terminal: nothing transitions out.
        CANCELLED = "cancelled", "Cancelled"

    class SuppressedReason(models.TextChoices):
        NO_CONSENT = "no_consent", "No consent"
        QUIET_HOURS = "quiet_hours", "Quiet hours"
        SUPPRESSED = "suppressed", "Suppressed"

    recipient = models.ForeignKey(
        Recipient,
        on_delete=models.PROTECT,
        related_name="messages",
    )
    template = models.ForeignKey(
        MessageTemplate,
        on_delete=models.PROTECT,
        related_name="messages",
    )
    #: The template's name and version at send time, denormalised on purpose —
    #: see the class docstring.
    template_name = models.CharField(max_length=100)
    template_version = models.PositiveIntegerField()

    channel = models.CharField(max_length=16, choices=Channel.choices)
    category = models.CharField(max_length=16, choices=Category.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    suppressed_reason = models.CharField(
        max_length=32, choices=SuppressedReason.choices, blank=True
    )
    #: Which kind of bounce, when the status is `bounced` (ADR comms-9). Null
    #: on every other status, and null on the bounces recorded before this
    #: column existed — "nobody asked" and "it was soft" must never be the same
    #: value, because only one of them explains a suppression that did not
    #: happen. Nullable rather than blank for exactly that: an empty string
    #: would sort with the answers. A bounce recorded from here on always
    #: carries one, because a provider that does not classify gets
    #: `services.UNCLASSIFIED_BOUNCE`.
    #:
    #: DJ001 says "avoid null on a string field", and it is right almost
    #: everywhere: two spellings of absence is a bug factory. This field has
    #: only one — it is a **choice** column, `hard` or `soft`, and the empty
    #: string is not a member of the set, so there is no second spelling to
    #: confuse with the first. The rule is answered rather than silenced, the
    #: same way `connections.InboundWebhook.delivery_id` answers it.
    bounce_kind = models.CharField(  # noqa: DJ001
        max_length=8, choices=BounceKind.choices, null=True, blank=True
    )

    #: Which transport actually carried it, and what that transport called it.
    #: Both empty until a provider has accepted the message.
    provider = models.CharField(max_length=64, blank=True)
    provider_message_id = models.CharField(max_length=255, blank=True)

    #: The rendered subject, kept because it is what a human scanning the log
    #: reads. The **body is not kept**: it is re-rendered from the versioned
    #: template and the context below, which is the same string by construction
    #: (a template version is immutable) and one fewer copy of the customer's
    #: prose sitting in a table.
    subject = models.CharField(max_length=255, blank=True)
    context = models.JSONField(default=dict, blank=True)

    error = models.TextField(blank=True)

    #: When this message is due to go out, when a caller asked for later.
    #: **Nullable, and null is every message ever sent** — the column is
    #: expand-only (rule 22) and an existing row means exactly what it meant.
    #:
    #: It is a RECORD, not the schedule itself: the wait is a Temporal timer on
    #: the delivery run, which is what makes it survive a deploy, and this
    #: column is what makes it *visible*. T4 shipped the timer without the
    #: column and the cost was immediate — a support agent could not tell a
    #: message waiting six hours from one waiting six seconds without opening
    #: the Temporal UI, and "what goes out on Monday" had no answer in the
    #: product at all before this column shipped.
    #:
    #: The two can only disagree in one direction and it is the harmless one: a
    #: run cancelled or lost leaves the column saying what was *intended*, which
    #: is still the honest answer to "what was this row for". The run stays the
    #: authority on what will actually happen.
    send_at = models.DateTimeField(null=True, blank=True)

    #: The request that asked for this, and the thing that caused it. Same
    #: columns and same names the `Event` and `AuditEntry` rows carry, so one
    #: id joins the door, the audit row, the event and the message.
    correlation_id = models.CharField(max_length=64, blank=True, db_index=True)
    causation_id = models.CharField(max_length=64, blank=True)

    #: Which policy, at which version, and which step of it — denormalised for
    #: exactly the reason `template_name`/`template_version` are (see the class
    #: docstring): "why did this person get three messages" is answered by
    #: reading the rows, without a join and after the policy has been revised
    #: four times. All three stay empty on a `send()` with no policy, which is
    #: the ordinary case and is what makes that path unchanged.
    policy_name = models.CharField(max_length=100, blank=True, default="")
    policy_version = models.PositiveIntegerField(null=True, blank=True)
    #: 1-based, so step 1 reads as step 1. Nullable rather than defaulting to
    #: zero: "this message was not part of a policy" and "this was the zeroth
    #: step" must not be the same value.
    policy_step = models.PositiveIntegerField(null=True, blank=True)

    #: The durable run that is carrying this message, written by `send()` from
    #: the id the row implies (house rule 18) and read back by
    #: `record_delivery_status` when a provider's status arrives — that is the
    #: whole reason it is a column rather than a value rebuilt at the webhook.
    #: A rebuilt id would be right today and wrong the moment a second workflow
    #: could own a message, which is exactly what C2-comms-b does when one
    #: escalation run sends several.
    #: `default=""` is stated rather than left to Django's implicit empty
    #: string: house rule 22 reads the migration, and an `AddField` of a
    #: non-nullable column with no default in the file is the one that fails on
    #: a table that already has rows.
    delivery_workflow_id = models.CharField(max_length=255, blank=True, default="")

    sent_at = models.DateTimeField(null=True, blank=True)
    #: What the provider told us afterwards, and when. Both nullable because
    #: most of a message's life is spent not yet knowing: an ESP that never
    #: sends a status leaves a `sent` row saying `sent`, which is honest.
    delivered_at = models.DateTimeField(null=True, blank=True)
    bounced_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    suppressed_at = models.DateTimeField(null=True, blank=True)

    class Meta(OrgScopedModel.Meta):
        verbose_name = "message"
        verbose_name_plural = "messages"
        constraints = [
            # `"suppressed"` as a literal because the class body it names is not
            # in scope inside a nested `Meta` — and because a migration file
            # freezes the string anyway. It is `Status.SUPPRESSED`'s value.
            models.CheckConstraint(
                condition=(models.Q(status="suppressed") & ~models.Q(suppressed_reason=""))
                | (~models.Q(status="suppressed") & models.Q(suppressed_reason="")),
                name="comms_message_suppressed_carries_a_reason",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            # ALREADY the tenant-leading recency composite (it predates ADR
            # core-11 — perf-ledgers FINDING B built it here first). It is what
            # `TenantScopedModel.Meta` would otherwise have contributed, and
            # this list shadows that, so it carries the coverage for this model.
            # Do not remove it as a duplicate: rule 37 would name this model.
            models.Index(fields=["tenant", "-created_at"]),
        ]

    def __str__(self) -> str:
        return (
            f"{self.template_name} v{self.template_version} → {self.recipient_id} ({self.status})"
        )

    # The two relation reads `MessageOut` publishes, as properties rather than
    # as Pydantic field aliases — and that difference is load-bearing rather
    # than stylistic. An alias (`Field(alias="recipient.email")`) is a *name*,
    # and the MCP transport serialises a tool result **by alias**, so the
    # machine door answers `recipient.email` where the human door answers
    # `recipient_email`: one row, two key sets, which is a door-parity
    # disagreement no value-by-value test would catch. A property is a real
    # attribute on the row, so `from_attributes` finds it under one name and
    # both doors say the same thing.
    #
    # Neither costs a query: every read of this model goes through
    # `selectors.list_messages`, which selects both relations.

    @property
    def recipient_email(self) -> str:
        """Where this went, without the caller having to fetch the recipient."""
        return str(self.recipient.email)

    @property
    def organization_slug(self) -> str:
        """Which part of the tenant sent it — the slug an `X-Org` header names."""
        return str(self.organization.slug)


class MessageEngagement(OrgScopedModel):
    """Somebody opened it, or clicked something in it. **A provider's inference.**

    ADR comms-9's engagement half. One row per thing a transport told us a
    person did with a message, and the whole design is the wall between this
    table and `Message.status`:

    **An engagement never mutates the message row.** A delivery is a fact the
    transport can witness — it handed the mail to a server and the server took
    it. An *open* is an inference from a request for a tracking image, and on
    one of the two largest mail clients in the world it is not even that: Apple
    Mail Privacy Protection prefetches every image in every message a user
    receives, so a "false open" is not an edge case, it is the default. Folding
    the two into one column would launder that inference into a fact, and the
    first thing a product would do with the laundered column is derive
    `delivered` from it — which is the specific move ADR comms-9 rejects by
    name. Delivery truth lives on `Message`; read inference lives here; the two
    populations never write to each other.

    **`append_only = True`, and it follows from what the rows are.** This is
    witnessed history — "at 09:31 the provider said this message was opened" —
    and a fact that can be edited is not evidence. The declaration is read by
    house rule 20 (the static half) and by `BaseModel.save`/`.delete` (the
    runtime belt), which is what makes an update raise at the line that
    attempts it rather than at review.

    **`derive_org_from = "message"`, and it is load-bearing here** (C9). The
    hat a status webhook acts under is the tenant's ROOT — an ESP has no idea a
    branch exists — so an engagement stamped from the acting hat would land at
    the root while the message it is about lives in a branch, and the branch
    that sent the message could never read the engagement on it. The landing
    gate in `OrgScopedModel.clean()` refuses the mismatch; the service sets the
    organization from the message and never from the actor.

    **The key is the provider's own event id** (architect C4). An ESP worth
    integrating with redelivers, so `(message, provider_event_id, kind)` is
    unique and `record_engagement` hands the first row back on the second
    delivery. `kind` is in the key because one provider event id can carry an
    open and a click on some vendors, and collapsing them would silently lose
    the second.

    DECLARED RESIDUE, because it is a real one: a provider that reports no
    event id at all writes every engagement of one kind on one message under the
    empty string, so the SECOND genuine open on that message returns the first
    row and records nothing new. That is a deliberate trade — a table with no
    key at all would double every count under an ordinary retry, and the outer
    dedupe (`apps/connections`' `delivery_id` constraint) already covers every
    provider this template has met. Trigger: the first transport whose
    engagement webhooks carry no event id and whose repeated opens have to be
    counted separately, which is the day this grows a per-delivery discriminator
    rather than the day it drops the key.
    """

    #: `core.models.is_append_only` reads this; nothing outside this module may
    #: update or delete a row, and `BaseModel.save`/`.delete` refuse at the last
    #: possible moment for the whole declared population. This is the runtime
    #: belt; house rule 20 is the static half. Zero edits to `quality/rules.yaml`
    #: — the population is the declaration (ADR core-6).
    append_only: ClassVar[bool] = True

    #: ADR core-13, coherent with the line above rather than a second opinion
    #: about the same table: rule 20 asks "may a row be rewritten", rule 31 asks
    #: "what happens to these rows over TIME". `bounded` is the near-miss and is
    #: worth naming — `message` really is CASCADE, so these rows cannot outlive
    #: their `Message` — but `Message` is itself `unbounded` on its dated
    #: trigger, so that cascade is a lifecycle that never fires, and declaring
    #: `bounded` would settle this table's question by a parent's death that
    #: does not come. The same reasoning `ChannelPreference` records one class up.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.APPEND_ONLY,
        reason=(
            "this is the engagement record a campaign report is derived from, and it "
            "is witnessed history: 'the provider said this was opened at 09:31' is a "
            "fact about a moment, and a row of it that can be rewritten is not "
            "evidence of anything. Growth is real and is bounded by traffic rather "
            "than by the contact book — an ESP reporting opens and clicks can write "
            "several rows per message — which is why the trigger below is a size as "
            "well as a ruling, and why this table is the first place a comms "
            "retention ruling will actually bite."
        ),
        trigger=(
            "2026-08-24 — the first of: the sending record's own retention "
            "trigger firing (a retention ruling "
            "for the sending record, at which point THIS table is swept first "
            "because `Message` PROTECTs nothing here and the CASCADE runs the right "
            "way), or a deployment past ~10 million rows in this table. Whichever "
            "arrives first turns this into a `purged` declaration with a callable "
            "and a `ScheduleDeclaration` behind it. Note the ordering: engagement "
            "rows may be swept while their messages stay, and never the reverse."
        ),
    )

    #: The row's organization comes from the message, never from the acting hat.
    #: See the class docstring; the gate is `OrgScopedModel.clean()`.
    derive_org_from: ClassVar[str] = "message"

    class Kind(models.TextChoices):
        """What the provider says the person did. **Two members, and no third.**

        Nested rather than module level — the discipline `Message.Status`
        follows and for the same reason: exactly one table uses this set, and a
        kind lifted to module scope would read as a vocabulary other tables
        share.

        A spam complaint is deliberately not a member. A complaint is consent
        news, it is carried by `suppress_recipient` and
        `comms.message.complained`, and a `complained` engagement row would put
        it back inside the very collapse ADR comms-9 took it out of.
        """

        OPENED = "opened", "Opened"
        CLICKED = "clicked", "Clicked"

    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name="engagements",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)

    #: Which link, on a click. **`TextField` rather than `URLField`**: a tracked
    #: link is an ESP's redirector with the original URL and a signature encoded
    #: into it, routinely past `URLField`'s 200-character default, and a
    #: validator refusing one at `full_clean()` would drop a real click for
    #: being long. Empty on an open, and the constraint below holds that.
    url = models.TextField(blank=True, default="")

    #: When the PROVIDER says it happened, which is not when the row was
    #: written: `created_at` already answers the second question, and a webhook
    #: that arrived an hour late must not report the open as having happened an
    #: hour late. Defaulted in the service when the provider named no time.
    occurred_at = models.DateTimeField()

    #: The transport's own handle for this event — the key that makes a
    #: redelivery idempotent (C4). Blank when the provider named none; see the
    #: declared residue in the class docstring.
    provider_event_id = models.CharField(max_length=255, blank=True, default="")

    class Meta(OrgScopedModel.Meta):
        verbose_name = "message engagement"
        verbose_name_plural = "message engagements"
        # No `indexes` here on purpose: declaring any would SHADOW
        # `TenantScopedModel.Meta`'s `(tenant, -created_at)` recency composite
        # (Django does not merge `Meta.indexes` down an inheritance chain) and
        # this model would then owe house rule 37 a hand-re-added copy. The
        # unique constraint below already leads with `message`, which is the one
        # read this table has — "the engagements on this message".
        constraints = [
            # C4: one row per provider event per kind. `kind` is in the key
            # because a vendor may report an open and a click under one event
            # id, and two facts must not collapse into one row.
            models.UniqueConstraint(
                fields=["message", "provider_event_id", "kind"],
                name="comms_engagement_unique_provider_event",
            ),
            # `"clicked"` as a literal because the class body it names is not in
            # scope inside a nested `Meta` — and because a migration file freezes
            # the string anyway. It is `Kind.CLICKED`'s value. An `opened` row
            # carrying a URL would be a destination for an event that has none,
            # and every report counting "clicks to this link" would be wrong.
            models.CheckConstraint(
                condition=models.Q(kind="clicked") | models.Q(url=""),
                name="comms_engagement_url_is_a_clicks_own",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.message_id} {self.kind} @ {self.occurred_at:%Y-%m-%d %H:%M}"


class SuppressionSurge(TenantScopedModel):
    """An episode in which the suppression wall started firing like a weapon.

    **The tripwire's memory, and the reason the announcement is a transition
    rather than a stream** (ADR comms-9 (c), the announce-on-transition ruling
    of 2026-08-22). A denial-of-comms attempt through the status webhook looks
    like ordinary bounce traffic one row at a time; what it does not look like
    is twenty-five addresses silenced on one connection inside an hour. Crossing
    that opens a row here and says so once on the spine; the first recording
    that sees the trailing hour back under the threshold closes the row and says
    *that* once. Because the row is the memory, an attacker who re-probes cannot
    turn the alarm into a flood — a state that is already announced is not
    announced again.

    **It is not an off switch.** While a surge is open, suppression still
    suppresses: a tripwire that silently disabled the wall would be a worse
    weapon than the one it was watching for, and the whole design is that a
    human acts on an announced state (ADR comms-9's rejected alternative,
    written down).

    `TenantScopedModel` and not `OrgScopedModel`: a `Connection` is the tenant's,
    the system actor a verified webhook acts as is resolved at the tenant root,
    and a surge is a fact about a transport rather than about a branch.

    **Open rows move; closed rows are history.** `ended_at` and
    `suppression_count` are written while the episode is live — the count is the
    worst trailing hour seen so far, which is what a human triaging it wants —
    and nothing writes a row once `ended_at` is set. A second surge on the same
    connection is a second row, which is why the uniqueness below is conditional
    on being open rather than absolute.

    Not `append_only`: the population that declares it may never be updated at
    all (house rule 20), and this one legitimately is, while it is open. The
    narrower promise — closed rows are immutable — is a test, not a declaration,
    and saying so here is the honest version of the difference.
    """

    #: ADR core-13, ADR comms-9. **The tripwire's memory, and a memory that is
    #: swept is a tripwire an attacker can wait out.** A closed row is the
    #: record that an episode happened, how bad it got and when it ended; the
    #: announce-on-transition design depends on the row's existence to keep a
    #: re-probing attacker from turning the alarm into a flood, and a sweeper
    #: would restore exactly that. Not `bounded`: `connection` is PROTECT and
    #: `tenant` is PROTECT, so nothing cascades here from anywhere.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.UNBOUNDED,
        reason=(
            "incident history for a denial-of-comms attempt. 'Has this connection "
            "done this before' is the question that separates a bad afternoon at a "
            "provider from an attack, and it is unanswerable from a swept table. "
            "Growth is one row per episode per connection — a table that stays "
            "empty on a healthy deployment, which is also why it is cheap to keep."
        ),
        trigger=(
            "2026-08-24 — a deployment where surges are routine rather than "
            "exceptional, which would mean the threshold in `services` is wrong "
            "before it means this table needs sweeping: re-tune the tripwire first, "
            "and only then decide whether closed episodes older than an incident "
            "review's horizon may go."
        ),
    )

    connection = models.ForeignKey(
        "connections.Connection",
        on_delete=models.PROTECT,
        related_name="comms_suppression_surges",
    )
    #: When the trailing-hour count first crossed the threshold.
    started_at = models.DateTimeField()
    #: When a recording first saw the trailing hour back under it. Null while
    #: the surge is live, which is also what the partial uniqueness below reads.
    ended_at = models.DateTimeField(null=True, blank=True)
    #: The worst trailing-hour count observed while this episode was open. A
    #: `PositiveIntegerField` and never a float: it is a count of addresses.
    suppression_count = models.PositiveIntegerField(default=0)

    class Meta(TenantScopedModel.Meta):
        verbose_name = "suppression surge"
        verbose_name_plural = "suppression surges"
        constraints = [
            # One live episode per connection, enforced by the database rather
            # than by the service that reads before it writes: two status
            # webhooks landing on one connection at the same instant are two
            # transactions, and "no open row yet" is exactly the read a race
            # makes true twice. `ended_at` is the state, so the uniqueness is
            # conditional on it and a closed episode never blocks the next one.
            models.UniqueConstraint(
                fields=["tenant", "connection"],
                condition=models.Q(ended_at__isnull=True),
                name="comms_one_open_surge_per_connection",
            ),
        ]
        indexes = [
            # Re-added by hand: this list SHADOWS `TenantScopedModel.Meta`'s
            # inherited composite (Django does not merge Meta.indexes down an
            # inheritance chain), and the model's default ordering is still
            # `-created_at`. ADR core-11; rule 37's coverage edge.
            models.Index(fields=["tenant", "-created_at"], name="suppressionsurge_recency"),
            models.Index(fields=["tenant", "connection", "-started_at"]),
        ]

    def __str__(self) -> str:
        state = "open" if self.ended_at is None else "closed"
        return f"suppression surge on {self.connection_id} ({state})"


class Device(OrgScopedModel):
    """One handset (or browser) a person has let this product push to.

    **The push channel's address book, and the reason it is a table rather than
    a column on `Recipient`.** Every other kind of reach is one string per
    person — an email address, a phone number, a chat handle — and `Recipient`
    holds those inline for exactly that reason. Push is not one string: a person
    has a phone and a tablet and a laptop browser, each install mints its own
    registration token, and a token is rotated by the platform without anybody
    asking. A column would have made "reach this person" mean "reach whichever
    device registered last", which is the failure mode a notification product
    cannot have.

    **`derive_org_from = "recipient"`**, and it is the same argument
    `MessageEngagement` makes one table over (C9): a device belongs wherever the
    contact belongs. A registration arriving under the tenant's root hat would
    otherwise land at the root while the contact it is about lives in a branch,
    and the branch that owns the contact could never reach its own devices. The
    landing gate in `OrgScopedModel.clean()` refuses the mismatch and
    `services.register_device` sets the organization from the recipient, never
    from the actor.

    **`recipient` is `PROTECT`, exactly as `Message.recipient` is**, and that is
    what keeps this declaration honest: nothing in this app cascades, so no
    parent's death takes these rows with it, and the lifecycle below is
    `unbounded` rather than a `bounded` that would never fire.

    **The token is encrypted at rest and never leaves on the wire.** A push
    registration token is the capability to put a notification on somebody's
    lock screen; paired with a leaked server credential it is a hijacked
    channel, and there is no read for which the plaintext is the answer. So
    `push_token` is an `EncryptedCharField` (house rule 15's secret-at-rest
    clause, met rather than waived) and `DeviceOut` publishes the row's id and
    nothing of the token at all. Because Fernet carries a random IV, the
    ciphertext cannot be filtered or constrained — which is why the identity of
    a device is `push_token_hash`, a SHA-256 digest beside it. A name ending
    `_hash` is a digest and not a recoverable secret, which is what lets it be
    the unique column the re-registration read needs.

    **Invalidation is a state, never a delete.** A token the platform has
    retired, a person who signed out, a handset somebody sold: each sets
    `retired_at` and the row stays, because "we pushed to this device in
    March" is a question the message log's `provider_message_id` points back at.
    `selectors.list_active_devices` is the read the transport uses and it drops
    them.
    """

    #: ADR core-13. `unbounded`, and it is the same shape `Recipient` argues for
    #: rather than a fresh decision: `recipient` is PROTECT, `tenant` and
    #: `organization` are PROTECT on `core.models`, so nothing cascades here and
    #: there is no owning row whose death sweeps the table — `bounded` would be
    #: a lifecycle that never fires. A purge is genuinely available for this
    #: table (nothing points at a `Device`), and it is deliberately not declared
    #: here: `apps/comms` ships no `purged` declaration at all, because the
    #: RETENTION RULING a sweeper would implement does not exist, and
    #: `tests/test_lifecycle.py` holds that absence as a decision. Building the
    #: sweeper before the ruling is rule 30's defect pointed the other way.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.UNBOUNDED,
        reason=(
            "the push address book, including the installs nobody can reach any "
            "more. Growth is bounded by handsets rather than by traffic — one row "
            "per install per contact, and a re-registration of the same token "
            "updates the row it finds rather than adding a second — so this table "
            "is a small multiple of the contact book and never a multiple of the "
            "message log. Retiring an install is `retired_at`, a state, "
            "because the message that went to it is still in the log pointing here."
        ),
        trigger=(
            "2026-08-24 — the first of: the sending record's retention ruling landing for the "
            "sending record (a device is contact data and is swept under whatever "
            "window the contact book gets, never a narrower one of its own), or a "
            "deployment whose retired rows outnumber its live ones by ten to "
            "one, which is the shape that says installs churn faster than contacts "
            "and the table wants its own `purged` declaration with a callable and a "
            "`ScheduleDeclaration` behind it."
        ),
    )

    #: The row's organization comes from the contact, never from the acting hat.
    #: See the class docstring; the gate is `OrgScopedModel.clean()`.
    derive_org_from: ClassVar[str] = "recipient"

    class Platform(models.TextChoices):
        """What kind of thing is holding the token.

        Nested rather than module level — `Message.Status`'s discipline: exactly
        one table uses this set, and a platform lifted to module scope would read
        as a vocabulary other tables share.

        It is deliberately the KIND and not the vendor, for `Channel`'s reason
        (ADR comms-6): `ios` is the kind, and whether this deployment reaches it
        through FCM or through APNs directly is a `Connection` row and a provider
        slug. A member named after a gateway would have forced a second one the
        first time somebody changed gateway.
        """

        IOS = "ios", "iOS"
        ANDROID = "android", "Android"
        WEB = "web", "Web"

    recipient = models.ForeignKey(
        Recipient,
        on_delete=models.PROTECT,
        related_name="devices",
    )
    platform = models.CharField(max_length=16, choices=Platform.choices)

    #: The registration token itself, encrypted at rest. `max_length` is the
    #: PLAINTEXT bound (the column is unbounded text — see `EncryptedCharField`)
    #: and it is generous on purpose: an FCM registration token is around 160
    #: characters today, an APNs one 64, and a web-push subscription's endpoint
    #: is a URL with a key in it. A bound that refused a real token at
    #: `full_clean()` would drop a genuine registration for being long.
    push_token = EncryptedCharField(max_length=4096)

    #: The identity of the device, because the ciphertext beside it has no
    #: identity: Fernet carries a random IV, so two rows holding one token hold
    #: different bytes and `.filter(push_token=...)` matches nothing, ever. A
    #: SHA-256 hex digest of the token, written only by
    #: `services.register_device`, and the column the unique constraint below
    #: and the re-registration read both use.
    push_token_hash = models.CharField(max_length=64, editable=False)

    #: What the person calls this device, when the client bothered to say —
    #: "Ada's iPhone". Blank rather than nullable, like every other optional
    #: string in this app, and never used to address anything.
    label = models.CharField(max_length=100, blank=True, default="")

    #: Set when this install stops being reachable: the platform retired the
    #: token, the person signed out, the handset was sold. Not a consent
    #: decision and not a delete — "stop pushing to this person" is
    #: `ChannelPreference.suppressed_at` on the `push` channel, enforced inside
    #: `send()` where no caller can reach around it, exactly as
    #: `Recipient.archived_at` is not a consent decision either.
    retired_at = models.DateTimeField(null=True, blank=True)

    class Meta(OrgScopedModel.Meta):
        verbose_name = "device"
        verbose_name_plural = "devices"
        # No `indexes` here on purpose, for `MessageEngagement`'s reason:
        # declaring any would SHADOW `TenantScopedModel.Meta`'s
        # `(tenant, -created_at)` recency composite (Django does not merge
        # `Meta.indexes` down an inheritance chain) and this model would then
        # owe house rule 37 a hand-re-added copy. The unique constraint below
        # leads with `tenant`, and the transport's read narrows on `recipient`,
        # which the FK's own index serves.
        constraints = [
            # ONE ROW PER TOKEN PER TENANT. A registration token identifies an
            # install, and an install belongs to one person: a second row for
            # the same token would mean two contacts reachable at one lock
            # screen, and a push meant for one of them landing on the other.
            # Scoped to the tenant rather than globally because the same handset
            # may legitimately be a contact of two different products' tenants.
            models.UniqueConstraint(
                fields=["tenant", "push_token_hash"],
                name="comms_device_unique_push_token",
            ),
        ]

    def __str__(self) -> str:
        state = "retired" if self.retired_at is not None else "active"
        return f"{self.label or self.platform} for {self.recipient_id} ({state})"
