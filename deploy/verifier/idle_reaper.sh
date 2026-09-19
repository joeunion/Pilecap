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
# THE IDLE REAPER — the thing that takes a verifier box down when nobody is
# left to do it.
#
# WHY IT IS INSIDE THE IMAGE AND NOT IN A WRAPPER ON SOMEBODY'S LAPTOP. Bringing
# a box up needs a session. Taking one down must NOT, because the session that
# started it is the one most likely to be gone: an agent's turn ends, a harness
# reaps a process, a laptop sleeps, and the instance keeps billing. A watchdog
# that outlives the session is something a person has to own. A timer inside the
# image needs no watcher at all — which is why teardown lives here and `up`
# lives in the wrapper.
#
# HOW IT TAKES THE BOX DOWN. `shutdown -h now`. The instance is launched with
# `InstanceInitiatedShutdownBehavior=terminate`, so a halt from inside is a
# TERMINATION and the encrypted root volume goes with it. That is the whole
# mechanism: one call, no API, no credential on the box, nothing to authorise.
#
# THE TWO WAYS DOWN, AND THEY PULL IN OPPOSITE DIRECTIONS.
#
#   THE HARD LIFETIME (`/etc/verifier/expires`) wins over everything, running
#   gate included. It is the only thing that bounds the bill when every other
#   signal says busy — a wedged test run, a session somebody left open, a
#   process that will not exit. When it fires it does not ask what is running.
#
#   THE IDLE TIMER (`/etc/verifier/idle-minutes` against
#   `/run/verifier/last-activity`) is the ordinary path, and it is the one that
#   must NEVER fire during a verification: a box reaped at minute 35 of a
#   40-minute gate is a verdict nobody has, and the verifier reports `stuck`
#   instead of a colour. So idleness is three separate questions and all three
#   must say idle — no login session, no verification-shaped process, and no
#   activity marker newer than the threshold.
#
# FAIL CLOSED, AND THE DIRECTION IS THE MONEY. A box that cannot READ its own
# lifetime cannot prove it is allowed to exist, so it stops: an absent
# `expires`, an unparsable one, an `expires` this file cannot make sense of —
# all one decision, `reap: expires unreadable — fail closed`. The alternative
# (hold when in doubt) is a bill with no ceiling and nobody watching, which is
# the exact failure this file exists to make impossible.
#
# THE ONE PLACE IT HOLDS IN DOUBT is the boot grace, and it is a clock
# question rather than a policy one. `expires` is an absolute instant; a box
# whose chrony has not synced yet can read a clock minutes or hours off and
# reap a machine somebody just paid to start. So for the first
# VERIFIER_BOOT_GRACE seconds after `/run/verifier/boot-at` the hard lifetime is
# not honoured. If the box never wrote a boot marker there is no grace: an
# unknown boot time is not an excuse, it is one more thing that cannot be
# proven.
#
# EVERY DECISION IS ONE LINE, and it goes three places: stdout (so
# `get-console-output` carries it off the box after the fact), the appended log
# at `/var/log/verifier-reaper.log`, and `logger` where syslog exists. One line
# per tick, `reaper <utc> <decision>`, whichever way it went — a reaper that
# only speaks when it acts is a reaper whose silence means either "healthy" or
# "dead" and nobody can tell which.
#
# THE TIMER. `verifier-reaper.timer` fires it every 60 seconds as root. The unit
# is installed by the bake recipe and ENABLED by the launch user-data, so an
# image can be inspected without its own reaper running.
#
#   ./idle_reaper.sh          decide once and act
#
# Exit: 0 it decided (hold or reap) · 2 it could not decide — a scratch root it
# cannot read, a clock it cannot ask. 2 is could-not-look here as everywhere,
# and the timer will simply ask again in a minute.
#
# TESTING SEAMS, and they are environment variables rather than flags because
# the timer's command line is fixed: VERIFIER_ROOT prefixes every path (empty on
# a real box), VERIFIER_USER names the account whose processes and sessions
# count. `scripts/tests/test_verifier_image.sh` drives every decision below
# under a scratch root with `who`, `pgrep`, `date`, `shutdown` and `logger`
# planted on PATH.
#
# WHAT IT CANNOT SEE, declared rather than discovered:
#
#   * A VERIFICATION THAT LOOKS LIKE NOTHING. The busy test is a fixed list of
#     process names (below). A verifier running something else entirely — a
#     long `docker build`, a hand-written script — is invisible to it, and the
#     activity marker is the belt: every wrapper call touches it.
#   * A SESSION `who` DOES NOT LIST. Whether a Session Manager session appears
#     in `who` on Amazon Linux is the field test's question, not this file's.
#   * THE CLOCK BEYOND THE GRACE. A box whose clock is wrong by more than the
#     grace window reaps early or late, and nothing here can tell.
#   * WHETHER THE HALT TERMINATES. That is the instance's shutdown behaviour,
#     set at launch by the wrapper, and unobservable from inside.
set -euo pipefail

