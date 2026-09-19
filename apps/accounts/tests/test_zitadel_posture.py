"""This deployment's sign-in posture is applied, reconciled, and declared once.

**Three doors that were open on every environment** (measured live
on 2026-09-07 against the compose stack this repository runs): the instance's
login policy said `allowRegister: true`, its lockout policy carried no
`maxPasswordAttempts` key at all — which is `0`, which is unlimited — and
`GET /admin/v1/restrictions` answered `{"details":{}}`, so
`/ui/login/register/org` served a working organisation-registration form to
anybody who could reach it. All three contradict `architecture.md` §H, where
open signup was rejected and invitations are the way in.

**The intent is the environment, not a row** (ADR ident-8). A deployment's
sign-in posture is set once by an operator editing `.env`; no runtime persona
changes it, so there is no model, no migration, no workflow kind and no REST or
MCP door — the shell door (`manage.py zitadel_seed`, which `scripts/setup.sh`
runs on every setup) is the only one, and rule 17 has no member here. That
makes the properties this module pins exactly the ones an environment-intent
shape owes:

* the seed applies all three and prints one readable line each;
* a second run writes nothing and says `exists` — the same idempotence every
  other line of that command has, and here it is by comparison rather than by
  the API's forgiveness;
* a field we do not manage survives a write **byte-identical** — the five login
  lifetimes, `secondFactors`, `maxOtpAttempts`, `allowedLanguages` — because
  Zitadel's `PUT` is a REPLACE and a partial body is how both known partial
  writers happened;
* `zitadel_audit` counts drift on the three managed fields, counts none when
  they agree, still prints the SMTP sender and this ORG's own login policy
  under `observed`, and still changes nothing;
* and the compose default equals the settings default, read out of both files —
  the one-declared-value law, which is the only thing standing between a fresh
  instance and a seeded one having different postures with nothing saying so.

**And a fourth door, one level down.** The three above are instance-wide, and
an instance-wide login policy governs only the organisations that have not set
one of their own — so on the shared development instance, where a sibling
product had already given this org its own policy, the closed instance policy
governed nothing the hosted registration page read. The seed reconciles the
org's own policy **where it has one** and leaves an inheriting org inheriting
(creating one would fork a value into two owners), and the audit judges the one
field of it the environment states an intent for. Both halves are measured
against the pinned build, including the refusal that makes the branch a branch:
`PUT /management/v1/policies/login` on an org with no policy of its own answers
`404 Org-M0sif`.

Nothing here dials Zitadel: `FakeZitadel` is the socket, carrying the three
instance surfaces in the state a freshly created instance is in (ADR ident-5,
decision (a) — the suite never dials).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings
from django.core.management import call_command, get_commands, load_command_class

from apps.accounts import zitadel
from apps.accounts.tests.conftest import (
    ORG_LOGIN_POLICY_INHERITED,
    ORG_LOGIN_POLICY_OWN,
    FakeZitadel,
)
from apps.core.tests.template_shape import template_shape

pytestmark = pytest.mark.django_db(transaction=True)

REPO = Path(settings.BASE_DIR)


@pytest.fixture
def posture(settings: Any) -> None:
    """A deployment that wants both doors shut and a bounded lockout.

    Set explicitly rather than leant on, because `config/settings/test.py` is
    free to say something else and a test whose set-up is somebody else's
    default is a test that changes meaning without changing.
    """
    settings.ZITADEL_ALLOW_SELF_REGISTRATION = False
    settings.ZITADEL_ALLOW_PUBLIC_ORG_REGISTRATION = False
    settings.ZITADEL_MAX_PASSWORD_ATTEMPTS = 100


@pytest.fixture
def fresh_instance(instance: FakeZitadel) -> FakeZitadel:
    """The three surfaces back in the state a NEWLY CREATED Zitadel is in.

    `apps/accounts/tests/conftest.py`'s `instance` fixture closes them, so that
    every other identity test's audit is about its own subject rather than about
    three disagreements it never set up. This module is the one whose subject IS
    the closing, so it re-opens them — MEASURED off the running v4.17.1 stack on
    2026-09-07: `allowRegister: true`, no `maxPasswordAttempts` key at all
    (proto3 omits zero, and zero is unlimited), and `GET /admin/v1/restrictions`
    answering `{"details":{}}`.

    Without this the seed tests would be vacuous: a command asserted to close a
    door that was already shut proves nothing about the closing.
    """
    instance.instance_login_policy["allowRegister"] = True
    instance.lockout_policy.pop("maxPasswordAttempts", None)
    instance.restrictions.pop("disallowPublicOrgRegistration", None)
    return instance


def _seed(capsys: Any) -> str:
    capsys.readouterr()
    call_command("zitadel_seed", "--skip-user")
    return str(capsys.readouterr().out)


def _posture_writer() -> str:
    """The command THIS deployment declares writes its sign-in posture.

    `DJB_IDENTITY_SHAPE`'s `posture_writer` key; `config/settings/base.py` is
    the authority. The template's own answer is `zitadel_seed`, and the cases
    below that assert `zitadel_seed`'s IDENTITY or its wording carry
    `@template_shape("posture_writer")` and skip on a product that named its
    own. The three that assert IDEMPOTENCE do not skip: "running the posture
    writer twice writes nothing the second time" is every product's property,
    and it is asked of whichever command the product declared.
    """
    return str(settings.IDENTITY_SHAPE["posture_writer"])


def _writer_options(name: str) -> tuple[str, ...]:
    """`--skip-user` when the declared writer takes it, and nothing when it does not.

    The template's `zitadel_seed` does far more than the posture, and
    `--skip-user` is what keeps these cases off its user half. A product's own
    writer owes no such flag, so passing it blindly would red the re-keyed cases
    on an unknown option rather than on the property they are about. Read off
    the command's own parser through `format_help()` — the public surface —
    rather than off a name this module would have to keep a list of.
    """
    parser = load_command_class(get_commands()[name], name).create_parser("manage.py", name)
    return ("--skip-user",) if "--skip-user" in parser.format_help() else ()


def _write_posture(capsys: Any) -> str:
    """Run the DECLARED posture writer, and hand back what it printed.

    The printed lines are the writer's own wording and no case below reads them;
    what the re-keyed cases read is the fake's REQUEST LOG, which is the same
    question asked of any writer.
    """
    capsys.readouterr()
    writer = _posture_writer()
    call_command(writer, *_writer_options(writer))
    return str(capsys.readouterr().out)


def _posture_section() -> tuple[list[str], int]:
    """The audit's posture SECTION, as `(lines, drift)` — I3's one read.

    Read instead of the whole command's exit status: a product's audit carries
    sections this template does not have, so the command's total moves for
    reasons that have nothing to do with the posture. The section's own count is
    the number this case is about.
    """
    from apps.accounts.management.commands.zitadel_audit import posture_section

    section = posture_section()
    return list(section.lines), section.drift


def _audit(capsys: Any, *, expect_exit: int = 0) -> str:
    capsys.readouterr()
    if expect_exit == 0:
        call_command("zitadel_audit")
    else:
        with pytest.raises(SystemExit) as exit_info:
            call_command("zitadel_audit")
        assert exit_info.value.code == expect_exit
    return str(capsys.readouterr().out)


# --- the seed applies all three ----------------------------------------------


@template_shape("posture_writer")
def test_the_seed_closes_all_three_doors(
    fresh_instance: FakeZitadel, posture: None, capsys: Any
) -> None:
    """The criterion, as the state the instance is left in.

    Asserted on the fake's surfaces rather than on the printed lines, because
    the lines are what the command SAYS and these are what it DID.
    """
    _seed(capsys)

    assert fresh_instance.instance_login_policy.get("allowRegister", False) is False
    assert fresh_instance.lockout_policy.get("maxPasswordAttempts") == 100
    assert fresh_instance.restrictions.get("disallowPublicOrgRegistration") is True


@template_shape("posture_writer")
def test_the_seed_prints_one_line_for_each(
    fresh_instance: FakeZitadel, posture: None, capsys: Any
) -> None:
    """Readable output is the operator's only window onto a shell-door change."""
    out = _seed(capsys)

    # Asserted per line on (verb, kind, what it says) rather than as one
    # pre-spaced string: `_say` pads the kind to a column width, and a test that
    # pinned the padding would fail the day somebody adds a longer kind — for a
    # reason that has nothing to do with what this test is about.
    said = {
        line.split(maxsplit=2)[1]: line
        for line in out.splitlines()
        if line.startswith(("created ", "exists  "))
    }
    assert said["login"].startswith("created ") and "self-registration OFF" in said["login"]
    assert said["lockout"].startswith("created ") and "max password attempts 100" in said["lockout"]
    assert (
        said["restrictions"].startswith("created ")
        and "public org registration OFF" in said["restrictions"]
    )


