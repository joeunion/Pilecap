"""Who may reshape a tenant's organization tree — and, now, who does not need a rule.

`core.authz.require(actor, "organization.move", node)` finds this file by
discovery — it is never registered anywhere.

**There is no predicate here any more, and that is the change.** Creating a
node, renaming it, moving it, inviting into it, withdrawing an offer, changing
a tenant's settings and removing a membership were all one question —
*"do you administer this part of the tree?"* — answered by one predicate that
read the actor's best ROLE over the node and compared it against a rank.
Resolution asks that question now, and asks it better: `where_of(actor, obj)`
is the node the object names, and the declared `admin` role holds `("*",)` over
it, so the seven keys are held exactly where a membership on that node or on
one of its ancestors says they are. Nothing about the answers moved; what moved
is that a tenant can now take one of the seven away from one person, which a
rank comparison could never express.

What this file still owns, and both are declarations rather than code:

* **The renames** — the three keys `core` brought into the one shape, each
  with the CRUD verb the act already was.
* **The prose** — one plain sentence per action, which is what a refused caller
  reads. The key is how a service asks the question; it is not English.

Two things it deliberately still does not do:

* **It does not implement the escalation wall.** That lives in
  `core.services._refuse_escalation`, next to the membership write it guards,
  because it is a rule about the *role being granted* rather than about the
  object being touched, and a policy predicate has no grant to look at.
* **It does not read the hat.** The object decides the question. A
  branch manager acting under the group's hat still may not touch a sibling
  branch, because the sibling is underneath no membership they hold — and that
  is now `effective_permissions`' sentence rather than a predicate's.
"""

from __future__ import annotations

from typing import Any

from apps.core.actor import Actor
from apps.core.authz import Policy, holds, refuses_system
from apps.core.exceptions import Conflict
from apps.core.models import Organization, is_org_scoped
from apps.core.services import root_organization

# **Empty, and it is a statement.** Every key `core` used to guard with the
# administer predicate is a plain capability now: `organization.create/update/
# move`, `invitation.create/revoke`, `tenant.update` and `membership.delete`
# are held by whoever holds them at the node the object names, and there is
# nothing left for a predicate to add. A predicate is for a question about the ROW — "is
# this person the widget's own creator" — and none of the seven has one.
#
# `core` keeps the dict so the discovery walk finds a shape it recognises and so
# the first product predicate here is an addition rather than a new file.
POLICIES: dict[str, Policy] = {}


#: The capability that says "administers this node": renaming it. The template's
#: `admin` role holds it (`*`) wherever its membership reaches, and `member`
#: (`*.read`) never does. `may_archive` asks it rather than a role by value
#: (house rule 54 (c)), and rather than `<kind>.archive` itself — that is the
#: key this predicate decides, so asking it back would be circular.
ADMINISTERS_THE_NODE = "organization.update"


@refuses_system
def may_archive(actor: Actor, obj: Any = None) -> bool:
    """Archive and Restore are an ADMINISTRATOR's press, and the system is nobody's.

    **The node's administration, asked at the noun's own node, inheriting
    downward:** the actor must hold `organization.update` WHERE THE ROW LIVES —
    an admin of the group archives a branch's row; a branch admin never
    archives the group's; a member never archives at all, and is refused with
    the key's own sentence. Restore is the same predicate: whoever may take a
    row out of the book may put it back, and a restore a narrower role could
    press would be a second, weaker door onto the same state.

    Where the question is asked, and why it is never the hat:

    * an `Organization` is its own node;
    * an org-scoped noun is asked at its `organization`;
    * a tenant-scoped noun names no branch, so it is asked at the tenant's
      ROOT — a tenant-wide row is the root's to take out of the book, and
      asking at the hat would let a branch admin archive rows the whole tenant
      reads.

    **`@refuses_system`**: the system actor gets THIS answer rather than the
    exemption, and it holds nothing, so it is no — a workflow does not archive
    a person's row on its own say-so. Fails closed on every unresolved half —
    no object, a tenant with no root.

    DOES NOT COVER — declared: this predicate is the CODE half, and `allows`
    asks the data half first — the key itself must be in the actor's collection
    at that node. A custom role therefore archives only when it holds BOTH
    `<kind>.archive` (resp. `.restore`) AND `organization.update` there; either
    alone is refused. It fails safe: a tenant that hands a role
    `organization.update` has not thereby handed it archive.

    A noun's app declares the pair once, in its own `policies.py`:

        POLICIES = {"widget.archive": may_archive, "widget.restore": may_archive}
    """
    return _administers_where_it_lives(actor, obj)


