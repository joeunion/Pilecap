"""Authorization: the service's half of the answer.

**Both layers, with a clear division** (`architecture.md`): the *door*
authenticates and resolves the tenant — a route's `auth=`, an MCP bearer token,
the socket middleware. The *service* authorizes, object by object, through
`require(actor, action, obj)`. A door that contains permission logic is the
same violation from the other side: it means the MCP tool, the activity and the
admin each get their own subtly different copy of the rule.

**Two halves, composed with AND** (ADR core-25, and it is what `allows` below
does step by step):

1. **The data half — what this person HOLDS here.** `effective_permissions`
   resolves three layers into one set: `owner` is the vocabulary; a declared
   role is its patterns over it (`apps/<x>/roles.py`); a tenant's own rows —
   custom roles, deltas on a declared role, and one person's grants — are the
   difference. A withhold beats everything. Roles inherit **downwards** and
   nothing else, so the question is always asked *at a node*.
2. **The code half — may this person do this to THAT ROW.** An app's
   `policies.py` exposes `POLICIES: dict[str, Callable[[Actor, Any], bool]]`,
   keyed `"widget.update"`. Discovered, never registered: drop the file and
   the predicate is gone. A predicate's **no is final**, for an owner too.

That split is the point. "How much of this tenant is yours" is data, and a
product reshapes it without a deploy; "is this person the widget's own
creator" is code, and no amount of role editing can express it. Trying to say
the second as more roles is how a permission system becomes forty checkboxes
nobody can reason about.

Beside them, and discovered the same way: **`ACTION_PROSE` — the sentence a
refused caller reads.** An action name is a key, not English; `require` answers
with the app's declared sentence for it and never with the key itself.

**Silence is no.** A key nobody declared is refused and logged
(`core.authz.undeclared`), and a key nobody holds is refused whatever the verb
looks like: an action nobody has written down is an action nobody has thought
about. **There is no exception for `<kind>.read` any more** (ADR core-27, Phase
R): a read resolves through the same three layers as a write, the selector asks
it once, and `visible_to` keeps answering the other question — which rows.

**And one question neither of them asks.** `require` answers "may you do this
kind of thing here"; the scoped manager answers "whose rows are these". Neither
answers "could you have got hold of *that* reference" — the foreign key handed
to a service by id, resolving to a row in a branch the caller holds no
membership over. That is `may_be_named(actor, obj)`, below, with its own
`# reach:` override grammar and its own house rule (26) reading the call sites.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from django.apps import AppConfig
from django.apps import apps as django_apps
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db import models

from apps.core import discovery, verbs
from apps.core.actor import Actor, actor_for
from apps.core.exceptions import Forbidden
from apps.core.log import get_logger
from apps.core.models import (
    AUTHZ_KIND_DERIVED,
    Grant,
    Membership,
    Organization,
    OrgScopedModel,
    RolePermission,
    Tenant,
    is_descendant_path,
    is_inherited_downward,
)
from apps.core.roads import road

log = get_logger(__name__)

Policy = Callable[[Actor, Any], bool]

# Roles, ordered. **deprecated v2.1 → removed v3.0.** The order used to be the
# only place in the tree that said one role outranks another, and it was the
# wall: "no grant above your own" was a number comparison. It is not any more —
# a custom role ranks 0 here, so the comparison could never bound one, and the
# ceiling is now the reserved key `tenant.own`, which only `owner` holds. Kept
# through v2.x because `effective_role` and every un-swept predicate still read
# it, and because removing it in the release that replaced it would have been
# two changes wearing one line.
ROLE_RANK: dict[str, int] = {
    Membership.Role.MEMBER: 1,
    Membership.Role.ADMIN: 2,
    Membership.Role.OWNER: 3,
}
# The rank a grant must not exceed, and the floor for "may administer".
# deprecated v2.1 → removed v3.0, with `ROLE_RANK` above and for its reason.
ADMIN_RANK = ROLE_RANK[Membership.Role.ADMIN]

_registry: dict[str, Policy] | None = None
_prose: dict[str, str] | None = None
_kinds: dict[str, type[models.Model]] | None = None
_words: dict[str, Permission] | None = None
_renames: dict[str, str] | None = None
_roles: dict[str, DeclaredRole] | None = None
#: Role key → the app label that declared it, filled by the same walk.
_role_apps: dict[str, str] = {}
#: A rename is announced ONCE per process. A deprecation printed per call is a
#: deprecation nobody reads; a module-level set is what makes it a notice.
_announced: set[str] = set()


def _declarations(module: str, attribute: str) -> list[tuple[AppConfig, dict[Any, Any]]]:
    """Every app's `<module>.<attribute>` dict, in app order, with its declarer.

    A caller of `core.discovery.declared`, which is THE discovery walk — so the
    vocabulary and the noun-verb family's hooks share one walk rather than two
    copies of it (principle 13). `policies.py` and `roles.py`
    are found the same way for the same reason — drop the file and the
    declaration counts, with no registration anywhere — and the `AppConfig`
    travels with the dict because every refusal below has to name WHICH app
    declared the thing it is refusing.
    """
    return discovery.declared(module, attribute)


def action_prose() -> dict[str, str]:
    """Every app's `ACTION_PROSE`, merged. Discovered once, then cached.

    **The refusal a person reads, declared beside the policy that refuses.** An
    action name (`"invitation.create"`) is an internal key: it is how a service
    asks the question and it is not English, so publishing it on the wire told a
    caller to go and read our source (the owner's plain-language ruling of
    2026-08-23; found live by FT-1 as "You may not invitation.create."). What
    goes out instead is one plain sentence per action, and it lives in the app
    that owns the action for the same reason the policy does — a product adds an
    action and its sentence in one file, and never edits `core`.
    """
    global _prose
    if _prose is None:
        _prose = _discover_prose()
    return _prose


def _discover_prose() -> dict[str, str]:
    found: dict[str, str] = {}
    for _, declared in _declarations("policies", "ACTION_PROSE"):
        found.update({str(action): str(text) for action, text in declared.items()})
    return found


def refusal_sentence(action: str) -> str:
    """What a refused caller is told. Plain language, never the action name.

    The declared sentence when there is one, and otherwise a **humanised**
    fallback built from the action's own parts — `"widget.approve"` becomes
    "You may not approve this widget." The fallback exists so that an action
    without a sentence degrades to English rather than to a dotted identifier;
    it is not a substitute for declaring one, and it reads badly on purpose for
    a two-word verb (`endpoint.issue_secret`), which is the nudge.

    A three-part action (`accounts.user.erase`) is read as `<app>.<noun>.<verb>`
    and the app segment is dropped: a caller does not know or care which module
    the rule lives in.

    A **renamed** key reads its successor's sentence, which is how a rename
    costs zero words: the sentence moved with the key, byte for byte, and a
    product still calling the old name is told exactly what it was told before.
    """
    action = renamed_permissions().get(action, action)
    declared = action_prose().get(action)
    if not declared:
        known = vocabulary().get(action)
        if known is not None:
            return known.sentence
    if declared:
        return declared
    parts = [part for part in action.split(".") if part]
    if len(parts) < 2:
        return "You may not do that here."
    noun, verb = parts[-2], parts[-1]
    return f"You may not {verb.replace('_', ' ')} this {noun.replace('_', ' ')}."


def policies() -> dict[str, Policy]:
    """Every app's `POLICIES`, merged. Discovered once, then cached."""
    global _registry
    if _registry is None:
        _registry = _discover_policies()
    return _registry


#: The predicates the `system` actor must answer to. Filled only by
#: `refuses_system` at import of the declaring module, and never by discovery —
#: so `reset_policies` leaves it alone.
_refuses_system: set[Policy] = set()


def refuses_system[P: Policy](predicate: P) -> P:
    """Declare that this predicate is asked of the `system` actor too.

    **The rule: the product acting for itself is refused only by a policy that
    says so; every other policy keeps the exemption.** `allows` step 1 waves a
    workflow, a schedule or a command through before any predicate runs, and
    that stays the default — the system has no membership to consult and the
    scoped manager still enforces the tenancy. A predicate decorated here is
    the one exception: for its keys the system actor gets the predicate's own
    answer, and a no raises the same `Forbidden` with the same sentence a
    member reads. A declaration beside the predicate, never a list of keys in
    `core`, so the exception lives where a reviewer reads the rule it guards.

    Returns the predicate unchanged, so the decorated name is the registered one.
    """
    _refuses_system.add(predicate)
    return predicate


def refusing_system() -> frozenset[Policy]:
    """The predicates that declared `refuses_system`, as a read-only set."""
    return frozenset(_refuses_system)


def reset_policies() -> None:
    """Drop every discovered cache. For tests that plant a declaration module.

    The vocabulary, the roles registry and the rename table are derived from
    the same declarations the policy registry is, so they all go together: a
    test that planted prose and dropped only `_registry` would be measured
    against a vocabulary built before its plant existed.
    """
    global _registry, _prose, _kinds, _words, _renames, _roles
    _registry = None
    _prose = None
    _kinds = None
    _words = None
    _renames = None
    _roles = None
    _role_apps.clear()
    _announced.clear()


