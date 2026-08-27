"""Who may configure a tenant's identity provider, and who may take a person's access away.

Policies are code.

`core.authz.require(actor, "sso_connection.create")` finds these by discovery —
this file is never registered anywhere.

The rule is one sentence and it is the strictest in the repository: **only an
owner or an admin touches an SSO connection.** A connection decides *who may
become a member of this tenant, and at what role*. A member who could edit one
could point the tenant's login at an identity provider they control and then
walk in as an owner — which makes this the one row where "a member may act on
their own records" has no sensible reading at all.

Reading a connection is not on this list, deliberately: reads go through
`selectors.list_sso_connections`, which narrows to the acting tenant, and
`authz` already lets a `member` perform a `view`-shaped action. What a member
may not see is the client secret, and that is enforced where it belongs —
`SsoConnectionOut` has no field for it.
"""

from __future__ import annotations

from typing import Any

from apps.core.actor import Actor
from apps.core.authz import ADMIN_RANK, Policy, effective_role, membership_for, rank
from apps.core.exceptions import Conflict
from apps.core.services import root_organization


def is_privileged(actor: Actor, obj: Any = None) -> bool:
    """An owner or an admin of the acting tenant, and nobody else."""
    membership = membership_for(actor)
    return membership is not None and membership.is_privileged


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
    """`admin` or better **at the tenant's root**, and nothing less.

    The predicate `accounts.user.erase` needed and did not have. Without an
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

    It is deliberately **not** `is_privileged` with a different name: that
    predicate reads the acting membership's own role, which says nothing about
    where in the tree that membership sits.
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
    return rank(effective_role(actor.user, tenant, root)) >= ADMIN_RANK


def themselves_or_administers_the_whole_tenant(actor: Actor, obj: Any = None) -> bool:
    """The person themselves, or `admin` or better at the tenant's root.

    **The wall the doors of P5-B-ACCT stand behind** (ADR ident-6). Erasure and
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
    (`services.tenants_this_user_alone_owns`) — including, and especially, when
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


POLICIES: dict[str, Policy] = {
    # Who may destroy a person, and who may merely lock them out. Explicit,
    # because the fallback's answer here ("any privileged membership") is wrong
    # by a whole tenant, and because the fallback would read `deactivate` as a
    # write no `member` may perform *on themselves* either.
    "accounts.user.erase": themselves_or_administers_the_whole_tenant,
    "accounts.user.deactivate": themselves_or_administers_the_whole_tenant,
    "sso_connection.create": is_privileged,
    "sso_connection.update": is_privileged,
    "sso_connection.disable": is_privileged,
    # The deployment's own identity configuration — the workforce door. Not a
    # tenant's row, and therefore not a tenant owner's decision.
    "identity_platform.configure": is_platform_operator,
}


# The sentence a refused caller reads, per action. See `core/policies.py` for
# why these exist and what register they are written in. `sso_identity.provision`
# is here although no policy above names it: `require` is called with it, the
# role fallback answers it, and a refusal is still a refusal somebody reads.
ACTION_PROSE: dict[str, str] = {
    "accounts.user.erase": "You may not erase that account.",
    "accounts.user.deactivate": "You may not switch that account off.",
    "sso_connection.create": "You may not set up an identity provider for this tenant.",
    "sso_connection.update": "You may not change this tenant's identity providers.",
    "sso_connection.disable": "You may not disable this tenant's identity providers.",
    "sso_identity.provision": "You may not create accounts from an identity provider here.",
    "identity_platform.configure": "You may not change how this deployment signs people in.",
}
