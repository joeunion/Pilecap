"""Rule 31's runner: who declared how their data dies, and whether a purge is reached.

Started as a subprocess by `quality/checks/rule_31.py::declared_lifecycles` — never by
the default suite, and never in the gate's own process. It is a subprocess for
the reason `quality/refusal_probe.py` and `quality/hotpath_probe.py` are: the
answer lives in the **live app registry** (`apps.core.lifecycle.undeclared_models`
is defined over `django_apps.get_models()`), and a gate that stood Django up in
its own process would take every other rule's canary down with it the day an
app's import broke.

TWO FACTS, MEASURED SEPARATELY.

**The census.** Every concrete model in the registry either carries a
`Lifecycle` — on the model, or in the third-party registry an app declared for a
table it does not own — or it does not. The complement is rule 31's backlog, and
it is reported per Django `app_label` so the gate can ratchet it per app: a
five-app declaration fan-out closes five independent classes without five
builders editing one file.

**The tooth.** A `PURGED` declaration names a callable, and a callable nobody
runs is the poller that was never built — the defect the whole vocabulary exists
to catch (`purge_expired` existed for a
cycle with nothing calling it). So the chain is WALKED, outwards from the
declaration:

    purged_by -> an activity that references it
               -> a workflow that executes that activity
               -> a ScheduleDeclaration whose action names that workflow

and the schedule half is read from **LC-1's structured registry**
(`apps.workflows.client.discovered_schedules`), never guessed from the tree: the
declarations are values, the action carries the workflow, and a registry walk
cannot be fooled by a `SCHEDULES` list somebody wrote and never exported.

The workflow half is read from the resolved class's **own source**
(`inspect.getsource`) rather than from a tree walk, because Temporal's
`workflow.execute_activity("name", ...)` takes the activity as a string at a
call site and there is no runtime edge to follow. That is reading the object the
registry handed back, not searching for one.

WHAT THIS IS NOT. This is **declaration-time reachability**: that the chain is
written down, end to end, in the tree that is being gated. Whether the schedule
is live on a Temporal server, whether its last run succeeded, and whether the
purge filter deletes the right rows are all runtime facts and belong to LC-2 and
LC-3's census. The boundary is declared here so that a green rule 31 is never
mistaken for a purge that ran.

Output: one JSON object on stdout —

    {"concrete": N, "declared": D, "kinds": {kind: n},
     "undeclared": [{"label", "app_label", "file", "line", "in_tree"}],
     "purged": [{"label", "app_label", "purged_by", "file", "line",
                 "resolved": bool, "reachable": bool,
                 "chain": [...], "why": "", "referencing_activities": [...]}],
     "schedules": [{"name", "workflow"}],
     "scheduled_workflows": N, "reached_activities": N}

Exit 0 whether or not there is a backlog (the check turns the census into
findings); a non-zero exit means the probe itself could not run, which the check
surfaces as a finding AND unbound floors — enforcement broken, never a pass.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# : The task queue handed to a `ScheduleDeclaration`'s builders. Every builder
# : takes the queue rather than reading it (ADR events-2), so the probe has to
# : pass one — and which one it passes cannot matter, because a schedule id
# : varies by queue and the WORKFLOW the action names does not. A name that is
# : obviously not a deployment's is used so that a value leaking into a message
# : says where it came from.
PROBE_QUEUE = "lifecycle-probe-queue"

# : The workflow-side call sites that reach an activity. `execute_activity` and
# : its local twin are the whole of it in this tree; the `*_method` and `start_*`
# : spellings are the SDK's other doors onto the same edge and are read so that a
# : product using them is not invisible here.
_ACTIVITY_CALLS = frozenset(
    {
        "execute_activity",
        "execute_local_activity",
        "execute_activity_method",
        "execute_local_activity_method",
        "start_activity",
        "start_local_activity",
    }
)

# : A workflow may delegate to a child, and the child's activities are reached
# : just as surely. Walked transitively with a visited set, so a pair of
# : workflows that name each other terminates.
_CHILD_CALLS = frozenset({"execute_child_workflow", "start_child_workflow"})

# : How deep the reference walk goes from a reached activity: the activity's own
# : body, then the bodies of the in-tree callables it names, and so on. Two is
# : enough for the shape this tree writes (`purge_expired_records` calls
# : `purge_expired` directly) and for one layer of indirection past it. It is
# : bounded rather than exhaustive on purpose — an unbounded walk would make
# : "reachable" mean "mentioned anywhere in the process", which is not a chain.
_REFERENCE_DEPTH = 2


def _dotted(obj: Any) -> str:
    """`module.qualname` for a callable, or "" when it does not have one."""
    module = getattr(obj, "__module__", "")
    name = getattr(obj, "__qualname__", "") or getattr(obj, "__name__", "")
    return f"{module}.{name}" if module and name else ""


def _source_of(obj: Any) -> str:
    try:
        return inspect.getsource(obj)
    except (OSError, TypeError):
        return ""


def _where(obj: Any) -> tuple[str, int, bool]:
    """(path, line, in_tree) for a class or callable, relative to ROOT where it can be.

    A model that belongs to somebody else — allauth's, `django.contrib`'s —
    lives in site-packages, and a finding pathed there names a file nobody in
    this tree can edit. `in_tree` is False for those and the check paths their
    findings at the census declaration instead.
    """
    try:
        path = Path(inspect.getsourcefile(obj) or "")
        line = int(inspect.getsourcelines(obj)[1])
    except (OSError, TypeError, ValueError):
        return "", 0, False
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        return str(path), line, False
    if ".venv" in rel.parts:
        return str(rel), line, False
    return str(rel), line, True


def _first_arg_names(source: str, attrs: frozenset[str]) -> set[str]:
    """The first argument of every `<something>.<attr>(...)` call, as a name.

    A string constant is the name Temporal registered; a `Name` or an
    `Attribute` is the callable itself, and its last identifier is the name the
    registry knows it by. Anything else — a variable holding a name built at
    runtime — is invisible, and that is stated in the rule's `does_not_cover`.
    """
    found: set[str] = set()
    try:
        tree = ast.parse(inspect.cleandoc(source))
    except (SyntaxError, ValueError):
        return found
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in attrs or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            found.add(first.value)
        elif isinstance(first, ast.Name):
            found.add(first.id)
        elif isinstance(first, ast.Attribute):
            found.add(first.attr)
    return found


def _referenced_callables(fn: Any) -> set[str]:
    """Every callable this function's body NAMES, as `module.qualname`.

    Resolved through the defining module's globals rather than by matching text,
    so `purge_expired` in `apps.events.activities` resolves to
    `apps.core.idempotency.purge_expired` — the dotted path a declaration
    writes — and an unrelated local of the same name resolves to nothing.
    """
    out: set[str] = set()
    module_name = getattr(fn, "__module__", "")
    if not module_name:
        return out
    try:
        module = importlib.import_module(module_name)
    except Exception:  # noqa: BLE001 - a module that will not import names nothing
        return out
    source = _source_of(fn)
    if not source:
        return out
    try:
        tree = ast.parse(inspect.cleandoc(source))
    except (SyntaxError, ValueError):
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            candidate = getattr(module, node.id, None)
            dotted = _dotted(candidate) if callable(candidate) else ""
            if dotted:
                out.add(dotted)
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            base = getattr(module, node.value.id, None)
            candidate = getattr(base, node.attr, None) if base is not None else None
            dotted = _dotted(candidate) if callable(candidate) else ""
            if dotted:
                out.add(dotted)
    return out


def _closure_of(fn: Any, depth: int) -> set[str]:
    """The callables this one names, and the ones those name, to `depth`."""
    reached = {_dotted(fn)} if _dotted(fn) else set()
    frontier = [fn]
    for _ in range(depth):
        nxt: list[Any] = []
        for one in frontier:
            for dotted in _referenced_callables(one):
                if dotted in reached:
                    continue
                reached.add(dotted)
                module_name, _, attr = dotted.rpartition(".")
                try:
                    target = getattr(importlib.import_module(module_name), attr, None)
                except Exception:  # noqa: BLE001
                    target = None
                if target is not None and inspect.isfunction(target):
                    nxt.append(target)
        frontier = nxt
        if not frontier:
            break
    return reached


def activity_closure(fn: Any) -> set[str]:
    """The callables an activity reaches, as `module.qualname`, to rule 31's depth."""
    return _closure_of(fn, _REFERENCE_DEPTH)


