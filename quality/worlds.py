"""Which apps this run's world holds — and what the self-test owes because of it.

THE FINDING THIS MODULE EXISTS FOR. `DJB_DISABLED_APPS=example
python -m quality.gate --selftest` exited **2 with fifteen dead canaries** on the
tree that shipped this: six rules stopped being able to demonstrate a failure at
all, and nothing in the engine could say whether that was a broken gate or a
smaller world. The gate's own self-test world was **optional and did not know
it**. A product that takes the worked example out of production — the one
subtraction `config/settings/discovery.py` exists to allow — took the gate's
teeth with it, silently.

There are three separate facts here and the engine had none of them:

1. **Which apps a deployment MAY remove.** `optional = True` on an `AppConfig`
   (`config/settings/discovery.py`). Read off the declarations, never a hand
   list — the same law as `INSTALLED_APPS`, for the same reason: a list here is
   a file every app in a parallel wave has to queue up to edit.
2. **Which apps THIS run removed.** `DJB_DISABLED_APPS`, read exactly the way
   `config/settings/base.py:117` reads it, so the gate's idea of the world and
   the process's idea cannot drift.
3. **Which world a canary form belongs to.** Derived from its plant path —
   `apps/<label>/...` — because that is where the derivation is honest for
   almost every form; DECLARED with `needs_app:` where it is not (rule 41's
   `undeclared_example_route` plants into the probe app and asserts about the
   *example* census, so its world is example's and no path can say so).

The self-test then plants only the forms whose world this run holds, and the
recorded population falls by exactly the number it did not plant — printed, per
rule, per run. **Disabling an optional app changes the counts, not the verdict.**

The complement, and the half that keeps this from becoming a way to switch a
rule off: a rule whose canaries ALL live in an app a deployment may remove is a
rule that can be deleted by an environment variable. `residence` below is that
census, and `quality/gate.py` refuses past the recorded backlog.

Nothing here imports Django's app registry or boots anything: `discover_apps` is
a static AST read, and the self-test runs long before any settings module is
loaded.

THE SECOND AXIS, added when the engine grew a rule about a language that is not
Python: **which trees this checkout holds**. An app can be removed from a
deployment; a whole tree can be absent from a template that never grew one. The
answer has the same shape as the first — declarations (`scope_kinds:` and
`needs_tree:` in `quality/rules.yaml`), a derivation per run, and counts that
fall while the verdict does not — and it is at the foot of this file under
"scope kinds".
"""

from __future__ import annotations

import ast
import os
import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from apps.core.roads import road
from quality.reason_floor import MIN_REASON
from quality.sdk.reexports import reexports

# The plant-path shape every fixture entry uses: `apps/<label>/<file>`.
_APPS_DIR = "apps"


def optional_app_labels(root: Path) -> frozenset[str]:
    """Every app label whose own `AppConfig` declares `optional = True`.

    Discovery, never a hand list (fact 1 in the header). Read through
    `config.settings.discovery`, which is the module that already owns this
    question for `INSTALLED_APPS` — a second reader of `apps.py` would be a
    second opinion about what optional means.
    """
    from config.settings.discovery import discover_apps

    return frozenset(app.label for app in discover_apps(root / _APPS_DIR) if app.optional)


def disabled_app_labels() -> frozenset[str]:
    """The labels `DJB_DISABLED_APPS` names for THIS run.

    Parsed the way `config/settings/base.py` parses it (`env.list`, a comma
    list), so the gate's world and the process's world are the same world. An
    empty or unset variable is the ordinary development tree: nothing removed.

    Nothing is validated here. Whether a named label exists, and whether it was
    allowed to be named, is `discover_apps`'s refusal to make while settings are
    being read — repeating that judgement in the gate would be a second place to
    disagree about it.
    """
    raw = os.environ.get("DJB_DISABLED_APPS", "")
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def app_of_plant(plant_at: str) -> str | None:
    """The app label a plant path lands in, or None for a path outside `apps/`.

    `apps/example/models.py` -> `example`; `quality/hotpaths.py` -> None. A
    fixture planted outside `apps/` belongs to no app's world and is planted in
    every world.
    """
    parts = Path(str(plant_at)).parts
    if len(parts) >= 2 and parts[0] == _APPS_DIR:
        return parts[1]
    return None


def app_of_dotted(dotted: str) -> str | None:
    """The app label a dotted registry path names, or None.

    `apps.example.selectors.list_widgets` -> `example`. The `#suffix` a door-tier
    entry carries (`...list_widgets#session`) is not part of the module path and
    is ignored.
    """
    head = str(dotted).split("#", 1)[0]
    parts = head.split(".")
    if len(parts) >= 2 and parts[0] == _APPS_DIR:
        return parts[1]
    return None


