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
# drives: deploy/ docs/runbooks/deploy.md frontend/package.json scripts/check.sh scripts/tests
# THE VERIFIER IMAGE'S DRIVE — the reaper, the user-data seam, the ops policy,
# the owner's bootstrap and the bake recipe, driven case by case.
#
#   ./scripts/tests/test_verifier_image.sh          run every case
#   ./scripts/tests/test_verifier_image.sh --list   name them and stop
#
# WHY IT EXISTS, AND WHY IT IS SITED HERE RATHER THAN UNDER deploy/tests/.
# `deploy/tests/*.sh` is run by NO moment — the full gate prints that set as a
# declared blind spot and does not invoke it. The subjects below are the money
# guard and the credential guard for a fleet of throwaway EC2 boxes: a reaper
# that stops reaping is a bill with no ceiling, a reaper that reaps during a
# gate is a verdict lost, and a bootstrap that opens an ingress rule or mints a
# key per run is a credential incident. None of those may live behind "it was
# proven once, by hand, on the day it was written", so this drive is registered
# column-zero in `scripts/check.sh`'s `selftest_drives_leg` and runs in the full
# gate with every other drive.
#
# EVERYTHING HERE IS A SHIM. No AWS resource is created, described, tagged or
# terminated by any case below; `aws`, `ssh`, `who`, `pgrep`, `date`, `shutdown`
# and `logger` are all planted on PATH in a per-case scratch directory, and
# every one of them records its argv to a file the case then reads. What that
# buys is the ARGUMENTS and the REFUSALS — the two things a script owns. What it
# cannot buy is anything about the real API or the real machine, and that list
# is the WHAT IT DOES NOT COVER block below rather than a footnote.
#
# THE CASES, in six groups (the count of each is `--list`'s to print, not this
# header's — a number here goes stale without the sentence around it changing):
#
#   the reaper       every decision the timer can reach and every input it can
#                    fail to read: the eight ordinary ones, the boot grace that
#                    keeps an unsynced clock from reaping a box it just made,
#                    the missing activity marker, and the two could-not-look
#                    refusals (no clock, no mtime). Every case asserts the
#                    DECISION LINE by text and the shutdown call by count, in
#                    both directions: a hold that shuts down and a reap that
#                    does not are the same defect from two sides, and a refusal
#                    that shuts the box down anyway is the worst of the three.
#   the seam         the user-data template renders with exactly four
#                    values, leaves no slot behind, and carries the four
#                    properties the launch wrapper depends on — and the BAKE
#                    box's own seam, which is a different file for a different
#                    moment: it installs git and initialises the repository the
#                    operator's FIRST push lands in (FIELD TEST 2 met what a
#                    raw box answers instead), and it writes its ready marker
#                    last, because the SSM agent is Online long before
#                    cloud-init's runcmd is finished.
#   the policy       the least-privilege properties of the ops policy,
#                    read out of the document as text, plus the two the rider
#                    added: every tag-bearing grant is scoped to ONE deployment
#                    namespace, and no deployment's own slug is hard-coded
#                    anywhere in the machinery. IAM's own evaluator is never
#                    asked (that needs the network and an account), which is
#                    declared below and is the field test's step.
#   the bootstrap    namespace-, account- and region-first (all three required
#                    with no default), refuse-first, account-pinned, idempotent,
#                    and the two credential properties (no ingress ever, one key
#                    ever).
#   the recipe       the bake plan is printed before it is an act; the plan is
#                    never mistaken for a finished bake (the launch wrapper
#                    decides success by scraping the last line); the checkout is
#                    parked on the branch the image ships on BEFORE any step
#                    derives a name from it, and the recipe therefore writes no
#                    database pin (the first bank on boxes paid for that order);
#                    the image carries the frontend toolchain — node pinned and
#                    checksummed, pnpm at the version the checkout's own
#                    packageManager field pins — because a box without it
#                    cannot reach a verdict at all;
#                    the bake marker leaves with the bake, so it is never
#                    captured into the image; and the recipe refuses to run
#                    anywhere but a bake box.
#   what must not    the deploy-layer drive population is unchanged, so
#   move             the gate's printed blind-spot count stays what it says.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * WHETHER `who` ON AMAZON LINUX LISTS A SESSION MANAGER SESSION the way the
#     shim here does. The hold-on-a-live-session case is exactly as good as that
#     assumption and no better; only a real box answers it.
#   * WHETHER `shutdown -h now` ON A ONE-TIME SPOT INSTANCE WITH
#     `InstanceInitiatedShutdownBehavior=terminate` TERMINATES RATHER THAN
#     STOPS. The drive proves the reaper CALLS it; the instance's own behaviour
#     is AWS's and is unobservable from here.
#   * WHETHER IAM READS THE POLICY THE WAY THE TEXT ASSERTIONS DO. Every policy
#     case below is a property of the DOCUMENT. A condition key that is
#     mis-spelled but well-shaped passes here and fails in the account; the only
#     real proof is a dry-run call under the credential, which needs both.
#   * WHETHER THE AWS ERROR CODES THE SHIMS ANSWER ARE THE CODES THE REAL API
#     RETURNS. They are copied from the EC2/IAM API references and pinned in the
#     fixtures; a mis-spelled one makes the case that reads it vacuous.
#   * THE IMAGE ITSELF. Nothing here bakes, boots or logs into anything. Whether
#     the recipe's steps succeed on Amazon Linux, whether cloud-init honours the
#     authorized-key slot for a user it creates in the same run, and whether the
#     compose stack comes up on the baked machine are all the field test's.
#   * THE BAKE SEAM AS A RUNNING THING. The cases below are properties of the
#     rendered DOCUMENT: that git is installed, that a repository is
#     initialised at the recipe's own path on `main` with
#     `receive.denyCurrentBranch=updateInstead`, that the ready marker is
#     written last and on a tmpfs. Whether cloud-init's `runcmd` really
#     finishes after the SSM agent reports Online, whether `install -d -o` and
#     `sudo -u` give the bake account a tree it can write, and whether
#     `updateInstead` puts a REAL `push --force main:main` into an unborn
#     working tree are four things only a box answers — FIELD TEST 3's, all
#     four. A fifth joins them with the marker guard's own config assertion:
#     that `sudo -u verifier git -C … config --get` READS on the box (git
#     refuses a repository whose owner is not the caller, and this guard runs
#     from root's `runcmd`) is asserted here as text and nowhere as behaviour.
#   * THE TIMER'S SCHEDULE. The unit and timer files are asserted as text —
#     that they name the script, run as root, and fire on the interval the
#     design says. Whether systemd parses them is systemd's answer, on a box.
set -euo pipefail

cd "$(dirname "$0")/../.."

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_verifier_image: scripts/tests/drive_preamble.sh is not in this tree." >&2
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
    echo "!! test_verifier_image: $*" >&2
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
    echo "!! unknown argument '$1': test_verifier_image.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

# --- the subjects, each named where it is missing ----------------------------
REAPER=deploy/verifier/idle_reaper.sh
SEAM=deploy/verifier/user-data.yaml.in
BAKE_SEAM=deploy/verifier/bake-user-data.yaml
UNIT=deploy/verifier/verifier-reaper.service
TIMER=deploy/verifier/verifier-reaper.timer
BAKE=deploy/verifier/bake.sh
POLICY=deploy/iam/verifier-ops-policy.json
TRUST=deploy/iam/verifier-box-trust.json
BOOTSTRAP=deploy/iam/verifier_bootstrap.sh
# THE CHECKOUT'S OWN INTERPRETER, for every PYTHON FILE THIS REPOSITORY SHIPS
# that this drive runs. `python3` off PATH is some other environment's: on a
# verifier box it is the system 3.9, where `zip(…, strict=True)` — which these
# files use — is `TypeError: zip() takes no keyword arguments`, and the drive
# would report that as a finding about the file it was driving. Inline
# `python3 -c` and heredoc programs below stay as they are: they are stdlib on
# any Python 3, and their own `command -v python3` guard covers their absence.
DRIVE_PY="$PWD/.venv/bin/python"
[ -x "$DRIVE_PY" ] ||
    cannot_look "this checkout has no .venv/bin/python, and the python files this drive
   runs are written at the version that venv holds. Run ./scripts/setup.sh first"
SUMMARY=deploy/policy_summary.py

for _subject in "$REAPER" "$SEAM" "$BAKE_SEAM" "$UNIT" "$TIMER" "$BAKE" "$POLICY" "$TRUST" "$BOOTSTRAP" "$SUMMARY"; do
    [ -f "$_subject" ] || cannot_look "${_subject} missing — there is nothing to drive"
done
unset _subject
command -v python3 >/dev/null 2>&1 || cannot_look "no python3 on PATH — the policy, the seam and the clock fixtures all need one"

ROOT="$PWD"
WORK=$(mktemp -d "${TMPDIR:-/tmp}/djb-test-verifier-image.XXXXXX") || cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'chmod -R u+rwX "$WORK" 2>/dev/null || true; rm -rf "$WORK"'

# epoch -> the ISO-8601 UTC spelling the tags and /etc/verifier/expires use.
iso_at() {
    python3 -c 'import sys,datetime
print(datetime.datetime.fromtimestamp(int(sys.argv[1]),datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))' "$1"
}

# set a file's mtime to an epoch, portably — `touch -d`/`touch -r` spell this
# differently on the box (GNU) and on the machine this drive usually runs on
# (BSD), and the reaper reads the mtime because `touch` is what marks activity.
set_mtime() {
    python3 -c 'import os,sys
os.utime(sys.argv[1], (float(sys.argv[2]), float(sys.argv[2])))' "$1" "$2"
}

# =============================================================================
# GROUP 1 — the reaper
# =============================================================================
#
# Each case builds a whole fake machine under $WORK/<name>: an /etc/verifier,
# a /run/verifier, a /var/log, and a bin/ of shims that is the only PATH the
# reaper sees for the five commands it calls. VERIFIER_ROOT points the reaper
# at it. Nothing outside that directory is read or written.

RW=""
RW_REC=""
rw_new() {
    RW="$WORK/$1"
    RW_REC="$RW/rec"
    rm -rf "$RW"
    mkdir -p "$RW/etc/verifier" "$RW/run/verifier" "$RW/var/log" "$RW/bin" "$RW_REC"
    : >"$RW_REC/who"
    : >"$RW_REC/procs"
    printf '%s\n' "$(date +%s)" >"$RW_REC/now"

    cat >"$RW/bin/date" <<'SHIM'
#!/usr/bin/env bash
# `+%s` is the reaper's clock and the case owns it; every other format is real
# time, because only the clock is under test.
for a in "$@"; do
    if [ "$a" = "+%s" ]; then cat "$REC/now"; exit 0; fi
done
exec /bin/date "$@"
SHIM
    cat >"$RW/bin/who" <<'SHIM'
#!/usr/bin/env bash
printf '%s' "$*" >>"$REC/who.argv"
printf '\n' >>"$REC/who.argv"
cat "$REC/who"
SHIM
    cat >"$RW/bin/pgrep" <<'SHIM'
#!/usr/bin/env bash
# The reaper calls `pgrep -u <user> -f <pattern>`; the pattern is the last
# argument. A match prints a pid and exits 0, exactly as pgrep does.
printf '%s\n' "$*" >>"$REC/pgrep.argv"
pat=""
for a in "$@"; do pat="$a"; done
if grep -E -- "$pat" "$REC/procs" >/dev/null 2>&1; then
    echo 4242
    exit 0
fi
exit 1
SHIM
    cat >"$RW/bin/shutdown" <<'SHIM'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$REC/shutdown.argv"
exit 0
SHIM
    cat >"$RW/bin/logger" <<'SHIM'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$REC/logger.argv"
exit 0
SHIM
    chmod +x "$RW/bin/date" "$RW/bin/who" "$RW/bin/pgrep" "$RW/bin/shutdown" "$RW/bin/logger"
}

rw_now() { cat "$RW_REC/now"; }
rw_set_now() { printf '%s\n' "$1" >"$RW_REC/now"; }
rw_session() { printf '%s\n' "$1" >"$RW_REC/who"; }
rw_process() { printf '%s\n' "$1" >>"$RW_REC/procs"; }
rw_expires() { printf '%s\n' "$1" >"$RW/etc/verifier/expires"; }
rw_idle_minutes() { printf '%s\n' "$1" >"$RW/etc/verifier/idle-minutes"; }
rw_activity_minutes_ago() {
    : >"$RW/run/verifier/last-activity"
    set_mtime "$RW/run/verifier/last-activity" "$(($(rw_now) - $1 * 60))"
}
rw_booted_seconds_ago() { printf '%s\n' "$(($(rw_now) - $1))" >"$RW/run/verifier/boot-at"; }

RW_RC=0
rw_run() {
    RW_RC=0
    env -i \
        PATH="$RW/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
        HOME="$RW" \
        REC="$RW_REC" \
        VERIFIER_ROOT="$RW" \
        VERIFIER_USER=verifier \
        bash "$ROOT/$REAPER" >"$RW/out" 2>&1 || RW_RC=$?
}

rw_decision() { sed -n '1,$p' "$RW/out"; }
rw_says() { grep -F -- "$1" "$RW/out" >/dev/null 2>&1; }
rw_logged() { grep -F -- "$1" "$RW/var/log/verifier-reaper.log" >/dev/null 2>&1; }
rw_shutdowns() {
    if [ -f "$RW_REC/shutdown.argv" ]; then
        grep -c . "$RW_REC/shutdown.argv"
    else
        echo 0
    fi
}
rw_report() {
    echo "    --- reaper stdout ---"
    sed 's/^/    /' "$RW/out"
    echo "    --- reaper log ---"
    sed 's/^/    /' "$RW/var/log/verifier-reaper.log" 2>/dev/null || echo "    (no log written)"
}

# Every reaper case ends here: the decision text, the log line and the shutdown
# count are asserted together, because a decision that says hold and shuts down
# anyway is the failure that costs a verdict.
rw_expect() {
    local want="$1" shutdowns="$2"
    if [ "$RW_RC" != "0" ]; then
        bad "the reaper exited ${RW_RC}"
        rw_report
        return
    fi
    if ! rw_says "$want"; then
        bad "wanted the decision '${want}' on stdout"
        rw_report
        return
    fi
    if ! rw_logged "$want"; then
        bad "the decision '${want}' was not appended to var/log/verifier-reaper.log"
        rw_report
        return
    fi
    if ! rw_logged "reaper "; then
        bad "the log line does not carry the 'reaper <utc> <decision>' shape"
        rw_report
        return
    fi
    local got
    got="$(rw_shutdowns)"
    if [ "$got" != "$shutdowns" ]; then
        bad "wanted ${shutdowns} shutdown call(s), got ${got}"
        rw_report
        return
    fi
    ok "${want} · shutdown x${shutdowns}"
}

case_reaper_holds_on_a_fresh_boot() {
    CURRENT=case_reaper_holds_on_a_fresh_boot
    rw_new fresh
    rw_expires "$(iso_at "$(($(rw_now) + 4 * 3600))")"
    rw_idle_minutes 30
    rw_activity_minutes_ago 1
    rw_run
    rw_expect "hold: fresh (1m < 30m)" 0
}

case_reaper_holds_while_a_session_is_live() {
    CURRENT=case_reaper_holds_while_a_session_is_live
    rw_new session
    rw_expires "$(iso_at "$(($(rw_now) + 4 * 3600))")"
    rw_idle_minutes 30
    rw_activity_minutes_ago 90
    rw_session "verifier pts/0        2026-09-15 21:04 (10.0.0.9)"
    rw_run
    rw_expect "hold: session" 0
}

case_reaper_holds_while_the_gate_is_running() {
    CURRENT=case_reaper_holds_while_the_gate_is_running
    rw_new busy
    rw_expires "$(iso_at "$(($(rw_now) + 4 * 3600))")"
    rw_idle_minutes 30
    rw_activity_minutes_ago 90
    rw_process "bash ./scripts/check.sh --loop"
    rw_run
    rw_expect "hold: busy (check.sh)" 0
}

case_reaper_reaps_when_idle_passes_the_threshold() {
    CURRENT=case_reaper_reaps_when_idle_passes_the_threshold
    rw_new idle
    rw_expires "$(iso_at "$(($(rw_now) + 4 * 3600))")"
    rw_idle_minutes 30
    rw_activity_minutes_ago 31
    rw_run
    rw_expect "reap: idle 31m ≥ 30m" 1
    CURRENT=case_reaper_reaps_when_idle_passes_the_threshold
    if rw_says "shutdown -h now"; then
        ok "the decision names the command it ran"
    else
        bad "the reap decision does not name 'shutdown -h now'"
    fi
    if grep -F -- "-h now" "$RW_REC/shutdown.argv" >/dev/null 2>&1; then
        ok "shutdown was called with -h now"
    else
        bad "shutdown was not called with '-h now': $(cat "$RW_REC/shutdown.argv" 2>/dev/null)"
    fi
}

case_reaper_reaps_an_expired_box_even_mid_gate() {
    CURRENT=case_reaper_reaps_an_expired_box_even_mid_gate
    rw_new expired
    local when
    when="$(iso_at "$(($(rw_now) - 1))")"
    rw_expires "$when"
    rw_idle_minutes 30
    rw_activity_minutes_ago 0
    rw_session "verifier pts/0        2026-09-15 21:04 (10.0.0.9)"
    rw_process "bash ./scripts/check.sh --loop"
    rw_booted_seconds_ago 7200
    rw_run
    rw_expect "reap: expired ${when}" 1
}

case_reaper_reaps_when_expires_is_unreadable() {
    CURRENT=case_reaper_reaps_when_expires_is_unreadable
    rw_new no_expires
    rw_idle_minutes 30
    rw_activity_minutes_ago 1
    rw_booted_seconds_ago 7200
    # no etc/verifier/expires at all
    rw_run
    rw_expect "reap: expires unreadable — fail closed" 1
}

case_reaper_reaps_when_expires_is_unparsable() {
    CURRENT=case_reaper_reaps_when_expires_is_unparsable
    rw_new bad_expires
    rw_expires "not-a-date"
    rw_idle_minutes 30
    rw_activity_minutes_ago 1
    rw_booted_seconds_ago 7200
    rw_run
    rw_expect "reap: expires unreadable — fail closed" 1
}

case_reaper_uses_the_default_idle_minutes_and_says_so() {
    CURRENT=case_reaper_uses_the_default_idle_minutes_and_says_so
    rw_new default_idle
    rw_expires "$(iso_at "$(($(rw_now) + 4 * 3600))")"
    rw_activity_minutes_ago 31
    # no etc/verifier/idle-minutes at all
    rw_run
    rw_expect "reap: idle 31m ≥ 30m (default)" 1
}

