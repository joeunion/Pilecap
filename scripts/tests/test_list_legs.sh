#!/usr/bin/env bash
# THIS FILE IS EXECUTED, AND IT IS BASH — not POSIX sh, and not zsh.
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
# drives: .github/workflows/ci.yml apps/conftest.py config/ docs/product/build-contract.md quality/ scripts/check.sh scripts/loop_tier.sh scripts/test.sh scripts/tests/fixtures/collection_world/ scripts/tests/test_loop_scope.sh scripts/tests/test_selftest_leg.sh scripts/verify_start.sh
# cites: scripts/tests/test_shard_census.sh scripts/pytest_durations.json apps/example/services.py
# The drive for the gate's UNIT TABLE and for `./scripts/check.sh --list-legs`.
#
#   ./scripts/tests/test_list_legs.sh          run every case
#   ./scripts/tests/test_list_legs.sh --list   name them and stop
#
# WHY IT EXISTS. `FULL_LEGS` in `scripts/check.sh` is the string every banked
# verdict row carries — it is what a green gate is claiming to have run — and it
# was maintained by hand. It had drifted by six names: `queue-index`,
# `archaeology`, `adr-census`, `dangling-docs`, `loop-names` and `ci-env` were
# announced on every full gate and named on no verdict row. The same hand-list
# hazard is what put a leg list into CI's YAML, where it went stale for a whole
# cycle with the house-rules engine unrun.
#
# So the gate now DERIVES the announced sequence from its own leg call sites and
# refuses when the string and the sequence disagree, and the unit table beside
# them is validated before it is printed. This drive is what proves those
# refusals fire, and that the refactor which made them possible — every leg body
# moved into a function — changed no mode's transcript.
#
# THE TWO INSTRUMENTS, AND WHY THERE ARE TWO.
#   1. The STATIC one, inside the gate: `--list-legs` reads the column-zero `leg`
#      call sites out of the file. Cheap, and what CI asks.
#   2. The DYNAMIC one, here: each mode is RUN with `DJB_GATE_LEGS_DRY=1`, which
#      announces every leg and runs no body, and the announced sequence is
#      compared against the fixture below. A static reading of a 4500-line
#      script is a second implementation of its control flow; the day the two
#      disagree the reading is the one that is green, which is why the fixture
#      is compared against the RUN and not against another grep.
#
# THE FIXTURE IS A READING OF THIS TREE, NOT A COPY OF ANY PLAN. The three
# sequences below were read off `scripts/check.sh` at 1c4c589a — the last commit
# before any leg body moved into a function — by walking the flow: every
# `leg <name>` call site in order, the `--fast` early exit, the `--loop` block's
# own legs and its `exit 0`. An older reading was available and was not used:
# six legs had been added to the file since it was taken, so a fixture from
# there would have been green against a sequence this tree never ran. A fixture
# is only worth what the tree it was read off is.
#
# AND IT WAS RE-CAPTURED ONCE, DELIBERATELY (2026-09-15). `fe` MOVED OUT OF THE
# `--loop` BLOCK ONTO THE FULL PATH, on a ruling: a tri-state leg that prints
# `skip` when there is no client is still a leg that RAN, and a leg the full
# gate never announces is one no verdict row names and no runner is ever handed.
# So the full sequence GAINED `fe` after `deploy-check` (22 unique names → 23)
# and the `--loop` sequence kept the same set with `fe` one position earlier —
# there is one call site, above the `--loop` block, and both modes reach it.
# THIS IS THE ONLY LICENCE THIS CASE HAS EVER GIVEN: the fixture is re-captured
# when a rung CHANGES the transcript on purpose and says so here, never to make
# a red go away.
#
# IT BUILDS ITS OWN VICTIMS, always: every plant goes into a `git clone` of this
# checkout under `mktemp -d`. Nothing here edits a real file.
#
# IT SHELLS OUT TO THE GATE ON PURPOSE, AND ONLY IN A CLONE. The usual rule is
# that a drive calls the leg BODY, because the per-checkout gate lock refuses a
# nested `./scripts/check.sh`. The subject here IS the gate's argument handling
# and its whole-mode flow, so there is no body to call — and a clone is a
# different checkout, so it has its own lock and takes nobody's.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#   * WHAT THE BODIES DO. Every case below runs with the bodies switched off.
#     That `ruff` still lints is `ruff`'s leg's business and the gate's own
#     transcript; this drive asserts only WHICH legs a mode announces and in
#     what order.
#   * THE DYNAMIC HALF OF THE SEQUENCE CENSUS. A leg whose body `exit`s early
#     in a way that skips a LATER leg would show here as the full sequence,
#     because no body runs. The merge-train bank's transcript is that instrument.
#   * NOTHING ABOUT INDENT ANY MORE, and that was a blind spot until a field
#     test planted it: the listing reads column-zero `leg` call sites, so an
#     INDENTED leg on the full path used to be invisible to it and to the dry
#     sequence alike. The pairing census reads every indent — `case_an_announced
#     _leg_whose_body_is_not_behind_the_runner_is_exit_2` — so what is left
#     uncovered is an indented leg that IS behind the runner: the dry sequence
#     sees it, and which MODE reaches it is the flow's business, not this file's.
#   * THE `--pr` AND `--bank` VARIANTS. Both normalise to the full mode before
#     the first leg; their own narrowing is `test_loop_scope.sh`'s.
#   * THE PYTEST-X2 UNIT RUN END TO END. `case_leg_pytest_x2_takes_a_slot` and
#     `case_a_shard_forces_the_partition_to_measure_and_banks_nothing` read the
#     WIRING at derived line numbers rather than running the unit, because
#     running it is the whole suite twice inside the selftest leg of a gate that
#     has already run it once. The dynamic half is every real full gate's own
#     transcript (the `pytest slot` line, the partition's decision line).
#   * WHETHER THE REGISTERED POPULATION IS THE RIGHT ONE. The drive reads
#     `selftest_registered_drives` out of `scripts/check.sh` rather than
#     re-deriving it, so the two sides can no longer drift — but a drive file
#     that exists in the tree and is registered NOWHERE is invisible to both
#     sides alike, and no case here can see it. The instrument census
#     (`--census`) is what asks whether a file in the tree owns a row.
#   * WHETHER ONE PASS IS ENOUGH. The `--passes 1` cases below assert that
#     the leg runs ONE pass, says so, and exits pass 1's own
#     status. Whether the belt it dropped is actually being carried somewhere
#     — the acceptance box's whole-suite two passes under one seed, and the
#     `leak-proof=` field that composes them into the row — is `gate_ledger.sh`
#     and `pm_push.sh`'s, and is asserted in their own drives.
#     A green here is a green about the FLAG, never about the proof.
#   * WHAT A ONE-PASS SHARD LEFT BEHIND. `own-tree-census` runs after the one
#     pass here exactly as it does after two, and the cases assert that it
#     still brackets the suite — not that a second pass would have found
#     nothing. That is the proof's job by construction now, and nothing in this
#     file can see it.
#   * THE SEAM PAST THE BANNER. `composed-of: …,pytest-x2/1,…` is asserted as a
#     string this gate PRINTS. Whether a composition downstream parses the
#     `<leg>[/<passes>]` grammar — `pm_push.sh`'s union of the shard logs
#     against the listing, which today knows only the bare leg name — is that
#     script's own drive, and until the bank's plan is taught the flag no
#     caller in this tree hands `--passes 1` at all.
#   * THE SHARD CENSUS IS OVER THE COLLECTION, NOT OVER THE RUN. The three-N,
#     two-seed census below compares `--collect-only` node ids; the composed
#     xdist half is driven for real at `-n 2`, but over TWO apps-root modules
#     rather than the whole suite. What is therefore not covered: a split that
#     composes differently with xdist at a collection size or a worker count
#     this target does not reach.
#   * WHETHER THE DURATIONS ARE ANY GOOD. The census proves a stale or absent
#     file cannot move the PARTITION. How BALANCED the groups are is a wall-clock
#     question the unit's own trigger owns, not a correctness one.
#   * A DURATIONS FILE THE GATE WOULD NEVER HAND OVER. `--durations-path` is
#     bound to pytest's rootdir and anything outside it is refused (exit 2
#     naming both, `gate_durations_path`), because an outside path makes
#     `pytest-split` COLLAPSE the partition silently — measured by V-G10 as a
#     3-way split of 3,822 items coming back as 3, 3 and 1, with no warning and
#     exit 0. The refusal is driven; what is NOT covered is the collapse itself,
#     which is the plugin's behaviour and not ours, and which the refusal exists
#     so that no shard of ours can ever be in.
#   * WALL TIME AS AN ASSERTION, except for `--list-legs` itself, where "fast
#     and bare" is the property: 5 s on a loaded shared box is a generous
#     ceiling for a run that reads one file, and it is the criterion's own.
set -euo pipefail

cd "$(dirname "$0")/../.."

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_list_legs: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh
DRIVE_OPTED_IN_TO_FINISH=1

PASSED=0
FAILED=0
CURRENT=""
ok() {
    echo "  ok       ${CURRENT} — $1"
    PASSED=$((PASSED + 1))
}
bad() {
    echo "  FAILED   ${CURRENT} — $1"
    FAILED=$((FAILED + 1))
}
cannot_look() {
    echo "!! test_list_legs: $*" >&2
    echo "   Nothing was asserted. A driver that could not run its cases has not" >&2
    echo "   cleared them." >&2
    exit 2
}

case "${1:-}" in
"") ;;
--list)
    grep -n '^case_[A-Za-z0-9_]*() {' "$0" | sed 's/() {.*//; s/^/  /'
    exit 0
    ;;
*)
    echo "!! unknown argument '$1': test_list_legs.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

command -v git >/dev/null 2>&1 || cannot_look "no git on PATH"
[ -f scripts/check.sh ] || cannot_look "scripts/check.sh is not in this tree — the listing this drive exists for has no home"
grep -q '^gate_unit ' scripts/check.sh ||
    cannot_look "scripts/check.sh declares no gate_unit rows — the unit table this drive exists for is not there"
grep -q '^gate_run_body() {' scripts/check.sh ||
    cannot_look "scripts/check.sh defines no gate_run_body — the leg runner this drive exists for is not there"

ROOT="$PWD"
WORK=$(mktemp -d "${TMPDIR:-/tmp}/djb-test-listlegs.XXXXXX") || cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'rm -rf "$WORK"'

# --- THE COLLECTION FIXTURE WORLD --------------------------------------------
#
# EVERY `--collect-only` BELOW IS OVER FIFTY ITEMS THIS DIRECTORY OWNS, NOT
# OVER `apps/`. The shard census asks one question many times — do the shards
# the gate would run partition the collection — and that question is a property
# of `pytest-split`'s grouping composed with this gate's flags, not a property
# of any app. Asking it of four thousand real items cost the drive its
# `apps/` declaration, which is what made the selftest bank re-drive the whole
# of this file on every rung that touched an app.
#
# The world, what it holds and what it does not cover:
# `scripts/tests/fixtures/collection_world/install.sh`. The one census whose
# subject really IS the real tree — whether the SHIPPED durations file still
# names the suite it balances — is `scripts/tests/test_shard_census.sh`, and it
# declares `apps/` for exactly that reason.
COLLECTION_WORLD_DIR="${ROOT}/scripts/tests/fixtures/collection_world"
[ -r "${COLLECTION_WORLD_DIR}/install.sh" ] ||
    cannot_look "scripts/tests/fixtures/collection_world/install.sh is not in this tree — every collection below is over that world and there is nothing to collect"
# shellcheck source=scripts/tests/fixtures/collection_world/install.sh
. "${COLLECTION_WORLD_DIR}/install.sh"
# Removed FIRST and again on every exit path: a previous run killed mid-case
# must not leave a scratch app in `apps/`, and must not have its leftovers
# counted as this run's world either.
world_uninstall "$ROOT"
drive_at_exit 'world_uninstall "$ROOT"'
world_install "$ROOT" ||
    cannot_look "could not install the collection fixture world into ${ROOT}/apps"

# The pytest target, DERIVED from the world and not typed: the scratch apps it
# ships plus the apps-root modules it ships. A world that grew a fifth app is
# collected on the day it lands.
WORLD_TARGET=""
for world_label in $(world_labels); do
    WORLD_TARGET="${WORLD_TARGET} apps/${world_label}"
done
for world_root_module in "${COLLECTION_WORLD_DIR}"/apps_root/test_*.py; do
    WORLD_TARGET="${WORLD_TARGET} apps/$(basename "$world_root_module")"
done
WORLD_TARGET="${WORLD_TARGET# }"

#: THE FLOOR THAT MAKES A GREEN MEAN SOMETHING. Every union, every partition and
#: every disjointness assertion below is vacuously true over an empty or nearly
#: empty collection, and an uninstalled world collects nothing while every case
#: goes green. So a collection this drive reads is refused unless it holds at
#: least this many items — `case_an_empty_fixture_world_is_could_not_look`
#: drives the refusal by removing one of the world's four apps.
#:
#: THE NUMBER IS DERIVED FROM THE WORLD, not chosen: the world collects 57
#: items and its SMALLEST app carries 10 of them, so a floor anywhere in
#: 48..57 fails when any one app of the four goes missing and passes when all
#: four are there. Fifty is that window with room for the world to lose a
#: module without the floor becoming the thing that reds. (56 until
#: 2026-09-21, when a fifth apps-root module joined the world to match the
#: `apps_root_modules` floor — see world_install's header.)
WORLD_FLOOR=50

#: AND THE FLOOR FOR A DELIBERATELY NARROWED COLLECTION, which is a different
#: number for a different claim. `case_the_shards_partition_the_pr_scope_too`
#: asks its question of the `--pr` SELECTION, not of the world: one app in
#: scope plus the always-on set is 40 of the 56 today, and the case's own
#: assertion is that something was deselected. What this floor refuses is the
#: narrowing that deselected nearly everything, where the union would be
#: trivially equal again.
WORLD_NARROWED_FLOOR=10

# --- THE FIXTURE: the three sequences, read off 1c4c589a's flow ---------------
#
# Space-joined, in announcement order, NOT de-duplicated: `temporal-census` is
# announced twice on the full path (before and after the suite) and a fixture
# that collapsed it would stop noticing if one of the two were dropped.
#
# AND AGAIN, DELIBERATELY (2026-09-15, G10). `collectstatic` BECAME A LEG. It
# was a step in `.github/workflows/ci.yml`, which that file's own header named
# as "the one candidate to fold into check.sh"; once CI runs UNITS, a YAML step
# conditioned on which unit is running would be CI typing a leg name. It is
# announced on the FULL path only — below the `--loop` block's own exit — so the
# full sequence gained `collectstatic` after `fe` (23 unique names → 24) and the
# `--loop` sequence is unchanged. Same licence as the paragraph above: a rung
# that changes the transcript ON PURPOSE re-captures and says so here.
FIXTURE_FAST="ruff mypy import-linter djb-checks house-rules migrations goalpost-census queue-index db-pin archaeology adr-census dangling-docs loop-names ci-env"
# `always-on` sits between the secret scan and pytest, and it is a `--loop`
# name only: its members are every one of them already run by the full gate
# (a full-only leg, or a drive inside the selftest leg), so announcing it on
# the full path would be one leg running another leg's members under a second
# name. Its call site is INDENTED inside the `--loop` block, which is what
# keeps it out of `FULL_LEGS` and out of the fixture below.
FIXTURE_LOOP="${FIXTURE_FAST} deploy-check fe secrets always-on pytest"
FIXTURE_FULL="${FIXTURE_FAST} deploy-check fe collectstatic supply-chain temporal-census partition pytest-x2 temporal-census own-tree-census selftest full-house-rules"

# clone_into <dir> — a scratch checkout of this repository. `--shared` keeps it
# cheap; `--no-hardlinks` keeps a plant in the clone out of the real object
# store. The clone has no `.venv` and no `.env`, which is exactly the bareness
# the `--list-legs` speed case needs.
clone_into() {
    local sha have
    git clone --quiet --shared --no-hardlinks "$ROOT" "$1" >/dev/null 2>&1 ||
        cannot_look "could not clone this checkout into $1 — every case below plants in a clone"
    # THE CLONE ENDS UP WITH A LOCAL `main` AT THE SOURCE'S `main` SHA WHETHER OR
    # NOT IT ARRIVED WITH ONE, and `--loop`'s scope derivation refuses (exit 2,
    # could-not-look) without one — correctly: an underived scope is not an empty
    # one. The sha is the one this checkout was cut from, which is the first of
    # the two legal moves the refusal itself prints (`scripts/verify_start.sh`
    # does the same thing at clone time).
    #
    # WHETHER OR NOT IT ARRIVED WITH ONE is the whole of the branch below, and it
    # cost a bank. `git clone` checks out the SOURCE's HEAD branch, so a clone of
    # a checkout on a rung branch — every `--loop` and every verifier clone this
    # drive has ever been measured in — has no local `main` and the create is the
    # only move. A clone of a checkout ON `main` — the primary, which is where
    # the merge train's bank runs the full gate — arrives WITH one, `branch main`
    # fails "already exists", and the drive read that as no fork point and took
    # the whole gate to exit 2 (BANK-3, 2026-09-16). An arrived `main` is
    # ASSERTED, never forced: `branch -f` would silently move a branch this drive
    # did not create, and the assertion is what would say so.
    sha=$(git -C "$ROOT" rev-parse --verify -q main 2>/dev/null || git -C "$1" rev-parse HEAD)
    if have=$(git -C "$1" rev-parse --verify -q main 2>/dev/null); then
        [ "$have" = "$sha" ] ||
            cannot_look "the clone in $1 arrived with a local main at ${have} — this checkout's main is ${sha}, so --loop's scope would fork from a tree this drive did not choose"
    else
        git -C "$1" branch main "$sha" >/dev/null 2>&1 ||
            cannot_look "could not create a local main in $1 — --loop's scope has no fork point there"
    fi
}

# clone_borrows_interpreter <clone> — lend the clone THIS checkout's `.venv`.
#
# WHY A CLONE NEEDS ONE AT ALL, and it is not obvious: `--list-legs` reads one
# file and prints, so most clones here need no interpreter and the bare-clone
# case ASSERTS they have none. But a `--loop` — even a DRY one, whose every leg
# body is switched off — derives its SCOPE before the first leg, and the scope
# walks `depends_on` by reading the app declarations with
# `$LOOP_TIER_ROOT/.venv/bin/python` (`scripts/loop_tier.sh`,
# `loop_scope__python`). `LOOP_TIER_ROOT` is the CLONE, a clone has no `.venv`,
# and the derivation refuses — exit 2, could-not-look, correctly, because an
# underived closure is not an empty one.
#
# WHY IT WAS INVISIBLE UNTIL A BANK PAID FOR IT. The refusal only fires when
# there is something to CLASSIFY: a clone of a checkout sitting on `main` has no
# changed files at all, so the closure is never walked and the dry run is green
# — which is the shape the primary's bank is in. A clone of a RUNG WORKTREE
# ahead of `main` by an `apps/` path does have one, and refuses. Reproduced from
# P6's full gate, 2026-09-16, as `a dry 'check.sh --loop' exited 2 — the
# sequence census has no subject`; and a rung ahead of main by `scripts/` alone
# is green too (that shape derives FULL and walks no closure), which is why this
# drive's own worktree never showed it.
#
# A SYMLINK, AND NOT A `uv sync`. The clone is this tree at this lockfile, so
# the source's interpreter is the right one by construction and the alternative
# is provisioning a whole venv per clone inside the selftest leg. It is NOT done
# inside `clone_into`, because `case_list_legs_needs_no_venv_no_docker_and_is_fast`
# asserts a clone arrives WITHOUT one and that assertion is the case's subject:
# a clone borrows an interpreter where a case needs a scope derived, and nowhere
# else.
clone_borrows_interpreter() {
    local dir=$1
    [ -x "${ROOT}/.venv/bin/python" ] ||
        cannot_look "this checkout has no .venv/bin/python to lend — the dry --loop's scope derivation cannot be given an interpreter (run ./scripts/setup.sh)"
    [ -e "${dir}/.venv" ] && return 0
    ln -s "${ROOT}/.venv" "${dir}/.venv" ||
        cannot_look "could not lend ${dir} this checkout's interpreter"
    return 0
}

# run_listing <checkout> [extra args] — run --list-legs there, capture output
# and status into LIST_OUT / LIST_RC.
LIST_OUT=""
LIST_RC=0
run_listing() {
    local dir=$1
    shift
    LIST_OUT="${WORK}/listing.out"
    LIST_RC=0
    (cd "$dir" && ./scripts/check.sh --list-legs "$@") >"$LIST_OUT" 2>&1 || LIST_RC=$?
    listing_floor
}

