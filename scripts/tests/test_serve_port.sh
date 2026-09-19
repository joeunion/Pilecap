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
# drives: compose.yaml scripts/db.sh scripts/kill_mine.sh scripts/queue_cited.sh scripts/serve.sh scripts/sweep.sh
# The drive for `scripts/serve.sh`'s port — the derivation that gives every
# checkout its own, and the belt that refuses one somebody else is holding.
#
#   ./scripts/tests/test_serve_port.sh          run every case
#   ./scripts/tests/test_serve_port.sh --list   name them and stop
#
# WHY IT EXISTS. `PORT="${PORT:-8000}"` gave every checkout on this machine one
# port. With five lanes running concurrently the second `serve.sh` lost the
# bind and the FIRST one kept it, so the second lane's agent drove four calls
# against ANOTHER AGENT'S TREE before a 401 gave it away — an anonymous route
# would never have told it. Both halves of the fix are invisible when they are working:
# a derivation that quietly separates two checkouts looks exactly like luck,
# and a refusal nobody trips looks exactly like a line that could be deleted.
#
# IT BUILDS ITS OWN CHECKOUTS. `serve.sh` derives its root from its own
# location and asks `db.sh` for the path hash, so a scratch directory holding
# `scripts/serve.sh` and `scripts/db.sh` IS a checkout as far as the derivation
# is concerned — no git, no venv, no database. That is what lets this drive
# answer "do two checkouts differ?" without cloning anything.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   1. IT NEVER RUNS UVICORN. Every case either asks for the port
#      (`--print-port`) or drives a REFUSAL, which returns before the `exec`.
#      Nothing here proves the server starts, serves, or binds the port it
#      printed — the rung report carries the live two-checkout drive, and
#      `serve.sh` printing the port it is about to hand uvicorn is the standing
#      link between the two.
#   2. THE COPIES. The two-checkout cases run a `cp` of `serve.sh` and `db.sh`
#      into scratch directories, made fresh at the start of the run so they
#      cannot drift within it — but a copy nonetheless. Every other case runs
#      THIS TREE'S OWN FILE.
#   3. THE RACE. `serve.sh` probes the port and then execs; something can take
#      it in between. That window is declared in `serve.sh`'s own header and
#      nothing here narrows or measures it.
#   4. COLLISION PROBABILITY. The window is 10000 wide and the digest is not
#      asserted to be uniform over it. What is asserted is that the window is
#      clear of every port `compose.yaml` publishes — which is the collision
#      this repository can actually cause — and the belt is what covers the
#      rest.
#   5. WHETHER THE HOLDER NAMED IS THE RIGHT HOLDER. The refusal prints
#      `lsof`'s answer; this drive asserts that the holder's pid appears in it,
#      not that `lsof` is telling the truth.
set -euo pipefail

cd "$(dirname "$0")/../.."

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_serve_port: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It carries the only thing keeping this drive's scratch work inside its" >&2
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

