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
# drives: .github/workflows/ci.yml deploy/provision.sh deploy/verifier/bake.sh scripts/check.sh scripts/db.sh scripts/gate_ledger.sh scripts/gate_refuse.sh scripts/githooks/pre-push scripts/kill_mine.sh scripts/pm_fold.sh scripts/pm_push.sh scripts/queue_cited.sh scripts/sweep.sh scripts/test_impact.json scripts/test_impact.py scripts/tests/drive_preamble.sh scripts/tests/test_pm_push.sh scripts/tests/test_verifier_box.sh scripts/verifier_box.sh
# cites: uv.lock scripts/local/legs
# A CITATION, NOT A SUBJECT: the docs-only cases below NAME `uv.lock`, because
# the declared list rules it OUT and the refusal that says so is the assertion.
# This drive never opens it, and declaring it as a subject would re-drive every
# case here on every resolve.
# The drive for `scripts/pm_push.sh --bank --on-boxes N` — the bank that moves
# the constraint off this laptop.
#
#   ./scripts/tests/test_pm_push.sh          run every case
#   ./scripts/tests/test_pm_push.sh --list   name them and stop
#
# WHY IT EXISTS. A bank is the one claim in this repository that a WHOLE tree
# passed a WHOLE gate, and `--on-boxes` earns that claim by composing it out of
# N partial runs on N machines nobody can see afterwards. Every way that
# composition can be wrong is silent by construction: a shard that measured a
# different tree, a shard whose leg set is short, a shard nobody could read, a
# box left billing after a Ctrl-C. Each of those would produce a green row over
# bytes no box ran, and a green row is exactly the thing the pre-push hook
# trusts without measuring. So each one is a case here, with its plant.
#
# IT BUILDS ITS OWN REPOSITORIES AND ITS OWN WORLD — `test_pm_merge.sh`'s idiom
# for the first half and `test_verifier_box.sh`'s for the second. Every case
# runs against a throwaway git repository under `mktemp -d` carrying a COPY of
# `pm_push.sh`, ITS OWN STUB `scripts/check.sh`, its own stub `pm_fold.sh` and
# its own stub `scripts/verifier_box.sh` that records every argv and answers
# `up`/`leg`/`wait`/`fetch`/`down` from per-case fixtures. Nothing here launches
# a machine, terminates one, runs the real gate or pushes anywhere but into a
# bare repository it made itself.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * THE REAL GATE. The scratch repositories carry a stub `check.sh` that
#     records its arguments and answers `--list-legs` from a fixture. These
#     cases prove the WIRING and the COMPOSITION; they prove nothing about
#     `scripts/check.sh` itself, which is measured everywhere else.
#   * THE REAL WRAPPER, AND THEREFORE THE REAL BOX. The stub asserts the SEAM's
#     argv — `up --for`, `leg <id> --unit U [--shard k/N] --log leg`,
#     `wait <id> leg`, `fetch`, `down` — and nothing about what
#     `scripts/verifier_box.sh` does with it. That is
#     `scripts/tests/test_verifier_box.sh`'s business and the field test's; the
#     first real on-box bank is the seam's own proof.
#   * A SHARD WHOSE GATE LIED. The box's `--leg` is the authority here exactly
#     as it is in CI. A log that says `ok` over a leg that did not run is
#     invisible to a composition, by construction.
#   * THE PUSH HOOK IN SITU. The scratch repositories do NOT wire
#     `core.hooksPath`, so the push at the end of a green bank runs no hook —
#     deliberately, because a hook that ran would reach for the real gate. The
#     hook is driven DIRECTLY instead, the way git calls it, in its own two
#     cases.
#   * WALL CLOCK. The stub answers instantly, so every measured wall here is
#     ~0s and what is asserted is that the FIELD is there and carries a number,
#     never what the number is. The walls are the measurement row's, on a real
#     bank.
set -euo pipefail

cd "$(dirname "$0")/../.."

# --- the drive preamble, and it comes before the first git command -----------
#
# `scripts/pm_push.sh` is the file whose `exec git -C <linked worktree> push`
# is the very mechanism the preamble exists for: it exports an absolute GIT_DIR
# into everything downstream, and an inherited GIT_DIR overrides every `-C`.
# This drive builds git repositories, so it is one signal away from the
# incident that preamble records.
[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_pm_push: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It carries the only thing keeping this drive's git commands inside its" >&2
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
CURRENT=""

cannot_look() {
    echo "!! test_pm_push: $*" >&2
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
    echo "!! unknown argument '$1': test_pm_push.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

command -v git >/dev/null 2>&1 || cannot_look "no git on PATH"
for _s in scripts/pm_push.sh scripts/gate_ledger.sh scripts/gate_refuse.sh \
    scripts/githooks/pre-push scripts/check.sh; do
    [ -f "$_s" ] || cannot_look "${_s} is not in this tree — there is nothing to drive"
done
unset _s

ROOT="$PWD"
SOURCE="$ROOT/scripts/pm_push.sh"
HOOK="$ROOT/scripts/githooks/pre-push"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-pm-push-drive.XXXXXX")" ||
    cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'chmod -R u+rwX "$WORK" 2>/dev/null || true; rm -rf "$WORK"'

# --- the listing this world is built from, read from the REAL gate -----------
#
# `--list-legs` is the one mode that sits ABOVE the lease, the lock and the slot
# (`scripts/check.sh`, the `GATE_LIST_LEGS` block), so asking the real gate for
# it from inside the selftest leg is legal where a nested `check.sh` would be
# refused for the lock. It is asked rather than typed for the same reason
# `pm_push.sh` asks it: a unit table copied into a drive is right on the day it
# is written.
REAL_LISTING="$WORK/listlegs.tsv"
if ! ./scripts/check.sh --list-legs >"$REAL_LISTING" 2>"$WORK/listlegs.err"; then
    sed 's/^/   | /' "$WORK/listlegs.err" >&2 || true
    cannot_look "./scripts/check.sh --list-legs exited non-zero — this drive's whole world is derived from it"
fi
[ -s "$REAL_LISTING" ] || cannot_look "./scripts/check.sh --list-legs printed nothing"

# shellcheck source=scripts/gate_refuse.sh
. scripts/gate_refuse.sh
# shellcheck source=scripts/gate_ledger.sh
. scripts/gate_ledger.sh
REAL_FULL_LEGS="$(gate_full_legs)"
[ -n "$REAL_FULL_LEGS" ] || cannot_look "scripts/check.sh declares no FULL_LEGS"
# WORLD_FULL_LEGS — what the stub gate in the next world declares, and it is a
# VARIABLE because the two halves of a world have to be composed under the same
# drawer. `gate_full_legs` reads the CHECKOUT's `scripts/local/legs/`, so a case
# that hands its world a listing composed under a DIFFERENT drawer and lets the
# stub echo this tree's leg set has built a world whose listing and whose
# FULL_LEGS disagree — and the bank correctly refuses it (`covered by no
# shard`). Every case but the drawer one wants this tree's own answer, so that
# is the default and `fresh_world` restores it.
WORLD_FULL_LEGS="$REAL_FULL_LEGS"
WORLD_FULL_LEGS_NEXT=""

# --- THE PLAN, DERIVED FROM THAT LISTING AND FROM THE SUBJECT ----------------
#
# WHY NOTHING BELOW IS TYPED. Every unit name, every shard count, every box
# count and the floor itself are facts about the tree this drive is running in,
# and a product that clones this template CHANGES THEM: X2's drawer gives a
# product's own leg its own `local` unit, so a consumer with one drawer leg
# declares six units where this template declares five. A drive that typed
# `selftest-2of3`, `--on-boxes 8` or `floor of 5` was not asserting the bank's
# behaviour — it was asserting this tree's unit table, and it reddened on THEIR
# first bank with the subject behaving perfectly (327/49 on their 3e6312cf).
# `pm_push.sh` derives its plan from `--list-legs`; so, from here, does this.
#
# THE SHAPE OF THE DERIVATION. Two layers. This block reads the LISTING alone —
# the units, which of them shard, and which carries the suite leg — and the
# probe case below runs ONE bank and reads the labels the SUBJECT produced,
# then asserts that set equals a set composed here from the listing. What the
# cases use is the intersection: derived from the listing, confirmed by the
# subject, and never a number a person typed.
PLAN_UNITS=0        # how many units this gate declares
PLAN_INDIV=""       # the indivisible units, in listing order
PLAN_CAPABLE=""     # the N-capable units, in listing order
PLAN_SUITE_LEG=""   # the suite leg's NAME, read out of the subject
PLAN_SUITE_UNIT=""  # the unit whose legs carry it, read out of the listing
PLAN_BOXES=0        # the N every ordinary case runs at
PLAN_FLOOR=0        # the DERIVED floor: one box per unit the listing declares
PLAN_TYPED_FLOOR=0  # the SYNTACTIC floor, read out of the subject's own constant
PLAN_LABELS=""      # every shard label the plan produces at PLAN_BOXES, in plan order
PLAN_FLAT=""        # the indivisible units' labels (each takes a whole box)
PLAN_FLAT1=""       # three of them by name, for the cases that perturb one box
PLAN_FLAT2=""
PLAN_FLAT3=""
PLAN_SUITE_FIRST="" # the suite unit's first and last shard
PLAN_SUITE_LAST=""
PLAN_SUITE_K=0
PLAN_VICTIM_UNIT="" # the LAST shardable unit — what the failure cases perturb
PLAN_VICTIM=""      # its last shard
PLAN_VICTIM_FIRST="" # its first shard
PLAN_VICTIM_K=0
PLAN_KILL_ALLOW=""  # the first three labels: "some boxes up, the rest in flight"

# THE SUITE LEG'S NAME COMES OUT OF THE SUBJECT, not out of this file: it is
# `pm_push.sh`'s own `BANK_SUITE_LEG`, the one leg name that file spells, and
# the unit carrying it is whatever the listing says. Typing it here would be a
# second opinion about the one thing the subject declares.
PLAN_SUITE_LEG="$(sed -n 's/^BANK_SUITE_LEG="\(.*\)"$/\1/p' "$SOURCE")"
PLAN_SUITE_LEG="${PLAN_SUITE_LEG%%$'\n'*}"
[ -n "$PLAN_SUITE_LEG" ] ||
    cannot_look "scripts/pm_push.sh declares no BANK_SUITE_LEG — every passes assertion here is about the unit that carries it"

PLAN_SUITE_UNIT="$(awk -F'\t' -v leg="$PLAN_SUITE_LEG" \
    '$4 ~ ("(^|,)" leg "(,|$)") { print $1; exit }' "$REAL_LISTING")"
[ -n "$PLAN_SUITE_UNIT" ] ||
    cannot_look "no unit in ./scripts/check.sh --list-legs carries the ${PLAN_SUITE_LEG} leg"

while IFS=$'\t' read -r _u _needs _shards _legs; do
    [ -n "$_u" ] || continue
    PLAN_UNITS=$((PLAN_UNITS + 1))
    if [ "$_shards" = "N-capable" ]; then
        PLAN_CAPABLE="${PLAN_CAPABLE}${PLAN_CAPABLE:+ }${_u}"
    else
        PLAN_INDIV="${PLAN_INDIV}${PLAN_INDIV:+ }${_u}"
    fi
done <"$REAL_LISTING"
unset _u _needs _shards _legs
[ "$PLAN_UNITS" -gt 0 ] || cannot_look "the listing declares no units at all"
[ -n "$PLAN_CAPABLE" ] ||
    cannot_look "this tree's listing has no N-capable unit — every sharded assertion below has no subject"

# THE FLOOR IS ONE BOX PER UNIT, which is `bank_boxes_plan`'s own arithmetic,
# and PLAN_BOXES is three above it: enough slack for the plan's `per=2` rule to
# bite and for the last shardable unit to take more than one shard, which is
# what the failure cases perturb. On today's template that is 5 and 8 — the
# numbers this drive used to type — so its evidence stays comparable.
PLAN_FLOOR="$PLAN_UNITS"
PLAN_BOXES=$((PLAN_UNITS + 3))

# AND THE SYNTACTIC FLOOR IS THE SUBJECT'S OWN CONSTANT. It is a typo belt and
# NOT the derived floor — `pm_push.sh` says so where it declares it — so the
# case about it reads the constant rather than repeating its value.
PLAN_TYPED_FLOOR="$(sed -n 's/^ON_BOXES_FLOOR=\([0-9][0-9]*\)$/\1/p' "$SOURCE")"
PLAN_TYPED_FLOOR="${PLAN_TYPED_FLOOR%%$'\n'*}"
[ -n "$PLAN_TYPED_FLOOR" ] ||
    cannot_look "scripts/pm_push.sh declares no ON_BOXES_FLOOR — the syntactic-floor case has nothing to read"

PLAN_FLAT="$PLAN_INDIV"
set -- $PLAN_INDIV
PLAN_FLAT1="${1:-}"
PLAN_FLAT2="${2:-}"
PLAN_FLAT3="${3:-}"
set --
[ -n "$PLAN_FLAT1" ] && [ -n "$PLAN_FLAT2" ] ||
    cannot_look "this tree's listing has fewer than two indivisible units — the cases that perturb a whole-box shard need one each"

# --- assertions (test_pm_merge.sh's four helpers, unchanged) -----------------
DRIVE_OUT=""
DRIVE_EXIT=0

ok() {
    echo "  ok       ${CURRENT} — $1"
    PASSED=$((PASSED + 1))
}

bad() {
    echo "  FAILED   ${CURRENT} — $1"
    [ -z "$DRIVE_OUT" ] || [ ! -f "$DRIVE_OUT" ] || sed 's/^/             | /' "$DRIVE_OUT" | tail -25
    FAILED=$((FAILED + 1))
}

exited() {
    local want="$1"
    if [ "$DRIVE_EXIT" -eq "$want" ]; then
        ok "exit ${DRIVE_EXIT}"
    else
        bad "wanted exit ${want}, got ${DRIVE_EXIT}"
    fi
}

says() {
    if grep -qF -- "$1" "$DRIVE_OUT"; then
        ok "says \"$1\""
    else
        bad "does not say \"$1\""
    fi
}

says_not() {
    if grep -qF -- "$1" "$DRIVE_OUT"; then
        bad "says \"$1\" and must not"
    else
        ok "does not say \"$1\""
    fi
}

holds() {
    local what="$1" want="$2" got="$3"
    if [ "$want" = "$got" ]; then
        ok "${what} = ${got}"
    else
        bad "${what}: wanted '${want}', got '${got}'"
    fi
}

# --- the world ----------------------------------------------------------------
W=""
REPO=""
REC=""
LEDGER=""
RUNNER=""
N=0

# count_lines <file> — non-blank lines, or 0 when the file is not there.
# `grep -c` PRINTS ITS ZERO AND EXITS 1, so a `|| printf 0` fallback appends a
# second zero to the first one and every `holds` comparison then reads
# `wanted '0', got '0\n0'`. Paid on this drive's own first red-first run.
count_lines() {
    local n
    n="$(grep -c . "$1" 2>/dev/null || true)"
    case "$n" in '' | *[!0-9]*) n=0 ;; esac
    printf '%s\n' "$n"
}

# sorted_lines <file> — the file's lines sorted, or nothing. A reader that
# `set -e`-kills the drive on a file the SUBJECT failed to write turns a FAILED
# assertion into a could-not-look, which is the wrong verdict about the wrong
# thing.
sorted_lines() {
    [ -f "$1" ] || return 0
    LC_ALL=C sort "$1"
}

field_lines() {
    [ -f "$1" ] || return 0
    awk -F'\t' -v f="$2" '{ print $f }' "$1"
}

# plan_round_robin <zones> — how many of this plan's shards land in each zone
# when the bank deals them round-robin, largest bucket first, in the shape the
# zone case compares against. Arithmetic over PLAN_BOXES, so a product whose
# listing declares one more unit gets the right answer with no edit here.
# drawer_plant <path> <unit> <needs> — one product leg, with X2's header.
# A REAL FILE in this drive's own scratch directory, never in the checkout: an
# untracked executable in the checkout reds the instrument census by design.
drawer_plant() {
    local path="$1" unit="$2" needs="$3"
    {
        echo '#!/usr/bin/env bash'
        echo '# >>> leg v1 >>>'
        echo "# unit: ${unit}"
        echo "# needs: ${needs}"
        echo '# tier: full'
        echo '# two-means: broken'
        echo '# <<< leg <<<'
        echo "echo \"${path##*/}: a product's own leg\""
        echo 'exit 0'
    } >"$path"
    chmod +x "$path"
}

# drawer_full_legs <drawer> — the leg set `gate_full_legs` composes UNDER THAT
# DRAWER, for the stub gate of a world whose listing was composed under it too.
#
# THE TWO HALVES OF A WORLD MUST AGREE. `gate_full_legs` reads the CHECKOUT's
# own `scripts/local/legs/`, so a world handed a listing from one drawer and a
# `FULL_LEGS=` from another declares legs no shard covers — and the bank
# refuses it, correctly, with `covered by no shard`. It went unnoticed because
# on a template with no drawer the two answers coincide.
#
# IN A SUBSHELL, AND WITH THE MEMO CLEARED: `gate_full_legs` caches its answer
# for the process, and a variable assignment in front of a shell FUNCTION does
# not reliably stay scoped to the call.
drawer_full_legs() {
    (
        export DJB_LOCAL_LEGS_DIR="$1"
        GATE_FULL_LEGS_MEMO=""
        gate_full_legs
    )
}

plan_round_robin() {
    local zones="$1" i=0 out=""
    while [ "$i" -lt "$zones" ]; do
        i=$((i + 1))
        out="${out}$(((PLAN_BOXES + zones - i) / zones)) "
    done
    printf '%s' "$out"
}

fresh_world() {
    N=$((N + 1))
    W="${WORK}/w${N}-$1"
    REPO="${W}/repo"
    REC="${W}/rec"
    LEDGER="${W}/verdicts"
    RUNNER="${W}/run-bank.sh"
    drive_require_scratch W "${W:-}"
    drive_require_scratch REPO "${REPO:-}"
    # THE OVERRIDE IS PER WORLD AND NEVER STICKY: a case that composed its own
    # leg set says so before the `fresh_world` that uses it, and the next world
    # is this tree's again.
    WORLD_FULL_LEGS="${WORLD_FULL_LEGS_NEXT:-$REAL_FULL_LEGS}"
    WORLD_FULL_LEGS_NEXT=""
    mkdir -p "$REPO/scripts/githooks" "$REC" "$W/tmp" "$W/lease"
    : >"$LEDGER"

    git -C "$REPO" init -q
    git -C "$REPO" symbolic-ref HEAD refs/heads/main
    git -C "$REPO" config user.email drive@example.invalid
    git -C "$REPO" config user.name "pm_push drive"

    cp "$SOURCE" "$REPO/scripts/pm_push.sh"
    cp "$ROOT/scripts/gate_ledger.sh" "$REPO/scripts/gate_ledger.sh"
    cp "$ROOT/scripts/gate_refuse.sh" "$REPO/scripts/gate_refuse.sh"
    cp "$HOOK" "$REPO/scripts/githooks/pre-push"
    chmod +x "$REPO/scripts/pm_push.sh" "$REPO/scripts/githooks/pre-push"

    cp "$REAL_LISTING" "$REC/listlegs.out"

    # THE BOX'S CHECKOUT PATH IS READ OUT OF `deploy/verifier/bake.sh`, which is
    # the ONE place it is written down (`scripts/verifier_box.sh`'s
    # `verifier_checkout_path` reads the same two lines). The scratch repository
    # therefore needs one, with the same two knob lines and nothing else: a
    # world without it measures the acceptance box's refusal instead of its work.
    mkdir -p "$REPO/deploy/verifier"
    {
        echo '#!/usr/bin/env bash'
        echo '# A STUB bake.sh — the two knob lines the checkout path is read from.'
        echo 'BAKE_USER="${DJB_VERIFIER_BAKE_USER:-verifier}"'
        echo 'BAKE_CHECKOUT="${DJB_VERIFIER_CHECKOUT:-/home/${BAKE_USER}/src}"'
    } >"$REPO/deploy/verifier/bake.sh"
    chmod +x "$REPO/deploy/verifier/bake.sh"

    # THE REGISTRY COORDINATE AND THE STUB THAT COMPOSES NAMES FROM IT.
    # `bank_boxes_image` asks `deploy/provision.sh image-ref` for every name it
    # uses — that function is the one composer of a registry name in this tree —
    # so the world needs one that records its argv and answers from a fixture.
    # A case that wants "no registry coordinate" removes the fixture, which is
    # exactly what an unset `DJB_IMAGE_REGISTRY` and an empty `deploy/.env` are.
    printf '%s\n' '000000000000.dkr.ecr.us-east-1.amazonaws.com/drivens' >"$REC/registry"
    mkdir -p "$REPO/deploy"
    sed -e "s|__REC__|${REC}|g" >"$REPO/deploy/provision.sh" <<'PROV'
#!/usr/bin/env bash
# A STUB. It records every argv and answers `image-ref` from one fixture, the
# way `deploy/provision.sh` composes it: <registry>/djb-<service>:<tag>. The
# real one's refusal when there is no coordinate is `die`, which is exit 2 with
# nothing on stdout, and that is modelled too.
REC="__REC__"
printf '%s\n' "$*" >>"$REC/provision.calls"
case "${1:-}" in
image-ref)
    reg="$(cat "$REC/registry" 2>/dev/null || true)"
    if [ -z "$reg" ]; then
        echo "!! provision: DJB_IMAGE_REGISTRY is empty." >&2
        exit 2
    fi
    printf '%s/djb-%s:%s\n' "$reg" "${2:-}" "${3:-}"
    exit 0
    ;;
esac
echo "stub provision: no fixture for '$*'" >&2
exit 2
PROV
    chmod +x "$REPO/deploy/provision.sh"

    # THE MAP, TRACKED AND EMPTY, exactly as it ships. The acceptance box
    # REWRITES this file in the working tree and commits nothing, so a case that
    # asserts "modified and uncommitted" needs a committed baseline to be
    # modified away from.
    mkdir -p "$REC"
    printf '%s\n' '{"generated": {"at": "-", "pytest": 0, "tree": "-"}, "tests": {}, "unmapped": {}}' \
        >"$REPO/scripts/test_impact.json"

    # THE STUB GATE. It records every invocation — which is what the "this Mac
    # measures nothing" claim is asserted against — and answers `--list-legs`
    # from a fixture. Its `FULL_LEGS=` line is the real one, because
    # `gate_full_legs` reads that assignment out of whatever `scripts/check.sh`
    # is in the checkout and the composed row carries the answer.
    {
        echo '#!/usr/bin/env bash'
        echo "FULL_LEGS=${WORLD_FULL_LEGS}"
        echo "printf '%s\\n' \"\$*\" >>\"${REC}/gate.calls\""
        echo 'if [ "${1:-}" = "--list-legs" ]; then'
        echo "    if [ -f \"${REC}/listlegs.err\" ]; then cat \"${REC}/listlegs.err\" >&2; fi"
        echo "    if [ -f \"${REC}/listlegs.rc\" ]; then exit \"\$(cat \"${REC}/listlegs.rc\")\"; fi"
        echo "    cat \"${REC}/listlegs.out\""
        echo '    exit 0'
        echo 'fi'
        echo 'echo "STUB GATE ran with: $*"'
        echo 'exit "${DJB_DRIVE_GATE_RC:-0}"'
    } >"$REPO/scripts/check.sh"
    chmod +x "$REPO/scripts/check.sh"

    # THE STUB FOLD. It exits 0 having committed nothing, which is the real
    # fold's answer on a tree with nothing to fold; a case that wants a fold
    # COMMIT calls `world_fold_commits` and gets one.
    {
        echo '#!/usr/bin/env bash'
        echo "printf 'ran\\n' >>\"${REC}/fold.calls\""
        echo 'echo "STUB FOLD ran"'
        echo 'echo "pm_fold: NOTHING TO FOLD. No commit was made."'
        echo 'exit 0'
    } >"$REPO/scripts/pm_fold.sh"
    chmod +x "$REPO/scripts/pm_fold.sh"

    world_write_verifier_box

    echo "one" >"$REPO/shared.txt"
    git -C "$REPO" add -A
    git -C "$REPO" commit -q -m "base"

    git -C "$REPO" worktree add -q --detach "$W/pm-push" >/dev/null 2>&1 ||
        cannot_look "could not add a pm-push worktree under ${W}"
    git init -q --bare "$W/origin"
    git -C "$REPO" remote add origin "$W/origin"

    # ONE RUNNER, AND IT `exec`s. A case that signals the bank has to reach the
    # bank's OWN pid: a subshell wrapper would take the signal itself and the
    # trap under drive would never fire.
    {
        echo '#!/usr/bin/env bash'
        echo "cd \"${REPO}\" || exit 2"
        echo "export DJB_GATE_LEDGER=\"${LEDGER}\""
        echo "export TMPDIR=\"${W}/tmp\""
        echo "export DJB_GATE_LEASE_DIR=\"${W}/lease\""
        echo 'exec ./scripts/pm_push.sh "$@"'
    } >"$RUNNER"
    chmod +x "$RUNNER"
}

