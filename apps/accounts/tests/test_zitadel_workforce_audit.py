"""`zitadel_audit` sees the workforce door too, and still changes nothing.

The audit walked every customer `SsoConnection`
and said nothing at all about the **workforce** provider — the one door the
people who build and run this product sign in through, and the one whose intent
is the *environment* rather than a row (`_apply_workforce_provider`: "nothing is
written back, and that is the honest shape"). With no row to compare against,
nothing reconciled it, and rule 27's declared blind spot — the console, which no
check can see — covered exactly the door with no row behind it.

**What is compared, and what is not.** `GOOGLE_WORKSPACE_DOMAINS` is the switch:
empty means the workforce door is off (`config/settings/base.py`), non-empty
means it is on. Zitadel holds the provider. So the reconciliation is between
those two, in both directions, plus the client id the provider actually carries
— because a console re-point at somebody else's Google project is the change
that lets strangers in and that no row of ours would ever notice.

The domain *list* is deliberately not in Zitadel at all (ADR ident-6:
`GOOGLE_WORKSPACE_DOMAINS` stays ours, enforced by
`policies.is_workforce_email` when an assertion arrives, because a restriction
expressed only in somebody else's console is a restriction we cannot test), so
there is no per-domain set to diff. The report prints the list beside the
provider and says where it is enforced, which is the honest thing to print.

Nothing here dials Zitadel: `FakeZitadel` is the socket, as everywhere else in
`test_zitadel.py` and `test_federation.py`.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.core.management import call_command

from apps.accounts import zitadel
from apps.accounts.tests.conftest import FakeZitadel

pytestmark = pytest.mark.django_db(transaction=True)

WORKFORCE_DOMAIN = "union.studio"
CLIENT_ID = "google-client-id"


@pytest.fixture
def workforce(settings: Any) -> None:
    """A deployment whose workforce door is configured — both halves."""
    settings.GOOGLE_OAUTH_CLIENT_ID = CLIENT_ID
    settings.GOOGLE_OAUTH_CLIENT_SECRET = "google-client-secret"  # noqa: S105 — a fake IdP client secret the test world configures  # pragma: allowlist secret
    settings.GOOGLE_WORKSPACE_DOMAINS = [WORKFORCE_DOMAIN]


@pytest.fixture
def door_off(settings: Any) -> None:
    """A deployment where the workforce door is switched off."""
    settings.GOOGLE_OAUTH_CLIENT_ID = CLIENT_ID
    settings.GOOGLE_OAUTH_CLIENT_SECRET = "google-client-secret"  # noqa: S105 — a fake IdP client secret the test world configures  # pragma: allowlist secret
    settings.GOOGLE_WORKSPACE_DOMAINS = []


def _materialise_the_workforce_provider(name: str = "") -> str:
    """Put a Google provider in the instance, the way the activity would."""
    from apps.accounts.zitadel import WORKFORCE_IDP_NAME

    resource = zitadel.ensure_google_identity_provider(
        name=name or WORKFORCE_IDP_NAME,
        client_id=CLIENT_ID,
        client_secret="google-client-secret",  # noqa: S106 — a fake IdP client secret the test world configures  # pragma: allowlist secret
    )
    return resource.id


def test_a_configured_door_with_a_matching_provider_agrees(
    instance: FakeZitadel, workforce: None, capsys: Any
) -> None:
    _materialise_the_workforce_provider()
    capsys.readouterr()

    call_command("zitadel_audit")

    out = capsys.readouterr().out
    assert "workforce" in out
    assert WORKFORCE_DOMAIN in out
    assert "DRIFT" not in out


def test_a_configured_door_with_no_provider_in_zitadel_is_drift(
    instance: FakeZitadel, workforce: None, capsys: Any
) -> None:
    """Domains named here, nothing in Zitadel: staff cannot sign in and nobody knew."""
    capsys.readouterr()

    with pytest.raises(SystemExit) as exit_info:
        call_command("zitadel_audit")

    out = capsys.readouterr().out
    assert exit_info.value.code == 1
    assert "DRIFT" in out
    assert "workforce" in out
    assert WORKFORCE_DOMAIN in out


def test_the_drift_remedy_names_a_command_that_exists(
    instance: FakeZitadel, workforce: None, capsys: Any
) -> None:
    """The way out this report offers has to be one an operator can take.

    The line used to read "run manage.py zitadel_seed or
    sync_workforce_identity_config", and neither half worked: `zitadel_seed`
    makes the project, the applications and the dev user and has never touched a
    provider, and `sync_workforce_identity_config` is the *service* — a name with
    no command behind it, so pasting it gets "Unknown command".

    A remedy that does not work is worse than none. It costs the reader the time
    to try it and then the trust to believe the next one, and it does that at the
    exact moment they have already found out that nobody on their staff can sign
    in.

    Asserted against Django's own command registry rather than against a string,
    because the failure mode is precisely a name that reads plausibly and is not
    there.
    """
    from django.core.management import get_commands

    capsys.readouterr()
    with pytest.raises(SystemExit):
        call_command("zitadel_audit")
    out = capsys.readouterr().out

    named = [word.strip(".,") for word in out.split() if word.strip(".,") in get_commands()]
    assert "sync_workforce_idp" in named
    assert "sync_workforce_identity_config" not in out
    # The phantom pairing is gone. `zitadel_seed` may still be named elsewhere in
    # a report about the objects it does make; it may not be named as the way out
    # of a missing workforce provider.
    workforce_line = next(
        line for line in out.splitlines() if "workforce" in line and "DRIFT" in line
    )
    assert "zitadel_seed" not in workforce_line


def test_a_provider_with_the_door_switched_off_here_is_drift(
    instance: FakeZitadel, door_off: None, capsys: Any
) -> None:
    """The other direction: a live Google door onto a product that refuses everybody."""
    _materialise_the_workforce_provider()
    capsys.readouterr()

    with pytest.raises(SystemExit) as exit_info:
        call_command("zitadel_audit")

    out = capsys.readouterr().out
    assert exit_info.value.code == 1
    assert "DRIFT" in out
    assert "GOOGLE_WORKSPACE_DOMAINS" in out


def test_a_provider_repointed_at_another_google_project_is_drift(
    instance: FakeZitadel, workforce: None, capsys: Any
) -> None:
    """The console change our rows structurally cannot see."""
    idp_id = _materialise_the_workforce_provider()
    instance.idps[idp_id]["config"]["google"]["clientId"] = "somebody-elses-project"
    capsys.readouterr()

    with pytest.raises(SystemExit):
        call_command("zitadel_audit")

    out = capsys.readouterr().out
    assert "DRIFT" in out
    assert "somebody-elses-project" in out


def test_a_door_that_is_off_on_both_sides_agrees(
    instance: FakeZitadel, door_off: None, capsys: Any
) -> None:
    """The fourth state, so the two drifts above are not "any answer is drift"."""
    capsys.readouterr()

    call_command("zitadel_audit")

    out = capsys.readouterr().out
    assert "workforce" in out
    assert "DRIFT" not in out


def test_the_workforce_provider_is_not_counted_as_unclaimed(
    instance: FakeZitadel, workforce: None, capsys: Any
) -> None:
    """It has no row, so the row-by-row walk cannot claim it — the audit does."""
    _materialise_the_workforce_provider()
    capsys.readouterr()

    call_command("zitadel_audit")

    assert "unclaimed" not in capsys.readouterr().out


def test_the_workforce_audit_changes_nothing(
    instance: FakeZitadel, workforce: None, capsys: Any
) -> None:
    """The property the rest of the audit already holds, extended to this section."""
    _materialise_the_workforce_provider()
    before = json.dumps(instance.idps, sort_keys=True)
    instance.requests.clear()
    capsys.readouterr()

    call_command("zitadel_audit")

    assert json.dumps(instance.idps, sort_keys=True) == before
    assert all(method == "GET" or path.endswith("_search") for method, path in instance.requests), (
        instance.requests
    )
