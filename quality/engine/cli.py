"""The command line: the standing section, the live scan, and main."""

from __future__ import annotations

import contextlib
import datetime
import io
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import NamedTuple

from quality import check_v1
from quality import checks as C
from quality import scan_ahead as SA
from quality import worlds as W
from quality.checks import REGISTRY
from quality.engine._hub import ROOT
from quality.reason_floor import MIN_REASON

# --- the command line: the standing section, the live scan, and main ------------------

#: A memo decline that names its own expiry rather than the input it cannot see.
_MEMO_PENDING = re.compile(r"\bpending\b|\bfor now\b|\bnot yet\b|\d{4}-\d{2}-\d{2}", re.I)
_VALVE_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
#: A valve's reason is held to rule 89's families plus the gate programme's own ids.
_VALVE_COORDINATE_RE = re.compile(
    C.COORDINATE_RE.pattern + r"|(?<![\w.$\-{/])(?:G-\d+|G\d+[a-z]+)(?![\w=}\-])"
)


class BacklogCensus(NamedTuple):
    """The standing section's totals: `declared`, the five backlog counters, tails, `frozen:`."""

    declared: int
    ratchet: int
    dated: int
    coordinate: int
    memo: int
    rerecord: int
    tails: int
    tail_rules: tuple[str, ...]
    frozen_classes: int
    frozen_recorded: int

    @property
    def backlog(self) -> int:
        return self.ratchet + self.dated + self.coordinate + self.memo + self.rerecord


def valve_backlog_kind(token: str, reason: str, today: str) -> str:
    """`dated` (its `— until` date is past), `coordinate` (names a plan id), or `declared`."""
    if W.trigger_is_past(W.valve_trigger(reason), today):
        return "dated"
    # A `coordinate:` valve's subject IS the id (rule 89's own valve).
    if token != "coordinate" and _VALVE_COORDINATE_RE.search(C._NOQA_CODES.sub("", reason)):  # noqa: S105 — a valve-kind word compared to a keyword, not a credential
        return "coordinate"
    return "declared"


def backlog_census(
    standing: list[tuple[str, str, int, str]],
    *,
    rules: list[dict] | None = None,
    held: dict[str, dict[str, tuple[int, int]]] | None = None,
    today: str | None = None,
) -> BacklogCensus:
    """Count the standing section's five closed questions; every other valve is `declared`."""
    rules = RULES if rules is None else rules
    held = HELD_BACKLOG if held is None else held
    today = today or datetime.date.today().isoformat()
    kinds = [valve_backlog_kind(token, reason, today) for token, _r, _l, reason in standing]
    by_id = {str(rule["id"]): rule for rule in rules}
    quiet = sorted(rid for rid in held if by_id.get(rid, {}).get("quiet_backlog"))
    frozen_rules = [rule for rule in rules if frozen_classes(rule) and rule.get("enabled", True)]
    recorded = [
        int(count)
        for rule in frozen_rules
        for klass, count in (rule.get("ratchets") or {}).items()
        if is_frozen(rule, str(klass))
    ]
    return BacklogCensus(
        declared=kinds.count("declared"),
        ratchet=sum(
            n for rid, classes in held.items() if rid not in quiet for n, _w in classes.values()
        ),
        dated=kinds.count("dated"),
        coordinate=kinds.count("coordinate"),
        memo=sum(1 for rule in rules if _MEMO_PENDING.search(memo_declines(rule) or "")),
        rerecord=recorded.count(0),
        tails=sum(w for rid in quiet for _n, w in held[rid].values()),
        tail_rules=tuple(quiet),
        frozen_classes=sum(len(frozen_classes(rule)) for rule in frozen_rules),
        frozen_recorded=sum(recorded),
    )


