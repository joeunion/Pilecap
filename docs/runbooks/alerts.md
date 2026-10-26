# Alerts and escalation — `<env>.example.invalid`

**Who gets woken, what they read first, and how the alert surface stays closed.**
The definitions are `deploy/observability/alerts/`; this file is the human half.

> **SCOPE.** This file is the alert route: the census, where an alert goes,
> what closes it, and the drills that prove all three. The app→collector half
> of the pipe belongs to `deploy/observability/README.md` — a route that fires
> correctly on a sink nothing reaches is still a deployment nobody can answer a
> question about, so perform both.

---

## The census is CLOSED, and it is DERIVED

The alert set is not a list. It is

    { one alert per declared transition-event pair }
  ∪ { one alert per declared spike }
  ∪ { the two trace alerts }
  ∪ { the two prober alerts }

and every part comes from ADR obs-2 as amended. **The two halves
are DERIVED DIFFERENTLY, and that is deliberate.** The event half is read out of
`apps/*/events.py` by AST and grows without an edit. The probe half is **named
explicitly** in `census.py`, because its two members are not events at all: they
are the two questions the sink cannot be asked to answer about itself — *is the
app up* (`/readyz`) and *is the sink still accepting* (the collector's own
export counters). Nothing under `apps/` declares either, so there is nothing to
derive them from; naming them is the honest form, and naming them THERE is what
keeps the census closed.

Print it — this is the derivation, and it is the **one place the next circuit's
author has to look**:

```bash
python3 deploy/observability/alerts/census.py
```

Today it prints:

```
ALERT CENSUS (derived, closed — ADR obs-2)

Read from: apps/accounts/events.py, apps/comms/events.py, apps/connections/events.py, apps/core/events.py, apps/djb_imports/events.py, apps/djb_notes/events.py, apps/djb_tags/events.py, apps/events/events.py, apps/example/events.py, apps/example_portal/events.py, apps/exports/events.py, apps/files/events.py, apps/search/events.py, apps/usage/events.py
Recovery verbs: recovered

Transition pairs declared: 2
  comms.suppression.surged  ->  comms.suppression.recovered
  search.engine.degraded  ->  search.engine.recovered

Spikes declared: 1
  accounts.signin.refused >= 20 in 5m (where=log; 12 call site(s); apps/accounts/events.py:17)

Trace alerts (deployment-wide, over server spans): 2
  latency >= 1 in 5m
  error_rate >= 12 in 5m

Probes: 2
  probe.readyz.failed (N consecutive /readyz failures; delivered by ClickStack)
  probe.sink.deaf (N consecutive windows of lost telemetry; delivered by the prober's own POST)

ALERTS = 2 pair(s) x 2 + 1 spike(s) + 2 trace alert(s) + 2 probes = 9
  [transition] comms.suppression degraded  (delivered by clickstack)
  [recovery] comms.suppression recovered  (delivered by clickstack)
  [transition] search.engine degraded  (delivered by clickstack)
  [recovery] search.engine recovered  (delivered by clickstack)
  [spike] accounts.signin.refused spike  (delivered by clickstack)
  [probe] readyz outage  (delivered by clickstack)
  [traces] latency  (delivered by clickstack)
  [traces] error_rate  (delivered by clickstack)
  [probe] sink deaf  (delivered by prober)
```

**`delivered_by` is a field, not a footnote.** Every member but one is
ClickStack's to deliver; the sink-deaf probe is the prober's own POST. `apply.py`
reconciles the `clickstack` members and **prints a `[skip]` line** for the
other, and `export.py` expects only the `clickstack` members back — otherwise a
portability check would report a permanent "MISSING FROM THE SINK" for an alert
that is working exactly as designed, and a false red is how a check stops being
read.

**How the next pair joins.** It declares its two names in its own app's
`events.py` — `<app>.<noun>.<degraded-verb>` and `<app>.<noun>.recovered` — and
that is all. `census.py` finds them because it reads the same files the gate
does, `apply.py` creates the saved search and the alert, and nobody edits a
list. `search.engine.degraded` / `search.engine.recovered` (ADR search-2) joined
exactly that way, and nothing here was edited for it.

**How a spike joins.** A spike is a count of one LOG key — a key the app
writes with `log.<level>("<key>", ...)`, not an event name — inside one window.
The app that writes the key declares it in its own `events.py`:

