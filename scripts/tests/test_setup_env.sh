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
# drives: .env.example .github/workflows/ci.yml README.md apps/conftest.py compose.yaml deploy/tests/test_release.sh scripts/check.sh scripts/db.sh scripts/gate_ledger.sh scripts/gate_refuse.sh scripts/kill_mine.sh scripts/loop_tier.sh scripts/queue_cited.sh scripts/rung_start.sh scripts/secrets_scan.sh scripts/setup.sh scripts/sweep.sh scripts/verifier_box.sh scripts/verify_start.sh
# cites: config/settings/test.py apps/files/tests/test_store_credential_belt.py
set -euo pipefail

# The drive for the sentinel-fenced blocks of `scripts/setup.sh`: the
# environment step (`env_sync_from_example` and its two helpers), the services
# step (`services_up`, which pulls before it starts and refuses when the pull
# fails), the local-main step (`ensure_local_main`, the first step, which gives
# a tag clone the `refs/heads/main` every scope tool in this tree reads by name)
# and the step wall (`step`/`step_end`/`setup_total`, the clock). They are
# fenced for the same reason — the rest of that script brings up docker, syncs a
# venv and talks to an identity provider, and a drive that needed any of that
# would be could-not-look on the machine that most needs it.
#
#   ./scripts/tests/test_setup_env.sh          run every case
#   ./scripts/tests/test_setup_env.sh --list   name them and stop
#
# WHY IT EXISTS. The per-rung ledger keys a banked verdict partly on a digest of
# `.env` — every line of it, in file order, comments and blanks included, minus
# the keys a deriver declares (`loop_env_fingerprint`, `scripts/gate_ledger.sh`).
# A verifier's clone builds its `.env` from `.env.example` and substitutes the
# derived database name and the identity carry in place, so a builder's checkout
# reuses that clone's verdict only while its own `.env` is the same skeleton.
# The environment step used to leave an existing `.env` alone, so every checkout
# drifted one line further from the example on every merge that touched it, and
# a consult that should have cost a second re-measured the whole suite instead
# (measured on this box, 2026-09-07: 162s against 1s, and 592 lines of
# difference in prose alone).
#
# So the step now REGENERATES the file, and every failure mode of a regeneration
# is expensive in a different direction:
#
#   * a value silently lost — the checkout's database name, its identity
#     credential, anything a human typed. The drive asserts the whole result
#     byte-for-byte against a file written out in full below, and asserts
#     separately that a value carrying an `=` and a value carrying a `#` come
#     through unchanged: those are the two shapes a key/value split gets wrong.
#   * a key the example has since dropped, dropped with it. The drive asserts
#     the kept block, by name and position.
#   * a VALUE ON STDOUT. The report block names keys and counts them; the first
#     key this file carries is a machine credential and a setup log gets pasted
#     into reports. The drive greps the whole block for `=` and fails on a hit.
#   * a run that is not idempotent — a kept block appended twice, a line moved —
#     which would make every second `setup.sh` a fresh digest and put the miss
#     straight back.
#
# IT NEVER RUNS `setup.sh`, AND IT NEVER TALKS TO A REAL DAEMON. It EXTRACTS the
# fenced blocks — between the `env-sync` sentinels, and between the `services`
# ones — and sources them into a scratch directory with `make_tmp` stubbed and,
# for the services cases, a `docker` script first on PATH. The extraction is the
# precedent `scripts/loop_tier.sh` set reading `apps/conftest.py`: the real text
# runs, and a sentinel that is gone is could-not-look rather than a green run
# over a function nobody defined.
#
# WHY THE SERVICES STEP IS DRIVEN AT ALL (measured 2026-09-12). `compose.yaml`
# pinned MinIO's Docker Hub release; Docker Hub stopped serving that tag; `setup.sh` — the first thing a stranger runs — went straight to
# `docker compose up -d` and the failure arrived in compose's vocabulary, or as
# `wait_healthy` counting to 180 against a container that could not exist. The
# step now pulls first and a failed pull is exit 2 naming the image and its
# registry. A registry that has stopped serving a tag cannot be arranged on the
# box running this drive, so the shim is not a convenience: it is the only way
# this refusal can be driven anywhere.
#
# THE FIXTURES ARE BUILT HERE and live under `mktemp -d`. Nothing plants in this
# checkout's own `.env`, which is the one file in a worktree whose loss costs a
# human their afternoon.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * THE REST OF `setup.sh`. The call site is asserted as text — that the step
#     calls the function and that the mode-600 line still follows it — and
#     nothing here runs the step in a real checkout.
#   * THE REAL DIGEST. The digest case below holds a COPY of the drop-by-key
#     `awk` and of the SHA-256 that `gate_ledger.sh` takes over its output,
#     because sourcing that file would drag in a venv census, git and a working
#     tree. The shipped side spells that digest `sha256_of` (one helper in
#     `scripts/gate_refuse.sh` that resolves `shasum -a 256` or `sha256sum`
#     depending on the machine); the model here resolves the same two tools
#     inline, so this drive runs on a box that has only one of them. The copy is
#     a MODEL: it proves the agreement property (identical files agree, a kept
#     key differs) and it is anchored by one case that asserts the shipped
#     digest still has the same shape. A rule change in `gate_ledger.sh` that
#     kept that shape and changed the meaning would pass here.
#   * WHETHER `.env.example` IS ITSELF RIGHT. The regeneration trusts the
#     example's own syntax; a line the example gets wrong is copied wrong, and
#     that is deliberate — the example is the contract.
#   * A KEY A HUMAN SET BY HAND THAT THE EXAMPLE LACKS. It is kept, and it is an
#     honest permanent difference against any clone until the example grows the
#     key. The kept block names it; nothing here calls that a defect.
#   * THE COMMENTS A HUMAN ADDED to their own `.env`. They are not kept, on
#     purpose — the example owns the prose — and no case asserts otherwise.
#   * WHETHER A REAL REGISTRY SERVES A REAL TAG. The shim answers; nothing here
#     dials a registry. That a pin RESOLVES is a `docker manifest
#     inspect` on a box with network, run by hand and pasted — never a case,
#     because a case that needed the internet would be red on an aeroplane and
#     green nowhere useful.
#   * WHETHER CI'S LOGIN WORKS. The workflow case reads the steps' shape — the
#     QEMU handler, the role assumed in us-east-1, the public-registry login,
#     all before the up, and `id-token: write` on the job. Whether the role
#     actually carries the `ecr-public-login` policy is IAM's answer, read on a
#     real run's log (`Login Succeeded`), never here. A step counts only with
#     no `if:` or exactly `vars.AWS_ECR_ROLE_ARN != ''`; what it still cannot
#     see is a guard that is true in text and false at run time — that
#     variable unset on the repository skips the login, and only the run's
#     log says so.
#   * WHETHER `docker compose config --images` ANSWERS THE WAY THE SHIM DOES.
#     The shim reads the scratch compose file's `image:` lines, which is what
#     that subcommand answers for a file with no build stanzas and no variable
#     substitution. A compose file whose image came from a `${VAR}` or a build
#     would be rendered by real compose and copied verbatim by the shim.
#   * THE REAL PULL, AND WHAT IT COSTS. Nothing here measures the wall clock a
#     `compose pull` adds to a fresh `setup.sh`, nor the reuse path on a box
#     where one service of seven is unhealthy (there the step pulls all seven).
#   * A SHALLOW OR SINGLE-BRANCH TAG CLONE — HALF DRIVEN NOW, and the half that
#     is not is named. `case_the_printed_remedy_runs_where_the_step_leaves_you`
#     builds a REAL `--depth 1 --single-branch` tag clone (measured on it: no
#     remote-tracking ref exists there at all, not merely no `origin/main`) and
#     runs the step and the sentence's follow-up in it. What is still NOT driven
#     on that shape is what the loop scope's merge-base and the secret scan's
#     basis answer over a truncated history — the ref exists, its ancestry does
#     not, and nothing here asks those two tools about it.
#   * A DIRTY DETACHED CHECKOUT. `git switch` to a branch at the same commit
#     carries uncommitted work across, and git allows it; the tag-clone case
#     below runs on a clean clone and nothing here asserts what a dirty one
#     does.
#   * A REPOSITORY WHOSE DEFAULT BRANCH IS NOT `main`. `ensure_local_main`
#     would create a `main` beside a product's `trunk`. Every scope tool in this
#     tree reads `refs/heads/main` by name, so such a product has already forked
#     the gate; declared rather than guarded.
#   * WHAT THE CLOCK MEASURES. The timing case asserts the SHAPE of the lines —
#     two steps, two walls, one total. Whether the number is the right number is
#     a property of this box, and a stack pulling seven images on a slow link
#     dominates any total this script can print.
#   * `setup.sh` END TO END. Nothing here runs the script. The local-main step's
#     POSITION is asserted as text (it is first, and the environment step
#     follows it) and its BODY is driven in scratch clones; the two together are
#     not the same as a real run, and the first-ten-minutes rehearsal on a fresh
#     tag clone is the field test's, never a case's.

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_setup_env: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It carries the only thing keeping this drive's scratch work inside its" >&2
    echo "   own scratch directory. Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh
DRIVE_OPTED_IN_TO_FINISH=1

PASSED=0
FAILED=0

