# The API door — the worked forms

The long form of `django-conventions` §6.

## The worked router and schemas

```python
# wrong — "__all__" leaks the next column; auth=None; unpaginated; bare manager
class OrderSchema(ModelSchema):
    class Meta: model = Order; fields = "__all__"
@router.get("/", auth=None)
def list_orders(request): return Order.objects.all()

# right — schemas.py
class OrderIn(Schema):
    customer_id: UUID
    lines: list[LineIn]
class OrderOut(Schema):
    model_config = ConfigDict(from_attributes=True)
    id: UUID; number: str; total: Decimal; status: Order.Status; created_at: datetime

# right — api.py
from ninja import Router, Status
from ninja.pagination import paginate
from apps.core.api import CursorPagination     # the ONE seam — cursors, not page numbers (ADR core-18)
from apps.core.api.docs import Tag                 # a tag key's display name and description
from apps.accounts.auth import API_AUTH            # [SessionAuth(), ApiTokenAuth()] — the one auth, restated by name
from apps.core.actor import actor_from_request     # who is calling: user OR token, plus the acting hat
from apps.core.requests import TenantRequest       # HttpRequest + .tenant, after TenantMiddleware

PREFIX = "orders"                                  # optional; without it the mount is /api/v1/<label>/

TAGS = {"orders": Tag("Orders", "Placing an order, and following one.")}   # key = scope family; see below

router = Router(tags=["orders"], auth=API_AUTH)    # explicit here, or on every route; never None

@router.get("/", response=list[OrderOut], url_name="order-list")
@paginate(CursorPagination)                        # {"items": [...], "has_more": ..., "next_cursor": ..., "count": null}
def list_orders(request: TenantRequest, status: Order.Status | None = None) -> ScopedQuerySet[Order]:
    return selectors.orders(tenant=request.tenant, status=status)

@router.post("/", response={201: OrderOut}, url_name="order-create")
def create_order(request: TenantRequest, payload: OrderIn) -> Status[Order]:
    if request.tenant is None:
        raise HttpError(403, "No tenant for this request.")     # a write with no tenant is refused, not guessed
    actor = actor_from_request(request)             # apps.core.actor — user OR token, plus the acting hat
    customer = get_object_or_404(Customer.objects.for_tenant(request.tenant), pk=payload.customer_id)
    return Status(201, services.create_order(tenant=request.tenant, actor=actor, customer=customer, lines=payload.lines))
```

- **Choosing a tag key — because the key IS the scope family.** A router's tag
  is not a label on a page. `apps/core/api/scopes.py` derives every scope name
  from it (`<tag>:read` / `<tag>:write`), so the string you type in
  `Router(tags=[...])` is the string a bearer token's ceiling names, and it goes
  out on the wire. **Default: the plural noun of the section's primary
  resource** — `orders`, `widgets`, `connections`. **Exception: name the
  MEANING, when the noun would mislead a reader who meets the string with no
  API around it** — a scope travels alone, in somebody's runbook and somebody
  else's agent config, and `messages:write` reads like "may write a message
  row" where `messaging:write` says what is being trusted. Record the reason
  where the tag is declared. The three invocations so far: **`messaging`**
  (comms — the capability is contacting a person, not editing rows),
  **`tenant-settings`** (core — `settings:write` is the most powerful string in
  the API and says nothing about whose settings), and **`org-structure` +
  `roles`** (core — `memberships:write` names a join table, and the
  owner's reason for `roles` is a domain one: under ONC certification the
  access-control vocabulary IS role-based, so `roles:write` maps one-to-one onto
  the language the product is audited in).
  **Either way the key is not the path** — `/organizations/`, `/memberships/`
  and `/invitations/` are three resources under two families, because a URL says
  what the resource is and a tag key says what a credential is trusted with.
  **And the key FREEZES the day a token could name it.** Renaming it kills every
  ceiling that holds it, silently — the token authenticates exactly as before
  and is refused at every door with nothing saying why. `FROZEN_FAMILIES` in
  `apps/core/api/scopes.py` is the census, and a departure from it is a finding.
  So: get the key right the first time; a new one is free, a rename is a
  deprecation with two live keys and a window.

- Errors: `ninja.errors.HttpError(status, detail)` for the route's own
  refusals. A service's domain exception is mapped **once**, by the exception
  handlers in `config/api.py` — `ValidationError` → 400, `IntegrityError` →
  409, `PermissionDenied` → 403, `ObjectDoesNotExist` → 404 — never caught and
  reshaped per route. **The envelope is `{"detail": …, "code": …}` plus
  `"errors"` when the refusal names fields and `"remedies"` for every
  registered code** — `code` is always present, and the body comes from
  `core.exceptions.wire_refusal`, the one composer both doors render
  (`config/api.py:on_domain_error`; §4, "Refusals"); `architecture.md` is the
  authority and the code agrees with it. **There is no second shape.** Ninja's
  own schema errors used to be blessed as one (`{"detail": [{"loc", "msg",
  "type"}]}`, 422, no `code`); the owner's ruling folded them in,
  so `config/api.py:on_schema_validation` recomposes pydantic's list into the
  same envelope with the registered code **`invalid_body`** at 422 (RFC 9110 §15.5.21 — config/api.py::STATUS_FOR carries the argument) — a
  plain-language `detail`, the field errors under `errors` in the caller's own
  field names, and the registry's remedies. Never a bare string.
  **Never `@csrf_exempt`.**

## Strict bodies — the wrong form and the right one

```python
# wrong — pydantic drops what it does not recognise, and the 201 says nothing
class WebhookEndpointIn(Schema):
    url: str
    event_names: list[str] = []

# right — the one seam; an unknown field is `invalid_body`, naming the field
from apps.core.schemas import StrictIn

class WebhookEndpointIn(StrictIn):
    url: str
    event_names: list[str] = []
```

### Computed aggregates — `MeasuredOut`

A number the server computed travels with its basis attached, and **the UI
never computes one**:

```python
# wrong — a naked number; every door that wants context re-adds the parts, differently
class WidgetStatsOut(Schema):
    count: int

# right — the value and how it was arrived at, Decimal at both levels (rule 15)
from apps.core.schemas import MeasuredBasisOut, MeasuredOut

class WidgetStatsOut(Schema):
    count: MeasuredOut

WidgetStatsOut(count=MeasuredOut(
    value=Decimal("42"),
    basis=MeasuredBasisOut(formula="onboarded + pending", inputs={"onboarded": Decimal("30"), "pending": Decimal("12")}),
))
```

The basis is **honest**: `value` equals what `formula` evaluates to over
`inputs`, and the rung's test recomputes it. Pydantic renders `Decimal` as a
string on the wire, so the value that arrives is the value that was computed.
The MCP twin returns the same fields byte-equal (rule 17) — **including the
timestamps**: one encoder in `config/api.py` renders both doors
and `config/mcp.py` puts every machine-door answer through it, so a client
may compare two renderings of a row for equality. There is no gate
rule recognising "a computed aggregate" — it is an open set, enforced through
the lead's criteria (`django-architect` §E10) — so do not wait to be caught:
if a route sums, counts or divides, it ships `MeasuredOut`.
