# ADR ident-13

- **ADR ident-13 (a realm per tenant — identity option B) · 2026-09-30**
  *(rewritten; the draft written for `enforced` alone is withdrawn)* ·
  **context:** `enforced` promised and did nothing, because the login policy
  is per organisation and every tenant lived in the deployment's one; and a
  customer surface is an external identity population, which must not share a
  login policy, a password rule, a provider list or branding with staff or
  with another customer · **decision:** a realm per tenant, created when the
  tenant is (`core.services.create_tenant` asks through `core.bridge`; the
  run is `EnsureTenantIdentityHomeWorkflow`; the row is
  `accounts.IdentityHome`, `pending` until the run lands, failing closed),
  through a port we own — `apps/accounts/realm.py::IdentityRealm`, the
  per-tenant operations option B adds and nothing more, over our own
  dataclasses, Zitadel its first adapter
  (`apps/accounts/realms/zitadel.py`: organisations, project grants, the org
  scope), chosen by `realms.current()`; the deployment's existing
  organisation is the staff realm; the platform's one project is granted to
  every tenant realm with the project check on; a tenant's `enforced` is its
  realm's login policy (password off, the provider required); one `User` per
  person, several subjects through the identity join keyed `(realm,
  subject)`, introduced by verified address with the realm known; a verified
  domain claim confines the sign-in it starts to the claiming tenant's realm
  (`selectors.authorize_url_for` hands the connection's tenant realm to
  `get_platform_login_url`, which adds the adapter's org scope —
  `realms/zitadel.py`'s `authorize_params`); an unclaimed address's sign-in
  is not confined, and its realm is read off the assertion;
  `User.zitadel_sub` retired into the join, its column drop a later release;
  no migration road — a deployment with no production users re-seeds ·
  **rejected:** one organisation with per-tenant providers (no per-tenant
  policy exists in it); an instance per tenant (N client secrets in the
  relying party); an organisation per surface (a surface is a face, a realm a
  population); a person per tenant (every foreign key hangs off `User`);
  Zitadel's domain discovery for the org scope (its primary-domain form needs
  Zitadel-side domain verification, which this template does its own way —
  ADR ident-10); porting the deployment-level
  bootstrap now (one vendor, and rule 27 already fences it); a migration mover
  (nobody is in production) · **consequences, read off the tree:** (a) **the
  staff realm has two spellings, and the second is a finding.** The ruling is
  one realm, one name, by its id; the tree stores the staff realm's join rows
  as `staff` (`apps/accounts/models.py::STAFF_REALM`) and its organisation id
  on the one tenant-less `IdentityHome` row the seed writes, and an assertion
  naming any realm id that is not a tenant realm's — an unknown or a removed
  organisation's included — reads as `staff`
  (`apps/accounts/selectors.py::get_realm_of_assertion`). (b) **A realm is
  keyed by its id, never its name**: a new organisation may take a removed
  one's name, and the audit reads `facts` by id. (c) **The set-your-password
  link follows the sign-in door.** Under `SIGN_IN_DOOR=ours` it is the
  surface's own entrance, built by `absolute_url` with the invited role's
  surface; under `hosted` it is Zitadel's own page on Zitadel's host
  (`apps/accounts/zitadel.py::invite_url`), carrying the platform's `userID`
  and `code` and nothing of ours — the person's realm is read at sign-in, from
  the assertion. (d) **`enforced` on the wire is a pair**:
  `SsoConnectionOut.enforced` is the intent on an active connection whose sync
  has applied, so a release still pending reads `false` while the realm still
  enforces, and `sync_state: pending` beside it says so. (e) **Link removal is
  not a port operation**: erasure removes the staff realm's federation links
  before deactivating, and deactivates a tenant realm's account, through which
  no link can sign in. (f) **A rollback re-spells.** A reverse to the
  migration before the join re-homes every tenant-realm subject as staff; the
  person's next sign-in names its realm and writes the row back in it, and the
  stale `staff` row remains beside it: nothing retires it yet, and the
  assertion's realm claim decides every real sign-in, so it is inert ·
  trigger to revisit: a second realm adapter is real
  (the bootstrap moves behind the port in that release); a tenant that needs
  two realms; the first deployment WITH production users that must move to
  this shape — then, and only then, a mover is designed.
