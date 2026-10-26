# ADR obs-2

- **ADR obs-2 (the sink is live, and it speaks)** · context: the
  Observability pillar's pending cell names this pass; the compose
  already ships otel-collector + ClickStack behind
  `--profile observability`; `core/observability.py` is the one
  configuration point; the announce-on-transition ruling gives P4 the
  ALERTING rung consuming degradation events, with hard deps explicitly
  outages (/readyz), not events · decision: staging runs the same
  collector→ClickStack pair as compose does locally, endpoint set by
  env; dashboards/saved searches/alert definitions live in
  `deploy/observability/` as exported config-as-code; alerts are
  ClickStack-native over the sink — the closed alert census: (1) each
  declared transition-event pair (today exactly
  `comms.suppression.surged`/`.recovered`), alert opens on surged,
  closes on recovered — the 1:1 the transitions-only design bought; (2)
  a /readyz probe from the collector's healthcheck receiver (or blackbox
  equivalent in the compose) alerting on N consecutive failures;
  delivery to the owner's Slack webhook; the escalation path documented
  in `docs/runbooks/alerts.md` (who, what they read first, re-ping
  cadence) · rejected: alerting through comms itself (comms is a product
  organ under test — the monitor must not share the patient's failure
  domains; the ruling's "comms can route it" stays open for products,
  with the spine events already there), CloudWatch as a second sink (G1:
  a second sink is where the reconstructing query dies; CloudWatch keeps
  only what AWS emits for free), per-request alerts (the ruling forbids
  them — transitions only), a new house rule for "every circuit alerts"
  (the second-circuit extraction is the ruling's own named trigger; not
  yet) · trigger to revisit: the second runtime circuit lands (extract
  the shared primitive, then consider the rule), or telemetry volume
  outgrows the container (ClickHouse Cloud w/ BAA, the documented
  scale-up). **Amended (the PM's ruling, recorded by the lead), appended
  to the decision sentence:** "Alert lifecycle, corrected: ClickStack
  alerts are windowed counts with
  auto-resolve — they cannot close on an event. So an alert **opens on
  the degradation event** appearing in the sink and **auto-resolves
  after N quiet windows** (N a declared constant in the definition,
  stated in `alerts.md`); the **recovery event is its own notification**
  (one message, the 1:1 the transitions-only design bought, delivered as
  a second alert rather than a close). Two non-event alerts stand beside
  the event pairs: the /readyz probe and the deaf-sink probe, both on
  the prober's own POST because neither can ride the sink. The census
  derivation names the event half by AST and the probe half explicitly."