world_write_verifier_box() {
    sed -e "s|__REC__|${REC}|g" -e "s|__REPO__|${REPO}|g" \
        -e "s|__SUITELEG__|${PLAN_SUITE_LEG}|g" \
        >"$REPO/scripts/verifier_box.sh" <<'STUB'
#!/usr/bin/env bash
# A STUB. It records every argv and answers from per-case fixtures. It makes no
# AWS call, launches nothing, terminates nothing and touches no real box.
set -uo pipefail
REC="__REC__"
REPO="__REPO__"
# THE SUITE LEG'S NAME, SUBSTITUTED IN rather than typed: it is the subject's
# own `BANK_SUITE_LEG`, and this stub has to spell what a real `--leg … --passes
# 1` banner spells.
SUITELEG="__SUITELEG__"
printf '%s\n' "$*" >>"$REC/vb.calls"

label_of_rung() {
    local r="${1#bank-}"
    printf '%s\n' "${r#*-}"
}
unit_of_label() {
    local l="$1"
    if [[ $l =~ ^(.*)-[0-9]+of[0-9]+$ ]]; then
        printf '%s\n' "${BASH_REMATCH[1]}"
    else
        printf '%s\n' "$l"
    fi
}

cmd="${1:-}"
shift || true
case "$cmd" in
up)
    rung=""
    az=""
    ttl=""
    idle=""
    while [ "$#" -gt 0 ]; do
        case "$1" in
        --for)
            rung="${2:-}"
            shift 2
            ;;
        # THE THREE ARGUMENTS R1 ADDS OR ALREADY HAS, PARSED HERE SO A CASE CAN
        # ASSERT THEM. `--az` is R1's new one and this stub is what stands in
        # for it until R1 merges; `--ttl`/`--idle` the wrapper already takes.
        --az)
            az="${2:-}"
            shift 2
            ;;
        --ttl)
            ttl="${2:-}"
            shift 2
            ;;
        --idle)
            idle="${2:-}"
            shift 2
            ;;
        *) shift ;;
        esac
    done
    [ -n "$rung" ] || {
        echo "stub up: no --for" >&2
        exit 2
    }
    label="$(label_of_rung "$rung")"
    printf '%s\t%s\t%s\t%s\t%s\n' "$label" "$rung" "${az:--}" "${ttl:--}" "${idle:--}" >>"$REC/up.calls"
    if [ -f "$REC/up.allow" ] && ! grep -qx "$label" "$REC/up.allow"; then
        # THE OPERATOR'S HAND, MODELLED. A case that signals the bank after
        # exactly three boxes are up needs the other five to be still in
        # flight, and a stub that answered instantly would make that window
        # unreachable. Bounded, so a case that forgets to release cannot hang
        # the leg.
        i=0
        while [ ! -f "$REC/release" ] && [ "$i" -lt 300 ]; do
            sleep 0.2
            i=$((i + 1))
        done
        echo "stub up: ${label} released without launching" >&2
        exit 2
    fi
    # HOW MANY TIMES THIS LABEL HAS BEEN BROUGHT UP. A retried shard is a
    # SECOND box and it must be a second id: the same id twice would make
    # "two boxes were launched and both were taken down" unassertable, and the
    # retry case turns on exactly that. The FIRST attempt's id is byte-for-byte
    # the one every other case already knows.
    upn="$(cat "$REC/up.n.${label}" 2>/dev/null || echo 0)"
    upn=$((upn + 1))
    printf '%s\n' "$upn" >"$REC/up.n.${label}"
    # THE REFUSAL IS SEQUENCED TOO — `up.rc.<label>.<n>` — because a RETRY's
    # own box can be the one that will not come up, and a case about that
    # needs the FIRST launch to succeed.
    if [ -f "$REC/up.rc.${label}.${upn}" ]; then
        echo "stub up: ${label} attempt ${upn} refused by fixture" >&2
        exit "$(cat "$REC/up.rc.${label}.${upn}")"
    fi
    if [ -f "$REC/up.rc.${label}" ]; then
        echo "stub up: ${label} refused by fixture" >&2
        exit "$(cat "$REC/up.rc.${label}")"
    fi
    id="i-$(printf '%s' "$label" | cksum | awk '{printf "%010d", $1}')"
    [ "$upn" = "1" ] || id="${id}-r${upn}"
    printf '%s\n' "$label" >"$REC/label-of.${id}"
    # THE SEAM'S OWN LINE, PRINTED RIGHT AFTER THE LAUNCH AND BEFORE ANYTHING
    # THAT CAN STILL FAIL (R1's `launched   <id>   az <az>`). A case that wants
    # an `up` which LAUNCHED and then died plants `up.launched_then_rc.<label>`
    # — which is the state the launch-then-die defect is about and the one
    # `up.rc.<label>` cannot
    # model, because that fixture refuses before any box exists.
    echo "launched   ${id}   az ${az:-xx-drive-9a}"
    if [ -f "$REC/up.launched_then_rc.${label}" ]; then
        echo "stub up: ${label} launched and then failed by fixture" >&2
        exit "$(cat "$REC/up.launched_then_rc.${label}")"
    fi
    echo "instance   ${id}   c7g.4xlarge   market: spot   az ${az:-xx-drive-9a}"
    # THE WRAPPER'S OWN MARKET LINE, which is where the bank's table reads the
    # market from — EC2's `InstanceLifecycle` as the wrapper read it back, not
    # the market the launch asked for. A case that wants a shard on on-demand
    # plants the one word.
    echo "market     $(cat "$REC/up.market.${label}" 2>/dev/null || echo spot)"
    echo "owner      drive        for: ${rung}   idle: 45m"
    echo "tree       the box agrees with this checkout"
    printf '%s\n' "$label" >>"$REC/up.done"
    exit 0
    ;;
leg)
    id="${1:-}"
    shift || true
    printf '%s\t%s\n' "$id" "$*" >>"$REC/leg.calls"
    # THE PASS COUNT THIS SHARD WAS HANDED, REMEMBERED PER BOX, because the
    # log this stub serves later has to say what this box RAN. A real
    # `check.sh --leg ... --passes 1` prints `pytest-x2/1` in its own
    # `composed-of:` banner (the seam grammar `<leg>[/<passes>]`, absent
    # meaning two), and a stub that always printed the bare name would let a
    # bank that ignored the flag compose a green.
    plbl="$(cat "$REC/label-of.${id}" 2>/dev/null || echo unknown)"
    case " $* " in
    *" --passes 1 "*) printf '1\n' >"$REC/leg.passes.${plbl}" ;;
    esac
    # A DETACH CAN FAIL DIFFERENTLY THE SECOND TIME, and that is the whole of
    # the transport case: ssh answers 255 seconds after `up` returns because
    # the SSM tunnel is not up yet, and answers 0 a moment later. So the rc is
    # sequenced PER BOX — `leg.rc.<label>.<n>` — and falls back to the
    # unsequenced fixture and then to 0.
    lbl="$(cat "$REC/label-of.${id}" 2>/dev/null || echo unknown)"
    n="$(cat "$REC/leg.n.${lbl}" 2>/dev/null || echo 0)"
    n=$((n + 1))
    printf '%s\n' "$n" >"$REC/leg.n.${lbl}"
    if [ -f "$REC/leg.rc.${lbl}.${n}" ]; then exit "$(cat "$REC/leg.rc.${lbl}.${n}")"; fi
    if [ -f "$REC/leg.rc.${lbl}" ]; then exit "$(cat "$REC/leg.rc.${lbl}")"; fi
    exit "$(cat "$REC/leg.rc" 2>/dev/null || echo 0)"
    ;;
run)
    # THE ACCEPTANCE BOX'S SEAM. `run` is SYNCHRONOUS and its exit status is the
    # remote command's, passed through untouched (`cmd_run`), so the fixture
    # that decides whether the map was written is one file.
    id="${1:-}"
    shift || true
    printf '%s\t%s\n' "$id" "$*" >>"$REC/run.calls"
    # THE IMAGE RUN IS ITS OWN SEAM ON THE SAME VERB, and it is told apart by
    # the one thing only it does: assert the box's own `image-tag` before
    # building. It records the argv separately AND COPIES THE LEDGER AS IT
    # STANDS AT THAT MOMENT — which is how "the row was written BEFORE the
    # build" is asserted as an ordering rather than inferred from two clocks.
    case "$*" in
    *"provision.sh image-tag"*)
        printf '%s\t%s\n' "$id" "$*" >>"$REC/image.calls"
        cat "${DJB_GATE_LEDGER:-/dev/null}" >"$REC/ledger.at.image" 2>/dev/null || true
        if [ -f "$REC/image.out" ]; then
            cat "$REC/image.out"
        elif [ -s "$REC/box.dirty" ]; then
            # THE BOX'S OWN COUPLING, MODELLED. Both these runs happen on ONE
            # machine and in ONE checkout: whatever the acceptance run wrote
            # into the tree is still there when the image step asks
            # `provision.sh image-tag` what tree this is, and a tracked file
            # that moved makes that answer `-dirty`. A stub that answered the
            # clean tag however the map was written could never see the defect
            # that cost a real bank its image.
            echo "!! image: refusing to build under 'tree-00000000000a-dirty' — this bank keys on a tree tag"
            echo "   the tree moved under it: $(cat "$REC/box.dirty")"
            exit 3
        else
            echo "Login Succeeded"
            echo "image: seconds web 39 worker 41"
            echo "image: digest web sha256:0aa1"
            echo "image: digest worker sha256:0bb2"
            echo "image: platform linux/arm64"
        fi
        exit "$(cat "$REC/image.rc" 2>/dev/null || echo 0)"
        ;;
    esac
    # AND THE ACCEPTANCE RUN DIRTIES THE BOX IFF IT WRITES INTO THE CHECKOUT.
    # The discriminator is the `--out` path the map writer is handed, and it is
    # the PROPERTY and not one fix's spelling: a RELATIVE path is a path inside
    # the checkout the command `cd`s to, and an absolute one (or one under
    # $HOME) is not. `$REC/box.dirty` is what the image seam above reads.
    accept_out="$(printf '%s\n' "$*" | sed -n 's/.*--out \([^ ;]*\).*/\1/p')"
    case "$accept_out" in
    '') ;;
    /* | '$HOME'/* | '${HOME}'/*) ;;
    *) printf '%s\n' "$accept_out" >"$REC/box.dirty" ;;
    esac
    exit "$(cat "$REC/accept.rc" 2>/dev/null || echo 0)"
    ;;
zones)
    # R1's new subcommand: one availability zone per line, sorted, and exit 2
    # when it cannot look. The bank reads it ONCE per run and spreads its
    # shards across what comes back.
    if [ -f "$REC/zones.rc" ]; then
        echo "stub zones: could not look by fixture" >&2
        exit "$(cat "$REC/zones.rc")"
    fi
    # A WRAPPER THAT SAYS SOMETHING ON STDERR AND STILL ANSWERS. `zones` warns
    # (an unset pricing region, a slow describe); the ring is what is on
    # STDOUT, and a reader that folded the two together would spread this
    # bank's boxes over an English sentence.
    [ ! -f "$REC/zones.noise" ] || echo "verifier_box: warning — DJB_VERIFIER_PRICING_REGION is unset" >&2
    if [ -f "$REC/zones" ]; then
        cat "$REC/zones"
    else
        printf '%s\n' xx-drive-9a xx-drive-9b xx-drive-9c
    fi
    exit 0
    ;;
wait)
    id="${1:-}"
    name="${2:-}"
    printf '%s\t%s\n' "$id" "$name" >>"$REC/wait.calls"
    lbl="$(cat "$REC/label-of.${id}" 2>/dev/null || echo unknown)"
    # SEQUENCED PER LABEL, `leg`'s idiom one case up, and for the same reason:
    # a shard whose box was RECLAIMED is retried on a fresh box, and the
    # second wait has to be able to answer differently from the first. The
    # sequence is per LABEL and not per id, because it is the shard that is
    # retried and the id is what changes.
    wn="$(cat "$REC/wait.n.${lbl}" 2>/dev/null || echo 0)"
    wn=$((wn + 1))
    printf '%s\n' "$wn" >"$REC/wait.n.${lbl}"
    # A SLOW SHARD, MODELLED. The defect this exists for is invisible to a
    # stub that answers instantly: every box finished at once, so nothing was
    # ever idle while another leg ran. Bounded, so a case that forgets to
    # release cannot hang the leg.
    if [ -f "$REC/wait.block.${lbl}" ]; then
        i=0
        while [ ! -f "$REC/release-wait" ] && [ "$i" -lt 300 ]; do
            sleep 0.2
            i=$((i + 1))
        done
    fi
    if [ -f "$REC/wait.out.${lbl}.${wn}" ]; then
        cat "$REC/wait.out.${lbl}.${wn}"
    elif [ -f "$REC/wait.out.${lbl}" ]; then
        cat "$REC/wait.out.${lbl}"
    fi
    if [ -f "$REC/box.rc.${lbl}.${wn}" ]; then exit "$(cat "$REC/box.rc.${lbl}.${wn}")"; fi
    exit "$(cat "$REC/box.rc.${lbl}" 2>/dev/null || echo 0)"
    ;;
fetch)
    id="${1:-}"
    remote="${2:-}"
    dest="${3:-}"
    printf '%s\t%s\t%s\n' "$id" "$remote" "$dest" >>"$REC/fetch.calls"
    lbl="$(cat "$REC/label-of.${id}" 2>/dev/null || echo unknown)"
    case "$remote" in
    *proof.txt)
        # THE LEAK PROOF, and it is served by DEFAULT and green — because a
        # real acceptance box writes one on every run and the world every
        # other case builds is the ordinary one. A case that wants the proof
        # missing, unparsable or red plants for it by name.
        #
        # AND A RECLAIMED ACCEPTANCE BOX SAYS SO HERE. `fetch` calls
        # `refuse_if_reclaimed` like every other subcommand, so a box AWS took
        # back between the run and the fetch is discovered at the fetch — which
        # is the state this fixture models, on the FIRST attempt only.
        pn="$(cat "$REC/accept.proof.n" 2>/dev/null || echo 0)"
        pn=$((pn + 1))
        printf '%s\n' "$pn" >"$REC/accept.proof.n"
        if [ -f "$REC/accept.proof.reclaimed" ] && [ "$pn" = "1" ]; then
            echo "box reclaimed (spot) ${id} status instance-terminated-no-capacity: not enough capacity" >&2
            echo "!! verifier_box: the box was reclaimed by AWS mid-flight." >&2
            exit 2
        fi
        if [ -f "$REC/accept.proof.absent" ]; then
            echo "stub fetch: nothing at ${remote} on ${id}" >&2
            exit 1
        fi
        if [ -f "$REC/accept.proof" ]; then
            cat "$REC/accept.proof" >"$dest"
        else
            printf 'seed=%s workers=16 pass1=0 pass2=0 map=0\n' 1073741827 >"$dest"
        fi
        exit 0
        ;;
    *pass1.log | *pass2.log)
        # THE ACCEPTANCE BOX'S TWO PASS LOGS. They are fetched WHENEVER
        # there is a box — laxer than the map's condition and laxer than the
        # proof's, because the one moment they can be read is before the box is
        # terminated and a red pass is exactly when somebody wants them.
        pl="${remote##*/}"
        pl="${pl%.log}"
        if [ -f "$REC/accept.${pl}.absent" ]; then
            echo "stub fetch: nothing at ${remote} on ${id}" >&2
            exit 1
        fi
        if [ -f "$REC/accept.${pl}" ]; then
            cat "$REC/accept.${pl}" >"$dest"
        else
            printf '%s\n' "Using --randomly-seed=1073741827" \
                "== 2481 passed in 512.01s ==" >"$dest"
        fi
        exit 0
        ;;
    *test_impact.json)
        # BEFORE the `*.rc`/`*.log` cases below, which are the SHARD's two
        # fetches: the map is neither, and a `.json` falling through to them
        # would be answered with a shard's log.
        if [ -f "$REC/accept.map.absent" ]; then
            echo "stub fetch: nothing at ${remote} on ${id}" >&2
            exit 1
        fi
        if [ -f "$REC/accept.map" ]; then
            cat "$REC/accept.map" >"$dest"
        else
            printf '%s\n' '{"generated": {"at": "2026-09-18T00:00:00+00:00", "pytest": 4, "tree": "tree:beefcafe1234"}, "tests": {"apps/x/tests/test_a.py::test_one": ["apps/x/services.py"]}, "unmapped": {}}' >"$dest"
        fi
        exit 0
        ;;
    esac
    if [ -f "$REC/absent.${lbl}" ]; then
        echo "stub fetch: nothing at ${remote} on ${id}" >&2
        exit 1
    fi
    case "$remote" in
    *.rc)
        if [ -f "$REC/norc.${lbl}" ]; then
            echo "stub fetch: no exit status on ${id}" >&2
            exit 1
        fi
        # THE STATUS OF THE ATTEMPT THAT JUST RAN, `wait`'s own sequence: a
        # retried shard's second box wrote a second status, and a fetch that
        # served the first would hand the composition the reclaimed box's.
        wn="$(cat "$REC/wait.n.${lbl}" 2>/dev/null || echo 1)"
        if [ -f "$REC/box.rc.${lbl}.${wn}" ]; then
            cat "$REC/box.rc.${lbl}.${wn}" >"$dest"
        elif [ -f "$REC/box.rc.${lbl}" ]; then
            cat "$REC/box.rc.${lbl}" >"$dest"
        else
            printf '0\n' >"$dest"
        fi
        exit 0
        ;;
    *.log)
        unit="$(unit_of_label "$lbl")"
        if [ -f "$REC/box.tree.${lbl}" ]; then
            tree="$(cat "$REC/box.tree.${lbl}")"
        else
            tree="$(cd "$REPO" && . scripts/gate_ledger.sh && gate_measured_tree)"
        fi
        onepass=""
        [ ! -f "$REC/leg.passes.${lbl}" ] || onepass=1
        if [ -f "$REC/box.legs.${lbl}" ]; then
            # A PLANTED LEG SET WINS OUTRIGHT, pass count and all: the cases
            # that plant one are the ones measuring a composition that
            # DISAGREES with the plan, and a stub that corrected the plant
            # would make that disagreement unreachable.
            legs="$(cat "$REC/box.legs.${lbl}")"
        else
            legs="$(awk -F'\t' -v u="$unit" '$1 == u { print $4 }' "$REC/listlegs.out")"
            if [ -n "$onepass" ]; then
                legs=",${legs},"
                legs="${legs/,${SUITELEG},/,${SUITELEG}/1,}"
                legs="${legs#,}"
                legs="${legs%,}"
            fi
        fi
        wall="$(cat "$REC/box.wall.${lbl}" 2>/dev/null || echo 42)"
        {
            echo "- --leg ${unit}${onepass:+ --passes 1}"
            echo "  needs:       db (a DECLARATION — the gate refuses at the leg, never here)"
            echo "  shards:      N-capable"
            echo "  composed-of: ${legs}"
            echo "  This run takes NO machine lease, NO checkout lock and records NO verdict:"
            echo "  one unit of the gate vouches for no tree."
            echo "ok: all checks passed (${wall}s)"
            echo "  ...of ONE UNIT: ${unit}."
            echo "  no verdict recorded — --leg ${unit}: one unit of the gate"
            echo "  is a targeted drive and vouches for no tree. The tree it ran on was ${tree}."
        } >"$dest"
        # A RED SHARD'S PYTEST OUTPUT, PLANTED. `check.sh --leg` runs pytest
        # inside the leg, so a red pytest shard's `leg.log` carries pytest's
        # own seed banner and its `FAILED <nodeid>` summary lines — which is
        # what the first-failing composer reads. A case that wants a red shard
        # NAMED plants them.
        [ ! -f "$REC/box.faillog.${lbl}" ] || cat "$REC/box.faillog.${lbl}" >>"$dest"
        exit 0
        ;;
    esac
    echo "stub fetch: no fixture for ${remote}" >&2
    exit 2
    ;;
harvest-drives)
    # THE BOX'S OWN LEDGER, MODELLED AS A FIXTURE FILE. The real subcommand
    # reads `.git/djb-gate-verdicts` over the transport and hands it to
    # `harvest_drive_rows`, which owns the tree filter and the already-here
    # rule; this stub models both so a case can assert what LANDED here, and
    # `test_verifier_box.sh` drives the real reader. It never refuses, exactly
    # as the real one does not.
    id="${1:-}"
    htree="${2:-}"
    printf '%s\t%s\n' "$id" "$htree" >>"$REC/harvest.calls"
    lbl="$(cat "$REC/label-of.${id}" 2>/dev/null || echo unknown)"
    hn=0
    halready=0
    if [ -f "$REC/boxledger.${lbl}" ]; then
        while IFS= read -r hline; do
            case "$hline" in
            *" drive "*"tree=${htree}"*) ;;
            *) continue ;;
            esac
            if grep -qxF -- "$hline" "${DJB_GATE_LEDGER}" 2>/dev/null; then
                halready=$((halready + 1))
                continue
            fi
            printf '%s\n' "$hline" >>"${DJB_GATE_LEDGER}"
            hn=$((hn + 1))
        done <"$REC/boxledger.${lbl}"
    fi
    echo "verifier_box: drive rows: ${hn} brought home at tree=${htree} (${halready} already here) from ${id}"
    exit 0
    ;;