def test_a_second_seed_run_writes_nothing_and_says_exists(
    fresh_instance: FakeZitadel, posture: None, capsys: Any
) -> None:
    """Idempotence, as the property `scripts/setup.sh` depends on every run.

    **Asked of the DECLARED posture writer, on its request log.** The `PUT`
    count is what makes this fail if the writers ever stop comparing: a command
    that reported `exists` while still writing would be green on the printed
    line and wrong on the wire — which is also why the printed line is no longer
    what is read here. `exists` is `zitadel_seed`'s own wording (the template's
    shape, pinned by `test_the_seed_prints_one_line_for_each`, which skips on a
    product that named its own writer); the empty request log is the mechanism,
    and it is the same mechanism whatever the writer is called.
    """
    _write_posture(capsys)
    fresh_instance.bodies.clear()

    _write_posture(capsys)

    posture_puts = [
        path
        for method, path, _ in fresh_instance.bodies
        if method == "PUT" and path.startswith(zitadel.ADMIN)
    ]
    assert posture_puts == [], posture_puts


def test_the_fields_we_do_not_manage_survive_byte_identical(
    fresh_instance: FakeZitadel, posture: None, capsys: Any
) -> None:
    """The full-body property, on the live objects rather than the request body.

    Zitadel's `PUT` is a REPLACE, so this is the assertion that would have
    caught both partial writers before they shipped: turning registration off must
    cost a deployment its `passwordCheckLifetime`, its second factors, its OTP
    lockout or its language restriction.
    """
    fresh_instance.lockout_policy = {**fresh_instance.lockout_policy, "maxOtpAttempts": 7}
    fresh_instance.restrictions = {
        **fresh_instance.restrictions,
        "allowedLanguages": {"list": ["en", "de"]},
    }
    lifetimes_before = {
        key: fresh_instance.instance_login_policy[key]
        for key in (
            "passwordCheckLifetime",
            "externalLoginCheckLifetime",
            "mfaInitSkipLifetime",
            "secondFactorCheckLifetime",
            "multiFactorCheckLifetime",
        )
    }
    factors_before = list(fresh_instance.instance_login_policy["secondFactors"])

    _seed(capsys)

    for key, value in lifetimes_before.items():
        assert fresh_instance.instance_login_policy[key] == value, key
    assert fresh_instance.instance_login_policy["secondFactors"] == factors_before
    assert fresh_instance.instance_login_policy.get("allowUsernamePassword") is True
    assert fresh_instance.lockout_policy["maxOtpAttempts"] == 7
    assert fresh_instance.restrictions["allowedLanguages"] == {"list": ["en", "de"]}


