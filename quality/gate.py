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
under a plant path, a stale plant standing on the tree, a runner that could not
be believed). 2 outranks a pass — a gate that is broken must never read as a
gate that passed.

Every mode begins with the same preflight: a self-test killed between plant and
restore leaves its fixtures standing, and everything below would then be
measuring them. The quiet half is why it runs first — a planted NEGATIVE reports
nothing at all, so the run goes GREEN over a tree that is partly fixture.

Scope kinds: a rule may be about a language that is not Python. It declares
`kind:` (roots, file suffixes and the comment token a valve is written with),
`needs_tree:` (the tree whose absence makes its live scan a PRINTED skip rather
than a red) and `runner:` (an external instrument speaking the check-v1
protocol, `quality/check_v1.py`). The runner MEASURES and this engine JUDGES:
overrides, ratchets, floors, canary attribution and 0/1/2 never cross the
process boundary, and a runner that cannot be believed is exit 2 rather than
zero findings.

Overrides: a line carrying `# rule-<id>: <reason>` — or the same marker in that
file's own comment syntax, `// rule-<id>: <reason>` in a kind that spells it
that way — on the flagged line or in
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

import contextlib
import io
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

from quality import check_v1  # noqa: E402
from quality import checks as C  # noqa: E402
from quality import worlds as W  # noqa: E402
from quality.checks import FLOOR_PROXIES, REGISTRY, CheckResult, Finding  # noqa: E402

_DOC: dict = yaml.safe_load((ROOT / "quality" / "rules.yaml").read_text())
RULES: list[dict] = _DOC["rules"]
RULES_BY_ID: dict[str, dict] = {str(r["id"]): r for r in RULES}

# --- the scope kinds this engine knows -------------------------------------------
#
# The languages a rule may be written about: roots, file suffixes, and the
# comment token a valve is written with. Data, like everything else here, so
# that adding one is a diff a reviewer reads rather than an edit to the walk.
SCOPE_KINDS: dict = _DOC.get("scope_kinds") or {}

# The recorded population of the SEAM's own canaries — the process boundary's
# failure modes, which no planted file can exercise because their subject is a
# runner that will not answer rather than a tree that is wrong. Same grammar as
# every other floor in this engine: below it is exit 2, above it is a note a
# human may commit.
SEAM: dict = _DOC.get("seam") or {}

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

#: F3 (Vra, 2026-08-31): the sentinel `run_rule`'s third return element carries when a
#: rule COULD NOT LOOK (tree present, toolchain absent; or a live runner
#: refused) rather than ran clean or was legally skipped. Before this existed
#: both shapes returned `""`, so a refused rule's own per-rule line printed
#: `ok` — the true reason sat only in the `broken` section further down, which
#: prints AFTER the per-rule table a reader checks first.
COULD_NOT_LOOK = "COULD-NOT-LOOK — "

#: One compiled valve pattern per comment token. The marker's grammar — the id,
#: the optional colon, the reason — is one string with the token substituted in,
#: so a second language gets the SAME valve, including the same reason floor,
#: rather than a second dialect somebody has to keep in step. Cached because the
#: override walk asks per line.
_OVERRIDE_RES: dict[str, re.Pattern[str]] = {"#": OVERRIDE_RE}


def override_re(comment: str) -> re.Pattern[str]:
    """The `<comment> rule-<id>: <reason>` pattern for one comment syntax."""
    cached = _OVERRIDE_RES.get(comment)
    if cached is None:
        cached = re.compile(re.escape(comment) + r"\s*rule-(\d+)\b:?\s*(.*)$")
        _OVERRIDE_RES[comment] = cached
    return cached


broken: list[str] = []
violations: list[str] = []
notes: list[str] = []

#: Which rule each violation line belongs to, RECORDED where the line is
#: appended rather than parsed back out of its text. The trailer below is
#: printed per rule, so the grouping has to be a fact the appender stated; a
#: regex over `rule (\d+):` would be a second, weaker answer to a question the
#: caller already knew. A violation with no entry here is a BUDGET — the one
#: finding class that has no rule id at all (`check_budgets`).
violation_rule: dict[str, str] = {}