def entry_world(entry: dict) -> str | None:
    """The app whose world this canary/negative form needs, or None for any world.

    Derived from the plant path, DECLARED by `needs_app:` where the derivation
    cannot see it (fact 3 in the header). An entry's extra files are part of the
    same form: if any of them lands in an app, the form needs that app — a
    two-file fixture whose second half is the app-resident one is exactly the
    shape a plant-target-only derivation would get wrong.
    """
    declared = entry.get("needs_app")
    if declared:
        return str(declared)
    for one in [entry, *(entry.get("extra_files") or [])]:
        label = app_of_plant(str(one["plant_at"]))
        if label is not None:
            return label
    return None


def entry_out_of_world(entry: dict, disabled: frozenset[str]) -> str | None:
    """The disabled app that puts this form out of this run's world, or None."""
    world = entry_world(entry)
    return world if world is not None and world in disabled else None


def rule_residence(rule: dict, optional: frozenset[str]) -> str | None:
    """The optional app that holds ALL of this rule's canary forms, or None.

    A rule with no canaries at all has no residence — that is `consistency()`'s
    finding ("fewer than two canary forms"), not this one's, and answering it
    twice would send a reader to the wrong repair. A rule with one canary form
    outside the optional apps is mixed and is not this census's business:
    rule 35 plants three forms in `core`, `events` and `realtime` and one in
    `quality/` itself, and a deployment without the worked example can still
    watch it fail four ways.
    """
    canaries = rule.get("canaries") or []
    if not canaries:
        return None
    worlds = {entry_world(entry) for entry in canaries}
    if len(worlds) != 1:
        return None
    only = next(iter(worlds))
    return only if only is not None and only in optional else None


def residence_census(rules: list[dict], optional: frozenset[str]) -> list[tuple[str, str]]:
    """(rule id, app) for every rule whose whole canary plan lives in an optional app.

    Ordered by rule id as `rules.yaml` holds them, so the printed census is a
    stable diff rather than a set that reshuffles.
    """
    found: list[tuple[str, str]] = []
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        app = rule_residence(rule, optional)
        if app is not None:
            found.append((str(rule["id"]), app))
    return found


#: An id the TEMPLATE minted: a plain integer (ADR gate-5). Spelled here as
#: well as in `quality/gate.py` because this module is the one that partitions
#: the census, and a partition that asked the engine for the predicate would
#: import the engine.
_TEMPLATE_ID_RE = re.compile(r"^\d+$")


