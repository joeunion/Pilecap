# ADR ident-8

**ADR ident-8 · 2026-09-07 · the sign-in posture is deployment
configuration, materialised through the one identity door.** *Context*: the
hosted login shipped with self-registration allowed, no lockout and public
organisation creation open on every environment (measured live before the
rung: `allowRegister: true`, no `maxPasswordAttempts`, `GET
/admin/v1/restrictions` = `{}`, `/ui/login/register/org` serving a working
form), against ADR ident-4's rejection of open signup. *Decision*: three
settings read from the environment (`ZITADEL_ALLOW_SELF_REGISTRATION`,
`ZITADEL_ALLOW_PUBLIC_ORG_REGISTRATION`, `ZITADEL_MAX_PASSWORD_ATTEMPTS` —
the NIST SP 800-63B ceiling, a product tightens it), materialised by
`zitadel_seed` through full-body `ensure_*` writers on the admin API and
reconciled by `zitadel_audit` (drift is exit 1 naming the remedy); the compose
`DEFAULTINSTANCE_*` keys carry the same values for a fresh instance and are
the belt, never the mechanism — they apply at instance creation only, and the
belt may be tighter than the mechanism but never looser. Every writer declares
the resource's full field set beside itself, read from the running build's
API document, and a census test refuses a body that is a strict subset (the
convention that closed the two partial writers that already existed: the
label policy, five fields short, and the OIDC provider's `usePkce`).
*Rejected*: an intent row plus workflow kind (a runtime door for a value no
runtime persona holds — cost without a reader); compose keys alone (every
existing instance stays open). *Measured at landing*: the instance-level write
closes every org without a policy of its own, which is every org a fresh
clone creates; on the shared laptop instance the org's own login policy had
already been closed by a sibling product, so the door that visibly moved was
public org registration, 200 → 404. *The org-level half, settled 2026-09-07*:
`zitadel_seed` reconciles the credential's own org's login policy **only where
that org has a policy of its own** (`isDefault` absent on the management `GET`)
and leaves an inheriting org inheriting, because creating one would fork a
value into two owners and make every later instance-level change silently not
apply here (first principles 9); `zitadel_audit` judges that org's
`allowRegister` where it is the org's own and defers to the instance verdict
where it is not, so one console edit is one disagreement. Measured on the pinned
build: `PUT /management/v1/policies/login` on an org with no policy of its own
answers `404 Org-M0sif`, so the branch is the API's own shape and not a
preference; and on the shared instance the org's `allowRegister` alone decided
whether `/ui/login/register` served a working registration form or an error
page. trigger to revisit: the first product that wants per-tenant
registration or lockout policy — then the row shape, with the audit comparing
against the row.