#: Per rule id, the comment tokens the files it reported in are written with.
#: The valve a reader is handed has to be paste-able WHERE THE FINDING LIVES
#: (F2, Vra, 2026-08-31): a `.ts` file's own reader must not be told to write
#: `#`. A rule whose findings span two languages therefore prints its marker
#: once per kind present, never once per rule.
finding_kinds: dict[str, set[str]] = {}


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

    The comment syntax comes from the FILE, through the scope kinds: a valve in
    a `.ts` file is `// rule-<id>: <reason>` and a valve in a `.py` file is the
    `#` form, and both are the same mechanism with the same reason floor rather
    than two grammars a reader has to learn.
    """
    lines = _file_lines(path)
    if not lines or line < 1 or line > len(lines):
        return None
    try:
        rel = str(path.relative_to(ROOT))
    except ValueError:
        rel = str(path)
    comment = W.comment_token(W.kind_of_path(rel, SCOPE_KINDS))
    pattern = override_re(comment)
    m = pattern.search(lines[line - 1])
    if m and m.group(1) == rule_id:
        return m.group(2).strip()
    i = line - 2
    while i >= 0 and lines[i].strip().startswith(comment):
        m = pattern.search(lines[i])
        if m and m.group(1) == rule_id:
            return m.group(2).strip()
        i -= 1
    return None


def _kind_walk() -> list[tuple[str, str, frozenset[str]]]:
    """(root, suffix, skip_dirs) for every place a valve may be written, from the kinds.

    Derived rather than typed so that the census and the suppression cannot
    disagree about where a valve counts: the day a kind declares a root, both
    halves see it. A kind whose roots are not on this checkout contributes
    nothing and says nothing — a frontend-less template has no frontend valves,
    which is a fact rather than a skip.

    `skip_dirs` rides the same tuple for the identical reason: a vendored
    directory (`node_modules`, `.next`, …) must not enter this walk any more
    than it enters a rule's own live scan, and the declaration is `kind_skip_dirs`'s
    — one set, read here and by every runner under `quality/runners/`.
    """
    walk: list[tuple[str, str, frozenset[str]]] = []
    for kind in SCOPE_KINDS.values():
        skip = W.kind_skip_dirs(kind)
        for root in kind.get("roots") or []:
            for suffix in kind.get("suffixes") or []:
                walk.append((str(root), str(suffix), skip))
    return walk


def all_overrides() -> list[tuple[str, str, int, str]]:
    """(rule_id, relpath, line, reason) for every override marker in the tree."""
    found: list[tuple[str, str, int, str]] = []
    seen: set[tuple[str, int]] = set()
    for sub, suffix, skip in _kind_walk():
        base = ROOT / sub
        if not base.exists():
            continue
        for path in sorted(base.rglob(f"*{suffix}")):
            if skip & set(path.parts):
                continue
            rel = str(path.relative_to(ROOT))
            pattern = override_re(W.comment_token(W.kind_of_path(rel, SCOPE_KINDS)))
            for lineno, text in enumerate(_file_lines(path), start=1):
                m = pattern.search(text)
                if m and (rel, lineno) not in seen:
                    seen.add((rel, lineno))
                    found.append((m.group(1), rel, lineno, m.group(2).strip()))
    return sorted(found, key=lambda row: (row[1], row[2]))


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
            marker = W.comment_token(W.kind_of_path(finding.path, SCOPE_KINDS))
            kept.append(
                Finding(
                    finding.path,
                    finding.line,
                    f"override `{marker} rule-{rule_id}` with no reason — an escape hatch "
                    f"nobody has to justify is an off switch (suppressing: {finding.msg})",
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


def run_runner(rule: dict) -> CheckResult:
    """A `runner:` rule's external instrument, through the check-v1 protocol.

    THE SEAM, AND THE ONE SENTENCE IT IS BUILT AROUND: the runner measures and
    this engine judges. What comes back is a CheckResult and nothing else — no
    verdict, no severity, no suppression — so a `runner:` rule rejoins the
    pipeline below at exactly the point an in-process `check:` rule does, and
    every semantic after that line is the same code for both. A refusal is
    raised rather than returned: could-not-look must not be able to arrive here
    wearing an empty findings list.
    """
    runner = rule.get("runner") or {}
    argv = [str(a) for a in (runner.get("argv") or [])]
    return check_v1.invoke(
        ROOT,
        argv=argv,
        roots=W.kind_roots(rule, SCOPE_KINDS),
        where=f"rule {rule['id']} runner {' '.join(argv)!r}",
        timeout=int(runner.get("timeout") or check_v1.DEFAULT_TIMEOUT),
    )


def run_rule(rule: dict, *, floors: bool = True) -> tuple[list[Finding], dict, str]:
    """The rule's check + override + ratchet pipeline. (violations, targets, skip).

    `skip` is empty for a rule that ran; a SKIPPED sentence for a rule about a
    tree this checkout does not have; and a `COULD_NOT_LOOK`-prefixed sentence
    (F3, Vra, 2026-08-31) for a rule that could not be run at all — its tree present
    with no toolchain, or a live runner this engine refused to believe. The
    three are returned rather than printed here because this function runs
    inside the self-test as well, where the plant has just made the tree exist
    and there is nothing to announce; the caller that DOES print (`live_scan`)
    is what turns the prefix into a status distinct from `ok`, so a refused
    rule's own line cannot read as a rule that ran clean.
    """
    rid = str(rule["id"])
    targets: dict = {}
    findings: list[Finding] = []
    verdict, why = W.tree_verdict(ROOT, rule, SCOPE_KINDS)
    if verdict == "broken":
        broken.append(f"rule {rid}: {why}")
        return [], targets, COULD_NOT_LOOK + why
    absent = verdict == "skip"
    impl = rule.get("check")
    if impl and not absent:
        result: CheckResult = REGISTRY[impl](ROOT, rule)
        targets.update(result.targets_matched)
        findings.extend(result.findings)
    if rule.get("runner") and not absent:
        try:
            reply = run_runner(rule)
        except check_v1.RunnerRefused as exc:
            # COULD NOT LOOK, and it outranks a pass. Reported and the rule
            # produces nothing — never zero findings, which is the shape a
            # broken instrument would otherwise wear.
            broken.append(f"rule {rid}: RUNNER REFUSED ({exc.klass}) — {exc.detail}")
            return [], targets, COULD_NOT_LOOK + f"({exc.klass}) {exc.detail}"
        targets.update(reply.targets_matched)
        findings.extend(reply.findings)
    proxy = rule.get("floor_proxy")
    if proxy and not absent:
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
            # paid for by a named app. An ABSENT TREE is the second, larger
            # subtraction and it takes every floor to zero — the derivation runs
            # here rather than being skipped around, so that the one path a
            # frontend-less template takes every run is the same path every
            # other rule takes.
            expected = W.derived_floor(rule, key, int(floor), DISABLED_APPS, absent_tree=absent)
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
    return kept, targets, why if absent else ""


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

    THE SUBJECT IS A FUNCTION, NOT A FILE. A `services.py` holding no top-level
    `def` at all records NO subject: a "longest function" of 0 with an empty
    label is not a measurement anybody took, it is a placeholder, and handing it
    to `check_budgets` turns "a new subject fails until a human measures it"
    into "a new empty module fails until a human commits a zero". The doctrine
    is about a subject that HAS a value; the first real function in a module
    becomes that subject in the change that writes it, exactly when a person can
    measure it — which is how every recorded ceiling here got its number. The
    module with one `def` is a subject and still fails without a ceiling, which
    is the half that keeps the doctrine true.
    """
    import ast as _ast

    service_lengths: dict[str, tuple[int, str]] = {}
    for path in sorted(ROOT.glob("apps/*/services.py")):
        tree = C._parse(path)
        if tree is None:
            continue
        longest, label, functions = 0, "", 0
        for node in tree.body:
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                functions += 1
                end = node.end_lineno or node.lineno
                measured = end - node.lineno + 1 - _docstring_lines(node)
                if measured > longest or not label:
                    longest = max(longest, measured)
                    label = f"{node.name} (lines {node.lineno}-{end})"
        # Counted, never inferred from the label: a function whose whole body is
        # its docstring measures 0, and reading "no label" as "no function"
        # would let that one module out of the population it belongs to.
        if functions == 0:
            continue
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


