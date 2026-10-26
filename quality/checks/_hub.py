"""What two or more sections share, and what they need at import time."""

from __future__ import annotations

import ast
import functools
import importlib
import importlib.util
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from quality.could_not_look import CouldNotLook
from quality.sdk.reexports import reexports
from quality.worlds import SERVICE_MODULE, descendants, parse_python, py_files, read_text

# Directory parts never scanned — `quality.worlds.SKIP_PARTS`, the walk's own.


@dataclass
class Finding:
    path: str  # relative to the scanned root
    line: int
    msg: str
    # : Which CLASS of the rule this finding belongs to, when the rule has more
    # : than one (rule 16's naming grammar has seven). It is what the gate's
    # : ratchets are counted against, so a backlog in one class cannot pay for
    # : growth in another. Empty for a rule with a single subject.
    klass: str = ""
    #: How many counted units this finding carries toward its class's ratchet.
    weight: int = 1

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.msg}"


@dataclass
class CheckResult:
    findings: list[Finding] = field(default_factory=list)
    targets_matched: dict = field(default_factory=dict)

    def hit(
        self,
        path: Path | str,
        line: int,
        msg: str,
        root: Path | None = None,
        klass: str = "",
        weight: int = 1,
    ) -> None:
        rel = str(path)
        if root is not None and isinstance(path, Path):
            try:
                rel = str(path.relative_to(root))
            except ValueError:
                rel = str(path)
        self.findings.append(Finding(rel, line, msg, klass, weight))

    def count(self, key: str, n: int = 1) -> None:
        self.targets_matched[key] = self.targets_matched.get(key, 0) + n


#: The engine reads a file, parses it and walks a tree ONCE — `quality.worlds`
#: owns the three; these names are the ones every check here already calls.
_read = read_text
_parse = parse_python
_py_files = py_files


def _app_dirs(root: Path) -> list[Path]:
    """Every app package under apps/ — a directory with an apps.py."""
    base = root / "apps"
    if not base.exists():
        return []
    return sorted(d for d in base.iterdir() if d.is_dir() and (d / "apps.py").exists())


def _exempt(rule: dict, path_rel: str, function: str | None = None) -> bool:
    """Whether rules.yaml exempts this site, by path (and function when given).

    Exemptions live in the rule's scope, each with a reason — a judgement a
    person wrote down, visible in one file, not an edit to somebody's app.
    """
    for entry in (rule.get("scope") or {}).get("exemptions") or []:
        if entry.get("path") and entry["path"] != path_rel:
            continue
        wanted = entry.get("function")
        if wanted and wanted != function:
            continue
        if entry.get("path") or wanted:
            return True
    return False


def _enclosing_functions(tree: ast.Module) -> list[tuple[int, int, str]]:
    """(start, end, name) for every function, for attributing a line to one."""
    spans: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            spans.append((node.lineno, node.end_lineno or node.lineno, node.name))
    return spans


def _function_at(spans: list[tuple[int, int, str]], line: int) -> str | None:
    best: tuple[int, str] | None = None
    for start, end, name in spans:
        if start <= line <= end and (best is None or start > best[0]):
            best = (start, name)
    return best[1] if best else None


# --- scoped-model discovery (rules 8, 12, 13) --------------------------------

_SCOPED_BASE = "TenantScopedModel"


def scoped_model_names(root: Path) -> set[str]:
    """Every class name that inherits TenantScopedModel, transitively, by AST.

    Derived from the tree on every run: a new scoped model is in scope the
    moment it exists, without anybody editing a list.
    """
    return descendants(root, _SCOPED_BASE)


# --- the `pilecap` facade, read as re-exports (rule 96) ------------------------

#: The facade package a product imports; its modules re-export the platform's names.
FACADE = "pilecap"
#: The facade's keep-back table: it declares names and exports none.
FACADE_KEPT_BACK = "_internal.py"


def facade_reexports(root: Path) -> dict[tuple[str, str], tuple[str, str]]:
    """`{(facade module, exported name): (source module, its name)}`, read off `pilecap/*.py`."""
    home = root / FACADE
    files = sorted(home.glob("*.py")) if home.is_dir() else []
    return dict(_facade_reexports(tuple((p, p.stat().st_mtime_ns) for p in files)))


