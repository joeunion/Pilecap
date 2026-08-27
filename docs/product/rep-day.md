# The reference user's day — the ordering ledger

> **Holds:** the reference user's jobs, named the way they would name them —
> what exists for each, what breaks, and the bar it must clear before a real
> user meets it. This is *why* a queue row matters. Every claim names the
> artifact it was read from; a claim with no file is unverified.
> **Must not hold:** the order of work (**that lives in `queue.md`**; if the
> two disagree the queue wins and this file is stale), acceptance criteria
> (those live in `cycles/`), or a feature list.
> **Status:** skeleton. Baseline it from a code-level audit of every surface
> the reference user touches, then re-read at the start of every cycle and
> update at the end of one.

The "rep" is whoever `north-star.md` names as the reference human — the clerk,
the operator, the analyst. This file keeps the name short.

Legend: **✅ clear** · **⚠ works with a hole** · **⛔ blocks a pilot**

## J1 · "…" *(the job in the user's words)*

**Exists.** *(what is built — `file:line`, endpoint, test)*
**Breaks.** *(each hole with its evidence)*
**Bar.** *(the sentence that must be true before a real user meets it)*
**Seen, not inferred — `YYYY-MM-DD`.** *(what a field test actually observed,
driving it)*

## J2 · …

## The road to pilot, in order

*(The jobs, in the order their bars must clear. This is a derivation from the
queue, never the other way round.)*

## What I got wrong going in

*(Every audit starts from assumptions. Write down the ones that were false.)*

---

<!-- worked example — replace with your product's first real entry -->

> ## EXAMPLE — delete when the first real entry lands
>
> ### J1 · "Get the customer's order in while they are on the phone" ⚠
>
> **Exists.** `POST /api/orders/` creates an order with lines
> (`apps/orders/api.py: create_order` → `services.create_order`); the schema
> validates quantities ≥ 1 (`schemas.py:LineIn`). The `orders.create` MCP
> tool wraps the same service (`apps/orders/mcp.py`). Covered by
> `apps/orders/tests/test_api.py::test_create_order_with_lines` and
> `test_mcp.py::test_create_matches_rest`.
>
> **Breaks.**
> - **Customer must already exist.** `create_order` takes a `customer` pk; there
>   is no create-customer-inline path, so a clerk with a new customer on the
>   phone has to leave the order, create the customer, come back, and re-enter
>   the lines (`services.py:create_order` signature; no `customer.name` field
>   on `schemas.py:OrderIn`).
> - **No way to say "I'll finish this later".** `Order.Status` has `OPEN`,
>   `SHIPPED`, `CANCELLED` — no draft. A half-taken order is a committed order
>   (`models.py:Order.Status`).
>
> **Bar.** A clerk takes a complete order from an unknown customer in one
> request path without leaving the screen, and can park it half-done.
>
> **Seen, not inferred — 2026-03-02.** Field test drove `POST /api/orders/`
> from an empty database with a customer that did not exist: `404
> {"detail": "Not Found"}`. Created the customer, retried: 201. Two round
> trips, one of them a dead end with no next action in the body. The
> `orders.create` MCP tool did the same — the doors agree, which is the one
> good thing here.
>
> ### The road to pilot, in order
>
> J1 (clear the two holes above) → J3 "tell me what ships today" → J2 "find
> it again" → J4 "tell me when it shipped".
>
> ### What I got wrong going in
>
> I assumed the list route was the bottleneck. It was the create path — the
> clerk never reaches the list if entering the order is a dead end.
