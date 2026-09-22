"""The measurement kit has to be able to fail.

`manage.py zitadel_measure` is the only thing in this repository that re-asks
the twenty facts `apps/accounts/zitadel.py` took off somebody else's product,
and the suite cannot run it for real (ADR ident-5(a): the tests never dial). So
the one property nobody else can check is the one this module checks: **that a
build which stopped answering what the tree says would be REPORTED, by name,
with the right exit code** — rather than passing, or crashing, or blurring a
disagreement into an unreachable instance.

This is `test_oauth_demo_instrument.py`'s shape, one layer up. That module
drives `check_result` with a planted refusal because an instrument that smiles
at a refusal proves nothing; this one drives the whole command against a socket
that can be made to disagree, because an instrument whose `DIFFERS` branch has
never executed is nineteen lines of decoration.

DOES NOT COVER — declared. Nothing here dials Zitadel, so **no assertion in
this module is evidence about v4.17.1**: the fake's shapes were recorded off
the pinned build on 2026-09-19 and they are a copy, which means a build that
changed would be caught by the hand run and never by this file. What is under
test is the instrument's own reporting, exit grammar and victim discipline. Nor
does it cover the `unmeasured` items beyond the shape of their lines —
their subjects are unbuilt by construction.
"""

from __future__ import annotations

import io
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts import zitadel
from apps.accounts.management.commands import zitadel_measure
from apps.accounts.tests.conftest import FakeMeasuredZitadel

pytestmark = pytest.mark.django_db


def run(**options: Any) -> tuple[int, str]:
    """The command, its exit code, and everything it printed.

    A clean run raises nothing and is reported as 0 here, so every case below
    reads as `code, printed = run()` rather than half of them being a
    `pytest.raises` and half not — which is what makes "this case is about the
    exit code" visible at the call site.
    """
    out = io.StringIO()
    try:
        call_command("zitadel_measure", stdout=out, stderr=out, **options)
    except SystemExit as exited:
        return int(exited.code or 0), out.getvalue()
    return 0, out.getvalue()


def verdict_lines(printed: str) -> list[str]:
    """Every line that carries one of the four verdict words, in print order."""
    return [
        line
        for line in printed.splitlines()
        if any(line.startswith(word) for word in zitadel_measure.VERDICTS)
    ]


def line_for(printed: str, item_id: str) -> str:
    for line in verdict_lines(printed):
        if f" {item_id} — " in line:
            return line
    raise AssertionError(f"no line for {item_id!r} in:\n{printed}")


# --- I5.1: the population is closed, and printed whole -----------------------


def test_the_report_is_twenty_lines_and_every_one_carries_a_closed_verdict(
    measured_instance: FakeMeasuredZitadel,
) -> None:
    """The criterion, asserted as arithmetic rather than as a count in prose.

    Twenty is not a magic number typed here: it is `len(ITEMS)`, so a rung
    that adds a twenty-first fact moves both sides together — and a rung that
    DROPS one moves neither, which is the failure this is really for. What is
    pinned as a literal is the population itself, below.
    """
    code, printed = run()

    assert code == 0, printed
    lines = verdict_lines(printed)
    assert len(lines) == len(zitadel_measure.ITEMS) == 20, printed
    for line, item in zip(lines, zitadel_measure.ITEMS, strict=True):
        assert f" {item.id} — " in line, line
        first = line.split()[0]
        assert first in zitadel_measure.VERDICTS, line


def test_the_population_is_the_eight_constants_and_the_designs_twelve() -> None:
    """The closed set, spelled out once so a silent deletion is a red.

    `ITEMS` is the only place the population lives, and a list that can be
    edited is a list that can be edited down: dropping the item that started
    failing is the cheapest way to make an instrument green, and it leaves no
    trace anywhere else. So the ids are written out here, in print order.
    """
    assert [item.id for item in zitadel_measure.ITEMS] == [
        "C1 put-field-sets",
        "C2 invite-code-expiry",
        "C3 is-default",
        "C4 org-m0sif",
        "C5 instance-5m9vdd",
        "C6 proto3-zero-omission",
        "C7 invite-path",
        "C8 v2-users-human-empty",
        "M1 authorize-redirect-per-login-version",
        "M2 finalize-needs-login-client",
        "M3 token-carries-client-id",
        "M4 finalize-refusal-enum",
        "M5 session-user-check-is-not-a-password",
        "M6 password-reset-mail-landing",
        "M7 zitadel-cookie-after-v2-round-trip",
        "M8 session-patch-rotates-the-token",
        "M9 webauthn-no-passkey-is-a-500",
        "M10 invite-ignores-org-default-redirect",
        "M11 org-password-complexity",
        "M12 subject-is-session-user-id",
    ]


