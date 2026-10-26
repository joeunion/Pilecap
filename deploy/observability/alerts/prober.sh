#!/bin/sh
# THE PROBER — the two alerts that cannot ride the sink (ADR obs-2 clause 2, as
# amended). One container, one loop, two questions:
#
#   1. IS THE APP UP?      curl the public /readyz, write probe.readyz.{ok,failed}
#                          into the sink as a log line; a ClickStack alert counts
#                          the failures and delivers the notification.
#   2. IS THE SINK DEAF?   scrape the COLLECTOR's own Prometheus endpoint for
#                          otelcol_exporter_send_failed_* / enqueue_failed_*, and
#                          when that total GROWS across N consecutive windows,
#                          POST straight to the alert webhook — because the one
#                          alert a sink cannot deliver is the one that says the
#                          sink stopped accepting.
#
# WAS `readyz_probe.sh`. Renamed when the second probe landed: a file called
# readyz_probe.sh that also watches the collector is a name that lies, and this
# repository treats a lying name as a violation rather than a nuance.
#
# THE RULING'S SCOPE BOUNDARY, held in code rather than in prose: designed
# degradations are EVENTS (the transition pairs); hard dependencies — Postgres,
# Redis, Temporal, Zitadel — are OUTAGES, and an outage is /readyz's answer,
# never an event the app emits. An app that has fallen over cannot emit the
# event that says so, which is exactly why this loop is not in `apps/`. The sink
# going deaf is the same argument one turn further out: a sink that has stopped
# accepting cannot carry the news that it stopped accepting.
#
# IT PROBES THE PUBLIC URL. `https://$SITE_ADDRESS/readyz`, not
# `http://web:8000/readyz`, because DNS, TLS and Caddy are in the path a user's
# request takes and an outage in any of them is an outage. `-k` is set only when
# PROBE_INSECURE=1 — the laptop's Caddy signs with its own internal CA.
#
# ONE HONEST DIFFERENCE ON A LAPTOP, and it is here rather than in a comment on
# a box. The laptop's SITE_ADDRESS is `localhost` (provision.sh), and inside a
# container `localhost` is the container itself — so a laptop probe of
# `https://localhost/readyz` would probe nothing. PROBE_CONNECT_TO takes curl's
# `--connect-to <host:port:connect-to-host:port>`, which keeps the Host header
# and the TLS SNI as SITE_ADDRESS and opens the socket to the `caddy` container
# instead. TLS, Caddy's real site block and the reverse proxy are all in the
# tested path; only PUBLIC DNS is not, and on staging PROBE_CONNECT_TO is unset
# so it is. Stated, not implied.
#
# THE /readyz HALF SHIPS OTLP, NOT STDOUT. One sink, one protocol
# (architecture.md). The log record's BODY is a single JSON string with an
# `event` key, which is the exact shape `core/observability.py` gives every
# application log line — so ONE `JSONExtractString(Body, 'event')` reads the
# app's events and this prober's alike, and the alert definitions do not need a
# second dialect.
#
# THE DEAF-SINK HALF DOES BOTH, AND THAT IS RULE 19 STATED BOTH WAYS: it writes
# `probe.sink.deaf` / `probe.sink.recovered` into the sink (best effort — while
# the sink is deaf that line is exactly what does not land, which is the point)
# AND it POSTs the notification to ALERT_WEBHOOK_URL itself. The POST is the
# delivery; the log line is the record for whoever reads the sink afterwards.
#
# WHAT IT CANNOT SEE, and this is declared, never implied:
#
#   * IT RUNS ON THE BOX IT WATCHES. If the whole box dies, this loop dies with
#     the sink and with the thing it was watching, and NOTHING pings. That is
#     the standing blind spot; `docs/runbooks/alerts.md` § "What this cannot
#     see" names it and names the $0-tier external check that closes it when a
#     product buys one.
#   * A CLICKSTACK THAT ACCEPTS AND FAILS TO INDEX. The counters below are the
#     COLLECTOR's: they say "we could not hand it over", which covers a stopped
#     sink, a refused connection and a rejected key. A sink that answers 200 and
#     then loses the row is invisible here (HyperDX's own health is a product's
#     operating concern, declared in the amendment).
#   * A DEAD COLLECTOR IS NOT SILENTLY IGNORED. If the metrics endpoint cannot
#     be scraped for SINK_DEAF_WINDOWS windows the alert opens anyway, with
#     `reason=collector_unreachable`: a collector nobody can ask is a collector
#     that is not exporting, and treating "cannot tell" as "fine" is how a
#     monitor lies.