def _administers_where_it_lives(actor: Actor, obj: Any) -> bool:
    """`organization.update` held at the node `obj` lives at. Fails closed."""
    if obj is None:
        return False
    if isinstance(obj, Organization):
        return holds(actor, ADMINISTERS_THE_NODE, at=obj)
    if is_org_scoped(type(obj)):
        branch = getattr(obj, "organization", None)
        return isinstance(branch, Organization) and holds(actor, ADMINISTERS_THE_NODE, at=branch)
    tenant_id = getattr(obj, "tenant_id", None)
    if tenant_id is None:
        return False
    # The actor's own tenant instance carries the memoised root (`Tenant`'s
    # `remember_root`), so a page of tenant-wide rows resolves it ONCE rather
    # than once per row through each row's own `tenant`. A row of another
    # tenant asks at its own tenant's root, and holds nothing there.
    tenant = (
        actor.tenant if actor.tenant is not None and actor.tenant.pk == tenant_id else obj.tenant
    )
    try:
        root = root_organization(tenant=tenant)
    except Conflict:
        return False
    return holds(actor, ADMINISTERS_THE_NODE, at=root)


@refuses_system
def may_move(actor: Actor, obj: Any = None) -> bool:
    """Move is an ADMINISTRATOR's press at BOTH ends, and the system is nobody's.

    The noun's service asks `<kind>.move` twice — once of the row (asked where
    it lives now) and once of the destination `Organization` (asked there) —
    the two-ends rule `move_organization` already keeps: a branch admin moves
    a row within the branch, never out of it and never into a sibling. Each
    question is `organization.update` at that node, `may_archive`'s reading.

    **`@refuses_system`**: a workflow does not re-home a person's row on its own
    say-so. DOES NOT COVER — declared: as `may_archive`'s — a custom role needs
    `<kind>.move` in its collection as well as `organization.update`.

        POLICIES = {"widget.move": may_move}
    """
    return _administers_where_it_lives(actor, obj)


@refuses_system
def may_merge(actor: Actor, obj: Any = None) -> bool:
    """Merge is an ADMINISTRATOR's press on BOTH records, and the system is nobody's.

    The noun's `merge_<noun>` asks `<kind>.merge` twice — of the loser and of
    the survivor, each where it lives — so a merge reaching across two branches
    needs administration at both. Each question is `organization.update` at that
    node, `may_archive`'s reading: a merge archives the loser, and whoever may
    not archive it may not merge it away either.

    **`@refuses_system`**: a workflow does not fold a person's record into
    another on its own say-so. DOES NOT COVER — declared: as `may_archive`'s.

        POLICIES = {"widget.merge": may_merge}
    """
    return _administers_where_it_lives(actor, obj)


# The three keys `core` renamed when the vocabulary became one shape, and the
# WHOLE cost of renaming one: a line here (ADR core-25). `core.authz.allows`
# resolves an alias one line BEFORE the policy lookup, so a product still
# calling `require(actor, "organization.rename", org)` gets exactly the answer
# it got before, with one deprecation printed per process — and never the role
# default, which is what an alias resolved after the lookup would have handed
# it. `manage.py rename_permission` is what rewrites rows once a deployment has
# grants; on this tree the tables do not exist yet, so there is nothing to
# rewrite and the rename costs no migration.
#
# Each of the three is the CRUD verb the act already was: renaming an
# organization is updating it, configuring a tenant is updating it, revoking a
# membership is deleting it. The sentences below did not move by one byte.
RENAMED_PERMISSIONS: dict[str, str] = {
    "organization.rename": "organization.update",
    "tenant.configure": "tenant.update",
    "membership.revoke": "membership.delete",
}


# What a refused caller is TOLD, one plain sentence per action — never the
# action name itself (`core.authz.refusal_sentence`; the owner's plain-language
# ruling of 2026-08-23, and FT-1's live catch of "You may not
# invitation.create." on 2026-08-24). The register is the escalation wall's,
# which was already right: say what is true and stop, without naming a module,
# a policy or a role the reader has no way to check.
#
# The vocabulary is the API document's: a **tenant** is one customer account and
# an **organization** is a part of it. Neither is house idiom — both are taught
# in the overview a caller reads before their first request — and using anything
# else here (a "workspace", a "node") would have the refusal and the guide
# describing one structure in two languages.
ACTION_PROSE: dict[str, str] = {
    "organization.create": "You may not create an organization there.",
    "organization.update": "You may not rename that organization.",
    "organization.move": "You may not move that organization.",
    "membership.delete": "You may not remove that person's membership.",
    # The two derived keys the membership doors ask for. Both existed as
    # permissions the moment every kind got its four verbs; what they had never
    # had was a SENTENCE, and the sentence is what a refused caller reads. The
    # `create` one closes a published contract that was not being kept: the
    # route has always promised "403 — you do not administer that organization"
    # and a member adding a member got 201.
    "membership.create": "You may not add people to that organization.",
    "membership.update": "You may not change what that person may do here.",
    "invitation.create": "You may not invite people into that organization.",
    "invitation.revoke": "You may not withdraw that invitation.",
    "tenant.update": "You may not change this tenant's configuration.",
}
