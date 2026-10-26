# ADR deploy-3b

- **ADR deploy-3b (`DATABASE_URL` empty; `PGSSLMODE=require`)** ·
  context: a URL wins over the parts (`base.py`), and a
  URL carrying no TLS parameter silently downgrades RDS to plain TCP ·
  decision: the manifest leaves `DATABASE_URL` empty and sets libpq's
  own `PGSSLMODE=require`, which every consumer (Django, `pg_dump`,
  `psql`) honors without a code path · rejected: `?sslmode=require` on
  the URL (only Django reads it; the backup script would not) · trigger to revisit:
  a second database consumer that does not speak libpq.