# A reaper case whose subject is a REFUSAL rather than a decision: the two
# inputs it cannot do without are the clock and the activity marker's mtime, and
# neither absence is a decision it may guess at. Exit 2, nothing decided, no
# shutdown — the timer asks again in a minute.
rw_expect_cannot_look() {
    local want="$1"
    if [ "$RW_RC" != "2" ]; then
        bad "wanted exit 2 (could-not-look), got ${RW_RC}"
        rw_report
        return
    fi
    if ! rw_says "$want"; then
        bad "wanted '${want}' on stderr"
        rw_report
        return
    fi
    local got
    got="$(rw_shutdowns)"
    if [ "$got" != "0" ]; then
        bad "it could not decide and shut the box down anyway (${got} call(s))"
        rw_report
        return
    fi
    ok "exit 2, '${want}', shutdown x0"
}

case_reaper_reaps_when_the_activity_marker_is_missing() {
    CURRENT=case_reaper_reaps_when_the_activity_marker_is_missing
    # Fail closed in the money direction, and REACHED ONLY after the session and
    # busy holds above — so a box doing real work can never be taken by it.
    rw_new no_activity
    rw_expires "$(iso_at "$(($(rw_now) + 4 * 3600))")"
    rw_idle_minutes 30
    rm -f "$RW/run/verifier/last-activity"
    rw_run
    rw_expect "reap: last-activity missing — fail closed" 1
}

case_reaper_cannot_read_the_clock_and_says_so() {
    CURRENT=case_reaper_cannot_read_the_clock_and_says_so
    rw_new no_clock
    rw_expires "$(iso_at "$(($(rw_now) + 4 * 3600))")"
    rw_idle_minutes 30
    rw_activity_minutes_ago 1
    # `date +%s` answers something that is not an epoch.
    printf '%s\n' "not-an-epoch" >"$RW_REC/now"
    rw_run
    rw_expect_cannot_look "could not read the clock"
}

case_reaper_cannot_read_the_activity_mtime_and_says_so() {
    CURRENT=case_reaper_cannot_read_the_activity_mtime_and_says_so
    rw_new no_mtime
    rw_expires "$(iso_at "$(($(rw_now) + 4 * 3600))")"
    rw_idle_minutes 30
    rw_activity_minutes_ago 1
    # The marker is THERE — so the fail-closed branch above is not the one under
    # test — and `stat` cannot answer for it in either dialect.
    cat >"$RW/bin/stat" <<'SHIM'
#!/usr/bin/env bash
echo "stat: cannot read file system information" >&2
exit 1
SHIM
    chmod +x "$RW/bin/stat"
    rw_run
    rw_expect_cannot_look "could not read the mtime"
}

case_reaper_holds_inside_the_boot_grace() {
    CURRENT=case_reaper_holds_inside_the_boot_grace
    # NOT one of the eight the criteria name — the ninth, and it is the clock
    # risk the design declares: a box whose chrony has not synced at boot can
    # read an expiry it has already passed and reap a machine somebody is about
    # to use. The grace is honoured ONLY when the box says when it booted.
    rw_new boot_grace
    rw_expires "$(iso_at "$(($(rw_now) - 1))")"
    rw_idle_minutes 30
    rw_activity_minutes_ago 0
    rw_booted_seconds_ago 30
    rw_run
    rw_expect "hold: boot grace" 0
}

# =============================================================================
# GROUP 2 — the user-data seam
# =============================================================================

SEAM_PUBKEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyForTheDriveOnly verifier@drive" # pragma: allowlist secret
SEAM_OWNER="a-session-name"
SEAM_EXPIRES="2026-09-16T03:10:00Z"
SEAM_IDLE="30"
# THE FIFTH SLOT. `/etc/djb/image-id` is the machine half of every drive verdict
# a box banks (`scripts/gate_ledger.sh`, `drive_machine_digest`) and the second
# box marker `scripts/check.sh` already names; it is written here because a box
# cannot be asked which image it was cut from.
SEAM_IMAGE="ami-0drive0drive0drive"

# The render is `sed`, not envsubst: envsubst is not on a mac by default and is
# not on a minimal Amazon Linux either, and the launch wrapper renders this same
# file the same way.
seam_render() {
    sed -e "s|\${VERIFIER_PUBKEY}|${SEAM_PUBKEY}|g" \
        -e "s|\${VERIFIER_OWNER}|${SEAM_OWNER}|g" \
        -e "s|\${VERIFIER_EXPIRES}|${SEAM_EXPIRES}|g" \
        -e "s|\${VERIFIER_IDLE_MINUTES}|${SEAM_IDLE}|g" \
        -e "s|\${VERIFIER_IMAGE_ID}|${SEAM_IMAGE}|g" \
        "$1" >"$2"
}

case_user_data_renders_with_four_values_and_leaves_no_slot() {
    CURRENT=case_user_data_renders_with_four_values_and_leaves_no_slot
    local out="$WORK/user-data.yaml"
    seam_render "$SEAM" "$out"

    local slots
    slots="$(grep -oE '\$\{[A-Z_]+\}' "$SEAM" | sort -u | tr '\n' ' ')"
    if [ "$slots" = "\${VERIFIER_EXPIRES} \${VERIFIER_IDLE_MINUTES} \${VERIFIER_IMAGE_ID} \${VERIFIER_OWNER} \${VERIFIER_PUBKEY} " ]; then
        ok "the template declares exactly the five slots the launch wrapper renders"
    else
        bad "the template's slots are '${slots}' — the wrapper renders exactly five"
    fi

    if grep -oE '\$\{[A-Za-z_]+\}' "$out" >/dev/null 2>&1; then
        bad "a slot survived the render: $(grep -oE '\$\{[A-Za-z_]+\}' "$out" | tr '\n' ' ')"
    else
        ok "no \${…} survives the render"
    fi

    if python3 -c 'import yaml' >/dev/null 2>&1; then
        if python3 - "$out" <<'PY'
import sys, yaml
d = yaml.safe_load(open(sys.argv[1]))
assert isinstance(d, dict), "cloud-config is not a mapping"
PY
        then
            ok "the rendered cloud-config parses as YAML"
        else
            bad "the rendered cloud-config is not valid YAML"
        fi
    else
        # The declared fallback: no PyYAML here, so the shape is grepped and the
        # case SAYS it looked at less than it wanted to.
        if head -n 1 "$out" | grep -E '^#cloud-config$' >/dev/null; then
            ok "no PyYAML on this python3 — shape only: the first line is #cloud-config"
        else
            bad "no PyYAML on this python3, and the first line is not '#cloud-config'"
        fi
    fi
}

case_user_data_carries_the_four_properties_the_launch_depends_on() {
    CURRENT=case_user_data_carries_the_four_properties_the_launch_depends_on
    local out="$WORK/user-data.yaml"
    [ -f "$out" ] || seam_render "$SEAM" "$out"

    if python3 -c 'import yaml' >/dev/null 2>&1; then
        local verdict
        verdict="$(python3 - "$out" "$SEAM_PUBKEY" "$SEAM_EXPIRES" "$SEAM_OWNER" "$SEAM_IDLE" <<'PY'
import sys, yaml
doc = yaml.safe_load(open(sys.argv[1]))
pub, expires, owner, idle = sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
problems = []
users = {u.get("name"): u for u in doc.get("users", []) if isinstance(u, dict)}
v = users.get("verifier")
if v is None:
    problems.append("no user named verifier")
elif pub not in [str(k).strip() for k in v.get("ssh_authorized_keys", [])]:
    problems.append("the public key is not in users[verifier].ssh_authorized_keys")
files = {f.get("path"): f for f in doc.get("write_files", []) if isinstance(f, dict)}
for path, want in (("/etc/verifier/expires", expires),
                   ("/etc/verifier/owner", owner),
                   ("/etc/verifier/idle-minutes", idle)):
    f = files.get(path)
    if f is None:
        problems.append("%s is not written" % path)
    elif str(f.get("content", "")).strip() != want:
        problems.append("%s carries %r, wanted %r" % (path, str(f.get("content", "")).strip(), want))
runcmd = " ".join(str(x) for x in doc.get("runcmd", []))
if "verifier-reaper.timer" not in runcmd:
    problems.append("runcmd does not enable verifier-reaper.timer")
print("; ".join(problems) if problems else "OK")
PY
        )"
        if [ "$verdict" = "OK" ]; then
            ok "pubkey, the three /etc/verifier files and the timer are all where the launch expects them"
        else
            bad "$verdict"
        fi
    else
        local misses=""
        grep -F "ssh_authorized_keys" "$out" >/dev/null || misses="${misses} ssh_authorized_keys"
        grep -F "/etc/verifier/expires" "$out" >/dev/null || misses="${misses} /etc/verifier/expires"
        grep -F "$SEAM_EXPIRES" "$out" >/dev/null || misses="${misses} the-expiry-value"
        grep -F "verifier-reaper.timer" "$out" >/dev/null || misses="${misses} the-timer"
        if [ -z "$misses" ]; then
            ok "no PyYAML on this python3 — shape only: every property is present as text"
        else
            bad "no PyYAML on this python3, and these are absent as text:${misses}"
        fi
    fi

    # The unit the timer starts must exist in the same directory, or the boot
    # enables a target the image does not carry.
    if grep -F "$(basename "$REAPER")" "$UNIT" >/dev/null; then
        ok "the service unit names the reaper script"
    else
        bad "the service unit does not name $(basename "$REAPER")"
    fi
    if grep -E 'OnUnitActiveSec=|OnBootSec=' "$TIMER" >/dev/null; then
        ok "the timer declares its interval"
    else
        bad "the timer declares no OnBootSec/OnUnitActiveSec"
    fi
}

# --- the BAKE box's own bootstrap, which is a different seam -----------------
#
# A BAKE BOX BOOTS RAW AMAZON LINUX AND IS PUSHED INTO BEFORE THE RECIPE RUNS.
# FIELD TEST 2 met what that costs when nothing prepares it first: the push
# reached the box's own shell and the box answered `bash: line 1:
# git-receive-pack: command not found`, `fatal: Could not read from remote
# repository`, exit 128 — no git, and no repository at the checkout path. So
# this seam installs git AND initialises the repository the push lands in, and
# it writes its ready marker LAST, because the SSM agent registers Online on
# its own schedule and never waits for cloud-init's runcmd.
#
# THE PATH IS DERIVED, NEVER RE-TYPED. `bake.sh` is the one place the checkout
# path is written down; the drive reads it exactly the way the wrapper does, so
# a drive that went green while the two drifted apart is not reachable.
bake_seam_user() {
    local user
    user="$(sed -n 's|^BAKE_USER="\${DJB_VERIFIER_BAKE_USER:-\(.*\)}"$|\1|p' "$BAKE")"
    printf '%s\n' "${user%%$'\n'*}"
}
bake_seam_checkout() {
    local user path
    user="$(bake_seam_user)"
    path="$(sed -n 's|^BAKE_CHECKOUT="\${DJB_VERIFIER_CHECKOUT:-\(.*\)}"$|\1|p' "$BAKE")"
    path="${path%%$'\n'*}"
    printf '%s\n' "${path//\$\{BAKE_USER\}/$user}"
}
bake_seam_render() {
    sed -e "s|\${VERIFIER_PUBKEY}|${SEAM_PUBKEY}|g" \
        -e "s|\${VERIFIER_CHECKOUT}|$(bake_seam_checkout)|g" \
        "$1" >"$2"
}

case_bake_user_data_installs_git_and_initialises_the_checkout() {
    CURRENT=case_bake_user_data_installs_git_and_initialises_the_checkout
    local out="$WORK/bake-user-data.yaml"
    bake_seam_render "$BAKE_SEAM" "$out"

    local slots
    slots="$(grep -oE '\$\{[A-Z_]+\}' "$BAKE_SEAM" | sort -u | tr '\n' ' ')"
    if [ "$slots" = "\${VERIFIER_CHECKOUT} \${VERIFIER_PUBKEY} " ]; then
        ok "the bake seam declares exactly the two slots the wrapper renders"
    else
        bad "the bake seam's slots are '${slots}' — the wrapper renders \${VERIFIER_CHECKOUT} and \${VERIFIER_PUBKEY}"
    fi
    if grep -oE '\$\{[A-Za-z_]+\}' "$out" >/dev/null 2>&1; then
        bad "a slot survived the render: $(grep -oE '\$\{[A-Za-z_]+\}' "$out" | tr '\n' ' ')"
    else
        ok "no \${…} survives the bake render"
    fi

    local checkout user
    checkout="$(bake_seam_checkout)"
    user="$(bake_seam_user)"
    if [ -n "$checkout" ] && [ -n "$user" ]; then
        ok "the recipe's own knobs read: ${user} at ${checkout}"
    else
        bad "could not read BAKE_USER/BAKE_CHECKOUT out of ${BAKE} — this case needs both"
        return
    fi

    if python3 -c 'import yaml' >/dev/null 2>&1; then
        local verdict
        verdict="$(python3 - "$out" "$checkout" "$user" <<'PY'
import re, sys, yaml

doc = yaml.safe_load(open(sys.argv[1]))
checkout, user = sys.argv[2], sys.argv[3]
problems = []
entries = doc.get("runcmd") or []


def flat(e):
    return " ".join(str(x) for x in e) if isinstance(e, list) else str(e)


lines = [flat(e) for e in entries]
if not lines:
    problems.append("runcmd is empty")

installs = [i for i, l in enumerate(lines) if re.search(r"\b(dnf|yum)\b", l) and " install" in l]
if not installs:
    problems.append("no package install in runcmd")
elif not any(re.search(r"\bgit\b", lines[i]) for i in installs):
    problems.append("the package install does not name git: %r" % [lines[i] for i in installs])

init = [i for i, l in enumerate(lines) if re.search(r"\bgit\b", l) and re.search(r"\binit\b", l)]
if not init:
    problems.append("no runcmd initialises a git repository")
else:
    i = init[0]
    if checkout not in lines[i]:
        problems.append("the init does not name the recipe's checkout %s: %r" % (checkout, lines[i]))
    if not re.search(r"-b\s+main\b", lines[i]):
        problems.append("the init does not put HEAD on main (-b main): %r" % lines[i])
    if installs and i < min(installs):
        problems.append("the repository is initialised before git is installed")

    deny = [
        l
        for l in lines
        if "receive.denyCurrentBranch" in l and "updateInstead" in l and checkout in l
    ]
    if not deny:
        problems.append(
            "no runcmd sets receive.denyCurrentBranch=updateInstead on %s — "
            "`push --force main:main` into a checked-out branch is refused by git" % checkout
        )

owned = [l for l in lines if user in l and checkout in l]
if not owned:
    problems.append("no runcmd gives %s to the bake user %s" % (checkout, user))

print("; ".join(problems) if problems else "OK")
PY
        )"
        if [ "$verdict" = "OK" ]; then
            ok "git is installed, and ${checkout} is initialised on main for ${user} with updateInstead"
        else
            bad "$verdict"
        fi
    else
        # The declared fallback, in the shape the seam cases above use: no
        # PyYAML here, so the properties are grepped as text and the case SAYS
        # it looked at less than it wanted to.
        local misses=""
        grep -E '\bgit\b' "$out" >/dev/null || misses="${misses} git"
        grep -F -- "$checkout" "$out" >/dev/null || misses="${misses} the-checkout-path"
        grep -F -- "updateInstead" "$out" >/dev/null || misses="${misses} updateInstead"
        if [ -z "$misses" ]; then
            ok "no PyYAML on this python3 — shape only: git, the checkout and updateInstead are present as text"
        else
            bad "no PyYAML on this python3, and these are absent as text:${misses}"
        fi
    fi

    # AND THE PATH IS NOT SPELLED TWICE. The slot is the whole point: a literal
    # here and a knob in the recipe is exactly the drift the wrapper's own
    # derivation exists to prevent.
    if grep -F -- "$checkout" "$BAKE_SEAM" >/dev/null 2>&1; then
        bad "the bake seam spells ${checkout} literally — it must carry the \${VERIFIER_CHECKOUT} slot"
    else
        ok "the bake seam never spells the checkout path itself"
    fi
}

case_bake_user_data_writes_its_ready_marker_last() {
    CURRENT=case_bake_user_data_writes_its_ready_marker_last
    # THE ORDER PROBLEM, MADE A PROPERTY OF THE FILE. cloud-init's `runcmd` is
    # the LAST boot stage; the SSM agent is a systemd unit that starts on its
    # own and reports Online long before a `dnf install` finishes. So
    # `PingStatus=Online` is not "the box is prepared", and the only thing that
    # is, is a marker the seam writes after everything else. It lives under
    # /run — a tmpfs — so it can never be captured into the image and can never
    # be left over from a previous boot.
    local out="$WORK/bake-user-data.yaml"
    [ -f "$out" ] || bake_seam_render "$BAKE_SEAM" "$out"

    if ! python3 -c 'import yaml' >/dev/null 2>&1; then
        ok "no PyYAML on this python3 — shape only: $(grep -c 'bake-ready' "$out" || true) mention(s) of a ready marker"
        return
    fi
    local verdict checkout
    checkout="$(bake_seam_checkout)"
    verdict="$(python3 - "$out" "$checkout" <<'PY'
import re, sys, yaml

doc = yaml.safe_load(open(sys.argv[1]))
checkout = sys.argv[2]
entries = doc.get("runcmd") or []


def flat(e):
    return " ".join(str(x) for x in e) if isinstance(e, list) else str(e)


lines = [flat(e) for e in entries]
if not lines:
    print("runcmd is empty")
    raise SystemExit(0)
last = lines[-1]
m = re.search(r"(/\S*ready\S*)", last)
problems = []
if m is None:
    problems.append("the last runcmd writes no ready marker: %r" % last)
else:
    path = m.group(1)
    if not path.startswith("/run/"):
        problems.append(
            "the ready marker %s is not under /run — anything else is captured into the image" % path
        )
    earlier = [i for i, l in enumerate(lines[:-1]) if path in l and not l.startswith("install ")]
    if earlier:
        problems.append("the marker is also touched before the last entry: %r" % [lines[i] for i in earlier])
    # IT VOUCHES FOR THE REPOSITORY, NOT FOR ITS OWN POSITION. A marker meaning
    # only that runcmd reached its end is written by a boot where git init
    # failed, and the wrapper then pushes into it and gets the exit 128 of
    # FIELD TEST 2 back. (No apostrophe and no backtick in this block: a
    # heredoc body inside a command substitution is parsed by bash for quoting,
    # and one unbalanced quote here is a syntax error 80 lines away.)
    if not (re.search(r"\btest\b", last) and checkout in last):
        problems.append(
            "the last runcmd writes the marker without testing %s first: %r" % (checkout, last)
        )
    # AND IT VOUCHES FOR ALL OF IT, DERIVED BOTH WAYS. The gap a review
    # found: if git init succeeds and the config entry beside it fails, .git
    # exists, the guard passes, the marker is written, the wrapper pushes, and
    # git answers
    #     ! [remote rejected] main -> main (branch is currently checked out)
    #   which is FIELD TEST 2 again, wearing a marker that said the box was
    # prepared. So the SETTINGS the runcmds establish and the PROPERTIES the
    # guard asserts are read out of the file and compared in BOTH directions:
    # a setting nobody guards is the gap above, and a property nobody sets is a
    # guard that vouches for something this seam never did.
    sets = {}
    for line in lines[:-1]:
        for key, value in re.findall(r"\bconfig\s+(\S+)\s+(\S+)", line):
            sets[key] = value
    for key, value in sorted(sets.items()):
        if key not in last or value not in last:
            problems.append(
                "runcmd sets %s=%s and the marker guard does not assert it: %r" % (key, value, last)
            )
    for key in sorted(re.findall(r"\b([a-z]+\.[a-zA-Z]+)\b", last)):
        if key not in sets:
            problems.append(
                "the marker guard asserts %s, which no runcmd of this seam sets" % key
            )
    print("MARKER %s" % path)
print("; ".join(problems) if problems else "OK")
PY
    )"
    local marker
    marker="$(printf '%s\n' "$verdict" | sed -n 's/^MARKER //p')"
    verdict="$(printf '%s\n' "$verdict" | grep -v '^MARKER ' || true)"
    if [ "$verdict" = "OK" ]; then
        ok "the last runcmd tests the repository and then writes ${marker}, on a tmpfs the image cannot carry"
    else
        bad "$verdict"
    fi
}