def split_residence_census(
    census: list[tuple[str, str]],
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """(the template's members, the product's) — D4, ADR gate-5.

    THE NUMBER IS A TEMPLATE FACT. `selftest_residence_backlog` was measured
    over the template's own rules and is folded into every product unchanged; a
    product that added namespaced rules and found the census one over would
    have had to RETYPE a number it never measured, which is how a backlog stops
    meaning anything. So the recorded backlog holds the template's members and
    nothing else, and a product's own rules are counted against zero: the first
    namespaced rule that plants its whole canary plan into an optional app is
    exit 2, named, at the moment it is written — which is the only moment its
    author can cheaply re-home a form.
    """
    template = [row for row in census if _TEMPLATE_ID_RE.match(row[0])]
    product = [row for row in census if not _TEMPLATE_ID_RE.match(row[0])]
    return template, product


# --- registry-fed floors ---------------------------------------------------------
#
# A floor is a rising number a reviewer commits: `probed_paths: 11` says eleven
# registry entries were executed, and one below that is UNBOUND — the check may
# be watching nothing. That grammar is right, and it is wrong the moment the
# number counts members an optional app contributed: eleven becomes ten when a
# deployment removes the worked example, and the floor then reads as a broken
# gate about a world that is simply smaller.
#
# So a rule that carries a `registry:` declares, per floor, WHAT the number
# counts — and the declaration is as much about the numbers that must NOT move
# as about the ones that must. Two of the four bases lower the expectation, one
# says the number is a fact about `rules.yaml` and no deployment can change it,
# and the fourth says plainly that the registry cannot count it at all. All four
# are printed rather than assumed: a floor silently lowered for the wrong reason
# is the same defect as a floor left too high, pointing the other way.

#: floor basis -> what it counts, for the derivation and for the message.
#: `declared_members` and `opaque` never lower; the other two do.
REGISTRY_BASES: dict[str, str] = {
    "declared_members": (
        "the registry rows themselves — data in quality/rules.yaml, which no deployment "
        "removes, so the expectation does not move"
    ),
    "probed_members": "the registry entries this deployment can actually execute",
    "lookup_column_members": (
        "the columns named by `lookup_columns` on the entries this deployment can execute"
    ),
    "opaque": "something the registry cannot count — the reason is on the rule",
}

#: The bases whose members an absent app takes away. Everything else is held at
#: its recorded number, because a smaller deployment did not make it smaller.
LOWERING_BASES: frozenset[str] = frozenset({"probed_members", "lookup_column_members"})


def registry_members(rule: dict, basis: str) -> list[dict]:
    """The registry entries a floor basis counts."""
    registry = rule.get("registry") or []
    if basis == "probed_members":
        return [e for e in registry if e.get("pin") == "probe"]
    if basis == "lookup_column_members":
        return [e for e in registry if e.get("lookup_columns")]
    return list(registry)


def registry_entry_app(entry: dict) -> str | None:
    """The app a registry entry's members belong to.

    Derived from the dotted path, DECLARED by `needs_app:` where the path lies:
    `apps.core.models.ScopedQuerySet.governing` is probed through
    `apps.example.models.WidgetPolicy`, so its members are the example app's
    however core the path reads.
    """
    declared = entry.get("needs_app")
    if declared:
        return str(declared)
    return app_of_dotted(str(entry.get("path", "")))


def registry_contribution(rule: dict, basis: str, apps: frozenset[str]) -> int:
    """How many of a floor's counted members these apps contribute."""
    total = 0
    for entry in registry_members(rule, basis):
        if registry_entry_app(entry) in apps:
            total += (
                sum(len(cols) for cols in (entry.get("lookup_columns") or {}).values())
                if basis == "lookup_column_members"
                else 1
            )
    return total


def derived_floor(
    rule: dict,
    key: str,
    recorded: int,
    disabled: frozenset[str],
    *,
    absent_tree: bool = False,
) -> int:
    """A registry-fed floor, lowered by exactly what this run's absent apps contributed.

    A floor with no declared basis, an `opaque` one, or one counted off the
    registry rows themselves is returned unchanged — `quality/gate.py` is where
    a MISSING declaration becomes a refusal, so that a reader meets it once, in
    the place that can name the registry.

    `absent_tree` is the second, larger world subtraction and it is total: a
    rule whose declared tree is not on this checkout scanned nothing, so every
    floor it carries derives to zero. The alternative — holding the recorded
    number over a tree that is not there — turns "this product has no frontend"
    into UNBOUND on every run, which is a broken gate reported for a legal
    shape. The counts fall; the verdict does not.
    """
    if absent_tree:
        return 0
    basis = str((rule.get("registry_floors") or {}).get(key, ""))
    if basis not in LOWERING_BASES:
        return recorded
    return max(0, recorded - registry_contribution(rule, basis, disabled))


# --- scope kinds: which language a rule is written about -------------------------
#
# THE SECOND AXIS THIS MODULE HAD TO GROW. Everything above answers *which apps
# this run holds*; a rule about a language that is not Python needs the sibling
# fact — *which TREES this run holds, and what a valve looks like in them*. Both
# are worlds, both are read off declarations rather than typed here, and both
# lower counts without ever moving a verdict.
#
# A scope kind is three facts and no more: the ROOTS its rules are about, the
# SUFFIXES that belong to it, and the COMMENT token a valve is written with.
# `quality/rules.yaml` declares them under `scope_kinds:`; the engine's override
# walk and its runner invocations both read them, which is what keeps
# "the roots this rule scans" and "the roots this rule's valves are found in"
# from being two lists that can disagree.

#: The kind a rule belongs to when it declares none — the tree's first language,
#: and the one every rule was written about before there was a second.
DEFAULT_KIND = "py"


def scope_kind(rule: dict, kinds: dict) -> dict:
    """The kind declaration a rule runs in.

    A rule names its kind by key. A SYNTHETIC rule — the ones the engine's own
    self-test builds to prove the seam can fail — may carry the declaration
    inline instead, because a probe that had to add a row to `rules.yaml` in
    order to be run would be a probe that changed the population it is
    measuring.
    """
    declared = rule.get("kind") or DEFAULT_KIND
    if isinstance(declared, dict):
        return declared
    if isinstance(declared, list):
        # A RULE ABOUT MORE THAN ONE LANGUAGE names each kind, and runs in their
        # UNION: every root and suffix either names, the skip-dirs of both. The
        # comment token stays per FILE (`kind_of_path`), which is why a union
        # needs no token of its own — a valve is read in the syntax of the
        # line it is written on, and the first kind's token is only the default.
        merged: dict = {"roots": [], "suffixes": [], "skip_dirs": []}
        for name in declared:
            one = dict(kinds.get(str(name)) or {})
            for key in ("roots", "suffixes", "skip_dirs"):
                for item in one.get(key) or []:
                    if item not in merged[key]:
                        merged[key].append(item)
            merged.setdefault("comment", one.get("comment"))
        return merged
    return dict(kinds.get(str(declared)) or {})


def kind_roots(rule: dict, kinds: dict) -> list[str]:
    """The roots a rule's runner may report about, and its valves are found in."""
    return [str(r) for r in (scope_kind(rule, kinds).get("roots") or [])]


def kind_of_path(rel_path: str, kinds: dict) -> dict:
    """The kind a file belongs to, by suffix — for reading a valve out of it.

    Resolved from the FILE rather than from the rule on purpose. A valve is
    written by whoever owns the line, in the comment syntax that line's language
    has, and a rule that one day reports across two languages must find both
    without either becoming a special case. A suffix no kind claims falls back
    to the default, which is what every path did before kinds existed.
    """
    suffix = Path(str(rel_path)).suffix
    for kind in kinds.values():
        if suffix in [str(s) for s in (kind.get("suffixes") or [])]:
            return dict(kind)
    return dict(kinds.get(DEFAULT_KIND) or {})


def comment_token(kind: dict) -> str:
    """The line-comment token a valve is written with in this kind."""
    return str(kind.get("comment") or "#")


def decorator_names(node: ast.AST) -> set[str]:
    """The last name of every decorator on a definition: `@service`, `@x.service()` → `service`."""
    names: set[str] = set()
    for decorator in getattr(node, "decorator_list", []):
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, ast.Attribute):
            names.add(target.attr)
    return names


