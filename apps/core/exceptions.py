"""What a service raises when it refuses — and the registry of every refusal.

House rule 14: **a service says what happened; only the door says what status
code that is.** `HttpError`, `Http404` and the number `404` never appear in a
`services.py` or a `selectors.py`, because the same service is called by REST,
by an MCP tool, by a socket consumer and by a Temporal activity — three of
which have no status codes at all. A service that raised `HttpError` would be a
service that only one door could call.

So the vocabulary is here, it is small, and it is about the domain:

* `NotFound` — the row is not there, or not the caller's to see.
* `Conflict` — it would collide with something that already exists.
* `Forbidden` — the caller may not.
* `Invalid` — the input does not hold, field by field.
* `RateLimited` — too much, too fast.

Every one carries a stable `code` a client can branch on, which the message
never is: prose gets rewritten, `"not_found"` does not.

The single mapper from these to HTTP lives in `config/api.py`. Nothing in
`apps/` knows a status code.

## The registry, and why a code is not a free string

A `code` is the half of a refusal that a client branches on and that an audit
row is queried by, which makes it a **published contract** — and until this
registry existed, it was a string somebody typed. Two subclasses could share
`"conflict"` and mean different things; a product could invent
`"insufficientfunds"` in one place and `"insufficient_funds"` in another; and
nothing anywhere could answer "what can this product refuse?" without grepping.

So every code is declared once, with two things the code alone cannot say:

* **`boundary`** — *which layer decided*. `selector` (the read found nothing a
  scoped query would return), `service` (the write does not hold), `policy`
  (`authz` said no), `door` (the edge refused before a service was reached).
  It is the first question anyone debugging a refusal asks, and the answer used
  to live only in the reader's head.
* **`remedy`** — what the *developer* reading it should do. Written for whoever
  is holding the refusal — an agent, a developer, an integrator — and
  deliberately **never sent to a client**, because it names `policies.py` and
  `X-Tenant` and the middleware, and internal prose on the wire is prose
  somebody starts parsing.
* **`fact`** — what is *true*, said to whoever is being refused. `not_found`'s
  fact is that not-there and not-yours are one answer on purpose; a code with
  no fact can only ever say "no".
* **`remedies`** — what they can *do* about it, as `Remedy(label, destination)`
  rather than a sentence, composed once here so a screen and an assistant
  render the same offer. These reach the wire (ADR core-5); `remedy` does not.

All four are required. `register_refusal` refuses a declaration missing the
fact, or carrying a remedy that is a string rather than a `Remedy`, **at import
time** — the same tier an unregistered code is refused at, because a grammar
whose parts are optional parameters is a grammar half the product will skip.

And a fifth, which is genuinely optional and says so:

* **`status`** — *what number the HTTP door answers this code with* (ADR
  core-23). Declared beside the code rather than appended to a table under
  `config/`, because a template whose first law is "registration is by
  discovery, never by editing `config/`" had exactly one exception left, and it
  cost a `config/api.py` edit per refusal code in every product rung that
  declared one. `CODE_STATUSES` below is that derivation, and `config/api.py`
  publishes it as `CODE_STATUS` — the module that *speaks* the number is still
  the door's, which is what house rule 14 asks; what moved is who *knows* it.

  **The absence is a declaration too.** A code with no status is a code the HTTP
  door has no number for, and there are two real populations: a refusal only the
  MACHINE door can make (`invalid_arguments`, `apps/core/mcp.py` — the MCP door
  has no status codes at all, a tool answers one line of text), and house rule
  47's own canary, which is registered, refusable and *deliberately* unpublished
  so that the rule's drop path stays reachable. Forcing a number on every code
  would cure the disease that instrument carries, and a canary that cannot fire
  is exit 2. So `status` is optional, its absence means "no number here", and
  rule 47's question moves from "is there a `CODE_STATUS` line" to "is there a
  `status=` at the declaring site" — one line, in the app that owns the refusal,
  and no edit under `config/` at all.

**One composer, both doors.** `wire_refusal(exc)` builds the body —
`{detail, code, errors?, remedies?}` — and `config/api.py` sends it as JSON
while `core.mcp.tool_call` renders it through `refusal_message`. Neither door
composes anything of its own, which is what stops the screen and the assistant
from saying two different things about one refusal.

`register_refusal` is the only writer. `REFUSALS` is a read-only view of the
registry, so "the only writer" is a property of the module rather than a
convention — and `manage.py introspect` reports the whole thing, which is how
an agent reads the product's refusal vocabulary instead of guessing at it.

**`DomainError.__init_subclass__` refuses an unregistered code at import time**,
which is the same moment `@service` and the app registry make their own
decisions: a refusal that only fails when it is first raised fails in
production, on the unhappy path, months later. Declaring the code is one line
next to the class, and the class cannot be defined without it.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import OperationalError as DjangoOperationalError

from apps.core.log import get_logger

log = get_logger(__name__)

# Where a validation message lands when it belongs to the object rather than to
# one of its fields — Django's own key, kept so a client sees one shape.
NON_FIELD_KEY = "__all__"


# --- The refusal registry ----------------------------------------------------

#: Which layer decided. Not decoration: it is what tells somebody reading a
#: refusal where to go and look, and the four are the four places a request can
#: be turned away in this template.
Boundary = Literal["selector", "service", "policy", "door"]

BOUNDARIES: tuple[Boundary, ...] = ("selector", "service", "policy", "door")

# A code is a machine token that outlives every message beside it, so it is
# held to a shape: lower snake case, which is what every existing one is and
# what a client can switch on without normalising.
CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

#: The range a refusal's declared status may sit in. 4xx and 5xx and nothing
#: else: a refusal that answered 2xx or 3xx would be a success or a redirect
#: wearing a refusal's clothes, and the one thing every reader of this table
#: assumes is that the number means "no".
REFUSAL_STATUS_RANGE = range(400, 600)

#: The four keys every refusal body may carry and no refusal may redefine —
#: `wire_refusal`'s own grammar. A refusal's `wire_extra` sits BESIDE them.
WIRE_COMMON_KEYS = frozenset({"detail", "code", "errors", "remedies"})


@dataclass(frozen=True, slots=True)
class Remedy:
    """One thing the caller can *do* about a refusal, as a label and a place.

    `label` is what a screen puts on a button and an assistant says out loud.
    `destination` is **opaque here and stays opaque here** (ADR core-5): this
    template has no navigation manifest to validate it against, so it is a
    string the product gives meaning to — a route name, a header, a settings
    page — and the first product that grows a manifest grows the rule that
    checks its remedies name real destinations. The template's own destinations
    are `<kind>:<name>` tokens (`header:X-Org`, `docs:openapi`,
    `introspect:refusals`, `self:membership`, `field:errors`,
    `route:token-mint`), which say where to look without promising a URL a
    product may not have.

    `route:` names an OPERATION by its `url_name` — the handle the ninja
    registry already keys on, which is why it promises no URL: a renderer that
    knows the mount reverses it, and one that does not can still print the name.
    It is the sixth kind: the scoped-token refusal
    wanted to point a caller at the operation that mints a wider token and had
    to settle for `docs:openapi` — "go and read the whole document" where "call
    this" was the answer. Existing `docs:openapi` remedies that really mean one
    operation may migrate to it; none is rewritten here, because a refusal's
    destination belongs to whoever owns that refusal.

    Frozen and structured rather than a sentence, because the whole reason
    remedies exist beside `remedy` is that a *composed* remedy can be rendered
    by a screen and by an assistant identically. A string cannot be.
    """

    label: str
    destination: str


def fill_noun(remedies: Sequence[Remedy], noun: str | None) -> tuple[Remedy, ...]:
    """`remedies` with every destination's `<noun>` slot filled; unfilled when `noun` is None."""
    if noun is None:
        return tuple(remedies)
    return tuple(
        Remedy(r.label, r.destination.replace(NOUN_SLOT, noun)) if NOUN_SLOT in r.destination else r
        for r in remedies
    )


