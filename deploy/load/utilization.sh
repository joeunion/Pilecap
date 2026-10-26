#!/usr/bin/env bash
. "$(dirname -- "${BASH_SOURCE:-$0}")/../../scripts/bash_only.sh" || exit 2
# deploy/load/utilization.sh — the box's own utilization, one JSON line per sample, beside the stack under load.
#
#   deploy/load/utilization.sh [--interval S] [--samples N] [--psql "<cmd>"] [--redis-cli "<cmd>"]
#                              [--temporal "<cmd>" --task-queue Q] [--proc-stat FILE]...
#   deploy/load/utilization.sh --cpu-only [--cpu-key client_cpu] [--interval S] [--samples N]
#   ... [--census FILE --own-project P [--docker "<cmd>"]]
#
# Each line: {"ts", "host_cpu", "pg_total", "pg_active", "pg_idle", "idle_in_tx", "outbox_pending",
# "pg_clients", "pg_other", "pg_by_app", "redis_clients"} and, with --temporal, "worker_backlog".
# `host_cpu` is the busy share of /proc/stat's `cpu` line between two reads; the pg counts are
# pg_stat_activity rows on the database the psql command connects to (current_database()), so the
# co-tenant organs' databases are not in them.
# `pg_total` counts every backend on the database; the budget is judged on `pg_clients`:
# the `backend_type = 'client backend'` rows of any role (capacity § 2a's population);
# `pg_other` names the rest as `<backend_type>:<n>[,...]` ("" when none) and
# `pg_by_app` the client backends as `<application_name>:<n>[,...]`, both from the same statement;
# `outbox_pending` is that database's `events_outbox` rows in `pending`, null until the table exists
# (the app has not migrated yet); `redis_clients` is INFO clients' connected_clients;
# `worker_backlog` is `temporal task-queue describe`'s approximateBacklogCount summed over the
# queue's workflow and activity halves.
#
# `--psql`, `--redis-cli` and `--temporal` are a command split on spaces (the box passes a `docker
# compose exec`); `--proc-stat` given more than once is read in turn (a canned pair for the test).
# `--cpu-key` names the CPU field by the box it is read on (`host_cpu` the web box, `organs_cpu`,
# `client_cpu` the drive's), and `--cpu-only` writes {"ts", <cpu key>} and asks no database.
# `--census FILE` writes, once before the first sample, every running container as
# `<compose project>\t<name>\t<image>` and a last line `host=bare` (every container is `--own-project`'s)
# or `host=shared others=<name>,...` (anything else runs on the box, so it is in the CPU key too).
# `--samples 0`, the default, samples until killed. Exit 0 sampled · 2 could not look: any read that
# fails ends the run on stderr, never as a line with a guessed number in it (house rule 35).
#
# does-not-cover: RDS metrics, the pool's own depth (no endpoint exposes it); the worker backlog without --temporal.

set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_NAME=utilization
DEPLOY_NOTHING="No sample was written for this read."
# shellcheck source=deploy/lib.sh
. "$HERE/../lib.sh" || exit 2

interval=5
samples=0
psql_cmd="psql"
redis_cmd="redis-cli"
temporal_cmd=""
task_queue=""
stat_files=()
cpu_key=host_cpu
cpu_only=""
census=""
own_project=""
docker_cmd="docker"
while [ "$#" -gt 0 ]; do
    case "$1" in
    --interval) interval="${2:?--interval takes seconds}"; shift 2 ;;
    --samples) samples="${2:?--samples takes a count}"; shift 2 ;;
    --psql) psql_cmd="${2:?--psql takes a command}"; shift 2 ;;
    --redis-cli) redis_cmd="${2:?--redis-cli takes a command}"; shift 2 ;;
    --temporal) temporal_cmd="${2:?--temporal takes a command}"; shift 2 ;;
    --task-queue) task_queue="${2:?--task-queue takes a queue name}"; shift 2 ;;
    --proc-stat) stat_files+=("${2:?--proc-stat takes a file}"); shift 2 ;;
    --cpu-key) cpu_key="${2:?--cpu-key takes a field name}"; shift 2 ;;
    --cpu-only) cpu_only=1; shift ;;
    --census) census="${2:?--census takes a file}"; shift 2 ;;
    --own-project) own_project="${2:?--own-project takes a compose project}"; shift 2 ;;
    --docker) docker_cmd="${2:?--docker takes a command}"; shift 2 ;;
    -h | --help) usage 0 ;;
    *) die "unknown argument '$1'" ;;
    esac
