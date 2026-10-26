"""Who may configure a tenant's identity provider, and who may take a person's access away.

Policies are code.

`core.authz.require(actor, "sso_connection.create")` finds these by discovery —
this file is never registered anywhere.

The rule is one sentence and it is the strictest in the repository: **only an
owner or an admin touches an SSO connection — at the tenant's ROOT.** A branch
admin administers a branch; the tenant's identity provider is the tenant's, and
until R1 the four SSO keys were asked with the connection as the object, so the
acting hat answered and an administrator of one leaf renamed, re-claimed,
enforced and deleted the owner's connection over the wire. The services pass
`root_organization(tenant=tenant)` now, and the keys carry no predicate at all:
`admin` holds them by `*` at the root and `owner` by the vocabulary, which is
the data half answering the question a predicate used to restate.

A connection decides *who may become a member of this tenant, and at what
role*. A member who could edit one
could point the tenant's login at an identity provider they control and then
walk in as an owner — which makes this the one row where "a member may act on
their own records" has no sensible reading at all.

Reading a connection is not a policy: it is `sso_connection.read`, asked in
`selectors.list_sso_connections` at the acting hat, and narrowed to the acting
tenant by `for_tenant` before anything is asked at all. What a member may not
see is the client secret, and that is enforced where it belongs —
`SsoConnectionOut` has no field for it.

**The keys are `<kind>.<verb>` now (P8, the last Phase-W sweep).** Three of them
moved and their old spellings live on in `RENAMED_PERMISSIONS` below, so a
CALLER still saying the old word is answered. **A stored row is a different
question and the answer is no**: a `Grant` or `RolePermission` a deployment
wrote under the old key is INERT from this merge until `manage.py
rename_permission` moves it, because the alias is resolved on the way IN to
`allows` and the collection is read by the new key. That is the documented
semantics of every rename here, and the CHANGELOG names each key and the
step. `user.erase`
and `user.deactivate` are keys of the kind `core.authz` already derives from
`User`; `deployment.configure` is a key of the VIRTUAL kind — the installation
itself, which has no table for a collection to be about, and for which `allows`
therefore skips the data half and lets the predicate be the whole rule.

**How much authority is asked, never computed.** The two account-wall predicates
used to read a rank at the tenant's root. They now ask whether the actor HOLDS
`ADMINISTERS_THE_TENANTS_PEOPLE` there — the same node, the same population on
the template, and a question a tenant's own role rows can answer differently
where a rank table never could.

**The member half is declared as data in `DEFAULT_ROLES`** (`user.erase`,
`user.deactivate`, `user.unlink`); the predicate narrows what the declaration offers.
"""

from __future__ import annotations

from typing import Any

from apps.accounts.models import domain_of
from apps.accounts.selectors import get_workforce_domains
from apps.core.actor import Actor
from apps.core.authz import Policy, holds
from apps.core.exceptions import Conflict
from apps.core.services import root_organization

#: The key that means "administers this tenant's people", asked at the ROOT
#: wherever this file used to compare a rank. It is a derived key of the kind
#: `User` yields and carries no predicate of its own, which is what makes it
#: usable as a bar: a key WITH a predicate is offered to every declared role by
#: the compat residue, so asking one here would admit exactly the people the
#: wall exists to refuse.
#:
#: It resolves to `admin` (by its `("*",)` pattern) and `owner` (by the
#: vocabulary) on the template, which is exactly who the rank comparison
#: admitted — and to whoever else a tenant's own role rows name, which the rank
#: comparison could never express.
ADMINISTERS_THE_TENANTS_PEOPLE = "user.update"


def is_workforce_email(email: str) -> bool:
    """Whether the workforce door may admit this address at all."""
    domains = get_workforce_domains()
    if not domains:
        return False
    return domain_of(email) in domains


