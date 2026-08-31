"""The OpenAPI document as the contract — assembled once, from what is already true.

**The document is the product's contract, and a contract with gaps in it is the
thing the fifteenth developer meets first.** ADR api-1 is the ruling this module
carries out: every route's prose comes from the route's own docstring, every
refusal is enumerated out of the refusal registry, every header the doors read
is documented once, every schema arrives with an example, and the whole of it is
derived rather than typed — because fifty-one routes hand-annotated is
fifty-one places for the annotation and the behaviour to part company, and five
cycles of review is what already missed them.

Five derivations, and nothing else in here:

* **Prose.** A route's docstring is split on a `---` line into a **contract
  half** (above — what a caller is owed) and a **workshop half** (below — the
  note to the next person who edits the file). The contract half is itself in
  two parts: its **first line is the TITLE** — a short noun or verb phrase, no
  Markdown, no trailing period, at most `TITLE_MAX_LENGTH` characters — and
  everything after it is the **description**, which opens with the sentence
  that says what the operation does. `summary` is the title and `description`
  is the body, because a navigation sidebar shows summaries and a sentence in a
  sidebar is a sentence nobody can scan (the owner's ruling of 2026-08-24). The
  MCP twin renders **the whole contract half**, title line included, imported
  off the route function, so the two doors cannot say different things about
  one capability — that is house rule 17 one surface earlier, and it is why
  `mcp.py` takes `description=contract_of(...)` rather than a string somebody
  typed twice.
* **Refusals.** What a route can answer with is derived from the shape of the
  door it is — a body can be invalid, a path parameter can be missing, a write
  can conflict, everything can be throttled — and the *text* for each code comes
  off `core.exceptions.REFUSALS`, the registry `introspect` prints. A route that
  knows better than the derivation says so with `@refuses(...)`, which
  **replaces** the derived set and is checked against the registry (house rule
  41). Nothing here writes refusal prose.
* **Headers, both directions.** The ones a caller SENDS — `X-Tenant`, `X-Org`,
  `Idempotency-Key` — are documented from the constants that declare them
  (house rule 40's population), on the operations that actually read them, so
  the hierarchy is explained in the one place a client is looking. The ones the
  platform SENDS BACK — `X-Request-Id`, `X-Correlation-Id`,
  `Idempotent-Replayed`, `Retry-After` — are documented the same way, off
  `RESPONSE_HEADERS` declarations collected from the modules that stamp them,
  onto the responses each one lands on. A writer that declares one joins the
  document with no edit to this file.
* **Examples.** A field may **declare** its own realistic value with
  `apps.core.schemas.example(...)`, and that declaration wins. Everything that
  did not declare one is synthesised from the schema's own JSON Schema — types,
  defaults, enums and formats — so a new field is never undocumented, only
  shape-grade. Synthesis is the floor and declaration is the ceiling: the
  synthesiser can tell you a field is a string and cannot tell you that a
  `channel` is `"email"`.

* **Tags.** A tag's human name and its description both come from the owning
  app's `TAGS` declaration, which maps the tag's wire name to a `Tag(display,
  description)`. The wire name is what routes and URLs carry and never changes;
  `display` is what a reader sees in the navigation, and it reaches the document
  as `x-displayName` — the extension every OpenAPI reader that renders a
  navigation understands.

What this module does NOT decide: which status code a refusal is. That is
`config/api.py`'s and only `config/api.py`'s (house rule 14), which is why the
mapping arrives here as an argument.

**And, at the bottom, the two things that read all four back: the renderers.**
`Scalar` is the `DocsBase` the API is mounted with, in place of ninja's default
Swagger UI; `llms_txt` is the same contract as flat text at `/llms.txt`, for the
reader that cannot run three megabytes of JavaScript and cannot afford 363 KB of
`$ref` graph either. Both belong beside the derivations rather than in
`config/api.py`, because they are the other half of the same ruling — a document
assembled this carefully deserves readers that show the prose, the refusals and
the examples instead of collapsing them — and because a mount should be one
argument, not a page. **The document itself is untouched by either**:
`openapi.json` is renderer-agnostic and stays byte-for-byte what it was, and
`/llms.txt` is derived on request rather than checked in, so neither rendering
can become a second copy of the contract that disagrees with it.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable, Iterable, Mapping, MutableMapping, Sequence
from typing import Any, NamedTuple, TypeVar

from django.http import HttpRequest, HttpResponse
from django.templatetags.static import static
from django.urls import reverse
from django.utils.html import format_html
from ninja import NinjaAPI
from ninja.openapi.docs import DocsBase

from apps.core.exceptions import REFUSALS
from apps.core.idempotency import HEADER as IDEMPOTENCY_HEADER
from apps.core.idempotency import REPLAYED_HEADER
from apps.core.middleware import CORRELATION_ID_HEADER, REQUEST_ID_HEADER

# `MCP_PATH` is NOT imported here, and the reason is a hard import cycle rather
# than taste: `apps/core/mcp.py` imports `contract_of` from this module at
# module scope (house rule 41 — the machine door renders the REST route's own
# docstring), so a module-scope import back the other way cannot be satisfied in
# EITHER order. Whichever of the two modules Python reaches first is the one
# left half-initialised when the other asks it for a name. It is read at
# function scope instead — `_mcp_path()` and inside `llms_text()` — where both
# modules are long since loaded.

#: The line that separates what a caller is owed from what a maintainer is told.
#: Three hyphens on their own line — a Markdown horizontal rule, so a docstring
#: that is never split still renders correctly wherever it is read.
CONTRACT_DIVIDER = "---"

#: The attribute `@refuses` leaves on a view. Read by `declared_refusals` and by
#: house rule 41's check; never read by anything that serves a request.
REFUSALS_ATTR = "_djb_refusal_codes"

#: Bound to a callable so `@refuses(...)` hands back the view it was given, with
#: its signature intact — an untyped decorator over a route is a route mypy
#: stops checking.
ViewT = TypeVar("ViewT", bound=Callable[..., Any])


class Tag(NamedTuple):
    """One group of routes: the name a person reads, and what the group is for.

        TAGS = {"tokens": Tag("API tokens", "Bearer tokens for programs ...")}

    **The key is the wire name and it is not a display name.** It is what a
    `Router(tags=[...])` carries, what appears in `openapi.json`, and what a
    generated client turns into a namespace — so it stays lowercase, stable and
    boring. `display` is the label a reader meets in the navigation, and it may
    say "Accounts & tokens" because nothing depends on it but eyes. Keeping them
    apart is what lets the platform give ten groups human names without
    renaming a single route.

    A plain string is still accepted where a `Tag` goes — it is read as the
    description with no display name — and house rule 41 then says so, because
    the point is to notice the missing name rather than to break the import.

    **`plane` is where a section sits in the overview's two-planes guide**, and
    it is declared HERE rather than written into that guide's prose (the
    partition's disposition D2, `docs/product/partition-closure.md` §5). The
    prose version put a per-member fact about a discovered population in a
    central in-closure file, so a product family could join no plane without
    editing a platform file, which a census catches by going red. Declared beside
    the family, the guide renders itself and the census test holds **by
    construction** for a product that declares, and goes **red by name** for one
    that does not, cleared in the product's own `api.py`. It is the same
    property the whole platform already claims — *an app that grows a tagged
    router grows the vocabulary with no file outside that app edited* — extended
    to the documentation of that vocabulary.

    `plane_note` is the one sentence the overview prints beside the key. It sits
    with the plane it explains for the same reason: "everyday rather than
    administrative, because…" is an argument about THIS family, and the file
    that owns the family is the file that should have to make it. Empty falls
    back to the description, so a family that declares a plane is never
    unprintable.
    """

    display: str
    description: str
    plane: str = ""
    plane_note: str = ""


#: The two planes, in the order the guide prints them. Two, and only two: the
#: split is "the product and the parts of the platform that are about you"
#: against "the tenant's own configuration", and a third would be a taxonomy
#: rather than a way of answering "will this refuse me".
EVERYDAY = "everyday"
ADMINISTRATIVE = "administrative"
PLANES: tuple[str, ...] = (EVERYDAY, ADMINISTRATIVE)


def plane_bullets(plane: str) -> str:
    """The overview's bullet list for one plane, rendered from the registry.

    Disposition D2 (`docs/product/partition-closure.md` §5). Every declared
    family whose `TAGS` entry names this plane, sorted by wire key so two
    deployments with the same apps produce the same guide, printed in the shape
    the census reads: ``* `key` — sentence``.

    **A family that declares no plane is printed in NEITHER list, deliberately.**
    That is the designed red: `test_the_authentication_guide_splits_every_family
    _into_exactly_one_plane` then fails naming the family, and a product clears
    it in its own `api.py` — an out-of-closure edit, which is the whole point of
    the move. Silently filing an undeclared family under one plane would be a
    guess about a trust boundary, made by a renderer.

    The walk is `scopes._tag_declarations()` — the same one the vocabulary is
    derived from — rather than a second walk of this module's own, so the guide
    and the scope census cannot come to disagree about which families exist, and
    so the partition's AST seam census still sees exactly one seam here.
    """
    from apps.core.api.scopes import _tag_declarations

    lines: list[str] = []
    for name, declared in sorted(_tag_declarations().items()):
        if not isinstance(declared, Tag) or declared.plane != plane:
            continue
        sentence = (declared.plane_note or declared.description).strip()
        lines.append(f"* `{name}` — {sentence}")
    return "\n".join(lines)


def tag_entry(name: str, declared: Tag | str) -> dict[str, str]:
    """One entry of the document's `tags` section, from what an app declared."""
    if isinstance(declared, Tag):
        entry = {"name": name, "description": declared.description}
        if declared.display:
            # The extension every OpenAPI reader that renders a navigation
            # agrees on. Absent, a reader falls back to the wire name, which is
            # the pre-2026-08-24 behaviour and exactly what rule 41 catches.
            entry["x-displayName"] = declared.display
        return entry
    return {"name": name, "description": str(declared)}


# --- the prose halves ---------------------------------------------------------


def _dedent(text: str) -> str:
    """A docstring's body, with the indentation the source file put on it gone.

    `inspect.cleandoc` would do this, but only from a live object; the house
    rule's check reads the same docstrings out of the AST, where there is no
    object to hand it. One implementation, both readers.
    """
    lines = text.expandtabs().splitlines()
    if not lines:
        return ""
    first, rest = lines[0].strip(), lines[1:]
    indents = [len(line) - len(line.lstrip()) for line in rest if line.strip()]
    margin = min(indents) if indents else 0
    body = [line[margin:].rstrip() for line in rest]
    out = [first, *body]
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)


def contract_of(obj: Any) -> str:
    """The half of a docstring a caller is owed. `""` when there is no docstring.

    Takes the object rather than the string so that `mcp.py` can write
    `description=contract_of(retrieve_widget)` and be reading the very function
    the REST door documents — the drift house rule 41 refuses is not available
    to make.
    """
    return contract_half(getattr(obj, "__doc__", None))


def contract_half(doc: str | None) -> str:
    """Everything above the `---` line, dedented. The whole of it when there is none."""
    if not doc or not doc.strip():
        return ""
    text = _dedent(doc)
    for index, line in enumerate(text.splitlines()):
        if line.strip() == CONTRACT_DIVIDER:
            return "\n".join(text.splitlines()[:index]).rstrip()
    return text


def workshop_half(doc: str | None) -> str:
    """Everything below the `---` line. `""` when the docstring is all contract."""
    if not doc or not doc.strip():
        return ""
    lines = _dedent(doc).splitlines()
    for index, line in enumerate(lines):
        if line.strip() == CONTRACT_DIVIDER:
            return "\n".join(lines[index + 1 :]).strip()
    return ""


#: The hard cap on a title, in characters. Sixty, and the number is a judgement
#: rather than a discovery: a navigation sidebar is a narrow column, the longest
#: title this tree needs is in the high thirties, and every SENTENCE that used to
#: stand in for a title was longer than sixty. So the cap
#: admits every real title with room to spare and refuses the failure mode it
#: exists for — a sentence in the sidebar. It is stated here, in `rules.yaml`
#: under rule 41, and in ADR api-1, and those three agree by review.
TITLE_MAX_LENGTH = 60

