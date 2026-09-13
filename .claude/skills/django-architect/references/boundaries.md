# Boundaries — A5's two costs, A5a and A5c in full

The long form of `django-architect` § A.

- **Cost of getting it wrong safely** (org-scoping something everyone may see):
  every read carries `.visible_to(root)`. Recoverable in one rung.
- **Cost of getting it wrong the other way** (tenant-scoping something a seller
  owns): every member of the tenant reads every seller's rows, and the fix is a
  migration plus a rewrite of every door. Not recoverable in one rung.
- **So the default under uncertainty is `OrgScopedModel`.** A flat product pays
  nothing for it: the tenant is a depth-one tree, every membership sits on the
  root, and `visible_to(root)` is the whole table.

**A5a — The direction of visibility is fixed: down only.** A membership sees
its own node and everything beneath it; roles inherit downwards
(`core.authz.effective_role`). Upward or sideways visibility — a sub-seller
seeing its parent's rows, a branch seeing a sibling's — is **not** a
configuration flag and is never added by widening `visible_to`. It is a
**named policy with a recorded reason** in the product's `architecture.md`
(context · what business fact demands it · what is exposed · trigger to
revisit), implemented as an explicit predicate in the owning app's
`policies.py` and a selector that says so in its name. *Why:* every deviation
anybody has ever wanted turns out to be one report for one role, and a
selector for that report is a hole with edges; widening the primitive is a hole
without any. *Enforced:* review — house rule 24 sees the shape of the read, not
its direction, and says so in its `does_not_cover`.

**A5c — Inherited configuration resolves upward through `governing()`;
nothing else ever looks up.** A model whose rows are configuration a parent
sets for its descendants — a policy, a template choice, a quiet-hours window —
declares **`InheritedDownward`** (`apps.core.models`), and only then is
`Model.objects.for_tenant(t).governing(org)` legal: the rows on `org`'s
**ancestor chain**, nearest first, in one query — the chain is decomposed out
of `org.path` in Python (`ancestor_paths`), never a tree walk. *Why:* "the
nearest ancestor's policy wins" is one algorithm that repeats per product (ADR
core-3 counted three identical call sites in the product this was lifted
from), and the alternative — widening `visible_to` — is A5a's hole without
edges. **Upward config resolution, never upward visibility**: `visible_to` is
untouched and stays downward-only; a branch *resolves* the policy it was
already governed by whether it could see it or not, and it still cannot list
its parent's rows. `governing()` on an unmarked model raises `TypeError`
naming the marker; `governing(None)` returns nothing — the same fail-closed
shape as `for_tenant(None)` and `visible_to(None)`. The declaration also
widens `core.authz.may_be_named` by exactly the marked population — the **link
gate** (§C8): a branch may *name* ancestor config it could never list,
because the edge on the hole is that the caller must already hold the
reference, so it discovers nothing. Sideways is not this and never becomes
this — a sibling share is A5a's named policy with a recorded reason.
*Enforced:* the model refuses (`TypeError`); house rule **24** as amended — a
`governing()` on a model that has not declared `InheritedDownward` is a
violation, so the widening and its fence are born together; the marker
decision itself is review's, made in the app map beside the A5 choice.
*Wrong:* `visible_to` widened to "and ancestors" for one resolver. *Right:*
`class WidgetPolicy(InheritedDownward, OrgScopedModel)`, a `get_` selector
calling `.for_tenant(t).governing(actor.org).first()` — and the **list**
selector still `visible_to`: a list never widens upward.