@runtime_checkable
class DeclaresRoles(Protocol):
    """A policy object that says, as DATA, which roles it admits.

    **deprecated v2.1 → removed v3.0.** A predicate declaring which roles it
    admits was the shape of "roles are data" while a role was one of three
    words. It is not the shape any more: what a role holds is a COLLECTION the
    deployment and the tenant both have a say in, and an app that wants a key
    open to a role says so in `DEFAULT_ROLES`, which the vocabulary reads.

    **The mechanism is the platform's; the fact is the app's.** `core` never
    learns that `usage.read_report` is open to everybody — it learns only that a
    policy *may* carry a `roles` set, and how to read one. An app declares the
    set beside the action it belongs to (`apps/usage/policies.py`'s
    `DeclaredPermission`), which is where the roles-are-data half of "roles are
    data, policies are code" has always lived, and where a product narrowing it
    edits one line in a diff a reviewer sees.

    A `Protocol` rather than a base class for the same reason: inheriting from
    something in `core` would make every declaring app import a shape from below
    it and would put the vocabulary of permissions into the platform. Structural
    typing costs the app nothing and lets `core` read a declaration it could not
    have named.
    """

    roles: frozenset[str]


def declared_roles(policy: Policy) -> frozenset[str] | None:
    """The roles a policy DECLARES, or `None` when it declares none. Never a guess.

    deprecated v2.1 → removed v3.0, with `DeclaresRoles` and for its reason.

    Two kinds of policy live in this registry and the difference is exactly what
    an instrument has to say out loud:

    * A **declaring** policy carries its admitted roles as data — the predicate
      consults the declaration, so the roles ARE the rule and can be published.
      A bound method is unwrapped to the object that holds the set, because the
      house form is `DeclaredPermission.can` in an app's `POLICIES` dict and the
      declaration is on the instance behind it.
    * An **opaque** policy is arbitrary code — `owns_or_is_privileged`,
      `may_read_the_ledger`. There is no role set to read, and inventing one
      would be worse than the silence: `None` is the honest answer, and
      `introspect` prints it as `null` rather than as a set nobody declared.

    The membership test is deliberately strict — a `frozenset`/`set` of `str`,
    nothing else. An attribute called `roles` that is a queryset, a list of
    model instances or a comma-joined string is not a declaration in this sense,
    and reading one as if it were is how an instrument comes to publish a
    permission that is not the one being enforced, one layer down.

    DOES NOT COVER — declared: whether the predicate actually consults its own
    declaration. `DeclaredPermission.can` does, and its app pins that; a policy
    that carried a `roles` set and then ignored it would be published here as if
    it mattered. The gate cannot see inside a predicate, and pretending
    otherwise is the failure this function exists to stop repeating.
    """
    holder: Any = getattr(policy, "__self__", policy)
    roles = getattr(holder, "roles", None)
    if isinstance(roles, (frozenset, set)) and all(isinstance(role, str) for role in roles):
        return frozenset(roles)
    return None


def _discover_policies() -> dict[str, Policy]:
    found: dict[str, Policy] = {}
    for _, declared in _declarations("policies", "POLICIES"):
        found.update({str(action): policy for action, policy in declared.items()})
    return found


# =============================================================================
# The vocabulary — one shape, `<kind>.<verb>`, derived before declared
# (ADR core-25)
# =============================================================================
#
# **Computed at import, never stored.** Django derives four permissions per
# model at `migrate` and writes them as rows; this derives four per kind at
# import and writes nothing, because rows go stale against code the moment a
# product adds a model, and a vocabulary with two owners is a vocabulary with
# none (principle 9).
#
# Three ways a key gets into the vocabulary, and they are ranked:
#
# 1. **derived** — every first-party model is a KIND and every kind carries
#    `create`, `read`, `update` and `delete` with a sentence built from its
#    `verbose_name`. A builder cannot forget one. An app may override the
#    SENTENCE by keying its `ACTION_PROSE` on a derived key; it may not
#    override whether the key exists.
# 2. **declared** — a status transition or a compound act, declared on a kind
#    in the owning app's `ACTION_PROSE` as one line: the key and its sentence.
#    A predicate in `POLICIES` and a `DEFAULT_ROLES` entry are both optional.
# 3. **reserved** — `core`'s own, below: ownership, which no pattern matches
#    and no role collection may include.

#: The four verbs every kind carries. Not configurable: a fifth would be a
#: second shape, and `read` is THE read verb — `view`, `list` and `get` are
#: three more spellings of it and the census says so.
CRUD_VERBS: tuple[str, ...] = ("create", "read", "update", "delete")

#: The three other spellings of `read` — the one alias set. The vocabulary
#: census reads it (a key spelled with one is non-conforming), the MCP door's
#: tool grammar reads it (a tool named after one of them reads), and the
#: deprecated `is_read()` shim reads it with `read` itself.
READ_ALIAS_VERBS = frozenset({"view", "list", "get"})

#: A kind or a verb: lowercase, underscores, no dots. The dot is the separator.
_SEGMENT = re.compile(r"^[a-z][a-z0-9_]*$")
_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")

#: The one platform role. Not a declaration and not a row: `owner` IS the
#: vocabulary, present and future, reads and the reserved verb included.
OWNER_ROLE = "owner"

#: Kinds with no row behind them. **A list of one, printed by the census**, so
#: that "the kind is not in the model registry" stays a refusal rather than a
#: shrug the next unbound noun slips through.
VIRTUAL_KINDS: dict[str, str] = {
    "deployment": (
        "the installation itself. Configuring the identity platform is a "
        "platform-operator act — a superuser, no tenant, no membership, no row "
        "— so there is no model to be a kind of, and inventing one would be "
        "inventing a table to hold a permission. It stays inside `require` so "
        "that one function is still the only place authorization is asked."
    ),
}

#: `core`'s reserved keys, with their sentences. A reserved key is a declared
#: verb that **no pattern matches** (`"*"` included), no declared or custom role
#: may include, and no grant may name — so `owner` is the only holder, and every
#: ceiling the rank table used to enforce follows from that one fact.
RESERVED_PERMISSIONS: dict[str, str] = {
    "tenant.own": "You may not make somebody an owner of this tenant.",
}


@dataclass(frozen=True)
class Permission:
    """One key in the vocabulary, with everything an instrument prints about it.

    `decided_by` is the honest half: `derived` means the model registry
    produced this key and nobody typed it, `declared` means an app's
    `ACTION_PROSE` did, `reserved` means `core` did. `conforms` and
    `non_conformance` are the census's: a key that does not fit the shape is
    still in here and still answers exactly as it does today — the transition
    is not allowed to widen or narrow anything — and the sweep that fixes it is
    named by its own rung.
    """

    action: str
    sentence: str
    kind: str
    verb: str
    app: str
    decided_by: str
    is_read: bool
    conforms: bool
    non_conformance: str = ""
    default_roles: tuple[str, ...] = ()
    predicate: Policy | None = None
    renamed_from: tuple[str, ...] = ()


@dataclass(frozen=True)
class DeclaredRole:
    """A role a product declares in code: a name and a set of PATTERNS.

    Patterns rather than a list of keys, because a list goes stale the first
    time an app is added: `("*.read",)` is still "may read everything" in a
    deployment with three more apps in it, and no data migration ran.

    `is_default_for_new_members` marks the one role a new membership gets when
    nobody says otherwise. One declaration may carry it, or none; two is an
    `ImproperlyConfigured`, because "the role a new member gets" is one answer.
    """

    key: str
    name: str
    permissions: tuple[str, ...] = ()
    is_default_for_new_members: bool = False
    description: str = field(default="", compare=False)


def snake_case(name: str) -> str:
    """`Widget -> widget`, `WidgetEntry -> widget_entry`, `WorkflowRun -> workflow_run`.

    DOES NOT COVER — declared: an acronym in a class name. `SSOConnection`
    becomes `s_s_o_connection` here, which is not a name anybody would write.
    The valve is `authz_kind`, and a product with such a class sets it; the
    census prints every kind, so the wrong one is visible the first time it is
    derived rather than the first time a grant is handed out.
    """
    return _CAMEL_BOUNDARY.sub("_", name).lower()


def first_party_models() -> list[type[models.Model]]:
    """Every concrete model this deployment designed, read off the registry.

    Filtered **by module**, not by base class: `auth.Permission`,
    `socialaccount.SocialToken` and `admin.LogEntry` are tables we did not
    design, and a permission over one of them is a permission nobody can act
    on. Not filtered to the SCOPED models either — `Membership`, `Tenant`,
    `User` and `ApiToken` are read and written through tenant doors and already
    carry keys, so the scoped set would leave four kinds outside the shape on
    day one.
    """
    return [model for model in django_apps.get_models() if model.__module__.startswith("apps.")]


