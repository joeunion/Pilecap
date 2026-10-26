# Worked examples for the born-to-standard checklist, and the report template

Every item in SKILL.md §1 has a marked worked example already in the tree.
Read the real file before writing your own — these are pointers with the
load-bearing lines quoted, not substitutes for the source.

## Lifecycle declarations (rule 31)

`apps/example/models.py` is the teaching text — all three self-declared kinds
with the reasoning in comments. The shape, for a model you own:

```python
from typing import ClassVar
from apps.core.lifecycle import Lifecycle, LifecycleKind

class Widget(TenantScopedModel):
    lifecycle: ClassVar[Lifecycle] = Lifecycle(kind=LifecycleKind.BOUNDED)
    # BOUNDED carries no reason: a cascade is a mechanism the schema states.
    # UNBOUNDED / APPEND_ONLY carry reason= (a sentence a reviewer can
    # DISAGREE with) and a dated trigger. See WidgetPolicy in the same file.
```

A `PURGED` declaration names its sweeper (`purged_by=...`) and that callable
must be REACHED — activity → workflow → a `ScheduleDeclaration` in some app's
`SCHEDULES`. Worked example: `apps/connections/models.py` (InboundWebhook)
paired with `SCHEDULES` in `apps/connections/activities.py`.

Third-party tables (allauth's, `django_session`, `django_admin_log`) never
grow the attribute; whichever app owns the concern declares them in its own
`apps/<x>/lifecycle.py`:

```python
# apps/accounts/lifecycle.py
def register(registry: LifecycleRegistry) -> None:
    registry.declare(EmailAddress, Lifecycle(kind=LifecycleKind.BOUNDED, ...))
```

The hook is ONLY for models that cannot self-declare: `LifecycleRegistry`
refuses a third-party registration for a model that carries its own
`lifecycle` ClassVar — a second opinion about the same table is the exact
disagreement the design forbids (`apps/core/lifecycle.py`, the declare()
refusal).

## Route contracts and refusals (rules 41, 47)

`apps/example/api.py` — every convention a route has to satisfy, visible. The
docstring IS the contract: first line the title (short phrase, no Markdown, no
full stop), the description below it, and the same docstring renders the MCP
twin. No `summary=`/`description=` kwargs (a second copy), no queue-row
references, no `_underscore` identifiers, no `@service`, no `manage.py`
anywhere in contract prose.

```python
@router.post("/", response={201: WidgetOut}, url_name="widget-create")
@refuses("forbidden", "not_found", "rate_limited")   # apps/example/api.py::create_widget_route
def create_widget_route(request: TenantRequest, payload: WidgetIn) -> ...:
    """Create a widget

    <description a stranger can act on — what it does, what it needs>
    """
```

Every code in `@refuses(...)` is one `core.exceptions` registers. A NEW code
needs its `CODE_STATUS` line (`apps/core/api/docs.py`) in the same rung —
rule 47 reports the exact table line to add when it is missing, and an
existing code that goes missing anyway is "an undiagnosed drop".

Marker hygiene while you are in these files: remedies' destinations are
`<kind>:<name>` tokens; do not add kinds, and do not spell a censused marker
(e.g. `shell:`) in the Remedy docstring or any prose — the counting guards
read prose too, and prose spelling the marker gets counted as a phantom
override.

## The door-pair parity test (rule 46)

`apps/example/tests/test_doors_over_the_wire.py`:

```python
#: House rule 46. The door pair this module answers for `apps/example`, read
#: by the gate off this module-level assignment.
DOOR_PAIR = ("rest", "mcp")
```

The body drives the SAME row through the REST door and the MCP door and
compares ON THE WIRE — never through the schema both sides happen to share,
and never only through the test client (which disables CSRF and swaps the
channel layer). The expected key set is written out by hand: a pin derived
from the thing it pins cannot fail. A `DOOR_PAIR` claiming a pair the app does
not own is itself refused by the rule.

## Schedules and workflow runs (rules 28, 18)

Periodic work is a `ScheduleDeclaration` in the app's discovered `SCHEDULES`
(`apps/core/schedules.py` defines the shape; worked examples:
`apps/events/activities.py` — `SCHEDULES = [PURGE, RECONCILE_OUTBOX]` — and
`apps/workflows/activities.py`). Never a cron entry, a thread, or a hand-made
Schedule object.

Rule 28's two patterns, exactly one per workflow class:

1. **Owns a run row**: the `@workflow.run` method reaches the finish seam —
   a method whose name ends `_finish`, or the `mark_run_finished` activity —
   and reaches it LAST, on the failure path too. Worked example:
   `apps/example/workflows.py` (`_finish(status=...)` in both arms).
2. **Owns no row**: the class declares `owns_no_run = True` — the
   schedule-started population.

Workflow ids are built by `workflow_id()` (rule 18), never random. And the
standing wall: nothing in a `workflows.py` touches the ORM, the network, the
clock or randomness — activities do the I/O (rule 9).

## Strict bodies (django-conventions §6)

The one seam lives in `config/api.py`: an unknown field in an `In`/`Patch`
body is refused as `invalid_body` NAMING the field, never dropped. The MCP
door is strict the same way off the same model — strictness is enforced off
the model, one seam, not duplicated per door. If you add a schema, add the wire
assertion that an unknown field is refused; `apps/core/tests/` has the
envelope census these assertions join.

## The report template

```
<still working | done, stopping | stuck on X>

BRANCH:    <pasted output of `git branch --show-current`>
BASELINE:  <sha from step zero>  (reset from <sha> — only if it happened)
FINAL:     <commit sha>   MIGRATIONS: <n, and the app>

RED / GREEN
  <the pasted red — command + failing output — then the same probe green>

CRITERIA
  C1: met — <artifact: test node id / wire response / file:line>
  C2: not met — <what stands in the way>

DEVIATIONS
  <every departure, with reason — or "none">

DISPROVED IN THE BRIEF
  <claim → evidence — or "nothing">

BLIND SPOTS
  <what this work does not cover; what these tests would not catch>

LEXICON DELTA
  <new verbs / events / tags / refusal codes / allow-list lines — or "none">

CLEANUP CENSUS
  <what you created and tore down; what remains (worktree + its DB only)>
```
