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
# THE COMPOSE FLOOR — the properties both compose files must carry, asserted
# over the RENDERED file and never over its source text.
#
#   ./deploy/tests/test_compose_floor.sh          run every case
#   ./deploy/tests/test_compose_floor.sh --list   name them and stop
#
# HAND-RUN, like every other drive under `deploy/tests/`. No gate moment
# invokes it; `scripts/check.sh`'s selftest leg prints the whole directory as a
# DECLARED blind spot and expires that block only when every drive in it
# carries `scripts/tests/drive_preamble.sh`. This one does, so it is READY;
# wiring it in alone would be a partial wiring that block cannot describe.
# Its row in `docs/product/instruments.md` is what makes it censused rather
# than merely present.
#
# WHY IT ASSERTS OVER THE RENDER. A grep over the source is a grep over a
# TEMPLATE: `${X:-default}` is not the value the daemon gets, a service the
# file defines under a profile may not be in the stack at all, and a mount
# written in the short `name:/path` form and a mount written long are the same
# fact spelled two ways. `docker compose config` is the one place where the
# substitution has happened, the profiles have been applied and every mount
# has one shape. The env it interpolates with is the drive's own: every
# `${NAME:?...}` slot in the file is DERIVED (a grep for the slot shape, which
# includes digits — `O11Y_PASSWORD_HASH` is why) and answered with a dummy, so
# a slot added to the file tomorrow is answered tomorrow without an edit here.
#
# THE LOSSES IT EXISTS TO REFUSE, every one of them silent:
#
#   1. THE SINK'S STORAGE. The ClickStack all-in-one holds three different
#      things in three different places: HyperDX's own metadata (Mongo, at
#      /data/db), the column store every span and log line actually lands in
#      (/var/lib/clickhouse) and the ClickHouse server's logs
#      (/var/log/clickhouse-server). Only the first was a named volume, so the
#      other two lived in whatever the container brought with it — the image
#      itself declares /var/lib/clickhouse as an anonymous VOLUME, which is a
#      volume nothing names, nothing backs up and no operator can find. The
#      dashboards are metadata and survive; the data behind them does not. A
#      sink that loses its telemetry and keeps its UI looks perfectly healthy.
#   2. THE UNCAPPED LOG. Docker's `json-file` driver has no default size
#      limit, and a compose file that says nothing about logging gets it. On
#      the box Caddy writes a JSON access line per request and the app writes a
#      structured line per request behind it, onto the same root volume
#      Postgres, Zitadel, Temporal and the ClickStack sink are using — so the
#      disk fills and every organ fails at once, which reads as an outage
#      rather than as a log that grew. The cap is one anchor applied to every
#      service, and the population is EVERY SERVICE IN THE RENDER rather than a
#      list somebody keeps in step by hand.
#   3. TEMPORAL'S RETENTION. `temporalio/auto-setup` registers the default
#      namespace with `DEFAULT_NAMESPACE_RETENTION`, whose own default is 24h
#      (read out of /etc/temporal/auto-setup.sh in the pinned image, lines 63
#      and 371). Nothing in the deployment set it, so closed histories aged out
#      after a day — on the box only, because the laptop runs the CLI's dev
#      server instead and never shows it.
#   4. THE MASTER CREDENTIAL HELD FOR LIFE. Zitadel's `start-from-init` does
#      three jobs in one process — create the database and the role, migrate,
#      then serve — so the container that serves the login page for months is
#      the same container that was handed the database's ADMIN credentials and
#      run as root to write a bootstrap file. Both outlive their reason: the
#      credential sits in `docker inspect` and in the process environment of a
#      network-facing service for the life of the box, and root is the uid that
#      service answers the internet as. The privileged work is bounded — it
#      happens once, at first boot — so it belongs in a container that exits,
#      and the census here is over the RENDER because a comment saying "the
#      admin keys are only used at init" is not a thing the daemon reads.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * WHETHER THE SINK ACTUALLY WRITES WHERE UPSTREAM SAYS. The two paths are
#     read off the pinned image (`docker image inspect` shows
#     /var/lib/clickhouse as a declared volume) and off ClickHouse's own
#     defaults for the log directory. A version bump can move either one
#     SILENTLY: the render would still show three named volumes and the data
#     would still be written somewhere else. Only a box with the new image in
#     it can see that.
#   * WHETHER A NAMESPACE THAT ALREADY EXISTS HAS THE RETENTION. auto-setup
#     applies `--retention` at REGISTRATION and leaves an existing namespace
#     untouched (`register_default_namespace`, same file). The one-time
#     operator command is recorded as a comment beside the variable in
#     `deploy/compose.yaml` and `case_the_existing_box_is_a_recorded_operator_act`
#     asserts the comment is there. NOTHING HERE SEES THE BOX.
#   * WHETHER ANY OF IT BOOTS. A render proves shape. The boot sequence, the
#     health checks and the volume actually being writable are staging's.
#   * BACKUP. A named volume is findable and durable across a recreate; it is
#     not a copy. What is backed up, and what deliberately is not, is
#     `deploy/`'s own runbook and not this drive's business.
#   * ANY OVERLAY BEYOND THE SECOND COMPOSE FILE. `deploy/compose.second.yaml`
#     IS rendered here, with the base, and the services it ADDS are derived as
#     a set difference against the base render — it used to be a grep over the
#     overlay's source printing a sentence no code checked, which said "no
#     service of its own" about an overlay that had one. What is still outside
#     this drive is a THIRD `-f` on somebody's command line: the two files the
#     platform ships are the two it renders, and a stack composed from more
#     than those is a stack nothing here has seen.
#   * WHETHER THE DAEMON HONOURS THE CAP. `logging:` in a render is what
#     compose will ask the daemon for. A daemon configured with
#     `log-driver`/`log-opts` it refuses, a driver plugin that is not installed,
#     or a `max-size` the daemon parses differently are all box facts. Only a
#     box can see `docker inspect --format '{{.HostConfig.LogConfig}}'`.
#   * WHETHER 50m × 5 IS THE RIGHT SIZE. The cap is a bounded worst case, not a
#     retention policy: it says the disk cannot fill, and it says nothing about
#     whether an incident's history is still in the file when somebody looks.
#   * WHETHER THE PRIVILEGE SPLIT BOOTS. The render proves that the privileged
#     work is declared as a container that exits and that the long-lived one
#     waits for it. It does not prove that `zitadel init` and `zitadel setup`
#     succeed against a real database, that the one-shots are idempotent on a
#     second `up`, or that `zitadel start` finds everything it needs without the
#     admin credentials — three facts only a box can answer. It also cannot see
#     the UID the long-lived container ends up with when the file declares no
#     `user:` at all: that comes from the image, and the census below asserts
#     only that the file does not ASK for root.
set -euo pipefail

cd "$(dirname "$0")/../.."

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_compose_floor: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   Refusing to run without it." >&2
    exit 2
}
# shellcheck source=scripts/tests/drive_preamble.sh
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
    echo "!! test_compose_floor: $*" >&2
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
    echo "!! unknown argument '$1': test_compose_floor.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

# --- preflight: an instrument that cannot look says so ------------------------
BOX_FILE="deploy/compose.yaml"
LAPTOP_FILE="compose.yaml"
STAGING_MANIFEST="deploy/env.staging.example"
PROD_MANIFEST="deploy/env.prod.example"