def test_every_item_is_either_measured_today_or_promised_to_a_named_rung(
    measured_instance: FakeMeasuredZitadel,
) -> None:
    """No item may be silently absent from both halves.

    `PROMISED` is the promise and `measure()` is the delivery, and they are
    deliberately separate structures — which is exactly the pair that can drift
    apart. An item in neither would raise a `KeyError` in the printer on a real
    run; here it is a named failure before anybody runs one.
    """
    _, printed = run()
    for item in zitadel_measure.ITEMS:
        line = line_for(printed, item.id)
        promised = zitadel_measure.PROMISED.get(item.id)
        if promised is None:
            assert not line.startswith(zitadel_measure.UNMEASURED), (
                f"{item.id} is measured today, so it must not print unmeasured: {line}"
            )
        else:
            assert line.startswith(f"{zitadel_measure.UNMEASURED} — {promised}"), line


# --- I5.2: it can fail -------------------------------------------------------


def test_a_planted_field_set_difference_is_reported_by_name(
    measured_instance: FakeMeasuredZitadel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The defect this item exists for, planted: a writer's declaration drifts.

    `usePkce` is the field this actually happened to — it was missing from
    `OIDC_IDENTITY_PROVIDER_FIELDS`, so every sync sent `usePkce=false` by
    omission and switched off a PKCE somebody had enabled in the console
    (`zitadel.py`, the OIDC provider declaration). Removing it again is the
    plant: the swagger the fake built at construction still serves eight
    properties, the declaration now has seven, and the instrument must say
    which field and which resource — a `DIFFERS` that only said "the field sets
    disagree" would send a reader back to diff seventy names by hand.
    """
    planted = dict(zitadel.PUT_FIELD_SETS)
    planted["/idps/generic_oidc/{id}"] = frozenset(
        zitadel.OIDC_IDENTITY_PROVIDER_FIELDS - {"usePkce"}
    )
    monkeypatch.setattr(zitadel, "PUT_FIELD_SETS", planted)

    code, printed = run()

    line = line_for(printed, "C1 put-field-sets")
    assert line.startswith(zitadel_measure.DIFFERS), line
    assert "usePkce" in line, line
    assert "/idps/generic_oidc/{id}" in line, line
    assert "ManagementServiceUpdateGenericOIDCProviderBody" in line, line
    assert code == 1, printed


def test_a_planted_field_set_difference_is_the_only_line_that_moves(
    measured_instance: FakeMeasuredZitadel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One disagreement is one line. Eighteen others still say what they said.

    The control for the case above, and it is not ceremony: an instrument whose
    items share state can turn one planted difference into a page of them, and
    a page of `DIFFERS` is a report nobody reads to the end.
    """

    def verdicts(printed: str) -> list[str]:
        # The VERDICT word per line, never the whole line: two runs build two
        # throwaway organisations with two ids, and those ids ride in C3's and
        # C4's detail. Diffing whole lines would call that a move.
        return [line.split()[0] for line in verdict_lines(printed)]

    before = verdicts(run()[1])
    planted = dict(zitadel.PUT_FIELD_SETS)
    planted["/restrictions"] = frozenset(zitadel.RESTRICTIONS_FIELDS | {"inventedField"})
    monkeypatch.setattr(zitadel, "PUT_FIELD_SETS", planted)

    code, printed = run()
    after = verdicts(printed)

    assert code == 1, printed
    moved = [
        item.id
        for item, one, two in zip(zitadel_measure.ITEMS, before, after, strict=True)
        if one != two
    ]
    assert moved == ["C1 put-field-sets"], moved
    assert "inventedField" in line_for(printed, "C1 put-field-sets")


def test_an_unreachable_instance_is_exit_two(
    measured_instance: FakeMeasuredZitadel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Could-not-look outranks everything, and asserts nothing.

    The distinction the whole instruments census is about: an instance that
    would not answer tells you nothing about whether the tree is right, and an
    exit code that could not tell that apart from a disagreement would let a
    dead socket read as a clean bill on one run and as a defect on the next.
    """

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise zitadel.ZitadelError("Zitadel GET /orgs failed: [Errno 61] Connection refused")

    monkeypatch.setattr(zitadel, "probe", refuse)
    monkeypatch.setattr(zitadel, "create_organization", refuse)
    monkeypatch.setattr(zitadel, "swagger_document", refuse)

    code, printed = run()

    assert code == 2, printed
    lines = verdict_lines(printed)
    assert len(lines) == 20, printed
    blind = [line for line in lines if line.startswith(zitadel_measure.COULD_NOT)]
    assert len(blind) == 20, printed
    assert all("Connection refused" in line for line in blind), blind
    assert "Nothing is asserted about the 20" in printed, printed
    # And not one of them is dressed as a disagreement. Asserted over the
    # verdict LINES rather than over the whole output, because the tally itself
    # always names the word ("0 DIFFERS") — a substring test over `printed`
    # would be a test that cannot fail.
    assert [line for line in lines if line.startswith(zitadel_measure.DIFFERS)] == []


def test_an_unconfigured_deployment_is_exit_two_before_anything_is_dialled(
    settings: Any,
) -> None:
    """No credential is could-not-look too, and it is refused before the socket."""
    settings.ZITADEL_ISSUER = ""
    settings.ZITADEL_PAT = ""

    with pytest.raises(CommandError) as refused:
        call_command("zitadel_measure", stdout=io.StringIO())

    assert refused.value.returncode == 2
    assert "could-not-look rather than agreement" in str(refused.value)


def test_it_creates_and_removes_its_own_org_and_touches_no_other(
    measured_instance: FakeMeasuredZitadel,
) -> None:
    """The victim rule, as arithmetic over the call log.

    Three separate claims, because the honest version of "it cleans up after
    itself" is all three: it made exactly ONE organisation, it removed exactly
    that one, and every write it aimed at an org surface named that org and no
    other. The third is the one a teardown assertion alone would miss — an
    instrument that measured against the credential's own org and then tidied
    its throwaway would pass the first two.

    **Named `removes` rather than `deactivates`, and the rung's criteria say
    deactivates.** `POST /admin/v1/orgs/{id}/_deactivate` answers a bare `404
    Not Found` on v4.17.1 — the admin API routes a deactivate for `orgs/me`
    only — so deletion is the teardown that exists. Measured 2026-09-19 and
    recorded in `zitadel.remove_organization`.
    """
    code, printed = run()

    assert code == 0, printed
    assert len(measured_instance.created_orgs) == 1, measured_instance.created_orgs
    mine = measured_instance.created_orgs[0]
    assert measured_instance.removed_orgs == [mine]

    # Every org-scoped write named the org it made. The parent fake's own org
    # ("1") and the instance surfaces are what a leak would show up as.
    strangers = [
        (method, path)
        for method, path, _org, _body in measured_instance.whole_calls
        if method in ("POST", "PUT", "PATCH", "DELETE") and "/orgs/" in path and mine not in path
    ]
    assert strangers == [], strangers

    # And the name says what it is, so a leaked one is identifiable on sight.
    created = [one for one in measured_instance.orgs if one["id"] == mine]
    assert created == [] or created[0]["name"].startswith(zitadel_measure.MEASURE_ORG_PREFIX)
    assert zitadel_measure.MEASURE_ORG_PREFIX in printed
    assert "deleting it is safe" in printed


def test_the_only_write_outside_its_own_org_is_the_no_op_the_refusal_is_measured_by(
    measured_instance: FakeMeasuredZitadel,
) -> None:
    """Two exceptions outside the victim, and both of them are declared.

    Stated as a closed list rather than as "it changes no intent", because
    "changes no intent" is the claim and this is the evidence. The list has
    grown by THREE calls since M1 became a check, and they are one act: M1
    makes a throwaway OIDC client under this deployment's own project,
    declares a login version on it, measures the redirect twice and
    DEACTIVATES it. A throwaway is not the real Web application — measuring
    two live declaration changes on the object everybody signs in through is
    the one breakage that locks a deployment out of its own front door — and
    the deactivation in the `finally` is why an interrupted run leaves a
    closed door rather than an open one.
    """
    code, printed = run()
    assert code == 0, printed

    mine = measured_instance.created_orgs[0]

    def names_my_org(path: str, org: str, body: dict[str, Any]) -> bool:
        # Three spellings, because Zitadel has three: the path
        # (`/admin/v1/orgs/{id}`), the header (every management call, and
        # `POST /v2/sessions`) and the body (`POST /v2/users/human`). A call
        # naming this run's org any of those ways is inside the victim, and so
        # is one aimed at a `/v2/users/<id>` or `/v2/sessions/<id>` this run
        # made inside it.
        return (
            mine in path
            or org == mine
            or mine in str((body.get("organization") or {}).get("orgId", ""))
            or path.startswith("/v2/sessions/")
            # `/v2/users/<id>/...` reaches a person this run made; the
            # collection path `/v2/users/human` is a CREATE and is not
            # excused here — C8's empty one has to show up in the list below.
            or (path.startswith("/v2/users/") and path != "/v2/users/human")
        )

    outside = [
        (method, path)
        for method, path, org, body in measured_instance.whole_calls
        if method in ("POST", "PUT", "PATCH", "DELETE")
        and not path.endswith("_search")
        and not names_my_org(path, org, body)
    ]

    # The ids are replaced by `{id}` so the list is a claim about WHICH
    # resources are written rather than about which ids one run happened to
    # mint — the same normalisation `zitadel.put_field_set` does, and for the
    # same reason.
    def shape(path: str) -> str:
        # `V2_<digits>` as well as bare digits since A8: an auth request id
        # carries the platform's own `V2_` prefix, and a list that kept those
        # would be a claim about which ids one run minted.
        return "/".join(
            "{id}" if part.isdigit() or part.removeprefix("V2_").isdigit() else part
            for part in path.split("/")
        )

    # The closed list, and each member says why it is on it: the create that
    # makes the victim, C5's no-op PUT (the one declared instance write), C8's
    # empty create — a 400 that writes nothing, asserted below rather than
    # assumed — M1's throwaway client, declared and then deactivated, and
    # since A8 a SECOND throwaway client for M3 and M4.
    #
    # **Eight calls for that second one, and it is one act.** M3, M4 and M7
    # are one journey on one client: make it, declare login v2 on it, finalize
    # one auth request (and spend the code the finalize answered, which is the
    # only token exchange in the run), refuse two more — one per spelling —
    # finalize a third for M7's cookie question, and deactivate. It is a
    # second client rather than M1's because M1's is deactivated inside its
    # own `finally`, and a deactivated client cannot start a login; sharing
    # one would make the items' order load-bearing.
    #
    # M6 adds nothing here: its reset is a write on the throwaway HUMAN, which
    # `names_my_org` excuses as inside the victim, and its landing is a GET.
    #
    # **And five more for M12, which is a THIRD throwaway client and one act.**
    # It cannot borrow either of the two above — both are
    # deactivated inside their own `finally`, and a deactivated client cannot
    # start a login — so it makes its own, declares login v2 on it, finalizes
    # ONE auth request against the ONE session both halves of M12 are read
    # off, spends that code for an id_token, and deactivates. Its session is
    # not on this list because it is opened with the throwaway org's header,
    # which `names_my_org` reads as inside the victim.
    assert [(method, shape(path)) for method, path in outside] == [
        ("POST", "/management/v1/orgs"),
        ("PUT", "/admin/v1/policies/login"),
        ("POST", "/v2/users/human"),
        ("POST", "/management/v1/projects/{id}/apps/oidc"),
        ("PUT", "/management/v1/projects/{id}/apps/{id}/oidc_config"),
        ("POST", "/management/v1/projects/{id}/apps/{id}/_deactivate"),
        ("POST", "/management/v1/projects/{id}/apps/oidc"),
        ("PUT", "/management/v1/projects/{id}/apps/{id}/oidc_config"),
        ("POST", "/v2/oidc/auth_requests/{id}"),
        ("POST", "/oauth/v2/token"),
        ("POST", "/v2/oidc/auth_requests/{id}"),
        ("POST", "/v2/oidc/auth_requests/{id}"),
        ("POST", "/v2/oidc/auth_requests/{id}"),
        ("POST", "/management/v1/projects/{id}/apps/{id}/_deactivate"),
        ("POST", "/management/v1/projects/{id}/apps/oidc"),
        ("PUT", "/management/v1/projects/{id}/apps/{id}/oidc_config"),
        ("POST", "/v2/oidc/auth_requests/{id}"),
        ("POST", "/oauth/v2/token"),
        ("POST", "/management/v1/projects/{id}/apps/{id}/_deactivate"),
    ], outside
    empty_creates = [
        body
        for method, path, _org, body in measured_instance.whole_calls
        if (method, path) == ("POST", "/v2/users/human") and not body
    ]
    assert empty_creates == [{}], empty_creates
    assert line_for(printed, "C5 instance-5m9vdd").startswith(zitadel_measure.OK)


def test_an_unmeasured_item_names_its_rung(
    measured_instance: FakeMeasuredZitadel,
) -> None:
    """One line per unbuilt ingredient, each naming the rung that lands it.

    The rung has to be in the VERDICT, not in the trailing prose: the builder of
    A8 greps `unmeasured — A8` to find what their rung owes, and a grep for
    `A8` alone matches every line that merely mentions it.
    """
    code, printed = run()

    assert code == 0, printed
    unmeasured = [
        line for line in verdict_lines(printed) if line.startswith(zitadel_measure.UNMEASURED)
    ]
    # **EMPTY since A11, and the test is kept rather than deleted.** Every
    # design item has an ingredient now, so the report is all verdicts — and
    # what this case guards from here is the shape of the NEXT promise: a
    # design item booked into `PROMISED` must name its rung in the verdict,
    # not in the trailing prose, because that is the string its builder greps
    # for. A deleted test would let the next one arrive unshaped.
    assert unmeasured == [], printed
    assert zitadel_measure.PROMISED == {}, zitadel_measure.PROMISED
    assert "0 unmeasured" in printed
    for line in verdict_lines(printed):
        assert not line.startswith(zitadel_measure.UNMEASURED), line


def test_an_unmeasured_item_is_not_an_agreement(
    measured_instance: FakeMeasuredZitadel,
) -> None:
    """The tally separates them, and the blind spots say how many were looked at.

    A twenty-line report whose verdict line said "20 ok" would be the exact
    dishonesty the `unmeasured` word exists to prevent — the remainder are
    facts nobody has looked at.
    """
    _, printed = run()
    assert "20 item(s): 20 ok, 0 DIFFERS, 0 could not, 0 unmeasured." in printed
    # The sentence wraps inside the blind-spot block, so what is asserted is
    # the half that carries the claim rather than a reflowed line. It no
    # longer spells a NUMBER: a count in prose goes stale the rung after an
    # `unmeasured` item becomes a check, which is exactly what happened to
    # "thirteen" when M1 and M2 landed.
    assert "are NOT judged and NOT covered" in printed
    assert "count in the verdict line is what says how many that was" in printed


# --- I5.3: the version block -------------------------------------------------


def test_the_version_block_prints_the_compose_pin_and_this_builds_own_info(
    measured_instance: FakeMeasuredZitadel,
) -> None:
    """Two independent statements about which build this is. Neither is asserted.

    The criterion is explicit that no equality is claimed here, and that is the
    honest shape: the running instance publishes no version on any surface this
    instrument can reach, so an equality would be between the pin and itself.
    What the block buys is that a reader of a `DIFFERS` six weeks from now can
    see which build the disagreement belongs to.
    """
    _, printed = run()

    assert "compose pin   ghcr.io/zitadel/zitadel:v4.17.1" in printed
    assert "management    Management API v1.0 (Apache License 2.0)" in printed
    assert "admin         Administration API aka Admin v1.0" in printed


def test_the_compose_pin_is_read_by_regex_and_says_so_when_it_cannot(tmp_path: Any) -> None:
    """A tree with no `compose.yaml` reports that, rather than a plausible tag.

    The pin is deliberately not a constant in the command — a constant would be
    a second copy of the pin, agreeing with `compose.yaml` on the day it was
    written. Which makes "the file is not there" a state that exists, and a
    version block that quietly printed nothing would be the worst of the three
    outcomes.
    """
    assert zitadel_measure.compose_pin().startswith("ghcr.io/zitadel/zitadel:")
    missing = zitadel_measure.compose_pin(root=tmp_path)
    assert missing.startswith("could not read"), missing
    (tmp_path / "compose.yaml").write_text("services:\n  db:\n    image: postgres:17\n")
    assert zitadel_measure.compose_pin(root=tmp_path).startswith("no zitadel image line")


# --- I5.5: the exit codes ----------------------------------------------------


def test_a_differs_is_exit_one_and_a_could_not_outranks_it(
    measured_instance: FakeMeasuredZitadel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2 beats 1 beats 0, and the tally names both counts.

    The ordering is the house semantics and it is the property an automated
    caller depends on: a run carrying one disagreement AND one unreadable
    surface must report the unreadable one, because the disagreement might be
    an artefact of the half that would not answer.
    """
    planted = dict(zitadel.PUT_FIELD_SETS)
    planted["/restrictions"] = frozenset({"onlyThis"})
    monkeypatch.setattr(zitadel, "PUT_FIELD_SETS", planted)

    code, printed = run()
    assert code == 1, printed
    assert "1 DIFFERS, 0 could not" in printed

    real = zitadel.probe

    def half_blind(method: str, path: str, *args: Any, **kwargs: Any) -> Any:
        if path.startswith("/secretgenerators"):
            raise zitadel.ZitadelError("Zitadel POST /secretgenerators/_search failed: timeout")
        return real(method, path, *args, **kwargs)

    monkeypatch.setattr(zitadel, "probe", half_blind)

    code, printed = run()
    assert code == 2, printed
    assert "1 DIFFERS, 1 could not" in printed
    assert line_for(printed, "C2 invite-code-expiry").startswith(zitadel_measure.COULD_NOT)


def test_the_blind_spots_print_beside_the_verdict(
    measured_instance: FakeMeasuredZitadel,
) -> None:
    """Declared where the person reading a green report is already looking.

    `zitadel_audit.blind_spot_lines`' rule, applied here for the same reason: a
    blind spot that lives only in a module docstring is a blind spot the
    operator does not have.
    """
    _, printed = run()
    assert "does not cover" in printed
    # A9 moved this line when it moved the measurement: the walk now drives
    # two of M9's three halves, and the blind spot that remains is the one
    # no walk of any kind can close — a relying-party id this server accepts
    # and every browser refuses.
    assert "M9's THIRD half" in printed
    assert "accepted by this server and refused by every browser" in printed
    assert printed.index("does not cover") > printed.index("C1 put-field-sets")


# --- the individual measurements, each planted the other way -----------------


def test_a_build_that_stopped_refusing_the_no_op_put_is_a_differs(
    measured_instance: FakeMeasuredZitadel,
) -> None:
    """C5's defect: the writers' idempotence stops being enforced by the API.

    Planted by moving the instance policy out from under the comparison, so the
    body the command sends is no longer the live one and the fake accepts it —
    which is exactly what a build that dropped `INSTANCE-5M9vdd` would look
    like from here.
    """
    measured_instance.instance_login_policy["allowRegister"] = True
    original = measured_instance._measured

    def accept_the_no_op(method: str, path: str, body: Any, request: Any) -> Any:
        if method == "PUT" and path == "/admin/v1/policies/login":
            return None  # the parent's route, which updates and answers 200
        return original(method, path, body, request)

    measured_instance._measured = accept_the_no_op  # type: ignore[method-assign]

    code, printed = run()

    line = line_for(printed, "C5 instance-5m9vdd")
    assert line.startswith(zitadel_measure.DIFFERS), line
    assert "ACCEPTS a no-op PUT" in line, line
    assert code == 1, printed


def test_a_session_that_arrives_carrying_a_password_factor_is_a_differs(
    measured_instance: FakeMeasuredZitadel,
) -> None:
    """M5's defect, and it is the fail-closed rule's whole premise.

    If a session created with a USER check alone already carried
    `factors.password`, a seam reading `factors.password.verifiedAt` would sign
    in somebody who typed nothing. That is the one this line is for.
    """
    real = measured_instance._open_session

    def pre_verified(body: Any) -> Any:
        answer = real(body)
        if answer.status_code == 201:
            session = measured_instance.sessions[answer.json()["sessionId"]]
            session["factors"]["password"] = {"verifiedAt": "2026-09-19T03:13:47Z"}
        return answer

    measured_instance._open_session = pre_verified  # type: ignore[method-assign]

    code, printed = run()

    line = line_for(printed, "M5 session-user-check-is-not-a-password")
    assert line.startswith(zitadel_measure.DIFFERS), line
    assert "would now pass a person who typed nothing" in line, line
    assert code == 1, printed


def test_an_invite_page_that_404s_is_a_differs_naming_invite_url(
    measured_instance: FakeMeasuredZitadel,
) -> None:
    """C7's defect: every invited person is sent to a page that is not there."""
    original = measured_instance._measured

    def gone(method: str, path: str, body: Any, request: Any) -> Any:
        if path == zitadel.INVITE_PATH:
            import httpx

            return httpx.Response(404, json={"message": "NotFound"})
        return original(method, path, body, request)

    measured_instance._measured = gone  # type: ignore[method-assign]

    code, printed = run()

    line = line_for(printed, "C7 invite-path")
    assert line.startswith(zitadel_measure.DIFFERS), line
    assert "zitadel.invite_url" in line, line
    # **And the run is exit 2, not 1** — the same 404 takes M10's landing read
    # with it, and a surface that would not answer outranks a disagreement.
    # Asserted rather than worked around: an instrument reporting 1 here would
    # be claiming it had looked at M10.
    assert line_for(printed, "M10 invite-ignores-org-default-redirect").startswith(
        zitadel_measure.COULD_NOT
    )
    assert code == 2, printed


def test_a_webauthn_challenge_that_succeeds_for_a_person_with_no_passkey_is_a_differs(
    measured_instance: FakeMeasuredZitadel,
) -> None:
    """M9's defect: "a 500 means no passkey" stops being how to read it.

    A build that started issuing the challenge would make the seam's
    500-is-normal branch swallow a real outage, which is the direction that
    costs a person their sign-in rather than an operator a puzzled minute.
    """
    real = measured_instance._open_session

    def always_open(body: Any) -> Any:
        return real({"checks": body.get("checks")})

    measured_instance._open_session = always_open  # type: ignore[method-assign]

    code, printed = run()

    line = line_for(printed, "M9 webauthn-no-passkey-is-a-500")
    assert line.startswith(zitadel_measure.DIFFERS), line
    assert "no longer how to read it" in line, line
    assert code == 1, printed


def test_the_two_doors_naming_one_person_differently_is_a_differs(
    measured_instance: FakeMeasuredZitadel,
) -> None:
    """**M12's defect, and it is the one the identity join cannot survive.**

    A build whose id_token `sub` stopped being the session's own
    `factors.user.id` would leave `record_zitadel_identity` holding two
    strings for one person: whoever used the hosted page first would meet
    *That identity is already linked to a different account* at this
    deployment's own form, and every test in the suite would stay green —
    both fakes would go on agreeing with each other. This is the line that
    would not.
    """
    real = measured_instance._measured_token

    def a_stranger() -> Any:
        answer = real()
        body = dict(answer.json())
        import json as _json
        from base64 import urlsafe_b64decode, urlsafe_b64encode

        head, payload, signature = str(body["id_token"]).split(".")
        claims = _json.loads(urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        claims["sub"] = "a-subject-this-session-never-had"
        moved = urlsafe_b64encode(_json.dumps(claims).encode()).decode().rstrip("=")
        body["id_token"] = f"{head}.{moved}.{signature}"
        import httpx

        return httpx.Response(200, json=body)

    measured_instance._measured_token = a_stranger  # type: ignore[method-assign]

    code, printed = run()

    line = line_for(printed, "M12 subject-is-session-user-id")
    assert line.startswith(zitadel_measure.DIFFERS), line
    assert "a-subject-this-session-never-had" in line, line
    assert "no longer name one person with one string" in line, line
    assert code == 1, printed


def test_a_round_trip_that_mints_no_id_token_is_could_not_and_never_an_ok(
    measured_instance: FakeMeasuredZitadel,
) -> None:
    """M12's honesty half: no token, nothing asserted — and it outranks a pass.

    The verdict a journey that did not reach a token owes is `could not`, not
    `ok` and not `DIFFERS`: an instrument that read "no token" as agreement
    would report the join as measured on every deployment whose credential
    cannot finalize an auth request at all (M2's 403).
    """
    real = measured_instance._measured_token

    def tokenless() -> Any:
        answer = real()
        body = {key: value for key, value in dict(answer.json()).items() if key != "id_token"}
        import httpx

        return httpx.Response(200, json=body)

    measured_instance._measured_token = tokenless  # type: ignore[method-assign]

    code, printed = run()

    line = line_for(printed, "M12 subject-is-session-user-id")
    assert line.startswith(zitadel_measure.COULD_NOT), line
    assert "no `id_token`" in line, line
    assert code == 2, printed


def test_m12_reads_one_session_through_both_doors_and_deactivates_its_client(
    measured_instance: FakeMeasuredZitadel,
) -> None:
    """The victim rule and the ONE-session rule, both asserted on the calls.

    One session rather than two is the whole property: two sessions would
    measure two people who happen to share an id. And the throwaway OIDC
    client M12 makes is deactivated before the run returns — `blind_spots()`
    says one is left behind per run, deactivated, and this is what makes that
    sentence true rather than hopeful.
    """
    code, printed = run()

    assert code == 0, printed
    line = line_for(printed, "M12 subject-is-session-user-id")
    assert line.startswith(zitadel_measure.OK), line
    assert "ONE identity fact" in line, line

    made = [
        body["name"]
        for method, path, _org, body in measured_instance.whole_calls
        if method == "POST" and path.endswith("/apps/oidc")
    ]
    mine = [name for name in made if name.startswith(zitadel_measure.SUBJECT_CHECK_PREFIX)]
    assert len(mine) == 1, made
    deactivated = [
        path
        for method, path, _org, _body in measured_instance.whole_calls
        if method == "POST" and path.endswith("/_deactivate")
    ]
    # One per throwaway client: M1's, mode A's, and M12's.
    assert len(deactivated) == 3, deactivated
    # ONE session, read twice. The last finalize of the run is M12's, it named
    # a session this run opened, and the `factors.user.id` on THAT session is
    # the string the line reports on both sides — which is what "one session,
    # both doors" means and what two sessions could not show.
    last = measured_instance.finalized_sessions[-1]
    session = measured_instance.sessions[last]
    ours = str((dict(session.get("factors") or {}).get("user") or {}).get("id", ""))
    assert ours, session
    assert f"factors.user.id={ours!r}" in line, line
    assert f"sub={ours!r}" in line, line


def test_a_teardown_that_fails_names_what_is_left_on_the_instance(
    measured_instance: FakeMeasuredZitadel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one state the victim rule cannot prevent, reported rather than hidden.

    A process that cannot delete its own organisation has left something on
    somebody's instance, and the only honest thing left to do is say the name.
    The measurements themselves still stand — the teardown is not one of them —
    so the exit code is unchanged and the sentence rides beside the tally.
    """
    monkeypatch.setattr(zitadel, "remove_organization", lambda **kwargs: False)

    code, printed = run()

    assert code == 0, printed
    assert "COULD NOT REMOVE organisation" in printed
    assert "LEFT ON THE INSTANCE: organisation" in printed
    assert zitadel_measure.MEASURE_ORG_PREFIX in printed


# --- the door it is built on -------------------------------------------------


def test_probe_reports_a_refusal_and_raises_on_an_unreachable_instance(
    measured_instance: FakeMeasuredZitadel,
) -> None:
    """The two states `_call` collapses into one, kept apart.

    `zitadel._call` raises on every non-2xx, which is right for a writer and
    useless for an instrument: three of the nineteen items ARE a non-2xx. So
    `probe` returns the status — and still raises for the one thing that is not
    an answer.
    """
    refused = zitadel.probe("POST", "/users/human", {}, prefix=zitadel.USER)
    assert refused.status == 400
    assert not refused.ok
    assert "AddHumanUserRequest" in refused.text

    identified = zitadel.probe("GET", "/sessions/nosuch", prefix=zitadel.USER)
    assert identified.status == 404
    assert identified.error_id == "QUERY-SFeaa"


def test_probe_raises_when_the_deployment_has_no_credential(settings: Any) -> None:
    """Before a socket is opened, and as the class a retry cannot fix."""
    settings.ZITADEL_ISSUER = ""
    settings.ZITADEL_PAT = ""
    with pytest.raises(zitadel.ZitadelNotConfigured):
        zitadel.probe("GET", "/orgs/me")


def test_create_organization_is_not_an_ensure_and_makes_a_second_one(
    measured_instance: FakeMeasuredZitadel,
) -> None:
    """The one writer here that must NOT be idempotent, and why.

    Every `ensure_*` above it is idempotent because it materialises an intent a
    row holds. This one holds no intent: a second call that FOUND the first
    run's organisation would hand the next measurement an org somebody had
    already written a policy onto, and C3 and C4 both need one that has never
    been configured.
    """
    first = zitadel.create_organization(name="pilecap-measure-throwaway-a")
    second = zitadel.create_organization(name="pilecap-measure-throwaway-a")
    assert first.id != second.id
    assert first.created and second.created

    assert zitadel.remove_organization(org_id=first.id) is True
    assert zitadel.remove_organization(org_id="") is False
    # An org this run did not create is refused by the fake, and the helper
    # reports that rather than raising inside somebody's `finally`.
    assert zitadel.remove_organization(org_id="999999") is False
