# The client layer

The long form of `django-architect` § E+.

## E+ · The client layer — the REST door's first consumer

A shipped user interface is a **client of the REST door**. This section is the
category and what follows from it: which house rules cross the language
boundary, which ones change sentence on the way, and which ones have no member
on the far side at all. **How the client is written is
`.claude/skills/fe-conventions/SKILL.md`** — the wrong form and the right form
for every convention below live there, and are deliberately not repeated here,
for the same reason `conv §n` is cited rather than quoted.

**E+1 — A user interface is a CLIENT, never a sixth door.** *Why:* every door
law is **vacuous** over it. House rule **10** (every door calls services), rule
**42** (every service is reachable through a door — some module the mounts
discover calls it by name), §G2 (what every door binds) and §C7 (the door half
of authorization) all phrase doorness as *reaching services by name inside this
tree*. A member for which every law of a category is vacuous is in the wrong
category, and the classification error is not cosmetic: door status would
license the client to **resolve authority**, which is the one thing a surface
running on somebody else's machine must never do. Nor is the client outside the
architecture — the contract between the backend and its consumer is a mechanism
this platform owns, and a product that treated it as somebody else's problem is
exactly how the two ends come to disagree about what a refusal means. The
category was already load-bearing before it was named: ADR api-1's revisit
trigger names the generated TS client, and §E9's `Remedy(label, destination)`
was designed for a button on a screen. *Enforced:* review (the app map carries
the client as a consumer row, not a door row); the rules below carry the
mechanical halves. *Wrong:* an interface holding a role check that decides what
a user may do, or reaching the database through an endpoint of its own shape.
*Right:* it calls `/api/v1/…` through the generated client and renders what the
refusal registry tells it.

**E+2 — The shape is doctrine, in five clauses.** **One** external consumer;
a **generated** client (`scripts/gen_client.sh` — a build artifact of the tree
it came from, and the reason a client and its contract are the same commit);
**one door** to the backend; the browser's credentials on the session, never a
second auth system; and **it never resolves authority**. A lead adopting a
client records the choice the way every other stack choice is recorded — an
ADR line in the format §J's neighbours use, and a stack-table row naming the
rejected alternatives with their reasons (an in-process template layer couples
the surface to the app registry and reopens rule **14**; a bespoke second API
shaped for the screen is two contracts, which is rule **17**'s drift one
surface over). *Enforced:* review; ADR line.

**E+3 — The relationship to REST is COVERAGE, never parity.** Rule **17** asks
*is this capability on both doors* and answers yes or no, because REST and MCP
are two doors onto one service layer. The client asks a different question —
*which operations does the interface reach, and which does it deliberately not*
— and the honest answer is a **census**, derived from the published document,
never a hand list. An interface covering a subset is not a violation; an
interface claiming a completeness it cannot enumerate is. *Enforced:* criterion
(the coverage census names both sets, each read off the OpenAPI document) until
the census rule lands in `rules.yaml` with its `does_not_cover`. *Wrong:*
"the UI has parity with the API". *Right:* "these 14 operations are reached,
these 9 are not, and the list is derived".

**E+4 — The transfer map: which house rules cross, and how.** Three lists, and
the third carries as much weight as the first two.

**TRANSFER as-is** — the rule's sentence is already language-neutral:

- **11** — the layer taxonomy IS rule 11 in another language. A
  `utils`/`helpers`/`lib` module doing a canonical job is the same violation
  there that it is under `apps/`.
- **16** — the naming grammar, with one addition that only exists on this
  side: **generated client types are used verbatim and never re-declared**. A
  hand-typed interface shadowing a generated one is a second contract with no
  gate on it, and it goes stale silently.
- **23** — supply chain clean, over a second dependency population (the package
  manifest and its lockfile, audited and licence-checked like the first).
- **7** — declared import contracts. This is where *a screen imports only from
  components* lands: it is §A2/§A3 in another language, an existing grammar
  with nothing new in it, and it needs no rule of its own.
