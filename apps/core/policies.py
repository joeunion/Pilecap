"""Who may reshape a tenant's organization tree. Policies are code; roles are data.

`core.authz.require(actor, "organization.move", node)` finds these by
discovery — this file is never registered anywhere.

There is one predicate here and it is worth saying why there is only one.
Creating a node, renaming it and moving it are all the same question —
**"do you administer this part of the tree?"** — and the answer is always the
same sentence: the actor's *effective* role over the node in question, which is
the best role they hold on that node **or on one of its ancestors**, must be
`admin` or better. Writing it once means a fourth operation cannot quietly
acquire a fifth rule.

Two things this file deliberately does not do:

* **It does not read the acting hat for the answer.** The object decides the
  question — "may you administer *this node*" — and the hat is only the default
  when a caller asks in the abstract (`obj is None`). A branch manager acting
  under the group's hat still may not touch a sibling branch, because the
  sibling is not underneath any membership they hold.
* **It does not implement the escalation wall.** That lives in
  `core.services._refuse_escalation`, next to the membership write it guards,
  because it is a rule about the *role being granted* rather than about the
  object being touched, and a policy predicate has no grant to look at.
"""

from __future__ import annotations

from typing import Any

from apps.core.actor import Actor
from apps.core.authz import ADMIN_RANK, Policy, effective_role, rank
from apps.core.models import Organization


def may_administer(actor: Actor, obj: Any = None) -> bool:
    """`admin` or better over this node — held on it, or on an ancestor of it.

    Without an object the acting hat stands in ("could I administer anything
    here at all?"), and **without either it is no**: a call with no node and no
    hat has not named a place, and the safe reading of "somewhere" is nowhere.
    That is also what refuses a move of the root, whose parent is `None`.
    """
    where = obj if isinstance(obj, Organization) else actor.org
    if where is None:
        return False
    return rank(effective_role(actor.user, actor.tenant, where)) >= ADMIN_RANK


POLICIES: dict[str, Policy] = {
    "organization.create": may_administer,
    "organization.rename": may_administer,
    "organization.move": may_administer,
    # Taking a hat away is an administrative act over the branch it sits on,
    # which is the same question the three above ask — so it is the same
    # predicate. The *ceiling* half of a removal (an admin may not remove an
    # owner) is not here for the reason stated in the module header: it is a
    # rule about the role being removed rather than about the object, so it
    # lives beside the write, in `core.services.revoke_membership`.
    "membership.revoke": may_administer,
    # --- when these three services first got doors --------------------------
    # All three were reachable from nothing until then, so the fact that
    # they authorized nothing had never been a hole a caller could stand in.
    # A door is what makes it one, and the answer is the same question the four
    # above ask: do you administer the place this act lands in?
    #
    # The OBJECT matters more here than anywhere else in this file, and the two
    # invitation actions and the settings one now differ about what it is.
    #
    # `tenant.configure` is the whole tenant by definition, so
    # `update_tenant_settings` passes the ROOT node rather than letting
    # `obj=None` fall back to the acting hat: without that, a branch admin
    # acting under their own hat would clear `may_administer` for their branch
    # and then rewrite settings for everybody, which is the escalation the tree
    # exists to prevent.
    #
    # The two invitation actions are the opposite case (ADR core-20, the
    # placement law). An invitation now RECORDS the node it was sent from, so
    # the object is that node — `invite_member` passes where the offer lands and
    # `revoke_invitation` passes where the offer stands. Passing the root, which
    # is what both did until the placement law, refused a branch admin for a
    # node they never named and let everybody else place an invitee above the
    # hat they were acting under.
    "invitation.create": may_administer,
    "invitation.revoke": may_administer,
    "tenant.configure": may_administer,
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
    "organization.rename": "You may not rename that organization.",
    "organization.move": "You may not move that organization.",
    "membership.revoke": "You may not remove that person's membership.",
    "invitation.create": "You may not invite people into that organization.",
    "invitation.revoke": "You may not withdraw that invitation.",
    "tenant.configure": "You may not change this tenant's configuration.",
}
