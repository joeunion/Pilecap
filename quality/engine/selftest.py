"""Selftest."""

from __future__ import annotations

import ast
import builtins
import contextlib
import datetime
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

from quality import checks as C
from quality import worlds as W
from quality.checks import REGISTRY, CheckResult, Finding
from quality.could_not_look import CouldNotLook
from quality.engine._hub import _DOC, JUDGED_SHAPE_CENSUS, ROOT, engine_leg, engine_number
from quality.reason_floor import MIN_REASON

# --- selftest --------------------------------------------------------------------


def names_planted(finding: Finding, plant_at: str) -> bool:
    parts = Path(plant_at).parts
    suffix = "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
    return plant_at in finding.path or suffix in finding.path or suffix in str(finding)


def selftest_floor(rule: dict) -> dict[str, int]:
    """The canary/negative population this rule RECORDS, as a rising floor.

    . The self-test used to print one aggregate — `117 canary forms fired`
    — and nothing compared it to anything, so "did THIS rule's canaries fire"
    was answered by arithmetic against rules.yaml rather than by reading the
    output. Counting the entries in `rules.yaml` and comparing THAT to what
    fired would not have closed it either: a total derived from the same file
    it is checking cannot notice that file shrinking. A canary deleted from a
    plan takes the expectation with it and the run stays green.

    So the population is RECORDED, in the same grammar as `floors` and the
    budget ceilings (`quality.worlds.Bound`): below it is exit 2 naming the
    rule, above it is the one room note. Growth is free; a plan that quietly
    loses a form is not.
    """
    declared = rule.get("selftest_floor") or {}
    return {
        "canaries": int(declared.get("canaries", 0)),
        "negatives": int(declared.get("negatives", 0)),
    }


def residence_findings(rules: list[dict]) -> list[str]:
    """A rule whose whole canary plan lives in an app a deployment may remove.

    THE SUBJECT. `optional = True` is a promise that a product can ship
    without an app. A rule whose every canary form plants into that app keeps
    its promise and loses its teeth in the same move: the check still runs, the
    self-test still prints a line, and nothing anywhere can demonstrate that the
    rule can fail. That is not a rule with a smaller world; it is a rule an
    environment variable deleted.

    The population is read off the `optional` declarations, never a list here
    (`quality/worlds.py`), and the same ratchet grammar the rest of this engine
    uses holds it: at or below `selftest_residence_backlog` the members are
    NOTES, printed by name every run; one over it and every member is exit 2
    naming the growth. Shrinking never tightens the number by itself.
    """
    template, product = W.split_residence_census(W.residence_census(rules, OPTIONAL_APPS))

    def _line(rid: str, app: str) -> str:
        return (
            f"rule {rid}: every canary form this rule has plants in apps/{app}, which declares "
            f"`optional = True` — a deployment that leaves {app} out leaves this rule unable to "
            "demonstrate a failure at all. Re-home one form into an app the product cannot "
            "remove, or say in the rule why the subject only exists there"
        )

    findings: list[str] = []
    # THE PRODUCT'S OWN CENSUS, AT ZERO (D4, ADR gate-5). The recorded backlog
    # is a measurement of the TEMPLATE's rules that a product folds and never
    # retypes, so a namespaced rule is never counted into it and never hidden
    # by it: the first one is named the moment it is written.
    if product:
        findings.append(
            f"selftest residence: {len(product)} product rule(s) prove nothing without an "
            "optional app, against a backlog of 0 — `selftest_residence_backlog` records the "
            "TEMPLATE's members and a product never retypes it (ADR gate-5). The members "
            "follow:"
        )
        findings.extend(_line(rid, app) for rid, app in product)
    bound = residence_bound(len(template))
    if bound.breached:
        findings.append(
            f"{bound.breach_clause()} — a rule whose whole canary plan lives in an optional "
            "app is a rule an environment variable deletes. The whole census follows:"
        )
        findings.extend(_line(rid, app) for rid, app in template)
    return findings


def residence_bound(measured: int) -> W.Bound:
    """The residence backlog as the one one-way number."""
    return W.Bound(
        direction="ceiling",
        recorded=RESIDENCE_BACKLOG,
        measured=measured,
        home="quality/rules.yaml `selftest_residence_backlog:`",
        klass="selftest_residence_backlog",
        subject="selftest residence (template rules whose whole plan is in an optional app)",
        word="backlog",
    )


#: The append fixtures whose free names neither they nor their plant site bind — one-way.
APPEND_FREE_NAME_BACKLOG: int = int(_DOC.get("selftest_append_free_name_backlog") or 0)


def _bound_names(tree: ast.AST) -> set[str]:
    """Every name a module binds anywhere in it: imports, definitions, targets, arguments."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            names.update(node.names)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            names.add(node.name)
    return names


def append_free_names(fixture: str, site: str) -> list[str] | None:
    """Names the fixture loads that it, its site and the builtins leave unbound; None: can't say."""
    try:
        planted = ast.parse(fixture)
        host = ast.parse(site) if site else ast.Module(body=[], type_ignores=[])
    except SyntaxError:
        return None
    if any(
        isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names)
        for n in ast.walk(host)
    ):
        return None
    loads = {
        n.id for n in ast.walk(planted) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
    }
    known = _bound_names(planted) | _bound_names(host) | set(dir(builtins))
    return sorted(loads - known)


def append_free_name_census(rules: list[dict]) -> list[tuple[str, str, str, list[str]]]:
    """(rule, fixture, site, unbound names) for every `mode: append` Python form that has some."""
    found: list[tuple[str, str, str, list[str]]] = []
    for f in plan_forms(rules):
        if f.form.get("mode") != "append":
            continue
        site_rel = resolve_plant_text(str(f.form["plant_at"]))
        fixture = f.home / str(f.form["fixture"])
        if fixture.suffix != ".py" or not site_rel.endswith(".py") or not fixture.exists():
            continue
        site = ROOT / site_rel
        free = append_free_names(
            fixture.read_text(encoding="utf-8"),
            site.read_text(encoding="utf-8") if site.exists() else "",
        )
        if free:
            found.append((f.rid, f"{f.kind}/{f.form['fixture']}", site_rel, free))
    return found


def append_free_name_bound(measured: int) -> W.Bound:
    """The append fixtures' free-name backlog as the one one-way number."""
    return W.Bound(
        direction="ceiling",
        recorded=APPEND_FREE_NAME_BACKLOG,
        measured=measured,
        home="quality/rules.yaml `selftest_append_free_name_backlog:`",
        klass="selftest_append_free_name_backlog",
        subject="selftest append fixtures leaning on a name their site may stop importing",
        word="backlog",
    )


def append_free_name_leg() -> None:
    """Name every append fixture that leans on its site's imports, and prove the census can fire."""
    census = append_free_name_census(RULES)
    lines = [
        f"    rule {rid} {fixture} → {site}: {', '.join(names)}"
        for rid, fixture, site, names in census
    ]
    bound = append_free_name_bound(len(census))
    if bound.breached:
        RUN.broken.append(
            f"{bound.breach_clause()} — an appended fixture that names a symbol neither it nor "
            "its plant site imports dies the day the site's imports change, and reads as a dead "
            "canary rather than as this. Import the names in the fixture. The census follows:\n"
            + "\n".join(lines)
        )
    else:
        say(
            f"selftest append free names: {len(census)} append fixture(s) lean on their site, "
            f"against a recorded backlog of {APPEND_FREE_NAME_BACKLOG}:"
        )
        for line in lines:
            say(line)
        room = W.room_note(bound)
        if room:
            say("    " + room.replace("\n", "\n    "))
    if append_free_names("def f():\n    return Q()\n", "import os\n") != ["Q"]:
        RUN.broken.append(
            "APPEND FREE-NAME CANARY DEAD — a fixture loading an unbound `Q` read clean"
        )
    if append_free_names("from x import Q\n\n\ndef f():\n    return Q()\n", "") != []:
        RUN.broken.append(
            "APPEND FREE-NAME NEGATIVE FIRED — a fixture importing its own `Q` read free"
        )


def residence_leg() -> None:
    """Run the residence census, and prove the census itself can fail.

    THE MECHANISM'S OWN CANARY, in the shape the budget canary already uses
    below: this leg's subject is `rules.yaml` data rather than the tree, so its
    forms are RULE-SHAPED and asserted directly. Planting a file could not
    exercise it — there is no file whose presence makes a rule's canary plan
    live in one app.
    """
    census, _product = W.split_residence_census(W.residence_census(RULES, OPTIONAL_APPS))
    for line in residence_findings(RULES):
        RUN.broken.append(line)
    if len(census) <= RESIDENCE_BACKLOG:
        # The standing backlog, printed BY NAME on every run: a number nobody
        # can expand into a list is a number nobody can pay down. Said with
        # `say` and not through `notes`, which a self-test run fills with every
        # ratchet note from every planted tree and never prints.
        say(
            f"selftest residence: {len(census)} of {len(RULES)} rules prove nothing without "
            f"an optional app, against a recorded backlog of {RESIDENCE_BACKLOG}:"
        )
        for rid, app in census:
            say(f"    rule {rid}: whole canary plan in apps/{app}")
        room = W.room_note(residence_bound(len(census)))
        if room:
            say("    " + room.replace("\n", "\n    "))

    optional_app = min(OPTIONAL_APPS) if OPTIONAL_APPS else None
    if optional_app is None:
        # No app in this tree declares `optional = True`, so the census has no
        # subject and its canary would be a plant into a world that does not
        # exist. Said out loud rather than skipped silently.
        say(
            "selftest residence: no app declares `optional = True` on this tree, so the "
            "residence census has no subject and its canary did not run."
        )
        return
    canary = {
        "id": "residence-canary",
        "canaries": [
            {"fixture": "a.py", "plant_at": f"apps/{optional_app}/models.py", "mode": "append"},
            {"fixture": "b.py", "plant_at": f"apps/{optional_app}/services.py", "mode": "append"},
        ],
    }
    if not residence_findings([*RULES, canary]):
        RUN.broken.append(
            "RESIDENCE CANARY DEAD — a rule planted 100% in "
            f"apps/{optional_app} did not push the census past its recorded backlog"
        )
    # THE NEGATIVE, and it is rule 35's real plan set rather than an invention:
    # three forms in `core`, `events` and `realtime` and one in `quality/`
    # itself. A census that fired here would be telling every mixed-residence
    # rule to move canaries that are already outside the optional world.
    mixed = {
        "id": "residence-negative",
        "canaries": [
            {"fixture": "a.py", "plant_at": f"apps/{optional_app}/models.py", "mode": "append"},
            {"fixture": "b.py", "plant_at": "apps/core/audit.py", "mode": "append"},
        ],
    }
    if residence_findings([*RULES, mixed]):
        RUN.broken.append(
            "RESIDENCE FALSE-POSITIVE REGRESSION — a rule with one canary form outside "
            f"apps/{optional_app} was counted into the residence census"
        )


def ratchet_headroom(rule: dict, findings: list[Finding]) -> list[str]:
    """Every class this rule records ABOVE the findings the tree holds in it.

    THE HEADROOM CANARY, AND WHY IT IS NOT FREE. A ceiling above the count is a
    backlog paid in the tree with its number left behind; the next finding in
    that class is absorbed under it as a note, so a class that grew reads as a
    class that held (rule 54's `workflows: 1 -> 0`, `quality/rules.yaml`, is the
    measured case). The self-test once caught it by accident — its canaries were
    read through the ratchet and one absorbed read as DEAD — and stopped
    catching it when the self-test learned to read forms raw. So it is asked
    here, of EVERY rule that declares `ratchets:`, through the one merged
    ceiling the engine judges (`rule["ratchets"]`, the drawer's number already
    added — `DRAWER_RATCHET_PARTS` says whose half is whose), never of one rule
    by name. `findings` are the rule's raw findings on the unplanted tree.
    """
    rid = str(rule["id"])
    have: dict[str, int] = {}
    for finding in findings:
        have[str(finding.klass)] = have.get(str(finding.klass), 0) + int(
            getattr(finding, "weight", 1)
        )
    out: list[str] = []
    for klass, allowed in sorted((rule.get("ratchets") or {}).items()):
        name = str(klass)
        recorded = int(allowed)
        count = have.get(name, 0)
        if recorded <= count:
            continue
        parts = DRAWER_RATCHET_PARTS.get((rid, name))
        split = f" (template {parts[0]} + drawer {parts[1]})" if parts else ""
        out.append(
            f"rule {rid} ratchet: class {name!r} is recorded at {recorded}{split} and this tree "
            f"holds {count} — headroom: the next {recorded - count} finding(s) in the class "
            "would be absorbed as notes, so a class that grew reads as one that held. Lower "
            f"it to {count} in {ratchet_home(rid, name)} (the live scan's own note names the "
            "number)"
        )
    return out


def headroom_not_judged(shape: str, disabled: frozenset[str]) -> str:
    """Why the headroom reader judges nothing on this run — '' on the template's own shape.

    THE RECORDED ROWS ARE THE TEMPLATE'S, SO ONLY THE TEMPLATE'S TREE CAN BE
    HELD TO THEM. A consumer's clone (a base declared through the `template`
    remote, `scripts/local/template-base` or `DJB_TEMPLATE_BASE`) and a world
    (`DJB_DISABLED_APPS`) both carry the template's numbers over a tree that is
    not the one they were measured on: a product that paid a class down, or a
    world whose app is gone, holds fewer findings than the template recorded,
    and reading that as headroom would red the product's self-test for the
    template's arithmetic. A template row above a product's count is the fold's
    business, and the live scan's own note already names the number. `shape` is
    `judged_shape()`'s sentence, read once at the self-test's head; a shape the
    census could not give is the caller's could-not-look, never a skip.
    """
    why: list[str] = []
    if not shape.startswith("none declared"):
        why.append(f"a template base is declared — {shape}")
    if disabled:
        why.append(f"a world (DJB_DISABLED_APPS names {', '.join(sorted(disabled))})")
    return " and ".join(why)


def headroom_judgement(
    rule: dict, findings: list[Finding], *, shape: str, disabled: frozenset[str]
) -> tuple[list[str], str]:
    """(the classes named as headroom, why nothing was judged) — the two pieces the tree loop uses.

    The forged forms ask THIS, so a shaped run's silence is proven through the
    same decision the tree's own loop takes, not asserted beside it.
    """
    skip = headroom_not_judged(shape, disabled)
    if skip:
        return [], skip
    return ratchet_headroom(rule, findings), ""


