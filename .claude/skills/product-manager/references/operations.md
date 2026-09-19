# Operations — running the machinery of the loop

The main skill says what the loop is; this file says how to run it without
losing work to the machinery — the builders, the wave, the host, and the owner
relationship. Nothing here is theory: every clause exists because its absence
cost a round, and each one says what it protects. Method belongs here; state
belongs in `docs/product/`, same as always.

## The parallel-frontier step

**Every agent return triggers the question: "what can run in parallel NOW?"**
— asked as part of processing the return, not waiting for the owner to ask it.
The test is the sacrifice test from the parallelism doctrine: a leg may start
early iff its inputs are frozen and its proofs still run on the final state.
If the answer is yes with no quality impact, dispatch immediately (ledger
first). Mixed-dependency legs split with a **named hold**. Common frontier
moves this earns over and over: pull the verification band's independent legs
forward once the diff freezes; write the next cycle's plan during this cycle's
tail; design-ahead ADRs when their evidence freezes; start owner clocks
(domains, access cases) the moment they are identifiable. The question costs
seconds; an idle frontier costs the whole gap.

**It is a LEDGER FIELD, not a habit.** Prose steps get skipped exactly when the
return is interesting — which is when the frontier is widest. So every ledger
row you close for a returning agent ends with a `frontier:` clause: either what
you dispatched because of this return, or why nothing could start (which leg is
not frozen, which proof would be invalidated). **A closed row with no
`frontier:` clause means the step did not happen** — visible in the file,
checkable at CLOSE, inherited by whoever runs the loop next. The reason it is a
field and not a paragraph is that a PM will skip a paragraph while believing it
followed it, including on a row it had itself marked blocking an hour earlier.

## The friction discipline

**Standing guard: PM commits are pathspec-only** — `git commit -m ... -- <paths>`
— because agents sharing the checkout may have files staged, and a bare commit
sweeps them in under the wrong message. **The named paths are the commit.**
Does not cover: builders committing in their own worktrees (they stage only
their own tree), or a stray file staged under a path the PM's pathspec happens
to name.

The loop's own drag is a population, and it is managed like one — captured
always, evaluated on the second strike, pruned on a cadence. The owner is
excluded from this discipline by standing ruling.

**Tier 1 — capture always, never pause.** Any friction that costs more than a
minute gets **one logged line at the moment it happens**, classed as one of
four: **violation** (an agent broke a standing rule), **environmental** (the
host, the network, a stall), **process** (the method itself cost the time), or
**inherent** (the work was genuinely that expensive). One line, then back to
work — the discipline is capture, not analysis, and a capture that pauses the
loop costs more than the friction it records. Log it where CLOSE will find it,
and there are only two such places: **the dispatch-ledger row's own result
cell** when the friction belongs to a dispatch, or **a dated
`## Friction capture` section in `queue.md`** when it does not. A capture
written anywhere else is a capture CLOSE will not read.

**Tier 2 — the second strike in-cycle is evaluated immediately.** One
occurrence is weather; the same friction twice in one cycle is a pattern with
a live reproduction, and the moment to evaluate it is now, while both
instances are fresh. Evaluate via **shop-the-price** — exactly the FRAME
question: what would a guard against this protect, and is that thing real? —
and if it clears, a mini-rung lands the guard. What clears at CLOSE instead of
mid-cycle builds as a **next-cycle band rung**, not a bolt-on.

**At CLOSE, the friction log feeds MISSES.** Scan it as part of stage 7:
anything classed *violation* or *process* that recurred is a miss candidate
and climbs the ladder like any other; *environmental* entries feed the
preflight list below; *inherent* entries are the honest cost of the work and
get no guard.

**Tier 3 — the guard retrospective, every three cycles or a week, whichever
comes first.** PM-run, owner excluded by his own ruling, and it has two halves
that must both happen:

- **Cross-cycle patterns** — what recurs across cycles that no single cycle's
  MISSES could see, because a pattern needs a population.
- **Pruning** — a **false-positive audit** (which guards fired on legitimate
  work), **dead-guard deletion** (which guards have never fired and protect a
  condition that no longer holds), and the **guard latency budget** (what the
  whole population costs per run, held under a declared ceiling). A guard
  population that only grows becomes the friction it was built to remove.

