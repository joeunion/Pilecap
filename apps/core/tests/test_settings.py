"""What the settings layer promises: discovery, and what production refuses.

Two things are proved here that cannot be seen from a diff:

* `INSTALLED_APPS` is derived from the tree, so adding an app is adding a
  directory — no shared file to collide on;
* production refuses the *published* development secrets, not merely absent
  ones. `.env.example` is read from disk for that, so the guard and the file
  cannot drift apart without this failing.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from typing import Any
from unittest import mock
from urllib.parse import urlsplit

import environ
import pytest
from csp.middleware import CSPMiddleware
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.db import connection
from django.http import HttpResponse
from django.test import Client, RequestFactory, override_settings
from django.test.utils import CaptureQueriesContext

import apps as apps_package
from apps.accounts.management.commands import zitadel_seed
from apps.core.models import Tenant
from apps.core.tests.settings_env import (
    IDENTITY_KEY_PREFIXES,
    PRODUCTION_ENVIRONMENT,
    _settings_module,
    identity_keys_base_reads,
)
from config.settings.base import DEFAULT_BRAND_ACCENT, read_template_version
from config.settings.base import _env_file as SETTINGS_ENV_FILE
from config.settings.discovery import DEFAULT_ORDER, discover_apps, discover_local_apps
from config.settings.guards import (
    DEV_CONNECTIONS_ENCRYPTION_KEY,
    DEV_DATABASE_PASSWORD,
    DEV_SECRET_KEY,
    check_connections_encryption_key,
    check_database_password,
    check_secret_key,
    refuse_development_defaults,
)

BASE_DIR = Path(settings.BASE_DIR)
APPS_DIR = BASE_DIR / "apps"

PROBE = "zzz_probe"
PROBE_MODULE = f"apps.{PROBE}"
PROBE_APPS_PY = """from django.apps import AppConfig


class ZzzProbeConfig(AppConfig):
    name = "apps.zzz_probe"
    depends_on: tuple[str, ...] = ("core",)
