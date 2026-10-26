#!/usr/bin/env bash
. "$(dirname -- "${BASH_SOURCE:-$0}")/bash_only.sh" || exit 2
# scripts/envelope.sh — one measured envelope on throwaway verifier boxes: the stack at a sha, the ladder, the soak, the boxes down.
#
#   scripts/envelope.sh <sha> [--shape prod|one-box|infra] [--type <web box type>] [--organs-type <t>] [--drive-type <t>]
#                             [--tenants K] [--clients N] [--soak-minutes M] [--ladder 1,2,4] [--step-seconds S]
#                             [--rds-env <file>]
#
# From the laptop, at <sha> = HEAD on a clean tree, with AWS_PROFILE, DJB_DEPLOY_NAMESPACE and
# DJB_VERIFIER_REGION exported (scripts/verifier_box.sh refuses without them).
#
# --shape prod (the default; the production shape, load-acceptable plan § Rulings 2): three boxes in
# the verifier group. The ORGANS box (default m7g.xlarge) runs every organ of deploy/compose.yaml
# --profile laptop, each published on its private address (deploy/load/compose.organs.yaml); the WEB
# box (default c7g.xlarge, non-burstable) builds the three images and runs web, worker (its compose
# replicas, `DJB_WORKER_PROCESSES`), frontend and caddy against them (deploy/load/compose.web.yaml),
# reads the pool's processes off `compose config`, migrates, grants, seeds K tenants and mints one
# token per client, N over K; the DRIVE box (default t4g.medium) runs deploy/load/drive.py in the
# web image's base interpreter against the web box's private address. Before any of that, each box
# probes the ports the others need: a port the group drops is the owner's one ingress rule, printed
# as an OWNER line, and the run stops there (exit 2, boxes down). Before the ladder, capacity.md § 7's
# pre-spend gate reads § 2a's census on the organs box and a principal over its bound voids the run.
# Each box samples its own CPU (host_cpu, organs_cpu, client_cpu); `drive.py judge` joins the three
# files to the run's own and writes the ENVELOPE and SOAK lines into docs/runbooks/capacity.md § 9.
# The organs box's Zitadel is the web box's issuer (its bootstrap PAT in the env file, reached through
# Caddy and a relay on the one port the group admits that no organ holds), so a seeded tenant's
# identity home lands. Every box that holds the stack first stops the box image's own stack (compose.yaml's
# project, up since the bake), and each stack sampler writes a `docker ps` census beside its samples; the
# recorded line says `host=bare` only when no box's census names anything but the envelope's own project.
# The socket probe (deploy/load/realtime_lag.py) holds 50 bearer sockets from the
# drive box in the soak's last window and once idle after it; both REALTIME lines are recorded too.
#
# --shape one-box (default t4g.large): one box, the stack and the drive on it
# in caddy's network namespace, one DRIVE_TOKEN under `acme`; the socket probe from the same place.
#
# --shape infra (the web box defaults to provision.sh infra's own DJB_INSTANCE_TYPE default): the shape
# `deploy/provision.sh infra` deploys — one box holding every service of deploy/compose.yaml but `db`,
# Postgres on the RDS instance `infra` made, the drive on a second box. `--rds-env` is the env file
# `provision.sh env-file` wrote for that environment, its DATABASE_HOST filled from infra's last lines:
# its database keys, its class and the worker count derived from it are laid over the box's own laptop
# env file, so the pool is the class's. The web box must reach RDS on 5432; the script probes that first
# and, when the database's group drops it, prints the owner's one ingress command and stops. The web box
# also reconciles the alert route (deploy/observability/alerts/apply.py) onto a dummy receiver
# (alerts/compose.sink.yaml) and prints every post it received after the soak as ALERTS lines.
#
# Exit 0 recorded · 2 refused or could not look, every box taken down either way (a box this script
# could not take down is named on stderr with the command that does).
#
# does-not-cover: a product's topology beyond --shape infra — a separate Redis and the pool's own depth are a product's run on its own stage; infra's RDS shape is measured here.
# does-not-cover: client-side saturation on --shape one-box — the drive runs on the box, so a knee may be the client's; the line's topology says so.
# does-not-cover: the cost — the wall is printed; the price is the instance types', read off `scripts/verifier_box.sh census` or the AWS price list.
# does-not-cover: Zitadel on --shape one-box — only the production shape wires the issuer, so a one-box run's identity homes still fail.

set -euo pipefail
# shellcheck source=scripts/gate_refuse.sh
. "$(dirname -- "${BASH_SOURCE[0]}")/gate_refuse.sh" || exit 2
refuse_if_piped envelope
# shellcheck source=scripts/ci_stack.sh
. "$(dirname -- "${BASH_SOURCE[0]}")/ci_stack.sh" || exit 2
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VB="$ROOT/scripts/verifier_box.sh"
PY="$(checkout_python "$ROOT")" || gate_die "" "envelope: no ${ROOT}/.venv interpreter — ./scripts/setup.sh provisions it"
CAPACITY="$ROOT/docs/runbooks/capacity.md"
MARK_END="<!-- recorded-knees end -->"
TENANT=acme
TOPOLOGY_PROD="web-box-organs-box-drive-off-box"
TOPOLOGY_INFRA="web-box-rds-drive-off-box"
# The database keys an --rds-env file lays over the box's env file: the pool, the credentials, TLS, the class.
SHAPE_KEYS="DATABASE_ POSTGRES_ PGSSLMODE ZITADEL_DATABASE_ TEMPORAL_SQL_TLS DJB_RDS_CLASS DJB_WORKER_PROCESSES"
PSQL_HELPER="envelope-psql"
APP_SERVICES="web worker frontend caddy"
NEAR_ORGANS="db redis meilisearch temporal minio"
NOT_ORGANS="web worker frontend caddy readyz-prober"
ORGAN_PORTS="4318 5432 6379 7233 7700 9000"
DRIVE_IMAGE="python:3.12-slim"
PROBE_SOCKETS=50
PROBE_EVENTS=20
PROBE_PREFIX="realtime-probe"
# A box the laptop is not polling is touched this often, inside the idle wall box_up asks for (60 min).
FRESH_EVERY=600
CENSUS_SQL="SELECT datname, usename, count(*), count(*) FILTER (WHERE state = 'active'), count(*) FILTER (WHERE state = 'idle'), coalesce(max(EXTRACT(epoch FROM now() - state_change)) FILTER (WHERE state = 'idle')::int, 0) FROM pg_stat_activity WHERE backend_type = 'client backend' AND pid <> pg_backend_pid() GROUP BY datname, usename ORDER BY 3 DESC, 1, 2"
# RDS holds its own `rdsadmin` sessions on its own database: the vendor's principal, which nothing here declares.
RDS_PRINCIPAL="AND usename <> 'rdsadmin'"
CENSUS_SQL_RDS="${CENSUS_SQL/pg_backend_pid()/pg_backend_pid() $RDS_PRINCIPAL}"


usage() {
    awk 'NR > 2 && /^#/ { sub(/^# ?/, ""); print; next } NR > 2 { exit }' "$0"
    exit "${1:-2}"
}

# --- the box halves ----------------------------------------------------------

# The box image's own stack stopped, its idle CPU at the stop printed: it would otherwise sit in the box's CPU key.
image_stack_stopped() {
    local project ids
    project="$(awk '$1 == "name:" { print $2; exit }' compose.yaml)"
    [ -n "$project" ] || gate_die "" "envelope: compose.yaml names no project for the box image's own stack"
    ids="$(docker ps -q --filter "label=com.docker.compose.project=$project")" || gate_die "" "envelope: docker ps refused"
    if [ -z "$ids" ]; then
        echo "envelope:       the box image's own stack ($project): nothing running"
        return 0
    fi
    # shellcheck disable=SC2086  # one id per word
    docker stats --no-stream --format '{{.Name}} {{.CPUPerc}}' $ids >"$W/image-stack.txt" 2>&1 || true
    # shellcheck disable=SC2086
    docker stop $ids >"$W/image-stop.log" 2>&1 || gate_die "" "envelope: the box image's own stack would not stop" "$(tail -5 "$W/image-stop.log")"
    [ -z "$(docker ps -q --filter "label=com.docker.compose.project=$project")" ] ||
        gate_die "" "envelope: the box image's own stack ($project) is still running after the stop"
    echo "envelope:       the box image's own stack ($project) stopped: $(awk '{ n++; c += $2; s = s " " $1 "=" $2 } END { printf "%d containers, %.1f%% of one core at the stop:%s", n, c, s }' "$W/image-stack.txt")"
}

box_start() {
    W="$HOME/envelope"
    mkdir -p "$W/out"
    chmod 777 "$W" "$W/out"
    rm -f "$W/rc"
    trap 'echo "$?" > "$W/rc"' EXIT
    cd "$ROOT"
    echo "envelope: box $(hostname) · $(nproc) vCPU · $(awk '/MemTotal/ { printf "%.1f GiB", $2 / 1048576 }' /proc/meminfo) · $1"
}

