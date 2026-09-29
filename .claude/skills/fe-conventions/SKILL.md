---
name: fe-conventions
description: >-
  Load before writing or changing anything under `frontend/` — every screen, every
  component, every client regeneration, every fix. It exists because agents emit
  plausible-but-wrong React and Next.js: a proxy that redirects the body away, an
  effect that runs twice, a hand-typed interface that quietly disagrees with the
  generated client, a page that renders perfectly and never hydrates. Each rule
  below shows the wrong form and the right one, at the versions the frontend pins.
  Do NOT use it to decide what gets built (that is the PM's), to decide the shape
  or write acceptance criteria (django-architect's client-layer section), to judge
  whether a rung is done (the field test's), or to write Python (django-conventions).
  It is how to write the client, not whether to.
---

# Frontend conventions for this repository

**A frontend rung's screens are not "met" on component tests alone.** That
sentence is first because it was paid for: five defects shipped on a tree with
574 passing component tests, and every one of them was invisible to the suite by
construction — jsdom has no proxy, no hydration, no double-mount against a real
network, and no origin model. The browser drive is part of the rung, not a
later stage (§8).

The second thing to know is what you are building. **The frontend is a CLIENT of
the REST door — the first external consumer this template ships. It is not a
sixth door.** Every door law in this house is phrased as *reaching services by
name*; all of them are vacuous over a browser bundle, and a category whose laws
are all vacuous for a member is the wrong category. The practical consequence is
the one that bites: **the client never resolves authority.** It carries the hat,
it never decides the hat.

**Before you write a line:** read the OpenAPI document the doors serve and the
generated client built from it. The wire contract is read, never guessed — the
exact analogue of `manage.py introspect` on the Python side, and for the same
reason.

**The four laws**, each stated where it lives and each with its honest
enforcement tier in §10:

1. **`SurfaceState` is a total function** — `loading | empty | error(E) |
   ready(T)`, all four authored (§3).
2. **HTTP vocabulary never appears above the client seam** (§4, Law 1).
3. **One door to the backend** (§4, Law 2).
4. **The generated client's types are used verbatim, never re-declared**
   (§4, Law 3).

Everything else in this file is a convention, a paid-for wrong form, or an
instrument.

---

## 1 · The stack, pinned

`frontend/package.json` exists, so **it is the authority** and this table
defers to it — a reader's index of the manifest, never a second pin. Where the
two disagree the manifest wins and the disagreement is a finding.

| Thing | Version | Why it is pinned here |
|---|---|---|
| Next.js | `16.3.3` | app router — routes are filesystem-discovered, which is this repo's discovery doctrine in JS |
| React / React DOM | `19.2.8` | StrictMode double-invokes effects in development; §6 is mostly about that |
| TypeScript | `5.9.3` | `tsc --noEmit` is a leg, not a suggestion |
| pnpm | `10.12.1` | `packageManager` field; the lockfile is the frontend's one serial artifact |
| Node | `26.4.0` (engines `^22.18 \|\| ^24 \|\| ^26`) | `frontend/.nvmrc` — the one interpreter the checkout is proven green on; a broken engines pin once shipped unnoticed for days |
| `openapi-typescript` | `7.9.1` | the generated client; regeneration is a deliberate rung |
| ESLint / `eslint-config-next` | `9.39.5` / `16.3.3` | `--max-warnings=0` |
| Vitest / jsdom | `4.1.11` / `30.0.1` | the component tier — necessary, never sufficient (§8) |
| `axe-core` | `4.13.0` | accessibility assertions inside component tests |
| `@testing-library/react` | `16.3.0` | the component tier's renderer — the tests assert what a user can reach, not what the tree contains |
| `@vitejs/plugin-react` | `6.1.1` | the JSX transform Vitest runs under; without it the component tier does not compile at all |
| `@types/react` / `@types/react-dom` | `19.2.8` / `19.2.4` | `tsc --noEmit` is only as true as these. They track the runtime packages and **need not equal them** — `@types/react-dom` trails `react-dom` here, which is normal and is not a version to "fix" |
| `@types/node` | `24.10.1` | the config files (`next.config.ts`, `vitest.config.ts`) and `frontend/scripts/` are typed against this, not against the interpreter in the row above |

**The browser driver is deliberately NOT in that table.** The rendered check
runs against a real browser and the runner is chosen per checkout — the
harness's own browser control when a human is attending, `puppeteer-core`
against the installed Chrome when nothing is. Naming a pinned dependency here
would be inventing an answer the tree does not have yet; naming both honest
options is the answer it does have.

**`engines` without `engine-strict` is a comment.** Put `engine-strict=true` in
`.npmrc` or pnpm warns and installs anyway — a broken engines pin has shipped
unnoticed for days on exactly that. `.nvmrc` names the one interpreter the
checkout is proven green on; `engines.node` is the floor, not the pin.

**Version pins are load-bearing in a way they are not on the Python side.** An
agent's training distribution is thick with React 17 and Next 12 patterns, and
every one of them still *compiles*. `getServerSideProps`, `pages/`,
`useEffect` cleanup rituals written for a world with no double-mount,
`next/router` — all plausible, all wrong here. When you are unsure whether an
API is current, read the installed package, not your memory.

---

## 2 · Layout and the import contract

```
frontend/
  package.json  pnpm-lock.yaml  .npmrc  .nvmrc  next.config.ts  tsconfig.json
  eslint.config.mjs  vitest.config.ts  vitest.setup.ts
  openapi.json               # the document of record, committed and deterministically exported
  src/
    app/                     # ROUTES. Filesystem-discovered; a route is never registered anywhere
    api/                     # THE CLIENT SEAM — the only place that knows the backend exists
      generated/             #   openapi-typescript output. Never hand-edited, never re-declared
      client.ts              #   the one request function; carries CSRF + Idempotency-Key + the hat
      refusals.ts            #   wire refusal -> SurfaceState. The mirror of config/api.py
    tokens/                  # L0 — names, values, and the ONE stylesheet a route may import
    primitives/              # L1 — no product nouns. A button knows nothing about deals
    components/              # L2 — product nouns; renders a SurfaceState; NEVER fetches
    screens/                 # L3 — ONE whole surface, total over its four states
      state.ts               #   SurfaceState and its runtime census, beside the layer it defines
    copy/                    # strings live in copy modules, not inline in JSX
  journeys/                  # journey specs + the acceptance ledger
```

**`primitives/` and `components/` are siblings, not a parent and two children,
and `screens/` is a layer of its own.** A screen is the unit a journey names and
a rung is dispatched against — one whole surface, total over `loading`, `empty`,
`error` and `ready` (§3) — and it is the layer the route hands state to. Both
`primitives/` and `components/` ship as a README and nothing else on purpose:
this template ships a *system*, not a look, and a component library shipped from
here would be taste exported into every product built on it. The one screen in
the tree (`src/screens/welcome/`) is a worked example, not a library — **a
component becomes a component the day a second screen needs it.**

**This is house rule 11 in JavaScript.** A `utils.ts`, `helpers.ts` or `lib.ts`
doing a canonical job is a violation exactly as it is in `apps/`: if it fetches
it belongs in `src/api/`, if it renders it belongs in `primitives/`,
`components/` or `screens/` by what it knows, if it is a string it belongs in
`copy/`.

**A route fetches and hands state down; only a component paints.** This is the
ingredient boundary, and it is the sharpest single line in the taxonomy because
it is checkable. Three violations, all of them things an agent reaches for when
a component it needs does not exist:

```tsx
// wrong — three ways a route invents an ingredient
<div style={{ display: "flex", gap: 8 }}>          // V1: an inline style
import "./deals.css";                               // V2: a stylesheet that is not the token entrance
<div className="deal-row">                          // V3: a class on a HOST element

// right — the route hands the state to a screen; the paint lives below it
<DealsScreen state={state} />                       // in src/app/deals/page.tsx
<Stack gap="sm"><DealCard deal={deal} /></Stack>    // inside the screen
<Card className="…">                                // legal: className is a PUBLISHED prop of Card
```

A missing component is not a licence to inline one; it **stops the rung** (§5).

**Imports flow one way, and it is house rule 7's shape. The chain is declared
ONCE, in `frontend/src/primitives/README.md`** — beside the layer it starts
from, where a builder filling that directory cannot miss it. Read it there.
This file does not carry a second copy of the arrows, because two authorities
for one contract is two things to drift; what this section adds is the
reasoning the declaration does not carry:

- **The `api ← app(routes)` arrow is the whole of §4's law.** The route
  fetches; nothing below it does. A screen or component that imports `api`
  cannot be rendered in every state on demand, and every story of it needs a
  network — which is what makes the four states unauditable.
- **Each layer's ceiling is what it must not know, not what it happens to
  need.** A primitive that imports a component has become a component; a
  component that imports a screen has become a screen. The arrow is the claim
  about knowledge, and the directory is where the claim is kept honest.
- **A route never imports another route.** Cross-surface sharing is a screen, a
  component or a copy module; one route reaching into another is the JS form of
  two apps importing each other sideways.

**Barrel files are banned.** An `index.ts` that re-exports a directory is the
`INSTALLED_APPS` of JavaScript: one shared file every parallel rung must edit,
so every parallel rung collides in it. Import from the module that defines the
thing. This is the single change that makes frontend rungs fan out at all — the
alternative, and the reason a sibling product adopted it, is serializing the
whole surface by decree.

```ts
// wrong — the collision file. Two rungs adding two components edit one line region.
import { DealCard, StageBadge } from "@/components";

// right — each import names the module that defines it
import { DealCard } from "@/components/deal-card";
import { StageBadge } from "@/components/stage-badge";
```

**A single door file is the other way to draw this boundary, and it is
rejected here on purpose.** A `components/index.ts` that every route knocks on
makes the boundary trivially checkable — and makes every component-adding rung
edit one file, which is precisely the collision that forces a whole frontend to
be built serially. The boundary above is the same boundary, drawn by the import
contract instead of by a shared file. Parallelism is why.

---

## 3 · SurfaceState — the total function

**A screen is a total function from state to render.** Not a screen until all
four states are authored:

```ts
// src/screens/state.ts
import type { Refusal } from "@/api/refusals";

/** What an empty state PROPOSES. The label is the act, in the imperative. */
export type NextAct = { readonly label: string; readonly detail?: string };

export type SurfaceState<TData> =
  | { readonly kind: "loading" }
  | { readonly kind: "empty"; readonly nextAct: NextAct }
  | { readonly kind: "error"; readonly refusal: Refusal }
  | { readonly kind: "ready"; readonly data: TData };

/** The runtime census the instruments read. */
export const SURFACE_STATES = ["loading", "empty", "error", "ready"] as const;
export type SurfaceStateKind = (typeof SURFACE_STATES)[number];

/** The four story exports every component story owes, declared BESIDE the states
 *  so a lint, a story and a component cannot disagree about what the four are. */
export const REQUIRED_STORY_EXPORTS = ["Loading", "Empty", "Error", "Ready"] as const;

/** Exhaustiveness, as a compile error rather than as a habit. */
export function unhandledState(state: never): never {
  throw new Error(`unhandled SurfaceState: ${JSON.stringify(state)}`);
}
```

```tsx
// wrong — three booleans, four-plus reachable combinations, and no fourth branch
function DealList({ data, isLoading, error }: Props) {
  if (isLoading) return <Skeleton />;
  if (error) return <p>Something went wrong</p>;      // and now a made-up sentence
  return <ul>{data.map(...)}</ul>;                    // data is [] here and renders nothing at all
}

// right — a discriminated union; the missing branch is a COMPILE error, and the
// error branch renders the server's own words instead of inventing any
function DealList({ state }: { state: SurfaceState<Deal[]> }) {
  switch (state.kind) {
    case "loading": return <DealListSkeleton />;
    case "empty":   return <NextActPrompt act={state.nextAct} />;
    case "error":   return <RefusalPanel refusal={state.refusal} />;
    case "ready":   return <ul>{state.data.map((d) => <DealCard key={d.id} deal={d} />)}</ul>;
  }
}
```

Three things this buys, each of which was bought the expensive way:

- **The never-hydrated page becomes a designed `loading` render** instead of
  nothing. A page whose only "not ready yet" state is *absence* cannot tell you
  it is broken.
- **`error` carries a structured `Refusal`, never a string.** A component
  holding a refusal can render the registry's own fact and its structured
  remedies; a component holding a string can only make a sentence up, and it
  will. This is the client half of the refusal grammar `core.exceptions`
  already owns.
- **`empty` proposes the next act.** An empty state that only reports emptiness
  has told the person something they could already see.

**Transport failure is not a refusal, and it must not escape as one.** A dead
origin, a CORS block or an aborted connection throws *before any response
exists* — there is no code, no fact, no remedies, and the refusal registry is
the wrong authority for it by construction.

**`error` is not a state that holds only a registry refusal. It is a state that
holds one of TWO things, and the union is closed:**

```ts
/** The two — and only two — things that can put a surface in `error`. */
export type Refusal =
  | { readonly kind: "registry"; readonly code: RegistryRefusalCode; /* fact, remedies */ }
  | { readonly kind: "transport"; readonly code: TransportFailureCode };

/** Read from the operation's x-refusal-codes union. Never hand-listed. */
export type RegistryRefusalCode = /* generated */ string;

/** The client's OWN closed vocabulary. Two members. It has no other home. */
export type TransportFailureCode = "network_unreachable" | "request_timeout";
```

- **The client seam catches the throw and returns a `transport` refusal.** Both
  members are rendered by the one default refusal renderer, exactly as a
  registry refusal is — the screen's `error` branch does not grow a second
  shape.
- **Never synthesise a registry code for a transport failure.** A made-up code
  in registry clothing fails *open*: it will not be in any operation's refusal
  union, so the completeness census cannot see it, and the screen renders a
  fact the server never said. That is the same class as an unset custom
  property resolving to the browser's default — a value that looks handled and
  is not.
- **Never let it reject unhandled.** That is §6's eighth pair, and it renders an
  eternal skeleton.

> **Ruled 2026-08-31 by the engineering lead, and closed: there is NO fifth
> `SurfaceState`.** The four-state law stands, and transport failure joins
> `error`'s input vocabulary rather than the state list. Two reasons, both
> structural. A fifth kind would **retroactively unfinish every surface that
> has already answered the four-state question** — every story-completeness
> floor in the tree would go from met to short by one, for a population most of
> those screens cannot even encounter. And the **four states are a closed
> question a screen answers once**; the things that can go wrong are an open
> population, and open populations belong in a *vocabulary*, where they can
> grow without moving the floor.

---

## 4 · The client seam

Four laws hold here: three of the file's four (numbers 2, 3 and 4 of the list
above), plus one more the seam needs in order for the other three to be
testable. They are laws, not preferences. §10 states honestly what enforces
each one today.

### Law 1 · HTTP vocabulary never appears above the client seam

The analogue of house rule 14, and the sharpest of the four. Below the seam
(`src/api/`) there are status codes, headers and response objects. Above it
there are refusals, states and remedies — and nothing else.

```tsx
// wrong — a screen switching on transport facts. This is rule 14 upside down.
const res = await fetch(`/api/v1/deals/${id}/`);
if (res.status === 404) return <p>Not found</p>;
if (res.status === 403) return <p>You do not have access</p>;
if (!res.ok) throw new Error(`HTTP ${res.status}`);

// right — the seam maps the wire to a refusal; the screen branches on the CODE
// and renders what the server said, exactly as the mapper in config/api.py does
// in the other direction
const result = await getDeal({ id });
if (result.kind === "refused") {
  return <RefusalPanel refusal={result.refusal} />;   // code, fact and remedies, all the server's
}
```

`src/api/refusals.ts` is the one mapper, and it is the mirror of
`config/api.py`. One module knows that a 404 is `not_found`; nothing else in
the tree may learn it.

### Law 2 · One door to the backend

The fourth member of the fence family that already holds rules 27, 33 and 48
(one door to the identity platform, to the search index, to the object store).
**No module outside `src/api/` names the backend origin or calls `fetch` at an
API path.** Not a component, not a route, not a test helper, not a "quick"
server action.

```ts
// wrong — a second door. It will not carry CSRF, will not carry the hat, and
// the drift pin's sentence about the generated client stops being true.
const rows = await fetch("http://localhost:8000/api/v1/deals/").then((r) => r.json());

// right — through the seam, which is the only place that knows an origin exists
import { listDeals } from "@/api/client";
const rows = await listDeals({ page: 1 });
```

The reason is the same reason rule 27 exists: a second door does not fail
loudly, it works — until the day it needs the header nobody remembered to add
there.

**One mutation wrapper.** Every write goes through it, and it carries three
things every time, so that no call site can forget one: the **CSRF token**, an
**`Idempotency-Key`**, and the **acting hat (`X-Org`)**. Each has a detail that
costs a debugging session to rediscover:

- **Make the poisoned pair unspellable, not forbidden.** A safe request and an
  unsafe request are *different types*, and the token and the idempotency key
  exist only on the unsafe one; the token is a *branded* type that only the
  bootstrap can produce. "An unsafe request with no token" then stops being a
  runtime check and becomes a value TypeScript cannot construct. The wrapper
  also refuses **before** any header or body work — a half-built request that
  is later discarded is a thing a refactor can accidentally send.
- **The key is minted per INTENT, not per attempt.** Re-rendering, retrying or
  double-clicking must reuse the key; a new intent mints a new one. Use
  `crypto.randomUUID()`, and if you need a fallback for a non-secure context
  make it **random, never a counter** — two tabs sharing a counter collide on
  exactly the key that must not collide. Surface the `idempotent-replayed`
  response header in developer tooling and **never act on it**: a screen that
  makes a fuss about a replay is arguing with the mechanism that just protected
  it.
- **`X-Org` is a parameter of every operation, not session state.** Type it so
  a screen that forgets the hat fails to compile rather than silently getting
  the default one. And **omit the header entirely on the default hat — never
  send it empty.** An empty or whitespace-only value counts as *sent* and is
  refused: `X-Org: ""` is a 403, not a shrug.

The hat travels; the client never decides it — the server revalidates it on
every request, and a client that "knows" its own hat has just resolved
authority.

> **The one piece that is not the frontend's, and it will be your first 403.**
> Behind the proxy the browser's `Origin` is the *client's* origin while
> Django's host is its own, so Django refuses **every write** with
> `page_token_missing` until that origin is in **`CSRF_TRUSTED_ORIGINS`**.
> Proven both directions on a real drive: 403 without it, 201 with it. Naming
> one browser origin on the client side is not enough — the *server* has to be
> told which origin that is, and the `.env` recipe is where it goes. Sign-in
> also **rotates the CSRF secret**, so the token is re-fetched after sign-in;
> a wrapper that fetches it once at boot works until somebody logs in.

### Law 3 · The generated client's types are used verbatim, never re-declared

House rule 16's naming grammar, pointed outward. The generated types are the
document, and the document is the contract.

```ts
// wrong — a hand-typed interface beside the generated one. Nothing fails today.
interface Deal { id: string; name: string; stage: string; amount: number }

// wrong, and worse — casting past the generated type because it disagreed with
// what you wanted to send
await createDeal({ body: { name, stage } as unknown as CreateDealBody });

// right — the generated type IS the shape
import type { components } from "@/api/generated/schema";
type Deal = components["schemas"]["DealOut"];
```

**When the document and your intent diverge, send what the server would have
defaulted — do not cast.** An `as` past the generated type is how a client
starts disagreeing with the document one field at a time, and the disagreement
surfaces later as a 422 raised a long way from the interface that lied. If the
document is genuinely wrong, that is a backend rung, not a cast.

The generator's own asymmetry is where this bites first: **a property carrying
a `default` is typed as always-present**, which is right for a *response* and
wrong for a *request*. The temptation is to cast the request body. Send the
value the server would have defaulted to instead:

```ts
// wrong — casting the body because the generated request type demands a field
await logActivity({ body: { dealId } as ActivityIn });

// right — send what the default would have been
await logActivity({ body: { dealId, note: intent.note ?? "" } });
```

Client regeneration is a **deliberate rung**, and a serial one (§9).

### Law 4 · Components render; they never fetch

House rule 12's split (`selectors.py` never writes; `services.py` never returns
a queryset for display), translated: **a screen or a component takes a
`SurfaceState<T>` and returns markup.** Fetching lives at the route, which
hands the state down.

```tsx
// wrong — the component owns a request, so it cannot be rendered in any state
// on demand, and every story of it needs a network
function DealList() {
  const [deals, setDeals] = useState<Deal[] | null>(null);
  useEffect(() => { listDeals().then(setDeals); }, []);
  return deals ? <ul>{...}</ul> : <Skeleton />;
}

// right — the route fetches, the component renders the state it is handed
export default async function DealsPage() {
  const state = await loadDeals();          // returns SurfaceState<Deal[]>
  return <DealList state={state} />;
}
```

---

## 5 · Copy, tokens and the taste fence

- **Strings live in copy modules**, not inline in JSX. A screen's words are
  reviewable as words when they sit together, and untranslatable when they do
  not.
- **A token has a consumer.** A declared token nothing reads is a
  reader-less declaration — the same class the Python side already refuses. The
  reverse is worse and fails *open*: a `var(--accent-loud)` nobody declared
  resolves to nothing at all, and an unset `accent-color` renders as the
  browser's default blue, which no static check can see. Both directions are a
  set-equality question, and the runtime half of it needs a rendered page (§8).
- **The template styles only surfaces whose WORDS it also owns** — the entrance
  chain, refusal pages, the placeholder landing. The moment it styles a surface
  whose content a product authors, it has shipped taste. Product screens carry
  no template look.
- **You do not make visual judgments.** An agent asked to fill a visual gap
  fills it *plausibly*, which is the documented failure mode wearing CSS. A
  missing ingredient — a token, a component, a designed state — **stops the
  rung**; it is not an invitation to improvise one. Design ships production
  fidelity; the builder implements it.

---

## 6 · The wrong forms, and where each was paid for

**Every pair below carries its provenance, and there are exactly two kinds of
it.** Most are defects that *shipped*, in a product built on this template, and
were found by a browser rather than by a test: the incident record is that
product's repository at commit `e55764c`, the fixes and their arguments landed
in `45c0113` ("the browser drive, and the five bugs only it could find") and
`b47a787`, and each such pair cites the file that carries the argument in
place. Two pairs (§6.8, §6.9) are instead **still-open classes on that
product's own ledger** — real, named, and without a fix commit — and they say so
on their own line rather than borrowing a citation.

**Nothing here is invented, and nothing here should be — a fabricated failure
example is exactly the defect this section exists to teach against.** Where the
record does not support a claim, the pair says so rather than rounding it off.

### 6.1 · The 308 that ate the request

*Paid for at `frontend/next.config.ts:90-106`.*

Next's default `trailingSlash: false` answers `/api/v1/deals/` with a **308
before any rewrite runs**. Django's resource paths all end in a slash, so every
proxied call became a redirect pair — and a browser following that redirect
drops the method and the body.

```ts
// wrong — the default, which is the dangerous value
const nextConfig: NextConfig = { /* trailingSlash left at its default */ };

// right — and pinned by a topology test, precisely BECAUSE the default is the
// dangerous one and a silent revert looks like nothing
const nextConfig: NextConfig = { skipTrailingSlashRedirect: true };
```

**Symptom:** the whole API unreachable through the proxy while `curl` showed
only `308` — nothing that looked like a failure anywhere.

### 6.2 · The rewrite that ate the slash

*Paid for at `frontend/next.config.ts:131-148`.*

The segment form `:path*` splits the path on `/` and rejoins it, which silently
drops a trailing empty segment. `/api/v1/deals/` arrives at Django as
`/api/v1/deals`, and django-ninja answers with its own `404 not_found`.

```ts
// wrong — `:path*` normalises the trailing slash away on its way through
async rewrites() {
  return [{ source: `${prefix}/:path*`, destination: `${DJANGO_ORIGIN}${prefix}/:path` }];
}

// right — the regex form captures the rest of the path verbatim, slash included
async rewrites() {
  return [{ source: `${prefix}/:path(.*)`, destination: `${DJANGO_ORIGIN}${prefix}/:path` }];
}
```

**Symptom:** every list endpoint 404 through the proxy while Django served the
identical path happily on its own port — so the evidence pointed at the backend,
which was innocent. Found by the browser drive **twice**: once as a 308, and
then, after that was fixed, as this.

> The wrong form above is a reconstruction from the fix's own argument, not a
> quotation: the rewrites block landed already-corrected, so no diff carries
> the broken line. The mechanism and the symptom are the record's; the exact
> characters of the losing spelling are inferred from it.

### 6.3 · The StrictMode pair — the bootstrap that ran twice

*Paid for at `frontend/porchlight.tsx:259-302`.*

React 19 StrictMode mounts effects **twice** in development, and this repo sets
`reactStrictMode: true`. An unguarded bootstrap effect therefore does its
one-time work twice — session establishment minting two page tokens is the
instance the guard below was written for.

```tsx
// wrong — establishing a session is not idempotent, and this establishes twice
useEffect(() => { establish(); }, []);

// right — a ref one-shot. Establishing is an event in the SESSION's life,
// not in a render's.
const established = useRef(false);
useEffect(() => {
  if (established.current) return;
  established.current = true;
  establish();
}, []);
```

*The guard was already in place by the time the drive ran; §6.4 is what the
drive found sitting on top of it. The pair is here because the guard is only
correct with §6.4's second half, and an agent that writes one without the other
has reproduced the incident.*

### 6.4 · The StrictMode pair — the cleanup that discarded the answer

*Paid for at `frontend/porchlight.tsx:259-302`. This is the fatal combination,
and both halves are individually idiomatic.*

```tsx
// wrong — the customary live-flag cleanup ON TOP of the ref guard.
// Pass 1 starts the work and is then cleaned up (live = false).
// Pass 2 sees the ref and starts nothing.
// Pass 1's answer arrives, sees live === false, and throws itself away.
const established = useRef(false);
useEffect(() => {
  if (established.current) return;
  established.current = true;
  let live = true;
  establish().then((s) => { if (live) setSession(s); });
  return () => { live = false; };
}, []);

// right — a ref-guarded one-shot gets NO live flag. There is no second run to
// race, and setting state after unmount is a no-op in React 18+.
const established = useRef(false);
useEffect(() => {
  if (established.current) return;
  established.current = true;
  establish().then(setSession);
}, []);
```

**Symptom:** the request went out, came back 200, and the hat switcher sat on a
skeleton for ever. **The cleanup ritual is correct for effects that legitimately
re-run; on a one-shot it is the bug.** Ask which kind you have before you write
the return statement — and keep the flag where it belongs:

```tsx
// right, the OTHER case — an effect keyed on the hat DOES re-run, so it DOES
// keep the flag. The flag belongs to an effect that re-runs, never to a one-shot.
useEffect(() => {
  let live = true;
  loadRoster(org).then((r) => { if (live) setRoster(r); });
  return () => { live = false; };
}, [org]);
```

### 6.5 · The cache hit read once, in the wrong place

*Paid for at `frontend/use-read.ts:68-129`.*

The state was seeded from the cache with `useState(initial)` — which reads the
cache **once**, at first render. The cache entry is written by the effect
*after* that render. So on the next render the cache had the value, the effect
took its early return, `setState` was never called, and the surface sat on a
skeleton **over data it already held**. StrictMode's double-invoke is what
closed the loop: pass 1 writes the cache and is cancelled by its own live flag;
pass 2 early-returns on the cache hit.

```ts
// wrong — a cache hit seeded into state once, and an effect that skips when the
// cache is warm. jsdom never saw it: the harness renders once and settles.
const initial = () => {
  const hit = cache.read<U>(key, org);
  return hit === undefined ? { kind: "loading" } : { kind: "ready", data: hit };
};
const [state, setState] = useState<SurfaceState<U>>(initial);
useEffect(() => { if (cache.has(key, org)) return; /* fetch and setState */ }, [identity]);
return state;

// right — a cache hit is DERIVED state: a pure function of the cache, the key
// and the hat. So it is computed in the render body, on every render.
const hit = cache.has(key, org) ? cache.read<U>(key, org) : undefined;
const [fetched, setFetched] = useState<SurfaceState<U>>({ kind: "loading" });
useEffect(() => { /* fetch and setFetched */ }, [identity]);
return hit === undefined ? fetched : { kind: "ready", data: hit };
```

**Symptom:** an eternal skeleton over data already in memory — and the general
form is worth more than the instance. **Anything derivable from props, state or
a store is computed during render, never copied into state by an effect.**
Reading it in an effect and calling `setState` is also the cascading-render
pattern React now lints against.

### 6.6 · The page that rendered perfectly and never hydrated

*Paid for at `frontend/next.config.ts:118-129`. The nastiest of the five.*

The page is served through the proxy on a different origin than `next dev`
itself. With `allowedDevOrigins` unset, the development server refuses the
hydration assets — and refuses them *quietly*.

```ts
// wrong — unset, which is the default
const nextConfig: NextConfig = { /* no allowedDevOrigins */ };

// right — BOTH spellings, because to a browser they are different origins
const nextConfig: NextConfig = { allowedDevOrigins: ["127.0.0.1", "localhost"] };
```

**Symptom:** the page server-renders perfectly and never hydrates. No console
error. No failed request. Nothing clickable works and nothing says why. **The
only trace was a DOM carrying no React fiber** — which is why the rendered
check (§8) asserts hydration *completed*, rather than asserting that the page
looks right.

> **Honest about the instrument:** the fiber observation was made by hand
> during the drive, and the regression guard that shipped asserts the *config
> line*, not hydration. Nobody has yet built the probe that would have caught
> this without a person looking. That is the gap §8's first assertion exists to
> close, and it is a gap, not a solved problem.

### 6.7 · The hand-typed interface that shadowed the generated type

*Paid for at `frontend/metric-with-receipt.tsx` and `frontend/story-fixtures.ts`
(commit `b47a787`); the surviving rule is at `frontend/operations.ts:295-311`.*

A component hand-wrote a nested wire shape from memory as `{ label, href }`.
The document's actual shape has no `label` at all — the field is `input`. So
every source link on the surface rendered its words as `undefined`.

```ts
// wrong — the shape, retyped from memory beside the generated one
type BasisExtras = {
  readonly sources?: readonly { readonly label: string; readonly href: string }[];
};
<a href={source.href}>{source.label}</a>          // renders "undefined"

// right — name the generated type once, in the seam, and use it
export type MeasuredSource = components["schemas"]["MeasuredSourceOut"];
// …
<a href={source.href}>{source.input}</a>
```

**Two things hid it, and both are the lesson:**

1. **The story fixture had been hand-written to the same wrong shape**, so the
   test agreed with the bug. **Type fixtures against the generated shape, never
   against the thing that reads them** — a fixture typed from the component is
   a mirror, and a mirror confirms whatever it is shown.
2. **The lint could not see it.** A rule that finds hand-written wire types
   keys on the schema suffix grammar (`…Out`, `…In`, `…Page`), and this type
   was called `BasisExtras`. That is the rule's *declared blind spot*, working
   exactly as declared — which is why the enforcement register (§10) puts
   hand-typed shadows at review-tier and does not claim a lint catches them.

A useful shape-agnostic net, worth writing once: **assert that no rendered
output contains the literal `undefined`.** It costs nothing and catches the
next one whatever field it reaches for.

**Symptom: none, at first — that is the trap.** A hand-typed interface agrees
with the document on the day it is written. The drift arrives later, as a 422
or a rendered `undefined` a long way from the interface that lied.

### 6.8 · The thrown fetch nobody caught

*The general form, not a shipped incident: recorded as a still-open class on
the sibling product's own ledger in the intake of 2026-08-31. There is no fix
commit behind this pair, so none is cited.*

A refusal policy that renders registry refusals **and nothing else** has no
branch for the failure that happens before a response exists. **A thrown fetch
that escapes the client seam is the wrong form** — wherever it escapes to.

```ts
// wrong — a rejected promise with no handler. The screen shimmers for ever.
const result = await client.GET("/api/v1/deals/");
if (result.error) return refused(result.error);
return ready(result.data);

// wrong the other way — caught, but dressed as a registry code. It is in no
// operation's refusal union, so the completeness census cannot see it and the
// screen renders a fact the server never said (§3).
catch (cause) { return refused({ kind: "registry", code: "not_found" }); }

// right — caught at the ONE client seam, turned into a TransportFailure, and
// reaching the screen as error(E) like any other refusal (§3)
try {
  const result = await client.GET("/api/v1/deals/");
  return result.error ? refused(registryRefusal(result.error)) : ready(result.data);
} catch (cause) {
  return refused(transportFailure(cause));   // network_unreachable | request_timeout
}
```

**Symptom:** an eternal skeleton, plus `unhandledRejection: TypeError: Failed to
fetch` in a console nobody was watching.

### 6.9 · The write button that disabled itself for ever

*The general form, not a shipped incident: the second of the two still-open
classes on the sibling product's ledger, from the same 2026-08-31 intake. No
fix commit behind it, and none invented.*

```tsx
// wrong — the flag is set, the await is not guarded, and nothing ever clears it
async function onSubmit() {
  setSubmitting(true);
  await createDeal({ body });
  setSubmitting(false);          // never reached on a rejection
}

// right — every write path owns its rejection, and the button comes back
async function onSubmit() {
  setSubmitting(true);
  try {
    const result = await createDeal({ body });
    if (result.kind === "refused") setState(errorFrom(result.refusal));
  } catch (cause) {
    setState(errorFrom(transportFailure(cause)));
  } finally {
    setSubmitting(false);
  }
}
```

**Symptom:** the button disables itself for ever, silently. No error state, no
console output, and a person who concludes the app is broken and reloads.

---

## 7 · No frontend workflows. By law.

Rules 9 and 28 already say that anything which waits or retries is a workflow,
that workflow code is deterministic, and that a workflow closes its run row.
None of that can hold in a browser: a tab is not durable, a client cannot be
made deterministic, and a run row a client owns is a run row that vanishes when
somebody closes a laptop.

```ts
// wrong — a retry loop in a component. This is a workflow wearing a hook.
useEffect(() => {
  const t = setInterval(() => { retryImport(); }, 5000);
  return () => clearInterval(t);
}, []);

// right — the backend starts the workflow; the SCREEN POLLS THE RUN ROW and
// renders its states. Waiting is the workflow's job; showing is the screen's.
const state = await loadImportRun({ runId });     // SurfaceState<ImportRun>
```

Polling a run row is not a workflow — it is a read with an interval, and it
renders `loading` while the row is unfinished. The distinction that matters: the
**work** must survive the tab closing, and only the server side can promise
that.

There is also no sender here, ever. Rule 25's `comms.send()` is the only legal
sender in this system, consent and quiet hours are enforced inside it, and a
browser cannot reach it. A client that mails anything has gone around every
suppression rule the platform owns.

---

## 8 · The browser drive is your eyes

**An agent cannot see its own frontend work.** A backend agent's artifacts are
fully self-inspectable — test output, querysets, wire bodies. A frontend
agent's actual output is pixels, and its default instruments are exactly the
ones that let a rendered-but-never-hydrated page ship under 574 green tests.

So the rendered check is not a QA nicety appended at the end. **It is the
perception substrate, and it belongs inside the rung's own gate.** Three
assertions, on every route the rung touched:

1. **Hydration completed.** Not "the page rendered" — the DOM carries a React
   root and an interaction actually does something. §6.6 is why: a page can
   render byte-perfect and be inert.
2. **The console is clean.** Zero errors, zero unhandled rejections. §6.8 and
   §6.9 both announced themselves here and nowhere else.
3. **Computed styles resolve.** Declared fonts report as loaded, no control
   wears the user-agent default (`rgb(0, 0, 238)`, an unset `accent-color`), no
   `var()` resolves to nothing. This is the only instrument that can see a
   token declared, consumed and still invisible.

**The drive runs twice, and the second run is not a formality.** Once in the
builder's own gate, where it is the only way the builder perceives what it
made; and again at PROVE, by somebody who did not build it — because whoever
builds never decides done, and a drive written by the author can be vacuous in
ways only a second pair of eyes over the seeded world will notice. A frontend
rung that reaches verification without a drive of its own has handed the
verifier a surface nobody has looked at, which is the one thing the stage
cannot fix cheaply.

**Two disciplines that make a drive honest**, both learned from drives that were
not:

- **State, per criterion, what in the seeded world made it non-vacuous.** Four
  of six criteria in one drive were vacuous as seeded, and only reading the
  assertion bodies revealed it. A drive over an empty database proves that empty
  databases render.
- **A negative observation from a bespoke harness is a hypothesis until a second
  instrument agrees.** "The control fires no request" nearly became a filed
  defect when the harness's own polling was what missed it. Confirm a negative
  before you report one.

### The screenshot report contract

**The report's SHAPE is not this file's.** `rung-execution`'s report contract
owns it for every rung here — branch and shas, red-first evidence,
per-criterion status with artifacts, deviations, disproved claims, blind spots,
lexicon delta, cleanup census — and a frontend rung owes all of it unchanged.
Read it there; it is not restated here, so it cannot drift from here. What
follows is only **what the drive adds** to that shape: the coverage floor, the
instrument output, and the caption that makes an image evidence rather than
decoration.

A screen's "done" names its artifact, and the artifact a human verifies in two
seconds is a picture. For every route a frontend rung touched, the report
carries:

- **A screenshot per authored `SurfaceState`** — `loading`, `empty`, `error`,
  `ready` — each labelled with the route and the state, and each saying what in
  the seeded world produced it. Four states authored and one screenshotted is
  one state proven.
- **The console transcript** for the drive, pasted, not characterised.
- **The hydration assertion's own output**, pasted.
- **Before and after**, where the rung changed an existing screen. "Screen
  red-first" for a frontend rung means the state or route was absent, or was
  rendering the undesigned default, **shown by the rendered check** — never
  described in prose.

Screenshots are also what makes owner acceptance cheap: a journey is accepted
from rendered evidence, never from a description of rendered evidence.

---

## 9 · Parallelism, and the three populations that do not fan out

Frontend rungs fan out — routes are filesystem-discovered so two rungs adding
two routes never touch a shared file, barrels are banned (§2), and ports and
build directories derive per checkout exactly as databases do. That is the
default and it is worth defending.

**Three populations do not fan out, and every fan-out must name all three.**
They do not fan out in the same way, and the difference is the whole of what a
dispatch needs to know:

- **(2) and (3) are SERIAL — serial with respect to each other.** Two rungs in
  the same population never run at once, and the rest of the wave proceeds
  beside them. A dispatch batches these; it does not queue the wave behind
  them.
- **(1) is EXCLUSIVE, which is stronger: it DOES hold the wave.** A lockfile
  rung runs with nothing else running at all — that is what exclusive means
  here, and why it is listed first.

1. **Dependency rungs are exclusive.** `pnpm-lock.yaml` is the frontend's
   `max_migration.txt`, and it is worse: it conflicts **dirtily**. Two branches
   can produce a textually clean merge that no longer satisfies either
   `package.json`, and nothing says so until `--frozen-lockfile` runs. Any rung
   touching `package.json` or the lockfile runs alone — the analogue of
   `makemigrations --merge` being forbidden, and for the identical reason.
2. **Client regeneration is serial.** Regenerating from a moved document is the
   migration shape: two rungs regenerating against two different documents
   produce a client that matches neither.
3. **Frozen-layer edits BATCH — one rung at a time against a given layer.** The
   root layout, providers, middleware, `next.config.ts` and the token file are
   the frontend's `core` — they freeze, and a rung that must change one says so
   up front and takes that layer alone while the rest of the wave runs beside
   it.

**A stale environment is a false red, and it costs a triage every time.** Before
you believe a red from the component suite on a merged tree: regenerate the
client from the current document and run `pnpm install --frozen-lockfile`. Two
of the three populations above announce themselves this way and only this way.

**One more serialization, inside the test runner.** A suite that plants files
into the real tree — a lint canary, a boundary fixture — cannot run beside
another suite doing the same thing; they see each other's plants. Turn file
parallelism **off** in that runner and say in the config that it is a
correctness setting, not a performance one, or the next person will turn it
back on for the speed.

---

## 10 · What actually enforces each law today

**Stated honestly, because a law claiming an enforcement it does not have is
worse than a law that admits it is on review.** Read this table before you cite
a rule at somebody.

| Law | Tier today | What raises it |
|---|---|---|
| SurfaceState is a total function (§3) | **compiler-tier for components** — a missing branch on the discriminated union is a `tsc` error; **review-tier** for whether all four are authored and reachable | the state/story completeness rule, when the JS scope kind and its rule library land |
| HTTP vocabulary never above the seam (§4, Law 1) | **review-tier** | a static rule over `src/` outside `src/api/` — the direct analogue of rule 14's check, once a JS rule can be declared |
| One door to the backend (§4, Law 2) | **review-tier** | the fourth member of the 27/33/48 fence family, same shape, same check, once a JS rule can be declared |
| Generated types verbatim (§4, Law 3) | **partly mechanical** — a byte-pin comparing the generated client against the current document makes *drift* loud; **review-tier** for hand-typed shadows and `as` casts | a shadow rule in the JS rule library — and note it will key on the schema suffix grammar, so a shadow named anything else stays review-tier by declaration (§6.7) |
| Components render, never fetch (§4, Law 4) | **review-tier** | the ingredient-boundary import rule |
| No barrels (§2) | **review-tier** | the no-barrel rule |
| Import contract (§2) | **review-tier** | the ingredient-boundary rule; rule 7's shape in JS |
| A token has a consumer (§5) | **review-tier** | the token-consumer census (static half) plus the computed-style census (runtime half) |
| Error-state completeness (§3, §4) | **review-tier** | the refusal-union census: every screen names a handling or an explicit delegation, for every code in the refusal union of the operations it calls, the union read from the document's refusal codes and never hand-listed. Its declared blind spot is the **transport** half of `error`'s vocabulary — those two codes are outside the registry by construction, so the census cannot reach them and a separate sentence owns them (§3) |
| Hydration, clean console, resolved styles (§8) | **criterion-tier** — the rung's own criteria and its report | the rendered check as a gate leg, once the drive's cost and determinism are measured |
| Dependency/regen/frozen-layer serialization (§9) | **review-tier**, plus a frozen-lockfile install that fails loudly | a lockfile leg in the gate |
| No frontend workflows (§7) | **review-tier** | it is a categorical law; the cheap tooth is a rule against timers that retry |

**None of this is a reason to write the wrong form.** Review-tier means a
person catches it, and the person is reading this file.

**When one of these does become a rule, it arrives with the same equipment
every rule here carries: canaries that must fire through the real scope, silent
negatives, and a written `does_not_cover`.** §6.7 is the argument — that rule's
declared blind spot is exactly where the defect walked through, and the blind
spot being *declared* is why the miss was legible afterwards instead of being a
surprise about a rule everyone thought was total.

---

## 11 · What does NOT transfer from the backend rules

Cargo-culting the Python house rules into the client produces ceremony that
protects nothing, which is how a convention set loses its authority. **These do
not apply here, and the reason each is vacuous is the point:**

| Rule | Why it is vacuous in the client |
|---|---|
| 1 · `auth.User` never imported | no ORM, no Django models |
| 2 · concrete models inherit `BaseModel` | no models |
| 6 · one migration leaf per app | no migrations. The lockfile is the analogous serial artifact (§9) |
| 8 · scoped reads go through `for_tenant(...)` | scoping is server-side and non-negotiable; a client "scoping" a read is a client resolving authority |
| 15 · field policies | no fields. Money and quantity arrive already typed by the generated client |
| 18 · deterministic workflow ids | no workflows (§7) |
| 20 · append-only is a declared population | no rows |
| 21 · admin inherits `ServiceModelAdmin` | no admin |
| 22 · expand/contract migrations | no migrations |
| 24 · `.for_tenant(t).visible_to(actor)` | same as 8 — visibility is the server's answer, and the client renders it |
| 25 · `comms.send()` is the only sender | no sender exists here at all (§7) |
| 26 · a service names nothing the actor could not reach | no services; reachability is decided where the services are |

**And what DOES transfer, so you can find the parent rule when you need the
argument:** 11 (the file-shape taxonomy, §2) · 7 (declared import contracts,
§2) · 12 (read/write separation, as render/request, §4 Law 4) · 14 (HTTP
vocabulary stays at the boundary, §4 Law 1) · 16 (the naming grammar, plus
generated types verbatim, §4 Law 3) · 5 (budgets, as requests-per-screen and
bundle floors) · 17 (parity, weakened to **coverage** — a capability on REST
need not be on a screen; a screen that exists must reach it through the one
door) · 23 (supply chain, a second population — the JS dependency tree) · 32
(resource-first paths, verbatim — the client consumes them) · 27/33/48 (the
one-door fence, §4 Law 2) · the whole enforcement grammar: valves that are
counted and printed, canaries that must fire, declared blind spots, ratchets,
and 0 clean / 1 violations / 2 enforcement-broken.

**One declared blind spot, by construction:** client caches are keyed by the
acting hat, and a hat change must invalidate them. Nothing mechanical proves it
does. Write the invalidation, and say in your report that you did.

---

## 12 · Before you report

- Every authored `SurfaceState` **screenshotted**, labelled, and each one saying
  what made it non-vacuous.
- **Hydration assertion and console transcript pasted**, not characterised.
- **Red-first shown by the rendered check** — the state or route absent, or
  rendering the undesigned default — never asserted in prose.
- Every **hand-typed shape checked against the generated client**; every `as`
  past a generated type either removed or defended in the report by name; every
  **fixture typed against the generated shape**, not against the component that
  reads it.
- If you touched `package.json`, the lockfile, the generated client or a frozen
  layer: **say so**, and say that the rung ran alone.
- Any **missing ingredient that stopped you**, named. Stopping is the correct
  outcome; improvising a token, a component or a designed state is not.
- Anything you could not see: the drive that would not run, the state you could
  not seed. **A frontend rung's most expensive failure mode is a green report
  over a surface nobody looked at.**

---

## 13 · Golden fences — what a product copies from the worked face

The worked face (`frontend/src/screens/widget/`, its copy module
`frontend/src/copy/widget.ts`) is the example a product copies, and every block
a product copies is fenced: `// golden: <verb> begin` … `// golden: <verb> end`
(`/* … */` in a stylesheet, `{/* … */}` inside JSX). The face's base — the list
and the record with no family verb on them — is fenced `face`.
`scripts/tests/test_golden_face.sh` copies the base and one verb's blocks into a
scratch world with the one rename (`Widget`→`Gadget`) and proves the copy holds
rules 77–80, type-checks and passes the face census. A block that needed a hand
edit beyond the rename is a finding against the example, not a step.

**Two fence forms, and the question that picks one: does the block need ONE of
its verbs, or ALL of them?**

- **OR — stacked single-verb fences.** A block SEVERAL verbs each need on their
  own (a shared import, the sheet's CSS that Edit and Move both use) carries one
  fence line per verb, stacked, and goes with ANY of them:

  ```ts
  // golden: move begin
  // golden: bulk begin
  import type { Destination } from "@/screens/widget/parts";
  // golden: bulk end
  // golden: move end
  ```

- **AND — one joint fence, `+` between the verbs.** A block that exists only
  where two verbs meet — the selection bar's *Merge* needs the bulk bar AND the
  merge confirm — goes only with a copy that holds EVERY verb it lists:

  ```tsx
  // golden: bulk+merge begin
  import { type MergePairPress, MergePairSheet } from "@/screens/widget/widget-merge";
  // golden: bulk+merge end
  ```

  A single verb's case leaves it behind (the bulk copy has no confirm to open,
  the merge copy has no bar to sit in); the drive's joint case — every verb at
  once, in `--all` — takes it and proves it. A joint list names two or more
  distinct family verbs, or the drive exits 2 naming the fence.

The wrong form for a joint block is the OR form: stacked `bulk` and `merge`
fences hand the bar's *Merge* to the bulk copy, where it imports a confirm the
copy does not have, and the copy stops compiling. The wrong form the other way
is leaving a joint block unfenced: no case ever copies it, so nothing proves it.
