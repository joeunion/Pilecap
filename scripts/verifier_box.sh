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
# THE VERIFIER BOX WRAPPER — one throwaway EC2 machine per verification, brought
# up, pushed to, run on, and taken down, from this laptop.
#
#   verifier_box.sh up --for <rung> [--az <az>] [--ttl <h>] [--idle <min>] [--type <t>] [--on-demand] [--no-push] [--image-id <ami>]
#   verifier_box.sh down <id> | --all-mine
#   verifier_box.sh pool --want <N> [--idle <min>]
#   verifier_box.sh census
#   verifier_box.sh ceiling [<n>]
#   verifier_box.sh zones
#   verifier_box.sh run <id> -- <cmd...>
#   verifier_box.sh loop <id> --log <name>
#   verifier_box.sh leg <id> --unit <unit> [--shard k/N] [--passes 1|2] --log <name>
#   verifier_box.sh wait <id> <name>
#   verifier_box.sh fetch <id> <remote> <local>
#   verifier_box.sh harvest <id> <name>
#   verifier_box.sh harvest-drives <id> <tree>
#   verifier_box.sh push <id> [<branch>...]
#   verifier_box.sh bake [--prune] [--keep]
#
# WHY IT EXISTS. A verification is one `--loop` on a tree, and this machine has
# two pytest slots for every agent on it at once. A verification that waits
# forty minutes for a slot has not been made more correct by the wait. So the
# clone, the compose stack and the gate move to a box nobody else is using, and
# the number the ledger records is the verification's own.
#
# WHERE THE AGENT STAYS: HERE. Only the clone, the stack and the gate are on the
# box. Every command that touches the tree is `run`, the gate is `loop` + `wait`,
# the artefacts come back with `fetch`, and the report, the ledger row and every
# docs edit are written on this machine exactly as before. Running the AGENT on
# the box was rejected: it needs a credential on an instance designed to be
# reclaimed, it moves the ledger writes off the primary checkout, and a Spot
# interruption would kill the agent mid-thought instead of killing a log it can
# re-fetch.
#
# THE TRANSPORT IS SSH OVER SESSION MANAGER — never a listening port. The box
# has no key pair, no ingress rule of any kind and an egress-only security
# group; `up` generates a per-box ed25519 pair on this machine, passes the
# PUBLIC half in user-data, and every remote command tunnels through
# `aws ssm start-session --document-name AWS-StartSSHSession`. stdout, stderr
# and the exit status pass through unaltered, which is what a forty-minute gate
# needs and what `ssm send-command` (polled, output truncated) cannot give.
#
# HOST KEYS ARE NOT CHECKED, AND THAT IS ARGUED RATHER THAN ASSUMED. Every ssh,
# scp and git-push below carries `StrictHostKeyChecking=no` and
# `UserKnownHostsFile=/dev/null`, which in almost any other script is the line
# that makes a man-in-the-middle possible. Three things make it correct here and
# all three have to hold:
#
#   * THE TUNNEL IS ALREADY AUTHENTICATED. The connection does not cross the
#     internet to a hostname: it goes through `ssm start-session` to an INSTANCE
#     ID, and Session Manager has already authenticated both ends against this
#     account before a single ssh byte moves. There is no name to spoof and no
#     route to intercept — the thing a host key would be protecting against has
#     been done one layer down.
#   * THE HOST KEY IS FRESH EVERY LAUNCH. A verifier box is made, used and
#     terminated; its host key is generated at first boot and has never existed
#     before. There is nothing to have pinned, so a known-hosts entry would be
#     written once and never matched — and `StrictHostKeyChecking=ask` on a
#     non-interactive wrapper is a hang, not a guard.
#   * THE KNOWN-HOSTS FILE IS THROWN AWAY ON PURPOSE. Writing these one-shot keys
#     into the operator's real `~/.ssh/known_hosts` would grow a file of entries
#     for instance ids that no longer exist, and a future instance id COLLIDING
#     with a stale entry is a warning that stops a verification for no reason.
#
# If any of those stops being true — a box that must be reached by hostname, a
# box that outlives one verification, a transport that is not SSM — then this
# posture stops being correct and the two options come out. The drive asserts
# this paragraph is here, beside the option, so it cannot be deleted while the
# options stay.
#
# EVERY NAME IT TOUCHES DERIVES FROM THE DEPLOYMENT NAMESPACE. More than one
# product shares one AWS account, so a fixed name would mean one product's
# census listing another's boxes and offering to terminate them. The identity,
# the instance profile, the security group, the image, the tags and this
# script's own state directory are all composed from `DJB_DEPLOY_NAMESPACE`,
# which is REQUIRED and has no default — a guessed namespace is a write into
# somebody else's resources. `djb:namespace` rides on every resource it creates
# and every filter it reads.
#
# WHAT NEVER LANDS ON A BOX: this machine's AWS credential or any profile (the
# box's own role can register with Session Manager and do nothing else); a forge
# token or deploy key (the tree is PUSHED to the box); the agent harness or its
# credential; an environment's secrets prefix or its instance profile; any
# private key (the private half of the per-box pair never leaves this machine
# and `down` deletes it). The only database on the box is the throwaway compose
# stack's and the only secrets are that stack's published throwaways.
#
# EXIT GRAMMAR, and it is the one every instrument here keeps:
#
#   0  it did the thing
#   1  a FINDING — `census` found an OVERDUE box, `wait` passed a red gate's own
#      status through. Something is true that you need to know.
#   2  REFUSED, or COULD NOT LOOK. Nothing was launched and nothing was
#      terminated. A missing coordinate, a missing profile, a missing plugin, a
#      missing image, a ceiling reached, an unknown flag, a piped stdout, an
#      instance that is not tagged as one of ours, an AWS call that failed.
#
# 2 OUTRANKS EVERYTHING, here as everywhere in this repository: a wrapper that
# could not look has cleared nothing. And a remote command's own status is
# passed through UNCHANGED — `run` never rewrites a remote 1 into a 2 or a 2
# into a 1, because the thing on the other end of the transport is the gate and
# its status is the verdict.
#
# `bake --keep` IS THE ONE PLACE A FAILURE LEAVES A BOX RUNNING, and it is the
# operator's word rather than the wrapper's judgment. On a recipe that did not
# finish, or a capture that produced nothing, the box stays up so the remaining
# steps can be walked by hand through the tunnel in one sitting — the failure
# still in place, the finished steps still done — instead of paying twenty
# minutes for the next guess. Every other way out still tears down with or
# without the flag, and what is kept is watched by NOTHING but the census: a
# bake box runs no reaper, so its `djb:expires` tag is a label rather than a
# timer. The full argument, and the sentence it hands the operator, are beside
# `bake_keep_hands_over` below.
#
# THE TWO DESCRIPTORS `bake` OPENS, AND THE LEAK THAT IS ACCEPTED WITH THEM.
# `cmd_bake` runs `exec 8>&1 9>&2` before it arms its teardown, and the
# teardown speaks through 8 and 9 rather than through 1 and 2. It has to: a
# trap runs inside whatever redirection was in force where it FIRED, and the
# readiness probe is `ssh_to … >/dev/null 2>&1`, so a wrapper killed during
# that wait terminated its box and said not one word about it. The drive proved
# that mechanism load-bearing by plant — dropping `>&8 2>&9` reds the "says so"
# assertion and nothing else.
#
# THE COST IS TWO INHERITED DESCRIPTORS. Bash marks the fds it allocates for
# itself (10 and up) close-on-exec; an explicitly numbered one does not get
# that, so 8 and 9 are inherited by every child `cmd_bake` spawns after that
# line — `ssh`, `git`, `ssh-keygen`, the `aws` CLI, and through the transport
# the remote recipe's own shell. IT IS ACCEPTED, for three reasons together:
# they are DUPLICATES of stdout and stderr, which every child already inherits
# as 1 and 2, so nothing is reachable through them that was not reachable
# anyway; no number is ever passed in an argument or an environment variable, so
# no child is told they exist; and their lifetime is one `bake` in one shell
# that exits at the end of it — no other subcommand arms them. The alternative
# is `8>&- 9>&-` on every call site inside `cmd_bake`, which is a wrapper
# around every remote call whose one forgotten instance is a descriptor leak
# nobody can see, to close a hole that is two aliases of the operator's own
# terminal. If a bake ever spawns a long-lived child, or hands a descriptor
# number to anything, this paragraph is the thing that stopped being true.
#
# WHAT IT CANNOT SEE, declared rather than discovered:
#
#   * EVERYTHING AN `aws` SHIM CANNOT KNOW. The drive beside this file plants
#     `aws`, `ssh`, `scp`, `git` and `session-manager-plugin` and asserts the
#     ARGUMENTS and the REFUSALS. Whether `AWS-StartSSHSession` works through
#     this account's Session Manager preferences, whether cloud-init honours the
#     authorized-key slot for a user it creates in the same run, and whether
#     `PingStatus=Online` arrives inside the wait are the field test's, on a real
#     box, and nothing here proves them.
#   * WHETHER `InstanceInitiatedShutdownBehavior=terminate` ACTUALLY TERMINATES.
#     This file passes the flag; the image's reaper depends on it absolutely (a
#     halt that merely STOPS leaves a root volume billing with nobody watching).
#     Only a real box answers it.
#   * THE OWNER DERIVATION. `DJB_VERIFIER_OWNER` falls back to the session name
#     in the dispatch ledger's header, and a wrong answer is a wrong `djb:owner`
#     tag: `census` prints it and `--all-mine` filters on it, so the failure is
#     a box `--all-mine` SKIPS, never somebody else's box terminated.
#   * COST. Prices are read at launch and printed. Nothing alerts, and the only
#     ceilings are the per-box TTL and `DJB_VERIFIER_MAX_BOXES`.
set -euo pipefail

# --- it refuses to be piped --------------------------------------------------
# check.sh's detection and its CI exemption, deliberately identical
# (`scripts/check.sh:167`) and for the same reason: a pipe replaces this
# script's exit status with the filter's, and the exit status is the verdict.
if [ -z "${CI:-}" ] && { [ -p /dev/fd/1 ] || [ -p /dev/stdout ]; }; then
    echo "!! verifier_box refuses pipes — run it bare or redirect to a file." >&2
    echo "   The exit status is the verdict, and a filter replaces it." >&2
    exit 2
fi

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$HERE/.." && pwd)"
set +x # never; the ProxyCommand below carries a profile name and a path

die() {
    echo "!! verifier_box: $*" >&2
    exit 2
}
finding() {
    echo "!! verifier_box: $*" >&2
    exit 1
}
# EVERY LINE THIS WRAPPER NARRATES CARRIES THE TIME IT WAS NARRATED AT, and the
# stamp comes from `now_epoch` — the same clock the waits below measure with —
# so a drive that fakes the clock sees the wrapper's own idea of the time and
# never the machine's. FIELD TEST 3 is the argument: a whole run against a real
# box whose one number — how long the box's own bootstrap took — was
# unrecoverable afterwards, because not one line of the output said when it was
# printed. `now_stamp` is defined further down, beside the clock it reads.
say() { echo "verifier_box: [$(now_stamp)] $*"; }

#: Values a caller may override. Read at CALL time, never cached, and the three
#: coordinates at the top have NO DEFAULT: a guessed namespace, account or region
#: is a write into somebody else's resources, and a default one shipped in the
#: template is a per-deployment fact every clone inherits without being asked.
#:
#:   DJB_DEPLOY_NAMESPACE      REQUIRED. The slug every name below is composed
#:                             from — the profile, the instance profile, the
#:                             security group, the image, the Project tag and
#:                             this script's own state directory. The same
#:                             variable `deploy/provision.sh` requires, for the
#:                             same reason.
#:   DJB_VERIFIER_REGION       REQUIRED. The region the boxes live in. There is
#:                             no default and this script never inherits the
#:                             profile's: an operator's configured default
#:                             region is very often NOT the one the environment
#:                             boxes are in, and a launch there is a box the
#:                             census cannot see.
#:   DJB_VERIFIER_PROFILE      the AWS CLI profile that can bring boxes up.
#:                             Default: `<namespace>-verifier`, the name
#:                             `deploy/iam/verifier_bootstrap.sh` tells the owner
#:                             to create.
#:   DJB_VERIFIER_INSTANCE_TYPE  default `c7g.4xlarge` — 16 vCPU, 32 GB, arm64,
#:                             which is this laptop's memory and 1.6x its cores.
#:   DJB_VERIFIER_TTL_HOURS    the hard lifetime a box enforces on ITSELF.
#:                             Default 4, cap 12. Above the cap is exit 2 before
#:                             anything is launched.
#:   DJB_VERIFIER_IDLE_MINUTES the idle threshold the box's reaper honours.
#:                             Default 30.
#:   DJB_VERIFIER_MAX_BOXES    how many of ours may run at once. It is the TOP
#:                             of a three-step precedence — this variable, then
#:                             the file `<DJB_VERIFIER_HOME>/ceiling`, then the
#:                             default 2 (two 16-vCPU boxes is the 32-vCPU Spot
#:                             quota a fresh account has). `ceiling` reads and
#:                             writes that file and prints all three with the
#:                             one that binds; every ceiling refusal prints the
#:                             same three, so "why two" is never a guess.
#:                             WHY THE FILE EXISTS: the variable is per-shell,
#:                             and a wave of fifteen agents is fifteen shells —
#:                             so the number that governs the whole machine
#:                             lived nowhere, and every one of them either hit
#:                             the default or spent a turn on the env-prefix
#:                             form its permission classifier refuses. The file
#:                             is one operator-written integer under
#:                             DJB_VERIFIER_HOME, which every session on this
#:                             machine already shares.
#:   DJB_VERIFIER_HOME         where the per-box keypairs and state live.
#:                             Default `~/.<namespace>/verifier`. OUTSIDE every
#:                             checkout, deliberately: a private key inside the
#:                             tree is a private key the gate measures.
#:   DJB_VERIFIER_OWNER        the `djb:owner` tag. Default: the session name in
#:                             the dispatch ledger's header, else
#:                             `$USER@$(hostname -s)`.
#:   DJB_VERIFIER_BAKE_TYPE    the bake box's type. Default `c7g.2xlarge`, and
#:                             always on-demand: a bake interrupted is an image
#:                             half-written.
#:   DJB_VERIFIER_AL2023_AMI   the base image a BAKE starts from, pinned by id.
#:                             Default: whatever the public SSM parameter
#:                             resolves to TODAY — which is the problem it
#:                             exists to solve. Two field tests a day apart ran
#:                             two different base AMIs and got two very
#:                             different machines; an unpinned base makes every
#:                             field test a different experiment. The bake
#:                             prints the id it resolved AND the image's own
#:                             dated name, and records both on the image it
#:                             captures, so a later bake can be pinned to a base
#:                             that was measured to work.
#:   DJB_VERIFIER_PROBE_MB     the throughput probe before every push, in MB.
#:                             Default 1; 0 turns it off. Why 1 and not the
#:                             tree's own size is argued at `throughput_probe`.
#:   DJB_VERIFIER_MAX_SCOPE_DEPTH  how many of the rung's own commits the push
#:                             will deepen the mirror by so the box can derive
#:                             the same --loop scope this machine does. Default
#:                             200. Above it the fork point is not carried, the
#:                             box's scope comes back empty, and the push SAYS
#:                             so — a rung that far from its fork point is not a
#:                             rung, and dragging a repository over a tunnel
#:                             measured in tens of kilobytes a second is the
#:                             failure the probe beside it exists to prevent.
#:   DJB_VERIFIER_MIN_KBPS     the floor that probe enforces, in KB/s. Default
#:                             50. Under it the push REFUSES, by name, instead
#:                             of stalling for an hour.
#:   DJB_VERIFIER_TUNNEL_WAIT_SECONDS  how long that probe will wait for the
#:                             SESSION CHANNEL after the SSM agent has already
#:                             said `Online`. Default 60, polled every 5. The
#:                             two are not the same readiness: `up` waits for
#:                             the agent's ping and the ssh-over-SSM channel is
#:                             a few seconds behind it, so the first probe comes
#:                             back `TargetNotConnected` with ssh's own 255 and
#:                             the wrapper used to die there — inside `cmd_push`,
#:                             BEFORE `up` had printed the instance line, so the
#:                             box was running, billing and unnamed. Past the
#:                             ceiling it is the same refusal it always was.
#:   DJB_VERIFIER_BANK_SHARD   set by a bank around each shard's `up`. It turns
#:                             the Spot→on-demand fallback below into a
#:                             REFUSAL: eight shards each answering a Spot
#:                             refusal with an on-demand box is eight boxes
#:                             against a quota an order of magnitude smaller
#:                             than the Spot one, bought without anybody
#:                             deciding to.
#:   DJB_VERIFIER_ON_DEMAND_OK the valve for the line above: `<reason>`, printed
#:                             where the launch is narrated and again in the
#:                             bank's own table. Unset, a bank shard whose Spot
#:                             request is refused is `could not launch` and the
#:                             bank refuses; a SINGLE `up` keeps the fallback
#:                             with or without it, printed either way.
#:   DJB_VERIFIER_PRICING_REGION  where to ask the Price List API what an
#:                             on-demand hour of this instance type costs, so a
#:                             fallback can print the money it is about to
#:                             spend. NO DEFAULT, for the reason every other
#:                             coordinate here has none: that API is published
#:                             in a small number of regions and a guessed one
#:                             is a call into an account's wrong endpoint.
#:                             Unset, the price prints as unknown and says so.

NAMESPACE="${DJB_DEPLOY_NAMESPACE:-}"
[ -n "$NAMESPACE" ] || die "DJB_DEPLOY_NAMESPACE is required — this deployment's namespace,
   the slug every identity, security group, image and tag here is composed from.
   There is no default: more than one product shares this AWS account, and a
   guessed namespace is a write into somebody else's resources. It is a slot in
   this environment's env file (deploy/env.staging.example)."

REGION="${DJB_VERIFIER_REGION:-}"
[ -n "$REGION" ] || die "DJB_VERIFIER_REGION is required — the region the verifier boxes
   live in. There is no default and this script never inherits the profile's:
   your own configured default region is very often a different one, and a box
   launched there is a box this census will never see and the reaper's bill
   nobody reads. Set it in the shell you run this from."

PROFILE="${DJB_VERIFIER_PROFILE:-${NAMESPACE}-verifier}"
INSTANCE_TYPE="${DJB_VERIFIER_INSTANCE_TYPE:-c7g.4xlarge}"
BAKE_TYPE="${DJB_VERIFIER_BAKE_TYPE:-c7g.2xlarge}"
TTL_HOURS="${DJB_VERIFIER_TTL_HOURS:-4}"
TTL_CAP=12
IDLE_MINUTES="${DJB_VERIFIER_IDLE_MINUTES:-30}"
VERIFIER_HOME="${DJB_VERIFIER_HOME:-${HOME}/.${NAMESPACE}/verifier}"

