# The service contract — the long form

The long form of `django-architect` § C.

## C1 — the contract's worked form

```python
# the shape before the decorator existed — kept as the WRONG form; nothing on
# main looks like this any more (apps/example/services.py is @service today)
@transaction.atomic
def create_widget(*, tenant: Tenant, owner: User, name: str, notes: str = "") -> Widget: ...

# [A7a] the same service under the contract — @service opens the span, writes
# the AuditEntry, logs .called/.failed with the bound context
@service
def create_widget(*, tenant: Tenant, actor: Actor, name: str, notes: str = "") -> Widget:
    authz.require(actor, "widget.create", tenant)
    with transaction.atomic():
        ...
```

**C3 — A service calls another app's *services and selectors*, never its
models.** *Why:* the other app's invariants live in its services; writing its
table from outside is the sideways import with a worse failure mode.
*Enforced:* house rule **10** (the door side), **7** (the import side); review.

**C4 — A service reachable from a workflow, a webhook or an MCP tool is
idempotent, keyed on `idempotency_key`.** *Why:* Temporal retries activities,
webhook senders redeliver, agents repeat calls; a second identical call must
return the first result, not a second row. *Enforced:* criterion ("calling `X`
twice with the same key yields one row and the same return"); the REST side
is E7.

**C5 — Services raise `core.exceptions.*`; `HttpError`, `Http404` and status
codes never appear in `services.py` or `selectors.py`; the one mapper is
`config/api.py`.** *Why:* the service serves five doors; a status code is one
door's vocabulary. *Enforced:* house rule **14**. **[main]** `config/api.py`
maps `ValidationError` → 400, `IntegrityError` → 409, `PermissionDenied` →
403, `ObjectDoesNotExist` / `Http404` → 404, body keyed by
`apps/core/exceptions.py::WIRE_COMMON_KEYS` — `code` is always present, and the
body is not composed there: `core.exceptions.wire_refusal` builds it and
`on_domain_error` sends it (§E9), so `core.exceptions` is the hierarchy *and*
the composer both doors share.

## C7 — the code half

```python
# [A7a] apps/<invoices>/policies.py — the code half; the role comes from Membership.role
def can(actor: Actor, action: str, obj: object) -> bool:
    if action == "invoice.void":
        return (isinstance(obj, Invoice)
                and obj.status == Invoice.Status.ISSUED
                and actor.role in {"owner", "admin"})
    ...
```

**C8 — A reference handed to a service must have been reachable:
`may_be_named`, and the `# reach:` valve.** `require` answers "may you do this
kind of thing here"; the scoped manager answers "whose rows are these";
neither answers **"could you have got hold of *that* reference"** — the FK
handed over by id that resolves to a row in a branch the caller holds no
membership over. A `@service` that writes an `OrgScopedModel` passes each
FK-target keyword argument through **`core.authz.may_be_named(actor, obj)`**:
True only downward (the actor's hat covers `obj.organization`'s subtree — the
same direction `visible_to` reads in) or through the **link gate** (`obj`'s
model declared `InheritedDownward` and `obj.organization` is on the hat's
ancestor chain — §A5c); everything else is False, including everything
unresolved — no hat, no tenant, another tenant's row — and there is **no
`system` exemption** inside the helper. The refusal is `NotFound()`, never
`Forbidden`: not-there and not-yours are one answer on purpose (§E9). A call
site that genuinely acts tenant-wide — a platform workflow holding no hat —
writes a **`# reach: <reason>`** comment on the line it excuses: a sentence a
reviewer can disagree with, which the gate counts and prints — a backlog that
may shrink and never grow. *Enforced:* house rule **26** — AST over
`services.py`, gate-tier, ratcheted over the measured backlog; whether a
`# reach:` reason is a *good* one is review's and the surveyor's, a declared
`does_not_cover`. *Wrong:* `set_preference(recipient=recipient, ...)` writing
against whatever row the client's id resolved to. *Right:* the form in
`apps/core/authz.py`'s own docstring — `if not may_be_named(actor, recipient):
raise NotFound()` — or the recorded `# reach:` line.

**C9 — An org-scoped row that inherits its organization declares it:
`derive_org_from`.** Some rows do not *choose* their branch — a preference
belongs wherever its recipient belongs, a line wherever its order does. The
model says so (`derive_org_from = "<fk-name>"`, a `ClassVar` on
`core.models.OrgScopedModel`), and `clean()` then refuses a **final**
`organization` that disagrees with the FK-target's, on insert and on update
alike. *Why:* the class this closes is a write that derived the organization
from the *actor's hat* while the row it hangs off belongs somewhere else — the
row lands in a branch its own parent cannot see, silently, a leak in whichever
direction the mismatch went, and no read afterwards can tell you it happened.
It is an invariant on the row's own fields-by-reference, which is the kind of
rule `clean()` is for — D3 stands: a database constraint cannot reach across a
row to read the parent's column, and a service that remembers to check is a
service somebody will one day write without. *Enforced:* the landing gate runs
where a service calls `full_clean()` (house style:
`with as_invalid(): row.full_clean()` — conv §4), which is a **declared blind
spot**, with rule **26** the belt; the declaration itself is review's, placed
when the lead places the model. *Wrong:* `organization=actor.org` stamped on
a child row whose parent lives elsewhere. *Right:* the declaration, and an
`organization` left to agree with the target's.