def member_floor_leg() -> None:
    """The member floors, forged in a scratch tree and judged by the shipped reader (ADR gate-6)."""
    fired = 0
    silent = 0
    by_rule = member_rules(RULES)
    if "91" not in by_rule:
        RUN.broken.append("MEMBER-FLOOR LEG COULD NOT RUN — rule 91 declares no `member_classes:`")
        return
    declared = {
        "acme_floors": '{"91.docstring-tail": 2}',
        "acme_bare": None,
        "acme_wrong": '{"91.no-such-class": 1}',
        "acme_empty": "{}",
    }
    with tempfile.TemporaryDirectory(prefix="djb-floors-") as scratch:
        root = Path(scratch)
        (root / "quality").mkdir()
        (root / C.MEMBER_FLOORS_FILE).write_text("{}\n")
        for label, floors in declared.items():
            app = root / "apps" / label
            app.mkdir(parents=True)
            line = f"    ratchet_floors: ClassVar[dict[str, int]] = {floors}\n" if floors else ""
            (app / "apps.py").write_text(
                "from typing import ClassVar\n\nfrom django.apps import AppConfig\n\n\n"
                f'class AcmeConfig(AppConfig):\n    name = "apps.{label}"\n{line}'
            )
        floors, problems = C.read_member_floors(root, by_rule, set(declared))
    text = "\n".join(problems)
    for what, needle in (
        (
            "a template app with no declaration",
            "apps/acme_bare/apps.py declares no `ratchet_floors`",
        ),
        (
            "a key naming no class of its rule",
            "'acme_wrong.no-such-class' is not a class of rule 91",
        ),
    ):
        if needle in text:
            fired += 1
        else:
            RUN.broken.append(f"MEMBER-FLOOR CANARY DEAD — {what} read as no problem: {problems!r}")
    for what, label in (("`{}`", "acme_empty"), ("a valid key", "acme_floors")):
        if f"apps/{label}/" in text:
            RUN.broken.append(f"MEMBER-FLOOR FALSE POSITIVE — {what} was refused: {problems!r}")
        else:
            silent += 1
    found = {(f.rule, f.klass): f for f in floors}
    floor = found.get(("91", "acme_floors.docstring-tail"))
    if (
        floor is None
        or floor.count != 2
        or not floor.source.startswith("apps/acme_floors/apps.py:")
    ):
        RUN.broken.append(
            f"MEMBER-FLOOR CANARY DEAD — the declared floor did not read back: {floors!r}"
        )
        return
    rule = {"id": "91", "member_classes": by_rule["91"], "ratchets": {floor.klass: floor.count}}
    key = ("91", floor.klass)
    before = len(RUN.notes)
    MEMBER_FLOOR_SOURCES[key] = floor.source

    def _forged(n: int, klass: str = floor.klass) -> list[Finding]:
        return [Finding("apps/acme_floors/models.py", 3, f"{n} forged lines", klass, n)]

    try:
        over = [str(f.msg) for f in apply_ratchets(rule, _forged(3)) if f.line == 0]
        under_out = apply_ratchets(rule, _forged(1))
        under = "\n".join(RUN.notes[before:])
        del RUN.notes[before:]
        level_out = apply_ratchets(rule, _forged(2))
        level = "\n".join(RUN.notes[before:])
        unrecorded = apply_ratchets(rule, _forged(4, "acme_floors.block-tail"))
    finally:
        del RUN.notes[before:]
        MEMBER_FLOOR_SOURCES.pop(key, None)
    if over and "apps/acme_floors/apps.py" in over[0] and floor.klass in over[0]:
        fired += 1
    else:
        RUN.broken.append(f"MEMBER-FLOOR CANARY DEAD — a class over its floor: {over!r}")
    if not under_out and "apps/acme_floors/apps.py" in under and '"91.docstring-tail": 1' in under:
        fired += 1
    else:
        RUN.broken.append(f"MEMBER-FLOOR CANARY DEAD — a class under its floor: {under!r}")
    refused = "(`inflow: refused`) — apps/acme_floors is judged at zero"
    if any(refused in str(f.msg) and "'acme_floors.block-tail'" in str(f.msg) for f in unrecorded):
        fired += 1
    else:
        RUN.broken.append(
            "MEMBER-FLOOR CANARY DEAD — an unrecorded product class: "
            f"{[str(f) for f in unrecorded]!r}"
        )
    if level_out or "a human may commit" in level:
        RUN.broken.append(
            f"MEMBER-FLOOR FALSE POSITIVE — a class at its floor: {level_out!r} {level!r}"
        )
    else:
        silent += 1
    say(
        f"member-floor census: {fired} of {engine_number('floors', 'canaries')} canary forms "
        "fired · "
        f"{silent} of {engine_number('floors', 'negatives')} negatives stayed silent (a floor is "
        "read from the app's own declaration; a template app without one is exit 2)"
    )
    engine_leg("floors", fired=fired, silent=silent)


def census_leg() -> None:
    """The census, forged: each canary moves one counter alone; a reasoned valve is declared."""
    fired = 0
    silent = 0
    today = datetime.date.today().isoformat()

    def row(token: str, reason: str) -> tuple[str, str, int, str]:
        pattern = re.compile(re.escape("#") + rf"\s*{re.escape(token)}:\s*(.*)$")
        valve = W.valve_on_line(f"    # {token}: {reason}", pattern)
        if valve is None:
            raise AssertionError(f"the valve reader read no {token} valve")
        return (token, "apps/zzz_canary/services.py", 1, valve.reason)

    def census(rows: list, rules: list | None = None, held: dict | None = None) -> BacklogCensus:
        return backlog_census(rows, rules=rules or [], held=held or {}, today=today)

    reason = "the vendor's client holds this until it ships the replacement"
    canaries = (
        ("ratchet", census([], [{"id": "x1"}], {"x1": {"k": (3, 3)}}), 3),
        ("dated", census([row("authz", f"{reason} — until 2001-01-01")]), 1),
        ("dated", census([row("door", f"{reason} — until 2001-01-01")]), 1),
        # coordinate: the canary's subject is a queue-row id planted in a valve's reason
        ("coordinate", census([row("reach", f"{reason}, booked as N1234")]), 1),
        ("memo", census([], [{"id": "x2", "memo": {"no": "declining pending evidence"}}]), 1),
        ("rerecord", census([], [{"id": "x3", "frozen": ["k"], "ratchets": {"k": 0}}]), 1),
    )
    counters = ("ratchet", "dated", "coordinate", "memo", "rerecord")
    for counter, got, want in canaries:
        others = [c for c in counters if c != counter and getattr(got, c)]
        if getattr(got, counter) == want and got.backlog == want and not others:
            fired += 1
        else:
            RUN.broken.append(
                f"CENSUS CANARY DEAD — a forged {counter} item moved {got} rather than "
                f"{counter} alone to {want}"
            )
    negatives = (
        census([row("authz", f"{reason} — until the vendor ships v2")]),
        census([row("authz", f"{reason} — until 2999-01-01")]),
    )
    for got in negatives:
        if got.declared == 1 and got.backlog == 0:
            silent += 1
        else:
            RUN.broken.append(
                f"CENSUS FALSE POSITIVE — a reasoned valve with a live trigger counted {got}"
            )
    say(
        f"backlog census: {fired} of {engine_number('census', 'canaries')} canary forms fired · "
        f"{silent} of {engine_number('census', 'negatives')} negatives stayed silent (each of the "
        "five counters moved alone; a valve whose trigger is an event or a future date is declared)"
    )
    engine_leg("census", fired=fired, silent=silent)


def frozen_leg() -> None:
    """`frozen:`, forged: rises, a returned line, a bad stamp, a drawer lift, a zero-state paste."""
    fired = 0
    silent = 0
    app_text = (
        "from django.apps import AppConfig\n\n\nclass AcmeConfig(AppConfig):\n"
        '    ratchet_floors = {{"89.coordinate": {n}}}\n'
    )
    homes = (
        (
            "quality/rules.yaml",
            "84",
            "hand_url",
            'rules:\n  - id: "84"\n    ratchets:\n      hand_url: {n}\n',
        ),
        (C.MEMBER_FLOORS_FILE, "89", "quality.coordinate", '"89":\n  quality.coordinate: {n}\n'),
        ("apps/acme/apps.py", "89", "acme.coordinate", app_text),
    )

    def judged(home: str, rid: str, klass: str, now_text: str, then_text: str | None) -> str | None:
        now = recorded_number(now_text, home, rid, klass)
        then = recorded_number(then_text, home, rid, klass) if then_text is not None else None
        if now is None:
            raise AssertionError(f"the reader found no {klass} in the forged {home}")
        return frozen_judgement(rid, klass, home, now[0], then[0] if then else None, "HEAD")

    for home, rid, klass, shape in homes:
        why = judged(home, rid, klass, shape.format(n=34), shape.format(n=33))
        if why and klass in why and "34" in why and "33" in why:
            fired += 1
        else:
            RUN.broken.append(
                f"FROZEN CANARY DEAD — {home}: {klass} raised 33 → 34 was not refused ({why!r})"
            )
        if judged(home, rid, klass, shape.format(n=32), shape.format(n=33)) is None:
            silent += 1
        else:
            RUN.broken.append(
                f"FROZEN FALSE POSITIVE — {home}: {klass} lowered 33 → 32 was refused"
            )
    returned = judged(
        "quality/rules.yaml",
        "84",
        "second_road",
        homes[0][3].replace("hand_url", "second_road").format(n=0),
        'rules:\n  - id: "84"\n',
    )
    if returned and "never arrives or returns" in returned:
        fired += 1
    else:
        RUN.broken.append(
            f"FROZEN CANARY DEAD — a frozen line that returned was not refused ({returned!r})"
        )
    try:
        text_at("deadbeef0000", "quality/rules.yaml")
        RUN.broken.append("FROZEN CANARY DEAD — an unreadable `recorded-at` sha read as history")
    except CouldNotLook:
        fired += 1
    rule = RULES_BY_ID["84"]
    before = dict(rule.get("ratchets") or {})
    LOCAL_DOC["ratchets"] = {"84": {"hand_url": 1}}
    try:
        lifted = _merge_local_ratchets()
    finally:
        LOCAL_DOC.pop("ratchets", None)
        rule["ratchets"] = before
    if len(lifted) == 1 and "'hand_url' is frozen" in lifted[0]:
        fired += 1
    else:
        RUN.broken.append(
            f"FROZEN CANARY DEAD — a drawer recording a frozen class was not refused ({lifted!r})"
        )
    member = {
        "id": "89",
        "member_classes": ["coordinate"],
        "frozen": ["coordinate"],
        "ratchets": {},
    }
    findings = [Finding("apps/acme/services.py", 3, "a forged coordinate", "acme.coordinate")]
    out = apply_ratchets(member, findings)
    if out == findings:
        fired += 1
    else:
        RUN.broken.append(
            "FROZEN CANARY DEAD — a finding in a frozen class at zero was not a bare violation "
            f"(a paste line or nothing): {[f.msg for f in out]!r}"
        )
    own = {
        "id": "acme-1",
        "frozen": ["k"],
        "ratchets": {"k": 2},
        "remedies": {"k": "x" * MIN_REASON},
    }
    if not frozen_declaration_problems(own) and is_frozen(own, "k"):
        silent += 1
    else:
        RUN.broken.append(
            "FROZEN FALSE POSITIVE — a drawer rule freezing its own class was refused: "
            f"{frozen_declaration_problems(own)!r}"
        )
    history_fired, history_silent = frozen_history_forms(homes)
    fired += history_fired
    silent += history_silent
    say(
        f"frozen census: {fired} of {engine_number('frozen', 'canaries')} canary forms fired · "
        f"{silent} of {engine_number('frozen', 'negatives')} negatives stayed silent (a rise in "
        "each of three homes, a returned line, an unreadable stamp, a drawer lift and a zero-state "
        "paste line refused; a lowered number in each home and a drawer's own frozen class held; "
        "in scratch repositories, a committed rise in each home, a rise over a fall on local "
        "main only, a shallow trunk and a class leaving `frozen:` refused; a fall, no commit, "
        "HEAD only, two coinciding trunks and a joining class held)"
    )
    engine_leg("frozen", fired=fired, silent=silent)


def frozen_history_forms(homes: tuple[tuple[str, str, str, str], ...]) -> tuple[int, int]:
    """The base forms through real git in scratch repositories: `(fired, silent)`."""
    fired = 0
    silent = 0
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(name, None)

    def git(root: Path, *argv: str) -> None:
        subprocess.run(
            ["git", "-C", str(root), "-c", "user.name=selftest", "-c", "user.email=s@t.invalid"]
            + list(argv),
            env=env,
            capture_output=True,
            check=True,
            timeout=60,
        )

    def commit(root: Path, home: str, text: str, message: str) -> None:
        (root / home).parent.mkdir(parents=True, exist_ok=True)
        (root / home).write_text(text, encoding="utf-8")
        git(root, "add", "--", home)
        git(root, "commit", "-q", "--no-verify", "-m", message)

    def repo(root: Path, home: str, main_text: str, rung_text: str | None) -> Path:
        git(root.parent, "init", "-q", "-b", "main", root.name)
        commit(root, home, main_text, "main")
        if rung_text is not None:
            git(root, "checkout", "-q", "-b", "rung")
            commit(root, home, rung_text, "rung")
        return root

    def tip(root: Path, ref: str) -> str:
        return _git_at(root, "rev-parse", ref).stdout.strip()

    def problems(root: Path, entries: list, lists: dict | None = None) -> list[str]:
        return frozen_problems(root, entries, {} if lists is None else lists)

    with tempfile.TemporaryDirectory(prefix="djb-frozen-base-") as scratch:
        base = Path(scratch)
        try:
            for index, (home, rid, klass, shape) in enumerate(homes):
                root = repo(base / f"raise{index}", home, shape.format(n=33), shape.format(n=34))
                fork = tip(root, "main")[:12]
                got = problems(root, [(rid, klass, home, 34, "HEAD")])
                if len(got) == 1 and klass in got[0] and "34" in got[0] and fork in got[0]:
                    fired += 1
                else:
                    RUN.broken.append(
                        f"FROZEN CANARY DEAD — {home}: {klass} raised 33 → 34 in a commit off main "
                        f"was not refused against the fold base {fork} ({got!r})"
                    )
            home, rid, klass, shape = homes[0]
            root = repo(base / "fall", home, shape.format(n=33), shape.format(n=32))
            if not problems(root, [(rid, klass, home, 32, "HEAD")]):
                silent += 1
            else:
                RUN.broken.append(f"FROZEN FALSE POSITIVE — {klass} lowered 33 → 32 in a commit")
            git(
                base,
                "clone",
                "-q",
                "--depth",
                "1",
                "--branch",
                "rung",
                "file://" + str(base / "raise0"),
                "shallow",
            )
            git(
                base / "shallow",
                "fetch",
                "-q",
                "--depth",
                "1",
                "origin",
                "main:refs/remotes/origin/main",
            )
            got = problems(base / "shallow", [(rid, klass, home, 34, "HEAD")])
            if (
                len(got) == 1
                and got[0].startswith("FROZEN COULD NOT LOOK")
                and "origin/main" in got[0]
            ):
                fired += 1
            else:
                RUN.broken.append(
                    f"FROZEN CANARY DEAD — a shallow clone whose trunk shares no base with HEAD "
                    f"was not could-not-look ({got!r})"
                )
            listed = 'rules:\n  - id: "84"\n    frozen: [{}]\n'
            root = repo(
                base / "leave",
                "quality/rules.yaml",
                listed.format("hand_url, private_twin"),
                listed.format("private_twin"),
            )
            got = problems(root, [], {"84": frozenset({"private_twin"})})
            if len(got) == 1 and "'hand_url'" in got[0] and "never leave" in got[0]:
                fired += 1
            else:
                RUN.broken.append(
                    f"FROZEN CANARY DEAD — hand_url left `frozen:` in a commit ({got!r})"
                )
            joined = frozenset({"hand_url", "private_twin", "a_new_class"})
            if not problems(root, [], {"84": joined}):
                silent += 1
            else:
                RUN.broken.append("FROZEN FALSE POSITIVE — a class joining `frozen:` was refused")
            root = base / "unborn"
            git(base, "init", "-q", "-b", "main", root.name)
            (root / home).parent.mkdir(parents=True, exist_ok=True)
            (root / home).write_text(shape.format(n=34), encoding="utf-8")
            label = frozen_base(root).label
            got = problems(root, [(rid, klass, home, 34, "HEAD")])
            if label == "none (no commit yet)" and not got:
                silent += 1
            else:
                RUN.broken.append(
                    f"FROZEN FALSE POSITIVE — no commit yet read as {label!r}: {got!r}"
                )
            root = repo(base / "alone", home, shape.format(n=33), None)
            label = frozen_base(root).label
            got = problems(root, [(rid, klass, home, 33, "HEAD")])
            if label.endswith("(HEAD only)") and not got:
                silent += 1
            else:
                RUN.broken.append(
                    f"FROZEN FALSE POSITIVE — no trunk ref read as {label!r}: {got!r}"
                )
            root = repo(base / "unpushed", home, shape.format(n=33), None)
            git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
            commit(root, home, shape.format(n=32), "main lowers, unpushed")
            lowered = tip(root, "main")[:12]
            git(root, "checkout", "-q", "-b", "rung")
            commit(root, home, shape.format(n=33), "rung")
            got = problems(root, [(rid, klass, home, 33, "HEAD")])
            if len(got) == 1 and f"above the 32 it held at the fold base {lowered}" in got[0]:
                fired += 1
            else:
                RUN.broken.append(
                    f"FROZEN CANARY DEAD — {klass} lowered to 32 on local main and raised back to "
                    f"33 off it was not refused against local main's base {lowered} ({got!r})"
                )
            root = repo(base / "coincide", home, shape.format(n=33), shape.format(n=32))
            git(root, "update-ref", "refs/remotes/origin/main", "main")
            fork = tip(root, "main")[:7]
            label = frozen_base(root).label
            got = problems(root, [(rid, klass, home, 32, "HEAD")])
            if label == f"{fork} (origin/main, main)" and not got:
                silent += 1
            else:
                RUN.broken.append(
                    f"FROZEN FALSE POSITIVE — two coinciding trunks read as {label!r}: {got!r}"
                )
        except (OSError, subprocess.SubprocessError, CouldNotLook) as error:
            RUN.broken.append(
                f"FROZEN LEG COULD NOT LOOK — a scratch repository would not build ({error})"
            )
    return fired, silent


