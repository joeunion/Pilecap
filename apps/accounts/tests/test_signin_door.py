# census: cross-app A5's door — its mount order, setting, frames and env examples
"""The switch: which sign-in door `/accounts/login/` opens, and what each does.

Design C-13. `SIGN_IN_DOOR` is one setting with two values and no third state,
and the properties below are in two families because the two doors owe
different things:

**Under `hosted` — the DEFAULT — nothing moved.** That is the whole criterion,
and it is the one a person who never touches this setting is protected by. The
page is byte-identical against A4's captured fixtures, the POST is still
refused, the seed still declares no login version, the logout page still says
what it said, and the first-admin link is still the identity platform's. A rung
that mounted a view of ours in front of allauth and changed the page by one
byte would have changed every deployment in the field.

**Under `ours` the password road, and nothing more.** Rung A5 ships J2-a: GET
the sign-in frame, POST an address and a password, and land. A person whose
organisation asks for a second step meets a SENTENCE and a dead end, for every
kind, and never a 302 to the hosted page — under login v2 that is a loop the
person can only leave by clearing cookies (the consumer's K10, an owner locked
out for a morning). Rung A6 builds the factor road; until it does, the honest
answer is the sentence, and the ceremony is CLOSED on the way to it.

**What this module does not do: decide who may sign in.** Landing goes through
allauth's `complete_social_login`, so `SocialAccountAdapter._platform_login`
makes the same three decisions it makes on the OIDC road. Three cases below
drive those three decisions THROUGH THIS DOOR rather than restating them — a
door that had quietly built its own assertion, or passed `verified=True`
because the password was right, would pass every test that signs the right
person in.

Nothing here dials Zitadel: the socket is `FakeSignInZitadel` with the one
human row `find_user` reads back, and the live walk is the verifier's.
"""

from __future__ import annotations

import ast
import html
import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from django.conf import settings as django_settings
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client
from django.urls import resolve, reverse

from apps.accounts import qr, signin, views, zitadel
from apps.accounts.management.commands import zitadel_seed
from apps.accounts.models import User
from apps.accounts.signin import (
    ZITADEL_FACTOR_NAMES,
    ZITADEL_PASSWORD_METHOD,
    FactorKind,
    SignIn,
    SignInOutcome,
    Step,
)
from apps.accounts.tests.conftest import (
    SIGNIN_INVITE_CODE,
    SIGNIN_INVITED_USER_ID,
    SIGNIN_LOGIN_NAME,
    SIGNIN_PASSWORD,
    SIGNIN_USER_ID,
    FakeInvitedZitadel,
    FakeModeAZitadel,
    FakeSignInZitadel,
)
from apps.accounts.tests.test_entrance_frames import BASELINES, FRAMES_DIR, _doors
from apps.accounts.tests.test_signin import A_FOREIGN_SENDER
from apps.core.tests.tree_census import source_text, source_tree

pytestmark = pytest.mark.django_db

BASE_DIR = Path(django_settings.BASE_DIR)
HERE = Path(__file__).resolve().parent
LOGIN_URL = "/accounts/login/"

#: A password that is not the fixture person's. Declared once, for the reason
#: `test_signin.py` declares its three: `detect-secrets` keys on the keyword,
#: and a pragma on a call `ruff format` may rewrap is a pragma on the wrong
#: line.
WRONG_PASSWORD = "not-the-password"  # pragma: allowlist secret

#: The three files a clone or a deployment copies. `DJB_SIGN_IN_DOOR` ships
#: COMMENTED in each, at the default, because turning it on writes a
#: declaration into somebody else's identity instance.
ENV_EXAMPLES = (".env.example", "deploy/env.prod.example", "deploy/env.staging.example")


# --- the world ---------------------------------------------------------------


@pytest.fixture
def door(monkeypatch: pytest.MonkeyPatch, settings: Any) -> Iterator[FakeSignInZitadel]:
    """`signin_instance`'s socket, plus the management row the DOOR reads.

    The seam answers a `subject`; the door needs an ASSERTION, and the address
    and its verified flag come off the platform's own record
    (`signin.asserted_person`). The shape is MEASURED off the pinned build on
    2026-09-19 — `human.email.email` and `human.email.isEmailVerified` on a
    `POST /management/v1/users/_search` row — and it is planted here rather
    than in `conftest.py` because it is this door's read and no other test's.

    `verified` is a KNOB and not a constant, which is the point: with it
    hard-coded true the adapter's first refusal would be unreachable, and a
    check that cannot fire is a check that is not there.
    """
    fake = FakeSignInZitadel()
    settings.ZITADEL_ISSUER = "http://zitadel.test"
    settings.ZITADEL_PAT = "test-pat"
    settings.GOOGLE_WORKSPACE_DOMAINS = []
    fake.users[SIGNIN_USER_ID] = {
        "id": SIGNIN_USER_ID,
        "userName": SIGNIN_LOGIN_NAME,
        "human": {"email": {"email": SIGNIN_LOGIN_NAME, "isEmailVerified": True}},
    }

    @contextmanager
    def stubbed(*, timeout: float | None = None) -> Iterator[httpx.Client]:
        with httpx.Client(
            base_url="http://zitadel.test",
            transport=httpx.MockTransport(fake.handle),
        ) as client:
            yield client

    monkeypatch.setattr(zitadel, "_client", stubbed)
    cache.clear()
    yield fake
    cache.clear()


@pytest.fixture
def ours(settings: Any, platform_provider: None) -> None:
    """The other door, turned on for one test. Never a default (decision 19).

    It brings `platform_provider` with it because the two really are one
    state: the door completes a sign-in through allauth's own provider, and a
    deployment with an empty `ZITADEL_CLIENT_ID` has no provider registered at
    all — which is a configuration this door answers 503 for, and is what
    A5.7's configured checkout is about. The case that drives the unregistered
    half asks for `ours_unconfigured` instead.
    """
    settings.SIGN_IN_DOOR = "ours"


@pytest.fixture
def ours_unconfigured(settings: Any) -> None:
    """Our door turned on in a deployment that never configured its client."""
    settings.SIGN_IN_DOOR = "ours"


def _sign_in(client: Client, *, password: str = SIGNIN_PASSWORD, **extra: str) -> Any:
    query = extra.pop("query", "")
    return client.post(
        f"{LOGIN_URL}{query}",
        {"action": "password", "email": SIGNIN_LOGIN_NAME, "password": password, **extra},
    )


def _note(body: str) -> str:
    """The sentence in the frame's alert slot, without the standing remedy.

    Unescaped, because the document is HTML and the copy has apostrophes in
    it: a comparison against the door's own constant would otherwise be a
    comparison against `&#x27;`, and the only way to make it pass would be to
    write the entity into the sentence a person reads.
    """
    found = re.search(r'<p class="alert" role="alert">(.*?)<span class="remedy">', body, re.S)
    assert found is not None, body
    return html.unescape(found.group(1).strip())


def _logout_page(client: Client) -> str:
    """The sign-out page as a signed-in person sees it.

    Signed in first, deliberately: allauth answers an anonymous GET of
    `/accounts/logout/` with a redirect and no page at all, so a test that
    read the body without a session would be asserting about an empty string
    and would stay green whatever the copy said.
    """
    from apps.accounts.services import create_user

    client.force_login(create_user(email="signed.in@yourco.test"))
    response = client.get(reverse("account_logout"))
    assert response.status_code == 200, response.status_code
    return str(response.content.decode())


def _on_the_face(body: str) -> str:
    """The copy, without the shell's own comments or its token block.

    Both are places this tree explains itself, and one of them names the
    screens the design is replacing ("the MFA screens", in the primitives
    comment inside `<style>`). A must-not-say assertion over the raw bytes
    would be an assertion about the REASONING rather than about the page, and
    the only way to satisfy it would be to delete the reasoning. What is left
    after both are removed is what a person can read.
    """
    without_comments = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    return re.sub(r"<style>.*?</style>", "", without_comments, flags=re.S)


def _title(body: str) -> str:
    found = re.search(r"<title>(.*?)</title>", body, re.S)
    assert found is not None, body
    return found.group(1).strip()


# --- A5.1 · the setting -------------------------------------------------------


def test_the_door_defaults_to_hosted() -> None:
    """A clone that declares nothing gets the door it has always had.

    Read off the live settings rather than off the source, because the thing
    being asserted is what a deployment RUNS with — and this checkout's own
    `.env` ships the line commented, which is the same statement one level
    down.
    """
    assert django_settings.SIGN_IN_DOOR == "hosted"
    assert django_settings.SIGN_IN_DOORS == ("ours", "hosted")


def test_an_unknown_door_refuses_rather_than_choosing_one() -> None:
    """A typo is `ImproperlyConfigured` at import, never the other door.

    The branch everywhere in this tree is `!= "ours"`, so a settings module
    that fell back would answer `DJB_SIGN_IN_DOOR=Ours` with the hosted page —
    a whole sign-in experience decided by a capital letter, discovered by a
    person who cannot get in. The refusal is read out of `base.py`'s own source
    because importing it under a bad value is what the guard prevents: the
    assertion is that the raise EXISTS and names the setting, and
    `apps/core/tests/test_settings.py` is where a module is re-imported under a
    planted environment.
    """
    source = source_text(BASE_DIR / "config" / "settings" / "base.py")

    assert 'env.str("DJB_SIGN_IN_DOOR", default="hosted")' in source
    assert "if SIGN_IN_DOOR not in SIGN_IN_DOORS:" in source
    assert "raise ImproperlyConfigured(" in source


@pytest.mark.parametrize("name", ENV_EXAMPLES)
def test_the_example_env_files_ship_the_door_commented_at_the_default(name: str) -> None:
    """Commented, and at `hosted`, in all three files a clone copies.

    Commented rather than set: an uncommented line is a value somebody has
    declared, and this one writes a declaration into an identity instance. A
    file that shipped it live would opt a deployment in by being copied.
    """
    text = source_text(BASE_DIR / name)
    lines = [line.strip() for line in text.splitlines() if "DJB_SIGN_IN_DOOR" in line]

    assert "# DJB_SIGN_IN_DOOR=hosted" in lines, lines
    assert not [line for line in lines if line.startswith("DJB_SIGN_IN_DOOR=")], lines


# --- A5.2 · the mount ---------------------------------------------------------


def test_the_sign_in_url_resolves_to_our_view() -> None:
    """One line ahead of allauth, and it is ours that answers."""
    assert resolve(LOGIN_URL).func is views.sign_in


def test_the_login_name_still_reverses_to_the_same_path() -> None:
    """allauth still contributes the NAME; only the callable changed.

    The shadow's whole property (ADR ident-4's `/admin/login/`, one mount
    above): every `reverse("account_login")` in this tree — the first-admin
    runbook, the invitation mail, the admin refusal, `LOGIN_URL` — keeps
    answering, and nobody had to be found and edited.
    """
    assert reverse("account_login") == LOGIN_URL


def test_the_mount_is_one_line_and_it_is_ahead_of_allauth() -> None:
    """ONE route, and its position is the whole mechanism.

    Read off the URLconf's source as a list of `path(...)` calls, because
    "ahead of" is an ordering property and `resolve` can only show the
    outcome — a mount that had drifted BELOW `include("allauth.urls")` would
    leave `resolve` answering allauth's view and this file's comment claiming
    otherwise.
    """
    tree = source_tree(BASE_DIR / "config" / "urls.py")
    paths: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        callee = node.func
        first = node.args[0]
        if not isinstance(callee, ast.Name) or callee.id != "path":
            continue
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            paths.append(first.value)

    assert paths.count("accounts/login/") == 1, paths
    assert paths.index("accounts/login/") < paths.index("accounts/"), paths


# --- A5.3 · under `hosted`, byte-identical ------------------------------------


@pytest.mark.parametrize("doors", sorted(BASELINES))
def test_hosted_get_renders_todays_page_byte_for_byte(client: Client, doors: int) -> None:
    """A4.5's fixtures, through OUR view, at both live door states.

    The same comparison A4 makes, asked again of the mounted shadow: A4 proved
    the template was untouched, and this proves the VIEW in front of it is.
    The token block is the one declared exception, for the reason
    `test_entrance_frames.py` gives there; everything a person looks at is
    byte-identical.
    """
    _doors(doors)

    now = client.get(LOGIN_URL).content.decode()
    was = (HERE / BASELINES[doors]).read_text()

    def outside(document: str) -> tuple[str, str]:
        head, _, rest = document.partition("<style>")
        _, _, tail = rest.partition("</style>")
        return head, tail

    assert outside(now) == outside(was)


def test_hosted_post_is_still_refused(client: Client) -> None:
    """403, and no session — `test_password_door_retired.py`'s property, kept.

    The shadow could have reopened the local password door by accident: a view
    of ours that answered POST would be a second credential store's form with
    a new URL in front of it (ADR ident-4). It does not, because under
    `hosted` the POST is allauth's own refusal and nothing of ours runs.
    """
    response = client.post(LOGIN_URL, {"login": SIGNIN_LOGIN_NAME, "password": SIGNIN_PASSWORD})

    assert response.status_code == 403
    assert "_auth_user_id" not in client.session


def test_hosted_seed_declares_no_login_version() -> None:
    """`None`, and `None` is a VALUE the writer states — the road back.

    A deployment on the hosted page declares that it wants no per-application
    login version at all, and the seed's writer CLEARS one a console edit left
    behind. A shared instance is stamped by no checkout.
    """
    assert zitadel_seed.declared_login_base_uri("https://app.example.test") is None


def test_hosted_logout_keeps_todays_sentence(client: Client) -> None:
    """The page a person meets on the way OUT, unchanged under the default."""
    body = _logout_page(client)

    assert "You will stay signed in to the identity" in body
    assert "Signing back in asks for your password" not in body


def test_the_whole_identity_suite_runs_under_the_default() -> None:
    """The default is declared in the tree, not left to the machine.

    Every case in this app's tests that does not say otherwise runs on
    `hosted`, and that is true because `.env.example` ships the line commented
    and `config/settings/base.py` defaults it — not because a runner happened
    to have the variable unset. `apps/core/tests/test_settings.py` pins the key
    to CLEARED in `PRODUCTION_ENVIRONMENT` for the same reason, and its
    completeness census is what would notice the pin going missing.
    """
    assert django_settings.SIGN_IN_DOOR == "hosted"
    assert "DJB_SIGN_IN_DOOR" in source_text(
        BASE_DIR / "apps" / "core" / "tests" / "test_settings.py"
    )


# --- A5.4 · under `ours`, the password road -----------------------------------


def test_ours_get_renders_the_sign_in_frame(client: Client, ours: None) -> None:
    """J2-a: the frame, in the entrance shell, with the form on it."""
    body = client.get(LOGIN_URL).content.decode()

    assert "<h1>Sign in</h1>" in body
    assert 'name="action" value="password"' in body
    # The hosted door's one-button page is gone from this render entirely.
    assert "login_doors" not in body


def test_ours_the_title_moves_with_the_frame(client: Client, ours: None) -> None:
    """A4's verifier found six frames titled `Sign In`. The door picks it now.

    The pair is the point: `ours` gets the frame's own title, and `hosted` —
    where the door hands nothing in — still gets the words the shell has
    always had, which is the half that keeps the byte-identity above true.
    """
    assert _title(client.get(LOGIN_URL).content.decode()) == "Sign in"


def test_the_title_map_covers_the_frame_vocabulary_and_nothing_else() -> None:
    """Set equality against the directory, so a seventh frame fails HERE.

    The vocabulary is the population of files under
    `templates/account/frames/` (A4's own census). A title map that drifted
    from it would either `KeyError` on a frame the door draws or carry a title
    for a screen nobody renders, and the second one reads as coverage.
    """
    on_disk = {path.stem for path in FRAMES_DIR.glob("*.html")}

    assert set(views.FRAME_TITLES) == on_disk, sorted(set(views.FRAME_TITLES) ^ on_disk)


def test_hosted_keeps_the_shells_own_title(client: Client) -> None:
    """The control for the rider, and the byte-identity's title half."""
    assert _title(client.get(LOGIN_URL).content.decode()) == "Sign In"


def test_ours_a_password_lands_at_the_login_redirect(
    client: Client, door: FakeSignInZitadel, ours: None
) -> None:
    """The whole road: form → seam → allauth's completion → 302, and a session.

    `LOGIN_REDIRECT_URL` rather than a spelled path: where a completed sign-in
    lands is `config/settings/base.py`'s derivation off `PRODUCT_BASE_URL`, and
    a product with a front end sends people somewhere else entirely.
    """
    response = _sign_in(client)

    assert response.status_code == 302, response.content
    assert response["Location"] == django_settings.LOGIN_REDIRECT_URL
    assert client.session.get("_auth_user_id")
    assert User.objects.get(zitadel_sub=SIGNIN_USER_ID).email == SIGNIN_LOGIN_NAME


def test_ours_unverified_address_is_refused_by_the_adapter(
    client: Client, door: FakeSignInZitadel, ours: None
) -> None:
    """The adapter's FIRST check, driven through this door (`adapter.py`).

    The password is right and the platform has not confirmed the mailbox. A
    door that asserted `verified=True` because the check passed would make
    this refusal unreachable — the code would still be there and nothing could
    ever fire it — so the flag is READ off the platform's record and this case
    is what says the read is load-bearing.

    No `User` row is written, which is the half that matters: the refusal is
    before allauth's signup step.
    """
    door.users[SIGNIN_USER_ID]["human"]["email"]["isEmailVerified"] = False

    response = _sign_in(client)

    assert "_auth_user_id" not in client.session
    assert not User.objects.filter(zitadel_sub=SIGNIN_USER_ID).exists()
    assert b"verified" in response.content


def test_ours_existing_person_is_linked_not_duplicated(
    client: Client, door: FakeSignInZitadel, ours: None
) -> None:
    """The adapter's SECOND check: somebody who predates the door keeps one row.

    The seeded owner, an invited person, a superuser — all of them exist
    before their first sign-in, and a door that minted a second account for
    them would leave the memberships on the first one.
    """
    from apps.accounts.services import create_user

    existing = create_user(email=SIGNIN_LOGIN_NAME)

    response = _sign_in(client)

    assert response.status_code == 302, response.content
    assert User.objects.filter(email=SIGNIN_LOGIN_NAME).count() == 1
    existing.refresh_from_db()
    assert existing.zitadel_sub == SIGNIN_USER_ID


