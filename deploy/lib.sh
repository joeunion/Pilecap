# road: deploy_scaffold — a deploy executable's die, say, usage and act harness, sourced once · example: quality/tests/deploy/test_release.py::test_every_deploy_executable_sources_the_one_scaffold
# deploy/lib.sh — the one scaffold a deploy executable sources.
#
# A LIBRARY, NOT AN INSTRUMENT: sourced, never executed, mode 644. It gives a
# deploy script its refusal, its narration, its usage and its act harness, and
# it takes the refusal and the pipe guard from the one seam the gate's scripts
# already use (`scripts/gate_refuse.sh`) rather than keeping copies of its own.
#
# THE DEFECT IT ANSWERS. `die`, `say` and `usage` were written once per deploy
# script, six times, each "deliberately identical" to another script's, each
# citing that other script by a line number that had since moved; the pipe
# guard was copied four times; `ACTS`/`act`/`stopped` twice. Copies that are
# deliberately identical are the copies that drift.
#
# THE CALLER, in this order:
#
#     . "$(dirname -- "${BASH_SOURCE:-$0}")/../scripts/bash_only.sh" || exit 2   # the belt, line 2
#     ...
#     HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
#     DEPLOY_NAME=release                                   # what every line leads with
#     DEPLOY_NOTHING="Nothing was released; no act ran."    # die's trailer — may be empty
#     . "$HERE/lib.sh" || exit 2
#     refuse_if_piped "$DEPLOY_NAME"                        # only where the exit status is the verdict
#
# and it gets:
#
#   die <text>…      `!! <name>: <text>`, the trailer indented, exit 2 — `gate_die`
#   say <text>…      `<name>: <text>` on stdout
#   usage [status]   the header's usage lines (DEPLOY_USAGE_LINES of them, or the
#                    whole leading comment block), DEPLOY_USAGE_TAIL after them, then
#                    exit <status> — 2 unless given (`--help` passes 0)
#   act_begin        the next act of the caller's ACTS, counted, not printed
#   act              act_begin, then `<name>: [i/N] <the act's line>`
#   act_ran/act_skipped/act_would <detail>   one line about the act begun
#   stopped <status> `RED: <name>: STOPPED at act i/N — <act> (exit <status>)`,
#                    DEPLOY_RECOVERY indented under it, exit 1 — an act that RAN
#                    and failed is a finding, never a could-not-look
#   bucket_name <kind> <env> <account>   `<NAMESPACE>-<env>-<account>-<kind>`, the
#                    one spelling of the media and backups buckets
#
# WHO DOES NOT SOURCE IT, and why — each one runs where `scripts/` is not:
#
#   deploy/entrypoint.sh, deploy/assert_not_published.sh,
#   deploy/observability/alerts/prober.sh   inside a container, where only
#                                           `deploy/` is mounted (at /deploy)
#   deploy/verifier/idle_reaper.sh          installed alone at /opt/verifier
#
# WHAT IT DOES NOT COVER
# does-not-cover: a deploy script run from a tree with no `scripts/` beside `deploy/` — the source fails and the caller exits 2 before its first line of work; the four above are the declared population that runs that way.
# does-not-cover: what an act does — the harness counts, names and stops acts; whether an act is idempotent is the act's own claim.

DEPLOY_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

# shellcheck source=scripts/gate_refuse.sh
. "$DEPLOY_ROOT/scripts/gate_refuse.sh" || {
    echo "!! ${DEPLOY_NAME:-deploy}: could not source $DEPLOY_ROOT/scripts/gate_refuse.sh — the refusal seam every deploy script speaks through." >&2
    exit 2
}

: "${DEPLOY_NAME:?deploy/lib.sh is sourced after its caller sets DEPLOY_NAME}"
: "${DEPLOY_NOTHING:=}"
: "${DEPLOY_USAGE_LINES:=}"
: "${DEPLOY_USAGE_TAIL:=}"
: "${DEPLOY_RECOVERY:=}"

die() {
    gate_die "$DEPLOY_NOTHING" "${DEPLOY_NAME}: $*"
}

say() { echo "${DEPLOY_NAME}: $*"; }

# The header's usage lines: the leading comment block after the shebang and the
# belt, `# ` stripped — the first DEPLOY_USAGE_LINES of it, or all of it.
usage() {
    local self="${BASH_SOURCE[1]:-$0}"
    awk -v want="${DEPLOY_USAGE_LINES:-0}" '
        NR == 1 { next }
        !started && /^\. / { next }
        /^#/ { started = 1; sub(/^# ?/, ""); print; n++; if (want > 0 && n >= want) exit; next }
        started { exit }
    ' "$self"
    if [ -n "$DEPLOY_USAGE_TAIL" ]; then
        echo ""
        echo "$DEPLOY_USAGE_TAIL"
    fi
    exit "${1:-2}"
}

# --- the act harness ------------------------------------------------------------
# The caller names its acts once, `ACTS=("name — what it does" …)`, and every
# count and every header is derived from that list: an act added without a
# name there prints `[8/7]`, which is the kind of thing a reader notices.
ACT_INDEX=0
ACT_NAME=""
ACT_T0=0

act_begin() {
    ACT_INDEX=$((ACT_INDEX + 1))
    ACT_NAME="${ACTS[$((ACT_INDEX - 1))]%% —*}"
    ACT_T0="$(date +%s)"
}

act() {
    act_begin
    echo ""
    echo "${DEPLOY_NAME}: [${ACT_INDEX}/${#ACTS[@]}] ${ACTS[$((ACT_INDEX - 1))]}"
}

act_ran() {
    echo "${DEPLOY_NAME}: [${ACT_INDEX}/${#ACTS[@]}] ${ACT_NAME} — ran${1:+: $1} ($(($(date +%s) - ACT_T0))s)"
}

act_skipped() {
    echo "${DEPLOY_NAME}: [${ACT_INDEX}/${#ACTS[@]}] ${ACT_NAME} — skipped: $1 unchanged ($(($(date +%s) - ACT_T0))s)"
}

act_would() {
    echo "${DEPLOY_NAME}: [${ACT_INDEX}/${#ACTS[@]}] ${ACT_NAME} — WOULD RUN${1:+: $1}"
}

# The one failure path. Every act routes through it, so the paragraph a human
# reads after a failed run is the same every time and always names the act.
stopped() {
    local status="${1:-1}"
    echo "" >&2
    set -- "${DEPLOY_NAME}: STOPPED at act ${ACT_INDEX}/${#ACTS[@]} — ${ACT_NAME} (exit ${status})." \
        "No act after this one ran."
    [ -z "$DEPLOY_RECOVERY" ] || set -- "$@" "$DEPLOY_RECOVERY"
    gate_finding "$@"
}

# S3's namespace is global across every AWS customer; the account id makes the name ours.
bucket_name() {
    local kind="$1" environment="$2" account="$3"
    case "$kind" in media | backups) ;; *) die "bucket_name: no bucket kind '$kind' (media or backups)" ;; esac
    [[ "$account" =~ ^[0-9]{12}$ ]] || die "bucket_name: '$account' is not a 12-digit AWS account id"
    printf '%s-%s-%s-%s' "${NAMESPACE:?bucket_name needs NAMESPACE}" "$environment" "$account" "$kind"
}