cannot_look() {
    echo "!! test_setup_env: $*" >&2
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
    # A mistyped flag is never a silently different run.
    echo "!! unknown argument '$1': test_setup_env.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

command -v shasum >/dev/null 2>&1 || command -v sha256sum >/dev/null 2>&1 ||
    cannot_look "neither shasum nor sha256sum is on PATH — the digest case cannot be computed"
[ -f scripts/setup.sh ] || cannot_look "scripts/setup.sh is not in this tree — there is nothing to drive"
[ -f scripts/gate_ledger.sh ] || cannot_look "scripts/gate_ledger.sh is not in this tree — the digest anchor cannot be read"
[ -f scripts/check.sh ] || cannot_look "scripts/check.sh is not in this tree — the wiring cannot be read"

ROOT="$PWD"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-setup-env-drive.XXXXXX")" || cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'chmod -R u+rwX "$WORK" 2>/dev/null || true; rm -rf "$WORK"'

# --- THE EXTRACTION, and the drive's honest could-not-look --------------------
#
# The sentinels are assembled rather than written at the head of a line, so a
# reader grepping the tree for the fence finds `setup.sh` and not this file too.
SENT_OPEN="# >>> env-sync >>>"
SENT_CLOSE="# <<< env-sync <<<"
EXTRACT="${WORK}/env_sync.sh"

sed -n "/^${SENT_OPEN}\$/,/^${SENT_CLOSE}\$/p" scripts/setup.sh >"$EXTRACT" 2>/dev/null || true

grep -qxF "$SENT_OPEN" "$EXTRACT" 2>/dev/null ||
    cannot_look "scripts/setup.sh has no line reading exactly \`${SENT_OPEN}\` — the env-sync fence is gone (or was never there, which is what a baseline tree looks like). Every case below sources the text between that sentinel and \`${SENT_CLOSE}\`, so there is no function to drive."
grep -qxF "$SENT_CLOSE" "$EXTRACT" 2>/dev/null ||
    cannot_look "scripts/setup.sh opens the env-sync fence with \`${SENT_OPEN}\` and never closes it with \`${SENT_CLOSE}\`. The extraction ran to the end of the file."
grep -q '^env_sync_from_example() {' "$EXTRACT" ||
    cannot_look "the env-sync fence in scripts/setup.sh defines no env_sync_from_example — the function this drive exists for is not inside its own sentinels."

# `make_tmp` is `setup.sh`'s, and it is not inside the fence: it owns a
# process-wide registry and an EXIT trap that a drive must not inherit. The stub
# has the one property the fenced code relies on — it ASSIGNS to the variable
# named by its argument and prints nothing (a `$(...)` form would run in a
# subshell and the assignment would not survive it).
make_tmp() {
    local __t="$1"
    printf -v "$__t" '%s' "$(mktemp "${WORK}/tmp.XXXXXXXX")"
}

# THE `# pinned` GRAMMAR IS scripts/db.sh's (`DB_PIN_MARKER_ERE`), and the fence
# reads it rather than spelling a second copy — so the drive sources db.sh the
# way setup.sh does before the environment step. Its source-time pin note is
# about THIS checkout's .env and goes nowhere a case reads.
# shellcheck source=scripts/db.sh
. scripts/db.sh 2>/dev/null
# shellcheck source=/dev/null
. "$EXTRACT"
command -v env_sync_from_example >/dev/null 2>&1 ||
    cannot_look "sourcing the extracted fence defined no env_sync_from_example"

# --- THE SECOND FENCE: the services step --------------------------------------
#
# Same mechanism, same reason. The services step pulls before it starts and
# REFUSES when the pull fails, which is a thing that can only be driven with a
# docker that is not this box's — so the step lives inside its own sentinels and
# the cases below source it beside a shim.
SENT_SVC_OPEN="# >>> services >>>"
SENT_SVC_CLOSE="# <<< services <<<"
EXTRACT_SVC="${WORK}/services.sh"

sed -n "/^${SENT_SVC_OPEN}\$/,/^${SENT_SVC_CLOSE}\$/p" scripts/setup.sh >"$EXTRACT_SVC" 2>/dev/null || true

grep -qxF "$SENT_SVC_OPEN" "$EXTRACT_SVC" 2>/dev/null ||
    cannot_look "scripts/setup.sh has no line reading exactly \`${SENT_SVC_OPEN}\` — the services fence is gone (or was never there, which is what a baseline tree looks like). The pull-failure cases below source the text between that sentinel and \`${SENT_SVC_CLOSE}\`, so there is no step to drive."
grep -qxF "$SENT_SVC_CLOSE" "$EXTRACT_SVC" 2>/dev/null ||
    cannot_look "scripts/setup.sh opens the services fence with \`${SENT_SVC_OPEN}\` and never closes it with \`${SENT_SVC_CLOSE}\`. The extraction ran to the end of the file."
grep -q '^services_up() {' "$EXTRACT_SVC" ||
    cannot_look "the services fence in scripts/setup.sh defines no services_up — the step this drive exists to refuse for is not inside its own sentinels."

# The three names the fence stands on and does not define. They are `setup.sh`'s
# and they are OUTSIDE the fence on purpose — `SERVICES` is the contract about
# what a fresh clone needs up, and the two health helpers talk to a real daemon.
# `service_health` is a COPY of setup.sh's, minus its pipe: the shim answers one
# line anyway and a copy that reads the same first line is enough for a stub.
SERVICES=(db minio)
service_health() {
    local out
    out="$(docker compose ps --format '{{.Health}}' "$1" 2>/dev/null)"
    printf '%s\n' "${out%%$'\n'*}"
}
stack_is_healthy() {
    local service
    for service in "${SERVICES[@]}"; do
        [ "$(service_health "$service")" = "healthy" ] || return 1
    done
    return 0
}
# The stub SAYS SO when it is entered, because "wait_healthy is never entered"
# is half of what the refusal case asserts and an absence nobody can see is not
# an assertion.
wait_healthy() {
    echo "wait_healthy ENTERED for $1"
    return 0
}

# shellcheck source=/dev/null
. "$EXTRACT_SVC"
command -v services_up >/dev/null 2>&1 ||
    cannot_look "sourcing the extracted services fence defined no services_up"
command -v image_registry_host >/dev/null 2>&1 ||
    cannot_look "sourcing the extracted services fence defined no image_registry_host — the refusal cannot name a registry it cannot read"

# --- THE THIRD FENCE: the local-main step -------------------------------------
#
# Same mechanism, third time. `ensure_local_main` is the FIRST step of
# `setup.sh` and the one that has to work on a checkout nobody here can arrange
# by hand: a clone of a published TAG, detached, with no `refs/heads/main`. The
# cases below build exactly that — a scratch repository, a tag on it, and a real
# `git clone --branch <tag>` of it — so the victim is made rather than found.
SENT_MAIN_OPEN="# >>> local-main >>>"
SENT_MAIN_CLOSE="# <<< local-main <<<"
EXTRACT_MAIN="${WORK}/local_main.sh"

sed -n "/^${SENT_MAIN_OPEN}\$/,/^${SENT_MAIN_CLOSE}\$/p" scripts/setup.sh >"$EXTRACT_MAIN" 2>/dev/null || true

grep -qxF "$SENT_MAIN_OPEN" "$EXTRACT_MAIN" 2>/dev/null ||
    cannot_look "scripts/setup.sh has no line reading exactly \`${SENT_MAIN_OPEN}\` — the local-main fence is gone (or was never there, which is what a baseline tree looks like). Every tag-clone case below sources the text between that sentinel and \`${SENT_MAIN_CLOSE}\`, so there is no step to drive."
grep -qxF "$SENT_MAIN_CLOSE" "$EXTRACT_MAIN" 2>/dev/null ||
    cannot_look "scripts/setup.sh opens the local-main fence with \`${SENT_MAIN_OPEN}\` and never closes it with \`${SENT_MAIN_CLOSE}\`. The extraction ran to the end of the file."
grep -q '^ensure_local_main() {' "$EXTRACT_MAIN" ||
    cannot_look "the local-main fence in scripts/setup.sh defines no ensure_local_main — the step this drive exists for is not inside its own sentinels."

# shellcheck source=/dev/null
. "$EXTRACT_MAIN"
command -v ensure_local_main >/dev/null 2>&1 ||
    cannot_look "sourcing the extracted local-main fence defined no ensure_local_main"

# --- THE FOURTH FENCE: the step wall ------------------------------------------
#
# `step`, `step_end` and `setup_total` — the clock. Extracted for
# the same reason as the rest: the timing case drives the WRAPPER over two
# planted no-op steps, and running the whole of `setup.sh` to see two elapsed
# lines would need docker, a venv and an identity provider.
SENT_WALL_OPEN="# >>> step-wall >>>"
SENT_WALL_CLOSE="# <<< step-wall <<<"
EXTRACT_WALL="${WORK}/step_wall.sh"

sed -n "/^${SENT_WALL_OPEN}\$/,/^${SENT_WALL_CLOSE}\$/p" scripts/setup.sh >"$EXTRACT_WALL" 2>/dev/null || true

grep -qxF "$SENT_WALL_OPEN" "$EXTRACT_WALL" 2>/dev/null ||
    cannot_look "scripts/setup.sh has no line reading exactly \`${SENT_WALL_OPEN}\` — the step-wall fence is gone (or was never there, which is what a baseline tree looks like). The timing case below sources the text between that sentinel and \`${SENT_WALL_CLOSE}\`, so there is no wrapper to drive."
grep -qxF "$SENT_WALL_CLOSE" "$EXTRACT_WALL" 2>/dev/null ||
    cannot_look "scripts/setup.sh opens the step-wall fence with \`${SENT_WALL_OPEN}\` and never closes it with \`${SENT_WALL_CLOSE}\`. The extraction ran to the end of the file."
grep -q '^setup_total() {' "$EXTRACT_WALL" ||
    cannot_look "the step-wall fence in scripts/setup.sh defines no setup_total — the run has no total for this drive to assert."

# NOT SOURCED HERE. It defines `step`, which this drive has no use for, and sets
# a RUN_START at source time that would make every total below the age of the
# drive rather than the age of the run. The timing case sources it inside its
# own subshell, which is also the only place its output can be captured whole.

# --- THE CONTROL'S SUBJECT: the refusal a tag clone hits without the step ------
#
# The three real files, sourced from THIS checkout the way `test_loop_scope.sh`
# sources them, and called with the cwd moved into a scratch clone. Nothing here
# copies the refusal's text: the control asserts the SHIPPED derivation refuses,
# so a rung that softened `loop_tier.sh` would take this case with it.
[ -f scripts/gate_refuse.sh ] || cannot_look "scripts/gate_refuse.sh is not in this tree — the loop-scope control cannot read a refusal"
[ -f scripts/secrets_scan.sh ] || cannot_look "scripts/secrets_scan.sh is not in this tree — the loop-scope control has no changed-file derivation"
[ -f scripts/loop_tier.sh ] || cannot_look "scripts/loop_tier.sh is not in this tree — the refusal this step exists to close the trap in front of is gone"
# shellcheck source=scripts/gate_refuse.sh
. scripts/gate_refuse.sh
# shellcheck source=scripts/secrets_scan.sh
. scripts/secrets_scan.sh
# shellcheck source=scripts/loop_tier.sh
. scripts/loop_tier.sh
command -v loop_tier_own_apps >/dev/null 2>&1 ||
    cannot_look "scripts/loop_tier.sh defines no loop_tier_own_apps — the control has nothing to run"

# --- the assertions -----------------------------------------------------------
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

exits() {
    if [ "$RC" -eq "$1" ]; then
        ok "exit ${RC}"
    else
        bad "wanted exit $1, got ${RC}"
    fi
}

says() {
    if grep -qF -- "$1" "$OUT"; then
        ok "says \"$1\""
    else
        bad "does not say \"$1\""
    fi
}

files_match() {
    # $1 what · $2 got · $3 wanted
    if cmp -s "$2" "$3"; then
        ok "$1 is byte-identical"
    else
        bad "$1 differs — diff (got | wanted) follows"
        diff "$2" "$3" | sed 's/^/             | /' | head -40 || true
    fi
}

file_has_line() {
    # $1 file · $2 the exact line
    if grep -qxF -- "$2" "$1"; then
        ok "${1##*/} carries the line \"$2\""
    else
        bad "${1##*/} does not carry the line \"$2\""
    fi
}

# --- the scratch world --------------------------------------------------------
#
# One directory per case, so a case can never read another's leftovers, and each
# one PRINTS what it planted: a fixture nobody saw arrive is a fixture that may
# not have arrived.
CASE_DIR=""
new_case_dir() {
    N=$((N + 1))
    CASE_DIR="${WORK}/case${N}"
    drive_require_scratch CASE_DIR "${CASE_DIR:-}"
    mkdir -p "$CASE_DIR"
}

plant() {
    # $1 filename (relative to CASE_DIR) · remaining args: the lines
    local name="$1"
    shift
    if [ "$#" -eq 0 ]; then
        : >"${CASE_DIR}/${name}"
    else
        printf '%s\n' "$@" >"${CASE_DIR}/${name}"
    fi
    echo "           planted ${CASE_DIR##*/}/${name} — $(wc -l <"${CASE_DIR}/${name}" | tr -d ' ') line(s)"
}

run_sync() {
    CURRENT="$1"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    local here="$PWD"
    cd "$CASE_DIR"
    RC=0
    env_sync_from_example >"$OUT" 2>&1 || RC=$?
    cd "$here"
    echo "           block:"
    sed 's/^/             > /' "$OUT"
}

# THE FIXTURE the criteria name: an example of six lines — three keys, two
# comments and one blank — and an environment holding two of those keys, one of
# them with a different value, plus one key the example does not have, in a
# different order.
plant_the_fixture() {
    new_case_dir
    plant .env.example \
        '# the first key' \
        'ALPHA=one' \
        'BETA=two' \
        '' \
        '# the third key' \
        'GAMMA=three'
    plant .env \
        'GAMMA=three' \
        'DELTA=kept-value' \
        'ALPHA=changed'
}

# THE EXPECTED RESULT, written out in full rather than computed: a drive that
# builds its expectation with the same rules as the code under it agrees with
# that code by construction and proves nothing.
plant_the_expectation() {
    printf '%s\n' \
        '# the first key' \
        'ALPHA=changed' \
        'BETA=two' \
        '' \
        '# the third key' \
        'GAMMA=three' \
        '' \
        '# --- kept from a previous .env: not in .env.example ---' \
        'DELTA=kept-value' >"${WORK}/expected.env"
}

case_the_result_is_the_example_with_the_values_carried_over() {
    plant_the_fixture
    plant_the_expectation
    cp "${CASE_DIR}/.env" "${WORK}/original.env"
    run_sync "a drifted .env is regenerated"
    exits 0
    files_match ".env" "${CASE_DIR}/.env" "${WORK}/expected.env"
}

case_the_changed_value_sits_at_the_examples_position() {
    # Line 2 of the example is ALPHA; line 2 of the result must be ALPHA with
    # the file's value. Asserted as a POSITION, because "the value survived
    # somewhere" is what an append-the-missing-keys shape would also satisfy,
    # and that shape is exactly what does not hit the digest.
    CURRENT="the carried value keeps the example's position"
    local got
    got="$(sed -n '2p' "${CASE_DIR}/.env")"
    if [ "$got" = "ALPHA=changed" ]; then
        ok "line 2 is the example's ALPHA line carrying the file's value"
    else
        bad "line 2 is \"${got}\" and should be the example's ALPHA line"
    fi
}

case_the_extra_key_sits_after_the_marker() {
    CURRENT="a key the example lacks is kept under the marker"
    local marker_line delta_line
    marker_line="$(grep -nxF '# --- kept from a previous .env: not in .env.example ---' "${CASE_DIR}/.env" | cut -d: -f1 || true)"
    delta_line="$(grep -nxF 'DELTA=kept-value' "${CASE_DIR}/.env" | cut -d: -f1 || true)"
    if [ -n "$marker_line" ] && [ -n "$delta_line" ] && [ "$delta_line" -gt "$marker_line" ]; then
        ok "the marker is at line ${marker_line} and the kept key at ${delta_line}"
    else
        bad "marker at \"${marker_line:-none}\", kept key at \"${delta_line:-none}\""
    fi
}

case_the_block_counts_one_added_one_preserved_one_kept() {
    CURRENT="the report block counts what it did"
    says "1 key(s) added from .env.example: BETA"
    says "1 value(s) preserved in place: ALPHA"
    says "1 key(s) not in .env.example kept at the end: DELTA"
    says ".env.previous written"
}

case_the_block_never_prints_a_value() {
    # The criterion, and the reason it is a criterion: the first key a real
    # `.env` carries here is a machine credential, and this block goes into
    # terminals, logs and pasted reports. Any `=` at all is a leak — there is no
    # legitimate `=` in a block that prints names and counts.
    CURRENT="the report block prints names, never values"
    if grep -q '=' "$OUT"; then
        bad "the block contains an \"=\" — a value reached stdout"
        sed 's/^/             | /' "$OUT"
    else
        ok "no \"=\" anywhere in the block"
    fi
}

case_the_previous_file_is_the_original() {
    CURRENT=".env.previous is the file that was there before"
    files_match ".env.previous" "${CASE_DIR}/.env.previous" "${WORK}/original.env"
    local mode
    mode="$(ls -l "${CASE_DIR}/.env.previous" 2>/dev/null | cut -c1-10 || true)"
    if [ "$mode" = "-rw-------" ]; then
        ok "mode is owner-only (${mode})"
    else
        bad "mode is ${mode} and should be -rw------- : that file is a whole copy of the environment"
    fi
}

case_a_second_run_changes_nothing_and_says_so() {
    cp "${CASE_DIR}/.env" "${WORK}/after-first-run.env"
    run_sync "a second run on the result"
    exits 0
    files_match ".env after a second run" "${CASE_DIR}/.env" "${WORK}/after-first-run.env"
    files_match ".env.previous after a second run" "${CASE_DIR}/.env.previous" "${CASE_DIR}/.env"
    says ".env already matches .env.example's shape — nothing to do"
}

case_a_value_holding_an_equals_or_a_hash_survives() {
    # The two shapes a key/value split gets wrong, and both are ordinary in a
    # real `.env`: a URL with a query string, and a value with a `#` in it that
    # a comment-stripper would truncate.
    new_case_dir
    # The example carries a comment the environment does not, so the file is
    # genuinely rewritten here rather than found already correct — otherwise
    # this case would assert three lines that were never re-emitted.
    plant .env.example \
        '# the doors' \
        'URL=https://example.invalid/x' \
        'NOTE=plain' \
        'PLAIN=same'
    plant .env \
        'URL=https://example.invalid/x?a=b&c=d' \
        'NOTE=has # a hash and = an equals' \
        'PLAIN=same'
    run_sync "values carrying = and #"
    exits 0
    file_has_line "${CASE_DIR}/.env" 'URL=https://example.invalid/x?a=b&c=d'
    file_has_line "${CASE_DIR}/.env" 'NOTE=has # a hash and = an equals'
    file_has_line "${CASE_DIR}/.env" 'PLAIN=same'
    CURRENT="values carrying = and #"
    if [ "$(wc -l <"${CASE_DIR}/.env" | tr -d ' ')" = "4" ]; then
        ok "the result is the example's four lines and nothing appended"
    else
        bad "the result has $(wc -l <"${CASE_DIR}/.env" | tr -d ' ') lines, wanted 4"
    fi
}

case_no_env_at_all_copies_the_example() {
    new_case_dir
    plant .env.example \
        '# a comment' \
        'ALPHA=one' \
        'BETA=two'
    run_sync "a checkout with no .env"
    exits 0
    files_match ".env" "${CASE_DIR}/.env" "${CASE_DIR}/.env.example"
    says "0 value(s) preserved in place"
    says ".env.previous not written"
    CURRENT="a checkout with no .env"
    if [ -e "${CASE_DIR}/.env.previous" ]; then
        bad ".env.previous exists and there was no previous file to keep"
    else
        ok "no .env.previous, and the block says so rather than staying silent"
    fi
}

case_no_example_is_a_refusal_that_touches_nothing() {
    new_case_dir
    plant .env \
        'ALPHA=mine' \
        'BETA=also-mine'
    cp "${CASE_DIR}/.env" "${WORK}/untouched.env"
    run_sync "a checkout with no .env.example"
    exits 1
    says ".env.example"
    says "was not written and was not touched"
    files_match ".env" "${CASE_DIR}/.env" "${WORK}/untouched.env"
    CURRENT="a checkout with no .env.example"
    if [ -e "${CASE_DIR}/.env.previous" ]; then
        bad ".env.previous was written by a run that refused"
    else
        ok "nothing was written"
    fi
}

# --- the two states the function's own header argues about --------------------
#
# Both of these are ARGUED in the fence's header and neither was driven: the
# header is the only thing standing behind them, and a header is not an
# instrument. They are the mirror of the cases above — same fixtures, the two
# inputs the awk is shaped around rather than the ones a happy path produces.

case_an_empty_env_is_a_truncated_file_and_not_an_empty_environment() {
    # `env_sync_classify` keys its first-file test on `FILENAME == envfile`
    # rather than the usual `FNR == NR`, and the header says why in as many
    # words: an EMPTY first file yields no records, so `FNR == NR` would be true
    # for the SECOND file's first line and the example would be read as the
    # environment — silently classifying every key as "kept" and rebuilding the
    # file with the whole example appended under the marker. A zero-byte `.env`
    # is a real state here (a killed write, a truncating redirect), so the
    # outcome the header argues for is asserted: every key ADDED, none kept, the
    # result the example's own bytes, and the empty file still kept beside it.
    new_case_dir
    plant .env.example \
        '# the doors' \
        'ALPHA=one' \
        'BETA=two' \
        '' \
        'GAMMA=three'
    plant .env
    CURRENT="the planted .env is zero bytes"
    if [ ! -s "${CASE_DIR}/.env" ] && [ -f "${CASE_DIR}/.env" ]; then
        ok "the fixture is a file of 0 bytes, not an absent file"
    else
        bad "the fixture is not a zero-byte file — this case would drive the no-.env path instead"
    fi
    run_sync "a truncated .env of zero bytes"
    exits 0
    files_match ".env" "${CASE_DIR}/.env" "${CASE_DIR}/.env.example"
    says "3 key(s) added from .env.example: ALPHA BETA GAMMA"
    says "0 value(s) preserved in place"
    says "0 key(s) not in .env.example kept at the end"
    says ".env.previous written"
    CURRENT="a truncated .env of zero bytes"
    if grep -qxF '# --- kept from a previous .env: not in .env.example ---' "${CASE_DIR}/.env"; then
        bad "the marker is in the result — the example was read as the environment"
    else
        ok "no kept-block marker: the example was not mistaken for the environment"
    fi
    # NOTHING IS LOST: the truncated file is still the file `.env.previous`
    # holds, so the one step of reversibility the fence promises survives the
    # state where there was nothing to reverse to.
    if [ -f "${CASE_DIR}/.env.previous" ] && [ ! -s "${CASE_DIR}/.env.previous" ]; then
        ok ".env.previous is the zero-byte original, kept rather than skipped"
    else
        bad ".env.previous is missing or is not the zero-byte original"
    fi
    # NOTHING BY VALUE: the block names three keys and counts them, and the
    # empty-file path must not become the one place a value reaches stdout.
    if grep -q '=' "$OUT"; then
        bad "the block contains an \"=\" — a value reached stdout"
        sed 's/^/             | /' "$OUT"
    else
        ok "no \"=\" anywhere in the block"
    fi
}

case_the_pinned_marker_survives_the_rebuild() {
    # THE ONE COMMENT THE REBUILD CARRIES. `# pinned` directly above the
    # operative DATABASE_NAME line says a human meant that name, and setup.sh's
    # pin block — run after this step — keeps a marked pin and overrides an
    # unmarked one. The rebuild used to drop it with the rest of the old prose,
    # and the pin block then overwrote the very name it was marked to keep.
    local above count
    new_case_dir
    plant .env.example \
        '# the database' \
        'DATABASE_URL=' \
        'DATABASE_NAME=' \
        'OTHER=1'
    plant .env \
        'OTHER=1' \
        '# pinned — the owner said so' \
        'DATABASE_NAME=djb_x'
    run_sync "a # pinned marker above DATABASE_NAME, at the example's position"
    exits 0
    CURRENT="a # pinned marker above DATABASE_NAME, at the example's position"
    above="$(awk '/^DATABASE_NAME=djb_x$/ { print prev; exit } { prev = $0 }' "${CASE_DIR}/.env")"
    if [ "$above" = "# pinned — the owner said so" ]; then
        ok "the marker line, verbatim, sits directly above DATABASE_NAME=djb_x"
    else
        bad "the line above DATABASE_NAME=djb_x is \"${above}\" — the rebuild dropped the # pinned marker"
    fi
    count="$(grep -c 'pinned' "${CASE_DIR}/.env" || true)"
    if [ "$count" = "1" ]; then
        ok "the marker appears exactly once"
    else
        bad "the marker appears ${count} time(s), wanted 1"
    fi

    # THE KEPT-AT-END BLOCK, for an example that does not name DATABASE_NAME.
    new_case_dir
    plant .env.example \
        'OTHER=1'
    plant .env \
        '# pinned' \
        'DATABASE_NAME=djb_y' \
        'OTHER=1'
    run_sync "a # pinned marker above DATABASE_NAME, in the kept-at-end block"
    exits 0
    CURRENT="a # pinned marker above DATABASE_NAME, in the kept-at-end block"
    above="$(awk '/^DATABASE_NAME=djb_y$/ { print prev; exit } { prev = $0 }' "${CASE_DIR}/.env")"
    if [ "$above" = "# pinned" ]; then
        ok "the marker sits directly above DATABASE_NAME=djb_y in the kept block"
    else
        bad "the line above DATABASE_NAME=djb_y is \"${above}\""
    fi

    # AND ONLY WHERE IT MARKS: a `# pinned` that is not directly above the
    # operative line marks nothing and is prose, dropped as before.
    new_case_dir
    plant .env.example \
        'DATABASE_NAME=' \
        'OTHER=1'
    plant .env \
        '# pinned' \
        'OTHER=2' \
        'DATABASE_NAME=djb_z'
    run_sync "a # pinned line that is not above DATABASE_NAME"
    exits 0
    CURRENT="a # pinned line that is not above DATABASE_NAME"
    if grep -q 'pinned' "${CASE_DIR}/.env"; then
        bad "a marker that marked nothing was carried"
    else
        ok "a # pinned that marks no DATABASE_NAME line is dropped with the prose"
    fi
}

case_a_key_present_twice_collapses_to_its_last_value() {
    # The header declares dotenv's own last-wins rule, applied where the file is
    # REBUILT rather than read: a key the file carries twice collapses to its
    # last value, ONCE, at the example's position. Every half of that is a way
    # to be wrong — first-wins, both lines emitted, or the duplicate demoted to
    # the kept block — and all three still look like a working sync.
    new_case_dir
    plant .env.example \
        '# the doors' \
        'ALPHA=one' \
        'BETA=two'
    plant .env \
        'ALPHA=first' \
        'BETA=two' \
        'ALPHA=last'
    run_sync "a key present twice with two values"
    exits 0
    says "1 value(s) preserved in place: ALPHA"
    says "0 key(s) added from .env.example"
    says "0 key(s) not in .env.example kept at the end"
    CURRENT="a key present twice with two values"
    local got count
    got="$(sed -n '2p' "${CASE_DIR}/.env")"
    if [ "$got" = "ALPHA=last" ]; then
        ok "line 2 is the example's ALPHA line carrying the LAST value"
    else
        bad "line 2 is \"${got}\" and should be ALPHA=last"
    fi
    count="$(grep -c '^ALPHA=' "${CASE_DIR}/.env" || true)"
    if [ "$count" = "1" ]; then
        ok "ALPHA appears exactly once in the result"
    else
        bad "ALPHA appears ${count} time(s) in the result, wanted 1"
    fi
    if grep -qxF 'ALPHA=first' "${CASE_DIR}/.env"; then
        bad "the first value survived — the rule is last-wins, not first-wins"
    else
        ok "the first value is gone"
    fi
    if [ "$(wc -l <"${CASE_DIR}/.env" | tr -d ' ')" = "3" ]; then
        ok "the result is the example's three lines and nothing appended"
    else
        bad "the result has $(wc -l <"${CASE_DIR}/.env" | tr -d ' ') lines, wanted 3"
    fi
}

# --- the digest ---------------------------------------------------------------
#
# A MODEL OF `loop_env_fingerprint`'s env-file component, not the function
# itself: the same drop-by-key `awk` and the same SHA-256 over its output. The
# case below it anchors the model against the shipped text, so a rewritten rule
# is at least visible here rather than silently modelled by the old one.
env_file_digest() {
    # $1 file · $2 newline-separated keys to drop
    DJB_LOOP_ENV_KEYS="$2" awk '
        BEGIN {
            n = split(ENVIRON["DJB_LOOP_ENV_KEYS"], k, "\n")
            for (i = 1; i <= n; i++) if (k[i] != "") drop[k[i]] = 1
        }
        {
            line = $0
            name = line
            sub(/=.*$/, "", name)
            gsub(/[ \t]/, "", name)
            if (name in drop) next
            print line
        }
    ' "$1" | digest_stdin
}

# THE TWO SPELLINGS, RESOLVED HERE RATHER THAN BORROWED. `shasum -a 256` is
# macOS's and `sha256sum` is a minimal Linux's, and this drive has to run on
# both — but it must not call the shipped `sha256_of`, because a model that
# borrows the implementation it is modelling asserts nothing.
digest_stdin() {
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 | awk '{print $1}'
    else
        sha256sum | awk '{print $1}'
    fi
}

case_the_digest_agrees_when_the_files_agree() {
    CURRENT="the env-file digest over a regenerated file and its own clone"
    new_case_dir
    plant .env.example \
        '# the identity carry' \
        'ZITADEL_PAT=' \
        'DATABASE_NAME=djb_example' \
        '' \
        'ALPHA=one'
    plant .env \
        'ALPHA=one' \
        'ZITADEL_PAT=a-machine-credential' \
        'DATABASE_NAME=djb_the_builders_own'
    run_sync "the builder's file regenerated"
    exits 0

    # (b) the CLONE: the example with the same two lines substituted in place —
    # which is exactly what `verify_start.sh` writes.
    printf '%s\n' \
        '# the identity carry' \
        'ZITADEL_PAT=a-machine-credential' \
        'DATABASE_NAME=djb_the_clones_own' \
        '' \
        'ALPHA=one' >"${WORK}/clone.env"

    local a b c
    a="$(env_file_digest "${CASE_DIR}/.env" 'DATABASE_NAME')"
    b="$(env_file_digest "${WORK}/clone.env" 'DATABASE_NAME')"
    CURRENT="the env-file digest over a regenerated file and its own clone"
    if [ "$a" = "$b" ]; then
        ok "the builder's regenerated file and the clone's digest to the same value"
    else
        bad "the two digests differ — the regeneration does not produce the clone's skeleton"
        diff "${CASE_DIR}/.env" "${WORK}/clone.env" | sed 's/^/             | /' || true
    fi

    # (c) THE HONEST MISS: one key the example does not have. It is kept, it
    # changes the file, and the digest must SEE it — a digest that agreed here
    # would be a digest that had stopped reading the file.
    cp "${WORK}/clone.env" "${WORK}/clone-plus.env"
    printf '\n%s\n%s\n' '# --- kept from a previous .env: not in .env.example ---' 'MINE=set-by-hand' >>"${WORK}/clone-plus.env"
    c="$(env_file_digest "${WORK}/clone-plus.env" 'DATABASE_NAME')"
    CURRENT="the env-file digest over a file carrying a kept key"
    if [ "$c" != "$b" ]; then
        ok "a kept key the example lacks is a DIFFERENT digest — an honest, permanent miss until the example grows the key"
    else
        bad "a file with an extra key digests the same as one without it"
    fi
}

case_the_digest_model_still_matches_the_shipped_digest() {
    CURRENT="the digest model is anchored against gate_ledger.sh"
    local missing=""
    grep -qF 'if (name in drop) next' scripts/gate_ledger.sh || missing="${missing} the drop-by-key line"
    grep -qF 'sub(/=.*$/, "", name)' scripts/gate_ledger.sh || missing="${missing} the key split"
    # THE DIGEST IS NAMED, NOT SPELLED, and that is the change this anchor
    # records: the shipped line pipes into `sha256_of`, which resolves the
    # machine's own tool. An anchor on `shasum -a 256` was an anchor on one
    # machine's spelling, and it held while the gate could not key its own
    # verdict on a Linux box.
    grep -qF '| sha256_of' scripts/gate_ledger.sh || missing="${missing} the pipe into sha256_of"
    grep -qE '^sha256_of\(\)' scripts/gate_refuse.sh || missing="${missing} sha256_of's definition in gate_refuse.sh"
    if [ -z "$missing" ]; then
        ok "gate_ledger.sh still splits the key, drops the declared ones and hashes through sha256_of"
    else
        bad "the shipped digest no longer carries:${missing} — the model above is stale and the agreement case proves less than it claims"
    fi
}

# --- the services step: a pull failure is a refusal ---------------------------
#
# THE SHIM IS THE POINT. A registry that has stopped serving a pinned tag cannot
# be arranged on the box running this drive, and a case that waited for one
# would be could-not-look on every machine. So `docker` is a script first on
# PATH that RECORDS every invocation in order — the log IS the sequence, which
# is what lets a case assert that `up` never ran after a failed pull — and
# answers by knob. The shape is `deploy/tests/test_release.sh`'s stub docker.
DOCKER_LOG=""

plant_the_shim() {
    mkdir -p "${CASE_DIR}/bin"
    cat >"${CASE_DIR}/bin/docker" <<'DOCKER'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$DJB_DRIVE_DOCKER_LOG"
case "$*" in
*"compose ps"*)
    printf '%s\n' "${DJB_DRIVE_HEALTH:-}"
    ;;
*"compose config --images"*)
    # What `docker compose config --images` answers: one fully-resolved image
    # reference per line, read here out of the scratch compose file the case
    # wrote rather than invented, so the census names what the case pinned.
    sed -n 's/^ *image: *//p' "$DJB_DRIVE_COMPOSE"
    ;;
