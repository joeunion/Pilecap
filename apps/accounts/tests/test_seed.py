"""What a fresh clone gets from the two seeds, and what each of them refuses to do.

`manage.py seed` — the tenant, the people and the token — is most of this
module. The last case is `manage.py zitadel_seed`'s, and it is here rather than
beside the other `zitadel_seed` cases because what it pins is the same property
every case above pins: **what a second run of a seed tells the person reading
it.** The one thing `zitadel_seed` genuinely cannot repeat is the browser
client's secret, and the sentence it prints in that state is the whole of a
second checkout's road out.
"""

from __future__ import annotations

from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts import zitadel
from apps.accounts.management.commands import zitadel_seed as seed
from apps.accounts.management.commands.seed import (
    SEED_MEMBER_EMAIL,
    SEED_OWNER_EMAIL,
    SEED_PASSWORD,
)
from apps.accounts.models import ApiToken, User
from apps.accounts.services import authenticate_token
from apps.accounts.tests.conftest import FakeZitadel
from apps.core.models import Membership, Tenant

pytestmark = pytest.mark.django_db


def _run(**options: Any) -> str:
    out = StringIO()
    # DEBUG is off under pytest, which is exactly the guard being bypassed here
    # — deliberately, and named, so the guard's own test below still means
    # something.
    call_command("seed", stdout=out, force=True, **options)
    return out.getvalue()


def test_a_fresh_database_becomes_drivable() -> None:
    """An empty database with tenancy on correctly answers nothing. This is the fix."""
    printed = _run()

    tenant = Tenant.objects.get(slug="acme")
    owner = User.objects.get(email=SEED_OWNER_EMAIL)
    member = User.objects.get(email=SEED_MEMBER_EMAIL)

    assert owner.check_password(SEED_PASSWORD)
    assert Membership.objects.get(user_id=owner.pk, tenant=tenant).role == Membership.Role.OWNER
    assert Membership.objects.get(user_id=member.pk, tenant=tenant).role == Membership.Role.MEMBER
    assert SEED_OWNER_EMAIL in printed


def test_the_printed_token_actually_works() -> None:
    printed = _run()
    plaintext = next(line for line in printed.splitlines() if line.startswith("djb_"))

    resolved = authenticate_token(plaintext=plaintext)
    assert resolved is not None
    assert resolved.user.email == SEED_OWNER_EMAIL
    assert resolved.tenant is not None and resolved.tenant.slug == "acme"


def test_running_it_twice_adds_a_token_and_nothing_else() -> None:
    """Idempotent where it must be, and not where re-running is the point.

    A token's plaintext is shown once, so "run seed again" is how somebody gets
    another one. Everything else is found rather than remade.
    """
    _run()
    _run()

    assert Tenant.objects.filter(slug="acme").count() == 1
    assert User.objects.filter(email=SEED_OWNER_EMAIL).count() == 1
    assert Membership.objects.filter(tenant__slug="acme").count() == 2
    assert ApiToken.objects.count() == 2


def test_it_refuses_to_seed_published_credentials_without_being_told_twice() -> None:
    """DEBUG is off under pytest, which is the same shape as a real deployment.

    `owner@example.com` with a password published in this repository is not test
    data on an internet-facing box; it is an account.
    """
    out = StringIO()
    with pytest.raises(CommandError):
        call_command("seed", stdout=out)

    assert not User.objects.filter(email=SEED_OWNER_EMAIL).exists()
    assert not Tenant.objects.exists()


def test_it_seeds_whatever_tenant_it_is_given() -> None:
    _run(tenant="Globex")

    tenant = Tenant.objects.get(slug="globex")
    assert Membership.objects.filter(tenant=tenant).count() == 2


# --- `manage.py zitadel_seed`: the run that cannot print a secret -------------


