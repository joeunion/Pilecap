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
import shutil
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from typing import Any
from unittest import mock

import environ
import pytest
from csp.middleware import CSPMiddleware
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.http import HttpResponse
from django.test import RequestFactory, override_settings

from apps.core.models import Tenant
from apps.core.tests.tree_census import TRANSIENT_APP_MODULES, without_transient_apps
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

# The probe is built under a name discovery ignores, then renamed into place.
# `discover_apps` skips any directory beginning with "." or "_", so nothing can
# observe a half-written app: the rename is atomic within one filesystem, so a
# concurrent scan sees either no probe at all or a complete one.
PROBE_BUILD = f".{PROBE}.building"
PROBE_DOOMED = f".{PROBE}.removing"


#: Discovery's answer with the throwaway probe app taken out. The tolerance —
#: and the argument for filtering rather than serialising — moved to
#: `apps.core.tests.tree_census` at RACE-1, because `test_optional_apps.py` was
#: counting the same directory with no filter at all and a helper only
#: this module could reach is a helper the next census does without.
without_the_probe = without_transient_apps


def test_the_seam_knows_the_name_this_module_plants() -> None:
    """The two ends of the filter, pinned together.

    The probe's name lives here, where it is built; the list a census filters on
    lives in `tree_census`. Nothing else would notice them drifting apart — the
    filter would simply stop filtering, and the race would come back wearing the
    same clothes as before.
    """
    assert PROBE_MODULE in TRANSIENT_APP_MODULES


# --- Registration by discovery ----------------------------------------------


def test_installed_apps_is_what_the_tree_contains() -> None:
    """No hand-written LOCAL_APPS: the list and the directory agree by construction.

    `without_the_probe` because a sibling test creates a real app under `apps/`
    and, under `-n auto`, runs while this one scans. See its docstring for why
    the exclusion is the honest form of this assertion rather than a dodge.
    """
    discovered = without_the_probe(discover_local_apps(APPS_DIR))
    assert discovered == list(settings.LOCAL_APPS)
    for name in discovered:
        assert name in settings.INSTALLED_APPS


def test_the_foundation_comes_first_and_the_rest_is_alphabetical() -> None:
    labels = [app.label for app in discover_apps(APPS_DIR) if app.name != PROBE_MODULE]
    assert labels[:2] == ["core", "accounts"]
    assert labels[2:] == sorted(labels[2:])


def test_every_app_declares_what_it_may_import() -> None:
    declared = {
        app.label: app.depends_on for app in discover_apps(APPS_DIR) if app.name != PROBE_MODULE
    }
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
def probe_app() -> Iterator[Path]:
    """A throwaway app, on disk, removed again whatever happens.

    **Built under an ignored name and renamed into place**, because another
    xdist worker is scanning `apps/` while this runs and a directory that
    already holds `apps.py` but not yet `__init__.py` is a state no reader
    should ever see. `discover_apps` skips a leading "." or "_", so the build
    directory is invisible to discovery, and `Path.rename` within one directory
    is atomic — the probe appears complete or not at all. It leaves the same way.
    """
    build = APPS_DIR / PROBE_BUILD
    app_dir = APPS_DIR / PROBE
    doomed = APPS_DIR / PROBE_DOOMED
    for stale in (build, doomed):
        shutil.rmtree(stale, ignore_errors=True)
    build.mkdir()
    (build / "__init__.py").write_text("")
    (build / "apps.py").write_text(PROBE_APPS_PY)
    build.rename(app_dir)
    # The `apps` package's directory listing is cached by the import system.
    importlib.invalidate_caches()
    try:
        yield app_dir
    finally:
        app_dir.rename(doomed)
        importlib.invalidate_caches()
        shutil.rmtree(doomed)


@pytest.mark.django_db
def test_a_new_app_appears_without_anyone_editing_settings(probe_app: Path) -> None:
    """The claim, end to end: a directory is an app.

    Nothing under `config/` is touched — the app is created, discovery finds it,
    and `introspect` reports it.
    """
    discovered = discover_local_apps(APPS_DIR)
    assert "apps.zzz_probe" in discovered

    installed = list(settings.DJANGO_APPS) + list(settings.THIRD_PARTY_APPS) + discovered
    with override_settings(INSTALLED_APPS=installed):
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
A_REAL_SECRET_KEY = (
    "0f7c3ae1e0f0a2b6c5d4e3f201928374655647382910abcdeff0123456789abcd"  # pragma: allowlist secret
)


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
    """Trusting `X-Forwarded-Proto` from anyone makes every HTTPS check a lie."""
    assert settings.BEHIND_PROXY is False
    assert getattr(settings, "SECURE_PROXY_SSL_HEADER", None) is None
    assert "BEHIND_PROXY" in _env_example()