down)
    id="${1:-}"
    printf '%s\n' "$id" >>"$REC/down.calls"
    lbl="$(cat "$REC/label-of.${id}" 2>/dev/null || echo unknown)"
    if [ -f "$REC/down.fail" ] || [ -f "$REC/down.fail.${lbl}" ]; then
        echo "stub down: terminate-instances refused for ${id}" >&2
        exit 1
    fi
    echo "terminated ${id}"
    exit 0
    ;;
esac
echo "stub verifier_box: unknown command '${cmd}'" >&2
exit 2
STUB
    chmod +x "$REPO/scripts/verifier_box.sh"
}

# world_fold_commits — make the stub fold add a COMMIT, the way the real one
# does when a derived file moved. The post-fold tree is then a different tree
# from the one HEAD carried when the operator typed the command.
world_fold_commits() {
    {
        echo '#!/usr/bin/env bash'
        echo "printf 'ran\\n' >>\"${REC}/fold.calls\""
        echo 'echo "STUB FOLD ran"'
        echo "printf 'derived\\n' >\"${REPO}/derived.txt\""
        echo "git -C \"${REPO}\" add derived.txt"
        echo "git -C \"${REPO}\" commit -q -m 'fold: the derived files'"
        echo 'echo "pm_fold: committed the derived files."'
        echo 'exit 0'
    } >"$REPO/scripts/pm_fold.sh"
    chmod +x "$REPO/scripts/pm_fold.sh"
    # COMMITTED, because `--bank` refuses a dirty tree and a fixture swapped in
    # after the base commit IS a dirty tree — the case would then measure that
    # refusal instead of the fold's ordering.
    git -C "$REPO" add scripts/pm_fold.sh
    git -C "$REPO" commit -q -m "a fold that commits"
}

# repo_tree — the tree a bank of this repository keys on.
#
# IT READS HEAD'S TREE AND NOT THE WORKING TREE'S, and the difference is the
# acceptance box. `gate_measured_tree` reads the WORKING tree through `git add
# -A`, and on a clean checkout that is HEAD's tree by construction — which is
# every state this world is in BEFORE a bank. Afterwards it is not: the
# acceptance box rewrites `scripts/test_impact.json` in the working tree and
# commits nothing (by design — a bank takes no commit), so a working-tree read
# taken after a bank names a tree the bank never keyed on. Every case here that
# reads the tree reads it after, so the stable value is the committed one.
repo_tree() { git -C "$REPO" rev-parse HEAD^{tree}; }

# --- running the subject ------------------------------------------------------
run_bank() {
    DRIVE_OUT="${W}/run-$(printf '%s' "$*" | tr -c 'a-zA-Z0-9' '_').log"
    set +e
    "$RUNNER" "$@" >"$DRIVE_OUT" 2>&1
    DRIVE_EXIT=$?
    set -e
}

# THE ONE ASSERTION EVERY CASE MAKES. S.3 is not a case that runs once: "the
# Mac measures nothing" has to be true of the green runs, the red runs and
# every refusal, and a claim asserted in one case is a claim the other sixteen
# could quietly break.
assert_mac_measured_nothing() {
    local other
    other="$(grep -v -- '--list-legs' "${REC}/gate.calls" 2>/dev/null | grep -c . || true)"
    [ -n "$other" ] || other=0
    if [ "$other" != "0" ]; then
        bad "the Mac's own gate was invoked ${other} time(s) other than --list-legs"
        return
    fi
    if [ -e "${W}/lease/djb-gate-lease" ]; then
        bad "the bank took the machine-wide full-gate lease"
        return
    fi
    if [ -e "${W}/lease/djb-gate-slots" ]; then
        bad "the bank took a pytest slot"
        return
    fi
    ok "the Mac measured nothing: no bare gate, no lease, no slot"
}

ledger_rows() { count_lines "$LEDGER"; }

# =============================================================================
# S.1 — the flag is refused outside the bank, loudly, before anything launches
# =============================================================================

# =============================================================================
# S.0 — the plan this tree's own listing produces, derived before anything else
# =============================================================================
#
# IT RUNS FIRST AND EVERY CASE BELOW DEPENDS ON IT. One ordinary bank over this
# tree's real unit table, and what it yields is the set of shard labels the
# SUBJECT produced — which is then compared against a set composed HERE out of
# the listing. Two derivations of one fact, asserted equal: the composition
# below is what the cases use, and the probe is what stops it being a guess.
#
# WHY IT IS A PROBE AND NOT A TABLE. `bank_boxes_plan` decides k per unit from
# N and from how many units shard; a drive that wrote `selftest-2of3` down was
# encoding that arithmetic at one N on one tree. The consumer's first bank
# reddened 49 assertions on a tree where the subject was right and this file's
# table was stale — the exact class this cycle exists to remove.
derive_the_plan_from_the_real_listing() {
    CURRENT=derive_the_plan_from_the_real_listing
    local observed unit k i composed last=""

    fresh_world plan_probe
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    [ "$DRIVE_EXIT" = "0" ] ||
        cannot_look "the probe bank over this tree's own listing exited ${DRIVE_EXIT} — every label below is derived from it, so there is nothing to derive"
    # Field 1 of `up.calls` is the label; the acceptance box is not in the plan.
    # ARRIVAL ORDER IS NOT PLAN ORDER — the boxes go up in parallel — so this
    # is compared as a SET and the order is composed from the listing below.
    observed="$(field_lines "${REC}/up.calls" 1 | grep -v '^acceptance$' || true)"
    [ -n "$observed" ] ||
        cannot_look "the probe bank brought up no shard box — nothing to derive the labels from"

    composed=""
    for unit in $PLAN_INDIV; do
        composed="${composed}${composed:+ }${unit}"
    done
    for unit in $PLAN_CAPABLE; do
        k="$(printf '%s\n' "$observed" | grep -c "^${unit}-[0-9]*of[0-9]*$" || true)"
        case "$k" in '' | *[!0-9]*) k=0 ;; esac
        [ "$k" -gt 0 ] ||
            cannot_look "the probe's plan gave the N-capable unit '${unit}' no shard at all"
        i=0
        while [ "$i" -lt "$k" ]; do
            i=$((i + 1))
            composed="${composed}${composed:+ }${unit}-${i}of${k}"
        done
        last="$unit"
        if [ "$unit" = "$PLAN_SUITE_UNIT" ]; then
            PLAN_SUITE_K="$k"
            PLAN_SUITE_FIRST="${unit}-1of${k}"
            PLAN_SUITE_LAST="${unit}-${k}of${k}"
        fi
    done
    PLAN_LABELS="$composed"
    holds "the composed plan is the probe's own set of ${PLAN_BOXES} shards" \
        "$(printf '%s\n' $observed | LC_ALL=C sort | paste -sd, -)" \
        "$(printf '%s\n' $PLAN_LABELS | LC_ALL=C sort | paste -sd, -)"

    # THE VICTIM: a shard of the LAST shardable unit. "The last" needs no
    # opinion about which unit that is, and every failure case below wants one
    # shard rather than a particular one.
    PLAN_VICTIM_UNIT="$last"
    PLAN_VICTIM_K="$(printf '%s\n' $PLAN_LABELS | grep -c "^${last}-" || true)"
    PLAN_VICTIM="${last}-${PLAN_VICTIM_K}of${PLAN_VICTIM_K}"
    PLAN_VICTIM_FIRST="${last}-1of${PLAN_VICTIM_K}"
    # THE FIRST THREE LABELS OF THE PLAN, for the case that signals the bank
    # once some boxes are up and the rest are still in flight. Three is "some
    # but not all" and needs no opinion about which three.
    PLAN_KILL_ALLOW="$(printf '%s\n' $PLAN_LABELS | sed -n '1,3p')"
    [ -n "$PLAN_SUITE_FIRST" ] ||
        cannot_look "the plan gave '${PLAN_SUITE_UNIT}' — the unit carrying the ${PLAN_SUITE_LEG} leg — no shard at all"
    holds "the plan's boxes (one per shard, and the acceptance box)" \
        "$((PLAN_BOXES + 1))" "$(count_lines "${REC}/up.calls")"
    echo "  ..       ${PLAN_UNITS} units; plan at ${PLAN_BOXES} boxes: $(printf '%s ' $PLAN_LABELS)"
    echo "  ..       suite leg '${PLAN_SUITE_LEG}' is in unit '${PLAN_SUITE_UNIT}' (${PLAN_SUITE_K} shard(s));"
    echo "  ..       the last shardable unit is '${PLAN_VICTIM_UNIT}' (${PLAN_VICTIM_K}); the perturbed shard is '${PLAN_VICTIM}'"
    echo "  ..       the syntactic floor the subject declares is ${PLAN_TYPED_FLOOR}; the derived one is ${PLAN_FLOOR}"
}

case_on_boxes_without_bank_is_refused() {
    CURRENT=case_on_boxes_without_bank_is_refused
    fresh_world on_boxes_without_bank

    run_bank --on-boxes "$PLAN_BOXES"
    exited 2
    says "--on-boxes is only meaningful with --bank"
    says_not "STUB GATE ran"
    holds "up calls" "0" "$(count_lines "${REC}/up.calls")"
    holds "verdict rows" "0" "$(ledger_rows)"
    assert_mac_measured_nothing

    # THE OTHER UNKNOWN FLAGS KEEP THE PROPERTY. A parser that grew one flag
    # must not have become a parser that accepts anything shaped like one.
    run_bank --on-boxen 8
    exited 2
    says "unknown flag --on-boxen"
    holds "up calls after the typo" "0" "$(count_lines "${REC}/up.calls")"

    # A VALUE-TAKING FLAG WITH NO VALUE IS A REFUSAL, never an empty count.
    run_bank --bank --on-boxes
    exited 2
    says "--on-boxes takes a box count"
    holds "up calls after the bare flag" "0" "$(count_lines "${REC}/up.calls")"
}

case_on_boxes_below_the_syntactic_floor_is_refused() {
    CURRENT=case_on_boxes_below_the_syntactic_floor_is_refused
    fresh_world on_boxes_below_the_floor

    # THE VALUE IS READ OUT OF `pm_push.sh`'s OWN `ON_BOXES_FLOOR`. That
    # constant is the typo belt and NOT the derived floor (the file says so
    # where it declares it), so the assertion is that the subject refuses
    # BELOW ITS OWN CONSTANT — a product that moves the constant moves both
    # halves together and this case follows it.
    run_bank --bank --on-boxes "$((PLAN_TYPED_FLOOR - 1))"
    exited 2
    says "is below the floor of ${PLAN_TYPED_FLOOR}"
    says "N = 3 + P + S"
    holds "up calls" "0" "$(count_lines "${REC}/up.calls")"
    holds "fold calls" "0" "$(count_lines "${REC}/fold.calls")"
    holds "verdict rows" "0" "$(ledger_rows)"
    assert_mac_measured_nothing

    run_bank --bank --on-boxes eight
    exited 2
    says "takes a whole number of boxes, got 'eight'"
    holds "up calls after a word" "0" "$(count_lines "${REC}/up.calls")"
}

# =============================================================================
# S.2 — the fold runs first and the bank is of the POST-fold HEAD
# =============================================================================

case_the_composed_row_keys_on_the_post_fold_tree() {
    CURRENT=case_the_composed_row_keys_on_the_post_fold_tree
    fresh_world post_fold_tree
    world_fold_commits
    local before after row keyed
    before="$(repo_tree)"

    run_bank --bank --on-boxes "$PLAN_BOXES"
    exited 0
    after="$(repo_tree)"
    if [ "$before" = "$after" ]; then
        bad "the fold did not move the tree, so this case measures nothing"
        return
    fi
    ok "the fold moved the tree: ${before:0:12} -> ${after:0:12}"
    holds "verdict rows" "1" "$(ledger_rows)"
    row="$(cat "$LEDGER")"
    keyed="$(printf '%s\n' "$row" | awk '{print $2}')"
    holds "the row's tree" "$after" "$keyed"
    if [ "$keyed" = "$before" ]; then
        bad "the row keyed on the PRE-fold tree — it would vouch for bytes the push does not carry"
    else
        ok "the row does not key on the pre-fold tree"
    fi
    says "banking the POST-FOLD HEAD"
    assert_mac_measured_nothing
}

# =============================================================================
# S.3 — the Mac never measures
# =============================================================================

case_the_mac_holds_no_lease_and_runs_no_gate() {
    CURRENT=case_the_mac_holds_no_lease_and_runs_no_gate
    fresh_world mac_no_lease
    local listed

    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    listed="$(grep -c -- '--list-legs' "${REC}/gate.calls" 2>/dev/null || true)"
    holds "gate invocations, all of them --list-legs" "1" "${listed:-0}"
    says "This Mac MEASURES NOTHING"
    assert_mac_measured_nothing

    # AND ON A RED RUN TOO, which is the half a green-only assertion misses.
    fresh_world mac_no_lease_red
    printf '1\n' >"${REC}/box.rc.static"
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 1
    assert_mac_measured_nothing
}

# =============================================================================
# S.4 — the plan is derived, never typed
# =============================================================================

case_the_plan_follows_the_listing() {
    CURRENT=case_the_plan_follows_the_listing
    local shards_now flat_shards want

    # (a) A LISTING WITH ONE MORE INDIVISIBLE UNIT. The plan gains a box for it
    # and the last shardable unit loses one — with no edit to pm_push.sh. The
    # "one fewer" is arithmetic over what THIS tree's plan gave that unit, not
    # a number: on a product whose drawer adds a `local` unit the whole row
    # shifts and the claim is the same claim.
    fresh_world plan_extra_unit
    printf 'extra-unit\tnone\t0\textra-leg\n' >>"${REC}/listlegs.out"
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    if grep -q -- '--unit extra-unit --log leg' "${REC}/leg.calls"; then
        ok "the new indivisible unit got its own box, unsharded"
    else
        DRIVE_OUT="${REC}/leg.calls"
        bad "the plan did not give extra-unit a box of its own"
    fi
    shards_now="$(grep -c -- "--unit ${PLAN_VICTIM_UNIT} " "${REC}/leg.calls" || true)"
    holds "${PLAN_VICTIM_UNIT} shards at N=${PLAN_BOXES} with one more indivisible unit (one fewer than the ${PLAN_VICTIM_K} it had)" \
        "$((PLAN_VICTIM_K - 1))" "${shards_now:-0}"
    holds "boxes (the plan's ${PLAN_BOXES}, and the acceptance box)" "$((PLAN_BOXES + 1))" \
        "$(count_lines "${REC}/up.calls")"

    # (b) A LISTING WHERE THE LAST SHARDABLE UNIT IS INDIVISIBLE. The split
    # drops; nothing in pm_push.sh knows that unit's name, and neither does
    # this case — it is `the last shardable unit in the listing`.
    fresh_world plan_victim_flat
    awk -F'\t' -v victim="$PLAN_VICTIM_UNIT" 'BEGIN { OFS = "\t" } $1 == victim { $3 = "0" } { print }' \
        "$REAL_LISTING" >"${REC}/listlegs.out"
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    if grep -q -- "--unit ${PLAN_VICTIM_UNIT} --log leg" "${REC}/leg.calls"; then
        ok "${PLAN_VICTIM_UNIT} took one whole box with no --shard"
    else
        DRIVE_OUT="${REC}/leg.calls"
        bad "${PLAN_VICTIM_UNIT} was still split after the listing called it indivisible"
    fi
    # WHAT IS LEFT FOR THE OTHER SHARDABLE UNITS is the arithmetic the plan
    # does: every unit but the shardable ones takes a whole box, and the rest
    # of N is split between them.
    flat_shards="$(grep -c -- '--shard' "${REC}/leg.calls" || true)"
    holds "shards left once ${PLAN_VICTIM_UNIT} is indivisible" \
        "$((PLAN_BOXES - (PLAN_UNITS - 1)))" "${flat_shards:-0}"
    assert_mac_measured_nothing

    # (c) AND THE FLOOR IS DERIVED TOO. The floor of TODAY's units is checked
    # at the argument for a typo's sake; the floor that stays right when a
    # unit is ADDED comes out of the listing, and it refuses with the
    # arithmetic rather than with a constant.
    fresh_world plan_derived_floor
    printf 'extra-unit\tnone\t0\textra-leg\n' >>"${REC}/listlegs.out"
    run_bank --bank --no-fold --on-boxes "$PLAN_FLOOR"
    exited 2
    says "this gate declares $((PLAN_UNITS + 1)) units"
    says "cannot give every one of them a box"
    says "never typed"
    holds "up calls under the derived floor" "0" "$(count_lines "${REC}/up.calls")"
    holds "verdict rows under the derived floor" "0" "$(ledger_rows)"

    # (d) AT THE FLOOR ITSELF, every shardable unit still carries a k. `1/1` is
    # a part of a whole and the gate takes one; a shardable unit handed NO k
    # would be a unit the composition could not account for, which is its own
    # exit 2 one function over.
    fresh_world plan_at_the_floor
    run_bank --bank --no-fold --on-boxes "$PLAN_FLOOR"
    exited 0
    for unit in $PLAN_CAPABLE; do
        if [ "$unit" = "$PLAN_SUITE_UNIT" ]; then
            want="--unit ${unit} --shard 1/1 --passes 1 --log leg"
        else
            want="--unit ${unit} --shard 1/1 --log leg"
        fi
        if grep -qF -- "$want" "${REC}/leg.calls"; then
            ok "at the floor: leg <id> ${want}"
        else
            DRIVE_OUT="${REC}/leg.calls"
            bad "at the floor, no shard was handed: ${want}"
        fi
    done
    DRIVE_OUT="${W}/run-__bank___no_fold___on_boxes_${PLAN_FLOOR}.log"
    holds "boxes at the floor (one per unit, and the acceptance box)" \
        "$((PLAN_FLOOR + 1))" "$(count_lines "${REC}/up.calls")"
    holds "one verdict row at the floor" "1" "$(ledger_rows)"
}

# =============================================================================
# S.4a — a PRODUCT's leg, in the drawer, gets its own unit and its own box
# =============================================================================
#
# WHY THIS CASE IS THE POINT OF THE REST OF THIS FILE. The template declares
# the units it declares; a product that clones it puts its own legs in
# `scripts/local/legs/` and the listing grows a unit — `local` for the
# drawer's own, or a name of the product's choosing. `pm_push.sh` was always
# right about that (it derives its plan from `--list-legs`), and this DRIVE was
# wrong: it typed the template's unit table, so the first consumer's first bank
# reddened 49 assertions with the subject behaving perfectly. Everything above
# now derives from the listing; this case proves the derivation over a listing
# the template itself does not have.
#
# THE PLANT IS A REAL FILE AND THE LISTING IS THE REAL READER'S. The leg is
# written into this drive's own scratch directory and handed to
# `check.sh --list-legs` through `DJB_LOCAL_LEGS_DIR` — the reader's own plant
# point — so what the bank is given is a listing the gate composed, never a row
# this file typed. Nothing is written into the checkout: an untracked
# executable in it reds the instrument census by design.
case_a_product_leg_in_the_drawer_gets_its_own_unit_and_its_own_box() {
    CURRENT=case_a_product_leg_in_the_drawer_gets_its_own_unit_and_its_own_box
    local drawer empty listing base units boxes

    drawer="$WORK/drawer-legs"
    empty="$WORK/drawer-empty"
    rm -rf "$drawer" "$empty"
    mkdir -p "$drawer" "$empty"
    drawer_plant "$drawer/x.sh" local none

    listing="$WORK/listlegs-drawer.tsv"
    base="$WORK/listlegs-nodrawer.tsv"
    # AN EMPTY DRAWER IS THE BASELINE. `PLAN_UNITS` is the listing of the tree
    # AS IT STANDS, and on a PRODUCT that already keeps legs in the drawer that
    # listing already has units of its own — so "one more than PLAN_UNITS"
    # would be a claim that is true only on the template. Two readings of the
    # same reader, one with an empty drawer and one with this leg in it, is the
    # differential.
    #
    # THE VARIABLE IS SET FOR THESE COMMANDS ONLY. The drive preamble UNSETS
    # every gate input (`DRIVE_GATE_VARS`) so an inherited one cannot perturb a
    # drive's world — which is right, and means a case that WANTS one says so
    # on the command itself.
    if ! DJB_LOCAL_LEGS_DIR="$empty" ./scripts/check.sh --list-legs \
        >"$base" 2>"$WORK/listlegs-nodrawer.err" ||
        ! DJB_LOCAL_LEGS_DIR="$drawer" ./scripts/check.sh --list-legs \
            >"$listing" 2>"$WORK/listlegs-drawer.err"; then
        DRIVE_OUT="$WORK/listlegs-drawer.err"
        bad "the gate could not list its legs with a drawer leg planted"
        return
    fi
    units="$(count_lines "$listing")"
    holds "one drawer leg adds exactly one unit to the listing" \
        "$(($(count_lines "$base") + 1))" "$units"
    if awk -F'\t' '$1 == "local" { found = 1 } END { exit !found }' "$listing"; then
        ok "the listing carries a 'local' unit"
    else
        DRIVE_OUT="$listing"
        bad "no 'local' unit in the listing after planting a drawer leg"
        return
    fi

    # (a) THE PLAN GIVES IT A BOX, unsharded, like any other indivisible unit,
    # and the bank composes one row over the whole set.
    boxes=$((units + 3))
    WORLD_FULL_LEGS_NEXT="$(drawer_full_legs "$drawer")"
    fresh_world drawer_leg
    cp "$listing" "${REC}/listlegs.out"
    run_bank --bank --no-fold --on-boxes "$boxes"
    exited 0
    holds "one verdict row over a listing with a product's own unit" "1" "$(ledger_rows)"
    if grep -qF -- "--unit local --log leg" "${REC}/leg.calls"; then
        ok "the product's unit got its own box, unsharded"
    else
        DRIVE_OUT="${REC}/leg.calls"
        bad "the plan gave the product's 'local' unit no box of its own"
    fi
    DRIVE_OUT="${W}/run-__bank___no_fold___on_boxes_${boxes}.log"
    holds "boxes (one per shard, and the acceptance box)" "$((boxes + 1))" \
        "$(count_lines "${REC}/up.calls")"
    holds "leg calls" "$boxes" "$(count_lines "${REC}/leg.calls")"
    holds "downs" "$((boxes + 1))" "$(count_lines "${REC}/down.calls")"
    assert_mac_measured_nothing

    # (b) AND THE DERIVED FLOOR MOVED WITH IT. One box short of the units this
    # listing declares is a refusal naming the arithmetic — which is the whole
    # reason the floor is derived and not typed.
    if [ "$((units - 1))" -ge "$PLAN_TYPED_FLOOR" ]; then
        WORLD_FULL_LEGS_NEXT="$(drawer_full_legs "$drawer")"
        fresh_world drawer_leg_floor
        cp "$listing" "${REC}/listlegs.out"
        run_bank --bank --no-fold --on-boxes "$((units - 1))"
        exited 2
        says "this gate declares ${units} units"
        says "never typed"
        holds "up calls under the product's own floor" "0" "$(count_lines "${REC}/up.calls")"
        holds "verdict rows under the product's own floor" "0" "$(ledger_rows)"
    else
        ok "the syntactic floor is above this listing's unit count — the derived floor has no room to be asserted here"
    fi

    # (c) TWO LEGS IN TWO UNITS, which is the shape a real product has: the
    # drawer's own `local` and one the product NAMED, with organs of its own.
    # ONE leg in ONE unit passed for a reason worth writing down — the name
    # `local` happens to be the unit this template's own drawer would make —
    # so a second unit with a second name is what proves the plan is reading
    # the listing rather than agreeing by coincidence.
    drawer_plant "$drawer/y.sh" frontend node
    if ! DJB_LOCAL_LEGS_DIR="$drawer" ./scripts/check.sh --list-legs \
        >"$listing" 2>"$WORK/listlegs-drawer2.err"; then
        DRIVE_OUT="$WORK/listlegs-drawer2.err"
        bad "the gate could not list its legs with two drawer legs planted"
        return
    fi
    units="$(count_lines "$listing")"
    holds "two drawer legs in two units add exactly two units" \
        "$(($(count_lines "$base") + 2))" "$units"
    boxes=$((units + 3))
    WORLD_FULL_LEGS_NEXT="$(drawer_full_legs "$drawer")"
    fresh_world drawer_two_legs
    cp "$listing" "${REC}/listlegs.out"
    run_bank --bank --no-fold --on-boxes "$boxes"
    exited 0
    holds "one verdict row over two product units" "1" "$(ledger_rows)"
    for want in "--unit local --log leg" "--unit frontend --log leg"; do
        if grep -qF -- "$want" "${REC}/leg.calls"; then
            ok "leg <id> ${want}"
        else
            DRIVE_OUT="${REC}/leg.calls"
            bad "the plan gave no box to: ${want}"
        fi
    done
    DRIVE_OUT="${W}/run-__bank___no_fold___on_boxes_${boxes}.log"
    holds "boxes with two product units" "$((boxes + 1))" "$(count_lines "${REC}/up.calls")"
    # AND THE ROW NAMES BOTH PRODUCT LEGS. A composition that dropped one
    # would be a green vouching for a leg no box ran, which is the one thing
    # this ledger exists to prevent.
    DRIVE_OUT="$LEDGER"
    says "local:x"
    says "local:y"
    assert_mac_measured_nothing
}

