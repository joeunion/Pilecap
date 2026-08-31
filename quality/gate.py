"""The house-rules gate. Rules are data (quality/rules.yaml); this is the engine.

    python -m quality.gate consistency + live scan + floors + budgets
                                         + the Django system-check leg
    python -m quality.gate --diff REF all of the above + the diff-aware checks
                                         against REF
    python -m quality.gate --selftest plant every canary through the real
                                         scope and demand it fires for ITS rule;
                                         plant every negative and demand silence;
                                         restore everything, whatever happens

Exit codes: 0 clean · 1 violations · 2 ENFORCEMENT BROKEN (dead canary, noisy
negative, unbound scope/floor, consistency failure, unknown flag, dirty tree
under a plant path). 2 outranks a pass — a gate that is broken must never read
as a gate that passed.

Overrides: a line carrying `# rule-<id>: <reason>` — on the flagged line or in
the contiguous comment block directly above it — suppresses that rule there.
Every override is counted and printed as a standing section on every run. An
override whose reason is missing or too short to be one is itself a violation.

Ratchets: a rule whose subject already has a backlog records the SIZE of that
backlog in `rules.yaml`, per class of finding — `ratchets: {selectors: 9}`. The
count may shrink and never grow: at or below the number the findings are a
standing backlog, printed as notes; one over it and every finding in that class
is a violation naming the growth. Shrinking never tightens the number by
itself — a human reads the note and commits the lower one, in a diff somebody
sees. A class with no entry is ratcheted at zero, which is what "clean" means.

Self-test plants into the REAL tree (create/append per fixture, try/finally
restore), because a canary proven against a copy proves the copy. It therefore
refuses to run when the tree is already dirty under any plant path: it could
not tell its own plants from your work, and could not restore honestly.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quality import checks as C  # noqa: E402
from quality import worlds as W  # noqa: E402
from quality.checks import FLOOR_PROXIES, REGISTRY, CheckResult, Finding  # noqa: E402

_DOC: dict = yaml.safe_load((ROOT / "quality" / "rules.yaml").read_text())
RULES: list[dict] = _DOC["rules"]
RULES_BY_ID: dict[str, dict] = {str(r["id"]): r for r in RULES}

# --- the world this run holds ---------------------------------------------------
#
# Read once, at import, exactly as `config/settings/base.py:117` reads it: a
# running process does not re-derive its world and neither does a gate run. Both
# are DECLARATIONS — `optional = True` on an `AppConfig`, and the deployment's
# `DJB_DISABLED_APPS` — and `quality/worlds.py` carries the whole argument for
# why neither is a list in this file.
OPTIONAL_APPS: frozenset[str] = W.optional_app_labels(ROOT)
DISABLED_APPS: frozenset[str] = W.disabled_app_labels()

# THE SELF-TEST'S OWN BACKLOG, and the only thing standing between "a rule that
# an environment variable can delete" and exit 2. Measured over the whole rule
# set; the members are printed by name on every self-test run. Same grammar as
# `ratchets:` (see this module's header): it may shrink and never grow, one over
# it turns the whole census into violations, and a human commits the lower
# number in a diff somebody reads. Nothing tightens by itself.
RESIDENCE_BACKLOG: int = int(_DOC.get("selftest_residence_backlog") or 0)
CANARY_DIR = ROOT / "quality" / "canary"
NEGATIVE_DIR = ROOT / "quality" / "negative"
BUDGETS_PATH = ROOT / "quality" / "budgets.yaml"

PROBE_APP = "zzz_canary"
PROBE_DIR = ROOT / "apps" / PROBE_APP
PROBE_APPS_PY = f"""from django.apps import AppConfig


class ZzzCanaryConfig(AppConfig):
    name = "apps.{PROBE_APP}"
    depends_on: tuple[str, ...] = ("core", "accounts")
