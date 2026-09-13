# One feature, end to end — the widget, narrated from the real tree

This is the tour of `apps/example`: one org-scoped model carried through every
convention and every door, narrated from the code as it stands on main. Nothing
here is invented — every path opens, and every step names the house rule
guarding it (ids as `docs/product/architecture.md` numbers them; text in
`quality/rules.yaml`). Read with the files beside you; the docstrings in the
example app are half the documentation of this platform and they are deliberate.

> **The example app now also demonstrates upward configuration.**
> `WidgetPolicy` declares
> `InheritedDownward` and is read with `.governing(org)`; `WidgetEntry`
> declares `derive_org_from = "widget"` — the landing gate, so an entry lands
> in its widget's branch, never the hat's; and `GET /api/v1/widgets/stats/`
> returns `WidgetStatsOut{count: MeasuredOut}`, whose formula is
> `onboarded + pending` with both terms on the wire (`apps/example/api.py`,
> `apps/example/schemas.py`). The tour below narrates the original widget
> path; the upward-axis pieces are noted where they touch it, and the files
> are beside you.

The feature, in one sentence: *a member creates a widget in the part of the
tenant they act for; onboarding waits a bounded stretch for a human approval; the
row, the audit trail, the events and both doors agree about all of it.*

One idea rides through everything below and is worth meeting before any door
does: **the acting hat**. A tenant is a tree of organizations, and every
request says which part of the tenant it acts as with the `X-Org` header —
resolved and revalidated against the actor's memberships on every request by
one function, `core.middleware.resolve_org`, which all the doors call. The
resolved hat is where a created row lands (§5), the second half of every
org-scoped read (§6), and it rides the workflow headers so activities running
days later still act as the branch (§11). When a step below says "the hat", it
means this.

## 1 · The model — `apps/example/models.py`

`Widget` inherits `OrgScopedModel` — which is `TenantScopedModel` plus an
`organization` foreign key — and that single choice sets everything downstream:

- **Rule 2**: every concrete model inherits `core.models.BaseModel` (UUIDv7 pk,
  `created_at`, `updated_at`). `OrgScopedModel` carries it; a bare
  `models.Model` is a fired canary.
- **Rule 15**: the field policies are visible — `onboarded_at` ends `_at`
  because it is a `DateTimeField`; `on_delete` is explicit on `owner`; there is
  no `FloatField` and no `is_deleted` boolean anywhere.
- The invariant lives in `Meta.constraints` — a `UniqueConstraint` on
  `(tenant, owner, name)` — not in `clean()` or `save()`: a constraint runs
  always, a method runs when called.
- The two relation reads the schema publishes (`owner_email`,
  `organization_slug`) are **properties, not Pydantic aliases**, and the model
  docstring says why: the MCP transport serializes by alias, so an alias split
  the two doors' key sets on the same row — a door-parity bug (rule 17) no
  value test could see. The fix and its story are recorded as
  ADR example-3, cited right there in the source.

Org-scoped versus tenant-scoped is the architect's call
(`django-architect` § A), and the model docstring records the asymmetry: wrongly
org-scoping costs a `visible_to(root)`; wrongly tenant-scoping leaks rows
between the tenant's own customers.

## 2 · The migrations — `apps/example/migrations/`

A chain of migrations and one `max_migration.txt` leaf. **Rule 6**: one leaf per
app, kept by django-linear-migrations, so two rungs touching one app collide in
git before they collide in CI. **Rule 22**: expand/contract, and the history
demonstrates it — `0006_widget_organization.py` adds the column nullable,
`0007_widget_organization_backfill.py` fills it (a `RunPython` with a reverse),
`0008_widget_organization_required.py` tightens it. Three migrations where one
"simpler" one would have broken a deploy mid-rollout.

Migrations are made **inside the rung, by the builder**, with
`makemigrations example`; `makemigrations --merge` is forbidden — a merge means
two agents touched one app, which is a PM ordering failure to surface, never to
patch (`CLAUDE.md` § "The schema discipline").

## 3 · The registration — `apps/example/apps.py`

The whole registration is the `AppConfig`: `name = "apps.example"` and a
`depends_on` tuple naming what this app may import. `INSTALLED_APPS` is derived
from `apps/*/apps.py` (`config/settings/discovery.py`); the mounts discover the
conventionally named files. **Nothing in `config/` or `pyproject.toml` is
edited to add an app** — that is what lets one agent per app run in parallel
without a shared file — and **rule 7** holds each app to its own declaration.

