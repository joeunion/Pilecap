"""Rule 49's runner: who writes an audit row, and did they declare who and where.

Started as a subprocess by `quality/checks/rule_49.py::audit_row_shape` — never by the
default suite, and never in the gate's own process. It is a subprocess for the
reason `quality/lifecycle_probe.py`, `quality/refusal_probe.py` and
`quality/hotpath_probe.py` are: the answer lives in **live function objects**,
and a gate that stood Django up in its own process would take every other
rule's canary down with it the day an app's import broke.

**ONE SEAM, AND IT IS IMPORTED RATHER THAN MIRRORED.** The audited population is
whatever `apps.core.service._declares_tenant` says it is — the very predicate
the `@service` decorator reads at decoration time to decide whether a row gets
written. This probe imports it and calls it. It does not re-implement "a
keyword-only parameter named tenant", and that is the point of the rule's scope
clause: a rule that mirrored the seam would be a second opinion about the
population, and the day the seam changed the rule would go on enforcing the old
one while reporting green. If the import ever breaks, this probe says so on
stdout (`"seam": null`) and the check turns that into exit-2 enforcement-broken
rather than an empty population that reads as a clean pass.

Output: one JSON object on stdout —

    {"seam": "apps.core.service._declares_tenant" | null,
     "seam_error": "",
     "audited": [{"dotted", "module", "file", "line",
                  "actor": "required"|"defaulted"|"absent",
                  "tenant": "required"|"defaulted"|"absent", "sweep": bool}],
     "services": ["<dotted names of EVERY @service, audited or not>"]}

`services` is the second list for one reason: the allow-list's own consistency
half. An entry naming a service that does not exist at all is a ghost — a line
that exempts nothing and will go on exempting nothing after the name it was
written for is gone.

Exit 0 whether or not there is a violation (the check turns the census into
findings); a non-zero exit means the probe itself could not run, which the
check surfaces as a finding AND unbound floors — enforcement broken, never a
pass.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import json
import os
import pkgutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def _shape(parameters: Any, name: str) -> str:
    """`required` · `defaulted` · `absent` — the three states the rule reads.

    `required` says nothing about nullability on purpose. `Tenant | None` with
    no default is a REQUIRED parameter whose value may legitimately be `None`
    (ADR core-8 (b)'s platform population, and `revoke_token`'s shape), and it
    is conformant: the caller was made to say. A DEFAULT is the failure, because
    it is the one shape where a caller can leave the question unanswered and
    nothing anywhere records that they did.
    """
    if name not in parameters:
        # For `tenant` this state is UNREACHABLE inside the audited population,
        # and that is not an oversight: declaring a keyword-only `tenant` is
        # exactly what `_declares_tenant` reads to decide a service is audited at
        # all, so a missing tenant means a service outside the population rather
        # than a violation inside it. AUDIT-3 found this by planting the canary
        # and watching it stay silent. The state is still modelled — `actor`
        # reaches it constantly, and a seam that changed its mind about the
        # population would otherwise arrive here with nothing to say.
        return "absent"
    if parameters[name].default is not inspect.Parameter.empty:
        return "defaulted"
    return "required"


def _on_the_sweep_signature(function: Any) -> bool:
    """Whether it is the factory's `(*, before, tenant: None) -> core.types.Swept`, resolved."""
    from apps.core.types import Swept

    try:
        signature = inspect.signature(function, eval_str=True)
    except (NameError, TypeError, SyntaxError):
        return False
    if set(signature.parameters) != {"before", "tenant"}:
        return False
    tenant = signature.parameters["tenant"].annotation
    return tenant in (None, type(None)) and signature.return_annotation is Swept


def _factory_calls(module: Any) -> list[ast.Call]:
    """Every call in the module's source whose callee resolves to `core.schedules.daily_purge`."""
    from apps.core.schedules import daily_purge

    try:
        tree = ast.parse(inspect.getsource(module))
    except (OSError, TypeError, SyntaxError):
        return []
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _resolve(module, node.func) is daily_purge
    ]