*"compose pull"*)
    if [ "${DJB_DRIVE_PULL_RC:-0}" -ne 0 ]; then
        echo "${DJB_DRIVE_PLANTED_REF} Pulling"
        echo "Error response from daemon: manifest for ${DJB_DRIVE_PLANTED_REF} not found: manifest unknown" >&2
        exit "${DJB_DRIVE_PULL_RC}"
    fi
    echo "${DJB_DRIVE_PLANTED_REF} Pulled"
    ;;
esac
exit 0
DOCKER
    chmod +x "${CASE_DIR}/bin/docker"
    echo "           planted ${CASE_DIR##*/}/bin/docker — the shim, first on PATH"
}

MINIO_PINNED_REF="public.ecr.aws/w9i8o4b2/minio:RELEASE.2025-09-07T16-13-09Z@sha256:9966a92a734f9411e32f4f41d7d9d826fcdc0f68c4e20b70295bd4e7c11f8a2f"

plant_the_scratch_compose() {
    # $1 the minio reference this case pins. Two services, because a census that
    # only ever sees one line cannot show that it names each one's registry.
    plant compose.yaml \
        'services:' \
        '  db:' \
        '    image: postgres:17' \
        '  minio:' \
        "    image: $1"
}

run_services() {
    # $1 the case name · $2 the health the shim reports · $3 the pull rc ·
    # $4 the reference the shim names when it fails
    CURRENT="$1"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    DOCKER_LOG="${CASE_DIR}/docker.log"
    : >"$DOCKER_LOG"
    RC=0
    (
        export PATH="${CASE_DIR}/bin:$PATH"
        export DJB_DRIVE_DOCKER_LOG="$DOCKER_LOG"
        export DJB_DRIVE_COMPOSE="${CASE_DIR}/compose.yaml"
        export DJB_DRIVE_HEALTH="$2"
        export DJB_DRIVE_PULL_RC="$3"
        export DJB_DRIVE_PLANTED_REF="$4"
        services_up
    ) >"$OUT" 2>&1 || RC=$?
    echo "           output:"
    sed 's/^/             > /' "$OUT"
    echo "           every docker invocation, in order:"
    sed 's/^/             $ docker /' "$DOCKER_LOG"
}