def ratchet_leg(shape: str) -> None:
    """The UNMEASURED branch, and proof that it fires for one shape only.

    THE SUBJECT IS `rules.yaml` DATA AND A LIST OF FINDINGS, so the forms are
    forged and handed to the shipped function directly — the shape
    `residence_leg` above and `declaration_leg` below already use, and the only
    honest one here: no file on any tree makes a ratchet class unmeasured. What
    makes one unmeasured is an app the partition does not name, and the nearest
    real one does not exist on the template (that is what the template BEING
    the partition means).

    ONE CANARY AND FOUR NEGATIVES, and the negatives are the whole argument:
    the branch must stay silent for a template app (absence IS the measurement
    there), for a class that is not an app at all, for the plant scaffold, and
    for a class the product has already recorded — including at zero, which is
    a measurement somebody made and not an absent one.
    """
    fired = 0
    silent = 0

    def _finding(path: str, klass: str) -> Finding:
        return Finding(path, 12, "a forged finding, planted by the self-test", klass)

    def _rule(ratchets: dict) -> dict:
        return {"id": "54", "ratchets": dict(ratchets)}

    def _headers(rule: dict, findings: list[Finding]) -> list[str]:
        return [
            str(f.msg) for f in apply_ratchets(rule, findings) if f.path == "quality/rules.yaml"
        ]

    if PLATFORM_APPS is None:
        RUN.broken.append(
            "RATCHET LEG COULD NOT RUN — the partition lockfile did not read, so nothing "
            "here can tell a product app from a template one. The line above names it"
        )
        return

    # -- THE CANARY: a class keyed on an app the partition does not name ------
    outsider = "acme"
    if outsider in PLATFORM_APPS:  # pragma: no cover - the template ships no `acme`
        RUN.broken.append(
            "RATCHET CANARY COULD NOT RUN — this tree's partition names an app called "
            f"{outsider!r}, so the canary's outsider is not outside anything"
        )
        return
    hits = [_finding(f"apps/{outsider}/selectors.py", f"{outsider}.read")]
    lines = _headers(_rule({}), hits)
    paste = f"{outsider}.read: 1  # recorded-at {recording_sha()} [fold]"
    wanted = (paste, f"apps/{outsider}", "platform_apps", "NEVER BEEN MEASURED", "ADR gate-6")
    if not lines:
        RUN.broken.append(
            "UNMEASURED-RATCHET CANARY DEAD — a finding in a class keyed on "
            f"apps/{outsider}, which the partition does not name and no ratchet records, "
            "produced no header at all: the product holding it is back at a zero nothing "
            "explains"
        )
    else:
        absent = [w for w in wanted if w not in lines[-1]]
        if absent:
            RUN.broken.append(
                "UNMEASURED-RATCHET CANARY MUTE — the header fired without the part a "
                f"reader acts on: {', '.join(absent)} is not in the line. The line IS the "
                f"remedy, and a header without it is the bare zero it replaced: {lines[-1]}"
            )
        else:
            fired += 1
    # AND THE FINDINGS THEMSELVES STILL FAIL. The recording is a remedy, never
    # an amnesty: a header that arrived INSTEAD of the violations would have
    # turned green-because-unrecorded into green-because-explained.
    if not [f for f in apply_ratchets(_rule({}), hits) if f.path != "quality/rules.yaml"]:
        RUN.broken.append(
            "UNMEASURED-RATCHET CANARY SOFTENED — the unmeasured header replaced the "
            "violations instead of heading them; an unrecorded class is still exit 1 "
            "(quality/budgets.yaml)"
        )

    # -- THE NEGATIVES --------------------------------------------------------
    negatives = (
        (
            "a template app",
            _rule({}),
            [_finding("apps/core/selectors.py", "core.read")],
            "apps/core is inside the partition, where an absent entry IS the measurement — "
            "offering to record one would ask the template to write down its own zeroes",
        ),
        (
            "a class that is not an app",
            _rule({}),
            [_finding("apps/core/policies.py", "nonconforming")],
            "`nonconforming` is a class name, not an app label, and a header naming "
            "apps/nonconforming would send a reader to a directory nobody has",
        ),
        (
            "the plant scaffold",
            _rule({}),
            [_finding(f"apps/{PROBE_APP}/services.py", f"{PROBE_APP}.role-value")],
            f"apps/{PROBE_APP} exists between `Plant.put` and `Plant.restore` and nowhere "
            "else; a recording for it names an app nobody can open",
        ),
        (
            "a class the product recorded at zero",
            _rule({f"{outsider}.read": 0}),
            [_finding(f"apps/{outsider}/selectors.py", f"{outsider}.read")],
            "a recorded 0 is a measurement somebody made; only an ABSENT entry is unmeasured",
        ),
    )
    for what, rule, findings, why in negatives:
        if _headers(rule, findings):
            RUN.broken.append(
                f"UNMEASURED-RATCHET FALSE POSITIVE — {what} was offered a recording line: {why}"
            )
        else:
            silent += 1

    say(
        f"ratchet census: {fired} of {engine_number('ratchet', 'canaries')} canary forms "
        f"fired · {silent} of {engine_number('ratchet', 'negatives')} negatives stayed "
        "silent (a product app's class with no entry says how to record it; a template app, "
        "a non-app class, the plant scaffold and a class already recorded at zero say "
        "nothing)"
    )
    engine_leg("ratchet", fired=fired, silent=silent)

    # -- THE HEADROOM CANARY, forged, then asked of every rule ----------------
    # Forged first, so the reader is proven before its answer is believed: a
    # class recorded above its count is named (the canary); a class at its
    # count, one recorded at zero, and a raised row on a run that is not the
    # template's own shape say nothing (the negatives). Every form goes through
    # `headroom_judgement`, the decision the tree loop below takes.
    head_fired = 0
    head_silent = 0
    template = "none declared (the template's own shape)"
    forged = {"id": "63", "ratchets": {"instrument-missing": 5, "entry-form": 1, "book": 0}}
    forged_findings = [_finding("docs/product/design/patterns.md", "entry-form")]
    lines, _skip = headroom_judgement(forged, forged_findings, shape=template, disabled=frozenset())
    if len(lines) == 1 and "'instrument-missing' is recorded at 5" in lines[0]:
        head_fired += 1
    else:
        RUN.broken.append(
            "HEADROOM CANARY DEAD — a class recorded at 5 over a tree holding 0 was not named "
            f"exactly once (the reader said: {lines!r})"
        )
    remote = "v0.0.0-forged (from the 'template' remote, derived from TEMPLATE_VERSION)"
    for what, rule, findings, on, disabled, says in (
        (
            "a class at its count",
            {"id": "64", "ratchets": {"literal-size": 1}},
            [_finding("frontend/src/zzz.css", "literal-size")],
            template,
            frozenset(),
            "",
        ),
        (
            "a class recorded at zero",
            {"id": "64", "ratchets": {"half-pixel": 0}},
            [],
            template,
            frozenset(),
            "",
        ),
        (
            "a raised row on a consumer's shape (a base declared through the remote)",
            forged,
            forged_findings,
            remote,
            frozenset(),
            remote,
        ),
        (
            "a raised row in a world (DJB_DISABLED_APPS set)",
            forged,
            forged_findings,
            template,
            frozenset({"search"}),
            "DJB_DISABLED_APPS names search",
        ),
    ):
        lines, skip = headroom_judgement(rule, findings, shape=on, disabled=disabled)
        if lines:
            RUN.broken.append(f"HEADROOM FALSE POSITIVE — {what} was named as headroom: {lines!r}")
        elif says and says not in skip:
            RUN.broken.append(
                f"HEADROOM SKIP MUTE — {what} was not judged, and the reason did not name the "
                f"shape ({says!r} is not in {skip!r})"
            )
        else:
            head_silent += 1

    say(
        f"ratchet headroom: {head_fired} of {engine_number('headroom', 'canaries')} canary "
        f"forms fired · {head_silent} of {engine_number('headroom', 'negatives')} "
        "negatives stayed silent (a raised row named on the template's own shape; a row at "
        "its count, one at zero, and a raised row on a consumer's shape or in a world say "
        "nothing)"
    )

    # The tree, every rule that declares a class above zero: its raw findings
    # (overrides applied, no ratchet), read once — ON THE TEMPLATE'S OWN SHAPE
    # ONLY (`headroom_not_judged` says why). Anywhere else the leg says which
    # shape in one line and judges nothing; a shape the census could not give
    # is could-not-look. A rule that could not look says so and is not judged.
    judged = 0
    classes = 0
    not_judged = headroom_not_judged(shape, DISABLED_APPS)
    broken_shape = shape.startswith("could not be read") or "; the census could not look" in shape
    if broken_shape:
        RUN.broken.append(
            f"RATCHET HEADROOM COULD NOT LOOK — the judged shape is {shape}, so nothing can "
            "say whether this tree is the one the recorded rows were measured on"
        )
    elif not_judged:
        say(
            f"ratchet headroom: not judged on this shape — {not_judged}. The recorded rows are "
            "the template's; a template row above a product's count is the fold's business, "
            "and the live scan's own note names the number"
        )
    else:
        for rule in RULES:
            rid = str(rule["id"])
            positive = {
                str(k): int(v) for k, v in (rule.get("ratchets") or {}).items() if int(v) > 0
            }
            if not positive or not rule.get("enabled", True):
                continue
            kept, _targets, skip = run_rule(rule, floors=False, ratchets=False)
            if skip:
                say(f"  ratchet headroom: rule {rid} not judged — {skip}")
                continue
            judged += 1
            measured = dict(rule)
            measured["ratchets"] = positive
            classes += len(positive)
            # A RULE LINE, NOT AN ENFORCEMENT BREAK: a row above its count is a
            # finding about THIS tree's number (exit 1, under `Violations:`
            # with the rule's own trailer); only the reader's own forms dying
            # is enforcement broken.
            for line in ratchet_headroom(measured, kept):
                RUN.violations.append(line)
                violation_rule[line] = rid
    if not not_judged and not broken_shape:
        say(
            f"ratchet headroom: {classes} class(es) recorded above zero across {judged} "
            "rule(s), each judged against its count on this tree (every rule that declares "
            "`ratchets:`, the drawer's number included)"
        )
    engine_leg("headroom", fired=head_fired, silent=head_silent)


@contextlib.contextmanager
def _as_product_tree(namespace: str, through: int) -> Iterator[None]:
    """Hold this process as if `rules.yaml` declared a product namespace.

    The wall's subject is `rules.yaml` DATA — two top-level keys and the id of
    every rule — so its canaries are rule-shaped and asserted directly, exactly
    as the residence census's are above. No file anywhere makes this tree a
    product tree, and a plant that tried would be proving something about a
    checkout nobody has.
    """
    world = world_module()
    was = (world.RULE_ID_NAMESPACE, world.TEMPLATE_IDS_THROUGH)
    cached = dict(_OVERRIDE_RES)
    world.RULE_ID_NAMESPACE, world.TEMPLATE_IDS_THROUGH = namespace, through
    # The valve patterns are compiled FROM the declaration and cached per
    # comment token, so a swapped declaration with a warm cache would test the
    # template's regex and call it the product's.
    _OVERRIDE_RES.clear()
    try:
        yield
    finally:
        world.RULE_ID_NAMESPACE, world.TEMPLATE_IDS_THROUGH = was
        _OVERRIDE_RES.clear()
        _OVERRIDE_RES.update(cached)


