# Building With an Agent Team: Methods, Standards, and Enforcement

*A portable account of a development system that shipped a production-grade platform with AI agents doing nearly all of the building — and what other teams can take from it, on any stack.*

This document describes how one team ran a continuous build loop in which a single persistent orchestrator directed disposable specialist agents, quality was enforced by a machine gate rather than by memory, and every lesson learned was pushed as far as possible into mechanisms that do not depend on anyone remembering them. The system was built on Django, but almost none of it is Django-specific; where a concrete example helps, it is drawn from that codebase and marked as an illustration.

The sections mirror what a team would adopt: **the methods** (how work is decided, dispatched, and verified), **the standards** (what "written correctly" means and where that is defined), **the enforcement** (the machinery that makes the standards real), then the learning system — how a mistake becomes a permanent change — and a short adoption path.

---

## 1 · The operating model

### One persistent orchestrator, disposable specialists

The only role that persists is a product-manager role: it owns the order of work, the ledgers, the reports, and the power to say no. Everything else — design, decomposition, building, verification, system auditing — is dispatched per unit of work to a fresh agent that does its one job and goes away. The orchestrator's hands are for reading, deciding, ordering, briefing, and correcting; **it never writes production code.** That is not a preference; it is the structural form of the system's one non-negotiable rule:

> **The agent that decides "done" is never the agent that built the thing, and the acceptance criteria are written before the code exists.**

Everything else in this document is logistics around that rule. The failure mode it prevents is subtle and universal: criteria written *after* an implementation produce a right-looking list unconsciously shaped to what the code already does, and a builder judging its own work produces agreement, not truth. Because the orchestrator cannot edit the application, it *must* dispatch — so independent verification happens by construction, not by discipline. For work too small to justify a team, the rule narrows but never disappears: **whoever builds does not decide done — one other agent, always, even for one line.** The miss that shaped it: a "one-line fix" built and verified by the same agent turned out to be a blast radius, a permission-model change, and a standards violation, caught only by luck.

The specialist roles, portable to any stack:

| Role | Owns | Never does |
|---|---|---|
| **Orchestrator** (persistent) | order of work, ledgers, reports, saying no | writes production code |
| **Design** | the shape of what the user sees — or, for a backend, the contract: resources, verbs, error bodies, event payloads | decides what gets built or when |
| **Engineering lead** | decomposition into small units, the module map, **the acceptance criteria** | builds the thing it just specified |
| **Builder** | the code, one unit at a time, gate green at each | judges whether the result is good |
| **Field test** | drives the real product as a user would and verifies against the criteria | fixes what it finds |
| **Surveyor** | reads the *system* — code, logs, config, the deployed box — and writes what it finds into the backlog, with evidence | fixes anything, sets priority, trusts a status document |

Field test and surveyor are deliberately separate instruments: driving the product finds the user-facing holes; reading the system finds the scope leak, the N+1 query, the backup that does not exist. Neither finds the other's class. A third instrument — a periodic **surface review** of one foundational interface at a time, with two lenses ("is it sound" and "can the fifteenth developer who never read the docs misuse it by accident") — catches what both miss: surfaces individually correct and structurally misusable. Every such review ends by asking *what rule or automated check keeps this class of defect closed forever* — the enforcement is the deliverable; the fixes are the byproduct.

### Know what the one rule cannot do

Verification against criteria is exactly as complete as the criteria — and a specification can be silent. Two independent adversarial verification passes once cleared a feature that a later code review found rendering user-authored text as HTML: no criterion had mentioned output encoding, so no verifier could have been wrong about it. The doctrine that followed: **reviews, sweeps, and field tests are not redundancy with verification; they cover the class verification structurally cannot reach.** And when a review finds something verification passed, the finding is a *criteria bug* — the missing criterion is written into the brief template, not just the fix into the code.

### Cycles anchor on a user's job, not a feature

