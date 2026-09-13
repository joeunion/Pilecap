#!/usr/bin/env bash
# THIS FILE IS EXECUTED, AND IT IS BASH — not POSIX sh, and not zsh. The
# shebang above is honoured by `./this`; `sh this` and `zsh this` IGNORE it,
# and neither of them fails where the mistake was made. Measured on this tree:
#
#   zsh scripts/queue_cited.sh   exit 2 blaming the TREE ("this is not a
#                                checkout root") for zsh's word-splitting
#   zsh scripts/kill_mine.sh     an ordinary-looking census of nothing
#   sh  scripts/sweep.sh         "lifecycle.sh: line 152: syntax error"
#
# A wrong shell here does not crash. It ANSWERS, and the answer looks like the
# tree's fault.
[ -n "${BASH_VERSION:-}" ] || {
    echo "${0##*/}: must run under bash — not sh, not zsh. Try \`bash ${0}\`." >&2
    exit 2
}
case ":${SHELLOPTS:-}:" in
*:posix:*)
    echo "${0##*/}: bash is in POSIX mode — which is what \`sh ${0}\` does on a" >&2
    echo "  machine whose /bin/sh is bash. Try \`bash ${0}\`." >&2
    exit 2
    ;;
esac
# The drive for the LEGIBLE RED — `quality/gate.py`'s per-rule trailer, its two
# readers (`--explain <id>` and the listing `--rules` aliases), and `--terse`.
#
#   ./scripts/tests/test_gate_explain.sh          run every case
#   ./scripts/tests/test_gate_explain.sh --list   name them and stop
#
# WHY IT EXISTS (DX-ARCH #1, the consumer's ranked first cost). A red printed
# `rule 13: apps/paper/services.py:42: <msg>` and stopped. Every other fact the
# rule DECLARES — where it is written down, how a legitimate exception is
# recorded, what it cannot see — sat in a 7,000-line yaml and reached nobody:
# `doc:` was read only by `consistency()`, and the valve grammar was prose in
# four different files. A builder holding a red had to go find the rule to
# learn what to do about it, and the commonest outcome was a second push.
#
# WHAT IS UNDER DRIVE, and each case says which half:
#   the FIELD   — every rule declares a valve; a rule that declares neither
#                 form is exit 2, and so is a `none:` with no sentence
#   the TRAILER — a real red carries four ASCII-keyed lines, once per rule,
#                 with the comment token of the file the finding is IN
#   the READERS — `--explain <id>`, the listing under both names, exit 2 on an
#                 unknown id and on an unknown flag
#   the FLAG    — `--terse` drops exactly the `ok` rows and the standing-
#                 override rows, and NEVER the ENFORCEMENT BROKEN block
#   the CENSUS  — the trailer and CLI censuses SAY they ran, so deleting the
#                 call is visible rather than silent
#   the BUDGET  — which modules are `service_function_length` subjects at all:
#                 a function is a subject, a function-less module is not, and a
#                 subject with a value still fails until a human records it
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   1. It asserts the ASCII KEYS (`doc:`, `valve:`, `blind:`, `next:`) and the
#      marker text, never the `§`/`—` glyphs around them.
#      A reword of the prose between the keys passes here and should.
#   2. The per-kind token substitution is driven end to end for BOTH tokens —
#      `#` on a `.py` finding, `//` on a `frontend/**` one — but the two-tokens-
#      on-ONE-rule form is asserted in process, because no rule on this tree
#      scans both kinds. The day one does, that case becomes an end-to-end one.
#   3. It proves the trailer PRINTS what the yaml declares. A stale
#      `does_not_cover`, or a `doc:` anchor pointing at a paragraph that no
#      longer means what the rule checks, is now louder — not fixed.
#   4. THE PLANT IS THE REAL TREE, restored in a trap. Killed between the
#      plant and the restore, it leaves `apps/example/selectors.py` dirty, and
#      an untracked `frontend/src/components/index.ts` and
#      `apps/zzz_probe_newapps/` standing — `git checkout --` the first and
#      delete the other two is the whole recovery, and the gate's own
#      stale-plant refusal and instrument census are what would tell you.
#   5. The budget cases prove WHICH MODULES ARE SUBJECTS. Whether a recorded
#      ceiling is the right number is a human's judgment and always was; the
#      measurement itself (the docstring subtraction) is the engine's own
#      budget canary, not this drive's.
set -euo pipefail