def backlog_census_lines(census: BacklogCensus) -> list[str]:
    """The three census lines, then the tails held apart from `backlog`."""
    lines = [
        f"declared: {census.declared}",
        f"backlog: {census.backlog} (ratchet {census.ratchet} · dated-past {census.dated} · "
        f"coordinate {census.coordinate} · memo-pending {census.memo} · frozen-rerecord "
        f"{census.rerecord})",
        f"frozen: {census.frozen_classes} class(es) · {census.frozen_recorded} recorded"
        f"{frozen_base_suffix()}",
    ]
    if census.tail_rules:
        lines.append(
            f"  tails: {census.tails} line(s) held under rule(s) "
            f"{', '.join(census.tail_rules)} (`quiet_backlog`) — counted apart from backlog"
        )
    return lines


def dated_valve_verdicts(
    standing: list[tuple[str, str, int, str]], today: str
) -> tuple[list[str], list[str], list[str]]:
    """(the dated valves' own lines, the past ones' exit-2 sentences, the coordinate reds)."""
    lines: list[str] = []
    past: list[str] = []
    named: list[str] = []
    for token, rel, line, reason in standing:
        trigger = W.valve_trigger(reason)
        if W.trigger_is_past(trigger, today):
            past.append(
                f"{rel}:{line}: the `{token}:` valve's trigger {trigger} is past (MOVE-TRIGGER "
                f"{trigger} fired) — do what it waited for and delete it, or write the new trigger"
            )
        elif _VALVE_DATE.fullmatch(trigger):
            lines.append(f"  until {trigger} · {token} {rel}:{line}")
        kind = valve_backlog_kind(token, reason, today)
        found = _VALVE_COORDINATE_RE.search(C._NOQA_CODES.sub("", reason))
        if kind == "coordinate" and found:
            named.append(
                f"{rel}:{line}: the `{token}:` valve names the plan coordinate "
                f"`{found.group(0)}` — say the reason in words; a trigger is a date or a sentence"
            )
    head = [f"dated: {len(lines) + len(past)} valve(s) carry a date"]
    return head + lines, past, named


def backlog_listing(ratchet: int) -> list[str]:
    """`--backlog`: one `rule · class · path:line · message` line per held finding, or exit 2."""
    lines = [
        f"rule {rid} · {klass or '(rule)'} · {f.path}:{f.line} · {f.msg}"
        for rid, klass, f in HELD_FINDINGS
    ]
    if len(lines) != ratchet:
        RUN.broken.append(
            f"--backlog printed {len(lines)} held finding(s) and `backlog:` counts ratchet "
            f"{ratchet} — the listing and the census disagree, so neither reads as the backlog"
        )
    return lines


def standing_section_lines(
    standing: list[tuple[str, str, int, str]],
    *,
    terse: bool,
    census: list[str] | None = None,
) -> list[str]:
    """The standing section as printed: one line per token, the total, the census, then each valve.

    Every named token a rule declares has its line, a zero included — a token
    with no line would read as one nobody counts — and `rule-<id>` valves are
    summed under one `rule-<id>` line, each listed with its rule below.
    """
    per_token: dict[str, int] = {token: 0 for token in named_valve_tokens()}
    per_token["rule-<id>"] = 0
    for token, _rel, _line, _reason in standing:
        key = "rule-<id>" if token.startswith("rule-") else token
        per_token[key] = per_token.get(key, 0) + 1
    lines = [f"valves (standing): {len(standing)}"]
    lines += [f"valves (standing): {token} {n}" for token, n in sorted(per_token.items())]
    lines += census or []
    if not terse:
        lines += [f"  {token} {rel}:{line} — {reason}" for token, rel, line, reason in standing]
    return lines