# =============================================================================
# GROUP 3 — the ops policy
# =============================================================================

policy_py() { python3 - "$POLICY" "$@"; }

case_policy_summary_prints_every_statement() {
    CURRENT=case_policy_summary_prints_every_statement
    local out="$WORK/policy-summary.txt" rc=0
    # policy_summary.py reads the document on STDIN and takes the MODE as its
    # first argument. (The criteria's line spells it as a path argument; that
    # form sets mode to the path, reads an empty stdin and prints "(nothing to
    # read)" at exit 0 — a green that looked at nothing.)
    "$DRIVE_PY" "$SUMMARY" role <"$POLICY" >"$out" 2>&1 || rc=$?
    if [ "$rc" != "0" ]; then
        bad "policy_summary.py exited ${rc}"
        return
    fi
    local want got
    want="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["Statement"]))' "$POLICY")"
    got="$(grep -c . "$out")"
    if [ "$want" = "$got" ]; then
        ok "${got} statement(s) in the document, ${got} line(s) in the summary"
    else
        bad "${want} statement(s) in the document but ${got} line(s) in the summary"
    fi
    if grep -E 'CAN DELETE' "$out" >/dev/null; then
        bad "the summary flags an S3 delete grant — this policy has no s3: action at all"
    else
        ok "no S3 delete grant flagged"
    fi
}

case_policy_every_terminate_allow_is_tag_conditioned() {
    CURRENT=case_policy_every_terminate_allow_is_tag_conditioned
    local verdict
    verdict="$(policy_py <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
problems = []
seen = 0
for s in doc["Statement"]:
    acts = s["Action"] if isinstance(s["Action"], list) else [s["Action"]]
    if s["Effect"] != "Allow" or "ec2:TerminateInstances" not in acts:
        continue
    seen += 1
    cond = json.dumps(s.get("Condition", {}))
    if "ec2:ResourceTag/djb:role" not in cond:
        problems.append("%s has no ec2:ResourceTag/djb:role condition" % s.get("Sid"))
if seen == 0:
    problems.append("no TerminateInstances Allow at all — the wrapper could not take a box down")
print("; ".join(problems) if problems else "OK %d" % seen)
PY
    )"
    case "$verdict" in
    "OK "*) ok "${verdict#OK } TerminateInstances Allow(s), every one conditioned on ec2:ResourceTag/djb:role" ;;
    *) bad "$verdict" ;;
    esac
}

case_policy_run_instances_on_an_instance_needs_all_three_request_tags() {
    CURRENT=case_policy_run_instances_on_an_instance_needs_all_three_request_tags
    local verdict
    verdict="$(policy_py <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
problems = []
seen = 0
for s in doc["Statement"]:
    acts = s["Action"] if isinstance(s["Action"], list) else [s["Action"]]
    res = s["Resource"] if isinstance(s["Resource"], list) else [s["Resource"]]
    if s["Effect"] != "Allow" or "ec2:RunInstances" not in acts:
        continue
    if not any(r.endswith(":instance/*") for r in res):
        continue
    seen += 1
    cond = json.dumps(s.get("Condition", {}))
    for key in ("aws:RequestTag/djb:role", "aws:RequestTag/djb:owner", "aws:RequestTag/djb:expires"):
        if key not in cond:
            problems.append("%s does not require %s" % (s.get("Sid"), key))
    if "instance/*" in json.dumps(res) and len(res) > 1:
        problems.append("%s mixes instance/* with other resources under one Condition" % s.get("Sid"))
if seen == 0:
    problems.append("no RunInstances Allow on instance/* at all")
print("; ".join(problems) if problems else "OK %d" % seen)
PY
    )"
    case "$verdict" in
    "OK "*) ok "${verdict#OK } RunInstances Allow(s) on instance/*, each requiring role+owner+expires at request time" ;;
    *) bad "$verdict" ;;
    esac
}

# THE ARN WITH NO ACCOUNT IN IT, which is the whole of this case. An EC2 IMAGE
# and an EC2 SNAPSHOT are named `arn:aws:ec2:<region>::image/*` and
# `arn:aws:ec2:<region>::snapshot/*` — the account field is EMPTY, because the
# resource is not owned per-account in the ARN the way an instance is. So an
# account-scoped `arn:aws:ec2:<region>:<account>:*/*` matches every INSTANCE
# resource and NOT ONE image or snapshot: the same statement that tags an
# instance at `run-instances` refuses `ec2:CreateTags` during `create-image`,
# on both of the resources that call creates. It is exactly the shape that
# reads correct and is wrong, and it cost a bake box's capture to find: the
# image landed UNTAGGED and the wrapper, which finds images by tag, could not
# see it.
case_policy_tags_the_image_and_the_snapshot_a_capture_creates() {
    CURRENT=case_policy_tags_the_image_and_the_snapshot_a_capture_creates
    local verdict
    verdict="$(policy_py <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
problems = []
seen = 0
for s in doc["Statement"]:
    acts = s["Action"] if isinstance(s["Action"], list) else [s["Action"]]
    if s["Effect"] != "Allow" or "ec2:CreateTags" not in acts:
        continue
    seen += 1
    res = s["Resource"] if isinstance(s["Resource"], list) else [s["Resource"]]
    cond = json.dumps(s.get("Condition", {}))
    if "ec2:CreateAction" not in cond:
        problems.append("%s grants CreateTags with no ec2:CreateAction condition" % s.get("Sid"))
    if "CreateImage" not in cond:
        problems.append("%s does not allow tagging during CreateImage" % s.get("Sid"))
    # The three the capture and the launch between them need. The account-less
    # pair is the half an account-scoped wildcard silently does not cover.
    for want in ("arn:aws:ec2:${REGION}:${ACCOUNT_ID}:*/*",
                 "arn:aws:ec2:${REGION}::image/*",
                 "arn:aws:ec2:${REGION}::snapshot/*"):
        if want not in res:
            problems.append("%s does not reach %s" % (s.get("Sid"), want))
if seen == 0:
    problems.append("no ec2:CreateTags Allow at all — nothing this credential creates could be tagged")
print("; ".join(problems) if problems else "OK %d" % seen)
PY
    )"
    case "$verdict" in
    "OK "*) ok "${verdict#OK } CreateTags Allow(s) reaching instances, images AND snapshots, all under ec2:CreateAction" ;;
    *) bad "$verdict" ;;
    esac
}

case_policy_passrole_names_only_the_verifier_box_role() {
    CURRENT=case_policy_passrole_names_only_the_verifier_box_role
    local verdict
    verdict="$(policy_py <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
problems = []
roles = []
for s in doc["Statement"]:
    acts = s["Action"] if isinstance(s["Action"], list) else [s["Action"]]
    if "iam:PassRole" not in acts:
        continue
    res = s["Resource"] if isinstance(s["Resource"], list) else [s["Resource"]]
    roles.extend(res)
    cond = json.dumps(s.get("Condition", {}))
    if "iam:PassedToService" not in cond:
        problems.append("%s passes a role without pinning iam:PassedToService" % s.get("Sid"))
if len(roles) != 1 or not roles[0].endswith("-verifier-box"):
    problems.append("PassRole names %r — it must name exactly the verifier box role" % roles)
elif "${NAMESPACE}" not in roles[0]:
    problems.append("PassRole names a FIXED role %r — it must derive from the deployment namespace" % roles[0])
print("; ".join(problems) if problems else "OK")
PY
    )"
    if [ "$verdict" = "OK" ]; then
        ok "PassRole names exactly <namespace>-verifier-box, pinned to ec2.amazonaws.com"
    else
        bad "$verdict"
    fi
}

case_policy_is_scoped_to_one_deployment_namespace() {
    CURRENT=case_policy_is_scoped_to_one_deployment_namespace
    # More than one product shares this AWS account. Without this, one
    # deployment's verifier credential could terminate another's boxes and one
    # deployment's census would list them.
    local verdict
    verdict="$(policy_py <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
must_be_scoped = {
    "ec2:RunInstances": "aws:RequestTag/djb:namespace",
    "ec2:TerminateInstances": "ec2:ResourceTag/djb:namespace",
    "ec2:CreateImage": "ec2:ResourceTag/djb:namespace",
    "ec2:DeregisterImage": "ec2:ResourceTag/djb:namespace",
    "ec2:DeleteSnapshot": "ec2:ResourceTag/djb:namespace",
    "ssm:StartSession": "ssm:resourceTag/djb:namespace",
    "ec2:GetConsoleOutput": "ec2:ResourceTag/djb:namespace",
}
problems = []
scoped = 0
for s in doc["Statement"]:
    if s["Effect"] != "Allow":
        continue
    acts = s["Action"] if isinstance(s["Action"], list) else [s["Action"]]
    res = s["Resource"] if isinstance(s["Resource"], list) else [s["Resource"]]
    # A statement whose resources are all account-independent reference data —
    # a public image, an AWS-owned document, a brand-new volume — carries no
    # resource tag to condition on and is not in scope here.
    if not any(("instance/*" in r or "image/*" in r or "snapshot/*" in r or
                "security-group/*" in r) for r in res):
        continue
    if all(r.startswith("arn:aws:ec2:${REGION}::") for r in res):
        continue
    for a in acts:
        key = must_be_scoped.get(a)
        if key is None:
            continue
        # The KEY differs by what the condition is about — a tag on the request
        # that creates a resource, a tag on a resource that already exists —
        # and one statement can legitimately use either. What may never be
        # missing is the namespace itself.
        if "djb:namespace" not in json.dumps(s.get("Condition", {})):
            problems.append("%s grants %s with no djb:namespace condition (wanted %s)"
                            % (s.get("Sid"), a, key))
        else:
            scoped += 1
if scoped == 0:
    problems.append("no statement is namespace-scoped at all")
print("; ".join(problems) if problems else "OK %d" % scoped)
PY
    )"
    case "$verdict" in
    "OK "*) ok "${verdict#OK } namespace-scoped grant(s); no tag-bearing resource is reachable across deployments" ;;
    *) bad "$verdict" ;;
    esac
}

case_no_product_name_is_baked_into_the_machinery() {
    CURRENT=case_no_product_name_is_baked_into_the_machinery
    # The rider's own census. The token is ASSEMBLED rather than spelled: a
    # guard that writes out the very string it forbids is a phantom hit for the
    # next census that reads this directory.
    local slug="pile" tail="cap"
    local hits
    hits="$(grep -rInE "${slug}${tail}[-/]" deploy/verifier deploy/iam || true)"
    if [ -z "$hits" ]; then
        ok "no deployment's own slug is hard-coded anywhere under deploy/verifier or deploy/iam"
    else
        bad "a deployment slug is hard-coded — every name must derive from DJB_DEPLOY_NAMESPACE:"
        printf '%s\n' "$hits" | sed 's/^/      /'
    fi

    # THE SAME RULE, TWO MORE COORDINATES. A product's name is the obvious one;
    # its AWS ACCOUNT NUMBER and its REGION are the two that read as harmless
    # infrastructure and are exactly as much a per-deployment fact. A template
    # that ships one deployment's account id has shipped a default that a clone
    # inherits silently, and a wrong account or a wrong region is a write into
    # somebody else's resources — the provisioning script's own sentence.
    local acct region
    acct="$(grep -rInE '[^0-9][0-9]{12}[^0-9]' deploy/verifier deploy/iam || true)"
    if [ -z "$acct" ]; then
        ok "no 12-digit account id anywhere under deploy/verifier or deploy/iam"
    else
        bad "an AWS account id is hard-coded — it belongs in the operator's shell, not the tree:"
        printf '%s\n' "$acct" | sed 's/^/      /'
    fi
    region="$(grep -rInE '\b(us|eu|ap|ca|sa|me|af|il)-(gov-)?(east|west|north|south|central|northeast|northwest|southeast|southwest)-[0-9]\b' deploy/verifier deploy/iam || true)"
    if [ -z "$region" ]; then
        ok "no region literal anywhere under deploy/verifier or deploy/iam"
    else
        bad "a region is hard-coded — a script that assumes one launches in the wrong place:"
        printf '%s\n' "$region" | sed 's/^/      /'
    fi
    # And the positive half: the names really are composed, not merely absent.
    local composed=0
    grep -F 'DJB_DEPLOY_NAMESPACE' "$BOOTSTRAP" >/dev/null && composed=$((composed + 1))
    grep -F '${NAMESPACE}-verifier-box' "$POLICY" >/dev/null && composed=$((composed + 1))
    if [ "$composed" = "2" ]; then
        ok "the bootstrap requires DJB_DEPLOY_NAMESPACE and the policy composes its role name from it"
    else
        bad "the names are absent but not composed (${composed}/2) — an empty slot is not a derivation"
    fi
}

case_bootstrap_refuses_without_a_deployment_namespace() {
    CURRENT=case_bootstrap_refuses_without_a_deployment_namespace
    bs_new nonamespace
    local rc=0
    env -i PATH="$BS/bin:/usr/bin:/bin" HOME="$BS" REC="$BS_REC" \
        bash "$ROOT/$BOOTSTRAP" --confirm >"$BS/out" 2>&1 || rc=$?
    if [ "$rc" = "2" ]; then
        ok "exit 2 with no DJB_DEPLOY_NAMESPACE, even with --confirm typed"
    else
        bad "wanted exit 2 with no namespace, got ${rc}"
        bs_report
    fi
    if grep -F -- "DJB_DEPLOY_NAMESPACE" "$BS/out" >/dev/null; then
        ok "the refusal names the variable it wants"
    else
        bad "the refusal does not name DJB_DEPLOY_NAMESPACE"
    fi
    if [ ! -f "$BS_REC/aws.argv" ]; then
        ok "not one aws call was made"
    else
        bad "aws was called before the namespace was known: $(cat "$BS_REC/aws.argv")"
    fi
}

case_policy_denies_every_write_to_an_environment_box() {
    CURRENT=case_policy_denies_every_write_to_an_environment_box
    # The braces over the belt. Every Allow above is already tag-conditioned;
    # this Deny is what answers "and if one of them is ever widened by accident".
    # Its shape is the environment boxes' own tags: a Project tag present and no
    # djb:role tag at all.
    local verdict
    verdict="$(policy_py <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
problems = []
found = None
for s in doc["Statement"]:
    if s["Effect"] != "Deny":
        continue
    found = s
    acts = s["Action"] if isinstance(s["Action"], list) else [s["Action"]]
    for want in ("ec2:TerminateInstances", "ec2:StopInstances",
                 "ec2:RebootInstances", "ec2:ModifyInstanceAttribute"):
        if want not in acts:
            problems.append("the Deny does not cover %s" % want)
    null = s.get("Condition", {}).get("Null", {})
    if str(null.get("ec2:ResourceTag/Project", "")).lower() != "false":
        problems.append("the Deny does not require a Project tag to be PRESENT")
    if str(null.get("ec2:ResourceTag/djb:role", "")).lower() != "true":
        problems.append("the Deny does not require djb:role to be ABSENT")
if found is None:
    problems.append("there is no Deny statement at all")
print("; ".join(problems) if problems else "OK")
PY
    )"
    if [ "$verdict" = "OK" ]; then
        ok "the Deny covers all four write actions on any Project-tagged instance with no djb:role"
    else
        bad "$verdict"
    fi
}

case_policy_grants_none_of_the_forbidden_action_families() {
    CURRENT=case_policy_grants_none_of_the_forbidden_action_families
    local verdict
    verdict="$(policy_py <<'PY'
import json, re, sys
doc = json.load(open(sys.argv[1]))
forbidden = [
    r"^iam:(Create|Put|Attach|Delete)",
    r"^secretsmanager:",
    r"^s3:",
    r"^ecr:",
    r"^ec2:(Authorize|Create)SecurityGroup",
    r"^ec2:CreateLaunchTemplate",
]
problems = []
for s in doc["Statement"]:
    if s["Effect"] != "Allow":
        continue
    acts = s["Action"] if isinstance(s["Action"], list) else [s["Action"]]
    for a in acts:
        for f in forbidden:
            if re.match(f, a):
                problems.append("%s grants %s" % (s.get("Sid"), a))
        if a == "*" or a.endswith(":*"):
            problems.append("%s grants the wildcard %s" % (s.get("Sid"), a))
print("; ".join(problems) if problems else "OK")
PY
    )"
    if [ "$verdict" = "OK" ]; then
        ok "no iam write, no secretsmanager, no s3, no ecr, no security-group write, no service wildcard"
    else
        bad "$verdict"
    fi
}

case_the_box_role_trusts_ec2_and_nothing_else() {
    CURRENT=case_the_box_role_trusts_ec2_and_nothing_else
    local verdict
    verdict="$(python3 - "$TRUST" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
problems = []
sts = doc.get("Statement", [])
if len(sts) != 1:
    problems.append("the trust policy has %d statements — one principal, one statement" % len(sts))
for s in sts:
    if s.get("Effect") != "Allow":
        problems.append("the trust statement is not an Allow")
    p = s.get("Principal", {})
    if p != {"Service": "ec2.amazonaws.com"}:
        problems.append("the principal is %r, not the EC2 service alone" % (p,))
    acts = s["Action"] if isinstance(s.get("Action"), list) else [s.get("Action")]
    if acts != ["sts:AssumeRole"]:
        problems.append("the trust action is %r, not sts:AssumeRole alone" % (acts,))
print("; ".join(problems) if problems else "OK")
PY
    )"
    if [ "$verdict" = "OK" ]; then
        ok "the box role is assumable by ec2.amazonaws.com and by nothing else"
    else
        bad "$verdict"
    fi
}