set -u

# --- the /readyz half --------------------------------------------------------
TARGET="${PROBE_TARGET:?PROBE_TARGET is required — e.g. https://staging.example.invalid/readyz}"
ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT:-http://otel-collector:4318}"
INTERVAL="${PROBE_INTERVAL_SECONDS:-15}"
SERVICE="${PROBE_SERVICE_NAME:-readyz-prober}"
INSECURE="${PROBE_INSECURE:-0}"
CONNECT_TO="${PROBE_CONNECT_TO:-}"

# --- the deaf-sink half ------------------------------------------------------
# The collector's internal Prometheus endpoint, on the compose network and
# published nowhere (deploy/observability/collector-telemetry.yaml binds it to
# 0.0.0.0:8888 for exactly this reader and says why).
COLLECTOR_METRICS_URL="${COLLECTOR_METRICS_URL:-http://otel-collector:8888/metrics}"

# N, A DECLARED CONSTANT — a window is a value somebody chose, written down,
# never a number that drifted. Three consecutive windows in which the collector
# said it is not delivering. At the 15-second probe interval that is 45 seconds
# of continuous loss — the same 3-of-N shape the /readyz alert uses, for the
# same reason: one blip never pages.
SINK_DEAF_WINDOWS="${SINK_DEAF_WINDOWS:-3}"

# WHERE THE NOTIFICATION GOES. The same slot every other alert uses —
# `<namespace>/<env>/env`, key SLACK_WEBHOOK_URL (ADR deploy-3a) — read here from the
# environment compose substituted it into. On a laptop it is the dummy receiver.
# EMPTY IS A DISARMED HALF AND IT SAYS SO OUT LOUD at start: a probe that
# silently cannot deliver is worse than no probe.
ALERT_WEBHOOK_URL="${ALERT_WEBHOOK_URL:-${SLACK_WEBHOOK_URL:-}}"
HOSTNAME_SELF="${PROBE_HOST:-$(hostname 2>/dev/null || echo unknown)}"

CURL_OPTS=""
if [ "$INSECURE" = "1" ]; then CURL_OPTS="-k"; fi
if [ -n "$CONNECT_TO" ]; then CURL_OPTS="$CURL_OPTS --connect-to $CONNECT_TO"; fi

# readyz_probe <body-file> — ONE probe of the target: the HTTP code on stdout.
# The loop below calls it every interval; `deploy/release.sh`'s readyz act and
# `deploy/stage.sh`'s call it once, through `--once` (`docker compose exec -T
# readyz-prober sh /alerts/prober.sh --once`), so the target, the socket
# override and the certificate posture are this container's for all three and
# the default target is written once, in deploy/compose.yaml.
readyz_probe() {
  # shellcheck disable=SC2086  # CURL_OPTS is words by construction
  curl $CURL_OPTS -sS -m 10 -o "$1" -w '%{http_code}' "$TARGET"
}

if [ "${1:-}" = "--once" ]; then
  readyz_probe /dev/null
  exit $?
fi

# One OTLP/HTTP log record. $1 event name, $2 severity text, $3 http code,
# $4 detail. The body is a JSON document embedded as a JSON *string*, so every
# quote inside it is escaped once — the same on-the-wire shape the Python
# LoggingHandler produces for `core.log`.
emit() {
  _event="$1"; _sev="$2"; _code="$3"; _detail="$4"
  _now="$(date +%s)000000000"
  _severity_number=9
  if [ "$_sev" = "ERROR" ]; then _severity_number=17; fi
  _body="{\\\"event\\\": \\\"${_event}\\\", \\\"level\\\": \\\"$(echo "$_sev" | tr 'A-Z' 'a-z')\\\", \\\"target\\\": \\\"${TARGET}\\\", \\\"code\\\": \\\"${_code}\\\", \\\"detail\\\": \\\"${_detail}\\\", \\\"interval_seconds\\\": \\\"${INTERVAL}\\\"}"
  printf '{"resourceLogs":[{"resource":{"attributes":[{"key":"service.name","value":{"stringValue":"%s"}}]},"scopeLogs":[{"scope":{"name":"prober.sh"},"logRecords":[{"timeUnixNano":"%s","observedTimeUnixNano":"%s","severityNumber":%s,"severityText":"%s","body":{"stringValue":"%s"}}]}]}]}' \
    "$SERVICE" "$_now" "$_now" "$_severity_number" "$_sev" "$_body" \
  | curl -sS -m 10 -o /dev/null \
      -X POST "${ENDPOINT}/v1/logs" \
      -H 'Content-Type: application/json' \
      --data-binary @- \
    || echo "prober: could not reach the collector at ${ENDPOINT}" >&2
}

