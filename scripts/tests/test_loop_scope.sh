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
#
# TWO TESTS, because on macOS `/bin/sh` IS bash: BASH_VERSION is set under
# `sh x.sh` and only POSIX MODE tells the two apart (SHELLOPTS carries
# `posix`). On Linux `/bin/sh` is dash and the first test is the one that
# fires. Neither test alone covers both machines.
#
# A SOURCED library must never carry this. There the interpreter is the
# caller's ON PURPOSE and an `exit` would kill the caller's shell — the
# argument is scripts/db.sh's, at scripts/db.sh:50-57, and it is why db.sh is
# the one executable in this tree deliberately without a belt.
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
# drives: .gitignore apps/ config/ deploy/tests docs/product/instruments.md pyproject.toml quality/ scripts/archaeology_lib.sh scripts/check.sh scripts/db.sh scripts/gate_lease.sh scripts/gate_ledger.sh scripts/gate_refuse.sh scripts/kill_mine.sh scripts/loop_tier.sh scripts/queue_cited.sh scripts/secrets_scan.sh scripts/sweep.sh scripts/test.sh scripts/tests/test_gate_lease.sh scripts/tests/test_loop_ledger.sh scripts/tests/test_pipefail_readers.sh scripts/tests/test_sweep.sh
# cites: scripts/test_impact.py scripts/test_impact.json .env.example

# The drive for the `--loop` SCOPE — `scripts/loop_tier.sh`'s fan-out decision
# table, its reverse-transitive `depends_on` closure, its refusals, and the
# always-on set that keeps the narrowing sound (`apps/conftest.py`).
#
#   ./scripts/tests/test_loop_scope.sh          run every case
#   ./scripts/tests/test_loop_scope.sh --list   name them
#
# WHY IT EXISTS. A scope is a claim that everything it deselected could not have
# been broken by the active rung. Every way that claim goes wrong is SILENT and looks
# like speed: a table row that quietly classifies a new territory as inert, a
# closure that stops walking one hop early, an always-on derivation that returns
# nothing and takes the whole cross-app population out with it. A green narrowed
# `--loop` looks identical in all four cases. So each of them is a case here,
# and each is asserted in BOTH directions — a table that only ever answers
# "full" passes every positive case ever written for it.
#
# THE PLANTED-MISS TRIPLE (case_the_planted_miss_triple) is the one that decides
# whether the active rung ships. It plants a real undeclared cross-app coupling, breaks
# it, and pastes three verdicts: today's selection RED, the scoped selection
# GREEN — the honest miss, shown rather than argued — and THE BANK'S selection
# RED. The third is the load-bearing one: the narrowing is only a deferral if the
# wave bank still catches what the rung deselected.
#
# WHY THE PLANT IS A PRODUCT APP. On this tree every app under `apps/` is a
# PLATFORM app (`quality/partition.yaml`'s `platform_apps`), and a platform app's
# tests are exactly what the partition SKIPS when the closure is unchanged — so a
# platform-app plant would be invisible to verdict (c) for a reason that has
# nothing to do with the scope. The drive therefore CREATES a throwaway product
# app in its scratch checkout — a directory with an `apps.py` and no entry in
# `platform_apps` — and re-derives that qualifying condition from
# `partition.yaml` at run time rather than trusting this sentence.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * The undeclared BEHAVIOURAL coupling that is not an import — a DB row, a
#     seeded fixture, an event payload consumed without importing `events.py`.
#     The plant here is an import-shaped coupling because that is the shape a
#     drive can build and break deterministically. The behavioural one surfaces
#     at the wave bank, and the scope banner's standing trade sentence is its
#     disclosure.
#   * Whether a floor's MEMBERS are still doing their job. The layer-2 floors
#     count named populations; a census gutted in place keeps its count. The
#     full gate's canary self-test and review are the cover, and this drive does
#     not pretend to be one.
#   * `pyproject.toml`'s pytest ini options, whose whole-suite blast radius is
#     the declared blind spot `scripts/loop_tier.sh` argues. The case below pins
#     that it derives NO widening — which is the decision, asserted, not a hole
#     left open.
#   * A COMPLETE `--pr` RUN. `--pr --base <sha>` is the full gate with its two
#     pytest passes narrowed, so running one end to end takes the machine's one
#     exclusive lease — and this drive runs INSIDE a full gate that is already
#     holding it. The cases therefore drive everything `--pr` DECIDES (its
#     refusals, through the real `scripts/check.sh`; its fork point and scope,
#     through the real derivation; its pass flags, through the real builder) and
#     pin the rest by the text of the file: no leg added, one variable reaching
#     both passes, neither ledger writer reachable. The one end-to-end run is
#     the verifier's, under a typed sanction.
#   * The real `-n` invocation is exercised where the property IS the parallel
#     run and nowhere else: the always-on set's survival across workers, the
#     worker count with the documented knob set, and the three cases that drive
#     the full gate's own pytest leg body. Everywhere else the counts are read
#     from state a case built once, because measuring the leg you ship costs a
#     real xdist run and a drive that paid for one per case would be a drive
#     nobody runs.
#   * A COLLECTOR THAT DIES AFTER WRITING ITS COUNTS FILE AND BEFORE RUNNING ITS
#     TESTS. The reconciliation counts files, so that collector is present and
#     the population is whole; pytest's own exit status and the `no tests ran`
#     mapping are the only tell, and neither is driven here. Declared rather
#     than discovered.
#   * HOW `--pr` DERIVES its narrowing, in the `--pr` half of the leg-body cases:
#     those drive the COMPOSITION (the preflight's counts directory reaching both
#     passes and the refusal binding above the narrowed-run note) over a fixed
#     scope. The derivation is case_pr_narrows_pytest_and_nothing_else's.

set -euo pipefail

cd "$(dirname "$0")/../.."

# --- the drive preamble, and it comes before the first git command -----------
# An inherited absolute `GIT_DIR` overrides `-C`, and the cases below build
# throwaway repositories exactly the way the drive that escaped did.
[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_loop_scope: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It carries the only thing keeping this drive's git commands inside its" >&2
    echo "   own scratch directory. Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh

# Section 5 of the preamble, opted into. On bash 3.2 a `set -u` death hands the
# EXIT trap a status of 0, so a drive that dies halfway reads as a PASS.
DRIVE_OPTED_IN_TO_FINISH=1

PASSED=0
FAILED=0

cannot_look() {
    echo "!! test_loop_scope: $*" >&2
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
    echo "!! unknown argument '$1': test_loop_scope.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

command -v git >/dev/null 2>&1 || cannot_look "no git on PATH"
[ -f scripts/loop_tier.sh ] || cannot_look "scripts/loop_tier.sh is not in this tree"
[ -f scripts/secrets_scan.sh ] || cannot_look "scripts/secrets_scan.sh is not in this tree"
[ -f apps/conftest.py ] || cannot_look "apps/conftest.py is not in this tree"
[ -f config/settings/discovery.py ] ||
    cannot_look "config/settings/discovery.py is gone — the closure reads the app declarations through it"
[ -f quality/partition.yaml ] || cannot_look "quality/partition.yaml is not in this tree"

ROOT="$PWD"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || cannot_look "no $PY — the closure and the always-on derivation both need this checkout's venv"

# The real files, sourced, in the order check.sh sources them.
# shellcheck source=scripts/secrets_scan.sh
. scripts/secrets_scan.sh
# shellcheck source=scripts/loop_tier.sh
. scripts/loop_tier.sh
command -v loop_tier_own_apps >/dev/null 2>&1 ||
    cannot_look "scripts/loop_tier.sh defines no loop_tier_own_apps — the mapping is gone"
command -v loop_scope__classify >/dev/null 2>&1 ||
    cannot_look "scripts/loop_tier.sh defines no loop_scope__classify — the decision table is gone"
command -v loop_scope__closure >/dev/null 2>&1 ||
    cannot_look "scripts/loop_tier.sh defines no loop_scope__closure — the widening is gone"
command -v loop_scope__pytest_args >/dev/null 2>&1 ||
    cannot_look "scripts/loop_tier.sh defines no loop_scope__pytest_args — the flags the two passes are pointed at are gone"
command -v loop_scope__prerun_absence >/dev/null 2>&1 ||
    cannot_look "scripts/loop_tier.sh defines no loop_scope__prerun_absence — an absent pre-run banner would be silent again"
command -v loop_scope__impact >/dev/null 2>&1 ||
    cannot_look "scripts/loop_tier.sh defines no loop_scope__impact — the test-impact map would be consulted by nobody, and every loop would be the closure scope with no line saying so"
# The worker-ceiling cases ask this box the same question the gate asks it: one
# derivation, in the file that owns it, rather than a number typed into a drive.
[ -f scripts/gate_lease.sh ] || cannot_look "scripts/gate_lease.sh is not in this tree — the slot share has no derivation"
# shellcheck source=scripts/gate_lease.sh
. scripts/gate_lease.sh
command -v gate_slot_workers >/dev/null 2>&1 ||
    cannot_look "scripts/gate_lease.sh defines no gate_slot_workers — the share the clamp and the refusal both name is gone"
command -v gate_slots_total >/dev/null 2>&1 ||
    cannot_look "scripts/gate_lease.sh defines no gate_slots_total — the slot count the share divides by is gone"
command -v gate_slot_worker_count >/dev/null 2>&1 ||
    cannot_look "scripts/gate_lease.sh defines no gate_slot_worker_count — the ONE derivation of the gate's -n is gone, and a typed DJB_GATE_SLOT_WORKERS would be honoured by pytest and not by the gate again"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-loop-scope-drive.XXXXXX")" ||
    cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'chmod -R u+rwX "$WORK" 2>/dev/null || true; rm -rf "$WORK"'

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
    if [ -n "$OUT" ] && [ -f "$OUT" ]; then
        sed 's/^/             | /' "$OUT" | tail -25
    fi
    FAILED=$((FAILED + 1))
}
is() {
    local got="$1" want="$2" what="$3"
    if [ "$got" = "$want" ]; then
        ok "${what} is '${want}'"
    else
        bad "${what}: wanted '${want}', got '${got}'"
    fi
}
# THE FLOOR UNDER EVERY `$OUT` READER. `says` over an empty capture is a red
# that blames the subject for a run that never happened, and the `grep -q`
# NEGATIVES scattered through this file are `ok` over one. The shared shape is
# `drive_capture_refusal` (drive_preamble.sh section 7); this is the voice.
capture_floor() {
    local why
    why="$(drive_capture_refusal "${CURRENT:-a case}" "${OUT:-}" "${RC:-<none>}")" &&
        cannot_look "$why"
    return 0
}
says() {
    capture_floor
    if grep -qF -- "$1" "$OUT"; then
        ok "says \"$1\""
    else
        bad "does not say \"$1\""
    fi
}
notes_say() {
    case "$LOOP_SCOPE_NOTES" in
    *"$1"*) ok "the printed note says \"$1\"" ;;
    *) bad "the printed note does not say \"$1\" — it says '${LOOP_SCOPE_NOTES}'" ;;
    esac
}
reason_says() {
    case "$LOOP_TIER_REASON" in
    *"$1"*) ok "the printed reason says \"$1\"" ;;
    *) bad "the printed reason does not say \"$1\" — it says '${LOOP_TIER_REASON}'" ;;
    esac
}

# cause_recorded <substring> — the refusal RECORDED its first line (B4.2).
#
# `scope_in` runs `loop_tier_own_apps` in THIS shell rather than a subshell
# (see its own comment), so the global `gate_refuse` sets survives the call and this
# assertion can read it. What it proves is the half a text assertion cannot: the
# banner in scripts/check.sh that follows this callee will print the cause rather
# than `(the callee set none …)`.
cause_recorded() {
    local want="$1" what="$CURRENT"
    CURRENT="${what}: the refusal RECORDED its cause"
    case "${GATE_LAST_REFUSAL:-}" in
    "")
        bad "GATE_LAST_REFUSAL is empty — the banner above this callee would have to say the callee set none"
        ;;
    *"$want"*) ok "cause: ${GATE_LAST_REFUSAL}" ;;
    *) bad "the recorded cause does not say \"${want}\" — it says '${GATE_LAST_REFUSAL}'" ;;
    esac
    CURRENT="$what"
}

# --- the scratch world -------------------------------------------------------
#
# A checkout whose `apps/` carries REAL `AppConfig` declarations, because the
# closure reads declarations rather than a list and a fake graph would prove
# nothing about the reader. The graph below is deliberately NOT this tree's: a
# drive that asserted on the template's own app names would go red the day
# somebody adds an app, and would be asserting on the tree rather than on the
# walk.
#
#   core   <- (nothing)
#   mid    <- core
#   leaf   <- mid
#   aside  <- core
#
# So the reverse closure of `core` is everything, of `mid` is {mid, leaf} — the
# TRANSITIVE case, which is the one a one-hop widening gets wrong — and of
# `leaf` is {leaf}.
REPO=""
app_config() {
    local dir=$1 label=$2 deps=$3 upper
    # `${label^}` is bash 4 and macOS ships bash 3.2 — where it is not a no-op
    # but a "bad substitution" that kills the drive mid-case. Measured here.
    upper=$(printf '%s' "$label" | awk '{print toupper(substr($0, 1, 1)) substr($0, 2)}')
    mkdir -p "$dir/apps/$label"
    : >"$dir/apps/$label/__init__.py"
    {
        echo "from django.apps import AppConfig"
        echo ""
        echo ""
        echo "class ${upper}Config(AppConfig):"
        echo "    name = \"apps.${label}\""
        echo "    depends_on: tuple[str, ...] = (${deps})"
    } >"$dir/apps/$label/apps.py"
}

fresh_checkout() {
    N=$((N + 1))
    REPO="${WORK}/checkout${N}"
    drive_require_scratch REPO "${REPO:-}"
    mkdir -p "$REPO"
    git -C "$REPO" init -q
    git -C "$REPO" symbolic-ref HEAD refs/heads/main
    git -C "$REPO" config user.email drive@example.invalid
    git -C "$REPO" config user.name "loop scope drive"
    mkdir -p "$REPO/config" "$REPO/quality" "$REPO/scripts/tests" "$REPO/frontend/src" \
        "$REPO/docs" "$REPO/templates"
    app_config "$REPO" core ""
    app_config "$REPO" mid '"core",'
    app_config "$REPO" leaf '"mid",'
    app_config "$REPO" aside '"core",'
    # EVERY FILE A CASE WILL LATER "CHANGE" MUST EXIST IN THE BASE COMMIT. An
    # untracked never-staged file is invisible to `secrets_scan_changed_files`,
    # and a case that arranged its subject that way would pass for the wrong
    # reason for ever.
    echo "base" >"$REPO/README.md"
    echo "base" >"$REPO/config/settings.py"
    echo "base" >"$REPO/quality/rules.yaml"
    echo "base" >"$REPO/frontend/src/app.tsx"
    # THE FIXTURE'S DOCS PATH IS ASSEMBLED, NEVER SPELLED. This drive SHIPS
    # (bucket R3) and `publish.sh`'s `dangling-docs` leg reads every
    # `docs/**.md` string in the artifact as a POINTER — so a scratch fixture
    # spelled in full is a pointer at a file the published tree has never had.
    # Same idiom and same reason as `scripts/archaeology_lib.sh`'s assembled
    # bucket globs: name it in halves no pattern can join.
    _docs=docs
    echo "base" >"$REPO/${_docs}/note.md"
    echo "base" >"$REPO/templates/base.html"
    echo "base" >"$REPO/pyproject.toml"
    echo "base" >"$REPO/apps/conftest.py"
    echo "base" >"$REPO/apps/test_root.py"
    echo "base" >"$REPO/scripts/tests/test_thing.sh"
    echo "base" >"$REPO/scripts/loop_tier.sh"
    echo "base" >"$REPO/scripts/check.sh"
    echo "base" >"$REPO/apps/mid/services.py"
    echo "base" >"$REPO/apps/leaf/services.py"
    echo "base" >"$REPO/apps/aside/services.py"
    echo "base" >"$REPO/apps/core/models.py"
    # THE TESTS-ONLY ROW'S SUBJECTS, in the base commit for the reason the
    # comment above gives: an untracked never-staged file is invisible to the
    # changed-file set, and a case that arranged its subject that way would pass
    # for the wrong reason for ever. `apps/mid/conftest.py` is the APP-ROOT
    # conftest — an ordinary touch, not tests-only — and it sits beside
    # `apps/mid/tests/conftest.py`, which is inside the test tree and IS.
    mkdir -p "$REPO/apps/mid/tests" "$REPO/apps/core/tests" "$REPO/apps/core/migrations"
    echo "base" >"$REPO/apps/mid/conftest.py"
    echo "base" >"$REPO/apps/mid/tests/test_thing.py"
    echo "base" >"$REPO/apps/mid/tests/conftest.py"
    echo "base" >"$REPO/apps/core/tests/test_core_thing.py"
    echo "base" >"$REPO/apps/core/migrations/0001_initial.py"
    echo "base" >"$REPO/apps/core/services.py"
    git -C "$REPO" add -A
    git -C "$REPO" commit -q -m "base"
}

# Run the sourced function inside a checkout, keeping the variables it exports.
# A subshell would throw them away, which is what the cases assert on.
scope_in() {
    local dir="$1" here
    CURRENT="$2"
    N=$((N + 1))
    OUT="${WORK}/scope${N}.log"
    here="$PWD"
    cd "$dir"
    RC=0
    loop_tier_own_apps >"$OUT" 2>&1 || RC=$?
    cd "$here"
}

touch_and_scope() {
    local dir="$1" name="$2"
    shift 2
    local f
    for f in "$@"; do
        mkdir -p "$dir/$(dirname "$f")"
        echo "changed" >>"$dir/$f"
    done
    scope_in "$dir" "$name"
}

# --- the scope a collapsed checkout cannot derive for itself -----------------
#
# A VERIFIER BOX HOLDS A DEPTH-1 MIRROR: the wrapper pushes `HEAD:refs/heads/main`
# into a shallow checkout, so over there HEAD, `refs/heads/main` and the
# merge-base of the two are ONE commit. `secrets_scan_changed_files` reads that
# exactly as it reads `main` itself — uncommitted changes only, and there are
# none — and this mapping over it therefore derives an EMPTY scope for a rung
# that touched an app. Measured on the first off-box gate run: `the merge-base
# IS this HEAD … the scope is EMPTY`. The verdict banked over there is honest
# (its key carries its own scope) and "the box ran the same --loop" is not true.
#
# THE FIX IS ONE FORK POINT, CARRIED. The wrapper sends the rung's merge-base as
# `refs/djb/base` in the same pack and names it in `DJB_LOOP_SCOPE_BASE`; the ONE
# derivation honours it when its own history reaches nothing. What this case
# adds over `test_secrets_scan.sh`'s is the half this file owns: that the SCOPE
# — the app labels, the closure, the canonical string the ledger keys on — comes
# out the same as it does on the machine that has the history.
collapsed_clone() {
    local src="$1" dst="$2"
    git clone -q --depth 1 --branch rung "file://${src}" "$dst" 2>/dev/null || return 1
    git -C "$dst" branch -q -f main HEAD
    git -C "$dst" checkout -q main
    return 0
}

case_a_collapsed_checkout_derives_the_same_scope_when_the_base_is_carried() {
    fresh_checkout
    local src="$REPO" base box
    # A RUNG THAT TOUCHED AN APP, COMMITTED — which is what a box receives and
    # what every case above arranges as an uncommitted edit instead.
    git -C "$src" checkout -q -b rung
    echo "the rung's own work" >>"$src/apps/mid/services.py"
    git -C "$src" add -A
    git -C "$src" commit -q -m "rung work in mid"
    base="$(git -C "$src" merge-base rung main)"

    # WHAT THE MACHINE WITH THE HISTORY SAYS, first, so the box has something to
    # be compared against rather than a number typed here.
    scope_in "$src" "the rung's own checkout, which has the history"
    local want_apps="$LOOP_SCOPE_APPS" want_touched="$LOOP_SCOPE_TOUCHED" want_canonical="$LOOP_SCOPE_CANONICAL"
    is "$RC" "0" "the exit status on the checkout that has the history"
    is "$want_touched" "mid" "the touched set here"

    box="${WORK}/box${N}"
    collapsed_clone "$src" "$box" ||
        cannot_look "could not build a depth-1 clone — the box's shape cannot be driven here"

    # THE RED, KEPT AS A CASE: with no base handed over, the box's scope is
    # empty for a rung that changed an app's services.
    scope_in "$box" "a depth-1 box checkout with no base handed to it"
    is "$RC" "0" "the exit status on the collapsed checkout"
    is "$LOOP_SCOPE_TOUCHED" "" "the touched set with nothing carried"
    is "$LOOP_SCOPE_APPS" "" "the scope with nothing carried"

    # THE REF THE WRAPPER SENDS, planted the way the wrapper sends it: the base
    # COMMIT has to be on the box, because a sha it does not have is a sha it
    # cannot diff against.
    git -C "$src" update-ref refs/djb/base "$base"
    git -C "$box" fetch -q --depth 1 "file://${src}" "+refs/djb/base:refs/djb/base" 2>/dev/null ||
        cannot_look "could not plant refs/djb/base in the box clone"

    DJB_LOOP_SCOPE_BASE=refs/djb/base scope_in "$box" "a depth-1 box checkout with the fork point carried"
    is "$RC" "0" "the exit status with the base carried"
    is "$LOOP_SCOPE_TOUCHED" "$want_touched" "the touched set — the same as the machine that has the history"
    is "$LOOP_SCOPE_APPS" "$want_apps" "the derived scope — the same"
    # THE CANONICAL STRING IS WHAT THE LOOP LEDGER KEYS ON. Two runs that
    # measured the same thing must key the same, or a verdict banked on one is
    # not readable by the other.
    is "$LOOP_SCOPE_CANONICAL" "$want_canonical" "the canonical scope string the ledger keys on"
    case "$LOOP_TIER_BASIS" in
    *"CARRIED fork point"*) ok "and the banner says the basis was handed to it rather than derived" ;;
    *) bad "the basis does not say it was carried — it says '${LOOP_TIER_BASIS}'" ;;
    esac
}

# --- the fan-out decision table, one case per row ----------------------------

case_a_core_touch_reaches_every_app_through_the_closure_alone() {
    fresh_checkout
    touch_and_scope "$REPO" "apps/core -> the closure reaches every app" apps/core/models.py
    is "$RC" "0" "the exit status"
    is "$LOOP_TIER_MODE" "fast" "the mode"
    is "$LOOP_SCOPE_TOUCHED" "core" "the touched set"
    is "$LOOP_SCOPE_APPS" "aside core leaf mid" "the derived scope"
    is "$LOOP_SCOPE_WIDENED" "aside leaf mid" "the widening"
    # THE SPLIT, ASSERTED. The closure decides what is not deselected; it does
    # NOT promote every app it reaches to "run in full". Collapsed into one
    # list, an `apps/core` touch runs every organ test in the tree — slower than
    # the tier this replaced, which is the opposite of the point.
    is "$LOOP_TIER_OWN_APPS" "core" "the own-app list (the TOUCHED apps only)"
    # NO SPECIAL CASE IN CODE. `core` reaches everything because everything
    # declares it, not because a line in the table says `core` is special.
    #
    # READ AS CODE, WITH COMMENTS STRIPPED FIRST — the same weaker-but-honest
    # read `test_verify_start.sh` makes for the same reason. The file EXPLAINS
    # the core case at length, and a grep that could not tell the explanation
    # from the act would make the explanation unwritable. Measured: this
    # assertion went red on its own subject's prose.
    #
    # THE READER IS ONE `awk` OVER THE FILE, AND IT USED TO BE A PIPELINE ENDING
    # IN `grep -q` — which is this repository's own documented trap
    # (`scripts/tests/test_pipefail_readers.sh`, `test_gate_lease.sh`'s
    # no-pipeline note) and which made THIS case report a green over a real hit.
    # `grep -q` exits at the first match and kills `sed` with SIGPIPE; under
    # `set -o pipefail` the pipeline's status is then 141, the `if` takes the
    # ELSE branch, and the case prints `ok` about a file that names an app. It
    # only bites once the producer's output passes the 64 KiB pipe buffer, so it
    # arrived silently the day `loop_tier.sh` grew past it: measured on this
    # tree at 58 KB of source, the shipped reader answered `ok` while
    # `grep -c` over the same bytes answered 2. A verifier reading the same case
    # in its own clone saw the red. An `awk` reading the file DIRECTLY has no
    # producer to kill and runs to EOF, so its answer does not depend on how big
    # the subject has grown.
    CURRENT="the table names no app"
    if awk '{ sub(/#.*$/, ""); if (index($0, "apps/core")) { print NR ": " $0; hit = 1 } }
        END { exit hit ? 0 : 1 }' "$ROOT/scripts/loop_tier.sh" >"${WORK}/names-an-app.txt"; then
        bad "loop_tier.sh names apps/core in CODE — the core case must fall out of the closure, not a special case:
$(sed 's/^/      /' "${WORK}/names-an-app.txt")"
    else
        ok "no executable line names an app: the core case falls out of the declarations"
    fi
}

case_the_transitive_step_is_walked_not_one_hop() {
    # THE SEVERANCE THIS CASE EXISTS FOR. `mid` is declared by `leaf` and by
    # nothing else; `leaf` is declared by nothing. A widening that walked ONE HOP
    # would answer {mid, leaf} here too — so the transitive property needs a
    # THREE-deep chain to be falsifiable at all, and `core -> mid -> leaf` is it:
    # touching `core` must reach `leaf`, which is two hops away.
    fresh_checkout
    touch_and_scope "$REPO" "the closure is transitive, not one hop" apps/mid/services.py
    is "$RC" "0" "the exit status"
    is "$LOOP_SCOPE_APPS" "leaf mid" "the derived scope from mid"
    # And the two-hop proof, run through the closure directly so the assertion
    # names the property rather than a coincidence of this fixture.
    local two_hop
    two_hop=$(cd "$REPO" && loop_scope__closure "$REPO/apps" core | tr '\n' ' ' | sed 's/ $//')
    case " $two_hop " in
    *" leaf "*) ok "the closure of core reaches leaf, which is TWO declarations away" ;;
    *) bad "the closure of core stopped before leaf: got '$two_hop' — a one-hop widening" ;;
    esac
}

case_forward_edges_are_not_widened() {
    fresh_checkout
    touch_and_scope "$REPO" "forward edges are NOT widened" apps/aside/services.py
    is "$RC" "0" "the exit status"
    # `aside` declares `core`. Widening forward would drag `core` in — and then
    # `core`'s own reverse closure, which is the whole tree. The DAG argument is
    # in the file: a dependency cannot import its dependent.
    is "$LOOP_SCOPE_APPS" "aside" "the derived scope"
    grep -q "FORWARD EDGES ARE NOT WIDENED" "$ROOT/scripts/loop_tier.sh" &&
        ok "the source carries the DAG argument for the forward direction" ||
        bad "the source no longer argues why forward edges are not widened"
}

case_config_is_the_full_suite_with_its_sentence() {
    fresh_checkout
    touch_and_scope "$REPO" "config/** -> full" config/settings.py
    is "$RC" "0" "the exit status"
    is "$LOOP_TIER_MODE" "full" "the mode"
    is "$LOOP_SCOPE_NARROW" "" "the narrow flag"
    reason_says "FULL suite"
    is "$LOOP_TIER_SHARED_HITS" "config/settings.py" "the hit that forced it"
}

case_templates_are_the_full_suite() {
    fresh_checkout
    touch_and_scope "$REPO" "templates/** -> full" templates/base.html
    is "$RC" "0" "the exit status"
    is "$LOOP_TIER_MODE" "full" "the mode"
}

case_quality_widens_no_pytest_scope_and_names_the_rule_that_outranks() {
    fresh_checkout
    touch_and_scope "$REPO" "quality/** -> no pytest widening" quality/rules.yaml
    is "$RC" "0" "the exit status"
    is "$LOOP_TIER_MODE" "fast" "the mode"
    is "$LOOP_SCOPE_APPS" "" "the derived scope"
    notes_say "FULL GATE under a typed DJB_GATE_SANCTION"
}

case_a_frontend_only_touch_derives_an_empty_backend_scope() {
    fresh_checkout
    touch_and_scope "$REPO" "frontend/ only -> empty backend scope" frontend/src/app.tsx
    is "$RC" "0" "the exit status"
    is "$LOOP_TIER_MODE" "fast" "the mode"
    is "$LOOP_SCOPE_APPS" "" "the derived scope"
    is "$LOOP_SCOPE_NARROW" "1" "the narrow flag"
    notes_say "no import path from frontend/ into a Python test"
    reason_says "always-on cross-app set runs alone"
}

case_the_shared_shapes_outrank_an_app_touched_beside_them() {
    # All four shapes, each with an app touched alongside it. A rung has not made
    # a shared change smaller by touching an app next to it.
    local shape
    for shape in apps/conftest.py apps/test_root.py scripts/tests/test_thing.sh scripts/loop_tier.sh; do
        fresh_checkout
        touch_and_scope "$REPO" "shared shape ${shape} outranks an app beside it" \
            "$shape" apps/mid/services.py
        is "$RC" "0" "the exit status"
        is "$LOOP_TIER_MODE" "full" "the mode for ${shape}"
        is "$LOOP_SCOPE_APPS" "" "the scope for ${shape}"
    done
}

case_the_reflexive_shape_covers_the_whole_selection_machinery() {
    # This rung widened shape (4) from `loop_tier.sh` alone to the four files
    # that between them decide what --loop runs. A rung that widened the
    # reflexive shape and then graded itself with the narrow one would be the
    # first thing the shape exists to refuse.
    local f
    for f in scripts/loop_tier.sh scripts/check.sh scripts/secrets_scan.sh scripts/gate_ledger.sh; do
        CURRENT="the reflexive shape covers ${f}"
        if loop_tier__is_shared_test_infra "$f"; then
            ok "${f} is shared test infrastructure"
        else
            bad "${f} is NOT in the reflexive shape — a rung changing it would be graded by the tier it changed"
        fi
    done
    CURRENT="an app's own conftest is NOT shared"
    if loop_tier__is_shared_test_infra "apps/mid/tests/conftest.py"; then
        bad "an app's own tests/conftest.py was swept into the shared shape — the commonest fixture edit in the tree would pay for the whole suite"
    else
        ok "apps/<x>/tests/conftest.py belongs to <x> and widens nothing"
    fi
}

case_the_declared_blind_spot_widens_nothing_and_says_so() {
    fresh_checkout
    touch_and_scope "$REPO" "pyproject.toml -> declared blind spot" pyproject.toml
    is "$RC" "0" "the exit status"
    is "$LOOP_TIER_MODE" "fast" "the mode"
    is "$LOOP_SCOPE_APPS" "" "the derived scope"
    notes_say "DEPENDENCY rung"
}

case_an_unclassifiable_path_is_exit_2_naming_the_path_and_the_table() {
    fresh_checkout
    mkdir -p "$REPO/newterritory"
    echo "base" >"$REPO/newterritory/thing.py"
    git -C "$REPO" add -A
    git -C "$REPO" commit -q -m "a territory the table has no row for"
    echo "changed" >>"$REPO/newterritory/thing.py"
    scope_in "$REPO" "an unclassifiable path is exit 2"
    is "$RC" "2" "the exit status"
    says "newterritory/thing.py"
    says "loop_scope__classify"
    cause_recorded "NO ROW for this changed path"
    # NEVER A SILENT FULL AND NEVER A SILENT NARROW — both directions asserted,
    # because either one is a defensible-looking guess and both are wrong.
    says "silent full run"
    says "silent narrow one"
}

case_the_one_legal_override_only_widens() {
    fresh_checkout
    DJB_LOOP_SCOPE_ALSO="aside" \
        touch_and_scope "$REPO" "DJB_LOOP_SCOPE_ALSO widens and cannot narrow" apps/mid/services.py
    is "$RC" "0" "the exit status"
    # `mid` is still there — the override ADDED `aside` and its closure and
    # removed nothing.
    is "$LOOP_SCOPE_APPS" "aside leaf mid" "the widened scope"
    notes_say "can only ADD"
    CURRENT="the override cannot remove"
    # There is no syntax for removal, and that is the assertion: the ONLY
    # environment variable the file reads for scope is the widening one.
    if grep -qE 'DJB_LOOP_SCOPE_(ONLY|EXCEPT|NOT|MINUS)' "$ROOT/scripts/loop_tier.sh"; then
        bad "loop_tier.sh reads a scope variable that could narrow"
    else
        ok "no environment variable can take an app OUT of scope"
    fi
}

# --- the TESTS-ONLY row (contract A.1) ---------------------------------------
#
# Before this row, every path under `apps/<x>/**` — a census test included —
# classified `app` and SEEDED THE CLOSURE, so a one-token edit to a shared
# census test bought the reverse closure of the app that holds it, which is
# every app in the tree. The row below splits that arm: a change under
# `apps/<x>/tests/**` ALONE puts `x` in the TESTS-ONLY set, which walks no
# closure.