env_file() {
    ./deploy/provision.sh env-file deploy/.env laptop >"$W/env-file.log" 2>&1 || {
        cat "$W/env-file.log" >&2
        gate_die "" "envelope: provision.sh env-file refused"
    }
    local key secret
    key="load$(head -c 6 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    secret="$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    "$PY" deploy/envfile.py set deploy/.env AWS_STORAGE_BUCKET_NAME envelope-media
    "$PY" deploy/envfile.py set deploy/.env AWS_S3_ENDPOINT_URL http://minio:9000
    "$PY" deploy/envfile.py set deploy/.env AWS_S3_REGION_NAME us-east-1
    "$PY" deploy/envfile.py set deploy/.env AWS_ACCESS_KEY_ID "$key"
    "$PY" deploy/envfile.py set deploy/.env AWS_SECRET_ACCESS_KEY "$secret"
    # The image's uid is not this box user's, and the file seam reads the file from inside it; a throwaway box only.
    chmod 644 deploy/.env
}

box_env() {
    DJB_IMAGE_TAG="$(./deploy/provision.sh image-tag)"
    export DJB_IMAGE_TAG
    DJB_ENVELOPE_MINIO_IMAGE="$(awk '$1 == "image:" && $2 ~ /\/minio:/ { print $2; exit }' compose.yaml)"
    [ -n "$DJB_ENVELOPE_MINIO_IMAGE" ] || gate_die "" "envelope: compose.yaml names no minio image to overlay"
    export DJB_ENVELOPE_MINIO_IMAGE
    DJB_ENVELOPE_CADDY_IMAGE="$(awk '$1 == "image:" && $2 ~ /^caddy:/ { print $2; exit }' deploy/compose.yaml)"
    [ -n "$DJB_ENVELOPE_CADDY_IMAGE" ] || gate_die "" "envelope: deploy/compose.yaml names no caddy image for the relay"
    export DJB_ENVELOPE_CADDY_IMAGE
    C=(docker compose --env-file deploy/.env -f deploy/compose.yaml -f deploy/load/compose.envelope.yaml)
    if [ "${1:-}" = infra ]; then
        # No laptop profile: every service but `db`, as `provision.sh up` runs on a box, the object store published.
        [ -s "$W/compose.infra.yaml" ] || gate_die "" "envelope: no $W/compose.infra.yaml — on_box_infra_web writes it"
        C+=(-f "$W/compose.infra.yaml" -f deploy/observability/alerts/compose.sink.yaml)
    else
        [ -z "${1:-}" ] || C+=(-f "deploy/load/compose.$1.yaml")
        C+=(--profile laptop)
    fi
    set -a
    # shellcheck source=/dev/null
    . deploy/.env
    set +a
}

build_images() {
    local target
    for target in web worker frontend; do
        docker build --target "$target" -t "$(./deploy/provision.sh image-ref "$target")" . \
            >"$W/build-$target.log" 2>&1 || {
            tail -40 "$W/build-$target.log" >&2
            gate_die "" "envelope: the $target image would not build"
        }
    done
}

make_bucket() {
    # shellcheck disable=SC2016
    "${C[@]}" exec -T minio sh -c 'mc alias set box http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null && mc mb --ignore-existing box/envelope-media' \
        >"$W/bucket.log" 2>&1 || gate_die "" "envelope: the object store refused the bucket" "$(cat "$W/bucket.log")"
}

migrate_and_grant() {
    local -a apply=("$@")
    "${C[@]}" run --rm -T -e DATABASE_USER="$POSTGRES_USER" -e DATABASE_PASSWORD="$POSTGRES_PASSWORD" \
        oneoff python manage.py migrate --noinput >"$W/migrate.log" 2>&1 || gate_die "" "envelope: migrate refused" "$(tail -20 "$W/migrate.log")"
    "${C[@]}" run --rm -T oneoff python /deploy/grants.sql.py --role "$DATABASE_USER" --create-role \
        >"$W/grants.sql" 2>"$W/grants.err" || gate_die "" "envelope: grants.sql.py refused" "$(cat "$W/grants.err")"
    "${apply[@]}" -U "$POSTGRES_USER" -d "$DATABASE_NAME" -v ON_ERROR_STOP=1 -f - <"$W/grants.sql" >"$W/grants.log" 2>&1 ||
        gate_die "" "envelope: the grants did not apply" "$(tail -20 "$W/grants.log")"
}

wait_ready() {
    local waited=0
    until curl -skf https://localhost/readyz >/dev/null 2>&1; do
        waited=$((waited + 5))
        [ "$waited" -lt 600 ] || gate_die "" "envelope: readyz never answered 200 in 600s" "$(curl -sk https://localhost/readyz 2>&1 | head -c 400)"
        sleep 5
    done
    echo "envelope:       readyz $(curl -sk https://localhost/readyz)"
}

# The pool's processes, read off the rendered compose (the soak's budget), and the app containers that hold them.
pool_processes() {
    "${C[@]}" config --format json >"$W/compose-config.json" 2>"$W/compose-config.err" ||
        gate_die "" "envelope: compose config would not render" "$(tail -5 "$W/compose-config.err")"
    "$PY" deploy/load/drive.py processes --compose "$W/compose-config.json" >"$W/processes.txt" ||
        gate_die "" "envelope: drive.py processes could not read the rendered compose"
    echo "envelope:       pool processes $(cat "$W/processes.txt") (docker compose config: deploy.replicas)"
    "${C[@]}" ps --format '{{.Name}} {{.Service}} {{.Status}}' web worker | sed 's/^/envelope:       ps /'
}

caddy_root() {
    "${C[@]}" exec -T caddy cat /data/caddy/pki/authorities/local/root.crt >"$W/caddy-root.crt" 2>/dev/null ||
        gate_die "" "envelope: could not read caddy's internal root certificate"
}

