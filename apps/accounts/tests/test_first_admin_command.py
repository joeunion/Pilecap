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

from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from apps.accounts import zitadel
from apps.accounts.tests.conftest import FakeZitadel
from apps.core.models import Tenant

pytestmark = pytest.mark.django_db(transaction=True)

FIRST_ADMIN = "ada.lovelace@yourcompany.test"


def _minted(instance: FakeZitadel) -> tuple[str, list[str]]:
    """The one person the command made, and every code minted for them, in order.

    Read off the fake rather than parsed back out of the printed text. The URL's
    ORIGIN is Zitadel's, and how it is spelled is a fact about Zitadel's front
    end that `zitadel.invite_url` owns — a regexp here would be a second,
    quieter copy of it, and under A5 the template's own URL changes.
    """
    assert len(instance.users) == 1, instance.users
    user_id = next(iter(instance.users))
    return user_id, list(instance.invite_codes[user_id])


def _link(instance: FakeZitadel, *, code: str) -> str:
    """The link the command is expected to have printed, built by its own builder."""
    user_id, _codes = _minted(instance)
    return zitadel.invite_url(user_id=user_id, code=code)


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

    The expected link is BUILT by `zitadel.invite_url` from the id and the code
    the fake minted, and counted in the output. The URL's origin and shape are
    Zitadel's own and that function is the tree's one place that knows them, so
    a product whose issuer, or whose base URL under A5, is different asks this
    same question and gets its own answer.
    """
    out = _run(capsys)

    user_id, codes = _minted(instance)
    assert codes == [codes[0]], codes
    link = zitadel.invite_url(user_id=user_id, code=codes[0])
    assert out.count(link) == 1, out


def test_the_code_is_in_no_log_record(
    instance: FakeZitadel, capsys: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """`create_invite_code`'s contract, held at the door that prints the code.

    The client's own log line names the user id and nothing more; this asserts
    the command added no line that undoes that. A credential in a log line is a
    credential in every sink the deployment forwards to.

    The code comes from the fake, not from a URL parsed back out of stdout — the
    property is "this string is in no record", and it must hold whatever shape
    the link the code travels in happens to have.
    """
    with caplog.at_level(0):
        _run(capsys)

    _user_id, codes = _minted(instance)
    code = codes[0]
    # A census over every RECORD, and over everything a record carries: the
    # rendered message, the raw format string, the arguments, and every value a
    # structured processor hung on the record. `caplog.text` is only the
    # rendered half, so a code that reached a sink as an extra field rather than
    # as a formatted one would not have been seen.
    for record in caplog.records:
        haystack = [record.getMessage(), str(record.msg), str(record.args)]
        haystack += [str(value) for value in record.__dict__.values()]
        assert code not in "\n".join(haystack), record
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
    # `reverse`, not the shipped path: where sign-in lives is the URLconf's
    # answer, and a product that mounted allauth somewhere else still owes the
    # step that tells the first person where to go.
    assert reverse("account_login") in steps[1] and FIRST_ADMIN in steps[1]
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
    # One person, two codes: the account was found, not made again.
    _user_id, codes = _minted(instance)
    assert len(codes) == 2, codes
    assert codes[0] != codes[1]
    # And each run printed the link for the code THAT run minted, built by
    # `zitadel.invite_url` rather than matched against a pinned URL shape.
    assert _link(instance, code=codes[0]) in first
    assert _link(instance, code=codes[1]) in second
    assert _link(instance, code=codes[0]) not in second


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


# --- which front end day zero lands on (A5.3, A5.5) ---------------------------
# The link this command prints is the first screen of the product for the first
# person in the deployment, and under `SIGN_IN_DOOR` there are two of them. ADR
# ident-9 said "prints the hosted set-password link" when there was one; design
# Decision 3 amends that to "the deployment's sign-in door's link", and these
# two cases are the amendment as a pair rather than as a sentence — the default
# unchanged, and the other door landing on our own host.


def test_hosted_first_admin_prints_the_hosted_link(instance: FakeZitadel, capsys: Any) -> None:
    """The DEFAULT, unchanged: step one is the identity platform's own page.

    No `override_settings` and no environment: `hosted` is what a clone gets
    and what every other case in this module already ran under, so this is the
    one that would notice a door that had quietly become `ours` for everybody.
    """
    out = _run(capsys)

    user_id, codes = _minted(instance)
    assert out.count(zitadel.invite_url(user_id=user_id, code=codes[0])) == 1
    assert zitadel.INVITE_PATH in out
    steps = [line for line in out.splitlines() if line.strip().startswith("1.")]
    assert "the identity platform's, not this product's" in steps[0], steps


def test_ours_first_admin_prints_our_page(
    instance: FakeZitadel, settings: Any, capsys: Any
) -> None:
    """Under `ours`, both the link and the sentence are about OUR front end.

    Two halves, because either one alone is a day-zero walk that goes wrong in
    a way nobody can see from here: a link to our page under a sentence saying
    the page is somebody else's sends the first human looking for a screen that
    is not there, and the reverse hands them a Zitadel URL they were told is
    ours. The address is `reverse`d rather than spelled, so a product that
    mounted the door elsewhere gets its own answer.
    """
    settings.SIGN_IN_DOOR = "ours"

    out = _run(capsys)

    user_id, codes = _minted(instance)
    link = zitadel.invite_url(user_id=user_id, code=codes[0])
    assert out.count(link) == 1, out
    assert link.startswith(f"{settings.PUBLIC_BASE_URL}{reverse('account_login')}?")
    assert f"userID={user_id}" in link and f"code={codes[0]}" in link
    assert zitadel.INVITE_PATH not in out

    steps = [line for line in out.splitlines() if line.strip().startswith("1.")]
    assert "this product's own" in steps[0], steps


# --- A7 · the walk the steps describe is the walk the door does ---------------


def test_ours_the_walk_is_two_steps_because_the_road_signs_them_in(
    instance: FakeZitadel, settings: Any, capsys: Any
) -> None:
    """A7.4 · under `ours`, "now go and sign in" would be an instruction to
    do something the previous step already did.

    The invite road sets the password and completes the sign-in on the same
    page-load (design C-11), so the walk after the link is: land on the
    product, then `bootstrap_tenant`. A third step telling the first human to
    go to a sign-in page they are already past is the day-zero runbook being
    wrong on the day it matters, and it is exactly the kind of wrongness
    nobody catches from a terminal that printed it confidently.
    """
    settings.SIGN_IN_DOOR = "ours"

    out = _run(capsys)

    steps = [line for line in out.splitlines() if line.strip().startswith(("1.", "2.", "3."))]
    assert len(steps) == 2, out
    assert "set a password" in steps[0]
    assert "bootstrap_tenant" in steps[1] and FIRST_ADMIN in steps[1]
    assert "Sign in at" not in out
    assert "signs them in here" in out


def test_hosted_the_walk_is_still_three_steps_and_names_the_sign_in(
    instance: FakeZitadel, capsys: Any
) -> None:
    """A7.5 · the default, unmoved — and the negative for the case above.

    Under `hosted` the sign-in IS a separate act: the hosted page ends the
    invite on Zitadel's own console (WATCH F6, `302 Location: /ui/console/`),
    so the person genuinely has to come here afterwards. A rung that made the
    walk two steps for everybody would have deleted the only instruction that
    gets them out of that console.
    """
    out = _run(capsys)

    steps = [line for line in out.splitlines() if line.strip().startswith(("1.", "2.", "3."))]
    assert len(steps) == 3, out
    assert reverse("account_login") in steps[1] and FIRST_ADMIN in steps[1]
    assert "signs them in here" not in out
