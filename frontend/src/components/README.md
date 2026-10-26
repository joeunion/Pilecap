# `components/` — L2, and a component lands here the day a second screen needs it

**The template's screens are *worked examples*, not a library** (`src/screens/`
— each is one surface, and not reusable by design). A component becomes a
component the day a second screen needs it, and not before.

## What belongs here when a product fills it

A **component** carries product nouns — `DealCard`, `PatientHeader`,
`InvoiceRow` — and it **renders what a screen hands it; it never fetches**.
That is house rule 12's read/write split translated: fetching lives at the
route, which hands the state down to a screen, and the screen hands its parts
on. A component that owns a request cannot be rendered in any
state on demand, and every story of it needs a network.

It may import `primitives/`, `tokens/` and `copy/` — the layers below it in
the chain `src/primitives/README.md` declares — and nothing above them: not
`kit/` (`kit/state.ts` included) or `screens/`, and never `api/`. It is
handed the data of a state, never the state's refusal vocabulary, which reaches
a surface through `kit/state.ts` alone; that is why the one refusal renderer is
a kit-layer module (`src/kit/refusal-panel.tsx`).

## The layer contract

It is written once, in `src/primitives/README.md`, and this file points at it
rather than repeating it — a second copy is a second thing to drift.

## Two things that are NOT components

- **`state.ts`** lives in `src/screens/`, beside the layer whose definition it
  is: a surface is not a screen until all four of its states are authored.
- **The client seam** lives in `src/api/`. It is the only place in this tree
  that knows the backend exists.