# =============================================================================
# S.4a2 — TWO shards go to the last shardable unit before any other gets two
# =============================================================================
#
# WHY IT IS A DIFFERENTIAL. `bank_boxes_plan` gives every N-capable unit but
# the last TWO shards once there are seven boxes or more, and the LAST takes
# whatever is left — and nothing pinned that: the probe reads k back out of the
# subject's own `up.calls`, so a plan that split them any other way would be
# read as the plan and agreed with. One more box than the ordinary run, and the
# only k that may move is the last unit's.
case_one_more_box_goes_to_the_last_shardable_unit() {
    CURRENT=case_one_more_box_goes_to_the_last_shardable_unit
    local unit k

    fresh_world one_more_box
    run_bank --bank --no-fold --on-boxes "$((PLAN_BOXES + 1))"
    exited 0
    for unit in $PLAN_CAPABLE; do
        k="$(grep -c -- "--unit ${unit} --shard" "${REC}/leg.calls" || true)"
        case "$k" in '' | *[!0-9]*) k=0 ;; esac
        if [ "$unit" = "$PLAN_VICTIM_UNIT" ]; then
            holds "one more box went to the last shardable unit '${unit}'" \
                "$((PLAN_VICTIM_K + 1))" "$k"
        else
            holds "'${unit}' kept the shards it had" \
                "$(printf '%s\n' $PLAN_LABELS | grep -c "^${unit}-" || true)" "$k"
        fi
    done
    assert_mac_measured_nothing
}

case_a_broken_listing_is_exit_2_before_any_box() {
    CURRENT=case_a_broken_listing_is_exit_2_before_any_box
    fresh_world broken_listing
    printf '2\n' >"${REC}/listlegs.rc"
    printf '!! --list-legs: a leg is in NO unit.\n' >"${REC}/listlegs.err"

    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 2
    says "--list-legs exited 2"
    says "a leg is in NO unit"
    holds "up calls" "0" "$(count_lines "${REC}/up.calls")"
    holds "verdict rows" "0" "$(ledger_rows)"
    assert_mac_measured_nothing
}

# =============================================================================
# S.4b — the plan spreads its shards across the zones the WRAPPER lists
# =============================================================================
#
# WHY. Spot capacity is a per-availability-zone fact, so a bank that launched
# every box into one zone is a bank that loses every box to one capacity event
# — which is the measured shape of a reclaimed wave (five of nine, on the
# consumer's own bank). The zones are READ from the wrapper and never typed
# here: a hand list is a list that goes stale the first time an account gains
# or loses a zone, and the bank would then refuse in a zone that exists or
# crowd into one that does not.

case_the_plan_spreads_shards_across_the_zones_the_wrapper_lists() {
    CURRENT=case_the_plan_spreads_shards_across_the_zones_the_wrapper_lists
    local counts reads azs

    fresh_world zones_round_robin
    printf '%s\n' xx-drive-9a xx-drive-9b xx-drive-9c >"${REC}/zones"
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    says "zones xx-drive-9a xx-drive-9b xx-drive-9c"

    # READ ONCE. The zone ring is one fact about this account and a second
    # read is a second answer — and nine `zones` calls against the API for one
    # bank is nine chances to answer differently halfway through a launch.
    reads="$(grep -c '^zones' "${REC}/vb.calls" || true)"
    holds "zones read once for the whole bank" "1" "${reads:-0}"

    # EVERY `up` CARRIES ONE, and the eight shards are spread 3/3/2 over the
    # three zones the wrapper named. The acceptance box is excluded from the
    # count and takes the next place in the ring: it is not a shard and the
    # criterion is about the shards.
    counts="$(awk -F'\t' '$1 != "acceptance" { print $3 }' "${REC}/up.calls" |
        LC_ALL=C sort | uniq -c | awk '{ print $1 }' | LC_ALL=C sort -rn | tr '\n' ' ')"
    holds "shards per zone (${PLAN_BOXES} shards over three zones)" "$(plan_round_robin 3)" "$counts"
    azs="$(awk -F'\t' '{ print $3 }' "${REC}/up.calls" | LC_ALL=C sort -u | grep -c . || true)"
    holds "distinct zones used (the acceptance box included)" "3" "${azs:-0}"
    if grep -q "$(printf '\t-\t')" "${REC}/up.calls"; then
        DRIVE_OUT="${REC}/up.calls"
        bad "a box was brought up with no --az at all"
    else
        ok "every up carried an --az"
    fi
    DRIVE_OUT="${W}/run-__bank___no_fold___on_boxes_${PLAN_BOXES}.log"
    holds "one verdict row" "1" "$(ledger_rows)"
    assert_mac_measured_nothing

    # AND THE RING IS STDOUT, NOT STDOUT AND STDERR. A wrapper that warns and
    # still answers must not have its warning round-robined over as a zone.
    fresh_world zones_noisy
    printf '%s\n' xx-drive-9a xx-drive-9b xx-drive-9c >"${REC}/zones"
    : >"${REC}/zones.noise"
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    says "zones xx-drive-9a xx-drive-9b xx-drive-9c"
    says_not "zones verifier_box: warning"
    holds "distinct zones when the wrapper also warned" "3" \
        "$(awk -F'\t' '{ print $3 }' "${REC}/up.calls" | LC_ALL=C sort -u | grep -c . || true)"

    # AND THE RING IS THE WRAPPER'S, WHATEVER ITS LENGTH. Two zones is 4/4 and
    # nothing in pm_push.sh knows how many there are.
    fresh_world zones_two
    printf '%s\n' xx-drive-9a xx-drive-9b >"${REC}/zones"
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    counts="$(awk -F'\t' '$1 != "acceptance" { print $3 }' "${REC}/up.calls" |
        LC_ALL=C sort | uniq -c | awk '{ print $1 }' | LC_ALL=C sort -rn | tr '\n' ' ')"
    holds "shards per zone (${PLAN_BOXES} shards over two zones)" "$(plan_round_robin 2)" "$counts"
}

case_no_zones_is_exit_2_before_any_box() {
    CURRENT=case_no_zones_is_exit_2_before_any_box

    # (a) THE WRAPPER COULD NOT LOOK. A bank that carried on would launch into
    # whatever zone the subnet default happens to be, which is the single-zone
    # shape this criterion exists to end — silently.
    fresh_world zones_unreadable
    printf '2\n' >"${REC}/zones.rc"
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 2
    says "could not read the zones"
    holds "up calls with no zones" "0" "$(count_lines "${REC}/up.calls")"
    holds "verdict rows" "0" "$(ledger_rows)"
    assert_mac_measured_nothing

    # (b) AND AN EMPTY ANSWER IS THE SAME ANSWER. Exit 0 with nothing on
    # stdout is a wrapper that looked and found none, and a ring of nothing is
    # not a ring.
    fresh_world zones_empty
    : >"${REC}/zones"
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 2
    says "could not read the zones"
    holds "up calls with an empty ring" "0" "$(count_lines "${REC}/up.calls")"
    holds "verdict rows" "0" "$(ledger_rows)"
}

# =============================================================================
# S.4c — every bank box reaps itself if this Mac dies (the killed-bank rider)
# =============================================================================
#
# WHY. The bank's teardown is a TRAP and no shell covers a SIGKILL: a measured
# `boxbank-17-killed.log` shows the trap firing and dying with the Mac, and
# what was left underneath was the image's own 4 h hard ceiling — enough for
# the bill, not for promptness. So every bank `up` types a ONE HOUR ceiling,
# comfortably above the longest measured leg.
#
# AND THE IDLE MINUTES STAY THE IMAGE'S OWN THIRTY. A shorter idle is not a
# tighter belt, it is a live defect: the box's idle clock starts when its LEG
# EXITS, so a two-minute pytest shard is idle for the eighteen minutes the
# selftest unit is still running. At ten it was reaped out from under the bank
# — `box gone (terminated)`, no log, and a leak proof composed as LOST over a
# tree every shard passed.
case_bank_boxes_carry_a_one_hour_lifetime_and_a_thirty_minute_idle() {
    CURRENT=case_bank_boxes_carry_a_one_hour_lifetime_and_a_thirty_minute_idle
    local ttls idles

    fresh_world box_lifetime
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    says "box lifetime: 1h hard, 30m idle - the box reaps itself if the Mac dies"
    # EVERY BOX, THE ACCEPTANCE ONE INCLUDED: it is the box that outlives the
    # shards and the one a killed bank is most likely to leave behind.
    ttls="$(awk -F'\t' '$4 == "1" { n++ } END { print n + 0 }' "${REC}/up.calls")"
    idles="$(awk -F'\t' '$5 == "30" { n++ } END { print n + 0 }' "${REC}/up.calls")"
    holds "ups carrying --ttl 1" "$((PLAN_BOXES + 1))" "$ttls"
    holds "ups carrying --idle 30" "$((PLAN_BOXES + 1))" "$idles"
    assert_mac_measured_nothing
}

# =============================================================================
# S.5 — N boxes, one leg per box, the seam's exact argv
# =============================================================================

# N BOXES, N SHARDS, AND THE SEAM'S EXACT ARGV — where N is what this tree's
# own listing produced, never a number in this file.
case_every_shard_gets_its_own_box_and_the_seams_argv() {
    CURRENT=case_every_shard_gets_its_own_box_and_the_seams_argv
    fresh_world every_shard
    local tree8 ids uniq want label unit k

    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    # ONE MORE BOX THAN SHARDS. The extra one is the `acceptance` box and it
    # is outside the plan by construction: it takes no unit, it is handed no
    # leg, and its answer enters no part of the composed verdict.
    holds "up calls" "$((PLAN_BOXES + 1))" "$(count_lines "${REC}/up.calls")"
    holds "leg calls" "$PLAN_BOXES" "$(count_lines "${REC}/leg.calls")"
    holds "wait calls" "$PLAN_BOXES" "$(count_lines "${REC}/wait.calls")"
    # TWO `run`s AND NOT ONE, and the second is the image: the acceptance
    # measurement in phase 3, and ONE build after the row is written. Both are
    # on the same verb and neither is a unit of the gate. A third would be a
    # second image of one tree, which is the shape the criteria rejected.
    holds "run calls (the acceptance measurement, and one image build)" "2" "$(count_lines "${REC}/run.calls")"
    holds "image builds (one, whatever the box count)" "1" "$(count_lines "${REC}/image.calls")"
    # TWO PER SHARD (a log and a status) PLUS THE NINTH BOX'S FOUR — the map,
    # the leak proof and the two pass logs — which is arithmetic over the plan
    # and not a number somebody counted once.
    holds "fetch calls (a log and a status per shard, the map, the leak proof, two pass logs)" \
        "$((PLAN_BOXES * 2 + 4))" "$(count_lines "${REC}/fetch.calls")"

    tree8="$(repo_tree)"
    tree8="${tree8:0:8}"
    DRIVE_OUT="${REC}/up.calls"
    for label in $PLAN_LABELS; do
        want="bank-${tree8}-${label}"
        if grep -qF "$want" "${REC}/up.calls"; then
            ok "up --for ${want}"
        else
            bad "no box was brought up for ${want}"
        fi
    done

    # THE ARGV IS COMPOSED FROM THE LABEL, which is the plan's own grammar:
    # `<unit>` for a whole box and `<unit>-<k>of<N>` for a shard, `--passes 1`
    # exactly on the unit the listing puts the suite leg in.
    DRIVE_OUT="${REC}/leg.calls"
    for label in $PLAN_LABELS; do
        case "$label" in
        *-[0-9]of[0-9] | *-[0-9]of[0-9][0-9] | *-[0-9][0-9]of[0-9][0-9])
            unit="${label%-*}"
            k="${label##*-}"
            k="${k/of//}"
            want="--unit ${unit} --shard ${k} --log leg"
            [ "$unit" != "$PLAN_SUITE_UNIT" ] ||
                want="--unit ${unit} --shard ${k} --passes 1 --log leg"
            ;;
        *) want="--unit ${label} --log leg" ;;
        esac
        if grep -qF -- "$want" "${REC}/leg.calls"; then
            ok "leg <id> ${want}"
        else
            bad "no shard was handed: ${want}"
        fi
    done

    ids="$(field_lines "${REC}/leg.calls" 1 | LC_ALL=C sort || true)"
    uniq="$(printf '%s\n' "$ids" | LC_ALL=C sort -u)"
    holds "each box id handed exactly one leg" "$uniq" "$ids"
    DRIVE_OUT="${W}/run-__bank___no_fold___on_boxes_${PLAN_BOXES}.log"
    assert_mac_measured_nothing
}

case_a_detach_that_ssh_refused_is_retried_once() {
    CURRENT=case_a_detach_that_ssh_refused_is_retried_once
    fresh_world detach_255
    printf '255\n' >"${REC}/leg.rc.${PLAN_VICTIM}.1"

    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    # Nine detaches for eight shards: the one that met the closed tunnel went
    # twice.
    holds "leg calls (every shard, one retried)" "$((PLAN_BOXES + 1))" "$(count_lines "${REC}/leg.calls")"
    says "exited 255"
    says "${PLAN_VICTIM}"
    says "retrying the detach"
    holds "ledger rows" "1" "$(ledger_rows)"
    assert_mac_measured_nothing
}

case_a_detach_that_failed_for_anything_else_is_not_retried() {
    CURRENT=case_a_detach_that_failed_for_anything_else_is_not_retried
    fresh_world detach_not_transport
    printf '2\n' >"${REC}/leg.rc.${PLAN_VICTIM}"

    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 2
    holds "leg calls (no retry for a non-transport failure)" "$PLAN_BOXES" "$(count_lines "${REC}/leg.calls")"
    says "a unit could not be detached: ${PLAN_VICTIM}"
    says_not "retrying the detach"
    holds "ledger rows" "0" "$(ledger_rows)"
    assert_mac_measured_nothing
}

# =============================================================================
# S.5d — the shards' drive rows come home before the boxes go
# =============================================================================

# WHY THE ROWS MATTER. A drive row is a CACHE keyed on the drive's own subjects
# and the MACHINE — and the machine half of a verifier box is its image, so a
# row one box banked is reusable by every other box of that image and by every
# later bank. The rows live in the box's `.git/djb-gate-verdicts`; the box is
# terminated a few lines later; nothing brought them back. So the Mac's ledger
# held nothing keyed to the boxes' image, `push` had nothing image-keyed to
# send out, and every bank re-drove every drive it had driven the wave before —
# with the selftest unit over twenty minutes of it.
#
# boxledger_rows <label> — two drive rows this box banked at the bank's tree.
boxledger_rows() {
    local label="$1" t="$2"
    printf 'v1 drive-v1:aaaa%s drive 2026-09-18T00:00:00Z selftest exit=0 took=3 tree=%s parts=scripts/tests/test_a.sh\n' "$label" "$t" >"${REC}/boxledger.${label}"
    printf 'v1 drive-v1:bbbb%s drive 2026-09-18T00:00:01Z sweep exit=0 took=4 tree=%s parts=scripts/tests/test_b.sh\n' "$label" "$t" >>"${REC}/boxledger.${label}"
}

ledger_drive_rows() {
    local n
    n="$(grep -c ' drive ' "$LEDGER" 2>/dev/null || true)"
    case "$n" in '' | *[!0-9]*) n=0 ;; esac
    printf '%s\n' "$n"
}

case_a_green_bank_brings_the_shards_drive_rows_home() {
    CURRENT=case_a_green_bank_brings_the_shards_drive_rows_home
    fresh_world harvest_drives
    local t
    t="$(repo_tree)"
    boxledger_rows ${PLAN_VICTIM} "$t"

    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    holds "harvest-drives calls (one per shard box, and none for the acceptance box)" \
        "$PLAN_BOXES" "$(count_lines "${REC}/harvest.calls")"
    holds "drive rows now in this checkout's ledger" "2" "$(ledger_drive_rows)"
    says "drive rows: 2 brought home"
    # THE TREE IS THE BANK'S OWN, not each box's idea of one: the rows are a
    # cache for THIS tree's drives and a row keyed elsewhere is somebody else's.
    if [ "$(field_lines "${REC}/harvest.calls" 2 | LC_ALL=C sort -u)" = "$t" ]; then
        ok "every harvest was asked for the bank's own tree"
    else
        bad "a harvest was asked for a tree that is not the bank's: $(field_lines "${REC}/harvest.calls" 2 | LC_ALL=C sort -u | tr '\n' ' ')"
    fi
    assert_mac_measured_nothing
}

case_drive_rows_already_home_are_not_appended_twice() {
    CURRENT=case_drive_rows_already_home_are_not_appended_twice
    fresh_world harvest_idempotent
    local t
    t="$(repo_tree)"
    boxledger_rows ${PLAN_VICTIM} "$t"
    # ALREADY HERE, exactly as a second bank of the same tree would find them.
    cat "${REC}/boxledger.${PLAN_VICTIM}" >>"$LEDGER"

    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    holds "drive rows in the ledger, still" "2" "$(ledger_drive_rows)"
    says "drive rows: 0 brought home"
    says "(2 already here)"
    assert_mac_measured_nothing
}

case_a_red_bank_harvests_nothing() {
    CURRENT=case_a_red_bank_harvests_nothing
    fresh_world harvest_red
    local t
    t="$(repo_tree)"
    boxledger_rows ${PLAN_VICTIM} "$t"
    printf '1\n' >"${REC}/box.rc.${PLAN_VICTIM}"

    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 1
    holds "harvest-drives calls on a red bank" "0" "$(count_lines "${REC}/harvest.calls")"
    holds "drive rows in the ledger" "0" "$(ledger_drive_rows)"
    holds "verdict rows" "0" "$(ledger_rows)"
    assert_mac_measured_nothing
}

# =============================================================================
# S.5c — the market each shard's box is on, in the table
# =============================================================================

# A TABLE THAT DOES NOT SAY WHICH MARKET IT BOUGHT IS A TABLE NOBODY CAN COST.
# The bank's boxes are Spot by default and the wrapper's fallback can buy
# on-demand for one of them; afterwards the boxes are gone and the table is all
# that is left. The word comes from the wrapper's own `market` line — EC2's
# `InstanceLifecycle`, read back off the instance — not from what the launch
# asked for.
case_the_shard_table_names_the_market_each_box_is_on() {
    CURRENT=case_the_shard_table_names_the_market_each_box_is_on
    fresh_world table_market
    printf 'on-demand\n' >"${REC}/up.market.static"

    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    # THE HEADER, NAMED EXACTLY. A bare `says "market"` is satisfied by any
    # line anywhere in a bank's output that happens to carry the word, and
    # several do.
    if grep -E '^  shard .*market' "$DRIVE_OUT" >/dev/null 2>&1; then
        ok "the table has a market column"
    else
        bad "the table's header has no market column: $(grep -E '^  shard ' "$DRIVE_OUT" || true)"
    fi
    if grep -E '^  static .*on-demand' "$DRIVE_OUT" >/dev/null 2>&1; then
        ok "the shard whose box went on-demand says so in its own row"
    else
        bad "the table's static row does not carry its market: $(grep -E '^  static' "$DRIVE_OUT" || true)"
    fi
    if grep -E "^  ${PLAN_FLAT2} .*spot" "$DRIVE_OUT" >/dev/null 2>&1; then
        ok "and a Spot shard's row says spot"
    else
        bad "the table's ${PLAN_FLAT2} row does not carry its market: $(grep -E "^  ${PLAN_FLAT2}" "$DRIVE_OUT" || true)"
    fi
    assert_mac_measured_nothing
}

# =============================================================================
# S.6 — refuse unless every shard is green and the legs add up
# =============================================================================

