# The goal posts — one dated verdict per pillar

> **This file is DATA. `scripts/goalpost_scan.py` is the reader, and it is the
> only thing that decides what a row means.** Run it:
>
> ```
> python3 scripts/goalpost_scan.py            # the verdicts
> python3 scripts/goalpost_scan.py --kinds    # the vocabularies, in full
> ```
>
> **Exit 0** read and judged · **1** a verdict is STALE (a computable re-trigger
> fired after its proof date) · **2** could not look (a pillar with no row, a row
> with no proof date, a re-trigger kind outside the closed set, an unreadable
> file). 2 outranks a pass.

## What a row is

The pillars are **not** named here — they are read from `north-star.md`'s "How
we will know" table, and a pillar with no row (or a row naming no pillar) is
exit 2. That is the census shape: the list IS the population, checked, never a
second copy that agrees today.

| Column | What it holds |
|---|---|
| `Pillar` | Verbatim from `north-star.md`'s table |
| `Verdict` | Starts with a declared kind (`--kinds`), then any qualifying text. A `MECHANISM` verdict must also carry `operation_by: <product>` |
| `Proof date` | `YYYY-MM-DD`. The day the verdict was earned — **never** the day it was typed |
| `Proof artifact` | The thing a stranger reads to check it. A status with no artifact is a hypothesis wearing a status |
| `Re-trigger` | ` · `-separated `<kind>:<spec>` tokens. The kinds are closed and are **borrowed** from `scale-envelope.md` § Re-triggers — there is no second re-trigger vocabulary in this repository |

**The verdict kinds are not listed here on purpose.** They live in
`goalpost_scan.py::VERDICT_KINDS`, one line each; `--kinds` prints them. One
writer per fact: a second copy here would agree today and drift the first time a
kind is added.

**Resolution is a DAY.** Staleness compares the row's proof date with the
committer date (`%cs`, the commit's own timezone) of the newest commit touching
the re-trigger's globs. A change made later on the proof date itself is
invisible, and a re-trigger touched in an unmerged worktree is invisible until
merge — main is the only tree a verdict vouches for.

**Whose pen this is.** The verdicts are the PM's, written at CLOSE (the
goal-post scan clause in `.claude/skills/product-manager/references/operations.md`).
A builder does not move a verdict. Seed the register from the product's own
first audit, and cite what each row was read from.

**Status:** skeleton. The pillars are read from `north-star.md` — fill that
first, then give every pillar a row here. A pillar with no row is exit 2, and
that is the correct state for a product that has not yet decided what it
promises.

## The register

| Pillar | Verdict | Proof date | Proof artifact | Re-trigger |
|---|---|---|---|---|

<!-- worked example — replace with your product's first real entry -->

> ## EXAMPLE — one worked pillar row; delete when the first real one lands
>
> | Pillar | Verdict | Proof date | Proof artifact | Re-trigger |
> |---|---|---|---|---|
> | Correctness | GREEN — every canary fires through the real scope, a piped gate is refused, and the verdict is keyed on the tree hash | 2026-03-09 | the cycle-1 PROVE report in `docs/product/readouts.md` (full gate in a stranger's clone, the verdict line pasted; self-test counts fired/silent; a planted literal reddening exit 1); the verdict ledger (`scripts/gate_ledger.sh`) | paths:quality/**,scripts/check.sh,scripts/gate_ledger.sh,scripts/test.sh |
>
> Read the row against the four columns above: the verdict opens with a
> declared kind, the date is the day it was EARNED, the artifact is a thing a
> stranger opens, and the re-trigger is a computable `<kind>:<spec>` — so the
> scan can call this row stale without anybody's opinion.

## What this register does not see

Read `python3 scripts/goalpost_scan.py --help` for the reader's declared blind
spots. The two that bite hardest:

- **A wrong verdict that cites a real artifact passes.** The scan checks that a
  row has a date, an artifact and a legal re-trigger — never that the artifact
  says what the row says.
- **`asserted:` is honest and toothless.** A fact no tree can see is printed
  `UNVERIFIED — asserted by <who> on <date>` forever, and nothing mechanically
  obliges anyone to refresh it. The PM's CLOSE scan is that obligation, and it
  is prose.