# run_listing_here — `--list-legs` ON THIS CHECKOUT, taken once and shared.
#
# EIGHT CASES ASKED FOR IT and every one of them got a fresh `./scripts/check.sh
# --list-legs` over an unchanging tree: eight identical answers, seven of them
# paid for twice. The PLANTED listings above keep their own runs — each is a
# different tree and a memo keyed on anything but the plant would be the
# apps-root census defect one directory over — so the sharing is named here and
# nowhere else.
LISTING_HERE_READY=""
LISTING_HERE_OUT=""
LISTING_HERE_RC=0
run_listing_here() {
    if [ -n "$LISTING_HERE_READY" ]; then
        LIST_OUT="$LISTING_HERE_OUT"
        LIST_RC="$LISTING_HERE_RC"
        listing_floor
        return 0
    fi
    LISTING_HERE_OUT="${WORK}/listing-here.out"
    LIST_OUT="$LISTING_HERE_OUT"
    LIST_RC=0
    (cd "$ROOT" && ./scripts/check.sh --list-legs) >"$LIST_OUT" 2>&1 || LIST_RC=$?
    LISTING_HERE_RC="$LIST_RC"
    LISTING_HERE_READY=1
    listing_floor
}

# THE CAPTURE FLOOR. `--list-legs` writes its refusals to the same file, so an
# EMPTY listing is the one state in which every `awk`, `grep -c` and
# `case ,$legs,` below answers "not there" without looking. The shared shape is
# `drive_capture_refusal` (drive_preamble.sh section 7); the voice is this
# drive.
listing_floor() {
    local why
    why="$(drive_capture_refusal "${CURRENT:-a listing}" "${LIST_OUT:-}" "${LIST_RC:-<none>}")" &&
        cannot_look "$why"
    return 0
}

# dry_sequence <mode...> — the leg names a mode announces, space-joined, with
# every body switched off.
#
# IN A CLONE, AND FOR TWO REASONS. The per-checkout gate lock refuses a nested
# `./scripts/check.sh`, and this drive runs INSIDE the selftest leg of a real
# gate — so a dry run in this checkout would go red for the lock and not for
# the property. And the lease is pointed at a scratch directory because a dry
# run still takes it (it lives outside the legs): a drive that queued behind
# somebody else's real full gate would be a drive holding the machine.
# MADE ONCE, AND NOT INSIDE THE FUNCTION: every caller reads this through a
# command substitution, which is a subshell, so a clone created lazily in here
# would be re-cloned on every call into a directory that already exists.
DRY_CLONE="${WORK}/dry-clone"
clone_into "$DRY_CLONE"
# THE DRY `--loop` DERIVES A SCOPE BEFORE ITS FIRST LEG, and a scope needs an
# interpreter. See `clone_borrows_interpreter` for what that cost and why the
# shape hid until a bank was in it.
clone_borrows_interpreter "$DRY_CLONE"
mkdir -p "${WORK}/lease"

# MEMOISED PER MODE, and the mode is the key. A dry run announces legs and runs
# no body, so two dry runs of one mode over one clone are two identical answers
# — and the bare mode and `--loop` were each asked for twice. The transcript
# file is per mode too (`dry-full.out`, `dry--loop.out`), because
# `case_the_full_fast_and_loop_leg_sequences_are_unchanged_by_the_refactor`
# greps the BARE run for its own "banks no verdict" line and a single shared
# `dry.out` would hand it whichever mode ran last.
#
# THE MEMO IS A FILE ON DISK rather than a shell variable: every caller reads
# this through `$(dry_sequence …)`, which is a subshell, so a variable set
# inside one is gone with it — the same reason `DRY_CLONE` is made outside the
# function.
dry_out_for() {
    local mode="${1:-full}"
    printf '%s/dry-%s.out' "$WORK" "$(printf '%s' "$mode" | tr -c 'a-zA-Z0-9' '_')"
}
# WHY A DRY RUN TYPES `DJB_LOOP_HERE`, and it is the defect A2.5 was sent to
# find rather than a convenience. `scripts/check.sh` refuses a `--loop` on a
# machine that is not a verifier box, and EXEMPTS CI — `elif [ -n "${CI:-}" ]`,
# right beside the valve. `drive_preamble.sh` §4 STRIPS `CI` and
# `GITHUB_ACTIONS` from every drive's environment, for its own good reason (a
# case whose verdict depends on who started it is not a case). The two are
# correct separately and fatal together: on a GitHub runner this drive's child
# `check.sh --loop` no longer sees `CI`, the exemption does not fire, and the
# dry run exits 2 before a single leg is announced. That is the whole of the
# template's own `selftest 2/3` red on 2026-09-21 (run 35599531093), and it
# reproduces on a laptop for the same reason — the strip is the machine, not
# the runner.
#
# THE VALVE IS THE RIGHT ANSWER AND NOT A WORKAROUND. What the refusal protects
# is the machine's minutes: a `--loop` runs every leg body and the boxes exist
# to carry them. A DRY run announces the legs and runs NO body — it is the one
# population the refusal is not about — and the valve's own grammar
# (`<who>: <why>`) is where that is said out loud, printed in the banner and
# recorded beside the verdict. `DJB_LOOP_HERE` is the preamble's declared
# doctrine applied at the case: a drive whose subject turns on an environment
# pins it itself.
DRY_LOOP_HERE="test_list_legs: a DRY sequence census — every leg body is switched off, nothing is measured"

# THE REFUSAL'S OWN LINES, IN THIS DRIVE'S OUTPUT. A path under `/tmp` on a
# runner is a path nobody will ever open: the machine is gone before anybody
# reads the log, and "see /tmp/djb-test-listlegs.FeD6jA/dry-__loop.out" cost a
# whole cycle of not knowing why CI was red. So the capture's own refusal is
# lifted into the transcript and the path is kept beside it for a laptop.
dry_capture_lines() {
    local out="$1" lines
    [ -s "$out" ] || {
        printf '   (the capture is empty — the run printed nothing at all)\n'
        return 0
    }
    lines="$(grep -nE '^(!!|Error|error:|cause:)' "$out" | head -20 || true)"
    if [ -z "$lines" ]; then
        # No refusal banner: the last lines are the closest thing to a cause.
        printf '   no `!!` line in the capture; its last 20 lines:\n'
        tail -20 "$out" | sed 's/^/   | /'
        return 0
    fi
    printf '   the capture says:\n'
    printf '%s\n' "$lines" | sed 's/^/   | /'
    # A refusal's argument is the lines under its banner, and they are what
    # says which valve fired; the banner alone reads like six other refusals.
    printf '   and the first refusal in full:\n'
    awk '/^!!/{on=1} on{print; n++} n>=18{exit}' "$out" | sed 's/^/   | /'
}

dry_sequence() {
    local out rc=0
    out="$(dry_out_for "${1:-full}")"
    if [ ! -s "$out" ]; then
        (
            cd "$DRY_CLONE" &&
                DJB_GATE_LEGS_DRY=1 \
                    DJB_GATE_LEASE_DIR="${WORK}/lease" \
                    DJB_LOOP_HERE="$DRY_LOOP_HERE" \
                    DJB_GATE_SANCTION="test_list_legs: the dry sequence census — every leg announced, no body run" \
                    ./scripts/check.sh "$@"
        ) >"$out" 2>&1 || rc=$?
        if [ "$rc" != "0" ]; then
            dry_capture_lines "$out" >&2
            cannot_look "a dry \`check.sh $*\` exited ${rc} — the sequence census has no subject (the capture is printed above; on a laptop it is also at ${out})"
        fi
        [ -s "$out" ] ||
            cannot_look "a dry \`check.sh $*\` exited 0 and printed nothing — the sequence census would read an empty capture as a mode that announces no legs"
    fi
    sed -n 's/^  leg: \([a-z0-9-]*\) (DJB_GATE_LEGS_DRY.*/\1/p' "$out" | tr '\n' ' ' | sed 's/ $//'
}

# --- the cases ---------------------------------------------------------------

case_an_empty_capture_is_could_not_look() {
    # THE FLOOR UNDER EVERY LISTING READER, SHOWN FIRING. `--list-legs` writes
    # its refusals into the same file every case then reads, so an EMPTY
    # capture is the one state in which `awk -F'\t'`, `grep -c` and
    # `case ,$legs,` all answer "not there" without looking — and several of
    # those readings are negatives that print `ok` for it. The plant is the way
    # a refactor makes one: the variable emptied, in a SUBSHELL, which does not
    # run this shell EXIT trap.
    local out="${WORK}/empty-capture.log" rc=0
    CURRENT="an emptied listing capture is could-not-look"
    (
        CURRENT="a planted case"
        LIST_OUT=""
        LIST_RC=0
        listing_floor
        echo "listing_floor returned instead of refusing"
    ) >"$out" 2>&1 || rc=$?
    if [ "$rc" != "2" ]; then
        bad "an emptied listing capture exited ${rc}, not 2 — a reader that answers a question it could not look at is what this floor exists to stop"
        return
    fi
    if ! grep -qF 'capture with no path at all' "$out"; then
        bad "exit 2, but the refusal never names the capture: $(sed -n 1p "$out")"
        return
    fi
    ok "exit 2, naming the capture and the exit code of the run that did not fill it"

    CURRENT="a listing with bytes in it is judged, not refused"
    printf 'unit\tneeds\tshards\tlegs\n' >"${WORK}/non-empty-listing.out"
    rc=0
    (
        CURRENT="a planted case"
        LIST_OUT="${WORK}/non-empty-listing.out"
        LIST_RC=2
        listing_floor
    ) >"$out" 2>&1 || rc=$?
    if [ "$rc" = "0" ]; then
        ok "a listing with bytes in it passes the floor whatever its status — the floor is about the capture, not the verdict"
    else
        bad "a readable listing was refused with ${rc}: $(sed -n 1p "$out")"
    fi
}

case_the_full_fast_and_loop_leg_sequences_are_unchanged_by_the_refactor() {
    # G9.1. The transcript is the same transcript: each mode announces the same
    # legs, in the same order, as it did before every body moved into a
    # function. The fixture is this tree's baseline (see the header).
    local got

    CURRENT="--fast announces the baseline's legs, in order"
    got=$(dry_sequence --fast)
    if [ "$got" = "$FIXTURE_FAST" ]; then
        ok "$(printf '%s' "$got" | wc -w | tr -d ' ') legs: ${got}"
    else
        bad "the --fast sequence moved
    fixture: ${FIXTURE_FAST}
    got:     ${got}"
    fi

    CURRENT="--loop announces the baseline's legs, in order"
    got=$(dry_sequence --loop)
    if [ "$got" = "$FIXTURE_LOOP" ]; then
        ok "$(printf '%s' "$got" | wc -w | tr -d ' ') legs: ${got}"
    else
        bad "the --loop sequence moved
    fixture: ${FIXTURE_LOOP}
    got:     ${got}"
    fi

    CURRENT="the full gate announces the baseline's legs, in order"
    got=$(dry_sequence)
    if [ "$got" = "$FIXTURE_FULL" ]; then
        ok "$(printf '%s' "$got" | wc -w | tr -d ' ') legs (temporal-census twice, as it is announced): ${got}"
    else
        bad "the full sequence moved
    fixture: ${FIXTURE_FULL}
    got:     ${got}"
    fi

    CURRENT="a dry run banks no verdict"
    if grep -q 'no verdict recorded — DJB_GATE_LEGS_DRY' "$(dry_out_for full)"; then
        ok "the full tail says so in its own words — a run that judged nothing leaves no row"
    else
        bad "a dry full run reached the end without saying it banked nothing"
    fi
}

case_an_announced_leg_whose_body_is_not_behind_the_runner_is_exit_2() {
    # RIDER (5), from the field test that planted it. An INDENTED `leg` whose
    # body sits inline is announced by the gate on every run and is invisible to
    # BOTH censuses: the listing reads column-zero call sites, and the dry
    # sequence reads the runner's own line, which such a leg never reaches. So
    # the gate says it ran a leg, no verdict row names it, and no runner is ever
    # handed it. The pairing census reads EVERY indent.
    local plant="${WORK}/plant-inline"
    CURRENT="an indented leg whose body is not behind gate_run_body"
    clone_into "$plant"
    python3 - "$plant/scripts/check.sh" <<'PY_PLANT'
import sys
p = sys.argv[1]
src = open(p).read().split("\n")
for i, line in enumerate(src):
    if line.startswith("leg full-house-rules "):
        # INDENTED, and its body inline — the exact shape the field test planted.
        src.insert(i, '    leg zzz-inline "an indented leg whose body is inline"')
        src.insert(i + 1, '    echo "  zzz-inline ran"')
        break
else:
    raise SystemExit("no full-house-rules leg to plant beside")
open(p, "w").write("\n".join(src))
PY_PLANT
    run_listing "$plant"
    if [ "$LIST_RC" = "2" ] && grep -q 'zzz-inline' "$LIST_OUT"; then
        ok "exit 2, naming zzz-inline: $(sed -n 1p "$LIST_OUT" | cut -c1-80)"
    else
        bad "an announced leg with no runner gave exit ${LIST_RC}: $(sed -n 1p "$LIST_OUT")"
    fi
    rm -rf "$plant"
}

case_full_legs_equals_the_announced_full_sequence() {
    # G9.2. Both sides derived: FULL_LEGS out of the file, the announced
    # sequence out of a RUN of the full mode with the bodies off. De-duplicated
    # on first appearance, because `temporal-census` is one leg announced twice
    # and the ledger's string names legs.
    local full_legs announced seen="" leg
    CURRENT="FULL_LEGS equals the legs a full run announces"
    full_legs=$(sed -n 's/^FULL_LEGS=//p' scripts/check.sh | sed -n 1p)
    if [ -z "$full_legs" ]; then
        bad "scripts/check.sh has no FULL_LEGS line — the string every verdict row carries is gone"
        return 0
    fi
    for leg in $(dry_sequence); do
        case ",${seen}," in
        *",${leg},"*) ;;
        *) seen="${seen}${seen:+,}${leg}" ;;
        esac
    done
    announced=$seen
    if [ "$announced" = "$full_legs" ]; then
        ok "$(printf '%s' "$announced" | tr ',' '\n' | grep -c .) names, identical on both sides"
    else
        bad "the string and the run disagree
    FULL_LEGS: ${full_legs}
    announced: ${announced}"
    fi

    CURRENT="and the listing derives the same sequence statically"
    run_listing_here
    if [ "$LIST_RC" = "0" ]; then
        ok "--list-legs exits 0 on this tree, which is the static half of the same comparison"
    else
        bad "--list-legs exits ${LIST_RC} on this tree: $(sed -n 1p "$LIST_OUT")"
    fi
}

case_an_announced_leg_missing_from_full_legs_is_exit_2() {
    # G9.2's refusal. A leg call site at column zero that FULL_LEGS has never
    # heard of is the exact defect six legs carried: announced on every run,
    # named on no verdict row.
    local plant="${WORK}/plant-announced"
    CURRENT="a planted leg call site the string does not know about"
    clone_into "$plant"
    # The plant is a leg the gate would announce, spelled in a clone only. It
    # goes immediately before the `full-house-rules` leg so the file still parses.
    python3 - "$plant/scripts/check.sh" <<'PY'
import sys
p = sys.argv[1]
src = open(p).read().split("\n")
for i, line in enumerate(src):
    if line.startswith("leg full-house-rules "):
        src.insert(i, 'leg zzz-probe "a probe leg no verdict row has ever named"')
        src.insert(i + 1, "gate_run_body zzz-probe gate_leg_full_house_rules")
        break
else:
    raise SystemExit("no full-house-rules leg to plant beside")
open(p, "w").write("\n".join(src))
PY
    run_listing "$plant"
    if [ "$LIST_RC" = "2" ] && grep -q 'zzz-probe' "$LIST_OUT"; then
        ok "exit 2, naming zzz-probe: $(grep -m1 'announced:' "$LIST_OUT" | cut -c1-72)…"
    else
        bad "a leg the string never heard of gave exit ${LIST_RC}: $(sed -n 1p "$LIST_OUT")"
    fi
    rm -rf "$plant"
}

# --- THE REGISTERED DRIVE POPULATION, READ FROM ITS ONE WRITER ---------------
#
# THREE CASES BELOW COMPARE THE LISTING'S `selftest` ROW AGAINST "the drives
# this gate registers", AND THEY USED TO RE-DERIVE THAT POPULATION with a
# `^\./scripts/tests/test_*.sh$` sed of their own. `scripts/check.sh` has one
# writer for it — `selftest_registered_drives` — and that writer widened to a
# NAMED PATH under `deploy/` (`./deploy/tests/test_stage.sh`, whose member is
# `stage`). The sed could not see a path it had no glob for, so the
# drive's answer and the gate's answer disagreed by exactly that member and
# three cases went red on a tree with nothing wrong with it:
#
#   FAILED  the listing's selftest row names every registered drive, once
#           — the registered order and the listing's selftest row disagree
#
# That is a population derived TWICE, which is the defect these cases exist to
# catch one level up. So the drive now READS THE WRITER: the function is
# extracted from `scripts/check.sh` and run, exactly as `gate_fn` does for the
# leg bodies, and a widening in the gate reaches every case here without an
# edit. `case_the_registered_population_has_one_writer` drives both directions.
#
# registered_drives_in <checkout> — that checkout's own registered drive names,
# one per line, in the gate's own order. Safe in a command substitution: the
# source happens inside its own subshell, so nothing leaks into this shell.
registered_drives_in() {
    local dir=$1 out
    out="${WORK}/fn-registered-$(printf '%s' "$dir" | tr -c 'A-Za-z0-9' '_').sh"
    awk -v want="selftest_registered_drives() {" '
        index($0, want) == 1 { on = 1 }
        on { print }
        on && $0 == "}" { exit }
    ' "${dir}/scripts/check.sh" >"$out"
    grep -q '^selftest_registered_drives() {' "$out" ||
        cannot_look "${dir}/scripts/check.sh no longer defines selftest_registered_drives() — the registered population has no writer to read"
    grep -q '^}$' "$out" ||
        cannot_look "the selftest_registered_drives() definition in ${dir}/scripts/check.sh has no closing brace at column 1 — the extraction cannot be trusted"
    (
        cd "$dir" || exit 2
        # shellcheck disable=SC1090  # the extracted definition, by design
        . "$out"
        selftest_registered_drives
    )
}

REGISTERED_DRIVES=$(registered_drives_in "$ROOT")
[ -n "$REGISTERED_DRIVES" ] ||
    cannot_look "selftest_registered_drives names no drive in this checkout — every population case below would be green over nothing"

# THE GATE'S OWN DEFAULT FOR THE PASS-COUNT PHRASE, READ RATHER THAN TYPED.
# `gate_pytest_split_args` prints it, and the two harnesses below extract that
# function WITHOUT the gate's file-scope assignments — so under `set -u` it is
# an unbound variable and the case reds for the harness rather than for the
# property. Set here, at the drive's own file scope, so every subshell inherits
# it; read out of `scripts/check.sh` so the DEFAULT wording still has exactly
# one writer, which is the whole point of the variable existing.
GATE_PASSES_CARRY=$(sed -n 's/^GATE_PASSES_CARRY="\(.*\)"$/\1/p' "${ROOT}/scripts/check.sh" | sed -n 1p)
[ -n "$GATE_PASSES_CARRY" ] ||
    cannot_look "scripts/check.sh no longer assigns GATE_PASSES_CARRY at column zero — the split line's phrasing has no default to stand in for"

