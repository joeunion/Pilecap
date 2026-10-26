"""ADR ident-6's machinery: the workforce door, the disable, and the revocation.

Three things ADR ident-6 added, and none of them dials anything: the same
`FakeZitadel` socket `test_zitadel.py` uses is what stands in for the management
API, so the real `_call`, the real paths and the real search-then-create
decisions all execute (ident-5's posture).

What is proved here is the machinery. What is proved next door, in
`test_a9_matrix.py`, is the twenty-two properties that machinery has to keep.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts import zitadel
from apps.accounts.activities import apply_identity_config
from apps.accounts.models import STAFF_REALM, SsoConnection, User
from apps.accounts.selectors import get_tenant_realm
from apps.accounts.services import (
    SYNC_IDENTITY_CONFIG_WORKFLOW,
    disable_sso_connection,
    erase_user,
    record_identity,
    sync_workforce_identity_config,
)
from apps.accounts.tests.conftest import FakeZitadel
from apps.accounts.types import (
    KIND_IDENTITY_REVOCATION,
    KIND_SSO_CONNECTION,
    KIND_WORKFORCE_PROVIDER,
    IdentityConfigSync,
)
from apps.accounts.zitadel import WORKFORCE_IDP_NAME
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.exceptions import Forbidden, Invalid
from apps.core.models import Organization, Tenant
from apps.workflows import context as workflow_context
from apps.workflows.models import WorkflowRun

pytestmark = pytest.mark.django_db(transaction=True)

WORKFORCE_DOMAIN = "union.studio"


@pytest.fixture
def acting(tenant: Tenant, root_org: Organization) -> Iterator[None]:
    """The workflow headers the interceptor would have restored."""
    tokens = workflow_context.set_principal(
        tenant_id=str(tenant.pk), user_id=None, org_id=str(root_org.pk)
    )
    yield
    workflow_context.reset_principal(tokens)


@pytest.fixture
def workforce(settings: Any) -> None:
    """A deployment that has actually configured the workforce door — both halves."""
    settings.GOOGLE_OAUTH_CLIENT_ID = "google-client-id"
    settings.GOOGLE_OAUTH_CLIENT_SECRET = "google-client-secret"  # noqa: S105 — a fake IdP client secret the test world configures  # pragma: allowlist secret
    settings.GOOGLE_WORKSPACE_DOMAINS = [WORKFORCE_DOMAIN]


@pytest.fixture
def operator(db: None) -> User:
    """A platform operator: somebody who administers the deployment itself."""
    from apps.accounts.services import create_user

    return create_user(email="operator@example.com", password=None, is_superuser=True)


# --- The workforce provider (ADR ident-6, item 1) ----------------------------


def test_the_workforce_door_is_asked_for_through_the_same_workflow(
    instance: FakeZitadel,
    workforce: None,
    operator: User,
    tenant: Tenant,
) -> None:
    """One way identity configuration reaches Zitadel, and this is it.

    The service records the ask; the run is what reaches the management API. A
    workforce provider clicked into the console by hand would be the exception
    that made ident-6's claim untrue, so the ask has to look exactly like a
    customer connection's — same workflow type, same deterministic id.

    **Amended** (ADR workflows-3): the id's first
    segment used to be the borrowed tenant's slug. It is `platform:` now,
    because the deployment's own Google credentials are not any customer's
    configuration. Same workflow, same key, same determinism — a different
    population.
    """
    actor = actor_for(user=operator, tenant=tenant, kind="human")

    asked = sync_workforce_identity_config(actor=actor, tenant=None)
    run_key = asked.key

    assert run_key.startswith("workforce-")
    # The run row IS the row this act wrote, and the typed result carries it so
    # the audit entry can name it (ADR core-22, L9). Same row, both ways.
    assert asked.run is not None
    run = WorkflowRun.objects.for_platform().get(
        type=SYNC_IDENTITY_CONFIG_WORKFLOW, workflow_id__endswith=run_key
    )
    assert run.workflow_id == f"platform:accounts:identity_config:{run_key}"
    assert run.tenant_id is None


def test_no_tenants_ledger_shows_the_deployments_workforce_run(
    instance: FakeZitadel,
    workforce: None,
    operator: User,
    tenant: Tenant,
    other_tenant: Tenant,
) -> None:
    """**The half that amendment was actually about.**

    Recording the deployment's run in a customer's ledger did not merely look
    untidy: that tenant's audit trail then said the deployment's work was
    theirs, and every read they can make — the admin, a future runs endpoint,
    an export — would have shown it to them. `for_tenant` fails closed and can
    never reach the null population, so this holds for *every* tenant rather
    than for the one that used to be borrowed.
    """
    actor = actor_for(user=operator, tenant=tenant, kind="human")

    run_key = sync_workforce_identity_config(actor=actor, tenant=None).key

    workflow_id = f"platform:accounts:identity_config:{run_key}"
    assert WorkflowRun.objects.for_platform().filter(workflow_id=workflow_id).count() == 1
    for seeded in Tenant.objects.all():
        assert not WorkflowRun.objects.for_tenant(seeded).filter(workflow_id=workflow_id)
    assert {tenant.pk, other_tenant.pk} <= set(Tenant.objects.values_list("pk", flat=True))


def test_an_operator_wearing_a_hat_still_starts_a_platform_run(
    instance: FakeZitadel,
    workforce: None,
    operator: User,
    tenant: Tenant,
    root_org: Organization,
) -> None:
    """A platform run wears no hat, and the operator's is dropped rather than stamped.

    `check_org_agreement` refuses an `org` beside a null tenant — correctly: an
    acting organization belongs to a tenant, so carrying one onto a run that
    acts for the deployment would put a cross-population hat on the headers the
    seam exists to keep honest. It refuses with `ValueError`, at the
    caller-bug tier, which means an operator who happened to have `X-Org`
    resolved would have got a traceback instead of a provider. The hat is
    dropped at the one place that knows which population the run belongs to.
    """
    actor = actor_for(user=operator, tenant=tenant, kind="human", org=root_org)

    run_key = sync_workforce_identity_config(actor=actor, tenant=None).key

    run = WorkflowRun.objects.for_platform().get(workflow_id__endswith=run_key)
    assert run.tenant_id is None


def test_the_same_workforce_configuration_twice_is_one_run(
    instance: FakeZitadel,
    workforce: None,
    operator: User,
    tenant: Tenant,
) -> None:
    """The environment is the intent, so the digest of it is the key."""
    actor = actor_for(user=operator, tenant=tenant, kind="human")

    first = sync_workforce_identity_config(actor=actor, tenant=None)
    second = sync_workforce_identity_config(actor=actor, tenant=None)

    # The KEY is the deterministic thing under test; the whole result comparing
    # equal is the stronger statement and it holds, because a re-ask resolves
    # the same run row (ADR core-22, L9: the run IS what this act wrote).
    assert first.key == second.key
    assert first == second
    assert (
        WorkflowRun.objects.for_platform().filter(type=SYNC_IDENTITY_CONFIG_WORKFLOW).count() == 1
    )


def test_changed_workforce_credentials_are_a_new_run(
    instance: FakeZitadel,
    workforce: None,
    operator: User,
    tenant: Tenant,
    settings: Any,
) -> None:
    """And the other half: rotating Google's secret is new work, not the same."""
    actor = actor_for(user=operator, tenant=tenant, kind="human")
    first = sync_workforce_identity_config(actor=actor, tenant=None)

    settings.GOOGLE_OAUTH_CLIENT_SECRET = "google-client-secret-rotated"  # noqa: S105 — a fake IdP client secret the test world configures  # pragma: allowlist secret
    second = sync_workforce_identity_config(actor=actor, tenant=None)

    assert first.key != second.key
    assert first != second


