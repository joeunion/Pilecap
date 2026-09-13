# `primitives/` — L1, and it is EMPTY on purpose

**Nothing lives here yet, and shipping something here would be the mistake.**

This template ships a *system*, not a look. A component library shipped from
here would be taste exported into every product built on it — the design strike
that was called on exactly that proposal, and the reason this directory is a
README and nothing else.

## What belongs here when a product fills it

A **primitive** knows nothing about your product. A button, a stack, a field, a
card. It may import `tokens/` and `copy/` **and nothing else** — no product
nouns, ever. If it knows what a deal, an invoice or a patient is, it is not a
primitive; it belongs in `components/`.

## The layer contract, in full

Imports flow one way. This is house rule 7's shape, in JavaScript:

```
copy ← tokens ← primitives ← components ← screens ← app(routes)
                                    api ← app(routes)
```

- A **route** (`src/app/`) may import from `screens`, `components`,
  `primitives`, `copy` and `api`. It fetches; it does not paint.
- A **screen** (`src/screens/`) may import `components`, `primitives`,
  `tokens`, `copy` and `state.ts`. It may **not** import from `api` — that is
  what keeps a screen renderable in every state without a network.
- A **component** (`src/components/`) may import `primitives`, `tokens` and
  `copy`. Never `api`.
- A **primitive** (here) may import `tokens` and `copy`. Nothing else.
- **A route never imports another route.**

**Barrel files are banned.** An `index.ts` that re-exports a directory is the
`INSTALLED_APPS` of JavaScript: one shared file every parallel rung must edit,
so every parallel rung collides in it. Import from the module that defines the
thing. That single rule is what lets frontend rungs fan out at all.

**A missing ingredient stops the rung.** An agent asked to fill a visual gap
fills it *plausibly*, which is the documented failure mode wearing CSS. If the
primitive you need is not here, say so and stop — do not inline a style, a
class on a host element, or a second stylesheet.

The wrong forms and the right ones are in
`.claude/skills/fe-conventions/SKILL.md` §2 and §5. This file points there; it
does not restate it, so it cannot drift from it.
