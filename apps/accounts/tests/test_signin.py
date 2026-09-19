# census: cross-app population=apps/**/*.py,config/**/*.py A3.9's door census
"""The sign-in seam, driven through every road it has (design C-8, C-14).

Nine properties, one per acceptance criterion, and each of them is a property
about a REFUSAL rather than about the happy road: a sign-in seam that lets the
wrong person in is green on every test that signs the right person in.

`apps/accounts/signin.py`'s own docstring numbers the four fail-closed rules;
the tests below name them in their own docstrings so a red one says which rule
stopped holding.
"""

from __future__ import annotations

import ast
import json
import logging
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings as django_settings
from django.core.cache import cache

from apps.accounts import signin, zitadel
from apps.accounts.management.commands import zitadel_audit
from apps.accounts.signin import FactorKind, SignIn, SignInOutcome, Step
from apps.accounts.tests.conftest import (
    SIGNIN_FACTOR_CODE,
    SIGNIN_LOGIN_NAME,
    SIGNIN_PASSWORD,
    SIGNIN_USER_ID,
    FakeModeAZitadel,
    FakeSignInZitadel,
)
from apps.core.tests.tree_census import source_text, source_tree

BASE_DIR = Path(__file__).resolve().parents[3]

# The wrong passwords, named once. **Constants rather than literals at the call
# sites**, because `detect-secrets` keys on the KEYWORD — a `password="…"`
# argument is a finding wherever it appears — and a pragma on a call that
# `ruff format` may wrap onto three lines is a pragma that stops covering the
# line it was written for. One declaration, one allowlist comment, and the
# scanner has nothing to find in the twelve places these are used.
WRONG_PASSWORD = "wrong"  # pragma: allowlist secret
ANOTHER_WRONG_PASSWORD = "not-the-password"  # pragma: allowlist secret
A_THIRD_WRONG_PASSWORD = "the-wrong-one"  # pragma: allowlist secret

#: Every entry point, so a census can drive the whole surface rather than the
#: three roads somebody remembered. The tuple is `(name, callable, kwargs)`.
ENTRY_POINTS: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("begin", "begin", {"address": SIGNIN_LOGIN_NAME, "password": SIGNIN_PASSWORD}),
    ("challenge", "challenge", {"kind": FactorKind.TOTP.value}),
    ("answer", "answer", {"code": SIGNIN_FACTOR_CODE}),
    ("enrol", "enrol", {}),
    ("confirm_enrolment", "confirm_enrolment", {"code": SIGNIN_FACTOR_CODE}),
    ("skip_enrolment", "skip_enrolment", {}),
    ("cancel", "cancel", {}),
)