case_one_red_shard_is_exit_1_and_no_row() {
    CURRENT=case_one_red_shard_is_exit_1_and_no_row
    fresh_world one_red_shard
    printf '1\n' >"${REC}/box.rc.${PLAN_VICTIM}"

    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 1
    says "the gate is RED"
    says "${PLAN_VICTIM}"
    says "--leg ${PLAN_VICTIM_UNIT} --shard ${PLAN_VICTIM_K}/${PLAN_VICTIM_K}"
    holds "verdict rows" "0" "$(ledger_rows)"
    # THE TABLE PRINTS ON EVERY EXIT PATH — a composition that refused and said
    # only "a shard was red" is a composition nobody can act on.
    says "shard"
    says "${PLAN_SUITE_FIRST}"
    assert_mac_measured_nothing
}

case_a_missing_or_exit_2_shard_is_exit_2() {
    CURRENT=case_a_missing_or_exit_2_shard_is_exit_2
    # (a) a shard that exited 2 — enforcement broken over there
    fresh_world shard_exit_2
    printf '2\n' >"${REC}/box.rc.static"
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 2
    says "the shard exited 2"
    says "static"
    holds "verdict rows" "0" "$(ledger_rows)"
    assert_mac_measured_nothing

    # (b) a shard whose .rc never came back
    fresh_world shard_no_rc
    : >"${REC}/norc.${PLAN_FLAT2}"
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 2
    says "no exit status came back from the box"
    holds "verdict rows with no status" "0" "$(ledger_rows)"

    # (c) a shard whose whole fixture is gone — nothing fetched at all
    fresh_world shard_absent
    : >"${REC}/absent.${PLAN_VICTIM_FIRST}"
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 2
    says "no log came back from the box"
    holds "verdict rows with no log" "0" "$(ledger_rows)"
    assert_mac_measured_nothing
}

# =============================================================================
# S.6b — a reclaimed shard is retried ONCE, in the next zone; twice is LOST
# =============================================================================
#
# WHY IT IS A RETRY AND NOT A REFUSAL. A Spot reclaim is AWS taking the machine
# back, and before this the whole bank was exit 2 over it: one box of nine
# vanishing cost the other eight's work and a full re-run (the consumer lost
# five of nine to one capacity event). ONE more box, in the NEXT zone, is the
# cheapest thing that can be true — a reclaim is a per-zone capacity fact, so
# the same zone is the one place not to go back to.
#
# AND ONLY ONCE. Two reclaims of one shard is capacity that is gone, and the
# honest answer is the one this bank always gave: LOST, never red.

case_a_reclaimed_shard_is_retried_once_on_a_fresh_box_in_the_next_zone() {
    CURRENT=case_a_reclaimed_shard_is_retried_once_on_a_fresh_box_in_the_next_zone
    local ups azs first second

    fresh_world reclaim_retried_once
    # THE FIRST WAIT IS THE RECLAIM AND THE SECOND IS A CLEAN BOX. The wrapper
    # says the words and passes 2 through; the shard's status is the 2 of a
    # box nobody can read, which is why this may never be composed as red.
    printf 'box reclaimed (spot) i-000 status instance-terminated-no-capacity: not enough capacity\n' \
        >"${REC}/wait.out.${PLAN_SUITE_LAST}.1"
    printf '2\n' >"${REC}/box.rc.${PLAN_SUITE_LAST}.1"

    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    holds "one verdict row over a retried shard" "1" "$(ledger_rows)"
    says "was RECLAIMED"
    says "retried-from i-"
    says_not "the verdict is LOST, never red"
    says_not "the gate is RED"

    # TWO BOXES FOR ONE SHARD, IN TWO ZONES. The ids differ (the old one is
    # gone) and so do the zones (the reclaim is a fact about the zone).
    ups="$(awk -F'\t' -v l="$PLAN_SUITE_LAST" '$1 == l { n++ } END { print n + 0 }' "${REC}/up.calls")"
    holds "ups for the reclaimed shard" "2" "$ups"
    first="$(awk -F'\t' -v l="$PLAN_SUITE_LAST" '$1 == l { print $3; exit }' "${REC}/up.calls")"
    second="$(awk -F'\t' -v l="$PLAN_SUITE_LAST" '$1 == l { a = $3 } END { print a }' "${REC}/up.calls")"
    if [ -n "$first" ] && [ -n "$second" ] && [ "$first" != "$second" ]; then
        ok "the second box went to another zone: ${first} then ${second}"
    else
        DRIVE_OUT="${REC}/up.calls"
        bad "the retry went back into '${first}' (second: '${second:-<none>}')"
    fi
    DRIVE_OUT="${W}/run-__bank___no_fold___on_boxes_${PLAN_BOXES}.log"
    holds "ups in all (every shard, the acceptance box, one retry)" "$((PLAN_BOXES + 2))" \
        "$(count_lines "${REC}/up.calls")"
    holds "leg calls (every shard and one re-detach)" "$((PLAN_BOXES + 1))" "$(count_lines "${REC}/leg.calls")"

    # THE OLD BOX STAYS ON THE TEARDOWN LIST AND THE NEW ONE JOINS IT. A
    # reclaimed instance is `already gone` to the wrapper's `down`, which is
    # exit 0 and not a refusal; a bank that dropped the id instead would be
    # trusting AWS to have finished what it started.
    holds "downs (every box, and the retry's extra one)" "$((PLAN_BOXES + 2))" "$(count_lines "${REC}/down.calls")"
    azs="$(sorted_lines "${REC}/down.calls")"
    holds "each box taken down exactly once" "$(printf '%s\n' "$azs" | LC_ALL=C sort -u)" "$azs"
    assert_mac_measured_nothing
}

# =============================================================================
# S.6a — a finished shard's log comes home BEFORE the slowest shard returns
# =============================================================================
#
# THE DEFECT THIS EXISTS FOR, and it is the one a stub that answers instantly
# can never show. The bank used to join EVERY `wait` and only then fetch. On
# the box, `idle_reaper.sh` counts from the moment the leg exits — no gate
# running, no tty — so a pytest shard that finished at two and a half minutes
# sat idle while the selftest unit ran for twenty, and the reaper shut it down
# under the bank. What came back was `box gone (terminated)`: no log, no
# status, and a leak proof composed as LOST — exit 2, no row, no retry, over a
# tree on which every shard had passed. It is not a reclaim, so nothing
# retried it; it is not a red, so nothing named a test. The fix is ordering,
# and this case asserts the ordering rather than the timeout that hid it.

case_a_finished_shards_log_is_fetched_before_the_slowest_shard_returns() {
    CURRENT=case_a_finished_shards_log_is_fetched_before_the_slowest_shard_returns
    local bankpid i rc early

    fresh_world fetch_before_the_join
    # ONE SLOW SHARD. Its `wait` blocks until this case releases it, which is
    # the twenty-minute selftest unit in miniature.
    : >"${REC}/wait.block.${PLAN_VICTIM}"
    DRIVE_OUT="${W}/run-fetch-before-join.log"
    set +e
    "$RUNNER" --bank --no-fold --on-boxes "$PLAN_BOXES" >"$DRIVE_OUT" 2>&1 &
    bankpid=$!
    # THE ASSERTION IS THAT A DIFFERENT SHARD'S LOG IS ALREADY HERE while the
    # slow one is still waiting. Bounded: if the fetch really is behind the
    # join, this loop times out and the case FAILS rather than hanging.
    early=0
    i=0
    while [ "$i" -lt 300 ]; do
        i=$((i + 1))
        if [ -f "${REC}/fetch.calls" ] && grep -q 'static/leg.rc' "${REC}/fetch.calls"; then
            early=1
            break
        fi
        sleep 0.2
    done
    : >"${REC}/release-wait"
    wait "$bankpid"
    rc=$?
    set -e
    DRIVE_EXIT="$rc"
    if [ "$early" = "1" ]; then
        ok "a finished shard's log was fetched while the slowest shard was still waiting"
    else
        bad "nothing was fetched until every wait had returned — a finished box is idle from its leg's exit, and its own reaper takes it"
    fi
    exited 0
    holds "one verdict row" "1" "$(ledger_rows)"
    # AND THE NINTH BOX'S FILES TOO: it finishes around six minutes and the
    # slowest shard can be twenty, so it is the box most exposed to its own
    # idle clock.
    holds "the leak proof came home" "1" \
        "$(grep -c 'proof.txt' "${REC}/fetch.calls" || true)"
    assert_mac_measured_nothing
}

case_a_shard_reclaimed_twice_is_lost_never_red() {
    CURRENT=case_a_shard_reclaimed_twice_is_lost_never_red
    fresh_world reclaimed_twice
    # BOTH BOXES TAKEN BACK. The unsequenced fixture answers every attempt, so
    # the retry meets the same capacity the first box did.
    printf 'box reclaimed (spot) i-000 status instance-terminated-no-capacity: not enough capacity\n' \
        >"${REC}/wait.out.${PLAN_SUITE_LAST}"
    printf '2\n' >"${REC}/box.rc.${PLAN_SUITE_LAST}"

    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 2
    says "RECLAIMED mid-flight"
    says "the verdict is LOST, never red"
    says_not "the gate is RED"
    holds "verdict rows" "0" "$(ledger_rows)"
    # ONCE, AND THE SECOND RECLAIM IS NOT A THIRD BOX. A bank that kept trying
    # would spend the operator's money on capacity that has already said no
    # twice, and would do it with nobody watching.
    holds "ups for the twice-reclaimed shard" "2" \
        "$(awk -F'\t' -v l="$PLAN_SUITE_LAST" '$1 == l { n++ } END { print n + 0 }' "${REC}/up.calls")"
    assert_mac_measured_nothing
}

# AND A RETRY WHOSE OWN BOX WILL NOT COME UP IS STILL LOST. The retry is one
# more box and not a promise of one: capacity that refused a launch outright
# is the same answer as capacity that took one back, and a bank that carried
# on would be composing a verdict over a shard nothing ran.
case_a_retry_box_that_will_not_come_up_is_lost() {
    CURRENT=case_a_retry_box_that_will_not_come_up_is_lost
    fresh_world retry_box_will_not_come_up
    printf 'box reclaimed (spot) i-000 status instance-terminated-no-capacity: not enough capacity\n' \
        >"${REC}/wait.out.${PLAN_SUITE_LAST}.1"
    printf '2\n' >"${REC}/box.rc.${PLAN_SUITE_LAST}.1"
    # THE SECOND LAUNCH, AND ONLY THE SECOND, IS REFUSED.
    printf '2\n' >"${REC}/up.rc.${PLAN_SUITE_LAST}.2"

    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 2
    says "the second box did not come up either"
    says "the verdict is LOST, never red"
    says_not "the gate is RED"
    holds "verdict rows" "0" "$(ledger_rows)"
    holds "ups for the shard (one reclaimed, one refused, and no third)" "2" \
        "$(awk -F'\t' -v l="$PLAN_SUITE_LAST" '$1 == l { n++ } END { print n + 0 }' "${REC}/up.calls")"
    assert_mac_measured_nothing
}

case_a_reclaimed_acceptance_box_is_retried_once() {
    CURRENT=case_a_reclaimed_acceptance_box_is_retried_once
    fresh_world reclaimed_acceptance
    # THE NINTH BOX IS THE ONE THE ROW RESTS ON SINCE ADR gate-1's AMENDMENT:
    # every pytest shard ran ONE pass, so a reclaimed acceptance box is a bank
    # with no leak proof at all — exit 2 over eight green shards. It gets the
    # same one more box, in the next zone, for the same reason.
    : >"${REC}/accept.proof.reclaimed"

    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    holds "one verdict row over a retried acceptance box" "1" "$(ledger_rows)"
    says "was RECLAIMED"
    says "retried-from i-"
    says_not "the leak proof could not be read"
    holds "ups for the acceptance box" "2" \
        "$(awk -F'\t' '$1 == "acceptance" { n++ } END { print n + 0 }' "${REC}/up.calls")"
    holds "ups in all (every shard, the acceptance box, one retry)" "$((PLAN_BOXES + 2))" \
        "$(count_lines "${REC}/up.calls")"
    holds "downs" "$((PLAN_BOXES + 2))" "$(count_lines "${REC}/down.calls")"
    assert_mac_measured_nothing
}

case_a_foreign_tree_on_a_box_is_exit_2_naming_both() {
    CURRENT=case_a_foreign_tree_on_a_box_is_exit_2_naming_both
    fresh_world foreign_tree
    local mine foreign
    foreign="dead0000dead0000dead0000dead0000dead0000"
    printf '%s\n' "$foreign" >"${REC}/box.tree.${PLAN_VICTIM}"

    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 2
    mine="$(repo_tree)"
    says "a box measured a DIFFERENT tree"
    says "$foreign"
    says "$mine"
    holds "verdict rows" "0" "$(ledger_rows)"
    assert_mac_measured_nothing
}

case_legs_that_do_not_add_up_are_exit_2_naming_the_leg() {
    CURRENT=case_legs_that_do_not_add_up_are_exit_2_naming_the_leg
    fresh_world legs_short
    local full

    # ONE LEG DROPPED FROM ONE SHARD'S composed-of. Every shard is green, every
    # tree agrees, and the union is one leg short of the units the listing
    # declares — which is a green that vouched for less than it says.
    #
    # THE PLANT CARRIES THE PASS COUNT IT WAS PLANNED AT, and that is not
    # decoration: this bank plans its suite shards at one pass, so a plant
    # naming a bare `pytest-x2` would be a plan/shard DISAGREEMENT and would
    # be refused one check earlier, for a reason this case is not about. The
    # leg set is short and nothing else is wrong with it.
    full=",$(awk -F'\t' -v u="$PLAN_SUITE_UNIT" '$1 == u { print $4 }' "$REAL_LISTING"),"
    full="${full//,own-tree-census,/,}"
    full="${full//,${PLAN_SUITE_LEG},/,${PLAN_SUITE_LEG}/1,}"
    full="${full#,}"
    full="${full%,}"
    printf '%s\n' "$full" >"${REC}/box.legs.${PLAN_SUITE_FIRST}"
    printf '%s\n' "$full" >"${REC}/box.legs.${PLAN_SUITE_LAST}"

    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 2
    says "do not add up to a full gate"
    says "own-tree-census"
    holds "verdict rows" "0" "$(ledger_rows)"
    assert_mac_measured_nothing
}

# =============================================================================
# S.7 — ONE full row, written by the one writer
# =============================================================================

case_the_composed_row_has_the_grammar_and_one_writer() {
    CURRENT=case_the_composed_row_has_the_grammar_and_one_writer
    fresh_world row_grammar
    local row tree looked onepass_legs
    # `took=` IS THE SLOWEST PYTEST SHARD'S OWN WALL, out of that shard's own
    # banner — not the Mac's elapsed, and not a shard that ran no suite.
    printf '90\n' >"${REC}/box.wall.${PLAN_SUITE_FIRST}"
    printf '140\n' >"${REC}/box.wall.${PLAN_SUITE_LAST}"
    printf '900\n' >"${REC}/box.wall.${PLAN_VICTIM_FIRST}"

    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    holds "exactly one line appended" "1" "$(ledger_rows)"
    row="$(cat "$LEDGER")"
    tree="$(repo_tree)"
    DRIVE_OUT="$LEDGER"

    if printf '%s\n' "$row" | grep -E \
        "^v1 [0-9a-f]{40} full [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z [a-z0-9,:/_-]+ caller=pm-bank sanction=push-wall boxes=${PLAN_BOXES} shards=[A-Za-z0-9,.:_-]+ waited=0 took=[0-9]+ leak-proof=acceptance:i-[0-9a-f]+ rc=0\$" >/dev/null; then
        ok "the row matches the grammar byte for byte"
    else
        bad "the row does not match the composed grammar: ${row}"
    fi
    holds "the row's tree" "$tree" "$(printf '%s\n' "$row" | awk '{print $2}')"
    # THE LEG FIELD IS `FULL_LEGS` WITH ONE MEMBER CARRYING ITS PASS COUNT,
    # and it is composed here out of the real declaration rather than typed:
    # a literal would be a second copy of the gate's own leg set, right on the
    # day it was written.
    onepass_legs=",${REAL_FULL_LEGS},"
    onepass_legs="${onepass_legs//,${PLAN_SUITE_LEG},/,${PLAN_SUITE_LEG}/1,}"
    onepass_legs="${onepass_legs#,}"
    onepass_legs="${onepass_legs%,}"
    holds "the row's leg field names the suite leg's ONE pass" "$onepass_legs" \
        "$(printf '%s\n' "$row" | awk '{print $5}')"
    # BY NAME AND NOT BY POSITION: the proof is appended AFTER `took=`, so a
    # positional read here would be asserting where the field sits rather than
    # what it says, and would move every time the grammar gains one.
    holds "took= is the slowest pytest shard, not the slowest shard" "took=140" \
        "$(printf '%s\n' "$row" | awk '{ for (i = 1; i <= NF; i++) if ($i ~ /^took=/) print $i }')"
    DRIVE_OUT="${W}/run-__bank___no_fold___on_boxes_${PLAN_BOXES}.log"
    # AND THE ZONE IS A COLUMN OF IT. Afterwards the boxes are gone and this
    # table is all there is to cost a bank from OR to see its spread in — a
    # bank whose every row named one zone is the shape the round-robin exists
    # to end, and nothing else printed afterwards would show it.
    if grep -qE "^  ${PLAN_SUITE_LAST} +i-[0-9]+ +(spot|on-demand|-) +[a-z0-9-]+ +1 +0 +140s +[0-9a-f]{40}\$" "$DRIVE_OUT"; then
        ok "the per-shard table carries that shard's own market, zone, passes, wall, box, rc and tree"
    else
        bad "the per-shard table does not carry ${PLAN_SUITE_LAST}'s own row"
    fi
    if grep -qE '^  static +i-[0-9]+ +(spot|on-demand|-) +[a-z0-9-]+ +- +0 ' "$DRIVE_OUT"; then
        ok "a unit that runs no suite carries a dash in the passes column, never a 2"
    else
        bad "the table's static row guesses a pass count: $(grep -E '^  static' "$DRIVE_OUT" || true)"
    fi
    # THE SANCTION NAMES EVERY SHARD IN PLAN ORDER, and plan order is what
    # the probe composed out of the listing: indivisible units first, then
    # every shard of every N-capable unit.
    if printf '%s\n' "$row" | grep -F "shards=$(printf '%s\n' $PLAN_LABELS | paste -sd, -)" >/dev/null; then
        ok "the sanction names every shard, in plan order"
    else
        bad "the sanction's shards field is not the plan: ${row}"
    fi

    # AND THE LIBRARY FINDS IT. A row nothing can look up is a row nothing
    # honours, whatever it says.
    looked="$(cd "$REPO" && DJB_GATE_LEDGER="$LEDGER" bash -c '. scripts/gate_ledger.sh && gate_ledger_lookup "$1"' _ "$tree" 2>/dev/null || true)"
    holds "gate_ledger_lookup returns it" "$row" "$looked"
    assert_mac_measured_nothing
}

# =============================================================================
# S.8 — the hook honours it and costs seconds
# =============================================================================

hook_run() {
    # THE WAY GIT CALLS IT: two arguments, the refs on stdin.
    local sha
    sha="$(git -C "$REPO" rev-parse HEAD)"
    DRIVE_OUT="${W}/hook-$1.log"
    set +e
    printf 'refs/heads/main %s refs/heads/main %s\n' "$sha" \
        "0000000000000000000000000000000000000000" |
        (cd "$REPO" && DJB_GATE_LEDGER="$LEDGER" ./scripts/githooks/pre-push origin "$W/origin") \
            >"$DRIVE_OUT" 2>&1
    DRIVE_EXIT=$?
    set -e
}

case_the_hook_honours_a_composed_row() {
    CURRENT=case_the_hook_honours_a_composed_row
    fresh_world hook_honours

    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    : >"${REC}/gate.calls"

    hook_run honours
    exited 0
    says "is measured green by a full gate run — verdict honoured"
    holds "gate invocations from the hook" "0" "$(count_lines "${REC}/gate.calls")"
}

case_a_short_legs_field_is_not_honoured() {
    CURRENT=case_a_short_legs_field_is_not_honoured
    fresh_world hook_short_legs
    local row short

    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    row="$(cat "$LEDGER")"
    # The SAME row, the SAME sanction and shards field, one leg short. A row
    # that names less than the gate declares is not a row the hook may honour.
    # FIELD 5 BY POSITION, never a substring of the whole line: the legs field
    # is no longer `FULL_LEGS` verbatim (its suite member carries a pass
    # count), and a substitution that missed would leave the row untouched and
    # this case green over a row it never shortened.
    short="$(printf '%s\n' "$row" | awk '{ $5 = "ruff,mypy"; print }')"
    printf '%s\n' "$short" >"$LEDGER"
    : >"${REC}/gate.calls"

    hook_run short_legs
    says "not honoured — measuring"
    says_not "verdict honoured"
}

# =============================================================================
# S.9 — boxes down on every exit path
# =============================================================================

# bank_sink_field <basename> <awk program> — read one of the bank's own sink
# files after the run. The sink is a `mktemp -d` under this world's TMPDIR and
# it survives the bank, which is what makes the launch log readable here at
# all; the glob is how its random name is found, and an absent file is NOTHING
# rather than a could-not-look, because the assertion above is what decides.
bank_sink_field() {
    local f
    for f in "$W"/tmp/djb-bank-boxes.*/"$1"; do
        [ -f "$f" ] || continue
        awk "$2" "$f" 2>/dev/null || true
        return 0
    done
    return 0
}

boxes_in_flight() {
    local f n=0
    for f in "$W"/tmp/djb-bank-boxes.*/boxes.tsv; do
        [ -f "$f" ] || continue
        n="$(count_lines "$f")"
    done
    printf '%s\n' "$n"
}

case_every_launched_box_is_taken_down_on_green_red_and_kill() {
    CURRENT=case_every_launched_box_is_taken_down_on_green_red_and_kill
    local downs uniq bankpid i rc

    # (a) GREEN. The green path takes them down ITSELF, before the push: this
    # script ends in `exec git push` and an exec never runs an EXIT trap.
    fresh_world down_on_green
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    holds "downs on a green bank (every shard and the acceptance box)" "$((PLAN_BOXES + 1))" \
        "$(count_lines "${REC}/down.calls")"
    downs="$(sorted_lines "${REC}/down.calls")"
    uniq="$(printf '%s\n' "$downs" | LC_ALL=C sort -u)"
    holds "each box taken down exactly once" "$uniq" "$downs"

    # (b) RED.
    fresh_world down_on_red
    printf '1\n' >"${REC}/box.rc.static"
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 1
    holds "downs on a red bank" "$((PLAN_BOXES + 1))" "$(count_lines "${REC}/down.calls")"

    # (c) A SIGNAL AFTER THREE BOXES ARE UP. The other five `up`s are still in
    # flight; the trap takes down the three it can name and says so.
    fresh_world down_on_kill
    # THE FIRST THREE SHARDS OF THIS TREE'S OWN PLAN, whatever they are
    # called: the case needs three boxes up and the rest still in flight.
    printf '%s\n' $PLAN_KILL_ALLOW >"${REC}/up.allow"
    DRIVE_OUT="${W}/run-kill.log"
    set +e
    "$RUNNER" --bank --no-fold --on-boxes "$PLAN_BOXES" >"$DRIVE_OUT" 2>&1 &
    bankpid=$!
    i=0
    while [ "$(boxes_in_flight)" -lt 3 ] && [ "$i" -lt 300 ]; do
        sleep 0.1
        i=$((i + 1))
    done
    if [ "$(boxes_in_flight)" -lt 3 ]; then
        : >"${REC}/release"
        wait "$bankpid" >/dev/null 2>&1
        set -e
        bad "three boxes never reached the bank's own census — the signal had nothing to interrupt"
        return
    fi
    kill -TERM "$bankpid" 2>/dev/null
    : >"${REC}/release"
    wait "$bankpid"
    rc=$?
    set -e
    DRIVE_EXIT="$rc"
    exited 143
    holds "downs after the signal" "3" "$(count_lines "${REC}/down.calls")"
    says "the bank stopped (exit 143) with boxes still up"
    holds "verdict rows after a signal" "0" "$(ledger_rows)"
}

