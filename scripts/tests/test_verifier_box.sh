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
# drives: .env.example README.md deploy/ scripts/check.sh scripts/gate_lease.sh scripts/gate_ledger.sh scripts/gate_refuse.sh scripts/githooks scripts/secrets_scan.sh scripts/setup.sh scripts/tests/test_loop_ledger.sh scripts/tests/test_verifier_image.sh scripts/verifier_box.sh scripts/verify_start.sh
# cites: scripts/pm_push.sh quality/rules.yaml
# THE VERIFIER BOX WRAPPER'S DRIVE — every refusal, every recorded argument, and
# every exit status the wrapper owns.
#
#   ./scripts/tests/test_verifier_box.sh          run every case
#   ./scripts/tests/test_verifier_box.sh --list   name them and stop
#
# WHY IT EXISTS. `scripts/verifier_box.sh` spends money and terminates machines.
# Every one of its failure modes is silent in the direction that costs: a
# refusal that launches first and refuses second, a ceiling that becomes
# on-demand money instead of a refusal, a `down` that reaches an instance
# nobody tagged as ours, a `loop` that pipes the gate and hands the ledger a
# lie, a `bake` that leaves its builder running. None of those reds anything by
# themselves — they just quietly work, wrongly.
#
# NOT ONE REAL AWS CALL, NOT ONE REAL BOX. `aws`, `ssh`, `scp`, `git`,
# `session-manager-plugin` and `sleep` are planted on PATH in a per-case scratch
# directory; `aws` answers from per-case fixtures and records EVERY invocation
# twice — once as `<service> <operation>` for counting, once as the whole
# command line for reading. `ssh-keygen` is the REAL one, because the key's mode
# is one of the things asserted and a shimmed keygen would prove the assertion
# against itself. `HOME` is a scratch directory whose `~/.aws/config` carries
# only a `[default]` in the WRONG region, which is what makes "the call carries
# --region explicitly" a real claim rather than a coincidence.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * EVERY ANSWER THE REAL API WOULD GIVE. The fixtures are this drive's
#     opinion of what EC2 and SSM return. A mis-spelled error code makes the
#     case that reads it vacuous; the codes here are the ones the EC2 API
#     reference lists, and the field test is the only run against the real one.
#   * THE TRANSPORT ITSELF. Whether `AWS-StartSSHSession` tunnels through this
#     account's Session Manager preferences, whether cloud-init honours the
#     authorized-key slot for a user it creates in the same run, whether
#     `PingStatus=Online` arrives inside the wait — all three are a real box's
#     answer and none of them is here.
#   * WHETHER THE LAUNCH FLAGS DO WHAT THEY SAY.
#     `--instance-initiated-shutdown-behavior terminate` is asserted as an
#     argument; whether a halt from inside then TERMINATES rather than stops is
#     AWS's behaviour, and the image's whole teardown rests on it.
#   * WALL CLOCK — REAL WALL CLOCK. There is a FAKE one: `sleep` advances it
#     instead of spending it, `ssh` charges it DRIVE_SSH_SECONDS to model a
#     tunnelled attempt to a box that is not answering, and `date +%s` reads
#     it, so a wait that COUNTS polls and a wait that MEASURES elapsed time are
#     told apart here — the defect that paid for the fixture was a refusal
#     that said 600s after waiting 900. What is still NOT proven is any real duration: not
#     whether a real SSH attempt costs the 5 s this fixture charges, and not
#     whether 600 s is enough for a real `dnf install` on a cold mirror. Both
#     are FIELD TEST 3's, and a poll that is much more expensive than the
#     fixture assumes would overrun the ceiling by more than this drive can
#     see.
#   * THE PRIMARY CHECKOUT'S OWN GIT. `git` is shimmed, so `push` is proven by
#     its recorded argv and its environment, never by a ref that moved. The
#     recorded `GIT_SSH_COMMAND` IS resolved here the way git resolves it —
#     `sh -c` splits it, `ssh -G` prints the configuration those words built —
#     so the shell hazard that cost FIELD TEST 1 is covered; the session that
#     configuration would open is still a real box's answer and is not.
set -euo pipefail

cd "$(dirname "$0")/../.."

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_verifier_box: scripts/tests/drive_preamble.sh is not in this tree." >&2
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
# A CLAIM WITH NO OWNER IN THIS TREE IS SKIPPED, PRINTED AND COUNTED — never a
# silent pass. The count is on the summary line and each reason is repeated
# under it, so a run that skipped is never read as a run that asserted (the
# `test_db_pin.sh` / `test_sweep.sh` form).
SKIPPED=0
SKIP_REASONS=""
skip() {
    echo "  SKIP     ${CURRENT} — $1"
    SKIPPED=$((SKIPPED + 1))
    SKIP_REASONS="${SKIP_REASONS}
     ${CURRENT} — $1"
}
cannot_look() {
    echo "!! test_verifier_box: $*" >&2
    echo "   Nothing was asserted. A driver that could not run its cases has not" >&2
    echo "   cleared them." >&2
    exit 2
}

# A file's permission bits, in octal, on both `stat`s — GNU coreutils on a
# runner and BSD on a laptop.
#
# TWO PROBES, ORDERED AND CAPTURED SEPARATELY, and both halves of that are the
# fix. The shape this replaces was one substitution around an `||` chain with
# the BSD form first:
#
#     mode="$(stat -f '%OLp' "$f" 2>/dev/null || stat -c '%a' "$f" 2>/dev/null || echo '?')"
#
# On GNU, `-f` is `--file-system` and takes NO argument, so `%OLp` is read as a
# FILE operand: the command reports "cannot read file system information for
# '%OLp'" and exits 1 — having ALREADY PRINTED a filesystem block for the real
# operand. `$( )` captures the whole of a chain's stdout, so the fallback's
# `600` was appended to that block and the comparison met a paragraph:
#
#     FAILED  the private half is mode   File: "…/id_ed25519"
#         ID: 3bf6563c9a3eb2b Namelen: 255     Type: ext2/ext3
#     600, wanted 600
#
# A green laptop and a red runner over a key whose mode was right all along.
#
# GNU FIRST, which is `deploy/verifier/idle_reaper.sh:272`'s order and the
# reason it has never had this: the probe that FAILS on each platform is the one
# that writes nothing to stdout — BSD `stat` has no `-c` and exits on the usage
# message, GNU `stat` has `-c`. Ordering alone would be enough today; the
# separate capture is what keeps it true if some future `stat` prints before it
# fails, which is exactly the assumption that broke here.
# `if`, not an `&&`-list: a failing probe is expected here, and under a caller's
# `set -e` an AND-list whose left half is false is the FUNCTION failing rather
# than the next probe getting its turn.
file_mode_octal() {
    local out=""
    if out="$(stat -c '%a' "$1" 2>/dev/null)" && [ -n "$out" ]; then
        printf '%s' "$out"
        return 0
    fi
    if out="$(stat -f '%OLp' "$1" 2>/dev/null)" && [ -n "$out" ]; then
        printf '%s' "$out"
        return 0
    fi
    return 1
}

case "${1:-}" in
"") ;;
--list)
    grep -n '^case_[A-Za-z0-9_]*() {' "$0" | sed 's/() {.*//; s/^/  /'
    exit 0
    ;;
*)
    echo "!! unknown argument '$1': test_verifier_box.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

VB=scripts/verifier_box.sh
BAKE=deploy/verifier/bake.sh
SEAM=deploy/verifier/user-data.yaml.in
BAKE_SEAM=deploy/verifier/bake-user-data.yaml
for _s in "$VB" "$BAKE" "$SEAM" "$BAKE_SEAM"; do
    [ -f "$_s" ] || cannot_look "${_s} missing — there is nothing to drive"
done
unset _s
command -v python3 >/dev/null 2>&1 || cannot_look "no python3 on PATH"
command -v ssh-keygen >/dev/null 2>&1 || cannot_look "no ssh-keygen on PATH — the key mode is asserted, not shimmed"

ROOT="$PWD"
WORK=$(mktemp -d "${TMPDIR:-/tmp}/djb-test-verifier-box.XXXXXX") || cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'chmod -R u+rwX "$WORK" 2>/dev/null || true; rm -rf "$WORK"'

# --- THE WRAPPER'S OWN FOOTPRINT, measured rather than asked of git ----------
#
# THE CLAIM IS "this wrapper did not touch the three files beside it",
# and the claim was being made by comparing `main:<path>` to `HEAD:<path>` —
# which is not a claim about the wrapper at all. It is a claim about the BRANCH,
# and it is red on every CI run of a pull request that carries a template fold,
# from the moment the fold lands until the PR merges:
#
#     FAILED  case_nothing_this_wrapper_promised_not_to_touch_moved
#       scripts/setup.sh  main 5ca24c45 vs HEAD c99e45f0
#
# Nothing ran. No wrapper act took place between those two shas; a human
# committed a byte, deliberately, and the drive scored it as the wrapper
# reaching out of its lane. The same read is ALSO the argument-as-sha trap
# on a detached no-main runner (`drive_preamble.sh` §8 has that measurement).
#
# SO THE MEASUREMENT IS THE ONE THE CLAIM IS ABOUT: the bytes of those three
# files BEFORE this drive's first wrapper act, and the bytes AFTER its last. It
# asks git nothing, so a branch, a fold, a detached HEAD, a shallow clone and a
# missing `main` are all irrelevant to it — and it catches a wrapper that
# writes and reverts nothing between two commits, which the git form never
# could.
#
# BEFORE THE FIRST ACT is enforced by position: this runs while the file is
# still defining its world, and every invocation of the wrapper in this drive
# goes through `$VB_COUNTED` below. AFTER THE LAST ACT is enforced by the case
# being the last line of this file.
FOOTPRINT_FILES="scripts/gate_lease.sh scripts/setup.sh .env.example"

# `<path> <cksum>` per file, or `<path> absent` — a neighbour that is not there
# is a RECORDED state and never a skipped one, so a file that vanishes between
# the two snapshots is a delta rather than two silences that match.
footprint_of() {
    local dir="$1" f
    for f in $FOOTPRINT_FILES; do
        if [ -f "${dir}/${f}" ]; then
            printf '%s %s\n' "$f" "$(cksum <"${dir}/${f}")"
        else
            printf '%s absent\n' "$f"
        fi
    done
}

# The differing lines, one per file, or nothing. Compared per FILE rather than
# as two blobs so the message names which neighbour moved.
footprint_delta() {
    local before="$1" after="$2" f a b out=""
    for f in $FOOTPRINT_FILES; do
        a="$(printf '%s\n' "$before" | awk -v k="$f" '$1 == k { sub($1 FS, ""); print; exit }')"
        b="$(printf '%s\n' "$after" | awk -v k="$f" '$1 == k { sub($1 FS, ""); print; exit }')"
        [ "$a" = "$b" ] && continue
        out="${out}
      ${f}  before ${a:-<unrecorded>} vs after ${b:-<unrecorded>}"
    done
    printf '%s' "$out"
}

FOOTPRINT_BEFORE="$(footprint_of "$ROOT")"

# THE COUNTING WRAPPER, and it is a FILE rather than a shell function for one
# measured reason: every call site here goes through `env -i`, which runs a
# PROGRAM and cannot see a function. An absolute path survives the empty
# environment, a background `&` and a pipeline — the three shapes the call
# sites are actually in — and the count lands on disk, where a subshell's
# increment would have been lost with the subshell.
#
# WHAT THE COUNT IS FOR: a footprint comparison that spans ZERO wrapper acts is
# two identical snapshots of a file nobody touched, and it is green. The floor
# in the case turns that into a red.
VB_ACTS="${WORK}/vb-acts"
: >"$VB_ACTS"
VB_COUNTED="${WORK}/vb-counted"
{
    printf '#!/usr/bin/env bash\n'
    printf '# Written by test_verifier_box.sh. Every act of the wrapper, counted.\n'
    printf 'printf "%%s\\n" "$*" >>%s\n' "$(printf '%q' "$VB_ACTS")"
    printf 'exec bash %s "$@"\n' "$(printf '%q' "${ROOT}/${VB}")"
} >"$VB_COUNTED"
chmod +x "$VB_COUNTED"

vb_act_count() {
    local n
    n="$(grep -c . "$VB_ACTS" 2>/dev/null || true)"
    case "$n" in '' | *[!0-9]*) n=0 ;; esac
    printf '%s\n' "$n"
}

# A namespace and a region that are nobody's product and nobody's account.
NS="drivens"
RG="xx-drive-9"
OWNER="drive-session-1"
MAIN_SHA="1111111111111111111111111111111111111111"

# =============================================================================
# THE WORLD — one fake machine and one fake account per case
# =============================================================================
W=""
REC=""

world_new() {
    W="$WORK/$1"
    REC="$W/rec"
    rm -rf "$W"
    mkdir -p "$W/bin" "$REC/ans" "$REC/err" "$REC/rc" "$REC/seq" "$REC/calls" \
        "$REC/ssh" "$W/home/.aws" "$W/vhome"

    # The operator's own config, in the WRONG region on purpose: every call the
    # wrapper makes must carry --region itself, and a call that inherited this
    # would launch somewhere the census never looks.
    printf '[default]\nregion = us-west-2\n' >"$W/home/.aws/config"

    cat >"$W/bin/aws" <<'SHIM'
#!/usr/bin/env bash
# TWO RECORDS PER CALL. `aws.ops` is `<service> <operation>`, one line each, in
# order — what a "exactly one run-instances" claim is about. `calls/<n>.flat` is
# the whole command line with its arguments' own newlines intact — what a "the
# user-data carries the public key" claim is about. `calls/<n>.args` is one
# argument per line for a structured diff.
_n="$(cat "$REC/seq/_call" 2>/dev/null || echo 0)"
_n=$((_n + 1))
printf '%s\n' "$_n" >"$REC/seq/_call"
printf '%s ' "$@" >"$REC/calls/${_n}.flat"
for _a in "$@"; do printf '%s\n' "${_a//$'\n'/\\n}" >>"$REC/calls/${_n}.args"; done

# Step over the global options the wrapper always passes, so the operation is
# $1 $2 — and record whether they were there at all.
_saw_region=""
_saw_profile=""
while [ "$#" -gt 0 ]; do
    case "$1" in
    --region)
        _saw_region="$2"
        shift 2
        ;;
    --profile)
        _saw_profile="$2"
        shift 2
        ;;
    *) break ;;
    esac
done
printf '%s %s\tregion=%s\tprofile=%s\n' "${1:-}" "${2:-}" "$_saw_region" "$_saw_profile" >>"$REC/aws.ops"

_key="${1:-}_${2:-}"
# A --query makes two calls on the same operation different questions, so it is
# part of the key when a fixture wants it to be.
_q=""
for _a in "$@"; do
    if [ -n "${_take_next:-}" ]; then
        _q="$_a"
        _take_next=""
    fi
    [ "$_a" = "--query" ] && _take_next=1
done
_qslug="$(printf '%s' "$_q" | tr -cd 'A-Za-z0-9' | cut -c1-40)"
_qkey="${_key}__${_qslug}"

# THE COUNTER IS PER QUESTION, NOT PER OPERATION. `describe-instances` is asked
# four different things in one `down --all-mine`; one counter across all of them
# means the second box's owner lookup lands on the fifth answer, and a fixture
# that wanted to say "not yours" is never reached. That defect terminated three
# boxes where two were this session's.
_seqfile="$REC/seq/$_qkey"
_i="$(cat "$_seqfile" 2>/dev/null || echo 0)"
_i=$((_i + 1))
printf '%s\n' "$_i" >"$_seqfile"

# EXACT FIRST, THEN LONGEST PREFIX. The key a fixture is filed under is the
# operation plus a slug of its --query, and those slugs are long and fiddly to
# transcribe by hand; a fixture filed under a PREFIX of one is unambiguous and
# readable. Longest wins, so `...InstanceIdInstance` (the census's six-column
# query) beats `...InstanceId` (the headroom count's one-column query) for the
# call that asks the longer question.
_pick() {
    local dir="$1" want base best f
    # EXACT FIRST — a fixture filed under the whole key, sequenced or not.
    for want in "${_qkey}.${_i}" "${_qkey}" "${_key}.${_i}" "${_key}"; do
        if [ -f "$dir/$want" ]; then
            printf '%s\n' "$dir/$want"
            return 0
        fi
    done
    # THEN THE LONGEST PREFIX. The key a fixture is filed under is the operation
    # plus a slug of its --query, and the slug strips every non-alphanumeric and
    # truncates at 40 characters — long and fiddly to transcribe. A fixture filed
    # under a readable PREFIX of one is unambiguous, and longest wins so the
    # census's six-column query beats the headroom count's one-column query.
    # THE SEQUENCE SUFFIX IS APPLIED TO THE MATCHED BASE, never carried into the
    # prefix comparison: `<base>.2` is not a prefix of anything and a fixture
    # that wanted to answer differently on the second call would never be found.
    for want in "$_qkey" "$_key"; do
        best=""
        for f in "$dir"/*; do
            [ -f "$f" ] || continue
            base="${f##*/}"
            case "$base" in *.[0-9]) continue ;; esac
            case "$want" in
            "$base"*)
                if [ "${#base}" -gt "${#best}" ]; then best="$base"; fi
                ;;
            esac
        done
        if [ -n "$best" ]; then
            if [ -f "$dir/${best}.${_i}" ]; then
                printf '%s\n' "$dir/${best}.${_i}"
            else
                printf '%s\n' "$dir/$best"
            fi
            return 0
        fi
    done
    return 1
}

_out="$(_pick "$REC/ans" || true)"
_errf="$(_pick "$REC/err" || true)"
_rcf="$(_pick "$REC/rc" || true)"
[ -z "$_out" ] || cat "$_out"
[ -z "$_errf" ] || cat "$_errf" >&2
if [ -n "$_rcf" ]; then exit "$(cat "$_rcf")"; fi
exit 0
SHIM

    cat >"$W/bin/ssh" <<'SHIM'
#!/usr/bin/env bash
# THE FAKE CLOCK PAYS FOR THIS CALL. A poll loop that waits by COUNTING its
# polls is wrong by however long each poll itself takes, and an SSH attempt
# through an SSM tunnel to a box that is not answering is not free. A shim that
# returned instantly would make that error invisible, so this one charges the
# clock DRIVE_SSH_SECONDS, the way the real transport charges the wall.
_d="$(cat "$REC/clock" 2>/dev/null || echo 0)"
printf '%s\n' "$((_d + ${DRIVE_SSH_SECONDS:-5}))" >"$REC/clock"
_n="$(cat "$REC/seq/_ssh" 2>/dev/null || echo 0)"
_n=$((_n + 1))
printf '%s\n' "$_n" >"$REC/seq/_ssh"
printf '%s ' "$@" >"$REC/ssh/${_n}.flat"
# THE OPERATOR'S OWN HAND, MODELLED. A wrapper that is interrupted mid-wait is
# the commonest way a box is orphaned and the one no failure path in the
# subject can see, so a fixture signals the subject through its own parent —
# which, for the readiness probe, is the wrapper's top-level shell and nothing
# in between.
if [ -f "$REC/ssh/${_n}.signal" ]; then
    kill -"$(cat "$REC/ssh/${_n}.signal")" "$PPID" 2>/dev/null || true
fi
for _a in "$@"; do printf '%s\n' "${_a//$'\n'/\\n}" >>"$REC/ssh/${_n}.args"; done
if [ -f "$REC/ssh/${_n}.out" ]; then
    cat "$REC/ssh/${_n}.out"
elif [ -f "$REC/ssh/default.out" ]; then
    cat "$REC/ssh/default.out"
fi
# AND WHAT SSH ITSELF SAID, which is a different channel and a different fact.
# `TargetNotConnected` is written by the session plugin on STDERR with ssh's
# own 255, and the subject now branches on that WORD and not on the status
# alone — a plain 255 is a dead transport and is still an instant refusal. A
# shim with no stderr could not tell the fixture's two kinds of 255 apart, so
# the case that proves the retry is bounded would have proven nothing.
if [ -f "$REC/ssh/${_n}.err" ]; then
    cat "$REC/ssh/${_n}.err" >&2
elif [ -f "$REC/ssh/default.err" ]; then
    cat "$REC/ssh/default.err" >&2
fi
if [ -f "$REC/ssh/${_n}.rc" ]; then exit "$(cat "$REC/ssh/${_n}.rc")"; fi
if [ -f "$REC/ssh/default.rc" ]; then exit "$(cat "$REC/ssh/default.rc")"; fi
exit 0
SHIM

    # A BOX ANSWERS WITH THE TREE IT IS STANDING ON, BY DEFAULT. Every question
    # the wrapper asks a box about its own git state — `rev-parse HEAD^{tree}`,
    # `rev-parse refs/heads/main^{tree}` — is answered here with the same sha
    # the shimmed `git` gives this checkout, so the DEFAULT world is a box that
    # agrees with what was pushed. A case that wants a box standing on something
    # else plants the ordinal it cares about; before this, silence was the
    # default and silence reads as "unreadable", which is a refusal about a
    # different thing.
    printf '%s\n' "$MAIN_SHA" >"$REC/ssh/default.out"

    cat >"$W/bin/scp" <<'SHIM'
#!/usr/bin/env bash
printf '%s ' "$@" >>"$REC/scp.flat"
printf '\n' >>"$REC/scp.flat"
# ARGUMENT BOUNDARIES, WHICH THE FLAT RECORD LOSES. An option value with
# spaces in it reads the same flattened as the same value split across three
# arguments; the case that resolves the transport needs the difference.
for _a in "$@"; do printf '%s\n' "${_a//$'\n'/\\n}" >>"$REC/scp.args"; done
# AND WHAT WAS IN THE FILE. A recorded argv says a path was named; it says
# nothing about the bytes, and "the carrier sent exactly these rows and no
# others" is a claim about bytes. Any argument that is a local file this shim
# can read is dumped, headed by its own path so two of them cannot be read as
# one.
_prev=""
for _a in "$@"; do
    case "$_prev" in -i | -o) _prev="$_a"; continue ;; esac
    _prev="$_a"
    [ -f "$_a" ] || continue
    printf -- '--- %s\n' "$_a" >>"$REC/scp.payload"
    cat "$_a" >>"$REC/scp.payload"
done
exit 0
SHIM

    cat >"$W/bin/git" <<'SHIM'
#!/usr/bin/env bash
printf '%s ' "$@" >>"$REC/git.flat"
printf '\n' >>"$REC/git.flat"
# The environment is half the claim for `push`: GIT_SSH_COMMAND is what carries
# the transport, and an argv-only record would not see it.
printf 'GIT_SSH_COMMAND=%s\n' "${GIT_SSH_COMMAND:-<unset>}" >>"$REC/git.env"
# THE DESTINATION DECLARATION, PER CALL, AND THE PER-CALL PART IS THE CLAIM.
# `DJB_PUSH_DESTINATION` is exported by a prefix assignment on ONE command, so
# "only the vouch carries it" is a statement about the difference between two
# lines of this file — an environment record that kept only the last value could
# not tell that apart from an export that leaked into the transfer.
printf '%s\t%s\n' "${DJB_PUSH_DESTINATION:-<unset>}" "$*" >>"$REC/git.dest"
for _a in "$@"; do
    # A PUSH THAT FAILS IS A FIXTURE, because the push is the one step whose
    # failure is THIS machine's rather than the box's: a pre-push hook that
    # refuses before a byte leaves the laptop looks, from the wrapper's side,
    # exactly like git exit 128. The box cannot explain it and cannot fix it,
    # so what happens to the box is the whole question.
    # TWO PUSHES NOW, AND THEY FAIL FOR DIFFERENT REASONS. The first is the
    # VOUCH — a `--dry-run` at a scratch repository on this machine, whose
    # failure is the pre-push hook refusing before anything leaves. The second
    # is the TRANSFER, to an `ssh://` remote, whose failure is the transport or
    # the receiver. One fixture switch for both would make every "the hook
    # refused" case indistinguishable from every "the tunnel died" case, which
    # is the exact confusion the wrapper's own sentences exist to clear.
    if [ "$_a" = "push" ]; then
        case "$*" in
        *ssh://*)
            # ONE REF PER PUSH MEANS A FIXTURE CAN REFUSE ONE OF THEM. Which
            # ref failed, and what had already landed, is the whole of what a
            # caller deciding between a retry and a teardown has to read.
            if [ -f "$REC/git.push.base.rc" ]; then
                case "$*" in
                *refs/djb/base*)
                    [ -f "$REC/git.push.base.err" ] && cat "$REC/git.push.base.err" >&2
                    exit "$(cat "$REC/git.push.base.rc")"
                    ;;
                esac
            fi
            if [ -f "$REC/git.push.rc" ]; then
                [ -f "$REC/git.push.err" ] && cat "$REC/git.push.err" >&2
                exit "$(cat "$REC/git.push.rc")"
            fi
            ;;
        *)
            # THE HOOK'S OWN SENTINEL, ON STDOUT, BY DEFAULT. `pre-push: wall
            # <word> <tree>` is what the real hook prints before every terminal
            # decision, and it is the only evidence the WRAPPER has that a wall
            # was consulted at all — a `--dry-run` exits 0 whether the hook
            # passed the tree or no hook exists to stop it. Every case here but
            # one is about a checkout whose hooks run, so that is the default; a
            # case that wants a HOOKLESS checkout plants an EMPTY
            # `git.vouch.out`, and the vouch then says nothing at all, which is
            # exactly what a `git clone` does.
            if [ -f "$REC/git.vouch.out" ]; then
                cat "$REC/git.vouch.out"
            else
                echo "pre-push: wall box-exempt 2222222222222222222222222222222222222222"
            fi
            if [ -f "$REC/git.vouch.rc" ]; then
                [ -f "$REC/git.vouch.err" ] && cat "$REC/git.vouch.err" >&2
                exit "$(cat "$REC/git.vouch.rc")"
            fi
            ;;
        esac
    fi
    # THE FORK POINT AND THE DISTANCE TO IT. Unplanted, both answer NOTHING —
    # which is what every case written before the base was carried expects, and
    # it is also the honest shape of a checkout with no local `main`.
    if [ "$_a" = "merge-base" ]; then
        # `--is-ancestor` IS A QUESTION WITH A STATUS AND NO WORDS. Unplanted it
        # answers yes, which is the shape of every checkout these cases model
        # (a fork point is behind its HEAD); a case about a history that reaches
        # no fork point plants `git.ancestor.rc`.
        case " $* " in
        *" --is-ancestor "*) exit "$(cat "$REC/git.ancestor.rc" 2>/dev/null || echo 0)" ;;
        esac
        cat "$REC/git.mergebase" 2>/dev/null || true
        exit 0
    fi
    if [ "$_a" = "rev-list" ]; then
        cat "$REC/git.revlist" 2>/dev/null || true
        exit 0
    fi
    if [ "$_a" = "rev-parse" ]; then
        # A DECLARED FORK POINT IS A FIXTURE, AND ITS ABSENCE IS THE DEFAULT.
        # `refs/djb/base` in the checkout is what a verify clone carries; every
        # other world has none, and answering it with HEAD's sha — this shim's
        # answer to everything else — would invent a declaration nobody made.
        case " $* " in
        *refs/djb/base*)
            [ -f "$REC/git.djbbase" ] || exit 1
            cat "$REC/git.djbbase"
            exit 0
            ;;
        esac
        # A CHECKOUT WITH NO LOCAL `main` IS A FIXTURE, and it has to be: the
        # wrapper reads its OWN checkout — the one this drive runs in, which
        # has the ref — so the population a `git clone --branch <tag>` belongs
        # to is unreachable here any other way. Only the question ABOUT main
        # answers absent; `rev-parse HEAD` still answers a sha, exactly as it
        # does in a tag clone.
        #
        # AND IT IS SCOPED TO ONE REPOSITORY, which the fixture names — the
        # CHECKOUT. The wrapper also asks this question of the scratch mirror
        # it builds under DJB_VERIFIER_HOME, where `main` is a ref the wrapper
        # itself just created from HEAD and exists in a tag clone too; a
        # fixture that answered absent there would fake a different failure
        # (the mirror landing on nothing) and let a case pass for it.
        _nomain="$(cat "$REC/git.no-main" 2>/dev/null || true)"
        if [ -n "$_nomain" ]; then
            _repo=""
            _prev=""
            for _c in "$@"; do
                [ "$_prev" = "-C" ] && {
                    _repo="$_c"
                    break
                }
                _prev="$_c"
            done
            [ "$_repo" = "$_nomain" ] || _nomain=""
        fi
        if [ -n "$_nomain" ]; then
            case " $* " in
            *" refs/heads/main "* | *" main "*)
                # THE TWO FORMS ANSWER DIFFERENTLY, as real git does, and the
                # difference is the whole claim: `--verify --quiet` is silent
                # and exit 1 (a question), while the bare form is a fatal and
                # exit 128 (an assumption).
                case "$*" in
                *--quiet*) exit 1 ;;
                *)
                    echo "fatal: ambiguous argument 'main': unknown revision or path not in the working tree." >&2
                    exit 128
                    ;;
                esac
                ;;
            esac
        fi
        # TWO SHAS, WHEN A CASE ASKS FOR TWO. `git.revparse` is HEAD's and is
        # the answer to everything by default; a case that plants
        # `git.revparse.main` (`<repo path><TAB><sha>`) makes the LOCAL `main` a
        # different commit, which is every rung worktree in this repository and
        # is the only way to tell "named after the tree the image holds" apart
        # from "named after whatever main happens to be".
        #
        # SCOPED TO ONE REPOSITORY, for the reason the no-main fixture above
        # gives: the wrapper asks this question of the scratch MIRROR too, where
        # `main` is a ref it just created from HEAD, and an unscoped fixture
        # makes the mirror land on a sha nobody pushed — a refusal about the
        # wrong thing, which is what this case saw on its first run.
        if [ -f "$REC/git.revparse.main" ]; then
            _mainfix="$(cat "$REC/git.revparse.main")"
            _mainrepo=""
            _prev=""
            for _c in "$@"; do
                [ "$_prev" = "-C" ] && {
                    _mainrepo="$_c"
                    break
                }
                _prev="$_c"
            done
            if [ "$_mainrepo" = "${_mainfix%%	*}" ]; then
                case " $* " in
                *" refs/heads/main "* | *" main "*)
                    printf '%s\n' "${_mainfix##*	}"
                    exit 0
                    ;;
                esac
            fi
        fi
        cat "$REC/git.revparse" 2>/dev/null || echo "0000000000000000000000000000000000000000"
        exit 0
    fi
done
exit 0
SHIM

    printf '#!/usr/bin/env bash\nexit 0\n' >"$W/bin/session-manager-plugin"
    # REAL WALL CLOCK IS NOT UNDER TEST — a real poll loop would cost minutes
    # per case — but WHAT THE SUBJECT BELIEVES THE WALL CLOCK IS now is. So
    # there is a fake one: `sleep` advances it instead of spending it, `ssh`
    # charges it (above), and `date +%s` reads it. A wait that COUNTS its polls
    # and a wait that MEASURES the clock are indistinguishable without this,
    # and the difference is a refusal naming a number that is not the
    # elapsed time.
    printf '%s\n' "$(/bin/date +%s)" >"$REC/clock"
    cat >"$W/bin/sleep" <<'SHIM'
#!/usr/bin/env bash
_d="$(cat "$REC/clock" 2>/dev/null || echo 0)"
printf '%s\n' "$((_d + ${1:-0}))" >"$REC/clock"
exit 0
SHIM
    cat >"$W/bin/date" <<'SHIM'
#!/usr/bin/env bash
# `+%s` is the subject's clock and the case owns it; every other format is real
# time, because only the clock is under test. (The image drive's reaper shim is
# the same idiom, for the same reason.)
for a in "$@"; do
    if [ "$a" = "+%s" ]; then cat "$REC/clock"; exit 0; fi
done
exec /bin/date "$@"
SHIM
    chmod +x "$W/bin/aws" "$W/bin/ssh" "$W/bin/scp" "$W/bin/git" \
        "$W/bin/session-manager-plugin" "$W/bin/sleep" "$W/bin/date"

    printf '%s\n' "$MAIN_SHA" >"$REC/git.revparse"
    # The profile exists by default; the case that wants it gone removes it.
    printf '\n[profile %s-verifier]\nregion = %s\n' "$NS" "$RG" >>"$W/home/.aws/config"
}

# The wrapper reads the profile through `aws configure list`, which is AWS's own
# resolution rather than a second opinion about ini files. The shim answers it
# from the scratch config, so "the profile is absent" is a real fixture.
world_profile_absent() {
    printf '[default]\nregion = us-west-2\n' >"$W/home/.aws/config"
    printf '%s\n' 1 >"$REC/rc/configure_list"
    printf 'The config profile could not be found\n' >"$REC/err/configure_list"
}

world_plugin_absent() { rm -f "$W/bin/session-manager-plugin"; }

# ans <key> <text...> / rc <key> <status> / err <key> <text>
ans() {
    local k="$1"
    shift
    printf '%s\n' "$*" >"$REC/ans/$k"
}
ansf() {
    local k="$1"
    shift
    printf '%s\n' "$@" >"$REC/ans/$k"
}
rcf() { printf '%s\n' "$2" >"$REC/rc/$1"; }
errf() {
    local k="$1"
    shift
    printf '%s\n' "$*" >"$REC/err/$k"
}

VB_RC=0
run_vb() {
    VB_RC=0
    env -i \
        PATH="$W/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
        HOME="$W/home" \
        REC="$REC" \
        USER="driveuser" \
        DJB_DEPLOY_NAMESPACE="$NS" \
        DJB_VERIFIER_REGION="$RG" \
        DJB_VERIFIER_HOME="$W/vhome" \
        DJB_VERIFIER_OWNER="$OWNER" \
        "$@" \
        "$VB_COUNTED" >"$W/out" 2>"$W/err" || VB_RC=$?
}

# run_vb takes env assignments first and the subcommand after `--`; this keeps
# the common case readable.
vb() {
    local -a env_extra=()
    while [ "${1:-}" != "--" ] && [ "$#" -gt 0 ]; do
        env_extra+=("$1")
        shift
    done
    shift || true
    VB_RC=0
    env -i \
        PATH="$W/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
        HOME="$W/home" \
        REC="$REC" \
        USER="driveuser" \
        DJB_DEPLOY_NAMESPACE="$NS" \
        DJB_VERIFIER_REGION="$RG" \
        DJB_VERIFIER_HOME="$W/vhome" \
        DJB_VERIFIER_OWNER="$OWNER" \
        "${env_extra[@]+"${env_extra[@]}"}" \
        "$VB_COUNTED" "$@" >"$W/out" 2>"$W/err" || VB_RC=$?
}

out_has() { grep -F -- "$1" "$W/out" >/dev/null 2>&1; }
err_has() { grep -F -- "$1" "$W/err" >/dev/null 2>&1; }
said() { grep -F -- "$1" "$W/out" "$W/err" >/dev/null 2>&1; }
# HOW MANY TIMES IT SAID IT, because "it retried twice" is a claim about a
# COUNT and `said` answers a yes/no that one line satisfies. `grep -c` over two
# files prints one count per file, so the counts are added here rather than
# read as a string.
said_count() {
    local n total=0 f
    for f in "$W/out" "$W/err"; do
        n="$(grep -cF -- "$1" "$f" 2>/dev/null || true)"
        case "$n" in '' | *[!0-9]*) n=0 ;; esac
        total=$((total + n))
    done
    printf '%s\n' "$total"
}
ops() { cat "$REC/aws.ops" 2>/dev/null || true; }
op_count() { ops | grep -cE "^$1" || true; }
call_flat() { cat "$REC/calls/$1.flat" 2>/dev/null || true; }
# The flat record of the Nth call to a given operation.
nth_call_of() {
    local want="$1" n="$2" i=0 f
    for f in $(ls "$REC/calls" 2>/dev/null | grep '\.flat$' | sort -t. -k1 -n); do
        if grep -qE -- "(^| )$want( |$)" "$REC/calls/$f" 2>/dev/null; then
            i=$((i + 1))
            [ "$i" = "$n" ] && {
                cat "$REC/calls/$f"
                return 0
            }
        fi
    done
    return 1
}
report() {
    echo "    --- stdout ---"
    sed 's/^/    /' "$W/out" 2>/dev/null || true
    echo "    --- stderr ---"
    sed 's/^/    /' "$W/err" 2>/dev/null || true
    echo "    --- aws ops ---"
    sed 's/^/    /' "$REC/aws.ops" 2>/dev/null || echo "    (none)"
}

# The stamp the subject prints, computed here from the same epoch, so a case
# can tell a stamp read from the FAKE clock apart from one read from the
# machine's. UTC, because that is the zone the expiry tags and the census
# already speak and two zones in one transcript is a subtraction nobody gets
# right at 2am.
stamp_utc() {
    python3 -c 'import sys,datetime
print(datetime.datetime.fromtimestamp(int(sys.argv[1]),datetime.timezone.utc).strftime("%H:%M:%S"))' "$1"
}

# A world in which `up` would succeed, so each refusal case can remove exactly
# one thing and nothing else explains the refusal.
world_up_ready() {
    ans "ec2_describe-images__sortby" "ami-v1"
    ans "ec2_describe-security-groups" "sg-v"
    ans "ec2_describe-instances__ReservationsInstancesInstanceId" ""
    ans "service-quotas_get-service-quota" "32.0"
    # FOUR COLUMNS, WHICH IS WHAT `run-instances` REALLY ANSWERS now:
    # `[InstanceId,SpotInstanceRequestId,Placement.AvailabilityZone,InstanceLifecycle]`.
    # `up` reads the zone and the market off THIS answer and not off a
    # describe, because a describe on a seconds-old id is inside EC2's
    # eventual-consistency window; a one-column fixture here would leave the
    # wrapper falling back to the describe on every case and the launch path
    # would go unmeasured.
    ans "ec2_run-instances" "$(printf 'i-up1\tsir-w1\t%sc\tspot' "$RG")"
    printf 'Pending\n' >"$REC/ans/ssm_describe-instance-information.1"
    printf 'Online\n' >"$REC/ans/ssm_describe-instance-information.2"
    ans "ec2_describe-instances__Reservations0Instances0Placement" "${RG}c"
    # THE MARKET EC2 REPORTS, BESIDE THE AZ, out of the one describe `up`
    # already makes. `InstanceLifecycle` is `spot` on a Spot instance and
    # ABSENT on an on-demand one — `--output text` renders that absence as
    # `None` — so this fixture is the spot answer and the on-demand answer is a
    # case that plants `None`. The key is the lifecycle-first projection's own
    # slug; the AZ-only key above is a different question and is answered
    # separately, because a fixture that answered both would hide which one the
    # wrapper asked.
    ans "ec2_describe-instances__Reservations0Instances0InstanceLifecycle" "$(printf 'spot\t%sc' "$RG")"
    # THE REAL SHAPE, MEASURED ON A REAL LAUNCH (2026-09-18): `--max-items 1`
    # makes the CLI print a pagination token on a SECOND line, so this answer
    # is two lines and the second one is `None`. It was a single line here and
    # the drive was green while a real `pool` launch tagged a box
    # `djb:price=0.203600<newline>None`. A fixture that is tidier than the API
    # is a fixture that cannot see the defect.
    ansf "ec2_describe-spot-price-history" "0.2085" "None"
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    printf '%s\n' "$MAIN_SHA" >"$REC/ssh/default.out"
}

# --- the warm pool's world ---------------------------------------------------
#
# ONE FIXTURE KEY FOR THE ONE QUESTION. `warm_pool_rows` asks EC2 a question
# nothing else in this wrapper asks — sorted by launch time, four columns — so
# it gets its own fixture file and can never be answered by the headroom
# count's listing, which is a PREFIX of the census's and would otherwise be
# picked up by the shim's longest-prefix rule and read as a pool.
pool_listing() {
    local row out=""
    for row in "$@"; do out="${out}${row}
"; done
    printf '%s' "$out" >"$REC/ans/ec2_describe-instances__sortbyReservations"
}

# One row of that listing: <id> <launch time> <ami> <type> <price tag>, from
# <id> <launched n minutes ago> <ami> <price tag>.
pool_row() {
    local id="$1" age_min="$2" ami="$3" price="$4" now
    now="$(cat "$REC/clock")"
    printf '%s\t%s\t%s\tc7g.4xlarge\t%s' "$id" "$(iso_utc $((now - age_min * 60)))" "$ami" "$price"
}

iso_utc() {
    python3 -c 'import sys,datetime
print(datetime.datetime.fromtimestamp(int(sys.argv[1]),datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))' "$1"
}

# A world in which a POOL launch would succeed. `world_up_ready`'s image,
# group, quota and price, plus a headroom count of nothing running.
world_pool_ready() {
    ans "ec2_describe-images__sortby" "ami-v1"
    ans "ec2_describe-security-groups" "sg-v"
    ans "ec2_describe-instances__ReservationsInstancesInstanceId" ""
    ans "service-quotas_get-service-quota" "32.0"
    # THE REAL SHAPE, MEASURED ON A REAL LAUNCH (2026-09-18): `--max-items 1`
    # makes the CLI print a pagination token on a SECOND line, so this answer
    # is two lines and the second one is `None`. It was a single line here and
    # the drive was green while a real `pool` launch tagged a box
    # `djb:price=0.203600<newline>None`. A fixture that is tidier than the API
    # is a fixture that cannot see the defect.
    ansf "ec2_describe-spot-price-history" "0.2085" "None"
    # The state and the tags `terminate_one` reads back, in the one describe it
    # now makes, before it will terminate anything.
    ans "ec2_describe-instances__Reservations0Instances0StateNameStateRea" \
        "$(printf 'running\tNone\tverifier\t%s' "$NS")"
}

# =============================================================================
# 1.1 and the namespace rider — the walls, before anything is launched
# =============================================================================

case_the_wrapper_refuses_without_a_namespace_or_a_region() {
    CURRENT=case_the_wrapper_refuses_without_a_namespace_or_a_region
    local v
    for v in DJB_DEPLOY_NAMESPACE DJB_VERIFIER_REGION; do
        world_new "no_${v}"
        world_up_ready
        VB_RC=0
        if [ "$v" = "DJB_DEPLOY_NAMESPACE" ]; then
            env -i PATH="$W/bin:/usr/bin:/bin" HOME="$W/home" REC="$REC" USER=driveuser \
                DJB_VERIFIER_REGION="$RG" DJB_VERIFIER_HOME="$W/vhome" \
                "$VB_COUNTED" up --for X >"$W/out" 2>"$W/err" || VB_RC=$?
        else
            env -i PATH="$W/bin:/usr/bin:/bin" HOME="$W/home" REC="$REC" USER=driveuser \
                DJB_DEPLOY_NAMESPACE="$NS" DJB_VERIFIER_HOME="$W/vhome" \
                "$VB_COUNTED" up --for X >"$W/out" 2>"$W/err" || VB_RC=$?
        fi
        if [ "$VB_RC" != "2" ]; then
            bad "${v} unset: wanted exit 2, got ${VB_RC}"
            report
            continue
        fi
        said "$v" || {
            bad "${v} unset: the refusal does not name the variable"
            continue
        }
        [ ! -f "$REC/aws.ops" ] || {
            bad "${v} unset: aws was called anyway — $(head -n 1 "$REC/aws.ops")"
            continue
        }
        ok "${v} unset → exit 2, names the variable, not one aws call"
    done
}

case_up_refuses_when_there_is_no_profile() {
    CURRENT=case_up_refuses_when_there_is_no_profile
    world_new no_profile
    world_up_ready
    world_profile_absent
    vb -- up --for X
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2, got ${VB_RC}"
        report
        return
    }
    ok "exit 2 with no profile"
    local miss=""
    said "./deploy/iam/verifier_bootstrap.sh --confirm" || miss="${miss} the-bootstrap-command"
    said "aws configure --profile ${NS}-verifier" || miss="${miss} the-configure-command"
    if [ -z "$miss" ]; then
        ok "both owner commands printed verbatim"
    else
        bad "the refusal does not print:${miss}"
        report
    fi
    [ "$(op_count 'ec2 run-instances')" = "0" ] && ok "no run-instances recorded" ||
        bad "$(op_count 'ec2 run-instances') run-instances recorded on the refusal path"
}

case_up_refuses_when_the_session_plugin_is_absent() {
    CURRENT=case_up_refuses_when_the_session_plugin_is_absent
    world_new no_plugin
    world_up_ready
    world_plugin_absent
    vb -- up --for X
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2, got ${VB_RC}"
        report
        return
    }
    said "brew install --cask session-manager-plugin" &&
        ok "exit 2 naming the one command that installs it" ||
        bad "the refusal does not name the install command"
    [ "$(op_count 'ec2 run-instances')" = "0" ] && ok "no run-instances recorded" ||
        bad "run-instances recorded with no way to reach the box"
}

case_up_refuses_when_no_image_has_been_baked() {
    CURRENT=case_up_refuses_when_no_image_has_been_baked
    world_new no_image
    world_up_ready
    ans "ec2_describe-images__sortby" "None"
    vb -- up --for X
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2, got ${VB_RC}"
        report
        return
    }
    said "verifier_box.sh bake" && ok "exit 2 naming bake" || bad "the refusal does not name bake"
    [ "$(op_count 'ec2 run-instances')" = "0" ] && ok "no run-instances recorded" ||
        bad "run-instances recorded with no image to launch"
}

# THE IMAGE THE TAG LOOKUP CANNOT SEE. `up` finds its image by tag, which is
# the right default and fails in one specific way: a capture whose TAGS were
# refused produces a perfectly good image that no tag filter matches, and the
# only thing standing between the operator and a second twenty-minute bake is
# being able to name the id by hand. The explicit id therefore WINS over the
# lookup — and is checked, because an image that is still `pending` launches
# nothing and the refusal has to say which of the two it is.
case_up_takes_an_explicit_image_id_over_the_tag_lookup() {
    CURRENT=case_up_takes_an_explicit_image_id_over_the_tag_lookup
    world_new up_image_id
    world_up_ready
    # The tag lookup would answer something DIFFERENT, so a launch on the
    # explicit id is a real precedence claim rather than a coincidence.
    ans "ec2_describe-images__sortby" "ami-from-the-tag"
    ans "ec2_describe-images__Images0NameState" "al2023-ami-2026.0.20260917.0-kernel-6.1-arm64	available"
    vb -- up --for X --image-id ami-explicit
    if [ "$VB_RC" != "0" ]; then
        bad "up --image-id exited ${VB_RC}"
        report
        return
    fi
    local call
    call="$(nth_call_of "run-instances" 1 || true)"
    case "$call" in
    *"--image-id ami-explicit"*) ok "the launch carries the explicit image, not the tag lookup's answer" ;;
    *) bad "run-instances is '${call}'" ;;
    esac
    if printf '%s' "$call" | grep -F -- "ami-from-the-tag" >/dev/null; then
        bad "the tag lookup's image reached the launch"
    else
        ok "the tag lookup's image is nowhere in the launch"
    fi
    said "ami-explicit" && ok "and it says which image it is launching" ||
        bad "the output never names the image"
}

case_up_refuses_an_explicit_image_that_is_not_available_yet() {
    CURRENT=case_up_refuses_an_explicit_image_that_is_not_available_yet
    world_new up_image_pending
    world_up_ready
    ans "ec2_describe-images__Images0NameState" "some-name	pending"
    vb -- up --for X --image-id ami-half-baked
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2 on an image that is not available, got ${VB_RC}"
        report
        return
    }
    said "pending" && ok "exit 2 naming the state the image is actually in" ||
        bad "the refusal does not say what state the image is in"
    [ "$(op_count 'ec2 run-instances')" = "0" ] && ok "nothing was launched" ||
        bad "a box was launched from an image that is not available"
}

# =============================================================================
# 1.2 — up launches exactly the box the design describes
# =============================================================================

case_up_launches_exactly_the_box_the_design_describes() {
    CURRENT=case_up_launches_exactly_the_box_the_design_describes
    world_new up_ok
    world_up_ready
    vb -- up --for X
    if [ "$VB_RC" != "0" ]; then
        bad "up exited ${VB_RC}"
        report
        return
    fi
    local call
    call="$(nth_call_of "run-instances" 1 || true)"
    [ -n "$call" ] || {
        bad "no run-instances was recorded at all"
        report
        return
    }
    local want miss=""
    for want in \
        "--region ${RG}" \
        "--image-id ami-v1" \
        "--instance-type c7g.4xlarge" \
        "MarketType=spot" \
        "SpotInstanceType=one-time" \
        "InstanceInterruptionBehavior=terminate" \
        "--instance-initiated-shutdown-behavior terminate" \
        "HttpTokens=required" \
        "--iam-instance-profile Name=${NS}-verifier-box" \
        "--security-group-ids sg-v" \
        "VolumeSize=60" \
        "VolumeType=gp3" \
        "Encrypted=true" \
        "Key=djb:role,Value=verifier" \
        "Key=djb:owner,Value=${OWNER}" \
        "Key=djb:namespace,Value=${NS}" \
        "Key=Name,Value=${NS}-verifier-${OWNER}-X" \
        "Key=Project,Value=${NS}"; do
        case "$call" in *"$want"*) ;; *) miss="${miss}
      ${want}" ;; esac
    done
    case "$call" in *"Key=djb:expires,Value=2"*) ;; *) miss="${miss}
      an ISO-8601 djb:expires tag" ;; esac
    if [ -z "$miss" ]; then
        ok "every launch property the design promises is on the recorded argv"
    else
        bad "the launch is missing:${miss}"
        echo "      recorded: ${call}" | cut -c1-400
    fi
    case "$call" in
    *--key-name*) bad "the launch carries --key-name — a verifier box has no key pair at all" ;;
    *) ok "no --key-name: the only way in is the user-data's authorized key" ;;
    esac
    # AND NO --subnet-id, because no zone was asked for. `up --az Z` pins one;
    # an ordinary `up` must leave the placement to EC2 exactly as it always
    # did, or the zone axis has quietly decided where every box in the account
    # lands and nothing would say so — the launch would still work.
    case "$call" in
    *--subnet-id*) bad "an up with no --az pinned a subnet anyway — the zone axis must cost an unzoned launch nothing" ;;
    *) ok "no --subnet-id: with no --az the placement is still EC2's" ;;
    esac
    case "$call" in
    *"us-west-2"*) bad "the call inherited the operator's configured region" ;;
    *) ok "the operator's own default region is nowhere on the call" ;;
    esac

    # The key, and the half that never leaves.
    local priv="$W/vhome/i-up1/id_ed25519"
    if [ -f "$priv" ] && [ -f "${priv}.pub" ]; then
        local mode
        mode="$(file_mode_octal "$priv" || echo '?')"
        [ "$mode" = "600" ] && ok "the private half is mode 600 under DJB_VERIFIER_HOME" ||
            bad "the private half is mode ${mode}, wanted 600"
        local pub
        pub="$(cat "${priv}.pub")"
        case "$call" in
        *"$pub"*) ok "the user-data carries the public half that was just written" ;;
        *) bad "the user-data does not carry the public key" ;;
        esac
    else
        bad "no keypair was written to ${W}/vhome/i-up1/"
    fi
    case "$call" in
    *"${OWNER}"*) ok "the user-data carries the owner" ;;
    *) bad "the user-data does not carry the owner" ;;
    esac

    # THE BLOCK'S FIRST LINE, FOUND RATHER THAN ASSUMED TO BE STDOUT'S FIRST.
    # `up` no longer discards the push's narration: a refused vouch has to be
    # explainable from `up`'s own output, so the sentinel, the hook's words and
    # the push's own `pushing …` line now precede the summary. What the design
    # claims is that the SUMMARY BLOCK opens on the instance and the market, and
    # that is what is read here — the old `head -n 1` was reading the block's
    # position, which was never the claim.
    local line
    line="$(grep -m1 '^instance   ' "$W/out" || true)"
    case "$line" in
    "instance   i-up1"*"market: spot"*) ok "the block's first line names the instance and the market" ;;
    *) bad "the block's first line is not the design's instance line: '${line}'" ;;
    esac
    [ "$(grep -c . "$W/out")" -ge 5 ] && ok "the block is five lines" ||
        bad "the block is $(grep -c . "$W/out") line(s), wanted five"
}

case_up_refuses_a_lifetime_above_the_cap() {
    CURRENT=case_up_refuses_a_lifetime_above_the_cap
    world_new ttl_cap
    world_up_ready
    vb -- up --for X --ttl 13
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2, got ${VB_RC}"
        report
        return
    }
    [ ! -f "$REC/aws.ops" ] && ok "exit 2 BEFORE any aws call at all" ||
        bad "the ceiling was checked after $(grep -c . "$REC/aws.ops") aws call(s)"
    said "cap" && ok "the refusal names the cap" || bad "the refusal does not mention a cap"
}

case_up_carries_a_shorter_lifetime_and_idle_through() {
    CURRENT=case_up_carries_a_shorter_lifetime_and_idle_through
    world_new ttl_short
    world_up_ready
    vb -- up --for X --ttl 2 --idle 10
    [ "$VB_RC" = "0" ] || {
        bad "up exited ${VB_RC}"
        report
        return
    }
    local call
    call="$(nth_call_of "run-instances" 1 || true)"
    case "$call" in
    *"/etc/verifier/idle-minutes"*) ok "the user-data writes the idle threshold" ;;
    *) bad "the user-data has no idle-minutes file" ;;
    esac
    # The rendered seam carries the typed idle value, and the expiry tag and the
    # expiry file are the same instant.
    local n_ten
    n_ten="$(printf '%s' "$call" | grep -c 'content: "10"' || true)"
    [ "$n_ten" -ge 1 ] && ok "the seam rendered the typed idle of 10 minutes" ||
        bad "the rendered user-data does not carry the typed idle value"
    local tag_exp file_exp
    # Read whole, then slice: `grep … | head -n 1` is the early-exit reader the
    # pipefail census names, and `$call` is a whole rendered cloud-config.
    tag_exp="$(printf '%s' "$call" | grep -oE 'Key=djb:expires,Value=[0-9TZ:-]+' || true)"
    tag_exp="${tag_exp%%$'\n'*}"
    tag_exp="${tag_exp##*=}"
    file_exp="$(printf '%s' "$call" | grep -oE '"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z"' || true)"
    file_exp="${file_exp%%$'\n'*}"
    file_exp="${file_exp//\"/}"
    [ -n "$tag_exp" ] && [ "$tag_exp" = "$file_exp" ] &&
        ok "the expiry the tag carries and the expiry the box reads are the same instant (${tag_exp})" ||
        bad "the tag says '${tag_exp}' and the box's own file says '${file_exp}' — the reaper and the census would disagree"
    said "ttl 2h" && ok "the block prints the lifetime it used" || bad "the block does not print 'ttl 2h'"
}

# =============================================================================
# 1.3 — the on-demand fallback
# =============================================================================

case_a_spot_refusal_falls_back_to_on_demand_and_says_which() {
    CURRENT=case_a_spot_refusal_falls_back_to_on_demand_and_says_which
    local code
    for code in InsufficientInstanceCapacity SpotMaxPriceTooLow MaxSpotInstanceCountExceeded; do
        world_new "spot_${code}"
        world_up_ready
        printf 'An error occurred (%s) when calling the RunInstances operation\n' "$code" >"$REC/err/ec2_run-instances.1"
        printf '1\n' >"$REC/rc/ec2_run-instances.1"
        printf '' >"$REC/ans/ec2_run-instances.1"
        ans "ec2_run-instances.2" "i-up1"
        vb -- up --for X
        if [ "$VB_RC" != "0" ]; then
            bad "${code}: up exited ${VB_RC}"
            report
            continue
        fi
        [ "$(op_count 'ec2 run-instances')" = "2" ] || {
            bad "${code}: $(op_count 'ec2 run-instances') run-instances call(s), wanted 2"
            continue
        }
        local second
        second="$(nth_call_of "run-instances" 2 || true)"
        case "$second" in
        *--instance-market-options*) bad "${code}: the fallback still asked for spot" ;;
        *) ok "${code}: the second call has no market options" ;;
        esac
        out_has "market: on-demand (spot refused: ${code})" &&
            ok "${code}: the block says which market it paid for and why" ||
            bad "${code}: stdout does not say 'market: on-demand (spot refused: ${code})'"
        # Identical in every other argument — the diff is the market options and
        # nothing else. The two calls are found by CONTENT, because the call
        # numbers depend on how many describes happened first.
        local first="" second="" f
        for f in $(ls "$REC/calls" | grep '\.args$' | sort -t. -k1 -n); do
            grep -qxF -- "run-instances" "$REC/calls/$f" || continue
            if [ -z "$first" ]; then first="$REC/calls/$f"; elif [ -z "$second" ]; then second="$REC/calls/$f"; fi
        done
        if [ -z "$second" ]; then
            bad "${code}: could not find two recorded run-instances calls to compare"
        elif diff <(grep -vF -- "--instance-market-options" "$first" | grep -vF "MarketType=spot") \
            <(grep -vF -- "--instance-market-options" "$second" | grep -vF "MarketType=spot") >/dev/null 2>&1; then
            ok "${code}: the fallback is the same launch minus the market options"
        else
            bad "${code}: the fallback differs from the first call in more than the market options:
$(diff "$first" "$second" | sed 's/^/        /')"
        fi
    done
}

# THE ONE SPOT REFUSAL THAT IS NOT THE MARKET AND NOT THE CREDENTIAL. The first
# Spot `run-instances` in an account creates EC2's Spot service-linked role as a
# side effect, IF the caller may; the verifier ops user may not, by design — its
# policy grants no `iam:` write and `iam:CreateServiceLinkedRole` is one. So a
# fresh account answers `AuthFailure.ServiceLinkedRoleCreationNotPermitted`,
# having created nothing. Two real launches were aborted on it.
#
# IT IS NEITHER OF THE TWO BRANCHES BESIDE IT. Falling back to on-demand would
# pay on-demand money for every launch for ever and never say why; reading it as
# a credential error sends the operator to `aws configure` for a role. And the
# dotted code did not even reach a branch: `spot_error_code`'s pattern matched
# `(AuthFailure)` with the close paren straight after, so the dotted form matched
# nothing, the code came back empty, and a named one-line account prerequisite
# arrived as `run-instances failed (no error code)`.
case_the_spot_service_linked_role_refusal_is_named_as_the_prerequisite_it_is() {
    CURRENT=case_the_spot_service_linked_role_refusal_is_named_as_the_prerequisite_it_is
    world_new spot_slr
    world_up_ready
    printf 'An error occurred (AuthFailure.ServiceLinkedRoleCreationNotPermitted) when calling the RunInstances operation: The provided credentials do not have permission to create the service-linked role for EC2 Spot Instances.\n' \
        >"$REC/err/ec2_run-instances"
    printf '1\n' >"$REC/rc/ec2_run-instances"
    printf '' >"$REC/ans/ec2_run-instances"
    vb -- up --for X
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2, got ${VB_RC}"
        report
        return
    }
    [ "$(op_count 'ec2 run-instances')" = "1" ] && ok "exactly one run-instances — no on-demand fallback for a prerequisite" ||
        bad "$(op_count 'ec2 run-instances') run-instances calls: this was retried as if the market had said no"
    said "ACCOUNT PREREQUISITE" &&
        ok "it says the refusal is an account prerequisite, not capacity and not the credential" ||
        bad "the refusal reads as a credential fault: $(tr '\n' ' ' <"$W/err")"
    said "create-service-linked-role --aws-service-name spot.amazonaws.com" &&
        ok "and prints the one command that fixes it" ||
        bad "the refusal does not print the create command"
    said "verifier_bootstrap.sh" &&
        ok "and names the step that checks it, so the fix lands in the tree rather than in a shell history" ||
        bad "the refusal does not point at the bootstrap's own step"
    said "--on-demand" && ok "and offers the one-launch way past it" ||
        bad "the refusal does not offer --on-demand"
    # AND THE CODE WAS READ AT ALL, which is the half that was silently broken:
    # an unmatched code prints `no error code` and the operator learns nothing.
    if said "no error code"; then
        bad "the dotted code did not match the reader's pattern — it arrived as 'no error code'"
    else
        ok "the dotted code was read rather than falling through as 'no error code'"
    fi
}

case_on_demand_asked_for_is_one_call_with_no_market_options() {
    CURRENT=case_on_demand_asked_for_is_one_call_with_no_market_options
    world_new on_demand
    world_up_ready
    vb -- up --for X --on-demand
    [ "$VB_RC" = "0" ] || {
        bad "up exited ${VB_RC}"
        report
        return
    }
    [ "$(op_count 'ec2 run-instances')" = "1" ] && ok "exactly one run-instances" ||
        bad "$(op_count 'ec2 run-instances') run-instances calls for an --on-demand launch"
    local call
    call="$(nth_call_of "run-instances" 1 || true)"
    case "$call" in
    *--instance-market-options*) bad "--on-demand still asked for spot" ;;
    *) ok "no market options anywhere on the call" ;;
    esac
    out_has "market: on-demand (asked for)" && ok "the block says the market was asked for" ||
        bad "the block does not say why it is on-demand"
}

case_a_credential_error_is_exit_2_and_one_call() {
    CURRENT=case_a_credential_error_is_exit_2_and_one_call
    local code
    for code in UnauthorizedOperation ExpiredToken; do
        world_new "cred_${code}"
        world_up_ready
        printf 'An error occurred (%s) when calling the RunInstances operation\n' "$code" >"$REC/err/ec2_run-instances"
        printf '1\n' >"$REC/rc/ec2_run-instances"
        printf '' >"$REC/ans/ec2_run-instances"
        vb -- up --for X
        [ "$VB_RC" = "2" ] || {
            bad "${code}: wanted exit 2, got ${VB_RC}"
            report
            continue
        }
        [ "$(op_count 'ec2 run-instances')" = "1" ] || {
            bad "${code}: $(op_count 'ec2 run-instances') run-instances calls — a credential error must not be retried"
            continue
        }
        said "aws configure --profile ${NS}-verifier" &&
            ok "${code}: exit 2, one call, and the owner's commands printed" ||
            bad "${code}: the refusal does not print the owner's commands"
    done
}

# =============================================================================
# 1.3b — the on-demand valve, and the market EC2 reports
# =============================================================================

# THE BANK'S SHARDS ARE NOT A SINGLE VERIFIER, and the difference is money
# nobody asked for. Eight shards that each answer a Spot refusal with an
# on-demand box are eight on-demand boxes against a quota an order of magnitude
# smaller than the Spot one — which is how a bank came to have no boxes for six
# of its eight units and a bill for the two it did get.
case_a_bank_shard_never_falls_back_to_on_demand_silently() {
    CURRENT=case_a_bank_shard_never_falls_back_to_on_demand_silently
    world_new bank_shard_no_valve
    world_up_ready
    printf 'An error occurred (InsufficientInstanceCapacity) when calling the RunInstances operation\n' \
        >"$REC/err/ec2_run-instances.1"
    printf '1\n' >"$REC/rc/ec2_run-instances.1"
    printf '' >"$REC/ans/ec2_run-instances.1"
    ans "ec2_run-instances.2" "i-up1"
    vb DJB_VERIFIER_BANK_SHARD=1 -- up --for X
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2, got ${VB_RC}"
        report
        return
    }
    [ "$(op_count 'ec2 run-instances')" = "1" ] &&
        ok "exactly one run-instances — the on-demand launch never happened" ||
        bad "$(op_count 'ec2 run-instances') run-instances calls: the shard bought on-demand anyway"
    local miss=""
    said "InsufficientInstanceCapacity" || miss="${miss} the-spot-refusal"
    said "DJB_VERIFIER_ON_DEMAND_OK" || miss="${miss} the-valve"
    said "could not launch" || miss="${miss} could-not-launch"
    said "on-demand" || miss="${miss} the-market-it-would-have-bought"
    [ -z "$miss" ] && ok "the refusal names the Spot refusal, the market it declined to buy, and the valve" ||
        bad "the refusal is missing:${miss}"
}

case_a_bank_shard_with_the_valve_buys_on_demand_and_prints_the_reason() {
    CURRENT=case_a_bank_shard_with_the_valve_buys_on_demand_and_prints_the_reason
    world_new bank_shard_valve
    world_up_ready
    # The on-demand rate, answered the way the Price List API answers it: one
    # JSON document, with the hourly rate inside it.
    ans "pricing_get-products" '{"terms":{"OnDemand":{"a":{"priceDimensions":{"b":{"unit":"Hrs","pricePerUnit":{"USD":"0.5804000000"}}}}}}}'
    printf 'An error occurred (InsufficientInstanceCapacity) when calling the RunInstances operation\n' \
        >"$REC/err/ec2_run-instances.1"
    printf '1\n' >"$REC/rc/ec2_run-instances.1"
    printf '' >"$REC/ans/ec2_run-instances.1"
    ans "ec2_run-instances.2" "i-up1"
    vb DJB_VERIFIER_BANK_SHARD=1 \
        DJB_VERIFIER_ON_DEMAND_OK="the Spot pool is empty in this AZ and the wave has to finish today" \
        DJB_VERIFIER_PRICING_REGION="$RG" -- up --for X
    [ "$VB_RC" = "0" ] || {
        bad "up exited ${VB_RC} with the valve typed"
        report
        return
    }
    [ "$(op_count 'ec2 run-instances')" = "2" ] &&
        ok "the valve let the on-demand launch through" ||
        bad "$(op_count 'ec2 run-instances') run-instances call(s), wanted 2"
    said "the Spot pool is empty in this AZ and the wave has to finish today" &&
        ok "the reason is printed, so a bank's table can carry it" ||
        bad "the valve's reason was not printed"
    said "0.5804" && ok "and the on-demand rate it is about to pay is printed" ||
        bad "the fallback does not print the on-demand price: $(tr '\n' ' ' <"$W/out")"
}

# A SINGLE VERIFIER KEEPS THE FALLBACK, and that is the other half of the
# valve: one box for one rung is a decision an operator is standing in front
# of, and refusing it would turn a capacity blip into a stopped rung.
case_a_single_up_keeps_the_fallback_and_prints_the_price() {
    CURRENT=case_a_single_up_keeps_the_fallback_and_prints_the_price
    world_new single_up_fallback
    world_up_ready
    ans "pricing_get-products" '{"terms":{"OnDemand":{"a":{"priceDimensions":{"b":{"unit":"Hrs","pricePerUnit":{"USD":"0.5804000000"}}}}}}}'
    printf 'An error occurred (InsufficientInstanceCapacity) when calling the RunInstances operation\n' \
        >"$REC/err/ec2_run-instances.1"
    printf '1\n' >"$REC/rc/ec2_run-instances.1"
    printf '' >"$REC/ans/ec2_run-instances.1"
    ans "ec2_run-instances.2" "i-up1"
    vb DJB_VERIFIER_PRICING_REGION="$RG" -- up --for X
    [ "$VB_RC" = "0" ] || {
        bad "up exited ${VB_RC} — a single verifier keeps the fallback"
        report
        return
    }
    [ "$(op_count 'ec2 run-instances')" = "2" ] && ok "the fallback still launches for a single verifier" ||
        bad "$(op_count 'ec2 run-instances') run-instances call(s), wanted 2"
    said "0.5804" && ok "and it prints what the on-demand hour costs" ||
        bad "the fallback did not print the on-demand price"
}

# THE PRICE IS UNKNOWN UNLESS SOMEBODY NAMED THE REGION IT IS PUBLISHED IN, and
# an unknown price is SAID rather than left out. The Price List API lives in
# two regions and this wrapper guesses neither, for the reason every other
# coordinate here has no default.
case_an_unasked_price_is_printed_as_unknown_and_says_why() {
    CURRENT=case_an_unasked_price_is_printed_as_unknown_and_says_why
    world_new no_pricing_region
    world_up_ready
    printf 'An error occurred (InsufficientInstanceCapacity) when calling the RunInstances operation\n' \
        >"$REC/err/ec2_run-instances.1"
    printf '1\n' >"$REC/rc/ec2_run-instances.1"
    printf '' >"$REC/ans/ec2_run-instances.1"
    ans "ec2_run-instances.2" "i-up1"
    vb -- up --for X
    [ "$VB_RC" = "0" ] || {
        bad "up exited ${VB_RC}"
        report
        return
    }
    [ "$(op_count 'pricing get-products')" = "0" ] &&
        ok "no pricing call was made with no region to make it in" ||
        bad "the Price List API was asked in a region nobody named"
    said "DJB_VERIFIER_PRICING_REGION" &&
        ok "and the unknown price names the knob that would answer it" ||
        bad "the fallback does not say why the price is unknown"
}

# THE MARKET A BOX IS ON IS EC2'S ANSWER, NEVER THE WRAPPER'S MEMORY OF WHAT IT
# ASKED FOR. A launch that asked for Spot and got on-demand through the
# fallback, a box claimed warm out of the pool, a box somebody else launched —
# in all three the only honest source is `InstanceLifecycle`.
case_up_prints_the_market_ec2_reports_not_the_one_it_asked_for() {
    CURRENT=case_up_prints_the_market_ec2_reports_not_the_one_it_asked_for
    world_new up_market_spot
    world_up_ready
    vb -- up --for X
    [ "$VB_RC" = "0" ] || {
        bad "up exited ${VB_RC}"
        report
        return
    }
    out_has "market     spot" && ok "the market line reads spot, from EC2's own InstanceLifecycle" ||
        bad "no 'market     spot' line: $(tr '\n' ' ' <"$W/out")"
    # ASKED FOR IN THE LAUNCH'S OWN QUERY, which is where it moved to: a
    # describe on an id seconds old can answer NotFound, and the swallowed
    # transient printed `market on-demand` over a Spot box.
    local q
    q="$(nth_call_of "run-instances" 1 || true)"
    case "$q" in
    *"Placement.AvailabilityZone,InstanceLifecycle"*)
        ok "and both are asked for in the LAUNCH's own query rather than inferred or re-described" ;;
    *) bad "the launch query does not carry the placement and the lifecycle: ${q}" ;;
    esac

    world_new up_market_on_demand
    world_up_ready
    # EC2 says NOTHING for an on-demand instance and `--output text` prints that
    # nothing as `None`. The absence IS the answer, and reading it as one is the
    # difference between "on-demand" and "unknown". On the launch's own answer
    # the request id is absent for the same reason and the ZONE is still there
    # — which is what lets an empty lifecycle beside a zone mean `on-demand`
    # rather than "the answer did not say".
    ans "ec2_run-instances" "$(printf 'i-up1\tNone\t%sc\tNone' "$RG")"
    vb -- up --for X --on-demand
    [ "$VB_RC" = "0" ] || {
        bad "on-demand up exited ${VB_RC}"
        report
        return
    }
    out_has "market     on-demand" && ok "an absent lifecycle reads as on-demand" ||
        bad "no 'market     on-demand' line: $(tr '\n' ' ' <"$W/out")"
}

# =============================================================================
# 1.3c — harvest-drives: the rows a shard banked, with no loop row to hang them on
# =============================================================================

# WHY THE SUBCOMMAND EXISTS AT ALL. `harvest <id> <name>` brings a box's LOOP
# verdict home and carries the drive rows beside it — but a bank's shard runs
# `--leg`, which banks no loop row by design, so `harvest` refuses it and the
# rows that shard just paid for die with the box. This door reaches the same
# `harvest_drive_rows` with the tree named instead of read out of a verdict,
# so a bank can bring its shards' cache home before it terminates them.
case_harvest_drives_brings_the_boxs_rows_home_once() {
    CURRENT=case_harvest_drives_brings_the_boxs_rows_home_once
    world_new harvest_drives
    # The state the reclaim check reads, and the per-box key the transport
    # needs — a box with no key beside it is a box this wrapper will not ssh
    # to, which is a refusal about a different thing.
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
    printf 'a-rung\n' >"$W/vhome/i-up1/rung"
    local ledger tree
    tree="$MAIN_SHA"
    ledger="$W/verdicts"
    : >"$ledger"
    # The box's own ledger, over the transport: two rows at this tree, one at
    # another tree, and one `full` row that must never travel.
    {
        printf 'v1 drive-v1:aaa drive 2026-09-18T00:00:00Z selftest exit=0 took=3 tree=%s parts=scripts/tests/test_a.sh\n' "$tree"
        printf 'v1 drive-v1:bbb drive 2026-09-18T00:00:01Z sweep exit=0 took=4 tree=%s parts=scripts/tests/test_b.sh\n' "$tree"
        printf 'v1 drive-v1:ccc drive 2026-09-18T00:00:02Z sweep exit=0 took=4 tree=%s parts=scripts/tests/test_b.sh\n' "0000000000000000000000000000000000000000"
        printf 'v1 %s full 2026-09-18T00:00:03Z static,pytest caller=pm-bank\n' "$tree"
    } >"$REC/ssh/1.out"
    vb DJB_GATE_LEDGER="$ledger" -- harvest-drives i-up1 "$tree"
    [ "$VB_RC" = "0" ] || {
        bad "harvest-drives exited ${VB_RC}"
        report
        return
    }
    local n
    n="$(grep -c . "$ledger" 2>/dev/null || true)"
    [ "$n" = "2" ] && ok "the two rows at this tree came home, and only they" ||
        bad "${n} row(s) landed, wanted 2: $(tr '\n' '|' <"$ledger")"
    grep -F " full " "$ledger" >/dev/null 2>&1 &&
        bad "a full row travelled — a box's whole-tree verdict is not a cache anybody may reuse" ||
        ok "no full row travelled"
    said "drive rows: 2 brought home" && ok "and it says how many, and from where" ||
        bad "it does not say how many rows came home"

    # AND A SECOND HARVEST APPENDS NOTHING. The rows are a cache keyed on the
    # drive and the machine; a second copy of one is a second answer to a
    # question that already has one.
    printf 'Online\n' >"$REC/ans/ssm_describe-instance-information.3"
    cp "$REC/ssh/1.out" "$REC/ssh/2.out"
    vb DJB_GATE_LEDGER="$ledger" -- harvest-drives i-up1 "$tree"
    n="$(grep -c . "$ledger" 2>/dev/null || true)"
    [ "$n" = "2" ] && ok "a second harvest appended nothing" ||
        bad "${n} row(s) after a second harvest, wanted 2"
    said "(2 already here)" && ok "and says they were already here" ||
        bad "the second harvest does not say the rows were already here"
}

case_harvest_drives_without_a_tree_is_refused() {
    CURRENT=case_harvest_drives_without_a_tree_is_refused
    world_new harvest_drives_no_tree
    vb -- harvest-drives i-up1
    [ "$VB_RC" = "2" ] && ok "exit 2 with no tree to filter on" ||
        bad "wanted exit 2, got ${VB_RC}"
    said "harvest-drives takes" && ok "and it says the form" ||
        bad "the refusal does not print the form"
}

case_census_prints_the_market_each_box_is_on() {
    CURRENT=case_census_prints_the_market_each_box_is_on
    world_new census_market
    local future
    future="$(python3 -c 'import datetime;print((datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ"))')"
    printf 'i-spot\tc7g.4xlarge\tverifier\t%s\t%s\t2026-09-15T10:00:00.000Z\tami-baked-7\tspot\ni-cash\tc7g.4xlarge\tverifier\t%s\t%s\t2026-09-15T10:00:00.000Z\tami-baked-7\tNone\n' \
        "$OWNER" "$future" "$OWNER" "$future" \
        >"$REC/ans/ec2_describe-instances__ReservationsInstancesInstanceIdInstance"
    vb -- census
    [ "$VB_RC" = "0" ] || {
        bad "census exited ${VB_RC}"
        report
        return
    }
    grep -E '^i-spot .*market spot' "$W/out" >/dev/null 2>&1 &&
        ok "the Spot box's line says spot" ||
        bad "the Spot box's census line has no market: $(grep '^i-spot' "$W/out" || true)"
    grep -E '^i-cash .*market on-demand' "$W/out" >/dev/null 2>&1 &&
        ok "the box EC2 reports no lifecycle for reads as on-demand" ||
        bad "the on-demand box's census line has no market: $(grep '^i-cash' "$W/out" || true)"
    local q
    q="$(nth_call_of "describe-instances" 1 || true)"
    case "$q" in
    *InstanceLifecycle*) ok "and the census reads it out of the query, never from a tag it wrote itself" ;;
    *) bad "the census query does not read InstanceLifecycle: ${q}" ;;
    esac
}

# =============================================================================
# 1.4 — the ceiling
# =============================================================================

case_the_box_ceiling_refuses_before_the_call() {
    CURRENT=case_the_box_ceiling_refuses_before_the_call
    world_new ceiling
    world_up_ready
    ans "ec2_describe-instances__ReservationsInstancesInstanceId" "i-a	i-b"
    vb -- up --for X
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2, got ${VB_RC}"
        report
        return
    }
    [ "$(op_count 'ec2 run-instances')" = "0" ] && ok "nothing was launched" ||
        bad "the ceiling was converted into an on-demand launch"
    local miss=""
    said "i-a" || miss="${miss} i-a"
    said "i-b" || miss="${miss} i-b"
    said "L-34B43A08" || miss="${miss} the-quota-code"
    [ -z "$miss" ] && ok "the refusal names both boxes and the quota it derives from" ||
        bad "the refusal does not name:${miss}"
}

case_a_raised_ceiling_launches() {
    CURRENT=case_a_raised_ceiling_launches
    world_new ceiling_raised
    world_up_ready
    ans "ec2_describe-instances__ReservationsInstancesInstanceId" "i-a	i-b"
    vb DJB_VERIFIER_MAX_BOXES=3 -- up --for X
    [ "$VB_RC" = "0" ] || {
        bad "up exited ${VB_RC} with the ceiling raised"
        report
        return
    }
    [ "$(op_count 'ec2 run-instances')" = "1" ] && ok "the raised ceiling launches, once" ||
        bad "$(op_count 'ec2 run-instances') run-instances calls"
}

# --- the ceiling FILE, and the precedence above it ---------------------------
#
# WHY THESE CASES EXIST. The ceiling was one environment variable, and an
# environment variable is per-shell: fifteen builders in one cycle each got the
# default 2, waited 20-45 minutes at it, and the one form that would have
# raised it — an inline `DJB_VERIFIER_MAX_BOXES=… ./scripts/verifier_box.sh` —
# costs an agent a permission-classifier turn. The number that governs one
# machine now lives in one file on that machine, and these cases pin the
# precedence, the refusal that has to explain it, and the subcommand that reads
# and writes it.

plant_ceiling_file() { printf '%s\n' "$1" >"$W/vhome/ceiling"; }

case_the_ceiling_is_read_from_the_file_when_the_env_is_unset() {
    CURRENT=case_the_ceiling_is_read_from_the_file_when_the_env_is_unset
    world_new ceiling_file
    world_up_ready
    ans "ec2_describe-instances__ReservationsInstancesInstanceId" "i-a	i-b"
    plant_ceiling_file 3
    vb -- up --for X
    [ "$VB_RC" = "0" ] || {
        bad "up exited ${VB_RC} with a ceiling file of 3 and two boxes running"
        report
        return
    }
    [ "$(op_count 'ec2 run-instances')" = "1" ] &&
        ok "the file raised the ceiling past the default 2 with no variable in the environment" ||
        bad "$(op_count 'ec2 run-instances') run-instances call(s)"

    # AND THE FILE CAN BIND DOWNWARDS TOO, which is the half that proves the
    # file is read rather than merely tolerated: a file of 2 with two boxes up
    # refuses, and the refusal says the FILE is what bound.
    world_new ceiling_file_binds
    world_up_ready
    ans "ec2_describe-instances__ReservationsInstancesInstanceId" "i-a	i-b"
    plant_ceiling_file 2
    vb -- up --for X
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2 at a ceiling file of 2, got ${VB_RC}"
        report
        return
    }
    said "ceiling is 2 (file)" && ok "and a ceiling the file set refuses AS the file" ||
        bad "the refusal does not name the file as the source: $(cat "$W/err")"
    [ "$(op_count 'ec2 run-instances')" = "0" ] && ok "nothing was launched" ||
        bad "the file's ceiling was converted into a launch"
}

case_the_env_ceiling_wins_over_the_file() {
    CURRENT=case_the_env_ceiling_wins_over_the_file
    # THE VARIABLE IS THE TOP OF THE PRECEDENCE, both directions. Down: a file
    # of 9 and a variable of 2 refuses at 2. Up: a file of 2 and a variable of
    # 9 launches. One direction alone is satisfied by a wrapper that ignores
    # one of the two inputs.
    world_new ceiling_env_down
    world_up_ready
    ans "ec2_describe-instances__ReservationsInstancesInstanceId" "i-a	i-b"
    plant_ceiling_file 9
    vb DJB_VERIFIER_MAX_BOXES=2 -- up --for X
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2 with the variable at 2 over a file of 9, got ${VB_RC}"
        report
        return
    }
    said "ceiling is 2 (env)" && ok "the variable wins over the file, and the refusal says which won" ||
        bad "the refusal does not name env as the source: $(cat "$W/err")"
    said "9" && ok "and the losing file's number is printed too — the operator can see what it overrode" ||
        bad "the refusal hides the file's 9: $(cat "$W/err")"
    [ "$(op_count 'ec2 run-instances')" = "0" ] && ok "nothing was launched" ||
        bad "something was launched above the variable's ceiling"

    world_new ceiling_env_up
    world_up_ready
    ans "ec2_describe-instances__ReservationsInstancesInstanceId" "i-a	i-b"
    plant_ceiling_file 2
    vb DJB_VERIFIER_MAX_BOXES=9 -- up --for X
    [ "$VB_RC" = "0" ] || {
        bad "up exited ${VB_RC} with the variable at 9 over a file of 2"
        report
        return
    }
    [ "$(op_count 'ec2 run-instances')" = "1" ] &&
        ok "and a variable above a lower file launches — the file is not a second ceiling" ||
        bad "$(op_count 'ec2 run-instances') run-instances call(s)"
}

case_the_ceiling_refusal_names_all_three_and_the_one_that_bound() {
    CURRENT=case_the_ceiling_refusal_names_all_three_and_the_one_that_bound
    world_new ceiling_refusal_sources
    world_up_ready
    ans "ec2_describe-instances__ReservationsInstancesInstanceId" "i-a	i-b"
    vb -- up --for X
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2, got ${VB_RC}"
        report
        return
    }
    local miss=""
    said "ceiling is 2 (default)" || miss="${miss} the-binding-source"
    said "DJB_VERIFIER_MAX_BOXES  unset" || miss="${miss} env-unset"
    said "/ceiling  absent" || miss="${miss} file-absent"
    said "default  2" || miss="${miss} the-default"
    said "-> default" || miss="${miss} the-arrow"
    [ -z "$miss" ] &&
        ok "the refusal prints env, file and default, and marks the one that bound" ||
        bad "the refusal does not carry:${miss}
$(cat "$W/err")"
    said "L-34B43A08" && ok "and the Spot vCPU quota the ceiling stands for is still named" ||
        bad "the refusal dropped the quota code"
    [ "$(op_count 'ec2 run-instances')" = "0" ] && ok "nothing was launched" ||
        bad "the ceiling was converted into a launch"
}

case_ceiling_prints_the_file_the_env_and_the_quota() {
    CURRENT=case_ceiling_prints_the_file_the_env_and_the_quota
    world_new ceiling_read
    ans "service-quotas_get-service-quota" "32.0"
    vb -- ceiling
    [ "$VB_RC" = "0" ] || {
        bad "ceiling exited ${VB_RC} on a machine with no file and no variable"
        report
        return
    }
    local miss=""
    out_has "ceiling 2 (default)" || miss="${miss} the-verdict"
    out_has "DJB_VERIFIER_MAX_BOXES  unset" || miss="${miss} env"
    out_has "/ceiling  absent" || miss="${miss} file"
    out_has "default  2" || miss="${miss} default"
    out_has "L-34B43A08  32.0" || miss="${miss} quota"
    [ -z "$miss" ] &&
        ok "ceiling prints the variable, the file, the default and the account's Spot vCPU quota" ||
        bad "ceiling does not print:${miss}
$(cat "$W/out")"

    # THE WRITE, AND IT IS THE SAME SUBCOMMAND. A write that did not show its
    # result is a write the operator verifies with a second command.
    world_new ceiling_write
    ans "service-quotas_get-service-quota" "32.0"
    vb -- ceiling 6
    [ "$VB_RC" = "0" ] || {
        bad "ceiling 6 exited ${VB_RC}"
        report
        return
    }
    [ "$(cat "$W/vhome/ceiling" 2>/dev/null || true)" = "6" ] &&
        ok "ceiling <n> writes the one integer into DJB_VERIFIER_HOME" ||
        bad "the ceiling file holds '$(cat "$W/vhome/ceiling" 2>/dev/null || echo '<nothing>')'"
    out_has "wrote " && out_has "ceiling 6 (file)" &&
        ok "and prints what it wrote and the ceiling that now binds" ||
        bad "the write does not print its result: $(cat "$W/out")"

    # AND THE VARIABLE STILL WINS OVER THE FILE IT JUST WROTE.
    vb DJB_VERIFIER_MAX_BOXES=4 -- ceiling
    out_has "ceiling 4 (env)" && out_has "/ceiling  6" &&
        ok "a later read under a variable says env binds and still shows the file's 6" ||
        bad "the read under a variable is not the shape the design states: $(cat "$W/out")"

    # A QUOTA IT CANNOT LOOK AT IS `unknown` AND NEVER A BLOCK. The credential
    # that reads a quota is not the credential that reads a local integer.
    world_new ceiling_quota_blind
    rcf "service-quotas_get-service-quota" 255
    errf "service-quotas_get-service-quota" "An error occurred (AccessDeniedException)"
    vb -- ceiling
    [ "$VB_RC" = "0" ] && ok "a quota it cannot read is not a refusal" ||
        bad "ceiling exited ${VB_RC} because the quota could not be read"
    out_has "L-34B43A08  unknown" && out_has "could not look" &&
        ok "and it prints unknown and says so, rather than a number nobody measured" ||
        bad "the unreadable quota is not printed as unknown: $(cat "$W/out")"
}

case_a_ceiling_file_that_is_not_a_number_is_exit_2_before_any_call() {
    CURRENT=case_a_ceiling_file_that_is_not_a_number_is_exit_2_before_any_call
    # A CEILING THAT CANNOT BE READ IS NOT A CEILING OF 2. The file is the wall
    # between this loop and an unbounded Spot bill; a fat-fingered `1O` that
    # quietly became the default would be a wave of one box, and a `1O` read as
    # ten would be a bill nobody chose.
    world_new ceiling_garbage
    world_up_ready
    plant_ceiling_file "1O"
    vb -- up --for X
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2 on a malformed ceiling file, got ${VB_RC}"
        report
        return
    }
    [ ! -f "$REC/aws.ops" ] && ok "exit 2 before a single AWS call" ||
        bad "a malformed ceiling file still reached AWS: $(ops)"
    said "1O" && said "/ceiling" &&
        ok "and the refusal shows the text it could not read and the file it came out of" ||
        bad "the refusal does not name the file and its contents: $(cat "$W/err")"

    # THE SAME RULE FOR THE VARIABLE, so neither input has a silent path.
    world_new ceiling_garbage_env
    world_up_ready
    vb DJB_VERIFIER_MAX_BOXES=lots -- up --for X
    [ "$VB_RC" = "2" ] && ok "a malformed variable is exit 2 too" ||
        bad "DJB_VERIFIER_MAX_BOXES=lots exited ${VB_RC}"
    [ ! -f "$REC/aws.ops" ] && ok "and nothing was asked of AWS" ||
        bad "a malformed variable still reached AWS: $(ops)"
}

case_census_prints_the_ceiling_beside_the_pool() {
    CURRENT=case_census_prints_the_ceiling_beside_the_pool
    # "CAN I HAVE A BOX RIGHT NOW" IS `ceiling - running`, and the census is
    # where the running boxes are counted — so the wall belongs on the same
    # page. It was not there, and the wall nobody could see was the default 2.
    world_new census_ceiling
    local now exp
    now="$(cat "$REC/clock")"
    exp="$(iso_utc $((now + 3600)))"
    printf 'i-c1\tc7g.4xlarge\tverifier\t%s\t%s\t%s\tami-v1\n' \
        "$OWNER" "$exp" "$(iso_utc $((now - 300)))" \
        >"$REC/ans/ec2_describe-instances__ReservationsInstancesInstanceIdInstance"
    plant_ceiling_file 8
    vb -- census
    [ "$VB_RC" = "0" ] || {
        bad "census exited ${VB_RC}"
        report
        return
    }
    out_has "ceiling 8 (file) · pool: empty" &&
        ok "an empty pool still prints the ceiling and where it came from" ||
        bad "the census's empty-pool line is not the shape the design states: $(cat "$W/out")"

    pool_listing "$(pool_row i-w1 30 ami-v1 0.2085)"
    vb DJB_VERIFIER_MAX_BOXES=5 -- census
    out_has "ceiling 5 (env) · pool: 1 warm · \$0.2085/h" &&
        ok "and a pool line carries the ceiling, its source and the cost together" ||
        bad "the census's pool line is not the shape the design states: $(cat "$W/out")"
}

# =============================================================================
# 1.5 — down
# =============================================================================

world_tagged() {
    # role, namespace — the two tags `down` reads before it terminates anything,
    # AND the state it reads them out of. `terminate_one` asks ONE describe for
    # all four now (an API error and a vanished instance both answered `None`
    # through two `tag_of` calls, and the wrapper called a reclaimed box
    # somebody else's), so the fixture is one four-column answer and a case
    # that wants a gone box plants the state rather than a missing tag.
    ans "ec2_describe-instances__Reservations0Instances0StateNameStateRea" \
        "$(printf 'running\tNone\t%s\t%s' "$1" "$2")"
}

case_down_refuses_an_instance_that_is_not_ours() {
    CURRENT=case_down_refuses_an_instance_that_is_not_ours
    world_new down_foreign
    world_tagged "None" "None"
    vb -- down i-environment
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2, got ${VB_RC}"
        report
        return
    }
    said "not a verifier box" && ok "exit 2, 'not a verifier box'" ||
        bad "the refusal does not say 'not a verifier box'"
    [ "$(op_count 'ec2 terminate-instances')" = "0" ] && ok "nothing terminated" ||
        bad "terminate-instances was called on an untagged instance"
}

case_down_refuses_another_namespaces_box() {
    CURRENT=case_down_refuses_another_namespaces_box
    world_new down_other_ns
    world_tagged "verifier" "someone-else"
    vb -- down i-theirs
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2, got ${VB_RC}"
        report
        return
    }
    said "someone-else" && ok "exit 2 naming the namespace it belongs to" ||
        bad "the refusal does not name the other namespace"
    [ "$(op_count 'ec2 terminate-instances')" = "0" ] && ok "nothing terminated" ||
        bad "one product's wrapper terminated another product's box"
}

case_down_terminates_and_takes_the_private_key_with_it() {
    CURRENT=case_down_terminates_and_takes_the_private_key_with_it
    world_new down_ok
    world_tagged "verifier" "$NS"
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
    vb -- down i-up1
    [ "$VB_RC" = "0" ] || {
        bad "down exited ${VB_RC}"
        report
        return
    }
    [ "$(op_count 'ec2 terminate-instances')" = "1" ] && ok "exactly one terminate-instances" ||
        bad "$(op_count 'ec2 terminate-instances') terminate-instances calls"
    local call
    call="$(nth_call_of "terminate-instances" 1 || true)"
    case "$call" in
    *"--instance-ids i-up1"*"--region ${RG}"* | *"--region ${RG}"*"--instance-ids i-up1"*)
        ok "the terminate names the instance and carries the region" ;;
    *) bad "the terminate call is '${call}'" ;;
    esac
    [ -d "$W/vhome/i-up1" ] && bad "the box's private key survived its own box" ||
        ok "the per-box directory and its private key are gone"
    out_has "terminated i-up1" && ok "it says what it did" || bad "stdout does not say 'terminated i-up1'"
}

case_down_all_mine_leaves_other_owners_alone() {
    CURRENT=case_down_all_mine_leaves_other_owners_alone
    world_new down_all_mine
    ans "ec2_describe-instances__ReservationsInstancesInstanceId" "i-mine1	i-mine2	i-theirs"
    # Owner answers in call order: the wrapper asks per instance.
    ansf "ec2_describe-instances__Reservations0Instances0TagsKeydjbowner" "$OWNER"
    printf '%s\n' "$OWNER" >"$REC/ans/ec2_describe-instances__Reservations0Instances0TagsKeydjbowner.1"
    printf '%s\n' "$OWNER" >"$REC/ans/ec2_describe-instances__Reservations0Instances0TagsKeydjbowner.2"
    printf 'another-session\n' >"$REC/ans/ec2_describe-instances__Reservations0Instances0TagsKeydjbowner.3"
    world_tagged "verifier" "$NS"
    vb -- down --all-mine
    [ "$VB_RC" = "0" ] || {
        bad "down --all-mine exited ${VB_RC}"
        report
        return
    }
    [ "$(op_count 'ec2 terminate-instances')" = "2" ] && ok "exactly the two boxes this session owns" ||
        bad "$(op_count 'ec2 terminate-instances') terminate-instances calls, wanted 2"
    said "i-theirs" && said "another-session" &&
        ok "the one it left is named with its owner" ||
        bad "it does not say which box it left, or whose it is"
}

# =============================================================================
# 1.6 — census
# =============================================================================

case_census_says_nothing_when_there_is_nothing() {
    CURRENT=case_census_says_nothing_when_there_is_nothing
    world_new census_empty
    ans "ec2_describe-instances__ReservationsInstancesInstanceIdInstance" ""
    vb -- census
    [ "$VB_RC" = "0" ] || {
        bad "wanted exit 0, got ${VB_RC}"
        report
        return
    }
    out_has "no verifier boxes" && out_has "$RG" && out_has "${NS}-verifier" &&
        ok "exit 0 and 'no verifier boxes' naming the region, the profile and the namespace" ||
        bad "the empty answer does not name where it looked: '$(head -n 1 "$W/out")'"
}

case_census_finds_an_overdue_box_and_that_is_a_finding() {
    CURRENT=case_census_finds_an_overdue_box_and_that_is_a_finding
    world_new census_overdue
    local past future
    past="$(python3 -c 'import datetime;print((datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(minutes=17)).strftime("%Y-%m-%dT%H:%M:%SZ"))')"
    future="$(python3 -c 'import datetime;print((datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ"))')"
    printf 'i-ok\tc7g.4xlarge\tverifier\t%s\t%s\t2026-09-15T10:00:00.000Z\ni-late\tc7g.4xlarge\tverifier\t%s\t%s\t2026-09-15T10:00:00.000Z\n' \
        "$OWNER" "$future" "$OWNER" "$past" \
        >"$REC/ans/ec2_describe-instances__ReservationsInstancesInstanceIdInstance"
    vb -- census
    [ "$VB_RC" = "1" ] || {
        bad "wanted exit 1 (a finding), got ${VB_RC}"
        report
        return
    }
    ok "exit 1 — a finding, not a refusal and not a pass"
    out_has "OVERDUE" && ok "the overdue box is marked" || bad "no OVERDUE marker"
    out_has "the reaper did not fire; down it" && ok "the line says what to do about it" ||
        bad "the OVERDUE line does not say what to do"
    local n
    n="$(grep -c "^i-" "$W/out" || true)"
    [ "$n" = "2" ] && ok "both boxes listed" || bad "${n} box line(s), wanted 2"
}

case_census_flags_a_bake_box_that_outlived_its_bake() {
    CURRENT=case_census_flags_a_bake_box_that_outlived_its_bake
    world_new census_stale_bake
    local future old
    future="$(python3 -c 'import datetime;print((datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))')"
    old="$(python3 -c 'import datetime;print((datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(minutes=120)).strftime("%Y-%m-%dT%H:%M:%S.000Z"))')"
    printf 'i-bake\tc7g.2xlarge\tverifier-bake\t%s\t%s\t%s\n' "$OWNER" "$future" "$old" \
        >"$REC/ans/ec2_describe-instances__ReservationsInstancesInstanceIdInstance"
    vb -- census
    [ "$VB_RC" = "1" ] || {
        bad "wanted exit 1, got ${VB_RC}"
        report
        return
    }
    out_has "STALE BAKE" && ok "exit 1 and the bake box is flagged" ||
        bad "a two-hour-old bake box was not flagged"
}

case_census_that_cannot_look_is_exit_2() {
    CURRENT=case_census_that_cannot_look_is_exit_2
    world_new census_denied
    printf 'An error occurred (AccessDenied) when calling the DescribeInstances operation\n' \
        >"$REC/ans/ec2_describe-instances__ReservationsInstancesInstanceIdInstance"
    printf '255\n' >"$REC/rc/ec2_describe-instances__ReservationsInstancesInstanceIdInstance"
    vb -- census
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2, got ${VB_RC}"
        report
        return
    }
    said "could not look" && ok "exit 2 and it says it could not look" ||
        bad "the refusal does not say 'could not look' — a census that cannot tell nothing from blind is the column this repository refuses"
    said "aws configure --profile ${NS}-verifier" && ok "the owner's commands are printed" ||
        bad "the refusal does not print the owner's commands"
}

# =============================================================================
# 1.6b — the warm pool: `pool`, the claim inside `up`, and the census section
# =============================================================================
#
# THE POOL IS PER MACHINE BY CONSTRUCTION, and every case below rests on that:
# the private half of a box's key never leaves the machine that launched it, so
# a candidate with no key under this machine's VERIFIER_HOME is not a candidate
# at all. That is the exit sentence in the wrapper's header, and it is why the
# claim's lock is a local `mkdir` rather than a tag.

case_pool_launches_the_difference_with_the_pool_tags() {
    CURRENT=case_pool_launches_the_difference_with_the_pool_tags
    world_new pool_launch
    world_pool_ready
    printf 'i-p1\n' >"$REC/ans/ec2_run-instances.1"
    printf 'i-p2\n' >"$REC/ans/ec2_run-instances.2"
    vb -- pool --want 2
    [ "$VB_RC" = "0" ] || {
        bad "pool exited ${VB_RC}"
        report
        return
    }
    [ "$(op_count 'ec2 run-instances')" = "2" ] && ok "an empty pool of 2 launches exactly 2" ||
        bad "$(op_count 'ec2 run-instances') run-instances call(s), wanted 2"
    local n call tagged=0 priced=0 i
    for i in 1 2; do
        call="$(nth_call_of "run-instances" "$i" || true)"
        case "$call" in *"Key=djb:for,Value=pool"*) tagged=$((tagged + 1)) ;; esac
        case "$call" in *"Key=djb:price,Value=0.2085"*) priced=$((priced + 1)) ;; esac
    done
    [ "$tagged" = "2" ] && ok "both launches carry djb:for=pool — which is what makes them findable as warm" ||
        bad "${tagged}/2 launches carry djb:for=pool"
    [ "$priced" = "2" ] && ok "both carry djb:price read at launch, so the census never has to compute one" ||
        bad "${priced}/2 launches carry djb:price"
    out_has "pool: 0 warm · 2 launched · 0 trimmed · \$0.4170/h" &&
        ok "the line states what it found, what it did, and what the pool now costs an hour" ||
        bad "the pool line is not the shape the design states: $(cat "$W/out")"
    local keyed=0
    for i in i-p1 i-p2; do
        [ -r "$W/vhome/${i}/id_ed25519" ] && keyed=$((keyed + 1))
    done
    [ "$keyed" = "2" ] && ok "each launched box's private half stays on this machine — the pool is per machine" ||
        bad "${keyed}/2 launched boxes have a key under this machine's VERIFIER_HOME"
}

case_pool_trims_only_unclaimed_boxes() {
    CURRENT=case_pool_trims_only_unclaimed_boxes
    # THREE WARM, THE MIDDLE ONE CLAIMED, AND A WANT OF TWO. One trim is due and
    # the OLDEST UNCLAIMED box is the one that must take it — the claimed one is
    # somebody's verification in flight.
    world_new pool_trim_oldest
    world_pool_ready
    pool_listing \
        "$(pool_row i-w1 90 ami-v1 0.2085)" \
        "$(pool_row i-w2 60 ami-v1 0.2085)" \
        "$(pool_row i-w3 30 ami-v1 0.2085)"
    mkdir -p "$W/vhome/i-w1" "$W/vhome/i-w2/claim" "$W/vhome/i-w3"
    vb -- pool --want 2
    [ "$VB_RC" = "0" ] || {
        bad "pool exited ${VB_RC}"
        report
        return
    }
    local terminated f
    terminated="$(for f in "$REC"/calls/*.flat; do
        grep -q 'terminate-instances' "$f" 2>/dev/null && grep -o 'i-w[0-9]' "$f"
    done | sort | tr '\n' ' ')"
    [ "$terminated" = "i-w1 " ] && ok "exactly the oldest UNCLAIMED box was trimmed" ||
        bad "terminate-instances reached '${terminated}', wanted 'i-w1 '"
    out_has "pool: 3 warm · 0 launched · 1 trimmed" && ok "the line states the trim" ||
        bad "the pool line does not state the trim: $(cat "$W/out")"

    # AND THE CRITERION'S OWN SHAPE: three warm, one claimed, a want of one.
    # Both unclaimed boxes go and the claimed one is never in a terminate argv.
    world_new pool_trim_claimed
    world_pool_ready
    pool_listing \
        "$(pool_row i-w1 90 ami-v1 0.2085)" \
        "$(pool_row i-w2 60 ami-v1 0.2085)" \
        "$(pool_row i-w3 30 ami-v1 0.2085)"
    mkdir -p "$W/vhome/i-w1" "$W/vhome/i-w2/claim" "$W/vhome/i-w3"
    vb -- pool --want 1
    [ "$VB_RC" = "0" ] || {
        bad "pool exited ${VB_RC}"
        report
        return
    }
    terminated="$(for f in "$REC"/calls/*.flat; do
        grep -q 'terminate-instances' "$f" 2>/dev/null && grep -o 'i-w[0-9]' "$f"
    done | sort | tr '\n' ' ')"
    case "$terminated" in
    *i-w2*) bad "a CLAIMED box was terminated — that is somebody's verification: '${terminated}'" ;;
    *) ok "the claimed box is never in a terminate-instances argv" ;;
    esac
    [ "$terminated" = "i-w1 i-w3 " ] && ok "both unclaimed boxes were trimmed, oldest first" ||
        bad "terminate-instances reached '${terminated}', wanted 'i-w1 i-w3 '"
}

case_pool_above_the_ceiling_is_exit_2_before_any_call() {
    CURRENT=case_pool_above_the_ceiling_is_exit_2_before_any_call
    world_new pool_ceiling
    world_pool_ready
    vb -- pool --want 5
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2, got ${VB_RC}"
        report
        return
    }
    [ ! -f "$REC/aws.ops" ] && ok "exit 2 before a single AWS call — a ceiling discovered after the launch is money" ||
        bad "the ceiling was checked after $(op_count '.') AWS call(s): $(ops)"
    said "DJB_VERIFIER_MAX_BOXES" && ok "the refusal names the knob" ||
        bad "the refusal does not name DJB_VERIFIER_MAX_BOXES"
    said "L-34B43A08" && ok "and the Spot vCPU quota the knob stands for" ||
        bad "the refusal does not name the quota code"
    [ "$(op_count 'ec2 run-instances')" = "0" ] && ok "nothing was launched" ||
        bad "something was launched above the ceiling"
}

case_a_pool_launch_carries_its_idle_threshold() {
    CURRENT=case_a_pool_launch_carries_its_idle_threshold
    world_new pool_idle
    world_pool_ready
    printf 'i-p1\n' >"$REC/ans/ec2_run-instances"
    vb -- pool --want 1 --idle 7
    [ "$VB_RC" = "0" ] || {
        bad "pool exited ${VB_RC}"
        report
        return
    }
    local call n
    call="$(nth_call_of "run-instances" 1 || true)"
    case "$call" in
    *"/etc/verifier/idle-minutes"*) ok "the pool launch's user-data writes the idle threshold" ;;
    *) bad "the pool launch's user-data has no idle-minutes file" ;;
    esac
    n="$(printf '%s' "$call" | grep -c 'content: "7"' || true)"
    [ "$n" -ge 1 ] && ok "the seam rendered the typed idle of 7 minutes — the reaper is what empties the pool" ||
        bad "the rendered user-data does not carry the typed idle value"
}

case_up_claims_a_warm_box_and_launches_nothing() {
    CURRENT=case_up_claims_a_warm_box_and_launches_nothing
    world_new up_claims
    world_up_ready
    pool_listing "$(pool_row i-w1 12 ami-v1 0.2085)"
    mkdir -p "$W/vhome/i-w1"
    printf 'key\n' >"$W/vhome/i-w1/id_ed25519"
    vb -- up --for V-boxpool
    [ "$VB_RC" = "0" ] || {
        bad "up exited ${VB_RC}"
        report
        return
    }
    [ "$(op_count 'ec2 run-instances')" = "0" ] && ok "a warm box was claimed and nothing was launched" ||
        bad "$(op_count 'ec2 run-instances') run-instances call(s) with a warm box available"
    out_has "claimed i-w1 (warm, 12m)" && ok "it says which box it claimed and how warm it was" ||
        bad "the claim is not announced in the shape the design states: $(cat "$W/out")"
    [ -d "$W/vhome/i-w1/claim" ] && ok "the claim is a local directory — the lock is mkdir's atomicity" ||
        bad "no claim directory: two ups on this machine would both take this box"
    local tagged="" f
    for f in "$REC"/calls/*.flat; do
        grep -q 'create-tags' "$f" 2>/dev/null && tagged="${tagged}$(cat "$f")"
    done
    case "$tagged" in
    *"i-w1"*"djb:for"*"V-boxpool"*) ok "and the tag records what it was claimed FOR, so the census can say" ;;
    *) bad "no create-tags recorded the claim: '${tagged}'" ;;
    esac
    [ "$(cat "$W/vhome/i-w1/rung" 2>/dev/null || true)" = "V-boxpool" ] &&
        ok "the box's rung file is written, so loop/leg/wait know where its logs live" ||
        bad "the claimed box has no rung file"
    out_has "tree       HEAD" && ok "and the push ran exactly as it does on a cold launch" ||
        bad "the claimed box was never pushed to"
}

case_two_claims_of_one_warm_box_yield_one_winner() {
    CURRENT=case_two_claims_of_one_warm_box_yield_one_winner
    # A REAL RACE ON THE REAL LOCK. Two wrappers, two fixture worlds so the
    # recorders cannot collide, ONE shared VERIFIER_HOME — which is the only
    # thing the two contend for, and is exactly the contention a PM claiming a
    # box while a builder claims one produces. `gate_lease.sh`'s acquire uses
    # the same primitive for the same reason: `mkdir` either makes the
    # directory or it does not, and there is no window between the two.
    world_new claim_race_a
    world_up_ready
    pool_listing "$(pool_row i-w1 5 ami-v1 0.2085)"
    local wa="$W" reca="$REC"
    world_new claim_race_b
    world_up_ready
    pool_listing "$(pool_row i-w1 5 ami-v1 0.2085)"
    local wb="$W" recb="$REC"
    local shared="$WORK/claim_race_home"
    rm -rf "$shared"
    mkdir -p "$shared/i-w1"
    printf 'key\n' >"$shared/i-w1/id_ed25519"
    local side
    for side in a b; do
        local ww rr
        if [ "$side" = a ]; then
            ww="$wa"
            rr="$reca"
        else
            ww="$wb"
            rr="$recb"
        fi
        env -i PATH="$ww/bin:/usr/bin:/bin:/usr/sbin:/sbin" HOME="$ww/home" REC="$rr" \
            USER=driveuser DJB_DEPLOY_NAMESPACE="$NS" DJB_VERIFIER_REGION="$RG" \
            DJB_VERIFIER_HOME="$shared" DJB_VERIFIER_OWNER="$OWNER" \
            "$VB_COUNTED" up --for "race-${side}" >"$ww/out" 2>"$ww/err" &
    done
    wait
    local claims=0 launches=0
    for side in a b; do
        local ww rr
        if [ "$side" = a ]; then
            ww="$wa"
            rr="$reca"
        else
            ww="$wb"
            rr="$recb"
        fi
        grep -F "claimed i-w1" "$ww/out" >/dev/null 2>&1 && claims=$((claims + 1))
        grep -cE '^ec2 run-instances' "$rr/aws.ops" >/dev/null 2>&1 &&
            launches=$((launches + $(grep -cE '^ec2 run-instances' "$rr/aws.ops" || true)))
    done
    [ "$claims" = "1" ] && ok "exactly one of two racing ups claimed the one warm box" ||
        bad "${claims} of 2 racing ups claimed i-w1 — the lock is not a lock"
    [ "$launches" = "1" ] && ok "and the loser launched its own rather than sharing one box's gate" ||
        bad "${launches} run-instances across the two, wanted 1"
    rm -rf "$shared"
    W="$wb"
    REC="$recb"
}

case_a_warm_box_on_another_image_or_without_a_key_is_skipped_by_name() {
    CURRENT=case_a_warm_box_on_another_image_or_without_a_key_is_skipped_by_name
    # A BOX ON AN OLDER IMAGE. Still a valid measurement — `setup.sh` resyncs —
    # but slower, and a claim is supposed to be the fast path, so it is skipped
    # and the skip says which image it was on.
    world_new claim_old_image
    world_up_ready
    pool_listing "$(pool_row i-w1 20 ami-old 0.2085)"
    mkdir -p "$W/vhome/i-w1"
    printf 'key\n' >"$W/vhome/i-w1/id_ed25519"
    vb -- up --for X
    [ "$VB_RC" = "0" ] || {
        bad "up exited ${VB_RC}"
        report
        return
    }
    said "skipped i-w1: image ami-old ≠ ami-v1" && ok "a warm box on another image is skipped BY NAME" ||
        bad "the skip does not name the image: $(cat "$W/out")"
    [ "$(op_count 'ec2 run-instances')" = "1" ] && ok "and a box was launched instead" ||
        bad "$(op_count 'ec2 run-instances') run-instances call(s)"

    # A BOX THIS MACHINE HAS NO KEY FOR. The private half never leaves the
    # machine that launched it, so this one belongs to somebody else's laptop
    # and there is no way into it from here.
    world_new claim_no_key
    world_up_ready
    pool_listing "$(pool_row i-w2 20 ami-v1 0.2085)"
    vb -- up --for X
    [ "$VB_RC" = "0" ] || {
        bad "up exited ${VB_RC}"
        report
        return
    }
    said "skipped i-w2: no key on this machine" && ok "a warm box with no local key is skipped BY NAME" ||
        bad "the skip does not name the missing key: $(cat "$W/out")"
    [ "$(op_count 'ec2 run-instances')" = "1" ] && ok "and a box was launched instead" ||
        bad "$(op_count 'ec2 run-instances') run-instances call(s)"
    [ ! -d "$W/vhome/i-w2/claim" ] && ok "and nothing was claimed" || bad "a box with no key was claimed"
}

case_census_prints_the_pool_and_its_hourly_cost() {
    CURRENT=case_census_prints_the_pool_and_its_hourly_cost
    world_new census_pool
    local now exp
    now="$(cat "$REC/clock")"
    exp="$(iso_utc $((now + 3600)))"
    {
        printf 'i-w1\tc7g.4xlarge\tverifier\t%s\t%s\t%s\tami-v1\n' "$OWNER" "$exp" "$(iso_utc $((now - 1800)))"
        printf 'i-w2\tc7g.4xlarge\tverifier\t%s\t%s\t%s\tami-v1\n' "$OWNER" "$exp" "$(iso_utc $((now - 600)))"
        printf 'i-c1\tc7g.4xlarge\tverifier\t%s\t%s\t%s\tami-v1\n' "$OWNER" "$exp" "$(iso_utc $((now - 300)))"
    } >"$REC/ans/ec2_describe-instances__ReservationsInstancesInstanceIdInstance"
    # Two of the three are still tagged djb:for=pool; the third was claimed, so
    # its tag now names what it was claimed for and it is no longer warm.
    pool_listing \
        "$(pool_row i-w1 30 ami-v1 0.2085)" \
        "$(pool_row i-w2 10 ami-v1 0.2085)"
    vb -- census
    [ "$VB_RC" = "0" ] || {
        bad "census exited ${VB_RC}"
        report
        return
    }
    out_has "i-w1 warm 30m \$0.2085/h" && ok "each warm box is one line with its age and its own hourly price" ||
        bad "the pool line for i-w1 is not the shape the design states: $(cat "$W/out")"
    out_has "i-w2 warm 10m \$0.2085/h" && ok "and so is the second" ||
        bad "the pool line for i-w2 is missing"
    out_has "i-c1 warm" && bad "the CLAIMED box is listed as warm — it is somebody's verification" ||
        ok "the claimed box is not in the pool section"
    out_has "pool: 2 warm · \$0.4170/h" && ok "and the sum is the tags added up, not a price looked up again" ||
        bad "the pool total is not the shape the design states: $(cat "$W/out")"

    # A PRICE THE TAG DOES NOT CARRY IS NEVER COMPUTED. An old pool box, or one
    # whose tagging was refused, has no djb:price — and a census that quietly
    # asked the spot market for today's number would print a cost that is not
    # what that box is costing.
    world_new census_pool_unpriced
    now="$(cat "$REC/clock")"
    exp="$(iso_utc $((now + 3600)))"
    printf 'i-w1\tc7g.4xlarge\tverifier\t%s\t%s\t%s\tami-v1\n' \
        "$OWNER" "$exp" "$(iso_utc $((now - 1800)))" \
        >"$REC/ans/ec2_describe-instances__ReservationsInstancesInstanceIdInstance"
    pool_listing "$(pool_row i-w1 30 ami-v1 None)"
    vb -- census
    out_has "i-w1 warm 30m \$?/h" && ok "an untagged price prints as unknown rather than as a number nobody measured" ||
        bad "the unpriced box's line is not '\$?/h': $(cat "$W/out")"
    [ "$(op_count 'ec2 describe-spot-price-history')" = "0" ] &&
        ok "and the census asked the spot market nothing" ||
        bad "the census computed a price it was not told"
}

case_census_with_no_pool_says_empty() {
    CURRENT=case_census_with_no_pool_says_empty
    world_new census_no_pool
    local now exp
    now="$(cat "$REC/clock")"
    exp="$(iso_utc $((now + 3600)))"
    printf 'i-c1\tc7g.4xlarge\tverifier\t%s\t%s\t%s\tami-v1\n' \
        "$OWNER" "$exp" "$(iso_utc $((now - 300)))" \
        >"$REC/ans/ec2_describe-instances__ReservationsInstancesInstanceIdInstance"
    vb -- census
    [ "$VB_RC" = "0" ] || {
        bad "census exited ${VB_RC}"
        report
        return
    }
    out_has "pool: empty" && ok "no warm box says so, rather than printing a section with nothing in it" ||
        bad "the census does not say the pool is empty: $(cat "$W/out")"

    # AND AN OVERDUE BOX IS STILL THE ONLY THING THAT MAKES THIS A FINDING. The
    # pool section is a report, never a verdict.
    world_new census_no_pool_overdue
    now="$(cat "$REC/clock")"
    printf 'i-c1\tc7g.4xlarge\tverifier\t%s\t%s\t%s\tami-v1\n' \
        "$OWNER" "$(iso_utc $((now - 7200)))" "$(iso_utc $((now - 10800)))" \
        >"$REC/ans/ec2_describe-instances__ReservationsInstancesInstanceIdInstance"
    pool_listing "$(pool_row i-w1 30 ami-v1 0.2085)"
    vb -- census
    [ "$VB_RC" = "1" ] && ok "the census's exit is unchanged: 1 only for OVERDUE or STALE" ||
        bad "a census with a pool and an overdue box exited ${VB_RC}, wanted 1"
    out_has "pool: 1 warm" && ok "and the pool section still printed on the finding path" ||
        bad "the pool section is missing when the census has a finding"
}

# =============================================================================
# 1.7 — run / loop / wait / fetch
# =============================================================================

case_run_carries_the_transport_and_touches_the_activity_marker() {
    CURRENT=case_run_carries_the_transport_and_touches_the_activity_marker
    world_new run_ok
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
    vb -- run i-up1 -- true
    [ "$VB_RC" = "0" ] || {
        bad "run exited ${VB_RC}"
        report
        return
    }
    local call
    call="$(cat "$REC/ssh/1.flat" 2>/dev/null || true)"
    local want miss=""
    for want in \
        "ProxyCommand=aws ssm start-session --target %h --document-name AWS-StartSSHSession" \
        "--profile ${NS}-verifier" \
        "--region ${RG}" \
        "-o ServerAliveInterval=30" \
        "verifier@i-up1" \
        "touch /run/verifier/last-activity"; do
        case "$call" in *"$want"*) ;; *) miss="${miss}
      ${want}" ;; esac
    done
    [ -z "$miss" ] && ok "the ssh carries the tunnel, the keepalive, the box user and the activity touch" ||
        bad "the ssh invocation is missing:${miss}"
}

case_run_passes_the_remote_status_through_unchanged() {
    CURRENT=case_run_passes_the_remote_status_through_unchanged
    local want
    for want in 7 1 2; do
        world_new "run_rc_${want}"
        ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
        mkdir -p "$W/vhome/i-up1"
        printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
        printf '%s\n' "$want" >"$REC/ssh/default.rc"
        vb -- run i-up1 -- false
        [ "$VB_RC" = "$want" ] && ok "a remote ${want} arrives as ${want}" ||
            bad "a remote ${want} arrived as ${VB_RC} — the wrapper rewrote the verdict"
    done
}

case_run_refuses_a_reclaimed_box_without_attempting_ssh() {
    CURRENT=case_run_refuses_a_reclaimed_box_without_attempting_ssh
    world_new run_reclaimed
    ans "ec2_describe-instances__Reservations0Instances0StateName" "terminated"
    ans "ec2_describe-instances__Reservations0Instances0StateReason" "Server.SpotInstanceTermination"
    mkdir -p "$W/vhome/i-gone"
    printf 'key\n' >"$W/vhome/i-gone/id_ed25519"
    vb -- run i-gone -- true
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2, got ${VB_RC}"
        report
        return
    }
    out_has "box reclaimed (spot) i-gone" && ok "it says the box was reclaimed, by name" ||
        bad "stdout does not carry 'box reclaimed (spot) i-gone'"
    [ ! -f "$REC/ssh/1.flat" ] && ok "no ssh was attempted" ||
        bad "it tried to ssh to a terminated instance"
    said "never red" && ok "it says the verdict is lost rather than red" ||
        bad "the refusal does not distinguish a lost verdict from a red one"
}

# --- the scope basis the box could not derive --------------------------------
#
# A DEPTH-1 MIRROR COLLAPSES HEAD AND `main` ONTO ONE COMMIT. On the box,
# `merge-base HEAD refs/heads/main` is therefore that commit, the gate's one
# changed-file derivation comes back EMPTY, and five readers of it — the
# `--loop` scope, the secret scan, the three changed-file censuses and the fe
# leg — all ask about nothing while printing a sentence that reads like a
# measurement. Measured on the first off-box run: `the merge-base IS this HEAD
# … the scope is EMPTY` for a rung that changed six files here.
#
# SO THE FORK POINT TRAVELS WITH THE TREE, as a ref and not just as a name: a
# sha the box does not HAVE is a sha it cannot diff against.
case_the_push_carries_the_rungs_fork_point_as_a_ref() {
    CURRENT=case_the_push_carries_the_rungs_fork_point_as_a_ref
    local base="4444444444444444444444444444444444444444"
    world_new push_base
    world_up_ready
    printf '%s\n' "$base" >"$REC/git.mergebase"
    printf '3\n' >"$REC/git.revlist"
    vb -- up --for X
    [ "$VB_RC" = "0" ] || {
        bad "up exited ${VB_RC}"
        report
        return
    }
    local flat
    flat="$(cat "$REC/git.flat" 2>/dev/null || true)"
    # DEEP ENOUGH TO REACH IT AND NOT ONE COMMIT DEEPER: three commits of rung
    # plus the fork point itself.
    case "$flat" in
    *"fetch -q --depth 4 "*) ok "the mirror is deepened to exactly the rung's own commits plus its fork point" ;;
    *) bad "the mirror was not deepened to reach the fork point: $(printf '%s' "$flat" | grep -F 'fetch -q' || echo none)" ;;
    esac
    case "$flat" in
    *"update-ref refs/djb/base ${base}"*) ok "the fork point is made a ref IN THE MIRROR" ;;
    *) bad "refs/djb/base was never created" ;;
    esac
    # AND NOT IN THIS CHECKOUT. A linked worktree shares its refs with the whole
    # family, so a ref planted here lands in every other agent's checkout and
    # two rungs overwrite each other's.
    case "$flat" in
    *"-C $ROOT update-ref"*) bad "a ref was written into the checkout's own git dir — that is the whole family's" ;;
    *) ok "nothing was written into this checkout's refs" ;;
    esac
    # AND IT GOES OVER FIRST, IN ITS OWN PUSH. A shallow source cannot send two
    # refs in one invocation — measured, with the tree landing anyway and the
    # status still non-zero — so the base is its own push and it is the one
    # sent before the tree.
    local push_line
    push_line="$(grep -F 'push --force ssh://' "$REC/git.flat" | sed -n '1p' || true)"
    case "$push_line" in
    *"refs/djb/base:refs/djb/base"*) ok "and it is the FIRST ref sent, in a push of its own" ;;
    *) bad "the first ssh:// push does not carry refs/djb/base: '${push_line}'" ;;
    esac
}

case_a_rung_too_far_from_its_fork_point_carries_nothing_and_says_so() {
    CURRENT=case_a_rung_too_far_from_its_fork_point_carries_nothing_and_says_so
    world_new push_base_deep
    world_up_ready
    printf '4444444444444444444444444444444444444444\n' >"$REC/git.mergebase"
    printf '5000\n' >"$REC/git.revlist"
    vb -- up --for X
    [ "$VB_RC" = "0" ] || {
        bad "up exited ${VB_RC}"
        report
        return
    }
    local flat
    flat="$(cat "$REC/git.flat" 2>/dev/null || true)"
    case "$flat" in
    *"fetch -q --depth 1 "*) ok "the mirror stays one commit deep" ;;
    *) bad "a 5000-commit history was dragged over a tunnel measured in tens of KB/s" ;;
    esac
    # CREATED OR SENT, not merely asked about: the push now reads a declared
    # `refs/djb/base` in the checkout before it derives one, and that question is
    # in the record too.
    case "$flat" in
    *"update-ref refs/djb/base"* | *"refs/djb/base:refs/djb/base"*) bad "the fork point was carried past the ceiling" ;;
    *) ok "no base ref was created or pushed" ;;
    esac
    # SAID, NOT SILENT: the box's scope will be empty and the operator is the
    # only one who can tell that from a rung that genuinely changed nothing.
    said "5000 commits from its fork point" || out_has "5000 commits from its fork point" &&
        ok "and the push says the base is not being carried and what follows from it" ||
        bad "nothing said the scope on the box will be empty"
}

# --- the union pushed as main, and the fork point it declares ------------------
#
# THE SHAPE A CONSUMER'S VERIFIER PUSHES: a checkout whose `main` IS its HEAD —
# the union of a rung and main, committed as main. `merge-base HEAD main` is
# HEAD there, so the derivation answers "nothing to carry", the box's `--loop`
# finds its fork point at HEAD, and every changed-file reader over there — the
# scope, the secret scan, the censuses, the fe leg — asks about nothing
# ("frontend: UNTOUCHED" for a frontend rung). `verify_start.sh` now writes the
# fold point into the clone as `refs/djb/base`; the push honours a declared
# base before it derives one.
#
# TWO HALVES, and the second is why this is not a claim about argv alone. The
# WRAPPER'S half runs in this drive's fake-git world (what it decides to carry,
# and how deep); the READER'S half replays exactly that decision with real git —
# the recorded depth, the recorded base — into a real receiver, and asks the
# box-side reader itself (`secrets_scan_changed_files`, which `loop_tier.sh`
# reuses) what the rung changed. `test_secrets_scan.sh`'s carried-base case is
# the reader's precedent; this is the same reader fed by the writer.
case_a_union_pushed_as_main_carries_the_fork_point_it_declares() {
    CURRENT=case_a_union_pushed_as_main_carries_the_fork_point_it_declares
    local w="${WORK}/union-as-main" src fold union
    rm -rf "$w"
    mkdir -p "$w"
    src="$w/src"
    git init -q "$src" || cannot_look "git init refused for the union's source"
    git -C "$src" symbolic-ref HEAD refs/heads/main
    git -C "$src" config user.email drive@example.invalid
    git -C "$src" config user.name "verifier box drive"
    echo shared >"$src/shared.txt"
    git -C "$src" add shared.txt && git -C "$src" commit -q -m "the fold point"
    fold="$(git -C "$src" rev-parse HEAD)"
    echo "the rung's own work" >"$src/rung.txt"
    git -C "$src" add rung.txt && git -C "$src" commit -q -m "the rung"
    union="$(git -C "$src" rev-parse HEAD)"
    # `main` IS HEAD, and the fork point is declared — the verify clone's shape.
    git -C "$src" update-ref refs/djb/base "$fold"

    # --- the wrapper's half ----------------------------------------------------
    world_new push_union_as_main
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-ua1"
    printf 'key\n' >"$W/vhome/i-ua1/id_ed25519"
    printf '%s\n' "$union" >"$REC/git.revparse"
    printf '%s\n' "$union" >"$REC/ssh/default.out"
    printf '%s\n' "$union" >"$REC/git.mergebase"
    git -C "$src" rev-list --count "${fold}..${union}" >"$REC/git.revlist"
    printf '%s\n' "$fold" >"$REC/git.djbbase"
    vb -- push i-ua1
    [ "$VB_RC" = "0" ] || {
        bad "push exited ${VB_RC}"
        report
        return
    }
    local flat depth carried first_push
    flat="$(cat "$REC/git.flat" 2>/dev/null || true)"
    carried="$(printf '%s\n' "$flat" | sed -n 's/.* update-ref refs\/djb\/base \([0-9a-f]\{40\}\).*/\1/p' | sed -n '1p')"
    [ "$carried" = "$fold" ] &&
        ok "a checkout whose main IS HEAD carries the fork point it declares (${fold:0:8})" ||
        bad "the declared fork point was not carried: update-ref named '${carried:-nothing}', wanted ${fold:0:8}"
    first_push="$(grep -F 'push --force ssh://' "$REC/git.flat" | sed -n '1p' || true)"
    case "$first_push" in
    *"refs/djb/base:refs/djb/base"*) ok "and it goes over first, in a push of its own" ;;
    *) bad "the first ssh:// push does not carry refs/djb/base: '${first_push}'" ;;
    esac
    said "carried    fork point ${fold:0:8} (refs/djb/base, declared in this checkout)" &&
        ok "the push says which base went and where it came from" ||
        bad "nothing said which fork point was carried: $(tr '\n' ' ' <"$W/err")"
    depth="$(printf '%s\n' "$flat" | sed -n 's/.*fetch -q --depth \([0-9]*\) .*/\1/p' | sed -n '1p')"
    [ -n "$carried" ] && [ -n "$depth" ] || return 0

    # --- the reader's half, with real git ---------------------------------------
    local mirror="$w/mirror" box="$w/box" list="$w/list" basis="$w/basis" rc=0
    git init -q --bare "$mirror"
    git -C "$mirror" fetch -q --depth "$depth" "file://${src}" "+HEAD:refs/heads/main" ||
        cannot_look "could not build the depth-${depth} mirror the wrapper recorded"
    git -C "$mirror" update-ref refs/djb/base "$carried" ||
        cannot_look "the recorded depth ${depth} does not reach the carried base — the mirror has no ${carried:0:8}"
    git init -q "$box"
    git -C "$box" config user.email drive@example.invalid
    git -C "$box" config user.name "verifier box drive"
    git -C "$box" config receive.denyCurrentBranch updateInstead
    git -C "$box" config receive.shallowUpdate true
    echo seed >"$box/seed.txt"
    git -C "$box" add -A && git -C "$box" commit -q -m seed
    git -C "$box" checkout -q -b verifier-parking
    git -C "$box" update-ref -d refs/heads/main
    git -C "$mirror" push -q --force "$box" refs/djb/base:refs/djb/base >"$w/push.log" 2>&1 &&
        git -C "$mirror" push -q --force "$box" refs/heads/main:refs/heads/main >>"$w/push.log" 2>&1 ||
        cannot_look "the replayed transfer did not land: $(tr '\n' ' ' <"$w/push.log")"
    git -C "$box" reset -q --hard refs/heads/main
    (
        cd "$box" || exit 2
        # shellcheck source=scripts/secrets_scan.sh
        . "$ROOT/scripts/secrets_scan.sh"
        DJB_LOOP_SCOPE_BASE=refs/djb/base secrets_scan_changed_files "$list" >"$w/derive.log" 2>&1 || exit $?
        printf '%s\n' "$SECRETS_SCAN_BASIS" >"$basis"
    ) || rc=$?
    [ "$rc" = "0" ] || {
        bad "the box-side derivation exited ${rc}: $(tr '\n' ' ' <"$w/derive.log")"
        return
    }
    tr '\0' '\n' <"$list" >"$w/list.txt"
    if grep -Fx rung.txt "$w/list.txt" >/dev/null; then
        ok "and on the box the reader derives the rung's own file (rung.txt) from the carried base"
    else
        bad "the box-side reader did not list rung.txt: '$(tr '\n' ' ' <"$w/list.txt")' — $(cat "$basis")"
    fi
    if grep -Fx shared.txt "$w/list.txt" >/dev/null; then
        bad "the box-side reader listed shared.txt, which the rung never touched"
    else
        ok "and nothing the rung did not touch"
    fi
    grep -F "CARRIED fork point" "$basis" >/dev/null 2>&1 &&
        ok "the reader's basis says the fork point was carried" ||
        bad "the reader's basis does not say it was carried: $(cat "$basis")"
}

# COMMITS PAST MAIN AND NO FORK POINT AT ALL — a refusal, never an empty scope.
# HEAD is not main's tip, no `refs/djb/base` is declared, and the history
# reaches no merge-base (a shallow clone, an unrelated history). The shape this
# replaces carried `base_sha=""` in silence and the box graded the rung against
# nothing.
case_commits_past_main_with_no_fork_point_are_refused_before_anything_leaves() {
    CURRENT=case_commits_past_main_with_no_fork_point_are_refused_before_anything_leaves
    world_new push_no_fork_point
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-nf1"
    printf 'key\n' >"$W/vhome/i-nf1/id_ed25519"
    printf '%s\t%s\n' "$ROOT" "3333333333333333333333333333333333333333" >"$REC/git.revparse.main"
    printf '1\n' >"$REC/git.ancestor.rc"
    vb -- push i-nf1
    [ "$VB_RC" = "2" ] && ok "exit 2 for a tree with commits past main and no fork point" ||
        bad "wanted exit 2, got ${VB_RC}"
    said "git update-ref refs/djb/base <sha>" &&
        ok "the refusal names the remedy: declare the fork point" ||
        bad "the refusal does not name the update-ref remedy: $(tr '\n' ' ' <"$W/err")"
    said "Nothing was pushed" && ok "and says nothing left" ||
        bad "the refusal does not say what state it left: $(tr '\n' ' ' <"$W/err")"
    local pushes
    pushes="$(grep -cF -- " push " "$REC/git.flat" 2>/dev/null || true)"
    [ "${pushes:-0}" = "0" ] && ok "no push of any kind was attempted — not the vouch, not the transfer" ||
        bad "${pushes} push(es) were attempted after the fork point could not be found"
    # AND A DERIVABLE ONE IS NOT REFUSED — the same world with a merge-base.
    world_new push_fork_point_derived
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-nf2"
    printf 'key\n' >"$W/vhome/i-nf2/id_ed25519"
    printf '%s\t%s\n' "$ROOT" "3333333333333333333333333333333333333333" >"$REC/git.revparse.main"
    printf '3333333333333333333333333333333333333333\n' >"$REC/git.mergebase"
    printf '1\n' >"$REC/git.revlist"
    vb -- push i-nf2
    [ "$VB_RC" = "0" ] && ok "the same tree with a derivable fork point pushes, exit 0" ||
        bad "a derivable fork point was refused too, exit ${VB_RC}: $(tr '\n' ' ' <"$W/err")"
}

# A DECLARED BASE THAT IS NOT BEHIND HEAD IS NOT A FORK POINT OF IT. `refs/djb/*`
# is family-shared in a linked worktree, so a ref somebody typed for another
# tree can be in view; honouring one that is not an ancestor would carry a
# stranger's scope to the box.
case_a_declared_base_that_is_not_behind_head_is_not_carried() {
    CURRENT=case_a_declared_base_that_is_not_behind_head_is_not_carried
    world_new push_foreign_base
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-fb1"
    printf 'key\n' >"$W/vhome/i-fb1/id_ed25519"
    printf '5555555555555555555555555555555555555555\n' >"$REC/git.djbbase"
    printf '1\n' >"$REC/git.ancestor.rc"
    vb -- push i-fb1
    [ "$VB_RC" = "0" ] || {
        bad "push exited ${VB_RC}"
        report
        return
    }
    grep -F "refs/djb/base 5555555555555555555555555555555555555555" "$REC/git.flat" >/dev/null 2>&1 &&
        bad "a declared base that is not an ancestor of HEAD was carried" ||
        ok "a declared base that is not behind HEAD is not carried"
}

case_loop_detaches_the_gate_on_the_box_and_never_pipes_it() {
    CURRENT=case_loop_detaches_the_gate_on_the_box_and_never_pipes_it
    world_new loop_ok
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
    printf 'a-rung\n' >"$W/vhome/i-up1/rung"
    printf '4242\n' >"$REC/ssh/default.out"
    vb -- loop i-up1 --log v1
    [ "$VB_RC" = "0" ] || {
        bad "loop exited ${VB_RC}"
        report
        return
    }
    # THE LAUNCH IS SESSION 3 NOW. Sessions 1 and 2 are `loop`'s own pre-flight
    # — the box's worktree tree and the box's main tree, compared before a
    # two-minute gate is started over the wrong one.
    local call
    call="$(cat "$REC/ssh/3.flat" 2>/dev/null || true)"
    local want miss=""
    for want in \
        "setsid nohup" \
        "DJB_LOOP_SCOPE_BASE=refs/djb/base ./scripts/check.sh --loop >" \
        "~/verify/a-rung/v1.log 2>&1" \
        "~/verify/a-rung/v1.rc"; do
        case "$call" in *"$want"*) ;; *) miss="${miss}
      ${want}" ;; esac
    done
    [ -z "$miss" ] && ok "the gate runs detached on the box, redirected on the box" ||
        bad "the remote command is missing:${miss}"
    case "$call" in
    *"check.sh --loop |"* | *"check.sh --loop 2>&1 |"*)
        bad "the gate is PIPED on the box — the gate refuses that, and a filter takes its exit status" ;;
    *) ok "the gate is never piped" ;;
    esac
    [ -f "$W/vhome/i-up1/v1.pid" ] && ok "the remote pid is remembered for wait" ||
        bad "no pid was written, so wait has nothing to poll"
}

# A box that is up, keyed, parked on the pushed tree and answering `4242` to
# everything — which is what `loop` and `leg` both need before they will detach
# anything. The pid the detach returns is that same 4242.
world_box_ready_to_detach() {
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
    printf '%s\n' "$1" >"$W/vhome/i-up1/rung"
    printf '4242\n' >"$REC/ssh/default.out"
}

case_leg_detaches_one_unit_shard_and_never_pipes_it() {
    CURRENT=case_leg_detaches_one_unit_shard_and_never_pipes_it
    world_new leg_ok
    world_box_ready_to_detach "bank-abc12345-selftest-2of3"
    vb -- leg i-up1 --unit selftest --shard 2/3 --log leg
    [ "$VB_RC" = "0" ] || {
        bad "leg exited ${VB_RC}"
        report
        return
    }
    # SESSION 3, for `loop`'s reason one case up: sessions 1 and 2 are the two
    # tree reads that stop a unit being measured against the image.
    local call
    call="$(cat "$REC/ssh/3.flat" 2>/dev/null || true)"
    local want miss=""
    for want in \
        "setsid nohup" \
        "./scripts/check.sh --leg selftest --shard 2/3 >" \
        "~/verify/bank-abc12345-selftest-2of3/leg.log 2>&1" \
        "~/verify/bank-abc12345-selftest-2of3/leg.rc"; do
        case "$call" in *"$want"*) ;; *) miss="${miss}
      ${want}" ;; esac
    done
    [ -z "$miss" ] && ok "one unit of the gate runs detached on the box, redirected on the box" ||
        bad "the remote command is missing:${miss}"
    case "$call" in
    *"--leg selftest --shard 2/3 |"* | *"--leg selftest --shard 2/3 2>&1 |"*)
        bad "the unit is PIPED on the box — the gate refuses that, and a filter takes its exit status" ;;
    *) ok "the unit is never piped" ;;
    esac
    # A UNIT IS NOT A SCOPE. `--loop` derives a changed-file scope and needs the
    # fork point named; `--leg <unit>` runs the unit whole, so a scope basis
    # here would be a variable the leg never reads and a difference between two
    # boxes running the same unit.
    case "$call" in
    *DJB_LOOP_SCOPE_BASE*) bad "leg sets DJB_LOOP_SCOPE_BASE — a unit is not scoped" ;;
    *) ok "no scope basis is set: a unit is not scoped" ;;
    esac
    case "$call" in
    *"touch /run/verifier/last-activity"*)
        ok "the detach goes through ssh_to, so a running leg keeps the reaper off the box" ;;
    *) bad "the detach does not touch the activity marker — the reaper cannot see a leg" ;;
    esac
    [ -f "$W/vhome/i-up1/leg.pid" ] && ok "the remote pid is remembered for wait" ||
        bad "no pid was written, so wait has nothing to poll"

    # AND WITHOUT A SHARD THE FLAG IS ABSENT ENTIRELY, never `--shard ` with
    # nothing after it: the gate sets its "a shard was typed" flag the moment it
    # SEES the word, and an empty one is exit 2 on the box for a unit that was
    # never meant to be sharded.
    world_new leg_unsharded
    world_box_ready_to_detach "bank-abc12345-static"
    vb -- leg i-up1 --unit static --log leg
    [ "$VB_RC" = "0" ] || {
        bad "an unsharded leg exited ${VB_RC}"
        report
        return
    }
    call="$(cat "$REC/ssh/3.flat" 2>/dev/null || true)"
    case "$call" in
    *"./scripts/check.sh --leg static > ~/verify/bank-abc12345-static/leg.log"*)
        ok "an indivisible unit carries no --shard at all" ;;
    *) bad "the unsharded remote command is not the bare unit: ${call}" ;;
    esac
}

# WHY THIS CASE EXISTS, AND IT IS A PAID ONE. ADR gate-1's amendment gave the
# gate a `--passes` modifier and the bank a plan that hands it, and the two
# were built in parallel behind one sentence naming this wrapper's argv — which
# nothing drove, because the bank's own drive STUBS this file. The first real
# sharded bank after both merged came down on `!! verifier_box: unknown
# argument '--passes' to leg`, with every box up and paid for and no unit run.
# A seam asserted on both sides of a stub is a seam nobody asserted.
#
# SO IT IS THE FORWARDING THAT IS DRIVEN, in both directions: the flag reaches
# the box's gate verbatim when it is given, and the box command is byte-for-byte
# the one it always was when it is not.
case_leg_forwards_the_pass_count_verbatim() {
    CURRENT=case_leg_forwards_the_pass_count_verbatim
    local call want miss desc name argv

    # (a) GIVEN, AND FORWARDED VERBATIM, AFTER THE SHARD. The order is the
    # gate's usage line and the bank's plan echo; a modifier that arrived
    # before `--shard` would parse the same and read differently everywhere it
    # is quoted afterwards.
    world_new leg_passes_1
    world_box_ready_to_detach "bank-abc12345-pytest-x2-1of1"
    vb -- leg i-up1 --unit pytest-x2 --shard 1/1 --passes 1 --log leg
    [ "$VB_RC" = "0" ] || {
        bad "leg --passes 1 exited ${VB_RC}"
        report
        return
    }
    call="$(cat "$REC/ssh/3.flat" 2>/dev/null || true)"
    miss=""
    for want in \
        "./scripts/check.sh --leg pytest-x2 --shard 1/1 --passes 1 >" \
        "~/verify/bank-abc12345-pytest-x2-1of1/leg.log 2>&1" \
        "~/verify/bank-abc12345-pytest-x2-1of1/leg.rc"; do
        case "$call" in *"$want"*) ;; *) miss="${miss}
      ${want}" ;; esac
    done
    [ -z "$miss" ] && ok "the pass count reaches the box's gate, after the shard" ||
        bad "the remote command is missing:${miss}
   got: ${call}"

    # (b) `--passes 2` IS THE DEFAULT SPELLED OUT AND IT IS STILL FORWARDED.
    # This wrapper keeps no opinion about what the counts MEAN — normalising 2
    # away here would be a second place that knows the default, and the gate
    # already has one.
    world_new leg_passes_2
    world_box_ready_to_detach "bank-abc12345-pytest-x2-1of1"
    vb -- leg i-up1 --unit pytest-x2 --shard 1/1 --passes 2 --log leg
    [ "$VB_RC" = "0" ] || {
        bad "leg --passes 2 exited ${VB_RC}"
        report
        return
    }
    call="$(cat "$REC/ssh/3.flat" 2>/dev/null || true)"
    case "$call" in
    *"--leg pytest-x2 --shard 1/1 --passes 2 >"*)
        ok "a spelled-out default is forwarded rather than interpreted here" ;;
    *) bad "--passes 2 did not reach the box: ${call}" ;;
    esac

    # (c) ABSENT, AND THE BOX COMMAND IS THE ONE IT ALWAYS WAS. Never
    # `--passes ` with nothing after it, and never a `2` this wrapper invented:
    # the gate sets its "a count was typed" flag the moment it SEES the word,
    # so either would be a different run on every box that never asked.
    world_new leg_passes_absent
    world_box_ready_to_detach "bank-abc12345-pytest-x2-1of2"
    vb -- leg i-up1 --unit pytest-x2 --shard 1/2 --log leg
    [ "$VB_RC" = "0" ] || {
        bad "an unmodified leg exited ${VB_RC}"
        report
        return
    }
    call="$(cat "$REC/ssh/3.flat" 2>/dev/null || true)"
    case "$call" in
    *"--passes"*) bad "a leg that asked for no pass count carries one anyway: ${call}" ;;
    *"./scripts/check.sh --leg pytest-x2 --shard 1/2 > ~/verify/bank-abc12345-pytest-x2-1of2/leg.log"*)
        ok "with no --passes the box command is byte-for-byte the one it was" ;;
    *) bad "the unmodified remote command is not the bare sharded unit: ${call}" ;;
    esac

    # (d) AND A COUNT THIS WRAPPER CANNOT READ IS REFUSED HERE, BEFORE THE
    # TRANSPORT. It is interpolated into a single-quoted `sh -c '…'` on the
    # box exactly as the unit and the shard are, so the charset wall is the
    # same wall — and a value the box's gate would refuse with exit 2 costs a
    # launched box to find out. Nothing about WHICH counts mean what is
    # decided here; `1|2` is the shape, and the gate owns the rules.
    for desc in \
        "no-value|--unit pytest-x2 --shard 1/1 --log leg --passes|--passes takes 1 or 2" \
        "three|--unit pytest-x2 --shard 1/1 --passes 3 --log leg|--passes takes 1 or 2, got '3'" \
        "word|--unit pytest-x2 --shard 1/1 --passes all --log leg|--passes takes 1 or 2, got 'all'" \
        "quote|--unit pytest-x2 --shard 1/1 --passes 1;id --log leg|--passes takes 1 or 2, got '1;id'"; do
        name="${desc%%|*}"
        argv="${desc#*|}"
        want="${argv#*|}"
        argv="${argv%%|*}"
        world_new "leg_passes_bad_${name}"
        world_box_ready_to_detach "a-rung"
        # shellcheck disable=SC2086  # the fixture's argv is split on purpose
        vb -- leg i-up1 $argv
        [ "$VB_RC" = "2" ] || {
            bad "${name}: wanted exit 2, got ${VB_RC}"
            report
            continue
        }
        if said "$want"; then
            ok "${name}: exit 2, refused by --passes's own sentence"
        else
            bad "${name}: exit 2, but not for the reason claimed — wanted '${want}'"
            report
        fi
        if [ -f "$REC/seq/_ssh" ]; then
            bad "${name}: exit 2 — but something was already sent to the box"
        else
            ok "${name}: and nothing was sent"
        fi
    done
}

case_leg_passes_the_shards_own_status_through() {
    CURRENT=case_leg_passes_the_shards_own_status_through
    local rc
    for rc in 0 1 2; do
        # ONE WORLD, NOT TWO. `wait` has to read the pidfile `leg` ITSELF wrote,
        # or the case is a case about a pidfile the drive planted by hand and
        # would stay green over a `leg` that never wrote one.
        world_new "leg_status_${rc}"
        world_box_ready_to_detach "a-rung"
        # Sessions 4, 5, 6 — `leg` spends 1 (worktree tree), 2 (main tree) and
        # 3 (the detach) before `wait` gets a turn: gone, the rc, the tail.
        printf 'gone\n' >"$REC/ssh/4.out"
        printf '%s\n' "$rc" >"$REC/ssh/5.out"
        printf 'the last forty lines\n' >"$REC/ssh/6.out"
        vb -- leg i-up1 --unit pytest-x2 --shard 1/2 --log leg
        [ "$VB_RC" = "0" ] || {
            bad "leg itself exited ${VB_RC} before the shard could answer"
            report
            continue
        }
        vb -- wait i-up1 leg
        [ "$VB_RC" = "$rc" ] && ok "a shard that exited ${rc} arrives here as exit ${rc}" ||
            bad "the shard's ${rc} arrived as ${VB_RC}"
    done
}

case_leg_without_a_unit_or_log_is_refused() {
    CURRENT=case_leg_without_a_unit_or_log_is_refused
    local argv desc name want
    # `--unit` missing · `--log` missing · no id at all · an unknown flag. Each
    # carries the SENTENCE it must be refused BY: without that, every one of
    # these is satisfied by a wrapper that has never heard of `leg` at all, and
    # the case would have been green on the baseline.
    for desc in \
        "no-unit|--log leg|leg needs --unit" \
        "no-log|--unit static|leg needs --log" \
        "no-id||leg needs an instance id" \
        "unknown-flag|--unit static --log leg --nonsense|unknown argument '--nonsense' to leg"; do
        name="${desc%%|*}"
        argv="${desc#*|}"
        want="${argv#*|}"
        argv="${argv%%|*}"
        world_new "leg_refusal_${name}"
        world_box_ready_to_detach "a-rung"
        if [ "$name" = "no-id" ]; then
            vb -- leg
        else
            # shellcheck disable=SC2086  # the fixture's argv is split on purpose
            vb -- leg i-up1 $argv
        fi
        [ "$VB_RC" = "2" ] || {
            bad "${name}: wanted exit 2, got ${VB_RC}"
            report
            continue
        }
        if said "$want"; then
            ok "${name}: exit 2, refused by leg's own sentence"
        else
            bad "${name}: exit 2, but not for the reason claimed — wanted '${want}'"
            report
        fi
        if [ -f "$REC/seq/_ssh" ]; then
            bad "${name}: exit 2 — but something was already sent to the box"
        else
            ok "${name}: and nothing was sent"
        fi
    done

    # AND A BOX AWS HAS TAKEN BACK IS REFUSED BEFORE THE TRANSPORT, not
    # discovered by an ssh that hangs: the verdict is LOST, never red.
    world_new leg_reclaimed
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
    printf 'a-rung\n' >"$W/vhome/i-up1/rung"
    ans "ec2_describe-instances__Reservations0Instances0StateName" "terminated"
    ans "ec2_describe-instances__Reservations0Instances0StateReason" "Server.SpotInstanceTermination"
    vb -- leg i-up1 --unit static --log leg
    [ "$VB_RC" = "2" ] && ok "a reclaimed box is exit 2" || bad "a reclaimed box exited ${VB_RC}"
    said "box reclaimed" && ok "and it is named as a reclaim, so the verdict is LOST and not red" ||
        bad "the refusal does not name the reclaim"
    [ ! -f "$REC/seq/_ssh" ] && ok "and nothing was attempted over the transport" ||
        bad "a reclaimed box was still ssh'd"
}

case_wait_passes_the_gates_own_status_through() {
    CURRENT=case_wait_passes_the_gates_own_status_through
    world_new wait_red
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
    printf 'a-rung\n' >"$W/vhome/i-up1/rung"
    printf '4242\n' >"$W/vhome/i-up1/v1.pid"
    # alive, alive, gone; then the rc; then the tail.
    printf 'alive\n' >"$REC/ssh/1.out"
    printf 'alive\n' >"$REC/ssh/2.out"
    printf 'gone\n' >"$REC/ssh/3.out"
    printf '1\n' >"$REC/ssh/4.out"
    printf 'the last forty lines\n' >"$REC/ssh/5.out"
    vb -- wait i-up1 v1
    [ "$VB_RC" = "1" ] && ok "a red gate on the box arrives here as exit 1" ||
        bad "the gate's 1 arrived as ${VB_RC}"
    out_has "the last forty lines" && ok "the log tail is printed" || bad "no log tail printed"
    out_has "gate exit 1" && ok "the status is stated as well as returned" ||
        bad "the status is not printed"
}

# =============================================================================
# 1.7b — harvest: the builder's box-banked --loop row comes home
# =============================================================================

# A 64-hex digest made of one repeated character, so a case can name three
# keys apart at a glance and still hand the subject something its own
# LOOP_KEY_RE will accept.
hex64() { printf "$1%.0s" $(seq 64); }

# The three rows the box's own loop ledger carries, and the log that names the
# middle one. The row grammar is `gate_ledger.sh::loop_ledger_record`'s.
box_loop_ledger() {
    local a b c
    a="$(hex64 a)"
    b="$(hex64 b)"
    c="$(hex64 c)"
    printf 'loop-v1 loop-v1:%s loop 2026-09-18T10:00:00Z caller=unstated scope=apps.example passes=1 tree=aaaa111 env=envaaa head=h1 merge-base=m1 waited=0 took=101\n' "$a"
    printf 'loop-v1 loop-v1:%s loop 2026-09-18T10:05:00Z caller=unstated scope=apps.example passes=1 tree=bbbb222 env=envbbb head=h2 merge-base=m2 waited=0 took=136\n' "$b"
    printf 'loop-v1 loop-v1:%s loop 2026-09-18T10:10:00Z caller=unstated scope=apps.example passes=1 tree=cccc333 env=envccc head=h3 merge-base=m3 waited=0 took=140\n' "$c"
}

# A `--loop` log that banks the MIDDLE row's key, in the shape check.sh prints
# it: the `banked:` sentence, then the key indented under it.
box_loop_log() {
    printf 'ok: loop checks passed (136s)\n'
    printf '  banked: this --loop verdict, keyed on tree + environment + scope.\n'
    printf '          loop-v1:%s\n' "$(hex64 b)"
    printf '          tree=bbbb222\n'
    printf '          env=envbbb\n'
    printf '          scope=apps.example\n'
}

# The local ledger a harvest appends to, with one row already in it so "every
# other local row is byte-identical" is a claim about something.
LOCAL_LEDGER_ROW='loop-v1 loop-v1:9999999999999999999999999999999999999999999999999999999999999999 loop 2026-09-17T09:00:00Z caller=unstated scope=apps.core passes=1 tree=dddd444 env=envddd waited=0 took=90'

world_harvest_ready() {
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
    printf 'a-rung\n' >"$W/vhome/i-up1/rung"
    printf '%s\n' "$LOCAL_LEDGER_ROW" >"$W/loop-verdicts"
}

case_harvest_brings_exactly_the_banked_row_home() {
    CURRENT=case_harvest_brings_exactly_the_banked_row_home
    world_new harvest_ok
    world_harvest_ready
    box_loop_log >"$REC/ssh/1.out"
    box_loop_ledger >"$REC/ssh/2.out"
    vb DJB_LOOP_LEDGER="$W/loop-verdicts" -- harvest i-up1 loop-a-rung
    [ "$VB_RC" = "0" ] || {
        bad "harvest exited ${VB_RC}"
        report
        return
    }
    local n first appended want
    n="$(grep -c . "$W/loop-verdicts" || true)"
    [ "$n" = "2" ] && ok "exactly one row was appended" || bad "${n} row(s) in the local ledger, wanted 2"
    first="$(sed -n '1p' "$W/loop-verdicts")"
    [ "$first" = "$LOCAL_LEDGER_ROW" ] && ok "every row that was already here is byte-identical" ||
        bad "the pre-existing row changed:
      was ${LOCAL_LEDGER_ROW}
      now ${first}"
    appended="$(sed -n '2p' "$W/loop-verdicts")"
    want="$(box_loop_ledger | sed -n '2p') box=i-up1"
    [ "$appended" = "$want" ] &&
        ok "the MIDDLE row — the one the log names — came home VERBATIM with ' box=' appended" ||
        bad "the appended row is not the box's row + ' box=':
      got  ${appended}
      want ${want}"
    out_has "harvested: loop-v1:$(hex64 b) tree=bbbb222 box=i-up1" &&
        ok "it says what it harvested, from which tree, off which box" ||
        bad "the harvested line is not the shape the design states: $(cat "$W/out")"
    out_has "banked: tree bbbb222 key loop-v1:$(hex64 b) box=i-up1" &&
        ok "and it prints the report's own \`banked:\` line, so the builder pastes rather than composes it" ||
        bad "the report's banked line was not printed: $(cat "$W/out")"
    # THE LEDGER IS READ THROUGH gate_ledger.sh's OWN PATH FUNCTION, never a
    # second spelling of where verdicts live. A wrapper that wrote its own
    # `.git/djb-loop-verdicts` would be a second writer of a file with one
    # owner, and the day the path moves the harvested rows go somewhere the
    # consult never looks.
    grep -F 'loop_ledger_path' "$VB" >/dev/null &&
        ok "the local ledger's path comes from gate_ledger.sh, not from a second spelling" ||
        bad "the wrapper spells the loop ledger's path itself — that is a second writer"
}

case_harvest_refuses_a_log_that_banked_nothing() {
    CURRENT=case_harvest_refuses_a_log_that_banked_nothing
    # A `--mine` run and a RED run both bank nothing, and both leave a log that
    # looks entirely normal. A harvest that shrugged at one would leave the
    # builder's report carrying a `banked:` line for a verdict that does not
    # exist.
    world_new harvest_nothing_banked
    world_harvest_ready
    {
        printf 'ok: loop checks passed (136s)\n'
        printf '  not banked: --mine — the closure was not walked, so this green is a\n'
        printf '  claim about one app.\n'
    } >"$REC/ssh/1.out"
    box_loop_ledger >"$REC/ssh/2.out"
    vb DJB_LOOP_LEDGER="$W/loop-verdicts" -- harvest i-up1 loop-a-rung
    [ "$VB_RC" = "2" ] && ok "a log that banked nothing is exit 2" ||
        bad "a log with no banked verdict exited ${VB_RC}"
    local n
    n="$(grep -c . "$W/loop-verdicts" || true)"
    [ "$n" = "1" ] && ok "and nothing was appended" || bad "${n} row(s) in the local ledger, wanted 1"
    said "banks no verdict" && ok "and the refusal says why, naming the log" ||
        bad "the refusal does not say the log banked nothing: $(cat "$W/err")"

    # AND A KEY THE BOX'S OWN LEDGER HAS NO ROW FOR. The log said a verdict was
    # banked; the ledger it was banked into does not have it. That is a
    # could-not-look about the transport or the box, never a row invented here.
    world_new harvest_no_row
    world_harvest_ready
    box_loop_log >"$REC/ssh/1.out"
    box_loop_ledger | sed -n '1p;3p' >"$REC/ssh/2.out"
    vb DJB_LOOP_LEDGER="$W/loop-verdicts" -- harvest i-up1 loop-a-rung
    [ "$VB_RC" = "2" ] && ok "a key the box's ledger has no row for is exit 2" ||
        bad "a missing row exited ${VB_RC}"
    n="$(grep -c . "$W/loop-verdicts" || true)"
    [ "$n" = "1" ] && ok "and nothing was appended" || bad "${n} row(s) in the local ledger, wanted 1"
    said "$(hex64 b)" && ok "and the refusal names the key it could not find" ||
        bad "the refusal does not name the key: $(cat "$W/err")"
}

case_harvest_twice_is_one_row() {
    CURRENT=case_harvest_twice_is_one_row
    # AT-LEAST-ONCE IS THE ASSUMPTION EVERYWHERE HERE. A builder who re-runs
    # the command, or a brief that lists it twice, must not leave two rows for
    # one measurement — the consult takes the LAST matching row, and two of
    # them is a count nobody can read afterwards.
    world_new harvest_twice
    world_harvest_ready
    # THREE SSH CALLS PER HARVEST, NOT TWO: the log, the box's loop ledger, and
    # the box's GATE ledger — the drive rows travel home beside the loop row.
    box_loop_log >"$REC/ssh/1.out"
    box_loop_ledger >"$REC/ssh/2.out"
    box_loop_log >"$REC/ssh/4.out"
    box_loop_ledger >"$REC/ssh/5.out"
    vb DJB_LOOP_LEDGER="$W/loop-verdicts" -- harvest i-up1 loop-a-rung
    [ "$VB_RC" = "0" ] || {
        bad "the first harvest exited ${VB_RC}"
        report
        return
    }
    local before after
    before="$(cat "$W/loop-verdicts")"
    vb DJB_LOOP_LEDGER="$W/loop-verdicts" -- harvest i-up1 loop-a-rung
    [ "$VB_RC" = "0" ] && ok "a second harvest of the same key is exit 0, not a refusal" ||
        bad "the second harvest exited ${VB_RC}"
    after="$(cat "$W/loop-verdicts")"
    [ "$before" = "$after" ] && ok "and the ledger is byte-identical — one measurement, one row" ||
        bad "the second harvest changed the ledger:
      before ${before}
      after  ${after}"
    said "already harvested" && ok "and it says the row was already home" ||
        bad "the second harvest does not say the row was already home: $(cat "$W/out")"
}

# --- the drive rows travel ---------------------------------------------------
#
# WHY THERE IS A CARRIER AT ALL. `scripts/gate_ledger.sh` banks one verdict per
# DRIVE, keyed on what that drive declares it drives plus the machine; the
# selftest leg does not re-run a banked drive. That ledger lives in `.git/` and
# no push carries it, so every fresh verifier box arrived with an empty one and
# re-drove all thirty — measured on the first on-box bank. With the machine half
# now the IMAGE id, a row banked on one box of an image is a row every box of
# that image may honour, and the only missing piece was a way over.
case_push_sends_only_the_drive_rows() {
    CURRENT=case_push_sends_only_the_drive_rows
    world_new push_drive_rows
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
    printf 'a-rung\n' >"$W/vhome/i-up1/rung"
    # SIX ROWS, THREE KINDS. A `full` row vouches for a whole gate over a whole
    # tree in a whole environment and a `loop` row for a scope; shipping either
    # to a box would hand it a verdict it could reuse for a measurement it never
    # made. A `drive` row is keyed on bytes and a machine the box re-derives for
    # itself, which is what makes it the one kind that is safe to carry.
    local ledger="$W/gate-verdicts"
    {
        printf 'v1 drive-v1:aaa drive 2026-09-18T10:00:00Z sweep exit=0 took=9 tree=t1 parts=p:1\n'
        printf 'v1 fullkey1 full 2026-09-18T10:01:00Z ruff,mypy exit=0 took=900 tree=t1\n'
        printf 'v1 drive-v1:bbb drive 2026-09-18T10:02:00Z db_pin exit=0 took=4 tree=t1 parts=p:2\n'
        printf 'loop-v1 loop-v1:ccc loop 2026-09-18T10:03:00Z caller=unstated tree=t1\n'
        printf 'v1 drive-v1:ddd drive 2026-09-18T10:04:00Z loop_scope exit=0 took=180 tree=t1 parts=p:3\n'
        printf 'v1 fullkey2 full 2026-09-18T10:05:00Z ruff,mypy exit=0 took=880 tree=t0\n'
    } >"$ledger"
    vb DJB_GATE_LEDGER="$ledger" -- push i-up1
    [ "$VB_RC" = "0" ] || {
        bad "push exited ${VB_RC}"
        report
        return
    }
    local n call
    n="$(grep -c . "$REC/scp.flat" 2>/dev/null || true)"
    [ "$n" = "1" ] && ok "exactly one scp — the rows go in the one call the transport already makes" ||
        bad "${n} scp call(s), wanted 1: $(cat "$REC/scp.flat" 2>/dev/null || true)"
    call="$(cat "$REC/scp.flat" 2>/dev/null || true)"
    case "$call" in
    *"ProxyCommand=aws ssm start-session"*) ok "and it tunnels through the same Session Manager document every other call here does" ;;
    *) bad "the scp does not carry the transport: ${call}" ;;
    esac
    case "$call" in
    *"@i-up1:verify/a-rung/ledger.in"*) ok "aimed at ~/verify/<rung>/ledger.in on the box, named after the rung the box was claimed for" ;;
    *) bad "the destination is not the rung's ledger.in: ${call}" ;;
    esac
    # THE BYTES, AND NOT THE ARGV. This is the whole claim.
    # THE BYTES OF THE ONE FILE THAT WENT, sliced by the header the shim writes
    # in front of each payload — never "everything after line 1", which would
    # be a claim about whatever else the call happened to carry.
    local sent
    sent="$(awk '/^--- /{cur = $2; next} cur ~ /\.ledger-out-/ {print}' "$REC/scp.payload" 2>/dev/null || true)"
    local want
    want="$(grep -F ' drive ' "$ledger")"
    [ "$sent" = "$want" ] &&
        ok "the file holds exactly the 3 \`drive\` rows, byte-identical, and neither \`full\` nor the \`loop\` row" ||
        bad "the carried rows are not the ledger's drive rows:
      got  $(printf '%s' "$sent" | tr '\n' '|')
      want $(printf '%s' "$want" | tr '\n' '|')"
    # AND NOTHING WAS INGESTED BY THE PUSH. The file lands; the box reads it
    # when `loop` or `leg` runs, and not before — so a push that is never
    # followed by a run changes nothing over there.
    local ingested="" f
    for f in "$REC"/ssh/*.flat; do
        [ -r "$f" ] || continue
        case "$(cat "$f")" in
        *"ledger.in"*"djb-gate-verdicts"*) ingested="$(cat "$f")" ;;
        esac
    done
    [ -z "$ingested" ] &&
        ok "and the push ingests nothing — the file lands, and \`loop\`/\`leg\` read it" ||
        bad "the push ran the ingest itself: ${ingested}"

    # AN EMPTY LEDGER SENDS NOTHING AND SAYS SO. A silent no-op here is a box
    # that re-drives everything for a reason nobody can see in the log.
    world_new push_drive_rows_empty
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
    printf 'a-rung\n' >"$W/vhome/i-up1/rung"
    : >"$W/gate-verdicts-empty"
    vb DJB_GATE_LEDGER="$W/gate-verdicts-empty" -- push i-up1
    [ "$VB_RC" = "0" ] || {
        bad "the push over an empty ledger exited ${VB_RC}"
        report
        return
    }
    # COUNTED WITH awk OVER A FILE THAT MAY NOT EXIST — `grep -c` answers 1 and
    # writes to stderr when the file is absent, which is the shape "no call at
    # all" takes and the one this arm is about.
    n="$(awk 'END { print NR + 0 }' "$REC/scp.flat" 2>/dev/null || echo 0)"
    [ "$n" = "0" ] && ok "an empty ledger sends no file at all" ||
        bad "${n} scp call(s) over an empty ledger: $(cat "$REC/scp.flat" 2>/dev/null || true)"
    out_has "drive rows: none to send" &&
        ok "and it says so, in one line" ||
        bad "the push is silent about having no rows to send: $(cat "$W/out")"
}

case_harvest_brings_the_drive_rows_of_the_banked_tree() {
    CURRENT=case_harvest_brings_the_drive_rows_of_the_banked_tree
    world_new harvest_drive_rows
    world_harvest_ready
    box_loop_log >"$REC/ssh/1.out"
    box_loop_ledger >"$REC/ssh/2.out"
    # THE BOX'S GATE LEDGER, ssh #3. Two drive rows at the tree the harvested
    # loop row names (`bbbb222`, the middle row of `box_loop_ledger`) and one at
    # a tree this harvest is not about — a box may have measured for somebody
    # else, and that is somebody else's evidence.
    {
        printf 'v1 drive-v1:box1 drive 2026-09-18T10:05:01Z sweep exit=0 took=9 tree=bbbb222 parts=p:1\n'
        printf 'v1 drive-v1:other drive 2026-09-18T09:00:00Z sweep exit=0 took=9 tree=zzzz999 parts=p:9\n'
        printf 'v1 drive-v1:box2 drive 2026-09-18T10:05:02Z db_pin exit=0 took=4 tree=bbbb222 parts=p:2\n'
    } >"$REC/ssh/3.out"
    local gl="$W/gate-verdicts"
    local kept='v1 drive-v1:mine drive 2026-09-17T08:00:00Z sweep exit=0 took=9 tree=dddd444 parts=p:0'
    printf '%s\n' "$kept" >"$gl"
    vb DJB_LOOP_LEDGER="$W/loop-verdicts" DJB_GATE_LEDGER="$gl" -- harvest i-up1 loop-a-rung
    [ "$VB_RC" = "0" ] || {
        bad "harvest exited ${VB_RC}"
        report
        return
    }
    local n
    n="$(grep -c . "$gl" || true)"
    [ "$n" = "3" ] && ok "the two drive rows at the harvested tree came home (1 already here + 2)" ||
        bad "${n} row(s) in the local gate ledger, wanted 3: $(tr '\n' '|' <"$gl")"
    [ "$(sed -n '1p' "$gl")" = "$kept" ] &&
        ok "and every row that was already here is byte-identical" ||
        bad "the pre-existing gate row changed: $(sed -n '1p' "$gl")"
    grep -qxF 'v1 drive-v1:box1 drive 2026-09-18T10:05:01Z sweep exit=0 took=9 tree=bbbb222 parts=p:1' "$gl" &&
        grep -qxF 'v1 drive-v1:box2 drive 2026-09-18T10:05:02Z db_pin exit=0 took=4 tree=bbbb222 parts=p:2' "$gl" &&
        ok "both rows arrived VERBATIM — a row composed here would be this machine's opinion of the box's measurement" ||
        bad "the box's rows did not arrive verbatim: $(tr '\n' '|' <"$gl")"
    grep -qF 'drive-v1:other' "$gl" &&
        bad "a drive row at ANOTHER tree came home — this command is about one measurement" ||
        ok "the row at another tree stayed on the box"
    out_has "drive rows: 2 brought home at tree=bbbb222" &&
        ok "and it says how many, at which tree" ||
        bad "the harvest is silent about the drive rows: $(cat "$W/out")"

    # TWICE IS ONCE. At-least-once is the assumption everywhere here, and the
    # loop row's own already-home path must not swallow the drive rows either.
    box_loop_log >"$REC/ssh/4.out"
    box_loop_ledger >"$REC/ssh/5.out"
    cat "$REC/ssh/3.out" >"$REC/ssh/6.out"
    local before
    before="$(cat "$gl")"
    vb DJB_LOOP_LEDGER="$W/loop-verdicts" DJB_GATE_LEDGER="$gl" -- harvest i-up1 loop-a-rung
    [ "$VB_RC" = "0" ] && ok "a second harvest is exit 0, not a refusal" ||
        bad "the second harvest exited ${VB_RC}"
    [ "$before" = "$(cat "$gl")" ] &&
        ok "and the gate ledger is byte-identical — one measurement, one row" ||
        bad "the second harvest changed the gate ledger:
      before $(printf '%s' "$before" | tr '\n' '|')
      after  $(tr '\n' '|' <"$gl")"
    out_has "drive rows: 0 brought home at tree=bbbb222 (2 already here)" &&
        ok "and it says both numbers, so 'nothing happened' and 'nothing was found' read differently" ||
        bad "the second harvest does not distinguish already-here from none-found: $(cat "$W/out")"
}

case_the_wrapper_reaches_python_only_through_the_checkout() {
    CURRENT=case_the_wrapper_reaches_python_only_through_the_checkout
    # HOUSE RULE: A PYTHON THIS REPOSITORY SHIPS RUNS ON THIS CHECKOUT'S
    # INTERPRETER, and `python3` off PATH is some other environment's. This
    # wrapper had four inline `python3 -c` date programs and no way to reach
    # `checkout_python` without sourcing the gate's refusal library into a
    # script that runs before a venv exists — so the date arithmetic is the
    # shape `deploy/verifier/idle_reaper.sh` already settled on for the same
    # problem on a box with no venv at all: bash arithmetic, with `date` asked
    # for exactly one thing, the current epoch second. That also makes the
    # parse DRIVABLE rather than a property of whichever coreutils the machine
    # happens to have — which is the property the two directions below rest on.
    local hits
    hits="$(grep -nE '(^|[^A-Za-z0-9_])python3?([^A-Za-z0-9_]|$)' "$VB" || true)"
    [ -z "$hits" ] && ok "no python in ${VB} at all — every date it needs it computes" ||
        bad "the wrapper still reaches a python:
$(printf '%s\n' "$hits" | sed 's/^/      /')"
    hits="$(grep -nE 'date[^|]*[+-]%[a-zA-Z]' "$VB" | grep -vE "date \+%s" || true)"
    [ -z "$hits" ] && ok "and it asks date(1) for nothing but the current epoch second" ||
        bad "a date(1) format string that is not \`+%s\` — GNU and BSD do not agree about those:
$(printf '%s\n' "$hits" | sed 's/^/      /')"

    # AND BOTH DIRECTIONS ARE DRIVEN THROUGH THE WRAPPER'S OWN DOORS, over a
    # span that crosses a leap day, a month with a LEADING ZERO (bash reads
    # `08` as octal, and that is how every August instant became unparsable in
    # the reaper this arithmetic is copied from) and a year boundary. The
    # expected values come from python HERE — a second implementation on
    # purpose, so the arithmetic is never checked against itself.
    #
    # epoch → ISO is what `up` writes into `djb:expires`; ISO → epoch is what
    # `census` subtracts to decide OVERDUE. One instant, both directions.
    local want iso_expected tag bad_at="" now exp
    for want in 1704067199 1709164800 1755000000 1767225600 2145916800; do
        world_new "clock_${want}"
        world_up_ready
        printf '%s\n' "$want" >"$REC/clock"
        iso_expected="$(iso_utc $((want + 3600)))"
        vb -- up --for X --ttl 1
        tag="$(printf '%s' "$(nth_call_of "run-instances" 1 || true)" |
            grep -oE 'Key=djb:expires,Value=[0-9TZ:-]+' || true)"
        tag="${tag%%$'\n'*}"
        tag="${tag##*=}"
        [ "$tag" = "$iso_expected" ] || bad_at="${bad_at} epoch→iso ${want}(${tag:-empty}≠${iso_expected})"
    done
    [ -z "$bad_at" ] && ok "epoch→ISO agrees with python's at every instant tried, leap day and leading zeros included" ||
        bad "the clock arithmetic disagrees with python's at:${bad_at}"

    bad_at=""
    for want in 1704067199 1709164800 1755000000 1767225600; do
        world_new "clock_back_${want}"
        printf '%s\n' "$want" >"$REC/clock"
        now="$want"
        # One minute PAST its expiry, and one minute short of it: the
        # subtraction either lands on the right side of the instant or the
        # census reaps a box that is fine and leaves one that is billing.
        exp="$(iso_utc $((now - 60)))"
        printf 'i-x1\tc7g.4xlarge\tverifier\t%s\t%s\t%s\tami-v1\n' \
            "$OWNER" "$exp" "$(iso_utc $((now - 600)))" \
            >"$REC/ans/ec2_describe-instances__ReservationsInstancesInstanceIdInstance"
        vb -- census
        [ "$VB_RC" = "1" ] || bad_at="${bad_at} overdue@${exp}(exit ${VB_RC})"
        world_new "clock_fwd_${want}"
        printf '%s\n' "$want" >"$REC/clock"
        exp="$(iso_utc $((now + 60)))"
        printf 'i-x1\tc7g.4xlarge\tverifier\t%s\t%s\t%s\tami-v1\n' \
            "$OWNER" "$exp" "$(iso_utc $((now - 600)))" \
            >"$REC/ans/ec2_describe-instances__ReservationsInstancesInstanceIdInstance"
        vb -- census
        [ "$VB_RC" = "0" ] || bad_at="${bad_at} not-yet@${exp}(exit ${VB_RC})"
    done
    [ -z "$bad_at" ] && ok "ISO→epoch puts the census on the right side of every expiry tried" ||
        bad "the census's subtraction is wrong at:${bad_at}"
}

case_fetch_uses_the_same_transport() {
    CURRENT=case_fetch_uses_the_same_transport
    world_new fetch_ok
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
    vb -- fetch i-up1 '~/verify/x/v1.log' "$W/v1.log"
    [ "$VB_RC" = "0" ] || {
        bad "fetch exited ${VB_RC}"
        report
        return
    }
    local n call
    n="$(grep -c . "$REC/scp.flat" 2>/dev/null || echo 0)"
    call="$(cat "$REC/scp.flat" 2>/dev/null || true)"
    [ "$n" = "1" ] && ok "exactly one scp" || bad "${n} scp call(s)"
    case "$call" in
    *"ProxyCommand=aws ssm start-session"*"verifier@i-up1:~/verify/x/v1.log"*)
        ok "the scp tunnels through the same Session Manager document" ;;
    *) bad "the scp does not carry the transport: ${call}" ;;
    esac
}

# =============================================================================
# 1.8 — push, and the tree agreement
# =============================================================================

case_push_reads_the_checkout_path_out_of_the_recipe() {
    CURRENT=case_push_reads_the_checkout_path_out_of_the_recipe
    world_new push_ok
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
    vb -- push i-up1 rung/x
    [ "$VB_RC" = "0" ] || {
        bad "push exited ${VB_RC}"
        report
        return
    }
    # The path is the recipe's knob, derived here the same way a reader would.
    local user path expect
    user="$(sed -n 's|^BAKE_USER="\${DJB_VERIFIER_BAKE_USER:-\(.*\)}"$|\1|p' "$BAKE")"
    user="${user%%$'\n'*}"
    path="$(sed -n 's|^BAKE_CHECKOUT="\${DJB_VERIFIER_CHECKOUT:-\(.*\)}"$|\1|p' "$BAKE")"
    path="${path%%$'\n'*}"
    expect="ssh://${user}@i-up1${path//\$\{BAKE_USER\}/$user}"
    # ONE REF PER PUSH, so the target is asserted on each of them rather than on
    # one combined line: a shallow source cannot send two refs in one
    # invocation (the real-git case further down measures it).
    local call missing=""
    call="$(cat "$REC/git.flat" 2>/dev/null || true)"
    case "$call" in
    *"push --force ${expect} refs/heads/main:refs/heads/main "*) ;;
    *) missing="${missing} the-tree" ;;
    esac
    case "$call" in
    *"push --force ${expect} refs/heads/rung/x:refs/heads/rung/x "*) ;;
    *) missing="${missing} the-named-branch" ;;
    esac
    if [ -z "$missing" ]; then
        ok "every push's target is the recipe's own knob: ${expect}"
    else
        bad "wanted '${expect}' for each ref (missing:${missing}), recorded: ${call}"
    fi
    # AND NEVER `main:main`. From a rung's WORKTREE that names main's tree
    # rather than the tree the operator is standing in — the pre-push hook
    # vouches for what is on stdin, found no verdict for it and refused, after
    # a bake box was already up and billing. HEAD is the one tree a checkout
    # can vouch for.
    if printf '%s' "$call" | grep -E '(^| )main:main( |$)' >/dev/null; then
        bad "the push still carries a branch by NAME (main:main): ${call}"
    else
        ok "no 'main:main' anywhere in the push — a branch by name is never what a checkout can vouch for"
    fi
    grep -F "ProxyCommand=aws ssm start-session" "$REC/git.env" >/dev/null &&
        ok "GIT_SSH_COMMAND carries the tunnel" ||
        bad "GIT_SSH_COMMAND does not carry the ProxyCommand: $(cat "$REC/git.env" 2>/dev/null)"
    # And nothing else in the tree spells the path.
    #
    # `--include` GOES BEFORE THE `--`, and that is not a style point. `--` ends
    # the options, so `grep -rIn -- <pat> scripts deploy --include='*.sh'` hands
    # grep a FILE called `--include=*.sh`: grep printed
    # `grep: --include=*.sh: No such file or directory` into every gate log that
    # ran this leg, exited 2 into a `|| true` that swallowed it, and searched
    # every file under scripts/ and deploy/ instead of the shell ones. The
    # stderr is captured and asserted empty below so the next one cannot be
    # silent either.
    local elsewhere greperr
    greperr="$W/pathcensus.err"
    elsewhere="$(grep -rIn --include='*.sh' -- "${path//\$\{BAKE_USER\}/$user}" scripts deploy 2>"$greperr" |
        grep -v "^${BAKE}:" | grep -v "^scripts/tests/test_verifier_box.sh:" || true)"
    [ -z "$elsewhere" ] && ok "no other shell file re-spells the path" ||
        bad "the path is spelled outside the recipe:
${elsewhere}"
    [ ! -s "$greperr" ] && ok "and the census itself looked at what it meant to look at" ||
        bad "the census said something on stderr, which means it did not scan what it thinks it did:
      $(cat "$greperr")"
}

# `ssh -G` RESOLVES A CONFIGURATION AND NEVER OPENS A CONNECTION — but only
# while `-G` is still being read as an option when ssh reaches it. A
# ProxyCommand that fell apart leaves a bare word in front of it, ssh takes
# that word as the destination, and everything after it is the remote command:
# the resolution then tries to OPEN the session instead of printing it, and
# prints no `proxycommand` line at all. That is the defect making itself
# visible one layer earlier than the field test saw it, and it is why the
# failure text below pastes what ssh said and what the proxy actually ran.
#
# The `ssh` asked is the REAL one — a shimmed ssh would answer the question
# against itself — and the `aws` on its PATH is a stub that records its
# arguments and exits, so a resolution that does try to connect spends nothing
# and still says what the ProxyCommand had shrunk to.
_resolve_proxycommand() {
    local out="$W/resolve.out"
    : >"$out"
    case "$1" in
    --string)
        shift
        # GIT'S OWN SEMANTICS: `GIT_SSH_COMMAND` is a STRING, handed to a
        # shell, split on whitespace by it.
        env PATH="$W/gbin:/usr/bin:/bin" HOME="$W/home" PROXY_RAN="$W/proxy.ran" \
            sh -c "$1 -G djb-resolve-only" >"$out" 2>&1 || true
        ;;
    --argv)
        shift
        # `ssh_to` and `cmd_fetch` pass the option as ONE argument: no shell,
        # nothing to split.
        env PATH="$W/gbin:/usr/bin:/bin" HOME="$W/home" PROXY_RAN="$W/proxy.ran" \
            "$W/gbin/ssh" "$@" -G djb-resolve-only >"$out" 2>&1 || true
        ;;
    esac
    sed -n 's/^[Pp]roxy[Cc]ommand //p' "$out" | tail -n 1
}

# The leading options of a recorded argv, one argument per line, stopping at
# the destination — which is where ssh's own option parsing stops too.
_ssh_options_from_args() {
    OPTS=()
    local a v
    while IFS= read -r a; do
        case "$a" in
        -i | -o | -F | -l | -p | -b | -c | -E)
            IFS= read -r v || v=""
            OPTS+=("$a" "$v")
            ;;
        -*) OPTS+=("$a") ;;
        *) break ;;
        esac
    done <"$1"
}

# GIT HANDS `GIT_SSH_COMMAND` TO A SHELL, AND A SHELL SPLITS ON WHITESPACE.
# The ProxyCommand is one option value with eight spaces in it, so it stays one
# option only if the string quotes it — and an argv-shaped record cannot tell
# the two apart: `-o` `ProxyCommand=aws ssm …` and `-o` `ProxyCommand=aws`
# `ssm` `start-session` … flatten to the same characters, which is why
# `case_push_reads_the_checkout_path_out_of_the_recipe`'s grep was green while
# the transport was broken. FIELD TEST 1 met it on the first real box:
# `aws: [ERROR]: … the following arguments are required: command`, then
# `Connection closed by UNKNOWN port 65535`, exit 128.
#
# So this case resolves each door's record the way that door's own caller does
# — the string through `sh -c`, the argv straight through — and then reads
# back the configuration ssh actually built.
case_the_push_transport_survives_the_shell_git_runs_it_in() {
    CURRENT=case_the_push_transport_survives_the_shell_git_runs_it_in
    world_new push_shell
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"

    local real_ssh
    real_ssh="$(PATH=/usr/bin:/bin command -v ssh || true)"
    [ -n "$real_ssh" ] && [ -x "$real_ssh" ] ||
        cannot_look "no real ssh on this machine — a shimmed one cannot resolve a configuration"
    mkdir -p "$W/gbin"
    ln -sf "$real_ssh" "$W/gbin/ssh"
    cat >"$W/gbin/aws" <<'STUB'
#!/usr/bin/env bash
printf 'aws %s\n' "$*" >>"$PROXY_RAN"
exit 0
STUB
    chmod +x "$W/gbin/aws"

    vb -- push i-up1 rung/x
    [ "$VB_RC" = "0" ] || {
        bad "push exited ${VB_RC}"
        report
        return
    }
    vb -- run i-up1 -- true
    vb -- fetch i-up1 '~/verify/x/v1.log' "$W/v1.log"

    # `proxy_command`'s whole output. `ssh -G` prints it back verbatim: %h and
    # %p are expanded when a session opens, not when a configuration is
    # printed, so the token is the assertion rather than a substitution of it.
    local want
    want="aws ssm start-session --target %h --document-name AWS-StartSSHSession"
    want="${want} --parameters portNumber=%p --profile ${NS}-verifier --region ${RG}"

    local gitssh got
    # THE LAST CALL THAT CARRIED A TRANSPORT, not the last call. The push is
    # followed now by local git reads (the worktree agreement) whose environment
    # carries no GIT_SSH_COMMAND at all, and `tail -n 1` over every call would
    # read one of those and report a transport that was never missing.
    gitssh="$(grep -v '=<unset>$' "$REC/git.env" | sed -n 's/^GIT_SSH_COMMAND=//p' | tail -n 1)"
    got="$(_resolve_proxycommand --string "$gitssh")"
    [ "$got" = "$want" ] && ok "git's own shell keeps push's ProxyCommand whole: proxycommand ${got}" ||
        bad "git splits GIT_SSH_COMMAND on whitespace and the ProxyCommand did not survive it.
      wanted    proxycommand ${want}
      resolved  ${got:-<no proxycommand line — ssh never reached -G>}
      ssh said  $(head -n 2 "$W/resolve.out" 2>/dev/null | tr '\n' ' ')
      the proxy it ran: $(tail -n 1 "$W/proxy.ran" 2>/dev/null || echo '<none>')
      the string: ${gitssh}"

    local -a OPTS=()
    _ssh_options_from_args "$REC/ssh/1.args"
    got="$(_resolve_proxycommand --argv "${OPTS[@]+"${OPTS[@]}"}")"
    [ "$got" = "$want" ] && ok "ssh_to's argv carries the ProxyCommand whole" ||
        bad "ssh_to's ProxyCommand resolved to '${got:-<none>}', wanted '${want}'"

    _ssh_options_from_args "$REC/scp.args"
    got="$(_resolve_proxycommand --argv "${OPTS[@]+"${OPTS[@]}"}")"
    [ "$got" = "$want" ] && ok "cmd_fetch's argv carries the ProxyCommand whole" ||
        bad "cmd_fetch's ProxyCommand resolved to '${got:-<none>}', wanted '${want}'"
}

# THE TRANSFER IS THE TREE, NOT THE HISTORY. Pushing a branch into an empty
# repository sends every object reachable from it — 213 MB of this
# repository's history, 655 s of a 739 s bake on a good tunnel, and a stall
# that never finished on a bad one. What a verification needs is the TREE, and
# git has no `push --depth`: what it sends is decided by what the remote
# already has, so the only lever is a shallow SOURCE. Measured on this
# checkout while this case was written: 9.6 MB against 222 MB.
# --- one ref per push, and why it is not a preference -------------------------
#
# A SHALLOW SOURCE CANNOT SEND TWO REFS IN ONE INVOCATION. The case below builds
# the three real repositories — a source, a shallow mirror of it, and a receiver
# shaped like a verifier box (non-bare, parked off `main`,
# `receive.shallowUpdate` and `receive.denyCurrentBranch=updateInstead`) — and
# measures git itself. It is the one case in this drive that does NOT use the
# git shim, deliberately: the property belongs to git and a shim would be this
# drive asserting its own fixture.
#
# WHAT IT COSTS TO GET WRONG. The first ref LANDS and the status is still 1, so
# the box holds the tree while every caller reads a failure — `up` refuses after
# a push that worked, and a bake's teardown takes the box down for it.
real_git_box_world() {
    local w="$1" src="$w/src" box="$2"
    git init -q "$src" || return 1
    git -C "$src" symbolic-ref HEAD refs/heads/main
    git -C "$src" config user.email drive@example.invalid
    git -C "$src" config user.name "verifier box drive"
    echo base >"$src/a.txt"
    git -C "$src" add -A && git -C "$src" commit -q -m base
    echo more >"$src/b.txt"
    git -C "$src" add -A && git -C "$src" commit -q -m "on main"
    git -C "$src" checkout -q -b rung
    echo work >"$src/rung.txt"
    git -C "$src" add -A && git -C "$src" commit -q -m "rung work"
    # THE RECEIVER, in the shape the box's own user-data leaves it: a working
    # checkout parked off `main` so a push to `main` is never a push to a
    # checked-out branch.
    git init -q "$box" || return 1
    git -C "$box" config user.email drive@example.invalid
    git -C "$box" config user.name "verifier box drive"
    git -C "$box" config receive.denyCurrentBranch updateInstead
    git -C "$box" config receive.shallowUpdate true
    echo seed >"$box/seed.txt"
    git -C "$box" add -A && git -C "$box" commit -q -m seed
    git -C "$box" checkout -q -b verifier-parking
    return 0
}

case_a_shallow_mirror_cannot_send_two_refs_in_one_push() {
    CURRENT=case_a_shallow_mirror_cannot_send_two_refs_in_one_push
    # NO COUNTER: this drive numbers its worlds by NAME (`world_new`), and this
    # case builds real repositories rather than a world, so it owns one
    # directory of its own under the scratch root.
    local w="${WORK}/realgit" src box mirror base rc=0 out
    rm -rf "$w"
    mkdir -p "$w"
    src="$w/src"
    box="$w/box"
    mirror="$w/mirror"
    out="${w}/push.log"
    real_git_box_world "$w" "$box" ||
        cannot_look "could not build the three real repositories this case measures git in"
    base="$(git -C "$src" merge-base rung main)"
    git init -q --bare "$mirror"
    git -C "$mirror" fetch -q --depth 2 "file://${src}" "+HEAD:refs/heads/main" ||
        cannot_look "could not build a shallow mirror of the scratch source"
    git -C "$mirror" update-ref refs/djb/base "$base"
    [ -f "$mirror/shallow" ] ||
        cannot_look "the mirror is not shallow — this case would measure nothing"

    # THE SHAPE THAT WAS SHIPPED: both refs, one invocation.
    git -C "$mirror" push --force "$box" \
        refs/heads/main:refs/heads/main refs/djb/base:refs/djb/base >"$out" 2>&1 || rc=$?
    if [ "$rc" != "0" ] && grep -F "remote failed to report status" "$out" >/dev/null; then
        ok "two refs in one push from a shallow mirror FAILS, exit ${rc}, 'remote failed to report status'"
    else
        bad "two refs in one push exited ${rc} without that failure — this machine's git does not reproduce the blocker, and the split below is being asserted against nothing:
$(sed 's/^/        /' "$out")"
    fi
    # AND THE HALF THAT MAKES IT EXPENSIVE: the first ref landed anyway.
    if [ -n "$(git -C "$box" rev-parse -q --verify refs/heads/main || true)" ] &&
        [ -z "$(git -C "$box" rev-parse -q --verify refs/djb/base || true)" ]; then
        ok "and it is the worst shape of failure: main LANDED, the base did not, the status is non-zero"
    else
        bad "the box's refs after the one-push attempt are not main-without-base — main=$(git -C "$box" rev-parse -q --verify refs/heads/main || echo none) base=$(git -C "$box" rev-parse -q --verify refs/djb/base || echo none)"
    fi

    # THE SPLIT, ON A FRESH RECEIVER: the same mirror, two invocations.
    local box2="$w/box2" rc1=0 rc2=0
    git init -q "$box2"
    git -C "$box2" config user.email drive@example.invalid
    git -C "$box2" config user.name "verifier box drive"
    git -C "$box2" config receive.denyCurrentBranch updateInstead
    git -C "$box2" config receive.shallowUpdate true
    echo seed >"$box2/seed.txt"
    git -C "$box2" add -A && git -C "$box2" commit -q -m seed
    git -C "$box2" checkout -q -b verifier-parking
    git -C "$mirror" push --force "$box2" refs/djb/base:refs/djb/base >>"$out" 2>&1 || rc1=$?
    git -C "$mirror" push --force "$box2" refs/heads/main:refs/heads/main >>"$out" 2>&1 || rc2=$?
    [ "${rc1}/${rc2}" = "0/0" ] && ok "the same shallow mirror sends both in two SEPARATE pushes, exit 0 twice" ||
        bad "the split pushes exited ${rc1} and ${rc2}"
    if [ -n "$(git -C "$box2" rev-parse -q --verify refs/heads/main || true)" ] &&
        [ "$(git -C "$box2" rev-parse -q --verify refs/djb/base || true)" = "$base" ]; then
        ok "and both refs are on the box: the fork point AND the tree"
    else
        bad "the split did not land both — main=$(git -C "$box2" rev-parse -q --verify refs/heads/main || echo none) base=$(git -C "$box2" rev-parse -q --verify refs/djb/base || echo none)"
    fi
    # IT IS NOT ABOUT `refs/djb/base`. `main` plus an ordinary second branch
    # fails identically, which is what makes this the multi-branch form of
    # `push`'s bug too and not a property of the new ref.
    local box3="$w/box3" rc3=0
    git init -q "$box3"
    git -C "$box3" config user.email drive@example.invalid
    git -C "$box3" config user.name "verifier box drive"
    git -C "$box3" config receive.denyCurrentBranch updateInstead
    git -C "$box3" config receive.shallowUpdate true
    echo seed >"$box3/seed.txt"
    git -C "$box3" add -A && git -C "$box3" commit -q -m seed
    git -C "$box3" checkout -q -b verifier-parking
    git -C "$mirror" fetch -q --depth 2 "file://${src}" "+refs/heads/rung:refs/heads/rung" 2>/dev/null || true
    git -C "$mirror" push --force "$box3" \
        refs/heads/main:refs/heads/main refs/heads/rung:refs/heads/rung >>"$out" 2>&1 || rc3=$?
    if [ "$rc3" != "0" ]; then
        ok "and it is not about refs/djb/base: main plus an ordinary branch fails the same way (exit ${rc3})"
    else
        bad "main plus an ordinary second branch succeeded from a shallow mirror — the rule this case states is narrower than it claims"
    fi
}

# --- a shallow push into a receiver that already has refs ---------------------
#
# WHAT IT COST. Three banks and a verification in a row died on the FIRST push
# into a freshly baked box, with `up` refusing after boxes were launched and
# paid for. The words the field saw were `remote: fatal: pack has 84 unresolved
# deltas` / `error: remote unpack failed: index-pack abnormal exit` /
# `! [remote rejected] refs/djb/base -> refs/djb/base (unpacker error)`; the
# words THIS machine's git gives for the same cause are `remote: error: Could
# not read <sha>` / `fatal: revision walk setup failed` / `! [remote rejected]
# main -> main (missing necessary objects)`. Two sentences, one mechanism, and
# the case below asserts the FAILURE rather than either sentence.
#
# THE MECHANISM, and it is not thin packs — which is worth pinning, because
# `--no-thin` is the fix everyone reaches for first and it does nothing here.
# A push sends only what the sender believes the receiver lacks, and it derives
# that belief from the refs the receiver ADVERTISES: `main = <the bake commit>`
# is read as "and therefore everything reachable from it". A freshly baked box
# is SHALLOW at that commit — it has that commit's own objects and not one of
# its ancestors' — so every object the sender omits on the strength of the
# advertisement is an object the receiver does not have. `--thin`/`--no-thin`
# governs only whether DELTA BASES may live outside the pack; the omission is
# driven by the advertised refs and no flag turns it off. A receiver that
# advertises NOTHING is assumed to have nothing, so the pack is complete, and
# that is the whole of the remedy.
#
# ALL THREE OUTCOMES ARE MEASURED HERE, because the wrong fix is green-looking:
# as shipped it fails, with `--no-thin` it fails IDENTICALLY, and with the box's
# refs cleared first it lands. A case that only measured the cure would leave
# the next reader free to "simplify" it to the flag.
#
# IT BUILDS ITS OWN OBJECT GRAPH and borrows nothing from the checkout it runs
# in — see `shallow_refs_source` below for the three ingredients and what each
# one is for.
#
# shallow_refs_source <dir> — the object graph the case below needs, built here
# and never borrowed from the checkout this drive is running in.
#
# WHY IT IS SYNTHESISED, AND WHY IT IS THIS SHAPE. The first version of the
# case read `main~20` out of the surrounding checkout. On this Mac that is
# fine; on a VERIFIER BOX the checkout IS the pushed tree at depth 2 — this
# wrapper's own push shape — so `main~20` does not exist and the whole drive
# exited 2, could-not-look, on every bank's selftest shard. A case whose world
# depends on the history of the repository it happens to live in is a case that
# cannot run where it matters most.
#
# THE THREE INGREDIENTS, each found by measurement and each load-bearing —
# eight synthetic graphs were built before one reproduced:
#
#   1. DELTA-WORTHY CONTENT. Every commit rewrites a large generated file, so
#      the sender has objects worth deltifying against history rather than
#      storing whole. With small files git sends everything and there is
#      nothing to omit.
#   2. SEVERAL LINEAGES CROSSING THE DEPTH FRONTIER. Long side branches forked
#      well back and merged in, so a `--depth N` fetch leaves the mirror with
#      MORE THAN ONE shallow boundary. A linear history gives exactly one, git
#      handles it, and the push succeeds — which is why every linear fixture
#      tried before this was green.
#   3. THE BAKE POINT NEAR THE TIP, with the mirror far deeper than it. The
#      receiver is shallow AT that commit while the sender holds its
#      ancestors, so the push un-shallows it and the receiver must then walk
#      into objects the sender omitted as "reachable from what you advertised".
#
# The case asserts the reproduction FIRES. A graph that stops reproducing it is
# a loud failure here, never a quiet pass.
shallow_refs_source() {
    local src="$1" r k n=0
    git init -q "$src" || return 1
    git -C "$src" symbolic-ref HEAD refs/heads/main || return 1
    git -C "$src" config user.email drive@example.invalid
    git -C "$src" config user.name "verifier box drive"
    shallow_refs_blob 0 >"$src/big.txt"
    git -C "$src" add -A && git -C "$src" commit -q -m c0 || return 1
    for r in 1 2 3 4 5 6; do
        if [ "$r" = 1 ]; then
            git -C "$src" checkout -q -b "lane${r}" main || return 1
        else
            git -C "$src" checkout -q -b "lane${r}" "main~3" || return 1
        fi
        for k in 1 2 3 4 5 6 7 8; do
            n=$((n + 1))
            shallow_refs_blob "$n" >"${src}/lane${r}.txt"
            git -C "$src" add -A && git -C "$src" commit -q -m "lane${r} c${k}" || return 1
        done
        git -C "$src" checkout -q main || return 1
        for k in 1 2 3; do
            n=$((n + 1))
            shallow_refs_blob "$n" >"$src/big.txt"
            git -C "$src" add -A && git -C "$src" commit -q -m "main ${n}" || return 1
        done
        git -C "$src" merge -q --no-ff "lane${r}" -m "merge lane${r}" >/dev/null 2>&1 || return 1
    done
    return 0
}

# shallow_refs_blob <n> — a few thousand lines that differ from every other n
# but share most of their shape with it: the content profile that makes git
# deltify rather than store whole, which is ingredient 1 above.
shallow_refs_blob() {
    awk -v n="$1" 'BEGIN {
        srand(n)
        for (j = 0; j < 2000; j++) printf "%d payloadpayloadpayload %d\n", j, int(rand() * 99999)
    }'
}

case_a_shallow_push_into_a_box_that_already_has_refs_is_refused() {
    CURRENT=case_a_shallow_push_into_a_box_that_already_has_refs_is_refused
    local w="${WORK}/shallow-refs" src box keep mirror bakemirror bake rc out tree_there tree_here

    rm -rf "$w"
    mkdir -p "$w" || cannot_look "could not make ${w}"
    box="$w/box"
    keep="$w/keep"
    mirror="$w/mirror"
    bakemirror="$w/bakemirror"
    out="$w/push.log"

    src="$w/src"
    shallow_refs_source "$src" ||
        cannot_look "could not build the source repository this case measures git in"
    bake="$(git -C "$src" rev-parse -q --verify "main~2" 2>/dev/null || true)"
    [ -n "$bake" ] ||
        cannot_look "the source this case just built has no main~2 — its own builder is broken"

    # THE BOX, IN THE SHAPE THE BAKE LEAVES IT: a working checkout whose history
    # arrived as a depth-1 SHALLOW push of the bake commit, parked off main. Not
    # a shallow CLONE — the bake box's own checkout is seeded by this very
    # wrapper's push, and the `.git/shallow` that leaves behind is the thing the
    # next push trips over.
    git init -q "$box" || cannot_look "could not init the box repository"
    git -C "$box" config user.email drive@example.invalid
    git -C "$box" config user.name "verifier box drive"
    git -C "$box" config receive.denyCurrentBranch updateInstead
    git -C "$box" config receive.shallowUpdate true
    git init -q --bare "$bakemirror" || cannot_look "could not init the bake mirror"
    git -C "$bakemirror" fetch -q --depth 1 "file://${src}" "+${bake}:refs/heads/main" ||
        cannot_look "could not build the bake's own depth-1 mirror"
    git -C "$bakemirror" push -q --force "file://${box}" refs/heads/main:refs/heads/main ||
        cannot_look "could not seed the box the way the bake seeds it"
    git -C "$box" checkout -q -B verifier-parking refs/heads/main ||
        cannot_look "could not park the box off main"
    [ -f "$box/.git/shallow" ] ||
        cannot_look "the seeded box is not shallow — this case would measure nothing"

    # THE SENDER: `push_the_tree_shallow`'s own mirror shape.
    git init -q --bare "$mirror" || cannot_look "could not init the mirror"
    git -C "$mirror" fetch -q --depth 24 "file://${src}" "+refs/heads/main:refs/heads/main" ||
        cannot_look "could not build a depth-24 mirror of the source"
    [ -f "$mirror/shallow" ] ||
        cannot_look "the mirror is not shallow — this case would measure nothing"
    cp -R "$box" "$keep" || cannot_look "could not keep a pristine copy of the box"

    # (a) AS SHIPPED BEFORE THIS RUNG — the field's own failure.
    rc=0
    git -C "$mirror" push --force "file://${box}" refs/heads/main:refs/heads/main >"$out" 2>&1 || rc=$?
    if [ "$rc" != "0" ]; then
        ok "a shallow push into a box that already advertises refs FAILS (exit ${rc})"
    else
        bad "the push into a ref-carrying shallow box SUCCEEDED on this machine's git — this
   object graph no longer reproduces the blocker, and the remedy below is being
   asserted against nothing:
$(sed 's/^/        /' "$out")"
        return
    fi

    # (b) AND `--no-thin` DOES NOT CURE IT. The flag everyone reaches for.
    rm -rf "$box"
    cp -R "$keep" "$box"
    rc=0
    git -C "$mirror" push --no-thin --force "file://${box}" refs/heads/main:refs/heads/main >>"$out" 2>&1 || rc=$?
    if [ "$rc" != "0" ]; then
        ok "--no-thin fails identically (exit ${rc}): the omission is driven by the advertised refs, not by delta bases"
    else
        bad "--no-thin cured it on this machine — then the remedy this wrapper ships is the
   wrong one and the comment above is wrong with it"
    fi

    # (c) THE REMEDY: a receiver that advertises nothing is assumed to have
    # nothing, and the pack is complete.
    rm -rf "$box"
    cp -R "$keep" "$box"
    git -C "$box" update-ref -d refs/heads/main
    git -C "$box" update-ref -d refs/heads/verifier-parking
    rc=0
    git -C "$mirror" push --force "file://${box}" refs/heads/main:refs/heads/main >>"$out" 2>&1 || rc=$?
    if [ "$rc" = "0" ]; then
        ok "with the box's refs cleared first, the same mirror and the same box land the tree"
    else
        bad "clearing the box's refs did not cure it (exit ${rc}):
$(sed 's/^/        /' "$out")"
        return
    fi

    # (d) AND THE PARKED DERIVATION SURVIVES IT, which is the half a cure could
    # quietly break. Deleting the checked-out branch's ref leaves HEAD a symref
    # to an unborn branch; `sync_box_worktree`'s `reset --hard refs/heads/main`
    # recreates it AT THE SAME NAME and moves the working tree with it — so the
    # box is parked exactly as the bake parked it, and `scripts/db.sh`'s
    # per-branch DATABASE_NAME derives the name every other box derives.
    git -C "$box" reset --hard refs/heads/main >/dev/null 2>&1 ||
        bad "the box's working tree could not be moved onto the pushed main after the clear"
    if [ "$(git -C "$box" symbolic-ref --short HEAD 2>/dev/null || true)" = "verifier-parking" ]; then
        ok "the box is parked on verifier-parking again — the per-branch database name is unchanged"
    else
        bad "the box is not parked on verifier-parking after the reset: $(git -C "$box" symbolic-ref --short HEAD 2>/dev/null || echo '<detached or unborn>')"
    fi
    tree_there="$(git -C "$box" rev-parse HEAD^{tree} 2>/dev/null || true)"
    tree_here="$(git -C "$mirror" rev-parse refs/heads/main^{tree} 2>/dev/null || true)"
    [ -n "$tree_here" ] && [ "$tree_there" = "$tree_here" ] &&
        ok "and the box's WORKING TREE is the tree that was pushed (${tree_here:0:8})" ||
        bad "the box's working tree is ${tree_there:-<unreadable>} and the pushed tree is ${tree_here:-<unreadable>}"
}

case_the_wrapper_sends_one_ref_per_push_base_first() {
    CURRENT=case_the_wrapper_sends_one_ref_per_push_base_first
    world_new push_split
    world_up_ready
    printf '4444444444444444444444444444444444444444\n' >"$REC/git.mergebase"
    printf '2\n' >"$REC/git.revlist"
    vb -- up --for X
    [ "$VB_RC" = "0" ] || {
        bad "up exited ${VB_RC}"
        report
        return
    }
    # EVERY ssh:// PUSH, IN ORDER, one ref each.
    local -a sent=()
    local line
    while IFS= read -r line; do
        sent+=("$line")
    done < <(grep -F -- "push --force ssh://" "$REC/git.flat" || true)
    [ "${#sent[@]}" = "2" ] && ok "two ssh:// pushes for a tree and a fork point — one ref each" ||
        bad "${#sent[@]} ssh:// push(es), wanted 2: $(printf '%s | ' "${sent[@]}")"
    case "${sent[0]:-}" in
    *"refs/djb/base:refs/djb/base"*) ok "the FIRST push is the fork point — a base that will not go is found before the tree is sent" ;;
    *) bad "the first push is not the base: '${sent[0]:-<none>}'" ;;
    esac
    case "${sent[1]:-}" in
    *"refs/heads/main:refs/heads/main"*) ok "the second is the tree" ;;
    *) bad "the second push is not main: '${sent[1]:-<none>}'" ;;
    esac
    # AND NEITHER CARRIES BOTH, which is the shape git refuses.
    for line in "${sent[@]}"; do
        case "$line" in
        *refs/djb/base*refs/heads/main* | *refs/heads/main*refs/djb/base*)
            bad "one invocation carries both refs: '${line}'"
            return
            ;;
        esac
    done
    ok "no invocation carries two refs"
}

case_a_refused_base_never_sends_the_tree() {
    CURRENT=case_a_refused_base_never_sends_the_tree
    world_new push_base_refused
    world_up_ready
    printf '4444444444444444444444444444444444444444\n' >"$REC/git.mergebase"
    printf '2\n' >"$REC/git.revlist"
    printf '1\n' >"$REC/git.push.base.rc"
    printf 'error: failed to push some refs\n' >"$REC/git.push.base.err"
    vb -- up --for X
    [ "$VB_RC" != "0" ] && ok "up fails when the fork point will not go, exit ${VB_RC}" ||
        bad "a refused base was swallowed and up exited 0"
    local pushes
    pushes="$(grep -cF -- "push --force ssh://" "$REC/git.flat" || true)"
    [ "$pushes" = "1" ] && ok "exactly one ssh:// push: the tree was never sent after the base refused" ||
        bad "${pushes} ssh:// pushes — the tree went over after a refusal"
    # THE BOX IS UNTOUCHED, and the message says so: that is the difference
    # between "retry" and "take it down", and it is the reason the base goes
    # first rather than last.
    said "THE REF THAT FAILED: refs/djb/base:refs/djb/base" &&
        ok "the refusal names the ref that failed" ||
        bad "the refusal does not name the failed ref: $(tr '\n' ' ' <"$W/err")"
    said "Nothing landed on the box" &&
        ok "and says the box is exactly as it was — nothing to undo" ||
        bad "the refusal does not say what state the box is in: $(tr '\n' ' ' <"$W/err")"
}

# AND THE WRAPPER HAS TO DO IT — the half the case above cannot see. That one
# measures git; this one measures whether this script clears the box's refs
# before the first push of a checkout, in the right order, once, and reading
# the parking branch's name out of the recipe instead of typing it.
case_the_first_push_to_a_box_clears_its_refs() {
    CURRENT=case_the_first_push_to_a_box_clears_its_refs
    local flat park clears first_clear first_push f n

    park="$(sed -n 's|^BAKE_PARK_BRANCH="\(.*\)"$|\1|p' "$ROOT/deploy/verifier/bake.sh")"
    [ -n "$park" ] ||
        cannot_look "could not read BAKE_PARK_BRANCH out of the real deploy/verifier/bake.sh —
   this case's whole subject is that the wrapper reads it from there"

    world_new push_clear_refs
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
    vb -- push i-up1
    [ "$VB_RC" = "0" ] || {
        bad "push exited ${VB_RC}"
        report
        return
    }
    flat="$(cat "$REC"/ssh/*.flat 2>/dev/null || true)"
    case "$flat" in
    *"update-ref -d refs/heads/main"*) ok "the box's main is deleted before the pack is offered" ;;
    *) bad "nothing deleted the box's main: a shallow box that advertises its bake commit makes the sender omit objects it does not have" ;;
    esac
    case "$flat" in
    *"update-ref -d refs/heads/${park}"*)
        ok "and its parking branch, by the name the recipe writes down (${park})" ;;
    *) bad "the parking branch '${park}' was not deleted — an update-ref -d on a name that drifted succeeds silently and clears nothing" ;;
    esac
    case "$flat" in
    *"update-ref -d refs/djb/base"*)
        ok "and refs/djb/base, which a previous checkout's push may have left advertising" ;;
    *) bad "refs/djb/base was not cleared — a stale one advertises just as loudly as main" ;;
    esac

    # BEFORE THE WORKING TREE IS MOVED ONTO IT, and that ordering is the whole
    # safety of the remedy: `sync_box_worktree`'s `reset --hard
    # refs/heads/main` is what recreates the parking branch the clear deleted.
    # A clear that landed after it would leave a box with no branch at all.
    # Both are ssh sessions, so the recorder numbers them and the comparison is
    # a real one rather than an assumption about two different log files.
    first_clear=""
    first_push=""
    for f in $(ls "$REC"/ssh/*.flat 2>/dev/null | sort -t/ -k99 -n || true); do
        n="${f##*/}"
        n="${n%.flat}"
        case "$(cat "$f" 2>/dev/null || true)" in
        *"update-ref -d refs/heads/main"*) [ -n "$first_clear" ] || first_clear="$n" ;;
        esac
        case "$(cat "$f" 2>/dev/null || true)" in
        *"reset --hard refs/heads/main"*) [ -n "$first_push" ] || first_push="$n" ;;
        esac
    done
    if [ -n "$first_clear" ] && [ -n "$first_push" ] && [ "$first_clear" -lt "$first_push" ]; then
        ok "the clear (ssh session ${first_clear}) comes before the worktree reset that recreates the branch (session ${first_push})"
    else
        bad "the clear and the reset are not in that order — clear=${first_clear:-<never>} reset=${first_push:-<never>}; a box cleared after its reset has no branch at all"
    fi

    # ONCE PER CHECKOUT PER BOX. A second push from the same checkout has a box
    # that is no longer shallow at a stranger's commit; clearing again would
    # re-send the whole tree over the tunnel every time.
    : >"$REC/ssh/1.flat" 2>/dev/null || true
    rm -f "$REC"/ssh/*.flat
    vb -- push i-up1
    [ "$VB_RC" = "0" ] || {
        bad "the second push exited ${VB_RC}"
        report
        return
    }
    clears="$(grep -lF -- "update-ref -d refs/heads/main" "$REC"/ssh/*.flat 2>/dev/null | grep -c . || true)"
    case "${clears:-0}" in
    0) ok "a second push from the same checkout clears nothing — the box is no longer the shape that needed it" ;;
    *) bad "the clear ran again on the second push: every push would re-send the whole tree" ;;
    esac
}

case_the_push_sends_a_depth_one_mirror_and_not_the_history() {
    CURRENT=case_the_push_sends_a_depth_one_mirror_and_not_the_history
    world_new push_shallow
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
    vb -- push i-up1
    [ "$VB_RC" = "0" ] || {
        bad "push exited ${VB_RC}"
        report
        return
    }
    local git_flat
    git_flat="$(cat "$REC/git.flat" 2>/dev/null || true)"
    case "$git_flat" in
    *"fetch -q --depth 1 file://${ROOT} +HEAD:refs/heads/main"*)
        ok "a depth-1 mirror of THIS checkout's HEAD is built first" ;;
    *) bad "no depth-1 fetch of HEAD recorded: ${git_flat}" ;;
    esac
    # The pack must leave from the MIRROR. A push from the checkout is the
    # whole history again however shallow the mirror is.
    local transfer
    transfer="$(grep -F -- "push --force ssh://" "$REC/git.flat" | tail -n 1 || true)"
    case "$transfer" in
    *"-C ${W}/vhome/"*) ok "the pack is pushed from the mirror, not from the checkout" ;;
    *) bad "the ssh:// push does not come from the mirror: ${transfer}" ;;
    esac
    case "$transfer" in
    *"-C ${ROOT} "*) bad "the transfer still runs in the checkout: ${transfer}" ;;
    *) ok "and never with -C on the checkout itself" ;;
    esac
    # The mirror lives OUTSIDE every checkout, for the private key's reason:
    # a scratch repository inside the tree is one the gate measures.
    case "$git_flat" in
    *"init -q --bare ${ROOT}"*) bad "the mirror was made inside the checkout" ;;
    *) ok "the mirror is made under DJB_VERIFIER_HOME, outside every checkout" ;;
    esac
    # And the receiver is told to accept a shallow history — measured: without
    # it the push is refused with `shallow update not allowed`.
    if grep -F -- "receive.shallowUpdate true" "$REC"/ssh/*.flat >/dev/null 2>&1; then
        ok "receive.shallowUpdate is set on the box before the pack is offered"
    else
        bad "nothing set receive.shallowUpdate on the box: a shallow push is refused without it"
    fi
}

# THE WALL STILL STANDS, AND IT HAD TO BE MOVED TO KEEP IT. The pack now leaves
# from a scratch mirror that has no hooks and no verdict ledger, so git runs no
# pre-push hook over it at all — which would have taken the tree straight past
# the wall that exists to stop exactly that. So the wrapper runs the hook
# ITSELF, first, by pushing `--dry-run` at a throwaway repository on this
# machine: git runs every hook and sends nothing, and the hook sees exactly the
# refs the real push would put on its stdin.
case_the_pre_push_hook_still_vouches_for_the_tree_that_goes() {
    CURRENT=case_the_pre_push_hook_still_vouches_for_the_tree_that_goes
    world_new push_vouch
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
    vb -- push i-up1
    [ "$VB_RC" = "0" ] || {
        bad "push exited ${VB_RC}"
        report
        return
    }
    local dry
    dry="$(grep -F -- "push --dry-run" "$REC/git.flat" | head -n 1 || true)"
    if [ -z "$dry" ]; then
        bad "no --dry-run push: the pre-push hook never ran, and the tree went unvouched"
        report
        return
    fi
    ok "the hook is run over a --dry-run push, which sends nothing"
    case "$dry" in
    *"-C ${ROOT} "*) ok "and it is run IN THE CHECKOUT, where the hook and the verdict ledger are" ;;
    *) bad "the dry run is not in the checkout, so it is not this checkout's hook: ${dry}" ;;
    esac
    # `HEAD:refs/heads/main`, AND NOT `refs/heads/main:…`. In THIS checkout the
    # tree that is going is named HEAD; naming the branch instead hands the
    # hook main's tree, which is the exact defect the HEAD push replaces — and
    # it is invisible from the primary checkout, where the two are the same
    # commit. (It was written that way here first, and read green.)
    case "$dry" in
    *"HEAD:refs/heads/main"*) ok "over HEAD — the tree that is actually going" ;;
    *) bad "the dry run does not vouch for HEAD: ${dry}" ;;
    esac
    case "$dry" in
    *" refs/heads/main:refs/heads/main"*)
        bad "the vouch names the BRANCH as its source: from a worktree that is a different tree
      from the one being sent, and the hook would vouch for the wrong one: ${dry}" ;;
    *) ok "and never the branch by name, which from a worktree is a different tree" ;;
    esac
    case "$dry" in
    *ssh://*) bad "the dry run goes at the BOX — the hook's wall must not need the tunnel: ${dry}" ;;
    *) ok "and at a throwaway repository on this machine, not through the tunnel" ;;
    esac
    # THE ORDER: vouch, then transfer. A vouch after the pack is a vouch that
    # vouched for nothing.
    local first_push
    first_push="$(grep -F -- " push " "$REC/git.flat" | head -n 1 || true)"
    case "$first_push" in
    *--dry-run*) ok "the vouch is the FIRST push of the two" ;;
    *) bad "something was pushed before the hook was consulted: ${first_push}" ;;
    esac
}

case_a_hook_that_refuses_stops_the_push_before_the_tunnel() {
    CURRENT=case_a_hook_that_refuses_stops_the_push_before_the_tunnel
    world_new push_vouch_refused
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
    # A hook's refusal is `git push` exit 1, whatever status the hook exited
    # with — the drive's own witness case measures that separately.
    printf '%s\n' 1 >"$REC/git.vouch.rc"
    printf '%s\n' "!! pre-push: REFUSED — the ref being pushed is not the tree in this checkout." >"$REC/git.vouch.err"
    vb -- push i-up1
    [ "$VB_RC" != "0" ] || {
        bad "a refused hook let the push through"
        report
        return
    }
    ok "a refused hook is a non-zero push (${VB_RC})"
    if grep -F -- "fetch -q --depth 1" "$REC/git.flat" >/dev/null 2>&1; then
        bad "the mirror was built anyway — the refusal did not stop the work"
    else
        ok "no mirror was built"
    fi
    if grep -F -- "push --force ssh://" "$REC/git.flat" >/dev/null 2>&1; then
        bad "the transfer ran after the hook refused"
    else
        ok "and nothing was sent to the box"
    fi
    said "pre-push hook refused" && ok "and the wrapper says whose wall it was" ||
        bad "the wrapper does not say the refusal was this machine's: $(tr '\n' ' ' <"$W/err")"
}

# =============================================================================
# THE BOX IS A MEASURING DESTINATION, NOT A FORGE
# =============================================================================
#
# THE DEFECT, measured on 2026-09-18. The vouch above runs this machine's
# pre-push hook, and that hook honours a banked FULL verdict or else runs the
# full gate — 30-70 minutes on this laptop. A verifier's union clone is BY
# CONSTRUCTION a tree no bank has ever measured, so no verification could reach a
# box at all: the box could take `main` and nothing else. The wall exists so an
# unmeasured tree never reaches a FORGE — somewhere it will be kept, shared or
# merged. A verifier box is a throwaway machine whose ENTIRE JOB is to run the
# gate on the tree it is handed, so the box's own run IS the measurement and
# doing it here first buys nothing.
#
# AND THE SECOND HALF, measured the same night: a `verify_start.sh` clone sets no
# `core.hooksPath` and its `.git/hooks` holds only samples, so from a clone the
# dry-run fired NO hook, exited 0 in silence, and the box carried a tree no wall
# had ever seen — while the identical command from the primary demanded the full
# gate. Silence and consent are indistinguishable to the caller unless the hook
# SAYS it ran, which is what the sentinel is for.
#
# THE TWO WORLDS BELOW, and why there are two. The wrapper's half (what the vouch
# DECLARES, and what it does when nothing answers) is provable in this drive's
# own fake-git world. The hook's half is not: a shimmed `git` never runs a hook,
# so "no gate ran" would be true of every case here for the wrong reason. Those
# cases build a THROWAWAY REPOSITORY with the REAL hook, the REAL ledger library,
# its own verdict ledger and a STUB `check.sh` that prints a marker — the same
# shape `scripts/tests/test_loop_ledger.sh` uses for this hook, and the only
# shape in which "the Mac's gate did not run" is an observation rather than an
# artefact of the shim.

#: A throwaway checkout carrying the real pre-push hook, its own verdict ledger
#: with a green row for `main`, a stub gate, and a probe remote shaped like the
#: wrapper's own. Sets HOOK_WORK, HOOK_PROBE, HOOK_LEDGER and HOOK_MAIN_SHA.
HOOK_WORK=""
HOOK_PROBE=""
HOOK_LEDGER=""
HOOK_MAIN_SHA=""
hook_world() {
    local base="${WORK}/hook-$1"
    HOOK_WORK="${base}/work"
    HOOK_PROBE="${base}/vhome/.vouch-4321/probe.git"
    drive_require_scratch HOOK_WORK "${HOOK_WORK:-}"
    drive_require_scratch HOOK_PROBE "${HOOK_PROBE:-}"
    rm -rf "$base"
    mkdir -p "$HOOK_WORK/scripts/githooks" "${base}/vhome/.vouch-4321"
    git init -q "$HOOK_WORK" || cannot_look "git init refused in the scratch checkout"
    git -C "$HOOK_WORK" symbolic-ref HEAD refs/heads/main
    git -C "$HOOK_WORK" config user.email drive@example.invalid
    git -C "$HOOK_WORK" config user.name "boxvouch drive"
    # THE CLONE'S OWN MISSING LINE, SET HERE ON PURPOSE. A repository made by
    # `git init` has no hooksPath either; this drive is about what the hook DOES
    # once it runs, and the case about a checkout where it does not run is the
    # wrapper's, one world over.
    git -C "$HOOK_WORK" config core.hooksPath scripts/githooks
    cp "$ROOT/scripts/gate_ledger.sh" "$HOOK_WORK/scripts/gate_ledger.sh"
    cp "$ROOT/scripts/gate_refuse.sh" "$HOOK_WORK/scripts/gate_refuse.sh"
    cp "$ROOT/scripts/githooks/pre-push" "$HOOK_WORK/scripts/githooks/pre-push"
    chmod +x "$HOOK_WORK/scripts/githooks/pre-push"
    # THE STUB GATE — the observable difference between "it measured" and "it did
    # not". A real `./scripts/check.sh` inside a drive is refused by the
    # per-checkout gate lock anyway, and would cost the wall clock this whole
    # hotfix exists to stop spending.
    printf '#!/usr/bin/env bash\necho "STUB GATE RAN"\nexit 0\n' >"$HOOK_WORK/scripts/check.sh"
    chmod +x "$HOOK_WORK/scripts/check.sh"
    echo "the measured content" >"$HOOK_WORK/README.md"
    git -C "$HOOK_WORK" add -A >/dev/null
    git -C "$HOOK_WORK" commit -q -m "main, the tree a full gate measured"
    HOOK_MAIN_SHA="$(git -C "$HOOK_WORK" rev-parse HEAD)"
    (cd "$HOOK_WORK" && . scripts/gate_ledger.sh &&
        gate_ledger_record "$(git rev-parse "${HOOK_MAIN_SHA}^{tree}")" "drive-legs") ||
        cannot_look "gate_ledger_record would not write into the scratch repo's ledger"
    HOOK_LEDGER="$HOOK_WORK/.git/djb-gate-verdicts"
    [ -s "$HOOK_LEDGER" ] || cannot_look "the scratch ledger is empty — the plant did not take"
    git init -q --bare "$HOOK_PROBE" || cannot_look "git init --bare refused for the probe"
}

#: One commit past the banked one: the shape of a verifier's union clone, which
#: is a tree no bank has ever measured. Leaves it checked out.
hook_union_commit() {
    printf 'a union nothing measured\n' >"$HOOK_WORK/UNION.md"
    git -C "$HOOK_WORK" add UNION.md >/dev/null
    git -C "$HOOK_WORK" commit -q -m "the union tree, unmeasured"
}

case_an_unmeasured_union_tree_reaches_the_box_without_a_mac_gate() {
    CURRENT=case_an_unmeasured_union_tree_reaches_the_box_without_a_mac_gate

    # --- the wrapper's half: what the vouch declares, and for how long ---------
    world_new push_declares_box
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
    vb -- push i-up1
    [ "$VB_RC" = "0" ] || {
        bad "push exited ${VB_RC}"
        report
        return
    }
    local dest_vouch dest_transfer
    dest_vouch="$(grep -F -- "push --dry-run" "$REC/git.dest" | head -n 1 || true)"
    dest_transfer="$(grep -F -- "push --force ssh://" "$REC/git.dest" | head -n 1 || true)"
    case "$dest_vouch" in
    verifier-box*) ok "the vouch declares DJB_PUSH_DESTINATION=verifier-box" ;;
    *) bad "the vouch does not declare the box destination: ${dest_vouch:-<no dry-run recorded>}" ;;
    esac
    case "$dest_transfer" in
    "<unset>"*) ok "and the declaration is gone by the transfer — one command, not an export" ;;
    *) bad "the declaration leaked past the vouch into the transfer: ${dest_transfer}" ;;
    esac

    # --- the hook's half: the gate that does not run ---------------------------
    hook_world bv1
    hook_union_commit
    local before after out rc=0
    before="$(wc -c <"$HOOK_LEDGER")"
    out="${WORK}/bv1-push.log"
    DJB_PUSH_DESTINATION=verifier-box \
        git -C "$HOOK_WORK" push --dry-run --force "$HOOK_PROBE" "HEAD:refs/heads/main" \
        >"$out" 2>&1 || rc=$?
    after="$(wc -c <"$HOOK_LEDGER")"

    [ "$rc" = "0" ] &&
        ok "the vouch exits 0 over an unmeasured union tree at a box" ||
        bad "the vouch exited ${rc} over an unmeasured union tree at a box: $(tr '\n' ' ' <"$out")"
    # THE CANARY. On the hook this replaces, this line is the one that fires: the
    # tree is the checkout's and has no verdict, so the wall ran `check.sh`.
    if grep -F "STUB GATE RAN" "$out" >/dev/null 2>&1; then
        bad "the Mac's full gate ran for a tree that was only going to a verifier box"
    else
        ok "no gate ran on this machine — the box's own run is the measurement"
    fi
    if grep -F "leaves for a VERIFIER BOX" "$out" >/dev/null 2>&1; then
        ok "and the hook names the exemption rather than passing in silence"
    else
        bad "the hook let the tree through without saying why: $(tr '\n' ' ' <"$out")"
    fi
    if grep -F "pre-push: wall box-exempt" "$out" >/dev/null 2>&1; then
        ok "the sentinel says which verdict the wall reached"
    else
        bad "no sentinel for the box-exempt decision: $(tr '\n' ' ' <"$out")"
    fi
    # BV.5 · THE LEDGER IS UNTOUCHED. An exemption that banked a row would be
    # worse than the gate it skipped: a verdict claiming a tree was measured here
    # when nothing measured it, which every later push would honour.
    [ "$after" = "$before" ] &&
        ok "the verdict ledger is byte-for-byte what it was (${before} bytes) — nothing was banked" ||
        bad "the box vouch wrote to the verdict ledger: ${before} bytes before, ${after} after"
}

case_a_box_destination_never_carries_a_foreign_tree() {
    CURRENT=case_a_box_destination_never_carries_a_foreign_tree
    # THE EXEMPTION IS FROM THE MEASUREMENT, NEVER FROM THE IDENTITY CHECK. A box
    # exists to measure what THIS checkout holds; a ref whose tree is not this
    # checkout's is the same defect at a box as it is at a forge, and the remedy
    # is the same one — push from a checkout of what you are pushing.
    hook_world bv2
    local foreign out rc=0
    git -C "$HOOK_WORK" checkout -q -b foreign
    printf 'not this checkout\n' >"$HOOK_WORK/FOREIGN.md"
    git -C "$HOOK_WORK" add FOREIGN.md >/dev/null
    git -C "$HOOK_WORK" commit -q -m "a tree that is not the checkout's"
    foreign="$(git -C "$HOOK_WORK" rev-parse HEAD)"
    git -C "$HOOK_WORK" checkout -q main

    out="${WORK}/bv2-push.log"
    DJB_PUSH_DESTINATION=verifier-box \
        git -C "$HOOK_WORK" push --dry-run --force "$HOOK_PROBE" "${foreign}:refs/heads/foreign" \
        >"$out" 2>&1 || rc=$?
    [ "$rc" = "1" ] &&
        ok "the vouch exits 1 over a foreign tree at a box destination" ||
        bad "the vouch exited ${rc} over a foreign tree at a box destination: $(tr '\n' ' ' <"$out")"
    if grep -F "REFUSED — the ref being pushed is not the tree in this checkout" "$out" >/dev/null 2>&1; then
        ok "the box destination still refuses a tree that is not this checkout's"
    else
        bad "a foreign tree passed the box destination: $(tr '\n' ' ' <"$out")"
    fi
    if grep -F "leaves for a VERIFIER BOX" "$out" >/dev/null 2>&1; then
        bad "the exemption was reached before the identity check"
    else
        ok "and the exemption was never reached"
    fi
}

case_the_destination_variable_alone_opens_nothing() {
    CURRENT=case_the_destination_variable_alone_opens_nothing
    # THE HOOK, DRIVEN THE WAY GIT DRIVES IT: `pre-push <remote name> <remote
    # url>` on argv, one `<local ref> <local sha> <remote ref> <remote sha>` line
    # on stdin. The remote here is an ordinary bare repository — not the
    # wrapper's `.vouch-<pid>/probe.git` — so the declaration is the only thing
    # present, and the only thing present must not be enough. If it were, an
    # exported variable would open `origin`.
    hook_world bv3
    hook_union_commit
    local elsewhere union out rc=0
    elsewhere="${WORK}/hook-bv3/vhome/elsewhere.git"
    git init -q --bare "$elsewhere" || cannot_look "git init --bare refused for the decoy remote"
    union="$(git -C "$HOOK_WORK" rev-parse HEAD)"
    out="${WORK}/bv3-hook.log"
    (
        cd "$HOOK_WORK" &&
            DJB_PUSH_DESTINATION=verifier-box ./scripts/githooks/pre-push origin "$elsewhere" \
                <<EOF
refs/heads/main ${union} refs/heads/main 0000000000000000000000000000000000000000
EOF
    ) >"$out" 2>&1 || rc=$?

    [ "$rc" = "0" ] &&
        ok "the hook exits 0, as it does at any remote once the stub gate is green" ||
        bad "the hook exited ${rc} at an ordinary remote: $(tr '\n' ' ' <"$out")"
    # THE CANARY. Absent on the hook this replaces, because it had nothing to
    # ignore; a green here with this line missing means the declaration was read
    # somewhere and never reported.
    if grep -F "DJB_PUSH_DESTINATION=verifier-box ignored — the remote is not a verifier-box probe" "$out" >/dev/null 2>&1; then
        ok "the hook names the declaration it ignored, and why"
    else
        bad "the declaration was ignored in silence: $(tr '\n' ' ' <"$out")"
    fi
    if grep -F "STUB GATE RAN" "$out" >/dev/null 2>&1; then
        ok "and the hook behaved exactly as it does with no declaration at all — it measured"
    else
        bad "the variable alone changed the hook's behaviour at an ordinary remote"
    fi
    if grep -F "leaves for a VERIFIER BOX" "$out" >/dev/null 2>&1; then
        bad "an ordinary remote was treated as a verifier box"
    else
        ok "no exemption was granted at a remote that is not a probe"
    fi
}

# THE PUSH MOVES A REF. THE GATE MEASURES A WORKING TREE.
#
# MEASURED ON THE FIRST REAL BOX CONSULT, 2026-09-18, and it came back GREEN for
# the wrong tree: `4004 passed`, `ok: loop checks passed`, and a banked key
# naming the tree the IMAGE WAS BAKED FROM rather than the union that was
# pushed. The push updates `refs/heads/main` on the box; the box's checkout is
# parked off main by design (so the push is legal at all); a push moves no
# files. So the gate over there measured the bake's files and banked an honest
# verdict about the wrong thing — and the wrapper's own agreement line printed
# "=" the whole time, because it compared the REF.
case_the_push_moves_the_boxs_working_tree_onto_what_it_pushed() {
    CURRENT=case_the_push_moves_the_boxs_working_tree_onto_what_it_pushed
    world_new push_worktree
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
    printf 'a-rung\n' >"$W/vhome/i-up1/rung"
    vb -- push i-up1
    [ "$VB_RC" = "0" ] || {
        bad "push exited ${VB_RC}"
        report
        return
    }
    # THE CANARY. Absent on the wrapper this replaces, which ended at the ref.
    local reset=""
    local f
    for f in "$REC"/ssh/*.flat; do
        [ -r "$f" ] || continue
        case "$(cat "$f")" in
        *"reset --hard refs/heads/main"*) reset="$(cat "$f")" ;;
        esac
    done
    if [ -n "$reset" ]; then
        ok "the push moves the box's working tree onto the pushed main"
    else
        bad "no \`reset --hard refs/heads/main\` reached the box — the ref moved and the files did not, so a gate there measures the image"
        return
    fi
    case "$reset" in
    *"git -C /"*) ok "and it is aimed at the box's checkout by absolute path" ;;
    *) bad "the reset is not aimed at a checkout: ${reset}" ;;
    esac
    # NOT A CLEAN. The box's `.env` — carrying the pinned DATABASE_NAME the
    # image was baked with — and its `.venv` are untracked; a clean takes both
    # and leaves a box that cannot run the gate at all.
    local cleaned=""
    for f in "$REC"/ssh/*.flat; do
        [ -r "$f" ] || continue
        case "$(cat "$f")" in
        *"git -C "*"clean"*) cleaned="$(cat "$f")" ;;
        esac
    done
    [ -z "$cleaned" ] &&
        ok "and nothing cleaned the box — its .env and .venv are untracked and it needs both" ||
        bad "the push cleans the box's untracked files: ${cleaned}"
    # THE AGREEMENT IS ABOUT THE WORKING TREE NOW, AND IT SAYS SO.
    out_has "= box WORKTREE" &&
        ok "the agreement line names the box's WORKING TREE, which is what the gate measures" ||
        bad "the agreement line still speaks about a ref: '$(grep '^tree' "$W/out" || true)'"
    out_has "tree       HEAD ${MAIN_SHA:0:8} = box WORKTREE ${MAIN_SHA:0:8}" &&
        ok "and the two trees are compared, not the two commits" ||
        bad "the agreement line is not the tree comparison: '$(grep '^tree' "$W/out" || true)'"
}

case_a_push_whose_box_worktree_will_not_move_is_refused() {
    CURRENT=case_a_push_whose_box_worktree_will_not_move_is_refused
    world_new push_worktree_stuck
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
    printf 'a-rung\n' >"$W/vhome/i-up1/rung"
    # THE BOX ANSWERS WITH A TREE THAT IS NOT THE ONE THAT WENT. Ordinals 1 and
    # 2 are the throughput probe and the receive.shallowUpdate config; 3 is the
    # reset and 4 is the read-back that has to agree with it.
    printf '%s\n' "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef" >"$REC/ssh/4.out"
    vb -- push i-up1
    [ "$VB_RC" != "0" ] &&
        ok "a box whose working tree does not agree with what was pushed is a refusal (${VB_RC})" ||
        bad "the push passed over a box standing on a different tree"
    said "WORKING TREE" &&
        ok "and the refusal names the working tree as the thing that disagreed" ||
        bad "the refusal does not name the working tree: $(tr '\n' ' ' <"$W/err")"
}

# AND THE BELT, ONE COMMAND LATER: `loop` will not start a gate on a box that is
# not standing on the pushed tree. The gate over there is two minutes and it
# answers plausibly either way, which is what makes this the cheap check.
case_a_loop_over_a_box_that_is_not_on_the_pushed_tree_is_refused() {
    CURRENT=case_a_loop_over_a_box_that_is_not_on_the_pushed_tree_is_refused
    world_new loop_stale_worktree
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
    printf 'a-rung\n' >"$W/vhome/i-up1/rung"
    # 1 is the worktree's tree, 2 is main's. The box is parked on what the image
    # was baked from while main carries the pushed union — the exact shape the
    # first real consult was in.
    #
    # LOW-ENTROPY SHAS ON PURPOSE, the way `$MAIN_SHA` is. A realistic 40-hex
    # fixture is a Hex High Entropy String to the secrets leg, and buying a
    # `pragma: allowlist secret` for a value nobody could mistake for a
    # credential spends a real exemption on a fake sha.
    printf '%s\n' "3333333333333333333333333333333333333333" >"$REC/ssh/1.out"
    printf '%s\n' "4444444444444444444444444444444444444444" >"$REC/ssh/2.out"
    vb -- loop i-up1 --log v1
    [ "$VB_RC" = "2" ] &&
        ok "a loop over a box that is not on the pushed tree is exit 2" ||
        bad "loop exited ${VB_RC} over a stale worktree, wanted 2"
    said "the box's checkout is not the pushed tree" &&
        ok "and the refusal names the cause" ||
        bad "the refusal does not name the cause: $(tr '\n' ' ' <"$W/err")"
    said "run push i-up1" &&
        ok "and the remedy, with the id" ||
        bad "the refusal names no remedy: $(tr '\n' ' ' <"$W/err")"
    local launched=""
    local f
    for f in "$REC"/ssh/*.flat; do
        [ -r "$f" ] || continue
        case "$(cat "$f")" in
        *"setsid nohup"*) launched="$(cat "$f")" ;;
        esac
    done
    [ -z "$launched" ] &&
        ok "and no gate was launched — the refusal is before the two minutes, not after" ||
        bad "a gate was launched on a box standing on the wrong tree: ${launched}"
    [ -f "$W/vhome/i-up1/v1.pid" ] &&
        bad "a pid was remembered for a gate that must not have started" ||
        ok "and nothing was remembered for wait to poll"
}

case_a_vouch_with_no_hook_is_refused() {
    CURRENT=case_a_vouch_with_no_hook_is_refused
    # A CLONE IS HOOKLESS, AND HOOKLESSNESS IS SILENT. `git clone` copies
    # committed state: not `core.hooksPath`, not a hook file — `.git/hooks` in a
    # fresh clone holds `*.sample` and no more. The `--dry-run` then exits 0
    # having consulted nothing, which from the wrapper's side is
    # indistinguishable from a wall that passed the tree. The empty
    # `git.vouch.out` below IS that checkout: a vouch that answers nothing.
    world_new push_no_hook
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
    : >"$REC/git.vouch.out"
    vb -- push i-up1
    [ "$VB_RC" != "0" ] || {
        bad "a hookless checkout vouched for its own tree and the push went ahead"
        report
        return
    }
    ok "a vouch with no hook behind it is a refusal (${VB_RC})"
    said "no pre-push hook ran on this checkout" &&
        ok "and the wrapper says what was missing" ||
        bad "the refusal does not name the missing hook: $(tr '\n' ' ' <"$W/err")"
    said "core.hooksPath=scripts/githooks" &&
        ok "and names the remedy" ||
        bad "the refusal names no remedy: $(tr '\n' ' ' <"$W/err")"
    if grep -F -- "push --force ssh://" "$REC/git.flat" >/dev/null 2>&1; then
        bad "the tree was sent to the box anyway"
    else
        ok "and nothing left this machine"
    fi
    if grep -F -- "fetch -q --depth 1" "$REC/git.flat" >/dev/null 2>&1; then
        bad "the mirror was built before the vouch was judged"
    else
        ok "no mirror was built"
    fi
}

# A TUNNEL UNDER THE FLOOR IS A NAMED REFUSAL, NOT AN HOUR OF STALL. A real
# night gave ~7 KB/s where the night before gave ~330: a 213 MB push stalled
# twice at 16 MB, and a 9 MB file took 18 minutes. Nothing in the wrapper could
# tell that from a push that was merely large, because nothing measured the
# tunnel. The probe is small on purpose — see `throughput_probe` — and the
# floor is a knob.
case_a_tunnel_under_the_floor_refuses_before_the_pack() {
    CURRENT=case_a_tunnel_under_the_floor_refuses_before_the_pack
    world_new push_slow_tunnel
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
    # The fake clock's ssh charge IS the tunnel's speed here: 1 MB in 120
    # seconds is about 8 KB/s, which is the night this was written for.
    vb DRIVE_SSH_SECONDS=120 -- push i-up1
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2 under a floor-breaking tunnel, got ${VB_RC}"
        report
        return
    }
    ok "exit 2 — refused, not attempted"
    said "KB/s" && ok "and it says what the tunnel actually measured" ||
        bad "the refusal quotes no measured rate: $(tr '\n' ' ' <"$W/err")"
    if grep -F -- "push --force ssh://" "$REC/git.flat" >/dev/null 2>&1; then
        bad "the pack was offered to a tunnel the probe had already failed"
    else
        ok "no pack was offered to it"
    fi
    said "DJB_VERIFIER_MIN_KBPS" && ok "and the refusal names the knob that overrides it" ||
        bad "the refusal does not name the floor's knob"

    # AND THE SAME PUSH ON A HEALTHY TUNNEL GOES. Without this the case above
    # would pass just as well against a probe that refuses everything.
    world_new push_fast_tunnel
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
    vb DRIVE_SSH_SECONDS=1 -- push i-up1
    [ "$VB_RC" = "0" ] && ok "a healthy tunnel pushes — the probe refuses a rate, not every push" ||
        {
            bad "a healthy tunnel was refused too (exit ${VB_RC})"
            report
        }
}

# =============================================================================
# 1.8b — the transport, across a pre-push hook that MEASURES
# =============================================================================
#
# FIELD TEST 4. `bake` pushed `main` into the box; the pre-push hook found no
# banked verdict for the tree it was carrying, ran the full gate — 1807 s — and
# the push then died with `git exit 141`, which the wrapper reported as a push
# that "failed" beside a paragraph about hooks and the verdict ledger. 141 is
# 128 + SIGPIPE, and neither of the two things it was read as can make one:
# `cmd_push`'s `>/dev/null` is not a pipe and nothing can take SIGPIPE writing
# to it, and a hook that exits NON-ZERO gives `git push` exit 1 whatever the
# hook's own status was. Both are measured below rather than argued.
#
# What does make one is the ORDER `git push` works in. The hook is handed the
# REMOTE sha of every ref on its stdin, and those can only come off a live
# connection — so git OPENS THE TRANSPORT FIRST, THEN runs the hook, and only
# then writes the pack. A hook that measures for half an hour is half an hour
# of an idle connection, and this wrapper's connection is an SSH session inside
# a Session Manager tunnel, which closes an idle one. By the time the gate came
# back green the tunnel was gone, git's write to it took SIGPIPE, and nothing
# was printed at all — not by git, which died on the write, and not by the hook,
# which had already passed.
#
# So the wrapper keeps the session's clock moving while the hook measures, and
# says what a 141 IS when one arrives anyway.

case_a_transport_that_dies_while_the_hook_measures_is_git_141() {
    CURRENT=case_a_transport_that_dies_while_the_hook_measures_is_git_141
    world_new sigpipe_witness

    # THE REAL GIT, because the claim is about git's own ordering and a shimmed
    # git would answer it against itself — the same reason the ProxyCommand case
    # steps around the `ssh` shim for a real `ssh -G`.
    local real_git
    real_git="$(PATH=/usr/bin:/bin command -v git || true)"
    { [ -n "$real_git" ] && [ -x "$real_git" ]; } ||
        cannot_look "no real git on this machine — the push ordering is git's own answer"

    local S="$W/witness"
    mkdir -p "$S/home"
    "$real_git" init -q --bare "$S/remote.git" 2>/dev/null ||
        cannot_look "git init --bare refused inside the scratch directory"
    "$real_git" init -q -b main "$S/repo" 2>/dev/null ||
        cannot_look "git init refused inside the scratch directory"
    "$real_git" -C "$S/repo" config user.email drive@example.invalid
    "$real_git" -C "$S/repo" config user.name "transport drive"
    echo "the content this push carries" >"$S/repo/README.md"
    "$real_git" -C "$S/repo" add README.md >/dev/null
    "$real_git" -C "$S/repo" commit -q -m "one"

    # A HOOK THAT MEASURES, modelled by its one relevant property: it takes
    # longer than the transport's patience. It drains stdin first, exactly as
    # `scripts/githooks/pre-push` does, so the only variable here is time.
    mkdir -p "$S/repo/.git/hooks"
    cat >"$S/repo/.git/hooks/pre-push" <<'HOOK'
#!/usr/bin/env bash
cat >/dev/null
sleep "${DRIVE_HOOK_SECONDS:-0}"
echo "the hook measured and passed"
exit "${DRIVE_HOOK_RC:-0}"
HOOK
    chmod +x "$S/repo/.git/hooks/pre-push"

    # THE TRANSPORT, which git invokes as `<command> <host> <remote command>`.
    # With `DRIVE_TRANSPORT_DIES_AFTER` set it walks away mid-hook, which is
    # what an idled-out Session Manager channel does to the ssh inside it.
    #
    # `exec 3<&0` AND `<&3` ARE LOAD-BEARING: a non-interactive shell redirects a
    # backgrounded job's stdin from /dev/null, so `sh -c "$*" &` would hand
    # `git-receive-pack` an immediate EOF, the remote would hang up on EVERY run
    # and every push here would be 141 for a reason that has nothing to do with
    # the case. That artefact is indistinguishable from the finding, and it made
    # the control below red before it was fixed.
    cat >"$S/transport" <<'SSH'
#!/usr/bin/env bash
shift
exec 3<&0
/bin/sh -c "$*" <&3 &
child=$!
if [ -n "${DRIVE_TRANSPORT_DIES_AFTER:-}" ]; then
    (
        sleep "$DRIVE_TRANSPORT_DIES_AFTER"
        kill -9 "$child" 2>/dev/null
    ) &
fi
wait "$child"
SSH
    chmod +x "$S/transport"

    # THE PUSH IS REDIRECTED THE WAY `cmd_bake` REDIRECTS IT — `>/dev/null` on
    # the whole thing — so the redirection is ruled OUT by measurement rather
    # than by reading it and deciding it looks harmless.
    _witness_push() {
        local rc=0
        (
            cd "$S/repo" || exit 2
            env -i \
                PATH=/usr/bin:/bin \
                HOME="$S/home" \
                GIT_CONFIG_GLOBAL=/dev/null \
                GIT_CONFIG_SYSTEM=/dev/null \
                GIT_SSH_COMMAND="$S/transport" \
                "$@" \
                "$real_git" push --force "ssh://localhost${S}/remote.git" main:main \
                >/dev/null 2>"$S/push.err"
        ) || rc=$?
        printf '%s\n' "$rc"
    }

    # THE PROPERTY, NOT THE NUMBER — and the number is why. This case asserted
    # `= 141` and was green on every machine it was written on and RED on the
    # CI runner, which reported `got 1` with the same transport dying in the
    # same place: git's exit when the far end goes away mid-write is the
    # platform's, not git's contract. Where SIGPIPE reaches git the shell
    # reports 128+13; where git handles the EPIPE itself it exits 1 — the same
    # number a hook's refusal gives, which is exactly the confusion the wrapper's
    # sentence exists to clear.
    #
    # SO THE CLAIM IS: non-zero, AND distinguishable from a hook refusal by
    # something other than luck — either the 141 (a signal, and a hook can never
    # produce one: the assertion three blocks down is what proves that) or a
    # transport marker in git's own words. The measured number is PRINTED in the
    # verdict, so the platform's answer is in the log rather than assumed by the
    # next reader.
    local rc transport_said=""
    rc="$(_witness_push DRIVE_HOOK_SECONDS=3 DRIVE_TRANSPORT_DIES_AFTER=1)"
    # The markers a dead transport leaves: git's own words for a far end that
    # went away, and — in this fixture — the shell reporting the transport it
    # was waiting on being killed (`Killed` on Linux, `Killed: 9` on macOS).
    # On a real box that last one is ssh's own error instead; the first three
    # are git's on every platform.
    if grep -E 'hung up|Broken pipe|write error|remote end|Killed' "$S/push.err" >/dev/null 2>&1; then
        transport_said="yes"
    fi
    if [ "$rc" = "0" ]; then
        bad "a transport that died during the hook still landed the push — then nothing below
      is measuring what it says it is"
    elif [ "$rc" = "141" ]; then
        ok "a transport that dies while the hook measures is a non-zero this machine reports as
      141 — 128+SIGPIPE, which a hook can never produce"
    elif [ -n "$transport_said" ]; then
        ok "a transport that dies while the hook measures is exit ${rc} on this machine (not a
      signal), and git's own words name the transport rather than a refusal"
    else
        bad "the push failed with ${rc}, which is not a signal, and NOTHING in git's output names
      the transport — so this failure is indistinguishable from a hook's refusal, and the
      wrapper's sentence cannot be right about it.
      git said: $(tr '\n' ' ' <"$S/push.err" 2>/dev/null)"
    fi

    # THE CONTROL, and it is the half that acquits the redirection: the same
    # slow hook, the same `>/dev/null`, a transport that stays up — and the push
    # lands.
    rc="$(_witness_push DRIVE_HOOK_SECONDS=3)"
    if [ "$rc" = "0" ] &&
        [ "$("$real_git" -C "$S/remote.git" rev-parse -q --verify refs/heads/main >/dev/null 2>&1 && echo yes)" = "yes" ]; then
        ok "the same slow hook under the same >/dev/null lands the push when the transport survives"
    else
        bad "the control push did not land (exit ${rc}) — then the 141 above is not the transport.
      git said: $(tr '\n' ' ' <"$S/push.err" 2>/dev/null)"
    fi

    # AND A HOOK THAT REFUSES IS EXIT 1, never its own status — so no 141 this
    # wrapper ever sees came from a hook, and the refusal text may say so.
    rc="$(_witness_push DRIVE_HOOK_RC=141)"
    [ "$rc" = "1" ] &&
        ok "a hook that exits 141 still gives git push exit 1 — a 141 is never the hook's" ||
        bad "a hook exiting 141 gave git push ${rc}; the refusal text below rests on this being 1"
    # AND THE CONTRAST, which is what makes the first block's marker test a
    # measurement rather than a hope: a refusal says `failed to push some refs`
    # and NOTHING about a remote end, a pipe or a killed transport. Without
    # this, "git's words name the transport" could be true of every failed push
    # and separate nothing.
    if grep -E 'hung up|Broken pipe|write error|remote end|Killed' "$S/push.err" >/dev/null 2>&1; then
        bad "a hook's refusal ALSO prints a transport marker, so nothing in git's output separates
      the two and a wrapper reading them cannot be right:
      git said: $(tr '\n' ' ' <"$S/push.err" 2>/dev/null)"
    else
        ok "and a refusal names no transport at all — which is what lets the two be told apart
      on a platform where both are exit 1"
    fi

    unset -f _witness_push
    # NOT ONE AWS CALL. The `aws` shim is on PATH throughout and records every
    # invocation; this section is git and a scratch directory.
    [ "$(ops | grep -c . || true)" = "0" ] && ok "no AWS call was made by any of it" ||
        bad "the witness reached AWS: $(ops)"
}

case_the_push_transport_outlives_a_hook_that_measures() {
    CURRENT=case_the_push_transport_outlives_a_hook_that_measures
    world_new push_keepalive
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
    vb -- push i-up1
    [ "$VB_RC" = "0" ] || {
        bad "push exited ${VB_RC}"
        report
        return
    }
    # READ OFF THE RUN, not out of the source: this is the string git was
    # actually handed.
    local gitssh
    # THE LAST CALL THAT CARRIED A TRANSPORT, not the last call. The push is
    # followed now by local git reads (the worktree agreement) whose environment
    # carries no GIT_SSH_COMMAND at all, and `tail -n 1` over every call would
    # read one of those and report a transport that was never missing.
    gitssh="$(grep -v '=<unset>$' "$REC/git.env" | sed -n 's/^GIT_SSH_COMMAND=//p' | tail -n 1)"
    case "$gitssh" in
    *ServerAliveInterval=*)
        ok "the push transport sends keepalives, so a hook that measures does not idle the session out" ;;
    *)
        bad "GIT_SSH_COMMAND carries no ServerAliveInterval. git opens this connection BEFORE it runs
      the pre-push hook and writes the pack AFTER it, so a hook that measures a full gate leaves
      the tunnel idle for the length of the gate — and the write into a closed one is the SIGPIPE
      that reads as 'git exit 141'.
      the string: ${gitssh}" ;;
    esac
    case "$gitssh" in
    *ServerAliveCountMax=*)
        ok "and it gives up after a bounded number of them rather than hanging on a dead session" ;;
    *)
        bad "GIT_SSH_COMMAND sets no ServerAliveCountMax — keepalives with no ceiling turn a dead
      tunnel into a push that never returns, which is worse than the 141: ${gitssh}" ;;
    esac
    # THE CEILING IS PUSH'S ALONE, AND THE INTERVAL IS NOT — which is what the
    # three call sites actually spell, and what this drive asserted the opposite
    # of until V-GATE read it: the old assertion looked at `$REC/ssh/1.flat` in
    # a case that makes no `ssh_to` call at all, so it took its empty branch and
    # said "nothing to contradict it" over a wrapper that had carried the
    # interval on `ssh_to` all along. An assertion aimed at a call site that
    # cannot exist is green about nothing.
    #
    # SO THE OTHER TWO SITES ARE DRIVEN HERE, in this same world: `run` records
    # an `ssh_to`, and `fetch` records the `scp`. `ssh_to` carries the interval
    # (one of its sessions is the twenty-minute recipe) and NOT the ceiling (the
    # default count max of 3 is the right bound for a session whose other end
    # should be answering); the `scp` carries neither.
    vb -- run i-up1 -- true
    local ssh1
    ssh1="$(cat "$REC/ssh/1.flat" 2>/dev/null || true)"
    if [ -z "$ssh1" ]; then
        bad "no ssh_to call was recorded, so this claim is about nothing — \`run\` is the site
      that makes one and it did not reach the shim"
    else
        case "$ssh1" in
        *ServerAliveInterval=*) ok "ssh_to keeps bytes moving too — its longest session is the recipe" ;;
        *) bad "ssh_to carries no ServerAliveInterval, and one of its sessions is a twenty-minute
      recipe with long silences in it: ${ssh1}" ;;
        esac
        case "$ssh1" in
        *ServerAliveCountMax=*) bad "ssh_to carries the CEILING as well: the hour is push's, for the
      pre-push hook's reason, and a short session that stops answering should fail at the
      default rather than after 120 probes: ${ssh1}" ;;
        *) ok "and not the ceiling — the deliberate hour is push's alone" ;;
        esac
    fi
    vb -- fetch i-up1 /tmp/gate.log "$W/fetched.log"
    local scp1
    scp1="$(cat "$REC/scp.flat" 2>/dev/null || true)"
    if [ -z "$scp1" ]; then
        bad "no scp call was recorded, so the fetch half of this claim is about nothing"
    else
        case "$scp1" in
        *ServerAlive*) bad "cmd_fetch carries a keepalive: one scp of one log needs none, and an
      option on every call site is an option nobody can argue the need for at any of them: ${scp1}" ;;
        *) ok "and cmd_fetch carries neither — one scp of one log" ;;
        esac
    fi
}

case_a_push_that_died_of_sigpipe_is_named_for_what_it_is() {
    CURRENT=case_a_push_that_died_of_sigpipe_is_named_for_what_it_is
    world_new push_sigpipe
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
    # git dies of SIGPIPE and prints NOTHING: it died on the write. That silence
    # is the whole difficulty, and it is the fixture.
    printf '%s\n' 141 >"$REC/git.push.rc"
    vb -- push i-up1
    [ "$VB_RC" = "141" ] && ok "the status is passed through untouched" ||
        bad "wanted the push's own 141 back, got ${VB_RC}"
    err_has "SIGPIPE" && ok "the wrapper names the signal rather than leaving a bare number" ||
        bad "a 141 is reported as a number with no reading: $(cat "$W/err" 2>/dev/null)"
    err_has "transport" && ok "and says the connection died, not that something refused" ||
        bad "the 141 is not attributed to the transport, so the operator goes looking at the hook
      and at the box, and neither of them did it: $(cat "$W/err" 2>/dev/null)"

    # THE OTHER PLATFORM'S NUMBER, DRIVEN THROUGH THE SAME SHIM. 141 is not the
    # answer everywhere: where git handles the EPIPE itself the transport's
    # death is exit 1 — the same number a hook's refusal gives — and this
    # repository's CI met exactly that (this machine and an Alpine box answer
    # 141; the Ubuntu runner answered 1 with the same transport dying in the
    # same place). A wrapper whose only sentence is the 141 one leaves that
    # operator a bare number that reads as the wrong thing.
    world_new push_failed_not_141
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
    printf '%s\n' 1 >"$REC/git.push.rc"
    printf 'error: failed to push some refs\n' >"$REC/git.push.err"
    vb -- push i-up1
    [ "$VB_RC" = "1" ] && ok "a non-141 failure's status is passed through too" ||
        bad "wanted the push's own 1 back, got ${VB_RC}"
    err_has "git exit 1" && ok "and the wrapper says so with the number" ||
        bad "the non-141 failure is not reported at all: $(cat "$W/err" 2>/dev/null)"
    err_has "THE TRANSPORT DIED" && ok "and NAMES THE TRANSPORT as one of the readings" ||
        bad "a failed push that is not 141 says nothing about the transport, so on a machine
      where the tunnel's death IS exit 1 the operator reads it as something refusing and goes
      looking at the wrong thing: $(cat "$W/err" 2>/dev/null)"
    # AND THE ONE THAT IS NEW WITH A SHALLOW PACK. `shallow update not allowed`
    # is a receiver that has not opted in, and it is exit 1 like everything
    # else here: unnamed, it is indistinguishable from a dead tunnel and the
    # operator retries forever against a box that will never accept the pack.
    err_has "shallow update not allowed" && ok "and the shallow receiver, which is this transfer's own new failure" ||
        bad "a failed push says nothing about a receiver that refuses a shallow history — the one
      failure a depth-1 pack adds: $(cat "$W/err" 2>/dev/null)"
    # AND IT NO LONGER BLAMES THE HOOK, because the hook cannot fail here any
    # more: the wall runs against a local repository BEFORE the tunnel is
    # opened, and it has its own sentence. Offering "the hook refused" as a
    # reading of a transfer failure would send the operator to a wall that
    # already passed.
    err_has "already passed" && ok "and says the wall on this machine already passed rather than offering it as a reading" ||
        bad "the transfer's sentence does not say the local wall already passed: $(cat "$W/err" 2>/dev/null)"
    err_has "failed to push some refs" &&
        ok "and git's own words are still in the output beside it — the wrapper adds a reading,
      it never swallows the stream it would have to grep to be sure" ||
        bad "git's own output is gone: the wrapper captured the stream, which is the eleven-minute
      push whose progress the operator can no longer watch"
}

# THE READER THAT LEAVES EARLY, IN THIS FILE'S SUBJECT. `scripts/check.sh`'s
# `pipefail_readers` leg censuses the same class across every script whose exit
# status is a verdict — but its grep reads ONE LINE AT A TIME, and a pipeline
# written across two lines puts the `|` at the end of the first and the reader
# at the start of the second, where the pattern cannot see it. Two sites in this
# wrapper sat in exactly that shape: `verifier_owner`, which runs at load and
# would have killed the wrapper before it printed anything, and
# `spot_error_code`, which runs on the launch path that decides spot or money.
# This case is the same claim with the continuation lines joined first, scoped
# to the one file this drive owns; widening the shared census is that leg's.
case_no_early_exit_reader_follows_a_pipe_in_this_wrapper() {
    CURRENT=case_no_early_exit_reader_follows_a_pipe_in_this_wrapper
    local hits
    hits="$(awk '
        { line = $0; sub(/[ \t]*#.*$/, "", line) }
        { buf = (buf == "" ? line : buf " " line); if (!start) start = NR }
        /\|[ \t]*$/ { next }
        {
            if (buf ~ /\|[ \t]*(head([ \t]|$)|grep[^|]*-[A-Za-z]*q([ \t]|$)|grep[^|]*-m[ \t]|awk[^|]*exit|sed -n[^|]*q)/)
                printf "      %d: %s\n", start, buf
            buf = ""
            start = 0
        }
    ' "$VB")"
    [ -z "$hits" ] &&
        ok "every reader in ${VB} reads its producer to EOF — no pipeline can hand it a 141" ||
        bad "a reader that leaves before its producer finishes, under this file's own \`set -o pipefail\`:
${hits}
      The producer dies of SIGPIPE once its output passes the pipe buffer and the pipeline's
      status becomes 141, which \`set -e\` turns into a wrapper that stops mid-ritual. Read the
      whole, then slice."
}

case_a_box_whose_tree_differs_is_exit_2() {
    CURRENT=case_a_box_whose_tree_differs_is_exit_2
    world_new tree_differs
    world_up_ready
    printf '2222222222222222222222222222222222222222\n' >"$REC/ssh/default.out"
    vb -- up --for X
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2, got ${VB_RC}"
        report
        return
    }
    # THE WORKING TREE IS WHAT DISAGREES NOW, and the sentence says so. The
    # comparison used to be against the box's `main` REF, which agreed while the
    # files it was supposed to stand for were still the image's.
    said "WORKING TREE" && ok "exit 2, and the refusal names the working tree" ||
        bad "the refusal does not say the trees differ"
    said "$MAIN_SHA" && said "2222222222222222222222222222222222222222" &&
        ok "both shas are named" || bad "the refusal does not name both shas"
}

case_up_prints_the_tree_agreement_when_they_agree() {
    CURRENT=case_up_prints_the_tree_agreement_when_they_agree
    world_new tree_agrees
    world_up_ready
    vb -- up --for X
    [ "$VB_RC" = "0" ] || {
        bad "up exited ${VB_RC}"
        report
        return
    }
    # HEAD, NOT `main`. What goes to the box is this checkout's HEAD, so HEAD
    # against the box's main is the agreement that means anything; comparing
    # `main` agreed only because `main:main` used to be what was pushed, and
    # from a rung's worktree it would be a comparison against a tree nobody
    # sent.
    out_has "tree       HEAD ${MAIN_SHA:0:8} = box WORKTREE ${MAIN_SHA:0:8}" &&
        ok "the block states the agreement the whole design rests on, over the tree that went" ||
        bad "the tree line does not state the agreement: '$(grep '^tree' "$W/out" || true)'"
}

# A REFUSED PUSH INSIDE `up` LEAVES A RUNNING BOX, AND SAYING SO IS THE WHOLE
# CASE. `up` launches FIRST and pushes SECOND, so the instance is already paid
# for by the time the vouch runs. Measured by hand against a real box on
# 2026-09-18: the vouch refused, `up` exited on the refusal's own words —
# "nothing left this machine" — and the box stayed UP and billing, unmentioned,
# until the census found it. An operator reading that sentence has every reason
# to believe nothing was created.
#
# AND IT IS NOT TORN DOWN, which is the other half of the ask. The launch is the
# expensive half and the push is the cheap one; a refusal here has a local cause
# and a local remedy, and re-pushing into a box that is already warm is the
# measured fast path. So the refusal hands over both doors and takes neither.
case_a_refused_push_inside_up_names_the_box_it_left_running() {
    CURRENT=case_a_refused_push_inside_up_names_the_box_it_left_running
    world_new up_push_refused
    world_up_ready
    # A hook's refusal is `git push` exit 1, whatever status the hook exited
    # with — the same fixture the standalone push case plants.
    printf '%s\n' 1 >"$REC/git.vouch.rc"
    printf '%s\n' "!! pre-push: REFUSED — the ref being pushed is not the tree in this checkout." >"$REC/git.vouch.err"
    vb -- up --for X
    [ "$VB_RC" = "2" ] &&
        ok "a refused push inside up is exit 2 — the launch happened and the vouch could not be had" ||
        bad "up exited ${VB_RC} on a refused push, wanted 2"
    # THE CANARY. Absent on the shipped wrapper, which exited on cmd_push's own
    # refusal and never mentioned the instance.
    said "box i-up1 is UP" &&
        ok "the refusal names the box it left running" ||
        bad "the box was left running and never named: $(tr '\n' ' ' <"$W/err")"
    said "verifier_box.sh push i-up1" &&
        ok "and hands over the re-push, which is the fast path once the cause is fixed" ||
        bad "the refusal offers no way to finish what was started"
    said "verifier_box.sh down i-up1" &&
        ok "and the way out, for an operator who would rather not pay for it" ||
        bad "the refusal offers no way to stop paying for the box"
    local n
    n="$(op_count "ec2 terminate-instances")"
    [ "$n" = "0" ] &&
        ok "and nothing was terminated — the launch is paid for and the decision is the operator's" ||
        bad "the wrapper tore the box down on a push refusal (${n} terminate call(s))"
    # THE HOOK'S OWN WORDS REACHED THE OPERATOR. `up` used to send cmd_push's
    # stdout to /dev/null, so the sentinel and the hook's explanation — the only
    # things anybody could fix the cause from — went nowhere.
    said "pre-push: wall " &&
        ok "the vouch's sentinel reached up's output" ||
        bad "up still swallows the vouch's stdout: $(tr '\n' ' ' <"$W/out")"
    said "pre-push: REFUSED" &&
        ok "and so did the hook's own explanation" ||
        bad "the hook's words did not reach the operator"
}

# =============================================================================
# 1.9 — bake
# =============================================================================

# THE SESSIONS A BAKE OPENS, IN ORDER, and every fixture below indexes them.
# The `ssh` shim files each session by its ordinal, so a case that plants a
# status on "the recipe" has to know which ordinal that is — and the push
# grew two sessions of its own, which moved it:
#
#   1  the readiness probe     `test -f /run/verifier/bake-ready`
#   2  the throughput probe    `cat >/dev/null`, the probe file on stdin
#   3  receive.shallowUpdate   `git -C <checkout> config …`
#   4  the worktree reset      `git -C <checkout> reset --hard refs/heads/main`
#   5  the worktree read-back  `git -C <checkout> rev-parse HEAD^{tree}`
#   6  the recipe              `./deploy/verifier/bake.sh`
#
# 2 to 5 are the push's: the tunnel is measured before a pack is offered to it,
# a shallow pack is refused outright by a receiver that has not opted in, and a
# push that moved a ref and left the files where they were is how every consult
# before 2026-09-18 came back green about the image. Named rather than spelled,
# so the next session that joins moves one constant instead of five fixtures.
SSH_READBACK=5
SSH_RECIPE=6

world_bake_ready() {
    ans "ssm_get-parameters" "ami-al2023"
    ans "ec2_describe-security-groups" "sg-v"
    ans "ec2_run-instances" "i-bake"
    ans "ssm_describe-instance-information" "Online"
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    ans "ec2_create-image" "ami-new"
    ans "ec2_describe-images__Images0State" "available"
    world_tagged "verifier-bake" "$NS"
    printf 'bake: ready for create-image\n' >"$REC/ssh/default.out"
    # THE PUSH'S READ-BACK ANSWERS WITH A TREE. The default above is the
    # recipe's own chatter, and the push now asks the box what it is standing
    # on — a question the chatter answers wrongly, which would refuse every
    # bake for a reason that has nothing to do with baking.
    printf '%s\n' "$MAIN_SHA" >"$REC/ssh/${SSH_READBACK}.out"
}

case_bake_launches_on_demand_and_captures_a_private_image() {
    CURRENT=case_bake_launches_on_demand_and_captures_a_private_image
    world_new bake_ok
    world_bake_ready
    vb -- bake
    if [ "$VB_RC" != "0" ]; then
        bad "bake exited ${VB_RC}"
        report
        return
    fi
    local call
    call="$(nth_call_of "run-instances" 1 || true)"
    case "$call" in
    *--instance-market-options*) bad "the bake box was launched on spot — an interrupted bake is a half-written image" ;;
    *) ok "the bake box is on-demand" ;;
    esac
    case "$call" in
    *"--image-id ami-al2023"*"--instance-type c7g.2xlarge"*) ok "it launches the Amazon Linux base at the bake type" ;;
    *) bad "the bake launch is '${call}'" ;;
    esac
    case "$call" in
    *"Key=djb:role,Value=verifier-bake"*) ok "it is tagged as a bake box, not a verifier" ;;
    *) bad "the bake box carries no verifier-bake tag" ;;
    esac
    said "on-demand" && ok "it says why it is on-demand" || bad "it does not say why"

    local img
    img="$(nth_call_of "create-image" 1 || true)"
    case "$img" in
    *"--instance-id i-bake"*"--name ${NS}-verifier-${MAIN_SHA:0:8}-"*) ok "the image is named for the namespace and the tree it was baked from" ;;
    *) bad "create-image is '${img}'" ;;
    esac
    local t miss=""
    for t in "Key=djb:role,Value=verifier-image" "Key=djb:namespace,Value=${NS}" \
        "Key=djb:main,Value=${MAIN_SHA}" "Key=djb:baked,Value=2" "ResourceType=snapshot"; do
        case "$img" in *"$t"*) ;; *) miss="${miss} ${t}" ;; esac
    done
    [ -z "$miss" ] && ok "image AND snapshot carry the four tags the census and the prune read" ||
        bad "create-image is missing:${miss}"
    if grep -lE "launch-permission|modify-image-attribute" "$REC"/calls/*.flat >/dev/null 2>&1; then
        bad "the image was published — that is the 'what never lands' clause broken at the account boundary"
    else
        ok "no --launch-permission and no modify-image-attribute anywhere in the log"
    fi
    [ "$(op_count 'ec2 terminate-instances')" = "1" ] && ok "the bake box was terminated" ||
        bad "the bake box was left running — 1.6's STALE BAKE, created on purpose"
    # THE LAST LINE, not merely somewhere in the output — the claim this
    # message has always made, now the claim it checks. A caller scrapes the
    # last line for the image id, so anything the wrapper learns to print on
    # the way out belongs BEFORE it.
    local last
    last="$(tail -n 1 "$W/out" 2>/dev/null || true)"
    case "$last" in
    *"image ami-new (main ${MAIN_SHA:0:8})"*) ok "the last line names the image and the tree" ;;
    *) bad "the last line does not name the image and the tree: '${last}'" ;;
    esac
}

# THE ORDER PROBLEM, AND THE ONLY THING THAT CLOSES IT. `PingStatus=Online` is
# the SSM agent's own answer about the SSM agent: it is a systemd unit that
# starts at boot and reports in long before cloud-init's `runcmd` — the LAST
# boot stage — has finished a `dnf install`. FIELD TEST 2 is what that gap
# looks like from the operator's chair: the push reached the box's own shell
# and the box said `bash: line 1: git-receive-pack: command not found`, exit
# 128. So the seam writes a marker after everything else and `bake` waits for
# THAT, through the same transport, before it pushes.
# THE IMAGE IS NAMED FOR THE TREE IT HOLDS. Every bake in this drive until now
# ran in a world where HEAD and `refs/heads/main` are the same commit, which is
# true of the primary checkout and of NO RUNG WORKTREE — and a bake is run from
# whichever checkout the operator is standing in. What the push sends is
# `HEAD:refs/heads/main`, so the tree baked into the image is HEAD's; composing
# the name, the description and the `djb:main` tag from the local `main` labelled
# that image with a tree it does not contain. `djb:main` is what the census, the
# prune and an operator asking "which build is this" all read.
case_the_image_is_named_for_the_tree_it_holds_not_local_main() {
    CURRENT=case_the_image_is_named_for_the_tree_it_holds_not_local_main
    local other="3333333333333333333333333333333333333333"
    world_new bake_head_not_main
    world_bake_ready
    # A RUNG WORKTREE, AS A FIXTURE: HEAD is one commit and this checkout's
    # `main` is another.
    printf '%s\t%s\n' "$ROOT" "$other" >"$REC/git.revparse.main"
    vb -- bake
    [ "$VB_RC" = "0" ] || {
        bad "bake exited ${VB_RC}"
        report
        return
    }
    local img
    img="$(nth_call_of "create-image" 1 || true)"
    case "$img" in
    *"--name ${NS}-verifier-${MAIN_SHA:0:8}-"*) ok "the image is named for HEAD, the tree the push sent" ;;
    *) bad "the image is not named for HEAD: '${img}'" ;;
    esac
    case "$img" in
    *"${other:0:8}"*) bad "the local main's sha is in the capture call — the image is labelled with a tree it does not hold" ;;
    *) ok "the local main's sha appears nowhere in the capture" ;;
    esac
    case "$img" in
    *"Key=djb:main,Value=${MAIN_SHA}"*) ok "djb:main carries HEAD's sha, which is what the box's main is" ;;
    *) bad "djb:main is not HEAD's sha: '${img}'" ;;
    esac
    # AND THE DESCRIPTION AND THE LAST LINE AGREE WITH THE TAG, because a
    # capture whose three provenance fields disagree is worse than one that is
    # wrong in the same way three times.
    case "$img" in
    *"main ${MAIN_SHA:0:8}, base ami-al2023"*) ok "the description names the same tree" ;;
    *) bad "the description does not name HEAD's tree: '${img}'" ;;
    esac
    out_has "image ami-new (main ${MAIN_SHA:0:8})" &&
        ok "and the line the operator reads names it too" ||
        bad "the last line does not name HEAD's tree: '$(grep '^image ' "$W/out" || true)'"
    # THE NOTE THE PUSH ALREADY PRINTS, which is what makes the difference
    # legible at the moment it matters rather than only in the image's tags.
    if said "this checkout's main is ${other:0:8}"; then
        ok "the push said on stderr that the two differ and which tree was going"
    else
        bad "the push did not say the checkout's main differs from HEAD: $(tr '\n' ' ' <"$W/err")"
    fi
}

case_bake_waits_for_the_boxs_bootstrap_before_it_pushes() {
    CURRENT=case_bake_waits_for_the_boxs_bootstrap_before_it_pushes
    world_new bake_waits
    world_bake_ready
    vb -- bake
    if [ "$VB_RC" != "0" ]; then
        bad "bake exited ${VB_RC}"
        report
        return
    fi

    # THE FIRST THING OVER THE TRANSPORT IS THE PROBE, and the push is git's,
    # so a probe recorded as ssh #1 is a probe that ran before it.
    local probe marker
    probe="$(cat "$REC/ssh/1.flat" 2>/dev/null || true)"
    marker="$(printf '%s' "$probe" | sed -n 's/.*test -f \([^ ]*\).*/\1/p')"
    if [ -n "$marker" ]; then
        ok "the first thing bake does over the transport is wait for ${marker}"
    else
        bad "the first ssh is not a readiness probe: ${probe:-<none>}"
    fi
    if [ -n "$marker" ] && grep -F -- "$marker" "$BAKE_SEAM" >/dev/null; then
        ok "the marker the wrapper waits for is the one the bake seam writes"
    else
        bad "the wrapper waits for '${marker:-<none>}', which ${BAKE_SEAM} never writes"
    fi
    # And the recipe is what the SECOND session runs — the order is
    # probe, push, recipe.
    grep -F -- "bake.sh" "$REC/ssh/${SSH_RECIPE}.flat" >/dev/null &&
        ok "the recipe runs on session ${SSH_RECIPE}, after the readiness probe and after the push's own two" ||
        bad "session ${SSH_RECIPE} is not the recipe: $(cat "$REC/ssh/${SSH_RECIPE}.flat" 2>/dev/null || echo '<none>')"
    # AND NOT BEFORE THE PUSH. The recipe reads the tree the push carries, so
    # every session up to it must be the push's own or the probe's.
    local before_recipe=0 f
    for f in "$REC"/ssh/*.flat; do
        [ -f "$f" ] || continue
        grep -F -- "bake.sh" "$f" >/dev/null 2>&1 && break
        before_recipe=$((before_recipe + 1))
    done
    [ "$before_recipe" = "$((SSH_RECIPE - 1))" ] &&
        ok "and exactly ${before_recipe} session(s) precede it — the probe and the push's two" ||
        bad "${before_recipe} session(s) run before the recipe, wanted $((SSH_RECIPE - 1))"

    # THE THREE PATHS ARE ONE PATH. The seam initialises it, the wrapper pushes
    # to it, and the recipe checks it — all from `bake.sh`'s single knob.
    local user path expect launch
    user="$(sed -n 's|^BAKE_USER="\${DJB_VERIFIER_BAKE_USER:-\(.*\)}"$|\1|p' "$BAKE")"
    user="${user%%$'\n'*}"
    path="$(sed -n 's|^BAKE_CHECKOUT="\${DJB_VERIFIER_CHECKOUT:-\(.*\)}"$|\1|p' "$BAKE")"
    path="${path%%$'\n'*}"
    path="${path//\$\{BAKE_USER\}/$user}"
    expect="ssh://${user}@i-bake${path}"
    launch="$(nth_call_of "run-instances" 1 || true)"
    case "$launch" in
    *"init"*"${path}"*) ok "the rendered user-data initialises the repository at ${path}" ;;
    *) bad "the launched user-data initialises no repository at ${path}" ;;
    esac
    case "$launch" in
    *'${VERIFIER_'*) bad "a slot survived the bake render: the user-data still carries \${VERIFIER_…}" ;;
    *) ok "no slot survives into the launched user-data" ;;
    esac
    local call
    call="$(cat "$REC/git.flat" 2>/dev/null || true)"
    case "$call" in
    *"push --force ${expect} refs/heads/main:refs/heads/main"*)
        ok "the push target is the path the seam initialised: ${expect}" ;;
    *) bad "wanted a push to '${expect}', recorded: ${call}" ;;
    esac
}

# FIELD TEST 5 WROTE THIS CASE, and it is the first failure on this path that
# happened INSIDE the box rather than on the way to it. The box booted, the
# marker arrived, the push landed — 213 MB of history through the tunnel — and
# then the recipe's very first line, `sudo dnf install`, answered:
#
#     sudo: a terminal is required to read the password …
#     sudo: a password is required
#
# The bake seam's `users:` entry granted the bake account no sudo rule, and
# NOTHING IN THE BOOTSTRAP NEEDED ONE: cloud-init's `runcmd` runs as root, so
# every `sudo -u verifier` in that file is root dropping privilege rather than
# the account climbing. The bootstrap therefore worked perfectly and the recipe
# could not run at all, and the difference is invisible until a tunnelled
# session with no tty is asked for a password it has no way to give.
#
# READ OUT OF THE RECORDED ARGV, never out of the template. What the box boots
# with is the RENDERED file, and a rule the render loses is a rule the recipe
# does not have.
case_the_bake_seam_grants_the_recipe_the_root_it_needs() {
    CURRENT=case_the_bake_seam_grants_the_recipe_the_root_it_needs
    world_new bake_sudo
    world_bake_ready
    vb -- bake
    if [ "$VB_RC" != "0" ]; then
        bad "bake exited ${VB_RC}"
        report
        return
    fi
    local launch users baker
    launch="$(nth_call_of "run-instances" 1 || true)"
    # The `users:` block of the rendered cloud-config, out of the flat record —
    # which keeps each argument's own newlines, so a block read here is the
    # block the box receives.
    users="$(printf '%s' "$launch" | awk '/^users:$/ {inside = 1; next} /^[a-z_]+:/ {inside = 0} inside')"
    baker="$(sed -n 's|^BAKE_USER="\${DJB_VERIFIER_BAKE_USER:-\(.*\)}"$|\1|p' "$BAKE")"
    baker="${baker%%$'\n'*}"
    if [ -z "$users" ]; then
        bad "the launched user-data carries no users: block at all"
        return
    fi
    case "$users" in
    *"- name: ${baker}"*) ok "the rendered users: block is the bake account ${baker}'s" ;;
    *) bad "the rendered users: block names no ${baker}: ${users}" ;;
    esac
    # NOT ANCHORED AT THE END OF THE LINE: the rule carries a trailing YAML
    # comment (the secret scanner reads `NOPASSWD:ALL` as a password keyword,
    # and a trailing comment is not part of a plain scalar's value), so an
    # anchored pattern would red over a rule that is exactly right.
    if printf '%s\n' "$users" | grep -E '^[[:space:]]+sudo:[[:space:]]*ALL=\(ALL\)[[:space:]]+NOPASSWD:ALL([[:space:]]|$)' >/dev/null; then
        ok "and it grants ${baker} passwordless sudo, which is what every step of the recipe stands on"
    else
        bad "the rendered users: block grants ${baker} no passwordless sudo, so \`sudo dnf install\` —
      the recipe's FIRST line — meets 'sudo: a terminal is required to read the password'
      on a session that has no terminal, exactly as FIELD TEST 5 did. The bootstrap's own
      \`sudo -u ${baker}\` calls are root dropping privilege and prove nothing about this:
${users}"
    fi
    # AND THE TWO HALVES CANNOT DRIFT: the rule the seam grants is the one the
    # recipe asserts for itself before it spends a second of the bake (F8.2).
    # A seam that stopped granting it would be met by the recipe's own refusal
    # rather than by a password prompt into a pipe.
    if grep -F -- "sudo -n true" "$BAKE" >/dev/null; then
        ok "and the recipe asserts the same rule for itself before step 1 rather than discovering it"
    else
        bad "${BAKE} never checks \`sudo -n true\`, so a seam that stops granting the rule is
      discovered by step 1's password prompt instead of by a refusal"
    fi
}

# THE REFUSAL HAS TO SURVIVE THE TUNNEL, which is the half a status cannot
# carry. FIELD TEST 5 was diagnosable in one read only because the recipe's own
# words came back through the transport and into the operator's log; the
# wrapper prints the recipe's whole output BEFORE it decides, and that ordering
# is the difference between `exit 2` and a sentence naming the fix.
case_a_recipe_that_refuses_is_a_refusal_the_operator_can_read() {
    CURRENT=case_a_recipe_that_refuses_is_a_refusal_the_operator_can_read
    world_new bake_recipe_refused
    world_bake_ready
    # The recipe is the session the map above names, so this is the recipe's
    # own refusal and nothing else's.
    printf '%s\n' 2 >"$REC/ssh/${SSH_RECIPE}.rc"
    printf '%s\n' \
        "!! bake: the bake account cannot sudo without a password." \
        "   deploy/verifier/bake-user-data.yaml's users: entry is the fix." >"$REC/ssh/${SSH_RECIPE}.out"
    vb -- bake
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2 when the recipe refused, got ${VB_RC}"
        report
        return
    }
    said "bake-user-data.yaml" &&
        ok "the recipe's own sentence — the one that names the fix — reaches the operator's log" ||
        bad "the recipe refused and its sentence never came back through the transport: the
      operator has a status and no reading. stdout: $(tr '\n' ' ' <"$W/out")"
    [ "$(op_count 'ec2 create-image')" = "0" ] && ok "nothing was captured from a recipe that refused" ||
        bad "it captured an image from a recipe that never ran a step"
    [ "$(op_count 'ec2 terminate-instances')" = "1" ] && ok "the builder was terminated exactly once" ||
        bad "$(op_count 'ec2 terminate-instances') terminate-instances calls, wanted 1"
}

case_bake_terminates_its_builder_when_the_bootstrap_never_finishes() {
    CURRENT=case_bake_terminates_its_builder_when_the_bootstrap_never_finishes
    world_new bake_never_ready
    world_bake_ready
    # The marker never appears: every probe answers non-zero, which is what a
    # box whose cloud-init died looks like from here.
    printf '%s\n' 1 >"$REC/ssh/default.rc"
    local CLOCK_AT_START
    CLOCK_AT_START="$(cat "$REC/clock")"
    vb -- bake
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2 when the box never finished its bootstrap, got ${VB_RC}"
        report
        return
    }
    grep -F -- "push --force" "$REC/git.flat" >/dev/null 2>&1 &&
        bad "it pushed into a box that never said it was ready — FIELD TEST 2's exit 128" ||
        ok "nothing was pushed into a box that never said it was ready"
    [ "$(op_count 'ec2 create-image')" = "0" ] && ok "nothing was captured" ||
        bad "it captured an image from a box that never bootstrapped"
    [ "$(op_count 'ec2 terminate-instances')" = "1" ] && ok "the builder was terminated rather than left billing" ||
        bad "a box that never bootstrapped was left running"

    # THE REFUSAL NAMES THE ELAPSED TIME, NOT A PRODUCT OF TWO CONSTANTS.
    # A loop that stops after N polls of an M-second
    # sleep has waited N*(M + however long each poll itself took), and each poll
    # here is a full SSH attempt through an SSM tunnel to a box that is not
    # answering. A message that says 600s after waiting 900 sends the operator
    # to the wrong question, and it is the number they will quote. The fake
    # clock above is what lets this case tell the two apart.
    local elapsed named
    elapsed="$(($(cat "$REC/clock") - CLOCK_AT_START))"
    # No `\b` — this drive runs on a BSD sed too, where it is not a word
    # boundary but a literal `b`, and the extractor then finds nothing and the
    # case reports "names no number" for every message including a correct one.
    named="$(grep -oE '[0-9]+s' "$W/err" | tr -d 's' | tail -n 1)"
    if [ -z "$named" ]; then
        bad "the refusal names no number of seconds at all: $(head -n 2 "$W/err" 2>/dev/null | tr '\n' ' ')"
    elif [ "$named" = "$elapsed" ] || [ "$((named > elapsed ? named - elapsed : elapsed - named))" -le "10" ]; then
        ok "the refusal names ${named}s and the wait really took ${elapsed}s of the box's clock"
    else
        bad "the refusal names ${named}s but the wait took ${elapsed}s on the clock — that is a
      product of the poll count and the sleep, not the time anyone waited.
      $(head -n 2 "$W/err" 2>/dev/null | tr '\n' ' ')"
    fi
    # And it did not simply give up early: a ceiling that is not reached is a
    # box terminated while it was still booting.
    if [ "$elapsed" -ge "600" ]; then
        ok "it waited the whole ${elapsed}s ceiling before giving up on the box"
    else
        bad "it gave up after ${elapsed}s, short of the 600s ceiling the wrapper declares"
    fi
}

case_bake_terminates_its_builder_when_the_recipe_fails() {
    CURRENT=case_bake_terminates_its_builder_when_the_recipe_fails
    world_new bake_fails
    world_bake_ready
    printf 'bake: step 7 failed\n' >"$REC/ssh/default.out"
    vb -- bake
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2, got ${VB_RC}"
        report
        return
    }
    [ "$(op_count 'ec2 create-image')" = "0" ] && ok "nothing was captured from a half-built box" ||
        bad "it captured an image from a recipe that did not finish"
    [ "$(op_count 'ec2 terminate-instances')" = "1" ] && ok "the builder was terminated anyway" ||
        bad "a failed bake left its box running"
    said "terminated" && ok "it says the box was taken down" || bad "it does not say what happened to the box"
}

# THE OTHER HALF OF THE PAIR ABOVE. That one fails by SAYING the wrong thing
# with a zero status; this one dies with a status while saying the right thing.
# A wrapper that only reads the words certifies a recipe that crashed after
# printing them, and a wrapper that only reads the status certifies one that
# exited 0 having done nothing.
case_bake_terminates_its_builder_when_the_recipe_session_fails() {
    CURRENT=case_bake_terminates_its_builder_when_the_recipe_session_fails
    world_new bake_recipe_status
    world_bake_ready
    # The recipe is the session the map above names, so this is the recipe's
    # own exit status and nothing else's.
    printf '%s\n' 3 >"$REC/ssh/${SSH_RECIPE}.rc"
    vb -- bake
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2 when the recipe session died, got ${VB_RC}"
        report
        return
    }
    [ "$(op_count 'ec2 create-image')" = "0" ] && ok "nothing was captured from a session that died" ||
        bad "it captured an image from a recipe session that exited non-zero"
    [ "$(op_count 'ec2 terminate-instances')" = "1" ] && ok "the builder was terminated" ||
        bad "a recipe session that exited non-zero left its box running"
    err_has "exit 3" && ok "the refusal names the recipe's own status" ||
        bad "the refusal does not name the status the recipe died with"
}

# FIELD TEST 3 WROTE THIS CASE. The box booted, the marker arrived, the seam
# worked — and then the push was refused by a pre-push hook on the operator's
# own machine, the wrapper exited 1, and the box stayed up billing by the
# minute until a human noticed it. Nothing on a bake box explains a refusal
# that happened before a byte left the laptop, and nothing on it can fix one,
# so the box has no reason to outlive the attempt.
case_bake_terminates_its_builder_when_the_push_is_refused() {
    CURRENT=case_bake_terminates_its_builder_when_the_push_is_refused
    world_new bake_push_refused
    world_bake_ready
    printf '%s\n' 128 >"$REC/git.push.rc"
    printf 'pre-push: refused\nerror: failed to push some refs\n' >"$REC/git.push.err"
    vb -- bake
    [ "$VB_RC" = "1" ] || {
        bad "wanted exit 1 when the push was refused, got ${VB_RC}"
        report
        return
    }
    local term
    term="$(nth_call_of "terminate-instances" 1 || true)"
    case "$term" in
    *"terminate-instances --instance-ids i-bake"*) ok "the builder was terminated by id" ;;
    *) bad "no 'terminate-instances --instance-ids i-bake' in the recorded argv — the box was left billing: ${term:-<none>}" ;;
    esac
    [ "$(op_count 'ec2 terminate-instances')" = "1" ] && ok "exactly once" ||
        bad "$(op_count 'ec2 terminate-instances') terminate-instances calls, wanted 1"
    [ "$(op_count 'ec2 create-image')" = "0" ] && ok "nothing was captured from a box that was never pushed to" ||
        bad "it captured an image from a box the push never reached"
    # BY CONTENT, NOT BY ORDINAL. The push opens sessions of its own — the
    # throughput probe and the shallow-update config — so "session 2 does not
    # exist" stopped being the same claim as "the recipe never ran".
    if grep -l -F -- "bake.sh" "$REC"/ssh/*.flat >/dev/null 2>&1; then
        bad "it ran the recipe after a refused push: $(grep -l -F -- "bake.sh" "$REC"/ssh/*.flat | tr '\n' ' ')"
    else
        ok "the recipe never ran on a checkout the push never landed in"
    fi
    said "terminated i-bake" && ok "and it SAYS the box was taken down" ||
        bad "the refusal never says what happened to the box"
    # AND THE SUMMARY PRINTS ON THE WAY OUT OF A FAILURE, naming the phase that
    # was in flight — which is the phase the operator has to go and look at.
    local phases
    phases="$(grep -F 'phases' "$W/out" 2>/dev/null || true)"
    case "$phases" in
    *"push"*"incomplete"*) ok "the phase summary printed on the failure and names push as the one in flight" ;;
    *) bad "no phase summary naming the incomplete push on the way out: ${phases:-<none>}" ;;
    esac
}

# THE EARLIEST FAILURE AFTER THE LAUNCH, and the one that looks least like a
# failure: a box that booted, took its money, and never said hello. `up` leaves
# such a box to the operator and tells them so; a bake has a teardown armed, so
# the same refusal here must not send them after a machine that is already
# going down.
case_bake_terminates_its_builder_when_the_agent_never_registers() {
    CURRENT=case_bake_terminates_its_builder_when_the_agent_never_registers
    world_new bake_no_ssm
    world_bake_ready
    ans "ssm_describe-instance-information" "Pending"
    vb -- bake
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2 when the agent never registered, got ${VB_RC}"
        report
        return
    }
    [ "$(op_count 'ec2 terminate-instances')" = "1" ] && ok "the builder was terminated when its agent never checked in" ||
        bad "a box whose agent never registered was left running"
    [ ! -f "$REC/ssh/1.flat" ] && ok "and nothing was attempted over a transport that never came up" ||
        bad "it reached for the transport of a box that never registered"
    if err_has "down i-bake"; then
        bad "the refusal sends the operator after a box its own teardown is already taking down"
    else
        ok "the refusal says the teardown has it, rather than handing the operator a stale command"
    fi
    # The phase in flight was the wait, and the summary says how long it was.
    local phases
    phases="$(grep -F 'phases' "$W/out" 2>/dev/null || true)"
    case "$phases" in
    *"online 300s (incomplete)"*) ok "the summary names the 300s ceiling the wait actually spent" ;;
    *) bad "the summary does not name the incomplete online wait: ${phases:-<none>}" ;;
    esac
}

# THE OPERATOR IS A FAILURE PATH TOO, and the commonest one: a bake takes
# twenty minutes, so a ^C somewhere in the middle of it is an ordinary
# afternoon. A wrapper whose teardown lives only in the branches it wrote has
# no branch for that, and the box outlives the session that launched it.
case_bake_terminates_its_builder_when_the_wrapper_is_killed() {
    CURRENT=case_bake_terminates_its_builder_when_the_wrapper_is_killed
    world_new bake_killed
    world_bake_ready
    # The readiness probe is the first session and it runs straight off the
    # wrapper's own shell, so this signal reaches the subject and not a
    # subshell of it.
    printf 'TERM\n' >"$REC/ssh/1.signal"
    printf '%s\n' 1 >"$REC/ssh/default.rc"
    vb -- bake
    [ "$VB_RC" = "143" ] || {
        bad "wanted exit 143 (SIGTERM) from a killed wrapper, got ${VB_RC}"
        report
        return
    }
    [ "$(op_count 'ec2 terminate-instances')" = "1" ] && ok "a killed wrapper takes its box down on the way out" ||
        bad "a killed wrapper left its box running — the orphan nobody is watching for"
    said "terminated i-bake" && ok "and says so" || {
        bad "it does not say what happened to the box"
        report
    }
    [ "$(op_count 'ec2 create-image')" = "0" ] && ok "nothing was captured" ||
        bad "it captured an image from a bake that was killed"
}

case_bake_terminates_its_builder_when_the_image_never_lands() {
    CURRENT=case_bake_terminates_its_builder_when_the_image_never_lands
    world_new bake_image_missing
    world_bake_ready
    # `create-image` answering None is the API's way of saying it did not make
    # one. The recipe finished, so the box is a fully built machine — and a
    # fully built machine nobody captured is still just a bill.
    ans "ec2_create-image" "None"
    vb -- bake
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2 when create-image returned no image, got ${VB_RC}"
        report
        return
    }
    [ "$(op_count 'ec2 terminate-instances')" = "1" ] && ok "the builder was terminated when the capture produced nothing" ||
        bad "a bake whose create-image returned nothing left its box running"
    said "terminated i-bake" && ok "and it says so" ||
        bad "it does not say what happened to the box"
}

# THE FAILURE PATH OF THE FAILURE PATH, which is the one nothing else here
# reaches. Every case above proves the teardown CALLS `terminate-instances`;
# none of them asks what happens when that call is the thing that fails, and
# that is exactly how an orphan is made: the wrapper exits reporting the
# original failure, the operator reads it, and a box nobody mentioned bills by
# the minute until the census or the expiry tag catches it. `RequestLimitExceeded`
# is EC2's own answer to a burst of calls and the likeliest one at minute 90 of
# a bake; an expired token is the other, and it is worse, because the retry the
# operator reaches for will fail the same way.
#
# WHAT THE WRAPPER OWES HERE, and all four are asserted below: the id, the two
# commands (take it down, then read the fleet back), a status that is still the
# ORIGINAL failure's — the terminate is the cleanup, not the verdict — and the
# phase summary, because the phase in flight is what the operator has to go and
# look at either way.
case_a_teardown_that_cannot_terminate_says_so_and_names_the_hand() {
    CURRENT=case_a_teardown_that_cannot_terminate_says_so_and_names_the_hand
    world_new bake_teardown_throttled
    world_bake_ready
    # The push is refused, so the ONLY thing that terminates this box is the
    # trap — and the trap's own terminate is what fails.
    printf '%s\n' 128 >"$REC/git.push.rc"
    printf 'pre-push: refused\n' >"$REC/git.push.err"
    rcf "ec2_terminate-instances" 254
    errf "ec2_terminate-instances" "An error occurred (RequestLimitExceeded) when calling the TerminateInstances operation: Request limit exceeded."
    vb -- bake
    # THE ORIGINAL FAILURE'S STATUS. The push was refused, which is a finding
    # (1); a teardown that could not clean up does not get to rewrite that into
    # its own 2, because what the operator has to fix is still the refusal.
    [ "$VB_RC" = "1" ] || {
        bad "wanted the push refusal's own exit 1 back, got ${VB_RC} — the teardown's failure
      replaced the verdict the operator has to act on"
        report
        return
    }
    err_has "could not terminate i-bake" && ok "it says which box it could not terminate, by id" ||
        bad "nothing in the output names the box that is still up: $(tr '\n' ' ' <"$W/err")"
    err_has "TAKE IT DOWN BY HAND" && ok "and that the operator now owns it" ||
        bad "the box was left up without saying that the hand is now the only way it goes down"
    err_has "down i-bake" && ok "and the command that takes it down" ||
        bad "the message does not spell the down command for this id"
    # THE CENSUS, WHICH IS THE SECOND COMMAND AND NOT DECORATION. A terminate
    # that failed may also have HALF worked, or the box may already be going
    # down, and the operator's next question is always the fleet rather than
    # this one box.
    err_has "census" && ok "and the census, which is the question the operator asks next" ||
        bad "the message names no way to read the fleet back, so the operator's next move is a
      guess about whether the box is really still there: $(tr '\n' ' ' <"$W/err")"
    local phases
    phases="$(grep -F 'phases' "$W/out" 2>/dev/null || true)"
    case "$phases" in
    *"push"*"incomplete"*) ok "the phase summary still prints, naming push as the phase in flight" ;;
    *) bad "a teardown that could not terminate also swallowed the phase summary: ${phases:-<none>}" ;;
    esac
    # AND THE KEY STAYS. `terminate_one` deletes the box's directory AFTER the
    # call it makes; the private half is the only way back into a box the
    # operator has just been told to take down by hand, so a teardown that
    # removed it would be handing over an unreachable machine.
    [ -f "$W/vhome/i-bake/id_ed25519" ] && ok "the private key survives a box that is still up" ||
        bad "the box is still up and its key is gone — there is no way in from here"
}

# THE SECOND FIXTURE, AND IT IS THE WORSE ONE. An expired token refuses every
# call including the retry, and it arrives at the end of a long bake rather
# than at the start — the wrapper cannot terminate, cannot describe, and cannot
# tell the operator anything except which id to go and look at. The original
# failure here is a 2 (the capture produced nothing), so this case also proves
# the status passthrough is the ORIGINAL's in both directions rather than a
# constant that happened to match the other case.
case_a_teardown_whose_credential_expired_still_hands_over_the_id() {
    CURRENT=case_a_teardown_whose_credential_expired_still_hands_over_the_id
    world_new bake_teardown_expired
    world_bake_ready
    # The recipe finished and the capture produced nothing: a fully built box
    # and no image, which is the most expensive machine in the fleet to leave
    # running.
    ans "ec2_create-image" "None"
    rcf "ec2_terminate-instances" 255
    errf "ec2_terminate-instances" "An error occurred (ExpiredToken) when calling the TerminateInstances operation: The security token included in the request is expired"
    vb -- bake
    [ "$VB_RC" = "2" ] || {
        bad "wanted the capture failure's own exit 2 back, got ${VB_RC}"
        report
        return
    }
    err_has "could not terminate i-bake" && ok "the id is handed over" ||
        bad "the box that is still up is not named: $(tr '\n' ' ' <"$W/err")"
    err_has "TAKE IT DOWN BY HAND" && ok "and the hand is named as the only way it goes down" ||
        bad "nothing says the operator now owns the box"
    err_has "ExpiredToken" && ok "and the API's own refusal is still in the output, unfiltered" ||
        bad "the AWS error was swallowed, so the operator cannot tell a throttle from an expired
      credential — and only one of those is fixed by trying again"
    local phases
    phases="$(grep -F 'phases' "$W/out" 2>/dev/null || true)"
    case "$phases" in
    *"total"*) ok "the phase summary still prints" ;;
    *) bad "no phase summary on the way out: ${phases:-<none>}" ;;
    esac
}

# THE SIBLING SITES, censused rather than assumed. The trap is not the only
# place this wrapper terminates a bake box: two refusals in the body take the
# box down THEMSELVES and then clear `BAKE_BOX` so the trap does not do it
# twice. A `|| true` at either of those is a failed terminate that says nothing
# at all — the trap has already been told there is no box — which is the same
# orphan as above with the one sentence that would have named it removed.
case_a_teardown_in_the_body_cannot_swallow_a_failed_terminate() {
    CURRENT=case_a_teardown_in_the_body_cannot_swallow_a_failed_terminate
    world_new bake_body_terminate_fails
    world_bake_ready
    # The recipe says the wrong thing, which is the body refusal that
    # terminates before it dies.
    printf 'bake: step 7 failed\n' >"$REC/ssh/default.out"
    rcf "ec2_terminate-instances" 254
    errf "ec2_terminate-instances" "An error occurred (RequestLimitExceeded) when calling the TerminateInstances operation: Request limit exceeded."
    vb -- bake
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2 when the recipe did not finish, got ${VB_RC}"
        report
        return
    }
    err_has "could not terminate i-bake" && ok "a failed terminate in the body says so too" ||
        bad "the body's own terminate failed and the wrapper said nothing: the box is up, the
      trap was told there is none, and the operator has a recipe failure to read and no box
      to look for: $(tr '\n' ' ' <"$W/err")"
    err_has "TAKE IT DOWN BY HAND" && ok "with the same sentence the trap uses" ||
        bad "the body's message is not the trap's, so one of the two ways out of a bake hands
      the operator less than the other"
    err_has "census" && ok "and the same two commands" ||
        bad "the body's message does not name the census"
    # ONE ATTEMPT, NOT TWO. The body terminates and then clears the box; a
    # second call out of the trap would be the wrapper asking AWS the same
    # question twice on a credential that just refused it.
    [ "$(op_count 'ec2 terminate-instances')" = "1" ] && ok "exactly one terminate attempt" ||
        bad "$(op_count 'ec2 terminate-instances') terminate-instances calls, wanted 1"
}

# `date +%s` IN THE DRIVE'S WORLD IS THE DRIVE'S CLOCK, so the numbers below are
# arithmetic rather than observation: SSM answers Pending once (one 10s poll),
# every session over the transport costs DRIVE_SSH_SECONDS, git costs nothing,
# and the image is available on the first ask. A stamp read from the machine's
# real clock instead of the wrapper's would disagree with the last line's, which
# is the assertion at the bottom.
case_bake_stamps_its_phases_and_prints_their_durations() {
    CURRENT=case_bake_stamps_its_phases_and_prints_their_durations
    world_new bake_timed
    world_bake_ready
    printf 'Pending\n' >"$REC/ans/ssm_describe-instance-information.1"
    printf 'Online\n' >"$REC/ans/ssm_describe-instance-information.2"
    local started
    started="$(cat "$REC/clock")"
    # THE FLOOR IS LOWERED FOR THIS CASE ALONE, and saying why is the point: at
    # DRIVE_SSH_SECONDS=37 the throughput probe measures 1 MB in 37 s — about
    # 27 KB/s — and refuses, which is the probe working. This case is about the
    # phase clock, so it asks for a floor the fixture clears; the refusal has
    # its own case.
    vb DRIVE_SSH_SECONDS=37 DJB_VERIFIER_MIN_KBPS=1 -- bake
    if [ "$VB_RC" != "0" ]; then
        bad "bake exited ${VB_RC}"
        report
        return
    fi

    # EVERY LINE THE WRAPPER NARRATES, not a sample of them: an unstamped phase
    # line is the one whose duration nobody can work out afterwards, and it is
    # always the one that mattered.
    local unstamped
    unstamped="$(grep '^verifier_box: ' "$W/out" | grep -vE '^verifier_box: \[[0-9]{2}:[0-9]{2}:[0-9]{2}\] ' || true)"
    [ -z "$unstamped" ] && ok "every line the wrapper narrated carries an HH:MM:SS stamp" ||
        bad "lines with no wall-clock stamp:
$(printf '%s\n' "$unstamped" | sed 's/^/      /')"

    local phases want miss=""
    phases="$(grep -F 'phases' "$W/out" 2>/dev/null || true)"
    [ -n "$phases" ] || {
        bad "no phase summary was printed at all"
        report
        return
    }
    # 10s of SSM polling, 37s of bootstrap probe, 148s of push, 37s of recipe
    # session, an instant capture. The push's four sessions at 37s each are the
    # throughput probe, the shallow-update config, the worktree reset and its
    # read-back — the vouch and the transfer are git's and cost the fake clock
    # nothing. That 148 is the push's real cost made visible in the summary the
    # operator reads, which is where a cost belongs; it grew by two sessions
    # when the push started moving the box's FILES and not only its ref, and
    # those two sessions are the difference between measuring the rung and
    # measuring the image.
    for want in "online 10s" "bootstrap 37s" "push 148s" "recipe 37s" "image 0s"; do
        case "$phases" in *"$want"*) ;; *) miss="${miss} '${want}'" ;; esac
    done
    [ -z "$miss" ] && ok "the summary names all five phases with the durations the clock actually spent" ||
        bad "the summary is missing:${miss}
      got: ${phases}"

    local elapsed
    elapsed="$(($(cat "$REC/clock") - started))"
    case "$phases" in
    *"total ${elapsed}s"*) ok "and the total is the ${elapsed}s the whole bake spent, not a sum of constants" ;;
    *) bad "the summary's total is not ${elapsed}s: ${phases}" ;;
    esac

    # THE STAMP COMES FROM THE SUBJECT'S CLOCK. A stamp taken from the machine's
    # real clock would read the wall time this case ran at, which is 84s adrift
    # of the clock the wrapper itself measured with — and every duration above
    # would still be right, because the durations are subtractions.
    local printed expected
    printed="$(printf '%s' "$phases" | sed -n 's/^verifier_box: \[\([0-9:]*\)\].*/\1/p')"
    expected="$(stamp_utc "$(cat "$REC/clock")")"
    [ "$printed" = "$expected" ] && ok "the summary's stamp ${printed} is the wrapper's own clock, not the machine's" ||
        bad "the summary is stamped ${printed:-<none>}; the wrapper's clock said ${expected}"
}

# THE ONE FAILURE THAT IS ALLOWED TO LEAVE A MACHINE RUNNING, and it is the
# operator's word rather than the wrapper's judgment. A recipe that died at
# step 8 is a box with seven steps already done on it and the failure still in
# place; walking the rest by hand through the tunnel in one sitting is what
# stops the next twenty-minute bake being another guess. FIELD TEST 5 is the
# argument — the recipe's first line failed, the box went down (correctly, with
# no flag), and the next thing anybody learned about that box cost a second
# bake.
case_bake_keep_leaves_the_box_up_when_the_recipe_fails() {
    CURRENT=case_bake_keep_leaves_the_box_up_when_the_recipe_fails
    world_new bake_keep
    world_bake_ready
    # The recipe session dies with its own status, so the exit below is a
    # number the flag has to pass through rather than a constant.
    printf '%s\n' 3 >"$REC/ssh/${SSH_RECIPE}.rc"
    vb -- bake --keep
    [ "$VB_RC" = "3" ] || {
        bad "wanted the recipe's own exit 3 back under --keep, got ${VB_RC}"
        report
        return
    }
    # THE CLAIM, and it is a count rather than a sentence: nothing terminated.
    [ "$(op_count 'ec2 terminate-instances')" = "0" ] && ok "the box was left up — no terminate-instances at all" ||
        bad "--keep terminated the box anyway ($(op_count 'ec2 terminate-instances') call(s)): the flag did nothing"
    [ "$(op_count 'ec2 create-image')" = "0" ] && ok "and nothing was captured from a recipe that did not finish" ||
        bad "it captured an image from a half-built box"
    err_has "i-bake IS STILL UP" && ok "it says the box is still up, deliberately" ||
        bad "nothing says the box was kept: $(tr '\n' ' ' <"$W/err")"
    err_has "down i-bake" && ok "and the command that takes it down" ||
        bad "the hand-over names no down command"
    err_has "census" && ok "and the census" || bad "the hand-over names no census"
    # THE BACKSTOP SENTENCE, and it has to be the TRUE one: a bake box runs no
    # reaper (the recipe installs the unit disabled; only the launch seam
    # enables it), so its expiry tag is a label the census reads and not a
    # timer the machine enforces. An operator who believes the box reaps itself
    # is an operator who leaves it up.
    err_has "no reaper" && ok "and that nothing on the box is going to take it down for them" ||
        bad "the hand-over does not say the box is unwatched — a bake box runs no reaper and its
      expiry tag is a label, not a timer: $(tr '\n' ' ' <"$W/err")"
    # THE TUNNEL COMMAND, derived rather than typed: the key this run made, the
    # ProxyCommand this wrapper builds, the account it uses. An operator who has
    # to reconstruct it is an operator who does not walk the steps.
    local key_line
    key_line="$(grep -F -- "ssh -i" "$W/err" 2>/dev/null || true)"
    case "$key_line" in
    *"$W/vhome/i-bake/id_ed25519"*"ProxyCommand="*"verifier@i-bake"*)
        ok "the copyable tunnel command carries this box's own key, the ProxyCommand and the account" ;;
    *) bad "the hand-over's ssh command is not the one ssh_to opens: ${key_line:-<none>}" ;;
    esac
    grep -F -- "bake.sh --plan" "$W/err" >/dev/null &&
        ok "and it points at the recipe's own runbook, which is what 'the steps that are left' means" ||
        bad "nothing tells the operator how to see the remaining steps"
    # THE PHASE SUMMARY STILL PRINTS: the phase in flight is what they are about
    # to go and look at.
    local phases
    phases="$(grep -F 'phases' "$W/out" 2>/dev/null || true)"
    case "$phases" in
    *"recipe"*"incomplete"*) ok "the phase summary still prints, naming recipe as the phase in flight" ;;
    *) bad "no phase summary naming the incomplete recipe: ${phases:-<none>}" ;;
    esac
}

# THE OTHER HALF OF THE FLAG, and it is the half that keeps it from being a
# money leak: --keep covers the two failures where the BOX IS GOOD and the
# operator can act on it. Everything else still goes down, because in every one
# of those the box is worth nothing to anybody — no repository, no tree, or
# nobody there to use it.
case_bake_keep_still_tears_down_every_box_it_does_not_cover() {
    CURRENT=case_bake_keep_still_tears_down_every_box_it_does_not_cover

    # A PUSH REFUSED ON THIS MACHINE. There is no tree on the box and nothing
    # on it can fix a refusal that happened before a byte left the laptop.
    world_new bake_keep_push
    world_bake_ready
    printf '%s\n' 128 >"$REC/git.push.rc"
    printf 'pre-push: refused\n' >"$REC/git.push.err"
    vb -- bake --keep
    [ "$VB_RC" = "1" ] || bad "wanted the push refusal's exit 1 under --keep, got ${VB_RC}"
    [ "$(op_count 'ec2 terminate-instances')" = "1" ] &&
        ok "--keep does not keep a box the push never reached" ||
        bad "--keep left a box up that has no tree on it and cannot be fixed from the box"

    # A BOOTSTRAP THAT NEVER FINISHED. No git, no repository: there is nothing
    # to walk by hand.
    world_new bake_keep_no_marker
    world_bake_ready
    printf '%s\n' 1 >"$REC/ssh/default.rc"
    vb -- bake --keep
    [ "$VB_RC" = "2" ] || bad "wanted exit 2 when the marker never arrived under --keep, got ${VB_RC}"
    [ "$(op_count 'ec2 terminate-instances')" = "1" ] &&
        ok "--keep does not keep a box whose cloud-init never finished" ||
        bad "--keep left up a box with no git and no repository on it"

    # A KILLED WRAPPER. The operator is not there to use what would be kept.
    world_new bake_keep_killed
    world_bake_ready
    printf 'TERM\n' >"$REC/ssh/1.signal"
    printf '%s\n' 1 >"$REC/ssh/default.rc"
    vb -- bake --keep
    [ "$VB_RC" = "143" ] || bad "wanted exit 143 from a killed --keep wrapper, got ${VB_RC}"
    [ "$(op_count 'ec2 terminate-instances')" = "1" ] &&
        ok "--keep does not survive the operator who is no longer there" ||
        bad "a killed --keep wrapper left its box running — the orphan nobody is watching for"

    # AND THE HAPPY PATH IS UNCHANGED: the work is in the AMI, so the box has
    # nothing left to offer.
    world_new bake_keep_ok
    world_bake_ready
    vb -- bake --keep
    [ "$VB_RC" = "0" ] || bad "a successful --keep bake exited ${VB_RC}"
    [ "$(op_count 'ec2 terminate-instances')" = "1" ] &&
        ok "--keep does not keep a box whose image was captured" ||
        bad "--keep left the builder running after a successful capture"

    # AND A MISTYPED FLAG IS STILL EXIT 2, never a silently ordinary bake.
    world_new bake_keep_typo
    world_bake_ready
    vb -- bake --kepe
    [ "$VB_RC" = "2" ] && ok "a mistyped --keep is exit 2, not a bake that quietly tears down" ||
        bad "wanted exit 2 on '--kepe', got ${VB_RC}"
    [ "$(op_count 'ec2 run-instances')" = "0" ] && ok "and nothing was launched before the refusal" ||
        bad "the refusal launched a box first"
}

# THE CAPTURE IS THE OTHER KEEPABLE FAILURE. Here the recipe FINISHED — twenty
# minutes of provisioning is standing on that box — and AWS produced no image.
# The default is still to take it down (a fully built box nobody captured is
# just a bill); --keep is the operator saying in advance that they are going to
# retry the capture by hand rather than pay for it twice.
case_bake_keep_leaves_the_box_up_when_the_capture_produces_nothing() {
    CURRENT=case_bake_keep_leaves_the_box_up_when_the_capture_produces_nothing
    world_new bake_keep_capture
    world_bake_ready
    ans "ec2_create-image" "None"
    vb -- bake --keep
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2 when create-image returned nothing under --keep, got ${VB_RC}"
        report
        return
    }
    [ "$(op_count 'ec2 terminate-instances')" = "0" ] &&
        ok "the fully built box was kept for a capture the operator can retry by hand" ||
        bad "--keep terminated a box the recipe had already finished on"
    err_has "create-image returned no image id" && ok "and it says why it was kept" ||
        bad "the hand-over does not name the failure it was kept for"
    err_has "i-bake IS STILL UP" && ok "and that the box is still up" ||
        bad "nothing says the box was kept"
}

# A REFUSED TAG IS NOT A LOST IMAGE, and the difference is twenty minutes and a
# box. `create-image` takes the tags in the same call that makes the image, so
# a policy that does not reach the image and snapshot ARNs refuses the WHOLE
# call and the capture produces nothing — over a machine that is finished and
# about to be thrown away. The capture therefore falls back to an UNTAGGED
# image and says, in the same breath, the two things the operator now needs:
# the id (because `up`'s tag lookup cannot see it) and the policy step that
# stops it happening again.
# THE BASE IMAGE IS THE VARIABLE NOBODY COULD NAME. The bake resolves "the
# latest Amazon Linux" from a public SSM parameter, so two field tests a day
# apart ran two different AMIs — and behaved so differently that the tunnel
# went from ~330 KB/s to ~7 KB/s — with nothing in either run recording which
# image it had been. An unpinned base makes every field test a different
# experiment. So: a knob pins it, the parameter is read ONCE when it does not,
# the id AND the image's own dated name are printed, and both ride on the
# image the bake captures.
case_the_base_image_is_pinned_printed_and_recorded_on_the_capture() {
    CURRENT=case_the_base_image_is_pinned_printed_and_recorded_on_the_capture
    world_new bake_base_ami
    world_bake_ready
    ans "ec2_describe-images__Images0NameState" "al2023-ami-2026.0.20260917.0-kernel-6.1-arm64	available"
    vb -- bake
    if [ "$VB_RC" != "0" ]; then
        bad "bake exited ${VB_RC}"
        report
        return
    fi
    said "ami-al2023" && ok "the resolved base image id is printed" ||
        bad "the bake never prints which base image it resolved"
    # AND THE TUNNEL'S MEASURED RATE, which is the other half of the same
    # question — a bake that says neither leaves a field test with a duration
    # and no way to tell a slow tunnel from a slow machine. It has to survive
    # `bake` calling the push with its stdout at /dev/null, which is exactly
    # where the first attempt at this line went.
    said "KB/s" && ok "and the throughput the tunnel actually carried, through the bake's own output" ||
        bad "the bake prints no measured tunnel throughput: stdout $(tr '\n' ' ' <"$W/out") / stderr $(tr '\n' ' ' <"$W/err")"
    said "al2023-ami-2026.0.20260917.0-kernel-6.1-arm64" &&
        ok "and the image's own DATED name, which is what tells two days apart" ||
        bad "the bake prints no dated image name — an id alone does not say which build it is"
    said "DJB_VERIFIER_AL2023_AMI=ami-al2023" &&
        ok "and the exact knob assignment that repeats this bake on the same base" ||
        bad "the bake does not print how to pin the base it just used"
    local img
    img="$(nth_call_of "create-image" 1 || true)"
    case "$img" in
    *"Key=djb:base-ami,Value=ami-al2023"*) ok "the captured image carries djb:base-ami" ;;
    *) bad "create-image does not tag the base image id: ${img}" ;;
    esac
    case "$img" in
    *"Key=djb:base-ami-name,Value=al2023-ami-2026.0.20260917.0-kernel-6.1-arm64"*)
        ok "and djb:base-ami-name, so the dated build survives on the artefact" ;;
    *) bad "create-image does not tag the base image NAME: ${img}" ;;
    esac
}

case_a_pinned_base_image_is_used_and_the_parameter_is_not_read() {
    CURRENT=case_a_pinned_base_image_is_used_and_the_parameter_is_not_read
    world_new bake_base_pinned
    world_bake_ready
    ans "ssm_get-parameters" "ami-whatever-is-latest-today"
    ans "ec2_describe-images__Images0NameState" "al2023-ami-pinned-build	available"
    vb DJB_VERIFIER_AL2023_AMI=ami-pinned -- bake
    if [ "$VB_RC" != "0" ]; then
        bad "bake exited ${VB_RC}"
        report
        return
    fi
    local call
    call="$(nth_call_of "run-instances" 1 || true)"
    case "$call" in
    *"--image-id ami-pinned"*) ok "the bake box launches from the pinned base" ;;
    *) bad "run-instances is '${call}'" ;;
    esac
    [ "$(op_count 'ssm get-parameters')" = "0" ] &&
        ok "and the 'latest' parameter was not read at all — a pin that still asks is not a pin" ||
        bad "$(op_count 'ssm get-parameters') ssm get-parameters call(s) on a pinned bake"
    if printf '%s' "$call" | grep -F -- "ami-whatever-is-latest-today" >/dev/null; then
        bad "today's latest reached the launch anyway"
    else
        ok "today's latest is nowhere in the launch"
    fi
}

case_census_prints_the_image_each_box_is_running() {
    CURRENT=case_census_prints_the_image_each_box_is_running
    world_new census_ami
    local future
    future="$(python3 -c 'import datetime;print((datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ"))')"
    printf 'i-one\tc7g.4xlarge\tverifier\t%s\t%s\t2026-09-15T10:00:00.000Z\tami-baked-7\n' "$OWNER" "$future" \
        >"$REC/ans/ec2_describe-instances__ReservationsInstancesInstanceIdInstance"
    vb -- census
    [ "$VB_RC" = "0" ] || {
        bad "census exited ${VB_RC}"
        report
        return
    }
    out_has "ami-baked-7" && ok "the census names the image the box is running" ||
        bad "the census does not print the box's image: $(tr '\n' ' ' <"$W/out")"
    local q
    q="$(nth_call_of "describe-instances" 1 || true)"
    case "$q" in
    *ImageId*) ok "and it asks for it in the query rather than inferring it" ;;
    *) bad "the census query does not read ImageId: ${q}" ;;
    esac
}

case_a_capture_whose_tags_are_refused_keeps_the_image_and_names_the_policy() {
    CURRENT=case_a_capture_whose_tags_are_refused_keeps_the_image_and_names_the_policy
    world_new bake_tags_refused
    world_bake_ready
    # The account's own words, from the refusal a live policy gave: the ARN it
    # names has no account id in it, which is the whole reason the grant missed.
    rcf "ec2_create-image.1" 254
    errf "ec2_create-image.1" "An error occurred (UnauthorizedOperation) when calling the CreateImage operation: You are not authorized to perform: ec2:CreateTags on resource: arn:aws:ec2:${RG}::snapshot/*"
    ans "ec2_create-image.2" "ami-untagged"
    vb -- bake
    # EXIT 1, THIS WRAPPER'S "a finding": the image exists and the thing that
    # finds images cannot see it. Not 0 (that would read as an ordinary bake
    # and the operator would go looking for the image with `up`), and not 2
    # (nothing was refused and nothing is unclear — a machine was captured).
    if [ "$VB_RC" != "1" ]; then
        bad "the bake exited ${VB_RC} — an untagged capture is a FINDING (1): not a lost image, not an ordinary success"
        report
        return
    fi
    ok "exit 1 — a finding, not a failure and not a silent pass"
    [ "$(op_count 'ec2 create-image')" = "2" ] && ok "the capture was retried once" ||
        bad "$(op_count 'ec2 create-image') create-image call(s), wanted 2 (tagged, then untagged)"
    local first second
    first="$(nth_call_of "create-image" 1 || true)"
    second="$(nth_call_of "create-image" 2 || true)"
    case "$first" in
    *--tag-specifications*) ok "the first attempt asks for the tags — untagged is the fallback, never the default" ;;
    *) bad "the first create-image carried no tag specifications: ${first}" ;;
    esac
    case "$second" in
    *--tag-specifications*) bad "the retry still asks for the tags it was just refused: ${second}" ;;
    *) ok "the retry drops the tag specifications and nothing else" ;;
    esac
    said "ami-untagged" && ok "it names the image that WAS captured" ||
        bad "the image id is nowhere in the output — the capture is lost to the operator"
    said "--image-id ami-untagged" && ok "and the command that launches from it, which the tag lookup cannot find" ||
        bad "it does not tell the operator how to use an untagged image"
    if said "verifier_bootstrap.sh" && said "create-policy-version"; then
        ok "and it names the policy step: the bootstrap, and the version publish an existing policy needs"
    else
        bad "the finding does not name what the policy needs — the next bake loses its tags too"
        report
    fi
    [ "$(op_count 'ec2 terminate-instances')" = "1" ] && ok "the bake box still went down" ||
        bad "the bake box was left running"
}

# ASCII ONLY, and it is the API's rule rather than this wrapper's taste:
# `create-image`'s name and description are 7-bit, and a single non-ASCII
# character refuses the call. The composed strings carry exactly two things
# from outside — the namespace and a git sha — so the namespace is where this
# can come from, and it is known before a box is launched. Refusing there costs
# nothing; discovering it at the capture costs the whole bake.
case_a_namespace_that_is_not_ascii_refuses_before_a_box_is_launched() {
    CURRENT=case_a_namespace_that_is_not_ascii_refuses_before_a_box_is_launched
    world_new bake_nonascii
    world_bake_ready
    vb DJB_DEPLOY_NAMESPACE="drivéns" -- bake
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2 on a non-ASCII namespace, got ${VB_RC}"
        report
        return
    }
    [ "$(op_count 'ec2 run-instances')" = "0" ] && ok "exit 2 with no box launched" ||
        bad "a bake box was launched for a capture that cannot name itself"
    [ "$(op_count 'ec2 create-image')" = "0" ] && ok "and no capture attempted" ||
        bad "create-image was called with a name the API refuses"
    said "ASCII" && ok "and the refusal says what is wrong with the name" ||
        bad "the refusal does not mention ASCII: $(tr '\n' ' ' <"$W/err")"
}

# THE OTHER HALF OF THE PRE-LAUNCH BLOCK, AND IT IS A GIT REF RATHER THAN A
# NAMESPACE. A checkout without `refs/heads/main` (`git clone --branch <tag>`,
# the population `setup.sh`'s first step exists to serve) used to pay for a box,
# a bootstrap and a pack before the RECIPE phase died on git's own `fatal:
# ambiguous argument 'main'` while composing the image's name. The name comes
# from HEAD now; the guard stays because `--loop`'s scope derivation on the box
# refuses without that ref, so a bake from such a checkout is twenty minutes and
# a bill spent on an image whose gate cannot run. Same class as the non-ASCII
# namespace beside it, same fix: ask before the launch.
case_bake_refuses_before_the_launch_when_there_is_no_local_main() {
    CURRENT=case_bake_refuses_before_the_launch_when_there_is_no_local_main
    world_new bake_no_main
    world_bake_ready
    printf '%s\n' "$ROOT" >"$REC/git.no-main"
    vb -- bake
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2 in a checkout with no local main, got ${VB_RC} (128 is git's own fatal, reached in the recipe phase with a box already up)"
        report
        return
    }
    [ "$(op_count 'ec2 run-instances')" = "0" ] && ok "exit 2 with no box launched" ||
        bad "a bake box was launched for a capture that cannot name itself"
    [ "$(op_count 'ec2 create-image')" = "0" ] && ok "and no capture attempted" ||
        bad "create-image was called after the name could not be composed"
    said "NO local refs/heads/main" && ok "the refusal names the ref that is missing" ||
        bad "the refusal does not name the ref: $(tr '\n' ' ' <"$W/err")"
    said "git branch main HEAD" && said "setup.sh" &&
        ok "and both legal moves — create the ref, or bake from a checkout that has one" ||
        bad "the refusal does not name the legal moves: $(tr '\n' ' ' <"$W/err")"
    # AND IT SAYS WHAT THE REF IS FOR, WHICH IS NO LONGER THE NAME. The image is
    # named after HEAD — the tree the push sends — so what is left needing a
    # local `main` is the gate on the box: `--loop`'s scope derivation refuses
    # without one. Saying so is what keeps a later reader from deleting this
    # guard as obsolete along with the naming it used to protect.
    said "--loop scope" && ok "and says what still needs the ref: the gate's scope on the box" ||
        bad "the refusal does not say what the ref is for: $(tr '\n' ' ' <"$W/err")"
}

case_bake_prune_keeps_the_newest_two() {
    CURRENT=case_bake_prune_keeps_the_newest_two
    world_new bake_prune
    printf 'ami-4\tsnap-4\t2026-09-15T10:00:00Z\nami-3\tsnap-3\t2026-09-14T10:00:00Z\nami-2\tsnap-2\t2026-09-13T10:00:00Z\nami-1\tsnap-1\t2026-09-12T10:00:00Z\n' \
        >"$REC/ans/ec2_describe-images__reverse"
    vb -- bake --prune
    [ "$VB_RC" = "0" ] || {
        bad "prune exited ${VB_RC}"
        report
        return
    }
    [ "$(op_count 'ec2 deregister-image')" = "2" ] && ok "exactly two images deregistered" ||
        bad "$(op_count 'ec2 deregister-image') deregister-image calls, wanted 2"
    [ "$(op_count 'ec2 delete-snapshot')" = "2" ] && ok "their two snapshots deleted with them" ||
        bad "$(op_count 'ec2 delete-snapshot') delete-snapshot calls, wanted 2"
    local flat
    flat="$(cat "$REC"/calls/*.flat 2>/dev/null || true)"
    case "$flat" in
    *ami-4*) bad "the newest image was deregistered" ;;
    *) ok "the newest two were never touched" ;;
    esac
    out_has "pruned ami-1" && out_has "pruned ami-2" && ok "it names what it pruned" ||
        bad "it does not name the pruned images"
}

# THROUGH THE BLOCK MAPPINGS, NEVER THROUGH A TAG, and the reason is the case
# two functions up: an image whose tags were refused still has snapshots, and a
# prune that finds them by `tag:djb:role` would deregister the image and leave
# the storage behind, billing, with nothing left pointing at it. The image's
# own BlockDeviceMappings are the only account of what it owns — and there can
# be more than one.
case_bake_prune_finds_snapshots_through_the_block_mappings() {
    CURRENT=case_bake_prune_finds_snapshots_through_the_block_mappings
    world_new bake_prune_mappings
    # Two images with TWO volumes each: a query that reads only the first
    # mapping leaves half the storage behind.
    printf 'ami-4\tsnap-4a\tsnap-4b\t2026-09-15T10:00:00Z\nami-3\tsnap-3a\tsnap-3b\t2026-09-14T10:00:00Z\nami-2\tsnap-2a\tsnap-2b\t2026-09-13T10:00:00Z\nami-1\tsnap-1a\tsnap-1b\t2026-09-12T10:00:00Z\n' \
        >"$REC/ans/ec2_describe-images__reverse"
    vb -- bake --prune
    [ "$VB_RC" = "0" ] || {
        bad "prune exited ${VB_RC}"
        report
        return
    }
    local q
    q="$(nth_call_of "describe-images" 1 || true)"
    case "$q" in
    *BlockDeviceMappings*) ok "the prune reads the images' BlockDeviceMappings" ;;
    *) bad "the prune's describe-images does not read BlockDeviceMappings: ${q}" ;;
    esac
    if printf '%s' "$q" | grep -F -- "Name=tag:" >/dev/null; then
        # The IMAGE filter is by tag and must stay so; what must never happen is
        # a SNAPSHOT lookup by tag, which is a separate describe-snapshots call.
        ok "the IMAGES are still filtered by tag (that is what makes them ours)"
    else
        bad "the image filter lost its tag scope: ${q}"
    fi
    [ "$(op_count 'ec2 describe-snapshots')" = "0" ] && ok "and no describe-snapshots anywhere — snapshots are never found by tag" ||
        bad "$(op_count 'ec2 describe-snapshots') describe-snapshots call(s): the prune is looking snapshots up instead of reading the image"
    [ "$(op_count 'ec2 delete-snapshot')" = "4" ] && ok "both snapshots of both pruned images deleted (4)" ||
        bad "$(op_count 'ec2 delete-snapshot') delete-snapshot call(s), wanted 4 — a second volume left behind is storage nobody can see"
    local flat
    flat="$(cat "$REC"/calls/*.flat 2>/dev/null || true)"
    case "$flat" in
    *snap-4a* | *snap-4b* | *snap-3a* | *snap-3b*) bad "a kept image's snapshot was deleted" ;;
    *) ok "the kept images' snapshots were never touched" ;;
    esac
}

# =============================================================================
# the family rules, and what must not move
# =============================================================================

# =============================================================================
# 1.9 — the zone axis, the Spot request, and the box that names itself
# =============================================================================
#
# WHY THERE IS A ZONE AXIS AT ALL. `run-instances` with no `--subnet-id` lets
# EC2 pick, and EC2 picks the same zone for eight shards fired within a second
# of each other — so one zone's Spot capacity is the whole bank's, and
# `InsufficientInstanceCapacity` there refuses the bank. Everything in this
# section is the machinery for asking somewhere else, plus the two things a
# reclaim leaves behind that nothing could read: the request's own status code
# and a box the wrapper never got as far as naming.

# A world in which `up --az` can resolve a zone: the security group's VPC, the
# zones that VPC reaches, and a subnet per zone. THREE SEPARATE FIXTURE KEYS,
# one per question, because the shim's longest-prefix rule would otherwise let
# the group's own `GroupId` answer stand in for its `VpcId` — and a fixture
# that answers two questions is a fixture that hides which one was asked.
world_zones_ready() {
    ans "ec2_describe-security-groups__SecurityGroups0VpcId" "vpc-v"
    ans "ec2_describe-subnets__SubnetsAvailabilityZone" "$(printf '%sa\t%sb\t%sc' "$RG" "$RG" "$RG")"
}

case_up_with_az_launches_into_that_zones_subnet() {
    CURRENT=case_up_with_az_launches_into_that_zones_subnet
    world_new up_az
    world_up_ready
    world_zones_ready
    ans "ec2_describe-subnets__Subnets0SubnetId" "subnet-b"
    vb -- up --for X --az "${RG}b"
    if [ "$VB_RC" != "0" ]; then
        bad "up --az exited ${VB_RC}"
        report
        return
    fi
    local call
    call="$(nth_call_of "run-instances" 1 || true)"
    case "$call" in
    *"--subnet-id subnet-b"*) ok "the launch carries the subnet of the zone that was asked for" ;;
    *) bad "the launch carries no --subnet-id: ${call}" ;;
    esac
    local sub
    sub="$(nth_call_of "describe-subnets" 1 || true)"
    case "$sub" in
    *"Name=vpc-id,Values=vpc-v"*) ok "the subnet was looked for in the SECURITY GROUP's VPC, not the account's default" ;;
    *) bad "the subnet lookup does not filter on the group's VpcId: ${sub}" ;;
    esac
    case "$sub" in
    *"Name=availability-zone,Values=${RG}b"*) ok "and in the zone that was typed" ;;
    *) bad "the subnet lookup does not filter on the typed zone: ${sub}" ;;
    esac

    # AND THE ARGV IS UNCHANGED WITHOUT THE FLAG. A default zone chosen here
    # would be this wrapper quietly deciding where every box in the account
    # lands, and it would be invisible: the launch would still work.
    world_new up_no_az
    world_up_ready
    world_zones_ready
    ans "ec2_describe-subnets__Subnets0SubnetId" "subnet-b"
    vb -- up --for X
    [ "$VB_RC" = "0" ] || {
        bad "a plain up exited ${VB_RC}"
        report
        return
    }
    call="$(nth_call_of "run-instances" 1 || true)"
    case "$call" in
    *--subnet-id*) bad "a launch with no --az still pinned a subnet: ${call}" ;;
    *) ok "no --az: the run-instances argv carries no --subnet-id at all" ;;
    esac
    [ "$(op_count 'ec2 describe-subnets')" = "0" ] &&
        ok "and no subnet was even looked up — the zone axis costs an unzoned launch nothing" ||
        bad "$(op_count 'ec2 describe-subnets') describe-subnets call(s) on a launch that asked for no zone"
}

case_a_zone_refusal_tries_the_next_zone_once_then_the_market_rule() {
    CURRENT=case_a_zone_refusal_tries_the_next_zone_once_then_the_market_rule
    world_new az_ring
    world_up_ready
    world_zones_ready
    # The subnet lookup is asked twice: the typed zone, then the ring's next.
    printf 'subnet-b\n' >"$REC/ans/ec2_describe-subnets__Subnets0SubnetId.1"
    printf 'subnet-c\n' >"$REC/ans/ec2_describe-subnets__Subnets0SubnetId.2"
    # Both zones refuse for capacity. As a BANK SHARD, so the market rule
    # underneath the ring is reached and is the refusal it always was.
    printf '255\n' >"$REC/rc/ec2_run-instances.1"
    printf 'An error occurred (InsufficientInstanceCapacity) when calling the RunInstances operation\n' \
        >"$REC/err/ec2_run-instances.1"
    printf '255\n' >"$REC/rc/ec2_run-instances.2"
    printf 'An error occurred (InsufficientInstanceCapacity) when calling the RunInstances operation\n' \
        >"$REC/err/ec2_run-instances.2"
    vb DJB_VERIFIER_BANK_SHARD=1 -- up --for X --az "${RG}b"
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2 after both zones refused, got ${VB_RC}"
        report
        return
    }
    said "az ${RG}b refused (InsufficientInstanceCapacity); trying ${RG}c" &&
        ok "the first zone's refusal is printed with the code and the zone it moved to" ||
        bad "the zone refusal is not narrated: $(tr '\n' ' ' <"$W/err" | cut -c1-300)"
    local n
    n="$(op_count 'ec2 run-instances')"
    [ "$n" = "2" ] && ok "exactly two launches were attempted — the ring turns ONCE" ||
        bad "${n} run-instances call(s), wanted 2"
    local second
    second="$(nth_call_of "run-instances" 2 || true)"
    case "$second" in
    *"--subnet-id subnet-c"*) ok "the second attempt is in the NEXT zone's subnet" ;;
    *) bad "the retry did not move zone: ${second}" ;;
    esac
    case "$second" in
    *MarketType=spot*) ok "and it is still a Spot request — the ring is not an on-demand fallback" ;;
    *) bad "the retry left the Spot market: ${second}" ;;
    esac
    said "THIS IS A BANK SHARD" &&
        ok "a second refusal reaches the market rule, which for a shard is a refusal" ||
        bad "the second refusal did not reach the bank-shard rule"
    local od=0 call i=1
    while call="$(nth_call_of "run-instances" "$i" 2>/dev/null)"; do
        case "$call" in *MarketType=spot*) ;; *) od=$((od + 1)) ;; esac
        i=$((i + 1))
        [ "$i" -le 10 ] || break
    done
    [ "$od" = "0" ] && ok "and NOT ONE on-demand box was bought on the way there" ||
        bad "${od} on-demand launch(es) — the ring must never become an unasked on-demand bank"
}

case_up_records_the_spot_request_id() {
    CURRENT=case_up_records_the_spot_request_id
    world_new sir_recorded
    world_up_ready
    ans "ec2_run-instances" "$(printf 'i-up1\tsir-0abc\t%sc\tspot' "$RG")"
    vb -- up --for X
    [ "$VB_RC" = "0" ] || {
        bad "up exited ${VB_RC}"
        report
        return
    }
    local call
    call="$(nth_call_of "run-instances" 1 || true)"
    case "$call" in
    *"Instances[0].[InstanceId,SpotInstanceRequestId,"*)
        ok "the launch asks for the request id in the same call that makes the box" ;;
    *) bad "the launch's --query does not ask for SpotInstanceRequestId: ${call}" ;;
    esac
    local f="$W/vhome/i-up1/spot-request"
    if [ -r "$f" ]; then
        [ "$(cat "$f")" = "sir-0abc" ] && ok "and it is written beside the box's key" ||
            bad "the recorded request id is '$(cat "$f")', wanted sir-0abc"
    else
        bad "no ${f} was written — nothing can ask why this box was reclaimed"
    fi

    # AN ON-DEMAND BOX HAS NO SPOT REQUEST, and the file's ABSENCE is the
    # record of that. A file holding `None` would be an id nobody can look up.
    world_new sir_on_demand
    world_up_ready
    ans "ec2_run-instances" "$(printf 'i-up1\tNone\t%sc\tNone' "$RG")"
    vb -- up --for X --on-demand
    [ "$VB_RC" = "0" ] || {
        bad "an on-demand up exited ${VB_RC}"
        report
        return
    }
    [ ! -e "$W/vhome/i-up1/spot-request" ] &&
        ok "an on-demand launch writes no spot-request file at all" ||
        bad "an on-demand box was given a spot request id: '$(cat "$W/vhome/i-up1/spot-request")'"
}

# A reclaimed box, ready for `wait` to walk into. The pid file is what makes
# `wait` a real subject rather than a refusal about a missing detach.
world_reclaimed_box() {
    ans "ec2_describe-instances__Reservations0Instances0StateName" "terminated"
    ans "ec2_describe-instances__Reservations0Instances0StateReason" "Server.SpotInstanceTermination"
    mkdir -p "$W/vhome/i-gone"
    printf 'key\n' >"$W/vhome/i-gone/id_ed25519"
    printf 'a-rung\n' >"$W/vhome/i-gone/rung"
    printf '4242\n' >"$W/vhome/i-gone/loop-x.pid"
}

case_wait_on_a_reclaimed_box_prints_the_spot_status_code() {
    CURRENT=case_wait_on_a_reclaimed_box_prints_the_spot_status_code
    world_new reclaim_status
    world_reclaimed_box
    printf 'sir-0abc\n' >"$W/vhome/i-gone/spot-request"
    ans "ec2_describe-spot-instance-requests" \
        "$(printf 'instance-terminated-no-capacity\tThere is no Spot capacity available')"
    vb -- wait i-gone loop-x
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2 on a reclaimed box, got ${VB_RC}"
        report
        return
    }
    out_has "box reclaimed (spot) i-gone status instance-terminated-no-capacity" &&
        ok "the reclaim line carries the Spot service's OWN status code" ||
        bad "the reclaim line has no status code: $(grep 'box reclaimed' "$W/out" || true)"
    out_has "There is no Spot capacity available" &&
        ok "and the message beside it, so the code is readable without a second lookup" ||
        bad "the status message is not printed"
    local q
    q="$(nth_call_of "describe-spot-instance-requests" 1 || true)"
    case "$q" in
    *"sir-0abc"*) ok "it asked about the request id the launch recorded, not a search" ;;
    *) bad "the status lookup does not name the recorded request: ${q}" ;;
    esac

    # AND A BOX WITH NO RECORDED REQUEST SAYS SO rather than asking about
    # nothing. Every on-demand box and every box launched by a wrapper older
    # than the recording is in this population.
    world_new reclaim_unrecorded
    world_reclaimed_box
    vb -- wait i-gone loop-x
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2, got ${VB_RC}"
        report
        return
    }
    out_has "status unrecorded" && ok "an unrecorded request reads 'unrecorded', never a made-up code" ||
        bad "the unrecorded case does not say so: $(grep 'box reclaimed' "$W/out" || true)"
    [ "$(op_count 'ec2 describe-spot-instance-requests')" = "0" ] &&
        ok "and nothing was asked of the Spot API about a request nobody has an id for" ||
        bad "it asked about a request id it does not have"
}

case_a_status_the_policy_cannot_read_is_named_not_hidden() {
    CURRENT=case_a_status_the_policy_cannot_read_is_named_not_hidden
    world_new reclaim_denied
    world_reclaimed_box
    printf 'sir-0abc\n' >"$W/vhome/i-gone/spot-request"
    printf '\naws: [ERROR]: An error occurred (UnauthorizedOperation) when calling the DescribeSpotInstanceRequests operation\n' \
        >"$REC/err/ec2_describe-spot-instance-requests"
    printf '255\n' >"$REC/rc/ec2_describe-spot-instance-requests"
    vb -- wait i-gone loop-x
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2, got ${VB_RC}"
        report
        return
    }
    out_has "status unreadable" &&
        ok "a refused status reads 'unreadable' — never a silent reclaim with no code" ||
        bad "a refused status lookup left the line bare: $(grep 'box reclaimed' "$W/out" || true)"
    out_has "ec2:DescribeSpotInstanceRequests not in the ops policy" &&
        ok "and it names the grant that is missing, which is the whole remedy" ||
        bad "the unreadable line does not name the missing IAM action"
    out_has "box reclaimed (spot) i-gone" &&
        ok "the reclaim itself is still reported — the status is an addition, never a replacement" ||
        bad "a failed status read swallowed the reclaim sentence"
}

case_down_on_a_reclaimed_box_says_already_gone_and_is_not_a_refusal() {
    CURRENT=case_down_on_a_reclaimed_box_says_already_gone_and_is_not_a_refusal
    world_new down_already_gone
    mkdir -p "$W/vhome/i-gone"
    printf 'key\n' >"$W/vhome/i-gone/id_ed25519"
    ans "ec2_describe-instances__Reservations0Instances0StateNameStateRea" \
        "$(printf 'terminated\tServer.SpotInstanceTermination\tverifier\t%s' "$NS")"
    vb -- down i-gone
    [ "$VB_RC" = "0" ] || {
        bad "wanted exit 0 on a box AWS has already taken, got ${VB_RC}"
        report
        return
    }
    out_has "already gone i-gone" && ok "exit 0 and it says the box was already gone" ||
        bad "the line does not say 'already gone': $(head -n 1 "$W/out")"
    out_has "Server.SpotInstanceTermination" &&
        ok "and it names WHY it went, out of the same describe" ||
        bad "the already-gone line carries no StateReason"
    said "is not a verifier box" &&
        bad "a reclaimed box was called foreign — the sentence this criterion exists to kill" ||
        ok "it is never called somebody else's box"
    [ "$(op_count 'ec2 terminate-instances')" = "0" ] &&
        ok "nothing was terminated — there is nothing there to terminate" ||
        bad "it called terminate-instances on an instance that is already terminated"
    [ "$(op_count 'ec2 describe-instances')" = "1" ] &&
        ok "and it asked ONE describe for the state and both tags" ||
        bad "$(op_count 'ec2 describe-instances') describes, wanted 1 — the state and the tags are one question"
    [ ! -d "$W/vhome/i-gone" ] && ok "the private key went with it" ||
        bad "the box directory survived a box that does not"
}

case_down_that_cannot_look_says_so_and_never_calls_it_foreign() {
    CURRENT=case_down_that_cannot_look_says_so_and_never_calls_it_foreign
    world_new down_cannot_look
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
    # THE LEADING BLANK LINE IS THE MEASURED SHAPE, not decoration: the AWS
    # CLI v2 opens an error with one (measured against the real API on
    # 2026-09-21), and a refusal that took `${out%%<newline>*}` printed
    # `could not look at i-…: ` with the API's sentence dropped.
    printf '\naws: [ERROR]: An error occurred (RequestLimitExceeded) when calling the DescribeInstances operation\n' \
        >"$REC/ans/ec2_describe-instances__Reservations0Instances0StateNameStateRea"
    printf '255\n' >"$REC/rc/ec2_describe-instances__Reservations0Instances0StateNameStateRea"
    vb -- down i-up1
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2 when the describe was refused, got ${VB_RC}"
        report
        return
    }
    said "could not look at i-up1" && ok "exit 2 and it says it could not look" ||
        bad "the refusal does not say 'could not look': $(tr '\n' ' ' <"$W/err" | cut -c1-200)"
    grep -F -- "could not look at i-up1: aws: [ERROR]: An error occurred (RequestLimitExceeded)" "$W/err" >/dev/null 2>&1 &&
        ok "and the API's own line is ON the colon — past the CLI's leading blank line, which had been swallowing it whole" ||
        bad "the refusal's colon carries nothing: $(grep 'could not look' "$W/err" || true)"
    said "is not a verifier box" &&
        bad "a blind call was reported as somebody else's box" ||
        ok "it never claims the box is not ours — that is a fact it could not read"
    [ "$(op_count 'ec2 terminate-instances')" = "0" ] &&
        ok "and NOTHING was terminated" ||
        bad "it terminated something it could not identify"
    [ -d "$W/vhome/i-up1" ] && ok "the key is still here, because the box may still be up" ||
        bad "the only way back into a box that may still be running was deleted"
}

case_a_probe_that_is_not_yet_connected_is_retried_within_the_ceiling() {
    CURRENT=case_a_probe_that_is_not_yet_connected_is_retried_within_the_ceiling
    world_new probe_not_yet_connected
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
    # The first probe meets the session channel before it is up: ssh's own 255
    # with the plugin's word on stderr. The second one lands.
    printf '255\n' >"$REC/ssh/1.rc"
    printf 'An error occurred (TargetNotConnected) when calling the StartSession operation\n' \
        >"$REC/ssh/1.err"
    vb DRIVE_SSH_SECONDS=1 -- push i-up1
    if [ "$VB_RC" != "0" ]; then
        bad "a probe that was merely early refused the whole push (exit ${VB_RC})"
        report
        return
    fi
    ok "the push goes: an early TargetNotConnected is a wait, not a refusal"
    said "not yet connected; waited 5s" &&
        ok "and the wait is printed with what it has spent" ||
        bad "the retry is silent: $(tr '\n' ' ' <"$W/err" | cut -c1-300)"
    said "DJB_VERIFIER_TUNNEL_WAIT_SECONDS" && ok "the line names the ceiling's own knob" ||
        bad "the wait line does not name the knob that bounds it"

    # THE CEILING HOLDS. A transport that never connects is the refusal it
    # always was, and the wait is bounded by a number somebody can read.
    world_new probe_never_connects
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
    printf '255\n' >"$REC/ssh/default.rc"
    printf 'An error occurred (TargetNotConnected) when calling the StartSession operation\n' \
        >"$REC/ssh/default.err"
    vb DRIVE_SSH_SECONDS=1 DJB_VERIFIER_TUNNEL_WAIT_SECONDS=10 -- push i-up1
    [ "$VB_RC" = "2" ] || {
        bad "a tunnel that never connects should be exit 2, got ${VB_RC}"
        report
        return
    }
    ok "past the ceiling it is the refusal it always was"
    said "waited on for 10s and never connected" &&
        ok "and the refusal says how long it waited" ||
        bad "the refusal does not state the wait it spent"
    local n
    n="$(cat "$REC/seq/_ssh" 2>/dev/null || echo 0)"
    [ "$n" = "3" ] && ok "a 10s ceiling at a 5s poll is three attempts — bounded, and the bound is arithmetic" ||
        bad "${n} ssh attempt(s) under a 10s ceiling, wanted 3"

    # AND A 255 THAT IS NOT THIS IS NOT RETRIED. A dead transport says so on
    # the first attempt and a minute spent re-proving it is a minute lost.
    world_new probe_dead_transport
    ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
    mkdir -p "$W/vhome/i-up1"
    printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
    printf '255\n' >"$REC/ssh/default.rc"
    printf 'ssh: connect to host i-up1 port 22: Connection refused\n' >"$REC/ssh/default.err"
    vb DRIVE_SSH_SECONDS=1 -- push i-up1
    [ "$VB_RC" = "2" ] || {
        bad "a dead transport should be exit 2, got ${VB_RC}"
        report
        return
    }
    n="$(cat "$REC/seq/_ssh" 2>/dev/null || echo 0)"
    [ "$n" = "1" ] && ok "a 255 that is not TargetNotConnected is refused on the first attempt" ||
        bad "${n} attempt(s) on a dead transport — only the not-yet-connected word is retried"
}

case_up_names_the_box_before_anything_can_fail_after_the_launch() {
    CURRENT=case_up_names_the_box_before_anything_can_fail_after_the_launch
    world_new launched_line
    world_up_ready
    # The probe's floor, raised past anything a fixture can reach: `up` gets
    # as far as the push and the push refuses. Everything after the launch is
    # in that failure's shadow, which is exactly the population this line is
    # for.
    vb DJB_VERIFIER_MIN_KBPS=999999999 -- up --for X
    [ "$VB_RC" = "2" ] || {
        bad "wanted exit 2 from a push under an impossible floor, got ${VB_RC}"
        report
        return
    }
    local line
    line="$(grep -m1 '^launched   ' "$W/out" || true)"
    case "$line" in
    "launched   i-up1   az ${RG}c") ok "the box is named with its zone BEFORE the push, and the failure leaves the line" ;;
    *) bad "no parsable 'launched <id> az <az>' line survived the refusal: '${line}'" ;;
    esac
    # AND IT IS THE SEAM'S GRAMMAR. `pm_push.sh` reads this line to record a
    # box before it reads `up`'s status; a reader that has to guess at the
    # column order is a reader that records the wrong id.
    local id az
    id="$(awk '$1 == "launched" { print $2 }' "$W/out")"
    az="$(awk '$1 == "launched" && $3 == "az" { print $4 }' "$W/out")"
    [ "$id" = "i-up1" ] && ok "field 2 is the instance id" || bad "field 2 is '${id}'"
    [ "$az" = "${RG}c" ] && ok "field 3 is the literal 'az' and field 4 is the zone" ||
        bad "field 4 is '${az}'"
    said "KB/s" && ok "and the refusal that followed it is still the probe's own" ||
        bad "the refusal is not the probe's"
}

case_census_prints_each_boxs_zone() {
    CURRENT=case_census_prints_each_boxs_zone
    world_new census_az
    local future
    future="$(python3 -c 'import datetime;print((datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ"))')"
    printf 'i-one\tc7g.4xlarge\tverifier\t%s\t%s\t2026-09-15T10:00:00.000Z\tami-baked-7\tspot\t%sa\ni-two\tc7g.4xlarge\tverifier\t%s\t%s\t2026-09-15T10:00:00.000Z\tami-baked-7\tspot\t%sc\n' \
        "$OWNER" "$future" "$RG" "$OWNER" "$future" "$RG" \
        >"$REC/ans/ec2_describe-instances__ReservationsInstancesInstanceIdInstance"
    vb -- census
    [ "$VB_RC" = "0" ] || {
        bad "census exited ${VB_RC}"
        report
        return
    }
    grep -E "^i-one .* az ${RG}a " "$W/out" >/dev/null 2>&1 &&
        ok "the first box's line carries its zone" ||
        bad "no zone on i-one's line: $(grep '^i-one' "$W/out" || true)"
    grep -E "^i-two .* az ${RG}c " "$W/out" >/dev/null 2>&1 &&
        ok "and the second's is a DIFFERENT zone — which is the whole thing a spread is judged by" ||
        bad "no zone on i-two's line: $(grep '^i-two' "$W/out" || true)"
    local q
    q="$(nth_call_of "describe-instances" 1 || true)"
    case "$q" in
    *"Placement.AvailabilityZone"*) ok "read out of the query, never from a tag this wrapper wrote" ;;
    *) bad "the census query does not read Placement.AvailabilityZone: ${q}" ;;
    esac

    # A ROW FROM AN OLDER WRAPPER HAS NO NINTH COLUMN, and it must read as
    # `unknown` rather than shifting every field one to the left.
    world_new census_az_absent
    printf 'i-old\tc7g.4xlarge\tverifier\t%s\t%s\t2026-09-15T10:00:00.000Z\tami-baked-7\tspot\n' \
        "$OWNER" "$future" \
        >"$REC/ans/ec2_describe-instances__ReservationsInstancesInstanceIdInstance"
    vb -- census
    [ "$VB_RC" = "0" ] || {
        bad "census over a short row exited ${VB_RC}"
        report
        return
    }
    out_has "az unknown" && ok "a row with no zone reads 'az unknown'" ||
        bad "a short row did not degrade to 'az unknown': $(grep '^i-old' "$W/out" || true)"
}

case_zones_lists_the_vpcs_zones_and_refuses_when_it_cannot_look() {
    CURRENT=case_zones_lists_the_vpcs_zones_and_refuses_when_it_cannot_look
    world_new zones_ok
    ans "ec2_describe-security-groups__SecurityGroups0VpcId" "vpc-v"
    # Unsorted and with a duplicate, because two subnets in one zone is the
    # ordinary shape of a real VPC and "the next zone" has to be well defined.
    ans "ec2_describe-subnets__SubnetsAvailabilityZone" \
        "$(printf '%sc\t%sa\t%sc\t%sb' "$RG" "$RG" "$RG" "$RG")"
    vb -- zones
    [ "$VB_RC" = "0" ] || {
        bad "zones exited ${VB_RC}"
        report
        return
    }
    local got want
    got="$(tr '\n' ' ' <"$W/out")"
    want="${RG}a ${RG}b ${RG}c "
    [ "$got" = "$want" ] && ok "one zone per line, sorted, de-duplicated" ||
        bad "zones printed '${got}', wanted '${want}'"
    [ "$(op_count 'ec2 run-instances')" = "0" ] && [ "$(op_count 'ec2 terminate-instances')" = "0" ] &&
        ok "and it is a read: nothing was launched and nothing was terminated" ||
        bad "zones is not read-only"
    local sub
    sub="$(nth_call_of "describe-subnets" 1 || true)"
    case "$sub" in
    *"Name=vpc-id,Values=vpc-v"*) ok "the zones are the SECURITY GROUP's VPC's, not the region's" ;;
    *) bad "the zone listing does not filter on the group's VpcId: ${sub}" ;;
    esac

    # AN EMPTY ANSWER IS NOT ZERO ZONES. A bank that read silence as "one
    # zone, then" would put every shard in the same place and call it a plan.
    world_new zones_empty
    ans "ec2_describe-security-groups__SecurityGroups0VpcId" "vpc-v"
    ans "ec2_describe-subnets__SubnetsAvailabilityZone" ""
    vb -- zones
    [ "$VB_RC" = "2" ] && ok "no subnets at all is exit 2, never an empty list" ||
        bad "an empty answer exited ${VB_RC}"
    said "could not look" && ok "and it says it could not look" ||
        bad "the empty refusal does not say 'could not look'"

    world_new zones_no_group
    ans "ec2_describe-security-groups__SecurityGroups0VpcId" "None"
    vb -- zones
    [ "$VB_RC" = "2" ] && ok "a group whose VPC cannot be read is exit 2 as well" ||
        bad "an unreadable group exited ${VB_RC}"
    said "${NS}-verifier" && ok "naming the group it could not resolve" ||
        bad "the refusal does not name the security group"
}

case_a_describe_that_has_not_caught_up_cannot_lie_about_the_market() {
    CURRENT=case_a_describe_that_has_not_caught_up_cannot_lie_about_the_market
    world_new launch_eventual_consistency
    world_up_ready
    world_zones_ready
    ans "ec2_describe-subnets__Subnets0SubnetId" "subnet-c"
    # EVERY `describe-instances` IN THE ACCOUNT HAS NOT CAUGHT UP. An instance
    # id is seconds old at this point and EC2's describe is eventually
    # consistent over it: `InvalidInstanceID.NotFound` about a box that is
    # running is a real answer, and the placement read swallowed its own error
    # — so the transient arrived as silence, the zone degraded to `unknown`
    # (honest) and `market_of_lifecycle ""` returned `on-demand`. A Spot box
    # labelled at five times its price, in the one record that outlives it.
    printf '\naws: [ERROR]: An error occurred (InvalidInstanceID.NotFound) when calling the DescribeInstances operation: The instance ID '"'"'i-up1'"'"' does not exist\n' \
        >"$REC/ans/ec2_describe-instances__Reservations0Instances0InstanceLifecycle"
    printf '255\n' >"$REC/rc/ec2_describe-instances__Reservations0Instances0InstanceLifecycle"
    vb -- up --for X --az "${RG}c"
    if [ "$VB_RC" != "0" ]; then
        bad "up exited ${VB_RC} with a describe that had not caught up"
        report
        return
    fi
    ok "the launch path does not depend on a describe catching up"
    local line
    line="$(grep -m1 '^launched   ' "$W/out" || true)"
    case "$line" in
    "launched   i-up1   az ${RG}c") ok "the zone is the LAUNCH's own answer: ${line}" ;;
    *) bad "the launched line lost its zone to the transient: '${line}'" ;;
    esac
    out_has "market     spot" &&
        ok "and the market is still spot — the transient cannot relabel a Spot box as on-demand" ||
        bad "the market line reads '$(grep -m1 '^market ' "$W/out" || true)' over a Spot launch"

    # AND THE PLACEMENT IS NEVER RE-ASKED ON THE LAUNCH PATH. A describe that
    # only sometimes answers is a describe whose absence must not be reachable
    # at all here, not one whose failure is handled politely.
    local q i=1 asked=""
    while q="$(nth_call_of "describe-instances" "$i" || true)"; do
        [ -n "$q" ] || break
        case "$q" in *"Reservations[0].Instances[0].[InstanceLifecycle"*) asked=1 ;; esac
        i=$((i + 1))
    done
    [ -z "$asked" ] &&
        ok "no describe asks for the placement after a launch — the launch already answered" ||
        bad "the launch path still re-describes the instance it has just been told about"
}

case_a_warm_claim_says_the_zone_you_typed_applied_to_nothing() {
    CURRENT=case_a_warm_claim_says_the_zone_you_typed_applied_to_nothing
    world_new claim_ignores_az
    world_up_ready
    world_zones_ready
    ans "ec2_describe-subnets__Subnets0SubnetId" "subnet-c"
    pool_listing "$(pool_row i-warm1 12 ami-v1 0.19)"
    mkdir -p "$W/vhome/i-warm1"
    printf 'key\n' >"$W/vhome/i-warm1/id_ed25519"
    vb -- up --for X --az "${RG}c"
    if [ "$VB_RC" != "0" ]; then
        bad "a claim with --az exited ${VB_RC}"
        report
        return
    fi
    [ "$(op_count 'ec2 run-instances')" = "0" ] && ok "the warm box was claimed — nothing was launched" ||
        bad "a warm box was available and a box was launched anyway"
    said "--az ${RG}c you typed applied to nothing" &&
        ok "and the claim SAYS the zone applied to nothing — the shape --ttl/--idle already use" ||
        bad "a claim silently ignored --az: $(tr '\n' ' ' <"$W/err" | cut -c1-300)"
    said "CLAIMED warm" && ok "naming the claim as the reason" ||
        bad "the note does not say the box was claimed warm"
    [ "$(op_count 'ec2 describe-subnets')" = "0" ] &&
        ok "and no subnet was resolved for a zone nothing was going to be launched into" ||
        bad "$(op_count 'ec2 describe-subnets') describe-subnets call(s) on a path that launches nothing"
}

# =============================================================================
# 1.9b — the grant the status read needs, and the territory that did not move
# =============================================================================

case_the_ops_policy_grants_the_spot_request_read() {
    CURRENT=case_the_ops_policy_grants_the_spot_request_read
    # THE DOCUMENT IN THE TREE, NOT THE LIVE POLICY. An IAM policy that already
    # exists keeps the version it was created with, so this file and the
    # account can disagree for as long as it takes a hand to publish a new
    # default version — `deploy/iam/verifier_bootstrap.sh` is what prints the
    # `create-policy-version` command and the OWNER is what runs it. What this
    # drive owes is that the document a bootstrap would publish carries the
    # grant; the live half is the owner's and is reported, never asserted here.
    local pol=deploy/iam/verifier-ops-policy.json
    [ -r "$pol" ] || {
        bad "${pol} is not in this tree"
        return
    }
    python3 -c 'import json,sys
d=json.load(open(sys.argv[1]))
for s in d["Statement"]:
    a=s.get("Action")
    a=[a] if isinstance(a,str) else a
    if "ec2:DescribeSpotInstanceRequests" in a:
        print(s["Sid"]); sys.exit(0)
sys.exit(1)' "$pol" >"$WORK/pol.sid" 2>/dev/null &&
        ok "the ops policy document grants ec2:DescribeSpotInstanceRequests (Sid $(cat "$WORK/pol.sid"))" ||
        bad "the ops policy does not grant ec2:DescribeSpotInstanceRequests — every reclaim's status reads 'unreadable'"
    # AND THE WRAPPER'S UNREADABLE SENTENCE NAMES THAT EXACT ACTION, so the
    # refusal and the remedy cannot drift apart.
    grep -F -- "ec2:DescribeSpotInstanceRequests not in the ops policy" "$VB" >/dev/null 2>&1 &&
        ok "and the wrapper's 'unreadable' sentence names the same action" ||
        bad "the wrapper's unreadable sentence does not name the grant the policy carries"
}

case_the_territory_this_change_does_not_own_did_not_move() {
    CURRENT=case_the_territory_this_change_does_not_own_did_not_move
    # BY BLOB, not by `git diff --quiet HEAD`: a file edited and
    # COMMITTED is exactly the case this claim exists to catch, and the
    # working-tree comparison calls that clean.
    #
    # THE POPULATION IS THE BANK'S SIDE AND THE GATE'S. The zone axis lives
    # entirely in this wrapper; `pm_push.sh` reads its printed seams and
    # `check.sh` and the house rules read nothing of it at all, so a hunk in
    # any of them is a merge conflict invented out of nothing and, for the
    # first, a measurement taken from under whoever is building the bank half.
    # `cmd_up` is in the list because the launch path is B-R1's and a ceiling
    # rung promised not to touch it: the ceiling is read in `require_headroom`,
    # which `cmd_up` CALLS and does not contain, so `cmd_up`'s own body is the
    # thing that must not have moved.
    #
    # `cmd_pool` WAS in this list and IS NOT ANY MORE (owner's call, 2026-09-21).
    # The ceiling stopped being one variable: it is env, then a file, then the
    # default, and `pool --want N` refusing with "above DJB_VERIFIER_MAX_BOXES
    # (8)" about an 8 that came out of the FILE is a refusal that names the
    # wrong source. Printing the three sources there is therefore part of the
    # ceiling, not a neighbour's line — so the pool's refusal moved into the
    # rung's OWNED set, deliberately, and the claim about it was retired rather
    # than quietly satisfied.
    # AND THE OTHER SIDE IS THE FORK POINT, NOT `main`'s TIP. `main` moves under
    # a rung all day — fifteen worktrees merge into it while one builds — so a
    # branch that touched none of these files reds this claim the moment
    # somebody else's rung lands one of them, and reds it AGAIN in the
    # VERIFIER's clone, which is the union of the branch and a main that has
    # moved since the fold. The honest question is "did THIS branch change
    # it", and `merge-base` is where that question is asked.
    #
    # AND A CARRIED FORK POINT IS ASKED BEFORE `main` IS. `merge-base main HEAD`
    # is only the fork point where `main` is the tip this branch forked from. On
    # a pull-request runner `main` lags the last merged train, so "this branch"
    # became the union of several trains INCLUDING the fold that legitimately
    # moved these files (a consumer's train PR: 568 passed, 2 failed); on a box
    # `main` IS HEAD and the case measured nothing. So: a declared
    # `refs/djb/base` (verify_start.sh writes it into every verify clone; the
    # box push carries it), then `DJB_LOOP_SCOPE_BASE` (what the box's gate is
    # handed), then `merge-base main HEAD`. Each is honoured only when it names
    # a commit behind HEAD.
    local base="" base_from="" cand f dirty="" a b owned
    cand="$(git rev-parse -q --verify 'refs/djb/base^{commit}' 2>/dev/null || true)"
    if [ -n "$cand" ] && git merge-base --is-ancestor "$cand" HEAD 2>/dev/null; then
        base="$cand"
        base_from="refs/djb/base"
    fi
    if [ -z "$base" ] && [ -n "${DJB_LOOP_SCOPE_BASE:-}" ]; then
        cand="$(git rev-parse -q --verify "${DJB_LOOP_SCOPE_BASE}^{commit}" 2>/dev/null || true)"
        if [ -n "$cand" ] && git merge-base --is-ancestor "$cand" HEAD 2>/dev/null; then
            base="$cand"
            base_from="DJB_LOOP_SCOPE_BASE"
        fi
    fi
    if [ -z "$base" ]; then
        base="$(git merge-base main HEAD 2>/dev/null || true)"
        base_from="merge-base main HEAD"
    fi
    [ -n "$base" ] || {
        bad "no merge base between main and HEAD — this claim has no other side"
        return
    }
    # THE CLAIM IS FALSIFIABLE ONLY FOR A CHANGE THAT OWNS THIS TERRITORY. "The
    # files this change does not own did not move" is a promise a verifier-box
    # change makes; for any other change there is nothing it promised, and
    # asserting it anyway reds every fold train for a file it was entitled to
    # move. The owner is read off the diff from the fork point to the working
    # tree (committed and uncommitted): the wrapper or this drive.
    owned="$(git diff --name-only "$base" -- "$VB" scripts/tests/test_verifier_box.sh 2>/dev/null || true)"
    if [ -z "$owned" ]; then
        skip "not a verifier-box change — the claim has no owner here (base ${base:0:8} from ${base_from}; the diff names neither ${VB} nor its drive)"
        return
    fi
    for f in scripts/pm_push.sh scripts/check.sh quality/rules.yaml; do
        a="$(git rev-parse "${base}:${f}" 2>/dev/null || true)"
        b="$(git rev-parse "HEAD:${f}" 2>/dev/null || true)"
        if [ -z "$a" ] || [ -z "$b" ]; then
            bad "could not read ${f} out of both ${base:0:8} and HEAD — this claim needs both"
            return
        fi
        [ "$a" = "$b" ] || dirty="${dirty}
      ${f}  fork point (${base_from}) ${a:0:8} vs HEAD ${b:0:8}"
        git diff --quiet HEAD -- "$f" 2>/dev/null || dirty="${dirty}
      ${f}  uncommitted in the working tree"
    done
    [ -z "$dirty" ] && ok "pm_push.sh, check.sh and rules.yaml are byte-identical to the fork point's" ||
        bad "files this change does not own have moved:${dirty}"

    # THE MATCH IS LITERAL, AND THE ESCAPES ARE WHY. This extraction was
    # `awk -v f="^${fn}\\(\\) \\{" '$0 ~ f …'`, and it matched NOTHING: the
    # shell hands awk the string `^cmd_pool\(\) \{`, awk then parses THAT
    # string's own escapes before it is ever a regex, and the result does not
    # match the line it was written for. Both sides extracted zero bytes, both
    # cksummed to `4294967295 0`, they were equal, and the case printed `ok`
    # — a guard over the one function it exists to guard, green for a body
    # that HAD moved (measured 2026-09-21: drive form `4294967295 0` both sides;
    # a working match, `1360171546 4104` vs `3412959428 4398`). `index($0, …)`
    # has no regex layer and therefore no escape layer to get wrong.
    #
    # AND AN EMPTY EXTRACTION IS NOW COULD-NOT-LOOK, WHICH IS EXIT 2. The old
    # guard compared against `" 0 0"`, which is not what cksum prints for empty
    # input on either platform — so the one thing that would have caught the
    # bug above was itself unable to fire. A claim with no bytes on either side
    # is not a passing claim and not a failing one; it is a drive that did not
    # look, and this file's other could-not-looks all exit 2.
    # AND IT READS ITS PRODUCER TO EOF. The awk above ended `on && /^}$/
    # {exit}`, which is the very shape `case_no_early_exit_reader_follows_a_
    # pipe_in_this_wrapper` forbids in the subject — and this drive is under
    # the same `set -o pipefail`. It was harmless only because the broken
    # regex never matched, so awk always ran to EOF; the moment the match was
    # repaired, awk left at `cmd_up`'s closing brace, `git show` took SIGPIPE
    # on a 4,300-line file, and THE WHOLE DRIVE DIED AT EXIT 141 before its
    # tally — measured, 2026-09-21. `done` stops the printing without stopping
    # the reading: read the whole, then slice.
    local fn before after
    local extract='index($0, f "() {") == 1 { on = 1 }
                   on && !done { print; if ($0 == "}") done = 1 }'
    for fn in cmd_up; do
        before="$(git show "${base}:${VB}" 2>/dev/null | awk -v f="$fn" "$extract" | cksum)"
        after="$(awk -v f="$fn" "$extract" "$VB" | cksum)"
        case "${before}|${after}" in
        *"4294967295 0"* | *" 0 0"*)
            cannot_look "extracted nothing for ${fn} out of ${base:0:8}'s ${VB} or HEAD's
   (before '${before}', after '${after}'). Two empty extractions COMPARE EQUAL,
   which is how this claim was green over a body that had moved. A claim with
   no bytes on either side did not look."
            ;;
        esac
        [ "$before" = "$after" ] && ok "${fn}'s own body is byte-identical to the fork point's" ||
            bad "${fn} moved: ${base:0:8} ${before} vs HEAD ${after}"
    done
}

# =============================================================================
# 1.9c — the detach that did not detach
# =============================================================================
#
# FOUR BUILDERS REPORTED `loop` AND `leg` AS A HANG and it did not reproduce
# on the two runs anyone looked at, so it was carried as a suspicion about the
# transport. It is not the transport. `A && B && C && setsid … >/dev/null 2>&1
# & echo $!` reads as if the redirects covered the background job; `&` binds to
# the WHOLE `&&` list, bash runs that list in a subshell, and the redirects are
# on `setsid` alone — so the subshell holds the ssh channel's stdout for as
# long as the gate runs and the command substitution that wanted one line of
# pid waits for the whole gate.
#
# MEASURED ON A REAL BOX (2026-09-21): the shipped `loop` returned after 400 s
# over a 386 s gate and printed `gate detached … as pid` at the END of it.
#
# AND THIS CASE EXECUTES THE SHAPE RATHER THAN SPELLING IT. A census for `{`
# and `}` would be a claim about punctuation; what the wrapper owes is that a
# caller reading the detach's stdout gets its line back while the payload is
# still running. So the RECORDED remote command — the real one, out of the
# real `loop`'s and `leg`'s own ssh argv — has its payload swapped for a sleep
# and its paths pointed at scratch, and is then run under a command
# substitution, which waits for EOF on a pipe exactly as ssh waits for the
# channel. Real wall clock, not the world's fake one: the case body runs
# outside `vb`'s environment and `date` here is the machine's.

# detach_payload_swapped <recorded argv> <scratch dir> <seconds>
# The remote command out of a recorded ssh argv, with the gate's payload
# replaced by a sleep and every path pointed somewhere this machine has. The
# swap is textual and narrow on purpose: everything about the SHAPE — the
# grouping, where the redirects sit, what the `&` binds to — is the wrapper's
# own bytes, which is the whole point of reading it back rather than retyping
# it.
detach_payload_swapped() {
    python3 - "$1" "$2" "$3" <<'PY'
import re, sys
argv, scratch, secs = sys.argv[1], sys.argv[2], sys.argv[3]
# The recorded flat argv is the whole command line; the remote command is
# everything after the `--` the wrapper passes to ssh.
i = argv.find(' -- ')
cmd = argv[i + 4:] if i >= 0 else argv
# The activity-marker touch the transport prepends is the box's, not the shape's.
cmd = cmd.replace("touch /run/verifier/last-activity 2>/dev/null || true; ", "", 1)
# The gate itself becomes a sleep. The payload carries no single quote, so the
# first `sh -c '` and the next `'` bracket it exactly.
a = cmd.index("sh -c '")
b = cmd.index("'", a + 7)
cmd = cmd[:a] + "sh -c 'sleep %s'" % secs + cmd[b + 1:]
# And the paths this machine does not have. `~/verify/<rung>` is replaced as a
# PREFIX — the pattern stops at the next `/`, because `\S+` swallowed the `;`
# after `ledger.in` and handed bash an unterminated `if`, which fails to parse,
# returns instantly and makes this whole case green over nothing. Measured: it
# passed against the very shape it exists to refuse.
cmd = re.sub(r'&& cd \S+ &&', '&& cd %s &&' % scratch, cmd)
cmd = re.sub(r'~/verify/[^/\s;]+', scratch, cmd)
sys.stdout.write(cmd)
PY
}

case_the_detach_returns_while_the_gate_is_still_running() {
    CURRENT=case_the_detach_returns_while_the_gate_is_still_running
    local sub rec n cmd scratch t0 t1 took out
    command -v python3 >/dev/null 2>&1 || cannot_look "no python3 — the recorded command cannot be re-pointed at scratch"
    for sub in loop leg; do
        world_new "detach_${sub}"
        ans "ec2_describe-instances__Reservations0Instances0StateName" "running"
        mkdir -p "$W/vhome/i-up1"
        printf 'key\n' >"$W/vhome/i-up1/id_ed25519"
        printf 'a-rung\n' >"$W/vhome/i-up1/rung"
        printf '4242\n' >"$REC/ssh/default.out"
        if [ "$sub" = "loop" ]; then
            vb -- loop i-up1 --log v1
        else
            vb -- leg i-up1 --unit ruff --log v1
        fi
        if [ "$VB_RC" != "0" ]; then
            bad "${sub} exited ${VB_RC}"
            report
            continue
        fi
        # The LAST ssh of the run is the detach; the two before it are the
        # tree pre-flight. Read the ordinal the shim counted rather than a
        # number typed here, which is what went stale the last time a session
        # was added in front of this one.
        n="$(cat "$REC/seq/_ssh" 2>/dev/null || echo 0)"
        rec="$(cat "$REC/ssh/${n}.flat" 2>/dev/null || true)"
        [ -n "$rec" ] || {
            bad "${sub}: no ssh argv was recorded at all"
            continue
        }
        scratch="${WORK}/detach-${sub}"
        rm -rf "$scratch"
        mkdir -p "$scratch/bin"
        # `setsid` IS LINUX'S AND THIS DRIVE ALSO RUNS ON A LAPTOP. A shim that
        # simply becomes its arguments keeps the recorded command VERBATIM —
        # the grouping, the redirects and what the `&` binds to are the bytes
        # under test and must not be edited to make the case runnable. Without
        # it the command dies at `command not found`, returns instantly, and
        # the case passes while proving nothing: measured, on this laptop,
        # against the very shape it exists to refuse.
        printf '#!/bin/sh\nexec "$@"\n' >"$scratch/bin/setsid"
        chmod +x "$scratch/bin/setsid"
        cmd="$(detach_payload_swapped "$rec" "$scratch" 8 || true)"
        case "$cmd" in
        *"sleep 8"*) ;;
        *)
            bad "${sub}: could not swap the payload out of the recorded command"
            continue
            ;;
        esac
        # THE COMMAND SUBSTITUTION IS THE INSTRUMENT. It waits for EOF on a
        # pipe; ssh waits for the channel to close. Same wait, same cause.
        t0="$(date +%s)"
        out="$(PATH="${scratch}/bin:$PATH" bash -c "$cmd" 2>/dev/null || true)"
        t1="$(date +%s)"
        took=$((t1 - t0))
        if [ "$took" -lt 4 ]; then
            ok "${sub}: the detach returns in ${took}s while an 8s payload is still running"
        else
            bad "${sub}: the detach held its caller for ${took}s of an 8s payload — the \`&\` binds to the whole \`&&\` list and its subshell keeps the channel open; group the list and put the redirects on the GROUP"
        fi
        local pid
        pid="$(printf '%s' "$out" | tr -d '[:space:]')"
        case "$pid" in
        '' | *[!0-9]*) bad "${sub}: the detach printed '${out}' instead of a pid" ;;
        *) ok "${sub}: and what it printed is a pid" ;;
        esac
        rm -rf "$scratch"
    done
}

case_a_piped_stdout_is_refused() {
    CURRENT=case_a_piped_stdout_is_refused
    world_new piped
    local rc=0
    set +e
    env -i PATH="$W/bin:/usr/bin:/bin" HOME="$W/home" REC="$REC" USER=driveuser \
        DJB_DEPLOY_NAMESPACE="$NS" DJB_VERIFIER_REGION="$RG" DJB_VERIFIER_HOME="$W/vhome" \
        "$VB_COUNTED" census 2>&1 | cat >"$W/out"
    rc="${PIPESTATUS[0]}"
    set -e
    [ "$rc" = "2" ] && ok "a piped stdout is exit 2 — the exit status is the verdict" ||
        bad "wanted exit 2 on a pipe, got ${rc}"
}

case_an_unknown_subcommand_or_flag_is_exit_2() {
    CURRENT=case_an_unknown_subcommand_or_flag_is_exit_2
    world_new unknown
    vb -- nonsense
    [ "$VB_RC" = "2" ] && ok "an unknown subcommand is exit 2" ||
        bad "an unknown subcommand exited ${VB_RC}"
    world_new unknown_flag
    world_up_ready
    vb -- up --for X --nonsense
    [ "$VB_RC" = "2" ] && ok "an unknown flag is exit 2, never a silently different run" ||
        bad "an unknown flag exited ${VB_RC}"
    [ ! -f "$REC/aws.ops" ] && ok "and nothing was asked of AWS" ||
        bad "an unknown flag still reached AWS"

    # EVERY SUBCOMMAND THE DISPATCHER ACCEPTS IS IN THE SYNOPSIS, and this is
    # the census that stops the help going quietly stale. `usage` used to be a
    # LINE RANGE over the header, and it had already dropped `bake`: the list
    # grew, the range did not, and the wrapper's own `--help` stopped naming a
    # subcommand it still ran. The two populations are read out of the file
    # itself so neither can be a hand list.
    local arms synopsis sub missing=""
    arms="$(awk '/^SUB="\$\{1:-\}"/ { on = 1 }
                 on && /^[a-z]+\) cmd_/ { sub(/\).*/, ""); print }' "$VB")"
    synopsis="$(awk '/^#   verifier_box\.sh /{ print $3 }' "$VB")"
    [ -n "$arms" ] || bad "no dispatcher arms read out of ${VB} — this census has lost its subject"
    for sub in $arms; do
        case " $(printf '%s ' $synopsis) " in
        *" ${sub} "*) ;;
        *) missing="${missing} ${sub}" ;;
        esac
    done
    [ -z "$missing" ] &&
        ok "every dispatched subcommand ($(printf '%s ' $arms)) is named in the synopsis --help prints" ||
        bad "the dispatcher accepts subcommand(s) --help never names:${missing}"
}

case_no_product_name_account_or_region_is_hard_coded() {
    CURRENT=case_no_product_name_account_or_region_is_hard_coded
    # The namespace census, extended over the wrapper and its drive. The
    # slug is ASSEMBLED rather than spelled: a guard that writes out the string
    # it forbids is a phantom hit for the next census that reads this directory.
    local slug="pile" tail="cap" hits f
    local scope="scripts/verifier_box.sh scripts/tests/test_verifier_box.sh deploy/verifier deploy/iam"
    # shellcheck disable=SC2086  # the paths have no spaces by construction
    hits="$(grep -rInE "${slug}${tail}[-/]" $scope || true)"
    [ -z "$hits" ] && ok "no deployment slug in the wrapper, its drive, or the image side" ||
        bad "a deployment slug is hard-coded:
$(printf '%s\n' "$hits" | sed 's/^/      /')"
    # shellcheck disable=SC2086
    hits="$(grep -rInE '[^0-9][0-9]{12}[^0-9]' $scope || true)"
    [ -z "$hits" ] && ok "no 12-digit account id" ||
        bad "an account id is hard-coded:
$(printf '%s\n' "$hits" | sed 's/^/      /')"
    grep -F 'DJB_DEPLOY_NAMESPACE' "$VB" >/dev/null && ok "the wrapper composes its names from the namespace" ||
        bad "the wrapper never reads DJB_DEPLOY_NAMESPACE — an absent literal is not a derivation"
}

case_the_only_excused_region_is_the_drives_own_fixture() {
    CURRENT=case_the_only_excused_region_is_the_drives_own_fixture
    local hits f
    local scope="scripts/verifier_box.sh scripts/tests/test_verifier_box.sh deploy/verifier deploy/iam"
    # THE ONE EXCUSED REGION IS EXCUSED BY ITS PATH, NOT BY ITS SPELLING. This
    # drive plants `us-west-2` in a scratch `~/.aws/config` on purpose — it is
    # the operator's WRONG region, and the whole point of that fixture is that
    # the wrapper must never inherit it. A `grep -v` on the VALUE excused the
    # string anywhere, including in the wrapper itself, which is the one place
    # it would be a real defect and the only place this census exists to look.
    # So the subject is censused with NO exclusion at all, and the fixture's own
    # file is censused separately.
    local subject_scope=""
    for f in $scope; do
        [ "$f" = "scripts/tests/test_verifier_box.sh" ] || subject_scope="${subject_scope} ${f}"
    done
    local re='\b(us|eu|ap|ca|sa|me|af|il)-(gov-)?(east|west|north|south|central|northeast|northwest|southeast|southwest)-[0-9]\b'
    # shellcheck disable=SC2086
    hits="$(grep -rInE "$re" $subject_scope || true)"
    [ -z "$hits" ] && ok "no region literal in the wrapper or the image side — no exclusion applied there at all" ||
        bad "a region is hard-coded in the subject:
$(printf '%s\n' "$hits" | sed 's/^/      /')"
    hits="$(grep -InE "$re" scripts/tests/test_verifier_box.sh | grep -v 'us-west-2' || true)"
    [ -z "$hits" ] && ok "the drive itself carries no region but its one declared wrong-region fixture" ||
        bad "a region beyond the declared fixture is hard-coded in the drive:
$(printf '%s\n' "$hits" | sed 's/^/      /')"
}

case_the_host_key_posture_is_argued_where_it_is_used() {
    CURRENT=case_the_host_key_posture_is_argued_where_it_is_used
    # TWO OPTIONS THAT WOULD BE A FINDING ANYWHERE ELSE. Turning host-key
    # checking off and throwing the known-hosts file away is, in most scripts,
    # the line that makes a man-in-the-middle possible. Here it is correct — and
    # a correct-looking option with no argument beside it is one the next reader
    # copies into a context where it is not. So the header must say it, and say
    # why, and this case is what stops the sentence being deleted while the
    # options stay.
    local header want miss="" reason=0
    header="$(awk '/^set -euo pipefail$/ {exit} {print}' "$VB")"
    for want in "StrictHostKeyChecking=no" "UserKnownHostsFile=/dev/null"; do
        case "$header" in *"$want"*) ;; *) miss="${miss} ${want}" ;; esac
    done
    [ -z "$miss" ] && ok "the header names both host-key options" ||
        bad "the header never mentions:${miss} — the options are used and never argued"
    # The ARGUMENT, not just the names: the tunnel that has already
    # authenticated, and the key that is new on every launch.
    case "$header" in *"Session Manager"*) reason=$((reason + 1)) ;; esac
    case "$header" in *"FRESH EVERY LAUNCH"*) reason=$((reason + 1)) ;; esac
    [ "$reason" = "2" ] && ok "and argues it: an already-authenticated SSM tunnel, and a host key that is new every launch" ||
        bad "the header names the options but does not argue them (${reason}/2 of the reasons present)"
    # And the option appears nowhere but the transport call sites and that
    # argument.
    #
    # `bake_keep_hands_over` IS ONE OF THOSE SITES, and the widening is
    # deliberate rather than an exemption: it does not OPEN a session, it PRINTS
    # the one `ssh_to` opens, to the same instance id, through the same
    # already-authenticated tunnel, for a box `--keep` has just left running so
    # the operator can walk the rest of the recipe on it. A hand-over that
    # dropped the two options would hand over a command that refuses on a host
    # key that is new by construction — which is the copy-into-the-wrong-context
    # hazard inverted, and it would be the wrapper teaching the operator to
    # improvise the options themselves.
    local sites in_transport in_header
    sites="$(grep -c 'StrictHostKeyChecking=no' "$VB" || true)"
    in_transport="$(awk '/^(ssh_to|cmd_fetch|cmd_push|push_drive_rows|push_the_tree_shallow|bake_keep_hands_over)\(\) \{/,/^\}/' "$VB" | grep -c 'StrictHostKeyChecking=no' || true)"
    in_header="$(printf '%s\n' "$header" | grep -c 'StrictHostKeyChecking=no' || true)"
    [ "$sites" = "$((in_transport + in_header))" ] &&
        ok "${in_transport} use(s) of the option, all inside ssh_to/cmd_fetch/cmd_push/push_drive_rows/push_the_tree_shallow/bake_keep_hands_over, plus ${in_header} in the header that argues it" ||
        bad "${sites} use(s) of the option but only ${in_transport} in the transport functions (+${in_header} in the header) — one escaped the argument"
}

case_nothing_this_wrapper_promised_not_to_touch_moved() {
    CURRENT=case_nothing_this_wrapper_promised_not_to_touch_moved
    # BY THE BYTES ON DISK, BEFORE THE FIRST WRAPPER ACT AND AFTER THE LAST —
    # and it asks git NOTHING. The whole argument for that, and the two
    # measurements that paid for it (a red on every PR carrying a fold, an
    # argument compared as a sha on a detached runner), is at `footprint_of` where
    # the snapshot is taken.
    #
    # `scripts/verify_start.sh` LEFT THIS POPULATION ON 2026-09-18, deliberately
    # and with its replacement below. The wrapper's vouch now REFUSES a checkout
    # whose pre-push hook left no sentinel, and the remedy that refusal names is
    # `core.hooksPath=scripts/githooks` — which `verify_start.sh` sets on the
    # clone it builds, because `git clone` copies neither the config nor a hook
    # file. The two files are PAIRED by that line, so "it did not move" is the
    # wrong claim about it; what this drive owes instead is that the pairing is
    # still there, which is the positive assertion after the comparison. The
    # other three are untouched neighbours and stay measured as absences.
    local after delta acts
    after="$(footprint_of "$ROOT")"
    delta="$(footprint_delta "$FOOTPRINT_BEFORE" "$after")"

    # THE FLOOR FIRST, because two identical snapshots taken either side of
    # NOTHING are green and prove nothing. The count is derived from the
    # counting wrapper every call site in this file goes through, and it is
    # PRINTED: a reader of the green line can see how much of the drive the
    # comparison actually spans.
    acts="$(vb_act_count)"
    if [ "$acts" -ge 1 ]; then
        ok "the comparison spans ${acts} wrapper act(s) — the snapshot was taken before the first and this is after the last"
    else
        bad "the comparison spans ${acts} wrapper act(s) — it is two snapshots of a file nothing touched, which is green by arithmetic"
    fi

    [ -z "$delta" ] && ok "gate_lease.sh, setup.sh and .env.example are byte-for-byte as this drive found them" ||
        bad "files the wrapper does not own have moved:${delta}"

    # ITS OWN VICTIM, and it is built rather than found (rung-execution §2): a
    # comparison nobody has seen fail is a comparison that may be unable to
    # fail. TWO victims, because the two ways a neighbour can move are answered
    # by different branches of `footprint_of` — a WRITE (a wrapper that appends
    # where it promised not to) and a REMOVAL (the `absent` state, which must be
    # a recorded delta and not two silences that match).
    local victim vbefore vafter vdelta
    victim="${WORK}/footprint-victim"
    rm -rf "$victim"
    mkdir -p "${victim}/scripts"
    cp "${ROOT}/scripts/gate_lease.sh" "${ROOT}/scripts/setup.sh" "${victim}/scripts/" 2>/dev/null ||
        cannot_look "could not copy the two scripts into the victim tree ${victim}"
    cp "${ROOT}/.env.example" "${victim}/" 2>/dev/null ||
        cannot_look "could not copy .env.example into the victim tree ${victim}"
    vbefore="$(footprint_of "$victim")"

    # A PLANTED WRAPPER, not a shell line pretending to be one: the same
    # counting shape every real call site uses, doing the one thing this case
    # says never happens.
    local plantwrap="${victim}/plant-wrapper"
    {
        printf '#!/usr/bin/env bash\n'
        printf 'printf "\\n# a wrapper that wrote where it promised not to\\n" >>%s\n' \
            "$(printf '%q' "${victim}/scripts/setup.sh")"
    } >"$plantwrap"
    chmod +x "$plantwrap"
    "$plantwrap" || cannot_look "the planted wrapper would not run"
    vafter="$(footprint_of "$victim")"
    vdelta="$(footprint_delta "$vbefore" "$vafter")"
    case "$vdelta" in
    *scripts/setup.sh*) ok "a planted wrapper appending to setup.sh is caught, and named:${vdelta}" ;;
    *) bad "a planted wrapper appended to setup.sh and the comparison said '${vdelta:-nothing}' — this claim cannot fail" ;;
    esac

    # AND A REMOVED NEIGHBOUR IS `absent`, WHICH IS A DELTA. A comparator that
    # skipped a missing file would call a deleted `.env.example` unchanged.
    rm -f "${victim}/.env.example"
    vafter="$(footprint_of "$victim")"
    vdelta="$(footprint_delta "$vbefore" "$vafter")"
    case "$vdelta" in
    *".env.example  before"*"vs after absent"*) ok "a removed neighbour records \`absent\` and reads as a delta" ;;
    *) bad "a removed .env.example produced '${vdelta:-nothing}' — an absence must be recorded, never skipped" ;;
    esac
    rm -rf "$victim"
    # THE PAIRING, ASSERTED RATHER THAN ASSUMED. The wrapper's no-hook refusal
    # names a remedy; a remedy nothing performs is a sentence. If this line ever
    # leaves `verify_start.sh`, every verification run from a clone refuses at
    # the vouch and the refusal tells the verifier to do something the tool was
    # supposed to have done for them.
    if grep -F -- 'config core.hooksPath scripts/githooks' scripts/verify_start.sh >/dev/null 2>&1; then
        ok "verify_start.sh still sets the hooksPath the wrapper's refusal names as the remedy"
    else
        bad "verify_start.sh no longer sets core.hooksPath — a verify clone would be hookless and every vouch from one would refuse"
    fi
    # THE POPULATION IS WHAT NOTHING RUNS, NOT WHAT THE DIRECTORY HOLDS, and
    # the difference cost a red on main. This line used to count
    # `deploy/tests/*.sh`, so the moment `test_stage.sh` was WIRED into
    # `scripts/check.sh` — correctly, as the first deploy-layer drive the
    # selftest leg can run — the directory grew and the count reded, punishing
    # exactly the change the claim exists to ask for. `test_verifier_image.sh`
    # carried the identical defect and fixed it first; the derivation below is
    # that fix, and the two copies are compared rather than trusted.
    local n want
    n="$(deploy_layer_unfenced deploy/tests scripts/check.sh)"
    want="$(deploy_layer_baseline deploy/tests scripts/check.sh)"
    if [ "$n" = "$want" ]; then
        ok "${n} deploy-layer drive(s) no moment invokes, and the two derivations agree — a drive WIRED into the gate leaves the set rather than growing it"
    else
        bad "the two derivations of the gap disagree: the per-file walk says ${n}, the directory minus the gate's invocation lines says ${want} — one of them has the fence's shape wrong"
    fi

    # ITS OWN VICTIM. A count nobody has seen fail is a count that may be
    # unable to fail, and this one is arithmetic over two derived sets.
    local plant d
    plant="${WORK}/deploy-layer-unfenced"
    rm -rf "$plant"
    mkdir -p "$plant"
    for d in deploy/tests/test_*.sh; do cp "$d" "$plant/"; done
    cp scripts/check.sh "$plant/check.sh"
    : >"${plant}/test_zzz_probe.sh"
    n="$(deploy_layer_unfenced "$plant" "${plant}/check.sh")"
    if [ "$n" = "$((want + 1))" ]; then
        ok "an UNFENCED newcomer moves the gap: ${want} -> ${n}"
    else
        bad "an unfenced newcomer left the gap at ${n}, wanted $((want + 1)) — this count cannot fail"
    fi

    printf './deploy/tests/test_zzz_probe.sh\n' >>"${plant}/check.sh"
    n="$(deploy_layer_unfenced "$plant" "${plant}/check.sh")"
    if [ "$n" = "$want" ]; then
        ok "and the same newcomer WIRED at column zero does not — the gap is what nothing runs"
    else
        bad "a wired newcomer left the gap at ${n}, wanted ${want} — fencing a drive must not red this"
    fi
    rm -rf "$plant"

    # THE TWO COPIES, COMPARED. `deploy_layer_unfenced` is mirrored here rather
    # than promoted into `drive_preamble.sh`: the preamble is sourced by every
    # drive in the tree and a two-caller helper does not earn a change to it
    # (principle 11). What a mirror owes instead is that it cannot drift
    # silently — so the sibling's definition is extracted and compared to this
    # file's, byte for byte, and a divergence reds HERE rather than showing up
    # as two drives disagreeing about the same number.
    local twin="scripts/tests/test_verifier_image.sh" mine theirs
    if [ ! -r "$twin" ]; then
        cannot_look "${twin} is not in this tree — the mirrored helper has no twin to be compared against"
    fi
    local fn
    for fn in deploy_layer_unfenced deploy_layer_baseline; do
        mine="$(awk -v f="${fn}() {" 'index($0, f) == 1 {on=1} on{print} on && $0=="}"{exit}' "$0")"
        theirs="$(awk -v f="${fn}() {" 'index($0, f) == 1 {on=1} on{print} on && $0=="}"{exit}' "$twin")"
        if [ -z "$mine" ] || [ -z "$theirs" ]; then
            cannot_look "one of the two ${fn} definitions could not be read (this file: $(printf '%s' "$mine" | grep -c .) line(s), ${twin}: $(printf '%s' "$theirs" | grep -c .))"
        elif [ "$mine" = "$theirs" ]; then
            ok "the mirrored ${fn} is byte-identical to ${twin}'s"
        else
            bad "the two copies of ${fn} have drifted — two derivations of one population is the defect this pair just fixed"
        fi
    done
}

# deploy_layer_baseline <directory> <gate file> — the SAME gap, counted a
# different way: every deploy-layer drive in the directory, minus the ones the
# gate file invokes at column zero. MIRRORED in `test_verifier_box.sh` and
# `test_verifier_image.sh`; both cases compare the two definitions byte for
# byte, so the copy cannot drift.
#
# WHY IT EXISTS, AND WHY THE NUMBER IS NO LONGER TYPED. The expectation used to
# be a literal — `7` here and `7` in the twin, each with its own plant arms at
# `8`/`7` — and the first consumer's bank is what removed it: a product is
# licensed to grow `deploy/tests/`, theirs holds sixteen, and the case reded
# with `the gate invokes none of 15 drive(s) under deploy/tests/, wanted 7` on
# a tree where nothing was wrong. A typed count of a population a product owns
# is a template asserting about somebody else's directory.
#
# AND A DERIVATION COMPARED AGAINST ITSELF ASSERTS NOTHING, which is why this
# is arithmetic over two whole sets rather than a second copy of the per-file
# loop: `deploy_layer_unfenced` walks the directory and asks the gate about
# each file; this one counts the directory and counts the gate's own
# invocation lines. The two agree only if the fence's shape is what both of
# them think it is, which is the property the typed number was standing in for.
deploy_layer_baseline() {
    local dir="$1" gate="$2" total=0 wired=0 d
    for d in "$dir"/test_*.sh; do
        [ -f "$d" ] || continue
        total=$((total + 1))
    done
    wired=$(grep -c '^\./deploy/tests/test_[A-Za-z0-9_]*\.sh$' "$gate" || true)
    printf '%s\n' "$((total - wired))"
}

# deploy_layer_unfenced <directory> <gate file> — how many deploy-layer drives
# that gate file does NOT invoke. MIRRORED from `test_verifier_image.sh`; the
# case above compares the two definitions so the copy cannot drift.
#
# THE INVOKED SET IS DERIVED FROM THE FENCE AND NEVER TYPED, and it is the
# gate's own derivation: a drive is run iff `./deploy/tests/<name>.sh` appears
# in `scripts/check.sh` as a WHOLE LINE AT COLUMN ZERO, which is the shape
# `selftest_registered_drives` reads and the shape the blind-spot block
# subtracts with.
deploy_layer_unfenced() {
    local dir="$1" gate="$2" d n=0
    for d in "$dir"/test_*.sh; do
        [ -f "$d" ] || continue
        if grep -qxF "./deploy/tests/${d##*/}" "$gate"; then continue; fi
        n=$((n + 1))
    done
    printf '%s\n' "$n"
}

# =============================================================================

echo "test_verifier_box: $(grep -c '^case_[A-Za-z0-9_]*() {' "$0") case(s)"
echo ""

case_the_wrapper_refuses_without_a_namespace_or_a_region
case_up_refuses_when_there_is_no_profile
case_up_refuses_when_the_session_plugin_is_absent
case_up_refuses_when_no_image_has_been_baked

case_up_takes_an_explicit_image_id_over_the_tag_lookup
case_up_refuses_an_explicit_image_that_is_not_available_yet
case_up_launches_exactly_the_box_the_design_describes
case_up_refuses_a_lifetime_above_the_cap
case_up_carries_a_shorter_lifetime_and_idle_through

case_a_spot_refusal_falls_back_to_on_demand_and_says_which
case_the_spot_service_linked_role_refusal_is_named_as_the_prerequisite_it_is
case_on_demand_asked_for_is_one_call_with_no_market_options
case_a_credential_error_is_exit_2_and_one_call

case_a_bank_shard_never_falls_back_to_on_demand_silently
case_a_bank_shard_with_the_valve_buys_on_demand_and_prints_the_reason
case_a_single_up_keeps_the_fallback_and_prints_the_price
case_an_unasked_price_is_printed_as_unknown_and_says_why
case_up_prints_the_market_ec2_reports_not_the_one_it_asked_for
case_harvest_drives_brings_the_boxs_rows_home_once
case_harvest_drives_without_a_tree_is_refused
case_census_prints_the_market_each_box_is_on

case_the_box_ceiling_refuses_before_the_call
case_a_raised_ceiling_launches
case_the_ceiling_is_read_from_the_file_when_the_env_is_unset
case_the_env_ceiling_wins_over_the_file
case_the_ceiling_refusal_names_all_three_and_the_one_that_bound
case_ceiling_prints_the_file_the_env_and_the_quota
case_a_ceiling_file_that_is_not_a_number_is_exit_2_before_any_call
case_census_prints_the_ceiling_beside_the_pool

case_down_refuses_an_instance_that_is_not_ours
case_down_refuses_another_namespaces_box
case_down_terminates_and_takes_the_private_key_with_it
case_down_all_mine_leaves_other_owners_alone

case_census_says_nothing_when_there_is_nothing
case_census_finds_an_overdue_box_and_that_is_a_finding
case_census_flags_a_bake_box_that_outlived_its_bake
case_census_that_cannot_look_is_exit_2

case_pool_launches_the_difference_with_the_pool_tags
case_pool_trims_only_unclaimed_boxes
case_pool_above_the_ceiling_is_exit_2_before_any_call
case_a_pool_launch_carries_its_idle_threshold
case_up_claims_a_warm_box_and_launches_nothing
case_two_claims_of_one_warm_box_yield_one_winner
case_a_warm_box_on_another_image_or_without_a_key_is_skipped_by_name
case_census_prints_the_pool_and_its_hourly_cost
case_census_with_no_pool_says_empty

case_run_carries_the_transport_and_touches_the_activity_marker
case_run_passes_the_remote_status_through_unchanged
case_run_refuses_a_reclaimed_box_without_attempting_ssh
case_loop_detaches_the_gate_on_the_box_and_never_pipes_it
case_leg_detaches_one_unit_shard_and_never_pipes_it
case_leg_forwards_the_pass_count_verbatim
case_leg_passes_the_shards_own_status_through
case_leg_without_a_unit_or_log_is_refused
case_the_push_carries_the_rungs_fork_point_as_a_ref
case_a_rung_too_far_from_its_fork_point_carries_nothing_and_says_so
case_a_union_pushed_as_main_carries_the_fork_point_it_declares
case_commits_past_main_with_no_fork_point_are_refused_before_anything_leaves
case_a_declared_base_that_is_not_behind_head_is_not_carried
case_wait_passes_the_gates_own_status_through
case_harvest_brings_exactly_the_banked_row_home
case_harvest_refuses_a_log_that_banked_nothing
case_harvest_twice_is_one_row
case_push_sends_only_the_drive_rows
case_harvest_brings_the_drive_rows_of_the_banked_tree
case_the_wrapper_reaches_python_only_through_the_checkout
case_fetch_uses_the_same_transport

case_push_reads_the_checkout_path_out_of_the_recipe
case_the_push_sends_a_depth_one_mirror_and_not_the_history
case_the_first_push_to_a_box_clears_its_refs
case_a_shallow_mirror_cannot_send_two_refs_in_one_push
case_a_shallow_push_into_a_box_that_already_has_refs_is_refused
case_the_wrapper_sends_one_ref_per_push_base_first
case_a_refused_base_never_sends_the_tree
case_the_pre_push_hook_still_vouches_for_the_tree_that_goes
case_a_hook_that_refuses_stops_the_push_before_the_tunnel
case_the_push_moves_the_boxs_working_tree_onto_what_it_pushed
case_a_push_whose_box_worktree_will_not_move_is_refused
case_a_loop_over_a_box_that_is_not_on_the_pushed_tree_is_refused
case_a_vouch_with_no_hook_is_refused
case_an_unmeasured_union_tree_reaches_the_box_without_a_mac_gate
case_a_box_destination_never_carries_a_foreign_tree
case_the_destination_variable_alone_opens_nothing
case_a_tunnel_under_the_floor_refuses_before_the_pack
case_the_push_transport_survives_the_shell_git_runs_it_in
case_a_transport_that_dies_while_the_hook_measures_is_git_141
case_the_push_transport_outlives_a_hook_that_measures
case_a_push_that_died_of_sigpipe_is_named_for_what_it_is
case_no_early_exit_reader_follows_a_pipe_in_this_wrapper
case_a_box_whose_tree_differs_is_exit_2
case_up_prints_the_tree_agreement_when_they_agree
case_a_refused_push_inside_up_names_the_box_it_left_running

case_bake_launches_on_demand_and_captures_a_private_image
case_bake_waits_for_the_boxs_bootstrap_before_it_pushes
case_the_bake_seam_grants_the_recipe_the_root_it_needs
case_a_recipe_that_refuses_is_a_refusal_the_operator_can_read
case_bake_terminates_its_builder_when_the_bootstrap_never_finishes
case_bake_terminates_its_builder_when_the_recipe_fails
case_bake_terminates_its_builder_when_the_recipe_session_fails
case_bake_terminates_its_builder_when_the_push_is_refused
case_bake_terminates_its_builder_when_the_agent_never_registers
case_bake_terminates_its_builder_when_the_wrapper_is_killed
case_bake_terminates_its_builder_when_the_image_never_lands
case_a_teardown_that_cannot_terminate_says_so_and_names_the_hand
case_a_teardown_whose_credential_expired_still_hands_over_the_id
case_a_teardown_in_the_body_cannot_swallow_a_failed_terminate
case_bake_stamps_its_phases_and_prints_their_durations
case_bake_keep_leaves_the_box_up_when_the_recipe_fails
case_bake_keep_leaves_the_box_up_when_the_capture_produces_nothing
case_bake_keep_still_tears_down_every_box_it_does_not_cover
case_the_base_image_is_pinned_printed_and_recorded_on_the_capture
case_a_pinned_base_image_is_used_and_the_parameter_is_not_read
case_census_prints_the_image_each_box_is_running
case_a_capture_whose_tags_are_refused_keeps_the_image_and_names_the_policy
case_a_namespace_that_is_not_ascii_refuses_before_a_box_is_launched
case_the_image_is_named_for_the_tree_it_holds_not_local_main
case_bake_refuses_before_the_launch_when_there_is_no_local_main
case_bake_prune_keeps_the_newest_two
case_bake_prune_finds_snapshots_through_the_block_mappings

case_up_with_az_launches_into_that_zones_subnet
case_a_zone_refusal_tries_the_next_zone_once_then_the_market_rule
case_up_records_the_spot_request_id
case_wait_on_a_reclaimed_box_prints_the_spot_status_code
case_a_status_the_policy_cannot_read_is_named_not_hidden
case_down_on_a_reclaimed_box_says_already_gone_and_is_not_a_refusal
case_down_that_cannot_look_says_so_and_never_calls_it_foreign
case_a_probe_that_is_not_yet_connected_is_retried_within_the_ceiling
case_up_names_the_box_before_anything_can_fail_after_the_launch
case_census_prints_each_boxs_zone
case_zones_lists_the_vpcs_zones_and_refuses_when_it_cannot_look
case_a_describe_that_has_not_caught_up_cannot_lie_about_the_market
case_a_warm_claim_says_the_zone_you_typed_applied_to_nothing
case_the_ops_policy_grants_the_spot_request_read
case_the_territory_this_change_does_not_own_did_not_move
case_the_detach_returns_while_the_gate_is_still_running

case_a_piped_stdout_is_refused
case_an_unknown_subcommand_or_flag_is_exit_2
case_no_product_name_account_or_region_is_hard_coded
case_the_only_excused_region_is_the_drives_own_fixture
case_the_host_key_posture_is_argued_where_it_is_used
case_nothing_this_wrapper_promised_not_to_touch_moved

echo ""
echo "test_verifier_box: ${PASSED} passed, ${FAILED} failed, ${SKIPPED} skipped"
if [ "$SKIPPED" -gt 0 ]; then
    echo "  skipped, each with the shape that has no owner here:${SKIP_REASONS}"
fi
drive_finished
[ "$FAILED" = "0" ] || exit 1
exit 0
