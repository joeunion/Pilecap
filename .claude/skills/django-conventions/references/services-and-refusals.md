# The service, the valves and the refusal grammar

The long form of `django-conventions` §4.

## The worked service

```python
# wrong — a write in a route, and a side effect in a signal nobody will find
def create_order(request, body: OrderIn): return Order.objects.create(tenant=request.tenant, **body.dict())
@receiver(post_save, sender=Order)
def send_receipt(sender, instance, created, **kwargs): ...

# right — one service: @service, keyword-only, atomic, emits its event inside the transaction, returns the object
from django.db import transaction

from apps.core.actor import Actor
from apps.core.authz import require
from apps.core.service import service
from apps.events.services import emit
from apps.orders.events import ORDER_CREATED           # rule 16: the name is a constant, never a literal here

@service
def create_order(*, tenant: Tenant, actor: Actor, customer: Customer, lines: list[LineIn]) -> Order:
    require(actor, "order.create")                     # rule 13: a service that resolves an actor authorizes
    with transaction.atomic():
        order = Order.objects.create(tenant=tenant, customer=customer, placed_by=actor.user, total=sum(l.amount for l in lines))
        OrderLine.objects.bulk_create([OrderLine(order=order, **l.model_dump()) for l in lines])
        emit(name=ORDER_CREATED, tenant=tenant, payload=OrderOut.from_orm(order).model_dump(mode="json"), actor=actor)
    return order
```

### The valves — the cheap way out, and where each one has to be written

