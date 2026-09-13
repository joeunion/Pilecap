# The hierarchy — reads with two halves

The long form of `django-conventions` §2, one level down from tenancy: the
tenant is a tree of `core.Organization`, and four rules follow from it.

### Hierarchy — the tenant is a tree, and reads have two halves

Every tenant owns a tree of `core.Organization` — a **materialized path** of
fixed-width base36 segments (`0000`, `0000.0001`, …), so "everything under this
node" is one indexed prefix scan and never a recursion. `create_tenant` makes
the **root**; a flat product is a depth-one tree and pays nothing.

**A row one *part* of the tenant owns inherits `OrgScopedModel`** (which is
`TenantScopedModel` plus an `organization` FK). Whether a model is org-scoped or
merely tenant-scoped is the architect's call, made in the app map — see
`django-architect` § A5. If you are writing the model and it has not been
decided, ask; do not guess downward.

```python
# wrong — half a read: this hands a sub-seller the whole tenant. Rule 24 refuses it.
rows = Deal.objects.for_tenant(tenant).filter(status="open")

# right — both halves, in this order, every time
rows = Deal.objects.for_tenant(tenant).visible_to(actor_or_org).filter(status="open")
```

- **`for_tenant` answers "whose data"; `visible_to` answers "which part of their
  network".** Both fail closed: `for_tenant(None)` and `visible_to(None)` each
  return nothing, so an unresolved tenant or an unresolved hat reads an empty
  table rather than the table. There is no superuser exemption at either level.
- **Visibility flows down only.** A seller sees its own rows and its
  sub-sellers'; never its parent's, never a sibling's. Upward or sideways is a
  named policy with a recorded reason, never a wider `visible_to`.
- `visible_to` takes an `Organization`, or anything carrying one on `.org` — an
  `Actor`, an MCP `Principal`. Selectors take `org=` and pass it through; a
  selector that takes only `tenant` on an org-scoped model is the violation
  house rule 24 exists for.

**The acting hat.** `X-Org: <slug>`, resolved **after** the tenant by
`core.middleware.resolve_org` — the one function the HTTP door, the bearer-token
auth, the socket middleware and the MCP mount all call, which is what makes the
four doors answer with the same rows for the same header. It resolves to a node
the user holds a membership **on or above**, or to `None`; the default is their
default membership's own node. It is revalidated every request, from rows.

```python
# right — the door passes what the middleware resolved; nothing reads it from a global
rows = list_deals(tenant=request.tenant, org=request.org)          # REST
rows = list_deals(tenant=acting.tenant, org=acting.org)            # MCP tool
tenant, user_id, org = workflow_context()                          # activity
```

**Writes take the hat from the actor, never from an argument.**

```python
# wrong — a caller that can name an organization can write into one it has no membership over
def create_deal(*, tenant: Tenant, actor: Actor, organization: Organization, name: str) -> Deal: ...

# right — the hat the door resolved, refused when there is none
def create_deal(*, tenant: Tenant, actor: Actor, name: str) -> Deal:
    require(actor, "deal.create")
    if actor.org is None:
        raise Invalid({"organization": ["This request resolved no acting organization."]})
    ...
```

**The escalation wall.** Memberships are person × tenant × org × role, and a
role is granted only through `core.services.add_membership` / `set_role`, which
refuse two things: a grant **outside the granter's subtree**, and a grant
**above the granter's own effective role**. Pass the granting `actor`; that is
what turns the wall on.

```python
# wrong — the wall is skipped, and an admin has just made an owner
Membership.objects.create(user=user, tenant=tenant, organization=branch, role="owner")

# right — refused with Forbidden when the granter is only an admin, or is elsewhere in the tree
add_membership(user=user, tenant=tenant, organization=branch, role="admin", actor=acting)
```

**Effective role** is `core.authz.effective_role(user, tenant, org)`: the best
role among the memberships whose organization is that node or an ancestor of it.
Roles inherit downwards; nothing inherits up or sideways.

**Re-parenting is a service plus a workflow** — `move_organization` authorizes
(ancestor-admin of **both** the old and the new parent) and starts a durable
run; `apply_organization_move` takes `select_for_update` over the whole subtree
and rewrites its paths in batches. Never write `Organization.path` or `.parent`
anywhere else: house rule 24 refuses it, and a path edited by hand is a subtree
that silently vanishes from every read in the product.

Every audit row carries `acting_org`, and the acting org rides on the workflow's
Temporal headers, so "which hat was this done under" is answerable months later.

### Inherited config — `governing()`, and the model that declares it