#: What may not appear in a title. Markdown is the owner's actual complaint —
#: the sidebar showed literal `**` — and the rest of this class travels with it:
#: a backtick, a bracketed link, a heading marker, a raw angle bracket. A
#: navigation label is rendered as TEXT by most readers, so any of these reaches
#: a reader as itself.
_TITLE_MARKDOWN = re.compile(r"[*_`\[\]#<>]")

#: The four mechanical tells of maintainer archaeology in a contract half.
#: Each is a thing no caller can act on and
#: every one of them is a *shape*, which is what makes this gateable where the
#: rest of the plain-language bar is review's. `(pattern, what it is)`.
_MECHANICAL_TELLS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bN\d{1,4}\b"), "a queue-row reference"),
    (re.compile(r"(?<![\w.])_[A-Za-z]\w*"), "an underscore-prefixed identifier"),
    (re.compile(r"@service\b"), "`@service`"),
    (re.compile(r"\bmanage\.py"), "`manage.py`"),
)


def title_of(contract: str) -> str:
    """The first line of the contract half — the NAME a navigation shows.

    Deliberately not a second field somebody writes: a title that can be edited
    without the docstring changing is a title that will be. A short noun or verb
    phrase — "Mint an API token", "Erase your own account" — with the sentence
    that explains it in the paragraph below, where `description_of` finds it.
    """
    for line in contract.splitlines():
        if line.strip():
            return line.strip()
    return ""


def description_of(contract: str) -> str:
    """The contract half BELOW its title line — the prose a reader is shown.

    The title is not repeated here: a reader who has clicked the title in a
    sidebar does not need to be told it again at the top of the page, and a
    document that prints it twice is a document somebody will "fix" by editing
    one of the two copies.
    """
    lines = contract.splitlines()
    for index, line in enumerate(lines):
        if line.strip():
            return "\n".join(lines[index + 1 :]).strip()
    return ""


def title_faults(title: str) -> list[str]:
    """Everything wrong with one title, in plain words. `[]` when it is fine.

    Returns the complaints rather than a boolean so the finding can say which
    of them it is: "carries Markdown" and "is 94 characters" are different
    mistakes with different fixes, and a rule that said only "bad title" would
    send the reader back to guess.
    """
    faults: list[str] = []
    if not title:
        return ["is empty"]
    found = sorted(set(_TITLE_MARKDOWN.findall(title)))
    if found:
        faults.append(
            "carries Markdown (" + ", ".join(repr(ch) for ch in found) + ") — a navigation "
            "label is shown as text, so the reader sees those characters"
        )
    if title.endswith("."):
        faults.append("ends in a full stop — it is a name, not a sentence")
    if len(title) > TITLE_MAX_LENGTH:
        faults.append(f"is {len(title)} characters, past the cap of {TITLE_MAX_LENGTH}")
    return faults


def mechanical_tells(contract: str) -> list[str]:
    """The maintainer archaeology in a contract half, named. `[]` when clean.

    The plain-language bar (design-agreements.md, 2026-08-23) is mostly taste
    and taste has no canary — but four of its symptoms are shapes, and a shape
    is checkable. What is caught here is never the whole of the bar; it is the
    part that can be caught, which is why rule 41 declares the rest as a blind
    spot instead of pretending.
    """
    found: list[str] = []
    for pattern, what in _MECHANICAL_TELLS:
        match = pattern.search(contract)
        if match is not None:
            found.append(f"{what} ({match.group(0)!r})")
    return found


# --- the token ceiling, said where a caller reads (ADR ident-7) ----------------


#: How the scope requirement is spelled in the published document, once. It is
#: a format string rather than prose at eighty-six call sites for the reason
#: everything else in this module is derived: a sentence written per route is a
#: sentence that will be right for most of them.
REQUIRED_SCOPE_SENTENCE = (
    "**Token scope:** a bearer token must carry `{scope}` to make this call. "
    "A token minted with no limit carries every scope, and signing in with a "
    "browser session is not affected. `POST /tokens/` is where a token with "
    "this scope is minted."
)

#: Added to the line above when the requirement is a READ, because a caller
#: holding the write half of the same section satisfies it and would otherwise
#: go and mint a second token to do something the first one already allows.
#: Appended from the derived scope rather than written per route, so the two
#: halves of the sentence cannot come to disagree.
WRITE_INCLUDES_READ_SENTENCE = (
    " A token carrying `{family}:write` satisfies this too: within one section, "
    "the write scope includes the read."
)

#: The variant for an operation **no bearer token reaches at all**. The
#: sentence above is written for a caller who can act on it —
#: mint a token carrying the scope, or widen the one they have — and on a
#: session-only operation every one of those instructions is a loop. It was
#: measured on the mint route itself, which is the worst possible place for it:
#: `POST /tokens/` published "a bearer token must carry `tokens:write`… `POST
#: /tokens/` is where a token with this scope is minted", sending a refused
#: caller to the exact route that had just refused them, to do the exact thing
#: no token may do.
#:
#: So the fact this states is the one that is true: there is no scope, and no
#: token to go and get. It names the refusal code so an agent can join the
#: sentence to the 403 it will actually receive.
SESSION_ONLY_SCOPE_SENTENCE = (
    "**Token scope:** none — **no bearer token reaches this call**, whatever "
    "scopes it carries, so there is no token to mint and none to widen. A token "
    "that tries is refused `session_required`. Sign in with a browser session "
    "and make the call from there."
)


def reachable_by_token(auth_callbacks: Sequence[Any]) -> bool:
    """Whether a bearer token can reach this operation at all.

    **Read off what each authenticator PUBLISHES about itself**, not off its
    class name and not off a list of routes. Every `ninja.security.AuthBase`
    builds an `openapi_security_schema` in its constructor out of its own
    `openapi_*` attributes, and that same object is what ninja writes into the
    document's `securitySchemes` — so an operation's footer and its `security`
    block are derived from one fact and cannot come to disagree. A route that
    narrows its `auth=` to a session-only pair carries no bearer scheme, and
    that is the whole test.

    An operation with **no authenticators at all** answers `True`: nothing about
    it is narrowed, and a caller holding a token is as welcome as anyone else.
    Answering `False` there would print "no bearer token reaches this" on the
    one kind of route that refuses nobody — the signature-verified inbound
    webhook receiver — which is the opposite of true.
    """
    if not auth_callbacks:
        return True
    return any(
        (getattr(callback, "openapi_security_schema", None) or {}).get("scheme") == "bearer"
        for callback in auth_callbacks
    )


def derived_scope(*, tags: Sequence[str], methods: Sequence[str]) -> str | None:
    """The scope this operation needs, or `None` when nothing can say.

    **The rendering path's derivation, and the only one that is allowed to
    shrug.** `scopes.required_scope` raises on an operation it cannot place —
    correctly, because an enforcement seam that guessed would put a capability
    outside every ceiling in the product. But a *document* is also the thing
    that reports the problem: house rule 41's one-tag census reads the rendered
    document, and a document that could not be built reports nothing at all.

    That is not hypothetical. Rule 41's own canary plants a two-tag route on
    purpose, and while this call raised, the whole document died at import — so
    the checks that read the mounted API died with it and two dozen unrelated
    canaries went silent at once. A diagnostic that cannot survive the illness
    it diagnoses is not a diagnostic.

    So: raise where a call is being decided, answer `None` where prose is being
    written. The route loses its scope sentence, the census keeps its subject,
    and the door refuses every ceilinged token for the same operation (see
    `config/api.py`) rather than letting one through unchecked.
    """
    from apps.core.api.scopes import UnderivableScope, required_scope

    try:
        return required_scope(tags=tags, methods=methods)
    except UnderivableScope:
        return None


def with_required_scope(
    description: str, scope: str | None, *, reachable_by_token: bool = True
) -> str:
    """A route's prose plus the one line saying which scope reaches it.

    Applied to the PUBLISHED description by `config/api.py` and never written
    into a docstring — see the note at that call site. Keeping the two apart is
    what lets house rule 41 go on insisting that the prose a maintainer writes
    and the prose a caller reads are the same text, while the caller also gets
    the fact only the mount knows.

    `scope is None` — nothing could be derived — prints no sentence at all. An
    invented one would be the per-route annotation this whole design exists to
    avoid, and a sentence saying "unknown" is a contract nobody can act on.

    `reachable_by_token=False` prints the session-only variant **instead**, and
    it prints it whether or not a scope derived: "no token reaches this" is not
    a fact about the tag and the method, so it does not need one to be true. The
    parameter is keyword-only with a default, so the two-argument call this
    function has always had keeps its old meaning; the mount is what knows the
    answer, and the mount is what passes it.
    """
    if not reachable_by_token:
        line = SESSION_ONLY_SCOPE_SENTENCE
    elif scope is None:
        return description
    else:
        line = REQUIRED_SCOPE_SENTENCE.format(scope=scope)
        family, _, verb = scope.rpartition(":")
        if verb == "read" and family:
            line += WRITE_INCLUDES_READ_SENTENCE.format(family=family)
    return f"{description.rstrip()}\n\n{line}" if description.strip() else line


# --- refusals -----------------------------------------------------------------


def refuses(*codes: str) -> Callable[[ViewT], ViewT]:
    """Declare what this route's own logic can refuse with.

        @router.post("/", response={201: WidgetOut}, url_name="widget-create")
        @refuses("invalid", "forbidden", "conflict")
        def create_widget_route(...): ...

    **Replaces the SHAPE derivation, and is additive over the DOOR-LEVEL
    codes** (`DOOR_LEVEL_REFUSALS` below). The reason to write one is that the
    derived set — generous by construction, reading the door's shape and not the
    service's raise sites — is wrong about what this route DOES. It is never
    wrong about what the door does to every request on the way in, and a route
    author cannot decline those by omitting them.

    **The defect this shape had.** All eight routes carrying
    `@refuses(...)` answer `403 addressing_header_not_honoured` — the middleware
    refuses a header it cannot honour before the view runs — and every one of
    them published a contract that did not mention it, because declaring
    replaced the derivation wholesale. Rule 41's census could not see it: it
    reads the published document, and the document was internally consistent and
    wrong. A caller reading eight contracts had no reason to handle a refusal
    all eight can make.

    Every code is checked against the refusal registry by house rule 41; an
    unregistered one is a violation, not a new code.
    """

    def decorate(view: ViewT) -> ViewT:
        setattr(view, REFUSALS_ATTR, tuple(codes))
        return view

    return decorate


#: The refusals a route earns from the DOOR, not from its own logic: they are
#: produced ABOVE the view — by the addressing middleware, by the token
#: ceiling, by the throttle — so no route can decline to answer with them and no
#: `@refuses(...)` can truthfully omit one.
#:
#: This is deliberately NOT "everything the derivation would have said". A
#: derived `not_found` or `conflict` is a claim about what the route's own
#: services do, and that claim is exactly what a route writes `@refuses(...)` to
#: correct. These three are claims about the mount, and the mount is the same
#: for every operation it covers.
#:
#: `rate_limited` is unconditional because the throttle is;
#: `addressing_header_not_honoured` is earned by AUTHENTICATION, which is the
#: same fact `config/api.py` publishes the `X-Tenant` and `X-Org` parameters
#: off — so the refusal those headers can produce is derived off the fact that
#: produces the headers, and the two cannot drift apart.
#:
#: **`insufficient_scope` is deliberately NOT here, and the reason is the whole
#: distinction this set turns on.** It is earned by being reachable with a
#: CEILINGED TOKEN, which is not the same fact as being authenticated: a
#: session-only route authenticates and has no ceiling to fall short of.
#: `POST /api/v1/tokens/` is exactly that route, and it writes `@refuses(...)`
#: to SUPPRESS the code — publishing it taught a caller to handle a refusal
#: this operation cannot make, and to handle it by minting a wider token at the
#: very endpoint that refused them, pinned by
#: `apps/accounts/tests/test_api.py::test_the_published_mint_does_not_offer_a_
#: scope_that_cannot_reach_it`).
#:
#: That pin is what caught the first version of this set, which included it and
#: re-added the code the route had removed on purpose. A door-level code has to
#: be one no route can decline; `insufficient_scope` is one some routes can
#: never make, so it stays where a route can correct it.
DOOR_LEVEL_REFUSALS: frozenset[str] = frozenset(
    {"addressing_header_not_honoured", "database_unavailable", "rate_limited"}
)

