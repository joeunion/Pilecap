"""`zitadel_audit` sees the console's own surfaces, judges neither, and says so.

Two classes of Zitadel configuration have no row behind them at all: the org's
**login policy** and the instance's **SMTP sender**. Nothing in this product
writes either, which is exactly why house rule 27's declared blind spot — the
console, which no check can see — covered them completely. The audit walked
every `SsoConnection` and then the workforce door, and a shared instance whose
login policy somebody had rewritten and whose mail somebody else's product now
sends still produced "Zitadel agrees with every row. Nothing changed."

**So they are OBSERVED, not judged.** A drift verdict needs an intent to
disagree with, and inventing one means building rule 27's whole materialisation
machinery to guard a surface nothing writes (ADR ident-2's amendment records the
decision and names the trigger: the first product managing login policy or SMTP
through services). The properties that fall out of that decision are what this
module pins, and each is a property rather than a mechanism:

* the two surfaces are **printed** — a person reading the report can see them;
* they **never reach a verdict** — no `DRIFT`, and the exit status is what it
  would have been without them;
* the audit still **changes nothing** — both new calls are GETs, so the
  mutate-then-assert-byte-identical discipline the rest of the audit is held to
  extends unchanged;
* an unreadable surface says **could not be read**, which is a different fact
  from "nothing there" and must not be mistaken for one;
* and the **does-not-cover paragraph prints beside the verdict**, under both
  verdicts, because the person reading a clean report is the person who most
  needs to know what "clean" covers — and a blind spot declared only in a module
  docstring is a blind spot the operator does not have.

Nothing here dials Zitadel. `FakeZitadel` is the socket, as everywhere else in
`test_zitadel.py` and `test_zitadel_workforce_audit.py`; the two surfaces it
does not know about are routed in **this module** rather than added to the
shared fake, because these two surfaces are this module's subject and a shared
fixture object is every identity test's.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from django.core.management import call_command

from apps.accounts.tests.conftest import FakeZitadel

pytestmark = pytest.mark.django_db(transaction=True)

# The shapes MEASURED off the pinned build by a live probe, kept whole
# rather than trimmed to the fields the report happens to read today: a fake
# that carried only what the reader wants cannot catch a reader that started
# wanting something else.
ORG_OWN_POLICY: dict[str, Any] = {
    "details": {"sequence": "25", "resourceOwner": "387613333072707590"},
    "allowUsernamePassword": True,
    "allowExternalIdp": True,
    "passwordlessType": "PASSWORDLESS_TYPE_ALLOWED",
    "ignoreUnknownUsernames": True,
    "secondFactors": ["SECOND_FACTOR_TYPE_OTP", "SECOND_FACTOR_TYPE_U2F"],
    "allowDomainDiscovery": True,
    "disableLoginWithPhone": True,
}

# What Zitadel answers when the org has NO policy of its own: the same endpoint,
# the instance default, and `isDefault` present. That flag is the whole news, so
# the fake serves both states and the report is tested against each.
INHERITED_POLICY: dict[str, Any] = {
    "details": {"sequence": "19", "resourceOwner": "387613333072642054"},
    "allowUsernamePassword": True,
    "allowRegister": True,
    "allowExternalIdp": True,
    "passwordlessType": "PASSWORDLESS_TYPE_ALLOWED",
    "isDefault": True,
    "allowDomainDiscovery": True,
}

# The instance's SMTP config, as the pinned build answers it. Note what is NOT
# in it and cannot be: Zitadel does not return the SMTP password, which is what
# makes printing this line safe at all.
SOMEBODY_ELSES_SMTP: dict[str, Any] = {
    "details": {"sequence": "110", "resourceOwner": "387613333072642054"},
    "senderAddress": "no-reply@example-crm.localhost",
    "senderName": "ExampleCRM",
    "host": "mailpit:1025",
    "state": "SMTP_CONFIG_ACTIVE",
    "description": "Set by ExampleCRM (accounts.login_policy)",
    "id": "388471039450939395",
}


class Console:
    """The two surfaces nobody's row claims, and whether they answer at all.

    A tiny holder rather than two loose dicts so a test can say what it is
    setting up in one line, and so "this surface is unreadable" is a state the
    fake can be put in — which is the only way the could-not-look sentence is
    provable rather than asserted about a code path nobody ran.
    """

    def __init__(self) -> None:
        self.policy: dict[str, Any] = dict(ORG_OWN_POLICY)
        self.smtp: dict[str, Any] = dict(SOMEBODY_ELSES_SMTP)
        self.policy_readable = True
        self.smtp_readable = True

    def frozen(self) -> str:
        """Both surfaces as one string, for the byte-identity assertion."""
        return json.dumps({"policy": self.policy, "smtp": self.smtp}, sort_keys=True)


@pytest.fixture
def console(instance: FakeZitadel, monkeypatch: pytest.MonkeyPatch) -> Console:
    """`FakeZitadel` plus the two console-owned surfaces, routed here.

    The routes are layered onto the instance rather than added to `FakeZitadel`
    itself for a territory reason and a design one. The territory reason: the
    shared fake is every identity test's fixture and these two routes belong to
    one module. The design one: these two surfaces are the *subject* of this module
    and of nothing else, so the module that asserts about them is the honest
    place for the shapes they answer with.

    Everything else — the settings, the PAT, the mocked transport, the closed
    Temporal seam — comes from `instance` unchanged, so a call outside the two
    paths below behaves exactly as it does in every other identity test.
    """
    surfaces = Console()
    original: Callable[[str, str, dict[str, Any]], dict[str, Any]] = instance._route

    def routed(method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if method == "GET" and path == "/policies/login":
            if not surfaces.policy_readable:
                raise KeyError(path)
            return {"policy": surfaces.policy}
        if method == "GET" and path == "/admin/v1/smtp":
            if not surfaces.smtp_readable:
                raise KeyError(path)
            return {"smtpConfig": surfaces.smtp}
        return original(method, path, body)

    monkeypatch.setattr(instance, "_route", routed)
    return surfaces


@pytest.fixture
def workforce_drift(settings: Any) -> None:
    """A deployment whose staff cannot sign in — the audit's cheapest real drift.

    Used only to get a **non-zero verdict** out of the command, so the
    paragraph and the observed section can be proven to behave the same under
    both verdicts. The workforce door is somebody else's subject
    (`test_zitadel_workforce_audit.py`); here it is a lever.
    """
    settings.GOOGLE_OAUTH_CLIENT_ID = "google-client-id"
    settings.GOOGLE_WORKSPACE_DOMAINS = ["union.studio"]


def _run(capsys: Any, *, expect_exit: int = 0) -> str:
    """Run the audit, assert the exit status, return what it printed."""
    capsys.readouterr()
    if expect_exit == 0:
        call_command("zitadel_audit")
    else:
        with pytest.raises(SystemExit) as exit_info:
            call_command("zitadel_audit")
        assert exit_info.value.code == expect_exit
    return str(capsys.readouterr().out)


def _observed_lines(out: str) -> list[str]:
    """The observed section's own lines — everything the reader sees under it."""
    lines = out.splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith("observed"))
    end = next(
        (
            index
            for index, line in enumerate(lines)
            if index > start and line.startswith("does not")
        ),
        len(lines),
    )
    return lines[start:end]


