"""`manage.py newapp` emits the canonical shape, born green, and refuses the rest.

The claim this module holds the generator to is one sentence: **the generated
app passes `./scripts/check.sh --fast` with nothing filled in but the label.**
Everything below is a piece of that — the file set is the canonical one and
nothing else, `apps.py` registers by discovery with its `depends_on` declared,
the door-parity stub skips rather than lying, and a label that would red the
gate is refused before a byte is written.

DOES NOT COVER — declared: the gate itself. `--fast` is nine legs and this is a
pytest module; it can prove the SHAPE is the one the legs want and it cannot
run them. The rung ran `--fast` over a generated app and pasted the verdict,
and the verifier reproduces it; that is the instrument for that half, and
nothing here pretends otherwise.

Every app is generated into a temp directory, never into `apps/`. A plant under
`apps/` would be visible to every other xdist worker's census
(`apps/core/tests/tree_census.py` says why that race is real), and none of the
claims here need the real directory: discovery, the canonical stems and the
ordering census are all functions of a root, and they are handed one.

Every file this module walks to is read through `tree_census`'s tolerant seam
even so. The race that seam exists for cannot reach a directory pytest made for
this test alone — but "a test module that opens what it walked" is a CLASS, the
belt at `test_tree_census.py` counts membership of it and not exposure to it,
and a module that read directly "because its own walk is safe" is the first
sentence of every module that later walked `apps/`.
"""

from __future__ import annotations

import ast
import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
from _pytest.outcomes import Failed, Skipped
from django.core.management import call_command
from django.core.management.base import CommandError
from django.template import Context, Engine

from apps.core.checks import BANNED_MODULES, CANONICAL_MODULES
from apps.core.management.commands import newapp
from apps.core.tests.test_query_ordering import ordered_by_call_sites
from apps.core.tests.tree_census import source_lines, source_text
from config.settings.discovery import discover_apps

#: The whole of what a generated app holds, relative to its own package. The
#: set is the claim: a file more is a file the gate has never seen, and a file
#: less is a canonical job with nowhere to live.
CANONICAL_SHAPE = frozenset(
    {
        "__init__.py",
        "apps.py",
        "models.py",
        "services.py",
        "selectors.py",
        "schemas.py",
        "events.py",
        "policies.py",
        "migrations/__init__.py",
        "tests/__init__.py",
        "tests/test_doors_over_the_wire.py",
    }
)

LABEL = "widgets"


def camel_case(label: str) -> str:
    """Django's own `camel_case_app_name` formula, for the template's context."""
    return "".join(x for x in label.title() if x != "_")


def generate(label: str, directory: Path) -> Path:
    """Run the command the way a builder does, into a directory of our own."""
    call_command("newapp", label, directory=str(directory))
    return directory / label


def files_of(app: Path) -> set[str]:
    return {
        path.relative_to(app).as_posix()
        for path in app.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }


def run_module(path: Path) -> dict[str, object]:
    """Execute a generated module the way pytest's importer would, and hand back its namespace."""
    namespace: dict[str, object] = {"__file__": str(path), "__name__": path.stem}
    exec(compile(source_text(path), str(path), "exec"), namespace)  # noqa: S102
    return namespace


# --- C1.1: the shape, and nothing else ---------------------------------------


def test_the_generated_shape_is_the_canonical_set_and_nothing_else(tmp_path: Path) -> None:
    """Set equality, in both directions.

    `django-admin startapp` writes `views.py`, `tests.py` and `admin.py` here,
    two of which are `djb.E011` on sight (house rule 11) — which is the whole
    reason this command exists rather than a line in a skill telling people
    which files to delete afterwards.
    """
    app = generate(LABEL, tmp_path)
    assert files_of(app) == set(CANONICAL_SHAPE)


def test_every_generated_module_is_a_canonical_stem(tmp_path: Path) -> None:
    """Read off `CANONICAL_MODULES` itself, never a copy of it.

    House rule 11 is enforced from `apps/core/checks.py`; if the canonical set
    moves there and this template does not follow, this is where it is said.
    """
    app = generate(LABEL, tmp_path)
    stems = {path.stem for path in app.glob("*.py")}
    assert stems <= CANONICAL_MODULES
    assert stems, "the generated app has no top-level module at all"
    assert not stems & BANNED_MODULES


# --- C1.2: registration is discovery -----------------------------------------


def test_discovery_sees_the_generated_app_with_its_declaration(tmp_path: Path) -> None:
    """Creating the package IS registering it — nothing in `config/` changes.

    `discover_apps` is the function `config/settings/base.py` builds
    `INSTALLED_APPS` from, pointed at a directory of ours; if it can see the
    generated app here it can see it under `apps/`, for the same reason and by
    the same AST read.
    """
    generate(LABEL, tmp_path)
    found = discover_apps(tmp_path)
    assert [app.label for app in found] == [LABEL]
    assert found[0].name == f"apps.{LABEL}"
    assert found[0].depends_on == ("core", "accounts")
    assert found[0].optional is False