"""

# --- Registration by discovery ----------------------------------------------


def test_installed_apps_is_what_the_tree_contains() -> None:
    """No hand-written LOCAL_APPS: the list and the directory agree by construction."""
    discovered = discover_local_apps(APPS_DIR)
    assert discovered == list(settings.LOCAL_APPS)
    for name in discovered:
        assert name in settings.INSTALLED_APPS


def test_the_foundation_comes_first_and_the_rest_is_alphabetical() -> None:
    labels = [app.label for app in discover_apps(APPS_DIR)]
    assert labels[:2] == ["core", "accounts"]
    assert labels[2:] == sorted(labels[2:])


def test_every_app_declares_what_it_may_import() -> None:
    declared = {app.label: app.depends_on for app in discover_apps(APPS_DIR)}
    # `core` imports nothing above it; that is the whole of its contract.
    assert declared["core"] == ()
    for label, depends_on in declared.items():
        if label == "core":
            continue
        assert "core" in depends_on, f"{label} declares no dependency on core"
        assert label not in depends_on


def test_an_explicit_order_wins_over_the_alphabet(tmp_path: Path) -> None:
    for label, body in (
        ("alpha", "class AlphaConfig(AppConfig):\n    name = 'apps.alpha'\n"),
        ("omega", "class OmegaConfig(AppConfig):\n    name = 'apps.omega'\n    order = 1\n"),
    ):
        app_dir = tmp_path / label
        app_dir.mkdir()
        (app_dir / "apps.py").write_text(f"from django.apps import AppConfig\n\n\n{body}")
    assert discover_local_apps(tmp_path) == ["apps.omega", "apps.alpha"]


def test_a_directory_without_an_app_config_is_not_an_app(tmp_path: Path) -> None:
    (tmp_path / "notanapp").mkdir()
    (tmp_path / "notanapp" / "apps.py").write_text("VALUE = 1\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "nothing").mkdir()
    assert discover_local_apps(tmp_path) == []


def test_depends_on_is_read_off_the_app_config(tmp_path: Path) -> None:
    app_dir = tmp_path / "thing"
    app_dir.mkdir()
    (app_dir / "apps.py").write_text(
        "from django.apps import AppConfig\n\n\n"
        "class ThingConfig(AppConfig):\n"
        "    name = 'apps.thing'\n"
        "    depends_on: tuple[str, ...] = ('core', 'accounts')\n"
    )
    (found,) = discover_apps(tmp_path)
    assert found.depends_on == ("core", "accounts")
    assert found.order == DEFAULT_ORDER


@pytest.fixture
def probe_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """`apps.zzz_probe` under `tmp_path`, on the `apps` package's path for this test only.

    Never in the real `apps/`: a sibling worker's discovery would boot an app that then vanishes.
    """
    root = tmp_path / "apps"
    app_dir = root / PROBE
    app_dir.mkdir(parents=True)
    (app_dir / "__init__.py").write_text("")
    (app_dir / "apps.py").write_text(PROBE_APPS_PY)
    _forget_probe_modules()
    monkeypatch.setattr(apps_package, "__path__", [*apps_package.__path__, str(root)])
    importlib.invalidate_caches()
    try:
        yield root
    finally:
        _forget_probe_modules()
        importlib.invalidate_caches()


def _forget_probe_modules() -> None:
    """Drop `apps.zzz_probe` and its submodules from `sys.modules`."""
    for name in [m for m in sys.modules if m == PROBE_MODULE or m.startswith(f"{PROBE_MODULE}.")]:
        del sys.modules[name]


@pytest.mark.django_db
def test_a_new_app_appears_without_anyone_editing_settings(probe_app: Path) -> None:
    """A directory with an `AppConfig` is an app: discovery finds it and `introspect` reports it."""
    discovered = discover_local_apps(probe_app)
    assert discovered == [PROBE_MODULE]

    with override_settings(INSTALLED_APPS=[*settings.INSTALLED_APPS, *discovered]):
        out = StringIO()
        call_command("introspect", stdout=out)
        payload: dict[str, Any] = json.loads(out.getvalue())

    assert PROBE in payload["apps"]


# --- What production refuses -------------------------------------------------


def _env_example() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (BASE_DIR / ".env.example").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def test_production_refuses_the_secret_key_that_ships_in_env_example() -> None:
    """Read from the file, so the guard cannot drift away from what people copy."""
    shipped = _env_example()["SECRET_KEY"]
    assert shipped == DEV_SECRET_KEY
    with pytest.raises(RuntimeError, match="public"):
        check_secret_key(shipped)


def test_production_refuses_the_encryption_key_that_ships_in_env_example() -> None:
    shipped = _env_example()["CONNECTIONS_ENCRYPTION_KEY"]
    assert shipped == DEV_CONNECTIONS_ENCRYPTION_KEY
    with pytest.raises(RuntimeError, match="published in"):
        check_connections_encryption_key(shipped)


def test_production_still_refuses_an_absent_key() -> None:
    with pytest.raises(RuntimeError):
        check_secret_key("")
    with pytest.raises(RuntimeError):
        check_connections_encryption_key("")


def test_production_refuses_the_key_the_test_suite_runs_on(settings: Any) -> None:
    """The tree under test must not be deployable as it stands."""
    with pytest.raises(RuntimeError):
        check_secret_key(settings.SECRET_KEY)
    with pytest.raises(RuntimeError):
        check_connections_encryption_key(settings.CONNECTIONS_ENCRYPTION_KEY)


#: A real-looking key: strong enough that `refuse_development_defaults` accepts it,
#: and not a secret — it exists to be accepted here and nowhere else. It lives at
#: module level because the pragma and the 64-hex literal do not fit one line.
A_REAL_SECRET_KEY = "0f7c3ae1e0f0a2b6c5d4e3f201928374655647382910abcdeff0123456789abcd"  # noqa: S105 — a signing secret the test both signs and verifies with  # pragma: allowlist secret


def test_a_real_pair_of_keys_is_accepted() -> None:
    from cryptography.fernet import Fernet

    refuse_development_defaults(
        secret_key=A_REAL_SECRET_KEY,
        connections_encryption_key=Fernet.generate_key().decode(),
    )


#: A DATABASE_URL carrying the published password — the exact shape the parts
#: check does NOT cover, which is what the test below asserts. Module level so
#: the pragma and the URL fit one line; the value is `.env.example`'s own.
A_PUBLISHED_DATABASE_URL = "postgres://djb:djb@127.0.0.1:5432/djb_probe"  # pragma: allowlist secret


def test_production_refuses_the_database_password_that_ships_in_env_example() -> None:
    """Read from the file, so the guard cannot drift from what people copy."""
    shipped = _env_example()["DATABASE_PASSWORD"]
    assert shipped == DEV_DATABASE_PASSWORD
    with pytest.raises(RuntimeError, match="public"):
        check_database_password(shipped)


def test_the_forgotten_database_password_is_the_published_one() -> None:
    """The absent case and the published case are one case, by construction.

    `config.settings.base` defaults DATABASE_PASSWORD to the guards constant, so
    a parts-configured deployment that never sets the variable is holding the
    published value — which is the same published-password deployment case
    above, and it is refused by the same comparison rather than by a second
    check that could drift.
    """
    with _settings_module("config.settings.base") as base:
        assert base.DATABASE_PASSWORD == DEV_DATABASE_PASSWORD

    with pytest.raises(RuntimeError, match="public"):
        check_database_password(DEV_DATABASE_PASSWORD)
    with pytest.raises(RuntimeError, match="must be set"):
        check_database_password("")


def test_a_generated_database_password_is_accepted() -> None:
    check_database_password("Yb2f5Qn8kR3wLd7ZpA1sT6vX")  # pragma: allowlist secret


def test_a_url_configured_deployment_is_outside_the_password_check() -> None:
    """DATABASE_URL wins over the parts, so there is no parts password to refuse.

    `base` decides the population — not `guards`, which is handed one value and
    cannot see which source won — and says so by passing `None`. The belt for a
    published password living inside a URL is the deployment's own start-up
    assertion, where the whole URL is in hand.
    """
    from cryptography.fernet import Fernet

    fernet = Fernet.generate_key().decode()

    with _settings_module("config.settings.base", DATABASE_URL=A_PUBLISHED_DATABASE_URL) as base:
        assert base._parts_database_password is None
        refuse_development_defaults(
            secret_key=A_REAL_SECRET_KEY,
            connections_encryption_key=fernet,
            database_password=base._parts_database_password,
        )

    with _settings_module("config.settings.base", DATABASE_NAME="djb_probe") as base:
        assert base._parts_database_password == base.DATABASE_PASSWORD


# --- The proxy header --------------------------------------------------------


def test_the_proxy_header_is_off_unless_the_deployment_says_it_is_behind_one() -> None:
    """Trusting `X-Forwarded-Proto` from anyone makes every HTTPS check a lie.

    **Both branches, imported under a cleared and a set environment**, rather
    than one assertion off live settings. `BEHIND_PROXY` is an `env.bool` read,
    so `assert settings.BEHIND_PROXY is False` reported the machine the suite ran
    on: green on a laptop that never set the variable, red on the first checkout
    that did — and, worse, silently vacuous about the half that matters, because
    a deployment that DOES set it never reached this test at all. The same class
    as the landing seam below, and the same fix.
    """
    # `SECURE_PROXY_SSL_HEADER` is bound only INSIDE `if BEHIND_PROXY:`, and
    # `importlib.reload` re-executes a module WITHOUT clearing its namespace —
    # so a name an earlier import bound survives a reload that does not rebind
    # it. Measured, not assumed: with `BEHIND_PROXY=1` ambient, the cleared
    # branch below read the header off the import Django did at start-up and
    # the negative was unfalsifiable. Dropping the stale binding first is what
    # makes the branch ask what THIS import did. Any future setting bound under
    # an `if` in `base.py` owes the same line to be testable this way.
    stale = importlib.import_module("config.settings.base")
    had_header = hasattr(stale, "SECURE_PROXY_SSL_HEADER")
    if had_header:
        del stale.SECURE_PROXY_SSL_HEADER

    with _settings_module("config.settings.base", BEHIND_PROXY=None) as base:
        assert base.BEHIND_PROXY is False
        assert getattr(base, "SECURE_PROXY_SSL_HEADER", None) is None

    with _settings_module("config.settings.base", BEHIND_PROXY="1") as base:
        assert base.BEHIND_PROXY is True
        assert base.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")

    # And left as it was found, for the same reload reason in the other
    # direction: the branch above BOUND the header, and the reload back to the
    # original environment will not unbind it.
    restored = importlib.import_module("config.settings.base")
    if not had_header and hasattr(restored, "SECURE_PROXY_SSL_HEADER"):
        del restored.SECURE_PROXY_SSL_HEADER

    assert "BEHIND_PROXY" in _env_example()


SECURITY_WAVE_KEYS = (
    "SESSION_IDLE_SECONDS",
    "WEBHOOK_PRIVATE_TARGETS_ALLOWED",
    "REALTIME_MAX_SOCKETS_PER_CREDENTIAL",
    "REALTIME_MAX_SOCKETS_PER_TENANT",
    "REALTIME_JOIN_LEASE_SECONDS",
)


@pytest.mark.parametrize(
    ("module", "private_targets"),
    [
        ("config.settings.production", False),
        ("config.settings.local", True),
        ("config.settings.test", False),
    ],
)
def test_the_security_wave_settings_resolve_to_their_defaults(
    module: str, private_targets: bool
) -> None:
    """A session idles out after 900 s; only a laptop lets a webhook reach private space."""
    cleared: dict[str, str | None] = dict.fromkeys(SECURITY_WAVE_KEYS)
    if module == "config.settings.production":
        cleared = {**PRODUCTION_ENVIRONMENT, **cleared}
    with _settings_module(module, **cleared) as loaded:
        assert loaded.SESSION_IDLE_SECONDS == 900
        assert loaded.SESSION_COOKIE_AGE == 900
        assert loaded.SESSION_SAVE_EVERY_REQUEST is False  # the slide is the middleware's (B)
        assert loaded.WEBHOOK_PRIVATE_TARGETS_ALLOWED is private_targets
        assert loaded.REALTIME_MAX_SOCKETS_PER_CREDENTIAL == 10
        assert loaded.REALTIME_MAX_SOCKETS_PER_TENANT == 500
        assert loaded.REALTIME_JOIN_LEASE_SECONDS == 90
    assert set(SECURITY_WAVE_KEYS) - set(_env_example()) == set(), "undocumented in .env.example"


# --- Static files and object storage -----------------------------------------


def test_the_production_environment_pins_every_identity_key_base_reads() -> None:
    """Completeness as a census, not as a list somebody remembered to extend.

    The population comes out of `base.py` itself; a key this dict is silent on
    is a key the machine underneath the test answers for. Both halves are worth
    failing on: a key `base` reads and the dict does not name (the next leak),
    and a key the dict names that `base` no longer reads (a pin outliving its
    setting, which reads as coverage and is not).
    """
    read_by_base = identity_keys_base_reads()
    pinned = {key for key in PRODUCTION_ENVIRONMENT if key.startswith(IDENTITY_KEY_PREFIXES)}

    assert read_by_base, "the census found no identity keys at all — it stopped looking"
    assert read_by_base - pinned == set(), "identity keys base reads that the dict does not pin"
    assert pinned - read_by_base == set(), "keys pinned here that base no longer reads"


PLANTED_CLIENT_ID = "planted-by-the-test"


def test_a_cleared_key_is_gone_from_the_process_environment() -> None:
    """Half one of the mechanism the completeness rests on, driven both ways."""
    with mock.patch.dict(os.environ, {"ZITADEL_CLIENT_ID": PLANTED_CLIENT_ID}):
        with _settings_module("config.settings.base") as base:
            assert base.ZITADEL_CLIENT_ID == PLANTED_CLIENT_ID

        with _settings_module("config.settings.base", ZITADEL_CLIENT_ID=None) as base:
            assert base.ZITADEL_CLIENT_ID == ""


def test_a_cleared_key_is_gone_from_the_env_file_too() -> None:
    """Half two, and the half nobody would think to write.

    `.env` is a SECOND source, and `environ.Env.read_env` SETDEFAULTS: a key
    popped from the process environment is handed straight back by the reload,
    so clearing that only pops would be clearing that does nothing on exactly
    the checkout it exists for — one whose `.env` names a client id. This tree's
    own `.env` ships that line EMPTY, so the difference is invisible here and
    would first be seen by a product that had configured sign-in, which is the
    audience the pin is for.

    So the test builds its own victim rather than editing anything: a stand-in
    for `read_env` that supplies a configured value the way a configured `.env`
    would, and the assertion is that the import still could not see it.

    **The stand-in stands in for the whole SOURCE, file included, and that is
    what makes the test say the same thing on a runner as on a laptop.**
    `base.py` reads the file conditionally — `if _env_file.is_file():
    env.read_env(...)` — so a stand-in for the CALL alone is inert on any
    checkout that has no `.env`: the call never happens, the plant never lands,
    and the control assertion below reads the `env.str` default instead. That is
    not hypothetical. GitHub's `gate` job on 76fb372e (run 35051950098) failed
    here and nowhere else — `assert '' == 'planted-by-the-test'`, 3,812 passed —
    because CI sets the environment from `.env.example`'s values and writes no
    `.env` at all, while every local bank was green on a checkout that has one.
    A test whose verdict is whether the machine it ran on happens to have a file
    is the same defect `_settings_module`'s clearing was written to end, one
    level out. So the pair below stands in for both halves — the file IS there
    (`_the_env_file_is_there`) and it says this (`_configured_env_file`) — and
    the presence half answers for `.env` and for nothing else, delegating every
    other path to the real `is_file` so no other file consulted during the
    reload is answered for by this test.
    """

    def _configured_env_file(_self: Any, *args: Any, **kwargs: Any) -> None:
        """What `read_env` does on a checkout whose `.env` names a client id.

        Assigned rather than `setdefault`ed, and that is not a shortcut: this
        tree's `.env` ships the line EMPTY, so the session's very first import
        has already put `""` in `os.environ` and a stand-in that setdefaulted
        would quietly do nothing at all — a plant that cannot fail standing in
        for a source that can.
        """
        os.environ["ZITADEL_CLIENT_ID"] = PLANTED_CLIENT_ID

    # THE PATH IS ASKED OF THE MODULE THAT READS IT, never rebuilt here.
    # `base.py` owns the name — `_env_file = BASE_DIR / ".env"` is the very
    # path whose `is_file()` the stand-in below answers for — so a hand-built
    # `BASE_DIR / ".env"` here is a second opinion about it: green on the day it
    # is written, and silently answering for nothing the day `base.py` moves or
    # renames the file it reads.
    #
    # It is also the only form the platform partition can place, and that is
    # what made this a hotfix rather than a tidy-up. `.env` is ignored and
    # per-checkout, so `quality/partition.py::tree_paths()` — tracked files plus
    # untracked-NON-IGNORED ones — never sees it: a closure class naming `.env`
    # alone is exit 2 for matching nothing in the tree, and `.env` appended to
    # an existing class is dropped in silence while the read census (§3) goes on
    # reporting the same stray. There was no closure class this read could have
    # joined. Asking the settings module instead puts the read inside `config/**`,
    # which class C3 already covers, and the test says exactly what it meant.
    env_file = SETTINGS_ENV_FILE
    real_is_file = Path.is_file

    def _the_env_file_is_there(self: Path, *args: Any, **kwargs: Any) -> bool:
        """`.env` exists — for `.env` only, and for nothing else on disk."""
        if self == env_file:
            return True
        return real_is_file(self, *args, **kwargs)

    # `mock.patch.dict` with nothing to add is doing the whole of its other job:
    # it snapshots `os.environ` and puts it back. `_settings_module` reloads
    # `base` one last time on the way out, after its own snapshot has been
    # restored, and that reload runs the stand-in above — so without this the
    # plant would outlive the test and every later case in the session would
    # read a configured client id.
    with mock.patch.dict(os.environ, {}):
        with mock.patch.object(Path, "is_file", _the_env_file_is_there):
            with mock.patch.object(environ.Env, "read_env", _configured_env_file):
                # The control: nothing cleared, and the planted file reaches settings.
                with _settings_module("config.settings.base") as base:
                    assert base.ZITADEL_CLIENT_ID == PLANTED_CLIENT_ID

                with _settings_module("config.settings.base", ZITADEL_CLIENT_ID=None) as base:
                    assert base.ZITADEL_CLIENT_ID == ""


def test_whitenoise_sits_immediately_after_the_security_middleware() -> None:
    """Above it, a static response would miss the security headers; below it, a
    request for a CSS file would travel through sessions, auth and tenancy."""
    order = list(settings.MIDDLEWARE)
    security = order.index("django.middleware.security.SecurityMiddleware")

    assert order[security + 1] == "whitenoise.middleware.WhiteNoiseMiddleware"


def test_a_product_base_url_moves_where_sign_in_lands() -> None:
    """The landing seam, ALL THREE branches, by importing settings under each one.

    `LOGIN_REDIRECT_URL` is DERIVED from `PRODUCT_BASE_URL`: unset, it
    is the shipped placeholder at `/welcome/` and a clone with no front end pays
    nothing; set, the same completed sign-in lands at the product instead, with
    nothing in `apps/` or `templates/` changed. Only importing the module under
    the environment can see those branches — asserting on the live value would
    only assert that today's environment is today's environment.

    **THE THIRD BRANCH IS THE ONE THAT SHIPPED BROKEN, AND IT IS THE REASON THIS
    TEST HAS THREE.** `PRODUCT_BASE_URL` is not absent on a fresh clone: it is
    PRESENT AND EMPTY, because `.env.example` ships the line and every entry
    point copies that file to `.env`. `env.str(..., default=PUBLIC_BASE_URL)`
    fires its default only on ABSENCE, so the value came out `""` and
    `LOGIN_REDIRECT_URL` derived to `""` — every completed sign-in in a fresh
    clone redirected to nowhere, and the two-branch version of this test was
    green throughout because the worktree it ran in had a `.env` predating the
    line. Present-but-empty defeating a `default=` is a twice-evidenced
    cross-product class; the branch below is what makes this seam's version of
    it fail loudly instead of shipping again.
    """
    # CLEARED, not merely unmentioned. An environment this branch is silent
    # about is one the checkout's own `.env` answers for, and a checkout that
    # declares a front end turned "unset derives to the placeholder" into
    # "today's environment is today's environment" — green or red according to
    # the machine. `None` is `_settings_module`'s clear, and it is what makes
    # the answer the derivation's.
    with _settings_module("config.settings.base", PRODUCT_BASE_URL=None) as base:
        assert base.PRODUCT_BASE_URL == base.PUBLIC_BASE_URL
        assert base.LOGIN_REDIRECT_URL == "/welcome/"

    with _settings_module(
        "config.settings.base", PRODUCT_BASE_URL="https://app.example.test/"
    ) as base:
        assert base.PRODUCT_BASE_URL == "https://app.example.test"
        assert base.LOGIN_REDIRECT_URL == "https://app.example.test"

    # The fresh clone: the variable is SET, to the empty string, exactly as
    # `cp .env.example .env` leaves it.
    with _settings_module("config.settings.base", PRODUCT_BASE_URL="") as base:
        assert base.PRODUCT_BASE_URL == base.PUBLIC_BASE_URL
        assert base.LOGIN_REDIRECT_URL == "/welcome/"


#: One deployment's environment, bound and unbound: the listed values the
#: operator typed, and a surface map with an exact host and a `{tenant}` host.
LISTED_HOSTS = {
    "ALLOWED_HOSTS": "sales.example.test,127.0.0.1",
    "CSRF_TRUSTED_ORIGINS": "https://sales.example.test",
    "PUBLIC_BASE_URL": "https://sales.example.test:8443",
}
BOUND_SURFACES = "staff=sales.example.test,customer=customer.example.test,club={tenant}.clubs.test"


def test_every_bound_surface_host_is_an_allowed_host() -> None:
    """`ALLOWED_HOSTS` gains every host `SURFACE_HOSTS` binds; unbound, it is what was listed.

    A customer host the map names but the admitted list does not is a surface
    that answers 400 before the resolver ever sees it — the map and the list
    are one fact, so the list is derived from the map. A `{tenant}` host is
    admitted as its parent domain; the resolver narrows it to the pattern.
    """
    with _settings_module("config.settings.base", **LISTED_HOSTS, SURFACE_HOSTS=None) as base:
        assert base.ALLOWED_HOSTS == LISTED_HOSTS["ALLOWED_HOSTS"].split(",")

    with _settings_module(
        "config.settings.base", **LISTED_HOSTS, SURFACE_HOSTS=BOUND_SURFACES
    ) as base:
        listed = LISTED_HOSTS["ALLOWED_HOSTS"].split(",")
        assert base.ALLOWED_HOSTS[: len(listed)] == listed
        assert set(base.ALLOWED_HOSTS) == {
            *listed,
            *(host for host in base.SURFACE_HOSTS.values() if "{tenant}" not in host),
            ".clubs.test",
        }
        assert len(base.ALLOWED_HOSTS) == len(set(base.ALLOWED_HOSTS))


def test_every_bound_surface_origin_is_a_trusted_origin() -> None:
    """`CSRF_TRUSTED_ORIGINS` gains every bound host in `PUBLIC_BASE_URL`'s scheme and port.

    Unbound it is exactly what was listed. Bound, a form posted from the
    customer host is trusted the way one from the staff host already was — the
    scheme and the port are the ones every link to that surface is built with.
    """
    with _settings_module("config.settings.base", **LISTED_HOSTS, SURFACE_HOSTS=None) as base:
        assert base.CSRF_TRUSTED_ORIGINS == LISTED_HOSTS["CSRF_TRUSTED_ORIGINS"].split(",")

    with _settings_module(
        "config.settings.base", **LISTED_HOSTS, SURFACE_HOSTS=BOUND_SURFACES
    ) as base:
        base_url = urlsplit(LISTED_HOSTS["PUBLIC_BASE_URL"])
        assert set(base.CSRF_TRUSTED_ORIGINS) == {
            *LISTED_HOSTS["CSRF_TRUSTED_ORIGINS"].split(","),
            *(
                f"{base_url.scheme}://{host}:{base_url.port}"
                for host in base.SURFACE_HOSTS.values()
                if "{tenant}" not in host
            ),
            f"{base_url.scheme}://*.clubs.test:{base_url.port}",
        }
        assert len(base.CSRF_TRUSTED_ORIGINS) == len(set(base.CSRF_TRUSTED_ORIGINS))


#: Every `SURFACE_HOSTS` shape the identity-home drive binds, each with the
#: `PUBLIC_BASE_URL` it runs under (`quality/tests/test_identity_home.py`
#: exports the hosts and builds the base URL from the staff host and its port),
#: plus the production shape of the same map: https, no port.
SURFACE_SHAPES = (
    ("staff=localhost,customer=customer.localhost", "http://localhost:8123"),
    ("staff=localhost,customer=customer.localhost", "https://localhost"),
    ("customer=customer.localhost", "http://localhost:8123"),
)


@pytest.mark.parametrize(("hosts", "base_url"), SURFACE_SHAPES)
def test_the_trusted_origins_and_the_sign_in_bases_are_one_derivation(
    hosts: str, base_url: str, settings: Any
) -> None:
    """Settings' trusted origins and `surface_base_urls()` name the same origins.

    Two derivations of one fact: `base.py` folds each bound host into
    `CSRF_TRUSTED_ORIGINS` (it runs before any app exists), and
    `core.surfaces.surface_base_urls()` builds each surface's base with
    `absolute_url` for the identity platform's redirect registrations. A
    browser that finishes a sign-in at a surface's base and then posts a form
    there needs both to name that origin; this holds them equal over every
    shape the drive uses, so a change to either alone is red here.
    """
    from apps.core.surfaces import surface_base_urls
    from config.settings.base import _surface_hosts, _surface_names, _surface_origins

    bound = _surface_hosts(hosts)
    settings.SURFACE_HOSTS = bound
    settings.PUBLIC_BASE_URL = base_url

    trusted = [
        origin for origin in _surface_origins(_surface_names(bound), base_url) if "*" not in origin
    ]
    assert trusted, f"{hosts} binds no exact host — the shape proves nothing"
    assert set(surface_base_urls()) == {base_url, *trusted}


def test_an_empty_brand_accent_falls_back_rather_than_shipping_nothing() -> None:
    """The seam's other variable, given the same treatment for the same reason.

    `.env.example` ships a real colour here, so this branch is not broken today
    — it is pinned so that an operator clearing the line gets the shipped
    neutral rather than an empty custom property.
    """
    with _settings_module("config.settings.base", BRAND_ACCENT="") as base:
        assert base.BRAND_ACCENT == base.DEFAULT_BRAND_ACCENT

    with _settings_module("config.settings.base", BRAND_ACCENT="#abcdef") as base:
        assert base.BRAND_ACCENT == "#abcdef"


def test_the_env_example_lines_this_seam_ships_are_really_what_a_clone_gets() -> None:
    """Read the FILE, not the environment: the empty line is the thing under test.

    `_env_example()` parses `.env.example` the way `cp .env.example .env` then
    `read_env` would, so this asserts about the shape a clone is handed rather
    than about the shape this worktree happens to have.
    """
    example = _env_example()
    assert example["PRODUCT_BASE_URL"] == "", (
        "the seam's design is that this line ships EMPTY and the derivation "
        "treats empty as absent — if it ever ships a value, the derivation's "
        "empty branch stops being the one a clone takes"
    )
    assert example["BRAND_ACCENT"] == DEFAULT_BRAND_ACCENT


def test_the_landing_seam_is_documented_where_an_operator_looks() -> None:
    """Both new variables are in `.env.example`.

    A setting a clone cannot find is a setting a clone does not have.
    """
    example = _env_example()
    assert "PRODUCT_BASE_URL" in example
    assert "BRAND_ACCENT" in example


def test_files_are_stored_on_disk_until_a_bucket_is_named() -> None:
    assert settings.STORAGES["default"]["BACKEND"] == "django.core.files.storage.FileSystemStorage"
    assert settings.AWS_STORAGE_BUCKET_NAME == ""
    assert "AWS_STORAGE_BUCKET_NAME" in _env_example()


def test_naming_a_bucket_is_the_whole_switch_to_s3() -> None:
    """No `USE_S3` flag: a deployment that set a bucket and forgot the flag
    would write uploads onto a container filesystem that disappears at the next
    deploy, and find out when somebody asked for a file back."""
    with _settings_module("config.settings.base", AWS_STORAGE_BUCKET_NAME="djb-uploads") as base:
        default = dict(base.STORAGES["default"])

    assert default["BACKEND"] == "storages.backends.s3.S3Storage"
    assert default["OPTIONS"]["bucket_name"] == "djb-uploads"
    # Private and signed: a key is not a capability anyone who guesses it holds.
    assert default["OPTIONS"]["default_acl"] is None
    # Signed on read by django-storages' own default; settings restate neither knob.
    assert "querystring_auth" not in default["OPTIONS"]
    assert "querystring_expire" not in default["OPTIONS"]
    assert default["OPTIONS"]["file_overwrite"] is False


def test_production_serves_static_from_a_compressed_manifest() -> None:
    with _settings_module("config.settings.production", **PRODUCTION_ENVIRONMENT) as production:
        staticfiles = dict(production.STORAGES["staticfiles"])
        default = dict(production.STORAGES["default"])
    with _settings_module("config.settings.base", **PRODUCTION_ENVIRONMENT) as base:
        inherited = dict(base.STORAGES["default"])

    assert staticfiles["BACKEND"] == "whitenoise.storage.CompressedManifestStaticFilesStorage"
    # `default` is inherited rather than restated, so a bucket set for
    # production still reaches it. Compared against BASE and not against live
    # settings: `config.settings.test` pins the ambient world to no object
    # storage (so that a laptop with a bucket in its .env runs CI's suite), and
    # a comparison against the active settings would then be asserting that
    # production inherits the TEST module's override rather than base's rule.
    assert default == inherited


# --- Connection reuse, i18n, and the template's own version ------------------


def test_connections_are_reused_and_checked_before_they_are_handed_out() -> None:
    """Reuse without a health check turns a failover into 500s, not reconnects.

    **Reuse is now the POOL's, and this test moved with it** (ADR config-1,
    2026-08-25). What stood here asserted `CONN_MAX_AGE == 60` and that
    `.env.example` shipped the same 60 — true until the day the measurement
    came in: under ASGI, persistent connections meant every `sync_to_async`
    thread pinned a connection nothing reclaimed (43 held against ≤4 active).
    Reuse did not stop being the point; the mechanism changed from "the thread
    keeps its socket" to "the process keeps a bounded pool of them", so the
    claim this test carries is now that the pool is what reuses and that the
    health check still guards a reused connection.

    Asserted on `config.settings.base` rather than on live settings for the
    reason it always was: `config.settings.test` deliberately runs unpooled and
    non-persistent (a held connection stops Django dropping its own test
    database), and a developer's own `.env` is allowed to differ. `.env.example`
    — the file a fresh clone copies — is the other half of the claim. What the
    pool *does* under load is not assertable from a settings dict and is not
    claimed here: `apps/core/tests/test_connection_pool.py` drives it.
    """
    with _settings_module("config.settings.base") as base:
        database = dict(base.DATABASES["default"])

    assert database["CONN_HEALTH_CHECKS"] is True
    # Persistent connections are refused by Django alongside a pool, so this is
    # 0 by construction rather than by a value somebody typed.
    assert database["CONN_MAX_AGE"] == 0
    assert database["OPTIONS"]["pool"]["max_size"] >= 1
    # The clone gets the pool, and no live `DATABASE_CONN_MAX_AGE` line: with the
    # pool on that variable is not read, so a value there would steer nothing.
    assert "DATABASE_CONN_MAX_AGE" not in _env_example()
    assert _env_example()["DATABASE_POOL_ENABLED"] == "true"

    # And the reason the live value differs is the one stated above, not drift.
    assert settings.DATABASES["default"]["CONN_MAX_AGE"] == 0
    assert "pool" not in settings.DATABASES["default"]["OPTIONS"]
    assert settings.DATABASES["default"]["CONN_HEALTH_CHECKS"] is True


def test_english_only_by_default_and_time_is_a_different_question() -> None:
    """`USE_I18N` off is a ruling; `USE_TZ` and the per-tenant display are not it."""
    assert settings.USE_I18N is False
    assert settings.USE_TZ is True
    assert _env_example()["USE_I18N"] == "0"

    # What a person is *shown* is the tenant's, and already on the model — this
    # is the reference `architecture.md` asks for rather than a second setting.
    fields = {field.name for field in Tenant._meta.get_fields()}
    assert {"timezone", "locale"} <= fields


def test_the_template_states_its_version_once() -> None:
    """`TEMPLATE_VERSION` is how a product knows what it cloned; one source."""
    version = read_template_version(BASE_DIR)

    # The SHAPE, never the value. A literal here would be a SECOND source of the
    # version — the exact thing this test's name says there is only one of — and
    # it would redden on every release, which the child-commit publish makes a
    # standing cadence rather than a one-off. What is actually load-bearing is
    # below: whatever version this file states, CHANGELOG.md has its section.
    assert settings.TEMPLATE_VERSION == version
    assert f"## [{version}]" in (BASE_DIR / "CHANGELOG.md").read_text()


# --- The database this tree connects to --------------------------------------


def _no_env_file(*args: Any, **kwargs: Any) -> None:
    """Stand-in for `environ.Env.read_env`: a checkout with no `.env` on disk."""
    return None


@contextmanager
def _base_without(*absent: str, **environment: str) -> Iterator[Any]:
    """Reload `config.settings.base` with `absent` genuinely unset.

    `_settings_module` above can only ADD variables, and the refusal under test
    fires on absence. Absence has two sources — the process environment and the
    `.env` file `base` reads at import — so this removes both: the named
    variables are popped, and `read_env` is neutralised. That is what a checkout
    which has run neither `scripts/setup.sh` nor `source scripts/db.sh` looks
    like from inside settings, and it cannot be simulated by setting anything.
    """
    base = importlib.import_module("config.settings.base")
    try:
        with mock.patch.dict(os.environ, environment):
            for name in absent:
                os.environ.pop(name, None)
            with mock.patch.object(environ.Env, "read_env", _no_env_file):
                importlib.reload(base)
                yield base
    finally:
        importlib.reload(base)


def test_an_unset_database_name_refuses_instead_of_choosing_one() -> None:
    """There is no last-resort default, and that is the whole fix.

    A default that names a real database is not a fallback, it is a wrong answer
    delivered confidently: `djb_main` was the owner's live development database,
    and any tree that had run neither script silently read and wrote it.
    """
    with pytest.raises(ImproperlyConfigured) as refusal:
        with _base_without("DATABASE_NAME", "DATABASE_URL"):
            pass  # pragma: no cover - the reload above is what raises

    message = str(refusal.value)
    assert "DATABASE_NAME" in message
    # Both remedies, always: this line cannot tell "never set up" from "sourcing
    # forgotten in this shell", and the two are fixed by different commands.
    assert "scripts/setup.sh" in message
    assert "scripts/db.sh" in message


def test_no_database_name_is_pinned_in_the_settings_block() -> None:
    """The pin for the scar itself, so the default cannot grow back by a slip."""
    source = (BASE_DIR / "config" / "settings" / "base.py").read_text()

    assert 'env.str("DATABASE_NAME", default="")' in source
    # No database name is a *default* anywhere in the module. The comments above
    # the block name `djb_main` on purpose — that is the scar being explained —
    # so the pin is on the code shape, not on the word.
    assert 'default="djb_' not in source
    # `.env.example` ships the slot empty for the same reason.
    assert _env_example()["DATABASE_NAME"] == ""


def test_a_name_in_the_environment_is_a_complete_answer() -> None:
    """What `scripts/db.sh` exports and what `scripts/setup.sh` writes to .env
    both arrive here, so the refusal must stay silent for both."""
    with _base_without("DATABASE_URL", DATABASE_NAME="djb_probe") as base:
        assert base.DATABASES["default"]["NAME"] == "djb_probe"
        # The task queue rides on the same value, so two checkouts never share one.
        assert base.TEMPORAL_TASK_QUEUE == "djb-probe"


def test_a_database_url_alone_is_a_complete_answer() -> None:
    """A deployment that sets only DATABASE_URL is configured, not un-set up: the
    URL wins over the parts as it always did, and the refusal does not fire."""
    url = "postgres://someone:secret@db.example.test:6432/elsewhere"  # pragma: allowlist secret

    with _base_without("DATABASE_NAME", DATABASE_URL=url) as base:
        database = dict(base.DATABASES["default"])

    assert database["NAME"] == "elsewhere"
    assert database["HOST"] == "db.example.test"
    assert database["PORT"] == 6432


# --- The queue that database name feeds ---------------------------------------
#
# The same value, one consumer further on. `TEMPORAL_TASK_QUEUE` is how two
# checkouts' workers avoid stealing each other's tasks, and it used to derive
# from `DATABASE_NAME` — one of the TWO ways a database name arrives here. A
# deployment that set only `DATABASE_URL` therefore had an empty `DATABASE_NAME`
# and a queue named `djb-`, which is every other URL-only deployment's queue as
# well: a staging worker eligible to accept a workflow production started, with
# nothing anywhere saying so.
#
# The fix is a deletion, not a warning. The derivation reads the name parsed out
# of the assembled `DATABASE_URL` — the same parse the connection uses — so no
# path reaches it holding an empty name, and the `djb-` fallback has nowhere to
# come from. An unnameable database is refused instead, next to that same
# refusal above and for the same reason.


def _queue_and_name(**environment: str) -> tuple[str, str]:
    """The task queue and the connected database name, from one settings import."""
    absent = tuple(name for name in ("DATABASE_NAME", "DATABASE_URL") if name not in environment)
    with _base_without(*absent, **environment) as base:
        return base.TEMPORAL_TASK_QUEUE, base.DATABASES["default"]["NAME"]


def test_a_url_only_deployment_gets_a_queue_with_a_name_in_it() -> None:
    """`djb-` is not a queue name, it is an absence."""
    url = "postgres://someone:secret@db.example.test:6432/elsewhere"  # pragma: allowlist secret
    queue, name = _queue_and_name(DATABASE_URL=url)

    assert name == "elsewhere"
    assert queue == "djb-elsewhere"


def test_the_url_only_queue_is_sanitised_the_same_way_the_parts_are() -> None:
    """One sanitiser, one place: a `djb_`-prefixed URL name loses the prefix too,
    so the queue a checkout gets does not depend on which door its name came
    through. Two spellings of the same database must not mean two queues."""
    url = "postgres://djb:djb@127.0.0.1:5432/djb_main_a1b2c3d4"  # pragma: allowlist secret
    from_url, _ = _queue_and_name(DATABASE_URL=url)
    from_parts, _ = _queue_and_name(DATABASE_NAME="djb_main_a1b2c3d4")

    assert from_url == from_parts == "djb-main_a1b2c3d4"


WINNER_URL = (
    "postgres://someone:secret@db.example.test:6432/djb_the_winner"  # pragma: allowlist secret
)


def test_the_queue_rides_whichever_source_won_the_connection() -> None:
    """DATABASE_URL wins over the parts for the connection — it always
    did — so it must win for the queue too. Two sources of truth here means the
    worker listens on a queue derived from a database the web process is not
    even connected to."""
    queue, name = _queue_and_name(
        DATABASE_NAME="djb_the_loser",
        DATABASE_URL=WINNER_URL,
    )

    assert name == "djb_the_winner"
    assert queue == "djb-the_winner"


def test_a_url_that_names_no_database_is_refused_rather_than_guessed() -> None:
    """The fallback is deleted, so the case it used to absorb has to land
    somewhere: on the same refusal used for an unset name. A URL with no
    database segment is a URL, not an answer, and `djb-` was the confident
    wrong answer this template already ruled out once."""
    with pytest.raises(ImproperlyConfigured) as refusal:
        no_database = "postgres://someone:secret@db.test:6432"  # pragma: allowlist secret
        with _base_without("DATABASE_NAME", DATABASE_URL=no_database):
            pass  # pragma: no cover - the reload above is what raises

    message = str(refusal.value)
    assert "DATABASE_URL" in message
    assert "scripts/setup.sh" in message
    assert "scripts/db.sh" in message


def test_no_configuration_of_this_tree_yields_the_bare_queue() -> None:
    """Enumerated in one place: every way a name can arrive, and the one
    way it cannot. The bare `djb-` is unreachable — not deprecated, not warned
    about, absent — and this is the test that would notice it coming back."""
    parts, _ = _queue_and_name(DATABASE_NAME="djb_probe")
    url_only, _ = _queue_and_name(DATABASE_URL="postgres://u:p@h:5432/probe")
    both, _ = _queue_and_name(DATABASE_NAME="djb_probe", DATABASE_URL="postgres://u:p@h:5432/other")
    override, _ = _queue_and_name(
        DATABASE_NAME="djb_probe", TEMPORAL_TASK_QUEUE="djb-explicitly-mine"
    )

    assert [parts, url_only, both, override] == [
        "djb-probe",
        "djb-probe",
        "djb-other",
        "djb-explicitly-mine",
    ]
    # And the fourth way — neither source set — is the refusal above, never a queue.
    with pytest.raises(ImproperlyConfigured):
        with _base_without("DATABASE_NAME", "DATABASE_URL"):
            pass  # pragma: no cover - the reload above is what raises


def test_the_queue_derivation_reads_the_connected_name_not_the_parts() -> None:
    """The pin on the shape, so the degrade cannot grow back by a slip: the
    derivation must not name `DATABASE_NAME`, because that is the variable that
    is empty in exactly the URL-only case above."""
    source = (BASE_DIR / "config" / "settings" / "base.py").read_text()
    derivation = source.split("TEMPORAL_TASK_QUEUE: str = (", 1)[1].split("\n)", 1)[0]

    assert "_database_name_in_use" in derivation
    assert "DATABASE_NAME" not in derivation
    # And the name it reads comes from the connection's own parse, so the two
    # cannot drift: one `db_url_config` call feeds both.
    assert "_database_config: dict[str, Any] = env.db_url_config(DATABASE_URL)" in source
    assert "**_database_config," in source


# --- The cache key space that same name feeds ---------------------------------
#
# The third consumer of the one derived name, and the one that was missing.
# `CACHE_URL` defaults every checkout on a machine to one Redis database, and
# `CACHES["default"]` carried no `KEY_PREFIX` — so two worktrees running at once
# shared one key space and each could read what the other had cached. It is the
# same problem one layer up (two clones of `main` sharing `djb_main`), with a worse symptom:
# a wrong database shows up as a missing table, a wrong cache entry shows up as
# a WRONG ROW returned confidently.
#
# It was invisible because `config/settings/test.py` swaps in `LocMemCache`, so
# no test in this suite has ever touched Redis. These tests therefore look at
# the DERIVATION in `base`, not at a live cache: the derivation is the thing
# that was absent, and it is the thing that can regress.


def _cache_prefix(**environment: str) -> tuple[str, str]:
    """The cache key prefix and the connected database name, from one import."""
    # Every source this derivation can read is either supplied here or made
    # genuinely absent — including `CACHE_KEY_PREFIX` itself, which a developer
    # may well have exported in the shell running the suite. A test whose answer
    # depends on the environment it ran in is not a test.
    sources = ("DATABASE_NAME", "DATABASE_URL", "CACHE_KEY_PREFIX")
    absent = tuple(name for name in sources if name not in environment)
    with _base_without(*absent, **environment) as base:
        return base.CACHE_KEY_PREFIX, base.CACHES["default"]["KEY_PREFIX"]


def test_the_cache_key_prefix_is_this_checkouts_database_name_and_is_wired_in() -> None:
    """It derives, it is non-empty, and it reaches the cache rather than sitting
    in a module as a value nobody consumes — which is the shape of the defect:
    the prefix existing and `CACHES` not carrying it looks identical from a
    settings dump and is identical to having none at all."""
    prefix, wired = _cache_prefix(DATABASE_NAME="djb_main_a1b2c3d4")

    assert prefix == "djb_main_a1b2c3d4"
    assert prefix != ""
    assert wired == prefix


def test_two_checkouts_of_one_branch_derive_different_cache_key_spaces() -> None:
    """The cache-prefix defect in one assertion, mirroring the database-name defect's exact shape.

    `scripts/db.sh` names a checkout `djb_<branch>_<8 hex of the SHA-256 of its
    top-level path>`, so two clones of `main` in two directories differ only in
    the hash — that is the pair that used to share `djb_main`, and the pair that
    shared one Redis key space until this prefix existed. Standing in for the
    two checkouts is the only thing settings can see of them: the name each one
    derived.
    """
    one, _ = _cache_prefix(DATABASE_NAME="djb_main_700aaf41")
    two, _ = _cache_prefix(DATABASE_NAME="djb_main_c0ffee11")

    assert one != two
    # And a URL-only deployment is inside the namespace too, not on the empty
    # prefix every other URL-only deployment would share (the same lesson, one
    # consumer further on).
    url_only, _ = _cache_prefix(DATABASE_URL="postgres://u:p@h:5432/elsewhere")
    assert url_only == "elsewhere"


def test_an_explicit_cache_key_prefix_wins_over_the_derivation() -> None:
    """The pin, spelled the way `DATABASE_NAME` and `TEMPORAL_TASK_QUEUE` spell
    it: an explicit value in the environment wins outright and nothing is
    derived, so two processes can be told to share one warm cache on purpose."""
    prefix, wired = _cache_prefix(DATABASE_NAME="djb_probe", CACHE_KEY_PREFIX="shared-on-purpose")

    assert prefix == wired == "shared-on-purpose"
    # An EMPTY pin is not a pin — `.env.example` ships the slot blank so a fresh
    # clone takes the derivation without having to know what to write, exactly
    # as TEMPORAL_TASK_QUEUE and TEMPORAL_MACHINERY_LIFETIME do.
    empty, _ = _cache_prefix(DATABASE_NAME="djb_probe", CACHE_KEY_PREFIX="")
    assert empty == "djb_probe"
    assert _env_example()["CACHE_KEY_PREFIX"] == ""


def test_no_configuration_of_this_tree_yields_an_unprefixed_cache() -> None:
    """Every way a prefix can arrive, and the one way it cannot. The bare `""`
    — the shared key space itself — is unreachable rather than merely
    discouraged, and this is the test that would notice it coming back."""
    parts, _ = _cache_prefix(DATABASE_NAME="djb_probe")
    url_only, _ = _cache_prefix(DATABASE_URL="postgres://u:p@h:5432/probe")
    both, _ = _cache_prefix(DATABASE_NAME="djb_probe", DATABASE_URL="postgres://u:p@h:5432/other")
    pinned, _ = _cache_prefix(DATABASE_NAME="djb_probe", CACHE_KEY_PREFIX="mine")

    assert [parts, url_only, both, pinned] == ["djb_probe", "probe", "other", "mine"]
    assert "" not in {parts, url_only, both, pinned}
    # And the fourth way — neither database source set — is the same refusal
    # as above, never an unprefixed cache.
    with pytest.raises(ImproperlyConfigured):
        with _base_without("DATABASE_NAME", "DATABASE_URL", "CACHE_KEY_PREFIX"):
            pass  # pragma: no cover - the reload above is what raises


# --- The OAuth door a fresh clone arrives with --------------------------------
#
# The same shape as the block above, and found the same way: a value `.env`
# shipped empty, which nothing filled in, which turned a whole door off in
# silence. `ZITADEL_MCP_AUDIENCE` empty is not "accept any audience", it is **no
# resource server** (`apps/accounts/oauth.py:configured`), so every clone's /mcp
# OAuth door was shut until somebody read `.env.example` and pasted a project id
# by hand — found twice before being pinned here.
#
# What is pinned here is the half a unit test can see: that the slot still
# ships empty, that the file and the script agree about who fills it, and that
# the *kind* of value the script writes is one the validator accepts. The
# behavioural half — a real `setup.sh` run against a scratch `.env`, its
# idempotence, and the file's mode afterwards — is a live proof, recorded with
# its before/after separately, because no test in this suite runs
# docker.


def _setup_sh() -> str:
    return (BASE_DIR / "scripts" / "setup.sh").read_text()


def test_env_example_still_ships_the_audience_empty_and_says_who_fills_it() -> None:
    """The slot and its instructions, held together so they cannot drift.

    Empty is deliberate — a template that shipped one deployment's project id
    would be shipping a door pointed at somebody else's Zitadel — so the fix
    was never to put a value in the file. It was to make the script that
    already knows the value write it, and this pins that the file now says so.
    """
    assert _env_example()["ZITADEL_MCP_AUDIENCE"] == ""

    example = (BASE_DIR / ".env.example").read_text()
    assert "scripts/setup.sh` fills this in" in example
    # And the script really does, rather than the comment merely claiming it.
    assert "env_set ZITADEL_MCP_AUDIENCE" in _setup_sh()


def test_setup_leaves_an_audience_that_is_already_there_alone() -> None:
    """The valve for an externally-managed Zitadel, pinned at the source.

    A project this script did not create has an id this script cannot resolve,
    so "write what seeding found" must never mean "overwrite what an operator
    set". The guard is a non-empty test (`=.`), the same one the `ZITADEL_PAT`
    branch above it uses, and `env_set` replaces in place rather than appending
    — which is what makes a re-run neither clobber nor duplicate.
    """
    script = _setup_sh()

    assert 'grep -q "^ZITADEL_MCP_AUDIENCE=." .env' in script
    assert "already set in .env; leaving it alone" in script


def test_setup_tightens_the_env_file_to_owner_only() -> None:
    """SEC-1's INFO, ridden where `.env`'s owner is.

    Everything `setup.sh` writes into that file is a credential — the Zitadel
    PAT most of all — and `cp` gives the copy whatever the umask says, which on
    a normal laptop is world-readable. Unconditional rather than only on the
    branch that creates the file: a `.env` somebody else made holds the same
    secrets.
    """
    script = _setup_sh()

    assert "chmod 600 .env" in script
    # THE ORDER IS WHAT IS PINNED, NOT THE SPELLING. A chmod before the file
    # exists is a chmod on nothing. The bare `cp` this used to look for moved
    # inside `env_sync_from_example` when the environment step stopped leaving
    # an existing `.env` alone and started regenerating it from `.env.example`,
    # so the assertion now names the STEP and its call rather than one line of
    # the copy — which is the thing that was always meant.
    step = script.index('step "environment file"')
    chmod = script.index("chmod 600 .env")
    assert step < chmod
    assert "\nenv_sync_from_example\n" in script[step:chmod]


def test_the_kind_of_value_setup_writes_arms_the_oauth_door() -> None:
    """B3-2: what the script writes is what the validator accepts.

    A bare Zitadel project id — no quoting, no comma, no whitespace, which is
    exactly what `env_set ZITADEL_MCP_AUDIENCE "${project_id}"` puts on the
    line. The failure this guards against is a value that *looks* like setup
    worked and leaves the door refusing every token: `oauth.configured()` is
    the prerequisite `scripts/oauth_demo.py` names in its `--help`, and it
    wants both an issuer and a non-empty audience list.
    """
    from apps.accounts import oauth

    project_id = "387144672868302854"

    with _base_without(ZITADEL_MCP_AUDIENCE=project_id) as base:
        assert base.ZITADEL_MCP_AUDIENCE == [project_id]

        with override_settings(
            ZITADEL_MCP_AUDIENCE=base.ZITADEL_MCP_AUDIENCE,
            ZITADEL_ISSUER="http://localhost:8081",
        ):
            assert oauth.audiences() == [project_id]
            assert oauth.configured() is True

    # And the state it replaces: empty is the door OFF, not a door open to all.
    with override_settings(ZITADEL_MCP_AUDIENCE=[], ZITADEL_ISSUER="http://localhost:8081"):
        assert oauth.configured() is False


# --- The sign-in door: both halves of the login-V2 pin ------------------------
#
# Zitadel v4.17.1 defaults `loginV2.required` to true and routes OIDC
# `authorize` to Login V2, which is a SEPARATE CONTAINER neither this
# repository's `compose.yaml` nor `deploy/compose.yaml` ships. Unpinned, the
# browser sign-in button lands on `/ui/v2/login/login?authRequest=…` and gets a
# 404 — the quickstart's first step, invitation acceptance and the /mcp OAuth
# flow all die behind one missing line. `deploy/compose.yaml` grew the pin;
# the ROOT `compose.yaml`, which is the one `scripts/setup.sh`, the devcontainer
# and the README all use, did not, so every laptop kept the defect.
#
# There are two halves and each needs the other, which is why they are pinned
# together here. `DefaultInstance` is applied WHEN THE INSTANCE IS CREATED, so
# the compose line fixes a FRESH volume and does nothing to an instance that
# already exists; the feature API is the only route into those, so `setup.sh`
# reads it and repairs. Drop either half and a real population keeps the 404.
#
# Text-level, deliberately, and the same bargain the block above strikes: no
# test in this suite runs docker, so the behavioural half — the repair driven
# against a live instance, its before/after `loginV2` values and the
# authorize redirect moving from `/ui/v2/login/…` (404) to `/ui/login/…`
# (200) — is a live proof recorded separately.

LOGIN_V2_KEY = "ZITADEL_DEFAULTINSTANCE_FEATURES_LOGINV2_REQUIRED"


def _compose_yaml() -> str:
    return (BASE_DIR / "compose.yaml").read_text()


def test_both_compose_files_pin_classic_login_the_same_way() -> None:
    """The laptop's stack gets the line the deployment already had.

    Pinned as the same *expression*, not merely the same key: a root file that
    hard-coded `false` would be a stack nobody could ever flip forward when
    the adoption trigger fires, and one that defaulted to `true` would ship
    the defect with a knob on it.
    """
    pin = f"{LOGIN_V2_KEY}: ${{ZITADEL_LOGIN_V2_REQUIRED:-false}}"

    assert pin in _compose_yaml()
    assert pin in (BASE_DIR / "deploy" / "compose.yaml").read_text()


def test_the_root_compose_pin_points_at_where_the_reasoning_lives() -> None:
    """One home for the argument, a citation at the second site.

    The 30 lines that read the spelling out of the image and re-word the
    trigger live in `deploy/compose.yaml`. Duplicating them is how two copies
    of a rationale start disagreeing, so the root file cites instead — and the
    citation is pinned, because a comment that stops naming its source is a
    comment the next reader has to re-derive.
    """
    compose = _compose_yaml()
    pin_at = compose.index(LOGIN_V2_KEY)
    # The comment block immediately above the key, not merely somewhere in the file.
    preamble = compose[max(0, pin_at - 1200) : pin_at]

    assert "classic-login-pin" in preamble
    assert "deploy/compose.yaml" in preamble
    # And the failure it prevents, named where somebody deleting the line will see it.
    assert "/ui/v2/login/login" in preamble


def test_setup_repairs_an_instance_the_compose_line_cannot_reach() -> None:
    """The half a fresh volume does not get.

    An instance that already exists ignores `DefaultInstance` — Zitadel's own
    defaults.yaml: once a feature is set on the instance, system-level settings
    are ignored until instance features are reset. Every laptop that ran this
    stack before the pin landed has one. So `setup.sh` reads the feature API
    and writes the fix, and it reads FIRST: the PUT happens only on the
    instance that actually carries the defect.
    """
    script = _setup_sh()

    assert "/v2/features/instance" in script
    assert '{"loginV2":{"required":false}}' in script
    # Read before write, so a correct instance is left alone.
    assert script.index("/v2/features/instance") < script.index('{"loginV2":{"required":false}}')
    # Both legs say which one happened; a repair nobody can see in a transcript
    # is a repair nobody can trust ran.
    assert "loginV2 required=true found on this instance — repairing (classic-login-pin)" in script
    assert "already correct" in script


def test_the_sign_in_repair_never_fails_setup() -> None:
    """Identity may legitimately be unbootstrapped, and setup must survive it.

    No PAT, no instance, an operator pointing at a Zitadel that is not up: none
    of those is a broken laptop, and `zitadel_seed` further down is already the
    step that reports a shut identity door. Every failing leg here prints the
    manual command and carries on — which under `set -euo pipefail` is a
    property of how the calls are written, so it is pinned at that level.
    """
    script = _setup_sh()
    start = script.index('step "sign-in door')
    block = script[start : script.index('step "database for this worktree"', start)]

    # curl's non-zero status can never reach `set -e`.
    assert block.count("|| true") == 2
    # A laptop without curl is told, not silently skipped.
    assert "command -v curl" in block
    # And every dead end names the command that fixes it by hand.
    assert block.count("login_v2_manual}") == 4


def test_the_sign_in_repair_runs_after_the_pat_is_in_env() -> None:
    """Ordering, because the step authenticates with what the step above wrote.

    On a first run `.env` has no `ZITADEL_PAT` until the machine-credential
    step copies it out of the bootstrap volume. Placed above that, this step
    would take the no-PAT branch on exactly the run — the first one — where the
    fresh instance is most likely to need it.
    """
    script = _setup_sh()

    assert script.index('step "zitadel machine credential"') < script.index('step "sign-in door')
    # And before the seed, whose OAuth clients are what the repaired door serves.
    assert script.index('step "sign-in door') < script.index(
        'step "zitadel identity configuration"'
    )


# --- The CSP the sign-in doors have to survive ---------------------------------
# `form-action` is not "where may this form POST"; browsers apply it to the
# whole REDIRECT CHAIN a submission travels. The provider-login form POSTs to
# our own host, our server answers 302 to the identity provider's authorize
# endpoint, and with `form-action 'self'` the browser refuses the hop — measured
# in the owner's console on staging, four occurrences, both doors:
#
#   Refused to send form data to
#   'https://accounts.google.com/o/oauth2/v2/auth?...' because it violates the
#   following Content Security Policy directive: "form-action 'self'".
#
# The server log shows only the 302 leaving; it cannot see the browser decline
# to follow it. So the authorize origins of the providers this deployment
# actually configured join the directive — derived from the configured
# endpoints, never a per-environment literal.

# A production environment with the sign-in door armed AND the workforce's
# Google configured behind it. Throwaway values: the point is that the Zitadel
# block in `SOCIALACCOUNT_PROVIDERS` is non-empty, which is what makes its origin
# reachable and therefore needed — and that configured Google credentials open
# no second origin, because that Google lives inside Zitadel.
IDENTITY_ENVIRONMENT = {
    **PRODUCTION_ENVIRONMENT,
    "GOOGLE_OAUTH_CLIENT_ID": "throwaway.apps.googleusercontent.com",
    "GOOGLE_OAUTH_CLIENT_SECRET": "throwaway-google-client-secret",  # pragma: allowlist secret
    "GOOGLE_WORKSPACE_DOMAINS": "example.test",
    "ZITADEL_CLIENT_ID": "throwaway-zitadel-client-id",
    "ZITADEL_CLIENT_SECRET": "throwaway-zitadel-client-secret",  # pragma: allowlist secret
    "ZITADEL_ISSUER": "https://auth.example.test",
}


def _rendered_csp(**environment: str | None) -> str:
    """The header a browser would actually receive, through django-csp itself.

    Not the settings dict: the defect was in what the browser enforces, so the
    assertion is on the rendered header, produced by the same middleware
    production runs. `config.settings.production` is imported under the given
    environment (`_settings_module`), and its policy is put on live settings
    only for the length of the render.
    """
    with _settings_module("config.settings.production", **environment) as production:
        policy = production.CONTENT_SECURITY_POLICY

    with override_settings(CONTENT_SECURITY_POLICY=policy):
        middleware = CSPMiddleware(lambda request: HttpResponse("."))
        rendered = middleware(RequestFactory().get("/accounts/login/"))

    # `MiddlewareMixin.__call__` is typed as possibly-awaitable because it can
    # be adapted for ASGI; called with a sync `get_response` it is not.
    assert isinstance(rendered, HttpResponse)
    return str(rendered.headers["Content-Security-Policy"])


def _form_action(**environment: str | None) -> list[str]:
    header = _rendered_csp(**environment)
    for directive in header.split(";"):
        parts = directive.split()
        if parts and parts[0] == "form-action":
            return parts[1:]
    raise AssertionError(f"no form-action in the rendered policy: {header}")


def test_the_provider_redirect_survives_form_action() -> None:
    """The one door's authorize origin is in the directive, and 'self' stays.

    Zitadel's is the origin of `ZITADEL_ISSUER` — the same setting the allauth
    app's `server_url` is built from, so a deployment that moved its identity
    host moves this with it and nobody edits a policy by hand. **Google's is
    NOT, even with the workforce's Google configured:** that Google is an
    identity provider inside Zitadel, so our form's redirect chain ends at
    Zitadel, and a Google origin here would be wider than the doors this
    deployment opened.
    """
    sources = _form_action(**IDENTITY_ENVIRONMENT)

    assert "'self'" in sources
    assert "https://accounts.google.com" not in sources
    assert "https://auth.example.test" in sources


def test_form_action_is_no_wider_than_the_doors_that_are_open() -> None:
    """The control. A fix that widened the directive would pass the test above.

    Nothing wildcarded, nothing over plain HTTP, and every origin is a scheme
    and a host with no path — a `form-action` source expression ignores a path
    anyway, so one in the value is a sign somebody pasted an endpoint.
    """
    sources = _form_action(**IDENTITY_ENVIRONMENT)

    assert "*" not in sources
    for source in sources:
        assert not source.startswith("http:"), source
        assert "*" not in source, source
        if source.startswith("https://"):
            assert source.count("/") == 2, source


def test_an_unconfigured_provider_gets_no_origin() -> None:
    """Derived, so a deployment with no sign-in door widens nothing.

    `PRODUCTION_ENVIRONMENT` names no client ids, so both `APPS` lists are empty
    and neither button exists. A directive that listed the origins anyway would
    be a per-environment literal wearing a derivation's clothes.
    """
    sources = _form_action(**PRODUCTION_ENVIRONMENT)

    assert sources == ["'self'"]


# --- The CSP the door on OUR host has to survive (A5.6) -----------------------
# The other half of the same defect, and the half that has no symptom on this
# side of the wire. With `SIGN_IN_DOOR=ours` the password is typed on OUR page,
# our server finalizes the OIDC auth request, and the answer is a 302 towards
# the OIDC client's registered redirect URI — a hop in the same submission's
# chain, so `form-action` decides whether the browser follows it. It does not
# tell us when it declines: the server log shows the 302 leaving, and every
# headless drive in this suite follows it happily, because a test client has no
# CSP. So the assertion is on the rendered header against the URIs the SEED
# registers, which is the only place those URIs exist.

#: The production environment with both providers armed AND our own door open.
#: `PUBLIC_BASE_URL` is what the seed builds the browser client's redirect URI
#: from, so it is the one value this case needs beyond `IDENTITY_ENVIRONMENT`.
OUR_DOOR_ENVIRONMENT = {
    **IDENTITY_ENVIRONMENT,
    "DJB_SIGN_IN_DOOR": "ours",
    "PUBLIC_BASE_URL": "https://app.example.test",
}


def _declared_redirect_uris(base_url: str) -> list[str]:
    """Every redirect URI `zitadel_seed` registers, read off the seed itself.

    Not a list typed here. The point of the criterion is that the policy and
    the registration cannot disagree, and two hand lists agree only until one
    of them moves — so the test reads the same constants the command does, and
    a seed that registers a new client fails this the day it lands rather than
    the day a browser refuses a redirect nobody can see refused.
    """
    return [
        f"{base_url}{zitadel_seed.BROWSER_CALLBACK_PATH}",
        f"{base_url}{zitadel_seed.BROWSER_LOGOUT_PATH}",
        *zitadel_seed.MCP_CALLBACK_URIS,
    ]


def test_the_csp_form_action_admits_every_declared_redirect_origin() -> None:
    """Under `ours`, every declared client's redirect origin is in the directive.

    A population, not an example: the set of origins the seed registers, each
    of them asserted present. A derivation that admitted the browser client and
    forgot the pre-registered MCP native client would pass a test that named
    one URI, and the person it failed for would be somebody completing a
    sign-in for an assistant with no way to see why.
    """
    sources = _form_action(**OUR_DOOR_ENVIRONMENT)
    base = str(OUR_DOOR_ENVIRONMENT["PUBLIC_BASE_URL"])

    wanted = {urlsplit(uri) for uri in _declared_redirect_uris(base)}
    for parts in wanted:
        origin = f"{parts.scheme}://{parts.netloc}"
        assert origin in sources, f"{origin} is registered with Zitadel and not in {sources}"


def test_the_csp_form_action_admits_every_surfaces_redirect_origin() -> None:
    """A sign-in completed on the customer host comes back to the customer host's callback.

    The seed registers a browser redirect URI for every surface the deployment
    answers at, and the policy admits each surface's origin — derived by this
    settings layer's own reading of the same map (`base.py`'s surface origins,
    since settings may not import `apps`) — so the hop back from our own page on
    the customer host is not refused.
    """
    environment = {
        **OUR_DOOR_ENVIRONMENT,
        "SURFACE_HOSTS": "staff=app.example.test,customer=customer.example.test",
    }
    sources = _form_action(**environment)

    assert "https://app.example.test" in sources
    assert "https://customer.example.test" in sources


def test_the_redirect_origins_are_not_admitted_under_the_hosted_door() -> None:
    """The control, and it is the derivation rather than a second list.

    Under `hosted` no form of ours is ever submitted into that chain — the
    password is typed on the identity platform's own screens — so admitting
    the loopback origins of a native client would be a policy wider than the
    doors this deployment opened, which is the rule the authorize origins
    beside them are derived by. `IDENTITY_ENVIRONMENT` clears
    `DJB_SIGN_IN_DOOR`, so this is the default deployment.
    """
    sources = _form_action(**IDENTITY_ENVIRONMENT)

    for uri in _declared_redirect_uris("https://app.example.test"):
        parts = urlsplit(uri)
        assert f"{parts.scheme}://{parts.netloc}" not in sources, uri


# --- What a DEBUG 500 prints ------------------------------------------------

CREDENTIAL_SUFFIXES = ("_PAT", "_TOKEN", "_SECRET", "_KEY", "_PASSWORD", "_DSN")


def _a_500() -> tuple[Any, Any, Any]:
    """An exception whose traceback holds no frame that saw a planted value."""
    try:
        raise RuntimeError("a deliberate 500")
    except RuntimeError:
        return sys.exc_info()


def test_a_debug_500_hides_every_credential_setting() -> None:
    """No setting or request variable named as a credential reaches the technical 500 page.

    does-not-cover: a credential named outside the vocabulary; a value code echoes into the page.
    """
    from django.views.debug import technical_500_response

    names = sorted(n for n in dir(settings) if n.isupper() and n.endswith(CREDENTIAL_SUFFIXES))
    assert names, "no setting carries the credential vocabulary"
    names += [f"PLANTED{suffix}" for suffix in CREDENTIAL_SUFFIXES]
    planted = {name: f"planted-{index:03d}-credential-sentinel" for index, name in enumerate(names)}
    with override_settings(DEBUG=True, **planted):
        request = RequestFactory().get("/")
        request.META.update(planted)
        body = technical_500_response(request, *_a_500()).content.decode()
    shown = sorted(name for name, value in planted.items() if value in body)
    assert shown == [], f"the DEBUG 500 prints {shown}"


# --- The request opens no transaction (ADR perf-2) ---------------------------


@pytest.mark.django_db(transaction=True)
def test_requests_open_no_transaction(tenant: Tenant, owner: Any) -> None:
    """A GET of the widget list reaches its selector with no transaction open around it."""
    from apps.accounts.services import issue_token
    from apps.core.actor import actor_for
    from apps.example import api as widget_api
    from apps.example.selectors import list_widgets

    _, bearer = issue_token(
        user=owner,
        tenant=tenant,
        name="no-request-transaction",
        actor=actor_for(user=owner, tenant=tenant),
    )
    seen: list[bool] = []

    def watched(**kwargs: Any) -> Any:
        seen.append(connection.in_atomic_block)
        return list_widgets(**kwargs)

    with (
        mock.patch.object(widget_api, "list_widgets", watched),
        CaptureQueriesContext(connection) as queries,
    ):
        answered = Client().get("/api/v1/widgets/", headers={"authorization": f"Bearer {bearer}"})

    assert answered.status_code == 200, answered.content
    assert seen == [False]
    assert not [q["sql"] for q in queries if q["sql"].upper().startswith(("SAVEPOINT", "BEGIN"))]
    assert settings.DATABASES["default"]["ATOMIC_REQUESTS"] is False