log_says() {
    if grep -qF -- "$1" "$DOCKER_LOG"; then
        ok "docker was invoked with \"$1\""
    else
        bad "no docker invocation carries \"$1\""
    fi
}

log_never_says() {
    if grep -qF -- "$1" "$DOCKER_LOG"; then
        bad "docker WAS invoked with \"$1\" — and this case exists to prove it was not"
        sed 's/^/             $ docker /' "$DOCKER_LOG"
    else
        ok "docker was never invoked with \"$1\""
    fi
}

says_not() {
    if grep -qF -- "$1" "$OUT"; then
        bad "says \"$1\" and must not"
    else
        ok "never says \"$1\""
    fi
}

case_a_pull_failure_is_could_not_look_naming_the_image() {
    new_case_dir
    plant_the_scratch_compose 'example/files-store:RELEASE.9999-01-01T00-00-00Z'
    plant_the_shim
    run_services "a pull that fails is a refusal, not a start" \
        "" 1 "example/files-store:RELEASE.9999-01-01T00-00-00Z"
    exits 2
    says "COULD NOT LOOK"
    says "example/files-store:RELEASE.9999-01-01T00-00-00Z"
    # The registry host, derived rather than spelled: `example/files-store` has
    # no host segment, so it is Docker Hub — which is the whole of the finding.
    says "(registry docker.io)"
    says "NOTHING WAS STARTED"
    log_says "compose pull"
    log_never_says "compose up"
    says_not "wait_healthy ENTERED"
}

case_a_healthy_stack_is_reused_without_a_pull() {
    new_case_dir
    plant_the_scratch_compose 'public.ecr.aws/w9i8o4b2/minio:RELEASE.2025-09-07T16-13-09Z@sha256:9966a92a734f9411e32f4f41d7d9d826fcdc0f68c4e20b70295bd4e7c11f8a2f'
    plant_the_shim
    run_services "a healthy stack is reused and nothing is fetched" \
        "healthy" 0 "public.ecr.aws/w9i8o4b2/minio:RELEASE.2025-09-07T16-13-09Z@sha256:9966a92a734f9411e32f4f41d7d9d826fcdc0f68c4e20b70295bd4e7c11f8a2f"
    exits 0
    says "reusing running stack"
    log_never_says "compose pull"
    log_never_says "compose up"
    says_not "wait_healthy ENTERED"
}

case_a_clean_pull_starts_the_stack_and_then_waits() {
    # The ordinary path, which is the one nobody would notice breaking: pull,
    # then up, then wait — in that order, with the order asserted rather than
    # assumed from the fact that all three happened.
    new_case_dir
    plant_the_scratch_compose 'public.ecr.aws/w9i8o4b2/minio:RELEASE.2025-09-07T16-13-09Z@sha256:9966a92a734f9411e32f4f41d7d9d826fcdc0f68c4e20b70295bd4e7c11f8a2f'
    plant_the_shim
    run_services "a clean pull starts the stack and waits for it" \
        "" 0 "public.ecr.aws/w9i8o4b2/minio:RELEASE.2025-09-07T16-13-09Z@sha256:9966a92a734f9411e32f4f41d7d9d826fcdc0f68c4e20b70295bd4e7c11f8a2f"
    exits 0
    log_says "compose pull"
    log_says "compose up -d"
    says "wait_healthy ENTERED for db"
    says "wait_healthy ENTERED for minio"
    says_not "COULD NOT LOOK"
    local pull_at up_at
    pull_at="$(grep -nF 'compose pull' "$DOCKER_LOG" | sed -n '1s/:.*//p' || true)"
    up_at="$(grep -nF 'compose up' "$DOCKER_LOG" | sed -n '1s/:.*//p' || true)"
    if [ -n "$pull_at" ] && [ -n "$up_at" ] && [ "$pull_at" -lt "$up_at" ]; then
        ok "the pull is invocation ${pull_at} and the up is ${up_at} — the pull comes first"
    else
        bad "pull at \"${pull_at:-none}\", up at \"${up_at:-none}\" — the pull does not precede the up"
    fi
}

case_a_reference_names_its_registry_the_way_docker_reads_one() {
    # The refusal's census is only worth reading if the host it prints is the
    # host docker would use. Docker's rule: the first path segment is a registry
    # only when it carries a dot or a colon, or is exactly `localhost`.
    CURRENT="image_registry_host reads a reference the way docker does"
    local ref want got
    while IFS='|' read -r ref want; do
        [ -n "$ref" ] || continue
        got="$(image_registry_host "$ref")"
        if [ "$got" = "$want" ]; then
            ok "${ref} → ${got}"
        else
            bad "${ref} → ${got}, wanted ${want}"
        fi
    done <<'REFS'
example/files-store:1|docker.io
quay.io/example/thing:1|quay.io
public.ecr.aws/w9i8o4b2/minio:RELEASE.2025-09-07T16-13-09Z@sha256:9966a92a734f9411e32f4f41d7d9d826fcdc0f68c4e20b70295bd4e7c11f8a2f|public.ecr.aws
ghcr.io/zitadel/zitadel:v4.17.1|ghcr.io
localhost:5000/thing:1|localhost:5000
postgres:17|docker.io
REFS
}