def test_the_config_class_is_named_after_the_label(tmp_path: Path) -> None:
    app = generate(LABEL, tmp_path)
    source = source_text(app / "apps.py")
    assert f"class {camel_case(LABEL)}Config(AppConfig):" in source
    assert f'name = "apps.{LABEL}"' in source


# --- C1.4: the door stub skips, and stops skipping ---------------------------


def test_the_door_stub_skips_until_a_door_exists(tmp_path: Path) -> None:
    """Skipping is DERIVED from the app's own files, and it cannot pass vacuously.

    Two states are driven: no door (the generated state — a module-level skip
    naming what would lift it), and one door planted beside the app (the skip
    is gone and the test is there to be collected, failing with instructions
    rather than passing over an empty comparison).
    """
    app = generate(LABEL, tmp_path)
    stub = app / "tests" / "test_doors_over_the_wire.py"

    with pytest.raises(Skipped) as skipped:
        run_module(stub)
    assert "exposes no door yet" in str(skipped.value)
    assert "api.py or mcp.py" in str(skipped.value)
    assert LABEL in str(skipped.value)

    (app / "api.py").write_text("", encoding="utf-8")
    namespace = run_module(stub)
    collected = namespace["test_the_two_doors_answer_alike"]
    assert callable(collected)
    with pytest.raises(Failed) as failed:
        collected()
    assert "still the generated stub" in str(failed.value)