Results go in the cycle report, not a side channel.

**Guard hygiene**, for every guard the discipline produces: it **names its
incident** (the friction-log line or miss it answers), **declares
`does_not_cover`** like any house rule, **carries a self-test**, and the
population stays under the latency budget. And the posture: **guards stop
casual drift, not sabotage.** Assume good intent — a guard designed against an
adversary is expensive, brittle, and insulting to the agents it wraps; a guard
designed against forgetting is cheap and usually right.

## Running builders

The dispatch contracts in `dispatch-briefs.md` say what a brief contains; this
section is the PM-side handling that keeps a dispatched builder from losing
work to the machinery.

- **Anti-stall and commit-at-boundaries go in every dispatch brief.** Long
  commands run in the background with output to a file, read when done — so a
  stream stall costs the rendering, not the work — and the builder commits at
  every rung or leg boundary, so a killed session loses minutes, not the rung.
  Under unstable conditions a WIP commit that skips hooks is legal if the tree
  is fully gated afterwards and the deviation is reported.
- **Turn-taking on test suites: never two suites in one checkout or one
  database.** Builders have their own worktree and database by construction;
  the rule bites where checkouts are genuinely shared — the main checkout, a
  standing agent's kept worktree, a verifier's clone. Before running a suite
  there, `pgrep` for a runner already in flight and wait your turn. Two suites
  interleaved in one database produce failures that are real, unreproducible,
  and expensive to disbelieve.
- **The PM's pre-edit gate check:** before ANY write in a shared checkout — a
  ledger edit, a queue row, a merge — `pgrep -f check.sh` and read what is
  running. A peer's FULL gate anywhere in the checkout family means hold: a
  main-checkout commit moves shared refs and trips the full gate's mutation
  guard. A peer's `--fast`/`--loop` is safe. The sibling fact, which is not
  obvious: **a merge into local main during a full gate is exit 2 on that gate
  even when the merge happens outside the gated checkout** — the gate's
  fingerprint reads main by sha.
- **Retire and refresh a long-lived agent at its first empty-handed leg.** An
  agent that returns from a leg with nothing landed — no commit, no finding,
  no verdict — has usually stopped converging, and feeding it more context
  deepens the hole. Retire it, keep the worktree, and dispatch a fresh builder
  into the **same worktree** with the criteria and the standing state; the
  work transfers, the spiral does not. This is the complement of *follow-on
  work goes to the standing agent*, not its contradiction: resume an agent
  that is converging, replace one that is not.
- **Write-first ordering under unstable conditions.** When the host or the
  session is shaky, do the write before the step that can die: the ledger row
  **before** the dispatch (the standing rule — a row stuck at `dispatching` is
  unambiguous), the commit before the long verification, the plan file before
  the fan-out. The recovery position is the last thing written, so write the
  thing you cannot re-derive first.

## The merge ritual reaps

When a rung's CHAIN is verified (its verification has passed), the PM removes
its worktree (`git worktree remove`, branch kept) and drops its databases —
the derived name, plus its `_hp` and `_perf` worlds — in the same action as
closing the ledger row. A standing agent whose chain is still open keeps its
worktree; nothing else does. Verifier clones are the verifier's to reap (a
brief clause); a clone found after its report is a finding against the brief.
**The watchdog checks disk at every firing** and treats a low free-space
reading as a stall-class event: reap, then report — a machine that cannot
write is a loop that cannot run, and it fails silently and misleadingly, since
the PM's own tool outputs die of a full disk before anything else visibly
does.

**The broom drops nothing it cannot positively prove.** A derivation-shaped
database with no visible checkout is `FOREIGN`, and `--sweep` alone leaves it;
reaping means `db_sweep.sh --all-checkouts --orphans --roots <dir-holding-the-clones>`
(positive proof) and, deliberately, `--sweep --force-foreign` ON TOP of it —
`--force-foreign` without `--roots` is REFUSED by `db_sweep.sh`, exit 2: foreign
is an absence of evidence, never a licence. A reap run without `--roots` reaps
nothing and says so.