case_the_minio_pin_names_the_registry_that_serves_it() {
    # The pin itself, as a text census over compose.yaml: one minio image line,
    # and it names the owner's ECR Public mirror BY DIGEST. MinIO withdrew every
    # public image on 2026-09-24; a tag on a mirror can be re-pushed, a digest
    # cannot, so the digest is what keeps this the release the tree always ran.
    CURRENT="compose.yaml's minio pin"
    local lines count block
    lines="$(grep -n 'image: .*minio' compose.yaml || true)"
    count="$(printf '%s\n' "$lines" | grep -c 'image:' || true)"
    if [ "$count" -eq 1 ]; then
        ok "exactly one minio image line: ${lines}"
    else
        bad "wanted exactly one minio image line, found ${count}: ${lines}"
    fi
    # NO PIPELINE HERE, and that is the point rather than a style choice: the
    # earlier shape was `printf … | grep -qF …`, a reader that short-circuits its
    # own producer at the tail of a pipeline under `pipefail` — over 64 KiB the
    # producer takes SIGPIPE and the pipeline's status is the wrong answer, every
    # run. `$lines` is already a shell string, so the membership test needs no
    # process at all.
    case "$lines" in
    *"${MINIO_PINNED_REF}"*)
        ok "it names the ECR Public mirror, the release this tree always pinned, by digest"
        ;;
    *)
        bad "it does not name ${MINIO_PINNED_REF}"
        ;;
    esac
    # The mirror holds ONE architecture, so the service says which rather than
    # leaving the daemon to infer it from a single-arch manifest.
    block="$(sed -n '/^  minio:$/,/^  [a-z]/p' compose.yaml)"
    case "$block" in
    *$'\n'"    platform: linux/arm64"$'\n'*)
        ok "the minio service states platform: linux/arm64"
        ;;
    *)
        bad "the minio service carries no \`platform: linux/arm64\` line"
        ;;
    esac
    if grep -qF 'newest release published to' compose.yaml; then
        bad "the comment still claims a Docker Hub provenance the pin no longer has"
    else
        ok "the comment beside the pin no longer claims the tag comes from Docker Hub"
    fi
}

# --- the CI half of the pin -----------------------------------------------------
#
# The mirror is linux/arm64 only and CI's runners are amd64, so every CI job that
# starts the compose stack must register the arm64 QEMU handler first. And ECR
# Public rations ANONYMOUS pulls by data: a full matrix (about sixteen shards
# pulling about 170 MB each) answered `toomanyrequests: Data limit exceeded` on
# the first consumer that measured it. So every such job logs in to the registry
# the pin names before its pull, with an OIDC role assumed in us-east-1 (ECR
# Public's API lives in that region only). One reader, pointed at this tree's
# workflow and at a planted copy with the login removed, so "no job logs in" is
# told apart from "the reader sees no login".
compose_up_jobs_census() {
    # $1 the workflow file. Prints one line per compose-up job and a total.
    "$ROOT/.venv/bin/python" - "$1" compose.yaml <<'PYTHON'
import re
import sys

import yaml

wf = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
compose = yaml.safe_load(open(sys.argv[2], encoding="utf-8"))
host = compose["services"]["minio"]["image"].split("/", 1)[0]
jobs = 0
for name, job in (wf.get("jobs") or {}).items():
    steps = job.get("steps") or []
    up = next(
        (i for i, s in enumerate(steps) if re.search(r"docker compose\b[^\n]*\bup\b", str(s.get("run", "")))),
        None,
    )
    if up is None:
        continue
    jobs += 1
    before = steps[:up]

    def uses(step, prefix):
        # A step counts only when it can run: no `if:`, or exactly the one guard
        # the workflow uses (no role variable -> anonymous, like the images job).
        # `if: false`, or any other condition, does not count.
        guard = step.get("if", None)
        runs = "if" not in step or guard == "vars.AWS_ECR_ROLE_ARN != ''"
        return runs and str(step.get("uses", "")).startswith(prefix)

    qemu = any(uses(s, "docker/setup-qemu-action@") and "arm64" in str((s.get("with") or {}).get("platforms", "")) for s in before)
    assume = next(
        (
            i
            for i, s in enumerate(before)
            if uses(s, "aws-actions/configure-aws-credentials@")
            and (s.get("with") or {}).get("aws-region") == "us-east-1"
            and "vars.AWS_ECR_ROLE_ARN" in str((s.get("with") or {}).get("role-to-assume", ""))
        ),
        None,
    )
    login = next(
        (
            i
            for i, s in enumerate(before)
            if host == "public.ecr.aws"
            and uses(s, "aws-actions/amazon-ecr-login@")
            and (s.get("with") or {}).get("registry-type") == "public"
        ),
        None,
    )
    perms = job.get("permissions", wf.get("permissions")) or {}
    oidc = isinstance(perms, dict) and perms.get("id-token") == "write"
    logged = login is not None and assume is not None and assume < login and oidc
    print(f"job {name}: qemu-arm64-before-up={'yes' if qemu else 'no'} logged-in-before-up={'yes' if logged else 'no'}")
print(f"host={host}")
print(f"compose-up-jobs={jobs}")
PYTHON
}

case_every_compose_up_job_runs_arm64_and_logs_in_before_the_pull() {
    CURRENT="every CI job that starts the stack can pull and run the minio mirror"
    [ -x "$ROOT/.venv/bin/python" ] || cannot_look "no venv interpreter at $ROOT/.venv/bin/python — the workflow reader cannot run"
    local out="${WORK}/compose-up-jobs.txt" plant="${WORK}/ci-without-login.yml" n
    if ! compose_up_jobs_census .github/workflows/ci.yml >"$out" 2>&1; then
        bad "the reader could not read .github/workflows/ci.yml and compose.yaml: $(tr '\n' ' ' <"$out")"
        return
    fi
    sed 's/^/             | /' "$out"
    n="$(sed -n 's/^compose-up-jobs=//p' "$out")"
    # THE FLOOR, BY NAME: the legs job is the population the finding came from.
    if grep -q '^job legs:' "$out"; then
        ok "the legs job starts the stack, so the census has its subject"
    else
        bad "no \`legs\` job starts the stack — the census has no subject"
    fi
    if [ "$(grep -c 'qemu-arm64-before-up=yes' "$out" || true)" = "$n" ]; then
        ok "all ${n} compose-up job(s) register the arm64 QEMU handler before the up"
    else
        bad "not every compose-up job registers the arm64 QEMU handler before the up"
    fi
    if [ "$(grep -c 'logged-in-before-up=yes' "$out" || true)" = "$n" ]; then
        ok "all ${n} compose-up job(s) assume the role in us-east-1 and log in to $(sed -n 's/^host=//p' "$out") before the up"
    else
        bad "not every compose-up job logs in to $(sed -n 's/^host=//p' "$out") before the up (id-token: write, the role in us-east-1, then registry-type: public)"
    fi
    # THE READER CAN FIRE: the same workflow with every login step removed.
    "$ROOT/.venv/bin/python" - .github/workflows/ci.yml "$plant" <<'PYTHON'
import sys

import yaml

wf = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
for job in (wf.get("jobs") or {}).values():
    job["steps"] = [s for s in job.get("steps") or [] if not str(s.get("uses", "")).startswith("aws-actions/amazon-ecr-login@")]
with open(sys.argv[2], "w", encoding="utf-8") as handle:
    yaml.safe_dump(wf, handle)
PYTHON
    compose_up_jobs_census "$plant" >"${WORK}/compose-up-jobs-plant.txt" 2>&1 || true
    if [ "$(grep -c 'logged-in-before-up=yes' "${WORK}/compose-up-jobs-plant.txt" || true)" = "0" ] &&
        grep -q '^job legs:' "${WORK}/compose-up-jobs-plant.txt"; then
        ok "and the same reader sees no login in a planted copy with the login removed"
    else
        bad "the reader still reports a login in a planted copy that has none: $(tr '\n' ' ' <"${WORK}/compose-up-jobs-plant.txt")"
    fi
    # AND A STEP THAT CAN NEVER RUN IS NOT A LOGIN: the same workflow with
    # `if: false` on every login and QEMU step.
    "$ROOT/.venv/bin/python" - .github/workflows/ci.yml "${WORK}/ci-if-false.yml" <<'PYTHON'
import sys

import yaml

wf = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
for job in (wf.get("jobs") or {}).values():
    for s in job.get("steps") or []:
        if str(s.get("uses", "")).startswith(
            ("aws-actions/amazon-ecr-login@", "aws-actions/configure-aws-credentials@", "docker/setup-qemu-action@")
        ):
            s["if"] = False
with open(sys.argv[2], "w", encoding="utf-8") as handle:
    yaml.safe_dump(wf, handle)
PYTHON
    compose_up_jobs_census "${WORK}/ci-if-false.yml" >"${WORK}/compose-up-jobs-if-false.txt" 2>&1 || true
    if grep -q '^job legs: qemu-arm64-before-up=no logged-in-before-up=no$' "${WORK}/compose-up-jobs-if-false.txt"; then
        ok "and it counts neither the QEMU step nor the login when a planted \`if: false\` guards them"
    else
        bad "the reader counts a step guarded by \`if: false\`: $(tr '\n' ' ' <"${WORK}/compose-up-jobs-if-false.txt")"
    fi
}

# --- the gate after the login dials the compose store --------------------------
#
# `aws-actions/configure-aws-credentials` EXPORTS the assumed STS credentials
# into the job environment for every later step, over the workflow `env:` — so
# a gate step that inherits them talks to the compose MinIO with an AWS key it
# has never heard of (`InvalidAccessKeyId` on every MinIO test, every shard).
# So in every job that assumes an AWS identity, each later step that runs the
# gate pins all three exported names EMPTY at step level (house rule 62's
# form): the gate needs no cloud credential, and the store's own address and
# pair have one authority, `config/settings/test.py`. An `${{ env.… }}`
# expression is not a pin — it reads the context the login already overwrote.
#
# BLIND SPOT, declared: this reads the YAML. It cannot see what the action
# exports at run time — a future version that exports under another name
# (AWS_SECURITY_TOKEN, a profile) passes here; the belt for the store is
# `apps/files/tests/test_store_credential_belt.py`, which exports a hostile
# credential and proves the suite's clients never carry it.
gate_after_login_census() {
    # $1 the workflow file. Prints one line per gate step after a login, and a total.
    "$ROOT/.venv/bin/python" - "$1" <<'PYTHON'
import sys

import yaml

wf = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
steps_seen = 0
for name, job in (wf.get("jobs") or {}).items():
    steps = job.get("steps") or []
    login = next(
        (i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("aws-actions/configure-aws-credentials@")),
        None,
    )
    if login is None:
        continue
    for s in steps[login + 1 :]:
        if "check.sh" not in str(s.get("run", "")):
            continue
        steps_seen += 1
        env = s.get("env") or {}
        key = env.get("AWS_ACCESS_KEY_ID")
        secret = env.get("AWS_SECRET_ACCESS_KEY")
        token = env.get("AWS_SESSION_TOKEN", "<inherited>")
        pinned = key == "" and secret == "" and token == ""
        print(
            f"job {name} step {s.get('name', '?')!r}: "
            f"store-credential-pinned={'yes' if pinned else 'no'} "
            f"key={key if key is not None else '<inherited>'} token={token!r}"
        )
print(f"gate-steps-after-login={steps_seen}")
PYTHON
}

case_the_gate_after_the_login_dials_the_compose_store() {
    CURRENT="the gate step after the AWS login holds no cloud credential"
    [ -x "$ROOT/.venv/bin/python" ] || cannot_look "no venv interpreter at $ROOT/.venv/bin/python — the workflow reader cannot run"
    local out="${WORK}/gate-after-login.txt" n
    if ! gate_after_login_census .github/workflows/ci.yml >"$out" 2>&1; then
        bad "the reader could not read .github/workflows/ci.yml: $(tr '\n' ' ' <"$out")"
        return
    fi
    sed 's/^/             | /' "$out"
    n="$(sed -n 's/^gate-steps-after-login=//p' "$out")"
    # THE FLOOR, BY NAME: the legs job's gate step is the population the finding came from.
    if grep -q '^job legs step ' "$out"; then
        ok "the legs job runs the gate after its AWS login, so the census has its subject"
    else
        bad "no gate step follows an AWS login in the \`legs\` job — the census has no subject"
        return
    fi
    if [ "$(grep -c 'store-credential-pinned=yes' "$out" || true)" = "$n" ]; then
        ok "all ${n} gate step(s) after an AWS login pin AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY and AWS_SESSION_TOKEN empty"
    else
        bad "not every gate step after an AWS login pins the three exported names empty — it inherits the login's STS export"
    fi
    # THE READER CAN FIRE: the same workflow with the step-level pins removed,
    # and again with the key read through the env context the login overwrote.
    "$ROOT/.venv/bin/python" - .github/workflows/ci.yml "${WORK}/ci-unpinned.yml" "${WORK}/ci-env-context.yml" <<'PYTHON'
import copy
import sys

import yaml

wf = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
unpinned, via_context = copy.deepcopy(wf), copy.deepcopy(wf)
for job in (unpinned.get("jobs") or {}).values():
    for s in job.get("steps") or []:
        for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
            (s.get("env") or {}).pop(key, None)
for job in (via_context.get("jobs") or {}).values():
    for s in job.get("steps") or []:
        if "AWS_ACCESS_KEY_ID" in (s.get("env") or {}):
            s["env"]["AWS_ACCESS_KEY_ID"] = "${{ env.AWS_ACCESS_KEY_ID }}"
for path, doc in ((sys.argv[2], unpinned), (sys.argv[3], via_context)):
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(doc, handle)
PYTHON
    local plant
    for plant in unpinned env-context; do
        gate_after_login_census "${WORK}/ci-${plant}.yml" >"${WORK}/gate-after-login-${plant}.txt" 2>&1 || true
        if grep -q '^job legs step .*store-credential-pinned=no' "${WORK}/gate-after-login-${plant}.txt" &&
            ! grep -q 'store-credential-pinned=yes' "${WORK}/gate-after-login-${plant}.txt"; then
            ok "and the same reader refuses a planted copy (${plant})"
        else
            bad "the reader passes a planted copy (${plant}): $(tr '\n' ' ' <"${WORK}/gate-after-login-${plant}.txt")"
        fi
    done
}