def test_ours_records_the_subject_once(client: Client, door: FakeSignInZitadel, ours: None) -> None:
    """The adapter's THIRD check: the join lands, through the one service, once.

    Twice through the door is one row and one subject. A second sign-in that
    re-pointed or duplicated the join would be the column the whole identity
    model is keyed on becoming a per-session fact.
    """
    assert _sign_in(client).status_code == 302
    client.logout()
    cache.clear()
    assert _sign_in(client).status_code == 302

    assert list(User.objects.values_list("zitadel_sub", flat=True)) == [SIGNIN_USER_ID]


def test_ours_next_survives_the_ceremony(
    client: Client, door: FakeSignInZitadel, ours: None
) -> None:
    """A same-origin `?next=` is where the person lands, not the default."""
    response = _sign_in(client, query="?next=/welcome/")

    assert response.status_code == 302
    assert response["Location"] == "/welcome/"


def test_ours_a_foreign_next_is_dropped(
    client: Client, door: FakeSignInZitadel, ours: None
) -> None:
    """An off-origin `?next=` lands at the default, silently and on purpose.

    An open redirect on the sign-in page is the classic phishing hop: the link
    looks like ours, the person really does sign in, and the browser is then
    handed to somebody else's host carrying whatever the query said. The
    validation is allauth's own `get_next_redirect_url`, used rather than
    re-implemented, which is why this is a test of the door HANDING IT OVER.
    """
    response = _sign_in(client, query="?next=https://evil.example/harvest")

    assert response.status_code == 302
    assert response["Location"] == django_settings.LOGIN_REDIRECT_URL


def test_ours_an_unknown_action_is_a_400(client: Client, ours: None) -> None:
    """Not a re-rendered form: there is no browser road that sends one.

    A page that answered a typo'd action with the sign-in screen would look
    like a refusal — the person reads "that didn't work" and tries again —
    while the truth is that nothing was checked at all.
    """
    response = client.post(LOGIN_URL, {"action": "teleport"})

    assert response.status_code == 400


def test_ours_a_wrong_password_reads_the_one_sentence(
    client: Client, door: FakeSignInZitadel, ours: None
) -> None:
    """J7: one sentence for a wrong password, an unknown address and a lockout.

    And the standing remedy under it, printed on every refusal — which is what
    lets a locked person read their road out without a "locked" sentence
    existing anywhere to be used as an oracle over which addresses have been
    attacked.
    """
    response = _sign_in(client, password=WRONG_PASSWORD)
    body = response.content.decode()

    assert response.status_code == 200
    assert _note(body) == "That email and password don't match. Try again."
    assert "ask whoever runs your organization to reset your sign-in" in body
    assert "locked" not in body.lower()
    assert "_auth_user_id" not in client.session


def test_ours_an_unknown_address_reads_the_same_sentence(
    client: Client, door: FakeSignInZitadel, ours: None
) -> None:
    """The A9 posture: nothing on the page says whether an account exists."""
    response = client.post(
        LOGIN_URL,
        {"action": "password", "email": "nobody@yourco.test", "password": SIGNIN_PASSWORD},
    )

    assert _note(response.content.decode()) == "That email and password don't match. Try again."


def test_ours_an_outage_answers_503_and_not_a_refusal(
    client: Client, door: FakeSignInZitadel, ours: None
) -> None:
    """Fail-closed rule 3, rendered: our expired credential is not their fault.

    A 403 from Zitadel is about the machine PAT, and answering "that password
    was wrong" for it tells every person in the deployment that they forgot
    their password on the same morning. The status is 503 because the page IS
    an outage — a monitor reading 200s would see a door that is down as a door
    that is busy.
    """
    door.refusals = [(403, "AUTH-AWfge")]

    response = _sign_in(client)

    assert response.status_code == 503
    assert _note(response.content.decode()).startswith("We couldn't reach the sign-in service")


def test_ours_an_unconfigured_client_is_an_outage_and_not_a_traceback(
    client: Client, door: FakeSignInZitadel, ours_unconfigured: None
) -> None:
    """Our door turned on in a deployment that never pasted its client id.

    An empty `ZITADEL_CLIENT_ID` disables the provider entirely rather than
    half-configuring it (`config/settings/base.py`), so allauth has nothing
    registered to complete a sign-in through. That is a real state — it is
    what a fresh clone that flipped the setting has — and the two wrong
    answers are a 500 with a traceback and, far worse, a session minted
    around a provider nobody configured. The right one is the outage sentence,
    which is also what A5.7's configured checkout is a criterion about.
    """
    response = _sign_in(client)

    assert response.status_code == 503
    assert _note(response.content.decode()).startswith("We couldn't reach the sign-in service")
    assert "_auth_user_id" not in client.session


def test_ours_the_throttle_answers_429_with_its_own_sentence(
    client: Client, door: FakeSignInZitadel, ours: None
) -> None:
    """Our limit, in front of Zitadel's lockout, and it does not count down."""
    limit = int(django_settings.SIGNIN_THROTTLE_PER_MINUTE)
    for _ in range(limit):
        _sign_in(client, password=WRONG_PASSWORD)

    response = _sign_in(client, password=WRONG_PASSWORD)

    assert response.status_code == 429
    assert _note(response.content.decode()) == "Too many tries. Wait a minute and try again."


@pytest.mark.parametrize("kind", sorted(set(FactorKind) - {FactorKind.TOTP}))
def test_ours_a_factor_reads_the_sentence_and_never_hands_off(
    client: Client, door: FakeSignInZitadel, ours: None, kind: FactorKind
) -> None:
    """A6.3's `kind_unanswerable` row, one case per kind, with the no-302 control.

    A population rather than an example, and the population is **every kind
    this deployment cannot answer**: an emailed code on an instance with no
    mail sender (the fake's default, and a fresh stack's state), a texted code
    nothing here can promise, and the two whose browser ceremony is design J6.
    An authenticator app is the one kind that reaches a form, and it has its
    own tests below.

    The hand-off is the thing being refused: with login v2 declared on the
    application the hosted page redirects straight back here, so sending a
    person there is a loop they can only leave by clearing cookies (K10).

    The sentence names what the account signs in WITH, in words a person uses,
    and never "MFA", "2FA", "U2F" or "WebAuthn" (design J7's must-not column).
    """
    door.auth_methods.append(_zitadel_name_for(kind))

    response = _sign_in(client)
    body = response.content.decode()

    assert response.status_code == 200
    assert "/ui/login" not in body
    assert not str(response.get("Location", ""))
    assert _note(body) == views.KIND_SENTENCES[kind]
    for banned in ("MFA", "2FA", "U2F", "WebAuthn"):
        assert banned not in _on_the_face(body), banned
    assert "_auth_user_id" not in client.session


def test_ours_a_factor_step_closes_the_ceremony_it_cannot_finish(
    client: Client, door: FakeSignInZitadel, ours: None
) -> None:
    """ADR ident-10 at the door: every session this deployment opens, it closes.

    The dead end above is a place the person stops, and a door that simply
    rendered a sentence would leave a ten-minute half-authenticated session on
    somebody else's server for every person it cannot land — one per try, and
    the tries are exactly the population that is about to try again. Driven on
    a security key rather than on an authenticator app because A6 gave the
    second one a road: the property is about the kinds that still stop here.
    """
    door.auth_methods.append("AUTHENTICATION_METHOD_TYPE_U2F")

    _sign_in(client)

    assert door.opened_sessions, "the ceremony never started"
    assert door.closed_sessions == door.opened_sessions
    assert "accounts.signin.ceremony" not in client.session


def test_ours_an_enrolment_step_draws_the_enrolment_frame(
    client: Client, door: FakeSignInZitadel, ours: None
) -> None:
    """A5's other dead end, replaced by the road A6 built. **The rung's diff, in one test.**

    The org asks for a second step and this person has none, and at A5 that
    was a sentence saying so. It is now frame J2-c: the design's own words, a
    symbol drawn from the platform's URI, and the secret in text for a person
    whose laptop has no camera.
    """
    door.login_settings = {"forceMfa": True, "mfaInitSkipLifetime": "0s"}

    response = _sign_in(client)
    body = response.content.decode()

    assert response.status_code == 200
    assert "<h1>Set up two-factor</h1>" in body
    assert _title(body) == "Set up two-factor"
    assert "Your organization asks for a second step when you sign in." in body
    assert "<svg" in body
    assert "ENROLSECRET" in body
    assert "accounts.signin.ceremony" in client.session, "the enrolment needs the ceremony"


def _zitadel_name_for(kind: FactorKind) -> str:
    """Zitadel's own name for one of the seam's five kinds.

    Read out of the seam's translation map rather than spelled here: that
    mapping is the one place the platform's vocabulary is turned into ours,
    and a second copy in a test is a copy that agrees until the build renames
    something.
    """
    return next(name for name, member in ZITADEL_FACTOR_NAMES.items() if member is kind)


# --- A5.5 · the seed, the audit and the invite branch on the door -------------


def test_ours_the_seed_declares_the_login_base_uri(settings: Any) -> None:
    """The declaration Zitadel appends `/login` to, and it is our entrance.

    `<base>/accounts` — the directory `reverse("account_login")` already
    answers under — so the URL the identity platform sends people to is the
    URL this deployment serves, and not a 404 on our own host with no remedy
    on it (the shape that locked the consumer's owner out).
    """
    settings.SIGN_IN_DOOR = "ours"

    declared = zitadel_seed.declared_login_base_uri("https://app.example.test")

    assert declared == "https://app.example.test/accounts"
    assert reverse("account_login").startswith(f"{zitadel_seed.LOGIN_BASE_PATH}/")


def test_the_declaration_is_computed_in_one_place_and_read_in_three() -> None:
    """The seed WRITES it, the audit JUDGES against it, the reconciler closes it.

    One spelling, three readers — which is what stops the audit coming to
    disagree with the writer about what is declared, and it is the property
    that makes the withdrawal road real: the same function answers `None`
    under `hosted`, and the writer clears on `None`.
    """
    readers = [
        BASE_DIR / "apps/accounts/management/commands/zitadel_audit.py",
        BASE_DIR / "apps/accounts/management/commands/zitadel_reconcile.py",
    ]

    for path in readers:
        assert "declared_login_base_uri" in source_text(path), path


def test_ours_the_audit_says_the_declaration_is_v2(
    door: FakeSignInZitadel, settings: Any, capsys: Any
) -> None:
    """The audit's applications section, under our door, names v2 and the URI.

    Driven through the command rather than the function: the line an operator
    reads is the artifact, and a judgement that agreed in Python while
    printing something else would be a verdict nobody can act on.
    """
    settings.PUBLIC_BASE_URL = "http://localhost:8000"
    settings.SIGN_IN_DOOR = "ours"
    call_command("zitadel_seed", "--skip-user")
    capsys.readouterr()

    call_command("zitadel_audit")
    out = str(capsys.readouterr().out)

    line = next(line for line in out.splitlines() if "loginVersion" in line)
    assert "v2 at http://localhost:8000/accounts" in line, line
    assert line.strip().startswith("agrees"), line


def test_hosted_the_audit_says_the_declaration_is_none(
    door: FakeSignInZitadel, settings: Any, capsys: Any
) -> None:
    """The control, and it is the DEFAULT half: no declaration, and agreement.

    A deployment on the hosted page writes nothing to a feature somebody else
    owns, and the audit says so in the same line rather than going quiet about
    the field.
    """
    settings.PUBLIC_BASE_URL = "http://localhost:8000"
    call_command("zitadel_seed", "--skip-user")
    capsys.readouterr()

    call_command("zitadel_audit")
    out = str(capsys.readouterr().out)

    line = next(line for line in out.splitlines() if "loginVersion" in line)
    assert "none (the identity platform's own page)" in line, line


def test_ours_the_invite_url_is_our_page(settings: Any) -> None:
    """The invited person's first screen is ours, carrying the platform's query.

    The parameter NAMES are Zitadel's (`userID`, `code`), deliberately: an
    operator comparing the two links sees one tail, and the invite road reads
    what the platform minted rather than a second spelling of it.
    """
    settings.SIGN_IN_DOOR = "ours"
    settings.PUBLIC_BASE_URL = "https://app.example.test"

    url = zitadel.invite_url(user_id="5001", code="ABC123")

    assert url == f"https://app.example.test{reverse('account_login')}?userID=5001&code=ABC123"


def test_hosted_the_invite_url_is_the_platforms_page(settings: Any) -> None:
    """The default half, unchanged: `INVITE_PATH` at the issuer."""
    settings.ZITADEL_ISSUER = "https://auth.example.test"

    url = zitadel.invite_url(user_id="5001", code="ABC123")

    assert url == f"https://auth.example.test{zitadel.INVITE_PATH}?userID=5001&code=ABC123"


def test_ours_the_logout_sentence_is_about_our_session(client: Client, ours: None) -> None:
    """J5: under our door there is no platform browser session left behind.

    Our page opens a Session API session for the ceremony and closes it at
    every exit, and there is no `{baseUri}/logout` leg to render — so the
    hosted sentence would be a promise about somebody else's cookie that this
    deployment does not make.
    """
    body = _logout_page(client)

    assert "This ends your session. Signing back in asks for your password" in body
    assert "You will stay signed in to the identity" not in body


# --- A5.8 · what must not have moved ------------------------------------------


def test_the_oauth_resource_server_was_not_touched() -> None:
    """`oauth.py` is the MCP door's token validator and is no part of this.

    Named as a negative because the two modules are one `import` apart and a
    sign-in door that reached into the resource server would be the browser
    road and the machine road sharing a decision neither of them makes.
    """
    tree = source_tree(BASE_DIR / "apps" / "accounts" / "oauth.py")
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert "SIGN_IN_DOOR" not in source_text(BASE_DIR / "apps" / "accounts" / "oauth.py")
    assert not [name for name in imported if "signin" in name or name.endswith(".views")], imported


# --- A7 · J1, the invite road (design C-11, J1-a) -----------------------------
#
# The first screen of the product for the first person in a deployment, and the
# only screen where somebody types a password they are choosing rather than one
# they already have. Everything below is driven through the DOOR, over the wire,
# because the property each case is about is what a person reading the page
# sees — and because the road's one security rule is invisible from the seam:
# MEASURED on the pinned build (2026-09-19), the machine PAT can set ANY
# person's password with no invite code at all, so the verify is not Zitadel
# checking a credential, it is OUR seam checking one before it makes a write
# Zitadel would happily make on a bare user id.
#
# WATCH F6 is what the road below closes. Measured on the baseline, the hosted
# ends `302 Location: /ui/console/` — the first human of the deployment
# deposited in the identity platform's console, which `setup.sh` tells them
# never to use. Under `ours` the same walk ends at `LOGIN_REDIRECT_URL`.

#: The password an invited person chooses in these tests. Declared once, with
#: the pragma on its own line, for the reason `WRONG_PASSWORD` is.
CHOSEN_PASSWORD = "Fresh-Horse-Battery-9!"  # pragma: allowlist secret

#: One the pinned build's own policy refuses (`minLength` 8, M11).
TOO_SHORT = "abc"  # pragma: allowlist secret


def _invite_query(instance: FakeInvitedZitadel, **extra: str) -> str:
    """The link's own tail — `userID` and `code`, Zitadel's spelling (A5.5)."""
    pairs = {"userID": instance.invited_id, "code": instance.invited_code, **extra}
    return "?" + "&".join(f"{name}={value}" for name, value in pairs.items())


def _open_the_link(client: Client, instance: FakeInvitedZitadel, **extra: str) -> Any:
    return client.get(f"{LOGIN_URL}{_invite_query(instance, **extra)}")


def _choose(
    client: Client,
    instance: FakeInvitedZitadel,
    *,
    password: str = CHOSEN_PASSWORD,
    **extra: str,
) -> Any:
    """Submit the frame. The form has no `action=`, so the query rides along."""
    return client.post(
        f"{LOGIN_URL}{_invite_query(instance, **extra)}",
        {"action": "invite", "password": password},
    )


def _frame(body: str) -> str:
    """Which frame the door drew, read off the title it drew it with (A5's rider)."""
    return _title(body)


def test_an_invited_person_sets_a_password_and_lands(
    client: Client, invited_instance: FakeInvitedZitadel, ours: None
) -> None:
    """A7.2 · the road, end to end, and the landing is the PRODUCT.

    The whole of J1 step 3 in one case: the link opens the frame, the password
    is set through the two measured calls, the person is checked against the
    password they just chose, and the browser is sent to `LOGIN_REDIRECT_URL`
    — never to the identity platform's console, which is where the hosted road
    ends (WATCH F6, `302 Location: /ui/console/`).
    """
    opened = _open_the_link(client, invited_instance)
    assert opened.status_code == 200, opened.status_code
    assert _frame(opened.content.decode()) == views.FRAME_TITLES["choose_your_password"]

    landed = _choose(client, invited_instance)

    assert landed.status_code == 302, landed.content
    assert landed["Location"] == django_settings.LOGIN_REDIRECT_URL
    assert invited_instance.set_passwords[invited_instance.invited_id] == CHOSEN_PASSWORD
    assert User.objects.filter(email=invited_instance.invited_login_name).exists()
    assert "/ui/console/" not in landed["Location"]


def test_the_address_shown_is_the_users_not_the_urls(
    client: Client, invited_instance: FakeInvitedZitadel, ours: None
) -> None:
    """A7.2 · the sentence names whoever the CODE was minted for.

    A link is something anybody can edit, and the sentence on this frame is
    what tells a person whose account they are about to set a password on. So
    the address is read back off the platform's own record for the user id in
    the link, and an `email=` somebody appended is not on the page at all.
    """
    planted = "mallory@evil.test"

    opened = _open_the_link(client, invited_instance, email=planted)

    body = opened.content.decode()
    assert invited_instance.invited_login_name in body
    assert planted not in body