**The bank is per tree, not per rung (S2, owner 2026-09-18).** A banked
verdict vouches for one tree; six verified rungs merged and banked once are
exactly as honest as six banks, and cost one full gate instead of six. The
PM merges a WAVE — every rung whose verification returned MET since the last
bank — and banks once, then pushes; a bank between two merges of one wave is
the cost the P20 ledger measured (BANK-6…BANK-10, 25–70 min each, the whole
machine held) and it bought nothing. The exceptions, each stated in the
ledger row: a hotfix whose merge the next rung's baseline needs (bank it
alone); a box push that must carry a specific tree (the field-test rule: no commit between
the bank and the push). Verification follows the same shape: one verifier
takes the wave's rungs in one clone when they share a territory, the
cost-baseline's lever 2, applied.

## Scaling the wave

**The stages split by what they need.** DESIGN, ratification and CLOSE are
**serial PM judgment** — they are the stages where taste, ordering and the
owner's rulings enter, and fanning them out buys nothing but averaging. BUILD
and verification **fan out**: when the wave is wide, run it as workflow
orchestration — the concurrency map is the script, the PM is in the loop
**between** phases, never inside one.

**Real parallelism is independent apps and enumerable sweeps; fake parallelism
is a shared schema or the same app.** Two rungs in different apps genuinely
run beside each other; two rungs in one app produce the merge migration the
whole system forbids; a "parallel" pair that both touch `core` is a serialized
pair wearing a concurrency map.

**Plans default to maximal safe parallelism; serialize only where a real
dependency or a quality gate demands it** (a standing owner ruling). Quality is
the constraint; wall-clock is the objective. The discipline, before sequencing
anything — run a **dependency pass** over the legs:

1. **What does this leg actually read, and is that input frozen yet?** A leg
   whose input is still being written serializes behind the writer; a leg
   reading only frozen state runs now.
2. **Do its outputs certify anything later work would invalidate?** A
   certification over a tree that will change is a certification of nothing.

Legs with **mixed** dependencies **split**: run the environment-shaped half
now and hold the certifying half for the final named commit, with an explicit
hold point in the plan. The worked shape is a two-phase verification —
environment-from-zero immediately, certification held for the final tree. Legs
that **re-measure what another leg already certifies dedup**: a pre-push full
gate on the main checkout *is* the integration check — record it, do not
re-run it. And the honesty bar: **the plan states the independence argument
per parallel leg. If the argument cannot be stated, the leg serializes.**

## The goal-post scan, at every CLOSE

The north-star's "How we will know" table is the product's standing goal posts
— plain-language promises, each with a stranger's check, a read-from artifact,
and a re-trigger. **Run `python3 scripts/goalpost_scan.py`**; it reads the
table as a register and refuses a green whose re-trigger has fired since its
proof date, which is the whole reason the table is a table and not a
paragraph: a verdict earned three cycles ago otherwise reads exactly like one
earned this morning.

Then the PM's own three questions: (1) did this cycle's work hit any pillar's
re-trigger? A tripped re-trigger whose re-verification is not already
scheduled becomes a queue row before the cycle closes. (2) Did any pending
cell's filling pass land? Update the cell to a dated verdict. (3) Did we learn
a promise is worded wrong or missing? The table is owner-ratified — propose
the amendment in the cycle report, never edit the promises unilaterally. A
verdict is dated, never permanent; the scan is what keeps "done" a condition
the system keeps meeting instead of an event that happened once.

## The queue-citation census, at every CLOSE

**Run `./scripts/queue_cited.sh` and read the CITED-BUT-UNSTRUCK block before
closing a cycle** — it greps the tree for row ids, asks `queue.md` what each
row says, and prints the ones the tree has already paid and the queue still
carries as open. It exits 0 whatever it finds and no gate runs it: a citation
is evidence somebody worked a row, never proof the row is finished, so every
line is a question for the PM and not a verdict.

It exists because of an asymmetry that will drain a backlog's credibility if
nothing watches it: **the fix cites the row; the row never cites the fix.** A
backlog therefore reads larger than it is — routinely by a large fraction —
and an ordering decision made on the wrong denominator is the actual cost.

