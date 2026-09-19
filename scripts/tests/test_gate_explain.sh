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
# drives: CLAUDE.md apps/ config/ frontend/src/components quality/ scripts/kill_mine.sh scripts/queue_cited.sh scripts/sweep.sh
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
#   the MEMO    — the per-rule cache in front of every `check:`: one tree gives
#                 one key, a moved input misses THAT rule and names what moved,
#                 a hit replays the red rather than printing ok, a rule that
#                 declines scans every time and owes a reason, an undecidable
#                 key scans, the three readers are untouched, and the
#                 self-test's bypass is proved by a PLANTED FALSE ENTRY the
#                 memo would otherwise have silenced
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
#   4. THE PLANT IS THE REAL TREE, restored in a trap, AND EVERY PLANT SITS
#      SOMEWHERE NO PRODUCT CAN OWN. `apps/example/selectors.py` is appended to
#      and restored from saved bytes; the other two are CREATED under names
#      reserved by the `zzz_` convention — `frontend/src/components/zzz_probe_gate_explain/`
#      (an `index.ts` inside it, so rule 52's `index` stem still scans it) and
#      `apps/zzz_probe_newapps/` — and the drive REFUSES to plant over a path
#      that already exists rather than overwriting it. Before the first case it
#      records `git status --porcelain --untracked-files=all`; after the last
#      unplant it takes that census again and a difference is exit 1 naming
#      each path (`moved: <path>`), even when every case passed. So a killed
#      run leaves `apps/example/selectors.py` dirty and the two `zzz_` paths
#      standing — `git checkout --` the first and delete the other two is the
#      whole recovery — and a run that reaches its own exit cannot leave a
#      product's file moved without saying so. The browser plant used to sit at
#      the bare `index` barrel directly under `frontend/src/components/` —
#      a path a product ships a real file at — and overwrote it on every plant
#      and `rm -f`'d it at exit. That spelling is deliberately absent here.
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

# The status the exit census may RAISE to and must never LOWER from. It is set
# at the one exit whose meaning this drive's case bookkeeping cannot express:
# `cannot_look` asserts nothing, so `FAILED` is 0 and a census reading only the
# case counters sees a pass where the truth is could-not-look.
CENSUS_FLOOR=0

cannot_look() {
    CENSUS_FLOOR=2
    echo "!! test_gate_explain: $*" >&2
    echo "   Nothing was asserted. A driver that could not run its cases has not" >&2
    echo "   cleared them." >&2
    exit 2
}

case "${1:-}" in
"") ;;
--list)
    # THE DEFINITION, NOT THE CALL. `^case_` matched the definition line AND
    # the column-zero invocation at the foot of this file, so every case was
    # named twice; `test_list_legs.sh:149` is the form that was already right.
    grep -n '^case_[A-Za-z0-9_]*() {' "$0" | sed 's/() {.*//; s/^/  /'
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
# rather than appended: a barrel standing on the tree is the very thing rule 52
# refuses, so this one must not survive the drive.
#
# WHERE IT SITS, AND WHY IT MOVED. It used to sit at the bare `index`
# barrel directly under `frontend/src/components/`, which is a path a PRODUCT
# ships a real file at — and this drive created it, overwrote whatever was
# there, and `rm -f`'d it at exit, on every gate. The consumer shipped one and
# the gate deleted it (their platform-feedback, 2026-09-13). The fix is the
# convention every other plant in this file already follows: a `zzz_` name no
# product can own, asserted absent before it is planted. The stem stays `index`
# and the root stays `frontend`, so rule 52's scope (`quality/rules.yaml`
# `scope_kinds.js`: roots `[frontend]`, stem `index`) still reaches it.
#
# Saving and restoring the bytes at the old path was the rejected alternative:
# a product's real barrel there is rule 52's violation, and restoring it
# byte-for-byte is restoring the defect the drive just proved.
JS_PROBE_DIR="frontend/src/components/zzz_probe_gate_explain"
JS_TARGET="${JS_PROBE_DIR}/index.ts"

# The directories THIS run created, DEEPEST FIRST (each new link is prepended),
# newline-delimited. macOS's bash 3.2 has no `arr+=(x)`, so a string it is — the
# same reason `drive_preamble.sh` keeps its cleanups on lines. Deepest first is
# removal order, so the unplant never has to reverse anything.
JS_DIRS_CREATED=""

# The precondition, factored out so a case can drive it: it REFUSES rather than
# overwriting. A leftover from a killed run is somebody's to look at, never
# something to silently stand on.
js_plant_precondition() {
    local blocked=""
    [ -e "${ROOT}/${JS_TARGET}" ] && blocked="${blocked} ${JS_TARGET}"
    [ -e "${ROOT}/${JS_PROBE_DIR}" ] && blocked="${blocked} ${JS_PROBE_DIR}"
    [ -z "$blocked" ] || cannot_look "the browser plant's path is already taken:${blocked}.
   This drive CREATES its plant and refuses to overwrite one — a path that is
   already there is either a leftover from a killed run (delete it) or a file
   somebody owns (then this drive is planting in the wrong place). Nothing was
   overwritten."
}

# Create the chain, remembering exactly which links were missing.
plant_the_js() {
    js_plant_precondition
    JS_DIRS_CREATED=""
    # Walked with parameter expansion rather than IFS splitting: a drive that
    # changes IFS even locally is one `unset` away from handing the rest of the
    # file a different word-splitting rule under bash 3.2.
    local remaining="$JS_PROBE_DIR" dir="" part
    while [ -n "$remaining" ]; do
        part="${remaining%%/*}"
        if [ "$part" = "$remaining" ]; then remaining=""; else remaining="${remaining#*/}"; fi
        [ -n "$part" ] || continue
        dir="${dir:+${dir}/}${part}"
        [ -e "${ROOT}/${dir}" ] && continue
        mkdir "${ROOT}/${dir}"
        JS_DIRS_CREATED="${dir}
${JS_DIRS_CREATED}"
    done
    {
        echo '// a re-export of a sibling directory: the shape rule 52 refuses'
        echo 'export * from "./deal-card";'
    } >"${ROOT}/${JS_TARGET}"
}

# Remove the file and exactly the directories this run created — deepest first,
# and with `rmdir`, so a directory somebody else put something in survives and
# nothing above the chain is ever touched.
unplant_js() {
    rm -f "${ROOT}/${JS_TARGET}"
    local dirs="$JS_DIRS_CREATED" dir
    JS_DIRS_CREATED=""
    [ -n "$dirs" ] || return 0
    while IFS= read -r dir; do
        [ -n "$dir" ] || continue
        rmdir "${ROOT}/${dir}" 2>/dev/null || true
    done <<<"$dirs"
}