def registries() -> tuple[dict[str, Any], dict[str, Any]]:
    """The discovered workflows and activities, each by its registered name and its `__name__`."""
    from temporalio import activity as temporal_activity
    from temporalio import workflow as temporal_workflow

    from apps.workflows.client import discovered_activities, discovered_workflows

    workflow_by_name: dict[str, Any] = {}
    for cls in discovered_workflows():
        definition = temporal_workflow._Definition.from_class(cls)
        name = definition.name if definition is not None else getattr(cls, "__name__", "")
        if name:
            workflow_by_name[name] = cls
        workflow_by_name.setdefault(getattr(cls, "__name__", ""), cls)

    activity_by_name: dict[str, Any] = {}
    for fn in discovered_activities():
        definition = temporal_activity._Definition.from_callable(fn)
        name = definition.name if definition is not None else getattr(fn, "__name__", "")
        if name:
            activity_by_name[name] = fn
        activity_by_name.setdefault(getattr(fn, "__name__", ""), fn)
    return workflow_by_name, activity_by_name


def workflow_name_of(target: Any) -> str:
    """The registered name of a schedule action's workflow, a name or a class; "" for none."""
    from temporalio import workflow as temporal_workflow

    if target is None:
        return ""
    if isinstance(target, str):
        return target
    definition = temporal_workflow._Definition.from_class(target)
    return definition.name if definition is not None else getattr(target, "__name__", "")


