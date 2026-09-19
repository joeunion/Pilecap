"""What a bearer token is allowed to reach, and how that is worked out.

ADR ident-7. A token used to carry the whole of its person's power, which is a
problem the moment tokens are handed to agent runtimes as ordinary practice. A
token now carries a **ceiling**: a list of `<family>:<verb-class>` strings, and
a call is refused at the door when the ceiling does not hold the one the call
needs. The person's role and the app's policies keep deciding underneath, so
the ceiling can only ever *narrow* — nothing a token holds exceeds the person
who minted it, by construction.

**The vocabulary is a census, not a list.** A family is a tag key — the same
`TAGS` declaration each app already writes beside its routers and that the
OpenAPI document already groups by — so an app that grows a tagged router grows
the vocabulary with no file outside that app edited. The verb classes are
exactly two: `read` and `write`. Nothing here enumerates a scope name, and
there is therefore nothing for a hand list to drift from.

**The derivation is total.** Every operation carries exactly one tag (house
rule 41 refuses a second) and its method says which verb class it is —
`GET`/`HEAD` read, everything else writes. That makes `required_scope` a
function rather than a lookup, which is why no route is annotated: there is
nothing to annotate.

**A family key is wire vocabulary now, and it FREEZES.** It sits under the
renamable display name the same way every other immutable key in this tree
does: renaming a key after tokens exist kills every ceiling that named it,
which is a credential-breaking change of the same class as renaming a URL —
and the failure is silent, because the token goes on authenticating and simply
starts being refused at every door. `FROZEN_FAMILIES` is the census of what has
shipped and `family_freeze_findings` is the predicate; `SANCTIONED_RENAMES`
carries the one departure an owner has ruled, which is the last cheap one.

**Where this is read.** The two door seams — `config/api.py` for HTTP and the
MCP mount — and nowhere below them. A service, selector or policy that
consulted a ceiling would be a second permission system, drifting from the
first the day they disagree.
"""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Iterable, Sequence
from typing import Any

from django.apps import apps as django_apps

from apps.core.api.frozen_families import FROZEN_FAMILIES, SANCTIONED_RENAMES
from apps.core.exceptions import Forbidden, Invalid, Remedy, register_refusal

__all__ = [
    "FROZEN_FAMILIES",
    "READ",
    "RENAME_IS_CLOSED",
    "SANCTIONED_RENAMES",
    "SCOPE_SEPARATOR",
    "UNSCOPED",
    "VERB_CLASSES",
    "WRITE",
    "InsufficientScope",
    "UnderivableScope",
    "ceiling_from_request",
    "effective_scopes",
    "families",
    "families_of_app",
    "family_freeze_findings",
    "granted_scopes",
    "parse_scope",
    "required_scope",
    "verb_class",
    "vocabulary",
    "within_ceiling",
]

#: The two verb classes, and there are deliberately only two. A third — an
#: "admin" class — cannot be derived: somebody would have to decide by hand
#: which writes are the dangerous ones, which is the enumeration this whole
#: module exists to avoid. The privileged surface is already its own family
#: wherever it matters, and the role underneath is the real guard.
READ = "read"
WRITE = "write"
VERB_CLASSES: tuple[str, ...] = (READ, WRITE)

#: What joins the two halves. A family key may contain a hyphen —
#: `tenant-settings` is one of them — and never a colon, which is what makes
#: splitting on the LAST separator exact rather than lucky.
SCOPE_SEPARATOR = ":"

#: The spoken form of "no ceiling at all". A mint door accepts it and stores no
#: ceiling, so a full-power token is something somebody asked for out loud
#: rather than something they got by leaving a field out.
UNSCOPED = "*"

#: The HTTP methods that only ever read. Everything else writes — stated as the
#: small closed set rather than the open one, because a method nobody here has
#: heard of is far more likely to change something than not.
READING_METHODS = frozenset({"GET", "HEAD"})


class UnderivableScope(Exception):
    """No scope could be worked out for an operation, so nothing may assume one.

    Raised rather than answered with a default, and that is the point: a
    fallback would let a route with a broken tag through every ceiling in the
    product and nothing would ever say so. It is an internal failure — a
    misdeclared route, not a caller's mistake — so it is not a refusal code and
    never reaches the wire.
    """


