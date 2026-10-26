# ADR core-14

- **ADR core-14 (the append-only runtime belt)** · context: an
  instance-`.save()` tamper on an append-only member drove clean through
  the full gate — rule 20's AST half
  cannot see a bound-name save, and P4's DB grant protects production
  only · decision: `BaseModel`'s `save()`/`delete()` refuse the
  update/delete path for any model in the declared append-only population
  (`AppendOnlyViolation`), population-driven off `APPEND_ONLY_ATTR` at
  zero per-model cost; rule 20's static half learns bound-name instance
  saves (Q1); three belts stated honestly: static (gate) + runtime (this)
  + DB grant (P4, production) · rejected: a per-model mixin (re-opens ADR
  core-6's MRO churn for a property the declaration already carries),
  queryset-level `.update()` interception in the manager (rule 20's
  static half + the DB grant already cover the bulk path; a fourth belt
  at the queryset layer buys marginal coverage for real manager
  complexity — the declared residue) · trigger to revisit: a measured
  bulk-path tamper the two remaining belts miss.