# =============================================================================
# GROUP 4 — the owner's bootstrap
# =============================================================================
#
# `aws` is planted on PATH and records every argv. Its answers come from two
# fixture switches: the account it reports, and whether the five resources
# already exist. Nothing reaches a network.

BS=""
BS_REC=""
bs_new() {
    BS="$WORK/$1"
    BS_REC="$BS/rec"
    rm -rf "$BS"
    mkdir -p "$BS/bin" "$BS_REC"
    printf '%s\n' "050254549871" >"$BS_REC/account"
    printf '%s\n' "fresh" >"$BS_REC/mode"
    cat >"$BS/bin/aws" <<'SHIM'
#!/usr/bin/env bash
# TWO RECORDS, and both are needed. `aws.argv` is the WHOLE command line,
# because "the secret never appears in an argument" is a claim about the whole
# line. `aws.ops` is the normalised `<service> <operation>`, because "exactly
# one create-policy" is a claim about operations and an anchored grep over a
# line that starts with the global options would have counted zero of them
# while every case still read green.
printf '%s\n' "$*" >>"$REC/aws.argv"
MODE="$(cat "$REC/mode")"
# The global options this script always passes come first; step over them so
# the operation is $1 $2.
while [ "$#" -gt 0 ]; do
    case "$1" in
    --region | --profile) shift 2 ;;
    *) break ;;
    esac
done
printf '%s %s\n' "${1:-}" "${2:-}" >>"$REC/aws.ops"
case "$1 $2" in
"sts get-caller-identity")
    printf '%s\n' "$(cat "$REC/account")"
    ;;
"iam get-policy" | "iam get-user" | "iam get-instance-profile")
    if [ "$MODE" = "exists" ]; then
        # THE DEFAULT VERSION ID, when that is what was asked for. The script
        # asks `get-policy` twice: once for existence, once for
        # `Policy.DefaultVersionId`, and a shim that answered `{"ok":true}` to
        # the second would hand the comparison a version id that is a JSON
        # object.
        case "$*" in
        *DefaultVersionId*) cat "$REC/policy.version" 2>/dev/null || echo "v1" ;;
        *) echo '{"ok":true}' ;;
        esac
    else
        echo "An error occurred (NoSuchEntity) when calling the operation" >&2
        exit 254
    fi
    ;;
"iam get-policy-version")
    # THE LIVE DOCUMENT, planted by the case that cares what it is. Absent, the
    # answer is an empty object — a live policy that is not this tree's, which
    # is the ordinary `exists` world and the one the re-run case reads.
    if [ "$MODE" = "exists" ]; then
        cat "$REC/policy.live" 2>/dev/null || echo "{}"
    else
        echo "An error occurred (NoSuchEntity) when calling the operation" >&2
        exit 254
    fi
    ;;
"iam get-role-policy")
    # THE BOX ROLE'S INLINE REGISTRY GRANT. Absent unless a case plants one,
    # which is the state every account is in before a human runs the
    # put-role-policy the bootstrap prints.
    if [ -f "$REC/rolepolicy.live" ]; then
        cat "$REC/rolepolicy.live"
    else
        echo "An error occurred (NoSuchEntity) when calling the GetRolePolicy operation" >&2
        exit 254
    fi
    ;;
"iam get-role")
    # THE SPOT SERVICE-LINKED ROLE IS ITS OWN QUESTION, and a case plants the
    # answer: `$REC/spot-slr` holding `exists` or `absent`. Without it the role
    # follows the mode, which keeps every case written before it unchanged.
    _slr="$(cat "$REC/spot-slr" 2>/dev/null || true)"
    case "$* $_slr" in
    *AWSServiceRoleForEC2Spot*exists*) echo '{"ok":true}' ;;
    *AWSServiceRoleForEC2Spot*absent*)
        echo "An error occurred (NoSuchEntity) when calling the GetRole operation" >&2
        exit 254
        ;;
    esac
    if [ "$MODE" = "exists" ]; then
        echo '{"ok":true}'
    else
        echo "An error occurred (NoSuchEntity) when calling the operation" >&2
        exit 254
    fi
    ;;
"iam list-access-keys")
    if [ "$MODE" = "exists" ]; then
        echo "FAKE-EXISTING-KEY-ID"
    fi
    ;;
"ec2 describe-security-groups")
    if [ "$MODE" = "exists" ]; then
        echo "sg-0verifier"
    else
        echo "None"
    fi
    ;;
"ec2 describe-vpcs")
    echo "vpc-0default"
    ;;
"iam create-access-key")
    # The one value the owner has to copy. Fixed here so the case can assert
    # both where it appears and where it must not.
    # Both values are ASSEMBLED rather than spelled: a key-shaped literal in a
    # tracked file is what the house rule's own raw scanner reads as a secret,
    # and that scanner has no pragma path.
    _s="driveOnly""NotARealSecret0000000000000000"
    printf '{"AccessKey":{"AccessKeyId":"FAKE-DRIVE-KEY-ID","SecretAccessKey":"%s"}}\n' "$_s"
    ;;
"ec2 create-security-group")
    echo "sg-0verifier"
    ;;
*)
    echo "{}"
    ;;
esac
exit 0
SHIM
    chmod +x "$BS/bin/aws"
}

bs_mode() { printf '%s\n' "$1" >"$BS_REC/mode"; }
bs_account() { printf '%s\n' "$1" >"$BS_REC/account"; }

# A namespace that is nobody's product, because the whole point of the rider
# these cases pin is that no product's name is baked into the machinery.
BS_NS="drivens"
# The three coordinates the operator supplies from their own shell. None of them
# has a default in the tree, so every case that wants to get past the refusals
# hands all three over explicitly — which is also what makes the three refusal
# cases below able to omit exactly one at a time.
BS_ACCOUNT="050254549871"
BS_REGION="us-east-1"

BS_RC=0
bs_run() {
    BS_RC=0
    env -i \
        PATH="$BS/bin:/usr/bin:/bin" \
        HOME="$BS" \
        REC="$BS_REC" \
        DJB_DEPLOY_NAMESPACE="$BS_NS" \
        DJB_VERIFIER_ACCOUNT="$BS_ACCOUNT" \
        DJB_VERIFIER_REGION="$BS_REGION" \
        bash "$ROOT/$BOOTSTRAP" "$@" >"$BS/out" 2>&1 || BS_RC=$?
}

# Counts OPERATIONS (`<service> <operation>`, one per call), which is what
# every "exactly once" and every "zero of these" claim below is about.
bs_calls() {
    if [ -f "$BS_REC/aws.ops" ]; then
        grep -cE "$1" "$BS_REC/aws.ops" || true
    else
        echo 0
    fi
}

# Counts whole COMMAND LINES — the form the two argument claims need.
bs_argv() {
    if [ -f "$BS_REC/aws.argv" ]; then
        grep -cE "$1" "$BS_REC/aws.argv" || true
    else
        echo 0
    fi
}
bs_report() {
    echo "    --- bootstrap stdout ---"
    sed 's/^/    /' "$BS/out"
    echo "    --- aws argv ---"
    sed 's/^/    /' "$BS_REC/aws.argv" 2>/dev/null || echo "    (no aws call recorded)"
}

case_the_owners_hand_is_a_command_the_tree_actually_spells() {
    CURRENT=case_the_owners_hand_is_a_command_the_tree_actually_spells
    # THE ONE HAND A HUMAN PERFORMS HAS TO BE COPY-PASTEABLE. Three variables
    # are required with no default — that is the right call, and it is exactly
    # what makes the usage header load-bearing: a header that shows a bare
    # `./deploy/iam/verifier_bootstrap.sh --confirm` shows a command that exits 2
    # on the first line of the script, and the owner's own two-command ceremony
    # then exists nowhere in the tree. The refusals name the variables, but a
    # refusal is what you read AFTER typing the wrong thing.
    local want="DJB_DEPLOY_NAMESPACE DJB_VERIFIER_ACCOUNT DJB_VERIFIER_REGION"

    # The header is everything above the script's own `set -euo pipefail`, with
    # backslash continuations folded back into one logical line each — the
    # command as a reader would type it.
    local header logical
    header="$(awk '/^set -euo pipefail$/ {exit} {print}' "$BOOTSTRAP")"
    logical="$(printf '%s\n' "$header" | sed -e 's/^# \{0,3\}//' | awk '
        { line = line $0 }
        /\\$/ { sub(/\\$/, " ", line); next }
        { print line; line = "" }
        END { if (line != "") print line }
    ')"

    local invocations bad_lines="" n=0 v missing
    # AN INVOCATION SPELLS THE PATH. Keying on the bare file name instead reads
    # the header's own PROSE about the script as a command to run — which is
    # what this detector did on its first pass, and a census that cannot tell a
    # sentence from a command is a census that reports on sentences.
    invocations="$(printf '%s\n' "$logical" | grep -E '\./deploy/iam/verifier_bootstrap\.sh( +--[a-z-]+)* *$' || true)"
    if [ -z "$invocations" ]; then
        bad "the header shows no invocation of the script at all"
        return
    fi
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        n=$((n + 1))
        missing=""
        for v in $want; do
            case "$line" in
            *"$v"*) ;;
            *) missing="${missing} ${v}" ;;
            esac
        done
        [ -z "$missing" ] || bad_lines="${bad_lines}    '${line}' is missing:${missing}
"
    done <<<"$invocations"

    if [ -z "$bad_lines" ]; then
        ok "${n} invocation line(s) in the header, every one carrying all three required variables"
    else
        bad "the header shows a command that would exit 2 before it did anything:
${bad_lines}"
    fi

    # And the same line where an operator looks for it, which is not a shell
    # script's comment block.
    local runbook=docs/runbooks/deploy.md
    if [ ! -f "$runbook" ]; then
        bad "${runbook} is not in this tree"
        return
    fi
    missing=""
    for v in $want; do
        grep -F -- "$v" "$runbook" >/dev/null || missing="${missing} ${v}"
    done
    if [ -z "$missing" ] && grep -F -- "verifier_bootstrap.sh" "$runbook" >/dev/null; then
        ok "the runbook spells the same command, all three variables named"
    else
        bad "the runbook does not carry the owner's hand — missing:${missing:- the script itself}"
    fi
}

case_bootstrap_refuses_without_an_account_or_a_region() {
    CURRENT=case_bootstrap_refuses_without_an_account_or_a_region
    # Two more required variables, the same grammar as the namespace and for the
    # same reason. The pair used to be defaults; a default account id is a
    # product fact shipped inside system machinery, and a default region is a
    # script that quietly launches somewhere else.
    local var
    for var in DJB_VERIFIER_ACCOUNT DJB_VERIFIER_REGION; do
        bs_new "no_${var}"
        local rc=0
        if [ "$var" = "DJB_VERIFIER_ACCOUNT" ]; then
            env -i PATH="$BS/bin:/usr/bin:/bin" HOME="$BS" REC="$BS_REC" \
                DJB_DEPLOY_NAMESPACE="$BS_NS" DJB_VERIFIER_REGION="$BS_REGION" \
                bash "$ROOT/$BOOTSTRAP" --confirm >"$BS/out" 2>&1 || rc=$?
        else
            env -i PATH="$BS/bin:/usr/bin:/bin" HOME="$BS" REC="$BS_REC" \
                DJB_DEPLOY_NAMESPACE="$BS_NS" DJB_VERIFIER_ACCOUNT="$BS_ACCOUNT" \
                bash "$ROOT/$BOOTSTRAP" --confirm >"$BS/out" 2>&1 || rc=$?
        fi
        if [ "$rc" != "2" ]; then
            bad "${var} unset: wanted exit 2, got ${rc}"
            bs_report
            continue
        fi
        if ! grep -F -- "$var" "$BS/out" >/dev/null; then
            bad "${var} unset: the refusal does not name the variable"
            continue
        fi
        if [ -f "$BS_REC/aws.argv" ]; then
            bad "${var} unset: aws was called anyway — $(head -n 1 "$BS_REC/aws.argv")"
            continue
        fi
        ok "${var} unset → exit 2, names the variable, not one aws call"
    done
}

case_bootstrap_refuses_without_confirm_and_creates_nothing() {
    CURRENT=case_bootstrap_refuses_without_confirm_and_creates_nothing
    bs_new refuse
    bs_run
    if [ "$BS_RC" = "2" ]; then
        ok "exit 2 without --confirm"
    else
        bad "wanted exit 2 without --confirm, got ${BS_RC}"
        bs_report
    fi
    local creates
    creates="$(bs_calls '(create|attach|add-role|authorize)-')"
    if [ "$creates" = "0" ]; then
        ok "zero create/attach calls recorded"
    else
        bad "${creates} create/attach call(s) recorded on the refusal path"
        bs_report
    fi
}

case_bootstrap_prints_its_whole_plan_before_it_refuses() {
    CURRENT=case_bootstrap_prints_its_whole_plan_before_it_refuses
    bs_new plan
    bs_run
    local misses=""
    for want in \
        "${BS_NS}-verifier-ops" \
        "${BS_NS}-verifier-box" \
        "AmazonSSMManagedInstanceCore" \
        "djb:namespace=${BS_NS}" \
        "access key"; do
        grep -F -- "$want" "$BS/out" >/dev/null || misses="${misses} '${want}'"
    done
    if [ -z "$misses" ]; then
        ok "the plan names every resource it would create"
    else
        bad "the plan does not name:${misses}"
        bs_report
    fi
    # The policy, statement by statement, in the same print — the owner reads
    # what they are about to attach rather than opening a JSON file.
    local statements
    statements="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["Statement"]))' "$POLICY")"
    local printed
    printed="$(grep -cE '^ +[A-Za-z0-9]+ +(Allow|Deny) ' "$BS/out" || true)"
    if [ "$printed" = "$statements" ]; then
        ok "all ${statements} policy statements printed in the plan"
    else
        bad "${statements} statements in the document, ${printed} printed in the plan"
        bs_report
    fi
    if grep -E '^ *1[.)] ' "$BS/out" >/dev/null && grep -E '^ *8[.)] ' "$BS/out" >/dev/null; then
        ok "the plan numbers the eight policy clauses"
    else
        bad "the plan does not number the eight policy clauses"
        bs_report
    fi
}

case_bootstrap_refuses_a_foreign_account() {
    CURRENT=case_bootstrap_refuses_a_foreign_account
    bs_new foreign
    bs_account "999999999999"
    bs_run --confirm
    if [ "$BS_RC" = "2" ]; then
        ok "exit 2 when the caller is not the pinned account"
    else
        bad "wanted exit 2 on a foreign account, got ${BS_RC}"
        bs_report
    fi
    local creates
    creates="$(bs_calls '(create|attach|add-role|authorize)-')"
    if [ "$creates" = "0" ]; then
        ok "zero create/attach calls recorded"
    else
        bad "${creates} create/attach call(s) recorded against a foreign account"
        bs_report
    fi
    if grep -F -- "999999999999" "$BS/out" >/dev/null; then
        ok "the refusal names the account it found"
    else
        bad "the refusal does not name the account it found"
    fi
}

case_bootstrap_first_run_creates_each_resource_exactly_once() {
    CURRENT=case_bootstrap_first_run_creates_each_resource_exactly_once
    bs_new first
    bs_run --confirm
    if [ "$BS_RC" != "0" ]; then
        bad "the first run exited ${BS_RC}"
        bs_report
        return
    fi
    local bad_any=0
    for pair in \
        "iam create-policy" \
        "iam create-user" \
        "iam attach-user-policy" \
        "iam create-role" \
        "iam create-instance-profile" \
        "iam add-role-to-instance-profile" \
        "iam attach-role-policy" \
        "ec2 create-security-group" \
        "ec2 create-tags" \
        "iam create-access-key"; do
        local n
        n="$(bs_calls "^${pair}")"
        if [ "$n" != "1" ]; then
            bad "'${pair}' was called ${n} time(s), wanted exactly 1"
            bad_any=1
        fi
    done
    [ "$bad_any" = "0" ] && ok "all ten creating calls made exactly once"
    [ "$bad_any" = "0" ] || bs_report
}

case_bootstrap_never_opens_an_ingress_rule() {
    CURRENT=case_bootstrap_never_opens_an_ingress_rule
    bs_new ingress
    bs_run --confirm
    local n
    n="$(bs_calls 'authorize-security-group')"
    if [ "$n" = "0" ]; then
        ok "no authorize-security-group-* call on the whole first run"
    else
        bad "${n} authorize-security-group call(s) — a verifier box has no ingress at all"
        bs_report
    fi
    local sg_line
    sg_line="$(grep -F -- "ec2 create-security-group" "$BS_REC/aws.argv" || true)"
    case "$sg_line" in
    *--vpc-id*) ok "the group is created in a named VPC" ;;
    *)
        bad "create-security-group names no --vpc-id: '${sg_line}'"
        bs_report
        ;;
    esac
}

case_bootstrap_attaches_only_the_ssm_managed_policy_to_the_box_role() {
    CURRENT=case_bootstrap_attaches_only_the_ssm_managed_policy_to_the_box_role
    bs_new ssmonly
    bs_run --confirm
    local attaches
    attaches="$(grep -F -- "iam attach-role-policy" "$BS_REC/aws.argv" || true)"
    if [ "$(printf '%s\n' "$attaches" | grep -c .)" != "1" ]; then
        bad "wanted exactly one attach-role-policy, got: ${attaches}"
        return
    fi
    if printf '%s' "$attaches" | grep -F -- "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore" >/dev/null; then
        ok "the box role's one managed policy is AmazonSSMManagedInstanceCore"
    else
        bad "the box role's attached policy is not AmazonSSMManagedInstanceCore: ${attaches}"
    fi
    # The role the environment boxes use reads a secrets prefix and writes a
    # backup bucket. A verifier box must never be handed it.
    if grep -E 'attach-role-policy.*(secretsmanager|backup)|iam-instance-profile.*(secretsmanager|backup)' "$BS_REC/aws.argv" >/dev/null; then
        bad "the bootstrap attaches a secrets or backup grant to the verifier box role"
    else
        ok "no secrets or backup grant anywhere on the box role"
    fi
}

case_bootstrap_second_run_creates_nothing_and_mints_no_second_key() {
    CURRENT=case_bootstrap_second_run_creates_nothing_and_mints_no_second_key
    bs_new second
    bs_mode exists
    bs_run --confirm
    if [ "$BS_RC" != "0" ]; then
        bad "the second run exited ${BS_RC} — finding everything already there is not an error"
        bs_report
        return
    fi
    local creates keys
    creates="$(bs_calls '^(iam|ec2) (create|attach|add-role)-')"
    keys="$(bs_calls 'create-access-key')"
    if [ "$creates" = "0" ]; then
        ok "zero creating calls on a second run"
    else
        bad "${creates} creating call(s) on a second run"
        bs_report
    fi
    if [ "$keys" = "0" ]; then
        ok "no second access key minted"
    else
        bad "${keys} create-access-key call(s) on a second run — keys must not accumulate"
        bs_report
    fi
    if grep -F -- "exists" "$BS/out" >/dev/null; then
        ok "the second run reports what it found"
    else
        bad "the second run does not report the resources as existing"
        bs_report
    fi
}

