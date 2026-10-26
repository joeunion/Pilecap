# ADR workflows-3

- **ADR workflows-3 (WorkflowRun scoping)** *(moved
  verbatim from
  `cycles/2026-08-22-cycle-p1-workflows-pay-their-debts.md` §ADRs)* ·
  2026-08-22 · context: `WorkflowRun` is tenant-required, so
  deployment-wide work has no ledger — erasure of a person with no
  tenant *skips identity revocation* and logs
  `accounts.identity.not_revoked` (a real hole pinned by test), and
  workforce identity sync borrows a tenant to get a row · decision:
  **`WorkflowRun` is the platform-wide run ledger** — `tenant` becomes
  nullable (an abstract-base field override; ONE expand migration,
  riding W1's leaf), and **null is a declared population, not a
  loosening**: a platform run's workflow id carries `PLATFORM_SEGMENT`
  (`"platform"`) as its first segment, `check_workflow_id` requires that
  segment iff `tenant is None`, `for_tenant(...)` keeps failing closed
  (it can never see a platform row, so every tenant door — REST, MCP,
  admin via `ServiceModelAdmin.get_queryset` — is unchanged by
  construction), and `for_platform()` is the one read path for the null
  population. `create_tenant` refuses the slug `"platform"`,
  because `SlugField` would otherwise mint a tenant whose runs collide
  with the platform's — the segment must be un-mintable, and a guard at
  tenant creation is the closed question that makes it so · rejected:
  **a system tenant** (a synthetic member of a real population is a lie
  every future query over tenants — billing, counts, admin lists, loops
  — must remember to exclude; and rows of *other* models would accrete
  onto it), **status quo + named gaps** (this is an erasure-compliance
  hole; naming it does not deactivate the Zitadel account) · trigger to
  revisit: a second model needs a platform population → decide then
  whether the nullable-with-declared-population shape generalizes or a
  platform scope becomes a first-class base.