def test_the_rule_sentence_is_read_from_the_complexity_policy(
    client: Client, invited_instance: FakeInvitedZitadel, ours: None
) -> None:
    """A7.2 · M11 on the page, and it MOVES when the policy does.

    Two worlds rather than one assertion against today's default: a sentence
    composed from a fixed dictionary and a sentence typed into the template
    are indistinguishable until the policy changes underneath them.
    """
    default = _open_the_link(client, invited_instance).content.decode()
    assert "At least 8 characters" in default

    invited_instance.password_rules = {
        "minLength": "14",
        "requiresUppercase": False,
        "requiresLowercase": False,
        "requiresNumber": False,
        "requiresSymbol": False,
    }
    tightened = _open_the_link(client, invited_instance).content.decode()

    assert "At least 14 characters" in tightened
    assert "Nothing else is required" in tightened
    assert "At least 8 characters" not in tightened


def test_a_policy_that_cannot_be_read_drops_the_sentence_rather_than_guessing(
    client: Client, invited_instance: FakeInvitedZitadel, ours: None
) -> None:
    """The frame's own rule: no policy handed in, no sentence.

    A number printed here that the platform would not enforce is worse than
    no number: the person meets a refusal the page told them could not happen.
    """
    invited_instance.password_rules = {}

    body = _open_the_link(client, invited_instance).content.decode()

    assert _frame(body) == views.FRAME_TITLES["choose_your_password"]
    assert "At least" not in _on_the_face(body)


def test_the_expiry_sentence_is_the_platforms_own_lifetime(
    client: Client, invited_instance: FakeInvitedZitadel, ours: None
) -> None:
    """C2's 259200s, as a date the person can act on."""
    from datetime import UTC, datetime, timedelta

    body = _open_the_link(client, invited_instance).content.decode()

    expected = (datetime.now(tz=UTC) + timedelta(seconds=259200)).strftime("%-d %B")
    assert f"This link stops working on {expected}." in body


def test_a_used_or_expired_link_reads_the_invite_gone_sentence(
    client: Client, invited_instance: FakeInvitedZitadel, ours: None
) -> None:
    """A7.2 · failure state one. The code is single-use, measured.

    Driven as the person would meet it: the code is spent by a first,
    successful submission, and the second one is the same link opened again
    from an email somebody kept.
    """
    _choose(client, invited_instance)
    client.logout()
    invited_instance.invited_methods = []

    again = _choose(client, invited_instance)

    assert again.status_code == 200, again.status_code
    assert _note(again.content.decode()) == (
        "This link has already been used or has expired. Ask whoever invited you for a fresh one."
    )


def test_a_password_the_policy_refuses_reads_the_rule_it_broke(
    client: Client, invited_instance: FakeInvitedZitadel, ours: None
) -> None:
    """A7.2 · failure state two, and the frame is still there to try again on."""
    refused = _choose(client, invited_instance, password=TOO_SHORT)

    body = refused.content.decode()
    assert refused.status_code == 200, refused.status_code
    assert _frame(body) == views.FRAME_TITLES["choose_your_password"]
    assert _note(body) == "That password doesn't meet the rules: Password is too short."
    assert invited_instance.invited_id not in invited_instance.set_passwords


def test_an_already_initialised_person_is_sent_to_sign_in(
    client: Client, invited_instance: FakeInvitedZitadel, ours: None
) -> None:
    """A7.2 · failure state three: somebody who already has credentials here.

    The sign-in FORM under the sentence, not the password-choosing one — the
    act they need is the one they can actually do. And the address is not
    prefilled: this page is reachable by anybody holding a user id, and
    confirming an address for one is an oracle the A9 posture refuses.
    """
    invited_instance.invited_methods = ["AUTHENTICATION_METHOD_TYPE_PASSWORD"]

    opened = _open_the_link(client, invited_instance)

    body = opened.content.decode()
    assert _frame(body) == views.FRAME_TITLES["sign_in"]
    assert _note(body) == "This link was already used. Sign in instead."
    assert invited_instance.invited_login_name not in body


def test_the_password_is_never_written_without_a_verified_code(
    client: Client, invited_instance: FakeInvitedZitadel, ours: None
) -> None:
    """The road's one security rule, and the reason it is OURS to keep.

    MEASURED: `POST /v2/users/{id}/password` on the machine PAT succeeds with
    no code whatsoever, so nothing at the platform stops a door that skipped
    the verify from setting a stranger's password off a guessed user id. The
    verify is therefore the whole authorisation, and this case drives a wrong
    code and asserts the WRITE was never attempted — not merely that the page
    said no.
    """
    refused = _choose(client, invited_instance, code="ZZZZZZ")

    wrote = [
        call
        for call in invited_instance.whole_calls
        if call[0] == "POST" and call[1].endswith("/password")
    ]
    assert not wrote, wrote
    assert _note(refused.content.decode()).startswith("This link has already been used")


def test_an_outage_on_the_invite_road_is_503_and_not_a_refusal(
    client: Client, invited_instance: FakeInvitedZitadel, ours: None
) -> None:
    """Fail-closed rule 3 on this road: a refusal aimed at OUR credential.

    A 403 is the machine PAT losing a role, and telling the invited person
    their link is dead for it would send them back to whoever invited them
    over a fault on our side.
    """
    invited_instance.refusals = [(403, "AUTH-AWfge")]

    answered = _choose(client, invited_instance)

    assert answered.status_code == 503, answered.status_code
    assert _note(answered.content.decode()) == views.SENTENCES[SignInOutcome.UNAVAILABLE]


def test_no_zitadel_error_id_reaches_the_page(
    client: Client, invited_instance: FakeInvitedZitadel, ours: None
) -> None:
    """A7.2 · the sweep. Every failure state of this road, over the wire.

    The design's "must not" column for J1-a's three is one line — *echo
    Zitadel's error id* — and it is a sweep rather than three assertions
    because the ids are exactly what a `str(error)` fallback would leak, and a
    fallback is added on the branch nobody wrote a case for.
    """
    ids = ("COMMAND-Wgn4q", "COMMAND-F5g2h", "DOMAIN-HuJf6", "AUTH-AWfge", "QUERY-Dfbg2")

    bodies = [
        _choose(client, invited_instance, code="ZZZZZZ").content.decode(),
        _choose(client, invited_instance, password=TOO_SHORT).content.decode(),
        _open_the_link(client, invited_instance, userID="404404404").content.decode(),
    ]
    invited_instance.refusals = [(403, "AUTH-AWfge")]
    bodies.append(_choose(client, invited_instance).content.decode())

    for body in bodies:
        face = _on_the_face(body)
        for error_id in ids:
            assert error_id not in face, (error_id, face[:400])
        assert "zitadel" not in face.lower()


def test_hosted_ignores_the_invite_query_entirely(
    client: Client, invited_instance: FakeInvitedZitadel
) -> None:
    """A7.5 · the default door, unmoved. Byte-identical to today's page.

    The query is the identity platform's own link tail, and under `hosted`
    that link does not point here at all — so a page that started rendering a
    password-choosing frame for it would be the invite road leaking into
    every deployment that never turned the setting.
    """
    plain = client.get(LOGIN_URL)
    with_query = _open_the_link(client, invited_instance)

    assert with_query.status_code == 200, with_query.status_code
    assert with_query.content == plain.content


def test_ours_a_sign_in_page_with_no_link_is_untouched(
    client: Client, invited_instance: FakeInvitedZitadel, ours: None
) -> None:
    """A5.4's page is still A5.4's page: the road opens only on a whole link.

    The frame alone is too weak an assertion here, and it was paid for:
    a first cut tested the PAIR for truthiness, and a 2-tuple is
    truthy whatever is in it, so every GET took the invite road, dialled the
    platform for a user id of `""`, read the 404 back as a dead link and drew
    the sign-in frame **with an "ask whoever invited you" note on it**. The
    frame was right and the page was wrong. So: no alert, and no call.
    """
    for query in ("", f"?userID={SIGNIN_INVITED_USER_ID}", f"?code={SIGNIN_INVITE_CODE}"):
        invited_instance.whole_calls.clear()
        answered = client.get(f"{LOGIN_URL}{query}")
        body = answered.content.decode()

        assert answered.status_code == 200, query
        assert _frame(body) == views.FRAME_TITLES["sign_in"], query
        assert 'class="alert"' not in body, query
        assert invited_instance.whole_calls == [], (query, invited_instance.whole_calls)


# --- A8 · Mode A, the OIDC round trip on our page (design C-10) ---------------
#
# The person did not come here on purpose: an app sent them. With
# `loginVersion` declared on that application the platform's authorize answers
# `302 {baseUri}/login?authRequest=V2_…` — MEASURED live on 2026-09-19 — and
# what finishes the journey is a code for the app, never a session here.
#
# Every case is driven through the door because the property each is about is
# what the browser does next: a 302 to the client's own callback, or a page
# with a sentence on it. Nothing here dials the platform; the live round trip
# is the measurement pasted in the rung's report and the verifier's own walk.


def _mode_a_query(fake: FakeModeAZitadel, **extra: str) -> str:
    pairs = {"authRequest": fake.auth_request_id, **extra}
    return "?" + "&".join(f"{name}={value}" for name, value in pairs.items())


def _journey(client: Client, fake: FakeModeAZitadel, **extra: str) -> Any:
    return client.get(f"{LOGIN_URL}{_mode_a_query(fake, **extra)}")


def _answer(
    client: Client,
    fake: FakeModeAZitadel,
    *,
    password: str = SIGNIN_PASSWORD,
    **extra: str,
) -> Any:
    return client.post(
        f"{LOGIN_URL}{_mode_a_query(fake, **extra)}",
        {"action": "password", "email": SIGNIN_LOGIN_NAME, "password": password},
    )


def test_mode_a_round_trip_lands_through_the_callback(
    client: Client, mode_a_instance: FakeModeAZitadel, ours: None
) -> None:
    """A8.2 · the whole of it: our page, our ceremony, the client's code.

    Four properties in one drive, because they are one journey and a case per
    property would let three of them pass on a road the fourth never took:
    the page draws OUR sign-in frame rather than the platform's; the ceremony
    is the ordinary one; the finalize happens exactly once; and the browser is
    sent to the CLIENT's registered callback with a code — not to
    `LOGIN_REDIRECT_URL`, which would be this product signing them in and the
    app that sent them waiting for ever.
    """
    opened = _journey(client, mode_a_instance)
    assert opened.status_code == 200, opened.status_code
    assert _frame(opened.content.decode()) == views.FRAME_TITLES["sign_in"]

    landed = _answer(client, mode_a_instance)

    assert landed.status_code == 302, landed.content
    assert landed["Location"].startswith(mode_a_instance.callback_uri)
    assert "code=mode-a-code-" in landed["Location"]
    assert landed["Location"] != django_settings.LOGIN_REDIRECT_URL
    assert [kind for _r, _s, kind, _d in mode_a_instance.finalizes] == ["session"]


def test_a_finalized_session_is_left_for_the_client_to_spend(
    client: Client, mode_a_instance: FakeModeAZitadel, ours: None
) -> None:
    """Mode A's one exception to ADR ident-10, and the LIVE walk is what found it.

    Every other exit of the seam closes the Zitadel session it opened. This
    road cannot: the finalize answers a callback URL with a code on it, the
    CLIENT spends that code afterwards on its own connection, and Zitadel
    validates the session the code was minted against at that moment. With
    the session closed on our way out the exchange answers

        400 {"error":"invalid_request",
             "error_description":"Errors.Session.Terminated"}

    which is what `scripts/oauth_demo.py` answered on the first live drive of
    this road — after a sign-in that was perfect from both ends and that
    every in-suite drive passed. A door test cannot see a client's later
    exchange, so what is asserted here is the PRECONDITION for it: the
    session was opened, finalized against, and is still there.
    """
    landed = _answer(client, mode_a_instance)

    assert landed.status_code == 302, landed.content
    finalized = [
        session for _r, session, kind, _d in mode_a_instance.finalizes if kind == "session"
    ]
    assert finalized, mode_a_instance.finalizes
    assert finalized[0] in mode_a_instance.opened_sessions
    assert finalized[0] not in mode_a_instance.closed_sessions, mode_a_instance.closed_sessions
    assert finalized[0] in mode_a_instance.sessions
    # And the ceremony is gone even though the session is not: the token is
    # the only handle on it and it does not outlive this request.
    assert client.session.get("accounts.signin.ceremony") is None


def test_every_other_road_still_closes_its_session(
    client: Client, mode_a_instance: FakeModeAZitadel, ours: None
) -> None:
    """The other direction of the exception, so it stays an exception.

    ADR ident-10 is unchanged everywhere a client is not waiting on a code:
    the ordinary password road, and a Mode A ceremony whose finalize was
    REFUSED (there is no code, so there is nothing for anybody to spend).
    Both are driven here, because a `close=` that quietly became `False` for
    everything would leave a half-authenticated session on somebody else's
    server for every sign-in in the deployment.
    """
    plain = _sign_in(client)
    assert plain.status_code == 302, plain.content
    assert mode_a_instance.opened_sessions == mode_a_instance.closed_sessions

    client.logout()
    cache.clear()
    mode_a_instance.refusals = [(403, "AUTH-AWfge")]
    refused = _answer(client, mode_a_instance)

    assert refused.status_code == 503, refused.status_code
    assert mode_a_instance.opened_sessions == mode_a_instance.closed_sessions


def test_a_refused_ceremony_answers_the_auth_request_with_an_error_reason(
    client: Client, mode_a_instance: FakeModeAZitadel, ours: None
) -> None:
    """A8.2 · a dead end is the CLIENT's news too, in M4's enum spelling.

    A person whose organisation asks for a step this page cannot ask for is in
    the middle of somebody else's journey. Left on our page they are a dead
    end inside a window the app may not own; answered, the app gets
    `error=access_denied` at its own redirect URI and can say something.

    The spelling is the criterion. MEASURED: `ERROR_REASON_ACCESS_DENIED`
    reaches the client as `access_denied`, and the RFC lowercase spelling a
    reader of the OAuth spec would reach for is accepted with a 200 and
    degrades to `server_error` — a client told the authorization server broke,
    for a person who simply could not finish.
    """
    mode_a_instance.auth_methods.append("AUTHENTICATION_METHOD_TYPE_OTP_SMS")

    answered = _answer(client, mode_a_instance)

    assert answered.status_code == 302, answered.content
    assert answered["Location"].startswith(mode_a_instance.callback_uri)
    assert "error=access_denied" in answered["Location"]
    assert "server_error" not in answered["Location"]
    sent = [detail for _r, _s, kind, detail in mode_a_instance.finalizes if kind == "error"]
    assert sent == [zitadel.REFUSE_ACCESS_DENIED], sent


def test_a_wrong_password_does_not_burn_the_journey(
    client: Client, mode_a_instance: FakeModeAZitadel, ours: None
) -> None:
    """The other half of the case above, and the reason it is not "any refusal".

    A wrong password is retryable. Answering the auth request for one would
    end a journey the person was one keystroke from finishing, and send them
    back to the app to start the whole dance again.
    """
    refused = _answer(client, mode_a_instance, password=WRONG_PASSWORD)

    assert refused.status_code == 200, refused.status_code
    assert _note(refused.content.decode()) == views.SENTENCES[SignInOutcome.REFUSED]
    assert mode_a_instance.finalizes == []

    # And the second try, with the right one, still lands the journey.
    cache.clear()
    landed = _answer(client, mode_a_instance)
    assert landed.status_code == 302, landed.content
    assert "code=mode-a-code-" in landed["Location"]


def test_an_auth_request_that_is_gone_reads_the_sentence_and_never_a_500(
    client: Client, mode_a_instance: FakeModeAZitadel, ours: None
) -> None:
    """A8.2 · `request_gone`, on the READ and on the WRITE.

    Three platform error ids mean this (`QUERY-Thee9` on the read,
    `COMMAND-jae5P` on the write, `COMMAND-Sx208nt` for one already answered —
    all measured), and one sentence covers all three because from where the
    person stands they are one fact. The sentence names the APP rather than
    this product: they did not come here on purpose.
    """
    gone = client.get(f"{LOGIN_URL}?authRequest=V2_000000000000000000")

    assert gone.status_code == 200, gone.status_code
    _reads_as_expired(gone)

    # And on the way out: an auth request answered once is answered forever.
    _answer(client, mode_a_instance)
    client.logout()
    cache.clear()
    again = _answer(client, mode_a_instance)
    assert again.status_code == 200, again.status_code
    _reads_as_expired(again)


def _reads_as_expired(response: Any) -> None:
    """The `request_gone` page: A11's seventh frame, its words, and NO FORM.

    The form's absence is the assertion that matters. Six frames all carried
    one, so A8 answered this state on the sign-in frame — which is the
    design's own "must not" for it: *render the form as if a plain sign-in
    would land somewhere useful*. The words are read against the door's one
    spelling of the sentence, so the frame and the constant cannot drift.
    """
    body = response.content.decode()
    assert _frame(body) == views.FRAME_TITLES["link_expired"], _frame(body)
    assert "<form" not in body, body
    head, _stop, move = views.SENTENCES[SignInOutcome.REQUEST_GONE].partition(". ")
    assert f"<h1>{head}.</h1>" in body, body
    assert move in body, body


def test_no_sign_up_is_said_rather_than_drawn(
    client: Client, mode_a_instance: FakeModeAZitadel, ours: None
) -> None:
    """A8.2 · `no_sign_up`. A client may ask for a registration screen; there is none.

    ADR accounts-1: people arrive by invitation and there has never been a
    signup door. The sentence says how they actually arrive, and the sign-in
    form stays under it — somebody who WAS invited can finish right here
    rather than being bounced for asking the wrong question.
    """
    mode_a_instance.prompts = ["PROMPT_CREATE"]

    opened = _journey(client, mode_a_instance)

    body = opened.content.decode()
    assert opened.status_code == 200, opened.status_code
    assert _note(body) == (
        "People arrive here by invitation. Sign in with the address you were invited at."
    )
    assert "<form" in body
    for forbidden in ("sign up", "signup", "register", "create an account"):
        assert forbidden not in _on_the_face(body).lower(), forbidden