```python
SPIKES: tuple[dict[str, str | int], ...] = (
    {"key": "accounts.signin.refused", "threshold": 20, "window": "5m",
     "reason": "twenty refused sign-ins in five minutes is a credential-stuffing shape; ..."},
)
```

`census.py` reads it by AST, finds the `log.<level>("<key>"` calls in the
app (test modules are not emitters), and derives one alert of kind `spike`;
`definitions.json`'s `spike` shape gives it a saved search on that key, the
declared window as its interval and the declared count as its threshold. A key
no call writes, a window the sink cannot check (`1m 5m 15m 30m 1h 6h 12h 1d`), a
threshold under 1, a key outside the declaring app's own namespace or a reason
carrying a quote or a brace is a **WARNING**, and `apply.py` refuses to run. The
auth-failure spike is the worked instance; its 20 in 5 minutes is the worked
example's number, and a product declares its own in its own app.

**The two trace alerts, and why they are named rather than declared.**
`latency` and `error_rate` read the Traces source's server spans — one per
request, at every door — so their population is the route table, closed, and
no app declares them; they are named in `census.py`'s `TRACES` like the probes.
They are kind `traces`, and a `traces` member is a **dashboard tile alert**,
not a saved search: ClickStack's saved-search alert can only count rows, while
its tile alert runs the tile's own select, which is what lets `latency` carry
`quantile(0.95)`. `apply.py` keeps one dashboard (`<namespace>-alerts-traces`)
with one tile per member, the tile id the member's key, the alert embedded in
the tile; `export.py` matches them as `tile:<name>`. `latency`'s value is the
p95 **over its budget**, per class: server spans are grouped read
(`GET`/`HEAD`) or write, each class's p95 is divided by its budget, and the
alert opens at 1 (`>=`) — exact per class, because inside one class the divisor
is constant. A class holding fewer than `MIN_SPANS` spans in the window reads 0.
The method and status are read under both HTTP semantic conventions
(`http.request.method` / `http.response.status_code`, else `http.method` /
`http.status_code`), because the instrumentation exports the old keys until the
stable opt-in is set. A kind in `census.KINDS` with no shape in
`definitions.json`, or a shape of no kind, is a refusal: `apply.py` exits 2
naming it.

**The one line that could hide a pair.** `RECOVERY_VERBS` in `census.py` is the
closed tuple `("recovered",)`. A circuit that spells its recovery `restored` or
`closed` would declare a pair this file cannot see. Widening that tuple is the
edit; the module docstring says so too, so the two cannot drift apart. An
unpaired degradation name is printed as a **WARNING** and `apply.py` refuses to
run — a circuit that can be raised and never lowered is the alarm somebody
silences.

---

## Two Slack paths, and only one of them is this one

**A chat-assistant Slack tool exists only inside a session and carries
interactive pings; production alerting rides a real incoming webhook and
nothing else.** The MCP path is NOT the alert path — an
alert that needs a session alive is an alert that does not exist at 3am, which
is the only hour it matters. Every artifact under
`deploy/observability/alerts/` names its destination by **slot**:

| | |
|---|---|
| Slot | `$DJB_DEPLOY_NAMESPACE/<env>/env`, key `SLACK_WEBHOOK_URL` (ADR deploy-3a: one JSON secret per environment; the namespace has no default — `apply.py` refuses rather than guesses) |
| Who reads it | `apply.py`, once, at deploy time, from the environment `provision.sh secrets-fetch` wrote |
| What fires it | ClickStack's own `check-alerts` task, every minute, inside the sink container |
| What is in the tree | the slot name. Never a URL, never a token, never a length that came from a value in this repository |

On a laptop the same variable holds the dummy receiver's URL
(`http://alerts-dummy:9099/hook`). **That is the only difference between the
laptop definitions and the staging definitions** — which is why the delivery
webhook is a `generic` webhook whose body is `{"text": ...}`: Slack's incoming
webhook accepts exactly that, and so does the dummy.

---

## The one alert that cannot ride the sink

**`alert.sink.deaf` is delivered by the prober's own POST, and it is the only
member of the census that is.** The argument is one sentence: *a sink that has
stopped accepting cannot carry the news that it stopped accepting.* Everything
else here rides ClickStack because ClickStack can see it; this one, by
construction, is exactly the thing ClickStack never sees.

