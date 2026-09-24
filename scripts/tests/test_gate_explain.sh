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
# drives: CLAUDE.md apps/ config/ frontend/src/components quality/ scripts/kill_mine.sh scripts/queue_cited.sh scripts/sweep.sh pyproject.toml
# cites: docs/product/architecture.md .env.example
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
#   the READERS — `--explain <id>`, the listing under both names, `--fold-map`
#                 (the fold instrument item 7 of the 2.1.1 release sends a
#                 product to), exit 2 on an unknown id and on an unknown flag,
#                 and the grammar sentence naming every argument that exists
#   the FLAG    — `--terse` drops exactly the `ok` rows and the standing-
#                 override rows, and NEVER the ENFORCEMENT BROKEN block
#   the CENSUS  — the trailer and CLI censuses SAY they ran, so deleting the
#                 call is visible rather than silent
#   the TREE CENSUS — a rule's `census:` callable, run by `--explain <id>` over
#                 this tree: it prints, an absent key changes nothing, an
#                 unresolvable one is exit 2 naming it, a raising one is a
#                 could-not-look line rather than a dead reader
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

# >>> one case, by name >>>
# `--case <name>` runs exactly that case and nothing else. The seam exists so
# rule 60's drawer census can prove ONE PLANT PER DRAWER through the drive that
# already owns the property, rather than re-implementing the drawer's reader —
# a second implementation of a reader is a second opinion about it. A name this
# file does not define is exit 2, never a silent run of nothing.
ONLY_CASE=""
run_case() {
    [ -z "$ONLY_CASE" ] || [ "$1" = "$ONLY_CASE" ] || return 0
    "$@"
}
# <<< one case, by name <<<
case "${1:-}" in
"") ;;
--list)
    # THE DEFINITION, NOT THE CALL. `^case_` matched the definition line AND
    # the column-zero invocation at the foot of this file, so every case was
    # named twice; `test_list_legs.sh:149` is the form that was already right.
    grep -n '^case_[A-Za-z0-9_]*() {' "$0" | sed 's/() {.*//; s/^/  /'
    exit 0
    ;;
--case)
    [ -n "${2:-}" ] || {
        echo "!! --case needs a case name; --list names them" >&2
        exit 2
    }
    grep -q "^${2}() {" "$0" || {
        echo "!! --case: test_gate_explain.sh defines no case named '${2}'; --list names them" >&2
        exit 2
    }
    ONLY_CASE="$2"
    ;;
*)
    echo "!! unknown argument '$1': test_gate_explain.sh takes nothing, --list or --case <name>" >&2
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
# `--rules`, `--fold-map` and an unknown flag all return from `main` BEFORE anything
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
    ("explain-54", ["--explain", "54"]),
    ("explain-55", ["--explain", "55"]),
    ("explain-999", ["--explain", "999"]),
    ("listing-explain", ["--explain"]),
    ("listing-rules", ["--rules"]),
    ("unknown-flag", ["--tesre"]),
    # THE FOURTH READER. `--fold-map` is the instrument item 7 of the 2.1.1
    # release sends a product to before it renames anything, so its refusals
    # are part of the same grammar every case below is about.
    ("fold-map-bare", ["--fold-map"]),
    ("fold-map-flag-next", ["--fold-map", "--rules"]),
    ("fold-map-self", ["--fold-map", "quality/rules.yaml"]),
    # HOTFIX-RULEMAP-2. The TEMPLATE SIDE is an argument now, so the two
    # ways of typing it wrongly are part of the same grammar: a second path
    # that is not a file, and `--template-tree` with no --fold-map to be
    # meaningful to.
    ("fold-map-second-missing", ["--fold-map", "quality/rules.yaml", "no-such-template.yaml"]),
    ("template-tree-orphan", ["--template-tree", "."]),
    ("fold-map-with-tree", ["--fold-map", "quality/rules.yaml", "--template-tree", "."]),
]
for name, argv in probes:
    rc, text = gate._captured(list(argv))
    (out / (name + ".log")).write_text(text, encoding="utf-8")
    (out / (name + ".rc")).write_text(str(rc), encoding="utf-8")
count = len(yaml.safe_load(pathlib.Path("quality/rules.yaml").read_text())["rules"])
(out / "rule-count").write_text(str(count), encoding="utf-8")
# THE LISTING'S POPULATION IS BOTH DOCUMENTS. A product's drawer rules
# are listed beside the template's, tagged [local], so the listing's expected
# line count is the template document's rules PLUS the drawer's — read out of
# the drawer's own yaml here, still never from `gate.RULES`, so the case keeps
# comparing the printer against something other than its own input. On the
# template there is no drawer and the two counts are one number.
drawer = pathlib.Path("quality/local/rules.yaml")
drawer_doc = yaml.safe_load(drawer.read_text()) if drawer.is_file() else None
drawer_count = len((drawer_doc or {}).get("rules") or []) if isinstance(drawer_doc, dict) else 0
(out / "listed-count").write_text(str(count + drawer_count), encoding="utf-8")
print(
    "captured %d reader probes; %d rules in quality/rules.yaml, %d in the drawer"
    % (len(probes), count, drawer_count)
)
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
LISTED_COUNT="$(cat "${READERS_DIR}/listed-count" 2>/dev/null || true)"
[ -n "$LISTED_COUNT" ] || cannot_look "the listing's population (template rules + drawer rules) derived empty"

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
    if [ "$listed" = "$LISTED_COUNT" ]; then
        ok "one line per rule, ${listed} of ${LISTED_COUNT} (${RULE_COUNT} template + $((LISTED_COUNT - RULE_COUNT)) drawer), byte-identical under both names"
    else
        bad "the listing printed ${listed} lines for ${LISTED_COUNT} rules (${RULE_COUNT} template + $((LISTED_COUNT - RULE_COUNT)) drawer)"
    fi
}

# --- the remedies: a fix form per finding class (ADR gate-6) -----------------

case_explain_prints_a_remedy_per_finding_class() {
    reader_probe explain-54
    CURRENT="case_explain_prints_a_remedy_per_finding_class"
    local fifty_four
    fifty_four="$(grep -c '^remedies: ' "$OUT" || true)"
    if [ "$RC" != "0" ]; then
        bad "--explain 54 exited ${RC}"
        return
    fi
    if [ "$fifty_four" != "3" ]; then
        bad "--explain 54 printed ${fifty_four} remedies lines, not one per finding class (3)"
        return
    fi
    if ! grep -q '^remedies: nonconforming .*RENAMED_PERMISSIONS' "$OUT" ||
        ! grep -q '^remedies: role-value .*holds(actor' "$OUT" ||
        ! grep -q '^remedies: read .*require(actor' "$OUT"; then
        bad "--explain 54's remedies do not name the three fix forms a reader writes instead"
        return
    fi
    reader_probe explain-55
    CURRENT="case_explain_prints_a_remedy_per_finding_class"
    local fifty_five
    fifty_five="$(grep -c '^remedies: ' "$OUT" || true)"
    if [ "$RC" = "0" ] && [ "$fifty_five" = "1" ] && grep -q '^remedies: \* ' "$OUT"; then
        ok "rule 54 prints three remedies (nonconforming, role-value, read) and rule 55 the one its per-app classes share"
    else
        bad "--explain 55 exited ${RC} with ${fifty_five} remedies lines; its per-app classes share exactly one"
    fi
}

case_a_finding_of_a_remedied_rule_names_its_fix_form() {
    forge "case_a_finding_of_a_remedied_rule_names_its_fix_form" '
import sys
sys.argv = ["gate"]
from quality import gate

gate.record_violation("54", "apps/acme/selectors.py:12: asks no gadget.read")
with_remedy = gate.violations[-1]
gate.record_violation("13", "apps/acme/services.py:3: a write outside a service")
without = gate.violations[-1]
print("54:", with_remedy)
print("13:", without)
sys.exit(
    0
    if with_remedy.endswith("fix form: --explain 54") and "fix form" not in without
    else 1
)
'
    if [ "$RC" = "0" ]; then
        ok "a finding of a rule that declares remedies ends with 'fix form: --explain 54'; one of a rule that declares none carries no tail"
    else
        bad "the fix-form pointer is missing from a remedied rule's finding, or was added to a rule that has no remedies"
    fi
}

# --- the unmeasured ratchet class (ADR gate-6) -------------------------------

case_an_unmeasured_class_prints_the_line_to_paste() {
    forge "case_an_unmeasured_class_prints_the_line_to_paste" '
import sys
sys.argv = ["gate"]
from quality import gate
from quality.checks import Finding

hit = Finding("apps/acme/selectors.py", 12, "asks no gadget.read", "acme.read")
unrecorded = gate.apply_ratchets({"id": "54", "ratchets": {}}, [hit])
headers = [f for f in unrecorded if f.path == "quality/rules.yaml"]
kept = [f for f in unrecorded if f.path != "quality/rules.yaml"]
recorded = gate.apply_ratchets({"id": "54", "ratchets": {"acme.read": 1}}, [hit])
template_app = gate.apply_ratchets(
    {"id": "54", "ratchets": {}},
    [Finding("apps/core/selectors.py", 12, "asks no gadget.read", "core.read")],
)
paste = "acme.read: 1  # recorded-at %s [fold]" % gate.recording_sha()
print("headers:", [f.msg for f in headers])
print("kept:", [str(f) for f in kept])
print("after recording:", [str(f) for f in recorded])
print("template app:", [str(f) for f in template_app])
ok = (
    len(headers) == 1
    and paste in headers[0].msg
    and "apps/acme" in headers[0].msg
    and "platform_apps" in headers[0].msg
    and "quality/local/rules.yaml" in headers[0].msg
    and chr(34) + "54" + chr(34) + ":" in headers[0].msg
    and len(kept) == 1
    and not recorded
    and not [f for f in template_app if f.path == "quality/rules.yaml"]
    and len(template_app) == 1
)
sys.exit(0 if ok else 1)
'
    if [ "$RC" = "0" ]; then
        ok "a class keyed on an app outside the partition with no entry is still exit 1 and prints the ratchets: line to paste INTO THE DRAWER (quality/local/rules.yaml, under its \"54\": block); pasting it makes the class a note; a template app is offered nothing"
    else
        bad "the unmeasured branch did not print the line to paste, softened the violation, or offered a template app a recording (see ${OUT})"
    fi
}

# --- the product valve, end to end (V-D rider) -------------------------------