case_the_registered_population_has_one_writer() {
    # THE READER FOLLOWS THE WRITER, IN BOTH DIRECTIONS. Two plants and one
    # negative, because "the drive reads the gate" is only worth anything if a
    # change in the gate MOVES the drive's answer and a genuine disagreement
    # still reds.
    local plant derived narrowed listed
    CURRENT="the derived population carries the member the old glob could not see"
    # DERIVED FROM THE WRITER, NOT TYPED: a member the OLD glob could not see
    # is one the gate does not register as `./scripts/tests/test_<name>.sh`,
    # and that question is asked of `scripts/check.sh` — the file this drive
    # already declares and already keys on — rather than of the directory.
    # Probing the filesystem would make this drive's body spell a path it does
    # not drive, which the drive-key floor refuses (`gate_ledger.sh`'s
    # `drive__uncovered`); asking the gate is also the more honest question,
    # because registration is what the population IS. Naming `stage` here
    # would be the same hand list one level down.
    derived=$(printf '%s\n' "$REGISTERED_DRIVES" | while IFS= read -r d; do
        [ -n "$d" ] || continue
        # A FILE ARGUMENT, NOT A PIPELINE TAIL: a quiet reader with a producer
        # behind it SIGPIPEs that producer and reports the wrong answer over
        # 64 KiB (`test_sweep.sh`'s `quiet_tail_guard`). Handed a file there is
        # nothing to strangle, which is that guard's own declared negative.
        grep -qxF "./scripts/tests/test_${d}.sh" "${ROOT}/scripts/check.sh" || printf '%s\n' "$d"
    done)
    if [ -n "$derived" ]; then
        ok "$(printf '%s' "$derived" | tr '\n' ' ')— registered by the gate under a path the old glob had no shape for"
    else
        bad "every registered drive is registered as ./scripts/tests/test_<name>.sh — this case is green over a widening that is not there, and the reader could still be a second derivation"
    fi

    CURRENT="and a writer that narrows takes the drive's answer with it"
    plant="${WORK}/plant-writer-narrowed"
    rm -rf "$plant"
    clone_into "$plant"
    python3 - "$plant/scripts/check.sh" <<'PY_NARROW'
import sys
p = sys.argv[1]
src = open(p).read().split("\n")
keep, cut, inside = [], 0, False
for line in src:
    if line.startswith("selftest_registered_drives() {"):
        inside = True
    elif inside and line == "}":
        inside = False
    # The arm is an awk ERE inside a shell single-quoted string, so the path is
    # written with escaped slashes (`\.\/deploy\/tests\/...`). Matching on the
    # bare path finds nothing, which is a plant that cuts nothing and a case
    # green over a narrowing that never happened.
    if inside and "deploy" in line.replace("\\", "") and "tests" in line.replace("\\", ""):
        cut += 1
        continue
    keep.append(line)
if cut == 0:
    raise SystemExit("no non-scripts/tests arm in the writer to narrow")
open(p, "w").write("\n".join(keep))
PY_NARROW
    narrowed=$(registered_drives_in "$plant")
    run_listing "$plant"
    listed=$(awk -F'\t' '$1 == "selftest" { print $4 }' "$LIST_OUT" | tr ',' '\n' | grep -v '^selftest$' || true)
    if [ "$LIST_RC" != "0" ]; then
        bad "the narrowed writer's listing exits ${LIST_RC}: $(sed -n 1p "$LIST_OUT")"
    elif [ "$(printf '%s\n' "$narrowed" | LC_ALL=C sort)" != "$(printf '%s\n' "$listed" | LC_ALL=C sort)" ]; then
        bad "the narrowed writer's two sides disagree
    reader:  $(printf '%s' "$narrowed" | tr '\n' ' ')
    listing: $(printf '%s' "$listed" | tr '\n' ' ')"
    # THE READER RUNS TO EOF. A `grep -q` at the tail of a pipeline exits on
    # its first match and SIGPIPEs the producer, which under `pipefail` reports
    # the wrong answer for every stream over the pipe buffer — the house form
    # is a full-stream reader (`test_sweep.sh`'s `quiet_tail_guard`, which reds
    # on the shape wherever it appears).
    elif printf '%s\n' "$narrowed" |
        awk -v want="$(printf '%s\n' "$derived" | sed -n 1p)" '$0 == want { found = 1 } END { exit !found }'; then
        bad "the reader kept '$(printf '%s\n' "$derived" | sed -n 1p)' after the writer dropped it — it is still a second derivation"
    else
        ok "the writer dropped $(printf '%s' "$derived" | wc -w | tr -d ' ') member(s) and the reader dropped them too; the listing stays green at $(printf '%s\n' "$narrowed" | grep -c .) drive(s)"
    fi
    rm -rf "$plant"

    CURRENT="and a selftest row that DROPS a registered drive still disagrees (the negative)"
    plant="${WORK}/plant-row-short"
    rm -rf "$plant"
    clone_into "$plant"
    python3 - "$plant/scripts/check.sh" <<'PY_SHORT'
import sys
p = sys.argv[1]
src = open(p).read().split("\n")
for i, line in enumerate(src):
    if line.startswith("gate_unit selftest "):
        # The row is `$(selftest_registered_drives)`-derived; freezing it to a
        # hand list one member short is exactly the drift the comparison
        # exists to see.
        src[i] = "gate_unit selftest db,docker,temporal N-capable selftest $(selftest_registered_drives | sed '$d')"
        break
else:
    raise SystemExit("no selftest unit row to shorten")
open(p, "w").write("\n".join(src))
PY_SHORT
    narrowed=$(registered_drives_in "$plant")
    run_listing "$plant"
    # `grep -v` EXITS 1 WHEN IT MATCHES NOTHING, and a refused listing has no
    # selftest row at all — so an unguarded assignment here kills the drive
    # under `set -e` at the exact moment the plant is doing its job. Paid for
    # twice, silently, before the trace found it.
    listed=$(awk -F'\t' '$1 == "selftest" { print $4 }' "$LIST_OUT" | tr ',' '\n' | grep -v '^selftest$' || true)
    if [ "$LIST_RC" = "2" ]; then
        ok "the listing refuses it outright: $(sed -n 1p "$LIST_OUT" | cut -c1-84)"
    elif [ "$(printf '%s\n' "$narrowed" | LC_ALL=C sort)" != "$(printf '%s\n' "$listed" | LC_ALL=C sort)" ]; then
        ok "the comparison sees the gap: reader $(printf '%s\n' "$narrowed" | grep -c .) drive(s), row $(printf '%s\n' "$listed" | grep -c .)"
    else
        bad "a row one drive short compared EQUAL — the fixed reader can no longer fail, which is worse than the red it replaced"
    fi
    rm -rf "$plant"
}

case_every_full_leg_is_in_exactly_one_unit() {
    # G9.3. Union over the units == FULL_LEGS, and the units are pairwise
    # disjoint. Derived from the listing's own output, which is what any other
    # reader would be handed.
    local full_legs population seen="" leg dupes="" missing="" extra=""
    CURRENT="the units partition FULL_LEGS and the registered drive order"
    full_legs=$(sed -n 's/^FULL_LEGS=//p' scripts/check.sh | sed -n 1p)
    # THE POPULATION IS BOTH TIERS. A unit that shards by a registered
    # population names that population too, so the partition to check is over
    # the legs a full run announces PLUS the drives the selftest leg walks —
    # checking only the legs would let a drive fall out of every shard with
    # this case still green.
    population="$(printf '%s' "$full_legs" | tr ',' ' ') $(printf '%s' "$REGISTERED_DRIVES" | tr '\n' ' ')"
    run_listing_here
    if [ "$LIST_RC" != "0" ]; then
        bad "--list-legs exits ${LIST_RC}, so there is no table to judge"
        return 0
    fi
    while IFS=$'\t' read -r _unit _needs _shards legs; do
        [ -n "${legs:-}" ] || continue
        for leg in $(printf '%s' "$legs" | tr ',' ' '); do
            case " $seen " in
            *" $leg "*) dupes="${dupes}${dupes:+ }$leg" ;;
            *) seen="${seen}${seen:+ }$leg" ;;
            esac
            case " $population " in
            *" $leg "*) ;;
            *) extra="${extra}${extra:+ }$leg" ;;
            esac
        done
    done <"$LIST_OUT"
    for leg in $population; do
        case " $seen " in
        *" $leg "*) ;;
        *) missing="${missing}${missing:+ }$leg" ;;
        esac
    done
    if [ -z "$dupes" ] && [ -z "$missing" ] && [ -z "$extra" ]; then
        ok "$(printf '%s' "$seen" | wc -w | tr -d ' ') member(s) across $(grep -c . "$LIST_OUT") units, disjoint, union == FULL_LEGS + the registered drives"
    else
        bad "in two units: '${dupes}' · in no unit: '${missing}' · neither a full leg nor a registered drive: '${extra}'"
    fi
}

case_a_leg_in_two_units_is_exit_2() {
    # G9.3's refusal. A leg two runners would both be handed is not a partition
    # — it is one leg run twice and a wall nobody costed.
    local plant="${WORK}/plant-twice"
    CURRENT="a leg declared in two units"
    clone_into "$plant"
    python3 - "$plant/scripts/check.sh" <<'PY'
import sys
p = sys.argv[1]
src = open(p).read().split("\n")
for i, line in enumerate(src):
    if line.startswith("gate_unit full-house-rules "):
        src.insert(i + 1, "gate_unit zzz-second none 0 full-house-rules")
        break
else:
    raise SystemExit("no full-house-rules unit to duplicate")
open(p, "w").write("\n".join(src))
PY
    run_listing "$plant"
    if [ "$LIST_RC" = "2" ] && grep -q "more than one unit" "$LIST_OUT"; then
        ok "exit 2: $(sed -n 1p "$LIST_OUT" | cut -c1-84)"
    else
        bad "a leg in two units gave exit ${LIST_RC}: $(sed -n 1p "$LIST_OUT")"
    fi
    rm -rf "$plant"
}

case_a_leg_in_no_unit_is_exit_2() {
    # G9.3's other refusal. A leg in no unit is a leg no runner is ever handed —
    # the silent half of the CI hand-list defect, which is the one that ships.
    local plant="${WORK}/plant-orphan"
    CURRENT="a leg declared in no unit"
    clone_into "$plant"
    python3 - "$plant/scripts/check.sh" <<'PY'
import sys
p = sys.argv[1]
src = open(p).read().split("\n")
for i, line in enumerate(src):
    if line.startswith("gate_unit full-house-rules "):
        # DELETED, not re-pointed: a unit re-pointed at a leg some other unit
        # already holds is the two-units case, and that refusal fires first.
        del src[i]
        break
else:
    raise SystemExit("no full-house-rules unit to remove")
open(p, "w").write("\n".join(src))
PY
    run_listing "$plant"
    if [ "$LIST_RC" = "2" ] && grep -q "in NO unit" "$LIST_OUT"; then
        ok "exit 2: $(sed -n 1p "$LIST_OUT" | cut -c1-84)"
    else
        bad "a leg in no unit gave exit ${LIST_RC}: $(sed -n 1p "$LIST_OUT")"
    fi
    rm -rf "$plant"
}

case_a_unit_with_no_needs_declaration_is_exit_2() {
    # G9.3. `needs` is a DECLARATION (nothing reads it to decide whether to
    # bring a stack up), and an empty declaration says nothing at all — `none`
    # is a claim, blank is a gap. The listing refuses rather than print a unit
    # whose organs nobody stated.
    local plant="${WORK}/plant-needs"
    CURRENT="a unit whose needs field is empty"
    clone_into "$plant"
    python3 - "$plant/scripts/check.sh" <<'PY'
import sys
p = sys.argv[1]
src = open(p).read().split("\n")
for i, line in enumerate(src):
    if line.startswith("gate_unit full-house-rules "):
        src[i] = 'gate_unit full-house-rules "" 0 full-house-rules'
        break
else:
    raise SystemExit("no full-house-rules unit to blank")
open(p, "w").write("\n".join(src))
PY
    run_listing "$plant"
    if [ "$LIST_RC" = "2" ] && grep -q "needs/shards/legs declaration" "$LIST_OUT"; then
        ok "exit 2: $(sed -n 1p "$LIST_OUT" | cut -c1-84)"
    else
        bad "a unit with no needs gave exit ${LIST_RC}: $(sed -n 1p "$LIST_OUT")"
    fi
    rm -rf "$plant"
}

case_list_legs_prints_one_line_per_unit_in_the_grammar() {
    # G9.4. Four tab-separated fields per line: unit, needs, shards, composed-of.
    # Every field is checked as a VALUE — `needs` non-empty, `shards` one of the
    # two words the grammar allows, every composed-of leg a full leg.
    local rows bad_rows="" line unit needs shards legs leg full_legs population
    CURRENT="every line is <unit>\\t<needs>\\t<shards>\\t<composed-of>"
    full_legs=$(sed -n 's/^FULL_LEGS=//p' scripts/check.sh | sed -n 1p)
    population="$(printf '%s' "$full_legs" | tr ',' ' ') $(printf '%s' "$REGISTERED_DRIVES" | tr '\n' ' ')"
    run_listing_here
    if [ "$LIST_RC" != "0" ]; then
        bad "--list-legs exits ${LIST_RC}"
        return 0
    fi
    rows=0
    while IFS=$'\t' read -r unit needs shards legs; do
        [ -n "${unit:-}" ] || continue
        rows=$((rows + 1))
        [ -n "${needs:-}" ] || bad_rows="${bad_rows}${bad_rows:+; }${unit}: empty needs"
        case "${shards:-}" in
        0 | N-capable) ;;
        *) bad_rows="${bad_rows}${bad_rows:+; }${unit}: shards '${shards:-}' is neither 0 nor N-capable" ;;
        esac
        [ -n "${legs:-}" ] || bad_rows="${bad_rows}${bad_rows:+; }${unit}: empty composed-of"
        for leg in $(printf '%s' "${legs:-}" | tr ',' ' '); do
            case " $population " in
            *" $leg "*) ;;
            *) bad_rows="${bad_rows}${bad_rows:+; }${unit}: '${leg}' is neither a full leg nor a registered drive" ;;
            esac
        done
    done <"$LIST_OUT"
    if [ "$rows" -lt 1 ]; then
        bad "the listing printed no rows at all"
    elif [ -n "$bad_rows" ]; then
        bad "$bad_rows"
    else
        ok "${rows} unit(s), four fields each, every composed-of member a full leg or a registered drive"
    fi

    CURRENT="and the listing has no other output"
    if [ "$(grep -c . "$LIST_OUT")" = "$rows" ]; then
        ok "${rows} line(s) out, ${rows} unit(s) — a caller can read it without a filter"
    else
        bad "$(grep -c . "$LIST_OUT") non-empty line(s) for ${rows} unit(s) — something else is printing"
    fi
}

case_list_legs_needs_no_venv_no_docker_and_is_fast() {
    # G9.4. The listing is what a runner asks BEFORE it has provisioned
    # anything, so it must touch nothing below the sourced shell libraries. The
    # clone has no `.venv` and no `.env`; PATH is reduced to the shell's
    # essentials with `uv` and `docker` removed from it, so a body that reached
    # for either would not find it.
    local plant="${WORK}/plant-bare" started ended took rc=0
    CURRENT="--list-legs in a bare clone, with uv and docker off PATH"
    clone_into "$plant"
    [ -d "$plant/.venv" ] && bad "the clone has a .venv — this case is not asking what it thinks"
    started=$(date +%s)
    (
        cd "$plant" &&
            PATH="/usr/bin:/bin:/usr/sbin:/sbin" \
                ./scripts/check.sh --list-legs
    ) >"${WORK}/bare.out" 2>&1 || rc=$?
    ended=$(date +%s)
    took=$((ended - started))
    if [ "$rc" = "0" ]; then
        ok "exit 0 with no venv, no uv, no docker, no network: $(grep -c . "${WORK}/bare.out") unit line(s)"
    else
        bad "exit ${rc} in a bare clone: $(sed -n 1p "${WORK}/bare.out")"
    fi
    CURRENT="and it is fast"
    if [ "$took" -le 5 ]; then
        ok "${took}s, ceiling 5s"
    else
        bad "${took}s — over the 5s ceiling a runner's derive step is costed against"
    fi
    rm -rf "$plant"
}

case_list_legs_precedes_the_lease() {
    # G9.4's position assertion, in the A2.5/A5F.2 shape: derived line numbers,
    # never typed ones. A listing that queued behind somebody else's full gate
    # would be useless to the one caller that wants it.
    local arm lease lock
    CURRENT="the --list-legs arm is above the lease and the checkout lock"
    arm=$({ grep -n '^if \[ -n "\$GATE_LIST_LEGS" \]; then$' scripts/check.sh || true; } | sed -n '1s/:.*//p')
    lease=$({ grep -n '^    gate_lease_acquire$' scripts/check.sh || true; } | sed -n '1s/:.*//p')
    lock=$({ grep -n '^    gate_lock_acquire$' scripts/check.sh || true; } | sed -n '1s/:.*//p')
    if [ -z "$arm" ] || [ -z "$lease" ] || [ -z "$lock" ]; then
        bad "arm '${arm:-<none>}', lease '${lease:-<none>}', lock '${lock:-<none>}' — the order has lost a subject"
        return 0
    fi
    if [ "$arm" -lt "$lease" ] && [ "$arm" -lt "$lock" ]; then
        ok "arm at line ${arm}, lease at ${lease}, lock at ${lock}"
    else
        bad "the arm (line ${arm}) is not above the lease (${lease}) and the lock (${lock})"
    fi

    CURRENT="and the arm exits, so no leg can run under it"
    if awk -v start="$arm" 'NR > start && NR <= start + 12 && /^    exit "\$GATE_LIST_LEGS_RC"$/ { found = 1 }
        END { exit found ? 0 : 1 }' scripts/check.sh; then
        ok "the arm ends in \`exit \"\$GATE_LIST_LEGS_RC\"\` — the listing's own status, and nothing after it"
    else
        bad "the --list-legs arm does not exit with the listing's status"
    fi
}

case_list_legs_with_an_argument_is_exit_2() {
    # G9.4. A mistyped modifier is never a smaller listing.
    local rc=0
    CURRENT="--list-legs with a trailing word"
    ./scripts/check.sh --list-legs zzz >"${WORK}/arg.out" 2>&1 || rc=$?
    if [ "$rc" = "2" ]; then
        ok "exit 2: $(sed -n 1p "${WORK}/arg.out")"
    else
        bad "exit ${rc} — a mistyped modifier was answered with something"
    fi
}

case_an_unknown_flag_is_still_exit_2_with_the_same_sentence() {
    # G9.4. A consumer whose gate has no `--list-legs` reads THAT stderr to find
    # out, so the refusal's shape is a contract: the `!! unknown argument '<x>':`
    # prefix is byte-identical and the list of forms behind it now names
    # `--list-legs` (which is G9.6's half of the same sentence).
    local rc=0 line
    CURRENT="an unknown flag is refused in the same words"
    ./scripts/check.sh --zzz-not-a-mode >"${WORK}/unknown.out" 2>&1 || rc=$?
    line=$(sed -n 1p "${WORK}/unknown.out")
    if [ "$rc" != "2" ]; then
        bad "an unknown flag exited ${rc}, not 2"
    elif [ "${line#"!! unknown argument '--zzz-not-a-mode': check.sh takes "}" = "$line" ]; then
        bad "the refusal's prefix changed: ${line}"
    else
        ok "${line}"
    fi

    CURRENT="and the sentence names --list-legs"
    case "$line" in
    *--list-legs*) ok "a reader refused by this gate is told the mode exists" ;;
    *) bad "the refusal lists the forms and never mentions --list-legs" ;;
    esac
}

case_the_usage_header_names_the_listing() {
    # G9.6. `test_gate_lease.sh::case_the_usage_header_and_the_parser_agree` is
    # the two-way SET comparison and stays the authority; this is the one
    # direction that matters to a reader arriving at the top of the file, named
    # here so a red says which mode went missing.
    local hdr_end
    CURRENT="--list-legs is in the usage header"
    hdr_end=$(awk -v want='set -euo pipefail' '$0 == want { print NR; exit }' scripts/check.sh)
    if [ -z "$hdr_end" ]; then
        bad "check.sh has no 'set -euo pipefail' line — the header has no end"
        return 0
    fi
    # ONE `awk` READING THE FILE DIRECTLY, no pipeline: a `grep -q` at the tail
    # of a pipe kills its producer on the first match, and over the 64 KiB pipe
    # buffer `pipefail` then reports a MATCH as a failure. The header is already
    # past that size.
    if awk -v last="$hdr_end" 'NR > last { exit } /--list-legs/ { found = 1 } END { exit found ? 0 : 1 }' scripts/check.sh; then
        ok "named in the header (lines 1-${hdr_end}), which is what the parser is compared against"
    else
        bad "the parser takes --list-legs and the header never mentions it"
    fi
}

# --- the selftest leg's drive shards -----------------------------------------
#
# THE LEG BODY, DRIVEN, NEVER THE GATE AROUND IT. The text between
# `scripts/check.sh`'s `selftest-leg` sentinels is extracted and sourced — the
# shape `scripts/tests/test_selftest_leg.sh` established — into a scratch
# checkout whose every REGISTERED drive — the set `selftest_registered_drives`
# derives, however many that is today — has been replaced by an `exit 0` stub,
# and whose `uv`
# is a stub too. What is being measured is WHICH members the leg walks under a
# k/K, and a real drive set would cost twenty minutes to answer that.
SHARD_CLONE=""
SHARD_BIN=""
SHARD_FENCE=""
# THE TWO THINGS THE FENCE STANDS ON, AND WHY THEY ARE HERE NOW. The shard
# assignment is a DURATION-BALANCED partition: the leg reads the committed
# measurement through the always-on fence's own reader
# (`always_on__read_durations`) and derives its member population through
# `selftest_registered_drives`, both of which live OUTSIDE the selftest fence.
# Sourced without them the leg falls back to the index round-robin and says so
# — green, and a census of the fallback rather than of the partition the gate
# ships. The census below is the only place the partition is ever asked of the
# REAL registered order, so it sources what the gate sources.
SHARD_ALWAYS=""
SHARD_REG=""
shard_harness_build() {
    SHARD_CLONE="${WORK}/shard-clone"
    SHARD_BIN="${WORK}/shard-bin"
    SHARD_FENCE="${WORK}/shard-fence.sh"
    clone_into "$SHARD_CLONE"
    mkdir -p "$SHARD_BIN"
    printf '#!/usr/bin/env bash\nexit 0\n' >"${SHARD_BIN}/uv"
    chmod +x "${SHARD_BIN}/uv"
    local f
    # THE STUBS CARRY A `# drives:` LINE, and it is not decoration. The leg
    # refuses a drive whose key it cannot decide (exit 2, `could not key`), and
    # a marker-less stub is exactly that shape — so every stub printed a
    # refusal instead of `drive <name>: exit 0`, the member reader below saw
    # nothing, and all three shards came back holding no drives at all. The
    # subject here is the SHARD ARITHMETIC, not the key, so the stubs declare
    # one path that is in every tree and never moves inside a case.
    for f in "$SHARD_CLONE"/scripts/tests/test_*.sh; do
        printf '#!/usr/bin/env bash\n# drives: scripts/tests/drive_preamble.sh\nexit 0\n' >"$f"
        chmod +x "$f"
    done
    sed -n '/^# >>> selftest-leg >>>$/,/^# <<< selftest-leg <<<$/p' \
        "$SHARD_CLONE/scripts/check.sh" >"$SHARD_FENCE"
    grep -q '^selftest_drives_leg() {' "$SHARD_FENCE" ||
        cannot_look "the selftest-leg fence in scripts/check.sh defines no selftest_drives_leg — there is no leg body to shard"
    SHARD_ALWAYS="${WORK}/shard-always.sh"
    SHARD_REG="${WORK}/shard-registry.sh"
    sed -n '/^# >>> always-on-leg >>>$/,/^# <<< always-on-leg <<<$/p' \
        "$SHARD_CLONE/scripts/check.sh" >"$SHARD_ALWAYS"
    grep -q '^always_on__read_durations() {' "$SHARD_ALWAYS" ||
        cannot_look "the always-on fence in scripts/check.sh defines no always_on__read_durations — the selftest shard's partition reads the committed measurement through it, so a census sourced without it would be censusing the round-robin fallback and nothing else"
    awk '/^selftest_registered_drives\(\) \{/, /^\}/' \
        "$SHARD_CLONE/scripts/check.sh" >"$SHARD_REG"
    grep -q '^selftest_registered_drives() {' "$SHARD_REG" ||
        cannot_look "scripts/check.sh no longer defines selftest_registered_drives() with a closing brace at column 1 — the population the shard partitions cannot be extracted"
}

