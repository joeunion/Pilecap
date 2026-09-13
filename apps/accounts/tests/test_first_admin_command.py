"""`zitadel_first_admin` opens the day-zero door once, and shuts it after.

With self-registration closed (ADR ident-8) a deployment that does not federate
had no way to its first identity but Zitadel's own console: `bootstrap_tenant`
needs a `User`, a `User` is minted by a first sign-in, and a first sign-in needs
an account somebody had to make by hand. This command is that account, made
through the writers the invitation workflow already uses (ADR ident-9).

The properties pinned here are the ones a day-zero door owes, and each is a
property rather than a mechanism:

* it makes the person and mints the code — **through the existing writers**, so
  there is no second way to create an identity in this tree;
* the invite code appears **exactly once, on stdout**, and in no log record —
  the same contract `create_invite_code` states and `zitadel_seed` gives a
  rotated client secret;
* a re-run before the person acts mints a superseding code **and says the old
  one is void**, because a code is single-use and an operator who sent the first
  link somewhere has to know it is dead;
* a run after they have set credentials is a **refusal that carries the rest of
  the runbook**, not an error id;
* and it **refuses the moment a tenant exists, before dialling anything** — from
  the first member on, `invite_member` is the only invitation path, and the
  fake's request log is what proves no call was made rather than a claim that
  none was.

Nothing here dials Zitadel: `FakeZitadel` is the socket, as everywhere else in
this app's tests.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts.tests.conftest import FakeZitadel
from apps.core.models import Tenant

pytestmark = pytest.mark.django_db(transaction=True)

FIRST_ADMIN = "ada.lovelace@yourcompany.test"

#: Zitadel's hosted set-password page, as `zitadel.invite_url` builds it. Pinned
#: as a shape rather than a literal because the id and the code are minted by
#: the fake at run time — what matters is that ONE such URL is printed and that
#: it carries both halves.
INVITE_URL = re.compile(r"http://zitadel\.test/ui/login/user/invite\?userID=(\d+)&code=([A-Z0-9]+)")


@pytest.fixture(autouse=True)
def reachable(settings: Any) -> None:
    """A deployment whose printed steps somebody else could actually open.

    Set explicitly, and it is not decoration: the suite runs with `DEBUG` off
    and `config/settings` ships `PUBLIC_BASE_URL=http://127.0.0.1:8000`, which
    is precisely the combination this command refuses — a real deployment with
    the shipped default would be refused too, on purpose. So
    every test whose subject is something else declares a reachable address, and
    the two whose subject IS that guard override this fixture with their own.
    """
    settings.PUBLIC_BASE_URL = "https://app.yourcompany.test"


def _run(capsys: Any, *, email: str = FIRST_ADMIN) -> str:
    capsys.readouterr()
    call_command("zitadel_first_admin", f"--email={email}")
    return str(capsys.readouterr().out)


def _refused(capsys: Any, *, email: str = FIRST_ADMIN) -> CommandError:
    """Run it expecting a refusal, and hand back the refusal itself.

    `call_command` re-raises `CommandError` where the real CLI writes it to
    stderr and exits with `returncode`; the exit-status claim is asserted off
    that attribute rather than repeated in prose.
    """
    capsys.readouterr()
    with pytest.raises(CommandError) as refusal:
        call_command("zitadel_first_admin", f"--email={email}")
    return refusal.value


# --- the happy path ----------------------------------------------------------


def test_it_makes_the_person_and_mints_one_code(instance: FakeZitadel, capsys: Any) -> None:
    """Both calls, through the existing writers, exactly once each.

    Asserted on the fake's request log rather than on the printed lines, because
    the lines are what the command SAYS and these are what it DID — and a second
    `invite_code` call would mean the link printed had already been superseded.
    """
    _run(capsys)

    assert ("POST", "/v2/users/human") in instance.requests
    minted = [
        path
        for method, path, _ in instance.bodies
        if method == "POST" and path.endswith("/invite_code")
    ]
    assert len(minted) == 1, instance.requests
    assert instance.users, "no person was made"


def test_the_link_is_printed_once_and_carries_both_halves(
    instance: FakeZitadel, capsys: Any
) -> None:
    """The operator's one window onto a value that exists for one use.

    Exactly one URL: a command that printed the link twice — in a summary and
    again in a step — would double the number of places somebody can paste a
    live credential out of a terminal.
    """
    out = _run(capsys)

    found = INVITE_URL.findall(out)
    assert len(found) == 1, out
    user_id, code = found[0]
    assert user_id in instance.users
    assert instance.invite_codes[user_id] == [code]


def test_the_code_is_in_no_log_record(
    instance: FakeZitadel, capsys: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """`create_invite_code`'s contract, held at the door that prints the code.

    The client's own log line names the user id and nothing more; this asserts
    the command added no line that undoes that. A credential in a log line is a
    credential in every sink the deployment forwards to.
    """
    with caplog.at_level(0):
        out = _run(capsys)

    _user_id, code = INVITE_URL.findall(out)[0]
    assert code not in caplog.text
    assert "accounts.zitadel.invite_code_created" in caplog.text


def test_it_prints_the_three_steps_in_order(instance: FakeZitadel, capsys: Any) -> None:
    """The runbook, in the order it is done, because it is done once by one person.

    The link is step zero and useless alone: the account it creates cannot own
    anything until a sign-in mints the `User` row and `bootstrap_tenant` writes
    the birth certificate. A command that printed only the link would have moved
    the wall rather than removed it.
    """
    out = _run(capsys)

    steps = [line for line in out.splitlines() if line.strip().startswith(("1.", "2.", "3."))]
    assert len(steps) == 3, out
    assert "set a password" in steps[0]
    assert "/accounts/login/" in steps[1] and FIRST_ADMIN in steps[1]
    assert "bootstrap_tenant" in steps[2] and FIRST_ADMIN in steps[2]


def test_it_writes_no_row_of_ours(instance: FakeZitadel, capsys: Any) -> None:
    """Nothing of ours changed, so nothing of ours is written — including audit.

    The birth certificate is `bootstrap_tenant`'s audited write (ADR core-17),
    and it comes last. A command that wrote a row here would be a second, quieter
    origin for an installation.
    """
    from apps.core.audit import AuditEntry

    _run(capsys)

    assert not Tenant.objects.exists()
    assert not AuditEntry.objects.exists()


# --- the second run, before the person acts ----------------------------------


def test_a_re_run_supersedes_and_says_the_old_link_is_void(
    instance: FakeZitadel, capsys: Any
) -> None:
    """Not idempotent, and it must not pretend to be.

    Zitadel supersedes rather than reissues (measured; `create_invite_code`'s
    docstring), so the first link stops working the moment this runs again. An
    operator who had already sent it needs to be told that in the same breath as
    the new one, not to discover it from somebody who could not sign in.
    """
    first = _run(capsys)
    second = _run(capsys)

    assert "is now void" in second
    assert INVITE_URL.findall(first)[0][1] != INVITE_URL.findall(second)[0][1]
    # One person, two codes: the account was found, not made again.
    assert len(instance.users) == 1
    user_id = next(iter(instance.users))
    assert len(instance.invite_codes[user_id]) == 2


def test_the_first_run_does_not_claim_a_previous_link_is_void(
    instance: FakeZitadel, capsys: Any
) -> None:
    """The other half, so the sentence above means something when it appears.

    A warning printed on every run is a warning nobody reads by the third one.
    """
    assert "is now void" not in _run(capsys)


# --- the refusals ------------------------------------------------------------


def test_a_person_who_already_signed_in_is_refused_with_the_rest_of_the_runbook(
    instance: FakeZitadel, capsys: Any
) -> None:
    """`ALREADY_INITIALIZED` is not a fault; it is a different starting point.

    They already have credentials, so there is nothing to invite them to set —
    but the two steps after the link are still exactly what has to happen, and a
    refusal that reported Zitadel's error id would leave the operator to work
    that out.
    """
    _run(capsys)
    instance.initialized_users = set(instance.users)

    refusal = _refused(capsys)

    assert "already has credentials" in str(refusal)
    assert "/accounts/login/" in str(refusal)
    assert f"bootstrap_tenant --email {FIRST_ADMIN}" in str(refusal)
    assert refusal.returncode == 1


def test_an_existing_tenant_shuts_the_door_without_dialling_anything(
    instance: FakeZitadel, tenant: Any, capsys: Any
) -> None:
    """The criterion, and the fake's request log is the instrument.

    "It refuses" is provable from the message; "it refuses before touching the
    identity platform" is provable only from the calls it did not make — and
    that half is the one that matters, because an account made and then refused
    is an account nobody knows exists.
    """
    instance.requests.clear()

    refusal = _refused(capsys)

    assert instance.requests == []
    assert "already has a tenant" in str(refusal)
    assert "/api/v1/memberships/invitations/" in str(refusal)
    assert refusal.returncode == 1


def test_an_unconfigured_deployment_is_refused_by_name(
    instance: FakeZitadel, settings: Any, capsys: Any
) -> None:
    """No credential means it will fail identically forever, so it says so first.

    The same sentence `zitadel_seed` gives, deliberately: two commands that
    disagreed about how to fix one missing variable would send an operator two
    ways.
    """
    settings.ZITADEL_PAT = ""

    refusal = _refused(capsys)

    assert "ZITADEL_ISSUER and ZITADEL_PAT must both be set" in str(refusal)
    assert refusal.returncode == 1


def test_a_loopback_base_url_outside_debug_is_refused(
    instance: FakeZitadel, settings: Any, capsys: Any
) -> None:
    """Two of the three printed steps are addresses somebody else has to open.

    A `PUBLIC_BASE_URL` that resolves only on the server would make this command
    print a dead end with confidence, which is worse than printing nothing. On a
    laptop it is right, so the refusal is gated on DEBUG rather than on the host
    alone. The production settings module does not yet refuse this setting
    itself (a standing SHOULD in the ledger since 2026-08-31), so this door
    carries its own guard.
    """
    settings.DEBUG = False
    settings.PUBLIC_BASE_URL = "http://127.0.0.1:8000"

    refusal = _refused(capsys)

    assert "only resolves on this machine" in str(refusal)
    assert refusal.returncode == 1


def test_a_reachable_base_url_outside_debug_is_not_refused(
    instance: FakeZitadel, settings: Any, capsys: Any
) -> None:
    """The negative, so the guard above is not "this command needs DEBUG".

    A production deployment with a real base URL is exactly the case this door
    exists for, and a guard that refused it too would have closed the door it
    was meant to hold open.
    """
    settings.DEBUG = False
    settings.PUBLIC_BASE_URL = "https://console.example-deployment.test"

    out = _run(capsys)

    assert "https://console.example-deployment.test/accounts/login/" in out


def test_something_that_is_not_an_address_is_refused(instance: FakeZitadel, capsys: Any) -> None:
    """A typo becomes a refusal here rather than an unreachable Zitadel account.

    The address is both the username and the inbox the link goes to, so a
    `--email ada` that succeeded would leave an account nobody can ever reach and
    a tenant nobody can ever bootstrap.
    """
    refusal = _refused(capsys, email="ada")

    assert "is not an email address" in str(refusal)
    assert refusal.returncode == 1


@pytest.mark.parametrize("email", ["ada", "ada@localhost", "@yourcompany.test", "ada@ada@x.test"])
def test_the_address_shapes_it_refuses(email: str, instance: FakeZitadel, capsys: Any) -> None:
    """One case per shape rather than one that happens to be caught.

    A single case is satisfied by a check that catches that one and nothing
    else, which is exactly how a loose regex passes review.
    """
    assert "is not an email address" in str(_refused(capsys, email=email))