def test_the_clients_login_hint_prefills_the_address(
    client: Client, mode_a_instance: FakeModeAZitadel, ours: None
) -> None:
    """The app already knows who it sent; making them type it again is friction."""
    mode_a_instance.login_hint = SIGNIN_LOGIN_NAME

    body = _journey(client, mode_a_instance).content.decode()

    assert f'value="{SIGNIN_LOGIN_NAME}"' in body


def test_mode_a_survives_the_platforms_missing_trailing_slash(
    client: Client, mode_a_instance: FakeModeAZitadel, ours: None
) -> None:
    """MEASURED, and the one surprise in Mode A.

    The platform composes the authorize redirect as
    `{baseUri}/login?authRequest=V2_…` — **no trailing slash** — and our mount
    is `/accounts/login/`. `APPEND_SLASH` answers the 301 and carries the
    query, so the journey works at the cost of one hop. A deployment that
    turned `APPEND_SLASH` off would lose every OIDC sign-in and nothing else,
    which is the kind of silence this case exists to break.
    """
    hopped = client.get(f"/accounts/login{_mode_a_query(mode_a_instance)}")

    assert hopped.status_code == 301, hopped.status_code
    assert hopped["Location"] == f"{LOGIN_URL}{_mode_a_query(mode_a_instance)}"
    landed = client.get(hopped["Location"])
    assert landed.status_code == 200, landed.status_code
    assert _frame(landed.content.decode()) == views.FRAME_TITLES["sign_in"]


def test_a_finalize_our_credential_cannot_make_is_an_outage_not_an_expiry(
    client: Client, mode_a_instance: FakeModeAZitadel, ours: None
) -> None:
    """M2's 403, on the one road it can reach a person.

    A deployment whose machine user lacks `IAM_LOGIN_CLIENT` signs everybody
    in perfectly and then cannot hand a single one of them back — measured,
    `403 AUTH-AWfge`. Read as "your link expired" that is a person sent round
    the journey again for ever; read as an outage it is a 503 and an operator
    with something to look at.
    """
    mode_a_instance.refusals = [(403, "AUTH-AWfge")]

    answered = _answer(client, mode_a_instance)

    assert answered.status_code == 503, answered.status_code
    assert _note(answered.content.decode()) == views.SENTENCES[SignInOutcome.UNAVAILABLE]


def test_no_zitadel_error_id_reaches_a_mode_a_page(
    client: Client, mode_a_instance: FakeModeAZitadel, ours: None
) -> None:
    """The A7 sweep, re-run over Mode A's own failure states."""
    ids = ("QUERY-Thee9", "COMMAND-jae5P", "COMMAND-Sx208nt", "AUTH-AWfge")

    bodies = [client.get(f"{LOGIN_URL}?authRequest=V2_000000000000000000").content.decode()]
    mode_a_instance.refusals = [(403, "AUTH-AWfge")]
    bodies.append(_answer(client, mode_a_instance).content.decode())
    mode_a_instance.refusals = [(500, "QUERY-Thee9")]
    bodies.append(_journey(client, mode_a_instance).content.decode())

    for body in bodies:
        face = _on_the_face(body)
        for error_id in ids:
            assert error_id not in face, (error_id, face[:300])
        assert "zitadel" not in face.lower()


def test_hosted_ignores_an_auth_request_entirely(
    client: Client, mode_a_instance: FakeModeAZitadel
) -> None:
    """A8.5 · the default door, unmoved and byte-identical.

    Under `hosted` no application declares login v2, so the platform never
    sends anybody here with an auth request — and a page that started reading
    one would be Mode A leaking into every deployment that never turned
    the setting.
    """
    plain = client.get(LOGIN_URL)
    with_journey = _journey(client, mode_a_instance)

    assert with_journey.status_code == 200, with_journey.status_code
    assert with_journey.content == plain.content


def test_ours_a_page_with_no_auth_request_dials_nothing(
    client: Client, mode_a_instance: FakeModeAZitadel, ours: None
) -> None:
    """A5.4's page is still A5.4's page — the A7 lesson, re-applied here.

    The invite road paid for this once: a truthiness test on the wrong thing
    made every GET take the new road and dial the platform for an empty id.
    One character of query is the whole difference, so it is asserted rather
    than assumed.
    """
    mode_a_instance.whole_calls.clear()

    answered = client.get(LOGIN_URL)

    body = answered.content.decode()
    assert answered.status_code == 200, answered.status_code
    assert _frame(body) == views.FRAME_TITLES["sign_in"]
    assert 'class="alert"' not in body
    assert mode_a_instance.whole_calls == [], mode_a_instance.whole_calls


# --- A6.1 · the factor faces --------------------------------------------------
#
# The chooser is a POPULATION — the kinds the platform says are ENROLLED
# intersected with the kinds this deployment can DELIVER — and every test here
# changes one member of it and reads the page back. An example-shaped test
# ("a TOTP person sees a code field") would stay green on a door that drew a
# chip for every kind it had heard of.


def _chips(body: str) -> list[tuple[str, str]]:
    """Every CHOOSER chip on the page, as `(action, label)`.

    `Never mind` and `Not now` are drawn as chips too — they are quiet
    secondary controls and the token block has exactly one declaration for
    that shape — so the chooser is the chips whose action names a kind.
    """
    found: list[tuple[str, str]] = []
    for row in re.findall(r'<div class="chips">(.*?)</div>', body, re.S):
        found += [
            (action, html.unescape(label.strip()))
            for action, label in re.findall(
                r'name="action" value="([^"]+)"[^>]*>([^<]*)</button>', row, re.S
            )
            if action.startswith(views.CHIP_ACTION_PREFIX)
        ]
    return found


def _asked(door: FakeSignInZitadel, method: str, path: str) -> bool:
    """Whether the door's ceremony made this call. **`whole_calls`, not `requests`.**

    The measured fake answers its own routes before the base fake's log is
    reached, so `requests` is empty for everything `_measured` handles and an
    assertion against it is green whatever happened.
    """
    return any(call[0] == method and call[1] == path for call in door.whole_calls)


def _lede(body: str) -> str:
    found = re.search(r'<p class="lede">(.*?)</p>', body, re.S)
    assert found is not None, body
    return html.unescape(found.group(1).strip())


def _enrol(door: FakeSignInZitadel, *names: str) -> None:
    """Put these kinds on the fixture person, as Zitadel names them."""
    door.auth_methods = [ZITADEL_PASSWORD_METHOD, *names]


def _answer_code(client: Client, code: str = "") -> Any:
    from apps.accounts.tests.conftest import SIGNIN_FACTOR_CODE

    return client.post(LOGIN_URL, {"action": "code", "code": code or SIGNIN_FACTOR_CODE})


def test_a_totp_user_is_asked_and_lands(
    client: Client, door: FakeSignInZitadel, ours: None
) -> None:
    """J2-a → J2-b → landed. **The rung, end to end, through the browser's road.**

    Both halves matter. The first is that the person is ASKED — at A5 an
    enrolled factor was a dead end, so a door that still refused would be a
    door that passes every test about refusing. The second is that answering
    it LANDS them, through allauth's own completion, with a real session: a
    factor form that renders beautifully and never signs anybody in is the
    same screen the design is replacing.
    """
    _enrol(door, "AUTHENTICATION_METHOD_TYPE_TOTP")

    asked = _sign_in(client)
    body = asked.content.decode()

    assert asked.status_code == 200
    assert "<h1>One more step</h1>" in body
    assert _title(body) == "One more step"
    assert _lede(body) == views.LEDES[FactorKind.TOTP]
    assert 'name="code"' in body
    assert "_auth_user_id" not in client.session, "asked is not signed in"

    landed = _answer_code(client)

    assert landed.status_code == 302
    assert landed["Location"] == django_settings.LOGIN_REDIRECT_URL
    assert "_auth_user_id" in client.session
    assert door.closed_sessions == door.opened_sessions


def test_email_otp_is_offered_only_with_smtp_configured(
    client: Client, door: FakeSignInZitadel, ours: None, settings: Any
) -> None:
    """The chip's availability IS the `smtp_configuration()` read (F10).

    One person, one enrolment, two deployments. With a sender on the instance
    the emailed code is a road; without one it is design J7's sentence, and
    the page never offers a code nobody will send.
    """
    settings.PRODUCT_NAME = "Pilecap"
    _enrol(door, "AUTHENTICATION_METHOD_TYPE_OTP_EMAIL")

    door.smtp = {}
    without = _sign_in(client)
    body = without.content.decode()
    assert "<h1>Sign in</h1>" in body
    assert _note(body) == views.KIND_SENTENCES[FactorKind.OTP_EMAIL]
    assert _chips(body) == []

    client.logout()
    cache.clear()
    door.smtp = {**A_FOREIGN_SENDER, "description": "Set by Pilecap (accounts.login_policy)"}
    with_sender = _sign_in(client)
    body = with_sender.content.decode()
    assert "<h1>One more step</h1>" in body
    assert _lede(body) == views.LEDES[FactorKind.OTP_EMAIL]
    assert _asked(door, "GET", "/admin/v1/smtp")


def test_the_email_otp_chip_names_the_senders_owner_when_foreign(
    client: Client, door: FakeSignInZitadel, ours: None, settings: Any
) -> None:
    """F10's second half: a person told whose mail to expect.

    On a shared instance the sender belongs to whoever configured it last,
    and the audit already prints that as a `foreign` line for an operator.
    The person waiting at the form needs the same fact in the same words: the
    code is coming, and it is coming from a name they have never heard of.
    """
    settings.PRODUCT_NAME = "Pilecap"
    _enrol(door, "AUTHENTICATION_METHOD_TYPE_OTP_EMAIL")
    door.smtp = dict(A_FOREIGN_SENDER)

    body = _sign_in(client).content.decode()

    assert "no-reply@example-crm.localhost" in body
    assert "The code is sent from no-reply@example-crm.localhost." in body

    # And our OWN sender is not announced: a note printed on every page is a
    # note nobody reads, and there is nothing to warn about.
    client.logout()
    cache.clear()
    door.smtp = {**A_FOREIGN_SENDER, "description": "Set by Pilecap (accounts.login_policy)"}
    ours_body = _sign_in(client).content.decode()
    assert "no-reply@example-crm.localhost" not in ours_body


def test_a_wrong_code_reads_the_refused_sentence_and_the_form_stays(
    client: Client, door: FakeSignInZitadel, ours: None
) -> None:
    """WATCH F8's opposite, one screen later. **Nothing typed disappears.**

    F8 is a wrong password costing the person both fields. A wrong code that
    threw the ceremony away would be the same defect on the second screen:
    the address and the password were both right, the platform judged six
    characters, and the session it judged them against is still verified. So
    the form stays, the chips stay, and the next code is one field away —
    and the sentence is about a CODE, because "that email and password don't
    match" on a screen with neither field on it sends the person to check
    something they are not looking at.
    """
    _enrol(door, "AUTHENTICATION_METHOD_TYPE_TOTP")
    _sign_in(client)

    refused = _answer_code(client, "000000")
    body = refused.content.decode()

    assert refused.status_code == 200
    assert "<h1>One more step</h1>" in body
    assert _note(body) == views.A_REFUSED_CODE
    assert "ask whoever runs your organization to reset your sign-in" in body
    assert 'name="code"' in body, "the form the person needs is gone"
    assert "accounts.signin.ceremony" in client.session, "a mistyped digit lost the ceremony"
    assert "_auth_user_id" not in client.session

    landed = _answer_code(client)
    assert landed.status_code == 302, "the surviving ceremony must be finishable"


def test_the_chooser_draws_the_other_kinds_and_never_the_one_it_is_asking(
    client: Client, door: FakeSignInZitadel, ours: None, settings: Any
) -> None:
    """Design J2-b: a code field for one kind, chips for the alternatives.

    The chip for the kind the form above is already asking for would be a
    button that says what the field says, so it is never drawn. The order is
    the door's own: an authenticator app is asked for first because it costs
    no round trip and no waiting.
    """
    settings.PRODUCT_NAME = "Pilecap"
    door.smtp = {**A_FOREIGN_SENDER, "description": "Set by Pilecap (accounts.login_policy)"}
    _enrol(door, "AUTHENTICATION_METHOD_TYPE_OTP_EMAIL", "AUTHENTICATION_METHOD_TYPE_TOTP")

    body = _sign_in(client).content.decode()

    assert _lede(body) == views.LEDES[FactorKind.TOTP]
    assert _chips(body) == [("use_otp_email", views.CHIP_LABELS[FactorKind.OTP_EMAIL])]

    chosen = client.post(LOGIN_URL, {"action": "use_otp_email"})
    swapped = chosen.content.decode()

    assert _lede(swapped) == views.LEDES[FactorKind.OTP_EMAIL]
    assert _chips(swapped) == [("use_totp", views.CHIP_LABELS[FactorKind.TOTP])]


def test_a_chip_the_page_never_drew_is_a_dead_end(
    client: Client, door: FakeSignInZitadel, ours: None, settings: Any
) -> None:
    """A typed action, a stale tab, or an instance whose mail sender went away.

    The kind is checked against the population the ceremony recorded, not
    against the five the seam has names for — so a form that asks for the
    email road on a deployment that cannot deliver it reaches the sentence
    rather than a code field nobody will fill.

    **Both directions, which is also what makes A6.3 per-KIND complete.** An
    authenticator app is the one kind the door can always ask for, so the
    only road to ITS `kind_unanswerable` sentence is this one: a person who
    never enrolled it, on a page that never drew the chip. A sentence with no
    road to it is a sentence nobody has ever read.
    """
    _enrol(door, "AUTHENTICATION_METHOD_TYPE_TOTP")
    _sign_in(client)

    response = client.post(LOGIN_URL, {"action": "use_otp_email"})
    body = response.content.decode()

    assert response.status_code == 200
    assert "<h1>Sign in</h1>" in body
    assert _note(body) == views.KIND_SENTENCES[FactorKind.OTP_EMAIL]
    assert not str(response.get("Location", ""))
    assert door.closed_sessions == door.opened_sessions

    client.logout()
    cache.clear()
    settings.PRODUCT_NAME = "Pilecap"
    door.smtp = {**A_FOREIGN_SENDER, "description": "Set by Pilecap (accounts.login_policy)"}
    _enrol(door, "AUTHENTICATION_METHOD_TYPE_OTP_EMAIL")
    _sign_in(client)

    other_way = client.post(LOGIN_URL, {"action": "use_totp"})
    other_body = other_way.content.decode()

    assert other_way.status_code == 200
    assert _note(other_body) == views.KIND_SENTENCES[FactorKind.TOTP]
    assert not str(other_way.get("Location", ""))
    for banned in ("MFA", "2FA", "U2F", "WebAuthn"):
        assert banned not in _on_the_face(other_body), banned


# --- A6.2 · enrolment, and the symbol this tree draws itself ------------------
#
# The QR is the one piece of the sign-in road that is arithmetic rather than a
# decision, so it is proved twice and neither proof is "it rendered": an
# independently written READER takes the symbol apart and recovers the URI,
# and the Reed-Solomon parity is checked by evaluating each block's codeword
# polynomial at the generator's own roots. A symbol that scans in nobody's
# camera is a QR that passes every test about being 33 squares wide.


#: Level M's block structure, versions 1-10, typed OUT OF THE SPECIFICATION
#: AGAIN rather than imported from the encoder: `(ecc per block, [data per
#: block])`. A reader that shares the writer's tables is a reader that agrees
#: with the writer's transcription errors, and that is exactly how a symbol
#: no scanner on earth could read passed every test in this file.
_SPEC_BLOCKS_M: dict[int, tuple[int, list[int]]] = {
    1: (10, [16]),
    2: (16, [28]),
    3: (26, [44]),
    4: (18, [32, 32]),
    5: (24, [43, 43]),
    6: (16, [27, 27, 27, 27]),
    7: (18, [31, 31, 31, 31]),
    8: (22, [38, 38, 39, 39]),
    9: (22, [36, 36, 36, 37, 37]),
    10: (26, [43, 43, 43, 43, 44]),
}

#: Alignment-pattern centres per version, likewise re-typed.
_SPEC_ALIGNMENT: dict[int, list[int]] = {
    1: [],
    2: [6, 18],
    3: [6, 22],
    4: [6, 26],
    5: [6, 30],
    6: [6, 34],
    7: [6, 22, 38],
    8: [6, 24, 42],
    9: [6, 26, 46],
    10: [6, 28, 50],
}

#: **The published format strings for error-correction level M**, one per
#: mask, MSB first — ISO/IEC 18004's own table. Nothing derives these and
#: nothing may: they are the independent check on the field whose PLACEMENT
#: was transposed, and V-A-W3 is what bought them.
_SPEC_FORMAT_M: tuple[str, ...] = (
    "101010000010010",
    "101000100100101",
    "101111001111100",
    "101101101001011",
    "100010111111001",
    "100000011001110",
    "100111110010111",
    "100101010100000",
)


def _spec_reserved(size: int, version: int) -> list[list[bool]]:
    """Which modules are function patterns, derived here from the specification.

    Finders and their separators, the two timing lines, the alignment
    patterns, the format fields, the version blocks and the dark module. No
    line of this comes from `qr.py`.
    """
    reserved = [[False] * size for _ in range(size)]

    def block(top: int, left: int, height: int, width: int) -> None:
        for row in range(top, top + height):
            for column in range(left, left + width):
                if 0 <= row < size and 0 <= column < size:
                    reserved[row][column] = True

    block(0, 0, 9, 9)
    block(0, size - 8, 9, 8)
    block(size - 8, 0, 8, 9)
    for at in range(size):
        reserved[6][at] = True
        reserved[at][6] = True
    centres = _SPEC_ALIGNMENT[version]
    last = centres[-1] if centres else 0
    for row in centres:
        for column in centres:
            if (row, column) in ((6, 6), (6, last), (last, 6)):
                continue
            block(row - 2, column - 2, 5, 5)
    if version >= 7:
        block(0, size - 11, 6, 3)
        block(size - 11, 0, 3, 6)
    return reserved