# The budget-subject plant: a whole app directory holding nothing but a
# `services.py`, which is what `apps/*/services.py` globs over. Created, never
# appended, and removed by name — the glob is the only thing that has to see it.
PROBE_APP_DIR="apps/zzz_probe_newapps"
unplant_probe_app() { rm -rf "${ROOT:?}/${PROBE_APP_DIR}"; }

# --- the working-tree census -------------------------------------------------
#
# `drive_preamble.sh::drive_tripwire_check` asks "did this drive move the real
# repository?" of HEAD and the refs. That is the right question one layer up
# from where this drive's plants live: every one of them is a FILE, and a file
# the drive created, overwrote or deleted never touches a ref. So the same
# shape, one layer down — the working tree as this drive found it, against the
# working tree as it leaves it, after the last unplant.
#
# It is a census of `git status --porcelain --untracked-files=all` rather than a
# list of the paths the drive knows about, for the tripwire's own reason: a list
# of what a drive MEANT to touch cannot see what it touched by accident, and the
# deleted barrel this criterion exists for was a path the drive knew about
# perfectly well.
WT_CENSUS_BEFORE="${WORK}/worktree-before.lst"
WT_CENSUS_AFTER="${WORK}/worktree-after.lst"

# One repository's working-tree census, one line per path, sorted so two
# censuses of the same tree are byte-identical whatever order git walked it in.
worktree_census() {
    git -C "$1" status --porcelain --untracked-files=all 2>/dev/null | LC_ALL=C sort
}

# The paths that differ between two censuses, one `moved: <path>` line each.
# Prints nothing and returns 0 when the two agree. The path is everything after
# the two status columns and the space git puts there; a rename's ` -> ` arrow
# stays on the line, because a reader wants both halves.
worktree_moved_paths() {
    local before="$1" after="$2"
    # `diff` exits 1 on a difference, which is the case this function exists
    # for, and `set -o pipefail` would hand that 1 to a `set -e` assignment and
    # kill the drive. `|| true` on the producer, and NO reader that stops early:
    # every stage below consumes its whole input (test_sweep.sh's pipefail
    # census is the standing rule this line obeys).
    { diff "$before" "$after" 2>/dev/null || true; } |
        sed -n 's/^[<>] ...//p' |
        LC_ALL=C sort -u |
        sed 's/^/moved: /'
}

# THE STATUS THIS CENSUS MAY RAISE AND MUST NEVER LOWER.
#
# The census is a cleanup: it runs from the EXIT trap, LONG after the drive
# decided what it was exiting with. Its first spelling exited 1 whenever it
# found a moved path — which turned a could-not-look into a red. Measured: a
# killed run leaves the `zzz_` plant standing, the next run's plant precondition
# refuses (`cannot_look`, exit 2), the unplant then deletes that leftover, the
# census sees `moved:` and exits **1**. The reader is told "the drive ran and
# found something" when the drive asserted NOTHING, and 2 outranks 1 everywhere
# else in this tree (CLAUDE.md § "The gate"). Raising 0 is this census's job;
# lowering 2 was never anybody's.
#
# Three sources, and the first two are this file's own:
#
#   CENSUS_FLOOR  2, set by `cannot_look` — the exit the case counters cannot
#                 express (nothing was asserted, so FAILED is 0)
#   FAILED        > 0 is the red this drive's own last lines exit 1 on
#   rc            `drive_preamble.sh::drive_epilogue`'s capture of `$?`, in
#                 scope here because bash scopes locals dynamically and the
#                 epilogue `eval`s this cleanup inside its own frame. It is the
#                 only source that sees a SIGNAL (measured on this bash: TERM
#                 143, INT 130, HUP 129 — drive_preamble.sh § 6), and it is read
#                 DEFENSIVELY: unset or not a number, and it is not consulted.
#                 Nothing in `drive_preamble.sh` is edited to provide it, and
#                 all three cells below hold with it absent.
census_status_floor() {
    local floor="$CENSUS_FLOOR"
    if [ "$FAILED" -gt 0 ] && [ "$floor" -lt 1 ]; then
        floor=1
    fi
    case "${rc-}" in
    '' | *[!0-9]*) ;;
    *)
        if [ "$rc" -gt "$floor" ]; then
            floor="$rc"
        fi
        ;;
    esac
    printf '%s\n' "$floor"
}

# Registered as its OWN cleanup, after the unplants and before the scratch
# directory goes, so it measures the tree the drive actually leaves behind.
worktree_census_at_exit() {
    [ -f "$WT_CENSUS_BEFORE" ] || return 0
    worktree_census "$ROOT" >"$WT_CENSUS_AFTER" 2>/dev/null || return 0
    local moved
    moved="$(worktree_moved_paths "$WT_CENSUS_BEFORE" "$WT_CENSUS_AFTER")"
    [ -n "$moved" ] || return 0
    local floor
    floor="$(census_status_floor)"
    echo "!! test_gate_explain LEFT THE WORKING TREE MOVED." >&2
    echo "   checkout: ${ROOT}" >&2
    echo "   Every plant this drive makes is restored or removed before it exits." >&2
    echo "   A path below is one it created, overwrote or deleted and did not put" >&2
    echo "   back — and on somebody's product tree that is their file. Nothing this" >&2
    echo "   run asserted is worth the cost of finding out which." >&2
    printf '%s\n' "$moved" | sed 's/^/     /' >&2
    if [ "$floor" != "0" ]; then
        # ALREADY exiting nonzero. Saying so is this census's whole job here;
        # changing it is not. Returning hands the epilogue back its own `rc`,
        # and the scratch cleanup registered after this one still runs.
        echo "   (the drive was already exiting ${floor}; the census reports, it does not lower)" >&2
        return 0
    fi
    # The ONE cell where this census is the verdict: a GREEN drive that moved a
    # path. The scratch directory is ours to clear here, because the cleanup
    # registered after this one never runs once we exit.
    rm -rf "$WORK"
    # 2 still outranks 1: a drive that also moved a REF has broken enforcement,
    # and that verdict is not ours to downgrade by exiting first.
    if ! drive_tripwire_check; then
        exit 2
    fi
    exit 1
}

WT_CENSUS_ARMED=0
if [ -n "${DRIVE_REPO_ROOT:-}" ]; then
    worktree_census "$ROOT" >"$WT_CENSUS_BEFORE" && WT_CENSUS_ARMED=1
fi
[ "$WT_CENSUS_ARMED" = "1" ] ||
    echo "test_gate_explain: not inside a git checkout — the working-tree census is not armed." >&2

