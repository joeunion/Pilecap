# The service, the valves and the refusal grammar

The long form of `django-conventions` §4.

## The worked service

```python
# wrong — a write in a route, and a side effect in a signal nobody will find
def create_order(request, body: OrderIn): return Order.objects.create(tenant=request.tenant, **body.dict())
@receiver(post_save, sender=Order)
def send_receipt(sender, instance, created, **kwargs): ...

# right — one service: @service, keyword-only, atomic, emits its event inside the transaction, returns the object
from decimal import Decimal
from uuid import UUID

from django.db import transaction
from ninja import Field, Schema

from apps.core.actor import Actor
from apps.core.authz import require
from apps.core.schemas import event_payload, example, personal
from apps.core.service import service
from apps.events.services import emit
from apps.orders.events import ORDER_CREATED           # rule 16: the name is a constant, never a literal here

class OrderOut(Schema):                                # the door's shape; the event is it through the strip
    id: UUID
    total: Decimal
    placed_by_email: str = Field(json_schema_extra=personal(example("dana@example.com")))  # names a person

@service
def create_order(*, tenant: Tenant, actor: Actor, customer: Customer, lines: list[LineIn]) -> Order:
    require(actor, "order.create")                     # rule 13: a service that resolves an actor authorizes
    with transaction.atomic():
        order = Order.objects.create(tenant=tenant, customer=customer, placed_by=actor.user, total=sum(l.amount for l in lines))
        OrderLine.objects.bulk_create([OrderLine(order=order, **l.model_dump()) for l in lines])
        emit(name=ORDER_CREATED, tenant=tenant, payload=event_payload(OrderOut.from_orm(order)), actor=actor)
    return order
```

### The valves — the cheap way out, and where each one has to be written

A house-rule finding on a service usually has two remedies, and violation
messages tend to name only the expensive one. Rule 16's message, for instance,
says "add the verb to `service_verbs` in rules.yaml"
(`quality/checks/rule_16_the_rest_of_the_grammar.py::naming_grammar`) — which widens the lexicon for the whole
template, forever, to excuse one function. The two cheap roads it does not
mention: a **counted override** on the line, and, when the thing is not a
capability at all, the **underscore-prefix road** — rule 16 skips a
`services.py` function whose name starts with `_` outright
(`quality/checks/rule_16_the_rest_of_the_grammar.py::naming_grammar`'s `_` skip, "a private helper is the inside of a service,
not a capability"). A private helper called only by services in the same module
should be `_`-prefixed and is then not the rule's subject at all. Reach for the
lexicon only when the verb genuinely names something a product DOES.

Every valve is a comment somebody wrote and a reviewer can disagree with. Four
of the five are **counted and printed** (a suppressed finding is never a silent
one) and need a reason of at least `quality/reason_floor.py::MIN_REASON`
characters — a bare marker becomes its own
finding rather than an off switch. What differs, and what costs merge cycles to
rediscover, is **where each has to sit**:

| Valve | Whose | Where it counts | Where it is invisible |
|---|---|---|---|
| `# rule-<id>: <reason>` | any rule, the universal override (`quality/engine/run.py::override_at`) | on the **flagged line itself**, or in the **contiguous `#` block directly above it** | anywhere a non-comment line intervenes. Rule 13 reports at the `def` line, so a valve **above the `@service` decorator is invisible** — the decorator breaks the block — while one **between the decorator and `def` counts** |
| `# authz: <reason>` | rule 13, a `@service` taking `actor` that never calls `authz.require` (`quality/checks/rule_13_clauses_i_iv.py::_AUTHZ_RE`, read by `quality/checks/rule_54.py::_function_valve`) | on a **comment line inside the function**, on the **`def` line**, or in the **contiguous `#` block above the first decorator** | a docstring or string that spells it (prose is not a valve), and anywhere a non-comment line intervenes |
| `# reach: <reason>` | rule 26, an org-scoped parameter not passed through `may_be_named` (`quality/checks/rule_26.py::_REACH_RE`) | on the **parameter's own line** (or the block above it) for that one parameter; or, for the whole function, on the **`def` line or the first decorator line** — either with its contiguous block above | anywhere else |
| `# door: <reason>` | rule 42 — and since R6 (P15) the valve carries **two claims, told apart by the finding class it suppresses**: *no door reaches this service* (the original), or *only this tree's own hands reach it* (a service called by management commands/admin only); write the reason to say WHICH (`quality/checks/rule_42.py::_DOOR_RE`) | on the **`def` line or the first decorator line**, each with its contiguous block above | anywhere else |
| `# role-bound: <reason>` | rule 29, a role value written without bounding it against the granter's ceiling (`quality/checks/rule_29.py::_ROLE_BOUND_RE`) | on the **`def` line**, or on **any parameter's line**, each with its contiguous block above | anywhere else |

Three of the five read the decorator line and two do not, which is the whole
reason this table exists: if a valve you wrote did not take, check its position
before you conclude the rule is broken.

**`# authz:` is the exception to the counting, and knowing that is the point.**
The other four carry the one reason floor (`quality/reason_floor.py::MIN_REASON`,
applied by the one reader, `quality/worlds.py::comment_reason`), count their
uses (`reach_valves`, `door_valves`, `role_bound_valves`, and the gate's own
standing section, `quality/engine/run.py::standing_valves`) and turn a bare marker
into a finding of its own. Rule 13's `# authz:` does neither: it reads through
the same reader (`quality/checks/rule_54.py::_function_valve`) but accepts any valve
that reader returns, holding or not, so a bare `# authz:` with no sentence
after it still suppresses. Write the
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
  the body over `apps/core/exceptions.py::WIRE_COMMON_KEYS`; `config/api.py` sends it as JSON and
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