# THE POST THIS ALERT RIDES. `{"text": ...}` — the exact body
# `deploy/observability/alerts/definitions.json` renders for every ClickStack
# alert, so a Slack incoming webhook and the laptop's dummy receiver both take
# it and the dummy's `hdx_state=` classifier counts this alert alongside the
# others without learning a second dialect.
notify() {
  _state="$1"; _headline="$2"; _reason="$3"; _lost="$4"; _queued="$5"
  if [ -z "$ALERT_WEBHOOK_URL" ]; then
    echo "prober: NOT DELIVERED (no ALERT_WEBHOOK_URL): ${_headline}" >&2
    return
  fi
  _text="${_headline} — host=${HOSTNAME_SELF} reason=${_reason} collector_lost_total=${_lost} collector_queue=${_queued} probe_interval=${INTERVAL}s windows=${SINK_DEAF_WINDOWS} hdx_state=${_state} Runbook: docs/runbooks/alerts.md"
  printf '{"text": "%s"}' "$_text" \
  | curl -sS -m 10 -o /dev/null \
      -X POST "$ALERT_WEBHOOK_URL" \
      -H 'Content-Type: application/json' \
      --data-binary @- \
    || echo "prober: could not deliver to the alert webhook" >&2
}

# TWO NUMBERS OFF ONE SCRAPE — `<lost_total> <queue_total>` on one line.
#
#   lost_total   every `otelcol_exporter_send_failed_*` (the exporter gave up
#                after its retry budget) plus every `otelcol_exporter_enqueue_
#                failed_*` (the queue was full and the batch never got a try),
#                across every signal. This is the DEFINITIVE number: when it
#                grows, telemetry was lost and nothing gets it back.
#   queue_total  every `otelcol_exporter_queue_size`. This is the EARLY number:
#                a healthy exporter drains within a second, so a sample taken
#                every 15s reads 0; a sink that stopped accepting holds the
#                batch and the sample reads ≥ 1 for as long as it stays deaf.
#
# WHY BOTH, when the amendment named only the failure counters. Measured on
# collector-contrib 0.140.0 against a sink that was simply not there: the
# exporter's default `retry_on_failure.max_elapsed_time` is 300s, so
# `send_failed` does not move for FIVE MINUTES after the sink goes deaf, while
# `queue_size` reads 1 within one batch interval. Waiting for the definitive
# number alone would make the declared detection window ~6 minutes; watching the
# queue as well makes it ~45 seconds and costs nothing, because the two are OR'd
# and each is reported by name in the notification. The failure counters were
# NOT replaced — a stopped sink that later drops the batch is still the thing
# that proves telemetry was lost, and the alert says which condition it saw.
#
# Summed across signals rather than watched per-signal because "is the sink
# accepting" has one answer, and a deployment that lost only logs is not less
# deaf than one that lost only spans.
#
# `%.0f` rather than `%d`: a Prometheus counter can render in scientific notation
# once it is large, and awk's `%d` truncates such a value to zero — a monitor
# that silently reads 0 for "a lot" is the failure mode being avoided here.
#
# Exits 1 if the endpoint could not be read at all, which the caller treats as
# its own condition rather than as zero.
collector_state() {
  _metrics="$(curl -sS -m 10 "$COLLECTOR_METRICS_URL" 2>/dev/null)" || return 1
  [ -n "$_metrics" ] || return 1
  printf '%s\n' "$_metrics" | awk '
    /^otelcol_exporter_send_failed_/    { lost  += $NF }
    /^otelcol_exporter_enqueue_failed_/ { lost  += $NF }
    /^otelcol_exporter_queue_size/      { queue += $NF }
    END { printf "%.0f %.0f", lost + 0, queue + 0 }
  '
}