VERIFIER_ROOT="${VERIFIER_ROOT:-}"
VERIFIER_USER="${VERIFIER_USER:-verifier}"

#: Seconds after boot during which the hard lifetime is not honoured, so an
#: unsynced clock cannot reap a box that was just created. Honoured only when
#: /run/verifier/boot-at exists.
VERIFIER_BOOT_GRACE="${VERIFIER_BOOT_GRACE:-120}"

#: The idle threshold used when /etc/verifier/idle-minutes is absent or
#: unreadable. The decision line SAYS `(default)` when this is what it used.
VERIFIER_DEFAULT_IDLE_MINUTES="${VERIFIER_DEFAULT_IDLE_MINUTES:-30}"

EXPIRES_FILE="${VERIFIER_ROOT}/etc/verifier/expires"
IDLE_FILE="${VERIFIER_ROOT}/etc/verifier/idle-minutes"
ACTIVITY_FILE="${VERIFIER_ROOT}/run/verifier/last-activity"
BOOT_FILE="${VERIFIER_ROOT}/run/verifier/boot-at"
LOG_FILE="${VERIFIER_ROOT}/var/log/verifier-reaper.log"

# The process names that mean "a verification is happening here". `check.sh`
# first, because it is the one whose interruption costs a verdict and the one
# whose name the decision line prints.
WATCHED_PROCESSES="check.sh pytest verify_start.sh setup.sh uv"

