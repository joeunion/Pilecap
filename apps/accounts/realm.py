"""The identity realm port: what the platform asks of a tenant's own identity population.

**A realm is a tenant's people, apart.** Identity option B: a customer's
people must not share a login policy, an IdP list or a password rule with staff
or with another customer, so every tenant has a realm of its own, the
deployment's platform is granted to it, and the sign-in request names it. This
module says what that takes in OUR words — a protocol over frozen values — and
`apps/accounts/realms/` holds the adapters that speak a vendor's.

**The operations option B ADDS, and nothing more** (decision 15, the bound the
owner ruled): making a realm, granting it the platform, its login policy, its
providers, its people, the sign-in request's confinement and the read-back. The
deployment-level bootstrap — the seed, the posture, the branding, the sign-in
seam, the `zitadel_*` commands — is not ported: one vendor, fenced to one module
by house rule 27, and moved behind this port only in the release a second
adapter is real. A new operation is a diff a reviewer reads
(`apps/accounts/tests/test_realm.py` pins the member set against a typed list —
the one place a typed list is the instrument, because a new member is exactly
the change that list exists to make visible).

**Nothing vendor-shaped crosses this line.** The values are ours: a realm is an
id and the issuer it signs people in at, a policy is two booleans, a person is a
subject and the link that lets them set credentials. A caller holding a
`RealmRef` cannot tell which vendor made it, which is the exit principle 5 asks
every critical dependency to have.

**Every method is idempotent** (C4, principle 16): the callers are activities,
Temporal delivers at least once, and the same input twice leaves one realm, one
grant, one policy, one link and one person. The one call that cannot be is named
where it is (`provision_person`'s credential link).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from apps.accounts.models import SsoConnection
    from apps.core.models import Tenant


@dataclass(frozen=True)
class RealmRef:
    """One tenant's realm: its id at the identity platform, and the issuer it signs in at."""

    id: str
    issuer: str


@dataclass(frozen=True)
class ProviderRef:
    """One external identity provider inside a realm, by its id there."""

    id: str


@dataclass(frozen=True)
class LoginPolicy:
    """How a realm's people may sign in: with a password, and whether an IdP is the only way.

    `provider_required` is a tenant's `enforced` SSO: the password off and the
    external provider the one door. The adapter refuses a policy that admits
    nobody — neither a password nor a provider.
    """

    password_allowed: bool
    provider_required: bool


@dataclass(frozen=True)
class PersonRef:
    """One person in a realm: their subject there, and where they set their credentials.

    `set_credentials_url` is `""` for a person who already has credentials —
    somebody invited into a second workspace signs in rather than sets a
    password.
    """

    subject: str
    set_credentials_url: str


@dataclass(frozen=True)
class RealmFacts:
    """What a realm IS at the identity platform, read back — the audit's comparison set.

    `policy` is `None` while the realm inherits the platform's default rather
    than owning a policy of its own; `providers` are the IdPs its sign-in offers.
    """

    realm: RealmRef
    exists: bool
    granted: bool
    policy: LoginPolicy | None
    providers: tuple[ProviderRef, ...]


@runtime_checkable
class IdentityRealm(Protocol):
    """What a tenant's identity realm answers; each operation is idempotent (C4)."""

    def ensure_realm(self, *, tenant: Tenant) -> RealmRef:
        """The tenant's realm, made if it has none; the same tenant twice is one realm."""
        ...

    def grant_platform(self, *, realm: RealmRef) -> None:
        """Let the realm's people sign in to this deployment's platform at all."""
        ...

    def set_login_policy(self, *, realm: RealmRef, policy: LoginPolicy) -> None:
        """Make the realm's sign-in say `policy`, every other setting kept as it is."""
        ...

    def attach_provider(self, *, realm: RealmRef, connection: SsoConnection) -> ProviderRef:
        """The connection's IdP inside the realm, offered on its sign-in."""
        ...

    def detach_provider(self, *, realm: RealmRef, provider: ProviderRef) -> None:
        """Stop the realm's sign-in offering `provider`; the provider itself is kept."""
        ...

    def provision_person(
        self, *, realm: RealmRef, email: str, names: tuple[str, str], surface: str
    ) -> PersonRef:
        """The person `email` in the realm, and the link on `surface` where they set credentials."""
        ...

    def deactivate_person(self, *, realm: RealmRef, subject: str) -> None:
        """Take one person's account in the realm out of use; the same subject twice is a no-op."""
        ...

    def authorize_params(self, *, realm: RealmRef) -> dict[str, str]:
        """The sign-in request's parameters that confine it to the realm."""
        ...

    def facts(self, *, realm: RealmRef) -> RealmFacts:
        """What the realm is at the platform now, read and never written."""
        ...
