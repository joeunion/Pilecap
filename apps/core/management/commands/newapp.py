"""`manage.py newapp <label>` — a new app, born to the house rules.

    uv run python manage.py newapp widgets

Django's own `startapp` is the wrong shape for this tree three times over: it
writes `views.py` and `tests.py` (two `djb.E011`s, house rule 11), it writes an
`apps.py` whose `name` is the bare label — so the process does not boot at all,
because every app here is `apps.<label>` — and it declares no `depends_on`, so
house rule 7 has nothing to hold the app to. The alternative a builder was left
with was typing the canonical shape from prose, or copying `apps/example`,
which carries four doors, three models, a workflow and eight test modules a
first app does not want.

This is `startapp` with THIS house's template
(`apps/core/management/app_template/`, rendered by Django's own
`--template`): the canonical file set and nothing else, `depends_on` declared,
and a door-parity stub that skips until the app has a door. **The generated app
is green under `./scripts/check.sh --fast` with nothing filled in but the
label** — that is the whole claim, and `apps/core/tests/test_newapp.py` is what
holds it to it.

WHAT IT DELIBERATELY DOES NOT EMIT:

* `api.py` / `mcp.py` — an empty router reds rules 41, 46 and 47 at once. The
  first door is the product's first real rung, and the test stub says so out
  loud rather than leaving a passing placeholder behind.
* a model, and therefore a migration — a generated table is a migration
  somebody has to revert. `models.py` carries the shape in its docstring and
  the rung that needs the table runs `makemigrations <label>` itself.
* `lifecycle.py` — not a canonical module name here; a model declares its own
  lifecycle on the class (house rule 31).

ONE THING DJANGO DOES THAT THIS TREE DID NOT ASK FOR: `startapp` runs whatever
`black` it finds on `PATH` over what it just wrote (`run_formatters`,
`django/core/management/utils.py`), at black's own 88 columns, while this tree
formats at 100. So the generated app would be formatted on one machine and not
on another, silently. The answer is not a flag — there is none — it is that the
templates are written to be a FIXED POINT of both formatters, and
`test_the_generated_files_are_exactly_what_the_template_says` reds the day one
of them moves a byte.

REFUSALS ARE EXIT 2 AND HAPPEN BEFORE ANY FILE IS WRITTEN. A label that would
red the gate the moment it was generated is not a half-built app for somebody
to clean up afterwards, and each refusal names the rule it is standing on.
"""

from __future__ import annotations

import importlib.util
import keyword
import re
import shutil
from pathlib import Path
from typing import Any

import yaml
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.checks import BANNED_MODULES
from apps.core.lexicon import PLURAL_REMEDY, looks_plural
from apps.core.management import BaseCommand
from apps.core.reach import extended_scope
from apps.core.scaffold import floors

#: The template `startapp` renders. Its files are `*.py-tpl` so that nothing in
#: the tree lints, type-checks or collects them as the modules they are not.
APP_TEMPLATE = Path(__file__).resolve().parents[1] / "app_template"

#: An app label. Lowercase, because `apps.<label>` is the import path every
#: module in the app carries and every sibling's `depends_on` spells.
LABEL = re.compile(r"^[a-z][a-z0-9_]*$")


def singular_apps_the_grammar_admits() -> frozenset[str]:
    """The singular app names rule 16 already admits, read off `rules.yaml` and the drawer.

    Read rather than copied, so the escape the refusal below offers is the one
    that actually works: record the name in `app_name_exemptions` with its
    reason — which is a visible diff a reviewer can disagree with — and this
    command stops refusing it. An unreadable or absent file means "nothing is
    exempt", which refuses more rather than less.
    """
    path = Path(settings.BASE_DIR) / "quality" / "rules.yaml"
    try:
        loaded: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return frozenset()
    if not isinstance(loaded, dict):
        return frozenset()
    for rule in loaded.get("rules") or []:
        if not isinstance(rule, dict) or str(rule.get("id")) != "16":
            continue
        if not isinstance(rule.get("scope") or {}, dict):
            return frozenset()
        try:
            scope = extended_scope(Path(settings.BASE_DIR), rule)
        except ValueError as refused:
            raise _refuse(str(refused)) from refused
        entries = scope.get("app_name_exemptions") or []
        return frozenset(str(entry["app"]) for entry in entries if entry.get("app"))
    return frozenset()


