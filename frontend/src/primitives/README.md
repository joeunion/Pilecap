# `primitives/` — L1: token-only shapes that know no product noun

**A primitive lives here when a house rule needs it to exist, or when every
face draws the same token-only shape** — the directory listing is what is
here: the sheet (rule 70), and the card, the pill, the still line and the
refusal notice's box the faces drew inline before (the book's §10, §16, §13,
§15). Shipping a look here would be the mistake.

This template ships a *system*, not a look. A component library shipped from
here would be taste exported into every product built on it — the design strike
that was called on exactly that proposal, and the reason a primitive here is
drawn with the tokens alone and carries no product noun.

**A primitive has no stylesheet.** Its paint is inline and token-only, and
each `style={` carries a `// paint:` comment with its reason (the book's §26:
a sheet belongs to a face).

**The dialog primitive is the sheet** (`patterns.md` §1), and it is here because house
rule 70 says only the dialog primitive draws a `<dialog>` or a
`role="dialog"` — a rule about the one primitive needs the primitive to exist.
Its shape is the book's floor (one head with the one dismiss, a body, a foot of
acts only), drawn with the tokens alone; a product's look reaches it through
the tokens and the drawer, never by a second dialog beside it.

## What belongs here when a product fills it

A **primitive** knows nothing about your product. A button, a stack, a field, a
card. It may import `tokens/` and `copy/` **and nothing else** — no product
nouns, ever. If it knows what a deal, an invoice or a patient is, it is not a
primitive; it belongs in `components/`.

## The layer contract, in full

Imports flow one way. This is house rule 7's shape, in JavaScript:

```
copy ← tokens ← primitives ← components ← kit ← screens ← app(routes)
                                          api ← app(routes)
```

- A **route** (`src/app/`) may import from `screens`, `kit`, `components`,
  `primitives`, `copy` and `api`. It fetches; it does not paint.
- A **screen** (`src/screens/`) may import `kit`, `components`, `primitives`,
  `tokens` and `copy`. It may **not** import from `api` — that is what keeps a
  screen renderable in every state without a network.
- The **kit** (`src/kit/`) is what every face shares — the surface state,
  the verb and route tables, the refusal renderer, the remedy door, and the
  primitives a screen draws — imported as `@pilecap/ui/<module>` (strings as
  `@pilecap/copy/<module>`). It may import `components`, `primitives`,
  `tokens` and `copy`, and `api` through `state.ts` alone.
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
class on a host element, or a stylesheet the design did not give. A face's own
prefixed, token-only sheet beside its screens IS the pattern (the book's §26).

The wrong forms and the right ones are in
`.claude/skills/fe-conventions/SKILL.md` §2 and §5. This file points there; it
does not restate it, so it cannot drift from it.
