# `frontend/` — the client layer

**One journey, and it is the whole of it: sign in, and land on `/welcome`.**

This is the template's *worked example* of a client, not its product. It exists
for the same reason `apps/example` does: a rule that never fired anywhere is
decoration, and every frontend rule this repository owns — the byte-pin,
`SurfaceState` in anger, the token census's runtime half — needs a tree to be
proven against. Delete it, or grow it. Nothing here is furniture you must keep.

**What it is NOT: a component library.** `src/primitives/` and
`src/components/` ship EMPTY, with a README each. Shipping components from here
would be exporting this template's taste into every product built on it.

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
  scripts/pin_client.sh        # the byte-pin: committed client == fresh generation
  journeys/                    # journey specs + the acceptance-ledger shape
  src/
    app/                       # ROUTES. Filesystem-discovered; a route is never registered anywhere
    api/                       # THE CLIENT SEAM — the only place that knows a backend exists
      generated/               #   openapi-typescript output. Never hand-edited, never re-declared
      client.ts                #   the one request function; carries the hat
      refusals.ts              #   wire refusal -> Refusal. The mirror of config/api.py
    tokens/                    # L0 — names, values, and the ONE stylesheet a route may import
    primitives/                # L1 — EMPTY. Boundary law in its README
    components/                # L2 — EMPTY. Boundary law in its README
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

`DJANGO_ORIGIN` overrides where the proxy points; it defaults to
`http://127.0.0.1:8000`, which is `scripts/serve.sh`.

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

- **A mutation wrapper.** This scaffold makes no writes, so it ships none —
  a reader-less mechanism is the class this house refuses. The first writing
  rung builds it, carrying the CSRF token, an `Idempotency-Key` and the hat,
  and it will need `CSRF_TRUSTED_ORIGINS` to name the browser's origin on the
  Django side.
- **A cache, and therefore its invalidation.** Client caches must be keyed by
  the acting hat and invalidated when the hat changes; nothing mechanical
  proves it. There is no cache here yet.
- **A gate leg.** `pnpm test`, `pnpm lint`, `pnpm typecheck` and the byte-pin
  are run by hand today. Wiring them into `scripts/check.sh` is a separate
  rung's territory.