def test_a_tenants_owner_may_not_configure_the_deployments_door(
    instance: FakeZitadel,
    workforce: None,
    owner_actor: Actor,
    tenant: Tenant,
) -> None:
    """The escalation wall, at the boundary between a customer and the installation.

    An owner is the most privileged person their workspace has. The workforce
    provider is not a bigger version of that permission — it is the deployment's,
    shared by every tenant on it, and a different question entirely.
    """
    before = WorkflowRun.objects.count()
    with pytest.raises(Forbidden):
        sync_workforce_identity_config(actor=owner_actor, tenant=None)

    # Counted across the refusal: the world already holds the tenant's realm
    # run (and the dispatch of its `identity_home.created`), and the refused
    # ask added nothing beside them.
    assert WorkflowRun.objects.count() == before


def test_an_empty_domain_list_refuses_rather_than_materialising_an_open_door(
    instance: FakeZitadel,
    workforce: None,
    operator: User,
    tenant: Tenant,
    settings: Any,
) -> None:
    """Empty means off — the fail-closed reading, carried into the materialisation.

    A Google provider live in Zitadel with this product refusing every address it
    asserts is a door that looks open and is not, which is the worst of the three
    states. It refuses, and the message says what to set.
    """
    settings.GOOGLE_WORKSPACE_DOMAINS = []
    actor = actor_for(user=operator, tenant=tenant, kind="human")

    before = WorkflowRun.objects.count()
    with pytest.raises(Invalid) as refused:
        sync_workforce_identity_config(actor=actor, tenant=None)

    assert "GOOGLE_WORKSPACE_DOMAINS" in refused.value.detail
    assert WorkflowRun.objects.count() == before