# --- the audit reconciles them -----------------------------------------------


def test_the_audit_agrees_after_a_seed(instance: FakeZitadel, posture: None, capsys: Any) -> None:
    """Three surfaces that used to be printed-and-not-judged now reach a verdict."""
    _seed(capsys)

    out = _audit(capsys, expect_exit=0)

    assert "agrees      posture self-registration — False" in out
    assert "agrees      posture password lockout — 100" in out
    # The ALLOW shape, which is the label's own shape: this deployment is
    # configured for `ZITADEL_ALLOW_PUBLIC_ORG_REGISTRATION=False` and Zitadel
    # agrees, so the line reads `False` like its two siblings. It read `True`
    # until the translation was moved off the printed value, and the sibling
    # case below is the one that pins why.
    assert "agrees      posture public org registration — False" in out
    assert "Zitadel agrees with every row" in out


def test_the_public_org_registration_line_reads_like_its_siblings(
    instance: FakeZitadel, posture: None, capsys: Any
) -> None:
    """Three registration doors, all shut, and all three lines have to say so.

    The label is spelled in the ALLOW direction — `public org registration` —
    and Zitadel's own field is spelled in the DISALLOW direction
    (`disallowPublicOrgRegistration`). The comparison translates between the
    two, as every other name Zitadel uses is translated at this edge. What must
    not happen is the translated value reaching the PRINTED one: a reader who
    sees `self-registration — False` and `org self-registration — False` beside
    `public org registration — True` reads the third as the one door still open,
    when all three mean shut.

    Asserted on the three lines TOGETHER rather than on the one that moved,
    because the property is that they agree with each other — a case naming only
    the third would be satisfied by flipping the other two instead.
    """
    instance.org_login_policy = dict(ORG_LOGIN_POLICY_OWN)
    instance.org_login_policy.pop("allowRegister", None)
    _seed(capsys)

    out = _audit(capsys, expect_exit=0)

    closed = [
        line
        for line in out.splitlines()
        if line.startswith("agrees      posture") and "registration" in line
    ]
    assert len(closed) == 3, closed
    assert all(line.endswith("— False") for line in closed), closed


