# Platform decisions the lead applies

`django-architect` § H, in full.

## H · Platform decisions the lead applies

From "The platform the template ships" in `architecture.md`. When a rung
touches the area, the rule is applied and cited; none is re-argued.

- **Email** — sent from a workflow activity (retries), never from a service or
  a route; Mailpit in compose for dev; a provider via `connections` in
  production.
- **Invitations & tenant lifecycle** — `core.services.invite_member(email,
  tenant, role)`; `create_tenant / suspend_tenant / close_tenant` are
  services; allauth signup joins the membership.
- **Rate limiting** — ninja throttling per token and per tenant, defaults in
  settings; MCP tools share the same limiter; a new door names its limit.
- **CORS / CSRF / CSP** — `django-cors-headers` with an env allow-list;
  session + CSRF for a same-site front end, token auth for everything else;
  `django-csp` in production settings; a route is never `@csrf_exempt`.
- **MCP auth** — bearer tokens now; the MCP OAuth 2.1 flow is the recorded
  upgrade when a third-party client must connect; sockets gain the same
  bearer path.
- **File storage** — `apps/files` (ADR files-2, which supersedes the
  django-storages design that used to sit here): the **boto3-backed storage
  seam** — `apps/files/storage.py` is the one module under `apps/` that
  imports boto3, names a bucket setting, signs a URL or reads an object's
  bytes (MinIO in dev, S3 in production, one seam; **not**
  django-storages) — keys immutable per version, shaped
  `t/<tenant_pk>/f/<file_pk>/v/<n>` (pks only, never tenant slugs or
  filenames); bytes never transit Django (presigned URLs both directions,
  TTLs declared in settings); uploads two-phase through services, and
  "replace" is a new `FileVersion`, never an overwrite.
- **Tenant settings & flags** — `Tenant.settings` JSON (merged key by key;
  the values are NOT schema-validated — a declared gap, `architecture.md`) +
  `core.flags.is_enabled(tenant, name)`; no third-party flag service; a flag
  is named in the rung that adds it and removed by a named later rung.
- **Events** — `v` on every payload; the outbox is retained;
  `manage.py replay_events` is the recovery path, so a consumer must be
  replay-safe.
- **Erasure & retention** — `accounts.services.erase_user`; audit/outbox
  archival is a dated residual with a trigger in the product's queue.
- **Seed, backup, restore** — `manage.py seed` is dev data only (the method
  still drives from zero); `scripts/backup.sh`, `scripts/restore_drill.sh`
  exist so the restore tripwire has something to fire.
- **Runtime** — `/healthz` (liveness) and `/readyz` (db, redis, temporal); a
  rung that adds a runtime dependency adds it to `/readyz`.
- **CI** — GitHub Actions runs `./scripts/check.sh` (full) on every PR; the
  gate is the only CI; a rung never adds a second pipeline.
- **i18n** — off by default (`USE_I18N=False`); `Tenant.timezone` / `locale`
  are present for display; a product turns i18n on as a recorded decision.
- **Template updates** — `docs/product/architecture.md` § "The platform the template ships", the
  "Template updates" row, is the ruling; this line does not restate it.