def seam_consistency() -> None:
    """The scope-kind declarations, and the seam's own recorded population.

    The seam is held to the grammar it enforces on everything else: a declared
    blind spot and a recorded self-test population, refused when missing rather
    than defaulted. A default here would be the exact defect the key exists to
    end — a plan that quietly loses a canary and keeps printing a total.
    """
    for name, kind in SCOPE_KINDS.items():
        if not isinstance(kind, dict):
            broken.append(f"scope kind {name!r}: not a declaration")
            continue
        for key in ("roots", "suffixes"):
            value = kind.get(key)
            if not isinstance(value, list) or not value:
                broken.append(f"scope kind {name!r}: {key} is {value!r}, not a non-empty list")
        for suffix in kind.get("suffixes") or []:
            if not str(suffix).startswith("."):
                broken.append(f"scope kind {name!r}: suffix {suffix!r} does not start with a dot")
        if not str(kind.get("comment", "")).strip():
            broken.append(
                f"scope kind {name!r}: no comment token — a kind whose valve syntax is "
                "unknown is a kind whose overrides cannot be found, and an override nobody "
                "can find is an exemption nobody can count"
            )
    # THE SIGNATURE CENSUS, both directions. A form whose expected signature the
    # code can no longer emit is the quietest failure an assertion corpus has:
    # it matches nothing, reports nothing, and reads as "stayed silent" forever.
    # So the refusal classes are declared, derived from the protocol module's own
    # source, and demanded of the canary table — a class cannot be renamed
    # without its canary, and cannot exist without one.
    emitted = check_v1.emitted_refusal_classes()
    for missing in sorted(check_v1.REFUSAL_CLASSES - emitted):
        broken.append(
            f"the seam declares the refusal class {missing!r}, which quality/check_v1.py no "
            "longer raises — a canary expecting it would match nothing and read as silence"
        )
    for undeclared in sorted(emitted - check_v1.REFUSAL_CLASSES):
        broken.append(
            f"quality/check_v1.py raises the refusal class {undeclared!r}, which is not in "
            "REFUSAL_CLASSES — a way to be unbelievable that nothing is obliged to prove"
        )
    canaried = {want for _label, _rule, want in _seam_canaries()}
    for unproven in sorted(check_v1.REFUSAL_CLASSES - canaried):
        broken.append(
            f"the refusal class {unproven!r} has no seam canary — a branch of the protocol "
            "nobody can show fires is a branch nobody can show works"
        )
    declared = SEAM.get("selftest_floor")
    if not isinstance(declared, dict) or {"canaries", "negatives"} - set(declared):
        broken.append(
            "the seam has no selftest_floor — record how many runner-protocol canary forms "
            "and negatives the plan holds, so a plan that quietly loses one is exit 2"
        )
    else:
        for kind_name, count in declared.items():
            try:
                if int(count) < 0:
                    raise ValueError
            except (TypeError, ValueError):
                broken.append(f"the seam's selftest_floor {kind_name!r} is {count!r}, not a count")
    if not str(SEAM.get("does_not_cover", "")).strip():
        broken.append("the seam has no does_not_cover — an undeclared blind spot")


def rule_seam_consistency(rule: dict) -> None:
    """A rule's kind, runner and tree declarations — shape only, never existence.

    `needs_tree` is deliberately NOT resolved against the filesystem, and that
    is the one place this differs from the scope-path assertion below it. A
    scope allow-list is a fact about today; a `needs_tree` is a statement about
    a tree a product may or may not have grown, and refusing the absent case
    would refuse the template's own steady state.
    """
    rid = str(rule["id"])
    kind = rule.get("kind")
    if kind is not None and not isinstance(kind, dict) and str(kind) not in SCOPE_KINDS:
        broken.append(
            f"rule {rid}: kind {kind!r} is not one of the declared scope kinds "
            f"({', '.join(sorted(SCOPE_KINDS)) or 'none'})"
        )
    wanted = rule.get("needs_tree")
    if wanted is not None:
        if not isinstance(wanted, str) or not wanted.strip():
            broken.append(f"rule {rid}: needs_tree is {wanted!r}, not a path")
        else:
            # F6 (Vra, 2026-08-31): a non-empty string is not yet a PATH — an absolute
            # one, or one carrying `..`, could name something this checkout
            # does not own, which is exactly the shape `check_v1._refuse_outside_roots`
            # already refuses on the runner's OWN findings. `needs_tree` gets
            # the identical refusal rather than a second, looser one.
            candidate = Path(wanted)
            if candidate.is_absolute() or ".." in candidate.parts:
                broken.append(
                    f"rule {rid}: needs_tree is {wanted!r}, not a path RELATIVE to the "
                    "checkout root — an absolute path or a `..` segment could name something "
                    "this tree does not own"
                )
    runner = rule.get("runner")
    if runner is None:
        return
    if not isinstance(runner, dict):
        broken.append(f"rule {rid}: runner is {runner!r}, not a declaration")
        return
    argv = runner.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        broken.append(f"rule {rid}: runner argv is {argv!r}, not a non-empty list of strings")
    if "timeout" in runner:
        try:
            if int(runner["timeout"]) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            broken.append(f"rule {rid}: runner timeout is {runner['timeout']!r}, not seconds")
    if not W.kind_roots(rule, SCOPE_KINDS):
        broken.append(
            f"rule {rid}: a runner rule whose kind declares no roots can report about "
            "anywhere, which makes its scope whatever the instrument feels like"
        )
    if rule.get("needs_tree") is None and W.needs_tree(rule, SCOPE_KINDS) is None:
        broken.append(
            f"rule {rid}: a runner rule declares `needs_tree` — either on itself or on its "
            "kind — because a checkout without the tree must skip and say so rather than "
            "run an instrument at nothing"
        )