# --- the surfaces are printed ------------------------------------------------


def test_an_org_policy_somebody_set_is_reported_as_the_orgs_own(
    console: Console, capsys: Any
) -> None:
    """The news is *whose* policy is answering, so it is the first thing said.

    On the live shared instance this was accepted against, the org policy
    had been rewritten by another product on the same instance and the audit
    said nothing at all.
    """
    out = _run(capsys)

    line = next(line for line in _observed_lines(out) if "login-policy" in line)
    assert "set on this org (not the instance default)" in line
    assert "387613333072707590" in line
    assert "external idp" in line
    assert "SECOND_FACTOR_TYPE_OTP" in line


def test_an_inherited_policy_is_reported_as_the_instance_default(
    console: Console, capsys: Any
) -> None:
    """The other state, so the line above is not "any policy reads as changed".

    `isDefault` is the only field that tells the two apart, and Zitadel sends it
    by omission — which is the shape most likely to be read wrong once.
    """
    console.policy = dict(INHERITED_POLICY)

    out = _run(capsys)

    line = next(line for line in _observed_lines(out) if "login-policy" in line)
    assert "the instance default (no policy of this org's own)" in line
    assert "not the instance default" not in line
    assert "self-registration" in line


def test_the_instance_smtp_sender_is_reported(console: Console, capsys: Any) -> None:
    """Who this instance's mail comes from — instance-wide, so possibly not us."""
    out = _run(capsys)

    line = next(line for line in _observed_lines(out) if "smtp" in line)
    assert "ExampleCRM" in line
    assert "no-reply@example-crm.localhost" in line
    assert "mailpit:1025" in line
    assert "SMTP_CONFIG_ACTIVE" in line


# --- and judged by nothing ---------------------------------------------------


def test_the_observed_section_reaches_no_verdict(console: Console, capsys: Any) -> None:
    """A rewritten org policy and somebody else's mail sender: still exit 0.

    This is the criterion, stated as the property a reader depends on. An
    operator who has automated on `zitadel_audit` exiting 0 gets new lines and
    the same exit — the report grew, the contract did not.
    """
    out = _run(capsys, expect_exit=0)

    assert "DRIFT" not in "\n".join(_observed_lines(out))
    assert "Zitadel agrees with every row" in out


