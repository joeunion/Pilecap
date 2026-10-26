"""Overrides."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from apps.core.roads import road
from quality import check_v1
from quality import checks as C
from quality import worlds as W
from quality.checks import FLOOR_PROXIES, REGISTRY, CheckResult, Finding
from quality.could_not_look import CouldNotLook as PlantCollisionCouldNotLook
from quality.engine._hub import ROOT

# --- overrides -----------------------------------------------------------------


def _file_lines(path: Path) -> list[str]:
    try:
        return path.read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        return []


def override_at(path: Path, line: int, rule_id: str) -> W.Valve | None:
    """The valve claimed for rule_id at this line, or None when none is claimed.

    Read by `quality.worlds.comment_reason`, the one valve reader: on the
    flagged line itself or in the CONTIGUOUS comment block directly above it,
    and only where the marker opens a comment. The comment syntax comes from
    the FILE, through the scope kinds: a valve in a `.ts` file is
    `// rule-<id>: <reason>` and in a `.py` file the `#` form — one mechanism,
    one reason floor, never two grammars.
    """
    try:
        rel = str(path.relative_to(ROOT))
    except ValueError:
        rel = str(path)
    comment = W.comment_token(W.kind_of_path(rel, SCOPE_KINDS))
    return W.comment_reason(
        _file_lines(path), line, _one_rule_valve(comment, rule_id), comment=comment
    )


def _one_rule_valve(comment: str, rule_id: str) -> re.Pattern[str]:
    """`<comment> rule-<this id>: <reason>`, the reason the first group."""
    key = f"{comment}\0{rule_id}"
    cached = _OVERRIDE_RES.get(key)
    if cached is None:
        cached = re.compile(re.escape(comment) + rf"\s*rule-{re.escape(rule_id)}:\s*(.*)$")
        _OVERRIDE_RES[key] = cached
    return cached


def override_reaches(rule_id: str, rel: str) -> bool:
    """Can the rule this marker names report about this path at all?

    THE WALK IS THE UNION AND A VALVE IS NOT. `quality.worlds.kind_files` reads every scope
    kind on the tree — the template's two and any the drawer declares — because
    a valve has to be FINDABLE wherever one can be written. But a valve is an
    exemption FROM ONE RULE, and a rule's subject is its own kind's roots. So a
    product kind rooted at `docs/` with `comment: "#"` made every `# rule-13:`
    shaped line in this repository's prose an override of TEMPLATE rule 13 —
    standing overrides went 41 to 56, and two lines of documentation whose
    "reason" was shorter than `MIN_REASON` became findings recorded against
    rules 13 and 16. A product kind turned a green tree red on rules it does
    not own (measured 2026-09-22).

    AN ID NO RULE CLAIMS IS KEPT, never dropped: `rule-99` in a source file is
    somebody's mistake and some other census's finding, and a reach test that
    silently swallowed it would be this fix causing the next one.
    """
    rule = RULES_BY_ID.get(str(rule_id))
    if rule is None:
        return True
    roots = W.kind_roots(rule, SCOPE_KINDS)
    if not roots:
        return True
    for root in roots:
        base = str(root).rstrip("/")
        if rel == base or rel.startswith(base + "/"):
            return True
    return False


def _walked_lines() -> list[tuple[str, str, int, str]]:
    """(relpath, comment token, line, text) for every line of every file a valve may be written in.

    The kinds' walk (`quality.worlds.kind_files`, the files on the disk) read
    once, for both censuses below, so the `rule-<id>` valves and the named
    markers are counted over one population.
    """
    out: list[tuple[str, str, int, str]] = []
    for rels in W.kind_files(ROOT, SCOPE_KINDS, "fs").values():
        for rel in rels:
            comment = W.comment_token(W.kind_of_path(rel, SCOPE_KINDS))
            for lineno, text in enumerate(_file_lines(ROOT / rel), start=1):
                out.append((rel, comment, lineno, text))
    return out


@road("valve", example="quality/engine/cli.py::live_scan")
def all_overrides() -> list[tuple[str, str, int, str]]:
    """Every valve in the tree: one line excused with a reason, counted in the standing section.

    Answers (rule_id, relpath, line, reason) per `rule-<id>` marker that opens
    a comment — the line `quality.worlds.comment_reason` would honour. The
    walk is every kind's; the ATTRIBUTION is one rule's — see `override_reaches`
    for the difference and what it cost to learn.
    """
    found: list[tuple[str, str, int, str]] = []
    seen: set[tuple[str, int]] = set()
    for rel, comment, lineno, text in _walked_lines():
        m = override_re(comment).search(text)
        if m is None or (rel, lineno) in seen or not W.opens_comment(text, m.start(), comment):
            continue
        if not override_reaches(m.group(1), rel):
            continue
        seen.add((rel, lineno))
        found.append((m.group(1), rel, lineno, m.group(2).strip()))
    return sorted(found, key=lambda row: (row[1], row[2]))


#: The token half of a declared marker: `# reach: <reason>` → `reach`,
#: `<comment> rule-13: <reason>` → `rule-13`. A marker the pattern cannot read
#: is a token the standing section does not count, and `valve_lines` says so.
_MARKER_TOKEN = re.compile(r"^(?:<comment>|#|//)\s*([a-z][a-z0-9-]*):")


def marker_tokens(rule: dict) -> list[str]:
    """The valve tokens one rule's `valve.marker` declares, in its order."""
    marker = str((rule.get("valve") or {}).get("marker") or "")
    tokens: list[str] = []
    for part in marker.split(" · "):
        m = _MARKER_TOKEN.match(part.strip())
        if m:
            tokens.append(m.group(1))
    return tokens