drive_at_exit 'unplant; unplant_js; unplant_probe_app'
drive_at_exit 'worktree_census_at_exit'
drive_at_exit 'rm -rf "$WORK"'

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

# THE FLOOR UNDER EVERY `$OUT` READER. Half the assertions in this file are
# NEGATIVE — the engine did NOT name the function-less module, `--terse` did
# NOT drop a line that is neither an ok row nor an override, rule 52 printed
# NO hash-token valve line — and every one of them is TRUE of a capture with
# nothing in it. A run that never started therefore prints `ok`. The shared
# shape is `drive_capture_refusal` (drive_preamble.sh section 7); this is the
# voice, and every case that reads `$OUT` calls it first.
capture_floor() {
    local why
    why="$(drive_capture_refusal "${CURRENT:-a case}" "${OUT:-}" "${RC:-<none>}")" &&
        cannot_look "$why"
    return 0
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
    capture_floor
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
    capture_floor
}

# THE READERS, CAPTURED ONCE, IN ONE PROCESS. `--explain <id>`, `--explain`,
# `--rules` and an unknown flag all return from `main` BEFORE anything
# measures — they read the parsed yaml and nothing else — so five separate
# `uv run python -m quality.gate` invocations were five interpreter starts and
# five imports of the engine to answer five questions about one parse. The
# engine drives them this way itself (`cli_census`, quality/gate.py), through
# `_captured`, which is `main`s own argv dispatch with stdout redirected: the
# claim under test is still that TWO NAMES reach ONE printer, which calling the
# printers directly would not prove.
#
# THE RULE COUNT IS STILL DERIVED SEPARATELY, out of the yaml, in the same
# process. Taking it from `len(gate.RULES)` would make
# `case_the_listing_is_the_same_under_both_names` compare the printer against
# its own input and the case could no longer fail.
READERS_DIR="${WORK}/readers"
READERS_READY=""
readers_once() {
    [ -z "$READERS_READY" ] || return 0
    mkdir -p "$READERS_DIR"
    CURRENT="the readers, captured in one process"
    N=$((N + 1))
    OUT="${WORK}/readers${N}.log"
    RC=0
    DJB_READERS_DIR="$READERS_DIR" uv run python - >"$OUT" 2>&1 <<'PY' || RC=$?
import os
import pathlib
import sys

import yaml

sys.argv = ["gate"]
from quality import gate

out = pathlib.Path(os.environ["DJB_READERS_DIR"])
probes = [
    ("explain-13", ["--explain", "13"]),
    ("explain-999", ["--explain", "999"]),
    ("listing-explain", ["--explain"]),
    ("listing-rules", ["--rules"]),
    ("unknown-flag", ["--tesre"]),
]
for name, argv in probes:
    rc, text = gate._captured(list(argv))
    (out / (name + ".log")).write_text(text, encoding="utf-8")
    (out / (name + ".rc")).write_text(str(rc), encoding="utf-8")
count = len(yaml.safe_load(pathlib.Path("quality/rules.yaml").read_text())["rules"])
(out / "rule-count").write_text(str(count), encoding="utf-8")
print("captured %d reader probes; %d rules in quality/rules.yaml" % (len(probes), count))
PY
    [ "$RC" = "0" ] ||
        cannot_look "the reader capture exited ${RC} — every reader case below would read a capture that was never taken (see ${OUT})"
    READERS_READY=1
}

# reader_probe <name> — one captured reader, in `$OUT`/`$RC`, as if `run_gate`
# had just taken it.
reader_probe() {
    local name=$1 base
    readers_once
    base="${READERS_DIR}/${name}"
    [ -f "${base}.rc" ] ||
        cannot_look "the reader capture left no status for ${name} — the fold above did not run every probe it declares"
    OUT="${base}.log"
    RC="$(cat "${base}.rc")"
    capture_floor
}

readers_once
RULE_COUNT="$(cat "${READERS_DIR}/rule-count" 2>/dev/null || true)"
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

# ONE PLANTED RED, TWO CASES. Both read the same thing out of the same live
# scan — the four trailer keys, and the pasteable marker on the valve line —
# and a live scan of this tree is about eighteen seconds. Two scans were two
# answers to one question, and the second one is the one nobody read. The
# plant is still planted and unplanted inside the memo, so the tree is dirty
# for exactly one scan.
RED_PLANT_READY=""
RED_PLANT_OUT=""
RED_PLANT_RC=0
red_plant_once() {
    if [ -n "$RED_PLANT_READY" ]; then
        OUT="$RED_PLANT_OUT"
        RC="$RED_PLANT_RC"
        capture_floor
        return 0
    fi
    plant_the_red
    run_gate "the planted rule-1 red, scanned once"
    unplant
    RED_PLANT_OUT="$OUT"
    RED_PLANT_RC="$RC"
    RED_PLANT_READY=1
}

