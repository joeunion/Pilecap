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

fresh_world() {
    N=$((N + 1))
    W="${WORK}/w${N}-$1"
    REPO="${W}/repo"
    REC="${W}/rec"
    LEDGER="${W}/verdicts"
    RUNNER="${W}/run-bank.sh"
    drive_require_scratch W "${W:-}"
    drive_require_scratch REPO "${REPO:-}"
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
        echo "FULL_LEGS=${REAL_FULL_LEGS}"
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
        >"$REPO/scripts/verifier_box.sh" <<'STUB'
#!/usr/bin/env bash
# A STUB. It records every argv and answers from per-case fixtures. It makes no
# AWS call, launches nothing, terminates nothing and touches no real box.
set -uo pipefail
REC="__REC__"
REPO="__REPO__"
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
    while [ "$#" -gt 0 ]; do
        case "$1" in
        --for)
            rung="${2:-}"
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
    printf '%s\t%s\n' "$label" "$rung" >>"$REC/up.calls"
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
    if [ -f "$REC/up.rc.${label}" ]; then
        echo "stub up: ${label} refused by fixture" >&2
        exit "$(cat "$REC/up.rc.${label}")"
    fi
    id="i-$(printf '%s' "$label" | cksum | awk '{printf "%010d", $1}')"
    printf '%s\n' "$label" >"$REC/label-of.${id}"
    echo "instance   ${id}   c7g.4xlarge   market: spot   az xx-drive-9a"
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
wait)
    id="${1:-}"
    name="${2:-}"
    printf '%s\t%s\n' "$id" "$name" >>"$REC/wait.calls"
    lbl="$(cat "$REC/label-of.${id}" 2>/dev/null || echo unknown)"
    [ ! -f "$REC/wait.out.${lbl}" ] || cat "$REC/wait.out.${lbl}"
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
        cat "$REC/box.rc.${lbl}" 2>/dev/null >"$dest" || printf '0\n' >"$dest"
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
                legs="${legs/,pytest-x2,/,pytest-x2/1,}"
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