# --- the tag-clone world ------------------------------------------------------
#
# THE VICTIM IS BUILT, NEVER FOUND (rung-execution §2). A destructive
# demonstration of "this checkout has no local main" run against something that
# already existed is a demonstration against somebody's afternoon: every
# checkout on a working box has `main`, and the only way to get one that does
# not is to make it. So each case here builds a scratch repository, tags a
# commit on it, and takes a REAL `git clone --branch <tag>` of it — which is
# git's own way of producing the detached, main-less checkout a consumer gets
# from `git clone --branch <a published tag> <the repository>`.
# Nothing below touches this checkout; `drive_require_scratch` refuses a path
# inside it, and the preamble's tripwire re-checks the real repository at exit.
REAL_GIT="$(command -v git)" || true
[ -n "$REAL_GIT" ] || cannot_look "no git on PATH — the tag-clone cases cannot build a victim"

SRC_REPO=""
new_source_repo() {
    N=$((N + 1))
    SRC_REPO="${WORK}/src${N}"
    drive_require_scratch SRC_REPO "${SRC_REPO:-}"
    mkdir -p "$SRC_REPO"
    git -C "$SRC_REPO" init -q
    git -C "$SRC_REPO" symbolic-ref HEAD refs/heads/main
    git -C "$SRC_REPO" config user.email drive@example.invalid
    git -C "$SRC_REPO" config user.name "setup env drive"
    echo "base" >"$SRC_REPO/README.md"
    git -C "$SRC_REPO" add README.md
    git -C "$SRC_REPO" commit -q -m "base"
    git -C "$SRC_REPO" tag v0.0.1-drive
    echo "           planted ${SRC_REPO##*/} — a repository with main at $(git -C "$SRC_REPO" rev-parse --short main) and the tag v0.0.1-drive on it"
}

# The two clones, and the difference between them is the whole subject: one is
# taken at a TAG (detached, no local branch at all), the other at a BRANCH.
CLONE=""
new_tag_clone() {
    N=$((N + 1))
    CLONE="${WORK}/clone${N}"
    drive_require_scratch CLONE "${CLONE:-}"
    git clone --quiet --branch v0.0.1-drive "$SRC_REPO" "$CLONE" 2>/dev/null ||
        cannot_look "could not clone the scratch repository at its tag — the victim could not be built"
    echo "           planted ${CLONE##*/} — a tag clone: HEAD $(git -C "$CLONE" rev-parse --short HEAD), local branches [$(git -C "$CLONE" for-each-ref --format='%(refname:short)' refs/heads | tr '\n' ' ')]"
}
new_branch_clone() {
    N=$((N + 1))
    CLONE="${WORK}/clone${N}"
    drive_require_scratch CLONE "${CLONE:-}"
    git clone --quiet --branch main "$SRC_REPO" "$CLONE" 2>/dev/null ||
        cannot_look "could not clone the scratch repository at its branch"
    echo "           planted ${CLONE##*/} — a branch clone: local branches [$(git -C "$CLONE" for-each-ref --format='%(refname:short)' refs/heads | tr '\n' ' ')]"
}

# THE THIRD SHAPE, and the one that decides the sentence. `--depth 1
# --single-branch` is what a CI job and a bandwidth-conscious stranger take, and
# it is not "a full clone with less history": measured on this box, 2026-09-15,
# it carries NO remote-tracking ref at all — `for-each-ref refs/remotes` is
# empty, so `origin/main` is not merely behind, it does not exist. Any printed
# remedy spelled against `origin/main` is a command that cannot run here, and
# the only way to know that is to build one.
new_shallow_tag_clone() {
    N=$((N + 1))
    CLONE="${WORK}/clone${N}"
    drive_require_scratch CLONE "${CLONE:-}"
    git clone --quiet --branch v0.0.1-drive --depth 1 --single-branch "$SRC_REPO" "$CLONE" 2>/dev/null ||
        cannot_look "could not shallow-clone the scratch repository at its tag — the victim could not be built"
    echo "           planted ${CLONE##*/} — a SHALLOW single-branch tag clone: HEAD $(git -C "$CLONE" rev-parse --short HEAD), local branches [$(git -C "$CLONE" for-each-ref --format='%(refname:short)' refs/heads | tr '\n' ' ')], remote-tracking [$(git -C "$CLONE" for-each-ref --format='%(refname:short)' refs/remotes | tr '\n' ' ')]"
}

# THE TAG MUST NOT BE THE TIP. "main ends at the remote's tip" is satisfied by a
# remedy that did nothing at all when the tag IS the tip, which is the shape
# `new_source_repo` leaves — so the remedy case moves the source's `main` one
# commit past the tag first, which is also the shape a consumer meets: they
# cloned v2.0.0 and the tree has moved on.
advance_the_source_main() {
    echo "past the tag" >>"$SRC_REPO/README.md"
    git -C "$SRC_REPO" add README.md
    git -C "$SRC_REPO" commit -q -m "one commit past the tag"
    echo "           advanced ${SRC_REPO##*/} — main now at $(git -C "$SRC_REPO" rev-parse --short main), the tag still at $(git -C "$SRC_REPO" rev-parse --short 'v0.0.1-drive^{commit}')"
}

# THE SHIM LOGS AND DELEGATES. "No branch, no switch" is an ABSENCE, and an
# absence nobody can see is not an assertion — so the log is asserted non-empty
# first, which is what tells "the step ran git and never branched" apart from
# "the shim was never on PATH".
SHIM_BIN=""
SHIM_LOG=""
plant_git_logger() {
    N=$((N + 1))
    SHIM_BIN="${WORK}/bin${N}"
    SHIM_LOG="${WORK}/git${N}.log"
    drive_require_scratch SHIM_BIN "${SHIM_BIN:-}"
    mkdir -p "$SHIM_BIN"
    {
        echo '#!/usr/bin/env bash'
        printf 'printf "%%s\\n" "$*" >> %q\n' "$SHIM_LOG"
        printf 'exec %q "$@"\n' "$REAL_GIT"
    } >"${SHIM_BIN}/git"
    chmod +x "${SHIM_BIN}/git"
    : >"$SHIM_LOG"
    echo "           planted ${SHIM_BIN##*/}/git — a logging shim in front of ${REAL_GIT}"
}
plant_git_failing_on() {
    # $1 — the git subcommand this shim refuses. Everything else delegates, so
    # the step gets as far as the command under test and no further.
    N=$((N + 1))
    SHIM_BIN="${WORK}/bin${N}"
    drive_require_scratch SHIM_BIN "${SHIM_BIN:-}"
    mkdir -p "$SHIM_BIN"
    {
        echo '#!/usr/bin/env bash'
        printf 'if [ "$1" = %q ]; then echo "fatal: planted failure in the drive" >&2; exit 128; fi\n' "$1"
        printf 'exec %q "$@"\n' "$REAL_GIT"
    } >"${SHIM_BIN}/git"
    chmod +x "${SHIM_BIN}/git"
    echo "           planted ${SHIM_BIN##*/}/git — a shim that fails \`git $1\` and delegates everything else"
}

# THE STEP RUNS IN A SUBSHELL, because one of its answers is `exit 2` and a
# sourced function that exits takes its caller with it — here, the whole drive,
# which would then have cleared nothing while looking like a clean run.
run_main_step() {
    # $1 dir · $2 case label · $3 (optional) a PATH prefix, for the shims
    local dir="$1" label="$2" pathpre="${3:-}"
    CURRENT="$label"
    N=$((N + 1))
    OUT="${WORK}/main${N}.log"
    RC=0
    (
        cd "$dir" || exit 3
        if [ -n "$pathpre" ]; then
            PATH="${pathpre}:${PATH}"
            export PATH
        fi
        ensure_local_main
    ) >"$OUT" 2>&1 || RC=$?
    echo "           block:"
    sed 's/^/             > /' "$OUT"
}

# THE REMEDY IS PARSED OUT OF THE SENTENCE, NEVER TYPED HERE. A drive holding
# its own copy of the follow-up command agrees with `setup.sh` by construction
# and would have stayed green through the whole of the defect this pair of
# helpers exists for: the sentence read fine, the command in it could not run.
# So the case takes the tail of the printed line and executes exactly that.
REMEDY=""
remedy_from_the_sentence() {
    REMEDY="$(sed -n 's/^main created at .*to move to the tip: \(.*\))$/\1/p' "$OUT" | sed -n 1p)"
    if [ -n "$REMEDY" ]; then
        ok "the sentence names a follow-up: \`${REMEDY}\`"
    else
        bad "the printed sentence names nothing after \`to move to the tip: \` — there is no remedy to run"
    fi
}

run_the_remedy() {
    # $1 dir. In a subshell, in that checkout, as the shell a stranger pastes it
    # into would run it — which is why it is `eval` and not a hand-split argv:
    # the sentence contains a `&&`, and a remedy whose two halves the drive ran
    # separately would not be the sentence.
    N=$((N + 1))
    OUT="${WORK}/remedy${N}.log"
    RC=0
    (cd "$1" && eval "$REMEDY") >"$OUT" 2>&1 || RC=$?
    echo "           ran the printed remedy: ${REMEDY}"
    sed 's/^/             > /' "$OUT"
}

run_the_superseded_remedy() {
    # $1 dir. THE CONTROL, which keeps the red permanently instead of pasting
    # it once into a report: the command the
    # sentence used to print, run in the same clone, in the same state the step
    # leaves. If it ever starts succeeding, the state the step leaves has
    # changed and the argument above the new sentence needs re-reading.
    N=$((N + 1))
    OUT="${WORK}/superseded${N}.log"
    RC=0
    (cd "$1" && git branch -f main origin/main) >"$OUT" 2>&1 || RC=$?
    echo "           ran the SUPERSEDED remedy: git branch -f main origin/main"
    sed 's/^/             > /' "$OUT"
}

prints_nothing() {
    if [ ! -s "$OUT" ]; then
        ok "printed nothing"
    else
        bad "printed something, and a checkout that already has main must be silent"
    fi
}

git_log_ran_but_never() {
    # $1 — an ERE of the subcommands that must not appear as the first word.
    if [ -s "$SHIM_LOG" ]; then
        ok "the shim was entered ($(wc -l <"$SHIM_LOG" | tr -d ' ') git call(s)): $(tr '\n' ';' <"$SHIM_LOG")"
    else
        bad "the shim logged NOTHING — it was not on PATH, so the absence below proves nothing"
    fi
    if grep -qE "^($1) " "$SHIM_LOG"; then
        bad "the step ran a \`git $1\` in a checkout whose repository already has main"
    else
        ok "no \`git $1\` in the log"
    fi
}

has_no_local_main() {
    # $1 dir · $2 what
    if git -C "$1" rev-parse -q --verify refs/heads/main >/dev/null 2>&1; then
        bad "$2 HAS a local refs/heads/main, and this case needs one that does not"
    else
        ok "$2 has no local refs/heads/main"
    fi
}

case_a_tag_clone_gets_main_at_head_and_is_on_it() {
    new_source_repo
    local want
    want="$(git -C "$SRC_REPO" rev-parse v0.0.1-drive^{commit})"
    new_tag_clone
    CURRENT="the victim is the shape a tag clone arrives in"
    has_no_local_main "$CLONE" "the fresh tag clone"
    if [ "$(git -C "$CLONE" symbolic-ref -q HEAD || echo detached)" = "detached" ]; then
        ok "and its HEAD is detached, which is what \`clone --branch <tag>\` leaves"
    else
        bad "its HEAD is not detached — the clone is not the shape a tag clone takes"
    fi

    run_main_step "$CLONE" "a tag clone gets main at HEAD and is on it"
    exits 0
    local got
    got="$(git -C "$CLONE" rev-parse -q --verify refs/heads/main || true)"
    if [ "$got" = "$want" ]; then
        ok "refs/heads/main is at the tag's commit (${got})"
    else
        bad "refs/heads/main is '${got:-absent}', wanted the tag's commit ${want}"
    fi
    got="$(git -C "$CLONE" symbolic-ref -q HEAD || echo detached)"
    if [ "$got" = "refs/heads/main" ]; then
        ok "HEAD is refs/heads/main — the checkout is ON the branch, not merely beside it"
    else
        bad "HEAD is '${got}', wanted refs/heads/main"
    fi
    # THE WHOLE SENTENCE, not a substring of it: a step that creates a ref and
    # says nothing leaves the next command's behaviour unexplained, and the
    # remedy for a reader who wanted the tip is inside these brackets.
    says "main created at $(git -C "$CLONE" rev-parse --short main) (this checkout had no local main — a tag clone; the --loop scope and the database name derive from it; to move to the tip: git fetch origin main && git reset --hard FETCH_HEAD)"
}