def test_missing_google_credentials_refuse_too(
    instance: FakeZitadel,
    workforce: None,
    operator: User,
    tenant: Tenant,
    settings: Any,
) -> None:
    settings.GOOGLE_OAUTH_CLIENT_ID = ""
    actor = actor_for(user=operator, tenant=tenant, kind="human")

    with pytest.raises(Invalid):
        sync_workforce_identity_config(actor=actor, tenant=None)


def test_the_activity_materialises_the_workforce_provider(
    instance: FakeZitadel, workforce: None
) -> None:
    """Google as an org-level template, under the one name the search finds it by.

    **No `acting` fixture, and that is the assertion**: a
    workforce run is a platform run, so its activity arrives with no tenant
    header at all. Restoring one here would have tested a posture that cannot
    happen — and would have hidden a `workflow_context()` call that raises on
    every real workforce run.
    """
    applied = apply_identity_config(
        IdentityConfigSync(kind=KIND_WORKFORCE_PROVIDER, key="workforce-abc123")
    )

    remote = zitadel.get_identity_provider(idp_id=applied.resource_id)
    assert remote is not None
    assert remote["name"] == WORKFORCE_IDP_NAME
    assert remote["config"]["google"]["clientId"] == "google-client-id"


def test_the_workforce_activity_twice_leaves_one_provider(
    instance: FakeZitadel, workforce: None
) -> None:
    """Temporal's at-least-once is the normal case, and there is no row to key on.

    The idempotence rests entirely on the search by name — which is exactly why
    the name is a constant and not derived from anything renameable.
    """
    payload = IdentityConfigSync(kind=KIND_WORKFORCE_PROVIDER, key="workforce-abc123")

    first = apply_identity_config(payload)
    second = apply_identity_config(payload)

    assert first.resource_id == second.resource_id
    assert len(instance.idps) == 1


def test_the_door_asks_without_naming_a_tenant(
    instance: FakeZitadel, workforce: None, tenant: Tenant, capsys: Any
) -> None:
    """**W7-2 at the door.**

    `--tenant` was `required=True`, and the command's own docstring said why:
    the run had to be recorded somewhere and `WorkflowRun` was tenant-scoped.
    That reason is gone, so the requirement is gone with it — an operator
    materialising the deployment's Google door no longer has to nominate a
    customer to hang it on, and no customer's audit trail gains a row about it.
    """
    from apps.core.audit import AuditEntry

    call_command("sync_workforce_idp")

    printed = capsys.readouterr().out
    assert "workforce provider" in printed
    run = WorkflowRun.objects.for_platform().get(type=SYNC_IDENTITY_CONFIG_WORKFLOW)
    assert run.workflow_id.startswith("platform:accounts:identity_config:workforce-")
    assert not AuditEntry.objects.for_tenant(tenant).filter(
        action="accounts.sync_workforce_identity_config"
    )