# IDEMPOTENT IS NOT THE SAME AS UP TO DATE, and the difference is what a live
# account found out the hard way. This script creates the policy when it is
# absent and says `exists` when it is not — so after the DOCUMENT in the tree
# changes, a re-run is a no-op that reads like a success, and the account goes
# on enforcing the version it was created with. A capture then fails on a grant
# the file plainly contains. The script must not silently publish a new version
# (an IAM policy version is the owner's act, and this script's whole shape is
# refuse-first), so what it owes is the SENTENCE: the live policy was not
# updated, here is the command that updates it, and here is the rendered
# document to give it.
case_bootstrap_says_an_existing_policy_is_not_updated_by_a_re_run() {
    CURRENT=case_bootstrap_says_an_existing_policy_is_not_updated_by_a_re_run
    bs_new policy_exists
    bs_mode exists
    bs_run --confirm
    if [ "$BS_RC" != "0" ]; then
        bad "the second run exited ${BS_RC}"
        bs_report
        return
    fi
    if grep -F -- "iam create-policy-version" "$BS/out" >/dev/null; then
        ok "it prints the command that publishes the document in the tree as the live version"
    else
        bad "an existing policy is reported as 'exists' and nothing tells the owner the account may be
      enforcing an older document, or how to publish this one"
        bs_report
    fi
    if grep -F -- "--set-as-default" "$BS/out" >/dev/null; then
        ok "and the command sets the new version as the default — a version nobody defaults to enforces nothing"
    else
        bad "the printed command does not carry --set-as-default"
        bs_report
    fi
    # THE RENDERED DOCUMENT HAS TO EXIST FOR THAT COMMAND TO BE RUNNABLE. The
    # tracked file carries ${ACCOUNT_ID}/${REGION}/${NAMESPACE} slots, so an
    # owner handed `file://deploy/iam/verifier-ops-policy.json` would publish a
    # policy with three literal slots in it.
    local path
    path="$(grep -oE 'file://[^ ]+' "$BS/out" | tail -n 1 || true)"
    path="${path#file://}"
    if [ -n "$path" ] && [ -r "$path" ] && grep -F -- '"Version"' "$path" >/dev/null 2>&1; then
        if grep -F -- '${ACCOUNT_ID}' "$path" >/dev/null 2>&1; then
            bad "the document it points at still carries the \${ACCOUNT_ID} slot — it is the tracked file, not a rendered one"
        else
            ok "the command points at a RENDERED document on disk (${path}), slots filled"
        fi
    else
        bad "the printed command names no readable rendered policy document (got '${path:-none}')"
        bs_report
    fi
    # AND IT DOES NOT RUN IT. Publishing a policy version is an act on a live
    # account, and this script is refuse-first by design.
    local versions
    versions="$(bs_calls 'create-policy-version')"
    if [ "$versions" = "0" ]; then
        ok "it printed the step and did not take it — the owner's hand, as everywhere else here"
    else
        bad "${versions} create-policy-version call(s): the script published a policy version itself"
        bs_report
    fi
}

# --- the interpreter the bootstrap runs a repository python file on -----------
#
# `deploy/policy_summary.py` is a file THIS REPOSITORY writes, and the plan the
# owner reads before typing `--confirm` is its output. Run under `python3` off
# PATH it runs under some other environment's Python; on a machine whose system
# one is a 3.9 — every Amazon Linux 2023 box — a file written at 3.12 fails in a
# way that reads as a finding about the file. The gate paid for exactly that
# class at the queue-index leg on the first off-box run, and `deploy/` was
# declared out of that census's population, which left this one behind.
case_the_bootstrap_summarises_the_policy_on_the_checkouts_own_interpreter() {
    CURRENT=case_the_bootstrap_summarises_the_policy_on_the_checkouts_own_interpreter
    bs_new interpreter
    # A RECORDING `python3` FIRST ON THE BOOTSTRAP'S PATH. `bs_run` hands the
    # script `PATH=$BS/bin:/usr/bin:/bin`, so this one is what a bare `python3`
    # would find — and the claim is that the summary does not find it.
    cat >"$BS/bin/python3" <<'PYSHIM'
#!/bin/sh
printf '%s\n' "$*" >> "$REC/python3.argv"
exec /usr/bin/python3 "$@"
PYSHIM
    chmod +x "$BS/bin/python3"
    bs_run
    # No --confirm: the plan prints, nothing is created, exit 2. That is the
    # path the summary runs on, and it is the one an owner reads.
    if [ "$BS_RC" != "2" ]; then
        bad "the bare run exited ${BS_RC}, not the refusal that prints the plan"
        bs_report
        return
    fi
    # THE SUMMARY RAN: its output is in the plan, so this is not a green over a
    # step that silently did nothing.
    if grep -F -- "verifier-ops-policy.json" "$BS/out" >/dev/null &&
        grep -qE 'Allow|Deny' "$BS/out"; then
        ok "the plan carries the policy summary, so the reader ran"
    else
        bad "the plan has no policy summary in it — the assertion below would be about nothing"
        bs_report
    fi
    # AND NOT THROUGH THE `python3` ON PATH.
    local via_path
    via_path="$(grep -cF -- "policy_summary.py" "$BS_REC/python3.argv" 2>/dev/null || true)"
    if [ "${via_path:-0}" = "0" ]; then
        ok "policy_summary.py was never handed to the python3 on PATH"
    else
        bad "${via_path} invocation(s) of policy_summary.py went through the PATH python3: $(cat "$BS_REC/python3.argv")"
    fi
    # The interpreter it DID use, asserted as text at the call site, because the
    # shim above can only prove a negative.
    if grep -qF -- '"$CHECKOUT_PYTHON" "$SUMMARY"' "$ROOT/$BOOTSTRAP"; then
        ok "the call site names the checkout's own interpreter"
    else
        bad "the bootstrap no longer runs the summary through CHECKOUT_PYTHON"
    fi
}

case_the_bootstrap_refuses_a_checkout_with_no_interpreter() {
    CURRENT=case_the_bootstrap_refuses_a_checkout_with_no_interpreter
    bs_new no_venv
    # ITS OWN VICTIM, BUILT: a copy of the script and the three files it reads,
    # in a tree that has no `.venv` — which is what an unprovisioned clone is.
    # Never the real checkout, and never by moving anything aside.
    local fake="$BS/fake-checkout"
    mkdir -p "$fake/deploy/iam"
    cp "$ROOT/$BOOTSTRAP" "$fake/deploy/iam/"
    cp "$ROOT/deploy/iam/verifier-ops-policy.json" "$fake/deploy/iam/"
    cp "$ROOT/deploy/iam/verifier-box-trust.json" "$fake/deploy/iam/"
    cp "$ROOT/deploy/policy_summary.py" "$fake/deploy/"
    [ -e "$fake/.venv" ] && bad "the victim tree has a venv — it cannot drive the refusal" && return
    BS_RC=0
    env -i \
        PATH="$BS/bin:/usr/bin:/bin" \
        HOME="$BS" \
        REC="$BS_REC" \
        DJB_DEPLOY_NAMESPACE="$BS_NS" \
        DJB_VERIFIER_ACCOUNT="$BS_ACCOUNT" \
        DJB_VERIFIER_REGION="$BS_REGION" \
        bash "$fake/deploy/iam/verifier_bootstrap.sh" --confirm >"$BS/out" 2>&1 || BS_RC=$?
    if [ "$BS_RC" = "2" ]; then
        ok "an unprovisioned checkout is exit 2 — could-not-look, not a run under a foreign python"
    else
        bad "wanted exit 2 in a checkout with no venv, got ${BS_RC}"
        bs_report
    fi
    if grep -F -- ".venv/bin/python" "$BS/out" >/dev/null &&
        grep -F -- "setup.sh" "$BS/out" >/dev/null; then
        ok "and the refusal names what is missing and the one command that makes it"
    else
        bad "the refusal does not name the interpreter or the remedy: $(tr '\n' ' ' <"$BS/out" | cut -c1-300)"
    fi
    # NOTHING WAS CREATED, which is this script's whole shape: the refusal is
    # before the first AWS call, not after it.
    local creates
    creates="$(bs_calls 'create-')"
    if [ "$creates" = "0" ]; then
        ok "and nothing was created before it refused"
    else
        bad "${creates} create-* call(s) happened before the interpreter was checked"
    fi
}

# --- the two account prerequisites this script CHECKS and never creates ------
#
# Both were done by hand, under the admin profile, on the night the first
# verifier box ran a gate — and neither was anywhere in the tree afterwards,
# which is the whole class this pair of cases closes.

# The tracked document with the three slots filled, exactly as the script fills
# them. A COPY, deliberately: a fixture that asked the script to render its own
# expected value would agree with any rendering, including a broken one.
bs_rendered_policy() {
    sed -e "s|\${ACCOUNT_ID}|${BS_ACCOUNT}|g" \
        -e "s|\${REGION}|${BS_REGION}|g" \
        -e "s|\${NAMESPACE}|${BS_NS}|g" \
        "$ROOT/deploy/iam/verifier-ops-policy.json"
}

# --- the box role's registry grant (ADR deploy-4a) ---------------------------
#
# WHY THIS PAIR EXISTS. The bank builds the deployed image on a verifier box
# and pushes it under the banked tree's tag, which needs a registry token the
# BOX mints under its own role. The first such image was pushed with a token
# piped over from a laptop, because the role had no grant and nothing in the
# tree said it needed one — so the grant lived in one person's shell history
# and in no file. These two cases pin the two halves that keep it honest: the
# bootstrap RENDERS the document and PRINTS the one command, and it ATTACHES
# NOTHING — a box that may write to the registry production pulls from is the
# owner's act, exactly as a new policy version is.

# The document the bootstrap must render, as a COPY: a fixture that asked the
# script for its own expected value would agree with any rendering, including a
# broken one. Every coordinate is derived here the same way it is derived there
# — from the namespace, the region and the caller's account.
bs_rendered_ecr_policy() {
    cat <<JSON
{"Version": "2012-10-17", "Statement": [
  {"Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*"},
  {"Effect": "Allow",
   "Action": ["ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage",
              "ecr:GetDownloadUrlForLayer", "ecr:InitiateLayerUpload",
              "ecr:UploadLayerPart", "ecr:CompleteLayerUpload",
              "ecr:PutImage", "ecr:DescribeImages", "ecr:ListImages"],
   "Resource": ["arn:aws:ecr:${BS_REGION}:${BS_ACCOUNT}:repository/${BS_NS}/djb-web",
                "arn:aws:ecr:${BS_REGION}:${BS_ACCOUNT}:repository/${BS_NS}/djb-worker"]}]}
JSON
}

case_bootstrap_prints_the_box_roles_registry_grant_and_attaches_nothing() {
    CURRENT=case_bootstrap_prints_the_box_roles_registry_grant_and_attaches_nothing
    bs_new ecr_grant_absent
    bs_mode exists
    bs_rendered_policy >"$BS_REC/policy.live"
    printf 'v2\n' >"$BS_REC/policy.version"
    bs_run --confirm
    if [ "$BS_RC" != "0" ]; then
        bad "the run exited ${BS_RC}"
        bs_report
        return
    fi
    # THE COMMAND A HUMAN RUNS, with the role and the inline policy's name.
    if grep -F -- "iam put-role-policy" "$BS/out" >/dev/null &&
        grep -F -- "--policy-name ${BS_NS}-verifier-box-ecr" "$BS/out" >/dev/null &&
        grep -F -- "--role-name ${BS_NS}-verifier-box" "$BS/out" >/dev/null; then
        ok "an absent registry grant prints the put-role-policy a human runs"
    else
        bad "the absent grant printed no put-role-policy for the box role"
        bs_report
    fi
    # AND IT ATTACHED NOTHING. This is the whole claim: the widest grant in the
    # file is never made by a script somebody ran to read a plan.
    if [ "$(bs_calls 'iam put-role-policy')" = "0" ]; then
        ok "and it attached nothing itself"
    else
        bad "$(bs_calls 'iam put-role-policy') put-role-policy call(s) were MADE by the bootstrap"
        bs_report
    fi
    # THE DOCUMENT IT RENDERED IS THE DOCUMENT THIS DRIVE COMPOSED — every
    # coordinate derived from the namespace, the region and the caller's
    # account, and nothing typed.
    local rendered want
    # `|| true`, because this drive runs under `pipefail` and a reader that
    # found nothing would kill it: a FAILED assertion about a missing line must
    # not arrive as a could-not-look about the reader.
    rendered="$(grep -F -- "--policy-document file://" "$BS/out" 2>/dev/null |
        sed 's|.*file://||' | tr -d ' ' || true)"
    if [ -z "$rendered" ] || [ ! -f "$rendered" ]; then
        bad "the printed command names no readable rendered document (${rendered:-<none>})"
        bs_report
        return
    fi
    want="$BS/want-ecr.json"
    bs_rendered_ecr_policy >"$want"
    if python3 -c '
import json, sys
a = json.load(open(sys.argv[1]))
b = json.load(open(sys.argv[2]))
sys.exit(0 if a == b else 1)
' "$rendered" "$want"; then
        ok "the rendered grant IS this drive's own composition of it"
    else
        bad "the rendered grant differs from the derived document:"
        sed 's/^/             | /' "$rendered"
    fi
    # LEAST PRIVILEGE, ASSERTED AS AN ABSENCE TOO: a bank may add an image and
    # may never remove one, and no repository outside this namespace is named.
    if grep -qE 'Delete|\*:\*|"ecr:\*"' "$rendered"; then
        bad "the grant carries a delete or a wildcard action: $(tr -d '\n' <"$rendered")"
    else
        ok "no delete and no wildcard action in it"
    fi
}

case_bootstrap_prints_no_registry_grant_when_the_role_already_carries_it() {
    CURRENT=case_bootstrap_prints_no_registry_grant_when_the_role_already_carries_it
    bs_new ecr_grant_current
    bs_mode exists
    bs_rendered_policy >"$BS_REC/policy.live"
    printf 'v2\n' >"$BS_REC/policy.version"
    bs_rendered_ecr_policy >"$BS_REC/rolepolicy.live"
    bs_run --confirm
    if [ "$BS_RC" != "0" ]; then
        bad "the run exited ${BS_RC}"
        bs_report
        return
    fi
    if grep -F -- "iam put-role-policy" "$BS/out" >/dev/null; then
        bad "it printed the attach command over a grant the role already carries — an instruction printed on every run is one nobody reads by the third"
        bs_report
    else
        ok "a role that already carries the grant is told nothing to do"
    fi
    if grep -F -- "registry grant ${BS_NS}-verifier-box-ecr" "$BS/out" >/dev/null &&
        grep -F -- "up to date" "$BS/out" >/dev/null; then
        ok "and it says so, naming the grant it compared"
    else
        bad "it does not say the live grant is current"
        bs_report
    fi
    # AND IT COMPARED RATHER THAN GUESSED.
    if [ "$(bs_calls 'iam get-role-policy')" -ge 1 ]; then
        ok "it read the live grant before deciding"
    else
        bad "no iam get-role-policy call was made — the verdict was a guess"
    fi
}

case_bootstrap_prints_no_policy_version_when_the_live_one_already_agrees() {
    CURRENT=case_bootstrap_prints_no_policy_version_when_the_live_one_already_agrees
    bs_new policy_current
    bs_mode exists
    printf 'v2\n' >"$BS_REC/policy.version"
    bs_rendered_policy >"$BS_REC/policy.live"
    bs_run --confirm
    if [ "$BS_RC" != "0" ]; then
        bad "the run exited ${BS_RC}"
        bs_report
        return
    fi
    if grep -F -- "iam create-policy-version" "$BS/out" >/dev/null; then
        bad "it printed the publish command over a live version that IS this tree's document — an instruction printed on every run is one nobody reads by the third"
        bs_report
    else
        ok "an up-to-date policy prints no publish command at all"
    fi
    if grep -F -- "up to date" "$BS/out" >/dev/null && grep -F -- "v2" "$BS/out" >/dev/null; then
        ok "it says so, and names the live version it compared against"
    else
        bad "it does not say the live version is current, or does not name it"
        bs_report
    fi
    # AND IT COMPARED RATHER THAN GUESSED: both reads are in the log.
    if [ "$(bs_calls 'iam get-policy-version')" -ge 1 ]; then
        ok "the live default version's document was actually fetched"
    else
        bad "no iam get-policy-version call — nothing was compared"
        bs_report
    fi
}

case_bootstrap_prints_the_policy_version_when_the_live_one_differs() {
    CURRENT=case_bootstrap_prints_the_policy_version_when_the_live_one_differs
    bs_new policy_stale
    bs_mode exists
    printf 'v1\n' >"$BS_REC/policy.version"
    # A LIVE DOCUMENT THAT IS ONE STATEMENT SHORT — the shape of the real
    # account's drift: the file granted a tagging action on an image and a
    # snapshot, the attached version did not, and a capture was refused on a
    # grant the tracked file plainly contained.
    bs_rendered_policy | "$DRIVE_PY" -c '
import json, sys

doc = json.load(sys.stdin)
doc["Statement"] = doc["Statement"][:-1]
json.dump(doc, sys.stdout)
' >"$BS_REC/policy.live"
    bs_run --confirm
    if [ "$BS_RC" != "0" ]; then
        bad "the run exited ${BS_RC}"
        bs_report
        return
    fi
    if grep -F -- "iam create-policy-version" "$BS/out" >/dev/null &&
        grep -F -- "--set-as-default" "$BS/out" >/dev/null; then
        ok "a drifted live version gets the publish command, --set-as-default included"
    else
        bad "the account is enforcing a document this tree does not carry and nothing said so"
        bs_report
    fi
    if grep -F -- "OUT OF DATE" "$BS/out" >/dev/null && grep -F -- "v1" "$BS/out" >/dev/null; then
        ok "it says which live version it compared against and that it lost"
    else
        bad "it does not name the stale live version"
        bs_report
    fi
    if [ "$(bs_calls 'create-policy-version')" = "0" ]; then
        ok "and it printed the step without taking it"
    else
        bad "the script published a policy version itself"
        bs_report
    fi
}

