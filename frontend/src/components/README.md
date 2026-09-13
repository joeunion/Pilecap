# `components/` — L2, and it is EMPTY on purpose

**Nothing lives here yet.** The single screen this template ships
(`src/screens/welcome/`) is a *worked example*, not a library: it is one
surface, and it is not reusable by design. A component becomes a component the
day a second screen needs it.

## What belongs here when a product fills it

A **component** carries product nouns — `DealCard`, `PatientHeader`,
`InvoiceRow` — and it **renders a `SurfaceState`; it never fetches**. That is
house rule 12's read/write split translated: fetching lives at the route, which
hands the state down. A component that owns a request cannot be rendered in any
state on demand, and every story of it needs a network.

It may import `primitives/`, `tokens/`, `copy/` and `screens/state.ts`. It may
**not** import from `api/`.

## The layer contract

It is written once, in `src/primitives/README.md`, and this file points at it
rather than repeating it — a second copy is a second thing to drift.

## Two things that are NOT components

- **`state.ts`** lives in `src/screens/`, beside the layer whose definition it
  is: a surface is not a screen until all four of its states are authored.
- **The client seam** lives in `src/api/`. It is the only place in this tree
  that knows the backend exists.