def test_the_door_still_refuses_a_tenant_slug_that_does_not_exist(
    instance: FakeZitadel, workforce: None
) -> None:
    """Optional is not ignored: a named audit anchor that is not there is a refusal."""
    with pytest.raises(CommandError):
        call_command("sync_workforce_idp", "--tenant", "not-a-tenant")

    assert not WorkflowRun.objects.for_platform().exists()


# --- Disabling reaches Zitadel (ADR ident-6, item 2) -------------------------


def test_disabling_a_connection_takes_its_provider_off_the_realms_sign_in(
    instance: FakeZitadel,
    acting: None,
    tenant: Tenant,
    owner_actor: Actor,
    sso_connection: SsoConnection,
) -> None:
    """The half ADR ident-6 owed: before it, disabling stopped our callback and nothing else.

    Once Zitadel fronts every IdP, a provider left on a realm's sign-in is the
    whole of the door still open — our own refusal is not in the path any more.
    The pinned build has no deactivation for the provider templates this tree
    makes (measured), so the release is the provider unlinked from the tenant
    realm's login policy.
    """
    apply_identity_config(IdentityConfigSync(kind=KIND_SSO_CONNECTION, key=str(sso_connection.pk)))
    sso_connection.refresh_from_db()
    materialised = sso_connection.zitadel_idp_id
    assert materialised

    disable_sso_connection(tenant=tenant, actor=owner_actor, connection=sso_connection)
    apply_identity_config(IdentityConfigSync(kind=KIND_SSO_CONNECTION, key=str(sso_connection.pk)))

    realm = get_tenant_realm(tenant)
    assert realm is not None
    assert materialised not in instance.login_policy_idps.get(realm.id, [])
    # Taken off, never deleted: the object and the links it holds survive a
    # customer's migration window.
    assert materialised in instance.idps


def test_releasing_a_released_provider_is_not_a_failure(
    instance: FakeZitadel,
    acting: None,
    tenant: Tenant,
    owner_actor: Actor,
    sso_connection: SsoConnection,
) -> None:
    """Unlinked twice is unlinked: a retry of the release must not fail a landed run."""
    apply_identity_config(IdentityConfigSync(kind=KIND_SSO_CONNECTION, key=str(sso_connection.pk)))
    disable_sso_connection(tenant=tenant, actor=owner_actor, connection=sso_connection)
    payload = IdentityConfigSync(kind=KIND_SSO_CONNECTION, key=str(sso_connection.pk))

    first = apply_identity_config(payload)
    second = apply_identity_config(payload)

    assert first.resource_id == second.resource_id


# --- Erasure revokes the identity (W2R5-20) ----------------------------------


def test_the_activity_deactivates_and_unlinks_the_person(
    instance: FakeZitadel, tenant: Tenant, member: User
) -> None:
    """Links first, then the account: the other order leaves a window open.

    **No `acting` fixture**, and that is the re-point ADR core-9 forced. A
    revocation is a platform run: `_start_identity_run` gives it `tenant=None`
    and `org=None`, so the interceptor stamps neither and the activity really
    arrives with nothing restored. Borrowing the tenanted headers here modelled a
    posture that cannot occur, and now fails at `_platform_scope` — which is the
    contract, proved next door in
    `test_a_platform_kind_under_tenant_stamped_headers_is_refused`.
    """
    instance.users["9001"] = {"id": "9001", "userName": member.email}
    instance.user_links["9001"] = [
        {"idpId": "77", "providedUserId": "google|abc"},
        {"idpId": "88", "providedUserId": "okta|def"},
    ]
    record_identity(
        realm=STAFF_REALM, user=member, subject="9001", tenant=None, actor=system_actor(tenant=None)
    )

    applied = apply_identity_config(
        IdentityConfigSync(kind=KIND_IDENTITY_REVOCATION, key=str(member.pk))
    )

    assert applied.resource_id == "9001"
    assert "9001" in instance.deactivated_users
    assert instance.user_links["9001"] == []