**What it watches.** `deploy/observability/alerts/prober.sh` scrapes the
**collector's own** Prometheus endpoint — `http://otel-collector:8888/metrics`,
on the compose network and published nowhere else
(`deploy/observability/collector-telemetry.yaml` says why the default
`localhost:8888` is not good enough) — and sums two things across every signal:

| Number | Metrics | What it means |
|---|---|---|
| `collector_lost_total` | `otelcol_exporter_send_failed_*` + `otelcol_exporter_enqueue_failed_*` | **Definitive.** Telemetry was lost and nothing gets it back. |
| `collector_queue` | `otelcol_exporter_queue_size` | **Early.** A healthy exporter drains within a second, so a 15-second sample reads 0; a sink that stopped accepting holds the batch. |

**Why both, when ADR obs-2 named only the failure counters.** Measured on
collector-contrib 0.140.0 against a sink that was simply not there: the
exporter's default `retry_on_failure.max_elapsed_time` is 300 s, so
`send_failed` **does not move for five minutes** after the sink goes deaf, while
`queue_size` reads ≥ 1 within one batch interval. Waiting for the definitive
number alone would make the declared detection window ~6 minutes; watching the
queue as well makes it ~45 seconds and costs nothing, because the two are OR'd
and each is named in the notification. The failure counters were **not**
replaced.

**Three conditions open it, and the message says which.** Each is counted as its
own run of consecutive windows, and any window that does not satisfy a condition
resets that counter to zero:

| `reason=` | The condition |
|---|---|
| `export_failures` | `collector_lost_total` GREW across `SINK_DEAF_WINDOWS` consecutive windows |
| `queue_backed_up` | `collector_queue` was > 0 across `SINK_DEAF_WINDOWS` consecutive windows |
| `collector_unreachable` | the metrics endpoint could not be scraped at all across `SINK_DEAF_WINDOWS` windows |

The third is there on purpose: **a collector nobody can ask is not a healthy
collector**, and treating "cannot tell" as "fine" is how a monitor lies. The
first reading after a start is a **baseline, never a growth** — `previous` is
unset until the first successful scrape, so a restart never pages.

**It opens ONCE and recovers ONCE.** The prober holds the state (`ok` / `deaf`)
in its own loop, so an outage that lasts an hour is one POST, not sixty — the
opposite cadence from the ClickStack-side alerts, and the difference is worth
knowing at 3am. Recovery is its own POST (`hdx_state=OK`), sent when all three
counters are back at zero.

**It also writes into the sink, and that is rule 19 stated both ways.**
`probe.sink.deaf` / `probe.sink.recovered` go out over OTLP as well as to the
webhook — best effort, because while the sink is deaf that line is exactly what
does not land, which is the point. **The POST is the delivery; the log line is
the record for whoever reads the sink afterwards.**

**Empty `SLACK_WEBHOOK_URL` DISARMS this half**, and the prober says so out loud
once per start (`prober: !! THE DEAF-SINK HALF IS DISARMED …`) rather than
failing quietly. A probe that silently cannot deliver is worse than no probe.

---

## Who is pinged, and what they read FIRST

**Today: whoever watches the Slack channel the webhook posts to.** A template
has one person on this rota, and pretending otherwise would be a schedule
nobody keeps. Widening it is the product's own decision, made here.

**What they read first, in order:**

1. **The message itself.** It carries the alert name, the state
   (`hdx_state=ALERT` when it opens, `hdx_state=OK` when the window goes quiet),
   the matching log lines, and a link into the sink.
2. **The fields in those lines** — for a transition alert: `event`, `tenant_id`,
   `connection_id`, `correlation_id`, `trace_id`. That is the "one link":
   paste the `correlation_id` into the sink's search and the whole request is
   there, with no repo access and no shell.
3. **The saved search behind the alert**, linked from the message. It is the
   same query the alert counts, so what the responder sees is what fired.

**Re-ping cadence.** A transition alert's interval is **5 minutes**; the outage
alert's is **1 minute**. ClickStack notifies once per breaching window, so an
alert that keeps breaching re-pings at its own interval and no faster. The
N-past-K re-probes inside an open surge produce **zero** pings — not because
the alert de-duplicates, but because the product emits no event for them (the
announce-on-transition ruling doing the work at the source, which is the only
place it can be done honestly).

