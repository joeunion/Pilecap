# Dispatch contracts

Five roles. Each brief below carries the clauses that were **paid for** — the
ones that, when missing, produced a wasted round. Each says what it protects,
so a PM can tell an obsolete clause from a load-bearing one.

## Universal clauses

- **"Return the report only. Write no files, change no code."** Without it an
  investigator starts fixing, and you lose the finding in a diff. (Omit for the
  development brief, and for the surveyor's queue rows — those are the two
  roles whose job *is* to write.)
- **"Every claim names the file that proves it."** Turns opinions into findings.
- **"A criterion that names a mechanism quotes the `file:line` the writer read."**

**Every agent's scratch files live under its own subdirectory** — `<scratchpad>/<rung-or-role>/` for the box wrapper, the logs, the probes — never at the scratchpad's root: the scratchpad is one directory per SESSION, shared by every sibling agent, and two agents dispatched in one message will write `vbox.sh` over each other (2026-09-28: a verifier pushed a sibling's tree onto its own box). The brief names the directory.
  The PM's own miss, six times in one cycle (2026-09-27): a README "standard"
  that did not exist, "shellcheck included" in a gate with no such leg, a note
  a function never writes to stdout, a banner a rung's own files make
  unreachable. A mechanism the writer cannot cite is a hypothesis, not a
  criterion; the verifier's standing question stays — *was this criterion
  checkable as written?* — and its answer is a finding against the criteria.
- **"Prefer precision over completeness where they conflict."**
- **State what is already decided and must not be re-argued.** A brief that omits
  the settled constraints gets them re-litigated, at full cost. Point at
  `architecture.md` and `design-agreements.md` by name.
- **"Read the schema with `uv run python manage.py introspect`; do not guess
  it."** Any role that touches models, schemas, routes, tools, consumers,
  workflows or settings.
- **"The first line of your report says whether you are still working."** *Still
  working* · *done, stopping* · *stuck on X*. "Final state" means leaving.
- **"Run anything long in the background with output to a file; read the file
  when it finishes."** The anti-stall clause, in every brief: a stream stall
  then costs the rendering, not the work, and recovery is reading the file
  from its last position. Its presence recovers stalls that would otherwise
  cost a rung; its absence is how a stalled agent gets abandoned with its work
  intact and invisible.
- **"Kill only your own children — by pid, `pkill -P`, or parentage; never
  by name."** `pkill -f pytest` from one checkout kills another checkout's
  gate, and it has done so more than once; other agents' suites and gates run
  on this machine at all times. `scripts/kill_mine.sh` is the checkout-scoped
  form.
- **"The credential kinds a door accepts are population members."** A
  criterion over a door enumerates session, bearer token, and any
  query-parameter form the door reads. Criteria that drive session sockets
  only will certify a door whose bearer-token path has never once resolved an
  acting hat.
- **"Clean up at return — everything you created that outlives your report
  is a leak."** A verifier's clone is torn down (directory, its derived
  database and `_perf`/`_hp` worlds via `scripts/db_sweep.sh --sweep` from
  inside the clone, any compose stack it started); a builder tears down every
  laptop stack it brought up, drops the `_perf` world it seeded
  (`db_sweep.sh --sweep --perf`), and leaves only its worktree and its own
  database for the PM's merge ritual. The report pastes the census. The cost
  of omitting it is not theoretical: a wave of verifier clones each seeding a
  sub-gigabyte perf world and a multi-gigabyte telemetry stack will fill the
  disk, wedge Docker and stall every concurrent rung. **"Leave the clone in
  place" is no longer a sentence a PM brief may contain.**
- **"A journey (composition) rung consumes proven ingredients only."** A
  missing or inadequate ingredient stops the rung — flag it, never inline a
  one-off primitive and never edit the ingredient from inside the journey
  rung; growing the foundation is its own phase-1 rung. (The build strategy:
  ingredients → journeys → fit-and-finish; paid for by a first product's
  rejected UI.)
- **A mid-flight amendment only half-lands.** If the brief changes materially,
  re-dispatch cleanly with the prior output carried forward — do not patch it.
- **An exhibit is written in the past tense, with the rung id that closed
  it.** A brief (or plan) quoting a defect as a live present-tense fact reads
  as an instruction to fix it again after it is fixed; the moment a rung
  closes it, every later citation says *was*, and names the rung. (Paid for
  in P15: three documents carried present-tense exhibits of closed defects.)

---

## Field test — stage 1 (WATCH) and stage 6 (PROVE)

Drives the real product as the user: the browser as a person would, where the
product has one, and the machine doors — **REST** (`/api/v1/`), **MCP** (`/mcp`)
and **sockets** — as an agent would (the other two doors, webhooks and
workflows, are driven *through* these and read in the outbox and the Temporal
UI). All three call the same services, so **a
disagreement between any two of them is itself a finding**: a capability one
door serves and another cannot, a shape that differs, a socket push the API
never accounts for. **For a backend-only product the three doors are the whole
field test**, driven from an empty database with real values a user would type,
and that is not a lesser test. Where the criteria touch a workflow, the brief
says the worker must be up (`./scripts/worker.sh`) and names the Temporal UI as
the place a run's state is read, not inferred.

