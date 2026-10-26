# ADR core-7

- **ADR core-7 (Measured)** *(an earlier draft of this decision named
  `Measured`/`MeasuredBasis` in prose — the importable symbols are
  `MeasuredOut`/`MeasuredBasisOut`, rule 16's suffix)* · context: the basis contract ("a number the UI never
  computes") was honored over a hundred times in an earlier consuming
  product by convention; the
  architect's diff-guard argument won at the panel · decision: generic
  `Measured` schema in `apps/core/schemas.py` — `value: Decimal`,
  `basis: MeasuredBasis(formula: str, inputs: dict[str, Decimal])` —
  plus conventions/architect entries; **enforcement at criteria-tier,
  honestly**: "any endpoint returning a computed aggregate" is an open set
  no closed question can scope (doctrine 1), so the lead's checklist gains
  the line and the blind spot is declared, not disguised as a rule ·
  rejected: an AST rule recognizing "computed aggregates" (walked past
  without malice — the sibling's six-times lesson) · trigger to revisit: a closed
  population emerges (e.g. a declared `*Stats` schema suffix convention)
  → revisit as a rule.
