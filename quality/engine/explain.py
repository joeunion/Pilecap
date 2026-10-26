"""The trailer: what a RED owes its reader."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from quality import worlds as W
from quality.engine._hub import ROOT
from quality.ratchet_debt import debt_of

# --- main ------------------------------------------------------------------------


# --- the trailer: what a RED owes its reader ------------------------------------
#
# THE DEFECT (the consumer's ranked first cost). A finding
# printed `rule 13: apps/<paper>/services.py:42: <msg>` and stopped. Every other
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


def remedy_pointer(rid: str) -> str:
    """The tail a finding carries when its rule declares `remedies:` (ADR gate-6).

    A ratcheted rule's classes are the shapes it refuses, and each one has a
    FIX FORM — the spelling that makes the finding go away honestly. Those live
    in the rule's `remedies:` block, which `--explain` prints, and the finding
    itself carries the one-word route to them: a red that names its own reader
    is a red a builder can act on without going to look for the rule.
    """
    rule = RULES_BY_ID.get(rid) or {}
    if not rule.get("remedies"):
        return ""
    return f" · fix form: --explain {rid}"


#: The two files a RATCHET HEADER is pathed at. A header is not a valvable
#: finding — there is no comment you can write in a rules file to excuse a
#: backlog — so it must not contribute a valve token to its rule's trailer.
#: Before rules 50-53 declared their finding classes no js rule had a ratchet,
#: so no js rule had ever carried a yaml-pathed row; the day one did, rule 52's
#: block printed a `# rule-52:` line for findings that were all `.ts`, which is
#: precisely the defect `valve_lines`' per-finding-kind substitution exists to
#: prevent (found by `case_a_frontend_finding_prints_the_slash_valve_token`).
RATCHET_HEADER_PATHS: frozenset[str] = frozenset({"quality/rules.yaml", "quality/local/rules.yaml"})


def record_violation(rid: str, finding: object, *, path: str = "") -> None:
    """Append a finding AND remember whose it is, so the trailer can group."""
    text = f"rule {rid}: {finding}{remedy_pointer(rid)}"
    RUN.violations.append(text)
    violation_rule[text] = rid
    if path and str(path) not in RATCHET_HEADER_PATHS:
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
    # THE CLAIM FOLLOWS THE CENSUS: "(counted and printed)" only where the
    # standing section counts every token this marker declares.
    counted = len(marker_tokens(rule)) == len(marker.split(" · "))
    tail = (
        "(counted and printed)"
        if counted
        else "(not counted — declared blind spot of the standing section)"
    )
    out: list[str] = []
    for token in present:
        line = f"    valve:  {marker.replace('<comment>', token)} — {where} {tail}"
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
                RUN.broken.append(
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
        # `[local]` is the drawer's tag and it is printed by BOTH readers: a
        # reader holding a red has to be able to tell whose rule refused them,
        # because the remedy differs (a template rule is the template's to
        # argue with; a drawer rule is the product's own). On a tree with no
        # drawer no line carries it, which is what makes the absent-drawer
        # negative a byte-identical `cmp`.
        mark = "  [local]" if is_local_rule(rid) else ""
        mark += "" if rule.get("enabled", True) else "  [DISABLED]"
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
    home = " · [local]" if is_local_rule(rid) else ""
    say(f"rule {rid} · {rule.get('name', '')} · {enabled}{home}")
    if home:
        say(
            "  home: quality/local/rules.yaml — this product's drawer; its fixtures are "
            f"under quality/local/{{canary,negative}}/{rid}/"
        )
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
    if rule.get("debt"):
        say(debt_of(rule, rule.get("ratchets") or {}).sentence())
    if is_member_rule(rule):
        say(f"member floors ({', '.join(rule['member_classes'])}), each with its home:")
        for klass, count in sorted((rule.get("ratchets") or {}).items()):
            source = MEMBER_FLOOR_SOURCES.get((rid, str(klass)), ratchet_home(rid, str(klass)))
            say(f"  {klass}: {count}  ({source})")
    elif rule.get("ratchets"):
        say(f"ratchets: {rule['ratchets']}")
    if rule.get("frozen"):
        say(
            f"frozen: {', '.join(str(k) for k in rule['frozen'])} — a recorded number may only "
            "fall; at zero its line is deleted and a finding is a violation with no paste line"
        )
    declined = memo_declines(rule)
    if declined is not None:
        say(f"memo: no — {' '.join(declined.split())}")
    elif rule.get("check"):
        say(f"memo: {memo_contract()}")
    # ONE LINE PER FINDING CLASS, and each one is a fix form rather than a
    # restatement of the rule (ADR gate-6). `*` is the catch-all a rule whose
    # classes are per-app declares: one remedy, every class.
    for klass, text in (rule.get("remedies") or {}).items():
        say(f"remedies: {klass} — {' '.join(str(text).split())}")
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
    # The ONE declaration of the reserved name, read from `PROBE_APP` and
    # printed once: a reader holding a PLANT OUTSIDE THE RESERVED NAMESPACE
    # refusal learns here where a plant may go without opening the engine.
    say(
        f"reserved segment: {PROBE_APP} — every mode: create plant sits under it, in "
        "apps/example/, or declares namespace_exempt: <reason> (MOVE-TRIGGER <date>)"
    )
    # --- THE CENSUS (C0's seam) -------------------------------------------
    #
    # Everything above this line is the rule's DECLARATION: what it says, where
    # it is written down, how an exception is recorded, what it cannot see. All
    # of it is true of an empty checkout. A rule may also declare `census:` — a
    # dotted path to a callable this reader runs over THIS TREE — so that
    # `--explain <id>` can answer "and what does that mean here, right now?"
    # without a second reader, a second walker or a management command. Rule
    # 59's census is the worked example: its third class prints one draft
    # `EVENT_KINDS` line per undecided noun, scattered through a gate's output;
    # the census is the block each `events.py` actually needs, grouped by app.
    #
    # THREE FAILURES, THREE DIFFERENT ANSWERS, none of them a crash:
    #   no `census:` key      nothing printed at all — every rule that came
    #                         before this seam explains byte-identically
    #   unresolvable          EXIT 2, naming the dotted path. A declaration
    #                         pointing at a callable that is not there is
    #                         broken enforcement, and 2 outranks a pass.
    #   the callable RAISES   a `could not look:` line naming the exception,
    #                         and the rest of the explanation still prints. A
    #                         reader that dies on a tree its census stumbled on
    #                         takes the declaration down with it, and the
    #                         declaration is the part that is always true.
    census = rule.get("census")
    if census:
        dotted = str(census)
        fn, problem = resolve_census(dotted)
        if problem or fn is None:
            say("")
            say(f"‼ rule {rid}: census {dotted!r} does not resolve — {problem}")
            return 2
        say("")
        say("census (this tree):")
        try:
            lines = list(fn(ROOT, rule))
        except Exception as exc:  # noqa: BLE001 — a stumbling census reports, never crashes
            say(f"  could not look: {dotted} raised {type(exc).__name__}: {exc}")
        else:
            for line in lines:
                say(f"  {line}")
            if not lines:
                say("  nothing to report on this tree")
    say("")
    say(f"selftest_floor: {rule.get('selftest_floor') or {}}")
    return 0


def resolve_census(dotted: str) -> tuple[Any, str]:
    """(the callable a rule's `census:` names, '') — or (None, why it does not resolve).

    The ONE resolution `--explain` and the self-test's census leg share, so the
    two cannot come to disagree about what a declaration points at.
    """
    import importlib

    module_name, _, attr = dotted.rpartition(".")
    if not module_name or not attr:
        return None, "it is not a dotted path to a callable (want `package.module.name`)"
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001 — any import failure is the same verdict
        return None, f"{module_name} would not import: {type(exc).__name__}: {exc}"
    fn = getattr(module, attr, None)
    if fn is None:
        return None, f"{module_name} has no attribute {attr!r}"
    if not callable(fn):
        return None, f"{module_name}.{attr} is a {type(fn).__name__}, not a callable"
    return fn, ""


def census_reader_problem(rule: dict) -> str:
    """Why this rule's `census:` reader cannot answer over THIS tree, or '' when it does.

    `--explain` prints a stumbling census as a `could not look:` line and goes
    on, because the declaration above it is always true; the self-test asks the
    stricter question — does every declared reader resolve and run without
    raising — because a census nobody runs is a reader that can rot.
    """
    dotted = str(rule.get("census") or "")
    fn, problem = resolve_census(dotted)
    if problem or fn is None:
        return f"census {dotted!r} does not resolve — {problem}"
    try:
        list(fn(ROOT, rule))
    except Exception as exc:  # noqa: BLE001 — a reader that raises could not look
        return f"census {dotted!r} raised {type(exc).__name__}: {exc}"
    # An EMPTY answer is an answer: rule 59's census has nothing to say on a
    # tree with no undecided noun, and `--explain` prints exactly that.
    return ""


def _census_probe_raises(root: Path, rule: dict) -> list[str]:
    """The census leg's canary: a reader that stumbles, on purpose."""
    raise RuntimeError("the census canary stumbles on purpose")


def _census_probe_answers(root: Path, rule: dict) -> list[str]:
    """The census leg's negative: a reader that answers."""
    return [f"answered over {root.name}"]


def census_reader_census() -> None:
    """Every rule's `census:` reader, run once — and the forms it must refuse.

    THE SELF-TEST NEVER CALLED A CENSUS. `--explain <id>` runs one when a
    reader asks, so a reader that stopped resolving, or started raising, was
    found by the next person to ask — never by the gate. This leg runs every
    declared reader over the tree, and proves it can tell: two scratch rules
    (one naming a callable that is not there, one whose reader raises) must be
    refused, and one whose reader answers must not.
    """
    declared = [r for r in RULES if r.get("enabled", True) and r.get("census")]
    answered = 0
    for rule in declared:
        problem = census_reader_problem(rule)
        if problem:
            RUN.broken.append(f"census census: rule {rule['id']}: {problem}")
        else:
            answered += 1
    here = _census_probe_answers.__module__
    forms = (
        ("zzz-census-missing", f"{here}.zzz_no_such_census", True),
        ("zzz-census-raises", f"{here}._census_probe_raises", True),
        ("zzz-census-answers", f"{here}._census_probe_answers", False),
    )
    fired = silent = 0
    for probe_id, dotted, must_refuse in forms:
        refused = bool(census_reader_problem({"id": probe_id, "census": dotted}))
        if refused and must_refuse:
            fired += 1
        elif not refused and not must_refuse:
            silent += 1
        else:
            RUN.broken.append(
                f"census census: the scratch rule {probe_id} ({dotted}) was "
                + ("answered" if must_refuse else "refused")
                + " — the census leg cannot tell a reader that answers from one that cannot"
            )
    say(
        f"census census: {answered} of {len(declared)} declared readers answered · "
        f"{fired} of 2 canary forms refused · {silent} of 1 negatives answered"
    )


from quality.engine.memo import memo_contract, memo_declines  # noqa: E402
from quality.engine.run import marker_tokens  # noqa: E402
from quality.engine.world import (  # noqa: E402
    MEMBER_FLOOR_SOURCES,
    PROBE_APP,
    RULES,
    RULES_BY_ID,
    RUN,
    SCOPE_KINDS,
    finding_kinds,
    is_local_rule,
    is_member_rule,
    ratchet_home,
    say,
    violation_rule,
)