# --- THE CEILING, AND THE THREE PLACES IT CAN COME FROM ----------------------
#
# ENV, THEN FILE, THEN DEFAULT — and the SOURCE is carried beside the number,
# because every refusal this ceiling produces has to answer "why that number"
# and a bare `2` cannot. The file is `<DJB_VERIFIER_HOME>/ceiling`: one integer,
# written by the operator or by `ceiling <n>`, outside every checkout and shared
# by every session on this machine — which is the property the variable does not
# have. Fifteen builders in one cycle each got the default 2 and waited 20-45
# minutes at it; the variable could have raised it for exactly one shell each,
# and the inline `DJB_VERIFIER_MAX_BOXES=… ./scripts/verifier_box.sh` form costs
# an agent a permission-classifier turn on top.
#
# A MALFORMED VALUE IS EXIT 2, NOT A SILENT DEFAULT, in either place. A ceiling
# is the wall between this loop and an unbounded Spot bill: a file somebody
# fat-fingered into `1O` must stop the wrapper, never quietly become 2 (too low,
# and the wave waits for nothing) or be read as ten.
CEILING_DEFAULT=2
CEILING_FILE="${VERIFIER_HOME}/ceiling"
CEILING_FILE_VALUE=""
if [ -f "$CEILING_FILE" ]; then
    [ -r "$CEILING_FILE" ] || die "the ceiling file ${CEILING_FILE} exists and cannot be read.
   Nothing was launched. Fix its permissions, or remove it and the default
   ${CEILING_DEFAULT} applies again."
    # THE FIRST LINE, READ WITHOUT A PIPE. `… | head -c 32` is the obvious
    # spelling and this file forbids it by census: an early-exit reader after a
    # producer is a SIGPIPE 141 under the `set -o pipefail` above. `read`
    # returns 1 on a file with no trailing newline while still having filled
    # the variable, so the status is discarded and the VALUE is what is judged.
    IFS= read -r CEILING_FILE_VALUE <"$CEILING_FILE" || true
    CEILING_FILE_VALUE="$(printf '%s' "$CEILING_FILE_VALUE" | LC_ALL=C tr -d '[:space:]')"
    case "$CEILING_FILE_VALUE" in
    '' | *[!0-9]* | 0)
        die "the ceiling file ${CEILING_FILE} does not hold a positive whole number of boxes:
   '${CEILING_FILE_VALUE}'
   Nothing was launched. A ceiling that cannot be read is not a ceiling of 2 —
   it is a number nobody typed. Write one with
   \`./scripts/verifier_box.sh ceiling <n>\`, or remove the file."
        ;;
    esac
fi
if [ -n "${DJB_VERIFIER_MAX_BOXES:-}" ]; then
    case "$DJB_VERIFIER_MAX_BOXES" in
    *[!0-9]* | 0)
        die "DJB_VERIFIER_MAX_BOXES is not a positive whole number of boxes:
   '${DJB_VERIFIER_MAX_BOXES}'
   Nothing was launched. Unset it to fall through to ${CEILING_FILE} or the
   default ${CEILING_DEFAULT}."
        ;;
    esac
    MAX_BOXES="$DJB_VERIFIER_MAX_BOXES"
    MAX_BOXES_SOURCE="env"
elif [ -n "$CEILING_FILE_VALUE" ]; then
    MAX_BOXES="$CEILING_FILE_VALUE"
    MAX_BOXES_SOURCE="file"
else
    MAX_BOXES="$CEILING_DEFAULT"
    MAX_BOXES_SOURCE="default"
fi

# The three sources, one per line, with the binding one marked — printed by
# `ceiling` and by every refusal the ceiling produces, so the two can never
# describe the machine differently.
ceiling_sources() {
    local mark_env="  " mark_file="  " mark_default="  "
    case "$MAX_BOXES_SOURCE" in
    env) mark_env="->" ;;
    file) mark_file="->" ;;
    default) mark_default="->" ;;
    esac
    printf '   %s env      DJB_VERIFIER_MAX_BOXES  %s\n' \
        "$mark_env" "${DJB_VERIFIER_MAX_BOXES:-unset}"
    printf '   %s file     %s  %s\n' \
        "$mark_file" "$CEILING_FILE" \
        "$([ -n "$CEILING_FILE_VALUE" ] && printf '%s' "$CEILING_FILE_VALUE" || printf 'absent')"
    printf '   %s default  %s\n' "$mark_default" "$CEILING_DEFAULT"
}

INSTANCE_PROFILE="${NAMESPACE}-verifier-box"
GROUP_NAME="${NAMESPACE}-verifier"
SSM_SSH_DOCUMENT="AWS-StartSSHSession"
AL2023_PARAM="/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
AL2023_PINNED="${DJB_VERIFIER_AL2023_AMI:-}"
PROBE_MB="${DJB_VERIFIER_PROBE_MB:-1}"
MIN_KBPS="${DJB_VERIFIER_MIN_KBPS:-50}"
TUNNEL_WAIT_SECONDS="${DJB_VERIFIER_TUNNEL_WAIT_SECONDS:-60}"
TUNNEL_POLL_SECONDS=5
MAX_SCOPE_DEPTH="${DJB_VERIFIER_MAX_SCOPE_DEPTH:-200}"
SPOT_QUOTA_CODE="L-34B43A08"
BANK_SHARD="${DJB_VERIFIER_BANK_SHARD:-}"
ON_DEMAND_OK="${DJB_VERIFIER_ON_DEMAND_OK:-}"
PRICING_REGION="${DJB_VERIFIER_PRICING_REGION:-}"
BAKE_STALE_MINUTES=90
ONLINE_WAIT_SECONDS=300
ONLINE_POLL_SECONDS=10

# THE BAKE BOX'S READY MARKER, AND WHY ONLINE IS NOT ENOUGH. `PingStatus=Online`
# is the SSM agent's answer about the SSM agent: a systemd unit that starts at
# boot, independent of cloud-init, and reports in while `runcmd` — cloud-init's
# LAST stage — is still inside a `dnf install`. FIELD TEST 2 met the gap from
# the operator's chair: the tunnel worked, the push reached the box, and the
# box's own shell answered `bash: line 1: git-receive-pack: command not found`,
# exit 128. So `bake` waits for the marker the bake seam writes after
# everything else — and that seam writes it only after TESTING the repository
# it vouches for, so its presence is a fact about the box rather than about how
# far a script got. Through the same transport, before it pushes. The string is
# here and in deploy/verifier/bake-user-data.yaml, and the drive asserts the
# two are one. The wait is generous because it is bounded by a `dnf install` on
# a cold mirror, and a bake box that never finishes booting is terminated
# rather than left to bill.
BAKE_READY_MARKER="/run/verifier/bake-ready"
BOOTSTRAP_WAIT_SECONDS=600

# HOW LONG THE WAIT ACTUALLY TOOK, MEASURED RATHER THAN MULTIPLIED. Both waits
# below count seconds off the clock instead of counting their own polls, and
# that is not a tidiness: a loop that stops after N polls of an M-second sleep
# has waited N*(M + however long each poll itself took), and
# `wait_for_bake_bootstrap`'s poll is a full SSH attempt through an SSM tunnel
# to a box that is not answering. Its refusal used to say `600s` after waiting
# closer to 900 — and that number is the one the operator quotes when they ask
# why the box was killed. `wait_for_ssm` shares the shape; its poll is one
# cheap describe call rather than a tunnelled SSH, so the error there was a few
# percent rather than fifty, and it is measured now for the same reason.
BOOTSTRAP_WAITED=0

# THE OWNER TAG. The dispatch ledger's header names the session that is running;
# the token is read by SHAPE rather than spelled, so no product's session naming
# is baked in here.
verifier_owner() {
    local from_ledger="" matches
    if [ -z "${DJB_VERIFIER_OWNER:-}" ] && [ -r "$ROOT/docs/product/in-flight.md" ]; then
        # READ THE WHOLE, THEN SLICE — never `| head -n 1`. `head` leaves on its
        # first line and closes the pipe under `grep`, which dies of SIGPIPE
        # once it has more than the 64 KiB pipe buffer left to write; under this
        # file's `set -o pipefail` that 141 becomes the pipeline's status, and
        # under `set -e` it kills the wrapper HERE — at load, before it has
        # printed a word, over a ledger that grows every cycle. The pipeline was
        # written across two lines, which is why the gate's `pipefail_readers`
        # census (one line at a time) could not see it;
        # `scripts/tests/test_verifier_box.sh` censuses this file with the
        # continuations joined.
        matches="$(grep -oE 'session [A-Za-z0-9._-]+' "$ROOT/docs/product/in-flight.md" || true)"
        from_ledger="${matches%%$'\n'*}"
        from_ledger="${from_ledger#session }"
    fi
    printf '%s\n' "${DJB_VERIFIER_OWNER:-${from_ledger:-${USER:-unknown}@$(hostname -s 2>/dev/null || echo host)}}"
}
OWNER="$(verifier_owner)"

# THE CHECKOUT PATH IS READ, NEVER RE-SPELLED. `deploy/verifier/bake.sh` owns it
# — the recipe does not clone, it CHECKS that the wrapper pushed a tree there —
# so the push target and the recipe's expectation are the same string by
# construction rather than by two people remembering. The drive asserts the two
# agree, and a bake.sh this cannot read is exit 2 rather than a guessed path.
BAKE_SH="$ROOT/deploy/verifier/bake.sh"
verifier_checkout_path() {
    [ -r "$BAKE_SH" ] || die "cannot read ${BAKE_SH}, and it is the ONE place the box's
   checkout path is written down. Guessing it here is how the push target and the
   recipe's expectation drift apart."
    # READ THE WHOLE, THEN SLICE — never `| head -n 1`. Under `set -o pipefail` a
    # reader that leaves on the first line closes the pipe under its producer,
    # and a producer with more than the 64 KiB pipe buffer left to write dies of
    # SIGPIPE (141), which the pipeline then reports as the MATCH having failed.
    # It is green on every small file anybody drove it with and fatal on the
    # first big one. `archaeology_class_report` slices the same way for the same
    # reason, and `scripts/tests/test_pipefail_readers.sh` censuses this file.
    local user path
    user="$(sed -n 's|^BAKE_USER="\${DJB_VERIFIER_BAKE_USER:-\(.*\)}"$|\1|p' "$BAKE_SH")"
    user="${user%%$'\n'*}"
    path="$(sed -n 's|^BAKE_CHECKOUT="\${DJB_VERIFIER_CHECKOUT:-\(.*\)}"$|\1|p' "$BAKE_SH")"
    path="${path%%$'\n'*}"
    { [ -n "$user" ] && [ -n "$path" ]; } || die "could not read the checkout knobs out of
   ${BAKE_SH}. Its BAKE_USER/BAKE_CHECKOUT defaults are the contract this script
   reads; if their shape changed, this is the line that must change with them."
    printf '%s\n' "${path//\$\{BAKE_USER\}/$user}"
}
# verifier_park_branch — the branch the bake parks the box's checkout on, read
# from the ONE place it is written down. A SECOND READER and not a second
# answer, exactly as `verifier_checkout_path` is: the name matters here because
# clearing the box's refs before a first push deletes it, and a name typed here
# that drifted from the recipe's would delete nothing and leave the failure in
# place — silently, because a `update-ref -d` on a ref that is not there
# succeeds.
verifier_park_branch() {
    [ -r "$BAKE_SH" ] || die "cannot read ${BAKE_SH}, and it is the ONE place the box's parking
   branch is written down."
    # Read whole, slice — the reason is at `verifier_checkout_path`.
    local park
    park="$(sed -n 's|^BAKE_PARK_BRANCH="\(.*\)"$|\1|p' "$BAKE_SH")"
    park="${park%%$'\n'*}"
    [ -n "$park" ] || die "could not read BAKE_PARK_BRANCH out of ${BAKE_SH}. Its shape is the
   contract this script reads; if it changed, this is the line that changes with it."
    printf '%s\n' "$park"
}

verifier_box_user() {
    [ -r "$BAKE_SH" ] || die "cannot read ${BAKE_SH}"
    # Read whole, slice — the reason is one function up.
    local user
    user="$(sed -n 's|^BAKE_USER="\${DJB_VERIFIER_BAKE_USER:-\(.*\)}"$|\1|p' "$BAKE_SH")"
    printf '%s\n' "${user%%$'\n'*}"
}

# --- the one boundary above the vendor CLI -----------------------------------
# Every call carries BOTH coordinates explicitly. A call that inherits either is
# a call against the wrong account or the wrong region, and both succeed.
aws_q() { aws --region "$REGION" --profile "$PROFILE" "$@"; }

# The owner's two commands, printed wherever the credential is the thing that is
# missing. Both are in the tree; neither is something this script can do.
print_owner_commands() {
    echo "   The identity these boxes need is the owner's to mint, once:"
    echo ""
    echo "     DJB_DEPLOY_NAMESPACE=${NAMESPACE} DJB_VERIFIER_ACCOUNT=<12-digit account> DJB_VERIFIER_REGION=${REGION} \\"
    echo "       ./deploy/iam/verifier_bootstrap.sh --confirm"
    echo "     aws configure --profile ${PROFILE}"
    echo ""
    echo "   docs/runbooks/deploy.md's verifier-box section is the same two commands."
}

# --- the three preflight walls -----------------------------------------------
#
# ALL THREE REFUSE BEFORE ANYTHING IS LAUNCHED, and that order is the point: a
# refusal that launches first and refuses second is the arrow-key money
# `deploy/provision.sh` refuses one door over.
require_profile() {
    aws_q configure list >/dev/null 2>&1 && return 0
    echo "!! verifier_box: no AWS profile '${PROFILE}' on this machine." >&2
    print_owner_commands
    exit 2
}

require_plugin() {
    command -v session-manager-plugin >/dev/null 2>&1 && return 0
    die "session-manager-plugin is not on PATH, and every command here tunnels
   through it. It is a TOOL, not a credential, so it is yours to install:

     brew install --cask session-manager-plugin"
}

# The newest self-owned image of THIS namespace. `None` is what the CLI prints
# for an empty query, and it is a refusal rather than a value.
newest_image() {
    aws_q ec2 describe-images --owners self \
        --filters "Name=tag:djb:role,Values=verifier-image" \
        "Name=tag:djb:namespace,Values=${NAMESPACE}" \
        --query 'sort_by(Images,&CreationDate)[-1].ImageId' --output text 2>/dev/null || true
}

require_image() {
    local image
    image="$(newest_image)"
    case "$image" in
    "" | None | null)
        die "no verifier image in ${REGION} for namespace '${NAMESPACE}'. Bake one first:

     scripts/verifier_box.sh bake

   It takes about twenty minutes and costs about a dime; every launch after it
   is a boot and a push.

   AN IMAGE THAT EXISTS AND IS NOT TAGGED LOOKS EXACTLY LIKE THIS, and it has
   happened: the lookup above filters on djb:role and djb:namespace, and a
   capture whose tags the policy refused produces a working image that matches
   neither. If a bake printed an image id and said its tags were refused, launch
   from it by hand — 'up --for <rung> --image-id <ami>' — and fix the policy
   (deploy/iam/verifier_bootstrap.sh) before the next bake."
        ;;
    esac
    printf '%s\n' "$image"
}

# NAME AND STATE IN ONE CALL, because they answer one question: is this image
# usable, and what is it. `None` is what the CLI prints for an empty query and
# it is a refusal rather than a value.
image_name_and_state() {
    aws_q ec2 describe-images --image-ids "$1" \
        --query 'Images[0].[Name,State]' --output text 2>/dev/null || true
}

# An image named by hand — from a bake whose tags were refused, or a base a
# field test wants pinned. It WINS over the tag lookup, and it is checked:
# `run-instances` on an image that is still `pending` fails in the API's own
# words several seconds after the launch, where this fails immediately in ours.
require_named_image() {
    local image="$1" row name state
    row="$(image_name_and_state "$image")"
    name="${row%%	*}"
    state="${row##*	}"
    case "$state" in
    available) ;;
    "" | None | null)
        die "${image} is not an image this credential can see in ${REGION}. Nothing was
   launched. Check the id, the region and the namespace's profile."
        ;;
    *)
        die "${image} is '${state}', not 'available'. Nothing was launched: an image that is
   still being captured has no root volume to boot from, and the API's refusal
   arrives seconds AFTER the launch call rather than before it. A capture
   normally reaches 'available' in a few minutes — 'aws ec2 describe-images
   --image-ids ${image}' is the thing to watch."
        ;;
    esac
    # THE NARRATION GOES TO STDERR AND THE ID TO STDOUT, because this
    # function's stdout IS its return value — the caller does
    # `image="$(require_named_image …)"`, and a `say` on stdout becomes part of
    # the image id. It did, once, here: `--image-id ami-explicit` launched an
    # instance whose `--image-id` argument was a whole sentence.
    say "image      ${image}  ${name:-<unnamed>}  (named on the command line; the tag lookup was not used)" >&2
    printf '%s\n' "$image"
}

# THE API'S OWN RULE, ASSERTED WHERE IT IS CHEAP. `create-image`'s name and
# description are 7-bit ASCII: one accented character, one smart quote, one
# em-dash and the whole call is refused — over a bake box that is finished and
# about to be thrown away. Everything composed into those strings comes from
# two places, the deployment namespace and a git sha, and only the first can
# carry anything but hex. So the namespace is checked BEFORE a box is launched
# and the composed strings again before the call, and the refusal shows the
# offending text rather than describing it.
#
# `tr -d` UNDER LC_ALL=C, AND NOT A BRACKET RANGE. `case "$v" in *[!$'\x20'-$'\x7e']*)`
# is the obvious spelling and it is wrong here: a bracket RANGE inside a shell
# pattern is resolved by the current locale's collation, and under this
# machine's default one it matched every string given to it, ASCII included —
# a guard that refuses everything is as useless as one that refuses nothing,
# and it reads correct. Deleting the printable set and asking what is LEFT has
# no collation in it, and it also catches the control characters a bracket
# range aimed at ASCII would have let through.
ascii_only() {
    local what="$1" value="$2" left
    left="$(printf '%s' "$value" | LC_ALL=C tr -d '\040-\176' || true)"
    case "$left" in
    ?*)
        die "the ${what} is not ASCII, and EC2's create-image refuses a name or a description
   that is not: '${value}'
   Nothing was launched and nothing was captured. Every character in an image's
   name and description comes from this deployment's namespace
   (DJB_DEPLOY_NAMESPACE) and a git sha; the sha is hex, so the namespace is
   where this came from. A namespace is a slug — letters, digits and hyphens —
   in every other place it is used too (the profile, the security group, the
   instance profile and the tags)."
        ;;
    esac
}

# --- time, in the one spelling the tags and the reaper both read --------------
#
# THE ARITHMETIC IS HERE AND `date` IS ASKED FOR EXACTLY ONE THING: the current
# epoch second. `deploy/verifier/idle_reaper.sh` settled this shape for the
# same problem one layer down, and its header carries the argument in full —
# `date -d` is GNU and `date -j -f` is BSD, and a script that parses its own
# instants with whichever one the machine happens to have is a script that
# silently stops parsing the day the machine changes. It also makes the parse
# DRIVABLE rather than a property of the box's coreutils, which is what lets
# the drive beside this file check both directions against a second
# implementation.
#
# AND IT REPLACES FOUR INLINE PYTHON PROGRAMS, which is the house rule this
# pays: a Python this repository ships runs on THIS CHECKOUT's interpreter
# (`checkout_python`, scripts/gate_refuse.sh), because an interpreter off PATH
# is some other environment's — 3.12 or 3.13 on this Mac and the system's 3.9
# on Amazon Linux 2023, which is where the first off-box gate run died. This
# wrapper cannot reach `checkout_python`: it runs from a laptop, before any
# venv is guaranteed, and sourcing the gate's refusal library into it would
# make a missing `.venv` the reason a box could not be taken DOWN. So the
# third answer, and it is this repository's own: no interpreter at all.

# days_from_civil <y> <m> <d> — days since 1970-01-01 on stdout. The standard
# proleptic-Gregorian conversion, shifted so 1970-01-01 is day 0.
days_from_civil() {
    local y="$1" m="$2" d="$3" yy era yoe doy doe mp
    yy=$y
    # `if`, never `[ … ] && …`: an AND-list whose left half is false returns 1,
    # and under `set -e` that would end the wrapper here — the same defect the
    # reaper's copy of this arithmetic records against its own March-to-December
    # instants.
    if [ "$m" -le 2 ]; then yy=$((y - 1)); fi
    if [ "$yy" -ge 0 ]; then era=$((yy / 400)); else era=$(((yy - 399) / 400)); fi
    yoe=$((yy - era * 400))
    if [ "$m" -gt 2 ]; then mp=$((m - 3)); else mp=$((m + 9)); fi
    doy=$(((153 * mp + 2) / 5 + d - 1))
    doe=$((yoe * 365 + yoe / 4 - yoe / 100 + doy))
    printf '%s\n' $((era * 146097 + doe - 719468))
}

# civil_from_days <days since 1970-01-01> — the inverse, into CIVIL_Y/M/D.
CIVIL_Y=0
CIVIL_M=0
CIVIL_D=0
civil_from_days() {
    local z=$(($1 + 719468)) era doe yoe doy mp y m d
    if [ "$z" -ge 0 ]; then era=$((z / 146097)); else era=$(((z - 146096) / 146097)); fi
    doe=$((z - era * 146097))
    yoe=$(((doe - doe / 1460 + doe / 36524 - doe / 146096) / 365))
    y=$((yoe + era * 400))
    doy=$((doe - (365 * yoe + yoe / 4 - yoe / 100)))
    mp=$(((5 * doy + 2) / 153))
    d=$((doy - (153 * mp + 2) / 5 + 1))
    if [ "$mp" -lt 10 ]; then m=$((mp + 3)); else m=$((mp - 9)); fi
    if [ "$m" -le 2 ]; then y=$((y + 1)); fi
    CIVIL_Y=$y
    CIVIL_M=$m
    CIVIL_D=$d
}

iso_at() {
    local e="$1" days secs
    case "$e" in '' | *[!0-9]*)
        printf '\n'
        return 0
        ;;
    esac
    days=$((e / 86400))
    secs=$((e % 86400))
    civil_from_days "$days"
    printf '%04d-%02d-%02dT%02d:%02d:%02dZ\n' \
        "$CIVIL_Y" "$CIVIL_M" "$CIVIL_D" \
        $((secs / 3600)) $((secs % 3600 / 60)) $((secs % 60))
}

epoch_of_iso() {
    local iso="$1" y m d hh mm ss days
    case "$iso" in
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z) ;;
    *)
        printf '\n'
        return 0
        ;;
    esac
    # `10#` ON EVERY FIELD. Bash reads a leading zero as octal, so `08` and
    # `09` are arithmetic syntax errors and every August and September instant
    # would come back unparsable — which is exactly the bug the reaper's own
    # copy of this function records against itself.
    y=$((10#${iso:0:4}))
    m=$((10#${iso:5:2}))
    d=$((10#${iso:8:2}))
    hh=$((10#${iso:11:2}))
    mm=$((10#${iso:14:2}))
    ss=$((10#${iso:17:2}))
    if [ "$m" -lt 1 ] || [ "$m" -gt 12 ] || [ "$d" -lt 1 ] || [ "$d" -gt 31 ] ||
        [ "$hh" -gt 23 ] || [ "$mm" -gt 59 ] || [ "$ss" -gt 60 ]; then
        printf '\n'
        return 0
    fi
    days="$(days_from_civil "$y" "$m" "$d")"
    printf '%s\n' $((days * 86400 + hh * 3600 + mm * 60 + ss))
}
now_epoch() { date +%s; }

# The stamp `say` prefixes every line with, in UTC — the zone the `djb:expires`
# tag, the census and `iso_at` above already speak. Two zones in one transcript
# is a subtraction nobody gets right at 2am, and the operator reading these
# lines is reading them beside a census that is already in UTC.
stamp_of() {
    local iso
    iso="$(iso_at "$1")"
    printf '%s\n' "${iso:11:8}"
}
now_stamp() { stamp_of "$(now_epoch)"; }

# --- the phases, measured ----------------------------------------------------
# A stamp on every line lets a reader SUBTRACT; the summary does the subtraction
# for them, and does it on the way out of a failure as well as a success —
# which is the run where nobody has the patience to subtract. One ordered
# ledger, appended as each phase closes, plus whatever was in flight when the
# wrapper stopped, marked as such: the incomplete phase is the one the operator
# has to go and look at.
PHASE_LOG=""
PHASE_NAME=""
PHASE_START=""
PHASE_ORIGIN=""

# phase_begin <name> — closes the phase in flight and opens a new one.
phase_begin() {
    phase_end
    PHASE_NAME="$1"
    PHASE_START="$(now_epoch)"
    [ -n "$PHASE_ORIGIN" ] || PHASE_ORIGIN="$PHASE_START"
}

phase_end() {
    [ -n "$PHASE_NAME" ] || return 0
    PHASE_LOG="${PHASE_LOG}${PHASE_NAME} $(($(now_epoch) - PHASE_START))s · "
    PHASE_NAME=""
    PHASE_START=""
}

# ONCE, wherever it is called from. A success prints it just before the answer
# line — the wrapper's last line stays the image id, which is what a caller
# scrapes — and every failure gets it from the teardown on the way out; the
# guard is what lets both exist without a run printing two summaries.
PHASE_SUMMARISED=""
phase_summary() {
    [ -z "$PHASE_SUMMARISED" ] || return 0
    local line="$PHASE_LOG"
    if [ -n "$PHASE_NAME" ]; then
        line="${line}${PHASE_NAME} $(($(now_epoch) - PHASE_START))s (incomplete) · "
    fi
    [ -n "$line" ] || return 0
    PHASE_SUMMARISED=1
    say "phases  ${line}total $(($(now_epoch) - PHASE_ORIGIN))s"
}

# --- the transport -----------------------------------------------------------
proxy_command() {
    printf 'aws ssm start-session --target %%h --document-name %s --parameters portNumber=%%p --profile %s --region %s\n' \
        "$SSM_SSH_DOCUMENT" "$PROFILE" "$REGION"
}

box_dir() { printf '%s/%s\n' "$VERIFIER_HOME" "$1"; }

box_key() { printf '%s/id_ed25519\n' "$(box_dir "$1")"; }

box_rung() {
    local f
    f="$(box_dir "$1")/rung"
    [ -r "$f" ] && cat "$f" || echo "unknown"
}

# ssh_to <id> <remote command...> — the exit status is the REMOTE command's,
# passed through untouched. Every call touches the box's activity marker first,
# because that mtime is the only thing standing between an idle reaper and a box
# somebody is using through short synchronous sessions.
ssh_to() {
    local id="$1"
    shift
    local key
    key="$(box_key "$id")"
    [ -r "$key" ] || die "no private key for ${id} under ${VERIFIER_HOME}. Either this box was
   brought up by another machine, or 'down' has already removed it. Either way
   there is no way in from here."
    ssh -i "$key" \
        -o "ProxyCommand=$(proxy_command)" \
        -o ServerAliveInterval=30 \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        -o LogLevel=ERROR \
        "$(verifier_box_user)@${id}" \
        -- "touch /run/verifier/last-activity 2>/dev/null || true; $*"
}

# A box AWS has taken back is not a box that failed to answer. `run` reads the
# instance's own state rather than inferring it from a hung connection, so the
# verifier reports `stuck on: box reclaimed` and the PM re-ups — never a red
# verdict on a tree nobody measured.
refuse_if_reclaimed() {
    local id="$1" state reason
    state="$(aws_q ec2 describe-instances --instance-ids "$id" \
        --query 'Reservations[0].Instances[0].State.Name' --output text 2>/dev/null || true)"
    case "$state" in
    running | pending | "") return 0 ;;
    esac
    reason="$(aws_q ec2 describe-instances --instance-ids "$id" \
        --query 'Reservations[0].Instances[0].StateReason.Code' --output text 2>/dev/null || true)"
    case "$reason" in
    *SpotInstanceTermination*)
        # THE SPOT SERVICE'S OWN STATUS CODE, ON THE SAME LINE. `StateReason`
        # says SOMETHING took the box back; only the request's status says
        # WHICH thing, and the difference decides what the caller does next —
        # `instance-terminated-no-capacity` is the market and the answer is
        # another zone, `instance-terminated-by-price` is the bid, and
        # `instance-terminated-by-user` is a hand and not a reclaim at all. A
        # bank that retried every reclaim identically would re-launch into the
        # zone that has just said no. It is APPENDED to the line that already
        # existed, never inserted, so every reader that parsed
        # `box reclaimed (spot) <id>` parses this one.
        echo "box reclaimed (spot) ${id} status $(spot_status_of "$id")"
        die "the box was reclaimed by AWS mid-flight. Nothing on it is retrievable.
   The verdict is LOST, never red: report 'stuck on: box reclaimed' and let the
   PM bring another one up."
        ;;
    esac
    echo "box gone (${state}) ${id}"
    die "the box is ${state} (${reason:-no reason given}). Nothing was attempted."
}

# --- tags, read back --------------------------------------------------------
# One describe, one query per field, because a shim that answers a query is a
# shim that answers the same shape the real CLI does.
tag_of() {
    aws_q ec2 describe-instances --instance-ids "$1" \
        --query "Reservations[0].Instances[0].Tags[?Key=='$2'].Value | [0]" \
        --output text 2>/dev/null || true
}

# api_line <captured output> — the first line of it that says anything.
#
# THE AWS CLI WRITES ITS ERRORS WITH A LEADING BLANK LINE, and that was not a
# guess: measured on v2 in this account on 2026-09-21, a refused
# `describe-instances` answers `\naws: [ERROR]: An error occurred
# (InvalidInstanceID.Malformed) …`. Every refusal here that promised to quote
# the API's own words took `${out%%$'\n'*}` — the FIRST line — and printed
# `could not look at i-…: ` with nothing after the colon. A refusal whose whole
# value is the API's sentence, printing no sentence, is worse than the silence
# it replaced: it looks like the API said nothing.
#
# A LINE OF ONLY WHITESPACE IS NOT A LINE, and an INDENTED one is: the CLI
# wraps long messages, and skipping every indented line would skip the message
# on the day the first word moves.
api_line() {
    local l
    while IFS= read -r l; do
        [ -n "$(printf '%s' "$l" | tr -d '[:space:]')" ] || continue
        printf '%s' "$l"
        return 0
    done <<<"$1"
    printf ''
}

# --- the zones, and the subnets that reach them -----------------------------
#
# WHY THERE IS A ZONE AXIS AT ALL. `run-instances` with no `--subnet-id` lets
# EC2 pick the Availability Zone, and EC2 picks the same one for eight shards
# fired within a second of each other — so a bank meets ONE zone's Spot
# capacity and a capacity refusal there is a capacity refusal for the whole
# bank. Spreading the shards is the cheapest thing that exists between a bank
# and `InsufficientInstanceCapacity` (EC2 Fleet's `capacity-optimized` is the
# expensive one, rejected in the P21 team-B plan § 5), and `--subnet-id` is how
# a zone is asked for: there is no `--availability-zone` on `run-instances`.
#
# THE VPC IS THE SECURITY GROUP'S, NEVER THE ACCOUNT'S DEFAULT. Everything this
# wrapper launches carries `${GROUP_NAME}`, and a security group belongs to
# exactly one VPC; a subnet in another VPC is a launch EC2 refuses. So the one
# question underneath all three readers below is "what VPC is our group in",
# asked once per call site and never guessed.
#
# AND THEY ARE THREE FUNCTIONS OVER ONE QUESTION rather than three filters that
# can disagree: `zones` prints what `zones_of_vpc` answers, the launch picks
# out of the same list, and the ring's next zone is an index into it. A bank
# that spread shards across a list one reader computed and another checked
# would be a bank whose two answers drift the day a subnet is added.

# vpc_of_group — the VpcId of the security group every box carries, on stdout.
# Empty when it could not be read; the caller decides whether that is fatal.
vpc_of_group() {
    local vpc
    vpc="$(aws_q ec2 describe-security-groups \
        --filters "Name=group-name,Values=${GROUP_NAME}" \
        --query 'SecurityGroups[0].VpcId' --output text 2>/dev/null || true)"
    vpc="${vpc%%$'\n'*}"
    case "$vpc" in "" | None | null) printf '' ;; *) printf '%s' "$vpc" ;; esac
}

# zones_of_vpc <vpc> — one Availability Zone per line, sorted, each of which
# this account has a subnet in. SORTED AND DE-DUPLICATED HERE, so "the next
# zone" is a well-defined thing and two runs of a bank spread the same way.
#
# A ZONE WITH NO SUBNET IS NOT A ZONE WE CAN LAUNCH IN, which is why the
# subject is `describe-subnets` and not `describe-availability-zones`: the
# latter answers what the REGION has and would hand the ring a zone the launch
# then cannot reach.
zones_of_vpc() {
    local raw
    raw="$(aws_q ec2 describe-subnets --filters "Name=vpc-id,Values=$1" \
        --query 'Subnets[].AvailabilityZone' --output text 2>/dev/null || true)"
    [ -n "$(printf '%s' "$raw" | tr -d '[:space:]')" ] || return 0
    printf '%s' "$raw" | tr '[:space:]' '\n' | grep -v '^$' | sort -u
}

# subnet_in_zone <vpc> <az> — one subnet id in that zone, or empty.
subnet_in_zone() {
    local s
    s="$(aws_q ec2 describe-subnets \
        --filters "Name=vpc-id,Values=$1" "Name=availability-zone,Values=$2" \
        --query 'Subnets[0].SubnetId' --output text 2>/dev/null || true)"
    s="${s%%$'\n'*}"
    case "$s" in "" | None | null) printf '' ;; *) printf '%s' "$s" ;; esac
}

# next_zone_after <vpc> <az> — the zone after <az> in the sorted list, wrapping
# to the first. Empty when the list has fewer than two members, or when <az> is
# not in it at all: a ring with one zone has no "next", and refusing to invent
# one is what keeps the retry below honest about having tried somewhere else.
next_zone_after() {
    local vpc="$1" az="$2" z first="" prev_matched="" n=0
    while IFS= read -r z; do
        [ -n "$z" ] || continue
        n=$((n + 1))
        [ -n "$first" ] || first="$z"
        if [ -n "$prev_matched" ]; then
            printf '%s' "$z"
            return 0
        fi
        [ "$z" = "$az" ] && prev_matched=1
    done <<<"$(zones_of_vpc "$vpc")"
    [ "$n" -gt 1 ] || return 0
    [ -n "$prev_matched" ] || return 0
    printf '%s' "$first"
}

# spot_status_of <id> — what the Spot service says about the request that
# bought this box, as `<code>: <message>`, on stdout.
#
# IT NEVER REFUSES AND IT NEVER GUESSES. Its one caller is a refusal that is
# already deciding something else, so a `die` here would replace a reclaim's
# own sentence with a sentence about reading a status. Three answers it can
# give instead, and each of them is a different fact: a CODE, which is the
# thing worth reading (`instance-terminated-no-capacity` is a market event and
# `instance-terminated-by-user` is somebody's hand); `unrecorded`, when the
# launch wrote no request id — every on-demand box, and every box launched by
# a wrapper older than this line; and `unreadable`, when the call itself was
# refused, which today is the ordinary answer because
# `ec2:DescribeSpotInstanceRequests` reaches the ops policy only when the OWNER
# publishes a new default version by hand (deploy/iam/verifier-ops-policy.json).
spot_status_of() {
    local id="$1" sir out rc=0 code msg
    sir="$(cat "$(box_dir "$id")/spot-request" 2>/dev/null || true)"
    sir="${sir%%$'\n'*}"
    case "$sir" in
    "" | None | null)
        printf 'unrecorded (no spot request id was written for this box at launch)'
        return 0
        ;;
    esac
    set +e
    out="$(aws_q ec2 describe-spot-instance-requests --spot-instance-request-ids "$sir" \
        --query 'SpotInstanceRequests[0].Status.[Code,Message]' --output text 2>&1)"
    rc=$?
    set -e
    if [ "$rc" != "0" ]; then
        case "$out" in
        *UnauthorizedOperation* | *AccessDenied*)
            printf 'unreadable (ec2:DescribeSpotInstanceRequests not in the ops policy'"'"'s LIVE version)'
            ;;
        *) printf 'unreadable (%s)' "$(api_line "$out")" ;;
        esac
        return 0
    fi
    out="${out%%$'\n'*}"
    code="${out%%	*}"
    msg="${out#*	}"
    [ "$msg" != "$out" ] || msg=""
    case "$code" in
    "" | None | null)
        printf 'unreadable (the API named no status code for %s)' "$sir"
        return 0
        ;;
    esac
    case "$msg" in
    "" | None | null) printf '%s' "$code" ;;
    *) printf '%s: %s' "$code" "$msg" ;;
    esac
}

# THE SYNOPSIS IS DERIVED, NEVER A LINE RANGE. `sed -n '15,25p'` had already
# silently dropped `bake` — the list grew and the range did not — and every
# subcommand added after it would have pushed another one out of the help while
# the dispatcher below kept accepting it. The subject is now the synopsis lines
# themselves, which cannot drift from themselves, and the drive censuses them
# against the dispatcher's own case arms.
usage() {
    echo "verifier_box.sh — one throwaway EC2 machine per verification, brought up,"
    echo "  pushed to, run on, and taken down, from this laptop."
    awk '/^#   verifier_box\.sh /{ sub(/^#  /, ""); print }' "${BASH_SOURCE[0]}"
    exit 2
}

# =============================================================================
# the warm pool
# =============================================================================
#
# WHY THERE IS ONE AT ALL. A cold `up` is about 115 s of launch plus about
# 50 s of the box's own bootstrap before the first byte of the tree moves, and
# a bank on eight boxes pays that eight times in parallel but still pays it.
# A box that is already running and already bootstrapped is claimed in one
# `mkdir` and one `create-tags`, and the push starts immediately.
#
# THE POOL IS PER MACHINE BY CONSTRUCTION, and that is not a policy — it is the
# key. The private half of a box's ed25519 pair is generated on the machine
# that launched it and never leaves (the header's WHAT NEVER LANDS ON A BOX
# paragraph), so a box launched from another laptop cannot be reached from this
# one at all. `djb:owner` filters the listing and the presence of a key under
# this machine's `VERIFIER_HOME` is the hard wall underneath it. A cross-machine
# pool was rejected for exactly that reason: the key would have to travel.
#
# THE CLAIM'S LOCK IS `mkdir`, AND THE TAG IS THE RECORD. Two `up`s on one
# machine race; `mkdir` either makes the directory or it does not and there is
# no window between the two — the same primitive, for the same reason, as
# `gate_lease.sh`'s acquire. A claim by tag alone would be a read followed by a
# write with no compare-and-set, which is two winners.

