"""Every route the API mounts reaches at most one `@service`, so its write has one boundary."""

# does-not-cover: a service reached through a helper defined outside the route's own module.
# does-not-cover: a call through a name the route's module does not bind (a parameter, a lookup).
# does-not-cover: the plain Django views, the admin and allauth — only the ninja API is walked.

from __future__ import annotations

import ast
import functools
import inspect
import json
import os
import subprocess
import sys
import textwrap
from collections.abc import Callable
from typing import Any

#: Bound under `django.setup()` in `_measured()`'s child; `bulk.run_bulk` is a one-boundary seam.
bulk: Any = None
widget_services: Any = None

#: The census sees at least this many routes reaching exactly one service, or it stopped looking.
ONE_SERVICE_FLOOR = 90

#: The plants below are read, never run.
_NEVER_CALLED: dict[str, Any] = {}


def _is_service(obj: Any) -> bool:
    return callable(obj) and "__witness__" in getattr(obj, "__dict__", {})


def _resolve(expr: ast.expr, scope: dict[str, Any]) -> Any:
    if isinstance(expr, ast.Name):
        return scope.get(expr.id)
    if isinstance(expr, ast.Attribute):
        base = _resolve(expr.value, scope)
        return None if base is None else getattr(base, expr.attr, None)
    return None


def _calls(fn_node: ast.AST) -> tuple[list[ast.Call], list[ast.Call]]:
    """The calls in a function's own body, and those inside the functions it nests."""
    direct: list[ast.Call] = []
    nested: list[ast.Call] = []
    stack: list[tuple[ast.AST, bool]] = [(child, False) for child in ast.iter_child_nodes(fn_node)]
    while stack:
        node, inner = stack.pop()
        if isinstance(node, ast.Call):
            (nested if inner else direct).append(node)
        inner = inner or isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
        stack.extend((child, inner) for child in ast.iter_child_nodes(node))
    return direct, nested


def services_reached(fn: Callable[..., Any], seen: frozenset[Any] = frozenset()) -> list[str]:
    """The boundaries a function opens, one per call site: a seam's services count as one."""
    fn = inspect.unwrap(fn)
    if fn in seen:
        return []
    seen = seen | {fn}
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    except (OSError, TypeError):
        return []
    scope = fn.__globals__
    direct, nested = _calls(tree)

    def boundaries(calls: list[ast.Call]) -> tuple[list[str], bool]:
        found: list[str] = []
        seamed = False
        for call in calls:
            callee = _resolve(call.func, scope)
            if callee is None:
                continue
            if callee is bulk.run_bulk:
                found.append(f"{callee.__module__}.{callee.__name__}")
                seamed = True
            elif _is_service(callee):
                found.append(f"{callee.__module__}.{callee.__name__}")
            elif inspect.isfunction(callee) and callee.__module__ == fn.__module__:
                found += services_reached(callee, seen)
        return found, seamed

    found, seamed = boundaries(direct)
    if not seamed:
        found += boundaries(nested)[0]
    return sorted(found)


def _census() -> tuple[list[str], int]:
    from apps.core.api.mount import bound_operations

    multi: list[str] = []
    single = 0
    for path, _, operation in bound_operations():
        reached = services_reached(operation.view_func)
        single += len(reached) == 1
        if len(reached) > 1:
            methods = ",".join(sorted(operation.methods))
            multi.append(f"{methods} {path} -> {', '.join(sorted(reached))}")
    return multi, single


def _two_services_planted() -> None:
    widget_services.archive_widget(**_NEVER_CALLED)
    widget_services.restore_widget(**_NEVER_CALLED)


def _two_services_inside_the_seam() -> None:
    def each() -> None:
        widget_services.archive_widget(**_NEVER_CALLED)
        widget_services.restore_widget(**_NEVER_CALLED)

    bulk.run_bulk(act=each, **_NEVER_CALLED)


def _one_service_twice() -> None:
    widget_services.archive_widget(**_NEVER_CALLED)
    widget_services.archive_widget(**_NEVER_CALLED)


def _a_service_beside_the_seam() -> None:
    bulk.run_bulk(act=lambda: widget_services.archive_widget(**_NEVER_CALLED), **_NEVER_CALLED)
    widget_services.restore_widget(**_NEVER_CALLED)


_PLANTS = (
    _two_services_planted,
    _two_services_inside_the_seam,
    _one_service_twice,
    _a_service_beside_the_seam,
)


def measure() -> None:
    """Print the census and the plants' readings as JSON; run only after `django.setup()`."""
    global bulk, widget_services
    from apps.core import bulk
    from apps.example import services as widget_services

    multi, single = _census()
    plants = {plant.__name__: services_reached(plant) for plant in _PLANTS}
    print(json.dumps({"multi": multi, "single": single, "plants": plants}))


@functools.cache
def _measured() -> dict[str, Any]:
    script = (
        "import django; django.setup(); "
        "from quality.tests.test_one_service_per_route import measure; measure()"
    )
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": os.environ.get("DJANGO_SETTINGS_MODULE", "config.settings.test"),
    }
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    out = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, env=env, cwd=root
    )
    assert out.returncode == 0, f"the census child exited {out.returncode}: {out.stderr}"
    measured: dict[str, Any] = json.loads(out.stdout.splitlines()[-1])
    return measured


def _reading(plant: Callable[..., Any]) -> list[str]:
    reading: list[str] = _measured()["plants"][plant.__name__]
    return reading


def test_no_route_reaches_two_services() -> None:
    measured = _measured()
    assert measured["multi"] == []
    assert measured["single"] >= ONE_SERVICE_FLOOR, f"only {measured['single']} reach one service"


def test_the_census_sees_a_planted_second_service() -> None:
    assert _reading(_two_services_planted) == [
        "apps.example.services.archive_widget",
        "apps.example.services.restore_widget",
    ]


def test_one_service_called_twice_is_two_boundaries() -> None:
    assert _reading(_one_service_twice) == ["apps.example.services.archive_widget"] * 2


def test_a_seam_with_its_own_atomic_is_one_boundary() -> None:
    assert _reading(_two_services_inside_the_seam) == ["apps.core.bulk.run_bulk"]


def test_a_service_beside_the_seam_is_a_second_boundary() -> None:
    assert _reading(_a_service_beside_the_seam) == [
        "apps.core.bulk.run_bulk",
        "apps.example.services.restore_widget",
    ]