def reached_activities(
    scheduled: list[tuple[str, str]],
    workflow_by_name: dict[str, Any],
    activity_by_name: dict[str, Any],
) -> tuple[dict[str, tuple[str, str, str]], set[str]]:
    """The activities the scheduled workflows execute, by dotted name, and the workflows walked."""
    reached: dict[str, tuple[str, str, str]] = {}
    seen_workflows: set[str] = set()
    frontier = list(scheduled)
    while frontier:
        schedule_name, workflow_name = frontier.pop()
        if workflow_name in seen_workflows:
            continue
        seen_workflows.add(workflow_name)
        cls = workflow_by_name.get(workflow_name)
        if cls is None:
            continue
        source = _source_of(cls)
        for activity_name in _first_arg_names(source, _ACTIVITY_CALLS):
            fn = activity_by_name.get(activity_name)
            dotted = _dotted(fn) if fn is not None else ""
            if dotted:
                reached.setdefault(dotted, (schedule_name, workflow_name, activity_name))
        for child in _first_arg_names(source, _CHILD_CALLS):
            frontier.append((schedule_name, child))
    return reached, seen_workflows


def main() -> int:
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
    import django

    django.setup()

    from django.apps import apps as django_apps

    from apps.core.lifecycle import LifecycleKind, declared_lifecycles, undeclared_models
    from apps.workflows.client import discovered_activities, discovered_schedules

    # --- the census -----------------------------------------------------------
    declared = declared_lifecycles()
    undeclared = undeclared_models()
    kinds: dict[str, int] = {}
    for one in declared.values():
        kinds[one.kind.value] = kinds.get(one.kind.value, 0) + 1

    census: list[dict[str, Any]] = []
    for model in undeclared:
        path, line, in_tree = _where(model)
        census.append(
            {
                "label": model._meta.label,
                "app_label": model._meta.app_label,
                "file": path,
                "line": line,
                "in_tree": in_tree,
            }
        )

    # --- the registries the tooth walks ---------------------------------------
    workflow_by_name, activity_by_name = registries()
    schedules: list[dict[str, str]] = []
    scheduled: list[tuple[str, str]] = []  # (schedule name, workflow name)
    for declaration in discovered_schedules():
        name = workflow_name_of(getattr(declaration.schedule(PROBE_QUEUE).action, "workflow", None))
        schedules.append({"name": declaration.name, "workflow": name})
        if name:
            scheduled.append((declaration.name, name))

    # --- schedule -> workflow -> (child workflow)* -> activity ----------------
    reached, seen_workflows = reached_activities(scheduled, workflow_by_name, activity_by_name)

    # : What every activity in the tree names, reached or not. The second half of
    # : the tooth's message: an unreachable callable that IS referenced by an
    # : activity is a missing SCHEDULE, and one nothing references at all is the
    # : poller that was never built. Two different repairs, so two sentences.
    closures: dict[str, set[str]] = {}
    for fn in discovered_activities():
        dotted = _dotted(fn)
        if dotted:
            closures[dotted] = activity_closure(fn)

    # --- the purged declarations, judged --------------------------------------
    #
    # A finding about a purge is pathed at the MODEL'S DECLARATION and not at the
    # callable: the declaration is the promise, and it is the line whose author
    # owes either a schedule or a truer kind. The callable's own file:line rides
    # in the message so the reader can go and look at it.
    by_label = {model._meta.label: model for model in django_apps.get_models()}
    purged: list[dict[str, Any]] = []
    for label, lifecycle in sorted(declared.items()):
        if lifecycle.kind is not LifecycleKind.PURGED:
            continue
        app_label = label.split(".")[0]
        dotted = lifecycle.purged_by.strip()
        module_name, _, attr = dotted.rpartition(".")
        target: Any = None
        try:
            target = getattr(importlib.import_module(module_name), attr, None)
        except Exception:  # noqa: BLE001 - an unimportable path is the finding
            target = None

        model_file, model_line, model_in_tree = _where(by_label.get(label))
        entry: dict[str, Any] = {
            "label": label,
            "app_label": app_label,
            "purged_by": dotted,
            "resolved": target is not None,
            "reachable": False,
            "chain": [],
            "why": "",
            "referencing_activities": [],
            "model_file": model_file,
            "model_line": model_line,
            "model_in_tree": model_in_tree,
        }
        path, line, _in_tree = _where(target) if target is not None else ("", 0, False)
        entry["file"], entry["line"] = path, line

        if target is None:
            entry["why"] = (
                "the dotted path does not resolve to anything importable, so there is "
                "nothing for a schedule to reach"
            )
            purged.append(entry)
            continue

        resolved_dotted = _dotted(target) or dotted
        referencing = sorted(
            activity for activity, closure in closures.items() if resolved_dotted in closure
        )
        entry["referencing_activities"] = referencing

        hit = next((one for one in referencing if one in reached), "")
        if hit:
            schedule_name, workflow_name, activity_name = reached[hit]
            entry["reachable"] = True
            entry["chain"] = [
                f"ScheduleDeclaration {schedule_name!r}",
                f"workflow {workflow_name}",
                f"activity {activity_name} ({hit})",
                resolved_dotted,
            ]
        elif referencing:
            entry["why"] = (
                f"{len(referencing)} activity/activities reference it "
                f"({', '.join(referencing)}), and no ScheduleDeclaration's workflow "
                "executes any of them — the sweeper exists and nothing starts it"
            )
        else:
            entry["why"] = (
                "no activity in the tree references it at all — a callable written, "
                "a schema shaped for it, and nothing that "
                "would ever call it"
            )
        purged.append(entry)

    json.dump(
        {
            "concrete": len(declared) + len(undeclared),
            "declared": len(declared),
            "kinds": kinds,
            "undeclared": census,
            "purged": purged,
            "schedules": schedules,
            "scheduled_workflows": len(seen_workflows),
            "reached_activities": len(reached),
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
