# ADR core-9

- **ADR core-9 — TWO decisions share this id**; both stand, both cited.
  **(a) `ordered_by` keeps the selector's ordering as tie-breakers**
  · context: `ordered_by` calls `.order_by(wanted)`, which
  **replaces** the queryset's ordering — any door promising a secondary
  sort silently loses it (`list_templates` did; the apology comment written
  against that gap still stands above `apps/comms/api.py::list_policies_route`'s
  return, stale since this decision) · decision: `ordered_by` re-applies
  the incoming queryset's existing ordering as tie-breakers after the
  requested field (dropping only a duplicate of the requested field
  itself), so a selector's promise survives the door · rejected:
  allow-list entries as field-tuples (pushes the fix to every route),
  documenting the loss (a promise a client cannot see is broken is not a
  contract) · trigger to revisit: a route that must deliberately replace ordering →
  an explicit `replace=True` parameter, then.
  **(b) `PLATFORM_CONTEXT` crosses on the bridge** · context:
  `platform_context()` is the declared accessor a
  platform-run activity may use, but `apps/workflows` sits above
  `apps/accounts`, so a builder working below that layer could not reach
  it and reported rather than smuggled — today the two platform kinds in
  `apps/accounts/activities.py` simply *skip* context resolution,
  asserting nothing; and the `"platform"` segment is now stated three
  times (`workflows/services.py:111` the owner, `core/services.py` and
  `accounts/services.py:723` the pinned repeats) — the queue row's named
  trigger for the bridge constant, fired · decision: the bridge gains
  `PLATFORM_CONTEXT = "workflows.platform_context"` with a
  `ReadsPlatformContext` shape in `SHAPES`; `apps/workflows` registers
  `platform_context` from `ready()` beside its existing names; the
  accounts platform kinds resolve scope through
  `bridge.get(bridge.PLATFORM_CONTEXT)()` and the loud contract travels
  with it — a platform kind invoked under tenant-stamped headers fails
  loudly instead of proceeding cross-scoped. The two segment *constants*
  stay where they are: the bridge carries callables with shapes, not
  values, and both repeats are already pinned against the owner by named
  tests (`test_move_matrix.py`, `test_federation.py`) — a pinned repeat
  is a contract, an unpinned import path is a wish · rejected: importing
  `apps.workflows.context` from accounts (the layer violation the bridge
  exists to invert), a fourth restatement of the behavior locally in
  accounts (the drift this ADR exists to stop), putting the segment string
  itself on the bridge (a constant is not a callable; the SHAPES contract
  has no meaning for it) · trigger to revisit: a second app below the
  platform needs platform scope → the key is already there; nothing to
  decide.