case_a_tests_only_touch_seeds_no_closure_and_is_not_own() {
    fresh_checkout
    touch_and_scope "$REPO" "apps/core/tests/** alone -> tests-only, no closure" \
        apps/core/tests/test_core_thing.py
    is "$RC" "0" "the exit status"
    is "$LOOP_TIER_MODE" "fast" "the mode"
    is "$LOOP_SCOPE_TESTS_ONLY" "core" "the tests-only set"
    is "$LOOP_SCOPE_TOUCHED" "" "the touched set (the closure's seeds)"
    is "$LOOP_SCOPE_APPS" "" "the derived scope — NO closure walk"
    is "$LOOP_TIER_OWN_APPS" "" "the own-app list"
    is "$LOOP_SCOPE_NARROW" "1" "the narrow flag"
    is "$LOOP_SCOPE_CHANGED_TESTS" "apps/core/tests/test_core_thing.py" "the edited test modules"
    notes_say "coupling that is not an import"
    reason_says "tests under apps/"
}

case_one_non_test_path_makes_the_app_an_ordinary_touch() {
    # THE DEFINITION, ASSERTED AT ITS EDGE (contract A.1): for app `x`, EVERY
    # changed path under `apps/x/` must match `apps/x/tests/**`. One that does
    # not and `x` is an ordinary touch, closure and all.
    fresh_checkout
    touch_and_scope "$REPO" "a test edit BESIDE a code edit in the same app" \
        apps/core/tests/test_core_thing.py apps/core/services.py
    is "$RC" "0" "the exit status"
    is "$LOOP_SCOPE_TESTS_ONLY" "" "the tests-only set"
    is "$LOOP_SCOPE_TOUCHED" "core" "the touched set"
    is "$LOOP_SCOPE_APPS" "aside core leaf mid" "the derived scope — the whole closure"
}

case_a_core_tests_edit_beside_a_leaf_touch_walks_the_leafs_closure_only() {
    # THE CONSUMER'S ACTUAL CASE. A cross-app wall forces a one-token edit to a
    # census test in `core`; the rung's real work is in a leaf app. Today `core`
    # is a seed and `closure(core)` is every app — their 92%. After the row, the
    # closure is the LEAF's alone.
    fresh_checkout
    touch_and_scope "$REPO" "a core TEST edit beside a leaf CODE touch" \
        apps/core/tests/test_core_thing.py apps/leaf/services.py
    is "$RC" "0" "the exit status"
    is "$LOOP_SCOPE_TESTS_ONLY" "core" "the tests-only set"
    is "$LOOP_SCOPE_TOUCHED" "leaf" "the touched set"
    is "$LOOP_SCOPE_APPS" "leaf" "the derived scope — the LEAF's closure alone"
    is "$LOOP_TIER_OWN_APPS" "leaf" "the own-app list"
    # And the control, on the same tree: the SAME core test edited as an
    # ordinary touch reaches every app. The two answers on one fixture are what
    # make the first one a narrowing rather than a coincidence.
    fresh_checkout
    touch_and_scope "$REPO" "the control: core as an ORDINARY touch still reaches every app" \
        apps/core/models.py apps/leaf/services.py
    is "$LOOP_SCOPE_APPS" "aside core leaf mid" "the control's derived scope"
}

case_a_migration_touch_widens_by_the_import_graph_not_by_tests() {
    # A KEEP pinning contract A.1's migration row: `migrations/**` is ordinary
    # app code and widens by the graph. The tests-only row must not swallow it.
    fresh_checkout
    touch_and_scope "$REPO" "apps/core/migrations/** -> an ordinary core touch" \
        apps/core/migrations/0001_initial.py
    is "$RC" "0" "the exit status"
    is "$LOOP_SCOPE_TESTS_ONLY" "" "the tests-only set"
    is "$LOOP_SCOPE_TOUCHED" "core" "the touched set"
    local from_migration="$LOOP_SCOPE_APPS"
    fresh_checkout
    touch_and_scope "$REPO" "apps/core/services.py -> the same closure" apps/core/services.py
    is "$LOOP_SCOPE_APPS" "$from_migration" "the closure a migration derives (same as code)"
    reason_says "reverse-transitive depends_on closure"
}

case_an_apps_root_conftest_is_an_ordinary_touch_not_tests_only() {
    # Contract A.1, said out loud (lead decision 12): `apps/x/conftest.py` at the
    # APP ROOT is a fixture every module of `x` stands on. Not tests-only.
    fresh_checkout
    touch_and_scope "$REPO" "apps/mid/conftest.py (app root) -> an ordinary touch" \
        apps/mid/conftest.py
    is "$RC" "0" "the exit status"
    is "$LOOP_SCOPE_TESTS_ONLY" "" "the tests-only set"
    is "$LOOP_SCOPE_TOUCHED" "mid" "the touched set"
    is "$LOOP_SCOPE_APPS" "leaf mid" "the derived scope"
    # …while the one INSIDE the test tree is tests-only.
    fresh_checkout
    touch_and_scope "$REPO" "apps/mid/tests/conftest.py -> tests-only" \
        apps/mid/tests/conftest.py
    is "$LOOP_SCOPE_TESTS_ONLY" "mid" "the tests-only set for the test tree's conftest"
    is "$LOOP_SCOPE_APPS" "" "the derived scope"
}

case_also_outranks_tests_only() {
    # The riskiest-rung question 5. The one legal override seeds the CLOSURE, so
    # an app it names runs as own — wider — and the tests-only line does not
    # name it. The override can only ADD, as it always could.
    fresh_checkout
    DJB_LOOP_SCOPE_ALSO="mid" \
        touch_and_scope "$REPO" "DJB_LOOP_SCOPE_ALSO outranks the tests-only row" \
        apps/mid/tests/test_thing.py
    is "$RC" "0" "the exit status"
    is "$LOOP_SCOPE_TESTS_ONLY" "" "the tests-only set (the override took mid out of it)"
    is "$LOOP_SCOPE_TOUCHED" "mid" "the touched set"
    is "$LOOP_SCOPE_APPS" "leaf mid" "the derived scope — the override's closure"
    notes_say "can only ADD"
}

case_the_canonical_key_differs_between_a_tests_only_and_an_own_app_run() {
    # A verdict banked with the tests-only rule must never vouch for a run
    # without it. Same scratch tree, two runs, two keys.
    fresh_checkout
    touch_and_scope "$REPO" "the canonical scope of a tests-only run" \
        apps/mid/tests/test_thing.py
    local tests_only_key="$LOOP_SCOPE_CANONICAL"
    case "$tests_only_key" in
    *"tests=mid"*) ok "the tests-only run's canonical scope carries tests=mid" ;;
    *) bad "the canonical scope does not carry the tests-only labels: '${tests_only_key}'" ;;
    esac
    fresh_checkout
    touch_and_scope "$REPO" "the canonical scope of an own-app run" apps/mid/services.py
    CURRENT="the two canonical scopes differ"
    if [ "$tests_only_key" = "$LOOP_SCOPE_CANONICAL" ]; then
        bad "a tests-only run and an own-app run key identically: '${tests_only_key}' — a banked verdict would vouch for a selection it never saw"
    else
        ok "two scopes, two keys: '${tests_only_key}' vs '${LOOP_SCOPE_CANONICAL}'"
    fi
    CURRENT="the tests= field is appended AFTER always="
    case "$LOOP_SCOPE_CANONICAL" in
    *"always="*"tests="*) ok "the field order is own= scope= always= tests= — the append precedent" ;;
    *) bad "tests= is not appended after always=: '${LOOP_SCOPE_CANONICAL}'" ;;
    esac
}

case_a_path_under_apps_the_table_cannot_place_is_exit_2() {
    # A module directly under `apps/` that is neither a conftest nor `test_*.py`
    # nor `__init__.py` belongs to no app and matches no row. The grammar of the
    # unclassifiable refusal, asserted for the apps/ territory specifically:
    # never a silent full, never a silent narrow.
    fresh_checkout
    echo "base" >"$REPO/apps/stray_module.py"
    git -C "$REPO" add -A
    git -C "$REPO" commit -q -m "a module under apps/ that belongs to no app"
    echo "changed" >>"$REPO/apps/stray_module.py"
    scope_in "$REPO" "a path under apps/ the table cannot place is exit 2"
    is "$RC" "2" "the exit status"
    says "apps/stray_module.py"
    says "loop_scope__classify"
    says "silent full run"
    says "silent narrow one"
}

# --- the refusals ------------------------------------------------------------

case_an_absent_local_main_is_a_refusal_not_a_thin_basis() {
    fresh_checkout
    # A clone shaped like `verify_start` used to leave: the rung branch, and no
    # local refs/heads/main at all.
    git -C "$REPO" checkout -q -b rung/thing
    echo "committed on the rung" >>"$REPO/apps/mid/services.py"
    git -C "$REPO" add -A
    git -C "$REPO" commit -q -m "the rung's own work"
    git -C "$REPO" branch -D main >/dev/null 2>&1
    scope_in "$REPO" "no local refs/heads/main is a refusal"
    is "$RC" "2" "the exit status"
    says "NO local refs/heads/main"
    says "git branch main"
    says "A thin basis is not a small answer"
    # The two legal moves, both named.
    says "linked worktree"
    cause_recorded "NO local refs/heads/main"
}

case_on_main_the_uncommitted_only_basis_stays_legal_and_prints_itself() {
    fresh_checkout
    touch_and_scope "$REPO" "on main, uncommitted-only stays legal" apps/mid/services.py
    is "$RC" "0" "the exit status"
    case "$LOOP_TIER_BASIS" in
    *"on main itself"*) ok "the basis says it is the on-main case, in its own words" ;;
    *) bad "the basis does not name the on-main case: '${LOOP_TIER_BASIS}'" ;;
    esac
}

case_an_undiscoverable_app_is_exit_2_naming_its_apps_py() {
    fresh_checkout
    mkdir -p "$REPO/apps/ghost"
    echo "base" >"$REPO/apps/ghost/services.py"
    git -C "$REPO" add -A
    git -C "$REPO" commit -q -m "a directory under apps/ that declares no AppConfig"
    echo "changed" >>"$REPO/apps/ghost/services.py"
    scope_in "$REPO" "an app the declarations cannot account for is exit 2"
    is "$RC" "2" "the exit status"
    says "apps/ghost/apps.py"
    says "declares no AppConfig"
    # THE F7 CHAIN AT THE LIBRARY LEVEL. This refusal is written by the embedded
    # Python reader inside a `$(...)` callee, so the cause reaches the global
    # only through the caller-side stderr capture. The end-to-end half — the same
    # sentence arriving on check.sh's banner — is
    # case_a_substitution_callees_refusal_surfaces_as_cause.
    cause_recorded "apps/ghost/apps.py"
}

case_a_broken_changed_file_derivation_is_the_inherited_exit_2() {
    # The INHERITED refusal, pinned in both directions rather than left to be
    # discovered: this is a MAPPING over the secret scan's set and not a second
    # derivation of it, so its could-not-look is the mapping's too.
    local outside="${WORK}/not-a-repo${N}"
    drive_require_scratch outside "${outside:-}"
    mkdir -p "$outside"
    scope_in "$outside" "no git directory -> the inherited exit 2"
    is "$RC" "2" "the exit status"
    says "could not read a git directory"
}

# --- the always-on set, and its two layers of floors -------------------------

collected_count() {
    # `679/3409 tests collected (2730 deselected)` -> 679; `3409 tests collected` -> 3409.
    local n
    n=$(awk '/tests collected/ {print $1}' "$1" | tail -1)
    printf '%s' "${n%%/*}"
}

# A clone of THIS checkout, made once and reset between cases. The tests-only
# row's importer widening is a property of this tree's real modules — 24 of them
# name `apps.comms.tests` today — so a fixture world with four invented apps
# would prove nothing about it. The clone is what lets a case CHANGE a real file
# without touching the tree the drive is running in.
REAL_CLONE=""
# The clone's interpreter, RE-LINKED ON EVERY REUSE and not only at creation.
# A clone carries tracked files and `.venv` is ignored, so it starts with none —
# and the gate bodies driven inside it run python files this repository ships,
# which must not fall back to whatever `python3` is first on PATH (on a verifier
# box that is a 3.9 these files are not written for). The re-link is the
# load-bearing half: `.gitignore` says `.venv/`, which matches a DIRECTORY, and
# what this plants is a SYMLINK — so `git clean -fd` on the reuse path sweeps it
# away as untracked and the next case measures a could-not-look instead of a
# census. Measured here, on exactly that path.
real_clone_python() {
    [ -e "${REAL_CLONE}/.venv" ] || ln -s "${ROOT}/.venv" "${REAL_CLONE}/.venv" 2>/dev/null || true
}

real_clone() {
    if [ -n "$REAL_CLONE" ]; then
        git -C "$REAL_CLONE" checkout -q -- . 2>/dev/null || true
        git -C "$REAL_CLONE" clean -qfd 2>/dev/null || true
        real_clone_python
        return 0
    fi
    REAL_CLONE="${WORK}/real-clone"
    drive_require_scratch REAL_CLONE "${REAL_CLONE:-}"
    git clone --quiet --shared --no-hardlinks "$ROOT" "$REAL_CLONE" >/dev/null 2>&1 ||
        cannot_look "could not clone this checkout into the scratch directory"
    git -C "$REAL_CLONE" checkout -q -B main
    git -C "$REAL_CLONE" config user.email drive@example.invalid
    git -C "$REAL_CLONE" config user.name "loop scope drive"
    real_clone_python
}

collect_scope() {
    # Collect the REAL suite at a named scope and report what was selected.
    # Runs from the real checkout: the always-on derivation is a property of
    # THIS tree's modules, and a fixture tree would prove nothing about it.
    local name="$1"
    shift
    CURRENT="$name"
    N=$((N + 1))
    OUT="${WORK}/collect${N}.log"
    RC=0
    (cd "$ROOT" && "$PY" -m pytest --collect-only -q -p no:randomly "$@") >"$OUT" 2>&1 || RC=$?
    capture_floor
}

# collect_scope_memo <slot> <name> <args…> — ONE collection per (slot), shared
# by every case that asks the same question of the same tree.
#
# WHY A SLOT AND NOT THE ARGV. Memoising on the argument list alone would be
# wrong here and silently so: several cases run byte-identical flags on
# DIFFERENT trees — the apps-root census case collects four scopes with its
# plant standing and the same four with it removed, and the whole claim is
# that every count drops by exactly one. A key made of the flags would hand
# the second set the first set's answer and the case would pass about nothing.
# So the sharing is NAMED at each site, by a slot a reader can grep, and the
# plant-side runs take no slot at all.
#
# WHAT IT SAVES, measured by the lead before the rung: this drive spent most of
# its 292 s on ~39 whole-suite collections at 6-10 s each, and five groups of
# them were asking one question several times over one unchanged tree.
#
# THE MEMO IS THE FILE, NOT THE TEXT: `$OUT` and `$RC` are restored exactly as
# `collect_scope` left them, so a caller reads the same log by the same names.
# The idiom is `bank_leg_run`'s and `manifest_all`'s, one layer up.
collect_scope_memo() {
    local slot="$1" name="$2" held
    shift 2
    eval "held=\${SCOPE_MEMO_OUT_${slot}:-}"
    if [ -n "$held" ]; then
        OUT="$held"
        eval "RC=\$SCOPE_MEMO_RC_${slot}"
        CURRENT="$name (the ${slot} collection, already taken)"
        return 0
    fi
    collect_scope "$name" "$@"
    eval "SCOPE_MEMO_OUT_${slot}=\$OUT"
    eval "SCOPE_MEMO_RC_${slot}=\$RC"
}

case_the_floors_refuse_when_the_cross_app_derivation_returns_nothing() {
    # SEVERANCE. The tokens are the derivation; emptied, every module derives no
    # reach, the always-on set collapses to the apps-root modules alone, and both
    # layers of floors must refuse BEFORE anything is deselected.
    local plant="${ROOT}/apps/conftest.py" backup="${WORK}/conftest.backup"
    cp "$plant" "$backup"
    # The plant is restored by the exit trap too, so a killed drive cannot leave
    # the real tree severed.
    drive_at_exit "cp \"$backup\" \"$plant\" 2>/dev/null || true"
    "$PY" - "$plant" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
source = path.read_text(encoding="utf-8")
severed = source.replace(
    '    "app_registry": ("get_app_configs",),', '    "app_registry": ("__severed__",),'
).replace(
    '    "model_registry": ("get_models(",),', '    "model_registry": ("__severed__",),'
).replace(
    '    "introspect_registry": ("management.commands.introspect",),',
    '    "introspect_registry": ("__severed__",),',
).replace(
    '    "absent_world": ("DJB_DISABLED_APPS",),', '    "absent_world": ("__severed__",),'
).replace('    "door_parity": ("DOOR_PAIR",),', '    "door_parity": ("__severed__",),')
if severed == source:
    sys.stderr.write("the severance found nothing to sever — the declaration moved\n")
    raise SystemExit(2)
path.write_text(severed, encoding="utf-8")
PY
    collect_scope "an emptied cross-app derivation refuses, exit 4 (the gate maps it to 2)" \
        --djb-tier=fast --djb-scope-narrow
    cp "$backup" "$plant"
    is "$RC" "4" "the exit status (pytest UsageError; scripts/check.sh maps 4 to exit 2)"
    says "LAYER 1 (reach kind)"
    says "LAYER 2 (named population)"
    says "NOTHING was deselected"
}

case_a_floor_member_moved_aside_is_a_refusal() {
    # The layer-2 property, and the reason layer 2 exists: emptying ONE member of
    # ONE population must redden even though every layer-1 reach kind is still
    # satisfied by the populations beside it.
    local victim="${ROOT}/apps/test_absent_world.py" hidden="${WORK}/moved-aside.py"
    [ -f "$victim" ] || cannot_look "apps/test_absent_world.py is gone — the floor member this case moves aside"
    mv "$victim" "$hidden"
    drive_at_exit "[ -f \"$hidden\" ] && mv \"$hidden\" \"$victim\" 2>/dev/null || true"
    collect_scope "a floor member moved aside is a refusal" --djb-tier=fast --djb-scope-narrow
    mv "$hidden" "$victim"
    is "$RC" "4" "the exit status"
    says "apps_root_modules"
    CURRENT="layer 1 alone would not have noticed"
    if grep -q "LAYER 1 (reach kind)" "$OUT"; then
        bad "a layer-1 floor also fired — this case can no longer show layer 2 catching what layer 1 misses"
    else
        ok "ONLY the named-population floor fired: layer 1 was satisfied throughout"
    fi
}

case_a_drawer_raised_floor_refuses_a_member_moved_aside_on_a_six_module_tree() {
    # THE THIRD PIECE of the drawer-raised floor: the declaration
    # (`DJB_POPULATION_FLOOR_ADDENDS` in apps/conftest_local.py), its ONE
    # reader (`_population_floors` in apps/conftest.py), and this case, which
    # plants a drawer row and proves the reader ran it.
    #
    # THE WORLD IS A PRODUCT'S: a sixth apps-root module the template does not
    # have. Without a drawer the case above goes blind on it — six members,
    # one moved aside, five remain, five meet the template's floor, exit 0
    # (`wanted '4', got '0'` on the first consumer's tree). With the drawer
    # declaring the product's one extra member, the floor is template + drawer
    # and moving one aside is a refusal again.
    #
    # THE PLANT WORKS ON A TREE THAT ALREADY HAS A DRAWER: the line appended
    # adds ONE to whatever the drawer already declares, so a product carrying
    # its own addend is measured with its own plus this case's module.
    local victim="${ROOT}/apps/test_absent_world.py" hidden="${WORK}/moved-aside-6.py"
    local probe="${ROOT}/apps/test_zzz_probe_floor.py" drawer="${ROOT}/apps/conftest_local.py"
    local drawer_backup="${WORK}/conftest_local.backup" had_drawer=""
    [ -f "$victim" ] || cannot_look "apps/test_absent_world.py is gone — the floor member this case moves aside"
    [ -e "$probe" ] && cannot_look "${probe} already exists — this case plants it and will not overwrite it"
    if [ -f "$drawer" ]; then
        had_drawer=1
        cp "$drawer" "$drawer_backup"
    fi
    drive_at_exit "rm -f \"$probe\"; [ -f \"$hidden\" ] && mv \"$hidden\" \"$victim\" 2>/dev/null; if [ -n \"$had_drawer\" ]; then cp \"$drawer_backup\" \"$drawer\" 2>/dev/null; else rm -f \"$drawer\"; fi; true"
    printf '%s\n' '"""A planted sixth apps-root module (test_loop_scope.sh, the drawer-raised floor)."""' \
        '' '' 'def test_zzz_probe_floor() -> None:' '    assert True' >"$probe"
    printf '%s\n' '' '# planted by test_loop_scope.sh: the drawer-raised floor, one more apps-root member' \
        'DJB_POPULATION_FLOOR_ADDENDS = {' \
        '    **globals().get("DJB_POPULATION_FLOOR_ADDENDS", {}),' \
        '    "apps_root_modules": globals().get("DJB_POPULATION_FLOOR_ADDENDS", {}).get("apps_root_modules", 0) + 1,' \
        '}' >>"$drawer"
    mv "$victim" "$hidden"
    collect_scope "a drawer-raised floor: a member moved aside on a six-module tree is a refusal" \
        --djb-tier=fast --djb-scope-narrow
    mv "$hidden" "$victim"
    rm -f "$probe"
    if [ -n "$had_drawer" ]; then
        cp "$drawer_backup" "$drawer"
    else
        rm -f "$drawer"
    fi
    if [ "$RC" = "4" ]; then
        ok "the exit status is '4'"
    else
        bad "the exit status: wanted '4', got '${RC}' — the drawer's addend was not read; its one reader is _population_floors in apps/conftest.py"
    fi
    says "apps_root_modules"
    CURRENT="the refusal names the drawer's half of the floor"
    if grep -q "apps_root_modules (floor [0-9]* = [0-9]* in apps/conftest.py + [0-9]* in apps/conftest_local.py" "$OUT"; then
        ok "the floor is printed as template + drawer — _population_floors read the planted row"
    else
        bad "no 'template + drawer' floor in the refusal — the planted DJB_POPULATION_FLOOR_ADDENDS row was not read by _population_floors (apps/conftest.py), the one reader of the drawer's declaration"
    fi
}

case_the_always_on_set_survives_the_real_parallel_invocation() {
    # MEASURE THE LEG YOU SHIP. A serial approximation of a parallel leg is green
    # either way, because the approximation genuinely passes. So this runs the
    # REAL `-n` shape the gate runs, and asserts the property that only exists
    # there: every worker collects the whole suite independently, so their counts
    # files must be IDENTICAL — reconciled, never summed.
    #
    # `--collect-only -n 2` IS NOT THAT SHAPE, and the first draft of this case
    # used it and was green: under `--collect-only` xdist never starts a worker,
    # so ONE counts file appeared, written by the controller, and the case
    # "proved" a reconciliation across a population of one. The case now fails
    # loud on a file count below two for exactly that reason.
    #
    # `-k` RATHER THAN A PATH, so the run stays cheap without changing the shape
    # being measured: every worker still performs the FULL collection this case
    # exists to compare, and the keyword filter only decides which of the
    # selected tests are executed afterwards. A path argument would narrow the
    # collection itself and measure a different leg.
    local counts="${WORK}/counts"
    drive_require_scratch counts "${counts:-}"
    mkdir -p "$counts"
    CURRENT="the counts reconcile across real xdist workers"
    N=$((N + 1))
    OUT="${WORK}/xdist${N}.log"
    RC=0
    (cd "$ROOT" && "$PY" -m pytest -q -p no:randomly -n 2 \
        --djb-tier=fast --djb-scope-narrow "--djb-scope-counts=$counts" \
        -k test_the_namer_unwraps_and_never_reaches_for_repr) >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the exit status"
    local files first n
    files=$(find "$counts" -type f | sort)
    n=$(printf '%s\n' "$files" | grep -c . || true)
    CURRENT="every worker wrote its own counts file"
    if [ "$n" -lt 2 ]; then
        bad "only ${n} counts file(s) under -n 2 — the workers did not each collect, so this case measured a serial approximation of the leg it exists to prove"
    else
        ok "${n} collector files written under -n 2"
    fi
    first=$(printf '%s\n' "$files" | head -1)
    CURRENT="the collectors agree"
    local f disagreed=""
    for f in $files; do
        cmp -s "$first" "$f" || disagreed="$f"
    done
    if [ -n "$disagreed" ]; then
        bad "the collectors disagree: ${first##*/} vs ${disagreed##*/}"
    else
        ok "every collector derived the same in_scope/always_on/deselected triple"
    fi
    CURRENT="the always-on set is not empty"
    local always
    always=$(awk -F= '/^always_on=/ {print $2}' "$first")
    if [ "${always:-0}" -gt 0 ]; then
        ok "always_on=${always} at an EMPTY scope — the cross-app population still runs"
    else
        bad "always_on=${always:-unset}: an empty scope deselected the cross-app population too, which is the hole the always-on set exists to close"
    fi
}

case_a_narrower_scope_selects_strictly_less_than_a_wider_one() {
    collect_scope_memo empty "an empty scope selects less than a scope with an app in it" \
        --djb-tier=fast --djb-scope-narrow
    is "$RC" "0" "the exit status"
    local empty scoped
    empty=$(awk '/tests collected/ {print $1}' "$OUT" | tail -1)
    # CANARY A.4-6, the half a count alone can prove: an EMPTY scope still runs
    # the always-on set. Zero selected would be a narrowing that took the
    # cross-app tripwires out with it, which is the hole the always-on set
    # exists to close — and it would still read as a green, fast loop.
    CURRENT="an empty scope still selects the always-on set"
    if [ -n "$empty" ] && [ "${empty%%/*}" -gt 0 ]; then
        ok "an empty scope selected ${empty} — the always-on cross-app set runs alone"
    else
        bad "an empty scope selected '${empty:-?}': the narrowing deselected the always-on set too"
    fi
    collect_scope "a scope with core in it selects more" \
        --djb-tier=fast --djb-scope-narrow --djb-scope=core
    is "$RC" "0" "the exit status"
    scoped=$(awk '/tests collected/ {print $1}' "$OUT" | tail -1)
    CURRENT="a wider scope selects strictly more"
    if [ -n "$empty" ] && [ -n "$scoped" ] && [ "${scoped%%/*}" -gt "${empty%%/*}" ]; then
        ok "empty scope selected ${empty}, scope=core selected ${scoped}"
    else
        bad "the two scopes selected '${empty:-?}' and '${scoped:-?}' — a scope that changes nothing is not a scope"
    fi
}

# --- the placement rule a product's edge census rides on ---------------------

# THE `--mine` ARM'S FLAGS, IN ONE PLACE AND READ BY TWO CASES. The placement
# case COLLECTS with these; `case_the_mine_arm_in_the_placement_case_matches_the_flags_check_sh_passes`
# asserts they are exactly what `check.sh --loop --mine` hands pytest for the
# same touch. One array, two readers, so the arm cannot go on proving a shape
# nobody runs: the shape it proves is the shape the other case measures off the
# script. Written blind while `--mine` did not exist; live and checked now that
# it does.
MINE_ARM_FLAGS=(--djb-tier=fast --djb-scope-narrow --djb-own-app=core --djb-scope=core)

# ONE `--mine` COLLECTION, AND IT CARRIES THE COUNTS WRITER. Two cases asked
# the same question of the same tree — one wanted the collected count, the
# other the always-on figure the counts files carry — so the run is taken once
# with `--djb-scope-counts` on. The flag writes a file per collector and
# changes nothing about what is SELECTED, which is what lets the count case
# read this capture instead of paying for a second collection.
MINE_COUNTS=""
MINE_COLLECTION_READY=""
MINE_COLLECTION_OUT=""
MINE_COLLECTION_RC=0
mine_collection_once() {
    local name="$1"
    if [ -n "$MINE_COLLECTION_READY" ]; then
        OUT="$MINE_COLLECTION_OUT"
        RC="$MINE_COLLECTION_RC"
        CURRENT="${name} (the --mine collection, already taken)"
        capture_floor
        return 0
    fi
    MINE_COUNTS="${WORK}/mine-counts"
    drive_require_scratch MINE_COUNTS "${MINE_COUNTS:-}"
    rm -rf "$MINE_COUNTS"
    mkdir -p "$MINE_COUNTS"
    collect_scope "$name" "${MINE_ARM_FLAGS[@]}" "--djb-scope-counts=$MINE_COUNTS"
    MINE_COLLECTION_OUT="$OUT"
    MINE_COLLECTION_RC="$RC"
    MINE_COLLECTION_READY=1
}

selects_the_plant() {
    # One assertion, asked of each scope shape in turn: the planted apps-root
    # module's nodeid is in the collection this scope produced.
    local nodeid="$1" where="$2"
    CURRENT="the planted apps-root census is SELECTED under ${where}"
    if grep -qxF "$nodeid" "$OUT"; then
        ok "${nodeid} is in the collection"
    else
        bad "${nodeid} was deselected under ${where}: an apps-root module belongs to NO app, so no scope can contain it and nothing may narrow it away — a product's edge census placed there would run in no per-rung gate"
    fi
}

case_a_planted_apps_root_census_runs_at_every_scope() {
    # THE PLACEMENT RULE, pinned for a census that does not exist yet. A product
    # that wants a tripwire over its edge — the ALB rules, the reverse proxy's
    # prefixes, whatever its front door is — needs it to run at EVERY scope, not
    # only in the full gate at push, because the whole point of such a census is
    # that it catches a config change nobody routed through an app. The platform
    # owns the MECHANISM that makes that possible and not the census itself:
    # `apps/test_<edge>.py`, a module at the apps root, is always-on BY
    # CONSTRUCTION (`apps/conftest.py`, `_is_always_on` — an item whose
    # `_app_label` is None can never be inside any scope, so deselecting it would
    # take a positive decision nobody has made; and `_population_members`, which
    # puts it in the `apps_root_modules` floor).
    #
    # A KEEP, and it says so: the property holds on the tree this case was
    # written against. What the case buys is that it cannot QUIETLY stop holding
    # — severing the structural half of `_is_always_on` deselects the plant under
    # a leaf scope while every other case in this drive stays green.
    #
    # The victim is PLANTED, never found: a case that leaned on one of the three
    # real apps-root modules would be asserting on this tree's contents rather
    # than on the rule, and would go red the day one of them is renamed.
    local plant="${ROOT}/apps/test_zzz_edge.py"
    local nodeid="apps/test_zzz_edge.py::test_the_planted_edge_census_is_collected"
    [ -e "$plant" ] &&
        cannot_look "apps/test_zzz_edge.py already exists — this case plants that path and would delete somebody else's file"
    drive_at_exit "rm -f \"$plant\" 2>/dev/null || true"
    cat >"$plant" <<'PY'
"""A planted apps-root module, standing in for a product's edge census.

Written by scripts/tests/test_loop_scope.sh and removed by it again. It names
none of the cross-app reach tokens apps/conftest.py derives: a plant that
survived a narrowing because it mentioned one of them would be proving the
derivation rather than the structural rule this case exists to pin.
"""


def test_the_planted_edge_census_is_collected() -> None:
    assert 1 + 1 == 2
PY
    local empty_with leaf_with pr_with mine_with
    local empty_without leaf_without pr_without mine_without

    # (1) THE EMPTY SCOPE — the hardest of the four: no app is named at all, so
    # the plant survives on the structural rule alone.
    collect_scope "a planted apps-root census under the EMPTY scope" \
        --djb-tier=fast --djb-scope-narrow
    is "$RC" "0" "the empty scope's exit status"
    selects_the_plant "$nodeid" "the empty scope"
    empty_with=$(collected_count "$OUT")

    # (2) `--loop --mine` — the own apps' fast tier with the closure NOT walked,
    # which at the pytest door is the own app alone in the scope. LIVE: the flag
    # is on this tree, and the flags this invocation uses are the shared array
    # above, which `case_the_mine_arm_in_the_placement_case_matches_the_flags_check_sh_passes`
    # asserts equal to the gate's own. The precondition is kept as a guard
    # rather than assumed: a drive that silently collected at a shape no mode
    # produces would pass and prove nothing.
    if grep -q -- '^--mine)' "${ROOT}/scripts/check.sh"; then
        collect_scope "a planted apps-root census under --loop --mine" \
            "${MINE_ARM_FLAGS[@]}"
        is "$RC" "0" "the --mine scope's exit status"
        selects_the_plant "$nodeid" "--loop --mine"
        mine_with=$(collected_count "$OUT")
    else
        cannot_look "scripts/check.sh no longer takes --mine — the arm above collects at a shape no mode produces, so its green would mean nothing"
    fi

    # (3) A LEAF-APP SCOPE — one touched app and the closure it pulled in.
    collect_scope "a planted apps-root census under a leaf-app scope" \
        --djb-tier=fast --djb-scope-narrow --djb-own-app=files \
        --djb-scope=files --djb-scope=exports
    is "$RC" "0" "the leaf-app scope's exit status"
    selects_the_plant "$nodeid" "a leaf-app scope"
    leaf_with=$(collected_count "$OUT")

    # (4) `--pr` — the same narrowing at a different fork point and with no organ
    # tier. Live: the flags are on this tree.
    collect_scope "a planted apps-root census under the --pr shape" \
        --djb-scope-narrow --djb-scope=files --djb-scope=exports
    is "$RC" "0" "the --pr shape's exit status"
    selects_the_plant "$nodeid" "the --pr shape"
    pr_with=$(collected_count "$OUT")

    # REMOVING IT RESTORES THE COUNT. Without this half the case cannot tell a
    # scope that really selected the plant from one that was never narrowing: the
    # difference of exactly one is what makes the nodeid assertions above mean
    # the plant was ADDED to each selection.
    rm -f "$plant"
    collect_scope_memo empty "the empty scope with the plant removed" \
        --djb-tier=fast --djb-scope-narrow
    is "$RC" "0" "the exit status"
    empty_without=$(collected_count "$OUT")
    collect_scope_memo leaf "the leaf-app scope with the plant removed" \
        --djb-tier=fast --djb-scope-narrow --djb-own-app=files \
        --djb-scope=files --djb-scope=exports
    is "$RC" "0" "the exit status"
    leaf_without=$(collected_count "$OUT")
    collect_scope_memo pr "the --pr shape with the plant removed" \
        --djb-scope-narrow --djb-scope=files --djb-scope=exports
    is "$RC" "0" "the exit status"
    pr_without=$(collected_count "$OUT")
    mine_collection_once "the --mine shape with the plant removed"
    is "$RC" "0" "the exit status"
    mine_without=$(collected_count "$OUT")

    CURRENT="removing the plant restores every count by exactly one"
    is "$empty_without" "$((empty_with - 1))" "the empty scope's count with the plant removed"
    is "$leaf_without" "$((leaf_with - 1))" "the leaf-app scope's count with the plant removed"
    is "$pr_without" "$((pr_with - 1))" "the --pr shape's count with the plant removed"
    is "$mine_without" "$((mine_with - 1))" "the --mine shape's count with the plant removed"
}