def test_revoking_twice_is_not_a_failure(
    instance: FakeZitadel, tenant: Tenant, member: User
) -> None:
    """The retry contract, in the posture a platform run really arrives in."""
    instance.users["9001"] = {"id": "9001", "userName": member.email}
    instance.user_links["9001"] = [{"idpId": "77", "providedUserId": "google|abc"}]
    record_identity(
        realm=STAFF_REALM, user=member, subject="9001", tenant=None, actor=system_actor(tenant=None)
    )
    payload = IdentityConfigSync(kind=KIND_IDENTITY_REVOCATION, key=str(member.pk))

    first = apply_identity_config(payload)
    second = apply_identity_config(payload)

    assert first.resource_id == second.resource_id == "9001"
    assert "9001" in instance.deactivated_users


def test_somebody_who_never_signed_in_has_nothing_to_revoke(
    instance: FakeZitadel, member: User
) -> None:
    """An honest empty answer, not a failure: there is no account to deactivate."""
    applied = apply_identity_config(
        IdentityConfigSync(kind=KIND_IDENTITY_REVOCATION, key=str(member.pk))
    )
    assert applied.resource_id == ""
    assert instance.deactivated_users == set()


def test_erasure_asks_for_the_revocation(
    instance: FakeZitadel, tenant: Tenant, owner_actor: Actor, member: User
) -> None:
    """At the service seam: the erasing transaction commits, the run is claimed.

    Re-pointed to the platform population by ADR ident-7, alongside
    `test_a9_matrix.py` row 20: the run this member's erasure claims is
    `platform:...`, not `<tenant.slug>:...`, because the credential is Zitadel's
    and the tenant it was erased in never owned it.
    """
    record_identity(
        realm=STAFF_REALM, user=member, subject="9001", tenant=None, actor=system_actor(tenant=None)
    )

    erase_user(user=member, actor=owner_actor, tenant=tenant)

    workflow_id = f"platform:accounts:identity_revocation:{member.pk}"
    run = WorkflowRun.objects.for_platform().get(workflow_id=workflow_id)
    assert run.tenant_id is None
    assert run.type == SYNC_IDENTITY_CONFIG_WORKFLOW
    assert not WorkflowRun.objects.for_tenant(tenant).filter(workflow_id=workflow_id)


def test_erasing_somebody_who_never_signed_in_asks_for_nothing(
    instance: FakeZitadel, tenant: Tenant, owner_actor: Actor, member: User
) -> None:
    """The honest skip: no `zitadel_sub`, so no account and no run at all.

    Re-pointed with its sibling above (ADR ident-7): the population the run
    would have landed in is the platform's, so that is the population an
    *absence* has to be measured against. Read through the tenant, this
    assertion would have gone on passing whether the skip worked or not.
    """
    erase_user(user=member, actor=owner_actor, tenant=tenant)

    assert not WorkflowRun.objects.for_platform().filter(
        workflow_id__contains="identity_revocation"
    )
    assert not WorkflowRun.objects.for_tenant(tenant).filter(
        workflow_id__contains="identity_revocation"
    )


def test_a_person_with_no_tenant_anywhere_is_erased_and_revoked(
    instance: FakeZitadel, nomad: User, tenant: Tenant, other_tenant: Tenant
) -> None:
    """**The amendment of the pin, said out loud rather than silently.**

    This test used to be
    `test_a_person_with_no_tenant_anywhere_is_erased_and_the_gap_is_named`, and
    it pinned the hole: `WorkflowRun` was tenant-scoped, a person with no
    membership left nowhere to record the revocation run, so `erase_user` logged
    `accounts.identity.not_revoked` and moved on — and the Zitadel account
    survived the erasure. With `SOCIALACCOUNT_ONLY` that account is the only way
    anybody signs in, so the erased person could sign straight back in.

    Amended under **ADR workflows-3**
    (`docs/product/architecture.md`, the ADR home), which made
    `WorkflowRun` the platform-wide run
    ledger: null tenant is a declared population with its own reserved first id
    segment. The gap it pinned is closed, so what it pins now is the closure —
    the run exists, it is the platform's, and no tenant's ledger carries it.

    **And it is no longer a half.** ADR ident-7 made
    every revocation a platform run: `_a_tenant_of` — which used to record a
    tenanted person's revocation in a borrowed workspace's ledger — is deleted,
    and the shape this test pins is now the universal one rather than the nomad's
    special case. Its siblings (`test_erasure_asks_for_the_revocation`, and
    `test_a9_matrix.py` row 20) were re-pointed to exactly these assertions.
    """
    from apps.core.actor import system_actor

    record_identity(
        realm=STAFF_REALM, user=nomad, subject="9002", tenant=None, actor=system_actor(tenant=None)
    )

    erase_user(user=nomad, actor=system_actor(), tenant=None)

    nomad.refresh_from_db()
    assert nomad.email.startswith("erased+")

    workflow_id = f"platform:accounts:identity_revocation:{nomad.pk}"
    run = WorkflowRun.objects.for_platform().get(workflow_id=workflow_id)
    assert run.tenant_id is None
    assert run.type == SYNC_IDENTITY_CONFIG_WORKFLOW
    # The run is nobody's but the deployment's — including the two seeded
    # workspaces this person never belonged to.
    for seeded in (tenant, other_tenant):
        assert not WorkflowRun.objects.for_tenant(seeded).filter(workflow_id=workflow_id)