@functools.lru_cache(maxsize=8)
def _facade_reexports(
    files: tuple[tuple[Path, int], ...],
) -> tuple[tuple[tuple[str, str], tuple[str, str]], ...]:
    out: list[tuple[tuple[str, str], tuple[str, str]]] = []
    for path, _stamp in files:
        if path.name == FACADE_KEPT_BACK:
            continue
        tree = parse_python(path)
        if tree is None:
            continue
        module = FACADE if path.stem == "__init__" else f"{FACADE}.{path.stem}"
        out.extend(((module, local), source) for local, source in reexports(tree, module).items())
    return tuple(out)


# --- the hot-path registry (rules 5 + 35, ADR gate-2) --------------------------
#
# The registry is rule 35's `registry:` list in quality/rules.yaml (dotted
# selector paths — the plan's ratified location); quality/budgets.yaml
# `hot_path_query_counts` holds each entry's gate-scale statement count under
# the rising-floor grammar. Rule 5's check holds the seam (every entry counted,
# every count registered, every entry citing the measurement-doc line that
# earned it — measured before enforced, the shape); rule 35's check runs
# the probe that EXPLAINs the probed entries' real reads.


def _dotted_to_file(root: Path, dotted: str) -> str:
    """The longest module-file prefix of a dotted path, as a repo-relative path."""
    parts = dotted.split("#")[0].split(".")
    for length in range(len(parts), 0, -1):
        candidate = Path(*parts[:length]).with_suffix(".py")
        if (root / candidate).is_file():
            return str(candidate)
    return "quality/rules.yaml"


def api_modules(app: Path) -> list[Path]:
    """Where an app's routes live — `api.py`, or every module of an `api/` package.

    Both halves of rule 5 used to ask `app / "api.py"` and `continue` when
    it was absent, so an app whose routes had outgrown one file was not covered
    by a rule whose own statement says "every paginated list endpoint's app".
    The statement was the contract and the implementation was narrower than it;
    this is that discrepancy closed, not the contract widened. `apps/core` is the
    first such app (B-CORE's organizations, memberships and invitations lists),
    and every one of its three paginated routes was outside the census.

    `config/api.py` mounts an app by the `router` its `api` module exposes and
    does not care which of the two shapes holds it, so the population here is
    the one the mount already accepts.
    """
    flat = app / "api.py"
    if flat.is_file():
        return [flat]
    package = app / "api"
    if package.is_dir():
        return sorted(p for p in package.glob("*.py"))
    return []


def _app_is_pinned(app: Path) -> bool:
    """Whether anything in this app's tests pins a query count.

    App-level on purpose — route accuracy is review's, and rule 5's
    `does_not_cover` says so. It is also why the canaries plant into the gate's
    own probe app: a pinned app absorbs any route planted into it.
    """
    tests = app / "tests"
    if not tests.exists():
        return False
    return any(
        "assert_num_queries" in _read(p) or "assertNumQueries" in _read(p)
        for p in sorted(tests.rglob("*.py"))
    )


# --- rule 8: scoped models are read through for_tenant ------------------------

_RULE8_FILES = {
    "api.py",
    "mcp.py",
    SERVICE_MODULE,
    "selectors.py",
    "activities.py",
    "consumers.py",
    "admin.py",
    "receivers.py",
}
_WRITE_MANAGER_CALLS = {"create", "get_or_create", "update_or_create", "bulk_create", "bulk_update"}
# --- the one event grammar, imported -------------------------------------------
#
# `<app>.<noun>.<past-verb>` is the RUNTIME's grammar first: `apps.events.events`
# holds `NAME_SEGMENTS` beside `check_name`, the refusal an undeclared or
# misshapen name meets at `emit`. The engine reads the same constant rather than
# typing the count again, so the gate cannot pass a shape the runtime refuses.
# It imports the CONSTANT and never `check_name` itself: the refusal's second
# half reads the live app registry, which the engine never boots — the shape is
# the half a static read can judge. A module that will not import is
# could-not-look (exit 2, naming the rule), never a pass on a grammar of zero.
_EVENT_GRAMMAR_MODULE = "apps.events.events"
_EVENT_GRAMMAR_CONSTANT = "NAME_SEGMENTS"
#: One segment of a name: what rule 16 and the plant census both accept.
EVENT_SEGMENT = r"[a-z0-9_]+"