# --- `--loop --mine`: the own apps alone, and never a banked verdict ---------

# call_lines <needle> <file> — EVERY line number that calls the needle, comment
# lines skipped. `first_call_line`'s population, for the readers that need a
# window rather than the first hit, and filtered by its rule rather than a
# second one: this drive has one answer to "is this line a call or a sentence
# about one", and the fold that put two of them in the file for an afternoon is
# the reason it says so here.
#
# Reads whole: nothing at the tail of this pipe exits early.
call_lines() {
    local needle="$1" file="$2"
    { grep -n -F -- "$needle" "$file" || true; } |
        awk -F: '$0 !~ /^[0-9]+:[[:space:]]*#/ {print $1}'
}

# The flag names `check.sh`'s `--loop` pytest leg assembles into TIER_ARGS, read
# out of the script itself: the block between the array's first assignment and
# the invocation it is expanded into. Read rather than listed, because a list
# here would be a second copy of the leg that agrees today.
mine_flag_names_in_check_sh() {
    local first last
    first=$(first_call_line 'TIER_ARGS=(--djb-tier=fast)' "${ROOT}/scripts/check.sh")
    last=$(first_call_line '"${TIER_ARGS[@]}"' "${ROOT}/scripts/check.sh")
    [ -n "$first" ] && [ -n "$last" ] && [ "$last" -gt "$first" ] || return 2
    # COMMENT LINES DROPPED BY THE SAME RULE the two readers above use: this
    # block EXPLAINS its three lists at length and names every flag in prose, so
    # a census that could not tell the explanation from the assembly would be
    # satisfied by a leg that stopped passing one of them.
    sed -n "${first},${last}p" "${ROOT}/scripts/check.sh" |
        awk '$0 !~ /^[[:space:]]*#/' |
        grep -o -- '--djb-[a-z-]*' | sort -u
}

case_the_mine_arm_in_the_placement_case_matches_the_flags_check_sh_passes() {
    # THE ARM WAS WRITTEN BLIND. The placement case's `--mine` invocation was
    # authored before `--mine` existed, from the shape the mode was going to
    # have; nothing re-checked it when the mode landed, and a hard-coded arm
    # that drifts from the gate proves a shape nobody runs while staying green.
    # This case is the re-check: the flags the arm collects with are asserted
    # EQUAL to the flags `check.sh --loop --mine` really hands pytest for the
    # same touch, derived here rather than typed.
    real_clone
    printf '\n' >>"$REAL_CLONE/apps/core/services.py"
    # Set and cleared around the call rather than as a prefix assignment: on
    # bash 3.2 a `VAR=x func` assignment PERSISTS after the function returns,
    # and a mode flag leaking into the next case is exactly the kind of state
    # this drive must not carry.
    LOOP_MINE=1
    scope_in "$REAL_CLONE" "a core touch under --mine, classified"
    LOOP_MINE=""
    is "$RC" "0" "the exit status"
    is "$LOOP_TIER_OWN_APPS" "core" "the own-app list"
    is "$LOOP_SCOPE_APPS" "core" "the derived scope"

    # THE SAME ASSEMBLY THE LEG DOES, over the globals the derivation just set.
    local expected=(--djb-tier=fast) label path
    for label in $LOOP_TIER_OWN_APPS; do expected+=("--djb-own-app=$label"); done
    for label in $LOOP_SCOPE_TESTS_ONLY; do expected+=("--djb-tests-only=$label"); done
    for path in $LOOP_SCOPE_CHANGED_TESTS; do expected+=("--djb-changed-test=$path"); done
    # THE MAP'S TWO FLAGS, ASSEMBLED UNDER THE LEG'S OWN GUARD, which is what
    # makes this arm a statement about `--mine` rather than about the map:
    # `--mine` does not consult the map, so `LOOP_IMPACT` is empty here and
    # neither flag is emitted — and if that ever stops being true, this
    # reconstruction says so instead of quietly agreeing.
    if [ -n "${LOOP_IMPACT:-}" ]; then
        for path in $LOOP_SCOPE_CHANGED_FILES; do expected+=("--djb-changed=$path"); done
    fi
    if [ -n "$LOOP_SCOPE_IMPACT_SELECT" ]; then
        expected+=("--djb-impact-select=$LOOP_SCOPE_IMPACT_SELECT")
    elif [ -n "$LOOP_SCOPE_NARROW" ]; then
        for label in $LOOP_SCOPE_APPS; do expected+=("--djb-scope=$label"); done
        expected+=(--djb-scope-narrow)
    fi

    # (a) THE RECONSTRUCTION ABOVE IS STILL THE SCRIPT'S. Compare the flag NAMES
    #     the leg can pass with the names this case's assembly knows how to
    #     produce — DECLARED, because the assembly emits a name only when its
    #     list is non-empty, and a set read off one derivation would go quietly
    #     smaller with it. A flag added to the leg and not to this list is the
    #     drift this half exists to catch; without it the comparison in (b)
    #     stays true and stops meaning anything.
    local covered="--djb-tier --djb-own-app --djb-tests-only --djb-changed-test --djb-scope --djb-scope-narrow --djb-changed --djb-impact-select"
    local script_names case_names counts_hits
    script_names=$(mine_flag_names_in_check_sh) ||
        cannot_look "could not read check.sh's TIER_ARGS block — the flags the leg passes cannot be read, so nothing here can be compared to them"
    CURRENT="the counts flag is the one declared subtraction"
    counts_hits=$(printf '%s\n' "$script_names" | grep -cx -- '--djb-scope-counts' || true)
    if [ "$counts_hits" = "1" ]; then
        ok "--djb-scope-counts is in the leg's set and is subtracted here BY NAME: it carries a scratch directory, not a scope claim"
    else
        bad "--djb-scope-counts is no longer among the leg's flags — the subtraction below is now silent rather than declared"
    fi
    script_names=$(printf '%s\n' "$script_names" | grep -vx -- '--djb-scope-counts')
    case_names=$(printf '%s\n' $covered | sort -u)
    CURRENT="this case covers every flag name the leg can pass"
    if [ "$script_names" = "$case_names" ]; then
        ok "the leg's flag names and this case's declared set are the same: $(printf '%s ' $case_names)"
    else
        bad "the leg passes [$(printf '%s ' $script_names)] and this case declares [$(printf '%s ' $case_names)] — the reconstruction has fallen behind the leg"
    fi
    CURRENT="and every flag it assembled is one of them"
    local emitted_names
    emitted_names=$(printf '%s\n' "${expected[@]}" | sed 's/=.*//' | sort -u)
    if [ -z "$(printf '%s\n' "$emitted_names" | grep -vxF -f <(printf '%s\n' "$case_names") || true)" ]; then
        ok "the assembly emitted only declared names: $(printf '%s ' $emitted_names)"
    else
        bad "the assembly emitted a name outside the declared set: [$(printf '%s ' $emitted_names)]"
    fi

    # (b) AND THE ARM IS EXACTLY THAT. Sorted, because the leg's order is an
    #     assembly detail and pytest does not read it as one.
    local want have
    want=$(printf '%s\n' "${expected[@]}" | sort)
    have=$(printf '%s\n' "${MINE_ARM_FLAGS[@]}" | sort)
    CURRENT="the placement case's --mine arm is the mode's own shape"
    if [ "$want" = "$have" ]; then
        ok "the arm collects with exactly what --loop --mine hands pytest: $(printf '%s ' $have)"
    else
        bad "the arm collects with [$(printf '%s ' $have)] and --loop --mine hands pytest [$(printf '%s ' $want)] — the placement case proves a --mine shape nobody runs"
    fi
}

case_mine_runs_own_apps_only_and_never_banks() {
    # THE SUBTRACTION IS REAL, and the only way to show that is to derive the
    # same touch both ways: `apps/core` is the app every other app declares, so
    # the ordinary `--loop` widens it to the whole tree and `--mine` does not.
    # A case that only asserted the `--mine` answer could not tell a closure
    # that was subtracted from one that was never going to be there.
    real_clone
    printf '\n' >>"$REAL_CLONE/apps/core/services.py"
    LOOP_MINE=1
    scope_in "$REAL_CLONE" "a core touch under --loop --mine"
    LOOP_MINE=""
    is "$RC" "0" "the exit status"
    is "$LOOP_TIER_MODE" "fast" "the mode"
    is "$LOOP_SCOPE_TOUCHED" "core" "the touched set"
    is "$LOOP_SCOPE_APPS" "core" "the derived scope — the own app, and nothing the closure reaches"
    is "$LOOP_SCOPE_WIDENED" "" "the widening — the closure was NOT walked into the scope"
    is "$LOOP_TIER_OWN_APPS" "core" "the own-app list — the touched app still runs IN FULL"
    local mine_canonical="$LOOP_SCOPE_CANONICAL" mine_reason="$LOOP_TIER_REASON"
    CURRENT="the --mine banner says what it did not walk"
    case "$mine_reason" in
    *"closure NOT walked"*) ok "the reason names the closure it did not walk" ;;
    *) bad "the reason does not say the closure was not walked: ${mine_reason}" ;;
    esac
    CURRENT="the --mine note names the run that does see a dependant"
    case "$LOOP_SCOPE_NOTES" in
    *"ordinary --loop"*) ok "the note points at the ordinary --loop" ;;
    *) bad "the note does not point at the run a dependant's regression surfaces in: ${LOOP_SCOPE_NOTES}" ;;
    esac

    scope_in "$REAL_CLONE" "the SAME touch under the ordinary --loop"
    is "$RC" "0" "the exit status"
    is "$LOOP_SCOPE_TOUCHED" "core" "the touched set is the same"
    CURRENT="the ordinary --loop walks the closure this touch has"
    if [ -n "$LOOP_SCOPE_WIDENED" ]; then
        ok "the ordinary run widened to [${LOOP_SCOPE_WIDENED}] — so --mine's empty widening is a subtraction, not an absence"
    else
        bad "the ordinary run widened to nothing either: this touch has no closure, so nothing above measured --mine"
    fi

    # THE KEY IS NOT SPELLABLE AS AN ORDINARY ONE. Same tree, same touch, two
    # scopes -> two keys is the loop ledger's whole contract; `mode=mine` is what
    # keeps a closure-less verdict from ever being reused by a closure-walked
    # run, even if the guards below were lost.
    CURRENT="the canonical scope distinguishes a --mine run"
    if [ "$mine_canonical" = "$LOOP_SCOPE_CANONICAL" ]; then
        bad "the --mine scope and the ordinary scope produce the same canonical string: ${mine_canonical}"
    else
        ok "two canonical scopes: [${mine_canonical}] vs [${LOOP_SCOPE_CANONICAL}]"
    fi
    case "$mine_canonical" in
    "mode=mine "*) ok "the --mine canonical scope declares its own mode" ;;
    *) bad "the --mine canonical scope does not say mode=mine: ${mine_canonical}" ;;
    esac

    # THE ALWAYS-ON SET IS OUTSIDE THE NARROWING — measured through the leg's own
    # counts writer rather than inferred from a total, at the narrowest scope
    # there is, which is exactly where a set that narrows with the scope would
    # disappear.
    local always
    mine_collection_once "the --mine selection, with the counts writer on"
    is "$RC" "0" "the exit status"
    always=$(awk -F= '/^always_on=/ {print $2}' "$(find "$MINE_COUNTS" -type f | sort | head -1)" 2>/dev/null || true)
    CURRENT="the always-on set runs under --mine"
    if [ -n "$always" ] && [ "$always" -gt 0 ]; then
        ok "always_on=${always} under --mine — the cross-app tripwires are outside the narrowing"
    else
        bad "always_on=${always:-unset} under --mine: the narrowest scope took the cross-app population with it, which is the hole the always-on set exists to close"
    fi

    # AND IT BANKS NOTHING. Read as text, the way the `--pr` no-bank case reads
    # its own: the run itself is a whole `--loop` and this drive does not take a
    # pytest slot. What must hold is that the key is never DERIVED under the
    # flag — every consult and every bank in that file is guarded on the key
    # being non-empty, so an underived key is the mechanism rather than two
    # remembered guards.
    local key_line bank_line guard_line
    key_line=$(first_call_line 'LOOP_LEDGER_KEY=$(loop_ledger_key' "${ROOT}/scripts/check.sh")
    bank_line=$(first_call_line 'loop_ledger_record ' "${ROOT}/scripts/check.sh")
    CURRENT="the key is not derived under --mine"
    if [ -z "$key_line" ]; then
        bad "check.sh no longer derives a loop ledger key at all — this assertion has lost its subject"
    else
        # The ENCLOSING condition, found by walking up to the `if` that opens the
        # branch: the derivation sits two lines inside it, and pinning "the line
        # immediately above" would make this assertion a claim about formatting.
        # Comment lines are not candidates — a paragraph explaining the guard is
        # not the guard.
        guard_line=$(call_lines 'GATE_MINE' "${ROOT}/scripts/check.sh" |
            awk -v k="$key_line" '$1 < k && $1 > k - 8 {n = $1} END {print n}')
        if [ -n "$guard_line" ]; then
            ok "the key derivation at check.sh:${key_line} sits under a GATE_MINE guard at :${guard_line}"
        else
            bad "no GATE_MINE guard in the 7 lines above the key derivation (check.sh:${key_line}) — a --mine run would derive a key, and a derived key is consulted and banked"
        fi
    fi
    CURRENT="the bank is downstream of that key"
    if [ -n "$bank_line" ] && [ -n "$key_line" ] && [ "$bank_line" -gt "$key_line" ]; then
        ok "loop_ledger_record (line ${bank_line}) is below the guarded derivation (line ${key_line}), so an underived key never reaches it"
    else
        bad "loop_ledger_record (${bank_line:-none}) is not below the key derivation (${key_line:-none}) — --mine's no-bank property rests on nothing"
    fi
    # AND IT SAYS SO IN BOTH SHAPES — driven over check.sh's own bytes rather
    # than asserted as a grep for a string, because the shape that matters is
    # the one this drive's own rung could not produce: a rung that changed
    # shared test infrastructure narrows nothing under `--mine`, and a banner
    # announcing a narrowing there would be the honesty line lying in the one
    # direction nobody checks.
    check_sh_function loop_mine_banner
    local banner
    CURRENT="the narrowed shape names the closure it did not walk"
    banner=$(loop_mine_banner open fast core)
    case "$banner" in
    *"the depends_on closure was NOT walked"*) ok "the open banner names the closure" ;;
    *) bad "the open banner does not name the closure: ${banner}" ;;
    esac
    case "$banner" in
    *"not banked: --mine"*) ok "and says it banks nothing" ;;
    *) bad "the open banner does not say it banks nothing: ${banner}" ;;
    esac
    CURRENT="the full shape does NOT claim a narrowing"
    banner=$(loop_mine_banner open full "")
    case "$banner" in
    *"the depends_on closure was NOT walked"*)
        bad "a --mine run that narrowed NOTHING (mode=full) still announces a narrowing: ${banner}"
        ;;
    *"nothing was narrowed"*) ok "the open banner says nothing was narrowed and the run is the full suite" ;;
    *) bad "the open banner says neither: ${banner}" ;;
    esac
    case "$banner" in
    *"not banked: --mine"*) ok "and it still banks nothing — the flag's no-bank half does not depend on the narrowing" ;;
    *) bad "a full-mode --mine run does not say it banks nothing: ${banner}" ;;
    esac
    CURRENT="the closing line names the apps the green is a claim about"
    banner=$(loop_mine_banner close fast core)
    case "$banner" in
    *"claim about [core]"*) ok "the close banner names [core]" ;;
    *) bad "the close banner does not name the own apps: ${banner}" ;;
    esac
    CURRENT="and does not name an empty list when there was no narrowing"
    banner=$(loop_mine_banner close full "")
    case "$banner" in
    *"claim about [-]"*) bad "the full-mode close banner claims a green about an empty app list: ${banner}" ;;
    *"narrowed nothing"*) ok "the full-mode close banner says the flag narrowed nothing" ;;
    *) bad "the full-mode close banner says neither: ${banner}" ;;
    esac
}

# --- the tests-only SELECTION, on this tree's real modules -------------------

MANIFEST_ALL=""
manifest_all() {
    # The organ classification of the whole tree, derived once: `<tier>\t<organs>
    # \t<nodeid>`. Used to name the organ-reaching tests a tests-only selection
    # must NOT contain — derived, never listed.
    [ -z "$MANIFEST_ALL" ] || return 0
    MANIFEST_ALL="${WORK}/manifest-all.tsv"
    collect_scope "the organ classification of this tree" --djb-tier-manifest="$MANIFEST_ALL"
    is "$RC" "0" "the classifying collection's exit status"
    [ -s "$MANIFEST_ALL" ] || cannot_look "the tier manifest came back empty — the classification is gone"
}

case_a_tests_only_comms_touch_is_not_own_and_widens_to_its_importers() {
    # CANARY A.4-3, and the one that is RED on today's shape: today
    # `apps/comms/tests/test_mcp.py` classifies `app`, `own=comms`, and comms'
    # organ tests run. Two halves — the CLASSIFICATION in a clone of this
    # checkout, and the SELECTION here, through the two flags check.sh passes.
    real_clone
    printf '\n' >>"$REAL_CLONE/apps/comms/tests/test_mcp.py"
    scope_in "$REAL_CLONE" "a tests-only comms touch, classified"
    is "$RC" "0" "the exit status"
    is "$LOOP_SCOPE_TESTS_ONLY" "comms" "the tests-only set"
    is "$LOOP_TIER_OWN_APPS" "" "the own-app list — comms is NOT own"
    is "$LOOP_SCOPE_APPS" "" "the derived scope — no closure walk"
    is "$LOOP_SCOPE_CHANGED_TESTS" "apps/comms/tests/test_mcp.py" "the edited test module"

    manifest_all
    collect_scope_memo whole "the whole collection, for the importer census"
    is "$RC" "0" "the whole collection's exit status"
    local full_log="$OUT" full_n
    full_n=$(collected_count "$full_log")

    collect_scope "the tests-only selection this tree really makes" \
        --djb-tier=fast --djb-scope-narrow \
        --djb-tests-only=comms --djb-changed-test=apps/comms/tests/test_mcp.py
    is "$RC" "0" "the tests-only collection's exit status"
    local only_log="$OUT" only_n
    only_n=$(collected_count "$only_log")

    CURRENT="the edited module is selected"
    if grep -qF "apps/comms/tests/test_mcp.py::" "$only_log"; then
        ok "the edited test module is in the selection"
    else
        bad "apps/comms/tests/test_mcp.py was NOT selected — the rung's own edit went ungraded"
    fi

    # THE IMPORTER WIDENING, DERIVED WITH THE SAME GREP AND ASSERTED AS AN
    # EQUALITY — no list. Every COLLECTED module whose source names
    # `apps.comms.tests` must be in the selection; the count is reported so a
    # widening that silently stopped answering cannot read as a narrow scope.
    #
    # RESTRICTED TO THE MODULES A FAST TIER CAN HOLD, and the restriction is the
    # rule rather than a convenience: the importer widening runs at the FAST
    # tier, so an importer whose every test reaches an organ is deselected by
    # the tier — correctly, and push-time. The manifest says which those are;
    # nothing here names one.
    local expected one importers=0 missing=""
    expected=$( (cd "$ROOT" && grep -rlF 'apps.comms.tests' apps --include='*.py') | sort -u)
    for one in $expected; do
        grep -qF "${one}::" "$full_log" || continue
        awk -F'\t' -v m="$one" '$1 == "fast" && index($3, m "::") == 1 {found = 1}
            END {exit found ? 0 : 1}' "$MANIFEST_ALL" || continue
        importers=$((importers + 1))
        grep -qF "${one}::" "$only_log" || missing="${missing} ${one}"
    done
    CURRENT="every collected module naming apps.comms.tests is selected"
    if [ "$importers" -lt 2 ]; then
        bad "only ${importers} collected module(s) name apps.comms.tests — the census this case compares against has emptied, so the equality proves nothing"
    elif [ -n "$missing" ]; then
        bad "the importer widening missed:${missing}"
    else
        ok "all ${importers} collected module(s) naming apps.comms.tests are selected"
    fi

    # COMMS' ORGAN TESTS ARE DESELECTED — the tests-only tier is FAST, and the
    # population is read off the manifest rather than named here.
    local slow_comms slow_n leaked=""
    slow_comms=$(awk -F'\t' '$1 == "slow" && $3 ~ /^apps\/comms\// {print $3}' "$MANIFEST_ALL")
    slow_n=$(printf '%s\n' "$slow_comms" | grep -c . || true)
    for one in $slow_comms; do
        grep -qF "$one" "$only_log" && leaked="$one"
    done
    CURRENT="comms' organ-reaching tests are deselected"
    if [ "$slow_n" -lt 1 ]; then
        bad "no organ-reaching comms test on this tree — this half cannot falsify"
    elif [ -n "$leaked" ]; then
        bad "an organ-reaching comms test is still selected: ${leaked}"
    else
        ok "all ${slow_n} organ-reaching comms test(s) deselected — the tests-only tier is FAST"
    fi

    CURRENT="a tests-only selection is a small fraction of the suite"
    if [ -n "$only_n" ] && [ -n "$full_n" ] && [ "$only_n" -lt "$full_n" ]; then
        ok "selected ${only_n} of ${full_n}"
    else
        bad "the tests-only selection collected '${only_n:-?}' of '${full_n:-?}' — it narrowed nothing"
    fi
}

case_the_edited_test_module_runs_whatever_tier_it_is_in() {
    # The half of the rule the FAST tier would otherwise take back: the module
    # the rung actually edited runs even when it reaches an organ. The subject is
    # derived off the manifest — an organ-reaching test module inside some app's
    # `tests/` tree — never named here.
    manifest_all
    local victim app
    victim=$(awk -F'\t' '$1 == "slow" && $3 ~ /^apps\/comms\/tests\// {split($3, a, "::"); print a[1]}' \
        "$MANIFEST_ALL" | sort -u | head -1)
    [ -n "$victim" ] || cannot_look "no organ-reaching module under apps/comms/tests/ — the subject is gone"
    app=comms
    collect_scope "the edited organ-reaching module is selected anyway" \
        --djb-tier=fast --djb-scope-narrow \
        "--djb-tests-only=${app}" "--djb-changed-test=${victim}"
    is "$RC" "0" "the exit status"
    CURRENT="the edited module survives the fast tier"
    if grep -qF "${victim}::" "$OUT"; then
        ok "${victim} is selected although it reaches an organ — it is what the rung changed"
    else
        bad "${victim} was deselected by the fast tier: the rung's own edit went ungraded"
    fi
}

case_a_files_touch_selects_the_exports_tests_through_the_closure() {
    # CANARY A.4-1, a KEEP: the closure still widens by the declarations
    # (`apps/exports/apps.py` declares `files`), and the tests-only row has not
    # taken that back.
    collect_scope_memo leaf "a files touch selects exports' tests through the closure" \
        --djb-tier=fast --djb-scope-narrow --djb-own-app=files \
        --djb-scope=files --djb-scope=exports
    is "$RC" "0" "the exit status"
    CURRENT="exports' tests are in the selection"
    if grep -q '^apps/exports/tests/' "$OUT"; then
        ok "apps/exports/tests/ is selected through the reverse depends_on closure"
    else
        bad "no apps/exports/tests/ nodeid in the selection — the closure stopped widening"
    fi
}

# ONE REAL `-n 2` RUN, TWO CASES, AND `-v` SERVES BOTH. The two cases asked
# byte-identical questions of the shipped leg — the banner's position relative
# to the first test result, and the banner's numbers against the counts files
# the same run wrote — and paid for two parallel pytest runs to do it. The
# difference was `-v` against `-q`, and `-v` prints everything `-q` does plus
# the per-test result lines the ordering case needs, so one run answers both.
# The memo is `bank_leg_run`'s, one section down: a drive that started this
# box's workers twice to assert two things about one run is paying the
# measurement twice.
PRERUN_COUNTS=""
PRERUN_READY=""
PRERUN_OUT=""
PRERUN_RC=0
prerun_xdist_once() {
    local name="$1"
    if [ -n "$PRERUN_READY" ]; then
        OUT="$PRERUN_OUT"
        RC="$PRERUN_RC"
        CURRENT="${name} (the -n 2 run, already taken)"
        capture_floor
        return 0
    fi
    CURRENT="$name"
    PRERUN_COUNTS="${WORK}/prerun-counts"
    drive_require_scratch PRERUN_COUNTS "${PRERUN_COUNTS:-}"
    rm -rf "$PRERUN_COUNTS"
    mkdir -p "$PRERUN_COUNTS"
    N=$((N + 1))
    OUT="${WORK}/prerun${N}.log"
    RC=0
    (cd "$ROOT" && "$PY" -m pytest -v -p no:randomly -n 2 \
        --djb-tier=fast --djb-scope-narrow "--djb-scope-counts=$PRERUN_COUNTS" \
        --djb-tests-only=comms --djb-changed-test=apps/comms/tests/test_mcp.py \
        -k test_the_namer_unwraps_and_never_reaches_for_repr) >"$OUT" 2>&1 || RC=$?
    capture_floor
    PRERUN_OUT="$OUT"
    PRERUN_RC="$RC"
    PRERUN_READY=1
}

case_the_banner_prints_every_decision_before_the_first_test() {
    # CONTRACT A.2. The counts are known only after a collection, and under
    # xdist the WORKERS collect — so the controller hook
    # `pytest_xdist_node_collection_finished` is where the pre-run banner can be
    # printed at all. The ordering is a fact, not a bet (review F2): the counts
    # file is written in `pytest_collection_modifyitems`, which pytest runs
    # before `pytest_collection_finish` sends the worker's `collectionfinish`
    # (xdist/remote.py:236,257; dsession.py:287), and the controller schedules
    # no test until every node has reported (dsession.py:297-305).
    #
    # MEASURED IN THE SHAPE THE GATE SHIPS: a real `-n 2`, not a serial
    # approximation. `-k` rather than a path, so every worker still performs the
    # FULL collection this case exists to read.
    prerun_xdist_once "the pre-run banner lands before the first test"
    is "$RC" "0" "the exit status"
    local banner_at first_test_at
    banner_at=$(grep -n 'scope   selected ' "$OUT" | head -1 | cut -d: -f1)
    first_test_at=$(grep -n 'PASSED' "$OUT" | head -1 | cut -d: -f1)
    CURRENT="the selected/deselected line exists"
    if [ -z "$banner_at" ]; then
        bad "no 'scope   selected' line in the run — the pre-run banner never printed"
        return
    fi
    ok "the pre-run banner printed at line ${banner_at}"
    CURRENT="it printed BEFORE the first test"
    if [ -z "$first_test_at" ]; then
        bad "no test result line to order against — the run selected nothing"
    elif [ "$banner_at" -lt "$first_test_at" ]; then
        ok "the banner (line ${banner_at}) precedes the first test result (line ${first_test_at})"
    else
        bad "the banner is at line ${banner_at} and the first test result at ${first_test_at} — it is an AFTER-run banner"
    fi
    # EVERY DECISION, one line each (contract A.2). The three the shell prints —
    # touched, closure, own, rule — are asserted by test_loop_tier.sh's wiring
    # case; these three are pytest's.
    local key
    for key in 'scope   tests-only:' 'scope   importers:' 'scope   always-on:'; do
        CURRENT="the banner prints '${key}'"
        if grep -qF "$key" "$OUT"; then
            ok "printed"
        else
            bad "the pre-run banner has no '${key}' line"
        fi
    done
}

case_the_pre_run_counts_agree_with_the_reconciliation() {
    # The pre-run numbers are the WORKERS' own, reconciled across every collector
    # before they are printed — so they must equal what the counts files say,
    # which is what scripts/check.sh reconciles again after the run. A banner
    # that printed one number and banked another would be worse than no banner.
    prerun_xdist_once "the pre-run counts agree with the counts files"
    is "$RC" "0" "the exit status"
    local files first n banner_selected banner_deselected file_selected file_deselected
    files=$(find "$PRERUN_COUNTS" -type f | sort)
    n=$(printf '%s\n' "$files" | grep -c . || true)
    CURRENT="every worker wrote its own counts file"
    if [ "$n" -lt 2 ]; then
        bad "only ${n} counts file(s) under -n 2 — this case measured a serial approximation"
        return
    fi
    ok "${n} collector files written under -n 2"
    first=$(printf '%s\n' "$files" | head -1)
    file_selected=$(awk -F= '/^selected=/ {print $2}' "$first")
    file_deselected=$(awk -F= '/^deselected=/ {print $2}' "$first")
    banner_selected=$(sed -n 's/.*scope   selected \([0-9][0-9]*\) .*/\1/p' "$OUT" | head -1)
    banner_deselected=$(sed -n 's/.*scope   selected [0-9][0-9]* · deselected \([0-9][0-9]*\).*/\1/p' "$OUT" | head -1)
    is "${banner_selected:-unset}" "${file_selected:-unset}" "the banner's selected count"
    is "${banner_deselected:-unset}" "${file_deselected:-unset}" "the banner's deselected count"
    CURRENT="the banner says how many collectors it reconciled"
    if grep -qF "reconciled across ${n} collectors" "$OUT"; then
        ok "the banner names ${n} collectors"
    else
        bad "the banner does not say it reconciled ${n} collectors"
    fi
}

# --- the importer widening, on a subject that can falsify it ------------------

case_a_tests_only_core_touch_widens_to_every_cross_app_importer() {
    # WHY `core` AND NOT `comms`. The comms case above asserts an equality over
    # a population that is entirely INSIDE `apps/comms/tests` on this tree: not
    # one collected module outside that directory names `apps.comms.tests`, so
    # the widening could do nothing whatever and the equality would still hold.
    # A world too small to falsify an assertion cannot assert it. `core` is the
    # subject that can: its test package is named from other apps' test modules,
    # which is the cross-app coupling the whole row exists for.
    #
    # THE FLOOR IS ASSERTED BEFORE THE RUN, and it is a could-not-look rather
    # than a failure: an EMPTY importer population is a census that has stopped
    # answering, and a case that greened on one would be the vacuity this case
    # was written to replace.
    manifest_all
    collect_scope_memo whole "the whole collection, for the core importer census"
    is "$RC" "0" "the whole collection's exit status"
    local full_log="$OUT"

    local population pop_n
    population=$( (cd "$ROOT" && grep -rlF 'apps.core.tests' apps --include='*.py') |
        { grep -v '^apps/core/tests/' || true; } | sort -u)
    pop_n=$(printf '%s\n' "$population" | grep -c . || true)
    CURRENT="the cross-app importer population is not empty"
    if [ "$pop_n" -lt 1 ]; then
        cannot_look "no module OUTSIDE apps/core/tests names apps.core.tests — the population this case measures has emptied, so the equality below would prove nothing"
    fi
    ok "${pop_n} module(s) outside apps/core/tests name apps.core.tests"

    # The edited module is derived off the tree, never named here: any collected
    # module under apps/core/tests/ is a `core` tests-only touch.
    local edited
    edited=$( { grep -o '^apps/core/tests/test_[a-z_]*\.py' "$full_log" || true; } | sort -u | head -1)
    [ -n "$edited" ] ||
        cannot_look "no collected module under apps/core/tests/ — the subject of a core tests-only touch is gone"

    collect_scope "the tests-only core selection this tree really makes" \
        --djb-tier=fast --djb-scope-narrow \
        --djb-tests-only=core "--djb-changed-test=${edited}"
    is "$RC" "0" "the tests-only collection's exit status"
    local only_log="$OUT"

    # THE EQUALITY, over the modules a FAST tier can hold. An importer whose
    # every test reaches an organ is deselected by the tier — correctly, and
    # push-time; the manifest says which those are and nothing here names one.
    local one importers=0 organ_only=0 missing=""
    for one in $population; do
        grep -qF "${one}::" "$full_log" || continue
        if ! awk -F'\t' -v m="$one" '$1 == "fast" && index($3, m "::") == 1 {found = 1}
            END {exit found ? 0 : 1}' "$MANIFEST_ALL"; then
            organ_only=$((organ_only + 1))
            continue
        fi
        importers=$((importers + 1))
        grep -qF "${one}::" "$only_log" || missing="${missing} ${one}"
    done
    CURRENT="every collected cross-app module naming apps.core.tests is selected"
    if [ "$importers" -lt 1 ]; then
        bad "not one collected fast-tier module outside apps/core/tests names apps.core.tests — the equality proves nothing"
    elif [ -n "$missing" ]; then
        bad "the importer widening missed:${missing}"
    else
        ok "all ${importers} cross-app importer module(s) selected (${organ_only} dropped as organ-only)"
    fi
}