case_the_printed_remedy_runs_where_the_step_leaves_you() {
    # WHY THE SENTENCE SAYS `FETCH_HEAD` AND NOT `origin/main` — the paragraph,
    # because the next reader's instinct will be to "tidy" it back.
    #
    # The step's last act is `git switch main`, so it hands the reader a
    # checkout that is ON `main`. The sentence used to print
    # `git branch -f main origin/main`, and git refuses to force-update a branch
    # that is checked out: `fatal: cannot force update the branch 'main'
    # checked out at …`, exit 128, measured on both clone shapes 2026-09-15.
    # That is the whole of V-F's finding 1 — the message named a cause it had
    # never run.
    #
    # Correcting only the VERB (`git fetch origin main && git reset --hard
    # origin/main` — the shape the criteria name) fixes the full clone and
    # leaves the shallow one broken: a `--depth 1 --single-branch` clone has no
    # remote-tracking refs at all, so the fetch succeeds and the reset dies with
    # `fatal: ambiguous argument 'origin/main'`, exit 128. Measured, both
    # shapes, the same morning. `FETCH_HEAD` is the ref the fetch just wrote,
    # it exists on every shape by construction, and it is the ONE sentence that
    # runs everywhere — which is why the conditional sentence the criteria
    # allowed as an alternative is not what shipped: a remedy that RUNS beats a
    # remedy that explains why it cannot.
    #
    # `git merge --ff-only FETCH_HEAD` was measured too and is green on both
    # shapes. It is not what shipped because it REFUSES when the tag is not an
    # ancestor of the tip — a hotfix tag off a release branch — and the sentence
    # promises movement to the tip, not a diagnosis.
    #
    # The remedy is PARSED from the printed line (`remedy_from_the_sentence`),
    # so this case cannot pass on a command the script does not actually print.
    new_source_repo
    advance_the_source_main
    local tip tag shape here
    tip="$(git -C "$SRC_REPO" rev-parse main)"
    tag="$(git -C "$SRC_REPO" rev-parse 'v0.0.1-drive^{commit}')"

    for shape in full shallow; do
        case "$shape" in
        full) new_tag_clone ;;
        shallow) new_shallow_tag_clone ;;
        esac
        here="$CLONE"

        run_main_step "$here" "a ${shape} tag clone: the step leaves the reader ON main, at the tag"
        exits 0
        if [ "$(git -C "$here" symbolic-ref -q HEAD || echo detached)" = "refs/heads/main" ] &&
            [ "$(git -C "$here" rev-parse HEAD)" = "$tag" ]; then
            ok "HEAD is refs/heads/main at the tag ($(git -C "$here" rev-parse --short HEAD)) — the state every remedy below runs from"
        else
            bad "HEAD is $(git -C "$here" symbolic-ref -q HEAD || echo detached) at $(git -C "$here" rev-parse --short HEAD), wanted refs/heads/main at the tag"
        fi
        remedy_from_the_sentence
        case "$REMEDY" in
        *"branch -f main"*) bad "the sentence still names \`branch -f main\` against the branch the step just checked out" ;;
        *) ok "the sentence does not name \`branch -f main\` — the shape git refuses here" ;;
        esac

        # THE RED, KEPT: the superseded command, in this clone, in this state.
        CURRENT="a ${shape} tag clone: the SUPERSEDED remedy is refused where the step leaves you"
        run_the_superseded_remedy "$here"
        if [ "$RC" -ne 0 ]; then
            ok "exit ${RC} — it does not run here, which is the defect this case closes"
        else
            bad "the superseded \`git branch -f main origin/main\` SUCCEEDED — the state the step leaves has changed"
        fi
        says "fatal:"
        if [ "$(git -C "$here" rev-parse main)" = "$tag" ]; then
            ok "and it moved nothing — main is still at the tag"
        else
            bad "main moved to $(git -C "$here" rev-parse --short main) despite the refusal"
        fi
        if [ "$shape" = shallow ]; then
            # THE SECOND HALF of the finding, driven independently of the
            # checked-out refusal: even detached, there is no `origin/main` here
            # to aim at.
            CURRENT="a shallow tag clone: origin/main does not exist at all"
            N=$((N + 1))
            OUT="${WORK}/originmain${N}.log"
            RC=0
            (cd "$here" && git rev-parse --verify origin/main) >"$OUT" 2>&1 || RC=$?
            if [ "$RC" -ne 0 ]; then
                ok "exit ${RC} — \`origin/main\` is not a revision in a --depth 1 --single-branch clone"
            else
                bad "origin/main resolved to $(cat "$OUT") — this clone is not the shape the case needs"
            fi
        fi

        # THE GREEN: the sentence's own command, run as printed.
        CURRENT="a ${shape} tag clone: the PRINTED remedy runs and lands on the remote's tip"
        run_the_remedy "$here"
        exits 0
        if [ "$(git -C "$here" rev-parse main)" = "$tip" ]; then
            ok "main is at the source's tip ($(git -C "$here" rev-parse --short main)), one commit past the tag it was created at"
        else
            bad "main is at $(git -C "$here" rev-parse --short main), wanted the tip $(git -C "$SRC_REPO" rev-parse --short main)"
        fi
        if [ "$(git -C "$here" symbolic-ref -q HEAD || echo detached)" = "refs/heads/main" ]; then
            ok "and the checkout is still ON main — the remedy did not detach the reader"
        else
            bad "the checkout is no longer on main after the remedy"
        fi
    done
}

case_a_clone_with_main_is_untouched() {
    new_source_repo
    new_branch_clone
    plant_git_logger
    run_main_step "$CLONE" "a clone that already has main is untouched" "$SHIM_BIN"
    exits 0
    prints_nothing
    git_log_ran_but_never 'branch|switch'
}

case_a_linked_worktree_of_a_repository_holding_main_is_untouched() {
    # THE pm-push AND rung/* SHAPE, and the reason the negative is a criterion:
    # every worktree on a working box is detached-or-branched inside a family
    # whose common git dir HAS main, so this step must be a no-op there by
    # construction rather than by luck.
    new_source_repo
    N=$((N + 1))
    local wt="${WORK}/wt${N}"
    drive_require_scratch wt "${wt:-}"
    git -C "$SRC_REPO" worktree add --detach "$wt" HEAD >/dev/null 2>&1 ||
        cannot_look "could not add a linked worktree to the scratch repository"
    echo "           planted ${wt##*/} — a linked worktree of ${SRC_REPO##*/}, detached at $(git -C "$wt" rev-parse --short HEAD)"
    plant_git_logger
    run_main_step "$wt" "a linked worktree of a repository holding main is untouched" "$SHIM_BIN"
    exits 0
    prints_nothing
    git_log_ran_but_never 'branch|switch'
    if [ "$(git -C "$wt" symbolic-ref -q HEAD || echo detached)" = "detached" ]; then
        ok "the worktree is still detached — nothing moved it"
    else
        bad "the worktree was switched onto a branch"
    fi
    git -C "$SRC_REPO" worktree remove --force "$wt" >/dev/null 2>&1 || true
}

case_an_unborn_head_prints_and_skips() {
    N=$((N + 1))
    local empty="${WORK}/empty${N}"
    drive_require_scratch empty "${empty:-}"
    mkdir -p "$empty"
    git -C "$empty" init -q
    git -C "$empty" symbolic-ref HEAD refs/heads/main
    echo "           planted ${empty##*/} — an initialised repository with no commit at all"
    run_main_step "$empty" "an unborn HEAD prints and skips"
    exits 0
    says "no commit to place main on — skipping"
    has_no_local_main "$empty" "the empty repository"
}

case_a_failing_git_is_exit_2_naming_the_command() {
    new_source_repo
    new_tag_clone
    plant_git_failing_on branch
    run_main_step "$CLONE" "a git that cannot create the ref is exit 2 naming the command" "$SHIM_BIN"
    exits 2
    says 'git branch main HEAD` failed'
    has_no_local_main "$CLONE" "the clone (nothing was half-created)"
}

case_the_loop_scope_refusal_is_what_a_tag_clone_hits_without_the_step() {
    # THE CONTROL. It runs the SHIPPED `loop_tier_own_apps` — not a copy of its
    # text — in the same scratch tag clone, before the step and after it. Before
    # is the 0.8 s refusal the field test measured on a real `git clone --branch
    # v2.0.0`; after is the scope deriving normally. A rung that softened that
    # refusal, or one that stopped creating the ref, takes this case with it.
    new_source_repo
    new_tag_clone

    local here="$PWD"
    CURRENT="before the step: the tag clone hits the --loop scope refusal"
    N=$((N + 1))
    OUT="${WORK}/scope${N}.log"
    RC=0
    cd "$CLONE"
    loop_tier_own_apps >"$OUT" 2>&1 || RC=$?
    cd "$here"
    exits 2
    says "this checkout has NO local refs/heads/main"

    run_main_step "$CLONE" "the step creates the ref the scope derivation reads"
    exits 0

    CURRENT="after the step: the scope derives, on the uncommitted-only basis"
    N=$((N + 1))
    OUT="${WORK}/scope${N}.log"
    RC=0
    cd "$CLONE"
    loop_tier_own_apps >"$OUT" 2>&1 || RC=$?
    cd "$here"
    exits 0
    case "${LOOP_TIER_BASIS:-}" in
    *"on main itself"*) ok "the basis is the on-main one: ${LOOP_TIER_BASIS}" ;;
    *) bad "the basis is '${LOOP_TIER_BASIS:-empty}', not the on-main uncommitted-only basis" ;;
    esac
}

# THE CROSS-APP CENSUS THAT USED TO SIT HERE HAS ITS OWN DRIVE.
# `case_the_siblings_census_names_every_script_that_depends_on_a_local_main`
# moved to the `test_scripts_census.sh` drive beside this one, with its name,
# its pattern and its argument. It is not a case about `setup.sh` — it
# quantifies over every
# script in that directory, which is a claim about the whole tree — and a census that runs
# only inside a drive the full gate reaches is a census the per-rung gate cannot
# see. The new file carries the `# census: cross-app` marker, so the `--loop`
# always-on leg runs it at every scope. This drive keeps the cases that are
# about the STEP: that `ensure_local_main` creates the ref, and that the scope
# derivation refuses without it.

# --- the clock ----------------------------------------------------------------

case_every_step_prints_its_wall_and_the_run_its_total() {
    # BY EXTRACTION, over two planted no-op steps: the wrapper is what is under
    # test, and running the whole of `setup.sh` to see two elapsed lines would
    # need docker, a venv and an identity provider — which is the reason every
    # other case here is fenced too.
    CURRENT="the step wrapper prints a wall per step and a total for the run"
    N=$((N + 1))
    OUT="${WORK}/wall${N}.log"
    RC=0
    (
        # shellcheck source=/dev/null
        . "$EXTRACT_WALL"
        step "alpha"
        step "beta"
        setup_total
    ) >"$OUT" 2>&1 || RC=$?
    echo "           block:"
    sed 's/^/             > /' "$OUT"
    exits 0
    local walls
    walls="$(grep -cE '^  \([a-z]+: [0-9]+\.[0-9]+s\)$' "$OUT" || true)"
    if [ "$walls" -eq 2 ]; then
        ok "two steps, two elapsed lines"
    else
        bad "wanted 2 elapsed lines of the shape \`  (<name>: <n>s)\`, found ${walls}"
    fi
    if grep -qE '^  \(alpha: ' "$OUT" && grep -qE '^  \(beta: ' "$OUT"; then
        ok "each line names its own step"
    else
        bad "the elapsed lines do not name alpha and beta"
    fi
    if grep -qE '^setup: total [0-9]+\.[0-9]+s$' "$OUT"; then
        ok "the run prints \`setup: total <n>s\`"
    else
        bad "no line of the shape \`setup: total <n>s\`"
    fi
    # A step that has not ended has no wall: `step_end` called twice must not
    # print twice, or the total below would be preceded by a phantom step.
    if [ "$(grep -cE '^  \(beta: ' "$OUT" || true)" -eq 1 ]; then
        ok "the last step's wall is printed exactly once, by setup_total"
    else
        bad "the last step's wall is printed more than once"
    fi
}

case_the_clock_is_rung_starts_and_not_a_third_one() {
    # Principle 13 as a CENSUS OVER A DISCOVERABLE POPULATION rather than a hand
    # list: every file in `scripts/` that defines `now_ms` must either BE
    # `rung_start.sh` — which owns the portability ladder — or name it, so a
    # reader of any copy knows which one is the original and where a fix lands.
    # `verify_start.sh` set that precedent first
    # (`scripts/verify_start.sh:297`, "rung_start.sh's, deliberately identical")
    # and `setup.sh` follows it. A genuinely third clock — a copy that cites
    # nothing — is what this case is here to catch.
    CURRENT="one clock, copied, every copy naming its source"
    local defs f
    defs="$(grep -rln '^now_ms() {' scripts/*.sh | sort)"
    echo "           clock census: $(printf '%s' "$defs" | tr '\n' ' ')"
    case "$defs" in
    *scripts/rung_start.sh*) ok "scripts/rung_start.sh still defines it — the original is there" ;;
    *) bad "scripts/rung_start.sh no longer defines now_ms — the file every copy cites is gone" ;;
    esac
    case "$defs" in
    *scripts/setup.sh*) ok "scripts/setup.sh carries a copy — the first thing a stranger runs has a clock" ;;
    *) bad "scripts/setup.sh defines no now_ms — the first thing a stranger runs has no clock" ;;
    esac
    for f in $defs; do
        [ "$f" != "scripts/rung_start.sh" ] || continue
        if grep -qF 'rung_start.sh' "$f"; then
            ok "${f} names rung_start.sh as where the ladder is owned"
        else
            bad "${f} defines now_ms and cites nothing — that is a third clock"
        fi
    done
    if grep -qF 'scripts/rung_start.sh' "$EXTRACT_WALL"; then
        ok "the fence itself names scripts/rung_start.sh, so the copy is readable as a copy"
    else
        bad "the step-wall fence does not name the file it copied the clock from"
    fi
}

