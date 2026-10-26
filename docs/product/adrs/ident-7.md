# ADR ident-7

**ADR ident-7 · scoped API tokens: the credential carries a
ceiling, and the ceiling is derived.** *Context*: the owner's ruling
(design-agreements.md): the platform's
posture is bring-your-own-agent through `/mcp`, so tokens are handed to
third-party agent runtimes as ordinary practice — and today an `ApiToken`
carries the full power of its person. An early persona walkthrough minted exactly such a token and
drove the whole arc on it, which is the practice the ruling names.
*Decision*, in seven parts. **(1) Two filters, never two truths.** A token's
`scopes` are a CEILING checked at the doors; the person's `Membership.role`
and each app's `policies.py` keep deciding underneath, untouched. Effective
capability is the intersection: the ceiling can never grant — a token scoped
`core:write` held by a `member` is still refused by the escalation wall, and
the wall's refusal is the one the caller sees (rule 29's spirit at the
credential layer: nothing a token holds exceeds its person, by construction,
because ∩ never widens). Scopes are read in exactly two seams — the REST door
plumbing and the MCP mount — and **nowhere below**: a service, selector or
policy that consults `token.scopes` is the second permission system this ADR
exists to refuse (the quality batch's rule, id PM-assigned, closes the class).
**(2) The vocabulary is derived, never enumerated.** A scope is
`<family>:<verb-class>`. The family population is the discovered `TAGS` keys —
the same discovery that already builds `INSTALLED_APPS`, the mounts and the
OpenAPI tags section — so a product that adds an app with a tagged router
gets its scopes for free, no registry edited. The verb classes are exactly
two, `read` and `write`. Per REST operation the derivation is total and
unambiguous by machinery that already exists: every operation carries exactly
one tag (the one-tag-per-operation gate clause is what makes this a
function, not a relation) and its method classifies it (GET/HEAD → `read`,
everything else → `write`). Per MCP tool: the tool's REST twin's scope, off
the same introspect registries rule 17 already diffs; a tool with a recorded
parity exemption classifies its own `<nouns>.<verb>` name against the two
declared grammars (selector `get`/`list` → `read`; rule 16's service-verb
lexicon → `write`); a tool or route whose scope cannot be derived is a
finding, never a fallback. **No per-route annotation exists** — there is
nothing to annotate and therefore nothing to drift. **(3) The tag key is now
wire vocabulary.** It sits under the renamable display name exactly as D10
prescribes — immutable key, renamable label — and renaming a key after launch is
a credential-breaking change of the same class as renaming a URL (the
versioning argument). **(4) Enforcement at the doors, both, before the
service runs.** REST: one check in the door plumbing (`config/api.py`'s
territory), after the token resolves and before the view — never in a route.
MCP: inside `core.mcp.tool_call`, the one contextmanager every tool already
enters. The refusal is a NEW registered code, `insufficient_scope`, E9's
grammar at import: the fact names the missing scope in a plain sentence, the
structured remedies name the mint door, and `wire_refusal` composes the one
body both doors send — byte-identical, rule 17's spirit. **An out-of-scope
tool refuses when called and never disappears from `tools/list`** (GitHub's
shape, not Stripe's): the list is the agent's map and each entry's rendered
description carries its derived required scope, so a narrow agent can still
tell its human "mint me `widgets:write` and I can do this" — hiding would
amputate the remedy channel and stand up a second enforcement point that can
disagree with the call-time check; and tool existence is public in
`llms.txt`, so there is no existence oracle to protect (the not-found
collapse protects rows, not the catalogue). Sockets: the bearer socket narrows **per frame** in the bridge — a frame is pushed only if
the ceiling holds `read` on some family of the app that declared the event
(the event name's `<app>` segment, a declared population), the kick group
untouched because a kick is an instruction to hang up, never a payload.
**(5) Compat and the default.** `ApiToken.scopes` lands expand-only (rule
22): a nullable JSON list where **NULL means unscoped** — the full power of
the person, the grandfathered meaning of every pre-scopes row, forever
(expand-only cannot rewrite the meaning of existing rows; revocation is the
remedy for an old broad token). An **empty list is refused at mint** — a
token that can do nothing is a mistake, not a ceiling. For NEW mints the
recommendation — **flagged for owner ratification, with the alternatives
below** — is *required-explicit*: the mint doors (`POST /api/v1/tokens/` and
`manage.py issue_token --scope`) take a scope list with **no default**, and
`*` is the explicit spelling of "no ceiling", so a full-power token is a
choice somebody made out loud. This breaks the mint route's request shape,
a deliberate early break — the only cheap moment — and is
recorded as the E5 exception it is. **(6) Orthogonality, stated.** The tenant
pin (`ApiToken.tenant`), the `X-Org` hat, `visible_to`, `may_be_named` and
the policies are all untouched: pins and hats narrow *which rows*, scopes
narrow *which capability families*, roles and policies decide *whether the
person may* — three narrowings that compose by intersection and never
substitute for each other. Minting is not bounded by role on purpose:
evaluating "which families may this role reach" at mint time would be the
second truth, drifting from the live role the moment it changes — a ceiling
wider than the grant is harmless because the grant still decides. **(7) The
docs are derived** (rule 41's machinery): every operation's published
description carries its required scope, the mint operation documents the
vocabulary off the same discovery, and `llms.txt` tells an agent which
scopes to request per family — zero hand annotations anywhere. *Rejected*:
**policies.py action names as the vocabulary** (a second permission system by
construction — a scope `invoice.void` beside a policy `invoice.void` will be
assumed equivalent and will drift; and reads mostly have no action name, so
half the surface would derive nothing); **service names / rule 42's census**
(internal vocabulary on the wire — the plain-language ruling forbids it; a
service rename becomes a credential break); **per-operation scopes** (the
vocabulary scales with the route count, agents must request dozens, and a
new route lands outside every existing ceiling — family×verb keeps route
growth additive, E5's own shape); **app-label families** (the exact same
finding: internal taxonomy on the wire); **a third `admin` class** (not
derivable — hand classification of which writes are "admin" is the
enumeration this ADR forbids; the privileged surface is already its own
family where it matters, and the role underneath is the real guard);
**hiding out-of-scope tools** (Stripe's shape — see part 4); **default-full
minting** (the path of least resistance re-arms the exact hazard the ruling
names); **default-narrow minting** (some hand-chosen "safe" subset nobody
stated — a default that grants anything is worse than a refusal that demands
a choice); **mint-time role bounding** (part 6). trigger to revisit: the
MCP OAuth 2.1 upgrade (the vocabulary survives as OAuth scopes; the
transport changes); a product wanting per-object grants (that is
roles/policies territory, never scopes); noun-level socket narrowing when
one app's families diverge in sensitivity.