register_refusal(
    code="insufficient_scope",
    boundary="door",
    remedy=(
        "The token authenticated fine and its ceiling does not cover this operation. "
        "The scope is derived from the operation's tag and its method by "
        "`apps/core/api/scopes.py::required_scope`; nothing is annotated per route, so "
        "the fix is a wider token and never a change to the route."
    ),
    fact=(
        "This token is limited to a set of scopes, and this operation needs one it does "
        "not carry. Nothing was read and nothing was written. The limit is on the token, "
        "not on the person who minted it — the same person signed in with a browser, or "
        "holding a wider token, may well be allowed to do this."
    ),
    remedies=(
        Remedy(
            "Mint a new token that carries the scope named here — the operation "
            "that mints one is under API tokens",
            "docs:openapi",
        ),
        Remedy("See which scope each operation needs, beside the operation", "docs:openapi"),
    ),
    # 403, its base class's, declared here rather than under `config/` (ADR
    # core-23) — the ceiling's refusal is this module's fact.
    status=403,
)


class InsufficientScope(Forbidden):
    """The token's ceiling does not reach this operation.

    A `Forbidden`, so the one mapper answers it `403` by walking the class tree
    and no status table is edited. It is a **door** refusal: it happens after
    the credential resolved and before anything below the door has been asked
    whether the person may — which is why a caller who gets this cannot
    conclude they would have been allowed with a wider token, only that this
    token was never going to find out.
    """

    code = "insufficient_scope"
    default_detail = "This token is not scoped for that."


def _tag_declarations_by_app() -> dict[str, dict[str, Any]]:
    """Every tag key any installed app declares beside its routers, by app label.

    Discovery, the same shape `INSTALLED_APPS` and the mounts use: an app that
    drops an `api.py` with a `TAGS` dict is in the population, and nothing is
    edited to put it there. Deliberately its own walk rather than a call into
    `config/api.py` — an app never imports `config`, and this module sits below
    the one that does.

    Kept grouped by app because two callers need the grouping and flattening it
    is the cheap direction: which families one app owns is the only honest way
    to ask "does this token reach anything this app can say", and an app is not
    its family — `comms` declares `messaging`, so a reader that assumed the two
    words were the same word would be right about six apps and wrong about that
    one, silently.
    """
    collected: dict[str, dict[str, Any]] = {}
    for config in django_apps.get_app_configs():
        if not config.name.startswith("apps."):
            continue
        module_name = f"{config.name}.api"
        if importlib.util.find_spec(module_name) is None:
            continue
        declared = getattr(importlib.import_module(module_name), "TAGS", None)
        if isinstance(declared, dict):
            collected[str(config.label)] = {str(name): entry for name, entry in declared.items()}
    return collected


def _tag_declarations() -> dict[str, Any]:
    """Every tag key any installed app declares, flattened across apps."""
    return {
        name: entry
        for declared in _tag_declarations_by_app().values()
        for name, entry in declared.items()
    }


def families_of_app(label: str) -> tuple[str, ...]:
    """The families one app owns, sorted. Empty when it declares no tagged router.

    The app label is what an event name's first segment and a tool's module path
    both give you, and neither of them gives you a family — so this is the one
    translation, and it is a lookup in the declaration rather than a guess from
    the spelling.

    Empty is a real answer and it is the closed one: an app with no tagged
    router owns no family, so no ceiling can name it, so a scoped credential
    reaches nothing it emits. Widening that to "everyone may" would let a narrow
    token hear from whichever app happened not to have a door yet.
    """
    return tuple(sorted(_tag_declarations_by_app().get(label, {})))


def families() -> tuple[str, ...]:
    """Every scope family this deployment has, sorted. Derived on every call.

    Not cached: a cache here would be a copy of the registry taken at whichever
    moment the first caller happened to ask, and the population it copies is
    exactly the thing a test plants a new app into.
    """
    return tuple(sorted(_tag_declarations()))


def vocabulary() -> tuple[str, ...]:
    """Every scope name that exists here — families crossed with verb classes."""
    return tuple(
        f"{family}{SCOPE_SEPARATOR}{verb}" for family in families() for verb in VERB_CLASSES
    )


# --- The freeze ---------------------------------------------------------------
# A family key is not a label. It is the literal string sitting in an
# `ApiToken.scopes` row on somebody else's machine, pasted into somebody else's
# agent runtime, and possibly written down in their own runbook. Renaming it
# does not break loudly: the token authenticates exactly as it did and starts
# being refused at every door, with nothing anywhere saying why — which is the
# worst shape a credential change can take, because the person holding it has no
# way to work out what to ask for instead.
#
# So the vocabulary GROWS freely and does not CHANGE. Growth is the whole design
# — an app that drops a tagged router joins the census with no file outside that
# app edited — and this is the other half of it: what has shipped, stays.