echo "prober: probing ${TARGET} every ${INTERVAL}s, shipping to ${ENDPOINT}" >&2
echo "prober: watching ${COLLECTOR_METRICS_URL}; ${SINK_DEAF_WINDOWS} consecutive windows of lost telemetry, a held queue or an unreachable collector opens the deaf-sink alert" >&2
if [ -z "$ALERT_WEBHOOK_URL" ]; then
  echo "prober: !! THE DEAF-SINK HALF IS DISARMED — neither ALERT_WEBHOOK_URL nor SLACK_WEBHOOK_URL is set, so a deaf sink will be detected and NOT delivered. Set the slot (\$DJB_DEPLOY_NAMESPACE/<env>/env, key SLACK_WEBHOOK_URL) and recreate this service." >&2
fi

# --- the deaf-sink state machine ---------------------------------------------
# `previous` unset until the first successful scrape: the FIRST reading is a
# baseline, never a growth. Each counter counts CONSECUTIVE windows; any window
# that does not satisfy its condition resets it to zero, and all three at zero
# is what closes the alert.
previous=""
growing=0
backed_up=0
unreadable=0
sink_state="ok"

while true; do
  # --- 1. is the app up? -----------------------------------------------------
  # --fail so a 503 from /readyz is a failure, not a body to parse. /readyz
  # answers 200 only when db, redis and temporal are all true
  # (apps/core/health.py), which is the whole point of asking it.
  code="$(readyz_probe /tmp/readyz.out 2>/tmp/readyz.err)"
  rc=$?
  if [ "$rc" -eq 0 ] && [ "$code" = "200" ]; then
    emit "probe.readyz.ok" "INFO" "$code" ""
  else
    detail="$(head -c 200 /tmp/readyz.out 2>/dev/null | tr -d '\\"' | tr '\n' ' ')"
    if [ -z "$detail" ]; then
      detail="$(head -c 200 /tmp/readyz.err 2>/dev/null | tr -d '\\"' | tr '\n' ' ')"
    fi
    emit "probe.readyz.failed" "ERROR" "${code:-000}" "${detail}"
  fi

  # --- 2. is the sink deaf? --------------------------------------------------
  if state="$(collector_state)"; then
    unreadable=0
    lost="${state% *}"
    queued="${state#* }"
    if [ -n "$previous" ] && [ "$lost" -gt "$previous" ]; then
      growing=$((growing + 1))
    else
      growing=0
    fi
    if [ "$queued" -gt 0 ]; then
      backed_up=$((backed_up + 1))
    else
      backed_up=0
    fi
    previous="$lost"
    if [ "$growing" -gt 0 ]; then
      reason="export_failures"
    else
      reason="queue_backed_up"
    fi
  else
    # Cannot ask the collector. Counted as its own consecutive condition and
    # NOT folded into the other two, so the notification can say which of the
    # three it saw. A collector nobody can ask is not a healthy collector.
    lost="${previous:-0}"
    queued="?"
    unreadable=$((unreadable + 1))
    growing=0
    backed_up=0
    reason="collector_unreachable"
  fi

  if [ "$growing" -ge "$SINK_DEAF_WINDOWS" ] \
     || [ "$backed_up" -ge "$SINK_DEAF_WINDOWS" ] \
     || [ "$unreadable" -ge "$SINK_DEAF_WINDOWS" ]; then
    if [ "$sink_state" = "ok" ]; then
      sink_state="deaf"
      emit "probe.sink.deaf" "ERROR" "" "collector_lost_total=${lost} queue=${queued} reason=${reason}"
      notify "ALERT" ":rotating_light: OPENED — alert.sink.deaf: telemetry is not reaching the sink" "$reason" "$lost" "$queued"
    fi
  elif [ "$growing" -eq 0 ] && [ "$backed_up" -eq 0 ] && [ "$unreadable" -eq 0 ] && [ "$sink_state" = "deaf" ]; then
    sink_state="ok"
    emit "probe.sink.recovered" "INFO" "" "collector_lost_total=${lost} queue=${queued}"
    notify "OK" ":white_check_mark: RECOVERED — alert.sink.deaf: telemetry is reaching the sink again" "recovered" "$lost" "$queued"
  fi

  sleep "$INTERVAL"
done