def scan_ahead_unmemoised() -> None:
    """Run every scan the memo will not answer across processes first; the loop replays them."""
    bypass = bool(memo_state.get("bypass") or os.environ.get("DJB_RULES_NO_MEMO"))
    ahead = [
        str(rule["id"])
        for rule in RULES
        if rule.get("enabled", True)
        and rule.get("check") in REGISTRY
        and (bypass or memo_declines(rule) is not None)
        and W.tree_verdict(ROOT, rule, SCOPE_KINDS)[0] not in ("broken", "skip")
    ]
    runners = [
        rule
        for rule in RULES
        if rule.get("enabled", True)
        and rule.get("runner")
        and W.tree_verdict(ROOT, rule, SCOPE_KINDS)[0] not in ("broken", "skip")
    ]
    processes, why = SA.workers()

    def run_ahead(rule: dict) -> object:
        try:
            return run_runner(rule)
        except check_v1.RunnerRefused as exc:
            return exc

    prefetched_runners.clear()
    with ThreadPoolExecutor(max_workers=processes) as threads:
        replies = {str(r["id"]): threads.submit(run_ahead, r) for r in runners}
        answers, dropped = SA.scan_ahead(ahead, processes)
        for rid, future in replies.items():
            try:
                prefetched_runners[rid] = future.result()
            except Exception:  # noqa: S112 — a failed prefetch leaves no entry; the rule runs its runner inline
                continue
    prefetched.clear()
    prefetched.update(answers)
    tail = f"; scanned in order: {', '.join(dropped)}" if answers and dropped else ""
    say(
        f"  scan-ahead: {len(answers)} of {len(ahead)} unmemoised rule(s) across "
        f"{processes if answers else 1} process(es), {len(prefetched_runners)} runner(s) on "
        f"threads ({why}){tail}"
    )


#: Each rule's kept findings this scan, by id: a class among them is breached, never headroom.
RUN_KEPT: dict[str, list[C.Finding]] = {}


def live_scan(diff_ref: str | None, *, terse: bool = False) -> None:
    # (line, status) — the status is carried beside the text rather than
    # re-derived from it, because `--terse` drops exactly the `ok` rows and a
    # reader of the count line has to be able to add them back up.
    per_rule: list[tuple[str, str]] = []
    counts = {"ok": 0, "RED": 0, "skipped": 0}
    memo_reset()
    HELD_BACKLOG.clear()
    RUN_KEPT.clear()
    scan_ahead_unmemoised()
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
            # (ruled 2026-08-31): a rule that could NOT look — its `broken.append`
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
        RUN_KEPT[rid] = kept
        shown = ", ".join(f"{k}={v}" for k, v in sorted(targets.items())) or "django-leg"
        status = "ok" if not kept and not any(r == rid for r, _ in django_findings) else "RED"
        counts[status] += 1
        per_rule.append((f"  rule {rid} {name}: {status} ({shown})", status))

    if diff_ref:
        apps = touched_apps(ROOT, diff_ref)
        for rule in RULES:
            if str(rule["id"]) not in RUN_KEPT:
                continue
            breached = {f.klass for f in RUN_KEPT[str(rule["id"])]}
            held = {
                k: v for k, v in HELD_BACKLOG.get(str(rule["id"]), {}).items() if k not in breached
            }
            ratchets = {k: v for k, v in (rule.get("ratchets") or {}).items() if k not in breached}
            for line in touched_headroom({**rule, "ratchets": ratchets}, held, apps):
                record_violation(str(rule["id"]), line)
    for problem in check_budgets():
        RUN.violations.append(problem)
    prose_lines, prose_problems, prose_notes = prose_verdicts()
    RUN.violations.extend(prose_problems)
    RUN.notes.extend(prose_notes)

    say(
        f"House rules: {len(RULES)} rules · {counts['ok']} ok · {counts['RED']} RED · "
        f"{counts['skipped']} skipped"
    )
    memo_report()
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

    standing = [row for row in standing_valves() if len(row[3]) >= MIN_REASON]
    census = backlog_census_lines(backlog_census(standing))
    dated, past, named = dated_valve_verdicts(standing, datetime.date.today().isoformat())
    for line in standing_section_lines(standing, terse=terse, census=census + dated):
        say(line)
    RUN.broken.extend(past)
    RUN.violations.extend(named)
    for line in prose_lines:
        say(line)
    # The yaml half of the same population: an allow-list entry is a valve
    # written in `quality/rules.yaml` instead of on the line it excuses.
    for line in allow_list_census():
        say(line)
    for rule_id, path, lineno, reason in all_overrides():
        if len(reason) < MIN_REASON:
            # (ruled 2026-08-31): the remedy must be paste-able where the finding
            # lives — a `.ts` file's own reader must not be told to write `#`.
            marker = W.comment_token(W.kind_of_path(path, SCOPE_KINDS))
            record_violation(
                rule_id,
                f"{path}:{lineno}: override `{marker} rule-{rule_id}` with no reason — an "
                "escape hatch nobody has to justify is an off switch",
                path=path,
            )
    for note in RUN.notes:
        say(f"  {note}")