# Mint one user and one token per socket probe credential under $TENANT, as many as the join bound needs.
probe_credentials() {
    local cap n
    cap="$("$PY" -c 'import sys; sys.path.insert(0, "deploy/load"); from realtime_lag import declared_socket_caps as d; print(d("config/settings/base.py")[0])')" ||
        gate_die "" "envelope: could not read the socket join bound"
    n=$(((PROBE_SOCKETS + cap - 1) / cap))
    (umask 077 && "${C[@]}" run --rm -T -e ENVELOPE_SLUGS="$TENANT" -e ENVELOPE_CLIENTS="$n" -e ENVELOPE_PREFIX="$PROBE_PREFIX" \
        oneoff python manage.py shell <deploy/load/clients.py >"$W/probe.log" 2>"$W/probe.err") ||
        gate_die "" "envelope: deploy/load/clients.py refused the probe's credentials" "$(tail -20 "$W/probe.err")"
    (umask 077 && awk -F '\t' '$1 == "CRED" { print $2 "\t" $3 }' "$W/probe.log" | python3 -c 'import json, sys
json.dump([{"tenant": t, "token": k} for t, k in (line.rstrip("\n").split("\t") for line in sys.stdin if line.strip())], sys.stdout)' >"$W/probe-credentials.json")
    rm -f "$W/probe.log"
    echo "envelope:       $n probe credentials under $TENANT (join bound $cap per credential)"
}

# A chrony `System time` line on stdin as a signed offset (`+0.000012s`), or nothing when it holds none.
chrony_offset() {
    awk '/System time/ && / seconds (fast|slow) / { for (i = 1; i <= NF; i++) if ($i ~ /^[0-9.]+$/) v = $i; if (v != "") printf "%s%ss", ($0 ~ / slow /) ? "-" : "+", v; exit }'
}

# One REALTIME line under <load>: the probe's own line, or could-not-look with its reason (house rule 35).
realtime_probe() {
    local load="$1" client="$2" out rc=0 why
    shift 2
    out="$W/realtime-$load.log"
    "$@" --sockets "$PROBE_SOCKETS" --events "$PROBE_EVENTS" --load "$load" --client "$client" >"$out" 2>&1 || rc=$?
    if [ "$rc" -eq 0 ] && grep -q '^realtime=' "$out"; then
        echo "== REALTIME · $(grep '^realtime=' "$out" | tail -1)"
        return 0
    fi
    why="$(sed -n 's/.*COULD NOT LOOK: //p' "$out" | tail -1 | tr ' |' '-_' | cut -c1-160)"
    echo "== REALTIME · realtime=could-not-look sockets=$PROBE_SOCKETS events=$PROBE_EVENTS load=$load client=$client exit=$rc why=${why:-unstated}"
    tail -20 "$out" >&2
}

# The soak (SOAK) in the background, the probe (PROBE) inside its last window, then the probe idle.
soak_and_probe() {
    local minutes="$1" half="$2" client="$3" window lead soak rc=0
    window="$(awk '$1 == "SOAK_WINDOW_SECONDS" { print int($3); exit }' deploy/load/drive.py)"
    [[ "$window" =~ ^[0-9]+$ ]] || gate_die "" "envelope: drive.py names no SOAK_WINDOW_SECONDS"
    "${SOAK[@]}" &
    soak=$!
    if [ $((minutes * 60)) -gt "$window" ]; then lead=$((minutes * 60 - window / 2)); else lead=$((minutes * 30)); fi
    sleep "$lead"
    echo "envelope:       the socket probe at ${lead}s into the soak (its last window, conc-$half)"
    realtime_probe "conc-$half" "$client" "${PROBE[@]}"
    wait "$soak" || rc=$?
    [ "$rc" -eq 0 ] || return "$rc"
    echo "envelope:       the socket probe idle, after the soak"
    realtime_probe idle "$client" "${PROBE[@]}"
}

half_of_the_knee() {
    python3 -c 'import glob, json, sys
m = json.load(open(sorted(glob.glob(sys.argv[1] + "/drive-*Z.json"))[-1]))
k = m["knee"]
c = k["concurrency"] if k.get("verdict") == "found" else m["ladder"][-1]
print(max(1, c // 2))' "$W/out"
}

on_box_one() {
    local sha="$1" minutes="$2" ladder="$3" step="$4" size="$5"
    box_start "one-box · sha $sha"
    image_stack_stopped

    echo "envelope: [1/9] env file, with this box's object store"
    env_file

    echo "envelope: [2/9] the three images, built here at this tree"
    box_env
    build_images

    echo "envelope: [3/9] the database and the object store, migrated and granted"
    "${C[@]}" up -d --wait db minio >"$W/wait.log" 2>&1 ||
        gate_die "" "envelope: db and minio never reported healthy" "$(tail -20 "$W/wait.log")" "$("${C[@]}" logs --tail 10 db minio 2>&1)"
    make_bucket
    migrate_and_grant "${C[@]}" exec -T -e PGPASSWORD="$POSTGRES_PASSWORD" -e DATABASE_USER="$DATABASE_USER" \
        -e DATABASE_PASSWORD="$DATABASE_PASSWORD" db psql

    echo "envelope: [4/9] the stack up, the app as its own role"
    ./deploy/provision.sh up --profile laptop -f "$ROOT/deploy/load/compose.envelope.yaml" \
        >"$W/up.log" 2>&1 || {
        tail -20 "$W/up.log" >&2
        "${C[@]}" ps -a --format '{{.Service}} {{.Status}}' >&2 || true
        "${C[@]}" logs --tail 30 web >&2 2>&1 || true
        gate_die "" "envelope: provision.sh up refused"
    }
    wait_ready
    pool_processes

    echo "envelope: [5/9] seed and a token"
    "${C[@]}" run --rm -T oneoff python manage.py seed --force >"$W/seed.log" 2>&1 || gate_die "" "envelope: seed refused" "$(tail -20 "$W/seed.log")"
    "${C[@]}" run --rm -T oneoff python manage.py issue_token --email owner@example.com --tenant "$TENANT" \
        --name envelope --scope '*' >"$W/token.log" 2>"$W/token.err" || gate_die "" "envelope: issue_token refused" "$(tail -20 "$W/token.err")"
    DRIVE_TOKEN="$(awk '/Copy it now/ { print last; exit } NF { last = $0 }' "$W/token.log")"
    export DRIVE_TOKEN
    [ -n "$DRIVE_TOKEN" ] || gate_die "" "envelope: issue_token printed no token"
    caddy_root

    local caddy web_image
    caddy="$("${C[@]}" ps -q caddy)"
    web_image="$(./deploy/provision.sh image-ref web)"
    local -a D=(docker run --rm --network "container:$caddy" -e DRIVE_TOKEN -e PYTHONUNBUFFERED=1
        -v "$ROOT:/src:ro" -v "$W:/work" --entrypoint python "$web_image" /src/deploy/load/drive.py)
    local -a TARGET=(--base-url https://localhost --tenant "$TENANT" --out /work/out --ca-bundle /work/caddy-root.crt)

    echo "envelope: [6/9] drive.py prepare"
    "${D[@]}" prepare "${TARGET[@]}" || gate_die "" "envelope: drive.py prepare refused"

    echo "envelope: [7/9] the ladder, sampled"
    bash deploy/load/utilization.sh --census "$W/census-one-box.txt" --own-project "$COMPOSE_PROJECT_NAME" \
        --psql "${C[*]} exec -T db psql -U $POSTGRES_USER -d $DATABASE_NAME" \
        --redis-cli "${C[*]} exec -T redis redis-cli" --temporal "${C[*]} exec -T temporal temporal --address temporal:7233" \
        --task-queue "${TEMPORAL_TASK_QUEUE:?the env file names no TEMPORAL_TASK_QUEUE}" >"$W/util.jsonl" 2>"$W/util.err" &
    local sampler=$!
    local -a LADDER=()
    [ "$ladder" = "default" ] || LADDER=(--ladder "$ladder")
    local rc=0
    "${D[@]}" run "${TARGET[@]}" --sha "$sha" --utilization /work/util.jsonl --size "$size" \
        --topology compose-one-host-drive-on-box --step-seconds "$step" "${LADDER[@]}" || rc=$?
    kill -0 "$sampler" 2>/dev/null || gate_die "" "envelope: the sampler stopped during the ladder" "$(cat "$W/util.err")"
    [ "$rc" -eq 0 ] || gate_die "" "envelope: drive.py run exited $rc — no soak is judged over an unjudged ladder"

    local half
    half="$(half_of_the_knee)"
    echo "envelope: [8/9] the soak at concurrency $half (half the knee) for $minutes min"
    echo "envelope: [9/9] realtime: $PROBE_SOCKETS sockets in the soak's last window, then idle"
    probe_credentials
    SOAK=("${D[@]}" soak "${TARGET[@]}" --concurrency "$half" --minutes "$minutes" --utilization /work/util.jsonl
        --processes "$(cat "$W/processes.txt")")
    PROBE=(docker run --rm --network "container:$caddy" -v "$ROOT:/src:ro" -v "$W:/work" --entrypoint python
        "$web_image" /src/deploy/load/realtime_lag.py --credentials /work/probe-credentials.json
        --base-url https://localhost --ca-bundle /work/caddy-root.crt)
    rc=0
    soak_and_probe "$minutes" "$half" one-box || rc=$?
    kill "$sampler" 2>/dev/null || true
    [ "$rc" -eq 0 ] || gate_die "" "envelope: drive.py soak exited $rc"
    echo "envelope: the box half is done"
}

on_box_organs() {
    local ip="$1"
    box_start "organs · $ip"
    image_stack_stopped
    export DJB_ENVELOPE_ORGANS_IP="$ip"

    echo "envelope: [organs 1/4] env file, with this box's object store"
    env_file
    box_env organs

    echo "envelope: [organs 2/4] the organs the app dials, healthy, on $ip"
    # shellcheck disable=SC2086  # the service lists are space-separated and must split
    "${C[@]}" up -d --wait $NEAR_ORGANS >"$W/wait.log" 2>&1 ||
        gate_die "" "envelope: the near organs never reported healthy" "$(tail -20 "$W/wait.log")"
    make_bucket

    echo "envelope: [organs 3/4] the rest of the organs"
    local services rendered doors rest="" s
    services="$("${C[@]}" config --services)" || gate_die "" "envelope: compose could not list the services"
    rendered="$("${C[@]}" config)" || gate_die "" "envelope: compose could not render the stack"
    # The `compose run` doors, by the one reader (scripts/ci_stack.sh), never typed here.
    doors="$(compose_once_members <<<"$rendered" | awk -F '\t' '$1 == "door" { printf " %s", $2 }')"
    for s in $services; do
        case " $NEAR_ORGANS $NOT_ORGANS $doors " in *" $s "*) ;; *) rest="$rest $s" ;; esac
    done
    # shellcheck disable=SC2086
    "${C[@]}" up -d $rest >"$W/up.log" 2>&1 || gate_die "" "envelope: the organs would not start" "$(tail -20 "$W/up.log")"

    echo "envelope: [organs 4/4] the sampler, once Temporal's namespace answers"
    local waited=0
    until "${C[@]}" exec -T temporal temporal --address temporal:7233 operator namespace describe --namespace default >"$W/namespace.log" 2>&1; do
        waited=$((waited + 5))
        [ "$waited" -lt 300 ] || gate_die "" "envelope: Temporal's default namespace never answered in 300s" "$(tail -5 "$W/namespace.log")"
        sleep 5
    done
    echo "envelope:       Zitadel's bootstrap PAT into the env file: the web box's issuer"
    waited=0
    until "${C[@]}" cp zitadel:/zitadel/bootstrap/machine.pat "$W/machine.pat" >"$W/pat.log" 2>&1 && [ -s "$W/machine.pat" ]; do
        waited=$((waited + 5))
        [ "$waited" -lt 300 ] || gate_die "" "envelope: Zitadel wrote no bootstrap PAT in 300s" "$(tail -5 "$W/pat.log")" "$("${C[@]}" logs --tail 10 zitadel 2>&1)"
        sleep 5
    done
    "$PY" deploy/envfile.py set deploy/.env ZITADEL_PAT "$(tr -d '\r\n' <"$W/machine.pat")"
    rm -f "$W/machine.pat"
    nohup bash deploy/load/utilization.sh --cpu-key organs_cpu --census "$W/census-organs.txt" --own-project "$COMPOSE_PROJECT_NAME" \
        --psql "${C[*]} exec -T db psql -U $POSTGRES_USER -d $DATABASE_NAME" \
        --redis-cli "${C[*]} exec -T redis redis-cli" --temporal "${C[*]} exec -T temporal temporal --address temporal:7233" \
        --task-queue "${TEMPORAL_TASK_QUEUE:?the env file names no TEMPORAL_TASK_QUEUE}" >"$W/util-organs.jsonl" 2>"$W/util.err" </dev/null &
    install -m 600 deploy/.env "$W/env"
    echo "envelope: the organs half is done"
}

on_box_census() {
    local ip="$1"
    cd "$ROOT"
    export DJB_ENVELOPE_ORGANS_IP="$ip"
    box_env organs
    "${C[@]}" exec -T db psql -U "$POSTGRES_USER" -d postgres -X -A -t -F '|' -c "$CENSUS_SQL"
}

# K tenants seeded, one user and one token per client, N over K, into $W/credentials.json; then the probe's.
seed_and_mint() {
    local tenants="$1" clients="$2"
    local -a slugs=("$TENANT")
    local n
    for ((n = 2; n <= tenants; n++)); do slugs+=("load$n"); done
    for n in "${slugs[@]}"; do
        "${C[@]}" run --rm -T oneoff python manage.py seed --force --tenant "$n" >"$W/seed-$n.log" 2>&1 ||
            gate_die "" "envelope: seed refused for $n" "$(tail -20 "$W/seed-$n.log")"
    done
    local joined
    joined="$(IFS=,; echo "${slugs[*]}")"
    (umask 077 && "${C[@]}" run --rm -T -e ENVELOPE_SLUGS="$joined" -e ENVELOPE_CLIENTS="$clients" oneoff \
        python manage.py shell <deploy/load/clients.py >"$W/clients.log" 2>"$W/clients.err") ||
        gate_die "" "envelope: deploy/load/clients.py refused" "$(tail -20 "$W/clients.err")"
    (umask 077 && awk -F '\t' '$1 == "CRED" { print $2 "\t" $3 }' "$W/clients.log" >"$W/credentials.tsv")
    rm -f "$W/clients.log"
    [ "$(wc -l <"$W/credentials.tsv")" -eq "$clients" ] ||
        gate_die "" "envelope: deploy/load/clients.py minted $(wc -l <"$W/credentials.tsv") of $clients credentials"
    (umask 077 && python3 -c 'import json, sys
rows = [line.rstrip("\n").split("\t") for line in open(sys.argv[1]) if line.strip()]
json.dump([{"tenant": t, "token": k} for t, k in rows], sys.stdout)' "$W/credentials.tsv" >"$W/credentials.json")
    rm -f "$W/credentials.tsv"
    probe_credentials
}

on_box_web() {
    local ip="$1" tenants="$2" clients="$3"
    box_start "web · organs at $ip · $tenants tenants · $clients clients"
    echo "envelope: clock $(chronyc tracking 2>/dev/null | grep 'System time' || echo 'System time : unread, chronyc did not answer')"
    image_stack_stopped
    export DJB_ENVELOPE_ORGANS_IP="$ip"
    [ -s "$W/env" ] || gate_die "" "envelope: no env file from the organs box at $W/env"
    install -m 644 "$W/env" deploy/.env
    DJB_ENVELOPE_CADDY_ROOT="$W/caddy-root.crt"
    export DJB_ENVELOPE_CADDY_ROOT

    echo "envelope: [web 1/5] the three images, built here at this tree"
    box_env web
    build_images

    echo "envelope: [web 2/5] migrated and granted against the organs box"
    migrate_and_grant "${C[@]}" run --rm -T --no-deps -e PGPASSWORD="$POSTGRES_PASSWORD" -e DATABASE_USER="$DATABASE_USER" \
        -e DATABASE_PASSWORD="$DATABASE_PASSWORD" --entrypoint psql db -h "$ip"

    echo "envelope: [web 3/5] $APP_SERVICES up, the app as its own role"
    "${C[@]}" up -d --no-deps caddy zitadel-relay >"$W/up-edge.log" 2>&1 ||
        gate_die "" "envelope: caddy and the Zitadel relay would not start" "$(tail -20 "$W/up-edge.log")"
    local waited=0 issuer
    until "${C[@]}" exec -T caddy cat /data/caddy/pki/authorities/local/root.crt >"$W/caddy-root.crt" 2>/dev/null &&
        [ -s "$W/caddy-root.crt" ]; do
        waited=$((waited + 2))
        [ "$waited" -lt 120 ] || gate_die "" "envelope: caddy minted no root certificate in 120s"
        sleep 2
    done
    issuer="$(curl -s --cacert "$W/caddy-root.crt" --resolve "$AUTH_ADDRESS:443:127.0.0.1" -o /dev/null -w '%{http_code}' \
        "https://$AUTH_ADDRESS/.well-known/openid-configuration" 2>&1 || true)"
    [ "$issuer" = 200 ] || gate_die "" "envelope: the issuer https://$AUTH_ADDRESS answered '$issuer' through caddy and the relay, not 200"
    echo "envelope:       issuer https://$AUTH_ADDRESS answers 200 (organs Zitadel, through caddy and the relay)"
    # shellcheck disable=SC2086
    "${C[@]}" up -d --no-deps $APP_SERVICES >"$W/up.log" 2>&1 || {
        "${C[@]}" logs --tail 30 web >&2 2>&1 || true
        gate_die "" "envelope: the app would not start" "$(tail -20 "$W/up.log")"
    }
    wait_ready
    pool_processes

    echo "envelope:       manage.py zitadel_seed: the project every realm is granted"
    "${C[@]}" run --rm -T -e SSL_CERT_FILE=/caddy-root.crt -v "$W/caddy-root.crt:/caddy-root.crt:ro" oneoff \
        python manage.py zitadel_seed >"$W/zitadel-seed.log" 2>&1 ||
        gate_die "" "envelope: manage.py zitadel_seed refused" "$(grep -iv secret "$W/zitadel-seed.log" | tail -20)"
    echo "envelope: [web 4/5] $tenants tenants, one user and one token per client"
    seed_and_mint "$tenants" "$clients"
    identity_homes "$tenants"

    echo "envelope: [web 5/5] the sampler"
    nohup bash deploy/load/utilization.sh --cpu-only --cpu-key host_cpu --census "$W/census-web.txt" --own-project "$COMPOSE_PROJECT_NAME" >"$W/util-web.jsonl" 2>"$W/util.err" </dev/null &
    echo "envelope: the web half is done"
}

# Every seeded tenant's identity home, read until none is pending: one line, never fatal.
identity_homes() {
    local want="$1" waited=0 line=""
    while [ "$waited" -lt 180 ]; do
        line="$("${C[@]}" run --rm -T oneoff python manage.py shell -c 'from collections import Counter
from apps.accounts.models import IdentityHome
c = Counter(IdentityHome.objects.values_list("state", flat=True))
print("identity_homes " + " ".join(f"{k}={v}" for k, v in sorted(c.items())))' 2>"$W/homes.err" | grep '^identity_homes' || true)"
        case "$line" in *pending=* | "") ;; *) break ;; esac
        waited=$((waited + 15))
        sleep 15
    done
    echo "envelope:       ${line:-identity_homes unread ($(tail -1 "$W/homes.err"))} (of $want seeded tenants + the staff realm)"
}

# The --rds-env file's database keys (SHAPE_KEYS, by prefix) laid over deploy/.env; DATABASE_HOST must be filled.
shape_env() {
    "$PY" - "$1" deploy/.env "$SHAPE_KEYS" <<'PYTHON' || gate_die "" "envelope: the --rds-env file's database keys did not apply"
import sys

sys.path.insert(0, "deploy")
from envfile import read_env_file, set_key

shape, target, prefixes = read_env_file(sys.argv[1]), sys.argv[2], sys.argv[3].split()
if not shape.get("DATABASE_HOST"):
    raise SystemExit("envelope: the --rds-env file has no DATABASE_HOST (provision.sh infra prints it)")
keys = sorted(k for k in shape if any(k == p or (p.endswith("_") and k.startswith(p)) for p in prefixes))
for key in keys:
    set_key(target, key, shape[key])
print(f"envelope:       {len(keys)} database keys from the shape's env file; class {shape.get('DJB_RDS_CLASS')}, workers {shape.get('DJB_WORKER_PROCESSES')}")
PYTHON
}

# One long-lived container holding a psql pointed at RDS as the master: the census, the grants (their \getenv pair) and the sampler use it.
psql_helper() {
    "${C[@]}" --profile laptop run -d --no-deps --name "$PSQL_HELPER" -e PGHOST="$DATABASE_HOST" -e PGPORT="$DATABASE_PORT" \
        -e PGPASSWORD="$POSTGRES_PASSWORD" -e PGSSLMODE=require -e DATABASE_USER="$DATABASE_USER" \
        -e DATABASE_PASSWORD="$DATABASE_PASSWORD" --entrypoint sleep db infinity >"$W/psql-helper.log" 2>&1 ||
        gate_die "" "envelope: the psql helper would not start" "$(tail -5 "$W/psql-helper.log")"
    docker exec "$PSQL_HELPER" psql -U "$POSTGRES_USER" -d "$DATABASE_NAME" -X -A -t -c 'SELECT version()' >"$W/rds-version.txt" 2>&1 ||
        gate_die "" "envelope: RDS at $DATABASE_HOST refused the master's psql" "$(tail -5 "$W/rds-version.txt")"
    echo "envelope:       RDS answers: $(cut -c1-60 "$W/rds-version.txt")"
}

# The alert route reconciled onto the dummy receiver and the sink keyed; never fatal, the ALERT-ROUTE line says which.
alert_route() {
    local tries=0 key
    until "${C[@]}" run --rm -T -e CLICKSTACK_URL=http://clickstack:8080 -e CLICKSTACK_ADMIN_EMAIL -e CLICKSTACK_ADMIN_PASSWORD \
        -e SLACK_WEBHOOK_URL -e DJB_DEPLOY_NAMESPACE oneoff python /app/deploy/observability/alerts/apply.py >"$W/alerts-apply.log" 2>&1; do
        tries=$((tries + 1))
        if [ "$tries" -ge 10 ]; then
            echo "envelope:       ALERT-ROUTE could-not-look: apply.py refused 10 times ($(tail -1 "$W/alerts-apply.log" | cut -c1-200))"
            return 0
        fi
        sleep 30
    done
    key="$("${C[@]}" run --rm -T -e CLICKSTACK_URL=http://clickstack:8080 -e CLICKSTACK_ADMIN_EMAIL -e CLICKSTACK_ADMIN_PASSWORD oneoff \
        python -c 'import os, sys
sys.path.insert(0, "/app/deploy/observability/alerts")
from apply import Sink
sink = Sink(os.environ["CLICKSTACK_URL"])
sink.authenticate(os.environ["CLICKSTACK_ADMIN_EMAIL"], os.environ["CLICKSTACK_ADMIN_PASSWORD"])
team = sink.request("GET", "/team")
print("APIKEY", team.get("apiKey", "") if isinstance(team, dict) else "")' 2>"$W/alerts-key.err" | awk '$1 == "APIKEY" { print $2 }')" || true
    if [ -z "$key" ]; then
        echo "envelope:       ALERT-ROUTE could-not-look: the sink named no ingestion key ($(tail -1 "$W/alerts-key.err" | cut -c1-200))"
        return 0
    fi
    "$PY" deploy/envfile.py set deploy/.env CLICKSTACK_API_KEY "$key"
    export CLICKSTACK_API_KEY="$key"
    "${C[@]}" up -d --no-deps --force-recreate otel-collector >"$W/collector.log" 2>&1 ||
        { echo "envelope:       ALERT-ROUTE could-not-look: the collector would not recreate with the key"; return 0; }
    echo "envelope:       ALERT-ROUTE armed: $(grep -c . "$W/alerts-apply.log") apply lines, the collector keyed, the receiver alerts-dummy"
}

on_box_infra_web() {
    local ip="$1" tenants="$2" clients="$3"
    box_start "infra web · RDS beside it · $tenants tenants · $clients clients"
    echo "envelope: clock $(chronyc tracking 2>/dev/null | grep 'System time' || echo 'System time : unread, chronyc did not answer')"
    image_stack_stopped
    [ -s "$W/shape.env" ] || gate_die "" "envelope: no --rds-env file handed to $W/shape.env"
    printf 'services:\n  minio:\n    ports: ["%s:9000:9000"]\n' "$ip" >"$W/compose.infra.yaml"

    echo "envelope: [infra 1/6] env file, with this box's object store, the shape's database and the alert receiver"
    env_file
    shape_env "$W/shape.env"
    "$PY" deploy/envfile.py set deploy/.env SLACK_WEBHOOK_URL http://alerts-dummy:9099/hook
    "$PY" deploy/envfile.py set deploy/.env CLICKSTACK_ADMIN_EMAIL envelope@example.com
    "$PY" deploy/envfile.py set deploy/.env CLICKSTACK_ADMIN_PASSWORD "Ev1!$(head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n')"

    echo "envelope: [infra 2/6] the three images, built here at this tree"
    box_env infra
    build_images

    echo "envelope: [infra 3/6] migrated and granted on RDS ($DATABASE_HOST)"
    psql_helper
    migrate_and_grant docker exec -i "$PSQL_HELPER" psql

    echo "envelope: [infra 4/6] the object store's bucket, then every service but db up, the app as its own role"
    "${C[@]}" up -d --wait minio >"$W/wait.log" 2>&1 || gate_die "" "envelope: minio never reported healthy" "$(tail -20 "$W/wait.log")"
    make_bucket
    ./deploy/provision.sh up -f "$ROOT/deploy/load/compose.envelope.yaml" -f "$W/compose.infra.yaml" \
        -f "$ROOT/deploy/observability/alerts/compose.sink.yaml" >"$W/up.log" 2>&1 || {
        tail -20 "$W/up.log" >&2
        "${C[@]}" ps -a --format '{{.Service}} {{.Status}}' >&2 || true
        "${C[@]}" logs --tail 30 web >&2 2>&1 || true
        gate_die "" "envelope: provision.sh up refused"
    }
    wait_ready
    pool_processes
    caddy_root

    echo "envelope: [infra 5/6] the alert route, onto the dummy receiver"
    alert_route

    echo "envelope: [infra 6/6] $tenants tenants, one user and one token per client; the sampler"
    seed_and_mint "$tenants" "$clients"
    nohup bash deploy/load/utilization.sh --cpu-key host_cpu --census "$W/census-web.txt" --own-project "$COMPOSE_PROJECT_NAME" \
        --psql "docker exec -i $PSQL_HELPER psql -U $POSTGRES_USER -d $DATABASE_NAME" \
        --redis-cli "${C[*]} exec -T redis redis-cli" --temporal "${C[*]} exec -T temporal temporal --address temporal:7233" \
        --task-queue "${TEMPORAL_TASK_QUEUE:?the env file names no TEMPORAL_TASK_QUEUE}" >"$W/util-web.jsonl" 2>"$W/util.err" </dev/null &
    echo "envelope: the infra web half is done"
}

on_box_infra_census() {
    cd "$ROOT"
    set -a
    # shellcheck source=/dev/null
    . deploy/.env
    set +a
    docker exec "$PSQL_HELPER" psql -U "$POSTGRES_USER" -d postgres -X -A -t -F '|' -c "$CENSUS_SQL_RDS"
}

# Every post the dummy receiver logged, one ALERTS line each; `none` when it logged nothing.
on_box_alerts() {
    W="$HOME/envelope"
    cd "$ROOT"
    box_env infra
    "${C[@]}" exec -T alerts-dummy cat /var/log/dummy/requests.jsonl 2>/dev/null | python3 -c 'import json, sys
rows = [json.loads(line) for line in sys.stdin if line.strip()]
for r in rows:
    at, state = r.get("at", "?"), r.get("state", "?")
    text = " ".join(str(r.get("text") or "").split())[:160]
    print("== ALERTS · %s state=%s %s" % (at, state, text))
if not rows:
    print("== ALERTS · none received")'
}

on_box_drive() {
    local sha="$1" web_ip="$2" organs_ip="$3" minutes="$4" ladder="$5" step="$6" size="$7" client="$8" topology="${9:-$TOPOLOGY_PROD}"
    box_start "drive · web at $web_ip · organs at $organs_ip · sha $sha · $topology"
    echo "envelope: clock $(chronyc tracking 2>/dev/null | grep 'System time' || echo 'System time : unread, chronyc did not answer')"
    [ -s "$W/credentials.json" ] && [ -s "$W/probe-credentials.json" ] && [ -s "$W/caddy-root.crt" ] ||
        gate_die "" "envelope: the web box's credentials, probe credentials and CA were not handed to $W"

    bash deploy/load/utilization.sh --cpu-only --cpu-key client_cpu >"$W/util-client.jsonl" 2>"$W/util.err" &
    local sampler=$!
    docker pull -q "$DRIVE_IMAGE" >"$W/pull.log" 2>&1 || gate_die "" "envelope: could not pull $DRIVE_IMAGE" "$(cat "$W/pull.log")"
    local -a D=(docker run --rm -e PYTHONUNBUFFERED=1 -v "$ROOT:/src:ro" -v "$W:/work" "$DRIVE_IMAGE"
        python /src/deploy/load/drive.py)
    local -a TARGET=(--base-url https://localhost --credentials /work/credentials.json --out /work/out
        --ca-bundle /work/caddy-root.crt --resolve "localhost:$web_ip" --resolve "minio:$organs_ip")

    echo "envelope: [drive 1/3] drive.py prepare, once per tenant"
    "${D[@]}" prepare "${TARGET[@]}" || gate_die "" "envelope: drive.py prepare refused"

    echo "envelope:       the socket probe idle, before any load (the control)"
    PROBE=(docker run --rm -e PYTHONUNBUFFERED=1 -v "$ROOT:/src:ro" -v "$W:/work" "$DRIVE_IMAGE"
        python /src/deploy/load/realtime_lag.py --credentials /work/probe-credentials.json
        --base-url https://localhost --ca-bundle /work/caddy-root.crt --resolve "localhost:$web_ip")
    local clock_web clock_drive
    clock_web="$(cat "$W/clock-web.txt" 2>/dev/null || true)"
    clock_drive="$(chronyc tracking 2>/dev/null | chrony_offset || true)"
    [ -z "$clock_web" ] || [ -z "$clock_drive" ] || PROBE+=(--clock "web=$clock_web,drive=$clock_drive")
    realtime_probe idle-before drive-box "${PROBE[@]}"

    echo "envelope: [drive 2/3] the ladder, from $(date -u +%FT%TZ)"
    local -a LADDER=()
    [ "$ladder" = "default" ] || LADDER=(--ladder "$ladder")
    local rc=0
    "${D[@]}" run "${TARGET[@]}" --sha "$sha" --utilization /work/util-client.jsonl --size "$size" \
        --client "$client" --topology "$topology" --step-seconds "$step" "${LADDER[@]}" || rc=$?
    kill -0 "$sampler" 2>/dev/null || gate_die "" "envelope: the client sampler stopped during the ladder" "$(cat "$W/util.err")"
    [ "$rc" -eq 0 ] || gate_die "" "envelope: drive.py run exited $rc — no soak is judged over an unjudged ladder"

    local half
    half="$(half_of_the_knee)"
    echo "envelope: [drive 3/3] the soak at concurrency $half (half the knee) for $minutes min from $(date -u +%FT%TZ), the socket probe in its last window"
    SOAK=("${D[@]}" soak "${TARGET[@]}" --concurrency "$half" --minutes "$minutes" --defer-judgement)
    rc=0
    soak_and_probe "$minutes" "$half" drive-box || rc=$?
    kill "$sampler" 2>/dev/null || true
    [ "$rc" -eq 0 ] || gate_die "" "envelope: drive.py soak exited $rc"
    echo "envelope: the drive half is done at $(date -u +%FT%TZ)"
}

on_box_whoami() {
    local token mac
    token="$(curl -sf -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 60')" ||
        gate_die "" "envelope: the instance metadata service did not answer"
    md() { curl -sf -H "X-aws-ec2-metadata-token: $token" "http://169.254.169.254/latest/meta-data/$1"; }
    mac="$(md mac)"
    echo "whoami ip=$(md local-ipv4) sg=$(md "network/interfaces/macs/$mac/security-group-ids" | head -1)"
}

on_box_probe() {
    python3 -c 'import socket, sys
host = sys.argv[1]
for port in sys.argv[2:]:
    try:
        socket.create_connection((host, int(port)), timeout=5).close()
        said = "open"
    except ConnectionRefusedError:
        said = "reachable"
    except (TimeoutError, socket.timeout):
        said = "blocked"
    except OSError as exc:
        said = f"failed({exc.strerror or exc})"
    print(f"probe {host}:{port} {said}")' "$@"
}

[ "$#" -gt 0 ] || usage 2
case "$1" in
-h | --help) usage 0 ;;
--on-box)
    shift
    role="${1:-}"
    shift || true
    case "$role:$#" in
    one-box:5) on_box_one "$@" ;;
    organs:1) on_box_organs "$@" ;;
    web:3) on_box_web "$@" ;;
    drive:8 | drive:9) on_box_drive "$@" ;;
    infra-web:3) on_box_infra_web "$@" ;;
    infra-census:0) on_box_infra_census ;;
    alerts:0) on_box_alerts ;;
    census:1) on_box_census "$@" ;;
    image-stack:0) W="$HOME/envelope" && mkdir -p "$W" && cd "$ROOT" && image_stack_stopped ;;
    whoami:0) on_box_whoami ;;
    probe:*) on_box_probe "$@" ;;
    *) gate_die "" "envelope: --on-box takes one-box|organs|web|drive|census|infra-web|infra-census|alerts|image-stack|whoami|probe and its arguments, got '$role' with $#" ;;
    esac
    exit 0
    ;;