def namespace_leg() -> None:
    """The id-grammar wall, and proof that every half of it can fail (ADR gate-5).

    FOUR CANARIES AND FOUR NEGATIVES, and the split is the point: the wall
    refuses three shapes and MUST NOT refuse the two that are legal, because a
    grammar that refused the template's own integers would take the whole rule
    set down and a grammar that refused nothing is the colliding tree this wall
    exists to end.
    """
    # -- the canaries: each of these must be refused ---------------------------
    if id_shape_problem("acme-1") is None:
        RUN.broken.append(
            "NAMESPACE CANARY DEAD — `acme-1` was accepted on a tree that declares no "
            "`rule_id_namespace`; a product id nothing claims must be refused"
        )
    with _as_product_tree("acme", 59):
        for probe, why in (
            ("60", "an integer above the template's recorded high-water"),
            ("other-2", "an id under a namespace this tree did not declare"),
            ("acme_3", "an id that is not `<ns>-<n>` at all"),
        ):
            problem = id_shape_problem(probe)
            if problem is None:
                RUN.broken.append(
                    f"NAMESPACE CANARY DEAD — {probe!r} ({why}) was accepted on a tree "
                    "declaring `rule_id_namespace: acme`"
                )
            elif "acme-<n>" not in problem:
                RUN.broken.append(
                    f"NAMESPACE CANARY MUTE — the refusal of {probe!r} does not name the "
                    f"grammar a reader has to write instead: {problem}"
                )
        # -- the negatives, INSIDE the product world -------------------------
        for legal in ("59", "1", "acme-1", "acme-204"):
            if id_shape_problem(legal) is not None:
                RUN.broken.append(
                    "NAMESPACE FALSE-POSITIVE REGRESSION — the legal id "
                    f"{legal!r} was refused on a tree declaring `rule_id_namespace: acme`"
                )
        if not override_re("#").search("# rule-acme-1: a product's own valve"):
            RUN.broken.append(
                "NAMESPACE CANARY DEAD — `# rule-acme-1:` is not a valve on a tree "
                "declaring `rule_id_namespace: acme`, so a product could not excuse its "
                "own rule anywhere"
            )
    if override_re("#").search("# rule-acme-1: a namespace this tree never claimed"):
        RUN.broken.append(
            "NAMESPACE FALSE-POSITIVE REGRESSION — `# rule-acme-1:` reads as a valve on a "
            "tree that declares no namespace, so a marker naming nothing would suppress"
        )

    # -- THE PRODUCT HALF OF THE RESIDENCE CENSUS (D4, and V-D's rider) -------
    #
    # `residence_findings` splits its census in two and counts the product's
    # members against ZERO — the branch that exists so a namespaced rule is
    # never hidden inside a backlog the template measured. Nothing planted it:
    # the template has no product rules, so on every real run that branch is
    # dead code with nobody watching it. The canary is a forged `acme-1` whose
    # whole canary plan lives in the one optional app, and the negative is the
    # same rule with one form outside it.
    optional_app = min(OPTIONAL_APPS) if OPTIONAL_APPS else None
    if optional_app is None:
        say(
            "rule ids: no app declares `optional = True` on this tree, so the product half "
            "of the residence census has no subject and its canary did not run."
        )
    else:
        whole = {
            "id": "acme-1",
            "canaries": [
                {"fixture": "a.py", "plant_at": f"apps/{optional_app}/models.py", "mode": "append"},
                {
                    "fixture": "b.py",
                    "plant_at": f"apps/{optional_app}/services.py",
                    "mode": "append",
                },
            ],
        }
        lines = residence_findings([*RULES, whole])
        header = [
            line
            for line in lines
            if "1 product rule(s)" in line and "against a backlog of 0" in line
        ]
        named = [line for line in lines if "rule acme-1:" in line and optional_app in line]
        if not header or not named:
            RUN.broken.append(
                "PRODUCT-RESIDENCE CANARY DEAD — a product rule `acme-1` whose whole canary "
                f"plan plants into apps/{optional_app} did not produce the product census's "
                "own line (1 against 0) with the member named. The branch counts a "
                f"product's rules against zero and nothing else watches it: {lines}"
            )
        mixed = {
            "id": "acme-1",
            "canaries": [
                {"fixture": "a.py", "plant_at": f"apps/{optional_app}/models.py", "mode": "append"},
                {"fixture": "b.py", "plant_at": "apps/core/audit.py", "mode": "append"},
            ],
        }
        if [line for line in residence_findings([*RULES, mixed]) if "product rule(s)" in line]:
            RUN.broken.append(
                "PRODUCT-RESIDENCE FALSE-POSITIVE REGRESSION — a product rule with one canary "
                f"form outside apps/{optional_app} was counted into the product census"
            )

    # -- the fixture-directory census, against a tree it builds itself ---------
    scratch = Path(tempfile.mkdtemp(prefix="djb-nsdir-"))
    try:
        (scratch / "canary" / "1").mkdir(parents=True)
        (scratch / "canary" / "acme-1").mkdir()
        (scratch / "canary" / "other-9").mkdir()
        bases = (("canary", scratch / "canary"),)
        loud = fixture_dir_findings(bases, claimed={"1", "acme-1"}, namespace="acme")
        if not any("other-9" in line and "'other'" in line for line in loud):
            RUN.broken.append(
                "NAMESPACE CANARY DEAD — a fixture directory under a namespace the tree has "
                f"not claimed did not name it: {loud}"
            )
        quiet = fixture_dir_findings(bases, claimed={"1", "acme-1", "other-9"}, namespace="acme")
        if quiet:
            RUN.broken.append(
                "NAMESPACE FALSE-POSITIVE REGRESSION — fixture directories every rule claims "
                f"were reported anyway: {quiet}"
            )
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    world = world_module()
    if world.RULE_ID_NAMESPACE is None:
        highest = max((int(r["id"]) for r in RULES if is_template_id(str(r["id"]))), default=0)
        say(
            f"rule ids: template mode — {len(RULES)} rules, integers minted through {highest}. "
            f"A product folding this release records `rule_id_namespace: <ns>` and "
            f"`template_rule_ids_through: {highest}` (ADR gate-5)."
        )
    else:
        say(
            f"rule ids: product mode — namespace {world.RULE_ID_NAMESPACE!r}, the template's "
            f"integers recorded through {world.TEMPLATE_IDS_THROUGH}."
        )


# --- RULE 60's THIRD CLASS: one plant per drawer, through the drawer's own case
#
# WHAT CLASSES (a) AND (b) CANNOT SEE. Class (a) asks whether a product edited
# a template-owned file; class (b) asks whether every drawer this tree opens is
# written down with its reader and its case. Both are text. Neither can tell a
# drawer that WORKS from a drawer whose reader opens the directory, reads the
# members and throws them away — and that failure is silent in the worst
# direction: the product drops its leg in, the gate says nothing, and the leg
# never runs.
#
# SO THIS ONE RUNS THEM. Per live row of the `drawers` table, the case that row
# names is invoked — `<drive> --case <case>` for a shell drive, the node id for
# the one pytest drawer — and the case is the assertion. THAT IS THE WHOLE
# DESIGN: the case already plants one item and already asserts the reader ran
# it and named it, so a census that grepped the transcript for `local:<name>`
# would be a second, weaker opinion about a property the case owns. One reader
# per drawer, one case per drawer, and this leg is neither.
#
# WHY IT IS HERE AND NOT IN THE RULE'S CHECK. The cases cost tens of seconds;
# rule 60's check runs on every `--fast`, whose whole target is under a minute.
# The self-test is where the engine already pays for proof, and it is the one
# place that runs BEFORE the drives it invokes (`scripts/check.sh`'s selftest
# leg: "the engine's own `--selftest` runs first"), so a case cannot collide
# with the same drive running as a registered member beside it — two of them
# would refuse outright if it did (`test_gate_explain` will not overwrite an
# existing `quality/local/`, `test_sweep`'s scratch identity is derived per
# checkout).
#
# EXIT SEMANTICS, and they are the tree's and not the plan's letter. A case
# that RAN AND FAILED is a drawer whose reader did not take the plant: it is
# reported here, and `broken` makes it exit 2, because a drawer nobody can
# extend means the extension convention is not enforced for it — which is the
# definition of enforcement broken. A case that could not be RUN at all — no
# such drive, no such case, the drive itself exit 2 — is the same verdict by a
# different road and says which road it was.