@pytest.mark.django_db(transaction=True)
def test_a_second_run_names_the_two_roads_to_a_secret_it_cannot_print(
    instance: FakeZitadel, capsys: Any
) -> None:
    """The second checkout on one machine, and what the closing line owes it.

    Zitadel shows a client secret exactly once, at creation. So the second
    checkout to seed against a project that already has a browser client gets
    `exists browser client` and no secret, and its sign-in cannot work until a
    secret reaches its `.env`. The only recovery the closing WARNING used to
    name was `--rotate-web-secret` — which mints a new secret and thereby stops
    the FIRST checkout's from working. Naming it alone made the line a remedy
    that silently breaks somebody else's sign-in.

    Two roads cost a sibling nothing, and both are named now. Copy the secret
    across from the checkout that holds it. Or give this checkout a project of
    its own with `ZITADEL_PROJECT_NAME` — then its browser client is *created*
    here, which is the one moment a secret is printable at all. The rotation
    keeps its place as the third road, with its cost stated in a sentence
    instead of left for a sibling to discover.

    The `exists` branch is driven rather than described: two runs against the
    fake instance, the second one's output read.
    """
    call_command("zitadel_seed", skip_user=True)
    capsys.readouterr()

    call_command("zitadel_seed", skip_user=True)
    second = capsys.readouterr().out

    # The state this sentence is for: the client was found, not made, so there
    # was no secret to print.
    assert "exists  browser client" in second
    assert "clientSecret" not in second

    # Road one — the sibling already holds it.
    assert "copy" in second.lower()
    assert "ZITADEL_CLIENT_SECRET" in second
    # Road two — a project of this checkout's own, whose client is created here.
    assert "ZITADEL_PROJECT_NAME" in second
    # And the third road's cost, said rather than left to be found.
    assert "--rotate-web-secret" in second
    assert "invalidates" in second


# --- the seed RECONCILES the browser client, rather than pinning it at birth --
#
# `ensure_web_application` found an application by name and returned its id. It
# never looked at what that application's OIDC config said, so every value the
# seed declares — the redirect URI, the post-logout URI, `devMode` — was written
# exactly once, at creation, and was somebody else's from then on. Two ordinary
# moves broke sign-in silently: a deployment whose `PUBLIC_BASE_URL` changed
# kept the old callback and no other, and a one-field console edit to the
# redirect URI left the person signing in on raw JSON at the identity platform,
# upstream of any page of ours. The seed said `exists` over both.


def _seeded(base_url: str, capsys: Any) -> str:
    capsys.readouterr()
    call_command("zitadel_seed", "--skip-user", "--base-url", base_url)
    return str(capsys.readouterr().out)


def _browser_config(instance: FakeZitadel) -> dict[str, Any]:
    """The browser client's live OIDC config, off the fake."""
    app = next(row for row in instance.apps.values() if row["name"] == "Web")
    config: dict[str, Any] = app["oidcConfig"]
    return config


def _oidc_config_puts(instance: FakeZitadel) -> list[dict[str, Any]]:
    return [
        body
        for method, path, body in instance.bodies
        if method == "PUT" and path.endswith("/oidc_config")
    ]


@pytest.mark.django_db(transaction=True)
def test_a_changed_base_url_updates_the_browser_clients_redirect_uris(
    instance: FakeZitadel, capsys: Any
) -> None:
    """THE criterion: the declared value wins, and the old one is GONE.

    Not merely "the new URI is present" — the 8000 URI is declared no longer, so
    it is cleared. A reconciler that added without removing would leave a
    deployment accepting a callback on an origin it has moved off, which is a
    redirect target somebody else may come to own.
    """
    _seeded("http://localhost:8000", capsys)
    assert _browser_config(instance)["redirectUris"] == [
        "http://localhost:8000/accounts/oidc/zitadel/login/callback/"
    ]

    out = _seeded("http://localhost:9000", capsys)

    assert _browser_config(instance)["redirectUris"] == [
        "http://localhost:9000/accounts/oidc/zitadel/login/callback/"
    ]
    assert _browser_config(instance)["postLogoutRedirectUris"] == ["http://localhost:9000/"]
    assert "updated browser client" in out


@pytest.mark.django_db(transaction=True)
def test_a_hijacked_redirect_uri_is_restored_by_the_seed(
    instance: FakeZitadel, capsys: Any
) -> None:
    """The console move, made against the fake exactly as it was made live.

    `PUT /management/v1/projects/<mine>/apps/<mine>/oidc_config redirectUris:
    ["http://127.0.0.1:1/hijacked/"]` — the deployment's own application, one
    field, and the seed used to answer `exists` over it.
    """
    _seeded("http://localhost:8000", capsys)
    config = _browser_config(instance)
    config["redirectUris"] = ["http://127.0.0.1:1/hijacked/"]

    out = _seeded("http://localhost:8000", capsys)

    assert _browser_config(instance)["redirectUris"] == [
        "http://localhost:8000/accounts/oidc/zitadel/login/callback/"
    ]
    assert "updated browser client" in out