# warm_pool_rows — the ONE answer to what is in the pool, read by `pool`, by
# `up`'s claim and by `census`. Three readers of one question, never three
# filters that can quietly disagree about which boxes are ours and idle.
#
# FIVE CONDITIONS AND EVERY ONE IS LOAD-BEARING: our role; our namespace
# (another product's boxes are not ours to claim or to trim); OUR OWNER
# (another session's warm box is another session's, and its key is on another
# machine anyway); `djb:for=pool` — a box that has been claimed is RE-TAGGED
# with what it was claimed for, so it leaves the pool by that act and the
# census cannot list it as available; and running-or-pending.
#
# SORTED BY LAUNCH TIME BY THE API, so "oldest first" is the order the rows
# arrive in rather than a second sort somewhere else that can disagree with
# this one.
#
# Rows on stdout: <id> TAB <launch time> TAB <ami> TAB <type> TAB <price tag>.
warm_pool_rows() {
    aws_q ec2 describe-instances \
        --filters "Name=tag:djb:role,Values=verifier" \
        "Name=tag:djb:namespace,Values=${NAMESPACE}" \
        "Name=tag:djb:owner,Values=${OWNER}" \
        "Name=tag:djb:for,Values=pool" \
        "Name=instance-state-name,Values=pending,running" \
        --query 'sort_by(Reservations[].Instances[],&LaunchTime)[].[InstanceId,LaunchTime,ImageId,InstanceType,Tags[?Key==`djb:price`].Value|[0]]' \
        --output text 2>/dev/null || true
}

# pool_price_sum <price...> — the hourly cost of a set of boxes on stdout,
# added up from the `djb:price` tags they were LAUNCHED with and NEVER from
# today's market. The number an operator needs is what these boxes are
# costing; a Spot price looked up now is what a NEW one would cost, and on a
# moving market those are different numbers. A tag that is not a number is
# counted as unknown by the caller and said out loud, never as zero.
pool_price_sum() {
    awk 'BEGIN {
        s = 0
        for (i = 1; i < ARGC; i++)
            if (ARGV[i] ~ /^[0-9]+(\.[0-9]+)?$/) s += ARGV[i]
        printf "%.4f\n", s
    }' "$@"
}

# claim_warm_box <image> <rung> — claim one warm box for <rung>, or say why
# each candidate was passed over. Sets CLAIMED_ID (empty when none was taken)
# and CLAIMED_TYPE. Narrates on stdout and never refuses: no warm box is the
# ordinary case, not a failure.
CLAIMED_ID=""
CLAIMED_TYPE=""
claim_warm_box() {
    local image="$1" rung="$2" rows id launched ami type price age now
    CLAIMED_ID=""
    CLAIMED_TYPE=""
    rows="$(warm_pool_rows)"
    if [ -z "$(printf '%s' "$rows" | tr -d '[:space:]')" ]; then
        echo "no warm box — launching"
        return 0
    fi
    now="$(now_epoch)"
    while IFS=$'\t' read -r id launched ami type price; do
        [ -n "$id" ] || continue
        # THE IMAGE HAS TO MATCH, and a mismatch is a SKIP rather than a
        # refusal: a box on an older image is still a valid measurement —
        # `setup.sh` resyncs the checkout — but it is slower, and a claim
        # exists to be the fast path. The skip names both images so the
        # operator can see the pool has gone stale behind a bake.
        if [ "$ami" != "$image" ]; then
            echo "skipped ${id}: image ${ami} ≠ ${image}"
            continue
        fi
        # AND THE KEY HAS TO BE HERE. This is the per-machine wall: a box
        # launched from another laptop has its private half there and there is
        # no way into it from this one.
        if [ ! -r "$(box_key "$id")" ]; then
            echo "skipped ${id}: no key on this machine"
            continue
        fi
        if ! mkdir "$(box_dir "$id")/claim" 2>/dev/null; then
            echo "skipped ${id}: already claimed on this machine"
            continue
        fi
        # THE TAG IS THE RECORD AND THE DIRECTORY IS THE LOCK, so a tagging
        # failure is a note rather than an unwind: the box is claimed either
        # way on this machine, and what is lost is only the census's ability
        # to say what it was claimed for.
        aws_q ec2 create-tags --resources "$id" \
            --tags "Key=djb:for,Value=${rung}" >/dev/null 2>&1 ||
            say "           NOTE: could not tag ${id} with djb:for=${rung}; it IS claimed on this machine (the directory is the lock) but the census will still call it warm." >&2
        printf '%s\n' "$rung" >"$(box_dir "$id")/rung"
        age="$(age_minutes "$launched" "$now")"
        echo "claimed ${id} (warm, ${age}m)"
        CLAIMED_ID="$id"
        CLAIMED_TYPE="$type"
        return 0
    done <<<"$rows"
    echo "no warm box — launching"
    return 0
}

# =============================================================================
# the ceiling, read and written
# =============================================================================
#
# `ceiling` with no argument PRINTS; `ceiling <n>` WRITES the file and then
# prints. One subcommand for both because the two questions are the same
# question — "what is the ceiling here, and where does it come from" — and a
# write that did not show its result is a write the operator has to verify with
# a second command.
#
# IT NEVER BLOCKS ON AWS. The quota is a courtesy line: it is the wall the
# ceiling is an estimate of, so it belongs beside the number, but an expired
# credential, a missing profile or a policy that does not grant
# `service-quotas:GetServiceQuota` must not stop an operator reading or setting
# a local integer. Could-not-look prints `unknown` and says nothing else.
cmd_ceiling() {
    local want=""
    while [ "$#" -gt 0 ]; do
        case "$1" in
        -h | --help) usage ;;
        -*) die "unknown argument '$1' to ceiling: it takes a whole number of boxes, or nothing" ;;
        *)
            [ -z "$want" ] || die "ceiling takes at most one number, got '${want}' and '$1'"
            want="$1"
            shift
            ;;
        esac
    done

    if [ -n "$want" ]; then
        case "$want" in
        *[!0-9]* | 0)
            die "ceiling takes a positive whole number of boxes, got '${want}'.
   ${CEILING_FILE} was not written."
            ;;
        esac
        mkdir -p "$VERIFIER_HOME" ||
            die "could not make ${VERIFIER_HOME} to hold the ceiling file"
        printf '%s\n' "$want" >"$CEILING_FILE" ||
            die "could not write ${CEILING_FILE}"
        echo "wrote ${CEILING_FILE} = ${want}"
        # The in-process state follows the file, so the print below is the
        # machine as it now is rather than as it was when this process started.
        CEILING_FILE_VALUE="$want"
        if [ "$MAX_BOXES_SOURCE" != "env" ]; then
            MAX_BOXES="$want"
            MAX_BOXES_SOURCE="file"
        fi
    fi

    echo "ceiling ${MAX_BOXES} (${MAX_BOXES_SOURCE})"
    ceiling_sources

    local quota="unknown" q="" rc=0
    set +e
    q="$(aws_q service-quotas get-service-quota --service-code ec2 \
        --quota-code "$SPOT_QUOTA_CODE" --query 'Quota.Value' --output text 2>/dev/null)"
    rc=$?
    set -e
    if [ "$rc" = "0" ]; then
        case "$q" in
        '' | None | null) ;;
        *[0-9]*) quota="$q" ;;
        esac
    fi
    printf '      quota    %s  %s  (Spot vCPU in %s; this type is %s)\n' \
        "$SPOT_QUOTA_CODE" "$quota" "$REGION" "$INSTANCE_TYPE"
    if [ "$quota" = "unknown" ]; then
        echo "               could not look — the local ceiling above still stands"
    fi
}

cmd_pool() {
    local want="" idle="$IDLE_MINUTES"
    while [ "$#" -gt 0 ]; do
        case "$1" in
        --want)
            want="${2:-}"
            shift 2 || die "--want takes a box count"
            ;;
        --idle)
            idle="${2:-}"
            shift 2 || die "--idle takes minutes"
            ;;
        *) die "unknown argument '$1' to pool" ;;
        esac
    done
    [ -n "$want" ] || die "pool needs --want <N>: how many warm boxes to keep. 'pool --want 0'
   is how the pool is emptied."
    case "$want" in *[!0-9]*) die "--want takes a whole number of boxes, got '${want}'" ;; esac
    case "$idle" in '' | *[!0-9]*) die "--idle takes whole minutes, got '${idle}'" ;; esac
    # THE CEILING IS THE FIRST THING AND IT COSTS NOTHING TO CHECK, which is
    # the whole point: `require_headroom` refuses AFTER a describe, and a
    # ceiling discovered after a launch is money rather than a refusal. This
    # one is arithmetic against a knob, so it can go before the credential is
    # even resolved.
    [ "$want" -le "$MAX_BOXES" ] ||
        die "pool --want ${want} is above the ceiling of ${MAX_BOXES} (${MAX_BOXES_SOURCE}). Nothing was
   asked of AWS and nothing was launched. Where the ${MAX_BOXES} came from,
   '->' the one that bound:
$(ceiling_sources)
   The ceiling stands for the Spot vCPU quota (${SPOT_QUOTA_CODE}) divided by this
   instance type; raise it only after the quota is raised —
   \`./scripts/verifier_box.sh ceiling <n>\` writes the file, DJB_VERIFIER_MAX_BOXES
   raises it for this shell alone. Nothing here asked AWS for the quota: this
   refusal is arithmetic and stays free."

    require_profile
    require_plugin

    local rows warm=0 launched=0 trimmed=0
    local -a ids=() launches=() amis=() types=() prices=() keep_prices=()
    rows="$(warm_pool_rows)"
    if [ -n "$(printf '%s' "$rows" | tr -d '[:space:]')" ]; then
        local id launched_at ami type price
        while IFS=$'\t' read -r id launched_at ami type price; do
            [ -n "$id" ] || continue
            ids+=("$id")
            prices+=("$price")
            warm=$((warm + 1))
        done <<<"$rows"
    fi

    if [ "$want" -gt "$warm" ]; then
        local image
        image="$(require_image)"
        require_headroom
        # ONE PRICE READ FOR THE WHOLE BATCH, and it is the price that goes on
        # every tag. Reading it per box would be N calls for one number and
        # would let two boxes launched in the same second carry two different
        # "prices at launch".
        local price
        price="$(spot_price "$INSTANCE_TYPE")"
        case "$price" in '' | None | null) price="?" ;; esac
        local n=0
        while [ "$n" -lt $((want - warm)) ]; do
            n=$((n + 1))
            launch_one_box "$image" "$INSTANCE_TYPE" "$idle" "$TTL_HOURS" "pool" "" \
                ",{Key=djb:for,Value=pool},{Key=djb:price,Value=${price}}"
            launches+=("$LAUNCHED_ID")
            keep_prices+=("$price")
            launched=$((launched + 1))
            say "pool launched ${LAUNCHED_ID} (${LAUNCHED_MARKET}, idle ${idle}m)"
        done
    fi

    local i due=0
    if [ "$warm" -gt "$want" ]; then
        due=$((warm - want))
    fi
    # TRIMMED OLDEST FIRST, AND ONLY WHAT NOBODY HAS CLAIMED. A claimed box is
    # a verification in flight; the listing is already oldest-first, so the
    # order is the API's and not a second arithmetic here.
    i=0
    while [ "$i" -lt "$warm" ]; do
        local bid="${ids[$i]}" bprice="${prices[$i]}"
        i=$((i + 1))
        if [ "$due" -gt 0 ] && [ ! -d "$(box_dir "$bid")/claim" ]; then
            terminate_or_by_hand "$bid" || true
            trimmed=$((trimmed + 1))
            due=$((due - 1))
            continue
        fi
        keep_prices+=("$bprice")
    done
    if [ "$due" -gt 0 ]; then
        say "pool ${due} box(es) over the want are CLAIMED and were left alone — a claim is a verification in flight"
    fi

    local unknown=0 p
    for p in ${keep_prices[@]+"${keep_prices[@]}"}; do
        case "$p" in [0-9]*) ;; *) unknown=$((unknown + 1)) ;; esac
    done
    printf 'pool: %d warm · %d launched · %d trimmed · $%s/h%s\n' \
        "$warm" "$launched" "$trimmed" \
        "$(pool_price_sum ${keep_prices[@]+"${keep_prices[@]}"})" \
        "$([ "$unknown" = "0" ] || printf ' (%d price(s) unknown)' "$unknown")"
}

# =============================================================================
# up
# =============================================================================
cmd_up() {
    local rung="" ttl="$TTL_HOURS" idle="$IDLE_MINUTES" type="$INSTANCE_TYPE"
    local on_demand="" no_push="" named_image="" ttl_typed="" idle_typed="" want_az=""
    while [ "$#" -gt 0 ]; do
        case "$1" in
        --az)
            want_az="${2:-}"
            shift 2 || die "--az takes an availability zone (e.g. ${REGION}a); 'zones' lists them"
            ;;
        --image-id)
            named_image="${2:-}"
            shift 2 || die "--image-id takes an ami id"
            ;;
        --for)
            rung="${2:-}"
            shift 2 || die "--for takes a rung id"
            ;;
        --ttl)
            ttl="${2:-}"
            ttl_typed=1
            shift 2 || die "--ttl takes hours"
            ;;
        --idle)
            idle="${2:-}"
            idle_typed=1
            shift 2 || die "--idle takes minutes"
            ;;
        --type)
            type="${2:-}"
            shift 2 || die "--type takes an instance type"
            ;;
        --on-demand)
            on_demand=1
            shift
            ;;
        --no-push)
            no_push=1
            shift
            ;;
        *) die "unknown argument '$1' to up" ;;
        esac
    done
    [ -n "$rung" ] || die "up needs --for <rung>: the tag and the box's log directory are named after it"
    case "$ttl" in '' | *[!0-9]*) die "--ttl takes whole hours, got '${ttl}'" ;; esac
    case "$idle" in '' | *[!0-9]*) die "--idle takes whole minutes, got '${idle}'" ;; esac
    [ "$ttl" -le "$TTL_CAP" ] ||
        die "--ttl ${ttl} is above the ${TTL_CAP}h cap. Nothing was launched. The cap is the
   only thing between a forgotten box and an unbounded bill; a verification that
   genuinely needs longer is a conversation, not a flag."
    [ "$ttl" -ge 1 ] || die "--ttl must be at least 1 hour"

    require_profile
    require_plugin
    # AN EXPLICIT IMAGE WINS OVER THE TAG LOOKUP, and it is checked rather than
    # trusted — see `require_named_image`. The lookup is the default because it
    # is the thing that keeps `up` a one-word command; the override exists
    # because a tag lookup cannot find an image whose tags were refused.
    local image
    if [ -n "$named_image" ]; then
        image="$(require_named_image "$named_image")"
    else
        image="$(require_image)"
    fi
    # --- a warm box is CLAIMED before anything is launched ------------------
    #
    # THE POOL IS THE FAST PATH AND THE LAUNCH IS THE FALL-BACK. A cold `up`
    # is ~115 s of launch plus ~50 s of bootstrap before the first byte of the
    # tree moves; a warm box is already through both, and a bank of eight pays
    # that difference eight times. Nothing else changes: the claim ends where
    # the launch ends, at a box id with a key beside it, and the push, the
    # vouch and the tree agreement below are the same code either way.
    local id="" market_note="" expires=""
    local launched_az="" launched_lifecycle="" launch_answered=""
    claim_warm_box "$image" "$rung"
    if [ -n "$CLAIMED_ID" ]; then
        id="$CLAIMED_ID"
        type="$CLAIMED_TYPE"
        expires="$(tag_of "$id" "djb:expires")"
        case "$expires" in "" | None | null) expires="(unread — census prints the tag)" ;; esac
        market_note="claimed from the warm pool"
        # A CLAIMED BOX CARRIES THE LIFETIME IT WAS LAUNCHED WITH, and a typed
        # flag that did not apply is said out loud rather than quietly ignored.
        # The alternative — refusing to claim whenever either flag is typed —
        # would make `up --for X --ttl 6` always cold, which is a surprise in
        # the other direction.
        if [ -n "$ttl_typed" ] || [ -n "$idle_typed" ]; then
            say "           NOTE: this box was CLAIMED warm, so it keeps the lifetime and idle" >&2
            say "           threshold it was launched with; the${ttl_typed:+ --ttl}${idle_typed:+ --idle} you typed applied to nothing." >&2
        fi
        # AND THE ZONE IS THE SAME KIND OF FACT, SAID THE SAME WAY. A warm box
        # is already somewhere; a claim cannot move it. Silence here is how a
        # bank spreads eight shards across three zones, claims six of them out
        # of a pool that is all in one, and reads its own plan back as though
        # it had worked — the `launched … az` line is honest either way, so
        # nothing else would ever say the zone was not honoured.
        if [ -n "$want_az" ]; then
            say "           NOTE: this box was CLAIMED warm, so it is in the zone it was launched in;" >&2
            say "           the --az ${want_az} you typed applied to nothing. The 'launched' line below" >&2
            say "           says where it actually is." >&2
        fi
    else
        require_headroom
        launch_one_box "$image" "$type" "$idle" "$ttl" "$rung" "$on_demand" "" "$want_az"
        id="$LAUNCHED_ID"
        market_note="$LAUNCHED_MARKET"
        expires="$LAUNCHED_EXPIRES"
        launched_az="$LAUNCHED_AZ"
        launched_lifecycle="$LAUNCHED_LIFECYCLE"
        # THE ZONE IS THE SIGNAL, never the lifecycle: `Placement` is on every
        # `run-instances` answer and `InstanceLifecycle` is absent on an
        # on-demand one, so an empty lifecycle beside a zone MEANS on-demand
        # and an empty zone means the answer did not carry the columns at all
        # — and then the describe below is the only way to know.
        [ -z "$LAUNCHED_AZ" ] || launch_answered=1
    fi

    # THE AZ AND THE MARKET, OUT OF ONE DESCRIBE. The market is EC2's own
    # `InstanceLifecycle` and not this wrapper's memory of what it asked for —
    # a launch that fell back, and a box claimed warm out of the pool, both
    # lie the other way round. The lifecycle comes FIRST in the projection so
    # the question has a slug of its own: `Placement.AvailabilityZone` alone
    # and the pair truncate to the same forty characters, and a fixture that
    # cannot tell two questions apart is a fixture that answers the wrong one.
    #
    # AND ON THE LAUNCH PATH IT IS NOT A DESCRIBE AT ALL. `run-instances` has
    # just answered about the instance it made, and that answer cannot be
    # behind the instance; a `describe-instances` on an id seconds old is
    # INSIDE EC2's eventual-consistency window and can say
    # `InvalidInstanceID.NotFound` about a box that is running. The call below
    # swallows its own error, so the transient arrives as an empty answer and
    # `market_of_lifecycle ""` reads `on-demand` — a Spot box labelled at five
    # times its price, in the one record that outlives the box. The describe
    # survives for the WARM CLAIM, which is the path with no launch response
    # and a box minutes old, long out of that window.
    local az market lifecycle placement
    if [ -n "$launch_answered" ]; then
        az="$launched_az"
        lifecycle="$launched_lifecycle"
    else
        placement="$(aws_q ec2 describe-instances --instance-ids "$id" \
            --query 'Reservations[0].Instances[0].[InstanceLifecycle,Placement.AvailabilityZone]' \
            --output text 2>/dev/null || true)"
        placement="${placement%%$'\n'*}"
        lifecycle="${placement%%	*}"
        az="${placement#*	}"
        [ "$az" != "$placement" ] || az=""
    fi
    market="$(market_of_lifecycle "$lifecycle")"

    # THE BOX IS NAMED BEFORE ANYTHING AFTER THE LAUNCH CAN FAIL, and that is
    # the whole of this line. Everything below it — the SSM wait, the vouch,
    # the probe, the pack — can refuse, and until this line every one of those
    # refusals exited with the instance line UNPRINTED: the box was running,
    # billing, and its id was nowhere on the operator's screen or in a bank's
    # `boxes.tsv`, so nothing took it down and the census found it later. The
    # probe's `TargetNotConnected` die was the measured instance; the ceiling
    # above it is a second belt and this is the first.
    #
    # ITS GRAMMAR IS A SEAM. `pm_push.sh`'s bank reads `launched <id> az <az>`
    # off a shard's `up` to record the box before it reads `up`'s own status,
    # so the words and their order are a contract with that reader and not a
    # narration. `az unknown` when the describe could not say: a field that is
    # sometimes absent is a field a parser handles once, and a line that
    # silently loses a column is a parser that shifts.
    echo "launched   ${id}   az ${az:-unknown}"

    wait_for_ssm "$id"

    local tree_line="tree       (not pushed — --no-push)"
    if [ -z "$no_push" ]; then
        # THE LAUNCH IS ALREADY PAID FOR BY THE TIME THE VOUCH RUNS, and that
        # ordering is what this block exists to make honest. `up` launches
        # FIRST and pushes SECOND, so a refused push leaves a RUNNING,
        # BILLING instance behind — and until this was written, `up` exited on
        # the refusal's own words ("nothing left this machine") while the box
        # stayed up, unmentioned, until the idle reaper or the census found it.
        # An operator reading that sentence has every reason to think nothing
        # was created.
        #
        # AND IT IS NOT TORN DOWN. The instance is the expensive half and the
        # push is the cheap one: a refusal here is almost always a local cause
        # with a local remedy (a hook that is not on this checkout's path, a
        # tree that is not this checkout's), and re-pushing into the box that
        # is already warm is measurably the fast path. So the refusal hands the
        # operator both doors and takes neither.
        #
        # STDOUT IS NOT DISCARDED HERE any more. The vouch's sentinel and the
        # hook's own words are the whole explanation of a refusal, and `up`
        # used to swallow them: only the wrapper's summary reached the
        # operator, who then had nothing to fix from.
        local prc=0
        cmd_push "$id" || prc=$?
        if [ "$prc" != "0" ]; then
            echo "!! verifier_box: box ${id} is UP (idle ${idle}m, expires ${expires}) — fix the cause and run: verifier_box.sh push ${id}   or take it down: verifier_box.sh down ${id}" >&2
            echo "   The box was NOT torn down: the launch is paid for and a re-push after the" >&2
            echo "   remedy is the fast path. Nothing reached it — the tree above is not on it." >&2
            exit 2
        fi
        # THE PUSH ALREADY PRINTED THE AGREEMENT, on stdout that now reaches
        # here, and it printed it about the box's WORKING TREE after moving it
        # onto the pushed main. Printing it again out of a second round trip
        # would be a second ssh to ask a question that has just been answered.
        tree_line=""
    fi

    echo "instance   ${id}   ${type}   market: ${market_note}   az ${az}"
    # TWO LINES ABOUT THE MARKET AND THEY ARE DIFFERENT CLAIMS. `market:` on
    # the line above is WHY — what the launch asked for and what the market
    # answered. This one is WHAT — the word EC2 uses for the instance that
    # exists, which is the only one worth reading back afterwards and the one
    # a bank's table carries.
    echo "market     ${market}"
    echo "owner      ${OWNER}        for: ${rung}   expires: ${expires} (ttl ${ttl}h)   idle: ${idle}m"
    [ -z "$tree_line" ] || echo "$tree_line"
    echo "session    aws ssm start-session --target ${id} --profile ${PROFILE} --region ${REGION}"
    echo "run        scripts/verifier_box.sh run ${id} -- <cmd>"
}

# LAUNCH ONE BOX, AND IT IS ONE FUNCTION BECAUSE THE SPOT FALLBACK IS ONE
# BLOCK. `up` (cold) and `pool` both need the same sequence: a per-box key
# generated here that never leaves this machine, the seam rendered with this
# box's expiry and idle threshold, a Spot request, the three market codes that
# mean "buy on-demand instead", the two account codes that mean "stop and say
# what is missing", and a box directory that comes into existence only once an
# instance id does. Duplicating that into `pool` would duplicate the one block
# whose branches are the difference between a named refusal and an unbounded
# bill — the opposite of the case principle 11 makes for duplication, which is
# about two things that merely LOOK alike.
#
# It sets LAUNCHED_ID / LAUNCHED_MARKET / LAUNCHED_EXPIRES, and refuses
# exactly as it did inside `up`, because it IS the code that was inside `up`.
LAUNCHED_ID=""
LAUNCHED_MARKET=""
LAUNCHED_EXPIRES=""
LAUNCHED_SPOT_REQUEST=""
LAUNCHED_AZ=""
LAUNCHED_LIFECYCLE=""
launch_one_box() {
    local image="$1" type="$2" idle="$3" ttl="$4" rung="$5" on_demand="$6" extra_tags="$7"
    local want_az="${8:-}"
    LAUNCHED_ID=""
    LAUNCHED_MARKET=""
    LAUNCHED_EXPIRES=""
    LAUNCHED_SPOT_REQUEST=""
    LAUNCHED_AZ=""
    LAUNCHED_LIFECYCLE=""

    local group
    group="$(aws_q ec2 describe-security-groups \
        --filters "Name=group-name,Values=${GROUP_NAME}" \
        --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || true)"
    case "$group" in
    "" | None | null)
        echo "!! verifier_box: no security group '${GROUP_NAME}' in ${REGION}." >&2
        print_owner_commands
        exit 2
        ;;
    esac

    # --- the zone, and the subnet that is how one is asked for --------------
    #
    # NOTHING IS RESOLVED WHEN NO ZONE WAS ASKED FOR, and that is a claim about
    # the ARGV as much as about the calls: an `up` with no `--az` makes exactly
    # the calls it made before this existed and its `run-instances` carries no
    # `--subnet-id`, so EC2 picks the zone exactly as it always did. A default
    # zone chosen here would be this wrapper quietly deciding where every box
    # in the account lands.
    local vpc_id="" subnet="" az="$want_az"
    if [ -n "$az" ]; then
        vpc_id="$(vpc_of_group)"
        [ -n "$vpc_id" ] || die "could not read the VPC of security group '${GROUP_NAME}' in ${REGION};
   --az ${az} cannot be honoured and nothing was launched. 'zones' asks the same
   question on its own."
        subnet="$(subnet_in_zone "$vpc_id" "$az")"
        [ -n "$subnet" ] || die "no subnet of ${vpc_id} is in availability zone '${az}', so there is no way to
   ask for that zone and nothing was launched. The zones this VPC can reach:
$(zones_of_vpc "$vpc_id" | sed 's/^/     /')"
    fi

    # --- the per-box key, generated here and never leaving ------------------
    local pending keyfile pubkey
    pending="${VERIFIER_HOME}/.pending-$$"
    rm -rf "$pending"
    mkdir -p "$pending"
    chmod 0700 "$pending"
    keyfile="${pending}/id_ed25519"
    ssh-keygen -q -t ed25519 -N "" -C "verifier@${OWNER}" -f "$keyfile" </dev/null
    chmod 0600 "$keyfile"
    pubkey="$(cat "${keyfile}.pub")"

    local expires
    expires="$(iso_at "$(($(now_epoch) + ttl * 3600))")"

    local user_data
    user_data="$(render_user_data "$ROOT/deploy/verifier/user-data.yaml.in" \
        "$pubkey" "$OWNER" "$expires" "$idle" "$image")"

    local name="${NAMESPACE}-verifier-${OWNER}-${rung}"
    local market_note="" id=""
    if [ -n "$on_demand" ]; then
        market_note="on-demand (asked for)"
        launch_attempt "$image" "$type" "$group" "$user_data" \
            "$expires" "$name" "" "$extra_tags" "$subnet" ""
        id="$LAUNCH_ID"
    else
        local spot_err="" az_retried="" rc=0
        launch_attempt "$image" "$type" "$group" "$user_data" \
            "$expires" "$name" "spot" "$extra_tags" "$subnet" "${pending}/spot.err"
        id="$LAUNCH_ID"
        rc="$LAUNCH_RC"
        # --- THE ZONE RING, ONCE, AND BEFORE THE MARKET RULE ---------------
        #
        # IT SITS ABOVE THE ON-DEMAND BRANCH DELIBERATELY. The three market
        # codes below answer "Spot said no" with on-demand money, and
        # `InsufficientInstanceCapacity` is the one of them that another ZONE
        # very often answers for free — so trying the next zone first is a
        # refusal avoided at no cost, and the branch below is what happens when
        # the ring has also run out. Reversing the two would buy an on-demand
        # box (or, for a bank shard, refuse the whole bank) while the zone next
        # door had capacity all along.
        #
        # AND ONCE. A ring that walked every zone would turn one capacity
        # refusal into N calls and N latencies, and the honest reading of two
        # zones refusing in a row is that the market is short of this type
        # right now — which is a thing to SAY, not a thing to keep asking.
        # `Unsupported` joins it because a type that is not offered in one zone
        # very often is in another, and on-demand cannot fix that one at all.
        if launch_failed; then
            spot_err="$(spot_error_code "${pending}/spot.err")"
            case "$spot_err" in
            InsufficientInstanceCapacity | Unsupported)
                local next_az="" next_subnet=""
                if [ -n "$az" ] && [ -z "$az_retried" ]; then
                    next_az="$(next_zone_after "$vpc_id" "$az")"
                    [ -z "$next_az" ] || next_subnet="$(subnet_in_zone "$vpc_id" "$next_az")"
                fi
                if [ -n "$next_az" ] && [ -n "$next_subnet" ]; then
                    echo "az ${az} refused (${spot_err}); trying ${next_az}" >&2
                    az_retried=1
                    az="$next_az"
                    subnet="$next_subnet"
                    launch_attempt "$image" "$type" "$group" "$user_data" \
                        "$expires" "$name" "spot" "$extra_tags" "$subnet" "${pending}/spot.err"
                    id="$LAUNCH_ID"
                    rc="$LAUNCH_RC"
                fi
                ;;
            esac
        fi
        if launch_failed; then
            spot_err="$(spot_error_code "${pending}/spot.err")"
            case "$spot_err" in
            InsufficientInstanceCapacity | SpotMaxPriceTooLow | MaxSpotInstanceCountExceeded)
                # THE MARKET SAYING NO, AND WHAT IT COSTS TO SAY YES ANYWAY.
                # On-demand is the right answer to these three for ONE box an
                # operator is standing in front of, and the wrong one for a
                # bank: N shards each answering a Spot refusal with an
                # on-demand box is N boxes against a quota an order of
                # magnitude smaller than the Spot one, bought without anybody
                # deciding to — which is how a bank came to have no box for
                # most of its units and a bill for the few it got.
                #
                # SO THE SHARD REFUSES AND THE SINGLE `up` DOES NOT, and both
                # of them SAY THE PRICE. The valve is a reason in words rather
                # than a flag, for `DJB_LOOP_HERE`'s reason: the sentence is
                # what a reader afterwards has, and a bare `=1` says only that
                # somebody got past a wall.
                local od
                od="$(on_demand_price "$type")"
                echo "!! verifier_box: Spot was refused (${spot_err}) for ${type} in ${REGION}." >&2
                if [ "$od" = "?" ]; then
                    echo "   on-demand price: UNKNOWN — DJB_VERIFIER_PRICING_REGION is unset, so the" >&2
                    echo "   Price List API was not asked. It is published in a small number of" >&2
                    echo "   regions and this wrapper guesses none of them." >&2
                else
                    echo "   on-demand would cost \$${od}/h for ${type}; Spot's last price was \$$(spot_price "$type")/h." >&2
                fi
                if [ -n "$BANK_SHARD" ] && [ -z "$ON_DEMAND_OK" ]; then
                    rm -rf "$pending"
                    echo "   THIS IS A BANK SHARD, so nothing was launched: could not launch." >&2
                    echo "   A bank's shards fall back together or not at all, and an unasked" >&2
                    echo "   on-demand bank is the failure this refusal exists to prevent. The" >&2
                    echo "   bank will refuse for the missing box, which is the outcome you want." >&2
                    echo "   To buy on-demand deliberately, type the reason and run the bank again:" >&2
                    echo "     DJB_VERIFIER_ON_DEMAND_OK=\"<why this wave is worth on-demand money>\"" >&2
                    exit 2
                fi
                if [ -n "$ON_DEMAND_OK" ]; then
                    echo "   on-demand ALLOWED by DJB_VERIFIER_ON_DEMAND_OK: ${ON_DEMAND_OK}" >&2
                    market_note="on-demand (spot refused: ${spot_err}; allowed: ${ON_DEMAND_OK})"
                else
                    market_note="on-demand (spot refused: ${spot_err})"
                fi
                launch_attempt "$image" "$type" "$group" "$user_data" \
                    "$expires" "$name" "" "$extra_tags" "$subnet" ""
                id="$LAUNCH_ID"
                ;;
            AuthFailure.ServiceLinkedRoleCreationNotPermitted)
                # NOT A CREDENTIAL FAULT, AND THAT IS THE WHOLE POINT OF THE
                # BRANCH. This code arrives looking like one — it begins
                # `AuthFailure` — and the credential is fine. What is missing is
                # EC2's own Spot service-linked role, which the FIRST Spot
                # request in an account creates as a side effect if the caller
                # may; the verifier ops user may not, by design, because its
                # policy grants no `iam:` write and
                # `iam:CreateServiceLinkedRole` is one.
                #
                # NO ON-DEMAND FALLBACK HERE, deliberately. The three codes
                # above are the market saying no and on-demand is the right
                # answer to them; this one is a one-line account prerequisite
                # that has never been met. Falling back would spend on-demand
                # money for every launch for ever and never say why.
                rm -rf "$pending"
                echo "!! verifier_box: Spot was refused for an ACCOUNT PREREQUISITE, not for capacity and" >&2
                echo "   not for your credential: ${spot_err}." >&2
                echo "   EC2's Spot service-linked role does not exist in this account. The first Spot" >&2
                echo "   request creates it as a side effect IF the caller may, and this one may not —" >&2
                echo "   the verifier ops policy grants no iam write at all, by design." >&2
                echo "   Nothing was launched. Two ways on, in order of preference:" >&2
                echo "     1. create the role ONCE, under the ADMIN profile:" >&2
                echo "          aws --region ${REGION} --profile <admin> \\" >&2
                echo "            iam create-service-linked-role --aws-service-name spot.amazonaws.com" >&2
                echo "        \`./deploy/iam/verifier_bootstrap.sh\` checks this as its step 0 and prints" >&2
                echo "        that same command when it is needed." >&2
                echo "     2. this one launch on-demand: verifier_box.sh up --on-demand --for <rung>" >&2
                exit 2
                ;;
            UnauthorizedOperation | ExpiredToken | AuthFailure | InvalidClientTokenId)
                rm -rf "$pending"
                echo "!! verifier_box: the credential was refused (${spot_err}). Nothing was launched." >&2
                print_owner_commands
                exit 2
                ;;
            *)
                local detail
                detail="$(head -n 3 "${pending}/spot.err" 2>/dev/null || true)"
                rm -rf "$pending"
                die "run-instances failed (${spot_err:-no error code}). Nothing was launched.
   ${detail}"
                ;;
            esac
        else
            market_note="spot ($(spot_price "$type")/h at launch)"
        fi
    fi
    { [ -n "$id" ] && [ "$id" != "None" ]; } || {
        rm -rf "$pending"
        die "run-instances returned no instance id"
    }

    mkdir -p "$(box_dir "$id")"
    chmod 0700 "$(box_dir "$id")"
    mv "$keyfile" "$(box_key "$id")"
    mv "${keyfile}.pub" "$(box_key "$id").pub"
    chmod 0600 "$(box_key "$id")"
    printf '%s\n' "$rung" >"$(box_dir "$id")/rung"
    # THE SPOT REQUEST ID LANDS BESIDE THE KEY, and only when there is one. An
    # on-demand box has no Spot request and the file's ABSENCE is the honest
    # record of that; a file holding `None` would be a request id nobody can
    # look up. `refuse_if_reclaimed` reads it and says `unrecorded` when it is
    # not there, which is also every box launched before this line existed.
    [ -z "$LAUNCH_SIR" ] || printf '%s\n' "$LAUNCH_SIR" >"$(box_dir "$id")/spot-request"
    rm -rf "$pending"

    LAUNCHED_ID="$id"
    LAUNCHED_SPOT_REQUEST="$LAUNCH_SIR"
    # THE ZONE AND THE MARKET THE LAUNCH ITSELF REPORTED. Not a later
    # describe: see the projection's own paragraph — a describe on a
    # seconds-old id can answer NotFound, and the swallowed transient turns a
    # Spot box into an `on-demand` line in the bank's table.
    LAUNCHED_AZ="$LAUNCH_AZ"
    LAUNCHED_LIFECYCLE="$LAUNCH_LIFECYCLE"
    LAUNCHED_MARKET="$market_note"
    LAUNCHED_EXPIRES="$expires"
}

# ONE ATTEMPT AT A LAUNCH, AND IT NEVER DECIDES ANYTHING. It exists because
# the launch is tried up to three times now — Spot, the next zone, on-demand —
# and each of those used to be its own `set +e` / capture / status dance
# written out in full; three copies of a five-line ritual is three places for
# the capture and the status to drift apart, and the middle one is new.
#
# IT ALWAYS RETURNS 0, deliberately. A failed Spot request is the ORDINARY
# input to the branches below it, so a non-zero return here would abort the
# whole wrapper under `set -e` before the branch that knows what to do with the
# error code ever ran. The status and the id are read back through
# `LAUNCH_RC`/`LAUNCH_ID`, and `launch_failed` is the one place that decides
# what "failed" means — a non-zero status, an empty id, or the `None` the CLI
# prints for a query that matched nothing, which are three different shapes of
# the same outcome and were compared in three places.
#
# THE ERROR FILE IS OPTIONAL AND THE ABSENCE IS A CHOICE. A Spot attempt's
# stderr is captured because `spot_error_code` has to read it; an on-demand
# attempt's is NOT, so the API's own words reach the operator's terminal
# exactly as they did before this function existed.
LAUNCH_ID=""
LAUNCH_SIR=""
LAUNCH_AZ=""
LAUNCH_LIFECYCLE=""
LAUNCH_RC=0
launch_attempt() {
    local image="$1" type="$2" group="$3" user_data="$4" expires="$5" name="$6" \
        market="$7" extra_tags="$8" subnet="$9" errfile="${10:-}"
    local out=""
    LAUNCH_ID=""
    LAUNCH_SIR=""
    LAUNCH_AZ=""
    LAUNCH_LIFECYCLE=""
    LAUNCH_RC=0
    set +e
    if [ -n "$errfile" ]; then
        out="$(run_instances_common "$image" "$type" "$group" "$user_data" \
            "verifier" "$expires" "$name" "$market" "$extra_tags" "$subnet" 2>"$errfile")"
    else
        out="$(run_instances_common "$image" "$type" "$group" "$user_data" \
            "verifier" "$expires" "$name" "$market" "$extra_tags" "$subnet")"
    fi
    LAUNCH_RC=$?
    set -e
    out="${out%%$'\n'*}"
    # FOUR FIELDS, AND EVERY ONE OF THEM MAY BE ABSENT. `--output text` gives a
    # tab-separated row; a fixture or an older answer with fewer columns must
    # degrade to empty rather than shifting the fields left, so the row is
    # split positionally and each field is read only if the split reached it.
    local rest="$out"
    LAUNCH_ID="${rest%%	*}"
    if [ "$rest" != "$LAUNCH_ID" ]; then
        rest="${rest#*	}"
        LAUNCH_SIR="${rest%%	*}"
        if [ "$rest" != "$LAUNCH_SIR" ]; then
            rest="${rest#*	}"
            LAUNCH_AZ="${rest%%	*}"
            if [ "$rest" != "$LAUNCH_AZ" ]; then
                LAUNCH_LIFECYCLE="${rest#*	}"
                LAUNCH_LIFECYCLE="${LAUNCH_LIFECYCLE%%	*}"
            fi
        fi
    fi
    # `--output text` spells an absent field `None`, and `SpotInstanceRequestId`
    # and `InstanceLifecycle` are both absent on an on-demand launch.
    case "$LAUNCH_SIR" in None | null) LAUNCH_SIR="" ;; esac
    case "$LAUNCH_AZ" in None | null) LAUNCH_AZ="" ;; esac
    case "$LAUNCH_LIFECYCLE" in None | null) LAUNCH_LIFECYCLE="" ;; esac
    return 0
}

launch_failed() { [ "$LAUNCH_RC" != "0" ] || [ -z "$LAUNCH_ID" ] || [ "$LAUNCH_ID" = "None" ]; }

# The launch itself, spelled out rather than hidden in a launch template: one
# resource to keep in step instead of two, and `deploy/provision.sh` spells its
# own `run-instances` in full for the same reason.
run_instances_common() {
    local image="$1" type="$2" group="$3" user_data="$4" role="$5" expires="$6" name="$7" market="$8"
    # EXTRA TAGS ARE APPENDED, NEVER SUBSTITUTED IN. The six tags below are on
    # every box this wrapper makes and are what `census`, `--all-mine`, the
    # reaper and the ops policy all read; a pool launch adds two more
    # (`djb:for=pool`, `djb:price`) and adds nothing else. An empty ninth
    # argument is the ordinary launch, byte-for-byte as it was.
    local extra_tags="${9:-}"
    # THE SUBNET IS APPENDED THE SAME WAY AND FOR THE SAME REASON. An empty
    # tenth argument is the ordinary launch, byte-for-byte as it was: EC2 picks
    # the zone, `--subnet-id` is nowhere on the argv, and the drive's launch
    # case reads exactly the command line it always did. A zone is asked for by
    # naming a subnet in it — `run-instances` has no `--availability-zone`.
    local subnet="${10:-}"
    local -a market_args=() subnet_args=()
    if [ -n "$market" ]; then
        market_args=(--instance-market-options
            "MarketType=spot,SpotOptions={SpotInstanceType=one-time,InstanceInterruptionBehavior=terminate}")
    fi
    [ -z "$subnet" ] || subnet_args=(--subnet-id "$subnet")
    aws_q ec2 run-instances \
        --image-id "$image" \
        --instance-type "$type" \
        --security-group-ids "$group" \
        "${subnet_args[@]+"${subnet_args[@]}"}" \
        --iam-instance-profile "Name=${INSTANCE_PROFILE}" \
        --instance-initiated-shutdown-behavior terminate \
        --metadata-options "HttpTokens=required,HttpEndpoint=enabled" \
        --block-device-mappings "DeviceName=/dev/xvda,Ebs={VolumeSize=60,VolumeType=gp3,Encrypted=true}" \
        --user-data "$user_data" \
        "${market_args[@]+"${market_args[@]}"}" \
        --tag-specifications "ResourceType=instance,Tags=[{Key=djb:role,Value=${role}},{Key=djb:owner,Value=${OWNER}},{Key=djb:expires,Value=${expires}},{Key=djb:namespace,Value=${NAMESPACE}},{Key=Name,Value=${name}},{Key=Project,Value=${NAMESPACE}}${extra_tags}]" \
        --query 'Instances[0].[InstanceId,SpotInstanceRequestId,Placement.AvailabilityZone,InstanceLifecycle]' --output text
}
# AND THE PLACEMENT AND THE MARKET COME OUT OF THE SAME ANSWER, for a reason
# that is not tidiness. `up` used to read them from a `describe-instances` on
# an instance id that was SECONDS old — inside EC2's eventual-consistency
# window, where a describe can answer `InvalidInstanceID.NotFound` for an
# instance that certainly exists. That call swallows its own error
# (`2>/dev/null || true`), so the transient arrives as an EMPTY answer: the AZ
# degrades to `unknown`, which is honest, but `market_of_lifecycle ""` returns
# `on-demand` — so a Spot box prints `market     on-demand` and the bank's
# table, which is the only record of what a wave cost once the boxes are gone,
# records the wrong market at five times the price. The launch's own response
# is authoritative about the instance it just made and cannot be behind it.
# THE SPOT REQUEST ID COMES OUT OF THE LAUNCH, NOT OUT OF A LATER SEARCH. It is
# the only handle on `describe-spot-instance-requests`, which is the only thing
# that can say WHY a box was reclaimed (`spot_status_of`); asking for it
# afterwards means filtering the account's Spot requests by instance id at the
# exact moment the instance has stopped existing, which is the moment the
# question arises. `run-instances` already returns it on the instance it just
# made, so the projection above takes two fields instead of one and the second
# is `None` on an on-demand launch — `--output text` renders that absence as
# the word, and the reader treats `None` and an absent column identically, so a
# box launched by a wrapper older than this line writes no file and the status
# reads `unrecorded` rather than lying.

# WHAT AN ON-DEMAND HOUR COSTS, SO A FALLBACK CAN PRINT THE MONEY IT IS ABOUT
# TO SPEND. `describe-spot-price-history` answers for Spot and there is no EC2
# call that answers for on-demand: the number is published by the Price List
# API, which lives in a small number of regions of its own. This wrapper
# GUESSES NONE of them — the argument every other coordinate here makes — so
# the region is a knob with no default, and with the knob unset the answer is
# `?` and the caller says why. A credential without `pricing:GetProducts` gets
# the same `?`, which is the honest answer to a question that could not be
# asked.
#
# READ WHOLE, THEN SLICE, for `spot_error_code`'s reason: a `| head` here would
# make a SIGPIPE indistinguishable from a price.
on_demand_price() {
    local type="$1" blob matches first num
    [ -n "$PRICING_REGION" ] || {
        printf '?\n'
        return 0
    }
    blob="$(aws --region "$PRICING_REGION" --profile "$PROFILE" pricing get-products \
        --service-code AmazonEC2 \
        --filters "Type=TERM_MATCH,Field=instanceType,Value=${type}" \
        "Type=TERM_MATCH,Field=regionCode,Value=${REGION}" \
        "Type=TERM_MATCH,Field=operatingSystem,Value=Linux" \
        "Type=TERM_MATCH,Field=tenancy,Value=Shared" \
        "Type=TERM_MATCH,Field=preInstalledSw,Value=NA" \
        "Type=TERM_MATCH,Field=capacitystatus,Value=Used" \
        --max-items 1 --query 'PriceList[0]' --output text 2>/dev/null || true)"
    matches="$(printf '%s' "$blob" | grep -oE '"USD"[^0-9]*[0-9]+\.[0-9]+' || true)"
    first="${matches%%$'\n'*}"
    num="${first//[!0-9.]/}"
    # The slug above keeps the dots, and `"USD"` contributes none; what is left
    # is the rate. An answer with no rate in it is `?` rather than an empty
    # string dressed up as a number.
    case "$num" in '' | '.'*) num="?" ;; esac
    printf '%s\n' "$num"
}

# THE MARKET A BOX IS ON, FROM EC2'S OWN ANSWER AND NEVER FROM WHAT THE LAUNCH
# ASKED FOR. `InstanceLifecycle` is `spot` on a Spot instance and ABSENT on an
# on-demand one (`--output text` renders that absence as `None`), so on-demand
# is read as the absence rather than assumed from the request — which is the
# whole point: a launch that asked for Spot and got on-demand through the
# fallback, and a box claimed warm out of the pool, both lie if you ask the
# wrapper's memory instead of the instance.
market_of_lifecycle() {
    case "${1:-}" in
    spot) printf 'spot\n' ;;
    '' | None | null) printf 'on-demand\n' ;;
    *) printf '%s\n' "$1" ;;
    esac
}

spot_error_code() {
    [ -r "$1" ] || return 0
    # READ THE WHOLE, THEN SLICE, for `verifier_owner`'s reason one organ over —
    # and this one decides spot or on-demand, so a 141 here is a launch that
    # stopped between the refusal and the fallback.
    local matches first
    # THE DOTTED CODE IS IN THE ALTERNATION, and that is the whole of the fix.
    # `AuthFailure.ServiceLinkedRoleCreationNotPermitted` does not match
    # `\(AuthFailure\)` — the close paren is not where the pattern expects it —
    # so before it was listed the match failed outright, the code came back
    # EMPTY, and a named account prerequisite arrived as `run-instances failed
    # (no error code)`.
    #
    # ITS POSITION BEFORE ITS OWN PREFIX IS NOT LOAD-BEARING, and an earlier
    # version of this comment said it was. That is PERL's rule — leftmost
    # alternative wins — and this is `grep -oE`, POSIX ERE, where the LONGEST
    # match wins whatever the order. Measured on this machine against the real
    # message: with `AuthFailure` listed first, `grep -oE` still returns the
    # dotted code, and `perl` returns the bare prefix. The literal parens are a
    # second reason it cannot go wrong here — `(AuthFailure)` needs a close
    # paren where the dotted string has a dot. The ordering stays because it
    # reads most-specific-first, not because anything depends on it.
    #
    # `Unsupported` IS IN THE ALTERNATION NOW, and it was the widest of the
    # holes: EC2 answers it when the instance TYPE is not offered in the zone
    # the launch landed in, which is the other half of the reason the zone ring
    # above exists — and before it was listed, that arrived as
    # `run-instances failed (no error code)` with nothing to branch on.
    matches="$(grep -oE '\((AuthFailure\.ServiceLinkedRoleCreationNotPermitted|InsufficientInstanceCapacity|SpotMaxPriceTooLow|MaxSpotInstanceCountExceeded|UnauthorizedOperation|ExpiredToken|AuthFailure|InvalidClientTokenId|Unsupported)\)' "$1" || true)"
    first="${matches%%$'\n'*}"
    printf '%s\n' "${first//[()]/}"
}