class Valve(NamedTuple):
    """A valve marker found where a reader looks: its reason, whether it holds, its trigger."""

    reason: str
    holds: bool
    until: str = ""


#: The trigger tail every valve token shares: `<reason> — until <date or sentence>`.
_UNTIL = re.compile(r"\s—\s+until\s+(?P<trigger>\S.*?)\s*$")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def valve_trigger(reason: str) -> str:
    """The `— until <trigger>` tail of a valve's reason, or `""`; the one parser, every token."""
    found = _UNTIL.search(reason)
    return found.group("trigger") if found else ""


def trigger_is_past(trigger: str, today: str) -> bool:
    """Whether a trigger is a `YYYY-MM-DD` date before `today` (also `YYYY-MM-DD`)."""
    return bool(_DATE.fullmatch(trigger)) and trigger < today


def opens_comment(text: str, start: int, comment: str) -> bool:
    """Whether the marker at `start` sits in this line's comment, not inside a string.

    The line either IS a comment (nothing but space before the token), or the
    token trails code with every quote before it closed — a `"# reach: …"`
    inside a string literal is prose spelling a marker, never the marker.
    """
    before = text[:start]
    if not before.strip():
        return True
    quote: str | None = None
    index = 0
    while index < len(before):
        char = before[index]
        if char == "\\":
            index += 2
            continue
        if quote is None and char in "\"'`":
            quote = char
        elif char == quote:
            quote = None
        index += 1
    return quote is None


@road("valve_reason", example="quality/checks/rule_54.py::_function_valve")
def comment_reason(
    lines: list[str],
    line: int,
    pattern: re.Pattern[str],
    *,
    comment: str = "#",
    floor: int = MIN_REASON,
) -> Valve | None:
    """The valve a marker claims at this line, or None: one reader, one floor.

    The marker counts on the flagged line itself or in the CONTIGUOUS comment
    block directly above it — never further away, so a valve cannot drift onto
    code nobody thought about — and only where it OPENS A COMMENT: prose that
    spells a marker (a docstring, a string literal) is a phantom registration,
    the class `checks.py::_function_valve` was the first reader to refuse.
    `pattern`'s first group is the reason; `comment` is the file's line-comment
    token (`comment_token` of its kind); `floor` is `quality.reason_floor`'s
    one number, and a reason under it is a valve that does not hold — its own
    finding wherever a reader reports one.
    """
    if not lines or line < 1 or line > len(lines):
        return None
    index = line - 1
    while index >= 0:
        text = lines[index]
        if index < line - 1 and not text.strip().startswith(comment):
            return None
        found = valve_on_line(text, pattern, comment=comment, floor=floor)
        if found is not None:
            return found
        index -= 1
    return None


