"""An app can be left out of a deployment — if the app itself said it may be.

A product that has grown its own domain app has two ways to stop shipping the
worked example, and before this the only one was **delete the directory** —
which also deletes the thing a new agent reads to learn the shape. The other is
to switch it off: `DJB_DISABLED_APPS=example`, read once while settings are
being derived.

The two properties that make it safe rather than a footgun:

* **an app declares its own optionality** (`AppConfig.optional`), so nothing
  anywhere holds a list of what is skippable, and a new app is non-optional by
  omission — the safe direction;
* **anything else named in the flag is refused BY NAME while settings are read**
  — `core`, because it did not declare itself optional, and a label matching no
  app at all, because a typo that disables nothing is precisely how the app
  somebody meant to leave out gets shipped.

**How the disabled configuration is proven.** The suite runs under the default
environment, with every app installed — `apps/example/tests` are not skipped and
are not meant to be. The flag changes `INSTALLED_APPS`, which is read once at
settings import, so it cannot be exercised by `override_settings` in-process at
all: the end-to-end tests below start a SEPARATE process with the flag set and
read what that process reports about itself.

**And the nested process rides THIS test's database.** These were the first
tests in the suite whose verdict depended on the checkout's derived BASE
database existing, and that is an unstated precondition the gate does not
promise: `--loop` in a worktree that had run `db.sh` passed, and the same tree's
full gate in a checkout that never created `djb_main_<hash>` went red with
`FATAL: database "..." does not exist`. Nothing in the nested run wants the base
database — `ATOMIC_REQUESTS = True` (`config/settings/base.py`) opens a
transaction for `GET /`, so merely serving a page that queries nothing still
opens a connection. The fixture below therefore hands the child the connection
parameters of the database the OUTER test is already on, which is the one
pytest-django created; `DATABASE_URL` is cleared so the parts win, which is the
escape hatch `scripts/db.sh` documents (a name in the environment beats the
derivation). A missing environment is not a test failure — it is a missing
environment — and a red test is the wrong shape for saying so.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import connection

from apps.core.tests.tree_census import TRANSIENT_APP_MODULES, without_transient_apps
from config.settings.discovery import discover_apps, discover_local_apps

APPS_DIR = Path(settings.BASE_DIR) / "apps"

#: Renders `/` in a fresh process and prints the hrefs it contains. Run under
#: the flag, this is what an operator would see on the box.
INDEX_SCRIPT = """
import json, re, django
django.setup()
from django.test import Client
body = Client().get("/").content.decode()
print(json.dumps(sorted(set(re.findall(r'href="([^"]+)"', body)))))
"""

#: What database a process ended up on. The falsifier for the fixture below.
WHICH_DATABASE_SCRIPT = """
import django
django.setup()
from django.db import connection
print(connection.settings_dict["NAME"])
"""

InAProcess = Callable[..., "subprocess.CompletedProcess[str]"]


def died_on_a_vanished_plant(stderr: str) -> bool:
    """True when a child process was killed by a transient app, by name.

    **The other half of the scan-vs-plant race, measured.**
    `test_settings.py`'s `probe_app` fixture holds a real `apps/zzz_probe/` for a
    few milliseconds; a child booted in that window reads it into
    `INSTALLED_APPS` and then imports it — and if the fixture's teardown lands
    between those two moments, `django.setup()` dies with
    `ModuleNotFoundError: No module named 'apps.zzz_probe'`. Reproduced live on
    2026-08-25 under `-n 10`, seed 1631073414, in
    `test_the_nested_run_rides_this_tests_database`.

    **Why a retry here and not tolerance in discovery.** An app that disappears
    between being discovered and being imported IS a real failure — for a real
    app it is exactly the failure a deployment wants to die on — so production
    code must keep dying on it. What is not real is the *probe*: it is a test
    artifact with a known name, and the second run happens against a tree that
    no longer holds one. The predicate is deliberately narrow — it matches the
    named transient modules and the import failure, nothing else — so a child
    that died of anything at all is still reported, with its own stderr, by the
    assertion that was going to read it. There is exactly one retry.

    The read half of the same race is `apps/core/tests/tree_census.py`; this is
    the half no tolerant read could have closed, because nothing here is reading
    a file.
    """
    return "No module named" in stderr and any(
        f"'{module}'" in stderr for module in TRANSIENT_APP_MODULES
    )


@pytest.fixture
def in_a_process(db: None) -> InAProcess:
    """Run a script in a fresh interpreter, on the database THIS test is on.

    `db` is requested for its side effect and not for a query: it is what makes
    pytest-django set the test database up, so `connection.settings_dict` names
    a database that certainly exists — created by `CREATE DATABASE` against the
    maintenance database, which needs no base database of its own. The child
    then gets that database by its parts, with `DATABASE_URL` blanked so the
    parts win over anything the outer environment was carrying.

    The alternative — letting the child re-derive the name from the checkout —
    is what made these tests report a missing environment as a red suite.
    """
    live = connection.settings_dict
    riding = {
        "DATABASE_NAME": str(live["NAME"]),
        "DATABASE_USER": str(live["USER"]),
        "DATABASE_PASSWORD": str(live["PASSWORD"]),
        "DATABASE_HOST": str(live["HOST"]),
        "DATABASE_PORT": str(live["PORT"]),
        # A stale URL would win over every part above and take the child
        # straight back to the base database this fixture exists to avoid.
        "DATABASE_URL": "",
    }

    def once(script: str, **environment: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(settings.BASE_DIR),
            env={
                **os.environ,
                "DJANGO_SETTINGS_MODULE": "config.settings.test",
                **riding,
                **environment,
            },
            capture_output=True,
            text=True,
            check=False,
        )

    def run(script: str, **environment: str) -> subprocess.CompletedProcess[str]:
        ran = once(script, **environment)
        if died_on_a_vanished_plant(ran.stderr):
            # Not a flake swallowed: the child was killed by a test artifact,
            # by name, and the second run is against a tree that no longer has
            # one. See `died_on_a_vanished_plant` for the whole argument.
            ran = once(script, **environment)
        return ran

    return run


# --- the declaration ----------------------------------------------------------


def test_the_worked_example_is_the_only_app_that_declares_itself_optional() -> None:
    """A set, so a second optional app is a decision somebody has to make on purpose."""
    optional = {app.label for app in discover_apps(APPS_DIR) if app.optional}

    assert optional == {"example"}


def test_the_default_environment_installs_every_app() -> None:
    """The dev tree is unchanged: an empty flag subtracts nothing.

    `without_transient_apps` because `test_settings.py` creates a real directory
    under `apps/` and, under `-n auto`, runs while this one counts it — see
    `apps/core/tests/tree_census.py` for why filtering is the honest form of
    these assertions rather than a dodge.
    """
    everything = without_transient_apps(discover_local_apps(APPS_DIR))

    assert without_transient_apps(discover_local_apps(APPS_DIR, [])) == everything
    assert set(everything) <= set(settings.INSTALLED_APPS)
    assert "apps.example" in everything
    assert settings.DJB_DISABLED_APPS == []


# --- the subtraction ----------------------------------------------------------


def test_disabling_the_example_takes_it_out_and_leaves_the_rest() -> None:
    everything = without_transient_apps(discover_local_apps(APPS_DIR))
    without = without_transient_apps(discover_local_apps(APPS_DIR, ["example"]))

    assert "apps.example" not in without
    assert set(everything) - set(without) == {"apps.example"}


@pytest.mark.parametrize("spelling", ["example", " example ", "example,"])
def test_the_label_is_read_forgivingly(spelling: str) -> None:
    """A comma list a person typed has whitespace in it; that is not an error."""
    assert "apps.example" not in discover_local_apps(APPS_DIR, spelling.split(","))


# --- the refusals -------------------------------------------------------------


def test_a_non_optional_app_is_refused_by_name() -> None:
    """You cannot switch off `core`, and the refusal says which app and why."""
    with pytest.raises(ImproperlyConfigured) as refusal:
        discover_local_apps(APPS_DIR, ["core"])

    assert "'core'" in str(refusal.value)
    assert "optional" in str(refusal.value)


def test_a_label_matching_no_app_is_refused_by_name() -> None:
    """The typo that would otherwise ship the app somebody meant to leave out."""
    with pytest.raises(ImproperlyConfigured) as refusal:
        discover_local_apps(APPS_DIR, ["exmaple"])

    assert "'exmaple'" in str(refusal.value)
    # And it lists what does exist, so the fix is in the message.
    assert "example" in str(refusal.value)


def test_the_flag_ships_empty_in_env_example() -> None:
    """`.env.example` is the complete list of what settings read (base.py's own claim)."""
    lines = (Path(settings.BASE_DIR) / ".env.example").read_text().splitlines()
    values = dict(
        line.split("=", 1)
        for line in (one.strip() for one in lines)
        if "=" in line and line[:1] != "#"
    )

    assert values["DJB_DISABLED_APPS"] == ""


# --- what a process under the flag reports about itself -----------------------


def test_the_nested_run_rides_this_tests_database(in_a_process: InAProcess) -> None:
    """The falsifier for the fixture: the child is on the database pytest made.

    Not the checkout's derived BASE database — the one this test is connected
    to, which exists because pytest-django created it. Before this, the child
    re-derived the name and a checkout that had never run `db.sh` failed here
    with `FATAL: database "djb_<branch>_<hash>" does not exist` — a missing
    environment wearing a red test's clothes.
    """
    ran = in_a_process(WHICH_DATABASE_SCRIPT)
    assert ran.returncode == 0, ran.stderr

    assert ran.stdout.strip() == str(connection.settings_dict["NAME"])
    assert ran.stdout.strip().startswith("test_"), "pytest-django's database, not the base one"


def test_a_process_under_the_flag_reports_no_example_anything(in_a_process: InAProcess) -> None:
    """`introspect` is the machine door onto the real registries — ask it."""
    ran = in_a_process(
        "import django; django.setup();"
        "from django.core.management import call_command; call_command('introspect')",
        DJB_DISABLED_APPS="example",
    )
    assert ran.returncode == 0, ran.stderr
    payload: dict[str, Any] = json.loads(ran.stdout)

    assert payload["settings"]["DJB_DISABLED_APPS"] == ["example"]
    assert "example" not in payload["apps"]
    assert [model for model in payload["models"] if model["app"] == "example"] == []
    assert [route for route in payload["routes"] if "widget" in str(route.get("name"))] == []
    assert [tool for tool in payload["tools"] if "widget" in tool["name"]] == []
    assert "widgets" not in json.dumps(payload["urls"])


def test_the_root_index_omits_a_disabled_apps_door(in_a_process: InAProcess) -> None:
    """The page is derived, so switching the app off is all it takes.

    Nobody edits the template and nobody deletes a line: `api:widget-list` stops
    resolving and the row is gone.
    """
    on = in_a_process(INDEX_SCRIPT)
    off = in_a_process(INDEX_SCRIPT, DJB_DISABLED_APPS="example")
    assert on.returncode == 0, on.stderr
    assert off.returncode == 0, off.stderr

    with_example: list[str] = json.loads(on.stdout)
    without: list[str] = json.loads(off.stdout)

    assert "/api/v1/widgets/" in with_example
    assert set(with_example) - set(without) == {"/api/v1/widgets/"}
    # The five doors are untouched: an app going away is not a door going away.
    for href in ("/api/v1/docs", "/mcp", "/accounts/login/", "/healthz", "/readyz"):
        assert href in without


def test_a_process_asked_to_disable_core_does_not_start(in_a_process: InAProcess) -> None:
    """Fail at settings import, not halfway through a request."""
    ran = in_a_process("import django; django.setup()", DJB_DISABLED_APPS="core")

    assert ran.returncode != 0
    assert "ImproperlyConfigured" in ran.stderr
    assert "'core'" in ran.stderr


def test_a_child_killed_by_the_probe_is_told_apart_from_a_child_that_failed() -> None:
    """The predicate, driven against the stderr that was actually measured.

    The retry above is only honest if it cannot swallow a real failure, so the
    interesting half is the negatives: a child that died of anything else — even
    another `ModuleNotFoundError` — is reported, not re-run.
    """
    measured = (
        "Traceback (most recent call last):\n"
        '  File "<string>", line 3, in <module>\n'
        "    apps.populate(settings.INSTALLED_APPS)\n"
        "ModuleNotFoundError: No module named 'apps.zzz_probe'\n"
    )
    assert died_on_a_vanished_plant(measured)

    for other in (
        "",
        "ModuleNotFoundError: No module named 'apps.example'",
        "ModuleNotFoundError: No module named 'httpx'",
        "ImproperlyConfigured: DJB_DISABLED_APPS names 'core'",
        "AssertionError: apps.zzz_probe",  # names it, but nothing failed to import
    ):
        assert not died_on_a_vanished_plant(other), other