def _own_kind(model: type[models.Model]) -> str | None:
    label = model._meta.label
    declared = getattr(model, "authz_kind", AUTHZ_KIND_DERIVED)
    if declared is None:
        reason = str(getattr(model, "authz_kind_reason", "") or "").strip()
        if not reason:
            raise ImproperlyConfigured(
                f"{label} sets `authz_kind = None` and declares no `authz_kind_reason`. "
                "Opting a model out of the vocabulary is a claim — no door reaches a row "
                "of it, nobody could be given a capability over it — and a claim with no "
                "sentence beside it is one nobody can disagree with."
            )
        return None
    kind = snake_case(model.__name__) if declared == AUTHZ_KIND_DERIVED else str(declared)
    if not _SEGMENT.match(kind):
        raise ImproperlyConfigured(
            f"{label} declares the authorization kind {kind!r}, which is not a key segment. "
            "A kind is lowercase letters, digits and underscores, starting with a letter; "
            "the dot is what separates it from the verb."
        )
    return kind


def _parent_kind(model: type[models.Model]) -> str | None:
    """The kind of the aggregate an owned child is authorized under."""
    label = model._meta.label
    name = str(getattr(model, "authz_kind_of", "") or "")
    try:
        related = model._meta.get_field(name)
    except FieldDoesNotExist:
        raise ImproperlyConfigured(
            f"{label} declares `authz_kind_of = {name!r}` and has no such field. "
            "It names the foreign key to the aggregate whose kind authorizes this row."
        ) from None
    remote = getattr(related, "remote_field", None)
    parent: type[models.Model] | None = getattr(related, "related_model", None)
    if remote is None or parent is None:
        raise ImproperlyConfigured(
            f"{label} declares `authz_kind_of = {name!r}`, which is not a foreign key."
        )
    if remote.on_delete is not models.CASCADE:
        raise ImproperlyConfigured(
            f"{label} declares `authz_kind_of = {name!r}`, whose `on_delete` is not CASCADE. "
            "A row authorized under its parent's kind is a row that DIES with the parent — "
            "writing a line of a ledger is writing the ledger. A row that outlives its "
            "parent is its own record and carries its own kind."
        )
    return kind_of(parent)


def kind_of(model: type[models.Model]) -> str | None:
    """The authorization kind of a model, or `None` when it opted out.

    Derived from the class name unless the model says otherwise, and taken from
    the aggregate above it when the model declares `authz_kind_of`.
    """
    if getattr(model, "authz_kind_of", None) is not None:
        return _parent_kind(model)
    return _own_kind(model)


def kind_registry_of(population: Iterable[type[models.Model]]) -> dict[str, type[models.Model]]:
    """Kind → the model that owns it, over a population handed in.

    The seam the real registry and the refusal tests both go through, so the
    two underivable cases — a kind claimed twice, an `authz_kind_of` naming a
    key that is not `CASCADE` — are proven against the same code that runs in
    the deployment rather than against a re-derivation of it.
    """
    registry: dict[str, type[models.Model]] = {}
    owners: dict[str, str] = {}
    children: list[type[models.Model]] = []
    for model in population:
        if getattr(model, "authz_kind_of", None) is not None:
            children.append(model)
            continue
        kind = _own_kind(model)
        if kind is None:
            continue
        if kind in owners:
            raise ImproperlyConfigured(
                f"{owners[kind]} and {model._meta.label} both claim the authorization kind "
                f"{kind!r}. A key would mean a different row depending on import order, so "
                "the vocabulary cannot be derived at all: one of them sets `authz_kind` to "
                "something else."
            )
        owners[kind] = model._meta.label
        registry[kind] = model
    for child in children:
        # Resolved for its refusals, not for its entry: an owned child adds no
        # kind of its own — that is what `authz_kind_of` means.
        _parent_kind(child)
    return registry


def kind_registry() -> Mapping[str, type[models.Model]]:
    """Every kind this deployment has, computed once, then cached."""
    global _kinds
    if _kinds is None:
        _kinds = kind_registry_of(first_party_models())
    return MappingProxyType(_kinds)


# --- What an event is ABOUT (ADR core-27; moved here by R4-F2) ----------------
#
# `kind_of_event` and `event_kinds_of` lived in `apps/realtime/bridge.py` until
# R4-F2, and the move is a seam constraint rather than tidiness: `emit()` has to
# ask the question too — an org-scoped event that carries no branch is broadcast
# tenant-wide by `bridge.group_for` — and `apps/events` may not import
# `apps/realtime`, because `import-linter` holds the platform apps independent of
# each other. The answer is a REGISTRY READ plus a per-app declaration and needs
# nothing either app owns, so it belongs below both of them. `apps/realtime`
# re-exports both names, so every existing reader is unchanged.

#: Which segment of `<app>.<noun>.<past-verb>` names the thing the event is about.
NOUN_SEGMENT = 1

#: The per-app declaration `kind_of_event` consults: `{noun: kind or None}`, in
#: the app's own `events.py` beside the names it maps. Per app rather than one
#: table here, because the app that declares the name is the only place that
#: knows which row the name is about — and a central table would be a hand list
#: with nothing re-deriving it (§I).
EVENT_KINDS_ATTRIBUTE = "EVENT_KINDS"


def event_kinds_of(app_label: str) -> Mapping[str, str | None]:
    """The noun → kind mapping one app declares, or an empty one.

    Read from the live app registry and **never cached**, for the reason
    `apps.events.events.declared_names` gives about its own registry: the number
    of apps is small and a cache is one more thing to invalidate in a test that
    plants a module. An app with no `events.py`, no `EVENT_KINDS`, or a label
    nothing is installed under answers `{}` — "declares no mapping", which
    `kind_of_event` then turns into a refusal rather than into a guess.
    """
    declared = discovery.declared_by(app_label, "events", EVENT_KINDS_ATTRIBUTE)
    return dict(declared) if isinstance(declared, Mapping) else {}


def kind_of_event(name: str) -> str | None:
    """The authorization kind an event is about, or `None` when nothing owns it.

    **Two doors ask this now** (R4-F2). The socket asks it per frame (ADR
    core-27): a connection holds the kinds its hat may read, and a frame is
    delivered when the kind this answers is one of them. `emit()` asks it per
    write: an event about an org-scoped row must carry the branch it landed in,
    and one about nothing must not name a branch at all — the two refusals in
    `apps.events.services.emit`.

    **Three answers, in this order, and the order is the design.** The noun IS a
    kind (`widget`, `message`, `connection`) — the common case, one frozenset
    lookup, no import; else the emitting app's `EVENT_KINDS` says which kind
    governs it (`suppression` → `suppression_surge`) or says `None` with the
    reason beside it; else `ImproperlyConfigured`. The registry is asked FIRST so
    that an app cannot quietly re-point a noun that already names a kind at a
    different one — which would be two answers to "who may read this" depending
    on which door asked.

    **It refuses rather than defaulting, and that is deliberate.** Defaulting
    open leaks a kind nobody checked; defaulting closed silently stops
    delivering an event, and a socket that has stopped delivering is the hardest
    failure in this product to notice. A refusal is loud where it is cheap:
    `apps/realtime/tests/test_read_fanout.py::test_every_event_noun_maps_to_a_kind_or_a_declared_none`
    walks the whole declared population on every gate run, so an unmapped noun
    is a red test and never a live surprise. The consumer's own per-frame
    handling of the refusal is `consumers._may_read`, which says what it does and
    why.

    **When the thing is absent:** a noun that is not a kind and that the app
    does not map raises, naming the noun and the file that must decide about it.
    """
    segments = str(name).split(".")
    if len(segments) <= NOUN_SEGMENT or not segments[NOUN_SEGMENT].strip():
        raise ImproperlyConfigured(
            f"{name!r} is not <app>.<noun>.<past-verb>, so it names no noun to be about."
        )
    app_label, noun = segments[0], segments[NOUN_SEGMENT]
    if noun in kind_registry():
        return noun
    declared = event_kinds_of(app_label)
    if noun in declared:
        return declared[noun]
    raise ImproperlyConfigured(
        f"{name!r} is about {noun!r}, which is no authorization kind and which "
        f"apps/{app_label}/events.py does not decide in {EVENT_KINDS_ATTRIBUTE}. "
        "The socket narrows what it delivers by the kinds a hat may read, so an "
        "undecided noun is an event nobody can be asked about: map it to the kind "
        f"whose `<kind>.read` governs it, or to None with the reason beside it when "
        "no row is behind it."
    )


def is_org_scoped_kind(kind: str | None) -> bool:
    """Whether rows of this kind belong to one BRANCH of a tenant.

    The runtime half of what rules 38 and 59 read statically: rule 38 keeps
    `organization_id` on such a model's `Out`, rule 59 keeps it on the payload an
    `emit` passes, and this is how `emit()` itself knows which question to ask.
    One derivation — `kind_registry()` crossed with the `OrgScopedModel`
    inheritance the ORM already knows — so a model that gains a branch joins this
    population without anybody editing a list.

    `None` is not org-scoped by construction: it means no row is behind the
    event at all, which is the other refusal's subject rather than this one's.
    """
    if kind is None:
        return False
    model = kind_registry().get(kind)
    return model is not None and issubclass(model, OrgScopedModel)