# shard_members [k K] — the drive names the leg actually RAN, one per line.
# A member that ran prints `drive <name>: exit <rc>`; one the shard skipped
# prints `drive <name>: not in shard k/K`, and only the first is a member.
# A SCRATCH LEDGER, AND IT IS A BELT RATHER THAN A CONVENIENCE. A green drive
# banks a reusable verdict, and `gate_ledger_path` resolves through
# `--git-common-dir` — one file SHARED by every worktree of this repository. A
# harness of stub drives writing rows into it would be a destructive
# demonstration aimed at found state, and on the second call every stub would
# come back `REUSED` rather than `exit 0`, which is not a member line. The same
# argument, in the same words, is `test_selftest_leg.sh`'s.
SHARD_LEDGER=""
shard_members() {
    local out="${WORK}/shard-run.out"
    SHARD_LEDGER="${WORK}/shard-verdicts"
    : >"$SHARD_LEDGER"
    (
        cd "$SHARD_CLONE" || exit 2
        PATH="${SHARD_BIN}:${PATH}"
        export PATH
        DJB_GATE_LEDGER="$SHARD_LEDGER"
        export DJB_GATE_LEDGER
        # THE FENCE IS NOT A WHOLE GATE, AND IT NEEDS WHAT THE GATE SOURCES.
        # The leg body reaches `gate_measured_tree` and `drive_key`
        # (`scripts/gate_ledger.sh`) and the refusal grammar under them
        # (`scripts/gate_refuse.sh`), which `scripts/check.sh` sources before
        # the leg is ever announced. Extracted alone, every member printed
        # `could not key` instead of `drive <name>: exit <rc>`, the member
        # reader below saw nothing, and all three shards came back holding no
        # drives — a census of the whole registered set, green about an empty
        # union. Sourced in the same order the gate sources them.
        # shellcheck source=scripts/gate_refuse.sh
        . ./scripts/gate_refuse.sh
        # shellcheck source=scripts/gate_ledger.sh
        . ./scripts/gate_ledger.sh
        # THE PARTITION'S TWO READERS, SOURCED BEFORE THE FENCE exactly as the
        # gate sources them: the always-on fence carries the durations reader
        # the shard plan balances over, and the registry carries the member
        # population it balances. Without them the leg is honest but is running
        # the round-robin fallback, and this census would be green about a
        # partition nobody ships.
        # shellcheck disable=SC1090  # the extracted always-on fence, by design
        . "$SHARD_ALWAYS"
        # shellcheck disable=SC1090  # the extracted drive registry, by design
        . "$SHARD_REG"
        # shellcheck disable=SC1090  # the extracted leg body, by design
        . "$SHARD_FENCE"
        # THE RECORDER'S OWN TWO GLOBALS, HONOURED RATHER THAN LEFT UNSET.
        # `selftest_member_end` hands every member's seconds to
        # `gate_member_record`, which is in the always-on fence now sourced
        # above and which reads `MODE` and `GATE_LEG_UNIT` to decide whether a
        # run may write the durations file at all. This drive runs under
        # `set -u`, subshells inherit it, and an unset `MODE` therefore KILLED
        # the subshell after the first member — every later drive landed in no
        # shard and the partition read as broken. A shard is a subset, so the
        # unit is named and the recorder rightly records nothing.
        MODE=""
        GATE_LEG_UNIT="selftest"
        selftest_drives_leg "$@"
    ) >"$out" 2>&1 || true
    # A FLOOR ON THE READER ITSELF. Everything below compares SETS, and a
    # reader that returns nothing makes "union == registered" false in a way
    # that reads as a shard arithmetic bug rather than as a harness that could
    # not run. A member that was skipped prints `not in shard k/K` and a member
    # the leg could not key prints `could not key`; if NEITHER shape nor an
    # `exit` line is in the transcript, the leg did not run at all.
    if ! grep -qE '^  drive [A-Za-z0-9_-]+: (exit |not in shard |REUSED |could not key)' "$out"; then
        cannot_look "the extracted leg body printed no drive line at all (see ${out}) — the harness did not run the leg, and every set comparison below would be a comparison with nothing"
    fi
    sed -n 's/^  drive \([A-Za-z0-9_-]*\): exit .*/\1/p' "$out"
}

case_every_drive_is_in_exactly_one_drives_unit() {
    # G9.5 / G9b.1. Two halves, and both are populations rather than counts: the
    # listing's `selftest` row names every registered drive exactly once, and
    # for K in 1, 2, 3 the shards PARTITION that same order — union equal,
    # pairwise disjoint. A floor written as "at least one drive ran" would be
    # satisfied by either half of a two-way split going blind.
    local registered listed k K union dupes="" missing="" extra=""
    CURRENT="the listing's selftest row names every registered drive, once"
    registered=$REGISTERED_DRIVES
    run_listing_here
    if [ "$LIST_RC" != "0" ]; then
        bad "--list-legs exits ${LIST_RC}, so there is no drive population to judge"
        return 0
    fi
    listed=$(awk -F'\t' '$1 == "selftest" { print $4 }' "$LIST_OUT" | tr ',' '\n' | grep -v '^selftest$')
    if [ "$(printf '%s\n' "$registered" | LC_ALL=C sort)" = "$(printf '%s\n' "$listed" | LC_ALL=C sort)" ]; then
        ok "$(printf '%s\n' "$registered" | grep -c .) drive(s), identical on both sides"
    else
        bad "the registered order and the listing's selftest row disagree
    registered: $(printf '%s' "$registered" | tr '\n' ' ')
    listed:     $(printf '%s' "$listed" | tr '\n' ' ')"
        return 0
    fi

    shard_harness_build
    for K in 1 2 3; do
        CURRENT="the shards of K=${K} partition the registered drive order"
        union=""
        k=0
        while [ "$k" -lt "$K" ]; do
            union="${union}$(shard_members "$k" "$K")
"
            # THE ARM IS ASSERTED, NOT ASSUMED. The shard assignment is a
            # duration-balanced partition when the committed measurement is
            # readable and the index round-robin when it is not — both are
            # legal, and only one of them is what the gate ships. A census that
            # silently ran the fallback would be green about arithmetic nobody
            # uses, which is the exact shape of a floor satisfied by nothing.
            if ! grep -qF "LPT over" "${WORK}/shard-run.out"; then
                cannot_look "shard ${k}/${K} did not print an LPT plan line (see ${WORK}/shard-run.out) — the harness sourced the leg without its durations reader or its registry, so every set comparison below would be about the round-robin fallback"
            fi
            k=$((k + 1))
        done
        union=$(printf '%s' "$union" | grep -v '^$' | grep -v '^house-rules-engine$' || true)
        dupes=$(printf '%s\n' "$union" | LC_ALL=C sort | uniq -d)
        missing=$(comm -23 <(printf '%s\n' "$registered" | LC_ALL=C sort) <(printf '%s\n' "$union" | LC_ALL=C sort))
        extra=$(comm -13 <(printf '%s\n' "$registered" | LC_ALL=C sort) <(printf '%s\n' "$union" | LC_ALL=C sort))
        if [ -z "$dupes" ] && [ -z "$missing" ] && [ -z "$extra" ]; then
            ok "K=${K}: $(printf '%s\n' "$union" | grep -c .) drive(s) across ${K} shard(s), disjoint, union == the registered order"
        else
            bad "K=${K}: in two shards '${dupes}' · in no shard '${missing}' · not registered '${extra}'"
        fi
    done

    CURRENT="an unsharded call still walks the whole set"
    union=$(shard_members | grep -v '^house-rules-engine$' || true)
    if [ "$(printf '%s\n' "$union" | LC_ALL=C sort)" = "$(printf '%s\n' "$registered" | LC_ALL=C sort)" ]; then
        ok "$(printf '%s\n' "$union" | grep -c .) drive(s) with no k/K — the default costs nothing"
    else
        bad "an unsharded call did not walk the whole registered order"
    fi

    CURRENT="a malformed shard pair is exit 2, never a smaller run"
    local rc=0
    (
        cd "$SHARD_CLONE" || exit 2
        PATH="${SHARD_BIN}:${PATH}"
        export PATH
        # shellcheck disable=SC1090  # the extracted leg body, by design
        . "$SHARD_FENCE"
        selftest_drives_leg 2 2
    ) >"${WORK}/shard-bad.out" 2>&1 || rc=$?
    if [ "$rc" = "2" ] && grep -q 'outside 0\.\.' "${WORK}/shard-bad.out"; then
        ok "shard 2/2 is refused: $(sed -n 1p "${WORK}/shard-bad.out")"
    else
        bad "shard 2/2 exited ${rc} — a k outside the range answered with a run"
    fi
}

case_a_drive_that_appears_in_no_unit_or_two_is_exit_2() {
    # G9.5's refusal, both directions. The `selftest` unit's population is
    # DERIVED (`$(selftest_registered_drives)`), so the plants replace that
    # derivation with a hand list — which is exactly the failure mode the
    # derivation exists to prevent, made visible.
    local plant
    CURRENT="a registered drive in no unit"
    plant="${WORK}/plant-drive-missing"
    clone_into "$plant"
    python3 - "$plant/scripts/check.sh" <<'PY_PLANT'
import sys
p = sys.argv[1]
src = open(p).read().split("\n")
drives = [
    l[len("./scripts/tests/test_"):-len(".sh")]
    for l in src
    if l.startswith("./scripts/tests/test_") and l.endswith(".sh")
]
for i, line in enumerate(src):
    if line.startswith("gate_unit selftest "):
        src[i] = "gate_unit selftest db,docker,temporal N-capable selftest " + " ".join(drives[1:])
        break
else:
    raise SystemExit("no selftest unit to narrow")
open(p, "w").write("\n".join(src))
PY_PLANT
    run_listing "$plant"
    if [ "$LIST_RC" = "2" ] && grep -q "is in NO unit — no shard" "$LIST_OUT"; then
        ok "exit 2: $(sed -n 1p "$LIST_OUT" | cut -c1-84)"
    else
        bad "a drive in no unit gave exit ${LIST_RC}: $(sed -n 1p "$LIST_OUT")"
    fi
    rm -rf "$plant"

    CURRENT="a registered drive in two units"
    plant="${WORK}/plant-drive-twice"
    clone_into "$plant"
    python3 - "$plant/scripts/check.sh" <<'PY_PLANT2'
import sys
p = sys.argv[1]
src = open(p).read().split("\n")
drives = [
    l[len("./scripts/tests/test_"):-len(".sh")]
    for l in src
    if l.startswith("./scripts/tests/test_") and l.endswith(".sh")
]
for i, line in enumerate(src):
    if line.startswith("gate_unit selftest "):
        src[i] = "gate_unit selftest db,docker,temporal N-capable selftest " + " ".join(drives)
        src.insert(i + 1, "gate_unit zzz-second-drives none 0 " + drives[0])
        break
else:
    raise SystemExit("no selftest unit to duplicate from")
open(p, "w").write("\n".join(src))
PY_PLANT2
    run_listing "$plant"
    if [ "$LIST_RC" = "2" ] && grep -q "more than one unit" "$LIST_OUT"; then
        ok "exit 2: $(sed -n 1p "$LIST_OUT" | cut -c1-84)"
    else
        bad "a drive in two units gave exit ${LIST_RC}: $(sed -n 1p "$LIST_OUT")"
    fi
    rm -rf "$plant"
}

case_the_build_contract_table_equals_the_listing() {
    # G9.7. The docs carry the unit table, and the command is the authority: the
    # table in `build-contract.md` is compared field for field against what
    # `--list-legs` prints, so a doc that drifts is a red rather than a reading.
    local doc=docs/product/build-contract.md unit needs shards legs row missing=""
    CURRENT="every unit the listing prints has its row in build-contract.md"
    [ -f "$doc" ] || {
        bad "$doc is not in this tree"
        return 0
    }
    run_listing_here
    if [ "$LIST_RC" != "0" ]; then
        bad "--list-legs exits ${LIST_RC}, so there is nothing to compare"
        return 0
    fi
    while IFS=$'\t' read -r unit needs shards legs; do
        [ -n "${unit:-}" ] || continue
        row="| \`${unit}\` | ${needs} | ${shards} | ${legs} |"
        grep -qF "$row" "$doc" || missing="${missing}${missing:+; }${unit}"
    done <"$LIST_OUT"
    if [ -z "$missing" ]; then
        ok "$(grep -c . "$LIST_OUT") row(s), each byte-identical to the listing's own line"
    else
        bad "build-contract.md has no matching row for: ${missing} — the doc and the command disagree"
    fi
}

# --- `--leg <unit>`: running ONE unit -----------------------------------------
#
# THE GATE, IN A CLONE, AND NOT THE LEG BODY. The subject of these cases is the
# gate's argument handling and its whole-mode flow — which legs a unit run
# announces, what it does NOT take and what it does NOT write — so there is no
# body to call, exactly as for the `--list-legs` cases above. A clone is a
# different checkout with its own lock and its own ledgers, so nothing here can
# touch the real ones.

LEG_OUT=""
LEG_RC=0
# FULL_LEGS, read once: the unit rows name legs AND (for a shardable unit) the
# drives its shard population is made of, and only the legs are announced.
FULL_LEGS_STRING=$(sed -n 's/^FULL_LEGS=//p' scripts/check.sh | sed -n 1p)
[ -n "$FULL_LEGS_STRING" ] ||
    cannot_look "scripts/check.sh has no FULL_LEGS line — the population these cases read is gone"

# dry_unit <unit> [args…] — the leg names a unit run announces, space-joined,
# de-duplicated on first appearance (`temporal-census` is announced twice and is
# one leg, which is how `FULL_LEGS` and the unit table both name it).
dry_unit() {
    local out="${WORK}/dry-unit.out" rc=0 leg seen=""
    (
        cd "$DRY_CLONE" &&
            DJB_GATE_LEGS_DRY=1 \
                DJB_GATE_LEASE_DIR="${WORK}/lease" \
                ./scripts/check.sh --leg "$@"
    ) >"$out" 2>&1 || rc=$?
    if [ "$rc" != "0" ]; then
        cannot_look "a dry \`check.sh --leg $*\` exited ${rc} — the unit census has no subject (see ${out})"
    fi
    for leg in $(sed -n 's/^  leg: \([a-z0-9-]*\) (DJB_GATE_LEGS_DRY.*/\1/p' "$out"); do
        case " $seen " in
        *" $leg "*) ;;
        *) seen="${seen}${seen:+ }$leg" ;;
        esac
    done
    printf '%s' "$seen"
}

case_leg_static_announces_its_legs_and_no_other() {
    # G10.1. For EVERY unit the listing prints — not just `static`, because a
    # floor that names one member of a population lets the others go blind — the
    # legs a `--leg <unit>` run announces are exactly that unit's `composed-of`,
    # minus the drive names a shardable unit lists as its shard population.
    local unit legs want got banners dry_lines
    run_listing_here
    if [ "$LIST_RC" != "0" ]; then
        bad "--list-legs exits ${LIST_RC}, so there are no units to run"
        return 0
    fi
    while IFS=$'\t' read -r unit _needs _shards legs; do
        [ -n "${unit:-}" ] || continue
        CURRENT="--leg ${unit} announces its own legs and no others"
        # A unit's members are legs AND (for a shardable one) the drives its
        # shard population is made of. Only the legs are announced.
        want=""
        for got in $(printf '%s' "$legs" | tr ',' ' '); do
            case ",${FULL_LEGS_STRING}," in
            *",${got},"*) want="${want}${want:+ }${got}" ;;
            esac
        done
        got=$(dry_unit "$unit")
        if [ "$got" = "$want" ]; then
            ok "$(printf '%s' "$got" | wc -w | tr -d ' ') leg(s): ${got}"
        else
            bad "the unit's announced sequence is not its composed-of
    want: ${want}
    got:  ${got}"
        fi
        # THE BANNERS ARE COUNTED TOO, AND THE TWO HALVES ARE DIFFERENT CODE.
        # The dry line above is `gate_run_body`'s — what a unit run RUNS — and
        # the `- ` banner is `leg`'s — what it ANNOUNCES. Severing only the
        # announcement filter leaves the dry lines correct and prints all two
        # dozen banners, so a case reading the dry lines alone goes green over a
        # transcript claiming every leg of the gate: measured on the plant, 26
        # banners against 1 dry line. One banner per announced leg, plus the one
        # `- --leg <unit>` preamble.
        #
        # READ OFF THE FILE, NOT OUT OF `dry_unit`. That function is called in a
        # command substitution — a SUBSHELL — so a global it set there would die
        # with it, which is the trap `scripts/check.sh` spells out beside its own
        # fingerprint line, and which reds this case as an unbound variable
        # rather than a wrong answer.
        CURRENT="--leg ${unit} prints one banner per leg it ran, and no others"
        banners=$(grep -c '^- ' "${WORK}/dry-unit.out" || true)
        dry_lines=$(grep -c 'DJB_GATE_LEGS_DRY — announced' "${WORK}/dry-unit.out" || true)
        if [ "$banners" = "$((dry_lines + 1))" ]; then
            ok "${banners} banner(s) for ${dry_lines} announced leg(s), plus the one --leg preamble"
        else
            bad "${banners} banner(s) for ${dry_lines} announced leg(s): the transcript names legs this unit never ran"
        fi
    done <"$LIST_OUT"
}

case_leg_takes_no_lease_no_lock_and_writes_no_verdict() {
    # G10.1. A unit is a targeted drive: it queues for nothing and it vouches
    # for nothing. Run in a clone, so the three ledgers compared before and
    # after are that clone's own.
    local plant="${WORK}/plant-leg-noverdict" before after f
    CURRENT="--leg full-house-rules takes no lease and no checkout lock"
    clone_into "$plant"
    before="${WORK}/ledgers-before"
    after="${WORK}/ledgers-after"
    : >"$before"
    : >"$after"
    for f in djb-gate-ledger djb-gate-last-full djb-loop-ledger djb-partition-ledger; do
        printf '%s %s\n' "$f" "$(cksum "${plant}/.git/${f}" 2>/dev/null | awk '{print $1 "-" $2}' || echo absent)" >>"$before"
    done
    LEG_RC=0
    (cd "$plant" && ./scripts/check.sh --leg full-house-rules) >"${WORK}/leg-noverdict.out" 2>&1 || LEG_RC=$?
    if [ "$LEG_RC" != "0" ]; then
        bad "--leg full-house-rules in a clone exited ${LEG_RC}: $(sed -n '$p' "${WORK}/leg-noverdict.out")"
        rm -rf "$plant"
        return 0
    fi
    if grep -q 'gate lease' "${WORK}/leg-noverdict.out"; then
        bad "the run announced a lease: $(grep -m1 'gate lease' "${WORK}/leg-noverdict.out")"
    else
        ok "no lease line in the whole transcript"
    fi
    if [ -e "${plant}/.git/djb-gate.lock" ]; then
        bad "the checkout lock file is still there after the run"
    else
        ok "no checkout lock left behind"
    fi

    CURRENT="and it records no verdict in any of the ledgers"
    for f in djb-gate-ledger djb-gate-last-full djb-loop-ledger djb-partition-ledger; do
        printf '%s %s\n' "$f" "$(cksum "${plant}/.git/${f}" 2>/dev/null | awk '{print $1 "-" $2}' || echo absent)" >>"$after"
    done
    if cmp -s "$before" "$after"; then
        ok "four ledger paths, byte-identical before and after"
    else
        bad "a ledger moved under a unit run:
$(diff "$before" "$after" || true)"
    fi
    if grep -q 'no verdict recorded — --leg full-house-rules' "${WORK}/leg-noverdict.out"; then
        ok "and the run SAYS so: $(grep -m1 'no verdict recorded' "${WORK}/leg-noverdict.out" | sed 's/^  //')"
    else
        bad "the run banked nothing and never said it was not going to"
    fi
    rm -rf "$plant"
}

