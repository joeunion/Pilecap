# ADR core-8

- **ADR core-8 — TWO decisions share this id**; both stand, both cited in
  the tree, recorded here together rather than renumbered.
  **(a) emit-side datetime normalization** · context: ninja
  renders datetimes through `NinjaJSONEncoder`/`DjangoJSONEncoder`
  (milliseconds); `emit()` stores pydantic's `model_dump(mode="json")`
  (microseconds) — same instant, two strings, template-wide · decision:
  **emit-side normalization**: `emit()` round-trips its payload through
  the exact encoder class the REST door renders with, so `Event.payload`
  == the REST body byte-for-byte and E3's sentence ("webhook clients see
  what a REST client sees") becomes literally true; REST bytes unchanged ·
  rejected: a microsecond renderer in `config/api.py` (changes every
  datetime on the wire; "REST is the contract" — ADR example-3's own
  precedent — and re-pins its byte-identical proofs), per-call-site
  truncation (open set; the next emitter forgets) · trigger to revisit: a consumer
  needing sub-millisecond precision → a versioned payload.
  **(b) AuditEntry's platform population** · context: `@service` writes
  the audit row only when
  `tenant is not None` (`apps/core/service.py:346`), so every
  platform-scoped action — a tenantless erasure, the workforce identity
  sync, and other platform-scoped actions besides — is *logged, not audited*: the one
  compliance-shaped trail has a hole exactly where the compliance actions
  are · decision: **mirror ADR workflows-3, shape for shape** —
  `AuditEntry.tenant` becomes nullable (ONE expand migration, the cycle's
  only leaf), **null is a declared population, not a loosening**:
  `for_tenant(...)` keeps failing closed and can never see a platform row
  (every tenant door — admin changelist included — is unchanged by
  construction), `for_platform()` on the manager is the one read path
  (same name, same docstring posture as `WorkflowRun`'s), the `@service`
  decorator becomes the population's one writer (`tenant` kwarg present,
  value None), and `append_only` covers the null rows exactly as before —
  rule 20 unchanged, rule 8 gains its 7th standing platform-population
  override, recorded · rejected: **a sentinel platform tenant**
  (workflows-3's own rejection, and rows of other models would accrete
  onto it), **a separate PlatformAuditEntry model** (two trails; every
  incident reconstruction must union them forever), **status quo** (an
  erasure's revocation with no audit row is the same hole in a different
  place) · trigger to revisit: a third model needs a platform population
  → workflows-3's own trigger fires and the shape generalizes or becomes
  a base. *(The AuditEntry platform-partial index — `condition=Q(tenant__
  isnull=True)`, never a bare tenant-blind index — is this ADR's shape, as
  measured and recorded.)*
  **There is no third sub-label on this id.** A later revoke ruling that
  briefly wore one — colliding with **(a)** above — lives at **ADR
  core-22**, which absorbed and renamed it.
