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
* **It does not read the acting hat.** The object decides the question. A
  branch manager acting under the group's hat still may not touch a sibling
  branch, because the sibling is underneath no membership they hold — and that
  is now `effective_permissions`' sentence rather than a predicate's.
"""

from __future__ import annotations

from apps.core.authz import Policy

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