case_leg_needs_no_sanction() {
    # G10.1. The sanction exists because a full gate holds the machine's one
    # exclusive lease and every other full gate queues behind it. A unit takes
    # no lease, so it is exempt — and the proof is that the refusal the full
    # mode prints is absent, not merely that the run exited 0.
    #
    # IN A CLONE, because this drive runs inside the selftest leg of a real
    # gate: that gate holds THIS checkout's lock, and a unit run in it would go
    # red for the lock rather than for the property. A clone is a different
    # checkout and has its own.
    CURRENT="a unit run with no DJB_GATE_SANCTION is not refused"
    local rc=0 plant="${WORK}/plant-leg-sanction"
    clone_into "$plant"
    (cd "$plant" && env -u DJB_GATE_SANCTION -u DJB_GATE_CALLER ./scripts/check.sh --leg full-house-rules) \
        >"${WORK}/leg-sanction.out" 2>&1 || rc=$?
    if grep -q 'REFUSING an unsanctioned FULL gate' "${WORK}/leg-sanction.out"; then
        bad "a unit run was refused for want of a sanction"
    elif [ "$rc" = "2" ]; then
        bad "a unit run exited 2 with no sanction: $(sed -n 1p "${WORK}/leg-sanction.out")"
    else
        ok "exit ${rc}, and the full mode's refusal sentence never appears"
    fi
    rm -rf "$plant"
}

case_an_unknown_unit_is_exit_2_naming_the_listing() {
    # G10.1. A runner handed a name this gate does not know must be told where
    # the names come from — never given a smaller run, and never a bare usage
    # line that leaves it guessing.
    local rc=0
    CURRENT="--leg with a name no unit has"
    (cd "$ROOT" && ./scripts/check.sh --leg zzz-not-a-unit) >"${WORK}/leg-unknown.out" 2>&1 || rc=$?
    if [ "$rc" = "2" ] && grep -q -- '--list-legs' "${WORK}/leg-unknown.out"; then
        ok "exit 2, pointing at the listing: $(sed -n 1p "${WORK}/leg-unknown.out")"
    else
        bad "exit ${rc}: $(sed -n 1p "${WORK}/leg-unknown.out")"
    fi

    CURRENT="and --leg with no unit at all"
    rc=0
    (cd "$ROOT" && ./scripts/check.sh --leg) >"${WORK}/leg-nounit.out" 2>&1 || rc=$?
    if [ "$rc" = "2" ]; then
        ok "exit 2: $(sed -n 1p "${WORK}/leg-nounit.out")"
    else
        bad "exit ${rc} — a --leg with no unit was answered with something"
    fi
}