## 4 · Authorization — `apps/example/policies.py` and `apps/core/authz.py`

Roles are data (`Membership.role`); policies are code. The app's `policies.py`
declares predicates — `can_create`, `owns_or_is_privileged`, `can_approve` —
and `core.authz.require(actor, action, obj)` consults them. The division is
**rule 13**'s second half: *the door authenticates, the service authorizes.* A
permission check in a route would be one copy per door of a rule that must have
exactly one.

Two walls stand behind this, both **rule 24**: `Membership.role` is written
only by the membership services (the escalation wall — no grant above your own
effective role or outside your subtree), and org-scoped reads always carry
`visible_to`. And one seam is already on main for the write side:
`core.authz.may_be_named(actor, obj)` answers "could you have *reached* this
row to name it" — downward through the hat's subtree, or upward exactly one
model-population wide, for models that declare `InheritedDownward`. Its
`# reach:` comment grammar is house rule 26, live in `quality/rules.yaml`
(id `26`, ratcheted over a measured backlog); the full design is the
docstring in `apps/core/authz.py`.

## 5 · The services — `apps/example/services.py`

Every write in the feature is here, and nowhere else (**rule 4**: no logic in
signals — the app ships no `signals.py` on purpose; **rule 10**: doors never
write). Every function is `@service` (**rule 13**): keyword-only checked at
import, atomic, traced, logged, audited (`apps/core/service.py` is the
decorator and its docstring is the specification). Every name begins with a
verb from the declared lexicon (**rule 16**).

Walk `create_widget` line by line — it is the canonical write:

