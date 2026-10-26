# ADR core-23

**ADR core-23 · the refusal registry carries the per-code facts; the replay
boundary is derived from it.** *Context*: `CODE_STATUS` and
the idempotency replay split both needed a per-code fact the refusal registry
already almost carried — and the registry was the only place a new code is
*discovered* rather than appended. *Decision*: `register_refusal` gains
`status=` — **optional, not required**, for three live reasons: rule 47's two
canaries would exit-2 at import if a status were demanded of them;
`invalid_arguments` is a MACHINE-door code with no HTTP status to declare; and
absence-is-a-declaration keeps the drop path reachable. `CODE_STATUS` and
`envelope_codes()` are derived off the registry, and the one-line status joins
each existing registration at its declaring site across apps. The replay
boundary is `boundary == "door"` — **boundary-as-door is doctrine, not
convenience**: a door refusal (bad credential, addressing header, CSRF, rate
limit) is decided in *front* of every service, on material the body
fingerprint does not name, and it ran nothing — the key was never spent.
Remembering one poisons the key for its whole TTL: the client that fixed its
credential and retried got the stale refusal back with `Idempotent-Replayed:
true` and could never reach its write — the exact poisoned-key class, and the 429
rate-limit second instance found in-rung. The door set is the only set
coherent with the middleware's own key-reuse arm, and it is a **closed
question over a discoverable population** — a code registered
`boundary="door"` next month joins by being registered and by nothing else.
*Rejected*: a second code→status registry in `config/api.py` (the append tax
re-created one file over); an envelope column on `IdempotencyRecord` (schema
with no reader; the 5xx drop-the-claim arm already exists); a hand list of
envelope codes (the set is open; the checklist forbids it); the plan's
original *fingerprint framing* of the boundary — the R2 builder found
`invalid_body`/`method_not_allowed` differ between the two framings, which is
this ADR's own revisit-trigger firing in-rung; the ruled `boundary=="door"`
derivation was implemented and ratified. *Deliberate residual*: a domain `403
forbidden` for an actor promoted between two calls still replays — a policy
decision is a decision about this fingerprinted request, made below the
doors; a client that wants the new answer says so with a new key. *Trigger to
revisit*: a code whose replay class differs from its boundary. Long forms:
`apps/core/idempotency.py` (module docstring + `REPLAYABLE_BELOW`),
`apps/core/exceptions.py` (`status` grammar + `envelope_codes`).