case_a_red_carries_its_trailer_once_after_its_findings() {
    red_plant_once
    CURRENT="case_a_red_carries_its_trailer_once_after_its_findings"
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
    red_plant_once
    CURRENT="case_the_trailers_valve_is_the_marker_a_reader_can_paste"
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
    plant_the_js
    run_gate "case_a_frontend_finding_prints_the_slash_valve_token"
    unplant_js
    if [ "$RC" != "1" ]; then
        bad "a planted barrel did not exit 1 (got ${RC}) — the browser-tree red this case reads never happened"
        return
    fi
    # The finding names the plant's own path, so this case also proves the plant
    # is where the drive says it is rather than somewhere a product could own.
    if ! grep -qE "^ +x rule 52: ${JS_TARGET}:" "$OUT"; then
        bad "rule 52's finding does not name ${JS_TARGET} — the plant is not where this drive declares it plants"
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

case_the_plant_refuses_a_path_that_already_exists() {
    # The other half of the same defect. Moving the plant to a `zzz_` name stops the drive
    # standing on a path a PRODUCT owns; this stops it standing on a path the
    # drive's own killed predecessor left. Both are the same sentence — a plant
    # is CREATED, never written over something already there — and until this
    # case the drive had no opinion about what it was overwriting.
    CURRENT="case_the_plant_refuses_a_path_that_already_exists"
    N=$((N + 1))
    OUT="${WORK}/precondition${N}.log"
    RC=0
    # The decoy is a plant of this drive's own making, put there the way the
    # killed run would have left it.
    plant_the_js
    # The EXIT trap is removed inside the subshell EXPLICITLY: `cannot_look`
    # exits 2, and an inherited epilogue would run this drive's unplants and
    # delete its scratch directory while the parent is still using it.
    (
        trap - EXIT
        js_plant_precondition
    ) >"$OUT" 2>&1 || RC=$?
    unplant_js
    if [ "$RC" != "2" ]; then
        bad "the precondition accepted an occupied plant path (exit ${RC}) — a drive that overwrites what it finds is exactly the defect this case exists for"
        return
    fi
    if ! grep -q "already taken" "$OUT"; then
        bad "the refusal does not say the path is taken — a could-not-look nobody can act on"
        return
    fi
    local named=0
    grep -q "$JS_TARGET" "$OUT" && grep -q "$JS_PROBE_DIR" "$OUT" && named=1
    if [ "$named" != "1" ]; then
        bad "the refusal names neither the file nor its directory — the reader has to go and find what is in the way"
        return
    fi
    ok "an occupied plant path is cannot_look naming the file and the directory, never a silent overwrite"
}

case_the_drive_creates_no_frontend_tree_on_a_tree_that_has_none() {
    # The residue half. The old unplant removed the FILE and left every
    # directory `mkdir -p` had made, so on a tree with no `frontend/` the drive
    # left one standing — and an empty `frontend/` is not nothing: the fe leg's
    # tri-state reads the tree's PRESENCE (`quality/worlds.py::tree_verdict`),
    # so a stray one is the "tree present, toolchain absent" cell, which is
    # exit 2.
    #
    # This tree HAS a `frontend/`, so the case cannot ask the question here: it
    # runs the plant and the unplant against a scratch root that has none, with
    # ROOT overridden in a subshell, and asks it there.
    CURRENT="case_the_drive_creates_no_frontend_tree_on_a_tree_that_has_none"
    N=$((N + 1))
    OUT="${WORK}/nofrontend${N}.log"
    RC=0
    local scratch="${WORK}/tree-with-no-frontend"
    rm -rf "$scratch"
    mkdir -p "$scratch"
    (
        trap - EXIT
        ROOT="$scratch"
        plant_the_js
        [ -f "${scratch}/${JS_TARGET}" ] || {
            echo "the plant did not create its own file, so the removal proves nothing"
            exit 3
        }
        unplant_js
    ) >"$OUT" 2>&1 || RC=$?
    if [ "$RC" != "0" ]; then
        bad "planting into a frontend-less tree did not complete (exit ${RC})"
        return
    fi
    if [ -e "${scratch}/frontend" ]; then
        bad "the drive left $(find "$scratch" -mindepth 1 | LC_ALL=C sort | tr '\n' ' ') standing on a tree that had no frontend/ — an empty browser tree is the fe leg's exit-2 cell"
        return
    fi
    ok "the whole created chain is removed: a tree with no frontend/ still has none"
}

case_an_empty_capture_is_could_not_look() {
    # The floor under every `$OUT` reader, shown firing. Half this file asserts
    # NEGATIVES over a capture, and a negative over an empty file is `ok`, so a
    # run that never started would print a clean drive. The plant is the way a
    # refactor makes one: the variable emptied. It runs in a SUBSHELL — which
    # does not run this shell's EXIT trap — so the demonstration costs two
    # processes and leaves nothing behind.
    local out="${WORK}/empty-capture.log" rc=0
    CURRENT="an emptied capture is could-not-look"
    (
        CURRENT="a planted case"
        OUT=""
        RC=0
        capture_floor
        echo "capture_floor returned instead of refusing"
    ) >"$out" 2>&1 || rc=$?
    if [ "$rc" != "2" ]; then
        bad "an emptied capture exited ${rc}, not 2 — a reader that answers a question it could not look at is what this floor exists to stop"
        OUT="$out"
        return
    fi
    if ! grep -qF 'capture with no path at all' "$out"; then
        bad "exit 2, but the refusal never says the capture is what could not be read"
        OUT="$out"
        return
    fi
    ok "exit 2, naming the capture and the exit code of the run that did not fill it"

    # THE NEGATIVE: a capture with bytes in it is judged, never refused.
    CURRENT="a capture with bytes in it is judged, not refused"
    printf 'the engine said something\n' >"${WORK}/non-empty-capture.log"
    rc=0
    (
        CURRENT="a planted case"
        OUT="${WORK}/non-empty-capture.log"
        RC=1
        capture_floor
    ) >"$out" 2>&1 || rc=$?
    if [ "$rc" = "0" ]; then
        ok "the floor is a floor, not an off switch"
    else
        bad "a readable capture was refused with ${rc}: $(sed -n 1p "$out")"
        OUT="$out"
    fi
}

case_the_exit_census_never_lowers_the_drives_own_status() {
    # The census is a CLEANUP: it runs from the EXIT trap, long after the drive
    # decided what it was exiting with. Its first spelling exited 1 on any moved
    # path, which turned a could-not-look into a red — measured on this tree: a
    # killed run leaves the `zzz_` plant, the next run's plant precondition
    # refuses (exit 2), the unplant deletes that leftover, the census sees
    # `moved:` and exits 1. The reader is then told a drive ran and found
    # something when it asserted nothing at all.
    #
    # One MOVED PATH, held constant; three incoming statuses, one cell each:
    #
    #   cannot_look  (floor 2) — reports, RETURNS; the epilogue's own 2 stands
    #   a red drive  (floor 1) — reports, RETURNS; the epilogue's own 1 stands
    #   a green one  (floor 0) — the census IS the verdict: exit 1
    #
    # "Returns" is the property, not "exits with the same number": the census
    # cannot exit with a status it never saw, so the only way it can preserve
    # one is to leave `exit "$rc"` to `drive_epilogue`. The sentinel below is
    # how this case sees the difference.
    CURRENT="case_the_exit_census_never_lowers_the_drives_own_status"

    local ctl="${WORK}/floor-control"
    rm -rf "$ctl"
    mkdir -p "$ctl"
    drive_require_scratch ctl "$ctl"
    git -C "$ctl" init -q
    printf 'a product ships this\n' >"${ctl}/owned.txt"
    git -C "$ctl" add owned.txt
    git -C "$ctl" -c user.name=t -c user.email=t@t commit -q -m seed
    local ctl_work="${WORK}/floor-control-work"
    mkdir -p "$ctl_work"
    worktree_census "$ctl" >"${ctl_work}/worktree-before.lst"
    rm -f "${ctl}/owned.txt"

    # One cell. $1 names it, $2 is the incoming floor, $3 the status the
    # subshell must come back with. The EXIT trap is dropped inside explicitly:
    # an inherited epilogue would run this drive's unplants and delete its
    # scratch directory while the parent is still using it.
    local cell_out="" cell_rc=0
    run_floor_cell() {
        N=$((N + 1))
        cell_out="${WORK}/floor${N}.log"
        cell_rc=0
        (
            trap - EXIT
            ROOT="$ctl"
            WORK="$ctl_work"
            WT_CENSUS_BEFORE="${ctl_work}/worktree-before.lst"
            WT_CENSUS_AFTER="${ctl_work}/worktree-after.lst"
            CENSUS_FLOOR=0
            FAILED=0
            case "$2" in
            2) CENSUS_FLOOR=2 ;;
            1) FAILED=1 ;;
            esac
            # $4, when given, is the SIGNAL status the epilogue would have
            # captured. It is set as a plain variable here for the same reason
            # the real one is visible at all: `census_status_floor` reads `rc`
            # out of whatever frame it is called from.
            [ -z "${4:-}" ] || rc=$4
            worktree_census_at_exit
            # Reached only when the census RETURNED — which is the whole of
            # "it did not lower the drive's status".
            echo "THE-CENSUS-RETURNED"
            exit 0
        ) >"$cell_out" 2>&1 || cell_rc=$?
    }

    # --- cell 1: cannot_look (2) — the defect this case was written for ------
    run_floor_cell "cannot_look" 2 0
    if [ "$cell_rc" != "0" ] || ! grep -q '^THE-CENSUS-RETURNED$' "$cell_out"; then
        OUT="$cell_out"
        bad "cell cannot_look: the census did not return (exit ${cell_rc}) — a could-not-look downgraded to a red is the defect this case exists for"
        return
    fi
    if ! grep -q 'already exiting 2' "$cell_out"; then
        OUT="$cell_out"
        bad "cell cannot_look: the census did not say it was leaving the 2 alone — a reader cannot tell a preserved status from a missed census"
        return
    fi

    # --- cell 2: a red drive (1) ---------------------------------------------
    run_floor_cell "a red drive" 1 0
    if [ "$cell_rc" != "0" ] || ! grep -q '^THE-CENSUS-RETURNED$' "$cell_out"; then
        OUT="$cell_out"
        bad "cell a red drive: the census did not return (exit ${cell_rc}) — a drive already exiting 1 has its own verdict"
        return
    fi
    if ! grep -q 'already exiting 1' "$cell_out"; then
        OUT="$cell_out"
        bad "cell a red drive: the census did not say it was leaving the 1 alone"
        return
    fi

    # --- cell 4: a SIGNAL status (143) — the cell the coupling depends on ----
    #
    # THE ONLY CELL THAT EXERCISES `rc`. Cells 1-3 are reachable with `rc` unset
    # and stayed green while nothing at all read it, so a rename of
    # `drive_epilogue`'s `local rc` (drive_preamble.sh § 6) would have dropped
    # 143 to 1 with every assertion above still passing — a drive KILLED by a
    # harness reported as a drive that found a violation. This cell is the
    # tripwire for that coupling, and § 6 now names `rc` as part of its contract.
    run_floor_cell "a signal status" 0 0 143
    if [ "$cell_rc" != "0" ] || ! grep -q '^THE-CENSUS-RETURNED$' "$cell_out"; then
        OUT="$cell_out"
        bad "cell a signal status: the census did not return (exit ${cell_rc}) — a TERM-killed drive would have been reported as this census's own finding"
        return
    fi
    if ! grep -q 'already exiting 143' "$cell_out"; then
        OUT="$cell_out"
        bad "cell a signal status: the census did not say it was leaving the 143 alone — \`rc\` was not read, so a signal had been lowered to a red"
        return
    fi
    ok "a TERM-killed drive keeps its 143: the census reports and returns (the \`rc\` coupling drive_preamble.sh § 6 declares)"

    # --- cell 3: a green drive (0) — the one cell the census is the verdict ---
    run_floor_cell "a green drive" 0 1
    if [ "$cell_rc" != "1" ]; then
        OUT="$cell_out"
        bad "cell a green drive: a moved path under a green drive did not exit 1 (got ${cell_rc}) — the census would have nothing to raise"
        return
    fi
    if grep -q '^THE-CENSUS-RETURNED$' "$cell_out"; then
        OUT="$cell_out"
        bad "cell a green drive: the census returned instead of exiting — a green drive that moved a path would be read as a pass"
        return
    fi

    # Every cell reports the path, whatever it does with the status: a census
    # that goes quiet because the drive was already red is a census nobody can
    # act on.
    local seen=0 f
    for f in "${WORK}"/floor*.log; do
        grep -q '^     moved: owned.txt$' "$f" && seen=$((seen + 1))
    done
    if [ "$seen" != "4" ]; then
        bad "only ${seen} of 4 cells named the moved path — the census must report at every incoming status, and only the verdict changes"
        return
    fi
    OUT=""
    ok "cannot_look keeps its 2 and a red drive its 1; only a green drive's 0 is raised to 1, and all three name the path"
}

