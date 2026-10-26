"""The `workflow` arm: a run, its activities, its mark and its event."""

from __future__ import annotations

import ast
import keyword
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from django.core.management.base import CommandParser

from apps.core.authz import CRUD_VERBS, READ_ALIAS_VERBS
from apps.core.scaffold import anchors
from apps.core.scaffold.arms._common import (
    GOLDEN_APP,
    GOLDEN_FIELD,
    MODEL_TYPES,
    Arms,
    _refuse,
    lexicon,
    past_tense,
)
from apps.core.scaffold.copier import Golden, snake
from apps.core.scaffold.shapes import Shape, adopt_verbs

#: The registered shapes this module's arm writes.
KEYS: tuple[str, ...] = ("workflow",)

#: The workflow golden's own process.
GOLDEN_PROCESS = "onboard"
PROCESS_WORD = re.compile(r"^[a-z]+$")
#: Why `--schedule` is refused on the workflow golden: its run is per-row, a schedule's has no row.
SCHEDULE_REFUSAL = (
    "the workflow golden is per-row (its run takes {run}); a schedule starts a sweep with no row "
    "and no tenant — scaffold the process without --schedule, or wait for the sweep golden"
)
#: The services the workflow golden's two activities call: house rule 16 reads their verb.
PROCESS_SERVICE_VERBS = ("mark", "announce")

#: The approve key's golden lines, and a copy's: an administrator at the row's node.
APPROVE_REWRITES = (
    ("see `can_approve`.", "an administrator at the row's own node."),
    ('"widget.approve": can_approve,', '"widget.approve": may_archive,'),
)
#: The timer golden: sleep until a moment the row names, act once, close.
TIMER_GOLDEN = "workflow.remind"
TIMER_PROCESS = "remind"
#: The timer golden's start verb and moment, as its fences spell them.
TIMER_VERB = "update"
#: The timer golden's lead before the moment; `--before` rewrites it.
TIMER_BEFORE = "REMIND_BEFORE = timedelta(0)"
#: The timer golden's test moment, and the line a `date` field says it in instead.
TIMER_MOMENT = "return datetime.now(UTC) + REMIND_BEFORE + timedelta(days=days)"
TIMER_IMPORT = "from datetime import UTC, datetime, timedelta"
#: The field types a moment may be: `scaffold field`'s two.
MOMENT_TYPES = ("date", "datetime")
DURATION = re.compile(r"^(?P<count>[1-9][0-9]*)(?P<unit>[smhd])$")
UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
#: Which form fits, printed by both forms — and so by `roads shape workflow`.
FORMS = (
    "form: {said} — a human decision is the approval wait (`workflow <app> <Noun> <process>`); "
    "a moment the row names is the timer (`--on <verb> --until <field> [--before <duration>]`)"
)


def gerund_of(verb: str) -> str:
    """The `-ing` form a run's class says `verb` in: `onboarding`, `approving`, `submitting`."""
    past = past_tense(verb)
    if verb.endswith("e") and not verb.endswith("ee"):
        return f"{verb[:-1]}ing"
    if past == f"{verb}{verb[-1]}ed":
        return f"{verb}{verb[-1]}ing"
    return f"{verb}ing"


def workflow_lines(line: str, process: str, label: str, source: str = GOLDEN_APP) -> str:
    """A golden `onboard` line as the process `process` says it, its run ids under `label`."""
    gerund, past = gerund_of(process), past_tense(process)
    for old, new in (
        ("Onboarding", gerund.capitalize()),
        ("onboarding", gerund),
        ("ONBOARDED", past.upper()),
        ("Onboarded", past.capitalize()),
        ("onboarded", past),
        ("Onboard", process.capitalize()),
        (GOLDEN_PROCESS, process),
        (f'app="{source}"', f'app="{label}"'),
    ):
        line = line.replace(old, new)
    return line


def agent_of(verb: str) -> str:
    """The `-er` noun a timer's run is named by: `reminder`, `reviewer`, `notifier`."""
    if verb.endswith("y") and verb[-2:-1] not in ("a", "e", "i", "o", "u"):
        return f"{verb[:-1]}ier"
    return f"{gerund_of(verb).removesuffix('ing')}er"


def before_of(duration: str) -> str:
    """`--before 2h` as the `timedelta` it writes; empty when `duration` is no duration."""
    matched = DURATION.match(duration)
    if matched is None:
        return ""
    return f"timedelta({UNITS[matched.group('unit')]}={int(matched.group('count'))})"


