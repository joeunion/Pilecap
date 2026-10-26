# The five-lens critique — the release step a minor cannot skip

A minor release ships only after five senior reviewers have re-read **the export
being released** and none of their findings stands above LOW (ADR docs-1; the
owner's rulings of 2026-10-23). `./scripts/publish.sh --release` enforces the
first half: it refuses a minor whose candidate identity no
`docs/product/reports/<cycle>/critique-*-reread.md` (the template's release re-read: R8 trims its reports and a product releases with deploy/release.sh) header names, and prints an
advisory for a patch. The identity is the export's tree hashed with its version
homes masked (`TEMPLATE_VERSION`, `pyproject.toml`, `uv.lock`, the CHANGELOG's
section header and foot link): the PM's ruling of 2026-10-23 on the owner's
"cut it as the candidate, then re-read THAT cut" — the re-read reads the alpha
cut, and the release's export differs from it only in those homes. The second half — the severity bar — is the PM's reading
of the reports, recorded in the cycle's plan.

## The road

1. **Cut the candidate.** The alpha cut, or `./scripts/publish.sh --to
   <scratch dir>` of the commit you will release. Its verdict prints
   `identity <40 hex>`: that is the candidate's name, and a `--release` whose
   export differs only in its version homes prints the same one.
2. **Dispatch five reviewers, one lens each, read-only, in parallel.** Each is
   handed the export's path and nothing else — no plan, no ledger, no report,
   no development checkout. They may run the export's own commands in a scratch
   copy of it (`--rules`, `--explain <id>`, `--fast`, the one path to a noun).
3. **Each writes one memo** at `docs/product/reports/<cycle>/critique-<lens>.md` (the template's):
   a header naming the identity and the start time, a verdict in one sentence, the
   findings that most changed the reviewer's opinion (each with the export's
   `path:line` and the expected behaviour), and what impressed them.
4. **The PM writes the re-read report**
   `docs/product/reports/<cycle>/critique-<cycle-or-version>-reread.md` (the template's). Its
   header — every line before the first `## ` — names the candidate's identity
   (12 hex or more, e.g. `identity 1f4f87b456e0`); its body is one table: lens · verdict · findings → rows, each
   row with its band. Commit it, then run `--release` from the same commit's
   tree: the report lives under `docs/product/reports/`, which the census trims,
   so committing it does not move the export's identity.
5. **No row above LOW → release.** Every LOW is booked as the next patch's row
   before the cut. A HIGH or MED is fixed, and the re-read runs again on the
   new candidate — a re-read of another identity vouches for nothing.

## The five lenses

| Lens | Reads the export as | Asks |
|---|---|---|
| First-feature developer | a stranger with the README and a laptop | Can I reach a live-driven first noun from these files alone, and where must I guess? |
| Maintainer | the engineer who owns the gate next year | Is every rule enforced, canaried and floored as its name says, and what costs the most to keep? |
| Operator | the person paged at night | Could I stand this up and run it under load from these files alone, and is every number measured? |
| Security reviewer | a pre-production review | Is the trust boundary the one the code runs, and do the security instruments verify what their prose claims? |
| Architect | a senior lead deciding whether to inherit it | Does the authority describe the tree, and which decisions would I refuse to inherit? |

## The reviewer's brief, verbatim to each

> You are a senior engineer reviewing a software template as published. Read
> ONLY the directory `<export>` — nothing else on this machine. Your lens:
> `<lens>` (`<the Asks column>`). Record the time you start. Write your memo to
> `<path>`: its first line names the lens, its header names the identity
> `<identity>`; then a one-sentence verdict; then at most seven findings, each with
> the export's `path:line`, what you expected and what the file says; then
> what impressed you. Cite, never paraphrase. Do not fix anything.

The yardstick every lens is read against (owner, 2026-10-01): a senior lead
engineer reads it and is impressed.