- **the whole enforcement grammar** — valves that carry their reason, censuses
  over discovered populations, canaries that must fire or the run is exit 2,
  `does_not_cover`, ratchets, and **0 clean · 1 violations · 2 enforcement
  broken**. The rule that makes a second language safe here: **an external
  runner is a measuring instrument, never a judge** — it reports targets and
  findings, and the engine keeps overrides, floors, canary attribution and the
  verdict.

**TRANSLATE** — the intent crosses, the sentence changes:

- **12** (reads and writes are separate) → **rendering and requesting are
  separate**. A component renders; it does not fetch. One mutation wrapper
  carries the idempotency key, the CSRF token and the acting hat, so no screen
  assembles those by hand and no screen can forget one.
- **14** (HTTP vocabulary never below the doors) → **HTTP vocabulary never
  appears ABOVE the client seam**, and this is the sharpest of the set. A
  screen switches on the **refusal code** and renders the registry's fact and
  remedies (§E9); ONE module maps wire refusals to surface state, and it is the
  mirror of `config/api.py`. A status-code comparison inside a screen is
  exactly the defect a service raising an HTTP exception is.
- **5** (query budgets at seeded scale) → **browser budgets**: requests per
  screen and a bundle floor, pinned at a stated scale, with the rising-floor
  shape rule 5 already uses.
- **27** / **33** / **48**'s fence (one door to the identity platform, to the
  search index, to the object store) → **ONE DOOR TO THE BACKEND**. No module
  outside the client seam names the API origin or issues a request to it — the
  fence is what keeps the generated client's sentence true, because a second
  request path is a second contract with no document behind it and no census
  over it.
- **17** → the coverage census of §E+3.
- **32** → **consumed, not transferred**, and this row is the one to check
  first. The rule is two closed populations read off the Django **app
  registry**, and there is no app registry on the far side of the seam; worse,
  on a filesystem router the first segment IS the module path, so *"names a
  resource, not the module that serves it"* has no satisfiable form there at
  all. What crosses is the consequence, not the check: the API surface's
  resource-first paths are something the client **consumes and never
  re-shapes** — the generated client carries them, and no screen composes a URL
  of its own. *This row awaits the lead's stage-2 confirmation; it is stated
  here as a consumption note and is not claimed as an enforced transfer.*

**DO NOT APPLY** — the anti-cargo-cult list, and it is load-bearing: **1**,
**2**, **6**, **8**, **15**, **18**, **20**, **21**, **22**, **24** and **26**
have no member on the far side of the seam, and the reason is the same for all
of them: there is no ORM there. No `auth.User` import (**1**), no model base
class (**2**), no queryset and no tenant or org manager (**8**, **24**), no
field type (**15**), no admin (**21**), no service signature to check a named
parameter against (**26**); no migration at all, which is what empties **6**
and **22**; and no workflow to give an id to (**18**) or ledger row to declare
append-only (**20**). A rule transplanted where it has no member is worse than
a rule missing, because it goes green forever and teaches its reader that the
gate is theatre. **25** never applies: the client is not a
sender, ever. And **9** / **28** apply by **forbidding the thing outright** —
**there are no client-side workflows, by law**. Anything that waits or retries
is a Temporal workflow behind the door (§E4); a screen **polls the run row**
and renders its state. A retry loop in a browser tab is a workflow nobody can
find, resume or audit.

**E+5 — The one shadow, declared rather than discovered.** A client cache keyed
by the acting hat must be invalidated when `X-Org` changes, and no check on
either side of the seam sees a stale cached read — the server answered
correctly for the hat it was given. It is a **declared blind spot by
construction**, named here so a lead writing client criteria states its
handling rather than discovering it (the same posture §E10 takes for the
computed aggregate). *Enforced:* criterion (the hat change is shown to
invalidate, with the stale read reproduced first).