esac

# --- the laptop half ---------------------------------------------------------

sha="$1"
shift
shape=prod
type=""
organs_type=m7g.xlarge
drive_type=t4g.medium
tenants=4
clients=8
minutes=30
ladder=default
step=60
rds_env=""
while [ "$#" -gt 0 ]; do
    case "$1" in
    --shape) shape="${2:?--shape takes prod or one-box (or infra)}"; shift 2 ;;
    --rds-env) rds_env="${2:?--rds-env takes the env file provision.sh env-file wrote for the infra environment}"; shift 2 ;;
    --type) type="${2:?--type takes an instance type}"; shift 2 ;;
    --organs-type) organs_type="${2:?--organs-type takes an instance type}"; shift 2 ;;
    --drive-type) drive_type="${2:?--drive-type takes an instance type}"; shift 2 ;;
    --tenants) tenants="${2:?--tenants takes a count}"; shift 2 ;;
    --clients) clients="${2:?--clients takes a count}"; shift 2 ;;
    --soak-minutes) minutes="${2:?--soak-minutes takes minutes}"; shift 2 ;;
    --ladder) ladder="${2:?--ladder takes 1,2,4,...}"; shift 2 ;;
    --step-seconds) step="${2:?--step-seconds takes seconds}"; shift 2 ;;
    *) gate_die "" "envelope: unknown argument '$1'" ;;
    esac
