#!/usr/bin/env bash
# The web process: ASGI, because sockets and the MCP mount are not WSGI-shaped.
#
#   ./scripts/serve.sh              # this CHECKOUT's own port — it prints it
#   ./scripts/serve.sh --print-port # the port, on stdout, and nothing else
#   PORT=8100 ./scripts/serve.sh    # somewhere else; a pin wins outright
#
# Everything is here: /api/v1/ (docs at /api/v1/docs), /admin/, /mcp, and websockets.
#
# ---------------------------------------------------------------------------
# THE PORT FOLLOWS THE CHECKOUT, and it is the fourth consumer of one
# derivation rather than a fourth idea about naming.
#
# THE INCIDENT. `PORT="${PORT:-8000}"` gave every checkout on this machine the
# same port, so with five lanes running concurrently the second `serve.sh` lost
# the bind and the FIRST one kept it — and the second lane's agent then drove
# four calls against ANOTHER AGENT'S TREE before a 401 gave it away. An
# anonymous route would never have told it. That is the same class of defect
# at the process layer: a verifier reading an instrument it believes is its own.
#
# THE DERIVATION, AND WHY IT IS NOT NEW. `scripts/db.sh` derives
# `djb_<branch>_<8 hex of the SHA-256 of the checkout's absolute top level>` and
# exports it; `config/settings/base.py` rides that same value for
# `CACHE_KEY_PREFIX` and `TEMPORAL_TASK_QUEUE`; `apps/files/storage.py` derives
# the bucket off the same path. This file asks `db.sh` for the same two things
# it already owns — `db_checkout_root` and `db_path_hash` — so there is no
# second copy of the arithmetic here to drift from the original. Database, task
# queue, cache namespace, bucket, and now the port: one input, five namespaces.
#
# THE RANGE, reasoned rather than picked. 20000-29999 is clear of every port
# `compose.yaml` publishes (5432, 6379, 7233, 8233, 1025, 8025, 8080, 8081,
# 9000, 9001, 7700, 4317, 4318), clear of Linux's ephemeral range (32768-60999)
# and clear of macOS's (49152-65535) — so a derived port can never be taken by
# the stack this repository brings up, and can never be handed out from
# underneath a long-running server as somebody else's outbound source port.
# 10000 slots means ten concurrent checkouts collide with probability ~0.45%,
# which is small and is NOT zero — hence the belt below.
#
# THE BELT, because a derivation is not a guarantee. Before uvicorn is exec'd
# this script asks whether the port is already accepting connections and
# REFUSES loudly if it is, naming the holder — exit 2, the repository's
# could-not-do-the-job code. uvicorn's own `[Errno 48] Address already in use`
# is true and is not enough: it names no holder, it arrives after the reloader
# banner has already scrolled past, and it exits 3, which reads like a crash
# rather than like a collision. A refusal that names the other process is what
# turns "my server died" into "another checkout has this port".
#
# WHAT THIS CANNOT SEE, declared:
#
#   1. THE RACE BETWEEN THE PROBE AND THE BIND. Something can take the port in
#      the microseconds between the check and `exec`. uvicorn's own error is
#      the second net and it is still there; this only makes the COMMON case
#      legible.
#   2. WHOSE CHECKOUT THE HOLDER IS. It names the holder's command, pid and
#      user (`lsof`), not the directory it was started from — and with no
#      `lsof` on PATH it says it could not name the holder rather than
#      pretending the port is free.
#   3. A PORT PINNED BY `PORT=`. A pin wins outright and is never derived over
#      — the same escape `DATABASE_NAME`, `CACHE_KEY_PREFIX` and
#      `TEMPORAL_TASK_QUEUE` all offer, spelled the same way. A STALE pin is
#      therefore two checkouts on one port again, deliberately-looking, and the
#      belt is what catches it.
# ---------------------------------------------------------------------------
set -euo pipefail

