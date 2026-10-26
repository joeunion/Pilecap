# `frontend/` — the client layer

**The template's worked client: sign in and land on `/welcome`; the worked
Widget face a product copies (`src/screens/widget/`, walked at
`/example/widgets`); and the customer face a second surface draws
(`src/screens/customer/`, the pages under `src/app/(customer)/`).** The route
table (`src/screens/routes.ts`) is the list of what is here, one row per page.

This is the template's *worked example* of a client, not its product. It exists
for the same reason `apps/example` does: a rule that never fired anywhere is
decoration, and every frontend rule this repository owns — the byte-pin,
`SurfaceState` in anger, the token census (house rule 53, a static reader of
declarations and `var()` reads; whether a token resolves to a real value is a
rendered fact the browser drive reads, fe-conventions §8, and no instrument
holds it yet) — needs a tree to be proven against. Delete it, or grow it. Nothing here is furniture you must keep.

**What it is NOT: a component library.** `src/components/` holds only its
README, and `src/primitives/` only token-only shapes that know no product noun
(the dialog a house rule needs, and the card, pill, still line and alert box
every face draws) — each says why in its own README. Shipping components from
here would be exporting this template's taste into every product built on it.

## How to write anything here

**`.claude/skills/fe-conventions/SKILL.md`, before you touch a file.** It is the
`django-conventions` of the client layer: the four laws, the wrong form and the
right form for each, and — in §10 — an honest table of what actually enforces
each law today. This file does not restate any of it, so it cannot drift from
it.

The one thing worth repeating here, because it is the reason the rest exists:
**an agent cannot see its own frontend work.** A backend agent's artifacts are
self-inspectable; a frontend agent's output is pixels, and its default
instruments are exactly the ones that let a rendered-but-never-hydrated page
ship under hundreds of green component tests. The browser drive is part of a
frontend rung, not a later stage.

## Layout

```
frontend/
  package.json  pnpm-lock.yaml  .npmrc  .nvmrc  next.config.ts  tsconfig.json
  openapi.json                 # the document of record — committed, exported from the checkout
  scripts/
    pin_client.sh              # the byte-pin: committed client == fresh generation
  journeys/                    # journey specs + the acceptance-ledger shape
  src/
    app/                       # ROUTES. Filesystem-discovered; a route is never registered anywhere
    api/                       # THE CLIENT SEAM — the only place that knows a backend exists
      generated/               #   openapi-typescript output. Never hand-edited, never re-declared
      client.ts                #   the one request function; carries the hat, the page token, the intent key
      refusals.ts              #   wire refusal -> Refusal. The mirror of config/api.py
    tokens/                    # L0 — names, values, and the ONE stylesheet a route may import
    primitives/                # L1 — token-only shapes, no product noun; the layer contract is its README
    components/                # L2 — a component the day a second screen needs one; see its README
    screens/                   # the SHAPE: state.ts, plus view + stories + copy per screen
    copy/                      # strings live in copy modules, not inline in JSX
```

The **import contract** — which layer may import which — is written once, in
`src/primitives/README.md`.

## Commands

| | |
|---|---|
| `pnpm dev` | the development server (proxying `/api/v1/**` to Django) |
| `pnpm build` | the production build |
| `pnpm test` | the component tier — necessary, never sufficient |
| `pnpm lint` · `pnpm typecheck` | `--max-warnings=0`, `tsc --noEmit` |
| `pnpm pin:client` | assert the committed client matches this checkout |
| `pnpm pin:client:write` | regenerate it (a deliberate, serial rung) |

`DJANGO_ORIGIN` is where the proxy points, and it is REQUIRED: `next.config.ts`
refuses to load without it, because the backend's port is derived per checkout
and no default can name it. For this checkout's own backend, from the
repository root: `export DJANGO_ORIGIN=http://127.0.0.1:$(./scripts/serve.sh --print-port)`.

## The three populations that stay serial

Frontend rungs fan out — routes are filesystem-discovered and barrels are
banned — **except** for these three, which are serial *with respect to each
other* and never block the rest of a wave:

1. **`package.json` / `pnpm-lock.yaml`.** The lockfile is this layer's
   `max_migration.txt`, and it is worse: it conflicts *dirtily*. Two branches
   can merge textually clean into a lockfile that satisfies neither
   `package.json`, and nothing says so until `--frozen-lockfile` runs.
2. **Client regeneration.** Two rungs regenerating against two different
   documents produce a client that matches neither.
3. **Frozen layers** — `src/app/layout.tsx`, `next.config.ts`,
   `src/tokens/tokens.css`. One rung at a time against a given layer.

## What is deliberately absent, and is therefore owed

Named here so the next rung finds them as gaps rather than discovering them as
bugs:

- **A cache, and therefore its invalidation.** Client caches must be keyed by
  the acting hat and invalidated when the hat changes; nothing mechanical
  proves it. There is no cache here yet.
- **Two scripts the gate does not run yet.** The fe leg (`scripts/fe_gate.sh`)
  runs the frozen-lockfile install and `pnpm test`, and discloses a client the
  contract surface may have staled; `pnpm lint` and `pnpm typecheck` are run by
  hand until that leg runs them too.