command -v python3 >/dev/null 2>&1 || cannot_look "no python3 on PATH — the render is read as JSON"
command -v docker >/dev/null 2>&1 || cannot_look "no docker on PATH — the render is docker compose's own"
docker compose version >/dev/null 2>&1 || cannot_look "docker is on PATH but 'docker compose' does not answer — this drive renders, it never runs a container"
[ -f "$BOX_FILE" ] || cannot_look "$BOX_FILE is not in this tree — there is nothing to render"
[ -f "$LAPTOP_FILE" ] || cannot_look "$LAPTOP_FILE is not in this tree — there is nothing to render"
[ -f "$STAGING_MANIFEST" ] || cannot_look "$STAGING_MANIFEST is not in this tree — the manifest of names is gone"

WORK=$(mktemp -d "${TMPDIR:-/tmp}/djb-test-compose-floor.XXXXXX") || cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'rm -rf "$WORK"'

# THE THREE PATHS, named once. A population, not a count: every case below
# names all three, so one of them going missing is a failure rather than an
# arithmetic coincidence that still clears a `>= 1` floor.
SINK_MONGO="/data/db"
SINK_COLUMNS="/var/lib/clickhouse"
SINK_LOGS="/var/log/clickhouse-server"

# The log cap, named once and compared as a whole. Three values, because a
# `max-size` with no `max-file` rotates into an unbounded number of files and a
# `max-file` with no `max-size` never rotates at all — either half alone is the
# same uncapped disk wearing a `logging:` key.
LOG_DRIVER="json-file"
LOG_MAX_SIZE="50m"
LOG_MAX_FILE="5"
# The floor. Not "at least one service" — a render that lost every service but
# one would clear that and prove nothing. The box defines a dozen organs; ten is
# below the count and above any plausible collapse of the render.
LOG_SERVICE_FLOOR=10
SECOND_FILE="deploy/compose.second.yaml"

# --- the identity system's privilege split, named once ------------------------
# The long-lived service is named; everything else about the split is DERIVED
# from the render. The one-shot population is "every service running the same
# image as the long-lived one, under another name", so a third one-shot added
# tomorrow is judged tomorrow without an edit here — and the image tag itself is
# read out of the render rather than typed, so a bump cannot make this census
# quietly stop finding anybody.
ZITADEL_RUNNING="zitadel"
ZITADEL_ADMIN_PREFIX="ZITADEL_DATABASE_POSTGRES_ADMIN_"
# THE SECOND CREDENTIAL SET, and it is a credential set rather than a
# configuration block: `ZITADEL_FIRSTINSTANCE_ORG_HUMAN_PASSWORD` is the human
# console administrator's password. Every key under this prefix is consumed
# ONCE, by the first-instance bootstrap inside `setup`, and by nothing
# afterwards — so a serving container holding them is the same `docker inspect`
# exposure the admin keys were, with a password that opens the identity system's
# own console rather than its database.
ZITADEL_FIRSTINSTANCE_PREFIX="ZITADEL_FIRSTINSTANCE_"
ZITADEL_BOOTSTRAP_TARGET="/zitadel/bootstrap"
ZITADEL_BOOTSTRAP_VOLUME="zitadel_bootstrap"
ZITADEL_PAT_KEY="ZITADEL_FIRSTINSTANCE_PATPATH"
ZITADEL_PAT_PATH="/zitadel/bootstrap/machine.pat"
# The commands, as the pinned image spells them. Read out of
# `ghcr.io/zitadel/zitadel:v4.17.1 --help` rather than recalled: the image
# offers `init`, `setup`, `start`, `start-from-init` and `start-from-setup`, and
# the last two are the ones that END in a long-lived process after doing
# privileged work in it. The long-lived service must run the first word below
# and none of the rest.
ZITADEL_START_WORD="start"
ZITADEL_COLD_START_WORDS="start-from-init start-from-setup"
# Root, spelled every way compose will accept it.
ROOT_USER_VALUES="0 root 0:0 root:root"

# --- the env the render interpolates with ------------------------------------
# DERIVED from the file, never typed: every `${NAME:?...}` slot answered with a
# dummy. The character class carries 0-9 because names here do
# (`O11Y_PASSWORD_HASH`), and a class that missed one would make this drive
# exit 2 on a file that is perfectly well.
derive_env() {
    local compose_file=$1 out=$2
    shift 2
    # `|| true` on the grep, and it is load-bearing rather than decoration: the
    # laptop file declares NO required slot at all, so a bare grep exits 1 and
    # takes this drive down under `set -e -o pipefail` before a single case has
    # run — a drive that died of its own shell, which is the one thing the
    # preamble's section 5 exists to stop reading as a pass.
    { grep -o '\${[A-Z0-9_]*:?' "$compose_file" || true; } |
        sed 's/\${//; s/:?$//' | sort -u |
        sed 's/$/=compose-floor-dummy/' >"$out"
    local extra
    for extra in "$@"; do
        echo "$extra" >>"$out"
    done
}

# render <compose file> <env file> <json out> [extra compose args...]
# Returns docker compose's own status; the caller decides what that means.
RENDER_RC=0
render() {
    local compose_file=$1 env_file=$2 out=$3
    shift 3
    set +e
    docker compose -f "$compose_file" --env-file "$env_file" "$@" config --format json \
        >"$out" 2>"${out}.err"
    RENDER_RC=$?
    set -e
}

# The census, written once and used by every mount case: it prints one line per
# volume entry of one service, and the shell counts lines rather than trusting
# an adjective. `declared=yes` means the entry's source is a key under the
# top-level `volumes:` — a mount pointing at a volume nobody declared is the
# same silent loss with a name on it.
cat >"${WORK}/census.py" <<'PYTHON'
import json
import sys

render_path, service = sys.argv[1], sys.argv[2]
with open(render_path) as fh:
    rendered = json.load(fh)

services = rendered.get("services", {})
if service not in services:
    print("MISSING-SERVICE %s" % service)
    raise SystemExit(0)

declared = set(rendered.get("volumes", {}) or {})
for entry in services[service].get("volumes", []) or []:
    print(
        "mount target=%s type=%s source=%s declared=%s"
        % (
            entry.get("target", "-"),
            entry.get("type", "-"),
            entry.get("source", "-"),
            "yes" if entry.get("source") in declared else "no",
        )
    )
PYTHON

# The one env value read back out of the render — printed, so a case compares a
# value rather than asserting a grep found something somewhere.
cat >"${WORK}/envvalue.py" <<'PYTHON'
import json
import sys

render_path, service, key = sys.argv[1], sys.argv[2], sys.argv[3]
with open(render_path) as fh:
    rendered = json.load(fh)
service_block = rendered.get("services", {}).get(service)
if service_block is None:
    print("MISSING-SERVICE")
    raise SystemExit(0)
env = service_block.get("environment", {}) or {}
print(env.get(key, "MISSING-KEY"))
PYTHON