@dataclass(frozen=True, slots=True)
class Refusal:
    """One registered refusal code, and the four things the code cannot say.

    Frozen because it is a published contract: a registry somebody could edit
    in place would be a contract that changes without a diff.

    The three-move shape, and none of the three is optional (ADR core-5):

    * **`fact`** — what is *true*, said to whoever is being refused. It is the
      half `remedy` was never allowed to be, because `remedy` is internal:
      "never say not-there when the truth is not-yours" is a fact, and until
      this field existed there was nowhere honest to put it.
    * **`remedies`** — what they can *do*, composed once here rather than
      three times at three doors. This is the field that reaches the wire.
    * **`remedy`** — what the *developer* holding the refusal should do. Still
      internal, still never sent: it names `policies.py` and `X-Tenant` and
      the middleware, and prose on the wire is prose somebody starts parsing.
    """

    code: str
    boundary: Boundary
    remedy: str
    fact: str
    remedies: tuple[Remedy, ...]
    #: What the HTTP door answers this code with, or `None` for a code that
    #: door has no number for — see the module docstring's fifth part. `None` is
    #: a declaration and not an omission: `invalid_arguments` is a machine-door
    #: refusal and the machine door has no statuses at all.
    status: int | None = None


_registry: dict[str, Refusal] = {}

#: Every registered refusal, read-only. `register_refusal` is the only writer,
#: and a `MappingProxyType` is what makes that a fact rather than a comment.
REFUSALS: Mapping[str, Refusal] = MappingProxyType(_registry)


class _CodeStatuses(Mapping[str, int]):
    """Every code that declared a number, and the number — read LIVE (ADR core-23).

    A view rather than a snapshot, for the reason `REFUSALS` is one: a dict built
    at some module's import is a dict whose contents depend on which module got
    imported first, and this one is read by three callers at three different
    moments — `config/api.py` while it writes the OpenAPI document, `config/mcp.py`
    inside a request, and `quality/refusal_probe.py` from outside the process
    that built the mount. A late registration used to be handled by somebody
    remembering to add a line; now it is handled by there being no line.
    """

    def __getitem__(self, code: str) -> int:
        refusal = _registry.get(code)
        if refusal is None or refusal.status is None:
            raise KeyError(code)
        return refusal.status

    def __iter__(self) -> Iterator[str]:
        return iter([code for code, row in _registry.items() if row.status is not None])

    def __len__(self) -> int:
        return sum(1 for row in _registry.values() if row.status is not None)

    def __repr__(self) -> str:
        return f"CODE_STATUSES({dict(self)!r})"


#: The code→status derivation ADR core-23 replaced the hand-appended table with.
#: `config/api.py` re-exports it as `CODE_STATUS`, which is the name the document
#: derivation, the machine door and the gate's refusal probe all read.
CODE_STATUSES: Mapping[str, int] = _CodeStatuses()


def envelope_codes() -> frozenset[str]:
    """Every code the EDGE decided — the refusals a claim was never spent on.

    **The replay boundary (ADR core-23), derived and never a hand list.** The
    idempotency middleware fingerprints `method + path + raw body`; a credential,
    an addressing header, a CSRF token, the rate-limit counters and the query
    string are all outside that. `boundary="door"` is this registry's own word
    for *the edge refused before a service was reached* — so nothing ran, nothing
    was written, and the key was never spent. Replaying such a refusal answers a
    question the retry did not ask again, and that is how a fixed credential
    finds its write permanently unreachable under the key it retried with.

    A hand list was rejected: the set is open, and a code registered
    `boundary="door"` next month has to join by being registered and by nothing
    else. `apps/core/idempotency.py` is the one caller; the argument in full is
    in its `_remember`.
    """
    return frozenset(code for code, row in _registry.items() if row.boundary == "door")


def as_remedies(remedies: Sequence[Remedy] | None, *, where: str) -> tuple[Remedy, ...]:
    """Structured remedies, or a `ValueError` naming what arrived instead.

    The one gate every remedy passes, whether it was declared in the registry
    or handed to a raise site. A list of sentences is the shape this refuses:
    it is what a composed remedy degrades into the moment nobody is checking,
    and a sentence cannot be rendered as a button.
    """
    if remedies is None:
        return ()
    if isinstance(remedies, (str, bytes, Remedy)):
        raise ValueError(
            f"{where}: remedies is a sequence of Remedy(label=…, destination=…), not "
            f"{type(remedies).__name__}. One remedy is still `(Remedy(...),)` — the "
            "plural is the contract, because a screen and an assistant both render a "
            "list."
        )
    out: list[Remedy] = []
    for entry in remedies:
        if not isinstance(entry, Remedy):
            raise ValueError(
                f"{where}: {entry!r} is not a Remedy. A remedy is a label and a "
                "destination, composed once here so every door renders the same one; "
                "a bare string is advice nobody can act on twice the same way."
            )
        if not entry.label.strip() or not entry.destination.strip():
            raise ValueError(
                f"{where}: a Remedy needs both a label and a destination; got {entry!r}."
            )
        out.append(entry)
    return tuple(out)


#: The slot a registered remedy's destination leaves for the refused row's
#: kind: `route:<noun>-archive`. The registry holds ONE remedy per code; the wire
#: fills the slot from the raise site's `noun` (`remedies_for_noun`) and the API
#: document from the operation's own kind (`apps.core.api.docs.refusal_response`),
#: so the published remedy and the sent one are one declaration rendered twice.
NOUN_SLOT = "<noun>"


