# ADR ident-12

**ADR ident-12 · 2026-09-19 · every Zitadel session the sign-in seam opens,
it closes — except the one a client is about to spend.**
*Context*: two things made this an ADR of ours rather than a comment. First,
the rule itself has been cited in this tree as "ADR ident-10" since rung A3 —
`apps/accounts/signin.py`, `apps/accounts/zitadel.py`, `apps/accounts/views.py`
and `apps/accounts/tests/conftest.py`, eight comment lines — but **ident-10
here is the domain-claim ADR**; the session rule is the CONSUMER's ident-10,
which design I-A §J5 cited with the qualifier and the code dropped. Those
eight citations should read ident-12 and do not yet (A11's territory reached
one of the four files; the correction is booked, not done). This ADR is
**ident-12 and not ident-11** for a second reason worth a line: house rule 57
cites "ADR ident-11" and no ADR of that number is written anywhere in this
file — a dangling citation older than this ADR, booked with the eight above. Second, rung A8
found a case where the rule cannot hold. *Decision*: `apps.accounts.signin`
opens a Session API session per ceremony and closes it at EVERY exit — the
refusals, the outages, the person's *Never mind*, and a second `begin` over a
ceremony already in flight — so a half-authenticated session is never left on
the identity platform for a person who did not finish. `_forget` is the one
place that closes, and every road leaves through it.

**SIGNED by the owner 2026-09-19 ("sign all three", recorded by the PM).** *The amendment*: on the Mode A
road (design C-10), a ceremony that FINALIZED an OIDC auth request leaves its
session open to the platform's own lifetime. *Which principle bends*:
principle 18 (least privilege, minimum necessary lifetime) and this ADR's own
rule. *Why the default is insufficient*: MEASURED on v4.17.1, 2026-09-19 — the
finalize answers a callback URL carrying a code, the CLIENT spends that code
afterwards on its own connection, and Zitadel validates the session the code
was minted against at that moment. With the session closed on our way out the
exchange answers `400 invalid_request "Errors.Session.Terminated"`, so the
person is signed in nowhere and the app that sent them gets an error, after a
sign-in that is perfect from both ends. *Alternatives*: close the session and
have our server exchange the code (a second token road, and the client's own
PKCE verifier is not ours to hold); delay the close behind a timer (a thread
or a workflow for a ten-minute object on somebody else's server, and the
client's timing is not knowable); keep it and accept the risk, which is this.
*The risk*: an authenticated session exists at the identity platform that
nothing of ours will close. *The mitigation, and why the risk is small*: the
session TOKEN is the only handle on it and never leaves the process — the
ceremony holding it is deleted in the same call — and M7 measured that the
browser is left holding a device cookie and no session, so a second authorize
with `prompt=none` answers the sign-in page rather than a code. The session
expires on the instance's own clock. *Reversal*: one argument to `_forget`;
`test_a_finalized_session_is_left_for_the_client_to_spend` and
`test_every_other_road_still_closes_its_session` are the pair that would flip
together. trigger to revisit: a Zitadel build that validates the session at
FINALIZE time instead of at exchange time (the measurement kit's M3 is the
line that would notice), or a deployment whose session lifetime is long
enough that an unclosed one is worth an operator's attention.