# mounts_verdict <json> <service> — writes the census to $CENSUS and sets
# $FOUND to the number of the three sink paths present as DECLARED named
# volumes. Each path is reported by name so a report can paste which one is
# missing.
CENSUS=""
FOUND=0
MISSING=""
mounts_verdict() {
    local render_json=$1 service=$2 path
    CENSUS="${WORK}/census-$(basename "$render_json" .json)-${service}.txt"
    python3 "${WORK}/census.py" "$render_json" "$service" >"$CENSUS"
    FOUND=0
    MISSING=""
    for path in "$SINK_MONGO" "$SINK_COLUMNS" "$SINK_LOGS"; do
        if grep -q "^mount target=${path} type=volume source=[^ ]* declared=yes$" "$CENSUS"; then
            FOUND=$((FOUND + 1))
        else
            MISSING="${MISSING}${MISSING:+ }${path}"
        fi
    done
}

# The log census. One line per service in the render, and the shell counts
# lines. `capped=yes` means the service asks for the whole cap — the driver AND
# both options — so a half-applied anchor is a named failure rather than a
# service that quietly counts.
cat >"${WORK}/logcensus.py" <<'PYTHON'
import json
import sys

render_path, driver, max_size, max_file = sys.argv[1:5]
with open(render_path) as fh:
    rendered = json.load(fh)

for name in sorted(rendered.get("services", {})):
    block = rendered["services"][name].get("logging") or {}
    options = block.get("options") or {}
    got_driver = block.get("driver", "-")
    got_size = options.get("max-size", "-")
    got_file = options.get("max-file", "-")
    capped = (
        got_driver == driver
        and str(got_size) == max_size
        and str(got_file) == max_file
    )
    print(
        "service=%s capped=%s driver=%s max-size=%s max-file=%s"
        % (name, "yes" if capped else "no", got_driver, got_size, got_file)
    )
PYTHON

# log_verdict <json> — sets $LOG_TOTAL (every service in the render), $LOG_CAPPED
# (those asking for the whole cap) and $LOG_UNCAPPED (the names of the rest,
# printed, because "some service" is not a finding).
LOG_CENSUS=""
LOG_TOTAL=0
LOG_CAPPED=0
LOG_UNCAPPED=""
log_verdict() {
    local render_json=$1
    LOG_CENSUS="${WORK}/logcensus-$(basename "$render_json" .json).txt"
    python3 "${WORK}/logcensus.py" "$render_json" \
        "$LOG_DRIVER" "$LOG_MAX_SIZE" "$LOG_MAX_FILE" >"$LOG_CENSUS"
    LOG_TOTAL=$(grep -c '^service=' "$LOG_CENSUS" || true)
    LOG_CAPPED=$(grep -c ' capped=yes ' "$LOG_CENSUS" || true)
    LOG_UNCAPPED=$(
        { grep ' capped=no ' "$LOG_CENSUS" || true; } |
            sed 's/^service=//; s/ .*//' | tr '\n' ' ' | sed 's/ $//'
    )
}

# The shape of ONE service, flattened to lines the shell can grep. Everything a
# privilege census needs — what it runs, as whom, whether it is expected to come
# back, what it waits for and on what condition, which env keys it holds, what it
# mounts — and nothing it does not. Written as lines rather than returned as JSON
# for the same reason the mount census above is: a case that greps a line can
# PRINT the line it did not find.
cat >"${WORK}/serviceshape.py" <<'PYTHON'
import json
import sys

render_path, service = sys.argv[1], sys.argv[2]
with open(render_path) as fh:
    rendered = json.load(fh)

block = rendered.get("services", {}).get(service)
if block is None:
    print("MISSING-SERVICE %s" % service)
    raise SystemExit(0)

command = block.get("command")
if isinstance(command, list):
    command = " ".join(str(part) for part in command)
print("command=%s" % (command if command else "-"))
print("image=%s" % block.get("image", "-"))
print("user=%s" % block.get("user", "-"))
print("restart=%s" % block.get("restart", "-"))
for name, dep in sorted((block.get("depends_on") or {}).items()):
    condition = dep.get("condition", "-") if isinstance(dep, dict) else "-"
    print("depends=%s:%s" % (name, condition))
for key in sorted(block.get("environment") or {}):
    print("envkey=%s" % key)
declared = set(rendered.get("volumes", {}) or {})
for entry in block.get("volumes") or []:
    print(
        "mount=%s source=%s declared=%s"
        % (
            entry.get("target", "-"),
            entry.get("source", "-"),
            "yes" if entry.get("source") in declared else "no",
        )
    )
PYTHON

# The one-shot population and the chain that reaches it. The population is
# DERIVED — every service carrying the long-lived service's own image under
# another name — so a one-shot somebody forgets to wire is still counted, and
# the chain is walked backwards from the long-lived service through
# `service_completed_successfully` edges, so "start waits for the last of them"
# is a walk rather than a name somebody typed.
cat >"${WORK}/oneshots.py" <<'PYTHON'
import json
import sys

render_path, running, admin_prefix, bootstrap_target = sys.argv[1:5]
with open(render_path) as fh:
    rendered = json.load(fh)

services = rendered.get("services", {})
if running not in services:
    print("MISSING-SERVICE %s" % running)
    raise SystemExit(0)

image = services[running].get("image")
population = sorted(
    name
    for name, block in services.items()
    if name != running and block.get("image") == image
)
print("population=%s" % " ".join(population))
for name in population:
    block = services[name]
    env = block.get("environment") or {}
    admin = [key for key in env if key.startswith(admin_prefix)]
    first = [key for key in env if key.startswith("ZITADEL_FIRSTINSTANCE_")]
    targets = {entry.get("target") for entry in (block.get("volumes") or [])}
    print(
        "oneshot=%s restart=%s user=%s admin_keys=%d firstinstance_keys=%d bootstrap=%s"
        % (
            name,
            block.get("restart", "-"),
            block.get("user", "-"),
            len(admin),
            len(first),
            "yes" if bootstrap_target in targets else "no",
        )
    )

# Backwards from the long-lived service, one completed-successfully edge at a
# time. A fork (two such edges from one service) or a cycle stops the walk, and
# the case compares the walk to the population — so either one is a failure
# rather than a walk that quietly stopped early.
chain = []
cursor = running
seen = set()
while True:
    deps = (services.get(cursor) or {}).get("depends_on") or {}
    nxt = [
        name
        for name, dep in deps.items()
        if isinstance(dep, dict)
        and dep.get("condition") == "service_completed_successfully"
    ]
    if len(nxt) != 1 or nxt[0] in seen:
        break
    cursor = nxt[0]
    seen.add(cursor)
    chain.append(cursor)
print("chain=%s" % " ".join(chain))
PYTHON

# shape_of <json> <service> — writes the flattened service to $SHAPE.
SHAPE=""
shape_of() {
    local render_json=$1 service=$2
    SHAPE="${WORK}/shape-$(basename "$render_json" .json)-${service}.txt"
    python3 "${WORK}/serviceshape.py" "$render_json" "$service" >"$SHAPE"
}

# admin_keys_on <shape file> — the ADMIN_* env keys the service holds, by name.
admin_keys_on() {
    { grep "^envkey=${ZITADEL_ADMIN_PREFIX}" "$1" || true; } |
        sed 's/^envkey=//' | tr '\n' ' ' | sed 's/ $//'
}

# firstinstance_keys_on <shape file> — the FIRSTINSTANCE_* env keys, by name.
firstinstance_keys_on() {
    { grep "^envkey=${ZITADEL_FIRSTINSTANCE_PREFIX}" "$1" || true; } |
        sed 's/^envkey=//' | tr '\n' ' ' | sed 's/ $//'
}