case_on_boxes_without_bank_is_refused() {
    CURRENT=case_on_boxes_without_bank_is_refused
    fresh_world on_boxes_without_bank

    run_bank --on-boxes 8
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

case_on_boxes_below_five_is_refused() {
    CURRENT=case_on_boxes_below_five_is_refused
    fresh_world on_boxes_below_five

    run_bank --bank --on-boxes 4
    exited 2
    says "is below the floor of 5"
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

    run_bank --bank --on-boxes 8
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

    run_bank --bank --no-fold --on-boxes 8
    exited 0
    listed="$(grep -c -- '--list-legs' "${REC}/gate.calls" 2>/dev/null || true)"
    holds "gate invocations, all of them --list-legs" "1" "${listed:-0}"
    says "This Mac MEASURES NOTHING"
    assert_mac_measured_nothing

    # AND ON A RED RUN TOO, which is the half a green-only assertion misses.
    fresh_world mac_no_lease_red
    printf '1\n' >"${REC}/box.rc.static"
    run_bank --bank --no-fold --on-boxes 8
    exited 1
    assert_mac_measured_nothing
}

# =============================================================================
# S.4 — the plan is derived, never typed
# =============================================================================

case_the_plan_follows_the_listing() {
    CURRENT=case_the_plan_follows_the_listing
    local extra_legs selftest_shards

    # (a) A LISTING WITH ONE MORE INDIVISIBLE UNIT. The plan gains a box for it
    # and the last shardable unit loses one — with no edit to pm_push.sh.
    fresh_world plan_extra_unit
    printf 'extra-unit\tnone\t0\textra-leg\n' >>"${REC}/listlegs.out"
    run_bank --bank --no-fold --on-boxes 8
    exited 0
    if grep -q -- '--unit extra-unit --log leg' "${REC}/leg.calls"; then
        ok "the new indivisible unit got its own box, unsharded"
    else
        DRIVE_OUT="${REC}/leg.calls"
        bad "the plan did not give extra-unit a box of its own"
    fi
    selftest_shards="$(grep -c -- '--unit selftest ' "${REC}/leg.calls" || true)"
    holds "selftest shards at N=8 with four indivisible units" "2" "${selftest_shards:-0}"
    holds "boxes (the plan's eight, and the acceptance box)" "9" "$(count_lines "${REC}/up.calls")"

    # (b) A LISTING WHERE `selftest` IS INDIVISIBLE. The split drops; nothing
    # in pm_push.sh knows the word `selftest`.
    fresh_world plan_selftest_flat
    awk -F'\t' 'BEGIN { OFS = "\t" } $1 == "selftest" { $3 = "0" } { print }' \
        "$REAL_LISTING" >"${REC}/listlegs.out"
    run_bank --bank --no-fold --on-boxes 8
    exited 0
    if grep -q -- '--unit selftest --log leg' "${REC}/leg.calls"; then
        ok "selftest took one whole box with no --shard"
    else
        DRIVE_OUT="${REC}/leg.calls"
        bad "selftest was still split after the listing called it indivisible"
    fi
    extra_legs="$(grep -c -- '--unit pytest-x2 --shard' "${REC}/leg.calls" || true)"
    holds "pytest-x2 shards when selftest is indivisible" "4" "${extra_legs:-0}"
    assert_mac_measured_nothing

    # (c) AND THE FLOOR IS DERIVED TOO. Five is the floor of TODAY's five units
    # and it is checked at the argument for a typo's sake; the floor that stays
    # right when a unit is ADDED comes out of the listing, and it refuses with
    # the arithmetic rather than with a constant.
    fresh_world plan_derived_floor
    printf 'extra-unit\tnone\t0\textra-leg\n' >>"${REC}/listlegs.out"
    run_bank --bank --no-fold --on-boxes 5
    exited 2
    says "this gate declares 6 units"
    says "cannot give every one of them a box"
    says "never typed"
    holds "up calls under the derived floor" "0" "$(count_lines "${REC}/up.calls")"
    holds "verdict rows under the derived floor" "0" "$(ledger_rows)"

    # (d) AT THE FLOOR ITSELF, every shardable unit still carries a k. `1/1` is
    # a part of a whole and the gate takes one; a shardable unit handed NO k
    # would be a unit the composition could not account for, which is its own
    # exit 2 one function over.
    fresh_world plan_at_the_floor
    run_bank --bank --no-fold --on-boxes 5
    exited 0
    for want in "--unit pytest-x2 --shard 1/1 --passes 1 --log leg" "--unit selftest --shard 1/1 --log leg"; do
        if grep -qF -- "$want" "${REC}/leg.calls"; then
            ok "at the floor: leg <id> ${want}"
        else
            DRIVE_OUT="${REC}/leg.calls"
            bad "at the floor, no shard was handed: ${want}"
        fi
    done
    holds "boxes at the floor (five shards and the acceptance box)" "6" "$(count_lines "${REC}/up.calls")"
    holds "one verdict row at the floor" "1" "$(ledger_rows)"
}

case_a_broken_listing_is_exit_2_before_any_box() {
    CURRENT=case_a_broken_listing_is_exit_2_before_any_box
    fresh_world broken_listing
    printf '2\n' >"${REC}/listlegs.rc"
    printf '!! --list-legs: a leg is in NO unit.\n' >"${REC}/listlegs.err"

    run_bank --bank --no-fold --on-boxes 8
    exited 2
    says "--list-legs exited 2"
    says "a leg is in NO unit"
    holds "up calls" "0" "$(count_lines "${REC}/up.calls")"
    holds "verdict rows" "0" "$(ledger_rows)"
    assert_mac_measured_nothing
}

# =============================================================================
# S.5 — N boxes, one leg per box, the seam's exact argv
# =============================================================================

case_eight_boxes_get_eight_shards() {
    CURRENT=case_eight_boxes_get_eight_shards
    fresh_world eight_shards
    local tree8 ids uniq want

    run_bank --bank --no-fold --on-boxes 8
    exited 0
    # NINE BOXES FOR EIGHT SHARDS. The ninth is the `acceptance` box and it is
    # outside the plan by construction: it takes no unit, it is handed no leg,
    # and its answer enters no part of the composed verdict. The plan is still
    # the eight the listing declares.
    holds "up calls" "9" "$(count_lines "${REC}/up.calls")"
    holds "leg calls" "8" "$(count_lines "${REC}/leg.calls")"
    holds "wait calls" "8" "$(count_lines "${REC}/wait.calls")"
    # TWO `run`s AND NOT ONE, and the second is the image: the acceptance
    # measurement in phase 3, and ONE build after the row is written. Both are
    # on the same verb and neither is a unit of the gate. A third would be a
    # second image of one tree, which is the shape the criteria rejected.
    holds "run calls (the acceptance measurement, and one image build)" "2" "$(count_lines "${REC}/run.calls")"
    holds "image builds (one, whatever the box count)" "1" "$(count_lines "${REC}/image.calls")"
    holds "fetch calls (a log and a status per shard, plus the map and the leak proof)" \
        "18" "$(count_lines "${REC}/fetch.calls")"

    tree8="$(repo_tree)"
    tree8="${tree8:0:8}"
    DRIVE_OUT="${REC}/up.calls"
    for want in "bank-${tree8}-static" "bank-${tree8}-supply-chain" \
        "bank-${tree8}-full-house-rules" "bank-${tree8}-pytest-x2-1of2" \
        "bank-${tree8}-pytest-x2-2of2" "bank-${tree8}-selftest-1of3" \
        "bank-${tree8}-selftest-2of3" "bank-${tree8}-selftest-3of3"; do
        if grep -qF "$want" "${REC}/up.calls"; then
            ok "up --for ${want}"
        else
            bad "no box was brought up for ${want}"
        fi
    done

    DRIVE_OUT="${REC}/leg.calls"
    for want in "--unit static --log leg" "--unit supply-chain --log leg" \
        "--unit full-house-rules --log leg" \
        "--unit pytest-x2 --shard 1/2 --passes 1 --log leg" \
        "--unit pytest-x2 --shard 2/2 --passes 1 --log leg" \
        "--unit selftest --shard 1/3 --log leg" \
        "--unit selftest --shard 2/3 --log leg" \
        "--unit selftest --shard 3/3 --log leg"; do
        if grep -qF -- "$want" "${REC}/leg.calls"; then
            ok "leg <id> ${want}"
        else
            bad "no shard was handed: ${want}"
        fi
    done

    ids="$(field_lines "${REC}/leg.calls" 1 | LC_ALL=C sort || true)"
    uniq="$(printf '%s\n' "$ids" | LC_ALL=C sort -u)"
    holds "each box id handed exactly one leg" "$uniq" "$ids"
    DRIVE_OUT="${W}/run-__bank___no_fold___on_boxes_8.log"
    assert_mac_measured_nothing
}

# =============================================================================
# S.5b — a detach that ssh refused is the transport, and it gets one more go
# =============================================================================

# WHY 255 IS ITS OWN CASE. `up` returns when SSM says the agent is Online, and
# the agent answers before the SSH tunnel does: a `leg` detached in that window
# gets ssh's own exit 255 with an EMPTY log — no gate ran, nothing was
# measured, and the bank refused a whole wave for a socket that was answering a
# few seconds later. A measured bank came down that way with all five of its
# boxes up and paid for.
#
# ONE RETRY, AND ONLY FOR 255. Anything else is the wrapper or the box saying
# something real, and a retry there would be a second copy of a leg that may
# already be running.
case_a_detach_that_ssh_refused_is_retried_once() {
    CURRENT=case_a_detach_that_ssh_refused_is_retried_once
    fresh_world detach_255
    printf '255\n' >"${REC}/leg.rc.selftest-2of3.1"

    run_bank --bank --no-fold --on-boxes 8
    exited 0
    # Nine detaches for eight shards: the one that met the closed tunnel went
    # twice.
    holds "leg calls (eight shards, one retried)" "9" "$(count_lines "${REC}/leg.calls")"
    says "exited 255"
    says "selftest-2of3"
    says "retrying the detach"
    holds "ledger rows" "1" "$(ledger_rows)"
    assert_mac_measured_nothing
}

case_a_detach_that_failed_for_anything_else_is_not_retried() {
    CURRENT=case_a_detach_that_failed_for_anything_else_is_not_retried
    fresh_world detach_not_transport
    printf '2\n' >"${REC}/leg.rc.selftest-2of3"

    run_bank --bank --no-fold --on-boxes 8
    exited 2
    holds "leg calls (no retry for a non-transport failure)" "8" "$(count_lines "${REC}/leg.calls")"
    says "a unit could not be detached: selftest-2of3"
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
    boxledger_rows selftest-2of3 "$t"

    run_bank --bank --no-fold --on-boxes 8
    exited 0
    holds "harvest-drives calls (one per shard box, and none for the acceptance box)" \
        "8" "$(count_lines "${REC}/harvest.calls")"
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
    boxledger_rows selftest-2of3 "$t"
    # ALREADY HERE, exactly as a second bank of the same tree would find them.
    cat "${REC}/boxledger.selftest-2of3" >>"$LEDGER"

    run_bank --bank --no-fold --on-boxes 8
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
    boxledger_rows selftest-2of3 "$t"
    printf '1\n' >"${REC}/box.rc.selftest-2of3"

    run_bank --bank --no-fold --on-boxes 8
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

    run_bank --bank --no-fold --on-boxes 8
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
    if grep -E '^  supply-chain .*spot' "$DRIVE_OUT" >/dev/null 2>&1; then
        ok "and a Spot shard's row says spot"
    else
        bad "the table's supply-chain row does not carry its market: $(grep -E '^  supply-chain' "$DRIVE_OUT" || true)"
    fi
    assert_mac_measured_nothing
}

# =============================================================================
# S.6 — refuse unless every shard is green and the legs add up
# =============================================================================

case_one_red_shard_is_exit_1_and_no_row() {
    CURRENT=case_one_red_shard_is_exit_1_and_no_row
    fresh_world one_red_shard
    printf '1\n' >"${REC}/box.rc.selftest-2of3"

    run_bank --bank --no-fold --on-boxes 8
    exited 1
    says "the gate is RED"
    says "selftest-2of3"
    says "--leg selftest --shard 2/3"
    holds "verdict rows" "0" "$(ledger_rows)"
    # THE TABLE PRINTS ON EVERY EXIT PATH — a composition that refused and said
    # only "a shard was red" is a composition nobody can act on.
    says "shard"
    says "pytest-x2-1of2"
    assert_mac_measured_nothing
}

case_a_missing_or_exit_2_shard_is_exit_2() {
    CURRENT=case_a_missing_or_exit_2_shard_is_exit_2
    # (a) a shard that exited 2 — enforcement broken over there
    fresh_world shard_exit_2
    printf '2\n' >"${REC}/box.rc.static"
    run_bank --bank --no-fold --on-boxes 8
    exited 2
    says "the shard exited 2"
    says "static"
    holds "verdict rows" "0" "$(ledger_rows)"
    assert_mac_measured_nothing

    # (b) a shard whose .rc never came back
    fresh_world shard_no_rc
    : >"${REC}/norc.supply-chain"
    run_bank --bank --no-fold --on-boxes 8
    exited 2
    says "no exit status came back from the box"
    holds "verdict rows with no status" "0" "$(ledger_rows)"

    # (c) a shard whose whole fixture is gone — nothing fetched at all
    fresh_world shard_absent
    : >"${REC}/absent.selftest-1of3"
    run_bank --bank --no-fold --on-boxes 8
    exited 2
    says "no log came back from the box"
    holds "verdict rows with no log" "0" "$(ledger_rows)"
    assert_mac_measured_nothing
}

case_a_reclaimed_box_is_exit_2_never_red() {
    CURRENT=case_a_reclaimed_box_is_exit_2_never_red
    fresh_world reclaimed
    # `wait` says the words the wrapper says, and the shard's own status is the
    # 2 a reclaimed box's `wait` passes through.
    printf 'box reclaimed (spot) i-000\n' >"${REC}/wait.out.pytest-x2-2of2"
    printf '2\n' >"${REC}/box.rc.pytest-x2-2of2"

    run_bank --bank --no-fold --on-boxes 8
    exited 2
    says "RECLAIMED mid-flight"
    says "the verdict is LOST, never red"
    says_not "the gate is RED"
    holds "verdict rows" "0" "$(ledger_rows)"
    assert_mac_measured_nothing
}

case_a_foreign_tree_on_a_box_is_exit_2_naming_both() {
    CURRENT=case_a_foreign_tree_on_a_box_is_exit_2_naming_both
    fresh_world foreign_tree
    local mine foreign
    foreign="dead0000dead0000dead0000dead0000dead0000"
    printf '%s\n' "$foreign" >"${REC}/box.tree.selftest-3of3"

    run_bank --bank --no-fold --on-boxes 8
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
    full=",$(awk -F'\t' '$1 == "pytest-x2" { print $4 }' "$REAL_LISTING"),"
    full="${full//,own-tree-census,/,}"
    full="${full//,pytest-x2,/,pytest-x2/1,}"
    full="${full#,}"
    full="${full%,}"
    printf '%s\n' "$full" >"${REC}/box.legs.pytest-x2-1of2"
    printf '%s\n' "$full" >"${REC}/box.legs.pytest-x2-2of2"

    run_bank --bank --no-fold --on-boxes 8
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
    printf '90\n' >"${REC}/box.wall.pytest-x2-1of2"
    printf '140\n' >"${REC}/box.wall.pytest-x2-2of2"
    printf '900\n' >"${REC}/box.wall.selftest-1of3"

    run_bank --bank --no-fold --on-boxes 8
    exited 0
    holds "exactly one line appended" "1" "$(ledger_rows)"
    row="$(cat "$LEDGER")"
    tree="$(repo_tree)"
    DRIVE_OUT="$LEDGER"

    if printf '%s\n' "$row" | grep -E \
        "^v1 [0-9a-f]{40} full [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z [a-z0-9,/_-]+ caller=pm-bank sanction=push-wall boxes=8 shards=[A-Za-z0-9,._-]+ waited=0 took=[0-9]+ leak-proof=acceptance:i-[0-9a-f]+ rc=0\$" >/dev/null; then
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
    onepass_legs="${onepass_legs//,pytest-x2,/,pytest-x2/1,}"
    onepass_legs="${onepass_legs#,}"
    onepass_legs="${onepass_legs%,}"
    holds "the row's leg field names the suite leg's ONE pass" "$onepass_legs" \
        "$(printf '%s\n' "$row" | awk '{print $5}')"
    # BY NAME AND NOT BY POSITION: the proof is appended AFTER `took=`, so a
    # positional read here would be asserting where the field sits rather than
    # what it says, and would move every time the grammar gains one.
    holds "took= is the slowest pytest shard, not the slowest shard" "took=140" \
        "$(printf '%s\n' "$row" | awk '{ for (i = 1; i <= NF; i++) if ($i ~ /^took=/) print $i }')"
    DRIVE_OUT="${W}/run-__bank___no_fold___on_boxes_8.log"
    if grep -qE '^  pytest-x2-2of2 +i-[0-9]+ +(spot|on-demand|-) +1 +0 +140s +[0-9a-f]{40}$' "$DRIVE_OUT"; then
        ok "the per-shard table carries that shard's own market, passes, wall, box, rc and tree"
    else
        bad "the per-shard table does not carry pytest-x2-2of2's own row"
    fi
    if grep -qE '^  static +i-[0-9]+ +(spot|on-demand|-) +- +0 ' "$DRIVE_OUT"; then
        ok "a unit that runs no suite carries a dash in the passes column, never a 2"
    else
        bad "the table's static row guesses a pass count: $(grep -E '^  static' "$DRIVE_OUT" || true)"
    fi
    if printf '%s\n' "$row" | grep -F "shards=static,supply-chain,full-house-rules,pytest-x2-1of2,pytest-x2-2of2,selftest-1of3,selftest-2of3,selftest-3of3" >/dev/null; then
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

    run_bank --bank --no-fold --on-boxes 8
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

    run_bank --bank --no-fold --on-boxes 8
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
    run_bank --bank --no-fold --on-boxes 8
    exited 0
    holds "downs on a green bank (eight shards and the acceptance box)" "9" \
        "$(count_lines "${REC}/down.calls")"
    downs="$(sorted_lines "${REC}/down.calls")"
    uniq="$(printf '%s\n' "$downs" | LC_ALL=C sort -u)"
    holds "each box taken down exactly once" "$uniq" "$downs"

    # (b) RED.
    fresh_world down_on_red
    printf '1\n' >"${REC}/box.rc.static"
    run_bank --bank --no-fold --on-boxes 8
    exited 1
    holds "downs on a red bank" "9" "$(count_lines "${REC}/down.calls")"

    # (c) A SIGNAL AFTER THREE BOXES ARE UP. The other five `up`s are still in
    # flight; the trap takes down the three it can name and says so.
    fresh_world down_on_kill
    printf 'static\nsupply-chain\nfull-house-rules\n' >"${REC}/up.allow"
    DRIVE_OUT="${W}/run-kill.log"
    set +e
    "$RUNNER" --bank --no-fold --on-boxes 8 >"$DRIVE_OUT" 2>&1 &
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

case_a_failed_down_names_the_hand_and_keeps_the_status() {
    CURRENT=case_a_failed_down_names_the_hand_and_keeps_the_status

    # (a) A GREEN BANK WHOSE BOXES WOULD NOT GO DOWN. The row IS banked — it is
    # honest — and the status becomes 2, because a clean exit over a machine
    # still billing must not read as success.
    fresh_world failed_down_green
    : >"${REC}/down.fail"
    run_bank --bank --no-fold --on-boxes 8
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
    printf '1\n' >"${REC}/box.rc.selftest-1of3"
    run_bank --bank --no-fold --on-boxes 8
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
    run_bank --bank --no-fold --on-boxes 8
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
    run_bank --bank --no-fold --on-boxes 8
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
    run_bank --bank --no-fold --on-boxes 8
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
    run_bank --bank --no-fold --on-boxes 8
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
    run_bank --bank --no-fold --on-boxes 8
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
    run_bank --bank --no-fold --on-boxes 8
    exited 0
    suite_shards="$(grep -c -- '--unit pytest-x2 --shard [0-9]*/[0-9]* --passes 1 --log leg' \
        "${REC}/leg.calls" || true)"
    holds "suite shards handed --passes 1" "2" "${suite_shards:-0}"
    plain_shards="$(grep -c -- '--passes' "${REC}/leg.calls" || true)"
    holds "shards handed --passes at all (the suite's two, and nothing else)" "2" "${plain_shards:-0}"
    DRIVE_OUT="${W}/run-__bank___no_fold___on_boxes_8.log"
    says "--leg pytest-x2 --shard 1/2 --passes 1"
    says "ONE pass per suite shard"
    # AND THE UNIT THAT RUNS NO SUITE IS NOT HANDED ONE. `selftest` shards the
    # same way and has no pass to drop; the plan reads WHICH unit carries the
    # suite leg out of the listing's own legs column.
    says_not "--leg selftest --shard 1/3 --passes"
    assert_mac_measured_nothing

    # (b) THE PLAN READS THE LISTING AND NOT A NAME. Move the suite leg onto
    # another unit in the listing and the `--passes 1` moves with it, with no
    # edit to pm_push.sh.
    fresh_world passes_follow_the_listing
    awk -F'\t' 'BEGIN { OFS = "\t" }
        $1 == "pytest-x2" { $4 = "temporal-census,partition,own-tree-census" }
        $1 == "selftest"  { $4 = $4 ",pytest-x2" }
        { print }' "$REAL_LISTING" >"${REC}/listlegs.out"
    run_bank --bank --no-fold --on-boxes 8
    DRIVE_OUT="${REC}/leg.calls"
    if grep -q -- '--unit selftest --shard [0-9]*/[0-9]* --passes 1 --log leg' "${REC}/leg.calls"; then
        ok "the pass count followed the suite leg to the unit the listing puts it in"
    else
        bad "the plan handed --passes 1 by unit name and not by the listing's legs"
    fi
    says_not "--unit pytest-x2 --shard 1/2 --passes 1"

    # (c) NO PROOF BOX, NO ONE-PASS SHARD. The world with no `bake.sh` is the
    # one state in which there can be no acceptance box at all, and every
    # pytest shard then runs the two passes it always did.
    fresh_world passes_without_proof_box
    git -C "$REPO" rm -q deploy/verifier/bake.sh
    git -C "$REPO" commit -q -m "a checkout with no bake.sh to read"
    run_bank --bank --no-fold --on-boxes 8
    exited 0
    holds "shards handed --passes with no proof box" "0" \
        "$(grep -c -- '--passes' "${REC}/leg.calls" || true)"
    holds "verdict rows" "1" "$(ledger_rows)"

    # (d) A SHARD THAT DISAGREES WITH ITS OWN PLAN LINE IS EXIT 2 AND NO ROW.
    # The plan handed one pass; this shard's banner says it ran the default
    # two. One of the two is wrong about what was measured and neither the
    # bank nor a reader afterwards can tell which, so nothing is banked.
    fresh_world passes_shard_disagrees
    awk -F'\t' '$1 == "pytest-x2" { print $4 }' "$REAL_LISTING" \
        >"${REC}/box.legs.pytest-x2-2of2"
    run_bank --bank --no-fold --on-boxes 8
    exited 2
    says "the plan and the unit listing disagree"
    says "pytest-x2: planned --passes 1 and the shard reports pytest-x2"
    holds "verdict rows" "0" "$(ledger_rows)"
    assert_mac_measured_nothing
}

case_the_acceptance_command_mints_one_seed_and_writes_a_proof() {
    CURRENT=case_the_acceptance_command_mints_one_seed_and_writes_a_proof
    local cmd seeds

    fresh_world acceptance_proof_argv
    run_bank --bank --no-fold --on-boxes 8
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
    run_bank --bank --no-fold --on-boxes 8
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
    run_bank --bank --no-fold --on-boxes 8
    exited 1
    holds "verdict rows" "0" "$(ledger_rows)"
    says "the leak proof is RED"

    # (b) A PROOF THAT NEVER CAME BACK IS COULD-NOT-LOOK, WHICH OUTRANKS EVERY
    # SHARD'S PASS. One pass was measured and nothing says what it left behind.
    fresh_world proof_absent
    : >"${REC}/accept.proof.absent"
    run_bank --bank --no-fold --on-boxes 8
    exited 2
    holds "verdict rows" "0" "$(ledger_rows)"
    says "the leak proof could not be read — one pass was measured and nothing proved it left nothing behind"
    says "fetch-proof.log"
    assert_mac_measured_nothing

    # (b2) AND SO IS ONE NOBODY CAN PARSE. A proof with no seed is two runs of
    # the suite and not a pair, whatever its statuses say.
    fresh_world proof_unparsable
    printf 'workers=16 pass1=0 pass2=0 map=0\n' >"${REC}/accept.proof"
    run_bank --bank --no-fold --on-boxes 8
    exited 2
    holds "verdict rows" "0" "$(ledger_rows)"
    says "the leak proof could not be read — one pass was measured and nothing proved it left nothing behind"

    # (b3) AND AN rc THAT IS NOT A DECIMAL IS NEITHER GREEN NOR RED. A reader
    # that took it as green would bank the strongest claim over the least
    # readable evidence.
    fresh_world proof_rc_not_a_number
    printf 'seed=8675309 workers=16 pass1=0 pass2=ok map=0\n' >"${REC}/accept.proof"
    run_bank --bank --no-fold --on-boxes 8
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
    run_bank --bank --no-fold --on-boxes 8
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
    run_bank --bank --no-fold --on-boxes 8
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

case_the_composed_row_carries_the_proof_and_the_hook_reads_it() {
    CURRENT=case_the_composed_row_carries_the_proof_and_the_hook_reads_it
    local row tree looked red_row aid f

    fresh_world row_leak_proof
    run_bank --bank --no-fold --on-boxes 8
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
    run_bank --bank --no-fold --on-boxes 8
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
    run_bank --bank --no-fold --on-boxes 8
    exited 2
    says "has uncommitted changes"
    says "scripts/test_impact.json"
    holds "verdict rows after the refusal" "1" "$(ledger_rows)"
    holds "the map in the tree, untouched by the refusal" "tree:beefcafe1234" "$(accept_mapq tree)"
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

    run_bank --bank --no-fold --on-boxes 8
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

    run_bank --bank --no-fold --on-boxes 8
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
    printf '1\n' >"${REC}/box.rc.selftest-2of3"

    run_bank --bank --no-fold --on-boxes 8
    exited 1
    # THE POSITIVE ANCHOR FIRST. Every other assertion here is an absence, and
    # a case made only of absences passes just as well when the bank refused
    # for some entirely different reason — or never ran at all. This line is
    # the composition saying WHY there is no image: the gate was red.
    says "the gate is RED. NO ROW WAS WRITTEN"
    says "selftest-2of3"
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

    run_bank --bank --no-fold --on-boxes 8
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

    run_bank --bank --no-fold --on-boxes 8
    exited 0
    holds "verdict rows" "1" "$(ledger_rows)"
    says "image: NOT built (exit 1)"
    says "ecr:InitiateLayerUpload"
    says "CI's images job builds a tag"
    # AND THE BOXES STILL GO DOWN AND THE PUSH STILL HAPPENS: a failed image is
    # not a reason to leave nine machines billing.
    holds "boxes taken down" "9" "$(count_lines "${REC}/down.calls")"
    assert_mac_measured_nothing
}

# NO REGISTRY COORDINATE IS NOT A FAILURE, it is a deployment that has not been
# given one — every clone of this template starts there. It is printed, nothing
# is asked of any box, and the bank is green.
case_no_registry_coordinate_is_printed_and_nothing_is_built() {
    CURRENT=case_no_registry_coordinate_is_printed_and_nothing_is_built
    fresh_world image_no_registry
    rm -f "${REC}/registry"

    run_bank --bank --no-fold --on-boxes 8
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

case_on_boxes_without_bank_is_refused
case_on_boxes_below_five_is_refused
case_the_composed_row_keys_on_the_post_fold_tree
case_the_mac_holds_no_lease_and_runs_no_gate
case_the_plan_follows_the_listing
case_a_broken_listing_is_exit_2_before_any_box
case_eight_boxes_get_eight_shards
case_a_detach_that_ssh_refused_is_retried_once
case_a_detach_that_failed_for_anything_else_is_not_retried
case_a_green_bank_brings_the_shards_drive_rows_home
case_drive_rows_already_home_are_not_appended_twice
case_a_red_bank_harvests_nothing
case_the_shard_table_names_the_market_each_box_is_on
case_one_red_shard_is_exit_1_and_no_row
case_a_missing_or_exit_2_shard_is_exit_2
case_a_reclaimed_box_is_exit_2_never_red
case_a_foreign_tree_on_a_box_is_exit_2_naming_both
case_legs_that_do_not_add_up_are_exit_2_naming_the_leg
case_the_composed_row_has_the_grammar_and_one_writer
case_the_hook_honours_a_composed_row
case_a_short_legs_field_is_not_honoured
case_every_launched_box_is_taken_down_on_green_red_and_kill
case_a_failed_down_names_the_hand_and_keeps_the_status
case_the_acceptance_box_is_outside_the_verdict
case_the_plan_hands_passes_1_only_when_a_proof_box_exists
case_the_acceptance_command_mints_one_seed_and_writes_a_proof
case_the_leak_proof_is_composed_and_the_map_is_not
case_the_composed_row_carries_the_proof_and_the_hook_reads_it
case_the_bank_reads_the_real_checkout_path_out_of_bake_sh
case_the_map_lands_in_the_tree_uncommitted
case_the_acceptance_map_never_dirties_the_box
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