def drawer_case_problem(row: C.DrawerRow, timeout: int = 300) -> tuple[str, str]:
    """Run one row's case. `("", transcript)` when the drawer held.

    The victim is the case's own: every one of them builds its plant in a
    scratch directory or a clone and tears it down, which is the condition of
    being a registered drive here. This function creates nothing.
    """
    drive, _, case = row.case.partition("::")
    target = ROOT / drive
    if not case or not target.is_file():
        return (f"the case {row.case!r} is not a case in this tree", "")
    if drive.endswith(".py"):
        argv = ["uv", "run", "pytest", f"{drive}::{case}", "-p", "no:randomly", "-q"]
        held, held_what = (
            re.compile(r"^\s*\d+ (passed|subtests? passed)", re.M),
            "a `N passed` line",
        )
    else:
        argv = ["bash", drive, "--case", case]
        held, held_what = re.compile(r"^\s*ok\b", re.M), "an `ok` line"
    # THE OUTPUT GOES TO A FILE, NEVER A PIPE. Every drive here refuses a piped
    # stdout — the same guard the gate has, for the same reason — so
    # `capture_output=True` measures the refusal and not the drawer. Paid once,
    # by `test_divergence_census.sh` answering "this drive refuses pipes".
    try:
        with tempfile.NamedTemporaryFile("w+", prefix="djb-drawer-", suffix=".log") as sink:
            proc = subprocess.run(
                argv,
                cwd=ROOT,
                stdout=sink,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
            sink.flush()
            sink.seek(0)
            transcript = sink.read().rstrip()
    except subprocess.TimeoutExpired:
        return (f"the case did not finish inside {timeout}s", "")
    except OSError as error:  # a toolchain this checkout does not have
        return (f"the case could not be started — {error}", "")
    if proc.returncode == 2:
        return ("the case COULD NOT LOOK (exit 2) — it cleared nothing", transcript)
    if proc.returncode != 0:
        return (f"the case did not hold (exit {proc.returncode})", transcript)
    if not held.search(transcript):
        # A case that ran, said nothing and exited 0 has asserted nothing, and
        # is the one shape that reads exactly like a drawer that works.
        return (f"the case exited 0 and its transcript carries no {held_what}", transcript)
    return ("", transcript)


def drawers_leg() -> None:
    """Prove every drawer's reader really runs a planted item, and say what it cost."""
    doc = ROOT / C._DRAWERS_DOC
    if not doc.is_file():
        RUN.broken.append(
            f"DRAWERS CENSUS COULD NOT LOOK — {C._DRAWERS_DOC} is not in this tree, so "
            "there is no table of drawers to run. Rule 60's class (b) says the same "
            "thing about the same file; this leg proves nothing without it."
        )
        return
    rows, _bad = C.drawer_rows(doc.read_text())
    live = [row for row in rows if row.state == "live"]
    held = [row for row in rows if row.state == "held"]
    if not live:
        RUN.broken.append(
            "DRAWERS CENSUS HAS NO SUBJECT — the `drawers` table declares no live row, so "
            "this leg would pass by running nothing. Rule 60's `drawer_rows` floor is the "
            "other half of this sentence."
        )
        return

    started = time.time()
    ran = 0
    for row in live:
        why, transcript = drawer_case_problem(row)
        if why:
            RUN.broken.append(
                f"DRAWER BROKEN — `{row.drawer}` (reader `{row.reader}`): {why}. The case "
                f"`{row.case}` is what proves one planted item reaches that reader; a "
                "drawer whose reader does not run the plant is a seam a product drops a "
                "file into and never hears from again. Transcript:\n"
                + ("\n".join(f"      | {line}" for line in transcript.splitlines()[-12:]))
            )
            continue
        ran += 1
        say(f"  drawer {row.drawer}: {row.case.rpartition('::')[2]} held")

    # -- THE LEG'S OWN CANARY AND NEGATIVE, each building its own victim ------
    # The subject is `drawer_case_problem`, so the forms are ROWS handed to it
    # — the shape `residence_leg` and `namespace_leg` already use — and the
    # victim is a two-line script this leg writes and removes. A row pointing
    # at a real drive would be a canary about somebody else's case.
    canary_fired = 0
    negative_silent = 0
    with tempfile.TemporaryDirectory(prefix="djb-drawers-canary-") as scratch:
        red = Path(scratch) / "test_a_drawer_that_does_not_run_its_plant.sh"
        red.write_text(
            "#!/usr/bin/env bash\n"
            "# Planted by the drawers leg and removed in the same breath: the shape of a\n"
            "# reader that opened the drawer and did not run what was in it.\n"
            'echo "  FAILED   the drawer was opened and the plant never ran"\n'
            "exit 1\n"
        )
        green = Path(scratch) / "test_a_drawer_that_runs_its_plant.sh"
        green.write_text(
            "#!/usr/bin/env bash\n"
            'echo "  ok       the planted item reached the reader and was named"\n'
            "exit 0\n"
        )
        forms = (
            ("a case that did not hold", red, True),
            ("a case that held", green, False),
            (
                "a case this tree does not have",
                Path(scratch) / "test_nothing_here.sh",
                True,
            ),
        )
        for label, script, must_fire in forms:
            try:
                rel = str(script.relative_to(ROOT))
            except ValueError:
                # The scratch is outside the checkout (rung-execution §5), so the
                # row names it by absolute path — which `drawer_case_problem`
                # resolves through `ROOT /`, and an absolute path there is itself.
                rel = str(script)
            # THE FORGED DRAWER IS DELIBERATELY NOT DRAWER-SHAPED, and that
            # is the rule working on its own canary harness: class (b) derives
            # its population from the drawer paths the template's own code
            # SPELLS, so a realistic one written here — even inside a comment,
            # which the census reads exactly as it reads code — would be a
            # drawer this file opens with no row, a finding against the census
            # by the census. The drawer field is a label in the message; the
            # subject of these three forms is the case.
            forged = C.DrawerRow(
                0, "live", label, "scripts/forged-drawer.d/<n>.sh", "x::y", f"{rel}::case_x"
            )
            why, _ = drawer_case_problem(forged, timeout=30)
            if must_fire and why:
                canary_fired += 1
            elif must_fire:
                RUN.broken.append(
                    f"DRAWERS CANARY DEAD — {label} was handed to the drawer census and it "
                    "reported nothing. Every verdict this leg prints above is then a "
                    "verdict from a census that cannot fail."
                )
            elif why:
                RUN.broken.append(
                    f"DRAWERS FALSE-POSITIVE REGRESSION — {label} was reported as a broken "
                    f"drawer: {why}"
                )
            else:
                negative_silent += 1

    seconds = time.time() - started
    ceiling = W.Bound(
        direction="ceiling",
        recorded=engine_number("drawers", "ceiling_s"),
        measured=int(seconds),
        home="quality/rules.yaml `engine: drawers:`",
        klass="ceiling_s",
        subject="the drawers census's seconds",
        word="ceiling",
    )
    say(
        f"  drawers census: {ran} of {len(live)} live drawer(s) ran a planted item through "
        f"their own case · {len(held)} held (a reserved name, no reader by design) · "
        f"{canary_fired} of {engine_number('drawers', 'canaries')} canary forms fired · "
        f"{negative_silent} of {engine_number('drawers', 'negatives')} negative stayed "
        f"silent · {seconds:.0f}s against a recorded ceiling of {ceiling.recorded}s"
    )
    engine_leg("drawers", fired=canary_fired, silent=negative_silent)
    if ceiling.breached:
        RUN.broken.append(
            f"DRAWERS CENSUS OVER ITS CEILING — {ceiling.breach_clause()}. A census nobody "
            "can afford is a census somebody turns off: run the cheapest case that proves "
            "discovery for the drawer that grew, or commit a higher ceiling in a diff a "
            "reviewer reads."
        )


def declaration_leg() -> None:
    """Prove the declaration's own censuses can fail, and say how many did.

    RULE-SHAPED AND FILE-SHAPED, because the subjects are of different kinds
    and a canary has to be planted through the mechanism the check really
    reads. The duplicate-id refusal's subject is `rules.yaml` data and the
    engine-fixture refusal's is a declaration in this module, so their forms
    are scratch data handed to the finding function — the shape `residence_leg`
    above already uses. The orphan census's subject is a FILE ON DISK, so its
    two forms are real files written into the real fixture trees and removed in
    a `finally`: a synthetic listing would have proved the arithmetic and left
    the walk itself able to go blind.

    Four forms, three negatives, each canary building its own victim. A form
    that does not fire is exit 2, never a pass.
    """
    fired = 0
    silent = 0

    # -- the duplicate id: it must fire, AND it must carry its remedy ----------
    # A refusal that fires with three words is the state this leg was written
    # against, so "did it fire" is not the whole question: the canary asserts
    # the parts of the remedy a reader acts on — both colliding entries, the
    # shared fixture directories, and which of the two is the one that moves.
    victim_id = str(RULES[0]["id"])
    dup = {
        "id": victim_id,
        "statement": "a scratch entry planted by the self-test to collide with a real id",
        "check": "zzz-declaration-canary",
    }
    dup_lines = duplicate_id_findings([*RULES, dup])
    if not dup_lines:
        RUN.broken.append(
            f"DUPLICATE-ID CANARY DEAD — a second entry declaring id {victim_id} did not "
            "raise a duplicate-id finding at all"
        )
    else:
        line = dup_lines[-1]
        wanted = (
            "THE COLLISION:",
            "REMEDY:",
            f"quality/canary/{victim_id}/",
            f"quality/negative/{victim_id}/",
            "rule_id_namespace",
            # THE CITE IS PART OF THE REMEDY, asserted so a later rewrite that
            # drops it goes red rather than quietly leaving a product to guess
            # where the grammar is written down (V-D1a rider).
            "ADR gate-5",
            "CHANGELOG",
        )
        absent = [w for w in wanted if w not in line]
        if absent:
            RUN.broken.append(
                f"DUPLICATE-ID CANARY MUTE — the refusal fired for id {victim_id} without "
                f"the part of its remedy a reader acts on: {', '.join(absent)} is not in the "
                "line. A duplicate id a product cannot act on is the state this remedy "
                "replaced"
            )
        else:
            fired += 1
    # THE NEGATIVE: an entry with an id nothing else holds is not a collision.
    fresh = dict(dup, id="zzz-declaration-negative")
    if duplicate_id_findings([*RULES, fresh]):
        RUN.broken.append(
            "DUPLICATE-ID FALSE-POSITIVE REGRESSION — an entry whose id no other entry "
            "holds was reported as a duplicate"
        )
    else:
        silent += 1

    # -- the orphan fixture: two forms, each a real file, each removed --------
    # Form one is the shape a fold produces: a file in a REAL rule's directory
    # that the rule's plan does not name. Form two is the directory half: a
    # fixture directory numbered for a rule that does not exist.
    real_dir = next(
        (NEGATIVE_DIR / str(r["id"]) for r in RULES if (NEGATIVE_DIR / str(r["id"])).is_dir()),
        None,
    )
    if real_dir is None:
        RUN.broken.append(
            "ORPHAN-FIXTURE CANARY COULD NOT RUN — no rule on this tree has a negative "
            "fixture directory, so the census has no real directory to be planted into"
        )
    else:
        forms = (
            real_dir / "zzz_orphan_canary.py",
            NEGATIVE_DIR / "zzz-no-such-rule" / "zzz_orphan_canary.py",
        )
        for victim in forms:
            made_dir = not victim.parent.is_dir()
            if made_dir:
                victim.parent.mkdir(parents=True)
            victim.write_text(
                "# planted by the self-test's declaration leg and removed in the same "
                "breath; a copy that outlived its run is the census working\n"
            )
            try:
                lines = orphan_fixture_findings(RULES, fixture_files_on_disk())
            finally:
                victim.unlink(missing_ok=True)
                if made_dir:
                    victim.parent.rmdir()
            rel = str(victim.relative_to(ROOT))
            if any(rel in line for line in lines):
                fired += 1
            else:
                RUN.broken.append(
                    f"ORPHAN-FIXTURE CANARY DEAD — {rel} was written into the fixture tree "
                    "and no entry of any rule claims it, and the census did not name it"
                )
    # -- the engine's own claims: a declared fixture the tree does not have --
    # The form that turned a real deletion into a FileNotFoundError halfway
    # through a self-test before this guard existed. The victim is a synthetic
    # declaration, never the real dict: deleting the real file to prove the
    # point would break the very leg the file exists for.
    absent = ROOT / "quality" / "negative" / "zzz-no-such-rule" / "zzz_never_written.js"
    if engine_fixture_findings({absent: "a scratch declaration planted by the self-test"}):
        fired += 1
    else:
        RUN.broken.append(
            f"ENGINE-FIXTURE CANARY DEAD — {absent.relative_to(ROOT)} is declared and is not "
            "on this tree, and the census did not say so"
        )
    if engine_fixture_findings(ENGINE_FIXTURES):
        RUN.broken.append(
            "ENGINE-FIXTURE REGRESSION — a fixture this module plants by path is missing "
            "from the tree; the lines from the consistency census above name it"
        )
    else:
        silent += 1

    # THE NEGATIVE, and it is the tree itself: at rest, after both plants were
    # removed, every file under the two fixture trees is claimed by an entry.
    # It is the restore-proof as well as the restraint-proof — a plant that
    # outlived its `finally` would show up here as a finding.
    at_rest = orphan_fixture_findings(RULES, fixture_files_on_disk())
    if at_rest:
        RUN.broken.append(
            "ORPHAN-FIXTURE FALSE-POSITIVE OR UNRESTORED PLANT — the tree at rest is not "
            "clean under the orphan census: " + " | ".join(at_rest)
        )
    else:
        silent += 1

    say(
        f"declaration census: {fired} of {engine_number('declaration', 'canaries')} canary "
        f"forms fired · {silent} of {engine_number('declaration', 'negatives')} negatives "
        "stayed silent (duplicate id with its remedy; an unclaimed file in a real rule's "
        "directory; a fixture directory no rule is named for; an engine-planted fixture "
        "the tree does not have)"
    )
    engine_leg("declaration", fired=fired, silent=silent)


# --- the seam's own canaries: a process boundary that cannot fail silently -------
#
# WHY THESE ARE NOT PLANTED FILES. Every other canary in this engine is a wrong
# file dropped into the real tree, because every other check's subject IS a
# file. The seam's subject is a RUNNER THAT WILL NOT ANSWER — missing, dead,
# slow, mute, lying, or reporting about somewhere it was never pointed — and no
# file anywhere makes a subprocess exit non-zero. So the forms are rules rather
# than fixtures, driven straight through `run_rule` so that the whole pipeline
# they must survive is the pipeline they are proved against, and they are
# counted against a recorded floor in `rules.yaml` exactly as a planted plan is.
#
# THE FAILURE MODE ALL OF THIS EXISTS TO REFUSE, said once: a runner that
# crashes, prints nothing and is read as zero findings. Every rule of a whole
# language then reports green from the day it is wired, and nothing on either
# side of the boundary can tell anybody. The list below is that sentence turned
# into a population a reader can count.

#: The seam's test double: one runner that emits a NAMED reply. One file rather
#: than fifteen, because the interesting thing about each form is the reply's
#: shape and a reader should be able to see all of them side by side.
SEAM_REPLIES = "quality/runners/fixtures/replies.py"


def _replies(name: str) -> list[str]:
    return ["python3", SEAM_REPLIES, name]


def _seam_rule(
    label: str,
    *,
    argv: list[str],
    roots: list[str],
    needs_tree: str | None = None,
    timeout: int | None = None,
    floors: dict | None = None,
) -> dict:
    """A synthetic rule for one seam form — inline kind, so no row is added to
    the population the self-test is measuring."""
    rule: dict = {
        "id": f"seam:{label}",
        "kind": {"roots": roots, "suffixes": [".py"], "comment": "#"},
        "runner": {"argv": argv} if timeout is None else {"argv": argv, "timeout": timeout},
    }
    if needs_tree is not None:
        rule["needs_tree"] = needs_tree
    if floors is not None:
        rule["floors"] = floors
    return rule


def _seam_probe(rule: dict, *, floors: bool = False) -> tuple[list[Finding], dict, str, list[str]]:
    """Run one synthetic rule and TAKE BACK whatever it appended to `broken`.

    The refusals these forms provoke are the proof, not the verdict: leaving
    them in `broken` would make a healthy seam exit 2 for demonstrating that it
    works. Removed by slice rather than by matching text, so a form that
    produced two refusals cannot leave one behind.
    """
    mark = len(RUN.broken)
    kept, targets, skip = run_rule(rule, floors=floors)
    produced = RUN.broken[mark:]
    del RUN.broken[mark:]
    return kept, targets, skip, produced


#: (label, the form, the refusal class its message must name). Each class is a
#: separate way to be unbelievable, and each one is here because reading it as
#: "clean" is a plausible mistake for an engine to make.
def _seam_canaries() -> list[tuple[str, dict, str]]:
    present = "quality"
    js_roots = ["quality"]
    nothing = "djb-no-such-instrument-on-this-box"
    return [
        # -- the runner will not run: three ways, and none of them is "clean" --
        ("runner-absent", _seam_rule("absent", argv=[nothing], roots=js_roots), "runner-absent"),
        (
            "runner-not-executable",
            _seam_rule("not-exec", argv=["quality/rules.yaml"], roots=js_roots),
            "runner-not-executable",
        ),
        # The POSIX always-fails program, resolved through PATH rather than
        # spelled as a path so that the form is about a runner that FAILS and
        # never accidentally about one that is missing on some other box.
        (
            "runner-failed",
            _seam_rule("failed", argv=["false"], roots=js_roots, needs_tree=present),
            "runner-failed",
        ),
        (
            "runner-timeout",
            _seam_rule(
                "timeout", argv=_replies("sleep"), roots=js_roots, needs_tree=present, timeout=1
            ),
            "runner-timeout",
        ),
        # -- the runner answers, and the answer cannot be believed ------------
        (
            "reply-not-json",
            _seam_rule("not-json", argv=_replies("not-json"), roots=js_roots, needs_tree=present),
            "reply-not-json",
        ),
        (
            "reply-not-an-object",
            _seam_rule(
                "not-object", argv=_replies("not-an-object"), roots=js_roots, needs_tree=present
            ),
            "reply-not-an-object",
        ),
        (
            "reply-wrong-protocol",
            _seam_rule(
                "wrong-protocol",
                argv=_replies("wrong-protocol"),
                roots=js_roots,
                needs_tree=present,
            ),
            "reply-wrong-protocol",
        ),
        (
            "reply-unknown-key",
            _seam_rule(
                "unknown-key", argv=_replies("unknown-key"), roots=js_roots, needs_tree=present
            ),
            "reply-unknown-key",
        ),
        (
            "findings-not-a-list",
            _seam_rule(
                "findings-scalar",
                argv=_replies("findings-not-a-list"),
                roots=js_roots,
                needs_tree=present,
            ),
            "findings-not-a-list",
        ),
        (
            "finding-not-an-object",
            _seam_rule(
                "finding-scalar",
                argv=_replies("finding-not-an-object"),
                roots=js_roots,
                needs_tree=present,
            ),
            "finding-not-an-object",
        ),
        (
            "finding-missing-key",
            _seam_rule(
                "finding-missing",
                argv=_replies("finding-missing-key"),
                roots=js_roots,
                needs_tree=present,
            ),
            "finding-missing-key",
        ),
        (
            "finding-unknown-key",
            _seam_rule(
                "finding-extra",
                argv=_replies("finding-unknown-key"),
                roots=js_roots,
                needs_tree=present,
            ),
            "finding-unknown-key",
        ),
        (
            "finding-bad-type",
            _seam_rule(
                "finding-type",
                argv=_replies("finding-bad-type"),
                roots=js_roots,
                needs_tree=present,
            ),
            "finding-bad-type",
        ),
        # A runner reporting about somewhere it was never pointed would move a
        # rule's subject without the rule changing.
        (
            "finding-outside-roots",
            _seam_rule(
                "outside",
                argv=_replies("finding-outside-roots"),
                roots=js_roots,
                needs_tree=present,
            ),
            "finding-outside-roots",
        ),
        # Targets feed the floors, and a floor fed a string counts nothing while
        # reporting something.
        (
            "targets-shape",
            _seam_rule(
                "targets", argv=_replies("targets-shape"), roots=js_roots, needs_tree=present
            ),
            "targets-shape",
        ),
        # -- the tri-state's refusing cell: a subject with no instrument ------
        (
            "tree-present-toolchain-absent",
            _seam_rule("cell-b", argv=[nothing], roots=js_roots, needs_tree=present),
            "IS on this tree and its instrument is not",
        ),
        # The same cell reached the other way. A toolchain is absent when the
        # PATH does not hold it AND when the file that is there cannot be run,
        # and a cell that only knew the first would let a chmod turn a rule off.
        (
            "tree-present-instrument-unrunnable",
            _seam_rule(
                "cell-b-twin", argv=["quality/rules.yaml"], roots=js_roots, needs_tree=present
            ),
            "exists and is not executable",
        ),
    ]


#: The stand-in cell-a uses to prove "an absent tree derives its floor to 0".
#: A LITERAL PRODUCT DIRECTORY NAME IS THE WRONG SHAPE HERE — this used to be
#: the literal "frontend", which was a legal stand-in for exactly as long as
#: no product tree by that name existed. The scaffold rung made `frontend/` a
#: real, tracked directory, and from that commit on cell-a stopped skipping:
#: `tree_verdict` saw a present tree, ran the canned-reply runner for real,
#: and its recorded floor of 150 fired UNBOUND against a canned
#: `files_scanned=3` — the check was never watching frontend at all (js_roots
#: stayed ["quality"]), but nothing told it the tree it was gating on had
#: stopped being absent. This name is synthetic and namespaced so nothing a
#: product grows can collide with it by accident; `seam_sentinel_census`
#: below proves that assumption on every run rather than trusting it forever,
#: which is the difference between fixing today's collision and fixing the
#: class of defect.
SEAM_ABSENT_TREE = "djb-no-such-tree-on-this-box"


def seam_leg() -> tuple[int, int]:
    """Fire every seam canary, hold every seam negative silent. (fired, silent)."""
    fired = 0
    silent = 0
    present, absent_tree = "quality", SEAM_ABSENT_TREE
    js_roots = ["quality"]

    for label, rule, wanted in _seam_canaries():
        kept, _targets, skip, produced = _seam_probe(rule)
        text = " ".join(produced)
        if wanted in text:
            fired += 1
        else:
            RUN.broken.append(
                f"SEAM CANARY DEAD — the {label} form did not refuse naming {wanted!r}. It "
                f"produced {produced!r} with {len(kept)} findings and skip={skip!r}; a runner "
                "this engine cannot believe must be could-not-look and never a clean scan"
            )

    # -- the negatives: the shapes the seam must ACCEPT ----------------------
    #
    # Without these the module above could pass every canary by refusing
    # everything, which is a protocol that reads nothing and a gate that can
    # never go green.
    accepted: list[tuple[str, dict, int, dict]] = [
        (
            "clean-reply",
            _seam_rule("clean", argv=_replies("clean"), roots=js_roots, needs_tree=present),
            0,
            {"files_scanned": 3},
        ),
        (
            "findings-inside-roots",
            _seam_rule("findings", argv=_replies("findings"), roots=js_roots, needs_tree=present),
            2,
            {"files_scanned": 2},
        ),
        # Line 0 is how this engine already spells "the file itself", and a
        # protocol that refused it would refuse half the findings it will carry.
        (
            "file-level-finding",
            _seam_rule("line-zero", argv=_replies("line-zero"), roots=js_roots, needs_tree=present),
            1,
            {"files_scanned": 1},
        ),
        # stderr is not the protocol. A runner that warns about a cache while
        # answering correctly has answered correctly.
        (
            "stderr-is-not-the-protocol",
            _seam_rule("stderr", argv=_replies("stderr-noise"), roots=js_roots, needs_tree=present),
            1,
            {"files_scanned": 1},
        ),
    ]
    for label, rule, want_findings, want_targets in accepted:
        kept, targets, skip, produced = _seam_probe(rule)
        if produced or skip or len(kept) != want_findings or targets != want_targets:
            RUN.broken.append(
                f"SEAM FALSE-POSITIVE REGRESSION — the {label} form is a legal check-v1 reply "
                f"and was not read as one: refusals={produced!r}, skip={skip!r}, "
                f"findings={len(kept)} (wanted {want_findings}), targets={targets!r} (wanted "
                f"{want_targets!r})"
            )
        else:
            silent += 1

    # The klass a runner declares must survive the boundary, because it is what
    # the engine's per-class ratchets are counted against: a klass dropped in
    # transit silently merges two backlogs into one.
    kept, _targets, _skip, produced = _seam_probe(
        _seam_rule("klass", argv=_replies("findings"), roots=js_roots, needs_tree=present)
    )
    if produced or sorted(f.klass for f in kept) != ["shape", "vocabulary"]:
        RUN.broken.append(
            "SEAM FALSE-POSITIVE REGRESSION — a runner's declared finding classes did not "
            f"survive the boundary: got {[f.klass for f in kept]!r}, wanted ['shape', "
            "'vocabulary']"
        )
    else:
        silent += 1

    # -- the tri-state's two silent cells ------------------------------------
    #
    # A SKIP THAT PRINTS NOTHING IS INDISTINGUISHABLE FROM A PASS, so the
    # sentence is asserted here and not merely the silence: the printed line is
    # the criterion, and a future edit that keeps the skip and drops the words
    # is exactly the regression this catches.
    _kept, targets, skip, produced = _seam_probe(
        _seam_rule(
            "cell-a",
            argv=_replies("clean"),
            roots=js_roots,
            needs_tree=absent_tree,
            floors={"files_scanned": 150},
        ),
        floors=True,
    )
    if produced or not skip.strip() or targets:
        RUN.broken.append(
            "SEAM TRI-STATE REGRESSION — a rule whose tree is not on this checkout did not "
            f"skip-and-say-so: refusals={produced!r}, sentence={skip!r}. A recorded floor of "
            "150 over an absent tree must derive to 0 rather than report UNBOUND"
        )
    else:
        silent += 1
    verdict, why = W.tree_verdict(
        ROOT,
        _seam_rule("cell-c", argv=_replies("clean"), roots=js_roots, needs_tree=present),
        SCOPE_KINDS,
    )
    if verdict != "run" or why:
        RUN.broken.append(
            f"SEAM TRI-STATE REGRESSION — a present tree with a present instrument gave "
            f"{verdict!r} ({why!r}) instead of running"
        )
    else:
        silent += 1

    silent += seam_valve_census()
    silent += seam_skip_dir_census()
    hygiene_fired, hygiene_silent = plant_hygiene_census()
    fired += hygiene_fired
    silent += hygiene_silent
    sentinel_fired, sentinel_silent = seam_sentinel_census()
    fired += sentinel_fired
    silent += sentinel_silent
    say(f"seam: {fired} runner-protocol canary forms refused · {silent} legal shapes accepted")
    return fired, silent


def seam_sentinel_census() -> tuple[int, int]:
    """Prove the tri-state's own 'absent tree' sentinel is actually absent. (fired, silent).

    THE DEFECT THIS EXISTS TO CATCH, NOT JUST TODAY'S INSTANCE OF IT. Cell-a's
    proof that "an absent tree derives its floor to 0" is only as honest as
    its stand-in tree genuinely being absent — `SEAM_ABSENT_TREE` replaces the
    literal "frontend", which was a legal choice for exactly as long as no
    product tree by that name existed, and stopped being one, silently, the
    moment the scaffold rung made `frontend/` real. A new synthetic name fixes
    that one collision; it does not fix the CLASS unless something checks,
    every run, that the name still holds no real tree. So: plant a directory
    at the sentinel path and prove the collision is caught loudly (fired);
    remove it and prove the ordinary, empty case stays silent (silent) — the
    same two-directions discipline as `plant_hygiene_census`, aimed at the
    premise a tri-state cell stands on rather than at the cell itself.
    """
    fired = 0
    silent = 0
    sentinel = ROOT / SEAM_ABSENT_TREE
    if sentinel.exists():
        RUN.broken.append(
            f"SEAM SELFTEST SENTINEL COLLISION — {SEAM_ABSENT_TREE!r} is meant to be a tree "
            "this checkout never has, and it already does, before the self-test planted "
            "anything. Cell-a's proof that an absent tree derives its floor to 0 needs a name "
            "nothing on the tree will ever hold — pick a different one rather than silently "
            "reading a present tree as though it were absent."
        )
        return fired, silent
    try:
        sentinel.mkdir()
        if (ROOT / SEAM_ABSENT_TREE).exists():
            fired += 1
        else:
            RUN.broken.append(
                "SEAM SENTINEL CANARY DEAD — a directory planted at the seam's own 'absent "
                f"tree' sentinel ({SEAM_ABSENT_TREE!r}) was not detected as present. If this "
                "check cannot see a real collision, cell-a can silently start scanning a real "
                "tree under that name exactly as it did for 'frontend' once."
            )
    finally:
        if sentinel.exists():
            sentinel.rmdir()
    if not (ROOT / SEAM_ABSENT_TREE).exists():
        silent += 1
    else:
        RUN.broken.append(
            f"SEAM SELFTEST SENTINEL COLLISION — {SEAM_ABSENT_TREE!r} was not restored "
            "cleanly after the plant; a later run reading it as absent would be wrong."
        )
    return fired, silent


def plant_hygiene_census() -> tuple[int, int]:
    """The two plant-path refusals, proved in both directions. (fired, silent).

    THE PAIR, and they are not the same question. One asks whether a plant path
    is DIRTY — the self-test's refusal, which exists because a run that cannot
    tell its plants from your work cannot restore honestly. The other asks
    whether a plant path IS A FIXTURE — the preflight, which exists because a
    run killed before its restore leaves the tree carrying wrongness that every
    later run reads as the product's own. A gate that had only the first would
    still go green over the residue of the run that died; a gate that had only
    the second would plant on top of somebody's uncommitted work.

    Driven from inside the self-test because that is the one place a plant can
    be held on purpose, and asserted in both directions because a refusal that
    fired on everything would refuse every ordinary working tree.
    """
    fired = 0
    silent = 0
    forms = [
        # A CREATED plant, standing where a dead run would have left it.
        ("50", NEGATIVE_DIR, RULES_BY_ID["50"]["negatives"][0]),
        # An APPENDED plant, which leaves a real tracked file with the fixture
        # on the end of it — a different residue and a different comparison.
        ("1", CANARY_DIR, RULES_BY_ID["1"]["canaries"][0]),
    ]
    for rid, base, entry in forms:
        plant = Plant()
        try:
            plant.put(base / rid / entry["fixture"], entry["plant_at"], entry["mode"])
            standing = [line for line in stale_plants() if entry["fixture"] in line]
            if standing:
                fired += 1
            else:
                RUN.broken.append(
                    f"STALE-PLANT CANARY DEAD — {entry['fixture']} was standing at "
                    f"{entry['plant_at']} ({entry['mode']}) and the preflight did not see it. "
                    "A run that dies before restore would then be measured as the product"
                )
            # The dirty-path half over the same held plant: whatever else it is,
            # a plant path carrying content git did not put there is a path this
            # engine must refuse to plant into.
            if any(str(entry["plant_at"]) in line for line in tree_dirty_under_plants()):
                fired += 1
            else:
                RUN.broken.append(
                    f"DIRTY-PLANT-PATH CANARY DEAD — {entry['plant_at']} was dirty and the "
                    "refusal did not see it. A self-test that cannot tell its own plants "
                    "from somebody's uncommitted work cannot restore honestly"
                )
        finally:
            plant.restore()
    # The restored tree is the negative for BOTH, and it is the assertion that
    # keeps either from being "any file under a plant path".
    residue = stale_plants() + tree_dirty_under_plants()
    if residue:
        RUN.broken.append(
            "PLANT-HYGIENE FALSE-POSITIVE REGRESSION — a restored tree was reported as "
            f"carrying residue: {residue}"
        )
    else:
        silent += 1
    return fired, silent


def seam_valve_census() -> int:
    """A valve written in a second language is suppressed AND counted. (1 or 0).

    THE HALF THAT IS EASY TO LOSE. Suppression alone is an off switch: the
    standing override section is the only thing that makes an exemption a
    decision somebody can read back, and a valve syntax the census walk does not
    know about is silently uncountable while still silently working. So the
    proving rule's own negative is planted and BOTH halves are asserted over the
    same file.
    """
    rid = "50"
    entries = [
        e
        for e in (RULES_BY_ID.get(rid, {}).get("negatives") or [])
        if "valve" in str(e.get("fixture", ""))
    ]
    if not entries:
        RUN.broken.append(
            f"SEAM VALVE CENSUS — rule {rid} has no valve negative to plant, so nothing "
            "proves a second language's exemption is counted rather than merely obeyed"
        )
        return 0
    entry = entries[0]
    plant = Plant()
    try:
        plant.put(
            fixture_home("negative", rid) / entry["fixture"], entry["plant_at"], entry["mode"]
        )
        rows = [row for row in all_overrides() if row[1] == str(entry["plant_at"])]
        if not rows:
            RUN.broken.append(
                "SEAM VALVE CENSUS — a `// rule-` valve planted at "
                f"{entry['plant_at']} is invisible to the standing override census. An "
                "exemption nobody counts is an off switch with extra steps"
            )
            return 0
        if rows[0][0] != rid or len(rows[0][3]) < MIN_REASON:
            RUN.broken.append(
                f"SEAM VALVE CENSUS — the planted valve was read as {rows[0]!r}, which is "
                f"not rule {rid} carrying a reason"
            )
            return 0
        return 1
    finally:
        plant.restore()


def seam_skip_dir_census() -> int:
    """A valve planted inside a kind's declared VENDORED directory stays OUT. (1 or 0).

    Ruled 2026-08-31. Before `quality/rules.yaml`'s `scope_kinds.js.skip_dirs`
    existed, `all_overrides()` skipped only `__pycache__` while the `js_secrets`
    runner carried its own separate `SKIP_DIRS` — two lists that disagreed, and
    a `// rule-` valve sitting inside a vendored `node_modules/` would have
    entered the standing override census exactly as a real one does. Planting
    one there and demanding it stay invisible to the census is the engine-side
    half of the fix; `quality/runners/js_secrets.py`'s own read of the identical
    declaration (`quality/runners/_kindscope.py`) is the runner-side half, and
    nothing here can see that half — only that both sides now consult one list.
    """
    target = "frontend/node_modules/some-pkg/index.js"
    plant = Plant()
    try:
        plant.put(VENDORED_VALVE_FIXTURE, target, "create")
        rows = [row for row in all_overrides() if row[1] == target]
        if rows:
            RUN.broken.append(
                "SEAM SKIP-DIR CENSUS — a `// rule-` valve planted inside "
                f"frontend/node_modules/ was counted in the standing override census: {rows!r}. "
                "A vendored directory must not enter the census any more than it enters a live "
                "scan"
            )
            return 0
        return 1
    finally:
        plant.restore()


#: A finding's identity for the self-test's delta: everything a reader sees.
FindingKey = tuple[str, int, str, str]


def _finding_key(f: Finding) -> FindingKey:
    return (f.path, f.line, f.msg, f.klass)


def form_delta(planted: list[Finding], baseline: list[Finding]) -> list[Finding]:
    """The findings a plant ADDED: `planted` minus `baseline`, as an exact multiset.

    THE WHOLE VERDICT OF A FORM IS THIS DIFFERENCE. A canary fires when the
    difference holds a finding naming its plant; a negative is silent when it
    holds none. Both sides are raw (check + `apply_overrides`, never
    `apply_ratchets`), so a backlog on the tree — recorded, paid, or bigger
    than the number — cannot absorb a canary or hide a negative that fired:
    what the form is judged on is what the form did, on this tree, whatever
    this tree already carried.

    **does_not_cover:** a planted finding identical in path, line, message and
    class to one the tree already had is subtracted with it — a `replace` plant
    reproducing its target's own finding exactly would read as silent on that
    finding. No form in the plan does that today.
    """
    left: dict[FindingKey, int] = {}
    for f in baseline:
        key = _finding_key(f)
        left[key] = left.get(key, 0) + 1
    added: list[Finding] = []
    for f in planted:
        key = _finding_key(f)
        if left.get(key, 0) > 0:
            left[key] -= 1
        else:
            added.append(f)
    return added


def could_not_look_cause(rule: dict, skip: str) -> str:
    """The short cause a rule's line prints when a form could not be judged.

    Taken from the sentence `run_rule` returned, never composed from a guess: a
    runner's refusal carries its class in parentheses, and whether it was the
    rule's `runner:` or a drawer's local runner is read off the rule the same
    way `run_rule` chose between them.
    """
    body = skip[len(COULD_NOT_LOOK) :] if skip.startswith(COULD_NOT_LOOK) else skip
    m = re.match(r"\(([^)]+)\)", body)
    if m:
        impl = rule.get("check")
        local = bool(impl) and impl not in REGISTRY
        return f"{'local runner' if local else 'runner'} refused: {m.group(1)}"
    return body.split(" — ")[0].strip()[:120] or "could not look"


def raw_form_findings(rule: dict, via: str) -> tuple[list[Finding], str]:
    """One rule's RAW findings on the tree as it stands. (findings, could-not-look cause).

    The cause is empty for a rule that ran; for one that could not look, it is
    the short cause the rule's own self-test line prints.
    """
    rid = str(rule["id"])
    if via == "diff":
        result = C.diff_checks(ROOT, "HEAD", RULES_BY_ID).get(rid, CheckResult())
        kept, _ = apply_overrides(rid, result.findings)
        return kept, ""
    kept, _, skip = run_rule(rule, floors=False, ratchets=False)
    if skip.startswith(COULD_NOT_LOOK):
        return [], could_not_look_cause(rule, skip)
    return kept, ""


def judged_shape() -> str:
    """Which shape this self-test judges on — the TEMPLATE's or a PRODUCT's.

    ONE READER OF THE BASE, AND IT IS NOT THIS FUNCTION. Rule 60's controls are
    judged differently on a tree that declares a template base (a product) and
    on one that does not (the template itself), so a transcript that does not
    say which it judged cannot be compared with another. The answer is taken
    from `python -m quality.djb.rituals.divergence --if-declared`'s own `base` line — the
    census owns the three readers and their precedence — and is only
    re-spelled here. Stdout to a file, never a pipe: the census refuses a pipe.
    """
    script = ROOT / JUDGED_SHAPE_CENSUS
    if not script.is_file():
        return f"could not be read ({JUDGED_SHAPE_CENSUS} is not in this tree)"
    with tempfile.NamedTemporaryFile("w+", prefix="djb-judged-shape-", suffix=".log") as sink:
        proc = subprocess.run(
            [sys.executable, "-m", "quality.djb.rituals.divergence", "--if-declared"],
            cwd=ROOT,
            stdout=sink,
            stderr=subprocess.STDOUT,
            check=False,
        )
        sink.flush()
        sink.seek(0)
        report = sink.read()
    for line in report.splitlines():
        stripped = line.strip()
        if not stripped.startswith("base "):
            continue
        value = stripped[len("base") :].strip()
        if value.startswith("none declared"):
            return "none declared (the template's own shape)"
        m = re.match(r"(\S+)\s+\(from (.+)\)$", value)
        if m:
            # EXIT 1 IS A FINDING, NOT A BLINDNESS. The census exits 1 when it
            # looked and found unnamed divergences — under rule 60's own
            # negative 2 it does so by construction — and its `census:` line
            # says how many. Only 2 (or anything else) is could-not-look.
            if proc.returncode == 0:
                tail = ""
            elif proc.returncode == 1:
                counted = re.search(r"^census:.*\bunnamed=(\d+)", report, re.MULTILINE)
                n = counted.group(1) if counted else "an uncounted number of"
                tail = f"; the census found {n} unnamed divergence(s) (exit 1)"
            else:
                tail = f"; the census could not look (exit {proc.returncode})"
            return f"{m.group(1)} (from {m.group(2)}){tail}"
    return f"could not be read (the census printed no base line; exit {proc.returncode})"


#: What each `needs_shape` word means, as the rule line spells it.
NEEDS_SHAPE_MEANS: dict[str, str] = {
    "template": "the template's own shape — no base declared —",
}


def shape_verdict(need: str) -> tuple[str, str]:
    """Is the tree, as it stands under a plant, the shape `need` names?

    ('judged', '') — it is; judge the form. ('not producible', <what this tree
    declares>) — it is not, and the census said what it is instead.
    ('could not look', <cause>) — the census gave no shape at all, or gave one
    while saying it could not look (exit 2).

    The answer is `judged_shape()`'s, re-read and never re-derived: the census
    owns the three base readers and their precedence, and a second reader here
    would be the thing principle 9 forbids.
    """
    shape = judged_shape()
    if shape.startswith("could not be read"):
        return "could not look", f"judged shape {shape}"
    if "; the census could not look" in shape:
        return "could not look", f"judged shape {shape}"
    declares_none = shape.startswith("none declared")
    if need == "template":
        if declares_none:
            return "judged", ""
        return "not producible", shape.split("; the census ")[0]
    return "could not look", f"needs_shape {need!r} is not one this engine can judge"


def narrowed_ids(only: list[str]) -> list[str]:
    """The ids a narrowed self-test judges — once each, in the plan's own order."""
    wanted = set(only)
    return [str(r["id"]) for r in RULES if str(r["id"]) in wanted]


def django_batch(kind: str) -> list[tuple[str, dict]]:
    """Every Django form of `kind` this world plants, as (rule id, entry), in plan order.

    THE DJANGO FORMS ARE ONE BATCH IN ONE APP, AND THE BATCH IS THEIR WORLD.
    Every rule's Django forms of a kind are planted into the probe app before
    one `manage.py check`, so each form stands on what the others laid there:
    a route APPENDED to `apps/zzz_canary/api.py` stands on the router another
    rule's form created, and a negative stays silent under the twins, the
    prefix and the tag declarations other rules' negatives supply. A narrowed
    run that planted only its own rules' forms built a different app — every
    form of rule 41 died of one `NameError: router` while the whole run proved
    it green. So a narrowed run plants THIS list, the whole corpus's, and
    judges only its named rules' entries in it: the world is the corpus's, the
    verdict is narrowed.
    """
    return [
        (str(rule["id"]), entry)
        for rule in RULES
        if rule.get("enabled", True)
        for entry in rule.get(kind) or []
        if entry.get("via") == "django" and not W.entry_out_of_world(entry, DISABLED_APPS)
    ]


#: What the last `selftest()` counted that `main()`'s closing line must repeat:
#: a clean run with a form not producible on this shape is not "every canary
#: fired, every negative stayed silent", and the closing line says so.
SELFTEST_RESULT: dict[str, int] = {"unproducible": 0}
#: The `rule-wall` line's name for the whole run's own parts, which no rule id owns.
WHOLE_PARTS = "@whole"


def _not_producible_clause() -> str:
    n = SELFTEST_RESULT.get("unproducible", 0)
    if not n:
        return ""
    return f" · {n} form{'' if n == 1 else 's'} not producible on this shape"


def selftest(only: list[str] | None = None, *, member: bool = False, whole: bool = False) -> None:
    """The engine's self-test — every rule's forms, or only the rules `only` names.

    A NARROWED RUN (`--selftest --rule <id>`) judges the named rules' forms
    exactly as the full run does — the same plants, the same delta, the same
    rule line, and for its Django forms the same probe app, the whole corpus's
    batch planted and only the named rules judged (`django_batch`) — and runs
    nothing else: not the five legs, not the seam, not the
    budget canary, not the trailer or cli censuses. It says so on its own line
    before the first plant, because a narrowed green is a claim about the named
    rules and is never the gate's verdict. The selftest leg runs the engine with
    no arguments, so the gate never takes this arm. The ONE census a narrowed
    run does take is the plant-collision census at the head: it judges the
    plants before any is planted, and a collision is the cause a narrowed run's
    SHORT count would otherwise leave unnamed.
    """
    # Read the tree's migration leaves BEFORE anything is planted into it, and
    # stop if any placeholder could not be resolved: a self-test that guessed a
    # parent would be proving something about a graph it invented.
    prime_plant_resolution()
    if RUN.broken:
        return
    dirty = tree_dirty_under_plants()
    if dirty:
        RUN.broken.append(
            "selftest refused: the tree is dirty under plant paths — it could not tell "
            "its plants from your work, or restore honestly:\n  " + "\n  ".join(dirty)
        )
        return

    # WHICH SHAPE THIS RUN JUDGES, said before the first plant: rule 60's
    # controls read differently on a tree that declares a template base.
    shape = judged_shape()
    say(f"selftest: template base — {shape}")
    # THE PLANT CENSUS'S COUNTS, once, derived from the plan this run judges:
    # `consistency()` already refused any outside plant (exit 2, nothing
    # planted), so the last number is 0 on every run that reaches this line.
    say(plant_namespace_line(RULES))
    # THE PLANT-COLLISION CENSUS, before the first plant and on a NARROWED run
    # too: a plant carrying a name the tree serves dies as a SHORT count with
    # nothing naming the cause, and a narrowed run of the rule it plants for is
    # exactly where somebody goes to find out why. Exit 2, nothing planted.
    collision_refusals, collision_line = plant_collision_run()
    say(collision_line)
    if collision_refusals:
        RUN.broken.extend(collision_refusals)
        return

    narrowed = narrowed_ids(only) if only else []
    NARROWED.clear()
    NARROWED.update(narrowed)
    if narrowed and member:
        say(
            f"selftest: partition member — rule(s) {', '.join(narrowed)}; the legs, the seam, the "
            f"budget canary and the cli census run {'HERE' if whole else 'in the --whole member'}"
        )
    elif narrowed:
        say(
            f"selftest: narrowed to rule(s) {', '.join(narrowed)} — the legs, the seam, the "
            "budget canary and the censuses were not run; this is not the gate's verdict"
        )
    # Invariant: the members' union is the whole run — the `--whole` member takes the unowned parts.
    parts = not narrowed or whole

    def in_scope(rid: str) -> bool:
        return not narrowed or rid in narrowed

    whole_started = time.monotonic()
    if parts:
        residence_leg()
        append_free_name_leg()
        ratchet_leg(shape)
        member_floor_leg()
        census_leg()
        frozen_leg()
        namespace_leg()
        plant_collision_leg()
        declaration_leg()
        drawers_leg()

    fired = 0
    silent = 0
    seam_fired, seam_silent = seam_leg() if parts else (0, 0)
    whole_wall = time.monotonic() - whole_started
    seam_floor = {
        "canaries": int((SEAM.get("selftest_floor") or {}).get("canaries", 0)),
        "negatives": int((SEAM.get("selftest_floor") or {}).get("negatives", 0)),
    }
    # A narrowed run did not run the seam, so it asserts no seam floor.
    if parts:
        for kind, got in (("canaries", seam_fired), ("negatives", seam_silent)):
            bound = W.Bound(
                direction="floor",
                recorded=seam_floor[kind],
                measured=got,
                home="quality/rules.yaml `seam: selftest_floor:`",
                klass=kind,
                subject=f"seam selftest: {kind}",
                word="selftest_floor",
            )
            if bound.breached:
                RUN.broken.append(
                    f"seam: SELFTEST POPULATION SHORT — {bound.breach_clause()}. Either a form "
                    "stopped proving what it claims (the line above names it) or the plan lost "
                    "one: the number lives in `seam.selftest_floor` and not in the length of "
                    "the list, so a form deleted from the list cannot take its own expectation "
                    "with it. Restore the form, or commit the lower number in a diff a reviewer "
                    "reads"
                )
            room = W.room_note(bound)
            if room:
                say("  " + room.replace("\n", "\n  "))
    fired += seam_fired
    silent += seam_silent
    # : Per rule id: how many canary forms fired for IT, and how many of its
    # : negatives stayed silent. Attributed at the point of assertion, never
    # : divided out of a total afterwards.
    per_rule: dict[str, dict[str, int]] = {
        str(rule["id"]): {"canaries": 0, "negatives": 0}
        for rule in RULES
        if rule.get("enabled", True)
    }
    # : The forms this run did NOT plant because the app they need is not in
    # : this deployment. Counted per rule and per kind, printed on the
    # : rule's own line, and subtracted from its recorded population — a world
    # : that is smaller is not a plan that shrank.
    skipped: dict[str, dict[str, int]] = {rid: {"canaries": 0, "negatives": 0} for rid in per_rule}
    absent: dict[str, set[str]] = {rid: set() for rid in per_rule}
    # : The forms this run could NOT JUDGE — a runner that refused, a plant
    # : refused because its path is taken, a tree the rule could not read. A
    # : third state beside fired/dead and silent/fired: each is printed on the
    # : rule's own line with its cause, counted at the foot, and never read as
    # : a canary that died or a negative that held. The refusal itself is
    # : already in `broken` (exit 2) — this is where the line says so.
    unjudged: dict[str, dict[str, int]] = {rid: {"canaries": 0, "negatives": 0} for rid in per_rule}
    unjudged_why: dict[str, list[str]] = {rid: [] for rid in per_rule}

    def not_judged(rid: str, kind: str, cause: str) -> None:
        unjudged[rid][kind] += 1
        if cause not in unjudged_why[rid]:
            unjudged_why[rid].append(cause)

    # : The forms this run did NOT judge because the tree under the plant is
    # : not the shape the form declares it needs (`needs_shape:`). The THIRD
    # : lowering, beside a form whose app this world lacks: printed on the
    # : rule's line with what the tree declares instead, subtracted from the
    # : floor, counted at the foot — never fired, never silent, never unjudged.
    unproducible: dict[str, dict[str, int]] = {
        rid: {"canaries": 0, "negatives": 0} for rid in per_rule
    }
    unproducible_why: dict[str, list[str]] = {rid: [] for rid in per_rule}

    def producible_here(rid: str, kind: str, entry: dict) -> bool:
        """Ask a form's declared shape of the tree under its plant. False: not judged."""
        need = entry.get("needs_shape")
        if not need:
            return True
        verdict, detail = shape_verdict(str(need))
        if verdict == "judged":
            return True
        if verdict == "not producible":
            unproducible[rid][kind] += 1
            why = (
                f"{entry['fixture']} needs {NEEDS_SHAPE_MEANS.get(str(need), need)} and this "
                f"tree declares {detail}"
            )
            if why not in unproducible_why[rid]:
                unproducible_why[rid].append(why)
            return False
        RUN.broken.append(
            f"rule {rid}: COULD NOT LOOK — {entry['fixture']} declares needs_shape: {need} and "
            f"the shape of this tree could not be judged ({detail}); a form whose shape "
            "nobody could read is neither judged nor lowered"
        )
        not_judged(rid, kind, detail)
        return False

    # : The clean tree a form declares it needs (`needs_clean_tree:`), asked
    # : once per run and only if some in-scope form declares one: the census
    # : costs seconds, and a run that judges no such form must not pay them.
    clean_tree_answer: dict[str, tuple[list[str], str]] = {}
    clean_tree_refused: set[str] = set()

    def clean_enough(rid: str, kind: str, entry: dict) -> bool:
        """Ask a form's declared clean tree of the tree at rest. False: could not look."""
        need = entry.get("needs_clean_tree")
        if not need:
            return True
        if need not in clean_tree_answer:
            clean_tree_answer[str(need)] = tree_dirty_on_template_owned()
        dirty, failed = clean_tree_answer[str(need)]
        if not dirty and not failed:
            return True
        cause = failed or (
            f"the tree is dirty on a template-owned path outside the plants: "
            f"{', '.join(dirty)} — commit or stash it; a base-planting form cannot tell your "
            "edit from a product's"
        )
        not_judged(rid, kind, cause)
        if rid not in clean_tree_refused:
            clean_tree_refused.add(rid)
            RUN.broken.append(
                f"rule {rid}: COULD NOT LOOK — {entry['fixture']} declares needs_clean_tree: "
                f"{need} and {cause}"
            )
        return False

    # : Per (rule, via): the rule's raw findings on the UNPLANTED tree, read
    # : once, before its first form. Every form is judged against it.
    baselines: dict[tuple[str, str], tuple[list[Finding], str]] = {}

    def baseline_of(rule: dict, via: str) -> tuple[list[Finding], str]:
        key = (str(rule["id"]), via)
        if key not in baselines:
            baselines[key] = raw_form_findings(rule, via)
        return baselines[key]

    def plant_form(plant: Plant, rid: str, home: Path, entry: dict) -> str:
        """Plant a form and its extra files. '' when held; the cause when refused."""
        for e in entry_forms(entry):
            if not plant.put(home / e["fixture"], e["plant_at"], e["mode"], rid=rid):
                return plant.refusal or f"plant refused: {resolve_plant_text(str(e['plant_at']))}"
        return ""

    # : Per rule id: the seconds its own forms took; the django batch is every member's.
    rule_wall: dict[str, float] = dict.fromkeys(per_rule, 0.0)

    # -- AST + diff canaries and negatives, one fixture at a time ---------------
    for rule in RULES:
        rid = str(rule["id"])
        if not rule.get("enabled", True) or not in_scope(rid):
            continue
        rule_started = time.monotonic()
        for entry in rule.get("canaries") or []:
            via = entry.get("via", "ast")
            gone = W.entry_out_of_world(entry, DISABLED_APPS)
            if gone:
                skipped[rid]["canaries"] += 1
                absent[rid].add(gone)
                continue
            if via == "django":
                continue  # batched probe runs below
            if not clean_enough(rid, "canaries", entry):
                continue
            base_findings, base_cause = baseline_of(rule, via)
            if base_cause:
                not_judged(rid, "canaries", base_cause)
                continue
            plant = Plant()
            try:
                refused = plant_form(plant, rid, fixture_home("canary", rid), entry)
                if refused:
                    not_judged(rid, "canaries", refused)
                    continue
                if not producible_here(rid, "canaries", entry):
                    continue
                planted, cause = raw_form_findings(rule, via)
                if cause:
                    not_judged(rid, "canaries", cause)
                    continue
                added = form_delta(planted, base_findings)
                want = (entry.get("expect") or {}).get("contains")
                hit = any(
                    names_planted(f, resolve_plant_text(str(entry["plant_at"])))
                    and (not want or want in str(f))
                    for f in added
                )
                if hit:
                    fired += 1
                    per_rule[rid]["canaries"] += 1
                else:
                    RUN.broken.append(
                        f"rule {rid}: CANARY DEAD — planted form {entry['fixture']} did not fire"
                    )
            finally:
                plant.restore()
        for entry in rule.get("negatives") or []:
            via = entry.get("via", "ast")
            gone = W.entry_out_of_world(entry, DISABLED_APPS)
            if gone:
                skipped[rid]["negatives"] += 1
                absent[rid].add(gone)
                continue
            if via == "django":
                continue
            if not clean_enough(rid, "negatives", entry):
                continue
            base_findings, base_cause = baseline_of(rule, via)
            if base_cause:
                not_judged(rid, "negatives", base_cause)
                continue
            plant = Plant()
            try:
                refused = plant_form(plant, rid, fixture_home("negative", rid), entry)
                if refused:
                    not_judged(rid, "negatives", refused)
                    continue
                if not producible_here(rid, "negatives", entry):
                    continue
                planted, cause = raw_form_findings(rule, via)
                if cause:
                    not_judged(rid, "negatives", cause)
                    continue
                # A negative fires when its plant ADDED any finding at all. The
                # delta is what makes that total question answerable: before
                # it, the output held the tree's own backlog too, and a
                # negative could only be judged by whether something NAMED it
                # (its plant path, or `expect.contains` for a multi-file
                # fixture pathed elsewhere). The difference holds only what the
                # plant did, so a finding it caused anywhere is a finding.
                hits = form_delta(planted, base_findings)
                if hits:
                    RUN.broken.append(
                        f"rule {rid}: FALSE-POSITIVE REGRESSION — negative {entry['fixture']} "
                        f"fired: {hits[0]}"
                    )
                else:
                    silent += 1
                    per_rule[rid]["negatives"] += 1
            finally:
                plant.restore()
        rule_wall[rid] += time.monotonic() - rule_started

    # -- the Django probe runs: all django canaries in one app, then negatives --
    #
    # One subprocess per corpus rather than one per fixture: each fixture is
    # still asserted individually (its expected id must fire naming its own
    # subject), and a probe app that fails to import fails EVERY assertion —
    # loudly, as exit 2 — rather than any canary quietly passing.
    for kind, is_canary in (("canaries", True), ("negatives", False)):
        # The whole corpus's batch is planted on every run; a narrowed run
        # judges only its named rules' entries in it (`django_batch` says why).
        # Out-of-world forms are already counted in the AST loop above; the two
        # loops must agree about what this run's world holds or the census
        # would count the same form twice, once each way.
        batch = django_batch(kind)
        entries = [(rid, entry) for rid, entry in batch if in_scope(rid)]
        if not entries:
            continue
        if narrowed:
            say(
                f"selftest: narrowed — the {len(entries)} django {kind} of rule(s) "
                f"{', '.join(narrowed)} are judged inside the whole corpus's probe app "
                f"({len(batch)} forms of {len({rid for rid, _ in batch})} rules planted, "
                "the others not judged)"
            )
        plant = Plant()
        try:
            plant.scaffold_probe()
            # A refused plant takes its own form out of the batch — not
            # judged, with its cause — and leaves the rest to be asserted.
            held: list[tuple[str, dict]] = []
            for rid, entry in batch:
                refused = plant_form(plant, rid, fixture_home(kind, rid), entry)
                if refused:
                    not_judged(rid, kind, refused)
                elif in_scope(rid):
                    held.append((rid, entry))
            entries = held
            env = dict(os.environ)
            env.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
            proc = subprocess.run(
                [sys.executable, "manage.py", "check", "--tag", "djb"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            output = proc.stdout + proc.stderr
            error_lines = [ln for ln in output.splitlines() if DJANGO_ID_RE.search(ln)]
            if is_canary:
                for rid, entry in entries:
                    expect = entry.get("expect") or {}
                    wanted_id, wanted_text = expect.get("id", ""), expect.get("contains", "")
                    hit = any(wanted_id in ln and wanted_text in ln for ln in error_lines)
                    if hit:
                        fired += 1
                        per_rule[rid]["canaries"] += 1
                    else:
                        RUN.broken.append(
                            f"rule {rid}: CANARY DEAD — django form {entry['fixture']} did not "
                            f"raise {wanted_id} naming {wanted_text!r}"
                        )
                if not error_lines:
                    RUN.broken.append(
                        "django canary probe produced no djb findings at all — output:\n"
                        + output.strip()[-2000:]
                    )
            else:
                # A negative is silent when nothing in the probe's output NAMES
                # it. The probe app is the signature for a fixture planted into
                # `apps/zzz_canary`; a fixture planted anywhere else names no
                # app at all, so it declares its own signature in
                # `expect.contains` — without one, a negative planted outside
                # the probe app could fire and be counted silent, which is a
                # regression corpus that cannot regress.
                ran = proc.returncode in (0, 1) and (proc.returncode == 0 or error_lines)
                for rid, entry in entries:
                    signature = (entry.get("expect") or {}).get("contains") or PROBE_APP
                    noisy = [ln for ln in error_lines if signature in ln]
                    if noisy:
                        for ln in noisy:
                            RUN.broken.append(
                                f"rule {rid}: FALSE-POSITIVE REGRESSION — the django negative "
                                f"{entry['fixture']} fired: {ln}"
                            )
                    elif ran:
                        silent += 1
                        per_rule[rid]["negatives"] += 1
                if not ran:
                    RUN.broken.append(
                        f"the django negative probe failed to run (exit {proc.returncode}):\n"
                        + output.strip()[-2000:]
                    )
        finally:
            plant.restore()

    # -- the budget mechanism's own canary: a ceiling below reality must fire ----
    budget_started = time.monotonic()
    measured = measure_budgets() if parts else {"service_function_length": {}}
    section = "service_function_length"
    budget_canary = 0
    binding = {k: v for k, v in measured[section].items() if not k.startswith(EXAMPLE_BUDGET_APPS)}
    if binding:
        key, value = next(iter(binding.items()))
        problems = check_budgets({section: {key: value - 1}})
        if any("grew" in p and key in p for p in problems):
            fired += 1
            budget_canary = 1
        else:
            RUN.broken.append(
                "BUDGET CANARY DEAD — a ceiling below the measured value did not fire"
            )
    if parts:
        whole_wall += time.monotonic() - budget_started

    leftover = tree_dirty_under_plants()
    if leftover:
        RUN.broken.append(
            "selftest left the tree dirty under plant paths — restore failed:\n  "
            + "\n  ".join(leftover)
        )

    # -- what each rule can show for itself -------------------------------
    #
    # One line per rule, and then the assertion the line exists for: a rule at
    # or above its recorded population passes and prints; one below it is exit
    # 2 NAMING THE RULE, whether its canaries failed to fire or stopped being
    # planted at all. The aggregate at the foot is what it always was, and it
    # is now the sum of things a reader can check individually.
    # : Kept local, not appended to `RUN.notes`: a self-test run
    # : accumulates every ratchet note from every planted tree, and printing
    # : those would bury the one thing this section exists to say.
    grown: list[str] = []
    say("selftest, by rule (fired/recorded · silent/recorded):")
    for rule in RULES:
        rid = str(rule["id"])
        name = rule.get("name", "")
        if not in_scope(rid):
            continue
        if not rule.get("enabled", True):
            say(f"  rule {rid} {name}: DISABLED — not planted")
            say(f"  rule-wall {rid}: 0.0 s")
            continue
        recorded = selftest_floor(rule)
        got = per_rule[rid]
        # THE ONLY LEGAL LOWERING, and it is paid for by a NAMED APP.
        # The recorded number in rules.yaml never moves — a reviewer still
        # reads the plan's full population in the diff — and what this run
        # expected falls by exactly the forms whose world this deployment does
        # not hold, with the app that took them printed on the same line. A
        # shrink nothing absent paid for is still POPULATION SHORT.
        # THE THIRD LOWERING is paid for by a NAMED SHAPE the same way: a form
        # that declared the shape it needs and found this tree is another one.
        floor = {
            k: max(0, recorded[k] - skipped[rid][k] - unproducible[rid][k])
            for k in ("canaries", "negatives")
        }
        status = (
            "ok"
            if got["canaries"] >= floor["canaries"] and got["negatives"] >= floor["negatives"]
            else "SHORT"
        )
        # A form nobody could judge is neither fired nor silent, and the line
        # says so with the cause rather than reading as a plan that shrank.
        if unjudged[rid]["canaries"] or unjudged[rid]["negatives"]:
            status = f"COULD NOT LOOK ({'; '.join(unjudged_why[rid])})"
        elsewhere = (
            ""
            if not absent[rid]
            else (
                f" · {skipped[rid]['canaries']}c/{skipped[rid]['negatives']}n not in this "
                f"world ({', '.join(sorted(absent[rid]))} disabled; recorded "
                f"{recorded['canaries']}/{recorded['negatives']})"
            )
        )
        not_here = (
            ""
            if not unproducible_why[rid]
            else (
                f" · {unproducible[rid]['canaries']}c/{unproducible[rid]['negatives']}n not "
                f"producible on this shape ({'; '.join(unproducible_why[rid])}; recorded "
                f"{recorded['canaries']}/{recorded['negatives']})"
            )
        )
        say(
            f"  rule {rid} {name}: canaries {got['canaries']}/{floor['canaries']} · "
            f"negatives {got['negatives']}/{floor['negatives']} — {status}{elsewhere}{not_here}"
        )
        say(f"  rule-wall {rid}: {rule_wall.get(rid, 0.0):.1f} s")
        for kind in ("canaries", "negatives"):
            # A form this world could not plant still counts toward the floor:
            # the population is the plan's, and the world only says who paid.
            bound = W.Bound(
                direction="floor",
                recorded=floor[kind],
                measured=got[kind] + unjudged[rid][kind],
                home=f"quality/rules.yaml rule {rid} `selftest_floor:`",
                klass=kind,
                subject=f"rule {rid} selftest: {kind}",
                word="selftest_floor",
            )
            if bound.breached:
                RUN.broken.append(
                    f"rule {rid}: SELFTEST POPULATION SHORT — {got[kind]} of {floor[kind]} "
                    f"recorded {kind} were planted and proved. Either a form died (the line "
                    f"above it says which) or the plan lost one: a canary deleted from "
                    f"`canaries:` takes its own expectation with it, which is why the number "
                    f"lives in `selftest_floor` and not in the length of the list. Restore the "
                    f"form, or commit the lower number in a diff a reviewer reads"
                )
            room = W.room_note(bound) if not unjudged[rid][kind] else None
            if room:
                grown.append(room.replace("\n", "\n  "))
    if parts:
        say(f"  budgets: canary {budget_canary}/1 — the mechanism's own, outside any rule")
    for note in grown:
        say(f"  {note}")
    # CANARY B.5-1, GENERALISED. A canary firing proves the rule can find its
    # subject; this proves the RED it would print is one a reader can act on.
    # Run over the rules whose canaries actually fired on THIS tree, so a rule
    # skipped for an absent world is not asked to explain a red it cannot
    # produce here.
    if parts or member:
        census_started = time.monotonic()
        trailer_census([rid for rid, got in per_rule.items() if got["canaries"] > 0])
    if parts:
        cli_census()
        whole_wall += time.monotonic() - census_started
        say(
            f"  rule-wall {WHOLE_PARTS}: {whole_wall:.1f} s — the legs, the seam, the budget "
            "canary and the censuses"
        )
    not_judged_total = sum(u["canaries"] + u["negatives"] for u in unjudged.values())
    not_judged_rules = [rid for rid, u in unjudged.items() if u["canaries"] or u["negatives"]]
    foot = (
        f"selftest: {fired} canary forms fired · {silent} negatives stayed silent · tree restored"
    )
    if not_judged_total:
        foot += (
            f" · {not_judged_total} forms could not be judged "
            f"(rules: {', '.join(not_judged_rules)})"
        )
    unproducible_total = sum(u["canaries"] + u["negatives"] for u in unproducible.values())
    unproducible_rules = [rid for rid, u in unproducible.items() if u["canaries"] or u["negatives"]]
    if unproducible_total:
        foot += (
            f" · {unproducible_total} forms not producible on this shape "
            f"(rules: {', '.join(unproducible_rules)})"
        )
    SELFTEST_RESULT["unproducible"] = unproducible_total
    say(foot)


from quality.engine.cli import BacklogCensus, backlog_census  # noqa: E402
from quality.engine.explain import trailer_census  # noqa: E402
from quality.engine.memo import cli_census  # noqa: E402
from quality.engine.plants import (  # noqa: E402
    NARROWED,
    Plant,
    plant_collision_leg,
    plant_collision_run,
    plant_namespace_line,
    prime_plant_resolution,
    resolve_plant_text,
    stale_plants,
    tree_dirty_on_template_owned,
    tree_dirty_under_plants,
)
from quality.engine.rules import (  # noqa: E402
    _git_at,
    duplicate_id_findings,
    engine_fixture_findings,
    entry_forms,
    fixture_dir_findings,
    fixture_files_on_disk,
    frozen_base,
    frozen_declaration_problems,
    frozen_judgement,
    frozen_problems,
    orphan_fixture_findings,
    plan_forms,
    recorded_number,
    text_at,
)
from quality.engine.run import (  # noqa: E402
    EXAMPLE_BUDGET_APPS,
    all_overrides,
    apply_overrides,
    apply_ratchets,
    check_budgets,
    measure_budgets,
    recording_sha,
    run_rule,
)
from quality.engine.world import (  # noqa: E402
    _OVERRIDE_RES,
    CANARY_DIR,
    COULD_NOT_LOOK,
    DISABLED_APPS,
    DJANGO_ID_RE,
    DRAWER_RATCHET_PARTS,
    ENGINE_FIXTURES,
    LOCAL_DOC,
    MEMBER_FLOOR_SOURCES,
    NEGATIVE_DIR,
    OPTIONAL_APPS,
    PLATFORM_APPS,
    PROBE_APP,
    RESIDENCE_BACKLOG,
    RULES,
    RULES_BY_ID,
    RUN,
    SCOPE_KINDS,
    SEAM,
    VENDORED_VALVE_FIXTURE,
    _merge_local_ratchets,
    fixture_home,
    id_shape_problem,
    is_frozen,
    is_template_id,
    member_rules,
    override_re,
    ratchet_home,
    say,
    violation_rule,
    world_module,
)