# every_firstinstance_key_in <render json> — the union of FIRSTINSTANCE_* keys
# across every service in the render, sorted. This is the POPULATION the
# one-shots are held to: "both one-shots carry all of them" is only a real
# assertion if "all of them" is derived from the file rather than counted
# against whatever the one-shots happen to hold.
every_firstinstance_key_in() {
    python3 -c '
import json, sys
render_path, prefix = sys.argv[1], sys.argv[2]
with open(render_path) as fh:
    rendered = json.load(fh)
keys = set()
for block in rendered.get("services", {}).values():
    keys.update(k for k in (block.get("environment") or {}) if k.startswith(prefix))
print(" ".join(sorted(keys)))
' "$1" "$ZITADEL_FIRSTINSTANCE_PREFIX"
}

# THE OVERLAY, RENDERED WITH THE BASE RATHER THAN GREPPED. An overlay is not a
# file you can read a service list off: compose MERGES it into the base, so the
# only place the real service population exists is the render of the pair. What
# this derives is the difference — the services the pair has that the base alone
# does not — because those are exactly the ones the base's `x-logging` anchor
# was never applied to, and they are invisible to every census that renders the
# base alone.
#
# overlay_verdict <base render json> <overlay file> <env file> <tag> — sets
# $OVERLAY_RC, $OVERLAY_JSON, and $OVERLAY_ADDED (the added service names).
OVERLAY_RC=0
OVERLAY_JSON=""
OVERLAY_ADDED=""
overlay_verdict() {
    local base_json=$1 overlay_file=$2 env_file=$3 tag=$4 profile
    OVERLAY_JSON="${WORK}/overlay-${tag}.json"
    OVERLAY_ADDED=""

    # The pair's own profile list, read from the pair — an overlay may declare a
    # profile the base does not, and a census that used the base's list would
    # not render the service that profile guards.
    local -a pair_profiles=()
    while read -r profile; do
        [ -n "$profile" ] || continue
        pair_profiles+=(--profile "$profile")
    done < <(docker compose -f "$BOX_FILE" -f "$overlay_file" --env-file "$env_file" config --profiles 2>/dev/null)

    set +e
    docker compose -f "$BOX_FILE" -f "$overlay_file" --env-file "$env_file" \
        "${pair_profiles[@]}" config --format json \
        >"$OVERLAY_JSON" 2>"${OVERLAY_JSON}.err"
    OVERLAY_RC=$?
    set -e
    [ "$OVERLAY_RC" = "0" ] || return 0

    OVERLAY_ADDED=$(python3 -c '
import json, sys
base_path, pair_path = sys.argv[1], sys.argv[2]
with open(base_path) as fh:
    base = set(json.load(fh).get("services", {}))
with open(pair_path) as fh:
    pair = set(json.load(fh).get("services", {}))
print(" ".join(sorted(pair - base)))
' "$base_json" "$OVERLAY_JSON")
}

# EVERY PROFILE, DERIVED. `db` carries `profiles: ["laptop"]`, so a bare render
# does not contain it — and a cap census over a render that cannot see a service
# cannot say anything about it. `config --profiles` is compose's own list of
# every profile the file declares, so a profile added tomorrow is rendered
# tomorrow without an edit here.
all_profiles_args() {
    local compose_file=$1 env_file=$2 profile
    PROFILE_ARGS=()
    while read -r profile; do
        [ -n "$profile" ] || continue
        PROFILE_ARGS+=(--profile "$profile")
    done < <(docker compose -f "$compose_file" --env-file "$env_file" config --profiles 2>/dev/null)
}

# --- the renders, taken once --------------------------------------------------
derive_env "$BOX_FILE" "${WORK}/box.env"
render "$BOX_FILE" "${WORK}/box.env" "${WORK}/box.json"
BOX_RENDER_RC=$RENDER_RC
[ "$BOX_RENDER_RC" = "0" ] || {
    echo "-- docker compose said:" >&2
    cat "${WORK}/box.json.err" >&2
    cannot_look "$BOX_FILE does not render (exit ${BOX_RENDER_RC}) — every case below reads that render"
}

derive_env "$LAPTOP_FILE" "${WORK}/laptop.env"
render "$LAPTOP_FILE" "${WORK}/laptop.env" "${WORK}/laptop.json" --profile observability
LAPTOP_RENDER_RC=$RENDER_RC
[ "$LAPTOP_RENDER_RC" = "0" ] || {
    echo "-- docker compose said:" >&2
    cat "${WORK}/laptop.json.err" >&2
    cannot_look "$LAPTOP_FILE does not render under --profile observability (exit ${LAPTOP_RENDER_RC})"
}

# The box again, with every profile it declares — the complete service
# population, which the bare render above is a subset of.
PROFILE_ARGS=()
all_profiles_args "$BOX_FILE" "${WORK}/box.env"
render "$BOX_FILE" "${WORK}/box.env" "${WORK}/box-all.json" "${PROFILE_ARGS[@]}"
BOX_ALL_RENDER_RC=$RENDER_RC
[ "$BOX_ALL_RENDER_RC" = "0" ] || {
    echo "-- docker compose said:" >&2
    cat "${WORK}/box-all.json.err" >&2
    cannot_look "$BOX_FILE does not render with every profile it declares (exit ${BOX_ALL_RENDER_RC})"
}

# --- case 1 -------------------------------------------------------------------
case_the_sink_persists_clickhouse_data_and_logs_on_the_box() {
    CURRENT="the sink's three data paths are declared named volumes (deploy/compose.yaml)"
    mounts_verdict "${WORK}/box.json" clickstack
    if [ "$FOUND" = "3" ]; then
        ok "3/3 — ${SINK_MONGO}, ${SINK_COLUMNS}, ${SINK_LOGS}, each a named volume declared under volumes:"
    else
        bad "${FOUND}/3 — not mounted as a declared named volume: ${MISSING}"
        echo "    -- the service's mounts as rendered:"
        sed 's/^/       /' "$CENSUS"
    fi
}

# --- case 2 -------------------------------------------------------------------
case_the_sink_persists_clickhouse_data_and_logs_on_the_laptop() {
    CURRENT="the sink's three data paths are declared named volumes (compose.yaml, --profile observability)"
    mounts_verdict "${WORK}/laptop.json" clickstack
    if [ "$FOUND" = "3" ]; then
        ok "3/3 — ${SINK_MONGO}, ${SINK_COLUMNS}, ${SINK_LOGS}, each a named volume declared under volumes:"
    else
        bad "${FOUND}/3 — not mounted as a declared named volume: ${MISSING}"
        echo "    -- the service's mounts as rendered:"
        sed 's/^/       /' "$CENSUS"
    fi
}

# --- case 3 -------------------------------------------------------------------
# The control. A census that cannot go red is not a census: this one removes ONE
# of the three mounts from a COPY of the file — its own victim, never the tree —
# and asserts the verdict drops to 2 and names the path it lost.
case_a_copy_with_the_column_store_unmounted_reds_the_census() {
    CURRENT="control: a copy of deploy/compose.yaml with the column store unmounted"
    local copy="${WORK}/copy-compose.yaml"
    grep -v "${SINK_COLUMNS}\$" "$BOX_FILE" >"$copy"
    if ! grep -q "${SINK_COLUMNS}" "$BOX_FILE"; then
        bad "the baseline file does not mount ${SINK_COLUMNS} at all, so nothing was removed — this control cannot speak until case 1 passes"
        return
    fi
    render "$copy" "${WORK}/box.env" "${WORK}/copy.json"
    if [ "$RENDER_RC" != "0" ]; then
        bad "the copy does not render (exit ${RENDER_RC}) — the control proved nothing"
        sed 's/^/       /' "${WORK}/copy.json.err"
        return
    fi
    mounts_verdict "${WORK}/copy.json" clickstack
    if [ "$FOUND" = "2" ] && [ "$MISSING" = "$SINK_COLUMNS" ]; then
        ok "2/3, and it names ${SINK_COLUMNS} — the census reads the render, not the intention"
    else
        bad "${FOUND}/3 missing='${MISSING}' — want 2/3 missing='${SINK_COLUMNS}'"
        sed 's/^/       /' "$CENSUS"
    fi
}

# --- case 4 -------------------------------------------------------------------
case_namespace_retention_defaults_to_thirty_days() {
    CURRENT="temporal's DEFAULT_NAMESPACE_RETENTION with the manifest slot unset"
    local value
    value=$(python3 "${WORK}/envvalue.py" "${WORK}/box.json" temporal DEFAULT_NAMESPACE_RETENTION)
    if [ "$value" = "720h" ]; then
        ok "720h — thirty days, and it is the file's own default rather than the image's 24h"
    else
        bad "DEFAULT_NAMESPACE_RETENTION renders as '${value}' — want 720h (the image's own default is 24h, which is the loss)"
    fi
}

# --- case 5 -------------------------------------------------------------------
case_namespace_retention_reads_the_manifest_slot() {
    CURRENT="temporal's DEFAULT_NAMESPACE_RETENTION with TEMPORAL_NAMESPACE_RETENTION=48h in the env"
    derive_env "$BOX_FILE" "${WORK}/box-48h.env" "TEMPORAL_NAMESPACE_RETENTION=48h"
    render "$BOX_FILE" "${WORK}/box-48h.env" "${WORK}/box-48h.json"
    if [ "$RENDER_RC" != "0" ]; then
        bad "the file does not render with the slot set (exit ${RENDER_RC})"
        sed 's/^/       /' "${WORK}/box-48h.json.err"
        return
    fi
    local value
    value=$(python3 "${WORK}/envvalue.py" "${WORK}/box-48h.json" temporal DEFAULT_NAMESPACE_RETENTION)
    if [ "$value" = "48h" ]; then
        ok "48h written, 48h read — an environment may override by name without editing the file"
    else
        bad "DEFAULT_NAMESPACE_RETENTION renders as '${value}' with TEMPORAL_NAMESPACE_RETENTION=48h — want 48h"
    fi
}

# --- case 6 -------------------------------------------------------------------
case_the_manifest_carries_the_retention_slot() {
    CURRENT="the staging manifest names TEMPORAL_NAMESPACE_RETENTION"
    local line
    line=$(grep -n '^TEMPORAL_NAMESPACE_RETENTION=' "$STAGING_MANIFEST" || true)
    if [ -z "$line" ]; then
        bad "${STAGING_MANIFEST} does not name TEMPORAL_NAMESPACE_RETENTION — the generator fills what the manifest names, so an unnamed slot reaches no environment"
    elif [ "${line#*=}" = "720h" ]; then
        ok "${STAGING_MANIFEST}:${line%%:*} = 720h — the manifest of names carries it, so provision.sh needs no hand table"
    else
        bad "${STAGING_MANIFEST} carries the name at a value this drive did not expect: ${line}"
    fi
    # The prod manifest is THE DELTA and nothing else: it lists names whose
    # VALUES differ. Retention does not differ, so inheriting it is the file's
    # own doctrine. Printed rather than asserted, because both are legal.
    if grep -q '^TEMPORAL_NAMESPACE_RETENTION=' "$PROD_MANIFEST" 2>/dev/null; then
        echo "           census: ${PROD_MANIFEST} OVERRIDES the value (legal; the delta file says why it would)"
    else
        echo "           census: ${PROD_MANIFEST} inherits it (legal, and the delta file's own rule — it lists only names whose values differ)"
    fi
}

# --- case 7 -------------------------------------------------------------------
case_the_existing_box_is_a_recorded_operator_act() {
    CURRENT="the one-time operator command for a namespace that already exists"
    local hits
    hits=$(grep -c 'namespace update' "$BOX_FILE" || true)
    if [ "$hits" = "1" ]; then
        ok "${BOX_FILE} carries it once — auto-setup applies retention at REGISTRATION only, and no drive can see a box"
    else
        bad "${hits} occurrence(s) of 'namespace update' in ${BOX_FILE} — want exactly 1, beside DEFAULT_NAMESPACE_RETENTION"
    fi
}

# --- case 8 -------------------------------------------------------------------
case_both_compose_files_still_validate() {
    CURRENT="both compose files still validate"
    if [ "$BOX_RENDER_RC" = "0" ] && [ "$LAPTOP_RENDER_RC" = "0" ]; then
        ok "docker compose config exits 0 for ${BOX_FILE} and for ${LAPTOP_FILE} (--profile observability)"
    else
        bad "box exit ${BOX_RENDER_RC}, laptop exit ${LAPTOP_RENDER_RC} — want 0 and 0"
    fi
}

# --- case 9 -------------------------------------------------------------------
case_every_service_on_the_box_rotates_its_logs() {
    CURRENT="every service in the box render asks for the log cap"
    log_verdict "${WORK}/box-all.json"
    local anchors
    anchors=$(grep -c '^x-logging:' "$BOX_FILE" || true)
    if [ "$LOG_TOTAL" -lt "$LOG_SERVICE_FLOOR" ]; then
        bad "the render carries ${LOG_TOTAL} service(s), below the floor of ${LOG_SERVICE_FLOOR} — a render this small cannot vouch for a stack"
        sed 's/^/       /' "$LOG_CENSUS"
    elif [ "$LOG_CAPPED" != "$LOG_TOTAL" ]; then
        bad "${LOG_CAPPED}/${LOG_TOTAL} services carry ${LOG_DRIVER} ${LOG_MAX_SIZE}×${LOG_MAX_FILE} — uncapped: ${LOG_UNCAPPED}"
        echo "    -- the log census as rendered:"
        sed 's/^/       /' "$LOG_CENSUS"
    elif [ "$anchors" != "1" ]; then
        bad "${anchors} top-level x-logging: key(s) in ${BOX_FILE} — want exactly 1, so there is one place to change the cap"
    else
        ok "${LOG_CAPPED}/${LOG_TOTAL} (floor ${LOG_SERVICE_FLOOR}), every one of them from the single x-logging anchor"
    fi
    # The overlay, pointed at rather than described. The sentence used to be
    # printed here unconditionally — "no service of its own" was a claim this
    # case did not check, so an overlay that grew one would have been announced
    # as harmless. It is now `case_the_overlay_adds_no_uncapped_service`, which
    # RENDERS the pair and derives the answer.
    echo "           census: ${SECOND_FILE} is judged by its own case below, over the rendered pair"
}

# --- case 10 ------------------------------------------------------------------
# The control. A census that counts a hand list cannot notice a service nobody
# added to the list: this one adds a service the anchor was never applied to — to
# a COPY of the file, its own victim, never the tree — and asserts the census
# drops below its total and names the planted service by name.
case_a_planted_service_without_logging_reds_the_census() {
    CURRENT="control: a copy of ${BOX_FILE} with one service added and no logging: on it"
    local copy="${WORK}/planted-compose.yaml" planted="planted-without-logging"
    awk -v planted="$planted" '
        { print }
        !done && /^services:$/ {
            print "  " planted ":"
            print "    image: busybox:1.37.0"
            print "    command: [\"true\"]"
            done = 1
        }
    ' "$BOX_FILE" >"$copy"
    if ! grep -q "^  ${planted}:$" "$copy"; then
        bad "nothing was planted into the copy — ${BOX_FILE} has no top-level 'services:' line, so this control cannot speak"
        return
    fi
    PROFILE_ARGS=()
    all_profiles_args "$copy" "${WORK}/box.env"
    render "$copy" "${WORK}/box.env" "${WORK}/planted.json" "${PROFILE_ARGS[@]}"
    if [ "$RENDER_RC" != "0" ]; then
        bad "the copy does not render (exit ${RENDER_RC}) — the control proved nothing"
        sed 's/^/       /' "${WORK}/planted.json.err"
        return
    fi
    log_verdict "${WORK}/planted.json"
    if [ "$LOG_CAPPED" = "$((LOG_TOTAL - 1))" ] && [ "$LOG_UNCAPPED" = "$planted" ]; then
        ok "${LOG_CAPPED}/${LOG_TOTAL}, and it names ${planted} — the census reads the render, not a list"
    else
        bad "${LOG_CAPPED}/${LOG_TOTAL} uncapped='${LOG_UNCAPPED}' — want $((LOG_TOTAL - 1))/${LOG_TOTAL} uncapped='${planted}'"
        sed 's/^/       /' "$LOG_CENSUS"
    fi
}

# --- case 10b -----------------------------------------------------------------
case_the_overlay_adds_no_uncapped_service() {
    CURRENT="${SECOND_FILE} adds no service the log cap never reached"
    if [ ! -f "$SECOND_FILE" ]; then
        ok "${SECOND_FILE} is not in this tree — there is no overlay to judge"
        return
    fi
    overlay_verdict "${WORK}/box-all.json" "$SECOND_FILE" "${WORK}/box.env" base
    if [ "$OVERLAY_RC" != "0" ]; then
        bad "${BOX_FILE} + ${SECOND_FILE} does not render together (exit ${OVERLAY_RC}) — an overlay nobody can render is an overlay nobody can judge"
        sed 's/^/       /' "${OVERLAY_JSON}.err"
        return
    fi
    log_verdict "$OVERLAY_JSON"
    if [ "$LOG_TOTAL" -lt "$LOG_SERVICE_FLOOR" ]; then
        bad "the rendered pair carries ${LOG_TOTAL} service(s), below the floor of ${LOG_SERVICE_FLOOR}"
        sed 's/^/       /' "$LOG_CENSUS"
    elif [ "$LOG_CAPPED" != "$LOG_TOTAL" ]; then
        bad "${LOG_CAPPED}/${LOG_TOTAL} services in the rendered pair carry the cap — uncapped: ${LOG_UNCAPPED}"
        echo "    -- services ${SECOND_FILE} ADDS to the base: [${OVERLAY_ADDED:-none}]"
        echo "    -- the log census of the pair as rendered:"
        sed 's/^/       /' "$LOG_CENSUS"
    elif [ -n "$OVERLAY_ADDED" ]; then
        # Capped, but new — worth saying out loud rather than passing silently:
        # the cap reached it, and somebody should know the overlay grew a service.
        ok "${LOG_CAPPED}/${LOG_TOTAL} capped; ${SECOND_FILE} ADDS [${OVERLAY_ADDED}] and the cap reached them too"
    else
        ok "${LOG_CAPPED}/${LOG_TOTAL} capped; ${SECOND_FILE} adds no service of its own — every key in it overrides a service ${BOX_FILE} defines, so each keeps the anchor through compose's map merge"
    fi
}

# --- case 10c -----------------------------------------------------------------
# The control. The sentence this pair of cases replaced was printed
# unconditionally, so it could not have noticed an overlay that grew a service:
# this plants one into a COPY of the overlay — its own victim, never the tree —
# and requires the census to NAME it, as added and as uncapped.
case_a_planted_service_in_the_overlay_reds_the_census() {
    CURRENT="control: a copy of ${SECOND_FILE} declaring a service of its own"
    if [ ! -f "$SECOND_FILE" ]; then
        bad "${SECOND_FILE} is not in this tree — this control has nothing to plant into"
        return
    fi
    local copy="${WORK}/planted-overlay.yaml" planted="planted-overlay-service"
    awk -v planted="$planted" '
        { print }
        !done && /^services:$/ {
            print "  " planted ":"
            print "    image: busybox:1.37.0"
            print "    command: [\"true\"]"
            done = 1
        }
    ' "$SECOND_FILE" >"$copy"
    if ! grep -q "^  ${planted}:$" "$copy"; then
        bad "nothing was planted — ${SECOND_FILE} has no top-level 'services:' line, so this control cannot speak"
        return
    fi
    overlay_verdict "${WORK}/box-all.json" "$copy" "${WORK}/box.env" planted
    if [ "$OVERLAY_RC" != "0" ]; then
        bad "the copy does not render with the base (exit ${OVERLAY_RC}) — the control proved nothing"
        sed 's/^/       /' "${OVERLAY_JSON}.err"
        return
    fi
    log_verdict "$OVERLAY_JSON"
    local missed=""
    case " $OVERLAY_ADDED " in
    *" $planted "*) ;;
    *) missed="${missed}
    -- the added-service derivation read '[${OVERLAY_ADDED}]' and does not name ${planted}" ;;
    esac
    case " $LOG_UNCAPPED " in
    *" $planted "*) ;;
    *) missed="${missed}
    -- the cap census read uncapped='${LOG_UNCAPPED}' and does not name ${planted}" ;;
    esac
    if [ -z "$missed" ]; then
        ok "${LOG_CAPPED}/${LOG_TOTAL}, and it names ${planted} as both ADDED by the overlay and uncapped — the census renders the pair, it does not describe it"
    else
        bad "a control that cannot go red leaves the overlay census unable to fail:${missed}"
        sed 's/^/       /' "$LOG_CENSUS"
    fi
}

