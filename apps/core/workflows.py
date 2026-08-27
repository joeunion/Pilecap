"""The standing integrations prober, as a durable run. **Ordering only — no I/O.**

House rule 9: nothing in this file reads a registry, opens a socket, asks the
time or touches the ORM. It calls one activity and returns what it said;
everything that could answer differently on a replay is in `activities.py`.

**Why a schedule and not a deploy step.** `deploy/release.sh`'s wall catches the
fake that was there at release time, and `scripts/setup.sh`'s epilogue catches
the one that was there at minute one. Neither catches **rot** — the key that
expires in November, the bucket policy somebody tightens, the ESP account that
lapses — and rot is the failure mode that has nobody looking for it by
construction. A deployment that was configured on Tuesday and is standing on a
fake by Friday is exactly the silence this census exists to break, so the
fourth surface is a clock.

**Why a workflow and not a cron line.** The house's own sentence: anything that
waits or retries is a workflow. It also makes the probe *visible* — a probe that
ran is a run somebody can look at, and a probe that could not read a seam is a
run with an error on it rather than a log line nobody greps.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from apps.core.types import ProbeOutcome

#: The activity, **named as a string** and not imported (house rule 9).
#: Importing `apps.core.activities` here would drag the census, the settings
#: read and the storage client into the workflow sandbox — the exact
#: non-determinism the rule refuses.
PROBE_ACTIVITY = "probe_integrations"

#: How long one census may take. Settings reads plus at most one bounded read
#: per live-probed integration; a minute is generous, and a census that has not
#: answered inside it is a census nobody should keep waiting for. **What the
#: budget means changed in wave 3**: it used to be how long before the RUN
#: DIED, and it is now how long before the run reports that nobody could look
#: (`run` below). A budget that kills the reporter is not a budget, it is a gag.
PROBE_TIMEOUT = timedelta(minutes=1)

#: The END-TO-END bound, queue time included, and it is the one that closes the
#: failure actually observed. `start_to_close_timeout` above only starts ticking
#: once a worker has PICKED THE ACTIVITY UP; an activity that is scheduled and
#: never started — no worker polling this queue, every activity slot taken, a
#: worker that died between the schedule and the poll — sits there under an
#: unset `schedule_to_start`, which is infinite, and the run waits for ever.
#: That is precisely the history the wave-3 investigation captured: events
#: ending at `activity_task_scheduled`, the execution still RUNNING, and the
#: client giving up. A standing probe with no deadline of its own is a run that
#: can hang for ever on a queue nobody is serving.
PROBE_DEADLINE = timedelta(minutes=2)

#: **One attempt, and the next tick is the retry.** The first version retried
#: three times with backoff, which is the right shape for work that must
#: eventually happen and the wrong shape for a measurement: three attempts
#: inside one run all measure the same half-minute, so they cost three timeouts
#: to learn one fact. A probe that could not read the world at 06:00 says so,
#: and asks again at 12:00 — which is the honest cadence for a detector whose
#: subject changes on the timescale of an expiring key.
PROBE_RETRY = RetryPolicy(maximum_attempts=1)

#: How many links of a cause chain the reason below walks. Bounded because a
#: cause chain is somebody else's data structure; three is
#: `apps/workflows/workflows.py::_reason`'s number and this is its shape,
#: restated rather than imported (`core` imports nothing above it).
REASON_LINKS = 3


def _reason(failure: BaseException) -> str:
    """The cause chain, joined — never the wrapper alone.

    Temporal wraps an activity's own exception in an `ActivityError` whose
    `str()` is `"Activity task failed"`: true, and useless to whoever reads the
    run six weeks later. `apps/workflows/workflows.py::_reason` is the worked
    form and this is the same three links; it is restated rather than imported
    because `core` imports nothing above it, and it is deterministic because it
    reads nothing but the exception it was handed.
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
class ProbeIntegrationsWorkflow:
    """Read the integrations census once, and let the run carry the answer.

    Started by this app's `ScheduleDeclaration`, which every worker boot makes
    real — so "who runs this?" is "the deployment, from the moment it comes up".
    """

    #: House rule 28's second population, said out loud: a schedule started this
    #: and no service asked for it, so there is no `WorkflowRun` row to close.
    owns_no_run = True

    @workflow.run
    async def run(self) -> ProbeOutcome:
        """One census, and **an answer either way**.

        The result is the run's own report: an outcome whose statuses are all
        `configured` is the healthy steady state and reads as one at a glance,
        which is what a standing probe owes anybody looking at it. The loud half
        — a warning per fake, an error per unreadable seam — is logged by the
        activity, where the sink can see it.

        ## Why the failure is caught (the wave-3 defect this closes)

        The first version simply awaited the activity and let it raise. That is
        the ordinary shape and it was wrong **here**, for a reason particular to
        what this workflow is: the census contacts things outside this process,
        so how long it takes is a property of the world. A black-holed endpoint
        does not raise — it hangs — and the activity then dies of its own
        `start_to_close_timeout` and took the whole run with it.

        Which is exactly backwards for a rot detector. **A standing probe that
        fails when the thing it probes is unreachable goes silent at the only
        moment anybody needed it**: the run row says `failed`, no census is
        produced, and the outage the probe existed to notice is the reason
        nothing was noticed. So "nobody could look" is DATA the run carries
        (`ProbeOutcome.incomplete`) and never an exception the run dies of.

        Found by `apps/workflows/tests/test_machinery_lifetime.py::
        test_the_sweeps_still_run_from_a_live_worker`, which drives every
        declared machine from a real worker under a time-skipping server — where
        skipped time races past any wall-clock activity and made the latent
        production defect deterministic. The test was right and the workflow was
        wrong.

        `Exception` and not a narrower type: what reaches here is Temporal's own
        wrapper around whatever the activity died of, and enumerating those is a
        second copy of somebody else's exception hierarchy. `asyncio.CancelledError`
        is a `BaseException`, so a cancel is not swallowed by this.
        """
        try:
            statuses: dict[str, str] = await workflow.execute_activity(
                PROBE_ACTIVITY,
                start_to_close_timeout=PROBE_TIMEOUT,
                schedule_to_close_timeout=PROBE_DEADLINE,
                retry_policy=PROBE_RETRY,
            )
        except Exception as failure:
            return ProbeOutcome(statuses={}, incomplete=_reason(failure))
        return ProbeOutcome(statuses=statuses)


WORKFLOWS: list[type] = [ProbeIntegrationsWorkflow]