cd "$(dirname "$0")/../.."

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_gate_explain: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It carries the only thing keeping this drive's scratch work inside its" >&2
    echo "   own scratch directory. Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh

# Section 5 of the preamble: on macOS's bash 3.2 a `set -u` death hands the EXIT
# trap a status of 0, so a drive that never reached its own summary reports
# success. Opting in makes that could-not-look instead.
DRIVE_OPTED_IN_TO_FINISH=1

PASSED=0
FAILED=0

cannot_look() {
    echo "!! test_gate_explain: $*" >&2
    echo "   Nothing was asserted. A driver that could not run its cases has not" >&2
    echo "   cleared them." >&2
    exit 2
}

case "${1:-}" in
"") ;;
--list)
    grep -n '^case_' "$0" | sed 's/() {.*//; s/^/  /'
    exit 0
    ;;
*)
    echo "!! unknown argument '$1': test_gate_explain.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

[ -f quality/gate.py ] || cannot_look "quality/gate.py is not in this tree"
[ -f quality/rules.yaml ] || cannot_look "quality/rules.yaml is not in this tree"
[ -f apps/example/selectors.py ] || cannot_look "apps/example/selectors.py is gone — the red plant has no home"
command -v uv >/dev/null 2>&1 || cannot_look "no uv on PATH — the engine is run through it"

ROOT="$PWD"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-gate-explain-drive.XXXXXX")" || cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"

PLANT_TARGET="apps/example/selectors.py"
PLANT_SAVED=""
unplant() {
    [ -n "$PLANT_SAVED" ] || return 0
    cp "$PLANT_SAVED" "${ROOT}/${PLANT_TARGET}"
    PLANT_SAVED=""
}

# The browser-tree plant, for the `//` half of the valve token. It is CREATED
# rather than appended — `frontend/src/components/index.ts` does not exist and
# must not survive this drive, because a barrel standing on the tree is the
# very thing rule 52 refuses.
JS_TARGET="frontend/src/components/index.ts"
unplant_js() { rm -f "${ROOT}/${JS_TARGET}"; }

# The budget-subject plant: a whole app directory holding nothing but a
# `services.py`, which is what `apps/*/services.py` globs over. Created, never
# appended, and removed by name — the glob is the only thing that has to see it.
PROBE_APP_DIR="apps/zzz_probe_newapps"
unplant_probe_app() { rm -rf "${ROOT:?}/${PROBE_APP_DIR}"; }

drive_at_exit 'unplant; unplant_js; unplant_probe_app; rm -rf "$WORK"'

CURRENT=""
RC=0
OUT=""
N=0

ok() {
    echo "  ok       ${CURRENT} — $1"
    PASSED=$((PASSED + 1))
}
bad() {
    echo "  FAILED   ${CURRENT} — $1"
    [ -n "$OUT" ] && [ -f "$OUT" ] && [ -s "$OUT" ] && sed 's/^/             | /' "$OUT" | tail -25
    FAILED=$((FAILED + 1))
}

# Run the engine, stdout and stderr together into a file of this drive's own.
# NEVER piped: the exit status is the verdict, and a pipe replaces it.
run_gate() {
    CURRENT="$1"
    shift
    N=$((N + 1))
    OUT="${WORK}/gate${N}.log"
    RC=0
    GATE_SKIP_DJANGO_LEG=1 uv run python -m quality.gate "$@" >"$OUT" 2>&1 || RC=$?
}

# The in-process forge: the selftest's own idiom (`_seam_rule`,
# quality/gate.py) — a rule is forged in MEMORY and the real `consistency()`
# is run over it, so the case measures the shipped function rather than a copy
# of its logic, and no file on disk is ever wrong.
forge() {
    CURRENT="$1"
    shift
    N=$((N + 1))
    OUT="${WORK}/forge${N}.log"
    RC=0
    uv run python -c "$1" >"$OUT" 2>&1 || RC=$?
}