case_leg_pytest_x2_takes_a_slot() {
    # G10.1, and the WEAKER form of it, said so rather than implied: running the
    # `pytest-x2` unit for real inside this drive would cost the whole suite
    # twice, inside the selftest leg of a gate that has already run it. What is
    # asserted here is the WIRING — the slot acquisition sits inside the leg
    # body the unit runs, at derived line numbers — and the dynamic half is
    # every real full gate's own transcript, which prints the `pytest slot` line.
    local body_start body_end slot
    CURRENT="the pytest slot is taken inside the unit's own leg body"
    body_start=$({ grep -n '^gate_leg_pytest_x2() {$' "${ROOT}/scripts/check.sh" || true; } | sed -n '1s/:.*//p')
    body_end=$({ grep -n '^gate_run_body pytest-x2 gate_leg_pytest_x2$' "${ROOT}/scripts/check.sh" || true; } | sed -n '1s/:.*//p')
    slot=$({ grep -n '^    gate_slot_acquire full$' "${ROOT}/scripts/check.sh" || true; } | sed -n '1s/:.*//p')
    if [ -z "$body_start" ] || [ -z "$body_end" ] || [ -z "$slot" ]; then
        bad "body '${body_start:-<none>}'..'${body_end:-<none>}', slot '${slot:-<none>}' — the wiring has lost a subject"
        return 0
    fi
    if [ "$slot" -gt "$body_start" ] && [ "$slot" -lt "$body_end" ]; then
        ok "gate_slot_acquire at line ${slot}, inside gate_leg_pytest_x2 (${body_start}..${body_end})"
    else
        bad "the slot acquisition (line ${slot}) is outside the leg body (${body_start}..${body_end}) — a unit that runs no suite would take one"
    fi

    CURRENT="and no OTHER unit's legs reach it"
    # DERIVED, NOT COUNTED. A magic number here would go stale the day a leg
    # body is reformatted; the property is that EVERY call site lies inside one
    # of the two pytest leg bodies — the per-rung leg's and the full unit's — so
    # no unit that runs no suite can take one.
    local outside
    outside=$(awk '
        /^gate_leg_pytest\(\) \{$|^    gate_leg_pytest\(\) \{$/ { in_loop = 1 }
        in_loop && /^    \}$/ { in_loop = 0 }
        /^gate_leg_pytest_x2\(\) \{$/ { in_x2 = 1 }
        /^gate_run_body pytest-x2 gate_leg_pytest_x2$/ { in_x2 = 0 }
        /^[[:space:]]*gate_slot_acquire [a-z]+$/ {
            if (!in_loop && !in_x2) { print NR ": " $0 }
        }
    ' "${ROOT}/scripts/check.sh")
    if [ -z "$outside" ]; then
        ok "every gate_slot_acquire call site is inside a pytest leg body"
    else
        bad "a slot is taken outside the two pytest leg bodies:
${outside}"
    fi
}

# --- the seed, the split, and the shard census --------------------------------
#
# THE LEG BODY, NEVER THE GATE AROUND IT (rung-execution §2). The two decisions
# a shard rests on — which seed both passes carry, and which split flags they
# carry — are functions in `scripts/check.sh` precisely so a drive can call the
# bytes the gate ships rather than re-derive them. `gate_fn` copies one
# definition out and sources it, the shape `scripts/tests/test_loop_scope.sh`
# established for `pytest_x2_passes`.
gate_fn() {
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

# A SCRATCH CHECKOUT WHOSE `scripts/test.sh` IS AN ARGV LOG. Not the real one:
# the question these cases ask is what the two passes are HANDED, and running
# the suite twice to find out would cost twenty minutes to read two lines.
X2_SHIM_DIR=""
x2_shim_build() {
    [ -z "$X2_SHIM_DIR" ] || return 0
    X2_SHIM_DIR="${WORK}/x2-shim"
    mkdir -p "${X2_SHIM_DIR}/scripts"
    cat >"${X2_SHIM_DIR}/scripts/test.sh" <<'SHIM'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$DJB_ARGV_LOG"
exit "${DJB_SHIM_RC:-0}"
SHIM
    chmod +x "${X2_SHIM_DIR}/scripts/test.sh"
}

# x2_argv <log> [env assignments…] — drive the seed, the split and the two
# passes over the shim, and leave every invocation's argv in <log>.
X2_DRIVE_RC=0
x2_argv() {
    local log=$1
    shift
    : >"$log"
    X2_DRIVE_RC=0
    (
        cd "$X2_SHIM_DIR" || exit 2
        # shellcheck disable=SC1090  # the extracted definitions, by design
        . "${WORK}/fn-gate_pytest_seed.sh"
        # shellcheck disable=SC1090
        . "${WORK}/fn-gate_durations_path.sh"
        # shellcheck disable=SC1090
        . "${WORK}/fn-gate_pytest_split_args.sh"
        # shellcheck disable=SC1090
        . "${WORK}/fn-pytest_x2_counts_refuse.sh"
        # shellcheck disable=SC1090
        . "${WORK}/fn-pytest_x2_verdict.sh"
        # shellcheck disable=SC1090
        . "${WORK}/fn-pytest_x2_passes.sh"
        heartbeat_label() { :; }
        heartbeat_stop() { :; }
        GATE_X2_COUNTS_DIR=""
        GATE_SLOT_WORKERS=2
        GATE_SHARD=""
        GATE_SHARD_K=""
        GATE_SHARD_N=""
        GATE_STORE_DURATIONS=""
        GATE_PASSES=""
        PYTEST_SEED=""
        GATE_SPLIT_ARGS=""
        DJB_SHIM_RC=0
        export DJB_ARGV_LOG="$log"
        # The caller's assignments, applied after the defaults so they win.
        eval "$*"
        # EXPORTED AFTER THE EVAL, because the shim is a separate PROCESS: a
        # `DJB_SHIM_RC=5` that stayed in this shell would leave the shim exiting
        # 0 and the case green over a run that never failed.
        export DJB_SHIM_RC
        gate_pytest_seed
        gate_pytest_split_args
        # shellcheck disable=SC2086  # the split flags word-split into arguments
        pytest_x2_passes $GATE_SPLIT_ARGS
    ) >"${WORK}/x2-drive.out" 2>&1 || X2_DRIVE_RC=$?
}

x2_ready() {
    x2_shim_build
    # `gate_pytest_split_args` CALLS `gate_durations_path`, so the extraction has
    # to take both: a function pulled out without its callee is a drive measuring
    # a `command not found`.
    gate_fn gate_durations_path
    gate_fn gate_pytest_seed
    gate_fn gate_pytest_split_args
    gate_fn pytest_x2_counts_refuse
    gate_fn pytest_x2_verdict
    gate_fn pytest_x2_passes
}

case_a_typed_seed_reaches_both_passes() {
    # G10.2. Every shard of one CI run has to split the SAME collection order,
    # and the order is the seed's. Two invocations, both carrying the typed
    # seed, is the whole property.
    local log="${WORK}/argv-seed.log" n
    CURRENT="DJB_GATE_PYTEST_SEED=7 reaches both passes"
    x2_ready
    x2_argv "$log" 'DJB_GATE_PYTEST_SEED=7'
    n=$(grep -c . "$log" || true)
    if [ "$X2_DRIVE_RC" != "0" ]; then
        bad "the two passes exited ${X2_DRIVE_RC} over the shim: $(sed -n '$p' "${WORK}/x2-drive.out")"
    elif [ "$n" != "2" ]; then
        bad "${n} invocation(s) of scripts/test.sh, not 2: $(tr '\n' '|' <"$log")"
    elif [ "$(grep -c -- '--randomly-seed=7' "$log")" != "2" ]; then
        bad "the typed seed did not reach both passes: $(tr '\n' '|' <"$log")"
    else
        ok "2 invocations, both --randomly-seed=7: $(sed -n 1p "$log")"
    fi

    CURRENT="and the leg says where the seed came from"
    if grep -q 'seed: 7 (typed: DJB_GATE_PYTEST_SEED)' "${WORK}/x2-drive.out"; then
        ok "$(grep -m1 'seed: 7' "${WORK}/x2-drive.out" | sed 's/^  //')"
    else
        bad "the provenance line is missing — a seed whose origin is invisible is one nobody can replay"
    fi

    CURRENT="and an untyped seed is minted, and says THAT"
    x2_argv "$log" 'true'
    if grep -qE 'seed: [0-9]+ \(minted\)' "${WORK}/x2-drive.out"; then
        ok "$(grep -m1 -E 'seed: [0-9]+ \(minted\)' "${WORK}/x2-drive.out" | sed 's/^  //')"
    else
        bad "an untyped run did not print a minted seed with its provenance"
    fi
}

case_an_unparsable_seed_is_exit_2() {
    # G10.2. Never a minted fallback: a silent one is how two shards come to
    # split two different collections and both go green.
    local rc=0
    CURRENT="a seed that is not an integer"
    x2_ready
    (
        DJB_GATE_PYTEST_SEED="deadbeef"
        # shellcheck disable=SC1090
        . "${WORK}/fn-gate_pytest_seed.sh"
        gate_pytest_seed
    ) >"${WORK}/seed-bad.out" 2>&1 || rc=$?
    if [ "$rc" = "2" ] && grep -q 'DJB_GATE_PYTEST_SEED is set and is not' "${WORK}/seed-bad.out"; then
        ok "exit 2: $(sed -n 1p "${WORK}/seed-bad.out")"
    else
        bad "exit ${rc}: $(sed -n 1p "${WORK}/seed-bad.out")"
    fi
}

case_shard_k_of_n_passes_split_and_group_to_both_passes_under_one_seed() {
    # G10.3. Both passes of a shard carry the same split, the same group and the
    # same seed — the second pass's meaning is "what pass 1 left behind", which
    # requires the two to have collected the same thing.
    local log="${WORK}/argv-shard.log"
    CURRENT="--shard 2/3 reaches both passes with one seed"
    x2_ready
    x2_argv "$log" 'DJB_GATE_PYTEST_SEED=11 GATE_SHARD=2/3 GATE_SHARD_K=2 GATE_SHARD_N=3'
    if [ "$X2_DRIVE_RC" != "0" ]; then
        bad "the two passes exited ${X2_DRIVE_RC}: $(sed -n '$p' "${WORK}/x2-drive.out")"
    elif [ "$(grep -c -F -- "$(split_flags 2 3)" "$log")" != "2" ]; then
        bad "the split flags did not reach both passes: $(tr '\n' '|' <"$log")"
    elif [ "$(grep -c -- '--randomly-seed=11' "$log")" != "2" ]; then
        bad "the two passes of one shard did not share a seed: $(tr '\n' '|' <"$log")"
    else
        ok "2 invocations: $(sed -n 1p "$log")"
    fi

    CURRENT="and 1/1 is the whole unit, with no split flags at all"
    x2_argv "$log" 'GATE_SHARD=1/1 GATE_SHARD_K=1 GATE_SHARD_N=1'
    if grep -q -- '--splits' "$log"; then
        bad "1/1 carried a split: $(sed -n 1p "$log")"
    elif grep -q 'shard 1/1: the WHOLE unit' "${WORK}/x2-drive.out"; then
        ok "no split flags, and the leg says why: $(grep -m1 'shard 1/1' "${WORK}/x2-drive.out" | sed 's/^  //')"
    else
        bad "1/1 carried no flags and never said it was the whole unit"
    fi
}

case_the_shard_census_reads_the_gates_own_flags() {
    # G10F2.3. The census's whole claim is "the shards the GATE runs partition
    # the collection", and it is only that claim if the flags come from the
    # gate. They did not: this file used to spell `--splits N --group k
    # --durations-path scripts/pytest_durations.json` at three sites, so a
    # change to what the leg actually carries would have left the census green
    # about a split nothing ships.
    local flags typed
    CURRENT="the census asks gate_pytest_split_args for the flags"
    flags=$(split_flags 2 3)
    if [ -z "$flags" ]; then
        bad "the extracted gate_pytest_split_args produced no flags for shard 2/3"
        return 0
    fi
    case "$flags" in
    *"--splits 3"*) ok "the gate's own string: ${flags}" ;;
    *) bad "the function did not produce a split for 2/3: ${flags}" ;;
    esac

    CURRENT="and no case re-types the SHIPPED durations path"
    # THE POPULATION IS THE DRIFT RISK, not every string that looks like a flag.
    # Two cases point `--durations-path` at a scratch file ON PURPOSE — a
    # missing one and a stale one are their subjects — and they name it through
    # a variable. What must never be re-typed is the path the GATE carries: that
    # is the one a change to the leg would leave behind here. Read as CODE, with
    # comments stripped, so this file may go on explaining itself; and counted
    # to EOF rather than probed, for the reason the pipefail note in
    # `test_loop_scope.sh` records.
    typed=$(sed 's/#.*$//' "$0" | grep -c -F -- "--durations-path scripts/" || true)
    if [ "$typed" = "0" ]; then
        ok "the gate's durations path is typed at no site in this drive"
    else
        bad "${typed} executable site(s) re-type the shipped durations path rather than reading gate_pytest_split_args"
    fi

    CURRENT="and the durations path the gate hands over is inside the rootdir"
    case "$flags" in
    *--durations-path\ /*) bad "the gate handed an absolute durations path: ${flags}" ;;
    *--durations-path*) ok "relative to the rootdir, as the refusal requires: ${flags#*--durations-path }" ;;
    *) bad "the gate's flags carry no durations path at all: ${flags}" ;;
    esac
}

case_shard_on_a_non_pytest_unit_is_exit_2() {
    # G10.3, DERIVED FROM THE LISTING rather than from the unit's name. The
    # criterion was written when `pytest-x2` was the only shardable unit; G9b
    # made `selftest` N-capable too, and a gate that refused a shard the LISTING
    # advertises would be advertising a split no runner could take. So the rule
    # is the field: `shards: 0` refuses, `shards: N-capable` accepts.
    local unit shards rc refused=0 accepted=0
    run_listing_here
    if [ "$LIST_RC" != "0" ]; then
        bad "--list-legs exits ${LIST_RC}, so there are no units to shard"
        return 0
    fi
    while IFS=$'\t' read -r unit _needs shards _legs; do
        [ -n "${unit:-}" ] || continue
        [ "$shards" = "0" ] || continue
        CURRENT="--leg ${unit} --shard 1/3 (shards: 0)"
        rc=0
        (cd "$ROOT" && ./scripts/check.sh --leg "$unit" --shard 1/3) >"${WORK}/shard-unit.out" 2>&1 || rc=$?
        if [ "$rc" = "2" ] && grep -q 'indivisible' "${WORK}/shard-unit.out"; then
            ok "exit 2: $(sed -n 1p "${WORK}/shard-unit.out")"
            refused=$((refused + 1))
        else
            bad "exit ${rc}: $(sed -n 1p "${WORK}/shard-unit.out")"
        fi
    done <"$LIST_OUT"
    CURRENT="every indivisible unit refuses a shard"
    if [ "$refused" -ge 1 ]; then
        ok "${refused} indivisible unit(s), each refused by name"
    else
        bad "no indivisible unit was driven — the listing has none, so this case asserted nothing"
    fi

    CURRENT="and an N-capable unit ACCEPTS one (the listing is not advertising a split nobody can take)"
    while IFS=$'\t' read -r unit _needs shards _legs; do
        [ -n "${unit:-}" ] || continue
        [ "$shards" = "N-capable" ] || continue
        accepted=$((accepted + 1))
    done <"$LIST_OUT"
    if [ "$accepted" -ge 1 ]; then
        ok "${accepted} N-capable unit(s) declared; the acceptance path is driven by the shard census below"
    else
        bad "the listing declares no N-capable unit at all — the split has no subject"
    fi
}

case_a_malformed_shard_pair_is_exit_2() {
    # G10.3. Five shapes, each its own assertion: a shard this gate cannot parse
    # is never a smaller run, and a k outside 1..N names a part that does not
    # exist.
    local pair rc
    for pair in "4/3" "0/3" "1/0" "a/3" "13"; do
        CURRENT="--shard ${pair}"
        rc=0
        (cd "$ROOT" && ./scripts/check.sh --leg pytest-x2 --shard "$pair") >"${WORK}/shard-bad-pair.out" 2>&1 || rc=$?
        if [ "$rc" = "2" ]; then
            ok "exit 2: $(sed -n 1p "${WORK}/shard-bad-pair.out")"
        else
            bad "exit ${rc} — a malformed pair was answered with a run"
        fi
    done

    CURRENT="--shard with no pair at all"
    rc=0
    (cd "$ROOT" && ./scripts/check.sh --leg pytest-x2 --shard) >"${WORK}/shard-nopair.out" 2>&1 || rc=$?
    if [ "$rc" = "2" ]; then
        ok "exit 2: $(sed -n 1p "${WORK}/shard-nopair.out")"
    else
        bad "exit ${rc} — a --shard with no pair was answered with a run"
    fi

    CURRENT="--shard outside a unit run is exit 2"
    rc=0
    (cd "$ROOT" && ./scripts/check.sh --loop --shard 1/3) >"${WORK}/shard-nounit.out" 2>&1 || rc=$?
    # THE STATUS IS NOT THE CLAIM, AND THIS CASE PASSED BY ORDERING. Several
    # refusals on this path exit 2 — the box guard among them — so `rc = 2`
    # alone is satisfied by whichever one happens to fire FIRST, and a
    # reordering that put another refusal in front would leave this case green
    # while the modifier it is about was silently consumed. The SENTENCE is the
    # claim: the parser refusing the argument it does not honour.
    if [ "$rc" = "2" ] && grep -qF -- 'unexpected extra arguments: --shard 1/3' "${WORK}/shard-nounit.out"; then
        ok "exit 2, and it is the parser refusing the modifier: $(sed -n 1p "${WORK}/shard-nounit.out")"
    elif [ "$rc" = "2" ]; then
        bad "exit 2, but for some other reason — a --shard this mode does not honour must be refused BY NAME: $(sed -n 1p "${WORK}/shard-nounit.out")"
    else
        bad "exit ${rc} — a --shard was consumed by a mode that does not honour it"
    fi
}

case_an_empty_shard_is_exit_2() {
    # G10.3. A shard that COLLECTED NOTHING has judged nothing: it is not a
    # green part and it is not a red suite. pytest says so with exit 5, and this
    # file has one word for "the suite did not run" — 2, which outranks a pass.
    local log="${WORK}/argv-empty.log"
    CURRENT="pytest exit 5 under a shard is could-not-look, not a red"
    x2_ready
    x2_argv "$log" 'DJB_SHIM_RC=5 GATE_SHARD=3/3 GATE_SHARD_K=3 GATE_SHARD_N=3'
    if [ "$X2_DRIVE_RC" = "2" ] && grep -q 'THIS RUN IS SHARD 3/3' "${WORK}/x2-drive.out"; then
        ok "exit 2, naming the shard: $(grep -m1 'PASS 1 DID NOT RUN' "${WORK}/x2-drive.out")"
    else
        bad "exit ${X2_DRIVE_RC}: $(sed -n '$p' "${WORK}/x2-drive.out")"
    fi

    CURRENT="and an ordinary red is still a red"
    x2_argv "$log" 'DJB_SHIM_RC=1'
    if [ "$X2_DRIVE_RC" = "1" ]; then
        ok "exit 1 — a failing suite is a finding, not a could-not-look"
    else
        bad "a pytest exit 1 came back as ${X2_DRIVE_RC}"
    fi
}

# THE SENTENCE THE ONE-PASS SHARD OWES, pinned here and not derived from the
# gate. It is a CONTRACT — the thing a reader of a bank's shard log learns the
# belt from — and a drive that read it out of `scripts/check.sh` would go green
# on whatever the file happened to say, which is the one question it is asked.
PASSES1_SENTENCE="  pytest pass 2 NOT run — --passes 1: the leak proof is the acceptance box's (ADR gate-1)"

# banner_line <file> <prefix> — one line of a `--leg` banner, by its prefix.
banner_line() {
    sed -n "s|^$2||p" "$1" | sed -n 1p
}

case_passes_1_runs_one_pass_and_says_so() {
    # `--leg pytest-x2 --shard k/P --passes 1` runs pass 1 ONLY, says
    # so in the sentence above, and exits pass 1's own status through the SAME
    # 0 / 1 / 2 mapping a two-pass run does. Two halves, because the property
    # has two: what the unit ANNOUNCES (the dry run, where the censuses that
    # bracket the suite are visible) and what the body HANDS pytest (the argv
    # shim, where one invocation is the whole claim).
    local log="${WORK}/argv-passes1.log" got want n body recon early
    CURRENT="--passes 1 announces the same legs a two-pass shard does"
    want=$(dry_unit pytest-x2 --shard 1/3)
    got=$(dry_unit pytest-x2 --shard 1/3 --passes 1)
    if [ "$got" = "$want" ]; then
        ok "the announced sequence is unchanged by the pass count: ${got}"
    else
        bad "one pass changed which legs the unit announces
    want: ${want}
    got:  ${got}"
    fi

    # DERIVED FROM THE ANNOUNCED SEQUENCE, never typed: the two censuses are
    # claims about what the suite left behind, and they hold over one pass, so
    # the one thing that must still be true is that they BRACKET it.
    CURRENT="and temporal-census / own-tree-census still bracket the one pass"
    case "$got" in
    "temporal-census "*" pytest-x2 "*"own-tree-census")
        ok "the one pass runs between the censuses: ${got}"
        ;;
    *)
        bad "the brackets are gone or reordered: ${got}"
        ;;
    esac

    CURRENT="and the body hands scripts/test.sh ONE invocation, with the seed and the split"
    x2_ready
    x2_argv "$log" 'DJB_GATE_PYTEST_SEED=13 GATE_SHARD=2/3 GATE_SHARD_K=2 GATE_SHARD_N=3 GATE_PASSES=1'
    n=$(grep -c . "$log" || true)
    if [ "$X2_DRIVE_RC" != "0" ]; then
        bad "the one pass exited ${X2_DRIVE_RC} over the shim: $(sed -n '$p' "${WORK}/x2-drive.out")"
    elif [ "$n" != "1" ]; then
        bad "${n} invocation(s) of scripts/test.sh, not 1: $(tr '\n' '|' <"$log")"
    elif ! grep -q -F -- "$(split_flags 2 3)" "$log"; then
        bad "the split flags did not reach the one pass: $(sed -n 1p "$log")"
    elif ! grep -q -- '--randomly-seed=13' "$log"; then
        bad "the seed did not reach the one pass: $(sed -n 1p "$log")"
    else
        ok "1 invocation, seeded and split: $(sed -n 1p "$log")"
    fi

    CURRENT="and it says pass 2 was not run, and where the belt went"
    if grep -qF -- "$PASSES1_SENTENCE" "${WORK}/x2-drive.out"; then
        ok "$(grep -m1 -F -- 'pass 2 NOT run — --passes 1' "${WORK}/x2-drive.out" | sed 's/^  //')"
    else
        bad "the leg dropped pass 2 and never said so — a shorter run wearing a two-pass verdict:
    $(sed -n '$p' "${WORK}/x2-drive.out")"
    fi

    # THE MAPPING, BOTH NON-ZERO ARMS. A one-pass shard exits PASS 1's status,
    # and pass 1's status is read exactly as it is today: 1 is a finding, and a
    # collector that never reported is 2 — which outranks a pass and must not
    # be turned into one by the early return.
    CURRENT="and a red pass 1 is still exit 1, with no NOT-run sentence"
    x2_argv "$log" 'DJB_SHIM_RC=1 GATE_SHARD=2/3 GATE_SHARD_K=2 GATE_SHARD_N=3 GATE_PASSES=1'
    if [ "$X2_DRIVE_RC" = "1" ] && ! grep -qF -- "$PASSES1_SENTENCE" "${WORK}/x2-drive.out"; then
        ok "exit 1 — a failing shard is a finding, and the leg claims nothing about pass 2"
    else
        bad "exit ${X2_DRIVE_RC}: $(sed -n '$p' "${WORK}/x2-drive.out")"
    fi

    CURRENT="and a shard that collected nothing is still exit 2, not a one-pass green"
    x2_argv "$log" 'DJB_SHIM_RC=5 GATE_SHARD=3/3 GATE_SHARD_K=3 GATE_SHARD_N=3 GATE_PASSES=1'
    if [ "$X2_DRIVE_RC" = "2" ] && grep -q 'THIS RUN IS SHARD 3/3' "${WORK}/x2-drive.out"; then
        ok "exit 2, naming the shard: $(grep -m1 'PASS 1 DID NOT RUN' "${WORK}/x2-drive.out")"
    else
        bad "exit ${X2_DRIVE_RC} — could-not-look came back as something else: $(sed -n '$p' "${WORK}/x2-drive.out")"
    fi

    # A TRANSCRIPT THAT SAYS "both passes" AND THEN "pass 2 NOT run" HAS TOLD
    # ITS READER TWO THINGS. The shard log a bank composes is read by somebody
    # who was not watching it run, so a line asserting two passes over one is
    # the same class of defect as a row vouching for more than ran. Three
    # reaches, because the claims live in three places: the leg DECLARATION
    # (the dry transcript), the split line (the argv harness), and the rest of
    # the leg body (static — those echoes sit at the gate's top level, where
    # neither harness can reach them).
    CURRENT="and no line of a one-pass transcript claims two passes"
    dry_unit pytest-x2 --shard 1/3 --passes 1 >/dev/null
    if grep -q 'both passes' "${WORK}/dry-unit.out"; then
        bad "the one-pass transcript still asserts two: $(grep -m1 'both passes' "${WORK}/dry-unit.out")"
    elif grep -q -- '--passes 1' "${WORK}/dry-unit.out"; then
        ok "$(grep -m1 '^- pytest' "${WORK}/dry-unit.out" | cut -c1-96)"
    else
        bad "the one-pass transcript names neither two passes nor one — it says nothing about the count at all"
    fi

    CURRENT="and the DEFAULT transcript still says both (the negative)"
    dry_unit pytest-x2 --shard 1/3 >/dev/null
    if grep -q 'both passes' "${WORK}/dry-unit.out"; then
        ok "unchanged for a two-pass shard: $(grep -m1 'both passes' "${WORK}/dry-unit.out" | cut -c1-84)"
    else
        bad "a two-pass run stopped saying so — the wording moved for everybody, not just the one-pass case"
    fi

    # THE SPLIT LINE READS THE VARIABLE, AND THAT IS WHAT IS ASSERTED — not
    # the wording. The decision site that flips it is top-level, so this
    # harness cannot reach it; what it CAN prove is that the echo prints
    # whatever the variable holds rather than a literal, which is the half
    # that would otherwise go on saying "both" after the flip.
    CURRENT="and the split line prints the pass-count variable, not a literal"
    x2_argv "$log" 'GATE_SHARD=2/3 GATE_SHARD_K=2 GATE_SHARD_N=3 GATE_PASSES=1 GATE_PASSES_CARRY=zzz-carry-probe'
    if grep -q 'both passes carry' "${WORK}/x2-drive.out"; then
        bad "the split line still spells it: $(grep -m1 'both passes carry' "${WORK}/x2-drive.out")"
    elif grep -q 'shard 2/3: zzz-carry-probe ' "${WORK}/x2-drive.out"; then
        ok "$(grep -m1 'shard 2/3:' "${WORK}/x2-drive.out" | sed 's/^  //')"
    else
        bad "the split line printed neither the variable nor the literal: $(grep -m1 'shard 2/3:' "${WORK}/x2-drive.out")"
    fi

    # STATIC, OVER THE LEG BODY, WITH ITS OWN CANARY. The remaining claims are
    # top-level echoes between the suite leg's announcement and the slot going
    # back — the partition's two lines and the seed line — and no harness here
    # runs that region. What is read instead is that none of them SPELLS the
    # count: every one goes through the variable the one decision site sets.
    CURRENT="and no echo in the suite leg's body spells a pass count"
    local region="${WORK}/x2-leg-region.txt" spelled canary
    awk '/^leg pytest-x2 /{on=1} on{print} on && /^gate_slot_release$/{exit}' \
        "${ROOT}/scripts/check.sh" >"$region"
    grep -q '^gate_slot_release$' "$region" ||
        cannot_look "scripts/check.sh no longer closes the suite leg with gate_slot_release at column 1 — the region this reads has no end"
    spelled=$(grep -c 'echo .*both passes' "$region" || true)
    if [ "$spelled" = "0" ]; then
        ok "$(grep -c . "$region") line(s) of the suite leg, no echo spelling a pass count"
    else
        bad "${spelled} echo(es) in the suite leg spell 'both passes' literally: $(grep -m1 'echo .*both passes' "$region")"
    fi

    CURRENT="and that reader FIRES when a literal is put back (the canary)"
    canary="${WORK}/x2-leg-canary.txt"
    sed 's|^\(echo "  \)${GATE_PASSES_RUN}|\1both passes run|' "$region" >"$canary"
    if [ "$(grep -c 'echo .*both passes' "$canary" || true)" -ge 1 ]; then
        ok "a re-planted literal is seen: $(grep -m1 'echo .*both passes' "$canary")"
    else
        cannot_look "the plant changed nothing — the reader above is green over a check that cannot fail"
    fi

    # STATIC, AND IT HAS TO BE: the reconciliation needs `loop_counts_refuse_if_
    # short` and the refusal seam, which the argv harness does not source — so
    # `GATE_X2_COUNTS_DIR` is empty there and the function returns 0 without
    # looking. What is asserted instead is the ORDER in the shipped body: the
    # one-pass return is AFTER the post-pass-1 reconciliation, never instead of
    # it. A return that jumped the reconciliation would be a green over a suite
    # whose collectors never reported.
    CURRENT="and the one-pass return sits AFTER the counts reconciliation"
    gate_fn pytest_x2_passes
    body="${WORK}/fn-pytest_x2_passes.sh"
    recon=$(grep -n 'if ! pytest_x2_counts_refuse; then' "$body" | sed -n 1p | cut -d: -f1)
    early=$(grep -n -F -- 'pytest pass 2 NOT run — --passes 1' "$body" | sed -n 1p | cut -d: -f1)
    if [ -z "${recon:-}" ] || [ -z "${early:-}" ]; then
        cannot_look "pytest_x2_passes no longer carries both the reconciliation and the one-pass return (recon '${recon:-}', return '${early:-}')"
    elif [ "$recon" -lt "$early" ]; then
        ok "reconciliation at line ${recon}, the one-pass return at ${early} — the belt's own check is not jumped"
    else
        bad "the one-pass return (line ${early}) precedes the reconciliation (line ${recon}): a shard whose collectors never reported would come back green"
    fi
}

case_passes_outside_a_shard_or_malformed_is_exit_2() {
    # Five refusals, each exit 2 with a sentence naming the reason,
    # and NOTHING RUN — the banner is the tell: every one of these lands before
    # `- --leg` is printed, so a transcript with a banner in it is a refusal
    # that had already started the unit.
    local rc out="${WORK}/passes-refusal.out"
    refuse() {
        local want=$1
        shift
        rc=0
        (cd "$ROOT" && ./scripts/check.sh "$@") >"$out" 2>&1 || rc=$?
        if [ "$rc" != "2" ]; then
            bad "exit ${rc} — a bad pass count was answered with a run: $(sed -n 1p "$out")"
        elif ! grep -qF -- "$want" "$out"; then
            bad "exit 2 with the wrong sentence (wanted '${want}'): $(sed -n 1p "$out")"
        elif grep -q '^- ' "$out"; then
            bad "exit 2, but the unit had already been announced: $(grep -m1 '^- ' "$out")"
        else
            ok "exit 2, nothing announced: $(sed -n 1p "$out")"
        fi
    }

    CURRENT="--passes 1 on the WHOLE unit (no --shard)"
    refuse "the whole-suite two-pass belt is this unit's own" --leg pytest-x2 --passes 1

    CURRENT="--passes with nothing after it"
    refuse "the suite leg runs 1 or 2 whole passes" --leg pytest-x2 --shard 1/3 --passes

    CURRENT="--passes 0, 3 and x"
    refuse "the suite leg runs 1 or 2 whole passes" --leg pytest-x2 --shard 1/3 --passes 0
    refuse "the suite leg runs 1 or 2 whole passes" --leg pytest-x2 --shard 1/3 --passes 3
    refuse "the suite leg runs 1 or 2 whole passes" --leg pytest-x2 --shard 1/3 --passes x
    refuse "the suite leg runs 1 or 2 whole passes" --leg pytest-x2 --shard 1/3 --passes=x

    CURRENT="--passes 1 with --store-durations (two ways to say pass 2 is not run)"
    refuse "two ways to say pass 2 is not run" --leg pytest-x2 --shard 1/3 --passes 1 --store-durations

    # DERIVED FROM THE LISTING, the shape `case_shard_on_a_non_pytest_unit_is_
    # exit_2` established: the rule is not "the unit is not called pytest-x2",
    # it is "the unit's composed-of does not name the suite leg". Only an
    # N-capable one can get this far — an indivisible unit is refused for the
    # shard first — so the population is derived and the case says how many it
    # found.
    local unit shards legs driven=0
    run_listing_here
    if [ "$LIST_RC" != "0" ]; then
        bad "--list-legs exits ${LIST_RC}, so there are no units to refuse"
        return 0
    fi
    while IFS=$'\t' read -r unit _needs shards legs; do
        [ -n "${unit:-}" ] || continue
        [ "$shards" = "N-capable" ] || continue
        case ",${legs}," in
        *,pytest-x2,*) continue ;;
        esac
        CURRENT="--passes 1 on '${unit}', an N-capable unit that runs no suite"
        refuse "that unit runs no suite" --leg "$unit" --shard 1/3 --passes 1
        driven=$((driven + 1))
    done <"$LIST_OUT"
    CURRENT="every N-capable unit with no suite refuses a pass count"
    if [ "$driven" -ge 1 ]; then
        ok "${driven} suiteless N-capable unit(s), each refused by name"
    else
        bad "no suiteless N-capable unit was driven — this half of a.2 asserted nothing"
    fi

    CURRENT="--passes outside a unit run is exit 2 (a modifier a mode does not honour is never consumed)"
    rc=0
    (cd "$ROOT" && ./scripts/check.sh --loop --passes 1) >"$out" 2>&1 || rc=$?
    # The sentence, not only the status — the case above argues why in full.
    if [ "$rc" = "2" ] && grep -qF -- 'unexpected extra arguments: --passes 1' "$out"; then
        ok "exit 2, and it is the parser refusing the modifier: $(sed -n 1p "$out")"
    elif [ "$rc" = "2" ]; then
        bad "exit 2, but for some other reason — a --passes this mode does not honour must be refused BY NAME: $(sed -n 1p "$out")"
    else
        bad "exit ${rc} — a --passes was consumed by a mode that does not honour it"
    fi
}

case_composed_of_names_the_pass_count() {
    # The banner's `composed-of:` is THIS RUN'S composition, and the
    # row downstream reads it: a one-pass shard that named `pytest-x2` could
    # not be told from a two-pass one. The grammar is `<leg>[/<passes>]` and
    # absent means 2 — so the default must be byte-identical to today, and that
    # half is asserted here rather than assumed.
    local listed want one two absent
    run_listing_here
    if [ "$LIST_RC" != "0" ]; then
        bad "--list-legs exits ${LIST_RC}, so there is nothing to compose"
        return 0
    fi
    listed=$(awk -F'\t' '$1 == "pytest-x2" { print $4 }' "$LIST_OUT")
    [ -n "$listed" ] ||
        cannot_look "the listing has no pytest-x2 row — the unit this criterion is about is not there"

    CURRENT="--passes absent: composed-of is the listing's own row, unchanged"
    dry_unit pytest-x2 --shard 1/3 >/dev/null
    absent=$(banner_line "${WORK}/dry-unit.out" '  composed-of: ')
    cp "${WORK}/dry-unit.out" "${WORK}/dry-absent.out"
    if [ "$absent" = "$listed" ]; then
        ok "composed-of: ${absent}"
    else
        bad "the default run's composition is not the listing's row
    listing: ${listed}
    banner:  ${absent}"
    fi

    CURRENT="--passes 1: the suite member carries /1 and nothing else moves"
    want=$(printf '%s' ",${listed}," | sed 's|,pytest-x2,|,pytest-x2/1,|' | sed 's|^,||; s|,$||')
    dry_unit pytest-x2 --shard 1/3 --passes 1 >/dev/null
    one=$(banner_line "${WORK}/dry-unit.out" '  composed-of: ')
    if [ "$one" = "$want" ]; then
        ok "composed-of: ${one}"
    else
        bad "the one-pass composition is not the seam grammar
    want: ${want}
    got:  ${one}"
    fi

    CURRENT="and --passes 2 is the default SPELLED OUT: it prints nothing new"
    dry_unit pytest-x2 --shard 1/3 --passes 2 >/dev/null
    two=$(banner_line "${WORK}/dry-unit.out" '  composed-of: ')
    if [ "$two" != "$absent" ]; then
        bad "spelling the default changed the composition
    absent:     ${absent}
    --passes 2: ${two}"
    elif [ "$(banner_line "${WORK}/dry-unit.out" '- ')" != "$(banner_line "${WORK}/dry-absent.out" '- ')" ]; then
        bad "spelling the default changed the banner's own argv line:
    absent:     $(banner_line "${WORK}/dry-absent.out" '- ')
    --passes 2: $(banner_line "${WORK}/dry-unit.out" '- ')"
    else
        ok "two spellings of one run, one transcript: ${two}"
    fi
}

case_list_legs_carries_no_pass_count() {
    # The listing is the UNIT table and a pass count is a property of
    # a RUN, so no fifth field and no `/` anywhere in a composed-of member —
    # `ci.yml` reads column 3 and `case_the_build_contract_table_equals_the_
    # listing` byte-compares the whole table, both of which the pass count
    # leaves alone. Asserted rather than reported, because "I did not touch it" is a
    # claim and this is an artifact.
    local unit legs leg bad_rows="" rows=0 listed banner
    run_listing_here
    if [ "$LIST_RC" != "0" ]; then
        bad "--list-legs exits ${LIST_RC}, so there is no table to read"
        return 0
    fi
    CURRENT="no composed-of member carries a pass count"
    while IFS=$'\t' read -r unit _needs _shards legs; do
        [ -n "${unit:-}" ] || continue
        rows=$((rows + 1))
        for leg in $(printf '%s' "$legs" | tr ',' ' '); do
            case "$leg" in
            */*) bad_rows="${bad_rows}${bad_rows:+; }${unit}: '${leg}'" ;;
            esac
        done
    done <"$LIST_OUT"
    if [ -z "$bad_rows" ]; then
        ok "${rows} unit(s), no '/' in any member — the pass count never reaches the table"
    else
        bad "the listing carries a run's pass count: ${bad_rows}"
    fi

    # THE TIE, so "the listing is untouched" cannot drift apart from "the
    # default run is untouched": for the unit that grew the flag, the table's
    # row and a no-flag run's banner are the same string.
    CURRENT="and the pytest-x2 row still equals a default run's composition"
    listed=$(awk -F'\t' '$1 == "pytest-x2" { print $4 }' "$LIST_OUT")
    dry_unit pytest-x2 >/dev/null
    banner=$(banner_line "${WORK}/dry-unit.out" '  composed-of: ')
    if [ -n "$listed" ] && [ "$listed" = "$banner" ]; then
        ok "${listed}"
    else
        bad "the listing's row and a default run's banner disagree
    listing: ${listed:-<no pytest-x2 row>}
    banner:  ${banner}"
    fi
}

case_a_shard_forces_the_partition_to_measure_and_banks_nothing() {
    # G10.3, STATIC, and said so: driving it dynamically means a real
    # `pytest-x2` unit run with a planted partition row, which is the whole
    # suite twice inside the selftest leg of a gate that has already run it.
    # What is read here is the wiring in the leg that ships.
    local gate="${ROOT}/scripts/check.sh"
    CURRENT="a shard forces PARTITION_MODE=measure"
    if awk '
        /^if \[ -n "\$GATE_SHARD" \] \|\| \[ -n "\$GATE_STORE_DURATIONS" \]; then$/ { on = 1 }
        on && $0 == "    PARTITION_MODE=measure" { found = 1 }
        on && /^fi$/ { on = 0 }
        END { exit found ? 0 : 1 }' "$gate"; then
        ok "the shard arm in the partition leg sets PARTITION_MODE=measure"
    else
        bad "no shard arm forces the partition to measure — a shard would split a collection its siblings never saw"
    fi

    CURRENT="and it banks no partition row"
    if grep -q 'shard ${GATE_SHARD} banks nothing' "$gate"; then
        ok "the banking block has its own shard arm, printed rather than silent"
    else
        bad "the partition banking block has no shard arm"
    fi

    CURRENT="and no verdict row either"
    if grep -q 'no verdict recorded — --leg ${GATE_LEG_UNIT}' "$gate"; then
        ok "the verdict tail refuses every unit run, shard or not"
    else
        bad "the verdict tail has no --leg arm"
    fi
}

# --- THE SHARD CENSUS ---------------------------------------------------------
#
# THE CANARY THAT MAKES A STALE DURATIONS FILE HARMLESS. `pytest-split`
# partitions the COLLECTED node ids and balances the groups by recorded
# durations: a file naming tests that no longer exist, or no file at all,
# changes how BIG the groups are and never which tests are in one. That is the
# claim, and this is the instrument for it — the union over k of the shards'
# collections, against the whole collection, for three N under two seeds.
collect_ids() {
    local out=$1
    shift
    collect_ids_spawn "$out" "$@"
    collect_ids_drain
    collect_ids_read "$out"
}

# THE COLLECTIONS RUN CONCURRENTLY, AND THAT IS THE WHOLE OF THIS DRIVE'S COST.
# The shard census below is 22 `--collect-only` runs over the real suite at
# about 6.3 s each, and every one of them is READ-ONLY: pytest imports the
# tree, applies the split, prints node ids and exits. They share nothing a
# concurrent peer can move — except pytest's own cache directory, which is why
# `-p no:cacheprovider` is on every one of them: two collectors writing
# `.pytest_cache` in one rootdir is the one contention this shape has.
#
# BOUNDED AT FOUR, AND REAPED BY PID. This box has other builders on it and
# `scripts/test.sh` already refuses a builder taking the whole machine; four is
# a share, not a claim on the box. The pool drains in the foreground before any
# result is read — a collection this drive did not wait for is a collection it
# did not measure — and every wait is on a pid this function started
# (rung-execution section 5: never by name).
#
# THE STATUS IS NOT LOST. Each child writes its own exit code beside its
# transcript and `collect_ids_read` refuses on anything but 0, so a collection
# that failed is could-not-look at the moment it is READ rather than a silently
# empty id list — which is the same floor as `drive_capture_refusal`, made
# explicit here because the capture and its status arrive from another process.
COLLECT_MAX=4
COLLECT_PIDS=""
collect_ids_spawn() {
    local out=$1 running
    shift
    running=$(printf '%s\n' $COLLECT_PIDS | grep -c . || true)
    [ "$running" -lt "$COLLECT_MAX" ] || collect_ids_drain
    rm -f "${out}.rc"
    (
        rc=0
        # shellcheck disable=SC2086  # WORLD_TARGET is a path list, by design
        (cd "$ROOT" && uv run pytest --collect-only -q -p no:cacheprovider "$@" $WORLD_TARGET) >"$out" 2>&1 || rc=$?
        printf '%s\n' "$rc" >"${out}.rc"
    ) &
    COLLECT_PIDS="${COLLECT_PIDS} $!"
}

collect_ids_drain() {
    local pid
    for pid in $COLLECT_PIDS; do
        wait "$pid" 2>/dev/null || true
    done
    COLLECT_PIDS=""
}

collect_ids_read() {
    local out=$1 rc held
    [ -f "${out}.rc" ] ||
        cannot_look "a --collect-only left no status beside ${out} — it was read before it was waited for, or it never started"
    rc="$(cat "${out}.rc")"
    # THE TRANSCRIPT'S TAIL TRAVELS WITH THE REFUSAL, and it is not a nicety.
    # This refusal used to say only `see ${out}` — and `${out}` is under a
    # mktemp directory on whatever machine ran the drive. On a verifier box that
    # is a path that DIES WITH THE BOX: BOXBANK-22's whole red was one line
    # naming a file nobody could ever open again, and the cause it was hiding
    # (`LAYER 2 (named population): apps_root_modules (floor 5, derived 4
    # module(s))`) was one grep away from being in the bank's own log. A
    # could-not-look that points at a file the reader cannot reach is a
    # could-not-look nobody can act on.
    if [ "$rc" != "0" ]; then
        cannot_look "a --collect-only exited ${rc} (see ${out}) — its last lines:
$(grep -v '^[[:space:]]*$' "$out" 2>/dev/null | tail -5)"
    fi
    [ -s "$out" ] ||
        cannot_look "a --collect-only exited 0 and printed nothing (${out}) — an empty collection makes every union below vacuously equal"
    # THE WORLD FLOOR, ASSERTED WHERE THE IDS ARE READ rather than once at the
    # top: a world that emptied between two cases would otherwise be caught by
    # neither. A SHARD's own collection is legitimately a fraction of the
    # world and a NARROWED one is legitimately smaller still, so the caller
    # passes the minimum its own collection is a claim about — and a caller
    # that passes none is reading a shard, where the union it feeds is the
    # assertion.
    if [ -n "${2:-}" ]; then
        held=$(grep -c '::' "$out" || true)
        [ "$held" -ge "$2" ] ||
            cannot_look "the collection in ${out} held ${held} item(s), under the floor of ${2} this caller is a claim about — the fixture world did not install, or an app of it is gone, and every union below would be vacuously equal"
    fi
    grep '::' "$out" | LC_ALL=C sort
}

# split_flags <k> <N> — THE FLAGS THE GATE ITSELF WOULD CARRY, out of
# `gate_pytest_split_args`, never re-typed here.
#
# A CENSUS THAT TYPES ITS OWN FLAGS MEASURES ITS OWN TYPING. The whole claim of
# the shard census is "the shards the GATE runs partition the collection"; flags
# spelled a second time in this file are a second answer to what a shard is, and
# the day they drift the census goes on passing about a split nothing ships.
# This is `rung-execution` §2's "measure the leg you actually ship", at the one
# seam where it is cheap: the function is extracted and called, exactly as
# `gate_pytest_seed` and `pytest_x2_passes` are.
split_flags() {
    local k=$1 n=$2
    gate_fn gate_durations_path
    gate_fn gate_pytest_split_args
    (
        cd "$ROOT" || exit 2
        GATE_SHARD="${k}/${n}"
        GATE_SHARD_K=$k
        GATE_SHARD_N=$n
        GATE_STORE_DURATIONS=""
        GATE_SPLIT_ARGS=""
        gate_pytest_split_args >/dev/null
        printf '%s' "$GATE_SPLIT_ARGS"
    )
}

case_an_empty_fixture_world_is_could_not_look() {
    # THE CASE THAT MAKES EVERY GREEN BELOW MEAN SOMETHING. A union is equal to
    # a whole collection trivially when the whole collection is small, and
    # exactly when it is empty — so a world that failed to install, or that
    # lost an app, would take this whole census green and silent. The floor in
    # `collect_ids_read` is what stops that, and this is the plant that proves
    # the floor fires: the world runs one app short, and the refusal is
    # DRIVEN rather than asserted as a count.
    local out="${WORK}/collect-short-world.out" victim="world_delta" held rc=0 kept
    CURRENT="a world one app short collects fewer items than the floor"
    kept="$WORLD_TARGET"
    WORLD_TARGET=""
    local one
    for one in $kept; do
        case "$one" in
        "apps/${victim}") continue ;;
        esac
        WORLD_TARGET="${WORLD_TARGET} ${one}"
    done
    WORLD_TARGET="${WORLD_TARGET# }"
    collect_ids_spawn "$out" --randomly-seed=7
    collect_ids_drain
    held=$(grep -c '::' "$out" || true)
    if [ "$held" -lt "$WORLD_FLOOR" ]; then
        ok "${held} item(s) without apps/${victim}, under the floor of ${WORLD_FLOOR}"
    else
        bad "${held} item(s) without apps/${victim} — still at or above the floor of ${WORLD_FLOOR}, so removing an app of the world is invisible to it"
    fi

    CURRENT="and reading it as a whole collection is exit 2, not a small green"
    # In a subshell, because the refusal this drives is an `exit 2`: the point
    # is that a case reading a short world DIES instead of comparing unions.
    (collect_ids_read "$out" "$WORLD_FLOOR") >"${WORK}/short-world-read.out" 2>&1 || rc=$?
    if [ "$rc" = "2" ] && grep -F "under the floor of" "${WORK}/short-world-read.out" >/dev/null; then
        ok "exit 2, naming the floor: $(sed -n 1p "${WORK}/short-world-read.out" | cut -c1-120)"
    else
        bad "exit ${rc} — a short world was read as a whole collection: $(sed -n 1p "${WORK}/short-world-read.out")"
    fi

    CURRENT="and the world restored is above the floor again"
    WORLD_TARGET="$kept"
    collect_ids_spawn "${WORK}/collect-restored-world.out" --randomly-seed=7
    collect_ids_drain
    held=$(grep -c '::' "${WORK}/collect-restored-world.out" || true)
    if [ "$held" -ge "$WORLD_FLOOR" ]; then
        ok "${held} item(s) with all $(world_labels | grep -c .) app(s) — the floor is a floor and not a ban"
    else
        bad "${held} item(s) with the whole world installed — under the floor of ${WORLD_FLOOR}, so the world itself is short"
    fi
}