def timer_lines(
    line: str,
    process: str,
    label: str,
    field: str,
    verb: str,
    before: str = "",
    kind: str = "datetime",
    source: str = GOLDEN_APP,
) -> str:
    """A golden `remind` line as `process` says it, asleep until `field`, started by `verb`."""
    agent, past = agent_of(process), past_tense(process)
    if before:
        line = line.replace(TIMER_BEFORE, f"REMIND_BEFORE = {before}")
    if kind == "date":
        line = line.replace(TIMER_MOMENT, f"return ({TIMER_MOMENT.removeprefix('return ')}).date()")
        line = line.replace(
            "def moment(days: float) -> datetime:", "def moment(days: float) -> date:"
        )
        line = line.replace(TIMER_IMPORT, "from datetime import UTC, date, datetime, timedelta")
    for old, new in (
        ("Reminder", agent.capitalize()),
        ("reminder", agent),
        ("REMINDED", past.upper()),
        ("Reminded", past.capitalize()),
        ("reminded", past),
        ("REMIND", process.upper()),
        ("Remind", process.capitalize()),
        (TIMER_PROCESS, process),
        (GOLDEN_FIELD, field),
        (f"{TIMER_VERB}_widget", f"{verb}_widget"),
        (f'app="{source}"', f'app="{label}"'),
    ):
        line = line.replace(old, new)
    return line


def returned_name(services: str, function: str) -> tuple[str, int] | None:
    """The name `function`'s last statement returns, and how many `return <name>` it holds."""
    tree = ast.parse(services)
    found = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function), None
    )
    if found is None or not found.body:
        return None
    last = found.body[-1]
    if not isinstance(last, ast.Return) or not isinstance(last.value, ast.Name):
        return None
    name = last.value.id
    said = sum(
        1
        for node in ast.walk(found)
        if isinstance(node, ast.Return)
        and isinstance(node.value, ast.Name)
        and node.value.id == name
    )
    return name, said


def keywords_of(services: str, function: str) -> set[str]:
    """The keyword-only parameters `function` takes in `services`, empty when it is not there."""
    tree = ast.parse(services)
    found = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function), None
    )
    return {arg.arg for arg in found.args.kwonlyargs} if found is not None else set()


