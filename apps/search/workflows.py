"""The startup reconcile, as a durable run. **Ordering only — no I/O here.**

House rule 9: workflow code is deterministic. Nothing in this file reads a
registry, opens a socket, asks the time or touches the ORM; it calls two
activities and decides the order. Everything that could give a different answer
on a replay lives in `activities.py`, which is exactly where a Temporal retry
can do something about it.

**Why a workflow at all**, rather than a few lines in the worker's startup: a
rebuild is minutes of streaming for a large table and it must survive a deploy,
a restarted container and a machine going away — which is the house's own
sentence about anything that waits or retries. It also makes the reconcile
*visible*: a rebuild that is happening is a run somebody can look at in the
Temporal UI, and a rebuild that failed is a run with an error on it rather than
a silence.

**Serial, and deliberately.** One kind at a time, inside one run, with a
deterministic id per task queue and `SKIP` on overlap. A deploy that changes
five declarations therefore pays five rebuilds one after another instead of
five index builds competing for one container's memory — the tradeoff the
owner's ruling records in as many words ("many-declaration deploys serialize").
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from apps.search.types import ReconcileOutcome

#: The two activities, **named as strings** and not imported (house rule 9).
#: Importing `apps.search.activities` here would pull the Meilisearch client and
#: the ORM into the workflow sandbox — the exact non-determinism the rule
#: refuses — and the string is what Temporal dispatches on anyway. The
#: `apps/exports/workflows.py` precedent, verbatim.
LIST_KINDS_ACTIVITY = "list_search_kinds"
RECONCILE_ACTIVITY = "reconcile_search_index"

#: How long the enumeration may take. It imports modules and returns a list of
#: strings; a minute is generous and a hung one is worth failing.
LIST_TIMEOUT = timedelta(minutes=1)

#: How long ONE kind's reconcile may take. A rebuild streams a whole table into
#: the index, so this is measured in hours rather than minutes — a ceiling that
#: catches a wedged activity without capping an honest rebuild of a large
#: product's biggest table.
RECONCILE_TIMEOUT = timedelta(hours=2)

#: The END-TO-END bound on one kind, queue time included, and it is the half
#: `start_to_close_timeout` above cannot give: that clock only starts once a
#: worker has PICKED THE ACTIVITY UP, so an activity scheduled and never started
#: — no worker polling this queue, every slot taken, a worker that died between
#: the schedule and the poll — sits under an unset `schedule_to_start`, which is
#: infinite, and the run waits for ever. `apps/core/workflows.py`'s prober took
#: this exact lesson before.
#:
#: Generous, because it has to cover the honest worst case — the bounded
#: attempts below, each allowed the two-hour rebuild ceiling — and its job is to
#: stop an infinite wait rather than to be tight.
RECONCILE_DEADLINE = timedelta(hours=7)

#: And the enumeration's, on the same argument. It returns a list of strings.
LIST_DEADLINE = timedelta(minutes=5)

#: How many times one kind is retried INSIDE a single pass.
#:
#: **It used to be unbounded, and the reasoning was right while the placement
#: was wrong.** A Meilisearch that is down at boot is the
#: case this policy exists for, and a reconcile that gave up would leave an index
#: un-materialised until somebody noticed — the silent class, reintroduced one
#: layer in. That argument still holds. What it does not license is retrying
#: *without end inside one run*: the run then never completes, the ledger holds
#: an execution that is neither succeeded nor failed, and nobody can tell "still
#: trying" from "wedged". Under the time-skipping server the machinery suite
#: drives every declared machine with, it is a plain hang —
#: `test_the_sweeps_still_run_from_a_live_worker` died 22 seconds in, saying
#: only "No completion event found".
#:
#: **So the never-give-up moved to where it is honest: the schedule's next
#: tick.** Three attempts absorb a restarting container; a genuine outage
#: completes the pass with a finding and another pass starts an hour later
#: (`activities.RECONCILE_EVERY`), for ever, with one readable run row per
#: attempt instead of one unreadable run that never ends. Same posture the
#: search circuit takes one layer up: an unreachable index is a degraded
#: state the product announces and survives, never one it dies of.
#:
#: **Three**, because in-run retries are now for a TRANSIENT failure — a dropped
#: connection, a container in the middle of coming back — while an outage is the
#: schedule's business. Three attempts one and two seconds apart cover the first
#: and cost nothing; nothing covers the second except asking again later, which
#: is what the tick is.
#:
#: **And an auth refusal counts as an outage here** — a reachable engine that answers `401
#: invalid_api_key` — the shape a keyed compose container gives a caller with no
#: key, and the one that actually bit — arrives as the same `EngineUnavailable`
#: a refused connection does (`engine.state`), so it is bounded by this same
#: constant and reported by the same finding. Both are the world saying no, and
#: neither may spin. `tests/test_reconcile.py::
#: test_an_unreachable_engine_and_a_refused_key_are_the_same_class` is what
#: keeps that true rather than incidental.
RECONCILE_ATTEMPTS = 3

#: The retry behind each kind — bounded, per the constant above.
#:
#: **`initial_interval` is one second and not five, and that was measured.** The
#: time-skipping test server does NOT skip activity retry backoff: it skips
#: *workflow* timers, and a retry interval is the server's own scheduling. So
#: every second of backoff here is a second on every full gate run, and at
#: 5s → 10s the machinery test took 17.6s where at 1s → 2s it takes 5.8s (same
#: tree, same assertion, one constant changed). One second is also the better
#: production value for what these retries are now FOR: a container that is
#: coming back is back in about that long, and anything slower than three
#: seconds is an outage the hourly tick is the honest answer to.
#:
#: `maximum_interval` does not bind at three attempts — it exists so that
#: raising `RECONCILE_ATTEMPTS` later cannot silently produce an hour-long wait
#: inside one run, which is the failure this whole block is undoing.
RECONCILE_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),
    maximum_attempts=RECONCILE_ATTEMPTS,
)

#: How many links of a cause chain `_reason` walks. Bounded because a cause
#: chain is somebody else's data structure; three is
#: `apps/workflows/workflows.py::_reason`'s number and this is its shape.
REASON_LINKS = 3


def _reason(failure: BaseException) -> str:
    """The cause chain, joined — never the wrapper alone.

    Temporal wraps an activity's own exception in an `ActivityError` whose
    `str()` is `"Activity task failed"`: true, and useless to whoever reads the
    run six weeks later. What an operator needs on a reconcile that could not
    finish is the engine's own complaint — "Meilisearch did not answer about
    djb_..._widgets" — and that is three links down.

    Deterministic (house rule 9): it reads nothing but the exception it was
    handed. Restated here rather than imported for the reason
    `apps/core/workflows.py` restates it — a workflow module imports its own
    app's `types.py` and the standard library, and nothing else.
    """
    parts: list[str] = []
    current: BaseException | None = failure
    for _ in range(REASON_LINKS):
        if current is None:
            break
        text = str(current).strip() or type(current).__name__
        if text not in parts:
            parts.append(text)
        current = current.__cause__
    return ": ".join(parts)


@workflow.defn
class ReconcileSearchIndexesWorkflow:
    """Make every declared kind's index agree with its declaration.

    Started by this app's `ScheduleDeclaration`, which every worker boot makes
    real — so the answer to "who runs this?" is "the deployment, at the moment it
    comes up", and never "whoever remembers".
    """

    #: House rule 28's second population, said out loud: this run is started by
    #: a schedule and no service asked for it, so there is no `WorkflowRun` row
    #: for it to close. Nobody is waiting on a visibility row for the
    #: deployment's own housekeeping — the ledger would be being made to carry a
    #: row nothing reads.
    owns_no_run = True

    @workflow.run
    async def run(self) -> ReconcileOutcome:
        """One pass: enumerate the kinds, then reconcile each in turn — and **finish**.

        Returns the outcome per kind — `unchanged`, `created` or `rebuilt` — so
        the run's own result says what it did. A run whose outcomes are all
        `unchanged` is the healthy steady state and reads as one at a glance,
        which is what a reconcile owes anybody looking at it.

        ## Why the failures are caught

        The first version awaited both activities and let them raise, behind a
        retry policy with no maximum attempts. Both halves of that were wrong
        together and neither is wrong alone.

        An unreachable Meilisearch is not an error the deployment should die of
        — that is the whole of ADR search-2's posture, and the same
        posture was built into the read path one layer up (the index down is a degraded
        state, answered from Postgres, announced on the spine, never an outage).
        But a run that retries for ever **inside itself** does not express that
        posture; it hides it. The execution is neither succeeded nor failed, the
        ledger cannot tell "still trying" from "wedged", and under the
        time-skipping server the machinery suite uses it is a hang with no
        subject: `test_the_sweeps_still_run_from_a_live_worker` gave up after
        22 seconds saying "No completion event found".

        So the pass **completes with a finding**. `incomplete` carries the
        engine's own complaint, walked three links out of Temporal's wrapper,
        and the never-give-up moved to the schedule: another pass starts an hour
        later, and another after that, for ever. Same convergence, a readable
        run row per attempt, and an operator who can see the difference between
        an index that is behind and an engine that is gone.

        **Partial passes are said as partial.** A kind that could not be
        reconciled leaves the ones that could in `outcomes` — "three of four" is
        a different fact from "none", and collapsing them would make a single
        bad declaration look like an outage.

        `Exception` and not a narrower type: what reaches here is Temporal's own
        wrapper around whatever the activity died of, and enumerating those is a
        second copy of somebody else's exception hierarchy.
        `asyncio.CancelledError` is a `BaseException`, so a cancel is not
        swallowed by this.
        """
        try:
            kinds: list[str] = await workflow.execute_activity(
                LIST_KINDS_ACTIVITY,
                start_to_close_timeout=LIST_TIMEOUT,
                schedule_to_close_timeout=LIST_DEADLINE,
                retry_policy=RECONCILE_RETRY,
            )
        except Exception as failure:
            # Nothing could even be enumerated, so there is no partial result to
            # report — the finding is the whole answer.
            return ReconcileOutcome(incomplete=_reason(failure))

        outcomes: dict[str, str] = {}
        incomplete = ""
        for kind in kinds:
            try:
                outcomes[kind] = await workflow.execute_activity(
                    RECONCILE_ACTIVITY,
                    kind,
                    start_to_close_timeout=RECONCILE_TIMEOUT,
                    schedule_to_close_timeout=RECONCILE_DEADLINE,
                    retry_policy=RECONCILE_RETRY,
                )
            except Exception as failure:
                # The FIRST reason is kept rather than the last: when the engine
                # is gone every kind fails with the same complaint, and the one
                # worth reading is the one that has not yet been retried into a
                # different-looking message.
                incomplete = incomplete or f"{kind}: {_reason(failure)}"
        return ReconcileOutcome(outcomes=outcomes, incomplete=incomplete)


WORKFLOWS = [ReconcileSearchIndexesWorkflow]