def _derived_sentence(model: type[models.Model], verb: str) -> str:
    meta = model._meta
    one = str(meta.verbose_name)
    many = str(meta.verbose_name_plural)
    if verb == "create":
        return f"You may not create {many} here."
    if verb == "read":
        return f"You may not read this {one}."
    if verb == "update":
        return f"You may not change this {one}."
    if verb == "delete":
        return f"You may not delete this {one}."
    # A family verb a marker derived (`archive`, `restore`, …): its own word.
    return f"You may not {verb} this {one}."


def _classify(action: str, kinds: Mapping[str, Any]) -> tuple[str, str, str]:
    """`(kind, verb, why it does not conform)` for a DECLARED key. `""` when it does."""
    parts = action.split(".")
    if len(parts) != 2:
        return (
            ".".join(parts[:-1]),
            parts[-1],
            f"a key is `<kind>.<verb>`; {action!r} has {len(parts)} parts",
        )
    kind, verb = parts
    if kind not in kinds and kind not in VIRTUAL_KINDS:
        return (
            kind,
            verb,
            f"no kind {kind!r}: no first-party model derives or declares it, and it is not "
            "one of the virtual kinds",
        )
    if verb in CRUD_VERBS:
        return (kind, verb, f"a second spelling of the derived key {action!r}")
    if verb in READ_ALIAS_VERBS:
        return (kind, verb, f"`read` is THE read verb; {verb!r} is another spelling of it")
    return (kind, verb, "")


def family_verbs(model: type[models.Model]) -> tuple[str, ...]:
    """The noun-verb family's verbs this model's markers derive, in road order.

    `Archivable` → `("archive", "restore")`, `Movable` → `("move",)` — each
    road's `grants`, never its routes (a bulk route grants nothing: it runs the
    noun's own verbs). The roads are `core.verbs.ROADS`,
    the same table house rule 74 reads, so the vocabulary and the rule that
    demands the doors cannot come to disagree about which verbs a marker means.
    """
    found: list[str] = []
    for family in verbs.ROADS.values():
        if family.marker != verbs.ANY_MARKER and getattr(model, family.marker, False):
            found.extend(verb for verb in family.grants if verb not in found)
    return tuple(found)


def _pattern_matches(pattern: str, action: str) -> bool:
    """A role pattern against a key. **Reserved keys match nothing.**"""
    if action in RESERVED_PERMISSIONS:
        return False
    return fnmatchcase(action, pattern)


def _build() -> tuple[dict[str, Permission], dict[str, str]]:
    """The whole vocabulary and the rename table, in one pass, in order."""
    kinds = kind_registry()
    prose = action_prose()
    registry = policies()

    renames = _discover_renames()
    aliases = set(renames)

    words: dict[str, Permission] = {}

    # 1 · derived — four verbs per kind, plus the verbs each family marker the
    #     kind's model declares (`Archivable` → `archive`, `restore`; read off
    #     `core.verbs.ROADS`, never typed here), the sentence overridable by prose.
    for kind, model in kinds.items():
        for verb in (*CRUD_VERBS, *family_verbs(model)):
            action = f"{kind}.{verb}"
            words[action] = Permission(
                action=action,
                sentence=prose.get(action) or _derived_sentence(model, verb),
                kind=kind,
                verb=verb,
                app=model._meta.app_label,
                decided_by="derived",
                is_read=verb == "read",
                conforms=True,
                predicate=registry.get(action),
            )

    # 2 · declared — every prose key that is neither a derived key's sentence
    #     override nor the old half of a rename.
    for config, declared in _declarations("policies", "ACTION_PROSE"):
        for raw, sentence in declared.items():
            action = str(raw)
            if action in words or action in aliases:
                continue
            kind, verb, why = _classify(action, kinds)
            words[action] = Permission(
                action=action,
                sentence=str(sentence),
                kind=kind,
                verb=verb,
                app=config.label,
                decided_by="declared",
                is_read=verb == "read",
                conforms=not why,
                non_conformance=why,
                predicate=registry.get(action),
            )

    # 3 · reserved — `core`'s own. Declared last so nothing can shadow one.
    for action, sentence in RESERVED_PERMISSIONS.items():
        kind, _, verb = action.partition(".")
        words[action] = Permission(
            action=action,
            sentence=sentence,
            kind=kind,
            verb=verb,
            app="core",
            decided_by="reserved",
            is_read=False,
            conforms=True,
            default_roles=(OWNER_ROLE,),
            predicate=registry.get(action),
        )

    _validate_renames(renames, words)
    _attach_renames(renames, words)
    _attach_default_roles(words)
    return words, renames


def _discover_renames() -> dict[str, str]:
    found: dict[str, str] = {}
    declarers: dict[str, str] = {}
    for config, declared in _declarations("policies", "RENAMED_PERMISSIONS"):
        for raw_old, raw_new in declared.items():
            old, new = str(raw_old), str(raw_new)
            if old in found and found[old] != new:
                raise ImproperlyConfigured(
                    f"{declarers[old]} and {config.name}.policies both rename {old!r}, to "
                    f"{found[old]!r} and {new!r}. One old key has one successor."
                )
            found[old] = new
            declarers[old] = f"{config.name}.policies"
    return found


def _validate_renames(renames: Mapping[str, str], words: Mapping[str, Permission]) -> None:
    for old, new in renames.items():
        if new in renames:
            raise ImproperlyConfigured(
                f"`RENAMED_PERMISSIONS` renames {old!r} to {new!r}, which is itself renamed to "
                f"{renames[new]!r}. A chain is a rename nobody can reason about: name the "
                "successor that exists."
            )
        if new not in words:
            raise ImproperlyConfigured(
                f"`RENAMED_PERMISSIONS` renames {old!r} to {new!r}, which is not in the "
                "vocabulary. An alias onto a key nobody declared is an alias onto silence: "
                "every caller of the old name would fall to the role default with nothing "
                "saying so."
            )


def _attach_renames(renames: Mapping[str, str], words: dict[str, Permission]) -> None:
    from collections import defaultdict

    sources: dict[str, list[str]] = defaultdict(list)
    for old, new in renames.items():
        sources[new].append(old)
    for new, olds in sources.items():
        words[new] = replace_permission(words[new], renamed_from=tuple(sorted(olds)))


def replace_permission(permission: Permission, **changes: Any) -> Permission:
    """A `Permission` with fields replaced. `dataclasses.replace`, named locally."""
    from dataclasses import replace

    return replace(permission, **changes)


def _discover_default_roles() -> dict[str, frozenset[str]]:
    """Every app's `DEFAULT_ROLES`: "a member may create widgets", said in the app.

    An unknown role key here is NOT an import refusal: a platform app has to
    keep importing in a product that deleted `member` from its own `roles.py`.
    The deploy census is where an entry naming a role nobody declared is
    reported.
    """
    found: dict[str, frozenset[str]] = {}
    for _, declared in _declarations("policies", "DEFAULT_ROLES"):
        for action, roles in declared.items():
            found[str(action)] = frozenset(str(role) for role in roles) | found.get(
                str(action), frozenset()
            )
    return found


def _attach_default_roles(words: dict[str, Permission]) -> None:
    """Who holds each key by default, in the order `architecture.md` states it.

    (1) `owner` always; (2) every declared role whose patterns match; (3) every
    `DEFAULT_ROLES` entry naming the key; **(4) retired by ADR core-27
    (R1-F2)**; **(5) retired** (the compat residue: a platform key with
    a predicate and no declaration offered to every `staff` role, the predicate
    narrowing); (6) otherwise `owner` and pattern matches only. The numbering
    keeps its gaps on purpose, so a missing clause reads as a retirement rather
    than as a typo. So the column equals `defaults_for(role)` for every declared
    role: a key with a predicate and no declaration is offered to nobody by
    default, and a product role that needs one declares it.

    **What (4) was, and why its retirement changes nothing for the template.**
    It said *a `.read` key is free to every membership until reads become
    permissions, so every role has it* — true while `allows` short-circuited
    every read, and a clause written for a phase that ended (rule 30's class).
    It outlived the flip: a declared role naming only write patterns still read
    every kind on every door, which is the exact opposite of ADR core-27's
    "a custom role reads nothing until its collection names reads" one layer
    down. The template observes nothing because its own declarations already
    say it — `admin` is `("*",)` and `member` is `("*.read",)`, so clause (2)
    gives both of them every read they had.

    DOES NOT COVER — declared: a tenant's CUSTOM roles. Those are rows, and the
    vocabulary is computed at import with no database; this column is the CODE
    layer's answer, which is the one an instrument can print for a deployment
    it has never connected to.
    """
    declared_roles_ = role_declarations()
    additions = _discover_default_roles()
    every_role = frozenset(declared_roles_)
    for action, permission in list(words.items()):
        if permission.decided_by == "reserved":
            continue
        holders = {OWNER_ROLE}
        holders |= {
            key
            for key, role in declared_roles_.items()
            if any(_pattern_matches(pattern, action) for pattern in role.permissions)
        }
        holders |= {role for role in additions.get(action, frozenset()) if role in every_role}
        words[action] = replace_permission(permission, default_roles=tuple(sorted(holders)))