def _resolve(module: Any, node: ast.expr) -> Any:
    """A `Name` or dotted `Attribute` read through the module's globals; None when it is neither."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return vars(module).get(node.id)
    if isinstance(node, ast.Attribute):
        base = _resolve(module, node.value)
        return getattr(base, node.attr, None) if base is not None else None
    return None


def factory_reach() -> set[str]:
    """What the `daily_purge(...)` declarations reach, as `module.qualname`, by rule 31's walk."""
    from apps.workflows.client import discovered_schedules
    from quality.lifecycle_probe import (
        activity_closure,
        reached_activities,
        registries,
        workflow_name_of,
    )

    scheduled_workflows: set[str] = set()
    for declaration in discovered_schedules():
        scheduled_workflows.add(
            workflow_name_of(getattr(declaration.schedule("audit-probe").action, "workflow", None))
        )
    declared: list[tuple[str, str]] = []
    import apps as apps_package

    for module_info in pkgutil.iter_modules(apps_package.__path__):
        dotted_module = f"apps.{module_info.name}.activities"
        try:
            module = importlib.import_module(dotted_module)
        except ModuleNotFoundError as error:
            if error.name != dotted_module:
                raise
            continue
        for call in _factory_calls(module):
            workflow = next((k.value for k in call.keywords if k.arg == "workflow"), None)
            name = workflow_name_of(_resolve(module, workflow)) if workflow is not None else ""
            if name and name in scheduled_workflows:
                declared.append((f"apps.{module_info.name}.activities", name))
    workflow_by_name, activity_by_name = registries()
    reached, _walked = reached_activities(declared, workflow_by_name, activity_by_name)
    out: set[str] = set()
    for dotted in reached:
        module_name, _, attr = dotted.rpartition(".")
        out |= activity_closure(getattr(importlib.import_module(module_name), attr))
    return out


def _dotted(function: Any) -> str:
    """`module.qualname`, the spelling rule 31's walk answers in."""
    return f"{getattr(function, '__module__', '')}.{getattr(function, '__qualname__', '')}"


def main() -> int:
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
    import django

    django.setup()

    out: dict[str, Any] = {"seam": None, "seam_error": "", "audited": [], "services": []}
    try:
        from apps.core.service import _declares_tenant
    except Exception as error:  # pragma: no cover - the consistency canary's own path
        out["seam_error"] = f"{type(error).__name__}: {error}"
        print(json.dumps(out))
        return 0
    out["seam"] = "apps.core.service._declares_tenant"

    import apps as apps_package

    reach = factory_reach()
    for module_info in pkgutil.iter_modules(apps_package.__path__):
        name = f"apps.{module_info.name}.services"
        try:
            services = importlib.import_module(name)
        except ModuleNotFoundError:
            continue
        for attribute, value in vars(services).items():
            wrapped = getattr(value, "__wrapped__", None)
            home = str(getattr(wrapped, "__module__", ""))
            if wrapped is None or (home != name and not home.startswith(f"{name}.")):
                continue
            dotted = f"{module_info.name}.{attribute}"
            out["services"].append(dotted)
            if not _declares_tenant(wrapped):
                continue
            parameters = inspect.signature(wrapped).parameters
            try:
                file = str(Path(inspect.getsourcefile(wrapped) or "").relative_to(ROOT))
                line = inspect.getsourcelines(wrapped)[1]
            except (OSError, ValueError):
                file, line = name.replace(".", "/") + ".py", 1
            out["audited"].append(
                {
                    "dotted": dotted,
                    "module": module_info.name,
                    "file": file,
                    "line": line,
                    "actor": _shape(parameters, "actor"),
                    "tenant": _shape(parameters, "tenant"),
                    "sweep": _dotted(value) in reach and _on_the_sweep_signature(wrapped),
                }
            )
    out["audited"].sort(key=lambda row: row["dotted"])
    out["services"].sort()
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