def register_refusal(
    *,
    code: str,
    boundary: Boundary,
    remedy: str,
    fact: str = "",
    remedies: Sequence[Remedy] | None = None,
    status: int | None = None,
) -> Refusal:
    """Declare a refusal code. **The only writer of the registry.**

    Called at module import, beside the class that raises it — the six below,
    and one line per refusal a product adds. Registering the same code twice
    with the same meaning is a no-op, so a module imported twice is not an
    error; registering it twice with a *different* meaning is refused, because
    two meanings under one code is exactly the ambiguity the registry removes.

    **All four arguments are required in practice** and the two newest have
    defaults only so that omitting them is a `ValueError` at import — the same
    tier every other malformed declaration is refused at — rather than a
    `TypeError` from the interpreter. Optional parameters are how a grammar
    becomes a suggestion: a `fact` nobody wrote is a code that can only ever
    say "no", and a `remedies` nobody wrote is a dead end with a status code.

    **`status` is the fifth part, and it is the one that really is optional**
    (ADR core-23). Give it and the code is published: `CODE_STATUSES` carries it,
    `config/api.py` answers with it, and the operation's `x-refusal-codes` names
    it — with no edit under `config/` anywhere. Leave it out and the code has no
    number at the HTTP door, which is the honest answer for a machine-door-only
    refusal and the state house rule 47's canary depends on. What is checked here
    is only that a number, when given, is a refusal's number: 4xx or 5xx, an
    `int` and not a `bool` (Python's `True` IS an `int`, and `True == 1` would
    key a table on a status of 1).
    """
    if status is not None and (isinstance(status, bool) or not isinstance(status, int)):
        raise ValueError(
            f"A refusal's status is the number the HTTP door answers it with, as an int; "
            f"{code!r} declared {status!r}."
        )
    if status is not None and status not in REFUSAL_STATUS_RANGE:
        raise ValueError(
            f"A refusal's status is a 4xx or a 5xx — every reader of it assumes the "
            f"number means no; {code!r} declared {status!r}. A code the HTTP door has no "
            "number for (a machine-door refusal) declares no status at all rather than a "
            "number outside the range."
        )
    if not CODE_PATTERN.match(code):
        raise ValueError(
            f"A refusal code is lower snake case and starts with a letter; got {code!r}."
        )
    if boundary not in BOUNDARIES:
        raise ValueError(
            f"A refusal's boundary says which layer decided, and is one of "
            f"{', '.join(BOUNDARIES)}; {code!r} declared {boundary!r}."
        )
    if not remedy.strip():
        raise ValueError(
            f"A refusal needs a remedy — what the person holding it should do next. "
            f"{code!r} declared none."
        )
    if not fact.strip():
        raise ValueError(
            f"A refusal needs a fact — what is TRUE, said to whoever is being refused. "
            f"{code!r} declared none. It is not the remedy said politely: `not_found`'s "
            "fact is that not-there and not-yours are one answer on purpose, and a code "
            "with no fact can only say no."
        )
    declared = as_remedies(remedies, where=f"refusal {code!r}")
    if not declared:
        raise ValueError(
            f"A refusal needs at least one remedy — what the caller can DO about it, "
            f"as Remedy(label=…, destination=…). {code!r} declared none, which is a "
            "dead end with a status code on it."
        )
    refusal = Refusal(
        code=code,
        boundary=boundary,
        remedy=remedy.strip(),
        fact=fact.strip(),
        remedies=declared,
        status=status,
    )
    existing = _registry.get(code)
    if existing is not None:
        if existing != refusal:
            raise ValueError(
                f"The refusal code {code!r} is already registered, with a different "
                f"meaning ({existing.boundary}: {existing.remedy!r}). A code is a "
                f"published contract; give this one its own."
            )
        return existing
    _registry[code] = refusal
    # WHO declared it: the calling module, read once at the one writer. Kept
    # beside the registry rather than on `Refusal`, whose equality is the
    # "same meaning twice is a no-op" test above — the declarer is a fact about
    # the declaration, not about the code's meaning.
    _declared_in[code] = str(sys._getframe(1).f_globals.get("__name__", ""))
    return refusal


#: code -> the module that registered it. See `declared_by`.
_declared_in: dict[str, str] = {}


def declared_by(code: str) -> str:
    """The module that registered `code` (`apps.<app>.<module>`), or `""`.

    What lets a pin tell the TEMPLATE's codes from a PRODUCT's: a typed table
    of the template's codes is a record the template keeps, and a product's
    `register_refusal(code, status=…)` is admitted by its own declaration in
    its own app — a product never edits a table in `core` to publish a code.
    """
    return _declared_in.get(code, "")


def declaring_app(code: str) -> str:
    """The app label that registered `code` (`apps.<label>…` → `<label>`), or `""`."""
    parts = declared_by(code).split(".")
    return parts[1] if len(parts) >= 2 and parts[0] == "apps" else ""


def remedies_for_noun(code: str, noun: str) -> tuple[Remedy, ...]:
    """The registered remedies for `code`, the `<noun>` slot filled with the refused row's kind.

    The one way a raise site that knows its noun says so: the registry holds the
    remedy, this only fills its slot — so the wire cannot send a remedy the API
    document does not publish.
    """
    registered = _registry.get(code)
    return fill_noun(registered.remedies if registered is not None else (), noun)


def refusal_for(code: str) -> Refusal | None:
    """The registered refusal, or `None`. For `introspect`, and for tests."""
    return _registry.get(code)


# --- The vocabulary ----------------------------------------------------------

register_refusal(
    code="error",
    boundary="service",
    remedy=(
        "The base refusal: a service said no for a reason this vocabulary has no word "
        "for yet, and the door has no status code for it either (config/api.py answers "
        "500). Read the service's own log line and audit row, then either raise one of "
        "the five below or give the reason its own registered subclass."
    ),
    fact=(
        "A service refused, for a reason this product has not given a name to yet. "
        "Nothing was written."
    ),
    remedies=(Remedy("See everything this product can refuse with", "introspect:refusals"),),
    # 500, and the only status in this file that is not an answer: a service
    # refused for a reason the vocabulary has no word for, so the door has no
    # number for it either and says so honestly rather than inventing a 4xx.
    status=500,
)