cd "$(dirname "$0")/.."

usage() {
    cat <<'USAGE'
usage: serve.sh [--print-port] [-h]

  With no arguments: run the ASGI server on THIS CHECKOUT's own port, derived
  from the checkout's absolute path the way its database name is. A port
  already in use is refused, loudly, naming the holder.

  --print-port   print the port this checkout would serve on and exit 0.
                 Stdout carries the number and nothing else, so a script can
                 read it; everything else goes to stderr.

  PORT=<n> wins outright and nothing is derived.

exit: uvicorn's own status when it runs · 2 refused (port taken, bad argument,
      or the derivation seam could not be read)
USAGE
}

PRINT_PORT=""
while [ $# -gt 0 ]; do
    case "$1" in
    --print-port)
        PRINT_PORT=1
        shift
        ;;
    -h | --help)
        usage
        exit 0
        ;;
    *)
        # A mistyped flag falling through to a silently different run is
        # enforcement misfiring, and that is an exit 2 (scripts/check.sh:71-76).
        echo "!! serve.sh: unknown argument '$1'." >&2
        usage >&2
        exit 2
        ;;
    esac
done

# db.sh is the seam this file derives BOTH the database name and the port
# through, so it is a requirement and not a nicety: serving without it means
# serving somebody else's database on everybody's port. It sets no shell
# options of its own and may read unset variables, so `set +u` around the
# source is the same shape `rung_start.sh:410` and `seam_check.sh:182` use.
if [ ! -r scripts/db.sh ]; then
    echo "!! serve.sh: scripts/db.sh is missing or unreadable." >&2
    echo "   It is the one seam this checkout's database name AND its port are" >&2
    echo "   derived through. Without it this process would serve a guessed" >&2
    echo "   database on a port every other checkout also wants." >&2
    exit 2
fi
set +u
# shellcheck source=scripts/db.sh
. scripts/db.sh
set -u

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.local}"

# The window, as one pair of names so the header's arithmetic has exactly one
# home. `serve_port` takes 4 hex digits (16 bits) off the SAME digest db.sh
# takes 8 from, and folds them into the window.
SERVE_PORT_BASE=20000
SERVE_PORT_SPAN=10000

serve_port() {
    local root digest
    root="$(db_checkout_root)"
    digest="$(db_path_hash "$root" 4)"
    # `16#` and not `0x`: bash's base prefix, and the digest is lower-case hex
    # from every one of db_path_hash's four ladders.
    printf '%d' "$((SERVE_PORT_BASE + 16#$digest % SERVE_PORT_SPAN))"
}

if [ -n "${PORT:-}" ]; then
    PORT_SOURCE="pinned by PORT= in the environment"
else
    PORT="$(serve_port)"
    PORT_SOURCE="derived from this checkout ($(db_checkout_root))"
fi

if [ -n "$PRINT_PORT" ]; then
    printf '%s\n' "$PORT"
    printf 'serve.sh: %s\n' "$PORT_SOURCE" >&2
    exit 0
fi