#: The subset of the above that an UNAUTHENTICATED operation also earns.
DOOR_LEVEL_ALWAYS: frozenset[str] = frozenset({"database_unavailable", "rate_limited"})


def door_level_refusals(*, authenticated: bool) -> frozenset[str]:
    """The door's own refusals for an operation of this kind."""
    return DOOR_LEVEL_REFUSALS if authenticated else DOOR_LEVEL_ALWAYS


def with_door_level(codes: Sequence[str], *, authenticated: bool) -> tuple[str, ...]:
    """A declared set, plus the door-level codes it cannot decline.

    Order is stable and declared-first: what the route says about itself reads
    ahead of what the mount adds, and a code the route already declared is not
    repeated. Filtered against the live registry for `derived_refusals`' reason
    — `insufficient_scope` is registered by a sibling module and a membership
    test on a frozen copy would depend on import order.
    """
    earned = [code for code in sorted(door_level_refusals(authenticated=authenticated))]
    return tuple(dict.fromkeys(code for code in (*codes, *earned) if code in REFUSALS))


def declared_refusals(view: Any) -> tuple[str, ...] | None:
    """What `@refuses` said, or `None` when the route did not say."""
    declared = getattr(view, REFUSALS_ATTR, None)
    return tuple(declared) if declared is not None else None


#: Read once at import so the derivation cannot name a code the registry does not
#: hold. The membership is the registry's; the *shape* rules are below.
def derived_refusals(
    *,
    methods: Iterable[str],
    has_path_params: bool,
    has_body: bool,
    authenticated: bool,
    idempotent_methods: Iterable[str],
    paginated: bool = False,
) -> tuple[str, ...]:
    """What a route of this SHAPE can answer with. A superset, and it says so.

    Derived from the door and not from the services behind it, because the
    services behind it are an open set and the door is a closed one. A route
    that wants the narrow truth writes `@refuses(...)`; the blind spot is
    declared in `quality/rules.yaml` under rule 41's `does_not_cover`.

    `paginated` is read off `@paginate` at the mount, so the population is the
    house rule 3 census and never a list of route names: a list route added in
    any app carries the cursor's two refusals with it, and one removed stops
    documenting them, with nothing here to edit either way.
    """
    verbs = {m.upper() for m in methods}
    codes: list[str] = []
    if has_body:
        # The door's own refusal, decided while ninja parses the request and
        # before any route runs: a field this operation does not have, a
        # required one missing, a value of the wrong type. Request bodies are
        # strict here, so a misspelled field name lands HERE rather than
        # arriving as a healthy 201 for a request that did nothing.
        codes.append("invalid_body")
    if has_body or not has_path_params:
        # And the service's own, which is a different fact with a different fix:
        # the shape was right and a rule about the data did not hold. A route
        # that narrows can answer it off a query or filter parameter too, which
        # is why this is not simply "every route with a body".
        codes.append("invalid")
    if authenticated:
        codes.append("forbidden")
        # A credential that authenticated may still be a token whose ceiling
        # does not reach this operation (ADR ident-7). Derived off the same
        # `authenticated` fact as `forbidden` rather than off a list of routes:
        # every door that takes a bearer token can answer this, and a route
        # added tomorrow documents it without anybody remembering to.
        codes.append("insufficient_scope")
        # And the addressing headers it may have sent (ADR core-21). Every
        # authenticated operation reads `X-Tenant` and `X-Org` — they are
        # published as parameters on exactly this `authenticated` fact, a few
        # lines down in `config/api.py` — so the refusal they can produce is
        # derived off the same fact rather than off a list of route names.
        codes.append("addressing_header_not_honoured")
    if has_path_params or has_body:
        # A path parameter names a row, and so does an id inside a body — and
        # naming a row this actor could not have reached is `not_found` here,
        # never `forbidden`. A collection route that names nothing cannot 404,
        # which is why this is not simply "every GET": a list that documented a
        # 404 would teach a client to handle one that never comes. A collection
        # route that CAN refuse that way says so with `@refuses(...)`.
        codes.append("not_found")
    if paginated:
        # A `?cursor=` a client built, edited, or replayed against a different
        # `?ordering=` (ADR core-18). And `not_found` on a COLLECTION route,
        # which is the one thing that changed about the sentence above: a cursor
        # names a walk, a walk belongs to a tenant, and a cursor from another
        # tenant answers the way every other row that tenant cannot reach does.
        codes.extend(("invalid_cursor", "not_found"))
    if verbs & {"POST", "PUT", "PATCH", "DELETE"}:
        codes.append("conflict")
    if verbs & {m.upper() for m in idempotent_methods}:
        codes.extend(("idempotency_key_reuse", "in_progress"))
    codes.append("rate_limited")
    codes.append("database_unavailable")
    # `REFUSALS` is read HERE and not snapshotted at import: `insufficient_scope`
    # is registered by `apps/core/api/scopes.py`, a sibling of this module, and a
    # frozen copy taken while this file was importing would or would not hold it
    # depending on which of the two Python reached first. A membership test on
    # the live registry cannot depend on import order.
    return tuple(dict.fromkeys(code for code in codes if code in REFUSALS))


def refusal_response(codes: Sequence[str]) -> dict[str, Any]:
    """One status's response object, written out of the registry and nowhere else.

    The description is each code's own `fact` — what is TRUE, said to whoever is
    refused — followed by the remedies the registry composes for it, which are
    the same remedies the wire body carries. Prose written here instead would be
    the fourth copy of a sentence with one home.
    """
    parts: list[str] = []
    for code in codes:
        refusal = REFUSALS.get(code)
        if refusal is None:  # pragma: no cover - rule 41 refuses this before it ships
            continue
        lines = [f"**`{code}`** — {refusal.fact}"]
        lines += [f"- {r.label} (`{r.destination}`)" for r in refusal.remedies]
        parts.append("\n".join(lines))
    return {
        # Machine-readable beside the prose, and load-bearing: house rule 41's
        # check reads this to assert every enumerated code is one the registry
        # holds, and a generated client has something to switch on that is not a
        # sentence. `x-` because OpenAPI says extensions are spelled that way.
        "x-refusal-codes": list(codes),
        "description": "\n\n".join(parts) or "A refusal.",
        "content": {
            "application/json": {
                "schema": {"$ref": "#/components/schemas/Refusal"},
                "example": _refusal_example(codes[0] if codes else "error"),
            }
        },
    }


def _refusal_example(code: str) -> dict[str, Any]:
    refusal = REFUSALS.get(code)
    body: dict[str, Any] = {"detail": "The request could not be completed.", "code": code}
    if refusal is not None:
        body["remedies"] = [
            {"label": r.label, "destination": r.destination} for r in refusal.remedies
        ]
    return body


def refusal_component() -> dict[str, Any]:
    """The wire shape of every refusal, with `code` enumerated off the registry.

    `core.exceptions.wire_refusal` is the only builder of this body and
    `architecture.md` is its authority; this is that body said in JSON Schema so
    a generated client has a type for it. The enum is read from the registry, so
    a product that registers a code gets it documented without touching this.
    """
    return {
        "Refusal": {
            "type": "object",
            "title": "Refusal",
            "description": (
                "Every refusal this API makes, in one shape. `code` is what a client "
                "branches on; `detail` is the human half; `errors` names fields when the "
                "refusal was about fields; `remedies` is what the caller can DO about it, "
                "composed once so a screen and an assistant offer the same way out."
            ),
            "required": ["detail", "code"],
            "properties": {
                "detail": {"type": "string", "title": "Detail"},
                "code": {"type": "string", "title": "Code", "enum": sorted(REFUSALS)},
                "errors": {
                    "type": "object",
                    "title": "Errors",
                    "additionalProperties": {"type": "array", "items": {"type": "string"}},
                },
                "remedies": {
                    "type": "array",
                    "title": "Remedies",
                    "items": {"$ref": "#/components/schemas/RefusalRemedy"},
                },
            },
            "example": _refusal_example("not_found"),
        },
        "RefusalRemedy": {
            "type": "object",
            "title": "RefusalRemedy",
            "description": (
                "One thing the caller can do about a refusal. `destination` is an opaque "
                "`<kind>:<name>` token — `header:X-Org`, `docs:openapi`, "
                "`introspect:refusals` — that says where to look without promising a URL."
            ),
            "required": ["label", "destination"],
            "properties": {
                "label": {"type": "string", "title": "Label"},
                "destination": {"type": "string", "title": "Destination"},
            },
            "example": {"label": "Name the organization to act as", "destination": "header:X-Org"},
        },
    }


# --- request headers ----------------------------------------------------------


def header_parameter(*, name: str, description: str) -> dict[str, Any]:
    """One request header, documented where a client is looking for it."""
    return {
        "in": "header",
        "name": name,
        "required": False,
        "schema": {"type": "string", "title": name},
        "description": description,
    }


# --- response headers ---------------------------------------------------------
#
# THE WRITE SIDE OF RULE 40, AND WHY IT IS A DERIVATION AND NOT A LIST.
#
# The document used to say nothing at all about the headers this platform puts
# ON a response. Every answer carries `X-Request-Id` and `X-Correlation-Id`, a
# replayed write carries `Idempotent-Replayed`, a 429 carries `Retry-After` —
# four headers a client receives and could not learn about from the contract,
# which is the same defect class as an undocumented refusal: the caller finds
# out by reading somebody's network tab.
#
# THE POPULATION IS THE DECLARED WRITER CONSTANTS, one writer each, exactly as
# rule 40 governs the read side — and it is DERIVED, never typed. A module that
# stamps a response header declares `RESPONSE_HEADERS`, a tuple of
# `ResponseHeader`, beside the constant that names it; `declared_response_
# headers()` walks the loaded `apps.*` modules and collects them. So a writer
# added in another module joins the document with NO EDIT HERE — which is the
# whole point, and is why this is a walk and not the hand list that would go
# stale the first time somebody stamped a fifth header.
#
# `covers` IS ASKED OF THE RENDERED DOCUMENT — the operation object, the status
# string, and that status's response object — and never of ninja's internals.
# Two reasons. It keeps this module out of deciding which status a refusal is
# (house rule 14: that is `config/api.py`'s, and by the time a predicate runs,
# its decision has already landed in the document as `x-refusal-codes`), and it
# lets a writer elsewhere declare its own coverage while importing nothing from
# the document builder.
#
# THE DECLARED BLIND SPOT: a module that stamps a header and never declares one
# of these is invisible here, exactly as rule 40 declares for a header read
# through a literal. The belt is the CORS census in `apps/core/tests` — a
# stamped header that is not exposed is a header a browser cannot read, so the
# two lists have to agree, and the test is what makes the agreement a census
# rather than a coincidence.

#: `Retry-After`, written by the one mapper (`config/api.py::on_domain_error`)
#: on a `RateLimited`. Rule 40's scope records that no `*_HEADER` constant
#: declares it on the READ side and that none should — it is RFC 9110
#: vocabulary, spelled the same by every server on the internet, with no
#: alternative spelling to drift to. The WRITE side asks a different question:
#: the documentation has to name the header it documents, and a name typed in
#: two places is precisely the defect rule 40 exists to close. One declaration,
#: here, and the mapper stamps through it.
RETRY_AFTER_HEADER = "Retry-After"


class ResponseHeader(NamedTuple):
    """One header the platform stamps on a response, documented where it lands.

    `name` is the writer's own constant — never a literal, so the document and
    the stamp cannot part company. `description` is what a client is owed about
    it. `covers` answers "does this header land on THIS response", and is
    handed the operation, the status as a string, and the response object.
    """

    name: str
    description: str
    covers: Callable[[Mapping[str, Any], str, Mapping[str, Any]], bool]


def on_every_response(
    operation: Mapping[str, Any], status: str, response: Mapping[str, Any]
) -> bool:
    """For a header a middleware stamps unconditionally, on the way out."""
    return True


def reads_header(operation: Mapping[str, Any], name: str) -> bool:
    """Whether this operation documents `name` as a request header it reads."""
    return any(
        isinstance(parameter, Mapping)
        and parameter.get("in") == "header"
        and parameter.get("name") == name
        for parameter in operation.get("parameters", ())
    )


def refuses_with(response: Mapping[str, Any], code: str) -> bool:
    """Whether this response is the one that answers `code`.

    Read off `x-refusal-codes`, which the refusal derivation already put there
    — so a predicate never has to know that `rate_limited` is a 429, and house
    rule 14's line stays where it is.
    """
    return code in (response.get("x-refusal-codes") or ())