def valve_on_line(
    text: str, pattern: re.Pattern[str], *, comment: str = "#", floor: int = MIN_REASON
) -> Valve | None:
    """The valve this one line writes, or None: a marker that opens a comment on it.

    `comment_reason`'s per-line half, and the census's whole question — the
    standing section counts the lines this answers for, so a line the reader
    would not honour is never counted as standing.
    """
    at = text.find(comment)
    while at >= 0:
        match = pattern.match(text, at)
        if match and opens_comment(text, at, comment):
            reason = (match.group(1) or "").strip()
            return Valve(reason, len(reason) >= floor, valve_trigger(reason))
        at = text.find(comment, at + 1)
    return None


def kind_skip_dirs(kind: dict) -> frozenset[str]:
    """Directory names this kind's walk skips — never descended, by either half.

    ONE declaration read by BOTH the engine's override walk (`quality/gate.py`'s
    `kind_files`/`all_overrides`) and every kind's runner subprocess
    (`quality/runners/_kindscope.py` mirrors this over the identical six lines
    of `quality/rules.yaml`, for a process that must not import Django's world
    just to learn a skip-dir list). The defect this closes: the `js` kind's own
    runner once carried its own `SKIP_DIRS` literal while the engine's walk knew
    only `__pycache__` — two lists that could disagree, and did the moment a
    12k-file `node_modules` showed up on one side and not the other.
    """
    return frozenset(str(d) for d in (kind.get("skip_dirs") or []))


# --- needs_tree: the tri-state a language-less checkout has to survive -----------


def needs_tree(rule: dict, kinds: dict) -> str | None:
    """The tree whose absence makes this rule's live scan a printed skip.

    Declared on the rule, or inherited from its kind when every rule of that
    kind is about the same tree. `None` means the rule is about a tree the
    template always has, which is every rule that existed before this key did.
    """
    declared = rule.get("needs_tree") or scope_kind(rule, kinds).get("needs_tree")
    return str(declared) if declared else None


def tree_verdict(root: Path, rule: dict, kinds: dict) -> tuple[str, str]:
    """(`run` | `skip` | `broken`, the sentence that says why) for one rule.

    THE THREE CELLS, and the argument for each:

    * **tree absent** -> `skip`. A template that ships no frontend is the
      steady state, not a defect, and a rule about a tree nobody has must not
      cost that product a red gate forever. The sentence is returned rather
      than swallowed because A SKIP THAT PRINTS NOTHING IS INDISTINGUISHABLE
      FROM A PASS — the printed line is the whole difference between a rule
      that legally looked at nothing and a rule that quietly stopped working.
    * **tree present, toolchain absent** -> `broken`. There IS something to
      look at and nothing looked. That is could-not-look, which outranks a
      pass, and it is the cell that makes the first one safe: skipping is only
      honest while there is genuinely nothing there.
    * **both present** -> `run`.

    The fourth cell — tree absent, toolchain installed — is a `skip` too, and
    deliberately so: the tree is what decides whether there is a subject, and a
    box that happens to have the interpreter installed has not thereby acquired
    one.
    """
    wanted = needs_tree(rule, kinds)
    if wanted is None:
        return "run", ""
    if not (root / wanted).exists():
        return (
            "skip",
            f"{wanted}/ is not on this tree (needs_tree: {wanted}), so the live scan looked "
            "at nothing and every floor this rule carries derives to 0 — counts fall, the "
            "verdict does not",
        )
    argv = [str(a) for a in ((rule.get("runner") or {}).get("argv") or [])]
    if not argv:
        return "run", ""
    from quality.check_v1 import RunnerRefused, resolve_runner

    try:
        resolve_runner(root, argv)
    except RunnerRefused as exc:
        return (
            "broken",
            f"{wanted}/ IS on this tree and its instrument is not: {exc.detail}. A tree with "
            "a subject and no instrument is could-not-look, never a clean scan",
        )
    return "run", ""


# --- the one fixed point ------------------------------------------------------


def fixed_point(grow: Callable[[], bool]) -> None:
    """Call `grow` until a pass adds nothing — the engine's one fixed-point loop.

    Every derivation that feeds itself (a class whose base is a model is a
    model; a helper that returns a bound name binds a name; a function that
    calls the finish seam is the finish seam) walks to the same stop: a pass
    that changed nothing. `grow` answers whether its pass added anything.
    """
    while grow():
        pass


