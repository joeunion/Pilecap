"""The one discovery walk: which installed app declares a conventionally named module.

Registration here is by discovery — an app drops `api.py`, `events.py`,
`policies.py`, a family hook, and the platform finds it with nothing edited
anywhere. Every such reader asks the same question of the same registry, and
this module is the one place it is asked: the installed `apps.*` configs, in
`INSTALLED_APPS` order, each probed for `<app>.<module>` without importing a
module that is not there.

The installed set is the app registry's, which `config/settings` derived from
`apps/*/apps.py` through the `installed_apps` road — so `DJB_DISABLED_APPS`
is honoured by construction: an app the deployment switched off is not
installed, and nothing here walks it.

Three entry points over the one walk, by what the caller needs back:

* `declaring(module)` — the configs and the dotted module names, nothing
  imported (a census that imports each module under its own `try`);
* `imported(module)` — the configs and the imported modules (a reader of every
  constant a module carries);
* `declared(module, attribute)` — the configs and one attribute's value, shape
  checked (the ordinary case: a dict, a router, a callable).

`declared_by(label, module, attribute)` asks one app the same question, and
`declared_services()` is the `@service` population every `services.py` defines
(read by `introspect` and the MCP door's tool grammar).

DOES NOT COVER — declared: an app outside `apps.*` (Django's own and the
third-party apps are never walked); a module created after the process
imported its package (the probe is `importlib.util.find_spec`, which reads the
import system's caches); a static reader of the tree, which is the quality
engine's and reads files, not the registry.
"""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Callable
from types import ModuleType
from typing import Any

from django.apps import AppConfig
from django.apps import apps as django_apps
from django.core.exceptions import ImproperlyConfigured

from apps.core.roads import road

#: The namespace every first-party app lives under (`AppConfig.name = "apps.<label>"`).
APPS_PACKAGE = "apps."


def _is_dict(value: Any) -> bool:
    """The default shape: a declaration is a dict."""
    return isinstance(value, dict)


def _probe(config: AppConfig, module: str) -> str | None:
    """`<app>.<module>`'s dotted name when that module exists, else `None`. Imports nothing."""
    name = f"{config.name}.{module}"
    return name if importlib.util.find_spec(name) is not None else None


def declaring(module: str) -> list[tuple[AppConfig, str]]:
    """Every installed `apps.*` config with a `<module>` submodule, in app order — unimported."""
    found: list[tuple[AppConfig, str]] = []
    for config in django_apps.get_app_configs():
        if not config.name.startswith(APPS_PACKAGE):
            continue
        name = _probe(config, module)
        if name is not None:
            found.append((config, name))
    return found


def imported(module: str) -> list[tuple[AppConfig, ModuleType]]:
    """Every installed app's `<module>`, imported, in app order."""
    return [(config, importlib.import_module(name)) for config, name in declaring(module)]


@road("discover", example="apps/core/authz.py::_declarations")
def declared(
    module: str,
    attribute: str,
    *,
    predicate: Callable[[Any], bool] | None = None,
    refuse_shape: bool = False,
    shape: str = "a dict",
) -> list[tuple[AppConfig, Any]]:
    """Every installed app's `<module>.<attribute>`, in app order, with its declarer.

    **The one discovery walk.** `policies.py` and `roles.py` are found this way,
    and so is every family hook, every `TAGS`, every `router` — drop the file
    and the declaration counts, with no registration anywhere. The `AppConfig`
    travels with the value because every refusal a caller raises has to name
    WHICH app declared the thing it is refusing.

    `predicate` is the shape the caller takes (a dict when omitted). An
    attribute that is absent contributes nothing. One that is present and fails
    the predicate contributes nothing when `refuse_shape=False` (the
    vocabulary's reading) and is `ImproperlyConfigured` naming
    `apps/<label>/<module>.py` and `shape` when `True` (a family hook's
    reading) — a malformed hook that quietly counted for nothing would be a
    blocker that never blocks.
    """
    accepts = predicate or _is_dict
    found: list[tuple[AppConfig, Any]] = []
    for config, loaded in imported(module):
        value = getattr(loaded, attribute, None)
        if value is None:
            continue
        if accepts(value):
            found.append((config, value))
        elif refuse_shape:
            raise ImproperlyConfigured(
                f"apps/{config.label}/{module}.py must export `{attribute}` as {shape}; "
                f"got {type(value).__name__}."
            )
    return found


def declared_by(label: str, module: str, attribute: str) -> Any | None:
    """One installed app's `<module>.<attribute>`, or `None` — no app, no module, no attribute."""
    try:
        config = django_apps.get_app_config(label)
    except LookupError:
        return None
    name = _probe(config, module)
    if name is None:
        return None
    return getattr(importlib.import_module(name), attribute, None)


def declared_services() -> list[tuple[AppConfig, str, Callable[..., Any]]]:
    """Every `@service` an installed app's `services.py` defines: `(config, name, function)`.

    A service carries `__wrapped__` and is its module's own definition, never one it imported.
    A `services/` package's are its members' that its `__init__` re-exports (rule 11).
    In app order, then definition order.
    """
    found: list[tuple[AppConfig, str, Callable[..., Any]]] = []
    for config, module in imported("services"):
        package = hasattr(module, "__path__")
        for name, value in vars(module).items():
            if not callable(value) or getattr(value, "__wrapped__", None) is None:
                continue
            home = str(getattr(value, "__module__", ""))
            if home != module.__name__ and not (package and home.startswith(f"{module.__name__}.")):
                continue
            found.append((config, name, value))
    return found