# --- the clock ---------------------------------------------------------------
#
# `date -d` is GNU and `date -j -f` is BSD, and a reaper that parses its own
# lifetime with whichever one the machine happens to have is a reaper that
# silently stops parsing when the machine changes. So the ISO-8601 instant is
# parsed HERE, in arithmetic, and `date` is asked for exactly one thing: the
# current epoch second. That also makes the parse itself drivable rather than
# a property of the box's coreutils.
verifier_iso_to_epoch() {
    local iso="$1"
    case "$iso" in
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z) ;;
    *) return 1 ;;
    esac
    local y m d hh mm ss
    # 10# on every field: bash reads a leading zero as octal, so `08` and `09`
    # are syntax errors in arithmetic and every August and September instant
    # would be "unparsable".
    y=$((10#${iso:0:4}))
    m=$((10#${iso:5:2}))
    d=$((10#${iso:8:2}))
    hh=$((10#${iso:11:2}))
    mm=$((10#${iso:14:2}))
    ss=$((10#${iso:17:2}))
    { [ "$m" -ge 1 ] && [ "$m" -le 12 ]; } || return 1
    { [ "$d" -ge 1 ] && [ "$d" -le 31 ]; } || return 1
    { [ "$hh" -le 23 ] && [ "$mm" -le 59 ] && [ "$ss" -le 60 ]; } || return 1

    # days_from_civil — the standard proleptic-Gregorian conversion, shifted so
    # that 1970-01-01 is day 0.
    # `if`, never `[ … ] && …`: an AND-list whose left half is false returns 1,
    # and under `set -e` that ends the shell — so every March-to-December
    # instant would have died here rather than parsed.
    local yy=$y era yoe doy doe mp days
    if [ "$m" -le 2 ]; then yy=$((y - 1)); fi
    if [ "$yy" -ge 0 ]; then era=$((yy / 400)); else era=$(((yy - 399) / 400)); fi
    yoe=$((yy - era * 400))
    if [ "$m" -gt 2 ]; then mp=$((m - 3)); else mp=$((m + 9)); fi
    doy=$(((153 * mp + 2) / 5 + d - 1))
    doe=$((yoe * 365 + yoe / 4 - yoe / 100 + doy))
    days=$((era * 146097 + doe - 719468))
    printf '%s\n' $((days * 86400 + hh * 3600 + mm * 60 + ss))
}

NOW=""
NOW="$(date +%s 2>/dev/null || true)"
case "$NOW" in
'' | *[!0-9]*)
    echo "!! verifier-reaper: could not read the clock — nothing was decided." >&2
    exit 2
    ;;
esac

# --- the decision line -------------------------------------------------------
#
# One line, three destinations, and the file write is best-effort ON PURPOSE: a
# reaper that refuses to halt an expired box because /var is full is a reaper
# that turned an unwritable disk into an unbounded bill. The stdout copy is the
# one the console log carries and it always happens.
LOG_DIR="$(dirname "$LOG_FILE")"
mkdir -p "$LOG_DIR" 2>/dev/null || true

say_decision() {
    local line
    line="reaper $(date -u +%Y-%m-%dT%H:%M:%SZ) $1"
    printf '%s\n' "$line"
    printf '%s\n' "$line" >>"$LOG_FILE" 2>/dev/null ||
        echo "verifier-reaper: could not append to ${LOG_FILE} — the decision above still stands." >&2
    command -v logger >/dev/null 2>&1 && logger -t verifier-reaper -- "$line" || true
}

reap() {
    say_decision "$1 — shutdown -h now"
    shutdown -h now
    exit 0
}

hold() {
    say_decision "$1"
    exit 0
}

# --- the idle threshold ------------------------------------------------------
IDLE_MINUTES="$VERIFIER_DEFAULT_IDLE_MINUTES"
IDLE_SUFFIX=" (default)"
if [ -r "$IDLE_FILE" ]; then
    _idle_raw="$(tr -d '[:space:]' <"$IDLE_FILE" || true)"
    case "$_idle_raw" in
    '' | *[!0-9]*) ;;
    *)
        IDLE_MINUTES="$_idle_raw"
        IDLE_SUFFIX=""
        ;;
    esac
fi

# --- 1 · the hard lifetime, which outranks everything ------------------------
if [ ! -r "$EXPIRES_FILE" ]; then
    reap "reap: expires unreadable — fail closed"
fi
EXPIRES_RAW="$(tr -d '[:space:]' <"$EXPIRES_FILE" || true)"
EXPIRES_EPOCH=""
EXPIRES_EPOCH="$(verifier_iso_to_epoch "$EXPIRES_RAW" || true)"
if [ -z "$EXPIRES_EPOCH" ]; then
    reap "reap: expires unreadable — fail closed"
fi

if [ "$NOW" -ge "$EXPIRES_EPOCH" ]; then
    # The one hold in doubt, and it is about the clock rather than the policy.
    if [ -r "$BOOT_FILE" ]; then
        _boot="$(tr -d '[:space:]' <"$BOOT_FILE" || true)"
        case "$_boot" in
        '' | *[!0-9]*) ;;
        *)
            _up=$((NOW - _boot))
            if [ "$_up" -ge 0 ] && [ "$_up" -lt "$VERIFIER_BOOT_GRACE" ]; then
                hold "hold: boot grace (${_up}s < ${VERIFIER_BOOT_GRACE}s) — the clock may not be synced yet"
            fi
            ;;
        esac
    fi
    reap "reap: expired ${EXPIRES_RAW}"
fi

# --- 2 · a live session holds the box ----------------------------------------
if command -v who >/dev/null 2>&1; then
    if [ -n "$(who 2>/dev/null || true)" ]; then
        hold "hold: session"
    fi
fi

# --- 3 · a verification in flight holds the box ------------------------------
for _proc in $WATCHED_PROCESSES; do
    if pgrep -u "$VERIFIER_USER" -f "$_proc" >/dev/null 2>&1; then
        hold "hold: busy (${_proc})"
    fi
done

# --- 4 · the idle timer ------------------------------------------------------
#
# The activity marker's MTIME is the signal, because `touch` is what the wrapper
# does on every `run`, `loop` and `push` and a touch writes no content. An absent
# marker is fail-closed for the same reason an absent `expires` is — but it is
# reached only AFTER the two holds above, so a box doing real work can never be
# reaped by it.
if [ ! -e "$ACTIVITY_FILE" ]; then
    reap "reap: last-activity missing — fail closed"
fi

file_mtime() {
    stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || return 1
}

LAST=""
LAST="$(file_mtime "$ACTIVITY_FILE" || true)"
case "$LAST" in
'' | *[!0-9]*)
    echo "!! verifier-reaper: could not read the mtime of ${ACTIVITY_FILE} — nothing was decided." >&2
    exit 2
    ;;
esac

IDLE_SECONDS=$((NOW - LAST))
[ "$IDLE_SECONDS" -ge 0 ] || IDLE_SECONDS=0
IDLE_FOR=$((IDLE_SECONDS / 60))

if [ "$IDLE_FOR" -ge "$IDLE_MINUTES" ]; then
    reap "reap: idle ${IDLE_FOR}m ≥ ${IDLE_MINUTES}m${IDLE_SUFFIX}"
fi

hold "hold: fresh (${IDLE_FOR}m < ${IDLE_MINUTES}m)${IDLE_SUFFIX}"