done
case "$shape" in
prod) type="${type:-c7g.xlarge}" ;;
one-box) type="${type:-t4g.large}" ;;
infra) type="${type:-$(awk -F 'DJB_INSTANCE_TYPE:-' 'NF > 1 { sub(/}.*/, "", $2); print $2; exit }' "$ROOT/deploy/provision.sh")}" ;;
*) gate_die "" "envelope: --shape takes prod or one-box (or infra, with --rds-env), got '$shape'" ;;
esac
if [ "$shape" = infra ]; then
    [ -n "$rds_env" ] && [ -r "$rds_env" ] || gate_die "" "envelope: --shape infra takes --rds-env <the env file provision.sh env-file wrote and infra read>"
    rds_host="$("$PY" "$ROOT/deploy/envfile.py" get "$rds_env" DATABASE_HOST)"
    rds_class="$("$PY" "$ROOT/deploy/envfile.py" get "$rds_env" DJB_RDS_CLASS)"
    [ -n "$rds_host" ] || gate_die "" "envelope: $rds_env has no DATABASE_HOST" "Fill it from the DATABASE_HOST line provision.sh infra printed last."
    [ -n "$rds_class" ] && [ "$rds_class" != compose ] || gate_die "" "envelope: $rds_env names no RDS class (DJB_RDS_CLASS='$rds_class')"