# The two records themselves live in `frozen_families.py` and are re-exported
# here UNCHANGED — same names, same values, same meaning, every caller and every
# test untouched. The move is the partition's disposition D1
# (`docs/product/partition-closure.md` §3 and §5): this is the one platform file
# a product APPENDS to in the commit that ships its first family, so it is the
# one file excluded from the platform partition's input closure. In-closure, a
# product's first door moved the closure hash and produced a false red;
# out-of-closure, the append reaches the partition through the discovery digest
# instead, whose `scope_families` section serializes this very ledger. That
# module's docstring carries the whole argument; nothing about the freeze
# changed.


#: Said in every freeze finding, because it is the part somebody needs to read.
#:
#: The three renames above were affordable because scoped tokens were days old
#: when the ruling landed and the PM sanctioned the break. That window is shut:
#: the next rename meets tokens minted by people who are not in this room, so it
#: is a deprecation with two live keys and a migration window, not an edit.
RENAME_IS_CLOSED = (
    "The three-way split of 2026-08-24 was the LAST cheap rename this vocabulary "
    "gets: scoped tokens were days old and the break was sanctioned. Any rename "
    "after it meets credentials held by people who cannot be asked, so it is a "
    "deprecation — both keys live, a window, and a way for a holder to find out "
    "— and never an edit to a key."
)


def family_freeze_findings(live: Sequence[str] | None = None) -> tuple[str, ...]:
    """What the freeze has to say about this deployment's vocabulary.

    Empty is clean. One sentence per finding, each naming the key, the scopes a
    token may be holding because of it, and what to do instead — so a builder
    who has just renamed a tag reads the consequence rather than a rule number.

    Takes the live families as a parameter so it can be planted BOTH WAYS: a
    vocabulary that has lost a frozen key, and a vocabulary that has grown a
    retired one back. Defaulting to `families()` is what every real caller
    wants; a check that could only ever be run against the truth is a check
    nobody can prove fires.

    **One direction only.** A family in `live` that is not frozen is not a
    finding — that is a new app with a new door, and refusing it would turn the
    census into a hand list every app has to be added to before it may have a
    tag, which is the enumeration this whole module exists to avoid.
    """
    present = {str(family) for family in (families() if live is None else live)}
    findings: list[str] = []
    for family in FROZEN_FAMILIES:
        if family in present:
            continue
        findings.append(
            f"the family key {family!r} is frozen and this deployment no longer "
            f"has it. A token minted here may be carrying {family}:read or "
            f"{family}:write, and every such ceiling is now dead: the token goes "
            "on authenticating and is refused at every door, with nothing "
            "telling its holder why. Restore the key, or record the change in "
            "SANCTIONED_RENAMES with the ruling that sanctioned it. "
            f"{RENAME_IS_CLOSED}"
        )
    for retired, successors in SANCTIONED_RENAMES.items():
        if retired not in present:
            continue
        findings.append(
            f"the family key {retired!r} was retired and is live again. It became "
            f"{', '.join(successors)}, so a token minted before the change would "
            "now be silently re-armed against whatever this key covers today — "
            "which is not what the person who minted it was told they were "
            f"granting. {RENAME_IS_CLOSED}"
        )
    return tuple(findings)


def _rename_advice(unknown: Sequence[str]) -> tuple[str, ...]:
    """For each unknown scope whose family we retired, the sentence that follows.

    Only for a key this tree ONCE HAD. A typo gets the plain refusal — telling
    somebody who wrote `orgnaizations:read` that it "was renamed" would be a
    fluent, confident lie, and the plain sentence plus the vocabulary is what
    they actually need.
    """
    advice: list[str] = []
    for entry in unknown:
        parsed = parse_scope(entry)
        if parsed is None:
            continue
        family, verb = parsed
        successors = SANCTIONED_RENAMES.get(family)
        if not successors:
            continue
        replacements = ", ".join(f"`{name}{SCOPE_SEPARATOR}{verb}`" for name in successors)
        advice.append(
            f"`{entry}` was retired: the {family!r} section became "
            f"{len(successors)} sections, so ask for {replacements} — whichever "
            "of them this token's job actually needs, and no more."
        )
    return tuple(advice)


def parse_scope(value: str) -> tuple[str, str] | None:
    """Split `family:verb` into its halves, or `None` when it is not one.

    Split on the LAST separator. A family may carry a hyphen, and one of them
    does, so a parser that had assumed one word per half would have been right
    about nine families and silently wrong about the tenth.
    """
    family, separator, verb = str(value).rpartition(SCOPE_SEPARATOR)
    if not separator or not family or verb not in VERB_CLASSES:
        return None
    return family, verb


