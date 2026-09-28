#!/usr/bin/env bash
# THIS FILE IS EXECUTED, AND IT IS BASH — not POSIX sh, and not zsh. The
# shebang above is honoured by `./this`; `sh this` and `zsh this` IGNORE it,
# and neither of them fails where the mistake was made.
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
# drives: .github/workflows/ci.yml .github/workflows/nightly-proof.yml deploy/provision.sh scripts/check.sh scripts/gate_ledger.sh scripts/gate_refuse.sh scripts/tests/drive_preamble.sh quality/rules.yaml quality/runners/workflow_credential_pins.py
# cites: scripts/pm_fold.sh scripts/pm_push.sh scripts/githooks/pre-push deploy/stage.sh deploy/tests/test_stage.sh
#
# THE WORKFLOW DRIVE — what `.github/workflows/ci.yml` measures, once, and what
# it honours, once — and how it hands a green tree to a box.
#
#   ./deploy/tests/test_ci_derive.sh          run every case
#   ./deploy/tests/test_ci_derive.sh --list   name them and stop
#
# WHY IT EXISTS. The workflow is shell inside YAML, and shell inside YAML is the
# least driven code in any repository: it runs on a runner, once, on somebody
# else's machine, and the only way to learn it was wrong is a red run — or, far
# worse, a GREEN one. Five properties of it are invisible when they are right
# and silent when they are wrong:
#
#   * THE MATRIX IS THE GATE'S ANSWER. `derive` asks `./scripts/check.sh
#     --list-legs --ci` and expands it: a unit whose `shards` column is an
#     INTEGER runs that many rows (the selftest count, derived from the
#     committed CI walls table), a unit that says `N-capable` runs
#     PYTEST_SHARDS rows, every other unit one row — and every row carries the
#     listing's `passes` column, so the suite's rows ride ONE pass. A listing
#     that refuses fails the job with no matrix; there is no fallback.
#   * THE RECORD. The `gate-verdict` job writes the one line
#     `pm_push.sh --ci-verdict` banks — `rc=0` only when derive, every row and
#     images succeeded, the MEASURED tree, the run's attempt, `scope=whole` on a
#     train's head and on a push — through `gate_ci_record_line`, the grammar's
#     own writer, and publishes it `if: always()`.
#   * PAY ONCE. On a push to main `derive` asks `gate_ci_consult`; a pull
#     request's green record for exactly this tree empties the matrix, `legs` is
#     skipped by its `if:`, and `verdict` says the tree was honoured. Anything
#     else measures in full, and a skipped `legs` that nothing honoured is red.
#   * THE SHAPE. `images` still stands behind `verdict`; the record job needs
#     `[derive, legs, images]`; no job can write contents; the two read grants
#     the consult spends sit on the consult's job alone; house rule 62 is clean
#     on the file.
#   * THE DEPLOY. `deploy-staging` stands behind `verdict` and `images`, runs
#     on a push to main only, and SKIPS WITH A NOTICE unless the product's
#     variables name a stage box and a deploy role; `deploy-prod` is a
#     dispatch with `tree` and `sanction` inputs that checks out the tree
#     staging HOLDS (a docs-only head leaves staging on an older one), hands
#     `deploy/stage.sh --env prod` the latest nightly leak proof, and refuses
#     when the product names no prod. Both call the one deploy script, hold no
#     credential but the OIDC role, carry dispatch text as env and never as
#     shell, and are judged by rule 62 (a plant with their valves stripped is
#     named). A dispatch runs no gate job and has its own concurrency group.
#     The real script's acts and prod refusals are `deploy/tests/test_stage.sh`'s.
#
# HOW IT DRIVES. The `run:` blocks are READ OUT OF THE WORKFLOW ITSELF with
# `yaml.safe_load` and executed under `bash -e`, as a runner executes them —
# nothing here is a copy of the workflow's shell. Each block runs in a scratch
# world under a CLEAN environment (`env -i` plus the knobs the case sets), so a
# drive that runs inside a CI row never hands its own row's variables to the
# block it is judging. `scripts/check.sh` is a stub that records its argv and
# answers either a fixture listing or a REPLAY of what this checkout's real
# `--list-legs --ci` printed at the start of the run; `gh` is a stub that
# answers the four calls the consult makes; the record and the consult run
# the REAL `scripts/gate_ledger.sh`, copied into a throwaway git repository.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * WHETHER GITHUB AGREES. `fromJSON`, `strategy.matrix`, a job-level `if:`
#     skipping a job whose matrix is empty, `needs.<job>.result`,
#     `steps.<id>.outputs` and `upload-artifact` are the platform's semantics;
#     this drive reads the expressions and runs the shell. The live run is the
#     proof that Actions agrees — it is the rung's live drive, not a case here.
#   * THE GITHUB API'S REAL ANSWERS. The stub `gh` answers in the shapes the
#     consult asks for (`--jq` already applied); whether the real API returns
#     the pull requests of a pushed commit is GitHub's.
#   * THE CONSULT'S OWN REFUSALS. Every reason `gate_ci_consult` measures
#     instead of honouring is `scripts/tests/test_pm_push.sh`'s; this drive
#     proves the workflow asks it and acts on both of its answers.
#   * WALL CLOCK, and whether the runner's `gh` is authenticated.
#   * THE RUNNER'S ROAD TO A BOX. `stage.sh` reaches a box over plain ssh and
#     no transport from a hosted runner is built; the jobs say what they assume
#     and a live staging deploy is the PM's proof once an owner sets the
#     variables. Whether the OIDC trust admits the jobs' `sub` is AWS's.
set -uo pipefail

cd "$(dirname "$0")/../.."

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_ci_derive: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   This drive builds throwaway git repositories, which is exactly the shape" >&2
    echo "   that wrote into the real repository from the pre-push hook the one time" >&2
    echo "   it was done without the preamble. Refusing to run without it." >&2
    exit 2
}
# shellcheck source=scripts/tests/drive_preamble.sh
. scripts/tests/drive_preamble.sh
DRIVE_OPTED_IN_TO_FINISH=1

PASSED=0
FAILED=0