# READ WHOLE, THEN SLICE — and this one was MEASURED on a real launch rather
# than reasoned about. `--max-items` makes the CLI print a PAGINATION TOKEN on
# a second line, so this call's answer is two lines and the second is `None`:
#
#     market: spot (0.203600
#     None/h at launch)
#
# That was merely ugly for as long as the answer only ever reached a narration.
# `pool` puts it in the `djb:price` TAG, where a newline is a tag value nothing
# can read back and a census that adds prices up would be adding up garbage —
# so the slice is here, at the one place the number is produced, rather than at
# each of the two places it is used.
spot_price() {
    local out
    out="$(aws_q ec2 describe-spot-price-history --instance-types "$1" \
        --product-descriptions "Linux/UNIX" --max-items 1 \
        --query 'SpotPriceHistory[0].SpotPrice' --output text 2>/dev/null || true)"
    out="${out%%$'\n'*}"
    case "$out" in '' | None | null) out="?" ;; esac
    printf '%s\n' "$out"
}

# `envsubst`-free: neither this machine nor a minimal Amazon Linux ships it, and
# a renderer that has to be installed first is a step that fails as written.
# THE FIFTH SLOT IS THE IMAGE THE BOX WAS CUT FROM, AND IT IS WRITTEN HERE
# BECAUSE THE BOX CANNOT BE ASKED. A drive verdict's machine half is the image
# id on a box (`scripts/gate_ledger.sh`, `drive_machine_digest`), so two boxes
# of one image reuse each other's rows and a box never reuses this laptop's.
# IMDS would answer the same question, but IMDS cannot be planted by a drive
# and a key input no drive can move is a key input nobody can prove — so the
# value comes from the `$image` this wrapper already resolved before the launch
# and travels in user-data like the other four.
render_user_data() {
    local template="$1" pubkey="$2" owner="$3" expires="$4" idle="$5" image="${6:-unknown}"
    [ -r "$template" ] || die "cannot read the launch seam ${template}"
    sed -e "s|\${VERIFIER_PUBKEY}|${pubkey}|g" \
        -e "s|\${VERIFIER_OWNER}|${owner}|g" \
        -e "s|\${VERIFIER_EXPIRES}|${expires}|g" \
        -e "s|\${VERIFIER_IDLE_MINUTES}|${idle}|g" \
        -e "s|\${VERIFIER_IMAGE_ID}|${image}|g" \
        "$template"
}