def test_the_tenantless_revocation_reaches_zitadel(
    instance: FakeZitadel, nomad: User, caplog: pytest.LogCaptureFixture
) -> None:
    """**The other half: the account is actually deactivated.**

    A recorded run that nothing executes would close the gap on paper and leave the
    credential live. So the run's activity is driven at the client seam the rest
    of this module uses (`FakeZitadel`, ident-5's posture — nothing dials), with
    **no principal restored**, which is the posture a platform run's activity
    really arrives in.

    `accounts.identity.not_revoked` is asserted absent by name: it was the log
    line that stood in for the missing revocation, and a line nobody deletes is
    how a closed gap comes back.
    """
    from apps.core.actor import system_actor

    instance.users["9002"] = {"id": "9002", "userName": nomad.email}
    instance.user_links["9002"] = [{"idpId": "77", "providedUserId": "google|abc"}]
    record_identity(
        realm=STAFF_REALM, user=nomad, subject="9002", tenant=None, actor=system_actor(tenant=None)
    )

    with caplog.at_level(logging.WARNING):
        erase_user(user=nomad, actor=system_actor(), tenant=None)
    assert "accounts.identity.not_revoked" not in caplog.text

    applied = apply_identity_config(
        IdentityConfigSync(kind=KIND_IDENTITY_REVOCATION, key=str(nomad.pk))
    )

    assert applied.resource_id == "9002"
    assert "9002" in instance.deactivated_users
    assert instance.user_links["9002"] == []


def test_the_platform_segment_this_app_writes_is_the_one_the_starter_checks(
    db: None,
) -> None:
    """The repeated literal, pinned against its source.

    `apps.accounts` may not import `apps.workflows` (the layer contract; the
    starter arrives through `core.bridge`), so `PLATFORM_RUN_SEGMENT` restates
    the segment `check_workflow_id` decides by — the same shape, and for the
    same reason, as `core.services.RESERVED_TENANT_SLUGS`. A test may import
    across apps, so the repeat is pinned here rather than trusted.
    """
    from apps.accounts.services import PLATFORM_RUN_SEGMENT
    from apps.workflows.services import PLATFORM_SEGMENT

    assert PLATFORM_RUN_SEGMENT == PLATFORM_SEGMENT


# --- The web client's secret, recoverable (R4 finding) -----------------------


def test_rotating_the_web_secret_prints_a_new_one_and_keeps_the_id(
    instance: FakeZitadel, settings: Any, capsys: Any
) -> None:
    """The way back from a lost secret, and what it must not disturb.

    The client **id** is what every registered redirect URI and every other line
    of `.env` already names, so the property that matters is that seeding and
    rotating leave the same objects: only the secret is new.
    """
    settings.DEBUG = False
    call_command("zitadel_seed", "--skip-user")
    seeded = dict(instance.apps)

    call_command("zitadel_seed", "--skip-user", "--rotate-web-secret")

    printed = capsys.readouterr().out
    assert "rotated" in printed
    assert "clientSecret: rotated-1-" in printed
    # Same project, same applications, same ids.
    assert {app_id: row["name"] for app_id, row in instance.apps.items()} == {
        app_id: row["name"] for app_id, row in seeded.items()
    }
    assert len(instance.rotations) == 1


