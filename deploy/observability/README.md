# The sink, and the questions it answers

**ADR obs-2's sink half, as code.** The deployment already runs the pipe —
`web`/`worker` → `otel-collector` → ClickStack, all on the compose network, the
endpoint set by `OTEL_EXPORTER_OTLP_ENDPOINT` in `deploy/.env` and nothing else.
What lives here is the half that has no home in a container: **the questions**.
Dashboards and saved searches are a posture, and a posture that lives only in
one container's Mongo volume dies with the container — which is what
`import.py` and `export.py` exist to prevent.

**Nothing in this directory is edited by hand after the first time.** Draw a
dashboard in the ClickStack UI, run `export.py`, commit what changes. That is
the loop; `import.py` is how it reaches the next sink.

## What is here

| Path | What it is |
|---|---|
| `hyperdx/hdx.py` | the API client both commands share, and the portability rule |
| `hyperdx/import.py` | put every saved search and dashboard into a ClickStack (idempotent by name) |
| `hyperdx/export.py` | pull them back out, ids stripped, sources named |
| `hyperdx/saved-searches/*.json` | seven questions, one file each |
| `hyperdx/dashboards/*.json` | "The pipe — one id, door to delivery" |
| `queries/*.sql` | the same questions as plain ClickHouse SQL, readable with no HyperDX at all |
| `alerts/` | the alert definitions and the prober — a separate concern, and it owns that directory alone |

## The ids ride on log lines, not on spans

Not a defect — a design decision that decides how every query here is written,
and getting it wrong costs an operator an hour.

`correlation_id`, `request_id`, `session_id`, `door`, `tenant_id` and `org_id`
are bound into structlog's contextvars and rendered onto **log records**
(`apps/core/observability.py`'s processor chain). Spans get the reverse
treatment: `_add_trace_ids` puts `trace_id`/`span_id` onto the log line, but
nothing puts the business ids onto the span. So:

```sql
-- returns nothing, always
WHERE SpanAttributes['correlation_id'] = '…'
-- the query that works
WHERE LogAttributes['correlation_id'] = '…'
```

The join from a chain to its spans is therefore `otel_logs.SpanId =
otel_traces.SpanId`, which is what `queries/o1-2a-the-trace.sql` and
`queries/o1-3-the-worker-logs.sql` do. A trace-first product would want
`span.set_attribute("correlation_id", …)` in `core/service.py`; this one is
log-first and the ids are complete there, so the cost is one JOIN rather than a
missing answer.

## The sink's ingestion key is minted by the sink

`CLICKSTACK_API_KEY` cannot be generated ahead of time. ClickStack's all-in-one
image runs its collector under an OpAMP supervisor whose OpAMP server is the
HyperDX API itself: until a team exists — until a human has completed first-run
setup in the UI — the configuration it hands that collector wires the OTLP
receiver into no pipeline, so nothing binds 4317/4318 and every span and log
line is dropped after the exporter's retry budget with `connection refused`.
The stack reads as completely healthy while this is true; the collector's own
log is the only witness. The key is minted by HyperDX at first-run setup and
travels out of the UI into `deploy/.env`, which is why `provision.sh` carries
it as DEFERRED rather than GENERATED and why the runbook's observability part
has a step for it.

*Declared blind spot:* nothing in the tree fails when the sink is deaf. A
`/readyz`-shaped check on the collector's export queue, or an alert on "the
sink stopped receiving", is the answer — named here, not built here.

## The portability rule, stated once

**No file here stores a HyperDX object id.** A fresh ClickStack has a fresh
team, a fresh connection and fresh sources, each with a new Mongo ObjectId; an
export that recorded `"source": "6a8a66…"` would import into a sink where that
id means nothing, and every saved search would come back pointing at no data.
The JSON names its source instead — `"sourceName": "Logs"` — and `import.py`
resolves the name against the target's own `/api/sources` at import time. That
is the difference between an export and a backup, and it is what makes the
re-import onto a fresh volume work rather than appear to.

**One id is not instance-local and must survive**: a dashboard *tile*'s `id` is
the author's layout handle, not a Mongo ObjectId, and the API rejects a tile
without one. `export.py` therefore drops `id` only where `_id` sits beside it.
An export looks perfect against the sink it came from whether or not it is
portable, which is why a re-import onto a fresh volume is performed rather than
assumed.

## Running it

Both commands take the same five variables. `DJB_O11Y_CONNECT` is `curl
--resolve` and belongs to laptop stacks only: macOS resolves `o11y.localhost`
for curl but Python's `getaddrinfo` refuses a multi-label `.localhost` name, so
the socket is opened at that address while the `Host` header and the TLS SNI
stay the routed name. A real environment has real DNS and leaves it unset.

```bash
export DJB_O11Y_BASE=https://o11y.staging.example.invalid
export DJB_O11Y_USER=observer                 # the Caddy wall (deploy/Caddyfile)
export DJB_O11Y_PASSWORD='…'                  # printed once by provision.sh env-file
export DJB_O11Y_EMAIL=you@example.com         # the HyperDX login
export DJB_O11Y_PASSWORD_HDX='…'

python3 deploy/observability/hyperdx/import.py          # create what is missing
python3 deploy/observability/hyperdx/import.py --replace # overwrite by name
python3 deploy/observability/hyperdx/export.py           # pull the UI's state back to disk
```

On a laptop stack, add:

```bash
export DJB_O11Y_BASE=https://o11y.localhost:8453   # your stack's DJB_HTTPS_PORT
export DJB_O11Y_CONNECT=127.0.0.1:8453
export DJB_O11Y_INSECURE=1                         # Caddy's internal CA
```

## The seven questions

Each saved search is one question an operator asks at 3am, in the order they
ask them.

| # | The question | Where it looks |
|---|---|---|
| 01 | Which business chains just ran, and what are their ids? | logs, `correlation_id != ''` |
| 02 | What happened to **this** chain, door to delivery? | logs, one `correlation_id` |
| 03 | Is everything that waits actually running? | logs, `ServiceName = 'worker'` |
| 04 | Which activity ran, under which deterministic workflow id, how long? | traces, `RunActivity:%` |
| 05 | Which deliveries did not land? | logs, the delivery-failure events |
| 06 | What is writing right now, through which door, for which tenant? | logs, `%.called` |
| 07 | What is broken? | logs, `SeverityText IN ('error','fatal','warn')` |

Search 02 ships with a placeholder correlation id. **The id is the one field
you edit** — paste yours and the same query answers the same question about
your chain.