@pytest.mark.django_db(transaction=True)
def test_an_unchanged_base_url_sends_no_put(instance: FakeZitadel, capsys: Any) -> None:
    """Idempotence by comparison, which is the only kind this surface allows.

    The sibling writers say why this is not a saving: an unchanged `PUT` is the
    call `scripts/setup.sh` makes on every run and the call at-least-once
    delivery guarantees will happen. Asserted on the request log rather than on
    the resulting state, because a `PUT` that happened to be idempotent would
    pass a state assertion and fail here.
    """
    _seeded("http://localhost:8000", capsys)
    instance.bodies.clear()

    out = _seeded("http://localhost:8000", capsys)

    assert _oidc_config_puts(instance) == []
    assert "exists  browser client" in out
    assert "updated browser client" not in out


@pytest.mark.django_db(transaction=True)
def test_the_reconciling_put_carries_the_resources_whole_field_set(
    instance: FakeZitadel, capsys: Any
) -> None:
    """ADR ident-8's full-body convention, at the one writer that just joined it.

    Zitadel's `PUT` is a REPLACE, so a body carrying only the three fields this
    deployment states an opinion about would zero `accessTokenType`,
    `idTokenUserinfoAssertion` and every other field the application was created
    with. `test_zitadel_full_body.py` is the census; this is the case at the
    writer, which is where a reader of this module would look.
    """
    _seeded("http://localhost:8000", capsys)
    instance.bodies.clear()

    _seeded("http://localhost:9000", capsys)

    sent = _oidc_config_puts(instance)
    assert len(sent) == 1
    assert set(sent[0]) == set(zitadel.OIDC_APP_CONFIG_FIELDS)
    # The fields we state no opinion about came back as the application has
    # them, not as their zero values.
    assert sent[0]["accessTokenType"] == "OIDC_TOKEN_TYPE_JWT"
    assert sent[0]["idTokenUserinfoAssertion"] is True


@pytest.mark.django_db(transaction=True)
def test_the_seeds_project_line_is_still_readable_by_setup(
    instance: FakeZitadel, capsys: Any
) -> None:
    """`scripts/setup.sh` reads the project id off this command's own output.

    Its awk matches the VERB in column one, so a third verb is a thing that
    reader has to be able to see or not need. It does not need it: only the
    applications reconcile, so the project line still says `created` or
    `exists`. Asserted as a census over both files rather than as a sentence,
    because the coupling is real and invisible from either side alone.
    """
    from pathlib import Path

    from django.conf import settings as django_settings

    reader = Path(django_settings.BASE_DIR, "scripts", "setup.sh").read_text()
    verbs = next(
        line for line in reader.splitlines() if '$2 == "project"' in line and "$1 ~" in line
    )

    out = _seeded("http://localhost:8000", capsys)

    project_line = next(line for line in out.splitlines() if " project " in line)
    assert project_line.split()[0] in ("created", "exists")
    for verb in ("created", "exists"):
        assert verb in verbs
    # And the third verb is NOT one the project line can wear, which is why the
    # reader above needs no change.
    assert "updated" not in project_line


# --- design C-9 · the login-version declaration, both ways --------------------
#
# Which login UI an application sends a person to is a per-application
# declaration (`loginVersion`), never an instance flag. Under
# `SIGN_IN_DOOR=ours` (rung A5) this deployment declares
# `loginV2.baseUri = <PUBLIC_BASE_URL>/accounts` and Zitadel appends `/login`;
# today it declares nothing, and **declaring nothing has to be a write**. The
# consumer paid for that distinction the expensive way: their reconciler
# expressed "clear it" as an empty list of applications to write, ran zero
# iterations, stayed green, and left an owner locked out of a deployment for a
# morning. So `None` CLEARS, and these are the cases that hold it there.


def _apps_by_name(instance: FakeZitadel) -> dict[str, dict[str, Any]]:
    return {str(row["name"]): row for row in instance.apps.values()}


def _login_version(instance: FakeZitadel, name: str) -> dict[str, Any] | None:
    return zitadel.login_version_of(_apps_by_name(instance)[name])


V2_BASE_URI = "http://localhost:8000/accounts"
CONSOLE_V2 = {"loginV2": {"baseUri": "http://somebody-elses-host.test/accounts"}}