def is_platform_operator(actor: Actor, obj: Any = None) -> bool:
    """Somebody who administers **the deployment**, not a customer inside it.

    The workforce Google door and the Zitadel objects behind it are the
    installation's configuration: one instance, one set of credentials, shared by
    every tenant on it. An owner of Acme is the most privileged person Acme has
    and has no business at all deciding which identity provider the staff of the
    company running this product sign in through — that is not a bigger version
    of their own permission, it is a different one.

    So it is `is_superuser` and not a role: the role vocabulary
    (`owner`/`admin`/`member`) is *within* a tenant by construction, and there is
    no fourth role to add here without making every tenant's owner wonder why
    they cannot use it. A `system` actor — `zitadel_seed`, a workflow — never
    reaches this: `core.authz.allows` answers it before any policy runs, because
    the product acting for itself has no membership to consult.

    **The escalation wall, from the other side.** `Membership.role` is written
    only by the membership services and cannot reach `superuser`; `is_superuser`
    is set by `createsuperuser` and by `create_user`'s one write path. Neither
    door lets a tenant's owner climb into the other's answer.
    """
    user = actor.user
    return bool(user is not None and getattr(user, "is_superuser", False))


def administers_the_whole_tenant(actor: Actor, obj: Any = None) -> bool:
    """Holds `ADMINISTERS_THE_TENANTS_PEOPLE` **at the tenant's root**, and nothing less.

    The predicate `user.erase` needed and did not have. Without an
    entry here, `core.authz.allows` fell through to the role fallback — "is this
    actor's membership privileged" — which is true of an `admin` of one branch
    of a large tenant, and `erase_user`'s own guard only asked whether the
    target belonged to the acting *tenant*. A branch admin could therefore erase
    somebody in the branch next door.

    **Why the root rather than the acting hat's subtree.** An erasure is not an
    org-scoped act. It anonymises the person everywhere, revokes every token
    they hold in every tenant, and asks the identity platform to deactivate the
    account they sign in to the *deployment* with. No branch of one tenant owns
    that reach, so no branch's admin may exercise it. Reading the ceiling at the
    root also fails closed where a subtree test would fall open: an actor with
    no resolved hat has no subtree to be inside, and "no hat" must never widen
    into "anywhere".

    It reads the ceiling at the ROOT rather than at the acting hat, which is the
    same distinction the four SSO keys make by passing the root to `require`:
    the acting membership's own role says nothing about where in the tree that
    membership sits.

    **The question moved from a rank to a key and the node did not** (P8). It
    used to compare the actor's resolved role at this same root against a rank
    table — a per-process table being a second opinion about data a tenant owns,
    and the shapes it was written in are the ones rule 54 (c) counts, so they are
    described here rather than spelled. It is now one `holds(...)` of the key
    named at the top of this file, which reads the very rows the role editor
    writes, so a tenant that excludes that key from its administrators has said
    something this wall now hears.
    """
    tenant = actor.tenant
    if tenant is None:
        return False
    try:
        root = root_organization(tenant=tenant)
    except Conflict:
        # A tenant with no root is a broken database, and an authorization
        # predicate is not the place to raise about it. No is the safe reading.
        return False
    return holds(actor, ADMINISTERS_THE_TENANTS_PEOPLE, at=root)


def themselves_or_administers_the_whole_tenant(actor: Actor, obj: Any = None) -> bool:
    """The person themselves, or `admin` or better at the tenant's root.

    **The wall the account doors stand behind** (ADR ident-6). Erasure and
    deactivation both reach a `User`, and there are exactly two answers to "who
    may take this person's access away": that person, and somebody who
    administers the whole tenant they are in.

    **Why self is safe here, said out loud.** A self clause on an authorization
    predicate is normally where escalation hides — it is a caller naming their
    own row and getting a bigger answer. It cannot do that here, because both
    acts this predicate guards are *downward only*: they remove access and grant
    none, and neither takes a role, a tenant or an organization as a parameter.
    The one thing self-service could destroy is a tenant left with no owner, and
    that is refused before either service writes anything
    (`selectors.list_tenants_this_user_alone_owns`) — including, and especially, when
    the person acting is the sole owner themselves.

    **`actor.user` and not `obj.pk == actor.user_id` alone.** An anonymous or
    token-only actor has no user, and `None == None` would have made "nobody" a
    match for "the person themselves" — the fail-open reading of a fail-closed
    question.

    It delegates the second half rather than restating it: the root ceiling, and
    the argument for why an erasure is not an org-scoped act, live in
    `administers_the_whole_tenant` and are not worth two copies.
    """
    user = actor.user
    if user is not None and getattr(user, "pk", None) is not None:
        if getattr(obj, "pk", None) == user.pk:
            return True
    return administers_the_whole_tenant(actor, obj)