RULE_COUNT="$(uv run python -c "
import pathlib, yaml
print(len(yaml.safe_load(pathlib.Path('quality/rules.yaml').read_text())['rules']))
")" || cannot_look "could not read the rule count out of quality/rules.yaml"
[ -n "$RULE_COUNT" ] || cannot_look "the rule count derived empty"

# --- the field ---------------------------------------------------------------

case_every_rule_declares_a_valve() {
    CURRENT="case_every_rule_declares_a_valve"
    local declared
    declared="$(grep -c '^    valve:' quality/rules.yaml || true)"
    if [ "$declared" = "$RULE_COUNT" ]; then
        ok "${declared} valve declarations for ${RULE_COUNT} rules"
    else
        bad "${declared} valve declarations for ${RULE_COUNT} rules — a rule that cannot say how to record a legitimate exception prints a red nobody can act on"
    fi
}

case_a_rule_with_no_valve_is_enforcement_broken() {
    forge "case_a_rule_with_no_valve_is_enforcement_broken" '
import sys
sys.argv = ["gate"]
from quality import gate
victim = gate.RULES[0]
rid = str(victim["id"])
victim.pop("valve", None)
gate.broken.clear()
gate.consistency()
hits = [b for b in gate.broken if b.startswith("rule " + rid + ": no valve")]
print("\n".join(gate.broken))
sys.exit(0 if hits else 1)
'
    if [ "$RC" = "0" ]; then
        ok "consistency() names the rule that declared neither form"
    else
        bad "a rule with no valve did not become ENFORCEMENT BROKEN naming itself"
    fi
}

case_a_none_valve_with_no_sentence_is_enforcement_broken() {
    forge "case_a_none_valve_with_no_sentence_is_enforcement_broken" '
import sys
sys.argv = ["gate"]
from quality import gate
victim = gate.RULES[0]
victim["valve"] = {"none": "nope"}
gate.broken.clear()
gate.consistency()
hits = [b for b in gate.broken if "none:" in b and str(victim["id"]) in b]
print("\n".join(gate.broken))
sys.exit(0 if hits else 1)
'
    if [ "$RC" = "0" ]; then
        ok "a none-form claim under the reason floor is exit 2, not a quieter trailer"
    else
        bad "a one-word none-form reason passed — the claim that nothing can excuse a rule is exactly the claim owing a sentence"
    fi
}

case_a_valve_declaring_both_forms_is_enforcement_broken() {
    forge "case_a_valve_declaring_both_forms_is_enforcement_broken" '
import sys
sys.argv = ["gate"]
from quality import gate
victim = gate.RULES[0]
victim["valve"] = {"none": "there is nothing at all to excuse here", "marker": "# x: <reason>"}
gate.broken.clear()
gate.consistency()
hits = [b for b in gate.broken if "AND a marker" in b]
print("\n".join(gate.broken))
sys.exit(0 if hits else 1)
'
    if [ "$RC" = "0" ]; then
        ok "a reader is never told there is no valve and handed one"
    else
        bad "a valve declaring the none form and a marker at once was accepted"
    fi
}

# --- the trailer -------------------------------------------------------------

plant_the_red() {
    PLANT_SAVED="${WORK}/selectors.orig.py"
    cp "${ROOT}/${PLANT_TARGET}" "$PLANT_SAVED"
    printf '\nfrom django.contrib.auth.models import User  # test_gate_explain plant\n' \
        >>"${ROOT}/${PLANT_TARGET}"
}