@pytest.mark.parametrize(
    "field,console_edit",
    [
        ("self-registration", {"instance_login_policy": {"allowRegister": True}}),
        ("password lockout", {"lockout_policy": {"maxPasswordAttempts": 3}}),
        ("public org registration", {"restrictions": {"disallowPublicOrgRegistration": False}}),
    ],
)
def test_the_audit_counts_drift_on_each_managed_field(
    field: str,
    console_edit: dict[str, dict[str, Any]],
    instance: FakeZitadel,
    posture: None,
    capsys: Any,
) -> None:
    """Somebody in the console, one field at a time — the tripwire's whole job.

    One parametrised case per managed field rather than one case that moves all
    three, because a single case is satisfied by an audit that notices any one
    of them and goes blind on the other two.
    """
    _seed(capsys)
    for surface, change in console_edit.items():
        setattr(instance, surface, {**getattr(instance, surface), **change})

    out = _audit(capsys, expect_exit=1)

    assert f"DRIFT       posture {field}" in out
    assert "1 disagreement(s). Nothing was changed." in out


def test_the_audit_still_changes_nothing(instance: FakeZitadel, posture: None, capsys: Any) -> None:
    """The audit's oldest property, extended to the three new reads.

    Both halves: every call the audit makes is a read, and the instance is
    byte-identical afterwards. A mutating call that happened to be idempotent
    would pass the second and fail the first.
    """
    _seed(capsys)
    before = json.dumps(
        {
            "login": instance.instance_login_policy,
            "lockout": instance.lockout_policy,
            "restrictions": instance.restrictions,
        },
        sort_keys=True,
    )
    instance.requests.clear()

    _audit(capsys, expect_exit=0)

    assert all(method == "GET" or path.endswith("_search") for method, path in instance.requests), (
        instance.requests
    )
    for path in (
        f"{zitadel.ADMIN}/policies/login",
        f"{zitadel.ADMIN}/policies/lockout",
        f"{zitadel.ADMIN}/restrictions",
        # The org's own policy, which the posture section now judges one field
        # of. Named here so this assertion cannot go vacuous the way a bare
        # all-calls-are-reads assertion would: that one is satisfied by an audit
        # that stopped making the call at all.
        "/policies/login",
    ):
        assert ("GET", path) in instance.requests, path
    # And the organisation count, which is a POST because `_search` is how
    # Zitadel spells a list read — the one verb exception the read-only property
    # has always carried.
    assert ("POST", f"{zitadel.ADMIN}/orgs/_search") in instance.requests
    assert (
        json.dumps(
            {
                "login": instance.instance_login_policy,
                "lockout": instance.lockout_policy,
                "restrictions": instance.restrictions,
            },
            sort_keys=True,
        )
        == before
    )


