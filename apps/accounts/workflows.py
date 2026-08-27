"""Getting our identity configuration into Zitadel, durably.

The service writes the intent onto our row inside its transaction and starts
this run on commit; this run is what actually reaches the management API. That
split is ADR ident-2's whole point and C2's classic shape: an external call
inside the service's transaction means a Zitadel hiccup rolls back a row that
was perfectly legitimate, and a transaction held open across a network call
holds a lock for as long as somebody else's server feels like taking.

House rule 9, visible: this module imports the standard library's `timedelta`,
`temporalio`, and its own `types.py` — and nothing else. **No ORM, no network,
no clock, no randomness, and no import of `activities.py`**; the activities are
invoked by name, because importing them would drag the ORM into a module that
has to replay identically years from now.

There is no wait here, and that is deliberate. This is not a process with a
human in it — it is one idempotent write to somebody else's API, retried until
it lands. The durability that matters is the retry, not a timer.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from apps.accounts.types import (
    IdentityConfigApplied,
    IdentityConfigSync,
    InvitationMessage,
    InvitedIdentity,
    InvitedPerson,
    InvitedPersonProvisioned,
    RunFinished,
)

# One attempt at the management API. Generous next to the client's own ten
# seconds, so that a slow-but-succeeding call is not killed here and retried
# into a duplicate — the activity is idempotent, but a retry that was never
# needed is still noise in the history.
APPLY_TIMEOUT = timedelta(seconds=60)

# **This is where the retrying lives** (ADR ident-2). Not in the httpx client,
# where a loop is invisible from outside the process; here, where every attempt
# is a row in the run's history that a person can read months later. Six
# attempts over a bounded backoff is roughly "survive a restart or a deploy of
# the identity service"; beyond that the failure is not transient and a run
# stuck retrying forever is a failure nobody is told about.
APPLY_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=60),
    maximum_attempts=6,
)

# Closing out the `WorkflowRun` row (A11). One local database write, bounded: a
# bookkeeping activity that retried forever would outlive the thing it is
# bookkeeping for.
FINISH_TIMEOUT = timedelta(seconds=30)
FINISH_RETRY = RetryPolicy(maximum_attempts=5)
FINISH_ACTIVITY = "mark_run_finished"

# The two terminal values of `apps.workflows.models.WorkflowRun.Status`. Named
# here as strings rather than imported, because a workflow module may import its
# own `types.py` and nothing else (house rule 9).
RUN_COMPLETED = "completed"
RUN_FAILED = "failed"


@workflow.defn(name="SyncIdentityConfigWorkflow")
class SyncIdentityConfigWorkflow:
    """Materialise one configuration row in Zitadel, and record what it became."""

    @workflow.run
    async def run(self, sync: IdentityConfigSync) -> IdentityConfigApplied:
        try:
            applied = await self._apply(sync)
        except Exception as error:
            # The row says what happened, and then the run still fails. A
            # `WorkflowRun` left at `running` beside a Temporal execution that
            # ended is worse than no row at all: it is a row that lies.
            await self._finish(status=RUN_FAILED, error=str(error))
            raise
        await self._finish(status=RUN_COMPLETED)
        return applied

    async def _apply(self, sync: IdentityConfigSync) -> IdentityConfigApplied:
        # `execute_activity` is typed `Any` — the activity is invoked by NAME
        # (house rule 9), so there is no function signature here for mypy to
        # read. `result_type` is what actually decides the shape at run time,
        # and the annotation below is what says so to the type checker.
        applied: IdentityConfigApplied = await workflow.execute_activity(
            "apply_identity_config",
            sync,
            start_to_close_timeout=APPLY_TIMEOUT,
            retry_policy=APPLY_RETRY,
            result_type=IdentityConfigApplied,
        )
        return applied

    async def _finish(self, *, status: str, error: str = "") -> None:
        """Close the run's visibility row, whichever way the run ended."""
        await workflow.execute_activity(
            FINISH_ACTIVITY,
            RunFinished(
                workflow_id=workflow.info().workflow_id,
                status=status,
                error=error,
            ),
            start_to_close_timeout=FINISH_TIMEOUT,
            retry_policy=FINISH_RETRY,
            result_type=str,
        )


