# census: cross-app population=templates/**/*.html,config/settings/*.py,uv.lock walks every *.html
"""The entrance chain: one shell for the whole allauth surface, and no chooser at one door.

Two properties, and neither of them is "a page renders".

**The first is a CENSUS, not a list.** The defect was that exactly one allauth
page in this tree was styled and every other one — sign-out, the third-party
failure page, the cancellation page, the password flows, the MFA screens — was
a browser default inside an otherwise finished product. A fix that overrode the
pages somebody thought of loses the same way the defect was created: allauth 65
ships thirty-odd of them and adds more every minor version, so the test has to
derive the population from the INSTALLED PACKAGE and demand that every member
of it resolves through our shell, including the pages nobody here has read.
That is what makes the property survive an allauth upgrade rather than being
re-established by hand after one.

**The second is the three-state login rule.** The count of doors is the live
population — allauth's own `get_providers` over the apps this deployment
declares plus the `SocialApp` rows on this site — and the page is a different
page at nought, one and many. At one it is one action and no list; at one it is
still a PAGE, because `SOCIALACCOUNT_LOGIN_ON_GET` staying `False` is what keeps a
GET from starting an authentication flow, keeps sign-out from bouncing straight
back into sign-in, and keeps the error return from being swallowed by a
redirect.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import allauth
import pytest
from allauth.socialaccount import app_settings as social_settings
from allauth.socialaccount.models import SocialApp
from django.conf import settings as django_settings
from django.contrib.sites.models import Site
from django.template import engines
from django.template.exceptions import TemplateDoesNotExist, TemplateSyntaxError
from django.template.loader import get_template
from django.test import Client

from apps.accounts.templatetags.entrance import DEFAULT_ACCENT
from apps.core.tests.template_shape import IDENTITY_SHAPE, template_shape
from apps.core.tests.tree_census import source_text
from config.settings.base import DEFAULT_BRAND_ACCENT

pytestmark = pytest.mark.django_db


def token_marker() -> str:
    """The custom property THIS product's entrance token block declares.

    Read from the declaration (`DJB_IDENTITY_SHAPE`, key `entrance_marker`;
    `apps/core/tests/template_shape.py` is the authority) rather than pinned as a literal,
    because the string is the template's own shape and the property it proves is
    every product's: nothing else in a tree spells its shell's marker, so the
    marker's presence in a rendered document is proof that the document was
    built by that product's ONE shell and not by allauth's.

    The declaration is the test suite's own, parsed once by `apps/core/tests/template_shape.py`.
    """
    return str(IDENTITY_SHAPE["entrance_marker"])


#: `{% extends "…" %}` with a literal name. A template that extends a VARIABLE
#: is out of the census by construction and is reported rather than skipped
#: silently — allauth ships none today, and a future one would be a finding.
EXTENDS = re.compile(r"{%\s*extends\s+\"([^\"]+)\"\s*%}")

ALLAUTH_ROOT = Path(allauth.__file__).resolve().parent

#: The floor under the census, so it cannot go quietly vacuous. It is a FLOOR
#: and not the measurement: a floor below the truth is the failure mode a floor
#: exists to prevent, so it sits at a number an upgrade would have to REMOVE
#: pages to fall under, and the live count is whatever the assertion below
#: prints on the day it fails. This comment used to name that count as well, and
#: named it wrongly — which is the whole argument against a measurement written
#: in prose: it rots on the next allauth bump and nothing goes red when it does.
#: The number lives in one place, and that place is derived.
CENSUS_FLOOR = 40


def _installed_allauth_template_dirs() -> list[Path]:
    """The allauth template directories THIS deployment's loaders actually search.

    Derived off the engine rather than off the package, because which of
    allauth's provider template directories exist depends on which provider apps
    are installed — a census that globbed the package would include templates no
    loader can find and fail for a reason that is not about this tree.
    """
    dirs: list[Path] = []
    # django-stubs types `engines[...]` as the abstract `BaseEngine`, which does
    # not carry `.engine`; this is the Django backend and it does.
    backend: Any = engines["django"]
    for loader in backend.engine.template_loaders:
        for candidate in getattr(loader, "get_dirs", list)():
            path = Path(candidate).resolve()
            if ALLAUTH_ROOT in path.parents or path == ALLAUTH_ROOT:
                dirs.append(path)
    return dirs


def _allauth_template_names() -> list[str]:
    """Every template name allauth ships that this deployment can load."""
    names: set[str] = set()
    for directory in _installed_allauth_template_dirs():
        for path in directory.rglob("*.html"):
            names.add(path.relative_to(directory).as_posix())
    return sorted(names)


def _source(name: str) -> str | None:
    """The template's source, or `None` when this deployment cannot compile it.

    Two of allauth's management pages `{% templatetag openblock %} load humanize
    {% templatetag closeblock %}`, and `django.contrib.humanize` is not in
    `INSTALLED_APPS` here — so those pages raise at COMPILE time and no styling
    of ours would ever be reached. That is a fact about this deployment rather
    than a hole in the census, and `test_the_uncompilable_pages_are_named_and_few`
    below is what stops it becoming a quiet skip.
    """
    try:
        loaded: Any = get_template(name)
        return str(loaded.template.source)
    except (TemplateDoesNotExist, TemplateSyntaxError):
        return None


def _uncompilable() -> list[str]:
    return [name for name in _allauth_template_names() if _source(name) is None]


def _chain(name: str) -> list[str]:
    """The `{% extends %}` chain from `name` upward, as origin paths.

    Loop-bounded: a template that extends itself would otherwise hang the suite
    instead of failing it.
    """
    origins: list[str] = []
    seen: set[str] = set()
    current = name
    while current and current not in seen:
        seen.add(current)
        source = _source(current)
        if source is None:
            break
        loaded: Any = get_template(current)
        origins.append(str(loaded.template.origin.name))
        if token_marker() in source:
            break
        match = EXTENDS.search(source)
        current = match.group(1) if match else ""
    return origins


def _resolves_through_our_shell(name: str) -> bool:
    origins = _chain(name)
    # Through the seam, not `read_text`: this module walks directories, and a
    # file listed by the walk and gone by the open is SKIPPED rather than a
    # `FileNotFoundError` (`apps/core/tests/tree_census.py`).
    return any(token_marker() in source_text(Path(origin)) for origin in origins)


# --- the census ---------------------------------------------------------------


def test_the_census_is_not_empty_and_is_not_small() -> None:
    """The population is real. A census over nothing passes for the wrong reason."""
    names = _allauth_template_names()
    chained = [name for name in names if (source := _source(name)) and EXTENDS.search(source)]
    assert len(chained) >= CENSUS_FLOOR, (
        f"only {len(chained)} of {len(names)} allauth templates extend anything — "
        "the census has lost its population, not its subject"
    )


def test_the_uncompilable_pages_are_named_and_few() -> None:
    """The census's own blind spot, stated rather than skipped.

    A page this deployment cannot compile is a page nobody can reach here, so it
    is honestly out of the population — but the number is pinned so that an
    upgrade which broke twenty of them reads as a failure instead of as a census
    that quietly shrank.
    """
    assert _uncompilable() == [
        "mfa/webauthn/authenticator_list.html",
        "usersessions/usersession_list.html",
    ]


def test_every_installed_allauth_page_resolves_through_our_shell() -> None:
    """Each one, by name, with the ones that do not listed.

    The assertion is on the whole set rather than parametrised per name because
    the finding a reader needs is "these four pages fell out", not four separate
    failures they have to collate.
    """
    escaped: list[str] = []
    for name in _allauth_template_names():
        source = _source(name)
        if source is None or not EXTENDS.search(source):
            # A fragment (an element or a snippet, included and never rendered
            # alone), or a page this deployment cannot compile at all.
            continue
        if not _resolves_through_our_shell(name):
            escaped.append(f"{name} -> {' -> '.join(_chain(name))}")
    assert not escaped, "allauth pages that render outside the entrance shell:\n" + "\n".join(
        escaped
    )


def test_the_census_covers_pages_this_tree_never_wrote() -> None:
    """The point of overriding the BASE rather than the pages.

    Four pages nobody here has authored, each of which a person can reach, and
    none of which appears anywhere in `templates/`.
    """
    ours = {
        path.relative_to(Path(django_settings.BASE_DIR) / "templates").as_posix()
        for path in (Path(django_settings.BASE_DIR) / "templates").rglob("*.html")
    }
    never_written = [
        "account/password_reset.html",
        "account/signup_closed.html",
        "account/verification_sent.html",
        "mfa/authenticate.html",
    ]
    for name in never_written:
        assert name not in ours, f"{name} is in templates/ — pick a page we really never wrote"
        assert _resolves_through_our_shell(name), f"{name} renders outside the entrance shell"


# --- the shell itself ---------------------------------------------------------


@template_shape("entrance_marker")
def test_the_shell_fetches_nothing(client: Client) -> None:
    """No stylesheet, no font, no script. The design is the inline token block.

    A token block that arrives is a token block that cannot fail to load, which
    is the entire reason the font is `system-ui` and there is one `<style>`
    element instead of a link.
    """
    body = client.get("/accounts/login/").content.decode()
    assert token_marker() in body
    assert "<link" not in body
    assert "<script" not in body
    assert "https://" not in body


@template_shape("entrance_marker")
def test_the_shell_declares_both_themes(client: Client) -> None:
    """A surface pair and `color-scheme`, so a dark-mode browser is not handed white."""
    body = client.get("/accounts/login/").content.decode()
    assert "color-scheme: light dark" in body
    assert "prefers-color-scheme: dark" in body


def test_the_accent_is_the_declared_one(client: Client, settings: Any) -> None:
    """`BRAND_ACCENT` reaches the rendered page: declared once, consumed here.

    Asserted on the accent VALUE inside this product's own token block, and not
    on the property spelling `--accent:`. The spelling is one shell's private
    vocabulary — a product that draws its own entrance names its custom
    properties whatever it likes — while "the declared colour reaches the
    document the shell built" is the property every product has to hold. The
    block is located by the declared marker (`entrance_marker`), which is what
    stops this passing on a page our shell never touched.
    """
    settings.BRAND_ACCENT = "#123456"
    body = client.get("/accounts/login/").content.decode()
    assert token_marker() in body
    assert "#123456" in body


def test_a_junk_accent_falls_back_rather_than_breaking_the_block(
    client: Client, settings: Any
) -> None:
    """A value that is not a colour must not end the declaration and eat the rest."""
    settings.BRAND_ACCENT = "red; } body { display: none"
    body = client.get("/accounts/login/").content.decode()
    assert token_marker() in body
    assert "display: none" not in body
    assert DEFAULT_ACCENT in body


@template_shape("template_files")
def test_the_two_copies_of_the_shipped_accent_agree() -> None:
    """One declared value, and it is written down twice — so pin them together.

    `config/settings/base.py` holds the SHIPPED default and
    `apps/accounts/templatetags/entrance.py` holds the LAST-RESORT fallback for
    a value that is not a colour. They are the same string and they are in two
    files, which is a drift that would show up as a clone whose entrance chain
    and whose malformed-value fallback are different greys.
    """
    assert DEFAULT_ACCENT == DEFAULT_BRAND_ACCENT


# --- the three-state login rule -----------------------------------------------


def _doors(count: int) -> None:
    """Make the live provider population exactly `count`. Rows, not settings."""
    SocialApp.objects.all().delete()
    site = Site.objects.get_current()
    for index in range(count):
        app = SocialApp.objects.create(
            provider="openid_connect",
            provider_id=f"idp{index}",
            name=f"Identity {index}",
            client_id=f"client-{index}",
            secret="",  # pragma: allowlist secret
            settings={"server_url": "https://id.example.test"},
        )
        app.sites.add(site)


@template_shape("login_page")
def test_no_provider_keeps_the_operator_sentence(client: Client) -> None:
    """Nought doors: say what is missing and who fixes it. Never a blank page.

    **And the remedy has to be the one that WORKS.** The page used to name
    `./scripts/setup.sh` and say it "writes the client id into `.env`". It does
    not: that script's whole `env_set` census is `ZITADEL_PAT`,
    `DATABASE_NAME`, `ZITADEL_MCP_AUDIENCE` and `AWS_STORAGE_BUCKET_NAME`, so a
    stranger who ran it landed back on this same page with the same sentence —
    a closed loop whose one instruction is the command that just succeeded. The
    step that actually changes the state is a person pasting the two values the
    seed printed, so the page names those two variables by the names `.env`
    knows them by, and the assertions below are what keeps it naming them.
    """
    _doors(0)
    body = client.get("/accounts/login/").content.decode()
    assert "no sign-in provider configured yet" in body
    assert "./scripts/setup.sh" in body
    assert "ZITADEL_CLIENT_ID" in body
    assert "ZITADEL_CLIENT_SECRET" in body
    # Collapsed, because the false clause used to straddle a line break — which
    # is also why the plain grep for it in the criteria set could never fail.
    collapsed = " ".join(body.split())
    assert "writes the client id" not in collapsed
    assert "<li>" not in body


@template_shape("login_page")
def test_one_provider_is_one_action_and_no_chooser(client: Client) -> None:
    """The defect the entrance survey measured: a bulleted list with one bullet in it."""
    _doors(1)
    body = client.get("/accounts/login/").content.decode()
    assert "Continue with Identity 0" in body
    assert "<li>" not in body, "a chooser at one door is a decision that does not exist"
    assert 'class="button"' in body


@template_shape("login_page")
def test_one_provider_names_the_hosted_hop(client: Client) -> None:
    """The seam is told, not smoothed: the person is about to leave this site."""
    _doors(1)
    body = client.get("/accounts/login/").content.decode()
    assert "identity platform" in body


def test_one_provider_is_still_a_page(client: Client) -> None:
    """Not a 302. Login-CSRF, the logout loop and the error return, in one line."""
    _doors(1)
    response = client.get("/accounts/login/")
    assert response.status_code == 200
    assert social_settings.LOGIN_ON_GET is False


@template_shape("login_page")
def test_two_providers_bring_the_chooser_back(client: Client) -> None:
    """The chooser was wrong as a default at one, never wrong as a mechanism."""
    _doors(2)
    body = client.get("/accounts/login/").content.decode()
    assert body.count("<li>") == 2
    assert "Identity 0" in body
    assert "Identity 1" in body
    assert "Continue with" not in body


@template_shape("login_page")
def test_the_count_is_the_population_and_not_a_setting() -> None:
    """Adding a row changes the page. Nothing in `.env` had to be touched.

    The rendered door count is `get_providers`' own — the apps
    `SOCIALACCOUNT_PROVIDERS` declares plus every `SocialApp` row on this site —
    so the page renders what this deployment can actually send somebody to.
    """
    client = Client()
    _doors(1)
    one = client.get("/accounts/login/").content.decode()
    _doors(2)
    two = client.get("/accounts/login/").content.decode()
    assert one.count("<li>") == 0
    assert two.count("<li>") == 2


# --- the three pages a failed or finished sign-in lands on --------------------


def test_the_sign_out_page_is_ours_and_in_register(client: Client, owner: Any) -> None:
    """The page every person sees on the way OUT, in the register they came IN through.

    allauth files sign-out under its MANAGEMENT layout, which is how the one
    screen everybody reaches ended up in a different family from the one
    everybody starts in.
    """
    client.force_login(owner)
    response = client.get("/accounts/logout/")
    assert response.status_code == 200
    body = response.content.decode()
    assert token_marker() in body
    assert "This ends your session here" in body
    assert "Menu:" not in body, "allauth's raw navigation is what the shell replaced"


def test_the_cancellation_page_is_ours_and_in_register(client: Client) -> None:
    """Somebody who pressed cancel did nothing wrong, and the page says so."""
    response = client.get("/accounts/3rdparty/login/cancelled/")
    assert response.status_code == 200
    body = response.content.decode()
    assert token_marker() in body
    assert "Sign-in cancelled" in body
    assert "Menu:" not in body


def test_the_failure_page_is_ours_and_in_register() -> None:
    """The third-party failure page, rendered directly: it answers 401 in the flow."""
    body = get_template("socialaccount/authentication_error.html").render({})
    assert token_marker() in body
    assert "Sign-in did not complete" in body
    assert "third-party account" not in body


def test_sso_refused_is_unregressed() -> None:
    """The app's own refusal page is untouched by all of this — its own document."""
    body = get_template("accounts/sso_refused.html").render({"reason": "because"})
    assert "Sign-in refused" in body
    assert "because" in body
