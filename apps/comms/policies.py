"""Who may say what to whom, and **when**. Policies are code; roles are data.

`core.authz.require(actor, "message.send", recipient)` finds these by
discovery — this file is never registered anywhere.

**Since T4 this module holds a second kind of policy and the file's title grew a
word for it: the tenant quiet-hours SEAM.** It is here rather than in
`services.py` for two reasons that agree. The owner's ruling of 2026-08-24 calls
a quiet window *policy*, and this is the app's policy module — the one place a
reader already comes to ask "what is this product allowed to say, and to whom".
And `providers.py`'s own docstring makes the mechanical half of the argument
about its own registry: a services module whose public names are nouns is a
services module doing something other than services (house rule 16). A window
resolver and a window lookup are nouns.

The rule for this app is one sentence: **anybody in the tenant may send, and
only an owner or an admin may change what the tenant is allowed to send.**
That asymmetry is the point of the whole app. Sending is ordinary product work
— an invoice, a receipt, a reminder — and gating it behind a role would only
push features into calling `django.core.mail` directly, which is the exact
bypass `send()` exists to close. Consent, quiet hours and suppression are not
gated by a role at all: they are enforced inside `send()` against the
recipient's own preferences, where no caller can reach around them.

Changing a template, granting or revoking consent, or lifting a suppression is
the other kind of act: it changes what the product may say to somebody, on that
person's behalf, so it takes a privileged role. Those services landed with
C1-1b and every one of them calls `require` — which is what makes the asymmetry
a property of the app rather than a claim in a docstring: a service with no
`require` is a house-rule-13 violation, and an action with no policy is
invisible in `introspect`.

**The privileged half of that asymmetry is no longer a rank comparison.** This
file used to answer "how much authority does this person have" by reading a role
by value off the membership row, which is a second opinion about a role no
tenant can edit (rule 54 (c), architect §C7). The predicate is gone and the keys
it guarded — the templates, the delivery policies and consent — are held by
`admin`'s `*` pattern and by `owner`, which is the same answer said once instead
of twice. Archiving and restoring a contact left that list when `Recipient`
became `Archivable`: they are the family's keys now, asked by
`core.policies.may_archive` at the contact's own node. Nothing a caller can see moved:
`tests/test_authz_sweep.py` measures every cell of this app's matrix against the
baseline and 0 of them did.

**DEFERRED, and deliberately: `DEFAULT_ROLES` for the member half.** The other
predicates here admit any membership (`can_send`, `can_keep_devices`), and the
shape they will eventually take is a `DEFAULT_ROLES` entry saying so as data.
They stay predicates for now because a `DEFAULT_ROLES` write entry moves what a
plain `member` DECLAREDLY holds, which is a pin of the flat product
(`apps/core/tests/test_vocabulary.py`'s template-roles test, and the scope echo
at the mint that reads the declaration and not the transitional set) — a
cross-app move that belongs to one later rung rather than to eight per-app
sweeps, each moving it a little. Until then the compat residue in
`core.authz._attach_default_roles` clause (5) admits `member` exactly as it
always did, and the predicate narrows it exactly as it always did.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

from apps.comms.models import ChannelPreference, is_quiet_at, quiet_opens_in, quiet_zone
from apps.core.actor import Actor
from apps.core.authz import Policy, membership_for
from apps.core.log import get_logger
from apps.core.models import Tenant
from apps.core.policies import may_archive

log = get_logger("apps.comms.policies")


def _is_member(actor: Actor) -> bool:
    """Whether this actor holds any membership in the tenant they are acting in.

    **Not a role read.** It asks whether there is a membership at all, never
    which one — the whole of rule 54 (c)'s subject is comparing the ROLE on that
    row against a rank, and there is no comparison here to make. What a
    membership gets by default is the role's collection, which is data a tenant
    owns and can edit; this is the reach question underneath it.
    """
    return membership_for(actor) is not None


def can_send(actor: Actor, obj: Any = None) -> bool:
    """Anyone in the tenant may send, in the part of it they are acting as.

    There is no per-recipient check here and that is deliberate: which
    recipients this hat can even *see* is answered one layer down, by
    `for_tenant(...).visible_to(...)` in `selectors.py`. A recipient in a
    sibling branch is not "forbidden", it is `not_found` — a 403 there would
    tell the caller that somebody else's customer exists.
    """
    return _is_member(actor)


def can_record_status(actor: Actor, obj: Any = None) -> bool:
    """**Nobody.** A delivery status is observed, never asserted.

    It returns `False` for every actor with a membership, and that is the whole
    point: `delivered` and `bounced` are things a *transport* told us, and a
    person who could set them by hand could make the message log say a customer
    received something they did not. The only caller is the signed status
    webhook, acting as the system — and `authz.allows` lets the system through
    before it ever consults this file (`core/authz.py`, the `kind == "system"`
    branch), which is exactly the asymmetry being drawn.

    So this is not a stub and it is not an oversight. It is the door being
    nailed shut from the inside, and `tests/test_services.py` proves a logged-in
    owner is refused by it.
    """
    return False


def can_record_engagement(actor: Actor, obj: Any = None) -> bool:
    """**Nobody.** An open is observed, never asserted.

    The same door `can_record_status` nails shut from the inside, and the reason
    is the same one turned sideways: a person who could assert an engagement
    could make the record say a customer read something they never opened —
    which is a fact about that customer, written by somebody else, into a table
    whose whole value is that it is witnessed. ADR comms-9 says the write is
    "deliberately door-less: a REST write would let a client mint 'opened'
    facts", and this predicate is that sentence made enforceable.

    Only the signed provider webhook, acting as the system, records one:
    `authz.allows` lets a `system` actor through before this file is consulted
    (`core/authz.py`), which is the asymmetry being drawn. `tests/
    test_engagement.py` proves a logged-in owner is refused by it.
    """
    return False


def can_keep_devices(actor: Actor, obj: Any = None) -> bool:
    """Anybody in the tenant may register a contact's device, or retire one.

    The same role `can_send` grants, and deliberately not the privileged one.
    A device registration is the push channel's equivalent of writing down
    somebody's phone number: it is ordinary product work — an app's own client
    calls it the moment a person taps "allow notifications" — and gating it
    behind an owner would push products into keeping tokens in a table of their
    own, which is `send()`'s bypass one layer down.

    **What it is not is a consent decision.** Registering a device does not
    make a person reachable: the `push` channel's `ChannelPreference` decides
    that, inside `send()`, and a marketing push still needs consent it cannot
    get from a registration. Retiring a device is likewise not "stop pushing to
    this person" — that is `suppress_recipient`, one wall in one place.

    Which contact's devices this hat can reach at all is answered one layer
    down, by `may_be_named` in the services: a contact in a sibling branch is
    `not_found`, never `forbidden`, for `can_send`'s reason.
    """
    return _is_member(actor)


def can_record_surge(actor: Actor, obj: Any = None) -> bool:
    """**Nobody.** A suppression surge is observed, never declared.

    The same door nailed shut from the inside that `can_record_status` is, and
    for a sharper reason: a surge row is the *memory* the mass-suppression
    tripwire announces transitions from (ADR comms-9). A person who could open
    one could announce a flood that never happened; a person who could close one
    could silence the alarm for the attack that is happening. Both writes are
    the system's, inside the status webhook's own transaction, and
    `authz.allows`' system branch reaches them without consulting this file.
    """
    return False


#: **Four keys that named a plain row op in a second word.** Registering a device
#: IS creating one; a provider's report IS a `MessageEngagement` row; a tripwire
#: opening IS a `SuppressionSurge` row; and `preference.set` was a second
#: spelling of `channel_preference.update` — same act, same sentence, named by no
#: `require` anywhere in this tree.
#:
#: **A rename is not a deletion and that is the point.** `resolve_renamed` runs
#: before the vocabulary lookup and `refusal_sentence` resolves the alias first,
#: so a product still calling `device.register` gets the same answer with the
#: same words it always got. What changes is the census: the vocabulary stops
#: carrying four synonyms for verbs the model registry already derives, and rule
#: 54 (a)'s ratchet loses this app's names.
#:
#: **What a deployment owes after this lands.** A `Grant` or `RolePermission` row
#: stored under an old key goes inert the day the sweep ships — the resolution
#: layers match on the key as written, and only `manage.py rename_permission`
#: moves the rows. A template clone with no such rows observes nothing; a product
#: that handed one of these out runs the command, which is why every renamed key
#: belongs in the release note by name.
RENAMED_PERMISSIONS: dict[str, str] = {
    "device.register": "device.create",
    "message_engagement.record": "message_engagement.create",
    "suppression_surge.record": "suppression_surge.create",
    "preference.set": "channel_preference.update",
}


POLICIES: dict[str, Policy] = {
    "message.send": can_send,
    # Observed, not asserted — see `can_record_status`. The system webhook is
    # the only caller and it does not reach this entry.
    "message.record_status": can_record_status,
    # And its sibling one table over (ADR comms-9): an open or a click is a
    # provider's report about a person, not a claim a client may make. The key
    # is the ROW's plain create — house rule 13's model half looks for a policy
    # noun matching the scoped model this app writes, and `message_engagement`
    # is that model.
    "message_engagement.create": can_record_engagement,
    # Likewise, one layer up: the tripwire's own state. See `can_record_surge`.
    "suppression_surge.create": can_record_surge,
    # The management surface. Recipients are ordinary contact data anybody in
    # the tenant may keep; closing one, and everything about consent and
    # templates, is an owner's or an admin's.
    # Cancelling a scheduled send is the same trust as making one: whoever may
    # send may change their mind. Not the privileged role — a person who can put
    # a message in the queue and cannot take it back out is a person who will
    # reach for the database.
    "message.cancel": can_send,
    "recipient.create": can_send,
    "recipient.update": can_send,
    # The push address book. Ordinary contact data, so the same role that keeps
    # a phone number keeps a device — see `can_keep_devices` for why this is not
    # the privileged one and why it is not a consent decision.
    "device.create": can_keep_devices,
    "device.retire": can_keep_devices,
    # The contact book's archive road. `Recipient` is `Archivable`, so both keys
    # are DERIVED; the predicate is the family's one — the node's
    # administration (`organization.update`) asked where the contact lives, and
    # `@refuses_system`, so a workflow never closes a person's contact on its
    # own say-so. Without this pair the system actor would keep the exemption
    # every other key has, and the default roles would answer alone.
    "recipient.archive": may_archive,
    "recipient.restore": may_archive,
    #
    # **And SIX keys are no longer here at all**, where `can_administer` — a
    # rank comparison on the membership row — used to sit:
    # `message_template.create`, `message_template.retire`,
    # `delivery_policy.create`, `delivery_policy.retire` and
    # `channel_preference.update` (`preference.set` renames onto that last one).
    # "Only an owner or an admin" is what `admin`'s `*` pattern and `owner`'s
    # whole-vocabulary collection already say, so the predicate was a second
    # opinion about a role a tenant owns and can edit — which is the thing rule
    # 54 (c) is against. Dropping it moves no cell: a key with no predicate is
    # held by `owner` and by every declared role whose pattern matches, and
    # `member`'s pattern is `*.read`.
}


# The sentence a refused caller reads, per action. See `core/policies.py`.
# A renamed key needs no line of its own: `refusal_sentence` resolves the alias
# first, so `device.register` reads `device.create`'s sentence, byte for byte.
ACTION_PROSE: dict[str, str] = {
    "message.send": "You may not send messages from this organization.",
    "message.record_status": "You may not record delivery results for this tenant's messages.",
    "message_engagement.create": ("You may not record opens or clicks for this tenant's messages."),
    "suppression_surge.create": "You may not record a blocked-address surge for this tenant.",
    "message.cancel": "You may not cancel this organization's scheduled messages.",
    "recipient.create": "You may not add contacts to this organization.",
    "recipient.update": "You may not change this organization's contacts.",
    "recipient.archive": "You may not archive this organization's contacts.",
    # The derived sentence would say "this recipient"; every door of this app
    # says "contact", so the pair keeps the word the archive sentence already
    # published.
    "recipient.restore": "You may not restore this organization's contacts.",
    "device.create": "You may not register devices for this organization's contacts.",
    "device.retire": "You may not retire devices for this organization's contacts.",
    "channel_preference.update": "You may not change what a contact has agreed to receive.",
    "message_template.create": "You may not create message templates for this organization.",
    "message_template.retire": "You may not retire this organization's message templates.",
    "delivery_policy.create": "You may not create delivery policies for this organization.",
    "delivery_policy.retire": "You may not retire this organization's delivery policies.",
}


# --- the tenant quiet-hours seam. EMPTY, and that is the whole design ------------
#
# **The owner's ruling of 2026-08-24: "empty seam is right — do it that way".**
# The policy is the product's, full stop: the platform never ships a default
# window and never holds an opinion about hours. What the platform owes — and
# the only reason any of this is here rather than in a product — is house rule
# 25's one-legal-sender argument: consent, quiet hours and suppression are
# *enforceable* precisely because there is ONE binding point, inside `send()`,
# that nothing can reach around. A product that grew its own tenant-wide window
# beside `send()` would be a second wall, and two walls disagree.
#
# So: one binding point, one vocabulary, and **nothing configured**.
#
# **Unset ≡ the seam does not exist.** No resolver is registered on a fresh
# clone, `tenant_quiet_window` answers `None` for every tenant, `_refusal` takes
# the same branch it always took, and the behaviour is byte-identical to the
# tree before this seam existed — which is a claim `tests/test_quiet_hours_seam.py`
# drives rather than asserts. There is no `COMMS_QUIET_HOURS` setting to leave
# blank and no row to leave null, because a default that exists is a default
# somebody has to decide, and deciding it is exactly what the ruling forbids.
#
# **Why a resolver and not a column.** A column would be the platform choosing
# where a product's policy lives, how it is versioned, who may write it and what
# it means when two of them disagree — four product decisions, taken by the
# template, for a feature the template has no opinion about. A registration is
# the shape this repository already uses for exactly this ("registration is by
# discovery, never by editing config" — `providers.register_channel`,
# `connections.register_inbound_handler`, `search.lifecycle.register`): a
# product resolves the window however it likes, from whatever it likes, and
# says so once from its own `AppConfig.ready()`.


@dataclass(frozen=True)
class QuietWindow:
    """A tenant-wide quiet window, as a product hands one back. **Not a row.**

    Frozen and plain, because it crosses a seam a product implements: whatever
    a product resolves it from — a settings table, a feature flag, a calendar —
    what comes back here is three values, and the arithmetic that reads them is
    `apps/comms/models.py`'s, shared with `ChannelPreference` so the tenant's
    window and the person's window cannot come to mean different things.

    `timezone` is a name (`"Europe/London"`), resolved through the same
    fallback-to-UTC-and-log path a preference row's is: an unknown zone in one
    product's seam must not make the product unable to send at all.
    """

    start: time
    end: time
    timezone: str = "UTC"

    def is_quiet_at(self, at: datetime) -> bool:
        """Whether `at` is inside this window. The preference row's own question."""
        return is_quiet_at(
            start=self.start,
            end=self.end,
            zone=quiet_zone(self.timezone, where="tenant quiet window"),
            at=at,
        )

    def opens_in(self, at: datetime) -> timedelta:
        """How long until it ends. Zero when it is not shut."""
        return quiet_opens_in(
            start=self.start,
            end=self.end,
            zone=quiet_zone(self.timezone, where="tenant quiet window"),
            at=at,
        )