def _on_a_replayable_answer(
    operation: Mapping[str, Any], status: str, response: Mapping[str, Any]
) -> bool:
    """Only where a write can be replayed: a success on an idempotent route."""
    return status.isdigit() and int(status) < 400 and reads_header(operation, IDEMPOTENCY_HEADER)


def _on_the_rate_limit_refusal(
    operation: Mapping[str, Any], status: str, response: Mapping[str, Any]
) -> bool:
    return refuses_with(response, "rate_limited")


#: This module's own declarations, for the three writers that predate the
#: convention: the context middleware's two ids, the idempotency middleware's
#: replay flag, and the mapper's `Retry-After`. Every `name` is the writer's
#: imported constant.
RESPONSE_HEADERS: tuple[ResponseHeader, ...] = (
    ResponseHeader(
        name=REQUEST_ID_HEADER,
        description=(
            "This one request's id — the value you sent, or one minted here if you sent "
            "none. Include this id when reporting a problem."
        ),
        covers=on_every_response,
    ),
    ResponseHeader(
        name=CORRELATION_ID_HEADER,
        description=(
            "The id that ties this request to the rest of the same piece of work. Send "
            "the same value on every call in a chain and one search finds all of them; "
            "send none and this request's own id is used."
        ),
        covers=on_every_response,
    ),
    ResponseHeader(
        name=REPLAYED_HEADER,
        description="`true` when this answer is a replay of an earlier identical request.",
        covers=_on_a_replayable_answer,
    ),
    ResponseHeader(
        name=RETRY_AFTER_HEADER,
        description=(
            "How many seconds to wait before trying again. Coming back sooner is "
            "refused the same way."
        ),
        covers=_on_the_rate_limit_refusal,
    ),
)


def declared_response_headers() -> tuple[ResponseHeader, ...]:
    """Every declared response-header writer, collected off the loaded modules.

    Sorted by name so the document is byte-stable between two processes that
    imported their modules in different orders. `sys.modules` is snapshotted
    into a sorted list first: reading an attribute can import, and a dictionary
    that changes size mid-walk raises.
    """
    found: dict[str, ResponseHeader] = {}
    for module_name in sorted(sys.modules):
        if module_name != "apps" and not module_name.startswith("apps."):
            continue
        module = sys.modules.get(module_name)
        declared = getattr(module, "RESPONSE_HEADERS", None) if module is not None else None
        if not isinstance(declared, tuple):
            continue
        for header in declared:
            if isinstance(header, ResponseHeader):
                found.setdefault(header.name, header)
    return tuple(found[name] for name in sorted(found))


def add_response_headers(schema: MutableMapping[str, Any]) -> None:
    """Document every stamped response header on the responses it lands on.

    Applied to the finished document rather than per bound operation, because
    the success responses are ninja's own and only exist by this point — and
    because a predicate that reads the document can be written by a module that
    knows nothing about how the document was built.
    """
    declared = declared_response_headers()
    if not declared:  # pragma: no cover - the census test refuses an empty population
        return
    for path_item in schema.get("paths", {}).values():
        if not isinstance(path_item, Mapping):
            continue
        for operation in path_item.values():
            if not isinstance(operation, Mapping):
                continue
            responses = operation.get("responses")
            if not isinstance(responses, MutableMapping):
                continue
            for status, response in responses.items():
                if not isinstance(response, MutableMapping):
                    continue
                for header in declared:
                    if header.covers(operation, str(status), response):
                        headers = response.setdefault("headers", {})
                        headers[header.name] = {
                            "description": header.description,
                            "schema": {"type": "string"},
                        }


# --- examples -----------------------------------------------------------------

#: Property names whose example is worth more than its type. Everything else is
#: answered from the JSON Schema alone; this table only makes the obvious ones
#: read like real data instead of like `"string"`.
_BY_NAME: dict[str, Any] = {
    "email": "person@example.com",
    "name": "Northern branch",
    "slug": "northern-branch",
    "notes": "Anything the product wants to remember.",
    "url": "https://example.com/hooks/inbound",
    "detail": "The request could not be completed.",
    "count": 137,
    "limit": 25,
    "has_more": True,
    "next_cursor": "eyJrIjpbIjIwMjYtMDgtMjNUMDk6MzA6MDBaIl0sInYiOjF9.p3Qb1w",
    "cursor": "eyJrIjpbIjIwMjYtMDgtMjNUMDk6MzA6MDBaIl0sInYiOjF9.p3Qb1w",
    "ordering": "-created_at",
    # The complementary half: everything above answers a field whose NAME says what
    # it holds; everything here answers one whose name says what KIND of thing
    # it holds — a status, a channel, a role — where the schema is a bare
    # string because the vocabulary is the product's rather than the platform's.
    # Without these the synthesiser fell through to echoing the field name, and
    # `"status": "status"` is not an example, it is the absence of one wearing
    # the shape of one.
    #
    # These are PLAUSIBLE, not authoritative: a product with different statuses
    # declares its own with `apps.core.schemas.example(...)`, which wins over
    # everything here. What they buy is that the document stops teaching a
    # reader that the field is called what it is called.
    "status": "active",
    "role": "admin",
    "channel": "email",
    "provider": "stripe",
    "template": "welcome",
    "category": "transactional",
    "protocol": "oidc",
    "issuer": "https://idp.example.com",
    "timezone": "Europe/London",
    "locale": "en-GB",
    "phone": "+15555550123",
    "subject": "Your receipt",
    "body": "Hello — here is the thing you asked for.",
    # Low-entropy on purpose: a realistic 32-hex opaque token is, to
    # `detect-secrets`, exactly a leaked one — the hazard
    # `apps.core.schemas.example` writes down, met here. Few distinct symbols,
    # not a repeated block of many.
    "state": "deadbeefdeadbeefdeadbeefdeadbeef",
    "type": "widget.onboard",
}

_SAMPLE_UUID = "0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f21"
_SAMPLE_AT = "2026-08-23T09:30:00Z"
_SAMPLE_ON = "2026-08-23"

_BY_FORMAT: dict[str, Any] = {
    "uuid": _SAMPLE_UUID,
    "uuid4": _SAMPLE_UUID,
    "date-time": _SAMPLE_AT,
    "date": _SAMPLE_ON,
    "email": "person@example.com",
    "uri": "https://example.com/hooks/inbound",
    "url": "https://example.com/hooks/inbound",
    "decimal": "12.50",
    # A concrete case: `QuietHoursIn.start` and `.end` are `time`
    # fields, and with no entry here the synthesiser echoed the field name — so
    # the published example for a `format: "time"` field was the string
    # `"start"`, which a caller who copied it got a 422 for. An example that its
    # own schema refuses is the worst kind of documentation defect: the client
    # has no reason to doubt it.
    "time": "09:00:00",
}

#: The suffixes below join the same job from the other end. `_timezone` is here
#: rather than in `_BY_NAME` because it reads as a qualifier — `quiet_hours_timezone`
#: is a timezone — and a name table that had to hold every prefix of every
#: qualified field would be a list nobody could finish.
_BY_SUFFIX_EXTRA: dict[str, str] = {
    "_timezone": "Europe/London",
    "_role": "admin",
    "_status": "active",
    "_channel": "email",
    "_uri": "https://example.com/callback",
    "_secret": "not-a-real-secret-value",  # pragma: allowlist secret
}


def _ref_name(node: Mapping[str, Any]) -> str | None:
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
        return ref.rsplit("/", 1)[-1]
    return None


def example_for(
    node: Mapping[str, Any],
    components: Mapping[str, Any],
    *,
    name: str = "",
    seen: frozenset[str] = frozenset(),
) -> Any:
    """A representative value for one JSON Schema node.

    Recursion is bounded by the `$ref` names already on the stack rather than by
    a depth counter: a self-referential schema (a tree node, an organization
    with a parent) is answered `null` at its second visit instead of looping,
    and nothing else is truncated.
    """
    if "example" in node:
        return node["example"]
    referenced = _ref_name(node)
    if referenced is not None:
        if referenced in seen:
            return None
        target = components.get(referenced)
        if not isinstance(target, Mapping):
            return None
        return example_for(target, components, name=name, seen=seen | {referenced})
    for key in ("anyOf", "oneOf", "allOf"):
        branches = node.get(key)
        if isinstance(branches, list) and branches:
            chosen = next(
                (b for b in branches if isinstance(b, Mapping) and b.get("type") != "null"),
                branches[0],
            )
            if isinstance(chosen, Mapping):
                return example_for(chosen, components, name=name, seen=seen)
    if "const" in node:
        return node["const"]
    enum = node.get("enum")
    if isinstance(enum, list) and enum:
        return enum[0]
    if "default" in node and node["default"] is not None:
        return node["default"]

    kind = node.get("type")
    if kind == "object" or "properties" in node:
        properties = node.get("properties")
        if not isinstance(properties, Mapping):
            return {}
        return {
            key: example_for(value, components, name=key, seen=seen)
            for key, value in properties.items()
            if isinstance(value, Mapping)
        }
    if kind == "array":
        items = node.get("items")
        if isinstance(items, Mapping):
            return [example_for(items, components, name=name, seen=seen)]
        return []
    if kind == "null":
        return None
    if kind == "boolean":
        return True
    if kind == "integer":
        value = _BY_NAME.get(name)
        return value if isinstance(value, int) else 1
    if kind == "number":
        return 1
    # Strings, and anything the schema declined to type.
    fmt = str(node.get("format") or "")
    if fmt in _BY_FORMAT:
        return _BY_FORMAT[fmt]
    if name in _BY_NAME:
        return _BY_NAME[name]
    for suffix, sample in (
        ("_id", _SAMPLE_UUID),
        ("_at", _SAMPLE_AT),
        ("_on", _SAMPLE_ON),
        ("_email", _BY_NAME["email"]),
        ("_slug", _BY_NAME["slug"]),
        ("_url", _BY_NAME["url"]),
        ("_name", _BY_NAME["name"]),
        *_BY_SUFFIX_EXTRA.items(),
    ):
        if name == suffix.lstrip("_") or name.endswith(suffix):
            return sample
    title = str(node.get("title") or name or "value")
    return re.sub(r"[^A-Za-z0-9 ]", " ", title).strip().lower() or "value"


def add_examples(components: Mapping[str, Any]) -> None:
    """Give every component schema an example. Mutates in place; idempotent."""
    for name, node in components.items():
        if not isinstance(node, dict) or "example" in node:
            continue
        node["example"] = example_for(node, components, name=name, seen=frozenset({name}))