def consistency() -> None:
    seam_consistency()
    seen_ids: set[str] = set()
    for rule in RULES:
        rid = str(rule["id"])
        if rid in seen_ids:
            broken.append(f"rule {rid}: duplicate id")
        seen_ids.add(rid)
        impl = rule.get("check")
        if impl and impl not in REGISTRY:
            broken.append(f"rule {rid}: check impl {impl!r} not in registry")
        if (
            not impl
            and not rule.get("django_check_ids")
            and not rule.get("diff")
            and not rule.get("runner")
        ):
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
        # THE VALVE, AS DATA (contract B.1). Every rule says how a legitimate
        # exception to it is recorded — the marker, and where it has to sit —
        # or says that nothing can excuse it and why. Before this field the
        # grammar was prose in four files (`quality/gate.py`'s generic
        # override, `checks.py`'s `# authz:`/`# reach:`/`# door:`/
        # `# role-bound:`, the conventions skill's table) and a reader holding
        # a red had no way to learn any of it from the red. A rule with
        # NEITHER form is exit 2 rather than a quieter trailer: the census of
        # which rules genuinely have no valve is the point of the field, and a
        # rule that silently declined to answer it would be the one place the
        # census cannot see.
        valve = rule.get("valve")
        if not isinstance(valve, dict):
            broken.append(
                f"rule {rid}: no valve — declare `valve: {{ marker: ..., where: ... }}` or "
                "`valve: { none: <why nothing can excuse this> }`; a red that cannot say how "
                "to record a legitimate exception is a red nobody can act on"
            )
        else:
            excuse = str(valve.get("none") or "").strip()
            marker = str(valve.get("marker") or "").strip()
            where = str(valve.get("where") or "").strip()
            if excuse and (marker or where):
                broken.append(
                    f"rule {rid}: valve declares `none:` AND a marker — one or the other, "
                    "never both; a reader cannot be told there is no valve and handed one"
                )
            elif excuse:
                if len(excuse) < MIN_REASON:
                    broken.append(
                        f"rule {rid}: valve `none:` reason is {len(excuse)} characters — a "
                        "claim that nothing can excuse this rule is exactly the claim that "
                        "owes a sentence a reviewer can disagree with"
                    )
            elif not (marker and where):
                broken.append(
                    f"rule {rid}: valve declares neither `marker:` + `where:` nor "
                    "`none: <reason>` — a valve a reader cannot paste, in a place the rule "
                    "will not read it, is not a valve"
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
        rule_seam_consistency(rule)
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


#: Short enough that no real fixture is excluded; long enough that a stub, a
#: blank line or a one-word file cannot match half the tree by accident.
MIN_FIXTURE_SIGNATURE = 20


def stale_plants() -> list[str]:
    """Files on this tree that ARE a fixture — the residue of a run that died.

    THE INCIDENT SHAPE, and it is the worst one this engine has: a self-test
    killed between plant and restore leaves its fixtures standing. The next run
    then reads planted wrongness as the product's own work — or, far worse,
    reads a planted NEGATIVE as a clean scan and reports green over a tree that
    is partly fixture. A gate that measures its own leftovers is not measuring
    anything, and nothing in its output says so.

    CLOSED QUESTION, AND DELIBERATELY THE NARROWEST TOTAL ONE: a plant target
    whose bytes ARE the fixture's bytes. Nobody writes a file identical to a
    planted violation by accident, and an ordinary edit under a plant path —
    which is most of `apps/` on any working day — is silent here. That is
    exactly why this can run on EVERY mode while the dirty-tree refusal below
    can only run inside the self-test: one asks whether a file changed, this
    asks whether a file IS a fixture.

    The scaffold app is the loudest member and needs no comparison at all: it
    exists only while a plant holds it, so finding it at rest is finding a run
    that never finished.
    """
    found: list[str] = []
    if PROBE_DIR.exists():
        found.append(
            f"apps/{PROBE_APP}/ — the self-test's scaffold app, which exists only while a "
            "plant is held. Finding it at rest is finding a run that never restored"
        )
    mark = len(broken)
    for rule in RULES:
        for kind, base in (("canaries", CANARY_DIR), ("negatives", NEGATIVE_DIR)):
            for entry in rule.get(kind) or []:
                for e in [entry, *(entry.get("extra_files") or [])]:
                    fixture = base / str(rule["id"]) / e["fixture"]
                    if not fixture.is_file():
                        continue
                    body = resolve_plant_text(fixture.read_text())
                    if len(body.strip()) < MIN_FIXTURE_SIGNATURE:
                        continue
                    target = ROOT / resolve_plant_text(str(e["plant_at"]))
                    if not target.is_file():
                        continue
                    try:
                        text = target.read_text()
                    except (OSError, UnicodeDecodeError):
                        continue
                    if text == body or (e["mode"] == "append" and text.endswith(body)):
                        found.append(
                            f"{target.relative_to(ROOT)} — the "
                            f"{'canary' if kind == 'canaries' else 'negative'} "
                            f"{e['fixture']} of rule {rule['id']} is standing on the tree"
                        )
    # Placeholder resolution reads the migration graph and can refuse; that
    # refusal belongs to the self-test, not to a preflight whose whole job is to
    # look at the tree before anything else does. Taken back rather than
    # surfaced here, so a preflight cannot invent a verdict of its own.
    del broken[mark:]
    return found


def refuse_stale_plants() -> None:
    """Exit 2 before anything measures a tree it would be measuring wrong.

    F4 (Vra, 2026-08-31): true of BOTH modes `main()` runs, not only `--selftest`. This
    function only appends to `broken`; the one `return` inside it is the
    "nothing stale" case. What used to make the header sentence a claim rather
    than a fact was `main()`'s own branch below it — `--selftest` already
    skipped its leg on `if not broken`, and plain scan mode called `live_scan`
    unconditionally, one `return`(-equivalent guard) short of the sentence
    above. Both modes now honour it.
    """
    stale = stale_plants()
    if not stale:
        return
    broken.append(
        "STALE PLANTS ON THE TREE — a self-test that did not reach its restore left these "
        "behind, and every leg after this line would be reading fixtures as the product's "
        "own code. A negative left standing is the dangerous half: it reports nothing and "
        "the run goes green over a tree that is partly planted. Remove them and run again "
        "(`git status --porcelain`, then `git checkout --` the tracked ones and delete the "
        "untracked ones):\n  " + "\n  ".join(stale)
    )


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
    mark = len(broken)
    kept, targets, skip = run_rule(rule, floors=floors)
    produced = broken[mark:]
    del broken[mark:]
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
            broken.append(
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
            broken.append(
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
        broken.append(
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
        broken.append(
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
        broken.append(
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
        broken.append(
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
            broken.append(
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
        broken.append(
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
                broken.append(
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
                broken.append(
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
        broken.append(
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
        broken.append(
            f"SEAM VALVE CENSUS — rule {rid} has no valve negative to plant, so nothing "
            "proves a second language's exemption is counted rather than merely obeyed"
        )
        return 0
    entry = entries[0]
    plant = Plant()
    try:
        plant.put(NEGATIVE_DIR / rid / entry["fixture"], entry["plant_at"], entry["mode"])
        rows = [row for row in all_overrides() if row[1] == str(entry["plant_at"])]
        if not rows:
            broken.append(
                "SEAM VALVE CENSUS — a `// rule-` valve planted at "
                f"{entry['plant_at']} is invisible to the standing override census. An "
                "exemption nobody counts is an off switch with extra steps"
            )
            return 0
        if rows[0][0] != rid or len(rows[0][3]) < MIN_REASON:
            broken.append(
                f"SEAM VALVE CENSUS — the planted valve was read as {rows[0]!r}, which is "
                f"not rule {rid} carrying a reason"
            )
            return 0
        return 1
    finally:
        plant.restore()


def seam_skip_dir_census() -> int:
    """A valve planted inside a kind's declared VENDORED directory stays OUT. (1 or 0).

    F1 (Vra, 2026-08-31). Before `quality/rules.yaml`'s `scope_kinds.js.skip_dirs`
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
        plant.put(NEGATIVE_DIR / "50" / "vendored_valve.js", target, "create")
        rows = [row for row in all_overrides() if row[1] == target]
        if rows:
            broken.append(
                "SEAM SKIP-DIR CENSUS — a `// rule-` valve planted inside "
                f"frontend/node_modules/ was counted in the standing override census: {rows!r}. "
                "A vendored directory must not enter the census any more than it enters a live "
                "scan"
            )
            return 0
        return 1
    finally:
        plant.restore()


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
    seam_fired, seam_silent = seam_leg()
    seam_floor = {
        "canaries": int((SEAM.get("selftest_floor") or {}).get("canaries", 0)),
        "negatives": int((SEAM.get("selftest_floor") or {}).get("negatives", 0)),
    }
    for kind, got in (("canaries", seam_fired), ("negatives", seam_silent)):
        want = seam_floor[kind]
        if got < want:
            broken.append(
                f"seam: SELFTEST POPULATION SHORT — {got} of {want} recorded {kind}. Either a "
                "form stopped proving what it claims (the line above names it) or the plan "
                "lost one: the number lives in `seam.selftest_floor` and not in the length of "
                "the list, so a form deleted from the list cannot take its own expectation "
                "with it. Restore the form, or commit the lower number in a diff a reviewer "
                "reads"
            )
        elif got > want:
            say(
                f"  seam selftest: {kind} at {got} against a recorded {want} — a human may "
                "commit the higher number to quality/rules.yaml; nothing tightens by itself."
            )
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
                    kept, _, _skip = run_rule(rule, floors=False)
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
                    kept, _, _skip = run_rule(rule, floors=False)
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
    # CANARY B.5-1, GENERALISED. A canary firing proves the rule can find its
    # subject; this proves the RED it would print is one a reader can act on.
    # Run over the rules whose canaries actually fired on THIS tree, so a rule
    # skipped for an absent world is not asked to explain a red it cannot
    # produce here.
    trailer_census([rid for rid, got in per_rule.items() if got["canaries"] > 0])
    cli_census()
    say(f"selftest: {fired} canary forms fired · {silent} negatives stayed silent · tree restored")


# --- main ------------------------------------------------------------------------


# --- the trailer: what a RED owes its reader ------------------------------------
#
# THE DEFECT (DX-ARCH #1; the consumer's ranked first cost). A finding
# printed `rule 13: apps/paper/services.py:42: <msg>` and stopped. Every other
# fact the rule DECLARES — where it is written down (`doc:`), how a legitimate
# exception is recorded (`valve:`), what it cannot see (`does_not_cover`) — sat
# in `rules.yaml` and reached nobody: `doc:` was read only by `consistency()`,
# and the valve grammar was prose in four different files. A reader holding a
# red had to find the rule in a 7,000-line yaml to learn what to do about it.
#
# THE FIX IS FOUR LINES, PRINTED ONCE PER RULE rather than once per finding: a
# rule with twelve findings owes its reader one trailer, not twelve.
#
# THE KEYS ARE ASCII AND THEY ARE THE CONTRACT. Drives
# assert `doc:`, `valve:`, `blind:`, `next:` and the marker text — never the
# `§` or `—` glyphs, which are prose and may be reworded without the meaning
# moving.
TRAILER_KEYS: tuple[str, ...] = ("doc:", "valve:", "blind:", "next:")

#: A budget violation has no rule id — `check_budgets` measures a recorded
#: number, not a declared rule — so it says where its number lives instead of
#: pretending to a `rules.yaml` entry it does not have.
BUDGET_TRAILER: list[str] = ["    doc:    — (a budget, not a rule; see quality/budgets.yaml)"]


def record_violation(rid: str, finding: object, *, path: str = "") -> None:
    """Append a finding AND remember whose it is, so the trailer can group."""
    text = f"rule {rid}: {finding}"
    violations.append(text)
    violation_rule[text] = rid
    if path:
        token = W.comment_token(W.kind_of_path(path, SCOPE_KINDS))
        finding_kinds.setdefault(rid, set()).add(token)


def _first_sentence(text: object) -> str:
    """The first sentence of a declaration, flattened onto one line.

    `does_not_cover` and `statement` are paragraphs in the yaml; a trailer line
    and a listing row each want the opening claim. The whole of either is one
    `--explain` away, which is what the `next:` line is for.
    """
    flat = " ".join(str(text or "").split())
    if not flat:
        return ""
    cut = flat.find(". ")
    return flat if cut < 0 else flat[: cut + 1]


def valve_lines(rule: dict, tokens: object = ()) -> list[str]:
    """The `valve:` half of a trailer — one line per comment token present.

    The marker a rule declares may carry `<comment>` where the file's own
    line-comment token belongs (the generic `<comment> rule-<id>: <reason>`
    override). It is substituted PER FINDING'S KIND, not per rule, so a rule
    that reported in a `.py` file and a `.ts` file prints both forms and each
    reader can paste the one their file speaks.
    """
    valve = rule.get("valve") or {}
    excuse = str(valve.get("none") or "").strip()
    if excuse:
        return [f"    valve:  none — {excuse}"]
    marker = str(valve.get("marker") or "").strip()
    where = str(valve.get("where") or "").strip()
    if not marker:
        return ["    valve:  (none declared — quality/rules.yaml has lost this rule's entry)"]
    present = sorted({str(t) for t in tokens}) or ["#"]
    out: list[str] = []
    for token in present:
        line = f"    valve:  {marker.replace('<comment>', token)} — {where} (counted and printed)"
        if line not in out:
            out.append(line)
    return out


def rule_trailer(rule: dict, tokens: object = ()) -> list[str]:
    """The four lines every RED carries, in reading order."""
    doc = rule.get("doc") or {}
    rid = str(rule["id"])
    lines = [f'    doc:    {doc.get("file", "—")} § "{doc.get("contains", "")}"']
    lines += valve_lines(rule, tokens)
    lines.append(f"    blind:  {_first_sentence(rule.get('does_not_cover'))}")
    lines.append(f"    next:   python -m quality.gate --explain {rid}")
    return lines


def trailer_for(rid: str) -> list[str]:
    """The trailer for a violation group — a rule's four lines, or the budget's."""
    rule = RULES_BY_ID.get(rid)
    if rule is None:
        return list(BUDGET_TRAILER)
    return rule_trailer(rule, finding_kinds.get(rid, set()))


def trailer_census(fired: object) -> None:
    """Every rule that just PROVED it can go RED must be able to explain itself.

    Canary B.5-1, generalised. A canary firing says the rule can find its
    subject; this says the finding it produces is actionable. A rule whose
    trailer has lost a key is exit 2 and not a quieter red, for the same reason
    a dead canary is: a red that cannot explain itself is broken enforcement,
    and the builder holding it is the last person who can tell.
    """
    checked = 0
    carried = 0
    for rid in sorted({str(r) for r in fired}, key=lambda r: (len(r), r)):
        rule = RULES_BY_ID.get(rid)
        if rule is None:
            continue
        checked += 1
        lines = rule_trailer(rule, ())
        whole = True
        for key in TRAILER_KEYS:
            filled = any(
                line.strip().startswith(key) and line.strip()[len(key) :].strip() for line in lines
            )
            if not filled:
                whole = False
                broken.append(
                    f"rule {rid}: RED WITHOUT A TRAILER — its canary fired, so this rule can go "
                    f"red on somebody's tree, and the block it would print carries no `{key}` "
                    "line. A red that cannot explain itself is broken enforcement"
                )
        carried += 1 if whole else 0
    # SAID OUT LOUD ON SUCCESS, in the seam and residence censuses' grammar. An
    # instrument that is silent when it passes is an instrument whose call can
    # be deleted without anything looking different — and this one runs over
    # every rule that just proved it can go red, which is the population nobody
    # would notice going quiet.
    if carried == checked:
        say(f"trailer census: {checked} rule(s) with findings, every one carried its four lines")
    else:
        say(f"trailer census: {carried} of {checked} rule(s) with findings carried four lines")


# --- the two readers: --explain <id>, and the listing ---------------------------
#
# Both read `RULES` — the parsed yaml, in the tree's own order — and never a
# second file. `--rules` is the LISTING's other name — the seam the derived
# rule list in the working guide reads: two readers do not both invent a
# printer for one question, so the alias is `cmp`-identical output rather than
# a second implementation.


def rules_listing() -> int:
    """`id  name  first sentence`, one line per rule. Disabled rules marked."""
    for rule in RULES:
        rid = str(rule["id"])
        name = str(rule.get("name", ""))
        mark = "" if rule.get("enabled", True) else "  [DISABLED]"
        say(f"{rid:>3}  {name:<44}  {_first_sentence(rule.get('statement'))}{mark}")
    return 0


def explain(rid: str) -> int:
    """One rule's whole declaration, in reading order. Unknown id → exit 2."""
    rule = RULES_BY_ID.get(rid)
    if rule is None:
        say(
            f"‼ unknown rule id {rid!r}: `python -m quality.gate --explain` with no id prints "
            "the listing of every rule this tree holds"
        )
        return 2
    enabled = "enabled" if rule.get("enabled", True) else "DISABLED"
    say(f"rule {rid} · {rule.get('name', '')} · {enabled}")
    if not rule.get("enabled", True):
        say(f"  disabled_reason: {rule.get('disabled_reason', 'no reason recorded')}")
    say("")
    say("statement:")
    say(f"  {' '.join(str(rule.get('statement', '')).split())}")
    say("")
    say("mechanism:")
    for key in ("check", "django_check_ids", "diff", "runner"):
        if rule.get(key):
            say(f"  {key}: {rule[key]}")
    say("")
    doc = rule.get("doc") or {}
    say(f'doc:    {doc.get("file", "—")} § "{doc.get("contains", "")}"')
    for line in valve_lines(rule, ()):
        say(line.strip())
    say("")
    say(f"floors: {rule.get('floors') or {}}")
    if rule.get("ratchets"):
        say(f"ratchets: {rule['ratchets']}")
    say("")
    say("does_not_cover:")
    say(f"  {' '.join(str(rule.get('does_not_cover', '')).split())}")
    say("")
    say("canaries:")
    for entry in rule.get("canaries") or []:
        say(f"  {entry.get('fixture')} → {entry.get('plant_at')} ({entry.get('via', 'ast')})")
    say("negatives:")
    for entry in rule.get("negatives") or []:
        say(f"  {entry.get('fixture')} → {entry.get('plant_at')} ({entry.get('via', 'ast')})")
    say("")
    say(f"selftest_floor: {rule.get('selftest_floor') or {}}")
    return 0


def _captured(argv: list[str]) -> tuple[int, str]:
    """`main(argv)`'s status and stdout, for the CLI census below."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(argv)
    return rc, buf.getvalue()


def cli_census() -> None:
    """The reader half of the self-test: the two flags a red points people at.

    Canaries B.5-2 and B.5-6's sibling. `--explain` and the listing are what
    the trailer's `next:` line promises, and a promise nothing drives is a
    promise that can be deleted by accident — the same argument every drive in
    `scripts/tests/` carries. Driven through `main`'s own argv dispatch, not
    through the printers, because the claim under test is that TWO NAMES reach
    ONE printer, and calling the printer twice would prove only
    that it is deterministic.
    """
    probes = 4
    answered = 0
    enabled = [str(r["id"]) for r in RULES if r.get("enabled", True)]
    if not enabled:
        broken.append("cli census: no enabled rule to explain — the listing would be empty")
        say(f"cli census: --explain/--rules answered {answered} of {probes} probes")
        return
    by_explain = _captured(["--explain"])
    by_rules = _captured(["--rules"])
    if by_explain == by_rules:
        answered += 1
    else:
        broken.append(
            "cli census: `--explain` with no id and `--rules` printed different things — "
            "they are one printer with two names, and a second implementation is the drift "
            "rule 17 exists against"
        )
    listed = [line for line in by_rules[1].splitlines() if line.strip()]
    if len(listed) == len(RULES):
        answered += 1
    else:
        broken.append(
            f"cli census: the listing printed {len(listed)} lines for {len(RULES)} rules — a "
            "rule a reader cannot see listed is a rule whose red points at nothing"
        )
    rc, text = _captured(["--explain", enabled[0]])
    if rc == 0 and "valve:" in text and "statement:" in text:
        answered += 1
    else:
        broken.append(
            f"cli census: `--explain {enabled[0]}` exited {rc} without printing the rule's own "
            "statement and valve — the `next:` line on every red points here"
        )
    rc, text = _captured(["--explain", "zzz-no-such-rule"])
    if rc == 2 and "listing" in text:
        answered += 1
    else:
        broken.append(
            f"cli census: `--explain` of an unknown id exited {rc} — an unknown id is "
            "could-not-look (exit 2) naming the listing, never a silent nothing"
        )
    # The same reason the trailer census says its count out loud: these four
    # probes are the only thing standing between the `next:` line on every red
    # and a flag somebody deleted. A silent pass is a pass nobody can miss.
    say(f"cli census: --explain/--rules answered {answered} of {probes} probes")


def live_scan(diff_ref: str | None, *, terse: bool = False) -> None:
    # (line, status) — the status is carried beside the text rather than
    # re-derived from it, because `--terse` drops exactly the `ok` rows and a
    # reader of the count line has to be able to add them back up.
    per_rule: list[tuple[str, str]] = []
    counts = {"ok": 0, "RED": 0, "skipped": 0}
    django_findings = [] if os.environ.get("GATE_SKIP_DJANGO_LEG") else run_django_leg()
    diff_results = C.diff_checks(ROOT, diff_ref, RULES_BY_ID) if diff_ref else {}

    for rule in RULES:
        rid = str(rule["id"])
        name = rule.get("name", "")
        if not rule.get("enabled", True):
            counts["skipped"] += 1
            per_rule.append(
                (
                    f"  rule {rid} {name}: DISABLED — "
                    f"{rule.get('disabled_reason', 'no reason recorded')}",
                    "skipped",
                )
            )
            continue
        kept, targets, skip = run_rule(rule)
        if skip:
            # THE PRINTED SKIP, and the line IS the criterion. A rule that
            # legally looked at nothing and a rule that quietly stopped working
            # produce the same silence, so the only thing that tells a reader
            # which one happened is a sentence naming the tree and saying the
            # floors derived to zero.
            #
            # F3 (Vra, 2026-08-31): a rule that could NOT look — its `broken.append`
            # already fired above, inside `run_rule` — is a THIRD status, never
            # this one and never `ok` below. Without this branch its line here
            # read `ok` while the true reason surfaced only in the broken
            # section further down, which a reader meets after the per-rule
            # table this line belongs to.
            counts["skipped"] += 1
            if skip.startswith(COULD_NOT_LOOK):
                per_rule.append((f"  rule {rid} {name}: {skip}", "skipped"))
            else:
                per_rule.append((f"  rule {rid} {name}: SKIPPED — {skip}", "skipped"))
            continue
        for rule_id, line in django_findings:
            if rule_id == rid:
                # The django leg reports through `manage.py check`, whose lines
                # are already pathed prose; there is no Finding to read a kind
                # off, so the trailer falls back to the default token.
                record_violation(rid, line)
        if rid in diff_results:
            diff_kept, _ = apply_overrides(rid, diff_results[rid].findings)
            kept = kept + diff_kept
        for finding in kept:
            record_violation(rid, finding, path=finding.path)
        shown = ", ".join(f"{k}={v}" for k, v in sorted(targets.items())) or "django-leg"
        status = "ok" if not kept and not any(r == rid for r, _ in django_findings) else "RED"
        counts[status] += 1
        per_rule.append((f"  rule {rid} {name}: {status} ({shown})", status))

    for problem in check_budgets():
        violations.append(problem)

    say(
        f"House rules: {len(RULES)} rules · {counts['ok']} ok · {counts['RED']} RED · "
        f"{counts['skipped']} skipped"
    )
    # `--terse`: the ok rows are ~50 lines of other apps' good news
    # between a builder and their own finding, and the count line above already
    # holds the number. What it drops is EXACTLY the rows whose status is `ok`
    # and the standing-override detail — never a RED, never a SKIPPED, never a
    # COULD-NOT-LOOK, and never the ENFORCEMENT BROKEN block, which `main`
    # prints whatever this flag says.
    for line, status in per_rule:
        if terse and status == "ok":
            continue
        say(line)

    standing = [
        (r, p, ln, reason) for r, p, ln, reason in all_overrides() if len(reason) >= MIN_REASON
    ]
    say(f"overrides (standing): {len(standing)}")
    if not terse:
        for rule_id, path, lineno, reason in standing:
            say(f"  rule-{rule_id} {path}:{lineno} — {reason}")
    for rule_id, path, lineno, reason in all_overrides():
        if len(reason) < MIN_REASON:
            # F2 (Vra, 2026-08-31): the remedy must be paste-able where the finding
            # lives — a `.ts` file's own reader must not be told to write `#`.
            marker = W.comment_token(W.kind_of_path(path, SCOPE_KINDS))
            record_violation(
                rule_id,
                f"{path}:{lineno}: override `{marker} rule-{rule_id}` with no reason — an "
                "escape hatch nobody has to justify is an off switch",
                path=path,
            )
    for note in notes:
        say(f"  {note}")


def main(argv: list[str]) -> int:
    diff_ref: str | None = None
    mode = "scan"
    terse = False
    explain_id: str | None = None
    args = list(argv)
    while args:
        arg = args.pop(0)
        if arg == "--selftest":
            mode = "selftest"
        elif arg == "--terse":
            terse = True
        elif arg == "--rules":
            mode = "listing"
        elif arg == "--explain":
            # `--explain` alone IS the listing: one printer, two names, so
            # `--rules` and a reader's bare `--explain` cannot come to
            # disagree about what the rule set is.
            if args and not args[0].startswith("-"):
                mode, explain_id = "explain", args.pop(0)
            else:
                mode = "listing"
        elif arg == "--diff":
            if not args:
                say("‼ --diff needs a ref")
                return 2
            diff_ref = args.pop(0)
        else:
            # A mistyped flag must never be a silently different run.
            say(
                f"‼ unknown argument {arg!r}: quality.gate takes --selftest, --diff <ref>, "
                "--terse, --explain [<id>] or --rules"
            )
            return 2

    # THE TWO READERS RETURN BEFORE ANYTHING MEASURES. `--explain` and the
    # listing read the parsed yaml and nothing else: they are how a builder
    # holding a red finds out what to do about it, so they must answer on a
    # tree whose plants are dirty or whose consistency is broken — the states
    # in which a reader most needs them.
    if mode == "listing":
        return rules_listing()
    if mode == "explain":
        return explain(str(explain_id))

    # BEFORE ANYTHING MEASURES ANYTHING. A tree carrying a dead run's fixtures
    # is a tree every leg below would read wrongly, and the failure is silent in
    # the direction that matters: a planted negative reports nothing at all.
    refuse_stale_plants()
    consistency()
    if mode == "selftest":
        if not broken:
            selftest()
    elif not broken:
        live_scan(diff_ref, terse=terse)

    seen: set[str] = set()
    deduped = [v for v in violations if not (v in seen or seen.add(v))]
    if broken:
        # NEVER SUPPRESSED BY `--terse`. Exit 2 outranks a pass, and a flag
        # whose whole job is to print less must not be able to print less of
        # the one section that says the enforcement itself stopped working.
        say("ENFORCEMENT BROKEN (exit 2 — outranks any pass):")
        for b in broken:
            say(f"  !! {b}")
    if deduped:
        say("Violations:")
        # Grouped by rule, in the order each rule first reported, so a rule
        # with twelve findings owes its reader ONE trailer rather than twelve.
        order: list[str] = []
        groups: dict[str, list[str]] = {}
        for v in deduped:
            rid = violation_rule.get(v, "")
            if rid not in groups:
                groups[rid] = []
                order.append(rid)
            groups[rid].append(v)
        for rid in order:
            for v in groups[rid]:
                say(f"  x {v}")
            for line in trailer_for(rid):
                say(line)
    if not broken and not deduped:
        if mode == "selftest":
            say("selftest clean: every canary fired, every negative stayed silent.")
        else:
            say(f"House rules: {len(RULES)} rules · all scopes bound · clean.")
    return 2 if broken else (1 if deduped else 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