### The reap, at every CLOSE

A cycle's CLOSE reaps what the cycle grew. Three sweeps, in order, each with
its census printed before anything is taken:

1. **Worktrees whose chains closed this cycle.** `git worktree list` is the
   census; the keep-set is a judgment, not a pattern — live agents and standing
   builders whose chains continue into the next cycle keep theirs (the
   chain-done rule); everything else from the closed cycle goes
   (`git worktree remove --force`, then `git worktree prune`). Left unowned,
   worktrees accumulate at a rate of tens of gigabytes per cycle, because no
   single stage feels responsible for them.
2. **Their orphaned databases.** `./scripts/db_sweep.sh --all-checkouts
   --orphans --perf --roots <dir-holding-the-clones> --sweep --force-foreign`
   (`--roots` is mandatory with `--force-foreign`) — the census lists FOREIGN
   names before dropping; run it only after step 1, so the orphans are
   genuinely orphaned. Eyes on the list; a name you cannot attribute stops the
   sweep.
3. **The Temporal glance** — count the task queues, record the number, and
   sweep dead-worktree queues only with the same eyes-on listing.

The reap is PM-run at CLOSE, after the readouts row and before the push — the
push's gate then measures a tree whose neighbours are gone, and the next
cycle's agents spawn onto a machine that is not carrying several cycles of
archaeology.

## Instruments fail loud

**An instrument declares its blind spots and fails loud when it cannot see; a
reporting instrument is held to the same standard as a rule.** The rules engine
lives by this — `does_not_cover` on every rule; a dead canary or an unbound
scope is exit 2, never a pass — and reporting instruments drift away from it by
accident, one at a time, in ways that all look like health.

The three shapes to watch for, because each has appeared more than once:

- **The instrument that measures something no door does.** A performance
  verdict over a query the product never issues is a green about nothing. Fix:
  the instrument's population is derived from the real doors, and it says so.
- **The instrument that names one cause for a symptom with several.** *"A test
  is inheriting state"* is one explanation of a cross-run failure; a harness
  that never started, or one that silently connected to a peer checkout's
  server, are others, and they want opposite responses. Fix: an instrument
  that cannot distinguish its candidate causes reports the ambiguity rather
  than picking.
- **The instrument that cannot see its newest input.** A scoreboard reader
  that scans the last two table rows will silently ignore a newest entry
  written below the table as prose; one that scores the *first* fraction it
  finds in a cell reads a chronological `8/10 → 10/10` as unmet; one that
  matches a scoring vocabulary no writer ever used spends its stop-token
  permanently while blind to a real degradation. Fix: an instrument that
  cannot see its newest input **refuses (exit 2) rather than judging the older
  one**; its scoring vocabulary is asserted by its own self-test and stated
  where the writer writes; and a stop-signal is indifferent to whether
  stopping is convenient — it records the verifier's verdict verbatim, puts a
  comparison token beside it, and its self-test asserts only membership in the
  set.

The test for whoever commissions an instrument: **can it distinguish "nothing
wrong" from "I could not look"?** If not, it degrades to silence, and silence
reads as health. The goal-post scan is the named must-check of any instrument
census, because it is the one instrument enforcing the ship definition's entry
condition.

**And four CLOSE steps that follow from the same standard:** archive the
closed cycle's ledger table to `archive/in-flight-closed.md`, so a verifier
reading `in-flight.md` cannot mistake a closed cycle's table for the live one
and cross-explain from it; lead every readouts cell with the value the reader
scores, not with the narrative; record sum-of-rung-hours ÷ critical-path
hours, which means ledger rows carry HH:MM — a parallelism claim measured on
real features rather than asserted; and carry `loop: <hits>/<verifier rows>`
in the readouts row's "Overran session?" cell beside GATE TAX, counted off the
verifier rows' own `loop:` cells — the miss rate is the re-measured minutes,
and a rate nobody prints is a tax nobody argues about.

**The PM does not edit a checkout while a gate runs in it — docs included.**
A gate whose tree changes records no verdict, and the loss is silent. Sequence:
ledger row → dispatch → commit → push on entering a wait; never push mid-batch.
Where *"advance to sent in the same action as the call"* and *"never edit during
a gate"* collide, dispatch before pushing.

