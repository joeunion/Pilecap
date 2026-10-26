# Workflows and activities — the worked forms

The long form of `django-conventions` §7.

## A run row's error names the cause, not the wrapper

**A run row's `error` names the cause, not the wrapper.** Temporal wraps an
activity's own exception in an `ActivityError` whose `str()` is
`"Activity task failed"` — true, and useless to whoever reads the
`WorkflowRun` row six weeks later. Walk `__cause__` a bounded number of links
(three: wrapper → activity error → the activity's own complaint) and join
them; `apps/core/determinism.py::reason_of` is the worked form.

```python
# WRONG — the row says "Activity task failed" and the reason is gone
except Exception as error:
    await self._finish(status=RUN_FAILED, error=str(error))
    raise

# RIGHT — the row carries the activity's own complaint
except Exception as failure:
    await self._finish(status=RUN_FAILED, error=_reason(failure))
    raise
```

Bounded because a cause chain is somebody else's data structure; deterministic
because it reads nothing but the exception it was handed. Rule 28 sees that
the finish seam is *reached*; it cannot see what you put in it.

## The two files, in full

```python
# wrong — ORM, network and clock inside the workflow; importing the activity; a thread for "background" work
with workflow.unsafe.imports_passed_through():
    from apps.example.activities import send_welcome          # drags the ORM into the sandbox
async def run(self, tenant_id: UUID) -> None: httpx.post(url, json={"at": datetime.now().isoformat()})
threading.Thread(target=send_welcome, args=(Tenant.objects.get(pk=tenant_id).pk,)).start()

# right — types.py: stdlib only
@dataclass
class OnboardIn:  email: str
@dataclass
class OnboardOut: confirmed_at: datetime | None

# right — workflows.py: stdlib dataclasses/timedelta + temporalio.workflow + types; nothing else
from datetime import timedelta
from temporalio import workflow
from apps.example.types import OnboardIn, OnboardOut

@workflow.defn(name="OnboardTenant")
class OnboardTenant:
    def __init__(self) -> None:
        self.confirmed = False

    @workflow.run
    async def run(self, input: OnboardIn) -> OnboardOut:
        await workflow.execute_activity(
            "send_welcome", input,                                   # by NAME — never the imported function
            start_to_close_timeout=timedelta(seconds=30),            # retry policy, when not the default, here too
        )
        await workflow.wait_condition(lambda: self.confirmed, timeout=timedelta(days=7))
        return OnboardOut(confirmed_at=workflow.now())

    @workflow.signal
    def confirm(self) -> None:
        self.confirmed = True

WORKFLOWS: list[type] = [OnboardTenant]

# right — activities.py: plain def in the worker's thread pool, the principal from context, a service does the work
from collections.abc import Callable
from typing import Any

from django.db import close_old_connections
from temporalio import activity

from apps.core.actor import system_actor
from apps.example import services
from apps.example.types import OnboardIn
from apps.workflows.context import workflow_context

@activity.defn(name="send_welcome")
def send_welcome(payload: OnboardIn) -> None:
    close_old_connections()                                    # both ends: no request cycle out here
    try:
        tenant, _user_id, org = workflow_context()             # THREE — tenant, user id, acting hat
        services.send_welcome(                                 # idempotent; the service does the write
            tenant=tenant,
            actor=system_actor(tenant, org),                   # nobody clicked this; the hat still rides
            to=payload.email,
        )
    finally:
        close_old_connections()

ACTIVITIES: list[Callable[..., Any]] = [send_welcome]
```

Read `apps/example/activities.py` before writing your first one — it is the
shape above, in full, with the reasons in its docstring.

**What a workflow argument may hold.** *A workflow argument may hold only what
survives the sandbox's import wall — `str`/`int`/`float`/`bool`/`UUID`/nested
dataclasses; never a type from a module `temporalio` restricts (today:
`datetime`); `date`/`Decimal`/`timedelta` refused by the writer everywhere.
Three failure modes, one error message.* That sentence is the settled boundary,
and it is worth knowing why the three modes look alike, because two agents
already read the same error two different ways:

- **The converter is innocent.** On the pinned `temporalio` 1.31.0
  `value_to_type` handles `hint is datetime`
  (`converter/_payload_converter.py:852`) and `UUID` (`:1048`), and
  `AdvancedJSONEncoder.default` writes both (`:678`, `:691`). A plain
  round-trip through the converter passes for both types. Do **not** write a
  doc line saying `datetime` cannot be serialised: on this library it can.
- **The sandbox is where `datetime` dies.** `datetime` is a restricted module
  inside the workflow sandbox
  (`worker/workflow_sandbox/_restrictions.py:604-608` — the entry that lets
  `datetime.datetime.now()` be refused), so the class a workflow ARGUMENT is
  decoded against is a `_RestrictedProxy` and the converter's identity dispatch
  (`hint is datetime`) falls through. The proxy forwards `__repr__`, so the
  error names the very class it failed to recognise — which is exactly why the
  message reads as a converter bug and is not one. `sandboxed=False` decodes
  the identical shape.
- **`date` / `Decimal` / `timedelta` die at the writer**, in the client,
  loudly: `AdvancedJSONEncoder.default` (`:672-693`) has no branch for any of
  them and `json` raises `TypeError: Object of type date is not JSON
  serializable` before anything is dispatched. Note the asymmetry in what the
  two modes cost you: the writer's refusal is immediate and named, while
  `datetime` fails on the argument decode *inside* the worker — a workflow-task
  failure Temporal retries forever, silently, with the `WorkflowRun` row still
  reading `running`.

The practical rule that falls out: keep `types.py` dataclasses to
`str`/`int`/`float`/`bool`/`UUID` and nested dataclasses. An instant crosses as
an ISO `str` the activity parses, or as an `int` epoch; money crosses as an
integer of minor units or a decimal `str` the activity re-reads — never a
`float`, which house rule 15 already forbids on the field it came from; a
duration crosses as `int` seconds and becomes a `timedelta` inside the
workflow, where `timedelta` is an allowed import.

- **`system_actor(...)` is the right actor for an activity's own writes — but
  the files seam refuses it: `store_bytes`/`store_stream` need a
  person-carrying actor** (`actor.user` set), because a document records who
  filed it (`uploaded_by`, non-null, `PROTECT`) and a credential with no user
  behind it cannot file one. An activity storing bytes on somebody's behalf
  restores that person off the workflow headers and passes them for the file
  while keeping `system_actor` for its own rows — the `_actor_for` /
  `_person_for` split in `apps/exports/activities.py` is the worked shape,
  with the argument for why that pair is honest in its docstrings.

## Starting a run

- **Start a workflow from a service** with
  `apps.workflows.services.start_workflow_on_commit(*, workflow, arg, tenant,
  user=None, org=None, id, task_queue=None)` — sync, callable inside
  `transaction.atomic()`; it registers
  the start with `transaction.on_commit` and records the `WorkflowRun` row. The
  **`id` is required and deterministic**: build it with `workflow_id(*, tenant,
  app, noun, key)` — keyword-only, like every other service here (e.g.
  `workflow_id(tenant=tenant, app="orders", noun="onboard", key=str(order.pk))`
  — one id per tenant, app, noun and key, the same every time) so a retried
  service does not start a second run. Never from a model, a signal or a route
  directly. `arg` is one dataclass from `types.py`, not positionals. **`org=` is
  the acting hat the run is started under** and it is not optional in spirit:
  omit it and every activity in the run acts for the whole tenant instead of
  for the branch that asked, which is the leak the hat exists to close. Pass
  `actor.org`; a tenant-wide run (a platform workflow — email, dispatch) is the
  deliberate `None`. The async
  form, `await start_workflow(..., client=)`, exists for callers already on the
  event loop (an activity starting a child, the worker, a test); a sync service
  does not build a client.

## The clock

- **A workflow that needs one instant spells it `workflow.now()`** — the
  `workflow` in `from temporalio import workflow`, which is the blessed
  spelling and not a workaround. Rule 9's allow-list already carries
  `temporalio` (rule 9's statement — `python -m quality.gate --explain 9`), and the
  determinism check treats a call whose chain ROOT is the literal name
  `workflow` as sanctioned (`quality/checks/rule_9.py::_wf_sanctioned`), so `workflow.now()`,
  `workflow.uuid4()`, `workflow.random().randint(...)` and `workflow.time()`
  all pass while the bare `now`/`uuid4`/`random`/`time`/`hash` they replace are
  banned outright (`quality/checks/rule_9.py::_WF_BANNED_CALLS`). Two traps, both the rule's own
  declared blind spots: **the receiver has to be spelled `workflow`** — `from
  temporalio import workflow as wf` then `wf.now()` is read as a clock and
  reported, correct code and all; and what you USE the instant for is review's
  job, not the gate's. Anything the clock is only *carried* for — a timestamp
  a row wants — belongs in an activity, where the real clock lives.