def test_the_org_login_policys_other_fields_and_smtp_are_still_only_observed(
    instance: FakeZitadel, posture: None, capsys: Any
) -> None:
    """The observed section did not lose its members to the posture section.

    One FIELD of this org's login policy graduated — `allowRegister`, which the
    environment now states an intent for and the seed now writes. Everything
    else about it still has no intent behind it: its lifetimes, its factors,
    whose policy it is. So does the instance's SMTP sender. All of it stays
    printed and unjudged, and the blind-spot paragraph says which half is which.
    """
    _seed(capsys)

    out = _audit(capsys, expect_exit=0)

    assert "observed    the console's own surfaces" in out
    assert "  login-policy " in out
    assert "  smtp         " in out
    assert "THIS ORG's own login" in out
    assert "Every other field of it is printed in the observed section" in out


# --- the org's own login policy: reconciled where it has one -----------------
#
# One level down from the three above, and a different question: the instance's
# policy governs every org WITHOUT one of its own, so on an org that has one it
# governs nothing the hosted registration page reads. Measured on the shared
# development instance, where the org's own `allowRegister` alone decided
# whether `/ui/login/register` served a working form or an error page.


@pytest.fixture
def org_with_its_own_policy(instance: FakeZitadel) -> FakeZitadel:
    """An org somebody has already given a login policy — with registration ON.

    Both halves matter. `ORG_LOGIN_POLICY_OWN` is the state in which the seed's
    org half writes at all (an inheriting org is left alone), and `allowRegister`
    true is the state in which the write is not a no-op — a seed asserted to
    close a door that was already shut proves nothing about the closing, which
    is the same reason `fresh_instance` above exists.
    """
    instance.org_login_policy = {**ORG_LOGIN_POLICY_OWN, "allowRegister": True}
    return instance


def _management_puts(instance: FakeZitadel) -> list[str]:
    """Every `PUT` that went to the ORG's surface, by path.

    The management prefix is stripped by the fake's transport, so the org's
    login policy is the bare path and the instance's is the one spelled with
    `/admin/v1`. That asymmetry is what lets this tell the two writers apart.
    """
    return [
        path for method, path, _ in instance.bodies if method == "PUT" and path == "/policies/login"
    ]


@template_shape("posture_writer")
def test_the_seed_closes_the_orgs_own_login_policy(
    org_with_its_own_policy: FakeZitadel, posture: None, capsys: Any
) -> None:
    """The fourth door, as the state the org is left in.

    This is the door ACC-1's instance-level write could not reach: an org with a
    policy of its own is governed by that policy, so on this box the hosted
    registration page stayed open behind a closed instance policy until
    somebody's console edit closed it by hand.
    """
    _seed(capsys)

    assert org_with_its_own_policy.org_login_policy.get("allowRegister", False) is False


@template_shape("posture_writer")
def test_the_seed_says_which_org_it_closed(
    org_with_its_own_policy: FakeZitadel, posture: None, capsys: Any
) -> None:
    """The org's name is on the line, because the instance may hold more than one.

    A line reading `login policy  self-registration OFF` twice would leave a
    reader unable to tell the instance's write from the org's — and those are
    the two doors this whole section is about not confusing.
    """
    out = _seed(capsys)

    line = next(line for line in out.splitlines() if "org TestOrg" in line)
    assert line.startswith("created ")
    assert "login policy" in line
    assert "self-registration OFF" in line