case_bootstrap_names_the_spot_service_linked_role_when_the_account_lacks_it() {
    CURRENT=case_bootstrap_names_the_spot_service_linked_role_when_the_account_lacks_it
    bs_new spot_slr_absent
    bs_mode exists
    printf 'absent\n' >"$BS_REC/spot-slr"
    bs_rendered_policy >"$BS_REC/policy.live"
    bs_run --confirm
    if [ "$BS_RC" != "0" ]; then
        bad "the run exited ${BS_RC}"
        bs_report
        return
    fi
    if grep -F -- "create-service-linked-role --aws-service-name spot.amazonaws.com" "$BS/out" >/dev/null; then
        ok "it prints the one command that creates EC2's Spot role"
    else
        bad "an account with no Spot service-linked role gets no mention of it — the first Spot launch fails AuthFailure.ServiceLinkedRoleCreationNotPermitted and nothing here says why"
        bs_report
    fi
    if grep -F -- "ServiceLinkedRoleCreationNotPermitted" "$BS/out" >/dev/null; then
        ok "and names the error the first Spot launch would otherwise arrive as"
    else
        bad "it does not name the failure code the operator will actually see"
        bs_report
    fi
    # UNDER THE ADMIN PROFILE, because the ops user may not: the command is
    # useless to anyone who copies it with the wrong credential.
    if grep -E -- "--profile default .*|--profile default" "$BS/out" >/dev/null; then
        ok "printed under the admin profile this run used"
    else
        bad "the printed command names no admin profile"
        bs_report
    fi
    if [ "$(bs_calls 'create-service-linked-role')" = "0" ]; then
        ok "and it did not create the role itself — an account-wide role is the owner's act"
    else
        bad "the script created an account-wide service-linked role"
        bs_report
    fi
}

case_bootstrap_says_nothing_to_do_when_the_spot_role_exists() {
    CURRENT=case_bootstrap_says_nothing_to_do_when_the_spot_role_exists
    bs_new spot_slr_present
    bs_mode exists
    printf 'exists\n' >"$BS_REC/spot-slr"
    bs_rendered_policy >"$BS_REC/policy.live"
    bs_run --confirm
    if [ "$BS_RC" != "0" ]; then
        bad "the run exited ${BS_RC}"
        bs_report
        return
    fi
    if grep -F -- "create-service-linked-role" "$BS/out" >/dev/null; then
        bad "it printed the create command for a role that already exists"
        bs_report
    else
        ok "an account that already has the role is told so and given no command"
    fi
    if grep -F -- "AWSServiceRoleForEC2Spot exists" "$BS/out" >/dev/null; then
        ok "and the check is visible rather than silent — a prerequisite nobody sees checked is one nobody trusts"
    else
        bad "the run says nothing about the Spot role at all"
        bs_report
    fi
}

case_bootstrap_prints_the_secret_on_the_last_line_and_nowhere_else() {
    CURRENT=case_bootstrap_prints_the_secret_on_the_last_line_and_nowhere_else
    bs_new secret
    bs_run --confirm
    local marker
    # Assembled, never spelled: a literal key-shaped string in this file is one
    # the raw house-rule scanner reads as a secret, and that scanner has no
    # pragma path. `archaeology_patterns`' idiom, for the same reason.
    marker="driveOnly""NotARealSecret0000000000000000"
    local hits last
    hits="$(grep -cF -- "$marker" "$BS/out" || true)"
    last="$(tail -n 1 "$BS/out")"
    if [ "$hits" = "1" ]; then
        ok "the secret appears exactly once in the output"
    else
        bad "the secret appears ${hits} time(s) in the output"
    fi
    case "$last" in
    *"$marker"*) ok "and it is on the last line" ;;
    *)
        bad "the last line is not the one carrying the secret: '${last}'"
        bs_report
        ;;
    esac
    if grep -F -- "$marker" "$BS_REC/aws.argv" >/dev/null 2>&1; then
        bad "the secret was passed as an argument to an aws call — it would land in ps and in a shell history"
        bs_report
    else
        ok "the secret is in no recorded argv"
    fi
}

case_bootstrap_refuses_a_piped_stdout() {
    CURRENT=case_bootstrap_refuses_a_piped_stdout
    bs_new piped
    local rc=0
    # `|| true` here would REPLACE PIPESTATUS with `true`'s and the case would
    # read 0 for every outcome — the exact class the guard under test exists
    # for, one level up. `set +e` around the pipeline instead.
    set +e
    env -i PATH="$BS/bin:/usr/bin:/bin" HOME="$BS" REC="$BS_REC" \
        DJB_DEPLOY_NAMESPACE="$BS_NS" \
        bash "$ROOT/$BOOTSTRAP" --confirm 2>&1 | cat >"$BS/out"
    rc="${PIPESTATUS[0]}"
    set -e
    if [ "$rc" = "2" ]; then
        ok "a piped stdout is exit 2 — the exit status is the verdict and a filter replaces it"
    else
        bad "wanted exit 2 on a piped stdout, got ${rc}"
        bs_report
    fi
    local creates
    creates="$(bs_calls '(create|attach|add-role)-')"
    if [ "$creates" = "0" ]; then
        ok "nothing was created on the piped run"
    else
        bad "${creates} creating call(s) on the piped run"
    fi
}

# =============================================================================
# GROUP 5 — the bake recipe
# =============================================================================

# THE PACKAGE THAT DOES NOT EXIST. Amazon Linux 2023 ships `docker` and no
# compose package at all — compose v2 is a CLI-plugin BINARY — so a `dnf
# install docker-compose-plugin` is `Error: Unable to find a match` and step 1
# dies with the whole recipe behind it. It was found by hand, on a box, at the
# cost of a bake; the class is wider than the one name, so this asserts the
# name is gone AND that the list is one a reader can check against the
# distribution's own repositories.
case_the_recipe_installs_no_package_amazon_linux_does_not_have() {
    CURRENT=case_the_recipe_installs_no_package_amazon_linux_does_not_have
    local dnf_line
    dnf_line="$(grep -nE '^sudo dnf install' "$BAKE" || true)"
    if [ -z "$dnf_line" ]; then
        bad "the recipe has no 'sudo dnf install' line at all"
        return
    fi
    case "$dnf_line" in
    *docker-compose-plugin*)
        bad "step 1 still installs 'docker-compose-plugin', which AL2023 does not have: ${dnf_line}"
        ;;
    *) ok "no 'docker-compose-plugin' in the dnf line — AL2023 has no such package" ;;
    esac
    # The plan is the runbook and it must not promise the package either.
    local out="$WORK/bake-plan-compose.txt" rc=0
    local pen="$WORK/bake-pen-compose"
    rm -rf "$pen"
    mkdir -p "$pen/bin" "$pen/rec"
    env -i PATH="$pen/bin:/usr/bin:/bin" HOME="$pen" REC="$pen/rec" \
        bash "$ROOT/$BAKE" --plan >"$out" 2>&1 || rc=$?
    if [ "$rc" != "0" ]; then
        bad "--plan exited ${rc}"
        return
    fi
    if grep -F -- "docker-compose-plugin" "$out" >/dev/null 2>&1; then
        bad "the plan still names the docker-compose-plugin package"
    else
        ok "the plan does not promise a package the distribution lacks"
    fi
}

# THE PIN AND THE CHECKSUM, IN THAT ORDER. `BAKE_UV_VERSION` is the precedent:
# a `curl | sh` that resolves "latest" is a different toolchain on every bake,
# and an image whose compose version nobody wrote down is an image whose
# behaviour nobody can reproduce. The checksum is the half the precedent does
# NOT have and this one needs: uv arrives through a publisher's installer over
# TLS, where compose arrives as a bare binary this recipe then marks
# executable — so the verification must happen BEFORE the bit that makes it
# runnable, and the order is asserted by line number rather than by reading.
case_the_compose_plugin_is_pinned_and_checksummed_before_it_is_installed() {
    CURRENT=case_the_compose_plugin_is_pinned_and_checksummed_before_it_is_installed
    local ver_n sha_n uv_n
    ver_n="$(grep -nE '^BAKE_COMPOSE_VERSION=' "$BAKE" | head -n 1 | cut -d: -f1 || true)"
    sha_n="$(grep -nE '^BAKE_COMPOSE_SHA256=' "$BAKE" | head -n 1 | cut -d: -f1 || true)"
    uv_n="$(grep -nE '^BAKE_UV_VERSION=' "$BAKE" | head -n 1 | cut -d: -f1 || true)"
    if [ -z "$ver_n" ] || [ -z "$sha_n" ]; then
        bad "no BAKE_COMPOSE_VERSION / BAKE_COMPOSE_SHA256 knob in the recipe (version ${ver_n:-absent}, sha ${sha_n:-absent})"
        return
    fi
    ok "the compose version and its sha256 are knobs at :${ver_n} and :${sha_n}"
    if [ -n "$uv_n" ] && [ "$ver_n" -gt "$uv_n" ] && [ "$((ver_n - uv_n))" -lt 40 ]; then
        ok "they sit beside BAKE_UV_VERSION (:${uv_n}) — the pin precedent, in one block"
    else
        bad "BAKE_COMPOSE_VERSION is at :${ver_n} and BAKE_UV_VERSION at :${uv_n:-absent} — the two pins must read together"
    fi

    # The version is SUBSTITUTED into the URL, never spelled twice: a literal
    # version in the URL beside a knob that claims to set it is a pin that
    # silently stops pinning.
    local url_line
    url_line="$(grep -nE 'docker-compose-linux-aarch64' "$BAKE" | head -n 1 || true)"
    if [ -z "$url_line" ]; then
        bad "the recipe never names the aarch64 compose asset — these boxes are arm64 (c7g)"
        return
    fi
    case "$url_line" in
    *'${BAKE_COMPOSE_VERSION}'*) ok "the download URL is built from the version knob, not a second literal" ;;
    *) bad "the compose URL does not interpolate BAKE_COMPOSE_VERSION: ${url_line}" ;;
    esac

    # THE ORDER. Verify, then install. A `chmod +x` (or an `install -m 0755`)
    # that runs before the comparison has already put an unverified binary
    # where docker will find it.
    local verify_n exec_n dir_n
    verify_n="$(grep -nE 'BAKE_COMPOSE_SHA256|shasum|sha256sum' "$BAKE" | grep -vE '^[0-9]+:#' | grep -vE '^[0-9]+:BAKE_COMPOSE_SHA256=' | head -n 1 | cut -d: -f1 || true)"
    exec_n="$(grep -nE 'install -m 0755 .*BAKE_COMPOSE_PLUGIN|chmod \+x .*BAKE_COMPOSE_PLUGIN' "$BAKE" | grep -vE '^[0-9]+:#' | tail -n 1 | cut -d: -f1 || true)"
    dir_n="$(grep -nE '/usr/local/lib/docker/cli-plugins' "$BAKE" | head -n 1 | cut -d: -f1 || true)"
    if [ -z "$dir_n" ]; then
        bad "the plugin does not land in /usr/local/lib/docker/cli-plugins — docker will not find it"
    else
        ok "the plugin lands in /usr/local/lib/docker/cli-plugins (:${dir_n})"
    fi
    if [ -z "$verify_n" ] || [ -z "$exec_n" ]; then
        bad "no checksum step (${verify_n:-absent}) or no install step (${exec_n:-absent}) in the recipe"
    elif [ "$verify_n" -lt "$exec_n" ]; then
        ok "the sha256 is verified at :${verify_n}, before the binary is made runnable at :${exec_n}"
    else
        bad "the checksum is at :${verify_n} and the install at :${exec_n} — an unverified binary is already in place"
    fi

    # And the plan says so, because the plan is what an operator reads before
    # spending money.
    local out="$WORK/bake-plan-pin.txt" rc=0
    local pen="$WORK/bake-pen-pin"
    rm -rf "$pen"
    mkdir -p "$pen/bin" "$pen/rec"
    env -i PATH="$pen/bin:/usr/bin:/bin" HOME="$pen" REC="$pen/rec" \
        bash "$ROOT/$BAKE" --plan >"$out" 2>&1 || rc=$?
    if [ "$rc" != "0" ]; then
        bad "--plan exited ${rc}"
        return
    fi
    if grep -F -- "cli-plugins" "$out" >/dev/null 2>&1 && grep -F -- "sha256" "$out" >/dev/null 2>&1; then
        ok "the plan names the plugin path and its checksum"
    else
        bad "the plan does not name the cli-plugins path and the sha256 step"
        sed 's/^/      /' "$out"
    fi
}

case_bake_plan_runs_nothing_and_names_its_steps_in_order() {
    CURRENT=case_bake_plan_runs_nothing_and_names_its_steps_in_order
    local out="$WORK/bake-plan.txt" rc=0
    local pen="$WORK/bake-pen"
    rm -rf "$pen"
    mkdir -p "$pen/bin"
    # Every tool the recipe would use, planted as a recorder. A --plan that
    # invoked one would be caught by the file it left behind.
    for tool in dnf yum docker git uv systemctl useradd install cloud-init; do
        cat >"$pen/bin/$tool" <<SHIM
#!/usr/bin/env bash
printf '%s\n' "$tool \$*" >>"\$REC/ran"
exit 0
SHIM
        chmod +x "$pen/bin/$tool"
    done
    mkdir -p "$pen/rec"
    env -i PATH="$pen/bin:/usr/bin:/bin" HOME="$pen" REC="$pen/rec" \
        bash "$ROOT/$BAKE" --plan >"$out" 2>&1 || rc=$?
    if [ "$rc" != "0" ]; then
        bad "--plan exited ${rc}"
        sed 's/^/    /' "$out"
        return
    fi
    if [ -s "$pen/rec/ran" ]; then
        bad "--plan ran something: $(tr '\n' '; ' <"$pen/rec/ran")"
    else
        ok "--plan ran none of the nine tools the recipe uses"
    fi
    # The order is the runbook of the image: a reader must be able to follow it
    # without running it.
    local order
    order="$(grep -nE 'uv sync --frozen|\./scripts/setup\.sh|docker compose pull|DJB_GATE_SLOTS=2|verifier-parking|cloud-init clean' "$out" |
        sed -E 's/^([0-9]+):.*(uv sync --frozen|\.\/scripts\/setup\.sh|docker compose pull|DJB_GATE_SLOTS=2|verifier-parking|cloud-init clean).*/\2/' |
        awk '!seen[$0]++' | tr '\n' '|')"
    local want="verifier-parking|uv sync --frozen|./scripts/setup.sh|docker compose pull|DJB_GATE_SLOTS=2|cloud-init clean|"
    if [ "$order" = "$want" ]; then
        ok "the plan names its six load-bearing steps in order"
    else
        bad "the plan's step order is '${order}', wanted '${want}'"
        sed 's/^/    /' "$out"
    fi
}

# THE PARK COMES FIRST, AND THERE IS THEN NOTHING TO PIN.
#
# MEASURED TWICE ON REAL BOXES, 2026-09-18. The recipe used to run
# `./scripts/setup.sh` while the checkout still stood on `main`, so the database
# it made was named from `main` (`scripts/db.sh` derives one name per branch per
# checkout); the park then moved the checkout onto the branch that exists only
# so `main` can be pushed onto it, and from that moment every derivation on
# every box launched from that image named a DIFFERENT database. The first
# remedy was a marker line in the checkout's `.env` declaring the baked name
# deliberate, and the first bank on boxes measured what that bought: three
# selftest shards exit 2 at ~540 s and no row composed. A drive that DERIVES the
# name could not look — "this checkout's database djb_verifier_parking_<hash>
# does not exist; run ./scripts/setup.sh first" — and the db-pin drive went RED,
# because the marker silences the very leg that drive plants against.
#
# SO THE ORDER IS THE FIX, AND THE MARKER GOES: park, THEN set up. The name the
# recipe's own `setup.sh` derives is then the name every later run on every box
# derives, the `.env` needs no marker, and the leg that judges a stale pin is
# left free to judge one.
#
# TWO CASES, AND NEITHER IS HONEST ALONE. An absent pin on a recipe that also
# lost its park is the original defect with the remedy deleted and nothing
# saying so, so the absence case re-asserts the order it depends on.
case_the_bake_parks_before_it_sets_up() {
    CURRENT=case_the_bake_parks_before_it_sets_up

    # THE BODY, because the plan is a promise and the body is what runs.
    local b_check b_park b_setup
    b_check="$(grep -nE '^\[ -d "\$BAKE_CHECKOUT/\.git" \]' "$BAKE" | head -n 1 | cut -d: -f1 || true)"
    b_park="$(grep -nE '^\(cd "\$BAKE_CHECKOUT".*checkout -B' "$BAKE" | head -n 1 | cut -d: -f1 || true)"
    b_setup="$(grep -nE '^\(cd "\$BAKE_CHECKOUT".*scripts/setup\.sh' "$BAKE" | head -n 1 | cut -d: -f1 || true)"
    if [ -z "$b_park" ] || [ -z "$b_setup" ]; then
        bad "the recipe has no park (${b_park:-absent}) or no setup.sh step (${b_setup:-absent}) — one of the two steps this case is about is not there"
    elif [ "$b_park" -lt "$b_setup" ]; then
        ok "the body parks at :${b_park} and only then runs ./scripts/setup.sh at :${b_setup} — the name setup derives is the name the image carries"
    else
        bad "the body parks at :${b_park}, AFTER ./scripts/setup.sh at :${b_setup}: the database is made under one branch and every box from the image derives another name"
    fi

    # AND IT PARKS ON A CHECKOUT SOMETHING ALREADY CHECKED. `git checkout -B` in
    # a directory the wrapper never pushed into is a failure nobody worded.
    if [ -n "$b_check" ] && [ -n "$b_park" ] && [ "$b_check" -lt "$b_park" ]; then
        ok "and the checkout guard at :${b_check} still stands in front of the park"
    else
        bad "the checkout guard is at '${b_check:-absent}' and the park at '${b_park:-absent}' — the park must stand on a guarded checkout"
    fi

    # THE PLAN, which is the image's runbook: an operator who reads it and never
    # runs it must see the order the body runs.
    local out="$WORK/bake-plan-park.txt" rc=0
    local pen="$WORK/bake-pen-park"
    rm -rf "$pen"
    mkdir -p "$pen"
    env -i PATH="/usr/bin:/bin" HOME="$pen" bash "$ROOT/$BAKE" --plan >"$out" 2>&1 || rc=$?
    if [ "$rc" != "0" ]; then
        bad "--plan exited ${rc}"
        return
    fi
    local p_park p_setup
    p_park="$(grep -n "verifier-parking" "$out" | head -n 1 | cut -d: -f1 || true)"
    p_setup="$(grep -nF -- "./scripts/setup.sh" "$out" | head -n 1 | cut -d: -f1 || true)"
    if [ -n "$p_park" ] && [ -n "$p_setup" ] && [ "$p_park" -lt "$p_setup" ]; then
        ok "the plan names the park (line ${p_park}) before the stack step (line ${p_setup})"
    else
        bad "the plan names the park at '${p_park:-absent}' and ./scripts/setup.sh at '${p_setup:-absent}' — the runbook and the body must read the same way"
        sed 's/^/      /' "$out"
    fi

    # AND IT SAYS WHY, because the next operator to tidy the step list needs the
    # reason and not only the order. An order with no argument beside it is an
    # order somebody moves back.
    if grep -F -- "DATABASE_NAME" "$out" >/dev/null && grep -F -- "derive" "$out" >/dev/null; then
        ok "and the plan says why the order is load-bearing (the DATABASE_NAME the stack step derives)"
    else
        bad "the plan gives no reason for the park preceding the stack step"
        sed 's/^/      /' "$out"
    fi
}

