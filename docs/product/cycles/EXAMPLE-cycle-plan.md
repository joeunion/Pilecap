# Cycle — "Get the customer's order in while they are on the phone"

> EXAMPLE — delete when the first real entry lands. Every name below (orders,
> customers, the clerk) is invented to show the shape; none of it is this
> repository's product.

**Type:** feature · **Framed** 2026-03-02 · **Queue rows:** N3 · N4 · N9 (debt draw)
**Persona:** the day-one order clerk · **Job:** take a complete order from a
customer who may not exist yet, without leaving the request path · **Current
cost:** two round trips, one of them a dead end (`rep-day.md` J1, seen
2026-03-02) · **Better means:** one path, a parkable draft.
**Debt drawn (band top 1–2):** N9 — the orders list query pin is set at 60
against a measured 53; lower it to measured + 2 and add `select_related`.
**Misses loaded:** i1 (criteria before code — these were written before the
rung started, baseline trees named below); cycle-1 miss "a fixture hid an
empty field" → criterion A3 drives from an empty database.

## Rungs (in order; each lands green alone)

| # | Rung | App | Doors · workflow? | Baseline tree | May run concurrently with |
|---|---|---|---|---|---|
| A | Inline customer on order create; `DRAFT` status | `orders` | REST + MCP (`orders.create`) · emits `orders.order.created` · no workflow | `4f1c…e9` (`git rev-parse HEAD^{tree}` at start) | C |
| B | Draft can be resumed and completed via `PATCH` + `/complete/` | `orders` | REST + MCP · emits `orders.order.completed` · no workflow | A's landing tree | — (same app as A) |
| C | Orders list `select_related("customer")`; pin lowered | `orders` | REST + MCP (`orders.list`, same selector) · no workflow | `4f1c…e9` | A — **no**: same app; C is sequenced after B. Recorded: the lead considered moving C to its own app and rejected it (the selector lives in `orders.selectors`). |

## Acceptance criteria — verbatim, written before the code

**A1.** `POST /api/orders/` with `{"customer": {"name": "Acme"}, "lines": [...]}`
where no customer named Acme exists for `request.tenant` returns **201** with
`customer.id` set, and `Customer.objects.for_tenant(t).filter(name="Acme").count() == 1`.
The `orders.create` MCP tool with the same body returns the same `OrderOut`
(door parity; a difference is a finding). *Absent case:* on the baseline tree
the same request returns **422** with `detail` naming `customer_id` as missing
— reproduce with an empty database, `./scripts/setup.sh` then the request
above. *If false:* the 201 does not arrive, or a second Acme appears, or the
two doors return different bodies.

**A2.** The same request with `"status": "draft"` returns 201 with
`status == "draft"`, and `GET /api/orders/?status=draft` lists it. *Absent
case:* on the baseline tree `"draft"` is rejected with 422 — the
`Order.Status` enum has no such member (`introspect` → `models.orders.Order.fields.status.choices`).

**A3.** Driven from an empty database (no fixtures): a clerk with one
membership creates the order in **one** request and **zero** prior
customer-creation requests. *Instrument:* the field test's request log; the
count of `POST /api/customers/` calls before the first 201 is 0.

**B1.** `PATCH /api/orders/{id}/` on a draft adds lines; `POST
/api/orders/{id}/complete/` moves it to `open` and is refused with **409**
`{"detail": "order has no lines"}` if it has none. *Absent case:* on A's
landing tree `/complete/` is 404.

**C1.** `GET /api/orders/?page=1` (a 50-row page, the size the router's pagination class sets) against the seeded database (`uv run
python manage.py seed_orders --tenant demo --count 500`) issues **≤ 5**
queries, asserted by `django_assert_num_queries(5)` in
`apps/orders/tests/test_api.py::test_list_orders_query_budget`. *Absent case:*
on the baseline tree the same test with the pin at 5 **fails** with 53 queries
— this is the demonstration that the pin can fail.

**Cross-explanation forbidden:** A1 passes by the inline-create mechanism in
`services.create_order`, not because C lowered query counts; C1 passes by
`select_related`, not because A created fewer customers. Attribute every
finding to its rung.

## What must still work (the negatives)

**Regression nets, byte-unchanged (the standing clause — do not drop; N7: it
was absent from four consecutive plans and the anchor discipline reopened
silently).** The four frozen nets (named in `docs/product/build-contract.md`)
ship this cycle byte-identical to their recorded anchors, or the divergence is
plan-ratified in writing and the new hashes recorded at CLOSE.

- `POST /api/orders/` with an existing customer's pk still returns 201
  (`test_create_order_with_existing_customer`).
- A user with no membership gets **an empty list**, not another tenant's
  draft (`test_no_membership_sees_nothing`).
- `makemigrations --check` clean; one leaf in `apps/orders/migrations/`;
  `max_migration.txt` matches.

## What these criteria would NOT catch (the declared blind spots)

- A draft left for 30 days — nothing here says what happens to it. When it
  lands it is a scheduled workflow, not a cron entry. Recorded as a residual
  with trigger "when the first customer asks".
- The inline customer is created even when the order's lines are invalid and
  the order is rejected — A1 asserts count == 1 on success only. **Promoted to
  a criterion?** No — `transaction.atomic` in the service covers it, and
  `test_bad_line_rejects_whole_order` exists on the baseline; the lead checked.
- Concurrency: two clerks creating "Acme" at once. Unique constraint on
  `(tenant, name)` will make one of them 400; the body of that 400 is not
  specified here.

## Rejected alternatives, and why

- **A separate `POST /api/customers/` call the client makes first.** That is
  the current state; it is the dead end J1 records.
- **`get_or_create` in the route.** Writes belong in services; the route does
  not know about tenancy uniqueness, and the MCP tool would have needed its
  own copy.
- **Running C concurrently with A in a second worktree.** Same app → both
  would produce `0007_*.py` and one would need `--merge`. Sequenced instead.

## PROVE verdict

*(Appended by the field test at stage 6. The only section written after the
code.)*
