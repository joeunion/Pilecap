# ADR platform-partition-1

- **ADR platform-partition-1 (the three cross-app moves the platform
  partition needed)** · at the freeze ·
  **the design and the authority is
  `docs/product/partition-closure.md`**, which ships; this entry is its
  ADR line per the ADR-home rule above, and records only the three
  decisions that reach across apps. · **context:** the partition skips
  the platform's pytest suite under a banked verdict whose key still
  matches everything that suite reads. A driven audit planted a product
  app (`apps/<orders>/` with a `TAGS` dict) and found **a false red on
  three in-closure tests** — not a stale green but a red a clone cannot
  clear without editing platform files, so the closure hash moves on the
  product's first door and the dividend dies there. The shape is
  general: a platform test that needs a per-member fact about a
  discovered population, sourcing that fact from a central in-closure
  file. · **decision, three moves** — (a) **D1**, the freeze census
  leaves the closure: `FROZEN_FAMILIES` and `SANCTIONED_RENAMES` move
  from `apps/core/api/scopes.py` into `apps/core/api/frozen_families.py`,
  re-exported unchanged, and that one file is the closure's **one
  enumerated exclusion** — it re-enters the skip key through the
  discovery digest's `scope_families` section, so a product's append is
  an out-of-closure edit that still buys an honest re-run; (b) **D2**,
  the two-planes guide's plane assignments move from `docs.py` prose
  onto each family's own `Tag` (`plane`, `plane_note`), and the guide
  renders from the registry — the property the platform already claims
  for the vocabulary, extended to its documentation; (c) **D4**, the
  exports census's hand-pinned assertions scope their quantifier to the
  lockfile's apps (`quality/partition.yaml`), because "pinned" was
  always a property of THIS TREE; the derived-side assertions stay
  global, since a product model must join the archive census and does.
  · **the generalized rule, cited into the architect's checklist:** a
  platform test that needs a per-member fact about a discovered
  population sources it from **the member's own declaration**, never
  from a central in-closure file; a central ledger products must append
  to either lives out-of-closure as a data module that re-enters the key
  through the digest, or the assertion scopes its quantifier to the
  lockfile population. · **rejected:** a `platform = True` marker on
  `AppConfig` (puts the boundary in code the product owns — the
  partition would skip on the product's own say-so); per-app freeze
  ledgers (a vanished app deletes its own memory, and the census exists
  to outlive what it remembers); leaving the plane in prose and widening
  the census test (it would stop asserting the thing it exists to
  assert). · trigger to revisit: a second exclusion is wanted — that
  is a design change to `partition-closure.md` §3, not an edit to the
  lockfile.