def test_a_second_seed_run_writes_nothing_to_the_orgs_policy(
    org_with_its_own_policy: FakeZitadel, posture: None, capsys: Any
) -> None:
    """Idempotence on the org surface too, and by comparison rather than by luck.

    The `PUT` count is the assertion: Zitadel refuses an unchanged login-policy
    body with `Org-5M9vdd` (measured), so a writer that stopped comparing would
    not merely be wasteful — it would fail on the second run, which is every run
    `scripts/setup.sh` makes after the first. Asked of the DECLARED writer, and
    on its request log alone — the `exists  login policy    org TestOrg:` line
    is `zitadel_seed`'s wording and is pinned by the marked cases above.
    """
    _write_posture(capsys)
    org_with_its_own_policy.bodies.clear()

    _write_posture(capsys)

    assert _management_puts(org_with_its_own_policy) == []


def test_the_orgs_unmanaged_fields_survive_the_write_byte_identical(
    org_with_its_own_policy: FakeZitadel, posture: None, capsys: Any
) -> None:
    """The full-body convention on the surface where it would hurt most.

    This instance is shared with another product, and the five lifetimes and the
    factor list on this org's policy are that product's settings. A partial
    `PUT` here — the shape that has already shipped twice in this repository —
    would zero them as a side effect of closing our own door.
    """
    before = {
        key: org_with_its_own_policy.org_login_policy[key]
        for key in (
            "passwordCheckLifetime",
            "externalLoginCheckLifetime",
            "mfaInitSkipLifetime",
            "secondFactorCheckLifetime",
            "multiFactorCheckLifetime",
        )
    }
    factors_before = list(org_with_its_own_policy.org_login_policy["secondFactors"])

    _seed(capsys)

    for key, value in before.items():
        assert org_with_its_own_policy.org_login_policy[key] == value, key
    assert org_with_its_own_policy.org_login_policy["secondFactors"] == factors_before
    assert org_with_its_own_policy.org_login_policy.get("ignoreUnknownUsernames") is True
    assert org_with_its_own_policy.org_login_policy.get("disableLoginWithPhone") is True


def test_an_inheriting_org_is_left_inheriting(
    instance: FakeZitadel, posture: None, capsys: Any
) -> None:
    """The decision, as an absence: no `PUT`, and a line saying why.

    Writing an org policy for an org that has none would fork one value into two
    owners — from that moment the instance write governs every org except this
    one, and a future instance-level change silently would not apply here. The
    fake starts in this state because it is the state every org on a fresh
    instance is in, which makes this the DEFAULT path rather than the exotic one.

    **Asked of the DECLARED writer, and read off its request log.** The
    precondition is asserted rather than assumed — `isDefault` is how Zitadel
    says "this org has no policy of its own" — so the empty log cannot pass for
    the wrong reason on a fake somebody changed. The printed sentence is the
    template writer's wording and is not read here.
    """
    assert instance.org_login_policy.get("isDefault") is True

    _write_posture(capsys)

    assert _management_puts(instance) == []


@template_shape("posture_writer")
def test_the_management_put_is_refused_on_an_inheriting_org(
    instance: FakeZitadel, posture: None
) -> None:
    """Why that branch is a branch and not an optimisation. **Measured.**

    `PUT /management/v1/policies/login` against an org with no policy of its own
    answers `404 Org-M0sif`, "Login Policy not found" — the update endpoint
    refuses outright rather than quietly creating one. So a seed that skipped the
    read and wrote unconditionally would not fork configuration; it would fail
    every run on every fresh clone. Driven against the writer directly, because
    the seed's own branch is what stops this from ever being reached.
    """
    # `False` against an inherited policy whose `allowRegister` is `True`, so the
    # writer's compare-first branch does NOT swallow the call: asking for the
    # value already in force would return early and this test would pass while
    # reaching no `PUT` at all.
    with pytest.raises(zitadel.ZitadelError) as refused:
        zitadel.ensure_login_policy(allow_register=False, prefix=zitadel.MANAGEMENT)

    assert "Org-M0sif" in str(refused.value)