def example_census(components: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """`(declared, undeclared)` — every scalar field, by `Schema.field`.

    Safe to run on the finished document: `add_examples` writes an example onto
    each COMPONENT and never onto a property, so an `example` key on a property
    node got there one way — a field declared it. That is the whole reason the
    two passes are separable, and it is what makes this a census of declarations
    rather than a census of the synthesiser's coverage.

    A *scalar* field is one whose example is a value rather than a shape: a
    property that is a `$ref` to another component is that component's business
    and is counted there, once, instead of once per place it is embedded. The
    ratchet under house rule 41 is over `undeclared`, and it is a ratchet rather
    than a ceiling of zero because 2026-08-24 declared the persona arc's schemas
    and not all ninety-five: what must never happen again is a NEW field arriving
    with `"string"` in the document.
    """
    declared: list[str] = []
    undeclared: list[str] = []
    for name, node in sorted(components.items()):
        if not isinstance(node, Mapping):
            continue
        properties = node.get("properties")
        if not isinstance(properties, Mapping):
            continue
        for field, spec in properties.items():
            if not isinstance(spec, Mapping) or _is_shape(spec):
                continue
            (declared if "example" in spec else undeclared).append(f"{name}.{field}")
    return declared, undeclared


def _is_shape(spec: Mapping[str, Any]) -> bool:
    """Whether a property is another component rather than a value of its own.

    Three roads to the same answer, and the third is the one that was missing.
    A `$ref` is plainly another component; a `oneOf`/`anyOf`/`allOf` branch that
    holds one is the nullable spelling of the same thing; and **an ARRAY whose
    `items` is a `$ref` is a collection of another component**, which is that
    component's business in exactly the same way and for exactly the same reason
    — the example belongs beside the fields it describes, once, rather than once
    per place it is embedded.

    Leaving the array road out put every ninja-synthesised `Paged<X>.items` into
    the undeclared backlog: 21 fields that no author can ever declare, because
    `@paginate` builds those classes at mount time and there is no source line to
    hang an example on. A ratchet whose backlog contains entries nobody can
    remove is a ratchet that has stopped being about anything, and it was
    inflating the number the whole census is judged by.
    """
    if _ref_name(spec) is not None:
        return True
    if spec.get("type") == "array":
        items = spec.get("items")
        if isinstance(items, Mapping) and _is_shape(items):
            return True
    for key in ("anyOf", "oneOf", "allOf"):
        branches = spec.get(key)
        if isinstance(branches, list) and any(
            isinstance(b, Mapping) and _ref_name(b) is not None for b in branches
        ):
            return True
    return False


# --- the overview -------------------------------------------------------------
#
# THE READER IS A STRANGER WITH AN API KEY (N138a). This string is the first
# thing anybody meets in `/api/v1/docs`, and it is held to the same bar as a
# route's contract half: plain language for a caller who has never seen this
# repository. It may keep concepts a caller genuinely needs — the acting
# headers, idempotency, the refusal shape — and must explain them rather than
# name them. What it may NOT do is speak in house idiom, and the words that were
# taken out of it are recorded here so nobody puts them back:
#
# * "**door**" for a way into the product. There is no door in the reader's
#   vocabulary; the sections now say "the other ways in", "a tool", "connect to
#   /ws/". The doors are still the doors everywhere in this tree.
# * "**hat**" for the acting organization. `X-Org` is now explained as which
#   organization inside the tenant you are acting as, and why a large customer
#   has more than one.
# * "**Pydantic shapes**" — the reader does not know or care what builds them.
#   The property they need is that the shapes are the same across REST, MCP, the
#   webhook bodies and the socket payloads, and that is what it now says.
# * "**`manage.py introspect` prints the whole catalogue**" — a shell command is
#   no use to somebody holding an API key. `introspect` is still where a
#   maintainer reads the refusal registry; the overview now says instead that
#   each operation enumerates its own codes, which is the caller's route to the
#   same information.
# * "**django-allauth**", "**your default membership names**", "**not-there and
#   not-yours are one answer**" — library names and internal phrasing, replaced
#   by what the caller does about each.
#
# The landmarks `test_the_document_opens_with_the_overview` pins — `POST
# /tokens/`, `X-Org`, `Idempotency-Key`, `/mcp`, `/api/v1/` — are load-bearing:
# a rewrite keeps all five.
#
# IT IS THE GUIDES, AND THEY ARE SEPARATE FROM THE REFERENCE (the owner's
# ruling of 2026-08-24). Each `##` heading below is one concept a stranger reads
# ONCE and then stops reading — how to get a token, what the two acting headers
# mean, how a list is paged, what a refusal looks like. A renderer that builds a
# navigation out of `info.description` turns each of them into its own entry, so
# the sidebar reads as a short shelf of guides above the per-operation
# reference, and the contents line at the top links them by anchor for the
# readers that do not. Nothing here explains a single operation: the moment a
# guide starts saying what one route returns, it has become a worse copy of that
# route's own docstring. Keep the heading levels at `##` — `/llms.txt` demotes
# them by one when it embeds this, and a mixed set would nest wrongly there.


# A DOCSTRING, NOT A BARE CONSTANT. The quickstart's mint command shows
# a real `scopes` value, and the scope-annotation census
# (`apps/accounts/tests/test_scopes.py::test_no_route_carries_a_hand_written_scope_annotation`)
# reads docstrings — the places the vocabulary is QUOTED — as documentation and
# everything else as a binding annotation. This text is documentation, so it
# lives in the shape the census means by that. The string is flush-left inside
# the class, so `__doc__` is the exact text with no dedent step.
class _OverviewText:
    """\
The product's HTTP API. The request and response shapes described here are the
same ones used by every other way into the product — the MCP tools, the webhook
bodies, the WebSocket payloads — so learning this document is enough for all of
them.

**Start here:** [Quickstart](#quickstart) · [Authentication](#authentication) ·
[Connecting an agent](#connecting-an-agent) ·
[Tenants and organizations](#tenants-and-organizations) ·
[Pages and filters](#pages-and-filters) ·
[Dates and times](#dates-and-times) ·
[Retrying a write safely](#retrying-a-write-safely) ·
[Errors](#errors) · [Consuming webhooks](#consuming-webhooks) ·
[Events and other ways in](#events-and-other-ways-in) ·
[Changelog and deprecation policy](#changelog-and-deprecation-policy).
Everything after that is the reference: one entry per operation, with what to
send, what comes back, and every way it can be refused.

## Quickstart

Get a token, make a call, follow an id.

**1. Get a token.** Sign in at `/accounts/login/` — if you do not know where
your organization signs in, `POST /api/v1/auth/realm/` takes an email address
and answers before you have any credential. Then, still signed in, mint one —
`POST /tokens/` — from your browser's devtools console:

    await fetch("/api/v1/tokens/", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": document.cookie.match(/csrftoken=([^;]+)/)[1],
      },
      body: JSON.stringify({name: "quickstart", scopes: ["widgets:read"]}),
    }).then(r => r.json())

Minting takes a signed-in browser session plus that `X-CSRFToken` header — a
bearer token cannot mint another token. `scopes` has no default; omitting it is
refused. Ask for the narrowest set the job needs: every operation below names
the scope it wants, a section's write scope includes the read, and `["*"]`
means no limit at all.

**The token is in this one response and is never shown again** — save it now.
Read `effective_scopes` in the same response: it is the part of what you asked
for that your role can actually back, so a scope that would have been dead
weight shows up here rather than as a refusal later.

**2. Make a call.** Send the token on every request:

    curl http://localhost:8000/api/v1/widgets/ \\
         -H "Authorization: Bearer $TOKEN"

Every list answers the same envelope:

    {"items": [ ... ], "has_more": false, "next_cursor": null, "count": null}

**3. Follow an id.** Take an `id` out of `items` and ask for that row:

    curl http://localhost:8000/api/v1/widgets/$ID/ \\
         -H "Authorization: Bearer $TOKEN"

That is the shape of the whole API: a list you walk by following
`next_cursor`, and an `id` you follow to the single-item route.

**Next:** [Pages and filters](#pages-and-filters) for the rest of the list
controls · [Errors](#errors) for the refusal envelope ·
[Connecting an agent](#connecting-an-agent) to drive all of this through
`/mcp`.

## Authentication

Two credentials are accepted everywhere: a **bearer token**
(`Authorization: Bearer <token>`) for a program, and a **browser session
cookie** for a signed-in page. Send one, not both.

**A `POST`, `PUT`, `PATCH` or `DELETE` made with a session cookie must also
carry the value of the `csrftoken` cookie in an `X-CSRFToken` header** — a
cookie is sent by the browser whether or not the page meant it. A bearer token
needs nothing extra.

Mint a token with `POST /tokens/`. It belongs to one person, is pinned to one
tenant, and minting needs a browser session — a token cannot mint another
token, because the offspring would outlive its parent's revocation. Revoke one
with `DELETE /tokens/{id}/`: immediate, and the record stays, so the audit
trail still says what that token did.

**Every token carries a scope list**, asked for at the mint. A scope is a
section of this API followed by `:read` or `:write`, and each operation below
says which one it needs. Within a section the write scope includes the read —
one way only, and never across sections. A scope only narrows: the minter's
role still decides underneath, so ask for the narrowest set that does the job.
A call outside the token's list is refused with `insufficient_scope` naming
the missing scope. `["*"]` says out loud that a token should have no limit at
all.

A request with no usable credential answers `401` before anything else is
considered. That is not one of the refusals an operation lists, because
nothing about the caller has been decided yet.

### The two planes

The sections of this API fall into two planes, and **which plane you can
change things in is decided by your role in the tenant, not by your token** —
a scope narrows what your role already allows, never widens it. Ask for a
scope your role cannot back and the mint does not refuse you: it hands back a
narrower `effective_scopes`, which is why that field is worth reading — an
ordinary member asking for an administrative section's write scope is handed
that section's read scope instead.

**The everyday plane** is the product itself, plus the parts of the platform
that are about you. An ordinary member of a tenant reads and writes here all
day and never meets a `403`.

{EVERYDAY_PLANE}

**The administrative plane** is the tenant's own configuration. **Reading here
is open to anybody in the tenant**, narrowed as usual to the part of the tree
you are acting in. **Changing any of it takes an owner or an administrator**;
a member who tries is refused with `403 forbidden` saying which act was
refused.

{ADMINISTRATIVE_PLANE}

Two edges. A section in the everyday plane can still hold an administrator's
operation, and each such operation says so in its own description. And the
plane decides which refusal you meet: an act refused *on something you can
see* is `403 forbidden`; anything you were not allowed to see in the first
place is `404 not_found`, as
[Tenants and organizations](#tenants-and-organizations) explains.

## Connecting an agent

**This product ships a machine door and a map to drive it with, and no agent
of its own.** Bring the assistant you already use.

**The door is `/mcp`** — one Streamable-HTTP endpoint speaking the Model
Context Protocol. It takes the same bearer token as everything else, and the
same `X-Tenant` and `X-Org` headers:

    {
      "mcpServers": {
        "example": {
          "url": "http://localhost:8000/mcp",
          "headers": {"Authorization": "Bearer $TOKEN"}
        }
      }
    }

**The map is `/llms.txt`** — this same contract as flat text, generated when
you ask for it, so it cannot go stale. Hand it to an agent that is deciding
*which* call to make: every operation with its prose, the credential it wants,
the scope it needs and the ways it can refuse, plus the whole scope vocabulary
in one block. Far smaller than the OpenAPI document, and no JavaScript.

**A worked example.** Mint a token scoped to the one job — say `widgets:read`
and nothing else — point the agent at `/mcp` with it, and ask a question in
words. The agent finds `list_widgets`, calls it, and walks the pages by
handing back the `next_cursor` it was given. Same operation, same shapes and
same refusals as `GET /api/v1/widgets/`; every capability in this document is
a tool at `/mcp` unless its own description says why not.

**The tool list does not shrink to fit the token's scopes.** An out-of-scope
tool is still listed, and refuses when called, with `insufficient_scope`
naming the missing scope. Hiding it would teach the agent that the capability
does not exist — false, and unfixable, because nobody would learn which scope
to ask for. Refusing names the one that can.

## Tenants and organizations

Data here belongs to a **tenant** — one customer account — and each tenant is
a **tree of organizations**, so a large customer can keep its divisions,
regions or franchisees apart inside one account. Two optional headers say
where in that structure you are acting. Both are re-checked against your
memberships on every request, so neither can reach anything you were not
already allowed to see.

* **`X-Tenant: <slug>`** — which customer account. Leave it out and you act in
  the one your account defaults to. **Name one your credential cannot act in
  and the request is refused** — `403 addressing_header_not_honoured`, naming
  the header — rather than quietly answering with nothing in it. A header you
  sent is a header you meant, so a template that did not interpolate is told
  so instead of reading as an empty account.
* **`X-Org: <slug>`** — which organization inside that tenant: one you are a
  member of, or one below your membership. Leave it out and you act in the
  organization your membership names. Permissions run **downwards only**:
  acting as an organization shows you its own data and that of everything
  beneath it, never a neighbouring organization's and never its parent's.

**Anything you are not allowed to see answers `404 not_found`, not
`403 forbidden`** — so a `404` is never proof that something does not exist.
Do not build a client that treats it as one.

## Pages and filters

Every list route answers the same envelope and takes the same controls, so a
client that has learned one list has learned all of them:

    {"items": [ ... ], "has_more": true, "next_cursor": "eyJ2IjoxLCJ0Ijoi...", "count": null}

**Walk a list by following `next_cursor`.** Ask for the first page with no
cursor; while `has_more` is true, send the `next_cursor` you were just given
back as `?cursor=`. When `has_more` is false, `next_cursor` is `null` and you
have seen everything.

    GET /api/v1/widgets/
    GET /api/v1/widgets/?cursor=eyJ2IjoxLCJ0Ijoi...

* **`?cursor=`** — where to carry on from. **It is opaque**: signed, tied to
  the account and the sort order it was issued for, and not a page number in
  disguise. Never build one, edit one, or keep one across a change of
  `?ordering=` — an edited or replayed cursor is refused with
  `400 invalid_cursor`.
* **`?limit=`** — how many items to return, up to the maximum the schema
  publishes (`maximum` on this parameter). **Ask for more and the request is
  refused**, `400 invalid`, naming the field — you are never quietly given the
  maximum instead, because a page of 200 returned to a request for 5000 is
  indistinguishable from a list that had 200 items in it, and a client walking
  by that answer stops at the first page.
* **`?include_count=true`** — adds `count`, the exact number of matching items
  across the whole list. **Without it, `count` is `null`**: counting costs a
  second pass over the matches, so you pay for a total only where you display
  one.
* **`?ordering=`** — a field name, with `-` in front of it for descending.
  Each list states which fields it accepts; anything else is refused rather
  than ignored.
* **`?q=`** — free-text search, where the list says it is supported.

**There is no page number.** A list here is newest-first, so with offsets one
item created or removed while you read shifts everything after it, and page 2
silently skips or repeats an item — an answer that looks exactly like a
correct page. A cursor names a position, not a count. It does not promise a
frozen snapshot: an item added above where you are is not on this walk — start
again to see it — and an item edited into a position you have passed will not
come round again. What it removes is skipping an item you never saw.

Lists take filters of their own as well, named in each operation. A filter the
route does not accept is refused with `400 invalid`, so a typo in a filter
name never silently returns the unfiltered list.

## Dates and times

Every instant this API returns is **UTC, ISO-8601, to the millisecond**:

    "created_at": "2026-08-25T09:30:00.123Z"

**The same row read through the machine door at `/mcp` carries the same
string, byte for byte.** One encoder renders both doors, so a client may
compare two renderings of a row for equality, key a cache on one, or diff a
REST answer against a tool result without normalising anything first. Three
fractional digits is the contract, not an accident of whichever library
serialised the answer.

Send times the same way. A field named `_at` is an instant and a field named
`_on` is a calendar date (`"2026-08-25"`), which is the difference between
"when it happened" and "which day it belongs to".

## Retrying a write safely

Send **`Idempotency-Key: <a key you choose>`** on any `POST`, `PUT` or
`PATCH`. The first request under a key runs and its response is remembered.
Repeat the request **byte-identically** under the same key and you get that
same response back, marked with **`Idempotent-Replayed: true`** — the write does
not happen twice. Use a new random key per logical operation; reuse it only when
retrying that operation.

**Byte-identical means what it says.** The match is over the method, the path
and the raw body, so re-serialising the same data — a pretty-printer, a
different key order, an SDK that rebuilds the body on retry — is a DIFFERENT
request under a key that is already spoken for, and it is refused rather than
replayed. Retry by sending the bytes you sent the first time; keep the encoded
body if your client rebuilds it.

Two things are refused rather than guessed at:

* the same key with a **different body** — `409 idempotency_key_reuse`.
  Nothing was written. Pick a new key if you meant a new operation.
* a retry arriving while the **first one is still running** — `409
  in_progress`. Wait a moment and retry; the answer is not lost.

## Errors

Every refusal has the same JSON shape, whatever went wrong:

    {
      "detail": "No widget matches that id.",
      "code": "not_found",
      "remedies": [{"label": "List what you can see", "destination": "docs:openapi"}]
    }

* `detail` — a sentence saying what happened;
* `code` — a short stable string such as `not_found`. Branch on this, never on
  the status code or the wording;
* `errors` — present when the problem is with particular fields: an object of
  field name to a list of messages;
* `remedies` — what you can do about it, each with a label and where to go.

Each operation lists the codes it can answer with, so a client can be written
against that exact set rather than against every code in the API.

## Consuming webhooks

**This section is about the webhooks we send you.** Register a URL, and every
time an event you subscribed to happens, we POST the payload to it — the same
shape the matching REST route returns.

**1. Subscribe.** `POST /webhook-endpoints/` with your URL and the event names
you want; `GET /event-types/` lists every name this deployment can send,
derived from what the product actually declares. **The response to the
registration is the only place your signing secret is ever shown** — save it
then. If you lose it, `POST /webhook-endpoints/{id}/secret/` issues a new one
and the old one stops verifying at the next delivery.

**2. Verify every delivery.** Each one arrives with two signature headers,
both keyed on your secret. Check either. **Prefer `X-Signature-V2`.**

`X-Signature-V2: t=<unix seconds>,sha256=<hex>` — join the number after `t=`
to the **exact bytes of the body** with a single `.` between them, HMAC-SHA256
that with your secret, and compare it with the value after `sha256=` in
constant time. Then check that `t` is within **5 minutes** of your own clock.
Both checks must pass:

    import hashlib, hmac, time

    def verify_v2(secret: str, body: bytes, header: str) -> bool:
        parts = dict(p.split("=", 1) for p in header.split(","))
        signed_at, sent = int(parts["t"]), parts["sha256"]
        if abs(time.time() - signed_at) > 300:
            return False
        payload = str(signed_at).encode() + b"." + body
        mine = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(mine, sent)

`X-Signature: sha256=<hex>` — the original scheme: HMAC-SHA256 of the exact
body bytes, hex-encoded, prefixed with `sha256=`. It signs no timestamp, so a
copy of one delivery verifies against it for as long as your secret lives —
the time check is the reason to move. It is still sent on every delivery and
will not be withdrawn without notice:

    def verify_v1(secret: str, body: bytes, header: str) -> bool:
        mine = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest("sha256=" + mine, header)

For either scheme: **hash the bytes you received.** Parsing the JSON and
re-encoding it changes the bytes, and the signature will not match.

**3. Ignore what you have already seen.** Every delivery carries `X-Event-Id`,
**stable across retries and replays** — the same event sent again is the same
id. Record the ids you have processed and drop a repeat. Do not use `t` for
this: every attempt is signed at the moment it is sent, so a retry an hour
later carries a fresh `t` and a genuine signature. Deliveries also carry
`X-Event-Name` and `X-Correlation-Id`.

**4. Answer quickly, and know the retry schedule.** Any 2xx means accepted.
Anything else, or no answer at all, is a failure we retry:

* each attempt gets **15 seconds** to answer;
* we make up to **6 attempts** in all;
* the first retry follows about **2 seconds** later and each wait doubles,
  never going above **5 minutes** between attempts;
* the whole conversation about one delivery stops **1 hour** after it started.

So answer `202` from the front of your handler and do the work afterwards — a
receiver that finishes its own slow work before replying is how a healthy
integration starts failing under load.

**5. Read what happened, and replay what we gave up on.** `GET /deliveries/`
lists every delivery with its status, its attempt count, and what your server
last answered — when it answered at all. A delivery that survives the whole
schedule without being accepted is **dead-lettered**: nothing is retrying it
any more, and it appears in `GET /dead-letters/`. When you have fixed whatever
was wrong, `POST /dead-letters/{id}/replay/` sends it again — **to every
endpoint subscribed to that event, including ones that already received it**,
which is the other reason step 3 matters.

**Testing locally.** Register an endpoint pointing at a tunnel to your laptop,
make the change that fires the event, then watch `GET /deliveries/`: it says
whether we called you, what you answered and how many attempts are left.
Before there is anything to tunnel to, test the verifier alone: sign a body
with your own secret, check your verifier says yes, then change one byte and
check that it says no.

## Events and other ways in

* **Outbound webhooks** — see [Consuming webhooks](#consuming-webhooks).
  `GET /event-types/` lists every event name you can subscribe to.
* **MCP** — see [Connecting an agent](#connecting-an-agent): one
  Streamable-HTTP endpoint at **`/mcp`**, the same bearer token, the same
  headers, and every capability in this document as a tool.
* **WebSockets** — connect to `/ws/events/` to receive those same payloads as
  they happen, in the same shapes this document describes. A socket shows you
  what is happening while you are connected; a webhook is what reaches you
  when you are not.

## Changelog and deprecation policy

Every surface in this document is generated from the deployment that serves
it — this page, `openapi.json`, and `/llms.txt` — so the reference is never a
description of an older version of itself. Fetch `openapi.json` on a schedule
and diff it: a changelog that cannot disagree with what is running.

**What may appear without notice:** new operations, new sections, new
optional request fields, and new fields on a response. Write a client that
ignores fields it does not recognise and never treats an enum's value set as
exhaustive, and none of them will break it.

### Versioning

The version is in the path: **`/api/v1/`**. A breaking change arrives as a
`/v2/` alongside this one, and `/v1/` keeps answering until clients have
moved. Within a version, a field is never removed from a response, and never
changes type.

That promise runs from **2026-08-24**, the day list responses moved to cursors
and this API acquired its first outside consumer; the one change it does not
cover is that move itself. An exception to the promise is dated, in
writing, in this section — that paragraph is the only one there is. A change
that would need a second one is a `/v2/` instead.

### What a /v2/ would mean

`/v2/` is a **second path that answers alongside this one**, not a switch that
gets thrown. Removing a field, changing a field's type, or changing what an
operation means are the changes that earn one. When one arrives, `/v1/` keeps
answering while clients move, this page says so, and the date `/v1/` stops
being served is published before it happens.

A section name — which is half of every scope your tokens carry — and a URL
path are the same kind of promise: renaming either would break every token and
every client that named it, so neither is renamed inside a version.
"""


#: The guide with its two-planes bullet lists still unrendered. Not the
#: document's description — `overview()` is.
OVERVIEW_TEMPLATE = _OverviewText.__doc__ or ""


def overview() -> str:
    """The document's description, with the two planes rendered from the registry.

    **A function and not a constant**, and the reason is a hard import order
    rather than taste: rendering the planes walks every installed app's `api.py`
    for its `TAGS`, and this module is imported BY those modules (they take
    `Tag` from here). Rendering at import time would re-enter whichever app's
    `api.py` was half-way through importing us, find no `TAGS` on it yet, and
    drop that family from the guide — silently, and differently depending on
    which app Python reached first. Called after the registry is populated, the
    walk is the same one the vocabulary uses and the answer is the same answer.

    Disposition D2 of the partition design (`docs/product/partition-closure.md`
    §5): the plane assignments used to live in this file's prose, which made a
    product family unable to join a plane without an in-closure edit. They live
    on each family's own `Tag` now, and this renders them.
    """
    return OVERVIEW_TEMPLATE.replace("{EVERYDAY_PLANE}", plane_bullets(EVERYDAY)).replace(
        "{ADMINISTRATIVE_PLANE}", plane_bullets(ADMINISTRATIVE)
    )


# --- the renderer -------------------------------------------------------------
#
# THE DOCS PAGE IS THE HUMAN FRONT DOOR. This template ships no front end, so
# for every product cloned from it the first screen a person ever sees of the
# API is this one, and they inherit whatever it is. Swagger UI renders the
# derivations above as a wall of collapsed accordions; Scalar renders the same
# document with search, real Markdown, per-language code samples generated from
# the operations themselves, and a try-it client that works. Nothing about the
# document changes to get that — it is the same `openapi.json`, byte for byte,
# because a renderer that needed its own dialect would be a second contract.
#
# THE BUNDLE IS VENDORED, NOT FETCHED. Scalar's own instructions are a `<script
# src>` at a CDN; a CDN reference here would mean the docs page is blank on an
# aeroplane, blank in an air-gapped deployment, and blank in any test that runs
# without a network — and it would put a third party in the request path of the
# page that documents the product's security model. So the bundle is committed
# under `vendor/scalar/`, pinned by version and checksum in that directory's
# `MANIFEST.toml` (which explains why a checksum in a file is the whole posture
# for a browser asset no Python audit can see), and reached through `static()`
# so the URL comes from the staticfiles storage rather than from a string typed
# here — under production's manifest storage that URL carries a content hash,
# and a hard-coded path would 404 the day the bundle is upgraded.
#
# FIVE OF THE DEFAULTS ARE SWITCHED OFF. The first three are the offline criterion
# rather than styling: left alone the bundle pulls a webfont from
# `fonts.scalar.com` on load, and routes every "try it" request through
# `proxy.scalar.com` — which would hand a third party this deployment's API
# traffic from the one page that is meant to explain it. `hideClientButton`
# goes with them: it is the only other control that would render a link to an
# origin outside this deployment.
#
# AND THE FOURTH IS A POSTURE, NOT A PRECAUTION. **The platform offers no
# agent; `/mcp` is the door for the user's own**
# (`docs/product/design-agreements.md`). Users bring their own assistants and
# this
# product ships them a machine door and a map (`/llms.txt`) to drive it with; it
# does not ship, embed or offer an assistant of its own on any surface, and the
# docs page is a surface. Scalar's bundle carries one — the "Ask AI" panel in
# the sidebar — so it is off here, and it is off for that reason first.
#
# The second argument, and it is only the second: that panel's flow POSTs the
# OpenAPI document to Scalar's own service to embed it ("Failed to upload your
# OpenAPI document" is the bundle's own string for that request failing). The
# document is the whole shape of a deployment's API, and the panel offers to
# send it from a page a person opened in order to read. Observed live in
# production. The bundle decides for itself by inspecting
# `window.location.href`, so on a non-Scalar host it is *usually* off —
# "usually" being why it is now stated: `agent.disabled` is the bundle's
# explicit switch, read before any of the host-sniffing, and a posture that
# depends on which hostname a product deploys under is not a posture.
#
# AND THE FIFTH, WHICH IS THE SAME DOCTRINE FROM THE OTHER SIDE. The sidebar
# also offers **"Generate MCP"**, which builds an MCP server that proxies this
# OpenAPI document. **This product already ships an MCP door, at `/mcp`**: the
# same services behind it, the tenant and the acting organization revalidated
# per call, refusals byte-identical to the REST ones because both render one
# composer's body, every write audited, and house rule 17 holding it to the
# HTTP door capability for capability. A generated OpenAPI proxy is a SECOND
# machine door with none of that — a disagreement between two doors is a
# finding here, so shipping a button that manufactures one is refused on the
# same doctrine rather than on taste. It is also, secondarily, a third-party
# product funnel on a self-hosted page: the same family as the AI panel, and
# the same flow, since generating one uploads the document too. `mcp.disabled`
# is the bundle's switch, and it is read the same way — before the
# host-sniffing (`!config.mcp?.disabled && (isScalarHost(…) || !!config.mcp)`).

#: The vendored bundle, by its path under `vendor/` — the argument to
#: `static()`, never the URL. `vendor` is the prefix `STATICFILES_DIRS` mounts
#: that directory under, so this path is what a reader sees in the page source
#: too, minus the storage's hash.
SCALAR_BUNDLE = "vendor/scalar/scalar-api-reference-1.66.1.js"

#: Everything the page tells the bundle except where the document is. Five
#: entries: three keep the page inside this deployment, and `agent` and `mcp`
#: are the platform's own postures. The `url` is added per request, from
#: `reverse()`.
SCALAR_CONFIGURATION: Mapping[str, Any] = {
    # The platform offers no agent; `/mcp` is the door for the user's own.
    "agent": {"disabled": True},
    # The machine door this product ships IS `/mcp`; a generated proxy is a
    # second one with none of its guarantees.
    "mcp": {"disabled": True},
    "hideClientButton": True,
    "proxyUrl": "",
    "withDefaultFonts": False,
}

#: The page itself. Two script tags and nothing else, in this order, because
#: the bundle boots on load by looking for `#api-reference` — the element has
#: to exist before it runs. Deliberately not a Django template: the whole point
#: of the page is that it references exactly one local asset and no external
#: origin, and that is a property one can read off a dozen lines here and would
#: have to go and check in another file otherwise.
SCALAR_PAGE = (
    "<!DOCTYPE html>\n"
    '<html lang="en">\n'
    "<head>\n"
    '<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    '<meta name="robots" content="noindex">\n'
    "<title>{title}</title>\n"
    "<style>body {{ margin: 0; }}</style>\n"
    "</head>\n"
    "<body>\n"
    '<script id="api-reference" data-configuration="{configuration}"></script>\n'
    '<script src="{bundle}"></script>\n'
    "</body>\n"
    "</html>\n"
)


class Scalar(DocsBase):
    """Ninja's docs renderer, serving Scalar off the vendored bundle.

    `DocsBase` is django-ninja 1.x's one extension point for this
    (`ninja/openapi/docs.py`): `NinjaAPI(docs=...)` takes an instance, and the
    single route ninja mounts at `docs_url` — `api:openapi-view` — calls
    `render_page` on whatever that instance is. Passing one here is therefore
    the whole of the swap: `Swagger` stops being constructed, so there is no
    second page still answering somewhere. Ninja's Swagger assets remain in the
    installed package's static directory, inert, because nothing renders the
    template that loads them.

    `get_openapi_url` is inherited and not overridden: it reverses
    `<namespace>:openapi-json`, so the document's URL is read out of the live
    URL configuration and a product that mounts the API somewhere else gets a
    docs page that still points at its own document.
    """

    #: Overridable on a subclass, for a product that pins a different build.
    bundle: str = SCALAR_BUNDLE
    configuration: Mapping[str, Any] = SCALAR_CONFIGURATION

    def render_page(self, request: HttpRequest, api: NinjaAPI, **kwargs: Any) -> HttpResponse:
        """The docs page, with the document's URL resolved for this mount."""
        configuration = {**self.configuration, "url": self.get_openapi_url(api, kwargs)}
        return HttpResponse(
            format_html(
                SCALAR_PAGE,
                title=api.title,
                # `format_html` escapes this; the bundle un-escapes `&quot;`
                # itself, and a browser hands `getAttribute` the decoded text
                # either way. Sorted and separator-tight so the same
                # configuration renders the same bytes on every request.
                configuration=json.dumps(configuration, separators=(",", ":"), sort_keys=True),
                bundle=static(self.bundle),
            )
        )


#: The instance `config/api.py` mounts. A module-level singleton so the mount
#: is one argument naming one thing, and so a test can assert the API is
#: carrying *this* renderer rather than re-deriving what it should have been.
SCALAR = Scalar()


# --- /llms.txt ----------------------------------------------------------------
#
# THE SAME CONTRACT, FOR THE OTHER KIND OF READER. `/api/v1/docs` is three
# megabytes of JavaScript that assembles a document into a page; an agent
# deciding which call to make cannot run it, and `openapi.json` — 363 KB of
# nested `$ref`s — costs it a large fraction of a context window to learn that
# there is a widgets list. `/llms.txt` is the third rendering of the one
# document: flat text, one block per operation, the prose the route wrote about
# itself, and the refusal codes it can answer with.
#
# IT IS DERIVED AT REQUEST TIME AND NEVER CHECKED IN. A committed llms.txt is a
# copy of the contract, and a copy of the contract is the thing that disagrees
# with it — the exact failure ADR api-1 exists to prevent, one file further out.
# Everything here comes from `api.get_openapi_schema()`, which is the same
# document Scalar renders and `scripts/gen_client.sh` generates from, plus
# `reverse()` for the URLs and the refusal registry for the grammar. A route
# added tomorrow appears here with no edit; a route deleted disappears. There is
# nothing in this module that a person could forget to update.
#
# THE API ARRIVES AS AN ARGUMENT, bound by `config/urls.py` with `partial` —
# ninja mounts its own document view exactly that way. It is not imported: an
# app never imports `config` (the import-linter contract of that name), and
# this module is imported BY `config/api.py`, so reaching back would be a cycle
# as well as a violation. The view takes what the mount hands it.

#: What the refusal grammar looks like on the wire. One sentence per field, and
#: the fields themselves are `core.exceptions.wire_refusal`'s — named here
#: rather than re-derived because the composer builds a dict, and the shape of
#: that dict is what a caller branches on.
REFUSAL_SHAPE = (
    "detail   — one sentence a person can read.\n"
    "code     — the stable token to branch on. Never absent.\n"
    "errors   — present when the refusal is about fields: {field: [reason, ...]}.\n"
    "remedies — present when the code has any: [{label, destination}, ...].\n"
)

#: The order operations are printed in — a caller reads a resource, not a verb.
METHOD_ORDER = ("get", "post", "put", "patch", "delete", "head", "options", "trace")


def _wrap_block(title: str, body: str) -> list[str]:
    """A `## title` and its body, or nothing at all when the body is empty."""
    text = body.strip()
    return [f"## {title}", "", text, ""] if text else []


def _demoted(markdown: str) -> str:
    """The overview's guide headings, one level down, for embedding under `##`.

    The overview owns its own heading levels because the reference page renders
    it as a document in its own right; here it is a section INSIDE one, and a
    `##` nested under a `##` would tell an agent that "Errors" is a sibling of
    "Operations" rather than a part of the overview. One line of arithmetic
    beats two copies of the prose at different heading levels.
    """
    return "\n".join("#" + line if line.startswith("#") else line for line in markdown.splitlines())


def _security_line(operation: Mapping[str, Any], *, root: Any, schemes: Mapping[str, Any]) -> str:
    """What credential this operation wants, read the way the OpenAPI spec reads it.

    Resolution is the specified one and not a guess: an operation's own
    `security` wins; absent, the document's root `security` applies; absent
    there too, the operation has no security requirement. An empty list at
    either level means the same thing explicitly. Ninja emits `security` on
    every authenticated operation and omits it entirely on `auth=None`, so on
    this document the fallback is what correctly identifies the two allow-listed
    open routes — and a product that adds a root default gets the right answer
    from the same three lines.

    It is the one thing an agent must not have to guess: a route described as
    open that wants a token answers 401 to a call the agent had no reason to
    doubt.
    """
    declared = operation.get("security", root)
    if not declared:
        return "auth: none — this route answers without a credential."
    names = sorted({name for alternative in declared for name in alternative})
    described = [f"{name} ({_scheme_of(schemes.get(name, {}))})" for name in names]
    return "auth: required — " + " or ".join(described) + "."


def _scheme_of(scheme: Mapping[str, Any]) -> str:
    """An OpenAPI security scheme as the header or cookie a caller actually sends."""
    kind = str(scheme.get("type", "")).lower()
    if kind == "http":
        return f"Authorization: {str(scheme.get('scheme', 'bearer')).title()} <token>"
    if kind == "apikey":
        where = str(scheme.get("in", "header"))
        return f"{where} {scheme.get('name', '?')}"
    return kind or "unknown"


def _refusal_line(operation: Mapping[str, Any]) -> str:
    """`403 forbidden`-style pairs, from the codes the document already carries.

    `x-refusal-codes` is put on each response by the derivations above, so this
    reads what house rule 41 already checked rather than re-deriving it and
    risking a third answer.
    """
    pairs: list[str] = []
    for status, response in sorted(operation.get("responses", {}).items()):
        for code in response.get("x-refusal-codes", ()) if isinstance(response, dict) else ():
            pairs.append(f"{status} {code}")
    return "refuses: " + (", ".join(pairs) if pairs else "nothing beyond the API defaults") + "."


def _response_header_names(operation: Mapping[str, Any]) -> list[str]:
    """The response headers this operation documents, read back off the document.

    Read rather than re-derived, for `_refusal_line`'s reason: the derivation
    ran once, into the document, and a second pass over the declarations here
    would be a second answer that could disagree with the first.
    """
    names = {
        name
        for response in operation.get("responses", {}).values()
        if isinstance(response, Mapping)
        for name in (response.get("headers") or {})
    }
    return sorted(names)


def _response_headers_block(schema: Mapping[str, Any]) -> list[str]:
    """What the server puts on the way BACK, said once for the whole document.

    Every sentence is the one the OpenAPI document carries, lifted out of it —
    so the two renderings cannot drift apart, which is the whole reason this
    file is derived on request instead of checked in.
    """
    described: dict[str, str] = {}
    for path_item in schema.get("paths", {}).values():
        if not isinstance(path_item, Mapping):
            continue
        for operation in path_item.values():
            if not isinstance(operation, Mapping):
                continue
            for response in (operation.get("responses") or {}).values():
                if not isinstance(response, Mapping):
                    continue
                for name, spec in (response.get("headers") or {}).items():
                    if isinstance(spec, Mapping):
                        described.setdefault(name, str(spec.get("description", "")))
    if not described:
        return []
    return _wrap_block(
        "Response headers",
        "\n".join(f"{name}: {described[name]}" for name in sorted(described))
        + "\n\nWhich of these an operation sends is stated on the operation, below.",
    )


def _operation_block(
    *,
    method: str,
    path: str,
    operation: Mapping[str, Any],
    root: Any,
    schemes: Mapping[str, Any],
) -> list[str]:
    """One operation: what to call, what it is for, what it wants, how it refuses.

    The prose comes first and the mechanical lines after, because the decision
    an agent is making here is *which* call — and the title plus its opening
    sentence is what answers it. Both are printed: since 2026-08-24 `summary` is
    the docstring's TITLE and `description` is everything below it, so they no
    longer overlap and printing one without the other would drop half the
    answer. Title first, on its own line, so a reader skimming for a capability
    meets the same short phrase the reference page shows in its navigation.
    """
    lines = [f"### {method.upper()} {path}", ""]
    title = str(operation.get("summary", "")).strip()
    description = str(operation.get("description", "")).strip()
    if title:
        lines += [title, ""]
    if description:
        lines += [description, ""]
    lines += [_security_line(operation, root=root, schemes=schemes), _refusal_line(operation)]
    sent_back = _response_header_names(operation)
    if sent_back:
        lines.append("response headers: " + ", ".join(sent_back) + ".")
    required = [
        f"{parameter.get('in', '?')} {parameter.get('name', '?')}"
        for parameter in operation.get("parameters", ())
        if parameter.get("required")
    ]
    if required:
        lines.append("required parameters: " + ", ".join(required) + ".")
    lines.append("")
    return lines


#: The line that makes a section of `/llms.txt` machine-readable: the wire name
#: of the tag the section holds. It is printed and not inferred from the heading,
#: because the heading is the DISPLAY name — a person's label, renamable by
#: design — and a client that guessed the wire name off it would guess wrong the
#: first time somebody wrote "Accounts & tokens" over `tokens`.
TAG_LINE = "tag: "

#: What that section's scopes are called, on the same terms. Both halves are
#: derived from the tag by the same function the operations use, so the block a
#: reader learns the vocabulary from cannot name a scope the door would refuse.
SCOPES_LINE = "scopes: "

#: Where an operation goes when it carries no tag at all. Nothing in a healthy
#: document reaches it — house rule 41 gives every operation exactly one tag —
#: and it exists so that a document which broke that rule still PRINTS the
#: operation instead of dropping it silently. It is deliberately not a tag name,
#: so the section census that reads `tag:` lines is the thing that notices.
UNGROUPED_HEADING = "Operations outside every section"


def _tag_section(
    *,
    name: str,
    declared: Mapping[str, Any],
    blocks: Sequence[str],
) -> list[str]:
    """One group of operations: its name, its wire tag, its scopes, what it is for.

    The three facts a reader needs before they read the operations, and all
    three are read off the document rather than written here: the display name
    and the description come from the owning app's own `TAGS` declaration, and
    the scopes come from the same derivation the door enforces with. A section
    that named a scope by hand would be the one place in this file a caller
    could be told about a ceiling that does not exist.

    The description is printed as it was declared, undemoted. A declaration with
    a heading in it would show up as an extra section — and the section census
    in the tests is exactly the thing that would then fail, by name, which is a
    better outcome than quietly reshaping somebody's prose.
    """
    display = str(declared.get("x-displayName") or name).strip()
    description = str(declared.get("description") or "").strip()
    scopes = [
        scope
        for scope in (
            derived_scope(tags=[name], methods=["GET"]),
            derived_scope(tags=[name], methods=["POST"]),
        )
        if scope
    ]
    lines = [f"## {display}", "", f"{TAG_LINE}{name}"]
    if scopes:
        lines.append(SCOPES_LINE + ", ".join(scopes))
    lines.append("")
    if description:
        lines += [description, ""]
    return lines + list(blocks)


def _tag_sections(
    schema: Mapping[str, Any],
    *,
    root: Any,
    schemes: Mapping[str, Any],
) -> list[str]:
    """The reference, grouped the way the document itself groups it.

    Previously `/llms.txt` printed one flat run of operations and said
    nothing at all about the tags — which was proven the hard way: moving every
    route to a different tag changed the reference page and left this file
    byte-identical. An agent reading only this
    surface could not learn that the sections exist, and therefore could not
    learn what the scope families are named after, which is the one thing it
    needs in order to tell a person which token to mint.

    Grouping is by the tag the operation carries, and the sections come out
    sorted by wire name so two deployments with the same routes produce the same
    text. A tag an operation carries without the document declaring it still
    gets a section — under its wire name, with no description — because dropping
    the operation would be the silence this whole file exists to prevent.
    """
    grouped: dict[str, list[str]] = {}
    for path in sorted(schema.get("paths", {})):
        methods = schema["paths"][path]
        for method in METHOD_ORDER:
            operation = methods.get(method)
            if not isinstance(operation, dict):
                continue
            tags = [str(tag) for tag in (operation.get("tags") or [])]
            grouped.setdefault(tags[0] if tags else "", []).extend(
                _operation_block(
                    method=method,
                    path=path,
                    operation=operation,
                    root=root,
                    schemes=schemes,
                )
            )

    declared: dict[str, Mapping[str, Any]] = {
        str(tag["name"]): tag
        for tag in schema.get("tags", ())
        if isinstance(tag, Mapping) and tag.get("name")
    }

    lines: list[str] = []
    for name in sorted(set(declared) | (set(grouped) - {""})):
        lines += _tag_section(
            name=name,
            declared=declared.get(name, {}),
            blocks=grouped.get(name, ()),
        )
    if grouped.get(""):
        lines += [f"## {UNGROUPED_HEADING}", "", *grouped[""]]
    return lines


def _vocabulary() -> tuple[str, ...]:
    """Every scope name this deployment has, for the block above.

    Imported inside the function like `_mcp_path` below and for a related
    reason: `scopes.py` registers a refusal into the registry this module reads
    at module scope, and two modules that import each other at import time is a
    cycle whichever one Python reaches first.
    """
    from apps.core.api.scopes import vocabulary

    return vocabulary()


def _mcp_path() -> str:
    """Where the machine door answers — imported here and not at module scope.

    **This module is BELOW `apps.core.mcp`, and the arrow may only point one
    way.** `mcp.py` imports `contract_of` from here so that a tool and its REST
    twin cannot describe one capability differently (house rule 17, one surface
    earlier). A module-level `from apps.core.mcp import MCP_PATH` here closes
    that into a cycle, and Python's failure mode for it is the worst one
    available: whichever module is imported second gets a *partially
    initialized* first one, so `manage.py check` dies with an ImportError
    naming a symbol that plainly exists. It did — the two halves landed in
    different rungs and met at the merge, which is the only place the cycle
    could exist.

    The fix is the direction, not the timing: the low module does not name the
    high one at import. Reading it inside the one function that needs it is
    what makes that true, and it costs a dictionary lookup on a page a person
    asks for now and then. It is the same shape `apps.core.checks` and
    `introspect` use to read the mounts (`pyproject.toml`'s import-linter
    exemptions say why), for the same reason.
    """
    from apps.core.mcp import MCP_PATH

    return MCP_PATH


def llms_text(api: NinjaAPI) -> str:
    """The whole of `/llms.txt`, built from the live document and the live URLs.

    Grouped into one section per tag — the same sections the reference page
    shows, each naming its wire tag and the scopes that reach it — and within a
    section ordered by path and then by HTTP verb rather than by the registry's
    insertion order, so two deployments with the same routes produce the same
    text and a diff between them is a real difference.
    """
    # Deferred, not lazy-for-speed: see the note beside this module's imports —
    schema = api.get_openapi_schema()
    info = schema.get("info", {})
    schemes = schema.get("components", {}).get("securitySchemes", {})
    root_security = schema.get("security")
    document_url = reverse(f"{api.urls_namespace}:openapi-json")
    reference_url = reverse(f"{api.urls_namespace}:openapi-view")

    lines = [
        f"# {info.get('title', 'API')} (version {info.get('version', '?')})",
        "",
        "A plain-text rendering of this deployment's HTTP contract, for an agent "
        "deciding which call to make. It is generated on request from the same "
        "OpenAPI document served below — never a checked-in file — so it cannot "
        "be out of date with the routes it describes.",
        "",
    ]

    lines += _wrap_block(
        "The doors",
        "\n".join(
            [
                f"OpenAPI document (JSON, authoritative): {document_url}",
                f"The same contract as a page, for a person: {reference_url}",
                f"MCP, for a tool-using agent: {_mcp_path()} "
                "(Streamable HTTP, the same bearer token, the same headers). "
                "Every capability below is a tool there unless its description says why not.",
            ]
        ),
    )

    lines += _wrap_block("Overview", _demoted(str(info.get("description", ""))))

    # How many operations answer without a credential is COUNTED, not asserted.
    # Two different routes each described themselves as "the one route in this
    # API that takes no token" and both were telling the truth as their author
    # remembered it. A number derived from the document
    # cannot be wrong twice in two files, and it goes stale the moment the
    # document does, which is to say never.
    open_count = sum(
        1
        for path in schema.get("paths", {}).values()
        for operation in path.values()
        if isinstance(operation, dict) and not operation.get("security", root_security)
    )
    lines += _wrap_block(
        "Authentication",
        "\n".join(
            [f"{name}: {_scheme_of(scheme)}" for name, scheme in sorted(schemes.items())]
            + [
                "",
                "Every operation below states its own requirement. "
                f"{open_count} of them require no credential at all; "
                "the rest do. Send one credential, not both.",
            ]
        ),
    )

    lines += _wrap_block(
        "Token scopes",
        "\n".join(
            [
                "A bearer token carries a CEILING: the set of things it is allowed to "
                "reach. Ask for the narrowest set that does the job — a scope only ever "
                "narrows, and the role of the person who minted the token still decides "
                "underneath, so a wide token is never more than its person and a narrow "
                "one is strictly less.",
                "",
                "A scope is one of this API's sections followed by `:read` or `:write`. "
                "`GET` and `HEAD` need the `read` half; every other method needs the "
                "`write` half. Each operation below names the one it needs.",
                "",
                "Within one section the write scope INCLUDES the read: a token carrying "
                "`<section>:write` may also read that section, and does not need "
                "`<section>:read` as well. It works one way only — a read scope never "
                "allows a write — and it never crosses sections, so a write on one says "
                "nothing about any other.",
                "",
                "The scopes that exist here:",
                "",
            ]
            + [f"  {scope}" for scope in _vocabulary()]
            + [
                "",
                "Mint one at POST /tokens/, sending `scopes` as a list of these names — "
                'or the single entry "*" for a token with no ceiling at all. There is no '
                "default; a mint that names no scopes is refused. The response's "
                "`effective_scopes` tells you which of what you asked for the minting "
                "person's role can actually back, so a scope that would have been dead "
                "weight is visible at the mint rather than as a refusal later.",
                "",
                "A call whose scope the token does not carry is refused with "
                "`insufficient_scope`, and the refusal names the scope that was missing. "
                "The set of tools at the machine door does not shrink with the ceiling: "
                "an out-of-ceiling capability is still listed, still describes itself, "
                "and refuses when called — so an agent can tell the person which scope to "
                "mint instead of reporting that a capability does not exist.",
            ]
        ),
    )

    lines += _wrap_block(
        "Refusals",
        "Every refusal is the same JSON object, whichever door produced it:\n\n"
        + REFUSAL_SHAPE
        + "\nThe registered codes, and what each one asserts:\n\n"
        + "\n".join(f"{code}: {REFUSALS[code].fact}" for code in sorted(REFUSALS)),
    )

    lines += _response_headers_block(schema)

    lines += _wrap_block(
        "Operations",
        "One section per part of this API, below — the same grouping the "
        "reference page shows in its navigation, and the same one the token "
        "scopes are named after. Each section states its tag (the wire name a "
        "client turns into a namespace), the scopes that reach it, and what the "
        "group is for. Operations are sorted by path and then by method within "
        "their own section.",
    )
    lines += _tag_sections(schema, root=root_security, schemes=schemes)
    return "\n".join(lines).rstrip() + "\n"


def llms_txt(request: HttpRequest, *, api: NinjaAPI) -> HttpResponse:
    """`/llms.txt` — the contract as text, derived from the mount that serves it.

    Unauthenticated, and narrowly so: it says strictly less than
    `openapi.json`, which answers without a credential at the same deployment,
    and it opens nothing. `api` is bound by `config/urls.py`; see the note above
    for why it is not imported.
    """
    return HttpResponse(llms_text(api), content_type="text/plain; charset=utf-8")