class DomainError(Exception):
    """The base every domain refusal derives from.

    `code` is the machine-readable half and is a class attribute, so a caller
    can branch on `exc.code` without matching on a message somebody will
    reword. `detail` is the human half.

    **The code must be registered before the class body closes** — see
    `__init_subclass__`. A subclass that does not set `code` inherits its
    parent's, which is already registered, so the common "same refusal, better
    name" subclass costs nothing.
    """

    code: str = "error"
    default_detail: str = "The request could not be completed."

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Refuse an unregistered code at import time.

        Import time rather than raise time, deliberately and for the same
        reason `@service` and the app registry decide at import: a refusal that
        is only checked when it is first raised is checked in production, on
        the unhappy path, long after the person who wrote it moved on.
        """
        super().__init_subclass__(**kwargs)
        if cls.code not in _registry:
            raise TypeError(
                f"{cls.__module__}.{cls.__qualname__} refuses with the code "
                f"{cls.code!r}, which is not in the refusal registry, so nothing "
                f"records which layer decides it or what to do about it. Declare it "
                f"beside the class, before it:\n\n"
                f"    from apps.core.exceptions import Remedy, register_refusal\n\n"
                f"    register_refusal(\n"
                f"        code={cls.code!r},\n"
                f"        boundary=...,  # one of: {', '.join(BOUNDARIES)}\n"
                f"        remedy=...,    # the DEVELOPER's next step; never sent to a client\n"
                f"        fact=...,      # what is TRUE, said to whoever is refused\n"
                f"        remedies=(Remedy(label=..., destination=...),),  # what they can DO\n"
                f"        status=...,    # the HTTP door's number; omit ONLY for a "
                f"machine-door code\n"
                f"    )\n"
            )

    def __init__(
        self,
        detail: str | None = None,
        *,
        remedies: Sequence[Remedy] | None = None,
    ) -> None:
        self.detail = detail or self.default_detail
        #: Contextual remedies, when this raise site knows something better than
        #: the registry does ("go to the invoice that already holds this
        #: number"). `None` — the ordinary case — means the registered ones.
        self._remedies: tuple[Remedy, ...] | None = (
            as_remedies(remedies, where=f"{type(self).__name__}(remedies=…)")
            if remedies is not None
            else None
        )
        super().__init__(self.detail)

    @property
    def errors(self) -> dict[str, list[str]]:
        """Field-by-field messages. Empty for everything except `Invalid`."""
        return {}

    @property
    def refusal(self) -> Refusal | None:
        """This refusal's registry entry — its boundary, fact, remedies and remedy.

        Only part of it reaches the wire: `wire_refusal` sends the fact's
        consequences, never the `remedy` prose. This is the whole row, for the
        log, the audit trail and whoever is reading them.
        """
        return _registry.get(self.code)

    @property
    def fact(self) -> str:
        """What is true, from the registry. Empty only for an unregistered code."""
        registered = self.refusal
        return registered.fact if registered is not None else ""

    @property
    def remedies(self) -> tuple[Remedy, ...]:
        """What the caller can do — this raise site's, or the registry's.

        A raise site that passed `remedies=` overrides the default *entirely*
        rather than adding to it: a contextual remedy exists because the generic
        one was not good enough here, and appending would leave the worse
        answer on the screen underneath the better one.
        """
        if self._remedies is not None:
            return self._remedies
        registered = self.refusal
        return registered.remedies if registered is not None else ()

    #: See `wire_extra`. Empty for every refusal that has nothing structured to
    #: add; a class default so no raise site pays for one it does not declare.
    _wire_extra: Mapping[str, Any] = MappingProxyType({})

    @property
    def wire_extra(self) -> Mapping[str, Any]:
        """What this refusal says on the wire BEYOND the four common keys.

        A refusal that has something STRUCTURED to say — a blocked archive's
        `noun` and the `blocking` children, a stale write's `current_version` —
        declares it here, beside itself, and says it once for both doors:
        `wire_refusal` is still the only composer and reads this attribute
        exactly as `config/api.py` reads `retry_after` off `RateLimited`.

        **The four common keys are not overridable, and that is refused AT
        RAISE** — the setter below — rather than when the body is composed: a
        refusal that could rewrite `code` or `detail` from a raise site would be
        a second composer wearing an attribute name, and a mistake found only
        on the unhappy path is found in production.
        """
        return self._wire_extra

    @wire_extra.setter
    def wire_extra(self, value: Mapping[str, Any]) -> None:
        colliding = sorted(set(value) & WIRE_COMMON_KEYS)
        if colliding:
            raise ValueError(
                f"{type(self).__name__}.wire_extra may not redefine {', '.join(colliding)}: "
                "the four common keys are the grammar every client branches on, and a "
                "raise site that could rewrite one would be a second composer."
            )
        self._wire_extra = MappingProxyType(dict(value))

    def __str__(self) -> str:
        return self.detail


register_refusal(
    code="not_found",
    boundary="selector",
    remedy=(
        "Read the row through the scoped selector for the acting tenant and hat — "
        ".for_tenant(tenant).visible_to(actor) — before concluding it is gone. A row "
        "in another tenant, or in a branch this hat does not cover, answers exactly "
        "the same way on purpose, so check X-Tenant and X-Org first."
    ),
    fact=(
        "There is no such row here. A row that exists in another tenant, or in a part "
        "of this tenant's tree your acting organization does not cover, answers exactly "
        "the same way — not-there and not-yours are one answer, deliberately, because a "
        "refusal that told them apart would confirm the row exists."
    ),
    remedies=(
        Remedy("Check which tenant you are acting in", "header:X-Tenant"),
        Remedy("Check which organization you are wearing", "header:X-Org"),
    ),
    status=404,
)


class NotFound(DomainError):
    """The row is not there — or it is, and it is not the caller's.

    Deliberately the same answer in both cases. A refusal that distinguished
    them would be an existence oracle: "403 on a row in another tenant" tells
    you the row exists, which is the fact the tenancy was hiding.
    """

    code = "not_found"
    default_detail = "Not Found"


register_refusal(
    code="conflict",
    boundary="service",
    remedy=(
        "Something already holds the name, the id or the state being written. Re-read "
        "the row and retry against what is now true; a caller that wants the first "
        "answer back instead of a second attempt sends an Idempotency-Key."
    ),
    fact=(
        "Something that already exists holds the name, the identifier or the state this "
        "write asked for. Nothing was written."
    ),
    remedies=(
        Remedy("Re-read the row and retry against what is true now", "self:reread"),
        Remedy(
            "Ask for the first answer back instead of a second attempt", "header:Idempotency-Key"
        ),
    ),
    status=409,
)


class Conflict(DomainError):
    """The write would collide with a row that already exists."""

    code = "conflict"
    default_detail = "That conflicts with a row that already exists."


register_refusal(
    code="forbidden",
    boundary="policy",
    remedy=(
        "The caller is who they say they are and authz.require said no. Read the "
        "action's entry in the owning app's policies.py and the actor's Membership "
        "role; widening the policy is a decision to record, never a patch at the door."
    ),
    fact=(
        "You are who you say you are, and this is still not yours to do here. The row "
        "exists and you can see it; the action is what was refused."
    ),
    remedies=(
        Remedy("Check the role your membership gives you here", "self:membership"),
        Remedy("Ask somebody who administers this organization", "header:X-Org"),
    ),
    status=403,
)


class Forbidden(DomainError):
    """The caller is who they say they are and still may not do this."""

    code = "forbidden"
    default_detail = "You do not have permission to do that."


register_refusal(
    code="invalid",
    boundary="service",
    remedy=(
        "Read `errors` field by field and resend. The keys are the schema's own field "
        "names (or __all__ for an object-level rule), so a client can point at the "
        "input that failed rather than at the request."
    ),
    fact=(
        "The input does not hold. The answer names each field that is wrong and why, in "
        "the schema's own field names, so the failure can be pointed at rather than "
        "guessed at."
    ),
    remedies=(
        Remedy("Read the failing fields and resend", "field:errors"),
        Remedy("Read the shape this endpoint accepts", "docs:openapi"),
    ),
    # 400 — a rule about your data did not hold; a service looked and said no.
    # NOT 422, which is what the door answers when the request never matched the
    # operation's shape at all (`invalid_body`, config/api.py).
    status=400,
)


class Invalid(DomainError):
    """The input does not hold, field by field.

    `errors` maps a field name (or `__all__`) to its messages — the same shape
    Django's `ValidationError.message_dict` uses, so a form, a Pydantic schema
    and a model constraint all reach a client looking the same.
    """

    code = "invalid"
    default_detail = "The request is not valid."

    def __init__(
        self,
        errors: Mapping[str, list[str]] | None = None,
        *,
        detail: str | None = None,
        remedies: Sequence[Remedy] | None = None,
    ) -> None:
        self._errors: dict[str, list[str]] = {
            str(field): [str(message) for message in messages]
            for field, messages in (errors or {}).items()
        }
        flattened = [message for messages in self._errors.values() for message in messages]
        super().__init__(detail or " ".join(flattened) or None, remedies=remedies)

    @property
    def errors(self) -> dict[str, list[str]]:
        return dict(self._errors)

    @classmethod
    def from_django(cls, exc: DjangoValidationError) -> Invalid:
        """Turn what `full_clean()` raises into what a service raises."""
        if hasattr(exc, "error_dict"):
            return cls(exc.message_dict)
        return cls({NON_FIELD_KEY: list(exc.messages)})


register_refusal(
    code="invalid_cursor",
    boundary="door",
    remedy=(
        "The `?cursor=` the client sent was not one this deployment minted, or was "
        "minted on a different LIST, or under a different `?ordering=`. Cursors are "
        "opaque and signed (apps/core/api/pagination.py): follow the `next_cursor` a "
        "response gave you rather than building, editing, or carrying one across a "
        "change of endpoint or sort order."
    ),
    fact=(
        "That cursor is not one this API issued for this walk. A cursor is opaque and "
        "signed, and it names a position in ONE list in ONE ordering — editing one, "
        "presenting one to a different list, or replaying one against a different sort "
        "order has no meaning to answer. Nothing was skipped and nothing was lost."
    ),
    remedies=(
        Remedy("Start the walk again with no cursor", "field:cursor"),
        Remedy("Follow the next_cursor the last response gave you", "field:next_cursor"),
    ),
    # 400, its base class's. The line exists because this table is keyed on the
    # CODE and a narrower code needs its own declaration — the same fact the
    # `CODE_STATUS["invalid_cursor"]` append used to record under `config/`.
    status=400,
)


class InvalidCursor(Invalid):
    """The `?cursor=` did not come from here, or not from this ordering.

    An `Invalid` rather than a code of its own family, because it is the same
    kind of answer — the input does not hold — and a client that already
    branches on `invalid` keeps working. The narrower code exists because the
    fix is genuinely different: nothing about the *filters* is wrong, and the
    remedy is "stop building cursors", not "re-read `errors` field by field".

    Deliberately NOT what a foreign tenant's cursor gets. That one is signed and
    well-formed and simply belongs to somebody else, so it answers `not_found`
    like every other row this tenant cannot reach — a refusal that told the two
    apart would confirm the other tenant's walk exists.
    """

    code = "invalid_cursor"
    default_detail = "That cursor is not one this API issued for this list."


register_refusal(
    code="rate_limited",
    boundary="door",
    remedy=(
        "Wait Retry-After seconds and retry. The throttle is declared at the door "
        "(core.throttling, config/api.py), so a client that genuinely needs more "
        "headroom asks for a scope rather than retrying harder."
    ),
    fact=(
        "You have asked for more than this door allows in the window it counts over. "
        "Nothing was written, and the allowance refills on its own."
    ),
    remedies=(Remedy("Wait the seconds Retry-After names, then retry", "header:Retry-After"),),
    status=429,
)


class RateLimited(DomainError):
    """Too much, too fast.

    `retry_after` is seconds, and it is the whole reason this is not a bare
    `Forbidden`: a client that is told when to come back stops hammering.
    """

    code = "rate_limited"
    default_detail = "Too many requests. Try again shortly."

    def __init__(
        self,
        detail: str | None = None,
        *,
        retry_after: int | None = None,
        remedies: Sequence[Remedy] | None = None,
    ) -> None:
        self.retry_after = retry_after
        super().__init__(detail, remedies=remedies)


register_refusal(
    code="search_unavailable",
    boundary="service",
    remedy=(
        "Both search engines were unreachable at once. The primary index being down "
        "is a degraded state the product survives (ADR search-2) — it is answered "
        "from Postgres and never refused — so this code means the FALLBACK could not "
        "answer either, which is a database problem rather than a search one. Look at "
        "the database before looking at the index."
    ),
    fact=(
        "No engine could answer this search: the index is unreachable and the "
        "fallback did not answer either. Nothing is wrong with the request, and "
        "nothing was written."
    ),
    remedies=(Remedy("Retry the same search shortly", "docs:openapi"),),
    # 503, and one of the two 5xx in this file that are not a bug: the caller's
    # request was fine and retrying is the remedy, which is what 503 means and
    # what `error`'s bare 500 above does not say.
    status=503,
)


class SearchUnavailable(DomainError):
    """No engine could answer a search at all.

    **The narrow residual R-d left behind**, and it is worth saying what it is
    not: an unreachable search index is NOT this. That is a degraded state the
    circuit in `apps/search/selectors.py` survives — the same request is
    answered from Postgres with `engine="postgres"` — because ADR search-2
    rules a degradation the system survives a state the product announces
    rather than one it refuses. This code is reached only when the fallback
    could not answer either, which means the database did not answer.

    **Why the class lives in `core` when the code is search's.** `config/api.py`
    owns the status number (house rule 14 keeps HTTP vocabulary above the
    doors), and that module may not import a product app: `INSTALLED_APPS` is
    derived from `apps/*/apps.py`, so a `config` that named `apps.search` would
    make an optional app a hard dependency of the mount. R-a's own comment in
    `apps/search/api.py` named this file for exactly that reason, and this is
    that line. The alternative — a generic platform `Unavailable` reusable by
    the storage seam — was rejected as wider than the frontier being closed;
    the day a second seam needs one, this is the precedent it generalises.
    """

    code = "search_unavailable"
    default_detail = (
        "Search is not answering right now. Nothing is wrong with your request — try again shortly."
    )


# --- The second seam, and the precedent above says this is where it generalises


#: How long a client is told to wait. Small on purpose: slot exhaustion clears
#: when the requests already in flight finish, which is seconds, not minutes —
#: and a `Retry-After` longer than the outage turns a recovery into an outage
#: that lasted as long as the header said. A raise site that knows better passes
#: its own; nothing here reads a setting, because the number that would make
#: this tunable is a number nobody would ever have measured.
DATABASE_RETRY_AFTER_SECONDS = 5

#: SQLSTATE class 08 — *connection exception*, the whole class. Every member of
#: it (`08000`, `08001`, `08003`, `08006`, `08P01`) says the same thing: the
#: conversation with the server did not happen or did not survive. There is no
#: member of class 08 that means "your query was wrong".
CONNECTION_SQLSTATE_CLASS = "08"

#: The two codes outside class 08 that mean "not now, but the request was fine".
#: `53300` is `too_many_connections` — the server is up, has slots configured,
#: and every one of them is spoken for; it is the code that composed 6,973 of
#: LOAD-1b's 7,040 errors. `57P03` is `cannot_connect_now` — the server is
#: starting up, recovering, or in single-user mode. Both are *come back later*.
CONNECTION_SQLSTATES = frozenset({"53300", "57P03"})

#: How far down a `__cause__` chain a SQLSTATE is looked for. Bounded because a
#: cause chain is somebody else's data structure and a cycle in one is not this
#: function's problem to discover at three in the morning. Three links is the
#: real depth (Django's wrapper → the driver's error → whatever it wrapped);
#: five is the belt.
CAUSE_LINKS = 5


def sqlstate_of(exc: BaseException | None) -> str | None:
    """The five-character SQLSTATE the server sent, walking `__cause__`.

    **The whole reason this is not `exc.sqlstate`.** What reaches application
    code is never the driver's exception: `BaseDatabaseWrapper.wrap_database_errors`
    catches `psycopg.Error` and re-raises `django.db.OperationalError(*args)`
    with the original as `__cause__`. The Django class carries the *message* and
    no code at all — so a classifier that read the attribute off what it caught
    would read `None` for every real fault, and answer "connection trouble" to a
    deadlock. `pgcode` is read too, for a product that swaps in psycopg2.
    """
    seen = 0
    current: BaseException | None = exc
    while current is not None and seen < CAUSE_LINKS:
        code = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if isinstance(code, str) and code:
            return code
        current = current.__cause__
        seen += 1
    return None


def is_connection_shaped(exc: BaseException) -> bool:
    """Is this the database being unreachable, rather than the database saying no?

    **Stated closed, because the cost of being wide is a retry loop against a
    healthy server.** True for an `OperationalError` (and nothing else — a
    `ProgrammingError` or an `IntegrityError` is not in this hierarchy at all)
    when either:

    * its SQLSTATE is class `08`, `53300` or `57P03` — see the constants above; or
    * **there is no SQLSTATE anywhere in the cause chain**, which is not an
      absence of evidence: a SQLSTATE comes *from the server*, in a response, so
      an `OperationalError` carrying none is one raised before any server ever
      answered. That is a network refusal, a DNS failure, a TLS failure — and
      `psycopg_pool.PoolTimeout`, which subclasses `psycopg.OperationalError`,
      carries no code, and is exactly what a bounded connection pool raises at its
      own exhaustion. The two failure classes meet here, and they meet by shape
      rather than by name: nothing in this module imports `psycopg_pool`.

    Everything else stays what it was. `40P01` (deadlock), `57014`
    (query cancelled) and `55P03` (lock not available) are all `OperationalError`s
    and all three are 500s: the connection was fine, and "come back later" is
    not the truth about any of them.

    DOES NOT COVER — declared: a driver exception that never passed through
    Django's wrapper (nothing in the ORM produces one), and the sqlstate-absent
    leg is a judgment. A managed database's failover may present a shape nobody
    enumerated; the live run is the only honest instrument for that.
    """
    if not isinstance(exc, DjangoOperationalError):
        return False
    sqlstate = sqlstate_of(exc)
    if sqlstate is None:
        return True
    return sqlstate.startswith(CONNECTION_SQLSTATE_CLASS) or sqlstate in CONNECTION_SQLSTATES


register_refusal(
    code="database_unavailable",
    boundary="door",
    remedy=(
        "The database refused or could not be reached — most often every configured "
        "connection slot is spoken for (SQLSTATE 53300). Look at the pool's own "
        "numbers first: connections held versus max_size, and held versus active. "
        "The count of these refusals is the back-off census — `core.database.unavailable` "
        "carries the SQLSTATE, so slot exhaustion is legible apart from a failover. "
        "It is a `door` refusal because nothing below the doors classified anything: "
        "a service raised no refusal at all, the driver did, and the door is where "
        "that becomes an answer."
    ),
    fact=(
        "The database could not be reached for this request. Nothing about the "
        "request was wrong and nothing was written — the same request sent again "
        "shortly is expected to succeed."
    ),
    remedies=(
        Remedy(
            "Wait the interval in Retry-After and send the same request again",
            "header:Retry-After",
        ),
        Remedy("Check whether this deployment is ready to serve", "route:readyz"),
    ),
    # 503, the second one, on the same terms as `search_unavailable`'s above.
    status=503,
)


class DatabaseUnavailable(DomainError):
    """The database could not be reached — a 503, not a 500.

    **What paid for this class.** LOAD-1b: 6,973 of 7,040 errors were connection
    refusals answered as bare HTTP 500s with no retry semantics, at the exact
    moment every client should have been backing off. A 500 tells a client the
    request was a bug, so a well-behaved one retries immediately or not at all;
    a 503 with `Retry-After` tells it the truth, which is the only input a
    back-off has.

    **The precedent, taken up.** `SearchUnavailable` above rejected a generic
    platform `Unavailable` "as wider than the frontier being closed" and named
    itself the thing to generalise from "the day a second seam needs one". This
    is that day and this is that generalisation: a sibling with the same shape,
    not a base class hoisted over both — hoisting would put the storage seam and
    the mail seam under a word none of them said, and each of those frontiers is
    still shut.

    **`retry_after` rides plumbing that already exists.** `RateLimited` has
    carried the attribute since the throttles landed and `config/api.py` stamps
    the header off it, so the header is not a second mechanism — the same three
    lines answer both.
    """

    code = "database_unavailable"
    default_detail = (
        "The database is not answering right now. Nothing is wrong with your "
        "request and nothing was written — try the same request again shortly."
    )

    def __init__(
        self,
        detail: str | None = None,
        *,
        retry_after: int | None = None,
        remedies: Sequence[Remedy] | None = None,
    ) -> None:
        self.retry_after = DATABASE_RETRY_AFTER_SECONDS if retry_after is None else retry_after
        super().__init__(detail, remedies=remedies)


def database_unavailable(exc: BaseException, *, seam: str) -> DatabaseUnavailable:
    """The refusal for a connection-shaped fault, and the operator's one line.

    **Both halves in one call, deliberately.** Three seams answer this refusal —
    ninja's handler, `handler500` above the middleware chain, and the machine
    door's `tool_call` — and a log line each of them wrote for itself would be
    three events with three spellings, which is not a census. `seam` is the half
    the bound context cannot know (`door`, `tenant_id`, `request_id` and the
    trace ids are already on the line without anybody passing them); it is what
    says whether the fault erupted above ninja or below it, which is the whole
    reason this event exists.

    A dashboard composes err% out of this event: `core.database.unavailable` counted
    against total requests is the back-off rate, and `sqlstate` is what tells
    slot exhaustion apart from a failover in the same census.
    """
    log.warning(
        "core.database.unavailable",
        sqlstate=sqlstate_of(exc),
        seam=seam,
        error=type(exc).__name__,
    )
    return DatabaseUnavailable()


# --- The one composer --------------------------------------------------------
#
# Two doors answer a refusal — `config/api.py` in JSON and `core.mcp.tool_call`
# in a message an assistant reads — and before this pair existed each composed
# its own. That is the drift the grammar is against: the screen and the
# assistant told a person two different things about one refusal, and neither
# was wrong enough to notice. So the body is built ONCE, here, and the message
# is rendered from that same body rather than from the exception again.


#: What a refusal body is served AS. Spelled here, beside the one composer,
#: because the two doors that answer one reach it from opposite sides: the HTTP
#: door gets it from ninja's renderer, and `apps/core/idempotency.py` refuses
#: from IN FRONT of the API, where there is no renderer to ask and `apps/` may
#: not import `config`. Naming it once and PINNING it against the mounted API in
#: a test (`apps/core/tests/test_idempotency_over_the_wire.py`) is the same
#: shape `apps/events/services.DOOR_ENCODER` uses for the same reason.
#:
#: The charset is the half that was missing: every other refusal on the
#: same routes answered `application/json; charset=utf-8` and these two answered
#: `application/json`, which is legible from outside as "this body was built
#: somewhere else".
REFUSAL_CONTENT_TYPE = "application/json; charset=utf-8"


def wire_refusal(exc: DomainError) -> dict[str, Any]:
    """The refusal as a client sees it. **The only builder of a refusal body.**

    `{detail, code}` always, `errors` when the refusal names fields, `remedies`
    when there are any — which, for every registered code, is always, because
    `register_refusal` refuses a code with none. Plus whatever a particular
    refusal declared in `wire_extra` (a blocked archive's `noun` and
    `blocking`), beside the four and never over one of them.

    **Additive, on purpose**: `remedies` joins a body that already carried
    `detail`, `code` and `errors`, and nothing was renamed or removed. A client
    pinned to the old three keys still reads them; the fact stays off the wire
    entirely (it is what the registry says the *code* means, not what happened
    on this request) and the internal `remedy` prose stays where it was written
    — in the registry, for whoever is holding the refusal.
    """
    body: dict[str, Any] = {"detail": exc.detail, "code": exc.code}
    if exc.errors:
        body["errors"] = exc.errors
    # What a refusal has to say BEYOND the four common keys, declared beside
    # itself (`DomainError.wire_extra`) and said once for both doors. The setter
    # refused a colliding key at raise; this re-check is the belt for a
    # subclass that bypassed the property.
    for key, value in exc.wire_extra.items():
        if key in WIRE_COMMON_KEYS:
            raise ValueError(f"{type(exc).__name__}.wire_extra may not redefine {key!r}.")
        body[key] = value
    remedies = exc.remedies
    if remedies:
        body["remedies"] = [
            {"label": remedy.label, "destination": remedy.destination} for remedy in remedies
        ]
    return body


#: What introduces a refusal's `wire_extra` on a text door: the keys REST's body
#: carries beside the common four, as ONE compact JSON object at the end of the
#: line — so a machine reader parses exactly what REST sent (`refusal_extra`).
REFUSAL_EXTRA_MARKER = " | carries: "


def refusal_message(body: Mapping[str, Any], *, extra: bool = True) -> str:
    """One line of text for a door with no status codes and no JSON body.

    Rendered from `wire_refusal`'s output rather than from the exception, so
    "the machine door said what the REST door said" is true by construction
    rather than by two modules agreeing. The `code` leads because it is what a
    client branches on; the order of everything after it is the order the body
    holds, so the same refusal renders the same string every time.

    **Every key beyond the common four rides too** (a refusal's `wire_extra` —
    a stale save's `current_version`, a blocked verb's `noun` and `blocking`):
    appended after `REFUSAL_EXTRA_MARKER` as one JSON object, sorted and
    compact, so the MCP door answers the same facts REST does and a client
    branches on the value rather than re-reading. `extra=False` is for a human
    reader (the admin's message bar), where a JSON tail is noise.
    """
    message = f"{body['code']}: {body['detail']}"
    errors = body.get("errors") or {}
    if errors:
        fields = "; ".join(f"{name}: {' '.join(messages)}" for name, messages in errors.items())
        message = f"{message} ({fields})"
    remedies = body.get("remedies") or []
    if remedies:
        offered = "; ".join(f"{entry['label']} [{entry['destination']}]" for entry in remedies)
        message = f"{message} — you can: {offered}"
    carried = {key: value for key, value in body.items() if key not in WIRE_COMMON_KEYS}
    if extra and carried:
        encoded = json.dumps(carried, sort_keys=True, separators=(",", ":"), default=str)
        message = f"{message}{REFUSAL_EXTRA_MARKER}{encoded}"
    return message


def refusal_extra(message: str) -> dict[str, Any]:
    """The `wire_extra` keys a text-door refusal carried, parsed back; `{}` when none."""
    head, marker, tail = message.rpartition(REFUSAL_EXTRA_MARKER)
    if not marker:
        return {}
    parsed = json.loads(tail)
    return dict(parsed) if isinstance(parsed, dict) else {}


@contextmanager
def as_invalid() -> Iterator[None]:
    """Run model validation and raise the domain's refusal instead of Django's.

        with as_invalid():
            widget.full_clean()

    `full_clean()` is the right place for a model's own rules and it raises
    `django.core.exceptions.ValidationError`, which is Django's word rather
    than the domain's. Two lines here keep every service speaking one
    vocabulary, and keep `config/api.py` the only module that knows a status
    code.
    """
    try:
        yield
    except DjangoValidationError as exc:
        raise Invalid.from_django(exc) from exc


# --- the noun-verb family's blocker shape ---------------------------------------
#
# One shape for "a live child holds this noun where it is", shared by every verb
# that can be held — archive, restore, move, merge. A child app answers with
# these from its `<verb>_blockers.py` (`apps.core.blockers`); the parent's
# service raises the verb's `Blocked` refusal over whatever came back, so the
# refusal is composed once by the parent and the children only ever say WHICH
# rows and WHERE the reader clears them.

#: A blocker's noun: the child's kind in lower snake case (`widget_entry`).
_BLOCKER_NOUN = re.compile(r"^[a-z][a-z0-9_]*$")

#: A door is ONE remedy kind, `route:` — the blocking child's operation by its
#: `url_name` (the house's spelling: `widget-list`, `widget_entry-record`), with
#: an optional query naming the parent (`route:widget-list?policy=<id>`). Never
#: a URL and never another remedy kind: `self:`, `header:` and `docs:` say
#: something about the CALLER, and a blocker is a row somewhere else.
_BLOCKER_DOOR = re.compile(r"^route:[a-z][a-z0-9_]*(?:-[a-z0-9_]+)*(?:\?[A-Za-z0-9_=&.-]+)?$")


@dataclass(frozen=True, slots=True)
class Blocker:
    """One live child holding a noun where it is, and where the reader clears it.

    `noun` is the child's kind (`widget`); `door` the remedy destination that
    lands on it — a `route:<url_name>[?query]` token, never a URL (ADR core-5);
    `label` the act as the reader takes it (*Move or archive the widgets that
    name this policy first*). Refused at construction when malformed, so a bad
    blocker fails where it is written rather than on the wire.
    """

    noun: str
    door: str
    label: str

    def __post_init__(self) -> None:
        if not _BLOCKER_NOUN.match(self.noun):
            raise ValueError(
                f"Blocker.noun is the child's kind in lower snake case (`widget`, "
                f"`widget_entry`); got {self.noun!r}."
            )
        if not _BLOCKER_DOOR.match(self.door):
            raise ValueError(
                f"Blocker.door is the blocking child's operation as a `route:` remedy — "
                f"`route:widget-list?policy=<id>` — never a URL and never another remedy "
                f"kind; got {self.door!r}."
            )
        if not self.label.strip():
            raise ValueError("Blocker.label is the act the reader takes; got none.")


class Blocked(Conflict):
    """A live child holds this noun where it is; the verb refuses and names it (E9).

        raise ArchiveBlocked(
            "This policy is still named by live widgets.",
            noun="widget_policy",
            blocking=(
                Blocker(
                    noun="widget",
                    door=f"route:widget-list?policy={policy.pk}",
                    label="Move or archive the widgets that name this policy first",
                ),
            ),
        )

    The family's one blocked shape — each held verb is a subclass with its own
    code (`archive_blocked`, `restore_blocked`, later `move_blocked`,
    `merge_blocked`) because the way out differs per verb. A `Conflict`, so the
    door answers 409 by the MRO: nothing collides, something depends. The
    blockers become the refusal's REMEDIES (label + door), and ride `wire_extra`
    as `noun` + `blocking: [{noun, door}]`, so a client branching on which
    child held it reads a field rather than parsing a sentence. Nothing was
    written, and nothing cascades.
    """

    def __init__(
        self,
        detail: str | None = None,
        *,
        noun: str,
        blocking: Sequence[Blocker],
    ) -> None:
        held = tuple(blocking)
        if not held or not all(isinstance(entry, Blocker) for entry in held):
            raise ValueError(
                f"{type(self).__name__} names its blocking children — at least one "
                "Blocker(noun=…, door=…, label=…). A block with nothing named is a dead "
                "end: the reader could not clear the way."
            )
        if not _BLOCKER_NOUN.match(noun):
            raise ValueError(
                f"{type(self).__name__}.noun is the kind the verb was asked of; got {noun!r}."
            )
        super().__init__(
            detail,
            remedies=tuple(Remedy(entry.label, entry.door) for entry in held),
        )
        self.noun = noun
        self.blocking = held
        self.wire_extra = {
            "noun": noun,
            "blocking": [{"noun": entry.noun, "door": entry.door} for entry in held],
        }


register_refusal(
    code="archive_blocked",
    boundary="service",
    remedy=(
        "A live child still holds this noun in the book — a child app's "
        "`archive_blockers.py` said so (`core.blockers.blockers_for`). The archive does "
        "not cascade; the raise site names each blocker as a structured remedy — its "
        "noun and its door — and the caller clears the way by hand, then archives "
        "again. Raise `ArchiveBlocked(detail, noun=…, blocking=…)`."
    ),
    fact=(
        "This cannot be archived while something live still depends on it. Nothing "
        "was written, and nothing it depends on was touched."
    ),
    remedies=(Remedy("Clear what still depends on it, then archive again", "self:reread"),),
    status=409,
)


class ArchiveBlocked(Blocked):
    """A live child holds this noun in the book; the archive refuses and names it."""

    code = "archive_blocked"
    default_detail = "This cannot be archived while something still depends on it."


register_refusal(
    code="restore_blocked",
    boundary="service",
    remedy=(
        "Something a restore would bring back into the book is not there for it any "
        "more — a child app's `restore_blockers.py` said so (a row it names was itself "
        "archived, a name it held is now another live row's). Nothing cascades back; "
        "the raise site names each blocker as a structured remedy and the caller "
        "clears the way first. Raise `RestoreBlocked(detail, noun=…, blocking=…)`."
    ),
    fact=(
        "This cannot be restored until something it depends on is put right. Nothing "
        "was written; it is still archived."
    ),
    remedies=(Remedy("Put right what it depends on, then restore again", "self:reread"),),
    status=409,
)


class RestoreBlocked(Blocked):
    """Something the restored row depends on is not there for it; the restore refuses."""

    code = "restore_blocked"
    default_detail = "This cannot be restored until what it depends on is put right."


register_refusal(
    code="archived",
    boundary="service",
    remedy=(
        "The row is ARCHIVED: its reads answer, read-only, and every write other than "
        "its restore refuses (`core.verbs.require_live`). Restore it through "
        "`restore_<noun>` — the remedy names the route — and write again; an archived "
        "row is never edited in place, because an edit nobody can see in the book is a "
        "change nobody reviews."
    ),
    fact=(
        "This is archived. It can be read, and it cannot be changed until it is "
        "restored. Nothing was written."
    ),
    remedies=(Remedy("Restore it first", f"route:{NOUN_SLOT}-restore"),),
    status=409,
)


class Archived(Conflict):
    """A write named an archived row. Restore it first.

        raise Archived(noun="widget")

    The remedy is the noun's own restore door (`route:<noun>-restore`), and
    `noun` rides `wire_extra` so a client knows which restore to offer without
    parsing the sentence.
    """

    code = "archived"
    default_detail = "This is archived; restore it before changing it."

    def __init__(self, detail: str | None = None, *, noun: str) -> None:
        if not _BLOCKER_NOUN.match(noun):
            raise ValueError(f"Archived.noun is the archived row's kind; got {noun!r}.")
        super().__init__(detail, remedies=remedies_for_noun(self.code, noun))
        self.noun = noun
        self.wire_extra = {"noun": noun}


register_refusal(
    code="stale_version",
    boundary="service",
    remedy=(
        "The row is `Versioned` and the write carried a `version` that is no longer "
        "the row's: somebody else saved it in between (`core.concurrency."
        "require_version`, under the row lock). Re-read the row, show the person what "
        "changed, and send the write again with the version the re-read answered — "
        "never retry blindly with the new number, which would overwrite what the "
        "other save said."
    ),
    fact=(
        "Somebody else changed this since you read it, so your change was not saved. "
        "Nothing was written; the answer says which version it has now."
    ),
    remedies=(Remedy("Read it again, then make your change to what is there now", "self:reread"),),
    status=409,
)


class StaleVersion(Conflict):
    """A write to a `Versioned` row carried a version the row no longer has.

        raise StaleVersion(current_version=version_of(locked))

    Raised by `core.concurrency.require_version` and nowhere else. The row's
    CURRENT version rides `wire_extra` so a face can reload and re-offer the
    edit without a second request to learn what it should have sent.
    """

    code = "stale_version"
    default_detail = "This changed since you read it; read it again and retry."

    def __init__(self, detail: str | None = None, *, current_version: int) -> None:
        if isinstance(current_version, bool) or not isinstance(current_version, int):
            raise ValueError(
                f"StaleVersion.current_version is the row's version as an int; got "
                f"{current_version!r}."
            )
        # The version it has now, said in words to the reader; the machine's
        # copy is `wire_extra`'s key, never a token in the sentence.
        super().__init__(
            detail
            or (
                "This changed since you read it; it is at version "
                f"{current_version} now. Read it again and retry."
            )
        )
        self.current_version = current_version
        self.wire_extra = {"current_version": current_version}


register_refusal(
    code="move_blocked",
    boundary="service",
    remedy=(
        "Something that must stay where it is holds this noun where it is: an "
        "APPEND-ONLY row derives its organization from it (a ledger line is recorded "
        "where it was written, and moving it is the rewrite house rule 20 forbids), or "
        "a child app's `move_blockers.py` said so (`core.blockers.blockers_for`). "
        "Nothing moved. The raise site names each blocker; a product that wants its "
        "ledger to follow declares its own road, deliberately. Raise "
        "`MoveBlocked(detail, noun=…, blocking=…)`."
    ),
    fact=(
        "This cannot move while something recorded under it has to stay where it was "
        "written. Nothing was moved."
    ),
    remedies=(Remedy("See what holds it where it is", "self:reread"),),
    status=409,
)


class MoveBlocked(Blocked):
    """Something that must stay put holds this noun at its node; the move refuses."""

    code = "move_blocked"
    default_detail = "This cannot move while something recorded under it must stay put."


register_refusal(
    code="merge_blocked",
    boundary="service",
    remedy=(
        "Something holds this noun apart from the one it would be merged into — a "
        "child app's `merge_blockers.py` said so (`core.blockers.blockers_for`). "
        "Nothing was re-pointed and neither row changed. The raise site names each "
        "blocker as a structured remedy; the caller clears the way, then merges "
        "again. Raise `MergeBlocked(detail, noun=…, blocking=…)`."
    ),
    fact=(
        "These two cannot be merged while something still holds them apart. Nothing "
        "was written, and neither record changed."
    ),
    remedies=(Remedy("See what holds them apart", "self:reread"),),
    status=409,
)


class MergeBlocked(Blocked):
    """Something holds the two rows apart; the merge refuses and names it."""

    code = "merge_blocked"
    default_detail = "These cannot be merged while something still holds them apart."


register_refusal(
    code="merged",
    boundary="service",
    remedy=(
        "The row was MERGED into another and survives only as a tombstone: its reads "
        "answer, read-only, naming the survivor in `merged_into`, and every write "
        "refuses (`core.verbs.require_live`). Write to the survivor instead — the "
        "remedy names its detail door and `merged_into` its id. There is no unmerge."
    ),
    fact=(
        "This was merged into another record and can no longer be changed. Nothing "
        "was written; the answer names the record it became."
    ),
    remedies=(Remedy("Open the record it became", f"route:{NOUN_SLOT}-detail"),),
    status=409,
)


class Merged(Conflict):
    """A write named a merged-away row. Write to its survivor.

        raise Merged(noun="widget", merged_into=loser.merged_into_id)

    The remedy is the noun's detail door (`route:<noun>-detail`) and the
    survivor's id rides `wire_extra` beside `noun`, so a client re-reads the
    right row without parsing the sentence.
    """

    code = "merged"
    default_detail = "This was merged into another record; change that one instead."

    def __init__(self, detail: str | None = None, *, noun: str, merged_into: Any) -> None:
        if not _BLOCKER_NOUN.match(noun):
            raise ValueError(f"Merged.noun is the merged row's kind; got {noun!r}.")
        super().__init__(detail, remedies=remedies_for_noun(self.code, noun))
        self.noun = noun
        self.merged_into = str(merged_into)
        self.wire_extra = {"noun": noun, "merged_into": str(merged_into)}


register_refusal(
    code="merge_survivor",
    boundary="service",
    remedy=(
        "The row is a merge's SURVIVOR: earlier records were merged into it and their "
        "tombstones name it (`Mergeable.merged_into`, PROTECT), so deleting it would "
        "leave them pointing at nothing. Refuse before the delete "
        "(`core.verbs.require_no_merged_losers`) rather than letting the database's "
        "PROTECT surface as a generic `conflict`; the caller archives the row instead, "
        "which keeps every tombstone's answer true."
    ),
    fact=(
        "Other records were merged into this one and still point at it, so it cannot be "
        "deleted. Nothing was removed; archive it to take it out of the book."
    ),
    remedies=(Remedy("Archive it instead", f"route:{NOUN_SLOT}-archive"),),
    status=409,
)


class MergeSurvivor(Conflict):
    """A delete named a row others were merged into. Archive it instead.

        raise MergeSurvivor(noun="widget")

    The remedy is the noun's archive door (`route:<noun>-archive`) and `noun`
    rides `wire_extra`, so a client offers the archive without parsing the
    sentence.
    """

    code = "merge_survivor"
    default_detail = (
        "Other records were merged into this one, so it cannot be deleted; archive it instead."
    )

    def __init__(self, detail: str | None = None, *, noun: str) -> None:
        if not _BLOCKER_NOUN.match(noun):
            raise ValueError(f"MergeSurvivor.noun is the survivor's kind; got {noun!r}.")
        super().__init__(detail, remedies=remedies_for_noun(self.code, noun))
        self.noun = noun
        self.wire_extra = {"noun": noun}