case_a_product_valve_suppresses_and_is_counted() {
    forge "case_a_product_valve_suppresses_and_is_counted" '
import copy
import pathlib
import shutil
import sys
sys.argv = ["gate"]
from quality import gate

# THE FORGED ID IS ONE THIS TREE DOES NOT OWN. A product whose
# namespace is `acme` numbers its first drawer rule acme-1, and a typed id
# then collided with that rule and with its fixture directory.
RID = next(
    f"acme-{n}"
    for n in range(1, 1000)
    if f"acme-{n}" not in gate.RULES_BY_ID
    and not any(
        (d / f"acme-{n}").exists()
        for d in (gate.CANARY_DIR, gate.NEGATIVE_DIR, gate.LOCAL_CANARY_DIR, gate.LOCAL_NEGATIVE_DIR)
    )
)
rule = copy.deepcopy(gate.RULES_BY_ID["1"])
rule["id"] = RID
# THE HOME IS ASKED FOR, NEVER SPELLED. `fixture_home` is the ONE resolver
# — a rule loaded from the product drawer lives under the drawer, a rule in
# the template document under the template tree — and a drive that typed
# either would be one more place teaching a product where its fixtures go.
# This forged rule is appended to the list the TEMPLATE document declares,
# rather than loaded from the drawer, so the resolver answers the template
# tree for it;
# a real product rule comes out of the drawer, and the case that plants one
# there is case_a_drawer_rule_is_a_rule_end_to_end.
made = []
for kind in ("canary", "negative"):
    dst = gate.fixture_home(kind, RID)
    shutil.copytree(gate.fixture_home(kind, "1"), dst)
    made.append(dst)
through = max(int(r["id"]) for r in gate.RULES if gate.is_template_id(str(r["id"])))
entry = rule["canaries"][0]
rc = 1
try:
    with gate._as_product_tree("acme", through):
        plant = gate.Plant()
        try:
            plant.put(
                gate.fixture_home("canary", RID) / entry["fixture"],
                entry["plant_at"],
                entry["mode"],
            )
            bare, _t, _why = gate.run_rule(rule, floors=False)
            if not bare:
                raise SystemExit(1)
            target = pathlib.Path(gate.ROOT) / bare[0].path
            lines = target.read_text().splitlines()
            index = bare[0].line - 1
            lines[index] = lines[index] + "  # rule-" + RID + ": the product excuses its own rule here"
            target.write_text("\n".join(lines) + "\n")
            valved, _t2, _why2 = gate.run_rule(rule, floors=False)
            counted = [
                row
                for row in gate.all_overrides()
                if row[0] == RID and row[1] == bare[0].path
            ]
        finally:
            plant.restore()
    print("unvalved:", [str(f) for f in bare])
    print("valved:", [str(f) for f in valved])
    print("counted:", counted)
    rc = 0 if (not valved and len(counted) == 1) else 1
finally:
    for d in made:
        shutil.rmtree(d, ignore_errors=True)
sys.exit(rc)
'
    if [ "$RC" = "0" ]; then
        ok "under a declared namespace a rule-acme-1 valve suppresses the product rule's own finding AND is counted in the standing override census"
    else
        bad "a product's valve did not suppress its own rule end to end, or was suppressed without being counted (see ${OUT})"
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

# THE GRAMMAR SENTENCE IS THE ONLY PLACE A READER LEARNS WHAT EXISTS. An
# argument the engine accepts and the refusal does not name is an argument
# nobody finds by mistyping one, which is how every one of these is found.
case_the_refusal_names_every_argument_the_engine_takes() {
    reader_probe unknown-flag
    CURRENT="case_the_refusal_names_every_argument_the_engine_takes"
    local missing="" arg
    for arg in --selftest --selftest-inputs --diff --fold-map --terse --explain --rules; do
        grep -q -- "$arg" "$OUT" || missing="${missing} ${arg}"
    done
    if [ -z "$missing" ]; then
        ok "the unknown-argument sentence names all seven arguments, --fold-map among them"
    else
        bad "the grammar sentence does not name:${missing} — an argument no refusal mentions"
    fi
}

case_fold_map_with_no_argument_refuses_with_the_grammar() {
    reader_probe fold-map-bare
    CURRENT="case_fold_map_with_no_argument_refuses_with_the_grammar"
    if [ "$RC" = "2" ] &&
        grep -q 'PREVIOUS quality/rules.yaml' "$OUT" &&
        grep -q 'git show <your pre-merge sha>:quality/rules.yaml' "$OUT" &&
        grep -q -- '--fold-map <previous rules.yaml>' "$OUT"; then
        ok "a bare --fold-map is exit 2 carrying the command that produces the file it needs"
    else
        bad "--fold-map with no argument exited ${RC} without the grammar sentence (see ${OUT})"
    fi
}

# THE SHAPE THAT WOULD BE WORST: `--fold-map --rules` reading the next FLAG as
# a path. It would map the tree against a file that is not a rules.yaml and
# print a rename list of nonsense, at exit 0.
case_fold_map_does_not_eat_the_next_flag_as_a_path() {
    reader_probe fold-map-flag-next
    CURRENT="case_fold_map_does_not_eat_the_next_flag_as_a_path"
    if [ "$RC" = "2" ] && grep -q 'PREVIOUS quality/rules.yaml' "$OUT"; then
        ok "--fold-map refuses a following flag rather than reading it as a path"
    else
        bad "--fold-map --rules exited ${RC} — a flag became a filename (see ${OUT})"
    fi
}

# THE STEADY STATE, END TO END. This template mapped against its own
# rules.yaml has nothing to rename and no fixture out of place; a run that
# printed either would be a reader firing on the shipped tree.
case_fold_map_of_this_tree_against_itself_has_nothing_to_do() {
    # The same property, and the same reason, as
    # `apps/core/tests/test_fold_map.py::test_this_template_tree_maps_onto_itself_with_nothing_to_do`.
    template_only "the self-map has content by construction on a product" || return 0
    reader_probe fold-map-self
    CURRENT="case_fold_map_of_this_tree_against_itself_has_nothing_to_do"
    local moved
    moved="$(grep -c ' → ' "$OUT" || true)"
    if [ "$RC" = "0" ] &&
        [ "$moved" = "0" ] &&
        grep -q 'unchanged; nothing to renumber' "$OUT" &&
        grep -q 'every template fixture on this tree is at the path it ships at' "$OUT"; then
        ok "the template maps onto itself: ${RULE_COUNT} rules unchanged, no fixture out of place"
    else
        bad "--fold-map of this tree against itself exited ${RC} with ${moved} renames (see ${OUT})"
    fi
}

# HOTFIX-RULEMAP-2. The grammar sentence is where a reader learns the template
# side can be TYPED — and until it could be, `--fold-map` on a merged tree read
# the merge result as the release and printed a clean map of nothing.
case_the_grammar_names_the_two_argument_fold_map() {
    reader_probe unknown-flag
    CURRENT="case_the_grammar_names_the_two_argument_fold_map"
    if grep -q -- '--fold-map <previous rules.yaml> \[<template rules.yaml>\]' "$OUT" &&
        grep -q -- '--template-tree <dir>' "$OUT"; then
        ok "the grammar names the template side as an argument and --template-tree beside it"
    else
        bad "the grammar sentence does not name the two-argument --fold-map (see ${OUT})"
    fi
}

# A SECOND PATH THAT IS NOT A FILE IS COULD-NOT-LOOK, never an empty template
# side: a map built from half its inputs is a rename list somebody would paste.
case_fold_map_second_argument_that_is_not_a_file_is_exit_2() {
    reader_probe fold-map-second-missing
    CURRENT="case_fold_map_second_argument_that_is_not_a_file_is_exit_2"
    if [ "$RC" = "2" ] &&
        grep -q 'COULD NOT LOOK' "$OUT" &&
        grep -q 'no-such-template.yaml' "$OUT"; then
        ok "a template side nobody can read is exit 2 naming the file"
    else
        bad "--fold-map with an unreadable second path exited ${RC} (see ${OUT})"
    fi
}

# F1 (HOTFIX-RULEMAP-2F). THE GUARD ABOVE FIRED ON THE ONE MODE THE FLAG EXISTS
# FOR: `--template-tree` was reachable from `fold_map_lines()` and DEAD from the
# command line, and the pytest module could not see it because all nineteen of
# its cases call the function and none of them calls `main`. This probe goes
# through `main`s own argv dispatch, which is the only place the defect lived.
case_template_tree_inside_fold_map_is_the_road_it_exists_for() {
    reader_probe fold-map-with-tree
    CURRENT="case_template_tree_inside_fold_map_is_the_road_it_exists_for"
    if [ "$RC" = "0" ] && ! grep -q 'only meaningful' "$OUT"; then
        ok "--fold-map <previous> --template-tree <dir> runs: the flag is reachable from the CLI"
    else
        bad "--fold-map with --template-tree exited ${RC} — the flag is dead from the command line (see ${OUT})"
    fi
}

# A flag that means something to one mode must never be silently ignored in
# another — the same law `--tesre` is refused under.
case_template_tree_without_fold_map_is_exit_2() {
    reader_probe template-tree-orphan
    CURRENT="case_template_tree_without_fold_map_is_exit_2"
    if [ "$RC" = "2" ] && grep -q 'only meaningful with --fold-map' "$OUT"; then
        ok "--template-tree outside --fold-map is refused rather than ignored"
    else
        bad "--template-tree with no --fold-map exited ${RC} (see ${OUT})"
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

case_the_readers_ignore_the_memo() {
    local home
    home="$(memo_home_dir)"
    DJB_RULES_MEMO_DIR="$home" forge "case_the_readers_ignore_the_memo" '
import pathlib
import sys
sys.argv = ["gate"]
from quality import gate

# The four readers return before anything measures, so a warm memo must not
# change one byte of what they print — and must not grow by one file either.
cold = {name: gate._captured(argv) for name, argv in (
    ("explain", ["--explain", "13"]),
    ("rules", ["--rules"]),
    ("inputs", ["--selftest-inputs"]),
    ("fold-map", ["--fold-map", "quality/rules.yaml"]),
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
    ("fold-map", ["--fold-map", "quality/rules.yaml"]),
)}
banked = len(list(home.rglob("*.json")))
for name in cold:
    print("%-8s identical=%s rc=%d" % (name, cold[name] == warm[name], warm[name][0]))
print("entries banked before the warm read: %d" % banked)
sys.exit(0 if cold == warm and all(rc == 0 for rc, _ in warm.values()) and banked else 1)
'
    if [ "$RC" = "0" ]; then
        ok "--explain, --rules, --selftest-inputs and --fold-map print the same bytes over a warm memo as over a cold one"
    else
        bad "a reader's output moved when the memo was warmed, or a reader stopped answering (see ${OUT})"
    fi
}
# --- the id grammar: two namespaces (ADR gate-5) -----------------------------
#
# WHY THESE CASES LIVE IN THIS FILE AND NOT IN ONE OF THEIR OWN. The rung that
# wrote them asked for a drive sentinel of their own in the gate script and
# took the lead's fallback instead: a registration block is a dozen lines in a
# file another rung was editing in the same wave, and an unregistered drive is
# a promise rather than a leg (this file's own header says so, and it shipped
# hand-run for a wave for exactly that reason). They belong beside the FIELD
# cases above either way — the subject is the same one, `consistency()`
# refusing a declaration a reader cannot act on.

case_a_product_rule_under_its_namespace_loads_and_fires() {
    forge "case_a_product_rule_under_its_namespace_loads_and_fires" '
import copy
import shutil
import sys
sys.argv = ["gate"]
from quality import gate

# THE FORGED ID IS ONE THIS TREE DOES NOT OWN. A product whose
# namespace is `acme` numbers its first drawer rule acme-1, and a typed id
# then collided with that rule and with its fixture directory.
RID = next(
    f"acme-{n}"
    for n in range(1, 1000)
    if f"acme-{n}" not in gate.RULES_BY_ID
    and not any(
        (d / f"acme-{n}").exists()
        for d in (gate.CANARY_DIR, gate.NEGATIVE_DIR, gate.LOCAL_CANARY_DIR, gate.LOCAL_NEGATIVE_DIR)
    )
)
rule = copy.deepcopy(gate.RULES_BY_ID["1"])
rule["id"] = RID
# THE HOME IS ASKED FOR, NEVER SPELLED. `fixture_home` is the ONE resolver
# — a rule loaded from the product drawer lives under the drawer, a rule in
# the template document under the template tree — and a drive that typed
# either would be one more place teaching a product where its fixtures go.
# This forged rule is appended to the list the TEMPLATE document declares,
# rather than loaded from the drawer, so the resolver answers the template
# tree for it;
# a real product rule comes out of the drawer, and the case that plants one
# there is case_a_drawer_rule_is_a_rule_end_to_end.
made = []
for kind in ("canary", "negative"):
    dst = gate.fixture_home(kind, RID)
    shutil.copytree(gate.fixture_home(kind, "1"), dst)
    made.append(dst)
gate.RULE_ID_NAMESPACE = "acme"
gate.TEMPLATE_IDS_THROUGH = max(
    int(r["id"]) for r in gate.RULES if gate.is_template_id(str(r["id"]))
)
gate.RULES.append(rule)
gate.RULES_BY_ID[RID] = rule
rc = 1
try:
    gate.broken.clear()
    gate.consistency()
    named = [b for b in gate.broken if RID in b]
    entry = rule["canaries"][0]
    plant = gate.Plant()
    try:
        plant.put(
            gate.fixture_home("canary", RID) / entry["fixture"],
            entry["plant_at"],
            entry["mode"],
        )
        findings, _floors, why = gate.run_rule(rule, floors=False)
    finally:
        plant.restore()
    print("consistency named acme-1:", named)
    print("could-not-look:", repr(why))
    print("findings:", [str(f) for f in findings])
    rc = 0 if (not named and findings and not why) else 1
finally:
    for d in made:
        shutil.rmtree(d, ignore_errors=True)
sys.exit(rc)
'
    if [ "$RC" = "0" ]; then
        ok "acme-1 loaded under rule_id_namespace: acme, planted from the home fixture_home() resolves for it, and fired through the real scope"
    else
        bad "a product rule under a declared namespace did not load, or its canary did not fire through the real scope"
    fi
}

case_a_product_rule_with_an_integer_id_is_refused() {
    forge "case_a_product_rule_with_an_integer_id_is_refused" '
import sys
sys.argv = ["gate"]
from quality import gate
gate.RULE_ID_NAMESPACE = "acme"
gate.TEMPLATE_IDS_THROUGH = 59
problem = gate.id_shape_problem("60")
print(problem)
sys.exit(0 if problem and "acme-<n>" in problem and "60" in problem else 1)
'
    if [ "$RC" = "0" ]; then
        ok "a bare integer above the folded template release is refused, naming acme-<n>"
    else
        bad "a product that typed an integer id was accepted, or the refusal did not name the grammar"
    fi
}

case_a_namespaced_id_on_a_template_tree_is_refused() {
    template_only "the refusal it drives exists only on a tree that claims no namespace" || return 0
    forge "case_a_namespaced_id_on_a_template_tree_is_refused" '
import sys
sys.argv = ["gate"]
from quality import gate
if gate.RULE_ID_NAMESPACE is not None:
    print("this tree declares a namespace; the template case cannot be driven here")
    sys.exit(1)
problem = gate.id_shape_problem("acme-1")
valve = gate.override_re("#").search("# rule-acme-1: a namespace nobody claimed")
print(problem)
print("valve matched:", bool(valve))
sys.exit(0 if problem and "rule_id_namespace" in problem and not valve else 1)
'
    if [ "$RC" = "0" ]; then
        ok "acme-1 is refused on a tree that declares no namespace, and a rule-acme-1 marker is not a valve there"
    else
        bad "a namespaced id, or a valve naming a namespace nobody claimed, was accepted on the template"
    fi
}

case_a_fixture_dir_under_an_unclaimed_namespace_is_exit_2() {
    forge "case_a_fixture_dir_under_an_unclaimed_namespace_is_exit_2" '
import pathlib
import shutil
import sys
import tempfile
sys.argv = ["gate"]
from quality import gate

scratch = pathlib.Path(tempfile.mkdtemp(prefix="djb-nsdir-case-"))
try:
    (scratch / "canary" / "1").mkdir(parents=True)
    (scratch / "canary" / "other-9").mkdir()
    bases = (("canary", scratch / "canary"),)
    loud = gate.fixture_dir_findings(bases, claimed={"1"}, namespace="acme")
    quiet = gate.fixture_dir_findings(bases, claimed={"1", "other-9"}, namespace="acme")
    print("loud:", loud)
    print("quiet:", quiet)
    named = [line for line in loud if "other-9" in line and "other" in line]
    sys.exit(0 if named and not quiet else 1)
finally:
    shutil.rmtree(scratch, ignore_errors=True)
'
    if [ "$RC" = "0" ]; then
        ok "a fixture directory under a namespace the tree never claimed is named; one every rule claims is silent"
    else
        bad "an unclaimed namespaced fixture directory was not named, or a claimed one was reported anyway"
    fi
}

case_a_tree_with_no_product_rules_is_unchanged() {
    template_only "it asserts this tree declares neither namespace key and carries no product rule" || return 0
    forge "case_a_tree_with_no_product_rules_is_unchanged" '
import sys
sys.argv = ["gate"]
from quality import gate
from quality import worlds as W

template, product = W.split_residence_census(W.residence_census(gate.RULES, gate.OPTIONAL_APPS))
shapes = [gate.id_shape_problem(str(r["id"])) for r in gate.RULES]
dirs = gate.fixture_dir_findings()
findings = gate.residence_findings(gate.RULES)
print("namespace:", gate.RULE_ID_NAMESPACE, "through:", gate.TEMPLATE_IDS_THROUGH)
print("residence template/product:", len(template), len(product), "backlog:", gate.RESIDENCE_BACKLOG)
print("id shapes refused:", [s for s in shapes if s])
print("fixture dir findings:", dirs)
print("residence findings:", findings)
ok = (
    gate.RULE_ID_NAMESPACE is None
    and gate.TEMPLATE_IDS_THROUGH is None
    and not product
    and len(template) == gate.RESIDENCE_BACKLOG
    and not [s for s in shapes if s]
    and not dirs
    and not findings
)
sys.exit(0 if ok else 1)
'
    if [ "$RC" = "0" ]; then
        ok "the template tree declares neither key: every id legal, no fixture directory unclaimed, the residence census wholly template and exactly at its recorded backlog"
    else
        bad "the wall moved a number on a tree with no product rules at all (see ${OUT})"
    fi
}

# --- the product's drawer: quality/local/ (P21 EP2, X3) ----------------------
#
# WHY THEY LIVE IN THIS FILE. Same answer D1's namespace cases above give, and
# the same subject: `consistency()` refusing a declaration a reader cannot act
# on, plus the two readers printing whose rule it is. The drawer's END-TO-END
# half — a product rule loaded by a fresh interpreter and fired through the
# real scope — is the last case here, and it plants in a scratch CHECKOUT.
#
# THE FIRST FIVE DRIVE THE SHIPPED FUNCTIONS OVER A TREE THE CASE BUILDS, by
# pointing the module's own `LOCAL_*` paths at a tempdir and calling
# `_read_local()` / `fixture_dir_findings()` / `resolve_check_problem()` /
# `local_ratchet_consistency()` / `local_plant_consistency()`. That is
# `namespace_leg`'s fixture-directory canary's shape (quality/gate.py): the
# victim is created by the probe, never found on the tree.
#
# THE END-TO-END THREE USED TO PLANT IN THE CHECKOUT, AND THE FIRST CONSUMER'S
# BANK IS WHAT MOVED THEM. Each of them opened with "the drawer is the tree's
# own path, so refuse rather than overwrite yours" — which is the right
# instinct and the wrong home: EVERY product that uses the drawer has one, so
# the three cases that prove the drawer reader works could only run where
# there was no drawer, and on the tree that actually uses the seam they exited
# 2. The engine's selftest then read that as `DRAWER BROKEN … the case COULD
# NOT LOOK (exit 2) — it cleared nothing` (`drawers_leg`, quality/gate.py), so
# the seam a product depends on was unproven on exactly the trees that depend
# on it. `apps/core/tests/test_conftest_local.py` had already paid the same
# lesson for the fixtures drawer and says it in its own words: a drawer's
# whole meaning is its ONE conventional path, so the path gets a world of its
# own rather than an assertion about the tree we happen to be standing in.
#
# THE WORLD IS A CLONE, AND THE ENGINE IN IT IS THE ENGINE UNDER TEST.
# `quality/gate.py` derives `ROOT` from its own file — `Path(__file__).resolve()
# .parents[1]` — and honours no override, so "point the engine at another tree"
# means running ANOTHER COPY OF THE ENGINE, which is what a checkout of this
# checkout is. A symlink farm cannot do it (`.resolve()` walks straight back
# here), and `$WORK` cannot (there is no engine in it). Measured on this box: a
# `--shared --no-hardlinks` clone is ~0.3 s and its first `uv run` ~0.8 s.
#
# THE CLONE'S OWN DRAWER IS REMOVED BEFORE ANY CASE RUNS. A product's committed
# `quality/local/` comes along in the clone, and it is the PRODUCT's — not this
# drive's fixture. Removing it from the clone's working tree AND its index is
# what makes "the drawer this case planted" a fact rather than an assumption,
# and it is `test_local_legs.sh`'s `fresh_drawer` argument one file over.
DRAWER_WORLD=""
drawer_world() {
    [ -z "$DRAWER_WORLD" ] || return 0
    local w="${WORK}/drawer-world"
    git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1 ||
        cannot_look "this checkout is not a git checkout — the drawer cases plant in a clone of it"
    # A CLONE MEASURES WHAT IS COMMITTED, AND THE GATE MEASURES THE WORKING
    # TREE. Everywhere else in this drive the two are the same file; here they
    # are not, so a builder with an uncommitted `quality/` edit would watch
    # these three cases pass over the engine they replaced. The rule that makes
    # them agree is already the house's — a `quality/**` rung COMMITS before
    # its gate, because the canary self-test refuses a dirty plant path — so
    # this refuses rather than quietly measuring the old bytes.
    [ -z "$(git -C "$ROOT" status --porcelain -- quality/ 2>/dev/null)" ] ||
        cannot_look "quality/ is dirty in this checkout and these cases run in a CLONE, which carries only what is committed — so they would measure the engine you just replaced. Commit first: a quality/** rung commits before its gate here, for the same reason the canary self-test refuses a dirty plant path."
    git clone --quiet --shared --no-hardlinks "$ROOT" "$w" >/dev/null 2>&1 ||
        cannot_look "could not clone this checkout into ${w} — the drawer cases plant in a clone"
    [ -f "${w}/quality/gate.py" ] && [ -f "${w}/quality/rules.yaml" ] ||
        cannot_look "the clone carries no engine — ${w}/quality/gate.py is what these cases point the drawer at"
    rm -rf "${w}/quality/local"
    git -C "$w" rm -r -q --cached --ignore-unmatch quality/local >/dev/null 2>&1 || true
    [ ! -e "${w}/quality/local" ] ||
        cannot_look "the clone still has a drawer at quality/local/ — these cases plant their own"
    # THE WORLD'S INTERPRETER IS WARMED HERE, ONCE, and that is not tidiness.
    # The FIRST `uv run` in a fresh checkout prints `Creating virtual
    # environment at: .venv` and `Installed N packages` — on stderr, which
    # every capture here folds into stdout — so the absent-drawer negative read
    # those three lines as a difference the drawer had made and failed on its
    # own venv. Measured the first time these cases moved into a clone.
    (cd "$w" && uv run python -c 'pass') >/dev/null 2>&1 ||
        cannot_look "the clone's interpreter would not start — \`uv run\` failed in ${w}"
    DRAWER_WORLD="$w"
}

case_a_drawer_ratchet_adds_to_a_template_class_and_never_replaces_it() {
    forge "case_a_drawer_ratchet_adds_to_a_template_class_and_never_replaces_it" '
import pathlib
import sys
sys.argv = ["gate"]
from quality import gate

# THE DEFECT THIS CASE EXISTS FOR, IN TWO ACTS. A drawer that named a class
# the TEMPLATE already records used to MERGE — `nonconforming: 0` became
# `nonconforming: 99` — and the only thing printed was a note: the template'"'"'s
# own recorded number was ERASED from a file the template never reads. D1
# closed it by refusing the class outright, and that refusal turned out to be
# too wide: rules 50-53 ratchet per FINDING class, so a product with a real
# backlog in `literal` was told its class was not a directory under `apps/`
# and had nowhere to record it at all (HOTFIX-DRAWER-1, from the first
# consumer'"'"'s fold).
#
# SO THE LAW IS ADDITION. A drawer class that a template rule DECLARES is
# accepted and its count is ADDED to the template'"'"'s; the template'"'"'s own number
# survives, which is the half that was ever actually at stake. A class that is
# neither an app on this tree nor one the rule declares is still refused, and
# still does not move the ceiling.
target = next(str(r["id"]) for r in gate.RULES if (r.get("ratchets") or {}))
rule = gate.RULES_BY_ID[target]
before = dict(rule.get("ratchets") or {})
already = sorted(before)[0]
product_app = "zzz_probe_drawer_app"

def merge(classes):
    gate.LOCAL_DOC["ratchets"] = {target: classes}
    rule["ratchets"] = dict(before)
    out = gate._merge_local_ratchets()
    after = dict(rule.get("ratchets") or {})
    gate.LOCAL_DOC.pop("ratchets", None)
    rule["ratchets"] = dict(before)
    return out, after

declared, after_declared = merge({already: 99})
no_app, after_no_app = merge({"acme_nowhere.read": 3})

made = pathlib.Path(gate.ROOT) / "apps" / product_app
made.mkdir(parents=True, exist_ok=False)
try:
    allowed, after_allowed = merge({f"{product_app}.read": 3})
finally:
    made.rmdir()

print("a class the rule declares:", declared)
print("  ceiling after:", after_declared.get(already), "was", before.get(already))
print("no such app:", no_app)
print("a real product app:", allowed, "->", after_allowed.get(f"{product_app}.read"))
sys.exit(0 if (
    not declared
    and after_declared.get(already) == int(before.get(already, 0)) + 99
    and len(no_app) == 1
    and "acme_nowhere" in no_app[0]
    and "TEMPLATE rule" in no_app[0]
    and already in no_app[0]
    and after_no_app == before
    and not allowed
    and after_allowed.get(f"{product_app}.read") == 3
) else 1)
'
    if [ "$RC" = "0" ]; then
        ok "a drawer class naming one a TEMPLATE rule DECLARES is accepted and ADDED to the template's number (never replacing it); a class that is neither an app on this tree nor one the rule declares is refused, names the rule's declared classes, and does not move the ceiling; a real product app's class records"
    else
        bad "the drawer replaced a template rule's recorded number, or refused a class that rule declares, or accepted one that is neither (see ${OUT})"
    fi
}

case_a_drawer_rule_with_no_namespace_is_enforcement_broken() {
    forge "case_a_drawer_rule_with_no_namespace_is_enforcement_broken" '
import pathlib
import sys
import tempfile
sys.argv = ["gate"]
from quality import gate

# WHY. `id_shape_problem` accepts a plain integer when the tree declares no
# namespace, because on a template that IS the only legal shape. A drawer
# carrying rules and no `rule_id_namespace:` therefore loaded `60` as a rule of
# its own — an integer minted from the drawer, colliding with the next template
# release, with every refusal ADR gate-5 exists for switched off.
scratch = pathlib.Path(tempfile.mkdtemp(prefix="djb-drawer-ns-"))
gate.LOCAL_DIR = scratch
gate.LOCAL_RULES_PATH = scratch / "rules.yaml"

def read(text):
    gate.LOCAL_RULES_PATH.write_text(text)
    doc, rules, problems = gate._read_local()
    return rules, problems

body = "rules:\n  - id: \"60\"\n    name: minted-from-the-drawer\n"
nameless, refused = read(body)
named, fine = read("rule_id_namespace: acme\ntemplate_rule_ids_through: 59\n" + body)
empty, quiet = read("rules: []\n")
print("nameless rules loaded:", nameless)
print("refusal:", refused)
print("with a namespace:", len(named), fine)
print("an empty rules list:", empty, quiet)
sys.exit(0 if (
    not nameless
    and len(refused) == 1
    and "rule_id_namespace" in refused[0]
    and "quality/local/rules.yaml" in refused[0]
    and len(named) == 1
    and not fine
    and not empty
    and not quiet
) else 1)
'
    if [ "$RC" = "0" ]; then
        ok "a drawer that carries rules and no rule_id_namespace is refused BY KEY and merges nothing — no integer is ever minted from the drawer; with the key it loads, and an empty rules list is silent"
    else
        bad "the drawer minted a rule under the template's own grammar, or refused a drawer that declared its namespace (see ${OUT})"
    fi
}

case_the_drawers_keys_are_closed_and_the_refusal_names_the_key() {
    forge "case_the_drawers_keys_are_closed_and_the_refusal_names_the_key" '
import pathlib, sys, tempfile
sys.argv = ["gate"]
from quality import gate

scratch = pathlib.Path(tempfile.mkdtemp(prefix="djb-drawer-keys-"))
gate.LOCAL_DIR = scratch
gate.LOCAL_RULES_PATH = scratch / "rules.yaml"

def read(text):
    gate.LOCAL_RULES_PATH.write_text(text)
    return gate._read_local()[2]

legal = read("rule_id_namespace: acme\ntemplate_rule_ids_through: 59\nrules: []\nratchets: {}\n")
strange = read("rule_id_namespace: acme\ntemplate_rule_ids_through: 59\nscope_kinds:\n  js: {}\n")
broken_yaml = read("rules: [ {id: half\n")
not_a_map = read("- one\n- two\n")
gate.LOCAL_RULES_PATH.unlink()
absent = gate._read_local()[2]
print("legal:", legal)
print("strange:", strange)
print("broken_yaml:", broken_yaml)
print("not_a_map:", not_a_map)
print("absent:", absent)
sys.exit(0 if (
    not legal
    and any("scope_kinds" in p and "quality/local/rules.yaml" in p for p in strange)
    and any("could not be read as YAML" in p for p in broken_yaml)
    and any("not a mapping" in p for p in not_a_map)
    and not absent
) else 1)
'
    if [ "$RC" = "0" ]; then
        ok "the drawer takes four keys and no more: an engine key, unparseable bytes and a non-mapping are each refused BY NAME, and an absent drawer is silent"
    else
        bad "the drawer accepted a key that is not its own, or refused a legal one, or read a malformed file as an empty drawer (see ${OUT})"
    fi
}

case_the_namespace_keys_are_refused_in_the_template_file() {
    forge "case_the_namespace_keys_are_refused_in_the_template_file" '
import pathlib, sys, tempfile
sys.argv = ["gate"]
from quality import gate

scratch = pathlib.Path(tempfile.mkdtemp(prefix="djb-drawer-home-"))
gate.LOCAL_DIR = scratch
gate.LOCAL_RULES_PATH = scratch / "rules.yaml"

clean = gate._read_local()[2]
gate._DOC["rule_id_namespace"] = "acme"
gate._DOC["template_rule_ids_through"] = 59
moved = gate._read_local()[2]
del gate._DOC["rule_id_namespace"]
del gate._DOC["template_rule_ids_through"]
print("clean:", clean)
for line in moved:
    print("moved:", line)
names_home = [p for p in moved if "quality/local/rules.yaml" in p and "quality/rules.yaml" in p]
sys.exit(0 if (not clean and len(moved) == 2 and len(names_home) == 2) else 1)
'
    if [ "$RC" = "0" ]; then
        ok "either namespace key left in the template-owned quality/rules.yaml is refused with the line that names its home in the drawer; a tree with neither is silent"
    else
        bad "a namespace key in the template-owned file was accepted, or its refusal did not name the move (see ${OUT})"
    fi
}

case_a_drawer_check_is_a_registry_name_or_a_drawer_runner() {
    forge "case_a_drawer_check_is_a_registry_name_or_a_drawer_runner" '
import pathlib, sys, tempfile
sys.argv = ["gate"]
from quality import gate

scratch = pathlib.Path(tempfile.mkdtemp(prefix="djb-drawer-check-"))
gate.LOCAL_DIR = scratch
gate.LOCAL_RUNNER_DIR = scratch / "runners"
gate.LOCAL_RUNNER_DIR.mkdir(parents=True)

registry_name = sorted(gate.REGISTRY)[0]
rescoped = gate.resolve_check_problem("acme-1", registry_name)
missing = gate.resolve_check_problem("acme-1", "acme_no_widget")
(gate.LOCAL_RUNNER_DIR / "acme_no_widget.py").write_text("print()\n")
runner = gate.resolve_check_problem("acme-1", "acme_no_widget")
print("re-scoped registry name:", rescoped)
print("neither:", missing)
print("drawer runner:", runner)
sys.exit(0 if (
    rescoped is None
    and runner is None
    and missing
    and "REGISTRY" in missing
    and "quality/local/runners/acme_no_widget.py" in missing
    and "checks.py" in missing
) else 1)
'
    if [ "$RC" = "0" ]; then
        ok "one resolver: a registry name re-scoped resolves, a check-v1 runner in the drawer resolves, and neither is a refusal naming BOTH places it looked"
    else
        bad "a check: that resolves to nothing was accepted, or a legal one refused, or the refusal did not name both homes (see ${OUT})"
    fi
}

case_a_mute_drawer_runner_is_enforcement_broken() {
    forge "case_a_mute_drawer_runner_is_enforcement_broken" '
import copy, pathlib, sys, tempfile
sys.argv = ["gate"]
from quality import gate

scratch = pathlib.Path(tempfile.mkdtemp(prefix="djb-drawer-mute-"))
gate.LOCAL_DIR = scratch
gate.LOCAL_RUNNER_DIR = scratch / "runners"
gate.LOCAL_RUNNER_DIR.mkdir(parents=True)
mute = gate.LOCAL_RUNNER_DIR / "acme_mute.py"
mute.write_text("import sys\nsys.exit(0)\n")

rule = copy.deepcopy(gate.RULES_BY_ID["1"])
rule["id"] = "acme-9"
rule["check"] = "acme_mute"
rule.pop("memo", None)
gate.memo_state["bypass"] = True
gate.broken.clear()
findings, _targets, why = gate.run_rule(rule, floors=False)
print("findings:", findings)
print("why:", why)
for line in gate.broken:
    print("broken:", line)
sys.exit(0 if (
    not findings
    and why.startswith(gate.COULD_NOT_LOOK)
    and any("LOCAL RUNNER REFUSED" in b for b in gate.broken)
) else 1)
'
    if [ "$RC" = "0" ]; then
        ok "a drawer runner that prints nothing is could-not-look — REFUSED by name, producing no findings, never a clean tree"
    else
        bad "a mute drawer runner read as zero findings, which is the cheapest way in the world to ship a rule that never fires (see ${OUT})"
    fi
}

case_a_drawer_ratchet_may_not_name_a_platform_app() {
    forge "case_a_drawer_ratchet_may_not_name_a_platform_app" '
import sys
sys.argv = ["gate"]
from quality import gate

platform = gate.PLATFORM_APPS
if platform is None:
    print(gate._PARTITION_PROBLEM)
    sys.exit(1)
platform = sorted(platform)
product = "acme_billing"
victim = platform[0] if platform[0] != "example" else platform[1]
target = next(str(r["id"]) for r in gate.RULES)

def judge(classes):
    gate.LOCAL_DOC["ratchets"] = {target: classes}
    gate.broken.clear()
    gate.notes.clear()
    gate.local_ratchet_consistency()
    out = list(gate.broken)
    gate.LOCAL_DOC.pop("ratchets", None)
    return out

bare = judge({victim: 3})
dotted = judge({f"{victim}.role-value": 3})
allowed = judge({product: 3})
print("bare platform app:", bare)
print("dotted platform class:", dotted)
print("a product app:", allowed)
sys.exit(0 if (
    len(bare) == 1 and victim in bare[0] and "platform_apps" in bare[0]
    and len(dotted) == 1 and victim in dotted[0]
    and not allowed
) else 1)
'
    if [ "$RC" = "0" ]; then
        ok "a drawer ratchet naming a partition.yaml platform app is refused — as <app> and as <app>.<kind> — and one naming a product app is recorded"
    else
        bad "the drawer raised a platform rule's ceiling from a file the template never reads, or refused a product app that belongs there (see ${OUT})"
    fi
}

case_a_drawer_canary_may_not_plant_into_a_platform_app() {
    forge "case_a_drawer_canary_may_not_plant_into_a_platform_app" '
import copy, sys
sys.argv = ["gate"]
from quality import gate

platform = gate.PLATFORM_APPS
if platform is None:
    print(gate._PARTITION_PROBLEM)
    sys.exit(1)
platform = sorted(platform)
victim = platform[0] if platform[0] != "example" else platform[1]

rule = copy.deepcopy(gate.RULES_BY_ID["1"])
rule["id"] = "acme-1"
gate.RULES.append(rule)
gate.LOCAL_RULE_IDS = frozenset({"acme-1"})

def judge(target):
    rule["canaries"] = [{"fixture": "planted.py", "plant_at": target, "mode": "append"}]
    rule["negatives"] = []
    gate.broken.clear()
    gate.local_plant_consistency()
    return list(gate.broken)

into_platform = judge(f"apps/{victim}/models.py")
into_example = judge("apps/example/models.py")
into_product = judge("apps/acme_billing/models.py")
gate.RULES.pop()
print("platform app:", into_platform)
print("apps/example:", into_example)
print("a product app:", into_product)
sys.exit(0 if (
    len(into_platform) == 1 and victim in into_platform[0] and "plant portability" in into_platform[0]
    and not into_example
    and not into_product
) else 1)
'
    if [ "$RC" = "0" ]; then
        ok "a drawer canary planting into a template-owned app is refused BY APP NAME; apps/example and a product app are silent"
    else
        bad "a drawer rule planted a fixture into an app the next fold overwrites, or the refusal named no app (see ${OUT})"
    fi
}

case_the_drawers_key_moves_only_when_the_drawer_does() {
    forge "case_the_drawers_key_moves_only_when_the_drawer_does" '
import copy, sys
sys.argv = ["gate"]
from quality import gate

blobs, trouble = gate.measured_blobs()
if trouble:
    print(trouble)
    sys.exit(1)

def engine():
    gate._ENGINE_DIGEST = None
    return gate._engine_digest(blobs)

base = engine()
same = engine()
# THE EDIT IS DERIVED FROM THE DRAWER THIS TREE HAS: a namespace the
# tree does not already declare, restored to exactly what was there — on the
# template an absent key, on a product its own namespace. A typed "acme" was a
# no-op on a product that IS acme and read as "a drawer edit moved nothing".
MISSING = object()
had = gate.LOCAL_DOC.get("rule_id_namespace", MISSING)
gate.LOCAL_DOC["rule_id_namespace"] = "acme" if had != "acme" else "acmeprobe"
moved = engine()
if had is MISSING:
    gate.LOCAL_DOC.pop("rule_id_namespace")
else:
    gate.LOCAL_DOC["rule_id_namespace"] = had
back = engine()

template = copy.deepcopy(gate.RULES_BY_ID["1"])
local = copy.deepcopy(template)
local["id"] = "acme-1"
one = gate.memo_key(template)[0]
local["statement"] = str(local.get("statement", "")) + " (edited)"
two = gate.memo_key(template)[0]
local_a = gate.memo_key(local)[0]
local["statement"] = str(local["statement"]) + " again"
local_b = gate.memo_key(local)[0]
print("engine base == same:", base == same)
print("engine moved by a non-rule drawer key:", base != moved)
print("engine restored:", base == back)
print("a template rule untouched by another rules text:", one == two)
print("a rules own text moves only its own key:", local_a != local_b)
sys.exit(0 if (base == same and base != moved and base == back and one == two and local_a != local_b) else 1)
'
    if [ "$RC" = "0" ]; then
        ok "the drawer's NON-rule keys fold into the engine digest (every rule re-keys), a no-op moves nothing, and one rule's own text re-keys only that rule (X3.5)"
    else
        bad "a drawer edit either re-keyed nothing or re-keyed everything — the first banks a verdict for a tree nobody measured, the second throws the memo away (see ${OUT})"
    fi
}

# THE DRAWER'S FIXTURES ARE NOT LINTED, AND THE DRAWER'S RUNNERS ARE. A drawer
# canary or negative is deliberately wrong Python exactly as the template's own
# `quality/canary` and `quality/negative` are, so the hook's ruff leg must not
# demand it stop being wrong; a drawer RUNNER is real code the engine loads and
# must stay linted — which is why the exclude names the two fixture roots and
# never the whole drawer. The two commands are the ruff leg's own, run at the
# world's root with `.`: ruff does not apply `extend-exclude` to a path named
# on its command line (without `--force-exclude`), so a case that named the
# fixture would measure a different road from the one the hook takes.
#
# The world is a CLONE, which carries the COMMITTED `pyproject.toml` — so a
# dirty one here is refused for the reason `drawer_world` refuses a dirty
# `quality/`: the case would measure the exclude you did not commit.
ruff_pairs() { # ruff_pairs <file> — one `<path> <code>` line per finding, either output format
    awk '
        /^[^ ].*:[0-9]+:[0-9]+: [A-Z]+[0-9]+/ {
            split($0, a, ":"); c = $2; print a[1], c; next
        }
        /^[A-Z]+[0-9]+ / { code = $1; next }
        /^ *--> / { p = $2; sub(/:[0-9]+:[0-9]+$/, "", p); print p, code; next }
    ' "$1"
}

case_a_drawer_fixture_is_not_linted_and_a_drawer_runner_is() {
    CURRENT=case_a_drawer_fixture_is_not_linted_and_a_drawer_runner_is
    [ -z "$(git -C "$ROOT" status --porcelain -- pyproject.toml 2>/dev/null)" ] ||
        cannot_look "pyproject.toml is dirty in this checkout and this case runs in a CLONE, which carries only what is committed — so it would measure the ruff exclude you did not commit. Commit first."
    drawer_world
    local neg="quality/local/negative/zzz_probe/bad.py"
    local can="quality/local/canary/zzz_probe/bad.py"
    local run="quality/local/runners/zzz_probe.py"
    mkdir -p "${DRAWER_WORLD}/quality/local/negative/zzz_probe" \
        "${DRAWER_WORLD}/quality/local/canary/zzz_probe" "${DRAWER_WORLD}/quality/local/runners"
    printf 'import os\nx=[1,2 ,3]\n' >"${DRAWER_WORLD}/${neg}"
    printf 'import os\nx=[1,2 ,3]\n' >"${DRAWER_WORLD}/${can}"
    printf 'import os\n' >"${DRAWER_WORLD}/${run}"
    N=$((N + 1))
    local check_out="${WORK}/ruffcheck${N}.log" fmt_out="${WORK}/rufffmt${N}.log"
    local check_rc=0 fmt_rc=0
    (cd "$DRAWER_WORLD" && uv run ruff check .) >"$check_out" 2>&1 || check_rc=$?
    (cd "$DRAWER_WORLD" && uv run ruff format --check --quiet .) >"$fmt_out" 2>&1 || fmt_rc=$?
    rm -rf "${DRAWER_WORLD}/quality/local"
    # The check run always has something to say — the runner's F401 — so an
    # empty capture is a run that never started, and it is could-not-look.
    OUT="$check_out"
    RC="$check_rc"
    capture_floor
    local pairs="${WORK}/ruffpairs${N}.log"
    ruff_pairs "$check_out" >"$pairs"
    if grep -F -e "$neg" -e "$can" "$check_out" >/dev/null; then
        bad "ruff check . reports a drawer FIXTURE — quality/local/canary and quality/local/negative are deliberately wrong Python and must be excluded like the template's (exit ${check_rc}); findings: $(grep -F -e "$neg" -e "$can" "$pairs" | tr '\n' ';')"
    else
        ok "ruff check . names neither drawer fixture (${neg}, ${can})"
    fi
    if grep -Fx "${run} F401" "$pairs" >/dev/null; then
        ok "and the drawer RUNNER is still linted — ${run} reports F401 (exit ${check_rc})"
    else
        bad "the drawer runner ${run} no longer reports F401 — a runner is real code and must stay linted; the exclude has swallowed the whole drawer (exit ${check_rc})"
    fi
    OUT="$fmt_out"
    RC="$fmt_rc"
    if [ "$fmt_rc" = 0 ] && [ ! -s "$fmt_out" ]; then
        ok "ruff format --check --quiet . is silent and exit 0 with both fixtures planted"
    else
        bad "ruff format --check --quiet . is exit ${fmt_rc}, want 0 and silent — it names a drawer fixture"
    fi
}

case_a_drawer_rule_is_a_rule_end_to_end() {
    CURRENT=case_a_drawer_rule_is_a_rule_end_to_end
    N=$((N + 1))
    OUT="${WORK}/drawer${N}.log"
    RC=0
    drawer_world
    # THE HIGH-WATER IS DERIVED, NEVER TYPED, and this is the line that pays
    # for it. A literal `59` here was green the day it was written and red the
    # day the template minted rule 60 — `consistency()` correctly refused an
    # integer id above the recorded release, in a case about the DRAWER, for a
    # reason that had nothing to do with the drawer. So the number comes from
    # the ONE reader that already answers it: `namespace_leg()`'s own
    # `integers minted through <n>` line, which is the sentence a product is
    # told to copy. A rule 61 cannot red this case either.
    local through
    through="$(
        (cd "$DRAWER_WORLD" && uv run python -c '
import sys
sys.argv = ["gate"]
from quality import gate
gate.namespace_leg()
') 2>/dev/null | sed -n 's/.*integers minted through \([0-9][0-9]*\).*/\1/p' | tail -1
    )"
    case "$through" in
    "" | *[!0-9]*)
        cannot_look "the template's high-water rule id could not be read from namespace_leg()'s own line — the drawer case cannot record a release it cannot name (got '${through}')"
        ;;
    esac
    mkdir -p "${DRAWER_WORLD}/quality/local/canary/acme-1" "${DRAWER_WORLD}/quality/local/negative/acme-1"
    cp "${DRAWER_WORLD}/quality/canary/1/import_user.py" "${DRAWER_WORLD}/quality/local/canary/acme-1/import_user.py"
    cp "${DRAWER_WORLD}/quality/canary/1/fk_label.py" "${DRAWER_WORLD}/quality/local/canary/acme-1/fk_label.py"
    cp "${DRAWER_WORLD}/quality/negative/1/get_user_model.py" "${DRAWER_WORLD}/quality/local/negative/acme-1/get_user_model.py"
    # The two derived lines are printf'd and the REST is a quoted heredoc: the
    # body carries backticks (the doc anchor) and an unquoted heredoc would
    # run them as commands.
    {
        printf 'rule_id_namespace: acme\ntemplate_rule_ids_through: %s\n' "$through"
        cat <<'DRAWER'
rules:
  - id: acme-1
    name: acme-no-auth-user-import
    enabled: true
    statement: >
      The product's own rule, re-scoping a registry check the template ships.
    check: auth_user_import
    doc: { file: docs/product/architecture.md, contains: "`auth.User` is never imported" }
    valve:
      marker: "<comment> rule-acme-1: <reason>"
      where: on the flagged line itself, or in the contiguous comment block directly above it
    scope: {}
    floors: { files_scanned: 90 }
    does_not_cover: >
      whatever rule 1 does not cover; this entry exists to drive the drawer.
    selftest_floor: { canaries: 2, negatives: 1 }
    canaries:
      - fixture: import_user.py
        plant_at: apps/example/services.py
        mode: append
      - fixture: fk_label.py
        plant_at: apps/example/models.py
        mode: append
    negatives:
      - fixture: get_user_model.py
        plant_at: apps/example/services.py
        mode: append
DRAWER
    } >"${DRAWER_WORLD}/quality/local/rules.yaml"
    (cd "$DRAWER_WORLD" && DJB_RULES_NO_MEMO=1 uv run python -c '
import sys
sys.argv = ["gate"]
from quality import gate

print("namespace:", gate.RULE_ID_NAMESPACE, gate.TEMPLATE_IDS_THROUGH)
print("local ids:", sorted(gate.LOCAL_RULE_IDS))
gate.broken.clear()
gate.consistency()
print("consistency broken:", gate.broken)
rule = gate.RULES_BY_ID["acme-1"]
fired = []
for kind in ("canaries", "negatives"):
    for entry in rule[kind]:
        plant = gate.Plant()
        try:
            plant.put(
                gate.fixture_home(kind, "acme-1") / entry["fixture"],
                entry["plant_at"],
                entry["mode"],
            )
            kept, targets, why = gate.run_rule(rule, floors=True)
        finally:
            plant.restore()
        print(kind, entry["fixture"], "->", [str(f) for f in kept], "targets", targets, "why", repr(why))
        fired.append((kind, bool(kept), targets.get("files_scanned", 0), why))
entry = rule["canaries"][0]
plant = gate.Plant()
try:
    plant.put(gate.fixture_home("canary", "acme-1") / entry["fixture"], entry["plant_at"], entry["mode"])
    target = gate.ROOT / entry["plant_at"]
    target.write_text(
        target.read_text().replace(
            "from django.contrib.auth.models import User",
            "from django.contrib.auth.models import User  # rule-acme-1: the drawer own valve",
        )
    )
    kept, _targets, _why = gate.run_rule(rule, floors=False)
    counted = [row for row in gate.all_overrides() if row[0] == "acme-1"]
finally:
    plant.restore()
print("valve suppressed:", not kept, "counted:", counted)
canaries = [f for f in fired if f[0] == "canaries"]
negatives = [f for f in fired if f[0] == "negatives"]
ok = (
    gate.RULE_ID_NAMESPACE == "acme"
    and sorted(gate.LOCAL_RULE_IDS) == ["acme-1"]
    and not gate.broken
    and len(canaries) == 2
    and all(hit and scanned >= 90 and not why for _k, hit, scanned, why in canaries)
    and all(not hit for _k, hit, _s, _w in negatives)
    and not kept
    and len(counted) == 1
)
sys.exit(0 if ok else 1)
') >"$OUT" 2>&1 || RC=$?
    local tagged=1
    (cd "$DRAWER_WORLD" && uv run python -m quality.gate --rules) >>"$OUT" 2>&1 || true
    grep -qE '^acme-1  acme-no-auth-user-import .*\[local\]$' "$OUT" || tagged=0
    (cd "$DRAWER_WORLD" && uv run python -m quality.gate --explain acme-1) >>"$OUT" 2>&1 || true
    grep -qF 'home: quality/local/rules.yaml' "$OUT" || tagged=0
    rm -rf "${DRAWER_WORLD}/quality/local"
    capture_floor
    if [ "$RC" = "0" ] && [ "$tagged" = "1" ]; then
        ok "a drawer rule loaded from quality/local/rules.yaml, passed consistency, fired BOTH canaries through the real scope over a bound floor, kept its negative silent, was suppressed and COUNTED by its own valve, and is tagged [local] by both readers"
    else
        bad "a product rule in the drawer is not a rule end to end (rc=${RC}, tagged=${tagged}) — see ${OUT}"
    fi
}

# THE FIFTH DRAWER KEY, driven end to end. `case_a_drawer_rule_is_a_rule_end_to_end`
# above proves a product RULE is a rule; this proves a product's rule may be
# ABOUT the product's own files. The template declares two scope kinds — `py`
# (apps, config) and `js` (frontend) — so before `scope_kinds:` was the
# drawer's fifth key a rule whose subject was a ledger, a doc or a
# `.env.example` had no kind to name and `check_v1._refuse_outside_roots`
# refused its runner's every finding. The first consumer of v2.1.2 met exactly
# that on four rules, and the refusal it pasted is the one this case drives
# from both sides: SILENT with the kind declared, and REFUSED WITH THE REMEDY
# when the same rule is pointed back at a template kind.
case_a_product_scope_kind_points_a_drawer_rule_at_its_own_files() {
    CURRENT=case_a_product_scope_kind_points_a_drawer_rule_at_its_own_files
    N=$((N + 1))
    OUT="${WORK}/drawerkind${N}.log"
    RC=0
    drawer_world
    # THE PLANT SITES ARE TWO FILES THIS TREE ALREADY HAS, appended to and
    # restored in a `finally` — the idiom `case_a_drawer_rule_is_a_rule_end_to_end`
    # uses one file over. A plant that CREATED a new `docs/…md` would be a
    # docs pointer spelled in this drive and absent from the tree, which the
    # `dangling-docs` leg correctly reds; widening that leg's one exemption so
    # a drive could name a file it deletes would be the census bending for its
    # own driver.
    [ -f "${DRAWER_WORLD}/docs/product/architecture.md" ] ||
        cannot_look "the clone carries no docs/product/architecture.md — the drawer kind's plant has no home"
    # DERIVED, NEVER TYPED, for the reason the case above states in full.
    local through
    through="$(
        (cd "$DRAWER_WORLD" && uv run python -c '
import sys
sys.argv = ["gate"]
from quality import gate
gate.namespace_leg()
') 2>/dev/null | sed -n 's/.*integers minted through \([0-9][0-9]*\).*/\1/p' | tail -1
    )"
    case "$through" in
    "" | *[!0-9]*)
        cannot_look "the template's high-water rule id could not be read from namespace_leg()'s own line (got '${through}')"
        ;;
    esac
    mkdir -p "${DRAWER_WORLD}/quality/local/canary/acme-2" \
        "${DRAWER_WORLD}/quality/local/negative/acme-2" "${DRAWER_WORLD}/quality/local/runners"
    cat <<'RUNNER' >"${DRAWER_WORLD}/quality/local/runners/ledger_probe.py"
"""A product's own rule about its LEDGERS — the drive's product-side runner.

THE SUBJECT IS THE RUNNER'S AND THE ROOTS ARE THE RULE'S, which is the whole
shape the fifth drawer key exists for. This instrument is about `docs/`
wherever it is pointed — exactly like the four in-process checks the first
consumer moved into the drawer — and the engine holds it to the roots its
kind declares. Under a kind rooted at `docs` it answers; under the template's
`py` kind every finding it reports is outside the roots and the whole run is
refused, which is the refusal the case drives from both sides.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

MARK = "UNFINISHED" + "-LEDGER-ROW"
SUBJECT = Path("docs")


def main(argv: list[str]) -> int:
    scanned = 0
    findings: list[dict] = []
    for path in sorted(SUBJECT.rglob("*.md")) if SUBJECT.is_dir() else []:
        if not path.is_file():
            continue
        scanned += 1
        for number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if MARK in line:
                findings.append(
                    {
                        "path": str(path),
                        "line": number,
                        "msg": "a ledger row that names no artifact",
                        "klass": "unfinished",
                    }
                )
    json.dump(
        {"protocol": "check-v1", "targets": {"files_scanned": scanned}, "findings": findings},
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
RUNNER
    # The marker is assembled rather than spelled, for the reason every plant in
    # this drive assembles one: a literal here is a string a later census over
    # this file would count as a real occurrence.
    printf 'A ledger row: UNFINISHED%sLEDGER-ROW\n' "-" >"${DRAWER_WORLD}/quality/local/canary/acme-2/stale_row.md"
    printf '# A plan\n\n- the second form, a row inside a list: UNFINISHED%sLEDGER-ROW\n' "-" >"${DRAWER_WORLD}/quality/local/canary/acme-2/stale_row_in_a_list.md"
    printf 'A ledger row, with its artifact: apps/example/models.py\n' >"${DRAWER_WORLD}/quality/local/negative/acme-2/named_row.md"
    {
        printf 'rule_id_namespace: acme\ntemplate_rule_ids_through: %s\n' "$through"
        cat <<'DRAWER'
scope_kinds:
  ledgers:
    # A DIRECTORY AND A FILE, because the seam claims both and a file root is
    # the one three readers had to be taught (V-HD1 HIGH-1). `comment: "#"` is
    # the token a product really picks for markdown, and it is what turned
    # every `# rule-13:` shaped line of prose in this repository into an
    # override of a TEMPLATE rule until the attribution was narrowed.
    roots: [docs, .env.example]
    suffixes: [".md"]
    comment: "#"
rules:
  - id: acme-2
    name: acme-every-ledger-row-names-its-artifact
    enabled: true
    kind: ledgers
    statement: >
      The product's own rule about the product's own ledgers. Every row names
      the artifact that proves it.
    check: ledger_probe
    doc: { file: docs/product/architecture.md, contains: "house rules" }
    valve:
      marker: "<comment> rule-acme-2: <reason>"
      where: on the flagged line itself, or in the contiguous comment block directly above it
    scope: {}
    floors: { files_scanned: 10 }
    does_not_cover: >
      a row whose artifact is named and does not exist; the probe reads the row,
      never the tree it points at.
    selftest_floor: { canaries: 2, negatives: 1 }
    canaries:
      - fixture: stale_row.md
        plant_at: docs/product/architecture.md
        mode: append
      - fixture: stale_row_in_a_list.md
        plant_at: docs/product/architecture.md
        mode: append
    negatives:
      - fixture: named_row.md
        plant_at: docs/product/architecture.md
        mode: append
DRAWER
    } >"${DRAWER_WORLD}/quality/local/rules.yaml"
    (cd "$DRAWER_WORLD" && DJB_RULES_NO_MEMO=1 uv run python -c '
import sys
sys.argv = ["gate"]
from quality import gate

print("kinds:", sorted(gate.SCOPE_KINDS))
print("local kinds:", sorted(gate.LOCAL_SCOPE_KINDS))
gate.broken.clear()
gate.consistency()
print("consistency broken:", gate.broken)
clean = not gate.broken

rule = gate.RULES_BY_ID["acme-2"]
fired = []
for kind in ("canaries", "negatives"):
    for entry in rule[kind]:
        plant = gate.Plant()
        try:
            plant.put(
                gate.fixture_home(kind, "acme-2") / entry["fixture"],
                entry["plant_at"],
                entry["mode"],
            )
            kept, targets, why = gate.run_rule(rule, floors=True)
        finally:
            plant.restore()
        paths = sorted({f.path for f in kept})
        print(kind, entry["fixture"], "->", paths, "targets", targets, "why", repr(why))
        fired.append((kind, kept, targets.get("files_scanned", 0), why))

canaries = [row for row in fired if row[0] == "canaries"]
negative = [row for row in fired if row[0] == "negatives"][0]
in_docs = all(
    row[1] and all(f.path.startswith("docs/") for f in row[1]) for row in canaries
)

# THE SAME RULE, POINTED BACK AT A TEMPLATE KIND. This is the refusal the
# consumer pasted, and the half that proves the remedy is reachable: a rule
# about docs/ whose kind is `py` is refused, and the refusal now says which
# declaration widens the roots and which FILE it is written in.
rule["kind"] = "py"
plant = gate.Plant()
try:
    entry = rule["canaries"][0]
    plant.put(gate.fixture_home("canary", "acme-2") / entry["fixture"], entry["plant_at"], entry["mode"])
    gate.broken.clear()
    _kept, _targets, why = gate.run_rule(rule, floors=False)
finally:
    plant.restore()
    rule["kind"] = "ledgers"
print("refusal:", why)

# HIGH-2 · THE WALK IS THE UNION, THE ATTRIBUTION IS ONE RULE'"'"'S OWN ROOTS.
# With `comment: "#"` and a root of `docs`, every `# rule-<id>:` shaped line of
# prose in this repository entered the standing-override census; two carried
# "reasons" shorter than MIN_REASON and became findings recorded against
# TEMPLATE rules 13 and 16. A product kind must not be able to red a rule it
# does not own.
target = gate.ROOT / "docs" / "product" / "architecture.md"
kept_text = target.read_text()
try:
    target.write_text(
        kept_text
        + "\n# rule-13: x\n# rule-acme-2: the product own valve on its own ledger rule\n"
    )
    rows = gate.all_overrides()
finally:
    target.write_text(kept_text)
here = "docs/product/architecture.md"
template_rows = [r for r in rows if r[0] == "13" and r[1] == here]
product_rows = [r for r in rows if r[0] == "acme-2" and r[1] == here]
print("template rule rows in docs/:", template_rows)
print("product rule rows in docs/:", product_rows)
attribution = not template_rows and len(product_rows) == 1
refused = (
    "finding-outside-roots" in why
    and "scope_kinds:" in why
    and "quality/local/rules.yaml" in why
)

ok = (
    "ledgers" in gate.SCOPE_KINDS
    and sorted(gate.LOCAL_SCOPE_KINDS) == ["ledgers"]
    and clean
    and len(canaries) == 2
    and in_docs
    and all(row[2] >= 10 and not row[3] for row in canaries)
    and not negative[1]
    and refused
    and attribution
)
sys.exit(0 if ok else 1)
') >"$OUT" 2>&1 || RC=$?
    local tagged=1
    (cd "$DRAWER_WORLD" && uv run python -m quality.gate --explain acme-2) >>"$OUT" 2>&1 || true
    grep -qF 'home: quality/local/rules.yaml' "$OUT" || tagged=0
    # HIGH-1 · THE FOURTH READER, run as the CLI the gate runs (check.sh's
    # selftest leg). A file root's walk is itself: a prefix test spelled
    # `root + "/"` counted 0 for the file root and this reader refused a root
    # that was exactly where it said it was — exit 2 at the bank, on the
    # consumer's own case, while the release notes said "a directory or file".
    local inputs="${WORK}/drawerkind-inputs${N}.txt"
    if (cd "$DRAWER_WORLD" && uv run python -m quality.gate --selftest-inputs) >"$inputs" 2>&1; then
        grep -qx '.env.example' "$inputs" || tagged=0
    else
        tagged=0
    fi
    cat "$inputs" >>"$OUT"
    rm -rf "${DRAWER_WORLD}/quality/local"
    capture_floor
    if [ "$RC" = "0" ] && [ "$tagged" = "1" ]; then
        ok "a product's own scope kind joins SCOPE_KINDS (a directory root AND a file root), points a drawer rule at docs/, fires its canary THERE over a bound floor, keeps its negative silent, is the ONLY rule a valve under docs/ is attributed to, and carries its file root through --selftest-inputs — and the same rule under a template kind is refused with the remedy naming \`scope_kinds:\` in the drawer"
    else
        bad "a product rule cannot be about the product's own files (rc=${RC}, tagged=${tagged}) — see ${OUT}"
    fi
}


case_no_drawer_is_byte_identical() {
    CURRENT=case_no_drawer_is_byte_identical
    N=$((N + 1))
    OUT="${WORK}/nodrawer${N}.log"
    RC=0
    drawer_world
    local before="${WORK}/nodrawer-before.txt" after="${WORK}/nodrawer-after.txt"
    (cd "$DRAWER_WORLD" && uv run python -m quality.gate --rules) >"$before" 2>&1 || RC=$?
    mkdir -p "${DRAWER_WORLD}/quality/local"
    (cd "$DRAWER_WORLD" && uv run python -m quality.gate --rules) >"$after" 2>&1 || RC=$?
    rmdir "${DRAWER_WORLD}/quality/local"
    cp "$before" "$OUT"
    capture_floor
    if [ "$RC" != "0" ]; then
        bad "the listing did not answer on a tree with no drawer (exit ${RC})"
        return
    fi
    if ! cmp -s "$before" "$after"; then
        bad "an EMPTY quality/local/ moved the listing — the drawer must cost a tree that has none exactly nothing: $(diff "$before" "$after" | head -5 | tr '\n' '|')"
        return
    fi
    ok "with no drawer, and with an empty one, \`--rules\` is byte-identical — the negative is the cmp, not a sentence"
}

# --- the TREE CENSUS (C0's `census:` seam) -----------------------------------
#
# Everything the readers above assert is a rule's DECLARATION, and all of it is
# true of an empty checkout. `census:` is the other half: a dotted path to a
# callable `--explain <id>` runs over THIS TREE, so the reader can answer "and
# what does that mean here, right now?" The four cases are the four answers —
# it prints, it is absent and changes nothing, it does not resolve, it stumbles
# — plus rule 59's real one, which is the per-app `EVENT_KINDS` block a product
# folding the template otherwise reassembles by hand out of a dozen findings.
#
# ONE PROCESS, like `readers_once` and for the same reason: five captures of
# one parse are five interpreter starts otherwise. The probe module is written
# into this drive's own scratch directory and reached through `sys.path`, so
# nothing is planted in the checkout for the three synthetic cases; the fifth
# plants rule 59's OWN canary through `gate.Plant` and restores it in a
# `finally`, which is `case_a_product_rule_under_its_namespace_loads_and_fires`'
# idiom one file over.
CENSUS_DIR="${WORK}/census"
CENSUS_READY=""
census_probes_once() {
    [ -z "$CENSUS_READY" ] || return 0
    mkdir -p "$CENSUS_DIR" "${WORK}/censuspath"
    cat >"${WORK}/censuspath/zzz_census_probe.py" <<'PROBE'
"""A census that answers, and one that stumbles. Never on the checkout."""


def two_lines(root, rule):
    return ["the first line this tree offered", "the second line this tree offered"]


def boom(root, rule):
    raise RuntimeError("this tree would not answer")
PROBE
    CURRENT="the census probes, captured in one process"
    N=$((N + 1))
    OUT="${WORK}/census${N}.log"
    RC=0
    DJB_CENSUS_DIR="$CENSUS_DIR" DJB_CENSUS_PATH="${WORK}/censuspath" \
        uv run python - >"$OUT" 2>&1 <<'PY' || RC=$?
import copy
import os
import pathlib
import sys

sys.argv = ["gate"]
sys.path.insert(0, os.environ["DJB_CENSUS_PATH"])
from quality import gate

out = pathlib.Path(os.environ["DJB_CENSUS_DIR"])


def keep(name, rc, text):
    (out / (name + ".log")).write_text(text, encoding="utf-8")
    (out / (name + ".rc")).write_text(str(rc), encoding="utf-8")


# The victim is a copy registered under its own id, so the engine's real
# `explain` reads it exactly as it reads every other rule.
plain = copy.deepcopy(gate.RULES_BY_ID["13"])
plain.pop("census", None)
gate.RULES_BY_ID["13"] = plain
rc_plain, text_plain = gate._captured(["--explain", "13"])
keep("no-census", rc_plain, text_plain)

with_census = copy.deepcopy(plain)
with_census["census"] = "zzz_census_probe.two_lines"
gate.RULES_BY_ID["13"] = with_census
keep("with-census", *gate._captured(["--explain", "13"]))

# THE BYTE-IDENTICAL HALF, computed where both captures are in hand: cut the
# census block — the blank line, the header, its indented lines — out of the
# capture that has one, and what is left must be the other capture's bytes. A
# rule that declares no census must explain exactly as it did before the seam
# existed, and "exactly" is a diff, not an eyeball.
lines = (out / "with-census.log").read_text(encoding="utf-8").splitlines(keepends=True)
head = [i for i, line in enumerate(lines) if line.rstrip("\n") == "census (this tree):"]
if len(head) != 1:
    keep("stripped-matches-plain", 1, f"expected one census header, found {len(head)}\n")
else:
    start = head[0] - 1  # the blank line the block opens with
    end = head[0] + 1
    while end < len(lines) and lines[end].startswith("  "):
        end += 1
    stripped = "".join(lines[:start] + lines[end:])
    same = stripped == text_plain
    keep(
        "stripped-matches-plain",
        0 if same else 1,
        "byte-identical\n"
        if same
        else "DIFFERS\n--- with the census block cut out\n"
        + stripped
        + "\n--- the same rule declaring no census\n"
        + text_plain,
    )

unresolvable = copy.deepcopy(plain)
unresolvable["census"] = "zzz_census_probe.no_such_callable"
gate.RULES_BY_ID["13"] = unresolvable
keep("unresolvable", *gate._captured(["--explain", "13"]))

raising = copy.deepcopy(plain)
raising["census"] = "zzz_census_probe.boom"
gate.RULES_BY_ID["13"] = raising
keep("raises", *gate._captured(["--explain", "13"]))

# Rule 59's real census, over a tree carrying rule 59's own undecided-noun
# canary. The plant is the shipped fixture at the shipped site, and it is
# restored whatever happens below.
rule59 = gate.RULES_BY_ID["59"]
entry = rule59["canaries"][3]
plant = gate.Plant()
try:
    plant.put(gate.CANARY_DIR / "59" / entry["fixture"], entry["plant_at"], entry["mode"])
    keep("rule59-planted", *gate._captured(["--explain", "59"]))
finally:
    plant.restore()
from quality import checks as _checks


def _reads_agreement(gate, rule54):
    """(agrees, silent rows, one readable line) for the tree as it stands now.

    The census reads clause (d)'s whole population and says how many of them
    ask nothing; the rule raises a finding for exactly those, classed
    `<app>.read`. Two numbers, ONE walker — a census that had drifted from the
    rule would be a census describing a different tree, which is what the
    one-walker discipline exists to make impossible. The header's population
    count is asserted against the rows actually printed, so a census that
    stopped printing rows cannot pass by counting none of them either.
    """
    result = _checks.authz_vocabulary_shape(gate.ROOT, rule54)
    findings = [f for f in result.findings if f.klass.endswith(".read")]
    lines = _checks.reads_census(gate.ROOT, rule54)
    header = lines[0] if lines else ""
    silent = [line for line in lines[1:] if "asks NOTHING" in line]
    rows = max(len(lines) - 2, 0)
    agrees = (
        f"{len(findings)} ask nothing" in header
        and len(silent) == len(findings)
        and rows > 0
        and f"{rows} public get_/list_ selector(s) over a kind" in header
    )
    return (
        agrees,
        len(silent),
        f"{len(findings)} read-class finding(s), {len(silent)} silent census row(s), "
        f"{rows} row(s) in all · {header}",
    )


# Rule 54's census, over a tree carrying rule 54's OWN clause-(d)
# canary: a public `list_` returning rows of a kind and asking nothing. The
# census has to print that selector WITH the line that opens it, because the
# product meeting the hard read rule at its own door is holding exactly this
# shape and CHANGELOG item 5 names no door.
rule54 = gate.RULES_BY_ID["54"]
entry54 = next(c for c in rule54["canaries"] if c["fixture"] == "list_gadgets_without_require.py")
plant54 = gate.Plant()
try:
    for extra in entry54.get("extra_files", []):
        plant54.put(gate.CANARY_DIR / "54" / extra["fixture"], extra["plant_at"], extra["mode"])
    plant54.put(gate.CANARY_DIR / "54" / entry54["fixture"], entry54["plant_at"], entry54["mode"])
    keep("rule54-planted", *gate._captured(["--explain", "54"]))
    _planted_agreement = _reads_agreement(gate, rule54)
finally:
    plant54.restore()

# AND THE CENSUS AGREES WITH THE RULE, on this tree, unplanted. The census
# reads clause (d)'s whole population and says how many of them ask nothing;
# the rule raises a finding for exactly those, classed `<app>.read`. Two
# numbers, ONE walker: a census that drifted from the rule would be a census
# describing a different tree, which is what the one-walker discipline exists
# to make impossible. Asserted rather than assumed, because the template's own
# answer is ZERO and a census that had stopped looking would print zero too —
# so the header's population count is asserted against the rows it printed.
_bare_agreement = _reads_agreement(gate, rule54)
# BOTH TREES, and the planted one is what makes this able to fail. The
# template's own answer is ZERO silent reads, so an unplanted `0 == 0` is
# satisfied by a census that had stopped looking altogether — the masking shape
# rung-execution §2 names. The planted tree has exactly one, so the pair is
# `0 == 0` and `1 == 1`, and a census that lost the class fails the second.
_agrees = _bare_agreement[0] and _planted_agreement[0] and _planted_agreement[1] == 1
keep(
    "rule54-agrees",
    0 if _agrees else 1,
    "unplanted: " + _bare_agreement[2] + "\nplanted:   " + _planted_agreement[2] + "\n"
    + ("agrees on both trees\n" if _agrees else "DISAGREES — see the two lines above\n"),
)
print("captured 7 census probes and the strip comparison")
PY
    [ "$RC" = "0" ] ||
        cannot_look "the census capture exited ${RC} — every census case below would read a capture that was never taken (see ${OUT})"
    CENSUS_READY=1
}

# census_probe <name> — one captured census probe, in `$OUT`/`$RC`.
census_probe() {
    local name=$1 base
    census_probes_once
    base="${CENSUS_DIR}/${name}"
    [ -f "${base}.rc" ] ||
        cannot_look "the census capture left no status for ${name} — the fold above did not run every probe it declares"
    OUT="${base}.log"
    RC="$(cat "${base}.rc")"
    capture_floor
}

case_a_declared_census_prints_its_lines_under_explain() {
    census_probe with-census
    CURRENT="case_a_declared_census_prints_its_lines_under_explain"
    if [ "$RC" != "0" ]; then
        bad "--explain on a rule with a working census exited ${RC}"
        return
    fi
    if grep -q '^census (this tree):$' "$OUT" &&
        grep -q '^  the first line this tree offered$' "$OUT" &&
        grep -q '^  the second line this tree offered$' "$OUT" &&
        grep -q '^negatives:$' "$OUT"; then
        ok "the callable's lines print under 'census (this tree):', after the rule's own declaration"
    else
        bad "a declared census printed no block, or lost the declaration above it"
    fi
}

case_a_rule_with_no_census_explains_byte_identically() {
    census_probe stripped-matches-plain
    CURRENT="case_a_rule_with_no_census_explains_byte_identically"
    if [ "$RC" = "0" ]; then
        ok "cut the census block out and the capture is the no-census capture's bytes — the seam adds nothing to a rule that declares none"
    else
        bad "a rule declaring no census no longer explains as it did (see ${OUT})"
    fi
}

case_a_census_that_does_not_resolve_is_exit_2_naming_it() {
    census_probe unresolvable
    CURRENT="case_a_census_that_does_not_resolve_is_exit_2_naming_it"
    if [ "$RC" = "2" ] && grep -q 'zzz_census_probe.no_such_callable' "$OUT" &&
        grep -q 'does not resolve' "$OUT"; then
        ok "a census pointing at a callable that is not there is enforcement broken, and the refusal names the dotted path"
    else
        bad "an unresolvable census exited ${RC} without naming itself — a declaration nobody can follow read as a pass"
    fi
}

case_a_census_that_raises_is_a_could_not_look_line() {
    census_probe raises
    CURRENT="case_a_census_that_raises_is_a_could_not_look_line"
    if grep -q '^  could not look: zzz_census_probe.boom raised RuntimeError: this tree would not answer$' "$OUT" &&
        grep -q '^selftest_floor:' "$OUT" && grep -q '^statement:$' "$OUT"; then
        ok "a stumbling census says so on its own line and the whole declaration still prints"
    else
        bad "a raising census took the explanation down with it, or said nothing about why (rc ${RC})"
    fi
}

case_rule_59s_census_is_the_per_app_draft_block() {
    census_probe rule59-planted
    CURRENT="case_rule_59s_census_is_the_per_app_draft_block"
    if [ "$RC" != "0" ]; then
        bad "--explain 59 over the planted canary exited ${RC}"
        return
    fi
    if grep -q '^census (this tree):$' "$OUT" &&
        grep -q '^  apps/example/events.py — 1 undecided noun; paste into EVENT_KINDS:$' "$OUT" &&
        grep -q '^      "gizmo": ' "$OUT"; then
        ok "rule 59's census groups every undecided noun under its app with the EVENT_KINDS line to paste"
    else
        bad "rule 59's census did not print the per-app draft block for the planted undecided noun"
    fi
}

case_rule_54s_census_lists_a_silent_read_with_the_line_that_opens_it() {
    census_probe rule54-planted
    CURRENT="case_rule_54s_census_lists_a_silent_read_with_the_line_that_opens_it"
    if [ "$RC" != "0" ]; then
        bad "--explain 54 over the planted silent read exited ${RC}"
        return
    fi
    # THREE SHAPES, ONE CAPTURE. The planted canary is the silent read; the
    # tree it was planted into supplies the other two, which is the point of a
    # census over THIS tree rather than a fixture: a product reading its own
    # 403 needs the asking row with its DOOR (the consumer's case, verbatim —
    # `GET /api/v1/memberships/mine/` is `list_memberships` behind
    # `apps/core/api/routes.py`), and the already-open row so it can tell a
    # read it must grant from a read it never had to.
    if ! grep -q '^census (this tree):$' "$OUT"; then
        bad "rule 54's census printed no block at all"
        return
    fi
    if grep -q '^  apps/zzz_canary/selectors.py:[0-9]* list_gadgets -> Gadget (gadget); asks NOTHING' "$OUT" &&
        grep -q 'opening: take `actor: Actor` and call require(actor, "gadget.read"' "$OUT"; then
        ok "rule 54's census lists a read that asks nothing with the require() line that opens it"
    else
        bad "rule 54's census did not list the planted silent read, or listed it with no opening"
    fi
    if grep -q 'list_memberships -> Membership (membership); asks membership.read at the acting hat' "$OUT" &&
        grep -q 'list_memberships .*door: apps/core/api/routes.py (route), apps/core/mcp.py (tool)' "$OUT"; then
        ok "an asking read names the key, the node it resolves at and EVERY door that reaches it — the consumer's own 403, with its two doors"
    else
        bad "the census lost the asking row, the node it resolves at, or the doors that reach it"
    fi
    if grep -qc 'asks nothing — `# read-open:' "$OUT" && grep -q 'opening: already open' "$OUT"; then
        ok "a read that is deliberately open is listed too, saying so, so a product can tell a read it must grant from one it never had"
    else
        bad "the census did not list the reads that are open by `# read-open:`"
    fi
}

case_rule_54s_census_agrees_with_the_rules_own_read_findings() {
    census_probe rule54-agrees
    CURRENT="case_rule_54s_census_agrees_with_the_rules_own_read_findings"
    if [ "$RC" = "0" ]; then
        ok "on this tree AND on the planted one the census's silent rows are exactly rule 54's read-class findings, and its header counts the rows it printed"
    else
        bad "the census and rule 54 disagree about this tree (see ${OUT})"
    fi
}

run_case case_every_rule_declares_a_valve
run_case case_a_product_rule_under_its_namespace_loads_and_fires
run_case case_a_product_rule_with_an_integer_id_is_refused
run_case case_a_namespaced_id_on_a_template_tree_is_refused
run_case case_a_fixture_dir_under_an_unclaimed_namespace_is_exit_2
run_case case_a_tree_with_no_product_rules_is_unchanged
run_case case_the_drawers_keys_are_closed_and_the_refusal_names_the_key
run_case case_the_namespace_keys_are_refused_in_the_template_file
run_case case_a_drawer_check_is_a_registry_name_or_a_drawer_runner
run_case case_a_mute_drawer_runner_is_enforcement_broken
run_case case_a_drawer_ratchet_may_not_name_a_platform_app
run_case case_a_drawer_ratchet_adds_to_a_template_class_and_never_replaces_it
run_case case_a_drawer_rule_with_no_namespace_is_enforcement_broken
run_case case_a_drawer_canary_may_not_plant_into_a_platform_app
run_case case_the_drawers_key_moves_only_when_the_drawer_does
run_case case_a_drawer_rule_is_a_rule_end_to_end
run_case case_a_product_scope_kind_points_a_drawer_rule_at_its_own_files
run_case case_a_drawer_fixture_is_not_linted_and_a_drawer_runner_is
run_case case_no_drawer_is_byte_identical
run_case case_a_rule_with_no_valve_is_enforcement_broken
run_case case_a_none_valve_with_no_sentence_is_enforcement_broken
run_case case_a_valve_declaring_both_forms_is_enforcement_broken
run_case case_a_red_carries_its_trailer_once_after_its_findings
run_case case_the_trailers_valve_is_the_marker_a_reader_can_paste
run_case case_the_budget_trailer_names_the_budget_file
run_case case_a_rule_whose_trailer_lost_a_key_is_enforcement_broken
run_case case_a_frontend_finding_prints_the_slash_valve_token
run_case case_the_plant_refuses_a_path_that_already_exists
run_case case_the_drive_creates_no_frontend_tree_on_a_tree_that_has_none
run_case case_a_rule_with_findings_in_two_kinds_prints_both_valve_tokens
run_case case_the_trailer_and_cli_censuses_print_and_are_asserted
run_case case_a_function_less_services_module_is_not_a_budget_subject
run_case case_one_function_is_a_subject_and_still_reds_without_a_ceiling
run_case case_a_new_function_subject_prints_its_paste_line
run_case case_explain_prints_the_rules_own_declaration
run_case case_explain_of_an_unknown_id_is_exit_2_naming_the_listing
run_case case_the_listing_is_the_same_under_both_names
run_case case_an_unknown_flag_is_still_exit_2
run_case case_the_refusal_names_every_argument_the_engine_takes
run_case case_fold_map_with_no_argument_refuses_with_the_grammar
run_case case_fold_map_does_not_eat_the_next_flag_as_a_path
run_case case_fold_map_of_this_tree_against_itself_has_nothing_to_do
run_case case_the_grammar_names_the_two_argument_fold_map
run_case case_fold_map_second_argument_that_is_not_a_file_is_exit_2
run_case case_template_tree_without_fold_map_is_exit_2
run_case case_template_tree_inside_fold_map_is_the_road_it_exists_for
run_case case_explain_prints_a_remedy_per_finding_class
run_case case_a_finding_of_a_remedied_rule_names_its_fix_form
run_case case_an_unmeasured_class_prints_the_line_to_paste
run_case case_a_product_valve_suppresses_and_is_counted
run_case case_terse_keeps_the_count_and_drops_only_the_ok_lines
run_case case_terse_prints_enforcement_broken_in_full
run_case case_a_memoised_rule_is_not_rescanned
run_case case_a_moved_input_misses_one_rule_and_names_it
run_case case_a_hit_replays_the_red
run_case case_the_selftest_bypasses_the_memo_and_its_canaries_still_fire
run_case case_memo_no_scans_always_and_needs_a_reason
run_case case_an_undecidable_key_scans
run_case case_the_readers_ignore_the_memo
run_case case_an_empty_capture_is_could_not_look
run_case case_the_exit_census_never_lowers_the_drives_own_status
run_case case_a_declared_census_prints_its_lines_under_explain
run_case case_a_rule_with_no_census_explains_byte_identically
run_case case_a_census_that_does_not_resolve_is_exit_2_naming_it
run_case case_a_census_that_raises_is_a_could_not_look_line
run_case case_rule_59s_census_is_the_per_app_draft_block
run_case case_rule_54s_census_lists_a_silent_read_with_the_line_that_opens_it
run_case case_rule_54s_census_agrees_with_the_rules_own_read_findings
# LAST, deliberately: it reads the tree every case above left behind.
run_case case_the_drive_leaves_the_working_tree_as_it_found_it

echo "test_gate_explain: ${PASSED} passed · ${FAILED} failed · ${DRIVE_SKIPPED} skipped"
drive_finished
if [ "$FAILED" -gt 0 ]; then
    echo "!! a red can no longer explain itself. The trailer, the two readers and" >&2
    echo "   --terse are the difference between a builder acting on a finding and a" >&2
    echo "   builder going to look for the rule in a 7,000-line yaml." >&2
    exit 1
fi
exit 0