done
[ "${#stat_files[@]}" -gt 0 ] || stat_files=(/proc/stat)
[[ "$interval" =~ ^[0-9]+$ ]] || die "--interval takes whole seconds, got '$interval'"
[[ "$samples" =~ ^[0-9]+$ ]] || die "--samples takes a whole count, got '$samples'"
[[ "$cpu_key" =~ ^[a-z_]+_cpu$ ]] || die "--cpu-key takes a <box>_cpu field name, got '$cpu_key'"
[ -z "$temporal_cmd" ] || [ -n "$task_queue" ] || die "--temporal needs --task-queue"
read -ra PSQL <<<"$psql_cmd"
read -ra REDIS <<<"$redis_cmd"
read -ra TEMPORAL <<<"$temporal_cmd"
read -ra DOCKER <<<"$docker_cmd"
[ -z "$census" ] || [ -n "$own_project" ] || die "--census needs --own-project"

if [ -n "$census" ]; then
    running="$("${DOCKER[@]}" ps --format '{{.Label "com.docker.compose.project"}}	{{.Names}}	{{.Image}}' 2>&1)" ||
        die "could not look: docker ps failed" "$running"
    others="$(printf '%s\n' "$running" | awk -F '\t' -v own="$own_project" 'NF && $1 != own { o = o (o ? "," : "") $2 } END { print o }')"
    {
        [ -z "$running" ] || printf '%s\n' "$running"
        if [ -n "$others" ]; then echo "host=shared others=$others"; else echo "host=bare"; fi
    } >"$census" || die "could not write the census to $census"
fi

if [ -n "$temporal_cmd" ]; then
    echo "utilization: does_not_cover: RDS metrics, the pool's own depth (no endpoint exposes it)" >&2
else
    echo "utilization: does_not_cover: RDS metrics, worker backlog, the pool's own depth (no endpoint exposes it)" >&2
fi

# The outbox count goes through query_to_xml so the one statement still parses before migrate; '-' is no table yet.
# The two named lists are sub-selects of the same statement, so they read the same pg_stat_activity snapshot.
PG_SQL="select count(*), count(*) filter (where state = 'active'), count(*) filter (where state = 'idle'), count(*) filter (where state = 'idle in transaction'), coalesce((select (xpath('/row/n/text()', query_to_xml('select count(*) as n from events_outbox where status = ''pending''', false, true, '')))[1]::text where to_regclass('public.events_outbox') is not null), '-'), count(*) filter (where backend_type = 'client backend'), coalesce((select string_agg(k || ':' || n, ',' order by k) from (select regexp_replace(backend_type, '[^a-z0-9]', '_', 'g') as k, count(*) as n from pg_stat_activity where datname = current_database() and pid <> pg_backend_pid() and backend_type <> 'client backend' group by 1) as o), ''), coalesce((select string_agg(k || ':' || n, ',' order by k) from (select coalesce(nullif(regexp_replace(application_name, '[^A-Za-z0-9@._-]', '_', 'g'), ''), 'unnamed') as k, count(*) as n from pg_stat_activity where datname = current_database() and pid <> pg_backend_pid() and backend_type = 'client backend' group by 1) as c), '') from pg_stat_activity where datname = current_database() and pid <> pg_backend_pid()"

reads=0
cpu_read() {
    local file="${stat_files[$((reads % ${#stat_files[@]}))]}" label rest
    reads=$((reads + 1))
    read -r label rest <"$file" 2>/dev/null || die "could not look: $file is unreadable"
    [ "$label" = "cpu" ] || die "could not look: $file's first line is not the aggregate cpu line"
    read -ra CPU <<<"$rest"
    [ "${#CPU[@]}" -ge 5 ] || die "could not look: $file's cpu line has ${#CPU[@]} fields"
}