@pytest.mark.django_db(transaction=True)
def test_a_v2_declaration_is_written_full_body(instance: FakeZitadel, capsys: Any) -> None:
    """A2.1, the forward direction — and the body carries the whole field set.

    Zitadel's `PUT` is a REPLACE, so a writer that sent `{"loginVersion": ...}`
    alone would clear every redirect URI on the application people sign in
    through while declaring where they should be sent. The declaration and the
    URIs are the two halves of one object and this is the case that proves the
    writer moves one without touching the other.
    """
    _seeded("http://localhost:8000", capsys)
    app_id = _apps_by_name(instance)["Web"]["id"]
    instance.bodies.clear()

    written = zitadel.ensure_application_login_version(
        project_id=_apps_by_name(instance)["Web"]["projectId"],
        app_id=app_id,
        base_uri=V2_BASE_URI,
    )

    assert written.updated is True
    assert _login_version(instance, "Web") == {"loginV2": {"baseUri": V2_BASE_URI}}
    sent = _oidc_config_puts(instance)
    assert len(sent) == 1
    assert set(sent[0]) == set(zitadel.OIDC_APP_CONFIG_FIELDS)
    assert sent[0]["redirectUris"] == [
        "http://localhost:8000/accounts/oidc/zitadel/login/callback/"
    ]


@pytest.mark.django_db(transaction=True)
def test_none_clears_a_v2_declaration_the_console_set(instance: FakeZitadel, capsys: Any) -> None:
    """A2.1, the reverse — **the road back, and it is a write, not a skip**.

    The world is the one that cost the consumer a morning: somebody declared
    login v2 on the application, pointing at a host this deployment does not
    serve. `base_uri=None` is how a deployment says "no declaration", and it
    has to reach Zitadel — an empty list of applications to write is zero
    iterations and leaves the declaration exactly where it was.
    """
    _seeded("http://localhost:8000", capsys)
    web = _apps_by_name(instance)["Web"]
    web["oidcConfig"]["loginVersion"] = dict(CONSOLE_V2)
    instance.bodies.clear()

    cleared = zitadel.ensure_application_login_version(
        project_id=str(web["projectId"]), app_id=str(web["id"]), base_uri=None
    )

    assert cleared.updated is True
    assert _login_version(instance, "Web") is None
    sent = _oidc_config_puts(instance)
    assert len(sent) == 1
    # The CLEAR is `null` in a full body, which is what removes the key —
    # measured against the pinned build, and the reason the field is in
    # `OIDC_APP_CONFIG_ABSENT` with `None` as its absent value.
    assert sent[0]["loginVersion"] is None
    assert set(sent[0]) == set(zitadel.OIDC_APP_CONFIG_FIELDS)


@pytest.mark.django_db(transaction=True)
def test_an_agreeing_declaration_sends_no_put(instance: FakeZitadel, capsys: Any) -> None:
    """A2.1's control: idempotence by comparison, in both of the two states.

    Asserted on the request log rather than on the resulting state, because a
    `PUT` that happened to be idempotent would pass a state assertion and fail
    here — and `scripts/setup.sh` runs the seed on every invocation.
    """
    _seeded("http://localhost:8000", capsys)
    web = _apps_by_name(instance)["Web"]
    project_id, app_id = str(web["projectId"]), str(web["id"])
    instance.bodies.clear()

    # Agreeing on "no declaration", which is the state today's seed leaves.
    settled = zitadel.ensure_application_login_version(
        project_id=project_id, app_id=app_id, base_uri=None
    )
    assert settled.updated is False
    assert _oidc_config_puts(instance) == []

    # And agreeing on a v2 declaration, which is the state A5 will leave.
    zitadel.ensure_application_login_version(
        project_id=project_id, app_id=app_id, base_uri=V2_BASE_URI
    )
    instance.bodies.clear()
    again = zitadel.ensure_application_login_version(
        project_id=project_id, app_id=app_id, base_uri=V2_BASE_URI
    )
    assert again.updated is False
    assert _oidc_config_puts(instance) == []


@pytest.mark.django_db(transaction=True)
def test_the_seed_declares_no_login_version_today(instance: FakeZitadel, capsys: Any) -> None:
    """A2.2: the seed passes what `declared_login_base_uri` hands it — `None`.

    The value is deliberately not hard-coded at the call site: one function
    computes this deployment's intent, the writer takes it and the audit judges
    against it, so the three cannot come to disagree about what is declared.
    Rung A5's `SIGN_IN_DOOR` is what makes that function return a URI.
    """
    out = _seeded("http://localhost:8000", capsys)

    assert seed.declared_login_base_uri("http://localhost:8000") is None
    for name in ("Web", "MCP Client"):
        assert _login_version(instance, name) is None
    assert "login version" in out
    assert "none — the identity platform's own page" in out