#: THE ARGUMENT GRAMMAR, IN ONE STRING. Two refusals print it — an unknown
#: argument and a `--fold-map` with nothing after it — and two spellings of one
#: list is exactly how a flag comes to exist that no refusal mentions.
GRAMMAR = (
    "quality.gate takes --selftest [--rule <id>]... [--member [--whole]], --selftest-inputs, "
    "--diff <ref>, "
    "--fold-map <previous rules.yaml> [<template rules.yaml>] [--template-tree <dir>], "
    "--terse, --explain [<id>], --rules, --backlog or --plant-collisions"
)


def main(argv: list[str]) -> int:
    diff_ref: str | None = None
    fold_map_previous: str | None = None
    fold_map_template: str | None = None
    fold_map_template_tree: str | None = None
    mode = "scan"
    terse = False
    explain_id: str | None = None
    only_rules: list[str] = []
    member = whole = False
    args = list(argv)
    while args:
        arg = args.pop(0)
        if arg == "--selftest":
            mode = "selftest"
        elif arg == "--selftest-inputs":
            mode = "inputs"
        elif arg == "--terse":
            terse = True
        elif arg == "--backlog":
            mode = "backlog"
        elif arg == "--plant-collisions":
            mode = "plant-collisions"
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
        elif arg == "--fold-map":
            # THE ARGUMENT IS NOT OPTIONAL, and the refusal carries the command
            # that produces it. The reader runs on a tree in the middle of a
            # merge, where the file it needs is not on disk at all: a bare
            # `--fold-map` that fell back to anything would map the tree
            # against itself and print a rename list of no renames.
            if not args or args[0].startswith("-"):
                say(
                    "‼ --fold-map needs the path to your PREVIOUS quality/rules.yaml — the one "
                    "before the merge: `git show <your pre-merge sha>:quality/rules.yaml > "
                    "/tmp/previous-rules.yaml`. " + GRAMMAR
                )
                return 2
            mode, fold_map_previous = "fold-map", args.pop(0)
            # THE SECOND PATH IS THE TEMPLATE SIDE, AND IT IS OPTIONAL. Taking
            # it positionally rather than behind a flag is what keeps the
            # refusals' one-line remedy a line somebody pastes; a following
            # FLAG is still a flag, by the same test the first argument uses.
            if args and not args[0].startswith("-"):
                fold_map_template = args.pop(0)
        elif arg == "--template-tree":
            if not args or args[0].startswith("-"):
                say("‼ --template-tree needs a directory. " + GRAMMAR)
                return 2
            fold_map_template_tree = args.pop(0)
        elif arg == "--member":
            member = True
        elif arg == "--whole":
            whole = True
        elif arg == "--rule":
            # THE NARROWED SELF-TEST, one rule id per flag, repeatable. An id
            # that names no rule is refused here, before anything is planted: a
            # narrowed run over a typo would judge nothing and print a foot.
            if not args or args[0].startswith("-"):
                say("‼ --rule needs a rule id. " + GRAMMAR)
                return 2
            only_rules.append(args.pop(0))
        else:
            # A mistyped flag must never be a silently different run.
            say(f"‼ unknown argument {arg!r}: " + GRAMMAR)
            return 2

    if fold_map_template_tree is not None and mode != "fold-map":
        # A flag that only means something to one mode must never be a silently
        # ignored flag in another: the same law `--tesre` is refused under. THE
        # `mode` CLAUSE IS THE POINT AND IT WAS MISSING (F1, HOTFIX-RULEMAP-2F):
        # without it this guard fired on the one mode the flag EXISTS for, so
        # `--template-tree` was reachable from the function and dead from the
        # command line — the shape a pytest suite that calls `fold_map_lines`
        # and never `main` cannot see, which is why the case that pins it is an
        # sh probe through `main`s own argv dispatch.
        say("‼ --template-tree is only meaningful with --fold-map. " + GRAMMAR)
        return 2
    if only_rules and mode != "selftest":
        # The same law, for the same reason: `--rule` narrows a self-test and
        # means nothing to any other mode, so it is refused rather than ignored.
        say("‼ --rule is only meaningful with --selftest. " + GRAMMAR)
        return 2
    if (member and not only_rules) or (whole and not member):
        # A partition member is a narrowed run, and only one member carries the whole parts.
        say("‼ --member needs --rule, and --whole needs --member. " + GRAMMAR)
        return 2
    unknown_rules = [rid for rid in only_rules if rid not in RULES_BY_ID]
    if unknown_rules:
        say(
            f"‼ --rule {', '.join(unknown_rules)}: no rule with that id in this tree's plan "
            "(`python -m quality.gate --rules` lists them). " + GRAMMAR
        )
        return 2

    # THE FOUR READERS RETURN BEFORE ANYTHING MEASURES. `--explain`, the
    # listing, `--selftest-inputs` and `--fold-map` read the parsed yaml and the
    # tree's own file names, and nothing else: the first two are how a builder holding a
    # red finds out what to do about it, and the third is what a banked verdict
    # is keyed on — so all three must answer on a tree whose plants are dirty or
    # whose consistency is broken, the states in which a reader most needs them.
    # The inputs reader in particular must answer on a tree the self-test cannot
    # run on, or a could-not-look would silently become a cache hit.
    if mode == "listing":
        return rules_listing()
    if mode == "explain":
        return explain(str(explain_id))
    if mode == "inputs":
        return selftest_inputs()
    if mode == "fold-map":
        # The loudest case of all: a tree mid-merge, whose plants may be dirty
        # and whose consistency may be broken precisely BECAUSE the ids
        # collided. A reader that refused to answer there would be a reader
        # nobody could use on the only day they need it.
        return fold_map(str(fold_map_previous), fold_map_template, fold_map_template_tree)

    if mode == "plant-collisions":
        # THE PLANT-COLLISION CENSUS ALONE — the `--loop` leg's whole body, and
        # the self-test's head line run without the self-test. It reads the
        # plants and the tree under test and plants nothing; a tree carrying a
        # dead run's plants is refused first, because those plants would read
        # as names the tree serves. Exit 2 on any refusal (an undeclared
        # collision is a dead canary in waiting), 0 otherwise.
        refuse_stale_plants()
        if not RUN.broken:
            collision_refusals, collision_line = plant_collision_run()
            say(collision_line)
            RUN.broken.extend(collision_refusals)
        if RUN.broken:
            say("ENFORCEMENT BROKEN (exit 2 — outranks any pass):")
            for b in RUN.broken:
                say(f"  !! {b}")
            return 2
        say("plant collisions: clean — every colliding name is declared on its plant.")
        return 0

    # BEFORE ANYTHING MEASURES ANYTHING. A tree carrying a dead run's fixtures
    # is a tree every leg below would read wrongly, and the failure is silent in
    # the direction that matters: a planted negative reports nothing at all.
    refuse_stale_plants()
    consistency()
    # THE MEMO'S OWN SHAPE, refused in the same breath and for the same reason
    # every other declared field is: a `memo: no` nobody has to justify is an
    # off switch. It is a SIBLING of `consistency()` rather than a clause
    # inside it because the criteria that asked for the memo put `consistency()`
    # out of territory; the position in `main` is what makes it identical in
    # effect — before anything measures, and exit 2 outranks a pass.
    memo_consistency()
    if mode == "selftest":
        # THE SELF-TEST NEVER CONSULTS OR WRITES THE MEMO, and the line is
        # printed rather than assumed. Every canary plants a violation into the
        # real tree and demands its rule finds it; a rule that replayed a
        # banked answer would go green over a tree it never read, and the
        # dead-canary exit 2 this whole engine turns on would be the thing the
        # memo silenced. The proof that the bypass is real, rather than a
        # printed word, is `memo_census`'s planted FALSE entry below.
        memo_state["bypass"] = True
        say("memo: bypassed (selftest) — every rule scans; the memo is neither read nor written")
        if not RUN.broken:
            selftest(only_rules, member=member, whole=whole)
    elif mode == "backlog" and not RUN.broken:
        # The plain run, its output withheld: the listing is the whole of what prints.
        HELD_FINDINGS.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            live_scan(diff_ref, terse=terse)
        standing = [row for row in standing_valves() if len(row[3]) >= MIN_REASON]
        for line in backlog_listing(backlog_census(standing).ratchet):
            say(line)
    elif not RUN.broken:
        live_scan(diff_ref, terse=terse)

    seen: set[str] = set()
    deduped = [v for v in RUN.violations if not (v in seen or seen.add(v))]
    if RUN.broken:
        # NEVER SUPPRESSED BY `--terse`. Exit 2 outranks a pass, and a flag
        # whose whole job is to print less must not be able to print less of
        # the one section that says the enforcement itself stopped working.
        say("ENFORCEMENT BROKEN (exit 2 — outranks any pass):")
        for b in RUN.broken:
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
    if not RUN.broken and not deduped:
        if mode == "selftest" and member:
            say(
                f"selftest clean for member rule(s) {', '.join(narrowed_ids(only_rules))}"
                f"{' and the whole run' + chr(39) + 's own parts' if whole else ''} — one member "
                f"of the gate's verdict{_not_producible_clause()}."
            )
        elif mode == "selftest" and only_rules:
            say(
                f"selftest clean for rule(s) {', '.join(narrowed_ids(only_rules))} only — "
                f"not the gate's verdict{_not_producible_clause()}."
            )
        elif mode == "selftest":
            say(
                "selftest clean: every canary fired, every negative stayed silent"
                f"{_not_producible_clause()}."
            )
        elif mode != "backlog":
            say(f"House rules: {len(RULES)} rules · all scopes bound · clean.")
    return 2 if RUN.broken else (1 if deduped else 0)


