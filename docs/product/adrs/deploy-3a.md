# ADR deploy-3a

- **ADR deploy-3a (one JSON secret per environment)** · context: the cost
  table priced "~8 secrets × $0.40"; `provision.sh secrets-put` stores
  one JSON object under `<namespace>/<env>/env` · decision: one secret per
  environment, the manifest's names as keys; the cost table's Secrets
  Manager line becomes **~$0.40/mo** · rejected: one secret per value
  (eight fetches at start, eight rotations to coordinate, the same blast
  radius — the box's role reads the prefix either way) · trigger to
  revisit: per-value rotation with different cadences, or a second
  consumer that may read one value and not the rest.