## The loop does not stop at CLOSE

A closed cycle is a report, not a gate. At CLOSE the PM frames the next cycle
and classifies the frame: built entirely from **pre-ratified** work — the
standing surface-review program, queued rows with holders, ratified
follow-ons — it **auto-opens immediately**; the owner reads the report and
interrupts at will, but absence never pauses the loop. The loop stops at a
cycle boundary only when the frame **requires a new ruling** (a new product
direction, spend, an external integration, the ship definition, taste) — and
then it stops on *that item only*, asked with a recommended default. Every
hard stop the owner actually cares about is item-shaped, not cycle-shaped:
money, credentials, real inboxes, irreversible acts on real data. The failure
this prevents is specific and expensive: a fully pre-ratified cycle sitting
framed and idle for half a day behind a stop that guarded nothing.

## The gate, per rung

**The per-rung gate is `--loop`; the full gate binds at the PM's batched
push.** This is `CLAUDE.md`'s designed policy — restated here because a PM
under pressure will inflate every brief to demand the full gate per rung and
pay ten minutes a rung for insurance the push gate already provides. That tax
can reach a third to a half of a rung's wall-clock before anyone notices it,
precisely because each individual run looks prudent. Two exceptions keep the
full gate per rung, because there it uniquely binds: rungs touching
`quality/**` (the canary self-test is their point) and rungs touching
dependencies (the supply-chain leg). Nothing reaches origin un-full-gated
either way — the pre-push gate is the binding proof, and recording that
verdict in the ledger is what makes the integration check a fact rather than a
claim.

**The verifier's single `--loop` is a consult, not a second gate.** A
verification runs `./scripts/check.sh --loop` once in its own clone — a
`VERDICT REUSED` banner is the observation and the gate, a miss completes and
is recorded rather than re-run — and its ledger row carries the typed cell
`loop: hit|miss(<reason>) <s>`, whose vocabulary `dispatch-briefs.md` § Field
test owns. That cell is the tax made countable: a field nobody fills is a tax
nobody can see.

## The environment

The host is part of the system, and it fails in ways no gate can see.

- **Preflight before any long run: the host is awake and on AC.** Sleep
  disabled for the duration (`caffeinate` or equivalent), power connected. A
  laptop that sleeps mid-suite produces the stall class below and can cost most
  of a rung; the preflight costs seconds.
- **Every worktree gets its own database** (`scripts/db.sh`) — restated here
  because it is also an environment rule: it is what makes turn-taking a
  shared-checkout problem only.
- **Network-fragile gate legs run early.** Anything that reaches the network —
  audits, image pulls, a live identity provider — goes at the front of a long
  run, so a late flake costs a retry of the cheap leg, not the suite work that
  preceded it.