**Observed, and it is a judgment call worth revisiting:** a three-minute
outage produced **three** pings, one a minute. That is the honest reading of a
one-minute interval — the thing is still down — and it is also how a channel
gets muted during a long incident. The lever is the outage alert's `interval`
in `definitions.json`; widening it to `5m` trades a slower first ping for a
quieter one. It is left at `1m` because an outage's FIRST ping is the one that
matters and nobody has yet sat through a real long one here.

---

## What closes it — read this before standing down

**The recovery has its own alert now. A "window quiet" notification is still
not it.**

ClickStack's alerting is windowed: it counts matching rows in the last
interval, opens when the count crosses the threshold, and auto-resolves the
first window that does not. So `comms.suppression.surged` — a single event,
emitted once on the crossing — opens the degraded alert in the window it lands
in, and that alert resolves itself one window later **whether or not the surge
is over**. Its OK notification is a statement about a query window, not about
the circuit.

**What that used to mean, and it was a real hole.** `comms.suppression.recovered`
reached the sink and fired **nothing at all** — no alert watched that name, so
the one event that means "it is over" was the one event nobody was told about.
Confirmed over the wire: the recovery event written, zero POSTs.

**So the recovered half is its own alert** (ADR obs-2 as amended: *"the
recovery event is its own notification … delivered as a second alert rather
than a close"*). One declared pair yields **two** alerts:

| Alert | Watches | Its OPEN means | Its OK means |
|---|---|---|---|
| `<prefix> degraded` | `<prefix>.surged` | the circuit went down | the 5-minute window stopped matching — **not** a recovery |
| `<prefix> recovered` | `<prefix>.recovered` | **the circuit came back** — this is the all-clear | the window stopped matching |

**Each alert owns its own opening sentence, and that is forced.** A ClickStack
webhook owns its body template and an alert only references one by id, so the
first attempt gave the recovery alert its own webhook — and ClickStack refused
it: **a webhook is unique by URL, not by name** (`400 Webhook already exists`,
found by trying it). So the shared body now renders `{{body}}` — *the alert's
own message* — for the ALERT state and nothing else, and each alert supplies its
own emoji and verb. The degraded alert opens with `:rotating_light: OPENED`; the
recovery alert opens with `:white_check_mark: RECOVERED`. One webhook, one
destination, one secret, one `slot and length` line at apply time.

The OK branch is the same sentence for every alert, because it means the same
thing for every alert: `:mag: window quiet — <alert> — the query window stopped
matching, which is NOT a verdict about the circuit`.

**Match the two to one episode by `correlation_id`** — both saved searches
select the same columns for exactly that reason.

**What it costs, stated: four notifications per episode instead of two.**
Degraded opens, degraded window-quiets, recovered opens, recovered
window-quiets. That is option 2 of the three below, and it is now the one that
is built.

**Deviation, recorded, not papered over.** ADR obs-2 originally said "alert
opens on surged, closes on recovered". ClickStack cannot express that: a state
that persists across windows either re-pings every window or resolves itself,
and there is no third behaviour in `checkAlerts`. The three options, priced:

| Option | Cost | Gives |
|---|---|---|
| Leave it, message says so | 0 | one open ping, one window-quiet ping, an honest message — and **no announcement of the recovery at all** |
| A second alert per pair on the recovery event (**what is built**) | one more alert and one more webhook per pair; **four** notifications per episode instead of two | a real "recovered" announcement, delivered rather than inferred |
| A tile alert over a running open-count | a ClickStack Source with a synthetic timestamp expression; untested cleverness in a template repo | true open/close, at the price of a re-ping every window while open |

---

## What this CANNOT see — declared, not implied

- **The death of the box it runs on.** ClickStack, the collector and the prober
  are all on the same host as the thing they watch (ADR deploy-1: one
  environment per box). If the box dies, nothing pings. **Until a product buys
  an external check, box-death is discovered by the owner's browser, and that
  is a declaration, not an oversight.** The cheap close is a $0-tier external
  uptime check on `https://<env>.example.invalid/readyz`; it is not bought yet.
- **A dead webhook.** Nobody monitors the monitor's delivery. **The weekly
  test-ping duty** below is the whole guard.
- **A ClickStack that ACCEPTS and fails to index.** The deaf-sink alert reads
  the **collector's** counters, which say "we could not hand it over" — that
  covers a stopped sink, a refused connection and a rejected key. A sink that
  answers 200 and then loses the row is invisible to it. Declared, not
  discovered: HyperDX's own health is a product's operating concern, and the
  amendment says so.
- **A stack started by hand.** `provision.sh up`'s refusal and
  `teardown.sh --all-mine`'s census both read `docker compose ls`. A stack
  somebody brought up with `docker run`, or with a compose file from another
  path, is not seen by either.
- **A slow drip.** `SURGE_THRESHOLD = 25` addresses per tenant per trailing hour
  (`apps/comms/services.py`); twenty-four an hour, for ever, is invisible. That
  is the wall's declared blind spot, inherited here.
- **A slow spray under the threshold.** The auth-failure spike opens at 20
  refused sign-ins inside one 5-minute window; nineteen every five minutes, for
  ever, is invisible, and so is a spray spread across windows. It also counts
  lines, not tenants: twenty refusals at one tenant and one at each of twenty
  tenants are the same alert, because the saved search groups nothing.
- **A logging outage reads as calm.** A spike counts the log lines the app
  wrote; an app that stopped writing them looks exactly like an app nobody is
  attacking. The probe half watches the sink, not the app's emission.
- **A deployment that exports no server spans reads as calm.** Both trace
  alerts count server spans. Under uvicorn the Django instrumentor makes one
  only when `opentelemetry-instrumentation-asgi` is installed (pinned in
  `pyproject.toml` since `f634a9556`); a deployment that drops it exports client
  spans and **no server spans at all**, and both alerts are silent by
  construction. Measured 2026-10-21: 1331 client spans and 0 server spans
  without it; 81 server spans and both alerts opened with it.
- **A p95 over too few spans.** A class with fewer than `MIN_SPANS` (20, the
  load drive's `MIN_WINDOW_SAMPLES`) server spans in a 5-minute window reads 0,
  so a quiet deployment's slowness is invisible rather than noise: three slow
  requests in five minutes never page.
- **An error the span never records.** A connection refused at Caddy, a request
  killed before Django's middleware runs, a worker that died mid-request: no
  server span, no count. `/readyz`'s probe is the guard for the box-level
  shapes.
- **A share, rather than a count.** `error_rate` counts 5xx; it does not divide
  by traffic. A busy deployment reaches 12 at a smaller share than a quiet one,
  and a quiet one can sit at 50% errors under 12 a window. The ratio is a
  chart, not this alert.
- **Slack accepting the message.** The laptop dummy proves the POST leaves
  ClickStack with the right body. Only the real destination proves Slack
  takes it.
- **A name assembled at runtime.** `census.py` reads `events.py` with `ast`, so
  a name built by concatenation would be invisible — a shape `events.py` is not
  allowed to have (house rule 16: names only, constants only).

---

## The weekly test-ping duty

**Every Monday, one command, and one look at Slack.** A webhook that has been
revoked, rotated or archived fails silently, and the failure is only visible on
the night it matters.

```bash
set -a; . deploy/.env; set +a
curl -sS -X POST "$SLACK_WEBHOOK_URL" \
  -H 'Content-Type: application/json' \
  -d "{\"text\": \"alert-route test ping — $(date -u +%FT%TZ)\"}"
```

Expect `ok` and a message in the channel. **If either is missing the alert
route is down and nothing else in this file is true.** Re-run `apply.py` after
rotating the slot, because the URL is copied into ClickStack's own store at
apply time and a rotated secret does not reach it by itself.

---

## Values, and why each one

| Value | Setting | Why |
|---|---|---|
| Transition alert interval | 5 min | short enough to matter, long enough that an open surge re-pings at most twelve times an hour |
| Outage alert interval | 1 min | an outage is measured in minutes, not windows |
| Outage threshold | **3** failures in a window (ClickStack's `above` is `>=`) | at a 15-second probe that is 3 consecutive failures — one blip never pages |
| Probe interval | 15 s | judgment value (`PROBE_INTERVAL_SECONDS`); the arithmetic below depends on it |
| **Declared detection window — `/readyz`** | **3 × 15 s = 45 s of failing probes + up to 60 s of check latency = under 2 minutes** | recorded, **never gated** |
| `SINK_DEAF_WINDOWS` | **3** consecutive windows | the same 3-of-N shape as the outage alert, for the same reason: one blip never pages |
| **Declared detection window — deaf sink** | **3 × 15 s = 45 s, and no check latency at all** | the prober POSTs directly, so there is no sink-side interval between detection and delivery — the one advantage of the alert that cannot ride the sink |
| Deaf-sink re-ping cadence | **none: one POST to open, one to recover** | the prober holds the state in its own loop, so a one-hour outage is two POSTs |
| Auth-failure spike threshold | **20** `accounts.signin.refused` lines in a window (`>=`) | `apps/accounts/events.py`'s `SPIKES` — the worked example's number; a product declares its own |
| Auth-failure spike interval | **5 min** | the declared window; ClickStack checks it as the alert's `interval` |
| **Declared detection window — auth-failure spike** | **≤ 5 min for the window to hold 20 + up to 60 s of check latency** | recorded, **never gated** |
| Latency budgets | **500 ms** p95 reads (`GET`/`HEAD`), **1000 ms** p95 writes, over server spans | the acceptable tier's bar (`census.py` `READ_BUDGET_MS`, `WRITE_BUDGET_MS`); the alert's value is p95 over budget, opening at 1 (`>=`) |
| Latency interval | **5 min** | one window of the tier's measurement; `MIN_SPANS` = **20** spans per class per window, or the class reads 0 |
| **Declared detection window — latency** | **≤ 5 min for the window to close + up to 60 s of check latency** | recorded, **never gated**; a window is judged after it closes |
| Error-count threshold | **12** server spans answering 5xx in a window (`>=`) | `ERROR_COUNT`: 0.5% of the tier's floor load, eight closed-loop clients at one request a second or more for 300 s |
| Error-count interval | **5 min** | the same window as latency |
| **Declared detection window — error count** | **≤ 5 min + up to 60 s of check latency** | recorded, **never gated** |
| `SURGE_THRESHOLD` | 25 distinct addresses / tenant / trailing hour | `apps/comms/services.py`, ADR comms-9 — not this file's to set |

---

## Installing the route

**Precondition for the two trace alerts:** `opentelemetry-instrumentation-asgi` is in `pyproject.toml`; without it the app under uvicorn exports no server spans and both trace alerts are silent.

```bash
# 1. The values. The delivery URL comes from the slot, on the box, under the
#    instance role — never from a shell somebody typed it into.
./deploy/provision.sh secrets-fetch "$DJB_DEPLOY_NAMESPACE/$DJB_ENV/" deploy/.env   # box only
set -a; . deploy/.env; set +a
# The release runs this in-network (release.sh act 5, in-container). A hand
# run must NOT use the walled public address; run apply/export in-container instead.
# The container is the `oneoff` service (docs/runbooks/deploy.md Part 1),
# which declares no depends_on — which is why these lines no longer carry
# --no-deps. There is nothing left to skip.
export CLICKSTACK_ADMIN_EMAIL=... CLICKSTACK_ADMIN_PASSWORD=...

# 2. See what will be created, without creating it.
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm -T -e CLICKSTACK_URL -e CLICKSTACK_ADMIN_EMAIL -e CLICKSTACK_ADMIN_PASSWORD -e SLACK_WEBHOOK_URL oneoff python /app/deploy/observability/alerts/apply.py --dry-run

# 3. Create it. Idempotent — re-running is the normal case.
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm -T -e CLICKSTACK_URL -e CLICKSTACK_ADMIN_EMAIL -e CLICKSTACK_ADMIN_PASSWORD -e SLACK_WEBHOOK_URL oneoff python /app/deploy/observability/alerts/apply.py

# 4. Prove what is running is what is in the tree.
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm -T -e CLICKSTACK_URL -e CLICKSTACK_ADMIN_EMAIL -e CLICKSTACK_ADMIN_PASSWORD -e SLACK_WEBHOOK_URL oneoff python /app/deploy/observability/alerts/export.py
```

`apply.py` refuses, rather than defaults, when `SLACK_WEBHOOK_URL`,
`CLICKSTACK_ADMIN_EMAIL` or `CLICKSTACK_ADMIN_PASSWORD` is missing. It prints
the destination as **host and length**, never as a value.

**The prober needs no `-f` of its own any more.** It is the `readyz-prober`
service in `deploy/compose.yaml`, so it comes up with every deployment — an
override file is how a deployment ends up with an alert path that is only armed
when somebody remembers a second `-f`. `PROBE_INSECURE` and `PROBE_CONNECT_TO`
are written into `deploy/.env` by `provision.sh env-file` (`1` and
`localhost:443:caddy:443` on a laptop; `0` and empty on a box, which is what puts
public DNS in the probe's path). **On a box there is nothing to add at all:**

```bash
./deploy/provision.sh up
```

On a laptop, add the dummy destination and point the slot at it:

```bash
# in deploy/.env:  SLACK_WEBHOOK_URL='http://alerts-dummy:9099/hook'
./deploy/provision.sh up \
  -f deploy/observability/alerts/compose.sink.yaml \
  --profile laptop
```

`provision.sh up` is the no-second-stack refusal in compose's vocabulary: it reads
`docker compose ls`, adopts the project already running from this checkout
(writing the name into `.env` so every later bare `docker compose` lands on it
too), and **refuses** to start a second project beside a running one unless you
say `--second` and mean it.

---

## What the drills demonstrate, and what to record

The drills below are written to be run as written; what follows is what a
correct run looks like, so a performance can be read as pass or delta rather
than as a story.

**One POST per transition, not one per window.** The prober holds `sink_state`
in its own loop, so a continuing outage produces no further POSTs after the
open. That is the opposite cadence from the ClickStack-side alerts, which
re-ping every breaching window — and it is why the two are distinguishable.

**`reason=queue_backed_up`, not `export_failures`.** The exporter's
`retry_on_failure.max_elapsed_time` is 300 s, so `collector_lost_total` reads
**0** for the first five minutes of a deaf sink and the failure counters say
nothing. Watching `queue_size` as well is what makes the detection window
45–60 s instead of ~6 minutes, and the notification says which of the two it
saw.

**The app's own `/readyz` stays 200 through a sink outage**, and the readyz
alert must not fire — the app was never down. Two alerts, two questions.

**Detection arithmetic, observed against declared.** Declared is 3 × 15 s =
45 s; an observed open lands a little later — the partial window in progress
when the sink went deaf, plus one scrape. Expected, and the reason the declared
number is recorded rather than gated.

**The census prints its members and their total**, derived here from
`deploy/observability/alerts/census.py` itself:

<!-- derived: alert-census -->
`ALERTS = 2 pair(s) x 2 + 1 spike(s) + 2 trace alert(s) + 2 probes = 9`
<!-- /derived -->

`apply.py` creates every member but the one the prober delivers, printing for it:

```
[skip] sink deaf: delivered by prober, not by this sink (deploy/observability/alerts/prober.sh)
```

**The open POST carries, verbatim:** the degraded event name, the tenant, the
connection id, the correlation id, the trace id, and a link into the sink. That
is the "one link", and it comes out of the saved search's `select`, not out of
prose.

### Three defects a dummy destination catches that a screenshot does not

Each is fixed in the definitions here, and each is silent without a receiver
that counts:

1. **`above` means `>=`.** `threshold: 0` makes *every* window breach,
   including the empty ones, and the alert sits in ALERT with a count of 0.
2. **`GET /alerts` does not return the alert's own `name`.** A reconciler
   keyed on it creates a duplicate alert on every run. The key is the saved
   search's id.
3. **Handlebars parses the webhook body before it is JSON.** `\"` inside
   `{{#if (eq state \"ALERT\")}}` is a parse error; ClickStack logs one line
   into `/var/log/app.log` inside its own container and drops the
   notification. **Silently, from the destination's point of view.** Single
   quotes fix it.

---

## Performing the drills

They are written to be run as written; the section above says what a correct
run looks like.

### Drill 1 — the surge path

```bash
# zero POSTs at the dummy before anything is driven
docker compose -p djb-a1s exec alerts-dummy sh -c 'cat /var/log/dummy/requests.jsonl 2>/dev/null | wc -l'

# K+5 = 30 distinct hard bounces on the seeded test connection, inside the hour
# (apps/comms/tests/test_suppression_wall.py is the shape; the seeded
#  connection is `manage.py seed`'s)
# ... then five more re-probes past K: expect ZERO additional POSTs
# ... then let the trailing hour fall under K and record one more status:
#     comms.suppression.recovered

# count and classify
# `json.loads` PER LINE, not `json.load` over the file: the dummy writes JSON
# LINES (one object per POST, appended), and `json.load` reads the first object
# and then dies on "Extra data" at the second. It did — and the `|| cat` below
# swallowed the traceback and dumped the raw file, so the classifier looked like
# it had classified something. The fallback is kept, but the failure is no
# longer silent.
docker compose -p djb-a1s exec -T alerts-dummy python3 -c \
  "import json;[print(e['at'],e['state'],e['text'][:80]) for e in (json.loads(l) for l in open('/var/log/dummy/requests.jsonl') if l.strip())]" \
  || { echo '!! the classifier failed — raw file follows'; \
       docker compose -p djb-a1s exec -T alerts-dummy cat /var/log/dummy/requests.jsonl; }
```

The record's keys are the dummy's own — `at`, `path`, `state`, `valid_json`,
`text`, `raw` (`deploy/observability/alerts/dummy_receiver.py`). There is no
`json` key; `state` is the `hdx_state=` token the receiver parses out of the
message text, which is what makes counting ALERT vs OK a `grep` rather than a
judgement.

**Or ask the dummy instead of parsing its file.** It serves the same records,
already decoded, as a JSON array:

```bash
docker compose -p djb-a1s exec -T alerts-dummy \
  python3 -c "import urllib.request,json;print(json.dumps(json.load(urllib.request.urlopen('http://localhost:9099/_log')),indent=2))"
```

**Expected:** exactly one POST with `hdx_state=ALERT`, exactly one with
`hdx_state=OK`, zero from the N-past-K re-probes. Read § "What closes it"
before reading the `OK` one as a recovery.

### Drill 2 — the outage probe

```bash
date -u +%FT%TZ                                   # t0
docker compose -p djb-a1s stop web
# watch the dummy; record the POST's timestamp
docker compose -p djb-a1s logs -f alerts-dummy
docker compose -p djb-a1s start web               # recovery
```

**Record** t0 → POST as an observation against the declared window (under two
minutes). **Never gate on it.**

### Drill 3 — portability

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm -T -e CLICKSTACK_URL -e CLICKSTACK_ADMIN_EMAIL -e CLICKSTACK_ADMIN_PASSWORD -e SLACK_WEBHOOK_URL oneoff python /app/deploy/observability/alerts/export.py --out /tmp/alerts-before.json
docker compose -p djb-a1s down
docker volume rm djb-a1s_clickstack_data
docker compose -p djb-a1s ... up -d               # the same command as above
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm -T -e CLICKSTACK_URL -e CLICKSTACK_ADMIN_EMAIL -e CLICKSTACK_ADMIN_PASSWORD -e SLACK_WEBHOOK_URL oneoff python /app/deploy/observability/alerts/apply.py      # registers the operator on a fresh volume
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm -T -e CLICKSTACK_URL -e CLICKSTACK_ADMIN_EMAIL -e CLICKSTACK_ADMIN_PASSWORD -e SLACK_WEBHOOK_URL oneoff python /app/deploy/observability/alerts/export.py --out /tmp/alerts-after.json
diff /tmp/alerts-before.json /tmp/alerts-after.json     # expect: no difference
```

**A hand edit anywhere in that sequence is a failure of the criterion**, not a
step.

### Drill 4 — no session in the path

```bash
grep -ri "mcp\|claude" deploy/observability/ docs/runbooks/alerts.md
```

**Expected:** only the § "Two Slack paths" sentence in this file, which says
the MCP path is NOT the alert path. Anything else — a definition naming a
laptop-side transport, a script shelling out to a session tool — is the
criterion failing.

---

## The end-to-end evidence a real destination owes

The drills above prove the route with a dummy receiver. Proving it reaches a
human takes one more performance against the real Slack webhook, and its
evidence is **five timestamps in this order**, from Slack's own permalinks and
whatever ledger records the sessions:

| # | Event | Timestamp |
|---|---|---|
| 1 | the last session that could have been watching ends (after arming the stop on the box with a detached scheduler ≥ 20 min out) | _pending_ |
| 2 | the second session ends — the ledger's "no session" row | _pending_ |
| 3 | the alert's Slack `ts` | _pending_ |
| 4 | the responder's one-word in-thread reply `ts` | _pending_ |
| 5 | the next session's start | _pending_ |

The criterion is the **ordering**: 1 < 2 < 3 < 4 < 5 — it is what proves the
alert reached a person with nothing of ours alive to deliver it. The arming
mechanism is `systemd-run --on-active=…` (or an equivalent detached scheduler)
**on the box** — a drill control, not application code; the workflow rule
governs the product and the box's scheduler is the drill's hand. If no alert
arrives within the declared window + 10 minutes, the answer is "nothing" and
the route is **red**.