# THE CEILING IS ASSERTED BEFORE THE CALL, not discovered after it. Without this
# the third launch gets AWS's own `MaxSpotInstanceCountExceeded`, which the
# fallback above turns into on-demand — i.e. the quota would silently become
# money.
require_headroom() {
    local running quota
    running="$(aws_q ec2 describe-instances \
        --filters "Name=tag:djb:role,Values=verifier" \
        "Name=tag:djb:namespace,Values=${NAMESPACE}" \
        "Name=instance-state-name,Values=pending,running" \
        --query 'Reservations[].Instances[].InstanceId' --output text 2>/dev/null || true)"
    local count=0
    [ -z "$running" ] || count="$(printf '%s\n' "$running" | tr '\t' '\n' | grep -c . || true)"
    [ "$count" -lt "$MAX_BOXES" ] || {
        quota="$(aws_q service-quotas get-service-quota --service-code ec2 \
            --quota-code "$SPOT_QUOTA_CODE" --query 'Quota.Value' --output text 2>/dev/null || echo "?")"
        # ALL THREE SOURCES, AND THE ONE THAT BOUND. A refusal that named only
        # DJB_VERIFIER_MAX_BOXES sent every reader to a variable that was very
        # often not where the number came from, and left the one place a whole
        # machine's ceiling can be set — the file — undiscoverable.
        die "${count} verifier box(es) already running and the ceiling is ${MAX_BOXES} (${MAX_BOXES_SOURCE}):
     $(printf '%s' "$running" | tr '\t' ' ')
   Nothing was launched. Where the ${MAX_BOXES} came from, '->' the one that bound:
$(ceiling_sources)
   The ceiling stands for the Spot vCPU quota (${SPOT_QUOTA_CODE} = ${quota})
   divided by this instance type (${INSTANCE_TYPE}); raise it only after the quota
   is raised — \`./scripts/verifier_box.sh ceiling <n>\` writes the file for every
   session on this machine, DJB_VERIFIER_MAX_BOXES raises it for this shell alone
   — or 'down' one of the boxes above."
    }
}

wait_for_ssm() {
    local id="$1" waited=0 started status=""
    started="$(now_epoch)"
    while [ "$waited" -lt "$ONLINE_WAIT_SECONDS" ]; do
        status="$(aws_q ssm describe-instance-information \
            --filters "Key=InstanceIds,Values=${id}" \
            --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || true)"
        [ "$status" = "Online" ] && return 0
        sleep "$ONLINE_POLL_SECONDS"
        waited=$(($(now_epoch) - started))
    done
    # WHO TAKES THE BOX DOWN DEPENDS ON WHO IS WAITING, and the refusal has to
    # say which. `up` hands the operator a box and a command for it; a bake has
    # a teardown armed and takes the box on the way out, so sending its operator
    # after a machine that is already terminating spends the one minute they
    # have on the wrong question.
    local hint="It is RUNNING and it is BILLING: take it down with

     scripts/verifier_box.sh down ${id}"
    [ -z "${BAKE_BOX:-}" ] || hint="The bake's teardown takes it down on the way out; nothing is left for you to do."
    die "${id} did not register with Session Manager inside ${waited}s (ceiling ${ONLINE_WAIT_SECONDS}s).
   ${hint}"
}

# ONLINE SAYS THE AGENT IS UP; THIS SAYS THE BOX IS PREPARED. The two are
# different questions and only the second one is the push's precondition — see
# BAKE_READY_MARKER above for what the difference cost. The probe is the
# cheapest thing that can answer it: one `test -f` over the transport, whose
# status is the remote command's. An ssh that cannot connect yet fails the same
# way and is retried the same way, which is the right behaviour: the key and
# the sshd are written by an EARLIER cloud-init stage than the marker, so
# anything that is not ready is not ready.
wait_for_bake_bootstrap() {
    local id="$1" started
    started="$(now_epoch)"
    BOOTSTRAP_WAITED=0
    while [ "$BOOTSTRAP_WAITED" -lt "$BOOTSTRAP_WAIT_SECONDS" ]; do
        if ssh_to "$id" "test -f ${BAKE_READY_MARKER}" >/dev/null 2>&1; then
            return 0
        fi
        sleep "$ONLINE_POLL_SECONDS"
        BOOTSTRAP_WAITED=$(($(now_epoch) - started))
    done
    return 1
}

# =============================================================================
# push, and the agreement it exists to prove
# =============================================================================
# WHAT IS PUSHED: THIS CHECKOUT'S HEAD, AND NEVER A BRANCH BY NAME.
#
# The wrapper used to push `main:main`, and from a rung's WORKTREE that is a
# different tree from the one the operator is standing in: the pre-push hook
# vouches for what is on stdin, found `main`'s tree with no verdict, and
# refused — correctly — after a bake box was already up and billing. `HEAD` is
# the one tree this checkout can vouch for, and it is the one the box should be
# verifying.
#
# THE CONSEQUENCE, SAID OUT LOUD RATHER THAN HIDDEN: from a worktree whose HEAD
# is not `main`, the BOX'S `main` becomes that worktree's tree. That is the
# right answer for a bake (the image only needs a tree) and for a verification
# of an already-folded rung (the tree IS the union), and it is the wrong answer
# if somebody expected the box to carry this machine's `main` separately. So
# the line below says which ref HEAD was, every time, and `tree_agreement_line`
# compares HEAD rather than main.
#
# THE TRANSFER IS SHALLOW, and that is the other half. Pushing a branch into an
# empty repository sends every object reachable from it: 213 MB of this
# repository's history, measured at 655 s of a 739 s bake on a good tunnel and
# an outright stall on a bad one. A verification needs the TREE. So the pack is
# built from a depth-1 mirror of HEAD — 9.6 MB of the same 222 MB repository,
# measured on this tree — and the hook still vouches for the same tree, because
# the vouch is run separately and first.
cmd_push() {
    local id="${1:-}"
    shift || true
    [ -n "$id" ] || die "push needs an instance id"
    refuse_if_reclaimed "$id"
    local key checkout head_sha head_ref main_sha
    key="$(box_key "$id")"
    [ -r "$key" ] || die "no private key for ${id}"
    checkout="$(verifier_checkout_path)"
    head_sha="$(git -C "$ROOT" rev-parse HEAD)"
    head_ref="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo HEAD)"
    main_sha="$(git -C "$ROOT" rev-parse --verify --quiet refs/heads/main 2>/dev/null || true)"
    # TWO REF LISTS, AND THE DIFFERENCE IS THE WHOLE POINT OF THIS CHANGE. The
    # VOUCH runs in this checkout, where the tree being pushed is named `HEAD`
    # — `refs/heads/main:…` there would hand the hook main's tree, which is
    # precisely the defect this replaces. The TRANSFER runs in the mirror,
    # where that same tree has already landed on the mirror's own `main`.
    local -a vouch_refs=("HEAD:refs/heads/main")
    local -a refs=("refs/heads/main:refs/heads/main")
    # THE RUNG'S FORK POINT TRAVELS WITH THE TREE, as a third ref. A depth-1
    # mirror collapses HEAD and `main` onto ONE commit, so on the box
    # `merge-base HEAD refs/heads/main` is that commit and the gate's
    # changed-file derivation comes back EMPTY for a rung that touched six files
    # here — the scope, the secret scan, the three changed-file censuses and the
    # fe leg all read that one derivation, so all five ask about nothing. The
    # verdict stays honest (its key records its own scope) and "the box ran the
    # same --loop" stops being true.
    #
    # A REF AND NOT JUST A SHA, because a sha the box does not HAVE is a name it
    # cannot diff against. `push_the_tree_shallow` deepens the mirror to reach
    # the base commit and pushes it as `refs/djb/base`; `cmd_loop` names that
    # ref in `DJB_LOOP_SCOPE_BASE` on the gate's command line.
    local base_sha=""
    if [ -n "$main_sha" ]; then
        base_sha="$(git -C "$ROOT" merge-base HEAD refs/heads/main 2>/dev/null || true)"
        [ "$base_sha" = "$head_sha" ] && base_sha=""
    fi
    local b
    for b in "$@"; do
        vouch_refs+=("refs/heads/${b}:refs/heads/${b}")
        refs+=("refs/heads/${b}:refs/heads/${b}")
    done
    say "pushing    HEAD (${head_ref} ${head_sha:0:8}) as the box's main${*:+ , and: $*}"
    if [ -n "$main_sha" ] && [ "$main_sha" != "$head_sha" ]; then
        # ON STDERR, for the reason the throughput probe below states in full:
        # `bake` invokes `cmd_push` with its stdout at /dev/null — it prints its
        # own phases — so a note narrated on stdout is a note that caller never
        # sees. (`up` reads this function's stdout now: a refusal it has to
        # explain is explained by the hook's own words.) This one carries more
        # now than it did: the image a bake captures is NAMED after HEAD, so
        # this is where an operator standing in a rung worktree learns that the
        # `main` on their screen is not the tree about to be baked and labelled.
        say "           NOTE: this checkout's main is ${main_sha:0:8} — the box's main will be HEAD's" >&2
        say "           tree, which is the tree this checkout can vouch for and the tree a" >&2
        say "           verification here is about." >&2
    fi

    # THE VOUCH, RUN WHERE IT ALWAYS RAN — on this checkout, over exactly these
    # refs, by the pre-push hook itself. It has to be explicit now: the pack
    # leaves from a scratch mirror that has no hooks and no verdict ledger, so
    # a plain push from there would carry the tree past the wall that exists to
    # stop exactly that. `--dry-run` runs every hook and sends no objects
    # (measured), and the remote is a throwaway empty repository on this
    # machine, because the hook reads the refs from stdin and has no opinion
    # about where they are going. Its exit status is the wall's.
    #
    # AND THE DESTINATION IS DECLARED, FOR THIS ONE COMMAND ONLY. A prefix
    # assignment exports `DJB_PUSH_DESTINATION` into the `git push` below and
    # into nothing else. The hook honours it ONLY together with the probe path
    # underneath — both conditions, so a variable exported by hand at a terminal
    # opens `origin` no more than it did before — and what it buys is the
    # measurement, never the identity check: an unmeasured tree that IS this
    # checkout's goes to the box, a foreign tree is refused here exactly as it
    # always was. The doctrine and the reasoning are the hook's own header.
    # A verifier box is not a forge; its whole job is to run the gate on the tree
    # it is handed, so spending 30-70 minutes of THIS Mac first bought nothing
    # and meant no verification could ever reach a box off `main`.
    #
    # THE OUTPUT IS CAPTURED RATHER THAN STREAMED, because the hook's own
    # SENTINEL is the only proof a wall was consulted at all — and it is read
    # below, not piped: the file is written, the status is git's, and the words
    # are re-emitted so the operator still sees them. Nothing reaches the gate
    # from here (a box destination exempts it), so there is no long run to watch.
    local vouch prc=0 vouch_log
    vouch="${VERIFIER_HOME}/.vouch-$$"
    rm -rf "$vouch"
    mkdir -p "$vouch"
    git init -q --bare "${vouch}/probe.git" 2>/dev/null || {
        rm -rf "$vouch"
        die "could not make a scratch repository under ${VERIFIER_HOME} to run the pre-push
   hook against. Nothing was pushed."
    }
    vouch_log="${vouch}/hook.out"
    DJB_PUSH_DESTINATION=verifier-box \
        git -C "$ROOT" push --dry-run --force "${vouch}/probe.git" "${vouch_refs[@]}" \
        >"$vouch_log" 2>&1 || prc=$?
    cat "$vouch_log" >&2 || true
    # THE SENTINEL, READ FROM THE FILE. `pre-push: wall <word> <tree>` is printed
    # by the hook before every terminal decision it makes; its ABSENCE means no
    # hook ran, which `git push --dry-run` reports as exit 0 and silence — the
    # shape a `git clone` has, because clone copies neither `core.hooksPath` nor
    # a hook file, and `.git/hooks` in a fresh clone holds only samples. Measured
    # on 2026-09-18: from the primary the dry-run demanded the full
    # gate; from a verify clone of it the identical command vouched for nothing
    # and the box carried an unvouched tree.
    local saw_wall=0
    grep -F -- "pre-push: wall " "$vouch_log" >/dev/null 2>&1 && saw_wall=1
    rm -rf "$vouch"
    if [ "$prc" != "0" ]; then
        echo "!! verifier_box: the pre-push hook refused this tree (exit ${prc}), and nothing left this" >&2
        echo "   machine. The hook's own words are above; it consults the verdict ledger and, on a" >&2
        echo "   miss, measures the full gate. This is THIS machine's wall and not the box's:" >&2
        echo "   there is nothing on the box that explains it and nothing there that can fix it." >&2
        echo "   The push was not attempted." >&2
        return "$prc"
    fi
    if [ "$saw_wall" -eq 0 ]; then
        # A RETURN AND NOT A `die`, and the difference is a box left billing.
        # `die` exits the PROCESS, so a refusal raised here from inside `up`
        # unwound past the caller that knew an instance had already been
        # launched — and `up` ended saying "nothing left this machine" while the
        # box stayed up, unmentioned. The refusal below is the one `up` catches
        # to name it. The refusal above already returns for the same reason, and
        # `bake` reads a status too, so `return` is this function's grammar and
        # the `die` was the exception.
        echo "!! verifier_box: no pre-push hook ran on this checkout — set core.hooksPath=scripts/githooks (verify_start.sh does) — nothing left this machine" >&2
        return 2
    fi

    # AND THE TUNNEL IS MEASURED BEFORE THE PACK IS OFFERED TO IT.
    throughput_probe "$id" || return $?

    push_the_tree_shallow "$id" "$head_sha" "$checkout" "$base_sha" "${refs[@]}" || return $?

    # AND THE FILES FOLLOW THE REF. Until this line the push ended with a ref
    # moved and a working tree untouched, so the box measured the image — see
    # `sync_box_worktree`, which also prints the agreement and refuses on
    # inequality. It is the LAST thing a push does, because everything before it
    # is what makes the agreement possible.
    sync_box_worktree "$id" "$checkout"

    # AND THE DRIVE ROWS FOLLOW THE FILES. Everything above moves a TREE; this
    # moves the box's memory of what has already been driven over one.
    push_drive_rows "$id"
}

# THE DRIVE ROWS TRAVEL, AND THEY TRAVEL BY scp.
#
# WHAT THEY ARE. `scripts/gate_ledger.sh` banks one row per drive keyed on what
# that drive DECLARES it drives, and the selftest leg does not re-run a drive
# whose key is already in the ledger. The ledger lives in `.git/` and no push
# carries it, so every fresh box arrived with an empty one and re-drove all
# thirty — measured on the first on-box bank. With the machine half now being
# the IMAGE id rather than `uname -sr`, a row banked on one box of an image is a
# row every box of that image can honour, and the only thing missing was a
# carrier.
#
# ONLY THE `drive` ROWS, AND THAT IS NOT TIDINESS. A `full` or a `loop` row
# vouches for a whole gate over a whole tree in a whole environment; shipping
# one to a box would hand that box a verdict it could reuse for a measurement it
# never made. A `drive` row is keyed on bytes and a machine, both of which the
# box can re-derive for itself, so it is the one kind that is safe to carry.
#
# BY scp AND NOT BY A REF. `refs/djb/ledger` was the obvious shape and it is the
# wrong one twice over: a shallow mirror sends ONE ref per `git push` (measured
# 5/5, argued at `push_the_tree_shallow`), so a fourth ref is a fourth round trip
# over the tunnel; and a ref needs a commit object for text that is not a tree.
# `cmd_fetch` already moves files over this transport in one call, and this is
# that call in the other direction (principle 13: the transport that exists).
#
# IT IS NOT AN INGEST. The file lands at `~/verify/<rung>/ledger.in` and nothing
# on the box has read it yet; `cmd_loop` and `cmd_leg` prepend the idempotent
# ingest to the command line that runs the gate, so a push that is never
# followed by a run changes nothing over there.
push_drive_rows() {
    local id="$1" rung path rows scratch n key
    [ -r "$ROOT/scripts/gate_ledger.sh" ] || {
        say "drive rows: not sent — no ${ROOT}/scripts/gate_ledger.sh to read the ledger's path from" >&2
        return 0
    }
    # A SUBSHELL, so sourcing the ledger library cannot redefine anything this
    # wrapper owns for the rest of its run.
    path="$(cd "$ROOT" && . scripts/gate_ledger.sh && gate_ledger_path 2>/dev/null)" || path=""
    if [ -z "$path" ] || [ ! -r "$path" ]; then
        say "drive rows: none to send"
        return 0
    fi
    rung="$(box_rung "$id")"
    scratch="${VERIFIER_HOME}/.ledger-out-$$"
    mkdir -p "$VERIFIER_HOME"
    rm -f "$scratch"
    # `grep || true`: no drive row is the ordinary case on a fresh checkout and
    # grep's exit 1 must not become this wrapper's under `set -e`.
    grep -F " drive " "$path" >"$scratch" 2>/dev/null || true
    n="$(awk 'END { print NR + 0 }' "$scratch")"
    if [ "$n" = "0" ]; then
        rm -f "$scratch"
        say "drive rows: none to send"
        return 0
    fi
    ssh_to "$id" "mkdir -p ~/verify/${rung}" >/dev/null 2>&1 || {
        rm -f "$scratch"
        say "drive rows: not sent — could not make ~/verify/${rung} on ${id}" >&2
        return 0
    }
    key="$(box_key "$id")"
    if scp -i "$key" \
        -o "ProxyCommand=$(proxy_command)" \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        -o LogLevel=ERROR \
        "$scratch" "$(verifier_box_user)@${id}:verify/${rung}/ledger.in"; then
        say "drive rows: ${n} sent to ${id}:~/verify/${rung}/ledger.in"
    else
        # A NOTE AND NOT A REFUSAL, and the difference is what a failed carrier
        # costs: the box re-drives what it could have reused. The tree is
        # already over there and vouched for; refusing here would throw away a
        # push that worked for the sake of a cache that did not.
        say "drive rows: NOT sent — the scp to ${id} failed; the box will re-drive what it could have reused" >&2
    fi
    rm -f "$scratch"
}

# 1 MB, AND THE SIZE IS THE ARGUMENT. The ask that bought this probe said 32
# MB, and 32 MB was right when the push it protects was 213 MB; against a 9.6
# MB shallow pack a 32 MB probe costs three times what it is guarding. What the
# probe has to do is turn AN HOUR OF STALL INTO A REFUSAL, and for that it only
# has to be big enough to measure and small enough to finish: at the 7 KB/s a
# real tunnel gave on a bad night, 1 MB answers in about two and a half minutes
# and 32 MB would not answer inside an hour — the very failure it exists to
# prevent. Both the size and the floor are knobs, and 0 turns it off.
throughput_probe() {
    local id="$1"
    case "$PROBE_MB" in
    '' | *[!0-9]*) die "DJB_VERIFIER_PROBE_MB must be whole megabytes, got '${PROBE_MB}'" ;;
    0)
        say "probe      skipped (DJB_VERIFIER_PROBE_MB=0)"
        return 0
        ;;
    esac
    local tmp started elapsed kbps kb
    tmp="${VERIFIER_HOME}/.probe-$$"
    mkdir -p "$VERIFIER_HOME"
    dd if=/dev/zero of="$tmp" bs=1048576 count="$PROBE_MB" 2>/dev/null || {
        rm -f "$tmp"
        die "could not write a ${PROBE_MB} MB probe file under ${VERIFIER_HOME}"
    }
    kb=$((PROBE_MB * 1024))
    # THE AGENT'S `Online` AND THE SESSION CHANNEL ARE NOT THE SAME READINESS,
    # and the gap between them was a whole class of lost box. `up` waits for
    # `PingStatus=Online` — the SSM agent reporting in — and the ssh-over-SSM
    # channel comes up a few seconds behind it, so the first probe comes back
    # with ssh's own 255 and `TargetNotConnected` on stderr. That `die` ran
    # INSIDE `cmd_push`, which runs inside `up` BEFORE `up` prints its instance
    # line, so the box was running, billing and its id was on nobody's screen —
    # measured on a bank whose shard had no `boxes.tsv` row to take down.
    #
    # SO IT WAITS, AND IT WAITS OUT LOUD AND WITH A CEILING. Every wait prints
    # what it has spent, `DJB_VERIFIER_TUNNEL_WAIT_SECONDS` bounds it, and past
    # the ceiling the refusal is the one that was always here — a transport
    # that is still not up after a minute is not a race, and a silent retry
    # loop is how a wrapper hangs instead of refusing.
    #
    # ONLY `TargetNotConnected`, AND ONLY WITH 255. A refused key, a dead
    # tunnel and a box that answers with an error are all instant refusals as
    # before; retrying those would spend a minute proving something the first
    # attempt already said. The stderr is CAPTURED to read that one word and
    # then re-emitted, so the operator loses nothing.
    local errfile waited=0 arc=0
    errfile="${VERIFIER_HOME}/.probe-$$.err"
    while :; do
        started="$(now_epoch)"
        arc=0
        ssh_to "$id" "cat >/dev/null" <"$tmp" 2>"$errfile" || arc=$?
        [ "$arc" != "0" ] || break
        if [ "$arc" = "255" ] && grep -F -- "TargetNotConnected" "$errfile" >/dev/null 2>&1 &&
            [ "$waited" -lt "$TUNNEL_WAIT_SECONDS" ]; then
            sleep "$TUNNEL_POLL_SECONDS"
            waited=$((waited + TUNNEL_POLL_SECONDS))
            say "tunnel     not yet connected; waited ${waited}s (ceiling ${TUNNEL_WAIT_SECONDS}s, DJB_VERIFIER_TUNNEL_WAIT_SECONDS)" >&2
            continue
        fi
        cat "$errfile" >&2 || true
        rm -f "$tmp" "$errfile"
        local waited_line=""
        [ "$waited" = "0" ] ||
            waited_line="
   The session channel was waited on for ${waited}s and never connected."
        die "the throughput probe could not reach ${id} through the tunnel at all. Nothing was
   pushed. The box is up as far as this wrapper knows; the transport is not.${waited_line}"
    done
    cat "$errfile" >&2 || true
    rm -f "$errfile"
    rm -f "$tmp"
    elapsed=$(($(now_epoch) - started))
    [ "$elapsed" -ge 1 ] || elapsed=1
    kbps=$((kb / elapsed))
    # ON STDERR, AND THAT IS NOT A STYLE CHOICE. `bake` invokes `cmd_push` with
    # its stdout at /dev/null — it prints its own phases — so a measurement
    # narrated on stdout is a measurement that caller never sees, and stderr is
    # the one channel every caller of this function keeps. This number is the point of the probe: it
    # is what tells a 29-minute push apart from a dead one, and what a field
    # test records.
    say "probe      ${PROBE_MB} MB through the tunnel in ${elapsed}s = ${kbps} KB/s (floor ${MIN_KBPS} KB/s)" >&2
    [ "$kbps" -ge "$MIN_KBPS" ] || die "the tunnel to ${id} is carrying ${kbps} KB/s, under the ${MIN_KBPS} KB/s floor.
   NOTHING WAS PUSHED, deliberately: a tree that needs a few minutes on a
   healthy tunnel needs hours on this one, and an hour of a push that looks
   alive is worse than a refusal — it was measured at ~7 KB/s on a real box,
   where a 213 MB push stalled twice at 16 MB and a 9 MB file took 18 minutes.
   This is the TUNNEL, not the box and not this wrapper. What has changed
   before: the base AMI (its SSM agent), the region's Session Manager data
   plane, and this machine's own network. 'census' prints the image each box is
   running; DJB_VERIFIER_AL2023_AMI pins a base that was measured to work.
   Take the box down, or raise the floor deliberately with DJB_VERIFIER_MIN_KBPS
   if a slow push is what you want."
}

# THE PACK, BUILT FROM A DEPTH-1 MIRROR. git has no `push --depth`: what it
# sends is decided by what the remote already has, and a remote that has
# nothing gets everything. A shallow SOURCE is the only lever, so the mirror is
# made here, in DJB_VERIFIER_HOME — outside every checkout, deliberately, for
# the same reason the private keys live there: a scratch repository inside the
# tree is a scratch repository the gate measures.
#
# THE RECEIVING END HAS TO ALLOW IT. A shallow push into a repository that has
# not opted in is refused with `shallow update not allowed` — measured. The
# config is set over the transport rather than in the bake seam so that it
# holds for a box launched from ANY image, including the ones already baked.
#
# WHAT A SHALLOW TREE ANSWERS ON THE BOX, measured rather than assumed: with
# `main` at the pushed commit, `git merge-base HEAD refs/heads/main` resolves
# to that commit both in the box's checkout and in the clone `verify_start.sh`
# makes from it — which is the same answer a full-history push gives, so the
# `--loop` fingerprint's `merge-base=` field is stable and the verifier's
# consult keys correctly. What WAS empty either way is "what did the active rung
# change" — the box carries one branch, so the diff against its own merge-base
# is nothing — and that is what `refs/djb/base` and `DJB_LOOP_SCOPE_BASE` are
# for: the fork point travels with the tree and the gate over there derives the
# scope this machine does. The loop ledger itself never travels — it lives in
# `.git/` and no push carries it — so a box's first `--loop` is a measure and
# its cell reads `miss(no-ledger)`, exactly as it did.
push_the_tree_shallow() {
    local id="$1" head_sha="$2" checkout="$3" base_sha="$4"
    shift 4
    local -a refs=("$@")
    local shallow got prc=0 depth=1 span=""
    shallow="${VERIFIER_HOME}/.shallow-$$"
    rm -rf "$shallow"
    mkdir -p "$VERIFIER_HOME"
    git init -q --bare "$shallow" 2>/dev/null || die "could not make the shallow mirror at ${shallow}"

    # `+HEAD:refs/heads/main` — the remote's HEAD, which is this checkout's
    # HEAD whatever branch it is on, landing on the mirror's `main`. Any extra
    # branch the caller named comes with it, all to the same depth. FETCHING
    # several refs in one invocation is fine and always was; it is PUSHING them
    # from a shallow source that cannot be done in one, which is argued at the
    # push itself.
    local -a fetch_refs=("+HEAD:refs/heads/main")
    local r
    for r in "${refs[@]}"; do
        case "$r" in
        "refs/heads/main:refs/heads/main") ;;
        *) fetch_refs+=("+${r%%:*}:${r%%:*}") ;;
        esac
    done
    # DEEP ENOUGH TO REACH THE FORK POINT, AND NOT ONE COMMIT DEEPER. The base
    # is an ancestor of HEAD, so `--depth <the rung's own commits + 1>` is
    # exactly HEAD..base inclusive — nothing before it comes across. What this
    # adds to the pack is the DELTA of the rung's own commits, against a tree
    # that is already nine megabytes; what it buys is a box that can say what
    # the rung changed. A rung with a long history falls back to depth 1 and
    # SAYS so rather than dragging a repository over a tunnel measured in tens
    # of kilobytes a second.
    if [ -n "$base_sha" ]; then
        span="$(git -C "$ROOT" rev-list --count "${base_sha}..HEAD" 2>/dev/null || echo "")"
        case "$span" in
        '' | *[!0-9]*) span="" ;;
        esac
        if [ -n "$span" ] && [ "$span" -le "$MAX_SCOPE_DEPTH" ]; then
            depth=$((span + 1))
        else
            # ON STDERR, for the reason the probe line below states in full:
            # `bake` sends this function's stdout to /dev/null, so a note
            # narrated on stdout is a note that caller never sees — and this one is
            # the only warning that the box's --loop is about to grade a rung
            # against an empty scope.
            say "note       the rung is ${span:-?} commits from its fork point (ceiling ${MAX_SCOPE_DEPTH}); the base is" >&2
            say "           NOT being carried and the box's --loop will derive an empty scope" >&2
            base_sha=""
        fi
    fi
    if ! git -C "$shallow" fetch -q --depth "$depth" "file://${ROOT}" "${fetch_refs[@]}"; then
        rm -rf "$shallow"
        die "could not build a depth-${depth} mirror of this checkout. Nothing was pushed."
    fi
    # THE BASE AS A REF, CREATED IN THE MIRROR RATHER THAN IN THIS CHECKOUT. A
    # linked worktree shares its refs with the whole family, so writing
    # `refs/djb/base` here would plant a ref in every other agent's checkout and
    # two rungs would overwrite each other's. The mirror is this run's own.
    if [ -n "$base_sha" ]; then
        if git -C "$shallow" update-ref refs/djb/base "$base_sha" 2>/dev/null; then
            : # it goes over in its own push, below — see THE ORDER
        else
            say "note       the fork point ${base_sha:0:8} is not in the mirror; the box's --loop will" >&2
            say "           derive an empty scope" >&2
            base_sha=""
        fi
    fi
    # THE MIRROR IS THE TREE THE HOOK VOUCHED FOR, or nothing goes. Without
    # this the wrapper could push a tree no wall ever saw, which is the whole
    # thing the vouch above exists to prevent.
    got="$(git -C "$shallow" rev-parse refs/heads/main 2>/dev/null || true)"
    if [ "$got" != "$head_sha" ]; then
        rm -rf "$shallow"
        die "the depth-1 mirror landed on ${got:-<nothing>} and this checkout's HEAD is
   ${head_sha}. Nothing was pushed: the tree the pre-push hook vouched for is
   not the tree that would have gone."
    fi

    # THE BOX'S OWN REFS ARE CLEARED BEFORE THE FIRST PUSH OF THIS CHECKOUT,
    # AND THIS IS THE FOURTH WAY A SHALLOW PUSH FAILS.
    #
    # WHAT HAPPENS WITHOUT IT. A push sends only what the sender believes the
    # receiver lacks, and it derives that belief from the refs the receiver
    # ADVERTISES: `main = <the bake commit>` is read as "and therefore
    # everything reachable from it". A freshly baked box is SHALLOW at that
    # commit — its checkout was seeded by this very function, so it holds that
    # commit's own objects and not one of its ancestors' — and every object the
    # sender omits on the strength of that advertisement is an object the
    # receiver does not have. The receiver then fails completing the pack. It
    # was measured in the field three banks running as `remote: fatal: pack has
    # 84 unresolved deltas` / `index-pack abnormal exit` / `! [remote rejected]
    # refs/djb/base -> refs/djb/base (unpacker error)`, and it reproduces on
    # this machine's git as `remote: error: Could not read <sha>` / `fatal:
    # revision walk setup failed` / `! [remote rejected] main -> main (missing
    # necessary objects)`. Two sentences, one mechanism.
    #
    # WHY NOT `--no-thin`, WHICH IS THE OBVIOUS FIX AND IS NOT ONE. `--thin`
    # governs whether DELTA BASES may live outside the pack; the OMISSION is
    # driven by the advertised refs and no flag turns it off. Measured, both
    # ways, in `test_verifier_box.sh`: `--no-thin` fails identically and the
    # ref-clear lands the tree. The case asserts all three outcomes precisely
    # so that this is not simplified back to the flag.
    #
    # ONCE PER CHECKOUT PER BOX, AND NOT EVERY PUSH. A receiver with no refs is
    # assumed to have nothing, so the pack is complete — and also whole, which
    # is the cost: the second push from the same checkout has a box that is no
    # longer shallow-at-a-stranger's-commit and can take an ordinary
    # incremental pack. Clearing every time would re-send the tree over a
    # tunnel measured in tens of kilobytes a second, every time.
    #
    # AND THE PARKED DERIVATION SURVIVES IT — `sync_box_worktree` is the other
    # half. Deleting the checked-out branch's ref leaves HEAD a symref to an
    # unborn branch; that function's `reset --hard refs/heads/main` recreates it
    # AT THE SAME NAME and moves the working tree with it, so the box is parked
    # exactly as the bake parked it and the per-branch DATABASE_NAME
    # `scripts/db.sh` derives is the one every other box derives. A clear
    # without that reset would leave a box with no branch at all.
    #
    # IT NEVER REFUSES. A box whose refs could not be cleared is a box the push
    # below may still land on — it is the ordinary state for every box that has
    # already had one — so this notes and carries on rather than turning a
    # remedy into a new way to fail.
    #
    # AND IT RIDES ON THE `receive.shallowUpdate` SESSION RATHER THAN TAKING
    # ONE OF ITS OWN. Both are "prepare this receiver for a shallow pack", they
    # are wanted at the same moment, and a second round trip is a second round
    # trip on a transport this file spends eighty lines apologising for. The
    # cost is that one status now covers two statements, so the note below
    # names both rather than claiming to know which failed.
    local marker park prep note_clear=""
    park="$(verifier_park_branch)"
    marker="$(box_dir "$id")/pushed-from"
    prep="git -C ${checkout} config receive.shallowUpdate true"
    if ! grep -qxF -- "$ROOT" "$marker" 2>/dev/null; then
        prep="git -C ${checkout} update-ref -d refs/heads/main; git -C ${checkout} update-ref -d refs/heads/${park}; git -C ${checkout} update-ref -d refs/djb/base; ${prep}"
        note_clear=1
        mkdir -p "$(box_dir "$id")"
        printf '%s\n' "$ROOT" >>"$marker"
    fi
    if ssh_to "$id" "${prep}; true" >/dev/null 2>&1; then
        [ -z "$note_clear" ] ||
            say "cleared    the box's main, ${park} and refs/djb/base before the first push from this checkout — a receiver that advertises nothing is assumed to have nothing, and a shallow box that advertises its bake commit is not" >&2
    elif [ -n "$note_clear" ]; then
        say "note       could not prepare ${id} for a shallow push — receive.shallowUpdate, or the" >&2
        say "           ref clear, or both. If the push below is refused for 'shallow update not" >&2
        say "           allowed', or fails with unresolved deltas / missing necessary objects," >&2
        say "           that is why." >&2
    else
        say "note       could not set receive.shallowUpdate on ${id}; a shallow push may be refused" >&2
    fi

    # GIT_SSH_COMMAND IS A STRING GIT HANDS TO A SHELL, NOT AN ARGV. The shell
    # splits it on whitespace, so the ProxyCommand — one option value with
    # eight spaces in it — has to be quoted INSIDE the string or ssh receives
    # `-o ProxyCommand=aws` and the rest of the session command as stray
    # arguments. FIELD TEST 1 paid for this line: `aws: [ERROR]: … the
    # following arguments are required: command`, `Connection closed by UNKNOWN
    # port 65535`, exit 128. `ssh_to` and `cmd_fetch` pass the option as one
    # argument and never needed it.
    # THE STATUS IS RETURNED, NEVER LEFT TO `set -e`. A caller that wants to do
    # something about a failed push — take a box down, say — has to invoke this
    # in a context where `set -e` is disabled, and in that context the `say`
    # below would run after a failed push and the function would return 0. The
    # explicit capture is what makes "the push failed" a thing a caller can ask.
    # AND THE SESSION STILL CARRIES THE KEEPALIVES, for a reason that is now
    # one step removed. `git push` is handed the REMOTE sha of every ref before
    # it runs its hooks, so it OPENS THE TRANSPORT FIRST and writes the pack
    # LAST — and anything slow in between is a tunnel sitting idle. FIELD TEST
    # 4 paid for it: a pre-push hook measured a full gate for 1807 s, the
    # Session Manager channel closed under it, and git died writing the pack
    # with exit 141 (128 + SIGPIPE) having printed nothing at all. The gate no
    # longer runs inside THIS push — the vouch above runs it against a local
    # repository, before the tunnel is touched — but the keepalives stay,
    # because a pack still takes minutes over this transport and a shallow
    # mirror's hooks are not the only thing that can pause a push. 30 s × 120
    # is an hour, which is longer than any push and shorter than forever.
    # WHAT THE OTHER TWO CARRY, since the difference is the argument. `ssh_to`
    # carries the INTERVAL and not the ceiling: one of its sessions is the
    # recipe itself — twenty minutes of `dnf` and `docker compose pull` with
    # long silences in the middle — so it needs bytes moving too, but the
    # default `ServerAliveCountMax` of 3 (90 s of unanswered probes) is the
    # right bound for a session whose other end should be answering. The 120
    # here is the deliberate loosening, and it is push's alone: only a push
    # holds a connection open across something that measures for half an hour
    # on THIS machine. `cmd_fetch` carries neither — one `scp` of one log.
    # ONE REF PER PUSH, AND IT IS A MEASUREMENT RATHER THAN A PREFERENCE.
    #
    # A SHALLOW SOURCE CANNOT SEND TWO REFS IN ONE INVOCATION. Measured 5/5 on
    # box-shaped repositories by the verifier and reproduced here on this
    # machine (git 2.39.5): from a shallow mirror, `push --force <remote> A B`
    # lands A and answers
    #
    #     ! [remote failure]  B -> B (remote failed to report status)
    #     error: failed to push some refs to '…'
    #
    # with exit 1. Isolated three ways: a NON-shallow mirror sends both in one
    # push and exits 0; the same shallow mirror sends both in two SEPARATE
    # pushes and exits 0 twice; and the order in the argument list changes
    # nothing — whichever ref is named second is the one that fails. It is not
    # about `refs/djb/base`: `main` plus an ordinary second branch fails
    # identically, which means the multi-branch form of `push` carried this
    # from the day it was written and nothing had ever sent two refs before the
    # fork point started travelling.
    #
    # WHY IT IS WORSE THAN A FAILED PUSH. `main` LANDS and the status is still
    # 1, so the box holds the tree while every caller reads a failure: `up`
    # refuses after a push that actually worked, and `cmd_bake`'s teardown
    # takes a bake box down for it.
    #
    # THE ORDER, and each status checked. The base FIRST: a base that will not
    # go is a box whose `--loop` would grade the rung against an empty scope,
    # and finding that out before the tree is sent leaves the box exactly as it
    # was. Then `main`, then any extra branch the caller named. The first
    # refusal stops the rest — a ref sent after a failure is a second thing to
    # explain in a message about the first.
    local -a push_order=()
    [ -z "$base_sha" ] || push_order+=("refs/djb/base:refs/djb/base")
    push_order+=("${refs[@]}")
    local ssh_cmd one_ref="" sent=""
    ssh_cmd="ssh -i '$(box_key "$id")' -o 'ProxyCommand=$(proxy_command)' -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ServerAliveInterval=30 -o ServerAliveCountMax=120"
    for one_ref in "${push_order[@]}"; do
        prc=0
        GIT_SSH_COMMAND="$ssh_cmd" \
            git -C "$shallow" push --force "ssh://$(verifier_box_user)@${id}${checkout}" "$one_ref" || prc=$?
        [ "$prc" = "0" ] || break
        sent="${sent}${sent:+ }${one_ref}"
    done
    rm -rf "$shallow"
    if [ "$prc" != "0" ]; then
        # A 141 SAYS WHAT IT IS, because it arrives with nothing beside it.
        # git that dies on a write prints no `fatal:` and the hook that passed
        # prints nothing more, so the bare number reads — and was read — as a
        # hook refusal. A hook's own refusal is `git push` exit 1 whatever
        # status the hook exited with, so a 141 is NEVER the hook's.
        if [ "$prc" = "141" ]; then
            echo "!! verifier_box: git took SIGPIPE (exit 141) writing the pack — the transport" >&2
            echo "   died before the pack was written. git opens this connection FIRST and" >&2
            echo "   writes the pack LAST, so anything slow in between is an idle tunnel." >&2
            echo "   Nothing refused: the wall on this machine ran BEFORE the tunnel was opened" >&2
            echo "   and passed. This is the transport. Try again; if it repeats, the tunnel is" >&2
            echo "   the thing to look at — 'census' prints the image each box is running." >&2
        else
            # AND EVERY OTHER NON-ZERO, because 141 IS NOT THE ANSWER
            # EVERYWHERE. git's exit when the far end goes away mid-write is
            # the platform's rather than git's contract: where SIGPIPE reaches
            # git the shell reports 128+13, and where git handles the EPIPE
            # itself it exits 1 — the same number a refusal gives. This
            # repository's own CI met the difference (this machine and an
            # Alpine box both answer 141; the Ubuntu runner answered 1 with the
            # same transport dying in the same place), so the branch above
            # cannot be the only sentence or the commonest failure on some
            # machine is a bare number that reads as the wrong thing.
            #
            # IT DOES NOT GUESS. git's stderr is the operator's, streamed live
            # and never captured — an eleven-minute push with its progress
            # swallowed so the wrapper could grep it would be a worse trade — so
            # this names the two readings and the line of git's own output that
            # decides between them.
            echo "!! verifier_box: the transfer failed (git exit ${prc}). FOUR THINGS LOOK LIKE THIS," >&2
            echo "   and git's own words above tell them apart:" >&2
            echo "     THE RECEIVER REFUSED A SHALLOW HISTORY — 'shallow update not allowed'. The" >&2
            echo "     pack sent here is a depth-1 mirror, and a repository that has not set" >&2
            echo "     receive.shallowUpdate rejects it. This wrapper sets that config over the" >&2
            echo "     transport before every push; if the line above says it could not, that is" >&2
            echo "     the thing to fix and the box is otherwise fine." >&2
            echo "     THE TRANSPORT DIED mid-pack — 'the remote end hung up', a 'Broken pipe', a" >&2
            echo "     'write error', or the tunnel's own death. Retry; a tunnel that keeps doing" >&2
            echo "     it is a finding about the tunnel, not about this tree." >&2
            echo "     THE REMOTE END REFUSED THE REF — a non-fast-forward or a checked-out branch." >&2
            echo "     The box's repository parks itself off main for exactly that reason; a box" >&2
            echo "     sitting ON main needs receive.denyCurrentBranch=updateInstead, which its" >&2
            echo "     own user-data sets." >&2
            echo "     THE BOX IS SHALLOW AND STILL ADVERTISING ITS OWN REFS — 'pack has N" >&2
            echo "     unresolved deltas' with 'index-pack abnormal exit', or 'Could not read" >&2
            echo "     <sha>' with 'missing necessary objects'. A push omits whatever the" >&2
            echo "     receiver's advertised refs imply it already has, and a freshly baked box" >&2
            echo "     is shallow at its bake commit and has none of that commit's ancestors." >&2
            echo "     This wrapper clears the box's main, its parking branch and refs/djb/base" >&2
            echo "     before the FIRST push from each checkout; if the line above says it could" >&2
            echo "     not, that is the thing to fix. By hand, once, then push again:" >&2
            echo "       scripts/verifier_box.sh run ${id} -- \"cd ${checkout} && git update-ref -d refs/heads/main && git update-ref -d refs/heads/\$(sed -n 's|^BAKE_PARK_BRANCH=\"\\(.*\\)\"\$|\\1|p' deploy/verifier/bake.sh)\"" >&2
            echo "     --no-thin does NOT fix this: thin packs govern delta bases, the omission" >&2
            echo "     is driven by the advertised refs. Measured both ways in test_verifier_box.sh." >&2
            echo "   The wall on THIS machine already passed: it ran before the tunnel was opened." >&2
        fi
        # WHICH REF, AND WHAT IS ALREADY OVER THERE. Each ref is its own push
        # now, so the box's state after a failure is a fact rather than a
        # guess, and a reader who has to decide whether to retry or to take the
        # box down needs it in the same breath as the exit code.
        echo "   THE REF THAT FAILED: ${one_ref}." >&2
        if [ -n "$sent" ]; then
            echo "   Already landed on the box before it: ${sent}." >&2
        else
            echo "   Nothing landed on the box: this was the first ref sent." >&2
        fi
        return "$prc"
    fi
    if [ -n "$base_sha" ]; then
        say "pushed $(printf '%s ' "${push_order[@]}")to ${id}:${checkout} (depth ${depth}: the tree and the rung's own ${span} commit(s), not the history; one push per ref)"
    else
        say "pushed $(printf '%s ' "${push_order[@]}")to ${id}:${checkout} (depth-1: the tree, not the history)"
    fi
}