# --- the disagreement this change creates, said out loud -------
#
# `PUBLIC_BASE_URL` defaults to `http://127.0.0.1:8000`
# (`config/settings/base.py:43`) and is what every absolute URL this product
# emits is built from — the OAuth redirect URI `manage.py zitadel_seed`
# registers, the links in mail, the `PUBLIC_BASE_URL` `scripts/oauth_demo.py`
# and `scripts/mail_demo.py` default to. Deriving the SERVE port without
# touching that value therefore makes the two disagree in every checkout, and
# the symptom is a redirect_uri mismatch at the far end of somebody else's
# login screen — the failure `config/settings/base.py:680` already names.
#
# THE VALUE IS NOT DERIVED HERE, deliberately: a deployment's public URL is a
# fact about the world (a domain, a proxy, a port somebody published), not an
# arithmetic on a checkout path, and `config/settings/` is where it lives.
# What this file owes is that the disagreement is never SILENT — the same
# demotion `db.sh` made for `DATABASE_NAME`, for the same reason and in the
# same place: on stderr, once, only when they actually differ.
announce_public_base_url_disagreement() {
    local line url urlport
    [ -f .env ] || return 0
    line="$(grep -E '^PUBLIC_BASE_URL=' .env 2>/dev/null | tail -1 || true)"
    [ -n "$line" ] || return 0
    url="${line#PUBLIC_BASE_URL=}"
    url="${url%%#*}"
    url="${url%"${url##*[![:space:]]}"}"
    case "$url" in
    \'*\')
        url="${url#\'}"
        url="${url%\'}"
        ;;
    \"*\")
        url="${url#\"}"
        url="${url%\"}"
        ;;
    esac
    [ -n "$url" ] || return 0
    urlport="${url##*:}"
    urlport="${urlport%%/*}"
    # No port in the URL at all (a real domain on 80/443) is not a
    # disagreement this script can judge, so it says nothing.
    case "$urlport" in
    '' | *[!0-9]*) return 0 ;;
    esac
    [ "$urlport" != "$PORT" ] || return 0
    printf 'note: PUBLIC_BASE_URL in .env says port %s and this process is serving %s.\n' \
        "$urlport" "$PORT" >&2
    printf '      Absolute URLs — the Zitadel redirect URI, links in mail, the demo\n' >&2
    printf '      scripts'\'' base URL — are built from PUBLIC_BASE_URL, so a browser login\n' >&2
    printf '      started here comes back to a port nothing is serving. Set it to\n' >&2
    printf '      http://127.0.0.1:%s in .env, or pin PORT=%s.\n' "$PORT" "$urlport" >&2
}
announce_public_base_url_disagreement

# --- the belt ----------------------------------------------------------------
#
# Accepting a connection is the property that matters — a socket bound and
# listening is one this process cannot have — and bash's own /dev/tcp asks it
# without needing a tool to be installed. The two closes are separate words
# because `exec 3<&- 3>&-` is not portable to bash 3.2, which is what macOS
# ships and what every drive here has to run on.
port_is_taken() {
    local port="$1"
    if (exec 3<>"/dev/tcp/127.0.0.1/${port}") 2>/dev/null; then
        exec 3<&-
        exec 3>&-
        return 0
    fi
    return 1
}

# The holder, in its own words. `lsof` is not assumed: an absent one is
# reported as an absence, never as "the port is free".
port_holder() {
    local port="$1"
    if ! command -v lsof >/dev/null 2>&1; then
        printf '     (no `lsof` on PATH — this refusal cannot name the holder)\n'
        return 0
    fi
    lsof -nP -iTCP:"${port}" -sTCP:LISTEN 2>/dev/null | sed 's/^/     /'
}

if port_is_taken "$PORT"; then
    printf '\n!! serve.sh REFUSES: 127.0.0.1:%s is already listening.\n' "$PORT" >&2
    printf '   This port is %s.\n' "$PORT_SOURCE" >&2
    printf '   Serving is not attempted, because the failure this prevents is not a\n' >&2
    printf '   crash — it is a SILENT one. A lost bind used to leave the agent driving\n' >&2
    printf '   calls against ANOTHER CHECKOUT'\''s server, and only an authenticated route\n' >&2
    printf '   ever told it.\n\n' >&2
    printf '   The holder:\n' >&2
    port_holder "$PORT" >&2
    printf '\n   Either stop it, or serve somewhere else deliberately:\n' >&2
    printf '     PORT=%s ./scripts/serve.sh\n' "$((PORT + 1))" >&2
    exit 2
fi

printf 'serve.sh: http://127.0.0.1:%s  (%s)\n' "$PORT" "$PORT_SOURCE"

exec uv run uvicorn config.asgi:application --reload --host 127.0.0.1 --port "${PORT}"