Configuration a parent sets for its descendants — a policy, a template choice,
a quiet-hours window — is resolved **upward**, and only on a model that has
said so by declaring `InheritedDownward` (`apps.core.models`):

```python
# wrong — resolving "which policy governs me" by widening a list read, or by
# walking parents in Python with one query per level
policies = WidgetPolicy.objects.for_tenant(tenant).filter(...)   # ...then climb

# right — the model declares it; resolution is one query, nearest ancestor first
from apps.core.models import InheritedDownward, OrgScopedModel

class WidgetPolicy(InheritedDownward, OrgScopedModel): ...

policy = WidgetPolicy.objects.for_tenant(tenant).governing(actor.org).first()
```

- **Upward config resolution, never upward visibility.** `governing(org)`
  returns the rows on `org`'s ancestor chain, nearest first — the chain is
  decomposed out of `org.path` in Python (`ancestor_paths`), so it costs no
  extra query. `visible_to` is untouched: a branch may *resolve* the policy
  that governs it and still cannot *list* its parent's rows. A `get_` selector
  resolves with `governing()`; every `list_` selector stays `visible_to` — a
  list never widens upward.
- `governing()` on a model that has not declared `InheritedDownward` raises
  `TypeError` naming the marker; `governing(None)` returns nothing — the same
  fail-closed shape as `for_tenant(None)` and `visible_to(None)`.
- Whether a model is inherited-downward is the architect's call
  (`django-architect` §A5c), made in the app map. If it has not been decided,
  ask; do not declare it to make a read compile.

### Reachability — `may_be_named`, and the `# reach:` grammar

A service takes `recipient=`, `policy=`, `parent=`; the caller hands an id;
the id resolves to a row in a branch the caller holds no membership over —
and nothing in tenancy or in `require` catches it, because the row *is* in
the tenant and the policy is about the verb. `core.authz.may_be_named(actor,
obj)` answers that third question, and house rule 26 reads every FK-target
keyword argument of a `@service` that writes an `OrgScopedModel`:

```python
# wrong — the write lands against whatever row the client's id resolved to
@service
def set_preference(*, tenant: Tenant, actor: Actor, recipient: Recipient, ...) -> ChannelPreference:
    require(actor, "preference.set")
    ...

# right — reachability checked, refused as not_found (not-there ≡ not-yours)
    require(actor, "preference.set")
    if not may_be_named(actor, recipient):
        raise NotFound()

# right — the recorded valve, for a caller that genuinely holds no hat
    # reach: the dispatch workflow acts tenant-wide and holds no hat
    services.record_delivery(recipient=recipient, ...)
```

- True two ways only: **downward** (the hat covers `obj.organization`'s
  subtree — the direction `visible_to` reads in), or the **link gate** (the
  model declared `InheritedDownward` and `obj.organization` is on the hat's
  ancestor chain — a branch may *name* the policy its parent set for it).
  Everything else is False, including everything unresolved; there is no
  `system` exemption.
- Refuse with `NotFound()`, never `Forbidden` — a refusal that told
  not-there from not-yours apart would confirm the row exists.
- The `# reach:` comment is not a disable: it sits on the line it excuses,
  the gate counts and prints every one, and the backlog may shrink and never
  grow. Write the reason as a sentence a reviewer can disagree with.

### Where a derived row lands — `derive_org_from`

An org-scoped row that inherits its branch from something it points at says
so, and the landing gate in `OrgScopedModel.clean()` then refuses a final
`organization` that disagrees with the target's, on insert and update alike:

```python
# wrong — the org stamped from the acting hat while the parent lives elsewhere;
# the row lands in a branch its own parent cannot see, silently
entry = WidgetEntry(tenant=tenant, organization=actor.org, widget=widget, ...)

# right — the model declares where its organization comes from
# (the marked worked example: apps/example/models.py, WidgetEntry)
class WidgetEntry(OrgScopedModel):
    derive_org_from = "widget"
```

The gate runs where the service calls `full_clean()` — which the house style
already does (`with as_invalid(): row.full_clean()`, §4) — and that is a
declared blind spot, not a closed question; rule 26 is the belt.

**A service never trusts that the caller resolved its object correctly.** A
service that takes a scoped-model instance was handed a row somebody else
fetched. Today every door fetches through `for_tenant(request.tenant)` (rule
8), which is why the pattern holds — but a policy predicate that inspects the
object, or any future non-door caller resolving by pk, stands outside that
fence. Either re-assert the boundary in the service (`obj.tenant_id ==
tenant.pk`, refuse with `NotFound`), or state in the service's docstring that
only door fetches reach it. Silence is the wrong third option.