**WATCH brief must include:** the persona and their credentials · the
surfaces, endpoints, tools and channels in scope · *"start from an empty
database and enter what a user would enter — seeded fixtures hide the class of
defect we most need found"* · *"trace the realistic path end to end and name
what the user must do by hand that the system already knows"* · **"be
skeptical; check the code, do not trust comments or docstrings"** · *"where
does the user hit a wall — a control, endpoint or tool that does nothing, a
state with no next action, a required field with no source"*.

**Door criteria are proven over the wire.** A criterion about a door (REST,
MCP, socket) must be verifiable with a real client — curl, a token, a socket —
never only through the test client, which silently disables CSRF and swaps the
channel layer. A criterion satisfiable only inside the test harness is a
criteria-writing error: say so and stop. This is the clause that catches the
most expensive shape there is — doors broken in production form underneath a
fully green suite, because the harness substituted friendlier parts exactly
where the breakage lived.

**The batch, when the brief carries more than one rung to verify** (the standing
rule in `SKILL.md` § The loop, owner 2026-09-15): the rungs listed in order,
each with its own criteria pointer and its own baseline for the red; ONE clone,
ONE consult (a lookup of the banked key, never a `--loop`); a verdict PER RUNG (a NOT MET blocks that rung alone);
the cleanup census once. A security fix or a wire-driven door rung is never
batched.