# WHY A BOX CAN LAUNCH AND THE `up` STILL FAIL. `up` launches the
# instance, waits for SSM to report the agent Online, and THEN probes the
# tunnel — and the probe's `die` fires before the `instance` line is printed.
# The bank read its id out of that line, so a box whose probe failed was a box
# the teardown could not name: launched, billing, and invisible to every list
# this script keeps. The `launched` line is printed the moment the instance
# exists, and this is the case that says the bank reads it BEFORE it reads the
# status.
case_a_box_whose_up_failed_after_the_launch_is_still_taken_down() {
    CURRENT=case_a_box_whose_up_failed_after_the_launch_is_still_taken_down
    local launched

    fresh_world launched_then_failed
    printf '2\n' >"${REC}/up.launched_then_rc.${PLAN_VICTIM}"

    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    # THE BANK STILL REFUSES. A box that did not come up is a unit nobody
    # measured, and naming the box is not the same as having its answer.
    exited 2
    says "a box did not come up: ${PLAN_VICTIM}"
    holds "verdict rows" "0" "$(ledger_rows)"

    launched="$(bank_sink_field up-${PLAN_VICTIM}.log '$1 == "launched" { print $2; exit }')"
    if [ -z "$launched" ]; then
        DRIVE_OUT="${REC}/down.calls"
        bad "the stub's up printed no launched line — the case cannot assert what it is for"
    elif grep -qxF "$launched" "${REC}/down.calls"; then
        ok "the box that launched and then failed was taken down: ${launched}"
    else
        DRIVE_OUT="${REC}/down.calls"
        bad "${launched} launched and was never taken down"
    fi
    DRIVE_OUT="${W}/run-__bank___no_fold___on_boxes_${PLAN_BOXES}.log"
    assert_mac_measured_nothing
}

case_a_failed_down_names_the_hand_and_keeps_the_status() {
    CURRENT=case_a_failed_down_names_the_hand_and_keeps_the_status

    # (a) A GREEN BANK WHOSE BOXES WOULD NOT GO DOWN. The row IS banked — it is
    # honest — and the status becomes 2, because a clean exit over a machine
    # still billing must not read as success.
    fresh_world failed_down_green
    : >"${REC}/down.fail"
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 2
    says "IT IS STILL UP"
    says "scripts/verifier_box.sh down"
    says "scripts/verifier_box.sh census"
    holds "the verdict was still banked" "1" "$(ledger_rows)"
    says_not "pm_push: pushing"

    # (b) A RED BANK WHOSE BOXES WOULD NOT GO DOWN. The status STAYS the
    # original failure's: what has to be fixed is still the red tree.
    fresh_world failed_down_red
    : >"${REC}/down.fail"
    printf '1\n' >"${REC}/box.rc.${PLAN_VICTIM_FIRST}"
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 1
    says "IT IS STILL UP"
    holds "no row over a red tree" "0" "$(ledger_rows)"
}

# =============================================================================
# a.4 / a.5 — the acceptance box: the test-impact map, OUTSIDE the verdict
# =============================================================================
#
# WHY THESE TWO CASES EXIST. The bank is the one claim in this repository that a
# WHOLE tree passed a WHOLE gate, and the acceptance box is a MEASUREMENT
# hanging off it — a whole extra suite run, on a box nobody waits for, whose
# answer is a FILE and never a verdict. Two ways of wiring that are wrong and
# both look exactly like it working: the measurement could join the composition,
# and then a coverage run that died would refuse a tree every shard passed; or
# it could be handed a `--leg`, and then it would be a unit of the gate whose
# legs have to add up. Each is a case below, and the composition's leg set is
# compared for EQUALITY across a bank with a map and a bank without one — the
# property is "unchanged", never "plausible".

# The map's own reader, so a case asks the file a question rather than grepping
# JSON with a regular expression. This checkout's interpreter, never `python3`
# off PATH — on a verifier box that is the system 3.9.
ACCEPT_PY="$ROOT/.venv/bin/python"

accept_mapq() {
    [ -x "$ACCEPT_PY" ] || {
        printf '<no interpreter>\n'
        return 0
    }
    "$ACCEPT_PY" -c '
import json, sys
with open(sys.argv[1]) as fh:
    doc = json.load(fh)
q = sys.argv[2]
if q == "tree":
    print(doc["generated"]["tree"])
elif q == "n_tests":
    print(len(doc["tests"]))
else:
    raise SystemExit("unknown query " + q)
' "$REPO/scripts/test_impact.json" "$1"
}

case_the_acceptance_box_is_outside_the_verdict() {
    CURRENT=case_the_acceptance_box_is_outside_the_verdict
    local tree8 legs_green legs_red

    # (a) THE MAP FAILED AND THE BANK IS STILL GREEN. A coverage run that died
    # is a measurement nobody got: the loop keeps the closure scope it has
    # today, and a tree every shard passed is green whatever the ninth box did.
    fresh_world acceptance_rc1
    printf '1\n' >"${REC}/accept.rc"
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    holds "verdict rows" "1" "$(ledger_rows)"
    says "acceptance: map NOT written (exit 1) — the loop keeps the closure scope"
    legs_red="$(awk '{print $5}' "$LEDGER")"
    if grep -qF 'test_impact.json' "${REC}/fetch.calls" 2>/dev/null; then
        bad "the map was fetched from a box that did not write one"
    else
        ok "no map was fetched from a failed acceptance box"
    fi
    assert_mac_measured_nothing

    # (b) THE MAP LANDED. The same bank, the same composition, plus a file.
    fresh_world acceptance_rc0
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    holds "verdict rows" "1" "$(ledger_rows)"
    says "acceptance: scripts/test_impact.json rewritten"
    says "tree:beefcafe1234"
    holds "the map in the tree names the box's tree" "tree:beefcafe1234" "$(accept_mapq tree)"
    legs_green="$(awk '{print $5}' "$LEDGER")"
    assert_mac_measured_nothing

    # (c) THE COMPOSITION IS THE SAME EITHER WAY.
    holds "the composed leg set with and without a map" "$legs_red" "$legs_green"

    # (d) THE SEAM'S ARGV. The box is brought up like any other and then handed
    # ONE `run` — never a `--leg`, because a unit is a part of the composed
    # verdict by definition and this box is not in it.
    fresh_world acceptance_argv
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    tree8="$(repo_tree)"
    tree8="${tree8:0:8}"
    DRIVE_OUT="${REC}/up.calls"
    says "bank-${tree8}-acceptance"
    DRIVE_OUT="${REC}/run.calls"
    says "--cov-context=test"
    says "scripts/test_impact.py write"
    # THE CHECKOUT PATH IS DERIVED AND NEVER SPELLED. `deploy/verifier/bake.sh`
    # is the ONE place it is written down, and `test_verifier_box.sh`'s census
    # reds any other file that spells it — correctly: a literal here is a
    # second place to keep in step.
    says "$(bake_checkout_path)"
    DRIVE_OUT="${REC}/leg.calls"
    says_not "acceptance"
    DRIVE_OUT="${REC}/fetch.calls"
    says "test_impact.json"

    # (e) NO ACCEPTANCE CHECKOUT TO READ IS NOT A BANK THAT FAILED, AND IT IS
    # THE ONE STATE IN WHICH THIS BANK IS BYTE-FOR-BYTE THE ONE IT WAS BEFORE
    # ADR gate-1's AMENDMENT. There can be no acceptance box, so there is no
    # whole-suite proof to stand on, so every pytest shard runs its own two
    # passes exactly as it always did: no `--passes` in any argv, no
    # `leak-proof=` field in the row, and the map is a printed line.
    fresh_world acceptance_no_checkout
    # COMMITTED, because `--bank` refuses a dirty checkout before it starts and
    # this case would otherwise measure that refusal instead of the plan.
    git -C "$REPO" rm -q deploy/verifier/bake.sh
    git -C "$REPO" commit -q -m "a checkout with no bake.sh to read"
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    holds "verdict rows" "1" "$(ledger_rows)"
    says "acceptance: no box"
    says_not "a box did not come up"
    says_not "--passes"
    DRIVE_OUT="${REC}/leg.calls"
    says_not "--passes"
    DRIVE_OUT="$LEDGER"
    says_not "leak-proof="
    if grep -F " ${REAL_FULL_LEGS} " "$LEDGER" >/dev/null; then
        ok "the legs field is FULL_LEGS itself — no member carries a pass count"
    else
        bad "the two-pass row's legs field is not FULL_LEGS: $(cat "$LEDGER")"
    fi
    assert_mac_measured_nothing

    # (f) A PLANNED PROOF THAT NEVER CAME UP IS EXIT 2, AND THAT IS THE WHOLE
    # DIFFERENCE THE AMENDMENT MAKES. Before it, a missing acceptance box cost
    # the map and nothing else. Now every pytest shard has been handed
    # `--passes 1` on the strength of a proof that is about to run on this
    # box, so a box that never came up leaves a bank that measured one pass
    # and can prove nothing about what it left behind — could-not-look, no
    # row, and never a green.
    fresh_world acceptance_planned_no_box
    printf '2\n' >"${REC}/up.rc.acceptance"
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 2
    holds "verdict rows" "0" "$(ledger_rows)"
    says "the leak proof could not be read — one pass was measured and nothing proved it left nothing behind"
    says "NO ROW WAS"
    # AND THE NOTE PRINTED ONE PHASE EARLIER AGREES WITH THE REFUSAL. Under a
    # two-pass plan this box was only ever the map's and the shards genuinely
    # were unaffected; under a one-pass plan they are not, and a note saying
    # so moments before the refusal would be the bank contradicting itself in
    # its own transcript.
    says "this bank will be"
    says "REFUSED — one pass was measured and nothing can prove it left nothing behind"
    says_not "every shard is unaffected"
    assert_mac_measured_nothing
}

# =============================================================================
# ADR gate-1's amendment — the bank's second pytest pass runs on one box
# =============================================================================
#
# WHAT CHANGED AND WHY THESE FOUR CASES EXIST. Until ADR gate-1's 2026-09-18
# amendment every pytest shard ran the suite TWICE over its own group under
# one seed — the idempotency belt — while the acceptance box ALSO ran the
# whole suite twice and its second pass was printed and composed nowhere. The
# bank was paying for the stronger proof and banking the weaker one. Now the
# shards run one pass and the acceptance box's two passes ARE the belt, which
# creates four new ways to bank a green that vouches for more than ran:
#
#   * a shard handed one pass by a bank that has no proof box (c.1)
#   * two passes on the proof box in DIFFERENT orders, which prove nothing
#     about state and everything about ordering (c.2)
#   * a proof nobody read, or a red one, reaching a row anyway (c.3)
#   * a row that says `pytest-x2` over one pass (c.4)
#
# Each is a case here, with its plant.
#
# WHAT THEY DO NOT COVER, declared rather than discovered: whether the box's
# proof was HONEST. A proof is a file a box wrote, fetched over the same seam
# as every shard's log, and a box whose suite LIED is invisible here exactly
# as a shard whose gate lied is. Nor do they reach `scripts/check.sh
# --passes 1` itself (`test_list_legs.sh`'s) or the ledger's reader
# (`test_loop_ledger.sh`'s); this drive asserts the SEAM's argv, the
# composition over what comes back, and the row the two produce.

case_the_plan_hands_passes_1_only_when_a_proof_box_exists() {
    CURRENT=case_the_plan_hands_passes_1_only_when_a_proof_box_exists
    local suite_shards plain_shards

    # (a) A PROOF BOX EXISTS, SO EVERY SUITE SHARD RUNS ONE PASS — every one
    # of them, and no other shard is touched. A bank that mixed the two would
    # compose a row whose legs field could not say which half of the suite ran
    # twice.
    fresh_world passes_with_proof_box
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    suite_shards="$(grep -c -- "--unit ${PLAN_SUITE_UNIT} --shard [0-9]*/[0-9]* --passes 1 --log leg" \
        "${REC}/leg.calls" || true)"
    holds "suite shards handed --passes 1" "$PLAN_SUITE_K" "${suite_shards:-0}"
    plain_shards="$(grep -c -- '--passes' "${REC}/leg.calls" || true)"
    holds "shards handed --passes at all (the suite unit's, and nothing else)" "$PLAN_SUITE_K" "${plain_shards:-0}"
    DRIVE_OUT="${W}/run-__bank___no_fold___on_boxes_${PLAN_BOXES}.log"
    says "--leg ${PLAN_SUITE_UNIT} --shard 1/${PLAN_SUITE_K} --passes 1"
    says "ONE pass per suite shard"
    # AND THE UNIT THAT RUNS NO SUITE IS NOT HANDED ONE. `selftest` shards the
    # same way and has no pass to drop; the plan reads WHICH unit carries the
    # suite leg out of the listing's own legs column.
    if [ "$PLAN_VICTIM_UNIT" != "$PLAN_SUITE_UNIT" ]; then
        says_not "--leg ${PLAN_VICTIM_UNIT} --shard 1/${PLAN_VICTIM_K} --passes"
    fi
    assert_mac_measured_nothing

    # (b) THE PLAN READS THE LISTING AND NOT A NAME. Move the suite leg onto
    # another unit in the listing and the `--passes 1` moves with it, with no
    # edit to pm_push.sh.
    fresh_world passes_follow_the_listing
    awk -F'\t' 'BEGIN { OFS = "\t" }
        $1 == "pytest-x2" { $4 = "temporal-census,partition,own-tree-census" }
        $1 == "selftest"  { $4 = $4 ",pytest-x2" }
        { print }' "$REAL_LISTING" >"${REC}/listlegs.out"
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    DRIVE_OUT="${REC}/leg.calls"
    if grep -q -- "--unit ${PLAN_VICTIM_UNIT} --shard [0-9]*/[0-9]* --passes 1 --log leg" "${REC}/leg.calls"; then
        ok "the pass count followed the suite leg to the unit the listing puts it in"
    else
        bad "the plan handed --passes 1 by unit name and not by the listing's legs"
    fi
    says_not "--unit ${PLAN_SUITE_UNIT} --shard 1/${PLAN_SUITE_K} --passes 1"

    # (c) NO PROOF BOX, NO ONE-PASS SHARD. The world with no `bake.sh` is the
    # one state in which there can be no acceptance box at all, and every
    # pytest shard then runs the two passes it always did.
    fresh_world passes_without_proof_box
    git -C "$REPO" rm -q deploy/verifier/bake.sh
    git -C "$REPO" commit -q -m "a checkout with no bake.sh to read"
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    holds "shards handed --passes with no proof box" "0" \
        "$(grep -c -- '--passes' "${REC}/leg.calls" || true)"
    holds "verdict rows" "1" "$(ledger_rows)"

    # (d) A SHARD THAT DISAGREES WITH ITS OWN PLAN LINE IS EXIT 2 AND NO ROW.
    # The plan handed one pass; this shard's banner says it ran the default
    # two. One of the two is wrong about what was measured and neither the
    # bank nor a reader afterwards can tell which, so nothing is banked.
    fresh_world passes_shard_disagrees
    awk -F'\t' -v u="$PLAN_SUITE_UNIT" '$1 == u { print $4 }' "$REAL_LISTING" \
        >"${REC}/box.legs.${PLAN_SUITE_LAST}"
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 2
    says "the plan and the unit listing disagree"
    says "${PLAN_SUITE_UNIT}: planned --passes 1 and the shard reports ${PLAN_SUITE_LEG}"
    holds "verdict rows" "0" "$(ledger_rows)"
    assert_mac_measured_nothing
}

case_the_acceptance_command_mints_one_seed_and_writes_a_proof() {
    CURRENT=case_the_acceptance_command_mints_one_seed_and_writes_a_proof
    local cmd seeds

    fresh_world acceptance_proof_argv
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    # THE ARGV STRING THE BOX'S SHELL IS HANDED, read out of the stub's own
    # record. Everything past it is `scripts/verifier_box.sh`'s and the box's.
    cmd="$(grep -F -- 'test_impact.py write' "${REC}/run.calls" || true)"
    DRIVE_OUT="${REC}/run.calls"
    if [ -z "$cmd" ]; then
        bad "no acceptance command was recorded at all"
        return
    fi
    # ONE SEED, MINTED ON THE BOX, ON BOTH PASSES. Two occurrences of ONE
    # variable — not two literals and not two mintings: with different orders
    # a red pass 2 means "order or state, cannot tell", which is not a leak
    # proof, and it would be banked as if it were.
    seeds="$(printf '%s\n' "$cmd" | grep -o -- '--randomly-seed=[^ ]*' | LC_ALL=C sort -u | grep -c . || true)"
    holds "distinct --randomly-seed= spellings in the command" "1" "${seeds:-0}"
    holds "passes carrying that seed" "2" \
        "$(printf '%s\n' "$cmd" | grep -o -- '--randomly-seed=' | grep -c . || true)"
    says "SEED="
    says "-n 16"
    says "proof.txt"
    says "pass1="
    says "pass2="
    says "map="
    # BOTH PASSES UNDER `set +e`, EACH WRITING ITS OWN rc, and the command
    # still exits 0 — the wrapper's status stays "the command ran" and the
    # three statuses travel home as data.
    says "P1=\$?"
    says "P2=\$?"
    says "set +e"
    says "exit 0"
    # THE MAP WRITER ONLY AFTER A GREEN PASS 1. A map inverted out of a
    # coverage database a red pass abandoned is a projection of half a run.
    if printf '%s\n' "$cmd" | grep -F 'if [ "${P1}" = 0 ]; then .venv/bin/python scripts/test_impact.py write' >/dev/null; then
        ok "the map writer is guarded on a green pass 1"
    else
        bad "the map writer is not guarded on pass 1's own status"
    fi
    # AND THE SUMMARY LINE CARRIES ALL THREE STATUSES.
    if printf '%s\n' "$cmd" | grep -F 'rc1=${P1} rc2=${P2} map=${MAP}' >/dev/null; then
        ok "the box's summary line names pass 1, pass 2 and the map separately"
    else
        bad "the summary line does not carry rc1= rc2= map="
    fi
    # THE CHECKOUT PATH IS STILL DERIVED AND NEVER SPELLED.
    says "$(bake_checkout_path)"
}

case_the_leak_proof_is_composed_and_the_map_is_not() {
    CURRENT=case_the_leak_proof_is_composed_and_the_map_is_not
    local sink

    # (a) A RED PASS 2 REFUSES THE ROW. This is the whole point of the rung:
    # before it, this exact state was exit 0 with a row banked and the box's
    # own rc printed into a terminal.
    fresh_world proof_pass2_red
    printf 'seed=8675309 workers=16 pass1=0 pass2=1 map=0\n' >"${REC}/accept.proof"
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 1
    holds "verdict rows" "0" "$(ledger_rows)"
    says "the gate is RED"
    says "the leak proof is RED"
    says "pass1=0 pass2=1"
    says "acceptance.log"
    assert_mac_measured_nothing

    # (a2) AND SO DOES A RED PASS 1, for the same reason and by the same road.
    fresh_world proof_pass1_red
    printf 'seed=8675309 workers=16 pass1=1 pass2=0 map=2\n' >"${REC}/accept.proof"
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 1
    holds "verdict rows" "0" "$(ledger_rows)"
    says "the leak proof is RED"

    # (b) A PROOF THAT NEVER CAME BACK IS COULD-NOT-LOOK, WHICH OUTRANKS EVERY
    # SHARD'S PASS. One pass was measured and nothing says what it left behind.
    fresh_world proof_absent
    : >"${REC}/accept.proof.absent"
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 2
    holds "verdict rows" "0" "$(ledger_rows)"
    says "the leak proof could not be read — one pass was measured and nothing proved it left nothing behind"
    says "fetch-proof.log"
    assert_mac_measured_nothing

    # (b2) AND SO IS ONE NOBODY CAN PARSE. A proof with no seed is two runs of
    # the suite and not a pair, whatever its statuses say.
    fresh_world proof_unparsable
    printf 'workers=16 pass1=0 pass2=0 map=0\n' >"${REC}/accept.proof"
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 2
    holds "verdict rows" "0" "$(ledger_rows)"
    says "the leak proof could not be read — one pass was measured and nothing proved it left nothing behind"

    # (b3) AND AN rc THAT IS NOT A DECIMAL IS NEITHER GREEN NOR RED. A reader
    # that took it as green would bank the strongest claim over the least
    # readable evidence.
    fresh_world proof_rc_not_a_number
    printf 'seed=8675309 workers=16 pass1=0 pass2=ok map=0\n' >"${REC}/accept.proof"
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 2
    holds "verdict rows" "0" "$(ledger_rows)"
    says "the leak proof could not be read — one pass was measured and nothing proved it left nothing behind"

    # (c) A DEAD MAP WRITER BESIDE TWO GREEN PASSES IS A ROW, AND THE MAP LINE
    # SAYS NOT WRITTEN. The two roles separate exactly here: `pass1=`/`pass2=`
    # are the claim, `map=` is the measurement, and a measurement may not
    # refuse a tree whose every pass was green.
    fresh_world proof_map_died
    printf 'seed=8675309 workers=16 pass1=0 pass2=0 map=1\n' >"${REC}/accept.proof"
    : >"${REC}/accept.map.absent"
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    holds "verdict rows" "1" "$(ledger_rows)"
    # THE MAP LINE NAMES THE CAUSE THE BOX PROVED. The command always exits 0,
    # so "the box said 0 and no file came back" is true of a dead writer and
    # of a fetch that could not reach the file; `map=1` in the proof says
    # which, and the reader that already has the file says so.
    says "acceptance: map NOT written (the box's map writer exited 1)"
    says_not "the box said 0 and no file came back"
    says "the leak proof — seed=8675309"
    says "map= is a measurement and decides nothing"
    DRIVE_OUT="$LEDGER"
    says "leak-proof=acceptance:"
    assert_mac_measured_nothing

    # (d) TWO GREEN PASSES AND A GREEN MAP: one row, and the map rewritten.
    fresh_world proof_all_green
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    holds "verdict rows" "1" "$(ledger_rows)"
    says "scripts/test_impact.json rewritten"
    says "pass1=0 pass2=0"
    holds "the map in the tree names the box's tree" "tree:beefcafe1234" "$(accept_mapq tree)"
    assert_mac_measured_nothing

    # (e) THE SINK'S OWN FILE. The proof lands beside every other thing the
    # bank fetched, under the name the composition reads.
    sink="$(grep -F 'proof.txt' "${REC}/fetch.calls" | awk -F'\t' '{ print $3; exit }' || true)"
    case "$sink" in
    */acceptance.proof)
        ok "the proof is fetched to \${SINK}/acceptance.proof: ${sink}"
        ;;
    *)
        bad "the proof was fetched to '${sink:-<nowhere>}', not \${SINK}/acceptance.proof"
        ;;
    esac
}