case_the_bake_writes_no_database_pin() {
    CURRENT=case_the_bake_writes_no_database_pin
    local n

    # (a) NO PIN, DEFINED OR CALLED. The recipe's remedy is the order above; a
    # second remedy beside it is the one that silences the leg.
    n="$(grep -c 'pin_database_name' "$BAKE" || true)"
    if [ "$n" = "0" ]; then
        ok "the recipe neither defines nor calls a database-name pin"
    else
        bad "the recipe still carries ${n} mention(s) of pin_database_name"
    fi

    # (b) AND NO SENTINELLED BLOCK LEFT BEHIND for a drive to extract — the
    # brackets leave with the thing they bracketed.
    if grep -F -- ">>> the database pin >>>" "$BAKE" >/dev/null 2>&1; then
        bad "the recipe still brackets a database-pin block a drive would extract and run"
    else
        ok "the sentinelled pin block is gone with the code it bracketed"
    fi

    # (c) AND THE MARKER TEXT IS NOWHERE IN THE FILE. It is `scripts/db.sh`'s
    # grammar, and the db-pin leg counts it wherever it lands in an .env: a
    # recipe still carrying the string in a comment is one edit away from
    # writing it into one, and a silenced leg is what the bank paid for.
    n="$(grep -c '# pinned' "$BAKE" || true)"
    if [ "$n" = "0" ]; then
        ok "the recipe spells no marker line for a box's .env to inherit"
    else
        bad "the recipe still spells the .env marker ${n} time(s)"
    fi

    # (d) AND THE PLAN PROMISES NONE OF IT. A runbook that describes a step the
    # body no longer runs is the drift this whole file exists to catch.
    local out="$WORK/bake-plan-nopin.txt" rc=0
    local pen="$WORK/bake-pen-nopin"
    rm -rf "$pen"
    mkdir -p "$pen"
    env -i PATH="/usr/bin:/bin" HOME="$pen" bash "$ROOT/$BAKE" --plan >"$out" 2>&1 || rc=$?
    if [ "$rc" != "0" ]; then
        bad "--plan exited ${rc}"
        return
    fi
    if grep -F -- "pin_database_name" "$out" >/dev/null 2>&1 || grep -F -- "# pinned" "$out" >/dev/null 2>&1; then
        bad "the plan still describes pinning the .env: $(grep -nF -- 'pinned' "$out" | head -n 2 | tr '\n' ' ')"
    else
        ok "the plan describes no pin either"
    fi

    # (e) AND THE REASON THERE IS NOTHING TO PIN IS STILL STANDING. Absence on
    # its own is green on a recipe that lost the park as well — which is the
    # original defect with its remedy deleted.
    local b_park b_setup
    b_park="$(grep -nE '^\(cd "\$BAKE_CHECKOUT".*checkout -B' "$BAKE" | head -n 1 | cut -d: -f1 || true)"
    b_setup="$(grep -nE '^\(cd "\$BAKE_CHECKOUT".*scripts/setup\.sh' "$BAKE" | head -n 1 | cut -d: -f1 || true)"
    if [ -n "$b_park" ] && [ -n "$b_setup" ] && [ "$b_park" -lt "$b_setup" ]; then
        ok "and the park still precedes the stack step (:${b_park} before :${b_setup}), which is what makes the absence right rather than a regression"
    else
        bad "the pin is gone and the park is at '${b_park:-absent}' against a stack step at '${b_setup:-absent}' — the absence is a regression, not a fix"
    fi
}

# THE IMAGE CARRIES THE FRONTEND TOOLCHAIN, OR EVERY BOX LOOP IS EXIT 2.
#
# MEASURED 2026-09-18, on a verifier box running an ordinary loop: the always-on
# leg's `fe_leg` member answered "no pnpm on PATH — cases 6-9 drive the real
# frozen-lockfile refusal · Nothing was asserted", which is COULD NOT LOOK, and
# 2 outranks everything else in the composition. So an image with no pnpm on it
# is an image on which no box loop and no on-box bank can reach a verdict, for a
# reason that has nothing to do with the tree being measured. Step 10's
# `./scripts/setup.sh` wants it too.
#
# PINNED AND CHECKSUMMED FOR NODE, DERIVED FOR PNPM, and the asymmetry is the
# point. Node arrives as a bare tarball from a publisher, so it gets the compose
# plugin's treatment exactly: a pinned version, the published sha256, and the
# verification BEFORE anything is unpacked. pnpm's version is not this file's to
# choose — `frontend/package.json`'s `packageManager` field already pins it for
# every developer and for CI, so the recipe READS it out of the checkout it is
# standing in. A second spelling here is a version the image and the tree can
# disagree about, silently, until a lockfile refuses on a box.
#
# TEXT, NOT BEHAVIOUR, AND THAT IS DECLARED. This case reads the recipe's
# sentinelled block; it does not run it, because running it would download a
# 30 MB tarball from nodejs.org on every gate. Whether the tarball unpacks,
# whether corepack activates, and whether `pnpm --version` answers on the image
# are the bake's own assertions and the field test's — never this drive's.
case_the_bake_installs_the_frontend_toolchain() {
    CURRENT=case_the_bake_installs_the_frontend_toolchain

    local block
    block="$(sed -n '/^# >>> the frontend toolchain >>>$/,/^# <<< the frontend toolchain <<<$/p' "$BAKE")"
    if [ -z "$block" ]; then
        bad "the recipe carries no sentinelled frontend-toolchain block: every box from this image
      answers 'no pnpm on PATH' and every box loop is exit 2 before it judges anything"
        return
    fi
    ok "the recipe brackets a frontend-toolchain block this case can read"

    # (a) NODE IS PINNED, not resolved at bake time. A "latest" that resolves is
    # a different runtime on every bake and an image nobody can reproduce on.
    local ver_n sha_n
    ver_n="$(grep -nE '^BAKE_NODE_VERSION=' "$BAKE" | head -n 1 | cut -d: -f1 || true)"
    sha_n="$(grep -nE '^BAKE_NODE_SHA256=' "$BAKE" | head -n 1 | cut -d: -f1 || true)"
    if [ -n "$ver_n" ] && [ -n "$sha_n" ]; then
        ok "node is pinned by version (:${ver_n}) and by sha256 (:${sha_n}), the two knobs reading together"
    else
        bad "BAKE_NODE_VERSION is at '${ver_n:-absent}' and BAKE_NODE_SHA256 at '${sha_n:-absent}' — a runtime with no pin, or a pin with no checksum"
    fi
    # AND THE VERSION IN THE URL COMES FROM THE KNOB. A literal version beside a
    # knob that claims to set it is a pin that has silently stopped pinning.
    # The tail reader runs to EOF and redirects, never `-q`: a quiet reader at
    # the tail of a pipeline under `pipefail` strangles its own producer over
    # 64 KiB (`test_sweep.sh`, `quiet_tail_sites`, for the measurements).
    if printf '%s\n' "$block" | grep -E 'nodejs\.org' | grep -E '\$\{?BAKE_NODE_VERSION' >/dev/null; then
        ok "the download URL is composed from the knob, never a literal version"
    else
        bad "the block's nodejs.org URL does not read BAKE_NODE_VERSION: $(printf '%s\n' "$block" | grep -F 'nodejs.org' | head -n 1)"
    fi

    # (b) AND THE CHECKSUM IS VERIFIED BEFORE THE RUNTIME IS IN PLACE. A
    # checksum after the unpack is a checksum of something already installed.
    local b_sha b_unpack
    b_sha="$(printf '%s\n' "$block" | grep -nE 'sha256sum -c' | head -n 1 | cut -d: -f1 || true)"
    b_unpack="$(printf '%s\n' "$block" | grep -nE 'tar -x[zJ]f' | head -n 1 | cut -d: -f1 || true)"
    if [ -n "$b_sha" ] && [ -n "$b_unpack" ] && [ "$b_sha" -lt "$b_unpack" ]; then
        ok "the sha256 is checked at block line ${b_sha}, before the unpack at ${b_unpack}"
    else
        bad "the checksum is at '${b_sha:-absent}' and the unpack at '${b_unpack:-absent}' — an unverified runtime would already be on the image"
    fi

    # (c) PNPM'S VERSION IS DERIVED FROM THE CHECKOUT, NEVER TYPED HERE. The
    # tree already pins it for every developer and for CI; a second spelling is
    # a disagreement waiting for a lockfile to find.
    if printf '%s\n' "$block" | grep -F -- "packageManager" >/dev/null; then
        ok "the block reads pnpm's version out of frontend/package.json's packageManager field"
    else
        bad "the block never reads packageManager — pnpm's version is either typed here or not pinned at all"
    fi
    local typed
    typed="$(printf '%s\n' "$block" | grep -cE 'pnpm@[0-9]' || true)"
    if [ "$typed" = "0" ]; then
        ok "and it spells no pnpm version of its own (0 literal pnpm@<n> in the block)"
    else
        bad "the block spells a literal pnpm version ${typed} time(s) — the image and the tree can now disagree"
    fi
    # AND THE FIELD IT READS IS REALLY THERE, in this tree, in the shape the
    # block's own reader expects. A derivation from a field nobody ships is a
    # bake that dies at the step, which is better than a wrong version and still
    # worth catching here.
    local pinned
    pinned="$(sed -n 's/.*"packageManager"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' frontend/package.json | head -n 1)"
    case "$pinned" in
    pnpm@[0-9]*) ok "frontend/package.json pins ${pinned}, which is what the block will read" ;;
    *) bad "frontend/package.json's packageManager is '${pinned:-absent}' — not a pnpm@<version> the block can derive from" ;;
    esac

    # (d) THE BODY CALLS IT, AND CALLS IT BEFORE THE STACK STEP, because
    # `./scripts/setup.sh` runs `pnpm install --frozen-lockfile`. It must also
    # come after the checkout guard: the version it derives lives in the tree.
    local b_check b_call b_setup
    b_check="$(grep -nE '^\[ -d "\$BAKE_CHECKOUT/\.git" \]' "$BAKE" | head -n 1 | cut -d: -f1 || true)"
    b_call="$(grep -nE '^install_frontend_toolchain$' "$BAKE" | head -n 1 | cut -d: -f1 || true)"
    b_setup="$(grep -nE '^\(cd "\$BAKE_CHECKOUT".*scripts/setup\.sh' "$BAKE" | head -n 1 | cut -d: -f1 || true)"
    if [ -n "$b_call" ] && [ -n "$b_setup" ] && [ -n "$b_check" ] && [ "$b_check" -lt "$b_call" ] && [ "$b_call" -lt "$b_setup" ]; then
        ok "the body installs it at :${b_call} — after the checkout guard at :${b_check} and before ./scripts/setup.sh at :${b_setup}"
    else
        bad "the install call is at '${b_call:-absent}', the checkout guard at '${b_check:-absent}', the stack step at '${b_setup:-absent}' — the order does not hold"
    fi

    # (e) AND THE PLAN SAYS SO. The plan is the image's runbook; a step that
    # runs and is not in it is a step the next operator will not know happened.
    local out="$WORK/bake-plan-fe.txt" rc=0
    local pen="$WORK/bake-pen-fe"
    rm -rf "$pen"
    mkdir -p "$pen"
    env -i PATH="/usr/bin:/bin" HOME="$pen" bash "$ROOT/$BAKE" --plan >"$out" 2>&1 || rc=$?
    if [ "$rc" != "0" ]; then
        bad "--plan exited ${rc}"
        return
    fi
    if grep -F -- "node" "$out" >/dev/null && grep -F -- "pnpm" "$out" >/dev/null && grep -F -- "sha256" "$out" >/dev/null; then
        ok "the plan names node, pnpm and the checksum"
    else
        bad "the plan does not name the frontend toolchain it installs"
        sed 's/^/      /' "$out"
    fi
}

case_bake_removes_its_marker_after_the_work_and_before_the_clean() {
    CURRENT=case_bake_removes_its_marker_after_the_work_and_before_the_clean
    # THE MARKER MUST NOT SURVIVE INTO THE IMAGE. `create-image` captures the
    # root volume as it stands, so a marker left in place is baked in — and then
    # EVERY launched verifier box satisfies `bake.sh`'s own precondition, which
    # means the destructive recipe (install packages, rewrite /etc/environment,
    # `cloud-init clean`) would run on a live box mid-verification if anything
    # ever invoked it there. The refusal at the top of the recipe is only worth
    # what the marker's absence makes it worth.
    local out="$WORK/bake-plan-2.txt" rc=0
    local pen="$WORK/bake-pen-2"
    rm -rf "$pen"
    mkdir -p "$pen/bin" "$pen/rec"
    env -i PATH="$pen/bin:/usr/bin:/bin" HOME="$pen" REC="$pen/rec" \
        bash "$ROOT/$BAKE" --plan >"$out" 2>&1 || rc=$?
    if [ "$rc" != "0" ]; then
        bad "--plan exited ${rc}"
        return
    fi

    # In the PLAN, which is the image's runbook. THE ANCHOR IS THE LAST STEP
    # THAT DOES WORK, and it is the shell-environment write rather than the
    # park: the park used to be the recipe's last act, so "after the park" and
    # "after the work" were one sentence — the park now runs before anything is
    # built, and an anchor left on it would hold this case green while asserting
    # nothing about the eleven steps in between.
    local work_n clean_n drop_n
    work_n="$(grep -n "DJB_GATE_SLOTS=2" "$out" | head -n 1 | cut -d: -f1 || true)"
    clean_n="$(grep -n "cloud-init clean" "$out" | head -n 1 | cut -d: -f1 || true)"
    drop_n="$(grep -nE "/etc/verifier/bake" "$out" | head -n 1 | cut -d: -f1 || true)"
    if [ -z "$drop_n" ]; then
        bad "the plan never says the bake marker is removed — it would be captured into the image"
    elif [ -n "$work_n" ] && [ -n "$clean_n" ] && [ "$drop_n" -gt "$work_n" ] && [ "$drop_n" -lt "$clean_n" ]; then
        ok "the plan removes the marker after the last working step (line ${work_n}) and before cloud-init clean (line ${clean_n})"
    else
        bad "the plan's marker removal is at line ${drop_n}; the last working step ${work_n}, clean ${clean_n} — it must sit between them"
        sed 's/^/      /' "$out"
    fi

    # And in the RECIPE ITSELF, because the plan is a promise and the body is
    # what runs.
    local b_work b_clean b_drop
    b_work="$(grep -nE '^step "[0-9]+/[0-9]+ environment' "$BAKE" | head -n 1 | cut -d: -f1 || true)"
    b_clean="$(grep -nE '^sudo cloud-init clean' "$BAKE" | head -n 1 | cut -d: -f1 || true)"
    b_drop="$(grep -nE '^sudo rm -f "\$BAKE_MARKER"' "$BAKE" | head -n 1 | cut -d: -f1 || true)"
    if [ -z "$b_drop" ]; then
        bad "the recipe body never removes \$BAKE_MARKER"
    elif [ -n "$b_work" ] && [ -n "$b_clean" ] && [ "$b_drop" -gt "$b_work" ] && [ "$b_drop" -lt "$b_clean" ]; then
        ok "the body removes it at :${b_drop}, after the last working step at :${b_work} and before the clean at :${b_clean}"
    else
        bad "the body's removal is at :${b_drop}; the last working step :${b_work:-absent}, clean :${b_clean:-absent}"
    fi
}

case_the_plan_is_never_mistaken_for_a_finished_bake() {
    CURRENT=case_the_plan_is_never_mistaken_for_a_finished_bake
    # The launch wrapper decides a bake succeeded by SCRAPING the recipe's last
    # line. A `--plan` that prints that same line is a plan the wrapper would
    # capture an image from — twenty minutes of provisioning that never ran,
    # baked into an AMI every verifier box then boots.
    local out="$WORK/bake-plan-3.txt" rc=0
    local pen="$WORK/bake-pen-3"
    rm -rf "$pen"
    mkdir -p "$pen/bin" "$pen/rec"
    env -i PATH="$pen/bin:/usr/bin:/bin" HOME="$pen" REC="$pen/rec" \
        bash "$ROOT/$BAKE" --plan >"$out" 2>&1 || rc=$?
    if [ "$rc" != "0" ]; then
        bad "--plan exited ${rc}"
        return
    fi
    if grep -F -- "ready for create-image" "$out" >/dev/null; then
        bad "the plan prints the success line the wrapper scrapes: '$(grep -F -- "ready for create-image" "$out" | head -n 1)'"
    else
        ok "no line of the plan matches the wrapper's success scrape"
    fi
    # The other direction, so the fix cannot be "delete the success line".
    if grep -E '^say "ready for create-image"' "$BAKE" >/dev/null; then
        ok "the real path still says it, once, at the end"
    else
        bad "the recipe's real path no longer prints the success line at all"
    fi
}