case_a_red_carries_its_trailer_once_after_its_findings() {
    plant_the_red
    run_gate "case_a_red_carries_its_trailer_once_after_its_findings"
    unplant
    if [ "$RC" != "1" ]; then
        bad "a planted rule-1 import did not exit 1 (got ${RC}) — the red this case reads never happened"
        return
    fi
    local missing=""
    local key
    for key in 'doc:' 'valve:' 'blind:' 'next:'; do
        grep -qE "^ +${key}" "$OUT" || missing="${missing} ${key}"
    done
    if [ -n "$missing" ]; then
        bad "the red's block is missing:${missing}"
        return
    fi
    local trailers
    trailers="$(grep -cE '^ +next:   python -m quality\.gate --explain 1$' "$OUT" || true)"
    if [ "$trailers" != "1" ]; then
        bad "the rule printed ${trailers} trailers, not one — a rule with twelve findings owes its reader one"
        return
    fi
    ok "doc: valve: blind: next: — four ASCII keys, once, after the finding"
}

case_the_trailers_valve_is_the_marker_a_reader_can_paste() {
    plant_the_red
    run_gate "case_the_trailers_valve_is_the_marker_a_reader_can_paste"
    unplant
    if grep -qE '^ +valve: +# rule-1: <reason>' "$OUT"; then
        ok "the python finding is handed the hash form of its rule's marker"
    else
        bad "the valve line does not carry the pasteable marker for this finding's file kind"
    fi
}

case_the_budget_trailer_names_the_budget_file() {
    forge "case_the_budget_trailer_names_the_budget_file" '
import sys
sys.argv = ["gate"]
from quality import gate
lines = gate.trailer_for("")
print("\n".join(lines))
sys.exit(0 if len(lines) == 1 and "quality/budgets.yaml" in lines[0] else 1)
'
    if [ "$RC" = "0" ]; then
        ok "a budget violation says where its number lives instead of faking a rules.yaml entry"
    else
        bad "a violation with no rule id did not get the budget trailer"
    fi
}

case_a_rule_whose_trailer_lost_a_key_is_enforcement_broken() {
    forge "case_a_rule_whose_trailer_lost_a_key_is_enforcement_broken" '
import sys
sys.argv = ["gate"]
from quality import gate
victim = gate.RULES[0]
victim["does_not_cover"] = ""
gate.broken.clear()
gate.trailer_census([str(victim["id"])])
hits = [b for b in gate.broken if "RED WITHOUT A TRAILER" in b and "blind:" in b]
print("\n".join(gate.broken))
sys.exit(0 if hits else 1)
'
    if [ "$RC" = "0" ]; then
        ok "a fired canary whose rule cannot explain its red is exit 2, naming the key"
    else
        bad "a rule with an empty does_not_cover produced a trailer the census accepted"
    fi
}

case_a_frontend_finding_prints_the_slash_valve_token() {
    # The other half of "the valve's token is the FINDING's, not the rule's".
    # `#` is driven above on a python red; until this case, the `//` form was
    # read off the code and never seen to print — and a valve line a reader
    # cannot paste into the file they are holding is the same defect the
    # trailer exists to close, one language over.
    mkdir -p "${ROOT}/frontend/src/components"
    {
        echo '// a re-export of a sibling directory: the shape rule 52 refuses'
        echo 'export * from "./deal-card";'
    } >"${ROOT}/${JS_TARGET}"
    run_gate "case_a_frontend_finding_prints_the_slash_valve_token"
    unplant_js
    if [ "$RC" != "1" ]; then
        bad "a planted barrel did not exit 1 (got ${RC}) — the browser-tree red this case reads never happened"
        return
    fi
    if ! grep -qE "^ +valve: +// rule-52: <reason>" "$OUT"; then
        bad "the .ts finding's valve line does not carry the // token — the reader is handed a marker their file cannot speak"
        return
    fi
    local hashed
    hashed="$(grep -cE "^ +valve: +# rule-52: <reason>" "$OUT" || true)"
    if [ "$hashed" != "0" ]; then
        bad "rule 52's block printed ${hashed} hash-token valve line(s) for findings that are all .ts — the token is per finding kind, not per rule"
        return
    fi
    ok "a frontend finding is handed // rule-52, and only that"
}