def named_valve_tokens() -> dict[str, str]:
    """Every named marker token (never `rule-<id>`) a rule declares, to the first declarer."""
    named: dict[str, str] = {}
    for rule in RULES:
        for token in marker_tokens(rule):
            if not re.fullmatch(r"rule-[a-z0-9-]+", token):
                named.setdefault(token, str(rule["id"]))
    return named


@road("valve_census", example="quality/engine/cli.py::live_scan")
def standing_valves() -> list[tuple[str, str, int, str]]:
    """The standing section: every valve the tree holds, under every token a rule declares.

    Answers (token, relpath, line, reason): each named marker any rule's
    `valve.marker` declares (`authz`, `reach`, `door`, …), read where it opens
    a comment by `quality.worlds.valve_on_line` — the one valve reader — plus
    the generic `rule-<id>` override, whose token is `rule-<id>`. A marker no
    rule declares is not counted (`valve_lines` prints the declared blind spot).
    """
    found = [(f"rule-{rid}", rel, line, reason) for rid, rel, line, reason in all_overrides()]
    patterns = {token: {} for token in named_valve_tokens()}
    for rel, comment, lineno, text in _walked_lines():
        if comment not in text:
            continue
        for token, cache in patterns.items():
            pattern = cache.get(comment)
            if pattern is None:
                pattern = re.compile(re.escape(comment) + rf"\s*{re.escape(token)}:\s*(.*)$")
                cache[comment] = pattern
            valve = W.valve_on_line(text, pattern, comment=comment)
            if valve is not None:
                found.append((token, rel, lineno, valve.reason))
    return sorted(found, key=lambda row: (row[1], row[2], row[0]))


def apply_overrides(rule_id: str, findings: list[Finding]) -> tuple[list[Finding], list[Finding]]:
    """(kept, suppressed). A bare override becomes its own finding, kept."""
    kept: list[Finding] = []
    suppressed: list[Finding] = []
    for finding in findings:
        valve = override_at(ROOT / finding.path, finding.line, rule_id)
        if valve is None:
            kept.append(finding)
        elif valve.holds:
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


#: The sha the recording line is stamped with, read once per process. A
#: recording says WHEN a count was true, and the only honest answer is the tree
#: the count was measured on.
_RECORDING_SHA: str | None = None


