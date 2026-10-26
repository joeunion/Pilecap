"""`manage.py roads` — the one screen of this platform's roads, read off the tree.

A job is a thing the platform does exactly one way; a road is the one mechanism
that does it; a marker (`@road`, `ROAD = road(...)`, or a `# road:` comment line
in shell) is how a road says which job it does. This command prints every job,
the road that stands for it, its partition and carrier, its contract (the
docstring's first line, or the shell marker's own text) and its worked example.
`roads <job>` prints one, `roads --json` the `roads/1` document the loop diffs,
`roads shape …` the scaffold's dry run. It touches no database and writes nothing.

AN INSTRUMENT, NEVER A JUDGE. Exit 0 is "printed"; exit 2 is could-not-look —
a Python road that does not import, an imported object with no `__road__` or
one naming another job, an example that does not resolve to a definition, a
marker the census cannot read, and two markers for one job with no `rule-84`
valve on the second. It exits 1 on nothing: house rule 84 is what refuses a
second road, and a declared second road is printed here as `kept`.

WHAT IT CANNOT SAY. A job nobody marked is invisible to it; a contract line
nobody updated is printed as written; that the marked object really does the
job is a reviewer's reading of the printed contract. A road in an optional app
this world disabled is still printed — the census reads the tree, not the
process — annotated, and not imported. The copies rule 84 counts by form are
printed only as their sum, `unmarked`, measured by the rule's own check; with
no rule 84 in the tree the header says `not measured`.

THE ONE IMPORT OUTSIDE `apps/`. It reads `quality.roads` (the one static reader
of the marker grammar), `quality.partition` (the lockfile's platform apps) and
the rule-84 check, lazily, inside the function that needs each: reporting what
the census found is this command's whole job, and a second reader of the
marker grammar here would be a second road for the census itself. No
import-linter contract forbids `apps` -> `quality`. The engine is reached by
NAME (`_engine`), not by an import statement: it sits outside the type
checker's `files` and is not written to its strict mode, and a static import
here would drag the whole engine under the `apps` leg's strict check. What
crosses back is typed `Any` and read by attribute, which is the honest type
for an engine this package does not own.
"""

from __future__ import annotations

import argparse
import ast
import copy
import importlib
import io
import json
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.management import BaseCommand

SCHEMA = "roads/1"
TEMPLATE_PRODUCT = "none — this is the template"
#: The one line for the examples a product's deleted worked example took with it.
WORKED_EXAMPLE_REMOVED = (
    "worked example removed: {n} road example(s) under apps/example*/ are not on this tree "
    "(build-contract.md's worked-example row) — the roads stand; their examples live in the "
    "template"
)
#: The one word that is no job: `roads shape …` asks the scaffold what it would write.
SHAPE = "shape"
#: A `would <act> <path>[:<anchor>]` line of the scaffold's dry run.
WOULD = re.compile(r"^would \w+ (?P<path>[^\s:]+)")


def _engine(module: str) -> Any:
    """A module of the quality engine, imported by name (the module docstring says why)."""
    return importlib.import_module(f"quality.{module}")


class CouldNotLook(Exception):
    """A road the door cannot vouch for; every one is exit 2, named."""