@template_shape("posture_writer")
def test_the_audit_counts_drift_on_the_orgs_own_allow_register(
    org_with_its_own_policy: FakeZitadel, posture: None, capsys: Any
) -> None:
    """Somebody in the console reopening THIS org's door — the blind spot, closed.

    Before this the audit printed the org's policy under `observed` and exited
    0 with registration wide open on it, because the section that judged
    `self-registration` was judging the INSTANCE's value and agreeing with it.
    """
    _seed(capsys)
    org_with_its_own_policy.org_login_policy = {
        **org_with_its_own_policy.org_login_policy,
        "allowRegister": True,
    }

    out = _audit(capsys, expect_exit=1)

    assert "DRIFT       posture org self-registration" in out
    assert "1 disagreement(s). Nothing was changed." in out


def test_the_audit_defers_to_the_instance_verdict_when_the_org_inherits(
    instance: FakeZitadel, posture: None, capsys: Any
) -> None:
    """One value, one verdict: an inheriting org is not judged a second time.

    The instance policy the section already compared IS this org's policy, so
    counting it again would report one console edit as two disagreements — and a
    number a reader acts on has to mean one thing.

    Read off the posture SECTION's own `(lines, drift)` rather than off the
    command's exit and its `N disagreement(s)` total: a product whose audit
    carries sections this template does not have moves that total for reasons
    that are nothing to do with the posture, and the section's count is the one
    this case is about.
    """
    _write_posture(capsys)
    instance.instance_login_policy = {
        **instance.instance_login_policy,
        "allowRegister": True,
    }
    instance.org_login_policy = {**ORG_LOGIN_POLICY_INHERITED, "allowRegister": True}

    lines, drift = _posture_section()
    out = "\n".join(lines)

    assert "inherits    posture org login policy inherits the instance (judged above)" in out
    assert "DRIFT       posture org self-registration" not in out
    assert drift == 1, out


# --- one declared value, across three files ----------------------------------


#: The three compose keys the sign-in posture owns, in the image's own spelling.
#: Named
#: once so the two tests below cannot come to disagree about the population.
POSTURE_COMPOSE_KEYS = (
    "ZITADEL_DEFAULTINSTANCE_LOGINPOLICY_ALLOWREGISTER",
    "ZITADEL_DEFAULTINSTANCE_LOCKOUTPOLICY_MAXPASSWORDATTEMPTS",
    "ZITADEL_DEFAULTINSTANCE_RESTRICTIONS_DISALLOWPUBLICORGREGISTRATION",
)

ENV_EXAMPLES = (".env.example", "deploy/env.staging.example")


def _compose_interpolation(path: Path, key: str) -> tuple[str, str]:
    """The `${VAR:-default}` a compose file gives one key, as (VAR, default)."""
    text = path.read_text(encoding="utf-8")
    match = re.search(rf"^\s*{re.escape(key)}:\s*\$\{{([A-Z_]+):-([^}}]*)\}}\s*$", text, re.M)
    assert match is not None, f"{path.name} has no `${{…:-…}}` value for {key}"
    return match.group(1).strip(), match.group(2).strip()


def _compose_default(path: Path, key: str) -> str:
    """Just the default half of the above, for the value comparisons."""
    return _compose_interpolation(path, key)[1]