#: The registered resolver, or `None` — and `None` is what ships.
#:
#: A module-level slot rather than a list, because there is exactly one answer
#: to "what is this tenant's quiet window" and a second resolver would be a
#: second policy, which is the thing being refused. Registering twice replaces,
#: exactly as `register_channel` does for a slug.
_QUIET_HOURS: Callable[[Tenant], QuietWindow | None] | None = None


def register_quiet_hours(resolver: Callable[[Tenant], QuietWindow | None]) -> None:
    """Tell `send()` how to find a tenant's quiet window. **A product's call.**

        # apps/<your-app>/apps.py
        def ready(self) -> None:
            from apps.comms.services import register_quiet_hours
            register_quiet_hours(my_window_for)

    The resolver is handed a `Tenant` and answers a `QuietWindow` or `None`.
    `None` means this tenant has no window, which is the same answer an
    unregistered seam gives for every tenant — so a product can switch the
    feature on for one tenant and change nothing for the rest.

    It is called inside the consent wall, on the send path, so it should be
    cheap and it must not raise: a resolver that throws is a product bug that
    would stop the tenant sending at all, and `tenant_quiet_window` refuses to
    let it — see there.
    """
    global _QUIET_HOURS
    _QUIET_HOURS = resolver


def unregister_quiet_hours() -> None:
    """Put the seam back to unset. Symmetry, and what a test's teardown needs."""
    global _QUIET_HOURS
    _QUIET_HOURS = None