else
    [ -z "$rds_env" ] || gate_die "" "envelope: --rds-env is --shape infra's"
fi
[[ "$minutes" =~ ^[0-9]+$ && "$step" =~ ^[0-9]+$ ]] || gate_die "" "envelope: --soak-minutes and --step-seconds take whole numbers"
[[ "$tenants" =~ ^[1-9][0-9]*$ && "$clients" =~ ^[1-9][0-9]*$ ]] || gate_die "" "envelope: --tenants and --clients take whole counts"
[ "$clients" -ge "$tenants" ] || gate_die "" "envelope: --clients $clients cannot spread over --tenants $tenants"
[[ "$ladder" = default || "$ladder" =~ ^[0-9]+(,[0-9]+)*$ ]] || gate_die "" "envelope: --ladder takes 1,2,4,..."
for t in "$type" "$organs_type" "$drive_type"; do
    [[ "$t" =~ ^[a-z0-9.]+$ ]] || gate_die "" "envelope: '$t' is not an instance type"
done

full="$(git -C "$ROOT" rev-parse --verify --quiet "$sha^{commit}")" || gate_die "" "envelope: $sha names no commit"
head="$(git -C "$ROOT" rev-parse HEAD)"
[ "$full" = "$head" ] || gate_die "" "envelope: $sha is not HEAD ($head)" "The box is pushed HEAD: check the candidate out, then run this again."
[ -z "$(tree_dirt "$ROOT" --untracked-files=no)" ] ||
    gate_die "" "envelope: the tree is dirty" "The box is pushed HEAD, so the measured tree would not be this one. Commit or stash first."
grep -qF "$MARK_END" "$CAPACITY" || gate_die "" "envelope: $CAPACITY has no '$MARK_END' marker to record against"

work="$(mktemp -d "${TMPDIR:-/tmp}/envelope.XXXXXX")" || gate_die "" "envelope: could not make a work directory"
chmod 700 "$work"
if [ "$shape" = infra ]; then
    echo "envelope: sha $full · infra · web $type · RDS $rds_class at $rds_host · drive $drive_type · $clients clients over $tenants tenants · ladder $ladder · ${step}s/step · soak ${minutes} min · namespace ${DJB_DEPLOY_NAMESPACE:-<unset>} · region ${DJB_VERIFIER_REGION:-<unset>} · logs $work"
elif [ "$shape" = prod ]; then
    echo "envelope: sha $full · prod · web $type · organs $organs_type · drive $drive_type · $clients clients over $tenants tenants · ladder $ladder · ${step}s/step · soak ${minutes} min · namespace ${DJB_DEPLOY_NAMESPACE:-<unset>} · region ${DJB_VERIFIER_REGION:-<unset>} · logs $work"
else
    echo "envelope: sha $full · one-box · $type · ladder $ladder · ${step}s/step · soak ${minutes} min · namespace ${DJB_DEPLOY_NAMESPACE:-<unset>} · region ${DJB_VERIFIER_REGION:-<unset>} · logs $work"