def reaching(edges: Mapping[str, Iterable[str]], seeds: Iterable[str]) -> set[str]:
    """The seeds, and every name whose edges reach one of them, transitively.

    `edges` maps a name to the names it points at (a class to its bases, a
    function to the names it calls); a name joins once any of its edges is
    already in the answer. The seeds stay in the answer — a caller that wants
    only what reached them discards them.
    """
    reached = set(seeds)
    pending = {name: set(targets) for name, targets in edges.items()}

    def grow() -> bool:
        joined = {name for name, targets in pending.items() if targets & reached}
        for name in joined:
            del pending[name]
        reached.update(joined)
        return bool(joined)

    fixed_point(grow)
    return reached


# --- the one one-way number ---------------------------------------------------
#
# ADR gate-6, written once. A ratchet, a floor, a budget ceiling, a self-test
# population, the residence backlog, the drawers leg's ceiling and the memo's
# keep are the same object: a number somebody RECORDED, a number this run
# MEASURED, the file the recorded one is written in, and the direction it may
# move by itself — none. Past it is the caller's verdict (a ratchet's findings
# fail, a floor is unbound, a population is short); short of it is ROOM, and
# room is one sentence in one grammar, ending in the line a human pastes.


@dataclass(frozen=True)
class Bound:
    """One one-way number: what was recorded, what this run measured, where it is written.

    `direction` is `ceiling` (the measurement may not rise past the record —
    ratchets, budgets, the residence backlog, the drawers leg's seconds) or
    `floor` (it may not fall under it — scope floors, self-test populations,
    the seam's and the engine legs' own). `home` is the file and the key the
    number is written under; `klass` is its name there, the key of the paste
    line; `subject` is how a line names it.
    """

    direction: str
    recorded: int
    measured: int
    home: str
    klass: str
    subject: str = ""
    word: str = ""

    def __post_init__(self) -> None:
        if self.direction not in ("ceiling", "floor"):
            raise ValueError(f"a Bound is a ceiling or a floor, not {self.direction!r}")

    @property
    def breached(self) -> bool:
        """Past the record in the direction the number may not move."""
        if self.direction == "ceiling":
            return self.measured > self.recorded
        return self.measured < self.recorded

    @property
    def room(self) -> bool:
        """Short of the record in the direction a human may move it."""
        if self.direction == "ceiling":
            return self.measured < self.recorded
        return self.measured > self.recorded

    @property
    def name(self) -> str:
        return self.subject or self.klass

    @property
    def called(self) -> str:
        return self.word or self.direction

    def breach_clause(self) -> str:
        """The one sentence for a number past its record; the caller says what it costs."""
        where = "past" if self.direction == "ceiling" else "under"
        moves = (
            "may shrink and never grow"
            if self.direction == "ceiling"
            else "may rise and never fall"
        )
        return (
            f"{self.name} is at {self.measured}, {where} its recorded {self.called} "
            f"{self.recorded} in {self.home} — a one-way number {moves} by itself"
        )


def room_note(bound: Bound) -> str | None:
    """THE ONE NOTE: a number short of its record says so, and hands over the line to paste.

    `None` when there is no room. The sentence ends at the colon and the paste
    line follows on its own line, two spaces in — the shape
    `scripts/budget_notes.sh` reads, which is why there is one shape.
    """
    if not bound.room:
        return None
    relation = "below" if bound.direction == "ceiling" else "above"
    number = "lower" if bound.direction == "ceiling" else "higher"
    return (
        f"{bound.name} measured {bound.measured}, {relation} its {bound.called} "
        f"{bound.recorded} ({bound.home}) — a human may commit the {number} number:\n"
        f"  {bound.klass}: {bound.measured}"
    )


def unmeasured_note(*, rid: str, klass: str, app: str, count: int, stamp: str) -> str:
    """A class with NO record is not a class at zero (ADR gate-6) — and the line says so once.

    The one place the engine writes the unmeasured sentence: an app outside the
    partition has a ceiling of nothing, which is unreadable rather than clean;
    the finding IS the recording, made once, in the product's drawer, and after
    it the class is an ordinary `Bound` that moves down only.
    """
    return (
        f"class {klass!r} has NEVER BEEN MEASURED — apps/{app} is outside the partition "
        f"(quality/partition.yaml `platform_apps`), so it is an app this template did not "
        f"ship, and no `ratchets:` entry on rule {rid} names this class. An absent entry is "
        f"a ceiling of zero, which is the right answer for a template app and an unreadable "
        f"one for yours: green-because-unrecorded is not a pass (quality/budgets.yaml), so "
        f"this is a violation and not a note. RECORD IT — in quality/local/rules.yaml, YOUR "
        f'drawer, under its top-level `ratchets:`, under `"{rid}":`, paste:  '
        f"{klass}: {count}  # recorded-at {stamp} [fold]  — the drawer is where a "
        f"product's counts live, because quality/rules.yaml is template-owned and a fold "
        f"overwrites it; the recording is the "
        f"ONE time a number here may arrive from nothing, it belongs to the fold that "
        f"brought the app in, and after it the class moves DOWN only, by a person's hand, "
        f"in a diff a reviewer reads (ADR gate-6). The whole class follows:"
    )