#: The keys this app renamed, old word to new (P8, the last Phase-W sweep).
#: **An old word ASKED is answered; an old word STORED is not.** `allows`
#: resolves an alias before it looks a policy up, deliberately, because a
#: renamed key resolved after the lookup would find no policy and fall to the
#: role default — the silent widening a rename exists to avoid. The other
#: direction has no such seam and is not meant to: a `Grant` or
#: `RolePermission` row carrying an old key is INERT from this merge until
#: `manage.py rename_permission` moves it, and the CHANGELOG names every key
#: and the step.
RENAMED_PERMISSIONS: dict[str, str] = {
    "accounts.user.deactivate": "user.deactivate",
    "accounts.user.erase": "user.erase",
    "identity_platform.configure": "deployment.configure",
    "sso_identity.provision": "sso_identity.create",
}


POLICIES: dict[str, Policy] = {
    # Who may destroy a person, and who may merely lock them out. Explicit,
    # because the fallback's answer here ("any privileged membership") is wrong
    # by a whole tenant, and because the fallback would read `deactivate` as a
    # write no `member` may perform *on themselves* either.
    "user.erase": themselves_or_administers_the_whole_tenant,
    "user.deactivate": themselves_or_administers_the_whole_tenant,
    # Cutting somebody's join to the identity platform is neither of the two
    # above — the account keeps everything it holds — but it ends their ability
    # to sign in until they link again, so it stands behind the same wall.
    "user.unlink": themselves_or_administers_the_whole_tenant,
    # **The four SSO keys carry NO policy, deliberately** (R1). They used to
    # carry a predicate that read the acting membership's own role — "is this
    # one owner or admin" — which is the data half's own question asked a second
    # time in code, and asked about the acting HAT: a branch admin passed it and
    # reached the tenant's identity provider. The services ask the four at
    # `root_organization(...)` instead, where `admin` holds `*` and `owner`
    # holds the vocabulary, and `member` holds neither (`*.read` names no
    # write). A predicate here would restate that and, being a predicate, would
    # also be final for an owner.
    #
    # The name of the deleted predicate is deliberately not written here: the
    # role-by-value census counts marker-shaped strings wherever they appear,
    # prose included, and a comment that spelled it would keep the line it
    # exists to remove.
    #
    # Confirming a domain claim sits at the same height: the operator at the
    # shell is the trust root and arrives as `system`, which `allows()` answers
    # before any node is asked.
    # The deployment's own identity configuration — the workforce door. Not a
    # tenant's row, and therefore not a tenant owner's decision. The kind is
    # VIRTUAL: there is no table the installation is a row of, so `allows` has
    # nothing to hold a collection over and this predicate is the entire rule —
    # which is what lets a superuser with no membership anywhere pass it.
    "deployment.configure": is_platform_operator,
}


# The sentence a refused caller reads, per action. See `core/policies.py` for
# why these exist and what register they are written in. `sso_identity.create`
# is here although no policy above names it: `require` is called with it, the
# data half answers it, and a refusal is still a refusal somebody reads. It is
# a DERIVED key, so this entry overrides the sentence the registry would build
# out of the model's `verbose_name` rather than declaring a second key.
ACTION_PROSE: dict[str, str] = {
    "user.erase": "You may not erase that account.",
    "user.deactivate": "You may not switch that account off.",
    "user.unlink": "You may not cut that account's link to the identity platform.",
    "sso_connection.create": "You may not set up an identity provider for this tenant.",
    "sso_connection.update": "You may not change this tenant's identity providers.",
    "sso_connection.disable": "You may not disable this tenant's identity providers.",
    "sso_domain.verify": "You may not verify an email domain for this tenant.",
    "sso_identity.create": "You may not create accounts from an identity provider here.",
    "deployment.configure": "You may not change how this deployment signs people in.",
}

# The member half of the three user-wall keys, as data; the predicates above narrow it.

DEFAULT_ROLES: dict[str, frozenset[str]] = {
    "user.erase": frozenset({"member"}),
    "user.deactivate": frozenset({"member"}),
    "user.unlink": frozenset({"member"}),
}
