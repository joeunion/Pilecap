"""Rule 31: every model declares how its data dies."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from quality.checks._hub import CheckResult

# --- rule 31: every model declares how its data dies ---------------------------
#
# ADR core-13, LF-1's primitive (`apps/core/lifecycle.py`), LF-Q's rule. Two
# questions, one probe, and they fail in different classes because they have
# different repairs.
#
# THE CENSUS. Every concrete model in the LIVE registry either carries a
# `Lifecycle` or does not, and the complement is a backlog measured before it is
# enforced (the retired `lifecycle-measurement.md`), ratcheted per Django
# `app_label`. Per-app and not per-rule for rule 46's reason and for the schema
# discipline's: the declaration fan-out is five builders in five apps, and a
# shared number is a shared file.
#
# THE TOOTH. A `PURGED` declaration names a callable, and a callable nothing
# runs is the poller that was never built — its shape, and this check exists
# to end the fifth sighting of that class. The chain is walked outwards
# from the declaration: `purged_by` -> an activity that references it -> a
# workflow that executes that activity -> a `ScheduleDeclaration` whose action
# names that workflow. The schedule half comes off LC-1's STRUCTURED REGISTRY
# (`apps.workflows.client.discovered_schedules`) and never off a tree walk; the
# workflow half is read from the resolved class's own source, because
# `workflow.execute_activity("name", ...)` takes a string at a call site and
# there is no runtime edge to follow.
#
# WHY A SUBPROCESS. The population is `django_apps.get_models()` and the
# registry is `discovered_schedules()`: both need a booted Django, and the gate
# must not stand Django up in its own process (rule 44's docstring records
# living through exactly that — one bad import and every rule's canary dies at
# once). `quality/lifecycle_probe.py` owns the boot and answers in JSON.

_LIFECYCLE_PROBE = "quality/lifecycle_probe.py"


def declared_lifecycles(root: Path, rule: dict) -> CheckResult:
    """Rule 31. Every concrete model declares how its data dies, and a purge is reached.

    Two classes of finding and one probe. An undeclared model fires in its own
    APP's class, so the measured backlog shrinks per app and never pays for
    another app's growth. A `purged` declaration whose callable no
    `ScheduleDeclaration` chain reaches fires in `unreachable` (or
    `unresolvable`, when the dotted path names nothing importable), neither of
    which is ratcheted: the tooth is born clean because the one live member
    (`core.IdempotencyRecord`) has its whole chain written down.

    Declaration-time reachability ONLY. That the chain is written, end to end,
    in the tree being gated — never that the schedule is live on a server, that
    its last tick ran, or that the filter deletes the right rows. Those are
    runtime facts and belong to LC-2/LC-3's census; the boundary is in
    `does_not_cover` so a green rule 31 is never read as a purge that ran.
    """
    out = CheckResult()
    proc = subprocess.run(
        [sys.executable, str(root / _LIFECYCLE_PROBE)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        report = json.loads(proc.stdout)
    except (ValueError, TypeError):
        report = None
    if proc.returncode != 0 or not isinstance(report, dict):
        out.hit(
            _CENSUS_DECLARATION,
            0,
            f"rule 31's probe could not read the model registry at all (exit "
            f"{proc.returncode}) — Django did not boot, or did not answer. That is "
            "enforcement broken and not an empty backlog; the floors below say so as exit "
            f"2. Output:\n{(proc.stdout + proc.stderr).strip()[-1500:]}",
            klass="probe",
        )
        return out

    out.count("concrete_models", int(report.get("concrete", 0)))
    out.count("declared_lifecycles", int(report.get("declared", 0)))
    out.count("scheduled_workflows", int(report.get("scheduled_workflows", 0)))
    out.count("purged_declarations", len(report.get("purged") or []))
    out.count("lifecycle_kinds", len(report.get("kinds") or {}))

    for model in report.get("undeclared") or []:
        label = str(model.get("label"))
        app_label = str(model.get("app_label"))
        in_tree = bool(model.get("in_tree"))
        if in_tree:
            where, line = str(model.get("file")), int(model.get("line") or 1)
            how = (
                "declare it on the model — `lifecycle: ClassVar[Lifecycle] = "
                "Lifecycle(kind=...)`, in the class body, where the person adding the "
                "table is already standing"
            )
        else:
            where, line = _CENSUS_DECLARATION, 0
            how = (
                "this table belongs to somebody else and will never grow an attribute, so "
                "whichever app OWNS THE CONCERN declares it in its own "
                "`apps/<app>/lifecycle.py::register(registry)` — discovered, never listed "
                "(a central dict would be one file every app in a parallel wave has to edit)"
            )
        out.hit(
            where,
            line,
            f"{label} is a concrete model and nothing says how its rows die. Four kinds "
            "and no fifth (ADR core-13): `purged` names the callable that sweeps it, "
            "`bounded` says the rows die with their parent, `unbounded` and `append_only` "
            "carry a reason and a dated trigger. A retention document is the shape that "
            "does not survive a product — the table added on Thursday is never in it — so "
            f"the declaration lives with the table. {how}",
            root=root,
            klass=app_label,
        )

    for entry in report.get("purged") or []:
        if entry.get("reachable"):
            continue
        label = str(entry.get("label"))
        dotted = str(entry.get("purged_by"))
        # Pathed at the DECLARATION, never at the callable: the declaration is
        # the promise, and it is the line whose author owes either a schedule or
        # a truer kind. The callable's own site rides in the message.
        if entry.get("model_in_tree"):
            where, line = str(entry.get("model_file")), int(entry.get("model_line") or 1)
        else:
            where, line = _CENSUS_DECLARATION, 0
        klass = "unresolvable" if not entry.get("resolved") else "unreachable"
        at = (
            f" (`{dotted}` is written at {entry.get('file')}:{entry.get('line')})"
            if entry.get("resolved") and entry.get("file")
            else ""
        )
        schedules = ", ".join(
            f"{one.get('name')} -> {one.get('workflow')}" for one in report.get("schedules") or []
        )
        out.hit(
            where,
            line,
            f"{label} declares `purged` and names `{dotted}`, and no ScheduleDeclaration "
            f"chain reaches it: {entry.get('why')}{at}. The chain rule 31 walks is "
            "`purged_by` -> an activity that references it -> a workflow that executes "
            "that activity -> a `ScheduleDeclaration` in some app's "
            "`activities.py::SCHEDULES` whose action names that workflow. The declared "
            f"machines today are [{schedules}]. A table declared purged with nothing "
            "purging it is the poller that was never built — the defect this whole "
            "vocabulary exists to catch, and the one this rule is the fifth sighting of. "
            "Write the activity and its ScheduleDeclaration in the same commit as the "
            "declaration, or say a truer kind",
            root=root,
            klass=klass,
        )
    return out


from quality.checks.rule_44 import _CENSUS_DECLARATION  # noqa: E402