# =============================================================================
# a red bank NAMES the first failing test and the command that replays it
# =============================================================================
#
# WHY. Before this, a red leak proof ended at `pass1=0 pass2=1` and a path to a
# log on a machine that no longer exists: the boxes are terminated four lines
# later, so a proof's two pass logs are readable exactly once — here, before
# the teardown — and a refusal that did not bring them home was a refusal
# nobody could act on without re-running the whole bank. The line is PRINTED
# beside the table and composed nowhere: the verdict row's grammar gains
# nothing, because a red bank writes no row at all.

case_a_red_leak_proof_names_the_first_failing_test_and_the_replay() {
    CURRENT=case_a_red_leak_proof_names_the_first_failing_test_and_the_replay
    local fetched

    fresh_world red_proof_names_the_test
    printf 'seed=8675309 workers=16 pass1=0 pass2=1 map=0\n' >"${REC}/accept.proof"
    {
        echo "Using --randomly-seed=8675309"
        echo "=========================== short test summary info ============================"
        echo "FAILED apps/example/tests/test_doors.py::test_rest_and_mcp_agree - AssertionEr..."
        echo "FAILED apps/core/tests/test_audit.py::test_append_only - assert 1 == 2"
    } >"${REC}/accept.pass2"

    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 1
    holds "verdict rows" "0" "$(ledger_rows)"
    says "the leak proof is RED"
    says "first failing: apps/example/tests/test_doors.py::test_rest_and_mcp_agree (pass 2; 2 FAILED) - replay: ./scripts/test.sh -n 16 --randomly-seed=8675309 apps/example/tests/test_doors.py::test_rest_and_mcp_agree"

    # THE LOGS CAME HOME BEFORE THE BOXES WENT. Both of them, on the laxer
    # condition the proof itself is fetched on: whenever there is a box.
    fetched="$(grep -c 'pass[12].log' "${REC}/fetch.calls" || true)"
    holds "pass logs fetched" "2" "${fetched:-0}"
    assert_mac_measured_nothing

    # AND ON A GREEN BANK TOO — the fetch is not conditional on a red, because
    # the condition is "there is a box to ask", and by the time anybody knows
    # the bank is red the box is the one thing that is about to be gone.
    fresh_world green_still_fetches_the_pass_logs
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    fetched="$(grep -c 'pass[12].log' "${REC}/fetch.calls" || true)"
    holds "pass logs fetched on a green bank" "2" "${fetched:-0}"
    says_not "first failing:"
}

case_a_red_shard_names_its_first_failing_test() {
    CURRENT=case_a_red_shard_names_its_first_failing_test

    fresh_world red_shard_names_the_test
    printf '1\n' >"${REC}/box.rc.${PLAN_SUITE_FIRST}"
    {
        echo "Using --randomly-seed=424242"
        echo "=========================== short test summary info ============================"
        echo "FAILED apps/connections/tests/test_relay.py::test_at_least_once - TimeoutError"
    } >"${REC}/box.faillog.${PLAN_SUITE_FIRST}"

    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 1
    holds "verdict rows" "0" "$(ledger_rows)"
    says "the gate is RED"
    says "first failing: apps/connections/tests/test_relay.py::test_at_least_once (${PLAN_SUITE_FIRST}; 1 FAILED) - replay: ./scripts/test.sh -n 16 --randomly-seed=424242 apps/connections/tests/test_relay.py::test_at_least_once"
    assert_mac_measured_nothing

    # A RED SHARD THAT IS NOT PYTEST NAMES NOTHING, and that is derived from
    # the log rather than from a unit name: a `static` leg that reddened has
    # no failing test to name, and a line saying `none named` under it would
    # be noise claiming to be evidence.
    fresh_world red_static_shard_names_nothing
    printf '1\n' >"${REC}/box.rc.static"
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 1
    says "the gate is RED"
    says_not "first failing:"
}

case_a_red_log_with_no_failed_line_says_none_named() {
    CURRENT=case_a_red_log_with_no_failed_line_says_none_named

    fresh_world red_proof_no_failed_line
    printf 'seed=8675309 workers=16 pass1=0 pass2=1 map=0\n' >"${REC}/accept.proof"
    # A PASS THAT DIED WITHOUT A SUMMARY — a collection error, an OOM, a box
    # that went away mid-run. The status is red and there is no nodeid in it;
    # a composer that invented one would be worse than one that says so.
    {
        echo "Using --randomly-seed=8675309"
        echo "INTERNALERROR> RuntimeError: the worker crashed"
    } >"${REC}/accept.pass2"

    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 1
    holds "verdict rows" "0" "$(ledger_rows)"
    says "the leak proof is RED"
    says "first failing: none named - no FAILED line in"
    says "/pass2.log"
    says_not "replay: ./scripts/test.sh"
    assert_mac_measured_nothing
}

case_the_composed_row_carries_the_proof_and_the_hook_reads_it() {
    CURRENT=case_the_composed_row_carries_the_proof_and_the_hook_reads_it
    local row tree looked red_row aid f

    fresh_world row_leak_proof
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    holds "exactly one line appended" "1" "$(ledger_rows)"
    row="$(cat "$LEDGER")"
    tree="$(repo_tree)"
    DRIVE_OUT="$LEDGER"

    # THE ROW'S LAST FIELD, IN THE GRAMMAR THE READER PARSES. `rc=` is a
    # decimal with no leading zero, and the box id is the one the bank
    # actually brought up — asserted against the stub's own record rather than
    # against a literal, so a row naming some OTHER box is a FAILED case.
    if printf '%s\n' "$row" | grep -E ' leak-proof=acceptance:i-[0-9a-f]+ rc=0$' >/dev/null; then
        ok "the row's last field is the leak proof, green"
    else
        bad "the row carries no leak-proof field: ${row}"
    fi
    # THE ID IS THE ACCEPTANCE BOX'S OWN, and it is read back out of the
    # stub's record of which box got which label rather than recomposed here:
    # a row naming SOME box would satisfy the pattern above while naming the
    # wrong machine, and the field's whole job is to say which box proved it.
    aid=""
    for f in "${REC}"/label-of.*; do
        [ -f "$f" ] || continue
        if grep -qx acceptance "$f"; then
            aid="${f##*/label-of.}"
            break
        fi
    done
    if [ -z "$aid" ]; then
        bad "no acceptance box id was recorded at all — there is nothing to compare the field against"
    elif printf '%s\n' "$row" | grep -F " leak-proof=acceptance:${aid} rc=0" >/dev/null; then
        ok "the field names the box the bank actually brought up: ${aid}"
    else
        bad "the field names a box that is not the acceptance box (${aid}): ${row}"
    fi
    # `took=` IS STILL THE SLOWEST PYTEST SHARD'S OWN WALL: the proof is
    # appended AFTER it and displaces nothing.
    if printf '%s\n' "$row" | grep -E ' waited=0 took=[0-9]+ leak-proof=' >/dev/null; then
        ok "took= is still the field before the proof, and still a number"
    else
        bad "the cost fields moved when the proof was appended: ${row}"
    fi
    # AND THE LIBRARY FINDS IT — with the proof green, a `pytest-x2/1` member
    # covers the declared `pytest-x2`.
    looked="$(cd "$REPO" && DJB_GATE_LEDGER="$LEDGER" bash -c '. scripts/gate_ledger.sh && gate_ledger_lookup "$1"' _ "$tree" 2>/dev/null || true)"
    holds "gate_ledger_lookup returns it" "$row" "$looked"

    # THE HOOK HONOURS IT IN SECONDS, WITH THE GATE UNCALLED.
    : >"${REC}/gate.calls"
    hook_run leak_proof_honoured
    exited 0
    says "is measured green by a full gate run — verdict honoured"
    holds "gate invocations from the hook" "0" "$(count_lines "${REC}/gate.calls")"

    # AND THE SAME ROW WITH A RED PROOF IS NOT HONOURED. One byte — `rc=0` to
    # `rc=1` — and the row names one pass with nothing standing behind it.
    red_row="${row% rc=0} rc=1"
    printf '%s\n' "$red_row" >"$LEDGER"
    : >"${REC}/gate.calls"
    hook_run leak_proof_red
    # THE READER'S OWN SENTENCE FOR THIS STATE, not the generic missing-leg
    # one: a reader who cannot tell "the row is short" from "the row ran half
    # of what it says" re-measures for a reason they cannot act on.
    says "the row ran ONE pass and carries no green leak proof"
    says "Not honoured — measuring"
    says_not "verdict honoured"
}

# bake_checkout_path — the shipped reader, over the shipped file. Never a
# literal: `deploy/verifier/bake.sh` is the one place the path is written down
# and `test_verifier_box.sh` censuses every other spelling of it.
bake_checkout_path() {
    (cd "$ROOT" && ROOT="$ROOT" bash -c '
        eval "$(sed -n "/^bank_boxes_box_checkout()/,/^}/p" scripts/pm_push.sh)"
        bank_boxes_box_checkout
    ' 2>/dev/null || true)
}

