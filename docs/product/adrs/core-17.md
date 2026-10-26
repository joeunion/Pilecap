# ADR core-17

- **ADR core-17 (first-tenant bootstrap)** · context: no runbook step
  creates the first tenant on a real
  environment; seed --force is forbidden there by design (the first
  environment was bootstrapped by hand); an earlier disproof left a
  residue to pin · decision: manage.py
  bootstrap_tenant — a @service-backed command minting exactly one tenant
  + root org + one owner membership for a named workforce email; refuses
  if ANY tenant exists; audits door=shell with tenant=the created tenant
  (the birth certificate); create_tenant stays unaudited ·
  rejected: auditing into the platform population (the row is about a
  tenant that now exists), relaxing seed for production (seed is dev data
  by contract), a web-based first-run wizard (a door with no
  authenticated caller yet — the shell is the honest door at zero) ·
  trigger to revisit: multi-tenant-at-birth products.
