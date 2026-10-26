# ADR core-25

**ADR core-25 · the permission vocabulary is one shape, computed from the
model registry, never stored.** *Context*: an administrator could not give
one person one capability below `admin` without a deploy or a fourth role,
and the action names the three role checks composed with were free-floating
strings — a key could name anything, nothing could census them, and no
instrument could say what permissions a deployment had. *Decision*: one
vocabulary shape `<kind>.<verb>` — kinds and the four CRUD verbs **derived**
from the model registry at import (`authz_kind` on the model is the immutable
key under a renamable class name; `authz_kind_of` puts an owned `CASCADE`
child under its aggregate's kind; `authz_kind = None` plus a reason opts a
table out), other verbs **declared** on a kind in the owning app's
`ACTION_PROSE` as one line with its sentence, one **reserved** ownership verb
`tenant.own` that no pattern matches; three layers with one owner each —
`owner` IS the vocabulary, product-declared roles live in `apps/<x>/roles.py`
with pattern collections, tenant data is custom roles, deltas and grants both
ways; `require` composes holds AND predicate at the node the object names; one
hand-out / take-back rule replaces rank; rule 13 proves a service asks for the
kind it writes. Nothing is materialised as rows — Django derives four
permissions per model at `migrate` and this derives four per kind at import,
because a table of permission names is a second owner of a fact the code
already holds, and it goes stale the moment a product adds a model.
*Rejected*: three platform built-in roles; free-floating action names; a
`<app>.<model>.<verb>` three-part key (no collision exists, and one tomorrow is
an import refusal resolved by an explicit `authz_kind` rather than a longer key
for everybody); additive rank-bundles; person × action access lists; a
`Permission` table synced from code; a parallel custom-role table; a rules
engine; allow-only grants; snapshot collections; a foreign key from
`Membership` to a role declaration; per-node role sets resolved through
`governing()` (a tree walk per `require`). *Buy, rejected with the two exits
recorded*: `contrib.auth` + guardian, django-rules, pycasbin, Oso, Cerbos,
Topaz, Zitadel authorizations, SpiceDB, Keto, Auth0 FGA and WorkOS each
contradict either the derived vocabulary or one owner of the membership graph;
**Permify is AGPL-3.0 and house rule 23's licence leg refuses it outright**.
trigger to revisit: **OpenFGA, self-hosted**, when a product needs a
relationship graph beyond the organization path — it would replace the data
half of resolution and keep the vocabulary; **AWS Verified Permissions**, when
a product is AWS-native and wants the decision out of process under a business
associate agreement. Either exit is taken behind `require`, which is the one
function every door already asks. Also revisit at the first product whose
tenants need *conditions* on a grant — time-boxed, approval-gated, "under
$1k" — which is a predicate over data and wants a check registry, not a wider
vocabulary; and at a product measuring O(people) withholds where a per-node
role set would be O(1).