"""

OVERRIDE_RE = re.compile(r"#\s*rule-(\d+)\b:?\s*(.*)$")
MIN_REASON = 12  # long enough to force a clause; short enough that a real reason clears it

broken: list[str] = []
violations: list[str] = []
notes: list[str] = []


def say(msg: str) -> None:
    print(msg)


# --- overrides -----------------------------------------------------------------


def _file_lines(path: Path) -> list[str]:
    try:
        return path.read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        return []


def override_at(path: Path, line: int, rule_id: str) -> str | None:
    """The reason claimed for rule_id at this line, or None when none is claimed.

    The marker counts on the flagged line itself, or in the CONTIGUOUS comment
    block directly above it — never further away, so an exemption cannot drift
    onto code nobody thought about.
    """
    lines = _file_lines(path)
    if not lines or line < 1 or line > len(lines):
        return None
    m = OVERRIDE_RE.search(lines[line - 1])
    if m and m.group(1) == rule_id:
        return m.group(2).strip()
    i = line - 2
    while i >= 0 and lines[i].strip().startswith("#"):
        m = OVERRIDE_RE.search(lines[i])
        if m and m.group(1) == rule_id:
            return m.group(2).strip()
        i -= 1
    return None


def all_overrides() -> list[tuple[str, str, int, str]]:
    """(rule_id, relpath, line, reason) for every override marker in the tree."""
    found: list[tuple[str, str, int, str]] = []
    for sub in ("apps", "config"):
        base = ROOT / sub
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            for lineno, text in enumerate(_file_lines(path), start=1):
                m = OVERRIDE_RE.search(text)
                if m:
                    found.append(
                        (m.group(1), str(path.relative_to(ROOT)), lineno, m.group(2).strip())
                    )
    return found


def apply_overrides(rule_id: str, findings: list[Finding]) -> tuple[list[Finding], list[Finding]]:
    """(kept, suppressed). A bare override becomes its own finding, kept."""
    kept: list[Finding] = []
    suppressed: list[Finding] = []
    for finding in findings:
        reason = override_at(ROOT / finding.path, finding.line, rule_id)
        if reason is None:
            kept.append(finding)
        elif len(reason) >= MIN_REASON:
            suppressed.append(finding)
        else:
            kept.append(
                Finding(
                    finding.path,
                    finding.line,
                    f"override `# rule-{rule_id}` with no reason — an escape hatch nobody has to "
                    f"justify is an off switch (suppressing: {finding.msg})",
                )
            )
    return kept, suppressed


def apply_ratchets(rule: dict, kept: list[Finding]) -> list[Finding]:
    """Findings within a recorded backlog are notes; one over it, all of them fail.

    Counted per CLASS (`Finding.klass`), so a backlog of nine badly named
    selectors cannot pay for one badly named model. A class with no recorded
    ratchet is ratcheted at zero — the ordinary case, where the first finding
    is a violation.
    """
    rid = str(rule["id"])
    recorded = rule.get("ratchets") or {}
    by_class: dict[str, list[Finding]] = {}
    for finding in kept:
        by_class.setdefault(finding.klass, []).append(finding)
    out: list[Finding] = []
    for klass, findings in sorted(by_class.items()):
        allowed = int(recorded.get(klass, 0)) if klass else 0
        label = klass or "(rule)"
        if len(findings) > allowed:
            if allowed:
                out.append(
                    Finding(
                        "quality/rules.yaml",
                        0,
                        f"class {label!r} is at {len(findings)} violations, past the recorded "
                        f"ratchet of {allowed} — a backlog may shrink and never grow. Fix the "
                        f"new one, or reduce another; raising the number is a diff a reviewer "
                        f"reads. The whole class follows:",
                        klass,
                    )
                )
            out.extend(findings)
        else:
            notes.append(
                f"rule {rid} ratchet: class {label} at {len(findings)} of the recorded "
                f"{allowed} — standing backlog, not a pass; nothing new landed."
            )
            for finding in findings:
                notes.append(f"    backlog {finding}")
            if len(findings) < allowed:
                notes.append(
                    f"    rule {rid}: class {label} is now BELOW its ratchet of {allowed} — "
                    f"a human may commit {len(findings)} to quality/rules.yaml; nothing "
                    "tightens by itself."
                )
    for klass, allowed in sorted(recorded.items()):
        # A class that has gone all the way to clean is the one worth saying
        # out loud, and it is the one no finding would mention.
        if str(klass) not in by_class and int(allowed) > 0:
            notes.append(
                f"rule {rid} ratchet: class {klass} has NO violations left against a "
                f"recorded {allowed} — a human may commit 0 to quality/rules.yaml."
            )
    return out


# --- running one rule ----------------------------------------------------------


def run_rule(rule: dict, *, floors: bool = True) -> tuple[list[Finding], dict]:
    """The rule's AST check + override + ratchet pipeline. Returns (violations, targets)."""
    rid = str(rule["id"])
    targets: dict = {}
    findings: list[Finding] = []
    impl = rule.get("check")
    if impl:
        result: CheckResult = REGISTRY[impl](ROOT, rule)
        targets.update(result.targets_matched)
        findings.extend(result.findings)
    proxy = rule.get("floor_proxy")
    if proxy:
        targets.update(FLOOR_PROXIES[proxy](ROOT, rule).targets_matched)
    kept, _suppressed = apply_overrides(rid, findings)
    kept = apply_ratchets(rule, kept)
    if floors:
        for key, floor in (rule.get("floors") or {}).items():
            matched = targets.get(key, 0)
            # A floor that counts registry members an ABSENT app contributed is
            # lowered by exactly what that app contributed, and the message says
            # so. Everything else keeps the recorded number: a smaller
            # world is the one legal reason a floor may fall, and it has to be
            # paid for by a named app.
            expected = W.derived_floor(rule, key, int(floor), DISABLED_APPS)
            if matched < expected:
                paid = (
                    ""
                    if expected == int(floor)
                    else (
                        f" (recorded {floor}, lowered to {expected} — "
                        f"{', '.join(sorted(DISABLED_APPS))} is not in this deployment)"
                    )
                )
                broken.append(
                    f"rule {rid}: UNBOUND — {key}={matched} below floor {expected}{paid}; "
                    "the check may be watching nothing"
                )
    return kept, targets


# --- the Django system-check leg -------------------------------------------------

DJANGO_ID_TO_RULE: dict[str, str] = {}
for _rule in RULES:
    for _cid in _rule.get("django_check_ids") or []:
        DJANGO_ID_TO_RULE[str(_cid)] = str(_rule["id"])


def run_django_leg() -> list[tuple[str, str]]:
    """(rule_id, message) per djb error from `manage.py check --tag djb`.

    settings=test, no database. A non-djb crash in the leg is enforcement
    broken, not a pass.
    """
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
    found: list[tuple[str, str]] = []
    for line in output.splitlines():
        m = re.search(r"\((djb\.[EW]\d+)\)", line)
        if m:
            rule_id = DJANGO_ID_TO_RULE.get(m.group(1), m.group(1))
            found.append((rule_id, line.strip()))
    if proc.returncode != 0 and not found:
        broken.append(
            f"the Django check leg failed without a djb finding (exit {proc.returncode}) — "
            f"enforcement is broken, not clean:\n{output.strip()[-2000:]}"
        )
    return found


# --- budgets: the rising floors --------------------------------------------------


