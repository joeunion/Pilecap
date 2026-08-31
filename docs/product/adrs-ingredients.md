> **RATIFIED** (PM under owner delegation #3): all five stack
> rulings accepted as recommended — MinIO+S3 one-seam · Postgres FTS
> per-model · Anthropic direct w/ Bedrock PHI escalation · Twilio+FCM ·
> ledger-only metering. Wave order adopted: ING-1 alone, then ING-5/2/4a,
> then ING-3/4b.
> **ING-2 subsequently re-ruled by the owner the same day: Meilisearch
> ships in v1** — see § ING-2's preamble (ADR search-2); the pg design
> survives as the degradation engine. The other four rulings stand.
> **ING-1 re-cut the same day (ADR files-2, ING-1D pair): versioning
> native + `files.storage.bytes` metering per the v1 feature-surface
> rulings; the MinIO+S3 stack ruling stands.** Enforcement renumbered per
> the PM landing-order assignment: 31 = lifecycle declarations (P5's) ·
> 32 = the storage wall · 33 = the search fence · 34 = the model door.

# ADRs — THE INGREDIENTS (ING-1..5, the ratified twelfth pillar)

**Status: DESIGNED (ING-0, architect). The five designs are the
engineering lead's; each STACK RULING is the owner's to ratify async — a
recommended default is attached to every one, with the price of each
alternative stated. Nothing here reopens a settled decision in
`architecture.md`; where a design *refines* a settled line, it says so loudly
and the refinement rides the stack ruling.**

Scope source: `queue.md` § "THE INGREDIENTS", ratified. Consumer
of record: a first consuming product built on this platform.
Build slot: P6–P7 per the T0 track — ING-1 alone likely a full cycle, the
others pair per the concurrency discipline.

Rules cited by id are the architect skill's (`A*`, `C*`, `D*`, `E*`, `G*`)
and the house rules as `architecture.md` numbers them. **No ingredient
touches `apps/core`.** Every ingredient is a new platform-tier app or growth
of an existing one, registered by discovery; the import-linter layers
contract needs **no edit** (the `comms` precedent: unlisted apps sit above
the fixed layers, governed by `depends_on` + rule 7).

Cross-ingredient seams follow §I+: a seam two rungs share exists **in the
tree** (a service signature, a schema, a discovered module name) before the
dependent rung dispatches.

---

## ING-1 · storage & documents — `apps/files` (versioning native · presigns as the security surface)

> **Owner rulings, the preamble this re-cut stands on:
> versioning is IN** — it post-dates files-1, which modeled a single
> immutable blob per row — and **quota-COUNTING is in** (an ING-5 meter,
> never an enforcement gate). Sharing links and previews are OUT with named
> triggers (§ exclusions). The MinIO+S3 one-seam stack ruling was ratified
> under delegation #3 and stands untouched: the re-cut changes the object
> model *above* the seam, never the seam.

**ADR files-2 (ING-1D design pair, owner-directed; supersedes
files-1's body — files-1's stack ruling stands ratified, and its two-phase
upload, `store_bytes` seam, archive-not-delete, tenant-settings policy and
wall posture all survive intact below) · context:** every product needs
object storage with the walls already built (a first consuming product: issued documents,
papers, template artifacts, digests of "the bytes *we stored*"), file
handling is the single most leak-prone surface a product improvises, and
the owner ruled versioning into v1: "replace this document" is a
first-class act, and a platform that models a file as one mutable blob
answers it with an overwrite — history destroyed, audit orphaned, and a
presigned URL whose meaning changes after issuance. **decision:**
`apps/files` with a two-model aggregate — `StoredFile` (the document:
identity, name, purpose, the walls) owning `FileVersion` rows (the bytes:
one **immutable object key per version**, digest, size, its own two-phase
lifecycle) — bytes never transit Django (presigned URLs both directions,
TTLs declared in settings), every issuance an audited service call,
"replace" = a new version finalized and promoted, never an overwrite;
stored bytes counted on ING-5's ledger at finalize. **rejected:** a
`version` column mutated in place on one row (replace rewrites
digest/size under every audit row and export manifest that cited them —
D9's exact target, applied to bytes); latest-pointer object keys and S3
bucket-versioning as the mechanism (both reasoned below);
`FileField`/media on domain models, public buckets or ACLs in any
configuration, and a generic-FK attachments framework (files-1's
rejections, all standing — the domain owns the edge: a product model
points at `StoredFile` with `PROTECT`, never the reverse). **trigger to
revisit:** direct-to-browser multipart uploads > 5 GB → S3 multipart
presigning grows inside `apps/files/storage.py`, same seam, per-part URLs
under the same wall.

### App/module map (A1, A2, B1)

| app | noun (aggregate) | depends_on | doors | workflows | events |
|---|---|---|---|---|---|
| `files` | `StoredFile` (+ `FileVersion`) | `core, accounts, usage` (+ bridge for events/workflows) | REST `/api/v1/files/` · MCP `files.*` | `FinalizeUpload`, `SweepPendingUploads` | `files.file.stored`, `files.file.archived` |

Canonical files: `models.py`, `storage.py` (**the one module that imports
boto3 and names the bucket settings** — the rule-27 shape, fenced by rule
32 below), `services.py`, `selectors.py`, `schemas.py`, `api.py`
(`PREFIX = "files"`), `mcp.py`, `workflows.py`/`activities.py`/`types.py`,
`meters.py` (the ING-5 vocabulary), `policies.py`, `events.py`,
`admin.py`, `tests/`.

### The document model (A5, C9, D2–D7, D9's spirit, D10; rules 2, 8, 15, 24)

`StoredFile(OrgScopedModel)` (A5 — a file belongs to the part of the
tenant that filed it; org-scoped is the default under uncertainty):
`filename` (the **renamable display name** — D10: the identity that
survives renames is the key, and the key lives on the version),
`purpose` (short label the audit trail reads: `upload`,
`generated-document`, `export`, …), `current_version` (int, 0 until a
first finalize — advanced only by `record_stored`), `uploaded_by` FK
user, `archived_at` (D7 — soft delete; no `is_deleted`).

`FileVersion(OrgScopedModel)`, `derive_org_from = "file"` (C9 — a version
lands where its document lives, never where the uploader's hat points):
FK `file` (`CASCADE` — owned child of the aggregate, D2), `version`
(int, allocated under `select_for_update` on the parent, E8), `key`
(immutable, unique, shaped `t/<tenant_pk>/f/<file_pk>/v/<version>`),
`content_type`, `size_bytes`, `sha256` (both blank until verified — the
digest of the bytes **we hold**, computed by us, never trusted from the
client), `status` (`TextChoices`: `PENDING → STORED`, D4 — transitions
only in services), `uploaded_by`, `created_at`. Constraints in
`Meta.constraints` (D3): unique `(file, version)`; unique `key`.

**Post-STORED immutability is the contract, held honestly:** a version row
transitions status once, so declaring `append_only` would be a lie (rule
20 is for populations nothing updates); the immutable half is the object,
the key and the digest — held by the presign fence (below), the
uniqueness constraints, and F5's overwrite probe, criteria-tier and said
so.

**Why two models and per-version keys — the rejections, reasoned:**

- **A `version` column mutated in place** — replacing rewrites `sha256`/
  `size_bytes` under the audit trail; "who uploaded v2, when, and what did
  v1 hold" becomes unanswerable; the export census loses per-version
  disposition (an export manifest that cited a digest must still be true
  months later).
- **Latest-pointer keys** (one stable key per file, overwritten per
  version) — a presigned GET issued before a replace silently serves the
  new bytes after it: the URL's audited meaning changes after issuance,
  the exact class the security surface exists to kill; old bytes are
  destroyed unless the backend versions them; and there is a
  digest-vs-object drift window mid-overwrite that no criterion can close.
- **S3 bucket-versioning as the version mechanism** — version identity
  becomes a backend-issued opaque id our rows must mirror anyway (two
  truths); MinIO/S3 parity becomes an assumption about versioning
  semantics instead of plain PUT/GET; retention moves into console
  lifecycle rules — the console is a window, not a door (rule 27's
  lesson, verbatim). Our rows are the intent; the bucket stays a plain
  keyspace.
- **Content-addressed keys** (the sha256 as the key) — cross-row dedupe is
  a cross-tenant existence oracle (an instant upload reveals someone else
  already holds these bytes); per-tenant prefix purge stops working;
  delete needs refcounts. Keys carry pks and a version ordinal only —
  never tenant slugs or filenames (files-1's line, kept).

**Tenant in the key, org deliberately not** (kept): re-parenting a branch
must not orphan object keys; the org is the row's, the key is forever.

**Size/type policy** (kept): `Tenant.settings` keys (schema-validated per
the platform table) + platform defaults, enforced inside the upload
services. The `FilePolicy(InheritedDownward, OrgScopedModel)` model stays
rejected with its trigger (the first product wanting per-branch file
policy → the D9/A5c-shaped model then).

### What "replace this document" means — the verbs (C1, C2, C4, C8, D4, E8)

Two-phase upload, now per version:

- `create_file(*, tenant, actor, filename, content_type, size_bytes,
  purpose)` → `StoredFile` + `FileVersion(version=1, PENDING)` + a
  short-TTL presigned PUT.
- `add_version(*, tenant, actor, file, content_type, size_bytes)` — **the
  replace verb** → `FileVersion(version=n+1, PENDING)` + presigned PUT.
  The old version is untouched: still readable, still presignable, still
  true for whatever recorded it.
- `confirm_upload(*, tenant, actor, version, idempotency_key)` → 202,
  starts `FinalizeUpload` on commit (C2).
- `record_stored(...)` (called from the activity): verifies, sets
  `STORED` + digest + size, **advances `current_version` only if the
  finalized version is numerically greater** (out-of-order finalizes
  converge on the highest stored version; under `select_for_update`, E8),
  meters `files.storage.bytes` in the same transaction (§ metering), and
  emits `files.file.stored` with the version in the payload.
- `archive_file(*, tenant, actor, file, reason)` → `archived_at` (D7);
  rows and objects stay until purge (the dated residual, § exclusions).
- `store_bytes(*, tenant, actor, filename, content_type, content: bytes,
  purpose, file=None)` — **the document-generation seam, kept and now
  versioning-aware**: one call an activity makes with rendered bytes;
  `file=None` creates a document at v1, `file=` versions an existing one;
  key, digest, size and the meter handled inside; emits the event. The
  renderer itself (PDF engine, paper templates) stays product work — the
  platform's half is that rendered bytes land scoped, digested, audited
  and versioned.

**An upload presign is issued only for a `PENDING` version** —
`create_file`/`add_version` mint it, and re-requesting one for a `STORED`
version refuses (a `Conflict`-class domain error through the one mapper,
E9). Belt where the backend supports it: the presigned PUT signs
`If-None-Match: *`, so even a leaked pre-finalize URL cannot overwrite an
object that already landed (MinIO and S3 both honor conditional writes);
the fence never depends on the belt — F5 proves the service-side refusal
stands alone.

### Presigned URLs — the security surface, stated honestly (C7, E9; rules 3, 13, 24)

- **Expiry policy, decided:** download GET **5 minutes**
  (`FILES_DOWNLOAD_URL_TTL`) — issued on demand, consumed by the click
  that asked; anything longer turns each issuance into a durable bearer
  credential. A UI that needs the bytes again re-issues, and re-issuance
  re-audits — so the audit trail approximates *use* at five-minute
  resolution, the best first-party approximation there is. Upload PUT
  **15 minutes** (`FILES_UPLOAD_URL_TTL`) — long enough for a large
  browser upload to begin on a slow link; short because the PENDING key
  it writes into is digested and size-checked at finalize regardless.
  Both are settings, per-env, defaults as stated.
- **A window, never single-use — honestly:** a presigned URL is a
  stateless signature; single-use does not exist without a stateful door
  in front of the bytes. Rejected: proxying bytes through Django to buy
  single-use (destroys the no-transit design); a first-party
  one-time-token redirect endpoint (a second credential system standing
  in front of S3's, and a bytes-adjacent Django route that becomes the
  load and leak surface). Trigger: a compliance demand that names
  single-use → the redirect-door ADR then, priced.
- **Scope binding — what a leak exposes, exactly:** the signature covers
  one method + one object key + the expiry, nothing else. A leaked GET
  exposes **the bytes of that one version until expiry** — no list, no
  sibling versions, no other tenant's keyspace, no write. A leaked
  upload PUT exposes **write access into one PENDING key until expiry or
  finalize** — whatever lands is then digested and measured by
  `FinalizeUpload`, so a hijacked pending upload produces a
  wrong-but-witnessed object, never a silent one; a declared residual,
  priced by the short TTL.
- **Audit semantics — issuance vs use:** issuance is the audited act.
  `issue_download_url(*, tenant, actor, file, version=None)` is a
  `@service` even though it writes no business row — the write is the
  `AuditEntry` (**audit on access**, files-1's line kept; G2's decorator
  is what makes a read auditable), and it records the file id **and the
  version it signed for**. **Use is not first-party observable** — the
  GET hits the object store, not us. The honest posture: S3 server
  access logs / CloudTrail data events are the use record; wiring them,
  and asserting access logging is on, is a **P4 production-pass posture
  note** (`storage_audit` gains that leg there). Until then the platform
  claims issuance, never use, and says so.
- **Refusal shapes (E9):** at the door, every issuance refusal is
  `not_found` — not-there ≡ not-yours, cross-tenant and sibling-branch
  alike; a presigned URL must never be the oracle that confirms a file
  exists. At the storage edge, an expired or tampered URL gets **S3's
  own 403, never re-dressed** — no Django sits in that path to dress it;
  the remedy is re-issuance through the audited door, and the schema
  docstring says so.
- **The seam's own belt:** `storage.py`'s presign functions refuse any
  key outside `t/<tenant_pk>/` for the tenant in hand — a signature over
  another tenant's key cannot be produced even by a confused caller
  inside the wall.

### Doors (E1, E2, E6, E7; rules 3, 16, 17)

- REST: `POST /api/v1/files/` (create → `{file, version, upload_url}`);
  `POST /{id}/versions` (**the replace door** → `{version, upload_url}`);
  `POST /{id}/versions/{n}/confirm` (202 → `FinalizeUpload`); `GET /`
  (paginated list, E6 — current-version metadata, archived excluded);
  `GET /{id}`; `GET /{id}/versions` (the history, paginated);
  `POST /{id}/download-url` (audited issuance; body may name `version`,
  default current); `POST /{id}/archive`.
- MCP parity (rule 17): `files.create`, `files.add_version`,
  `files.confirm`, `files.get`, `files.list`, `files.list_versions`,
  `files.issue_download_url`, `files.archive`.
- **Deliberately door-less** (kept, extended): **the bytes** — no route
  ever streams object content through Django, presigned GET/PUT only; no
  socket, no webhook surface; S3 event notifications stay rejected (a
  second inbound door for what `FinalizeUpload` verifies itself;
  trigger: virus-scanning demand → the notification lands in
  `connections` like any provider webhook); and **version deletion** —
  no door deletes a version; purge is the platform's, dated in the
  exclusions.

### Walls (A5, C7, C8, C9; rules 3, 13, 24, 26)

Reads: `.for_tenant(t).visible_to(actor)` everywhere (rule 24); versions
reached through their file. Authz actions in `policies.py`:
`file.create`, `file.read` (download-URL issuance), `file.replace`
(`add_version`), `file.archive`. Every service taking a `StoredFile` or
`FileVersion` parameter passes it through `may_be_named` (C8, rule 26);
refusal is `not_found` (E9). `derive_org_from = "file"` on `FileVersion`
(C9). Keys carry pks only — never tenant slugs or filenames (D10's
spirit: the identifier outlives renames).

### Events / workflow split (C2, E3, E4; rules 9, 18, 28)

Events: `files.file.stored` (v=1, payload `StoredFileOut` — carries the
finalized `version`, its digest, and the resulting `current_version`),
`files.file.archived` (v=1). *Rejected, kept:* `files.file.download_issued`
as an event — the audit row is the record; an event is for subscribers and
none exists (trigger: the first subscriber). *Rejected, new:* a
`version_superseded` event — promotion rides `stored`'s payload; a
subscriber that cares reads `current_version`.

Workflows: `FinalizeUpload` — id `workflow_id(tenant, "files", "version",
key=<version_pk>)` (**per-version**, rule 18: two versions of one file
finalizing concurrently are two runs, never one); activities
`verify_object` (head-object + streamed sha256, retry policy declared at
the call site) → `record_stored` (the service; closes its run per rule
28). `SweepPendingUploads` (Temporal schedule, `owns_no_run = True`)
expires `PENDING` versions past TTL; a file left with no `STORED` version
is archived by the sweep, with the audit row saying so. Object **purge**
on archive/erasure/close stays the dated residual (§ exclusions) —
archive is soft (D7) and the object stays until purge lands.

**No silent fallback, stated (the search-2 posture):** the storage seam
has no degradation engine — an unreachable backend refuses loudly
(`Unavailable` through the one mapper), never a quiet retry pretending to
work; if a designed fallback ever lands here, its state transitions
announce themselves on the spine as declared events (the
`search.engine.degraded`/`recovered` precedent, ADR search-2) — **a
degradation the system survives is a state it announces, never just
tolerates.**

### Metering — the ING-5 seam (C4; the quota-COUNTING ruling)

`apps/files/meters.py` declares **`files.storage.bytes`** (the
`<app>.<noun>.<unit>` grammar, validated at import by ING-5's registry).
**Counted at finalize:** `record_stored` calls
`apps.usage.services.record_usage(meter="files.storage.bytes",
quantity=<verified size_bytes>, ref=<version>, idempotency_key=<version
pk + meter>)` in the same atomic block as the status write — an activity
retry never double-meters (C4), and a rolled-back finalize leaves neither
row (C2). **Archive never decrements** — archived bytes are still held
bytes; the meter measures storage, not visibility. **Purge, when it
lands, records a negative entry** per purged version — a new witnessed
fact with its own `ref`, never a supersede (ING-5's supersedes pattern
corrects *mistakes*; a purge is not a mistake). *Rejected:* counting at
upload-create (counts bytes that may never land); decrement-by-supersede
(miscasts a fact as a correction); any live counter (ING-5's stack
ruling, binding here too). **Enforcement is out by ruling** — counting,
never refusing: no write path consults the ledger to block an upload; the
threshold surface is ING-5's `usage.threshold.crossed`, cross-referenced
there.

### What v1 deliberately excludes, each with its trigger

- **Sharing links** (a URL handed to someone outside the tenant) — OUT
  (owner ruling). A share is a public door: its own token row,
  revocation, expiry policy and audit surface — never a longer-TTL
  presign wearing a feature name. Trigger: the first product demand →
  its own ADR.
- **Previews / thumbnails** — OUT (same ruling). Rendering, when it
  comes, is a workflow writing derived bytes back through `store_bytes`;
  taste stays the product's. Trigger: the first picker or UI that needs
  one.
- **Quota enforcement** — counting only, per the ruling; a refusing quota
  is a product decision built on the ledger and the threshold event.
  Trigger: a product asks → its own services, its own ADR.
- **Object purge** — the dated residual, kept: objects persist behind
  archive/erasure until purge lands; the rule-31 declaration below is
  honest about it today. Trigger: retention demand or the first tenant
  close.
- **Multipart > 5 GB** — the ADR's trigger-to-revisit above.
- **Virus scanning** — trigger: demand → S3 event notification into
  `connections` (files-1's line, kept).

### Rules & canaries born with it

- **Rule 32 — bytes go through the store** (renumbered from files-1's 31
  per the PM landing-order assignment — **31 = P5's lifecycle
  declarations · 32 = this wall · 33 = the search fence · 34 = the model
  door**; mirror of 25/27): no module under `apps/` outside
  `apps/files/storage.py` imports `boto3`/`botocore` or names the
  bucket/storage settings (`config/settings/` excepted, where env is
  read). Canaries: a planted `import boto3` in a domain app; a planted
  settings name outside the allow-list — both fire through the real scope
  at self-test or exit 2. Negatives: `apps/files/storage.py`, tests.
  Second clause, same rule: no ACL grant in `apps/files/storage.py` — a
  planted `ACL="public-read"` fires. `does_not_cover` (declared, rule-27
  style): **the bucket's own policy in AWS** — the console is a window;
  the belt is `manage.py storage_audit` (read-only: public-access-block
  on, no public ACLs; the access-logging leg joins at P4), the runtime
  tripwire P4 wires up.
- **Rule 31 — lifecycle declarations (P5's rule, referenced, never
  defined here):** the object store is an off-ORM population and declares
  itself **purged-by-callable** through the P5 registry —
  `delete_tenant_objects(*, tenant)` (prefix delete on `t/<tenant_pk>/`),
  reached from `close_tenant`'s walk by discovery, never hand-listed (the
  ING-2 Meili-documents posture, verbatim). Until purge lands, the
  declaration carries the honest interim retention line (the dated
  residual above). `StoredFile`/`FileVersion` rows are ordinary ORM
  populations, dispositioned by the export census like the rest.
- Criteria-tier: sibling-branch 404 byte-identical to absence (E9);
  TTLs honored wire-true; recorded digest equals a local recomputation
  (E10's spirit — the basis is checked); **a version key is never
  overwritable** — F1–F5 below carry these.

### STACK RULING ING-1 (ratified under delegation #3 — stands; the re-cut changes the object model above the seam, not the seam)

**Recommended default: MinIO (dev/test/worktrees, in `compose.yaml`) +
S3 (prod, by env), spoken to through one boto3-backed seam
(`apps/files/storage.py`) — not through django-storages.** This *refines*
the platform-table line "django-storages, local default, S3 by env": that
line predates the two-phase presigned design; django-storages' value is
`FieldFile` semantics we deliberately do not use (bytes never transit the
app), and local-disk cannot presign, so "local default" would make the
upload contract untestable in the gate.

- **S3-only (including dev)** — price: every worktree and CI run needs AWS
  credentials and network; the gate stops being hermetic (the exact property
  worktree-per-rung exists for). Rejected as default.
- **MinIO-dev + S3-prod via django-storages** — price: a dependency whose
  main abstraction (FieldFile) is unused, presigning driven through a
  storage class designed for a different flow; buys a backend swap we do
  not want (the seam is already one module).
- **django-storages abstraction, local default** — price: the presigned
  contract (the whole door design) has no local implementation; dev and
  prod diverge on the core mechanism. Rejected.
- Recommended default's own price, stated: one more compose service
  (MinIO), and an S3-compatibility assumption (MinIO tracks the S3 API;
  the seam is one module if it ever drifts).

### Dependencies & size

**ING-1 → P4 (provisioning):** the prod bucket, IAM policy (per-env,
least-privilege, presign-capable), public-access-block, the secrets ARNs,
and the new access-logging/`storage_audit` leg land in P4's production
pass per the AWS standing posture (Secrets Manager → env; the app reads
env only). MinIO lands with ING-1 itself. **ING-5 → ING-1 (the meter
seam, new):** `record_usage`'s signature must be in-tree before F2
dispatches (§I+ — a seam is code, not prose); ING-1 runs in wave 1 before
`apps/usage` builds, so the expected path is the **signature-only merge**
ING-3's seam already records as the escape — or F2 lands meter-less and a
named F-line adds the entry after U1; the lead sequences and says which.
**ING-1 → ING-2 (deferred):** extracted-text search over stored documents
needs an extraction activity + ING-2 adoption; trigger recorded, no build
edge now. **ING-1 → P5's export rung:** the export archive is written
through this app (`store_bytes`, purpose `export`) and handed out by
`issue_download_url` — the export rung's recorded dependency, the reason it may
trail into P6. Migrations: `apps/files/migrations/0001_initial` (leaf).

**Size: 5 rungs** — the decomposition below.

### The lead's decomposition — five rungs, draft criteria (the build-cycle lead finalizes)

Rules cited per set; every criterion here is a draft shape the dispatching
lead hardens with instruments and absent-case results (dispatch-briefs,
stage 4). Sequential, one app, one leaf.

**F1 · models + the storage seam + compose** — `apps/files` (new app:
`models.py`, `storage.py`, `schemas.py`, skeleton) + `compose.yaml`.
Size M. Cites A1, A2, A5, B1, C9, D2–D7, D10, E8's groundwork; rules 2,
8, 15, 22, 24.
1. `StoredFile` + `FileVersion` land per the model section; constraints
   (`unique (file, version)`, unique `key`) in `Meta.constraints` (D3);
   `derive_org_from="file"` proven — a version created under a hat
   pointing elsewhere lands in the file's org or refuses at
   `full_clean` (C9).
2. Key derivation unit-proven: `t/<tenant_pk>/f/<file_pk>/v/<n>` —
   tenant present, org absent, stable under file rename (D10).
3. `storage.py` is the only boto3 importer; `presign_put` /
   `presign_get` / `head` / streamed-sha256 / prefix-delete exist with
   typed signatures (the seam later rungs and P5's export consume, §I+);
   the presign functions refuse a key carrying another tenant's pk (the
   belt), unit-proven.
4. MinIO joins compose with healthcheck + named volume; the bucket name
   derives per-checkout (the `DATABASE_NAME` derivation precedent), so
   two checkouts and every xdist worker use disjoint buckets and
   parallel gates never meet in MinIO.
5. Migration `0001_initial` is the leaf; expand-only (rule 22).

**F2 · upload services + `FinalizeUpload` + the meter** — `apps/files`.
Size L. Cites C1, C2, C4, C7, C8, D4, E8, E9; rules 9, 10, 13, 18, 26,
28.
1. `create_file` / `add_version` / `confirm_upload` / `record_stored` /
   `store_bytes` exist `@service`, keyword-only, authz actions named
   (rule 13); every `StoredFile`/`FileVersion` param through
   `may_be_named` or its `# reach:` line (C8, rule 26).
2. A failed create leaves no row, no `Outbox` row, no `WorkflowRun`
   (C2).
3. `confirm_upload` twice with one idempotency key → one run (the id is
   per-version, rule 18, cited); a retried `record_stored` → one
   `STORED` transition and **one** meter entry (C4 — proven by a doubled
   activity call).
4. `verify_object` trusts nothing from the client: a test uploads bytes
   disagreeing with the declared size, and the recorded `sha256`/
   `size_bytes` are the measured ones.
5. Version allocation under concurrency: two concurrent `add_version`
   calls yield v(n+1) and v(n+2), never a duplicate (E8,
   `select_for_update`); out-of-order finalizes converge
   `current_version` to the highest `STORED` version (both orders
   tested).
6. An upload presign for a `STORED` version refuses (`Conflict`-class
   through the one mapper, E9); where MinIO honors `If-None-Match` the
   belt is wire-asserted, and the criterion passes on the service-side
   refusal alone where it does not.
7. The meter rides the transaction: a `files.storage.bytes` entry with
   quantity = verified bytes exists iff the finalize committed; a
   rolled-back finalize leaves neither (C2 + C4).
8. `files.file.stored` emitted inside the transaction, v=1, payload
   carrying version + digest + `current_version` (E3).

**F3 · doors + the download audit** — `apps/files` (`api.py`, `mcp.py`,
`selectors.py`). Size M. Cites C6, E1, E2, E6, E7, E9, G3; rules 3, 5,
12, 16, 17, 24.
1. Every route carries explicit `auth=`; both lists `@paginate`d with
   filter schema + ordering allow-list; Postgres query count pinned at
   seeded scale (rules 3, 5).
2. MCP parity: every REST capability has its tool; the same row's
   `StoredFileOut` byte-equal through both doors (rule 17).
3. Issuance is audited: `AuditEntry(action=issue_download_url,
   door=rest|mcp)` records file id **and version**; a refused issuance
   is audited with its refusal outcome and yields no URL (G3).
4. **Version pinning wire-proven:** a URL issued for v2 serves v2's
   bytes (digest-checked) after v3 lands and is promoted — an issued
   URL's meaning never changes post-hoc.
5. TTL honored wire-true against MinIO: an expired GET refuses at the
   storage edge with the backend's own 403, un-re-dressed; the
   re-issuance remedy line exists in the schema docstring.
6. `Idempotency-Key` behavior named on every write route (E7): the same
   key twice returns the first response and one version row; the same
   key from another tenant is a fresh request.
7. Sibling-branch and cross-tenant issuance → `not_found`,
   byte-identical to absence (E9), on both doors.

**F4 · sweep + archive + events + the lifecycle declaration** —
`apps/files`. Size M. Cites C2, D7, E3, E4, G3; rules 9, 18, 28, 31
(referenced).
1. `SweepPendingUploads` expires `PENDING` versions past TTL (Temporal
   schedule; `owns_no_run` posture cited); a file left with no `STORED`
   version is archived by the sweep with an audit row saying so.
2. `archive_file` sets `archived_at`; the archived file is absent from
   every list door and refuses new issuance (`not_found` — D7's
   "absent from every door", E9's one answer), and present in the audit
   trail.
3. Archive decrements nothing on the meter (bytes still held) —
   asserted against the ledger.
4. `files.file.archived` emitted (E3, v=1).
5. The object population's rule-31 declaration exists
   (purged-by-callable, `delete_tenant_objects`, honest interim
   retention line); `close_tenant`'s walk reaches it **by discovery** —
   a hand-list reference anywhere is the violation the declared-population
   ruling closed. If
   P5's registry has not landed, the callable + module-docstring truth
   per that ruling's shape, the declaration joining in P5's own rung (the
   ING-2 R-c posture, verbatim).
6. `delete_tenant_objects` prefix-deletes: after it, a head on any of
   the tenant's keys 404s and another tenant's objects are untouched
   (wire, MinIO).

**F5 · rule 32 + canaries + `storage_audit` + THE PROBE** — `apps/files`
+ `quality/rules.yaml`. Size M. Cites C8, E9, E10's spirit, G3; rules
24, 26; rule 32 born here; the socket-leak probe precedent.
1. Rule 32 lands **with firing canaries**: a planted `import boto3` in a
   domain app, a planted bucket-settings name outside the allow-list,
   and a planted `ACL="public-read"` in `storage.py` all fire through
   the real scope at self-test; negatives (`storage.py` itself,
   `config/settings/`, tests) stay silent; a dead canary is exit 2.
2. `manage.py storage_audit` (read-only) runs against MinIO in the
   suite: public-access-block on, no public ACLs; its P4 access-logging
   leg is a stated pending line with an owner, never silently absent.
3. **THE PROBE, born proven, kept as permanent regressions** (the
   socket-leak precedent — red demonstrated first, then the real wall refuses):
   (a) cross-tenant issuance — a tenant-B actor names tenant A's file
   id → `not_found`, both doors; the red half disables the scope check
   through a test double and shows the leak; (b) same-tenant
   sibling-branch likewise; (c) an expired presign refuses at the edge
   (wire); (d) **a leaked PENDING-upload URL cannot overwrite a stored
   object**: finalize the version, then replay the old PUT — refused
   (the service-side re-presign refusal, plus the `If-None-Match` belt
   where MinIO honors it); (e) **a version key is never re-presignable
   after `STORED`**: every presign path runs through the one seam
   function that checks status and prefix — a planted bypass fails the
   census-shaped test (R2-7's pattern, in-app).
4. Digest honesty end-to-end: the recorded sha256 equals an out-of-band
   recomputation over bytes downloaded through the presigned GET
   (E10's spirit — the basis checked through both presign directions).
5. Audit inventory (G3): after the suite's happy path, `AuditEntry`
   rows exist for `create_file` / `add_version` / `confirm_upload` /
   `issue_download_url` / `archive_file` with the driven `door` values;
   the refused probes left refusal-outcome rows and no URLs.

**Dependency edges restated for the lead:** F1 → F2 → F3 → F4 → F5, all
in `apps/files`, sequential (one app, one leaf). F2's meter call needs
the `record_usage` signature merged first (§I+, dependencies above) or
moves to a named later line; P5's export rung consumes F2's
`store_bytes` and F3's issuance door.

---

## ING-2 · full-text search — `apps/search` (Meilisearch v1 · pg FTS as the degradation engine)

> **Owner ruling, the preamble this design stands on: Meilisearch
> ships in v1.** The owner's argument, decisive: builders inheriting
> guaranteed instant, relevant search at zero development cost IS the
> Ingredients pillar ("a product building foundation-class capability
> privately is the pillar failing" — and mediocre platform search guarantees
> products bolt on better search privately, un-walled and un-reviewed). The
> original pg-only ruling (ADR search-1) stands as the DEGRADATION ENGINE,
> not the destination. The caller-facing contract is engine-blind; no
> frontend or client impact from the engine choice, ever. The ruling's four
> design commitments — one chokepoint + a fencing rule, org-id-list filtering
> never paths, a spine-riding indexer + erasure hooks, pg fallback behind an
> engine-agnostic contract — are the design below, done properly rather than
> by amendment prose.

**ADR search-2 (ING-2D design pair, owner-directed; supersedes
search-1's engine ruling — search-1's per-model pg shape survives intact as
the fallback engine) · context:** every product needs "find the thing", and
search is where scoping quietly dies — an external index that does not carry
the walls is a probing oracle, which is exactly why search-1 refused an
engine and why this design's center of gravity is the filter injection, not
the engine. **decision:** Meilisearch self-hosted in the compose stack (the
ClickStack/Zitadel/MinIO posture); **one shared index per searchable kind**
with `tenant_id` + `org_id` as filterable attributes and the scope filter
resolved in Postgres per request and injected by one chokepoint; a
**rule-33 fencing rule** (the rule-27 shape) walls the Meili client
into `apps/search/engine.py`; the **indexer rides the events spine**
(outbox, at-least-once, replay-safe, mirroring `push_realtime` to the
letter); **pg FTS + trigram stays behind the same engine-agnostic protocol**
as the designed degradation — Meili down means slower and plainer, never
dead. **rejected:** index-per-tenant (below, reasoned); Meili tenant tokens
/ browser-direct search (below); a central `SearchEntry` shadow table
(search-1's rejection stands — the *engine's* documents are not a shadow
authz copy because no authorization decision is ever made from them: the
filter is computed in Postgres every request and the fencing rule means no
other path exists); OpenSearch/Elasticsearch (ops weight + the same sync
work for relevance gains no product at this scale needs — search-1's
rejection, unchanged). **trigger to revisit:** the P6 harness measuring the
visible-org-id list as a real ceiling at seeded scale (the named risk of
list-not-path filtering), or a product needing semantic similarity (its own
ADR, adjacent ING-3 — not folded in here).

### The document model (A5, D7; rules 8, 24)

**Declared per app in a discovered `apps/<x>/search.py`** — the
`events.py`/`meters.py` pattern; registration never edits `config/` or
`apps/search`:

```python
SEARCHABLES = [
    Searchable(
        model=Widget,
        label="widgets",                     # the kind, and the index name's tail
        fields=[("name", "A"), ("notes", "B")],  # one declaration, both engines
        refresh_on=(
            "example.widget.created",        # names from the app's events.py,
            "example.widget.updated",        # never literals (rule 16)
            "example.widget.archived",
        ),
    ),
]
```

One declaration drives **both engines**: the field list is the Meili
document's searchable attributes (declaration order = attribute ranking) and
the same list feeds `search_vector(fields)`, the blessed `GeneratedField`
tsvector column + GIN index the adopting app owns (search-1's shape,
verbatim — the adopting app owns its column and its migration; the collision
discipline holds). `registry.py` validates at **import time** — a declared
field missing on the model, a bad weight, a `refresh_on` name absent from
the emitting app's `events.py`, a model that is neither `TenantScopedModel`
nor `OrgScopedModel`: each refuses at boot (E9's strongest tier).

**The document** is deliberately lean: `id` (the row's pk — UUIDv7 is a
legal Meili document id), `tenant_id`, `org_id` (org-scoped kinds only),
`label` (the display string a picker shows), and the declared text fields.
Nothing else — no snapshot of the row, no relations, no counts.
`filterableAttributes = [tenant_id, org_id]`, and **no materialized paths in
Meili, ever**: the path is Postgres's private vocabulary and copying it out
would make every re-parent a bulk rewrite of documents.

**Index topology: one shared index per kind
(`<prefix>_<kind>`), all tenants together, filtered — not index-per-tenant.**
Reasoned rejection of index-per-tenant: at 1,000 tenants × K kinds that is
thousands of indexes — per-index settings that drift (one settings surface
becomes N that must be reconciled), index creation as a provisioning step on
tenant signup that can fail and must be retried, cold-start and reindex
fan-out multiplied by tenant count, and Meili's per-index memory overhead
paid per tenant. Its one genuine advantage — tenant deletion as index drop —
is traded for `deleteByFilter(tenant_id = X)` inside
`delete_tenant_documents`, an at-least-once purge with its own criterion.
Isolation does **not** ride the topology in either design; it rides the
injected filter, which is why the filter is the thing born proven (R-e).
Also rejected: one single global index across kinds (per-kind searchable
attributes and ranking make shared settings untunable, and every query pays
a kind filter for nothing). The `<prefix>` derives from `DATABASE_NAME`
(the B2 derivation precedent), so two checkouts and every xdist worker
create disjoint index namespaces and parallel gates never meet in Meili any
more than they do in Postgres.

**What happens on an org MOVE: zero documents update, by construction.**
Re-parenting an `Organization` changes its ancestry (`path`), not the
`organization_id` on any row — and documents carry `org_id`, never
ancestry. The querying side absorbs the move instead: the visible-org-id
set is resolved from the actor's hat by an indexed path-prefix scan **in
Postgres, per request**, so the first query after the move filters against
the new subtree with no reindex, no sync loop, no window where stale
ancestry answers. The spine carries the move event and the indexer ignores
it (no `refresh_on` names it). The one case a document's `org_id` changes
is a **row-level** reassignment — a service write on the row itself, which
emits the row's own `refresh_on` event and converges through the ordinary
indexer path. Archived rows (`archived_at` set, D7): the refresh event
deletes the document — absent from every list door means absent from
search.

### The chokepoint, and the fencing rule (C6; rules 3, 8, 12, 17, 24)

**One read chokepoint:** `apps/search/selectors.py`

```python
def search(*, tenant, actor, q: str, kinds=None, page=1) -> SearchPage
```

engine-blind: query in, scoped page out. It sits in `selectors.py`, not
`services.py` — a search is a read, and C6/rule 12 place reads in selectors;
the ruling's intent ("a single search service always injects the filters")
is preserved exactly where it matters: **one function builds the scope, and
no other path to an engine exists.** The selector resolves
`ScopeFilter(tenant_id, visible_org_ids)` in **one Postgres query** (the
hat's subtree by indexed prefix scan — the same resolution `visible_to`
performs), then hands `q`, the kinds and the `ScopeFilter` to the engine.
The engine receives resolved ids only — it never sees the actor, the hat or
a path, so an engine cannot get scoping wrong, only receive it. Per-kind
filter shape: `tenant_id = <t> AND org_id IN [<ids>]` for org-scoped kinds;
`tenant_id = <t>` for tenant-scoped kinds (the registry knows each model's
base — the org-blind-push lesson applied: the injection is per-kind-aware, never a
one-shape-fits-all that goes org-blind on the scoped half). `q` travels
only as the engine's query parameter and is **never concatenated into the
filter expression** — the filter is built from resolved UUIDs and nothing
the client sent, which is what the R-e smuggling probe verifies.
Fails closed: `tenant=None` or an unresolved hat returns the empty page —
the `for_tenant(None)` posture, one level out. Counts are **exact and
scoped**: page-based pagination (`hitsPerPage`/`page`), which Meili answers
with exhaustive `totalHits` under the filter — the anti-oracle criterion
(nothing anywhere counts what sits outside your scope) holds because no
unfiltered query exists to count with.

The write-side chokepoints live in `apps/search/services.py` —
`index_event`, `delete_documents`, `delete_tenant_documents`, `reindex` —
the only callers of the engine's write half; the indexer activity and the
management command call services, never the engine (rule 10's shape).

**THE FENCING RULE — rule 33, "one door to the index" (the rule-27
shape; numbered per the PM landing-order assignment):** no module under `apps/` outside
`apps/search/engine.py` imports the Meili client (`meilisearch`) or names
`MEILI_URL` / `MEILI_MASTER_KEY` (`config/settings/` excepted, where the
environment is read). **Second clause, same rule:** nothing outside the
`rules.yaml` allow-list imports `apps.search.engine` at all —
`apps/search/selectors.py`, `apps/search/services.py`, the
`search_reindex` command, tests. Canaries, planted through the real scope
at self-test: an `import meilisearch` in a domain app; a `MEILI_MASTER_KEY`
reference outside the allow-list; an `from apps.search import engine` in
`apps/example` — all must fire or exit 2. Negatives: `engine.py` itself,
`config/settings/`, the allow-listed importers. `does_not_cover`
(declared, rule-34's honest half): a raw `httpx` call to the Meili URL —
the closed grammar's other side, review's and the census's; and **the Meili
server's own state** — the console/API is a window, not a door: index
settings are code (`engine.py` declares them; `search_reindex` re-applies
them idempotently), so a hand-edited setting is overwritten on the next
rebuild, and that overwrite is a criterion, not a hope.

Rejected here: **Meili tenant tokens** (signed filter JWTs) and with them
browser-direct search. Tenant tokens exist so a *browser* can query Meili
without a backend hop — which is precisely the door this platform refuses:
every door calls services, the chokepoint is the wall, and a client holding
any Meili-facing credential is a path around rule 33. Server-side, a token
buys nothing the injected filter does not already do. The engine
authenticates with the master key from env in `engine.py` only; a scoped
Meili API key is the recorded hardening when a second consumer of the Meili
container ever appears (trigger named — none exists).

### The indexer — riding the spine (C2, C4, E3, E4; rules 9, 10, 18)

The spine already fans one committed event out to every subscriber with
at-least-once delivery, retries, a relay for stranded rows and
`manage.py replay_events` for recovery. The indexer is **a third fan-out
leg beside `push_realtime`, mirroring it to the letter**: a new
`index_search` activity in `apps/events/activities.py`, called from
`DispatchEventWorkflow`'s fan-out, that looks up
`bridge.find("search.index_event")` — registered by `apps/search`'s
`AppConfig.ready()`, shape pinned by test — and returns `False` with a log
line when nobody registered it, so a template without `apps/search`
still delivers its webhooks (the `REALTIME_PUSH` posture, verbatim; the
name stays out of `core.bridge`'s constants — no ingredient touches
`apps/core` — and lives beside the activity that calls it).

**What the activity does:** the handler looks the event's name up in the
registry's `refresh_on` map (an event no searchable subscribed to is a
no-op, `False`); extracts the row pk from the payload (`id` on the `Out`
schema every payload is); **re-reads the row from Postgres through the
model's own `for_tenant` manager** — never trusting the payload's field
values — builds the lean document from current state, and upserts it
(row archived or gone → deletes the document). The activity completes only
after Meili **confirms the task** (`waitForTask`), so a Meili-side failure
is a raised activity and a Temporal retry, with the retry policy declared
at the call site.

**Idempotency and ordering fall out of the re-read** (C4): the upsert is
keyed on the document id, and because the document is always built from the
row's *current* state, a redelivered event, a `replay_events` sweep, or an
old event replayed after a newer write all converge on the same document —
at-least-once plus last-writer-agnostic equals exactly-current. There is no
version fencing to maintain and no ordering assumption to violate.

**The erasure hook, and the lifecycle declaration.** The Meili documents
are an off-ORM population, and the standing ruling is that populations are
**declared, never hand-listed** (the lifecycle-declarations rule, its
§2, now firmly **rule 31** per the PM landing-order assignment; the
storage wall renumbered to 32 in ADR files-2 — the collision this
parenthesis used to record is resolved).
`apps/search` declares its document store **purged-by-callable** through
that rule's registry (the "third-party models via registry" clause was
written for exactly this): `delete_tenant_documents(*, tenant)` is the
callable, reached by discovery from `close_tenant`'s walk. Person-level
erasure needs no search-specific hand edit either: `erase_user` anonymises
rows through services, those services emit, and the spine converges the
documents — the **erased-absence criterion** (the erasure probe, extended to
the index: after erasure and an outbox drain, no document in any index
contains the pre-erasure email or name) is what proves the chain rather
than a second walk.

**The rebuild, and the honest backup story.** `manage.py search_reindex
[--kind <label>]` walks the registry, batches rows through the same
document builder, builds into a fresh index and **swaps atomically**
(Meili's index swap), so mid-rebuild queries keep answering from the old
index. Backup of the Meili volume: **none, on purpose, documented** — the
source of record is Postgres, the index is a derived view, and the recovery
story *is* the rebuild; the restore drill gains a search leg that runs the
command and asserts document-count parity against Postgres. The command is
also the backstop for anything that out-lives the indexer activity's retry
budget.

**Index-lag honesty — what the contract PROMISES.** Search is **eventually
consistent, never read-your-writes**: a just-committed row appears after
its event dispatches and Meili's task settles — seconds in the healthy
case, bounded below by outbox dispatch latency. The contract states this
in `SearchPage`'s docstring and this ADR, and every convergence criterion
is phrased **drain-then-assert** (drain the outbox, await the task, then
compare), never sleep-and-hope. A product needing read-your-writes for a
picker uses its list endpoint — which is Postgres and instantly true — and
the picker-parity criterion is accordingly *parity after drain*, a
deliberate weakening of search-1's by-construction parity, priced and
stated. The degraded engine covers the gap's sharpest corner for free: a
just-created row searched through the pg engine is fresh by construction
(the consistency note the ruling asked for).

### The degradation engine — pg FTS + trigram behind the same contract

`engine.py` defines the protocol (the `comms/providers.py` precedent — a
`Protocol`, satisfied by shape):

```python
class SearchEngine(Protocol):
    def query(self, *, kinds, q, scope: ScopeFilter, page) -> EngineHits: ...
    def upsert(self, *, kind, document) -> None: ...
    def delete(self, *, kind, ids) -> None: ...          # + delete_by_tenant
```

`MeiliEngine` is the default. `PostgresEngine` is **search-1's design,
intact**: one scoped query per requested kind — each through the model's
own `.for_tenant(t).visible_to(actor)`-equivalent scope (rules 8/24 hold by
construction on this path; the engine receives the resolved ids and filters
on them) — over the declared tsvector `GeneratedField` (websearch parsing,
`ts_rank`), plus a trigram (`pg_trgm`) GIN index on the declared `label`
for modest fuzzy matching, rank-merged across kinds. Its `upsert`/`delete`
are no-ops: the generated column needs no sync, which is exactly why it can
never be stale and why it is the right thing to be standing on when the
sync'd engine is down.

**When it engages — the circuit shape.** The selector tries Meili under a
tight declared budget (connect + query, ~800 ms); a timeout or connection
error answers **that same request** from `PostgresEngine` and sets a
short-TTL cooldown key in the cache (Redis — already a platform
dependency), so subsequent requests skip the dead call until the TTL
expires and one request probes again. No background health-checker, no
third state: try, fail over, cool down, re-probe. **And the transitions
announce themselves**: closed→open emits `search.engine.degraded` and
open→closed emits `search.engine.recovered` — declared in
`apps/search/events.py` (rule 16), emitted on **state transitions only,
never per request**, so re-probe flapping cannot spam the spine. A
degradation that lands in the event stream is one ClickStack alerts on
(P4) and comms can route to a human with zero new plumbing — where the
sole prior signal was a failover log line a user's complaint would have
beaten to the operator (the owner's scar). The posture,
stated once: **a degradation the system survives is a state it
announces, never just tolerates.** During an outage the
indexer's activities fail and retry on Temporal's clock — the spine IS the
catch-up queue, so recovery needs no manual reindex for anything inside
the retry budget; `search_reindex` is the named backstop beyond it.

**What degrades, stated:** latency (one filtered engine query becomes N
per-kind Postgres queries, rank-merged), typo-tolerance (Meili's full
tolerance narrows to trigram similarity on `label` only), relevance
(field-weighted BM25-class ranking becomes `ts_rank`), and
prefix-as-you-type (gone). What does **not** degrade: the walls — both
engines receive the same `ScopeFilter`, and the R-e probes run against
both. **The response says which engine answered**: `SearchPage.engine`
(`"meili" | "postgres"`) — the honest surface the chaos drill asserts on
and a client may surface or ignore.

**The chaos drill is a criterion, not an ops aspiration** (R-d): stop the
Meili container mid-suite → the search door returns 200 with pg-ranked
hits and `engine="postgres"`, zero 5xx; start it → within one cooldown TTL
the engine field reads `"meili"` again. Because a fallback that engages is
a designed state, **Meili is deliberately NOT a `/readyz` dependency** —
failing readiness on a component whose absence the design survives would
convert the degradation into a self-inflicted outage; Meili health rides
the circuit state and observability instead (G1's sink sees the failover
log line).

### Doors (E1, E2, E6; rules 3, 16, 17)

REST `GET /api/v1/search/?q=&kinds=&page=` — `auth=` explicit, the page
contract (E6's envelope via `SearchPage`: `items`, exact scoped `count`,
`engine`). MCP `search.query`, full parity (rule 17), byte-equal fields.
Schemas: `SearchHitOut` (kind, id, label, rank), `SearchPage`.
**Deliberately door-less:** per-model search routes (one door serves every
registered kind); any write route (indexing is spine-fed and
service-only — a client that could write documents could mint search
results); admin. Audit: none per query (a search is a read; rejected as
volume without a consumer; trigger: a compliance demand) — the write side
(`delete_tenant_documents`, `reindex`) is `@service` and audited like any
write.

### Compose & ops

`getmeili/meilisearch` (pinned minor) joins `compose.yaml` beside
ClickStack/Zitadel/MinIO: one small container, a named volume
(`meili_data`), `/health` as the compose healthcheck. **Master key
posture:** `MEILI_MASTER_KEY` from env — `.env.example` carries the
published dev value (the standing dev-values posture), production injects
from Secrets Manager per the AWS standing default; the key is named in
`config/settings/` and `engine.py` only (rule 33's fence). `MEILI_ENV=
development` locally. **Memory expectations, stated so nobody is
surprised:** ~100–300 MB baseline; documents are lean (ids + label + text
fields), so index size tracks text volume, not row width — the P6 harness
records the measured footprint at seeded scale and that number, not this
prose, is the authority thereafter. Prod/staging: the container joins the
staging compose the same way ClickStack does (self-hosted, zero marginal
cost); nothing here waits on P4.

### What v1 deliberately excludes, each with its trigger

- **Semantic / pgvector similarity** — a different question (similarity,
  not text match), adjacent to ING-3; trigger: a product asks → its own
  ADR.
- **Per-tenant index tuning** (tenant synonyms, stop-words, ranking
  overrides) — trigger: the first tenant demand → `Tenant.settings` keys
  applied by the engine, schema-validated per the platform table.
- **Synonyms (global)** — trigger: a field-test relevance finding naming
  the missed vocabulary.
- ~~Facets / aggregations~~ — **moved IN by the owner's Meili-v1 ruling
  (queue.md): facets ship native via Meili.** The guard that
  kept them out survives as their contract: facet counts compute only
  under the injected `ScopeFilter` (the anti-oracle extends to facet
  counts), and the pg engine's degraded twin returns no facets —
  documented in the degradation set, not silently empty.
- **Highlighting / snippets** — trigger: the first picker that wants
  match context; Meili-native when it comes, with the pg engine's
  `ts_headline` as the degraded twin.
- **Search analytics / query logging** — trigger: a compliance or product
  demand; arrives as an audited, declared population, not a side log.

### STACK RULING ING-2 — superseded

Search-1's ruling ("Postgres FTS, per-model generated columns") was
ratified under delegation #3 and **superseded by
the owner's direct ruling above** (the inheritance argument). The
alternatives table survives in spirit: OpenSearch/Elasticsearch remain
rejected (ops surface + relevance gains nobody needs); pgvector remains a
separate future ADR. What changed is Meilisearch's column: its "same sync
+ scoping tax, lighter ops" price was re-judged worth paying because the
sync rides an existing spine (no new pipeline), the scoping never left
Postgres (no shadow authz — the exact A5a objection dissolved by the
filter-injection design), and the ops surface is one compose container.

### Dependencies & size

**No build edges in.** ING-1 → ING-2 stays a deferred, trigger-named edge
(extracted-text search over stored documents needs an extraction activity
+ adoption — recorded, not built). ING-5: none. P4: none — Meili is
compose-local. **Sequencing notes (soft, the lead sequences):** P3's
realtime fix rung also touches `apps/events` — it lands before P6 per the
T0 track, so no collision is expected, and if the windows overlap the
`apps/events` touches serialize; R-c's lifecycle declaration follows the
format P5's declarations rule lands — if R-c arrives first, it ships the
callable + docstring truth and the declaration joins the registry in P5's
own rung. Migrations: **none in `apps/search`** (still no models);
`apps/example/migrations/0010_widget_search_vector` in the adoption rung
(current leaf `0009_widget_policy_and_entry`); none in `apps/events`.

**Size: 5 rungs** (was 2 under search-1) — the decomposition below.

### The lead's decomposition — five rungs, draft criteria (P6 finalizes)

Rules cited per set; every criterion here is a draft shape the P6 lead
hardens with instruments and absent-case results (dispatch-briefs, stage
4). Sequential except where noted; one builder can carry R-a→R-d standing.

**R-a · engine + chokepoint + fencing rule** — `apps/search` (new app:
registry-less skeleton, `engine.py`, `selectors.py`, `schemas.py`,
`api.py`, `mcp.py`, tests) + `compose.yaml` + `quality/rules.yaml`.
Size M. Cites A1, A2, B1, C6, E1, E2, E6, E9; rules 3, 8, 12, 16, 17, 24;
rule-33 born here.
1. Rule 33 lands **with firing canaries**: a planted `import meilisearch`
   in a domain app and a planted `MEILI_MASTER_KEY` reference outside the
   allow-list both fire through the real scope at self-test; negatives
   (`engine.py`, `config/settings/`) stay silent; a dead canary is exit 2.
2. Second clause proven: a planted `from apps.search import engine` in
   `apps/example` fires; the allow-list (`selectors.py`, `services.py`,
   the command, tests) stays silent.
3. `selectors.search(*, tenant, actor, q, kinds, page)` exists and is the
   only engine caller on the read path; a recording fake engine shows the
   filter is exactly `tenant_id = <t> AND org_id IN [<resolved ids>]` for
   an org-scoped kind and `tenant_id = <t>` for a tenant-scoped kind.
4. Scope resolution is one Postgres query (indexed prefix scan), pinned
   with `assertNumQueries` at seeded scale.
5. Fails closed: `tenant=None` and an unresolved hat each return the
   empty page, byte-identical to a no-matches page.
6. Both doors mounted (`/api/v1/search/` with explicit `auth=`;
   `search.query` registered); byte-parity is R-e's wire proof.
7. Compose: the Meili container with healthcheck + volume + env key;
   index prefix derives from `DATABASE_NAME` — the derivation function is
   unit-proven to give two checkouts disjoint prefixes.
8. Honest interim (replaced by R-d): Meili unreachable raises the domain
   `Unavailable` through the one mapper — never a 500, never a silent
   empty page pretending to be an answer.

**R-b · declarations + the spine tap + the indexer** — `apps/events` (the
tap: one activity + one fan-out call, no models, no migration) then
`apps/search` (`registry.py`, `services.py` write half, bridge
registration). **Two apps, one rung, ADR-lined** (checklist line 1's
recorded exception): the events-side tap is unusable alone, mirrors
`push_realtime` verbatim, and adds zero migrations to either app — the
collision the one-app rule guards against cannot occur; the tap commits
first so the seam exists in-tree (§I+) before the search-side work.
Size L. Cites A2, C2, C4, E3, E4, §I+; rules 7, 9, 10, 16, 18.
1. Registry discovery + import-time refusal: a self-test plants a
   `Searchable` naming a missing field (and one naming an undeclared
   event) and expects the boot refusal, verbatim message pinned.
2. `index_search` mirrors `push_realtime`: `bridge.find`, absent →
   `False` + log line, dispatch outcome unaffected — a checkout without
   `apps/search` runs the events suite green.
3. The bridge shape is pinned by test on the registrant's side; the name
   registers from `AppConfig.ready()` and from nowhere else.
4. The activity re-reads the row through `for_tenant` by pk — a test
   feeds a stale payload and the document carries the row's current
   state, proving the payload is never trusted.
5. At-least-once convergence: the same event dispatched twice, and
   `replay_events` over an already-indexed event, leave exactly one
   document with current state; an older event replayed after a newer
   write converges (the re-read proof, both orders).
6. The activity completes only on Meili task confirmation: a Meili 5xx
   raises and Temporal retries per the declared policy (the retry policy
   is at the call site, cited).
7. An archived row's refresh event deletes the document; the deleted
   document is absent from a subsequent query.
8. An org re-parent mutates zero documents (asserted against a recording
   engine); a row-level org reassignment updates `org_id` through its own
   refresh event.

**R-c · erasure + lifecycle declaration + rebuild** — `apps/search`
(+ the discovered lifecycle declaration). Size M. Cites C4, D8's spirit,
G3; rules 13, 22 (none — no migrations), the lifecycle-declarations rule.
1. `manage.py search_reindex [--kind]` rebuilds into a fresh index and
   swaps atomically; a query issued mid-rebuild answers from the old
   index (wire-proven against the real container).
2. Settings are code: the command re-applies searchable/filterable
   attributes and ranking idempotently; a hand-edited index setting is
   overwritten by the next rebuild and the test drives that overwrite
   (console-is-a-window, rule-27 posture).
3. The document population is declared purged-by-callable through the
   P5 lifecycle registry (or, if P5 has not landed it, the callable +
   module-docstring truth per the declared-population ruling's shape (named
   below), with the declaration named
   as P5's wiring); `close_tenant`'s walk reaches
   `delete_tenant_documents` by discovery — a hand-list reference
   anywhere is the violation the declared-population ruling closed.
4. `delete_tenant_documents` deletes by filter; after it, a root-actor
   query returns zero hits for that tenant across every kind.
5. **Erased-absence**: after `erase_user` + outbox drain, no document in
   any index contains the pre-erasure email or name — the erasure probe,
   extended to the index; it fails against a build that skips the drain
   and passes once the drain lands.
6. Backup honesty: the recovery story (`search_reindex`, no volume
   backup) is stated in the module docstring; the restore drill's search
   leg runs the command and asserts document-count parity with Postgres.

**R-d · the degradation engine** — `apps/search` (`PostgresEngine`, the
circuit, `helpers.py`'s `search_vector`). Size M. Cites C6, E10's honesty
posture; rules 5, 8, 12, 24.
1. `PostgresEngine` satisfies the same protocol: per-kind scoped queries
   over the declared tsvector column + trigram on `label`, rank-merged,
   same `SearchPage`; its `upsert`/`delete` are documented no-ops.
2. The circuit: a Meili timeout/conn-error inside the declared budget
   answers **the same request** from pg with `engine="postgres"` and sets
   the cache cooldown; requests inside the TTL skip Meili (asserted by a
   call counter); TTL expiry re-probes.
3. **The chaos drill as a criterion**: stop the container → 200s with pg
   hits + degraded flag, zero 5xx; start it → within one TTL the engine
   field reads `"meili"` again. Both halves in one test, against the real
   compose service.
4. Degradation honesty: the documented degraded set (latency,
   typo-tolerance, ranking, prefix) is what the test asserts — a typo'd
   query found by Meili and missed by pg is the *expected* fixture, not a
   flake.
5. Just-created-row: a row committed and searched without draining the
   outbox is found through the pg engine — the consistency note proven.
6. Outage convergence: indexer activities failed during the drill retry
   and converge after recovery with no manual reindex (inside the retry
   budget); the budget and the `search_reindex` backstop beyond it are
   stated at the call site.
7. The drill asserts the announcements: `search.engine.degraded` fires
   when the container stops and `search.engine.recovered` fires within
   one cooldown TTL of restart — transitions only (a second failing
   request emits nothing); the event assertions ride the same drill
   test, no new rung.

**R-e · example adoption + wire proofs + the adversarial probe** —
`apps/example` (declaration + migration) + wire tests. Size M. Cites E1,
E2, E6, E9; rules 5, 16, 17, 22, 24; the socket-leak class.
1. `apps/example/search.py` declares the Widget searchable with
   `refresh_on` names from `events.py`; migration
   `0010_widget_search_vector` adds the generated column + GIN + trigram
   index, expand-only, leaf holds.
2. REST and MCP: the same query returns byte-equal `SearchPage` fields
   through both doors (rule 17).
3. Picker-parity **after drain**: create rows → drain the outbox → search
   finds exactly what the scoped list shows; per-kind counts equal the
   scoped list's counts (anti-oracle, exact `totalHits`).
4. **THE PROBE, born proven, kept as a permanent regression**: a
   branch-B actor queries terms matching only branch-A rows (same
   tenant) → zero hits, zero counts, on **both engines**; cross-tenant
   likewise; and the red is demonstrated first — the injection disabled
   through a test double leaks, then the real chokepoint refuses (the
   earlier probes' precedent: the probe that found the socket leak became
   the regression).
5. Filter smuggling: a documented corpus of hostile `q` values (Meili
   filter syntax, quotes, backslashes, `OR tenant_id != …`) each returns
   zero cross-scope hits on both engines — `q` provably never reaches
   the filter expression.
6. A hatless/revoked actor gets the empty page, byte-identical to
   no-matches (E9 — not-there ≡ not-yours).
7. Query budget: the search route's Postgres query count pinned at
   seeded scale on the Meili path (scope resolution + auth only).

**Dependency edges, restated for the P6 lead:** none on ING-1 (deferred
trigger stands) · none on ING-5 · none on P4 (compose-local) · soft
sequencing vs P3 (`apps/events` touches; P3 lands first per the track)
and P5 (declaration format; R-c ships the callable either way). R-a →
R-b → R-c and R-b → R-d (the indexer must exist for the drill's
convergence half); R-e last (proves all of it). R-c and R-d are
order-independent of each other but share `apps/search`, so they run
sequential under the one standing builder — parallel rungs never share
an app.

---

## ING-3 · LLM primitives — `apps/completions`

**ADR completions-1 · context:** products will call models
(a first consuming product: `draft_reintro` — draft a re-introduction for a dormant contact);
un-platformed, every product grows its own key handling, retry logic,
unaudited prompts and unmetered spend. **decision:** a new platform app
`apps/completions`. Aggregate: `Completion` — one model call as a row
(status `QUEUED → RUNNING → SUCCEEDED | FAILED`, D4), org-scoped, carrying
the rendered prompt, the output, the model id, and the usage figures.
**Every provider call is a Temporal activity** (rule 9 — the constraint is
constitutional, not optional): the `run_completion` service writes the row
and starts `RunCompletion` on commit (C2); no service or door ever holds a
provider socket open inside a transaction. Prompts are **versioned config**
per D9/D10: `Prompt(TenantScopedModel)` — immutable `key`, `version`,
body, variables schema — `create/revise/retire`, mirroring
`comms.MessageTemplate` (the named precedent); a `Completion` records
`prompt_key` + `prompt_version` denormalized (the durable answer to "what
was this drafted under", D10). **rejected:** synchronous provider calls in
services (C2 — a provider hiccup rolls back a legitimate row; rule 9 the
other side); LiteLLM/LangChain as the abstraction (a large dependency whose
retry/fallback logic fights Temporal's — retries are the workflow's job;
the registry protocol is ~50 lines of ours, comms `providers.py` is the
worked shape); prompts as code constants (unversioned config a tenant
cannot see or audit — D9's exact target). **trigger to revisit:** streaming
token-by-token to sockets → a `realtime` bridge from the activity, designed
then (the row-based contract survives underneath).

### App/module map

| app | noun (aggregate) | depends_on | doors | workflows | events |
|---|---|---|---|---|---|
| `completions` | `Completion` (+ `Prompt` config) | `core, accounts, usage` (+ bridge) | REST `/api/v1/completions/` · MCP `completions.*` | `RunCompletion` | `completions.completion.succeeded`, `completions.completion.failed` |

Canonical files, plus `providers/` (package): `providers/__init__.py`
(registry — `ModelProvider` protocol: `complete(*, model, messages, params)
-> ProviderResult(text, input_tokens, output_tokens, provider_request_id)`,
`register_model_provider(slug, provider)`), `providers/anthropic.py` (**the
one module that imports the provider SDK and names the key setting**).
Services: `run_completion(*, tenant, actor, prompt_key, context, model=None,
idempotency_key)` (C4 — MCP-reachable, idempotent), `record_result` /
`record_failure` (called from the activity; write output/usage, emit),
`create_prompt` / `revise_prompt` / `retire_prompt` (D9). Selectors:
`get_completion`, `list_completions_for_tenant`, `get_prompt` (resolves
latest active version).

### Doors

- REST: `POST /api/v1/completions/` → 202 + `CompletionOut` (id, status);
  `GET /{id}`; `GET /` (paginated, E6). Prompt CRUD:
  `POST/GET /api/v1/completions/prompts/` (+ revise/retire actions).
- MCP: `completions.run` (may await the workflow result up to a declared
  timeout before falling back to the id — the door waits, the activity does
  the I/O; the agent's ergonomic path), `completions.get`,
  `completions.list`, `completions.prompts.*` — full parity (rule 17).
- **Deliberately door-less:** provider/model administration (which
  providers exist is deployment config + registry code, not tenant data);
  raw "send this string to the model" without a prompt row — every call
  names a `prompt_key` (auditable vocabulary; an ad-hoc one-off is a
  product writing a prompt row first, which is the point).
- Composition note for the consumer: `draft_reintro` is a **product**
  service — gather context via selectors → `run_completion(prompt_key=
  "reintro", ...)` → file the output as the product's `PreparedDraft`. The
  output is a draft a human sends; ING-3 never transmits anything —
  the consuming product's own "the send is never a tool" rule and
  rule 25's wall are untouched by construction (the LLM app has no path to `comms.send`).

**v1 surface (owner rulings): tool-use is OUT.** A
`Completion` is one rendered prompt in, one output out — the model never
calls tools mid-run. The composition note above is the v1 answer: the
product gathers context through selectors, the model writes. Trigger: the
first product whose draft needs mid-call retrieval that selectors cannot
pre-gather → its own ADR, because a tool surface handed to a model is a
door, and doors call services — that design is not smuggled in as a
provider parameter. **Streaming's trigger stands unchanged** (the ADR's
trigger-to-revisit above): token-by-token to sockets arrives via a
`realtime` bridge from the activity, the row-based contract intact
underneath.

### Walls

`Completion(OrgScopedModel)` (A5 default; a draft belongs to the branch
that asked), read `.for_tenant(t).visible_to(actor)` (rule 24);
`Prompt(TenantScopedModel)` (config the whole tenant shares, A5's
one-sentence test). Authz: `completion.run`, `completion.read`,
`prompt.manage` in `policies.py` (C7). `may_be_named` on any org-scoped
FK-target params (C8, rule 26). **Prompt/output content never enters logs
or audit-entry input** — `LOG_KEYS` excludes them; the `AuditEntry` for
`run_completion` records the prompt key/version and the row id, not the
text (G2's redaction doing its job). Keys: `ANTHROPIC_API_KEY` via the AWS
secrets posture (Secrets Manager → env; read in `config/settings/` only).

### Events / workflow split

Events (E3, declared in `events.py`, v=1, payload `CompletionOut` minus
output body — subscribers fetch content through the door):
`completions.completion.succeeded`, `completions.completion.failed`.
*Rejected:* a `requested` event (no subscriber; the row exists).

`RunCompletion`: id `workflow_id(tenant, "completions", "completion",
key=<pk>)` (rule 18 — a retried `run_completion` with the same idempotency
key finds the same run, never starts a second). Activities: `call_model`
(the I/O; retry policy at the call site — backoff on 429/5xx,
non-retryable on 4xx-permanent; timeout declared), then `record_result`
(calls the service: writes output + status, **meters usage in the same
transaction** — see the seam), or `record_failure`. Closes its run (rule
28). Workflow code deterministic (rule 9) — model choice, prompt version,
params all resolved before start and carried in `types.py` dataclasses
(D11's snapshot shape: a prompt revised mid-run never changes a running
completion).

**The metering seam (ING-3 → ING-5):** `record_result` calls
`apps.usage.services.record_usage` twice —
`meter="completions.tokens.input"` / `"completions.tokens.output"`,
`quantity` Decimal, `ref` the completion id, `idempotency_key` derived from
completion id + meter (so an activity retry never double-meters, C4) — in
the same atomic block as the result write. The seam is the service
signature in `apps/usage/services.py`, in-tree before ING-3 dispatches
(§I+).

### Rules & canaries born with it

- **Rule 34 — one door to the model** (renumbered from 32 per the PM
  landing-order assignment; mirror of 25/27/32): no module under
  `apps/` outside `apps/completions/providers/` imports the provider SDK
  (`anthropic`) or names the key setting (`config/settings/` excepted).
  Canaries: planted import in a domain app; planted settings name.
  `does_not_cover` (declared): a raw `httpx` call to a provider URL — the
  grammar's closed half; review's and the census's.
- **Census test (R2-7 precedent, in-app):** every path from the registry to
  a provider's `complete()` runs through the one `_invoke` that records
  usage and writes the row — a planted bypass fails it. Promotion to a
  house rule recorded as a queue candidate; trigger: the second provider
  adapter.
- Criteria-tier: a failed `run_completion` leaves no `Outbox` row and no
  `WorkflowRun` (C2); same idempotency key twice → one row, one run (C4);
  token figures on the row equal the usage ledger's entries for the ref
  (the E10-shaped recomputation).

### STACK RULING ING-3 (owner ratifies)

**Recommended default: Anthropic API, direct, as the shipped provider slug
(`anthropic`); the abstraction is the in-house registry protocol above**
(the owner's standing context is Anthropic; the template's own agent team
runs on Claude).
- **AWS Bedrock (Claude via Bedrock)** — the serious alternative, and the
  posture-consistent one: keys become IAM (no new secret vendor), and a
  PHI-bearing product gets the model under the AWS BAA umbrella. Price:
  model availability lags the direct API, per-region routing, a second SDK.
  **Recorded as the named PHI escalation**: a PHI product swaps the slug —
  `providers/bedrock.py`, same protocol — and records it in its own
  `architecture.md`. (Anthropic offers BAAs directly too; whichever paper
  exists at that trigger wins.)
- **OpenAI default** — price: against the standing context, no offsetting
  advantage for the template's purposes.
- **LiteLLM as the abstraction** — price: a large dependency, its own
  retry/fallback machinery colliding with Temporal's (two retry brains),
  and a supply-chain surface rule 23 must then carry; buys multi-provider
  breadth the registry gives us per-adapter as needed. Rejected.

### Dependencies & size

**ING-5 before ING-3's result rung** (the seam above). No other edges in.
Migrations: `apps/completions/migrations/0001_initial` (leaf).

**Size: 4 rungs** — L1 models (`Completion`, `Prompt` D9 trio) + schemas;
L2 provider registry + `anthropic` adapter + rule 34; L3 services +
`RunCompletion` + metering seam + events; L4 doors (REST + MCP parity) +
census + criteria. All in `apps/completions`, sequential.

---

## ING-4 · comms tracking + channels — `apps/comms` grows

**ADR comms-9 · context:** the C1-1c residue — opened/clicked
tracking and real SMS/push vendors were deferred *with the tracking rung,
named* (queue C1-1); the status contract and the consent wall now stand
(P2's R2, ADR comms-8: bounce-driven auto-suppression in-transaction,
wall re-run at the transport edge). **decision:** grow `apps/comms` —
no new app (the aggregate is still `Message`; A1 holds). Two halves.
**(a) Engagement:** `MessageEngagement(OrgScopedModel)` —
**`append_only = True`** (rule 20 population, by declaration, no yaml
edit — the ADR core-6 dividend): FK `Message` (`CASCADE` — owned child of
the aggregate, D2), `kind` (`TextChoices`: `OPENED`, `CLICKED`), `url`
(clicked only), `occurred_at`, `provider_event_id`, unique on
`(message, provider_event_id, kind)` (idempotent webhook redelivery, C4);
`derive_org_from = "message"` (C9 — the engagement lands where its message
lives, never where a webhook handler's hat points). Recorded by
`record_engagement` (service, `system` actor — comms-8's A5b shape), fed by
the **existing signed provider webhook receiver** through
`normalize_status`'s sibling `normalize_engagement` on the provider
protocol. **An engagement never mutates `Message.status`** — an "open" is a
provider-attested inference (Apple MPP fires false opens), witnessed
history in one population, delivery truth in another; folding them would
launder an inference into a fact. **(b) Channels:** the `SMS` and `PUSH`
kinds in the existing `Channel` enum get one reference transport each,
riding `ConnectionChannel` (provider = a `connections` row, comms-6's
kind-vs-vendor split intact). Push needs `Device(OrgScopedModel)`: FK
`Recipient` (`CASCADE`), `token`, `platform` (`TextChoices`), `last_seen_at`,
`invalidated_at`; `derive_org_from = "recipient"` (C9). *Rejected:* push
tokens in `Recipient`'s address fields (tokens are plural per person,
rotate, and expire — an address is one and stable); a first-party tracking
pixel/redirect endpoint (BYO-frontend; the ESP does it; trigger: a product
that must not use ESP tracking domains); deriving `DELIVERED` from an open
(the laundering above); OneSignal (its own consent model competes with the
wall — two walls is no wall). **trigger to revisit:** a provider contract
distinguishing per-link click metadata worth modeling → `url` grows
structure then.

### The honest wall, extended (comms-8 riding)

- SMS: an inbound **STOP** maps to `complained` in `record_delivery_status`
  → the **existing** in-transaction auto-suppression fires (comms-8
  mechanism, zero new code paths); Twilio's `undelivered` maps into the
  collapsed bounce set. The wall's edge recheck in `deliver_message`
  already guards the new transports — the R2-7 census test extends to the
  SMS/push chokepoints and a planted bypass still fails it.
- Push: provider token-invalid feedback sets `Device.invalidated_at`
  (service write); a recipient whose devices are all invalidated refuses at
  send time exactly as an empty address does — fail-closed, no new status
  vocabulary (R2-5's dialect discipline).
- Engagement recording is **witnessing, not consent**: it never suppresses,
  never sends, and is recorded even for a recipient since suppressed — a
  fact about the past is not permission for the future.

**`send_at` — IN (owner ruling), riding what already
stands.** `comms.send(*, ..., send_at=None)` accepts a future instant:
the message row is written and audited at call time, and the delivery
workflow — which already owns everything that waits — sleeps on a
**Temporal timer** to `send_at` before entering `deliver_message` (rule
9: the wait is Temporal's, never a cron or a poll; the deterministic id
already covers the retried-schedule case, rule 18). What makes scheduling
safe is **R2's edge wall, not the scheduler**: the delivery-time recheck
(comms-8 — consent, suppression, quiet hours re-judged at the transport
edge) runs when the message actually goes, so a recipient suppressed
between queue and fire is refused *then*, and a `send_at` months out is
never a consent time-capsule. No new vocabulary, no new door — `send_at`
is a parameter on the one legal sender (rule 25) — and the
temporal-lever refinement (quiet-hours → reschedule, not kill) stays its
own recorded trigger, sharpened by scheduling traffic when it comes. A
provider outage is already announced by the machinery this app owns
(status webhooks, bounce handling, the DLQ); any *designed* fallback
transport added later announces its state transitions as declared events
per the search-2 posture (`search.engine.degraded`'s precedent) — a
degradation the system survives is a state it announces, never just
tolerates. **Digest composition stays product-layer** — OUT per the same
ruling: bundling N events into one message is product taste (what to
bundle, when to flush); the platform halves already exist (`send()` +
`send_at` + the wall). Trigger: the second product hand-rolling the same
bundling loop → a platform digest primitive then.

### Doors

- Inbound: **no new door** — engagement and SMS/push status arrive through
  the existing signed receiver (`connections`/`events`, verify → store →
  workflow).
- REST/MCP: `Message` detail/`comms` selectors grow engagement
  (`MessageEngagementOut` list on the message; parity per rule 17). Device
  registration: `POST /api/v1/devices/` + `comms.devices.register`
  (a product's mobile client registers its token) + deregister.
- **Deliberately door-less:** engagement writes (webhook-fed service only —
  a REST write would let a client mint "opened" facts); suppression state
  (already ruled — the existing pair is the door).

### Events / workflow split

Events, declared in `apps/comms/events.py` (E3, v=1):
`comms.message.opened`, `comms.message.clicked` (payload:
`MessageEngagementOut`). No new workflows — delivery already rides the
existing workflows; tracking is webhook → service.

### Walls

All new models org-scoped with `derive_org_from` (C9); reads through
`.for_tenant(t).visible_to(actor)` (rule 24). Authz: `device.register`
predicates in `policies.py`; `record_engagement` under `system` actor,
audited (`AuditEntry` `actor_kind=system`, `door=webhook`). Rule 25's
module allow-list grows the SMS/push SDK modules (`twilio`,
`firebase_admin`) pinned to `apps/comms/providers*` — the sender wall now
covers three transports, same rule id, canaries re-planted per transport.

### Rules & canaries born with it

- Rule 20 covers `MessageEngagement` **by declaration** (canary: the
  self-test plants an update to a member row and expects the fire — the
  population-driven rule already does this; the new member joins the
  planting set).
- Rule 25's grown allow-list, with a planted `import twilio` in a domain
  app as the new canary.
- R2-7 census extended: the transport chokepoint set now enumerates email +
  SMS + push, each containing the wall recheck reference; promotion trigger
  (a second app growing a transport) unchanged.
- Criteria-tier: STOP → suppressed → next `send()` refused `SUPPRESSED`
  (the comms-8 chain, re-proven over SMS); redelivered engagement webhook →
  one row (C4); an engagement row for a suppressed recipient exists and
  suppresses nothing.

### STACK RULING ING-4 (owner ratifies)

**Recommended defaults: SMS = Twilio · push = FCM (Firebase Cloud
Messaging, both platforms via one API).**
- Twilio: the status webhook vocabulary (`delivered`/`undelivered`/
  `failed`, inbound STOP) maps 1:1 onto the collapsed status set and the
  comms-8 suppression mechanism — the honest wall works day one. Price:
  per-message cost above bulk alternatives; 10DLC registration friction
  (identical everywhere).
- **AWS End User Messaging** (the Pinpoint successor) — posture-consistent
  (IAM, no new vendor). Price: a thinner status/feedback contract than
  Twilio's, clunkier STOP handling — the honest wall costs more to build
  on it. Named alternative for an all-AWS product.
- **Telnyx** — cheaper per message, smaller ecosystem. Price: fewer
  worked examples; fine as a product swap (the provider is a
  `connections` row — swapping is config + one adapter, comms' design
  promise).
- FCM: free, both mobile platforms, token-invalidation feedback (the
  `Device.invalidated_at` signal). Price: a Google project per product;
  data-residency posture is Google's.
- **OneSignal** — rejected (competing consent model, above).
- **Expo Push** — the right swap **iff** the product's client is Expo;
  recorded as a product-level adapter, not the template default.

### Dependencies & size

No edges to other ingredients. Rungs serialize inside `apps/comms` (one
app, one leaf — the standing-builder pattern from P2). Migrations:
current leaf `0004_policies_as_data` → T1 lands
`0005_message_engagement`, T3 lands `0006_device` (expected final leaf
`0006_device`).

**Size: 3 rungs** — T1 engagement (model, `record_engagement`, events,
receiver mapping, criteria); T2 SMS (Twilio adapter, STOP/undelivered
mapping, rule 25 growth, census extension); T3 push (FCM adapter, `Device`
+ doors, invalidation, fail-closed empty-device send).

---

## ING-5 · usage metering — `apps/usage`

**ADR usage-1 · context:** the platform is about to spend
money on behalf of tenants (ING-3 tokens; later SMS, storage), and a
number that surfaces on an invoice or a dashboard months later must be a
ledger, not a counter someone can bump. **decision:** a new platform app
`apps/usage`, **metering only** — invoicing stays product-layer until a
product asks (the scope ruling, recorded here). Aggregate:
`UsageEntry(OrgScopedModel)` with **`append_only = True`** (rule 20
population, by declaration): `meter` (charfield, grammar
`<app>.<noun>.<unit>` — e.g. `completions.tokens.input`), `quantity`
`Decimal(19,4)` (rule 15 — never Float, even for counts), `occurred_at`,
`ref` (source model label + id), `idempotency_key` (unique per tenant —
C4: a retried activity never double-meters), and the D8 correction pair:
`supersedes` FK (self, `PROTECT`) + `superseded_because` — a wrong entry
is answered, never edited. Meter names are **declared vocabulary**:
`apps/<x>/meters.py` (discovered, the `events.py` pattern — a literal at a
call site is a violation the same way an event literal is), validated
against the grammar at import time. The write door is one service:
`record_usage(*, tenant, actor, meter, quantity, ref, idempotency_key,
occurred_at=None)` — callable from activities under the run's actor;
`# authz: recording is the platform's witnessed side-effect of an
already-authorized action; the actor is carried for audit, not asked for
permission` (rule 13's escape hatch, used with its reason). The read is
`get_usage(*, tenant, actor, period, meters=None)` returning per-meter
**`MeasuredOut`** (E10): `value` = the period total, `basis.formula` =
`"sum(day_totals)"`, `basis.inputs` = ISO-date → Decimal day subtotals —
**re-addable by a reader**, the honest basis, checked by criterion.
**rejected:** stored per-tenant counter rows (see stack ruling); per-entry
events (an outbox row per LLM call doubles the write volume of the
hottest path for zero subscribers; the ledger IS the record; trigger:
a quota/threshold feature → threshold events then — **the trigger has since fired**,
see § events below: the crossing gets an event, the entry still never
does); a `Meter` model
(meters are code-declared vocabulary like events, not tenant data).
**trigger to revisit:** a product asks for invoicing → a product-layer
app reading this ledger (the ledger's shape — Decimal, ref, supersedes —
is designed so that day needs no migration here).

**TRIGGER — buffered ingestion (ratified alongside this ADR's criteria
amendments): the first per-REQUEST meter.** Every meter this ADR names
is **per-activity** — a completion that ran, an upload that finalised — so one
`record_usage` per unit of durable work, at the rate a worker does work. The
day a meter is recorded **per request** (an API call counted, a page served, a
tool invocation billed), the arithmetic changes shape: U1 measured one recording
at **13 statements** on a tenant with no thresholds configured
(`apps/usage/tests/test_services.py::RECORD_QUERY_BUDGET`, and nine of the
thirteen are `full_clean` plus the transaction and audit machinery every
`@service` pays), which is unremarkable per activity and is a second write
transaction on every request in the product. That is when buffered ingestion
gets its own ADR — a batched or queued write path in front of this ledger, with
the durability question answered out loud, because a buffer that loses rows is a
bill that is wrong in the customer's favour and a buffer that blocks is an
outage. **Nothing is built for it now**, deliberately: the shape of the buffer
depends on which per-request meter arrives first and what it may lose.

### App/module map

| app | noun (aggregate) | depends_on | doors | workflows | events |
|---|---|---|---|---|---|
| `usage` | `UsageEntry` | `core, accounts` | REST `/api/v1/usage/` (read-only) · MCP `usage.report` | none (rollup deferred, trigger named) | `usage.threshold.crossed` (ruled; § below) |

Canonical files; `selectors.py` carries the day-bucketed aggregation
(indexed on `(tenant, meter, occurred_at)` — the covering index is the
"counter" until measurement says otherwise).

### Doors

- REST: `GET /api/v1/usage/?period=&meters=` — paginated per meter (E6),
  `auth=` explicit, each meter's total a `MeasuredOut`.
- MCP: `usage.report`, parity (rule 17), byte-equal payload.
- **Deliberately door-less:** **writes.** No REST/MCP route records usage —
  a write door would let a client mint or dispute usage; `record_usage` is
  service-only, reached from activities and services. (No rule 17 issue:
  parity binds REST capabilities to MCP, and no write route exists on
  either.) Also door-less: cross-tenant/platform rollups (a platform
  operator read is a later `for_platform()`-shaped decision, not this
  ADR's).

### Walls

`UsageEntry(OrgScopedModel)` (A5 default — usage attributable to a branch
stays visible to that branch; the tenant total is the root's
`visible_to(root)` for free). Reads `.for_tenant(t).visible_to(actor)`
(rule 24) — **a branch admin's usage report never tallies a sibling's
tokens** (the anti-oracle, one level down). Authz: `usage.read` predicate;
recording per the `# authz:` reason above. Audit: `record_usage` is
`@service` — every entry has its `AuditEntry`; the ledger row and the audit
row answer different questions (what was consumed vs who caused the write)
and both exist.

### Events / workflow split

**One event — `usage.threshold.crossed` (v=1) — IN by owner ruling
(the trigger named in the rejection above has fired).**
Declared in `apps/usage/events.py` (E3, rule 16). Thresholds are tenant
config: `Tenant.settings` keys (schema-validated per the platform
table), lines of `(meter, period, quantity)`. The crossing check rides
`record_usage`: when the period total before and after an entry
straddles a configured line, the event emits inside the same transaction
(E3), deduped to **one crossing per (tenant, meter, period, threshold)**
by an idempotency-shaped uniqueness — a retried activity or a
superseding correction never double-fires. **Metering observes and never
refuses** — the ruling's word is quota-COUNTING: no write path anywhere
consults the ledger to block an action; a product wanting a hard quota
builds the refusal in its own services on this event and this read, its
own ADR. Per-entry events stay rejected — the crossing is rare, the
entry is not. The meter vocabulary also grows one member the same day:
**`files.storage.bytes`** (declared in `apps/files/meters.py` — ING-1 /
ADR files-2): recorded at finalize with the verified byte size, negative
entries on purge, never a decrement on archive; the storage quota story
is this ledger plus this event, and no counter anywhere.

No workflows, still deliberate (the rollup workflow — a Temporal
schedule writing append-only rollup rows derived from the ledger — is
**deferred with its trigger**: a perf harness measuring the
day-bucketed SUM as too slow at seeded scale).

### Rules & canaries born with it

- Rule 20 covers `UsageEntry` by declaration (the population's canary
  planting picks it up — an update planted on a member fires; no yaml
  edit).
- Meter-name grammar refused at **import time** (registry validation —
  E9's tier; self-test plants a bad name and expects the boot refusal).
- Criteria-tier: same idempotency key twice → one entry (C4); a
  superseding entry leaves both rows readable and the report reflects the
  correction; `MeasuredOut.value` equals the recomputation from
  `basis.inputs` (E10 — the checked basis); REST and MCP byte-equal.

### STACK RULING ING-5 — counter storage shape (owner ratifies)

**Recommended default: the ledger is the only store — an indexed
day-bucketed SUM is the read, wrapped in `MeasuredOut`; materialized
rollups arrive later as append-only derived rows via a Temporal schedule,
at a measured trigger (P3 harness).**
- **In-transaction counter rows** (`UsageCounter(tenant, meter, period)`
  F()-incremented) — price: a hot row serializing every LLM call in the
  tenant (the write path's contention point), and a second truth that can
  drift from the ledger; when they disagree, which is right? Rejected.
- **Redis counters** — price: fast and lossy; a restart or failover under-
  counts money. A cache that lies about billing-adjacent numbers is worse
  than a slow truth. Rejected as a store (fine later as a read cache in
  front of rollups, if ever needed).
- **ClickHouse (the ClickStack sink)** — price: observability metrics are
  sampled, retention-bound telemetry — a sink, not a source of record;
  billing-grade metering from the o11y pipe conflates two contracts
  (G1's one-sink is about telemetry, not money). Rejected, explicitly,
  since the owner holds ClickHouse Cloud: the ledger stays in Postgres;
  ClickStack keeps observing it like everything else.
- Recommended default's own price, stated: the read is O(period rows)
  until rollups land; the trigger is named and the index is designed for
  the interim.

### Dependencies & size

**ING-5 → ING-3:** `record_usage`'s signature is the seam ING-3 consumes;
this app lands (or at minimum its `services.py` signature merges) before
ING-3's L3 rung dispatches (§I+ — a seam is code, not prose). Migrations:
`apps/usage/migrations/0001_initial` (leaf).

**Size: 2 rungs** — U1 model + `record_usage` + meters discovery + rule-20
membership; U2 selector + `MeasuredOut` read + both doors + criteria.

---

## The dependency map, and the build order

```
ING-5 (usage) ──seam──▶ ING-3 (completions)        [record_usage, §I+]
ING-5 ──seam──▶ ING-1-F2                            [record_usage; a
                    signature-only merge suffices before wave 1's F2 —
                    §I+, ADR files-2 § dependencies]
ING-1 (files) ──provisioning──▶ P4                  [bucket, IAM, secret ARNs]
ING-1 ──deferred, trigger named──▶ ING-2            [extracted-text search]
ING-2 (search)      independent of the other ingredients; touches
                    apps/search + a no-migration spine tap in apps/events
                    (R-b, ADR-lined) + apps/example (adoption, R-e);
                    soft sequencing vs P3 (events) and P5 (lifecycle
                    declaration format) — the lead sequences
ING-4 (comms grows) independent (serializes inside apps/comms)
```

Suggested waves (one agent per app, per the collision discipline):
**wave 1** — ING-1 alone (its own cycle, per the ratification; the
`record_usage` signature-only merge precedes F2 — the seam note above);
**wave 2** — ING-5 ∥ ING-2 R-a..R-d ∥ ING-4-T1 (three lanes: `usage`,
`search` under one standing builder — R-b's events tap serialized after
any P3 events work — and `comms`); **wave 3** — ING-3 (seam now in-tree)
∥ ING-2 R-e (`example` adoption + probes) ∥ ING-4-T2/T3 (still `comms`,
same standing builder). ING-2's growth to 5 rungs spans waves 2–3.

**Total size: 19 rungs** (ING-1: 5 · ING-2: 5 · ING-3: 4 · ING-4: 3 ·
ING-5: 2) ≈ one full cycle plus two paired cycles — the ING-2 re-ruling
added three rungs to the original 16; still inside the queue's P6–P7
slotting with the lead's sequencing note above.

## New enforcement, summarized (born with the ingredients)

Numbering per the PM landing-order assignment: **31 = lifecycle
declarations (P5's) · 32 = the storage wall · 33 = the search fence ·
34 = the model door.**

| rule | ingredient | shape | tier |
|---|---|---|---|
| 31 lifecycle declarations (P5's rule, referenced) | ING-1, ING-2 | off-ORM populations declared purged-by-callable via the discovered registry (`delete_tenant_objects`, `delete_tenant_documents`) — no hand-list in any erasure/close walk | gate (lands with P5) |
| 32 bytes-through-the-store | ING-1 | import/settings wall around `apps/files/storage.py`; no-public-ACL clause; `storage_audit` tripwire for the console blind spot | gate |
| 33 one-door-to-the-index | ING-2 | import/settings wall around `apps/search/engine.py` + engine-importer allow-list; settings-as-code overwrite for the Meili console blind spot | gate |
| 34 one-door-to-the-model | ING-3 | import/settings wall around `apps/completions/providers/` | gate |
| 25 (grows) | ING-4 | SMS/push SDK modules join the sender wall's list; canaries re-planted | gate |
| 20 (grows by declaration) | ING-4, ING-5 | `MessageEngagement`, `UsageEntry` join the append-only population — zero yaml edits | gate |
| census tests (R2-7 pattern) | ING-1, ING-3, ING-4 | presign chokepoint (status+prefix check); metered-invoke chokepoint; transport chokepoints ×3 | in-app, promotion triggers named |
| import-time refusals | ING-2, ING-5 | searchable declarations (field/weight/event names); meter grammar | boot (E9 tier) |
| criteria-only, declared | all | anti-oracle counts, checked `MeasuredOut` bases, byte-equal door pairs, C2/C4 behaviors; ING-1's presign/version probes and ING-2's chaos drill (incl. the degraded/recovered announcements) + filter-injection probes as permanent regressions | criteria |
