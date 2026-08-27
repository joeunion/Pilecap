"""Authorization: the service's half of the answer.

**Both layers, with a clear division** (`architecture.md`): the *door*
authenticates and resolves the tenant — a route's `auth=`, an MCP bearer token,
the socket middleware. The *service* authorizes, object by object, through
`require(actor, action, obj)`. A door that contains permission logic is the
same violation from the other side: it means the MCP tool, the activity and the
admin each get their own subtly different copy of the rule.

Two sources, in this order:

1. **Policies — code.** An app's `policies.py` exposes
   `POLICIES: dict[str, Callable[[Actor, Any], bool]]`, keyed `"widget.update"`.
   Discovered, never registered: drop the file and the action is covered.
2. **Roles — data.** `Membership.role` is the fallback when no policy names the
   action: `owner` and `admin` may do anything in their tenant; `member` may
   read and may not write.

That order is the point. Roles answer "how much of this tenant is yours",
which is a small, stable question with three answers; policies answer "may
*this* person do *this* to *that row*", which is unbounded and belongs in code
next to the model it is about. Trying to express the second as more roles is
how a permission system becomes forty checkboxes nobody can reason about.

Beside them, and discovered the same way: **`ACTION_PROSE` — the sentence a
refused caller reads.** An action name is a key, not English; `require` answers
with the app's declared sentence for it and never with the key itself.

**A write with no policy is refused for a member**, not allowed: an action
nobody has written a rule for is an action nobody has thought about, and the
safe reading of silence is no.

**And one question neither of them asks.** `require` answers "may you do this
kind of thing here"; the scoped manager answers "whose rows are these". Neither
answers "could you have got hold of *that* reference" — the foreign key handed
to a service by id, resolving to a row in a branch the caller holds no
membership over. That is `may_be_named(actor, obj)`, below, with its own
`# reach:` override grammar and its own house rule (26) reading the call sites.
"""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from django.apps import apps as django_apps
from django.contrib.auth.base_user import AbstractBaseUser

from apps.core.actor import Actor
from apps.core.exceptions import Forbidden
from apps.core.models import (
    Membership,
    Organization,
    Tenant,
    is_descendant_path,
    is_inherited_downward,
)

Policy = Callable[[Actor, Any], bool]

# The verbs a `member` may perform without a policy saying so. Everything else
# is a write, and a write needs either a privileged role or a policy.
READ_VERBS = frozenset({"view", "read", "list", "get"})

# Roles, ordered. The order is what makes "no grant above your own" a
# comparison rather than a table of special cases, and it is the only place in
# the tree that says one role outranks another — a product that adds a fourth
# role adds it here and nowhere else.
ROLE_RANK: dict[str, int] = {
    Membership.Role.MEMBER: 1,
    Membership.Role.ADMIN: 2,
    Membership.Role.OWNER: 3,
}
# The rank a grant must not exceed, and the floor for "may administer".
ADMIN_RANK = ROLE_RANK[Membership.Role.ADMIN]

_registry: dict[str, Policy] | None = None
_prose: dict[str, str] | None = None


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
    for config in django_apps.get_app_configs():
        if not config.name.startswith("apps."):
            continue
        module_name = f"{config.name}.policies"
        if importlib.util.find_spec(module_name) is None:
            continue
        module = importlib.import_module(module_name)
        declared = getattr(module, "ACTION_PROSE", None)
        if isinstance(declared, dict):
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
    """
    declared = action_prose().get(action)
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
        _registry = _discover()
    return _registry


def reset_policies() -> None:
    """Drop the caches. For tests that plant a policy module."""
    global _registry, _prose
    _registry = None
    _prose = None


@runtime_checkable
class DeclaresRoles(Protocol):
    """A policy object that says, as DATA, which roles it admits.

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


def _discover() -> dict[str, Policy]:
    found: dict[str, Policy] = {}
    for config in django_apps.get_app_configs():
        if not config.name.startswith("apps."):
            continue
        module_name = f"{config.name}.policies"
        if importlib.util.find_spec(module_name) is None:
            continue
        module = importlib.import_module(module_name)
        declared = getattr(module, "POLICIES", None)
        if isinstance(declared, dict):
            found.update({str(action): policy for action, policy in declared.items()})
    return found


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
    return list(
        Membership.objects.filter(user_id=user.pk, tenant=tenant).select_related("organization")
    )


def effective_role(
    user: AbstractBaseUser | None,
    tenant: Tenant | None,
    org: Organization | None = None,
) -> str | None:
    """The best role this person holds **over** `org`. `None` when they hold none.

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
    best: str | None = None
    for membership in memberships_in(user, tenant):
        if org is not None and not is_descendant_path(org.path, membership.organization.path):
            continue
        if rank(membership.role) > rank(best):
            best = str(membership.role)
    return best


def actor_role(actor: Actor, org: Organization | None = None) -> str | None:
    """The acting user's effective role, under their own hat unless told otherwise."""
    return effective_role(actor.user, actor.tenant, org if org is not None else actor.org)


def membership_for(actor: Actor) -> Membership | None:
    """The acting user's best membership in the acting tenant, if there is one.

    "Best" rather than "first" since a person may hold several in one tenant:
    the one that answers "what may they do here" is the strongest, and picking
    an arbitrary row would make the answer depend on insertion order. It is
    narrowed to the acting hat's ancestors when there is a hat — a policy asking
    `membership_for` while acting as a branch gets the branch's answer, not the
    group's.
    """
    if actor.user is None or actor.tenant is None:
        return None
    candidates = [
        membership
        for membership in memberships_in(actor.user, actor.tenant)
        if actor.org is None or is_descendant_path(actor.org.path, membership.organization.path)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda membership: rank(membership.role))


def is_read(action: str) -> bool:
    """True when the action's verb is one a `member` may perform by default."""
    _, _, verb = action.rpartition(".")
    return verb in READ_VERBS


def allows(actor: Actor, action: str, obj: Any = None) -> bool:
    """Whether this actor may do this, without raising. `require` is the usual call."""
    # The system acts for the product itself — a workflow, a schedule, a
    # command. There is no membership to consult and no person to ask, and the
    # tenancy is still enforced by the scoped manager on every read it makes.
    if actor.kind == "system":
        return True

    policy = policies().get(action)
    if policy is not None:
        return bool(policy(actor, obj))

    membership = membership_for(actor)
    if membership is None:
        return False
    if membership.is_privileged:
        return True
    return is_read(action)


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

        require(actor, "preference.set")
        if not may_be_named(actor, recipient):
            raise NotFound()                      # the check, done

        # reach: the dispatch workflow acts tenant-wide and holds no hat
        services.record_delivery(recipient=recipient, ...)

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