# THE PUSH MOVES A REF; THE GATE MEASURES A WORKING TREE. THEY ARE NOT THE SAME
# THING, AND UNTIL THIS FUNCTION EXISTED EVERY BOX CONSULT MEASURED THE IMAGE.
#
# MEASURED ON THE FIRST REAL CONSULT, 2026-09-18, and it came back GREEN —
# `4004 passed`, `ok: loop checks passed` — with a banked key naming a tree
# nobody had pushed: the tree the IMAGE WAS BAKED FROM. The mechanism is
# straightforward once seen. The push updates `refs/heads/main` on the box. The
# box's checkout is parked on a branch that is not main (the bake parks it there
# precisely so a push to main is legal), and a push moves no working tree. So the
# box's files were the bake's files, `./scripts/check.sh --loop` measured those,
# and the verdict it banked was honest about a tree that had nothing to do with
# the rung. The old agreement line compared the REF and printed "=" while the
# measured tree was stale — an instrument agreeing with itself.
#
# `reset --hard refs/heads/main` WHILE PARKED, AND NOT `checkout main`. Checking
# main out would make it the current branch, and the NEXT push to main would then
# be refused by the receiver (or, with `denyCurrentBranch=updateInstead`, would
# start caring about the box's dirt). Resetting moves the PARKING branch and the
# working tree onto main's commit and leaves main un-checked-out, which is the
# property the bake's park exists to create. One command, and the box keeps its
# shape.
#
# AND NO `git clean`. A reset leaves untracked files alone, which is the point:
# the box's `.env` — carrying the pinned DATABASE_NAME the image was built with —
# and its `.venv` are untracked, and a clean would take both and leave a box that
# cannot run the gate at all.
sync_box_worktree() {
    local id="$1" checkout="$2" here there rung
    ssh_to "$id" "git -C ${checkout} reset --hard refs/heads/main" >/dev/null ||
        die "could not move the box's working tree onto the pushed main. The ref landed and
   the files did not, which is the shape that measured the image for a whole
   cycle: the gate over there would grade whatever the box is standing on."
    here="$(git -C "$ROOT" rev-parse "HEAD^{tree}")"
    there="$(ssh_to "$id" "git -C ${checkout} rev-parse HEAD^{tree}" 2>/dev/null | tr -d '\r' | tail -n 1 || true)"
    [ "$here" = "$there" ] ||
        die "the box's WORKING TREE is ${there:-<unreadable>} and this checkout's is ${here}.
   The ref moved and the files did not agree with it. A gate on the box would
   measure that tree and bank an honest verdict about the wrong thing —
   which is exactly what every consult before this check did. Nothing further
   was attempted."
    rung="$(box_rung "$id")"
    # THE TREE, NOT THE COMMIT, and that is the whole correction. A commit sha
    # says which history; the gate's verdict is keyed on the TREE, so the tree is
    # what has to agree and the tree is what this prints.
    printf 'tree       HEAD %s = box WORKTREE %s · rung %s\n' "${here:0:8}" "${there:0:8}" "$rung"
}

# =============================================================================
# run / loop / wait / fetch
# =============================================================================
# THE INGEST, PREPENDED TO THE COMMAND LINE THAT RUNS THE GATE.
#
# `cmd_push` leaves the drive rows at `~/verify/<rung>/ledger.in` and reads
# nothing; this is the one place they enter the box's own ledger, and it runs
# immediately before the gate that will consult it. A separate `ingest`
# subcommand would be a second round trip over a tunnel measured in tens of
# kilobytes a second for a loop that already opens one.
#
# IDEMPOTENT BY LINE, AND THAT IS THE WHOLE CONTRACT. `grep -qxF -- "$l"` is a
# WHOLE-LINE fixed-string match, so a row that is already there is never
# appended twice however many times a push and a run are repeated — at-least-once
# is the assumption everywhere here (principle 16), and two rows for one
# measurement is a count nobody can read afterwards. An empty line is skipped
# rather than appended, because `grep -qxF ""` matches every line and would
# make the guard itself the bug.
#
# THE BOX'S LEDGER IS `<checkout>/.git/djb-gate-verdicts`, which is where
# `gate_ledger_path` resolves over there: the box is a plain clone with no
# worktrees, so its common git dir is `.git`. `cmd_harvest` reads the loop
# ledger beside it on the same assumption.
#
# NO `$VAR` OF OURS SURVIVES INTO IT. Everything this composes is expanded HERE
# except `$l`, which is escaped so the BOX's shell owns it — the rule the two
# remote strings below already live by.
box_ledger_ingest() {
    local checkout="$1" rung="$2" ledger="$1/.git/djb-gate-verdicts" incoming="~/verify/$2/ledger.in"
    # THE GROUP AND THE `|| true` ARE INSIDE IT, and both are load-bearing. The
    # caller splices this into a single `&&` chain that ends in the gate, so an
    # ingest that reported non-zero — a full disk, a ledger the box cannot
    # append to — would SILENTLY SKIP THE GATE and `loop` would wait forever on
    # a log nothing wrote. A carrier that fails costs a re-drive; it may never
    # cost a run. Written `{ …; fi || true; }` rather than `… || true` after the
    # group, because `A && B || true && C` parses as `((A && B) || true) && C`
    # and would run the gate over a `cd` that failed.
    echo "{ if [ -f ${incoming} ]; then while IFS= read -r l; do [ -z \"\$l\" ] || grep -qxF -- \"\$l\" ${ledger} 2>/dev/null || printf '%s\\n' \"\$l\" >> ${ledger}; done < ${incoming}; fi || true; }"
}

cmd_run() {
    local id="${1:-}"
    shift || true
    [ -n "$id" ] || die "run needs an instance id"
    [ "${1:-}" = "--" ] || die "run takes: run <id> -- <command...>"
    shift
    [ "$#" -gt 0 ] || die "run needs a command after --"
    refuse_if_reclaimed "$id"
    # The remote status is the verdict and it is passed through untouched.
    ssh_to "$id" "$@"
}

cmd_loop() {
    local id="${1:-}"
    shift || true
    [ -n "$id" ] || die "loop needs an instance id"
    local name=""
    while [ "$#" -gt 0 ]; do
        case "$1" in
        --log)
            name="${2:-}"
            shift 2 || die "--log takes a name"
            ;;
        *) die "unknown argument '$1' to loop" ;;
        esac
    done
    [ -n "$name" ] || die "loop needs --log <name>"
    refuse_if_reclaimed "$id"
    local rung checkout remote pid
    rung="$(box_rung "$id")"
    checkout="$(verifier_checkout_path)"

    # BEFORE ANYTHING IS LAUNCHED: IS THE BOX STANDING ON THE TREE THAT WAS
    # PUSHED? A push moves `refs/heads/main` and no files, and the box's checkout
    # is parked off main by design — so a box whose worktree was never moved onto
    # the pushed main runs the gate over the tree the IMAGE was baked from and
    # banks a verdict that is honest about the wrong thing. That is not
    # hypothetical: it is what the first real consult did, green, for a tree
    # nobody had sent. `cmd_push` moves the files now, and this is the belt —
    # because the expensive, silent, plausible failure is a gate that runs for
    # two minutes and answers about the image.
    #
    # TWO TREES, NOT TWO COMMITS. The verdict is keyed on a tree; the tree is
    # what has to agree.
    local box_head_tree box_main_tree
    box_head_tree="$(ssh_to "$id" "git -C ${checkout} rev-parse HEAD^{tree}" 2>/dev/null | tr -d '\r' | tail -n 1 || true)"
    box_main_tree="$(ssh_to "$id" "git -C ${checkout} rev-parse refs/heads/main^{tree}" 2>/dev/null | tr -d '\r' | tail -n 1 || true)"
    { [ -n "$box_head_tree" ] && [ -n "$box_main_tree" ]; } ||
        die "could not read the box's own trees (worktree '${box_head_tree:-<unreadable>}',
   main '${box_main_tree:-<unreadable>}'). A gate launched now would measure a tree
   nothing here can name. Nothing was launched."
    [ "$box_head_tree" = "$box_main_tree" ] ||
        die "the box's checkout is not the pushed tree — run push ${id}.
   its working tree is ${box_head_tree}
   its main is       ${box_main_tree}
   A push moves a ref; it moves no files, and this box parks off main on purpose.
   A gate launched now would measure what the image was baked with and bank a
   verdict about it. Nothing was launched."

    # THE REDIRECT IS ON THE BOX AND THE GATE IS NEVER PIPED: the gate refuses a
    # piped stdout, and its exit status is the verdict, so it is written to its
    # own file rather than carried back over a connection that can drop.
    # THE SCOPE BASIS, NAMED ON THE COMMAND LINE. The push put the rung's fork
    # point on the box as `refs/djb/base`; without this the gate over there
    # derives its changed-file set from a depth-1 history where HEAD, `main` and
    # their merge-base are one commit, and answers EMPTY for a rung that touched
    # six files here. The gate reads the name only when its own history reaches
    # no fork point, so a box that never received the ref (an old image, a push
    # that declined to carry it) behaves exactly as it did.
    # THE DRIVE ROWS ENTER THE BOX'S LEDGER FIRST, and before the gate rather
    # than at push time: `cmd_push` only lands the file. See `box_ledger_ingest`.
    local ingest
    ingest="$(box_ledger_ingest "$checkout" "$rung")"
    # THE WHOLE LIST IS GROUPED AND THE REDIRECTS ARE ON THE GROUP, and that
    # is the difference between a detach and a forty-minute hang.
    #
    # `A && B && C && setsid … >/dev/null 2>&1 & echo $!` reads as if the
    # redirects covered the background job. They do not: `&` binds to the
    # ENTIRE `&&` list, bash runs that list in a SUBSHELL, and the
    # `>/dev/null 2>&1` is attached to `setsid` alone — so the subshell keeps
    # the ssh channel's stdout and stderr open for as long as the gate runs.
    # sshd will not close a channel a process still holds, so `ssh` does not
    # return, so the command substitution below does not return, and a command
    # whose whole purpose is to detach blocks its caller for the length of the
    # thing it detached.
    #
    # MEASURED ON A REAL BOX (2026-09-21, c7g.4xlarge, us-east-1d), three
    # shapes, one payload:
    #     setsid nohup sh -c 'sleep 45' >/dev/null 2>&1 & echo $!      ->  8 s
    #     mkdir … && cd … && setsid … >/dev/null 2>&1 & echo $!        -> 46 s
    #     { mkdir … && cd … && setsid …; } </dev/null >/dev/null 2>&1 & echo $!
    #                                                                  ->  7 s
    # and `loop` itself, before this line, returned after 400 s — printing
    # `gate detached … as pid` at the END of a 386 s gate. Four builders
    # reported it as a hang; it is the shell's operator precedence.
    #
    # STDIN IS CLOSED TOO. It is not what was holding the channel here — the
    # first shape above inherits it and still returns in 8 s — but a detached
    # gate that can read the caller's stdin is a gate that can eat the
    # operator's next keystroke, and the group is where to say so once.
    remote="{ mkdir -p ~/verify/${rung} && cd ${checkout} && ${ingest} && setsid nohup sh -c 'DJB_LOOP_SCOPE_BASE=refs/djb/base ./scripts/check.sh --loop > ~/verify/${rung}/${name}.log 2>&1; echo \$? > ~/verify/${rung}/${name}.rc'; } </dev/null >/dev/null 2>&1 & echo \$!"
    pid="$(ssh_to "$id" "$remote" | tr -d '\r' | tail -n 1)"
    case "$pid" in '' | *[!0-9]*) die "the box did not return a pid for the detached gate" ;; esac
    printf '%s\n' "$pid" >"$(box_dir "$id")/${name}.pid"
    say "gate detached on ${id} as pid ${pid}; log ~/verify/${rung}/${name}.log"
    say "read it with: scripts/verifier_box.sh wait ${id} ${name}"
}