cannot_look() {
    echo "!! test_ci_derive: $*" >&2
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
    echo "!! unknown argument '$1': test_ci_derive.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

WORKFLOW=".github/workflows/ci.yml"
[ -f "$WORKFLOW" ] || cannot_look "$WORKFLOW is not in this tree — there is nothing to drive"
[ -f scripts/gate_ledger.sh ] || cannot_look "scripts/gate_ledger.sh is not in this tree — the record and the consult are its functions"
[ -f scripts/gate_refuse.sh ] || cannot_look "scripts/gate_refuse.sh is not in this tree — scripts/gate_ledger.sh sources it beside itself"
[ -f quality/runners/workflow_credential_pins.py ] || cannot_look "quality/runners/workflow_credential_pins.py is not in this tree — house rule 62's runner is how 'clean on the file' is read"
command -v jq >/dev/null 2>&1 || cannot_look "no jq on PATH — the derive block builds its matrix with jq, as the runner does"

# A python that can read YAML: the checkout's venv first (pyyaml is locked
# there), then whatever python3 is on PATH.
PY=""
for candidate in ./.venv/bin/python python3; do
    if command -v "$candidate" >/dev/null 2>&1 &&
        "$candidate" -c 'import yaml' >/dev/null 2>&1; then
        PY="$candidate"
        break
    fi
done
[ -n "$PY" ] || cannot_look "no python with pyyaml on PATH — the run blocks are read out of the workflow with yaml.safe_load, never transcribed"
case "$PY" in ./*) PY="$PWD/${PY#./}" ;; esac

ROOT="$PWD"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-ci-derive-drive.XXXXXX")" || cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'rm -rf "$WORK"'

# --- THE WORKFLOW, READ ----------------------------------------------------------
# One reader for every question below: a job's step by id OR name (its `run:`
# text, or any key of it as JSON), and a job's own keys as JSON. A block that is
# not there prints nothing and exits 3, which each caller turns into a FAILED
# case naming what it looked for — a drive that cannot find the logic has not
# proved the logic is wrong, but on the baseline that absence IS the red.
cat >"$WORK/wf.py" <<'PYTHON'
import json
import sys

import yaml

path, what = sys.argv[1], sys.argv[2]
doc = yaml.safe_load(open(path, encoding="utf-8"))
jobs = doc.get("jobs") or {}


def step_of(job, want):
    for step in (jobs.get(job) or {}).get("steps") or []:
        if step.get("id") == want or step.get("name") == want:
            return step
    raise SystemExit(3)


if what == "run":
    step = step_of(sys.argv[3], sys.argv[4])
    if "run" not in step:
        raise SystemExit(3)
    sys.stdout.write(step["run"])
elif what == "step":
    print(json.dumps(step_of(sys.argv[3], sys.argv[4]), sort_keys=True))
elif what == "job":
    if sys.argv[3] not in jobs:
        raise SystemExit(3)
    print(json.dumps(jobs[sys.argv[3]], sort_keys=True, default=str))
elif what == "workflow":
    print(json.dumps(doc, sort_keys=True, default=str))
else:
    raise SystemExit(f"unknown question {what!r}")
PYTHON

wf() { "$PY" "$WORK/wf.py" "$WORKFLOW" "$@" 2>/dev/null; }
job_json() { wf job "$1" || printf '{}'; }
step_json() { wf step "$1" "$2" || printf '{}'; }

extract_run() {
    local job=$1 want=$2 out=$3
    : >"$out"
    wf run "$job" "$want" >"$out" || return 1
    [ -s "$out" ]
}

DERIVE_SH="$WORK/derive.sh"
CONSULT_SH="$WORK/consult.sh"
LEGS_SH="$WORK/legs.sh"
ROW_SH="$WORK/row.sh"
VERDICT_SH="$WORK/verdict.sh"
RECORD_SH="$WORK/record.sh"
HAVE_DERIVE=0 HAVE_CONSULT=0 HAVE_LEGS=0 HAVE_ROW=0 HAVE_VERDICT=0 HAVE_RECORD=0
extract_run derive units "$DERIVE_SH" && HAVE_DERIVE=1
extract_run derive consult "$CONSULT_SH" && HAVE_CONSULT=1
extract_run legs "the gate, one unit (./scripts/check.sh --leg)" "$LEGS_SH" && HAVE_LEGS=1
extract_run legs row "$ROW_SH" && HAVE_ROW=1
extract_run verdict "the verdict" "$VERDICT_SH" && HAVE_VERDICT=1
extract_run gate-verdict record "$RECORD_SH" && HAVE_RECORD=1
# The two blocks every other case stands on: absent, nothing can be asserted.
[ "$HAVE_DERIVE" = "1" ] || cannot_look "the derive job's 'units' step has no run block in $WORKFLOW"
[ "$HAVE_LEGS" = "1" ] || cannot_look "the legs job's gate step has no run block in $WORKFLOW"

# --- THE REAL GATE'S ANSWER, TAKEN ONCE -----------------------------------------
# REDIRECTED, NEVER PIPED — the gate refuses a piped stdout. The listing takes
# no lease, no lock and no slot, so asking it from a drive is legal (it is not a
# nested gate run). Both forms are recorded, so the replay stub answers exactly
# what this checkout's gate would.
REPLAY="$WORK/replay"
mkdir -p "$REPLAY"
rc=0
./scripts/check.sh --list-legs >"$REPLAY/full.out" 2>"$REPLAY/full.err" </dev/null || rc=$?
echo "$rc" >"$REPLAY/full.rc"
[ "$rc" = "0" ] && [ -s "$REPLAY/full.out" ] ||
    cannot_look "this checkout's ./scripts/check.sh --list-legs exits ${rc} or prints nothing: $(sed -n 1p "$REPLAY/full.err")"
rc=0
./scripts/check.sh --list-legs --ci >"$REPLAY/ci.out" 2>"$REPLAY/ci.err" </dev/null || rc=$?
echo "$rc" >"$REPLAY/ci.rc"
[ "$rc" = "0" ] && [ -s "$REPLAY/ci.out" ] ||
    cannot_look "this checkout's ./scripts/check.sh --list-legs --ci exits ${rc} or prints nothing: $(sed -n 1p "$REPLAY/ci.err")"
# The listing's answers the cases compare against, derived here and never typed:
# the unit whose `passes` is 1, and every unit whose `shards` is an integer.
ONEPASS_UNITS=$(awk -F'\t' '$5 == "1" { print $1 }' "$REPLAY/ci.out")
[ -n "$ONEPASS_UNITS" ] ||
    cannot_look "no unit of this checkout's --list-legs --ci carries passes=1 — the property 'the suite rides one pass' has no subject"

# --- the assertions --------------------------------------------------------------
ok() {
    echo "  ok       $*"
    PASSED=$((PASSED + 1))
}
bad() {
    echo "  FAILED   $*"
    FAILED=$((FAILED + 1))
}
holds() {
    local label="$1" want="$2" got="$3"
    if [ "$want" = "$got" ]; then ok "${label} — ${got}"; else
        bad "${label} — wanted '${want}', got '${got}'"
    fi
}
says() {
    case "$OUT" in
    *"$1"*) ok "it says: $1" ;;
    *)
        bad "it never says: $1"
        printf '%s\n' "$OUT" | sed 's/^/           | /'
        ;;
    esac
}

# --- the scratch world -------------------------------------------------------------
CASE_DIR=""
OUTPUT_FILE=""
ARGV_LOG=""
OUT=""
RC=0

# A throwaway tree holding a stub `scripts/check.sh` and nothing else. The stub
# records its argv (and the walls variable it was handed, and whether that
# file's directory existed) and answers from the knobs the case sets.
fresh_derive() {
    CASE_DIR="$WORK/case.$RANDOM$$"
    OUTPUT_FILE="$CASE_DIR.out/github_output"
    ARGV_LOG="$CASE_DIR.out/argv.log"
    rm -rf "$CASE_DIR" "$CASE_DIR.out" "$CASE_DIR.tmp"
    mkdir -p "$CASE_DIR/scripts" "$CASE_DIR.out" "$CASE_DIR.tmp"
    : >"$OUTPUT_FILE"
    : >"$ARGV_LOG"
    cat >"$CASE_DIR/scripts/check.sh" <<'CHECKSTUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$DJB_DRIVE_ARGV_LOG"
if [ -n "${DJB_MEMBER_WALLS_OUT:-}" ]; then
    d=${DJB_MEMBER_WALLS_OUT%/*}
    if [ -d "$d" ]; then w=dir-exists; else w=dir-missing; fi
    printf 'walls=%s %s\n' "$DJB_MEMBER_WALLS_OUT" "$w" >>"$DJB_DRIVE_ARGV_LOG.env"
fi
if [ "${1:-}" = "--list-legs" ]; then
    if [ -n "${DJB_DRIVE_REPLAY:-}" ]; then
        if [ "$#" = 1 ]; then
            which=full
        elif [ "$#" = 2 ] && [ "$2" = "--ci" ]; then
            which=ci
        else
            shift
            echo "!! unexpected extra arguments: $*" >&2
            exit 2
        fi
        cat "$DJB_DRIVE_REPLAY/$which.out"
        cat "$DJB_DRIVE_REPLAY/$which.err" >&2
        exit "$(cat "$DJB_DRIVE_REPLAY/$which.rc")"
    fi
    [ -z "${DJB_DRIVE_LIST_STDOUT:-}" ] || printf '%b' "$DJB_DRIVE_LIST_STDOUT"
    [ -z "${DJB_DRIVE_LIST_STDERR:-}" ] || printf '%b' "$DJB_DRIVE_LIST_STDERR" >&2
    exit "${DJB_DRIVE_LIST_RC:-0}"
fi
exit "${DJB_DRIVE_LEG_RC:-0}"
CHECKSTUB
    chmod +x "$CASE_DIR/scripts/check.sh"
}

# block_run <script> [VAR=value ...] — one extracted block, inside the scratch
# tree, under a CLEAN environment plus this case's knobs, under `bash -e` as a
# runner invokes a `run:` block (`bash -e {0}`: the flag is on the INVOCATION,
# where the block's own text cannot see it). DRIVE_BASH_FLAGS="" runs it bare.
block_run() {
    local script="$1"
    shift
    OUT="$(
        cd "$CASE_DIR" && env -i \
            PATH="$PATH" HOME="${HOME:-/tmp}" LANG=C.UTF-8 \
            TMPDIR="$CASE_DIR.tmp" RUNNER_TEMP="$CASE_DIR.tmp" \
            GITHUB_OUTPUT="$OUTPUT_FILE" \
            DJB_DRIVE_ARGV_LOG="$ARGV_LOG" \
            PYTEST_SHARDS="${DRIVE_SHARDS:-3}" \
            "$@" bash ${DRIVE_BASH_FLAGS--e} "$script" 2>&1
    )"
    RC=$?
}

drive() {
    local label="$1" want="$2"
    shift 2
    [ "$1" = "--" ] && shift
    "$@"
    if [ "$RC" = "$want" ]; then
        ok "${label} — exit ${RC}"
    else
        bad "${label} — wanted exit ${want}, got ${RC}"
        printf '%s\n' "$OUT" | sed 's/^/           | /'
    fi
}

# What a block wrote to `$GITHUB_OUTPUT`, by key. Absent is the empty string.
output_of() { sed -n "s/^$1=//p" "$OUTPUT_FILE" | sed -n 1p; }

# rows_of <unit> — how many matrix rows carry that unit.
rows_of() { output_of matrix | jq -r --arg u "$1" '[.[] | select(.unit == $u)] | length' 2>/dev/null || echo "?"; }

# A 5-column listing in `--list-legs --ci`'s shape:
#   <unit>\t<needs>\t<shards>\t<composed-of>\t<passes>
# an indivisible unit, a unit with a DERIVED integer count, the one-pass suite
# unit at N-capable, and a network unit.
LISTING_CI="fast\tdb\t0\truff,mypy\t\ndrives\tdb,docker\t4\tselftest,drv_a,drv_b\t\nsuite\tdb,redis\tN-capable\tpartition,suite-x2\t1\nnet\tnetwork\t0\tsupply\t\n"

# =============================================================================
# C1.1 — derive asks `--list-legs --ci` and expands it
# =============================================================================

case_derive_asks_the_gate_for_the_ci_listing() {
    # THE ARGV IS THE ONLY PLACE THE PROPERTY IS VISIBLE: the matrix of a
    # listing that happens to carry no integer looks the same either way.
    fresh_derive
    drive "derive against a replay of this checkout's gate" 0 -- block_run "$DERIVE_SH" \
        DJB_DRIVE_REPLAY="$REPLAY"
    holds "the listing call derive makes" "--list-legs --ci" "$(paste -sd'|' "$ARGV_LOG")"
}

case_the_real_listing_becomes_the_measured_matrix() {
    # TODAY'S TABLE, AS A RUNNER WOULD BUILD IT NOW. Every unit of the listing
    # is in the matrix; a unit whose `shards` is an integer runs exactly that
    # many rows `k/<that integer>`; a unit that says `N-capable` runs
    # PYTEST_SHARDS rows; every row carries `passes`, and it is `1` exactly on
    # the unit the listing marks.
    local unit shards n want got wrong="" missing="" shards_ok=""
    fresh_derive
    DRIVE_SHARDS=3
    block_run "$DERIVE_SH" DJB_DRIVE_REPLAY="$REPLAY"
    unset DRIVE_SHARDS
    if [ "$RC" != "0" ]; then
        bad "derive exited ${RC} against the real listing — there is no matrix to read"
        printf '%s\n' "$OUT" | sed 's/^/           | /'
        return 0
    fi
    while IFS=$'\t' read -r unit _needs shards _legs _passes; do
        [ -n "$unit" ] || continue
        case "$shards" in
        0) n=1 ;;
        N-capable) n=3 ;;
        *) n=$shards ;;
        esac
        got=$(rows_of "$unit")
        if [ "$got" = "0" ]; then
            missing="${missing}${missing:+ }${unit}"
        elif [ "$got" != "$n" ]; then
            wrong="${wrong}${wrong:+ }${unit}(${got} rows, the listing says ${shards})"
        fi
        case "$shards" in
        0 | N-capable) ;;
        *) shards_ok="${shards_ok}${shards_ok:+ }${unit}=${shards}" ;;
        esac
    done <"$REPLAY/ci.out"
    holds "units of the listing absent from the matrix" "" "$missing"
    holds "units whose row count is not the listing's answer" "" "$wrong"
    if [ -n "$shards_ok" ]; then
        ok "a unit the listing counts runs by the LISTING's count, not PYTEST_SHARDS: ${shards_ok}"
    else
        ok "no unit of today's listing carries an integer (no table) — the N-capable arm carries it"
    fi
    holds "every row carries a passes key" "0" \
        "$(output_of matrix | jq -r '[.[] | select(has("passes") | not)] | length' 2>/dev/null || echo '?')"
    for unit in $ONEPASS_UNITS; do
        holds "every ${unit} row is one pass" "$(rows_of "$unit")" \
            "$(output_of matrix | jq -r --arg u "$unit" '[.[] | select(.unit == $u and .passes == "1")] | length' 2>/dev/null || echo '?')"
        holds "the ${unit} rows are PYTEST_SHARDS (3) of them" "3" "$(rows_of "$unit")"
    done
    holds "rows marked one pass on a unit the listing did not mark" "0" \
        "$(output_of matrix | jq -r --arg w " $(printf '%s ' $ONEPASS_UNITS)" \
            '[.[] | select(.passes == "1") | select(.unit as $u | ($w | contains(" " + $u + " ")) | not)] | length' 2>/dev/null || echo '?')"
}

case_a_listing_becomes_rows_by_its_own_columns() {
    # THE SHAPE, ON A FIXTURE THAT HOLDS EVERY KIND: 1 + 4 + 3 + 1 rows at
    # PYTEST_SHARDS=3, in the listing's order, the JSON `fromJSON` will read.
    fresh_derive
    DRIVE_SHARDS=3
    drive "a four-unit listing at PYTEST_SHARDS=3" 0 -- block_run "$DERIVE_SH" \
        DJB_DRIVE_LIST_STDOUT="$LISTING_CI"
    unset DRIVE_SHARDS
    holds "the matrix" \
        '[{"needs":"db","passes":"","shard":"","unit":"fast"},{"needs":"db,docker","passes":"","shard":"1/4","unit":"drives"},{"needs":"db,docker","passes":"","shard":"2/4","unit":"drives"},{"needs":"db,docker","passes":"","shard":"3/4","unit":"drives"},{"needs":"db,docker","passes":"","shard":"4/4","unit":"drives"},{"needs":"db,redis","passes":"1","shard":"1/3","unit":"suite"},{"needs":"db,redis","passes":"1","shard":"2/3","unit":"suite"},{"needs":"db,redis","passes":"1","shard":"3/3","unit":"suite"},{"needs":"network","passes":"","shard":"","unit":"net"}]' \
        "$(output_of matrix | jq -cS '.' 2>/dev/null)"
    says "row: drives 4/4"
    says "row: suite 3/3 passes=1"

    # PYTEST_SHARDS moves the N-capable unit and NOT the counted one.
    fresh_derive
    DRIVE_SHARDS=5
    drive "the same listing at PYTEST_SHARDS=5" 0 -- block_run "$DERIVE_SH" \
        DJB_DRIVE_LIST_STDOUT="$LISTING_CI"
    unset DRIVE_SHARDS
    holds "the counted unit keeps the listing's count" "4" "$(rows_of drives)"
    holds "the N-capable unit takes PYTEST_SHARDS" "5" "$(rows_of suite)"

    # NO TABLE: the listing prints `N-capable` for the counted unit too (the
    # honest "CI must supply the count"), and PYTEST_SHARDS supplies it.
    fresh_derive
    drive "a listing with no count" 0 -- block_run "$DERIVE_SH" \
        DJB_DRIVE_LIST_STDOUT="fast\tdb\t0\truff\t\ndrives\tdb\tN-capable\tselftest,drv_a\t\n"
    holds "an N-capable unit with no passes mark takes PYTEST_SHARDS" "3" "$(rows_of drives)"
    holds "and rides both passes" "0" \
        "$(output_of matrix | jq -r '[.[] | select(.passes == "1")] | length' 2>/dev/null || echo '?')"
}

case_a_listing_the_matrix_cannot_honour_is_refused() {
    # EACH OF THESE IS A ROW THE GATE WOULD REFUSE AT THE LEG, OR A COUNT NOBODY
    # CAN RUN — refused at derive, exit 2, no matrix, never a smaller run.
    local fixture label
    for fixture in \
        "one pass on an indivisible unit|suite\tdb\t0\tsuite-x2\t1\n" \
        "a shards column that is not a count|drives\tdb\tmany\tselftest\t\n" \
        "a passes column that is not 1|suite\tdb\tN-capable\tsuite-x2\t2\n"; do
        label=${fixture%%|*}
        fresh_derive
        drive "${label}" 2 -- block_run "$DERIVE_SH" DJB_DRIVE_LIST_STDOUT="${fixture#*|}"
        holds "no matrix was emitted (${label})" "" "$(output_of matrix)"
    done
    fresh_derive
    DRIVE_SHARDS=zero
    drive "a PYTEST_SHARDS that is not a count" 2 -- block_run "$DERIVE_SH" \
        DJB_DRIVE_LIST_STDOUT="$LISTING_CI"
    unset DRIVE_SHARDS
    holds "no matrix was emitted (PYTEST_SHARDS=zero)" "" "$(output_of matrix)"
}

case_a_refusing_listing_fails_the_job_with_no_fallback() {
    # THERE IS NO FALLBACK, AND THAT IS THE DESIGN. Exit 2 is "enforcement is
    # broken" and outranks a pass. Under the runner's `bash -e` AND a bare bash.
    local flags label
    for flags in -e ""; do
        label="${flags:-bare bash}"
        fresh_derive
        DRIVE_BASH_FLAGS="$flags"
        drive "exit 2 from the listing (${label})" 2 -- block_run "$DERIVE_SH" \
            DJB_DRIVE_LIST_RC=2 \
            DJB_DRIVE_LIST_STDERR="!! ENFORCEMENT ITSELF IS BROKEN — this outranks any pass.\n"
        holds "no matrix was emitted (${label})" "" "$(output_of matrix)"
        says "ENFORCEMENT ITSELF IS BROKEN"

        fresh_derive
        drive "exit 1 from the listing beside a printed table (${label})" 1 -- block_run "$DERIVE_SH" \
            DJB_DRIVE_LIST_RC=1 DJB_DRIVE_LIST_STDOUT="$LISTING_CI"
        holds "no matrix was emitted (${label})" "" "$(output_of matrix)"

        fresh_derive
        drive "exit 0 and silence (${label})" 2 -- block_run "$DERIVE_SH" DJB_DRIVE_LIST_STDOUT=""
        holds "no matrix was emitted (${label})" "" "$(output_of matrix)"
        unset DRIVE_BASH_FLAGS
    done
}

case_the_seed_is_minted_once() {
    local a
    fresh_derive
    block_run "$DERIVE_SH" DJB_DRIVE_LIST_STDOUT="$LISTING_CI"
    a="$(output_of seed)"
    case "$a" in
    '' | *[!0-9]*) bad "no numeric seed was minted (got '${a}')" ;;
    *) ok "a seed was minted — ${a}" ;;
    esac
    holds "exactly one seed line" "1" "$(grep -c '^seed=' "$OUTPUT_FILE" || true)"
}

case_the_row_invokes_the_gate_and_nothing_else() {
    # Exactly `./scripts/check.sh --leg <unit> [--shard k/N] [--passes 1]
    # [--pr --base <sha>]`, read off the stub's own argv — and `--pr --base`
    # ONLY on a pull request whose head is not a train (`pm/*`): a train is
    # measured whole, because its run is the one measurement.
    local walls
    walls="$WORK/walls.$RANDOM/member-walls/walls.tsv"
    fresh_derive
    drive "an indivisible unit on a push" 0 -- block_run "$LEGS_SH" \
        UNIT=fast SHARD= PASSES= PR_BASE= PR_HEAD_REF= DJB_GATE_PYTEST_SEED=12345 DJB_MEMBER_WALLS_OUT="$walls"
    holds "one invocation, bare" "--leg fast" "$(cat "$ARGV_LOG")"

    fresh_derive
    drive "a counted unit's shard on a push" 0 -- block_run "$LEGS_SH" \
        UNIT=drives SHARD=3/4 PASSES= PR_BASE= PR_HEAD_REF= DJB_GATE_PYTEST_SEED=12345 DJB_MEMBER_WALLS_OUT="$walls"
    holds "the shard rides along" "--leg drives --shard 3/4" "$(cat "$ARGV_LOG")"
    holds "the walls file the row was handed, and its directory existed" "walls=${walls} dir-exists" \
        "$(cat "$ARGV_LOG.env" 2>/dev/null)"

    fresh_derive
    drive "the suite's shard on a push" 0 -- block_run "$LEGS_SH" \
        UNIT=suite SHARD=2/3 PASSES=1 PR_BASE= PR_HEAD_REF= DJB_GATE_PYTEST_SEED=12345 DJB_MEMBER_WALLS_OUT="$walls"
    holds "the shard carries --passes 1" "--leg suite --shard 2/3 --passes 1" "$(cat "$ARGV_LOG")"

    fresh_derive
    drive "the suite's shard on a train's pull request" 0 -- block_run "$LEGS_SH" \
        UNIT=suite SHARD=2/3 PASSES=1 PR_BASE=abc123 PR_HEAD_REF=pm/train-9 DJB_GATE_PYTEST_SEED=12345 DJB_MEMBER_WALLS_OUT="$walls"
    holds "a pm/* head runs whole — no --pr --base" "--leg suite --shard 2/3 --passes 1" "$(cat "$ARGV_LOG")"

    fresh_derive
    drive "a counted unit's shard on a feature branch's pull request" 0 -- block_run "$LEGS_SH" \
        UNIT=drives SHARD=1/4 PASSES= PR_BASE=abc123 PR_HEAD_REF=feature/x DJB_GATE_PYTEST_SEED=12345 DJB_MEMBER_WALLS_OUT="$walls"
    holds "any other pull request is narrowed" "--leg drives --shard 1/4 --pr --base abc123" "$(cat "$ARGV_LOG")"

    fresh_derive
    drive "a unit that failed" 1 -- block_run "$LEGS_SH" \
        UNIT=fast SHARD= PASSES= PR_BASE= PR_HEAD_REF= DJB_GATE_PYTEST_SEED=12345 DJB_MEMBER_WALLS_OUT="$walls" DJB_DRIVE_LEG_RC=1
    fresh_derive
    drive "a unit whose enforcement broke" 2 -- block_run "$LEGS_SH" \
        UNIT=fast SHARD= PASSES= PR_BASE= PR_HEAD_REF= DJB_GATE_PYTEST_SEED=12345 DJB_MEMBER_WALLS_OUT="$walls" DJB_DRIVE_LEG_RC=2
}

case_every_row_writes_its_walls_and_uploads_them() {
    # THE HARVEST'S INPUT (`scripts/pm_fold.sh`'s walls step reads every
    # `member-walls*` artifact of a run): the gate step names a walls file
    # OUTSIDE the checkout, and an upload step publishes it `if: always()` —
    # a red shard's walls are still walls — under a per-row name the row
    # step derives, since an artifact name cannot carry the shard's `/`.
    local gate upload
    gate=$(step_json legs "the gate, one unit (./scripts/check.sh --leg)")
    holds "the gate step sets DJB_MEMBER_WALLS_OUT under the runner's temp" \
        '${{ runner.temp }}/member-walls/walls.tsv' \
        "$(printf '%s' "$gate" | jq -r '.env.DJB_MEMBER_WALLS_OUT // ""')"
    upload=$("$PY" - "$WORKFLOW" <<'PYTHON'
import json, sys, yaml
doc = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
for step in doc["jobs"]["legs"]["steps"]:
    if str(step.get("uses", "")).startswith("actions/upload-artifact@") and "member-walls" in json.dumps(step):
        print(json.dumps(step, sort_keys=True))
        break
PYTHON
    )
    if [ -z "$upload" ]; then
        bad "the legs job has no upload-artifact step for the member walls"
    else
        holds "the walls upload runs always" "always()" "$(printf '%s' "$upload" | jq -r '.if // ""')"
        holds "its name is the row step's" '${{ steps.row.outputs.walls_artifact }}' \
            "$(printf '%s' "$upload" | jq -r '.with.name // ""')"
        holds "its path is the walls directory" '${{ runner.temp }}/member-walls/' \
            "$(printf '%s' "$upload" | jq -r '.with.path // ""')"
    fi
    if [ "$HAVE_ROW" != "1" ]; then
        bad "the legs job has no 'row' step naming the walls artifact"
        return 0
    fi
    fresh_derive
    drive "the row step on a counted unit's shard" 0 -- block_run "$ROW_SH" UNIT=drives SHARD=2/6
    holds "the artifact name" "member-walls-drives-2-of-6" "$(output_of walls_artifact)"
    fresh_derive
    drive "the row step on an indivisible unit" 0 -- block_run "$ROW_SH" UNIT=fast SHARD=
    holds "the artifact name" "member-walls-fast" "$(output_of walls_artifact)"
}

case_the_workflow_types_no_unit_name_of_its_own() {
    # Everything CI runs arrives from the listing. Comment lines are prose; a
    # unit name in a `run:`, a `matrix:` or a job name would be a second list.
    local unit hits total=0
    for unit in $(cut -f1 "$REPLAY/ci.out"); do
        hits="$(grep -vE '^\s*#' "$WORKFLOW" | grep -cwF -- "$unit" || true)"
        if [ "$hits" != "0" ]; then
            bad "the workflow names the unit '${unit}' outside a comment (${hits} time(s))"
            total=$((total + 1))
        fi
    done
    [ "$total" != "0" ] || ok "no unit of the listing appears outside a comment — the matrix is asked for, never typed"
}

# =============================================================================
# C1.2 — the record
# =============================================================================
#
# The record step runs in a throwaway git repository carrying a copy of THIS
# checkout's `scripts/gate_ledger.sh`, so the tree it writes is asserted against
# the same reduction computed here, and the line against the grammar's reader.

# The leg the record's reader lets ride one pass, read from its one declaration
# so the stub listing below composes the one-pass unit of it.
ONEPASS_LEG=$(sed -n 's/^GATE_ONEPASS_UNIT=//p' scripts/gate_ledger.sh)
[ -n "$ONEPASS_LEG" ] || cannot_look "scripts/gate_ledger.sh declares no GATE_ONEPASS_UNIT — the record's reader has no one-pass leg to honour"

RECORD_MATRIX='[{"unit":"fast","needs":"none","shard":"","passes":""},{"unit":"suite","needs":"db","shard":"1/2","passes":"1"},{"unit":"suite","needs":"db","shard":"2/2","passes":"1"},{"unit":"drives","needs":"db","shard":"1/2","passes":""},{"unit":"drives","needs":"db","shard":"2/2","passes":""}]'

fresh_repo() {
    CASE_DIR="$WORK/repo.$RANDOM$$"
    OUTPUT_FILE="$CASE_DIR.out/github_output"
    ARGV_LOG="$CASE_DIR.out/argv.log"
    rm -rf "$CASE_DIR" "$CASE_DIR.out" "$CASE_DIR.tmp"
    drive_require_scratch CASE_DIR "$CASE_DIR"
    mkdir -p "$CASE_DIR/scripts" "$CASE_DIR.out" "$CASE_DIR.tmp"
    : >"$OUTPUT_FILE"
    : >"$ARGV_LOG"
    cp scripts/gate_ledger.sh "$CASE_DIR/scripts/gate_ledger.sh"
    cp scripts/gate_refuse.sh "$CASE_DIR/scripts/gate_refuse.sh"
    # A stub gate: the listing the consult expands a record through, and the
    # FULL_LEGS line `gate_full_legs` reads when there is no drawer.
    sed "s/@ONEPASS@/${ONEPASS_LEG}/g" >"$CASE_DIR/scripts/check.sh" <<'CHECKSTUB'
#!/usr/bin/env bash
FULL_LEGS=ruff,mypy,partition,@ONEPASS@,selftest,drv_a
printf '%s\n' "$*" >>"$DJB_DRIVE_ARGV_LOG"
if [ "${1:-}" = "--list-legs" ]; then
    if [ "${2:-}" = "--ci" ]; then
        printf 'fast\tnone\t0\truff,mypy\t\nsuite\tdb\tN-capable\tpartition,@ONEPASS@\t1\ndrives\tdb\t2\tselftest,drv_a\t\n'
    else
        printf 'fast\tnone\t0\truff,mypy\nsuite\tdb\tN-capable\tpartition,@ONEPASS@\ndrives\tdb\tN-capable\tselftest,drv_a\n'
    fi
    exit 0
fi
exit 0
CHECKSTUB
    chmod +x "$CASE_DIR/scripts/check.sh"
    git -C "$CASE_DIR" init -q
    git -C "$CASE_DIR" config user.email drive@example.invalid
    git -C "$CASE_DIR" config user.name "ci derive drive"
    echo one >"$CASE_DIR/shared.txt"
    git -C "$CASE_DIR" add -A
    git -C "$CASE_DIR" commit -q -m base
}

# record_run [VAR=value ...] — the step, green by default, as a push to main.
record_run() {
    local head
    head="$(git -C "$CASE_DIR" rev-parse HEAD)"
    block_run "$RECORD_SH" \
        DERIVE_RESULT=success LEGS_RESULT=success IMAGES_RESULT=success \
        MATRIX="$RECORD_MATRIX" RUN_ID=31415926535 RUN_ATTEMPT=2 HEAD_SHA="$head" \
        PR_BASE= PR_HEAD_REF= HONOURED= "$@"
}

record_file() { printf '%s' "$CASE_DIR.tmp/gate-verdict/gate_verdict.txt"; }

record_field() {
    awk -v k="$1" '{ for (i = 1; i <= NF; i++) if (index($i, k "=") == 1) { print substr($i, length(k) + 2); exit } }' \
        "$(record_file)" 2>/dev/null || true
}

case_the_record_is_the_measured_tree_and_every_field() {
    local want parsed
    if [ "$HAVE_RECORD" != "1" ]; then
        bad "the gate-verdict job has no 'record' step — there is no record to read"
        return 0
    fi
    fresh_repo
    drive "a green run's record" 0 -- record_run
    want="$(cd "$CASE_DIR" && . scripts/gate_ledger.sh && gate_measured_tree)"
    holds "tree is the MEASURED tree" "$want" "$(record_field tree)"
    holds "commit is the head" "$(git -C "$CASE_DIR" rev-parse HEAD)" "$(record_field commit)"
    holds "legs: the matrix's units, the one-pass unit marked" "drives,fast,suite/1" "$(record_field legs)"
    holds "shards is PYTEST_SHARDS" "3" "$(record_field shards)"
    holds "scope on a push" "whole" "$(record_field scope)"
    holds "rc" "0" "$(record_field rc)"
    holds "run" "31415926535" "$(record_field run)"
    holds "attempt is the run's attempt" "2" "$(record_field attempt)"
    holds "one line" "1" "$(grep -c . "$(record_file)" 2>/dev/null || echo 0)"
    # THE GRAMMAR'S OWN READER ACCEPTS IT — the writer is the seam, not a copy.
    parsed=$(cd "$CASE_DIR" && . scripts/gate_ledger.sh >/dev/null 2>&1 &&
        gate_ci_record_parse "$(sed -n 1p "$(record_file)")" && echo parsed || echo "refused: ${GATE_CI_REC_WHY:-}")
    holds "gate_ci_record_parse reads the line" "parsed" "$parsed"
    holds "the artifact name the step hands the upload is gate_ci_artifact_name's" \
        "$(cd "$CASE_DIR" && . scripts/gate_ledger.sh >/dev/null 2>&1 && gate_ci_artifact_name 2)" \
        "$(output_of artifact)"
}

case_a_red_or_cancelled_job_is_rc_1_and_a_narrowed_pr_says_so() {
    local r
    [ "$HAVE_RECORD" = "1" ] || {
        bad "the gate-verdict job has no 'record' step"
        return 0
    }
    for r in "LEGS_RESULT=failure" "LEGS_RESULT=cancelled" "LEGS_RESULT=skipped" \
        "DERIVE_RESULT=failure" "IMAGES_RESULT=failure" "IMAGES_RESULT=skipped"; do
        fresh_repo
        drive "the record under ${r}" 0 -- record_run "$r"
        holds "rc under ${r}" "1" "$(record_field rc)"
    done
    fresh_repo
    drive "a derive that produced no matrix" 0 -- record_run DERIVE_RESULT=failure MATRIX=
    holds "rc with no matrix" "1" "$(record_field rc)"
    fresh_repo
    drive "a feature branch's pull request" 0 -- record_run PR_BASE=abc123 PR_HEAD_REF=feature/x
    holds "scope on a narrowed pull request" "pr" "$(record_field scope)"
    fresh_repo
    drive "a train's pull request" 0 -- record_run PR_BASE=abc123 PR_HEAD_REF=pm/train-9
    holds "scope on a pm/* pull request" "whole" "$(record_field scope)"
    # THE TWO-TREE CLASS: a head whose measured tree is not the checkout's is
    # WARNED here, and refused by the reader.
    fresh_repo
    drive "a head that is not the checkout" 0 -- record_run \
        HEAD_SHA="$(git -C "$CASE_DIR" commit-tree "$(git -C "$CASE_DIR" mktree </dev/null)" -m empty)"
    says "the reader will refuse this record"
}

case_an_honoured_push_writes_no_record() {
    # A run that measured nothing has no measurement to record: the tree's
    # record is the pull request run's, and a second line here claiming
    # `run=<this run>` would be a record of a measurement that never happened.
    [ "$HAVE_RECORD" = "1" ] || {
        bad "the gate-verdict job has no 'record' step"
        return 0
    }
    fresh_repo
    drive "the record on an honoured push" 0 -- record_run LEGS_RESULT=skipped MATRIX='[]' \
        HONOURED=777 HONOURED_ATTEMPT=2 HONOURED_TREE=abcdef0123
    holds "no record file" "absent" "$([ -e "$(record_file)" ] && echo present || echo absent)"
    holds "no artifact handed to the upload" "" "$(output_of artifact)"
    says "honoured"
}

# =============================================================================
# C1.3 — the consult on a push, and the verdict that honours it
# =============================================================================

# A stub `gh` answering the four calls `gate_ci_consult` makes, `--jq` already
# applied, from knobs: FAKE_RUN (the one completed pull_request run), FAKE_ATTEMPT
# (its latest attempt), FAKE_RECORD (the file its artifact holds).
plant_gh() {
    mkdir -p "$CASE_DIR.bin"
    cat >"$CASE_DIR.bin/gh" <<'GHSTUB'
#!/usr/bin/env bash
printf 'gh %s\n' "$*" >>"$DJB_DRIVE_ARGV_LOG.gh"
case "$1 ${2:-}" in
"api "*"/pulls")
    exit 0
    ;;
"api "*"/runs?"*)
    [ -z "${FAKE_RUN:-}" ] || printf '%s\n' "$FAKE_RUN"
    exit 0
    ;;
"run view")
    printf 'completed %s\n' "${FAKE_ATTEMPT:-1}"
    exit 0
    ;;
"run download")
    name="" dir=""
    shift 2
    while [ "$#" -gt 0 ]; do
        case "$1" in
        --name) name=$2; shift 2 ;;
        --dir) dir=$2; shift 2 ;;
        *) shift ;;
        esac
    done
    if [ "$name" != "gate-verdict-${FAKE_ATTEMPT:-1}" ]; then
        echo "no artifact matches any of the names or patterns provided" >&2
        exit 1
    fi
    mkdir -p "$dir"
    cp "$FAKE_RECORD" "$dir/gate_verdict.txt"
    exit 0
    ;;
esac
echo "stub gh: unexpected call: $*" >&2
exit 1
GHSTUB
    chmod +x "$CASE_DIR.bin/gh"
}

# consult_world <rc> — a throwaway repository whose HEAD a pull request run
# measured, that run's record (rc as given) planted behind the stub gh.
consult_world() {
    local rc=$1 head tree line
    fresh_repo
    plant_gh
    head=$(git -C "$CASE_DIR" rev-parse HEAD)
    tree=$(cd "$CASE_DIR" && . scripts/gate_ledger.sh >/dev/null 2>&1 && gate_measured_tree)
    line=$(cd "$CASE_DIR" && . scripts/gate_ledger.sh >/dev/null 2>&1 &&
        gate_ci_record_line "$head" "$tree" "fast,suite/1,drives" 3 whole "$rc" 777 2)
    printf '%s\n' "$line" >"$CASE_DIR.out/record.txt"
    CONSULT_HEAD=$head
    CONSULT_TREE=$tree
}

consult_run() {
    block_run "$CONSULT_SH" PATH="$CASE_DIR.bin:$PATH" PUSH_SHA="$CONSULT_HEAD" \
        GH_TOKEN=drive GH_REPO=example/drive \
        FAKE_RUN=777 FAKE_ATTEMPT=2 FAKE_RECORD="$CASE_DIR.out/record.txt" "$@"
}

case_an_honoured_push_measures_nothing() {
    local honoured
    [ "$HAVE_CONSULT" = "1" ] || {
        bad "the derive job has no 'consult' step — a push to main re-measures every tree"
        return 0
    }
    consult_world 0
    drive "the consult on a push whose tree a pull request measured green" 0 -- consult_run
    says "consult: honoured run=777 attempt=2 tree=${CONSULT_TREE}"
    honoured=$(output_of honoured)
    holds "the consult's honoured output" "777" "$honoured"
    holds "its attempt" "2" "$(output_of attempt)"
    holds "its tree" "$CONSULT_TREE" "$(output_of tree)"

    # derive, handed the consult's answer, runs no row.
    : >"$OUTPUT_FILE"
    : >"$ARGV_LOG"
    drive "derive handed the honour" 0 -- block_run "$DERIVE_SH" HONOURED="$honoured" \
        HONOURED_ATTEMPT=2 HONOURED_TREE="$CONSULT_TREE"
    holds "the matrix is empty" "[]" "$(output_of matrix)"
    holds "and the gate's listing was never asked" "0" "$(grep -c -- '--list-legs' "$ARGV_LOG" || true)"

    # verdict, with legs skipped by its `if:`, says what honoured it.
    if [ "$HAVE_VERDICT" = "1" ]; then
        drive "verdict on an honoured push" 0 -- block_run "$VERDICT_SH" \
            DERIVE_RESULT=success LEGS_RESULT=skipped HONOURED=777 HONOURED_ATTEMPT=2 HONOURED_TREE="$CONSULT_TREE"
        says "ok: tree ${CONSULT_TREE} measured green by run 777 (attempt 2) — honoured, nothing re-measured"
    else
        bad "the verdict job has no 'the verdict' step"
    fi
}

case_a_push_nothing_honours_measures_in_full() {
    [ "$HAVE_CONSULT" = "1" ] || {
        bad "the derive job has no 'consult' step"
        return 0
    }
    consult_world 1
    drive "the consult on a push whose pull request run was red" 0 -- consult_run
    says "consult: measure"
    holds "no honoured output" "" "$(output_of honoured)"
    : >"$OUTPUT_FILE"
    # This world's stub gate answers its own listing: one indivisible unit, the
    # one-pass unit at N-capable (PYTEST_SHARDS=3) and a unit counted 2 — six rows.
    drive "derive with nothing honoured" 0 -- block_run "$DERIVE_SH" HONOURED=
    holds "the full matrix runs" "6" "$(output_of matrix | jq -r 'length' 2>/dev/null || echo '?')"

    # And a consult that cannot look (a gh that answers nothing) measures too —
    # it never refuses.
    consult_world 0
    printf '#!/usr/bin/env bash\necho "stub gh: the API is down" >&2\nexit 1\n' >"$CASE_DIR.bin/gh"
    drive "the consult with a gh that fails" 0 -- consult_run
    says "consult: measure — could not look"
    holds "no honoured output" "" "$(output_of honoured)"
}

case_the_verdict_honours_only_an_honour() {
    [ "$HAVE_VERDICT" = "1" ] || {
        bad "the verdict job has no 'the verdict' step"
        return 0
    }
    fresh_derive
    drive "every row green" 0 -- block_run "$VERDICT_SH" DERIVE_RESULT=success LEGS_RESULT=success HONOURED=
    says "ok: every unit of the gate ran and passed"
    fresh_derive
    drive "legs skipped and nothing honoured" 1 -- block_run "$VERDICT_SH" DERIVE_RESULT=success LEGS_RESULT=skipped HONOURED=
    fresh_derive
    drive "a red row" 1 -- block_run "$VERDICT_SH" DERIVE_RESULT=success LEGS_RESULT=failure HONOURED=
    fresh_derive
    drive "a failed derive beside an honour" 1 -- block_run "$VERDICT_SH" DERIVE_RESULT=failure LEGS_RESULT=skipped \
        HONOURED=777 HONOURED_ATTEMPT=1 HONOURED_TREE=abc
}

case_the_wiring_between_the_jobs() {
    # The expressions that carry the consult's answer from step to step and job
    # to job, read as the strings GitHub evaluates. That GitHub evaluates them
    # as written is the platform's (declared above); that they are WRITTEN is
    # this case's.
    local derive legs verdict consult units
    derive=$(job_json derive)
    legs=$(job_json legs)
    verdict=$(job_json verdict)
    consult=$(step_json derive consult)
    units=$(step_json derive units)
    holds "the consult runs on a push only" "github.event_name == 'push'" \
        "$(printf '%s' "$consult" | jq -r '.if // ""')"
    holds "the units step reads the consult's honour" '${{ steps.consult.outputs.honoured }}' \
        "$(printf '%s' "$units" | jq -r '.env.HONOURED // ""')"
    holds "derive publishes the honour" '${{ steps.consult.outputs.honoured }}' \
        "$(printf '%s' "$derive" | jq -r '.outputs.honoured // ""')"
    holds "legs is skipped by its if: on an empty matrix" "needs.derive.outputs.matrix != '[]'" \
        "$(printf '%s' "$legs" | jq -r '.if // ""')"
    holds "verdict reads the honour from derive" '${{ needs.derive.outputs.honoured }}' \
        "$(step_json verdict "the verdict" | jq -r '.env.HONOURED // ""')"
    holds "verdict runs always (except on a dispatch, which measures nothing)" "always() && github.event_name != 'workflow_dispatch'" "$(printf '%s' "$verdict" | jq -r '.if // ""')"
    # THE CONSULT NEEDS THE PULL REQUEST'S HEAD IN THE CHECKOUT: a shallow
    # clone answers "commit unknown" and every push re-measures.
    holds "derive's checkout fetches the whole history" "0" \
        "$(printf '%s' "$derive" | jq -r '[.steps[] | select((.uses // "") | startswith("actions/checkout@")) | .with["fetch-depth"]][0] // "unset"')"
}

# =============================================================================
# C1.4 — structural pins
# =============================================================================

case_the_shape_of_the_workflow() {
    local shape="$WORK/shape.txt" r62="$WORK/rule62.json"
    "$PY" - "$WORKFLOW" >"$shape" <<'PYTHON'
import sys, yaml
doc = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
jobs = doc.get("jobs") or {}
def needs(j):
    n = (jobs.get(j) or {}).get("needs") or []
    return [n] if isinstance(n, str) else list(n)
print("images-needs=" + ",".join(needs("images")))
gv = jobs.get("gate-verdict") or {}
print("gv-needs=" + ",".join(needs("gate-verdict")))
print("gv-if=" + str(gv.get("if")))
up = [s for s in gv.get("steps") or [] if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
print("gv-upload-if=" + (str(up[0].get("if")) if up else "none"))
print("gv-upload-name=" + (str((up[0].get("with") or {}).get("name")) if up else "none"))
def perms(p):
    return p if isinstance(p, dict) else {}
write = [n for n, j in jobs.items() if perms(j.get("permissions")).get("contents") == "write"]
if perms(doc.get("permissions")).get("contents") == "write":
    write.append("<workflow>")
print("contents-write=" + ",".join(write))
for grant in ("actions", "pull-requests"):
    holders = sorted(n for n, j in jobs.items() if perms(j.get("permissions")).get(grant) in ("read", "write"))
    if perms(doc.get("permissions")).get(grant):
        holders.append("<workflow>")
    print(f"{grant}-holders=" + ",".join(holders))
PYTHON
    holds "images still stands behind verdict" "1" \
        "$(sed -n 's/^images-needs=//p' "$shape" | tr ',' '\n' | grep -cx verdict || true)"
    holds "gate-verdict needs every job it speaks for" "derive,legs,images" "$(sed -n 's/^gv-needs=//p' "$shape")"
    holds "gate-verdict runs always (except on a dispatch, which measures nothing)" "always() && github.event_name != 'workflow_dispatch'" "$(sed -n 's/^gv-if=//p' "$shape")"
    holds "its upload runs whenever the record step handed it a name" \
        "always() && steps.record.outputs.artifact != ''" "$(sed -n 's/^gv-upload-if=//p' "$shape")"
    holds "its upload is named by the record step" '${{ steps.record.outputs.artifact }}' \
        "$(sed -n 's/^gv-upload-name=//p' "$shape")"
    holds "no job holds contents: write" "" "$(sed -n 's/^contents-write=//p' "$shape")"
    # TWO READERS OF ANOTHER RUN'S ARTIFACT, AND NO THIRD: derive's consult
    # (a pull request's gate-verdict) and deploy-prod's nightly tooth (the
    # nightly-proof run's leak-proof record).
    holds "actions: read is held where the consult and the nightly tooth run, and nowhere else" "deploy-prod,derive" \
        "$(sed -n 's/^actions-holders=//p' "$shape")"
    holds "pull-requests: read is held where the consult runs, and nowhere else" "derive" \
        "$(sed -n 's/^pull-requests-holders=//p' "$shape")"
    holds "a git push anywhere in the workflow, outside a comment" "0" \
        "$(grep -vE '^\s*#' "$WORKFLOW" | grep -cE 'git +push' || true)"
    # HOUSE RULE 62, BY ITS OWN RUNNER, ON THIS FILE: every run step after an
    # exporter pins the exported names or says why.
    if (cd "$ROOT" && "$PY" quality/runners/workflow_credential_pins.py .github/workflows >"$r62" 2>"$r62.err"); then
        holds "rule 62's findings on the workflows" "0" "$(jq -r '.findings | length' "$r62" 2>/dev/null || echo '?')"
        holds "and it scanned run steps after an exporter (a floor, not a vacuous zero)" "yes" \
            "$(jq -r 'if .targets.run_steps_after_an_exporter >= 1 then "yes" else "no" end' "$r62" 2>/dev/null || echo '?')"
    else
        bad "rule 62's runner exited non-zero: $(sed -n 1p "$r62.err")"
    fi
}

# =============================================================================
# C2.1 — the deploy jobs: staging on a push to main, prod by dispatch
# =============================================================================
#
# Both jobs call `deploy/stage.sh` and nothing else deploys; the drive runs
# their `run:` blocks against a STUB `deploy/stage.sh` that records its argv one
# argument per line (so a sanction carrying spaces, quotes or `$(…)` is compared
# byte for byte), prints a closing line and exits as the case says. The real
# script's acts and every prod refusal are `deploy/tests/test_stage.sh`'s.

# plant_stage — the stub, into the current scratch tree.
plant_stage() {
    mkdir -p "$CASE_DIR/deploy"
    cat >"$CASE_DIR/deploy/stage.sh" <<'STAGESTUB'
#!/usr/bin/env bash
: >"$DJB_DRIVE_ARGV_LOG.stage"
for a in "$@"; do printf '%s\n' "$a" >>"$DJB_DRIVE_ARGV_LOG.stage"; done
printf 'ns=%s registry=%s\n' "${DJB_DEPLOY_NAMESPACE:-}" "${DJB_IMAGE_REGISTRY:-}" >"$DJB_DRIVE_ARGV_LOG.stage.env"
echo "stage: destination  $1"
[ -z "${DJB_DRIVE_STAGE_CLOSING:-}" ] || echo "$DJB_DRIVE_STAGE_CLOSING"
[ -z "${DJB_DRIVE_STAGE_REFUSAL:-}" ] || echo "!! stage: $DJB_DRIVE_STAGE_REFUSAL" >&2
exit "${DJB_DRIVE_STAGE_RC:-0}"
STAGESTUB
    chmod +x "$CASE_DIR/deploy/stage.sh"
}

stage_argv() { paste -sd'|' "$ARGV_LOG.stage" 2>/dev/null || true; }

DEPLOY_STAGING_GATE="$WORK/deploy-staging-target.sh"
DEPLOY_STAGING_RUN="$WORK/deploy-staging-stage.sh"
DEPLOY_PROD_GATE="$WORK/deploy-prod-target.sh"
DEPLOY_PROD_TREE="$WORK/deploy-prod-tree.sh"
DEPLOY_PROD_NIGHTLY="$WORK/deploy-prod-nightly.sh"
DEPLOY_PROD_RUN="$WORK/deploy-prod-promote.sh"
HAVE_DS_GATE=0 HAVE_DS_RUN=0 HAVE_DP_GATE=0 HAVE_DP_TREE=0 HAVE_DP_NIGHTLY=0 HAVE_DP_RUN=0
extract_run deploy-staging target "$DEPLOY_STAGING_GATE" && HAVE_DS_GATE=1
extract_run deploy-staging stage "$DEPLOY_STAGING_RUN" && HAVE_DS_RUN=1
extract_run deploy-prod target "$DEPLOY_PROD_GATE" && HAVE_DP_GATE=1
extract_run deploy-prod tree "$DEPLOY_PROD_TREE" && HAVE_DP_TREE=1
extract_run deploy-prod nightly "$DEPLOY_PROD_NIGHTLY" && HAVE_DP_NIGHTLY=1
extract_run deploy-prod promote "$DEPLOY_PROD_RUN" && HAVE_DP_RUN=1

# deploy_shape <job> — the job's own keys, and its steps in order, as lines the
# cases compare: `needs=`, `if=`, `perm:<k>=<v>`, `env-key`, `secrets-ref`, and
# one `step=<id>|<uses>|<if>` line per step.
deploy_shape() {
    "$PY" - "$WORKFLOW" "$1" <<'PYTHON'
import json, sys, yaml
doc = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
job = (doc.get("jobs") or {}).get(sys.argv[2])
if job is None:
    print("absent")
    raise SystemExit(0)
n = job.get("needs") or []
print("needs=" + ",".join([n] if isinstance(n, str) else n))
print("if=" + str(job.get("if")))
for k, v in sorted((job.get("permissions") or {}).items()):
    print(f"perm:{k}={v}")
print("environment=" + str(job.get("environment")))
print("secrets-ref=" + ("yes" if "secrets." in json.dumps(job) else "no"))
print("inputs-in-run=" + ("yes" if any("inputs." in str(s.get("run", "")) or "github.event.inputs" in str(s.get("run", "")) for s in job.get("steps") or []) else "no"))
for s in job.get("steps") or []:
    print("step={}|{}|{}".format(s.get("id", ""), str(s.get("uses", "")).split("@")[0], s.get("if", "")))
    if str(s.get("uses", "")).startswith("aws-actions/configure-aws-credentials@"):
        print("role=" + str((s.get("with") or {}).get("role-to-assume")))
    if "env" in s:
        for k, v in sorted(s["env"].items()):
            print(f"env:{s.get('id', '')}:{k}={v}")
PYTHON
}
shape_of() { sed -n "s/^$1//p" "$2" | sed -n 1p; }

case_deploy_staging_stands_behind_the_verdict_and_the_image() {
    local s="$WORK/ds-shape.txt"
    deploy_shape deploy-staging >"$s"
    if [ "$(cat "$s")" = "absent" ]; then
        bad "the workflow has no deploy-staging job — a merge to main deploys nothing"
        return 0
    fi
    holds "deploy-staging needs the verdict and the image" "verdict,images" "$(shape_of needs= "$s")"
    holds "it runs on a push to main and on nothing else" \
        "github.event_name == 'push' && github.ref == 'refs/heads/main'" "$(shape_of if= "$s")"
    holds "its grants: read the tree, mint the OIDC token — nothing else" \
        "perm:contents=read|perm:id-token=write" "$(grep '^perm:' "$s" | paste -sd'|' -)"
    holds "it declares no GitHub environment (the trust names the ref form)" "None" "$(shape_of environment= "$s")"
    holds "it reads no secret — its one credential is the OIDC role" "no" "$(shape_of secrets-ref= "$s")"
    holds "the stage variables decide first; every later step asks that answer" \
        "target||;|actions/checkout|steps.target.outputs.deploy == 'true';|aws-actions/configure-aws-credentials|steps.target.outputs.deploy == 'true';stage||steps.target.outputs.deploy == 'true'" \
        "$(grep '^step=' "$s" | sed 's/^step=//' | paste -sd';' -)"
    holds "the role it assumes is the product's deploy role" '${{ vars.AWS_DEPLOY_ROLE_ARN }}' "$(shape_of role= "$s")"
    holds "the stage target reaches the step as a variable" '${{ vars.DJB_STAGE_TARGET }}' "$(shape_of env:stage:TARGET= "$s")"
    holds "the namespace reaches stage.sh" '${{ vars.DJB_DEPLOY_NAMESPACE }}' "$(shape_of env:stage:DJB_DEPLOY_NAMESPACE= "$s")"
    holds "the registry reaches stage.sh" '${{ vars.DJB_IMAGE_REGISTRY }}' "$(shape_of env:stage:DJB_IMAGE_REGISTRY= "$s")"
}

case_deploy_staging_skips_with_a_notice_unless_the_product_names_a_stage() {
    if [ "$HAVE_DS_GATE" != "1" ]; then
        bad "deploy-staging has no 'target' step — nothing decides whether there is a stage box"
        return 0
    fi
    local knobs
    for knobs in "TARGET= ROLE=" "TARGET=ec2-user@stage ROLE=" "TARGET= ROLE=arn:aws:iam::1:role/x"; do
        fresh_derive
        # shellcheck disable=SC2086 # the knobs are words by design
        drive "the gate with ${knobs}" 0 -- block_run "$DEPLOY_STAGING_GATE" $knobs
        holds "deploy=false with ${knobs}" "false" "$(output_of deploy)"
        says "::notice::deploy-staging skipped"
    done
    fresh_derive
    block_run "$DEPLOY_STAGING_GATE" TARGET= ROLE=
    says "DJB_STAGE_TARGET AWS_DEPLOY_ROLE_ARN"
    fresh_derive
    drive "the gate with both variables set" 0 -- block_run "$DEPLOY_STAGING_GATE" \
        TARGET=ec2-user@stage ROLE=arn:aws:iam::1:role/x
    holds "deploy=true" "true" "$(output_of deploy)"
}

case_deploy_staging_runs_stage_sh_and_carries_its_exit_and_closing_line() {
    if [ "$HAVE_DS_RUN" != "1" ]; then
        bad "deploy-staging has no 'stage' step"
        return 0
    fi
    fresh_derive
    plant_stage
    drive "a stage that went live" 0 -- block_run "$DEPLOY_STAGING_RUN" TARGET=ec2-user@stage \
        DJB_DEPLOY_NAMESPACE=acme DJB_IMAGE_REGISTRY=1.dkr.ecr.us-east-1.amazonaws.com/acme \
        DJB_DRIVE_STAGE_CLOSING="stage: tree-0123456789ab live in 97s (migrate 4s)"
    holds "stage.sh's argv" "ec2-user@stage|--env|staging" "$(stage_argv)"
    holds "the namespace and registry reached it" "ns=acme registry=1.dkr.ecr.us-east-1.amazonaws.com/acme" \
        "$(cat "$ARGV_LOG.stage.env" 2>/dev/null)"
    says "stage-verdict: rc=0 stage: tree-0123456789ab live in 97s (migrate 4s)"
    local rc
    for rc in 1 2; do
        fresh_derive
        plant_stage
        drive "a stage that exited ${rc}" "$rc" -- block_run "$DEPLOY_STAGING_RUN" TARGET=ec2-user@stage \
            DJB_DEPLOY_NAMESPACE=acme DJB_IMAGE_REGISTRY=r DJB_DRIVE_STAGE_RC="$rc" \
            DJB_DRIVE_STAGE_REFUSAL="the registry does not have this tree's web image"
        says "stage-verdict: rc=${rc} no closing line"
        says "!! stage: the registry does not have this tree's web image"
    done
    fresh_derive
    plant_stage
    drive "a docs-only delta (exit 0, nothing went live)" 0 -- block_run "$DEPLOY_STAGING_RUN" \
        TARGET=ec2-user@stage DJB_DEPLOY_NAMESPACE=acme DJB_IMAGE_REGISTRY=r
    says "stage-verdict: rc=0 no closing line"
}

case_deploy_prod_is_a_dispatch_with_a_tree_and_a_sanction() {
    local s="$WORK/dp-shape.txt" on
    deploy_shape deploy-prod >"$s"
    on=$("$PY" - "$WORKFLOW" <<'PYTHON'
import sys, yaml
doc = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
on = doc.get("on", doc.get(True)) or {}
wd = on.get("workflow_dispatch") if isinstance(on, dict) else None
inputs = (wd or {}).get("inputs") or {}
print(",".join(f"{k}:{'required' if v.get('required') else 'optional'}:{v.get('type')}" for k, v in sorted(inputs.items())) or "none")
PYTHON
    )
    holds "the workflow takes a dispatch with two required string inputs" \
        "sanction:required:string,tree:required:string" "$on"
    if [ "$(cat "$s")" = "absent" ]; then
        bad "the workflow has no deploy-prod job — nothing promotes a staged tree"
        return 0
    fi
    holds "deploy-prod runs on a dispatch and on nothing else" "github.event_name == 'workflow_dispatch'" "$(shape_of if= "$s")"
    holds "it needs no job — the gate already measured the tree staging holds" "" "$(shape_of needs= "$s")"
    holds "its grants: read the tree, read the nightly's artifact, mint the OIDC token" \
        "perm:actions=read|perm:contents=read|perm:id-token=write" "$(grep '^perm:' "$s" | paste -sd'|' -)"
    holds "it declares no GitHub environment (the trust names the ref form)" "None" "$(shape_of environment= "$s")"
    holds "it reads no secret — its one credential is the OIDC role" "no" "$(shape_of secrets-ref= "$s")"
    holds "no dispatch input is spelled inside a run: block (they arrive as env)" "no" "$(shape_of inputs-in-run= "$s")"
    holds "the steps, in order: decide, check out, resolve the tree, read the nightly, assume, promote" \
        "target||;|actions/checkout|;tree||;nightly||;|aws-actions/configure-aws-credentials|;promote||" \
        "$(grep '^step=' "$s" | sed 's/^step=//' | paste -sd';' -)"
    holds "the role it assumes is the product's deploy role" '${{ vars.AWS_DEPLOY_ROLE_ARN }}' "$(shape_of role= "$s")"
    holds "the tree input reaches its step as env" '${{ inputs.tree }}' "$(shape_of env:tree:TREE= "$s")"
    holds "the sanction input reaches stage.sh as env" '${{ inputs.sanction }}' "$(shape_of env:promote:SANCTION= "$s")"
    holds "the nightly directory is the nightly step's" '${{ steps.nightly.outputs.dir }}' "$(shape_of env:promote:NIGHTLY_DIR= "$s")"
    holds "the prod target is the product's variable" '${{ vars.DJB_PROD_TARGET }}' "$(shape_of env:promote:PROD= "$s")"
    holds "the staging box it reads is the product's variable" '${{ vars.DJB_STAGE_TARGET }}' "$(shape_of env:promote:STAGE= "$s")"
}

case_deploy_prod_refuses_when_the_product_names_no_prod() {
    if [ "$HAVE_DP_GATE" != "1" ]; then
        bad "deploy-prod has no 'target' step"
        return 0
    fi
    local knobs
    for knobs in "PROD= STAGE=s ROLE=r REF=refs/heads/main" "PROD=p STAGE= ROLE=r REF=refs/heads/main" \
        "PROD=p STAGE=s ROLE= REF=refs/heads/main" "PROD=p STAGE=s ROLE=r REF=refs/heads/feature"; do
        fresh_derive
        # shellcheck disable=SC2086 # the knobs are words by design
        drive "the prod gate with ${knobs}" 2 -- block_run "$DEPLOY_PROD_GATE" $knobs
        says "nothing was promoted"
    done
    fresh_derive
    drive "the prod gate with every variable, on main" 0 -- block_run "$DEPLOY_PROD_GATE" \
        PROD=p STAGE=s ROLE=r REF=refs/heads/main
}

# tree_world — a repository whose main holds a code commit, then a docs-only
# commit on top (staging kept the code commit's tree), and a third tree that
# is only on a side branch; `origin/main` is planted as a runner's checkout has it.
tree_world() {
    fresh_repo
    mkdir -p "$CASE_DIR/deploy"
    cp deploy/provision.sh "$CASE_DIR/deploy/provision.sh"
    git -C "$CASE_DIR" add -A
    git -C "$CASE_DIR" commit -q -m code
    TW_CODE=$(git -C "$CASE_DIR" rev-parse HEAD)
    TW_CODE_TREE=$(git -C "$CASE_DIR" rev-parse 'HEAD^{tree}')
    echo docs >"$CASE_DIR/README.md"
    git -C "$CASE_DIR" add README.md
    git -C "$CASE_DIR" commit -q -m docs
    TW_DOCS=$(git -C "$CASE_DIR" rev-parse HEAD)
    git -C "$CASE_DIR" update-ref refs/remotes/origin/main "$TW_DOCS"
    git -C "$CASE_DIR" checkout -q -b side
    echo side >"$CASE_DIR/side.txt"
    git -C "$CASE_DIR" add side.txt
    git -C "$CASE_DIR" commit -q -m side
    TW_SIDE_TREE=$(git -C "$CASE_DIR" rev-parse 'HEAD^{tree}')
    git -C "$CASE_DIR" checkout -q "$TW_DOCS"
}

case_deploy_prod_checks_out_the_tree_staging_holds() {
    if [ "$HAVE_DP_TREE" != "1" ]; then
        bad "deploy-prod has no 'tree' step — it would promote the dispatch ref's tree, not staging's"
        return 0
    fi
    local form
    # A tree is content-addressed: the first world names the trees, and every
    # rebuilt world below carries the same ones.
    tree_world
    for form in "tree-${TW_CODE_TREE:0:12}" "${TW_CODE_TREE:0:12}" "$TW_CODE_TREE"; do
        tree_world
        drive "the tree input '${form:0:17}…' behind a docs-only head" 0 -- block_run "$DEPLOY_PROD_TREE" TREE="$form"
        holds "the checkout is the commit that carries staging's tree (${form:0:17}…)" "$TW_CODE" "$(git -C "$CASE_DIR" rev-parse HEAD)"
        holds "the tag the step published (${form:0:17}…)" "tree-${TW_CODE_TREE:0:12}" "$(output_of tag)"
    done
    for form in "" "tree-xyz" "tree-0123" "HEAD" "tree-${TW_CODE_TREE:0:12}; rm -rf /"; do
        tree_world
        drive "a tree input that is not a tree tag ('${form}')" 2 -- block_run "$DEPLOY_PROD_TREE" TREE="$form"
        holds "the checkout did not move ('${form}')" "$TW_DOCS" "$(git -C "$CASE_DIR" rev-parse HEAD)"
    done
    tree_world
    drive "a tree that main never held (a side branch's)" 2 -- block_run "$DEPLOY_PROD_TREE" TREE="tree-${TW_SIDE_TREE:0:12}"
    says "no commit on origin/main"
    holds "the checkout did not move" "$TW_DOCS" "$(git -C "$CASE_DIR" rev-parse HEAD)"
}

# A stub `gh` for the nightly step: `run list` answers FAKE_NIGHTLY_RUN (or
# fails when FAKE_GH_DOWN), `run download` writes a leak_proof.txt unless
# FAKE_NO_ARTIFACT.
plant_gh_nightly() {
    mkdir -p "$CASE_DIR.bin"
    cat >"$CASE_DIR.bin/gh" <<'GHSTUB'
#!/usr/bin/env bash
printf 'gh %s\n' "$*" >>"$DJB_DRIVE_ARGV_LOG.gh"
[ -z "${FAKE_GH_DOWN:-}" ] || { echo "stub gh: the API is down" >&2; exit 1; }
case "$1 ${2:-}" in
"run list")
    [ -z "${FAKE_NIGHTLY_RUN:-}" ] || printf '%s\n' "$FAKE_NIGHTLY_RUN"
    exit 0
    ;;
"run download")
    [ -z "${FAKE_NO_ARTIFACT:-}" ] || { echo "no artifact matches any of the names or patterns provided" >&2; exit 1; }
    dir=""
    while [ "$#" -gt 0 ]; do case "$1" in --dir) dir=$2; shift 2 ;; *) shift ;; esac; done
    mkdir -p "$dir"
    echo "schema=leak-proof/1 rc=0" >"$dir/leak_proof.txt"
    exit 0
    ;;
esac
echo "stub gh: unexpected call: $*" >&2
exit 1
GHSTUB
    chmod +x "$CASE_DIR.bin/gh"
}

case_deploy_prod_hands_stage_sh_the_latest_nightly() {
    if [ "$HAVE_DP_NIGHTLY" != "1" ]; then
        bad "deploy-prod has no 'nightly' step — the nightly tooth would read nothing"
        return 0
    fi
    local artifact
    artifact=$("$PY" - .github/workflows/nightly-proof.yml <<'PYTHON'
import sys, yaml
doc = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
for job in (doc.get("jobs") or {}).values():
    for s in job.get("steps") or []:
        if str(s.get("uses", "")).startswith("actions/upload-artifact@"):
            print((s.get("with") or {}).get("name", ""))
PYTHON
    )
    fresh_derive
    plant_gh_nightly
    drive "a completed nightly run with its artifact" 0 -- block_run "$DEPLOY_PROD_NIGHTLY" \
        PATH="$CASE_DIR.bin:$PATH" GH_TOKEN=drive GH_REPO=example/drive FAKE_NIGHTLY_RUN=4242
    holds "the directory handed on holds the record" "yes" \
        "$([ -s "$(output_of dir)/leak_proof.txt" ] && echo yes || echo no)"
    holds "it asked for the nightly workflow's latest completed run on main" "1" \
        "$(grep -c -- 'run list --workflow nightly-proof.yml --branch main --status completed' "$ARGV_LOG.gh" || true)"
    holds "and downloaded the artifact nightly-proof.yml publishes (${artifact})" "1" \
        "$(grep -c -- "run download 4242 --name ${artifact} " "$ARGV_LOG.gh" || true)"

    fresh_derive
    plant_gh_nightly
    drive "no completed nightly run" 0 -- block_run "$DEPLOY_PROD_NIGHTLY" \
        PATH="$CASE_DIR.bin:$PATH" GH_TOKEN=drive GH_REPO=example/drive FAKE_NIGHTLY_RUN=
    holds "nothing handed on — stage.sh reads nightly:none and refuses" "" "$(output_of dir)"
    grep -q '^dir=' "$OUTPUT_FILE" && ok "the empty dir output is written, never absent" ||
        bad "no dir= output — the promote step would read an unset value"

    fresh_derive
    plant_gh_nightly
    drive "a run whose artifact is gone" 0 -- block_run "$DEPLOY_PROD_NIGHTLY" \
        PATH="$CASE_DIR.bin:$PATH" GH_TOKEN=drive GH_REPO=example/drive FAKE_NIGHTLY_RUN=4242 FAKE_NO_ARTIFACT=1
    holds "an empty directory is handed on — stage.sh refuses it as unreadable, never as none" "no" \
        "$(d=$(output_of dir); [ -n "$d" ] && [ -d "$d" ] && [ -e "$d/leak_proof.txt" ] && echo yes || echo no)"
    holds "and it is a directory that exists" "yes" "$(d=$(output_of dir); [ -n "$d" ] && [ -d "$d" ] && echo yes || echo no)"

    fresh_derive
    plant_gh_nightly
    drive "GitHub could not be asked" 2 -- block_run "$DEPLOY_PROD_NIGHTLY" \
        PATH="$CASE_DIR.bin:$PATH" GH_TOKEN=drive GH_REPO=example/drive FAKE_GH_DOWN=1
    says "could not ask GitHub"
}

case_deploy_prod_runs_stage_sh_with_the_four_teeth_inputs() {
    if [ "$HAVE_DP_RUN" != "1" ]; then
        bad "deploy-prod has no 'promote' step"
        return 0
    fi
    # A SANCTION IS OPERATOR TEXT: spaces, quotes and a command substitution
    # arrive at stage.sh as ONE argument, byte for byte, and nothing runs.
    local sanction="Ana O'Neil: \"ship\" \$(touch pwned) \`id\` & more"
    fresh_derive
    plant_stage
    drive "a promotion that went live" 0 -- block_run "$DEPLOY_PROD_RUN" PROD=ec2-user@prod STAGE=ec2-user@stage \
        SANCTION="$sanction" NIGHTLY_DIR=/tmp/nightly DJB_DEPLOY_NAMESPACE=acme DJB_IMAGE_REGISTRY=r \
        DJB_DRIVE_STAGE_CLOSING="stage: tree-0123456789ab live in 120s (migrate skipped)"
    holds "stage.sh's argv" "ec2-user@prod|--env|prod|--sanction|${sanction}|--staging|ec2-user@stage|--nightly|/tmp/nightly" "$(stage_argv)"
    holds "the sanction's command substitution never ran" "no" "$([ -e "$CASE_DIR/pwned" ] && echo yes || echo no)"
    says "stage-verdict: rc=0 stage: tree-0123456789ab live in 120s (migrate skipped)"
    fresh_derive
    plant_stage
    drive "an empty nightly directory is passed as an empty argument, never dropped" 2 -- block_run "$DEPLOY_PROD_RUN" \
        PROD=ec2-user@prod STAGE=ec2-user@stage SANCTION="a: b" NIGHTLY_DIR= DJB_DEPLOY_NAMESPACE=acme \
        DJB_IMAGE_REGISTRY=r DJB_DRIVE_STAGE_RC=2 DJB_DRIVE_STAGE_REFUSAL="REFUSED — nightly: nightly:none"
    holds "stage.sh's argv" "ec2-user@prod|--env|prod|--sanction|a: b|--staging|ec2-user@stage|--nightly|" "$(stage_argv)"
    says "stage-verdict: rc=2 no closing line"
}

case_a_dispatch_runs_no_gate() {
    # A PROMOTION IS NOT A MEASUREMENT. The dispatch that runs deploy-prod must
    # not re-run the gate over the dispatch ref (a second measurement of a tree
    # the record already names), nor let `verdict`/`gate-verdict` — both
    # `always()` — publish a red record for a run that measured nothing. And a
    # dispatch on main must not share the push-to-main concurrency group, where
    # a queued run cancels the pending one: a prod promotion would cancel a
    # merge's gate, or be cancelled by it.
    local s="$WORK/dispatch.txt"
    "$PY" - "$WORKFLOW" >"$s" <<'PYTHON'
import sys, yaml
doc = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
jobs = doc.get("jobs") or {}
for j in ("derive", "verdict", "gate-verdict"):
    print(f"{j}=" + str((jobs.get(j) or {}).get("if")))
print("group=" + str((doc.get("concurrency") or {}).get("group")))
print("cancel=" + str((doc.get("concurrency") or {}).get("cancel-in-progress")))
PYTHON
    holds "derive stands down on a dispatch" "github.event_name != 'workflow_dispatch'" "$(shape_of derive= "$s")"
    holds "verdict runs always, except on a dispatch" "always() && github.event_name != 'workflow_dispatch'" "$(shape_of verdict= "$s")"
    holds "gate-verdict runs always, except on a dispatch" "always() && github.event_name != 'workflow_dispatch'" "$(shape_of gate-verdict= "$s")"
    holds "a dispatch has its own concurrency group" \
        "gate-\${{ github.workflow }}-\${{ github.event_name == 'workflow_dispatch' && 'dispatch' || github.ref }}" \
        "$(shape_of group= "$s")"
    # AND A DISPATCH NEVER CANCELS ONE IN FLIGHT. Every dispatch shares that
    # group, so a cancel-in-progress keyed on the ref alone would let a
    # dispatch from any branch cancel a prod promotion from main mid-act —
    # the job-level `cancel-in-progress: false` does not reach the workflow's.
    holds "cancel-in-progress is never true on a dispatch" \
        "\${{ github.event_name != 'workflow_dispatch' && github.ref != 'refs/heads/main' }}" \
        "$(shape_of cancel= "$s")"
}

case_rule_62_judges_the_deploy_steps() {
    # PLANT-VERIFY, BOTH DIRECTIONS: the stage and promote steps run after the
    # deploy role's exporter, so rule 62 must JUDGE them — strip their `# creds:`
    # valves in a copy and the runner names both; the real file is clean (the
    # shape case above).
    # The runner reads its declaration from `quality/rules.yaml` under its cwd
    # and names files relative to it, so the plant gets a root of its own
    # holding a copy of that declaration — never a file inside this checkout.
    local plant="$WORK/r62plant" r62="$WORK/r62plant.json"
    rm -rf "$plant"
    mkdir -p "$plant/quality" "$plant/wf"
    cp quality/rules.yaml "$plant/quality/rules.yaml"
    "$PY" - "$WORKFLOW" "$plant/wf/ci.yml" <<'PYTHON'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
out, job = [], ""
for line in text.splitlines(keepends=True):
    m = re.match(r"^  ([a-z][a-z-]*):\s*$", line)
    if m:
        job = m.group(1)
    if job in ("deploy-staging", "deploy-prod") and re.search(r"#\s*creds:", line):
        continue
    out.append(line)
open(sys.argv[2], "w", encoding="utf-8").write("".join(out))
PYTHON
    if (cd "$plant" && "$PY" "$ROOT/quality/runners/workflow_credential_pins.py" wf >"$r62" 2>"$r62.err"); then
        holds "with the valves stripped, rule 62 names deploy-staging's stage step" "1" \
            "$(jq -r '[.findings[] | select(.msg | contains("job deploy-staging, step") and contains("unset"))] | length' "$r62" 2>/dev/null || echo '?')"
        holds "and deploy-prod's promote step" "1" \
            "$(jq -r '[.findings[] | select(.msg | contains("job deploy-prod, step") and contains("unset"))] | length' "$r62" 2>/dev/null || echo '?')"
    else
        bad "rule 62's runner exited non-zero on the plant: $(sed -n 1p "$r62.err")"
    fi
}

case_derive_asks_the_gate_for_the_ci_listing
case_the_real_listing_becomes_the_measured_matrix
case_a_listing_becomes_rows_by_its_own_columns
case_a_listing_the_matrix_cannot_honour_is_refused
case_a_refusing_listing_fails_the_job_with_no_fallback
case_the_seed_is_minted_once
case_the_row_invokes_the_gate_and_nothing_else
case_every_row_writes_its_walls_and_uploads_them
case_the_workflow_types_no_unit_name_of_its_own
case_the_record_is_the_measured_tree_and_every_field
case_a_red_or_cancelled_job_is_rc_1_and_a_narrowed_pr_says_so
case_an_honoured_push_writes_no_record
case_an_honoured_push_measures_nothing
case_a_push_nothing_honours_measures_in_full
case_the_verdict_honours_only_an_honour
case_the_wiring_between_the_jobs
case_the_shape_of_the_workflow
case_deploy_staging_stands_behind_the_verdict_and_the_image
case_deploy_staging_skips_with_a_notice_unless_the_product_names_a_stage
case_deploy_staging_runs_stage_sh_and_carries_its_exit_and_closing_line
case_deploy_prod_is_a_dispatch_with_a_tree_and_a_sanction
case_deploy_prod_refuses_when_the_product_names_no_prod
case_deploy_prod_checks_out_the_tree_staging_holds
case_deploy_prod_hands_stage_sh_the_latest_nightly
case_deploy_prod_runs_stage_sh_with_the_four_teeth_inputs
case_a_dispatch_runs_no_gate
case_rule_62_judges_the_deploy_steps

drive_finished
echo "test_ci_derive: ${PASSED} passed · ${FAILED} failed"
if [ "$FAILED" -gt 0 ]; then
    echo "!! a property of the workflow did not hold: it measures a tree once, as the" >&2
    echo "   gate's own listing says, records that measurement in the one grammar the" >&2
    echo "   push reads, and honours it once on main." >&2
    exit 1
fi
exit 0