@template_shape("template_files")
@pytest.mark.parametrize("compose", ["compose.yaml", "deploy/compose.yaml"])
def test_the_compose_defaults_are_the_settings_defaults(compose: str) -> None:
    """The one-declared-value law, read out of both files rather than remembered.

    A compose default that drifted from `config/settings/base.py` would give a
    freshly created instance a different posture from the one the seed applies
    seconds later — and nothing anywhere would say so, because each half is
    individually correct.

    The third key is compared through its declared POLARITY, not for equality:
    the image spells it `DISALLOW`PublicOrgRegistration while the operator's
    knob is `ZITADEL_ALLOW_PUBLIC_ORG_REGISTRATION`, and compose has no `!` in
    `${…:-…}`. So the assertion is the one that actually protects anybody: the
    belt is never LOOSER than the mechanism.
    """
    path = REPO / compose
    assert path.is_file(), path

    allow_register = _compose_default(path, "ZITADEL_DEFAULTINSTANCE_LOGINPOLICY_ALLOWREGISTER")
    attempts = _compose_default(path, "ZITADEL_DEFAULTINSTANCE_LOCKOUTPOLICY_MAXPASSWORDATTEMPTS")
    disallow_org = _compose_default(
        path, "ZITADEL_DEFAULTINSTANCE_RESTRICTIONS_DISALLOWPUBLICORGREGISTRATION"
    )

    assert allow_register == str(settings.ZITADEL_ALLOW_SELF_REGISTRATION).lower()
    assert attempts == str(settings.ZITADEL_MAX_PASSWORD_ATTEMPTS)
    # Tighter is safe, looser is the bug. `disallow == True` is always at least
    # as tight as whatever the settings default allows.
    assert disallow_org == "true" or (
        disallow_org == "false" and settings.ZITADEL_ALLOW_PUBLIC_ORG_REGISTRATION
    ), (
        f"{compose} would create an instance with public org registration OPEN while "
        f"ZITADEL_ALLOW_PUBLIC_ORG_REGISTRATION is "
        f"{settings.ZITADEL_ALLOW_PUBLIC_ORG_REGISTRATION}"
    )


@template_shape("template_files")
@pytest.mark.parametrize("compose", ["compose.yaml", "deploy/compose.yaml"])
def test_no_posture_compose_key_interpolates_an_undocumented_variable(compose: str) -> None:
    """A compose knob no `.env.example` carries is a knob nobody can turn.

    **The class, not the instance.** A `${VAR:-default}` whose `VAR` appears in
    no env example is a CONSTANT wearing a variable's clothes: it reads as
    configurable in the file that uses it, and the operator who goes looking for
    it in `.env.example` finds nothing and reasonably concludes it does not
    exist. Worse here than in most cases, because the operator would then
    set the variable the examples DO document and get a fresh instance created
    with the opposite of what they asked for.

    So the assertion is over the whole posture population and both files rather
    than over the one key that was wrong: the next key added the same way fails
    here rather than after somebody has trusted it.
    """
    path = REPO / compose
    for key in POSTURE_COMPOSE_KEYS:
        variable, _default = _compose_interpolation(path, key)
        missing = [
            example
            for example in ENV_EXAMPLES
            if not re.search(rf"^{variable}=", (REPO / example).read_text(encoding="utf-8"), re.M)
        ]
        assert not missing, (
            f"{compose}'s {key} interpolates ${{{variable}}}, which {', '.join(missing)} "
            "does not carry. An operator cannot set what no example names, so the "
            "`${…:-…}` is a constant and the file lies about being configurable."
        )


@template_shape("template_files")
@pytest.mark.parametrize("env_file", list(ENV_EXAMPLES))
@pytest.mark.parametrize(
    "key",
    [
        "ZITADEL_ALLOW_SELF_REGISTRATION",
        "ZITADEL_ALLOW_PUBLIC_ORG_REGISTRATION",
        "ZITADEL_MAX_PASSWORD_ATTEMPTS",
        # The compose-only half of the org-registration door. Not a Django
        # setting — nothing in `config/settings` reads it — but it IS a knob the
        # deployment has, so it owes a documented line exactly as the three
        # above do. The test above is the general guard; this is the named row.
        "ZITADEL_DISALLOW_PUBLIC_ORG_REGISTRATION",
    ],
)
def test_every_posture_setting_ships_in_both_env_examples(env_file: str, key: str) -> None:
    """A setting `.env.example` does not carry is a setting nobody knows exists.

    The house rule is already "a new variable lands in `.env.example` with a safe
    local default in the same commit"; this is that, made a failure rather than
    a habit, for the three variables whose absence is a door left open.
    """
    text = (REPO / env_file).read_text(encoding="utf-8")
    assert re.search(rf"^{key}=", text, re.M), f"{env_file} does not carry {key}"