fi
t0="$(date +%s)"
INSTANCES=()

teardown() {
    local rc=$? id
    rm -f "$work/env" "$work/credentials.json" "$work/probe-credentials.json"
    for id in ${INSTANCES[@]+"${INSTANCES[@]}"}; do
        if "$VB" down "$id" >"$work/down-$id.log" 2>&1; then
            echo "envelope: box $id down · wall $((($(date +%s) - t0) / 60)) min"
        else
            cat "$work/down-$id.log" >&2
            gate_refuse "envelope: the box $id is STILL UP"
            gate__indented "Take it down: scripts/verifier_box.sh down $id"
            rc=2
        fi
    done
    exit "$rc"
}
trap teardown EXIT

box_up() {
    local role="$1" box_type="$2" rc=0 id
    local -a market=()
    [ "${3:-}" != on-demand ] || market=(--on-demand)
    "$VB" up --for "envelope-${full:0:12}-$role" --type "$box_type" --ttl 4 --idle 60 ${market[@]+"${market[@]}"} >"$work/up-$role.log" 2>&1 || rc=$?
    id="$(awk '$1 == "instance" || $1 == "launched" { print $2; exit }' "$work/up-$role.log")"
    [ -z "$id" ] || INSTANCES+=("$id")
    cat "$work/up-$role.log"
    [ "$rc" -eq 0 ] && [ -n "$id" ] || gate_die "" "envelope: verifier_box up ($role) exited $rc (its log is above)"
    BOX="$id"
}

box_src="$(cd "$ROOT" && "$PY" -c 'from quality.djb.box.transport import verifier_checkout_path as p; print(p())')" ||
    gate_die "" "envelope: the box's checkout path could not be read off deploy/verifier/bake.sh"

box_say() {
    local id="$1" out="$2"
    shift 2
    "$VB" run "$id" -- "mkdir -p ~/envelope && cd $box_src && { bash scripts/envelope.sh --on-box $* > ~/envelope/say.out 2>&1; rc=\$?; cat ~/envelope/say.out; exit \$rc; }" >"$out" 2>"$out.err"
}

box_half() {
    local id="$1" name="$2" hours="$3"
    shift 3
    "$VB" run "$id" -- "mkdir -p ~/envelope && cd $box_src && { nohup bash scripts/envelope.sh --on-box $* > ~/envelope/box.log 2>&1 < /dev/null & } && echo started" \
        >"$work/start-$name.log" 2>&1 || gate_die "" "envelope: the $name half would not start" "$(cat "$work/start-$name.log")"
    local deadline=$(($(date +%s) + hours * 3600)) box_rc="" last fresh_at other
    fresh_at="$(date +%s)"
    while [ -z "$box_rc" ]; do
        [ "$(date +%s)" -lt "$deadline" ] || gate_die "" "envelope: the $name half did not finish inside $hours h"
        sleep 30
        if [ $(($(date +%s) - fresh_at)) -ge "$FRESH_EVERY" ]; then
            for other in ${INSTANCES[@]+"${INSTANCES[@]}"}; do
                [ "$other" = "$id" ] || "$VB" run "$other" -- true >"$work/fresh-$other.log" 2>&1 ||
                    echo "envelope: could not touch $other's activity marker ($work/fresh-$other.log)" >&2
            done
            fresh_at="$(date +%s)"
        fi
        if "$VB" run "$id" -- "cat ~/envelope/rc 2>/dev/null || echo running" >"$work/poll-$name.log" 2>&1; then
            last="$(awk 'NF { l = $0 } END { print l }' "$work/poll-$name.log")"
            [[ "$last" =~ ^[0-9]+$ ]] && box_rc="$last"
        fi
    done
    "$VB" run "$id" -- "cat ~/envelope/box.log" >"$work/box-$name.log" 2>&1 || true
    cat "$work/box-$name.log"
    [ "$box_rc" -eq 0 ] || gate_die "" "envelope: the $name half exited $box_rc (its log is above; every box is taken down)"
}

box_get() {
    "$VB" run "$1" -- "cat ~/envelope/$2" >"$3" 2>"$3.err" || gate_die "" "envelope: could not read $2 off $1" "$(cat "$3.err")"
}

box_put() {
    "$VB" run "$1" -- "umask 077 && mkdir -p ~/envelope && cat > ~/envelope/$3" <"$2" >"$work/put.log" 2>&1 ||
        gate_die "" "envelope: could not hand $3 to $1" "$(cat "$work/put.log")"
}

# `bare` when every census says so, else `shared`: a box whose census names another project shares its CPU.
host_of() {
    if [ "$(awk '$0 == "host=bare" { n++ } END { print n + 0 }' "$@")" -eq "$#" ]; then echo bare; else echo shared; fi
}

record() {
    local envelope="$1" soak="$2" size="$3" realtime="$4" host="$5"
    [ -n "$envelope" ] && [ -n "$soak" ] || gate_die "" "envelope: the run printed no ENVELOPE or no SOAK line"
    [ -n "$realtime" ] || gate_die "" "envelope: the run printed no REALTIME line"
    local wall entry rt=""
    wall=$((($(date +%s) - t0) / 60))
    entry="- $(date -u +%Y-%m-%d) · sha \`${full:0:12}\` · \`$size\` · host=$host · wall ${wall} min (box up to the line) · \`scripts/envelope.sh\`"
    # One `-v` value, its lines joined by awk's own \n escape (a literal newline in -v is BSD awk's error).
    while IFS= read -r line; do rt="$rt${rt:+\\n}  - \`$line\`"; done <<<"$realtime"
    awk -v entry="$entry" -v env="  - \`$envelope\`" -v soak="  - \`$soak\`" -v rt="$rt" -v mark="$MARK_END" \
        '$0 == mark { print entry; print env; print soak; print rt } { print }' "$CAPACITY" >"$work/capacity.md"
    cp "$work/capacity.md" "$CAPACITY"
    echo "envelope: recorded in $CAPACITY:"
    echo "$entry"
    echo "  $envelope"
    echo "  $soak"
    while IFS= read -r line; do echo "  $line"; done <<<"$realtime"
}

whoami() {
    local role="$1" id="$2"
    box_say "$id" "$work/whoami-$role.log" whoami || gate_die "" "envelope: the $role box could not say where it is" "$(cat "$work/whoami-$role.log.err")"
    ADDR="$(sed -n 's/^whoami ip=\([0-9.]*\) .*/\1/p' "$work/whoami-$role.log")"
    GROUP="$(sed -n 's/^whoami .* sg=\(sg-[0-9a-f]*\).*/\1/p' "$work/whoami-$role.log")"
    [ -n "$ADDR" ] && [ -n "$GROUP" ] || gate_die "" "envelope: the $role box's address or group is unread" "$(cat "$work/whoami-$role.log")"
    echo "envelope: $role $id · $ADDR · $GROUP"
}