case_a_rule_with_findings_in_two_kinds_prints_both_valve_tokens() {
    # ASSERTED IN PROCESS, and the reason is declared blind spot 2 above: no
    # rule on this tree scans both `apps/**` and `frontend/**`, so there is no
    # pair of plants that would make one rule report in both. What CAN be
    # driven is the printer itself, over the token set the two end-to-end cases
    # each proved one half of.
    forge "case_a_rule_with_findings_in_two_kinds_prints_both_valve_tokens" '
import sys
sys.argv = ["gate"]
from quality import gate
lines = gate.rule_trailer(gate.RULES_BY_ID["52"], {"#", "//"})
valves = [ln for ln in lines if ln.strip().startswith("valve:")]
print("\n".join(lines))
hash_form = [ln for ln in valves if "# rule-52: <reason>" in ln]
slash_form = [ln for ln in valves if "// rule-52: <reason>" in ln]
sys.exit(0 if len(valves) == 2 and len(hash_form) == 1 and len(slash_form) == 1 else 1)
'
    if [ "$RC" = "0" ]; then
        ok "one rule, two finding kinds, two valve lines — one each, neither duplicated"
    else
        bad "a rule whose findings span two kinds did not print one pasteable marker per kind"
    fi
}

# --- the census --------------------------------------------------------------

case_the_trailer_and_cli_censuses_print_and_are_asserted() {
    forge "case_the_trailer_and_cli_censuses_print_and_are_asserted" '
import ast, contextlib, io, pathlib, sys
sys.argv = ["gate"]
from quality import gate

def called_in_selftest(source):
    tree = ast.parse(source)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "selftest"
    )
    return {
        n.func.id for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }

source = pathlib.Path("quality/gate.py").read_text()
problems = []
wired = called_in_selftest(source)
for name in ("trailer_census", "cli_census"):
    if name not in wired:
        problems.append(name + ": selftest() does not call it — the instrument is not wired in")

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    gate.trailer_census(["1"])
    gate.cli_census()
printed = buf.getvalue()
for claim in (
    "trailer census: 1 rule(s) with findings, every one carried its four lines",
    "cli census: --explain/--rules answered 4 of 4 probes",
):
    if claim not in printed:
        problems.append("not printed on success: " + claim)

# THE CONTROL. An assertion that cannot see the deletion it exists to catch is
# not an assertion: the same call-site read, over a copy of the source with the
# call removed, has to come back empty.
for name in ("trailer_census", "cli_census"):
    without = "\n".join(
        line for line in source.splitlines()
        if not line.strip().startswith(name + "(")
    )
    if name in called_in_selftest(without):
        problems.append("the control: " + name + " was deleted and the case still passed")

print(printed)
print("\n".join(problems))
sys.exit(1 if problems else 0)
'
    if [ "$RC" = "0" ]; then
        ok "both censuses say they ran, and deleting either call is red here"
    else
        bad "a census ran silently, or its call could be deleted without this case noticing"
    fi
}

# --- the budget subject ------------------------------------------------------
#
# WHOSE NUMBER IS IT. `budgets.yaml`'s doctrine is that a NEW subject fails
# until a human measures it and commits the number — which is a claim about a
# subject that HAS a value. A `services.py` with no top-level function has no
# longest function to measure, and minting a subject for it would hand whoever
# generated the module a `quality/` edit for a zero nobody measured. So the
# subject is a FUNCTION, and these three cases are the two directions of that
# and the remedy line in between.

plant_probe_app() {
    mkdir -p "${ROOT}/${PROBE_APP_DIR}"
    {
        echo '"""Write operations for the probe app.'
        echo ''
        echo 'Every write goes through a `@service` here; doors call these, never the ORM.'
        echo '"""'
    } >"${ROOT}/${PROBE_APP_DIR}/services.py"
    if [ "${1:-}" = "with-a-function" ]; then
        {
            echo ''
            echo ''
            echo 'def create_probe(*, name: str) -> str:'
            echo '    return name'
        } >>"${ROOT}/${PROBE_APP_DIR}/services.py"
    fi
}