def _python_definition(source: str, symbol: str) -> str | None:
    """Why `symbol` is not a definition in this Python source, or None when it is.

    Read with `ast`, never a pattern over lines: a name is resolved only as a
    module-level `def`/`async def`/`class`, a module-level assignment's target
    (`TAGS = …`, `LIMIT: int = …` — the definition a declaration-shaped road
    has), or `Class.method` as a `def` directly inside that module-level class.
    A call, a nested def, a name bound inside a function or a class, or a
    method named without its class is not a definition, and the answer says
    which it found instead.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return f"it does not parse ({error.msg}, line {error.lineno})"
    parts = symbol.split(".")
    if len(parts) > 2 or not all(parts):
        return f"{symbol!r} is neither a name nor Class.method"
    defs = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    top = {node.name: node for node in tree.body if isinstance(node, defs)}
    if len(parts) == 1:
        if symbol in top or symbol in _assigned_names(tree.body):
            return None
    else:
        owner = top.get(parts[0])
        if isinstance(owner, ast.ClassDef) and any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == parts[1]
            for node in owner.body
        ):
            return None
        if not isinstance(owner, ast.ClassDef):
            return f"there is no module-level class {parts[0]}"
    name = parts[-1]
    wanted = (
        f"a def directly inside class {parts[0]}"
        if len(parts) == 2
        else "a module-level def, class or assignment"
    )
    for node in ast.walk(tree):
        if isinstance(node, defs) and node.name == name:
            return f"{symbol} is not {wanted} (found `{name}` at line {node.lineno})"
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and name in _assigned_names([node]):
            return f"{symbol} is not {wanted} (found an assignment at line {node.lineno})"
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            called = node.func
            spelled = called.id if isinstance(called, ast.Name) else getattr(called, "attr", None)
            if spelled == name:
                return f"{symbol} is not defined there (found a call at line {node.lineno})"
    return f"{symbol} is not defined there (found nothing by that name)"


def _assigned_names(body: list[ast.stmt]) -> set[str]:
    """The plain names these statements bind by `=` or an annotated `: T = …`, nothing nested.

    A bare annotation (`LIMIT: int`, no value) binds nothing at import, so it
    is not a definition.
    """
    names: set[str] = set()
    for node in body:
        if isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif (
            isinstance(node, ast.AnnAssign)
            and node.value is not None
            and isinstance(node.target, ast.Name)
        ):
            names.add(node.target.id)
    return names


def _shell_definition(source: str, symbol: str) -> str | None:
    """Why `symbol` is not a column-zero `name() {` or `case_name() {` here, or None."""
    name = re.escape(symbol)
    if re.search(rf"^(?:case_)?{name}\(\)\s*\{{", source, re.MULTILINE):
        return None
    for number, line in enumerate(source.splitlines(), start=1):
        if re.search(rf"\b{name}\b", line):
            return (
                f"{symbol} is not a column-zero `{symbol}() {{` definition "
                f"(found line {number}: {line.strip()[:60]!r})"
            )
    return f"{symbol} is not defined there (found nothing by that name)"


def _typescript_definition(source: str, symbol: str) -> str | None:
    """Why `symbol` is not a column-zero TypeScript definition here, or None.

    A definition is `function`/`class`/`const`/`let`/`interface`/`type`/`enum`
    at column zero, optionally `export`ed (`export default`, `async`, a
    generator's `*` included) — the TypeScript carrier's `// road:` marker sits
    above exactly such a line. A line that merely calls the symbol never
    resolves it.
    """
    name = re.escape(symbol)
    definition = (
        rf"^(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:async\s+)?"
        rf"(?:function\*?|class|const|let|interface|type|enum)\s+{name}\b"
    )
    if re.search(definition, source, re.MULTILINE):
        return None
    for number, line in enumerate(source.splitlines(), start=1):
        if re.search(rf"\b{name}\b", line):
            return (
                f"{symbol} is not a column-zero definition (function, class, const, "
                f"interface, type) (found line {number}: {line.strip()[:60]!r})"
            )
    return f"{symbol} is not defined there (found nothing by that name)"


def resolve_example(root: Path, example: str) -> str | None:
    """Why `path::symbol` does not resolve under `root`, or None when it does.

    A `.py` file is read with `ast` (`_python_definition`); a `.sh` file is a
    shell file whose definition line is `name() {` or a drive's `case_name() {`
    at column zero, brace required (`_shell_definition`); a `.ts`/`.tsx` file is
    the face's carrier, a column-zero definition (`_typescript_definition`). A
    line that merely calls the symbol never resolves it. Those are the carriers
    a marker has; a file of any other suffix is refused, naming the suffix.
    """
    path, sep, symbol = example.partition("::")
    if not sep or not path or not symbol:
        return f"example {example!r} is not <path>::<symbol>"
    target = root / path
    if not target.is_file():
        return f"example {example!r}: {path} does not exist"
    readers = {
        ".py": _python_definition,
        ".sh": _shell_definition,
        ".ts": _typescript_definition,
        ".tsx": _typescript_definition,
    }
    reader = readers.get(target.suffix)
    if reader is None:
        suffix = repr(target.suffix) if target.suffix else "suffix-less"
        carried = "an example is carried by .py, .sh, .ts or .tsx"
        return f"example {example!r}: {path} is a {suffix} file: {carried}"
    text = target.read_text(encoding="utf-8", errors="replace")
    why = reader(text, symbol)
    return f"example {example!r} in {path}: {why}" if why else None


def import_road(dotted: str) -> object:
    """The object a Python road's dotted name imports as: the longest module, then attributes."""
    parts = dotted.split(".")
    for cut in range(len(parts), 0, -1):
        try:
            obj: object = importlib.import_module(".".join(parts[:cut]))
        except ModuleNotFoundError:
            continue
        for attribute in parts[cut:]:
            obj = getattr(obj, attribute)
        return obj
    raise ModuleNotFoundError(dotted)


def _app_label(marker: Any) -> str | None:
    parts = Path(marker.path).parts
    return parts[1] if len(parts) > 2 and parts[0] == "apps" else None


def _check_import(marker: Any, disabled: frozenset[str]) -> None:
    if marker.carrier != "py" or not marker.import_path:
        return
    if _app_label(marker) in disabled:
        return  # a disabled app's modules cannot import in this world; annotated instead
    try:
        obj = import_road(marker.import_path)
    except Exception as error:  # any failure to import is could-not-look
        raise CouldNotLook(
            f"{marker.path}:{marker.line}: the road for {marker.job!r} does not import as "
            f"{marker.import_path} ({type(error).__name__}: {error})"
        ) from error
    declared = getattr(obj, "__road__", None)
    if not isinstance(declared, dict):
        raise CouldNotLook(
            f"{marker.path}:{marker.line}: {marker.import_path} imports but carries no "
            f"__road__ — the census reads a marker the running code does not have"
        )
    if declared.get("job") != marker.job:
        raise CouldNotLook(
            f"{marker.path}:{marker.line}: the census reads job {marker.job!r} but "
            f"{marker.import_path}.__road__ says {declared.get('job')!r}"
        )


def _tree(root: Path) -> str | None:
    try:
        done = subprocess.run(  # noqa: S603 — argv list to `git` with the checkout root; no shell
            ["git", "-C", str(root), "rev-parse", "HEAD^{tree}"],  # noqa: S607 — `git` from PATH in the developer's checkout
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip() or None


def unmarked(root: Path) -> dict[str, Any]:
    """Rule 84's copy classes, measured by the rule's own check; `not measured` without it.

    The classes are the rule's recorded ones; a frozen class at zero has no line (rule 84).
    """
    gate = _engine("gate")
    rule = next((r for r in gate.RULES if str(r.get("id")) == "84"), None)
    if rule is None:
        return {"measured": False, "reason": "rule 84 absent", "total": None, "classes": {}}
    classes = {str(k): 0 for k in rule.get("ratchets") or {}}
    for finding in _engine("checks").road_uniqueness(root, rule).findings:
        if finding.klass in classes:
            classes[finding.klass] += 1
    return {
        "measured": True,
        "reason": None,
        "total": sum(classes.values()),
        "classes": dict(sorted(classes.items())),
    }


#: Scaffold flags `roads shape` holds back: it plans a write, never a check, list or removal.
UNFORWARDED = frozenset({"--dry-run", "--check", "--list", "--remove"})


def arm_flags(held: Iterable[str]) -> list[argparse.Action]:
    """The scaffold parser's own flags not in `held`, each renamed `arm_<dest>` for forwarding."""
    from apps.core.management.commands.scaffold import Command as Scaffold

    taken = set(held) | UNFORWARDED
    found: list[argparse.Action] = []
    for action in Scaffold().create_parser("manage.py", "scaffold")._actions:
        if action.option_strings and not set(action.option_strings) & taken:
            clone = copy.copy(action)
            clone.dest = f"arm_{action.dest}"
            found.append(clone)
    return found


def _forwarded(action: argparse.Action, value: object) -> list[str]:
    """The words that hand `value` back to the scaffold as the flag `action` names."""
    if value in (None, False, action.default):
        return []
    flag = action.option_strings[-1]
    return [flag] if value is True else [flag, str(value)]


def planted_rules() -> dict[str, set[str]]:
    """`{path: {rule id}}` for every path a rule's plan plants, and its path inside its app."""
    plants, gate = _engine("engine.plants"), _engine("gate")
    plants.prime_plant_resolution()
    found: dict[str, set[str]] = {}
    for form in plants.plan_forms(gate.RULES):
        at = str(plants.resolve_plant_text(str(form.form["plant_at"])))
        parts = Path(at).parts
        keys = {at, "/".join(parts[2:])} if len(parts) > 2 and parts[0] == "apps" else {at}
        for key in keys:
            found.setdefault(key, set()).add(str(form.rid))
    return found


def _by_id(rule: str) -> tuple[int, str]:
    return (int(rule), "") if rule.isdigit() else (1 << 30, rule)


def answers_to(path: str, label: str, planted: dict[str, set[str]]) -> str:
    """The rules a planned path answers to, as `roads shape` prints them under it."""
    inside = f"apps/{label}/"
    rules = planted.get(path.removeprefix(inside) if path.startswith(inside) else path, set())
    if not rules:
        return "    answers to: no rule plants a path like this one"
    return "    answers to: rules " + " ".join(sorted(rules, key=_by_id))


class Command(BaseCommand):
    help = (
        "Print every job this platform does one way, the road that stands for it, "
        "its contract and its worked example. Exit 2 when a road cannot be vouched for."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("job", nargs="?", help="Print one job's road, or `shape`.")
        parser.add_argument(
            "words", nargs="*", help="shape: <shape> <words> — what `scaffold` would write."
        )
        parser.add_argument(
            "--json", action="store_true", help="The roads/1 document, for the loop."
        )
        parser.add_argument(
            "--root",
            default=None,
            help="The tree the census reads (default: this checkout). Imports stay this process's.",
        )
        parser.add_argument(
            "--remove",
            action="store_true",
            help="refused: a removal plans as `scaffold <shape> <app> <Noun> --remove --dry-run`",
        )
        self.arm = arm_flags(parser._option_string_actions)
        for action in self.arm:
            parser._add_action(action)

    def handle(self, *args: Any, **options: Any) -> None:
        flags = [
            word
            for action in getattr(self, "arm", [])
            for word in _forwarded(action, options.get(action.dest))
        ]
        if options.get("remove"):
            words = " ".join(str(word) for word in options["words"]) or "<shape> <app> <Noun>"
            self.stderr.write(
                "roads: `--remove` is not a road to plan — `roads shape` plans what the scaffold "
                f"would write. A removal plans as `scaffold {words} --remove --dry-run`."
            )
            raise SystemExit(2)
        if options["job"] == SHAPE:
            self.shape([str(word) for word in options["words"]], flags)
            return
        if flags:
            self.stderr.write(f"roads: {' '.join(flags)} is the scaffold's — `roads shape` only")
            raise SystemExit(2)
        if options["words"]:
            self.stderr.write(f"roads: a job takes no further words — {options['words']!r}")
            raise SystemExit(2)
        census_module = _engine("roads")

        root = Path(options["root"] or settings.BASE_DIR).resolve()
        platform = sorted(_engine("partition").platform_apps())
        disabled = frozenset(_engine("worlds").disabled_app_labels())
        try:
            markers = census_module.census(root)
            standing = census_module.standing(markers)
            kept: list[Any] = []
            for marker in markers:
                first = standing[marker.job]
                if marker is first:
                    continue
                if marker.valve is None:
                    raise CouldNotLook(
                        f"{marker.path}:{marker.line}: a second road for {marker.job!r} beside "
                        f"{first.where} with no rule-84 valve above it — house rule 84 refuses it"
                    )
                kept.append(marker)
            worked = _engine("djb.rituals.divergence")
            removed = 0
            for marker in markers:
                reason = resolve_example(root, marker.example)
                if reason and worked.removed_worked_example(
                    root, marker.example.partition("::")[0]
                ):
                    removed += 1
                elif reason:
                    raise CouldNotLook(f"{marker.path}:{marker.line}: {reason}")
            for marker in markers:
                _check_import(marker, disabled)
        except (CouldNotLook, census_module.CensusError) as error:
            self.stderr.write(f"roads: could not look — {error}")
            raise SystemExit(2) from error

        jobs = sorted(standing)
        if options["job"]:
            if options["job"] not in standing:
                self.stderr.write(
                    f"roads: no job {options['job']!r} on this tree. The vocabulary: "
                    + (", ".join(jobs) or "(no roads marked)")
                )
                raise SystemExit(2)
            jobs = [options["job"]]

        # The `installed_apps` road's answer, as settings holds it (`LOCAL_APPS` is
        # `discover_local_apps`'s list, `DJB_DISABLED_APPS` already subtracted): an
        # app never imports `config`, and walking the registry here would be a
        # discovery seam the partition census refuses.
        installed = {name.removeprefix("apps.") for name in settings.LOCAL_APPS}
        product_apps = sorted(installed - set(platform))
        unmarked_counts = unmarked(root)
        kept_rows = [
            {
                "job": m.job,
                "path": m.path,
                "line": m.line,
                "reason": m.valve,
                "platform_road": standing[m.job].where,
            }
            for m in kept
            if m.job in jobs
        ]
        tree = _tree(root)

        if options["json"]:
            document = {
                "schema": SCHEMA,
                "tree": tree,
                "platform_apps": platform,
                "roads": [standing[job].as_json() for job in jobs],
                "kept": kept_rows,
                "unmarked": unmarked_counts,
            }
            self.stdout.write(json.dumps(document, indent=2))
            return

        shown = [standing[job] for job in jobs]
        on_platform = sum(1 for m in shown if m.partition == "platform")
        on_product = len(shown) - on_platform
        if on_product:
            product = str(on_product)
        else:
            product = "none" if product_apps else TEMPLATE_PRODUCT
        if unmarked_counts["measured"]:
            tail = f"unmarked {unmarked_counts['total']} (see --explain 84)"
        else:
            tail = f"unmarked: not measured ({unmarked_counts['reason']})"
        self.stdout.write(
            f"roads · {len(jobs)} jobs · {len(shown)} roads (platform {on_platform} · "
            f"product {product}) · tree {tree or 'unknown — not a git checkout'} · {tail}"
        )
        width = max((len(m.job) for m in shown), default=0) + 2
        for marker in shown:
            where = marker.import_path or (
                f"{marker.path}::{marker.symbol}" if marker.symbol else marker.path
            )
            note = (
                "  (optional app, disabled in this world)" if _app_label(marker) in disabled else ""
            )
            self.stdout.write(
                f"{marker.job:<{width}}{where}  {marker.partition}  {marker.carrier}  "
                f"{marker.kind}{note}"
            )
            self.stdout.write(f"    {marker.contract}")
            self.stdout.write(f"    example  {marker.example}")
        for row in kept_rows:
            self.stdout.write(
                f"kept  {row['job']}  {row['path']}:{row['line']} beside {row['platform_road']}"
                f" — {row['reason']}"
            )
        if removed:
            self.stdout.write(WORKED_EXAMPLE_REMOVED.format(n=removed))

    def shape(self, words: list[str], flags: list[str] | None = None) -> None:
        """`roads shape <shape> <words>`: the scaffold's dry run, each path's rules, `next:`."""
        planned, said = io.StringIO(), io.StringIO()
        words = [*words, *(flags or [])]
        try:
            call_command("scaffold", *words, "--dry-run", stdout=planned, stderr=said)
        except CommandError as refused:
            self.stderr.write(f"roads shape: {refused}")
            raise SystemExit(refused.returncode) from refused
        label = words[2] if words[:1] == ["adopt"] and len(words) > 2 else words[1]
        planted = planted_rules()
        self.stdout.write(
            f"roads shape · {' '.join(words)} · what the scaffold would write, and the rules "
            "each path answers to"
        )
        for line in planned.getvalue().splitlines():
            self.stdout.write(line)
            if matched := WOULD.match(line):
                self.stdout.write(answers_to(matched.group("path"), label, planted))
        self.stdout.write(f"next: uv run python manage.py scaffold {' '.join(words)}")