cannot_look() {
    echo "!! test_serve_port: $*" >&2
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
    echo "!! unknown argument '$1': test_serve_port.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

[ -x scripts/serve.sh ] || cannot_look "scripts/serve.sh is not an executable file in this tree"
[ -f scripts/db.sh ] || cannot_look "scripts/db.sh is not in this tree — the derivation seam is gone"
[ -f compose.yaml ] || cannot_look "compose.yaml is not in this tree — the published ports cannot be read"
command -v python3 >/dev/null 2>&1 ||
    cannot_look "no python3 on PATH — it is how this drive holds a port without starting a server"

ROOT="$PWD"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-serve-port-drive.XXXXXX")" || cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"

HOLDER_PID=""
stop_holder() {
    [ -n "$HOLDER_PID" ] || return 0
    kill "$HOLDER_PID" 2>/dev/null || true
    wait "$HOLDER_PID" 2>/dev/null || true
    HOLDER_PID=""
}
drive_at_exit 'stop_holder; rm -rf "$WORK"'

# --- the assertions ----------------------------------------------------------
CURRENT=""
RC=0
OUT=""
ERR=""
N=0

ok() {
    echo "  ok       ${CURRENT} — $1"
    PASSED=$((PASSED + 1))
}
bad() {
    echo "  FAILED   ${CURRENT} — $1"
    for f in "$OUT" "$ERR"; do
        [ -n "$f" ] && [ -f "$f" ] && [ -s "$f" ] && sed 's/^/             | /' "$f" | tail -20
    done
    FAILED=$((FAILED + 1))
}

# Run a serve.sh — this tree's, or a scratch copy's — keeping stdout and stderr
# APART, because "the number is on stdout and nothing else" is one of the
# properties under drive.
run_serve() {
    local script="$1"
    CURRENT="$2"
    shift 2
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    ERR="${WORK}/err${N}.log"
    RC=0
    "$script" "$@" >"$OUT" 2>"$ERR" || RC=$?
}

exits() {
    if [ "$RC" -eq "$1" ]; then
        ok "exit ${RC}"
    else
        bad "wanted exit $1, got ${RC}"
    fi
}

exits_not() {
    if [ "$RC" -ne "$1" ]; then
        ok "exit ${RC}, which is not $1"
    else
        bad "exited $1 and must not"
    fi
}

says() {
    if grep -qF -- "$1" "$ERR" || grep -qF -- "$1" "$OUT"; then
        ok "says \"$1\""
    else
        bad "does not say \"$1\""
    fi
}

# --- the scratch checkouts ----------------------------------------------------
#
# Two files is a checkout here: `serve.sh` cd's to its own parent's parent and
# sources `scripts/db.sh` from there, and the derivation reads nothing else.
SCRATCH_DIR=""
scratch_checkout() {
    SCRATCH_DIR="${WORK}/$1"
    drive_require_scratch SCRATCH_DIR "${SCRATCH_DIR:-}"
    mkdir -p "${SCRATCH_DIR}/scripts"
    cp "${ROOT}/scripts/serve.sh" "${SCRATCH_DIR}/scripts/serve.sh"
    cp "${ROOT}/scripts/db.sh" "${SCRATCH_DIR}/scripts/db.sh"
    chmod +x "${SCRATCH_DIR}/scripts/serve.sh"
}

# Hold a port the way another checkout's server would: listening, and not this
# process. `python3` rather than `nc`, whose flags differ between the BSD one
# macOS ships and the GNU one Linux does.
hold_port() {
    # Two statements, not one `local a=… b="…$a…"`: on macOS's bash 3.2 the
    # second name is expanded before the first is bound, and under `set -u`
    # that is an unbound-variable death — which section 5 of the preamble then
    # correctly reports as could-not-look rather than a pass.
    local port="$1"
    local ready="${WORK}/held.${port}"
    rm -f "$ready"
    python3 -c '
import socket, sys, time
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind(("127.0.0.1", int(sys.argv[1])))
s.listen(5)
open(sys.argv[2], "w").write("held\n")
time.sleep(300)
' "$port" "$ready" &
    HOLDER_PID=$!
    local n=0
    while [ ! -f "$ready" ]; do
        n=$((n + 1))
        [ "$n" -lt 100 ] || cannot_look "the scratch holder never bound 127.0.0.1:${port}"
        sleep 0.1
    done
}

port_is_free() {
    python3 -c '
import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.bind(("127.0.0.1", int(sys.argv[1])))
except OSError:
    raise SystemExit(1)
finally:
    s.close()
raise SystemExit(0)
' "$1"
}

# A port nothing is listening on, taken from the derived window so the window
# itself is what gets exercised.
free_port() {
    python3 -c '
import socket
for port in range(20000, 30000):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
    except OSError:
        s.close()
        continue
    s.close()
    print(port)
    break
'
}

# --- the cases ----------------------------------------------------------------

case_the_port_is_derived_and_stable() {
    # A derivation that is not stable is not a derivation: a builder who wrote
    # the port down once has to be able to come back to it.
    run_serve "${ROOT}/scripts/serve.sh" "the same checkout, asked twice" --print-port
    exits 0
    local first second
    first="$(cat "$OUT")"
    run_serve "${ROOT}/scripts/serve.sh" "the same checkout, asked twice" --print-port
    second="$(cat "$OUT")"
    if [ -n "$first" ] && [ "$first" = "$second" ]; then
        ok "both answers are ${first}"
    else
        bad "asked twice and got '${first}' then '${second}'"
    fi
}

case_two_checkouts_derive_different_ports() {
    # THE WHOLE POINT. Two checkouts at two paths must not want one port.
    local a b pa pb
    scratch_checkout alpha
    a="$SCRATCH_DIR"
    scratch_checkout bravo
    b="$SCRATCH_DIR"
    run_serve "${a}/scripts/serve.sh" "two checkouts, two ports" --print-port
    exits 0
    pa="$(cat "$OUT")"
    run_serve "${b}/scripts/serve.sh" "two checkouts, two ports" --print-port
    exits 0
    pb="$(cat "$OUT")"
    if [ -n "$pa" ] && [ -n "$pb" ] && [ "$pa" != "$pb" ]; then
        ok "alpha derived ${pa} and bravo derived ${pb}"
    else
        bad "two checkouts derived '${pa}' and '${pb}' — the derivation did not separate them"
    fi
    # And a third fact worth pinning: neither of them is the old constant.
    if [ "$pa" != "8000" ] && [ "$pb" != "8000" ]; then
        ok "neither is the old fixed constant 8000"
    else
        bad "a checkout still derives 8000 — the constant is back"
    fi
}

case_the_port_says_where_it_came_from() {
    # A number with no provenance is a number a reader has to go and look up.
    run_serve "${ROOT}/scripts/serve.sh" "the derivation names its input" --print-port
    exits 0
    says "derived from this checkout"
    says "$ROOT"
    # stdout is DATA — a script reads it. Prose belongs on stderr.
    if [ "$(wc -l <"$OUT" | tr -d ' ')" = "1" ]; then
        ok "stdout is exactly one line"
    else
        bad "stdout is not one line: $(tr '\n' ' ' <"$OUT")"
    fi
}

case_a_pin_wins_outright() {
    # The escape, spelled the way DATABASE_NAME's and CACHE_KEY_PREFIX's are.
    local free
    free="$(free_port)"
    CURRENT="PORT= wins"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    ERR="${WORK}/err${N}.log"
    RC=0
    PORT="$free" "${ROOT}/scripts/serve.sh" --print-port >"$OUT" 2>"$ERR" || RC=$?
    exits 0
    if [ "$(cat "$OUT")" = "$free" ]; then
        ok "PORT=${free} came back as ${free}"
    else
        bad "PORT=${free} came back as $(cat "$OUT")"
    fi
    says "pinned by PORT="
}

case_the_window_is_clear_of_every_published_port() {
    # DERIVED, NOT A HAND LIST. If somebody publishes a compose port inside the
    # serve window, this case goes red and names it — which is the only way a
    # window stays true as the stack grows.
    CURRENT="the window is clear of compose.yaml"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    ERR="${WORK}/err${N}.log"
    RC=0
    python3 - "$ROOT" >"$OUT" 2>"$ERR" <<'PY' || RC=$?
import re
import sys

root = sys.argv[1]
base = span = None
for line in open(f"{root}/scripts/serve.sh"):
    m = re.match(r"^SERVE_PORT_BASE=(\d+)", line)
    if m:
        base = int(m.group(1))
    m = re.match(r"^SERVE_PORT_SPAN=(\d+)", line)
    if m:
        span = int(m.group(1))
if base is None or span is None:
    print("serve.sh no longer declares SERVE_PORT_BASE/SERVE_PORT_SPAN")
    raise SystemExit(2)

published = set()
for line in open(f"{root}/compose.yaml"):
    stripped = line.strip()
    if not stripped.startswith("- "):
        continue
    value = stripped[2:].strip().strip('"').strip("'")
    # host_ip:HOST:CONTAINER, or HOST:CONTAINER. The host half is field -2.
    parts = value.split(":")
    if len(parts) < 2:
        continue
    host = parts[-2]
    # ${VAR:-8081} -> 8081
    m = re.match(r"^\$\{[A-Za-z0-9_]+:-(\d+)\}$", host)
    if m:
        host = m.group(1)
    if host.isdigit():
        published.add(int(host))

if not published:
    print("no published ports parsed out of compose.yaml — the reader is broken, not the window")
    raise SystemExit(2)

clash = sorted(p for p in published if base <= p < base + span)
print(f"window {base}-{base + span - 1}; compose publishes {sorted(published)}")
if clash:
    print(f"CLASH {clash}")
    raise SystemExit(1)
PY
    exits 0
    says "window 20000-29999"
}

case_a_taken_port_is_refused_loudly() {
    # THE BELT, and the ABSENT clause: a second serve must never exit 0 against
    # a bound port.
    local free
    free="$(free_port)"
    hold_port "$free"
    CURRENT="a taken port is refused"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    ERR="${WORK}/err${N}.log"
    RC=0
    PORT="$free" "${ROOT}/scripts/serve.sh" >"$OUT" 2>"$ERR" || RC=$?
    exits 2
    exits_not 0
    says "REFUSES"
    says "127.0.0.1:${free} is already listening"
    # It has to name the HOLDER, or the refusal is just a nicer crash.
    if grep -qF -- "$HOLDER_PID" "$ERR"; then
        ok "names the holding pid ${HOLDER_PID}"
    elif grep -qF -- "no \`lsof\` on PATH" "$ERR"; then
        ok "no lsof here, and it says so rather than pretending"
    else
        bad "names neither the holder nor the reason it could not"
    fi
    # And it must not have started anything.
    if grep -qF "Uvicorn running" "$OUT" || grep -qF "Uvicorn running" "$ERR"; then
        bad "uvicorn started anyway"
    else
        ok "uvicorn was never started"
    fi
    stop_holder
}

case_the_belt_covers_the_derived_port_too() {
    # The refusal is not a courtesy attached to the pin: the derived port is
    # exactly the one two checkouts can collide on by accident.
    local mine
    mine="$("${ROOT}/scripts/serve.sh" --print-port 2>/dev/null)"
    [ -n "$mine" ] || cannot_look "this checkout's serve.sh printed no port"
    # PLANT ONLY IF IT IS FREE. A builder running this drive while their own
    # `serve.sh` is up is not a broken drive — it is the exact condition under
    # test, already arranged. Refusing there would make the gate red for a
    # server doing its job.
    if port_is_free "$mine"; then
        hold_port "$mine"
    fi
    run_serve "${ROOT}/scripts/serve.sh" "the derived port, held by somebody else"
    exits 2
    says "127.0.0.1:${mine} is already listening"
    says "derived from this checkout"
    stop_holder
}

case_a_public_base_url_that_names_another_port_is_announced() {
    # THE DISAGREEMENT THIS CHANGE CREATES. Deriving the serve port without
    # touching PUBLIC_BASE_URL makes every absolute URL — the Zitadel redirect
    # URI above all — point at a port this checkout is not serving. The value
    # is settings' to own; the SILENCE is this script's, and this is the case
    # that keeps it broken.
    local dir port
    scratch_checkout delta
    dir="$SCRATCH_DIR"
    printf 'PUBLIC_BASE_URL=http://127.0.0.1:8000\n' >"${dir}/.env"
    port="$("${dir}/scripts/serve.sh" --print-port 2>/dev/null)"
    [ -n "$port" ] || cannot_look "the scratch checkout printed no port"
    # Held, so the run stops at the belt instead of trying to exec uvicorn in a
    # directory with no project in it.
    if port_is_free "$port"; then
        hold_port "$port"
    fi
    run_serve "${dir}/scripts/serve.sh" "PUBLIC_BASE_URL names another port"
    says "PUBLIC_BASE_URL in .env says port 8000"
    says "http://127.0.0.1:${port}"
    stop_holder

    # AND IT IS SILENT WHEN THEY AGREE, or it becomes noise every reader
    # scrolls past — which is the state a stderr note like this had already reached.
    printf 'PUBLIC_BASE_URL=http://127.0.0.1:%s\n' "$port" >"${dir}/.env"
    if port_is_free "$port"; then
        hold_port "$port"
    fi
    run_serve "${dir}/scripts/serve.sh" "PUBLIC_BASE_URL agrees"
    if grep -qF "PUBLIC_BASE_URL in .env says port" "$ERR"; then
        bad "announced a disagreement between a port and itself"
    else
        ok "silent when PUBLIC_BASE_URL and the derived port agree"
    fi
    stop_holder
}

case_an_unknown_argument_is_exit_2() {
    # A mistyped flag is never a silently different run.
    run_serve "${ROOT}/scripts/serve.sh" "an unknown argument" --pirnt-port
    exits 2
    says "unknown argument"
    if grep -qF "Uvicorn running" "$OUT" || grep -qF "Uvicorn running" "$ERR"; then
        bad "started a server on a mistyped flag"
    else
        ok "started nothing"
    fi
}

case_a_missing_derivation_seam_is_exit_2() {
    # Without db.sh there is no path hash and no DATABASE_NAME: serving then
    # means a guessed database on everybody's port. That is could-not-look, and
    # 2 outranks a pass here as everywhere.
    local dir
    scratch_checkout charlie
    dir="$SCRATCH_DIR"
    rm -f "${dir}/scripts/db.sh"
    run_serve "${dir}/scripts/serve.sh" "no scripts/db.sh" --print-port
    exits 2
    says "scripts/db.sh is missing or unreadable"
}

case_the_port_derivation_rides_db_sh_rather_than_copying_it() {
    # The house pattern is ONE derivation with several consumers. A second copy
    # of the arithmetic in this file is the drift class the repository refuses
    # everywhere else, so the seam is asserted as text.
    CURRENT="the derivation is db.sh's, not a second copy"
    OUT=""
    ERR=""
    RC=0
    if grep -q 'db_path_hash' scripts/serve.sh && grep -q 'db_checkout_root' scripts/serve.sh; then
        ok "serve.sh asks db.sh for both the root and the hash"
    else
        bad "serve.sh no longer reads the root and the hash out of db.sh"
    fi
    # `sha256_of` joins the pattern for the reason test_verify_start.sh gives
    # at the same guard: one helper now spells SHA-256 for the gate family, and
    # a second copy written through it would be invisible to the old pattern.
    if grep -qE 'shasum|sha256sum|sha256_of|openssl dgst|cksum' scripts/serve.sh; then
        bad "serve.sh has grown its own digest ladder — that is the second copy"
    else
        ok "serve.sh carries no digest arithmetic of its own"
    fi
}

case_the_port_is_derived_and_stable
case_two_checkouts_derive_different_ports
case_the_port_says_where_it_came_from
case_a_pin_wins_outright
case_the_window_is_clear_of_every_published_port
case_a_taken_port_is_refused_loudly
case_the_belt_covers_the_derived_port_too
case_a_public_base_url_that_names_another_port_is_announced
case_an_unknown_argument_is_exit_2
case_a_missing_derivation_seam_is_exit_2
case_the_port_derivation_rides_db_sh_rather_than_copying_it

echo "test_serve_port: ${PASSED} passed · ${FAILED} failed"
drive_finished
if [ "$FAILED" -gt 0 ]; then
    echo "!! serve.sh's port is no longer this checkout's own, or a port somebody else" >&2
    echo "   holds is no longer refused. Both halves are the same defect: an agent" >&2
    echo "   verifying ANOTHER CHECKOUT's deployment and being told nothing." >&2
    exit 1
fi
exit 0
