"""Which apps are installed — discovered from the tree, never hand-listed.

`INSTALLED_APPS` was the last place a new app still had to edit a shared file.
It no longer is: anything under `apps/` with an `apps.py` declaring an
`AppConfig` subclass is installed, in a stable order, and two agents adding two
apps in two worktrees never touch the same line.

The scan is **static**. It reads each `apps.py` with `ast`, because settings are
imported before the app registry exists and importing an `AppConfig` module at
that point is how you get a circular import at best. Nothing here executes app
code.

Three optional class attributes on the `AppConfig` are read:

* `order: int` — where the app sits in `INSTALLED_APPS`. Default 50; `core` is
  0 and `accounts` 10 unless they say otherwise, so the foundation is always
  ahead of what builds on it and everything else falls out alphabetically.
* `depends_on: tuple[str, ...]` — the app labels this app is allowed to import.
  `core` declares none, because `core` imports nothing above it. Nothing here
  enforces it; house rule 7 (the quality engine) reads the same attribute and
  refuses an import outside it, by AST, at gate time. It lives on the
  `AppConfig` so that the declaration ships with the app rather than in a
  contract file every app has to queue up to edit.
* `optional: bool` — whether a deployment may leave this app OUT. Default
  false, which is the safe direction. Only an app that has said yes can be
  named in `DJB_DISABLED_APPS`, and everything else named there is refused by
  name while settings are being read. The worked example (`apps/example`)
  is the one app that declares it: a product ships without the example and
  keeps it in the tree, rather than deleting a directory it may want to read.
  **It is a declaration on the app, not a list here** — the app is the only
  thing that knows whether the product still works without it.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

# Where an app sits when its `AppConfig` says nothing.
DEFAULT_ORDER = 50

# The two apps whose position is structural rather than alphabetical: `core`
# holds the base model every other app inherits, `accounts` the user model
# Django resolves before anything else can point a foreign key at it.
FIXED_ORDER = {"core": 0, "accounts": 10}


@dataclass(frozen=True)
class DiscoveredApp:
    """One app found under `apps/`, with what its `AppConfig` declared."""

    label: str
    name: str
    order: int
    depends_on: tuple[str, ...]
    #: Whether this app may be left out of a deployment. **A declaration on the
    #: `AppConfig`, not a list here** — the app itself is the only thing that
    #: knows whether the product still works without it. `apps/example` declares
    #: it because the worked example is documentation that happens to be code:
    #: a product ships without it and keeps it in the tree. Everything else is
    #: false by omission, which is the safe direction — you cannot switch off
    #: `core` by forgetting to say so.
    optional: bool = False


def _is_app_config(node: ast.ClassDef) -> bool:
    """True when a class declaration looks like `class X(AppConfig)`.

    The terminal name is what is compared, so `AppConfig`, `apps.AppConfig` and
    `django.apps.AppConfig` all match, and so does a project's own base class
    named `SomethingAppConfig`.
    """
    for base in node.bases:
        terminal = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
        if str(terminal).endswith("AppConfig"):
            return True
    return False


def _literal(node: ast.ClassDef, attribute: str) -> object | None:
    """The literal value assigned to a class attribute, or None."""
    for statement in node.body:
        targets: list[ast.expr] = []
        if isinstance(statement, ast.Assign):
            targets = list(statement.targets)
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == attribute for t in targets):
            continue
        if statement.value is None:
            continue
        try:
            value: object = ast.literal_eval(statement.value)
        except ValueError:
            return None
        return value
    return None


def _read(apps_py: Path, label: str) -> DiscoveredApp | None:
    try:
        tree = ast.parse(apps_py.read_text(encoding="utf-8"), filename=str(apps_py))
    except (OSError, SyntaxError):
        return None

    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or not _is_app_config(node):
            continue
        order = _literal(node, "order")
        depends_on = _literal(node, "depends_on")
        optional = _literal(node, "optional")
        return DiscoveredApp(
            label=label,
            name=f"apps.{label}",
            order=int(order) if isinstance(order, int) else FIXED_ORDER.get(label, DEFAULT_ORDER),
            depends_on=tuple(str(one) for one in depends_on)
            if isinstance(depends_on, (list, tuple))
            else (),
            optional=optional is True,
        )
    return None


def discover_apps(apps_dir: Path, disabled: Iterable[str] = ()) -> list[DiscoveredApp]:
    """Every app under `apps_dir` this deployment installs, in `INSTALLED_APPS` order.

    `disabled` is the deployment's opt-out — `DJB_DISABLED_APPS`, a comma list of
    app LABELS, empty by default so a development tree is unchanged. It can only
    ever take away an app that declared `optional = True` on its `AppConfig`:

    * a label naming an app that did not declare it is refused, by name, because
      "switch off `core`" is a request that cannot be honoured and answering it
      with a half-built process is worse than not starting;
    * a label naming no app at all is refused too. A mistyped label that quietly
      disabled nothing is exactly the shape this exists to prevent — a product
      that meant to leave the worked example out of production, and shipped it.

    Both refusals happen while settings are being read, so the process does not
    start rather than starting wrong.
    """
    found: list[DiscoveredApp] = []
    if apps_dir.is_dir():
        for child in sorted(apps_dir.iterdir()):
            if not child.is_dir() or child.name.startswith((".", "_")):
                continue
            app = _read(child / "apps.py", child.name)
            if app is not None:
                found.append(app)

    wanted_off = {str(label).strip() for label in disabled if str(label).strip()}
    by_label = {app.label: app for app in found}
    for label in sorted(wanted_off):
        app = by_label.get(label)
        if app is None:
            raise ImproperlyConfigured(
                f"DJB_DISABLED_APPS names {label!r}, which is not an app under apps/ "
                f"(found: {', '.join(sorted(by_label)) or 'none'}). A label that "
                "disables nothing is how an app nobody meant to ship gets shipped."
            )
        if not app.optional:
            raise ImproperlyConfigured(
                f"DJB_DISABLED_APPS names {label!r}, which is not optional: its "
                f"AppConfig does not declare `optional = True`. An app declares "
                "whether the product still works without it; this one has not, and "
                "the deployment would be built on a hole."
            )

    return sorted(
        (app for app in found if app.label not in wanted_off),
        key=lambda app: (app.order, app.label),
    )


def discover_local_apps(apps_dir: Path, disabled: Iterable[str] = ()) -> list[str]:
    """The `INSTALLED_APPS` entries for everything under `apps_dir`, minus `disabled`."""
    return [app.name for app in discover_apps(apps_dir, disabled)]