def event_name_segments() -> int:
    """`<app>.<noun>.<past-verb>`'s segment count, read from the runtime's own module."""
    try:
        module = importlib.import_module(_EVENT_GRAMMAR_MODULE)
        count = getattr(module, _EVENT_GRAMMAR_CONSTANT)
    except Exception as exc:  # noqa: BLE001 — every failure here is the same could-not-look
        raise CouldNotLook(
            f"the event grammar `{_EVENT_GRAMMAR_MODULE}.{_EVENT_GRAMMAR_CONSTANT}` "
            f"(the shape `check_name` refuses by) would not read: {exc}"
        ) from exc
    if not isinstance(count, int) or count < 2:
        raise CouldNotLook(
            f"`{_EVENT_GRAMMAR_MODULE}.{_EVENT_GRAMMAR_CONSTANT}` is {count!r} — not a "
            "segment count a name of an app, a noun and a verb can have"
        )
    return count


def event_shape() -> re.Pattern[str]:
    """A whole event name in the one grammar: `NAME_SEGMENTS` segments of `EVENT_SEGMENT`."""
    return re.compile("^" + r"\.".join([EVENT_SEGMENT] * event_name_segments()) + "$")


# --- floor proxies for the Django-check rules -----------------------------------
#
# The system checks (rules 2, 3, 11, 13-half, 15, 17, 21) run inside Django and
# report violations, not counts — so their UNBOUND guard is an AST-side proxy:
# a cheap count of the same subject, floored in rules.yaml. A registry that
# somehow resolved to nothing would trip the proxy here even though the check
# itself printed a clean nothing.


def count_model_classes(root: Path, rule: dict) -> CheckResult:
    """The model population every model-reading rule shares (`_model_classes`)."""
    out = CheckResult()
    out.count("model_classes", len(_model_classes(root)))
    return out


def count_routes(root: Path, rule: dict) -> CheckResult:
    """Rules 3 and 17's floor: how many routes there are to be judged.

    , 2026-08-24 — (a)'s twin, found while closing it and booked rather
    than swept in. This walked `api.py` by BASENAME and so read 69 where the
    live ninja registry has 86: `apps/core/api/routes.py`'s seventeen routes
    were outside the floor of both rules that use this proxy. Nothing was
    unenforced (djb.E003/E030/E031 and djb.E017 all read the live registry),
    but a floor five below the truth cannot notice its subject shrinking, which
    is the whole job of a floor. `api_modules()` is the same population
    `config/api.py` mounts, and the same one rules 5 and 41 walk — one
    function, so the four rules cannot come to disagree about what an API
    module is.
    """
    out = CheckResult()
    for path in [module for app in _app_dirs(root) for module in api_modules(app)]:
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if _is_route_decorator(dec):
                    out.count("routes")
    return out


_EVENT_KINDS_NAME = "EVENT_KINDS"


# --- class 3: the undecided noun, and the draft line that closes it ----------
#
# The rule-59 amendment the owner SIGNED 2026-09-21. `kind_of_event`
# used to be the only thing in the tree that noticed an undecided noun, and it
# noticed it INSIDE the emitting service's transaction: the consumer added an
# event name, forgot the `EVENT_KINDS` line, and lost the WRITE — six `usage`
# service tests red, the doors 500ing, availability spent on a missing
# declaration. The amendment moves that refusal to the two places that can
# make it without costing a write: the socket drops the frame
# (`realtime.consumers._may_read`, which already caught the same refusal), and
# THIS CLASS refuses the tree — once per undecided noun, at the constant's own
# line, carrying the `EVENT_KINDS` line to paste.
#
# THE FINDING IS THE DRAFT. A refusal that says "decide this noun" sends the
# reader to three files to work out which kind; the walk already knows, because
# class 1 resolves the same emit site's payload to an `Out` and rule 16 pairs an
# `Out` with its model. So the message ends in the line, and the reader pastes it.