case_the_drive_leaves_the_working_tree_as_it_found_it() {
    # The tripwire's shape one layer down, and it runs LAST so it sees the tree
    # every other case left behind. Two halves, because an assertion that can
    # only pass is not an instrument:
    #
    #   the ASSERTION — this checkout's working tree is as this drive found it
    #   the CONTROL   — the exit census, run against a scratch git repository
    #                   with one tracked file deleted, names it and exits 1
    CURRENT="case_the_drive_leaves_the_working_tree_as_it_found_it"
    N=$((N + 1))
    OUT="${WORK}/worktree${N}.log"
    RC=0

    if [ "$WT_CENSUS_ARMED" != "1" ]; then
        bad "the working-tree census was never armed, so this case measured nothing"
        return
    fi
    worktree_census "$ROOT" >"${WORK}/worktree-now.lst"
    local moved
    moved="$(worktree_moved_paths "$WT_CENSUS_BEFORE" "${WORK}/worktree-now.lst")"
    if [ -n "$moved" ]; then
        bad "the drive has already moved the working tree by its last case:
$(printf '%s\n' "$moved" | sed 's/^/             | /')"
        return
    fi

    # --- the control ---------------------------------------------------------
    local ctl="${WORK}/moved-control"
    rm -rf "$ctl"
    mkdir -p "$ctl"
    drive_require_scratch ctl "$ctl"
    git -C "$ctl" init -q
    printf 'a product ships this\n' >"${ctl}/owned.txt"
    git -C "$ctl" add owned.txt
    git -C "$ctl" -c user.name=t -c user.email=t@t commit -q -m seed
    local ctl_work="${WORK}/moved-control-work"
    mkdir -p "$ctl_work"
    worktree_census "$ctl" >"${ctl_work}/worktree-before.lst"
    rm -f "${ctl}/owned.txt"
    RC=0
    (
        trap - EXIT
        ROOT="$ctl"
        WORK="$ctl_work"
        WT_CENSUS_BEFORE="${ctl_work}/worktree-before.lst"
        WT_CENSUS_AFTER="${ctl_work}/worktree-after.lst"
        # The cell this control has always been: a GREEN drive that moved a
        # path. Pinned rather than inherited, because an earlier case having
        # failed would otherwise put this control in the `floor 1` cell, where
        # the census reports and returns instead of exiting — and the control
        # would red for the drive's history rather than for its own property.
        CENSUS_FLOOR=0
        FAILED=0
        worktree_census_at_exit
    ) >"$OUT" 2>&1 || RC=$?
    if [ "$RC" != "1" ]; then
        bad "a tracked file deleted under the census did not make the exit census exit 1 (got ${RC}) — the assertion above can pass without being able to fail"
        return
    fi
    if ! grep -q '^     moved: owned.txt$' "$OUT"; then
        bad "the exit census did not name the deleted path as \`moved: owned.txt\` — a refusal that does not say which file is one nobody can act on"
        return
    fi
    ok "this tree is as the drive found it, and a deleted tracked file is exit 1 naming it"
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

# ONE PLANTED SUBJECT, TWO CASES, for the reason above: the red that names the
# module and the function, and the remedy line under it, are two readings of
# one live scan.
PROBE_FN_READY=""
PROBE_FN_OUT=""
PROBE_FN_RC=0
probe_app_with_function_once() {
    if [ -n "$PROBE_FN_READY" ]; then
        OUT="$PROBE_FN_OUT"
        RC="$PROBE_FN_RC"
        capture_floor
        return 0
    fi
    plant_probe_app with-a-function
    run_gate "the probe app with one top-level def, scanned once"
    unplant_probe_app
    PROBE_FN_OUT="$OUT"
    PROBE_FN_RC="$RC"
    PROBE_FN_READY=1
}

case_one_function_is_a_subject_and_still_reds_without_a_ceiling() {
    probe_app_with_function_once
    CURRENT="case_one_function_is_a_subject_and_still_reds_without_a_ceiling"
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
    probe_app_with_function_once
    CURRENT="case_a_new_function_subject_prints_its_paste_line"
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
    reader_probe explain-13
    CURRENT="case_explain_prints_the_rules_own_declaration"
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
    reader_probe explain-999
    CURRENT="case_explain_of_an_unknown_id_is_exit_2_naming_the_listing"
    if [ "$RC" = "2" ] && grep -q 'listing' "$OUT"; then
        ok "an unknown id is could-not-look, and says where the ids are"
    else
        bad "--explain 999 exited ${RC} without naming the listing"
    fi
}

case_the_listing_is_the_same_under_both_names() {
    reader_probe listing-explain
    local bare="$OUT"
    local bare_rc="$RC"
    reader_probe listing-rules
    CURRENT="case_the_listing_is_the_same_under_both_names"
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
    reader_probe unknown-flag
    CURRENT="case_an_unknown_flag_is_still_exit_2"
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


# --- the memo ----------------------------------------------------------------
#
# THE PER-RULE MEMO, driven through the shipped engine. Every case below forges
# in process (`forge`, above) for the reason that idiom exists here: the claim
# is about the FUNCTIONS this gate ships, and a case that re-implemented the key
# would prove only that its copy is deterministic. Each one points the memo at a
# directory under this drive's own `$WORK` — never at the checkout's real memo,
# which is shared across its worktrees exactly as the gate ledger is.
#
# WHAT THESE CASES DO NOT COVER, declared: whether a rule that DECLINES the memo
# was right to (a reviewer's finding, as the reason text is); the wall-clock
# saving, which is a measurement the PM writes from a bank log and never a drive
# assertion; and a check that reads a path its walk does not name, which is the
# engine's population-4 blind spot inherited exactly.

MEMO_HOME_N=0
memo_home_dir() {
    MEMO_HOME_N=$((MEMO_HOME_N + 1))
    printf '%s\n' "${WORK}/memo${MEMO_HOME_N}"
}

case_a_memoised_rule_is_not_rescanned() {
    local home
    home="$(memo_home_dir)"
    DJB_RULES_MEMO_DIR="$home" forge "case_a_memoised_rule_is_not_rescanned" '
import sys
sys.argv = ["gate"]
from quality import gate
from quality.checks import REGISTRY, CheckResult

calls = {"n": 0}
def stub(root, rule):
    calls["n"] += 1
    return CheckResult()
REGISTRY["zzz_drive_memo"] = stub
rule = {"id": "zzz-drive-memo", "enabled": True, "check": "zzz_drive_memo",
        "doc": {"file": "quality/rules.yaml", "contains": "rules"}, "scope": {}}
gate.memo_reset()
gate.memo_consult(rule, "zzz_drive_memo")
gate.memo_consult(rule, "zzz_drive_memo")
gate.memo_consult(rule, "zzz_drive_memo")
gate.memo_report()
print("check ran %d time(s) for %d hit(s)" % (calls["n"], gate.memo_counts["hits"]))
sys.exit(0 if calls["n"] == 1 and gate.memo_counts["hits"] == 2 else 1)
'
    if [ "$RC" = "0" ] && grep -q "house rules: .* scanned · .* memoized" "$OUT"; then
        ok "three consults on one tree ran the check once, and the run says how many it memoized"
    else
        bad "a rule whose every input was byte-identical was rescanned, or the run did not print its scanned/memoized count (see ${OUT})"
    fi
}

case_a_moved_input_misses_one_rule_and_names_it() {
    local home
    home="$(memo_home_dir)"
    DJB_RULES_MEMO_DIR="$home" forge "case_a_moved_input_misses_one_rule_and_names_it" '
import pathlib
import sys
sys.argv = ["gate"]
from quality import gate

real = [r for r in gate.RULES
        if r.get("enabled", True) and r.get("check") and gate.memo_declines(r) is None]
base = {str(r["id"]): gate.memo_key(r)[0] for r in real}

# (i) one byte of the rule STATEMENT -> that rule alone re-keys.
victim = real[0]
vid = str(victim["id"])
moved = dict(victim)
moved["statement"] = str(victim.get("statement", "")) + " "
after = {str(r["id"]): gate.memo_key(moved if str(r["id"]) == vid else r)[0] for r in real}
by_text = sorted(k for k in base if base[k] != after.get(k))

# (ii) one byte of the DOC ANCHOR the rule declares.
doc_moved = dict(victim)
doc_moved["doc"] = dict(victim.get("doc") or {})
doc_moved["doc"]["contains"] = str(doc_moved["doc"].get("contains", "")) + "x"
by_doc = gate.memo_key(doc_moved)[0] != base[vid]

# (iii) one byte inside the WALK the rule reads -> every rule of that kind.
target = pathlib.Path("apps/example/selectors.py")
saved = target.read_bytes()
try:
    target.write_bytes(saved + b"\n# one byte the walk must see\n")
    gate._MEASURED = None
    by_walk = {str(r["id"]): gate.memo_key(r)[0] for r in real}
finally:
    target.write_bytes(saved)
    gate._MEASURED = None
walked = sorted(k for k in base if base[k] != by_walk.get(k))

# and the MISS LINE names the component.
from quality.checks import REGISTRY, CheckResult
REGISTRY["zzz_drive_memo"] = lambda root, rule: CheckResult()
probe = {"id": "zzz-drive-miss", "enabled": True, "check": "zzz_drive_memo",
         "doc": {"file": "quality/rules.yaml", "contains": "rules"}, "scope": {}}
gate.memo_reset()
gate.memo_consult(probe, "zzz_drive_memo")
second = dict(probe)
second["statement"] = "a byte the first key never saw"
gate.memo_consult(second, "zzz_drive_memo")
named = [ln for ln in gate.memo_lines if "miss(rule)" in ln]
print("statement moved: %s" % by_text)
print("doc anchor moved the key: %s" % by_doc)
print("a walk byte re-keyed %d of %d rules of that kind" % (len(walked), len(real)))
print("the miss line: %s" % (named or gate.memo_lines))
sys.exit(0 if by_text == [vid] and by_doc and walked and named else 1)
'
    if [ "$RC" = "0" ]; then
        ok "a moved statement re-keys one rule, a moved doc anchor re-keys its rule, a moved walk byte re-keys the kind, and the miss names the component"
    else
        bad "an input moved without the key moving, or a miss could not say what moved (see ${OUT})"
    fi
}

case_a_hit_replays_the_red() {
    local home
    home="$(memo_home_dir)"
    DJB_RULES_MEMO_DIR="$home" forge "case_a_hit_replays_the_red" '
import sys
sys.argv = ["gate"]
from quality import gate
from quality.checks import REGISTRY, CheckResult

def red(root, rule):
    out = CheckResult()
    out.hit("apps/example/selectors.py", 7, "the drive plant: a violation that must survive a hit")
    out.count("modules", 3)
    return out
REGISTRY["zzz_drive_red"] = red
rule = {"id": "zzz-drive-red", "enabled": True, "check": "zzz_drive_red",
        "doc": {"file": "quality/rules.yaml", "contains": "rules"}, "scope": {}}
gate.memo_reset()
cold = gate.memo_consult(rule, "zzz_drive_red")
warm = gate.memo_consult(rule, "zzz_drive_red")
same = [str(f) for f in cold.findings] == [str(f) for f in warm.findings]
print("cold: %s" % [str(f) for f in cold.findings])
print("warm: %s" % [str(f) for f in warm.findings])
print("targets cold=%s warm=%s hits=%d" % (cold.targets_matched, warm.targets_matched, gate.memo_counts["hits"]))
sys.exit(0 if same and warm.findings and warm.targets_matched == cold.targets_matched
         and gate.memo_counts["hits"] == 1 else 1)
'
    if [ "$RC" = "0" ]; then
        ok "a hit replays the finding and its targets, byte for byte — a memoised violation is still a violation"
    else
        bad "a hit printed ok over a banked violation, or lost its targets (see ${OUT})"
    fi
}

case_the_selftest_bypasses_the_memo_and_its_canaries_still_fire() {
    local home
    home="$(memo_home_dir)"
    DJB_RULES_MEMO_DIR="$home" forge "case_the_selftest_bypasses_the_memo_and_its_canaries_still_fire" '
import pathlib
import sys
sys.argv = ["gate"]
from quality import gate
from quality.checks import REGISTRY, CheckResult

# THE PLANT IS A FALSE MEMO ENTRY: it says this rule found nothing, under the
# very key the consult will compute. With the memo live it MUST win — that is
# what makes it a real plant rather than an inert file — and under the
# self-test bypass the check MUST run anyway and its finding MUST come back.
def red(root, rule):
    out = CheckResult()
    out.hit("apps/example/selectors.py", 1, "the canary the false entry must not silence")
    return out
REGISTRY["zzz_drive_canary"] = red
rule = {"id": "zzz-drive-canary", "enabled": True, "check": "zzz_drive_canary",
        "doc": {"file": "quality/rules.yaml", "contains": "rules"}, "scope": {}}
home = pathlib.Path(gate.memo_home()[0])
key, components, why = gate.memo_key(rule)
gate.memo_write(home, str(rule["id"]), str(key), components, CheckResult())
warmed = sorted(p.name for p in (home / str(rule["id"])).glob("*.json"))

gate.memo_reset()
gate.memo_state["bypass"] = False
silenced = gate.memo_consult(rule, "zzz_drive_canary")
gate.memo_state["bypass"] = True
fired = gate.memo_consult(rule, "zzz_drive_canary")
after = sorted(p.name for p in (home / str(rule["id"])).glob("*.json"))
print("the false entry, with the memo live: %d finding(s)" % len(silenced.findings))
print("the same entry, under the bypass:    %d finding(s)" % len(fired.findings))
print("memo files before=%s after=%s" % (warmed, after))
sys.exit(0 if not silenced.findings and len(fired.findings) == 1 and warmed == after else 1)
'
    if [ "$RC" = "0" ]; then
        ok "a planted false memo entry silences the finding with the memo live and does NOT under the self-test bypass, and the bypass wrote nothing"
    else
        bad "the self-test bypass is a printed word: either the plant was inert, or the bypass read or wrote the memo (see ${OUT})"
    fi
}

case_memo_no_scans_always_and_needs_a_reason() {
    local home
    home="$(memo_home_dir)"
    DJB_RULES_MEMO_DIR="$home" forge "case_memo_no_scans_always_and_needs_a_reason" '
import sys
sys.argv = ["gate"]
from quality import gate
from quality.checks import REGISTRY, CheckResult

calls = {"n": 0}
def stub(root, rule):
    calls["n"] += 1
    return CheckResult()
REGISTRY["zzz_drive_declines"] = stub
declining = {"id": "zzz-drive-declines", "enabled": True, "check": "zzz_drive_declines",
             "doc": {"file": "quality/rules.yaml", "contains": "rules"}, "scope": {},
             "memo": {"no": "the drive s own scratch rule, declining on purpose"}}
gate.memo_reset()
gate.memo_consult(declining, "zzz_drive_declines")
gate.memo_consult(declining, "zzz_drive_declines")
scanned_always = calls["n"] == 2 and gate.memo_counts["hits"] == 0

refusals = []
for shape in ({"no": ""}, {"no": "too short"}, "no", {False: "a bare yaml no key"}):
    victim = dict(declining)
    victim["memo"] = shape
    gate.broken.clear()
    gate.memo_consistency([victim])
    refusals.append(list(gate.broken))
gate.broken.clear()

# and rule 42 on the real tree declares it, with a reason a reader can weigh.
real = gate.RULES_BY_ID.get("42") or {}
declared = gate.memo_declines(real)

print("the declining rule scanned twice: %s (hits %d)" % (scanned_always, gate.memo_counts["hits"]))
for shape, said in zip(("empty", "short", "scalar", "bare-yaml-no"), refusals):
    print("  %-13s -> %s" % (shape, (said[0][:110] if said else "NOTHING REFUSED")))
print("rule 42 declines with: %s" % ((declared or "")[:80] or "NOTHING"))
sys.exit(0 if scanned_always and all(refusals) and declared else 1)
'
    if [ "$RC" = "0" ]; then
        ok "a declining rule scans on every run and is never a hit, and a declaration with no reason — including a bare yaml no, which parses as false — is ENFORCEMENT BROKEN"
    else
        bad "a memo: no was honoured without a reason, or a declining rule was memoised anyway (see ${OUT})"
    fi
}

case_an_undecidable_key_scans() {
    local home
    home="$(memo_home_dir)"
    DJB_RULES_MEMO_DIR="$home" forge "case_an_undecidable_key_scans" '
import sys
sys.argv = ["gate"]
from quality import gate
from quality.checks import REGISTRY, CheckResult

calls = {"n": 0}
def stub(root, rule):
    calls["n"] += 1
    return CheckResult()
REGISTRY["zzz_drive_blind"] = stub

# (i) a scope this tree cannot expand. The victim is built here and the doc
#     carries no path literal — a made-up docs path would be a dangling pointer
#     the documentation census reads.
blind = {"id": "zzz-drive-blind", "enabled": True, "check": "zzz_drive_blind",
         "doc": {"file": "quality/rules.yaml", "contains": "rules"},
         "scope": {"allow_import": [{"path": "apps/nowhere/*.py"}]}}
gate.memo_reset()
gate.memo_consult(blind, "zzz_drive_blind")
gate.memo_consult(blind, "zzz_drive_blind")
by_scope = (calls["n"] == 2 and gate.memo_counts["undecidable"] == 2
            and gate.memo_counts["hits"] == 0
            and len([ln for ln in gate.memo_lines if "memo undecidable" in ln]) == 2)
said = list(gate.memo_lines)

# (ii) git itself refusing. The measured tree is what every component is read
#      from, so a git that will not answer is could-not-look for every rule.
saved = gate._MEASURED
ok_key = {"id": "zzz-drive-blind2", "enabled": True, "check": "zzz_drive_blind",
          "doc": {"file": "quality/rules.yaml", "contains": "rules"}, "scope": {}}
try:
    gate._MEASURED = ({}, "`git ls-tree` exited 128 — not a git repository")
    gate.memo_reset()
    before = calls["n"]
    gate.memo_consult(ok_key, "zzz_drive_blind")
    by_git = (calls["n"] - before == 1 and gate.memo_counts["undecidable"] == 1
              and gate.memo_counts["hits"] == 0)
    said += gate.memo_lines
finally:
    gate._MEASURED = saved

for line in said:
    print("  %s" % line)
print("by_scope=%s by_git=%s" % (by_scope, by_git))
sys.exit(0 if by_scope and by_git else 1)
'
    if [ "$RC" = "0" ]; then
        ok "a key that cannot be derived scans every time, prints why, and is never a hit — could-not-look outranks a cache"
    else
        bad "an undecidable key read the cache, or scanned without saying so (see ${OUT})"
    fi
}

case_the_three_readers_ignore_the_memo() {
    local home
    home="$(memo_home_dir)"
    DJB_RULES_MEMO_DIR="$home" forge "case_the_three_readers_ignore_the_memo" '
import pathlib
import sys
sys.argv = ["gate"]
from quality import gate

# The three readers return before anything measures, so a warm memo must not
# change one byte of what they print — and must not grow by one file either.
cold = {name: gate._captured(argv) for name, argv in (
    ("explain", ["--explain", "13"]),
    ("rules", ["--rules"]),
    ("inputs", ["--selftest-inputs"]),
)}
home = pathlib.Path(gate.memo_home()[0])
from quality.checks import CheckResult
for rule in gate.RULES:
    if not (rule.get("enabled", True) and rule.get("check")) or gate.memo_declines(rule) is not None:
        continue
    key, components, why = gate.memo_key(rule)
    if key:
        gate.memo_write(home, str(rule["id"]), key, components, CheckResult())
warm = {name: gate._captured(argv) for name, argv in (
    ("explain", ["--explain", "13"]),
    ("rules", ["--rules"]),
    ("inputs", ["--selftest-inputs"]),
)}
banked = len(list(home.rglob("*.json")))
for name in cold:
    print("%-8s identical=%s rc=%d" % (name, cold[name] == warm[name], warm[name][0]))
print("entries banked before the warm read: %d" % banked)
sys.exit(0 if cold == warm and all(rc == 0 for rc, _ in warm.values()) and banked else 1)
'
    if [ "$RC" = "0" ]; then
        ok "--explain, --rules and --selftest-inputs print the same bytes over a warm memo as over a cold one"
    else
        bad "a reader's output moved when the memo was warmed, or a reader stopped answering (see ${OUT})"
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
case_the_plant_refuses_a_path_that_already_exists
case_the_drive_creates_no_frontend_tree_on_a_tree_that_has_none
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
case_a_memoised_rule_is_not_rescanned
case_a_moved_input_misses_one_rule_and_names_it
case_a_hit_replays_the_red
case_the_selftest_bypasses_the_memo_and_its_canaries_still_fire
case_memo_no_scans_always_and_needs_a_reason
case_an_undecidable_key_scans
case_the_three_readers_ignore_the_memo
case_an_empty_capture_is_could_not_look
case_the_exit_census_never_lowers_the_drives_own_status
# LAST, deliberately: it reads the tree every case above left behind.
case_the_drive_leaves_the_working_tree_as_it_found_it

echo "test_gate_explain: ${PASSED} passed · ${FAILED} failed"
drive_finished
if [ "$FAILED" -gt 0 ]; then
    echo "!! a red can no longer explain itself. The trailer, the two readers and" >&2
    echo "   --terse are the difference between a builder acting on a finding and a" >&2
    echo "   builder going to look for the rule in a 7,000-line yaml." >&2
    exit 1
fi
exit 0
