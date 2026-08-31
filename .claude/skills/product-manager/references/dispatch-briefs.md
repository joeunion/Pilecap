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

**PROVE brief must include:** the acceptance criteria **verbatim from stage 4**,
and *"verify against these criteria, not against what was built; if a criterion
was wrong, that is a finding against the criteria."* Through REST always,
through MCP and sockets wherever the rung touches them — and the same
capability through two doors where both exist, because the disagreement is the
finding; through the browser, desktop and phone, where the product has one;
plus one adjacent persona to catch what the primary path hides. And the
mirror lens, for every criterion over a stateful flow: *which state or
population member did this criterion NOT drive?* — an undriven live path is a
finding against the criteria.

**And the prohibition, pasted in verbatim — this clause is the brief's, not a
paraphrase of it:**

> *Verify a green full verdict exists in the ledger for the exact tree under
> test — one grep of the measured tree against the verdict ledger that
> `scripts/gate_ledger.sh` maintains (its `gate_measured_tree` is the key:
> HEAD's tree plus untracked non-ignored files — `git rev-parse HEAD^{tree}`
> matches it only on a checkout with no untracked files; docs-or-ledger-only
> commits after the banked tree are not a fail). One grep; that is
> observation. Then drive the criteria through the doors and the UI. Running
> `check.sh`, `test.sh` or any suite is out of scope and a criteria-writing
> error — if a criterion asks you to, say so and stop.*

Why a prohibition rather than a preference: the gate is deterministic on a tree,
so re-running it is not a second opinion, it is the same opinion bought again —
and a criterion that tells the verifier to run the gate buys it a third time.
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
introspection output for the apps in scope.

**The one demand that has failed most often.** For **every** criterion, require:
*what observable thing differs if this is false?* Criteria that assert a
**mechanism** rather than a **property** pass while the property they meant to
protect goes unguarded — "the tests stay unchanged" (which forbids a refusal
getting stronger), "a permission row exists" (whose absence nothing can detect),
"the handler survives a throwing call" (a harm unreachable because no call site
catches). **If answering the question needs a code path that does not exist,
the criterion is describing a mechanism.**

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
  deliberately excluded;
- **the criteria pointer** — where the acceptance criteria live, verbatim
  (a cycle file citation, never a paraphrase);
- **the baseline sha** — the tree the criteria were written against, which
  the builder's step-zero check verifies;
- **what is unusual** — sanctioned out-of-territory lines, worker-up
  requirements, known traps, exceptions to any standing rule, and anything
  this work does that the last ten rungs did not;
- **the seam block**, whenever the brief names a callable the rung will call
  and did not write — see immediately below.

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
./scripts/seam_check.sh --claims <file> > "$PWD/seam-<rung>.log" 2>&1; echo "exit=$?"
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
  and ONE pytest pass. That is the builder's gate.
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
