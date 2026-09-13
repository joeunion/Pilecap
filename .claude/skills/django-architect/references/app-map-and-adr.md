# The app map and the ADR line

The formats `django-architect` § A and § I tell you to copy.

### The app-map template

One table in the product's `architecture.md`, owned by the lead, edited only
by the lead, one row per app. A rung's brief carries the delta to this table.

| app | noun (aggregate) | depends_on | doors exposed | workflows owned | events emitted / consumed |
|---|---|---|---|---|---|
| `<label>` | `<Noun>` (+ children) | `core, accounts, …` | REST `/api/v1/<prefix>/` · MCP `<nouns>.*` · socket · webhook in/out | `<WorkflowName>` | `<app>.<noun>.<past-verb>` / consumed ones |

A worked example for a generic domain (never any real product):

| app | noun (aggregate) | depends_on | doors exposed | workflows owned | events emitted / consumed |
|---|---|---|---|---|---|
| `orders` | `Order` (+ `OrderLine`) | `core, accounts, events, workflows` | REST `/api/orders/` · MCP `orders.create`, `orders.cancel` · socket push | `FulfilOrder` | emits `orders.order.placed`, `orders.order.cancelled` |
| `invoices` | `Invoice` (+ `InvoiceLine`) | `core, accounts, events, workflows, orders` | REST `/api/v1/invoices/` · MCP `invoices.issue` · webhook out | `CollectInvoice` | emits `invoices.invoice.issued`, `invoices.invoice.paid`; consumes `orders.order.placed` |

The `orders` entry in `invoices.depends_on` is an ADR line: *context:* an
invoice is built from an order's lines · *decision:* `invoices` reads `orders`
through its selectors · *rejected:* duplicating the lines onto `Invoice` at
placement (two truths), an event carrying every line (a payload that grows
with the order) · *trigger to revisit:* `orders` needs to read `invoices` back.

### The ADR line

```
ADR <app>-<n> · <date> · context: <one sentence> · decision: <one sentence> ·
rejected: <alt 1> (<why>), <alt 2> (<why>) · trigger to revisit: <the observable event>
```

It lives in the product's `architecture.md` under the app map. An ADR without
a rejected alternative is a note, not a decision; one without a trigger is a
decision nobody can reopen honestly.