def recording_sha() -> str:
    """This checkout's HEAD, short — the stamp on a `recorded-at` line.

    A literal `<sha>` when git cannot answer (an exported tree, a tarball): the
    line is still the line to paste, and a reader who has no git has no sha to
    put in it either.
    """
    global _RECORDING_SHA
    if _RECORDING_SHA is None:
        _RECORDING_SHA = "<sha>"
        try:
            done = subprocess.run(
                ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if done.returncode == 0 and done.stdout.strip():
                _RECORDING_SHA = done.stdout.strip()
        except Exception:  # noqa: S110 — no git, no repository, no answer — the literal stands
            pass
    return _RECORDING_SHA


def unmeasured_app(klass: str, findings: list[Finding], root: Path = ROOT) -> str | None:
    """The PRODUCT app this ratchet class belongs to, or None (ADR gate-6).

    THE SUBJECT. Per-app ratchet classes are keyed `<app>` or `<app>.<what>`,
    and every recorded one names an app the TEMPLATE ships. A product's own app
    has no entry, and an absent entry is a ratchet of zero — which is the right
    answer for a template app (a clean class stays clean by absence) and an
    unreadable one for a product's (nothing anywhere says the class exists, what
    the grammar is, or that recording it is allowed at all).

    THE APP IS CONFIRMED BY THE FINDINGS, never inferred from the key alone.
    `nonconforming` and `secrets` are class names, not app names, and a
    predicate that read the key on its own would offer to record an app that
    does not exist. So a class is app-keyed only when EVERY finding in it sits
    under `apps/<label>/` for the label the key opens with — fail closed, and the
    tree is read only to refuse a directory that holds no `apps.py`.

    Three ways this answers None, all deliberate: an app INSIDE the partition
    (the template's own — absence is the measurement), the plant scaffold
    (`apps/zzz_canary` exists only between `Plant.put` and `Plant.restore`, and
    a recording for it would name an app nobody can open), and a run that could
    not read the partition at all (`_read_platform_apps`).
    """
    if PLATFORM_APPS is None:
        return None
    label = str(klass).split(".", 1)[0].strip()
    if not label or label == PROBE_APP or label in PLATFORM_APPS:
        return None
    # A directory under apps/ that is not an app is the apps root's (`_app_dirs`'s predicate).
    folder = root / "apps" / label
    if folder.is_dir() and folder not in C._app_dirs(root):
        return None
    prefix = f"apps/{label}/"
    if not findings:
        return None
    if not all(str(finding.path).replace("\\", "/").startswith(prefix) for finding in findings):
        return None
    return label


def unmeasured_line(rid: str, klass: str, app: str, count: int) -> str:
    """The finding an unmeasured class prints — `quality.worlds.unmeasured_note`, stamped."""
    rule = RULES_BY_ID.get(str(rid))
    if rule is not None and is_member_rule(rule):
        return member_unmeasured_line(rid, klass, app, count)
    return W.unmeasured_note(rid=rid, klass=klass, app=app, count=count, stamp=recording_sha())


def member_unmeasured_line(rid: str, klass: str, app: str, count: int) -> str:
    """A product app's unrecorded member class: the tails to delete, or the line to paste."""
    if RULES_BY_ID.get(str(rid), {}).get("inflow") == "refused":
        return (
            f"class {klass!r} has no floor, and rule {rid} records none for a new member "
            f"(`inflow: refused`) — apps/{app} is judged at zero: DELETE the {count} line(s), "
            "or cite the decision by id; a floor holds only the debt the template shipped "
            "with. The whole class follows:"
        )
    return (
        f"class {klass!r} has NEVER BEEN MEASURED — apps/{app} is outside the partition "
        f"(quality/partition.yaml `platform_apps`) and its `ratchet_floors` names no "
        f"`{rid}.{klass.partition('.')[2]}`; an absent floor is a ceiling of zero, which is "
        f"unreadable for an app the template did not ship (ADR gate-6). RECORD IT — in "
        f"apps/{app}/apps.py, on the AppConfig's `ratchet_floors`, paste:  "
        f'"{rid}.{klass.partition(".")[2]}": {count},  # recorded-at {recording_sha()} [fold]'
        f"  — once, from the fold that brought the app in; after it the class moves DOWN "
        f"only, in a diff a reviewer reads. The whole class follows:"
    )


def weight(findings: list[Finding]) -> int:
    """The counted units a class holds — each finding's `weight`, summed."""
    return sum(int(getattr(finding, "weight", 1)) for finding in findings)


def drawer_ratchetable_class(rule_id: str, klass: str, rule: dict) -> bool:
    """May a PRODUCT record its own count for this class, in its own drawer?

    The mirror of the acceptance branch in `_merge_local_ratchets`, and it has
    to be a predicate rather than a comment because a finding that cannot say
    "you may record this" leaves the product to reverse-engineer the grammar —
    which is the whole of ADR gate-6's context, reappearing one class-kind
    over. True for a TEMPLATE rule's own FINDING class: one the rule declares
    under its `ratchets:` whose name is not an app on this tree (an app-keyed
    class takes `unmeasured_app`'s route, and a PLATFORM app's ceiling is the
    template's under the partition).
    """
    if is_local_rule(rule_id):
        return False
    if str(klass) not in {str(k) for k in (rule.get("ratchets") or {})}:
        return False
    if is_frozen(rule, str(klass)):
        return False
    return not (ROOT / "apps" / str(klass).split(".", 1)[0]).is_dir()


def finding_class_line(rid: str, klass: str, recorded: int, count: int) -> str:
    """The `recorded-at` paste line for a template rule's own finding class.

    `unmeasured_line`'s sibling, and the reason it exists: `unmeasured_app`
    answers None for a class that is not app-keyed, so `literal` — rule 50's
    own class, the one a product folding v2.1.2 actually had a backlog in —
    printed no paste line at all and the product typed its number by hand.
    """
    mine = max(0, count - recorded)
    return (
        f"class {klass!r} is at {count} violations against rule {rid}'s own recorded ceiling "
        f"of {recorded} — this is a TEMPLATE rule's FINDING class, not an app: the template "
        f"measured its own tree at {recorded} and yours is the backlog on top of it. RECORD "
        f"YOURS — in quality/local/rules.yaml, YOUR drawer, under its top-level `ratchets:`, "
        f'under `"{rid}":`, paste:  {klass}: {mine}  # recorded-at {recording_sha()} [fold]'
        f"  — the drawer's number is ADDED to the template's {recorded} and never replaces "
        f"it, so the template's measurement stays the template's to move; the recording "
        f"belongs to the fold that brought your code in, and after it the class moves DOWN "
        f"only, by a person's hand, in a diff a reviewer reads (ADR gate-6). The whole class "
        f"follows:"
    )


@road("bound", example="quality/engine/run.py::run_rule")
def apply_ratchets(rule: dict, kept: list[Finding]) -> list[Finding]:
    """Findings within a recorded backlog are notes; one over it, all of them fail.

    Counted per CLASS (`Finding.klass`), so a backlog of nine badly named
    selectors cannot pay for one badly named model. A class with no recorded
    ratchet is ratcheted at zero — the ordinary case, where the first finding
    is a violation.

    AND WHEN THE CLASS IS A PRODUCT APP'S, the zero says so out loud (ADR
    gate-6). An app outside `quality/partition.yaml`'s partition with no entry
    on this rule is UNMEASURED rather than clean: the findings still fail,
    exactly as before, and the header they arrive under is the `ratchets:` line
    to paste, stamped with the sha it was true at. See `unmeasured_app` for
    which classes qualify and `unmeasured_line` for what the header says.
    """
    rid = str(rule["id"])
    recorded = rule.get("ratchets") or {}
    #: The class names this rule has WRITTEN DOWN, whatever their value. A
    #: recorded 0 is a measurement; an absent key is the thing ADR gate-6 is
    #: about, and `recorded.get(klass, 0)` cannot tell the two apart.
    named = {str(key) for key in recorded}
    by_class: dict[str, list[Finding]] = {}
    for finding in kept:
        by_class.setdefault(finding.klass, []).append(finding)
    out: list[Finding] = []

    def bound_of(klass: str, measured: int, allowed: int) -> W.Bound:
        label = klass or "(rule)"
        return W.Bound(
            direction="ceiling",
            recorded=allowed,
            measured=measured,
            home=(
                f"{ratchet_home(rid, label)} `ratchet_floors`"
                if ratchet_home(rid, label).endswith("/apps.py")
                else f"{ratchet_home(rid, label)}, rule {rid} `ratchets:`"
            ),
            klass=ratchet_paste_key(rid, label) if klass else label,
            subject=f"rule {rid} ratchet: class {label}",
            word="ratchet",
        )

    for klass, findings in sorted(by_class.items()):
        allowed = int(recorded.get(klass, 0)) if klass else 0
        label = klass or "(rule)"
        bound = bound_of(str(klass), weight(findings), allowed)
        frozen = bool(klass) and is_frozen(rule, str(klass))
        if bound.breached:
            parts = DRAWER_RATCHET_PARTS.get((rid, str(klass)))
            # THE FINDING IS HOMED WHERE THE NUMBER IS WRITTEN, and it says
            # which half of a summed ceiling is whose — "past the recorded
            # ratchet of 12" sends a reader looking for a 12 that is written in
            # neither file once the template's own count is non-zero.
            home = ratchet_home(rid, str(klass)) if klass else "quality/rules.yaml"
            split = f" (template {parts[0]} + drawer {parts[1]})" if parts else ""
            if frozen and allowed:
                # A frozen class offers no paste line: its number only falls.
                out.append(
                    Finding(
                        home,
                        0,
                        f"{bound.breach_clause()}{split}. The class is FROZEN (rule {rid} "
                        "`frozen:`) — its number may only fall, so fix the new finding; "
                        "there is no line to paste. The whole class follows:",
                        klass,
                    )
                )
            elif frozen:
                pass  # the zero state: the findings fail, and nothing is offered to record
            elif allowed:
                out.append(
                    Finding(
                        home,
                        0,
                        f"{bound.breach_clause()}{split}. Fix the new one, or reduce another; "
                        f"raising the number is a diff a reviewer reads, in {home}. The whole "
                        "class follows:",
                        klass,
                    )
                )
            elif klass and drawer_ratchetable_class(rid, str(klass), rule):
                # A TEMPLATE RULE'S OWN FINDING CLASS, recorded at 0 and now
                # over it. `unmeasured_app` answers None here — the class names
                # no app and never will — so before this branch the product got
                # the findings and no line to paste anywhere.
                out.append(
                    Finding(
                        "quality/local/rules.yaml",
                        0,
                        finding_class_line(rid, str(klass), allowed, weight(findings)),
                        klass,
                    )
                )
            elif klass and str(klass) not in named:
                # UNMEASURED, not zero (ADR gate-6). The verdict is the same
                # exit 1 it already was — what changes is that the header now
                # says the class exists, why it has no ceiling, and the exact
                # line that gives it one. A class the product HAS recorded at
                # zero is measured and takes the ordinary path above.
                app = unmeasured_app(str(klass), findings)
                if app is not None:
                    out.append(
                        Finding(
                            "quality/rules.yaml",
                            0,
                            unmeasured_line(rid, str(klass), app, weight(findings)),
                            klass,
                        )
                    )
            out.extend(findings)
        else:
            held = HELD_BACKLOG.setdefault(rid, {})
            held[str(klass)] = (len(findings), weight(findings))
            RUN.notes.append(
                f"rule {rid} ratchet: class {label} at {weight(findings)} of the recorded "
                f"{allowed} — standing backlog, not a pass; nothing new landed."
            )
            if not RULES_BY_ID.get(rid, {}).get("quiet_backlog"):
                for finding in findings:
                    RUN.notes.append(f"    backlog {finding}")
                    HELD_FINDINGS.append((rid, str(klass), finding))
            room = W.room_note(bound)
            if room:
                RUN.notes.append("    " + room.replace("\n", "\n    "))
    for klass, allowed in sorted(recorded.items()):
        # A class that has gone all the way to clean is the one worth saying
        # out loud, and it is the one no finding would mention.
        if str(klass) not in by_class and int(allowed) > 0:
            if is_frozen(rule, str(klass)):
                RUN.notes.append(
                    f"rule {rid} ratchet: frozen class {klass} measured 0, below its recorded "
                    f"{allowed} ({ratchet_home(rid, str(klass))}) — delete its line; the "
                    "class stays in `frozen:` and its zero state has no number."
                )
                continue
            room = W.room_note(bound_of(str(klass), 0, int(allowed)))
            if room:
                RUN.notes.append(room)
    return out


#: Rule id → class → (findings, weight) held as notes under a recorded number this run.
HELD_BACKLOG: dict[str, dict[str, tuple[int, int]]] = {}

#: Each held finding of a rule that is not `quiet_backlog`, as (rule id, class, finding).
HELD_FINDINGS: list[tuple[str, str, Finding]] = []


def touched_apps(root: Path, ref: str) -> set[str]:
    """The app labels a change since `ref` touches, untracked files included; git's answer."""
    listed = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-only", ref],
        capture_output=True,
        text=True,
    ).stdout.split()
    listed += subprocess.run(
        ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard", "--", "apps"],
        capture_output=True,
        text=True,
    ).stdout.split()
    return {p.split("/")[1] for p in listed if p.startswith("apps/") and p.count("/") >= 2}