# --- the wiring ---------------------------------------------------------------

case_ensure_local_main_precedes_the_environment_step() {
    # `.env` PERSISTS A DERIVED NAME: the database name carries the branch
    # (scripts/db.sh), and on a detached HEAD there is no branch to carry. So
    # the ref has to exist before the first file that remembers it — which is a
    # POSITION in this script, and the only thing that can hold it is a case.
    CURRENT="the local-main step comes before the environment step"
    local banner call env_line
    banner="$(grep -nF 'step "local main"' scripts/setup.sh | sed -n '1s/:.*//p' || true)"
    call="$(grep -nx 'ensure_local_main' scripts/setup.sh | sed -n '1s/:.*//p' || true)"
    env_line="$(grep -nF 'step "environment file"' scripts/setup.sh | sed -n '1s/:.*//p' || true)"
    if [ -n "$banner" ] && [ -n "$call" ] && [ -n "$env_line" ] &&
        [ "$call" -gt "$banner" ] && [ "$env_line" -gt "$call" ]; then
        ok "banner at ${banner}, call at ${call}, the environment step at ${env_line}"
    else
        bad "banner at \"${banner:-none}\", call at \"${call:-none}\", environment step at \"${env_line:-none}\""
    fi
    # AND IT IS THE FIRST STEP, not merely an earlier one: no `step` banner
    # above it.
    local first
    first="$(grep -n '^step "' scripts/setup.sh | sed -n '1s/:.*//p' || true)"
    if [ "$first" = "$banner" ]; then
        ok "it is the FIRST step banner in the file (line ${first})"
    else
        bad "the first step banner is at line ${first:-none}, not ${banner:-none}"
    fi
}

case_the_total_is_the_last_thing_the_script_prints() {
    # "The last line of a run reads `setup: total <n>s`" is a property of the
    # SCRIPT's shape, not of the wrapper: a `printf` added below the call would
    # take the last line back without changing anything the case above sees.
    CURRENT="setup_total is the last statement that prints"
    local tail_code lines has_call="" has_guard=""
    tail_code="$(sed -n '/^setup_total$/,$p' scripts/setup.sh | sed 's/#.*$//' | grep -v '^[[:space:]]*$' || true)"
    # NO `grep -q` AT THE TAIL OF A PIPELINE, and `scripts/sweep.sh`'s census is
    # what caught the first draft of this case doing it: a reader that
    # short-circuits its own producer under `pipefail` takes SIGPIPE over 64 KiB
    # and the pipeline's status is then the wrong answer, every run. The same
    # note sits over `case_the_minio_pin_names_the_registry_that_serves_it` for
    # the same reason. `$tail_code` is already a shell string, so both
    # membership tests need no process at all.
    lines=$(printf '%s\n' "$tail_code" | wc -l)
    lines=${lines// /}
    case $'\n'"${tail_code}"$'\n' in
    *$'\n'setup_total$'\n'*) has_call=1 ;;
    esac
    case "$tail_code" in
    *'exit 1'*) has_guard=1 ;;
    esac
    if [ "$lines" -eq 2 ] && [ -n "$has_call" ] && [ -n "$has_guard" ]; then
        ok "nothing but the SETUP_INCOMPLETE exit guard follows it: $(printf '%s' "$tail_code" | tr '\n' ';')"
    else
        bad "something else follows setup_total: $(printf '%s' "$tail_code" | tr '\n' ';')"
    fi
}

case_the_readme_quickstart_names_the_tag_clone_shape_and_the_number() {
    # README IS WHERE A STRANGER WHO NEVER LOADS A SKILL READS. The two
    # sentences point at the mechanism — the step's name and the fact that a
    # number is printed — and never repeat the script's text, which is the class
    # the pointer-not-a-copy class: a second copy of a sentence is a second thing to keep
    # true.
    CURRENT="README's quickstart names the tag-clone shape and the number"
    local section
    section="$(sed -n '/^## Quickstart, from a fresh clone$/,/^## /p' README.md)"
    if [ -z "$section" ]; then
        bad "README.md has no section heading reading exactly '## Quickstart, from a fresh clone'"
        return
    fi
    case "$section" in
    *"clone --branch"*) ok "it names the tag-clone command shape" ;;
    *) bad "it never names \`clone --branch\` — the shape every consumer's first clone takes" ;;
    esac
    case "$section" in
    *"ensure_local_main"* | *"creates one"*) ok "it names the step that creates the ref" ;;
    *) bad "it does not say setup.sh creates the ref" ;;
    esac
    case "$section" in
    *"setup: total"* | *"total"*) ok "it says the run prints its total" ;;
    *) bad "it does not say a total is printed" ;;
    esac
}

case_the_step_calls_services_up() {
    CURRENT="setup.sh's services step calls the fenced function"
    local step_line call_line up_line fence_line
    step_line="$(grep -nF 'step "services"' scripts/setup.sh | sed -n '1s/:.*//p' || true)"
    call_line="$(grep -nx 'services_up' scripts/setup.sh | sed -n '1s/:.*//p' || true)"
    if [ -n "$step_line" ] && [ -n "$call_line" ] && [ "$call_line" -gt "$step_line" ]; then
        ok "the step at line ${step_line} calls services_up at ${call_line}"
    else
        bad "step at \"${step_line:-none}\", call at \"${call_line:-none}\""
    fi
    # THE CONTROL for the replaced shape: the one `up -d` left in the
    # file is inside the fence, below `services_up`. An `up -d` above it is the
    # baseline's unguarded start, back again.
    fence_line="$(grep -nF "$SENT_SVC_OPEN" scripts/setup.sh | sed -n '1s/:.*//p' || true)"
    up_line="$(grep -nF 'docker compose up -d' scripts/setup.sh | sed -n '1s/:.*//p' || true)"
    if [ -n "$fence_line" ] && [ -n "$up_line" ] && [ "$up_line" -gt "$fence_line" ]; then
        ok "the only \`docker compose up -d\` (line ${up_line}) sits inside the services fence (opened at ${fence_line})"
    else
        bad "fence opens at \"${fence_line:-none}\", the first \`docker compose up -d\` is at \"${up_line:-none}\" — a start outside the fence pulls nothing first"
    fi
}

case_the_step_calls_the_function() {
    CURRENT="setup.sh's environment step calls the function"
    local step_line call_line chmod_line
    step_line="$(grep -nF 'step "environment file"' scripts/setup.sh | head -1 | cut -d: -f1 || true)"
    call_line="$(grep -nx 'env_sync_from_example' scripts/setup.sh | head -1 | cut -d: -f1 || true)"
    chmod_line="$(grep -nx 'chmod 600 .env' scripts/setup.sh | head -1 | cut -d: -f1 || true)"
    if [ -n "$step_line" ] && [ -n "$call_line" ] && [ -n "$chmod_line" ] &&
        [ "$call_line" -gt "$step_line" ] && [ "$chmod_line" -gt "$call_line" ]; then
        ok "the step calls it at line ${call_line} and the owner-only chmod still follows at ${chmod_line}"
    else
        bad "step at \"${step_line:-none}\", call at \"${call_line:-none}\", chmod at \"${chmod_line:-none}\""
    fi
}

case_the_superseded_sentence_is_gone() {
    CURRENT="the sentence the step no longer means is gone"
    if grep -qF 'already present, leaving it alone' scripts/setup.sh; then
        bad "setup.sh still says it leaves an existing .env alone, and it does not"
    else
        ok "setup.sh no longer claims to leave an existing .env alone"
    fi
}

case_the_previous_file_is_ignored_by_git() {
    # The file holds a whole copy of the environment, credential included. It is
    # covered by the `.env.*` line rather than a line of its own, and this case
    # is what tells the two apart if that line ever narrows.
    CURRENT=".env.previous is ignored by git"
    if git check-ignore -q .env.previous 2>/dev/null; then
        ok "git ignores .env.previous"
    else
        bad "git does NOT ignore .env.previous — a full copy of the environment is stageable"
    fi
}

case_the_drive_is_registered_in_the_gate() {
    CURRENT="this drive runs in the gate's selftest leg"
    if grep -qF 'scripts/tests/test_setup_env.sh' scripts/check.sh; then
        ok "check.sh calls it"
    else
        bad "check.sh does not call it — an unregistered drive is a drive nobody runs"
    fi
}

echo "test_setup_env: driving the two fences extracted from scripts/setup.sh"
echo "           env-sync: $(wc -l <"$EXTRACT" | tr -d ' ') line(s) between the sentinels into ${EXTRACT}"
echo "           services: $(wc -l <"$EXTRACT_SVC" | tr -d ' ') line(s) between the sentinels into ${EXTRACT_SVC}"
echo "           local-main: $(wc -l <"$EXTRACT_MAIN" | tr -d ' ') line(s) between the sentinels into ${EXTRACT_MAIN}"
echo "           step-wall: $(wc -l <"$EXTRACT_WALL" | tr -d ' ') line(s) between the sentinels into ${EXTRACT_WALL}"

case_the_result_is_the_example_with_the_values_carried_over
case_the_changed_value_sits_at_the_examples_position
case_the_extra_key_sits_after_the_marker
case_the_block_counts_one_added_one_preserved_one_kept
case_the_block_never_prints_a_value
case_the_previous_file_is_the_original
case_a_second_run_changes_nothing_and_says_so
case_a_value_holding_an_equals_or_a_hash_survives
case_no_env_at_all_copies_the_example
case_no_example_is_a_refusal_that_touches_nothing
case_an_empty_env_is_a_truncated_file_and_not_an_empty_environment
case_a_key_present_twice_collapses_to_its_last_value
case_the_pinned_marker_survives_the_rebuild
case_the_digest_agrees_when_the_files_agree
case_the_digest_model_still_matches_the_shipped_digest
case_a_pull_failure_is_could_not_look_naming_the_image
case_a_healthy_stack_is_reused_without_a_pull
case_a_clean_pull_starts_the_stack_and_then_waits
case_a_reference_names_its_registry_the_way_docker_reads_one
case_the_minio_pin_names_the_registry_that_serves_it
case_every_compose_up_job_runs_arm64_and_logs_in_before_the_pull
case_the_gate_after_the_login_dials_the_compose_store
case_a_tag_clone_gets_main_at_head_and_is_on_it
case_the_printed_remedy_runs_where_the_step_leaves_you
case_a_clone_with_main_is_untouched
case_a_linked_worktree_of_a_repository_holding_main_is_untouched
case_an_unborn_head_prints_and_skips
case_a_failing_git_is_exit_2_naming_the_command
case_the_loop_scope_refusal_is_what_a_tag_clone_hits_without_the_step
case_every_step_prints_its_wall_and_the_run_its_total
case_the_clock_is_rung_starts_and_not_a_third_one
case_ensure_local_main_precedes_the_environment_step
case_the_total_is_the_last_thing_the_script_prints
case_the_readme_quickstart_names_the_tag_clone_shape_and_the_number
case_the_step_calls_services_up
case_the_step_calls_the_function
case_the_superseded_sentence_is_gone
case_the_previous_file_is_ignored_by_git
case_the_drive_is_registered_in_the_gate

echo "test_setup_env: ${PASSED} passed · ${FAILED} failed"
drive_finished
if [ "$FAILED" -gt 0 ]; then
    echo "!! EITHER the services step no longer pulls before it starts — so a registry" >&2
    echo "   that has dropped a pinned tag is a timeout inside \`up\` again instead of a" >&2
    echo "   refusal naming the image — the failure that cost a fresh clone its files" >&2
    echo "   store on 2026-09-12" >&2
    echo "   — or it refuses when it should reuse, and every setup.sh in the house now" >&2
    echo "   spends the network on a stack that was already healthy." >&2
    echo "   OR the environment step no longer regenerates .env from .env.example the way a" >&2
    echo "   verifier's clone builds its own — or it does, and has started losing a value," >&2
    echo "   dropping a key, printing one, or rewriting the file on a second run. All four" >&2
    echo "   halves are load-bearing: the first puts every builder's consult back to" >&2
    echo "   re-measuring the whole suite, and the others cost a credential, a setting or" >&2
    echo "   an afternoon." >&2
    exit 1
fi
exit 0
