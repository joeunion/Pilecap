# `deploy/observability/alerts/` — the alert route, as code

The escalation path, the values and the drills live in
**`docs/runbooks/alerts.md`**. This file says only what each artifact here is,
so a reviewer knows which one to open.

| File | What it is |
|---|---|
| `census.py` | Derives the alert census from `apps/*/events.py` — the transition pairs and the declared `SPIKES` — and names the two deployment-wide trace alerts (`TRACES`) and the probes. **The population.** Run it: `python3 deploy/observability/alerts/census.py` |
| `definitions.json` | The shape of each alert, the saved search behind it, and the delivery webhook. **No destination URL — the Secrets Manager slot name only.** |
| `apply.py` | Reconciles a ClickStack to census × definitions. Idempotent. The only importer. |
| `export.py` | Reads the live config back out and diffs it against the census. The portability instrument. |
| `prober.sh` | **Both alerts that cannot ride the sink.** Curls the public `/readyz` and writes `probe.readyz.{ok,failed}` into the sink over OTLP; scrapes the collector's own export counters and **POSTs `alert.sink.deaf` itself**, because a sink cannot announce that it stopped accepting. Was `readyz_probe.sh` until it grew the second half — a name that lies is a violation here, not a nuance. |
| _(no `compose.probe.yaml`)_ | The prober is a service in `deploy/compose.yaml` (`readyz-prober`), not an override. An override file is how a deployment ends up with an alert path that is only armed when somebody remembers a second `-f`. |
| `compose.sink.yaml` | Compose override adding the **laptop-only** dummy destination. |
| `dummy_receiver.py` | The dummy: answers 200, logs every POST as JSONL so a criterion can count them. |

**There is no `alerts` app and no `events` consumer, and that is a decision.**
ADR obs-2 put alerting **on the sink** and rejected alerting through the app —
"the monitor must not share the patient's failure domains". An app-side
consumer would be that rejected shape under a new name. Everything here is
config and one shell loop; nothing under `apps/` changed for it.

**A spike's numbers are its app's:** the auth-failure spike's 20 in 5 minutes
is the worked example's, and a product declares its own in its own app's `events.py`.