# --- case 11 ------------------------------------------------------------------
case_the_running_zitadel_holds_service_creds_only_and_is_not_root() {
    CURRENT="the long-lived ${ZITADEL_RUNNING} serves without the master credential and does not ask for root"
    shape_of "${WORK}/box.json" "$ZITADEL_RUNNING"
    if grep -q '^MISSING-SERVICE' "$SHAPE"; then
        bad "${BOX_FILE} renders no '${ZITADEL_RUNNING}' service at all — there is nothing to judge"
        return
    fi

    local command user admin firstinstance cold word verdicts=""
    command=$(sed -n 's/^command=//p' "$SHAPE")
    user=$(sed -n 's/^user=//p' "$SHAPE")
    admin=$(admin_keys_on "$SHAPE")
    firstinstance=$(firstinstance_keys_on "$SHAPE")

    # (a) what it runs. `start`, and none of the cold-start verbs that do
    #     privileged work inside a process that then stays up.
    case "$command" in
    "${ZITADEL_START_WORD} "* | "$ZITADEL_START_WORD") ;;
    *) verdicts="${verdicts}
    -- command: '${command}' — want it to begin '${ZITADEL_START_WORD}'" ;;
    esac
    for cold in $ZITADEL_COLD_START_WORDS; do
        case " $command " in
        *" $cold "*) verdicts="${verdicts}
    -- command: '${command}' names '${cold}', which does privileged work in the process that then serves" ;;
        esac
    done

    # (b) as whom. Absent is legal and is what the image's own non-root default
    #     means; asking for root is not.
    for word in $ROOT_USER_VALUES; do
        if [ "$user" = "$word" ]; then
            verdicts="${verdicts}
    -- user: '${user}' — the service that answers the internet asks to be root"
        fi
    done

    # (c) what it holds. The finding itself: the database's ADMIN credentials in
    #     the environment of a long-lived, network-facing container.
    if [ -n "$admin" ]; then
        verdicts="${verdicts}
    -- environment: ${admin} — the master credential, in \`docker inspect\` for the life of the box"
    fi

    # (d) the OTHER credential set, and it is the console's rather than the
    #     database's. Every FIRSTINSTANCE_* key is consumed once, by the
    #     first-instance bootstrap inside `setup`; `start` reads none of them.
    #     One of them is the human administrator's password, so a serving
    #     container holding the set is the same exposure as (c) pointed at the
    #     identity system's own console. `ZITADEL_MASTERKEY` is NOT in this set
    #     and must stay: `start` decrypts with it on every boot.
    if [ -n "$firstinstance" ]; then
        verdicts="${verdicts}
    -- environment: ${firstinstance}
       — first-instance bootstrap keys, consumed once by setup and never by start; one of them is the console admin's password"
    fi
    if ! grep -q '^envkey=ZITADEL_MASTERKEY$' "$SHAPE"; then
        verdicts="${verdicts}
    -- environment: ZITADEL_MASTERKEY is ABSENT — \`start\` decrypts with it on every boot, so this is the opposite mistake"
    fi

    if [ -z "$verdicts" ]; then
        ok "command='${command}', user='${user}' (root never asked for), 0 ${ZITADEL_ADMIN_PREFIX}* keys, 0 ${ZITADEL_FIRSTINSTANCE_PREFIX}* keys, ZITADEL_MASTERKEY kept"
    else
        bad "the long-lived service is still privileged:${verdicts}"
    fi
}

# --- case 12 ------------------------------------------------------------------
case_init_and_setup_are_one_shots_and_start_waits_for_them() {
    CURRENT="the privileged work is one-shots that exit, and ${ZITADEL_RUNNING} waits for the last of them"
    local census="${WORK}/oneshots-box.txt"
    python3 "${WORK}/oneshots.py" "${WORK}/box.json" "$ZITADEL_RUNNING" \
        "$ZITADEL_ADMIN_PREFIX" "$ZITADEL_BOOTSTRAP_TARGET" >"$census"
    if grep -q '^MISSING-SERVICE' "$census"; then
        bad "${BOX_FILE} renders no '${ZITADEL_RUNNING}' service at all — there is nothing to judge"
        return
    fi

    local population chain verdicts="" line name
    population=$(sed -n 's/^population=//p' "$census")
    chain=$(sed -n 's/^chain=//p' "$census")

    if [ -z "$population" ]; then
        bad "no service in the render runs ${ZITADEL_RUNNING}'s image under another name — the privileged work has nowhere to have moved to"
        sed 's/^/       /' "$census"
        return
    fi

    # Every member, by name. A population and not a count: a one-shot that lost
    # its `restart: "no"` is a named failure, never an arithmetic coincidence
    # that still clears a ">= 1".
    while IFS= read -r line; do
        name=${line#oneshot=}
        name=${name%% *}
        case "$line" in
        *" restart=no "*) ;;
        *) verdicts="${verdicts}
    -- ${name}: ${line#*"$name" }" ;;
        esac
        case "$line" in
        *" restart=no "*)
            case "$line" in
            *" user=0 "*) ;;
            *) verdicts="${verdicts}
    -- ${name}: does not run as root, so it cannot write the bootstrap file the distroless image's own user cannot — ${line}" ;;
            esac
            case "$line" in
            *" admin_keys=0 "*) verdicts="${verdicts}
    -- ${name}: holds no ${ZITADEL_ADMIN_PREFIX}* key, so it cannot do the privileged work — ${line}" ;;
            esac
            case "$line" in
            *" firstinstance_keys=0 "*) verdicts="${verdicts}
    -- ${name}: holds no ${ZITADEL_FIRSTINSTANCE_PREFIX}* key at all — ${line}" ;;
            esac
            case "$line" in
            *" bootstrap=yes") ;;
            *) verdicts="${verdicts}
    -- ${name}: does not mount ${ZITADEL_BOOTSTRAP_TARGET} — ${line}" ;;
            esac
            ;;
        esac
    done < <(grep '^oneshot=' "$census" || true)

    # EVERY first-instance key, on EVERY one-shot — the population derived from
    # the render rather than counted against what the one-shots happen to hold.
    # It matters that this is all-of-them and not at-least-one: the bootstrap
    # runs in `setup`, and a key that stayed behind on the serving container is
    # both a leak there and a missing input here, which is one edit producing
    # two failures that look unrelated.
    local wanted got
    wanted=$(every_firstinstance_key_in "${WORK}/box.json")
    for name in $population; do
        shape_of "${WORK}/box.json" "$name"
        got=$(firstinstance_keys_on "$SHAPE")
        if [ "$got" != "$wanted" ]; then
            verdicts="${verdicts}
    -- ${name}: does not carry every ${ZITADEL_FIRSTINSTANCE_PREFIX}* key the render declares
       has:  [${got}]
       want: [${wanted}]"
        fi
    done

    # The wait. The chain is walked, so "start waits for the LAST of them" and
    # "every one of them ran first" are the same assertion.
    local chain_sorted population_sorted
    chain_sorted=$(printf '%s\n' $chain | sort | tr '\n' ' ' | sed 's/ $//')
    population_sorted=$(printf '%s\n' $population | sort | tr '\n' ' ' | sed 's/ $//')
    if [ "$chain_sorted" != "$population_sorted" ]; then
        verdicts="${verdicts}
    -- ${ZITADEL_RUNNING} waits, through service_completed_successfully edges, for: [${chain}]
       the one-shot population is:                                              [${population}]"
    fi

    if [ -z "$verdicts" ]; then
        ok "one-shots [${population}], each restart=no user=0 with the admin keys, every ${ZITADEL_FIRSTINSTANCE_PREFIX}* key and ${ZITADEL_BOOTSTRAP_TARGET}; ${ZITADEL_RUNNING} waits on the chain [${chain}]"
    else
        bad "the privilege split is incomplete:${verdicts}"
        echo "    -- the one-shot census as rendered:"
        sed 's/^/       /' "$census"
    fi
}

# --- case 13 ------------------------------------------------------------------
case_the_bootstrap_pat_path_is_unchanged() {
    CURRENT="whoever writes ${ZITADEL_PAT_PATH} mounts the volume its readers look in"
    local holders="" service verdicts="" shape
    # DERIVED: every service in the render that names the PAT path. The readers
    # (`setup.sh`, the runbook's identity step) go to the VOLUME, so a writer
    # that does not mount it writes into a container layer that is deleted the
    # moment the one-shot exits — the PAT gone with no error anywhere.
    while IFS= read -r service; do
        shape_of "${WORK}/box.json" "$service"
        shape="$SHAPE"
        grep -q "^envkey=${ZITADEL_PAT_KEY}$" "$shape" || continue
        holders="${holders}${holders:+ }${service}"
        if ! grep -q "^mount=${ZITADEL_BOOTSTRAP_TARGET} source=${ZITADEL_BOOTSTRAP_VOLUME} declared=yes$" "$shape"; then
            verdicts="${verdicts}
    -- ${service}: names ${ZITADEL_PAT_KEY} and does not mount ${ZITADEL_BOOTSTRAP_VOLUME} at ${ZITADEL_BOOTSTRAP_TARGET}"
            { grep '^mount=' "$shape" || echo "mount=<none>"; } | sed 's/^/       /'
        fi
    done < <(python3 -c 'import json,sys; print("\n".join(sorted(json.load(open(sys.argv[1])).get("services", {}))))' "${WORK}/box.json")

    # The VALUE is read off a WRITER, not off the long-lived service. That is
    # the whole point of the key having moved: `zitadel` no longer names it, so
    # reading it there would be asserting `MISSING-KEY` against a path. The
    # writer is the first holder the census found, and the census is derived.
    local value writer
    writer=${holders%% *}
    value=$(python3 "${WORK}/envvalue.py" "${WORK}/box.json" "$writer" "$ZITADEL_PAT_KEY")

    if [ -z "$holders" ]; then
        bad "no service in the render names ${ZITADEL_PAT_KEY} — the machine PAT the platform authenticates with is written nowhere"
    elif [ -n "$verdicts" ]; then
        bad "the PAT is written where nothing can read it:${verdicts}"
    elif [ "$value" != "$ZITADEL_PAT_PATH" ]; then
        bad "${writer} renders ${ZITADEL_PAT_KEY}='${value}' — want ${ZITADEL_PAT_PATH}, which is the path scripts/setup.sh and the runbook copy out of"
    else
        ok "${ZITADEL_PAT_PATH}, unchanged; written by [${holders}], each mounting ${ZITADEL_BOOTSTRAP_VOLUME}"
    fi
}

# --- case 14 ------------------------------------------------------------------
# The control. A census over the render can only speak if it goes red when the
# thing comes back: this one puts the master credential back into the long-lived
# service — in a COPY of the file, its own victim, never the tree — and asserts
# that case 11's reading NAMES the key it found.
case_a_copy_with_the_master_credential_back_on_the_long_lived_zitadel_reds_the_census() {
    CURRENT="control: a copy of ${BOX_FILE} with the master credential back on ${ZITADEL_RUNNING}"
    local copy="${WORK}/mastercred-compose.yaml"
    # BOTH credential sets, because case 11 now refuses both and a control that
    # plants one leaves the other half unable to fail. One is the database's
    # master password, the other the human console administrator's.
    local planted_admin="${ZITADEL_ADMIN_PREFIX}PASSWORD"
    local planted_first="${ZITADEL_FIRSTINSTANCE_PREFIX}ORG_HUMAN_PASSWORD"
    shape_of "${WORK}/box.json" "$ZITADEL_RUNNING"
    local already=""
    grep -q "^envkey=${planted_admin}$" "$SHAPE" && already="${already}${already:+ }${planted_admin}"
    grep -q "^envkey=${planted_first}$" "$SHAPE" && already="${already}${already:+ }${planted_first}"
    if [ -n "$already" ]; then
        bad "${ZITADEL_RUNNING} already holds ${already}, so planting it changes nothing — this control cannot speak until case 11 passes"
        return
    fi
    awk -v running="  ${ZITADEL_RUNNING}:" -v admin="$planted_admin" -v first="$planted_first" '
        $0 == running { in_service = 1 }
        /^  [a-zA-Z]/ && $0 != running { in_service = 0 }
        { print }
        in_service && !done && /^    environment:/ {
            print "      " admin ": planted-master-credential"
            print "      " first ": planted-console-credential"
            done = 1
        }
    ' "$BOX_FILE" >"$copy"
    if ! grep -q "^      ${planted_admin}: planted-master-credential\$" "$copy" ||
        ! grep -q "^      ${planted_first}: planted-console-credential\$" "$copy"; then
        bad "nothing was planted into the copy — ${BOX_FILE} has no '  ${ZITADEL_RUNNING}:' service with an 'environment:' block, so this control cannot speak"
        return
    fi
    render "$copy" "${WORK}/box.env" "${WORK}/mastercred.json"
    if [ "$RENDER_RC" != "0" ]; then
        bad "the copy does not render (exit ${RENDER_RC}) — the control proved nothing"
        sed 's/^/       /' "${WORK}/mastercred.json.err"
        return
    fi
    shape_of "${WORK}/mastercred.json" "$ZITADEL_RUNNING"
    local admin first missed=""
    admin=$(admin_keys_on "$SHAPE")
    first=$(firstinstance_keys_on "$SHAPE")
    case " $admin " in
    *" $planted_admin "*) ;;
    *) missed="${missed}
    -- ${planted_admin} did not reach the admin census: it read '${admin}'" ;;
    esac
    case " $first " in
    *" $planted_first "*) ;;
    *) missed="${missed}
    -- ${planted_first} did not reach the first-instance census: it read '${first}'" ;;
    esac
    if [ -z "$missed" ]; then
        ok "the census reads both back off the render and names them — ${planted_admin} and ${planted_first}; it is reading the file, not the intention"
    else
        bad "a control that cannot go red leaves case 11 unable to fail:${missed}"
        sed 's/^/       /' "$SHAPE"
    fi
}

case_the_sink_persists_clickhouse_data_and_logs_on_the_box
case_the_sink_persists_clickhouse_data_and_logs_on_the_laptop
case_a_copy_with_the_column_store_unmounted_reds_the_census
case_namespace_retention_defaults_to_thirty_days
case_namespace_retention_reads_the_manifest_slot
case_the_manifest_carries_the_retention_slot
case_the_existing_box_is_a_recorded_operator_act
case_every_service_on_the_box_rotates_its_logs
case_a_planted_service_without_logging_reds_the_census
case_the_overlay_adds_no_uncapped_service
case_a_planted_service_in_the_overlay_reds_the_census
case_the_running_zitadel_holds_service_creds_only_and_is_not_root
case_init_and_setup_are_one_shots_and_start_waits_for_them
case_the_bootstrap_pat_path_is_unchanged
case_a_copy_with_the_master_credential_back_on_the_long_lived_zitadel_reds_the_census
case_both_compose_files_still_validate

echo
echo "test_compose_floor: ${PASSED} passed, ${FAILED} failed"
drive_finished
[ "$FAILED" -eq 0 ] || exit 1
exit 0
