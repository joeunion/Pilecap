# ADR accounts-1

**ADR accounts-1 · the invitation provisions the person; there is
no signup door.** *Context*: an early from-zero persona walkthrough had one step with no door at
all. `/accounts/signup/` 404s, the login page rendered a heading
and nothing under it, `bootstrap_tenant`'s advice told an operator to run
`seed` — which makes a tenant and so destroys that command's own precondition —
and the field test ended up at `createsuperuser`: no service, no audit row, no
tenant. The invitation email, meanwhile, carried no link anybody could act on;
it pointed at that formless login and offered a signup that does not exist. It
worked for scripts, because the API hands the token back to the *inviter*, and
was a dead end for every invited human. Rule 42 could not see any of it: it
walks `@service` definitions outward to doors, and **a job with no service is
an absence, not a doorless service** — the census read accounts at zero while
the product had no way to create a person (that blind spot is now declared in
rule 42's `does_not_cover`). *Decision*: **no standalone create-account; the
invitation is the door.** `core.services.invite_member` writes its row and, on
commit, starts `ProvisionInvitedPersonWorkflow` under a deterministic id keyed
on the invitation's primary key. Its first activity makes the person real in
the identity platform through the rule-27 door — Zitadel's v2 `AddHumanUser`
with **no password**, search-then-create idempotent, then `CreateInviteCode`
with `returnCode` — and its second activity is the existing generic
`send_email`, so the message still travels rule 25's one allow-listed sender
and Zitadel mails nobody. The email's primary link is the credential-setting
page, whose shape was measured by fetching it against the pinned build rather
than read off a doc page. A person who already signs in here gets the
sign-in branch instead, because `CreateInviteCode` refuses an initialized user
and that refusal is an ordinary outcome, not a fault. Membership is still ours:
`accounts.adapter.accept_pending_invitations` matches our row at sign-in.
*The tension, named rather than waved past*: **the invite code crosses Temporal
history**, inside the link, for as long as retention says — and `core.mail`'s
own docstring has always said the invitation carries no credential *because* a
bearer token in a payload is a bearer token in history. That reasoning stands
and this is genuinely different in kind: our token authenticates a person to
everything they can reach, for its whole life, silently. The invite code is
single-use, short-lived (three days, measured off Zitadel's own secret
generator, which is also the number the email states), superseded the moment
another is issued, and it opens exactly one screen — the one where somebody
with no password chooses one. It reads nothing and grants no membership. The
rule it does not license: our own credentials still never enter a payload.
*Rejected*: **`sendCode`** and letting Zitadel mail the invitation (a second
sender that knows nothing of consent, quiet hours or suppression — rule 25
bypassed, and wording no test of ours can read); **open signup / Zitadel hosted
registration** (a product may turn it on as *its* choice; the platform will not
ship a door that creates people nobody invited); **a `zitadel_user_id` column
on `Invitation`** (idempotency is search-then-create against the identity
platform, which is the authority — a column would be a second copy of its
answer and a migration this ADR does not need); **rewiring delivery to
`comms.send()` here** (the substance the queue row asked for is that
*we* deliver and Zitadel does not, and that is kept; the `core.mail` →
`comms.send` rewire is ADR comms-2's named follow-on and keeps its own row, so
the rule-25 ratchet stands unchanged at one rather than moving under a rung
that is not about it). trigger to revisit: Zitadel routing `/v2beta` or
moving the login UI off `/ui/login/user/invite` (both are pinned facts here,
measured, and `zitadel_audit` is the tripwire); a product that wants open
registration; the comms rewire landing, which is when the delivery half of this
ADR is restated in comms' terms.