class WorkflowArm(Arms):
    """`scaffold workflow`: the approval wait, or with `--until` the timer."""

    #: The timer's start site in a target whose verb is not the golden's: (scope, returned, said).
    started_at: tuple[str, str, int] | None = None

    def create_parser(self, prog_name: str, subcommand: str, **kwargs: Any) -> CommandParser:
        """The command's parser with the timer's three flags, which only this arm reads."""
        parser = super().create_parser(prog_name, subcommand, **kwargs)
        parser.add_argument("--on", default="", help="workflow: the verb whose service starts it")
        parser.add_argument(
            "--until", default="", help="workflow: the date or datetime field it sleeps until"
        )
        parser.add_argument(
            "--before", default="", help="workflow --until: how long before, e.g. 2h, 30m, 1d"
        )
        return parser

    def fragments(
        self,
        root: Path,
        golden: Golden,
        label: str,
        noun: str,
        lines: Callable[[str], str],
        imports: str = "",
        reads: dict[str, list[anchors.Piece]] | None = None,
    ) -> dict[str, list[anchors.Piece]]:
        """The shared fragments; the timer's start call moved into its verb's service."""
        found = super().fragments(root, golden, label, noun, lines, imports, reads)
        if golden.key != TIMER_GOLDEN or self.started_at is None:
            return found
        scope, returned, said = self.started_at
        golden_scope = (f"{TIMER_VERB}_{snake(noun)}",)
        for piece in found.get("services.py", []):
            if piece.anchor.scope == golden_scope:
                piece.anchor = anchors.Anchor((scope,), "before", f"return {returned}", said - 1)
                piece.lines = [line.replace("=locked)", f"={returned})") for line in piece.lines]
        return found

    def workflow(
        self,
        root: Path,
        goldens: dict[str, Golden],
        shape: Shape,
        words: list[str],
        options: dict[str, Any],
    ) -> None:
        """`workflow <app> <Noun> <process>`: the run, its activities, its mark and its event."""
        golden = self.golden_of(shape, goldens)
        if len(words) != 3:
            raise _refuse(
                "workflow takes <app> <Noun> <process> [--on <v> --until <field>] [--before <d>] — "  # noqa: E501 — the census reads the grammar whole
                "e.g. `workflow orders Order review`, or `… remind --on update --until due_at` "
                "with an optional `--before 2h`."
            )
        label, noun, process = words
        timed = bool(options.get("until") or options.get("on") or options.get("before"))
        self.stdout.write(FORMS.format(said="the timer" if timed else "the approval wait"))
        if options.get("schedule"):
            raise _refuse(SCHEDULE_REFUSAL.format(run=f"{noun}{gerund_of(process).capitalize()}"))
        if not PROCESS_WORD.match(process) or keyword.iskeyword(process):
            raise _refuse(f"{process!r} is no process — one lower-case verb, e.g. `review`.")
        if process in CRUD_VERBS or process in READ_ALIAS_VERBS:
            raise _refuse(
                f"`{snake(noun)}.{process}` would be a second spelling of a derived key — the "
                "vocabulary refuses it; name the process, e.g. `review`."
            )
        if process in adopt_verbs(root):
            raise _refuse(
                f"`{process}` is a family verb (`scaffold adopt {process}`), never a process."
            )
        if timed:
            self.timer(root, goldens, label, noun, process, options)
            return
        past = past_tense(process)
        if not past.endswith("ed"):
            raise _refuse(f"`{process}` has no `-ed` past tense for its `{process}_at` mark.")
        declared = lexicon(root)
        missing = [verb for verb in PROCESS_SERVICE_VERBS if verb not in declared]
        if missing:
            raise _refuse(
                f"{' '.join(missing)}: not a declared service verb — house rule 16 would refuse "
                f"`mark_{snake(noun)}_{past}` and `announce_{snake(noun)}_{past}`."
            )
        workflows = root / "apps" / label / "workflows.py"
        if not options["check"] and workflows.is_file():
            raise _refuse(
                f"apps/{label} already has a `workflows.py` — one scaffolded process per app; a "
                "second goes into its `WORKFLOWS` and `ACTIVITIES` by hand."
            )

        def lines(line: str) -> str:
            said = workflow_lines(line, process, label, golden.app)
            for old, new in APPROVE_REWRITES if label != golden.app else ():
                said = said.replace(old, new)
            return said

        self.additive(
            root,
            golden,
            label,
            noun,
            lines,
            options,
            taken=f"{past}_at",
            migration=f"{snake(noun)}_{past}_at",
        )
        self.stdout.write(
            f"door: POST /{{id}}/approve/ (`{snake(noun)}-approve`) and its MCP twin send the "
            f"`approve` signal the run waits on; `{snake(noun)}.approve` is an administrator's"
        )

    def timer(
        self,
        root: Path,
        goldens: dict[str, Golden],
        label: str,
        noun: str,
        process: str,
        options: dict[str, Any],
    ) -> None:
        """`--on <verb> --until <field> [--before <duration>]`: asleep until the row's moment."""
        golden = goldens.get(TIMER_GOLDEN)
        if golden is None:
            raise _refuse(f"golden pending — no `{TIMER_GOLDEN}` fence on this tree")
        verb, field = str(options.get("on") or ""), str(options.get("until") or "")
        if not verb or not field:
            raise _refuse(
                "the timer takes both `--on <verb>` (whose service starts it) and "
                "`--until <field>` (the moment it sleeps until)."
            )
        before = before_of(str(options.get("before") or "")) if options.get("before") else ""
        if options.get("before") and not before:
            raise _refuse(f"{options['before']!r} is no duration — a count and s, m, h or d: `2h`.")
        past = past_tense(process)
        if not past.endswith("ed"):
            raise _refuse(f"`{process}` has no `-ed` past tense for its `{process}_at` mark.")
        if "mark" not in lexicon(root):
            raise _refuse(
                f"mark: not a declared service verb — house rule 16 would refuse "
                f"`mark_{snake(noun)}_{past}`."
            )
        app_dir = root / "apps" / label
        models = app_dir / "models.py"
        held = models.read_text() if models.is_file() else ""
        typed = re.search(rf"^    {field} = models\.(\w+)\(", held, re.M)
        kind = MODEL_TYPES.get(typed.group(1), typed.group(1)) if typed else ""
        if kind not in MOMENT_TYPES:
            said = f"is a `{typed.group(1)}`" if typed else "is no field on it"
            raise _refuse(
                f"`--until {field}`: `{noun}.{field}` {said} — the timer sleeps until a `date` or "
                f"`datetime`; add one with `scaffold field {label} {noun} {field}:datetime?`."
            )
        services = app_dir / "services.py"
        text = services.read_text() if services.is_file() else ""
        function = f"{verb}_{snake(noun)}"
        wanted = {snake(noun), field, f"clear_{field}"}
        if not wanted <= keywords_of(text, function):
            raise _refuse(
                f"`--on {verb}`: `{function}` is not a service of the noun that sets "
                f"`{field}` — the run starts where the moment is written, a service taking "
                f"{', '.join(f'`{k}=`' for k in sorted(wanted))}, e.g. `--on update`."
            )
        returned = returned_name(text, function)
        if returned is None:
            raise _refuse(f"`{function}` ends in no `return <row>` for the run to start before.")
        workflows = app_dir / "workflows.py"
        if not options["check"] and workflows.is_file():
            raise _refuse(
                f"apps/{label} already has a `workflows.py` — one scaffolded process per app; a "
                "second goes into its `WORKFLOWS` and `ACTIVITIES` by hand."
            )
        self.started_at = None if verb == TIMER_VERB else (function, *returned)
        try:
            self.additive(
                root,
                golden,
                label,
                noun,
                lambda line: timer_lines(
                    line, process, label, field, verb, before, kind, golden.app
                ),
                options,
                taken=f"{past}_at",
                migration=f"{snake(noun)}_{past}_at",
            )
        finally:
            self.started_at = None