def touched_headroom(rule: dict, held: dict[str, tuple[int, int]], apps: set[str]) -> list[str]:
    """Each class an app this change touches records above what the tree holds (rule 91's form)."""
    rid = str(rule["id"])
    out: list[str] = []
    for klass, allowed in sorted((rule.get("ratchets") or {}).items()):
        home = ratchet_home(rid, str(klass))
        app = home.split("/")[1] if home.startswith("apps/") else ""
        if app not in apps or (world_module().RULE_ID_NAMESPACE and app in PLATFORM_APPS):
            continue
        count = held.get(str(klass), (0, 0))[1]
        if count < int(allowed):
            out.append(
                f"rule {rid} ratchet: class {str(klass)!r} is recorded at {allowed} and this tree"
                f" holds {count} — headroom in an app this change touches. Lower it to {count}"
                f" in {home}"
            )
    return out


# --- running one rule ----------------------------------------------------------


def local_runner_argv(impl: str) -> list[str] | None:
    """`check: <name>` as a check-v1 runner in the drawer, or None.

    THE SECOND HALF OF ONE RESOLVER. `check:` has always named an entry
    in `quality.checks.REGISTRY`, and a product may not edit `quality/checks/` — it
    is template-owned, and a product's check in it is a conflict in the one
    file whose conflicts are worst. So a name the registry does not hold is
    looked for ONCE more, as `quality/local/runners/<name>.py`, and invoked
    across the check-v1 process boundary exactly as a `runner:` rule is: the
    runner MEASURES, this engine JUDGES, and a runner that cannot be believed
    is exit 2 rather than zero findings.

    Neither a registry name nor a file here is a refusal that names both
    places it looked — `resolve_check_problem` below is that sentence, and it
    is the ONLY place either reader decides a `check:` is unresolvable.
    """
    path = world_module().LOCAL_RUNNER_DIR / f"{impl}.py"
    if not path.is_file():
        return None
    # Checkout-relative when it is inside the checkout — which is the only
    # place a real drawer sits, and what makes the refusal messages readable —
    # and absolute otherwise, so a probe that points `LOCAL_RUNNER_DIR` at a
    # tempdir it built gets an answer rather than a traceback.
    try:
        where = str(path.relative_to(ROOT))
    except ValueError:
        where = str(path)
    return ["python3", where]