# --- Static files and object storage -----------------------------------------


@contextmanager
def _settings_module(name: str, **environment: str) -> Iterator[Any]:
    """Import a settings module under a given environment, then put it back.

    Settings are read at import time — the honest thing for settings to do, and
    awkward to test: the only way to see what a deployment with an S3 bucket
    gets is to import the module with the bucket set. So the module is reloaded,
    asserted on, and reloaded again with the original environment.
    `django.conf.settings` is a separate object and is untouched throughout.
    """
    base = importlib.import_module("config.settings.base")
    is_base = name == base.__name__
    try:
        with mock.patch.dict(os.environ, environment):
            importlib.reload(base)
            if is_base:
                yield base
            else:
                # Dropped rather than reloaded, both here and on the way out:
                # `config.settings.production` raises unless the environment it
                # demands is present, so it must be *executed* under the patch
                # and simply not left behind afterwards.
                sys.modules.pop(name, None)
                yield importlib.import_module(name)
    finally:
        if not is_base:
            sys.modules.pop(name, None)
        importlib.reload(base)


# What `config.settings.production` refuses to start without. A throwaway pair
# of real-shaped keys, so the guards pass and the module can be read.
PRODUCTION_ENVIRONMENT = {
    "DEBUG": "0",
    "ALLOWED_HOSTS": "example.test",
    "SECRET_KEY": "b3a1" * 16,  # pragma: allowlist secret
    "CONNECTIONS_ENCRYPTION_KEY": "aGVsbG93b3JsZGhlbGxvd29ybGRoZWxsb3dvcmxkMTI9",
    # Third throwaway: the suite runs with the published
    # `DATABASE_PASSWORD=djb` in its environment (base reads .env), and
    # production refuses to start on it. Anything that loads production
    # settings needs a complete production environment, which is what this
    # dict is for.
    "DATABASE_PASSWORD": "throwaway-production-database-password",  # pragma: allowlist secret
}


def test_whitenoise_sits_immediately_after_the_security_middleware() -> None:
    """Above it, a static response would miss the security headers; below it, a
    request for a CSS file would travel through sessions, auth and tenancy."""
    order = list(settings.MIDDLEWARE)
    security = order.index("django.middleware.security.SecurityMiddleware")

    assert order[security + 1] == "whitenoise.middleware.WhiteNoiseMiddleware"


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
    assert default["OPTIONS"]["querystring_auth"] is True
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
    assert _env_example()["DATABASE_CONN_MAX_AGE"] == "0"
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
    version = (BASE_DIR / "TEMPLATE_VERSION").read_text().strip()

    assert version == "1.0.0"
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
    # Before the copy would be a chmod on a file that does not exist yet.
    assert script.index("cp .env.example .env") < script.index("chmod 600 .env")


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

# A production environment with both sign-in doors armed. Throwaway values: the
# point is that the provider blocks in `SOCIALACCOUNT_PROVIDERS` are non-empty,
# which is what makes their origins reachable and therefore needed.
IDENTITY_ENVIRONMENT = {
    **PRODUCTION_ENVIRONMENT,
    "GOOGLE_OAUTH_CLIENT_ID": "throwaway.apps.googleusercontent.com",
    "GOOGLE_OAUTH_CLIENT_SECRET": "throwaway-google-client-secret",  # pragma: allowlist secret
    "GOOGLE_WORKSPACE_DOMAINS": "example.test",
    "ZITADEL_CLIENT_ID": "throwaway-zitadel-client-id",
    "ZITADEL_CLIENT_SECRET": "throwaway-zitadel-client-secret",  # pragma: allowlist secret
    "ZITADEL_ISSUER": "https://auth.example.test",
}


def _rendered_csp(**environment: str) -> str:
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


def _form_action(**environment: str) -> list[str]:
    header = _rendered_csp(**environment)
    for directive in header.split(";"):
        parts = directive.split()
        if parts and parts[0] == "form-action":
            return parts[1:]
    raise AssertionError(f"no form-action in the rendered policy: {header}")


def test_the_provider_redirect_survives_form_action() -> None:
    """Both doors' authorize origins are in the directive, and 'self' stays.

    Google's origin is a constant of the provider; Zitadel's is the origin of
    `ZITADEL_ISSUER` — the same setting the allauth app's `server_url` is built
    from, so a deployment that moved its identity host moves this with it and
    nobody edits a policy by hand.
    """
    sources = _form_action(**IDENTITY_ENVIRONMENT)

    assert "'self'" in sources
    assert "https://accounts.google.com" in sources
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