def vocabulary() -> Mapping[str, Permission]:
    """Every permission this deployment has. Computed once, then cached.

    Every key's `default_roles` is the declaration's: `owner`, pattern matches, `DEFAULT_ROLES`.
    Read-only on purpose: a call site that could add a key would be a second
    owner of the vocabulary, which is the defect this whole shape is against.
    """
    global _words, _renames
    if _words is None:
        _words, _renames = _build()
    return MappingProxyType(_words)


def grantable_permissions() -> frozenset[str]:
    """Every key that may appear in a COLLECTION: the vocabulary minus the virtual kinds.

    **The one exclusion, in one place.** A virtual kind (`VIRTUAL_KINDS`) names
    no table — the installation itself is not a row anybody can be given
    authority over — so a key on one is answered by its predicate and by nothing
    else, and it belongs in nobody's collection: not `owner`'s, not a declared
    role's, not a pattern's expansion, not a `Role` row a tenant wrote.

    It lives here rather than at each reader because the readers disagreed
    exactly once and the cost was the ceiling. `_collection_from_rows` excluded
    virtual kinds for `owner` alone, so the first key to land on a virtual kind
    made a declared role hold something the owner did not — and
    `_refuse_handing_out`, which is `collection(role) - collection(owner)`,
    refused AN OWNER granting `admin`. The kind had been declared with zero keys
    on it, so nothing exercised the asymmetry until one arrived. Three readers
    now ask this one function: `_collection_from_rows` (both branches),
    `defaults_for` (the declared-role branch), and
    `core.services._expand_patterns`, which turns `"*"` into rows.

    **`owner`'s DEFAULTS are deliberately not routed through here**, and the
    difference is not an oversight. `defaults_for(OWNER_ROLE)` answers "what IS
    the owner role" — the whole vocabulary, present and future, the reserved
    verb included — which is a definition and not a set anybody may be handed.
    What an owner HOLDS is `collection()`, and that is filtered.
    """
    words = vocabulary()
    if not VIRTUAL_KINDS:
        return frozenset(words)
    return frozenset(action for action, word in words.items() if word.kind not in VIRTUAL_KINDS)


def non_conforming() -> Mapping[str, str]:
    """The census: every key that does not fit the shape, and why. A RATCHET.

    Every one of these answers today exactly as it answered yesterday — the
    policy lookup is untouched and a non-conforming key is still in the
    vocabulary. What the census says is that the key cannot be reasoned about
    by shape: its kind is not a model, or its verb is a second spelling of one
    of the four.

    **This list shrinks and never grows.** Each name belongs to an app whose
    sweep is its own step; the last sweep flips the list to empty. The pin is
    `apps/core/tests/test_vocabulary.py`, which spells the names, so a new
    non-conforming key fails there by name rather than moving a number.
    """
    return MappingProxyType(
        {
            action: permission.non_conformance
            for action, permission in sorted(vocabulary().items())
            if not permission.conforms
        }
    )


def renamed_permissions() -> Mapping[str, str]:
    """Old key → new key, discovered from every app's `policies.py`.

    The alias under the immutable key: a product's `require(actor,
    "organization.rename", org)` answers as `organization.update` for one
    release, with one deprecation printed, and `manage.py rename_permission`
    is what rewrites the rows.
    """
    global _words, _renames
    if _renames is None:
        _words, _renames = _build()
    return MappingProxyType(_renames)


def resolve_renamed(action: str) -> str:
    """The successor of a renamed key, announced once per process.

    Resolved BEFORE the policy lookup, which is the whole point: no window
    opens in which an old key finds no policy and falls to the role default.
    """
    renames = renamed_permissions()
    new = renames.get(action)
    if new is None:
        return action
    if action not in _announced:
        _announced.add(action)
        log.warning("core.authz.renamed", old=action, new=new)
    return new


def role_declarers() -> Mapping[str, str]:
    """Role key → the app label that declared it. What an instrument prints."""
    role_declarations()
    return MappingProxyType(dict(_role_apps))


def role_declarations() -> Mapping[str, DeclaredRole]:
    """Every app's `roles.py::ROLES`, merged. Discovered once, then cached.

    Discovered exactly as policies are — drop `apps/<x>/roles.py` and the roles
    count — because a product declaring its own roles should no more edit
    `core` than a product declaring its own policies does.
    """
    global _roles
    if _roles is None:
        _roles = _discover_roles()
    return MappingProxyType(_roles)


def _discover_roles() -> dict[str, DeclaredRole]:
    found: dict[str, DeclaredRole] = {}
    declarers: dict[str, str] = {}
    _role_apps.clear()
    for config, declared in _declarations("roles", "ROLES"):
        module_name = f"{config.name}.roles"
        for raw_key, role in declared.items():
            key = str(raw_key)
            if not isinstance(role, DeclaredRole):
                raise ImproperlyConfigured(
                    f"{module_name} declares {key!r} as {type(role).__name__}, not a "
                    "`DeclaredRole`. The declaration is what the platform reads; a dict or "
                    "a string is a shape it would have to guess at."
                )
            if role.key != key:
                raise ImproperlyConfigured(
                    f"{module_name} files {role.key!r} under the key {key!r}. One role has "
                    "one key: the dict key and the declaration have to agree, or half the "
                    "tree reads one and half reads the other."
                )
            if key == OWNER_ROLE:
                raise ImproperlyConfigured(
                    f"{module_name} declares the role {OWNER_ROLE!r}, which is the platform's. "
                    "`owner` IS the vocabulary — every key, present and future — and a "
                    "declaration that narrowed it would be a ceiling quietly disappearing."
                )
            if key in RESERVED_PERMISSIONS:
                raise ImproperlyConfigured(
                    f"{module_name} declares a role keyed {key!r}, which is a reserved "
                    "permission. A role key and a permission key are different vocabularies "
                    "and one name in both is a name two readers disagree about."
                )
            if key in declarers:
                raise ImproperlyConfigured(
                    f"{declarers[key]} and {module_name} both declare the role {key!r}. "
                    "Two apps declaring one role is two collections under one name, and "
                    "which one a membership gets would depend on import order."
                )
            declarers[key] = module_name
            _role_apps[key] = config.label
            found[key] = role
    return found


def default_role_key() -> str:
    """The role a new membership gets when nobody says otherwise, or `""`."""
    marked = sorted(
        key for key, role in role_declarations().items() if role.is_default_for_new_members
    )
    if len(marked) > 1:
        raise ImproperlyConfigured(
            f"More than one declared role is marked `is_default_for_new_members`: {marked}. "
            "The role a new member gets is one answer or none."
        )
    return marked[0] if marked else ""


def defaults_for(role_key: str) -> frozenset[str]:
    """Every permission a role holds by default — patterns matched, plus additions.

    `owner` is the whole vocabulary by definition, the reserved verb included;
    every declared role is its patterns over the GRANTABLE vocabulary (reserved
    keys match nothing, and neither does a virtual kind) plus every
    `DEFAULT_ROLES` entry naming it; a role nobody declared holds nothing, which
    is what makes a membership carrying a key no deployment has hold nothing
    rather than everything.

    **A declared role's half goes through `grantable_permissions()`** — the one
    exclusion — so that this function and `collection()` cannot disagree about
    what a role has. They disagreed once, about virtual kinds, and the cost is
    written up there. `owner` is the exception and stays the whole vocabulary,
    because this answers what the owner role IS rather than what anybody may be
    handed; `collection(OWNER_ROLE)` is the second question and it is filtered.
    """
    words = vocabulary()
    if role_key == OWNER_ROLE:
        return frozenset(words)
    role = role_declarations().get(role_key)
    if role is None:
        return frozenset()
    grantable = grantable_permissions()
    held = {
        action
        for action in grantable
        if any(_pattern_matches(pattern, action) for pattern in role.permissions)
    }
    held |= {
        action
        for action, roles in _discover_default_roles().items()
        if role_key in roles and action in grantable
    }
    return frozenset(held)


# =============================================================================
# Resolution — what one person holds in one place (ADR core-25, blueprint §2)
# =============================================================================
#
# Three layers meet here and each is read exactly once:
#
#   1. **code** — `owner` IS the vocabulary; a declared role is its patterns
#      over the vocabulary, plus what an app's `DEFAULT_ROLES` adds
#      (`defaults_for`; the compat residue retired with clause (5)).
#   2. **the tenant's rows** — a `RolePermission` include adds a key to a role,
#      an exclude takes one away; a custom role's includes ARE its collection.
#   3. **the person's rows** — a `Grant` allow adds one key to one membership,
#      a withhold takes one away. **A withhold beats everything** ("forbid
#      overrides permit"), because the alternative is a subtraction somebody
#      undoes by being given something.
#
def _collection_from_rows(
    role_key: str,
    rows: Iterable[tuple[str, str]],
) -> frozenset[str]:
    """One role's collection, given its `(effect, permission)` delta rows.

    Split from `collection()` so that `effective_permissions` can read every
    role on the chain out of ONE query rather than one query per role — the
    three-statement budget is the reason this seam exists at all.
    """
    grantable = grantable_permissions()
    if role_key == OWNER_ROLE:
        # `owner` IS the vocabulary, present and future, the reserved verb
        # included — minus the virtual kinds, which name no row anybody can be
        # given authority over (`grantable_permissions`, the one exclusion). No
        # row reshapes it: a delta on "everything" would be a ceiling
        # disappearing quietly, and `set_role_collection` refuses `owner` at the
        # door for the same reason.
        return grantable
    if not role_key:
        # The roleless membership. It holds nothing beyond its own grants —
        # which is a state the system reaches and never a state a door sets.
        return frozenset()
    if role_key in role_declarations():
        base = defaults_for(role_key)
    else:
        # A CUSTOM role, or a key no deployment declares: its collection is
        # exactly its include rows, and an unknown key therefore holds nothing
        # rather than everything. No query is needed to tell the two apart —
        # a key with no rows and no declaration holds ∅ either way.
        base = frozenset()
    reserved = set(RESERVED_PERMISSIONS)
    include = {
        permission
        for effect, permission in rows
        if effect == RolePermission.Effect.INCLUDE and permission not in reserved
    }
    exclude = {permission for effect, permission in rows if effect == RolePermission.Effect.EXCLUDE}
    return frozenset((base | include) - exclude)