def test_seeding_without_the_flag_rotates_nothing(
    instance: FakeZitadel, settings: Any, capsys: Any
) -> None:
    """Rotation never happens as a side effect. That is the whole reason it is a flag."""
    settings.DEBUG = False
    call_command("zitadel_seed", "--skip-user")
    call_command("zitadel_seed", "--skip-user")

    assert instance.rotations == []
    assert "rotated" not in capsys.readouterr().out


def test_a_second_rotation_is_a_second_secret(
    instance: FakeZitadel, settings: Any, capsys: Any
) -> None:
    """It does not pretend to be idempotent, because it is not and must not be."""
    settings.DEBUG = False
    call_command("zitadel_seed", "--skip-user")
    call_command("zitadel_seed", "--skip-user", "--rotate-web-secret")
    call_command("zitadel_seed", "--skip-user", "--rotate-web-secret")

    printed = capsys.readouterr().out
    assert "rotated-1-" in printed
    assert "rotated-2-" in printed
    assert len(instance.rotations) == 2


# --- every revocation is the platform's, and the seam says so ------


def test_a_tenanted_members_revocation_is_the_platforms_too(
    instance: FakeZitadel,
    tenant: Tenant,
    other_tenant: Tenant,
    owner_actor: Actor,
    member: User,
) -> None:
    """**B2-6 / ADR ident-7: the borrow is gone, for somebody who does belong.**

    `_a_tenant_of` used to pick any tenant this person held a membership in and
    record the revocation there, deterministically — which made the borrow
    repeatable and left it exactly as wrong. The credential is Zitadel's; no
    workspace owns it; so no workspace's ledger claims it. `for_tenant` fails
    closed and can never reach the null population, so the absence below holds
    for *every* tenant rather than for the one that used to be borrowed.
    """
    from apps.core.models import Membership
    from apps.core.services import add_membership

    # A second membership, deliberately not an owner one: `erase_user` refuses to
    # orphan a tenant, and this test is about the ledger, not about that refusal.
    add_membership(
        user=member,
        tenant=other_tenant,
        role=Membership.Role.MEMBER,
        actor=system_actor(tenant=other_tenant),
    )
    record_identity(
        realm=STAFF_REALM, user=member, subject="9001", tenant=None, actor=system_actor(tenant=None)
    )

    erase_user(user=member, actor=owner_actor, tenant=tenant)

    workflow_id = f"platform:accounts:identity_revocation:{member.pk}"
    run = WorkflowRun.objects.for_platform().get(workflow_id=workflow_id)
    assert run.tenant_id is None
    assert run.type == SYNC_IDENTITY_CONFIG_WORKFLOW
    for seeded in Tenant.objects.all():
        assert not WorkflowRun.objects.for_tenant(seeded).filter(
            workflow_id__contains="identity_revocation"
        )


def test_erasing_the_same_person_twice_is_still_one_run(
    instance: FakeZitadel, tenant: Tenant, owner_actor: Actor, member: User
) -> None:
    """The retry contract, unchanged by the move (ADR ident-7 says so explicitly).

    One deterministic id per person means the second ask is the same ask, and it
    is absorbed as already-asked rather than raising: erasing an already-erased
    person is not two revocations. `erase_user` refuses its own second call for
    unrelated reasons, so the run is re-requested at the seam that owns the
    contract.
    """
    from apps.accounts.services import _revoke_identity_platform_access

    record_identity(
        realm=STAFF_REALM, user=member, subject="9001", tenant=None, actor=system_actor(tenant=None)
    )

    first = _revoke_identity_platform_access(user=member, actor=owner_actor)
    second = _revoke_identity_platform_access(user=member, actor=owner_actor)

    assert first == second == str(member.pk)
    assert (
        WorkflowRun.objects.for_platform()
        .filter(workflow_id=f"platform:accounts:identity_revocation:{member.pk}")
        .count()
        == 1
    )