# =============================================================================
# leg — `loop` for ONE UNIT of the gate, which is what a bank on boxes is
# =============================================================================
#
# WHAT IT IS. `loop` runs the whole per-rung gate on one box. `leg` runs ONE
# UNIT of the FULL gate — `./scripts/check.sh --leg <unit> [--shard k/N]
# [--passes 1|2]`, the same argv CI's matrix hands each runner — so N boxes can
# each carry one unit and the Mac can compose one verdict out of what they
# return.
#
# AND A MODIFIER THE GATE GREW IS A MODIFIER THIS HAS TO FORWARD, which is a
# sentence paid for. `--passes` arrived on the gate and on the bank's plan in
# one wave, both sides citing this argv — and neither drove it, because the
# bank's own drive stubs this file. The first real sharded bank after they
# merged came down on `unknown argument '--passes' to leg` with every box up
# and paid for. A seam asserted on both sides of a stub is a seam nobody
# asserted; `test_verifier_box.sh` now asserts the forwarding here.
# `scripts/pm_push.sh --bank --on-boxes N` is the only caller, and the argv
# below is the seam between the two: that script stubs this wrapper and asserts
# exactly this shape, this drive asserts the real parser takes it, and the two
# halves were built in parallel behind that one sentence.
#
# THE REMOTE STRING IS `cmd_loop`'s, DUPLICATED RATHER THAN SHARED, and that is
# deliberate (principle 11 — two callers are not a shared concept). A "detach"
# helper parameterised over the command would be an indirection whose whole
# body is one `printf`, and the two strings differ in the one place that
# matters and must stay readable side by side: `loop` names the scope basis,
# `leg` does not.
#
# A UNIT IS NOT A SCOPE, which is why `DJB_LOOP_SCOPE_BASE` is absent here.
# `--loop` derives a changed-file scope and needs the rung's fork point named
# on the box; `--leg <unit>` runs the unit whole, exactly as a full gate does,
# so a scope basis would be a variable the leg never reads — and a variable
# that is set on one box and not another is the kind of difference a composed
# verdict cannot see.
#
# AND IT PASSES NO OPINION ABOUT WHICH UNITS EXIST. The unit table is
# `scripts/check.sh --list-legs`'s and the box's own gate refuses an unknown
# unit with exit 2, which `wait` passes through unchanged. A second list here
# would be a second authority that goes stale the first time a unit is added.
# What IS refused here is a unit or a shard that could not be a unit or a
# shard at all — see the charset wall below, which is about the quoting and
# never about the table.
cmd_leg() {
    local id="${1:-}"
    shift || true
    [ -n "$id" ] || die "leg needs an instance id: leg <id> --unit <unit> [--shard k/N] [--passes 1|2] --log <name>"
    local unit="" shard="" passes="" name=""
    while [ "$#" -gt 0 ]; do
        case "$1" in
        --unit)
            unit="${2:-}"
            shift 2 || die "--unit takes a unit name"
            ;;
        --shard)
            shard="${2:-}"
            shift 2 || die "--shard takes k/N"
            ;;
        --passes)
            passes="${2:-}"
            shift 2 || die "--passes takes 1 or 2"
            ;;
        --log)
            name="${2:-}"
            shift 2 || die "--log takes a name"
            ;;
        *) die "unknown argument '$1' to leg" ;;
        esac
    done
    [ -n "$unit" ] || die "leg needs --unit <unit>: it runs ONE unit of the full gate, and the
   units are the gate's own — ./scripts/check.sh --list-legs prints them."
    [ -n "$name" ] || die "leg needs --log <name>: the box writes the unit's output to
   ~/verify/<rung>/<name>.log and its status to <name>.rc, and 'wait <id> <name>'
   is how they are read back."
    # THE CHARSET WALL, AND IT IS ABOUT THE QUOTING RATHER THAN THE TABLE. Both
    # values are interpolated into a single-quoted `sh -c '…'` on the box, so a
    # value carrying a quote would end that string and run whatever followed it
    # as the box's own shell. Nothing here knows which units exist; it knows
    # only that a unit name is a word and a shard is two numbers.
    case "$unit" in
    *[!A-Za-z0-9._-]* | "") die "'${unit}' is not a unit name — letters, digits, dot, underscore
   and hyphen only. Nothing was sent. (Which units EXIST is the box's gate's
   answer, not this wrapper's: ./scripts/check.sh --list-legs.)" ;;
    esac
    if [ -n "$shard" ]; then
        case "$shard" in
        *[!0-9/]* | */*/* | /* | */) die "--shard takes k/N, got '${shard}'. Nothing was sent." ;;
        */*) ;;
        *) die "--shard takes k/N, got '${shard}'. Nothing was sent." ;;
        esac
    fi
    # AND THE PASS COUNT IS THE SAME WALL FOR THE SAME REASON — it lands in the
    # same single-quoted `sh -c '…'`, so a value carrying a quote would end that
    # string. `1|2` is the SHAPE and nothing here decides what the counts mean:
    # that one pass is legal only beside a shard, that two is the default and
    # normalises away, that a unit with no suite has no pass to drop — all of
    # that is the box's gate's, exactly as WHICH units exist is. A second
    # opinion here would be a second authority to keep in step, and the one
    # thing this wrapper must not do is answer a question it was not asked.
    #
    # WHY IT IS REFUSED HERE AT ALL, then: a value the gate would refuse costs a
    # launched box and a round trip to discover, and the bank that hands this
    # flag has N of them up and billing while it finds out. Nothing was sent.
    if [ -n "$passes" ]; then
        case "$passes" in
        1 | 2) ;;
        *) die "--passes takes 1 or 2, got '${passes}'. Nothing was sent." ;;
        esac
    fi
    refuse_if_reclaimed "$id"
    local rung checkout remote pid
    rung="$(box_rung "$id")"
    checkout="$(verifier_checkout_path)"

    # THE SAME PRE-FLIGHT `loop` PAYS, AND FOR THE SAME REASON MULTIPLIED BY N.
    # A push moves `refs/heads/main` and no files; a box whose worktree was
    # never moved onto the pushed main measures the tree the IMAGE was baked
    # from and answers honestly about the wrong thing. On a bank that is not one
    # wasted verification but one shard of a composed verdict that would be
    # green — and the composition's own tree check (`pm_push.sh`, the log's
    # "The tree it ran on was") only catches it AFTER the whole leg's wall has
    # been paid on every box. Two round trips, before a seven-minute unit.
    local box_head_tree box_main_tree
    box_head_tree="$(ssh_to "$id" "git -C ${checkout} rev-parse HEAD^{tree}" 2>/dev/null | tr -d '\r' | tail -n 1 || true)"
    box_main_tree="$(ssh_to "$id" "git -C ${checkout} rev-parse refs/heads/main^{tree}" 2>/dev/null | tr -d '\r' | tail -n 1 || true)"
    { [ -n "$box_head_tree" ] && [ -n "$box_main_tree" ]; } ||
        die "could not read the box's own trees (worktree '${box_head_tree:-<unreadable>}',
   main '${box_main_tree:-<unreadable>}'). A unit launched now would measure a tree
   nothing here can name. Nothing was launched."
    [ "$box_head_tree" = "$box_main_tree" ] ||
        die "the box's checkout is not the pushed tree — run push ${id}.
   its working tree is ${box_head_tree}
   its main is       ${box_main_tree}
   A push moves a ref; it moves no files, and this box parks off main on purpose.
   A unit launched now would measure what the image was baked with and its shard
   of a composed verdict would vouch for it. Nothing was launched."

    # THE REDIRECT IS ON THE BOX AND THE UNIT IS NEVER PIPED, for `cmd_loop`'s
    # reason: the gate refuses a piped stdout, and its exit status is the
    # shard's verdict, so it is written to its own file rather than carried back
    # over a connection that can drop.
    # THE SAME INGEST `loop` PAYS, for the reason a bank multiplies: every box
    # of one image can honour every other's drive rows now, and a shard that
    # re-drove thirty drives is the cost the carrier exists to remove.
    local ingest
    ingest="$(box_ledger_ingest "$checkout" "$rung")"
    # THE MODIFIER IS APPENDED AFTER THE SHARD AND ONLY WHERE IT WAS TYPED.
    # Absent, the string below is byte-for-byte the one it always was — never
    # `--passes ` with nothing after it and never a `2` this wrapper supplied,
    # because the gate sets its "a count was typed" flag the moment it SEES
    # the word and either would make a run that asked for nothing different
    # from the run it has always been.
    # GROUPED AND REDIRECTED, for the reason spelled out in full at `cmd_loop`'s
    # own detach: `&` binds to the whole `&&` list and the redirects would
    # otherwise cover only `setsid`, so the list's subshell holds the ssh
    # channel for the length of the leg and the detach blocks its caller.
    remote="{ mkdir -p ~/verify/${rung} && cd ${checkout} && ${ingest} && setsid nohup sh -c './scripts/check.sh --leg ${unit}${shard:+ --shard ${shard}}${passes:+ --passes ${passes}} > ~/verify/${rung}/${name}.log 2>&1; echo \$? > ~/verify/${rung}/${name}.rc'; } </dev/null >/dev/null 2>&1 & echo \$!"
    pid="$(ssh_to "$id" "$remote" | tr -d '\r' | tail -n 1)"
    case "$pid" in '' | *[!0-9]*) die "the box did not return a pid for the detached unit" ;; esac
    printf '%s\n' "$pid" >"$(box_dir "$id")/${name}.pid"
    say "unit ${unit}${shard:+ shard ${shard}}${passes:+ passes ${passes}} detached on ${id} as pid ${pid}; log ~/verify/${rung}/${name}.log"
    say "read it with: scripts/verifier_box.sh wait ${id} ${name}"
}

cmd_wait() {
    local id="${1:-}" name="${2:-}"
    { [ -n "$id" ] && [ -n "$name" ]; } || die "wait takes: wait <id> <name>"
    local pidfile rung pid alive rc
    pidfile="$(box_dir "$id")/${name}.pid"
    [ -r "$pidfile" ] || die "no detached gate named '${name}' for ${id} on this machine"
    pid="$(cat "$pidfile")"
    rung="$(box_rung "$id")"
    while :; do
        refuse_if_reclaimed "$id"
        alive="$(ssh_to "$id" "kill -0 ${pid} 2>/dev/null && echo alive || echo gone" | tr -d '\r' | tail -n 1)"
        [ "$alive" = "alive" ] || break
        sleep "$ONLINE_POLL_SECONDS"
    done
    rc="$(ssh_to "$id" "cat ~/verify/${rung}/${name}.rc 2>/dev/null || echo 2" | tr -d '\r' | tail -n 1)"
    echo "--- last 40 lines of ~/verify/${rung}/${name}.log ---"
    ssh_to "$id" "tail -n 40 ~/verify/${rung}/${name}.log 2>/dev/null || true" || true
    echo "--- gate exit ${rc} ---"
    case "$rc" in '' | *[!0-9]*) die "the box did not record an exit status for '${name}'" ;; esac
    exit "$rc"
}

# =============================================================================
# harvest — the box's banked --loop row comes home
# =============================================================================
#
# WHAT IT IS FOR. A builder's last boundary is one `--loop`, and when that
# `--loop` ran on a box the verdict it banked is in the BOX's ledger. The
# verifier's consult then runs on another box from the same image at the same
# pushed sha, derives the same key, and HITS — but only if the row is
# somewhere the consult can see it. `harvest` is the one command that brings
# it back, and it is a separate command rather than part of `wait` for one
# reason: a harvest that cannot is exit 2, and folding it into `wait` would
# let that mask a green gate's own status.
#
# THE ROW IS COPIED VERBATIM, WITH ONE FIELD APPENDED. It is the BOX's
# measurement and every field in it is the box's answer — the tree, the
# environment fingerprint, the five components, the seconds. Re-deriving any
# of them here would be this machine's answer wearing the box's verdict.
# ` box=<id>` is appended by the precedent every field on this row has
# followed since it existed (`sanction=`, then `tree=`/`env=`, then the
# components): APPEND, NEVER INSERT, so every reader that existed before this
# field parses the row exactly as it did.
#
# AND THE PATH COMES FROM `gate_ledger.sh`, SOURCED. The loop ledger has one
# owner and one spelling of where it lives; a wrapper that composed
# `.git/djb-loop-verdicts` itself would be a second opinion about a file with
# one, and the day `loop_ledger_path` changes the harvested rows would land
# somewhere no consult looks. The sourcing is inside this function — the
# precedent is `scripts/pm_push.sh`'s and `scripts/githooks/pre-push`'s — so
# every other subcommand is byte-for-byte the script it was.
cmd_harvest() {
    local id="${1:-}" name="${2:-}"
    { [ -n "$id" ] && [ -n "$name" ]; } ||
        die "harvest takes: harvest <id> <name> — the <name> a 'loop <id> --log <name>' used."
    [ -r "$ROOT/scripts/gate_ledger.sh" ] ||
        die "no ${ROOT}/scripts/gate_ledger.sh — nothing here knows where a loop verdict lives,
   and this wrapper will not invent a second answer. Nothing was harvested."
    # shellcheck source=scripts/gate_ledger.sh
    . "$ROOT/scripts/gate_ledger.sh"
    refuse_if_reclaimed "$id"

    local rung checkout scratch key="" seen=0 line tok rc=0
    rung="$(box_rung "$id")"
    checkout="$(verifier_checkout_path)"
    scratch="${VERIFIER_HOME}/.harvest-$$"
    rm -rf "$scratch"
    mkdir -p "$scratch"

    # THE LOG IS READ OVER THE TRANSPORT, FROM WHERE THE BOX WROTE IT, and not
    # from wherever a `fetch` happened to put it: `harvest <id> <name>` knows
    # the box and the name and nothing about this machine's filesystem, and a
    # third argument for a path the caller already chose would be a way for
    # the two copies to disagree.
    ssh_to "$id" "cat ~/verify/${rung}/${name}.log" >"$scratch/loop.log" 2>/dev/null || rc=$?
    if [ "$rc" != "0" ]; then
        rm -rf "$scratch"
        die "could not read ~/verify/${rung}/${name}.log on ${id} (exit ${rc}). Nothing was
   harvested and nothing was appended. That is the transport or a name that
   never ran, never a verdict."
    fi

    # THE KEY IS THE TOKEN UNDER THE `banked:` SENTENCE, which is where
    # `scripts/check.sh` prints it. Read the whole file and slice — a reader
    # that leaves early kills its producer, and this one is reading a gate log.
    while IFS= read -r line; do
        case "$line" in
        *"banked: this --loop verdict"*)
            seen=1
            continue
            ;;
        esac
        [ "$seen" = "1" ] || continue
        for tok in $line; do
            case "$tok" in
            loop-v1:*)
                key="$tok"
                break
                ;;
            esac
        done
        [ -z "$key" ] || break
    done <"$scratch/loop.log"

    if [ -z "$key" ] || ! printf '%s' "$key" | grep -E "$LOOP_KEY_RE" >/dev/null; then
        rm -rf "$scratch"
        die "the log for '${name}' on ${id} banks no verdict — there is nothing to harvest and
   NOTHING WAS APPENDED. A --mine run banks nothing (it walked no closure), a red
   run banks nothing, and a run whose tree moved underneath it banks nothing; the
   log itself says which. Harvesting anyway would put a key in this checkout's
   ledger that no measurement stands behind."
    fi

    # THE BOX'S OWN LEDGER, AT THE ONE PATH ITS CHECKOUT KEEPS IT. The box is a
    # plain clone with no worktrees, so its common git dir is `.git` — the same
    # place `loop_ledger_path` resolves to over there.
    rc=0
    ssh_to "$id" "cat ${checkout}/.git/djb-loop-verdicts" >"$scratch/box-ledger" 2>/dev/null || rc=$?

    local row="" f1 f2 rest
    if [ "$rc" = "0" ]; then
        while IFS= read -r line; do
            case "$line" in
            *" ${key} "*)
                read -r f1 f2 rest <<<"$line"
                [ "$f2" = "$key" ] && row="$line"
                ;;
            esac
        done <"$scratch/box-ledger"
    fi
    if [ -z "$row" ]; then
        rm -rf "$scratch"
        die "the log on ${id} says it banked ${key}, and that box's own loop ledger
   (${checkout}/.git/djb-loop-verdicts) has no row for it. NOTHING WAS APPENDED.
   A row composed here would be this machine's opinion of the box's measurement."
    fi
    rm -rf "$scratch"

    local local_path
    local_path="$(cd "$ROOT" && loop_ledger_path)" ||
        die "could not resolve this checkout's loop ledger. Nothing was appended."

    # THE DRIVE ROWS COME HOME WITH THE LOOP ROW, AND BEFORE IT.
    #
    # WHY THEY TRAVEL AT ALL. The machine half of a drive key is the IMAGE on a
    # box, so a row the box banked is a row every box of that image can honour —
    # and a row banked HERE is a Mac row that no box will ever hit and no box's
    # row will ever collide with. Bringing them back is what makes the carrier
    # two-way: `cmd_push` ships this checkout's rows out, this brings the box's
    # new ones in, and the next box of the same image starts warm.
    #
    # ONLY THE ROWS AT THE HARVESTED TREE. A box may hold rows from an earlier
    # tree it measured for somebody else; those are somebody else's evidence and
    # this command is about ONE measurement. The `tree=` field of the loop row
    # being harvested is the whole filter.
    #
    # BEFORE the already-home check below, deliberately: a second harvest must
    # still be able to bring rows a re-run banked after the first, and the
    # append is idempotent line by line, so running it twice is one row.
    local tree
    tree="$(loop_component_value "$row" tree)"
    harvest_drive_rows "$id" "$checkout" "${tree:-}"

    # ALREADY HOME IS EXIT 0, NOT A REFUSAL. At-least-once is the assumption
    # everywhere here: a builder who re-runs the command, or a brief that
    # lists the step twice, must not leave two rows for one measurement.
    if [ -r "$local_path" ]; then
        while IFS= read -r line; do
            case "$line" in
            *" ${key} "*)
                read -r f1 f2 rest <<<"$line"
                if [ "$f2" = "$key" ]; then
                    say "already harvested: ${key} is in this checkout's loop ledger — nothing appended."
                    printf 'banked: tree %s key %s box=%s\n' \
                        "$(loop_component_value "$line" tree)" "$key" "$id"
                    return 0
                fi
                ;;
            esac
        done <"$local_path"
    fi

    printf '%s box=%s\n' "$row" "$id" >>"$local_path"
    printf 'harvested: %s tree=%s box=%s\n' "$key" "${tree:-unstated}" "$id"
    # THE REPORT'S OWN LINE, PRINTED RATHER THAN COMPOSED BY HAND.
    # `rung-execution` § 6 fixes the spelling a builder's report owes, and
    # the box id joins it wherever the loop ran on one; a builder pastes
    # this line rather than assembling it from three places.
    printf 'banked: tree %s key %s box=%s\n' "${tree:-unstated}" "$key" "$id"
}

# harvest_drive_rows <id> <checkout> <tree> — the box's `drive` rows at that
# tree, appended to this checkout's gate ledger, once each. Narrates and never
# refuses: a drive row is a CACHE and the loop row beside it is the
# measurement, so a carrier that could not read is a re-drive next time and
# never a harvest that failed.
harvest_drive_rows() {
    local id="$1" checkout="$2" tree="$3" scratch path line n=0 already=0
    if [ -z "$tree" ]; then
        say "drive rows: none brought home — the loop row names no tree to filter on"
        return 0
    fi
    path="$(cd "$ROOT" && gate_ledger_path 2>/dev/null)" || path=""
    if [ -z "$path" ]; then
        say "drive rows: none brought home — this checkout's gate ledger could not be resolved" >&2
        return 0
    fi
    scratch="${VERIFIER_HOME}/.ledger-in-$$"
    rm -f "$scratch"
    mkdir -p "$VERIFIER_HOME"
    ssh_to "$id" "cat ${checkout}/.git/djb-gate-verdicts" >"$scratch" 2>/dev/null || {
        rm -f "$scratch"
        say "drive rows: none brought home — ${id} has no gate ledger to read"
        return 0
    }
    # AN EOF READER OVER THE WHOLE FILE, never an early-exit pipe: the shape
    # `scripts/tests/test_pipefail_readers.sh` counts across this population.
    while IFS= read -r line; do
        case "$line" in
        *" drive "*" tree=${tree} "* | *" drive "*" tree=${tree}") ;;
        *) continue ;;
        esac
        if grep -qxF -- "$line" "$path" 2>/dev/null; then
            already=$((already + 1))
            continue
        fi
        printf '%s\n' "$line" >>"$path"
        n=$((n + 1))
    done <"$scratch"
    rm -f "$scratch"
    say "drive rows: ${n} brought home at tree=${tree} (${already} already here) from ${id}"
}

# harvest-drives <id> <tree> — the drive rows alone, with no loop row to hang
# them on.
#
# WHY IT IS NOT `harvest`. `harvest <id> <name>` exists to bring a BOX'S LOOP
# VERDICT home and carries the drive rows beside it; a bank's shard runs
# `--leg`, which banks no loop row by design ("one unit of the gate vouches for
# no tree"), so `harvest` refuses it — correctly — and the drive rows that
# shard just paid for die with the box. A bank of five boxes re-drove every
# drive it had already driven the wave before, and the selftest unit's wall is
# where that shows up.
#
# IT IS A SUBCOMMAND AND NOT A SECOND READER. `harvest_drive_rows` is the one
# function that knows the box's ledger path, the tree filter and the
# already-here rule; a caller that fetched the file and appended it itself
# would be a second opinion about all three. So the caller reaches that
# function through this door and nothing else.
#
# AND IT NEVER REFUSES, for `harvest_drive_rows`'s own reason: a drive row is a
# CACHE, the measurement is the leg beside it, and a carrier that could not
# read costs a re-drive rather than a verdict.
cmd_harvest_drives() {
    local id="${1:-}" tree="${2:-}"
    { [ -n "$id" ] && [ -n "$tree" ]; } ||
        die "harvest-drives takes: harvest-drives <id> <tree> — the tree the rows are keyed at."
    [ -r "$ROOT/scripts/gate_ledger.sh" ] ||
        die "no ${ROOT}/scripts/gate_ledger.sh — nothing here knows where this checkout's
   ledger lives, and this wrapper will not invent a second answer."
    # shellcheck source=scripts/gate_ledger.sh
    . "$ROOT/scripts/gate_ledger.sh"
    refuse_if_reclaimed "$id"
    harvest_drive_rows "$id" "$(verifier_checkout_path)" "$tree"
}

cmd_fetch() {
    local id="${1:-}" remote="${2:-}" local_path="${3:-}"
    { [ -n "$id" ] && [ -n "$remote" ] && [ -n "$local_path" ]; } ||
        die "fetch takes: fetch <id> <remote path> <local path>"
    refuse_if_reclaimed "$id"
    local key
    key="$(box_key "$id")"
    [ -r "$key" ] || die "no private key for ${id}"
    scp -i "$key" \
        -o "ProxyCommand=$(proxy_command)" \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        -o LogLevel=ERROR \
        "$(verifier_box_user)@${id}:${remote}" "$local_path"
    say "fetched ${id}:${remote} -> ${local_path}"
}

# =============================================================================
# down
# =============================================================================
cmd_down() {
    local target="${1:-}"
    [ -n "$target" ] || die "down takes an instance id or --all-mine"
    require_profile
    if [ "$target" = "--all-mine" ]; then
        local ids id owner left=""
        ids="$(aws_q ec2 describe-instances \
            --filters "Name=tag:djb:namespace,Values=${NAMESPACE}" \
            "Name=instance-state-name,Values=pending,running" \
            --query 'Reservations[].Instances[].InstanceId' --output text 2>/dev/null || true)"
        [ -n "$ids" ] || {
            say "no running boxes in namespace ${NAMESPACE}"
            return 0
        }
        for id in $(printf '%s' "$ids" | tr '\t' ' '); do
            owner="$(tag_of "$id" "djb:owner")"
            if [ "$owner" = "$OWNER" ]; then
                terminate_one "$id"
            else
                left="${left}
   left ${id} — owner ${owner}, not ${OWNER}"
            fi
        done
        [ -z "$left" ] || say "boxes this session does not own were left alone:${left}"
        return 0
    fi
    terminate_one "$target"
}

# THE SCRIPT IS THE FIRST WALL AND THE POLICY IS THE SECOND. The ops policy
# refuses a terminate on anything not tagged as ours; this refuses it one step
# earlier, where the message can say why.
#
# AND IT ASKS ONCE, FOR ALL FOUR FIELDS. Two `tag_of` calls answered `None` for
# an instance that had VANISHED and `None` for a call the API refused, and the
# refusal printed for both was `is not a verifier box (djb:role=none)` — which
# is a sentence about somebody else's machine, said about our own box, at the
# exact moment a Spot reclaim had taken it. A bank then read that as a foreign
# box and left the rest of its fleet alone. So the state and the tags come out
# of ONE describe, and the three outcomes are three different sentences:
#
#   * the call FAILED  -> exit 2, `could not look at <id>: <the API's line>`,
#     and NOTHING is terminated. A credential that expired mid-teardown must
#     not read as a box that was never ours.
#   * the box is gone  -> `already gone <id> (<StateReason.Code>)`, exit 0.
#     A `down` on a reclaimed box is the bank's ordinary path, not a refusal:
#     the box is already not billing and the only thing left to do is drop the
#     key, which is what the caller wanted.
#   * the tags say it is somebody else's -> today's refusal, unchanged.
terminate_one() {
    local id="$1" role ns state reason trc=0 look rc=0
    set +e
    look="$(aws_q ec2 describe-instances --instance-ids "$id" \
        --query 'Reservations[0].Instances[0].[State.Name,StateReason.Code,Tags[?Key==`djb:role`].Value|[0],Tags[?Key==`djb:namespace`].Value|[0]]' \
        --output text 2>&1)"
    rc=$?
    set -e
    if [ "$rc" != "0" ]; then
        # A VANISHED INSTANCE IS NOT A BLIND CALL. EC2 answers
        # `InvalidInstanceID.NotFound` for an id it has finished forgetting,
        # which is where a reclaimed box ends up about an hour later — that is
        # `already gone` and not `could not look`, and reading them as one was
        # the other half of the `djb:role=none` sentence.
        # AND `Malformed` IS NOT `NotFound`. An id EC2 cannot even parse is a
        # CALLER's mistake, not a box that went away, and answering it `already
        # gone` at exit 0 would make a typo look like a successful teardown.
        case "$look" in
        *InvalidInstanceID.NotFound*)
            rm -rf "$(box_dir "$id")"
            echo "already gone ${id} (not-found — EC2 no longer holds this instance)"
            return 0
            ;;
        esac
        echo "!! verifier_box: could not look at ${id}: $(api_line "$look")" >&2
        echo "   NOTHING was terminated, and this is not a claim that the box is not ours —" >&2
        echo "   it is the API refusing the question. Fix the credential or the throttle and" >&2
        echo "   run it again; 'census' reads the same fleet." >&2
        exit 2
    fi
    look="${look%%$'\n'*}"
    IFS=$'\t' read -r state reason role ns <<<"$look"
    # `--output text` spells an absent field `None`, and a tag that says `None`
    # is a tag that is not there. Normalised once, here, so the three branches
    # below compare against emptiness and not against a word.
    case "$state" in None | null) state="" ;; esac
    case "$reason" in None | null) reason="" ;; esac
    case "$role" in None | null) role="" ;; esac
    case "$ns" in None | null) ns="" ;; esac
    case "$state" in
    terminated | shutting-down)
        rm -rf "$(box_dir "$id")"
        echo "already gone ${id} (${reason:-no reason given})"
        return 0
        ;;
    esac
    case "$role" in
    verifier | verifier-bake) ;;
    *) die "${id} is not a verifier box (djb:role=${role:-none}); nothing terminated." ;;
    esac
    [ "$ns" = "$NAMESPACE" ] ||
        die "${id} belongs to namespace '${ns:-none}', not '${NAMESPACE}'; nothing terminated.
   One product's census never terminates another's boxes."
    # THE CALL'S STATUS IS READ RATHER THAN LEFT TO `set -e`, and that is not
    # defensive style: this function's most important caller runs with `set -e`
    # OFF. `bake_teardown` disables it deliberately — a handler that dies half
    # way through is a handler that reports nothing — and under the old form a
    # `terminate-instances` that FAILED there fell straight through the three
    # lines below it: the box directory was deleted, `terminated <id>` was
    # printed, and the wrapper exited with the original failure's status over a
    # machine that was still running and no longer reachable from this laptop.
    # The drive plants `RequestLimitExceeded` and an expired token at exactly
    # this call.
    aws_q ec2 terminate-instances --instance-ids "$id" >/dev/null || trc=$?
    [ "$trc" = "0" ] || return "$trc"
    # ONLY AFTER THE CALL SUCCEEDED. The private half is the only way back into
    # a box that is still up, so a failed terminate must not take it with it.
    rm -rf "$(box_dir "$id")"
    echo "terminated ${id}"
}

# ONE SENTENCE FOR EVERY WAY A BAKE'S OWN TERMINATE CAN FAIL, because there are
# two of them — the trap, and the two body refusals that take the box down
# themselves and then clear `BAKE_BOX` so the trap does not do it twice — and a
# box orphaned by one reads exactly like a box orphaned by the other.
#
# WHAT THE SENTENCE OWES: the id, the command that takes the box down, and the
# command that reads the FLEET back. The second is not decoration: a terminate
# that failed may also have half worked, and the operator's next question is
# never this one box on its own. The API's own words are NOT filtered out
# either — a throttle is fixed by trying again and an expired token is not, and
# only EC2's answer tells them apart.
#
# A SUBSHELL, because `terminate_one` refuses by `die`: a `die` inside the trap
# would replace the status the caller is owed with a 2, and the refusal would
# then be reported as the bake's own failure.
terminate_or_by_hand() {
    local id="$1" trc=0
    (terminate_one "$id") || trc=$?
    [ "$trc" != "0" ] || return 0
    echo "!! verifier_box: could not terminate ${id} (aws exit ${trc}) — IT IS STILL UP AND IT IS
   STILL BILLING, and nothing else is going to notice except its expiry tag.
   TAKE IT DOWN BY HAND:
     scripts/verifier_box.sh down ${id}
   then read the fleet back, because a call that failed may also have half
   worked and this box is not necessarily the only one on the clock:
     scripts/verifier_box.sh census" >&2
    return "$trc"
}

# =============================================================================
# census — the line the PM reads at the start of every session
# =============================================================================
cmd_census() {
    require_profile
    local raw rc=0
    set +e
    raw="$(aws_q ec2 describe-instances \
        --filters "Name=tag:djb:namespace,Values=${NAMESPACE}" \
        "Name=instance-state-name,Values=pending,running" \
        --query 'Reservations[].Instances[].[InstanceId,InstanceType,Tags[?Key==`djb:role`].Value|[0],Tags[?Key==`djb:owner`].Value|[0],Tags[?Key==`djb:expires`].Value|[0],LaunchTime,ImageId,InstanceLifecycle,Placement.AvailabilityZone]' \
        --output text 2>&1)"
    rc=$?
    set -e
    if [ "$rc" != "0" ]; then
        echo "!! verifier_box: could not look — $(api_line "$raw")" >&2
        print_owner_commands
        exit 2
    fi
    if [ -z "$(printf '%s' "$raw" | tr -d '[:space:]')" ]; then
        echo "no verifier boxes (${REGION}, profile ${PROFILE}, namespace ${NAMESPACE})"
        census_pool_section
        return 0
    fi
    # THE IMAGE EACH BOX IS RUNNING, PRINTED, because the base image is the
    # variable nobody could name after the fact. Two field tests a day apart
    # behaved so differently that the tunnel went from ~330 KB/s to ~7 KB/s,
    # and the one thing known to have changed was the AMI underneath — which
    # nothing recorded and nothing printed, so it took a `describe-instances`
    # after the fact to find out. On a verifier box this is the baked image; on
    # a bake box it is the Amazon Linux base.
    # AND THE MARKET EACH ONE IS ON, for the same reason as the image: it is
    # the variable nobody can name after the box is gone, and it is the
    # difference between a bank that cost cents and one that cost dollars.
    # Read from `InstanceLifecycle` — EC2's own word — never inferred from a
    # tag this wrapper wrote at launch.
    # AND THE ZONE EACH ONE IS IN, for the third time the same argument is
    # made on this line: it is a variable nobody can name after the box is
    # gone, and it is now one a bank CHOOSES — `pm_push.sh` spreads its shards
    # across the zones and the census is the only thing that can say whether
    # they actually landed apart. A row written by an older wrapper has no
    # ninth column and reads `az unknown`, never a shifted line.
    local findings=0 id type role owner expires launched ami lifecycle az market now age exp_epoch
    now="$(now_epoch)"
    while IFS=$'\t' read -r id type role owner expires launched ami lifecycle az; do
        [ -n "$id" ] || continue
        market="$(market_of_lifecycle "$lifecycle")"
        age="$(age_minutes "$launched" "$now")"
        exp_epoch="$(epoch_of_iso "$expires")"
        local note=""
        if [ -n "$exp_epoch" ] && [ "$now" -ge "$exp_epoch" ]; then
            note="   OVERDUE $(hm $((now - exp_epoch))) — the reaper did not fire; down it"
            findings=$((findings + 1))
        elif [ "$role" = "verifier-bake" ] && [ "$age" -ge "$BAKE_STALE_MINUTES" ]; then
            note="   STALE BAKE ${age}m — a bake box that outlived its bake is a bill"
            findings=$((findings + 1))
        fi
        case "$az" in "" | None | null) az="unknown" ;; esac
        echo "${id}   ${type}   ${role}   market ${market}   az ${az}   ami ${ami:-unknown}   owner ${owner}   expires ${expires}   age $(hm $((age * 60))) ${note}"
    done <<<"$raw"
    # THE POOL SECTION COMES AFTER THE BOX LINES AND BEFORE THE VERDICT, and it
    # prints on the finding path too: a census that went quiet about the pool
    # the moment one box was overdue would hide the cost at exactly the moment
    # somebody was reading the output for cost.
    census_pool_section
    [ "$findings" = "0" ] || finding "${findings} box(es) above need a hand. 'down <id>' takes one."
}

# =============================================================================
# zones — the list a bank spreads its shards across
# =============================================================================
#
# A READ AND NOTHING ELSE. It launches nothing, tags nothing and terminates
# nothing; its whole job is to be the ONE answer to "which zones can this
# account launch a verifier box in", so the bank that spreads shards and the
# `up --az` that honours one are reading the same list. A bank that computed
# its own would drift from the wrapper's the day a subnet is added.
#
# AND IT FAILS LOUD WHEN IT CANNOT LOOK. An empty answer and a refused call are
# the same silence at a terminal and opposite facts to a bank: no zones means
# "do not plan a spread", a refused call means "the plan you just made is
# guesswork". Both are exit 2 here, each with its own sentence, because a bank
# that read zero zones as "one zone, then" would put every shard in the same
# place and call it a decision.
cmd_zones() {
    require_profile
    local vpc rows
    vpc="$(vpc_of_group)"
    [ -n "$vpc" ] || {
        echo "!! verifier_box: could not look — no VPC for security group '${GROUP_NAME}' in ${REGION}." >&2
        print_owner_commands
        exit 2
    }
    rows="$(zones_of_vpc "$vpc")"
    [ -n "$(printf '%s' "$rows" | tr -d '[:space:]')" ] || {
        echo "!! verifier_box: could not look — ${vpc} has no subnets this credential can see in ${REGION}," >&2
        echo "   so there is no zone to launch into and no spread to plan. Nothing was asked for." >&2
        print_owner_commands
        exit 2
    }
    printf '%s\n' "$rows"
}

# THE POOL, AND WHAT IT COSTS AN HOUR. A REPORT, NEVER A VERDICT — the census's
# exit stays 1 only for OVERDUE and STALE BAKE, because a warm pool is a thing
# somebody asked for and a box sitting in it is doing its job.
#
# THE PRICE IS THE TAG, AND AN ABSENT TAG PRINTS AS `$?/h`. A census that
# quietly asked the Spot market for today's number would print a cost that is
# not what these boxes are costing — the whole reason the price is written onto
# the box at launch. `never computed` is the property; `$?` is what it looks
# like.
census_pool_section() {
    local rows id launched ami type price now age n=0 unknown=0
    local -a prices=()
    rows="$(warm_pool_rows)"
    # THE CEILING RIDES ON THE POOL LINE, because the two numbers are one
    # question: "can I have a box right now" is `ceiling - running`, and a
    # census that printed the running boxes and the warm ones but not the wall
    # they are measured against left the reader to guess the wall — and the
    # guess was 2, because that is the default nobody could see.
    if [ -z "$(printf '%s' "$rows" | tr -d '[:space:]')" ]; then
        echo "ceiling ${MAX_BOXES} (${MAX_BOXES_SOURCE}) · pool: empty"
        return 0
    fi
    now="$(now_epoch)"
    while IFS=$'\t' read -r id launched ami type price; do
        [ -n "$id" ] || continue
        age="$(age_minutes "$launched" "$now")"
        case "$price" in
        [0-9]*) ;;
        *)
            price="?"
            unknown=$((unknown + 1))
            ;;
        esac
        echo "${id} warm ${age}m \$${price}/h"
        prices+=("$price")
        n=$((n + 1))
    done <<<"$rows"
    printf 'ceiling %d (%s) · pool: %d warm · $%s/h%s\n' \
        "$MAX_BOXES" "$MAX_BOXES_SOURCE" "$n" \
        "$(pool_price_sum ${prices[@]+"${prices[@]}"})" \
        "$([ "$unknown" = "0" ] || printf ' (%d price(s) unknown)' "$unknown")"
}

# HOW OLD A BOX IS, FROM WHATEVER SHAPE EC2 GAVE THE LAUNCH TIME. The API
# answers `2026-09-18T12:00:00.000Z` and, through some paths,
# `2026-09-18T12:00:00+00:00`; `epoch_of_iso` above reads exactly one shape, so
# the normalisation is here and it is two substitutions rather than a second
# parser. An instant it cannot read is age 0 — a box is never reaped for a
# timestamp nobody could parse.
age_minutes() {
    local launched="$1" now="$2" e t
    t="${launched%+00:00}Z"
    [ "$t" != "${launched}Z" ] || t="$launched"
    case "$t" in *.*Z) t="${t%%.*}Z" ;; esac
    e="$(epoch_of_iso "$t")"
    case "$e" in '' | *[!0-9]*) echo 0 ;; *) echo $(((now - e) / 60)) ;; esac
}

hm() { printf '%dh%02dm\n' $(($1 / 3600)) $((($1 % 3600) / 60)); }

# =============================================================================
# bake — the image side's `up`
# =============================================================================

# A BOX THAT IS UP IS A BOX THAT IS BILLING, so every way out of `bake` after
# the launch takes the box with it. FIELD TEST 3 found the way out nobody had
# written: the push was refused by a pre-push hook on the operator's own
# machine, the wrapper exited, and an on-demand box ran on until a human
# noticed it. Nothing on a bake box explains a refusal that happened before a
# byte left the laptop, and nothing on it can fix one.
#
# IT IS A TRAP AND NOT FIVE CALL SITES, because five call sites are the five
# failures somebody thought of; the trap covers the sixth. INT and TERM route
# through it by exiting. What NO shell can cover is a SIGKILL, and that is what
# the box's own `djb:expires` tag, its self-enforced TTL and the census's STALE
# BAKE line are underneath this for.
#
# AND IT SPEAKS THROUGH ITS OWN DESCRIPTORS, fds 8 and 9, which `cmd_bake`
# duplicates from the real stdout and stderr before it arms anything. A trap
# runs inside whatever redirection was in force where it fired, and the
# readiness probe is `ssh_to … >/dev/null 2>&1` — so a wrapper killed during
# the wait terminated its box and said not one word about it. That was this
# drive's finding against this function, and a silent teardown reads, to the
# operator, exactly like no teardown at all.
# --keep, AND IT IS ONE PATH AND NOT A MOOD. `bake --keep` says: if the RECIPE
# fails, or the CAPTURE fails, leave the box up — because in both of those the
# box itself is good and the operator can act on it. A recipe that died at step
# 8 is a machine with seven steps already done on it, and the thing the
# operator wants is a shell on it while the failure is still there: walk the
# remaining steps by hand in one sitting, find the one that is wrong, then bake
# again from a recipe that has been corrected once rather than five times at
# twenty minutes each. FIELD TEST 5 is the argument — the recipe's first line
# failed, the box went down (correctly, with no flag), and the next thing
# anybody learned about the box took a whole second bake.
#
# EVERY OTHER WAY OUT STILL TEARS DOWN, flag or no flag, because in every one
# of them the box is worth nothing to anybody: a bootstrap marker that never
# arrived (there is no git and no repository on it), a push refused before a
# byte left this laptop (the box has no tree), a killed wrapper (the operator
# is not there to use what is kept), an image that was captured (the work is
# in the AMI). A flag that kept those is a flag that leaks money for nothing.
#
# AND WHAT IS KEPT HAS NO BACKSTOP BUT THE CENSUS, which is said out loud
# wherever it is used. A bake box runs NO REAPER: the recipe installs the unit
# DISABLED and only the launch seam enables it, so `djb:expires` on a bake box
# is a LABEL the census reads and not a timer the machine enforces. Kept means
# kept until a human takes it down.
BAKE_KEEP=""

# Set when the capture had to fall back to an untagged image. It changes the
# bake's EXIT STATUS to 1 — this wrapper's "a finding": the image exists and
# the thing that finds images cannot see it, which is precisely something the
# operator needs to know and is neither a failure nor a pass.
CAPTURE_UNTAGGED=""

# The sentence an untagged image is handed over with: what to do NOW (the id,
# and the flag that launches from it) and what to fix so the next bake does not
# need this. The policy step is the owner's hand twice over — the document is
# in the tree, and an IAM policy that already exists keeps the version it was
# created with, so a bootstrap re-run alone is not enough.
print_untagged_capture() {
    local image="$1"
    echo "!! verifier_box: ${image} was captured WITHOUT ITS TAGS." >&2
    echo "   The image is good. What is missing is the labelling, and two things read it:" >&2
    echo "   'up' finds the newest image by djb:role + djb:namespace, and '--prune' decides" >&2
    echo "   what is ours. Until the tags are there, THIS IMAGE IS INVISIBLE to both." >&2
    echo "" >&2
    echo "   NOW — launch from it by hand:" >&2
    echo "     scripts/verifier_box.sh up --for <rung> --image-id ${image}" >&2
    echo "" >&2
    echo "   THE FIX, and it is the owner's: the ops policy must grant ec2:CreateTags on the" >&2
    echo "   ACCOUNT-LESS image and snapshot ARNs — arn:aws:ec2:<region>::image/* and" >&2
    echo "   ::snapshot/* — beside the account-scoped one. deploy/iam/verifier-ops-policy.json" >&2
    echo "   carries them; the ACCOUNT may not. An existing policy keeps the document it was" >&2
    echo "   created with, so re-running the bootstrap REPORTS it and does not update it:" >&2
    echo "" >&2
    echo "     DJB_DEPLOY_NAMESPACE=${NAMESPACE} DJB_VERIFIER_ACCOUNT=<12-digit account> DJB_VERIFIER_REGION=${REGION} \\" >&2
    echo "       ./deploy/iam/verifier_bootstrap.sh --confirm" >&2
    echo "" >&2
    echo "   and then the command IT prints — an 'iam create-policy-version --set-as-default'" >&2
    echo "   over the document it renders. Both are the owner's to run." >&2
}

# The sentence a kept box is handed over with. Everything in it is derived —
# the key path, the transport, the account, the checkout — so a copied command
# cannot drift from the one `ssh_to` opens.
bake_keep_hands_over() {
    local id="$1" why="$2"
    echo "!! verifier_box: ${why}" >&2
    echo "   --keep: ${id} IS STILL UP, deliberately, and it is still billing. Nothing on this
   box is watched by anything: a bake box runs no reaper (the recipe installs the
   unit disabled and only the launch seam enables it), so its djb:expires tag is a
   label the census reads and NOT a timer the machine enforces. It goes down when
   you take it down.
   A SHELL ON IT — the same transport ssh_to opens, printed so it can be copied:
     ssh -i $(box_key "$id") -o \"ProxyCommand=$(proxy_command)\" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR $(verifier_box_user)@${id}
   then, on the box:
     cd $(verifier_checkout_path) && ./deploy/verifier/bake.sh --plan
   which prints the whole recipe in order so you can walk the steps that are left.
   One command at a time from here instead:
     scripts/verifier_box.sh run ${id} -- '<command>'
   WHEN YOU ARE DONE:
     scripts/verifier_box.sh down ${id}
     scripts/verifier_box.sh census" >&2
}

BAKE_BOX=""
bake_teardown() {
    local rc=$?
    set +e
    trap - EXIT
    {
        phase_summary
        if [ -n "$BAKE_BOX" ]; then
            echo "!! verifier_box: the bake stopped (exit ${rc}) with ${BAKE_BOX} still up; taking it" >&2
            echo "   down so it cannot become a stale bill — nothing on a bake box outlives its bake." >&2
            if ! terminate_or_by_hand "$BAKE_BOX"; then
                # THE STATUS STAYS THE ORIGINAL FAILURE'S. The terminate is the
                # cleanup and not the verdict: what the operator has to fix is
                # still the push that was refused or the capture that produced
                # nothing, and a teardown that rewrote that into its own status
                # would send them after the wrong thing. The one substitution is
                # the belt underneath it — a teardown firing on a CLEAN exit
                # with a box still up must not report success over an orphan,
                # and 2 is this wrapper's `could not clear`.
                [ "$rc" != "0" ] || rc=2
            fi
            BAKE_BOX=""
        fi
    } >&8 2>&9
    exit "$rc"
}

cmd_bake() {
    if [ "${1:-}" = "--prune" ]; then
        bake_prune
        return 0
    fi
    # `--keep` is read here and nowhere else, so every path below decides for
    # itself whether it is one of the two the flag covers. An unknown flag is
    # still exit 2: a mistyped `--kepe` must never be a silently ordinary bake.
    if [ "${1:-}" = "--keep" ]; then
        BAKE_KEEP=1
        shift
    fi
    [ "$#" = "0" ] || die "unknown argument '$1' to bake"
    # BEFORE A BOX IS LAUNCHED, because everything the capture will be called
    # is composed from this and a git sha, and a name EC2 refuses is a bake
    # that spends twenty minutes to fail at its last call.
    ascii_only "deployment namespace" "$NAMESPACE"
    # AND A LOCAL `main`, WHICH NOT EVERY CHECKOUT HAS. This guard was written
    # when the recipe phase composed the image's NAME from `refs/heads/main`: a
    # checkout made by `git clone --branch <tag>` has no such ref, the read sat
    # after the launch, the bootstrap and the push, and it died there on git's
    # own `fatal: ambiguous argument 'main'` — twenty minutes and a bill, spent
    # to fail at a NAME.
    #
    # THE NAME NO LONGER NEEDS IT — it is composed from HEAD, the tree the push
    # actually sends — AND THE GUARD STAYS, because the ref is still a
    # precondition of a bake that means anything. Everything downstream of this
    # image is `--loop` on the box, and `--loop`'s scope derivation refuses
    # outright in a checkout with no local `main` (`loop_tier_own_apps`: a thin
    # basis is not a small answer, it is the wrong one). A bake from such a
    # checkout is twenty minutes and a bill spent on an image whose whole
    # purpose is a gate that will not run — a later failure than the one this
    # guard was written for, and a more expensive one. The refusal moves here
    # for the same reason it always sat here: there, it costs a launch first.
    if ! git -C "$ROOT" rev-parse --verify --quiet refs/heads/main >/dev/null 2>&1; then
        die "this checkout has NO local refs/heads/main. The image itself is named after
   HEAD — the tree the push sends — but the ref is what the gate on the box
   derives its --loop scope from, and that derivation REFUSES without it: a
   box baked here is twenty minutes and a bill spent on an image whose gate
   cannot run.
   Nothing was launched and nothing was captured: the refusal is here rather
   than there because there it costs a launch, a bootstrap and a push first.
   The two legal moves:
     1. create the ref at this clone's fork point:
          git branch main HEAD
        (./scripts/setup.sh does exactly this as its first step)
     2. bake from a checkout of the family that HAS one — the primary, or any
        linked worktree of it, whose refs live in the common git dir."
    fi
    require_profile
    require_plugin

    # THE BASE IMAGE, RESOLVED ONCE AND SAID OUT LOUD. `$AL2023_PARAM` is a
    # public parameter that means "the latest", so it answers differently on
    # different days: two field tests a day apart ran two different AMIs and
    # got two very different machines, and neither run recorded which. A knob
    # pins it; absent the knob the parameter is read ONCE, and either way the
    # id and the image's own dated NAME are printed here and recorded on the
    # image this bake captures — so "which base did the good image come from"
    # is a tag rather than an archaeology.
    local base base_name base_state base_row
    if [ -n "$AL2023_PINNED" ]; then
        base="$AL2023_PINNED"
        say "base       ${base} (pinned by DJB_VERIFIER_AL2023_AMI; the SSM parameter was not read)"
    else
        base="$(aws_q ssm get-parameters --names "$AL2023_PARAM" \
            --query 'Parameters[0].Value' --output text)"
        case "$base" in "" | None) die "could not resolve the Amazon Linux image from ${AL2023_PARAM}" ;; esac
    fi
    base_row="$(image_name_and_state "$base")"
    base_name="${base_row%%	*}"
    base_state="${base_row##*	}"
    case "$base_name" in "" | None | null) base_name="<name unreadable>" ;; esac
    say "base       ${base}  ${base_name}  (state ${base_state:-unknown})"
    say "           pin this bake's base with DJB_VERIFIER_AL2023_AMI=${base} to repeat it exactly"

    local group
    group="$(aws_q ec2 describe-security-groups \
        --filters "Name=group-name,Values=${GROUP_NAME}" \
        --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || true)"
    case "$group" in
    "" | None | null)
        echo "!! verifier_box: no security group '${GROUP_NAME}' in ${REGION}." >&2
        print_owner_commands
        exit 2
        ;;
    esac

    local pending keyfile pubkey expires id
    pending="${VERIFIER_HOME}/.pending-bake-$$"
    rm -rf "$pending"
    mkdir -p "$pending"
    chmod 0700 "$pending"
    keyfile="${pending}/id_ed25519"
    ssh-keygen -q -t ed25519 -N "" -C "verifier-bake@${OWNER}" -f "$keyfile" </dev/null
    chmod 0600 "$keyfile"
    pubkey="$(cat "${keyfile}.pub")"
    expires="$(iso_at "$(($(now_epoch) + 2 * 3600))")"

    # TWO SLOTS, AND THE SECOND IS THE RECIPE'S OWN KNOB. The seam creates the
    # repository the push below lands in, and it must land at exactly the path
    # `bake.sh` checks — so the path is rendered from `verifier_checkout_path`
    # rather than typed into the YAML, the same derivation `cmd_push` uses for
    # its target.
    local user_data
    user_data="$(sed -e "s|\${VERIFIER_PUBKEY}|${pubkey}|g" \
        -e "s|\${VERIFIER_CHECKOUT}|$(verifier_checkout_path)|g" \
        "$ROOT/deploy/verifier/bake-user-data.yaml")"

    # ON-DEMAND, ALWAYS, AND IT IS SAID OUT LOUD: a bake interrupted is an image
    # half-written, and twenty minutes of provisioning is worth more than the
    # few cents Spot would save.
    say "baking on-demand (a bake interrupted is an image half-written)"
    # THE FIRST FIELD, because `run_instances_common`'s projection is now
    # `[InstanceId,SpotInstanceRequestId]` for every caller. A bake is always
    # on-demand, so the second field is always `None` and the slice is the id.
    id="$(run_instances_common "$base" "$BAKE_TYPE" "$group" "$user_data" \
        "verifier-bake" "$expires" "${NAMESPACE}-verifier-bake-${OWNER}" "")"
    id="${id%%$'\n'*}"
    id="${id%%	*}"
    { [ -n "$id" ] && [ "$id" != "None" ]; } || {
        rm -rf "$pending"
        die "run-instances returned no instance id for the bake box"
    }
    mkdir -p "$(box_dir "$id")"
    chmod 0700 "$(box_dir "$id")"
    mv "$keyfile" "$(box_key "$id")"
    mv "${keyfile}.pub" "$(box_key "$id").pub"
    chmod 0600 "$(box_key "$id")"
    printf '%s\n' "bake" >"$(box_dir "$id")/rung"
    rm -rf "$pending"

    # FROM HERE THERE IS A MACHINE ON THE CLOCK, so from here every exit takes
    # it down. The five phases below are the five the summary names, and the
    # first of them opens at the launch, which is where the bill opens too.
    BAKE_BOX="$id"
    exec 8>&1 9>&2
    trap 'bake_teardown' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM

    phase_begin online
    wait_for_ssm "$id"
    # AND THEN THE SECOND WAIT, WHICH IS THE ONE THE PUSH ACTUALLY NEEDS.
    phase_begin bootstrap
    say "waiting for the box's own bootstrap (${BAKE_READY_MARKER})"
    if ! wait_for_bake_bootstrap "$id"; then
        # THE SAME SENTENCE THE TRAP USES, because this is the same orphan: a
        # `|| true` over the bare call swallowed a failed terminate whole, and
        # the `BAKE_BOX=""` on the next line then told the trap there was no box
        # left to take down.
        terminate_or_by_hand "$id" || true
        BAKE_BOX=""
        die "${id} never wrote ${BAKE_READY_MARKER} in ${BOOTSTRAP_WAITED}s (ceiling ${BOOTSTRAP_WAIT_SECONDS}s), so its
   cloud-init did not finish: there is no git and no repository to push into.
   The box was terminated so it cannot become a stale bill. Nothing was pushed
   and nothing was captured."
    fi

    phase_begin push
    say "pushing this checkout's HEAD into the box's checkout (depth 1)"
    local prc=0
    cmd_push "$id" >/dev/null || prc=$?
    [ "$prc" = "0" ] || finding "the push to ${id} failed (git exit ${prc}). Whichever of the two
   readings above it is — this machine's pre-push hook refusing before a byte
   left the laptop, or the tunnel dying while that hook measured — it happened
   on THIS side: there is nothing on the box that explains it and nothing there
   that can fix it. The box is going down; fix it here and bake again."

    phase_begin recipe
    local out image_sha
    # THE SHA THE IMAGE IS NAMED FOR IS THE SHA THE IMAGE HOLDS, and that is
    # HEAD's. What the push sends is `HEAD:refs/heads/main` — this checkout's
    # HEAD, landing on the box's `main` — so the tree baked into the image is
    # HEAD's tree whatever branch this checkout is on. Composing the name, the
    # description and the `djb:main` tag from the LOCAL `main` agreed with that
    # only in a checkout sitting on main; from a rung's worktree the image
    # carried one tree and was labelled with another, and `djb:main` is what a
    # census, a prune and an operator asking "which build is this" all read.
    #
    # THE PRE-LAUNCH GUARD ON `refs/heads/main` STAYS, and it is no longer
    # about this line: see its own block, which says what it is for now.
    #
    # UNGUARDED ON PURPOSE. `rev-parse HEAD` cannot fail in a checkout this
    # wrapper already pushed from; a failure here is a repository that moved
    # under a running bake.
    image_sha="$(git -C "$ROOT" rev-parse HEAD)"
    set +e
    out="$(ssh_to "$id" "cd $(verifier_checkout_path) && ./deploy/verifier/bake.sh" 2>&1)"
    local rc=$?
    set -e
    printf '%s\n' "$out"
    if [ "$rc" != "0" ] || ! printf '%s' "$out" | grep -F -- "ready for create-image" >/dev/null; then
        if [ -n "$BAKE_KEEP" ]; then
            # THE ONE PATH --keep EXISTS FOR. The box is a machine with the
            # finished steps already on it and the failure still in place, which
            # is the only moment walking the rest by hand is cheaper than baking
            # again. Clearing BAKE_BOX is what disarms the trap for this exit
            # and nothing else — every other way out of this function still
            # takes the box with it.
            # THE STATUS IS THE RECIPE'S. A recipe that exited 0 while NOT
            # printing the line the wrapper scrapes has no status of its own to
            # pass on, and that is a finding rather than a refusal: 1.
            local keep_rc="$rc"
            [ "$keep_rc" != "0" ] || keep_rc=1
            BAKE_BOX=""
            bake_keep_hands_over "$id" "the recipe did not finish (exit ${rc})."
            exit "$keep_rc"
        fi
        # THE SAME SENTENCE THE TRAP USES, because this is the same orphan: a
        # `|| true` over the bare call swallowed a failed terminate whole, and
        # the `BAKE_BOX=""` on the next line then told the trap there was no box
        # left to take down.
        terminate_or_by_hand "$id" || true
        BAKE_BOX=""
        die "the recipe did not finish (exit ${rc}); the bake box was terminated so it
   cannot become a stale bill. Nothing was captured."
    fi

    phase_begin image
    say "capturing the image"
    local image_name image_desc baked new_image image_tags snap_tags
    baked="$(iso_at "$(now_epoch)")"
    image_name="${NAMESPACE}-verifier-${image_sha:0:8}-$(printf '%s' "$baked" | tr -d ':-')"
    image_desc="Verifier box image for ${NAMESPACE}, main ${image_sha:0:8}, base ${base} ${base_name}"
    # THE API'S 7-BIT RULE, AT THE CALL. The namespace was checked before the
    # launch; this is the same guard over the strings actually being sent, so
    # anything that ever joins them is covered by construction rather than by
    # somebody remembering. An em-dash in a description refused a real capture.
    ascii_only "image name" "$image_name"
    ascii_only "image description" "$image_desc"
    # THE BASE RIDES ON THE IMAGE. `djb:base-ami` and `djb:base-ami-name` are
    # what turn "that bake worked and the next one did not" into a question
    # with an answer.
    image_tags="Tags=[{Key=djb:role,Value=verifier-image},{Key=djb:namespace,Value=${NAMESPACE}},{Key=djb:main,Value=${image_sha}},{Key=djb:baked,Value=${baked}},{Key=djb:base-ami,Value=${base}},{Key=djb:base-ami-name,Value=${base_name}}]"
    snap_tags="$image_tags"
    local cap_err cap_rc=0
    cap_err="${VERIFIER_HOME}/.capture-$$.err"
    mkdir -p "$VERIFIER_HOME"
    set +e
    new_image="$(aws_q ec2 create-image --instance-id "$id" --name "$image_name" \
        --description "$image_desc" \
        --tag-specifications "ResourceType=image,${image_tags}" \
        "ResourceType=snapshot,${snap_tags}" \
        --query 'ImageId' --output text 2>"$cap_err")"
    cap_rc=$?
    set -e
    # A REFUSED TAG IS NOT A LOST IMAGE. `create-image` takes its tags in the
    # same call that makes the image, so a policy that does not reach the image
    # and snapshot ARNs refuses the WHOLE call — and what is thrown away is a
    # finished machine, not a label. An EC2 image ARN carries NO account id
    # (`arn:aws:ec2:<region>::image/*`), so an account-scoped tagging grant
    # matches every instance and not one image or snapshot; that is exactly
    # what a live policy did, and the capture failed over a bake box that was
    # ready. So: retry WITHOUT the tags, keep the image, and make the missing
    # grant a NAMED FINDING with both the workaround and the fix in it.
    if { [ "$cap_rc" != "0" ] || [ -z "$new_image" ] || [ "$new_image" = "None" ]; } &&
        grep -Fq "CreateTags" "$cap_err" 2>/dev/null; then
        echo "!! verifier_box: the capture's TAGS were refused — 'ec2:CreateTags' is not granted on the" >&2
        echo "   image and/or the snapshot this call creates. EC2's own words:" >&2
        sed 's/^/     /' "$cap_err" >&2
        echo "   Retrying the capture UNTAGGED: the recipe finished and the image is worth more" >&2
        echo "   than its labels." >&2
        set +e
        new_image="$(aws_q ec2 create-image --instance-id "$id" --name "$image_name" \
            --description "$image_desc" \
            --query 'ImageId' --output text 2>"$cap_err")"
        cap_rc=$?
        set -e
        if [ "$cap_rc" = "0" ] && [ -n "$new_image" ] && [ "$new_image" != "None" ]; then
            CAPTURE_UNTAGGED="$new_image"
        fi
    fi
    if [ "$cap_rc" != "0" ] && { [ -z "$new_image" ] || [ "$new_image" = "None" ]; }; then
        sed 's/^/   /' "$cap_err" >&2 || true
    fi
    rm -f "$cap_err"
    # A FULLY BUILT BOX NOBODY CAPTURED IS STILL JUST A BILL. The recipe
    # finished, which makes this the most tempting box in the fleet to leave
    # running "in case" — and the one there is least excuse for, because its
    # twenty minutes of work is exactly what a second bake reproduces. That is
    # the default and it stands; `--keep` is the operator saying, in advance and
    # in writing, that they are going to retry the capture by hand on THIS box
    # rather than spend the twenty minutes again.
    case "$new_image" in
    "" | None)
        if [ -n "$BAKE_KEEP" ]; then
            BAKE_BOX=""
            bake_keep_hands_over "$id" "create-image returned no image id for ${id}."
            exit 2
        fi
        die "create-image returned no image id for ${id}."
        ;;
    esac

    local state waited=0
    while [ "$waited" -lt 1800 ]; do
        state="$(aws_q ec2 describe-images --image-ids "$new_image" \
            --query 'Images[0].State' --output text 2>/dev/null || true)"
        [ "$state" = "available" ] && break
        waited=$((waited + ONLINE_POLL_SECONDS))
        sleep "$ONLINE_POLL_SECONDS"
    done
    if [ "$state" != "available" ]; then
        if [ -n "$BAKE_KEEP" ]; then
            BAKE_BOX=""
            bake_keep_hands_over "$id" "${new_image} did not become available inside ${waited}s."
            exit 2
        fi
        die "${new_image} did not become available inside ${waited}s."
    fi

    phase_end
    phase_summary
    terminate_one "$id"
    BAKE_BOX=""
    # THE IMAGE IS PRIVATE TO THIS ACCOUNT. Nothing here ever passes
    # --launch-permission or calls modify-image-attribute, and the drive asserts
    # the absence: a published image is the "what never lands" clause broken at
    # the account boundary.
    if [ -n "$CAPTURE_UNTAGGED" ]; then
        print_untagged_capture "$new_image"
        # THE ANSWER LINE IS STILL LAST, because a caller scrapes it — and it
        # says what is different about this one rather than reading like the
        # ordinary success two lines down.
        echo "image ${new_image} (main ${image_sha:0:8}) — UNTAGGED: up --image-id ${new_image}"
        exit 1
    fi
    # `main` here is the BOX's main, which is this checkout's HEAD: that is what
    # the push put there and what the image holds.
    echo "image ${new_image} (main ${image_sha:0:8}) — verifier_box.sh up will use it"
}

# THE IMAGES ARE FOUND BY TAG; THEIR SNAPSHOTS ARE NOT, AND MUST NOT BE. What
# makes an image OURS is its tags, so the filter above is right. What an image
# OWNS is in its own BlockDeviceMappings, and reading that is the only way that
# stays true when the tags are missing — which happens: a capture whose
# `ec2:CreateTags` the policy refused produces a working, untagged image, and a
# prune that looked snapshots up by tag would deregister an image and leave its
# storage behind, billing, with nothing pointing at it.
#
# EVERY MAPPING, NOT THE FIRST. `BlockDeviceMappings[0]` reads the root volume
# and silently ignores the rest; an image with a second EBS volume would lose
# half its storage to the same leak. With `--output text` the row is then
# variable-width — id, one field per snapshot, date — which is why it is read
# as an array and sliced at both ends rather than with a fixed `read -r a b c`.
bake_prune() {
    require_profile
    local rows keep=2 n=0
    rows="$(aws_q ec2 describe-images --owners self \
        --filters "Name=tag:djb:role,Values=verifier-image" \
        "Name=tag:djb:namespace,Values=${NAMESPACE}" \
        --query 'reverse(sort_by(Images,&CreationDate))[].[ImageId,BlockDeviceMappings[].Ebs.SnapshotId,CreationDate]' \
        --output text 2>/dev/null || true)"
    [ -n "$(printf '%s' "$rows" | tr -d '[:space:]')" ] || {
        say "no verifier images to prune"
        return 0
    }
    local line image snap
    local -a fields snaps
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        IFS=$'\t' read -r -a fields <<<"$line"
        image="${fields[0]:-}"
        [ -n "$image" ] || continue
        # Everything between the id and the trailing CreationDate is a
        # snapshot; a row with no mappings at all is id + date and yields none.
        snaps=()
        local i
        for ((i = 1; i < ${#fields[@]} - 1; i++)); do
            snap="${fields[$i]}"
            case "$snap" in "" | None | null) continue ;; esac
            snaps+=("$snap")
        done
        n=$((n + 1))
        if [ "$n" -le "$keep" ]; then
            say "keeping ${image}"
            continue
        fi
        aws_q ec2 deregister-image --image-id "$image" >/dev/null
        for snap in ${snaps[@]+"${snaps[@]}"}; do
            aws_q ec2 delete-snapshot --snapshot-id "$snap" >/dev/null
        done
        echo "pruned ${image} (snapshot(s) ${snaps[*]:-none})"
    done <<<"$rows"
}

# =============================================================================
SUB="${1:-}"
shift || true
case "$SUB" in
up) cmd_up "$@" ;;
down) cmd_down "$@" ;;
pool) cmd_pool "$@" ;;
census) cmd_census "$@" ;;
ceiling) cmd_ceiling "$@" ;;
zones) cmd_zones "$@" ;;
run) cmd_run "$@" ;;
loop) cmd_loop "$@" ;;
leg) cmd_leg "$@" ;;
wait) cmd_wait "$@" ;;
fetch) cmd_fetch "$@" ;;
harvest) cmd_harvest "$@" ;;
harvest-drives) cmd_harvest_drives "$@" ;;
push) cmd_push "$@" ;;
bake) cmd_bake "$@" ;;
"" | -h | --help) usage ;;
*) die "unknown subcommand '${SUB}': up down pool census ceiling zones run loop leg wait fetch harvest harvest-drives push bake" ;;
esac