if [ "$shape" = infra ]; then
    # The web box holds the stack on-demand: a spot reclaim of it loses the run.
    box_up web "$type" on-demand
    web="$BOX"
    box_up drive "$drive_type"
    drive="$BOX"
    whoami web "$web"
    web_ip="$ADDR"
    group="$GROUP"
    whoami drive "$drive"

    echo "envelope: [1/7] the group admits the envelope's own traffic, and the web box reaches RDS"
    box_say "$drive" "$work/probe-drive.log" probe "$web_ip" 443 9000
    box_say "$web" "$work/probe-web.log" probe "$rds_host" 5432
    cat "$work/probe-drive.log" "$work/probe-web.log"
    ! grep -q ' failed(' "$work/probe-drive.log" "$work/probe-web.log" ||
        gate_die "" "envelope: a probe failed for a reason that is not a group (above)"
    if grep -q ' blocked$' "$work/probe-web.log"; then
        gate_refuse "envelope: the database's group drops the web box — the infra shape needs one ingress rule on it, and it is the owner's to add"
        gate__indented "OWNER: aws ec2 authorize-security-group-ingress --region ${DJB_VERIFIER_REGION:-us-east-1} --group-id <the group provision.sh infra made for the database, <namespace>-<env>-db> --protocol tcp --port 5432 --source-group $group"
        exit 2
    fi
    ! grep -q ' blocked$' "$work/probe-drive.log" || gate_die "" "envelope: the verifier group drops the drive's traffic to the web box (above)"

    echo "envelope: [2/7] the web box, handed the shape's env file"
    (umask 077 && box_put "$web" "$rds_env" shape.env)
    box_half "$web" web 2 infra-web "$web_ip" "$tenants" "$clients"

    echo "envelope: [3/7] the pre-spend baseline (capacity.md § 7) over § 2a's census, on RDS"
    box_say "$web" "$work/census.txt" infra-census || gate_die "" "envelope: the census could not be read" "$(cat "$work/census.txt.err")"
    cat "$work/census.txt"
    app_db="$("$PY" "$ROOT/deploy/envfile.py" get "$rds_env" DATABASE_NAME)"
    box_get "$web" processes.txt "$work/processes.txt"
    processes="$(cat "$work/processes.txt")"
    "$PY" "$ROOT/deploy/load/drive.py" baseline --census "$work/census.txt" --app-db "$app_db" --processes "$processes" ||
        gate_die "" "envelope: the baseline is dirty — the run is void before it starts (capacity.md § 7)"

    echo "envelope: [4/7] the drive box, handed its credentials and the web box's CA"
    (umask 077 && box_get "$web" credentials.json "$work/credentials.json")
    box_get "$web" caddy-root.crt "$work/caddy-root.crt"
    (umask 077 && box_get "$web" probe-credentials.json "$work/probe-credentials.json")
    box_put "$drive" "$work/credentials.json" credentials.json
    box_put "$drive" "$work/probe-credentials.json" probe-credentials.json
    box_put "$drive" "$work/caddy-root.crt" caddy-root.crt
    sed -n 's/^envelope: clock //p' "$work/box-web.log" | chrony_offset >"$work/clock-web.txt" || true
    box_put "$drive" "$work/clock-web.txt" clock-web.txt
    box_half "$drive" drive 3 drive "$full" "$web_ip" "$web_ip" "$minutes" "$ladder" "$step" "$type" "$drive_type" "$TOPOLOGY_INFRA"

    echo "envelope: [5/7] the alert receiver's posts, ladder and soak included"
    box_say "$web" "$work/alerts.txt" alerts || echo "envelope: the alert receiver could not be read ($(cat "$work/alerts.txt.err"))"
    sed -n 's/^envelope: ALERT-ROUTE /ALERT-ROUTE /p' "$work/box-web.log"
    cat "$work/alerts.txt"

    echo "envelope: [6/7] both boxes' samples beside the run's own files"
    mkdir -p "$work/out"
    "$VB" run "$drive" -- "cd ~/envelope/out && tar cf - drive-*Z.json soak-*-samples.json" >"$work/out.tar" 2>"$work/out.err" ||
        gate_die "" "envelope: could not fetch the drive's output" "$(cat "$work/out.err")"
    tar xf "$work/out.tar" -C "$work/out"
    box_get "$web" util-web.jsonl "$work/util-web.jsonl"
    box_get "$drive" util-client.jsonl "$work/util-client.jsonl"
    box_get "$web" census-web.txt "$work/census-web.txt"
    cat "$work/census-web.txt"
    rc=0
    "$PY" "$ROOT/deploy/load/drive.py" judge --out "$work/out" --utilization "$work/util-web.jsonl" \
        --utilization "$work/util-client.jsonl" --processes "$processes" >"$work/judge.log" 2>&1 || rc=$?
    cat "$work/judge.log"
    [ "$rc" -eq 0 ] || gate_die "" "envelope: drive.py judge exited $rc"

    echo "envelope: [7/7] the lines, recorded"
    record "$(sed -n 's/^== ENVELOPE · //p' "$work/judge.log" | tail -1)" \
        "$(sed -n 's/^== SOAK · //p' "$work/judge.log" | tail -1)" "$type + $rds_class RDS + $drive_type drive" \
        "$(sed -n 's/^== REALTIME · //p' "$work/box-drive.log")" "$(host_of "$work/census-web.txt")"
    exit 0
fi

if [ "$shape" = one-box ]; then
    box_up one "$type"
    box_half "$BOX" one-box 4 one-box "$full" "$minutes" "$ladder" "$step" "$type"
    box_get "$BOX" census-one-box.txt "$work/census-one-box.txt"
    record "$(sed -n 's/^== ENVELOPE · //p' "$work/box-one-box.log" | tail -1)" \
        "$(sed -n 's/^== SOAK · //p' "$work/box-one-box.log" | tail -1)" "$type" \
        "$(sed -n 's/^== REALTIME · //p' "$work/box-one-box.log")" "$(host_of "$work/census-one-box.txt")"
    exit 0
fi

# The boxes that hold the stack launch on-demand: a spot reclaim of one loses the run.
box_up organs "$organs_type" on-demand
organs="$BOX"
box_up web "$type" on-demand
web="$BOX"
box_up drive "$drive_type"
drive="$BOX"

whoami organs "$organs"
organs_ip="$ADDR"
group="$GROUP"
whoami web "$web"
web_ip="$ADDR"
whoami drive "$drive"

echo "envelope: [1/7] the group admits the envelope's own traffic"
box_say "$drive" "$work/probe-drive.log" probe "$web_ip" 443
box_say "$drive" "$work/probe-drive-organs.log" probe "$organs_ip" 9000
# shellcheck disable=SC2086
box_say "$web" "$work/probe-web.log" probe "$organs_ip" $ORGAN_PORTS 443
cat "$work/probe-drive.log" "$work/probe-drive-organs.log" "$work/probe-web.log"
! grep -q ' failed(' "$work/probe-drive.log" "$work/probe-drive-organs.log" "$work/probe-web.log" ||
    gate_die "" "envelope: a probe failed for a reason that is not the group (above)"
if grep -q ' blocked$' "$work/probe-drive.log" "$work/probe-drive-organs.log" "$work/probe-web.log"; then
    perms=""
    for port in 443 $ORGAN_PORTS; do
        perms="$perms 'IpProtocol=tcp,FromPort=$port,ToPort=$port,UserIdGroupPairs=[{GroupId=$group,Description=envelope-prod-shape}]'"
    done
    gate_refuse "envelope: the verifier group drops traffic between its own boxes — the production shape needs one ingress rule, and it is the owner's to add"
    gate__indented "OWNER: aws ec2 authorize-security-group-ingress --region ${DJB_VERIFIER_REGION:-us-east-1} --group-id $group --ip-permissions$perms"
    exit 2
fi

echo "envelope: [2/7] the organs box"
box_half "$organs" organs 1 organs "$organs_ip"
(umask 077 && box_get "$organs" env "$work/env")

echo "envelope: [3/7] the web box"
box_put "$web" "$work/env" env
box_half "$web" web 1 web "$organs_ip" "$tenants" "$clients"

echo "envelope: [4/7] the pre-spend baseline (capacity.md § 7) over § 2a's census"
box_say "$organs" "$work/census.txt" census "$organs_ip" || gate_die "" "envelope: the census could not be read" "$(cat "$work/census.txt.err")"
cat "$work/census.txt"
app_db="$("$PY" "$ROOT/deploy/envfile.py" get "$work/env" DATABASE_NAME)"
box_get "$web" processes.txt "$work/processes.txt"
processes="$(cat "$work/processes.txt")"
"$PY" "$ROOT/deploy/load/drive.py" baseline --census "$work/census.txt" --app-db "$app_db" --processes "$processes" ||
    gate_die "" "envelope: the baseline is dirty — the run is void before it starts (capacity.md § 7)"

echo "envelope: [5/7] the drive box, handed its credentials and the web box's CA"
(umask 077 && box_get "$web" credentials.json "$work/credentials.json")
box_get "$web" caddy-root.crt "$work/caddy-root.crt"
(umask 077 && box_get "$web" probe-credentials.json "$work/probe-credentials.json")
box_put "$drive" "$work/credentials.json" credentials.json
box_put "$drive" "$work/probe-credentials.json" probe-credentials.json
box_put "$drive" "$work/caddy-root.crt" caddy-root.crt
sed -n 's/^envelope: clock //p' "$work/box-web.log" | chrony_offset >"$work/clock-web.txt" || true
box_put "$drive" "$work/clock-web.txt" clock-web.txt
box_half "$drive" drive 3 drive "$full" "$web_ip" "$organs_ip" "$minutes" "$ladder" "$step" "$type" "$drive_type"

echo "envelope: [6/7] every box's samples beside the run's own files"
mkdir -p "$work/out"
"$VB" run "$drive" -- "cd ~/envelope/out && tar cf - drive-*Z.json soak-*-samples.json" >"$work/out.tar" 2>"$work/out.err" ||
    gate_die "" "envelope: could not fetch the drive's output" "$(cat "$work/out.err")"
tar xf "$work/out.tar" -C "$work/out"
box_get "$web" util-web.jsonl "$work/util-web.jsonl"
box_get "$organs" util-organs.jsonl "$work/util-organs.jsonl"
box_get "$drive" util-client.jsonl "$work/util-client.jsonl"
box_get "$web" census-web.txt "$work/census-web.txt"
box_get "$organs" census-organs.txt "$work/census-organs.txt"
cat "$work/census-web.txt" "$work/census-organs.txt"
rc=0
"$PY" "$ROOT/deploy/load/drive.py" judge --out "$work/out" --utilization "$work/util-web.jsonl" \
    --utilization "$work/util-organs.jsonl" --utilization "$work/util-client.jsonl" --processes "$processes" >"$work/judge.log" 2>&1 || rc=$?
cat "$work/judge.log"
[ "$rc" -eq 0 ] || gate_die "" "envelope: drive.py judge exited $rc"

echo "envelope: [7/7] the lines, recorded"
record "$(sed -n 's/^== ENVELOPE · //p' "$work/judge.log" | tail -1)" \
    "$(sed -n 's/^== SOAK · //p' "$work/judge.log" | tail -1)" "$type + $organs_type organs + $drive_type drive" \
    "$(sed -n 's/^== REALTIME · //p' "$work/box-drive.log")" "$(host_of "$work/census-web.txt" "$work/census-organs.txt")"