def _spec_masked(row: int, column: int, pattern: int) -> bool:
    """The eight mask predicates, written out again from the specification."""
    return (
        ((row + column) % 2 == 0),
        (row % 2 == 0),
        (column % 3 == 0),
        ((row + column) % 3 == 0),
        ((row // 2 + column // 3) % 2 == 0),
        (((row * column) % 2 + (row * column) % 3) == 0),
        ((((row * column) % 2 + (row * column) % 3) % 2) == 0),
        ((((row + column) % 2 + (row * column) % 3) % 2) == 0),
    )[pattern]


def _read_symbol(matrix: list[list[bool]]) -> dict[str, Any]:
    """Take a symbol apart again. **INDEPENDENT OF THE ENCODER, deliberately.**

    The first version of this reader borrowed `qr._skeleton` and
    `qr._masked`, and that is precisely why it decoded thirty symbols that
    no scanner could read: the encoder wrote the format field transposed and
    the reader read it back transposed, so the two agreed perfectly about a
    symbol the world rejects. V-A-W3 found it with zxing-cpp and jsQR.

    So this shares nothing with `qr.py` — its own reserved map, its own mask
    predicates, its own block table, its own format cells. Where the two
    disagree the disagreement is the finding, which is the only thing a
    second implementation is FOR.

    **What it still cannot do**, declared: it is not a scanner. It reads a
    perfect matrix, not a photograph, and it corrects no errors. The proof
    that a real decoder reads these symbols is the scratch run against
    zxing-cpp recorded in the return that fixed it, and the verifier's browser.
    """
    size = len(matrix)
    version = (size - 17) // 4
    cells = (
        [(index, 8) for index in range(6)]
        + [(7, 8), (8, 8), (8, 7)]
        + [(8, 14 - index) for index in range(9, 15)]
    )
    fmt = "".join("1" if matrix[row][column] else "0" for row, column in cells)[::-1]
    raw = int(fmt, 2) ^ 0x5412
    mask = (raw >> 10) & 0b111
    level = (raw >> 13) & 0b11

    reserved = _spec_reserved(size, version)
    stream: list[int] = []
    column, upward = size - 1, True
    while column > 0:
        if column == 6:
            column -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for offset in (0, 1):
                at = column - offset
                if not reserved[row][at]:
                    dark = 1 if matrix[row][at] else 0
                    stream.append(dark ^ 1 if _spec_masked(row, at, mask) else dark)
        upward = not upward
        column -= 2

    whole = len(stream) - len(stream) % 8
    words = [int("".join(str(b) for b in stream[at : at + 8]), 2) for at in range(0, whole, 8)]
    ecc_length, sizes = _SPEC_BLOCKS_M[version]
    words = words[: sum(sizes) + ecc_length * len(sizes)]

    blocks: list[list[int]] = [[] for _ in sizes]
    eccs: list[list[int]] = [[] for _ in sizes]
    at = 0
    for index in range(max(sizes)):
        for which, size_of in enumerate(sizes):
            if index < size_of:
                blocks[which].append(words[at])
                at += 1
    for _ in range(ecc_length):
        for which in range(len(sizes)):
            eccs[which].append(words[at])
            at += 1

    data = "".join(f"{word:08b}" for block in blocks for word in block)
    count_bits = 8 if version < 10 else 16
    count = int(data[4 : 4 + count_bits], 2)
    body = bytes(
        int(data[4 + count_bits + 8 * index : 12 + count_bits + 8 * index], 2)
        for index in range(count)
    )
    return {
        "version": version,
        "mask": mask,
        "level": level,
        "mode": int(data[:4], 2),
        "text": body.decode(),
        "format": fmt,
        "syndromes": [
            _evaluate(block + ecc, root)
            for block, ecc in zip(blocks, eccs, strict=True)
            for root in range(ecc_length)
        ],
    }


#: GF(256) again, the reader's own — same field, separate arithmetic.
def _gf_mul(left: int, right: int) -> int:
    product = 0
    while right:
        if right & 1:
            product ^= left
        right >>= 1
        left <<= 1
        if left & 0x100:
            left ^= 0x11D
    return product


def _gf_pow(base: int, power: int) -> int:
    out = 1
    for _ in range(power):
        out = _gf_mul(out, base)
    return out


def _evaluate(codeword: list[int], root: int) -> int:
    """One codeword polynomial at alpha^root, by Horner's rule."""
    at = _gf_pow(2, root)
    total = 0
    for coefficient in codeword:
        total = _gf_mul(total, at) ^ coefficient
    return total


#: What Zitadel hands back from `POST /v2/users/{id}/totp`, in the shape the
#: fake serves it — a TOTP URI with the issuer, the account and the secret.
A_TOTP_URI = "otpauth://totp/Pilecap:ada@yourco.test?secret=JBSWY3DPEHPK3PXP&issuer=Pilecap"


@pytest.mark.parametrize(
    "payload",
    ["x", A_TOTP_URI, "otpauth://totp/" + "n" * 60, "A" * qr.MAX_BYTES],
    ids=["one-byte", "a-totp-uri", "a-long-label", "the-whole-envelope"],
)
def test_the_symbol_round_trips_through_an_independent_reader(payload: str) -> None:
    """Byte mode, level M, and the URI comes back out. **The encoder's real test.**

    A reader rather than a fixture: a pinned expected matrix would be a
    recording of whatever this encoder does today, and would go green on a
    symbol no camera can read. The reader reverses the specification's steps
    and the payload has to survive all of them.
    """
    read = _read_symbol(qr.encode(payload))

    assert read["text"] == payload
    assert read["mode"] == 0b0100, "byte mode"
    assert read["level"] == 0b00, "error-correction level M"
    assert read["mask"] in range(8)
    assert 1 <= read["version"] <= 10


def test_the_parity_is_a_real_reed_solomon_remainder() -> None:
    """Every block's codeword evaluates to zero at every root of its generator.

    The one property a round-trip cannot see: a reader that ignores the
    parity recovers the payload from a symbol whose error correction is
    nonsense, and a damaged or angled scan then fails in the person's hand
    rather than in a test. Horner evaluation here against polynomial long
    division there, so the two arithmetics are independent.
    """
    for payload in ("x", A_TOTP_URI, "A" * qr.MAX_BYTES):
        read = _read_symbol(qr.encode(payload))
        assert set(read["syndromes"]) == {0}, payload


def test_the_symbol_is_laid_out_as_the_specification_says() -> None:
    """The function patterns, checked where the reader borrows rather than reads."""
    modules = qr.encode(A_TOTP_URI)
    size = len(modules)
    version = (size - 17) // 4

    assert size == 4 * version + 17
    for top, left in ((0, 0), (0, size - 7), (size - 7, 0)):
        assert modules[top][left] and modules[top + 6][left + 6], "finder ring"
        assert not modules[top + 1][left + 1], "finder inner ring is light"
        assert modules[top + 3][left + 3], "finder core"
    assert [modules[6][at] for at in range(8, 14)] == [True, False, True, False, True, False]
    assert [modules[at][6] for at in range(8, 14)] == [True, False, True, False, True, False]
    assert modules[size - 8][8], "the dark module"


@pytest.mark.parametrize("mask", range(8))
def test_the_format_field_is_the_one_the_specification_publishes(mask: int) -> None:
    """**The defect V-A-W3 found, pinned where it cannot come back.**

    The encoder computed the right fifteen bits and wrote them into the
    wrong thirty modules: the reference implementation's `set(x, y, …)`
    takes x as the COLUMN, and it was transcribed as `matrix[x][y]`. Every
    symbol therefore carried a format field a scanner reads bit-reversed,
    and not one of them was readable — by zxing-cpp, by jsQR, or by a phone.

    This reads the field out of a real symbol and compares it against the
    published string for level M at each mask. It shares nothing with the
    encoder and nothing with `_read_symbol`'s block machinery: eight
    constants out of the specification, and the cells they belong in.
    """
    encoded = A_TOTP_URI.encode()
    version = qr._version_for(encoded)
    words = qr._codewords(encoded, version)
    bits = [(w >> shift) & 1 for w in words for shift in range(7, -1, -1)]
    bits += [0] * qr._REMAINDER[version]
    base, fixed, size = qr._skeleton(version)
    qr._place(base, fixed, size, bits)
    for row in range(size):
        for column in range(size):
            if not fixed[row][column] and qr._masked(row, column, mask):
                base[row][column] ^= 1
    qr._stamp(base, size, version, mask)

    first = (
        [(index, 8) for index in range(6)]
        + [(7, 8), (8, 8), (8, 7)]
        + [(8, 14 - index) for index in range(9, 15)]
    )
    second = [(8, size - 1 - index) for index in range(8)] + [
        (size - 15 + index, 8) for index in range(8, 15)
    ]
    for name, cells in (("first", first), ("second", second)):
        written = "".join("1" if base[row][column] else "0" for row, column in cells)[::-1]
        assert written == _SPEC_FORMAT_M[mask], f"{name} copy, mask {mask}"


def test_the_tables_agree_with_each_versions_own_total() -> None:
    """Data codewords plus parity codewords is the version's total, or a table is wrong.

    The cheapest possible check on ten rows typed out of a specification, and
    the one that catches the transcription slip a round-trip would blame on
    the encoder.
    """
    for version, (ecc_length, sizes) in qr._BLOCKS_M.items():
        assert sum(sizes) + ecc_length * len(sizes) == qr._TOTAL_CODEWORDS[version], version


def test_a_payload_over_the_envelope_is_refused_rather_than_truncated() -> None:
    """A symbol that encodes half a URI scans perfectly and enrols nobody."""
    with pytest.raises(qr.TooLong):
        qr.encode("A" * (qr.MAX_BYTES + 1))


def test_the_symbol_fetches_nothing_and_says_nothing() -> None:
    """The entrance's no-fetch rule, and the secret is not written into the picture."""
    drawn = qr.svg(A_TOTP_URI)

    assert drawn.startswith("<svg ")
    assert "JBSWY3DPEHPK3PXP" not in drawn
    for banned in ("<script", "<image", "href", "url(", "https://", "<link"):
        assert banned not in drawn, banned


def test_the_enrolment_frame_draws_the_platforms_own_uri(
    client: Client, door: FakeSignInZitadel, ours: None
) -> None:
    """J2-c: the symbol on the page decodes to the URI Zitadel handed us.

    Not "an `<svg>` is present" — that is satisfied by a picture of anything.
    The document's own path is taken apart and read back, so a door that
    drew the symbol for the wrong string, or for a stale one, is red here.
    """
    door.login_settings = {"forceMfa": True, "mfaInitSkipLifetime": "2592000s"}

    body = _sign_in(client).content.decode()

    assert "<h1>Set up two-factor</h1>" in body
    assert _read_symbol(_symbol_in(body))["text"] == (
        f"otpauth://totp/Pilecap:{SIGNIN_LOGIN_NAME}?secret=ENROLSECRET"
    )
    # The secret in text as well as in the picture: a person on a laptop with
    # no camera types it, which is why the frame offers it in its own right.
    assert "ENROLSECRET" in body


def _symbol_in(body: str) -> list[list[bool]]:
    """The rendered SVG, read back into a module matrix."""
    found = re.search(r'<svg viewBox="0 0 (\d+) \d+".*?<path d="(.*?)"', body, re.S)
    assert found is not None, "no symbol on the page"
    padded = int(found.group(1))
    quiet = 4
    size = padded - 2 * quiet
    modules = [[False] * size for _ in range(size)]
    for column, row in re.findall(r"M(\d+) (\d+)h1v1h-1z", found.group(2)):
        modules[int(row) - quiet][int(column) - quiet] = True
    return modules


def test_not_now_is_drawn_only_where_a_skip_is_allowed(
    client: Client, door: FakeSignInZitadel, ours: None
) -> None:
    """A6.2: *Not now (N days)* iff `mfaInitSkipLifetime` is non-zero.

    Both arms, because the wrong one is a door that looks available and
    refuses — which design J2-c calls worse than no door — and because the
    number is READ at render rather than written into the template.
    """
    door.login_settings = {"forceMfa": True, "mfaInitSkipLifetime": "2592000s"}
    offered = _sign_in(client).content.decode()
    assert "Not now (30 days)" in offered
    assert 'value="skip"' in offered

    client.logout()
    cache.clear()
    door.login_settings = {"forceMfa": True, "mfaInitSkipLifetime": "0s"}
    withheld = _sign_in(client).content.decode()
    assert "Not now" not in withheld
    assert 'value="skip"' not in withheld


def test_not_now_lands_the_person_and_a_withdrawn_skip_does_not(
    client: Client, door: FakeSignInZitadel, ours: None
) -> None:
    """The button works — and the customer's policy still outranks a stale page.

    The second half is the one worth a test: the org's settings can change
    between the render that drew the link and the press that used it, and a
    template that honoured the button anyway would be this product overruling
    a deployment's own security posture.
    """
    door.login_settings = {"forceMfa": True, "mfaInitSkipLifetime": "2592000s"}
    _sign_in(client)

    landed = client.post(LOGIN_URL, {"action": "skip"})
    assert landed.status_code == 302
    assert "_auth_user_id" in client.session

    client.logout()
    cache.clear()
    _sign_in(client)
    door.login_settings = {"forceMfa": True, "mfaInitSkipLifetime": "0s"}

    refused = client.post(LOGIN_URL, {"action": "skip"})
    body = refused.content.decode()

    assert refused.status_code == 200
    assert "<h1>Sign in</h1>" in body
    assert _note(body) == views.A_REFUSED_SKIP
    assert "_auth_user_id" not in client.session
    assert door.closed_sessions == door.opened_sessions


def test_enrolment_with_the_code_lands_the_person(
    client: Client, door: FakeSignInZitadel, ours: None
) -> None:
    """The whole of J2-c: scan, type, and be signed in — and a wrong code is not.

    The refused arm re-renders the frame WITHOUT a second symbol: the
    platform begins one enrolment and the person's app already holds it, so
    a door that asked for another secret would invalidate the one they just
    scanned and the code they are about to type.
    """
    from apps.accounts.tests.conftest import SIGNIN_FACTOR_CODE

    door.login_settings = {"forceMfa": True, "mfaInitSkipLifetime": "0s"}
    _sign_in(client)

    wrong = client.post(LOGIN_URL, {"action": "enrol", "code": "000000"})
    body = wrong.content.decode()
    assert wrong.status_code == 200
    assert "<h1>Set up two-factor</h1>" in body
    assert _note(body) == views.A_REFUSED_CODE
    assert "<svg" not in body, "a second symbol would replace the one they scanned"
    assert 'name="code"' in body

    landed = client.post(LOGIN_URL, {"action": "enrol", "code": SIGNIN_FACTOR_CODE})
    assert landed.status_code == 302
    assert "_auth_user_id" in client.session


def test_no_face_says_a_forbidden_word(
    client: Client, door: FakeSignInZitadel, ours: None, settings: Any
) -> None:
    """The consumer's F14, adopted: never "MFA", "2FA", "U2F" or "WebAuthn".

    A census over every face the sign-in door can draw, gathered by DRIVING the
    door rather than by reading the templates — the sentences are the door's
    constants and the copy a person meets is the rendered document.
    """
    settings.PRODUCT_NAME = "Pilecap"
    faces: dict[str, str] = {}

    _enrol(door, "AUTHENTICATION_METHOD_TYPE_TOTP")
    faces["J2-a"] = client.get(LOGIN_URL).content.decode()
    faces["J2-b"] = _sign_in(client).content.decode()
    faces["J2-b refused"] = _answer_code(client, "000000").content.decode()
    faces["J2-a cancelled"] = client.post(LOGIN_URL, {"action": "cancel"}).content.decode()

    client.logout()
    cache.clear()
    _enrol(door, "AUTHENTICATION_METHOD_TYPE_U2F")
    faces["J2-a unanswerable"] = _sign_in(client).content.decode()

    client.logout()
    cache.clear()
    _enrol(door)
    door.login_settings = {"forceMfa": True, "mfaInitSkipLifetime": "2592000s"}
    faces["J2-c"] = _sign_in(client).content.decode()
    faces["J2-c refused"] = client.post(
        LOGIN_URL, {"action": "enrol", "code": "000000"}
    ).content.decode()

    for name, face in faces.items():
        readable = _on_the_face(face)
        for banned in ("MFA", "2FA", "U2F", "WebAuthn", "TOTP", "otpauth"):
            assert banned not in readable, f"{name} says {banned}"
    assert len(faces) == 7


# --- A6.3 · design J7's sentences, one case each ------------------------------
#
# `refused`, `throttled`, `unreachable` and `kind_unanswerable` have their
# cases in A5.4 above, re-run here by being in the same module. The three this
# rung reaches for the first time are below, and the census after them is what
# stops a sentence being added to the door with no case behind it.


def test_a_lockout_reads_the_wrong_password_sentence(
    client: Client, door: FakeSignInZitadel, ours: None
) -> None:
    """J7: the SAME sentence as a wrong password, plus the standing remedy.

    A distinct "locked" sentence is an oracle over which addresses exist and
    have been attacked, so the page must be unable to tell a person which of
    the three happened. **The error id here is not measured** — A3's hand
    walk measured the wrong-password refusal (`400 COMMAND-3M0fs`) and nobody
    has locked an account on the pinned build — and that is deliberate rather
    than a gap: the property is id-INDEPENDENT, so the test drives a judged
    refusal carrying a different id and asserts the page cannot tell.
    """
    door.refusals = [(400, "COMMAND-a-lockout-id-nobody-has-measured")]

    response = _sign_in(client)
    body = response.content.decode()

    assert response.status_code == 200
    assert _note(body) == views.SENTENCES[SignInOutcome.REFUSED]
    assert "ask whoever runs your organization to reset your sign-in" in body
    assert "lock" not in _on_the_face(body).lower()
    assert "COMMAND" not in body, "the platform's error id must not reach the page"


def test_a_ceremony_that_is_gone_says_so_and_gives_back_the_form(
    client: Client, door: FakeSignInZitadel, ours: None
) -> None:
    """J7's `ceremony_gone`: the tab left open for a quarter of an hour.

    Two shapes reach it and both are driven: a POST with no ceremony at all
    (a bookmarked form, a cleared cookie) and a ceremony whose session the
    platform has already expired. Neither is a refusal of the person.
    """
    nothing_started = _answer_code(client)
    body = nothing_started.content.decode()
    assert nothing_started.status_code == 200
    assert "<h1>Sign in</h1>" in body
    assert _note(body) == views.SENTENCES[SignInOutcome.CEREMONY_GONE]
    assert 'name="password"' in body, "the form to start again is the point"

    _enrol(door, "AUTHENTICATION_METHOD_TYPE_TOTP")
    _sign_in(client)
    door.sessions.clear()

    expired = _answer_code(client)
    assert _note(expired.content.decode()) == views.SENTENCES[SignInOutcome.CEREMONY_GONE]


def test_never_mind_says_nothing_was_changed(
    client: Client, door: FakeSignInZitadel, ours: None
) -> None:
    """J7's `cancelled`, in the cancellation page's own words, and no apology.

    The words are reused rather than rewritten: `login_cancelled.html` states
    the same fact for the hosted road, and two spellings of one sentence is
    how a product ends up apologising on one screen and not on another.
    """
    _enrol(door, "AUTHENTICATION_METHOD_TYPE_TOTP")
    _sign_in(client)

    response = client.post(LOGIN_URL, {"action": "cancel"})
    body = response.content.decode()

    assert response.status_code == 200
    assert "<h1>Sign in</h1>" in body
    assert _note(body) == views.SENTENCES[SignInOutcome.CANCELLED]
    assert "sorry" not in body.lower()
    assert "_auth_user_id" not in client.session
    assert door.closed_sessions == door.opened_sessions
    assert "accounts.signin.ceremony" not in client.session


def test_every_sentence_this_door_can_say_has_a_case_behind_it() -> None:
    """The census: a sentence with no drive is a sentence nobody has read.

    Read off the module's own maps rather than listed here, so a sentence
    added to the door with no case behind it reds this rather than shipping
    unrendered. The case names are the test functions in this module.
    """
    drives = {
        name for name, member in vars(views).items() if isinstance(member, str) and name.isupper()
    }
    assert set(views.SENTENCES) == {
        SignInOutcome.REFUSED,
        SignInOutcome.THROTTLED,
        SignInOutcome.UNAVAILABLE,
        SignInOutcome.CEREMONY_GONE,
        SignInOutcome.CANCELLED,
        # A7's three and A8's one. They are J7 rows like the five above —
        # what makes them different is only which road reaches them.
        SignInOutcome.INVITE_GONE,
        SignInOutcome.INVITE_WEAK,
        SignInOutcome.INVITE_REFUSED,
        SignInOutcome.REQUEST_GONE,
    }, "a J7 outcome gained or lost a sentence — give it a case above"
    # Every outcome the seam can answer either has a sentence or is one of
    # the three that never reaches a note: `CONTINUE` is a frame, `DONE` is a
    # redirect, `KIND_UNANSWERABLE` is answered per KIND out of the map
    # below. Derived, so a tenth outcome is a failure here rather than a
    # verdict the door renders as "that email and password don't match".
    assert set(SignInOutcome) - set(views.SENTENCES) == {
        SignInOutcome.CONTINUE,
        SignInOutcome.DONE,
        SignInOutcome.KIND_UNANSWERABLE,
        # A11b's, and it belongs with `REQUEST_GONE`'s reasoning rather than
        # with the five: the reset road's answer is a whole page STATE, not a
        # note over a form, so its words are the frame's own — and a sentence
        # here as well would be a second place for them to drift.
        SignInOutcome.RESET_ASKED,
    }
    assert set(views.KIND_SENTENCES) == set(FactorKind)
    assert set(views.LEDES) == set(FactorKind)
    assert set(views.CHIP_LABELS) == set(FactorKind)
    assert {"A_REFUSED_CODE", "A_REFUSED_SKIP"} <= drives


# --- A6.4 · the deep link rides the state ------------------------------------


def test_next_rides_the_whole_ceremony(client: Client, door: FakeSignInZitadel, ours: None) -> None:
    """A `?next=` taken at J2-a is still where the person lands after J2-b."""
    _enrol(door, "AUTHENTICATION_METHOD_TYPE_TOTP")
    _sign_in(client, query="?next=/welcome/")

    landed = _answer_code(client)

    assert landed.status_code == 302
    assert landed["Location"] == "/welcome/"


def test_a_later_next_cannot_repoint_a_proven_password(
    client: Client, door: FakeSignInZitadel, ours: None
) -> None:
    """The consumer's NO-GO V-184, driven. **The landing is decided at the start.**

    The deep link is taken on the request where the person has proved
    nothing, and it rides in the server-side state from there. A second POST
    carrying a different `?next=` is a page — or a link somebody sent — trying
    to re-point a sign-in that is already half done, and it is ignored: the
    person lands where they were going, and a ceremony begun with no deep
    link lands at the default however many are offered to it afterwards.
    """
    _enrol(door, "AUTHENTICATION_METHOD_TYPE_TOTP")
    _sign_in(client, query="?next=/welcome/")

    landed = client.post(
        f"{LOGIN_URL}?next=/admin/",
        {"action": "code", "code": door.factor_code},
    )

    assert landed["Location"] == "/welcome/"

    client.logout()
    cache.clear()
    _sign_in(client)
    plain = client.post(
        f"{LOGIN_URL}?next=/welcome/",
        {"action": "code", "code": door.factor_code},
    )

    assert plain["Location"] == django_settings.LOGIN_REDIRECT_URL


def test_the_typed_name_survives_a_refusal_on_the_second_screen(
    client: Client, door: FakeSignInZitadel, ours: None
) -> None:
    """WATCH F8 across the whole ceremony, not only its first screen.

    A person thrown back to J2-a from the code screen — a timed-out ceremony,
    an outage — must not find an empty address field: nothing about what they
    typed was wrong, and retyping it is the friction F8 is about.
    """
    _enrol(door, "AUTHENTICATION_METHOD_TYPE_TOTP")
    _sign_in(client)
    door.refusals = [(403, "AUTH-AWfge")]

    thrown_back = _answer_code(client)
    body = thrown_back.content.decode()

    assert thrown_back.status_code == 503
    assert f'value="{SIGNIN_LOGIN_NAME}"' in body


def test_a_route_this_build_does_not_have_is_an_outage_and_not_a_wrong_code(
    client: Client, door: FakeSignInZitadel, ours: None
) -> None:
    """A path the build does not have is an outage, not a wrong code.

    **And the case that taught it was a typo of ours.** A rung spelled the
    enrolment confirm `/totp/_verify`, got `404 {"code":5,"message":"Not
    Found"}` for the current window, the two either side and a deliberately
    wrong `000000`, and concluded the build had no such leg. The 404 was
    honest and the reading was not: the route is `/totp/verify`, it answers
    200, and the live enrolment road works. So the property below is real
    and the evidence for it is a path that genuinely is not there — which is
    now the only way to reach it, because the real one is called correctly.

    The discriminator is Zitadel's own: a JUDGED 404 carries an error id (an
    unknown login name is `QUERY-Dfbg2` on the session create, and A5's
    refusal road rides that shape), and a route 404 carries none. Both are
    driven here, so the rule cannot be satisfied by answering "outage" to
    everything.
    """
    # Driven on the FACTOR road rather than the enrolment one, because the
    # enrolment confirm is now spelled correctly and there is no missing
    # path left there to point at. The arm is `_judge`'s and is shared by
    # every leg, so the road it is driven on is the one where a refusal can
    # be planted honestly — a session call, through the fake's own queue,
    # with no knob invented to make the case reachable.
    _enrol(door, "AUTHENTICATION_METHOD_TYPE_TOTP")
    _sign_in(client)
    door.refusals = [(404, "")]

    absent = _answer_code(client)
    body = absent.content.decode()

    assert absent.status_code == 503
    assert _note(body).startswith("We couldn't reach the sign-in service")
    assert views.A_REFUSED_CODE not in body, "a missing route is not the person's mistake"

    # The other half: a 404 Zitadel put an id on is still a refusal of the
    # person, which is the road an unknown address takes.
    client.logout()
    cache.clear()
    refused = client.post(
        LOGIN_URL,
        {"action": "password", "email": "nobody@yourco.test", "password": SIGNIN_PASSWORD},
    )
    assert refused.status_code == 200
    assert _note(refused.content.decode()) == views.SENTENCES[SignInOutcome.REFUSED]


# --- A9 · the passkey road, at the door (design J6) --------------------------


#: A host that can be a relying party, for the tests whose subject is not the
#: predicate. The shipped `PUBLIC_BASE_URL` is `http://127.0.0.1:8000`, whose
#: host is an IP address and therefore not one — which is the DEFAULT state
#: and has its own case below.
A_REAL_HOST = "https://app.example.test"
A_REAL_RP = "app.example.test"

SCRIPT = Path(django_settings.BASE_DIR) / "apps/accounts/static/accounts/signin.js"


@pytest.fixture
def passkeys(door: FakeSignInZitadel, settings: Any) -> FakeSignInZitadel:
    """A deployment whose host is a relying party, and a person with a passkey."""
    settings.PUBLIC_BASE_URL = A_REAL_HOST
    door.passkey_rp = A_REAL_RP
    return door


def test_the_affordance_is_drawn_only_where_the_road_exists(
    client: Client, door: FakeSignInZitadel, ours: None, settings: Any
) -> None:
    """A9.2's first half, and it is the DOOR's half, not the browser's.

    On the shipped `PUBLIC_BASE_URL` the host is an IP address, no browser
    will run a ceremony against it, and the page is byte-for-byte A6's: no
    button, and no script tag either. Point the deployment at a hostname and
    both appear.
    """
    settings.PUBLIC_BASE_URL = "http://127.0.0.1:8000"
    closed = client.get(LOGIN_URL).content.decode()

    # `_on_the_face`, because the shell's own token block explains in a CSS
    # comment where the reveal's script lives — reasoning, not a page.
    assert "passkey" not in _on_the_face(closed).lower()
    assert "<script" not in closed
    assert "signin.js" not in _on_the_face(closed)

    settings.PUBLIC_BASE_URL = A_REAL_HOST
    opened = client.get(LOGIN_URL).content.decode()

    assert "Sign in with a passkey" in opened
    assert 'value="passkey_start"' in opened
    assert "accounts/signin.js" in opened


def test_the_affordance_ships_hidden_and_only_the_script_unhides_it(
    client: Client, passkeys: FakeSignInZitadel, ours: None
) -> None:
    """A9.2's second half: the BROWSER decides, and it decides in the client.

    A button revealed by the server is a button on a browser that cannot
    press it — the page has no way to know. So the markup ships `hidden`
    with the marker the static file looks for, and a browser with no
    `PublicKeyCredential` never sees it.
    """
    body = client.get(LOGIN_URL).content.decode()

    # A DIV, not a form of its own: the button belongs to the sign-in form
    # above it (`form="sign-in-form"`), which is how the typed address
    # travels with it — V-A-W3 found a passkey POST arriving with no email.
    holder = re.search(r"<div[^>]*data-needs=\"publickey-credential\"[^>]*>", body)
    assert holder is not None, body
    assert "hidden" in holder.group(0), "the affordance must ship hidden"
    assert 'form="sign-in-form"' in body, "the button must post the typed address"
    assert "data-needs='publickey-credential'" in SCRIPT.read_text(), (
        "the marker the frame ships and the marker the script looks for are one string"
    )


def test_the_script_is_static_never_inline_and_fetches_nothing() -> None:
    """A9.2's census, in Python. **The front-end harness does not reach here.**

    `frontend/vitest.config.ts` includes `src/**/*.test.ts(x)` and nothing
    else, so the vitest/jsdom suite cannot see a file under
    `apps/accounts/static/`; standing up a second JS harness for 150 lines
    that touch no framework would be a toolchain a product has to maintain.
    So the properties that matter are read statically, and they are the ones
    a CSP and the entrance's no-fetch rule turn on:

    * it is served from this origin, by `{% static %}`, and no frame inlines it;
    * it fetches nothing — no `fetch`, no `XMLHttpRequest`, no absolute URL;
    * the only exchange it makes with the server is the page's own form.

    **What this cannot see**, declared: whether the code WORKS. The reveal,
    the base64url round trip and the `navigator.credentials.get` call are
    the verifier's rendered check (A9.4) and a real browser's, and nothing
    in this suite executes a line of it.
    """
    source = SCRIPT.read_text()
    # The file's own comments SAY what it does not do — "no `fetch`, no
    # `XMLHttpRequest`" — and a census over the raw bytes would read the
    # explanation as the offence and could only be satisfied by deleting the
    # explanation. The same trap `_on_the_face` exists for, one layer down.
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.M)

    for banned in ("fetch(", "XMLHttpRequest", "http://", "https://", "import(", "eval("):
        assert banned not in code, banned
    assert "form.submit()" in code, "the one exchange is the page's own form"

    frames = "\n".join(source_text(path) for path in sorted(FRAMES_DIR.glob("*.html")))
    assert "{% static 'accounts/signin.js' %}" in frames
    inline = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", frames)
    assert inline == [], f"the production CSP is script-src 'self': {inline}"

    config = (Path(django_settings.BASE_DIR) / "frontend/vitest.config.ts").read_text()
    assert 'include: ["src/**/*.test.ts", "src/**/*.test.tsx"]' in config, (
        "the front-end harness moved — if it now reaches static/, this census "
        "should become a jsdom case"
    )


def test_the_passkey_ceremony_lands_the_person(
    client: Client, passkeys: FakeSignInZitadel, ours: None
) -> None:
    """J6 entrance (a) through the door: an address, a device, and no password.

    Two POSTs, because that is what a WebAuthn ceremony is: the first asks
    the platform for a challenge and puts it in the page, the second carries
    what the authenticator signed. The challenge rides in a hidden field the
    static file reads, never in an inline script.
    """
    asked = client.post(LOGIN_URL, {"action": "passkey_start", "email": SIGNIN_LOGIN_NAME})
    body = asked.content.decode()

    assert asked.status_code == 200
    assert "<h1>Sign in</h1>" in body
    carried = re.search(r'name="options" value="([^"]*)"', body)
    assert carried is not None, body
    options = json.loads(html.unescape(carried.group(1)))
    assert options["rpId"] == A_REAL_RP
    assert "_auth_user_id" not in client.session

    landed = client.post(
        LOGIN_URL,
        {
            "action": "passkey",
            "assertion": json.dumps({"id": passkeys.passkey_credential_id, "type": "public-key"}),
        },
    )

    assert landed.status_code == 302
    assert landed["Location"] == django_settings.LOGIN_REDIRECT_URL
    assert "_auth_user_id" in client.session
    assert passkeys.closed_sessions == passkeys.opened_sessions


def test_a_passkey_bound_elsewhere_reads_the_designs_own_sentence(
    client: Client, passkeys: FakeSignInZitadel, ours: None
) -> None:
    """K1 at the door, and **never a 500 to the person**.

    A passkey added on the identity platform's own pages is bound to their
    relying-party id. A9's drive measured that as `500 WEBAU-4G8sw` — the
    same answer a person with no passkey gets — so the page can only say
    this to somebody who really does own one, and it does.
    """
    passkeys.passkey_rp = "identity.example.test"

    response = client.post(LOGIN_URL, {"action": "passkey_start", "email": SIGNIN_LOGIN_NAME})
    body = response.content.decode()

    assert response.status_code == 200, "a 500 from the platform is not a 500 to the person"
    assert "<h1>Sign in</h1>" in body
    assert _note(body) == views.A_PASSKEY_FROM_SOMEWHERE_ELSE
    assert "WEBAU" not in body
    for banned in ("MFA", "2FA", "U2F", "WebAuthn"):
        assert banned not in _on_the_face(body), banned
    assert "_auth_user_id" not in client.session


def test_a_person_with_no_passkey_still_meets_the_chips(
    client: Client, passkeys: FakeSignInZitadel, ours: None
) -> None:
    """The road nobody is on stays the road it was (A9.3's last clause)."""
    passkeys.passkey_rp = None
    _enrol(passkeys, "AUTHENTICATION_METHOD_TYPE_TOTP")

    body = _sign_in(client).content.decode()

    assert "<h1>One more step</h1>" in body
    assert _lede(body) == views.LEDES[FactorKind.TOTP]
    assert 'name="options"' not in body, "no ceremony was begun, so nothing is carried"


def test_the_chip_road_puts_the_challenge_on_the_factor_frame(
    client: Client, passkeys: FakeSignInZitadel, ours: None
) -> None:
    """J6 entrance (b): the typed password reaches J2-b with the passkey kind."""
    _enrol(passkeys, "AUTHENTICATION_METHOD_TYPE_TOTP")
    passkeys.auth_methods.append("AUTHENTICATION_METHOD_TYPE_PASSKEY")

    first = _sign_in(client).content.decode()
    assert ("use_passkey", views.CHIP_LABELS[FactorKind.PASSKEY]) in _chips(first)

    chosen = client.post(LOGIN_URL, {"action": "use_passkey"})
    body = chosen.content.decode()

    assert "<h1>One more step</h1>" in body
    assert _lede(body) == views.LEDES[FactorKind.PASSKEY]
    carried = re.search(r'name="options" value="([^"]*)"', body)
    assert carried is not None, body
    assert json.loads(html.unescape(carried.group(1)))["rpId"] == A_REAL_RP

    landed = client.post(
        LOGIN_URL,
        {
            "action": "passkey",
            "assertion": json.dumps({"id": passkeys.passkey_credential_id, "type": "public-key"}),
        },
    )
    assert landed.status_code == 302
    assert "_auth_user_id" in client.session


# --- A11.2 · the words, verbatim ---------------------------------------------
#
# **What this census is for, and what it deliberately is not.** Every other
# test in this module drives a road and reads a sentence off the page it
# reaches. That proves a sentence is RENDERED; it cannot prove the sentence is
# the one the design wrote, because both sides of the assertion come out of
# the same tree. So the design's own words are transcribed here, once, with
# the line each came from, and the shipped copy is compared against them.
#
# **A divergence is allowed and must be DECLARED.** Five of the shipped
# sentences deliberately differ from the design's, and each carries the reason
# at its row below. What is refused is an UNDECLARED one: a sentence that
# drifted, or a new state whose words nobody compared with anything. The test
# fails in both directions — a shipped sentence with no row, and a row whose
# sentence is not shipped — because the second is how a design line quietly
# stops describing the product.

#: Design I-A's own words, by state, with the line they were transcribed from
#: (the P20 cycle plan; the § and line number are on each row).
#:
#: **THE PLAN'S PATH IS DELIBERATELY NOT SPELLED HERE.** The `--loop`
#: ledger's own drive asserts that no module under `apps/` names a docs
#: path, and it is not tidiness: the gate REUSES a banked verdict across a
#: docs-only delta, and it may only do that while no test's answer can move
#: when a document does. A path in this comment makes that reuse a stale
#: green — the drive named this file and this line, on a full gate, after
#: the `--loop` that landed it had no way to look.
DESIGN_SENTENCES: dict[str, str] = {
    # § J7's table, :955-967
    "refused": "That email and password don't match. Try again.",
    "throttled": "Too many tries. Wait a minute and try again.",
    "unavailable": "We couldn't reach the sign-in service. Try again in a moment.",
    "ceremony_gone": "That took too long. Start again.",
    "cancelled": "You stopped before finishing, so you are not signed in and nothing was changed.",
    "invite_gone": (
        "This link has already been used or has expired. Ask whoever invited you for a fresh one."
    ),
    "invite_refused": "This link was already used. Sign in instead.",
    "request_gone": (
        "This sign-in link has expired. Go back to the app that sent you here and try again."
    ),
    "no_sign_up": "People arrive here by invitation. Sign in with the address you were invited at.",
    # § J6, :941 — the template's ending, the one without an account page.
    #
    # **TRIMMED, AND THE ROW BELOW IS WHY.** The design gives
    # this sentence the remedy because its own version ends "Add one from
    # Your account…" and our tree has no account page to send anyone to. But
    # `standing_remedy` is printed on EVERY note, so the rendered screen said
    # "…reset your sign-in." and then "If this keeps happening, ask whoever
    # runs your organization to reset your sign-in." — V-A-W3 read both, one
    # under the other. Two entries in this very table contradict each other;
    # the one that says the remedy lives outside any single sentence is the
    # one that matches what a person sees. **A cross-chain edit to A11's pin,
    # flagged in the rung's return for its author to confirm.**
    # § J6, :941 — the template's own ending, the one without an account
    # page. **The FULL design line, remedy and all**: what ships is this
    # minus the remedy, by divergence 1's rule, and a pin that had been
    # moved to the trimmed form would be asserting the shipped string
    # against itself.
    "passkey_elsewhere": (
        "Passkeys added elsewhere don't work here. "
        "Ask whoever runs your organization to reset your sign-in."
    ),
    # § J7's kind rows and § J6 — the remedy as those sentences END with it,
    # capitalised and with no "If this keeps happening". It is NOT the same
    # string as the frame's standing line below, and the difference is the
    # point of divergence 1: what the shipped sentences drop is THIS, and
    # what the frame supplies instead is that.
    "kind_remedy_tail": "Ask whoever runs your organization to reset your sign-in.",
    # § J7, :949 — printed on EVERY note rather than inside any one sentence
    "standing_remedy": (
        "If this keeps happening, ask whoever runs your organization to reset your sign-in."
    ),
    # § J2-b, :884 and § J2-c, :896
    "totp_lede": "Enter the code from your authenticator app.",
    "enrol_lede": (
        "Your organization asks for a second step when you sign in. "
        "Scan this with an authenticator app, then type the code it shows."
    ),
    # § J1-a, :753-810
    "invited_lede": "You were invited as {email}. Pick a password and you're in.",
    "invite_expiry": (
        "This link stops working on {expires}. Missed it? Ask whoever invited you for a fresh one."
    ),
    # § J5, :932
    "logout_ours": "This ends your session. Signing back in asks for your password again.",
}

#: Every shipped sentence that deliberately differs from the design, and why.
#: A row here is a decision somebody made and can defend; a sentence in
#: neither this map nor `DESIGN_SENTENCES` is the failure this census exists
#: for.
DECLARED_DIVERGENCES: dict[str, str] = {
    "kind_unanswerable_remedy": (
        "Design J7 writes each unanswerable-kind sentence ENDING in the standing remedy "
        "('Ask whoever runs your organization to reset your sign-in'). A5 moved that remedy "
        "into the frame's own alert slot, where it prints on EVERY note — so a sentence that "
        "still carried it would print it twice on one screen. The shipped sentences stop "
        "before it and the frame supplies it. **`A_PASSKEY_FROM_SOMEWHERE_ELSE` is under this "
        "row too**, and is named because it is easy to miss: it comes from J6 rather than "
        "J7's table and it is a constant of its own rather than a `KIND_SENTENCES` member, so "
        "it shipped with the remedy still attached until the live browser drive saw it twice "
        "on one screen."
    ),
    "u2f_and_passkey_tense": (
        "Design J7 writes the security-key and passkey rows as a flat 'This account signs in "
        "with a security key.' The shipped pair say '…and we can't ask for one here yet', "
        "which is what is true of a deployment whose browser ceremony a person's kind cannot "
        "reach — and it stays true after A9, which built the passkey road for the kinds it "
        "CAN deliver and narrowed this map to the kinds it cannot."
    ),
    "a_refused_code": (
        "Design J7 has ONE `refused` row and its sentence names an email and a password. On "
        "the code screens there is neither field, so A6 ships 'That code isn't right. Try "
        "again.' — the same fact about a different screen. The design's row is not wrong; it "
        "is written for J2-a and was never shown J2-b."
    ),
    "a_refused_skip": (
        "A state the design did not enumerate: the org's policy changed between the render "
        "that drew *Not now* and the press. A6's sentence says what is now in force rather "
        "than re-drawing a link the platform has withdrawn."
    ),
    "invited_remedy": (
        "The `choose_your_password` frame's standing remedy says 'ask whoever invited you for "
        "a fresh link' rather than the organization one. An invited person has no "
        "organization yet — they are not a member of anything until they land — and an "
        "invitation has an inviter, which is a person they can actually reach."
    ),
    "per_kind_ledes_and_chips": (
        "Design J2-b draws two chips ('Email me a code instead · Use my security key') and one "
        "lede. A6 ships one of each PER KIND, from one map, because the chooser is a "
        "population: a deployment whose person enrolled a texted code would otherwise read a "
        "screen about an authenticator app they do not have."
    ),
    "reset_asks_for_an_address_not_a_password": (
        "Design J5 and P-10 drew a `reset` frame on which the person picks a new password, and "
        "A4 shipped one. M6 then measured that the platform's reset mail lands on the "
        "PLATFORM's own /ui/login/password/init with an EMPTY authRequestID — a mail has no "
        "application context, so the per-application login-v2 declaration that moves the "
        "sign-in screen cannot move this one. A frame of ours taking a new password was "
        "therefore a screen nobody could reach, and it was unreachable from A4 until A11b. "
        "The shipped frame asks for an ADDRESS, asks the platform to send its own mail, and "
        "says where that mail goes."
    ),
    "notes_that_are_not_refusals": (
        "Design J7 puts the standing remedy on EVERY refusal. Two frames carry a note that is "
        "not a refusal — `signed_out` states a fact somebody asked for, and `link_expired` "
        "has no form and therefore no next move to caption — and neither prints it. Printing "
        "'if this keeps happening' under 'You're signed out' would be an apology for a button "
        "the person pressed."
    ),
    "invite_weak_detail": (
        "Design J1-a writes 'That password doesn't meet the rules: <Zitadel's policy "
        "sentence>.' The constant in `SENTENCES` is the half this tree owns; the platform's "
        "own reason is appended at the call site (`_invite_note`), because a policy sentence "
        "restated here goes wrong on the first org that tightens one."
    ),
}


def _seen(document: str) -> str:
    """The copy, unescaped, with the shell's comments and token block gone."""
    return html.unescape(_on_the_face(document))


def test_every_frame_sentence_matches_the_design() -> None:
    """A11.2 · the words, against the design's own, with every divergence declared.

    Four populations in one case, because they are one question — what does a
    person read? — and four cases would be four places for a fifth population
    to not be added to.
    """
    from apps.accounts.tests.test_entrance_frames import FRAMES, POLICY_SENTENCE, SEEDED, _render

    # (1) The door's maps carry the design's sentence for every state the
    #     design named, and nothing the design did not.
    for state, wanted in DESIGN_SENTENCES.items():
        if state in views.SENTENCES or state in {outcome.value for outcome in views.SENTENCES}:
            shipped = next(
                text for outcome, text in views.SENTENCES.items() if outcome.value == state
            )
            assert shipped == wanted, (state, shipped, wanted)
    assert views.SENTENCES[SignInOutcome.INVITE_WEAK] == "That password doesn't meet the rules."
    assert views._NO_SIGN_UP == DESIGN_SENTENCES["no_sign_up"]
    # Divergence 1's rule, applied rather than restated: the shipped
    # sentence is the design's with the standing remedy taken off, because
    # the frame prints that remedy under every note and a sentence carrying
    # it too put it on the screen twice.
    assert views.A_PASSKEY_FROM_SOMEWHERE_ELSE == DESIGN_SENTENCES[
        "passkey_elsewhere"
    ].removesuffix(f" {DESIGN_SENTENCES['kind_remedy_tail']}")
    assert views.LEDES[FactorKind.TOTP] == DESIGN_SENTENCES["totp_lede"]

    # (2) `invite_weak` is completed the way the design writes it.
    composed = views._invite_note(
        SignIn(
            outcome=SignInOutcome.INVITE_WEAK,
            step=Step.INVITE,
            refusal_detail="Password is too short",
        )
    )
    assert composed == "That password doesn't meet the rules: Password is too short."

    # (3) Every frame carries the design's copy, rendered.
    rendered = {name: _seen(_render(name, **SEEDED[name])) for name in FRAMES}
    assert (
        DESIGN_SENTENCES["invited_lede"].format(email="ada@yourco.test")
        in rendered["choose_your_password"]
    )
    assert (
        DESIGN_SENTENCES["invite_expiry"].format(expires="17 September")
        in rendered["choose_your_password"]
    )
    assert DESIGN_SENTENCES["enrol_lede"] in rendered["set_up_two_factor"]
    assert DESIGN_SENTENCES["totp_lede"] in _seen(
        _render("one_more_step", lede=views.LEDES[FactorKind.TOTP])
    )
    assert POLICY_SENTENCE in rendered["choose_your_password"]
    head, _stop, move = DESIGN_SENTENCES["request_gone"].partition(". ")
    assert f"{head}." in rendered["link_expired"] and move in rendered["link_expired"]

    # A11b's frame, in BOTH states, and the divergence asserted rather than
    # only described: the design's `reset` takes a password and the shipped
    # one takes an address, because M6 measured where the mail lands.
    assert RESET_ASKS in rendered["reset"]
    assert 'type="password"' not in _render("reset", **SEEDED["reset"])
    after = _seen(_render("reset", asked=True))
    assert RESET_ON_ITS_WAY in after and RESET_WHERE in after
    assert "<form" not in after

    # (4) The standing remedy prints on every frame that can carry a
    #     REFUSAL, which is the design's own scope for it ("the standing
    #     second line that is on EVERY refusal"). Two frames carry a note
    #     that is not a refusal and correctly do not print it; both are
    #     named, so a third would be a failure rather than an omission.
    no_refusal = {"signed_out", "link_expired"}
    with_notes = [name for name in FRAMES if 'class="alert"' in _render(name, note="x")]
    assert len(with_notes) == len(FRAMES), with_notes
    for name in with_notes:
        remedy = _seen(_render(name, **{**SEEDED[name], "note": "x"}))
        if name in no_refusal:
            assert DESIGN_SENTENCES["standing_remedy"] not in remedy, name
            continue
        if name == "choose_your_password":
            assert "ask whoever invited you for a fresh link" in remedy, name
            continue
        assert DESIGN_SENTENCES["standing_remedy"] in remedy, name


def test_the_sign_out_page_says_what_the_measurement_found() -> None:
    """A11.1 · J5's `ours` sentence, now a measured fact (M7).

    The design recorded it as intent — *until it is measured the `ours`
    sentence above is design's intent, not a fact* — because nobody had
    looked at what a v2 round trip leaves in a browser. M7 has now looked: a
    device cookie and no session, and a second authorize with `prompt=none`
    answers the sign-in page rather than a code. So the page may promise it.
    """
    from django.template.loader import render_to_string
    from django.test import override_settings

    for door, wanted in (
        ("ours", DESIGN_SENTENCES["logout_ours"]),
        ("hosted", "You will stay signed in to the identity platform itself"),
    ):
        with override_settings(SIGN_IN_DOOR=door):
            page = " ".join(render_to_string("account/logout.html", {}).split())
        assert wanted in html.unescape(page), (door, page[:400])


def test_no_face_says_mfa_or_webauthn() -> None:
    """Design J2-c's "must not", over every frame and every sentence at once.

    The vocabulary a person reads is the one they have: an authenticator app,
    a code, a security key, a passkey. "MFA", "2FA", "U2F" and "WebAuthn" are
    ours, and the consumer's F14 is that they leak out of a variable name into
    a face the first time somebody writes a sentence in a hurry.
    """
    from apps.accounts.tests.test_entrance_frames import FRAMES, SEEDED, _render

    faces = [_seen(_render(name, **{**SEEDED[name], "note": "x"})) for name in FRAMES]
    faces += list(views.SENTENCES.values())
    faces += list(views.KIND_SENTENCES.values())
    faces += list(views.LEDES.values())
    faces += list(views.CHIP_LABELS.values())
    faces += [views.A_PASSKEY_FROM_SOMEWHERE_ELSE, views.A_REFUSED_CODE, views.A_REFUSED_SKIP]

    for face in faces:
        lowered = face.lower()
        for forbidden in ("mfa", "2fa", "u2f", "webauthn"):
            assert forbidden not in lowered, (forbidden, face[:200])


def test_every_declared_divergence_is_still_a_divergence() -> None:
    """The other direction: a reason for a difference that no longer exists.

    A divergence row outlives its difference the moment somebody brings the
    shipped sentence back in line, and a stale reason reads exactly like a
    live one. Each is therefore asserted to still DIFFER from the design.
    """
    assert DESIGN_SENTENCES["kind_remedy_tail"] not in views.KIND_SENTENCES[FactorKind.OTP_EMAIL]
    # The member of that population a reader misses: J6's, not J7's, and a
    # constant rather than a map entry. It shipped WITH the remedy until the
    # live drive read it twice on one screen.
    assert DESIGN_SENTENCES["kind_remedy_tail"] not in views.A_PASSKEY_FROM_SOMEWHERE_ELSE
    assert views.A_PASSKEY_FROM_SOMEWHERE_ELSE != DESIGN_SENTENCES["passkey_elsewhere"]
    assert "here yet" in views.KIND_SENTENCES[FactorKind.U2F]
    assert "here yet" in views.KIND_SENTENCES[FactorKind.PASSKEY]
    assert views.A_REFUSED_CODE != DESIGN_SENTENCES["refused"]
    assert views.A_REFUSED_SKIP not in DESIGN_SENTENCES.values()
    assert len(views.LEDES) > 1 and len(views.CHIP_LABELS) > 2
    assert set(DECLARED_DIVERGENCES) == {
        "kind_unanswerable_remedy",
        "u2f_and_passkey_tense",
        "a_refused_code",
        "a_refused_skip",
        "invited_remedy",
        "per_kind_ledes_and_chips",
        "invite_weak_detail",
        "notes_that_are_not_refusals",
        "reset_asks_for_an_address_not_a_password",
    }
    for reason in DECLARED_DIVERGENCES.values():
        assert len(reason) > 80, reason


# --- A11b · the reset road (design J5, settled by M6) ------------------------
#
# The *Forgot your password?* link finally goes somewhere, and where it goes
# is not what the design drew. M6 measured that the platform's reset mail
# lands on the PLATFORM's own page with an empty `authRequestID` — a mail has
# no application context for a per-application declaration to move — so a
# frame of ours taking a new password would be a screen nobody can reach,
# which is exactly what the `reset` frame was between A4 and here.
#
# **The floor makes these cases slow on purpose.** `request_reset` pads both
# roads to `RESET_FLOOR_SECONDS`, because a page that answers in 6 ms for an
# address nobody has and 16 ms for one somebody does (measured) is an account
# oracle with a stopwatch in front of it. The cases below patch the floor
# down where they are not about it, and one case is about it.

#: The reset frame's own three sentences, as shipped. Written here once so
#: the census, the road's cases and the divergence row all read the same
#: strings — a sentence asserted in three places by three spellings is a
#: sentence two of them stop noticing.
RESET_ASKS = "Type your address and we'll ask the sign-in service to email you a link."
RESET_ON_ITS_WAY = "If that address has an account, a link is on its way to it."
RESET_WHERE = (
    "The link opens the sign-in service's own page, where you pick the new password. "
    "Come back here afterwards to sign in."
)

NOBODY = "nobody-at-all@yourco.test"


def _forgot(client: Client, **extra: str) -> Any:
    query = "&".join(f"{name}={value}" for name, value in extra.items())
    return client.get(f"{LOGIN_URL}?forgot=1{'&' + query if query else ''}")


def _ask_reset(client: Client, *, email: str = SIGNIN_LOGIN_NAME, query: str = "?forgot=1") -> Any:
    """Submit the reset form the way a BROWSER submits it.

    `reset.html`'s form carries no `action`, so the POST goes to the address
    the page is standing on — `?forgot=1`, and whatever else came with it.
    A drive that posted to the bare path would be exercising a shape no
    browser produces, and would miss the one hazard this road has: a query
    on the POST is a `next` somebody could re-point the landing with.
    """
    return client.post(f"{LOGIN_URL}{query}", {"action": "reset", "email": email})


@pytest.fixture
def instant_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    """The timing floor, off, for the cases that are not about it.

    Named rather than blanket-patched in a conftest: a case that runs WITH
    the floor has to be able to, and one of them does.
    """
    monkeypatch.setattr("apps.accounts.signin.RESET_FLOOR_SECONDS", 0.0)


def test_forgot_your_password_opens_the_reset_frame(
    client: Client, door: FakeSignInZitadel, ours: None
) -> None:
    """A11b · the link goes somewhere, and what it opens asks for an ADDRESS.

    Not a password. The frame carried a New-password field from A4 until
    here, and it was unreachable the whole time — so this case asserts both
    halves: the frame renders, and the thing on it is the address form.
    """
    opened = _forgot(client)

    body = opened.content.decode()
    assert opened.status_code == 200, opened.status_code
    assert _frame(body) == views.FRAME_TITLES["reset"]
    assert "<h1>Reset your password</h1>" in body
    assert 'name="email"' in body and 'value="reset"' in body
    assert 'type="password"' not in body, "the reset frame must not ask for a password"


def test_the_platform_is_asked_exactly_once_for_an_address_it_knows(
    client: Client, door: FakeSignInZitadel, ours: None, instant_floor: None
) -> None:
    """A11b · the write, through the one door, once."""
    answered = _ask_reset(client)

    assert answered.status_code == 200, answered.status_code
    assert door.reset_requests == [(SIGNIN_USER_ID, '{"sendLink": {}}')], door.reset_requests


def test_an_address_nobody_has_reads_the_same_page_and_asks_for_nothing(
    client: Client, door: FakeSignInZitadel, ours: None, instant_floor: None
) -> None:
    """A11b · no enumeration, in the two places it leaks.

    **The bytes**, first: the page an unknown address gets is the page a
    known one gets, compared whole rather than by a sentence — a difference
    anywhere in the document is a difference somebody can diff.

    **And the call**, second: the platform is not asked about somebody who is
    not there. That is not politeness either; a reset request for an address
    a stranger typed is a mail this deployment caused to be sent to a person
    who did not ask for one.
    """
    known = _ask_reset(client)
    cache.clear()
    door.reset_requests.clear()
    unknown = _ask_reset(client, email=NOBODY)

    assert unknown.status_code == known.status_code == 200
    assert unknown.content == known.content
    assert door.reset_requests == [], door.reset_requests
    assert NOBODY not in unknown.content.decode()


def test_the_page_says_where_the_mail_lands(
    client: Client, door: FakeSignInZitadel, ours: None, instant_floor: None
) -> None:
    """A11b · the sentence M6 settled. **It says IF, and it says WHERE.**

    "If" because the rest of the road spends a measured 250 ms not saying
    whether the address has an account, and a page that then said "we've
    sent you a link" would give it away in words. "Where" because the mail
    opens the identity platform's own page, not ours — the person picks the
    password there and comes back here — and the one thing somebody who just
    pressed the button needs is to know which window to look in next.
    """
    answered = _ask_reset(client)

    body = _on_the_face(answered.content.decode())
    assert RESET_ON_ITS_WAY in body
    assert RESET_WHERE in body
    # The after-state has nothing to fill in: the next act is in an inbox.
    assert "<form" not in body


def test_both_roads_leave_on_the_same_floor(
    client: Client, door: FakeSignInZitadel, ours: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A11b · the timing half, measured against a CLOCK I hold, not the wall.

    MEASURED live on the pinned build: the known road is two platform calls
    and the unknown road is one — 16 ms against 6 ms, a 2.6x difference
    anybody can average out over a few hundred tries, and the per-address
    throttle does not bound an attacker walking a thousand addresses once
    each. So both roads are held to one floor.

    **The clock is patched, not the wall**, and that is the whole shape of
    this case. A first cut compared two real elapsed times through the fake
    and asserted the shorter road slept longer — true, and flaky: one 10 ms
    hiccup on a loaded box flips it, and a test that fails for the machine
    it runs on teaches everybody to re-run rather than to read. With a
    scripted clock the assertion is exact instead: each road sleeps the
    floor MINUS what it spent, so a road that spent 16 ms sleeps 234 ms and
    one that spent 6 ms sleeps 244 ms, and both leave at 250.
    """
    from apps.accounts import signin as seam

    assert seam.RESET_FLOOR_SECONDS >= 0.2, seam.RESET_FLOOR_SECONDS
    floor = seam.RESET_FLOOR_SECONDS

    # Two reads per road: `request_reset` stamps the start, `_hold` reads it
    # again. The numbers are the live measurement's own, so the arithmetic
    # below is the arithmetic the real roads do.
    ticks = iter([0.0, 0.016, 0.0, 0.006])
    monkeypatch.setattr("apps.accounts.signin.monotonic", lambda: next(ticks))
    slept: list[float] = []
    monkeypatch.setattr("apps.accounts.signin.sleep", slept.append)

    _ask_reset(client)
    cache.clear()
    _ask_reset(client, email=NOBODY)

    assert len(slept) == 2, slept
    for road in slept:
        assert 0 < road <= floor, (road, floor)
    assert slept[0] == pytest.approx(floor - 0.016), slept
    assert slept[1] == pytest.approx(floor - 0.006), slept


def test_an_outage_on_the_lookup_is_503_and_says_nothing_about_anybody(
    client: Client, door: FakeSignInZitadel, ours: None, instant_floor: None
) -> None:
    """A11b · fail-closed rule 2 on this road, and it leaks nothing either.

    A lookup that could not be made is an outage for EVERY address, which is
    why this arm is safe to be honest about where the others are not: the
    sentence is about us, not about them.
    """
    door.transport_fails = True

    answered = _ask_reset(client)

    assert answered.status_code == 503, answered.status_code
    assert _note(answered.content.decode()) == views.SENTENCES[SignInOutcome.UNAVAILABLE]
    assert door.reset_requests == [], door.reset_requests


def test_the_reset_road_spends_the_same_throttle_as_the_password_road(
    client: Client, door: FakeSignInZitadel, ours: None, instant_floor: None
) -> None:
    """A11b · one bucket per address, and both roads spend it.

    Two roads with two buckets is one bucket an attacker picks: a limiter on
    the password form alone leaves the reset form as a free oracle against
    the same address. Driven across the two, in that order, so the count that
    throttles is the SUM.
    """
    for _ in range(int(django_settings.SIGNIN_THROTTLE_PER_MINUTE)):
        _sign_in(client, password=WRONG_PASSWORD)

    answered = _ask_reset(client)

    assert answered.status_code == 429, answered.status_code
    assert _note(answered.content.decode()) == views.SENTENCES[SignInOutcome.THROTTLED]
    assert door.reset_requests == [], door.reset_requests


def test_next_survives_the_detour_through_the_reset_road(
    client: Client, door: FakeSignInZitadel, ours: None, instant_floor: None
) -> None:
    """A11b · a deep link outlives a forgotten password.

    Somebody who arrived on `?next=` and detoured through here is still going
    where they were going: the sign-in frame's own link carries it forward,
    and the reset frame's *Back to sign in* carries it back.
    """
    # Unescaped, because the document is HTML and the link carries an `&`:
    # a comparison against the raw bytes would be a comparison against
    # `&amp;`, which is the browser's business and not the door's.
    landing = html.unescape(client.get(f"{LOGIN_URL}?next=/welcome/").content.decode())
    assert "?forgot=1&next=%2Fwelcome%2F" in landing, landing[-800:]

    opened = html.unescape(_forgot(client, next="/welcome/").content.decode())
    assert f'href="{LOGIN_URL}?next=%2Fwelcome%2F"' in opened, opened[-800:]

    # **The POST carries a DIFFERENT `next`, and the stored one wins.** The
    # form has no `action`, so a browser posts to the address it is on and a
    # query on this request is real; a road that re-took the link here would
    # let a POST re-point a landing chosen at the start, which is V-184. The
    # two values differ precisely so that passing cannot be a coincidence.
    asked = html.unescape(_ask_reset(client, query="?forgot=1&next=/elsewhere/").content.decode())
    assert f'href="{LOGIN_URL}?next=%2Fwelcome%2F"' in asked, asked[-800:]
    assert "elsewhere" not in asked, asked[-800:]


def test_hosted_has_no_reset_road_at_all(client: Client, door: FakeSignInZitadel) -> None:
    """A11b · the default door, unmoved and byte-identical.

    Under `hosted` the page is the one-button entrance and allauth answers
    it: `?forgot=1` is a query it has never read, and a POST is still the
    403 ADR ident-4 closed the local password store with.
    """
    plain = client.get(LOGIN_URL)
    with_query = _forgot(client)

    assert with_query.status_code == 200, with_query.status_code
    assert with_query.content == plain.content
    assert door.reset_requests == [], door.reset_requests


# --- the six the live browser drive found ------------------------------------
#
# Every one of these was green in this file before the fake was corrected,
# because the fake did what the platform does not. Each test below names the
# platform fact it now rides on.


def test_a_person_with_two_factors_types_the_first_code_and_lands(
    client: Client, door: FakeSignInZitadel, ours: None, settings: Any
) -> None:
    """**Defect 1.** The ceremony records WHICH kind it asked for, or nobody lands.

    `_after_password` wrote `kinds` and no `pending`, and `_pending` only
    falls back to a single offer — so a person with two enrolled kinds typed
    a perfectly good code and read "this account signs in a way this page
    can't ask for", with the ceremony thrown away. Two kinds is the whole
    point of the case: with one, the fallback hid it.
    """
    settings.PRODUCT_NAME = "Pilecap"
    door.smtp = {**A_FOREIGN_SENDER, "description": "Set by Pilecap (accounts.login_policy)"}
    _enrol(door, "AUTHENTICATION_METHOD_TYPE_TOTP", "AUTHENTICATION_METHOD_TYPE_OTP_EMAIL")

    asked = _sign_in(client)
    body = asked.content.decode()
    assert "<h1>One more step</h1>" in body
    assert _lede(body) == views.LEDES[FactorKind.TOTP]
    assert signin.asked_for(client.session) is FactorKind.TOTP, "nothing recorded what was asked"

    landed = _answer_code(client)

    assert landed.status_code == 302, landed.content
    assert "_auth_user_id" in client.session


def test_an_emailed_code_is_sent_before_the_form_asks_for_it(
    client: Client, door: FakeSignInZitadel, ours: None, settings: Any
) -> None:
    """**Defect 2.** A form that asks for a code nobody was told to send.

    The password road drew *One more step* and called `challenge` never, so
    the platform mailed nothing and Mailpit stayed empty — and the only
    control that would have sent one was a chip for the kind already being
    asked for, which the page deliberately does not draw. The census is on
    what the platform was ASKED to do, not on what the page looks like.
    """
    settings.PRODUCT_NAME = "Pilecap"
    door.smtp = {**A_FOREIGN_SENDER, "description": "Set by Pilecap (accounts.login_policy)"}
    _enrol(door, "AUTHENTICATION_METHOD_TYPE_OTP_EMAIL")

    asked = _sign_in(client)
    body = asked.content.decode()

    assert "<h1>One more step</h1>" in body
    assert _lede(body) == views.LEDES[FactorKind.OTP_EMAIL]
    assert door.codes_sent == [("otpEmail", door.email_code)], (
        "the page asked for a code the platform was never told to send"
    )

    landed = _answer_code(client, door.email_code)
    assert landed.status_code == 302, landed.content
    assert "_auth_user_id" in client.session


def test_the_code_field_takes_the_length_the_platform_sends(
    client: Client, door: FakeSignInZitadel, ours: None, settings: Any
) -> None:
    """**Defect 3.** An eight-digit code in a six-character box.

    MEASURED off Mailpit by V-A-W3: `Your sign-in code is 41470160` — the
    emailed code is EIGHT digits, and the frame capped the field at six for
    every kind. The browser truncated it, the platform refused the six
    characters that arrived, and the same code pasted past the cap landed.
    A page must never cap a field shorter than the value the platform sends.
    """
    settings.PRODUCT_NAME = "Pilecap"
    door.smtp = {**A_FOREIGN_SENDER, "description": "Set by Pilecap (accounts.login_policy)"}
    _enrol(door, "AUTHENTICATION_METHOD_TYPE_OTP_EMAIL")

    emailed = _sign_in(client).content.decode()
    assert 'maxlength="8"' in emailed
    assert 'pattern="[0-9]{8}"' in emailed
    assert len(door.email_code) == 8

    client.logout()
    cache.clear()
    _enrol(door, "AUTHENTICATION_METHOD_TYPE_TOTP")
    app = _sign_in(client).content.decode()
    assert 'maxlength="6"' in app
    assert 'pattern="[0-9]{6}"' in app

    # And the truncation itself: six characters of an eight-digit code is a
    # refusal, which is what every person on the emailed road met.
    client.logout()
    cache.clear()
    _enrol(door, "AUTHENTICATION_METHOD_TYPE_OTP_EMAIL")
    _sign_in(client)
    truncated = _answer_code(client, door.email_code[:6])
    assert truncated.status_code == 200
    assert _note(truncated.content.decode()) == views.A_REFUSED_CODE


def test_the_settings_are_read_for_the_org_the_person_is_in(
    client: Client, door: FakeSignInZitadel, ours: None
) -> None:
    """An org-level `forceMfa` was ignored because nothing passed an org.

    `views._password` called `begin(org_id="")` and `login_settings` was
    therefore always asked for the INSTANCE default. The session read
    carries `factors.user.organizationId` (measured), and that is the org
    the question belongs to.
    """
    _sign_in(client)

    assert door.login_settings_orgs, "the login settings were never read"
    assert all(org == door.org_id for org in door.login_settings_orgs), door.login_settings_orgs


def test_a_person_in_another_org_still_lands(
    client: Client, door: FakeSignInZitadel, ours: None
) -> None:
    """The landing reads the person BY ID, which is not organisation-scoped.

    `POST /management/v1/users/_search` answers only rows in the caller's own
    organisation, so somebody invited into a second org on the same instance
    authenticated perfectly and then met a 503 (V-A-W3). `GET /v2/users/{id}`
    is not scoped — and it spells the verified flag `isVerified`, where the
    v1 search row spells the same fact `isEmailVerified`.
    """
    door.org_id = "a-different-organisation"

    landed = _sign_in(client)

    assert landed.status_code == 302, landed.content
    assert "_auth_user_id" in client.session
    assert any(path == f"/v2/users/{SIGNIN_USER_ID}" for _, path, _, _ in door.whole_calls), (
        "the landing still went through the org-scoped search"
    )


def test_the_enrolment_road_reads_the_persons_own_org_not_the_instance(
    client: Client, door: FakeSignInZitadel, ours: None
) -> None:
    """**The skip that let somebody past a second factor their org demands.**

    `_after_password` passed the person's org and `_may_skip` passed none,
    so one ceremony asked two different questions. An org with
    `mfaInitSkipLifetime=0` under an instance that allows 365 days drew
    *Not now (365 days)* — and pressing it LANDED the person with no second
    factor at all. Both halves are here: the face, and the forged POST.
    """
    door.login_settings = {"forceMfa": True, "mfaInitSkipLifetime": "0s"}
    door.instance_login_policy["mfaInitSkipLifetime"] = "31536000s"

    offered = _sign_in(client).content.decode()

    assert "<h1>Set up two-factor</h1>" in offered
    assert "Not now" not in offered, "the instance's skip was drawn over the org's refusal"
    assert 'value="skip"' not in offered
    assert door.login_settings_orgs, "no policy read happened at all"
    assert all(org == door.org_id for org in door.login_settings_orgs), door.login_settings_orgs

    # And the button nobody was shown, sent anyway.
    forged = client.post(LOGIN_URL, {"action": "skip"})

    assert forged.status_code == 200
    assert _note(forged.content.decode()) == views.A_REFUSED_SKIP
    assert "_auth_user_id" not in client.session, "a forged skip landed somebody"


def test_the_day_count_on_the_face_is_the_orgs_own(
    client: Client, door: FakeSignInZitadel, ours: None
) -> None:
    """Thirty days where the org says thirty, whatever the instance says."""
    door.login_settings = {"forceMfa": True, "mfaInitSkipLifetime": "2592000s"}
    door.instance_login_policy["mfaInitSkipLifetime"] = "31536000s"

    body = _sign_in(client).content.decode()

    assert "Not now (30 days)" in body
    assert "365" not in body

    landed = client.post(LOGIN_URL, {"action": "skip"})
    assert landed.status_code == 302
    assert "_auth_user_id" in client.session


def test_the_sender_note_is_only_on_the_face_waiting_for_mail(
    client: Client, door: FakeSignInZitadel, ours: None, settings: Any
) -> None:
    """A note about whose mail to expect, on a screen expecting no mail.

    The foreign-sender line is a warning for somebody waiting for a code to
    arrive. It rendered on the authenticator-app face too, where nothing is
    being sent and the sender is nobody's business.
    """
    settings.PRODUCT_NAME = "Pilecap"
    door.smtp = dict(A_FOREIGN_SENDER)
    _enrol(door, "AUTHENTICATION_METHOD_TYPE_TOTP", "AUTHENTICATION_METHOD_TYPE_OTP_EMAIL")

    app_face = _sign_in(client).content.decode()
    assert _lede(app_face) == views.LEDES[FactorKind.TOTP]
    assert "The code is sent from" not in app_face
    assert "no-reply@example-crm.localhost" not in app_face

    mail_face = client.post(LOGIN_URL, {"action": "use_otp_email"}).content.decode()
    assert _lede(mail_face) == views.LEDES[FactorKind.OTP_EMAIL]
    assert "The code is sent from no-reply@example-crm.localhost." in mail_face