def tenant_quiet_window(tenant: Tenant | None) -> QuietWindow | None:
    """This tenant's quiet window, or `None`. **`None` on a fresh clone, always.**

    Three ways to get `None`, and they are deliberately indistinguishable to the
    caller: no resolver registered (the shipped state), a resolver that says this
    tenant has none, and a resolver that raised.

    **The third is the one worth explaining.** A product's resolver runs inside
    the consent wall, on every send. If it throws — a settings row missing, a
    cache down, a typo — the honest choices are to refuse the send or to proceed
    as though there were no window. Refusing would mean a product's quiet-hours
    misconfiguration stops that tenant contacting anybody at all, including the
    transactional mail their customers are waiting for; proceeding means a
    marketing message may go out inside a window the product meant to configure.
    The second is the smaller harm and it is loud — `comms.quiet_hours.resolver_failed`
    at warning, naming the tenant — where the first is silent from the
    recipient's side and catastrophic from the tenant's.

    **This is not the platform holding an opinion about hours.** It is the
    platform holding an opinion about its own failure mode, which is the one
    kind of opinion a seam is allowed.
    """
    resolver = _QUIET_HOURS
    if resolver is None or tenant is None:
        return None
    try:
        window = resolver(tenant)
    except Exception:  # noqa: BLE001 - a product's resolver, deliberately caught
        log.warning("comms.quiet_hours.resolver_failed", tenant_id=str(tenant.pk))
        return None
    return window if isinstance(window, QuietWindow) else None


def quiet_defer_seconds(
    *,
    preference: ChannelPreference | None,
    tenant: Tenant | None,
    at: datetime,
) -> int:
    """How many whole seconds a quiet-hours refusal has left to run.

    **The longer of the two windows**, because both refuse independently: a
    message held by the person's window until 07:00 and by the tenant's until
    08:00 may not go out at 07:00. Waiting the shorter one would wake the run
    into a second refusal, spend the deferral (`MAX_DEFERRALS`) and record a
    message nobody sent — which is the failure this function exists to avoid
    rather than a conservatism.

    Zero is a legal answer and means "re-judge now"; `quiet_opens_in`'s own
    docstring carries the reason.
    """
    person = preference.quiet_opens_in(at) if preference is not None else timedelta(0)
    window = tenant_quiet_window(tenant)
    house = window.opens_in(at) if window is not None else timedelta(0)
    return int(max(person, house).total_seconds())
