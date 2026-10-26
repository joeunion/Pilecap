# ADR core-20

**ADR core-20 · a grant comes from where you sent it: an
invitation records its landing node.** *Context*: the owner's ruling —
"Agree — comes from where you sent it. Don't elevate out of context."
`Invitation` carried no organization at all, so `invite_member` asked both its
authority questions at `root_organization(tenant)` and `accept_invitation`
landed the membership at the root, whatever hat the inviter was wearing. That
was wrong in two directions at once, and a direct measurement against the
tree — rather than argument — showed both: an owner acting under a branch's hat had a grant
land at the ROOT — reaching further than the context it was sent from, with
nothing in the request saying so — and a branch admin, who administers a branch
and nothing above it, was refused outright ("You may not invite people into this
tenant", from a `require` at a root they hold nothing on) and so could not
invite anybody into their own branch. One defect, not two: the landing node was
a constant where it should have been the context. `add_membership` with
`organization` omitted had the identical shape one door over. *Decision*:
`Invitation` is an `OrgScopedModel`; `organization` is the **landing node** —
the acting hat at grant time — written on the row. Every authority question is
asked AT that node: issue (`require(actor, "invitation.create", where)` and
`_refuse_escalation(organization=where)`), supersede, revoke (`may_be_named`
then `require(..., invitation.organization)`), and the reads, which chain
`.visible_to(org)` like every other org-scoped read. The accepted membership
lands exactly there. **An omitted placement is the ACTING HAT and never the
root**, through `_landing_node(...)` — the one seam BOTH grant doors ask, so
`add_membership` and `invite_member` cannot come to mean two things one service
apart; the root survives only where there is nobody acting (`create_tenant`,
`seed`, `accept_invitation`'s own call), because a tenant's first membership is
the whole tenant by definition. Pending uniqueness is per `(tenant,
organization, email)`: two branches may each have a live offer out to one
person, because they are offers of two places, and the tenant-wide form let one
branch silently withdraw another's. **No refusal on any of these paths names a
branch** — the accept conflict names the tenant — because telling not-there from
not-yours apart is how a caller maps a subtree they hold nothing on. The
property that makes the whole change safe, in one sentence: **a caller can only
ever be surprised narrower**; the landing node is always at or below the hat and
there is no input that widens it. A flat product (hat == root) is byte-identical
and that is asserted, not claimed. The migration is expand/contract in rule 22's
order and reversible at every step — constraint off, column nullable, backfill,
required, per-node constraint — and its backfill is a reading of history rather
than a default: every existing row predates placement and already MEANT the
root, so the root is what those rows are written down as. *Rejected*:
**docs-only honesty** (write down that invitations land at the root and call the
surprise documented — the branch admin still cannot invite into their own
branch, and the elevation is still silent); **root-as-default** (an omitted
placement going on meaning the root, which is the elevation itself wearing a
name); **org-in-the-accept-payload** (letting the accepter say where they land —
the placement is not theirs to choose, it was decided by whoever invited them
and bounded by what *they* could reach, and a field a caller can send is a field
an impersonation shape can send; accept stays session-only, ADR core-16
unchanged). trigger to revisit: a product that needs an invitation to land
somewhere the inviter could not reach (a delegated-onboarding shape, refused by
construction today — the way in is a service that names the granter's own
ceiling, never a wider default); the granter-lost-role-before-accept window
becoming a real complaint rather than a declared one (it stays open by design —
refusing at accept hands the invitee a refusal they cannot act on, and it is the
same window `add_membership` already has); or a tenant deep enough that "one
pending offer per address per node" starts reading as a duplicate-invitation bug
rather than as two offers of two places.