def _docstring_lines(node: object) -> int:
    """How many source lines the first statement spends being a docstring.

    The docstring is the first Expr-of-a-str-Constant statement in the body —
    the same thing `ast.get_docstring` reads — and nothing else. A module whose
    first statement is a string that is NOT a docstring does not exist in
    Python's grammar, so there is no ambiguity to resolve here.
    """
    import ast as _ast

    body = getattr(node, "body", None)
    if not body:
        return 0
    first = body[0]
    if (
        isinstance(first, _ast.Expr)
        and isinstance(first.value, _ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return (first.end_lineno or first.lineno) - first.lineno + 1
    return 0


def measure_budgets() -> dict[str, dict[str, int]]:
    """The measured value of every budget subject, keyed as budgets.yaml keys it.

    `service_function_length` measures the BODY MINUS THE DOCSTRING: the
    span from `def` to the last line, less whatever the docstring spends. The
    ceiling exists to catch a service growing a SECOND JOB, and prose is the
    opposite of that — a function that shrinks by ten lines of code while its
    author writes ten lines explaining why measured flat under the old span, so
    the instrument could not see the thing it was pointed at. Rule-mandated
    comment lines (13's `# authz:`, 26's `# reach:`) still count, deliberately:
    "a rule-mandated block" is an open set, and an unfalsifiable population is
    the one thing the checklist forbids an instrument to carry.
    """
    return {
        section: {key: value for key, (value, _label) in subjects.items()}
        for section, subjects in _measure_budgets_detailed().items()
    }


def _measure_budgets_detailed() -> dict[str, dict[str, tuple[int, str]]]:
    """Every budget subject as (measured value, the label that NAMES it).

    The label is what lets a refusal say *which function* grew. `service_
    function_length` is keyed per FILE (the ruling: re-keying per function would
    make every new function a new-subject red and rewrite budgets.yaml's
    contract for a message-sized win), so without a label the message can only
    point at a module and leave the reader to go and find the longest thing in
    it.
    """
    import ast as _ast

    service_lengths: dict[str, tuple[int, str]] = {}
    for path in sorted(ROOT.glob("apps/*/services.py")):
        tree = C._parse(path)
        if tree is None:
            continue
        longest, label = 0, ""
        for node in tree.body:
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                end = node.end_lineno or node.lineno
                measured = end - node.lineno + 1 - _docstring_lines(node)
                if measured > longest:
                    longest = measured
                    label = f"{node.name} (lines {node.lineno}-{end})"
        service_lengths[str(path.relative_to(ROOT))] = (longest, label)
    out_fields: dict[str, tuple[int, str]] = {}
    for path in sorted(ROOT.glob("apps/*/schemas.py")):
        tree = C._parse(path)
        if tree is None:
            continue
        for node in _ast.walk(tree):
            if isinstance(node, _ast.ClassDef) and node.name.endswith("Out"):
                key = f"{path.relative_to(ROOT)}::{node.name}"
                end = node.end_lineno or node.lineno
                out_fields[key] = (
                    sum(1 for s in node.body if isinstance(s, _ast.AnnAssign)),
                    f"{node.name} (lines {node.lineno}-{end})",
                )
    return {"service_function_length": service_lengths, "out_schema_fields": out_fields}


def check_budgets(recorded: dict | None = None) -> list[str]:
    if recorded is None:
        recorded = yaml.safe_load(BUDGETS_PATH.read_text()) if BUDGETS_PATH.exists() else None
    if not recorded:
        return ["quality/budgets.yaml is missing or empty — the rising floors are not recorded"]
    problems: list[str] = []
    for section, subjects in _measure_budgets_detailed().items():
        ceilings = recorded.get(section) or {}
        for key, (value, label) in subjects.items():
            named = f"{key} — {label}" if label else key
            ceiling = ceilings.get(key)
            if ceiling is None:
                problems.append(
                    f"budget: {section} has no recorded ceiling for {named} (measured {value}) — "
                    "a new subject fails until a human measures it and commits the number. "
                    f"The line to paste under `{section}:` in quality/budgets.yaml:\n"
                    f"  {key}: {value}"
                )
            elif value > int(ceiling):
                problems.append(
                    f"budget: {section} {named} grew to {value}, past the recorded ceiling "
                    f"{ceiling} — shrink it, or raise the ceiling in quality/budgets.yaml "
                    "in a diff a reviewer sees. The line to paste, verbatim:\n"
                    f"  {key}: {value}"
                )
            elif value < int(ceiling):
                notes.append(
                    f"budget note: {section} {named} measured {value}, below its ceiling "
                    f"{ceiling} — a human may commit the lower number:\n"
                    f"  {key}: {value}"
                )
    return problems


# --- consistency -----------------------------------------------------------------


def _scope_paths(node: object, trail: tuple[str, ...] = ()) -> Iterator[tuple[str, str]]:
    """Every `path:` a rule's scope names, with the key trail that names it.

    Walked structurally rather than by a list of known keys, so a rule that
    invents a new allow-list shape is covered on the day it is written.
    """
    if isinstance(node, dict):
        value = node.get("path")
        if isinstance(value, str) and value.strip():
            yield ".".join(trail) or "scope", value.strip()
        for key, child in node.items():
            if key != "path":
                yield from _scope_paths(child, (*trail, str(key)))
    elif isinstance(node, list):
        for child in node:
            yield from _scope_paths(child, trail)


def registry_floor_consistency(rule: dict) -> None:
    """A floor over a registry an optional app feeds must say what it counts.

    `probed_paths: 11` is a fact about eleven executed registry entries — and
    six of rule 35's twenty-one entries are the worked example's. Take the
    worked example out and the same number is a fact about a world that no
    longer exists, so the floor reads as a broken gate rather than as a smaller
    tree. The repair is not a lower number (that would lower it for everybody);
    it is a DECLARED BASIS, from which the expectation is derived per run.

    Required only where it bites: a registry with no optional-app member feeds
    no world-dependent number, and taxing it would be a rule about nothing. The
    day such a member arrives, this refuses — which is the day the floor
    actually became world-dependent.
    """
    rid = str(rule["id"])
    registry = rule.get("registry") or []
    declared = rule.get("registry_floors") or {}
    floors = rule.get("floors") or {}
    if not registry:
        if declared:
            broken.append(f"rule {rid}: registry_floors declared with no registry to feed them")
        return
    for key, basis in declared.items():
        if str(basis) not in W.REGISTRY_BASES:
            broken.append(
                f"rule {rid}: registry_floors {key!r} names basis {basis!r}, which is not "
                f"one of {', '.join(sorted(W.REGISTRY_BASES))}"
            )
        if key not in floors:
            broken.append(
                f"rule {rid}: registry_floors names {key!r}, which is not one of this "
                "rule's floors — a derivation for a number nobody reads"
            )
    if not any(W.registry_entry_app(e) in OPTIONAL_APPS for e in registry):
        return
    for key in floors:
        if key not in declared:
            broken.append(
                f"rule {rid}: floor {key!r} is pinned to {floors[key]} over a registry an "
                f"OPTIONAL app feeds ({', '.join(sorted(OPTIONAL_APPS))}) and does not say "
                "what it counts. Declare `registry_floors: {"
                f"{key}: <basis>"
                "}` so the expectation is derived from the apps this deployment "
                f"actually holds — one of {', '.join(sorted(W.REGISTRY_BASES))}; `opaque` "
                "is the honest answer where the registry cannot count it, and carries its "
                "reason on the rule"
            )


def consistency() -> None:
    seen_ids: set[str] = set()
    for rule in RULES:
        rid = str(rule["id"])
        if rid in seen_ids:
            broken.append(f"rule {rid}: duplicate id")
        seen_ids.add(rid)
        impl = rule.get("check")
        if impl and impl not in REGISTRY:
            broken.append(f"rule {rid}: check impl {impl!r} not in registry")
        if not impl and not rule.get("django_check_ids") and not rule.get("diff"):
            broken.append(f"rule {rid}: no mechanism at all — not a rule, a wish")
        proxy = rule.get("floor_proxy")
        if proxy and proxy not in FLOOR_PROXIES:
            broken.append(f"rule {rid}: floor proxy {proxy!r} not in registry")
        doc = rule.get("doc") or {}
        doc_path = ROOT / doc.get("file", "")
        if not doc_path.is_file():
            broken.append(f"rule {rid}: doc file {doc.get('file')} missing")
        elif str(doc.get("contains", "")).lower() not in doc_path.read_text().lower():
            broken.append(
                f"rule {rid}: doc {doc['file']} no longer states the rule (anchor "
                f"{doc['contains']!r} missing)"
            )
        canaries = rule.get("canaries") or []
        if len(canaries) < 2:
            broken.append(
                f"rule {rid}: fewer than two canary forms — a check that can't "
                "demonstrably fail two ways is decoration"
            )
        if not rule.get("negatives"):
            broken.append(f"rule {rid}: no negatives — restraint unproven")
        if not rule.get("floors"):
            broken.append(f"rule {rid}: no floors — green-because-empty would read as a pass")
        # the recorded self-test population. Required rather than
        # defaulted, because a rule that arrives without one is ratcheted at
        # zero and its canaries could all stop being planted in silence — which
        # is the exact failure this key exists to end.
        declared = rule.get("selftest_floor")
        if not isinstance(declared, dict) or {"canaries", "negatives"} - set(declared):
            broken.append(
                f"rule {rid}: no selftest_floor — record how many canary forms and negatives "
                "this rule's plan holds, so a plan that quietly loses one is exit 2 and not a "
                "smaller total nobody reads"
            )
        else:
            for kind, count in declared.items():
                try:
                    if int(count) < 0:
                        raise ValueError
                except (TypeError, ValueError):
                    broken.append(
                        f"rule {rid}: selftest_floor {kind!r} is {count!r}, which is not a count"
                    )
        for klass, count in (rule.get("ratchets") or {}).items():
            # A ratchet nobody can read is an off switch with extra steps.
            if not str(klass).strip():
                broken.append(f"rule {rid}: a ratchet with no class name")
            try:
                if int(count) < 0:
                    raise ValueError
            except (TypeError, ValueError):
                broken.append(f"rule {rid}: ratchet {klass!r} is {count!r}, which is not a count")
        if not str(rule.get("does_not_cover", "")).strip():
            broken.append(f"rule {rid}: no does_not_cover — an undeclared blind spot")
        registry_floor_consistency(rule)
        for kind, base in (("canaries", CANARY_DIR), ("negatives", NEGATIVE_DIR)):
            for entry in rule.get(kind) or []:
                for e in [entry, *(entry.get("extra_files") or [])]:
                    if not (base / rid / e["fixture"]).is_file():
                        broken.append(f"rule {rid}: {kind[:-1]} fixture {e['fixture']} missing")
                # A form may DECLARE the world it needs when its plant path
                # cannot say so, and a declaration naming an app that is not on
                # this tree is a plan for a world nobody can enter.
                declared = entry.get("needs_app")
                if declared and not (ROOT / "apps" / str(declared)).is_dir():
                    broken.append(
                        f"rule {rid}: {kind[:-1]} {entry['fixture']} declares "
                        f"`needs_app: {declared}`, which is not an app under apps/"
                    )
        for cid in rule.get("django_check_ids") or []:
            checks_src = (ROOT / "apps" / "core" / "checks.py").read_text()
            if str(cid) not in checks_src:
                broken.append(
                    f"rule {rid}: django check id {cid} not present in apps/core/checks.py"
                )
        # every path a rule's SCOPE names must resolve on this
        # tree. A scope entry is read as a fact about today — "this file may
        # import the engine", "this tree may name the credential" — and rule
        # 33's own does_not_cover already declared it cannot tell whether an
        # allow-listed module still DESERVES to be. This is the sibling it was
        # missing: whether it EXISTS. Two of rule 33's five allow_import
        # entries named files no rung had written yet, so the statement a
        # reader was handed as true today described a tree that did not exist,
        # and nothing anywhere could say so. A forward-looking entry is now
        # added by the rung that lands the file, which keeps the allow-list a
        # diff rather than a discovery (the same discipline rule 11's
        # `extra_modules` comments record about themselves).
        for where, path in _scope_paths(rule.get("scope") or {}):
            if not (ROOT / path).exists():
                broken.append(
                    f"rule {rid}: scope {where} names {path}, which does not exist on this "
                    "tree — an allow-list entry is a fact about today, not a plan; add it in "
                    "the rung that writes the file"
                )


# --- planting --------------------------------------------------------------------


# --- plant placeholders: a fixture may not freeze the tree's state ------------
#
# THE INCIDENT (P7, the SRCH-FIX push). Rule 6's negative plants "one honest new
# leaf on top of the real one" into `apps/example/migrations/`, and all three of
# its moving parts were TYPED: the parent in the fixture, the number in
# `plant_at`, and the marker in its extra file. R-e landed
# `0011_widget_search_vector`, so the plant stopped being a successor and became
# a SECOND LEAF — the negative fired, the self-test went exit 2, and the push was
# blocked by a fixture rather than by the tree.
#
# THIS WAS THE FOURTH TIME. rules.yaml's own comment on that entry said so
# ("CORE-11 (0010) is the third rung to pay this"), and paying it a fifth time
# means every rung that touches `apps/example` — the designated search-adoption
# app, which will keep growing migrations — owes an edit to a file in `quality/`
# that has nothing to do with what it built. That is the collision the whole
# discovery discipline exists to avoid, pointed at the gate instead of at
# `config/`.
#
# THE FIX IS DERIVATION, the same answer the rest of this engine already gives:
# a fixture names what it wants and the resolver reads today's tree.
#
# {{leaf:<app>}} the app's current single migration leaf
# {{after:<app>:<slug>}} the next number after it, plus <slug> —
# `0011_widget_search_vector` -> `0012_neg_leaf`
#
# Substituted in BOTH `plant_at` and fixture CONTENT, because a plant that
# derived its parent but kept a typed filename would still fork the graph on the
# number alone. An unknown placeholder, or an app whose graph does not have
# exactly one leaf, is exit 2 (could-not-look) — never a silent literal.
PLACEHOLDER = re.compile(r"\{\{(leaf|after):([A-Za-z_][A-Za-z0-9_]*)(?::([A-Za-z0-9_]+))?\}\}")

# : Resolved ONCE, against the unplanted tree, and cached. Deliberate: the
# : resolver reads the migration graph, and rule 6's canaries plant INTO that
# : graph — a resolver that re-read per plant would be reading a tree an earlier
# : plant had already moved. `selftest` primes it before the first plant, and
# : `tree_dirty_under_plants` (which runs first, and refuses a dirty tree) is what
# : makes "unplanted" a fact rather than a hope.
_RESOLVED: dict[str, str] = {}
_RESOLVED_PRIMED = False


def resolve_plant_text(text: str) -> str:
    """Every `{{...}}` in a plant_at or a fixture body, replaced from today's tree."""

    def one(match: re.Match[str]) -> str:
        kind, app_label, slug = match.group(1), match.group(2), match.group(3)
        leaf = _RESOLVED.get(app_label)
        if leaf is None:
            leaf = C.app_migration_leaf(ROOT, app_label)
            if leaf is None:
                broken.append(
                    f"plant placeholder {match.group(0)}: apps/{app_label} does not have "
                    "exactly one migration leaf on this tree, so a fixture cannot be "
                    "chained onto it. The self-test could not look — it has not passed"
                )
                return match.group(0)
            _RESOLVED[app_label] = leaf
        if kind == "leaf":
            return leaf
        number, _, _rest = leaf.partition("_")
        try:
            nxt = f"{int(number) + 1:04d}"
        except ValueError:
            broken.append(
                f"plant placeholder {match.group(0)}: the leaf {leaf!r} does not begin with "
                "a migration number, so there is no 'next' to derive"
            )
            return match.group(0)
        return f"{nxt}_{slug}" if slug else nxt

    return PLACEHOLDER.sub(one, text)


def prime_plant_resolution() -> None:
    """Read the tree's leaves once, before anything is planted into it."""
    global _RESOLVED_PRIMED
    if _RESOLVED_PRIMED:
        return
    _RESOLVED_PRIMED = True
    for rule in RULES:
        for kind in ("canaries", "negatives"):
            for entry in rule.get(kind) or []:
                for e in [entry, *(entry.get("extra_files") or [])]:
                    resolve_plant_text(str(e["plant_at"]))
                    fixture = (
                        (CANARY_DIR if kind == "canaries" else NEGATIVE_DIR)
                        / str(rule["id"])
                        / e["fixture"]
                    )
                    if fixture.is_file():
                        resolve_plant_text(fixture.read_text())


class Plant:
    """Plant fixture files into the real tree; restore exactly, whatever happens."""

    def __init__(self) -> None:
        self.saved: dict[Path, bytes | None] = {}
        self.made_dirs: list[Path] = []

    def _remember(self, target: Path) -> None:
        if target not in self.saved:
            self.saved[target] = target.read_bytes() if target.exists() else None

    def put(self, fixture: Path, plant_at: str, mode: str) -> None:
        plant_at = resolve_plant_text(plant_at)
        target = ROOT / plant_at
        self._remember(target)
        parent = target.parent
        missing: list[Path] = []
        while not parent.exists():
            missing.append(parent)
            parent = parent.parent
        for d in reversed(missing):
            d.mkdir()
            self.made_dirs.append(d)
        content = resolve_plant_text(fixture.read_text())
        if mode == "append":
            base = target.read_text() if target.exists() else ""
            target.write_text(base + content)
        else:
            target.write_text(content)

    def scaffold_probe(self) -> None:
        self._remember(PROBE_DIR / "__init__.py")
        self._remember(PROBE_DIR / "apps.py")
        PROBE_DIR.mkdir(exist_ok=True)
        self.made_dirs.append(PROBE_DIR)
        (PROBE_DIR / "__init__.py").write_text("")
        (PROBE_DIR / "apps.py").write_text(PROBE_APPS_PY)

    def restore(self) -> None:
        for target, original in self.saved.items():
            if original is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(original)
        for d in reversed(self.made_dirs):
            if d.exists() and not any(d.iterdir()):
                d.rmdir()
        if PROBE_DIR.exists():
            shutil.rmtree(PROBE_DIR, ignore_errors=True)
        self.saved.clear()
        self.made_dirs.clear()


def plant_paths() -> list[str]:
    """Every path a plant can touch, RESOLVED — the dirty check reads these.

    Resolved rather than literal because `git status --porcelain -- <path>` on a
    `{{after:example:neg_leaf}}.py` matches nothing at all: the refusal that
    protects the tree would go on saying "clean" about a path it was no longer
    naming (N-Q32b).
    """
    prime_plant_resolution()
    paths: set[str] = {f"apps/{PROBE_APP}"}
    for rule in RULES:
        for kind in ("canaries", "negatives"):
            for entry in rule.get(kind) or []:
                for e in [entry, *(entry.get("extra_files") or [])]:
                    paths.add(resolve_plant_text(str(e["plant_at"])))
    return sorted(paths)


def tree_dirty_under_plants() -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain", "--", *plant_paths()],
        capture_output=True,
        text=True,
        check=False,
    )
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


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
    budget ceilings: below it is exit 2 naming the rule, above it is a note
    saying a human may commit the higher number. Growth is free; a plan that
    quietly loses a form is not.
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
    census = W.residence_census(rules, OPTIONAL_APPS)
    lines = [
        f"rule {rid}: every canary form this rule has plants in apps/{app}, which declares "
        f"`optional = True` — a deployment that leaves {app} out leaves this rule unable to "
        "demonstrate a failure at all. Re-home one form into an app the product cannot "
        "remove, or say in the rule why the subject only exists there"
        for rid, app in census
    ]
    if len(census) <= RESIDENCE_BACKLOG:
        return []
    return [
        f"selftest residence is at {len(census)} rules, past the recorded backlog of "
        f"{RESIDENCE_BACKLOG} — a rule whose whole canary plan lives in an optional app may "
        f"shrink and never grow. The whole census follows:",
        *lines,
    ]


def residence_leg() -> None:
    """Run the residence census, and prove the census itself can fail.

    THE MECHANISM'S OWN CANARY, in the shape the budget canary already uses
    below: this leg's subject is `rules.yaml` data rather than the tree, so its
    forms are RULE-SHAPED and asserted directly. Planting a file could not
    exercise it — there is no file whose presence makes a rule's canary plan
    live in one app.
    """
    census = W.residence_census(RULES, OPTIONAL_APPS)
    for line in residence_findings(RULES):
        broken.append(line)
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
        if len(census) < RESIDENCE_BACKLOG:
            say(
                f"    a human may commit {len(census)} to quality/rules.yaml "
                "(selftest_residence_backlog); nothing tightens by itself."
            )

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
        broken.append(
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
        broken.append(
            "RESIDENCE FALSE-POSITIVE REGRESSION — a rule with one canary form outside "
            f"apps/{optional_app} was counted into the residence census"
        )


def selftest() -> None:
    # Read the tree's migration leaves BEFORE anything is planted into it, and
    # stop if any placeholder could not be resolved: a self-test that guessed a
    # parent would be proving something about a graph it invented.
    prime_plant_resolution()
    if broken:
        return
    dirty = tree_dirty_under_plants()
    if dirty:
        broken.append(
            "selftest refused: the tree is dirty under plant paths — it could not tell "
            "its plants from your work, or restore honestly:\n  " + "\n  ".join(dirty)
        )
        return

    residence_leg()

    fired = 0
    silent = 0
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

    # -- AST + diff canaries and negatives, one fixture at a time ---------------
    for rule in RULES:
        rid = str(rule["id"])
        if not rule.get("enabled", True):
            continue
        for entry in rule.get("canaries") or []:
            via = entry.get("via", "ast")
            gone = W.entry_out_of_world(entry, DISABLED_APPS)
            if gone:
                skipped[rid]["canaries"] += 1
                absent[rid].add(gone)
                continue
            if via == "django":
                continue  # batched probe runs below
            plant = Plant()
            try:
                plant.put(CANARY_DIR / rid / entry["fixture"], entry["plant_at"], entry["mode"])
                for extra in entry.get("extra_files") or []:
                    plant.put(CANARY_DIR / rid / extra["fixture"], extra["plant_at"], extra["mode"])
                if via == "diff":
                    result = C.diff_checks(ROOT, "HEAD", RULES_BY_ID).get(rid, CheckResult())
                    kept, _ = apply_overrides(rid, result.findings)
                else:
                    kept, _ = run_rule(rule, floors=False)
                want = (entry.get("expect") or {}).get("contains")
                hit = any(
                    names_planted(f, resolve_plant_text(str(entry["plant_at"])))
                    and (not want or want in str(f))
                    for f in kept
                )
                if hit:
                    fired += 1
                    per_rule[rid]["canaries"] += 1
                else:
                    broken.append(
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
            plant = Plant()
            try:
                plant.put(NEGATIVE_DIR / rid / entry["fixture"], entry["plant_at"], entry["mode"])
                for extra in entry.get("extra_files") or []:
                    plant.put(
                        NEGATIVE_DIR / rid / extra["fixture"], extra["plant_at"], extra["mode"]
                    )
                if via == "diff":
                    result = C.diff_checks(ROOT, "HEAD", RULES_BY_ID).get(rid, CheckResult())
                    kept, _ = apply_overrides(rid, result.findings)
                else:
                    kept, _ = run_rule(rule, floors=False)
                # A negative fires when something in the output NAMES it. The
                # plant path is that signature for a one-file fixture; a
                # MULTI-FILE negative is not, because a finding about a relation
                # between three modules is pathed at whichever of them is wrong,
                # which need not be the one written as `plant_at`. Such a fixture
                # declares its own signature in `expect.contains` — the same
                # grammar the django probe uses — and the two are read together,
                # never one instead of the other.
                want = (entry.get("expect") or {}).get("contains")
                hits = [
                    f
                    for f in kept
                    if names_planted(f, resolve_plant_text(str(entry["plant_at"])))
                    or (want and want in str(f))
                ]
                if hits:
                    broken.append(
                        f"rule {rid}: FALSE-POSITIVE REGRESSION — negative {entry['fixture']} "
                        f"fired: {hits[0]}"
                    )
                else:
                    silent += 1
                    per_rule[rid]["negatives"] += 1
            finally:
                plant.restore()

    # -- the Django probe runs: all django canaries in one app, then negatives --
    #
    # One subprocess per corpus rather than one per fixture: each fixture is
    # still asserted individually (its expected id must fire naming its own
    # subject), and a probe app that fails to import fails EVERY assertion —
    # loudly, as exit 2 — rather than any canary quietly passing.
    for kind, base, is_canary in (
        ("canaries", CANARY_DIR, True),
        ("negatives", NEGATIVE_DIR, False),
    ):
        entries: list[tuple[str, dict]] = []
        for rule in RULES:
            rid = str(rule["id"])
            if not rule.get("enabled", True):
                continue
            for entry in rule.get(kind) or []:
                if entry.get("via") != "django":
                    continue
                # Already counted as out-of-world in the AST loop above; the
                # two loops must agree about what this run's world holds or the
                # census would count the same form twice, once each way.
                if W.entry_out_of_world(entry, DISABLED_APPS):
                    continue
                entries.append((rid, entry))
        if not entries:
            continue
        plant = Plant()
        try:
            plant.scaffold_probe()
            for rid, entry in entries:
                plant.put(base / rid / entry["fixture"], entry["plant_at"], entry["mode"])
                for extra in entry.get("extra_files") or []:
                    plant.put(base / rid / extra["fixture"], extra["plant_at"], extra["mode"])
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
            error_lines = [ln for ln in output.splitlines() if "(djb." in ln]
            if is_canary:
                for rid, entry in entries:
                    expect = entry.get("expect") or {}
                    wanted_id, wanted_text = expect.get("id", ""), expect.get("contains", "")
                    hit = any(wanted_id in ln and wanted_text in ln for ln in error_lines)
                    if hit:
                        fired += 1
                        per_rule[rid]["canaries"] += 1
                    else:
                        broken.append(
                            f"rule {rid}: CANARY DEAD — django form {entry['fixture']} did not "
                            f"raise {wanted_id} naming {wanted_text!r}"
                        )
                if not error_lines:
                    broken.append(
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
                            broken.append(
                                f"rule {rid}: FALSE-POSITIVE REGRESSION — the django negative "
                                f"{entry['fixture']} fired: {ln}"
                            )
                    elif ran:
                        silent += 1
                        per_rule[rid]["negatives"] += 1
                if not ran:
                    broken.append(
                        f"the django negative probe failed to run (exit {proc.returncode}):\n"
                        + output.strip()[-2000:]
                    )
        finally:
            plant.restore()

    # -- the budget mechanism's own canary: a ceiling below reality must fire ----
    measured = measure_budgets()
    section = "service_function_length"
    budget_canary = 0
    if measured[section]:
        key, value = next(iter(measured[section].items()))
        problems = check_budgets({section: {key: value - 1}})
        if any("grew" in p and key in p for p in problems):
            fired += 1
            budget_canary = 1
        else:
            broken.append("BUDGET CANARY DEAD — a ceiling below the measured value did not fire")

    leftover = tree_dirty_under_plants()
    if leftover:
        broken.append(
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
    # : Kept local, not appended to the module-level `notes`: a self-test run
    # : accumulates every ratchet note from every planted tree, and printing
    # : those would bury the one thing this section exists to say.
    grown: list[str] = []
    say("selftest, by rule (fired/recorded · silent/recorded):")
    for rule in RULES:
        rid = str(rule["id"])
        name = rule.get("name", "")
        if not rule.get("enabled", True):
            say(f"  rule {rid} {name}: DISABLED — not planted")
            continue
        recorded = selftest_floor(rule)
        got = per_rule[rid]
        # THE ONLY LEGAL LOWERING, and it is paid for by a NAMED APP.
        # The recorded number in rules.yaml never moves — a reviewer still
        # reads the plan's full population in the diff — and what this run
        # expected falls by exactly the forms whose world this deployment does
        # not hold, with the app that took them printed on the same line. A
        # shrink nothing absent paid for is still POPULATION SHORT.
        floor = {k: max(0, recorded[k] - skipped[rid][k]) for k in ("canaries", "negatives")}
        status = (
            "ok"
            if got["canaries"] >= floor["canaries"] and got["negatives"] >= floor["negatives"]
            else "SHORT"
        )
        elsewhere = (
            ""
            if not absent[rid]
            else (
                f" · {skipped[rid]['canaries']}c/{skipped[rid]['negatives']}n not in this "
                f"world ({', '.join(sorted(absent[rid]))} disabled; recorded "
                f"{recorded['canaries']}/{recorded['negatives']})"
            )
        )
        say(
            f"  rule {rid} {name}: canaries {got['canaries']}/{floor['canaries']} · "
            f"negatives {got['negatives']}/{floor['negatives']} — {status}{elsewhere}"
        )
        for kind in ("canaries", "negatives"):
            if got[kind] < floor[kind]:
                broken.append(
                    f"rule {rid}: SELFTEST POPULATION SHORT — {got[kind]} of {floor[kind]} "
                    f"recorded {kind} were planted and proved. Either a form died (the line "
                    f"above it says which) or the plan lost one: a canary deleted from "
                    f"`canaries:` takes its own expectation with it, which is why the number "
                    f"lives in `selftest_floor` and not in the length of the list. Restore the "
                    f"form, or commit the lower number in a diff a reviewer reads"
                )
            elif got[kind] > floor[kind]:
                grown.append(
                    f"rule {rid} selftest: {kind} at {got[kind]} against a recorded "
                    f"{floor[kind]} — a human may commit the higher number to "
                    "quality/rules.yaml; nothing tightens by itself."
                )
    say(f"  budgets: canary {budget_canary}/1 — the mechanism's own, outside any rule")
    for note in grown:
        say(f"  {note}")
    say(f"selftest: {fired} canary forms fired · {silent} negatives stayed silent · tree restored")


# --- main ------------------------------------------------------------------------


def live_scan(diff_ref: str | None) -> None:
    per_rule: list[str] = []
    django_findings = [] if os.environ.get("GATE_SKIP_DJANGO_LEG") else run_django_leg()
    diff_results = C.diff_checks(ROOT, diff_ref, RULES_BY_ID) if diff_ref else {}

    for rule in RULES:
        rid = str(rule["id"])
        name = rule.get("name", "")
        if not rule.get("enabled", True):
            per_rule.append(
                f"  rule {rid} {name}: DISABLED — "
                f"{rule.get('disabled_reason', 'no reason recorded')}"
            )
            continue
        kept, targets = run_rule(rule)
        for rule_id, line in django_findings:
            if rule_id == rid:
                violations.append(f"rule {rid}: {line}")
        if rid in diff_results:
            diff_kept, _ = apply_overrides(rid, diff_results[rid].findings)
            kept = kept + diff_kept
        for finding in kept:
            violations.append(f"rule {rid}: {finding}")
        shown = ", ".join(f"{k}={v}" for k, v in sorted(targets.items())) or "django-leg"
        status = "ok" if not kept and not any(r == rid for r, _ in django_findings) else "RED"
        per_rule.append(f"  rule {rid} {name}: {status} ({shown})")

    for problem in check_budgets():
        violations.append(problem)

    say(f"House rules: {len(RULES)} rules")
    for line in per_rule:
        say(line)

    standing = [
        (r, p, ln, reason) for r, p, ln, reason in all_overrides() if len(reason) >= MIN_REASON
    ]
    say(f"overrides (standing): {len(standing)}")
    for rule_id, path, lineno, reason in standing:
        say(f"  rule-{rule_id} {path}:{lineno} — {reason}")
    for rule_id, path, lineno, reason in all_overrides():
        if len(reason) < MIN_REASON:
            violations.append(
                f"rule {rule_id}: {path}:{lineno}: override `# rule-{rule_id}` with no reason — "
                "an escape hatch nobody has to justify is an off switch"
            )
    for note in notes:
        say(f"  {note}")


def main(argv: list[str]) -> int:
    diff_ref: str | None = None
    mode = "scan"
    args = list(argv)
    while args:
        arg = args.pop(0)
        if arg == "--selftest":
            mode = "selftest"
        elif arg == "--diff":
            if not args:
                say("‼ --diff needs a ref")
                return 2
            diff_ref = args.pop(0)
        else:
            # A mistyped flag must never be a silently different run.
            say(f"‼ unknown argument {arg!r}: quality.gate takes --selftest or --diff <ref>")
            return 2

    consistency()
    if mode == "selftest":
        if not broken:
            selftest()
    else:
        live_scan(diff_ref)

    seen: set[str] = set()
    deduped = [v for v in violations if not (v in seen or seen.add(v))]
    if broken:
        say("ENFORCEMENT BROKEN (exit 2 — outranks any pass):")
        for b in broken:
            say(f"  !! {b}")
    if deduped:
        say("Violations:")
        for v in deduped:
            say(f"  x {v}")
    if not broken and not deduped:
        if mode == "selftest":
            say("selftest clean: every canary fired, every negative stayed silent.")
        else:
            say(f"House rules: {len(RULES)} rules · all scopes bound · clean.")
    return 2 if broken else (1 if deduped else 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
