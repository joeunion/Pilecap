# ADR ident-9

**ADR ident-9 · 2026-09-07 · the first identity has a door of its own, and it
shuts behind itself.** *Context*: with self-registration closed (ADR ident-8) a
deployment without a workforce IdP has no way to its first identity but the
Zitadel console or the `FirstInstance` admin — measured from zero on a sibling
product at twenty-one minutes, every step of it read off somebody else's admin
UI; and `bootstrap_tenant` needs a `User` that only a first sign-in can mint.
*Decision*: `manage.py zitadel_first_admin --email <address>` mints a
credential-less Zitadel human and an invitation code through the existing
`accounts/zitadel.py` writers (`ensure_invited_user`, `create_invite_code`,
`invite_url` — no new writer) and prints the hosted set-password link and the
two steps after it: sign in at the product so the adapter mints the `User`, then
`bootstrap_tenant --email`. It writes one row of ours, an audited
`FirstAdminVouch`, and no tenant — the birth certificate stays `bootstrap_tenant`'s
audited write (ADR core-17) (amended by FIRSTADMIN-1, 2026-10-19: the command
writes one audited `FirstAdminVouch` — single-use, 7-day, honoured only while no
tenant exists — which the workforce wall reads as its third vouch kind, beside the
workforce domain and the tenant invitation; the first live deployment's first
admin was refused `domain_not_allowed` without it). **It refuses once any tenant exists**, so
`core.services.invite_member` through REST and MCP is the only invitation path
from the first member on; it also refuses an unconfigured platform, a loopback
`PUBLIC_BASE_URL` outside DEBUG (the printed steps would be a dead end), and a
`--email` that is not an address. The code is printed once and is in no log line
and no row (`returnCode`, never `sendCode`: house rule 25 gives the product one
sender and Zitadel is not it), the precedent being the client secret
`--rotate-web-secret` prints. A federated deployment needs no command: first
sign-in through the workforce IdP, then `bootstrap_tenant`. *Rejected*: the
product's invitation workflow at zero (it needs a tenant, an actor, a running
worker and a mail path before the first human exists, and lands on the same
undriven hosted last mile); `bootstrap_tenant` creating the Zitadel human
(`core` may not import `accounts.zitadel` — house rules 7 and 27); a
dev-user-shaped account with a password we choose (a credential we transport —
`ensure_human_user`'s own docstring says why not); documenting the console path
only (the wall stays); an option on `zitadel_seed` (that runs on every
`setup.sh`, and a once-on-purpose act with a credential on stdout is its own
command); a `--force` on the tenant-exists refusal (the product has an
invitation door; a force flag is a second one). trigger to revisit: the first
product that federates at birth and never runs this command — then it is
deleted, not kept; or the hosted invite page becomes driveable headlessly, at
which point the command's printed steps can be verified by machine instead of
by a person once.
