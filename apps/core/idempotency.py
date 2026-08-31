"""`Idempotency-Key`: the same write, sent twice, happens once.

A client that times out on a POST does not know whether the write landed. Its
choices are to retry (and maybe charge the card twice) or not to (and maybe
never charge it at all). Neither is acceptable, so the protocol gives it a third
one: send `Idempotency-Key: <opaque>` and the server promises that a repeat of
that request returns the first response rather than doing the work again.

The shape here is the ordinary one, and the parts that matter are the parts that
are easy to leave out:

* **A record is claimed before the view runs**, not after. Two concurrent
  retries would otherwise both find nothing, both run, and both write. The
  second one gets `409 in_progress` and is told to retry.
* **The body is fingerprinted.** Reusing one key for a different request is a
  client bug, and answering it with the *other* request's response would be a
  silent, expensive wrong answer. It is `409 idempotency_key_reuse` instead.
* **A 5xx is not replayed.** A decision the server made below the doors it will
  make again; a 500 is a failure, and caching one would turn a transient fault
  into a permanent answer.
* **A refusal the EDGE made is not replayed either** (ADR core-23). A door
  refusal — a bad credential, an addressing header this caller cannot use, a
  missing CSRF token, a rate limit — is decided in *front* of every service, on
  material the fingerprint does not name, and it ran nothing: the key was never
  spent. Recording one used to poison the key for its whole TTL, so a client
  that fixed its credential and retried got the stale refusal back with
  `Idempotent-Replayed: true` and could never reach its write. The population is
  `core.exceptions.envelope_codes()` — every code registered `boundary="door"`,
  derived and never a hand list. See `_remember`.
* **The scope is the credential and the tenant the door RESOLVED**, hashed
  together — not the key alone, and never the tenant the request *spelled*.
  Keys are chosen by clients and two of them will collide eventually; a
  collision that crossed a tenant boundary would hand one customer another
  customer's response body. See "Whose scope is it" below: the difference
  between the requested tenant and the resolved one was a live defect, and the
  hole it opened did not need a collision at all.

Records expire after 24 hours (`IDEMPOTENCY_TTL_HOURS`). That is a window, not
a guarantee of forever: a client retrying a day later is making a new request by
any reasonable reading.

## Whose scope is it — ADR core-16

`scope_for` used to digest the raw `Authorization` header, the session key and
the **requested** `X-Tenant` string, defaulting to `""` when the header was
absent. The scope was therefore a function of the request's *spelling* rather
than of the tenant the door resolved, and the two come apart the moment a
person belongs to more than one tenant: one credential, `X-Tenant` omitted
both times, a default membership flipped in between — one spelling, two hats,
one scope, and the second call is handed the first hat's response body. That
is not a key collision. It is the ordinary path.

**The rule now: scope on the tenant the door resolved, wherever the door has
resolved it.** `TenantMiddleware` sits one line above this middleware in
`MIDDLEWARE` and has already answered "on whose behalf" for every
session-authenticated request, so `request.tenant` is the honest second half of
the scope and the header is not read at all on that path.

**Where the door has not resolved it yet** — the machine door, where
`ApiTokenAuth` reads a bearer token at *view* time (`apps/accounts/auth.py`),
after this middleware has already had to decide whether to claim or to replay —
the answer comes from a **registered resolver** (see "The seam" below), and it
is scoped exactly as the session path's is, because it is the same answer to
the same question arriving a little later.

**And where nobody can say at all**, the scope carries the tenant the request
*named as a row* — `Tenant` resolved from the slug, never the slug itself — so
that two differently-addressed failures do not share one claim. The stored
`tenant` FK is the belt: `_may_replay` refuses to hand back a record whose
tenant is NULL, and refuses one whose tenant is not the tenant asking.

**What was rejected.** Refusing an absent `X-Tenant` — it makes an optional
header mandatory by accident and breaks the single-tenant client, which is the
common case. Keying on the default membership's slug — still the spelling's
family, and a default flipped between two calls still shares a scope. Moving
idempotency into ninja's auth layer wholesale — the claim has to be written
*before* the view or two concurrent retries both write, which is this module's
first principle.

**The last population, and how it was closed.** A bearer credential that sends
**no** `X-Tenant` at all resolves its tenant from the user's default membership,
inside the view, off rows this app cannot read: `ApiToken` lives in
`apps.accounts`, and `core` may not import it (house rule 7). Part 1 of this
rung left that one path scoped on the credential alone and said so here rather
than hiding it — and a default membership flipped between two calls under one
key was still answered from the first hat.

Part 2 closed it with the seam below: `core` declares
`register_tenant_resolver`, `apps.accounts` registers one from its
`AppConfig.ready()`, and the scope digests what it returns. The call runs
downward, no import runs upward, rule 7 is untouched. **It closed a second
thing on the way**: a request carrying both a session cookie and a bearer token
used to be scoped on the *session's* tenant while `ApiTokenAuth` re-tenanted it
from the token, so the two never agreed and that client got no idempotency at
all — silently. The resolver is asked first now, because the token is what
actually decides such a request (`API_AUTH` tries `ApiTokenAuth` first, and it
is first on purpose — queue V1).

**What it costs, measured rather than asserted.** One extra
`authenticate_token` where an idempotent write carries a bearer token — a single
`SELECT` of the token row, once per request, because `acting_tenant` remembers
its answer and `scope_for` and `_may_replay` share it. A request with no
`Authorization` header pays nothing: the resolver declines on the header alone,
before any query. The `last_used_at` write does **not** double — `touch_token`
already refuses to write twice inside `ACCOUNTS_TOKEN_TOUCH_SECONDS`, so the
second resolution in one request sees the first one's timestamp and returns.
`test_idempotency.py` counts both statements and fails if either moves.

## The two codes, and why they are in the registry

`idempotency_key_reuse` and `in_progress` reach a client in the same
`{detail, code}` envelope every other refusal does, and a client branches on
them the same way — so they are refusals in every sense that matters, and a
refusal this product can make that `manage.py introspect` cannot report is a
published contract nobody declared. Both are registered here, beside the code
that emits them rather than in `core.exceptions` beside a class, because
neither has a class: this middleware sits in *front* of every door and answers
before a service is reached, which is exactly what `boundary="door"` says.

**The set is closed.** `_refusal` takes a registered `Refusal` row from
`EMITTABLE`, never a string, so a third code cannot be typed at a call site —
it has to be registered and listed, which is the one step that keeps
`introspect`'s vocabulary the *whole* vocabulary. The test module
`apps/core/tests/test_refusals.py` reads these call sites back and holds them
to exactly that.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import timedelta
from typing import Any, ClassVar, cast

from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone

from apps.core.exceptions import (
    REFUSAL_CONTENT_TYPE,
    DomainError,
    Refusal,
    Remedy,
    envelope_codes,
    register_refusal,
    wire_refusal,
)
from apps.core.lifecycle import Lifecycle, LifecycleKind
from apps.core.middleware import AUTHORIZATION_HEADER, TENANT_HEADER
from apps.core.models import BaseModel, Tenant

# --- What this middleware may refuse with, declared ---------------------------
#
# `boundary="door"`: both of these are decided at the edge, before any service
# runs, which is the first thing somebody debugging one needs to know.

KEY_REUSE = register_refusal(
    code="idempotency_key_reuse",
    boundary="door",
    remedy=(
        "Replay the original response by sending the identical body under this key. The "
        "fingerprint is over the method, the path and the body, so one changed byte is a "
        "different request; a genuinely different write needs a key of its own, and reusing "
        "this one to mean something else is the client bug this refuses to paper over."
    ),
    fact=(
        "This Idempotency-Key has already been used, for a different request. The "
        "fingerprint covers the method, the path and the body, so one changed byte is a "
        "different request under a key that is already spoken for. Nothing was written."
    ),
    remedies=(
        Remedy("Resend the identical body to replay the first answer", "header:Idempotency-Key"),
        Remedy("Give a genuinely different write a key of its own", "header:Idempotency-Key"),
    ),
    # 409, and declared here rather than appended to a table under `config/`
    # (ADR core-23). Both of these are conflicts and they answer the number
    # `Conflict` carries, which is now a fact this declaration states instead of
    # one `config/api.py` restated on their behalf.
    status=409,
)

IN_PROGRESS = register_refusal(
    code="in_progress",
    boundary="door",
    remedy=(
        "Wait and retry: the first request with this key is still executing. The claim is "
        "written before the view runs, which is what stops two concurrent retries from both "
        "writing; it turns into a replayable response when that first request finishes, and "
        "into nothing when the record expires (IDEMPOTENCY_TTL_HOURS)."
    ),
    fact=(
        "The first request under this Idempotency-Key is still running, so its answer "
        "does not exist yet. Yours was not run — which is the point: two concurrent "
        "retries of one write must not both write."
    ),
    remedies=(Remedy("Wait, then retry the identical request", "header:Idempotency-Key"),),
    status=409,
)


class IdempotencyKeyReuse(DomainError):
    """The key is spoken for, by a different request.

    A class, and not merely the registry row above, because `wire_refusal` — the
    ONE composer of a refusal body — takes a `DomainError`. Until this existed
    the middleware built `{detail, code}` by hand, which is why these two 409s
    were the only refusals on eight shipping routes that reached a client with
    NO `remedies`: the registry had two good ones written for this code all
    along and nothing carried them to the wire.
    """

    code = "idempotency_key_reuse"
    default_detail = "That Idempotency-Key was used for a different request."


class IdempotencyInProgress(DomainError):
    """The first request under this key has not finished. See above."""

    code = "in_progress"
    default_detail = "An identical request is still in flight. Retry shortly."


#: Everything this middleware can refuse with, and the whole of it. `_refusal`
#: takes a row from here rather than a string, so the set of codes that can
#: reach a client from in front of the doors is closed against the registry
#: instead of being whatever somebody last typed.
EMITTABLE: tuple[Refusal, ...] = (KEY_REUSE, IN_PROGRESS)

#: The class that carries each emittable code to `wire_refusal`. Keyed on the
#: code rather than the `Refusal` row so the two halves cannot drift silently:
#: `_refusal`'s guard already closed the set against the registry, and this
#: closes it against the classes.
EXCEPTION_FOR: dict[str, type[DomainError]] = {
    IdempotencyKeyReuse.code: IdempotencyKeyReuse,
    IdempotencyInProgress.code: IdempotencyInProgress,
}

HEADER = "Idempotency-Key"
REPLAYED_HEADER = "Idempotent-Replayed"
METHODS = frozenset({"POST", "PUT", "PATCH"})

# Everything below 500 is a decision the server made and will make again, so it
# is replayed: a client that retries a 400 gets the same 400 rather than a
# second attempt at the same rejected write. A 5xx is not a decision — it is a
# failure — so the claim is dropped and a retry genuinely retries.
#
# **This line is right about everything a SERVICE decided and was wrong about
# everything decided in front of one** (ADR core-23). The second arm is
# `envelope_codes()` below; what survives here, deliberately, is the residual
# stated so nobody has to rediscover it: a domain `403 forbidden` for an actor
# who was PROMOTED between the two calls still replays. That is not an oversight
# — a policy decision is a decision about this fingerprinted request, made below
# the doors, by the layer whose answers this cache exists to hold. A client that
# wants the new answer is making a new request and says so with a new key.
REPLAYABLE_BELOW = 500


class IdempotencyRecord(BaseModel):
    """One `Idempotency-Key`, its request, and the response it produced."""

    #: ADR core-13, and **the worked example of the grammar**: this is the one
    #: table in the tree that already had the whole shape a `purged`
    #: declaration describes — a TTL column (`expires_at`), a callable that
    #: sweeps by it (`purge_expired`, below), an activity that calls the
    #: callable (`apps.events.activities.purge_expired_records`) and a
    #: discovered schedule that runs the activity's workflow
    #: (`apps.events.activities.PURGE`). Declaring it proves the vocabulary
    #: fits something real rather than something invented for the vocabulary.
    #:
    #: `purged_by` names the CALLABLE and not the schedule on purpose: rule 31
    #: walks outwards from here — callable, to the activity that references it,
    #: to the `ScheduleDeclaration` whose workflow reaches that activity — and
    #: a declaration that named the schedule directly would assert the end of
    #: that chain instead of letting the check prove it. This closes for good a
    #: real gap: `purge_expired` once existed with nothing calling it.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.PURGED,
        purged_by="apps.core.idempotency.purge_expired",
        reason=(
            "a replay cache with a TTL: a record past `expires_at` can no longer "
            "answer a replay, so keeping it buys nothing and costs a growing table "
            "on the hottest write path in the API."
        ),
    )

    # A hash of the credential + the tenant the door RESOLVED, where it has
    # resolved one by the time this middleware runs. Not the tenant FK alone:
    # the FK cannot be looked up before the row exists, and for a bearer-token
    # request the tenant is not resolved until the view runs — so the scope
    # carries the *requested* tenant row on that path and `_may_replay` reads
    # the FK below as the second half of the answer.
    scope = models.CharField(max_length=64)
    key = models.CharField(max_length=255)
    fingerprint = models.CharField(max_length=64)

    # The tenant the request that wrote this record actually acted in, filled in
    # by `_remember` once the view has run. Load-bearing rather than
    # decorative: `_may_replay` refuses a record whose tenant is NULL and
    # refuses one whose tenant disagrees with the tenant asking for the replay.
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="idempotency_records",
        null=True,
        blank=True,
    )
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=500)

    # Null until the first request finishes. A second request that finds null
    # is a concurrent retry, and is told so rather than allowed to double-write.
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    body = models.TextField(blank=True)
    content_type = models.CharField(max_length=100, blank=True)

    expires_at = models.DateTimeField(db_index=True)

    # NO RECENCY INDEX (ADR core-11). Every read rides the `(scope, key)`
    # unique constraint, and `purge_expired` filters `expires_at` — which
    # carries its own index right above — never `created_at`. Dropping the
    # inherited bare index is pure write-cost saving on a table written once
    # per mutating request.
    class Meta(BaseModel.Meta):
        verbose_name = "idempotency record"
        verbose_name_plural = "idempotency records"
        constraints = [
            models.UniqueConstraint(
                fields=["scope", "key"],
                name="idempotencyrecord_unique_key_per_scope",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.method} {self.path} [{self.key}]"

    @property
    def is_complete(self) -> bool:
        return self.status_code is not None


def _digest(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


# Domain separators for the two halves of a scope. A scope built from a
# RESOLVED tenant and a scope built from a REQUESTED one must never collide,
# because they are answers to different questions and only the first is
# authorized: without these, one credential's resolved-A scope and its
# requested-A scope would hash to the same 64 characters.
RESOLVED = "resolved"
REQUESTED = "requested"
#: What stands in the scope for "this request named no tenant at all".
UNNAMED = "-"


def credential_for(request: HttpRequest) -> str:
    """The caller, as a hash — never stored in the clear, only this digest.

    A session and a bearer token for the same person are different credentials,
    which is right: they are different clients with different retry behaviour.
    """
    authorization = request.headers.get(AUTHORIZATION_HEADER, "")
    session_key = getattr(getattr(request, "session", None), "session_key", "") or ""
    return _digest(authorization, session_key)


def requested_tenant(request: HttpRequest) -> Tenant | None:
    """The tenant the request *named*, as a row — nobody's authorization implied.

    Deliberately a row and not the string: `X-Tenant: Alpha` and
    `X-Tenant: alpha` are one tenant, and a scope that told them apart would
    turn a legitimate retry into a second write. Reading nothing back is the
    answer for an absent header and for a slug no tenant has.

    The header was spelled here as a literal on purpose, as the population rule
    40 was born to fire on. That rule now exists, its canary is a PLANT rather
    than this live site (`quality/canary/40/header_literal_at_a_value_default.py`
    is this exact shape, injected through the real scope at self-test time), and
    the second spelling is gone: the name is `core.middleware.TENANT_HEADER`,
    the one the HTTP door resolves by. The value default stays — `.get(name, "")`
    is fine once the NAME cannot drift, and it is the drift that fails open.
    """
    slug = request.headers.get(TENANT_HEADER, "").strip().lower()
    if not slug:
        return None
    return Tenant.objects.filter(slug=slug).first()


# --- The seam: how this middleware learns a tenant it may not resolve itself --
#
# A credential this middleware cannot read is a scope it cannot build. The one
# population is the bearer token: it lands in the tenant its pin names, or in
# its user's **default membership**, and either way that is decided inside the
# view by `authenticate_token` off an `ApiToken` row living in `apps.accounts` —
# an app `core` may not import (house rule 7, the fixed layer direction). Left
# unresolved, such a credential was scoped on itself alone, and a default
# membership flipped between two calls under one key was answered from the first
# hat. That was the last opening of the hole ADR core-16 closes.
#
# So the call inverts, exactly as `core.bridge` inverts every other one: the
# higher app registers a callable from its `AppConfig.ready()` and this module
# looks it up at call time. No import runs upward, no cycle, and the dependency
# stays declared on the app rather than smuggled into a function body.
#
# A registry of its own rather than a `bridge` name, because the shape differs:
# `bridge` names take one registrant each and raise in production when nobody
# registered. This is a *list* asked in turn, and an empty list is not a fault —
# a template with no machine door has nothing to resolve, and the scope simply
# falls through to what the request named. Same "a product without this app
# still runs" promise, said for a registry whose emptiness is ordinary.

#: What a resolver is handed and what it must answer: the request, and the
#: tenant that request will act in — or `None`, meaning "not mine to answer".
#: `Tenant` is typed loosely for the reason `bridge`'s protocols type their
#: foreign classes as `Any`: the registrant lives in an app this one cannot
#: name. It is a real `Tenant` row; only the annotation is modest.
TenantResolver = Callable[[HttpRequest], Any]

_tenant_resolvers: list[TenantResolver] = []

#: Where a resolver's answer is cached for the life of one request. Set even
#: when the answer is `None`, so a credential nobody can resolve is asked about
#: once rather than once per call site — `scope_for` and `_may_replay` both want
#: it, and the resolver behind it costs a query.
RESOLVED_TENANT_ATTR = "_idempotency_acting_tenant"


def register_tenant_resolver(resolver: TenantResolver) -> None:
    """Declare that this app can say which tenant a credential lands in.

    Called from an `AppConfig.ready()`, which runs once per process and in every
    process — `manage.py`, the ASGI server, the Temporal worker and pytest all
    reach it. Registering the same callable twice is a no-op rather than a
    second entry: `ready()` is idempotent in intent, and a duplicated resolver
    would spend a second query to reach the same answer.
    """
    if resolver not in _tenant_resolvers:
        _tenant_resolvers.append(resolver)


def acting_tenant(request: HttpRequest) -> Tenant | None:
    """The tenant this request will act in, as far as anyone can say right now.

    A **registered resolver is asked first**, and that ordering is the whole of
    the cookie-plus-token case. `TenantMiddleware` resolves the session's tenant
    before this middleware runs, but `API_AUTH` tries `ApiTokenAuth` *first* and
    it re-tenants the request from the token — so when a request carries both,
    the token is what decides it, and a scope built on the session's tenant
    would never match the record the request went on to write. That client used
    to get no idempotency at all, silently. Asking the resolver first is what
    makes the scope agree with the request.

    A resolver declines by answering `None`, which is the ordinary case: a
    request with no `Authorization` header at all costs nothing here, because
    the resolver refuses on the header before it reaches a query. Then the
    answer is what the door resolved — the session path, unchanged, and the
    reason part 1's red stays closed.

    `None` from everybody means nobody can say, and `scope_for` falls back to
    what the request *named*. Such a request resolves no tenant in the view
    either, so it writes nothing worth replaying.

    **A resolver is not authorization and never becomes any.** It answers the
    same question `TenantMiddleware` answers, for a credential that arrives
    later; the route still authenticates. A resolver that answered wrongly would
    move a request into a scope of its own — never into somebody else's.
    """
    if hasattr(request, RESOLVED_TENANT_ATTR):
        return cast("Tenant | None", getattr(request, RESOLVED_TENANT_ATTR))
    answer: Tenant | None = None
    for resolver in _tenant_resolvers:
        answer = resolver(request)
        if answer is not None:
            break
    if answer is None:
        answer = getattr(request, "tenant", None)
    setattr(request, RESOLVED_TENANT_ATTR, answer)
    return answer


def scope_for(request: HttpRequest) -> str:
    """Who and where this request is — the credential, and the tenant it acts in.

    The scope follows the **hat, not the spelling**. For a session-authenticated
    request `TenantMiddleware` has already resolved it from `Membership` rows;
    for a bearer credential the seam above answers; either way the header is not
    what the digest is built from, so a default membership flipped between two
    calls moves the second into a scope of its own rather than into the first
    call's cached answer.

    Only when nobody can resolve anything does the scope carry the tenant the
    request *named*, as a row — which keeps two differently-addressed failures
    from sharing one claim — or, if it named nothing either, the credential
    alone. Both of those describe a request that will resolve no tenant in the
    view and therefore write nothing.
    """
    credential = credential_for(request)
    tenant = acting_tenant(request)
    if tenant is not None:
        return _digest(credential, RESOLVED, str(tenant.pk))
    requested = requested_tenant(request)
    if requested is not None:
        return _digest(credential, REQUESTED, str(requested.pk))
    return _digest(credential, REQUESTED, UNNAMED)


def fingerprint_for(request: HttpRequest) -> str:
    """What makes two requests "the same request" for replay purposes.

    **BYTE-identical, and the docs say so.** The digest is over the
    method, the path and the RAW BODY — not a parsed structure — so the same
    JSON re-serialised with different whitespace or a different key order is a
    different request. That is a real edge for a real client: a pretty-printing
    library, a generated SDK or a re-serialising proxy that rebuilds the body on
    retry is refused on exactly the retry this header exists to make safe.

    **Body fingerprinting is deliberately NOT built.** Parsing the body to
    compare it semantically means picking a canonical JSON form — key order,
    number formatting, unicode normalisation, whether `1` and `1.0` are one
    value — and every one of those is a decision that has to be right forever
    for a client nobody has met yet. The cheap true fix is to say what the rule
    IS, in both places a client can read it.

    **The dated trigger, so this is a deferral and not a silence:** the first
    time a real client's LEGITIMATE retry is refused here — same operation, same
    intent, body rebuilt by its own stack — that is the evidence that the
    canonicalisation is worth its cost, and it comes with the client's actual
    serialiser to design against instead of a guess.
    """
    body = request.body if request.method in METHODS else b""
    return _digest(str(request.method), request.path, body.decode("utf-8", "replace"))


def _refusal(detail: str, refusal: Refusal, status: int) -> JsonResponse:
    """The edge's refusal body: `{detail, code}`, and the code is a declared one.

    The guard is not defensive programming — it is the closure. A `Refusal` can
    be built by hand (it is an ordinary frozen dataclass), so "the argument is
    typed" is not the same promise as "the code is registered and listed"; this
    is the second one, at the moment of emission.
    """
    if refusal not in EMITTABLE:
        raise ValueError(
            f"The idempotency middleware refuses with "
            f"{', '.join(row.code for row in EMITTABLE)}, and nothing else; "
            f"{refusal.code!r} is not one of them. Declare it with register_refusal "
            f"and add it to EMITTABLE, or use one of the codes that is already there — "
            f"a code the registry has not got is a contract nothing can report."
        )
    return JsonResponse(
        wire_refusal(EXCEPTION_FOR[refusal.code](detail)),
        status=status,
        content_type=REFUSAL_CONTENT_TYPE,
    )


def _may_replay(record: IdempotencyRecord, request: HttpRequest) -> bool:
    """Is this completed record *this* caller's answer, and not another hat's?

    The scope has already said the credential matches. This is the second
    question, and it is asked of the stored row rather than of the request's
    headers, because the headers are what got this wrong in the first place.

    Two refusals, both fail-closed:

    * **A record with no tenant is never replayed.** It was written by a request
      that resolved nothing — an unauthenticated caller, a token pinned to one
      tenant while the header named another (`authenticate_token`'s refusal), a
      session with no membership. Every one of those wrote nothing, so there is
      no work to spare a retry, and handing that body to a request that *did*
      resolve a tenant is the shape rule 8 exists to refuse.
    * **A record whose tenant is not this request's tenant is never replayed.**
      Belt to the scope's braces. `acting_tenant` is the same answer `scope_for`
      built the scope from — asked once and remembered — so the two halves
      cannot drift apart between the lookup and the decision.
    * **A record with a tenant is never replayed to a request that has none.**
      The scopes already separate them, so this is unreachable rather than
      load-bearing; it is written as a refusal anyway, because "unreachable"
      is a claim about today's `scope_for` and this is a claim about what may
      be handed to a caller.

    The caller that gets `False` is not refused — it is simply not answered from
    the cache: it runs as the fresh request it is.
    """
    if record.tenant_id is None:
        return False
    tenant = acting_tenant(request)
    if tenant is None:
        return False
    return bool(record.tenant_id == tenant.pk)


def _refusal_code(response: HttpResponse) -> str | None:
    """The `code` in a refusal envelope, when the answer is one of ours.

    **Read off the wire rather than off an exception**, because by the time this
    middleware sees the answer the exception is long gone: it sits in front of
    every door, and what comes back up the stack is an `HttpResponse` that ninja,
    `handler500`, or a Django middleware below this one already composed. The
    envelope is `wire_refusal`'s and `REFUSAL_CONTENT_TYPE` is what it is served
    as, so `code` is exactly where it always is.

    **Narrow on purpose, and every `None` is the old behaviour.** A streaming
    response (whose `.content` would raise), a body that is not JSON, a JSON body
    that is not an object, an object with no `code` — none of those is a refusal
    this middleware can classify, and it stores them exactly as it did before.
    Guessing at an unreadable body would be this layer inventing a refusal
    nobody made.
    """
    if getattr(response, "streaming", False):
        return None
    if not response.headers.get("Content-Type", "").startswith("application/json"):
        return None
    try:
        body = json.loads((getattr(response, "content", b"") or b"").decode("utf-8", "replace"))
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    code = body.get("code")
    return code if isinstance(code, str) else None


def _replay(record: IdempotencyRecord) -> HttpResponse:
    response = HttpResponse(
        record.body,
        status=record.status_code,
        content_type=record.content_type or "application/json",
    )
    response[REPLAYED_HEADER] = "true"
    return response


class IdempotencyMiddleware:
    """Honours `Idempotency-Key` on writes under `/api/`.

    Outside `/api/` it does nothing: the admin and the allauth flows are
    browser-driven and post forms, and a form post is not the retry problem this
    solves.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        key = request.headers.get(HEADER, "").strip()
        if not key or request.method not in METHODS or not request.path.startswith("/api/"):
            return self.get_response(request)

        scope = scope_for(request)
        fingerprint = fingerprint_for(request)
        now = timezone.now()
        ttl = timedelta(hours=int(getattr(settings, "IDEMPOTENCY_TTL_HOURS", 24)))

        try:
            # `on_commit`-free and in its own transaction: the claim has to be
            # visible to a concurrent retry immediately, whatever the request's
            # own transaction does afterwards.
            with transaction.atomic():
                record = IdempotencyRecord.objects.create(
                    scope=scope,
                    key=key,
                    fingerprint=fingerprint,
                    method=str(request.method),
                    path=request.path[:500],
                    expires_at=now + ttl,
                )
            claimed = True
        except IntegrityError:
            claimed = False
            existing = IdempotencyRecord.objects.filter(scope=scope, key=key).first()
            if existing is None:  # pragma: no cover - lost a race with the purge
                return self.get_response(request)
            record = existing

        if not claimed:
            if record.expires_at <= now:
                record.delete()
                return self.__call__(request)
            if record.fingerprint != fingerprint:
                return _refusal(
                    "That Idempotency-Key was used for a different request.",
                    KEY_REUSE,
                    409,
                )
            if not record.is_complete:
                return _refusal(
                    "An identical request is still in flight. Retry shortly.",
                    IN_PROGRESS,
                    409,
                )
            if not _may_replay(record, request):
                # Somebody else's answer, or nobody's. Not a refusal — this
                # request is simply run as the fresh request it is, and the
                # record it could not have is left exactly as it was.
                return self.get_response(request)
            return _replay(record)

        response = self.get_response(request)
        self._remember(record, request, response)
        return response

    def _remember(
        self, record: IdempotencyRecord, request: HttpRequest, response: HttpResponse
    ) -> None:
        """Store a replayable response, or drop the claim so a retry may proceed.

        **Two arms drop the claim, and they drop it the same way** — the record
        is deleted, so the retry is the fresh request it always was rather than
        one that is told anything about the first.

        1. **A 5xx is not a decision, it is a failure** (`REPLAYABLE_BELOW`).
           Caching one turns a transient fault into a permanent answer.
        2. **A refusal the EDGE made was never this key's answer** (ADR core-23).
           `envelope_codes()` is every code registered `boundary="door"`, which
           is this product's own word for *the edge refused before a service was
           reached*: no route ran, nothing was read, nothing was written, and the
           claim was never spent. Replaying one is how a client that fixes its
           credential and retries — the exact retry `Idempotency-Key` exists to
           make safe — gets the stale refusal back with `Idempotent-Replayed:
           true` and finds its write unreachable for the record's whole TTL.

        The material says the same thing from the other side: the fingerprint is
        `method + path + raw body`, and a credential, an addressing header, a
        CSRF token, the rate-limit counters and the query string all sit outside
        it. A refusal decided on any of those is a refusal about something the
        key never named.

        **Derived, never a hand list.** The set is open — a product registers its
        own door refusals — and a list here would go stale the first time one
        landed, silently, which is the shape of the defect rather than a fix for
        it.
        """
        if response.status_code >= REPLAYABLE_BELOW:
            IdempotencyRecord.objects.filter(pk=record.pk).delete()
            return
        refused_with = _refusal_code(response)
        if refused_with is not None and refused_with in envelope_codes():
            IdempotencyRecord.objects.filter(pk=record.pk).delete()
            return
        content = getattr(response, "content", b"") or b""
        IdempotencyRecord.objects.filter(pk=record.pk).update(
            status_code=response.status_code,
            body=content.decode("utf-8", "replace"),
            content_type=response.headers.get("Content-Type", "application/json"),
            tenant=getattr(request, "tenant", None),
            updated_at=timezone.now(),
        )


def purge_expired(*, now: Any = None) -> int:
    """Drop records past their TTL. Returns how many went."""
    deleted, _ = IdempotencyRecord.objects.filter(expires_at__lte=now or timezone.now()).delete()
    return int(deleted)