@pytest.mark.django_db(transaction=True)
def test_the_seed_clears_a_console_declared_login_v2(instance: FakeZitadel, capsys: Any) -> None:
    """A2.2's second half: a planted console v2 is CLEARED by an ordinary run.

    Planted the way it is planted in the console — one field on the
    deployment's own browser client — and closed by the command an operator
    already runs, with no flag and nothing to remember.
    """
    _seeded("http://localhost:8000", capsys)
    _apps_by_name(instance)["Web"]["oidcConfig"]["loginVersion"] = dict(CONSOLE_V2)

    out = _seeded("http://localhost:8000", capsys)

    assert _login_version(instance, "Web") is None
    assert "updated login version   Web" in out


@pytest.mark.django_db(transaction=True)
def test_the_seed_grants_the_login_client_role_once(instance: FakeZitadel, capsys: Any) -> None:
    """A2.4: `IAM_LOGIN_CLIENT` on the machine user, additively, once.

    Two properties in one case because they fail together: the role is granted
    (without it the login-v2 finalize answers `403 AUTH-AWfge` and nobody
    completes a sign-in on our own page), and `IAM_OWNER` survives — the update
    is a REPLACE of the role list, so a writer sending only the new role would
    take away the permission every other call in this module authenticates
    with, and the next seed run would fail on its first management call with
    nothing left that could grant it back.
    """
    machine = str(instance.machine["id"])
    instance.instance_members[machine] = ["IAM_OWNER"]

    out = _seeded("http://localhost:8000", capsys)

    assert instance.instance_members[machine] == ["IAM_OWNER", "IAM_LOGIN_CLIENT"]
    assert "login client" in out

    # Once: the second run compares and sends nothing.
    instance.bodies.clear()
    out = _seeded("http://localhost:8000", capsys)
    assert [
        path for method, path, _ in instance.bodies if method == "PUT" and "members" in path
    ] == []
    assert instance.instance_members[machine] == ["IAM_OWNER", "IAM_LOGIN_CLIENT"]
    assert "exists  login client" in out


# --- design I-A §3.7 · M1 and M2, as checks against a live instance ----------
#
# Two facts about the pinned build that this tree took off somebody else's
# measurement. They are NOT dialled by the suite — ADR ident-5(a) — so what is
# proved here is that each check LOOKS at the right thing and leaves nothing
# behind; `manage.py zitadel_measure` (rung I5) is what runs them for real.


@pytest.mark.django_db(transaction=True)
def test_the_login_version_check_measures_both_redirects_and_deactivates_its_victim(
    instance: FakeZitadel, capsys: Any
) -> None:
    """M1: the authorize redirect per login version, on a throwaway client.

    The two shapes are the measured ones: no declaration goes to Zitadel's own
    hosted page, a declaration goes to ours. **And the victim is closed** — an
    OIDC client left active on a real project is a live sign-in door nobody
    meant to open, so the check deactivates what it made, in a `finally`.
    """
    _seeded("http://localhost:8000", capsys)
    project_id = str(_apps_by_name(instance)["Web"]["projectId"])
    before = set(instance.apps)

    seen = zitadel.check_login_version_redirects(project_id=project_id, base_uri=V2_BASE_URI)

    assert "/ui/login/login?authRequestID=" in seen["undeclared"]
    assert seen["declared"].startswith(f"{V2_BASE_URI}/login?authRequest=V2_")
    made = set(instance.apps) - before
    assert len(made) == 1
    assert made <= instance.deactivated_apps
    # And never the real Web application, whose declaration is untouched.
    assert _login_version(instance, "Web") is None


@pytest.mark.django_db(transaction=True)
def test_the_login_client_check_reports_the_credentials_roles(instance: FakeZitadel) -> None:
    """M2: whether this deployment's credential may finalize a v2 sign-in.

    A read rather than an attempted finalize: a real finalize needs a real auth
    request and a real session, so measuring it directly would mean signing
    somebody in, and the role is the whole of what the 403 is about.
    """
    machine = str(instance.machine["id"])

    assert zitadel.check_login_client_role()["may_finalize"] is True

    instance.instance_members[machine] = ["IAM_OWNER"]
    seen = zitadel.check_login_client_role()
    assert seen["may_finalize"] is False
    assert seen["roles"] == ["IAM_OWNER"]
    assert seen["login_name"] == "djb-platform"
