# ADR deploy-1

- **ADR deploy-1 — TWO decisions share this id**; both stand, both cited
  (`deploy/compose.yaml` cites both meanings on one file).
  **(a) the environment shape** · context: the Deployability pillar needs a real
  environment; the Hosting row ships everything a choice needs and
  presumes none; the ratified band is ~$40–90/mo, teardown-friendly, and
  every self-hostable organ was ruled self-host (ClickStack explicitly;
  Zitadel in the same breath) · decision: one EC2 Graviton box per
  environment running a production compose (web, worker, Caddy TLS,
  Temporal, Zitadel, Redis, otel-collector, ClickStack) + RDS Postgres +
  S3 + Secrets Manager; provision/teardown as plain `aws` CLI scripts in
  `deploy/`; the template's own environments run self-hosted Temporal
  (the Hosting row's recorded alternative, ratified as a
  divergence from "Cloud by default") · rejected: ECS Fargate + ALB + ACM
  (~$50/mo dearer before the first container, splits the compose into
  task definitions, and teardown-friendly it is not), Kubernetes (the
  row's own words: an escalation, not a default), Postgres-in-compose for
  the environments (forfeits the managed-snapshot half of the backup
  posture B1 drills), an IaC framework (a toolchain tax at one box per
  env; the runbook must be performable by a stranger with aws-cli and
  ssh) · trigger to revisit: a second standing environment, a real
  product's traffic, or the box's memory headroom measured under 20% at
  V1.
  **(b) the Postgres major pinned at 18** · context:
  RDS runs 18.3, every pinned client 16.10, pg_dump refuses
  cross-major, and provision.sh lets AWS's default decide · decision: the
  template targets Postgres 18 (the reasoning: the live instance is
  the fact on the ground; client moves are cheap; pg_dump 18 reads 16
  worlds; EOL runway) — compose.yaml postgres:18, deploy/compose.yaml
  postgres:18.6 (latest 18.x minor), provision.sh --engine-version 18 +
  --auto-minor-version-upgrade · rejected: pin 16.10 + rebuild RDS
  (owner-approval infra act to buy a shorter-lived major), no pin (the
  finding itself) · trigger to revisit: a stack component
  (Zitadel/Temporal) refusing 18 — the rung's own stop-and-report.