case_a_function_less_services_module_is_not_a_budget_subject() {
    plant_probe_app
    run_gate "case_a_function_less_services_module_is_not_a_budget_subject"
    unplant_probe_app
    if [ "$RC" != "0" ]; then
        bad "a services.py holding no top-level def exited ${RC} — a module with nothing to measure became a subject anyway"
        return
    fi
    if grep -q "${PROBE_APP_DIR}/services.py" "$OUT"; then
        bad "the engine named the function-less module in its output — no key, no budget line, no note was the whole claim"
        return
    fi
    ok "no top-level def, no subject, no line to paste — the tree stays green"
}

case_one_function_is_a_subject_and_still_reds_without_a_ceiling() {
    plant_probe_app with-a-function
    run_gate "case_one_function_is_a_subject_and_still_reds_without_a_ceiling"
    unplant_probe_app
    if [ "$RC" != "1" ]; then
        bad "a services.py holding one top-level def exited ${RC} — an unrecorded subject with a value has to fail, or the doctrine is gone"
        return
    fi
    if ! grep -q "has no recorded ceiling for ${PROBE_APP_DIR}/services.py — create_probe (lines " "$OUT"; then
        bad "the red does not name the module AND the function it measured"
        return
    fi
    ok "one def is one subject, named by function, and it fails until a human records it"
}

case_a_new_function_subject_prints_its_paste_line() {
    plant_probe_app with-a-function
    run_gate "case_a_new_function_subject_prints_its_paste_line"
    unplant_probe_app
    if [ "$RC" != "1" ]; then
        bad "the plant exited ${RC} — the remedy line this case reads was never printed"
        return
    fi
    if ! grep -q 'The line to paste under `service_function_length:` in quality/budgets.yaml:' "$OUT"; then
        bad "the refusal stopped saying where the number goes"
        return
    fi
    if ! grep -qE "^ +${PROBE_APP_DIR}/services\.py: [0-9]+$" "$OUT"; then
        bad "the pasteable line is not a `<key>: <measured>` a human can copy into budgets.yaml"
        return
    fi
    ok "the remedy is still a line the reader pastes, not an instruction to go and work it out"
}

# --- the readers -------------------------------------------------------------

case_explain_prints_the_rules_own_declaration() {
    run_gate "case_explain_prints_the_rules_own_declaration" --explain 13
    if [ "$RC" != "0" ]; then
        bad "--explain 13 exited ${RC}"
        return
    fi
    if grep -q 'statement:' "$OUT" && grep -q 'valve:' "$OUT" &&
        grep -q 'Every public write in services.py is @service' "$OUT" &&
        grep -q 'does_not_cover:' "$OUT"; then
        ok "the statement, the mechanism, the valve and the blind spot, read from the yaml"
    else
        bad "--explain 13 did not print the rule's own declaration"
    fi
}

case_explain_of_an_unknown_id_is_exit_2_naming_the_listing() {
    run_gate "case_explain_of_an_unknown_id_is_exit_2_naming_the_listing" --explain 999
    if [ "$RC" = "2" ] && grep -q 'listing' "$OUT"; then
        ok "an unknown id is could-not-look, and says where the ids are"
    else
        bad "--explain 999 exited ${RC} without naming the listing"
    fi
}

case_the_listing_is_the_same_under_both_names() {
    run_gate "case_the_listing_is_the_same_under_both_names" --explain
    local bare="$OUT"
    local bare_rc="$RC"
    run_gate "case_the_listing_is_the_same_under_both_names" --rules
    if [ "$bare_rc" != "0" ] || [ "$RC" != "0" ]; then
        bad "the listing exited ${bare_rc}/${RC}"
        return
    fi
    if ! cmp -s "$bare" "$OUT"; then
        bad "bare --explain and --rules printed different things — two printers for one question"
        return
    fi
    local listed
    listed="$(grep -c . "$OUT" || true)"
    if [ "$listed" = "$RULE_COUNT" ]; then
        ok "one line per rule, ${listed} of ${RULE_COUNT}, byte-identical under both names"
    else
        bad "the listing printed ${listed} lines for ${RULE_COUNT} rules"
    fi
}