def test_the_observed_section_does_not_change_a_drift_count(
    console: Console, workforce_drift: None, capsys: Any
) -> None:
    """The other half of the same property: it adds nothing to a count either.

    One disagreement with the two surfaces present is one disagreement, not
    three. Asserted on the printed count rather than on the exit status, because
    the exit status cannot tell 1 from 3.
    """
    out = _run(capsys, expect_exit=1)

    assert "1 disagreement(s). Nothing was changed." in out
    assert "DRIFT" not in "\n".join(_observed_lines(out))


def test_an_unreadable_surface_says_so_and_still_exits_zero(console: Console, capsys: Any) -> None:
    """Could-not-look and nothing-there are different facts, and it says which.

    A missing line would read as "there is no SMTP configuration", which is the
    reassuring answer and the wrong one. And an unreadable surface nothing
    manages must not become the first thing that fails a deploy step.
    """
    console.policy_readable = False
    console.smtp_readable = False

    out = _run(capsys, expect_exit=0)

    observed = "\n".join(_observed_lines(out))
    assert "login-policy could not be read" in observed
    assert "smtp         could not be read" in observed
    assert "Zitadel agrees with every row" in out


# --- and it still changes nothing --------------------------------------------


def test_reading_the_console_surfaces_changes_nothing(
    console: Console, instance: FakeZitadel, capsys: Any
) -> None:
    """The audit's oldest property, extended to the two new surfaces.

    Byte-identity over the two new surfaces **and** over the rest of the
    instance, because a read that mutated something else would otherwise pass a
    test whose subject is the reads that were added.
    """
    before = console.frozen()
    instance_before = json.dumps(
        {"idps": instance.idps, "projects": instance.projects, "users": instance.users},
        sort_keys=True,
    )

    _run(capsys)

    assert console.frozen() == before
    assert (
        json.dumps(
            {"idps": instance.idps, "projects": instance.projects, "users": instance.users},
            sort_keys=True,
        )
        == instance_before
    )


def test_every_console_call_is_a_get(console: Console, instance: FakeZitadel, capsys: Any) -> None:
    """The change-nothing property as a property of the CALLS, not the result.

    A mutating call that happened to be idempotent would pass the byte-identity
    assertion above and fail here, which is the point of having both.
    """
    instance.requests.clear()

    _run(capsys)

    assert all(method == "GET" or path.endswith("_search") for method, path in instance.requests), (
        instance.requests
    )
    assert ("GET", "/policies/login") in instance.requests
    assert ("GET", "/admin/v1/smtp") in instance.requests


# --- the paragraph, beside the verdict ---------------------------------------


def test_the_blind_spot_paragraph_prints_under_a_clean_verdict(
    console: Console, capsys: Any
) -> None:
    """The whole point: it is the reader of a GREEN report who needs it.

    Before this test the paragraph existed only in the command module's
    docstring, where the operator reading the output never meets it.
    """
    out = _run(capsys, expect_exit=0)

    assert "does not cover" in out
    assert "House rule 27 fences this codebase. It cannot fence the console." in out
    assert "point-in-time" in out


def test_the_blind_spot_paragraph_prints_under_a_drift_verdict(
    console: Console, workforce_drift: None, capsys: Any
) -> None:
    """Both verdicts, because a caveat that vanishes on failure is not a caveat."""
    out = _run(capsys, expect_exit=1)

    assert "does not cover" in out
    assert "House rule 27 fences this codebase. It cannot fence the console." in out


def test_the_paragraph_is_beside_the_verdict_and_not_at_the_top(
    console: Console, capsys: Any
) -> None:
    """*Beside* is the criterion, and it is a claim about position.

    A paragraph printed before the report begins is scrolled past; one printed
    immediately above the verdict line is read by the person about to act on
    that line. Asserted as ordering rather than as presence, because presence is
    what a paragraph at the top would also satisfy.
    """
    out = _run(capsys, expect_exit=0)
    lines = out.splitlines()

    paragraph = next(index for index, line in enumerate(lines) if line.startswith("does not cover"))
    verdict = next(index for index, line in enumerate(lines) if "Zitadel agrees" in line)
    first_row = next(index for index, line in enumerate(lines) if line.startswith("instance "))

    assert first_row < paragraph < verdict
    # And nothing but blank lines between the paragraph and the verdict it
    # qualifies — "beside" is not "somewhere further up".
    assert all(not line.strip() for line in lines[paragraph + 11 : verdict])