def collection(tenant: Tenant | None, role_key: str) -> frozenset[str]:
    """Every permission a role holds **in this tenant**. One query, or none.

    `owner` → the vocabulary minus the virtual kinds · a declared key → what
    the code layer gives it, plus this tenant's include rows, minus its exclude
    rows · a custom key → its include rows · an unknown key or `""` → nothing.

    A reserved key (`tenant.own`) is never added by an include row: only
    `owner` holds one, and that is the whole of every ceiling the rank table
    used to enforce.
    """
    if role_key == OWNER_ROLE or not role_key or tenant is None:
        return _collection_from_rows(role_key, ())
    rows = RolePermission.objects.for_tenant(tenant).filter(role_key=role_key)
    return _collection_from_rows(role_key, list(rows.values_list("effect", "permission")))


def _memo_box(
    user: AbstractBaseUser | None,
    tenant: Tenant | None,
    memo: Actor | None,
) -> dict[str, Any]:
    """Where the raw rows live for THIS question: the actor's own box, or a fresh one.

    **The identity gate, and it is the whole of "the wall reads the target
    uncached".** An actor's memo is about exactly one person in exactly one
    tenant — the person the actor IS. A question about anybody else (the target
    of a hand-out, the membership a wall is measuring, a census over three
    people) gets an empty throwaway dict, reads the tables, and writes nothing
    back. So a caller may pass `memo=actor` unconditionally and still be asking
    the database whenever the subject is not the actor: the caching decision is
    made here, once, rather than at every call site that might forget.
    """
    if memo is None:
        return {}
    identity = (getattr(user, "pk", None), getattr(tenant, "pk", None))
    own = (memo.user_id, memo.tenant.pk if memo.tenant is not None else None)
    if identity != own:
        return {}
    return memo._permission_rows


def _grant_rows(
    tenant: Tenant | None,
    memberships: Sequence[Membership],
) -> dict[Any, tuple[tuple[str, str], ...]]:
    """Every grant on every one of this person's memberships, **by membership**.

    Keyed by membership rather than flattened because the rows are cached
    `at`-independently and the ALGEBRA still narrows to the chain: a withhold on
    a membership in a sibling branch must not subtract at the hat, which is what
    a flat list of `(permission, effect)` pairs would silently do.
    """
    rows: dict[Any, list[tuple[str, str]]] = {membership.pk: [] for membership in memberships}
    for membership_id, permission, effect in (
        Grant.objects.for_tenant(tenant)
        .filter(membership__in=memberships)
        .values_list("membership_id", "permission", "effect")
    ):
        rows.setdefault(membership_id, []).append((permission, effect))
    return {key: tuple(value) for key, value in rows.items()}


def _delta_rows(
    tenant: Tenant | None,
    memberships: Sequence[Membership],
) -> dict[str, tuple[tuple[str, str], ...]]:
    """The `RolePermission` deltas for every role key this person's memberships name.

    One statement for every role on every membership, or none when they are all
    roleless — the same shape `collection()` reads one role at a time, read here
    for the whole chain at once because three statements is the budget.
    """
    keys = sorted({str(membership.role) for membership in memberships if membership.role})
    deltas: dict[str, list[tuple[str, str]]] = {key: [] for key in keys}
    if keys:
        rows = (
            RolePermission.objects.for_tenant(tenant)
            .filter(role_key__in=keys)
            .values_list("role_key", "effect", "permission")
        )
        for role_key, effect, permission in rows:
            deltas.setdefault(role_key, []).append((effect, permission))
    return {key: tuple(value) for key, value in deltas.items()}


def effective_permissions(
    user: AbstractBaseUser | None,
    tenant: Tenant | None,
    at: Organization | None = None,
    *,
    memo: Actor | None = None,
) -> frozenset[str]:
    """What this person may do at this node. **Three statements, whatever the data.**

    `at` is the node the question is about. The memberships that count are the
    ones whose organization **is `at` or an ancestor of it** — roles inherit
    downwards and nothing else: a branch admin is not a group admin and never
    sees a sibling. `at=None` counts every membership the person holds in the
    tenant — each one's chain — for a caller with no hat and no object (a
    command, a test). It is not a plain union: a withhold on ANY branch
    membership subtracts tenant-wide, so it fails closed, as `visible_to` does.

    The algebra, in order: every membership on the chain contributes its role's
    collection and its `allow` grants; every `withhold` grant anywhere on the
    chain then subtracts. A withhold on the branch beats an allow at the root.

    **The three statements** are the memberships, their grants, and the delta
    rows for the role keys they name — each table read once, with the set
    algebra done in Python.

    **`memo` is an `Actor` offering its own memo, and it is the actor's rows or
    nothing** (PR0). Hand it the actor whose question this is and the three
    tables are read once for that actor's lifetime, so a second `require` in one
    request pays nothing more; hand it an actor while asking about SOMEBODY ELSE
    — a wall measuring its target, a census walking three people — and it misses
    by identity (`_memo_box`) and reads the tables. The rows held are the RAW
    rows and they are `at`-independent, because the chain filter is Python: one
    fetch answers the question at every node. A miss is the three statements and
    never a widening. `forget_permissions()` on the actor is the one
    invalidation, and the single stale window it leaves is written down on the
    slot itself (`core.actor.Actor._permission_rows`).

    **When the thing is absent:** no user, no tenant, no membership on the
    chain, **or a node belonging to another tenant** → `frozenset()`. An
    unresolved scope holds nothing, never everything.

    **The foreign-node check is FIRST, before the memo and before any query**
    (R1-F4). Two tenants' trees are unrelated strings that happen to share a
    grammar: every tenant's root is path `"0000"`, so `is_descendant_path` said
    *yes* to a question it had no business answering and an owner of one tenant
    resolved as an owner of another's root. The comparison is a tenant id, it
    costs nothing, and it runs before `_memo_box` so a foreign question never
    touches — or fills — the actor's own memo.
    """
    if tenant is None or (at is not None and at.tenant_id != tenant.pk):
        return frozenset()
    box = _memo_box(user, tenant, memo)
    memberships: tuple[Membership, ...] | None = box.get("memberships")
    if memberships is None:
        memberships = tuple(memberships_in(user, tenant))
        box["memberships"] = memberships
    chain = list(chain_over(memberships, at))
    if not chain:
        # The early return is BEFORE the other two statements and stays there:
        # a person with no membership over this node costs one query today and
        # must keep costing one, memo or no memo.
        return frozenset()
    if "grants" not in box:
        box["grants"] = _grant_rows(tenant, memberships)
        box["deltas"] = _delta_rows(tenant, memberships)
    by_membership: dict[Any, tuple[tuple[str, str], ...]] = box["grants"]
    deltas: dict[str, tuple[tuple[str, str], ...]] = box["deltas"]
    grants = [pair for membership in chain for pair in by_membership.get(membership.pk, ())]

    reserved = set(RESERVED_PERMISSIONS)
    allowed: set[str] = set()
    for membership in chain:
        key = str(membership.role)
        allowed |= _collection_from_rows(key, deltas.get(key, ()))
    allowed |= {
        permission
        for permission, effect in grants
        if effect == Grant.Effect.ALLOW and permission not in reserved
    }
    withheld = {permission for permission, effect in grants if effect == Grant.Effect.WITHHOLD}
    return frozenset(allowed - withheld)


def where_of(actor: Actor, obj: Any = None) -> Organization | None:
    """**The node the question is about.** Down only, and never sideways.

    An `Organization` is its own node; a row that names one is asked at the
    node it names; anything else falls back to the hat. No hat and no
    object is `None`, which `effective_permissions` reads as the tenant-wide
    union — the abstract question, asked by a command or a test.

    It never walks upward and never widens: a row in a sibling branch resolves
    to the sibling, where the actor holds nothing, and the answer is no.
    """
    if isinstance(obj, Organization):
        return obj
    org = getattr(obj, "organization", None)
    if isinstance(org, Organization):
        return org
    return actor.org