case_the_bank_reads_the_real_checkout_path_out_of_bake_sh() {
    CURRENT=case_the_bank_reads_the_real_checkout_path_out_of_bake_sh
    local got

    # THE ONE CASE THAT DOES NOT USE THE STUB, and it exists because every
    # other case does. The world above writes its own `deploy/verifier/bake.sh`
    # with the two knob lines in today's shape; if the REAL file's shape moved,
    # every stubbed case would stay green while the bank silently lost its
    # acceptance box on every real run. So this one asks the shipped reader
    # about the shipped file.
    got="$(bake_checkout_path)"
    case "$got" in
    /*)
        ok "the real deploy/verifier/bake.sh yields an absolute checkout path: ${got}"
        ;;
    *)
        bad "bank_boxes_box_checkout read '${got:-<nothing>}' out of the real deploy/verifier/bake.sh — the bank would run no acceptance box at all, silently, on every real bank"
        ;;
    esac
    case "$got" in
    *'${BAKE_USER}'* | *'$BAKE_USER'*)
        bad "the path still carries an unexpanded \${BAKE_USER}: ${got}"
        ;;
    *)
        ok "the user knob is expanded, not carried through as a literal"
        ;;
    esac
}

case_the_map_lands_in_the_tree_uncommitted() {
    CURRENT=case_the_map_lands_in_the_tree_uncommitted
    local head_before head_after dirty

    fresh_world map_uncommitted
    head_before="$(git -C "$REPO" rev-parse HEAD)"
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0

    head_after="$(git -C "$REPO" rev-parse HEAD)"
    holds "the bank committed nothing" "$head_before" "$head_after"
    dirty="$(git -C "$REPO" status --porcelain -- scripts/test_impact.json)"
    if [ -n "$dirty" ]; then
        ok "the map is modified in the working tree: ${dirty}"
    else
        bad "the map is not modified in the working tree — nothing was fetched into it"
    fi
    says "git add scripts/test_impact.json"

    # AND THE NEXT BANK IN THE SAME CHECKOUT SEES THAT FILE. This is the half
    # a green-only case would miss and it is asserted rather than assumed: the
    # bank refuses a dirty checkout BEFORE it starts, and the map it wrote
    # itself is the one file that is dirty afterwards — so the second bank
    # refuses at exit 2, NAMES the map in `git status --short`, and banks
    # nothing. That is the correct behaviour and not a trap: a derived file the
    # bank produced has to be COMMITTED before the tree it vouches for is the
    # tree that gets pushed, which is the same rule `pm_fold.sh` exists to
    # satisfy for every other derived file. Nothing here is silently swallowed.
    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 2
    says "has uncommitted changes"
    says "scripts/test_impact.json"
    holds "verdict rows after the refusal" "1" "$(ledger_rows)"
    holds "the map in the tree, untouched by the refusal" "tree:beefcafe1234" "$(accept_mapq tree)"
}

# =============================================================================
# DOC-1 — the docs-only road, which runs before either arm
# =============================================================================
#
# WHAT IS BEING ASSERTED. A bank whose whole delta since the nearest MEASURED
# ancestor is documentation must (a) launch nothing, take no lease and take no
# pytest slot, (b) run EXACTLY the readers those paths have and nothing else,
# (c) write ONE ordinary full row the hook then honours, and (d) refuse, by
# name and into a full bank, on every doubt. Each of those is a way the road
# could be silently wrong: a road that launched a box would have spent the
# money it exists to save, a road that ran no reader would be a green nobody
# measured, and a road that wrote a row the hook cannot read would cost the
# push the whole gate anyway.
#
# THE FIXTURE DOC'S PATH IS COMPOSED AND NOT SPELLED — `test_loop_ledger.sh`'s
# reason and the cycle-plan fixture's before it: the dangling-docs leg refuses
# a documentation pointer that is in no tree, and every doc here lives only
# inside a scratch repository.
PMPUSH_DIR="docs/fixtures"
PMPUSH_DOC="${PMPUSH_DIR}/rows.md"

#: The measured commit's tree in the world just built — M in the road's own
#: letter, and the tree every `from=` here names.
PMPUSH_MTREE=""
#: The legs field the planted source row carries: the real declaration with
#: the suite member at ONE pass, which is what a sharded bank banks today, and
#: a green leak proof beside it. Composed from the real declaration rather
#: than typed, `case_the_composed_row_has_the_grammar_and_one_writer`'s rule.
PMPUSH_SOURCE_LEGS=""
PMPUSH_PROOF=" leak-proof=acceptance:i-0drivebox0000000 rc=0"

# A world whose HEAD is one docs-only commit on top of a MEASURED tree.
#
# `$1` is what the docs commit also touches, or nothing: a case that means to
# put a path OUTSIDE the declared list in the delta names it here.
world_docs_only() {
    local also="${1:-}"
    fresh_world docs_only
    PMPUSH_SOURCE_LEGS=",${REAL_FULL_LEGS},"
    PMPUSH_SOURCE_LEGS="${PMPUSH_SOURCE_LEGS//,${PLAN_SUITE_LEG},/,${PLAN_SUITE_LEG}/1,}"
    PMPUSH_SOURCE_LEGS="${PMPUSH_SOURCE_LEGS#,}"
    PMPUSH_SOURCE_LEGS="${PMPUSH_SOURCE_LEGS%,}"
    mkdir -p "${REPO}/${PMPUSH_DIR}" "$REPO/scripts/tests" "$REPO/quality"
    printf 'the rows\n' >"${REPO}/${PMPUSH_DOC}"
    printf 'rules: []\n' >"$REPO/quality/probe.yaml"
    # THE STUB DRIVE. It declares the fixture directory, records its argv and
    # answers from a fixture — the same shape as every other stub in this
    # drive, so a case can red it, break it, or watch it run.
    {
        echo '#!/usr/bin/env bash'
        printf '# %s %s\n' 'drives:' "$PMPUSH_DIR"
        echo "printf 'ran %s\\n' \"\$*\" >>\"${REC}/drive.calls\""
        echo 'echo "STUB DRIVE ran"'
        echo "exit \"\$(cat \"${REC}/drive.rc\" 2>/dev/null || echo 0)\""
    } >"$REPO/scripts/tests/test_docs_probe.sh"
    chmod +x "$REPO/scripts/tests/test_docs_probe.sh"
    git -C "$REPO" add -A >/dev/null
    git -C "$REPO" commit -q -m "a measured tree with a doc and a drive that reads it"
    PMPUSH_MTREE="$(repo_tree)"
    docs_only_row "$PMPUSH_MTREE" "$PMPUSH_SOURCE_LEGS" "$PMPUSH_PROOF"
    printf 'one more row\n' >>"${REPO}/${PMPUSH_DOC}"
    [ -z "$also" ] || printf 'a line nobody measured\n' >>"${REPO}/${also}"
    git -C "$REPO" add -A >/dev/null
    git -C "$REPO" commit -q -m "a documentation commit"
}

# One full row in this world's ledger, written the way a bank writes it.
docs_only_row() {
    printf 'v1 %s full 2026-09-19T00:00:00Z %s caller=pm-bank sanction=push-wall boxes=5 shards=static waited=0 took=100%s\n' \
        "$1" "$2" "${3:-}" >>"$LEDGER"
    echo "  PLANT TOOK · source row: tree=${1} legs=${2}"
}

# The rows THIS RUN wrote: every line in the ledger that is not one of the
# source rows the world planted. `ledger_rows` counts the file, and a world
# that seeds a measured ancestor has a row in it before the subject runs — so
# a case asserting "one row" against the file would be asserting the plant.
#
# `grep -vc` PRINTS ITS ZERO AND EXITS 1, which is the trap `count_lines`
# records one helper over; the same guard, for the same reason.
docs_only_new_rows() {
    local n
    n="$(grep -vc ' full 2026-09-19T00:00:00Z ' "$LEDGER" 2>/dev/null || true)"
    case "$n" in '' | *[!0-9]*) n=0 ;; esac
    printf '%s\n' "$n"
}

# The gate's argv, with `--list-legs` taken out: what this Mac was asked to
# MEASURE, which is the whole question S.15 asks.
gate_measuring_calls() {
    grep -v -- '--list-legs' "${REC}/gate.calls" 2>/dev/null || true
}

case_a_docs_only_delta_runs_the_readers_and_banks_without_a_box() {
    CURRENT=case_a_docs_only_delta_runs_the_readers_and_banks_without_a_box
    world_docs_only
    local row tree calls

    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    says "docs-only? yes"
    says "docs-only reuse of ${PMPUSH_MTREE}"

    # (a) NOTHING WAS LAUNCHED AND NOTHING WAS TAKEN. `--on-boxes 8` is on the
    #     command line and no box exists: the road decided BEFORE the arms.
    holds "up calls" "0" "$(count_lines "${REC}/up.calls")"
    holds "verifier wrapper calls" "0" "$(count_lines "${REC}/vb.calls")"
    if [ -e "${W}/lease/djb-gate-lease" ]; then
        bad "the docs-only road took the machine-wide full-gate lease"
    else
        ok "no lease"
    fi
    if [ -e "${W}/lease/djb-gate-slots" ]; then
        bad "the docs-only road took a pytest slot"
    else
        ok "no pytest slot"
    fi

    # (b) EXACTLY THE DERIVED READERS. `--leg static` always; the stub drive
    #     because it DECLARES the directory that moved; and nothing else — in
    #     particular never `--bank`, which is the whole bank this road exists
    #     not to run.
    calls="$(gate_measuring_calls)"
    holds "the gate's measuring argv" "--leg static" "$calls"
    holds "drive runs" "1" "$(count_lines "${REC}/drive.calls")"

    # (c) ONE ROW, IN THE ORDINARY GRAMMAR, KEYED ON THE PUSHED TREE.
    holds "rows this run wrote" "1" "$(docs_only_new_rows)"
    row="$(grep -v ' full 2026-09-19T00:00:00Z ' "$LEDGER" || true)"
    tree="$(repo_tree)"
    DRIVE_OUT="$LEDGER"
    if printf '%s\n' "$row" | grep -E \
        "^v1 ${tree} full [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z ${PMPUSH_SOURCE_LEGS} caller=pm-bank sanction=docs-only from=${PMPUSH_MTREE} paths=[0-9]+ readers=\S+ waited=0 took=0 leak-proof=acceptance:i-[0-9a-z]+ rc=0\$" >/dev/null; then
        ok "the row matches the docs-only grammar byte for byte"
    else
        bad "the row does not match the docs-only grammar: ${row}"
    fi
    holds "paths=" "paths=1" \
        "$(printf '%s\n' "$row" | awk '{ for (i = 1; i <= NF; i++) if ($i ~ /^paths=/) print $i }')"
    case "$row" in
    *"readers=static,scripts/tests/test_docs_probe.sh"*) ok "the sanction names the readers that ran, in the order they ran" ;;
    *) bad "the sanction's readers field is not the derived list: ${row}" ;;
    esac
    DRIVE_OUT="${W}/run-__bank___no_fold___on_boxes_${PLAN_BOXES}.log"

    # (d) THE COST, WHICH IS THE WHOLE POINT. The readers are stubs here, so
    #     what is asserted is the OVERHEAD the criterion bounds — the source
    #     walk, the delta and the row — and never the readers' own wall.
    local overhead
    overhead="$(awk '/^  source \+ delta \+ row: / { print $6 }' "$DRIVE_OUT")"
    case "${overhead:-x}" in
    '' | *[!0-9]*) overhead="" ;;
    esac
    if [ -n "$overhead" ] && [ "$overhead" -le 5 ]; then
        ok "source + delta + row took ${overhead}s, inside the 5s the criterion bounds"
    else
        bad "source + delta + row took '${overhead}'s (the line is absent, or over 5s)"
    fi
}

case_the_hook_honours_the_docs_only_row_and_measures_nothing() {
    CURRENT=case_the_hook_honours_the_docs_only_row_and_measures_nothing
    world_docs_only

    run_bank --bank --no-fold
    exited 0
    holds "rows this run wrote" "1" "$(docs_only_new_rows)"
    : >"${REC}/gate.calls"

    hook_run docs_only
    exited 0
    says "is measured green by a full gate run — verdict honoured"
    holds "gate invocations from the hook" "0" "$(count_lines "${REC}/gate.calls")"
}

case_one_path_off_the_declared_list_and_the_arm_runs_as_it_always_did() {
    CURRENT=case_one_path_off_the_declared_list_and_the_arm_runs_as_it_always_did
    world_docs_only uv.lock

    run_bank --bank --no-fold
    exited 0
    says "docs-only? no — uv.lock is not a docs-only path — full bank"
    # TODAY'S ARM FOLLOWS, and that is the half a refusal-only assertion
    # misses: the bank must still happen, not merely be declined.
    holds "the gate's measuring argv" "--bank" "$(gate_measuring_calls)"
    holds "drive runs" "0" "$(count_lines "${REC}/drive.calls")"
    # THE STUB GATE BANKS NOTHING — the row a `--bank` writes is the real
    # gate's, and this world has one that records argv and exits. So the
    # assertion that the bank happened is the argv above; what is asserted
    # here is that the ROAD wrote nothing of its own.
    holds "rows the road wrote" "0" "$(docs_only_new_rows)"
}

case_a_red_reader_is_a_red_tree_and_a_reader_that_could_not_look_is_a_full_bank() {
    CURRENT=case_a_red_reader_is_a_red_tree_and_a_reader_that_could_not_look_is_a_full_bank

    # (a) RED. A reader that went red is NOT a cheaper road — it is a red tree.
    world_docs_only
    printf '1\n' >"${REC}/drive.rc"
    run_bank --bank --no-fold
    exited 1
    says "docs-only readers RED: scripts/tests/test_docs_probe.sh"
    holds "rows this run wrote" "0" "$(docs_only_new_rows)"
    says_not "verdict banked"
    # AND THE BANK NEVER RAN: a red reader does not fall through to a full
    # gate that might disagree with it.
    holds "the gate's measuring argv" "--leg static" "$(gate_measuring_calls)"

    # (b) COULD NOT LOOK. Exit 2 is enforcement broken, and a reuse resting on
    #     a reader that could not look would be a green nobody measured — so
    #     the full bank follows and the row it writes is the bank's.
    world_docs_only
    printf '2\n' >"${REC}/drive.rc"
    run_bank --bank --no-fold
    exited 0
    says "could not look"
    says "full bank"
    case "$(gate_measuring_calls)" in
    *"--bank"*) ok "the full bank followed the reader that could not look" ;;
    *) bad "nothing measured the tree after a reader exited 2: $(gate_measuring_calls)" ;;
    esac
    holds "rows the road wrote" "0" "$(docs_only_new_rows)"
}

case_a_source_row_that_is_not_honoured_is_a_full_bank_with_the_lookups_note() {
    CURRENT=case_a_source_row_that_is_not_honoured_is_a_full_bank_with_the_lookups_note
    world_docs_only
    # THE SAME ROW, ONE LEG SHORT. `gate_ledger_lookup` refuses it and says
    # which leg; the road refuses WITH that note rather than walking past the
    # most recent thing the gate said about this line of development.
    : >"$LEDGER"
    docs_only_row "$PMPUSH_MTREE" "ruff,mypy"

    run_bank --bank --no-fold
    exited 0
    says "nearest banked ancestor's row is not honoured — full bank"
    says "so it is not honoured — measuring"
    case "$(gate_measuring_calls)" in
    *"--bank"*) ok "the full bank followed" ;;
    *) bad "no bank ran after an unhonoured source row" ;;
    esac

    # AND A ONE-PASS ROW WITH NO PROOF IS THE SAME ANSWER, for the same
    # reason: `pytest-x2/1` is half a claim without the box that proved it.
    world_docs_only
    : >"$LEDGER"
    docs_only_row "$PMPUSH_MTREE" "$PMPUSH_SOURCE_LEGS"
    run_bank --bank --no-fold
    exited 0
    says "nearest banked ancestor's row is not honoured — full bank"
    says "carries no green leak proof"
}

case_a_dirty_tree_refuses_before_the_road_and_the_measuring_valve_skips_it() {
    CURRENT=case_a_dirty_tree_refuses_before_the_road_and_the_measuring_valve_skips_it

    # (a) THE CLEAN-TREE REFUSAL IS STILL FIRST. The road sits after it on
    #     purpose: "the tree" has to be a thing that exists in history before
    #     anything can diff it.
    world_docs_only
    printf 'an uncommitted byte nobody can name\n' >>"${REPO}/${PMPUSH_DOC}"
    run_bank --bank --no-fold
    exited 2
    says "has uncommitted changes"
    says_not "docs-only?"
    holds "rows this run wrote" "0" "$(docs_only_new_rows)"

    # (b) THE MEASURING VALVE. One typed variable turns the road off for one
    #     run and says so in the transcript.
    world_docs_only
    export DJB_BANK_MEASURE=1
    run_bank --bank --no-fold
    unset DJB_BANK_MEASURE
    exited 0
    says "docs-only reuse SKIPPED by DJB_BANK_MEASURE — measuring"
    says_not "docs-only? yes"
    holds "the gate's measuring argv" "--bank" "$(gate_measuring_calls)"
}

# =============================================================================
# STG-1 — the image, built once, by the bank, from the banked tree
# =============================================================================
#
# WHY THESE CASES EXIST. The deployed image was built by CI behind a second
# full gate, under an OIDC role that had failed on every run for a month, and
# nothing anywhere said so: the registry simply stopped moving while every
# green tree went by. Building it in the bank fixes that and creates a new way
# to be wrong — a build that fails, a registry that is unreachable, a box
# standing on a different tree — and EVERY ONE OF THOSE MUST LEAVE THE VERDICT
# ALONE. A green row is a claim about bytes a gate measured; an image is an
# artefact derived from them afterwards. So every case below asserts the row as
# hard as it asserts the image.
#
# image_calls — how many times a box was asked to build.
image_calls() { count_lines "${REC}/image.calls"; }

# the tag this world's bank must build under — composed here from the repository
# rather than read out of the bank's own output, so a bank that composed it
# wrongly is a FAILED case and not an agreement between two copies of one bug.
world_image_tag() { printf 'tree-%s\n' "$(repo_tree | cut -c1-12)"; }

# THE MEASUREMENT MAY NOT DIRTY THE TREE IT MEASURED, and this case is the
# whole of that rule. BOXBANK-11 was green, banked and pushed, and its image
# was REFUSED: the acceptance run wrote the test-impact map into the box's own
# checkout, the image step ran on that same box a few seconds later, and
# `provision.sh image-tag` answered `tree-ee9be431c7b9-dirty`. The refusal was
# right — a tag that says the tree was uncommitted names an image nobody can
# reproduce — so the defect is upstream of it: a map is an OUTPUT of a
# measurement and belongs beside the measurement's other outputs, under
# `~/verify/<rung>/`, not in the tree the verdict is keyed on.
#
# IT IS ASSERTED THROUGH THE BOX'S COUPLING AND NOT THROUGH THE ARGV ALONE.
# The stub dirties itself iff the `--out` it is handed is a path inside the
# checkout, and the image seam then answers the way the real box answered — so
# this case reds on the old command by the same mechanism that cost the bank
# its image, rather than by a string nobody has ever seen a box print.
case_the_acceptance_map_never_dirties_the_box() {
    CURRENT=case_the_acceptance_map_never_dirties_the_box
    local tag out
    fresh_world map_outside_the_checkout
    tag="$(world_image_tag)"

    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    # THE MAP IS WRITTEN OUTSIDE THE CHECKOUT — the property, read off the argv
    # the box was handed.
    out="$(sed -n 's/.*--out \([^ ;]*\).*/\1/p' "${REC}/run.calls" | sed -n '1p')"
    case "$out" in
    /* | '$HOME'/* | '${HOME}'/*)
        ok "the map is written outside the checkout: ${out}"
        ;;
    *)
        bad "the map is written to '${out}', which is inside the checkout the image step reads"
        ;;
    esac
    # AND THE BOX IS THEREFORE CLEAN WHEN THE IMAGE STEP ASKS.
    if [ -s "${REC}/box.dirty" ]; then
        bad "the acceptance run left the box's tree dirty ($(cat "${REC}/box.dirty")) — the image step reads that tree"
    else
        ok "the acceptance run left the box's tree untouched"
    fi
    says_not "refusing to build under"
    says_not "image: NOT built"
    says "image: ${tag} pushed (web 39s, worker 41s)"
    # AND THE MAP STILL COMES HOME. The fix moves where the box WRITES it, not
    # where the Mac reads it from or where it lands here.
    says "acceptance: scripts/test_impact.json rewritten from"
    assert_mac_measured_nothing
}

case_the_image_is_built_after_the_row_and_never_on_a_red() {
    CURRENT=case_the_image_is_built_after_the_row_and_never_on_a_red
    local tag
    fresh_world image_after_row
    tag="$(world_image_tag)"

    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    holds "image builds (one box, never one per shard)" "1" "$(image_calls)"
    # THE ARGV THE BOX WAS HANDED, in full: the tag is the BANKED TREE's and
    # the refs are the two composed names. A build under any other tag is an
    # image nobody can tie to a verdict. Asserted against the recorded command
    # string and not against the bank's stdout, because the argv is the claim.
    image_argv_says() {
        if grep -qF -- "$1" "${REC}/image.calls"; then
            ok "the box was asked: $1"
        else
            bad "the box was NOT asked '$1' — it got: $(tr '\n' ' ' <"${REC}/image.calls" | cut -c1-500)"
        fi
    }
    image_argv_says "docker build --target web --tag 000000000000.dkr.ecr.us-east-1.amazonaws.com/drivens/djb-web:${tag}"
    image_argv_says "docker build --target worker --tag 000000000000.dkr.ecr.us-east-1.amazonaws.com/drivens/djb-worker:${tag}"
    image_argv_says "docker push 000000000000.dkr.ecr.us-east-1.amazonaws.com/drivens/djb-web:${tag}"
    image_argv_says "docker push 000000000000.dkr.ecr.us-east-1.amazonaws.com/drivens/djb-worker:${tag}"
    # THE BOX MINTS ITS OWN TOKEN. A token piped from this Mac would make every
    # bank depend on the operator's credentials, and would put a registry
    # password in a local argv. The region is DERIVED from the registry host.
    image_argv_says "aws ecr get-login-password --region us-east-1"
    # AND THE BOX CHECKS ITS OWN TREE BEFORE IT BUILDS — the half this Mac
    # cannot do, and the one that catches a box parked off the pushed tree.
    image_argv_says "./deploy/provision.sh image-tag"
    # AND IT PUTS THE TOKEN DOWN. `docker login` leaves the credential in the
    # box's `~/.docker/config.json`; the box dies minutes later, so this is
    # hygiene rather than a control — and hygiene that is one clause long is
    # hygiene worth having.
    image_argv_says "docker logout 000000000000.dkr.ecr.us-east-1.amazonaws.com"
    # THE ORDER, ASSERTED AS AN ORDER: the ledger as it stood when the box was
    # asked to build already carried the row.
    holds "verdict rows at the moment the build started" "1" "$(count_lines "${REC}/ledger.at.image")"
    holds "verdict rows" "1" "$(ledger_rows)"
    # AND THE BANK SAYS WHAT IT PUSHED, in the line a measurement row is read
    # from, with the registry's own digest beside it.
    says "image: ${tag} pushed (web 39s, worker 41s)"
    says "image: web sha256:0aa1 worker sha256:0bb2"
    assert_mac_measured_nothing
}

case_a_red_bank_builds_no_image() {
    CURRENT=case_a_red_bank_builds_no_image
    fresh_world image_red
    printf '1\n' >"${REC}/box.rc.${PLAN_VICTIM}"

    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 1
    # THE POSITIVE ANCHOR FIRST. Every other assertion here is an absence, and
    # a case made only of absences passes just as well when the bank refused
    # for some entirely different reason — or never ran at all. This line is
    # the composition saying WHY there is no image: the gate was red.
    says "the gate is RED. NO ROW WAS WRITTEN"
    says "${PLAN_VICTIM}"
    holds "image builds on a red bank" "0" "$(image_calls)"
    holds "verdict rows" "0" "$(ledger_rows)"
    says_not "pushed (web"
    assert_mac_measured_nothing
}

# STG1.2 — A TAG THAT IS NOT THIS TREE'S IS A LIE, AND THE BANK STILL STANDS.
# The box asserts its own `provision.sh image-tag` against the tag the bank
# keyed on, because that is the half this Mac cannot do: a box parked off the
# pushed tree would otherwise build the wrong bytes under the right name.
case_a_lying_tag_builds_nothing_and_the_bank_stands() {
    CURRENT=case_a_lying_tag_builds_nothing_and_the_bank_stands
    fresh_world image_lying_tag
    # The box's own refusal, exactly as the remote command prints it, and its
    # status. Nothing was built and nothing was pushed.
    {
        echo "!! image: refusing to build under 'tree-00000000000a-dirty' — this bank keys on a tree tag"
    } >"${REC}/image.out"
    printf '3\n' >"${REC}/image.rc"

    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    holds "verdict rows — the image is not the verdict" "1" "$(ledger_rows)"
    says "refusing to build under 'tree-00000000000a-dirty'"
    says "image: NOT built (exit 3)"
    says "the verdict row above STANDS"
    says_not "pushed (web"
    assert_mac_measured_nothing
}

# A FAILED BUILD OR PUSH IS PRINTED AND BANKS NOTHING AWAY. The registry going
# down may not retract a green: the fallback is CI's own job, which builds a tag
# the registry does not hold.
case_a_failed_push_is_printed_and_the_row_still_stands() {
    CURRENT=case_a_failed_push_is_printed_and_the_row_still_stands
    fresh_world image_push_failed
    {
        echo "Login Succeeded"
        echo "denied: User is not authorized to perform ecr:InitiateLayerUpload"
    } >"${REC}/image.out"
    printf '1\n' >"${REC}/image.rc"

    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    holds "verdict rows" "1" "$(ledger_rows)"
    says "image: NOT built (exit 1)"
    says "ecr:InitiateLayerUpload"
    says "CI's images job builds a tag"
    # AND THE BOXES STILL GO DOWN AND THE PUSH STILL HAPPENS: a failed image is
    # not a reason to leave nine machines billing.
    holds "boxes taken down" "$((PLAN_BOXES + 1))" "$(count_lines "${REC}/down.calls")"
    assert_mac_measured_nothing
}

# NO REGISTRY COORDINATE IS NOT A FAILURE, it is a deployment that has not been
# given one — every clone of this template starts there. It is printed, nothing
# is asked of any box, and the bank is green.
case_no_registry_coordinate_is_printed_and_nothing_is_built() {
    CURRENT=case_no_registry_coordinate_is_printed_and_nothing_is_built
    fresh_world image_no_registry
    rm -f "${REC}/registry"

    run_bank --bank --no-fold --on-boxes "$PLAN_BOXES"
    exited 0
    holds "verdict rows" "1" "$(ledger_rows)"
    holds "image builds" "0" "$(image_calls)"
    says "image: not built — no registry coordinate"
    assert_mac_measured_nothing
}

# =============================================================================
# STG1.3 — CI skips a tag the registry already holds
# =============================================================================
#
# THE STEP BODY IS EXTRACTED FROM `.github/workflows/ci.yml` AND RUN, rather
# than described: a workflow step is the one piece of shell in this repository
# that nothing else ever executes, and "the YAML contains a step that looks
# right" is precisely the claim that was true of the push role for the month it
# was broken. The body is written to use only environment variables, which is
# what makes it extractable at all — every `${{ }}` lives in the step's `env:`.
CI_YML=".github/workflows/ci.yml"
CI_SKIP_STEP="is this tag already in the registry"

# ci_step_body <step name> — the dedented `run:` block of that step.
ci_step_body() {
    awk -v want="      - name: $1" '
        $0 == want { instep = 1; next }
        instep && /^      - / { exit }
        instep && /^        run: \|/ { inrun = 1; next }
        inrun && /^        [^ ]/ { exit }
        inrun { sub(/^          /, ""); print }
    ' "$ROOT/$CI_YML"
}

# ci_world <web answer> <worker answer> — a scratch checkout carrying nothing
# but a `deploy/provision.sh` that answers `image-digest` with the planted exit
# status, which is the ONE thing the step reads the registry through.
ci_world() {
    local dir="$W/ci" rcweb="$1" rcworker="$2"
    rm -rf "$dir"
    mkdir -p "$dir/deploy"
    {
        echo '#!/usr/bin/env bash'
        echo "printf '%s\\n' \"\$*\" >>\"${dir}/provision.calls\""
        echo 'case "${2:-}" in'
        echo "web)    rc=${rcweb};    dg=sha256:0aa1 ;;"
        echo "worker) rc=${rcworker}; dg=sha256:0bb2 ;;"
        echo '*)'
        echo '    echo "stub provision: no such service" >&2'
        echo '    exit 2'
        echo '    ;;'
        echo 'esac'
        # THE DIGEST ITSELF, on the exit-0 path: the step echoes what it read,
        # and a stub that printed nothing would make the notice unfalsifiable.
        echo '[ "$rc" = "0" ] || exit "$rc"'
        echo 'printf "%s\n" "$dg"'
    } >"$dir/deploy/provision.sh"
    chmod +x "$dir/deploy/provision.sh"
    printf '%s\n' "$dir"
}

# ci_run <dir> — the body, in that world, with the step's own environment.
ci_run() {
    local dir="$1"
    DRIVE_OUT="$dir/out"
    : >"$dir/github_output"
    set +e
    (
        cd "$dir" &&
            TAG=tree-0123456789ab \
                REGISTRY=000000000000.dkr.ecr.us-east-1.amazonaws.com/drivens \
                PUSH=true \
                GITHUB_OUTPUT="$dir/github_output" \
                bash "$dir/body.sh"
    ) >"$DRIVE_OUT" 2>&1
    DRIVE_EXIT=$?
    set -e
}

case_ci_skips_a_present_tag_and_builds_an_absent_one() {
    CURRENT=case_ci_skips_a_present_tag_and_builds_an_absent_one
    local dir body
    fresh_world ci_skip
    body="$(ci_step_body "$CI_SKIP_STEP")"
    if [ -z "$body" ]; then
        bad "there is no '${CI_SKIP_STEP}' step with a run: block in ${CI_YML} — nothing to run"
        return
    fi

    # (a) BOTH SERVICES PRESENT → skipped, with the notice a reader sees in the
    #     job's log, and no build.
    dir="$(ci_world 0 0)"
    printf '%s\n' "$body" >"$dir/body.sh"
    ci_run "$dir"
    exited 0
    says "::notice::tree-0123456789ab already in the registry — skipped"
    if grep -qx 'have=true' "$dir/github_output"; then
        ok "the step's output says the registry has it"
    else
        bad "the step wrote '$(tr '\n' ' ' <"$dir/github_output")' and not have=true"
    fi

    # (b) ONE SERVICE MISSING → built. Both are rebuilt, because one image per
    #     service per tree is the unit, and a half-present tag is not a tag.
    dir="$(ci_world 0 2)"
    printf '%s\n' "$body" >"$dir/body.sh"
    ci_run "$dir"
    exited 0
    says_not "already in the registry"
    says "worker is NOT in the registry"
    if grep -qx 'have=false' "$dir/github_output"; then
        ok "a half-present tag is not a tag: the job builds"
    else
        bad "the step wrote '$(tr '\n' ' ' <"$dir/github_output")' and not have=false"
    fi

    # (c) AND THE BUILD STEP ACTUALLY CONSUMES IT. The body decides; the `if:`
    #     is what makes the decision skip a build, and a body whose answer
    #     nothing reads is the same as no body at all.
    if awk '
        /^      - name: build web and worker/ { instep = 1 }
        instep && /^        if: / { print; exit }
    ' "$ROOT/$CI_YML" | grep -F "steps.have.outputs.have != 'true'" >/dev/null; then
        ok "the buildx step is conditioned on the registry answer"
    else
        bad "the buildx step in ${CI_YML} does not read steps.have.outputs.have"
    fi
}

# --- run ----------------------------------------------------------------------

derive_the_plan_from_the_real_listing
case_on_boxes_without_bank_is_refused
case_on_boxes_below_the_syntactic_floor_is_refused
case_the_composed_row_keys_on_the_post_fold_tree
case_the_mac_holds_no_lease_and_runs_no_gate
case_the_plan_follows_the_listing
case_a_product_leg_in_the_drawer_gets_its_own_unit_and_its_own_box
case_a_broken_listing_is_exit_2_before_any_box
case_one_more_box_goes_to_the_last_shardable_unit
case_the_plan_spreads_shards_across_the_zones_the_wrapper_lists
case_no_zones_is_exit_2_before_any_box
case_bank_boxes_carry_a_one_hour_lifetime_and_a_thirty_minute_idle
case_every_shard_gets_its_own_box_and_the_seams_argv
case_a_detach_that_ssh_refused_is_retried_once
case_a_detach_that_failed_for_anything_else_is_not_retried
case_a_green_bank_brings_the_shards_drive_rows_home
case_drive_rows_already_home_are_not_appended_twice
case_a_red_bank_harvests_nothing
case_the_shard_table_names_the_market_each_box_is_on
case_one_red_shard_is_exit_1_and_no_row
case_a_missing_or_exit_2_shard_is_exit_2
case_a_finished_shards_log_is_fetched_before_the_slowest_shard_returns
case_a_reclaimed_shard_is_retried_once_on_a_fresh_box_in_the_next_zone
case_a_shard_reclaimed_twice_is_lost_never_red
case_a_retry_box_that_will_not_come_up_is_lost
case_a_reclaimed_acceptance_box_is_retried_once
case_a_foreign_tree_on_a_box_is_exit_2_naming_both
case_legs_that_do_not_add_up_are_exit_2_naming_the_leg
case_the_composed_row_has_the_grammar_and_one_writer
case_the_hook_honours_a_composed_row
case_a_short_legs_field_is_not_honoured
case_every_launched_box_is_taken_down_on_green_red_and_kill
case_a_box_whose_up_failed_after_the_launch_is_still_taken_down
case_a_failed_down_names_the_hand_and_keeps_the_status
case_the_acceptance_box_is_outside_the_verdict
case_the_plan_hands_passes_1_only_when_a_proof_box_exists
case_the_acceptance_command_mints_one_seed_and_writes_a_proof
case_the_leak_proof_is_composed_and_the_map_is_not
case_a_red_leak_proof_names_the_first_failing_test_and_the_replay
case_a_red_shard_names_its_first_failing_test
case_a_red_log_with_no_failed_line_says_none_named
case_the_composed_row_carries_the_proof_and_the_hook_reads_it
case_the_bank_reads_the_real_checkout_path_out_of_bake_sh
case_the_map_lands_in_the_tree_uncommitted
case_the_acceptance_map_never_dirties_the_box
case_a_docs_only_delta_runs_the_readers_and_banks_without_a_box
case_the_hook_honours_the_docs_only_row_and_measures_nothing
case_one_path_off_the_declared_list_and_the_arm_runs_as_it_always_did
case_a_red_reader_is_a_red_tree_and_a_reader_that_could_not_look_is_a_full_bank
case_a_source_row_that_is_not_honoured_is_a_full_bank_with_the_lookups_note
case_a_dirty_tree_refuses_before_the_road_and_the_measuring_valve_skips_it
case_the_image_is_built_after_the_row_and_never_on_a_red
case_a_red_bank_builds_no_image
case_a_lying_tag_builds_nothing_and_the_bank_stands
case_a_failed_push_is_printed_and_the_row_still_stands
case_no_registry_coordinate_is_printed_and_nothing_is_built
case_ci_skips_a_present_tag_and_builds_an_absent_one

# >>> summary: passed and failed, separately >>>
echo ""
echo "test_pm_push: ${PASSED} passed, ${FAILED} failed"
# Section 5 of the preamble: say that the run REACHED here, so a `set -u` death
# that bash hands the EXIT trap as a 0 reads as could-not-look instead.
drive_finished
[ "$FAILED" -eq 0 ] || exit 1
exit 0