#: What `declared_names` counts: an UPPERCASE module-level string constant in an
#: app's `events.py` whose value has at least `event_name_segments()`
#: dot-separated segments — `<app>.<noun>.<past-verb>`, the runtime's grammar.


#: The sentence rule 59's third class ends every finding with, and the one seam
#: the census below reads the draft line back out of. SPELLED ONCE: the `hit()`
#: above interpolates this constant, so a reword cannot move the finding without
#: moving the census that reads it back.
_UNDECIDED_DRAFT_MARKER = f"Paste it into {_EVENT_KINDS_NAME}:"


def undecided_noun_census(root: Path, rule: dict) -> list[str]:
    """Rule 59's `census:` — every undecided noun on THIS tree, grouped by app.

    C1 made the FINDING the draft: one undecided noun prints the
    `EVENT_KINDS` line to paste. A product folding the template has a dozen of
    them at once, scattered through a gate's output between everything else it
    said, and reassembling them into the block each `events.py` actually needs
    is the reader's job every time. This is that block, printed by
    `--explain 59` (C0's `census:` seam).

    ONE WALKER, NEVER A SECOND. It runs rule 59's own check and keeps the
    `undecided_noun` findings, reading the draft back out of the message at the
    marker the finding itself ends with — so a census that disagreed with the
    gate would be a census reading a different tree, not a second opinion about
    this one. A management command walking the emit sites again was the
    rejected alternative (team C's § 5): two walkers, two answers.

    Returns a line per printed row, `[]` when this tree has decided every noun.
    """
    result = org_scoped_events_carry_their_branch(root, rule)
    by_app: dict[str, list[str]] = {}
    for finding in result.findings:
        if finding.klass != "undecided_noun":
            continue
        # `apps/<label>/events.py` — the path this class always hits at.
        parts = Path(finding.path).parts
        app_label = parts[1] if len(parts) > 1 else finding.path
        _, marker, draft = finding.msg.rpartition(_UNDECIDED_DRAFT_MARKER)
        by_app.setdefault(app_label, []).append(
            draft.strip() if marker else f"{finding.path}:{finding.line}: {finding.msg}"
        )
    lines: list[str] = []
    for app_label in sorted(by_app):
        drafts = by_app[app_label]
        noun_word = "noun" if len(drafts) == 1 else "nouns"
        lines.append(
            f"apps/{app_label}/events.py — {len(drafts)} undecided {noun_word}; "
            f"paste into {_EVENT_KINDS_NAME}:"
        )
        lines.extend(f"    {draft}" for draft in drafts)
    return lines


# --- the member floors: a per-member ratchet lives with the member --------------

#: Where the floors of the members that are not apps are written.
MEMBER_FLOORS_FILE = "quality/ratchet_floors.yaml"
#: The `AppConfig` attribute an app's floors are declared under.
APP_FLOORS_ATTRIBUTE = "ratchet_floors"


@dataclass(frozen=True)
class MemberFloor:
    """One recorded floor: rule, ratchet class (`<member>.<class>`), count, `path:line`."""

    rule: str
    klass: str
    count: int
    source: str


def _app_config_class(tree: ast.Module) -> ast.ClassDef | None:
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                terminal = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
                if str(terminal).endswith("AppConfig"):
                    return node
    return None


def _app_floors_node(config: ast.ClassDef) -> ast.expr | None:
    for statement in config.body:
        if isinstance(statement, ast.Assign):
            targets = statement.targets
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == APP_FLOORS_ATTRIBUTE for t in targets):
            return statement.value
    return None


