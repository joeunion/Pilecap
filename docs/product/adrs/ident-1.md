# ADR ident-1

- **ADR ident-1 (Zitadel topology)** · context:
  compose ships one `postgres:16`; Zitadel needs Postgres · decision:
  one pinned Zitadel container + a dedicated `zitadel` **database on our
  existing Postgres service** (created by an init step, isolated by
  database not by instance), masterkey and first-instance config by env,
  and a **FirstInstance machine user whose PAT lands on a shared
  volume/env** — the credential our provider service authenticates the
  management API with · rejected: a second Postgres container (second
  stateful service, port pair, backup story for nothing), Zitadel Cloud
  for dev (the loop must run on a laptop, V3's lesson generalized),
  CockroachDB (Zitadel's other backend; heavier for zero gain) · trigger to revisit:
  production deployment → its own managed Postgres, recorded then.