The unit of work is a job the user has, named the way the user would name it, sized to land inside one working session (one that cannot is two). Each cycle runs a fixed sequence: **frame** the job and its cost → **watch** an agent drive the *current* build as the user, before anything is designed (output: a friction log where every item is a reproduction — *a cycle never starts from an opinion, the orchestrator's included*) → **design**, always with alternatives and why they lost, every decision expressed as a buildable value, never an adjective → **decompose** into units with acceptance criteria written before the code exists → **build** → **prove** against the criteria verbatim → **close**, then harvest the misses (Section 5).

The strategy that orders the backlog: **optimize how often the user team can drive the real product.** Anything built that no one can yet exercise is inventory, not progress — a merged branch nobody can sign into has moved a file, not the product. Work that unblocks driving outranks work that is merely valuable. And "done" is ultimately what a user-persona verdict says, not what the criteria say: criteria prove the thing was built as specified; done is a persona doing their job and it being better than before.

Two practices make the driving honest:

- **Drive from an empty database, never from seeded fixtures.** The most expensive class of defect is the one seeded data hides: a field every fixture already carries, so nothing downstream is ever seen empty. A user team that starts from zero finds that class on day one; one that starts from the demo fixture never will.
- **Drive through machine interfaces before the UI exists.** *(Illustration:)* in this codebase every capability is reachable through several "doors" — REST API, an AI-agent tool interface, websockets — all calling one service layer, so the user team can drive a capability the moment it merges, without waiting for a screen; and because the doors share the service layer, **a disagreement between two doors is itself a finding.** The portable idea: give every capability a machine-drivable surface from day one, and make cross-surface consistency a checkable property.

### Isolation, parallelism, and surviving a crash

Running many agents against one codebase concentrates risk at shared state. The rules that keep it safe are structural, not behavioral:

- **Two agents never share a checkout.** Every builder works in its own isolated working copy with **its own database**, derived automatically from the checkout, so its tests measure its own tree and nothing else. This removes, by construction, the two failures shared checkouts produce: a commit landing on another agent's branch, and a test run measuring a tree it did not claim to.
- **One agent per module at a time.** A unit of work names the module it owns; two parallel units in different modules are legal, two in the same module never are. *(Illustration:)* in Django the collision surfaces as a migration merge conflict — and the system treats that conflict not as something to resolve but as **the plan announcing it was wrong**: the builder stops and reports an ordering failure rather than patching it.
- **Parallelism is argued, never assumed — and it is the default.** Before sequencing anything, a dependency pass asks of each leg: what does it read, and is that input frozen? Do its outputs certify anything later work would invalidate? The plan states an independence argument per parallel leg; **a leg whose argument cannot be stated serializes.** Real parallelism is independent modules and enumerable sweeps; a "parallel" pair touching one shared core module is a serialized pair wearing a concurrency map.
- **Write-first, so a crash is cheap.** The orchestrator assumes its session can die without warning. The dispatch ledger row is written *before* the dispatch goes out; the cycle plan — the one artifact whose loss cannot be repaired, because re-deriving criteria after reading the implementation destroys the property that makes them valuable — is committed the moment decomposition returns; decisions are recorded *with their rejected alternatives*, because no amount of code-reading recovers a reason. When a session did die mid-wave, the loop resumed hours later with zero work lost, because the plan, ledger, and worktrees were already on disk.
- **Liveness is read from the running system, never from the ledger.** The status artifact is precisely the thing that is wrong when there is a stall.

### Where a human enters

The loop pauses for humans only at hard stops: real money, real people's inboxes, interactive credentials, irreversible acts on real data, and changes to the ship definition. Everything else runs without asking; the interface between stops is legible reports, not consultation. Every question to the owner is decision-shaped with a recommended default — "A or B; we recommend A because Y; A happens unless you say otherwise" — because an open question outsources the thinking the orchestrator exists to do.

---

## 2 · Rules of evidence

The whole system runs on claims made by agents about work done by agents, so the rules of evidence carry more weight than in a human team, where shame and reputation do some of this work. Six rules, each bought with a specific failure:

1. **Every status claim names its artifact** — a file, a test, an endpoint, a click path. "Built," with nothing named, is a hypothesis wearing a status. This is also the anti-drift rule: a claim that names its artifact becomes *visibly unsupported* when it rots, instead of merely wrong. (A status table here once disagreed with the code in eleven places — for the third time — before the rule was adopted.)
2. **A finding is a reproduction, not an opinion.** Request and response, or a click path, or it did not happen. The sharpest corollary: *a schema that permits something is not an interface that serves it* — inspecting a definition never substitutes for driving the behavior.
3. **The verifier tests the criteria, never the implementation** — and if a criterion turns out to be wrong, that is a finding *against the criteria*, recorded as such.
4. **Green-because-empty is not green.** A test that cannot fail proves nothing; a check whose scope matched nothing is not a pass — in this system it is a broken-enforcement error (Section 4). Two of three production interfaces were once broken while 597 tests passed, because the harness had silently substituted friendlier parts exactly where the breakage lived. The doctrine that followed: criteria about an interface must be provable **over the wire, with a real client** — a criterion satisfiable only inside the test harness is a criteria-writing error.
5. **Red-first.** Before fixing a defect, prove it exists: run the demonstration on the baseline, paste the actual failing output into the report (not a description of it), then build, then show the same probe green. A criterion that never went red may be unable to fail. Where feasible, prove both directions: sever the guard and show the failures appear; restore it and show them gone. One safety clause, paid for the hard way: **a destructive demonstration creates its own victim** — a scratch copy, a planted file — never material that existed before the work began.
6. **Deferred is written down as deferred, with the condition that makes it due.** "Production is stood up when a second customer is named." Silence reads as coverage; a deferral without a trigger is a sentence that makes everyone feel better.

Two disciplines sit under all six. First, criteria must assert **properties, not mechanisms**: "a permission row exists" passes while nothing can detect its absence. The test for every criterion is *what observable thing differs if this is false?* — and the criterion must state what its instrument returns in the *negative* case, because a check that answers the same whether or not the thing exists is a check that cannot fail. A criterion over a stateful flow enumerates the states it drives and names the ones it deliberately does not; the costliest verification miss in this system's history was a criterion that honestly went red and green — on the wrong member of the population, so the guarded path never actually ran.

Second, the recurring failure shape in any agent (or human) system: **a plausible mechanism, a real symptom, a confident wrong conclusion** — settled in minutes by looking at the artifact instead of the rendering. When a timestamp or an exit code surprises you, read the row, not the report. Its operational twin: **never pipe or filter the output of anything whose exit status you intend to trust** — `check | tail` replaces the check's exit code with `tail`'s. That lesson was written down and then recommitted twice by the person who wrote it down, which is why it eventually became a mechanism: the gate now *refuses to run* with a piped output. Prose does not hold under pressure, even the author's.

Finally, the standard extends to instruments themselves: **an instrument must be able to distinguish "nothing is wrong" from "I could not look," and must fail loudly in the second case.** Three reporting tools were found in one week that silently degraded to a healthy-looking answer when their input was missing or unreadable. An instrument that cannot see must refuse — because silence reads as health.

---

## 3 · The standards stack

Standards live in three layers, deliberately separated so each can be loaded by the role that needs it and none drifts into the others: **what shape and why** (architecture), **how to write it** (code conventions), and **how to execute a unit of work** (execution discipline). The layering has a practical payoff: a dispatch brief shrinks to *territory + a pointer to the criteria + what is unusual about this unit*, because everything generic lives in a standard the agent loads.

### Layer 1 — Architecture rules: numbered, owned, settled

Every architectural standard is a **numbered rule with a one-sentence statement**, and every rule has exactly one owning document. *(Illustrations from this codebase:)* "no business logic in signal handlers — services own writes," "HTTP vocabulary never appears below the interface layer," "workflow code is deterministic — all I/O lives in activities," "every list endpoint carries an asserted query budget at seeded scale." The specifics are Django's; the pattern is not: each rule is a closed, checkable sentence, numbered so criteria and reviews can cite it by id, and paired wherever possible with an automated check (Section 4).

Settled decisions are recorded as decision records with a fixed anatomy: **context → decision → rejected alternatives with why each lost → the condition under which to revisit.** The rejected-alternatives clause is load-bearing — a successor who does not know why an approach was rejected will rebuild it. Settled decisions are not reopened; a product that must diverge records the divergence, with the reason, in its own copy.

One meta-rule governs all documentation: **one authority per question, and the authority never counts or tracks.** Anything that can change without the document changing — a test count, a duration, a list of what was built — does not belong in a guidance file, because it goes stale invisibly. The document points at the thing that knows: the schema is read from a live introspection command, never from prose; timings are printed by the tool that measures them, never written into a header. (The gate script's header carries the scar: a hand-written duration, true when written, wrong once the suite grew — replaced by a printed measurement of the tree in front of you.)

### Layer 2 — Code conventions as wrong-form / right-form pairs

The code-conventions standard exists because of a documented failure mode of AI coding agents: **plausible-but-wrong code** — outdated APIs, logic hidden in event hooks, N+1 queries, guessed schemas, I/O inside code that must be deterministic. It does not describe good code in the abstract; **every rule shows the wrong form and the right form side by side**, as compilable code, with a comment naming why the wrong form is wrong. An agent shown only the right form will still emit the plausible wrong one; an agent shown the pair recognizes its own output in the wrong column. The document also carries an explicit **outdated-API blacklist** — the patterns a model will plausibly emit from stale training data, listed by name. Every builder loads this standard before writing a line, every time; it is summarized nowhere else, precisely so it cannot drift from itself.

### Layer 3 — Execution discipline

How a unit of work is executed is itself a standard, loaded first by every builder:

- **Step zero is an instrument, not a checklist.** One command resets the working copy to the current baseline, provisions the environment, prepares the checkout's own database, and dumps the live schema — printing what it did and exiting with a verdict. These were four hand-steps done from memory by every builder every time (30–50 % of a short unit's wall clock), and hand-steps done from memory are also hand-steps *skipped* from memory: whole batches of builders were once cut from a stale baseline at once. The instrument also *refuses* to reset when the tree holds uncommitted work — a refusal is never worked around by hand.
- **Territory, and flag-and-hold.** The brief's file set is the territory. A need outside it is flagged — the file, the exact change, why the criteria need it — and *not edited*. A brief claim the builder's evidence disproves is reported with the evidence; disproving the brief is encouraged and has repeatedly been a unit's most valuable output ("whoever builds does not decide done" earned its corollary: *whoever briefs does not decide true*).
- **Stage explicit paths, never "add everything."** The staged set is the claim about what changed.
- **Commit at every boundary.** A commit is not a claim the work is proven; it is a claim that *this is what was written* — so a killed session loses minutes, not the unit.
- **Never pipe the gate; run long commands in the background writing to a file, and read the file** — a stream stall then costs the rendering, not the work.
- **Kill only your own child processes, by pid and parentage, never by name** — a kill-by-name from one checkout has killed another agent's test run twice.
- **The report contract.** First line: *still working / done, stopping / stuck on X*. Then: the actual branch name pasted from the tool (never remembered), red-first evidence pasted, per-criterion status each naming its proving artifact, **every deviation from the brief or the standards, none silent**, everything the brief got wrong (with evidence), declared blind spots, and a cleanup census — everything created that outlives the report is a leak.

---

## 4 · Enforcement: the gate, canaries, and honest verdicts

### The three-tier gate and its exit contract

One script is the quality gate, in three shapes with one exit contract:

| Tier | Runs | Who runs it | Cost |
|---|---|---|---|
| **fast** | static analysis only: lint, strict types, import contracts, the house rules, migration-graph checks — no database, no network, no test suite | the pre-commit hook | seconds |
| **loop** | fast + deployment-config checks + a secrets scan over the changed files + **one** test pass | the builder, once per unit of work | a couple of minutes |
| **full** | loop + the supply-chain/audit leg + **two** test passes under one random seed + the canary self-test + end-to-end checks; **records a verdict keyed on the tree hash** | the pre-push hook | minutes |

The exit contract is the part worth stealing verbatim:

> **Exit 0 clean · 1 violations · 2 enforcement broken — and 2 outranks a pass.**

Exit 2 is the category most gate designs are missing: it does not mean "your code is bad," it means "the machinery that would have judged your code cannot be trusted" — a check that could not fire, a scope that matched nothing, a self-test that failed, a consistency error, an *unknown flag*. That last one matters: a mistyped flag must be a loud error, never a silent fall-through to some default behavior that the caller then misreads as the check they asked for. Builders are told explicitly: exit 2 means stop and report; do not work around it.

Two design details in the full tier carry portable reasoning. The two test passes run under **one shared random seed**, so the only difference between them is what pass one left behind — a pass-2 failure can only mean state leakage, never a different ordering. The per-unit tier takes a *fresh* seed every run, so ordering couplings are discovered continuously at the most-attended tier instead of one at a time, months apart; the seed is printed, so a red order replays exactly.

**Gate economics are stated, because nobody works them out unprompted.** The builder runs the loop tier per unit and never the full gate by hand; the full gate is deterministic on a tree, so it runs once, at push. When this discipline slipped, the tax silently reached a third to a half of every unit's wall clock before anyone measured it.

### Rules as data: canaries, floors, negatives, declared blind spots

The house rules are not scattered through scripts; they live in **one data file**, each rule carrying: an **id** and **statement** · the **check** that implements it · a **scope** that is *derived by the check, never typed by hand* (what appears under scope is only allow-lists and exemptions, each with its written reason) · **floors** · **canaries** · **negatives** · and **does_not_cover**. Four of those deserve definitions, because together they are what makes the gate honest:

- **Canaries** — planted violations, injected through the rule's *real* scope at self-test time, each expected to fire for *its* rule. **A canary that does not fire is exit 2, not a pass.** The principle: *every check must demonstrably be able to fail; a check that cannot fail is decoration.* The self-test plants into the real tree (restoring afterward, whatever happens), because a canary proven against a copy proves the copy — and it refuses to run when the tree is already dirty under a plant path, because then it could not tell its own plants from your work.
- **Negatives** — known false-positive shapes, kept forever as regressions. A negative that starts firing means the rule got greedier, and that is caught the same run.
- **Floors** — the minimum population the check must have matched (files scanned, models found, routes seen). Below floor, the scope is *unbound* and the run is exit 2: this is the mechanical form of "green because empty is not green."
- **does_not_cover** — every rule *declares its blind spots* in a sentence. This turns automation's limits into a map: the declared blind spots are precisely where human-shaped review has the highest yield, and the surveyor works that list on rotation. What irreducibly stays with review — right shape, wrong content — is written down as a blind spot on the nearest rule, never left implicit.

Even the self-test population is protected: each rule *records* how many canaries and negatives its plan holds rather than counting them — a total counted from the same file it checks cannot notice that file shrinking; a deleted canary would take its own expectation with it and the run would stay green.

Three more mechanisms round out the engine:

- **Overrides are visible, reasoned, and counted.** A rule is suppressed at one line only by an inline marker carrying a reason, on that line or in the contiguous comment directly above — so an exemption cannot drift onto code nobody thought about. Every override is counted and printed as a standing section on every run; an override with no real reason is itself a violation.
- **Ratchets** let a new rule land against an existing backlog: the violation count is recorded per class and **may shrink but never grow** — at or below the number, findings print as notes; one over, and every finding names the growth. Shrinking never tightens the number by itself; a human commits the lower number in a diff somebody sees.
- **Closed questions over discoverable populations.** Every check is phrased as "does anything in this enumerable population do X" — never as recognition of an open set of spellings, because open-set checks get walked past without malice. A concern that cannot be phrased as a closed question becomes a declared blind spot with review pointed at it, not a mushy check.

Two boundaries are drawn on purpose. There is **no LLM leg in the gate** — the gate is deterministic on a tree; model judgment lives in the loop's review stages, which are honest about being judgment. And the **warn tier is almost empty**: the default is block-with-narrow-scope; the only warn-shaped mechanism is a budget with a rising floor (for heuristics like function length), which fails on *growth*, never on existence.

### The tree-keyed verdict ledger

The full gate's verdict is a property of a **tree**, not of who asked for it. A complete green full run records the content address of exactly what it measured (the working tree — tracked plus untracked-unignored files — hashed through a temporary index); the pre-push hook consults the ledger and does not re-measure a tree already proven green, so a second run of the same bytes is free by construction. Three properties keep the ledger honest, and they are the portable design:

1. **The key is what was measured, not what was committed** — so a verdict earned before a commit legitimately vouches for the commit after it.
2. **Only a complete green full run earns a verdict.** A red run records nothing (it should re-explain itself every time); exit 2 records nothing and never can; partial tiers never record — a partial run must never vouch for a tree.
3. **The verdict names a tree that still existed when the run ended** — measured at start *and* end; if agents edited the checkout mid-run, the pass still prints but earns no carry-forward.

The trust class is stated in the file itself: this is a local ledger an agent could forge a line into, exactly as a hook bypass is one flag away. The hooks were never a security boundary; CI re-runs everything from a fresh checkout. Guards here stop casual drift, not sabotage (Section 5).

The ledger also changes what verification costs downstream: the verifier's brief *prohibits* re-running the gate — it checks the ledger once for a green verdict on the exact tree under test, then spends all its time driving the criteria through real interfaces. Re-running a deterministic gate is not a second opinion; it is the same opinion bought again. The separation of powers survives: the machine's recorded verdict decides *green*; the verifier decides *meets criteria* — and its evidence is the product under its own hands, which no gate run ever was.

One later refinement matters to teams maintaining a shared platform under many products: the test suite was **partitioned**, so a downstream clone can skip the platform's own tests when a banked green verdict exists whose key still covers everything that portion of the suite reads. The load-bearing choice is the fail-safe direction: anything not positively in the recorded platform set **always runs**. The portable lesson: cache verdicts keyed on the complete input closure of what was verified, derive that closure honestly (a driven audit found the naive closure missed config files the tests read off disk), and make the failure mode "ran tests unnecessarily," never "skipped tests wrongly."

---

## 5 · The learning system

Recording a lesson is not integrating it. The system's answer is a **promotion ladder**: every miss is pushed as high up as it will go, and where it landed is written down.

| Level | Mechanism | Reliability |
|---|---|---|
| **1** | the machine refuses — a rule with a canary, a gate leg, a database constraint | total |
| **2** | the default changes — the wrong path stops existing | total |
| **3** | the artifact carries it — a clause in the brief template, at the point of use | high |
| **4** | a checklist | decays |
| **5** | prose in a document | only for what you look up deliberately |

The test for any placement: *if this recurred tomorrow, would it be caught without anybody remembering?* That is exactly what a canary asserts.

But the governing constraint is that **promotion is governed by settledness, not importance.** Higher is not better. A rule still being learned belongs at gate-or-test level, where relaxing is cheap and violations stay *visible* — that visibility is how you discover the rule was too tight. A sibling system learned this the hard way: a hard, top-of-ladder enforcement of a not-yet-settled rule broke legitimate record creation nine layers deep, because the real exception was unknowable in advance and the enforcement level made it inexpressible. A level-1 enforcement of a wrong rule is worse than a level-3 enforcement of it; only settled rules with enumerable exceptions earn the top of the ladder. In this system's late history the doctrine became mechanism: a new rule is *born disabled and loud*, measured against the live population, and flipped on only when the measurement is clean.

Two companion rules keep the ladder from bloating the system:

- **Prune on promotion.** When a learning reaches level 1 or 2, the prose about it is deleted. Every promotion makes the guidance file *shorter* — an unbounded guidance file is one nobody reads, which is how a documented warning fails to prevent the mistake it documents.
- **A new discipline with no artifact will be skipped under load.** A ratified process step lived in prose and was skipped on three of its first four opportunities — by the person who ratified it. The fix was to give it a required field in the ledger, so its absence is visible in a file rather than invisible in a habit. Give every new discipline a field, a file, or a check.

### The miss log and the friction discipline

At every cycle close, five minutes go to one question — never "how did the cycle go," always: **what did we believe that was false, and what would have caught it sooner?** One line per miss, and every entry must end in one of exactly three outcomes: **a rule with a canary**, **a recorded ruling**, or **accepted, with the reason**. An entry that ends in none of those is a note, and notes rot.

Running beside it, the friction discipline: any friction costing more than a minute gets **one logged line at the moment it happens** — classified as *violation* (someone broke a standing rule), *environmental* (the host, the network), *process* (the method itself cost the time), or *inherent* (the work was genuinely that expensive) — and then back to work. Capture, never analysis; a capture that pauses the loop costs more than what it records. **The second strike of the same friction in one cycle is evaluated immediately**, through one question — *what would a guard against this protect, and is that thing real today?* — and if it clears, a small unit of work lands the guard. Every few cycles, a guard retrospective prunes the population: a false-positive audit, deletion of guards that have never fired and protect conditions that no longer hold, and a latency budget for the whole set — because a guard population that only grows becomes the friction it was built to remove.

The posture behind every guard: **guards stop casual drift, not sabotage. Assume good intent.** A guard designed against an adversary is expensive, brittle, and insulting to the agents it wraps; a guard designed against forgetting is cheap and usually right.

The same question — *what does this expense protect, and is that thing real?* — is also asked in the other direction, at planning time, of every expensive or risky piece of work. The distinction that prevents over-learning: *cutting a known flaw* trades quality for speed and is refused; *declining to build an instrument for a condition that does not hold yet* is a falsifiability question and is negotiable — recorded as a cut, with the trigger that makes it due.

### Loop health is a measured scoreboard

Whether the process itself is healthy is not a feeling; it is a table — one row per completed cycle, with columns like *criteria met/total*, *the user-persona verdict (verbatim, plus a token from a closed vocabulary)*, *misses promoted to levels 1–2*, *debt drawn*, *debt added with its trigger*. A script evaluates the last two completed rows and exits 1 when two or more stop signals hold — and, in keeping with the house exit contract, **exits 2 when the scoreboard cannot be read**: a missing file, a blank column (a blank counts as a miss, never a zero), fewer than two completed rows. A loop that cannot measure itself is in no position to claim it is fine. The health checker is itself canaried — fed deliberately bad rows and expected to fail, an empty board and expected to refuse — because a check that cannot demonstrably fail is decoration, for checks on the loop exactly as for checks on the code.

The stop signals worth watching in any agent loop, because the failure is invisible from inside: outcome measures that do not move while cycles keep completing; a miss log that stops producing promotions (the retro has become ceremony); cycles passing their criteria while the user verdict does not improve; and — the sharpest instrument, easiest to miss — **nobody overrules the orchestrator any more**. A delegate that overrules the orchestrator and is right is the method working; a loop in which nobody is ever wrong has stopped checking.

### Drift discipline

Drift — status tables disagreeing with code, guidance claiming stale counts — is the *characteristic* failure of an agent-run repository, not an occasional lapse. Every cycle therefore ends with a de-drift step: find what this cycle just made false and fix it now, while you still know what changed; prune the prose of anything just promoted; kill duplicated authority (two documents answering one question is drift with a countdown on it — one defers or one dies). The durable fixes are structural: every status claim names its artifact; one authority per question; and **prefer a check to a sentence** — a number in prose drifts; a number asserted in a test cannot.

---

## 6 · An adoption path

Taken whole, this system is a lot. It was not built whole; it accreted, one paid-for lesson at a time. The order another team should adopt it in:

**1. Take the one rule first, and take it structurally.** Whoever builds does not decide done — one other agent (or person), always, even for one line — and acceptance criteria are written before the code exists, by someone who will not build it. If your orchestrator *cannot* write production code, the rest happens by construction. Add the evidence rules that make it bite: every status claim names its artifact, every finding is a reproduction, red-first on every fix.

**2. Then the gate contract.** Three tiers (seconds at commit, minutes per unit, full at push with a tree-keyed verdict ledger) and — above all — the three-valued exit: clean, violations, *enforcement broken*, with enforcement-broken outranking a pass. Give every check a canary that must fire and a floor below which it refuses to claim anything; keep false positives as regression fixtures; make every check declare what it does not cover, and point human review there. Never pipe the gate. This is the piece that converts standards from culture into physics, and none of it is stack-specific.

**3. Then the ladder.** A miss log where every entry ends in a rule, a ruling, or an accepted-with-reason; promotion by settledness, not importance; prose deleted on promotion; a friction log with a second-strike trigger; and a health scoreboard the machine reads, that fails loudly when it cannot be read. This is what makes the system get better instead of merely bigger — and what makes it survive the departure of whoever built it, because nothing important depends on anyone remembering.

The through-line of all three: **move every judgment you can from memory into mechanism, prove every mechanism can fail, and write down — as a first-class artifact — what each mechanism cannot see.** Teams do not drift because they are careless; they drift because prose does not hold under pressure, even its author's. This system's most repeated lesson was exactly that, learned three times by the person who first wrote it down, and settled only when the gate learned to refuse.
