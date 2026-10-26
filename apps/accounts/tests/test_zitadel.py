"""The management client, the activity, and the two commands — Zitadel down.

**Nothing here dials anything** (ADR ident-5). `config/settings/test.py` points
the issuer at port 1 and blanks the PAT, and the fixture below replaces the
client's socket with `httpx.MockTransport` while leaving everything above it
alone: the real `_call`, the real URL paths, the real payloads, the real
search-then-create decisions. What is replaced is the network and only the
network, which is why these tests can prove idempotence rather than proving that
a stub was called.

The instance the stub keeps is a dictionary, and it behaves the way Zitadel does
in the two ways that matter: creating twice under one name really does make two
objects, and a `GET` of a deleted id really does 404. A stub that quietly
de-duplicated would make `ensure_*` look idempotent when it was not.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from django.core.management import call_command

from apps.accounts import zitadel
from apps.accounts.activities import apply_identity_config
from apps.accounts.models import SsoConnection
from apps.accounts.selectors import get_tenant_realm
from apps.accounts.tests.conftest import FakeZitadel
from apps.accounts.types import KIND_SSO_CONNECTION, IdentityConfigSync
from apps.core.models import Organization, Tenant
from apps.workflows import context as workflow_context

# --- the posture (W2R2-5) -----------------------------------------------------


def test_the_suite_cannot_reach_zitadel() -> None:
    """ident-5's first layer, asserted rather than assumed.

    A settings module is a file somebody can edit; this is what makes editing it
    a failing test rather than a suite that quietly starts configuring a shared
    identity instance.
    """
    from django.conf import settings as live

    assert live.ZITADEL_ISSUER == "http://127.0.0.1:1"
    assert live.ZITADEL_PAT == ""
    assert not zitadel.configured()


def test_the_client_refuses_before_it_opens_a_socket() -> None:
    """Unconfigured is a refusal, not a ten-second timeout."""
    with pytest.raises(zitadel.ZitadelNotConfigured):
        zitadel.organization()


# --- idempotence (W2R2-3) -----------------------------------------------------


def test_ensure_project_creates_once_and_then_reuses(instance: FakeZitadel) -> None:
    first = zitadel.ensure_project(name="Thing")
    second = zitadel.ensure_project(name="Thing")

    assert first.created is True
    assert second.created is False
    assert first.id == second.id
    assert len(instance.projects) == 1


def test_ensure_application_creates_once_and_then_reuses(instance: FakeZitadel) -> None:
    project = zitadel.ensure_project(name="Thing")
    first = zitadel.ensure_web_application(
        project_id=project.id, name="Web", redirect_uris=["http://x/cb"], post_logout_uris=["/"]
    )
    second = zitadel.ensure_web_application(
        project_id=project.id, name="Web", redirect_uris=["http://x/cb"], post_logout_uris=["/"]
    )

    assert first.id == second.id
    assert len(instance.apps) == 1
    # The secret exists exactly once, and the second answer says so rather than
    # inventing one.
    assert first.detail["clientSecret"]
    assert "clientSecret" not in second.detail


def test_ensure_idp_updates_the_object_our_row_already_names(instance: FakeZitadel) -> None:
    """The real idempotence: the retry updates, it does not twin.

    This is the one that matters, because Temporal's at-least-once delivery
    means the second call is the normal case rather than the exception.
    """
    made = zitadel.ensure_oidc_identity_provider(
        name="acme",
        issuer="https://a.example",
        client_id="c",
        client_secret="s",  # noqa: S106 — a fake IdP client secret the test world configures
    )
    again = zitadel.ensure_oidc_identity_provider(
        name="acme",
        issuer="https://a.example",
        client_id="c",
        client_secret="s",  # noqa: S106 — a fake IdP client secret the test world configures
        existing_id=made.id,
    )

    assert made.created is True
    assert again.created is False
    assert again.id == made.id
    assert len(instance.idps) == 1
    assert ("PUT", f"/idps/generic_oidc/{made.id}") in instance.requests


def test_ensure_idp_finds_by_name_when_the_row_carries_no_id(instance: FakeZitadel) -> None:
    """The second net, for a row whose write-back never landed."""
    made = zitadel.ensure_oidc_identity_provider(
        name="acme",
        issuer="https://a.example",
        client_id="c",
        client_secret="s",  # noqa: S106 — a fake IdP client secret the test world configures
    )
    again = zitadel.ensure_oidc_identity_provider(
        name="acme",
        issuer="https://a.example",
        client_id="c",
        client_secret="s",  # noqa: S106 — a fake IdP client secret the test world configures
    )

    assert again.id == made.id
    assert len(instance.idps) == 1


def test_ensure_idp_recreates_when_the_recorded_id_is_gone(instance: FakeZitadel) -> None:
    """Somebody deleted it in the console; a re-sync repairs rather than dies."""
    made = zitadel.ensure_oidc_identity_provider(
        name="acme",
        issuer="https://a.example",
        client_id="c",
        client_secret="s",  # noqa: S106 — a fake IdP client secret the test world configures
    )
    instance.idps.clear()

    again = zitadel.ensure_oidc_identity_provider(
        name="acme",
        issuer="https://a.example",
        client_id="c",
        client_secret="s",  # noqa: S106 — a fake IdP client secret the test world configures
        existing_id=made.id,
    )

    assert again.created is True
    assert again.id != made.id
    assert len(instance.idps) == 1


# --- the activity and the commands (W2R2-1, W2R2-2, W2R2-3, W2R2-4) ----------
#
# `transaction=True` from here down. An activity calls `close_old_connections()`
# at both ends — it has no request cycle to do it for it — and that closes the
# wrapping transaction a plain `django_db` test runs inside. The commands are
# doors onto the same code and take it for the same reason. This is the shape
# `apps/events/tests/test_activities.py` already carries, and its comment says
# so too.


@pytest.fixture
def acting(tenant: Tenant, root_org: Organization) -> Iterator[None]:
    """The workflow headers the interceptor would have restored."""
    tokens = workflow_context.set_principal(
        tenant_id=str(tenant.pk), user_id=None, org_id=str(root_org.pk)
    )
    yield
    workflow_context.reset_principal(tokens)


@pytest.mark.django_db(transaction=True)
def test_the_activity_materialises_and_writes_the_resource_id_back(
    instance: FakeZitadel,
    acting: None,
    sso_connection: SsoConnection,
) -> None:
    applied = apply_identity_config(
        IdentityConfigSync(kind=KIND_SSO_CONNECTION, key=str(sso_connection.pk))
    )

    sso_connection.refresh_from_db()
    assert sso_connection.zitadel_idp_id == applied.resource_id
    assert sso_connection.sync_state == SsoConnection.SyncState.APPLIED
    # The object really is there, in the tenant's realm, under the name the
    # audit will look for.
    realm = get_tenant_realm(sso_connection.tenant)
    assert realm is not None
    remote = zitadel.get_identity_provider(idp_id=applied.resource_id, org_id=realm.id)
    assert remote is not None
    assert remote["name"] == sso_connection.idp_name
    assert zitadel.oidc_issuer_of(remote) == sso_connection.issuer


@pytest.mark.django_db(transaction=True)
def test_the_activity_twice_leaves_one_object(
    instance: FakeZitadel,
    acting: None,
    sso_connection: SsoConnection,
) -> None:
    """W2R2-3, at the level Temporal actually retries: the activity."""
    payload = IdentityConfigSync(kind=KIND_SSO_CONNECTION, key=str(sso_connection.pk))

    first = apply_identity_config(payload)
    second = apply_identity_config(payload)

    assert first.resource_id == second.resource_id
    assert len(instance.idps) == 1


@pytest.mark.django_db(transaction=True)
def test_the_activity_refuses_a_connection_that_is_gone(
    instance: FakeZitadel,
    acting: None,
    sso_connection: SsoConnection,
) -> None:
    """Deleted mid-run: it raises, Temporal retries, the run fails saying so.

    Which is the honest outcome — quietly succeeding at nothing would leave a
    `WorkflowRun` marked completed for work nobody did.
    """
    from apps.core.exceptions import NotFound

    payload = IdentityConfigSync(kind=KIND_SSO_CONNECTION, key=str(sso_connection.pk))
    SsoConnection.objects.filter(pk=sso_connection.pk).delete()

    with pytest.raises(NotFound):
        apply_identity_config(payload)
    assert not instance.idps


@pytest.mark.django_db(transaction=True)
def test_the_activity_refuses_a_config_kind_it_does_not_know(
    instance: FakeZitadel,
    acting: None,
    sso_connection: SsoConnection,
) -> None:
    with pytest.raises(ValueError, match="config kind"):
        apply_identity_config(IdentityConfigSync(kind="nonsense", key=str(sso_connection.pk)))
    assert not instance.idps


@pytest.mark.django_db(transaction=True)
def test_zitadel_seed_is_idempotent(instance: FakeZitadel, settings: Any, capsys: Any) -> None:
    """W2R2-1, in the suite: the second run makes nothing and says so.

    `DEBUG` on, because the dev person is the one object the command refuses to
    make without it — and a seed test that skipped it would be proving the
    idempotence of three objects and calling it four.
    """
    settings.DEBUG = True
    call_command("zitadel_seed")
    first = capsys.readouterr().out
    made = (len(instance.projects), len(instance.apps), len(instance.users))

    call_command("zitadel_seed")
    second = capsys.readouterr().out

    assert (len(instance.projects), len(instance.apps), len(instance.users)) == made
    assert made == (1, 3, 1)
    assert "created project" in first
    assert "created" not in second
    assert second.count("exists") >= 4


@pytest.mark.django_db(transaction=True)
def test_zitadel_seed_skips_the_dev_person_outside_debug(
    instance: FakeZitadel, settings: Any, capsys: Any
) -> None:
    """The same guard `seed` carries, for the same reason.

    `ZITADEL_DEV_USER_PASSWORD` ships in `.env.example`. A person with a
    published password on an internet-facing deployment is not test data.
    """
    settings.DEBUG = False
    call_command("zitadel_seed")

    assert instance.users == {}
    assert "skipped user" in capsys.readouterr().out


@pytest.mark.django_db(transaction=True)
def test_rotating_the_mcp_secret_mints_one_and_leaves_every_id_alone(
    instance: FakeZitadel, settings: Any, capsys: Any
) -> None:
    """The MCP resource's secret gets the recovery path the browser
    client already had.

    `ensure_api_application` prints a `clientSecret` on the run that creates it
    and Zitadel never shows it again, so a deployment that lost it had one way
    forward: delete the application, take a new app id, and re-register every
    audience that names it. That is not a rotation, it is an outage.

    What is pinned is the *idempotent surround*, which is the whole reason
    rotation is a flag and not a step: the project and all three applications
    are the same objects before and after, so a rotation repairs a lost secret
    without disturbing anything a deployment already configured.
    """
    settings.DEBUG = True
    call_command("zitadel_seed")
    capsys.readouterr()
    before = {app_id: dict(app) for app_id, app in instance.apps.items()}
    resource_id = next(
        app_id
        for app_id, app in instance.apps.items()
        if app["name"] == settings.ZITADEL_MCP_RESOURCE_NAME
    )

    call_command("zitadel_seed", "--rotate-mcp-secret")
    out = capsys.readouterr().out

    assert instance.rotations == [resource_id], "the browser client must not be touched"
    assert {app_id: dict(app) for app_id, app in instance.apps.items()} == before
    assert "rotated mcp secret" in out
    # `rotated`, never `exists`: a command that claimed idempotence it does not
    # have is worse than one that has none.
    assert "exists  mcp resource" in out
    assert "rotated" in out


@pytest.mark.django_db(transaction=True)
def test_the_rotated_mcp_secret_is_printed_once_and_stored_nowhere(
    instance: FakeZitadel, settings: Any, capsys: Any
) -> None:
    """**The half that matters.** The plaintext reaches the operator and no one else.

    It is on stdout exactly once, and it is in no row of ours — the command
    writes nothing at all (`zitadel_seed`'s docstring: the objects it makes are
    deployment infrastructure, not any tenant's configuration) — so a second run
    is a second rotation and there is nothing anywhere to read the first one back
    out of. The warning after it says so in the operator's own words.
    """
    settings.DEBUG = True
    call_command("zitadel_seed")
    capsys.readouterr()

    call_command("zitadel_seed", "--rotate-mcp-secret")
    out = capsys.readouterr().out

    minted = f"rotated-{len(instance.rotations)}-"
    secret = next(line for line in out.splitlines() if minted in line)
    assert out.count(secret.split("clientSecret: ")[1]) == 1
    assert "cannot be printed again" in out
    assert instance.apps and all(
        "clientSecret" not in json.dumps(app) for app in instance.apps.values()
    )


@pytest.mark.django_db(transaction=True)
def test_a_plain_seed_run_rotates_nothing(
    instance: FakeZitadel, settings: Any, capsys: Any
) -> None:
    """Rotation is never a side effect of a seed run — that is why it is a flag.

    Without this the two rotations would be free to creep into `./scripts/setup.sh`'s
    path and break every `.env` the previous run filled in.
    """
    settings.DEBUG = True
    call_command("zitadel_seed")
    call_command("zitadel_seed")
    capsys.readouterr()

    assert instance.rotations == []


@pytest.mark.django_db
def test_zitadel_seed_refuses_without_configuration(settings: Any) -> None:
    from django.core.management.base import CommandError

    settings.ZITADEL_PAT = ""
    with pytest.raises(CommandError, match="not configured"):
        call_command("zitadel_seed")


@pytest.mark.django_db(transaction=True)
def test_zitadel_audit_agrees_when_nothing_has_drifted(
    instance: FakeZitadel,
    acting: None,
    sso_connection: SsoConnection,
    capsys: Any,
) -> None:
    apply_identity_config(IdentityConfigSync(kind=KIND_SSO_CONNECTION, key=str(sso_connection.pk)))
    capsys.readouterr()

    call_command("zitadel_audit")

    out = capsys.readouterr().out
    assert "agrees" in out
    assert "DRIFT" not in out


@pytest.mark.django_db(transaction=True)
def test_zitadel_audit_reports_drift_and_changes_nothing(
    instance: FakeZitadel,
    acting: None,
    sso_connection: SsoConnection,
    capsys: Any,
) -> None:
    """W2R2-4's second half: a hand-mutated instance, and a report that repairs nothing.

    The mutation is a raw write straight into the instance — standing in for
    somebody in the console, which is the thing no check can see. Both halves
    are asserted: the drift is named, and **every request the audit made was a
    read**. The second assertion is the one that would catch a future "while
    we're here, fix it" commit.
    """
    applied = apply_identity_config(
        IdentityConfigSync(kind=KIND_SSO_CONNECTION, key=str(sso_connection.pk))
    )
    instance.idps[applied.resource_id]["name"] = "renamed-in-the-console"
    before = json.dumps(instance.idps, sort_keys=True)
    instance.requests.clear()
    capsys.readouterr()

    with pytest.raises(SystemExit) as exit_info:
        call_command("zitadel_audit")

    out = capsys.readouterr().out
    assert exit_info.value.code == 1
    assert "DRIFT" in out
    assert "renamed-in-the-console" in out
    assert json.dumps(instance.idps, sort_keys=True) == before
    assert all(method == "GET" or path.endswith("_search") for method, path in instance.requests), (
        instance.requests
    )


@pytest.mark.django_db(transaction=True)
def test_zitadel_audit_reports_a_row_whose_idp_is_gone(
    instance: FakeZitadel,
    acting: None,
    sso_connection: SsoConnection,
    capsys: Any,
) -> None:
    apply_identity_config(IdentityConfigSync(kind=KIND_SSO_CONNECTION, key=str(sso_connection.pk)))
    instance.idps.clear()
    capsys.readouterr()

    with pytest.raises(SystemExit):
        call_command("zitadel_audit")

    assert "which Zitadel does not have" in capsys.readouterr().out


@pytest.mark.django_db(transaction=True)
def test_zitadel_audit_counts_providers_no_row_claims(
    instance: FakeZitadel,
    sso_connection: SsoConnection,
    capsys: Any,
) -> None:
    """The blind spot's one visible edge, and it is a count rather than a verdict."""
    zitadel.ensure_oidc_identity_provider(
        name="made-by-hand",
        issuer="https://x.example",
        client_id="c",
        client_secret="s",  # noqa: S106 — a fake IdP client secret the test world configures
    )
    capsys.readouterr()

    call_command("zitadel_audit")

    assert "unclaimed   1 idp(s)" in capsys.readouterr().out


@pytest.mark.django_db
def test_an_idps_name_has_one_derivation_on_the_row(
    sso_connection: SsoConnection,
) -> None:
    """The activity, the realm adapter and the audit all read `SsoConnection.idp_name`.

    It used to be derived twice — once in the activity and once, restated, in
    the audit — and read a third time through a late import of the activity's
    private helper by the realm adapter. One derivation on the row is the road;
    this pins what it derives from: nothing renamable.
    """
    assert sso_connection.idp_name == f"{sso_connection.tenant.slug}:{sso_connection.pk}"


@pytest.mark.django_db(transaction=True)
def test_another_tenants_connection_is_audited_separately(
    instance: FakeZitadel,
    sso_connection: SsoConnection,
    other_sso_connection: SsoConnection,
    capsys: Any,
) -> None:
    """The sibling: `--tenant` narrows, and the other tenant's row is absent."""
    call_command("zitadel_audit", tenant=sso_connection.tenant.slug)

    out = capsys.readouterr().out
    assert sso_connection.name in out
    assert other_sso_connection.name not in out