**PROVE brief must include:** the acceptance criteria **verbatim from stage 4**,
and *"verify against these criteria, not against what was built; if a criterion
was wrong, that is a finding against the criteria."* Through REST always,
through MCP and sockets wherever the rung touches them — and the same
capability through two doors where both exist, because the disagreement is the
finding; through the browser, desktop and phone, where the product has one;
plus one adjacent persona to catch what the primary path hides. **For a
release or a merge note, the adjacent persona is the PRODUCT'S PM at the fold:
read each actionable sentence as an instruction and plant it** — two of twelve
notes written from the code were false as written (2026-09-27: "delete every
`AWS_*` key" also deleted the pins a rule requires; "every other workflow is
yours" named a template-owned file), and only the plant showed it. And the
mirror lens, for every criterion over a stateful flow: *which state or
population member did this criterion NOT drive?* — an undriven live path is a
finding against the criteria.

**The verifier's first question, before any criterion:** *"Did the rung reuse
the roads the brief cited and add none? — `manage.py roads --json` on the
baseline tree and on the rung's tree, diffed: a job gaining a road the criteria
did not name, a `kept` entry the criteria did not name, or rule 84's ratchet
classes rising, is NOT MET before the first criterion is read."*
And the brief asks the verifier to *"say whether the rung kept the builder's
seven"* (`django-conventions`, the block of that title).

**A destructive plant builds its own victim on a COMMITTED tree** (builder and verifier alike): a plant that commits, resets or checks out — `git reset --hard`, `checkout --`, a scratch branch — runs only after the rung's own work is committed, and never against the tree the rung is being built in; a verifier-box rider (2026-09-16) lost every uncommitted edit to a `reset --hard HEAD~1` inside its own F.2 plant and rebuilt them from scratch.

**A brief names the mechanism, never a finding id, for anything the builder will write into a shipped file.** The archaeology census refuses finding ids in comments and drives; a rider brief that cites one invites the builder to write exactly that, and the hook reds the commit. Ids belong in the commit message and the ledger (paid 2026-09-16).

**A subagent never waits silently for more than five minutes.** The harness kills an agent whose stream shows no progress for 600 s ("Agent stalled: no progress for 600s"), and a Monitor or a `run_in_background` task produces none while it runs — three agents died twice in one evening this way (2026-09-16, STALL-1/2), one of them mid-self-test with its plants left in the tree. A long run (a self-test, a `--loop`, a drive set) is launched in the background and then WAITED FOR in foreground Bash polls of at most five minutes each (`for i in $(seq 1 18); do kill -0 <pid> 2>/dev/null || break; sleep 15; done; tail -3 <log>`), each poll returning output; a 35-minute self-test is seven polls. This supersedes "never end a turn with a run in flight" only in the mechanism — the agent still never ends its turn while a run of its own is alive.

**Against a real external system, explore first, then codify.** When a rung's proof is a real box, a real account or a real vendor, the loop's one-defect-per-iteration shape is the wrong shape: each field test costs a verify, a merge, a bank and a launch to find the NEXT line that fails. The first run is a HAND WALK on a kept box (`bake --keep`, `up`, or the vendor's console) with every fix and every command recorded as it happens; one codifying rung then lands the whole list with its drive cases, and the field test after it is the proof. The verifier-box lane paid six serial field tests (Tuesday to Wednesday night) for a recipe that ran 14/14 in two minutes once walked by hand (2026-09-17; the owner: "get it running by hand once, find all the errors in one drive").

**The clone's own dev database is dropped by its exact derived name, as the LAST step** — `db_sweep.sh --sweep --hot-path --perf` from inside the clone drops the test, hot-path and perf worlds and DELIBERATELY keeps the checkout's live database; the verifier then drops that one by the name the sweep's scope line printed (`db_drop <name>` or the compose `psql` drop), and never reaches for `--all` (machine-wide — every checkout's databases; a verifier killed it at the confirmation on 2026-09-16, nothing lost).

**Every log the verifier writes is named after its rung** (`loop-v-<rung>.log`, `verify_start-<rung>.log`, never `verify_start.log`): several verifiers share one session scratchpad, and V-G9b (2026-09-15) read back V-PR1's `verify_start.log` as its own — an unqualified name in a shared directory is a transcript that silently belongs to someone else.

**When the clone lives on a verifier box** (boxes are per PM choice, the brief
says which): the brief names the instance id, and `scripts/verifier_box.sh
run|fetch <id>` is the ONLY way to touch the tree — the agent stays on
this machine. `verify_start.sh --no-loop` runs on the box from `~/pilecap`, its log fetched
into the scratchpad and cited by local path; the ledger cell is the `loop:` line
read off that log, and nothing on the box runs `--loop`.
*If `run` prints `box reclaimed`, stop and report `stuck on: box reclaimed` —
the verdict is lost, never red; the PM re-ups and re-dispatches.* The cleanup
census names the box: `down <id>` unless the brief says the reaper takes it,
and `census` afterwards showing nothing of yours.

**And three demands the PROVE brief makes of the verifier's own hands**, because
evidence lifted from a builder's report is a claim to re-derive, never an
artifact — the builder deciding done by proxy:

- **RED re-measured on the BASELINE.** Reproduce the builder's red yourself, on
  the baseline tree, in a scratch worktree or clone
  (`git worktree add <tmp> <baseline sha>`) and **never by `git stash`** —
  agents do not stash here (the standing rule, bought by F1b's shared-stash
  race), so the sibling's "stash or checkout" lands here as *checkout only*.
- **The canary shown red BY NAME** — the drive case name, or the planted
  `file:line`, pasted from your own run. "The red reproduces" is prose; the
  named failure is the artifact.
- **The drive on the verifier's own pair** — the verifier's own clone and its
  own derived database, which is exactly what `verify_start.sh` exists to
  build. A drive run against the builder's transcript has verified a story.

**And the prohibition, pasted in verbatim — this clause is the brief's, not a
paraphrase of it:**

> *Build your clone with `./scripts/verify_start.sh <branch> --no-loop` and read its `consult:` line: `HIT` means the union is the builder's banked tree (or that tree plus prose); `MISS(code: …)` names the paths main gained by code after the fold point. Copy the line into your `loop:` cell. **Do not run `./scripts/check.sh --loop`, `test.sh`, any suite or the full gate** — the builder's bank is the measurement and a verifier that measures again has made a criteria error; if a criterion asks you to, say so and stop. Read the committed delta against every criterion by hand: re-run each planted RED on the baseline and the head, open every cited line, run the territory census and the seven, and drive the doors the criteria name. Start reading at the builder's `committed <sha8>` signal; its loop may still be running — your verdict names the commit, not the loop.*
>
> *Your ledger row carries the result as one typed cell, the `loop:` line
> `verify_start.sh` prints under its `consult:` line, copied as printed —
> exactly one of four: `loop: hit` (a loop row names the union's tree),
> `loop: docs-only reuse` (main's delta since the fold is docs-only and a row
> names the branch tip's tree), `loop: miss(code: <a8>..<b8>)` (main moved by
> code after the fold point; the `consult:` line names the paths) or
> `loop: miss(no-ledger)` (no loop row names the tree) — read off the line,
> never inferred, and with no seconds: the lookup prints none.*

Why a cap rather than a preference: the gate is deterministic on a tree,
so re-running it is not a second opinion, it is the same opinion bought again —
which is why the consult is a lookup and a miss is recorded rather than re-run.
The separation survives intact: the builder still never decides done. A
machine's recorded verdict decides *green*, the verification decides *meets
criteria*, and its evidence is the product under its own hands, which no gate
run ever was.

> Warning worth repeating in the brief: a green suite is not a drivable
> product. Green test layers can coexist with an endpoint that refuses every
> real request and a flow that reports a refusal as an acceptance.

## Design — stage 2

**Must include:** the register in the owner's own words · the hard constraints
(tokens, accessibility floors, touch targets, icon set, licence limits) ·
**everything already rejected, with what each rejection taught** · the settled
identity from `design-agreements.md`.

**And, load-bearing:** *"express every decision as a buildable value — hex, px,
weights, ms, cubic-bezier, enough SVG description to draw. Prose adjectives are
unusable."* A direction described in adjectives cannot be compared with another.

For a backend-only product the design stage designs the **contract**:
resources, verbs, status codes, error bodies, pagination shape, the schema
every door shares, the events the change emits and their payloads, which of it
is exposed as an MCP tool. Same rule — every decision as a buildable value (a
path, a field list, a status code, an example body, an event name), never an
adjective.

Ask for **alternatives and why they lost**, not a single answer. If two options
are siblings, say so and demand a third that breaks the family resemblance.

## Engineering lead — stage 4

**Never the agent that then builds it.** The brief must open with:

> *"Your job is stage 4 only: decompose into rungs and write the acceptance
> criteria. Do NOT write or modify production code. Your criteria go to a
> different agent to build against and a third to verify — which only works if
> they exist before the implementation does."*

**Must include:** *"load `.claude/skills/django-architect/SKILL.md` before
decomposing, and cite the rules you applied — by id — in every criteria set"*
(it is the architect's rulebook: boundaries, the service contract, the doors,
the deliverables; house rules 11–26 are its gate-enforceable subset) · what has
already happened and what is already in the tree ·
the constraints that are not negotiable (`architecture.md`) · known traps ·
the enforcement conventions (canaries, floors, where a house rule is defined —
`quality/rules.yaml`) · **the app map**, which the lead owns, and the
introspection output for the apps in scope · *"the roads the rung REUSES, one line per job
the rung touches, cited as `job · import` from `manage.py roads --json` on the
baseline tree, and the statement that the rung adds no road — or names the job
whose road it adds, with the marker's site as a criterion."*

- **Every criterion names its sites (S5, owner 2026-09-18).** A criterion
  that says "the sixteen `require` literals in `apps/accounts/services.py`"
  makes the builder find them; the I8 build spent 44 of its 104 shell calls
  and half its 33 minutes finding what the lead already knew. A criterion
  names each site as `file:line` on the baseline sha (a range where the
  sites are contiguous), the expected count, and the anchor text the
  builder can assert on before editing; the plan's rung section is the
  criteria pointer and the brief cites its line range, never the whole
  file. A builder that greps to find a site the criteria did not name
  reports it as a finding against the criteria in its report's friction
  section. Measured: turns and tool calls per build, against I8's 201 and
  125 (the plan's SPEED PROGRAM, S5).

**A frontend rung whose element class has no pattern-book entry is refused
at DECOMPOSE.** The lead reads `docs/product/design/patterns.md` and the
product's drawer beside it before decomposing any rung under `frontend/src/`;
for every element class the rung draws, the criteria cite the entry by section
and its instrument by file (house rule 63 guarantees the file exists). A class
with no entry is not decided in the criteria — the rung is returned to DESIGN,
which writes the entry and lands its instrument first. The verifier's brief on
such a rung carries the book's mirror-pass clause (§27).

**The one demand that has failed most often.** For **every** criterion, require:
*what observable thing differs if this is false?* Criteria that assert a
**mechanism** rather than a **property** pass while the property they meant to
protect goes unguarded — "the tests stay unchanged" (which forbids a refusal
getting stronger), "a permission row exists" (whose absence nothing can detect),
"the handler survives a throwing call" (a harm unreachable because no call site
catches). **If answering the question needs a code path that does not exist,
the criterion is describing a mechanism.**

**And a brief never forbids a rule's own valve — it demands the reason.**
`# door:`, `# reach:`, `# authz:` and their kin are the declared escape a rule
was designed with, counted and printed; a criterion that bans one sends the
builder to fight the census instead of writing the sentence that justifies the
case. The case that bought this line, 2026-09-07: a criteria set forbade
`# door:` outright where rule 42's activity-only census made that valve the
remedy, and the builder met the census twice over instead. Every valve is
sited and reasoned in `quality/rules.yaml`; demand the reason in the valve.

**Name the instrument, and what it returns when the thing is ABSENT.** A
criterion may not say *"`X` reports true"* without stating what `X` answers in
the negative case. A check that returns the same value whether or not the
thing exists is a check that cannot fail, and it has been written into
criteria before. For this repository that means: a criterion citing
`assertNumQueries(n)` says what n is and why; one citing an endpoint says the
status and body for the absent case as well as the present one; one citing
`introspect` says which key is expected to be missing before the rung.

**A criterion over a stateful flow enumerates the states it drives and names
the states it deliberately does not.** Red-first kills the criterion that
cannot fail; it cannot kill the criterion that goes honestly red and green on
the wrong population member. The shape to fear, because it looks like a pass:
a criterion over a consent wall that drives an already-suppressed row and
never a sending retry — the exact case the docstring claimed — so the wall is
certified while it has never once run on the retry path. The worked closure is
a test that **forces every state inside itself**. A criterion that cannot list
its states is a criterion over a population it has not looked at.

**A criterion carrying a "fails on today's code" half must specify that
demonstration precisely enough to reproduce** — which request, which data, in
which order, against **which baseline tree** (name it: `git rev-parse
HEAD^{tree}` at the rung's start). Otherwise a verifier cannot tell *the
demonstration is unreproducible* from *the criterion is wrong* — and those want
opposite responses.

**A destructive demonstration creates its own victim; found state is never a
demo target.** A builder proving a refusal, a sweep, or a kill path creates
the thing it destroys inside the drill — a scratch clone, a decoy world, a
planted file — and never points the destructive half at material that existed
before the work started, whatever the brief says about how safe it looks. The
canonical way this goes wrong is worth stating plainly, because it is nearly
comic and entirely real: the agent fixing a broom that dropped live databases
drops two live databases while demonstrating the warning about it.

**And the plant is sited where the partition can still see it.** A criterion
whose demonstration plants its canary in a **platform** app is invisible to a
run that skipped that partition: the plant lands inside the skipped half, the
drive looks at nothing, and it reports green. A planted-miss demonstration
therefore sites its plant in a **product app outside the touched closure** —
and the qualifying condition is **re-derived from `quality/partition.yaml` at
drive time**, never carried as a hand-written app list, which goes stale the
first time an app is added and turns the siting rule back into a comment. On
**this template's** tree the condition bites hardest, because every app
`partition.yaml` names is a platform app and the product set is empty: here
the drive **creates a throwaway product app** to site its plant in, and drops
it again in its cleanup census — the previous paragraph's own rule, applied to
the world the plant needed. *Prose today; **PART-1** promotes it where its
instrument lands — its "born non-vacuous" criterion plants exactly that
scratch product app (an `apps.py` directory absent from `platform_apps`), which
is the first thing here to make the siting rule checkable rather than
advisory.* How the closure itself is drawn, and which classes cover what, is
`docs/product/partition-closure.md` beside its skip table.

**For every rung the lead marks risky or expensive, the brief demands: the
cheaper alternative, what it gives up, and the condition under which the
expensive version becomes necessary.** The lead knows the alternatives; a
brief that does not ask gets a quote instead of a choice. A single such
question, asked in time, routinely dissolves a day of the most dangerous code
in the plan.

**Must ask for:** rungs in order, each landing green alone · **each rung's app
and its baseline tree** — a rung that needs two apps is two rungs, or a lead
decision recorded as such · **which doors the rung touches** (REST, MCP,
sockets, webhooks in/out) **and whether it adds a workflow** — a workflow rung
needs the worker up to be proved, and its criteria name the run's end state as
the instrument · **which rungs may run concurrently** (different apps) and
which may not (same app) · criteria phrased so a verifier gets a
yes/no **without reading the implementation** · the negative cases — *what must
still work* · **"what could go wrong that these criteria would NOT catch"**,
which is the honest blind-spot list · whether it should be two rungs rather than
one.

## Development — stage 5

**The brief opens with: "load `.claude/skills/rung-execution/SKILL.md` first,
then `django-conventions`."** That skill carries the builder-facing half this
section used to restate per brief — the baseline check, the born-to-standard
checklist, gate discipline, red-first, the escalation pattern, the report
contract, the standing safety clauses — so a development brief no longer
repeats them. What a brief still MUST carry, because no skill can know it:

- **the territory** — the app and the exact file set, and what is
  deliberately excluded. On a product's tree the platform is outside every
  territory by definition (`.claude/agents/builder.md`, house rule 95, the
  pre-commit hook), so a brief does not repeat "nothing under `quality/` or
  `scripts/`";
- **the three commands a product rung meets, named when they apply** — a
  client regeneration is `./scripts/rung_tidy.sh --client` (never
  `scripts/gen_client.sh` by hand); the type check is CI's form, `uv run mypy`
  over `pyproject.toml`'s `files`; a `Patch` field's words go in
  `frontend/src/copy/<noun>.ts`;
- **the criteria pointer** — where the acceptance criteria live, verbatim
  (a cycle file citation, never a paraphrase);
- **the baseline sha** — the tree the criteria were written against, which
  the builder's step-zero check verifies;
- **what is unusual** — sanctioned out-of-territory lines, worker-up
  requirements, known traps, exceptions to any standing rule, and anything
  this work does that the last ten rungs did not;
- **"keep the builder's seven"** — the block of that title in
  `django-conventions`, cited by title, never restated;
- **the roads the rung reuses**, as the lead cited them — and the builder's
  sentence: *"A helper you are about to write is a job you have not asked
  `roads` about. Ask first. A road you add without the criteria naming its job
  is NOT MET at PROVE, whatever else the rung did."*
- **the seam block**, whenever the brief names a callable the rung will call
  and did not write — see immediately below.
- **the batch, when the brief carries more than one rung** (the standing rule
  in `SKILL.md` § The loop): the rungs listed in order with each one's own
  territory, criteria pointer and baseline; the instruction that each rung is
  its own commit with its own red-first evidence and its own report section;
  the cap (four rungs or one session, one app, one territory, no frozen app);
  and the stop rule — a rung that cannot land is reported by name with the
  others marked untouched, never worked around.

**On a product's tree**, a product builder's brief is territory + criteria
pointer + "the one path" (`docs/sdk/the-one-path.md`): the builder reads
`docs/sdk/reference.md` first, and the brief restates none of it.

The clauses below remain as the record of what was paid for and for the
occasional brief that must override one — an override is stated explicitly,
never implied by omission.

### The seam block

**A development brief that names a cross-app callable carries
`scripts/seam_check.sh`'s pasted output, and the PM refuses ITSELF the
dispatch without it.** A standing rule, not a gate leg, and deliberately: the
gate measures the tree, and a brief is not in the tree.

```bash
# never piped — the exit status is the verdict
./scripts/seam_check.sh --claims <file> > "$PWD/seam-<rung>.log" 2>&1
echo "exit=$?"
```

Each claim is `module.path:callable(signature-fragment)`, one per line, and the
fragment may be empty (`module:callable()` asserts existence alone). The check
**imports** through the baseline checkout's own venv — never greps — runs
`django.setup()` for anything under `apps/` or `config/`, and reads
`inspect.signature`. Exit **0** every claim proven · **1** a claim is FALSE ·
**2** it could not look, which outranks a pass everywhere. **Paste the whole
run, exit status included**; a green nobody else can see is not evidence, and
a true claim prints no line of its own by design, so the verdict footer is what
carries it.

**What it costs and what it buys.** Between one and two seconds warm for a
handful of claims, `django.setup()` included. Against that: a rung dispatched
on a brief naming seams the baseline tree does not carry in the claimed shape
will prove all of them false, hold, and sit serialized for hours behind a
re-dispatch — while every one of those gaps was knowable from the baseline
tree at brief time, in about a second.

**Why a grep is not a substitute** — the half nobody works out unprompted. The
gap that costs most is a name that **exists** with the wrong signature: a
storage service taking `content: bytes` where the brief assumed a streamable
body, which would have put a whole tenant's archive in a worker's RAM. A grep
for the name goes green and the rung holds anyway. Only importing and
comparing the signature catches it.

**What the block does NOT license.** It proves existence and the parameter
NAMES the fragment lists — nothing about behaviour, semantics, types,
parameter order, defaults, or whether the seam is the RIGHT one for the job.
The brief still owns all of that, and the criteria still owe the
observable-difference question above. A seam block is a floor under a brief,
never a substitute for reading the code the rung will call.

**Must include:** the criteria as the definition of done · *"rung by rung, gate
green at each; no rung lands red and no rung lands broad"* · the branch and the
worktree · **"load `.claude/skills/django-conventions/SKILL.md` before writing
code"** · and the standing conventions it will otherwise rediscover.

**The doors and the spine — say it every time:**

> *"Every door calls services: a route, an MCP tool, a consumer, an activity or
> a webhook receiver imports services, selectors and schemas — never a model
> for a write. Services own writes and `emit()` their events inside the
> transaction. Anything that must wait or retry is a Temporal workflow, and
> **workflow code is deterministic**: no ORM, no `httpx`, no clock, no
> randomness inside `workflows.py` — activities do the I/O and call services.
> Register by discovery — an `apps.py` whose `AppConfig` declares `depends_on`,
> then drop `api.py`, `mcp.py`, `consumers.py`, `workflows.py`, `activities.py`
> in your app; never edit `config/` or `pyproject.toml`. Every route carries
> an explicit `auth=` — on its router or on the route — never `auth=None`
> outside the `rules.yaml` allow-list."*

**Gate economics, which nobody works out unprompted.** Tell them:

- **`./scripts/check.sh --loop` per rung** — the fast legs, `check --deploy`,
  and ONE pytest pass. That is the builder's gate, and nobody else runs it: the verifier's consult is a lookup of the key you paste, so post `committed <sha8> — loop running on <box>` the moment your last commit is in, then launch the loop. Fold main in at your last boundary, run it after that fold,
  and paste the `banked:` key it printed, so the verifier's consult has a tree
  to hit.
- **The box loop goes in a DRIVER SCRIPT in the builder's scratchpad, and the
  brief says so in the form below** — three exports on their own lines, then
  the wrapper. The reason is one sentence and it belongs in the brief: *the
  permission classifier does not match an inline env-prefix form
  (`DJB_X=… ./scripts/verifier_box.sh …`), so a builder that types one loses a
  turn to a prompt.* Every builder of one fifteen-rung wave paid that turn.

  ```bash
  # <scratchpad>/<rung>/vb.sh — exports on their own lines, then the wrapper
  export DJB_DEPLOY_NAMESPACE=<namespace>
  export DJB_VERIFIER_REGION=<region>
  exec ./scripts/verifier_box.sh "$@"
  ```

  The ceiling on how many boxes the wave may hold is `verifier_box.sh ceiling`
  — the file `~/.<namespace>/verifier/ceiling`, one integer, above the default
  2 and below `DJB_VERIFIER_MAX_BOXES`; it is the operator's to set once for
  the machine, and every ceiling refusal prints all three sources and the one
  that bound.
- **The full gate runs once, at push, and the builder does not run it by hand.**
  Pre-push consults the verdict ledger, so a tree already measured passes in
  seconds; a confirmatory full run before committing buys nothing and costs the
  rung most of its wall clock. A builder told only "gate green at each rung"
  reads that as the full gate and pays for it before the hook ever gets the
  chance not to — which is why this clause is in the brief and not left to the
  hook.
- **Never pipe the gate.** Its exit status is the evidence; `| tail` replaces it
  with `tail`'s. **Exit 2 means the enforcement is broken, not your code** —
  stop and report it; do not work around it.
- `./scripts/test.sh` exits with pytest's own status and is never piped.

**The worktree and the database.** *"You work in your own worktree; it has its
own Postgres database (`scripts/db.sh`); nothing you run touches another
agent's tree. Stage explicit paths; never `git add -A`."* Two agents in one
checkout is how a commit lands on another agent's branch and a gate measures a
tree it did not claim to; the worktree removes both by construction.

**Commit at boundaries, and take turns on suites — say both every time:**

> *"Commit at every rung or leg boundary — a commit is not a claim the rung is
> proven; it is a claim that this is what you wrote, and a killed session then
> loses minutes, not the rung. Never run two test suites in one checkout or
> against one database: your worktree's database is yours alone, but before
> running a suite anywhere shared, `pgrep` for a runner already in flight and
> wait for it."*

Under genuinely unstable conditions a WIP commit that skips hooks is legal
only if the tree is fully gated afterwards and the deviation is reported with
the rest.

**The schema discipline — say it every time, in full:**

> *"Your rung names its app: `<app>`. Make the migration inside the rung with
> `uv run python manage.py makemigrations <app>` from the models you changed;
> commit the migration and the updated `max_migration.txt` with the code.
> **Never run `makemigrations --merge`.** If `makemigrations` or
> `max_migration.txt` shows a conflict, another rung has touched this app: stop,
> report it as an ordering failure, and do not patch it. Read the schema with
> `uv run python manage.py introspect`; do not guess it. Models a tenant owns
> inherit `TenantScopedModel`; every read in a door or service is
> `.objects.for_tenant(...)`; services take `tenant` as a keyword argument."*

**Independent rungs go out together, and the rule has two halves.** Two rungs
in **different apps** do not touch each other's migrations; run them
concurrently in separate worktrees, each against its own database. Two rungs in
**the same app must not** — they will both produce migration `000N` and one of
them will need `--merge`, which is forbidden. Say both halves: a flat "run rungs
in parallel" is the failure mode, and so is a flat "never". One agent holding
the whole product alone while nothing else moves is the default, and it is not
a good one.

**A client fan-out NAMES ALL THREE SERIAL POPULATIONS, every time.** `SKILL.md`
owns the batching rules and they are unchanged here — fan-out is argued and is
the default, every parallel leg carries its independence argument, and a leg
whose argument cannot be stated serializes. What a fan-out over the client
layer owes on top is the same debt the schema discipline pays two paragraphs
above: the populations where the independence argument **cannot** be stated,
named in the brief, so that a plan omitting one has not argued its parallelism
— it has assumed it. There are exactly three, and a fan-out brief naming fewer
is returned.

- **(i) Dependency rungs are EXCLUSIVE — the `makemigrations --merge`
  analogue.** The lockfile — `pnpm-lock.yaml` under the pinned manager — is the
  client's `max_migration.txt`, and it is the worse of the two: two branches
  editing it merge **textually clean** into a lockfile that no longer satisfies
  its `package.json`, and stay silent until an install with the lockfile frozen
  runs. There is no leaf file whose conflict announces it at the moment it
  happens, which is why the law has to be typed into the brief instead. Any
  rung touching `package.json` or `pnpm-lock.yaml` holds the wave alone. The
  belt underneath it is a gate leg that installs with the lockfile frozen; a
  product that has not built one yet has the exclusivity law and nothing else,
  and the brief says which of the two it is standing on.
- **(ii) Client-regeneration rungs are SERIAL.** A generated client is a build
  artifact of one tree and one contract. Two rungs regenerating it produce two
  artifacts of two different contracts, and the merge silently keeps one —
  schedule them one at a time, exactly as migrations are scheduled, for
  exactly the same reason.
- **(iii) Frozen-layer edits BATCH, the way `core` does.** The root layout, the
  shared providers, the request middleware, the design tokens and the framework
  config are the client's `apps/core`: a rung touching one serializes the line
  behind it. It states its reason in the plan and batches with the other
  frozen-layer work into a rare, deliberate rung — the clause above, one layer
  over.

**And say what no fence dissolves.** Those three are where parallel is illegal.
Holistic visual coherence is **not** one of them, because it is not a
build-time question at all: it is answered at verification, which is serial by
nature and by design — build parallel, verify serial, which is already how the
Python side works. A plan promising coherence as an output of the fan-out has
promised something a fan-out cannot deliver, and the honest form says where it
is actually paid for.

**Must NOT include:** any invitation to judge whether the result is good. That
belongs to stage 6, with someone else.

---

## Auditing an unfamiliar area

When you need ground truth rather than a change:

> *"The status docs are KNOWN to have drifted. Establish ground truth FROM THE
> CODE — and from `uv run python manage.py introspect`, which is what the
> schema actually is. A doc claim is a hypothesis; the code is the evidence.
> For each item answer BUILT (name the artifact), PARTIAL (what exists, what is
> missing), or ABSENT (confirmed by search)."*

Ask explicitly for **"where the docs disagree with the code"** as its own
section. That list is usually the most valuable thing the audit produces.

---

## Surveyor — finds the work

Reads the system rather than driving it. Dispatch when the non-functional band
would otherwise empty, at wave boundaries, after a deploy, or on demand.

**Must include:**

> *"The status docs are KNOWN to drift. Establish ground truth FROM THE CODE,
> the logs, the settings as `introspect` reports them, and the running box. A
> doc claim is a hypothesis. Report every place they disagree as its own
> section; that list is usually the most valuable thing you produce."*

> *"Write what you find into `docs/product/queue.md` yourself. **Every row
> carries its evidence** — a `file:line`, a measurement, a log line, a
> reproduction. Propose a band and say why. Do not set priority; the PM orders.
> A row you cannot evidence goes in your report, not the queue."*

**The six standing lenses, every run, then one rotating lens.** The standing
six are the failures this stack accumulates silently:

- **Query counts at seeded scale.** Every list endpoint and every admin
  changelist against a seeded database at the product's declared scale × k;
  report the count, the N+1 if there is one, and the `select_related` /
  `prefetch_related` that is missing. Compare against the `assertNumQueries`
  floors in the tests — a floor that is far above the measured count is a floor
  that will not catch a regression.
- **Migration graph health.** One leaf per app; `max_migration.txt` agrees with
  the tree; no merge migrations anywhere in history; `makemigrations --check`
  clean; data migrations carry a reverse; no migration imports a model directly
  instead of `apps.get_model`.
- **`manage.py check --deploy`** against production settings, warnings as
  failures, plus `.env.example` against what settings actually reads.
- **The worker.** Task queue backlog, failed and stuck workflow runs, retries
  that never end, deliveries in the dead letter — read from the Temporal UI
  and the `WorkflowRun` / `Delivery` tables, not from a log line that says
  "started".
- **The outbox.** `Outbox` rows written and never dispatched, and the age of
  the oldest; an `emit()` whose event nobody received is the failure the spine
  makes silent.
- **Door parity.** For each capability, which doors serve it — REST, MCP,
  sockets, webhooks — and whether the shapes agree; a tool with no route, a
  route with no tool, a payload that differs between them, each is a row.

Then **point it somewhere specific**; an unbounded "look for problems" returns
platitudes. Rotate:

- **The declared blind spots** — every `does_not_cover` in `quality/rules.yaml`
  is a place automation has admitted it is not looking. Highest yield, and the
  map already exists.
- **The deployed box versus the repo** — configuration, hand-made data,
  migrations applied that are not in the tree, anything that would not survive
  a rebuild from `setup.sh`.
- **The failure surfaces** — error logs, refusals nobody sees, activities that
  fail silently, webhook deliveries that dead-letter without a row anyone
  reads, and anything that reports success while doing nothing.
- **Promises the product makes** — every error message, empty state and API
  description that names an action, checked against whether that action exists.
- **The tenant boundary** — every read of a scoped model outside
  `for_tenant(...)`, especially where rule 8 cannot see: raw SQL, admin,
  management commands, activities and consumers with no request. Where a
  product has opted out, every place it has started to need tenancy back.

**Ask for, explicitly:** *"what you could not check, and why."* A surveyor
blocked by absent logs has found something larger than what it went looking
for.

**Never:** fixes anything · commits · sets priority · reports a finding it has
not evidenced.

## Standing clauses

These are brief clauses that belong to no single role — each one closes a class
that has struck at least twice.

- **Every rung report states `git branch --show-current`** — never a
  remembered branch name. A misnamed branch makes a merge silently fail while
  the ledger reads "merging", and the gate then runs green on the unmerged
  tree.
- **Mutation scripts never live in a shared scratchpad with relative
  paths** — absolute worktree-pinned paths or direct tool edits only. A peer
  that runs a relative-path script from its own tree applies the author's edit
  *there*, silently and in the wrong checkout.
- **Every brief names the lane's own log paths, carrying the agent or rung id
  and living in that lane's worktree** (`"$PWD/serve-<rung>.log"`), or assigns
  it a scratchpad subdirectory of its own — never a bare `serve.log`,
  `worker.log`, `gate.log` or `/tmp/seam.log`. Those are the names every skill
  prescribes, which is exactly why several concurrent lanes write into one
  file — and then a verifier reads a foreign tenant id out of what it believes
  is its own log. A per-lane `scratchpad/<lane>/` is the pattern.
- **Field-test briefs: socket work needs a non-reload server.** `--reload`
  closes sockets with code 1012 on every commit to the checkout, which
  invalidates the run without ever looking like a test failure.
- **A development brief naming a cross-app callable carries
  `scripts/seam_check.sh`'s pasted output, and the PM refuses ITSELF the
  dispatch without it** — see § The seam block. Not a gate leg: the gate
  measures the tree, and a brief is not in the tree.
- **Every FIX rung's brief carries: "where do this defect's siblings live?"** —
  a one-grep census of the same shape elsewhere, reported, not necessarily
  fixed. A defect found in one sweep is routinely present in its sibling
  sweeps, and a bug found in a service is routinely present in a second,
  undocumented form in the middleware beside it. Per-occurrence fixes re-mint
  queue rows forever; the census is one grep.