def _refuse(message: str) -> CommandError:
    """A refusal that exits 2 — could-not-do, not a lesser finding."""
    return CommandError(message, returncode=2)


class Command(BaseCommand):
    help = "Create a new app under apps/, born to the house rules."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "label",
            help=(
                "The app's label: lowercase, and plural, because an app is a collection "
                "of things (`widgets`, not `widget`)."
            ),
        )
        parser.add_argument(
            "--directory",
            default=None,
            help=(
                "Where the app package is written. Defaults to <BASE_DIR>/apps, which is "
                "the only place discovery looks; a temp directory is for tests."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        label = str(options["label"]).strip()
        chosen = options["directory"]
        directory = Path(chosen) if chosen else Path(settings.BASE_DIR) / "apps"

        self.refuse_what_would_red(label, directory)

        app_dir = directory / label
        app_dir.mkdir(parents=True)
        try:
            call_command("startapp", label, str(app_dir), template=str(APP_TEMPLATE))
        except BaseException:
            # A half-written package is worse than none: the next run would
            # refuse it as taken, and the gate would read it as an app.
            shutil.rmtree(app_dir, ignore_errors=True)
            raise

        self.stdout.write(f"{app_dir} — the canonical shape, and nothing else.")
        if not chosen:
            for line in floors.record(Path(settings.BASE_DIR), label, None):
                self.stdout.write(f"  {line}")
            # Invariant: imported here — `_common` imports this module at its head.
            from apps.core.scaffold.arms._common import regenerate_derived

            for line in regenerate_derived(Path(settings.BASE_DIR)):
                self.stdout.write(line)
        self.stdout.write(
            "  Registration is done: discovery reads apps.py. config/ does not change."
        )
        shown = f"apps/{label}" if not chosen else str(app_dir)
        self.stdout.write(f"undo: rm -r {shown} removes everything this command wrote")
        self.stdout.write(
            f"next: uv run python manage.py roads shape noun {label} <Noun> — a noun whose "
            f"plural no app holds (house rule 32), e.g. "
            f"{''.join(x for x in label.title() if x != '_')}Item"
        )

    def refuse_what_would_red(self, label: str, directory: Path) -> None:
        """Every refusal this command owns, before a byte is written."""
        if not LABEL.match(label) or keyword.iskeyword(label) or not label.isidentifier():
            raise _refuse(
                f"{label!r} is not an app label. It has to be a lowercase Python "
                "identifier — `apps.<label>` is the import path every module in the app "
                "carries and every sibling's `depends_on` spells "
                "(docs/sdk/the-developers-hand.md § App labels)."
            )
        if label in BANNED_MODULES:
            raise _refuse(
                f"{label!r} is one of the names business logic hides behind "
                f"({', '.join(sorted(BANNED_MODULES))}) — house rule 11 refuses it as a "
                "module and it is no better as an app. Name the app after the things it "
                "holds."
            )
        if (directory / label).exists():
            raise _refuse(
                f"{directory / label} already exists. An app is generated once; a second "
                "generation over a live app would overwrite work. Pick another label, or "
                "edit the app that is there."
            )
        if importlib.util.find_spec(label) is not None:
            raise _refuse(
                f"{label!r} is already an importable Python module, so `apps/{label}` "
                "would shadow it for anything that imports the bare name. Django's own "
                "`startapp` refuses this too; it is refused here first, before the "
                "directory is made."
            )
        if not looks_plural(label) and label not in singular_apps_the_grammar_admits():
            raise _refuse(
                f"{label!r} is not plural — an app is a collection of things (`widgets`, "
                "not `widget`), and house rule 16 reds every `apps/*/apps.py` that says "
                f"otherwise, so this app would be born red. {PLURAL_REMEDY} (rule 16's "
                "`app_name_exemptions`, the list that admits `core`, `realtime`, `usage` and "
                "`search`) — and this command reads that union, so record it there and run "
                "again."
            )
