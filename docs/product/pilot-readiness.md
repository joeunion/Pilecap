# Pilot readiness — what stands between here and real users

> **Holds:** the ship *gate* — what must be true before real users, real data,
> real money — as a ledger of what is not yet true, each item with what was
> measured (not what was intended), a severity, and the sentence that defends
> anything deferred.
> **Must not hold:** the order of work (**that lives in `queue.md`** — an item
> here becomes work only by having a row there), acceptance criteria, or a
> status that names no artifact.
> **Status:** skeleton. Baseline it from a code- and host-level audit, dated.
> The definition of "shipped" it gates against is in `north-star.md`.

## Blocks the pilot — nothing else matters until these are true

### R0 · *(title: the property that is false, stated as a fact)* — **state, dated**

*(What was measured, with `file:line` or a reproduction · why it blocks · what
"true" would look like, as a yes/no a verifier can answer.)*

## Must be true before real data, not before first login

| # | What | State |
|---|---|---|

## Security, by severity

**High.** · **Medium.** · **Low.**

## Scale — where it bends

*(Every unbounded read against a table that grows, with the volume at which it
bends. The query pins in the tests are the tripwire; this is the map.)*

## Deferred, with the sentence that defends each

*(Silence reads as coverage. Everything not being done is named here with its
reason and the condition that makes it due.)*

## Suggested order

*(A derivation, for the PM's convenience. The queue is the authority.)*

---

<!-- worked example — replace with your product's first real entry -->

> ## EXAMPLE — delete when the first real entry lands
>
> ### R0 · A clerk at one customer can read another customer's orders — **REPRODUCED 2026-03-02**
>
> `list_orders` returns `Order.objects.all()` filtered only by status
> (`apps/orders/api/orders.py:41`); the tenant resolver sets `request.tenant`
> but nothing in the route uses it. Reproduced with two users in two tenants:
> user A `GET /api/orders/` → 200, 14 items, 6 of them tenant B's; the
> `orders.list` MCP tool goes through `selectors.orders(tenant=…)` and returns
> 8 — the doors disagree, which is its own row. House rule 8 did not fire
> because the route lives in a package (`apps/orders/api/`) and the rule's
> scope was derived from `api.py` only — a blind spot, now a row. **True**
> means: user A's list contains only tenant A's rows through every door,
> asserted by `test_list_orders_is_scoped_to_tenant` and its MCP twin, and
> rule 8's scope covers every module that imports a scoped model.
>
> ### Must be true before real data, not before first login
>
> | # | What | State |
> |---|---|---|
> | R4 | Nightly off-box backup | **none scheduled** — the only dump is `pg_dump` into the compose volume on the same box |
> | R5 | A restore drill against the real host | never run; no drill script exists in `scripts/` |
> | R6 | Anything watching | no heartbeat, no uptime check, nothing reads the dead letter for failed webhook deliveries, no alert reaches a phone |
>
> ### Security, by severity
>
> **High.** R0 above. `check --deploy` reports `SECURE_HSTS_SECONDS` unset on
> production settings (`config/settings/production.py`). **Medium.** No
> rate limit on `POST /api/auth/token/`. **Low.** Admin served on `/admin/`.
>
> ### Scale — where it bends
>
> `GET /api/orders/` issues 3 + N queries (N = page size) without
> `select_related("customer")` — measured 53 queries at page size 50; the pin
> in `test_api.py` is set at 60 and would not catch it. Bends at ~2,000 orders
> per tenant on the seeded box.
>
> ### Deferred, with the sentence that defends each
>
> - **CSV import of the spreadsheet** — not before ten orders have been entered
>   by hand; the import hides the defect class we most need found first.
> - **Second region** — when a customer outside the first one signs.
>
> ### Suggested order
>
> R0 → the query pin lowered to measured + k → R4/R5 → rate limit → R6.