def _floor_entry(
    rid: str, klass: str, count: object, source: str, member_rules: Mapping[str, Iterable[str]]
) -> tuple[MemberFloor | None, str]:
    allowed = member_rules.get(rid)
    if allowed is None:
        rules = ", ".join(sorted(member_rules)) or "none"
        return None, f"{source}: rule {rid!r} keeps no member floors (the rules that do: {rules})"
    member, _, suffix = klass.partition(".")
    if not member or suffix not in set(allowed):
        return None, (
            f"{source}: {klass!r} is not a class of rule {rid} "
            f"(its classes: {', '.join(sorted(allowed))})"
        )
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        return None, f"{source}: {klass!r} is {count!r}, not a count"
    return MemberFloor(rid, klass, count, source), ""


def read_member_floors(
    root: Path, member_rules: Mapping[str, Iterable[str]], must_declare: Iterable[str]
) -> tuple[list[MemberFloor], list[str]]:
    """Every member's floors: each app's `AppConfig.ratchet_floors`, then the platform's file.

    `must_declare` names the apps whose missing declaration is a problem (exit 2), never a zero.
    """
    from config.settings.discovery import discover_apps

    floors: list[MemberFloor] = []
    problems: list[str] = []
    required = set(must_declare)
    labels = {app.label for app in discover_apps(root / "apps")}
    for label in sorted(labels):
        rel = f"apps/{label}/apps.py"
        tree = _parse(root / rel)
        config = _app_config_class(tree) if tree is not None else None
        node = _app_floors_node(config) if config is not None else None
        if node is None:
            if label in required:
                problems.append(
                    f"{rel} declares no `{APP_FLOORS_ATTRIBUTE}` — an app owns its ratchet "
                    "floors (rules " + ", ".join(sorted(member_rules)) + "); declare "
                    f"`{APP_FLOORS_ATTRIBUTE}: ClassVar[dict[str, int]] = {{...}}` keyed "
                    "`<rule>.<class>`, `{}` when it holds none"
                )
            continue
        if not isinstance(node, ast.Dict):
            problems.append(f"{rel}: `{APP_FLOORS_ATTRIBUTE}` is not a dict literal")
            continue
        for key, value in zip(node.keys, node.values, strict=True):
            source = f"{rel}:{getattr(key, 'lineno', node.lineno)}"
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                problems.append(f"{source}: a `{APP_FLOORS_ATTRIBUTE}` key is not a string")
                continue
            rid, _, suffix = key.value.partition(".")
            try:
                count: object = ast.literal_eval(value)
            except ValueError:
                count = None
            floor, why = _floor_entry(rid, f"{label}.{suffix}", count, source, member_rules)
            if why:
                problems.append(why)
            elif floor is not None:
                floors.append(floor)
    path = root / MEMBER_FLOORS_FILE
    try:
        document = yaml.compose(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        problems.append(f"{MEMBER_FLOORS_FILE} could not be read: {error}")
        return floors, problems
    if document is None:
        return floors, problems
    if not isinstance(document, yaml.MappingNode):
        problems.append(f"{MEMBER_FLOORS_FILE} is not a mapping of rule id → class → count")
        return floors, problems
    for rule_node, classes in document.value:
        rid = str(rule_node.value)
        if not isinstance(classes, yaml.MappingNode):
            problems.append(f"{MEMBER_FLOORS_FILE}: rule {rid} is not a mapping of class → count")
            continue
        for key_node, value_node in classes.value:
            klass = str(key_node.value)
            source = f"{MEMBER_FLOORS_FILE}:{key_node.start_mark.line + 1}"
            if klass.partition(".")[0] in labels:
                problems.append(
                    f"{source}: {klass!r} is an app's floor — it lives in "
                    f"apps/{klass.partition('.')[0]}/apps.py `{APP_FLOORS_ATTRIBUTE}`"
                )
                continue
            try:
                count = int(value_node.value)
            except (TypeError, ValueError):
                count = value_node.value
            floor, why = _floor_entry(rid, klass, count, source, member_rules)
            if why:
                problems.append(why)
            elif floor is not None:
                floors.append(floor)
    return floors, problems


from quality.checks.rule_16_the_rest_of_the_grammar import (  # noqa: E402
    _model_classes,
)
from quality.checks.rule_41_clause import _is_route_decorator  # noqa: E402
from quality.checks.rule_59 import org_scoped_events_carry_their_branch  # noqa: E402
