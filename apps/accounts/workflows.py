"""Getting our identity configuration into Zitadel, durably (ADR ident-2).

The service writes the intent; these runs reach the management API, retried until it lands.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from apps.accounts.types import (
    IdentityConfigApplied,
    IdentityConfigSync,
    IdentityHomeApplied,
    IdentityHomeAsk,
    InvitationMessage,
    InvitedIdentity,
    InvitedPerson,
    InvitedPersonProvisioned,
)
from apps.core.determinism import run_to_finish

#: Generous beside the client's own ten seconds, so a slow success is not retried into noise.
APPLY_TIMEOUT = timedelta(seconds=60)

#: The retrying lives here, where every attempt is a row in the run's history (ADR ident-2).
APPLY_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=60),
    maximum_attempts=6,
)


@workflow.defn(name="SyncIdentityConfigWorkflow")
class SyncIdentityConfigWorkflow:
    """Materialise one configuration row in Zitadel, and record what it became."""

    @workflow.run
    async def run(self, sync: IdentityConfigSync) -> IdentityConfigApplied:
        async def apply() -> IdentityConfigApplied:
            return await self._apply(sync)

        applied, _tenant_slug = await run_to_finish(apply)
        return applied

    async def _apply(self, sync: IdentityConfigSync) -> IdentityConfigApplied:
        applied: IdentityConfigApplied = await workflow.execute_activity(
            "apply_identity_config",
            sync,
            start_to_close_timeout=APPLY_TIMEOUT,
            retry_policy=APPLY_RETRY,
            result_type=IdentityConfigApplied,
        )
        return applied


#: Delivery retries less: the message is the same message, and a host that blinked recovers fast.
PROVISION_TIMEOUT = timedelta(seconds=60)
PROVISION_RETRY = APPLY_RETRY
DELIVER_TIMEOUT = timedelta(seconds=60)
DELIVER_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=60),
    maximum_attempts=5,
)

#: `apps.workflows`' mailer, named and not owned here.
SEND_EMAIL_ACTIVITY = "send_email"
PROVISION_ACTIVITY = "provision_invited_identity"


@workflow.defn(name="ProvisionInvitedPersonWorkflow")
class ProvisionInvitedPersonWorkflow:
    """Turn one invitation row into a person who can act on it: provision, then deliver the link.

    Two activities in order: the link does not exist until the identity platform mints a code.
    """

    @workflow.run
    async def run(self, invited: InvitedPerson) -> InvitedPersonProvisioned:
        async def provision_and_deliver() -> InvitedPersonProvisioned:
            identity = await self._provision(invited)
            delivered = await self._deliver(invited, identity)
            return InvitedPersonProvisioned(
                zitadel_user_id=identity.zitadel_user_id,
                already_initialized=identity.already_initialized,
                delivered=delivered,
            )

        provisioned, _tenant_slug = await run_to_finish(provision_and_deliver)
        return provisioned

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

        A new message, never a mutation of the argument: the argument is replayed out of history.
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


HOME_TIMEOUT = APPLY_TIMEOUT
HOME_RETRY = APPLY_RETRY
HOME_ACTIVITY = "ensure_identity_home"


@workflow.defn(name="EnsureTenantIdentityHomeWorkflow")
class EnsureTenantIdentityHomeWorkflow:
    """Give one tenant its own realm at the identity platform, and record it.

    One activity: every step is idempotent by search through the realm port, so the whole retries.
    A cancel that lands before the activity leaves the home `pending` — fail closed (ADR ident-13).
    """

    @workflow.run
    async def run(self, ask: IdentityHomeAsk) -> IdentityHomeApplied:
        async def ensure() -> IdentityHomeApplied:
            applied: IdentityHomeApplied = await workflow.execute_activity(
                HOME_ACTIVITY,
                ask,
                start_to_close_timeout=HOME_TIMEOUT,
                retry_policy=HOME_RETRY,
                result_type=IdentityHomeApplied,
            )
            return applied

        applied, _tenant_slug = await run_to_finish(ensure)
        return applied


WORKFLOWS: list[type] = [
    SyncIdentityConfigWorkflow,
    ProvisionInvitedPersonWorkflow,
    EnsureTenantIdentityHomeWorkflow,
]