case_the_shards_partition_the_collection_for_three_n_and_two_seeds() {
    # G10.4. A FLOOR FIRST, and it is the fixture world's: the whole collection
    # must hold at least `WORLD_FLOOR` items or every union below is trivially
    # equal to every other and the case proves nothing.
    # `case_an_empty_fixture_world_is_could_not_look` drives that refusal.
    local seed n k whole union dupes missing extra
    # PHASE ONE: every collection this case needs, launched into the pool. The
    # flags are the ones asserted below, built here by the same `split_flags`.
    for seed in 7 4242; do
        collect_ids_spawn "${WORK}/collect-whole-${seed}.out" --randomly-seed="$seed"
        for n in 1 3 7; do
            k=1
            while [ "$k" -le "$n" ]; do
                # shellcheck disable=SC2046  # the gate's own flag string word-splits, by design
                collect_ids_spawn "${WORK}/collect-${seed}-${n}-${k}.out" \
                    --randomly-seed="$seed" $(split_flags "$k" "$n")
                k=$((k + 1))
            done
        done
    done
    collect_ids_drain

    # PHASE TWO: read and assert, over exactly the transcripts phase one made.
    for seed in 7 4242; do
        whole=$(collect_ids_read "${WORK}/collect-whole-${seed}.out" "$WORLD_FLOOR")
        CURRENT="the whole collection at seed ${seed} clears the fixture world's floor"
        if [ "$(printf '%s\n' "$whole" | grep -c .)" -lt "$WORLD_FLOOR" ]; then
            bad "the whole collection holds fewer than ${WORLD_FLOOR} items — every union below would be vacuously equal"
            return 0
        fi
        ok "$(printf '%s\n' "$whole" | grep -c .) item(s)"
        for n in 1 3 7; do
            CURRENT="N=${n} at seed ${seed}: the shards partition the collection"
            union=""
            k=1
            while [ "$k" -le "$n" ]; do
                union="${union}$(collect_ids_read "${WORK}/collect-${seed}-${n}-${k}.out")
"
                k=$((k + 1))
            done
            union=$(printf '%s' "$union" | grep -v '^$' | LC_ALL=C sort)
            dupes=$(printf '%s\n' "$union" | uniq -d)
            missing=$(comm -23 <(printf '%s\n' "$whole") <(printf '%s\n' "$union" | LC_ALL=C sort -u))
            extra=$(comm -13 <(printf '%s\n' "$whole") <(printf '%s\n' "$union" | LC_ALL=C sort -u))
            if [ -z "$dupes" ] && [ -z "$missing" ] && [ -z "$extra" ]; then
                ok "$(printf '%s\n' "$union" | grep -c .) item(s) across ${n} shard(s), disjoint, union == the whole collection"
            else
                bad "N=${n} seed=${seed}: in two shards '$(printf '%s' "$dupes" | head -c 120)' · in no shard '$(printf '%s' "$missing" | head -c 120)' · not in the collection '$(printf '%s' "$extra" | head -c 120)'"
            fi
        done
    done
}

case_the_partition_holds_under_the_real_worker_count() {
    # G10.4, and rung-execution §2's own rule: a drive that exercised a SERIAL
    # approximation of a parallel leg has measured its approximation. The split
    # is applied in `pytest_collection_modifyitems`, and under xdist every
    # WORKER collects for itself — so the composition of pytest-split's split
    # with xdist's distribution is what has to be shown, not the split alone.
    #
    # OVER THE FIXTURE WORLD, RUN FOR REAL at the gate's own worker count. The
    # whole suite twice over per shard is the alternative, inside the selftest
    # leg of a gate that has already run it once — and the composition being
    # shown (pytest-split's grouping under xdist's distribution) is a property
    # of the two plugins, which fifty items exercise exactly as four thousand
    # do. These are the world's plain modules: no fixture, no database, no
    # organ, so a real run of them is a real run and costs a second.
    local target="apps/world_alpha/tests/test_plain.py apps/world_beta/tests/test_plain.py apps/world_gamma/tests/test_plain.py apps/world_delta/tests/test_plain.py"
    local workers=2 n=2 k whole union dupes missing extra xml
    CURRENT="the unsharded run at -n ${workers} over ${target}"
    xml="${WORK}/junit-whole.xml"
    # shellcheck disable=SC2086  # the target is a path list, by design
    (cd "$ROOT" && uv run pytest -n "$workers" --randomly-seed=7 --junitxml="$xml" $target) \
        >"${WORK}/xdist-whole.out" 2>&1 || cannot_look "the unsharded target run failed (see ${WORK}/xdist-whole.out)"
    whole=$(grep -o 'classname="[^"]*" name="[^"]*"' "$xml" | LC_ALL=C sort)
    if [ "$(printf '%s\n' "$whole" | grep -c .)" -lt 1 ]; then
        bad "the target collected nothing at -n ${workers} — this case has no subject"
        return 0
    fi
    ok "$(printf '%s\n' "$whole" | grep -c .) test(s) ran across ${workers} worker(s)"

    CURRENT="N=${n} at -n ${workers}: the shards partition what the workers ran"
    union=""
    k=1
    while [ "$k" -le "$n" ]; do
        xml="${WORK}/junit-${k}.xml"
        # shellcheck disable=SC2086
        (cd "$ROOT" && uv run pytest -n "$workers" --randomly-seed=7 \
            $(split_flags "$k" "$n") \
            --junitxml="$xml" $target) \
            >"${WORK}/xdist-${k}.out" 2>&1 || cannot_look "shard ${k}/${n} of the target failed (see ${WORK}/xdist-${k}.out)"
        union="${union}$(grep -o 'classname="[^"]*" name="[^"]*"' "$xml" | LC_ALL=C sort)
"
        k=$((k + 1))
    done
    union=$(printf '%s' "$union" | grep -v '^$' | LC_ALL=C sort)
    dupes=$(printf '%s\n' "$union" | uniq -d)
    missing=$(comm -23 <(printf '%s\n' "$whole") <(printf '%s\n' "$union" | LC_ALL=C sort -u))
    extra=$(comm -13 <(printf '%s\n' "$whole") <(printf '%s\n' "$union" | LC_ALL=C sort -u))
    if [ -z "$dupes" ] && [ -z "$missing" ] && [ -z "$extra" ]; then
        ok "$(printf '%s\n' "$union" | grep -c .) test(s) across ${n} shard(s) at -n ${workers}, disjoint, union == the unsharded run"
    else
        bad "under real workers: in two shards '${dupes}' · in no shard '${missing}' · not in the whole run '${extra}'"
    fi
}

case_a_missing_durations_file_still_partitions_and_says_so() {
    # G10.4. A stale or absent durations file only UNBALANCES — the groups are
    # chunked by count and every collected test is still in exactly one of them.
    # The plugin says so in its own words and the leg says so in ours.
    local out="${WORK}/collect-nodurations.out" absent="${WORK}/no-such-durations.json" ids
    CURRENT="a --splits with a durations path that does not exist"
    rm -f "$absent"
    ids=$(collect_ids "$out" --randomly-seed=7 --splits 3 --group 1 --durations-path "$absent")
    if [ "$(printf '%s\n' "$ids" | grep -c .)" -ge 1 ]; then
        ok "$(printf '%s\n' "$ids" | grep -c .) item(s) still collected"
    else
        bad "a missing durations file emptied the shard"
    fi
    if grep -qi 'no test durations found' "$out"; then
        ok "and the plugin says so: $(grep -i -m1 'no test durations found' "$out" | cut -c1-96)"
    else
        bad "the plugin split with no durations and never said which of the two it was on"
    fi

    CURRENT="and the leg prints the unbalanced-split note when the file is absent"
    x2_ready
    x2_argv "${WORK}/argv-nodurations.log" 'GATE_SHARD=1/3 GATE_SHARD_K=1 GATE_SHARD_N=3'
    if grep -q 'durations: none — unbalanced split' "${WORK}/x2-drive.out"; then
        ok "$(grep -m1 'durations: none' "${WORK}/x2-drive.out" | sed 's/^  //')"
    else
        bad "the leg split with no durations file and printed no note about it"
    fi
}

case_a_durations_path_outside_the_rootdir_is_exit_2() {
    # G10F2.2. NOT A STALE FILE AND NOT A MISSING ONE — the third shape, and the
    # only one of the three that is dangerous: handed a path OUTSIDE pytest's
    # rootdir, `pytest-split` neither warns nor fails, it silently collapses the
    # partition. V-G10 measured a 3-way split of 3,822 items coming back as 3, 3
    # and 1 items, exit 0. A shard that judged three tests and went green is not
    # a smaller run; it is a green that means nothing, which is the worst shape
    # a selection defect can take. So the gate refuses the path instead.
    local rc out="${WORK}/durations-outside.out"
    gate_fn gate_durations_path
    for bad_path in "/tmp/zzz-djb-durations.json" "../zzz-djb-durations.json" "scripts/../../zzz.json"; do
        CURRENT="--durations-path ${bad_path}"
        rc=0
        (cd "$ROOT" && DJB_GATE_DURATIONS_PATH="$bad_path" gate_durations_path) >"$out" 2>&1 || rc=$?
        if [ "$rc" != "2" ]; then
            bad "exit ${rc} — an outside durations path was answered with a run"
        elif ! grep -q "$(cd "$ROOT" && pwd -P)" "$out"; then
            bad "the refusal does not name the rootdir it measured against: $(sed -n 1p "$out")"
        elif ! grep -qF -- "$bad_path" "$out"; then
            bad "the refusal does not name the path it refused: $(sed -n 1p "$out")"
        else
            ok "exit 2, naming both: $(sed -n 1p "$out")"
        fi
    done

    CURRENT="and the path the gate actually carries is accepted"
    rc=0
    (cd "$ROOT" && gate_durations_path) >"$out" 2>&1 || rc=$?
    if [ "$rc" = "0" ] && [ "$(cat "$out")" = "scripts/pytest_durations.json" ]; then
        ok "the default resolves inside the rootdir: $(cat "$out")"
    else
        bad "exit ${rc} for the shipped path: $(sed -n 1p "$out")"
    fi
}

case_a_durations_file_naming_tests_that_no_longer_exist_still_partitions() {
    # G10.4's other half, and the one a stale file actually produces: names the
    # collection no longer has. The partition is over the COLLECTION; the
    # durations only weigh it.
    #
    # THE PLANT LIVES INSIDE THE CHECKOUT, AND THAT IS A MEASUREMENT, NOT A
    # PREFERENCE. A `--durations-path` pointing OUTSIDE the rootdir changes what
    # pytest collects: driven here, an absolute path under the session
    # scratchpad produced `1 error during collection` and a 7-item collection
    # out of `deploy/`, where the same content inside the checkout collected the
    # ordinary 3,619. The shipped path is `scripts/pytest_durations.json` — in
    # the tree — so the plant goes in the tree too, at a `zzz_` name no product
    # can own, and is removed by the case and by the exit trap both.
    local stale="${ROOT}/.zzz-stale-durations.json" out="${WORK}/collect-stale.out" n whole union k dupes missing extra
    CURRENT="the plant's own path is free"
    if [ -e "$stale" ]; then
        cannot_look ".zzz-stale-durations.json already exists in this tree — this case will not overwrite a file it did not create"
    fi
    ok ".zzz-stale-durations.json is this case's to create"
    drive_at_exit "rm -f \"$stale\""
    CURRENT="a durations file naming nothing that exists"
    cat >"$stale" <<'STALE'
{
    "apps/zzz_gone/tests/test_gone.py::test_one": 12.5,
    "apps/zzz_gone/tests/test_gone.py::test_two": 3.25
}
STALE
    n=3
    collect_ids_spawn "${WORK}/collect-stale-whole.out" --randomly-seed=7
    k=1
    while [ "$k" -le "$n" ]; do
        collect_ids_spawn "${out}.${k}" --randomly-seed=7 --splits "$n" --group "$k" --durations-path "$stale"
        k=$((k + 1))
    done
    collect_ids_drain
    whole=$(collect_ids_read "${WORK}/collect-stale-whole.out" "$WORLD_FLOOR")
    union=""
    k=1
    while [ "$k" -le "$n" ]; do
        union="${union}$(collect_ids_read "${out}.${k}")
"
        k=$((k + 1))
    done
    union=$(printf '%s' "$union" | grep -v '^$' | LC_ALL=C sort)
    dupes=$(printf '%s\n' "$union" | uniq -d)
    missing=$(comm -23 <(printf '%s\n' "$whole") <(printf '%s\n' "$union" | LC_ALL=C sort -u))
    extra=$(comm -13 <(printf '%s\n' "$whole") <(printf '%s\n' "$union" | LC_ALL=C sort -u))
    if [ -z "$dupes" ] && [ -z "$missing" ] && [ -z "$extra" ]; then
        ok "$(printf '%s\n' "$union" | grep -c .) item(s) across ${n} shard(s), disjoint, union == the whole collection"
    else
        bad "a stale durations file moved the PARTITION, not just the balance: two '${dupes}' · none '${missing}' · extra '${extra}'"
    fi
    rm -f "$stale"
}