def holds(actor: Actor, permission: str, at: Organization | None = None) -> bool:
    """Whether this actor's effective set at `at` contains this key. The DATA half.

    It answers "what does this person hold here" and nothing else — no
    predicate, no row. A policy that needs "how much authority does this person
    have over that branch" calls this rather than reading a role by value.
    """
    where = at if at is not None else where_of(actor, None)
    return permission in effective_permissions(actor.user, actor.tenant, where, memo=actor)


def read_kinds(
    user: AbstractBaseUser | None,
    tenant: Tenant | None,
    at: Organization | None = None,
    *,
    memo: Actor | None = None,
) -> frozenset[str]:
    """**The kinds this person may read at this node**, as kinds rather than keys.

    The `.read` half of `effective_permissions`, mapped through the vocabulary
    from `"<kind>.read"` to `"<kind>"`. **One derivation, in `core`, consumed by
    three callers that would otherwise each write their own** (lead decision 9):
    the socket's read set at connect (PR3), the tenant archive's walk over the
    requester's readable kinds (PR4.e) and search's `kinds ∩ readable` (PR4.g).
    Three re-derivations of one sentence is how two doors come to disagree, and
    rule 46 is the rule that disagreement breaks.

    A key whose verb is not `read` is not in the answer, and a non-conforming
    read spelling (`usage.read_report` and its siblings, until each app's sweep
    renames it) is not either: `Permission.is_read` is the census's own field
    and this reads it rather than re-deciding what a read looks like.

    **When the thing is absent:** no user, no tenant, or nothing held at `at` →
    `frozenset()`. An unresolved scope reads nothing, never everything — the
    same fail-closed shape as `effective_permissions`, which it is one line over.
    """
    words = vocabulary()
    held = effective_permissions(user, tenant, at, memo=memo)
    kinds: set[str] = set()
    for action in held:
        word = words.get(action)
        if word is not None and word.is_read:
            kinds.add(word.kind)
    return frozenset(kinds)


def read_kinds_by_node(
    user: AbstractBaseUser | None,
    tenant: Tenant | None,
) -> dict[Any, frozenset[str]]:
    """`read_kinds` at **every node this person holds a membership on**. Three statements.

    The `before`/`after` shape the narrowing kick compares
    (`core.services.kick_if_reads_narrowed`). **Per node, and that is the whole
    reason it is not one set:** a read is held *at a node*, so an admin at A
    demoted at A1 keeps every read at A and loses them below — a tenant-wide
    union would show no change and kick nobody.

    It costs **three statements whatever the number of nodes**, because it
    builds one throwaway probe actor and hands its memo to every call: the rows
    are `at`-independent, so the first node pays for all of them. The probe is
    local and dies here — it is never an authorization decision, only the
    carrier of one fetch.

    **When the thing is absent:** no membership in this tenant → `{}`, and
    comparing two empty maps narrows nothing.
    """
    probe = actor_for(user=user, tenant=tenant)
    box = _memo_box(user, tenant, probe)
    memberships: tuple[Membership, ...] | None = box.get("memberships")
    if memberships is None:
        memberships = tuple(memberships_in(user, tenant))
        box["memberships"] = memberships
    return {
        membership.organization.pk: read_kinds(user, tenant, membership.organization, memo=probe)
        for membership in memberships
    }


# =============================================================================


# deprecated v2.1 → removed v3.0. Ranks are how the ceilings were enforced
# before `tenant.own` was a reserved key nobody but an owner holds; a custom
# role ranks 0 here, which is why the comparison had to stop being the wall.
def rank(role: str | None) -> int:
    """A role as a number. `None` — no membership at all — is 0."""
    return ROLE_RANK.get(str(role), 0) if role is not None else 0


def memberships_in(user: AbstractBaseUser | None, tenant: Tenant | None) -> list[Membership]:
    """Every membership this user holds in this tenant, org rows attached.

    One query, and it is the only one the hierarchy costs on the read path: a
    person holds a handful of memberships, the ancestor test is a string
    comparison in Python, and neither grows with the size of the tree.
    """
    if user is None or tenant is None:
        return []
    return list(Membership.objects.for_tenant(tenant).of(user).select_related("organization"))


@road("role_chain", example="apps/core/authz.py::effective_permissions")
def chain_over(memberships: Iterable[Membership], at: Organization | None) -> Iterator[Membership]:
    """The memberships that reach `at`: held ON it or on one of its ancestors.

    **Roles inherit downwards only**, so a membership counts over a node when
    the node is the membership's own organization or lies underneath it —
    never the reverse: a membership on a child does not reach its parent.
    One prefix test per row, in Python, over rows the caller already read
    (`memberships_in`), so asking costs no query.

    `at=None` is the tenant-wide question — no node named — and every
    membership answers it; that is the reading every caller had before this
    was one function. The tenant check is the CALLER's and comes first: every
    tenant's root is `"0000"`, so this comparison cannot tell two tenants'
    trees apart and must never be asked across them.
    """
    for membership in memberships:
        if at is None or is_descendant_path(at.path, membership.organization.path):
            yield membership


def effective_role(
    user: AbstractBaseUser | None,
    tenant: Tenant | None,
    org: Organization | None = None,
) -> str | None:
    """The best role this person holds **over** `org`. `None` when they hold none.

    **deprecated v2.1 → removed v3.0.** "How much authority" is a question with
    one answer now — `effective_permissions(user, tenant, at)` — and a role KEY
    is no longer a number that can be compared: a tenant's own `approver` ranks
    0 beside `member`, so the best-ranked key is not the strongest collection.
    Kept because every un-swept `policies.py` still reads it and because the
    template's three keys still rank as they did; ties among custom keys break
    to the NEAREST ancestor membership, which is the honest reading of "best"
    when the ranks say nothing.

    *Over*, not *at*: **roles inherit downwards.** An owner of the group is an
    owner of every branch beneath it without a row per branch, because the
    alternative — a membership per node — is a permission system that goes
    stale the first time somebody opens a new branch. The rule is one sentence:
    the best role among the memberships whose organization is an **ancestor of,
    or is,** the org in question.

    Nothing inherits upwards or sideways. A branch admin is not a group admin
    and never sees a sibling; `architecture.md` allows the exception only as an
    explicit policy with a named reason, and there is none in the template.

    `org=None` means *anywhere in this tenant* — the best role they hold in it
    at all. That is the honest answer for a caller with no hat resolved (a
    management command, a test, a service called with a bare tenant), and it is
    deliberately **not** what visibility does: `visible_to(None)` returns
    nothing. Authorization asks "may this person do this kind of thing here";
    visibility asks "which rows", and the second is the one that must fail
    closed.
    """
    # A node of ANOTHER tenant is not a node this person holds anything over,
    # and the path comparison below cannot tell — every tenant's root is
    # `"0000"` (R1-F4). The shim answers `None`, exactly as it does for somebody
    # with no membership on the chain.
    if tenant is None or (org is not None and org.tenant_id != tenant.pk):
        return None
    chain = list(chain_over(memberships_in(user, tenant), org))
    if not chain:
        return None
    # Best rank, and **ties break to the nearest ancestor** — the longest path
    # on the chain. Every key a deployment declares outside the template's
    # three ranks 0, so a person holding two custom roles on one chain used to
    # get whichever row the database happened to return first. "Nearest" is the
    # only honest reading of "best" when the ranks say nothing.
    best = max(
        chain, key=lambda membership: (rank(membership.role), len(membership.organization.path))
    )
    return str(best.role)


def actor_role(actor: Actor, org: Organization | None = None) -> str | None:
    """The acting user's effective role, under their own hat unless told otherwise.

    deprecated v2.1 → removed v3.0, with `effective_role` and for its reason.
    """
    return effective_role(actor.user, actor.tenant, org if org is not None else actor.org)


def membership_for(actor: Actor) -> Membership | None:
    """The acting user's best membership in the acting tenant, if there is one.

    **deprecated v2.1 → removed v3.0.** `allows` no longer calls it: what a
    person may do is `effective_permissions`, which reads every membership on
    the chain rather than picking the strongest one. A predicate that wants
    "does this person belong here at all" keeps working; one that wants "how
    much authority" wants `holds(actor, key, at=...)`.

    "Best" rather than "first" since a person may hold several in one tenant:
    the one that answers "what may they do here" is the strongest, and picking
    an arbitrary row would make the answer depend on insertion order. It is
    narrowed to the hat's ancestors when there is a hat — a policy asking
    `membership_for` while acting as a branch gets the branch's answer, not the
    group's.
    """
    if actor.user is None or actor.tenant is None:
        return None
    # The memberships the actor already caches (`_memo_box` — the rows
    # `effective_permissions` reads, on the actor's own memo): a predicate asking
    # "is this person a member here" per ROW of a page used to read the table
    # once per row; it reads it once per actor now, whichever of the two asks
    # first. The same raw rows, the same `forget_permissions()` invalidation.
    box = _memo_box(actor.user, actor.tenant, actor)
    memberships: tuple[Membership, ...] | None = box.get("memberships")
    if memberships is None:
        memberships = tuple(memberships_in(actor.user, actor.tenant))
        box["memberships"] = memberships
    candidates = list(chain_over(memberships, actor.org))
    if not candidates:
        return None
    return max(candidates, key=lambda membership: rank(membership.role))


