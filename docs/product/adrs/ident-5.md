# ADR ident-5

- **ADR ident-5 — TWO decisions share this id**; both stand, both cited.
  **(a) test posture for Zitadel** · the settled decision: test posture
  for Zitadel mirrors the posture already settled for Temporal (ADR
  ident-5): the suite, `--loop` and CI never dial
  Zitadel — `config/settings/test.py` points the issuer at a
  must-not-dial address and the RP/JWT paths are proven against an
  in-process stub issuer (signed JWTs, real JWKS shape); only a
  dedicated verification pass drives the real container, and CI stays
  Zitadel-free. Rejected: suite requiring Zitadel up (every gate run
  leaking state into a shared service), mocking at
  the allauth layer (proves our config, not the protocol — the stub
  issuer signs real JWTs so JWKS/audience/expiry paths execute) ·
  trigger to revisit: first product CI needing a live-identity e2e leg.
  **(b) what erasure erases, and what survives with reasons** ·
  context: PII was found surviving `erase_user`
  in four tables; the docstring claims completeness it does not have ·
  decision: the sweep extends to allauth `EmailAddress` (rows deleted),
  allauth `SocialAccount` (rows deleted — the identity link is revoked
  Zitadel-side already), `SsoIdentity.email` (redacted to the
  `erased+<uuid>@invalid` form), `Invitation.email` (voided + redacted
  through `core.redact_invitations` — a platform-wide sweep keyed on the
  email, `system`-actor shaped, `# reach:` declared); retained
  populations each carry a written reason: `zitadel_sub` (the
  cross-tenant subject-collision fence — an opaque identifier, not
  contact data; verified against the A9 collision
  tests, stopping and reporting if the truth differs), memberships and
  `AuditEntry` (the docstring's own audit-trail argument),
  `Event`/`Outbox` payloads (declared not rewritten, by ruling) ·
  rejected: deleting allauth rows by cascade from User deletion (the row
  stays — settled), event-payload rewriting (the same ruling) · trigger to
  revisit: the first compliance ask (which also triggers the
  Event/Outbox archival residual).