def resolve_check_problem(rule_id: str, impl: str) -> str | None:
    """Why this `check:` resolves to nothing on this tree, or None."""
    if impl in REGISTRY:
        return None
    if local_runner_argv(impl) is not None:
        return None
    return (
        f"rule {rule_id}: check impl {impl!r} resolves to nothing — it is not a name in "
        f"the REGISTRY of quality/checks/ and there is no check-v1 runner at "
        f"quality/local/runners/{impl}.py. A product never edits quality/checks/ (it is "
        "template-owned and a fold overwrites it): write the runner in the drawer, or "
        "re-scope a registry check the template already ships"
    )


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
        remedy=drawer_roots_remedy(str(rule["id"])),
    )


def run_rule(
    rule: dict, *, floors: bool = True, ratchets: bool = True
) -> tuple[list[Finding], dict, str]:
    """The rule's check + override + ratchet pipeline. (violations, targets, skip).

    `ratchets=False` is the self-test's read: check + `apply_overrides` and NO
    ratchet, because a planted form is judged by the findings it ADDS to the
    tree (`form_delta`), and a verdict read through the ratchet makes a form's
    liveness a function of the tree's backlog — dead on a product that paid a
    debt, alive on one that did not. The ratchet has its own proof
    (`ratchet_leg`) and is not consulted here.

    `skip` is empty for a rule that ran; a SKIPPED sentence for a rule about a
    tree this checkout does not have; and a `COULD_NOT_LOOK`-prefixed sentence
    (ruled 2026-08-31) for a rule that could not be run at all — its tree present
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
        RUN.broken.append(f"rule {rid}: {why}")
        return [], targets, COULD_NOT_LOOK + why
    absent = verdict == "skip"
    impl = rule.get("check")
    if impl and not absent:
        unresolved = resolve_check_problem(rid, impl)
        if unresolved:
            RUN.broken.append(unresolved)
            return [], targets, COULD_NOT_LOOK + unresolved
        if impl in REGISTRY:
            # THE ONE CONSULT. `memo_consult` either replays this rule's last
            # answer for a key nothing has moved, or calls the check and banks
            # it — and everything below this line runs either way, so no memo
            # can hide an unbound floor, a ratchet that grew or a valve that
            # lost its reason. See THE PER-RULE MEMO, below.
            try:
                result: CheckResult = memo_consult(rule, impl)
            except PlantCollisionCouldNotLook as exc:
                # A CHECK THAT COULD NOT LOOK — an input it imports would not
                # import, a population it reads would not read — outranks a
                # pass and is never zero findings: exit 2, naming the rule.
                RUN.broken.append(f"rule {rid}: COULD NOT LOOK — {exc}")
                return [], targets, COULD_NOT_LOOK + str(exc)
        else:
            # THE DRAWER'S RUNNER, across the same process boundary a
            # `runner:` rule crosses, and refused the same way: a runner that
            # will not answer is could-not-look, never zero findings.
            argv = local_runner_argv(str(impl)) or []
            try:
                result = check_v1.invoke(
                    ROOT,
                    argv=argv,
                    roots=W.kind_roots(rule, SCOPE_KINDS),
                    where=f"rule {rid} local runner {' '.join(argv)!r}",
                    remedy=drawer_roots_remedy(rid),
                    timeout=int(
                        (rule.get("runner") or {}).get("timeout") or check_v1.DEFAULT_TIMEOUT
                    ),
                )
            except check_v1.RunnerRefused as exc:
                RUN.broken.append(f"rule {rid}: LOCAL RUNNER REFUSED ({exc.klass}) — {exc.detail}")
                return [], targets, COULD_NOT_LOOK + f"({exc.klass}) {exc.detail}"
        targets.update(result.targets_matched)
        findings.extend(result.findings)
    if rule.get("runner") and not absent:
        try:
            ahead = prefetched_runners.pop(rid, None)
            if isinstance(ahead, check_v1.RunnerRefused):
                raise ahead
            reply = ahead if ahead is not None else run_runner(rule)
        except check_v1.RunnerRefused as exc:
            # COULD NOT LOOK, and it outranks a pass. Reported and the rule
            # produces nothing — never zero findings, which is the shape a
            # broken instrument would otherwise wear.
            RUN.broken.append(f"rule {rid}: RUNNER REFUSED ({exc.klass}) — {exc.detail}")
            return [], targets, COULD_NOT_LOOK + f"({exc.klass}) {exc.detail}"
        targets.update(reply.targets_matched)
        findings.extend(reply.findings)
    proxy = rule.get("floor_proxy")
    if proxy and not absent:
        targets.update(FLOOR_PROXIES[proxy](ROOT, rule).targets_matched)
    kept, _suppressed = apply_overrides(rid, findings)
    if ratchets:
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
            # A scope floor is a `Bound` the scan may not fall under. It prints
            # no room note: a floor sits under the measurement on purpose (it
            # binds the SCAN, not this week's count), so growth past it is the
            # ordinary state, never news.
            bound = W.Bound(
                direction="floor",
                recorded=expected,
                measured=int(matched),
                home=f"quality/rules.yaml rule {rid} `floors:`",
                klass=str(key),
                subject=f"rule {rid} floor {key}",
                word="floor",
            )
            if bound.breached:
                paid = (
                    ""
                    if expected == int(floor)
                    else (
                        f" (recorded {floor}, lowered to {expected} — "
                        f"{', '.join(sorted(DISABLED_APPS))} is not in this deployment)"
                    )
                )
                RUN.broken.append(
                    f"rule {rid}: UNBOUND — {key}={matched} below floor {expected}{paid}; "
                    "the check may be watching nothing"
                )
    return kept, targets, why if absent else ""


# --- the Django system-check leg -------------------------------------------------


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
        m = DJANGO_ID_RE.search(line)
        if m:
            rule_id = DJANGO_ID_TO_RULE.get(m.group(1), m.group(1))
            found.append((rule_id, line.strip()))
    if proc.returncode != 0 and not found:
        RUN.broken.append(
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

    from apps.core.scaffold.copier import FENCE_LINE

    service_lengths: dict[str, tuple[int, str]] = {}
    for path in W.service_modules(ROOT):
        rel = path.relative_to(ROOT)
        # A `services/` package is ONE subject, keyed by its directory.
        package = rel.name != W.SERVICE_MODULE
        subject = rel.parent if package else rel
        if len(subject.parts) != 3:
            continue  # an app's own service module only; a nested `services.py` is no subject
        tree = C._parse(path)
        if tree is None:
            continue
        key = str(subject)
        source = W.read_text(path).splitlines()
        longest, label = service_lengths.get(key, (0, ""))
        functions = 0
        for node in tree.body:
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                functions += 1
                end = node.end_lineno or node.lineno
                # A `golden:` fence line is a marker, never a line of the function (rule 91).
                fences = sum(1 for line in source[node.lineno - 1 : end] if FENCE_LINE.match(line))
                measured = end - node.lineno + 1 - _docstring_lines(node) - fences
                if measured > longest or not label:
                    longest = max(longest, measured)
                    where = f"{path.name}::" if package else ""
                    label = f"{where}{node.name} (lines {node.lineno}-{end})"
        # Counted, never inferred from the label: a function whose whole body is
        # its docstring measures 0, and reading "no label" as "no function"
        # would let that one module out of the population it belongs to.
        if functions == 0:
            continue
        service_lengths[key] = (longest, label)
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


#: The worked-example apps: their ceilings advise everywhere and never refuse (ADR gate-5).
EXAMPLE_BUDGET_APPS = ("apps/example/", "apps/example_portal/")


def check_budgets(recorded: dict | None = None) -> list[str]:
    """Every budget refusal; a worked-example breach is printed, never refused."""
    # Printed, never a RUN.notes entry: the fold reads every note there as a lowering.
    if recorded is None:
        recorded = W.read_budgets(ROOT) or None
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
            else:
                bound = W.Bound(
                    direction="ceiling",
                    recorded=int(ceiling),
                    measured=int(value),
                    home=f"quality/budgets.yaml `{section}:`",
                    klass=str(key),
                    subject=f"budget note: {section} {named}",
                    word="ceiling",
                )
                if bound.breached and key.startswith(EXAMPLE_BUDGET_APPS):
                    print(
                        f"budget advisory: {section} {named} grew to {value}, past the template's"
                        f" ceiling {ceiling} — example (advisory): the worked"
                        " example's ceilings advise, never refuse",
                        flush=True,
                    )
                elif bound.breached:
                    problems.append(
                        f"budget: {section} {named} grew to {value}, past the recorded ceiling "
                        f"{ceiling} — shrink it, or raise the ceiling in quality/budgets.yaml "
                        "in a diff a reviewer sees. The line to paste, verbatim:\n"
                        f"  {key}: {value}"
                    )
                room = W.room_note(bound)
                if room:
                    RUN.notes.append(room)
    return problems


from quality.engine.memo import memo_consult, prefetched_runners  # noqa: E402
from quality.engine.world import (  # noqa: E402
    _OVERRIDE_RES,
    COULD_NOT_LOOK,
    DISABLED_APPS,
    DJANGO_ID_RE,
    DJANGO_ID_TO_RULE,
    DRAWER_RATCHET_PARTS,
    PLATFORM_APPS,
    PROBE_APP,
    RULES,
    RULES_BY_ID,
    RUN,
    SCOPE_KINDS,
    drawer_roots_remedy,
    is_frozen,
    is_local_rule,
    is_member_rule,
    override_re,
    ratchet_home,
    ratchet_paste_key,
    world_module,
)