def is_member(actor: Actor, obj: Any = None) -> bool:
    """Whether the actor holds any membership reaching its hat in the acting tenant; a `Policy`.

    Not a role read (rule 54 (c)) and not reach (`may_be_named`): `obj` is accepted and unread.
    """
    return membership_for(actor) is not None


def is_read(action: str) -> bool:
    """True when the action's verb is one a `member` may perform by default.

    **deprecated v2.1 → removed v3.0, and READ BY NOTHING since Phase R.**
    `allows` used to consult it for the free-read branch; that branch is gone
    (ADR core-27) and a read is now resolved by the same three layers as any
    other key. `read` is THE read verb and `Permission.is_read` is the census's
    answer (`verb == "read"`); the other three spellings are non-conforming keys
    their own app's sweep renames.
    """
    _, _, verb = action.rpartition(".")
    return verb == "read" or verb in READ_ALIAS_VERBS


def allows(actor: Actor, action: str, obj: Any = None) -> bool:
    """Whether this actor may do this, without raising. `require` is the usual call.

    **Seven steps, and the order is the whole rule** (blueprint §2):

    1. `system` is the product acting for itself — a workflow, a schedule, a
       command. There is no membership to consult and no person to ask, and
       the tenancy is still enforced by the scoped manager on every read.
       **Unless the key's predicate declared `refuses_system`** — then the
       system actor gets that predicate's own answer (`core.policies.
       may_archive` is the first: an archive is an admin's press, and a
       workflow is nobody's admin).
    2. **Where** — `where_of(actor, obj)`: the node the object names, the
       hat when it names none, and the tenant-wide union when there is
       neither.
    3. **Vocabulary** — an alias resolves first (one line, deliberately BEFORE
       the lookup: a renamed key resolved after it would find no policy and
       fall to the role default, which is the silent widening the rename
       exists to avoid). A key nobody declared is refused and logged, because
       the safe reading of a word the deployment has never heard of is no —
       and an owner's "everything" is the VOCABULARY, not every string.
    4. **The data half** — `effective_permissions(user, tenant, at, memo=actor)`.
       The actor carries the memo, so the second question in one request is
       free and the pin says so (`test_resolution.py`); the memo answers for
       the actor's own identity and nothing else.
    5. Not held → no.
    6. **The code half** — the app's predicate, if it wrote one. A predicate's
       no is final, for an owner too: a product writing "nobody reopens a
       closed period" gets to mean it.
    7. `require` turns the no into `Forbidden` with the key's own sentence.

    **Phase R: a `.read` key is a key like any other** (ADR core-27). The free
    branch that let any membership in the tenant read anything is gone: a read
    is held by `owner` (the vocabulary), by `admin` (`*`), by `member`
    (`*.read`), by whatever a custom role includes and by an `allow` grant —
    and a `withhold` subtracts it exactly as it subtracts a write. **`visible_to`
    still decides WHICH rows** (rule 24, BVB-4); this decides WHETHER this kind,
    here, and the selector asks it once (§C6). A membership with no role reads
    nothing. `is_read()` survives as a deprecated shim that nothing in this
    function reads.

    **A key whose KIND names no row skips the data half**, for the reason the
    virtual kinds are virtual: there is nothing for a collection to be about.
    `deployment` is the declared case — configuring the installation is a
    platform-operator act with no tenant, no membership and no row — and the
    census's un-swept non-conforming keys (`identity_platform.configure`,
    `usage.read_report`, `workflow.signal`) are the same shape without the
    declaration, so the app's predicate is the whole rule for them exactly as
    it is today. It shrinks to the declared list as each app's sweep gives its
    keys a real kind. **A kindless key with no predicate has no rule at all and
    falls to the data half**, where it is refused to everyone the role patterns
    do not reach — silence is still no.
    """
    if actor.kind == "system":
        # Exempt unless the key's predicate declared `refuses_system`; then its
        # own answer. Renames resolve first, as below.
        declared_predicate = policies().get(resolve_renamed(action))
        if declared_predicate is None or declared_predicate not in _refuses_system:
            return True
        return bool(declared_predicate(actor, obj))

    at = where_of(actor, obj)
    action = resolve_renamed(action)

    permission = vocabulary().get(action)
    if permission is None:
        log.warning("core.authz.undeclared", action=action, actor_kind=actor.kind)
        return False

    policy = policies().get(action)
    kindless = permission.kind in VIRTUAL_KINDS or permission.kind not in kind_registry()
    if kindless and policy is not None:
        # Nothing to hold a collection over: the predicate is the whole rule.
        # FIRST, so that a key of this shape costs exactly what it cost before —
        # one lookup, in the predicate itself.
        pass
    elif action not in effective_permissions(actor.user, actor.tenant, at, memo=actor):
        return False

    if policy is None:
        return True
    return bool(policy(actor, obj))


def may_be_named(actor: Actor, obj: Any) -> bool:
    """Whether this actor could have **reached** this row to name it. Fails closed.

    `require` answers "may you do this kind of thing here". This answers a
    different question that used to have no answer at all: **could you have got
    hold of this reference?** A service takes `recipient=`, `policy=`,
    `parent=`; the caller hands over an id; the id resolves to a row in a
    branch the caller has no membership over, and the write lands. Nothing in
    the tenancy catches it, because the row *is* in the tenant; nothing in the
    policy catches it, because the policy is about the verb.

    Two ways to be True, and only two:

    1. **Downward** — the actor's hat covers `obj.organization`'s subtree. The
       ordinary case, and the same direction `visible_to` reads in: a row they
       could have listed is a row they could have named.
    2. **The link gate** — `obj`'s model declared `InheritedDownward` *and*
       `obj.organization` is on the hat's ancestor chain. A branch may name the
       policy its parent set for it, which is a row it could never list. That
       widening is deliberate and it is exactly one model-population wide: the
       edge on the hole is that the caller must already be holding the
       reference, so it discovers nothing (ADR core-4, and `architecture.md`
       A5a on why a hole without edges is the leak).

    Everything else is False, including every unresolved thing: no hat, no
    tenant, a row in another tenant, a row with no organization at all. That is
    the same fail-closed shape `for_tenant(None)` and `visible_to(None)` have —
    an unresolved scope reads and names nothing, rather than everything.

    **No `system` exemption**, unlike `allows()` above. `allows` is asking
    whether a role permits a verb, and the product acting for itself has no
    role to consult; this is asking whether a *specific reference* was
    reachable, and "the product started this workflow" is not an answer to
    that. A platform run that genuinely acts tenant-wide passes `org=None`,
    gets `False` here, and says so at the call site with a recorded
    `# reach:` comment — visible, counted, and reviewable, which is what the
    exemption inside a helper would never have been.

    ## The `# reach:` grammar

    House rule 26 (quality/rules.yaml) reads every FK-target keyword argument
    of a `@service` that writes an `OrgScopedModel` and requires one of two
    things at the call site:

        require(actor, "recipient.update")
        if not may_be_named(actor, recipient):
            raise NotFound()                      # the check, done

        services.record_delivery(recipient=recipient, ...)   # <- the valve line above it

    where the valve line is a comment whose marker is `reach` and whose reason
    follows the colon — "the dispatch workflow acts tenant-wide and holds no
    hat". (Spelled in prose here: an example line opening with the marker would
    be counted as a valve by the standing census, though it excuses nothing.)

    The comment is not a disable. It is a sentence somebody wrote and a
    reviewer can disagree with, it sits on the line it excuses, and the gate
    counts and prints every one of them — a backlog that may shrink and never
    grow. A blanket exemption in this function would have been all of the same
    holes with none of the visibility.

    DOES NOT COVER — declared: whether the *reason* in a `# reach:` comment is
    a good one. The gate counts them and prints them; judging them is review's,
    and the surveyor's lens on the standing total.
    """
    hat = actor.org
    if hat is None or actor.tenant is None:
        return False
    org = getattr(obj, "organization", None)
    if not isinstance(org, Organization):
        return False
    # Same tenant, or nothing else matters: two tenants' trees are unrelated
    # strings and a path comparison across them would be meaningless rather
    # than merely wrong.
    if getattr(obj, "tenant_id", None) != actor.tenant.pk:
        return False
    if is_descendant_path(org.path, hat.path):
        return True
    return is_inherited_downward(type(obj)) and is_descendant_path(hat.path, org.path)


def require(actor: Actor, action: str, obj: Any = None) -> None:
    """Authorize, or raise `Forbidden`. Called by a service before every write.

    It raises rather than returns a boolean because the caller that forgets to
    check a boolean is the caller this exists to catch.

    **What the refused caller is told is prose, not the action name.** The
    sentence comes from `refusal_sentence`, which reads the app's own
    `ACTION_PROSE`; the action name still identifies the check in the audit row
    and in a log line, where the reader is a maintainer.
    """
    if not allows(actor, action, obj):
        raise Forbidden(refusal_sentence(action))