def test_the_platform_kinds_resolve_their_scope_through_the_bridge(
    instance: FakeZitadel, member: User
) -> None:
    """**B2-5 / ADR core-9: the accessor is reached, not skipped.**

    Before the bridge key existed these two kinds called nothing at all — the
    accessor lives in `apps.workflows`, which sits above this app, so the
    builder could not reach it. "Resolves its scope" is a claim about a call
    being made, and the only way to fail such a claim is to make the call
    observable. So the registered callable is swapped for one that records.
    """
    from apps.core import bridge

    calls: list[str] = []

    def recording() -> tuple[Any, Any, Any]:
        calls.append("asked")
        return (None, None, None)

    real = bridge.registered()[bridge.PLATFORM_CONTEXT]
    bridge.register(bridge.PLATFORM_CONTEXT, recording)
    try:
        instance.users["9001"] = {"id": "9001", "userName": member.email}
        record_identity(
            realm=STAFF_REALM,
            user=member,
            subject="9001",
            tenant=None,
            actor=system_actor(tenant=None),
        )
        apply_identity_config(IdentityConfigSync(kind=KIND_IDENTITY_REVOCATION, key=str(member.pk)))
    finally:
        bridge.register(bridge.PLATFORM_CONTEXT, real)

    assert calls == ["asked"]


def test_a_platform_kind_under_tenant_stamped_headers_is_refused(
    instance: FakeZitadel, acting: None, tenant: Tenant, member: User
) -> None:
    """**B2-5's loud contract: the mismatch is named, not absorbed.**

    `acting` stamps the headers a *tenanted* run arrives with. A platform kind
    cannot legitimately arrive that way — `_start_identity_run` gives it
    `tenant=None` and `org=None` — so a run that does was started wrong, and
    doing the deployment's work under one customer's scope is W4-2's silence
    one app over. The refusal names the kind and the scope it found, and
    nothing reaches Zitadel.

    It lands at the activity and not inside `platform_context()`, which is a
    plain contextvar read and hands a stamped tenant straight back; that is
    pinned as found in `apps/workflows/tests/test_platform_context_bridge.py`.
    """
    instance.users["9001"] = {"id": "9001", "userName": member.email}
    record_identity(
        realm=STAFF_REALM, user=member, subject="9001", tenant=None, actor=system_actor(tenant=None)
    )

    with pytest.raises(RuntimeError) as refused:
        apply_identity_config(IdentityConfigSync(kind=KIND_IDENTITY_REVOCATION, key=str(member.pk)))

    assert KIND_IDENTITY_REVOCATION in str(refused.value)
    assert tenant.slug in str(refused.value)
    assert "9001" not in instance.deactivated_users


def test_the_workforce_kind_is_refused_under_a_tenant_hat_as_well(
    instance: FakeZitadel, workforce: None, acting: None, tenant: Tenant
) -> None:
    """Both platform kinds, not only the one already moved.

    The workforce door is the other member of the population: it reaches Zitadel
    with the deployment's own credentials and resolved nothing at all, so a stray
    tenant hat on that run would have gone equally unnoticed. The refusal is
    before the credential is read, so nothing is created.
    """
    with pytest.raises(RuntimeError) as refused:
        apply_identity_config(IdentityConfigSync(kind=KIND_WORKFORCE_PROVIDER, key="workforce-abc"))

    assert KIND_WORKFORCE_PROVIDER in str(refused.value)
    assert tenant.slug in str(refused.value)


def test_the_tenanted_kind_is_untouched_by_all_of_this(
    instance: FakeZitadel, acting: None, sso_connection: SsoConnection
) -> None:
    """`KIND_SSO_CONNECTION` still asks `WORKFLOW_CONTEXT` and still needs a tenant.

    The refusal above is scoped to the two platform kinds by construction — it is
    called on their branches and nowhere else — and a customer's connection sync
    under tenanted headers behaves exactly as it did.
    """
    applied = apply_identity_config(
        IdentityConfigSync(kind=KIND_SSO_CONNECTION, key=str(sso_connection.pk))
    )

    assert applied.kind == KIND_SSO_CONNECTION
    assert applied.resource_id != ""