cpu_read
prev_total=0
for n in "${CPU[@]}"; do prev_total=$((prev_total + n)); done
prev_idle=$((CPU[3] + CPU[4]))

taken=0
while [ "$samples" -eq 0 ] || [ "$taken" -lt "$samples" ]; do
    sleep "$interval"
    cpu_read
    total=0
    for n in "${CPU[@]}"; do total=$((total + n)); done
    idle=$((CPU[3] + CPU[4]))
    d_total=$((total - prev_total))
    d_idle=$((idle - prev_idle))
    prev_total=$total
    prev_idle=$idle
    [ "$d_total" -gt 0 ] || die "could not look: /proc/stat did not advance between two reads"
    tenths=$(((1000 * (d_total - d_idle) + d_total / 2) / d_total))
    if [ -n "$cpu_only" ]; then
        printf '{"ts": %s.0, "%s": %d.%d}\n' "$(date +%s)" "$cpu_key" $((tenths / 10)) $((tenths % 10))
        taken=$((taken + 1))
        continue
    fi

    pg="$("${PSQL[@]}" -X -A -t -c "$PG_SQL" 2>&1)" || die "could not look: the psql read of pg_stat_activity failed" "$pg"
    IFS='|' read -r pg_total pg_active pg_idle idle_in_tx outbox pg_clients pg_other pg_by_app extra <<<"$pg"
    named='^([A-Za-z0-9@._-]+:[0-9]+(,[A-Za-z0-9@._-]+:[0-9]+)*)?$'
    [[ "${pg_total:-}${pg_active:-}${pg_idle:-}${idle_in_tx:-}${pg_clients:-}" =~ ^[0-9]+$ && "${outbox:-}" =~ ^([0-9]+|-)$ &&
        "${pg_other-}" =~ $named && "${pg_by_app-}" =~ $named && -z "${extra-}" ]] ||
        die "could not look: pg_stat_activity answered '$pg', not six counts and two named lists"
    [ "$outbox" != "-" ] || outbox=null

    info="$("${REDIS[@]}" INFO clients 2>&1)" || die "could not look: redis INFO clients failed" "$info"
    clients="$(printf '%s\n' "$info" | tr -d '\r' | awk -F: '$1 == "connected_clients" { print $2 }')"
    [[ "$clients" =~ ^[0-9]+$ ]] || die "could not look: INFO clients carried no connected_clients"

    backlog=""
    if [ -n "$temporal_cmd" ]; then
        described="$("${TEMPORAL[@]}" task-queue describe --task-queue "$task_queue" -o json 2>&1)" ||
            die "could not look: temporal task-queue describe failed" "$described"
        backlog="$(printf '%s\n' "$described" | awk '{ while (match($0, /"approximateBacklogCount": *[0-9]+/)) { v = substr($0, RSTART, RLENGTH); sub(/.*: */, "", v); n += v; seen++; $0 = substr($0, RSTART + RLENGTH) } } END { if (seen) print n }')"
        [[ "$backlog" =~ ^[0-9]+$ ]] || die "could not look: task-queue describe carried no approximateBacklogCount" "$described"
        backlog=", \"worker_backlog\": $backlog"
    fi

    printf '{"ts": %s.0, "%s": %d.%d, "pg_total": %d, "pg_active": %d, "pg_idle": %d, "idle_in_tx": %d, "outbox_pending": %s, "pg_clients": %d, "pg_other": "%s", "pg_by_app": "%s", "redis_clients": %d%s}\n' \
        "$(date +%s)" "$cpu_key" $((tenths / 10)) $((tenths % 10)) "$pg_total" "$pg_active" "$pg_idle" "$idle_in_tx" "$outbox" \
        "$pg_clients" "$pg_other" "$pg_by_app" "$clients" "$backlog"
    taken=$((taken + 1))
done