#: Where every budget ceiling is written.
BUDGETS_FILE = "quality/budgets.yaml"


def read_budgets(root: Path) -> dict:
    """`quality/budgets.yaml`, parsed — the one reader of the budget ceilings."""
    import yaml

    path = root / BUDGETS_FILE
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def budget_ceiling(root: Path, section: str, key: str) -> int | None:
    """One recorded ceiling, or None when nobody recorded it."""
    value = (read_budgets(root).get(section) or {}).get(key)
    return None if value is None else int(value)


# --- the tree, the files and the classes, read once ---------------------------

#: Directory parts never walked. Tests are proof, not product; migrations are
#: rule 22's own subject and get their own walker; fixtures are planted wrongness.
SKIP_PARTS: frozenset[str] = frozenset({"__pycache__", "migrations", "tests", "canary", "negative"})


def read_text(path: Path) -> str:
    """A file's text, or '' when it cannot be read — the engine's one reader of a file."""
    try:
        return path.read_text()
    except (OSError, UnicodeDecodeError):
        return ""


_AST_CACHE: dict[tuple[str, float], ast.Module | None] = {}


def parse_python(path: Path) -> ast.Module | None:
    """A module's AST, parsed once per (path, mtime); None when it will not parse."""
    try:
        key = (str(path), path.stat().st_mtime)
    except OSError:
        return None
    if key in _AST_CACHE:
        return _AST_CACHE[key]
    try:
        tree: ast.Module | None = ast.parse(read_text(path))
    except SyntaxError:
        tree = None
    _AST_CACHE[key] = tree
    return tree


def py_files(
    root: Path,
    *subtrees: str,
    named: set[str] | None = None,
    suffixes: tuple[str, ...] = (".py",),
) -> list[Path]:
    """Every file of the suffixes under the subtrees, minus `SKIP_PARTS`; optionally only
    files with the given basenames. DERIVED from the tree, never typed.

    `suffixes` widens the walk to another language with the SAME skip law —
    the road census reads `.sh` through here rather than owning a second walk.
    `SKIP_PARTS` is judged relative to each subtree, so naming `scripts/tests`
    as a subtree reads the drives that `scripts` alone would skip.
    """
    out: list[Path] = []
    for sub in subtrees:
        base = root / sub
        if not base.exists():
            continue
        found: set[Path] = set()
        for suffix in suffixes:
            found.update(base.rglob(f"*{suffix}"))
        for path in sorted(found):
            if SKIP_PARTS & set(path.relative_to(base).parts):
                continue
            if named is not None and path.name not in named:
                if not (SERVICE_MODULE in named and is_service_module(path.relative_to(root))):
                    continue
            out.append(path)
    return out


#: An app's service module by file name; a `services/` package re-exported whole is its other form.
SERVICE_MODULE = "services.py"
_SERVICE_PACKAGE = SERVICE_MODULE.removesuffix(".py")


def is_service_module(rel: str | Path) -> bool:
    """Whether a root-relative path is `…/services.py` or `apps/<x>/services/*.py`."""
    parts = Path(rel).parts
    if not parts:
        return False
    if parts[-1] == SERVICE_MODULE:
        return True
    return (
        len(parts) == 4
        and parts[0] == _APPS_DIR
        and parts[2] == _SERVICE_PACKAGE
        and parts[3].endswith(".py")
    )


@road("service_modules", example="quality/checks/rule_42.py::door_reachability")
def service_modules(root: Path, *, app: str | None = None) -> list[Path]:
    """Every app's service modules (or `app`'s), in path order — the file and the package form."""
    return py_files(root, f"{_APPS_DIR}/{app}" if app else _APPS_DIR, named={SERVICE_MODULE})


def base_names(node: ast.ClassDef) -> list[str]:
    """The last segment of each base's dotted name — `models.Model` -> `Model`.

    A subscripted base (`ScopedManager["Connection"]`) resolves to the
    generic's own name, which is what tells a manager from a model.
    """
    out: list[str] = []
    for base in node.bases:
        cur: ast.expr = base
        while isinstance(cur, ast.Subscript):
            cur = cur.value
        parts: list[str] = []
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        if parts:
            out.append(parts[0])
    return out