from quality.engine.explain import (  # noqa: E402
    explain,
    record_violation,
    rules_listing,
    trailer_for,
)
from quality.engine.fold_map import fold_map  # noqa: E402
from quality.engine.memo import (  # noqa: E402
    memo_consistency,
    memo_declines,
    memo_report,
    memo_reset,
    memo_state,
    prefetched,
    prefetched_runners,
)
from quality.engine.plants import (  # noqa: E402
    consistency,
    plant_collision_run,
    refuse_stale_plants,
)
from quality.engine.prose import prose_verdicts  # noqa: E402
from quality.engine.readers import selftest_inputs  # noqa: E402
from quality.engine.rules import allow_list_census, frozen_base_suffix  # noqa: E402
from quality.engine.run import (  # noqa: E402
    HELD_BACKLOG,
    HELD_FINDINGS,
    all_overrides,
    apply_overrides,
    check_budgets,
    named_valve_tokens,
    run_django_leg,
    run_rule,
    run_runner,
    standing_valves,
    touched_apps,
    touched_headroom,
)
from quality.engine.selftest import _not_producible_clause, narrowed_ids, selftest  # noqa: E402
from quality.engine.world import (  # noqa: E402
    COULD_NOT_LOOK,
    RULES,
    RULES_BY_ID,
    RUN,
    SCOPE_KINDS,
    frozen_classes,
    is_frozen,
    say,
    violation_rule,
)