A house-rule finding on a service usually has two remedies, and violation
messages tend to name only the expensive one. Rule 16's message, for instance,
says "add the verb to `service_verbs` in rules.yaml"
(`quality/checks.py:1576-1578`) — which widens the lexicon for the whole
template, forever, to excuse one function. The two cheap roads it does not
mention: a **counted override** on the line, and, when the thing is not a
capability at all, the **underscore-prefix road** — rule 16 skips a
`services.py` function whose name starts with `_` outright
(`quality/checks.py:1569-1570`, "a private helper is the inside of a service,
not a capability"). A private helper called only by services in the same module
should be `_`-prefixed and is then not the rule's subject at all. Reach for the
lexicon only when the verb genuinely names something a product DOES.

Every valve is a comment somebody wrote and a reviewer can disagree with. Four
of the five are **counted and printed** (a suppressed finding is never a silent
one) and need **≥ 12 characters of reason** — a bare marker becomes its own
finding rather than an off switch. What differs, and what costs merge cycles to
rediscover, is **where each has to sit**:

| Valve | Whose | Where it counts | Where it is invisible |
|---|---|---|---|
| `# rule-<id>: <reason>` | any rule, the universal override (`quality/gate.py:70`, `override_at` `:91-110`) | on the **flagged line itself**, or in the **contiguous `#` block directly above it** | anywhere a non-comment line intervenes. Rule 13 reports at the `def` line, so a valve **above the `@service` decorator is invisible** — the decorator breaks the block — while one **between the decorator and `def` counts** |
| `# authz: <reason>` | rule 13, a `@service` taking `actor` that never calls `authz.require` (`quality/checks.py:1221`; rule 41's refusal census reads it the same way, `:5978-5997`) | **anywhere inside the function**, `def` line through its last line (the check reads `ast.get_source_segment` of the `FunctionDef`) | above the decorator, **and** between the decorator and `def` — `FunctionDef.lineno` is the `def` line, so neither is in the segment |
| `# reach: <reason>` | rule 26, an org-scoped parameter not passed through `may_be_named` (`quality/checks.py:3359`, `_reach_reason` `:3391-3410`) | on the **parameter's own line** (or the block above it) for that one parameter; or, for the whole function, on the **`def` line or the first decorator line** — either with its contiguous block above (`:3536-3537`) | anywhere else |
| `# door: <reason>` | rule 42 — and since R6 (P15) the valve carries **two claims, told apart by the finding class it suppresses**: *no door reaches this service* (the original), or *only this tree's own hands reach it* (a service called by management commands/admin only); write the reason to say WHICH (`quality/checks.py:5215`, `_door_reason` `:5231-5248`) | on the **`def` line or the first decorator line**, each with its contiguous block above (`:5453-5454`) | anywhere else |
| `# role-bound: <reason>` | rule 29, a role value written without bounding it against the granter's ceiling (`quality/checks.py:2018`, `_role_bound_reason` `:2022`) | on the **`def` line**, or on **any parameter's line**, each with its contiguous block above (`:2114-2118`) | anywhere else |

Three of the five read the decorator line and two do not, which is the whole
reason this table exists: if a valve you wrote did not take, check its position
before you conclude the rule is broken.

**`# authz:` is the exception to the counting, and knowing that is the point.**
The other four carry a 12-character reason floor
(`quality/gate.py:71`, `quality/checks.py:2019`, `:3361`, `:5216`), count their
uses (`reach_overrides`, `door_overrides`, `role_bound_comments`, and the
gate's own override census) and turn a bare marker into a finding of its own.
Rule 13's `# authz:` does neither: `quality/checks.py:1221` is a substring test,
so a bare `# authz:` with no sentence after it silently suppresses. Write the
sentence anyway. It is the only thing standing between "this service does not
authorize" and nobody ever asking why again.

### Refusals — the three-move grammar, spoken once

A refusal is a `code` (what a client branches on), a **`fact`** (what is
*true*, said to whoever is refused), and **`remedies`** (what they can *do*,
structured). All of it is declared at import, beside the class that raises it,
and `core.exceptions.register_refusal` refuses a malformed declaration at that
same import — the strongest tier there is:

```python
# wrong — an unregistered code; DomainError.__init_subclass__ refuses this at import
class QuotaExceeded(DomainError):
    code = "quota_exceeded"

# wrong — remedies as prose; register_refusal raises ValueError at import
register_refusal(code="quota_exceeded", boundary="service",
                 remedy="...", fact="...", remedies=("upgrade your plan",))

# right — all four parts, the remedies structured, declared before the class body
from apps.core.exceptions import DomainError, Remedy, register_refusal

register_refusal(
    code="quota_exceeded",
    boundary="service",
    remedy="Raise the tenant's quota row or shed the batch.",   # internal; never on the wire
    fact="This tenant's quota is spent; the request was not partially applied.",
    remedies=(Remedy("See your current usage", "introspect:refusals"),),
)

class QuotaExceeded(DomainError):
    code = "quota_exceeded"
    default_detail = "Quota exceeded."
```

- **One composer.** `core.exceptions.wire_refusal(exc)` builds
  `{detail, code, errors?, remedies?}`; `config/api.py` sends it as JSON and
  `core.mcp.tool_call` renders it through `refusal_message` as one line, code
  first. Never catch a domain exception in a route or a tool to shape your own
  body — that is the fourth copy of a rule with one home, and it is how the
  screen and the assistant come to offer different ways out.
- The internal `remedy` prose is for whoever is holding the refusal and never
  reaches a client; the `fact` is what the registry says the *code* means, and
  stays off the wire too. What travels is `detail`, `code`, `errors` when the
  refusal names fields, and `remedies` as `{label, destination}` objects.
- `destination` is an opaque `<kind>:<name>` token (`header:X-Org`,
  `docs:openapi`, `introspect:refusals`) — the template validates nothing
  about it; a product with a navigation manifest grows that rule itself.
- A raise site that knows better than the registry passes contextual
  `remedies=` (typed — `Remedy` tuples, refused otherwise), which **replaces**
  the default list rather than appending to it.
- Not-there and not-yours are one answer, deliberately: refuse an unreachable
  reference with `NotFound()`, never `Forbidden` (§2, reachability).
