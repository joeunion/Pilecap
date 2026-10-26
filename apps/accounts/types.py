"""The shapes that cross this app's workflow boundary.

Plain dataclasses in a module that imports nothing but the standard library,
because every one of these is serialised into Temporal's history and replayed
out of it — possibly years later, by a worker running code nobody has looked at
since. A workflow argument that was an `SsoConnection` could not be replayed at
all: the row may have changed, or gone.

Ids are strings for the same reason: what comes back out of history is JSON, and
a string parsed once, in the activity, at the edge of the database, is one
conversion in one place.

**No secret is in any of these.** The issuer, the client id and the client
secret an identity provider needs are read from the row *inside* the activity,
through the encrypted field that holds them. Putting them in the workflow
argument would write a customer's client secret into Temporal's history, where
it would sit in plaintext for the retention period and appear in the web UI to
anybody who can open a run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The classes of configuration this workflow can materialise, named once so the
# service, the workflow argument and the activity's branch cannot disagree about
# a string. It is a vocabulary and not a boolean because ADR ident-6 put three members
# in it, and the third one is not configuration at all:
#
# * `SSO_CONNECTION` — one tenant's own identity provider, keyed on the row.
# * `WORKFORCE_PROVIDER` — the deployment's Google Workspace door. Keyed on a
#   digest of the environment rather than a row, because **its intent is the
#   environment**: `GOOGLE_*` is deployment configuration, not any customer's,
#   and there is no tenant-scoped row for it to be the intent of. That
#   asymmetry is declared here rather than papered over with a row nobody owns.
# * `IDENTITY_REVOCATION` — a person's Zitadel account, deactivated and
#   unlinked, keyed on our `User` row. It rides this workflow because it is the
#   same shape: one idempotent write to somebody else's API, retried until it
#   lands, that must not happen inside the erasing service's transaction.
# * `IDENTITY_BRANDING` — how the deployment's hosted sign-in screen LOOKS,
#   keyed on the `IdentityBranding` row. A platform kind like the workforce
#   door — one instance, one login screen, no customer's — but unlike it this
#   one HAS a row to be the intent of, which is the whole of the fix for an
#   unwatched console: the console could repaint the screen and nothing here
#   would know, so there is now something for `zitadel_audit` to disagree with.
KIND_SSO_CONNECTION = "sso_connection"
KIND_WORKFORCE_PROVIDER = "workforce_provider"
KIND_IDENTITY_REVOCATION = "identity_revocation"
KIND_IDENTITY_BRANDING = "identity_branding"


@dataclass
class IdentityConfigSync:
    """What `SyncIdentityConfigWorkflow` is started with.

    `kind` says which class of configuration this run is about, so the activity
    knows which management objects to drive; `key` is the row it is about. The
    two together are what the workflow id is built from, which is what makes a
    second sync of the same row the same run rather than a second one.

    The tenant is deliberately absent: it rides on the workflow's headers
    (`apps.workflows.context`) and is restored inside the activity, so no caller
    can reach into somebody else's tenant by putting the wrong id in a payload.
    """

    kind: str
    key: str


@dataclass
class IdentityConfigApplied:
    """What the activity got back, and what the service records on the row.

    `resource_id` is the Zitadel object our row now names. Whether this call
    made it or found it is not carried: the realm port answers neither, so a
    flag here would read `False` on a connection that was just made — a value
    that is always false is a lie on the wire. The log line of the branch that
    can tell says it.
    """

    kind: str
    key: str
    resource_id: str


@dataclass
class InvitationMessage:
    """The invitation email as it crosses into `send_email`: `workflows.types.SendEmail`'s fields.

    Restated, not imported: a workflow module imports its own `types.py` (rule 9).
    """

    to: list[str]
    subject: str
    template: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class InvitedPerson:
    """What `ProvisionInvitedPersonWorkflow` is started with.

    `invitation_id` is our row's primary key — the key the run's deterministic
    id is built from, so a retried `invite_member` starts one run and not two.
    It rides in the payload as well as in the id because the log lines want it.

    The tenant is deliberately absent, as it is on every other payload here: it
    rides on the workflow's headers and is restored inside the activity.

    **No credential is in this**, and the one that appears later never comes
    from here: the invite code is minted *inside* the activity and travels
    outward. See `InvitedIdentity`.
    """

    invitation_id: str
    email: str
    message: InvitationMessage


@dataclass
class InvitedIdentity:
    """What `provision_invited_identity` got back from Zitadel.

    **This is the one payload in this module that carries a credential**, and it
    is declared rather than hidden: `set_credentials_url` embeds the invite
    code, so it is written into Temporal's history for the retention period.
    ADR accounts-1 argues why that is acceptable here and is not a licence to
    put our own bearer tokens in a payload — the code is single-use,
    short-lived, revocable by re-issuing, and gates only the setting of a
    password on an account that has none. It cannot read anything, and it does
    not confer membership: `accounts.adapter.accept_pending_invitations` still
    has to match OUR row at sign-in.

    `set_credentials_url` is empty when the person already has credentials —
    the ordinary case of somebody who already signs in here being invited into
    a second tenant. `already_initialized` says that is why, so the workflow is
    not left inferring it from an empty string.

    `link_expires_on` is an ISO date, rendered in the activity because a
    workflow may not read a clock (house rule 9).
    """

    zitadel_user_id: str
    set_credentials_url: str = ""
    link_expires_on: str = ""
    already_initialized: bool = False


@dataclass
class InvitedPersonProvisioned:
    """What the run returns, and deliberately **not** what it carried.

    No URL and no code: the workflow result is the most-read row in the Temporal
    UI, and there is no reason for a credential to be the thing a person sees
    when they open a run. What is useful there is which account was settled on,
    whether it already signed in, and whether the email went.
    """

    zitadel_user_id: str
    already_initialized: bool = False
    delivered: int = 0


@dataclass
class IdentityHomeAsk:
    """What `EnsureTenantIdentityHomeWorkflow` is started with: the tenant, by slug.

    The slug rather than the primary key because the run is the DEPLOYMENT's
    (a `platform:` id with no tenant on its headers — the realm is identity
    configuration, not any tenant's row), so the tenant is named in the payload
    and read inside the activity, where the database is.
    """

    tenant_slug: str


@dataclass
class IdentityHomeApplied:
    """What the run made: the tenant's realm, by its id at the identity platform."""

    tenant_slug: str
    realm_id: str
