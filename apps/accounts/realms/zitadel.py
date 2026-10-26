"""`IdentityRealm` over Zitadel: a realm is an organisation, the platform a granted project.

The first adapter, and the only module besides `apps/accounts/zitadel.py`'s own
callers that may import the client (house rule 27's allow-list names it). Every
call below goes through that client, so the credential, the timeout and the
never-log-a-body rule are the client's and not this module's; what this module
adds is the translation between our values (`apps.accounts.realm`) and
Zitadel's vocabulary — an organisation, a project grant, the project check, an
org's own login policy, an IdP linked to it, the org scope on the authorize.

**Every method is the client's idempotent writers composed** (search, then
create), so an activity retried by Temporal leaves one of everything. A
refusal aimed at the caller — a login policy that admits nobody — is a
registered `core.exceptions` code; Zitadel failing is `ZitadelError`, which the
calling activity's retry policy owns, exactly as it does for every other call
into the client.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings

from apps.accounts import zitadel
from apps.accounts.realm import LoginPolicy, PersonRef, ProviderRef, RealmFacts, RealmRef
from apps.core.exceptions import Invalid

if TYPE_CHECKING:
    from apps.accounts.models import SsoConnection
    from apps.core.models import Tenant

#: The scope that confines a sign-in to one organisation. MEASURED on the
#: pinned build: an authorize carrying `urn:zitadel:iam:org:id:<id>` for a
#: realm answers the hosted login (`302 /ui/login/login?authRequestID=…`), and
#: for an id the instance holds no org under answers the callback with
#: `error=invalid_request`, `Errors.Org.NotFound` — so the scope is read, not
#: ignored.
ORG_SCOPE_PREFIX = "urn:zitadel:iam:org:id:"

#: The scopes the relying party asks for on every sign-in: allauth's OpenID
#: Connect provider's own default, since the settings name none. Carried here
#: because an authorize parameter REPLACES allauth's `scope` rather than adding
#: to it (`OAuth2Client.get_redirect_url` applies the extra parameters last), so
#: the realm's scope must carry these or the sign-in loses its profile and
#: address. `test_realm.py` pins the equality against allauth's default.
SIGN_IN_SCOPES = ("openid", "profile", "email")

#: A project grant that still lets its org's people in.
GRANT_ACTIVE = "PROJECT_GRANT_STATE_ACTIVE"


def realm_name(tenant: Tenant) -> str:
    """What a tenant's organisation is called: the deployment's project, then the slug.

    The slug because it is the tenant's stable public handle (renaming changes
    the `name`, never the `slug`) and the name is the search the next run finds
    the realm by. The project name first because an org name is unique across
    the whole instance, so two deployments sharing one development instance
    would otherwise adopt each other's tenants.
    """
    return f"{settings.ZITADEL_PROJECT_NAME} {tenant.slug}"


class ZitadelRealm:
    """The Zitadel adapter: each realm operation as the client's idempotent calls."""

    def ensure_realm(self, *, tenant: Tenant) -> RealmRef:
        """The tenant's organisation, made if it has none; the same tenant twice is one org."""
        made = zitadel.ensure_organization(name=realm_name(tenant))
        return RealmRef(id=made.id, issuer=zitadel.issuer())

    def grant_platform(self, *, realm: RealmRef) -> None:
        """Grant the deployment's project to the realm; a second grant is the first one."""
        zitadel.grant_project(project_id=_platform_project_id(), org_id=realm.id)

    def set_login_policy(self, *, realm: RealmRef, policy: LoginPolicy) -> None:
        """Write the realm's own login policy with the fields `policy` decides.

        `password_allowed` is `allowUsernamePassword`. `provider_required`
        switches `allowExternalIdp` on; a policy that does not require a
        provider leaves that field as it is, because a realm offering its
        people an IdP beside their password is a tenant's choice this port does
        not take away. Refused (`invalid`) before anything is dialled: a policy
        with neither a password nor a provider admits nobody, and one with both
        says the provider is required and the password allowed at once.
        """
        if policy.password_allowed == policy.provider_required:
            raise Invalid(
                {
                    "policy": [
                        "A realm's sign-in either takes a password or requires the "
                        "customer's identity provider, and exactly one of the two."
                    ]
                }
            )
        zitadel.ensure_login_policy(
            org_id=realm.id,
            allow_username_password=policy.password_allowed,
            allow_external_idp=True if policy.provider_required else None,
        )

    def attach_provider(self, *, realm: RealmRef, connection: SsoConnection) -> ProviderRef:
        """The connection's IdP made inside the realm and linked to its login policy.

        The realm must own its login policy first (`set_login_policy`): Zitadel
        refuses a link on an org that inherits, and the client raises that as
        an ordering fault rather than forking a policy nobody asked for.
        """
        provider = zitadel.ensure_oidc_identity_provider(
            name=connection.idp_name,
            issuer=connection.issuer,
            client_id=connection.client_id,
            client_secret=connection.client_secret,
            existing_id=connection.zitadel_idp_id,
            org_id=realm.id,
        )
        zitadel.link_idp_to_login_policy(org_id=realm.id, idp_id=provider.id)
        return ProviderRef(id=provider.id)

    def detach_provider(self, *, realm: RealmRef, provider: ProviderRef) -> None:
        """Take the provider off the realm's login policy; unlinked twice is unlinked."""
        zitadel.unlink_idp_from_login_policy(org_id=realm.id, idp_id=provider.id)

    def provision_person(
        self, *, realm: RealmRef, email: str, names: tuple[str, str], surface: str
    ) -> PersonRef:
        """The person in the realm with no credentials, and the link that lets them set some.

        The person is idempotent (search, then create, in the realm); **the link
        is not and cannot be** — Zitadel mints a new single-use code on every
        call and supersedes the last, so the idempotency a caller needs lives
        one level up, in the workflow id that stops a second run starting. A
        person who already set credentials gets no link: they sign in.
        """
        given, family = names
        person = zitadel.ensure_invited_user(
            email=email, first_name=given, last_name=family, org_id=realm.id
        )
        try:
            code = zitadel.create_invite_code(user_id=person.id)
        except zitadel.ZitadelError as error:
            if not zitadel.is_already_initialized(error):
                raise
            return PersonRef(subject=person.id, set_credentials_url="")
        return PersonRef(
            subject=person.id,
            set_credentials_url=zitadel.invite_url(user_id=person.id, code=code, surface=surface),
        )

    def deactivate_person(self, *, realm: RealmRef, subject: str) -> None:
        """Deactivate the person's account in the realm; inactive already is done."""
        zitadel.deactivate_user(user_id=subject, org_id=realm.id)

    def authorize_params(self, *, realm: RealmRef) -> dict[str, str]:
        """The authorize's `scope`: the sign-in scopes and the realm's org scope."""
        return {"scope": " ".join((*SIGN_IN_SCOPES, f"{ORG_SCOPE_PREFIX}{realm.id}"))}

    def facts(self, *, realm: RealmRef) -> RealmFacts:
        """The organisation, its grant, its own login policy and its linked providers, read back."""
        if zitadel.get_organization(org_id=realm.id) is None:
            return RealmFacts(realm=realm, exists=False, granted=False, policy=None, providers=())
        grant = zitadel.project_grant(project_id=_platform_project_id(), org_id=realm.id)
        live = zitadel.login_policy(org_id=realm.id)
        policy = None
        if not live.get("isDefault"):
            password = bool(live.get("allowUsernamePassword", False))
            external = bool(live.get("allowExternalIdp", False))
            policy = LoginPolicy(
                password_allowed=password, provider_required=external and not password
            )
        return RealmFacts(
            realm=realm,
            exists=True,
            granted=grant is not None and str(grant.get("state", "")) == GRANT_ACTIVE,
            policy=policy,
            providers=tuple(
                ProviderRef(id=str(row.get("idpId", "")))
                for row in zitadel.login_policy_providers(org_id=realm.id)
            ),
        )


def _platform_project_id() -> str:
    """The deployment's own project, which every realm is granted; the seed makes it."""
    project = zitadel.find_project(name=settings.ZITADEL_PROJECT_NAME)
    if project is None:
        raise zitadel.ZitadelNotConfigured(
            f"This deployment's Zitadel project {settings.ZITADEL_PROJECT_NAME!r} does not "
            "exist, so there is nothing to grant a realm. Run manage.py zitadel_seed."
        )
    return str(project["id"])