def test_the_stub_claims_no_door_pair_while_the_app_owns_none(tmp_path: Path) -> None:
    """House rule 46 fires in BOTH directions, and this is the second one.

    A module-level `DOOR_PAIR` is a claim that the pair is ANSWERED; a claim for
    a pair the app does not own retires a debt never taken on, and the rule says
    so by name. So the generated stub carries the census token in its source and
    binds the name only under an `if` — which is a nested statement, and rule 46
    reads module-level assignments. This pins that arrangement: the token is
    present for the always-on census, and the top-level assignment is not.
    """
    app = generate(LABEL, tmp_path)
    stub = app / "tests" / "test_doors_over_the_wire.py"
    source = source_text(stub)
    assert "DOOR_PAIR" in source, "the always-on census token left the generated stub"

    module_level = {
        target.id
        for node in ast.parse(source).body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert "DOOR_PAIR" not in module_level


# --- C1.6: the refusals, before a byte is written -----------------------------


@pytest.mark.parametrize(
    ("label", "because"),
    [
        ("Widgets", "an app label is a lowercase Python identifier"),
        ("9lives", "an app label is a lowercase Python identifier"),
        ("class", "a keyword is not an identifier either"),
        ("helpers", "house rule 11's banned module names"),
        ("widget", "house rule 16 — an app is a collection of things"),
        ("email", "a label that shadows an importable module"),
    ],
)
def test_a_taken_or_invalid_label_is_refused_and_writes_nothing(
    tmp_path: Path, label: str, because: str
) -> None:
    """Every refusal is exit 2 and leaves the directory exactly as it found it."""
    with pytest.raises(CommandError) as refused:
        call_command("newapp", label, directory=str(tmp_path))
    assert refused.value.returncode == 2, because
    assert list(tmp_path.iterdir()) == [], "a refusal wrote something"


def test_a_label_already_under_apps_is_refused_and_the_app_there_is_untouched(
    tmp_path: Path,
) -> None:
    """The taken case builds its own victim: a decoy package, still intact after."""
    decoy = tmp_path / LABEL
    decoy.mkdir()
    (decoy / "models.py").write_text("# somebody's work\n", encoding="utf-8")

    with pytest.raises(CommandError) as refused:
        call_command("newapp", LABEL, directory=str(tmp_path))
    assert refused.value.returncode == 2
    assert (decoy / "models.py").read_text(encoding="utf-8") == "# somebody's work\n"
    assert files_of(decoy) == {"models.py"}


def test_the_refusal_is_exit_2_from_a_real_shell(tmp_path: Path) -> None:
    """The status a CI step or a builder actually sees, not the attribute alone.

    `CommandError(..., returncode=2)` is only a promise until something exits on
    it; this runs `manage.py` in a subprocess and reads the status, which is the
    thing the criterion is about.
    """
    root = Path(__file__).resolve().parents[3]
    environment = dict(os.environ, DJANGO_SETTINGS_MODULE="config.settings.test")
    finished = subprocess.run(
        [sys.executable, "manage.py", "newapp", "widget", "--directory", str(tmp_path)],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert finished.returncode == 2, finished.stderr
    assert "not plural" in finished.stderr
    assert list(tmp_path.iterdir()) == []


# --- C1.7: a generated app with a list door lands in the ordering census ------


def test_a_generated_app_with_a_list_door_does_not_red_the_ordering_census(
    tmp_path: Path,
) -> None:
    """The census that used to be a hand-typed set of file names.

    A new app with a list door reddened `test_query_ordering.py`, a module in
    `apps/core` that the new app's rung was not allowed to edit. The seeds are
    derived from the tree now, so the generated door joins the census by
    existing — and its call site is held to the same SHAPE as every other one.
    """
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()
    app = generate(LABEL, apps_dir)
    (app / "api.py").write_text(
        "from apps.core.api.query import ordered_by\n"
        "\n"
        'ORDERING = ("name", "-created_at")\n'
        "\n"
        "\n"
        "def list_widgets(queryset, ordering):\n"
        '    return ordered_by(queryset, ordering, allowed=ORDERING, default="-created_at")\n',
        encoding="utf-8",
    )

    sites = ordered_by_call_sites(tmp_path)
    assert [site.caller for site in sites] == [f"apps/{LABEL}/api.py"]
    assert all(site.is_a_shape_the_table_drives for site in sites)


def test_a_call_site_of_an_unknown_shape_still_reds_the_census(tmp_path: Path) -> None:
    """The control: the derivation did not become a census that cannot fail.

    A call with no `allowed=` is a shape the table above has never been run
    against, and it has to be reported rather than absorbed.
    """
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()
    app = generate(LABEL, apps_dir)
    (app / "api.py").write_text(
        "from apps.core.api.query import ordered_by\n"
        "\n"
        "\n"
        "def list_widgets(queryset, ordering):\n"
        "    return ordered_by(queryset, ordering)\n",
        encoding="utf-8",
    )

    sites = ordered_by_call_sites(tmp_path)
    assert sites
    assert not any(site.is_a_shape_the_table_drives for site in sites)


# --- born to standard: the things that would go wrong quietly -----------------


def test_the_generated_files_are_exactly_what_the_template_says(tmp_path: Path) -> None:
    """Nothing reformatted the output on the way out — and something tries to.

    Django's `startapp` runs whatever `black` it finds on `PATH` over what it
    just wrote (`run_formatters`, `django/core/management/utils.py`), at black's
    88 columns, while this tree formats at 100. So a generated app would be
    formatted on one machine and not on another, silently, and the two
    formatters disagree about any line between 89 and 100 columns. The templates
    are written to be a fixed point of both; this is what says so, and it goes
    red the day one of them moves a byte.
    """
    app = generate(LABEL, tmp_path)
    engine = Engine()
    context = Context(
        {"app_name": LABEL, "camel_case_app_name": camel_case(LABEL)}, autoescape=False
    )
    for relative in sorted(CANONICAL_SHAPE):
        template = newapp.APP_TEMPLATE / f"{relative}-tpl"
        expected = engine.from_string(source_text(template)).render(context)
        assert source_text(app / relative) == expected, relative


def test_no_generated_line_crosses_the_line_limit_even_for_a_long_label(
    tmp_path: Path,
) -> None:
    """The label is substituted into prose, so its length is a real variable.

    Ruff refuses a line over 100 columns and the generated app has to pass that
    leg on the day it is made. A label of 30 characters is well past anything a
    product has used and is the ceiling this pins; a longer one is a declared
    blind spot rather than a silent red.
    """
    long_label = "a" * 29 + "s"
    app = generate(long_label, tmp_path)
    too_long = [
        f"{path.relative_to(app).as_posix()}:{number}"
        for path in sorted(app.rglob("*.py"))
        for number, line in enumerate(source_lines(path), start=1)
        if len(line) > 100
    ]
    assert too_long == []


def test_the_plural_test_here_is_the_gates_own(tmp_path: Path) -> None:
    """The one thing the command copies rather than reads, pinned to its source.

    Production code under `apps/` may not import `quality` — the gate imports
    `apps`, and the other direction would invert that — so `newapp` carries its
    own two-line copy of house rule 16's plural test. A test may import
    `quality` (the worked precedent is `apps/exports/tests/test_census.py`), so
    the copy is held to the original here: the day `_looks_plural` moves, this
    is what says the command stopped agreeing with the rule it is standing on.
    """
    # Imported by name rather than by `from quality.checks import …` on purpose:
    # mypy's world here is `apps` and `config` (pyproject `[tool.mypy] files`),
    # it follows what a module imports, and `quality/` is deliberately outside
    # that world — a plain import would drag 74 errors in somebody else's file
    # into this leg. `import_module` keeps the runtime import real and the type
    # checker out of a directory it was never pointed at.
    the_rules_own = importlib.import_module("quality.checks")._looks_plural

    corpus = [
        "widgets",
        "widget",
        "analysis",
        "status",
        "bus",
        "photos",
        "memos",
        "core",
        "usage",
        "a" * 29 + "s",
    ]
    assert [newapp._looks_plural(word) for word in corpus] == [
        bool(the_rules_own(word)) for word in corpus
    ]


def test_the_singular_names_the_grammar_admits_are_read_not_typed() -> None:
    """The escape the refusal offers is the one that actually works.

    `rules.yaml` rule 16's `app_name_exemptions` is where a deliberate singular
    is recorded, with its reason, in a diff a reviewer sees. The command reads
    that list rather than holding a copy, so recording a name there is enough.
    """
    admitted = newapp.singular_apps_the_grammar_admits()
    assert {"core", "realtime", "usage", "search"} <= admitted
    assert not newapp._looks_plural("usage")
