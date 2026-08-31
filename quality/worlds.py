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
"""

from __future__ import annotations

import os
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


def derived_floor(rule: dict, key: str, recorded: int, disabled: frozenset[str]) -> int:
    """A registry-fed floor, lowered by exactly what this run's absent apps contributed.

    A floor with no declared basis, an `opaque` one, or one counted off the
    registry rows themselves is returned unchanged — `quality/gate.py` is where
    a MISSING declaration becomes a refusal, so that a reader meets it once, in
    the place that can name the registry.
    """
    basis = str((rule.get("registry_floors") or {}).get(key, ""))
    if basis not in LOWERING_BASES:
        return recorded
    return max(0, recorded - registry_contribution(rule, basis, disabled))