def verb_class(methods: Iterable[str]) -> str:
    """Which of the two classes a set of HTTP methods falls in.

    An operation that both reads and writes is a write, because the ceiling is
    a ceiling: the wider of the two is the one that has to be held.
    """
    verbs = {str(method).upper() for method in methods}
    return READ if verbs and verbs <= READING_METHODS else WRITE


def required_scope(*, tags: Sequence[str], methods: Sequence[str]) -> str:
    """The one scope a call needs, from its tag and its method.

    Keyword-only and taking the two halves rather than an operation object, so
    that the HTTP door (which holds a bound operation), the machine door (which
    holds a tool and its twin's tag) and a test walking the published document
    all reach the same function instead of three that agree by review.

    Raises `UnderivableScope` when the tag is missing or doubled — never a
    default. An operation with two tags is already a house-rule violation and
    guessing which one bounds it would turn that into a silent hole.
    """
    named = [str(tag) for tag in tags or ()]
    if len(named) != 1:
        raise UnderivableScope(
            f"a scope is derived from exactly one tag and this operation carries "
            f"{len(named)} ({', '.join(repr(tag) for tag in named) or 'none'}); "
            "a tag is what says which family a capability belongs to"
        )
    return f"{named[0]}{SCOPE_SEPARATOR}{verb_class(methods)}"


def granted_scopes(ceiling: Sequence[str]) -> frozenset[str]:
    """Everything a written-down ceiling actually grants.

    **The one place the verbs' relationship is expressed.** `write` implies
    `read` within its own family (owner ruling, 2026-08-24): the two verbs are
    levels, not flags, so a token allowed to change a section's records is
    allowed to look at them. Nobody minting a token for an agent that files
    invoices should have to remember to ask for the reading half as well — and
    the pair that gets forgotten is the one that fails at three in the morning.

    Two boundaries, and both are the point:

    * **one direction only.** `read` never satisfies `write`. A token given the
      narrow half stays narrow, which is the whole reason for having halves.
    * **one family only.** `widgets:write` says nothing whatever about
      `users:read`. The implication is inside a section, never across the
      product.

    Rejected, and recorded: treating the two verbs as orthogonal flags. It reads
    tidier and it makes every real mint a pair — `widgets:read` beside
    `widgets:write` on every family an agent touches — so the population of
    tokens that can write but mysteriously cannot read is created by ordinary
    forgetfulness rather than by anybody's decision. Deferred with a trigger: a
    genuinely submit-only credential (write without read — a drop box) is a
    THIRD verb somebody declares on purpose, never this one quietly stopping
    implying.
    """
    held = {str(entry) for entry in ceiling}
    implied = set(held)
    for entry in held:
        parsed = parse_scope(entry)
        if parsed is not None and parsed[1] == WRITE:
            implied.add(f"{parsed[0]}{SCOPE_SEPARATOR}{READ}")
    return frozenset(implied)


def within_ceiling(*, ceiling: Sequence[str] | None, scope: str) -> bool:
    """Whether a token holding `ceiling` may make a call needing `scope`.

    `None` is the whole point of the parameter being nullable: it means the
    token was minted before ceilings existed, or was minted `*` deliberately,
    and either way it carries every scope. That meaning is fixed forever —
    the column was added expand-only and rewriting what an existing row means
    is not something an expand-only change is allowed to do.

    Everything else is `granted_scopes`, which is where the one relationship
    between the two verbs lives: a write carries its own family's read.
    """
    if ceiling is None:
        return True
    return scope in granted_scopes(ceiling)