1. `require(actor, "widget.create")` — authorize before touching anything.
2. **Fail closed on every unresolved scope**: no `actor.user` → `Invalid`
   (the system actor cannot own a row); no `actor.org` → `Invalid` (a row with
   no organization would be invisible to every read, including the root's).
3. **The hat decides where the row lands.** There is deliberately no
   `organization=` parameter: a caller that could name one could write into a
   branch it holds no membership over. The row is written into `actor.org`,
   the hat the door resolved from `X-Org` and revalidated this request.
4. `full_clean()` under `as_invalid()` — Django's validation, spoken in the
   domain's refusal vocabulary (**rule 14**: no HTTP below the doors).
5. `_publish(WIDGET_CREATED, ...)` — the event, emitted *inside the write's
   transaction*, through `core.bridge` (the upward-call registry — a lower
   layer never imports a higher one). The name is a constant from
   `apps/example/events.py`, never a literal (**rule 16**).
6. `start_workflow_on_commit(...)` — onboarding waits for a person, so it is a
   workflow, registered on this transaction's commit: a create that rolls back
   onboards nothing. The id comes from `workflow_id(tenant=..., app="example",
   noun="widget", key=str(widget.pk))` — deterministic (**rule 18**), so a
   retried create starts one run, not two. The **hat rides along** (`org=`),
   so activities running days later still act as the branch, not the tenant.

Then read `approve_widget`, the counterpart: it **writes nothing**. The
approval is a signal to the waiting workflow (`signal_workflow`, with the same
derived id — never remembered, never passed in). The row changes when the
workflow's own activity says so; a service that set `onboarded_at` here would
be claiming an outcome the run has not reached. Approving twice while the run
waits is deliberately `ok` — a retried request must not be told it conflicted.

Note the module's `LOG_KEYS` at the top: redaction is an allow-list, not a
blocklist (`apps/core/service.py`), and `notes` — customer prose — is
deliberately not on it.

## 6 · The selectors — `apps/example/selectors.py`

**Rule 12**: reads and writes are separate — `selectors.py` never writes,
`services.py` never returns a queryset for display. The reason is the doors:
REST, MCP and (later) sockets all need "one widget, in this tenant, visible to
this hat, or a refusal", and a selector is where that lives once.

`list_widgets` is one line that carries three rules:

```python
Widget.objects.for_tenant(tenant).visible_to(org).select_related("owner", "organization")
```

- `for_tenant(tenant)` — **rule 8**, whose data; fails closed on `None`.
- `.visible_to(org)` — **rule 24**, which part of their network; also fails
  closed. A read that stops after the first half hands a sub-seller the whole
  tenant, and the gate refuses that shape by AST.
- `select_related` is **the contract, not an optimization**: `WidgetOut` walks
  both relations per row, so without it a page of fifty is a hundred and one
  queries. The query pin in the tests (**rule 5**) turns removing it into a
  failure instead of a slow page.

`get_widget` raises the *same* `NotFound` for a row in another tenant, a
sibling branch, one level up the tree, or one that does not exist — a 403
would tell the caller the row exists, which is the fact the scoping hides.

(The upward axis is visible here too:
`get_governing_widget_policy` reads
`WidgetPolicy.objects.for_tenant(t).governing(org)` — nearest ancestor wins,
opt-in via `InheritedDownward`, fail-closed like both halves above. The
mechanism is `apps/core/models.py`; the worked read is this file.)

## 7 · The schemas — `apps/example/schemas.py`

`WidgetIn`, `WidgetPatch`, `WidgetFilter`, `WidgetOut`, `WidgetPage` — the
suffix grammar of **rule 16**, and one schema per shape *shared across the
doors*: the REST response, the MCP tool output and the event payload are the
same Pydantic classes, which is what makes door parity checkable at all.

The platform's other wire shapes live in `apps/core/schemas.py`, including
`MeasuredOut{value, basis}`: any number the server computes travels with the
formula and the inputs it was evaluated over, as `Decimal` (**rule 15**), so no
client ever computes it again. Its docstring also records the ratified naming
deviation — the ADR wrote `Measured`; rule 16's suffix grammar won.

## 8 · The REST door — `apps/example/api.py` and `config/api.py`

The router restates `auth=API_AUTH` rather than inheriting it (**rule 3**:
explicit auth on every route or router, never `auth=None` outside the
allow-list), names `PREFIX = "widgets"` so the URL says what the resource is,
and declares its narrowings as constants — `ORDERING` and `SEARCH_FIELDS` are
allow-lists, because `?ordering=` fed straight into `.order_by()` is a
full-table sort on any column a client cares to name.

The list route is `@paginate`d (**rule 3**), scoped first and only narrowed
after, and reads through the selector (**rule 10**). The write routes call
`_acting()` — which refuses a request with no resolved tenant — and then a
service; whether the actor *may* is not decided here (**rule 13**, from the
door's side).

`config/api.py` is the other half of **rule 14**: the one place a refusal
becomes a number. `STATUS_FOR` there is the whole mapping — read it rather
than remember its length; it is walked up the MRO, so a product's
`InsufficientFunds(Conflict)` is a 409 for free. The body
comes from `core.exceptions.wire_refusal` — `{detail, code, errors?,
remedies?}` — composed once and rendered identically by the machine door. The
Django-native escapes (`ValidationError`, `IntegrityError`, `Http404`,
`ObjectDoesNotExist`, throttling) are mapped in the same file so a database
constraint answers a machine with a `conflict` body, not a 500 and a page of
HTML. Run `uv run python manage.py introspect` and read the `refusals` section:
every registered code with its boundary, fact and remedies — that is the
product's refusal vocabulary, readable instead of guessable.

## 9 · The MCP door — `apps/example/mcp.py`

**Rule 17 is what this file exists to demonstrate**: every capability the REST
door has, capability for capability, over the *same* selectors, services and
schemas. The tool
takes who-is-calling from the principal the token middleware left on the ASGI
scope — never from an argument, so no caller can name a tenant, org or user it
holds no token for. The hat comes from the same `X-Org` header, resolved by
the same function (`resolve_org` in `apps/core/middleware.py`), which is what
makes the two doors agree on the same rows for the same hat. `tool_call`
(`apps/core/mcp.py`) translates domain refusals once, the way `config/api.py`
does — one composer, two doors. `tests/test_mcp.py` diffs the two registries
out of `introspect`, so a capability that exists on one door and not the other
is a failing test, not an observation.

## 10 · The events — `apps/example/events.py`

Four constants, and that is the whole file: `example.widget.created`,
`.updated`, `.deleted`, `.onboarded` — the `<app>.<noun>.<past-verb>` grammar
of **rule 16**, declared once per app and never a literal at a call site,
because an event name is a published contract a webhook subscriber matches on.
A past-tense verb always: an event states that something *has happened*;
`widget.create` would be an instruction, and instructions are service calls.
`_publish` in `services.py` says them through `core.bridge` inside the write's
transaction; `apps/events` (the outbox, the signed deliveries with retries and
dead-letter, the realtime push) takes it from there. `WIDGET_ONBOARDED` is the
one a request cannot emit — it is stated by an activity, days later, same
grammar, same file.

## 11 · The workflow — `apps/example/workflows.py` and `activities.py`

`WidgetOnboardingWorkflow` is the honest answer to "where does the thing that
waits go": an activity that changes a row, a long wait for a human that may
never come, and a statement of what happened at the end. None of the three
fits in a request. How long the wait is, is the module's own
`APPROVAL_DEADLINE` constant — read it there, never here.

**Rule 9, visible in the imports**: `workflows.py` imports `timedelta`,
`temporalio.workflow` and its own `types.py` — nothing else. No ORM, no
network, no clock, no randomness, and **no import of `activities.py`**:
activities are invoked *by name*, because importing them would drag the ORM
into a module that must replay identically years from now. Even the workflow's
timestamp is the activity's. A timer that long costs nothing while it runs,
survives every restart, and ends in exactly two ways — somebody signalled, or
nobody did; **both are outcomes, neither is an error.** The run also closes
out its own `WorkflowRun` row on both paths, so the bookkeeping never says
`running` beside an execution that ended.

`activities.py` is where the world is touched (**rule 10** still holds:
neither activity writes a model — both call services). Every activity takes
the same three steps a product's will: **restore the principal, read through
the scoped managers, call a service.** Tenant, user and org arrive on the
workflow's Temporal *headers* — unpacked by the interceptor into
`workflow_context()` — never in the payload, so no caller reaches another
tenant or branch by putting the wrong id in an argument. **The hat is
restored, not widened**: a run started by a sub-seller reads with that
sub-seller's `visible_to` and its audit rows say so. Plain `def`, run in the
worker's thread pool, `close_old_connections()` at both ends, idempotent —
because Temporal guarantees at-least-once.

The dataclasses crossing the boundary live in `apps/example/types.py` — the
one module a workflow may share with the world.

## 12 · The admin — `apps/example/admin.py`

`WidgetAdmin` inherits `core.admin.ServiceModelAdmin` (**rule 21**): writes go
through services (so **rule 13**'s audit row happens with `door=admin`), and
scoped models are filtered by the acting tenant. The admin is a door like any
other; a raw `ModelAdmin` on a scoped model is a violation.

## 13 · The proof — `apps/example/tests/` and the gate

The test directory is the map of what "done" meant. `ls apps/example/tests/`
is the current list; four of them matter to an arrival:

- `test_api.py` — the property through the door a user uses, with the **query
  pin** (**rule 5**) and the **sibling-absence tests**: another tenant's rows
  absent, and a sibling branch of the *same* tenant's rows absent too. The
  shared fixtures are `apps/conftest.py`'s (`api`, `tenant`, `other_tenant`,
  `owner`, `stranger`, `nomad`, `root`).
- `test_mcp.py` — door parity (**rule 17**), by diffing registries.
- `test_doors_over_the_wire.py` — the A11 net: real HTTP, real sockets, the
  production shapes the test harness would otherwise substitute away
  (`docs/product/misses.md` is why this file exists).
- `test_workflows.py` — the run under Temporal's time-skipping test
  environment: the week-long wait, both endings.

`./scripts/check.sh --loop` is run by the builder, per rung, in a worktree with
its own database (`scripts/db.sh`); and by the verifier, once, as the consult —
a `VERDICT REUSED` banner is the gate, a miss completes and is recorded. The
full gate self-tests the enforcement —
every canary planted through the real scope must fire, every negative must
stay silent, and a dead canary is exit 2, not a pass. Run the gate **bare, or
redirected to a file — never piped**: it detects a piped stdout and refuses
with exit 2 (`scripts/check.sh`), because a pipe replaces the exit status you
came for with the filter's.

## 14 · What one POST leaves behind

The part of the architecture you cannot see in any single file: the trail one
successful `POST /api/v1/widgets/` writes, all of it queryable, none of it
optional.

- **The row** — `example.Widget`, with `tenant`, `organization`, `owner`,
  UUIDv7 pk, `created_at`.
- **The audit row** — `core.audit.AuditEntry`, written by `@service` inside
  the same transaction: actor and actor kind (human, agent, system), the
  service name as the action, the object, the **door** it came through, the
  outcome, the input redacted per `LOG_KEYS`, and the correlation ids.
  Append-only (rule 20) — the `append_only = True` marker on the model is what
  the enforcement reads.
- **The event and its outbox row** — `example.widget.created` in
  `apps/events`' tables, atomic with the write, dispatched after commit by a
  workflow: signed webhook deliveries with retries and dead-letter, and the
  realtime push to the tenant's socket group.
- **The workflow run** — a `WorkflowRun` row (visibility) and a Temporal
  execution under the deterministic id, headers carrying tenant, user and
  org, now waiting on a timer that costs nothing.
- **The trace and the log lines** — one span per service
  (`example.create_widget`), `.called` on the way in, structured through
  `core.log` (rule 19), all under the request's trace.

A refusal leaves a trail too: the audit row (outside the rolled-back
transaction), the `.failed` log line, and a `{detail, code, remedies}` body a
client can branch on. Nothing here un-happens; it accumulates, and that is the
provenance the whole class of products this template serves is bought with.

## 15 · Drive it yourself, from empty

The fastest way to make all of the above concrete — and the shape every field
test takes, because tenancy on means *an empty database is a product where
every door correctly returns nothing*, indistinguishable from a broken one
until there is a tenant, a person and a token:

```bash
./scripts/setup.sh                  # compose stack up (db · redis · temporal · zitadel),
                                    #   .env (+ ZITADEL_PAT), this worktree's database,
                                    #   migrate, zitadel_seed — idempotent, run it any time
source scripts/db.sh                # export DATABASE_NAME for THIS worktree — see below
uv run python manage.py seed        # a tenant, an owner, a member, a token (printed once)
./scripts/serve.sh                  # uvicorn; /api/v1/docs and /mcp are live
./scripts/worker.sh                 # the Temporal worker, second terminal
```

**`source scripts/db.sh` is not decoration, and it comes before every
database-touching `manage.py` you run by hand.** Each worktree owns a database
named for its branch, and the scripts (`setup.sh`, `serve.sh`, `worker.sh`,
`test.sh`) source `db.sh` themselves — but a bare `manage.py seed` in a shell
that has not sourced it knows nothing of that, falls back to the default
database (the checkout-derived name `setup.sh` wrote into `.env`; `scripts/db.sh`), and seeds some *other*
checkout's data. That is not hypothetical: a verifier did exactly that.
Source it once per shell, first.

Running two checkouts' servers at once? The port is the door:
`PORT=<n> ./scripts/serve.sh` starts this one somewhere else. `scripts/serve.sh`
holds the default and documents the override in its own header — read it there.

Then, with the seeded token: `GET /api/v1/widgets/` (empty page, envelope
`{items, has_more, next_cursor, count}` — cursor-paged, and `count` is `null`
until you send `?include_count=true`) · `POST` one (201, `WidgetOut`) · watch
the run appear in
the Temporal UI (the port `compose.yaml` publishes it on) — its first activity has already set
`onboarded_at`, and now it waits · `POST .../approve/` and watch the wait end
and `example.widget.onboarded` emit, `approved: true` ·
`GET` with a wrong `X-Org` and read the empty page fail closed. Every step of
the tour above becomes an observable behavior in about two minutes.

## The path, compressed

```
X-Org header ──► resolve_org (core/middleware.py) ──► the hat, revalidated
POST /api/v1/widgets/       tool create_widget          door: authenticate, resolve
        └────────────► services.create_widget ◄────────┘   (rules 3, 10)
                         require · fail-closed org       (rules 13, 24)
                         write + audit, one transaction  (rules 13, 20)
                         _publish(WIDGET_CREATED)        (rule 16; the outbox)
                         start_workflow_on_commit        (rule 18; the hat rides)
                                  │
                    WidgetOnboardingWorkflow (rule 9: deterministic)
                       activity: mark_widget_onboarded ──► service, as the hat
                       wait ≤ APPROVAL_DEADLINE ◄─ approve_widget signals (a service, no write)
                       activity: announce ──► service emits WIDGET_ONBOARDED
```

Every arrow lands in a service. That is the whole architecture; the rest is
enforcement making sure it stays true.