# --- the pre-run banner's ABSENCE, named rather than silent -------------------

case_a_dying_collector_leaves_a_named_absence_not_silence() {
    # MEASURE THE LEG YOU SHIP. The pre-run banner rides
    # `pytest_xdist_node_collection_finished`, which prints only once EVERY node
    # has reported — so a collector that never reports takes the banner with it,
    # and an absent banner is indistinguishable from one that was never wired.
    # This builds the real state (a real `-n 2`, a real worker that exits during
    # collection, the real counts directory it leaves behind) and then reads it
    # with the printer the reconciliation calls.
    #
    # `--max-worker-restart=0` IS PART OF THE MEASUREMENT AND IS DECLARED.
    # Without it xdist REPLACES a collector that dies — measured here: eight
    # successive victims were replaced and the banner printed normally. The
    # silent absence therefore needs the restarts to be exhausted, which this
    # flag reaches in one step instead of by killing workers until xdist gives
    # up. What it does not change is the state the reconciliation reads: one
    # counts file where two collectors were asked for.
    local counts="${WORK}/dying-counts"
    local plant="${ROOT}/apps/test_zzz_dying_collector.py"
    drive_require_scratch counts "${counts:-}"
    rm -rf "$counts"
    mkdir -p "$counts"
    CURRENT="the plant's own path is free"
    if [ -e "$plant" ]; then
        cannot_look "apps/test_zzz_dying_collector.py already exists in this tree — this case will not overwrite a file it did not create"
    fi
    ok "apps/test_zzz_dying_collector.py is this case's to create"
    # Restored by the exit trap too, so a killed drive cannot leave a module in
    # the real tree that exits a worker whenever an environment variable is set.
    drive_at_exit "rm -f \"$plant\""
    cat >"$plant" <<'PLANT'
"""A collector that dies on purpose, so a drive can prove an absent banner is NAMED.

Inert unless a drive names a worker in DJB_DRIVE_KILL_COLLECTOR. When it is
named, it waits for the OTHER worker's counts file to appear before it goes:
the state this exists to build is "one collector reported, the other never
did", and a victim that died first would build "no collector reported", which
is a different refusal the gate already has.
"""

import os
import pathlib
import time

_victims = [v for v in os.environ.get("DJB_DRIVE_KILL_COLLECTOR", "").split(",") if v]
if os.environ.get("PYTEST_XDIST_WORKER", "") in _victims:
    _witness = pathlib.Path(os.environ.get("DJB_DRIVE_KILL_AFTER", "/nonexistent"))
    _deadline = time.time() + 60
    while not _witness.exists() and time.time() < _deadline:
        time.sleep(0.05)
    os._exit(1)


def test_zzz_dying_collector_is_inert_by_default() -> None:
    assert True
PLANT
    CURRENT="a collector that dies during collection"
    N=$((N + 1))
    OUT="${WORK}/dying${N}.log"
    RC=0
    (cd "$ROOT" && DJB_DRIVE_KILL_COLLECTOR=gw1 DJB_DRIVE_KILL_AFTER="${counts}/gw0" \
        "$PY" -m pytest -q -p no:randomly -n 2 --max-worker-restart=0 \
        --djb-tier=fast --djb-scope-narrow "--djb-scope-counts=$counts" \
        -k test_the_namer_unwraps_and_never_reaches_for_repr) >"$OUT" 2>&1 || RC=$?
    rm -f "$plant"

    local files n
    files=$(find "$counts" -type f | sort)
    n=$(printf '%s\n' "$files" | grep -c . || true)
    CURRENT="one collector of two reported"
    if [ "$n" = "1" ]; then
        ok "1 counts file under -n 2 — the second collector never reported"
    else
        bad "${n} counts file(s) under -n 2: this case did not build the state it exists to read"
        return
    fi
    CURRENT="the node's death is in the output"
    says "node down"
    CURRENT="the pre-run banner did NOT print"
    if grep -qF 'scope   selected ' "$OUT"; then
        bad "the pre-run banner printed although a collector never reported — this case can no longer build its own subject"
    else
        ok "no 'scope   selected' line: the banner is absent, which is the silence this case is about"
    fi

    # THE PRINTER, ON THE REAL STATE. `scripts/check.sh`'s reconciliation calls
    # it with the same two numbers: the counts files it found, and the workers
    # it asked for.
    CURRENT="the absence is named with its count"
    N=$((N + 1))
    OUT="${WORK}/absence${N}.log"
    loop_scope__prerun_absence "$n" 2 >"$OUT" 2>&1
    says "the pre-run banner did not fire (1 of 2 collectors reported)"
    CURRENT="a complete report prints nothing at all"
    N=$((N + 1))
    OUT="${WORK}/absence-quiet${N}.log"
    loop_scope__prerun_absence 2 2 >"$OUT" 2>&1
    if [ -s "$OUT" ]; then
        bad "the printer spoke when every collector reported: $(head -1 "$OUT")"
    else
        ok "silent when 2 of 2 reported — an absence named only when there is one"
    fi

    # AND IT IS WIRED. The reconciliation is the only reader; a printer nothing
    # calls is the same silence with more code in it.
    CURRENT="the --loop reconciliation calls the printer"
    if grep -q 'loop_scope__prerun_absence' "${ROOT}/scripts/check.sh"; then
        ok "scripts/check.sh calls loop_scope__prerun_absence"
    else
        bad "scripts/check.sh never calls loop_scope__prerun_absence — the absence is printed by nobody"
    fi

    # AND THE SHORTFALL IS A REFUSAL, NOT A NOTE. The state this case just built
    # is the dangerous one: pytest can exit 0 from it (the survivors ran what
    # they held, and "no tests ran" is not a failure), so a printed absence
    # beside a green verdict banks a row for a suite that did not run. The
    # refusal is `scripts/check.sh`'s own function, run here over the real
    # numbers this case measured.
    CURRENT="pytest's own status from a dead collector is not a verdict"
    ok "pytest exited ${RC:-0} with ${n} of 2 collectors — which is why the shell refuses rather than reading it"
    check_sh_function loop_counts_refuse_if_short
    CURRENT="one collector short of the number the leg started is exit 2"
    N=$((N + 1))
    OUT="${WORK}/counts-short${N}.log"
    RC=0
    loop_counts_refuse_if_short "$n" 2 >"$OUT" 2>&1 || RC=$?
    is "$RC" "2" "the refusal's exit status"
    says "1 of 2 collectors reported — a collector died and the suite that ran is not the suite that was asked for; nothing is judged"
    says "No verdict is banked."
    CURRENT="and a full report is not refused"
    N=$((N + 1))
    OUT="${WORK}/counts-full${N}.log"
    RC=0
    loop_counts_refuse_if_short 2 2 >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the exit status when every collector reported"
    if [ -s "$OUT" ]; then
        bad "the refusal spoke when 2 of 2 reported: $(head -1 "$OUT")"
    else
        ok "silent and 0 when the population is whole"
    fi
    CURRENT="an unknown population is not refused into a red"
    N=$((N + 1))
    OUT="${WORK}/counts-unknown${N}.log"
    RC=0
    loop_counts_refuse_if_short 1 0 >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the exit status when the leg never said how many collectors it started"

    # WIRED, AND WIRED ABOVE THE BANK. A refusal that ran after the verdict was
    # written would print a sentence about a row that already exists.
    CURRENT="the --loop reconciliation calls the refusal"
    if grep -q 'loop_counts_refuse_if_short "\$LOOP_COUNT_N"' "${ROOT}/scripts/check.sh"; then
        ok "scripts/check.sh calls loop_counts_refuse_if_short with the files it found"
    else
        bad "scripts/check.sh never calls loop_counts_refuse_if_short — a short collection would bank a verdict again"
    fi
    CURRENT="and it is reached before anything is banked"
    local refuse_line bank_line
    refuse_line=$(first_call_line 'loop_counts_refuse_if_short "$LOOP_COUNT_N"' "${ROOT}/scripts/check.sh")
    bank_line=$(first_call_line 'loop_ledger_record ' "${ROOT}/scripts/check.sh")
    if [ -n "$refuse_line" ] && [ -n "$bank_line" ] && [ "$refuse_line" -lt "$bank_line" ]; then
        ok "the refusal (line ${refuse_line}) is above the bank (line ${bank_line})"
    else
        bad "the refusal at line '${refuse_line:-<none>}' does not precede the bank at '${bank_line:-<none>}' — a short collection could still bank"
    fi

    # AND IT CARRIES ITS CAUSE THROUGH THE ONE SEAM. The refusal used to print
    # its `!!` line with a bare `echo`, so the banner three lines down read the
    # callee-set-none sentence: a reader with no scrollback was told that the
    # scope could not be reconciled and NOT what the collectors did. The text is
    # byte-identical (asserted above); what is asserted here is that it was also
    # REMEMBERED (scripts/gate_refuse.sh, the B4 family).
    CURRENT="the shortfall refusal RECORDS its first line"
    gate_refuse_reset
    N=$((N + 1))
    OUT="${WORK}/counts-cause${N}.log"
    RC=0
    loop_counts_refuse_if_short 1 2 >"$OUT" 2>&1 || RC=$?
    is "$RC" "2" "the refusal's exit status"
    cause_recorded "1 of 2 collectors reported"
    CURRENT="and the --loop reconciliation prints a cause line for it"
    if grep -qF 'cause: ${GATE_LAST_REFUSAL}' "${ROOT}/scripts/check.sh" &&
        grep -qF 'the --loop scope could not be RECONCILED — see above.' "${ROOT}/scripts/check.sh"; then
        ok "scripts/check.sh banners the reconciliation's refusal with its cause"
    else
        bad "the --loop reconciliation exits 2 with no cause banner — the shortfall's sentence never reaches a reader without the scrollback"
    fi
}

# --- the worker count: ONE derivation, and the documented knob honoured by it --
#
# THE FALSE RED THIS PAIR CLOSES, and it was found on a CONTROL run rather than
# a plant: with `DJB_GATE_SLOT_WORKERS` set — a knob `scripts/test.sh` reads and
# `apps/conftest.py`'s ceiling reads FIRST — every `--loop` exited 2 on a clean
# suite. The gate started `-n <derived share>`, pytest clamped ITSELF down to the
# typed value, and the shortfall refusal above compared the survivors against the
# PRE-CLAMP number: `2 of 5 collectors reported — a collector died`, on a tree
# where nothing had died at all. Two answers to "how many collectors" is how a
# floor stops binding, and this is what it looks like when it stops binding in
# the loud direction.

case_a_typed_slot_share_is_the_workers_number_and_no_clamp_fires() {
    local total share counts="${WORK}/typed-counts" n
    total=$(gate_slots_total)
    share=$(gate_slot_workers "$total")

    # A PROBE WORLD TOO SMALL TO FALSIFY, SAID OUT LOUD. The claim is that a
    # typed value STRICTLY BELOW the share is honoured; on a box whose share is
    # already 2 or less there is no such value to type, and a case that "passed"
    # there would be a case that could not fail.
    CURRENT="this box can falsify the claim"
    if [ "$share" -le 2 ]; then
        ok "SKIPPED — this box's slot share is ${share}, so no typed value is strictly below it; nothing was asserted and this line is the disclosure"
        return
    fi
    ok "the share is ${share}, so a typed 2 is strictly below it"

    CURRENT="a typed share at or below this slot's IS the workers number"
    GATE_SLOT_WORKERS=""
    GATE_SLOT_WORKERS_PROV=""
    gate_refuse_reset
    N=$((N + 1))
    OUT="${WORK}/typed-derive${N}.log"
    RC=0
    DJB_GATE_SLOT_WORKERS=2 gate_slot_worker_count "$total" >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the derivation's exit status"
    is "${GATE_SLOT_WORKERS}" "2" "GATE_SLOT_WORKERS"
    CURRENT="and it prints where the number came from"
    says "workers:    -n 2 (typed: DJB_GATE_SLOT_WORKERS, at or below this slot's share of ${share})"

    # MEASURE THE LEG YOU SHIP: a REAL `-n` at the number the derivation just
    # produced, with the counts directory the leg passes, and no plant anywhere.
    drive_require_scratch counts "${counts:-}"
    rm -rf "$counts"
    mkdir -p "$counts"
    CURRENT="the leg's own -n starts exactly that many collectors"
    N=$((N + 1))
    OUT="${WORK}/typed-run${N}.log"
    RC=0
    (cd "$ROOT" && DJB_GATE_SLOT_WORKERS=2 "$PY" -m pytest -q -p no:randomly -n "$GATE_SLOT_WORKERS" \
        --djb-tier=fast --djb-scope-narrow "--djb-scope-counts=$counts" \
        -k test_the_namer_unwraps_and_never_reaches_for_repr) >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the exit status of the clean run"
    CURRENT="and the python ceiling has nothing left to lower"
    if grep -qF 'clamped -n' "$OUT"; then
        bad "the clamp fired inside the gate's own -n — the shell and pytest are answering with two different numbers again"
    else
        ok "no 'clamped' line: -n and the ceiling are one number"
    fi
    n=$(find "$counts" -type f | wc -l | tr -d ' ')
    CURRENT="the expected population is the population that collected"
    is "$n" "$GATE_SLOT_WORKERS" "the counts files found"
    CURRENT="so the shortfall refusal is silent on a clean suite with the knob set"
    N=$((N + 1))
    OUT="${WORK}/typed-refuse${N}.log"
    RC=0
    loop_counts_refuse_if_short "$n" "$GATE_SLOT_WORKERS" >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the refusal's exit status"
    if grep -qF 'collectors reported' "$OUT"; then
        bad "the shortfall refusal fired on a clean suite: the false red is back"
    else
        ok "silent — ${n} of ${GATE_SLOT_WORKERS}, not ${n} of ${share}"
    fi

    # AND THE GATE ASKS THIS FUNCTION, not `gate_slot_workers` directly. A
    # derivation nothing calls is the same two numbers with more code in it.
    CURRENT="gate_slot_acquire takes its number from this derivation"
    if grep -qF 'gate_slot_worker_count "$total"' "${ROOT}/scripts/gate_lease.sh"; then
        ok "gate_slot_acquire calls gate_slot_worker_count"
    else
        bad "gate_slot_acquire does not call gate_slot_worker_count — the knob is unhonoured at the source again"
    fi
    GATE_SLOT_WORKERS=""
    GATE_SLOT_WORKERS_PROV=""
    # AND THE HAND-DOWN GOES BACK. The derivation EXPORTS the number it resolved
    # (scripts/gate_lease.sh: the gate hands its share down to `scripts/test.sh`
    # and to the python ceiling), and an export outlives the command prefix that
    # set the knob — so a case below that measures the DERIVED ceiling would be
    # measuring this case's typed 2. `gate_slot_release` is where the gate itself
    # gives it back; this drive is not the gate, so it gives it back here.
    unset DJB_GATE_SLOT_WORKERS
}

case_a_typed_share_above_the_slot_is_refused_naming_both() {
    local total share over
    total=$(gate_slots_total)
    share=$(gate_slot_workers "$total")
    over=$((share + 1))

    # REFUSED, NOT CLAMPED, and the direction is the whole argument: a knob that
    # NARROWS a slot costs its own run and nobody else's, while a knob that
    # WIDENS one spends the share of every gate that is still believing in its
    # own — which is the oversubscription the semaphore exists to stop. A silent
    # lowering would also teach the knob's reader that what they typed is what
    # ran.
    CURRENT="one above the share is refused, naming both numbers"
    gate_refuse_reset
    N=$((N + 1))
    OUT="${WORK}/typed-over${N}.log"
    RC=0
    DJB_GATE_SLOT_WORKERS="$over" gate_slot_worker_count "$total" >"$OUT" 2>&1 || RC=$?
    is "$RC" "2" "the exit status"
    says "DJB_GATE_SLOT_WORKERS=${over} is ABOVE this slot's share of ${share}."
    says "Nothing was judged: no slot was taken and no suite started."
    cause_recorded "is ABOVE this slot's share"

    # The plan's own number, where this box is small enough for it to be above
    # the share. Skipped out loud rather than silently on a box that is not.
    CURRENT="the documented example value is refused too"
    if [ "$share" -lt 99 ]; then
        gate_refuse_reset
        N=$((N + 1))
        OUT="${WORK}/typed-99-${N}.log"
        RC=0
        DJB_GATE_SLOT_WORKERS=99 gate_slot_worker_count "$total" >"$OUT" 2>&1 || RC=$?
        is "$RC" "2" "the exit status for 99"
        says "DJB_GATE_SLOT_WORKERS=99 is ABOVE this slot's share of ${share}."
    else
        ok "SKIPPED — this box's share is ${share}, so 99 is not above it; the boundary case above is the assertion"
    fi

    CURRENT="an unreadable value is exit 2, as DJB_GATE_SLOTS already is"
    gate_refuse_reset
    N=$((N + 1))
    OUT="${WORK}/typed-junk${N}.log"
    RC=0
    DJB_GATE_SLOT_WORKERS="two" gate_slot_worker_count "$total" >"$OUT" 2>&1 || RC=$?
    is "$RC" "2" "the exit status"
    says "is not a positive whole number."
    cause_recorded "is not a positive whole number"

    CURRENT="and zero is refused rather than read as 'no ceiling'"
    gate_refuse_reset
    N=$((N + 1))
    OUT="${WORK}/typed-zero${N}.log"
    RC=0
    DJB_GATE_SLOT_WORKERS=0 gate_slot_worker_count "$total" >"$OUT" 2>&1 || RC=$?
    is "$RC" "2" "the exit status"

    CURRENT="the share itself is honoured, so the refusal is a ceiling and not a ban"
    gate_refuse_reset
    GATE_SLOT_WORKERS=""
    N=$((N + 1))
    OUT="${WORK}/typed-at${N}.log"
    RC=0
    DJB_GATE_SLOT_WORKERS="$share" gate_slot_worker_count "$total" >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the exit status at the share"
    is "$GATE_SLOT_WORKERS" "$share" "GATE_SLOT_WORKERS at the share"
    GATE_SLOT_WORKERS=""
    GATE_SLOT_WORKERS_PROV=""
    # AND THE HAND-DOWN GOES BACK, because this case is not the gate. The
    # derivation now EXPORTS the number it resolved (scripts/gate_lease.sh — the
    # gate hands its share down to `scripts/test.sh` and the python ceiling), and
    # an export outlives the command prefix that set the knob: a case below that
    # measures the DERIVED ceiling would be measuring this case's typed value.
    unset DJB_GATE_SLOT_WORKERS

    # AND IT IS REFUSED ABOVE THE SLOT. A run that was never going to be legal
    # must not queue for the box first — the `--pr` refusals' own property, one
    # guard over.
    CURRENT="the derivation sits above the slot attempt"
    local derive_line try_line
    derive_line=$(first_call_line 'gate_slot_worker_count "$total"' "${ROOT}/scripts/gate_lease.sh")
    try_line=$(first_call_line 'gate_slot_try "$mode"' "${ROOT}/scripts/gate_lease.sh")
    if [ -n "$derive_line" ] && [ -n "$try_line" ] && [ "$derive_line" -lt "$try_line" ]; then
        ok "the derivation (line ${derive_line}) is above the first slot attempt (line ${try_line})"
    else
        bad "the derivation at '${derive_line:-<none>}' does not precede the slot attempt at '${try_line:-<none>}' — an unhonourable number would wait for the box before being refused"
    fi
}

# --- THE BANK'S SHARE: one number, three readers -------------------------------
#
# THE MISS, AND IT COST THE FIRST LIVE MERGE-TRAIN BANK (bank-2349.log,
# 2026-09-16). `--bank` holds EVERY pytest slot, so its share is the whole box's
# cores; the leg started `-n 10` and said so. `apps/conftest.py`'s worker ceiling
# found nothing handed down, DERIVED one slot's share of its own (5), clamped the
# leg to it, and pytest created five workers and passed 3653 tests — over which
# the collector census, still expecting one collector per worker ASKED for,
# printed `5 of 10 collectors reported — a collector died`, exit 2, nothing
# banked, nothing pushed. Two mechanisms held different numbers for one run and
# every one of them was behaving exactly as written.
#
# THE TWO HALVES, AND EACH HAS ITS OWN CASE BELOW. (1) The derivation EXPORTS the
# share it resolved, under the one name the ceiling and `scripts/test.sh` already
# read, so there is nothing left for the ceiling to derive. (2) The census's
# expected population is what pytest CREATED — every collector writes
# `workers=<workercount>` into its own counts file — so the census can no longer
# be told a number the run disagrees with, whatever else changes.
#
# NO SLOT IS TAKEN, AND THAT IS DELIBERATE. `gate_slot_worker_count` is the call
# `gate_slot_acquire bank` makes for the number, and its own header says it
# "never takes a slot and starts nothing, which is what lets a drive ask it the
# question the gate asks". A drive that acquired a REAL bank would stop every
# builder on this machine in order to prove an integer.

BANK_READY=""
BANK_COUNTS="${WORK}/bank-counts"
BANK_OUT=""
BANK_RC=0
BANK_WORKERS=""
BANK_SLOT_SHARE=""
BANK_BOX=""
BANK_HANDED=""
BANK_TOTAL=2

bank_leg_run() {
    # ONE REAL RUN AT THE BANK'S `-n`, shared by both cases and memoised, because
    # the number under test is this box's whole core count and starting that many
    # workers twice to assert two different things about one run would be paying
    # the measurement twice. Either case alone calls this and gets it.
    [ -z "$BANK_READY" ] || return 0
    check_sh_function loop_counts_refuse_if_short
    drive_require_scratch BANK_COUNTS "${BANK_COUNTS:-}"
    rm -rf "$BANK_COUNTS"
    mkdir -p "$BANK_COUNTS"

    # THE SHIMMED BOX: two slots, whatever this machine's cores are. The slot
    # share is one slot's (`gate_slot_workers`); the bank's is the box's
    # (`gate_slot_cores`) — the exact second argument `gate_slot_acquire bank`
    # passes, and the whole reason the two numbers can differ at all.
    BANK_SLOT_SHARE=$(gate_slot_workers "$BANK_TOTAL")
    BANK_BOX=$(gate_slot_cores)

    unset DJB_GATE_SLOT_WORKERS
    GATE_SLOT_WORKERS=""
    GATE_SLOT_WORKERS_PROV=""
    gate_refuse_reset
    RC=0
    gate_slot_worker_count "$BANK_TOTAL" "$BANK_BOX" >"${WORK}/bank-derive.log" 2>&1 || RC=$?
    [ "$RC" = "0" ] ||
        cannot_look "the bank's own derivation refused on this box — gate_slot_worker_count ${BANK_TOTAL} ${BANK_BOX} exited ${RC}, so nothing below could be measured"
    BANK_WORKERS="$GATE_SLOT_WORKERS"
    # What the leg's own environment carries into the suite, captured BEFORE the
    # run so a later `unset` cannot make this look true.
    BANK_HANDED="${DJB_GATE_SLOT_WORKERS:-<unset>}"

    # THE LEG IN THE SHAPE THE GATE RUNS IT: the bank's `-n`, the counts
    # directory both pytest legs pass, and NO `-q` — xdist prints
    # `created: N/N workers` in the report header, which is the run's own answer
    # to the question the census asks, and `-q` is what hides it.
    BANK_OUT="${WORK}/bank-run.log"
    BANK_RC=0
    (cd "$ROOT" && "$PY" -m pytest -p no:randomly -n "$BANK_WORKERS" \
        --djb-tier=fast --djb-scope-narrow "--djb-scope-counts=$BANK_COUNTS" \
        -k test_the_namer_unwraps_and_never_reaches_for_repr) >"$BANK_OUT" 2>&1 || BANK_RC=$?
    # GIVEN BACK HERE, exactly as `gate_slot_release` gives it back in the gate:
    # every case after these two measures the DERIVED ceiling, and a whole-box
    # share left in this drive's environment would silently become theirs.
    unset DJB_GATE_SLOT_WORKERS
    GATE_SLOT_WORKERS=""
    GATE_SLOT_WORKERS_PROV=""
    BANK_READY=1
}

case_a_bank_runs_every_slots_share_and_the_census_agrees() {
    local n first recorded
    bank_leg_run

    CURRENT="a bank's share is every slot's share, not one slot's"
    is "$BANK_WORKERS" "$BANK_BOX" "the -n the bank leg starts"
    if [ "$((BANK_SLOT_SHARE * BANK_TOTAL))" = "$BANK_BOX" ]; then
        ok "and ${BANK_TOTAL} x ${BANK_SLOT_SHARE} = ${BANK_BOX}: the bank runs every slot's share"
    else
        ok "SKIPPED — this box's ${BANK_BOX} cores do not divide into ${BANK_TOTAL} slots of ${BANK_SLOT_SHARE} exactly; the assertion above is the claim and this line is the disclosure"
    fi

    CURRENT="the derivation hands the share down to the suite"
    is "$BANK_HANDED" "$BANK_WORKERS" "DJB_GATE_SLOT_WORKERS in the leg's environment"

    OUT="$BANK_OUT"
    CURRENT="so the python ceiling has nothing left to lower"
    if grep -qF 'clamped -n' "$OUT"; then
        bad "the clamp fired inside the bank's own -n — the shell and pytest are answering with two different numbers again, which is the ${BANK_SLOT_SHARE} of ${BANK_BOX} that banked nothing"
    else
        ok "no 'clamped' line: the bank's -n and the ceiling are one number"
    fi
    CURRENT="and pytest created the workers the leg asked for"
    says "created: ${BANK_WORKERS}/${BANK_WORKERS} workers"
    is "$BANK_RC" "0" "the leg's exit status"

    CURRENT="every collector reported, and each one recorded the population it belongs to"
    n=$(find "$BANK_COUNTS" -type f | wc -l | tr -d ' ')
    is "$n" "$BANK_WORKERS" "the counts files found"
    first=$(find "$BANK_COUNTS" -type f | sort | head -1)
    recorded=$(awk -F= '$1 == "workers" { print $2; exit }' "$first")
    is "$recorded" "$BANK_WORKERS" "the workers= the collectors recorded"

    CURRENT="so the census is silent, and the verdict banks"
    gate_refuse_reset
    N=$((N + 1))
    OUT="${WORK}/bank-census${N}.log"
    RC=0
    loop_counts_refuse_if_short "$n" "$BANK_WORKERS" "$first" >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the census's exit status"
    if grep -qF 'collectors reported' "$OUT"; then
        bad "the shortfall refusal fired on a complete bank: the false red is back"
    else
        ok "silent — ${n} of ${BANK_WORKERS}"
    fi

    # THE LOAD-BEARING HALF OF HB.2. Hand the census the number that was ASKED
    # FOR BEFORE A CLAMP — twice the population that ran — and it still reads the
    # run's own answer out of the collectors' files. That is what makes "the
    # census counts what ran" a mechanism rather than a coincidence of the export
    # above: the two halves fail independently, and this case can tell them apart.
    CURRENT="and it counts what RAN even when handed the pre-clamp number"
    gate_refuse_reset
    N=$((N + 1))
    OUT="${WORK}/bank-preclamp${N}.log"
    RC=0
    loop_counts_refuse_if_short "$n" "$((BANK_WORKERS * 2))" "$first" >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the census's exit status with $((BANK_WORKERS * 2)) asked for and ${n} created"
    if grep -qF 'collectors reported' "$OUT"; then
        bad "the census believed the pre-clamp number over the collectors' own — this is tonight's ${BANK_SLOT_SHARE} of ${BANK_BOX}, one layer down"
    else
        ok "silent: the collectors' workers=${recorded} outranks the ${BANK_WORKERS} x 2 it was told"
    fi

    # AND THE SHARE BELONGS TO THE SLOT. A whole-box share left exported after the
    # box has been given back is a ceiling that is true of nothing, and every leg
    # the full gate runs after the suite would inherit it — the self-test leg's
    # drives included, which measure the DERIVED ceiling.
    CURRENT="the release gives the share back"
    gate_slot_release >/dev/null 2>&1
    is "${DJB_GATE_SLOT_WORKERS:-<unset>}" "<unset>" "DJB_GATE_SLOT_WORKERS after gate_slot_release"
    local release_line
    release_line=$(first_call_line 'unset DJB_GATE_SLOT_WORKERS' "${ROOT}/scripts/gate_lease.sh")
    if [ -n "$release_line" ]; then
        ok "scripts/gate_lease.sh unsets it (line ${release_line})"
    else
        bad "scripts/gate_lease.sh never unsets DJB_GATE_SLOT_WORKERS — the released bank's share outlives the box"
    fi
}