# FIELD TEST 5, IN THE RECIPE RATHER THAN IN THE SEAM. The bake box booted,
# the push landed, and step 1's `sudo dnf install` answered `sudo: a terminal
# is required to read the password` — eleven minutes of push spent on a
# precondition nobody had asserted. A recipe whose FIRST act needs root checks
# for root before it spends the bake, and says which file grants it; `sudo -n`
# is what makes that check a refusal rather than a prompt into a pipe that
# nobody can answer.
#
# BOTH DIRECTIONS, because a guard that refuses everything is the same defect
# wearing a refusal's clothes: a box that CAN sudo must get past it and reach
# step 1.
case_the_recipe_refuses_a_bake_box_it_cannot_sudo_on() {
    CURRENT=case_the_recipe_refuses_a_bake_box_it_cannot_sudo_on
    local pen="$WORK/bake-sudo" rc=0
    rm -rf "$pen"
    mkdir -p "$pen/bin" "$pen/rec" "$pen/etc/verifier"
    # The marker, so the refusal under test is the SUDO one and not the
    # not-a-bake-box one two lines above it.
    printf 'a bake box\n' >"$pen/etc/verifier/bake"
    # Every tool the first five steps would reach, planted as a recorder — so
    # "step 1 never ran" is a file that does not exist rather than an
    # inference.
    local tool
    # `sha256sum` and `docker` join the list for step 1's compose plugin: the
    # recipe verifies the pinned binary and then asks the plugin to answer, and
    # BOTH are GNU/Linux tools this drive's own machine may not have (macOS
    # spells the first `shasum -a 256` and has no docker at all). Shimming them
    # keeps this case about the SUDO guard; the pin and the checksum are
    # asserted as text and by ORDER in their own case, where a shim cannot
    # flatter them.
    for tool in dnf systemctl useradd usermod curl install id sha256sum docker; do
        cat >"$pen/bin/$tool" <<SHIM
#!/usr/bin/env bash
printf '%s\n' "$tool \$*" >>"\$REC/ran"
exit 0
SHIM
        chmod +x "$pen/bin/$tool"
    done
    # THE SUDO SHIM IS THE FIXTURE. \`-n true\` answers from a file the case
    # writes, and everything else is a recorder: the recipe's own steps must
    # not be what decides this case.
    cat >"$pen/bin/sudo" <<'SHIM'
#!/usr/bin/env bash
printf '%s\n' "sudo $*" >>"$REC/ran"
if [ "${1:-}" = "-n" ]; then
    exit "$(cat "$REC/sudo-n.rc" 2>/dev/null || echo 0)"
fi
exit 0
SHIM
    chmod +x "$pen/bin/sudo"

    # THE CHECKOUT KNOB IS AIMED INTO THE PEN, AND THAT IS NOT TIDINESS.
    # `BAKE_CHECKOUT` reads `DJB_VERIFIER_CHECKOUT` and falls back to the
    # recipe's own default, which is NOT under `VERIFIER_ROOT` — so with the
    # knob unset this case was reading a real absolute path outside the pen. On
    # a developer machine nothing is there, step 6 refused, and that refusal is
    # the outcome (b) below asserts; ON A VERIFIER BOX the recipe's default
    # checkout path IS the checkout, so step 6 passed, and the recipe walked on
    # through the park to step 8 and died on node instead. The case was green
    # on one OS by accident of the filesystem it ran on. A pen that aims the
    # knob at a path inside itself refuses at step 6 on every machine, for the
    # reason the case claims rather than for where it is running.
    #
    # The path itself is deliberately NOT spelled here: it is the recipe's knob
    # and `test_verifier_box.sh`'s census over `scripts` and `deploy` reds on a
    # second spelling of it anywhere else, which is the point of having a knob.
    local nocheckout="$pen/no-such-checkout"
    printf '%s\n' 1 >"$pen/rec/sudo-n.rc"
    # (a) THE BOX WITH NO RULE. `sudo -n true` refuses, and nothing after it runs.
    env -i PATH="$pen/bin:/usr/bin:/bin" HOME="$pen" REC="$pen/rec" VERIFIER_ROOT="$pen" \
        DJB_VERIFIER_CHECKOUT="$nocheckout" \
        bash "$ROOT/$BAKE" >"$pen/out" 2>&1 || rc=$?
    if [ "$rc" = "2" ]; then
        ok "a bake box whose account cannot sudo is exit 2"
    else
        bad "wanted exit 2 when \`sudo -n true\` refuses, got ${rc}"
        sed 's/^/      /' "$pen/out"
    fi
    # BEFORE STEP 1, WHICH IS THE WHOLE CLAIM — and a step banner in the output
    # is how a refusal that merely happens LATER (step 6's checkout, which
    # names the same user-data file) is told apart from this one.
    if grep -E '^== bake step' "$pen/out" >/dev/null; then
        bad "the recipe printed a step banner before it refused, so this is some LATER refusal and
      the sudo precondition is still discovered rather than asserted: $(grep -E '^== bake step' "$pen/out" | tr '\n' ' ')"
    else
        ok "and it refused before step 1 — no step of the recipe ran"
    fi
    if grep -F -- "NOPASSWD" "$pen/out" >/dev/null && grep -F -- "$BAKE_SEAM" "$pen/out" >/dev/null; then
        ok "and the refusal names both ${BAKE_SEAM} and the rule to put in it"
    else
        bad "the refusal does not name the rule and the file that grants it, so the operator has a
      message and no fix: $(tr '\n' ' ' <"$pen/out")"
    fi
    # `sudo dnf`, the way the recipe spells step 1 — the `dnf` recorder alone is
    # never reached, because `sudo` is the shim in front of it.
    if grep -E '^sudo dnf ' "$pen/rec/ran" >/dev/null 2>&1; then
        bad "it ran \`sudo dnf install\` anyway: the refusal is not CLOSED, it is a warning with
      an exit status in front of a recipe that runs regardless"
    else
        ok "step 1 never ran — no package was installed on a box the recipe cannot finish on"
    fi
    if grep -E '^sudo -n ' "$pen/rec/ran" >/dev/null 2>&1; then
        ok "the probe is \`sudo -n\`, which can only refuse — never a password prompt into a pipe"
    else
        bad "the recipe's probe is not \`sudo -n\`: a tunnelled session has no terminal to answer with.
      recorded: $(tr '\n' ' ' <"$pen/rec/ran")"
    fi

    # (b) THE BOX WITH THE RULE. The guard passes and the recipe gets as far as
    # the first precondition it cannot satisfy in a pen — the checkout, step 6 —
    # which is how this case knows the guard let it through rather than that
    # nothing was guarded.
    rm -f "$pen/rec/ran"
    printf '%s\n' 0 >"$pen/rec/sudo-n.rc"
    rc=0
    # ASSERTED, NOT ASSUMED: the path the knob names really has no checkout in
    # it, so the step-6 refusal below is about the pen and never about a tree
    # this machine happens to carry at the default path.
    if [ -e "$nocheckout/.git" ]; then
        bad "the pen's checkout path ${nocheckout} already holds a .git — step 6 would pass and this case would measure some later step"
        return
    fi
    env -i PATH="$pen/bin:/usr/bin:/bin" HOME="$pen" REC="$pen/rec" VERIFIER_ROOT="$pen" \
        DJB_VERIFIER_CHECKOUT="$nocheckout" \
        bash "$ROOT/$BAKE" >"$pen/out2" 2>&1 || rc=$?
    if grep -E '^sudo dnf ' "$pen/rec/ran" >/dev/null 2>&1; then
        ok "a box that CAN sudo reaches step 1 — the guard refuses a missing rule, not every bake"
    else
        bad "the recipe refused a box whose \`sudo -n true\` succeeds: $(tr '\n' ' ' <"$pen/out2")"
    fi
    if grep -F -- "no checkout at" "$pen/out2" >/dev/null; then
        ok "and it walks on to the checkout check at step 6, which a pen cannot satisfy"
    else
        bad "wanted the step-6 checkout refusal after the sudo guard passed, got: $(tr '\n' ' ' <"$pen/out2")"
    fi
}

# THE RULE ABOVE IS THE BAKE BOX'S, AND ONLY THE BAKE BOX'S. `create-image`
# captures the root volume as it stands, and cloud-init's sudo rules are FILES
# on that volume — so a rule left in place is baked into the image and every
# verifier box launched from it hands its account passwordless root. That
# contradicts the launch seam's own sentence ("with NO sudo rule: nothing a
# verification does needs root"), silently, from the other side of the image.
# So the recipe removes it, LAST — after the clean, because every step before
# that one needs the rule — and ASSERTS the removal, so a wrong drop-in path is
# a bake that refuses rather than an image nobody looks inside.
case_the_bake_users_root_leaves_with_the_bake() {
    CURRENT=case_the_bake_users_root_leaves_with_the_bake
    # (a) THE IMAGE'S OWN SEAM GRANTS NOTHING, which is the doctrine the recipe
    # is protecting. Read off the RENDERED file, like every other seam claim.
    local out="$WORK/user-data-sudo.yaml"
    [ -f "$out" ] || seam_render "$SEAM" "$out"
    if grep -E '^[[:space:]]*sudo:' "$out" >/dev/null; then
        bad "the launch seam grants a sudo rule: $(grep -E '^[[:space:]]*sudo:' "$out")"
    else
        ok "the launch seam grants no sudo rule — nothing a verification does needs root"
    fi

    # (b) THE RECIPE REMOVES THE BAKE BOX'S, and the plan says so, because the
    # plan is the image's runbook.
    local plan="$WORK/bake-plan-sudo.txt" rc=0
    env -i PATH="/usr/bin:/bin" HOME="$WORK" \
        bash "$ROOT/$BAKE" --plan >"$plan" 2>&1 || rc=$?
    if [ "$rc" != "0" ]; then
        bad "--plan exited ${rc}"
        return
    fi
    if grep -F -- "sudoers.d" "$plan" >/dev/null; then
        ok "the plan says the bake account's sudo rule is removed before the image is captured"
    else
        bad "the plan never says the sudo rule leaves with the bake — a reader of the runbook
      cannot tell that the image's account is not root"
    fi

    # (c) AND THE BODY DOES IT AFTER THE LAST STEP THAT NEEDS ROOT. `sudo
    # cloud-init clean` is that step; a removal above it is a recipe that
    # cannot finish.
    local b_clean b_drop
    b_clean="$(grep -nE '^sudo cloud-init clean' "$BAKE" | head -n 1 | cut -d: -f1 || true)"
    b_drop="$(grep -nE '^sudo rm -f "\$BAKE_SUDOERS"' "$BAKE" | head -n 1 | cut -d: -f1 || true)"
    if [ -z "$b_drop" ]; then
        bad "the recipe body never removes the bake account's sudo drop-in, so \`create-image\`
      captures it and every verifier box launched from the image has passwordless root"
    elif [ -n "$b_clean" ] && [ "$b_drop" -gt "$b_clean" ]; then
        ok "the body removes it at :${b_drop}, after the last step that needs it (the clean at :${b_clean})"
    else
        bad "the body removes the sudo rule at :${b_drop}, at or above the clean at :${b_clean} —
      every step of the recipe before the clean needs the rule it just dropped"
    fi

    # (d) AND IT ASSERTS THE REMOVAL. The drop-in's path is cloud-init's
    # convention and this drive cannot see the real one; an assertion is what
    # turns a wrong path into a refused bake instead of a root-capable image.
    local after
    after="$(sed -n "${b_drop:-1},\$p" "$BAKE")"
    if printf '%s\n' "$after" | grep -F -- "sudo -n true" >/dev/null; then
        ok "and it proves the rule is gone afterwards, so a drop-in path that is not cloud-init's
      refuses the bake rather than shipping an image with root in it"
    else
        bad "nothing after the removal checks that it worked: if cloud-init writes its rules
      somewhere else on this AMI, the recipe would report success over a root-capable image"
    fi
}

case_bake_refuses_to_run_anywhere_but_a_bake_box() {
    CURRENT=case_bake_refuses_to_run_anywhere_but_a_bake_box
    local pen="$WORK/bake-refuse" rc=0
    rm -rf "$pen"
    mkdir -p "$pen/bin" "$pen/rec"
    env -i PATH="$pen/bin:/usr/bin:/bin" HOME="$pen" REC="$pen/rec" VERIFIER_ROOT="$pen" \
        bash "$ROOT/$BAKE" >"$pen/out" 2>&1 || rc=$?
    if [ "$rc" = "2" ]; then
        ok "exit 2 with no bake marker — the recipe never runs on a laptop or on a verifier box"
    else
        bad "wanted exit 2 off a bake box, got ${rc}"
        sed 's/^/    /' "$pen/out"
    fi
    # And the marker is the one the bake box's own user-data writes, so the two
    # files cannot drift apart silently.
    local marker
    marker="$(grep -oE '/etc/verifier/bake' "$BAKE" | head -n 1)"
    if [ -n "$marker" ] && grep -F -- "/etc/verifier/bake" "$BAKE_SEAM" >/dev/null; then
        ok "the marker the recipe requires is the one the bake user-data writes"
    else
        bad "the recipe's bake marker and the bake user-data do not name the same file"
    fi
    rc=0
    env -i PATH="$pen/bin:/usr/bin:/bin" HOME="$pen" REC="$pen/rec" \
        bash "$ROOT/$BAKE" --nonsense >"$pen/out2" 2>&1 || rc=$?
    if [ "$rc" = "2" ]; then
        ok "an unknown flag is exit 2, never a silently different run"
    else
        bad "wanted exit 2 on an unknown flag, got ${rc}"
    fi
}

# =============================================================================
# GROUP 6 — what must not move
# =============================================================================

# deploy_layer_unfenced <directory> <gate file> — how many deploy-layer drives
# that gate file does NOT invoke.
#
# THE INVOKED SET IS DERIVED FROM THE FENCE AND NEVER TYPED, and it is the
# gate's own derivation: a drive is run iff `./deploy/tests/<name>.sh` appears
# in `scripts/check.sh` as a WHOLE LINE AT COLUMN ZERO, which is the shape
# `selftest_registered_drives` reads and the shape the blind-spot block
# subtracts with. Counting the directory instead — which this case used to do —
# reds the moment anybody WIRES one, punishing exactly the change the block
# exists to ask for. It cost a red on main the day `test_stage.sh` landed
# correctly fenced.
deploy_layer_unfenced() {
    local dir="$1" gate="$2" d n=0
    for d in "$dir"/test_*.sh; do
        [ -f "$d" ] || continue
        if grep -qxF "./deploy/tests/${d##*/}" "$gate"; then continue; fi
        n=$((n + 1))
    done
    printf '%s\n' "$n"
}

case_the_deploy_layer_drives_nothing_invokes_are_unchanged() {
    CURRENT=case_the_deploy_layer_drives_nothing_invokes_are_unchanged
    # The gate prints the deploy-layer drives NO MOMENT INVOKES as a DECLARED
    # blind spot, with a count. This drive is deliberately not one of them — it
    # lives under scripts/tests/ so a moment actually runs it — and the size of
    # that declared gap must not grow without somebody deciding it should.
    local n plant d
    n="$(deploy_layer_unfenced deploy/tests scripts/check.sh)"
    if [ "$n" = "7" ]; then
        ok "7 deploy-layer drives no moment invokes, unchanged — this drive did not join the set nothing runs"
    else
        bad "the gate invokes none of ${n} drive(s) under deploy/tests/, wanted 7 — the printed blind-spot count moved"
    fi

    # ITS OWN VICTIM, BOTH WAYS. A count nobody has seen fail is a count that
    # may be unable to fail, and this one is arithmetic over two derived sets:
    # the plants are a copy of the real population under the scratch directory,
    # plus a newcomer, against a copy of the real gate.
    plant="$WORK/deploy-layer-a"
    rm -rf "$plant"
    mkdir -p "$plant"
    for d in deploy/tests/test_*.sh; do cp "$d" "$plant/"; done
    cp scripts/check.sh "$plant/check.sh"
    : >"$plant/test_x.sh"
    n="$(deploy_layer_unfenced "$plant" "$plant/check.sh")"
    if [ "$n" = "8" ]; then
        ok "an UNFENCED newcomer moves the gap: 7 -> 8"
    else
        bad "an unfenced newcomer left the gap at ${n} — this count cannot fail"
    fi

    plant="$WORK/deploy-layer-b"
    rm -rf "$plant"
    mkdir -p "$plant"
    for d in deploy/tests/test_*.sh; do cp "$d" "$plant/"; done
    cp scripts/check.sh "$plant/check.sh"
    : >"$plant/test_y.sh"
    printf './deploy/tests/test_y.sh\n' >>"$plant/check.sh"
    n="$(deploy_layer_unfenced "$plant" "$plant/check.sh")"
    if [ "$n" = "7" ]; then
        ok "a newcomer WIRED at column zero does not move it — the gap is what nothing runs"
    else
        bad "a wired newcomer moved the gap to ${n} — fencing a drive must not red this"
    fi
}

# =============================================================================

echo "test_verifier_image: $(grep -c '^case_[A-Za-z0-9_]*() {' "$0") case(s)"
echo ""

case_reaper_holds_on_a_fresh_boot
case_reaper_holds_while_a_session_is_live
case_reaper_holds_while_the_gate_is_running
case_reaper_reaps_when_idle_passes_the_threshold
case_reaper_reaps_an_expired_box_even_mid_gate
case_reaper_reaps_when_expires_is_unreadable
case_reaper_reaps_when_expires_is_unparsable
case_reaper_uses_the_default_idle_minutes_and_says_so
case_reaper_holds_inside_the_boot_grace
case_reaper_reaps_when_the_activity_marker_is_missing
case_reaper_cannot_read_the_clock_and_says_so
case_reaper_cannot_read_the_activity_mtime_and_says_so

case_user_data_renders_with_four_values_and_leaves_no_slot
case_user_data_carries_the_four_properties_the_launch_depends_on
case_bake_user_data_installs_git_and_initialises_the_checkout
case_bake_user_data_writes_its_ready_marker_last

case_policy_summary_prints_every_statement
case_policy_every_terminate_allow_is_tag_conditioned
case_policy_run_instances_on_an_instance_needs_all_three_request_tags
case_policy_tags_the_image_and_the_snapshot_a_capture_creates
case_policy_passrole_names_only_the_verifier_box_role
case_policy_denies_every_write_to_an_environment_box
case_policy_grants_none_of_the_forbidden_action_families
case_policy_is_scoped_to_one_deployment_namespace
case_the_box_role_trusts_ec2_and_nothing_else
case_no_product_name_is_baked_into_the_machinery

case_bootstrap_refuses_without_a_deployment_namespace
case_bootstrap_refuses_without_an_account_or_a_region
case_the_owners_hand_is_a_command_the_tree_actually_spells
case_bootstrap_refuses_without_confirm_and_creates_nothing
case_bootstrap_prints_its_whole_plan_before_it_refuses
case_bootstrap_refuses_a_foreign_account
case_bootstrap_first_run_creates_each_resource_exactly_once
case_bootstrap_never_opens_an_ingress_rule
case_bootstrap_attaches_only_the_ssm_managed_policy_to_the_box_role
case_bootstrap_second_run_creates_nothing_and_mints_no_second_key
case_bootstrap_says_an_existing_policy_is_not_updated_by_a_re_run
case_bootstrap_prints_no_policy_version_when_the_live_one_already_agrees
case_bootstrap_prints_the_policy_version_when_the_live_one_differs
case_bootstrap_prints_the_box_roles_registry_grant_and_attaches_nothing
case_bootstrap_prints_no_registry_grant_when_the_role_already_carries_it
case_bootstrap_names_the_spot_service_linked_role_when_the_account_lacks_it
case_bootstrap_says_nothing_to_do_when_the_spot_role_exists
case_the_bootstrap_summarises_the_policy_on_the_checkouts_own_interpreter
case_the_bootstrap_refuses_a_checkout_with_no_interpreter
case_bootstrap_prints_the_secret_on_the_last_line_and_nowhere_else
case_bootstrap_refuses_a_piped_stdout

case_the_recipe_installs_no_package_amazon_linux_does_not_have
case_the_compose_plugin_is_pinned_and_checksummed_before_it_is_installed
case_bake_plan_runs_nothing_and_names_its_steps_in_order
case_the_bake_parks_before_it_sets_up
case_the_bake_writes_no_database_pin
case_the_bake_installs_the_frontend_toolchain
case_bake_removes_its_marker_after_the_work_and_before_the_clean
case_the_plan_is_never_mistaken_for_a_finished_bake
case_the_recipe_refuses_a_bake_box_it_cannot_sudo_on
case_the_bake_users_root_leaves_with_the_bake
case_bake_refuses_to_run_anywhere_but_a_bake_box

case_the_deploy_layer_drives_nothing_invokes_are_unchanged

echo ""
echo "test_verifier_image: ${PASSED} passed, ${FAILED} failed"
drive_finished
[ "$FAILED" = "0" ] || exit 1
exit 0
