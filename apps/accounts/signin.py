"""The sign-in CHECK, as a seam. **One door reaches it, and rung A5 mounted it.**

Design I-A's capability C-8 and C-14. One person, at a form, being checked
against the identity platform's Session API and nothing else: this module opens
a Zitadel session, asks it the questions a ceremony asks, reads the answers
fail-closed, and closes the session on the way out of every exit it has.

**What it is not.** It is not a view, not a route, not a template and not a
service. It writes no row, reads no model, and knows nothing about a tenant.
**Exactly one thing in `apps/` or `config/` imports it** — `apps/accounts/
views.py`, the door rung A5 mounted behind `SIGN_IN_DOOR=ours` — and
`apps/accounts/tests/test_signin.py::
test_one_door_reaches_the_seam_and_it_is_the_one_a5_mounted` is the census that
says so. A seam built one rung ahead of its door was deliberate (rule 42): none
of the properties below is easier to prove through a browser.

**The contract, in one sentence.** Every entry point takes the ceremony's own
store and returns one `SignIn`, whose `outcome` is a member of
`SignInOutcome` and whose `step` is a member of `Step` — a closed vocabulary
each, so the page that renders this can be a switch over a finite set rather
than a chain of truthiness tests over a dictionary.

---

## The four fail-closed rules

The rules are numbered because the tests name them, and they exist because
every one of them is a way a sign-in seam goes green while letting somebody in.
Each rule's shape is the same: **the only road to `done` is positive evidence,
and everything else is a refusal or an outage.**

1. **A 2xx is not a verified anything.** MEASURED (`zitadel_measure`'s M5):
   `POST /v2/sessions` with a `user` check and no password answers **201**, and
   the session it made carries `factors.user` with no `factors.password` at
   all. So the verdict is read back off `session.factors.<kind>.verifiedAt` and
   never off a status code. A seam that trusted the 201 would sign in anybody
   whose address exists.
2. **An answer this seam cannot read is an outage, never a pass.** A body with
   no `session`, a `verifiedAt` that is absent or empty, a 5xx, a transport
   failure, a deadline reached — all `UNAVAILABLE`. Not `REFUSED`: telling a
   person their password is wrong when the truth is that we could not look is
   the failure mode this rule exists for.
3. **A refusal aimed at OUR credential is an outage, never the person's
   fault.** A `401`, `403` or `429` from Zitadel is about the machine PAT —
   expired, un-roled, rate-limited — and answering `REFUSED` for it would tell
   every person in the deployment that they forgot their password on the same
   morning. Only a `400`/`404`/`409`-shaped refusal, which is Zitadel judging
   the CHECK, is `REFUSED`.
4. **A factor kind this seam cannot answer is never satisfied.** A kind outside
   `FactorKind`, or a WebAuthn challenge the build refuses with
   `WEBAU-4G8sw` ("no passkey here", M9), is `KIND_UNANSWERABLE` — a dead end
   with a sentence, never a pass and never a hand-off to the hosted page, which
   under login v2 is a 302 loop (K10).

## The two clocks

`ZITADEL_SIGNIN_TIMEOUT` (4 s) bounds one call; `ZITADEL_SIGNIN_DEADLINE`
(12 s) bounds the whole check. The deadline is stamped into the ceremony as a
monotonic start and consulted **before every call**, so a check that has run
out of time stops rather than making a request whose answer nobody is waiting
for. Monotonic rather than wall-clock: a clock adjustment mid-ceremony must not
extend or collapse a deadline.

## The ceremony

One key in the caller's store (`request.session`, at A5), holding a mapping
whose keys are exactly `CEREMONY_FIELDS` — a closed set, so the state a page
carries between two POSTs is enumerable rather than whatever the last branch
happened to put there. **It is deleted at every exit**, and the Zitadel session
it names is closed at the same moment (ADR ident-12: every session this module
opens, it closes). "Every exit" includes the refusals, the outages, the
person's own *Never mind*, and a second `begin` over a ceremony already in
flight.

## What is never in a log line

`accounts.signin.*` lines carry an outcome, a reason and a duration. They never
carry an address, a password, a one-time code, a session token, an enrolment
secret or a TOTP URI — the sweep in `test_signin.py::
test_no_secret_reaches_a_log_line` drives the whole ceremony and reads every
line back out of what left the process. The person's Zitadel user id IS logged:
it is an opaque platform id, it is what an operator correlates with, and it is
the same id `accounts.zitadel.*` lines already carry.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass, field, replace
from datetime import timedelta
from enum import StrEnum
from time import monotonic, sleep
from typing import Any

from django.conf import settings
from django.core.cache import cache

# rule-27: a sign-in CHECK writes nothing of ours until Zitadel answers, so no transaction
# holds across the call; the person waits at the form, so it cannot be an activity.
from apps.accounts import zitadel
from apps.core import context
from apps.core.log import get_logger
from apps.core.surfaces import STAFF, absolute_url, surface_base_urls

log = get_logger(__name__)


class Step(StrEnum):
    """What the page must ask the person for next. A closed set of FRAMES.

    Deliberately four and not one per screen: `Step` says what is being asked
    for, and the frame that draws it (design P-10's six) is the page's choice.
    A seam that named frames would be a seam the page could disagree with.
    """

    #: The address-and-password form. Where a ceremony starts, and where it
    #: returns to after a refusal or a throttle.
    # The NAME of a frame, not a credential; detect-secrets keys on the
    # keyword and cannot tell a vocabulary member from a value.
    PASSWORD = "password"  # noqa: S105 — the name of the sign-in form's frame  # pragma: allowlist secret
    #: *One more step* — a factor is enrolled and has to be answered.
    FACTOR = "factor"
    #: *Set up two-factor* — the org asks for one and this person has none.
    ENROL = "enrol"
    #: *Reset your password* — the address form, and the page that says a
    #: link is on its way. A frame of its own because it asks for one thing
    #: nothing else asks for (an address with no password beside it) and
    #: because its second state has no form at all.
    RESET = "reset"  # pragma: allowlist secret
    #: *Choose your password* — the invited person's first screen (design
    #: J1-a, rung A7). A fifth member rather than a reuse of `PASSWORD`,
    #: because the two ask for different things: `PASSWORD` is an address and
    #: a password being CHECKED, and this is one password being CHOSEN. A page
    #: that could not tell them apart would draw the sign-in form at somebody
    #: who has no password to type into it.
    INVITE = "invite"
    #: There is nothing more to ask. The ceremony is over, in either direction,
    #: and `outcome` is what direction it went.
    NOTHING = "nothing"


class SignInOutcome(StrEnum):
    """What one ask answered. **Every return value of this module is one of these.**

    The closed set the page switches on, and the population
    `test_every_outcome_is_a_member_of_the_closed_set` proves is both complete
    (nothing returns a string outside it) and REACHED (every member is produced
    by some drive — a vocabulary with an unreachable member is a member nobody
    renders).
    """

    #: Keep going: `step` says what to ask for. Nothing has failed.
    CONTINUE = "continue"
    #: The person is checked. `subject` carries the Zitadel user id, the
    #: Zitadel session is already closed, and the door takes it from here.
    DONE = "done"
    #: Zitadel judged the check and said no — a wrong password, an unknown
    #: address, a locked account. **One sentence for all three** (design J7:
    #: a distinct "locked" sentence is an oracle over which addresses exist).
    REFUSED = "refused"
    #: Our own per-address limit. Zitadel was not asked.
    THROTTLED = "throttled"
    #: We could not look. Fail-closed rules 2 and 3 both land here.
    UNAVAILABLE = "unavailable"
    #: The ten-minute ceremony window closed under a tab left open, or there
    #: was no ceremony to continue.
    CEREMONY_GONE = "ceremony_gone"
    #: This deployment cannot answer the kind this person signs in with.
    KIND_UNANSWERABLE = "kind_unanswerable"
    #: The person said *Never mind*. Nothing was changed.
    CANCELLED = "cancelled"
    #: The invite link is spent, expired or superseded. **One member for all
    #: three**, because Zitadel answers one error id for all three
    #: (`INVITE_CODE_INVALID`, measured) and a seam that split them would be
    #: inventing a distinction it cannot observe.
    INVITE_GONE = "invite_gone"
    #: The org's complexity policy refused the password they chose.
    #: `refusal_detail` carries the policy's own reason for the one frame
    #: that quotes it.
    INVITE_WEAK = "invite_weak"
    #: They already have credentials here, so there is nothing to set. The act
    #: they need is to sign in, and the page draws that form instead.
    INVITE_REFUSED = "invite_refused"
    #: The reset was ASKED FOR. **Not "a mail was sent"** — this seam does
    #: not know that, and must not: it is the same answer whether the address
    #: has an account or not, which is the whole of design J5's
    #: no-enumeration rule. What it means is "we have finished asking".
    RESET_ASKED = "reset_asked"  # pragma: allowlist secret
    #: Mode A: the OIDC auth request expired, was already answered, or never
    #: existed. **One member for all three** — measured, the platform answers
    #: three different ids (`QUERY-Thee9`, `COMMAND-jae5P`, `COMMAND-Sx208nt`)
    #: for one fact a person can act on: there is nothing here to finish, and
    #: the move is to start again from the app that sent them.
    REQUEST_GONE = "request_gone"


class FactorKind(StrEnum):
    """The second-step kinds this seam knows how to ask for. A closed set.

    The five design C-8 names. A kind Zitadel reports that is not in here is
    `KIND_UNANSWERABLE` by fail-closed rule 4 — including a kind a future
    Zitadel invents, which is the case the closed set is FOR: a seam that
    forwarded an unknown kind to a page would render a form for something
    nobody has written an answer path for.
    """

    TOTP = "totp"
    OTP_EMAIL = "otp_email"
    OTP_SMS = "otp_sms"
    U2F = "u2f"
    PASSKEY = "passkey"


#: Zitadel's own names for the same five, as `authentication_methods` reports
#: them. One mapping, here, so the translation happens once: a seam that
#: matched on Zitadel's strings in four places would be four places to update
#: when the build renames one, and the `KIND_UNANSWERABLE` road is what an
#: unrecognised name takes.
#: Zitadel's name for the password itself, which `authentication_methods`
#: ALWAYS reports — MEASURED by hand against the pinned build on 2026-09-18: a
#: person with a password and nothing else answers
#: `authMethodTypes: ['AUTHENTICATION_METHOD_TYPE_PASSWORD']`, never `[]`. It
#: is not in the map below because it is not a SECOND step, and a seam that
#: read "the list is non-empty" as "a factor is enrolled" would send every
#: person on this build to a form they cannot answer. Named rather than merely
#: absent, so the absence is a decision a reader can check.
# Zitadel's enum member, not a credential — allowlisted for the reason above.
ZITADEL_PASSWORD_METHOD = "AUTHENTICATION_METHOD_TYPE_PASSWORD"  # noqa: S105 — Zitadel's enum name for the password method  # pragma: allowlist secret

ZITADEL_FACTOR_NAMES: Mapping[str, FactorKind] = {
    "AUTHENTICATION_METHOD_TYPE_TOTP": FactorKind.TOTP,
    "AUTHENTICATION_METHOD_TYPE_OTP_EMAIL": FactorKind.OTP_EMAIL,
    "AUTHENTICATION_METHOD_TYPE_OTP_SMS": FactorKind.OTP_SMS,
    "AUTHENTICATION_METHOD_TYPE_U2F": FactorKind.U2F,
    "AUTHENTICATION_METHOD_TYPE_PASSKEY": FactorKind.PASSKEY,
}

#: Which `checks` block answers each kind, and which `challenges` block (if
#: any) has to be asked for first. `None` means the kind needs no challenge —
#: an authenticator app is already showing a code, and asking Zitadel to send
#: something would be a round trip for nothing.
FACTOR_CHECK_NAMES: Mapping[FactorKind, str] = {
    FactorKind.TOTP: "totp",
    FactorKind.OTP_EMAIL: "otpEmail",
    FactorKind.OTP_SMS: "otpSms",
    FactorKind.U2F: "webAuthN",
    FactorKind.PASSKEY: "webAuthN",
}
FACTOR_CHALLENGE_NAMES: Mapping[FactorKind, str | None] = {
    FactorKind.TOTP: None,
    FactorKind.OTP_EMAIL: "otpEmail",
    FactorKind.OTP_SMS: "otpSms",
    FactorKind.U2F: "webAuthN",
    FactorKind.PASSKEY: "webAuthN",
}

#: The one key this module puts in the caller's store.
CEREMONY_KEY = "accounts.signin.ceremony"

#: **Every key the ceremony mapping may carry, and nothing else.** A closed set
#: rather than a dataclass because the store is a Django session at A5 and a
#: session holds JSON; the closure is enforced by `_remember`, which refuses an
#: unknown key loudly rather than letting a typo become a field nobody reads.
CEREMONY_FIELDS = frozenset(
    {
        # Zitadel's session id and the CURRENT session token. The token
        # rotates on every PATCH that verifies something and is absent from
        # the answer of one that verifies nothing (M8) — carrying the old one
        # forward on that shape is the bug this field's writer guards.
        "session_id",
        "token",
        # Whose ceremony this is, as Zitadel's opaque id.
        "user_id",
        # **And which organisation they are in.** Every policy read on this
        # road is the ORG's policy, not the instance's, and the org is known
        # exactly once — off the session read, at the password step. A later
        # read that asked with no org got the INSTANCE default: an org with
        # `mfaInitSkipLifetime=0` drew *Not now (365 days)* and pressing it
        # LANDED somebody with no second factor, because the instance
        # allowed a skip the org forbids (V-A-W3F).
        "org_id",
        # The monotonic stamp the deadline is measured from.
        "started",
        # Which `Step` the page was last told to draw.
        "step",
        # The kinds offered at `Step.FACTOR`, and the one being answered.
        "kinds",
        "pending",
        # Mode A (design C-10, rung A8): the OIDC auth request this ceremony
        # is finishing, if it is finishing one. Carried HERE rather than
        # re-read off the URL at each step because `_finish` is reached from
        # four roads — password, factor, enrolment, invite — and the finalize
        # has to happen on every one of them, once, in the same place.
        "auth_request",
    }
)

#: The closed set of event names this module logs. Design §3.6's five, named
#: here so the log-sweep test can assert over a population rather than a regex.
LOG_EVENTS = (
    "accounts.signin.checked",
    "accounts.signin.refused",
    "accounts.signin.unavailable",
    "accounts.signin.handed_off",
    "accounts.signin.finished",
)

#: The `KIND_UNANSWERABLE` reason for design J6's own sentence: this person
#: HAS a passkey and it is bound to a relying party that is not us. Not a
#: `FactorKind` — it is a state of one kind, not a sixth kind — and not an
#: outcome, because it is the same dead end with a different sentence.
PASSKEY_ELSEWHERE = "passkey_elsewhere"

#: The other side of the same 500: this person owns no passkey at all. A
#: reason of its own rather than the KIND, because "this account signs in
#: with a passkey" is false of them — V-A-W3 read exactly that sentence on a
#: person who had never registered one.
PASSKEY_NONE = "passkey_none"

#: The statuses that mean "Zitadel refused OUR credential" — fail-closed rule 3.
OUR_CREDENTIAL_STATUSES = frozenset({401, 403, 429})


@dataclass(frozen=True)
class SignIn:
    """One answer from the seam. Frozen, because a page must not edit a verdict.

    `reason` is a short stable token for the log and for the page's sentence
    lookup — never prose, and never Zitadel's own message, which is translated
    and can carry an error id the person must not read (design J7's "must not"
    column).
    """

    outcome: SignInOutcome
    step: Step
    reason: str = ""
    #: At `Step.FACTOR`, the kinds this person may answer with.
    kinds: tuple[FactorKind, ...] = ()
    #: At `Step.ENROL`, what the QR is drawn from and what is printed under it.
    enrolment_uri: str = ""
    enrolment_secret: str = ""
    #: Whether *Not now* may be offered at `Step.ENROL` (`mfaInitSkipLifetime`
    #: non-zero on the org's login settings, read at render — design J2-c).
    may_skip: bool = False
    #: For how long, in whole days — the number design J2-c prints inside the
    #: *Not now* link. Zero exactly when `may_skip` is false, so the page has
    #: one fact to test rather than two that can disagree.
    skip_days: int = 0
    #: At `Step.FACTOR` on the passkey road: the `publicKey` options Zitadel
    #: answered, as the JSON the browser's own `navigator.credentials.get`
    #: takes. Carried as a STRING rather than a mapping because the only
    #: thing that ever reads it is a `JSON.parse` in the page, and a dict
    #: would be a shape this seam pretends to own.
    passkey_options: str = ""
    #: At `Step.FACTOR`, the address this deployment's identity mail goes out
    #: as, and ONLY when that sender belongs to somebody else (A6's F10).
    #: Empty means "say nothing": naming our own sender on our own page would
    #: be noise, and naming a foreign one is the person's only warning that
    #: the code arrives from a name they do not recognise.
    foreign_sender: str = ""
    #: On `DONE`: Zitadel's user id, which is the whole of what the door needs.
    subject: str = ""
    #: On `DONE`: the organisation the session verified the person in — the
    #: realm this sign-in came from, read off the session at the password step
    #: (`factors.user.organizationId`, measured). The door hands it to the
    #: adapter as the realm claim, so a person's realm is the platform's word
    #: and never a join row that may be stale. Empty on a road that never read
    #: a session (the invite road's done).
    realm: str = ""
    #: The org's password rules, for the Choose-your-password frame (M11).
    password_rules: Mapping[str, Any] = field(default_factory=dict)
    #: On `INVITE_WEAK` only: the platform's own reason, with its error id
    #: stripped. The one place a string Zitadel wrote reaches a page, and it
    #: is the design's instruction (J1-a: "Zitadel's reason rendered as ONE
    #: sentence, never Zitadel's error id") — the policy is the platform's, so
    #: a sentence of ours restating it would go wrong on the first org that
    #: tightens one.
    refusal_detail: str = ""
    #: On the invite road's `DONE`: the address the platform answered for the
    #: user id in the link. The door needs a login name to build its
    #: assertion and the invited person never typed one.
    login_name: str = ""
    #: Mode A only: where the browser goes next, as the PLATFORM built it —
    #: the client's own registered redirect URI with a code on it, or with an
    #: `error=` on it when the ceremony ended without one. Non-empty is what
    #: tells the door this journey belongs to an OIDC client rather than to
    #: this product, and a door that landed such a person at
    #: `LOGIN_REDIRECT_URL` would have signed them in here and left the app
    #: that sent them waiting forever.
    callback_url: str = ""


@dataclass(frozen=True)
class Person:
    """The platform's own record of whoever the ceremony just verified.

    Frozen for the reason `SignIn` is: the door reads an assertion, it does
    not compose one. `verified` is the platform's word about the ADDRESS, not
    about the password — the two are different facts and only the first one
    is what `adapter.asserted_email` is asking for.
    """

    subject: str
    address: str
    verified: bool


# --- the throttle (design C-14) ----------------------------------------------
#
# Our own limit, in front of Zitadel's account lockout, because the two bound
# different things: the lockout protects ONE account over its lifetime
# (`ZITADEL_MAX_PASSWORD_ATTEMPTS`) and cannot see a try against an address
# that has no account at all, while this bounds what one form can spend in one
# minute. A cache counter in the shared Redis, so the limit is the
# deployment's and not each process's — four web processes with a local
# counter is a limit four times higher than the one anybody wrote down.
#
# **Two buckets, because one of them is dodgeable.** Per email address, which
# is the thing being guessed; and per client address, which is what stops a
# caller walking a thousand addresses under the first limit. Both are counted
# on every try and either one refuses.
#
# **Neither key contains the address.** A cache key reaches Redis, `MONITOR`
# output and a slow-log; a digest is as good a bucket and is not a list of who
# tried to sign in. Same reason the log lines carry none.


def _bucket(kind: str, value: str) -> str:
    digest = hashlib.sha256(value.strip().casefold().encode()).hexdigest()[:32]
    return f"accounts.signin.throttle.{kind}.{digest}"


def _spend(key: str, limit: int) -> bool:
    """Count one try in this bucket. `False` when it is the one over the limit.

    `add`-then-`incr` rather than `get`-then-`set`: the two-step read/write
    races between processes and the whole point of a shared counter is that it
    does not. The `ValueError` arm is the window expiring between the two calls
    — a real state, not a theoretical one, and the honest answer there is to
    start the window again rather than to refuse somebody for a key that no
    longer exists.
    """
    if limit <= 0:
        return False
    if cache.add(key, 1, timeout=60):
        return True
    try:
        return int(cache.incr(key)) <= limit
    except ValueError:
        cache.set(key, 1, timeout=60)
        return True


def throttled(*, address: str, client_address: str = "") -> bool:
    """Whether this try is over either limit. **Asked before Zitadel is.**"""
    limit = int(getattr(settings, "SIGNIN_THROTTLE_PER_MINUTE", 5))
    within = _spend(_bucket("address", address), limit)
    if client_address:
        # Both are spent, never short-circuited: a `and` here would stop
        # counting the client bucket the moment the address bucket refused,
        # and an attacker walking addresses would never fill it.
        within = _spend(_bucket("client", client_address), limit) and within
    return not within


# --- the ceremony ------------------------------------------------------------


def _remember(store: MutableMapping[str, Any], **fields: Any) -> dict[str, Any]:
    """Merge `fields` into the ceremony. Refuses a key outside `CEREMONY_FIELDS`."""
    unknown = set(fields) - CEREMONY_FIELDS
    if unknown:
        raise ValueError(
            f"the sign-in ceremony carries a closed set of keys and {sorted(unknown)} "
            f"is not in it — add it to CEREMONY_FIELDS with the reason, or fix the typo"
        )
    ceremony = dict(store.get(CEREMONY_KEY) or {})
    ceremony.update(fields)
    store[CEREMONY_KEY] = ceremony
    return ceremony


def _ceremony(store: Mapping[str, Any]) -> dict[str, Any]:
    found = store.get(CEREMONY_KEY)
    return dict(found) if isinstance(found, Mapping) else {}


def _forget(store: MutableMapping[str, Any], *, close: bool = True) -> None:
    """Close the Zitadel session this ceremony named, then delete the ceremony.

    In that order, and both unconditionally: a store cleared before the close
    is a session nobody can close any more, and a close that raised would
    otherwise leave the ceremony behind for the next POST to resume into a
    session that may be gone. Every exit of this module goes through here.

    **`close=False` is Mode A's one exception to ADR ident-12, and it was
    MEASURED rather than reasoned** (rung A8, 2026-09-19, live against
    v4.17.1). Finalizing an auth request answers a `callbackUrl` with a code
    on it, and the CLIENT spends that code afterwards, on its own connection,
    at `POST /oauth/v2/token`. Zitadel validates the session the code was
    minted against AT THAT MOMENT: with the session closed on our way out the
    exchange answers

        400 {"error":"invalid_request",
             "error_description":"Errors.Session.Terminated"}

    and the person is left signed in nowhere while the app that sent them
    gets an error — after a sign-in that looked perfect from both ends and
    that every in-suite drive passed. So on the one road where the session is
    somebody else's to spend, it is left to Zitadel's own lifetime instead.

    What that leaves behind is bounded and unreachable: the session TOKEN is
    the only handle on it, it never left this process (the ceremony that held
    it is deleted on the next line), no cookie of the platform's is set in
    the browser, and the session expires on the instance's own clock. The
    alternative — closing a session a client is about to spend — is not a
    tidier version of this, it is a sign-in that does not work.
    """
    ceremony = _ceremony(store)
    session_id = str(ceremony.get("session_id", ""))
    token = str(ceremony.get("token", ""))
    if session_id and close:
        try:
            zitadel.close_session(session_id=session_id, token=token)
        except zitadel.ZitadelError:
            # The session is a ten-minute object on somebody else's server and
            # this is the LAST act of a ceremony: a transport failure here
            # must not change the verdict the person is about to read. It is
            # logged (below) and nothing else.
            log.info("accounts.signin.finished", outcome="close_failed")
    store.pop(CEREMONY_KEY, None)


def _out_of_time(ceremony: Mapping[str, Any]) -> bool:
    """Whether the whole-check deadline has passed. Asked before EVERY call."""
    started = ceremony.get("started")
    if not isinstance(started, int | float):
        return False
    deadline = float(getattr(settings, "ZITADEL_SIGNIN_DEADLINE", 12.0))
    return (monotonic() - float(started)) >= deadline


def _elapsed(ceremony: Mapping[str, Any]) -> float:
    started = ceremony.get("started")
    if not isinstance(started, int | float):
        return 0.0
    return round(monotonic() - float(started), 3)


# --- reading Zitadel's answers, fail-closed ----------------------------------


def _verified(answer: zitadel.Probe, kind: str) -> bool:
    """Whether the session's factors say this kind is verified. **Rule 1.**

    A missing `session`, a missing `factors`, a missing kind, or a
    `verifiedAt` that is absent or empty all read as NOT verified, and there
    is deliberately no arm that reads a status code.
    """
    session = answer.body.get("session")
    if not isinstance(session, Mapping):
        return False
    factors = session.get("factors")
    if not isinstance(factors, Mapping):
        return False
    factor = factors.get(kind)
    if not isinstance(factor, Mapping):
        return False
    return bool(str(factor.get("verifiedAt", "") or "").strip())


def _outage(answer: zitadel.Probe) -> bool:
    """Whether this answer is ours to own rather than the person's. **Rules 2, 3.**"""
    return answer.status in OUR_CREDENTIAL_STATUSES or answer.status >= 500


def _unavailable(step: Step, reason: str, *, elapsed: float = 0.0) -> SignIn:
    log.info("accounts.signin.unavailable", reason=reason, seconds=elapsed)
    return SignIn(outcome=SignInOutcome.UNAVAILABLE, step=step, reason=reason)


def _refused(step: Step, reason: str, *, elapsed: float = 0.0) -> SignIn:
    log.info("accounts.signin.refused", reason=reason, seconds=elapsed)
    return SignIn(outcome=SignInOutcome.REFUSED, step=step, reason=reason)


def _judge(answer: zitadel.Probe, step: Step, *, elapsed: float = 0.0) -> SignIn | None:
    """The two fail-closed refusal arms, or `None` when the answer was a 2xx."""
    if answer.ok:
        return None
    if _outage(answer):
        return _unavailable(step, "identity_platform_refused_us", elapsed=elapsed)
    if answer.error_id == zitadel.SESSION_GONE:
        return SignIn(
            outcome=SignInOutcome.CEREMONY_GONE, step=Step.PASSWORD, reason="ceremony_gone"
        )
    if answer.status == 404 and not answer.error_id:
        # **A 404 WITH NO ERROR ID IS A ROUTE THAT IS NOT THERE, NOT A
        # JUDGEMENT** — fail-closed rule 2, on the shape a hand walk found.
        #
        # MEASURED on the pinned build (v4.17.1): a path this build does not
        # have answers `404 {"code":5,"message":"Not Found"}` for every
        # input, including a deliberately wrong one, with no `details[].id`
        # on any of them. Read as a judgement it is a person told their
        # authenticator is wrong over and over about a road that is not
        # there; read this way it is the outage it is.
        #
        # **The case that taught it was OUR OWN TYPO** — `/totp/_verify` for
        # `/totp/verify` — and that is worth keeping in view: this arm turns
        # a wrong path into an honest 503 instead of a false refusal, and it
        # cannot tell anybody WHOSE mistake the missing path is. A 503 that
        # nobody can clear is still a bug; it is just an honest one.
        #
        # The discriminator is the ID, and it is the one Zitadel gives us: a
        # judged 404 carries one (an unknown login name is `QUERY-Dfbg2` on
        # the session create, which is the shape A5's refusal road rides).
        return _unavailable(step, "not_on_this_build", elapsed=elapsed)
    return _refused(step, "check_refused", elapsed=elapsed)


# --- the seven entry points --------------------------------------------------


def begin(
    store: MutableMapping[str, Any],
    *,
    address: str,
    password: str,
    client_address: str = "",
    org_id: str = "",
    auth_request: str = "",
) -> SignIn:
    """Check an address and a password, and say what is left to do.

    The road: throttle → open a session carrying both checks → READ the
    factors back (rule 1) → ask what this person has enrolled → decide between
    *done*, *one more step* and *set up two-factor*. Every hop is preceded by
    the deadline check, which is why the count of calls is worth keeping low.
    """
    _forget(store)
    if throttled(address=address, client_address=client_address):
        log.info("accounts.signin.refused", reason="throttled")
        return SignIn(outcome=SignInOutcome.THROTTLED, step=Step.PASSWORD, reason="throttled")

    ceremony = _remember(
        store, started=monotonic(), step=Step.PASSWORD.value, auth_request=auth_request
    )
    opened = _call(
        lambda: zitadel.open_session(
            checks={"user": {"loginName": address}, "password": {"password": password}},
            org_id=org_id,
        )
    )
    if opened is None:
        store.pop(CEREMONY_KEY, None)
        return _unavailable(Step.PASSWORD, "identity_platform_unreachable")
    verdict = _judge(opened, Step.PASSWORD, elapsed=_elapsed(ceremony))
    if verdict is not None:
        _forget(store)
        return verdict

    session_id = str(opened.body.get("sessionId", ""))
    token = str(opened.body.get("sessionToken", ""))
    if not session_id:
        _forget(store)
        return _unavailable(Step.PASSWORD, "identity_platform_answered_no_session")
    ceremony = _remember(store, session_id=session_id, token=token)

    read = _next_call(store, lambda: zitadel.read_session(session_id=session_id))
    if isinstance(read, SignIn):
        return read
    verdict = _judge(read, Step.PASSWORD, elapsed=_elapsed(ceremony))
    if verdict is not None:
        _forget(store)
        return verdict
    if not _verified(read, "password"):
        # **Fail-closed rule 1 in one line.** A 2xx and a session and no
        # `factors.password.verifiedAt` is a refusal, not a pass.
        _forget(store)
        return _refused(Step.PASSWORD, "password_not_verified", elapsed=_elapsed(ceremony))

    user_id = _user_id_of(read)
    _remember(store, user_id=user_id)
    log.info("accounts.signin.checked", subject=user_id, seconds=_elapsed(ceremony))
    # **The person's OWN organisation, read off the session** — V-A-W3 found
    # `login_settings` being asked with no org at all, so an org that had
    # turned `forceMfa` on was answered with the INSTANCE default and its
    # people were landed with no second step. The session read carries
    # `factors.user.organizationId` (measured), and the caller's `org_id`
    # still wins when it gave one.
    whose = org_id or _org_of(read)
    _remember(store, org_id=whose)
    return _after_password(store, org_id=whose)


def passkey_begin(
    store: MutableMapping[str, Any],
    *,
    address: str,
    client_address: str = "",
    org_id: str = "",
) -> SignIn:
    """Design J6's entrance (a): an address and a passkey, and no password.

    **Not the usernameless road the design drew, and that is a measurement
    rather than a shortcut.** J6 (a) says "a WebAuthn challenge from the
    Session API for DISCOVERABLE credentials". A9's drive asked this build
    for exactly that — `POST /v2/sessions` with a `webAuthN` challenge and no
    `user` check — and it answers **400 `COMMAND-eeR2e` "User ID missing"**,
    for our host and for Zitadel's alike. There is no usernameless passkey
    road on v4.17.1 through this door.

    What IS there, measured on the same drive: the one-shot with a LOGIN NAME
    and no password answers **201** carrying the request options, and the
    assertion finishes it **200** with `factors.webAuthN.verifiedAt` set. So
    the person types the address they always type and never types a
    password, which is the whole of what the affordance promises.

    The throttle is the password road's, on the same two buckets: this is a
    form that takes an address and asks the platform about it, and a limit
    that only counted the password road would be a limit with a door beside
    it.
    """
    _forget(store)
    if throttled(address=address, client_address=client_address):
        log.info("accounts.signin.refused", reason="throttled")
        return SignIn(outcome=SignInOutcome.THROTTLED, step=Step.PASSWORD, reason="throttled")

    ceremony = _remember(store, started=monotonic(), step=Step.PASSWORD.value)
    opened = _call(
        lambda: zitadel.open_session(
            checks={"user": {"loginName": address}},
            challenges={
                "webAuthN": {
                    "domain": _rp_domain(),
                    "userVerificationRequirement": "USER_VERIFICATION_REQUIREMENT_REQUIRED",
                }
            },
            org_id=org_id,
        )
    )
    if opened is None:
        store.pop(CEREMONY_KEY, None)
        return _unavailable(Step.PASSWORD, "identity_platform_unreachable")
    if opened.status == 500 and opened.error_id == zitadel.WEBAUTHN_NO_CREDENTIAL:
        # No session was made, so the person has to be resolved by NAME for
        # the elsewhere/none discrimination. One read, on the failure path
        # only, and a read we cannot make answers the kind rather than the
        # sentence (`_why_no_webauthn_for`).
        try:
            found = zitadel.find_user(username=address)
        except zitadel.ZitadelError:
            found = None
        who = str(found.get("id", "")) if isinstance(found, Mapping) else ""
        return _unanswerable(store, _why_no_webauthn_for(who, FactorKind.PASSKEY))
    verdict = _judge(opened, Step.PASSWORD, elapsed=_elapsed(ceremony))
    if verdict is not None:
        _forget(store)
        return verdict

    session_id = str(opened.body.get("sessionId", ""))
    options = _webauthn_options(opened)
    if not session_id or not options:
        _forget(store)
        return _unavailable(Step.PASSWORD, "identity_platform_answered_no_challenge")
    _remember(
        store,
        session_id=session_id,
        token=str(opened.body.get("sessionToken", "")),
        pending=FactorKind.PASSKEY.value,
        kinds=[FactorKind.PASSKEY.value],
        step=Step.FACTOR.value,
    )
    # **The create's answer carries NO factors block** — MEASURED on v4.17.1:
    # `POST /v2/sessions` answers `details`, `sessionId` and `sessionToken`
    # and nothing else. Reading `factors.user.id` off it gave an empty
    # subject, `asserted_person` then found nobody, and a person who had just
    # proved a passkey read the outage sentence and a 503 (V-A-W3). The id is
    # on the session READ, which is where `begin` has always taken it from.
    read = _next_call(store, lambda: zitadel.read_session(session_id=session_id))
    if isinstance(read, SignIn):
        return read
    verdict = _judge(read, Step.PASSWORD, elapsed=_elapsed(ceremony))
    if verdict is not None:
        _forget(store)
        return verdict
    _remember(store, user_id=_user_id_of(read))
    return SignIn(
        outcome=SignInOutcome.CONTINUE,
        step=Step.FACTOR,
        kinds=(FactorKind.PASSKEY,),
        passkey_options=options,
    )


def challenge(store: MutableMapping[str, Any], *, kind: str) -> SignIn:
    """Ask Zitadel to put a code where the person can read it — or don't.

    A `totp` kind needs nothing sent: the authenticator is already showing a
    code, and a round trip to say so is a round trip against the deadline.
    """
    ceremony = _ceremony(store)
    if not ceremony.get("session_id"):
        return SignIn(
            outcome=SignInOutcome.CEREMONY_GONE, step=Step.PASSWORD, reason="ceremony_gone"
        )
    chosen = _kind(kind)
    # **The offer is the ceremony's, not the request's.** `_after_password`
    # already intersected ENROLLED with DELIVERABLE and wrote the result into
    # the ceremony, so a kind that is not in there is one this page never drew
    # a chip for — a typed action, a stale tab, or somebody trying the email
    # road on an instance whose SMTP went away between two POSTs. All three
    # are the same dead end with a sentence, and none of them is a request
    # this seam should carry to Zitadel.
    if chosen is None or chosen.value not in list(ceremony.get("kinds") or []):
        return _unanswerable(store, kind)
    sender = _foreign_sender(_smtp()) if chosen is FactorKind.OTP_EMAIL else ""

    wanted = FACTOR_CHALLENGE_NAMES[chosen]
    if wanted is None:
        _remember(store, pending=chosen.value, step=Step.FACTOR.value)
        return SignIn(
            outcome=SignInOutcome.CONTINUE,
            step=Step.FACTOR,
            reason="",
            kinds=(chosen,),
            foreign_sender=sender,
        )

    body: dict[str, Any] = {wanted: {}}
    if wanted == "webAuthN":
        body[wanted] = {
            "domain": _rp_domain(),
            "userVerificationRequirement": "USER_VERIFICATION_REQUIREMENT_REQUIRED",
        }
    answer = _next_call(
        store,
        lambda: zitadel.check_session(
            session_id=str(ceremony["session_id"]),
            token=str(ceremony.get("token", "")),
            challenges=body,
        ),
    )
    if isinstance(answer, SignIn):
        return answer
    if answer.status == 500 and answer.error_id == zitadel.WEBAUTHN_NO_CREDENTIAL:
        # **Fail-closed rule 4, and the one place a 500 is NOT an outage.**
        # MEASURED (M9, re-measured by A9 on v4.17.1): this build answers 500
        # for a WebAuthn challenge begun for a person with no registered
        # credential. Read as an outage it would be retried forever for
        # somebody who simply has no passkey.
        #
        # **And for a person whose passkey is bound somewhere else — the SAME
        # status and the SAME error id** (A9's drive: a credential registered
        # for `localhost` answers `500 WEBAU-4G8sw` to a begin on `127.0.0.1`
        # and the other way round). The two cannot be told apart from this
        # answer, so they are told apart from what the person HAS.
        return _unanswerable(store, _why_no_webauthn(store, chosen))
    verdict = _judge(answer, Step.FACTOR, elapsed=_elapsed(ceremony))
    if verdict is not None:
        _forget(store)
        return verdict
    _remember(store, pending=chosen.value, step=Step.FACTOR.value, **_rotation(answer))
    return SignIn(
        outcome=SignInOutcome.CONTINUE,
        step=Step.FACTOR,
        reason="",
        kinds=(chosen,),
        foreign_sender=sender,
        passkey_options=_webauthn_options(answer) if wanted == "webAuthN" else "",
    )


def answer(store: MutableMapping[str, Any], *, code: str = "", assertion: str = "") -> SignIn:
    """Verify the factor the ceremony is waiting on. The last hop of J2 and J6.

    Two payload shapes, because there are two kinds of factor: six digits a
    person reads off something, and a signed assertion a browser produced.
    Which one is used is decided by the KIND the ceremony is waiting on, never
    by which argument the caller filled in — a door that chose on truthiness
    would send a code as an assertion the day somebody typed into the wrong
    field.
    """
    ceremony = _ceremony(store)
    if not ceremony.get("session_id"):
        return SignIn(
            outcome=SignInOutcome.CEREMONY_GONE, step=Step.PASSWORD, reason="ceremony_gone"
        )
    chosen = _pending(ceremony)
    if chosen is None:
        return _unanswerable(store, str(ceremony.get("pending", "")))

    check_name = FACTOR_CHECK_NAMES[chosen]
    if check_name == "webAuthN":
        # MEASURED (A9, v4.17.1): the finish is
        # `PATCH /v2/sessions/{id}` with
        # `checks.webAuthN.credentialAssertionData` carrying the browser's
        # own credential object, and it answers 200 with
        # `factors.webAuthN.verifiedAt` set.
        signed = _assertion(assertion)
        if signed is None:
            return _refused(Step.FACTOR, "assertion_unreadable", elapsed=_elapsed(ceremony))
        payload: dict[str, Any] = {check_name: {"credentialAssertionData": signed}}
    else:
        payload = {check_name: {"code": code}}
    answered = _next_call(
        store,
        lambda: zitadel.check_session(
            session_id=str(ceremony["session_id"]),
            token=str(ceremony.get("token", "")),
            checks=payload,
        ),
    )
    if isinstance(answered, SignIn):
        return answered
    verdict = _judge(answered, Step.FACTOR, elapsed=_elapsed(ceremony))
    if verdict is not None:
        return _wrong_code(store, verdict)
    _remember(store, **_rotation(answered))

    read = _next_call(store, lambda: zitadel.read_session(session_id=str(ceremony["session_id"])))
    if isinstance(read, SignIn):
        return read
    verdict = _judge(read, Step.FACTOR, elapsed=_elapsed(ceremony))
    if verdict is not None:
        _forget(store)
        return verdict
    if not _verified(read, check_name):
        # Rule 1 again, on the factor rather than the password: the PATCH
        # answering 200 is not the code having been right.
        return _wrong_code(
            store, _refused(Step.FACTOR, "factor_not_verified", elapsed=_elapsed(ceremony))
        )
    return _finish(store, reason="factor")


def _assertion(raw: str) -> dict[str, Any] | None:
    """The browser's credential object, parsed. `None` when it is not one.

    Never trusted as a string and never forwarded blind: what arrives is a
    form field, and a form field is whatever the page was handed. A body this
    cannot read is a refusal of the ceremony, not a 500 and not a payload
    passed on to Zitadel to be refused there.
    """
    try:
        found = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return found if isinstance(found, dict) else None


def enrol(store: MutableMapping[str, Any]) -> SignIn:
    """Begin TOTP enrolment: the URI the QR is drawn from, and the secret."""
    ceremony = _ceremony(store)
    user_id = str(ceremony.get("user_id", ""))
    if not ceremony.get("session_id") or not user_id:
        return SignIn(
            outcome=SignInOutcome.CEREMONY_GONE, step=Step.PASSWORD, reason="ceremony_gone"
        )
    begun = _next_call(store, lambda: zitadel.begin_totp_enrolment(user_id=user_id))
    if isinstance(begun, SignIn):
        return begun
    verdict = _judge(begun, Step.ENROL, elapsed=_elapsed(ceremony))
    if verdict is not None:
        _forget(store)
        return verdict
    _remember(store, pending=FactorKind.TOTP.value, step=Step.ENROL.value)
    days = _may_skip(store)
    return SignIn(
        outcome=SignInOutcome.CONTINUE,
        step=Step.ENROL,
        kinds=(FactorKind.TOTP,),
        enrolment_uri=str(begun.body.get("uri", "")),
        enrolment_secret=str(begun.body.get("secret", "")),
        may_skip=days > 0,
        skip_days=days,
    )


def confirm_enrolment(store: MutableMapping[str, Any], *, code: str) -> SignIn:
    """Finish enrolment with the six digits the authenticator shows."""
    ceremony = _ceremony(store)
    user_id = str(ceremony.get("user_id", ""))
    if not ceremony.get("session_id") or not user_id:
        return SignIn(
            outcome=SignInOutcome.CEREMONY_GONE, step=Step.PASSWORD, reason="ceremony_gone"
        )
    confirmed = _next_call(
        store, lambda: zitadel.confirm_totp_enrolment(user_id=user_id, code=code)
    )
    if isinstance(confirmed, SignIn):
        return confirmed
    verdict = _judge(confirmed, Step.ENROL, elapsed=_elapsed(ceremony))
    if verdict is not None:
        # Same reading as `answer`'s: the platform judged six digits and the
        # enrolment it judged them against is still open, so the person types
        # the next code their app shows rather than starting the whole
        # ceremony — and a new secret — over. Bounded by the same counter.
        return _wrong_code(store, verdict)
    return _finish(store, reason="enrolled")


def skip_enrolment(store: MutableMapping[str, Any]) -> SignIn:
    """*Not now* — offered only when the org's `mfaInitSkipLifetime` allows it.

    A skip the settings do not allow is `REFUSED` rather than silently
    honoured: the person's org asked for a second step, and a seam that let
    the button work anyway would be the product overruling the customer's
    policy from a template.
    """
    ceremony = _ceremony(store)
    if not ceremony.get("session_id"):
        return SignIn(
            outcome=SignInOutcome.CEREMONY_GONE, step=Step.PASSWORD, reason="ceremony_gone"
        )
    if not _may_skip(store):
        return _refused(Step.ENROL, "skip_not_offered", elapsed=_elapsed(ceremony))
    return _finish(store, reason="skipped")


def cancel(store: MutableMapping[str, Any]) -> SignIn:
    """*Never mind.* The session is closed, the ceremony deleted, nothing changed."""
    elapsed = _elapsed(_ceremony(store))
    _forget(store)
    log.info("accounts.signin.finished", outcome="cancelled", seconds=elapsed)
    return SignIn(outcome=SignInOutcome.CANCELLED, step=Step.NOTHING, reason="cancelled")


def asserted_person(*, subject: str, login_name: str) -> Person | None:
    """Who the platform says this is, for the door to hand to allauth. **A5.**

    **The one thing `SignIn.done` cannot carry, and the reason it is here
    rather than in the door.** `_finish` answers a `subject` — an opaque
    Zitadel id — because that is all a CHECK produces. What the adapter
    decides on is an *assertion*: an address, and whether the platform says it
    VERIFIED that address (`adapter.asserted_email`, whose first rule is that
    a missing flag is `False`). On the OIDC road that flag is the
    `email_verified` claim; on this road there is no id token, so it is read
    off the platform's own record for the person the session verified.

    **Read, never inferred from the typed address.** The person typed a login
    name and proved a password against it; neither of those is the platform
    saying the mailbox is theirs. A door that passed `verified=True` because
    the password was right would make `_platform_login`'s first refusal
    unreachable — the check would still be there and nothing could ever fire
    it, which is the shape rule 1 of this module exists to refuse.

    **The id is cross-checked, and a disagreement is `None`.** The search is
    by login name; the ceremony is by subject. If the row that comes back is
    not the person the session verified, the two reads name two people and
    there is no reading of that which is safe to act on — the same posture the
    adapter takes when its own two identifiers disagree.

    `None` for every could-not-look as well: no credential, a transport
    failure, no such row, a row with no address. The door answers `unavailable`
    for it and never `refused` — fail-closed rule 2, on the last read of the
    road rather than on the check itself.

    MEASURED against the pinned build on 2026-09-19 (`POST
    /management/v1/users/_search`): a human row carries
    `human.email.email` and `human.email.isEmailVerified`, and a machine row
    carries no `human` block at all.
    """
    # **BY ID, NOT BY NAME** — V-A-W3 found a person in another Zitadel
    # organisation authenticating perfectly and then meeting a 503 at the
    # landing, because `POST /management/v1/users/_search` is scoped to the
    # caller's org and answered no rows. `GET /v2/users/{id}` is not scoped:
    # MEASURED on v4.17.1, it answers 200 with the same `human.email` block
    # for a person in any organisation on the instance. The id is the one the
    # ceremony verified, so there is nothing left to cross-check it against
    # and nothing to guess: a read that answers a different person is not a
    # shape this call has.
    read = _call(lambda: zitadel.read_user(user_id=subject))
    if read is None or not read.ok:
        log.info("accounts.signin.unavailable", reason="person_unreadable")
        return None
    found = read.body.get("user")
    if not isinstance(found, Mapping) or str(found.get("userId", "")) != subject:
        log.info("accounts.signin.unavailable", reason="person_unreadable")
        return None
    human = found.get("human")
    email = human.get("email") if isinstance(human, Mapping) else None
    if not isinstance(email, Mapping):
        log.info("accounts.signin.unavailable", reason="person_unreadable")
        return None
    address = str(email.get("email", "") or "").strip().lower()
    if not address:
        log.info("accounts.signin.unavailable", reason="person_unreadable")
        return None
    # **`isVerified`, not `isEmailVerified`** — MEASURED on v4.17.1: the v2
    # read (`GET /v2/users/{id}`) spells the flag `isVerified`, and the v1
    # management SEARCH this call used to make spells the same fact
    # `isEmailVerified`. Two surfaces, two spellings, one truth; reading the
    # v1 name off a v2 body makes every person unverified and every landing
    # a refusal. The fake carries both spellings on purpose and is what
    # caught this one before a browser did.
    return Person(subject=subject, address=address, verified=bool(email.get("isVerified")))


def sign_in_rules(*, org_id: str = "") -> Mapping[str, Any]:
    """The org's password rules, for the Choose-your-password frame (M11).

    Empty when the read fails, and that is the designed degradation: a frame
    with no rule sentence still works, and a frame that refused to render
    because a settings read timed out would be a sign-in door taken down by a
    sentence.
    """
    try:
        found = zitadel.password_complexity(org_id=org_id)
    except zitadel.ZitadelError:
        return {}
    settings_block = found.body.get("settings") if found.ok else None
    return dict(settings_block) if isinstance(settings_block, Mapping) else {}


# --- the shared middles ------------------------------------------------------


def _call(make: Callable[[], zitadel.Probe]) -> zitadel.Probe | None:
    """One Zitadel call, with the transport failure folded into `None`.

    `ZitadelError` here is "no credential" or "the socket never answered" —
    the two states `Probe` deliberately does not model, because they are not
    answers. Both are fail-closed rule 2's: an outage, never a refusal.
    """
    try:
        return make()
    except zitadel.ZitadelError:
        return None


def _next_call(
    store: MutableMapping[str, Any], make: Callable[[], zitadel.Probe]
) -> zitadel.Probe | SignIn:
    """The deadline check, then the call. **Every hop after the first.**

    Returns a `SignIn` when it refuses to make the call at all, which is what
    makes `test_the_deadline_bounds_the_whole_check` able to assert that the
    next request was never sent rather than that it came back late.
    """
    ceremony = _ceremony(store)
    if _out_of_time(ceremony):
        elapsed = _elapsed(ceremony)
        _forget(store)
        return _unavailable(Step.PASSWORD, "deadline_reached", elapsed=elapsed)
    answered = _call(make)
    if answered is None:
        _forget(store)
        return _unavailable(Step.PASSWORD, "identity_platform_unreachable")
    return answered


def _rotation(answer: zitadel.Probe) -> dict[str, str]:
    """The rotated session token, when there IS one. **M8.**

    A PATCH that verified something answers a new token; one that verified
    nothing answers none at all rather than the one it was sent. So an absent
    `sessionToken` means "keep the one you have", and a writer that wrote it
    anyway would put `""` where the credential was.
    """
    rotated = str(answer.body.get("sessionToken", "") or "")
    return {"token": rotated} if rotated else {}


def _org_of(read: zitadel.Probe) -> str:
    """Which organisation the verified person belongs to. **MEASURED shape.**

    `GET /v2/sessions/{id}` answers `session.factors.user` carrying `id`,
    `loginName`, `displayName` and `organizationId`. The last is the one a
    login-settings read has to be scoped by, and it is the only place in a
    ceremony where it is known without asking again.
    """
    session = read.body.get("session")
    factors = session.get("factors") if isinstance(session, Mapping) else None
    user = factors.get("user") if isinstance(factors, Mapping) else None
    return str(user.get("organizationId", "")) if isinstance(user, Mapping) else ""


def _user_id_of(read: zitadel.Probe) -> str:
    session = read.body.get("session")
    if not isinstance(session, Mapping):
        return ""
    factors = session.get("factors")
    if not isinstance(factors, Mapping):
        return ""
    user = factors.get("user")
    return str(user.get("id", "")) if isinstance(user, Mapping) else ""


def _kind(name: str) -> FactorKind | None:
    try:
        return FactorKind(name)
    except ValueError:
        return None


def _pending(ceremony: Mapping[str, Any]) -> FactorKind | None:
    """Which kind `answer` is verifying — chosen, or the only one on offer.

    `challenge` records a choice; a person with exactly ONE enrolled kind
    never made one, because the page drew no chips for them. Falling back to
    the single offer is what keeps that person from having to press a button
    that says the same thing as the form they are already looking at.

    **The fallback is one, never the first of several.** Two kinds on offer
    and no choice recorded is a page that skipped a step, and answering the
    code against whichever kind happened to sort first would verify the wrong
    factor — so that case is `None`, which reaches the unanswerable sentence
    rather than a guess.
    """
    chosen = _kind(str(ceremony.get("pending", "")))
    if chosen is not None:
        return chosen
    offered = [name for name in (ceremony.get("kinds") or []) if _kind(str(name)) is not None]
    return _kind(str(offered[0])) if len(offered) == 1 else None


def _unanswerable(store: MutableMapping[str, Any], kind: str) -> SignIn:
    """A dead end with a sentence — never a hand-off, which is a 302 loop (K10)."""
    elapsed = _elapsed(_ceremony(store))
    _forget(store)
    log.info("accounts.signin.handed_off", reason="kind_unanswerable", seconds=elapsed)
    # The KIND is the reason, because the sentence is per kind (design J7) —
    # except when the kind is one this seam has never heard of, where naming
    # it would put a string Zitadel chose into a page's switch.
    if kind in (PASSKEY_ELSEWHERE, PASSKEY_NONE):
        # Two reasons that are not kinds, and they are the passkey's: design
        # J6's own state, and its opposite. Passed through rather than
        # flattened to `unknown_kind`, because the page has a sentence for
        # each that no kind's sentence says — and because the KIND's
        # sentence, "this account signs in with a passkey", is false of the
        # second one.
        return SignIn(
            outcome=SignInOutcome.KIND_UNANSWERABLE,
            step=Step.NOTHING,
            reason=kind,
        )
    named = _kind(kind)
    return SignIn(
        outcome=SignInOutcome.KIND_UNANSWERABLE,
        step=Step.NOTHING,
        reason=named.value if named is not None else "unknown_kind",
    )


def _wrong_code(store: MutableMapping[str, Any], verdict: SignIn) -> SignIn:
    """A refused CODE keeps the ceremony. Everything else still ends it.

    **WATCH F8, one screen later.** F8 is a wrong password costing the person
    both fields; a mistyped digit that sent them back to the address form
    would be the same defect on the second screen, and it is the one this
    door is being built to close. Zitadel judging six digits leaves the
    session perfectly alive — the password is still verified on it — so the
    honest answer is the same form with a sentence over it, not a ceremony
    thrown away.

    **Bounded, because a form that can be retried forever is a code oracle.**
    A six-digit code is a million guesses and a TOTP window is thirty
    seconds; the same per-minute counter that stands in front of the password
    (design C-14) stands here, bucketed on the platform's opaque user id
    rather than on the address, because by this point the address has already
    been proven and the id is what the ceremony holds. Over the limit the
    ceremony IS ended and the person reads the throttle sentence.
    """
    if verdict.outcome is not SignInOutcome.REFUSED:
        _forget(store)
        return verdict
    ceremony = _ceremony(store)
    limit = int(getattr(settings, "SIGNIN_THROTTLE_PER_MINUTE", 5))
    if _spend(_bucket("code", str(ceremony.get("user_id", ""))), limit):
        return verdict
    _forget(store)
    log.info("accounts.signin.refused", reason="throttled")
    return SignIn(outcome=SignInOutcome.THROTTLED, step=Step.PASSWORD, reason="throttled")


def offered(store: Mapping[str, Any]) -> tuple[FactorKind, ...]:
    """Which kinds the ceremony is currently offering. **A read, for the door.**

    The page has to redraw the chooser on every POST that does not land — a
    refused code, a chip pressed — and the population it drew the first time
    is in the ceremony, not in the request. Exposed as a function rather than
    by letting the door read `CEREMONY_KEY` itself, because the store's shape
    is this module's business and a door reading a dict key would be a second
    place that knows it.
    """
    ceremony = _ceremony(store)
    found = [_kind(str(name)) for name in (ceremony.get("kinds") or [])]
    return tuple(one for one in found if one is not None)


def asked_for(store: Mapping[str, Any]) -> FactorKind | None:
    """Which kind the ceremony is waiting on. **A read, for the door.**

    `offered` says what the chooser draws; this says which of them the code
    field above it belongs to, and the page needs both on every re-render —
    a refused code must come back asking for the SAME kind, not for whichever
    one the door prefers.
    """
    return _pending(_ceremony(store))


def _finish(store: MutableMapping[str, Any], *, reason: str) -> SignIn:
    """The one road to `DONE`, and it closes the session on the way out.

    **Mode A's finalize happens HERE, before the close, and the order is the
    whole of why it is here** (design C-10, rung A8). Zitadel mints the
    client's code against the session named in the finalize, so a ceremony
    that closed its session first — ADR ident-12's rule, which every other
    exit of this module obeys — would have nothing left to finalize with. Four
    roads reach this function (password, factor, enrolment, invite) and the
    finalize belongs on every one of them exactly once, which is what makes
    this the one place it can live.
    """
    ceremony = _ceremony(store)
    subject = str(ceremony.get("user_id", ""))
    realm = str(ceremony.get("org_id", ""))
    seconds = _elapsed(ceremony)
    request_id = str(ceremony.get("auth_request", "") or "")

    handed_back: SignIn | None = None
    if request_id:
        handed_back = _hand_back(ceremony, request_id=request_id, subject=subject)

    # The session is left OPEN exactly when a client is about to spend a code
    # minted against it — see `_forget`'s own note, which carries the measured
    # error a close produces. Every other exit closes, ADR ident-12 unchanged.
    _forget(store, close=handed_back is None or not handed_back.callback_url)
    if handed_back is not None and handed_back.outcome is not SignInOutcome.DONE:
        return handed_back
    log.info(
        "accounts.signin.finished",
        outcome="done",
        reason=reason,
        subject=subject,
        seconds=seconds,
    )
    return SignIn(
        outcome=SignInOutcome.DONE,
        step=Step.NOTHING,
        reason=reason,
        subject=subject,
        realm=realm,
        callback_url=handed_back.callback_url if handed_back is not None else "",
    )


def _hand_back(ceremony: Mapping[str, Any], *, request_id: str, subject: str) -> SignIn:
    """Give the verified session back to the OIDC client that sent them.

    Fail-closed the same way every other call in this module is: a refusal
    aimed at OUR credential is an outage and never the person's fault — and
    on this road the likeliest one is exactly that, because a deployment
    whose machine user lacks `IAM_LOGIN_CLIENT` answers `403 AUTH-AWfge` to
    every finalize while every other part of the sign-in works (M2). Telling
    that person their link expired would send them round the journey again,
    for ever.
    """
    answer = _call(
        lambda: zitadel.finalize_auth_request(
            request_id=request_id,
            session_id=str(ceremony.get("session_id", "")),
            session_token=str(ceremony.get("token", "")),
        )
    )
    if answer is None:
        return _unavailable(Step.NOTHING, "identity_platform_unreachable")
    if not answer.ok:
        if answer.error_id in AUTH_REQUEST_GONE_IDS:
            log.info("accounts.signin.refused", reason="request_gone", subject=subject)
            return SignIn(
                outcome=SignInOutcome.REQUEST_GONE, step=Step.NOTHING, reason="request_gone"
            )
        log.info("accounts.signin.unavailable", reason="finalize_refused", subject=subject)
        return _unavailable(Step.NOTHING, "finalize_refused")

    callback = str(answer.body.get("callbackUrl", "") or "")
    if not callback:
        # A 200 with no callback URL is an answer this seam cannot read, and
        # fail-closed rule 2 makes that an outage rather than a landing with
        # nowhere to land (a redirect to "" is a redirect to this page).
        log.info("accounts.signin.unavailable", reason="finalize_answered_no_callback")
        return _unavailable(Step.NOTHING, "finalize_answered_no_callback")
    log.info("accounts.signin.finished", outcome="finalized", subject=subject)
    return SignIn(
        outcome=SignInOutcome.DONE, step=Step.NOTHING, reason="finalized", callback_url=callback
    )


def _after_password(store: MutableMapping[str, Any], *, org_id: str) -> SignIn:
    """Password verified. One more step, set one up, or land."""
    ceremony = _ceremony(store)
    methods = _next_call(
        store, lambda: zitadel.authentication_methods(user_id=str(ceremony.get("user_id", "")))
    )
    if isinstance(methods, SignIn):
        return methods
    if not methods.ok:
        # A read we could not make is an outage by rule 2 — never a silent
        # "then there are no factors", which would walk straight past a
        # second step the person's org asked for.
        _forget(store)
        return _unavailable(Step.PASSWORD, "enrolment_unreadable", elapsed=_elapsed(ceremony))

    kinds = _enrolled(methods)
    if kinds:
        offered, sender = deliverable(kinds)
        if not offered:
            # **ENROLLED but not DELIVERABLE, and that is a dead end with a
            # sentence** (K10, design J7's `kind_unanswerable` row). The kind
            # named is the person's FIRST enrolled one, because the sentence
            # is about what this account signs in with — not about the five
            # this page happens to know the names of.
            return _unanswerable(store, kinds[0].value)
        _remember(store, step=Step.FACTOR.value, kinds=[one.value for one in offered])
        # **THE FACTOR IS ASKED FOR HERE, NOT LEFT FOR THE PAGE TO ASK LATER**
        # — two defects V-A-W3 found live, and they are one line apart.
        #
        # (1) A ceremony that recorded `kinds` and no `pending` left `answer`
        # reading `_pending()` as empty, and `_pending` only falls back when
        # there is exactly ONE offer — so every person with two enrolled
        # kinds typed a correct code and read "this account signs in a way
        # this page can't ask for", with the ceremony thrown away. The page
        # cannot record it either: it draws what it is handed.
        #
        # (2) An emailed code has to be SENT. Nothing on the password road
        # called `challenge`, so the form asked for a code Zitadel had never
        # been told to mail: Mailpit stayed empty and the only way to make it
        # send was a chip for the kind already being asked for, which the
        # page deliberately does not draw.
        #
        # So the seam picks the kind it will ask for and asks for it, in the
        # same breath as saying there is one.
        return _ask_for(store, offered, sender=sender)

    forced, days = _mfa_policy(store, org_id=org_id)
    if isinstance(forced, SignIn):
        return forced
    if forced:
        _remember(store, step=Step.ENROL.value)
        return SignIn(
            outcome=SignInOutcome.CONTINUE,
            step=Step.ENROL,
            may_skip=days > 0,
            skip_days=days,
        )
    return _finish(store, reason="password")


#: Which kind to ask for first when a person has several. **The seam's, not
#: the page's**, because the seam is what records `pending` and sends the
#: challenge — a page that chose would be choosing after the code was mailed.
#: An authenticator app is already showing a code, so it costs no round trip
#: and nothing has to arrive.
ASK_ORDER: tuple[FactorKind, ...] = (
    FactorKind.TOTP,
    FactorKind.PASSKEY,
    FactorKind.OTP_EMAIL,
    FactorKind.OTP_SMS,
    FactorKind.U2F,
)


def _ask_for(
    store: MutableMapping[str, Any], offered: tuple[FactorKind, ...], *, sender: str
) -> SignIn:
    """Pick the kind to ask for, send its challenge if it needs one, and say so."""
    chosen = next((kind for kind in ASK_ORDER if kind in offered), offered[0])
    if FACTOR_CHALLENGE_NAMES[chosen] is None:
        _remember(store, pending=chosen.value, step=Step.FACTOR.value)
        return SignIn(
            outcome=SignInOutcome.CONTINUE,
            step=Step.FACTOR,
            kinds=offered,
            foreign_sender=sender,
        )
    asked = challenge(store, kind=chosen.value)
    if asked.outcome is not SignInOutcome.CONTINUE:
        return asked
    # The challenge answers about ONE kind; the page still draws the chooser
    # it was going to draw, so the offer is put back.
    return SignIn(
        outcome=SignInOutcome.CONTINUE,
        step=Step.FACTOR,
        kinds=offered,
        foreign_sender=asked.foreign_sender or sender,
        passkey_options=asked.passkey_options,
    )


def _enrolled(methods: zitadel.Probe) -> tuple[FactorKind, ...]:
    """Which of the five closed kinds this person has. Unknown names are dropped.

    Dropped rather than forwarded, by fail-closed rule 4: a kind nobody has
    written an answer path for must not become a chip on the page. A person
    whose ONLY kind is unknown therefore reaches the `kind_unanswerable`
    sentence rather than a form that cannot work. `ZITADEL_PASSWORD_METHOD`
    is dropped by the same filter and for a different reason, stated there.
    """
    reported = methods.body.get("authMethodTypes")
    if not isinstance(reported, list):
        return ()
    found = [ZITADEL_FACTOR_NAMES[str(one)] for one in reported if str(one) in ZITADEL_FACTOR_NAMES]
    return tuple(dict.fromkeys(found))


#: The kinds this door knows how to put in front of a person AT ALL, before
#: the deployment is asked whether it can deliver them. Two of the closed
#: five, and the three that are missing are missing for stated reasons:
#:
#: * `OTP_SMS` — nothing in this tree can read whether the instance has an SMS
#:   provider (`zitadel.py` has no such call), so a texted-code chip would be
#:   a door that looks available and refuses, which design J2-c calls worse
#:   than no door. J7's sentence for the kind is the honest answer, and it is
#:   what this omission renders. MEASURED on the pinned build on 2026-09-19:
#:   `POST /v2/users/{id}/otp_sms` answers `400 COMMAND-Q54j2` — *Multifactor
#:   OTP (OneTimePassword) isn't ready* — so on this instance the kind cannot
#:   even be ENROLLED and never reaches `authentication_methods`. The
#:   exclusion is therefore belt as well as braces, and it is fail-closed
#:   rather than read: an instance where SMS IS ready still gets no chip, and
#:   that is this seam's declared blind spot rather than a claim about SMS.
#: * `U2F`, `PASSKEY` — answering either needs a WebAuthn ceremony in the
#:   browser, which is design J6 and is not built. The seam already refuses
#:   them for a second, measured reason (M9's `WEBAU-4G8sw` for a person with
#:   no credential on this relying party), and a chip for a road that ends in
#:   a 500 is worse than the sentence.
#:
#: A kind leaving this set is a page that stops offering something; a kind
#: joining it is a rung that built the road first. Neither is a setting.
#:
#: **`PASSKEY` joins CONDITIONALLY** (A9) and is therefore not in the literal
#: below: its road exists — A9's drive measured begin **201** and finish
#: **200** on our own host, from a login name and with no password — but only
#: where the deployment's host is a legal relying-party id. See
#: `answerable_here`, which is what `deliverable` actually asks.
ANSWERABLE_HERE = frozenset({FactorKind.TOTP, FactorKind.OTP_EMAIL})


def answerable_here() -> frozenset[FactorKind]:
    """`ANSWERABLE_HERE`, plus the kinds whose road this DEPLOYMENT can run.

    One kind is deployment-conditional rather than absolute, and it is the
    passkey: the ceremony is real and measured, and a host that is an IP
    address cannot run it in any browser (`passkey_road_open`). `U2F` stays
    out — the same WebAuthn ceremony would answer it, but nothing here has
    ever driven a security key, and a chip for an untested road is the door
    that looks available and refuses.
    """
    return ANSWERABLE_HERE | ({FactorKind.PASSKEY} if passkey_road_open() else frozenset())


def deliverable(kinds: tuple[FactorKind, ...]) -> tuple[tuple[FactorKind, ...], str]:
    """ENROLLED ∩ DELIVERABLE, and the foreign sender to name. **A6.1.**

    Two facts, deliberately answered together because they come from ONE
    read. An emailed code is deliverable exactly when the instance has an
    SMTP sender configured (`zitadel.smtp_configuration()`, the read
    `manage.py zitadel_audit` already makes); and when that sender turns out
    to belong to somebody else, the person waiting for the mail is the one
    who needs to know whose name it will arrive under — the same fact, off
    the same body, and asking twice would be two round trips for one answer.

    **Fail-closed, like everything else here.** An SMTP read that raises is
    "we could not look", and a kind we could not confirm is not offered: a
    chip that promises a code nobody sends is a person waiting at a form for
    mail that is never coming.
    """
    if FactorKind.OTP_EMAIL not in kinds:
        # The read is bought only by the person it is about. Somebody signing
        # in with an authenticator app pays no round trip to learn about mail.
        return tuple(one for one in kinds if one in answerable_here()), ""

    smtp = _smtp()
    here = answerable_here()
    offered = tuple(
        one for one in kinds if one in here and (one is not FactorKind.OTP_EMAIL or bool(smtp))
    )
    return offered, _foreign_sender(smtp)


def _smtp() -> dict[str, Any]:
    """The instance's SMTP sender, or `{}` — including when we could not look."""
    try:
        return zitadel.smtp_configuration()
    except zitadel.ZitadelError:
        log.info("accounts.signin.unavailable", reason="smtp_unreadable")
        return {}


def _foreign_sender(smtp: Mapping[str, Any]) -> str:
    """The sender address to print, and `""` when the sender is our own."""
    configured = dict(smtp)
    if not configured or not zitadel.is_foreign(configured):
        return ""
    return str(configured.get("senderAddress", "") or "")


def _mfa_policy(store: MutableMapping[str, Any], *, org_id: str) -> tuple[bool | SignIn, int]:
    """Does this org force a second step, and for how many days may it be skipped.

    The second half is a NUMBER of days rather than a flag because design
    J2-c prints it — *Not now (30 days)* — and a page handed a boolean would
    have to invent the number or drop it. Zero is "no skip", which is exactly
    the case where the link is not drawn at all.
    """
    found = _next_call(store, lambda: zitadel.login_settings(org_id=org_id))
    if isinstance(found, SignIn):
        return found, 0
    if not found.ok:
        _forget(store)
        return _unavailable(Step.PASSWORD, "login_settings_unreadable"), 0
    block = found.body.get("settings")
    block = dict(block) if isinstance(block, Mapping) else {}
    forced = bool(block.get("forceMfa")) or bool(block.get("forceMfaLocalOnly"))
    return forced, _skip_days(str(block.get("mfaInitSkipLifetime", "") or ""))


def _skip_days(lifetime: str) -> int:
    """`mfaInitSkipLifetime` as whole days. **A protobuf Duration, so seconds.**

    Zitadel sends `"2592000s"`. Anything this cannot read is zero — an
    unparseable lifetime is not a licence to offer a skip whose length nobody
    can state, and the org asked for the second step.
    """
    seconds = lifetime.strip().removesuffix("s")
    try:
        whole = int(float(seconds))
    except ValueError:
        return 0
    return max(whole // 86400, 1) if whole > 0 else 0


def _may_skip(store: MutableMapping[str, Any]) -> int:
    """How many days this person's ORG allows a skip for. Zero means none.

    **The org, never the instance.** This read used to pass `org_id=""`
    while the password step passed the person's own, so one ceremony asked
    two different questions: the enrolment face printed the INSTANCE's
    365-day skip over an org that allows none, and the button it drew
    landed the person with no second factor. The org is in the ceremony —
    put there at the password step, which is the only moment it is known —
    and every policy read on this road takes it from there.
    """
    forced, days = _mfa_policy(store, org_id=_org_in(store))
    return 0 if isinstance(forced, SignIn) else days


def _org_in(store: Mapping[str, Any]) -> str:
    """The organisation this ceremony belongs to, or `""` before it is known."""
    return str(_ceremony(store).get("org_id", ""))


def _webauthn_options(answer: zitadel.Probe) -> str:
    """The `publicKey` block Zitadel answered, as the JSON the browser takes.

    MEASURED (A9, v4.17.1): a 201/200 carrying a WebAuthn challenge puts it at
    `challenges.webAuthN.publicKeyCredentialRequestOptions.publicKey`, with
    `rpId` equal to the `domain` that was asked for and one entry in
    `allowCredentials` per registered credential. Empty when the answer does
    not carry one, which is a page that draws no ceremony rather than a page
    that hands `undefined` to `navigator.credentials.get`.
    """
    challenges = answer.body.get("challenges")
    block = challenges.get("webAuthN") if isinstance(challenges, Mapping) else None
    if not isinstance(block, Mapping):
        return ""
    options = block.get("publicKeyCredentialRequestOptions")
    inner = options.get("publicKey") if isinstance(options, Mapping) else None
    return json.dumps(inner, separators=(",", ":")) if isinstance(inner, Mapping) else ""


def _why_no_webauthn_for(user_id: str, chosen: FactorKind) -> str:
    """The discrimination, given the person's id rather than a ceremony."""
    if chosen not in (FactorKind.PASSKEY, FactorKind.U2F) or not user_id:
        return chosen.value
    methods = _call(lambda: zitadel.authentication_methods(user_id=user_id))
    if methods is None or not methods.ok:
        return chosen.value
    if chosen in _enrolled(methods):
        return PASSKEY_ELSEWHERE
    # They own none. The sentence for the KIND says "this account signs in
    # with a passkey", which is the one thing that is certainly not true.
    return PASSKEY_NONE if chosen is FactorKind.PASSKEY else chosen.value


def _why_no_webauthn(store: Mapping[str, Any], chosen: FactorKind) -> str:
    """Which of the two 500s this is: no passkey at all, or one bound elsewhere.

    **The build cannot tell us** — A9's drive measured the same `500
    WEBAU-4G8sw` for a person with no credential, for a credential registered
    against another relying party, and for a domain neither party owns. So the
    discrimination is made from what the person HAS: `authentication_methods`
    reports `…_PASSKEY` for somebody who registered one and does not for
    somebody who did not (measured in the same drive). A passkey they own that
    this host cannot use is design J6's `passkey_elsewhere`; no passkey at all
    is the ordinary kind-unanswerable road.

    A read we cannot make answers the kind, not the sentence: claiming
    "elsewhere" on a failed read would tell a person with no passkey to go and
    find the device they added it on.
    """
    if chosen not in (FactorKind.PASSKEY, FactorKind.U2F):
        return chosen.value
    return _why_no_webauthn_for(str(_ceremony(store).get("user_id", "")), chosen)


def passkey_road_open() -> bool:
    """Whether a WebAuthn ceremony can run on this deployment's host AT ALL.

    **Not a preference — the specification.** A relying-party id must be a
    valid domain string; an IP literal is not one, and every browser refuses
    a ceremony whose `rp.id` is an address. The template ships
    a base URL of `http://127.0.0.1:8000`, so the default local checkout is
    exactly that case: Zitadel will happily mint `rpId: "127.0.0.1"` (A9's
    drive measured a 201 and a 200 finish for it, server-side), and no
    browser will ever complete it.

    So the affordance is withheld rather than drawn-and-broken — design
    J2-c's rule about a door that looks available and refuses, one screen
    earlier. A deployment on a real hostname, or a laptop using
    `http://localhost:8000`, has the road open.
    """
    domain = _rp_domain()
    if not domain or domain == "localhost":
        # `localhost` is the one name the specification exempts, and it is
        # what a laptop actually types.
        return bool(domain)
    if all(part.isdigit() for part in domain.split(".")) and domain.count(".") == 3:
        return False
    return ":" not in domain and "." in domain


def _rp_domain() -> str:
    """The WebAuthn relying-party id: OUR host, never the identity platform's.

    MEASURED (M9): a passkey enrolled on Zitadel's own pages is bound to
    Zitadel's RP id and is refused on ours, which is design J6's
    `passkey_elsewhere` sentence rather than a bug to work around.

    **The host of the surface this request came in on** — the one the door
    bound (`core.context`'s `surface`), through the one URL builder: a passkey
    is bound to its host, so one enrolled on the staff host is never offered on
    the customer host (sessions and passkeys are per host). With no surfaces
    bound it is the deployment's own host, as it always was. A `{tenant}` host
    has no single name to bind a passkey to, and reads as the deployment's.
    """
    try:
        base = absolute_url(path="", surface=str(context.value("surface") or STAFF))
    except ValueError:
        base = surface_base_urls()[0]
    return base.split("://")[-1].split("/")[0].split(":")[0]


# --- the invite road (design C-11, J1-a; rung A7) ----------------------------
#
# The other way in, and the only one where somebody types a password they are
# CHOOSING rather than one they already have. Two entry points, deliberately
# asymmetric:
#
#   `invitation(user_id=…)` is a READ — the address, the rules, the deadline,
#   and whether there is anything to set at all. It takes no store and spends
#   nothing, because a page render must be repeatable: the code is single-use
#   (measured), so a GET that verified would kill the link of anybody who
#   opened it and reloaded.
#
#   `set_invited_password(store, …)` is the ACT, and it is the only place in
#   this tree allowed to call `zitadel.set_first_password`. It verifies the
#   code, sets the password, and then signs the person in through `begin` —
#   the same road, the same fail-closed rules, the same factor handling.
#
# **Fail-closed rule 5, and it is this road's own.** MEASURED on the pinned
# build: the machine PAT sets any person's password on a bare user id, with no
# invite code whatsoever. So the verify is not the platform checking a
# credential, it is THIS FUNCTION checking one — the only thing between a
# guessed user id and a stranger's account is the `if not verified.ok: return`
# below, and `test_the_password_is_never_written_without_a_verified_code`
# drives a wrong code and asserts the write never left the process.


@dataclass(frozen=True)
class Invitation:
    """What the Choose-your-password frame is drawn from. Frozen, like `SignIn`.

    `outcome` is a member of the same closed set the rest of this module
    answers in, narrowed to the four this read can produce: `CONTINUE` (there
    is a password to set), `INVITE_REFUSED` (they already have one),
    `INVITE_GONE` (the platform does not know that user id) and `UNAVAILABLE`
    (we could not look).
    """

    outcome: SignInOutcome
    #: The address the PLATFORM answered for this user id. Never the URL's.
    address: str = ""
    #: `GET /v2/settings/password/complexity`'s settings block, or empty.
    password_rules: Mapping[str, Any] = field(default_factory=dict)
    #: How long a code of this instance stands, or `None` when unreadable.
    lifetime: timedelta | None = None


def invitation(*, user_id: str) -> Invitation:
    """Read what the invited person's first screen says. **Spends nothing.**

    Three reads and no writes: who this is, what they have already enrolled,
    and what the org's password policy asks for. The middle one is the whole
    of how `INVITE_REFUSED` is told from `INVITE_GONE` — both answer
    `COMMAND-Wgn4q` at the verify (measured), so the discriminator is the
    person's own enrolled methods: a credential-less human answers a body with
    **no `authMethodTypes` key at all**, and one who has set a password
    answers `['AUTHENTICATION_METHOD_TYPE_PASSWORD']`.

    **The address is not part of the refused answer.** A link is a capability
    and its holder may see whose account it opens — but `INVITE_REFUSED` is
    reachable for any user id somebody types, and confirming an address for
    one would be an oracle over which accounts exist (the standing A9
    posture). So the address rides on `CONTINUE` and nowhere else.
    """
    read = _call(lambda: zitadel.read_human(user_id=user_id))
    if read is None:
        log.info("accounts.signin.unavailable", reason="invited_person_unreadable")
        return Invitation(outcome=SignInOutcome.UNAVAILABLE)
    if not read.ok:
        if _outage(read) or read.status in OUR_CREDENTIAL_STATUSES:
            log.info("accounts.signin.unavailable", reason="invited_person_unreadable")
            return Invitation(outcome=SignInOutcome.UNAVAILABLE)
        log.info("accounts.signin.refused", reason="invite_gone")
        return Invitation(outcome=SignInOutcome.INVITE_GONE)

    person = read.body.get("user")
    human = person.get("human") if isinstance(person, Mapping) else None
    email = human.get("email") if isinstance(human, Mapping) else None
    address = str(email.get("email", "") if isinstance(email, Mapping) else "").strip().lower()
    if not address:
        log.info("accounts.signin.unavailable", reason="invited_person_unreadable")
        return Invitation(outcome=SignInOutcome.UNAVAILABLE)

    methods = _call(lambda: zitadel.authentication_methods(user_id=user_id))
    if methods is None or not methods.ok:
        log.info("accounts.signin.unavailable", reason="invited_methods_unreadable")
        return Invitation(outcome=SignInOutcome.UNAVAILABLE)
    if _enrolled_anything(methods):
        log.info("accounts.signin.refused", reason="invite_refused", subject=user_id)
        return Invitation(outcome=SignInOutcome.INVITE_REFUSED)

    return Invitation(
        outcome=SignInOutcome.CONTINUE,
        address=address,
        password_rules=sign_in_rules(),
        lifetime=zitadel.invite_code_lifetime(),
    )


def set_invited_password(
    store: MutableMapping[str, Any],
    *,
    user_id: str,
    code: str,
    password: str,
    client_address: str = "",
) -> SignIn:
    """Verify the link, set the password, sign them in. **In that order, always.**

    The three steps are one function because the order is the security
    property (fail-closed rule 5 above) and an order enforced by two callers
    agreeing is an order one of them will eventually get wrong.

    The last step is `begin` rather than a shortcut: the person has just
    chosen a password, so checking it is one more call and it buys the whole
    of the other road — fail-closed rule 1 on the session's factors, the
    org's MFA policy, the factor and enrolment steps, the throttle. A road
    that minted a landing straight off a 200 from the write would be a second
    opinion about who is signed in, which is the thing this module has
    exactly one of.
    """
    verified = _call(lambda: zitadel.verify_invite_code(user_id=user_id, code=code))
    if verified is None:
        return _unavailable(Step.INVITE, "identity_platform_unreachable")
    if not verified.ok:
        if _outage(verified) or verified.status in OUR_CREDENTIAL_STATUSES:
            log.info("accounts.signin.unavailable", reason="invite_unverifiable")
            return _unavailable(Step.INVITE, "invite_unverifiable")
        log.info("accounts.signin.refused", reason="invite_gone")
        return SignIn(outcome=SignInOutcome.INVITE_GONE, step=Step.INVITE, reason="invite_gone")

    written = _call(lambda: zitadel.set_first_password(user_id=user_id, password=password))
    if written is None:
        return _unavailable(Step.INVITE, "identity_platform_unreachable")
    if not written.ok:
        if _outage(written) or written.status in OUR_CREDENTIAL_STATUSES:
            log.info("accounts.signin.unavailable", reason="password_unwritable")
            return _unavailable(Step.INVITE, "password_unwritable")
        log.info("accounts.signin.refused", reason="invite_weak")
        return SignIn(
            outcome=SignInOutcome.INVITE_WEAK,
            step=Step.INVITE,
            reason="invite_weak",
            refusal_detail=_policy_reason(written),
        )

    read = _call(lambda: zitadel.read_human(user_id=user_id))
    person = read.body.get("user") if read is not None and read.ok else None
    human = person.get("human") if isinstance(person, Mapping) else None
    email = human.get("email") if isinstance(human, Mapping) else None
    address = str(email.get("email", "") if isinstance(email, Mapping) else "").strip().lower()
    if not address:
        # The password IS set — the write answered 200 — so this is not a
        # refusal and the person is not locked out: their link is spent and
        # their password works at the sign-in form. An outage sentence is the
        # honest one, and the page it lands on carries that form.
        log.info("accounts.signin.unavailable", reason="invited_person_unreadable")
        return _unavailable(Step.INVITE, "invited_person_unreadable")

    log.info("accounts.signin.checked", subject=user_id, reason="invite_password_set")
    return replace(
        begin(store, address=address, password=password, client_address=client_address),
        login_name=address,
    )


def _enrolled_anything(methods: zitadel.Probe) -> bool:
    """Whether this person has ANY credential at the platform.

    Every kind, not only a password: somebody enrolled on a passkey alone has
    nothing for this screen to set either, and the honest answer for them is
    the same one — sign in instead. MEASURED: the answer for a
    credential-less human carries no `authMethodTypes` key at all.
    """
    return bool(methods.body.get("authMethodTypes") or [])


def _policy_reason(answer: zitadel.Probe) -> str:
    """The platform's own sentence about the password, with its ERROR ID GONE.

    `message` arrives as `"Password is too short (DOMAIN-HuJf6)"` — the prose
    a person can act on, with a token they must never read stapled to it
    (design J7's "must not" column for this frame). `Probe.error_id` already
    recovers ids from that parenthesis, so the id is stripped by comparing
    against it rather than by a regexp that would also eat a legitimate
    parenthesis in a translated policy string.
    """
    message = str(answer.body.get("message", "")).strip()
    error_id = answer.error_id
    if error_id and message.endswith(f"({error_id})"):
        message = message[: -len(f"({error_id})")].strip()
    return message if message and error_id not in message else ""


# --- Mode A: the OIDC round trip on our page (design C-10; rung A8) ---------
#
# The journey a person is in the MIDDLE of when they reach this page: an app —
# the browser RP through allauth, an assistant's MCP client, anything holding
# an OIDC client id — sent them to the platform's authorize endpoint, and with
# `loginVersion` declared (A2, A5) the platform sent them here with an auth
# request id instead of drawing its own page. The ceremony is the same one;
# what changes is what `done` MEANS. Without an auth request, `done` is a
# session on this product (the door hands the assertion to allauth). With one,
# `done` is a code for the app that sent them, and the door 302s there.
#
# `_finish` above is where that happens. The two functions here are the other
# two things Mode A needs: reading what the client asked for, so the page can
# say it, and telling the client when the person did not finish.

#: The three ids that all mean "there is nothing here to finish" — the read's,
#: the write's, and a second finalize of one already answered. Measured, all
#: three, because the door's sentence is the same for all three and a reader
#: matching one of them answers 503 for the other two.
AUTH_REQUEST_GONE_IDS = frozenset(
    {
        zitadel.AUTH_REQUEST_GONE,
        zitadel.AUTH_REQUEST_GONE_ON_WRITE,
        zitadel.AUTH_REQUEST_ALREADY_HANDLED,
    }
)


@dataclass(frozen=True)
class AuthRequest:
    """What the OIDC client that sent this person asked for. Frozen, like the rest.

    Narrow on purpose. The page needs three things and this carries three:
    whether the journey is still live, whether a REGISTRATION screen was asked
    for (there is no sign-up door here — ADR accounts-1 — so the page says so
    rather than drawing one), and which address to prefill. The client id, the
    scopes and the redirect URI are read and deliberately NOT carried: none of
    them is copy on any frame, and a page that displayed a client id would be
    showing a person a number they cannot check.
    """

    outcome: SignInOutcome
    #: `PROMPT_CREATE` was in the request's prompt list.
    wants_sign_up: bool = False
    #: The `loginHint` the client sent, lowercased, or `""`.
    login_hint: str = ""


def auth_request(*, request_id: str) -> AuthRequest:
    """Read the journey this page is standing in the middle of. **A read.**

    `REQUEST_GONE` for a 404 and for a request already answered; `UNAVAILABLE`
    for everything we could not look at — fail-closed rule 2 and 3 unchanged,
    and on this road the difference matters more than usual: "your link
    expired" sends a person back to the app to start again, and telling them
    that when the truth is our PAT lost a role would send them round for ever.
    """
    read = _call(lambda: zitadel.read_auth_request(request_id=request_id))
    if read is None:
        log.info("accounts.signin.unavailable", reason="auth_request_unreadable")
        return AuthRequest(outcome=SignInOutcome.UNAVAILABLE)
    if not read.ok:
        if read.error_id in AUTH_REQUEST_GONE_IDS:
            log.info("accounts.signin.refused", reason="request_gone")
            return AuthRequest(outcome=SignInOutcome.REQUEST_GONE)
        log.info("accounts.signin.unavailable", reason="auth_request_unreadable")
        return AuthRequest(outcome=SignInOutcome.UNAVAILABLE)

    found = read.body.get("authRequest")
    if not isinstance(found, Mapping):
        log.info("accounts.signin.unavailable", reason="auth_request_unreadable")
        return AuthRequest(outcome=SignInOutcome.UNAVAILABLE)
    # MEASURED: `prompt` is a LIST of enum names and is ABSENT when the client
    # asked for none — not an empty list — so `or []` is load-bearing.
    prompts = [str(one) for one in (found.get("prompt") or [])]
    return AuthRequest(
        outcome=SignInOutcome.CONTINUE,
        wants_sign_up=zitadel.PROMPT_CREATE in prompts,
        login_hint=str(found.get("loginHint", "") or "").strip().lower(),
    )


def refuse(store: MutableMapping[str, Any], *, request_id: str, reason: str) -> SignIn:
    """Tell the client the person did not finish, and get the way back for them.

    **Why a person who cannot finish is 302'd rather than left on a page.**
    They are in the middle of somebody else's journey: the app that sent them
    is waiting on a callback it will never get, and a sentence on our page is
    a dead end in a window the app may not even own. An `error=access_denied`
    at their own redirect URI is a state the app is written to handle.

    Only the TERMINAL refusals come here — a dead end and a *Never mind*. A
    wrong password does not: it is retryable, the ceremony survives it, and
    answering the auth request would burn a journey the person was one keystroke
    from finishing.

    Answers `callback_url=""` when the platform could not be told, and the
    door then falls back to its own sentence — there is no third thing to do,
    and pretending is worse than a page that says what happened.
    """
    answered = _call(
        lambda: zitadel.refuse_auth_request(
            request_id=request_id, reason=zitadel.REFUSE_ACCESS_DENIED, description=reason
        )
    )
    callback = str(answered.body.get("callbackUrl", "") or "") if answered is not None else ""
    if not callback:
        log.info("accounts.signin.unavailable", reason="refusal_not_delivered")
    else:
        log.info("accounts.signin.handed_off", reason=reason)
    _forget(store)
    return SignIn(
        outcome=SignInOutcome.CANCELLED,
        step=Step.NOTHING,
        reason=reason,
        callback_url=callback,
    )


# --- the reset road (design J5, settled by M6; rung A11b) -------------------
#
# **What this road is, after M6 measured where the mail lands.** The design
# drew a frame on which a person picks a new password. They cannot: MEASURED
# on the pinned build, the platform's reset mail carries a link to the
# PLATFORM's own `/ui/login/password/init` page with an empty `authRequestID`,
# and a mail has no application context for the per-application login-v2
# declaration to act on. So the honest road is: this page takes the address,
# asks the platform to send its own mail, and says where that mail goes. The
# person sets the password there and comes back here to sign in.
#
# **No enumeration, in both of the ways it leaks.** The page is identical for
# an address with an account and one without — that half is the door's. This
# half is the other one: the two roads take a different number of platform
# calls (a lookup, or a lookup and a write), and MEASURED on this instance
# that is 16 ms against 6 ms — a 2.6x difference anybody can average out over
# a few hundred samples, and the per-address throttle does not bound an
# attacker walking a THOUSAND addresses once each. So the road answers on a
# floor: it pads to `RESET_FLOOR_SECONDS` and both roads leave at the same
# time.

#: How long the reset road takes, both roads, always. A CONSTANT rather than
#: a setting on purpose: the two clocks above are deployment properties — how
#: slow this network is — and this is a security floor, which is not
#: something a deployment should be able to turn down to zero without
#: editing code and reading this paragraph. 250 ms is comfortably above the
#: slower road as measured (16 ms) with room for a loaded instance, and below
#: what a person waiting for a page notices.
RESET_FLOOR_SECONDS = 0.25


def request_reset(
    store: MutableMapping[str, Any],
    *,
    address: str,
    client_address: str = "",
) -> SignIn:
    """Ask the platform to mail its reset link. **Says nothing about who exists.**

    Three answers and only three: `THROTTLED` (our own limit, and the same
    limit the password road spends, because two roads with two buckets is one
    bucket an attacker picks), `UNAVAILABLE` (we could not look — fail-closed
    rule 2, and it is the same answer for both roads because the failure is
    on OUR side of the lookup), and `RESET_ASKED`, which is what a person
    reads whether or not there was anybody to ask about.

    **A refusal from the reset write is swallowed deliberately**, and it is
    the one place in this module that swallows anything. The person was found
    a moment ago; if the write 404s now, the row went away between two calls,
    and telling them so would be the enumeration oracle this whole function
    is shaped around — arriving at the one person it cannot help anyway. The
    log line keeps it.

    The ceremony is not touched. A reset is not a sign-in: nothing is opened,
    so nothing is closed, and a person who asks for a link mid-ceremony still
    has the ceremony they left.
    """
    started = monotonic()
    if throttled(address=address, client_address=client_address):
        log.info("accounts.signin.refused", reason="throttled")
        return SignIn(outcome=SignInOutcome.THROTTLED, step=Step.RESET, reason="throttled")

    # `find_user` raises rather than answering a `Probe` — it is the v1
    # search every `ensure_*` uses — so the outage road is a `try` here and
    # not `_call`. `asserted_person` reads it the same way, for the same
    # reason, a hundred lines up.
    try:
        row = zitadel.find_user(username=address)
    except zitadel.ZitadelError:
        log.info("accounts.signin.unavailable", reason="reset_lookup_failed")
        return _hold(started, _unavailable(Step.RESET, "reset_lookup_failed"))

    user_id = str(row.get("id", "")) if isinstance(row, Mapping) else ""
    if user_id:
        asked = _call(lambda: zitadel.request_password_reset(user_id=user_id))
        if asked is None or not asked.ok:
            # Swallowed, per the docstring: the answer a person reads may not
            # depend on what the platform said about one particular account.
            log.info(
                "accounts.signin.unavailable",
                reason="reset_not_accepted",
                subject=user_id,
            )
        else:
            log.info("accounts.signin.checked", reason="reset_asked", subject=user_id)
    else:
        log.info("accounts.signin.checked", reason="reset_asked_for_nobody")

    return _hold(started, SignIn(outcome=SignInOutcome.RESET_ASKED, step=Step.RESET))


def _hold(started: float, answer: SignIn) -> SignIn:
    """Leave no earlier than the floor. **The timing half of no-enumeration.**

    A page that answers in 6 ms for an address nobody has and 16 ms for one
    somebody does is an account oracle with a stopwatch in front of it, and
    the per-address throttle does not bound an attacker who tries each
    address once. Both roads therefore leave together.

    Monotonic, for the reason the ceremony's deadline is: a clock adjustment
    mid-request must not turn the floor into a stall or into nothing. And it
    never SHORTENS anything — a road that was already slower than the floor
    is returned as it is, because the floor is a minimum and not a schedule.
    """
    remaining = RESET_FLOOR_SECONDS - (monotonic() - started)
    if remaining > 0:
        sleep(remaining)
    return answer