def ceiling_from_request(requested: Sequence[str] | None) -> list[str] | None:
    """What a mint door asked for, turned into what the row stores.

    **The one place both mint doors agree**, so that the browser and the shell
    cannot come to say two different things about the same mistake. Returns
    `None` for the unscoped form, which is the same value a token minted before
    any of this existed carries — one meaning, one representation.

    Refuses three things, each with the sentence the person needs:

    * saying nothing at all — a token's reach is a decision, and a default
      would quietly make it the widest one;
    * an empty list — a token that can do nothing is a mistake, not a ceiling;
    * a name that is not in this deployment's vocabulary, naming where the
      vocabulary comes from so the next attempt can be right — and, when the
      name is one this tree once had, what it became (`_rename_advice`). That
      is guidance and not a shim: the old string is refused, and it stays
      refused, because translating it would go on granting the ceiling the
      rename existed to retire.
    """
    if requested is None:
        raise Invalid(
            {"scopes": ["Say which scopes this token should have."]},
            detail=(
                "Say which scopes this token should have. Send a list of "
                "`family:read` or `family:write` names, or the single entry "
                '"*" if it really should be able to do everything you can. '
                "The families are the sections of this API; the reference page "
                "and /llms.txt both list them."
            ),
        )
    asked = [str(entry).strip() for entry in requested if str(entry).strip()]
    if not asked:
        raise Invalid(
            {"scopes": ["A token with no scopes could not do anything."]},
            detail=(
                "A token with no scopes could not do anything, so this is more "
                "likely a mistake than a very careful choice. Name the scopes it "
                'needs, or send the single entry "*" for a token with no limit.'
            ),
        )
    if UNSCOPED in asked:
        if len(asked) > 1:
            raise Invalid(
                {"scopes": [f'"{UNSCOPED}" means every scope, so it cannot be combined.']},
                detail=(
                    f'"{UNSCOPED}" already means every scope, so it cannot be sent '
                    "alongside others. Send it on its own, or list exactly the "
                    "scopes you want."
                ),
            )
        return None
    known = set(vocabulary())
    unknown = [entry for entry in asked if entry not in known]
    if unknown:
        advice = _rename_advice(unknown)
        raise Invalid(
            {
                "scopes": [f"{entry!r} is not a scope in this API." for entry in unknown]
                + list(advice)
            },
            detail=(
                f"{', '.join(repr(entry) for entry in unknown)} "
                f"{'is not a scope' if len(unknown) == 1 else 'are not scopes'} in this "
                "API. A scope is one of this API's sections followed by `:read` or "
                "`:write` — the sections are the headings on the reference page, and "
                "/llms.txt lists every scope name in one place."
                + ("" if not advice else " " + " ".join(advice))
            ),
        )
    return sorted(dict.fromkeys(asked))


def effective_scopes(
    *,
    user: Any,
    tenant: Any,
    org: Any = None,
    scopes: Sequence[str] | None,
) -> list[str] | None:
    """Which of the scopes asked for this person could actually use today.

    **Why a mint door answers this at all.** Somebody setting an agent up asks
    for the reach they think the job needs, and a scope their own role cannot
    back is dead weight: the token carries it, the role underneath refuses
    anyway, and the first anybody hears of it is a refusal in production
    hours later on a call nobody is watching. Saying so at the mint is the
    cheapest moment there is.

    **What it is derived from, said plainly, because it is a guide and not a
    promise.** What this person holds in the token's tenant, at the hat —
    `core.authz.effective_permissions`, which is the one derivation of "what
    may this person do here" and reads all three layers: the role their
    membership names, this tenant's own deltas on it, and their own grants. If
    every key they hold is a read, the write half of what they asked for is
    dead weight and the echo says so. One granted write key anywhere — a
    tenant's custom role, one `allow` grant — and the write scopes stand.

    It used to read a ROLE and compare it against a rank, which could not see a
    grant at all: somebody given exactly one write capability was told their
    write scopes were dead, and they were not.

    **The declaration, not the transition** (`compat=False`). A key a role
    holds today only because the app that owns it has not been swept yet is a
    capability its own predicate still narrows — and an echo is a claim about
    what a credential can back, so it is made from what the roles and the rows
    actually say. Reading the transitional set here would promise a member the
    write half of every family with an un-swept predicate in it.

    So a write scope missing from this list means *most* of that family will
    refuse; it does not mean all of it will, because a policy is free to let a
    member act on their own records and several do. The reverse never happens —
    a scope in this list is one the data layer admits, and a policy can still
    refuse an individual call for a reason about the row rather than about the
    person.

    `None` in, `None` out: a token with no ceiling asked for nothing in
    particular, so there is nothing to answer about.
    """
    if scopes is None:
        return None
    from apps.core.authz import effective_permissions, vocabulary

    # What was ASKED FOR, plus what asking for it carried: a write scope brings
    # its family's read, and the echo is where somebody sees that rather than
    # having to know it. Explicitness lives at the mint; the wire just answers.
    granted = sorted(granted_scopes(scopes))
    held = effective_permissions(user, tenant, org, compat=False)
    if not held:
        return []
    words = vocabulary()
    if any(not words[action].is_read for action in held if action in words):
        return granted
    return [scope for scope in granted if (parse_scope(scope) or ("", WRITE))[1] == READ]