def structured(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    """Every structured line captured, parsed back from what left the process.

    `test_rp_login.py`'s idiom, for the reason it gives there: this reads the
    rendering a person actually queries rather than swapping the processor
    chain out under the code being measured.
    """
    return [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.getMessage().startswith("{")
    ]


def sign_in(fake: FakeSignInZitadel, store: dict[str, Any]) -> SignIn:
    """The password leg, as every test that needs a live ceremony starts.

    The throttle bucket is emptied first, and that is deliberate rather than
    convenient: a test that walks six roads is six tries at one address, so
    the limiter would refuse the sixth road for the right reason and the
    wrong test. The two tests whose SUBJECT is the limiter call `signin.begin`
    directly, so this helper cannot hide their red.
    """
    cache.clear()
    return signin.begin(store, address=fake.login_name, password=fake.password)


# --- A3.1 · the closed vocabulary -------------------------------------------


def test_every_outcome_is_a_member_of_the_closed_set(
    mode_a_instance: FakeModeAZitadel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every answer is a `SignInOutcome`, and every member is REACHED.

    Two halves, and the second is the one that matters. Completeness alone —
    "nothing returns a string outside the set" — is satisfied by a seam that
    only ever answers `REFUSED`. So the drive below walks the whole surface
    and asserts the set of outcomes it PRODUCED is the whole enum: a member
    nobody can reach is a sentence the page will never render, and a member
    the page cannot render is a person stuck on a screen.
    """
    # The RICHEST fake rather than A3's, and the subclassing is the reason
    # this test can stay ONE assertion: three of the members below are the
    # invite road's and one is Mode A's, and a census that reached them from
    # three fixtures would be three populations wearing one name. Everything
    # A3 drove is inherited unchanged; what is added is the two surfaces.
    fake = mode_a_instance
    seen: set[SignInOutcome] = set()

    def record(found: SignIn) -> SignIn:
        assert isinstance(found.outcome, SignInOutcome), found
        assert isinstance(found.step, Step), found
        assert found.outcome in set(SignInOutcome), found
        assert found.step in set(Step), found
        seen.add(found.outcome)
        return found

    # Every entry point on an EMPTY store: the `ceremony_gone` road, plus the
    # one entry point that does not need a ceremony.
    for _, name, kwargs in ENTRY_POINTS:
        record(getattr(signin, name)({}, **kwargs))

    # DONE, straight through: a password and nothing enrolled.
    store: dict[str, Any] = {}
    record(sign_in(fake, store))

    # CONTINUE at the factor step, then CANCELLED out of it.
    fake.auth_methods.append("AUTHENTICATION_METHOD_TYPE_TOTP")
    store = {}
    record(sign_in(fake, store))
    record(signin.cancel(store))

    # REFUSED — the password is wrong.
    cache.clear()
    record(
        signin.begin(
            {},
            address=fake.login_name,
            password=ANOTHER_WRONG_PASSWORD,
        )
    )

    # UNAVAILABLE — Zitadel refuses OUR credential.
    cache.clear()
    fake.refusals = [(403, "AUTH-AWfge")]
    record(signin.begin({}, address=fake.login_name, password=fake.password))

    # KIND_UNANSWERABLE — a kind outside the closed set.
    store = {}
    record(sign_in(fake, store))
    record(signin.challenge(store, kind="carrier-pigeon"))

    # CEREMONY_GONE — the session vanished under an open tab.
    store = {}
    record(sign_in(fake, store))
    fake.sessions.clear()
    record(signin.answer(store, code=fake.factor_code))

    # THROTTLED — our own limit, last because it spends the bucket.
    cache.clear()
    for _ in range(10):
        found = signin.begin({}, address=fake.login_name, password=fake.password)
        record(found)

    # The invite road's three (A7). Last, and in this order, because each one
    # changes the world the next is driven in: a spent code, then a refused
    # password, then a person who has one.
    cache.clear()
    record(
        signin.set_invited_password(
            {}, user_id=fake.invited_id, code="ZZZZZZ", password=fake.password
        )
    )
    record(
        signin.set_invited_password(
            {}, user_id=fake.invited_id, code=fake.invited_code, password="short"
        )
    )
    fake.invited_methods = ["AUTHENTICATION_METHOD_TYPE_PASSWORD"]
    seen.add(signin.invitation(user_id=fake.invited_id).outcome)

    # Mode A's one (A8): an auth request that is not there.
    seen.add(signin.auth_request(request_id="V2_000000000000000000").outcome)

    # The reset road's one (A11b). Last, and with the floor patched off:
    # this census drives the whole surface and a real 250 ms pause per call
    # would make one test the slowest in the module for a property it is not
    # about — `test_both_roads_leave_on_the_same_floor` is the one that is.
    monkeypatch.setattr("apps.accounts.signin.RESET_FLOOR_SECONDS", 0.0)
    cache.clear()
    record(signin.request_reset({}, address=fake.login_name))

    assert seen == set(SignInOutcome), (
        f"outcomes never produced by any drive: {sorted(set(SignInOutcome) - seen)}"
    )


# --- A3.2 · fail-closed, four times, and no row -----------------------------


def test_a_2xx_with_no_verified_password_is_refused(
    signin_instance: FakeSignInZitadel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**Fail-closed rule 1.** M5: a 201 is not "the password was right".

    The world this builds is the exact one `zitadel_measure`'s M5 measured on
    the pinned build — a session that exists, a `factors.user` on it, and no
    `factors.password` at all — and the seam must answer REFUSED. A seam that
    read the status would answer DONE here and sign in anybody whose address
    exists.
    """
    fake = signin_instance
    real_open = zitadel.open_session

    def open_without_checking_the_password(**kwargs: Any) -> zitadel.Probe:
        checks = dict(kwargs.pop("checks"))
        checks.pop("password", None)
        return real_open(checks=checks, **kwargs)

    monkeypatch.setattr(zitadel, "open_session", open_without_checking_the_password)

    store: dict[str, Any] = {}
    found = sign_in(fake, store)

    assert found.outcome is SignInOutcome.REFUSED
    assert found.reason == "password_not_verified"
    assert found.subject == ""
    # And the session that 201'd is not left behind.
    assert fake.opened_sessions == fake.closed_sessions != []


@pytest.mark.parametrize("status", [401, 403, 429])
def test_a_refusal_aimed_at_our_credential_is_unavailable_never_refused(
    signin_instance: FakeSignInZitadel, status: int
) -> None:
    """**Fail-closed rule 3.** An expired PAT is not everybody forgetting at once.

    401/403/429 is Zitadel judging OUR machine credential, not the person's
    password. Answered as REFUSED it would tell every person in the
    deployment that their password is wrong on the same morning — and the
    operator would be looking at a support queue instead of at a PAT.
    """
    fake = signin_instance
    fake.refusals = [(status, "AUTH-AWfge")]

    found = signin.begin({}, address=fake.login_name, password=fake.password)

    assert found.outcome is SignInOutcome.UNAVAILABLE
    assert found.reason == "identity_platform_refused_us"


def test_an_answer_the_seam_cannot_read_is_unavailable_never_done(
    signin_instance: FakeSignInZitadel,
) -> None:
    """**Fail-closed rule 2.** A 5xx and a dead socket are outages, not verdicts.

    Both halves, because they arrive by different roads: a 5xx comes back as
    a `Probe`, and a transport failure comes back as a `ZitadelError` that
    never became one. Neither may be `DONE` and neither may be `REFUSED`.
    """
    fake = signin_instance

    fake.refusals = [(503, "")]
    found = signin.begin({}, address=fake.login_name, password=fake.password)
    assert found.outcome is SignInOutcome.UNAVAILABLE
    assert found.reason == "identity_platform_refused_us"

    fake.transport_fails = True
    found = signin.begin({}, address=fake.login_name, password=fake.password)
    assert found.outcome is SignInOutcome.UNAVAILABLE
    assert found.reason == "identity_platform_unreachable"


def test_a_factor_kind_the_seam_cannot_answer_is_never_a_pass(
    signin_instance: FakeSignInZitadel,
) -> None:
    """**Fail-closed rule 4.** Two shapes: an unknown name, and M9's WebAuthn 500.

    The second is the one worth writing down. MEASURED: this build answers
    `500 WEBAU-4G8sw` for a WebAuthn challenge begun for a person with no
    registered credential. Read as an outage it is a retry loop for somebody
    who simply has no passkey; read as a pass it is a sign-in with no factor.
    It is neither — it is a dead end with a sentence (K10: there is nothing
    to hand off TO under login v2).
    """
    fake = signin_instance
    fake.auth_methods.append("AUTHENTICATION_METHOD_TYPE_TOTP")

    store: dict[str, Any] = {}
    sign_in(fake, store)
    found = signin.challenge(store, kind="carrier-pigeon")
    assert found.outcome is SignInOutcome.KIND_UNANSWERABLE
    assert found.step is Step.NOTHING

    store = {}
    sign_in(fake, store)
    # **A kind the ceremony never offered is refused before Zitadel is asked**
    # (A6): `deliverable` drops `passkey` from the chips, so a form that sent
    # one is a typed action or a stale tab and is a dead end on that alone.
    found = signin.challenge(store, kind=FactorKind.PASSKEY.value)
    assert found.outcome is SignInOutcome.KIND_UNANSWERABLE
    assert found.reason == FactorKind.PASSKEY.value

    # **M9's own 500 is still driven**, on the road that will reach it when
    # design J6 builds the browser ceremony: a ceremony that IS offering the
    # kind, so the challenge is really sent and the build's refusal is really
    # read. Planted through the seam's own writer rather than by editing the
    # store, because the ceremony's key set is closed and this is how the
    # module itself writes it.
    store = {}
    sign_in(fake, store)
    signin._remember(store, kinds=[FactorKind.PASSKEY.value])
    found = signin.challenge(store, kind=FactorKind.PASSKEY.value)
    assert found.outcome is SignInOutcome.KIND_UNANSWERABLE
    # This world's person owns no passkey, so the reason says exactly that.
    assert found.reason == signin.PASSKEY_NONE
    assert fake.opened_sessions == fake.closed_sessions

    # An enrolled kind Zitadel names and this seam does not know is DROPPED
    # from the chips rather than forwarded — a form nobody wrote an answer
    # path for is worse than the sentence.
    fake.auth_methods = [
        "AUTHENTICATION_METHOD_TYPE_PASSWORD",
        "AUTHENTICATION_METHOD_TYPE_SOMETHING_NEW",
    ]
    store = {}
    found = sign_in(fake, store)
    assert FactorKind.TOTP not in found.kinds
    assert all(kind in set(FactorKind) for kind in found.kinds)


def test_the_password_itself_is_not_a_second_step(
    signin_instance: FakeSignInZitadel,
) -> None:
    """The one a hand walk caught, and the suite could not have.

    MEASURED against the pinned build on 2026-09-18:
    `GET /v2/users/{id}/authentication_methods` for a person with a password
    and nothing else answers
    `authMethodTypes: ['AUTHENTICATION_METHOD_TYPE_PASSWORD']` — **never an
    empty list**. A seam that read "the list is non-empty" as "a second factor
    is enrolled" would therefore send EVERY person on this build to a *One
    more step* form with no chip on it, and every test written against a fake
    that answered `[]` would be green while it did.
    """
    fake = signin_instance
    assert fake.auth_methods == [signin.ZITADEL_PASSWORD_METHOD]

    store: dict[str, Any] = {}
    found = sign_in(fake, store)

    assert found.outcome is SignInOutcome.DONE, found
    assert found.kinds == ()
    assert found.subject == SIGNIN_USER_ID


@pytest.mark.django_db
def test_the_seam_writes_no_row(
    signin_instance: FakeSignInZitadel, django_assert_num_queries: Any
) -> None:
    """The whole ceremony, end to end, under a query counter set to zero.

    Two halves, because either alone is dodgeable. The RUNTIME half is the
    counter: a ceremony that wrote a row would spend a query. The STATIC half
    is the module's own imports: `signin.py` importing a model or a service
    is a row one refactor away, and the counter would not see it until the
    day somebody added the write.
    """
    fake = signin_instance
    fake.auth_methods.append("AUTHENTICATION_METHOD_TYPE_TOTP")
    store: dict[str, Any] = {}

    with django_assert_num_queries(0):
        assert sign_in(fake, store).step is Step.FACTOR
        assert signin.challenge(store, kind=FactorKind.TOTP.value).step is Step.FACTOR
        assert signin.answer(store, code=fake.factor_code).outcome is SignInOutcome.DONE

    imported = {
        node.module or ""
        for node in ast.walk(source_tree(BASE_DIR / "apps/accounts/signin.py"))
        if isinstance(node, ast.ImportFrom)
    }
    forbidden = {name for name in imported if name.endswith((".models", ".services", ".selectors"))}
    assert forbidden == set(), f"the seam imports a row-shaped module: {sorted(forbidden)}"


# --- A3.3 · every opened session closed at every exit ------------------------


def test_every_opened_session_is_closed_at_every_exit(
    signin_instance: FakeSignInZitadel,
) -> None:
    """ADR ident-10: every Zitadel session this module opens, it closes.

    Driven over EVERY exit rather than over the happy one, because the exits
    that leak are the ones nobody walks by hand: a refused factor, an outage
    half way through, a person who closed the tab, a second `begin` over a
    ceremony already in flight. The assertion is a list comparison and not a
    set one — a session closed twice and a session never closed have the same
    set difference.
    """
    fake = signin_instance
    fake.auth_methods.append("AUTHENTICATION_METHOD_TYPE_TOTP")

    # done
    store: dict[str, Any] = {}
    sign_in(fake, store)
    signin.answer(store, code=fake.factor_code)
    # cancelled
    store = {}
    sign_in(fake, store)
    signin.cancel(store)
    # refused, at the factor step
    store = {}
    sign_in(fake, store)
    signin.answer(store, code="000000")
    signin.cancel(store)
    # an outage half way through: the 503 is spent by the factor PATCH, and
    # the DELETE behind it still has to happen.
    store = {}
    sign_in(fake, store)
    signin.challenge(store, kind=FactorKind.TOTP.value)
    fake.refusals = [(503, "")]
    signin.answer(store, code=fake.factor_code)
    # a second begin over a ceremony already in flight
    store = {}
    sign_in(fake, store)
    sign_in(fake, store)
    signin.cancel(store)

    assert fake.opened_sessions == fake.closed_sessions
    assert fake.sessions == {}
    assert len(fake.opened_sessions) >= 6


# --- A3.4 · the two clocks ---------------------------------------------------


def test_the_deadline_bounds_the_whole_check(
    signin_instance: FakeSignInZitadel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One call's timeout cannot bound a check that is four calls long.

    The clock is stepped so that the FIRST call lands inside the deadline and
    the second does not. The assertion is that the second request was never
    SENT — not that it came back late — which is the whole difference between
    a deadline and a timeout, and the reason the check is made before each
    call rather than after.
    """
    fake = signin_instance
    assert zitadel.signin_timeout() == 4.0
    from django.conf import settings as django_settings

    assert django_settings.ZITADEL_SIGNIN_DEADLINE == 12.0

    ticks = iter([0.0, 0.0, 99.0, 99.0, 99.0, 99.0])
    monkeypatch.setattr(signin, "monotonic", lambda: next(ticks))

    store: dict[str, Any] = {}
    found = signin.begin(store, address=fake.login_name, password=fake.password)

    assert found.outcome is SignInOutcome.UNAVAILABLE
    assert found.reason == "deadline_reached"
    # The session was opened and then closed; the READ that would have
    # followed it never happened.
    assert fake.opened_sessions == fake.closed_sessions != []
    reads = [call for call in fake.whole_calls if call[0] == "GET" and "/v2/sessions/" in call[1]]
    assert reads == [], reads
    assert store == {}


def test_a_session_call_runs_under_the_sign_in_clock_not_the_management_one(
    signin_instance: FakeSignInZitadel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The per-call half of A3.4, asserted where the caller is.

    The stub transport never waits, so the number under test is the one
    `zitadel._client` is HANDED. A management call keeps the management clock
    in the same run, which is what makes this a difference rather than a
    global change.
    """
    handed: list[float | None] = []
    real_client = zitadel._client

    def recorded(*, timeout: float | None = None) -> Any:
        handed.append(timeout)
        return real_client(timeout=timeout)

    monkeypatch.setattr(zitadel, "_client", recorded)

    zitadel.open_session(checks={"user": {"loginName": signin_instance.login_name}})
    zitadel.organization()

    assert handed == [4.0, None]


# --- A3.5 · the throttle -----------------------------------------------------


def test_the_sixth_try_in_a_minute_is_throttled_and_zitadel_is_not_asked(
    signin_instance: FakeSignInZitadel,
) -> None:
    """Our limit sits in FRONT of Zitadel, which is the whole of its value.

    An account lockout protects one account over its lifetime and cannot see
    a try against an address that has no account at all; this bounds what one
    form can spend in a minute either way. The second assertion is the one
    that makes it a throttle rather than a message: the call count does not
    move on the sixth try.
    """
    fake = signin_instance
    for attempt in range(5):
        found = signin.begin({}, address=fake.login_name, password=WRONG_PASSWORD)
        assert found.outcome is SignInOutcome.REFUSED, attempt

    asked = len(fake.whole_calls)
    found = signin.begin({}, address=fake.login_name, password=WRONG_PASSWORD)

    assert found.outcome is SignInOutcome.THROTTLED
    assert found.step is Step.PASSWORD
    assert len(fake.whole_calls) == asked, "Zitadel was asked on a throttled try"


def test_the_client_address_has_its_own_bucket(
    signin_instance: FakeSignInZitadel,
) -> None:
    """The dodge the address bucket alone leaves open, closed.

    Five tries against five DIFFERENT addresses are five misses under the
    per-address limit and one caller walking a list under the per-client one.
    Both buckets are spent on every try, deliberately un-short-circuited, or
    the second would never fill once the first refused.
    """
    for attempt in range(5):
        found = signin.begin(
            {},
            address=f"nobody-{attempt}@yourco.test",
            password=WRONG_PASSWORD,
            client_address="10.0.0.9",
        )
        assert found.outcome is SignInOutcome.REFUSED, attempt

    found = signin.begin(
        {},
        address="nobody-5@yourco.test",
        password=WRONG_PASSWORD,
        client_address="10.0.0.9",
    )
    assert found.outcome is SignInOutcome.THROTTLED

    # A different caller is unaffected: the bucket is per client, not global.
    found = signin.begin(
        {},
        address="nobody-6@yourco.test",
        password=WRONG_PASSWORD,
        client_address="10.0.0.10",
    )
    assert found.outcome is SignInOutcome.REFUSED


def test_no_bucket_key_carries_the_address_itself(
    signin_instance: FakeSignInZitadel,
) -> None:
    """A cache key reaches Redis's MONITOR and its slow log. A digest does not."""
    key = signin._bucket("address", SIGNIN_LOGIN_NAME)
    assert SIGNIN_LOGIN_NAME not in key
    assert "yourco" not in key
    # And it is stable, or the limit would be one try per process.
    assert key == signin._bucket("address", SIGNIN_LOGIN_NAME.upper())


# --- A3.6 · no secret in a log ----------------------------------------------


def test_no_secret_reaches_a_log_line(
    signin_instance: FakeSignInZitadel, caplog: pytest.LogCaptureFixture
) -> None:
    """The whole ceremony, swept. Nothing a person typed, nothing we were given.

    The sweep is over what LEFT the process, not over the call sites, because
    a call site census cannot see a value that arrived inside a dict somebody
    splatted into a log call. The address is in the list beside the password:
    a log line naming who tried to sign in is an oracle over which addresses
    exist, which is the same A9 posture the page's own sentences hold.
    """
    fake = signin_instance
    fake.auth_methods.append("AUTHENTICATION_METHOD_TYPE_TOTP")

    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        store: dict[str, Any] = {}
        sign_in(fake, store)
        signin.challenge(store, kind=FactorKind.TOTP.value)
        token = str(store[signin.CEREMONY_KEY]["token"])
        signin.answer(store, code=fake.factor_code)

        enrolling: dict[str, Any] = {}
        fake.auth_methods = ["AUTHENTICATION_METHOD_TYPE_PASSWORD"]
        fake.login_settings["forceMfa"] = True
        sign_in(fake, enrolling)
        enrolment = signin.enrol(enrolling)
        signin.confirm_enrolment(enrolling, code=fake.factor_code)

        signin.begin(
            {},
            address=fake.login_name,
            password=A_THIRD_WRONG_PASSWORD,
        )

    whole = caplog.text
    forbidden = {
        "the password": SIGNIN_PASSWORD,
        "a wrong password": A_THIRD_WRONG_PASSWORD,
        "the address": SIGNIN_LOGIN_NAME,
        "the factor code": SIGNIN_FACTOR_CODE,
        "the session token": token,
        "the enrolment secret": enrolment.enrolment_secret,
        "the enrolment uri": enrolment.enrolment_uri,
    }
    for what, secret in forbidden.items():
        assert secret, f"the sweep's own {what} is empty — it would pass against anything"
        assert secret not in whole, f"{what} reached a log line"

    ours = [
        line
        for line in structured(caplog)
        if str(line.get("event", "")).startswith("accounts.signin.")
    ]
    assert ours, "the ceremony logged nothing at all — the sweep would pass on silence"
    assert {str(line["event"]) for line in ours} <= set(signin.LOG_EVENTS), sorted(
        {str(line["event"]) for line in ours} - set(signin.LOG_EVENTS)
    )
    # The opaque platform id IS logged, and is the thing an operator joins on.
    assert SIGNIN_USER_ID in whole


# --- A3.7 · the ceremony keys a closed set ----------------------------------


def test_the_ceremony_keys_a_closed_set(signin_instance: FakeSignInZitadel) -> None:
    """Whatever branch ran, the state between two POSTs is enumerable.

    And the closure is enforced rather than asserted: `_remember` refuses a
    key outside the declared set, so a typo is a loud failure at the write
    rather than a field nobody reads.
    """
    fake = signin_instance
    fake.auth_methods.append("AUTHENTICATION_METHOD_TYPE_TOTP")
    store: dict[str, Any] = {}

    sign_in(fake, store)
    assert set(store) == {signin.CEREMONY_KEY}
    assert set(store[signin.CEREMONY_KEY]) <= signin.CEREMONY_FIELDS

    signin.challenge(store, kind=FactorKind.TOTP.value)
    assert set(store[signin.CEREMONY_KEY]) <= signin.CEREMONY_FIELDS

    with pytest.raises(ValueError, match="closed set"):
        signin._remember(store, not_a_field="x")


def test_the_ceremony_is_deleted_at_every_exit(signin_instance: FakeSignInZitadel) -> None:
    """Every exit, including the ones nobody walks by hand."""
    fake = signin_instance
    fake.auth_methods.append("AUTHENTICATION_METHOD_TYPE_TOTP")

    exits: dict[str, Any] = {}

    store: dict[str, Any] = {}
    sign_in(fake, store)
    signin.answer(store, code=fake.factor_code)
    exits["done"] = dict(store)

    store = {}
    sign_in(fake, store)
    signin.cancel(store)
    exits["cancelled"] = dict(store)

    store = {}
    signin.begin(store, address=fake.login_name, password=WRONG_PASSWORD)
    exits["refused"] = dict(store)

    store = {}
    fake.refusals = [(503, "")]
    signin.begin(store, address=fake.login_name, password=fake.password)
    exits["unavailable"] = dict(store)

    store = {}
    sign_in(fake, store)
    signin.challenge(store, kind="carrier-pigeon")
    exits["kind_unanswerable"] = dict(store)

    for exit_name, left in exits.items():
        assert left == {}, f"the {exit_name} exit left a ceremony behind: {left}"


# --- A3.8 · M5, M8, M9, M11 are checks --------------------------------------


def test_the_four_session_facts_are_measured_and_not_promised() -> None:
    """A3.8 as a census over the measurement kit's own declarations.

    `zitadel_measure` prints `unmeasured — <rung>` for every item whose
    ingredient does not exist yet, and the four the Session API rests on must
    not be in that population: a design drawn on four facts nothing re-asks is
    a design drawn on four docstrings.
    """
    from apps.accounts.management.commands import zitadel_measure

    promised = set(zitadel_measure.PROMISED)
    for item in ("M5", "M8", "M9", "M11"):
        named = [one.id for one in zitadel_measure.ITEMS if one.id.startswith(f"{item} ")]
        assert len(named) == 1, f"{item} is not one line in the kit: {named}"
        assert named[0] not in promised, f"{item} is still `unmeasured` — A3.8 is not met"


# --- A3.9 · the door population, declared ------------------------------------


def test_one_door_reaches_the_seam_and_it_is_the_one_a5_mounted(
    signin_instance: FakeSignInZitadel,
) -> None:
    """**Exactly one importer, and it is the door.** A3 declared this; A5 landed it.

    A census rather than a grep string, because the three import spellings are
    what a grep for one of them misses. The tests are excluded by
    construction — they are the drive, not a door — and everything else under
    `apps/` and `config/` must be silent.

    **SET EQUALITY, in both directions, and that is the whole point of keeping
    the census after the door exists.** Before A5 it read "nobody"; a census
    that had simply been deleted when the door landed would have stopped
    saying anything about the second importer — a service, an activity, a
    consumer reaching past the door into the ceremony — which is the thing the
    seam's shape exists to prevent. One request-path importer of the Session
    API is what makes `SIGN_IN_DOOR=hosted` a complete exit (principle 5: one
    boundary above the vendor), and it is true only while this list is one
    name long.
    """
    importers: list[str] = []
    for path in sorted(BASE_DIR.glob("apps/**/*.py")) + sorted(BASE_DIR.glob("config/**/*.py")):
        relative = str(path.relative_to(BASE_DIR))
        if "/tests/" in relative or relative.endswith("signin.py"):
            continue
        # THE TOLERANT READ (`apps.core.tests.tree_census`): a file this
        # walk listed and another xdist worker's teardown removed between
        # the listing and the open is SKIPPED, not a FileNotFoundError.
        tree = source_tree(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "apps.accounts.signin"
            ):
                importers.append(relative)
            if isinstance(node, ast.ImportFrom) and (node.module or "") == "apps.accounts":
                if any(alias.name == "signin" for alias in node.names):
                    importers.append(relative)
            if isinstance(node, ast.Import) and any(
                alias.name.startswith("apps.accounts.signin") for alias in node.names
            ):
                importers.append(relative)

    assert importers == ["apps/accounts/views.py"], (
        f"the seam has exactly one importer and it is the sign-in door; found {importers}"
    )

    # And the module says which rung owns the door, so the next reader does
    # not have to find this test to learn it.
    source = source_text(BASE_DIR / "apps/accounts/signin.py")
    assert "rung A5" in source
    assert "SIGN_IN_DOOR" in source


def test_the_seam_rides_rule_27_on_the_valve_with_its_reason() -> None:
    """The one import that needs a reason carries one, and the reason is the rung's.

    Lane I's Overrule 7: three importers ride the valve and the allow-list is
    not edited here. A bare `# rule-27:` is itself a finding (the rule counts
    reasons under twelve characters), so this asserts the reason is the
    argued one rather than a word that satisfies the length.
    """
    # The marker is ASSEMBLED rather than typed. Rule 27 counts marker-shaped
    # strings wherever they appear — a docstring included — so a test that
    # spelled it would plant two bare overrides in this file and report them
    # as findings against the module it is checking.
    marker = "# rule-" + "27:"
    source = source_text(BASE_DIR / "apps/accounts/signin.py")
    assert marker in source
    assert "a sign-in CHECK is not the identity-configuration WRITE" in source
    assert "quality/rules.yaml" not in source.split(marker)[0]


# --- A6 · what the seam grew for the factor and enrolment roads --------------
#
# Four properties, all of them about the difference between what a person HAS
# enrolled and what this deployment can actually put in front of them. A seam
# that conflated the two would draw a chip for an emailed code on an instance
# with no mail sender, and the person would sit at a form waiting for a
# message nobody sent.

#: An SMTP configuration in the shape `GET /admin/v1/smtp` answers, belonging
#: to somebody else — the `description` is the only place an owner is written
#: down at all and `Set by <product>` is the shape both products on the shared
#: development instance write (`zitadel_audit.smtp_owner`). Copied in shape
#: from `test_zitadel_console_surfaces.SOMEBODY_ELSES_SMTP`, which is where it
#: was measured; not imported, because that module's constant is the AUDIT's
#: fixture and a test that shared it would couple two rungs' worlds.
A_FOREIGN_SENDER: dict[str, Any] = {
    "senderAddress": "no-reply@example-crm.localhost",
    "senderName": "ExampleCRM",
    "host": "mailpit:1025",
    "state": "SMTP_CONFIG_ACTIVE",
    "description": "Set by ExampleCRM (accounts.login_policy)",
    "id": "388471039450939395",
}


def _ours(product: str) -> dict[str, Any]:
    """The same configuration, described as this deployment's own."""
    return {**A_FOREIGN_SENDER, "description": f"Set by {product} (accounts.login_policy)"}


@pytest.mark.parametrize("answer_shape", ["empty", "missing"])
def test_an_emailed_code_is_not_offered_without_a_sender(
    signin_instance: FakeSignInZitadel, answer_shape: str
) -> None:
    """ENROLLED ∩ DELIVERABLE, and the ∩ is what this test is.

    Two shapes for "no sender", because only the STATE is measured and not
    the answer: an instance with no SMTP configuration may answer an empty
    envelope or refuse the read outright, nobody has taken it off the pinned
    build to find out, and a door whose behaviour depended on which would be
    a door built on a guess. Both land on the same dead end with a sentence.
    """
    fake = signin_instance
    fake.smtp = {}
    fake.smtp_none_answers = answer_shape
    fake.auth_methods.append("AUTHENTICATION_METHOD_TYPE_OTP_EMAIL")

    store: dict[str, Any] = {}
    found = sign_in(fake, store)

    assert found.outcome is SignInOutcome.KIND_UNANSWERABLE, found
    assert found.reason == FactorKind.OTP_EMAIL.value
    assert found.kinds == ()
    assert fake.opened_sessions == fake.closed_sessions


def test_an_emailed_code_is_offered_when_the_instance_has_a_sender(
    signin_instance: FakeSignInZitadel, settings: Any
) -> None:
    """The same person, the same enrolment, one fact about the deployment changed."""
    fake = signin_instance
    settings.PRODUCT_NAME = "Pilecap"
    fake.smtp = _ours("Pilecap")
    fake.auth_methods.append("AUTHENTICATION_METHOD_TYPE_OTP_EMAIL")

    store: dict[str, Any] = {}
    found = sign_in(fake, store)

    assert found.outcome is SignInOutcome.CONTINUE, found
    assert found.step is Step.FACTOR
    assert found.kinds == (FactorKind.OTP_EMAIL,)
    # Our own sender is not named: the note exists to warn, and a warning
    # printed on every page is a warning nobody reads.
    assert found.foreign_sender == ""


def test_a_foreign_sender_is_named_and_it_is_the_audits_own_reading(
    signin_instance: FakeSignInZitadel, settings: Any
) -> None:
    """F10. The chip's availability is one read; whose mail it is, the same one.

    The reading is `zitadel_audit`'s, imported rather than restated, so the
    sentence on the sign-in page and the `foreign` line in `manage.py
    zitadel_audit` cannot come to disagree about whose instance this is.
    """
    fake = signin_instance
    settings.PRODUCT_NAME = "Pilecap"
    fake.smtp = dict(A_FOREIGN_SENDER)
    fake.auth_methods.append("AUTHENTICATION_METHOD_TYPE_OTP_EMAIL")

    store: dict[str, Any] = {}
    found = sign_in(fake, store)

    assert found.kinds == (FactorKind.OTP_EMAIL,)
    assert found.foreign_sender == "no-reply@example-crm.localhost"
    assert zitadel_audit.smtp_owner(fake.smtp) == "ExampleCRM"


def test_the_sender_read_is_bought_only_by_the_people_it_is_about(
    signin_instance: FakeSignInZitadel,
) -> None:
    """Nobody signing in with an authenticator app pays a round trip for mail."""
    fake = signin_instance
    fake.auth_methods.append("AUTHENTICATION_METHOD_TYPE_TOTP")

    store: dict[str, Any] = {}
    sign_in(fake, store)

    # `whole_calls`, not `requests`: the measured fake answers its own routes
    # before the base fake's log is reached, so an assertion against
    # `requests` is green whatever the ceremony asked for.
    assert all(call[1] != "/admin/v1/smtp" for call in fake.whole_calls)


def test_an_sms_code_a_key_and_a_passkey_are_not_offered_by_this_door(
    signin_instance: FakeSignInZitadel,
) -> None:
    """`ANSWERABLE_HERE`, driven as a population rather than read as a constant.

    Each of the three is excluded for a reason stated beside the constant, and
    each of them is a person who must reach a sentence rather than a form:
    nothing here can tell whether the instance has an SMS provider, and the
    browser ceremony a key or a passkey needs is design J6.
    """
    fake = signin_instance
    for kind, name in (
        (FactorKind.OTP_SMS, "AUTHENTICATION_METHOD_TYPE_OTP_SMS"),
        (FactorKind.U2F, "AUTHENTICATION_METHOD_TYPE_U2F"),
        (FactorKind.PASSKEY, "AUTHENTICATION_METHOD_TYPE_PASSKEY"),
    ):
        fake.auth_methods = [signin.ZITADEL_PASSWORD_METHOD, name]
        store: dict[str, Any] = {}
        found = sign_in(fake, store)
        assert found.outcome is SignInOutcome.KIND_UNANSWERABLE, (kind, found)
        assert found.reason == kind.value
        assert kind not in signin.ANSWERABLE_HERE


def test_a_wrong_code_keeps_the_ceremony_and_a_sixth_one_ends_it(
    signin_instance: FakeSignInZitadel,
) -> None:
    """WATCH F8, one screen later — and the bound that keeps it from being an oracle.

    A mistyped digit must not cost the person their password: the platform
    judged six characters and the session it judged them against is still
    verified, so the ceremony stays and the next code is one field away. What
    it must also not be is unbounded — a six-digit code is a million guesses
    — so the same per-minute counter that stands in front of the password
    stands here, and the try that exceeds it ends the ceremony for real.
    """
    fake = signin_instance
    fake.auth_methods.append("AUTHENTICATION_METHOD_TYPE_TOTP")
    limit = int(django_settings.SIGNIN_THROTTLE_PER_MINUTE)

    store: dict[str, Any] = {}
    sign_in(fake, store)
    for _ in range(limit):
        refused = signin.answer(store, code="000000")
        assert refused.outcome is SignInOutcome.REFUSED, refused
        assert refused.step is Step.FACTOR
        assert signin.CEREMONY_KEY in store, "a wrong code threw the ceremony away"

    over = signin.answer(store, code="000000")

    assert over.outcome is SignInOutcome.THROTTLED
    assert store == {}, "the try over the limit must end the ceremony"
    assert fake.opened_sessions == fake.closed_sessions


def test_the_right_code_after_a_wrong_one_still_lands(
    signin_instance: FakeSignInZitadel,
) -> None:
    """The other half: the ceremony that survived is one a person can finish."""
    fake = signin_instance
    fake.auth_methods.append("AUTHENTICATION_METHOD_TYPE_TOTP")

    store: dict[str, Any] = {}
    sign_in(fake, store)
    signin.answer(store, code="000000")
    landed = signin.answer(store, code=fake.factor_code)

    assert landed.outcome is SignInOutcome.DONE, landed
    assert landed.subject == SIGNIN_USER_ID
    assert store == {}


def test_offered_reads_back_what_the_ceremony_is_offering(
    signin_instance: FakeSignInZitadel, settings: Any
) -> None:
    """The door redraws the chooser from the ceremony, never from the request."""
    fake = signin_instance
    settings.PRODUCT_NAME = "Pilecap"
    fake.smtp = _ours("Pilecap")
    fake.auth_methods += [
        "AUTHENTICATION_METHOD_TYPE_TOTP",
        "AUTHENTICATION_METHOD_TYPE_OTP_EMAIL",
    ]

    store: dict[str, Any] = {}
    found = sign_in(fake, store)

    assert set(found.kinds) == {FactorKind.TOTP, FactorKind.OTP_EMAIL}
    assert set(signin.offered(store)) == set(found.kinds)
    assert signin.offered({}) == ()


@pytest.mark.parametrize(
    ("lifetime", "days"),
    [("2592000s", 30), ("86400s", 1), ("3600s", 1), ("0s", 0), ("", 0), ("nonsense", 0)],
)
def test_the_skip_window_is_read_in_whole_days(lifetime: str, days: int) -> None:
    """Design J2-c prints *Not now (N days)*, so N has to come from somewhere.

    A protobuf Duration, in seconds, from the org's own login settings — and
    anything unreadable is zero, because an unparseable lifetime is not a
    licence to offer a skip whose length nobody can state.
    """
    assert signin._skip_days(lifetime) == days


def test_not_now_is_offered_exactly_when_the_platform_allows_a_skip(
    signin_instance: FakeSignInZitadel,
) -> None:
    """Both arms, because the wrong one is a door that looks available and refuses."""
    fake = signin_instance
    fake.login_settings = {"forceMfa": True, "mfaInitSkipLifetime": "2592000s"}

    store: dict[str, Any] = {}
    forced = sign_in(fake, store)
    assert forced.step is Step.ENROL
    assert forced.may_skip is True
    assert forced.skip_days == 30
    assert signin.skip_enrolment(store).outcome is SignInOutcome.DONE

    fake.login_settings = {"forceMfa": True, "mfaInitSkipLifetime": "0s"}
    store = {}
    forced = sign_in(fake, store)
    assert forced.may_skip is False
    assert forced.skip_days == 0
    refused = signin.skip_enrolment(store)
    assert refused.outcome is SignInOutcome.REFUSED
    assert refused.reason == "skip_not_offered"


# --- A9 · the passkey road (design J6) ---------------------------------------
#
# Every number in this section came off v4.17.1 on 2026-09-19, driven through
# `apps/accounts/zitadel.py` with a virtual authenticator built for the walk.
# The one that changed the design: **a passkey bound elsewhere and no passkey
# at all answer the same 500 with the same error id**, so the sentence design
# J6 writes is unreachable from the refusal and has to be reached from what
# the person owns.

#: Hosts a relying-party id can be, and hosts it cannot. `localhost` is the
#: name the specification exempts and the one a laptop actually types; an IP
#: address is refused by every browser, and the shipped `PUBLIC_BASE_URL` is
#: one, which is why this predicate exists at all rather than being assumed.
RP_HOSTS: tuple[tuple[str, bool], ...] = (
    ("https://app.example.com", True),
    ("https://sign-in.yourco.test", True),
    ("http://localhost:8000", True),
    ("http://127.0.0.1:8000", False),
    ("http://192.168.1.10:8000", False),
    ("", False),
)


@pytest.mark.parametrize(("base_url", "open_road"), RP_HOSTS)
def test_the_passkey_road_is_open_only_where_the_host_can_be_a_relying_party(
    settings: Any, base_url: str, open_road: bool
) -> None:
    """A door that looks available and refuses, one screen before J2-c's version.

    The server is happy either way — A9's drive measured Zitadel minting
    `rpId: "127.0.0.1"` and answering a begin **201** and a finish **200**
    for it — and no browser will run that ceremony, because a relying-party
    id must be a domain. So the affordance is withheld on the evidence of the
    host rather than drawn and left to fail in the person's hand.
    """
    settings.PUBLIC_BASE_URL = base_url

    assert signin.passkey_road_open() is open_road
    assert (FactorKind.PASSKEY in signin.answerable_here()) is open_road


def test_a_passkey_bound_to_this_host_begins_and_finishes(
    signin_instance: FakeSignInZitadel, settings: Any
) -> None:
    """J6's entrance, end to end on the seam. **An address and a device, no password.**

    MEASURED: `POST /v2/sessions` with a `user` check carrying a LOGIN NAME,
    no password check and a `webAuthN` challenge answers 201 with the request
    options; the assertion goes back as
    `checks.webAuthN.credentialAssertionData` and answers 200 with
    `factors.webAuthN.verifiedAt` set.
    """
    fake = signin_instance
    settings.PUBLIC_BASE_URL = "https://app.example.test"
    fake.passkey_rp = "app.example.test"
    cache.clear()

    store: dict[str, Any] = {}
    begun = signin.passkey_begin(store, address=fake.login_name)

    assert begun.outcome is SignInOutcome.CONTINUE, begun
    assert begun.step is Step.FACTOR
    assert begun.kinds == (FactorKind.PASSKEY,)
    options = json.loads(begun.passkey_options)
    assert options["rpId"] == "app.example.test"
    assert len(options["allowCredentials"]) == 1

    landed = signin.answer(
        store, assertion=json.dumps({"id": fake.passkey_credential_id, "type": "public-key"})
    )

    assert landed.outcome is SignInOutcome.DONE, landed
    assert landed.subject == SIGNIN_USER_ID
    assert store == {}
    assert fake.opened_sessions == fake.closed_sessions


def test_a_passkey_bound_elsewhere_reads_the_elsewhere_state(
    signin_instance: FakeSignInZitadel, settings: Any
) -> None:
    """K1, and the correction A9's drive made to it.

    The consumer measured `500 WEBAU-3M9si` for a passkey bound to another
    relying party. **On this build it is `500 WEBAU-4G8sw`** — the same id a
    person with NO passkey gets, for a credential bound elsewhere and for a
    domain neither party owns alike. The refusal therefore cannot say which,
    and the seam asks `authentication_methods` instead: somebody who owns a
    passkey this host cannot use reads design J6's own sentence, and somebody
    who owns none reads the ordinary one.
    """
    fake = signin_instance
    settings.PUBLIC_BASE_URL = "https://app.example.test"
    fake.passkey_rp = "identity.example.test"  # Zitadel's own host, not ours
    cache.clear()

    store: dict[str, Any] = {}
    found = signin.passkey_begin(store, address=fake.login_name)

    assert found.outcome is SignInOutcome.KIND_UNANSWERABLE, found
    assert found.reason == signin.PASSKEY_ELSEWHERE
    assert store == {}
    assert fake.opened_sessions == fake.closed_sessions


def test_no_passkey_at_all_is_not_told_to_go_and_find_one(
    signin_instance: FakeSignInZitadel, settings: Any
) -> None:
    """The other arm of the same refusal, and the reason the arm exists.

    Both people get `500 WEBAU-4G8sw`. Telling the one who never registered
    anything that "passkeys added elsewhere don't work here" would send them
    hunting for a device they do not have.
    """
    fake = signin_instance
    settings.PUBLIC_BASE_URL = "https://app.example.test"
    fake.passkey_rp = None
    cache.clear()

    found = signin.passkey_begin({}, address=fake.login_name)

    assert found.outcome is SignInOutcome.KIND_UNANSWERABLE, found
    # **Not the KIND's reason** — V-A-W3 read "this account signs in with a
    # passkey" on somebody who had never registered one, which is the one
    # thing that is certainly untrue of them.
    assert found.reason == signin.PASSKEY_NONE


def test_the_begin_always_names_the_person(
    signin_instance: FakeSignInZitadel, settings: Any
) -> None:
    """There is no discoverable road on this build, so the seam never tries one.

    MEASURED: `POST /v2/sessions` carrying a `webAuthN` challenge and no
    `checks.user` answers **400 `COMMAND-eeR2e` "User ID missing"**, for our
    host and for the platform's alike — which is design J6 entrance (a)'s
    stated mechanism, refused. A census over what was actually SENT, because
    a seam that tried it and fell back would pass every test about the
    answer.
    """
    fake = signin_instance
    settings.PUBLIC_BASE_URL = "https://app.example.test"
    fake.passkey_rp = "app.example.test"
    cache.clear()

    signin.passkey_begin({}, address=fake.login_name)

    sent = [body for method, path, _, body in fake.whole_calls if path == "/v2/sessions"]
    assert sent, "the begin was never made"
    for body in sent:
        if "webAuthN" in dict(body.get("challenges") or {}):
            assert dict(body.get("checks") or {}).get("user"), body


def test_an_unreadable_assertion_is_refused_and_never_forwarded(
    signin_instance: FakeSignInZitadel, settings: Any
) -> None:
    """A form field is whatever the page was handed. **Parsed, or refused.**"""
    fake = signin_instance
    settings.PUBLIC_BASE_URL = "https://app.example.test"
    fake.passkey_rp = "app.example.test"
    cache.clear()

    store: dict[str, Any] = {}
    signin.passkey_begin(store, address=fake.login_name)
    before = len(fake.whole_calls)

    refused = signin.answer(store, assertion="not json at all")

    assert refused.outcome is SignInOutcome.REFUSED
    assert refused.reason == "assertion_unreadable"
    assert len(fake.whole_calls) == before, "an unreadable body was sent to the platform anyway"


def test_the_passkey_chip_road_carries_the_challenge(
    signin_instance: FakeSignInZitadel, settings: Any
) -> None:
    """Design J6 entrance (b): password first, then the device.

    The chip exists only where the road is open, and pressing it puts the
    platform's own request options in the verdict for the page to hand the
    browser.
    """
    fake = signin_instance
    settings.PUBLIC_BASE_URL = "https://app.example.test"
    fake.passkey_rp = "app.example.test"
    fake.auth_methods = [signin.ZITADEL_PASSWORD_METHOD]
    cache.clear()

    store: dict[str, Any] = {}
    after = signin.begin(store, address=fake.login_name, password=fake.password)

    assert after.outcome is SignInOutcome.CONTINUE, after
    assert after.kinds == (FactorKind.PASSKEY,)

    asked = signin.challenge(store, kind=FactorKind.PASSKEY.value)

    assert asked.outcome is SignInOutcome.CONTINUE, asked
    assert json.loads(asked.passkey_options)["rpId"] == "app.example.test"

    landed = signin.answer(
        store, assertion=json.dumps({"id": fake.passkey_credential_id, "type": "public-key"})
    )
    assert landed.outcome is SignInOutcome.DONE, landed