- **Stall versus sleep — diagnose before recovering, because the recoveries
  differ.** From inside, both look like nothing advancing. A **stream stall**
  (the watchdog's class) kills the rendering while the host keeps running:
  background processes continued, file timestamps advanced, the work is
  usually intact. A **host sleep** freezes everything: a wall-clock gap
  appears in every log at once, and in-flight connections died mid-word. Check
  the timestamps first.
- **The recovery is resume-from-last-position, never re-plan.** Read what was
  actually written — the last commit, the last ledger state, the output file
  the anti-stall pattern was writing — and re-issue from there. Re-planning
  after a stall treats an environmental cut as a method failure and pays for
  the whole rung twice.

## Running beside the owner

The owner's intent: future owners of this template will know less about running
an agentic loop than the one who built it, and the skill must make them
successful without their needing to know why. So the default is autonomy, and
the interface is reports.

- **Hard stops only**: real money, interactive credentials, real people's
  inboxes, irreversible acts on real data, and the ship definition. These are
  the main skill's classes A, B and D — nothing here adds a stop, and nothing
  else pauses the loop.
- **Otherwise: autonomy with legible reports.** The owner steers by reading,
  not by being consulted — which makes the report's legibility a load-bearing
  property, not a courtesy. A report the owner cannot act on is a pause
  wearing a status update.
- **Questions to the owner are decision-shaped, with a recommended default.**
  Never "what do you think about X" — always "A or B; we recommend A because
  Y; A happens unless you say otherwise." An open question outsources the
  thinking the PM is for; a decision-shaped one costs the owner a yes.

## The surface-review program

One foundation surface per cycle gets a standing review rung, and the pattern
is held fixed. It exists because the surveyor's lenses and the field test's
driving both miss the same class: a surface that is individually correct and
structurally misusable.

**The pattern, every review:**

- **Two lenses, both required**: **sound** — no legal call sequence escalates,
  everything fails closed, no path around the walls — and **unmisusable** —
  the 15th app's author, who never read the docs, cannot accidentally ship a
  leak; the easy path is the safe path.
- **Executable findings only**: a named call sequence producing a named wrong
  outcome, confirmed by execution where possible. Each finding becomes a
  failing test (CONFIRMED, fix rung in-cycle) or is refuted. An unexecutable
  concern is an opinion and goes in the report, not the findings.
- **A known-issues exclusion list** in the brief, so the review spends itself
  on the unknown rather than rediscovering the queue.
- **Fixes land in the review's named fix cycle, scheduled before the review
  dispatches** — an unscheduled finding is a survey. A cycle's own standing
  review keeps its fixes in-cycle. **Pulled-forward reviews are legal** — they
  are read-only and parallelize freely; the constraint was always fix
  *capacity*, never review timing — as long as each names the cycle its fixes
  land in, in its own queue row.
- **Every review ends by asking what rule or canary keeps the found class
  closed forever.** Enforcement is the deliverable; the fixes are the
  byproduct. The worked move is two artifacts, not one: the concrete holes
  close in a fix rung, and the rule that stops the 15th builder from reopening
  the class is queued as its own enforcement rung.
- Settled rulings are not reopened — but a genuine security hole outranks
  settledness.

**The order, by inheritance leverage** — an example ordering, of the shape a
product writes for its own surfaces; the real one lives in `queue.md`, which,
as always, owns the ordering:

1. auth / permissions / hierarchy
2. workflows / Temporal — determinism, idempotency, hat-in-headers, run
   lifecycle
3. events + webhooks — outbox guarantees, replay, inbound signature and the
   tenant seam
4. comms — consent, quiet hours and suppression inside `send()`
5. realtime / sockets — channel auth, cross-group leakage; typically the
   least-enforced door
6. the enforcement engine itself — canary honesty, `does_not_cover`
   completeness
7. data lifecycle — expand/contract in practice, append-only, erasure and
   retention

**Re-review on material change to a surface, never on the calendar.** A
surface nobody has touched holds its certification; a surface that changed
materially lost it, whatever the date says.

## Merge discipline and crash triage

- **A command you trust ends at that command — merges included.** Never filter
  a merge's stdout: a filter that does not match git's refusal prints nothing,
  exits into a shell nobody is reading, and leaves a ledger saying "merging"
  over a tree that never merged — which then gates green. **`scripts/pm_merge.sh`
  is the PM's one merge path** and makes that sequence unavailable; where it is
  not used, check `$?` or `git log -1` after every merge.
- **Crash triage is a cross-check, not a read:** every ledger row at
  `dispatching`/`sent` must name an agent the agent list can see, or a returned
  report; any row that cannot is printed and chased. `scripts/pm_triage.sh` is
  the artifact half — it prints the rows the ledger believes are outstanding —
  and it deliberately cannot do the other half, because no shell script can ask
  which agents are alive. That half is the PM's hands. Skip the cross-check and
  a dead verification goes unnoticed for hours while the ledger asserts it is
  working.
- **PM-side refusals (classifier blocks etc.) that alter a dispatch get one
  ledger line each** — a retro cannot audit what left no artifact.
- **A defect row's cited evidence is re-verified at dispatch** — before a rung
  is cut from a queue row, the PM (or the brief's first instruction) checks
  that the row's `file:line` still says what the row claims. A row can describe
  a defect that was fixed cycles ago; dispatch against it and the only net left
  is the builder's own verify-first discipline.
