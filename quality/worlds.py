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

import os
import re
from pathlib import Path

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


def kind_skip_dirs(kind: dict) -> frozenset[str]:
    """Directory names this kind's walk skips — never descended, by either half.

    ONE declaration read by BOTH the engine's override walk (`quality/gate.py`'s
    `_kind_walk`/`all_overrides`) and every kind's runner subprocess
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