# The invitation's two steps, each with its own patience. Provisioning is a pair
# of calls to somebody else's API and gets the same generous window and the same
# six attempts the configuration sync gets, for the same reason. Delivery is
# handed to `apps.workflows`' own `send_email`, which is the activity
# `core.mail` has always used; the timeout matches what that activity does — one
# render and one SMTP conversation — and the retry is shorter because the
# message it would re-send is the same message, and an invitation still trying
# an hour later is an address that is wrong rather than a host that blinked.
PROVISION_TIMEOUT = timedelta(seconds=60)
PROVISION_RETRY = APPLY_RETRY
DELIVER_TIMEOUT = timedelta(seconds=60)
DELIVER_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=60),
    maximum_attempts=5,
)

# The generic mailer, in `apps.workflows`. Named as a string and **not owned
# here**: it renders a template and hands the message to the configured
# backend, which is exactly what this run needs once it knows the link.
SEND_EMAIL_ACTIVITY = "send_email"
PROVISION_ACTIVITY = "provision_invited_identity"


@workflow.defn(name="ProvisionInvitedPersonWorkflow")
class ProvisionInvitedPersonWorkflow:
    """Turn one invitation row into a person who can actually act on it.

    **The dead-end this closes**: the invitation email used to point
    at a login page with no form, on a deployment with no way to create a
    person, and offered a signup route that 404s. Nothing between the row and
    the human worked. Now the row starts this, and this makes the account —
    credential-less, so the invited person chooses their own password — mints
    the code that lets them set it, and puts that link in the email OUR mailer
    sends.

    **Two activities, in order, because the second needs the first's answer.**
    The link does not exist until Zitadel has minted a code, so the message
    `core.services.invite_member` composed is carried through this run with a
    hole in it and the link is merged in here. That merge is the only thing this
    workflow computes, and it is dictionary and string work — replayable
    forever, no clock, no ORM, no network, no randomness (house rule 9). The
    module docstring above holds for this class exactly as it does for the other
    one: the imports at the top of this file are the whole of what runs here.

    **The run row closes both ways** (house rule 28), through the same
    `_finish` seam the sync workflow uses — a `WorkflowRun` left at `running`
    beside an execution that ended is a ledger that lies.
    """

    @workflow.run
    async def run(self, invited: InvitedPerson) -> InvitedPersonProvisioned:
        try:
            identity = await self._provision(invited)
            delivered = await self._deliver(invited, identity)
        except Exception as error:
            await self._finish(status=RUN_FAILED, error=str(error))
            raise
        await self._finish(status=RUN_COMPLETED)
        return InvitedPersonProvisioned(
            zitadel_user_id=identity.zitadel_user_id,
            created=identity.created,
            already_initialized=identity.already_initialized,
            delivered=delivered,
        )

    async def _provision(self, invited: InvitedPerson) -> InvitedIdentity:
        identity: InvitedIdentity = await workflow.execute_activity(
            PROVISION_ACTIVITY,
            invited,
            start_to_close_timeout=PROVISION_TIMEOUT,
            retry_policy=PROVISION_RETRY,
            result_type=InvitedIdentity,
        )
        return identity

    async def _deliver(self, invited: InvitedPerson, identity: InvitedIdentity) -> int:
        """Send the message the service composed, with the link merged in.

        A new `InvitationMessage` rather than a mutation of the one in the
        payload: the argument is replayed out of history and mutating it would
        make this run's behaviour depend on how many times it had been replayed.

        The two keys added here are the two the template branches on. When the
        person already has credentials both are empty, and the template says
        "sign in" instead of "set a password" — which is the honest sentence for
        somebody who already signs in to this deployment and has just been
        invited into a second tenant.
        """
        message = InvitationMessage(
            to=list(invited.message.to),
            subject=invited.message.subject,
            template=invited.message.template,
            context={
                **invited.message.context,
                "set_credentials_url": identity.set_credentials_url,
                "link_expires_on": identity.link_expires_on,
            },
        )
        delivered: int = await workflow.execute_activity(
            SEND_EMAIL_ACTIVITY,
            message,
            start_to_close_timeout=DELIVER_TIMEOUT,
            retry_policy=DELIVER_RETRY,
            result_type=int,
        )
        return delivered

    async def _finish(self, *, status: str, error: str = "") -> None:
        """Close the run's visibility row, whichever way the run ended."""
        await workflow.execute_activity(
            FINISH_ACTIVITY,
            RunFinished(
                workflow_id=workflow.info().workflow_id,
                status=status,
                error=error,
            ),
            start_to_close_timeout=FINISH_TIMEOUT,
            retry_policy=FINISH_RETRY,
            result_type=str,
        )


WORKFLOWS: list[type] = [SyncIdentityConfigWorkflow, ProvisionInvitedPersonWorkflow]