case_a_dead_collector_under_a_bank_still_refuses() {
    # THE OTHER DIRECTION, AND THE ONE THAT MATTERS MOST: the census was widened
    # to read the run's own population, so the thing to prove is that it did not
    # become unable to fail. One collector's file removed from a complete bank is
    # exactly the state the refusal exists for — a worker that died during
    # collection, which pytest can still exit 0 from.
    local scratch="${WORK}/bank-dead" n first
    bank_leg_run
    drive_require_scratch scratch "${scratch:-}"
    rm -rf "$scratch"
    mkdir -p "$scratch"
    cp "$BANK_COUNTS"/* "$scratch"/
    rm -f "$(find "$scratch" -type f | sort | tail -1)"
    n=$(find "$scratch" -type f | wc -l | tr -d ' ')
    first=$(find "$scratch" -type f | sort | head -1)

    CURRENT="one collector short of a full bank is still a refusal"
    gate_refuse_reset
    N=$((N + 1))
    OUT="${WORK}/bank-dead${N}.log"
    RC=0
    loop_counts_refuse_if_short "$n" "$BANK_WORKERS" "$first" >"$OUT" 2>&1 || RC=$?
    is "$RC" "2" "the census's exit status"
    says "${n} of ${BANK_WORKERS} collectors reported — a collector died"
    says "No verdict is banked."
    cause_recorded "collectors reported"

    # AND THE SENTENCE IS UNCHANGED, which is not decoration: the drives above,
    # `scripts/check.sh`'s own banner and every transcript a reader has ever
    # grepped all name this text. Widening where the number comes from must not
    # move the words it is printed in.
    CURRENT="and the survivors' own file cannot talk it out of refusing"
    if grep -qF "${n} of ${BANK_WORKERS}" "$OUT"; then
        ok "the surviving collectors still say workers=${BANK_WORKERS}, so ${n} of them is short"
    else
        bad "the refusal did not name ${n} of ${BANK_WORKERS} — the population the survivors recorded was lost"
    fi
}

# --- the collector population under the gate that BANKS ------------------------
#
# THE DEFECT, AND IT IS THE DANGEROUS DIRECTION. The shortfall refusal above
# bound under `--loop` alone: `--djb-scope-counts` was assigned at one site
# inside the `--loop` block, so the FULL gate's two passes carried no counts
# directory, there were no files to reconcile, and the refusal was never
# reached. Measured on this tree — a worker that exits during collection with
# xdist's restart budget exhausted leaves pytest able to exit **0** printing
# `no tests ran`, and 0 is the one status the full gate reads as "this tree is
# clean". A full gate that lost a collector banked a green verdict for a suite
# that had not run, and the only tell was a line in the middle of a passing
# transcript.
#
# THE LEG BODY, NEVER A NESTED GATE. A drive may not run `./scripts/check.sh`
# inside one — the per-checkout lock refuses it — so these cases source the leg's
# own functions out of the file that ships them and drive those over real state.

X2_READY=""
x2_leg_body() {
    [ -z "$X2_READY" ] || return 0
    # The four the leg is made of: the two passes and the reconciliation between
    # them, the reconciliation's reader, the pass-2 explainer it calls on a red,
    # and the shortfall refusal underneath both.
    check_sh_function loop_counts_refuse_if_short
    check_sh_function pytest_x2_counts_refuse
    check_sh_function pytest_x2_verdict
    check_sh_function pytest_x2_passes
    # THE TICKER IS NOT THIS DRIVE'S BUSINESS, stubbed for the reason the
    # EXIT-trap case stubs its neighbours: a drive that had to start a heartbeat
    # in order to measure a reconciliation would be measuring the heartbeat.
    heartbeat_label() { :; }
    heartbeat_stop() { :; }
    X2_READY=1
}

X2_PLANT="${ROOT}/apps/test_zzz_g1_full_collector.py"
X2_PLANTED=""
x2_plant() {
    # A DESTRUCTIVE DEMONSTRATION BUILDS ITS OWN VICTIM. The module below is
    # created by this drive at a name no product can own, and removed by the case
    # and by the exit trap both — so a killed run cannot leave a module in the
    # real tree that exits a worker whenever an environment variable is set.
    CURRENT="the plant's own path is free"
    if [ -e "$X2_PLANT" ] && [ -z "$X2_PLANTED" ]; then
        cannot_look "apps/test_zzz_g1_full_collector.py already exists in this tree — this case will not overwrite a file it did not create"
    fi
    if [ -z "$X2_PLANTED" ]; then
        ok "apps/test_zzz_g1_full_collector.py is this drive's to create"
        drive_at_exit "rm -f \"$X2_PLANT\""
        X2_PLANTED=1
    else
        ok "the plant is this drive's, from an earlier case"
    fi
    cat >"$X2_PLANT" <<'PLANT'
"""A collector that dies on purpose, so a drive can prove the FULL gate refuses.

Inert unless a drive names a worker in DJB_DRIVE_KILL_COLLECTOR. When it is
named, it waits for the OTHER worker's counts file to appear before it goes:
the state this exists to build is "one collector reported, the other never
did", which is the state a full gate used to bank a green verdict over.
"""

import os
import pathlib
import time

_victims = [v for v in os.environ.get("DJB_DRIVE_KILL_COLLECTOR", "").split(",") if v]
if os.environ.get("PYTEST_XDIST_WORKER", "") in _victims:
    _witness = pathlib.Path(os.environ.get("DJB_DRIVE_KILL_AFTER", "/nonexistent"))
    _deadline = time.time() + 60
    while not _witness.exists() and time.time() < _deadline:
        time.sleep(0.05)
    os._exit(1)


def test_zzz_g1_full_collector_is_inert_by_default() -> None:
    assert True
PLANT
}

# The two tests this drive's `-k` selects: one real test of this tree's, and the
# plant's own inert one. Named once so the three cases below cannot drift apart.
X2_K="test_the_namer_unwraps_and_never_reaches_for_repr or test_zzz_g1_full_collector_is_inert_by_default"

# A SCRATCH LEDGER, AND IT IS THE MEASUREMENT RATHER THAN A CONVENIENCE. The
# claim is that the LEG BODY writes no verdict row, and the before/after count
# used to be taken over the real `djb-gate-verdicts` — one file SHARED by every
# worktree of this repository through `--git-common-dir`. A peer's bank
# appending a row between the two counts reds this case for somebody else's
# work (measured: 274 before, 275 after, while BANK-12 ran on the primary), and
# the same peer writing nothing would have hidden a row this run really wrote.
# Pointed at a file of this drive's own, the count answers about this run and
# only this run.
X2_LEDGER=""
x2_ledger_rows() {
    [ -n "$X2_LEDGER" ] || return 1
    if [ -f "$X2_LEDGER" ]; then
        wc -l <"$X2_LEDGER" | tr -d ' '
    else
        echo 0
    fi
}

case_a_dying_collector_under_the_full_gate_leg_body_is_exit_2_and_banks_nothing() {
    local counts="${WORK}/full-counts" rows_before rows_after
    x2_leg_body
    x2_plant
    drive_require_scratch counts "${counts:-}"
    rm -rf "$counts"
    mkdir -p "$counts"
    X2_LEDGER="${WORK}/x2-verdicts"
    drive_require_scratch X2_LEDGER "${X2_LEDGER:-}"
    : >"$X2_LEDGER"
    rows_before=$(x2_ledger_rows)

    # `--max-worker-restart=0` IS PART OF THE MEASUREMENT AND IS DECLARED, for
    # the reason the `--loop` case beside it states: without it xdist REPLACES a
    # collector that dies and the state this case exists to build never forms.
    GATE_SLOT_WORKERS=2
    PYTEST_SEED=1
    GATE_X2_COUNTS_DIR="$counts"
    CURRENT="a dying collector under the FULL gate's leg body"
    N=$((N + 1))
    OUT="${WORK}/x2full${N}.log"
    RC=0
    (cd "$ROOT" && DJB_GATE_LEDGER="$X2_LEDGER" \
        DJB_DRIVE_KILL_COLLECTOR=gw1 DJB_DRIVE_KILL_AFTER="${counts}/gw0" \
        pytest_x2_passes --max-worker-restart=0 "--djb-scope-counts=$counts" \
        -k "$X2_K") >"$OUT" 2>&1 || RC=$?
    is "$RC" "2" "the leg body's exit status"
    says "1 of 2 collectors reported"
    says "the two pytest passes could not be RECONCILED — see above."
    says "cause: 1 of 2 collectors reported"
    CURRENT="and it is could-not-look, never pytest's own status"
    if grep -qE 'no tests ran|node down' "$OUT"; then
        ok "pytest itself printed the state it exits 0 from — which is why the shell refuses instead of reading it"
    else
        bad "this case did not build the state it exists to read: no dead node in the transcript"
    fi

    # BANKED NOTHING, MEASURED RATHER THAN ARGUED. The leg body itself writes no
    # verdict — the bank is the caller's — so what is falsifiable here is that
    # this run added no row to the ledger the caller would have written into,
    # and that the caller's refusal sits above every writer.
    CURRENT="the verdict ledger gained no row"
    rows_after=$(x2_ledger_rows)
    is "$rows_after" "$rows_before" "the verdict ledger's row count"
    CURRENT="and the refusal is above everything that banks"
    local x2_line partition_line verdict_line
    x2_line=$(first_call_line 'pytest_x2_passes $X2_PASS_ARGS' "${ROOT}/scripts/check.sh")
    partition_line=$(first_call_line 'quality.partition bank' "${ROOT}/scripts/check.sh")
    verdict_line=$(first_call_line 'gate_ledger_record ' "${ROOT}/scripts/check.sh")
    if [ -n "$x2_line" ] && [ -n "$partition_line" ] && [ "$x2_line" -lt "$partition_line" ]; then
        ok "the passes (line ${x2_line}) are above the partition bank (line ${partition_line})"
    else
        bad "the passes at '${x2_line:-<none>}' do not precede the partition bank at '${partition_line:-<none>}'"
    fi
    if [ -n "$x2_line" ] && [ -n "$verdict_line" ] && [ "$x2_line" -lt "$verdict_line" ]; then
        ok "and above the verdict row (line ${verdict_line})"
    else
        bad "the passes at '${x2_line:-<none>}' do not precede the verdict row at '${verdict_line:-<none>}'"
    fi
    CURRENT="and the caller maps a 2 to a 2"
    if grep -qE '^2\) exit 2 ;;' "${ROOT}/scripts/check.sh"; then
        ok "the leg maps the reconciliation's 2 to the gate's 2, never to a 1"
    else
        bad "the leg does not map the passes' exit 2 to 2 — broken enforcement would read as a finding"
    fi
    rm -f "$X2_PLANT"
    GATE_X2_COUNTS_DIR=""
}

case_a_dying_collector_under_pr_is_exit_2_and_writes_no_narrowed_run_note() {
    # THE SAME PLANT THROUGH THE `--pr` SHAPE. `--pr` mints its counts directory
    # in the preflight and appends `--djb-scope-counts=<it>` to the flags both
    # passes carry, so the leg reuses that one rather than passing the option
    # twice — and the refusal has to bind there too, above the narrowed-run note
    # the verdict section would otherwise print for a run that never got there.
    #
    # WHAT THIS CASE DOES NOT DRIVE, declared: how `--pr` DERIVES its narrowing.
    # That is `case_pr_narrows_pytest_and_nothing_else`'s subject. The flags
    # below are the preflight's SHAPE with a fixed scope, so this case measures
    # the composition and not the derivation.
    local counts="${WORK}/pr-x2-counts" pr_args
    x2_leg_body
    x2_plant
    drive_require_scratch counts "${counts:-}"
    rm -rf "$counts"
    mkdir -p "$counts"
    pr_args="--djb-scope-narrow --djb-scope=example --djb-own-app=example --djb-scope-counts=${counts}"

    GATE_SLOT_WORKERS=2
    PYTEST_SEED=1
    GATE_X2_COUNTS_DIR="$counts"
    CURRENT="a dying collector under the --pr pass shape"
    N=$((N + 1))
    OUT="${WORK}/x2pr${N}.log"
    RC=0
    # shellcheck disable=SC2086
    (cd "$ROOT" && DJB_DRIVE_KILL_COLLECTOR=gw1 DJB_DRIVE_KILL_AFTER="${counts}/gw0" \
        pytest_x2_passes --max-worker-restart=0 $pr_args -k "$X2_K") >"$OUT" 2>&1 || RC=$?
    is "$RC" "2" "the leg body's exit status"
    says "1 of 2 collectors reported"
    CURRENT="and no narrowed-run note is printed by a run that never reached one"
    if grep -qF 'no verdict recorded — narrowed run' "$OUT"; then
        bad "the narrowed-run note printed from a refused run — a sentence about a verdict nobody was going to write"
    else
        ok "no 'no verdict recorded — narrowed run' line"
    fi
    CURRENT="and that note lives BELOW the passes in the file"
    local x2_line note_line
    x2_line=$(first_call_line 'pytest_x2_passes $X2_PASS_ARGS' "${ROOT}/scripts/check.sh")
    note_line=$(first_call_line 'no verdict recorded — narrowed run' "${ROOT}/scripts/check.sh")
    if [ -n "$x2_line" ] && [ -n "$note_line" ] && [ "$x2_line" -lt "$note_line" ]; then
        ok "the passes (line ${x2_line}) are above the narrowed-run note (line ${note_line})"
    else
        bad "the passes at '${x2_line:-<none>}' do not precede the narrowed-run note at '${note_line:-<none>}'"
    fi
    CURRENT="and the leg passes no second counts flag when --pr already carried one"
    if grep -qF 'if [ -n "$GATE_PR_COUNTS_DIR" ]; then' "${ROOT}/scripts/check.sh"; then
        ok "the leg reuses the --pr directory instead of minting a second one"
    else
        bad "the leg does not reuse GATE_PR_COUNTS_DIR — two --djb-scope-counts flags, and the last one wins silently"
    fi
    rm -f "$X2_PLANT"
    GATE_X2_COUNTS_DIR=""
}

case_the_full_gate_passes_write_counts_and_the_whole_suite_reconciles() {
    # THE OTHER DIRECTION, AND IT IS THE ONE A FALSE RED WOULD LIVE IN. A
    # reconciliation that refused a healthy full gate would stop every push, so
    # the clean case is driven with no plant at all: two real passes at a real
    # `-n 2`, both writing counts, both reconciling, exit 0.
    local counts="${WORK}/full-clean-counts" n files first selected collected
    x2_leg_body
    drive_require_scratch counts "${counts:-}"
    rm -rf "$counts"
    mkdir -p "$counts"

    GATE_SLOT_WORKERS=2
    PYTEST_SEED=1
    GATE_X2_COUNTS_DIR="$counts"
    CURRENT="two clean passes under the full gate's leg body"
    N=$((N + 1))
    OUT="${WORK}/x2clean${N}.log"
    RC=0
    (cd "$ROOT" && pytest_x2_passes "--djb-scope-counts=$counts" \
        -k test_the_namer_unwraps_and_never_reaches_for_repr) >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the leg body's exit status"
    says "pytest pass 1: green"
    says "pytest pass 2: green"
    CURRENT="every collector wrote its counts file"
    files=$(find "$counts" -type f | sort)
    n=$(printf '%s\n' "$files" | grep -c . || true)
    is "$n" "2" "the counts files pass 2 left"
    CURRENT="and the collectors agree"
    first=$(printf '%s\n' "$files" | head -1)
    local file
    for file in $files; do
        if ! cmp -s "$first" "$file"; then
            bad "two collectors wrote different counts under the whole suite: $(basename "$first") vs $(basename "$file")"
            return
        fi
    done
    ok "all ${n} counts files identical"
    CURRENT="the whole-suite file is a POPULATION, not a scope"
    selected=$(awk -F= '/^selected=/ {print $2}' "$first")
    is "$(awk -F= '/^deselected=/ {print $2}' "$first")" "0" "deselected under the whole suite"
    CURRENT="and selected is this tree's collected count"
    collect_scope_memo whole "the whole tree's collected count"
    collected=$(collected_count "$OUT")
    is "${selected:-unset}" "${collected:-unset}" "the counts file's selected"
    CURRENT="and the pre-run banner says the population and nothing about a scope"
    N=$((N + 1))
    OUT="${WORK}/x2clean-banner${N}.log"
    RC=0
    (cd "$ROOT" && "$PY" -m pytest -q -p no:randomly -n 2 "--djb-scope-counts=$counts" \
        -k test_the_namer_unwraps_and_never_reaches_for_repr) >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the exit status"
    says "collectors: 2 of 2 reported (the whole suite)"
    if grep -qF 'scope   selected' "$OUT"; then
        bad "the narrowed banner printed under the whole suite — there is no scope to describe there"
    else
        ok "no scope lines under a run that narrowed nothing"
    fi
    GATE_X2_COUNTS_DIR=""
}

case_the_full_counts_dir_is_removed_on_an_early_red() {
    # A2F.2'S SHAPE, ONE DIRECTORY OVER. The `--pr` counts directory rides the
    # EXIT trap because a red leg, a refused lease and a SIGTERM all leave by a
    # path no tidy-up line sits on; the full gate's own directory is minted
    # inside the `pytest-x2` leg, which is above a dozen more of those paths.
    # THE REAL TRAP STRING IS WHAT RUNS, not a paraphrase of it.
    local trap_line stub="${WORK}/full-trap-harness.sh" victim="${WORK}/full-counts-victim"
    trap_line=$( { grep -n "trap 'RC=\$?" "${ROOT}/scripts/check.sh" || true; } | head -1 | cut -d: -f1)
    CURRENT="the full-mode EXIT trap exists"
    if [ -z "$trap_line" ]; then
        bad "no 'trap ... EXIT' in scripts/check.sh's full-mode branch — nothing owns the cleanup"
        return
    fi
    ok "found at line ${trap_line}"
    CURRENT="the trap drops the FULL counts directory"
    if sed -n "${trap_line}p" "${ROOT}/scripts/check.sh" | grep -F 'GATE_FULL_COUNTS_DIR' >/dev/null; then
        ok "the EXIT trap names GATE_FULL_COUNTS_DIR"
    else
        bad "the EXIT trap does not drop the full gate's counts directory: every red leg below the pytest leg leaks one"
        return
    fi
    rm -rf "$victim"
    mkdir -p "$victim"
    {
        echo '#!/usr/bin/env bash'
        echo 'set -uo pipefail'
        echo 'gate_lock_release() { :; }'
        echo 'gate_slot_release() { :; }'
        echo 'gate_lease_release() { :; }'
        echo 'gate_run_finish() { :; }'
        echo 'GATE_PR_COUNTS_DIR=""'
        echo "GATE_FULL_COUNTS_DIR=\"${victim}\""
        sed -n "${trap_line}p" "${ROOT}/scripts/check.sh"
        echo 'exit 1'
    } >"$stub"
    N=$((N + 1))
    OUT="${WORK}/fulltraprun${N}.log"
    RC=0
    bash "$stub" >"$OUT" 2>&1 || RC=$?
    is "$RC" "1" "the harness's exit status (the early-red path)"
    CURRENT="the counts directory is gone after a NON-ZERO exit"
    if [ -d "$victim" ]; then
        bad "the directory survived a red exit — every full gate that reds below the pytest leg leaves one behind"
    else
        ok "removed by the shipped trap line on a red exit"
    fi
    CURRENT="and the leg leaves the removal to the trap"
    if grep -qE '^ *rm -rf "\$GATE_FULL_COUNTS_DIR"' "${ROOT}/scripts/check.sh"; then
        bad "a second remover stands beside the trap — two owners of one directory"
    else
        ok "the EXIT trap is the only remover"
    fi
}

# --- the inner loop: the cache, the first screen, and the worker ceiling ------
#
# WHY THESE LIVE IN THIS DRIVE. Three of them are properties of `scripts/check.sh`
# and `apps/conftest.py` — the two files this drive already sources, plants into
# and reads — and the fourth is `scripts/test.sh`'s refusal, which is the same
# `gate_slot_workers` derivation the scope banner prints. A drive file of their
# own would need an invocation block in `scripts/check.sh`'s self-test leg
# before any moment invoked it, and an uninvoked drive is green every time
# somebody remembers — the state `deploy/tests/` is in and the one the census
# block below the self-test leg exists to declare. They land where the gate
# already looks.

# first_call_line <needle> <file> — the line number of the first line that CALLS
# the needle, comment lines skipped.
#
# WHY THE FILTER EXISTS. The first draft took the first line MENTIONING the
# name, and a peer's fold then landed a COMMENT naming `loop_ledger_record` six
# hundred lines above the call — so the case compared a comment against a call
# and reported an ordering failure that was not there. An ordering assertion a
# prose edit can flip is an assertion about prose.
#
# Reads whole, then filters: nothing at the tail of this pipe exits early.
first_call_line() {
    local needle="$1" file="$2"
    { grep -n -F -- "$needle" "$file" || true; } |
        awk -F: '!seen && $0 !~ /^[0-9]+:[[:space:]]*#/ {print $1; seen = 1}'
}

check_sh_function() {
    # Copy one function DEFINITION out of scripts/check.sh and source it, so a
    # case drives the bytes check.sh ships rather than a re-implementation of
    # them. check.sh itself cannot be sourced — it IS the gate, and sourcing it
    # would start one — and a drive may not run a nested gate either, because
    # the per-checkout lock refuses it. The function is the seam.
    local name="$1" out
    out="${WORK}/fn-${name}.sh"
    awk -v want="${name}() {" '
        index($0, want) == 1 { on = 1 }
        on { print }
        on && $0 == "}" { exit }
    ' "${ROOT}/scripts/check.sh" >"$out"
    grep -q "^${name}() {" "$out" ||
        cannot_look "scripts/check.sh no longer defines ${name}() — the case cannot drive bytes it cannot find"
    grep -q '^}$' "$out" ||
        cannot_look "the ${name}() definition in scripts/check.sh has no closing brace at column 1 — the extraction cannot be trusted"
    # shellcheck source=/dev/null
    . "$out"
}

case_last_failed_reruns_only_the_failure() {
    # `-p no:cacheprovider` used to sit in pyproject's `addopts`, which does not
    # make `--lf` an error — it makes it a NO-OP: pytest accepts the flag and
    # collects everything, so a builder narrowing to one red gets the whole
    # module and no line saying why. Driven end to end, on this tree's real
    # configuration, with the cache pointed at the scratch directory so the
    # checkout is left exactly as it was found.
    local plant="${ROOT}/apps/test_zzz_last_failed.py"
    local cache="${WORK}/lf-cache"
    drive_require_scratch cache "${cache:-}"
    CURRENT="the plant's own path is free"
    if [ -e "$plant" ]; then
        cannot_look "apps/test_zzz_last_failed.py already exists in this tree — this case will not overwrite a file it did not create"
    fi
    ok "apps/test_zzz_last_failed.py is this case's to create"
    drive_at_exit "rm -f \"$plant\""
    cat >"$plant" <<'PLANT'
"""One failure and one pass, so `--lf` has something to narrow to."""


def test_zzz_last_failed_is_the_one_that_fails() -> None:
    assert False, "this failure is the subject of the --lf case"


def test_zzz_last_failed_is_the_one_that_passes() -> None:
    assert True
PLANT

    CURRENT="the first run records the failure"
    N=$((N + 1))
    OUT="${WORK}/lf-first${N}.log"
    RC=0
    (cd "$ROOT" && "$PY" -m pytest -q -p no:randomly -o "cache_dir=${cache}" \
        apps/test_zzz_last_failed.py) >"$OUT" 2>&1 || RC=$?
    is "$RC" "1" "the exit status of the run that fails"
    CURRENT="pytest wrote a cache it can read back"
    if [ -f "${cache}/v/cache/lastfailed" ]; then
        ok "the lastfailed cache exists — the cache plugin is loaded"
    else
        bad "no ${cache}/v/cache/lastfailed: the cache plugin is disabled, so --lf can only be a no-op"
        rm -f "$plant"
        return
    fi

    CURRENT="--lf selects the failure and deselects the pass"
    N=$((N + 1))
    OUT="${WORK}/lf-second${N}.log"
    RC=0
    (cd "$ROOT" && "$PY" -m pytest -q -p no:randomly -o "cache_dir=${cache}" --lf \
        --collect-only apps/test_zzz_last_failed.py) >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the exit status of the --lf collection"
    says "test_zzz_last_failed_is_the_one_that_fails"
    CURRENT="the passing test is NOT collected"
    if grep -qF "test_zzz_last_failed_is_the_one_that_passes" "$OUT"; then
        bad "--lf collected the test that passed — the flag is being accepted and ignored, which is what -p no:cacheprovider did"
    else
        ok "only the failure was collected"
    fi
    rm -f "$plant"
}

case_the_cache_directory_cannot_move_a_verdict_key() {
    # THE ONE REASON `-p no:cacheprovider` COULD HAVE HAD, checked rather than
    # assumed. A `--loop` verdict is keyed on a tree written through `git add -A`
    # over a scratch index (scripts/gate_ledger.sh, gate_measured_tree); a cache
    # directory that the index could see would move the key under a running gate
    # and turn a green run into "the tree changed while the gate ran". It cannot:
    # the path is ignored, and `git add -A` without `-f` skips an ignored path.
    # READ WHOLE, THEN MATCHED. A `producer | grep -q` tail exits at the first
    # match and SIGPIPEs the producer, which `set -o pipefail` reports as a
    # failure — the class that redded a sibling rung's verify at 755s of a
    # sanctioned full gate. Nothing in this drive reads through an early-exit
    # reader.
    CURRENT="the addopts LINE no longer disables the cache plugin"
    local addopts_line
    addopts_line=$(grep -E '^addopts = ' "${ROOT}/pyproject.toml" || true)
    case "$addopts_line" in
    *no:cacheprovider*) bad "pyproject.toml's addopts still carries -p no:cacheprovider — --lf/--ff/--sw cannot work" ;;
    '') bad "pyproject.toml has no addopts line at all" ;;
    *) ok "addopts leaves the cache plugin loaded (${addopts_line})" ;;
    esac
    CURRENT=".pytest_cache/ is ignored"
    RC=0
    (cd "$ROOT" && git check-ignore -q .pytest_cache/) || RC=$?
    is "$RC" "0" "git check-ignore's status for .pytest_cache/"

    # THE MEASUREMENT, on a real scratch index over a real planted cache file.
    local idx tree_before tree_after cache_file
    cache_file="${ROOT}/.pytest_cache/djb-drive-probe"
    idx="${WORK}/probe-index"
    CURRENT="the measured tree before the cache exists"
    tree_before=$(cd "$ROOT" && GIT_INDEX_FILE="$idx" git read-tree HEAD &&
        GIT_INDEX_FILE="$idx" git add -A >/dev/null 2>&1 &&
        GIT_INDEX_FILE="$idx" git write-tree)
    rm -f "$idx"
    [ -n "$tree_before" ] || cannot_look "could not write a scratch index over this checkout"
    ok "the scratch index wrote ${tree_before}"
    mkdir -p "${ROOT}/.pytest_cache"
    printf 'a drive probe\n' >"$cache_file"
    CURRENT="and after a file appears under .pytest_cache/"
    tree_after=$(cd "$ROOT" && GIT_INDEX_FILE="$idx" git read-tree HEAD &&
        GIT_INDEX_FILE="$idx" git add -A >/dev/null 2>&1 &&
        GIT_INDEX_FILE="$idx" git write-tree)
    rm -f "$idx" "$cache_file"
    is "$tree_after" "$tree_before" "the measured tree with a cache file present"
}

case_test_sh_refuses_n_auto_and_names_the_share() {
    # `-n auto` took every core on a box whose cores the gate has already split
    # into slots. It is exit 2 — nothing ran, and a refusal that reads as a test
    # failure is a refusal somebody re-runs instead of reading — and it names
    # the derivation and the number, so the corrected command is in the message.
    local share slots spelling
    slots=$(gate_slots_total)
    share=$(gate_slot_workers "$slots")
    for spelling in "-n auto" "-nauto" "--numprocesses auto" "--numprocesses=auto" "-n logical"; do
        CURRENT="./scripts/test.sh ${spelling} is refused"
        N=$((N + 1))
        OUT="${WORK}/nauto${N}.log"
        RC=0
        # shellcheck disable=SC2086 # the spelling IS the argument shape under test
        (cd "$ROOT" && ./scripts/test.sh $spelling --collect-only -q apps/example) >"$OUT" 2>&1 || RC=$?
        is "$RC" "2" "the exit status for '${spelling}'"
        says "REFUSING '-n auto'"
        CURRENT="the refusal names gate_slot_workers and this box's share for '${spelling}'"
        says "gate_slot_workers (scripts/gate_lease.sh) says ${share} on this box."
        says "Nothing ran."
    done

    CURRENT="the share itself is still accepted"
    N=$((N + 1))
    OUT="${WORK}/nshare${N}.log"
    RC=0
    (cd "$ROOT" && ./scripts/test.sh -n "$share" --collect-only -q apps/example) >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the exit status of a run at the share"

    # AND THE STALE SENTENCE IS GONE. `-n auto` was advertised in this file's
    # header as "what both gate legs run"; the gate legs run `-n
    # $GATE_SLOT_WORKERS`, and a header that says otherwise is how a builder
    # learns the wrong number from the right file.
    CURRENT="the header no longer advertises -n auto as the gate's shape"
    local stale
    stale=$( { grep -F -- '-n auto' "${ROOT}/scripts/test.sh" || true; } | grep -cF 'what both' || true)
    if [ "${stale:-0}" != "0" ]; then
        bad "scripts/test.sh still tells a reader that -n auto is what the gate legs run"
    else
        ok "the stale sentence is gone from scripts/test.sh"
    fi
    CURRENT="and the header names the share instead"
    if grep -qF 'GATE_SLOT_WORKERS' "${ROOT}/scripts/test.sh"; then
        ok "scripts/test.sh's header names the number the gate legs really run"
    else
        bad "scripts/test.sh's header names no share — the corrected sentence is missing"
    fi
}

# ONE UNCAPPED COLLECTION, TWO CASES. Two cases ran a byte-identical
# `DJB_PYTEST_UNCAPPED=1 pytest -n <2x the share> --collect-only apps/example`
# — one to show the clamp does not fire, one to read the disclosure line it
# prints instead — and both are readings of one run. The `-n` and the share
# are passed in and CHECKED against the first call rather than assumed: the
# two cases derive them independently, and a memo that quietly served a
# different pair would be a capture about another question.
UNCAPPED_READY=""
UNCAPPED_OUT=""
UNCAPPED_RC=0
UNCAPPED_ARGS=""
uncapped_collect_once() {
    local name="$1" over="$2" share="$3" want="-n ${over} (share ${share})"
    if [ -n "$UNCAPPED_READY" ]; then
        if [ "$UNCAPPED_ARGS" != "$want" ]; then
            cannot_look "the uncapped collection was taken at '${UNCAPPED_ARGS}' and is now wanted at '${want}' — two cases derived different numbers, so one capture cannot answer both"
        fi
        OUT="$UNCAPPED_OUT"
        RC="$UNCAPPED_RC"
        CURRENT="${name} (the uncapped collection, already taken)"
        capture_floor
        return 0
    fi
    CURRENT="$name"
    N=$((N + 1))
    OUT="${WORK}/uncapped${N}.log"
    RC=0
    (cd "$ROOT" && DJB_PYTEST_UNCAPPED=1 "$PY" -m pytest -n "$over" --collect-only -q -p no:randomly apps/example) >"$OUT" 2>&1 || RC=$?
    capture_floor
    UNCAPPED_OUT="$OUT"
    UNCAPPED_RC="$RC"
    UNCAPPED_ARGS="$want"
    UNCAPPED_READY=1
}

case_an_empty_capture_is_could_not_look() {
    # THE FLOOR UNDER EVERY `$OUT` READER, SHOWN FIRING. `says` over a capture
    # that was never taken is a red blaming the subject, and the `grep -q`
    # negatives through this file are `ok` over one. The plant is the way a
    # refactor makes one — the variable emptied — driven in a SUBSHELL, which
    # does not run this shell EXIT trap, so it costs two processes and leaves
    # nothing behind.
    local out="${WORK}/empty-capture.log" rc=0
    CURRENT="an emptied capture is could-not-look"
    rc=0
    (
        CURRENT="a planted case"
        OUT=""
        RC=0
        says "NOTHING THIS RUN COULD EVER HAVE PRINTED"
    ) >"$out" 2>&1 || rc=$?
    if [ "$rc" != "2" ]; then
        bad "an emptied capture exited ${rc}, not 2 — a reader that answers a question it could not look at is what this floor exists to stop"
        return
    fi
    if ! grep -qF 'capture with no path at all' "$out"; then
        bad "exit 2, but the refusal never says the capture is what could not be read: $(sed -n 1p "$out")"
        return
    fi
    ok "exit 2, naming the capture and the exit code of the run that did not fill it"

    CURRENT="a capture with bytes in it is judged, not refused"
    printf 'the collection said something\n' >"${WORK}/non-empty-capture.log"
    rc=0
    (
        CURRENT="a planted case"
        OUT="${WORK}/non-empty-capture.log"
        RC=0
        says "NOTHING THIS RUN COULD EVER HAVE PRINTED"
    ) >"$out" 2>&1 || rc=$?
    if [ "$rc" = "0" ] && grep -qF 'does not say' "$out"; then
        ok "the floor is a floor, not an off switch — a readable capture is judged"
    else
        bad "a readable capture exited ${rc}: $(sed -n 1p "$out")"
    fi
}

case_a_typed_n_above_the_share_is_clamped_and_printed() {
    # THE BELT FOR EVERY OTHER DOOR. `scripts/test.sh` is not the only way a
    # number gets typed — a bare `uv run pytest -n 10` is the shape the queue row
    # measured — so the ceiling lives in `apps/conftest.py::pytest_configure`,
    # where every entry point passes.
    local share slots
    slots=$(gate_slots_total)
    share=$(gate_slot_workers "$slots")
    local over=$((share * 2))

    CURRENT="a bare pytest above the share prints the clamp"
    N=$((N + 1))
    OUT="${WORK}/clamp${N}.log"
    RC=0
    (cd "$ROOT" && "$PY" -m pytest -n "$over" --collect-only -q -p no:randomly apps/example) >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the exit status"
    says "clamped -n ${over} → ${share} (DJB_PYTEST_UNCAPPED=1 to override)"

    CURRENT="a run AT the share says nothing"
    N=$((N + 1))
    OUT="${WORK}/clamp-at${N}.log"
    RC=0
    (cd "$ROOT" && "$PY" -m pytest -n "$share" --collect-only -q -p no:randomly apps/example) >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the exit status"
    if grep -qF "clamped -n" "$OUT"; then
        bad "the clamp fired at the share itself — a ceiling that lowers the gate's own legs is a ceiling nobody can run under"
    else
        ok "no clamp line at -n ${share}"
    fi

    uncapped_collect_once "the typed escape turns it off" "$over" "$share"
    is "$RC" "0" "the exit status"
    if grep -qF "clamped -n" "$OUT"; then
        bad "DJB_PYTEST_UNCAPPED=1 did not lift the clamp"
    else
        ok "DJB_PYTEST_UNCAPPED=1 lifts it, and the escape is typed rather than discovered"
    fi

    # THE NUMBER, NOT THE SENTENCE. Lowering `numprocesses` alone would print a
    # clamp and still start every worker: xdist builds one `tx` entry per worker
    # in its own `pytest_cmdline_main`, which has already run by the time a
    # conftest hook sees the config. So the WORKER COUNT is what is asserted,
    # off xdist's own `created: N/M worker` line, on a real parallel run.
    CURRENT="the clamp lowers the worker count, not just the message"
    N=$((N + 1))
    OUT="${WORK}/clamp-workers${N}.log"
    RC=0
    (cd "$ROOT" && DJB_PYTEST_MAX_WORKERS=1 "$PY" -m pytest -p no:randomly -n 4 \
        apps/example/tests/test_network.py) >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the exit status of the clamped parallel run"
    says "clamped -n 4 → 1"
    says "created: 1/1 worker"
}

case_census_runs_the_instrument_census_alone_without_a_slot() {
    # `--census` IS THE FINISHING BUILDER'S ONE LEG, AND IT MUST COST NOTHING.
    # It exists because the instrument census is the `--fast` leg that reds when
    # a rung added an instrument and has not written its row, and asking for that
    # answer used to mean running every other static leg with it. A mode that
    # took the machine's exclusive lease, the per-checkout lock or a pytest slot
    # to read one markdown table would make every queued gate wait for it, and
    # the whole reason to reach for it is that it is cheap.
    #
    # DRIVEN THROUGH THE FUNCTION, NOT THROUGH A NESTED GATE. A drive may not
    # shell out to `./scripts/check.sh` from inside a gate — the per-checkout
    # lock refuses it — so the body is extracted the way `loop_mine_banner` and
    # `loop_counts_refuse_if_short` are, and run over a scratch checkout this
    # case plants into. That the extracted body is the SAME body the `--fast`
    # leg runs is the point of it being a function at all, and the position
    # assertions below pin the arm that calls it.
    check_sh_function instrument_census
    real_clone

    CURRENT="a clean checkout censuses clean"
    N=$((N + 1))
    OUT="${WORK}/census-clean${N}.log"
    RC=0
    (cd "$REAL_CLONE" && instrument_census) >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the exit status on a tree whose instruments all own a row"
    says "instruments derived"
    says "rows in instruments.md"

    # THE VICTIM IS PLANTED, never found: a case that leaned on one of this
    # tree's real instruments would be asserting on the tree's contents rather
    # than on the census, and would go green the day somebody censused it.
    CURRENT="an uncensused instrument is exit 2, naming the path"
    local plant="scripts/djb_drive_uncensused_probe.sh"
    drive_at_exit "rm -f \"${REAL_CLONE}/${plant}\" 2>/dev/null || true"
    printf '#!/usr/bin/env bash\necho "a planted instrument with no row"\n' >"${REAL_CLONE}/${plant}"
    chmod +x "${REAL_CLONE}/${plant}"
    N=$((N + 1))
    OUT="${WORK}/census-planted${N}.log"
    RC=0
    (cd "$REAL_CLONE" && instrument_census) >"$OUT" 2>&1 || RC=$?
    is "$RC" "2" "the exit status with an uncensused instrument in the tree"
    says "uncensused: ${plant}"
    # THE REFUSAL SAYS WHAT TO DO ABOUT IT, which is the half a bare exit code
    # cannot carry to the builder who just added the file.
    says "owes a row in docs/product/instruments.md"

    CURRENT="and removing it restores the clean census"
    rm -f "${REAL_CLONE}/${plant}"
    N=$((N + 1))
    OUT="${WORK}/census-restored${N}.log"
    RC=0
    (cd "$REAL_CLONE" && instrument_census) >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the exit status once the plant is gone"

    # NO LEASE, NO LOCK, NO SLOT — asserted BY POSITION, because that is what the
    # property is: the mode's arm exits above every line that takes any of the
    # three. Comment lines are excluded, so a paragraph explaining the lease
    # cannot answer for the lease.
    local arm call define sourced lock lease slot
    # THE ARM, AND THE CALL INSIDE IT, LOCATED SEPARATELY. `instrument_census` as
    # a needle finds the DEFINITION first, which is not a call and would pin the
    # wrong line: the property is about where the mode RUNS it. The arm is its
    # guard; the call is the line that captures its status, which cannot exist
    # anywhere else.
    arm=$(first_call_line 'if [ -n "$GATE_CENSUS" ]; then' "${ROOT}/scripts/check.sh")
    call=$(first_call_line 'CENSUS_MODE_RC=$?' "${ROOT}/scripts/check.sh")
    define=$(first_call_line 'instrument_census() {' "${ROOT}/scripts/check.sh")
    sourced=$(first_call_line '. scripts/gate_lease.sh' "${ROOT}/scripts/check.sh")
    lock=$(first_call_line 'gate_lock_acquire' "${ROOT}/scripts/check.sh")
    lease=$(first_call_line 'gate_lease_acquire' "${ROOT}/scripts/check.sh")
    slot=$(first_call_line 'gate_slot_acquire' "${ROOT}/scripts/check.sh")

    CURRENT="the --census arm runs the census, below its definition"
    if [ -z "$arm" ] || [ -z "$call" ] || [ -z "$define" ]; then
        bad "the arm ('${arm:-<none>}'), its call ('${call:-<none>}') or the definition ('${define:-<none>}') cannot be located — nothing below is measuring the mode"
    elif [ "$define" -lt "$arm" ] && [ "$arm" -lt "$call" ] && [ "$call" -lt "$((arm + 12))" ]; then
        ok "defined at check.sh:${define}, the arm at :${arm}, its call inside it at :${call}"
    else
        bad "defined at ${define}, arm at ${arm}, call at ${call} — the call this case pins is not inside the --census arm"
    fi
    local what at
    for what in "the lease library is sourced:${sourced}" \
        "the per-checkout lock is taken:${lock}" \
        "the machine-wide lease is taken:${lease}" \
        "a pytest slot is taken:${slot}"; do
        CURRENT="--census exits before ${what%%:*}"
        at=${what##*:}
        if [ -z "$at" ]; then
            bad "check.sh no longer has a line where ${what%%:*} — this assertion has lost its subject"
        elif [ -n "$call" ] && [ "$call" -lt "$at" ]; then
            ok "the --census arm's call (line ${call}) is above it (line ${at})"
        else
            bad "the --census arm's call at '${call:-<none>}' is NOT above line ${at} — a mode built to cost nothing would queue behind every full gate"
        fi
    done

    # AND THE LIVE LINE, which is legal here only because of the positions just
    # asserted: this drive runs inside the selftest leg of a gate that is
    # HOLDING the per-checkout lock, and `--census` exits above it. If that ever
    # stops being true the four assertions above red first, and this line reds
    # with them rather than hanging.
    CURRENT="the mode itself runs, and prints the census and nothing else"
    N=$((N + 1))
    OUT="${WORK}/census-live${N}.log"
    RC=0
    (cd "$ROOT" && ./scripts/check.sh --census) >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the mode's exit status on this tree"
    says "instruments derived"
    # `-e` IS LOAD-BEARING AND WAS MISSING (B4.7). The fourth string here begins
    # with a hyphen, so `grep -qF "$noise"` handed it to getopt as OPTIONS: grep
    # exited 2 with a usage message and the `else` branch printed `ok` whether or
    # not the line was there. Three assertions were real and the fourth — the one
    # that watches for a LEG having run — could not fail. `-e` says "this is the
    # pattern", which is the whole fix.
    local noise
    for noise in "pytest slot" "gate lock" "waiting for the" "- ruff"; do
        CURRENT="--census prints no '${noise}' line"
        if grep -qF -e "$noise" "$OUT"; then
            bad "--census printed a '${noise}' line — it is running more than the census"
        else
            ok "no '${noise}' line"
        fi
    done

    # THE CONTROL, INLINE: the assertion above is only worth its `ok` if it can
    # go RED. A copy of the census output with a `- ruff` line planted in it must
    # be SEEN by the identical expression — under the old form it was not, and
    # that is what made three of these four lines decoration.
    local planted="${WORK}/census-planted${N}.log"
    cp "$OUT" "$planted"
    echo "- ruff                 the planted leg line" >>"$planted"
    CURRENT="the '- ruff' assertion can fail — a planted leg line is SEEN"
    if grep -qF -e "- ruff" "$planted"; then
        ok "the planted line fires the same expression that cleared the real output"
    else
        bad "a planted '- ruff' line was NOT seen — the assertion above cannot fail and proves nothing"
    fi
}

case_the_typed_escape_prints_and_lifts_the_clamp() {
    # A SILENT ESCAPE IS A HOLE, NOT AN ESCAPE. The case above proves
    # `DJB_PYTEST_UNCAPPED=1` lifts the ceiling; until now nothing proved the run
    # SAID so, and it did not — the escape returned before every write, so the
    # transcript of an uncapped run and the transcript of a capped one differed
    # nowhere. A reader of a log could not tell how many workers the box had
    # carried, which is the one question the ceiling exists to answer.
    local share slots over
    slots=$(gate_slots_total)
    share=$(gate_slot_workers "$slots")
    over=$((share * 2))

    # `--collect-only`, AND THE WORKER COUNT IS NOT MEASURED HERE. The case above
    # measures the clamped count off xdist's own `created: N/M worker` line,
    # because there the number is the claim. Here the claim is the LINE, and
    # starting twice this box's share of real collectors to read a string is the
    # contention the ceiling was built to prevent — on a box with other builders
    # on it. So: what `-n` was typed is asserted, what it printed is asserted,
    # and the worker count this path produces is read off the code (the escape
    # returns before `numprocesses` and `tx` are touched — `apps/conftest.py`,
    # `pytest_configure`), never off a run.
    uncapped_collect_once "the typed escape PRINTS the number it is running past" "$over" "$share"
    is "$RC" "0" "the exit status"
    says "uncapped: -n ${over} (DJB_PYTEST_UNCAPPED=1 — the slot share on this box is ${share})"

    CURRENT="and does not ALSO print the clamp it lifted"
    if grep -qF "clamped -n" "$OUT"; then
        bad "the uncapped run printed a clamp line as well — two sentences about one run, one of them false"
    else
        ok "no clamp line: the run says it is uncapped and nothing else"
    fi

    # THE ESCAPE TOUCHES THE NUMBER NOWHERE, read off the code rather than run:
    # everything that assigns `numprocesses` or `tx` must sit BELOW the escape's
    # return, or the line above would be a disclosure attached to a clamp that
    # still happened.
    CURRENT="the escape returns above every assignment"
    local escape_line assign_line
    escape_line=$(first_call_line 'if os.environ.get("DJB_PYTEST_UNCAPPED"' "${ROOT}/apps/conftest.py")
    assign_line=$(first_call_line 'config.option.numprocesses = share' "${ROOT}/apps/conftest.py")
    if [ -n "$escape_line" ] && [ -n "$assign_line" ] && [ "$escape_line" -lt "$assign_line" ]; then
        ok "the escape at apps/conftest.py:${escape_line} precedes the clamp's assignment at :${assign_line}"
    else
        bad "the escape (${escape_line:-<none>}) does not precede the clamp's assignment (${assign_line:-<none>}) — the printed line would be describing a run that was clamped anyway"
    fi

    # AND A RUN WITH NO `-n` AT ALL STAYS SILENT. A shell that exports the
    # variable for one parallel run would otherwise put the line on top of every
    # serial `uv run pytest` it ever makes, and a disclosure that prints when
    # there is nothing to disclose is the next thing a reader learns to skip.
    CURRENT="a serial run under the same variable says nothing"
    N=$((N + 1))
    OUT="${WORK}/uncapped-serial${N}.log"
    RC=0
    (cd "$ROOT" && DJB_PYTEST_UNCAPPED=1 "$PY" -m pytest --collect-only -q -p no:randomly apps/example) >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the exit status"
    if grep -qF "uncapped: -n" "$OUT"; then
        bad "a serial run printed the escape line — there was no ceiling to run past"
    else
        ok "silent when no -n was typed"
    fi
}

case_the_python_clamp_and_the_shell_share_are_the_same_number() {
    # A SECOND COPY OF A DERIVATION, NAMED AND DRIVEN. `apps/conftest.py` has to
    # be able to derive the share on its own — a bare `uv run pytest` inherits
    # nothing — so `gate_slot_workers`' arithmetic exists twice, once in shell
    # and once in Python. Two copies that nobody compares is the drift class the
    # whole rules engine exists against; this compares them.
    local shell_share python_share
    shell_share=$(gate_slot_workers "$(gate_slots_total)")
    CURRENT="the shell derivation answers"
    case "$shell_share" in
    '' | *[!0-9]*) cannot_look "gate_slot_workers did not print a number: '${shell_share}'" ;;
    esac
    ok "gate_slot_workers says ${shell_share}"
    # `apps/conftest.py` imports the models, so it needs Django set up before it
    # can be imported at all — the same two lines every management command pays.
    local probe="import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.test')
django.setup()
import apps.conftest as c
print(c._djb_slot_share())"
    python_share=$(cd "$ROOT" && env -u DJB_GATE_SLOT_WORKERS -u DJB_PYTEST_MAX_WORKERS \
        "$PY" -c "$probe" 2>/dev/null || true)
    CURRENT="the python derivation answers"
    case "$python_share" in
    '' | *[!0-9]*) cannot_look "apps/conftest.py's _djb_slot_share did not print a number: '${python_share}'" ;;
    esac
    is "$python_share" "$shell_share" "apps/conftest.py's derived share against gate_slot_workers'"

    CURRENT="a handed-down share outranks the derivation"
    local handed
    handed=$(cd "$ROOT" && DJB_GATE_SLOT_WORKERS=3 "$PY" -c "$probe" 2>/dev/null || true)
    is "$handed" "3" "the share when the caller hands one down"
}

case_a_tree_miss_prints_three_lines_every_other_miss_two_and_the_detail_on_request() {
    # THE FIRST SCREEN IS THE RUNG'S. A measuring `--loop` used to open with
    # twelve lines about why a CACHE lookup missed, above the finding the gate
    # was run for. The facts did not stop being worth printing; they stopped
    # being worth printing first. Driven over `scripts/check.sh`'s own printer.
    #
    # WIDENED BY THE DOCS-ONLY PYTEST REUSE (2026-09-15), AND THE NAME NOW SAYS
    # SO. A `miss(tree)` prints THREE lines by default — the token, the key, and
    # the `since banked head …; docs-only: yes|no` line — because that third
    # line is what the docs-only pytest reuse is decided on, and a run whose
    # cheapest available answer is hidden behind a flag is a 2302-second
    # re-measure bought by two docs files. Every OTHER token still prints two,
    # which is what the short-banner property was ever about and is asserted
    # below. The name was one line behind the property for a day and was
    # corrected (2026-09-15) together with the citation that named it — a name
    # that lies is worse than a stale citation, but only when both move.
    #
    # THE TWO-LINE CLAIM RESTS ON ONE GUARD, AND THE CASE SAYS WHICH. The three
    # lines are printed by the single `= "tree"` test in `loop_miss_narrative`
    # (`scripts/check.sh`): every token that is not the literal `tree` takes the
    # two-line path. So the `env:env-file` assertion below is a true negative
    # for exactly that guard and for nothing else — a SECOND condition added
    # beside it (a token that also earned a third line, a mode that suppressed
    # it) would make both halves of this case green while the banner had grown a
    # branch nothing here looks at. That is this case's declared blind spot.
    check_sh_function loop_miss_narrative
    LOOP_LEDGER_KEY="loop-v1:planted0000000000000000000000000000000000000000000000000000"
    LOOP_LEDGER_TREE="planted-tree-0000000000000000000000000000"
    LOOP_ENV_FINGERPRINT="planted-env"
    LOOP_ENV_COMPONENTS="env-file=planted dists=planted head=planted"
    LOOP_MISS_CENSUS="7 rows (0 seeded — planted by the drive)"
    local why
    why=$(printf '%s\n%s\n%s\n' "tree" "banked row: a planted row" "since banked head: 3 path(s) changed")

    CURRENT="the default miss banner is short: the token, the key, and what moved"
    N=$((N + 1))
    local tree_out env_out
    tree_out="${WORK}/miss-default${N}.log"
    env_out="${WORK}/miss-default-env${N}.log"
    OUT="$tree_out"
    RC=0
    (unset DJB_LOOP_VERBOSE; loop_miss_narrative "$why") >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the printer's exit status"
    is "$(wc -l <"$OUT" | tr -d ' ')" "3" "the number of lines a miss(tree) prints by default"
    says "MISSED: miss(tree)"
    says "DJB_LOOP_VERBOSE=1"
    says "since banked head: 3 path(s) changed"
    CURRENT="and every other token still prints the two P19 A4.2 asked for"
    OUT="$env_out"
    RC=0
    (unset DJB_LOOP_VERBOSE
        loop_miss_narrative "$(printf '%s\n%s\n' "env:env-file" "banked row: a planted row")") >"$OUT" 2>&1 || RC=$?
    is "$(wc -l <"$OUT" | tr -d ' ')" "2" "the number of lines an env: miss prints by default"
    OUT="$tree_out"
    CURRENT="and the detail is not in it"
    if grep -qF "fingerprint components" "$OUT"; then
        bad "the default banner still prints the fingerprint components"
    else
        ok "no components block, no census, no seven-line explanation"
    fi

    CURRENT="DJB_LOOP_VERBOSE=1 prints the whole thing"
    N=$((N + 1))
    OUT="${WORK}/miss-verbose${N}.log"
    RC=0
    (DJB_LOOP_VERBOSE=1 loop_miss_narrative "$why") >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the printer's exit status under DJB_LOOP_VERBOSE=1"
    says "MISSED: miss(tree)"
    says "banked row: a planted row"
    says "fingerprint components (the env= line, spelled out):"
    says "7 rows (0 seeded — planted by the drive)"
    says "The token names the component"
    CURRENT="the verbose form is the long one it always was"
    local verbose_lines
    verbose_lines=$(wc -l <"$OUT" | tr -d ' ')
    if [ "$verbose_lines" -ge 12 ]; then
        ok "${verbose_lines} lines under DJB_LOOP_VERBOSE=1 — nothing was deleted, only moved"
    else
        bad "only ${verbose_lines} lines under DJB_LOOP_VERBOSE=1 — the detail was dropped rather than moved"
    fi

    CURRENT="and --loop is the only mode that reaches it"
    if awk '/^if \[ "\$MODE" = "--loop" \]; then/ {on = 1}
        on && /loop_miss_narrative "\$LOOP_MISS_WHY"/ {found = 1}
        END {exit found ? 0 : 1}' "${ROOT}/scripts/check.sh"; then
        ok "the only call site is inside check.sh's --loop block: full mode is untouched"
    else
        bad "loop_miss_narrative is called outside the --loop block, or not at all"
    fi
}

# --- `--pr --base <sha>`: a full-mode variant that narrows pytest and nothing else

# A clone of THIS checkout kept for the `--pr` cases alone, reset to its own
# base between them. The `--pr` cases COMMIT — that is what a proposed change
# is — and a case that committed into the clone the tests-only cases share
# would move their subject underneath them.
PR_CLONE=""
PR_CLONE_BASE=""
pr_clone() {
    if [ -n "$PR_CLONE" ]; then
        git -C "$PR_CLONE" checkout -q main 2>/dev/null || true
        git -C "$PR_CLONE" reset -q --hard "$PR_CLONE_BASE"
        git -C "$PR_CLONE" clean -qfd
        pr_clone__lend_the_interpreter
        return 0
    fi
    PR_CLONE="${WORK}/pr-clone"
    drive_require_scratch PR_CLONE "${PR_CLONE:-}"
    git clone --quiet --shared --no-hardlinks "$ROOT" "$PR_CLONE" >/dev/null 2>&1 ||
        cannot_look "could not clone this checkout for the --pr cases"
    git -C "$PR_CLONE" checkout -q -B main
    git -C "$PR_CLONE" config user.email drive@example.invalid
    git -C "$PR_CLONE" config user.name "loop scope drive"
    pr_clone__lend_the_interpreter
    PR_CLONE_BASE=$(git -C "$PR_CLONE" rev-parse HEAD)
}

# THE CLOSURE WALK NEEDS AN INTERPRETER, and it looks for exactly one place:
# `.venv/bin/python` beside the file it was sourced from (`loop_scope__python`).
# A clone has none, and without one the closure's refusal is "no interpreter" —
# a could-not-look standing in for the refusal a case is actually asking about,
# which is a green-looking case proving the wrong thing.
#
# A REAL DIRECTORY HOLDING ONE SYMLINK, never a symlink called `.venv`, and the
# difference is the tree's own ignore rule: `.gitignore` says `.venv/` — a
# DIRECTORY — so a directory is ignored and a symlink of that name is an
# untracked file. Both halves were measured here. As a symlink it was swept away
# by `git clean -fd` between cases (the case then read "no interpreter" instead
# of "declares no AppConfig"), and it showed up in `git status` as `?? .venv`,
# which made `--pr` refuse the clone as a DIRTY TREE — a case failing on the
# lending, not on the thing it was asking about. As a directory it is ignored:
# `clean` leaves it, status stays clean, and the refusals still mean what they
# say.
# AND IT LENDS THE WHOLE VENV, not just the interpreter: `bin/python` alone
# makes CPython compute `sys.prefix` from the borrowed path and look for
# site-packages under a directory that has none — measured here as "No module
# named 'django'", which is a could-not-look standing in for the refusal again.
# `bin`, `lib` and `pyvenv.cfg` together resolve to the real packages.
pr_clone__lend_the_interpreter() {
    [ -x "$PR_CLONE/.venv/bin/python" ] && return 0
    mkdir -p "$PR_CLONE/.venv"
    ln -s "$ROOT/.venv/bin" "$PR_CLONE/.venv/bin" 2>/dev/null || true
    ln -s "$ROOT/.venv/lib" "$PR_CLONE/.venv/lib" 2>/dev/null || true
    cp "$ROOT/.venv/pyvenv.cfg" "$PR_CLONE/.venv/pyvenv.cfg" 2>/dev/null || true
    return 0
}

# The `--pr` question, asked of the same function `--loop` asks: one derivation,
# a different fork point.
pr_scope_in() {
    local dir="$1" base="$2" here
    CURRENT="$3"
    N=$((N + 1))
    OUT="${WORK}/prscope${N}.log"
    here="$PWD"
    cd "$dir"
    RC=0
    SECRETS_SCAN_BASE_REF="$base" loop_tier_own_apps >"$OUT" 2>&1 || RC=$?
    cd "$here"
}

# Run the real `scripts/check.sh` in the clone. SAFE BY CONSTRUCTION for the
# refusal cases: no DJB_GATE_SANCTION is ever set, so even a `--pr` preflight
# that stopped refusing would meet the unsanctioned-full-gate refusal instead of
# starting a full gate inside the one this drive may itself be running under.
pr_check() {
    local name="$1"
    shift
    CURRENT="$name"
    N=$((N + 1))
    OUT="${WORK}/prcheck${N}.log"
    RC=0
    (cd "$PR_CLONE" && ./scripts/check.sh "$@") >"$OUT" 2>&1 || RC=$?
}

took_nothing() {
    local what="$CURRENT"
    CURRENT="${what}: it took neither the lease nor a slot"
    if grep -qE 'full-gate lease (ACQUIRED|held)|gate slot ACQUIRED|WAITING for the machine-wide' "$OUT"; then
        bad "the refusal named a lease or a slot — a run that was never going to be legal must not queue for one"
    else
        ok "no lease, no slot"
    fi
    CURRENT="${what}: and ran no leg"
    if grep -qE '^- (ruff|mypy|import-linter)' "$OUT"; then
        bad "a leg ran before the refusal"
    else
        ok "no leg ran"
    fi
}

case_pr_refuses_an_uncomputable_impact_map_before_taking_the_lease() {
    # CANARY A.4-7. Every way the impact map cannot be computed is exit 2 and
    # NEVER a smaller run, and every one of them lands above the machine's one
    # exclusive lease and its pytest slot. A gate that queued for an hour and
    # then said the flag was wrong would be an expensive way to learn about a
    # typo — so the absence of the lease and slot lines is asserted, not assumed.
    pr_clone
    local base aside
    base=$(git -C "$PR_CLONE" rev-parse HEAD)

    pr_check "--pr with no --base" --pr
    is "$RC" "2" "the exit status"
    says "--pr needs --base"
    took_nothing

    pr_check "--pr --base git cannot resolve" --pr --base 0000000000000000000000000000000000000000
    is "$RC" "2" "the exit status"
    says "cannot resolve that to a commit"
    took_nothing

    # A REAL NON-ANCESTOR, BUILT: a commit on a side branch this HEAD has never
    # contained. `<base>...HEAD` from there is taken at a merge-base nobody
    # named, over a set the caller did not ask about.
    git -C "$PR_CLONE" checkout -q -b side
    echo "a commit HEAD will never contain" >>"$PR_CLONE/README.md"
    git -C "$PR_CLONE" commit -q -am "the side commit" >/dev/null
    aside=$(git -C "$PR_CLONE" rev-parse HEAD)
    git -C "$PR_CLONE" checkout -q main
    pr_check "--pr --base <a non-ancestor>" --pr --base "$aside"
    is "$RC" "2" "the exit status"
    says "NOT an ancestor of HEAD"
    took_nothing

    echo "uncommitted" >>"$PR_CLONE/README.md"
    pr_check "--pr over a dirty tree" --pr --base "$base"
    is "$RC" "2" "the exit status"
    says "refuses a DIRTY TREE"
    took_nothing
}

case_pr_refuses_an_unaccountable_label_above_the_lease() {
    # A2.3'S FIFTH WAY, AND THE ONLY ONE REACHED THROUGH THE DERIVATION rather
    # than through the flag itself: a directory under `apps/` that declares no
    # AppConfig. The closure walk cannot account for it, so the impact map is
    # underived — and an underived map is exit 2, never a smaller run, and never
    # after the machine's exclusive lease has been taken.
    #
    # A SANCTION IS TYPED, because `--pr` IS a full gate and the sanction check
    # sits above this block; without one the run refuses there instead, which is
    # a different case (above). TWO BELTS so a regression here cannot start a
    # real full gate inside the one this drive may be running under:
    # `DJB_GATE_LEASE_DIR` is a relative path, which `gate_lease.sh` refuses
    # outright rather than waiting on, and the took-nothing assertion below
    # fails loudly if the run ever reached it.
    pr_clone
    local base
    base=$(git -C "$PR_CLONE" rev-parse HEAD)
    mkdir -p "$PR_CLONE/apps/ghost"
    echo "base" >"$PR_CLONE/apps/ghost/services.py"
    git -C "$PR_CLONE" add -A
    git -C "$PR_CLONE" commit -q -m "a directory under apps/ that declares no AppConfig" >/dev/null
    CURRENT="--pr over an app the declarations cannot account for"
    N=$((N + 1))
    OUT="${WORK}/prcheck${N}.log"
    RC=0
    (cd "$PR_CLONE" && DJB_GATE_LEASE_DIR="not/a/real/directory" \
        DJB_GATE_SANCTION="loop-scope-drive: the --pr impact map refusal, asserted above the lease" \
        ./scripts/check.sh --pr --base "$base") >"$OUT" 2>&1 || RC=$?
    is "$RC" "2" "the exit status"
    says "--pr COULD NOT DERIVE THE IMPACT MAP"
    says "apps/ghost/apps.py"
    took_nothing
}

# banner_cause <headline> — the banner's SECOND line, asserted as a second line
# and not merely as a string somewhere in the log. "see above" followed by the
# cause is the whole criterion; a `cause:` line three legs later would satisfy a
# plain `says` and help nobody.
#: The line `banner_cause` found, for the assertions that follow it. A GLOBAL and
#: not a stdout value: `$(banner_cause …)` would run the whole thing in a
#: subshell, and every ok/bad it counted would die there — a drive whose own
#: tally is computed in a subshell is the class this file exists to refuse.
BANNER_CAUSE=""
banner_cause() {
    local headline="$1"
    CURRENT="the banner's SECOND line is its cause"
    BANNER_CAUSE=$(awk -v h="$headline" 'found { print; exit } index($0, h) { found = 1 }' "$OUT")
    case "$BANNER_CAUSE" in
    *"cause: "*) ok "it reads:${BANNER_CAUSE#*cause:}" ;;
    "") bad "nothing follows \"${headline}\" — the refusal still points at an above the reader may not have" ;;
    *) bad "the line after \"${headline}\" is '${BANNER_CAUSE}', not a cause" ;;
    esac
}

case_a_substitution_callees_refusal_surfaces_as_cause() {
    # REVIEW F7, DRIVEN END TO END. The deepest refusal in the scope derivation
    # is written by the embedded Python reader inside `loop_scope__closure`,
    # which its caller invokes under `$(...)`. A subshell throws away every
    # assignment it makes, and a Python process could not call a shell helper
    # anyway — so without the caller-side `2>"$err"` capture there is no channel
    # at all between that sentence and the banner three frames up. This case
    # takes the whole chain: python -> subshell -> loop_tier -> check.sh's
    # `--pr COULD NOT DERIVE THE IMPACT MAP` banner, and asserts the label the
    # PYTHON named comes out on the banner's own second line.
    #
    # THE SAME TWO BELTS as the unaccountable-label case above, and for the same
    # reason: a relative `DJB_GATE_LEASE_DIR` that `gate_lease.sh` refuses
    # outright, and `took_nothing`, so a regression here cannot start a real full
    # gate inside the one this drive may be running under.
    pr_clone
    local base cause
    base=$(git -C "$PR_CLONE" rev-parse HEAD)
    mkdir -p "$PR_CLONE/apps/phantom"
    echo "base" >"$PR_CLONE/apps/phantom/services.py"
    git -C "$PR_CLONE" add -A
    git -C "$PR_CLONE" commit -q -m "a directory under apps/ that declares no AppConfig" >/dev/null
    CURRENT="--pr over an app only the closure walk can refuse"
    N=$((N + 1))
    OUT="${WORK}/prcheck${N}.log"
    RC=0
    (cd "$PR_CLONE" && DJB_GATE_LEASE_DIR="not/a/real/directory" \
        DJB_GATE_SANCTION="loop-scope-drive: the substitution callee's cause, asserted above the lease" \
        ./scripts/check.sh --pr --base "$base") >"$OUT" 2>&1 || RC=$?
    is "$RC" "2" "the exit status"
    banner_cause "--pr COULD NOT DERIVE THE IMPACT MAP — see above."
    cause="$BANNER_CAUSE"
    CURRENT="and the cause is the PYTHON reader's sentence, carried out of the subshell"
    case "$cause" in
    *"apps/phantom/apps.py"*) ok "the banner names apps/phantom/apps.py" ;;
    *) bad "the cause is '${cause}' — the label the closure walk refused is not in it" ;;
    esac
    CURRENT="and it is the callee's cause, not this file's own 'see above'"
    case "$cause" in
    *"could not derive the depends_on closure"*)
        bad "the cause is loop_tier.sh's OWN pointer line — the pointer was recorded instead of the thing pointed at"
        ;;
    *) ok "the recorded line is the refusal, not another pointer" ;;
    esac
    took_nothing
}

case_a_banner_with_no_recorded_cause_is_exit_2() {
    # B4.3. The population that legitimately reaches this today is the banners
    # whose callee is a separate PROCESS, but the shape must hold for any callee
    # that refuses without saying why — so the case BUILDS one: a shim
    # `loop_tier_own_apps` that returns 1 and records nothing at all. A blank
    # `cause:` would read as "there was no cause"; the sentence says that nobody
    # recorded one, which is a different and worse thing.
    pr_clone
    local base cause
    base=$(git -C "$PR_CLONE" rev-parse HEAD)
    {
        echo ""
        echo "# A SHIM, planted by scripts/tests/test_loop_scope.sh: a callee that"
        echo "# refuses and records nothing. See case_a_banner_with_no_recorded_cause_is_exit_2."
        echo "loop_tier_own_apps() { return 1; }"
    } >>"$PR_CLONE/scripts/loop_tier.sh"
    git -C "$PR_CLONE" commit -q -am "a callee that refuses and records no cause" >/dev/null
    CURRENT="a banner whose callee recorded no cause"
    N=$((N + 1))
    OUT="${WORK}/prcheck${N}.log"
    RC=0
    (cd "$PR_CLONE" && DJB_GATE_LEASE_DIR="not/a/real/directory" \
        DJB_GATE_SANCTION="loop-scope-drive: the no-cause banner, asserted above the lease" \
        ./scripts/check.sh --pr --base "$base") >"$OUT" 2>&1 || RC=$?
    # 2 REGARDLESS OF THE CALLEE'S STATUS: the shim returned 1, and a banner that
    # cannot say why is broken enforcement, which outranks a finding.
    is "$RC" "2" "the exit status — 2 although the callee returned 1"
    banner_cause "--pr COULD NOT DERIVE THE IMPACT MAP — see above."
    cause="$BANNER_CAUSE"
    CURRENT="and the cause says nobody recorded one"
    case "$cause" in
    *"the callee set none"*) ok "the banner says the callee set none" ;;
    *) bad "the cause is '${cause}' — a blank cause reads as 'there was none' rather than 'nobody recorded one'" ;;
    esac
    CURRENT="and it names that as broken enforcement, not as a finding"
    case "$cause" in
    *"broken enforcement"*) ok "it says so in words" ;;
    *) bad "the cause does not call it broken enforcement: '${cause}'" ;;
    esac
    took_nothing
}

case_pr_removes_its_counts_directory_on_every_path() {
    # THE MIRROR-LENS FINDING, DRIVEN. The counts directory the pre-run banner
    # writes into used to be dropped on the green path alone — a line only a run
    # that got that far ever reaches. A red leg, a refused lease and a SIGTERM
    # all exit above it, and each one left a directory behind.
    #
    # THE REAL TRAP STRING IS WHAT RUNS, not a paraphrase of it: the case lifts
    # the EXIT trap out of scripts/check.sh, installs it in a scratch script
    # with its neighbours stubbed (they are other functions' business), and
    # exits NON-ZERO — the path that leaked. A paraphrase would go green while
    # the shipped line said something else.
    local trap_line stub="${WORK}/trap-harness.sh" victim="${WORK}/counts-victim"
    trap_line=$( { grep -n "trap 'RC=\$?" "${ROOT}/scripts/check.sh" || true; } | head -1 | cut -d: -f1)
    CURRENT="the full-mode EXIT trap exists"
    if [ -z "$trap_line" ]; then
        bad "no 'trap ... EXIT' in scripts/check.sh's full-mode branch — nothing owns the cleanup"
        return
    fi
    ok "found at line ${trap_line}"
    CURRENT="the trap drops the counts directory"
    if sed -n "${trap_line}p" "${ROOT}/scripts/check.sh" | grep -F 'GATE_PR_COUNTS_DIR' >/dev/null; then
        ok "the EXIT trap names GATE_PR_COUNTS_DIR"
    else
        bad "the EXIT trap does not drop the counts directory: a --pr run that reds anywhere leaks it"
        return
    fi
    # AND IT REALLY REMOVES IT. The trap line verbatim, its neighbours stubbed,
    # a real directory, and an exit status of 1.
    rm -rf "$victim"
    mkdir -p "$victim"
    {
        echo '#!/usr/bin/env bash'
        echo 'set -uo pipefail'
        echo 'gate_lock_release() { :; }'
        echo 'gate_slot_release() { :; }'
        echo 'gate_lease_release() { :; }'
        echo 'gate_run_finish() { :; }'
        echo "GATE_PR_COUNTS_DIR=\"${victim}\""
        sed -n "${trap_line}p" "${ROOT}/scripts/check.sh"
        echo 'exit 1'
    } >"$stub"
    N=$((N + 1))
    OUT="${WORK}/traprun${N}.log"
    RC=0
    bash "$stub" >"$OUT" 2>&1 || RC=$?
    is "$RC" "1" "the harness's exit status (the path that used to leak)"
    CURRENT="the counts directory is gone after a NON-ZERO exit"
    if [ -d "$victim" ]; then
        bad "the directory survived a red exit — this is the leak, unfixed"
    else
        ok "removed by the shipped trap line on a red exit"
    fi
    # AND THE GREEN PATH NO LONGER DROPS IT TOO. One owner, or two lines drift.
    CURRENT="the green path leaves the cleanup to the trap"
    if grep -qE '^ *\[ -z "\$GATE_PR_COUNTS_DIR" \] \|\| rm -rf' "${ROOT}/scripts/check.sh"; then
        bad "a second remover stands beside the trap — two owners of one directory"
    else
        ok "the EXIT trap is the only remover"
    fi
}

case_pr_without_a_sanction_is_the_full_gates_refusal() {
    # `--pr` IS A FULL GATE, so it is sanctioned like one. The valve is not
    # widened by the flag: an unsanctioned `--pr` meets the identical refusal a
    # bare `./scripts/check.sh` meets, and takes nothing either.
    #
    # (The plan places this case in scripts/tests/test_gate_lease.sh, which is
    # appended to by a later rung first; it lives here until that lands, and the
    # mechanism it asserts is the same one.)
    pr_clone
    local base
    base=$(git -C "$PR_CLONE" rev-parse HEAD)
    pr_check "--pr with no DJB_GATE_SANCTION" --pr --base "$base"
    is "$RC" "2" "the exit status"
    says "REFUSING an unsanctioned FULL gate"
    took_nothing
}

case_pr_narrows_pytest_and_nothing_else() {
    # WHAT THE DRIVE CAN PROVE HERE, AND WHAT IT CANNOT. A `--pr` run end to end
    # IS a full gate: it takes the machine's one exclusive lease, and this drive
    # runs inside the self-test leg of a full gate that is already holding it.
    # So the case drives everything `--pr` DECIDES — the fork point, the scope,
    # the flags the two passes are pointed at — and pins the rest by the text of
    # the file: no leg is added, and the two passes are reached through the one
    # variable rather than through a second expansion.
    pr_clone
    local base
    base=$(git -C "$PR_CLONE" rev-parse HEAD)
    echo "" >>"$PR_CLONE/apps/files/services.py"
    git -C "$PR_CLONE" commit -q -am "a files change, committed" >/dev/null
    pr_scope_in "$PR_CLONE" "$base" "the --pr impact map for a committed files change"
    is "$RC" "0" "the exit status"
    is "$LOOP_SCOPE_TOUCHED" "files" "the touched set"
    CURRENT="the basis names the fork point the caller handed it"
    case "$LOOP_TIER_BASIS" in
    *"$(git -C "$PR_CLONE" rev-parse --short "$base")"*) ok "the basis names ${base}" ;;
    *) bad "the basis does not name the base: '${LOOP_TIER_BASIS}'" ;;
    esac

    local args
    args=$(loop_scope__pytest_args | tr '\n' ' ')
    CURRENT="the pass flags narrow to the scope"
    case " $args " in
    *" --djb-scope-narrow "*) ok "they carry --djb-scope-narrow" ;;
    *) bad "no --djb-scope-narrow in '${args}'" ;;
    esac
    CURRENT="the pass flags carry the scope"
    case " $args " in
    *" --djb-scope=files "*) ok "they name files" ;;
    *) bad "--djb-scope=files is missing from '${args}'" ;;
    esac
    CURRENT="the ORGAN TIER IS NOT APPLIED"
    case "$args" in
    *--djb-tier*) bad "the flags carry a tier: '${args}' — --pr grades every test the change can reach, organ-reaching or not" ;;
    *) ok "no --djb-tier: every test in the scope runs" ;;
    esac
    CURRENT="and no app is promoted to own"
    case "$args" in
    *--djb-own-app*) bad "the flags carry --djb-own-app, which only means 'run the organ tests anyway' — already true of every app here" ;;
    *) ok "no --djb-own-app" ;;
    esac

    # NO LEG IS ADDED. The block is a preflight that prints; a reader comparing
    # this run's legs against FULL_LEGS must find them equal.
    # THE BLOCK IS EXTRACTED TO A FILE AND THE READER IS HANDED THE FILE —
    # never a producer whose tail a quiet reader can close. A reader that
    # short-circuits at a pipeline tail under `pipefail` kills its producer with
    # SIGPIPE, `pipefail` hands the pipeline 141, and over the pipe buffer that
    # is the WRONG ANSWER every run (the census in scripts/tests/test_sweep.sh,
    # and the reproduction in scripts/tests/test_loop_ledger.sh). With no
    # pipeline there is no producer to close.
    local block="${WORK}/pr-block.txt"
    awk '/^# --- the --pr scope:/ {on = 1}
        on && /^# --- / && !/^# --- the --pr scope:/ {exit}
        on {print}' "${ROOT}/scripts/check.sh" >"$block"
    CURRENT="the --pr block exists in scripts/check.sh"
    if [ -s "$block" ]; then
        ok "found it"
    else
        bad "no --pr scope block in scripts/check.sh"
        return
    fi
    CURRENT="the --pr block announces no leg of its own"
    if grep -qE '^ *leg ' "$block"; then
        bad "the --pr block calls leg: the run's leg list would no longer equal FULL_LEGS"
    else
        ok "no leg call — FULL_LEGS is what runs"
    fi
    CURRENT="both passes are reached through the one variable"
    if grep -qF 'PARTITION_TARGETS="$GATE_PR_PYTEST_ARGS"' "${ROOT}/scripts/check.sh"; then
        ok "--pr replaces \$PARTITION_TARGETS rather than adding a second expansion"
    else
        bad "nothing assigns GATE_PR_PYTEST_ARGS into PARTITION_TARGETS — the passes would not be narrowed"
    fi
    # ABOVE THE LEASE, ASSERTED BY POSITION. The refusals this block can raise —
    # an app label the declarations cannot account for, an always-on floor that
    # does not meet — are could-not-looks about the impact map, and a run that
    # was never going to be legal must not first queue for the machine's one
    # exclusive lease. It is also what makes the scope print on a RED run: a
    # banner below the legs goes missing exactly when a reader is asking what
    # the gate graded. The position is load-bearing and silent when it moves,
    # so it is pinned here rather than remembered.
    local pr_at lease_at
    pr_at=$( { grep -n '^# --- the --pr scope:' "${ROOT}/scripts/check.sh" || true; } | head -1 | cut -d: -f1)
    lease_at=$( { grep -n 'GATE_SLOT_LEASE_FIRST=1' "${ROOT}/scripts/check.sh" || true; } | head -1 | cut -d: -f1)
    CURRENT="the impact map is derived ABOVE the lease"
    if [ -n "$pr_at" ] && [ -n "$lease_at" ] && [ "$pr_at" -lt "$lease_at" ]; then
        ok "the --pr block (line ${pr_at}) precedes the lease (line ${lease_at})"
    else
        bad "the --pr block is at ${pr_at:-nowhere} and the lease at ${lease_at:-nowhere} — a refusal below the lease has queued for the machine before refusing, and a banner below the legs goes missing on a red run"
    fi
    CURRENT="the full gate's leg list is untouched"
    if grep -q '^FULL_LEGS=ruff,' "${ROOT}/scripts/check.sh" &&
        grep -q '^FULL_LEGS=.*,pytest-x2,' "${ROOT}/scripts/check.sh"; then
        ok "FULL_LEGS still opens at ruff and still carries pytest-x2"
    else
        bad "FULL_LEGS moved"
    fi
}

case_a_files_touch_under_pr_selects_the_exports_tests_and_names_the_closure() {
    # CANARY A.4-1, asked at the `--pr` fork point: the closure still widens by
    # the declarations (`apps/exports/apps.py` declares `files`), and the
    # selection the flags produce really does contain exports' tests.
    pr_clone
    local base
    base=$(git -C "$PR_CLONE" rev-parse HEAD)
    echo "" >>"$PR_CLONE/apps/files/services.py"
    git -C "$PR_CLONE" commit -q -am "a files change, committed" >/dev/null
    pr_scope_in "$PR_CLONE" "$base" "a committed files change, at the --pr fork point"
    is "$RC" "0" "the exit status"
    CURRENT="the closure line names exports"
    case " $LOOP_SCOPE_WIDENED " in
    *" exports "*) ok "exports is in the closure" ;;
    *) bad "the closure is '${LOOP_SCOPE_WIDENED}' — exports declares files and must be in it" ;;
    esac

    local args
    args=$(loop_scope__pytest_args | tr '\n' ' ')
    # shellcheck disable=SC2086
    collect_scope "the --pr selection for a files change" $args
    is "$RC" "0" "the exit status"
    CURRENT="exports' tests are in the --pr selection"
    if grep -q '^apps/exports/tests/' "$OUT"; then
        ok "apps/exports/tests/ is selected through the reverse depends_on closure"
    else
        bad "no apps/exports/tests/ nodeid in the --pr selection"
    fi
}

case_an_organ_test_in_a_closure_added_app_runs_under_pr_and_not_under_loop() {
    # CANARY A.4-5, as the review corrected it. An organ test in a TOUCHED app
    # already runs under `--loop` — the own-app rule — so the difference the two
    # modes make is only visible in an app the CLOSURE added: `--pr` runs it
    # (every test the change can reach), `--loop` does not (the organ tier).
    # The subject is derived off the manifest, never named here.
    manifest_all
    # A NODEID, NOT A MODULE, and the difference is the case: a module under
    # apps/exports/tests/ holds fast tests beside its organ-reaching ones, so a
    # module-level grep finds the module selected under BOTH modes and the case
    # can tell them apart only by the test that actually reaches an organ. A
    # parametrised id is skipped so the literal grep below stays a literal one.
    local victim
    victim=$(awk -F'\t' '$1 == "slow" && $3 ~ /^apps\/exports\/tests\// && $3 !~ /\[/ {print $3}' \
        "$MANIFEST_ALL" | sort -u | head -1)
    [ -n "$victim" ] ||
        cannot_look "no organ-reaching test under apps/exports/tests/ — the subject this case needs is gone"

    collect_scope_memo pr "an organ test in a closure-added app, under --pr" \
        --djb-scope-narrow --djb-scope=files --djb-scope=exports
    is "$RC" "0" "the exit status"
    CURRENT="under --pr it is SELECTED"
    if grep -qxF "$victim" "$OUT"; then
        ok "${victim} runs — --pr applies no organ tier"
    else
        bad "${victim} was deselected under --pr: the organ tier is being applied where it must not be"
    fi

    collect_scope_memo leaf "the same module under --loop's fast tier" \
        --djb-tier=fast --djb-scope-narrow --djb-own-app=files \
        --djb-scope=files --djb-scope=exports
    is "$RC" "0" "the exit status"
    CURRENT="under --loop it is DESELECTED"
    if grep -qxF "$victim" "$OUT"; then
        bad "${victim} runs under --loop too — then the two modes select the same thing and this case cannot tell them apart"
    else
        ok "${victim} is deselected — the organ tier is push-time for an app the closure added"
    fi
}

case_pr_with_an_empty_diff_runs_the_always_on_set_and_says_so() {
    # AN EMPTY SELECTION IS PRINTED, NEVER SILENT. `--base` = HEAD on a clean
    # tree is a legal question with an empty answer, and the honest shape is the
    # always-on set alone with the reason said out loud — not a narrowing nobody
    # can trace and not a silent whole suite.
    pr_clone
    local head
    head=$(git -C "$PR_CLONE" rev-parse HEAD)
    pr_scope_in "$PR_CLONE" "$head" "--pr --base HEAD: an empty diff"
    is "$RC" "0" "the exit status"
    is "$LOOP_SCOPE_TOUCHED" "" "the touched set"
    is "$LOOP_SCOPE_APPS" "" "the scope"
    reason_says "the scope is EMPTY and the always-on cross-app set runs alone"

    local args empty
    args=$(loop_scope__pytest_args | tr '\n' ' ')
    # shellcheck disable=SC2086
    collect_scope "an empty --pr scope still runs the always-on set" $args
    is "$RC" "0" "the exit status"
    empty=$(collected_count "$OUT")
    CURRENT="the always-on cross-app set still runs"
    if [ -n "$empty" ] && [ "$empty" -gt 0 ]; then
        ok "an empty --pr scope selected ${empty} — the cross-app tripwires run alone"
    else
        bad "an empty --pr scope selected '${empty:-?}': the narrowing took the always-on set with it"
    fi
}

case_pr_ignores_a_banked_partition_row() {
    # THE TWO NARROWINGS ARE NOT COMPOSABLE, and the first half of this case is
    # the mechanical proof rather than the claim: the scope's always-on floors
    # are asserted over the WHOLE collection, so a PATH-narrowed collection
    # under `--djb-scope-narrow` — which is exactly what a skipped platform
    # partition would hand the two passes — refuses. pytest's usage error is 4,
    # which `scripts/check.sh` maps to 2.
    collect_scope "a path-narrowed collection under a scope refuses" \
        --djb-scope-narrow --djb-scope=files apps/files
    is "$RC" "4" "the exit status (pytest usage error)"
    # The ORGAN floors are the first of the two layers to notice — both are
    # asserted over the whole collection, and it is that sentence, not which
    # floor spoke first, that is the mechanism here.
    says "the floors are asserted over the whole collection"

    # SO `--pr` FORCES A MEASURE, and says so when there was a row to ignore.
    CURRENT="--pr forces the partition to measure"
    if grep -qE '^ *PARTITION_MODE=measure' "${ROOT}/scripts/check.sh"; then
        ok "scripts/check.sh sets PARTITION_MODE=measure under --pr"
    else
        bad "nothing forces the partition to measure under --pr: a banked row would path-narrow both passes and the floors would refuse"
    fi
    CURRENT="and it says so rather than skipping silently"
    if grep -qF 'IGNORES THE BANKED PARTITION ROW' "${ROOT}/scripts/check.sh"; then
        ok "the run names the row it ignored"
    else
        bad "a banked partition row is ignored silently"
    fi
}

case_pr_writes_no_verdict_row_and_no_partition_row() {
    # A NARROWED RUN BANKS NOTHING, ANYWHERE. The full ledger's rows are read by
    # the pre-push hook as "a full gate has passed these bytes"; a `--pr` run
    # passed a SCOPE of them. The partition's row is the same class one level
    # down: the platform portion was deselected, so this run has nothing to say
    # about it.
    #
    # ASSERTED AS WIRING, and the reason is declared: writing either row takes a
    # complete `--pr` run, which is a full gate, and this drive runs inside one.
    # What is asserted is that neither writer is REACHABLE under --pr — the
    # branch that skips it precedes it in both chains.
    local verdict_branch verdict_write bank_branch bank_write
    verdict_branch=$( { grep -n 'no verdict recorded — narrowed run' "${ROOT}/scripts/check.sh" || true; } | head -1 | cut -d: -f1)
    verdict_write=$( { grep -n 'gate_ledger_record "\$MEASURED_START"' "${ROOT}/scripts/check.sh" || true; } | head -1 | cut -d: -f1)
    CURRENT="the verdict chain has a narrowed-run branch"
    if [ -n "$verdict_branch" ] && [ -n "$verdict_write" ] && [ "$verdict_branch" -lt "$verdict_write" ]; then
        ok "the --pr branch (line ${verdict_branch}) precedes gate_ledger_record (line ${verdict_write})"
    else
        bad "no narrowed-run branch before gate_ledger_record (${verdict_branch:-none} / ${verdict_write:-none}) — --pr would bank a full verdict row"
    fi
    bank_branch=$( { grep -n 'partition verdict NOT banked: --pr' "${ROOT}/scripts/check.sh" || true; } | head -1 | cut -d: -f1)
    bank_write=$( { grep -n 'quality.partition bank' "${ROOT}/scripts/check.sh" || true; } | head -1 | cut -d: -f1)
    CURRENT="the partition banking chain has one too"
    if [ -n "$bank_branch" ] && [ -n "$bank_write" ] && [ "$bank_branch" -lt "$bank_write" ]; then
        ok "the --pr branch (line ${bank_branch}) precedes the bank (line ${bank_write})"
    else
        bad "no --pr branch before the partition bank (${bank_branch:-none} / ${bank_write:-none})"
    fi
}

# --- criterion 9: the planted-miss triple ------------------------------------

case_the_planted_miss_triple() {
    # THE CASE THAT DECIDES WHETHER THE RUNG SHIPS.
    #
    # A throwaway checkout of this repository, carrying a real undeclared
    # cross-app coupling: a PRODUCT app's test reaching a PLATFORM app's symbol
    # through a channel the `depends_on` declarations do not cover. Break the
    # symbol from the platform side and ask three selections what they see.
    local plant="${WORK}/plant"
    drive_require_scratch plant "${plant:-}"
    CURRENT="the planted-miss triple"
    git clone --quiet --shared --no-hardlinks "$ROOT" "$plant" >/dev/null 2>&1 ||
        cannot_look "could not clone this checkout into the scratch directory"
    git -C "$plant" checkout -q -B main
    git -C "$plant" config user.email drive@example.invalid
    git -C "$plant" config user.name "loop scope drive"
    # THE CLONE CARRIES COMMITTED STATE ONLY, and the triple has to be a verdict
    # on THE TREE THIS DRIVE IS RUNNING IN. Measured: with the selection
    # machinery left at HEAD, verdict (b) failed with "unrecognized arguments"
    # because the flag under test existed only in the working tree — a drive
    # that grades the last commit is green on a broken uncommitted change and
    # the builder finds out at push. So the two files that decide the selection
    # are copied over the clone, and they are the only ones: everything else the
    # plant needs is exactly what was committed.
    cp "$ROOT/apps/conftest.py" "$plant/apps/conftest.py"
    cp "$ROOT/scripts/loop_tier.sh" "$plant/scripts/loop_tier.sh"

    # THE QUALIFYING CONDITION, RE-DERIVED rather than trusted. The plant app is
    # a PRODUCT app precisely because a platform app's tests are what the
    # partition skips; if `partition.yaml` ever grew this name the case would be
    # measuring nothing, so it asks.
    local plant_app=djbplant
    # `.env` is gitignored and does not survive a clone, and pytest-django
    # refuses to start without a database name. NO PLANTED TEST TOUCHES THE
    # DATABASE, so nothing is ever created under this name — it exists to get
    # past the settings refusal, and it is deliberately not this checkout's.
    local PLANT_DB=djb_loop_scope_drive_plant
    if "$PY" - "$ROOT/quality/partition.yaml" "$plant_app" <<'PY'
import pathlib
import sys

text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
name = sys.argv[2]
inside = False
for line in text.splitlines():
    if line.startswith("platform_apps:"):
        inside = True
        continue
    if inside:
        stripped = line.strip()
        if stripped.startswith("- "):
            if stripped[2:].strip() == name:
                raise SystemExit(0)
            continue
        if stripped and not stripped.startswith("#"):
            break
raise SystemExit(1)
PY
    then
        cannot_look "quality/partition.yaml lists '${plant_app}' as a platform app — the plant would be invisible to verdict (c) for a reason that has nothing to do with the scope"
    fi
    ok "the plant app '${plant_app}' is NOT in partition.yaml's platform_apps — its tests always run"

    # The A side: a documented channel on a platform app.
    printf 'CHANNEL = "v1"\n' >"$plant/apps/example/plant_channel.py"
    # The B side: a product app whose test reaches it. It declares NO depends_on
    # on `example` — that is the undeclared coupling, and it is the whole point.
    mkdir -p "$plant/apps/${plant_app}/tests"
    : >"$plant/apps/${plant_app}/__init__.py"
    : >"$plant/apps/${plant_app}/tests/__init__.py"
    {
        echo "from django.apps import AppConfig"
        echo ""
        echo ""
        echo "class DjbplantConfig(AppConfig):"
        echo "    name = \"apps.${plant_app}\""
        echo "    depends_on: tuple[str, ...] = ()"
    } >"$plant/apps/${plant_app}/apps.py"
    {
        echo "from apps.example import plant_channel"
        echo ""
        echo ""
        echo "def test_the_documented_channel_still_answers():"
        echo "    assert plant_channel.CHANNEL == \"v1\""
    } >"$plant/apps/${plant_app}/tests/test_undeclared_coupling.py"
    git -C "$plant" add -A >/dev/null 2>&1
    git -C "$plant" commit -q -m "the plant: a product app reaching a platform symbol, undeclared"

    # BREAK IT FROM A. The rung's whole change is one file in `apps/example`.
    printf 'CHANNEL = "v2"\n' >"$plant/apps/example/plant_channel.py"

    # What the scope derives for that change, from the plant's own tree.
    scope_in "$plant" "the plant's derived scope"
    is "$RC" "0" "the scope derivation's exit status"
    case " $LOOP_SCOPE_APPS " in
    *" ${plant_app} "*)
        bad "the plant app is IN scope — the coupling was declared after all, and this case is measuring nothing"
        return
        ;;
    *) ok "the plant app is OUTSIDE the derived scope (${LOOP_SCOPE_APPS}) — the coupling is undeclared, as designed" ;;
    esac

    local node="apps/${plant_app}/tests/test_undeclared_coupling.py"
    local a_args=(--djb-tier=fast)
    local app
    for app in $LOOP_TIER_OWN_APPS; do a_args+=("--djb-own-app=$app"); done
    local scope_args=()
    for app in $LOOP_SCOPE_APPS; do scope_args+=("--djb-scope=$app"); done

    # THE BREAK IS ONE BREAK, AND THE TRIPLE IS THREE SELECTIONS OVER IT. That
    # is worth saying plainly, because the three verdicts below share a failing
    # test on purpose: what differs between (a), (b) and (c) is whether the
    # selection CONTAINS it, and that is the only variable the active rung moved.
    #
    # A SELECTION IS ASKED WITH `--collect-only` OVER THE WHOLE SUITE, never by
    # handing the tier a path. The organ floors assert over the whole collection
    # and `--loop` always collects the whole suite, so `--djb-tier=fast <path>`
    # is a UsageError by design — the first draft of this case did exactly that
    # and read the tier's own refusal as verdict (a). The floors were right and
    # the case was wrong.
    CURRENT="the plant is RED when it runs at all"
    N=$((N + 1))
    OUT="${WORK}/verdict-red${N}.log"
    RC=0
    (cd "$plant" && DATABASE_NAME="$PLANT_DB" "$PY" -m pytest -q -rf -p no:randomly \
        "$node") >"$OUT" 2>&1 || RC=$?
    is "$RC" "1" "the exit status of the broken coupling"
    says "$node"

    # (a) TODAY'S SELECTION — the fast tier plus the rung's own apps, with no
    #     scope narrowing. It CONTAINS the plant, so today the break is caught
    #     at the rung.
    CURRENT="(a) today's selection contains the plant, so today the break is caught"
    N=$((N + 1))
    OUT="${WORK}/verdict-a${N}.log"
    RC=0
    (cd "$plant" && DATABASE_NAME="$PLANT_DB" "$PY" -m pytest --collect-only -q -p no:randomly \
        "${a_args[@]}") >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the exit status"
    says "$node"

    # (b) THE SCOPED LOOP — the same tree, the same break, narrowing on. The
    #     plant is DESELECTED and the run is green. THE HONEST MISS, SHOWN.
    CURRENT="(b) the scoped loop is GREEN — the honest miss, shown"
    N=$((N + 1))
    OUT="${WORK}/verdict-b${N}.log"
    RC=0
    (cd "$plant" && DATABASE_NAME="$PLANT_DB" "$PY" -m pytest --collect-only -q -p no:randomly \
        "${a_args[@]}" "${scope_args[@]}" --djb-scope-narrow) >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the exit status"
    if [ "$RC" != "0" ]; then
        # A COLLECTION THAT ERRORED CONTAINS NOTHING, so the absence check below
        # would pass on a run that answered nothing at all. Measured: it did.
        bad "the scoped collection did not answer (exit ${RC}), so its emptiness proves nothing"
    elif grep -qF "$node" "$OUT"; then
        bad "the scoped selection still collected ${node} — then (b) is not the miss this triple exists to show"
    else
        ok "the scoped selection does not contain ${node}: deselected, and the break goes unseen"
    fi

    # (c) THE BANK'S SELECTION — the full gate's own invocation, no tier flags at
    #     all. IF THIS DOES NOT HOLD, THE RUNG IS WRONG AND DOES NOT SHIP: the
    #     narrowing is only a deferral if the wave bank still catches it.
    CURRENT="(c) the BANK's selection is RED"
    N=$((N + 1))
    OUT="${WORK}/verdict-c${N}.log"
    RC=0
    (cd "$plant" && DATABASE_NAME="$PLANT_DB" "$PY" -m pytest -q -rf -p no:randomly \
        "$node") >"$OUT" 2>&1 || RC=$?
    is "$RC" "1" "the exit status"
    says "$node"

    # (c), pinned at the SELECTION level under the partition's SKIP mode: the
    # plant is a product app, so the partition cannot take it out.
    CURRENT="(c) holds at the selection level under the partition's SKIP mode"
    N=$((N + 1))
    OUT="${WORK}/verdict-c-skip${N}.log"
    RC=0
    (cd "$plant" && DATABASE_NAME="$PLANT_DB" "$PY" -m quality.partition paths) >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the skip-mode path list's exit status"
    if grep -qF "apps/${plant_app}" "$OUT"; then
        ok "under the partition's SKIP mode the plant app is STILL in the path list — a product app is outside the partition and its tests always run"
    else
        bad "the plant app is not in the skip-mode path list — verdict (c) does not hold under a SKIP and the rung does not ship"
    fi
}

# --- the census seeds (the gate lane's census-seed rider, criteria R.1-R.4) -----------------------------------------------
#
# THE HOLE. The closure this scope walks is the REVERSE `depends_on` one, and
# `core` is everyone's dependency and nobody's dependant — so `core`'s tests are
# never pulled in by another app's change. That is right for nearly all of them
# and wrong for the handful that quantify over EVERY app's declarations: a rung
# that adds a permission key to its own `policies.py` moves a census that lives
# in `core`, and no `--loop` anywhere ran it. Found at a bank, by a hotfix.
#
# `seeded_args` — the `--djb-changed-test` flags `loop_scope__pytest_args`
# emits, space-joined, so a case can assert on what the leg would actually be
# handed rather than on a variable it could read a different way.
seeded_args() {
    loop_scope__pytest_args | grep -- '--djb-changed-test=' | tr '\n' ' ' | sed 's/ $//'
}

# scratch_census <checkout> [declaration…] — plant a census module in the
# scratch world that DECLARES what it quantifies over.
#
# THE CASES BELOW PROVE A DERIVATION, so they must not lean on the real tree's
# census module: the scratch world grows its own, at a path no product owns, and
# the assertions name THAT path. If the derivation were still a typed literal,
# every one of them would go red — which is the whole point of planting it here
# rather than asserting on `apps/core/tests/test_vocabulary.py`.
scratch_census() {
    local dir=$1 name decls=""
    shift
    for name in "$@"; do decls="${decls}${decls:+, }\"${name}\""; done
    mkdir -p "$dir/apps/core/tests"
    {
        echo '"""A scratch census over other apps declarations."""'
        echo ""
        echo "CENSUS_SEEDED_BY = (${decls},)"
    } >"$dir/apps/core/tests/test_scratch_census.py"
    printf '%s' "apps/core/tests/test_scratch_census.py"
}

case_a_policies_touch_census_seeds_the_vocabulary_module() {
    # R.1 and R.2. The seed is ONE MODULE, the app is not widened, the
    # footer says so, and the banked key carries it.
    local census
    fresh_checkout
    census=$(scratch_census "$REPO" policies roles)
    printf 'POLICIES = {}\n' >"$REPO/apps/mid/policies.py"
    git -C "$REPO" add apps/mid/policies.py
    scope_in "$REPO" "apps/mid/policies.py -> the declared census is seeded"
    is "$RC" "0" "the exit status"
    is "$LOOP_SCOPE_SEEDED_TESTS" "$census" "the seeded census module(s)"
    is "$LOOP_SCOPE_SEEDED_BY" "apps/mid/policies.py" "the file(s) that seeded it"
    is "$LOOP_SCOPE_TOUCHED" "mid" "the touched set"

    CURRENT="and the scope did NOT gain core"
    case " $LOOP_SCOPE_APPS " in
    *" core "*) bad "the seed widened the scope to the whole core app: ${LOOP_SCOPE_APPS}" ;;
    *) ok "scope=${LOOP_SCOPE_APPS} — the module is added, the app is not" ;;
    esac

    CURRENT="the leg is handed the module as a changed-test flag"
    is "$(seeded_args)" "--djb-changed-test=${census}" "the --djb-changed-test flags"

    notes_say "census-seeded by apps/mid/policies.py: ${census}"

    CURRENT="and the banked key carries the seed"
    case "$LOOP_SCOPE_CANONICAL" in
    *"seeded=${census}"*)
        ok "$LOOP_SCOPE_CANONICAL"
        ;;
    *) bad "the canonical scope does not carry the seed: ${LOOP_SCOPE_CANONICAL}" ;;
    esac
}

case_roles_seed_the_same_census_and_ordinary_files_seed_nothing() {
    # R.1's population, both members and the negatives. `policies.py` and
    # `roles.py` are ONE discovery walk in `apps.core.authz._declarations`, so
    # a seed on one and not the other would be half a rule.
    local census
    fresh_checkout
    census=$(scratch_census "$REPO" policies roles)
    printf 'ROLES = {}\n' >"$REPO/apps/leaf/roles.py"
    git -C "$REPO" add apps/leaf/roles.py
    scope_in "$REPO" "apps/leaf/roles.py -> the same census is seeded"
    is "$LOOP_SCOPE_SEEDED_TESTS" "$census" "the seeded census module(s)"

    fresh_checkout
    scratch_census "$REPO" policies roles >/dev/null
    touch_and_scope "$REPO" "an ordinary app file seeds nothing" apps/leaf/services.py
    is "$LOOP_SCOPE_SEEDED_TESTS" "" "the seeded set for a plain code touch"
    CURRENT="and the canonical says so rather than omitting the field"
    case "$LOOP_SCOPE_CANONICAL" in
    *"seeded=-"*) ok "$LOOP_SCOPE_CANONICAL" ;;
    *) bad "the canonical has no seeded= field: ${LOOP_SCOPE_CANONICAL}" ;;
    esac

    # CORE'S OWN DECLARATIONS ARE EXCLUDED, and not for tidiness: a change there
    # makes `core` a touched app, so the module is already in the selection and
    # a note about it would be a line nobody can act on.
    fresh_checkout
    scratch_census "$REPO" policies roles >/dev/null
    printf 'POLICIES = {}\n' >"$REPO/apps/core/policies.py"
    git -C "$REPO" add apps/core/policies.py
    scope_in "$REPO" "a declaration in the census's OWN app seeds nothing — it is already touched"
    is "$LOOP_SCOPE_SEEDED_TESTS" "" "the seeded set"
    is "$LOOP_SCOPE_TOUCHED" "core" "the touched set — core runs in full anyway"
}

case_the_seeded_census_goes_red_on_a_planted_nineteenth_key() {
    # R.3, AND IT IS THE PROPERTY THE OTHER TWO CASES ONLY SET UP: a
    # declaration this tree could really grow makes the core census RED, and
    # without the seed that census is not merely green — it is DESELECTED, which
    # is what "no --loop anywhere ran it" looks like from the inside.
    #
    # THE PYTEST INVOCATION THE LOOP MAKES, NOT A NESTED GATE. A drive may not
    # run `./scripts/check.sh` inside one (the per-checkout lock refuses it) and
    # a scratch clone has no database for the module to run against, so what is
    # driven here is the command the `--loop` leg builds — the flags this file's
    # own derivation emits — against this checkout's real suite. Declared rather
    # than implied: the gate wrapper around those flags is not covered here; the
    # two cases above cover the derivation that produces them.
    #
    # IT BUILDS ITS OWN VICTIM AND RESTORES IT BYTE-IDENTICAL. The plant is one
    # line in a tracked file, removed by the case and by the exit trap both, and
    # the case refuses to run at all if the tree is already dirty there.
    local plant="${ROOT}/apps/example/policies.py" backup="${WORK}/policies.orig"
    local out rc=0 seeded="--djb-changed-test=apps/core/tests/test_vocabulary.py"
    local narrow="--djb-tier=fast --djb-own-app=example --djb-scope-narrow --djb-scope=example"

    CURRENT="the plant's own file is clean before this case touches it"
    if [ -n "$(git -C "$ROOT" status --porcelain -- apps/example/policies.py)" ]; then
        cannot_look "apps/example/policies.py is already modified — this case will not plant into a file somebody else is editing"
    fi
    ok "apps/example/policies.py is committed and unmodified"
    cp "$plant" "$backup"
    drive_at_exit "cp \"$backup\" \"$plant\" 2>/dev/null || true"

    CURRENT="WITHOUT the seed, the core census is not even selected"
    out="${WORK}/seed-collect-without.txt"
    # shellcheck disable=SC2086  # the flag list word-splits into arguments
    (cd "$ROOT" && uv run pytest --collect-only -q -p no:randomly $narrow) >"$out" 2>&1 || true
    if [ "$(grep -c 'test_vocabulary' "$out")" = "0" ]; then
        ok "0 items of apps/core/tests/test_vocabulary.py in the selection — the census the declaration moved never runs"
    else
        bad "$(grep -c 'test_vocabulary' "$out") item(s) selected without the seed — this case has no subject"
    fi

    CURRENT="WITH the seed, the module is selected"
    out="${WORK}/seed-collect-with.txt"
    # shellcheck disable=SC2086
    (cd "$ROOT" && uv run pytest --collect-only -q -p no:randomly $narrow "$seeded") >"$out" 2>&1 || true
    if [ "$(grep -c 'test_vocabulary' "$out")" -ge 1 ]; then
        ok "$(grep -c 'test_vocabulary' "$out") item(s) selected — the module is in, and nothing else of core is"
    else
        bad "the seed did not put the module in the selection"
    fi

    CURRENT="and with a declaration planted, the census is RED by name"
    python3 - "$plant" <<'PY_PLANT'
import sys

path = sys.argv[1]
src = open(path).read()
anchor = "ACTION_PROSE: dict[str, str] = {"
if anchor not in src:
    raise SystemExit("apps/example/policies.py has no ACTION_PROSE to plant into")
# BOTH HALVES AT ONCE, and neither is `gadget.view`: no kind `gizmo`, and `view`
# is an alias for the one read verb, so the classification cannot pass it by
# luck — and it is a DIFFERENT key from the one the census's own test plants, so
# the count the pin asserts moves.
open(path, "w").write(
    src.replace(anchor, anchor + '\n    "gizmo.view": "You may not view gizmos.",', 1)
)
PY_PLANT
    out="${WORK}/seed-red.txt"
    rc=0
    (cd "$ROOT" && uv run pytest apps/core/tests/test_vocabulary.py \
        -k the_census_refuses_a_nineteenth -p no:randomly -q) >"$out" 2>&1 || rc=$?
    cp "$backup" "$plant"
    if [ "$rc" = "1" ] && grep -q 'FAILED apps/core/tests/test_vocabulary.py::test_the_census_refuses_a_nineteenth' "$out"; then
        ok "$(grep -m1 '^FAILED' "$out")"
    else
        bad "the planted declaration left the census green (exit ${rc}): $(tail -2 "$out" | head -1)"
    fi

    CURRENT="and the plant is restored byte-identical"
    if [ -z "$(git -C "$ROOT" status --porcelain -- apps/example/policies.py)" ]; then
        ok "apps/example/policies.py is back to the committed bytes"
    else
        bad "the plant was not restored — the tree is dirty where this case worked"
    fi
}

# --- the always-on digest on a machine that spells SHA-256 differently -------
#
# `loop_scope__always_digest` is one of the two sites the first off-box gate run
# died at: `scripts/loop_tier.sh: line 721: shasum: command not found` on Amazon
# Linux 2023, where the digest is spelled `sha256sum`. An UNDERIVED digest here
# is not a refusal — the function answers `UNDECLARED` for an unreadable
# declaration — so what the box actually got was an EMPTY digest inside the
# ledger key: a key nothing could ever hit, silently.
#
# THE SIBLING CASE IS `test_loop_ledger.sh`'s
# `case_the_ledgers_digest_is_the_same_where_only_sha256sum_exists`, which
# drives the helper's own two branches and its neither-tool refusal. This one
# asks only the question this file owns: does the scope's digest still answer,
# and answer THE SAME, with the Mac's spelling gone.
case_the_always_on_digest_survives_a_machine_with_no_shasum() {
    CURRENT="the always-on digest with shasum shadowed off PATH"
    local shim="${WORK}/digest-shim" name found d normal shadowed
    mkdir -p "$shim"
    # FIXED DIRECTORIES, not `command -v`: this drive is bash and the shell a
    # human debugs it from may be zsh, where `command -v find` can answer with
    # the bare word and link a shim to itself.
    for name in awk sed sort find tr cat cut head git grep env printf sha256sum; do
        found=""
        for d in /usr/bin /bin /usr/sbin /sbin /opt/homebrew/bin /usr/local/bin; do
            if [ -x "$d/$name" ]; then
                found="$d/$name"
                break
            fi
        done
        [ -n "$found" ] && ln -sf "$found" "$shim/$name"
    done
    if [ ! -x "$shim/sha256sum" ]; then
        # COULD NOT LOOK, AND IT SAYS SO RATHER THAN PASSING. This drive has no
        # skip idiom, and a case that quietly returned 0 on a machine with only
        # one digest tool would report a proven property it never drove.
        cannot_look "this machine has no 'sha256sum' anywhere on the standard paths, so the
   branch a Linux box takes cannot be driven here at all"
    fi
    for name in awk sed find; do
        [ -x "$shim/$name" ] || {
            bad "the shim could not link '$name' — the case would fail for that and read as the digest's failure"
            return 0
        }
    done

    normal="$(loop_scope__always_digest "$ROOT/apps/conftest.py")"
    shadowed="$(PATH="$shim" loop_scope__always_digest "$ROOT/apps/conftest.py")"
    case "$normal" in
    [0-9a-f]*) ok "the digest derives on this machine (${normal:0:12}…)" ;;
    *) bad "the digest did not derive with the ordinary PATH: '${normal}'" ;;
    esac
    is "$shadowed" "$normal" "the digest with only sha256sum on PATH"
}

# --- THE TEST-IMPACT MAP, CONSULTED ------------------------------------------
#
# A FIXTURE MAP OVER THE FIXTURE WORLD, for the reason the fixture world exists
# at all: the selection rule is about what a map SAYS, and a case standing on
# this tree's real map would go red the day an acceptance box re-measures it.
# The real map's own numbers are a MEASUREMENT and belong in the rung's report,
# not in an assertion (`scripts/test_impact.py` writes it; the count moves with
# the suite).
#
# THE POPULATION IS DECLARED, NOT COUNTED BY A READER. `MAP_LEAF_TESTS` tests
# reach `apps/leaf/services.py`; every test in the map reaches
# `apps/core/services.py`, which is the DAG root and the class the map cannot
# help with (architect A2). So a leaf change must select exactly the first
# number and a root change exactly the whole population — the two ends of the
# only claim a selection makes.
MAP_LEAF_TESTS=4
MAP_TESTS=300

# map_entry <nodeid> <file>… — one map line, JSON, no trailing comma logic in
# the caller: the writer below joins them.
map_entry() {
    local nodeid=$1 first=1 file
    shift
    printf '    "%s": [' "$nodeid"
    for file in "$@"; do
        [ "$first" = "1" ] || printf ', '
        printf '"%s"' "$file"
        first=0
    done
    printf ']'
}

# plant_map <repo> [whole|no-leaf|dropped-test]
#
# Writes the fixture map and COMMITS it, a commit after the base. The commit
# matters twice: `generated.tree` names the base's tree — the map's
# PREDECESSOR, exactly as the real writer does, because committing a map moves
# the tree it was measured on — and a tracked map is one the age walk can find
# a commit for.
#
# THE TREE SHA IS LABELLED `tree:` IN THE FIXTURE, and that is not decoration:
# a bare forty-hex string in a JSON file is what `detect-secrets`' high-entropy
# plugin reads as a credential, and JSON has no comment to hang a pragma on.
# The label is the real writer's own (scripts/test_impact.py) and the reader
# strips it.
plant_map() {
    local dir=$1 shape=${2:-whole} tree i first=1
    tree=$(git -C "$dir" rev-parse 'HEAD^{tree}') || return 2
    {
        printf '{\n'
        printf '  "generated": {"at": "2026-09-18T00:00:00+00:00", "pytest": %s, "tree": "tree:%s"},\n' \
            "$MAP_TESTS" "$tree"
        printf '  "tests": {\n'
        i=1
        while [ "$i" -le "$MAP_LEAF_TESTS" ]; do
            if [ "$shape" = "dropped-test" ] && [ "$i" = "1" ]; then
                # THE DANGEROUS HALF. The FILE stays in the map, so nothing
                # falls back — and this one test is simply not there to be
                # selected. Declared, bounded by the wave's bank, and asserted
                # below rather than hoped about.
                i=$((i + 1))
                continue
            fi
            [ "$first" = "1" ] || printf ',\n'
            if [ "$shape" = "no-leaf" ]; then
                map_entry "apps/leaf/tests/test_leaf.py::test_leaf_${i}" \
                    "apps/core/services.py" "apps/conftest.py"
            else
                map_entry "apps/leaf/tests/test_leaf.py::test_leaf_${i}" \
                    "apps/leaf/services.py" "apps/core/services.py" "apps/conftest.py"
            fi
            first=0
            i=$((i + 1))
        done
        i=$((MAP_LEAF_TESTS + 1))
        while [ "$i" -le "$MAP_TESTS" ]; do
            [ "$first" = "1" ] || printf ',\n'
            map_entry "apps/mid/tests/test_mid.py::test_mid_${i}" \
                "apps/mid/services.py" "apps/core/services.py" "apps/conftest.py"
            first=0
            i=$((i + 1))
        done
        printf '\n  },\n'
        printf '  "unmapped": {}\n'
        printf '}\n'
    } >"$dir/scripts/test_impact.json"
    git -C "$dir" add scripts/test_impact.json
    git -C "$dir" commit -q -m "the fixture map"
}

# selection_holds <nodeid> — the written selection file names it.
selection_holds() {
    if [ -z "$LOOP_SCOPE_IMPACT_SELECT" ] || [ ! -f "$LOOP_SCOPE_IMPACT_SELECT" ]; then
        bad "there is no selection file to look in"
        return 0
    fi
    if grep -Fxq -- "$1" "$LOOP_SCOPE_IMPACT_SELECT"; then
        ok "the selection names ${1}"
    else
        bad "the selection does not name ${1}"
    fi
}

fallback_says() {
    case "$LOOP_SCOPE_IMPACT_FALLBACK" in
    *"$1"*) ok "the fallback sentence says \"$1\"" ;;
    *) bad "the fallback sentence does not say \"$1\" — it says '${LOOP_SCOPE_IMPACT_FALLBACK}'" ;;
    esac
}

# args_for — the pytest flags this derivation would hand the leg, one per line.
args_for() {
    LOOP_IMPACT=1
    loop_scope__pytest_args
    LOOP_IMPACT=""
}

args_carry() {
    local want=$1 args
    args=$(args_for)
    case "
$args" in
    *"
$want"*) ok "the pytest args carry ${want}" ;;
    *) bad "the pytest args do not carry ${want} — they are [$(printf '%s ' $args)]" ;;
    esac
}

args_do_not_carry() {
    local want=$1 args
    args=$(args_for)
    case "
$args" in
    *"
$want"*) bad "the pytest args still carry ${want} — [$(printf '%s ' $args)]" ;;
    *) ok "the pytest args do NOT carry ${want}" ;;
    esac
}

case_a_seen_leaf_file_selects_only_its_tests() {
    fresh_checkout
    plant_map "$REPO" whole
    echo "changed" >>"$REPO/apps/leaf/services.py"
    LOOP_IMPACT=1
    scope_in "$REPO" "a leaf file the map has seen"
    LOOP_IMPACT=""
    is "$RC" "0" "the exit status"
    is "$LOOP_SCOPE_IMPACT_SEEN" "1" "the number of changed files the map has seen"
    is "$LOOP_SCOPE_IMPACT_TESTS" "$MAP_LEAF_TESTS" "the number of tests selected"
    is "$LOOP_SCOPE_IMPACT_FALLBACK" "" "the fallback sentence (empty: the map answered)"
    selection_holds "apps/leaf/tests/test_leaf.py::test_leaf_1"
    CURRENT="a leaf file the map has seen: the selection excludes the rest"
    if [ -n "$LOOP_SCOPE_IMPACT_SELECT" ] &&
        grep -Fq 'test_mid_' "$LOOP_SCOPE_IMPACT_SELECT"; then
        bad "a mid test the change cannot reach is in the selection"
    else
        ok "no test outside the ${MAP_LEAF_TESTS} the map attributes to the file is selected"
    fi
    # THE CLOSURE IS STILL DERIVED AND IS NOT WHAT RUNS. `leaf` declares `mid`,
    # which declares `core`, so today's scope for this touch is `leaf` alone —
    # and the point of the selection is that even THAT is not passed.
    is "$LOOP_SCOPE_APPS" "leaf" "the closure scope the map replaced"
    args_carry "--djb-impact-select=${LOOP_SCOPE_IMPACT_SELECT}"
    args_carry "--djb-changed=apps/leaf/services.py"
    args_do_not_carry "--djb-scope=leaf"
    args_do_not_carry "--djb-scope-narrow"
    CURRENT="a leaf file the map has seen: the key carries the map"
    case "$LOOP_SCOPE_CANONICAL" in
    *" map="?*) ok "$LOOP_SCOPE_CANONICAL" ;;
    *) bad "the canonical scope carries no map= field: ${LOOP_SCOPE_CANONICAL}" ;;
    esac
}

case_a_never_seen_file_falls_back_and_says_so() {
    # FIVE PLANTS, ONE EACH, AND EACH ONE A CLASS THE MAP CANNOT SEE BY
    # CONSTRUCTION: coverage records executed Python lines, so a template, an
    # environment file, a fixture, a rules file and a migration are all
    # invisible to it. The fifth — the migration — is the one that looks like
    # an app file and is not.
    #
    # `.env` ITSELF IS NOT ONE OF THE FIVE and the substitution is declared:
    # this tree's fan-out table has no row for a bare `.env` (it is ignored and
    # cannot reach a changed-file set), so a tracked one is EXIT 2 at the
    # table — a stronger answer than a fallback, and the table was left as it
    # stands. `.env.example`, which is tracked and classified, stands in its
    # place.
    local plant
    for plant in templates/x.html .env.example apps/leaf/fixtures/a.json \
        quality/rules.yaml apps/leaf/migrations/0002_x.py; do
        fresh_checkout
        mkdir -p "$REPO/$(dirname "$plant")"
        echo "base" >"$REPO/$plant"
        git -C "$REPO" add "$plant"
        # `|| true`: two of the five plants are already in the base commit
        # (the fixture world creates them), and a commit with nothing staged
        # is a non-zero exit about a no-op.
        git -C "$REPO" commit -q -m "the plant, in the base" || true
        plant_map "$REPO" whole
        echo "changed" >>"$REPO/$plant"
        LOOP_IMPACT=1
        scope_in "$REPO" "a never-seen file: ${plant}"
        LOOP_IMPACT=""
        is "$RC" "0" "the exit status"
        is "$LOOP_SCOPE_IMPACT_SELECT" "" "the selection (empty: the map has never seen it)"
        fallback_says "$plant"
        fallback_says "never recorded by the map"
        CURRENT="a never-seen file: ${plant} — the key still names the map"
        case "$LOOP_SCOPE_CANONICAL" in
        *" map="?*) ok "$LOOP_SCOPE_CANONICAL" ;;
        *) bad "no map= field: ${LOOP_SCOPE_CANONICAL}" ;;
        esac
        CURRENT="a never-seen file: ${plant} — today's scope is what runs"
        if [ "$LOOP_TIER_MODE" = "full" ]; then
            # `templates/**` is a FULL-suite row in the fan-out table, and the
            # table outranks the map: there is no scope to pass because there
            # is no scope, and the fallback sentence says both halves.
            ok "mode=full — the table outranks the map, and no scope flag is emitted"
            args_do_not_carry "--djb-scope-narrow"
        else
            args_carry "--djb-scope-narrow"
            args_do_not_carry "--djb-impact-select"
        fi
    done
}

case_a_root_file_selects_everything_it_touches() {
    # THE CLASS THE MAP CANNOT HELP WITH, MEASURED RATHER THAN ASSUMED
    # (architect A2: `core` is the DAG root). Every test in the fixture map
    # executes `apps/core/services.py`, so the honest selection is the whole
    # population — and the loop says the number instead of implying a
    # narrowing it did not make.
    fresh_checkout
    plant_map "$REPO" whole
    echo "changed" >>"$REPO/apps/core/services.py"
    LOOP_IMPACT=1
    scope_in "$REPO" "a root file every test executes"
    LOOP_IMPACT=""
    is "$RC" "0" "the exit status"
    is "$LOOP_SCOPE_IMPACT_TESTS" "$MAP_TESTS" "the number of tests selected"
    is "$LOOP_SCOPE_IMPACT_FALLBACK" "" "the fallback sentence (empty: the map answered)"
    CURRENT="a root file: the selection is honest about being the whole population"
    if [ "$LOOP_SCOPE_IMPACT_TESTS" = "$MAP_TESTS" ]; then
        ok "the root file selects all ${MAP_TESTS} — a narrowing of nothing, printed as such"
    else
        bad "the root file selected ${LOOP_SCOPE_IMPACT_TESTS} of ${MAP_TESTS}"
    fi
}

case_a_removed_entry_falls_back_and_a_dropped_test_is_the_declared_hole() {
    # (a) THE CANARY. The map loses the FILE entirely — which is what a map
    #     written before the file existed looks like — and the whole run falls
    #     back to today's closure scope, so every test that would have been
    #     selected runs anyway.
    fresh_checkout
    plant_map "$REPO" no-leaf
    echo "changed" >>"$REPO/apps/leaf/services.py"
    LOOP_IMPACT=1
    scope_in "$REPO" "the map lost the file: the closure still runs it"
    LOOP_IMPACT=""
    is "$RC" "0" "the exit status"
    is "$LOOP_SCOPE_IMPACT_SELECT" "" "the selection (empty: fallback)"
    fallback_says "apps/leaf/services.py"
    args_carry "--djb-scope=leaf"
    args_do_not_carry "--djb-impact-select"

    # (b) THE DANGEROUS HALF, ASSERTED RATHER THAN HOPED ABOUT. The file stays
    #     in the map and ONE test that touches it is dropped: nothing falls
    #     back, the run is green, and that test does not run. This is the
    #     declared hole — bounded by the map's age (printed on every run) and
    #     by the bank, which runs everything, once per wave.
    fresh_checkout
    plant_map "$REPO" dropped-test
    echo "changed" >>"$REPO/apps/leaf/services.py"
    LOOP_IMPACT=1
    scope_in "$REPO" "a dropped map entry is a test nobody runs"
    LOOP_IMPACT=""
    is "$RC" "0" "the exit status"
    is "$LOOP_SCOPE_IMPACT_TESTS" "$((MAP_LEAF_TESTS - 1))" "the number of tests selected"
    CURRENT="a dropped map entry: the hole is real and this case names it"
    if [ -n "$LOOP_SCOPE_IMPACT_SELECT" ] &&
        grep -Fxq -- 'apps/leaf/tests/test_leaf.py::test_leaf_1' "$LOOP_SCOPE_IMPACT_SELECT"; then
        bad "the dropped test is in the selection — this case is not testing what it claims"
    else
        ok "the dropped test is NOT selected: a map that forgets a test silently narrows, which is why the map's age is printed on every run and the bank runs the whole suite once per wave"
    fi
}

case_an_absent_map_is_the_closure_scope() {
    fresh_checkout
    echo "changed" >>"$REPO/apps/leaf/services.py"
    LOOP_IMPACT=1
    scope_in "$REPO" "no map at all"
    LOOP_IMPACT=""
    is "$RC" "0" "the exit status — an absent map is never a refusal"
    is "$LOOP_SCOPE_IMPACT_SELECT" "" "the selection (empty: there is no map)"
    is "$LOOP_SCOPE_MAP_SHA" "-" "the map sha in the key"
    fallback_says "absent or unreadable"
    args_carry "--djb-scope=leaf"
    CURRENT="no map at all: the key says so rather than omitting the field"
    case "$LOOP_SCOPE_CANONICAL" in
    *" map=-") ok "$LOOP_SCOPE_CANONICAL" ;;
    *) bad "the canonical scope does not end in map=-: ${LOOP_SCOPE_CANONICAL}" ;;
    esac
}

case_an_unreadable_map_is_the_closure_scope_and_not_exit_2() {
    fresh_checkout
    plant_map "$REPO" whole
    printf 'this is not JSON\n' >"$REPO/scripts/test_impact.json"
    echo "changed" >>"$REPO/apps/leaf/services.py"
    LOOP_IMPACT=1
    scope_in "$REPO" "a map that is not a map"
    LOOP_IMPACT=""
    is "$RC" "0" "the exit status — could-not-read is a BIGGER run, never a refusal"
    is "$LOOP_SCOPE_IMPACT_SELECT" "" "the selection (empty: the map could not be read)"
    fallback_says "could not be read as a map"
    args_carry "--djb-scope=leaf"
}

case_the_map_sha_is_in_the_loop_key() {
    # TWO MAPS OVER ONE TREE ARE TWO KEYS. The loop ledger keys a verdict on
    # the tree AND the canonical scope, so a selection made under one map must
    # never be vouched for by a verdict banked under another — and the only
    # thing in the key that can say which map is this field.
    fresh_checkout
    plant_map "$REPO" whole
    echo "changed" >>"$REPO/apps/leaf/services.py"
    LOOP_IMPACT=1
    scope_in "$REPO" "the first map"
    LOOP_IMPACT=""
    local first="$LOOP_SCOPE_CANONICAL" first_sha="$LOOP_SCOPE_MAP_SHA"
    # A SECOND MAP OVER THE SAME TREE: one more test against the same file.
    MAP_TESTS=$((MAP_TESTS + 1))
    git -C "$REPO" checkout -q -- apps/leaf/services.py
    plant_map "$REPO" whole
    MAP_TESTS=$((MAP_TESTS - 1))
    echo "changed" >>"$REPO/apps/leaf/services.py"
    LOOP_IMPACT=1
    scope_in "$REPO" "the second map, same tree"
    LOOP_IMPACT=""
    CURRENT="two maps over one tree are two keys"
    if [ "$first_sha" = "$LOOP_SCOPE_MAP_SHA" ]; then
        bad "both maps digested to ${first_sha} — the fixture did not change the map"
    elif [ "$first" = "$LOOP_SCOPE_CANONICAL" ]; then
        bad "two maps, one canonical scope: ${first}"
    else
        ok "map=${first_sha} -> map=${LOOP_SCOPE_MAP_SHA}, and the canonical scope moved with it"
    fi
    CURRENT="the map field is LAST, the append precedent every field since tests= took"
    case "$LOOP_SCOPE_CANONICAL" in
    *"alwayson="*" map="*) ok "$LOOP_SCOPE_CANONICAL" ;;
    *) bad "map= is not appended after alwayson=: ${LOOP_SCOPE_CANONICAL}" ;;
    esac
}

case_the_valve_widens_and_keys_itself() {
    # THE VALVE IS THE MEASUREMENT'S OTHER HALF — the same change run with the
    # map and without it — and it can only WIDEN. It keys itself, because a
    # person who typed it asked for the bigger run and must not be handed a
    # verdict banked by the smaller one.
    fresh_checkout
    plant_map "$REPO" whole
    echo "changed" >>"$REPO/apps/leaf/services.py"
    DJB_LOOP_NO_IMPACT=1
    LOOP_IMPACT=1
    scope_in "$REPO" "the valve: today's closure scope"
    LOOP_IMPACT=""
    DJB_LOOP_NO_IMPACT=""
    is "$RC" "0" "the exit status"
    is "$LOOP_SCOPE_IMPACT_SELECT" "" "the selection (empty: the valve was typed)"
    is "$LOOP_SCOPE_MAP_SHA" "bypassed" "the map field in the key"
    fallback_says "DJB_LOOP_NO_IMPACT"
    args_carry "--djb-scope=leaf"
}

case_mine_and_pr_do_not_consult_the_map_and_still_carry_it() {
    # `--mine` IS A CLAIM ABOUT AN APP. A selection reaching into a DEPENDANT
    # of that app to run one test would be a third thing wearing the flag's
    # name, so the map is not consulted — and the key still says which map the
    # tree carried, so a row can always be read against it.
    fresh_checkout
    plant_map "$REPO" whole
    echo "changed" >>"$REPO/apps/leaf/services.py"
    LOOP_MINE=1
    scope_in "$REPO" "--mine does not consult the map"
    LOOP_MINE=""
    is "$RC" "0" "the exit status"
    is "$LOOP_SCOPE_IMPACT_SELECT" "" "the selection (empty: --mine did not ask)"
    fallback_says "the caller did not ask for the map"
    CURRENT="--mine carries the map sha in its key"
    case "$LOOP_SCOPE_CANONICAL" in
    "mode=mine"*" map="?*) ok "$LOOP_SCOPE_CANONICAL" ;;
    *) bad "a --mine key with no map= field: ${LOOP_SCOPE_CANONICAL}" ;;
    esac
    CURRENT="and the flags are the ones --mine passed before the map existed"
    local args
    args=$(loop_scope__pytest_args)
    case "
$args" in
    *"
--djb-changed="*) bad "--mine now passes --djb-changed: [$(printf '%s ' $args)]" ;;
    *) ok "no --djb-changed under --mine: [$(printf '%s ' $args)]" ;;
    esac
}

# --- the cases, in the order they should run ---------------------------------

case_an_empty_capture_is_could_not_look
case_the_always_on_digest_survives_a_machine_with_no_shasum
case_a_collapsed_checkout_derives_the_same_scope_when_the_base_is_carried
case_a_policies_touch_census_seeds_the_vocabulary_module
case_roles_seed_the_same_census_and_ordinary_files_seed_nothing
case_the_seeded_census_goes_red_on_a_planted_nineteenth_key
case_a_core_touch_reaches_every_app_through_the_closure_alone
case_the_transitive_step_is_walked_not_one_hop
case_forward_edges_are_not_widened
case_config_is_the_full_suite_with_its_sentence
case_templates_are_the_full_suite
case_quality_widens_no_pytest_scope_and_names_the_rule_that_outranks
case_a_frontend_only_touch_derives_an_empty_backend_scope
case_the_shared_shapes_outrank_an_app_touched_beside_them
case_the_reflexive_shape_covers_the_whole_selection_machinery
case_the_declared_blind_spot_widens_nothing_and_says_so
case_an_unclassifiable_path_is_exit_2_naming_the_path_and_the_table
case_the_one_legal_override_only_widens
case_a_tests_only_touch_seeds_no_closure_and_is_not_own
case_one_non_test_path_makes_the_app_an_ordinary_touch
case_a_core_tests_edit_beside_a_leaf_touch_walks_the_leafs_closure_only
case_a_migration_touch_widens_by_the_import_graph_not_by_tests
case_an_apps_root_conftest_is_an_ordinary_touch_not_tests_only
case_also_outranks_tests_only
case_the_canonical_key_differs_between_a_tests_only_and_an_own_app_run
case_a_path_under_apps_the_table_cannot_place_is_exit_2
case_an_absent_local_main_is_a_refusal_not_a_thin_basis
case_on_main_the_uncommitted_only_basis_stays_legal_and_prints_itself
case_an_undiscoverable_app_is_exit_2_naming_its_apps_py
case_a_broken_changed_file_derivation_is_the_inherited_exit_2
case_the_floors_refuse_when_the_cross_app_derivation_returns_nothing
case_a_floor_member_moved_aside_is_a_refusal
case_a_drawer_raised_floor_refuses_a_member_moved_aside_on_a_six_module_tree
case_the_always_on_set_survives_the_real_parallel_invocation
case_a_narrower_scope_selects_strictly_less_than_a_wider_one
case_a_planted_apps_root_census_runs_at_every_scope
case_the_mine_arm_in_the_placement_case_matches_the_flags_check_sh_passes
case_mine_runs_own_apps_only_and_never_banks
case_a_tests_only_comms_touch_is_not_own_and_widens_to_its_importers
case_the_edited_test_module_runs_whatever_tier_it_is_in
case_a_files_touch_selects_the_exports_tests_through_the_closure
case_the_banner_prints_every_decision_before_the_first_test
case_the_pre_run_counts_agree_with_the_reconciliation
case_a_tests_only_core_touch_widens_to_every_cross_app_importer
case_a_dying_collector_leaves_a_named_absence_not_silence
case_last_failed_reruns_only_the_failure
case_the_cache_directory_cannot_move_a_verdict_key
case_test_sh_refuses_n_auto_and_names_the_share
case_a_typed_n_above_the_share_is_clamped_and_printed
case_census_runs_the_instrument_census_alone_without_a_slot
case_the_typed_escape_prints_and_lifts_the_clamp
case_the_python_clamp_and_the_shell_share_are_the_same_number
case_a_tree_miss_prints_three_lines_every_other_miss_two_and_the_detail_on_request
case_pr_refuses_an_uncomputable_impact_map_before_taking_the_lease
case_pr_refuses_an_unaccountable_label_above_the_lease
case_pr_removes_its_counts_directory_on_every_path
case_pr_without_a_sanction_is_the_full_gates_refusal
case_pr_narrows_pytest_and_nothing_else
case_a_files_touch_under_pr_selects_the_exports_tests_and_names_the_closure
case_an_organ_test_in_a_closure_added_app_runs_under_pr_and_not_under_loop
case_pr_with_an_empty_diff_runs_the_always_on_set_and_says_so
case_pr_ignores_a_banked_partition_row
case_pr_writes_no_verdict_row_and_no_partition_row
case_the_planted_miss_triple
case_a_substitution_callees_refusal_surfaces_as_cause
case_a_banner_with_no_recorded_cause_is_exit_2
case_a_typed_slot_share_is_the_workers_number_and_no_clamp_fires
case_a_typed_share_above_the_slot_is_refused_naming_both
case_a_bank_runs_every_slots_share_and_the_census_agrees
case_a_dead_collector_under_a_bank_still_refuses
case_the_full_gate_passes_write_counts_and_the_whole_suite_reconciles
case_a_dying_collector_under_the_full_gate_leg_body_is_exit_2_and_banks_nothing
case_a_dying_collector_under_pr_is_exit_2_and_writes_no_narrowed_run_note
case_the_full_counts_dir_is_removed_on_an_early_red

case_a_seen_leaf_file_selects_only_its_tests
case_a_never_seen_file_falls_back_and_says_so
case_a_root_file_selects_everything_it_touches
case_a_removed_entry_falls_back_and_a_dropped_test_is_the_declared_hole
case_an_absent_map_is_the_closure_scope
case_an_unreadable_map_is_the_closure_scope_and_not_exit_2
case_the_map_sha_is_in_the_loop_key
case_the_valve_widens_and_keys_itself
case_mine_and_pr_do_not_consult_the_map_and_still_carry_it

echo "test_loop_scope: ${PASSED} passed · ${FAILED} failed"
# Every case ran. Anything below here is a verdict on them, not another case —
# see section 5 of the preamble for why saying so is load-bearing.
drive_finished
if [ "$FAILED" -gt 0 ]; then
    echo "!! the --loop SCOPE is not behaving as declared. A scope is a claim that" >&2
    echo "   everything it deselected could not have been broken by the active rung; every" >&2
    echo "   way that claim goes wrong is silent and looks like speed." >&2
    exit 1
fi
exit 0