_GRAPH_CACHE: dict[tuple[str, tuple[tuple[str, float], ...]], dict[str, frozenset[str]]] = {}


def class_graph(root: Path) -> dict[str, frozenset[str]]:
    """{class name: its base names} for every class under `apps/` — the classes, read once.

    One reading of "which class inherits which", cached on every file's mtime
    like the AST cache under it, so the half-dozen populations that walk the
    inheritance (scoped models, model classes, append-only, archivable, the
    marker mixins, inherited-downward) resolve against ONE graph through
    `reaching` — the one fixed point. Two modules defining one class name are
    the union of both (the loud direction).
    """
    files = py_files(root, "apps")
    facade = sorted((root / "pilecap").glob("*.py")) if (root / "pilecap").is_dir() else []
    stamps: list[tuple[str, float]] = []
    for path in [*files, *facade]:
        try:
            stamps.append((str(path), path.stat().st_mtime))
        except OSError:
            continue
    key = (str(root), tuple(stamps))
    cached = _GRAPH_CACHE.get(key)
    if cached is not None:
        return cached
    aliases: dict[str, str] = {}
    for path in facade:
        tree = parse_python(path)
        module = "pilecap" if path.stem == "__init__" else f"pilecap.{path.stem}"
        for local, (_source, name) in (reexports(tree, module) if tree else {}).items():
            if local != name:
                aliases[local] = name
    graph: dict[str, set[str]] = {}
    for path in files:
        tree = parse_python(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases = base_names(node)
                graph.setdefault(node.name, set()).update(
                    {*bases, *(aliases[b] for b in bases if b in aliases)}
                )
    frozen = {name: frozenset(bases) for name, bases in graph.items()}
    _GRAPH_CACHE.clear()
    _GRAPH_CACHE[key] = frozen
    return frozen


def descendants(root: Path, *seeds: str) -> set[str]:
    """Every class under `apps/` reaching one of `seeds` through its bases, the seeds excluded."""
    return reaching(class_graph(root), set(seeds)) - set(seeds)


# --- the files each kind's walk reads --------------------------------------------
#
# The tree git holds is read once in `quality/tree.py` (standard library only, so
# the partition and a typed test import it without the engine's world).


def _walk_suffixed(
    root: Path, base: Path, suffixes: tuple[str, ...], skip: frozenset[str]
) -> Iterator[str]:
    """Every file under `base` with one of `suffixes`, never descending into a `skip` directory."""
    for here, dirs, files in os.walk(base):
        dirs[:] = [name for name in dirs if name not in skip]
        for name in files:
            if name.endswith(suffixes):
                yield str((Path(here) / name).relative_to(root))


def kind_files(
    root: Path,
    kinds: Mapping[str, dict],
    population: str,
    *,
    measured: Iterable[str] = (),
) -> dict[str, list[str]]:
    """{declared root: the files every kind's walk reads under it} — one loop, two populations.

    `population` is `fs` (the files on the disk, what a live scan and the
    override walk read) or `measured` (the paths of the measured tree — HEAD
    plus the working tree, `.gitignore` honoured — which is also what
    "tracked" means everywhere in this engine since `measured_tree` became the
    one read; hand those paths in as `measured`). A directory root yields its
    files of the kind's suffixes outside the kind's skip dirs; a FILE root is
    its own member whatever its suffix (a suffix filter over one named path is
    a second opinion about a file somebody declared). A root not on this tree
    contributes nothing and says nothing.
    """
    if population not in ("fs", "measured"):
        raise ValueError(f"kind_files reads `fs` or `measured`, not {population!r}")
    present = frozenset(measured) if population == "measured" else frozenset()
    out: dict[str, list[str]] = {}
    for kind in kinds.values():
        skip = kind_skip_dirs(kind)
        suffixes = tuple(str(s) for s in (kind.get("suffixes") or []))
        for declared in (str(r) for r in (kind.get("roots") or [])):
            base = root / declared
            if not base.exists():
                continue
            found = out.setdefault(declared, [])
            if base.is_file():
                if population == "fs" or declared in present:
                    found.append(declared)
                continue
            if population == "fs":
                candidates = _walk_suffixed(root, base, suffixes, skip)
            else:
                candidates = (
                    p for p in present if p.startswith(declared + "/") and p.endswith(suffixes)
                )
            for rel in candidates:
                if skip & set(Path(rel).parts):
                    continue
                found.append(rel)
    return {declared: sorted(set(rels)) for declared, rels in out.items()}