case_an_unknown_flag_is_still_exit_2() {
    run_gate "case_an_unknown_flag_is_still_exit_2" --tesre
    if [ "$RC" = "2" ] && grep -q 'unknown argument' "$OUT"; then
        ok "a mistyped flag is never a silently different run"
    else
        bad "--tesre exited ${RC} — a typo has become a smaller gate"
    fi
}

# --- the flag ----------------------------------------------------------------

case_terse_keeps_the_count_and_drops_only_the_ok_lines() {
    run_gate "case_terse_keeps_the_count_and_drops_only_the_ok_lines"
    local full="$OUT"
    local full_rc="$RC"
    run_gate "case_terse_keeps_the_count_and_drops_only_the_ok_lines" --terse
    if [ "$full_rc" != "$RC" ]; then
        bad "--terse changed the exit status (${full_rc} -> ${RC}) — it prints less, it decides nothing"
        return
    fi
    if ! grep -qE '^House rules: [0-9]+ rules · [0-9]+ ok · [0-9]+ RED · [0-9]+ skipped' "$OUT"; then
        bad "--terse dropped the count line, which is the whole of what the ok rows were saying"
        return
    fi
    local only_full stray
    only_full="${WORK}/only-in-full.txt"
    diff "$OUT" "$full" | sed -n 's/^> //p' >"$only_full" || true
    stray="$(grep -vcE ': ok \(|^  rule-[0-9]+ ' "$only_full" || true)"
    if [ "$stray" = "0" ] && [ -s "$only_full" ]; then
        ok "the difference is exactly the ok rows and the standing-override rows — nothing else"
    else
        bad "--terse also dropped ${stray} line(s) that are neither an ok row nor a standing override"
        OUT="$only_full"
    fi
}

case_terse_prints_enforcement_broken_in_full() {
    forge "case_terse_prints_enforcement_broken_in_full" '
import io, contextlib, sys
sys.argv = ["gate"]
from quality import gate
gate.RULES[0].pop("valve", None)
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = gate.main(["--terse"])
text = buf.getvalue()
print(text)
sys.exit(0 if rc == 2 and "ENFORCEMENT BROKEN" in text and "no valve" in text else 1)
'
    if [ "$RC" = "0" ]; then
        ok "exit 2 outranks a flag whose job is to print less"
    else
        bad "--terse suppressed, or softened, the ENFORCEMENT BROKEN block"
    fi
}

case_every_rule_declares_a_valve
case_a_rule_with_no_valve_is_enforcement_broken
case_a_none_valve_with_no_sentence_is_enforcement_broken
case_a_valve_declaring_both_forms_is_enforcement_broken
case_a_red_carries_its_trailer_once_after_its_findings
case_the_trailers_valve_is_the_marker_a_reader_can_paste
case_the_budget_trailer_names_the_budget_file
case_a_rule_whose_trailer_lost_a_key_is_enforcement_broken
case_a_frontend_finding_prints_the_slash_valve_token
case_a_rule_with_findings_in_two_kinds_prints_both_valve_tokens
case_the_trailer_and_cli_censuses_print_and_are_asserted
case_a_function_less_services_module_is_not_a_budget_subject
case_one_function_is_a_subject_and_still_reds_without_a_ceiling
case_a_new_function_subject_prints_its_paste_line
case_explain_prints_the_rules_own_declaration
case_explain_of_an_unknown_id_is_exit_2_naming_the_listing
case_the_listing_is_the_same_under_both_names
case_an_unknown_flag_is_still_exit_2
case_terse_keeps_the_count_and_drops_only_the_ok_lines
case_terse_prints_enforcement_broken_in_full

echo "test_gate_explain: ${PASSED} passed · ${FAILED} failed"
drive_finished
if [ "$FAILED" -gt 0 ]; then
    echo "!! a red can no longer explain itself. The trailer, the two readers and" >&2
    echo "   --terse are the difference between a builder acting on a finding and a" >&2
    echo "   builder going to look for the rule in a 7,000-line yaml." >&2
    exit 1
fi
exit 0