case_collectstatic_is_a_leg_in_the_static_unit() {
    # G10.7. It was a step in `ci.yml`; a YAML step conditioned on which unit is
    # running would be CI typing a leg name, which is the drift the unit table
    # exists to stop.
    local legs
    CURRENT="collectstatic is a leg a full run announces"
    case ",${FULL_LEGS_STRING}," in
    *,collectstatic,*) ok "named in FULL_LEGS, so every verdict row carries it" ;;
    *) bad "FULL_LEGS does not name collectstatic" ;;
    esac

    CURRENT="and it is a member of the static unit"
    run_listing_here
    legs=$(awk -F'\t' '$1 == "static" { print $4 }' "$LIST_OUT")
    case ",${legs}," in
    *,collectstatic,*) ok "the static unit's composed-of names it" ;;
    *) bad "the static unit does not hold collectstatic: ${legs}" ;;
    esac

    CURRENT="and the --loop transcript does NOT announce it"
    case " $(dry_sequence --loop) " in
    *" collectstatic "*) bad "the per-rung gate now pays for collectstatic on every run" ;;
    *) ok "announced on the full path only — below the --loop block's own exit" ;;
    esac
}

case_the_loop_leg_carries_no_split() {
    # G10.10. A loop is never sharded, and a bare full gate never is either: the
    # split flags exist in ONE assembly, and it is the pytest-x2 leg's.
    local gate="${ROOT}/scripts/check.sh" hits
    CURRENT="the split flags are assembled in exactly one place"
    hits=$(grep -c -- '--splits' "$gate")
    if [ "$hits" = "1" ]; then
        ok "one --splits in the whole file, in gate_pytest_split_args"
    else
        bad "${hits} --splits site(s) — two assemblies are two answers to what a pass carries"
    fi

    CURRENT="and the per-rung pytest leg carries none"
    if awk '
        /^    gate_leg_pytest\(\) \{$/ { on = 1 }
        on && /--splits|--durations-path|--store-durations/ { found = 1 }
        on && /^    \}$/ { on = 0 }
        END { exit found ? 1 : 0 }' "$gate"; then
        ok "gate_leg_pytest mentions no split flag at all"
    else
        bad "the --loop pytest leg carries a split flag — a loop is never sharded"
    fi
}

case_the_full_gate_leg_carries_no_split() {
    # G10.10, the other half, driven rather than read: a bare `pytest-x2` with
    # no shard and no --store-durations hands the two passes no split flags.
    local log="${WORK}/argv-bare.log"
    CURRENT="a bare pytest-x2 hands the passes no split flags"
    x2_ready
    x2_argv "$log" 'true'
    if grep -qE -- '--splits|--group |--durations-path|--store-durations' "$log"; then
        bad "a bare full gate carried a split: $(sed -n 1p "$log")"
    else
        ok "2 invocations, neither carrying a split flag: $(sed -n 1p "$log")"
    fi
}

case_the_shards_partition_the_pr_scope_too() {
    # G10.8, and `build-contract.md`'s reader clause: "this repository's own
    # ci.yml gains that line in the wave that lands the sharded CI gate". The
    # two narrowings are BOTH pytest flags on the same argument list — the
    # `--pr` scope replaces `$PARTITION_TARGETS`, the split joins it — so the
    # property to show is that the shards still partition, over the NARROWED
    # collection.
    #
    # THE SCOPE FLAGS ARE THE ONES THE GATE EMITS, not an invention:
    # `loop_scope__pytest_args` (scripts/loop_tier.sh) prints
    # `--djb-scope-narrow` and one `--djb-scope=<label>` per app, and that is
    # what `--pr` appends. The scope named is ONE of the fixture world's four
    # apps, so the narrowing is real — the other three apps' ordinary modules
    # are outside it — and the assertion below refuses a run that deselected
    # nothing rather than letting an unnarrowed census read as a narrowed one.
    local n=3 k whole union dupes missing extra rc=0
    CURRENT="the --pr scope narrows, so there is something to partition"
    collect_ids_spawn "${WORK}/collect-pr-whole.out" --randomly-seed=7 --djb-scope-narrow --djb-scope=world_alpha
    k=1
    while [ "$k" -le "$n" ]; do
        # shellcheck disable=SC2046  # the gate's own flag string word-splits, by design
        collect_ids_spawn "${WORK}/collect-pr-${k}.out" --randomly-seed=7 \
            --djb-scope-narrow --djb-scope=world_alpha \
            $(split_flags "$k" "$n")
        k=$((k + 1))
    done
    collect_ids_drain
    whole=$(collect_ids_read "${WORK}/collect-pr-whole.out" "$WORLD_NARROWED_FLOOR")
    if ! grep -q 'deselected' "${WORK}/collect-pr-whole.out"; then
        bad "the scope flags deselected nothing — this case would be the unnarrowed census again"
        return 0
    fi
    ok "$(printf '%s\n' "$whole" | grep -c .) item(s): $(grep -m1 'deselected' "${WORK}/collect-pr-whole.out")"

    CURRENT="N=${n} over the --pr scope: the shards partition it"
    union=""
    k=1
    while [ "$k" -le "$n" ]; do
        union="${union}$(collect_ids_read "${WORK}/collect-pr-${k}.out")
"
        k=$((k + 1))
    done
    union=$(printf '%s' "$union" | grep -v '^$' | LC_ALL=C sort)
    dupes=$(printf '%s\n' "$union" | uniq -d)
    missing=$(comm -23 <(printf '%s\n' "$whole") <(printf '%s\n' "$union" | LC_ALL=C sort -u))
    extra=$(comm -13 <(printf '%s\n' "$whole") <(printf '%s\n' "$union" | LC_ALL=C sort -u))
    if [ -z "$dupes" ] && [ -z "$missing" ] && [ -z "$extra" ]; then
        ok "$(printf '%s\n' "$union" | grep -c .) item(s) across ${n} shard(s), disjoint, union == the --pr selection"
    else
        bad "over the --pr scope: two '${dupes}' · none '${missing}' · extra '${extra}'"
    fi

    CURRENT="--pr under --leg still needs its --base"
    (cd "$ROOT" && ./scripts/check.sh --leg pytest-x2 --shard 1/3 --pr) >"${WORK}/leg-pr-nobase.out" 2>&1 || rc=$?
    if [ "$rc" = "2" ] && grep -q -- '--pr needs --base' "${WORK}/leg-pr-nobase.out"; then
        ok "exit 2: $(sed -n 1p "${WORK}/leg-pr-nobase.out")"
    else
        bad "exit ${rc}: $(sed -n 1p "${WORK}/leg-pr-nobase.out")"
    fi

    CURRENT="and the two narrowings land on ONE argument list"
    if grep -q 'X2_PASS_ARGS="${PARTITION_TARGETS}${GATE_SPLIT_ARGS:+ ${GATE_SPLIT_ARGS}}${GATE_X2_COUNTS_ARG:+ ${GATE_X2_COUNTS_ARG}}"' "${ROOT}/scripts/check.sh"; then
        ok "the scope, the split and the counts flag are one string both passes are handed"
    else
        bad "the pass arguments are no longer assembled in one place — two narrowings in two strings is two things to keep in step"
    fi
}

case_clone_into_gets_a_main_from_either_source_shape() {
    # HL.2. The drive's own clone step, run from BOTH source shapes — because it
    # had only ever been run from one. Every `--loop` and every verifier clone
    # runs this drive from a rung worktree, where the clone arrives with no local
    # `main`; the merge train's bank runs the full gate on the PRIMARY, whose
    # HEAD is `main`, where the clone arrives WITH one. The second shape took a
    # whole bank to exit 2 (BANK-3, 2026-09-16) and no case had ever been in it.
    #
    # The step is exercised through `ROOT` in a SUBSHELL: `cannot_look` exits,
    # and this case's whole point is to survive the exit and read the sentence.
    local src="${WORK}/hl-src" out="${WORK}/hl-clone-into.out" want rc broke=""
    local branch="hl-scratch-rung-branch"

    CURRENT="clone_into gives the clone a main from a source on main AND from one on a rung branch"
    # THE BASE IS DERIVED, NOT SPELLED `main`. This line used to be
    # `git -C "$ROOT" rev-parse --verify -q main`, which is exit 1 on a runner:
    # `actions/checkout` detaches HEAD and creates no local branch, so the case
    # reported "this checkout has no local main" and asserted nothing while a
    # perfectly good `refs/remotes/origin/main` sat beside it unasked. The
    # reader in `drive_preamble.sh` §8 answers for every shape, and a REFUSAL
    # from it is could-not-look (exit 2) rather than a red: a case with no base
    # ref has not cleared itself.
    local base
    base="$(drive_base_ref "$ROOT")" ||
        cannot_look "no base ref in ${ROOT} — this case has no sha to aim at"
    want=$(git -C "$ROOT" rev-parse --verify -q "${base}^{commit}") || {
        bad "the base ref ${base} does not resolve to a commit in ${ROOT}"
        return 0
    }
    rm -rf "$src"
    git clone --quiet --shared --no-hardlinks "$ROOT" "$src" >/dev/null 2>&1 || {
        bad "could not make the scratch source checkout in ${src}"
        return 0
    }

    # (a) the bank's shape: the source checkout's HEAD IS `main`.
    git -C "$src" checkout --quiet -B main "$want" >/dev/null 2>&1 || {
        bad "could not put the scratch source checkout on main"
        return 0
    }
    rm -rf "${WORK}/hl-from-main"
    rc=0
    (
        ROOT="$src"
        clone_into "${WORK}/hl-from-main"
    ) >"$out" 2>&1 || rc=$?
    if [ "$rc" != "0" ]; then
        broke="from a source on main the step exited ${rc}: $(sed -n 1p "$out")"
    elif [ "$(git -C "${WORK}/hl-from-main" rev-parse --verify -q main 2>/dev/null)" != "$want" ]; then
        broke="from a source on main the clone's main is not ${want}"
    fi

    # (b) the shape every --loop has always been in: HEAD is a rung branch, so
    #     the clone arrives with no local `main` at all.
    git -C "$src" checkout --quiet -B "$branch" "$want" >/dev/null 2>&1 || {
        bad "could not put the scratch source checkout on a rung branch"
        return 0
    }
    rm -rf "${WORK}/hl-from-rung"
    rc=0
    (
        ROOT="$src"
        clone_into "${WORK}/hl-from-rung"
    ) >"$out" 2>&1 || rc=$?
    if [ "$rc" != "0" ]; then
        broke="${broke}${broke:+; }from a source on a rung branch the step exited ${rc}: $(sed -n 1p "$out")"
    elif [ "$(git -C "${WORK}/hl-from-rung" rev-parse --verify -q main 2>/dev/null)" != "$want" ]; then
        broke="${broke}${broke:+; }from a source on a rung branch the clone's main is not ${want}"
    fi

    if [ -z "$broke" ]; then
        ok "both shapes proceeded and the clone's main is ${want}: HEAD main (arrived with one, asserted) and HEAD ${branch} (none, created)"
    else
        bad "$broke"
    fi
    rm -rf "$src" "${WORK}/hl-from-main" "${WORK}/hl-from-rung"
}

case_the_dry_loop_derives_a_scope_from_a_source_ahead_of_main() {
    # G10F.2, and it is the THIRD source shape — the one neither case beside it
    # was ever in. `clone_into` answers "does the clone get a `main`"; this
    # answers the question after it: with a `main` AND commits past it, the dry
    # `--loop` has changed files to classify, and classifying them walks the app
    # declarations with an interpreter the clone does not have.
    #
    # THE CHANGED PATH IS AN `apps/` ONE, DELIBERATELY. A rung ahead of `main`
    # by `scripts/` alone derives FULL and walks no closure — green, and the
    # reason this drive's own worktree never showed the defect while P6's
    # `apps/` rung paid a whole sanctioned full gate for it.
    #
    # BOTH SURVIVING SHAPES ARE RE-ASSERTED HERE, not assumed: a clone of a
    # source ON `main` (the merge train's bank) has nothing to classify and must
    # stay green, which is the shape HOTFIX-LISTLEGS closed.
    local src="${WORK}/g10f-src" out="${WORK}/g10f-dry.out" want rc broke=""
    local branch="g10f-scratch-ahead-branch" probe="apps/example/services.py"

    CURRENT="a dry --loop in a clone of a source AHEAD of main derives its scope"
    # Derived, for the reason the case above states in full.
    local base
    base="$(drive_base_ref "$ROOT")" ||
        cannot_look "no base ref in ${ROOT} — this case has no sha to fork from"
    want=$(git -C "$ROOT" rev-parse --verify -q "${base}^{commit}") || {
        bad "the base ref ${base} does not resolve to a commit in ${ROOT}"
        return 0
    }
    [ -f "${ROOT}/${probe}" ] || {
        bad "${probe} is not in this tree — the case needs one real app path to put ahead of main"
        return 0
    }
    rm -rf "$src"
    git clone --quiet --shared --no-hardlinks "$ROOT" "$src" >/dev/null 2>&1 || {
        bad "could not make the scratch source checkout in ${src}"
        return 0
    }
    git -C "$src" checkout --quiet -B main "$want" >/dev/null 2>&1 &&
        git -C "$src" checkout --quiet -b "$branch" >/dev/null 2>&1 || {
        bad "could not put the scratch source checkout on a rung branch cut from main"
        rm -rf "$src"
        return 0
    }
    # ITS OWN VICTIM: the commit is made in the scratch source and nowhere else.
    printf '\n# g10f probe\n' >>"${src}/${probe}"
    git -C "$src" add "$probe" >/dev/null 2>&1
    git -C "$src" -c user.email=drive@example.invalid -c user.name="list legs drive" \
        commit -q -m "probe: one app path ahead of main" >/dev/null 2>&1 || {
        bad "could not commit the probe path in the scratch source"
        rm -rf "$src"
        return 0
    }

    rm -rf "${WORK}/g10f-ahead"
    rc=0
    (
        ROOT="$src"
        clone_into "${WORK}/g10f-ahead"
    ) >"$out" 2>&1 || rc=$?
    # OUTSIDE THE `ROOT` OVERRIDE, and that is the point: `clone_into` must read
    # the SCRATCH source's `main`, while the interpreter is lent by THIS
    # checkout — the scratch source has no `.venv` and was never going to.
    [ "$rc" != "0" ] || clone_borrows_interpreter "${WORK}/g10f-ahead"
    if [ "$rc" != "0" ]; then
        bad "the clone step exited ${rc} from a source ahead of main: $(sed -n 1p "$out")"
        rm -rf "$src" "${WORK}/g10f-ahead"
        return 0
    fi
    rc=0
    (
        cd "${WORK}/g10f-ahead" &&
            DJB_GATE_LEGS_DRY=1 \
                DJB_GATE_LEASE_DIR="${WORK}/lease" \
                DJB_LOOP_HERE="$DRY_LOOP_HERE" \
                DJB_GATE_SANCTION="test_list_legs: the ahead-of-main dry scope" \
                ./scripts/check.sh --loop
    ) >"$out" 2>&1 || rc=$?
    if [ "$rc" != "0" ]; then
        broke="the dry --loop exited ${rc}: $(sed -n 1p "$out")"
    elif ! grep -q 'scope   touched: example' "$out"; then
        broke="the dry --loop derived no scope for the probe app: $(grep -m1 'scope   touched' "$out")"
    fi
    if [ -z "$broke" ]; then
        ok "exit 0 and the scope was derived: $(grep -m1 'scope   touched' "$out" | sed 's/^  //')"
    else
        bad "$broke"
    fi

    CURRENT="and a clone of a source ON main is still green, with nothing to classify"
    git -C "$src" checkout --quiet main >/dev/null 2>&1
    rm -rf "${WORK}/g10f-onmain"
    rc=0
    (
        ROOT="$src"
        clone_into "${WORK}/g10f-onmain"
    ) >"$out" 2>&1 || rc=$?
    # OUTSIDE THE `ROOT` OVERRIDE, and that is the point: `clone_into` must read
    # the SCRATCH source's `main`, while the interpreter is lent by THIS
    # checkout — the scratch source has no `.venv` and was never going to.
    [ "$rc" != "0" ] || clone_borrows_interpreter "${WORK}/g10f-onmain"
    if [ "$rc" = "0" ]; then
        rc=0
        (
            cd "${WORK}/g10f-onmain" &&
                DJB_GATE_LEGS_DRY=1 \
                    DJB_GATE_LEASE_DIR="${WORK}/lease" \
                    DJB_LOOP_HERE="$DRY_LOOP_HERE" \
                    DJB_GATE_SANCTION="test_list_legs: the on-main dry scope" \
                    ./scripts/check.sh --loop
        ) >"$out" 2>&1 || rc=$?
    fi
    if [ "$rc" = "0" ]; then
        ok "exit 0 — the bank's shape is unaffected: $(grep -m1 'scope   touched' "$out" | sed 's/^  //')"
    else
        bad "the on-main shape exited ${rc}: $(sed -n 1p "$out")"
    fi
    rm -rf "$src" "${WORK}/g10f-ahead" "${WORK}/g10f-onmain"
}

echo "test_list_legs: the unit table and --list-legs"
echo

case_an_empty_capture_is_could_not_look
case_the_full_fast_and_loop_leg_sequences_are_unchanged_by_the_refactor
case_full_legs_equals_the_announced_full_sequence
case_an_announced_leg_missing_from_full_legs_is_exit_2
case_an_announced_leg_whose_body_is_not_behind_the_runner_is_exit_2
case_the_registered_population_has_one_writer
case_every_full_leg_is_in_exactly_one_unit
case_a_leg_in_two_units_is_exit_2
case_a_leg_in_no_unit_is_exit_2
case_a_unit_with_no_needs_declaration_is_exit_2
case_list_legs_prints_one_line_per_unit_in_the_grammar
case_list_legs_needs_no_venv_no_docker_and_is_fast
case_list_legs_precedes_the_lease
case_list_legs_with_an_argument_is_exit_2
case_an_unknown_flag_is_still_exit_2_with_the_same_sentence
case_the_usage_header_names_the_listing
case_every_drive_is_in_exactly_one_drives_unit
case_a_drive_that_appears_in_no_unit_or_two_is_exit_2
case_the_build_contract_table_equals_the_listing
case_leg_static_announces_its_legs_and_no_other
case_leg_takes_no_lease_no_lock_and_writes_no_verdict
case_leg_needs_no_sanction
case_an_unknown_unit_is_exit_2_naming_the_listing
case_leg_pytest_x2_takes_a_slot
case_a_typed_seed_reaches_both_passes
case_an_unparsable_seed_is_exit_2
case_shard_k_of_n_passes_split_and_group_to_both_passes_under_one_seed
case_shard_on_a_non_pytest_unit_is_exit_2
case_the_shard_census_reads_the_gates_own_flags
case_a_malformed_shard_pair_is_exit_2
case_an_empty_shard_is_exit_2
case_passes_1_runs_one_pass_and_says_so
case_passes_outside_a_shard_or_malformed_is_exit_2
case_composed_of_names_the_pass_count
case_list_legs_carries_no_pass_count
case_a_shard_forces_the_partition_to_measure_and_banks_nothing
case_an_empty_fixture_world_is_could_not_look
case_the_shards_partition_the_collection_for_three_n_and_two_seeds
case_the_partition_holds_under_the_real_worker_count
case_a_missing_durations_file_still_partitions_and_says_so
case_a_durations_file_naming_tests_that_no_longer_exist_still_partitions
case_a_durations_path_outside_the_rootdir_is_exit_2
case_collectstatic_is_a_leg_in_the_static_unit
case_the_loop_leg_carries_no_split
case_the_full_gate_leg_carries_no_split
case_the_shards_partition_the_pr_scope_too
case_clone_into_gets_a_main_from_either_source_shape
case_the_dry_loop_derives_a_scope_from_a_source_ahead_of_main

echo
echo "test_list_legs: ${PASSED} passed, ${FAILED} failed"
drive_finished
[ "$FAILED" -eq 0 ] || exit 1
exit 0
