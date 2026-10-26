# ADR core-22

**ADR core-22 · the audit row contract: NIST SP 800-53 AU-3 read
onto `AuditEntry`'s existing columns.** *Context*: the compliance reviewer is a
persona the BAAs make real, and an early probe found the trail
answering them by accident of service signature — `actor_user_id` None on every
row, mint rows missing `object_id`, failed calls naming no credential; every
column present, no contract saying what a conforming row is. The contract
vocabulary is **NIST SP 800-53 AU-3, "content of audit records"** — the
standards grounding owner-ratified directly ("agreed with your
recommendation"). AU-3's content elements are questions this table already has
columns for, so the standard is adopted as a **reading discipline, not a
migration: no new column is required**, and AUDIT-2's plumbing changes what the
existing columns are *handed*, never what they are. (Rules read against:
G2/G3 — the columns being contracted; D8/rule 20 — append-only grounds the
no-backfill ruling; E9 — the `error_code` vocabulary; 16 — the `action`
vocabulary.) The model is `apps/core/audit.py`; the one writer is the
`@service` decorator (`apps/core/service.py`); the mapping:

| AU-3 content element | `AuditEntry` column(s) | the reading |
|---|---|---|
| **type of event** | `action` | `<app label>.<service>`, built by the decorator from the function itself — the `@service` population IS the event vocabulary (rule 16's verb grammar), never a free string at a call site |
| **when** | `created_at` | UTC (`USE_TZ`), written once (`auto_now_add` on an append-only row); the recorded moment is itself a protected fact (an idempotent re-call never moves it) |
| **where** | `door` + `tenant` + `acting_org` | `door` ∈ rest·mcp·socket·workflow·webhook·admin·shell, bound into context by the door and read from nowhere else; `tenant` places the row's population — NULL is the declared platform population, ADR core-8 (b), never a loosening; `acting_org` is the hat the door resolved: which part of the tenant the call acted *as* |
| **source** | `request_id` · `session_id` · `correlation_id` · `causation_id` · `trace_id` | `correlation_id` minted at the door and never below (G2); `causation_id` the immediate parent; the join keys that survive restarts and days, riding the workflow headers and the Temporal memo |
| **outcome** | `outcome` + `error_code` | `ok`/`error`; on error the **registered** refusal code — E9's registry is the vocabulary, so every code on a row resolves in `introspect`'s refusals section |
| **identity of associated individuals, subjects, objects** | `actor_user` · `actor_token` · `actor_kind` — and `object_type` + `object_id` + `input` | who acted (the actor half; semantics per door below) and what was acted on (the object half; `input` redacted per `LOG_KEYS`) |

*Actor semantics per door — and there are THREE kinds, closed.* A **session**
call (REST session auth; the admin) is `human`: `actor_user` set, `actor_token`
None — a person clicked. A **bearer** call (REST or MCP; sockets when the
bearer path lands) is `agent`: `actor_user` AND `actor_token` set —
`actor_from_request`'s own doctrine, quoted: "the person authorised the machine
once, months ago, and 'a human clicked this' is not true of it." A
**workflow, schedule or shell** call is `system`: `actor_user` None
**honestly** — `system_actor`'s docstring is the text: "attributing an
overnight reconciliation to whoever happened to trigger the process last week
is how an audit trail becomes fiction." **Ruled: there is no fourth
"workflow" kind.** The `door` column already carries workflow-ness, and the
run rides `correlation_id`/`causation_id`; a fourth kind would split the
`system` population in two for no reader's benefit.

*The legitimate absences* — enumerated so a reviewer meeting a gap knows
whether it is the contract or a defect (five at authoring; absence 1
generalized and self-reports added, absorbing the AUDIT-2b rulings; the conditional admin placeholder that briefly stood as (vi) resolved
**removed** the same day — the L3 check found the seam present, so no absence
ever existed there; AUDIT-3-PRE):

1. **The population altitude.** A sweep acts on a population, not a row,
   and its one audit row is a **declared shape**, never a degenerate one:
   `object_type` = the swept model's label, `object_id` NULL — a blank label
   on a sweep's row is a violation, not a tolerated default (L6). **The
   count's home is the typed `Swept` result and the structured log line in
   the sink (G1) — deliberately NOT the row** (ruled at AUDIT-3-PRE):
   `input` is by contract the service's redacted *arguments* and the seam
   never sees a return value; a count without the row ids verifies nothing
   — the ids were ceded at this altitude on purpose — so putting it on the
   row would buy an unverifiable number at the price of either a
   one-row-class column on an append-only table or a second seam
   convention. trigger to revisit: a compliance ask that requires the count
   from the trail alone — then the expand-only column, never a second
   valve. `accounts.erase_user` is the founding member: an
   erasure sweeps the person's credentials in one `.update(revoked_at=...)`
   and those deaths are audited as the one erasure row, the correct altitude
   for the action somebody took — "erase this person" — so the per-row
   absence is the contract, not a miss. The sweep services are allow-listed
   **by name** with this ground — today's census:
   `connections.purge_inbound_webhooks`, `events.purge_dispatched_outbox`,
   `events.purge_deliveries`, `exports.purge_exports`,
   `files.purge_pending_versions`, `workflows.purge_finished_runs` —
   and the membership AUDIT-3's rule checks is the list in `rules.yaml`,
   never this prose.
   **Amended 2026-10-03 (owner, SIGNED 2026-10-03 15:48 ("sign core 22",
   recorded by the PM); proposed by the lead at bd6144b6 on C-QUAL-3's
   rule-49 derivation):** Absence 1 is declared by the purge factory: a
   sweep `core.schedules.daily_purge` reaches, with the factory's declared
   signature `(*, before, tenant: None) -> Swept`, is an absence by
   construction; the by-name census remains for sweeps the factory does not
   reach. Rejected: the by-name list alone (a typed population every app
   rung edits — the W6 serializer class). Trigger to revisit: a sweep that
   needs a second signature. The six names above are the census as it stood
   at authoring; the list in `rules.yaml` keeps only what the factory does
   not reach, and a name the factory covers is deleted there, not kept.
2. **Workflow-driven writes.** A service called from an activity records
   `kind=system`, `actor_user` None. The human cause is upstream at the door
   that started the run, and it is *reachable*, not restated: the causation
   chain joins the system row to the door row where the person is. This
   absence, like 6 (and like 1 until its 2026-10-03 amendment), is a **by-name
   census, never a shape** — the
   members take no `actor` kwarg at all, because machine work has no actor
   to take, and each carries its `# authz: machine-work` valve, held to it
   by AUDIT-2c's MACHINE_WORK census. Today's census (the rule-49 birth
   condition's find, 2026-08-26): `accounts.ensure_membership`,
   `events.enqueue_dispatch`, `events.close_outbox`,
   `events.record_delivery_attempt`, `events.dead_letter_delivery`,
   `workflows.record_run`, `workflows.finish_run` — and the membership the
   rule checks is the list in `rules.yaml`, never this prose.
3. **Platform-token actions.** A credential pinned to no workspace writes
   rows with `tenant` NULL — the declared platform population (ADR core-8
   (b), which this contract cites as the ground and now re-homes the
   citation of). Those rows are absent from every tenant's trail **by
   construction** — `for_tenant` can never see them — and the platform
   question is asked with the platform's own word, `for_platform()`.
4. **The shell door's person.** A management command's row is `door=shell,
   kind=system`, `actor_user` None — and that row IS the contract, not a
   defect: the box's own access audit (ssh) owns *who held the shell*, and
   this table does not duplicate an authority it cannot verify. What the row
   does owe — the door, the tenant acted on — AUDIT-2 threads explicitly
   (`system_actor(tenant=…)`), so the shape is deliberate, never defaulted.
5. **The pre-contract population, declared with its date and NO backfill.**
   Every row written before 2026-08-26 predates this contract — including
   the six live-stage revocation rows with `actor_*` None, and every
   credential death before the revoke ruling below, which was never recorded at all.
   None of it is backfilled, and the ground is structural, not
   preferential: `AuditEntry` is append-only (rule 20; the model's own
   `save()` refuses a second write), and **a backfill is an UPDATE on a
   ledger — forbidden by the very rule that makes the table evidence.** A
   trail whose gaps are dated and declared is evidence; a trail somebody
   helpfully completed is not.
6. **Self-reports.** A service whose subject is the platform's own state —
   the `announce_*` members — names no object: **empty object fields ARE the
   contract**, because there is no row the announcement is about; the
   announcement itself is the fact (L8). Allow-listed
   by name, membership post-L8-check — today's census:
   `example.announce_widget_onboarded`, `search.announce_degraded`,
   `search.announce_recovered` — and AUDIT-3's rule reads the checked list,
   never this prose.

*Outcome semantics — a refusal is filed as claimed (L11, KEEP as
capability).* A refused call's row (`outcome=error`) records the claim **as
the caller claimed it** — that is the capability, not a leak: "what did my
people *attempt*" is a question the compliance reviewer owns, and a trail
that drops refused attempts cannot answer it. No oracle opens: the pk in
`input` is the caller's own bytes returned to the trail, and E9's
`not_found` doctrine already refuses existence confirmation on the wire. Two
pins: the `error_code` on a refusal is the **registered** code, never prose;
and a refusal row carries **no object** — `object_type`/`object_id` stay
empty, because nothing was acted on.

*Two rulings this contract cites where they live, rather than restating.*
The **object convention** (L7) is owned by `core.service._object_of`'s own
docstring — the declared chain is `audit_object` → the first `models.Model`
in a tuple or dataclass result → nothing, and attribute-reading is ruled NOT
the rejected reshaping (the four typed sweep results covered with zero edits
to the types); this ADR points at the seam and renders no second copy. The
**escalation wall's exemption re-key** (L1): the wall's spelling moves from
actor-is-None to `kind == system` — an exemption becomes a named, audited
altitude — one sentence here, cited to the wall's own docstring once
AUDIT-2c lands it.

*SIEM export is a derived mapping, computed at export time from these rows —
never a storage shape.* A product that acquires a SIEM obligation writes an
exporter that walks `AuditEntry` and emits one OCSF event per row: `action` →
the activity / API operation of the OCSF activity class the product selects,
`created_at` → `time`, the actor columns → `actor.user` / `actor.session`,
`door` → the metadata provenance, `outcome` + `error_code` →
`status`/`status_id`, the correlation ids → `metadata.correlation_uid`. The
columns above carry everything such an export needs, so the mapping is a pure
function of the rows and can be written the day it is owed. **CADF and
OCSF-as-storage are rejected, with the ground the owner ratified verbatim
(2026-08-26): this is an internal table under rule 20, not a SIEM feed, and a
storage redesign buys a vocabulary nothing here reads.**

*Provenance, and the id this absorbs.* The revoke ruling
was first published under a sub-label appended to core-8's id — colliding
with core-8's own **(a)** entry (an early finding). **The decision
moves here**: this ADR is its home, the ruling stands unchanged in substance
(moved from `cycles/2026-08-25-cycle-p10-the-true-envelope.md` §MICRO-1's ADR
line, the id rewritten to this one — the only edit), a cross-reference stands
at core-8, and the retired rendering must reach zero in `apps/` and in this
file — **a census by grep, never a site list** (misses P8 #1); archived cycle
files are exempt as history, not guidance. The docstring sweep is AUDIT-2's.
The absorbed ruling: *context*: `revoke_token` was exempted from the audit
population by core-8's declares-tenant rule; a trail recording credential
births and not deaths · *decision*: revoke declares `tenant`
(required), call sites pass `token.tenant`, the service refuses a mismatch;
null-tenant deaths join the platform population beside their births;
already-revoked is an idempotent no-op · *rejected*: the standing
asymmetry (fails the trail's purpose), a defaulted tenant (core-8's own
sync_workforce lesson), Conflict on re-revoke (DELETE is idempotent by HTTP
law; the moment is the fact being protected) · trigger to revisit: a second
credential-shaped model wanting the same birth/death pairing.

*Rejected*: **a fourth "workflow" actor kind** (the `door` column carries it;
a split `system` population serves no reader); **a backfill of the
pre-contract population** (an UPDATE on an append-only ledger — structurally
illegal under rule 20, absence 5's ground); **CADF** (a vocabulary nothing
here reads, adopted into storage); **OCSF as the storage shape** (the same
ground — the internal table is rule 20's, the SIEM shape is an export's);
**new columns** (every AU-3 element already lands on an existing column — a
contract that can be met by reading discipline must not be met by schema).
trigger to revisit: the first product with a SIEM export obligation (the
export paragraph becomes a rung), or a compliance ask AU-3 cannot answer from
these columns. *Blind spot, resolved then
narrowed (AUDIT-3-PRE)*: the L3 check found the admin actor seam
**present** — `ServiceModelAdmin.acting()` (`apps/core/admin.py`) builds the
actor from the request and the door stamps `admin` by path — so the
conditional absence that briefly stood in the list above was removed; no
absence ever existed there. What remains declared, narrowed to what the
check actually saw: the seam is only as good as each `call_service` that
uses it. `TenantAdmin.call_service` was found **dropping the actor for
`create_tenant`** — and the rider's fix found the hole deeper than the drop:
`create_tenant` itself was **laundering every caller's identity as
`system_actor`** before the wall ever saw it — the row said the product
acted when a person had. It now takes a required `actor` and forwards it
(AUDIT-3's rider, proven with a failing test written first: an admin-created tenant's row carries the staff
member, `door=admin`), so the admin-seam assertion above is true **without a
counter-example**. And the operator trio (`suspend_tenant` /
`resume_tenant` / `close_tenant`) is reachable from **no door today**: its
`# door:` valve names manage.py and the admin, neither of which exists —
building the operator surface is booked separately, and the valve's stale claim is
corrected in that work.
