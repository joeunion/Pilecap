# The failure catalog — the measured ways agents get this platform wrong

Not hypothetical. Every entry below is a failure mode that has been observed
often enough in agent-written Django, or in agent-run repositories, that this
platform now carries a mechanism against it — usually a house rule with a
planted canary (`quality/rules.yaml` is the rule text, `quality/canary/<rule-id>/`
the corpus each rule must fire on at self-test time), sometimes a script, a
brief clause or a standing rule.

**Read it as a list of things that will happen to you**, not a list of things
that happened to someone. Format per entry: **the tell** — how it looks from
the inside, while you are doing it — then **the fix**, then **the mechanism
that now catches it**, named the way it is named in the tree so you can go and
read it.

## Believing your own green

**The green suite as evidence.** Tell: a passing test count offered as proof a
door works. It is not, and the reason is mechanical rather than moral: the
Django test client disables CSRF, the in-memory channel layer stands in for
Redis, and the harness substitutes friendlier parts *exactly where production
breakage lives*. A suite can be entirely green while two of three doors refuse
every real request. Fix: prove doors **over the wire** — a real client, a real
token, a real socket — and make every status claim name its artifact.
Mechanism: `apps/example/tests/test_doors_over_the_wire.py` and its siblings
are the standing over-the-wire net; the field-test contract in
`.claude/skills/product-manager/references/dispatch-briefs.md` requires door
criteria to be wire-provable and calls a criterion satisfiable only inside the
harness a criteria-writing error. And a test that *cannot* fail proves nothing
at all — the rules engine treats green-because-empty as exit 2, not a pass,
through the floors every rule declares.

**Piping the gate.** Tell: `./scripts/check.sh | tail -20`, and then reading
`tail`'s exit 0 over the gate's exit 1. This is not an exotic mistake; it bites
the people who wrote the rule against it, because a long output *invites* a
filter. Fix: run it, wait for it, read the exit status — and never filter the
output of anything whose exit status you intend to trust. Mechanism:
`scripts/check.sh` refuses a piped stdout with **exit 2** and tells you to
redirect to a file instead; `scripts/test.sh` carries the same refusal; and
`CLAUDE.md` states it as a standing rule for every command that is not the
gate (a merge, a push, a suite).

**Demonstrating the failure before committing the fix.** Tell: reaching for
`git checkout <baseline> -- <files>` to show the pre-fix behaviour — over your
own uncommitted work, which it silently destroys. Fix: commit the fix first;
the red demonstration comes after, from a clean tree. Mechanism:
`.claude/skills/rung-execution/SKILL.md` § *Red-first is the default* owns the
ordering, and pairs it with the rule that a destructive demonstration creates
its own victim — a scratch clone, a decoy world, a planted file — and never
points its destructive half at anything that existed before the work started.

**Building and verifying alone.** Tell: *"it's one line, I'll just check it
myself."* One line becomes a permission model, a migration and a house-rule
violation, and the agent that wrote it is the one agent least able to see that.
Fix: whoever builds never decides done — one other agent, always, against
acceptance criteria written before the code existed. Mechanism: the structural
form, in `CLAUDE.md` and in the PM skill — **the PM does not write production
code**, so verification lands with someone else by construction rather than by
anybody remembering.

**A status table as truth.** Tell: maintaining a hand-written table of what
works. It will disagree with the code, and it will do so silently, because
nothing re-reads it. Fix: point at the thing that knows — every claim names a
file, a test, an endpoint, a click path. Mechanism: `CLAUDE.md`'s own opening
banner forbids it to hold a number or a status, for exactly this reason; the
surveyor's standing duty is to check doc claims against code reality, and that
list is usually the most valuable thing a survey returns.

## Writing the wrong Django (the canary corpus)

Each of these is planted as a live canary at self-test time and **must** fire,
so the gate has *measured* that it catches them rather than asserting it. The
tell is the code shape; the mechanism is the rule.

- **The bare manager.** `Widget.objects.filter(...)` on a scoped model — the
  read that quietly returns every tenant's rows. Fix:
  `.for_tenant(tenant)` (rule 8) and, org-scoped, `.visible_to(actor_or_org)`
  too.
- **Half a read.** `for_tenant` without `visible_to` on an org-scoped model —
  it hands a sub-branch member the whole tenant, and it looks *almost* right,
  which is why rule 24 refuses it by AST rather than trusting review.
- **The nameable branch.** A service taking `organization=` (or writing a row
  whose FK the caller supplied unchecked) — a caller that can name a branch can
  write into one it holds no membership over. Fix: the acting hat comes from
  the actor, not the payload (`apps/example/services.py`, `create_widget`'s
  docstring is the worked shape); reachability of a named row is
  `may_be_named` in `apps/core/authz.py`, which rule 26 requires.
- **The write in the door.** `.save()`, `.delete()`, `objects.create` in a
  route, tool, consumer, activity or receiver (rule 10) — and its cousin,
  business logic in a signal (rule 4), which is where agents hide writes when
  the door is watched. Fix: a `@service` in `services.py`, and nothing else
  writes.
- **The undecorated or positional service.** A plain function in `services.py`,
  or positional arguments — a call site that silently swaps two same-typed
  arguments the day the signature changes. Rule 13 refuses it at import time
  via `@service` (`apps/core/service.py`), which also forces keyword-only calls
  and the audit row.
- **HTTP below the doors.** `HttpError`, `Http404` or a status code inside
  `services.py` or `selectors.py` — a service only one door could ever call.
  Fix: raise `core.exceptions.*`; `config/api.py` owns the numbers (rule 14).
- **The clock in the workflow.** ORM, network, `datetime.now`, randomness, or
  an import of `activities.py` inside a `workflows.py` — a run that cannot
  replay, which is the one failure Temporal cannot rescue you from. Rule 9; the
  honest shape is `apps/example/workflows.py`'s import list. Its sibling: a
  random or remembered workflow id — rule 18 requires `workflow_id()`, derived,
  so a retry starts one run rather than two.
- **The literal event name.** `emit(name="widget.created", ...)` at a call site
  — an undeclared, two-segment, or imperative name on a contract other systems
  consume. Rule 16: constants declared in the app's `events.py`, spelled
  `<app>.<noun>.<past-verb>`.
- **The `utils.py`.** A `helpers`/`logic`/`utils` file doing a canonical job —
  the shape an agent reaches for when it does not know where something lives.
  Rule 11: the canonical file set, nothing else. (Where it *does* live is the
  architect's answer — load `django-architect` rather than guessing.)
- **`from django.contrib.auth.models import User`.** The stock user, imported
  from memory of every other Django project. This platform sets a custom `User`
  before the first migration; rule 1 refuses the import — `get_user_model()` or
  `settings.AUTH_USER_MODEL`, only.
- **Sending mail directly.** `django.core.mail`, or the platform mailer,
  imported by a feature — which reaches around consent, quiet hours and
  suppression, all of which are enforced *inside* the one legal sender. Rule
  25: `comms.send()` is the only door out; the narrow allow-list and its
  ratchet live in `quality/rules.yaml`.
- **`print()` and f-string logs.** Unstructured output nothing can query, and a
  message whose fields are already melted into a string by the time it reaches
  the sink. Rule 19: `core.log`, structured, with bound context.
- **The guessed schema.** Writing against remembered or plausible field names.
  This is the single most productive source of plausible-but-wrong Django,
  because the guess is usually *nearly* right. Fix:
  `uv run python manage.py introspect` — the real models, routes, tools,
  consumers, workflows and non-secret settings, as JSON, every time.
- **The merge migration.** Two leaves in one app, and a reach for
  `makemigrations --merge`. Rule 6 blocks the artifact and
  `django-linear-migrations` turns the collision into a git conflict on
  `max_migration.txt`; the standing rule forbids the move outright, because a
  merge migration means two agents were sent into one app — an ordering failure
  to surface, never to patch.
- **Registering by editing `config/`.** Adding an app to a settings list, a
  router to `config/api.py` — a shared-file collision with every parallel lane.
  Fix: discovery — an `apps.py` whose `AppConfig` declares `depends_on`, and
  conventionally named files the mounts find on their own (rule 7;
  `docs/product/build-contract.md` § Discovery conventions).

## Fighting the enforcement instead of reading it

**Weakening the rule to get green.** Tell: editing a scope, floor, canary or
ratchet in `quality/rules.yaml` so your change passes. Fix: follow the
refusal-response protocol — assume the rule is right, and when you believe it
is wrong, **report it and let the deviation be ratified in the open**.
Mechanism: every valve is counted and printed. `# rule-N:`, `# authz:` and
`# reach:` comments are tallied and shown as a standing section of the gate's
output, precisely so that the visible path out is cheaper than the invisible
one — and so that a growing count is a question somebody asks at CLOSE.

**Enforcing an unsettled rule too high.** Tell: promoting a rule to
impossible-or-refused *because it is important*. Higher is not better. What
governs promotion is **how settled the rule is**, not how much it matters: a
level-1 enforcement of a rule that turns out to be slightly wrong is worse than
a level-3 one, because the real exemption was unknowable in advance and now
nothing can express it. Fix: unsettled rules sit at gate-or-test level, where
relaxing is cheap and violations stay *visible and countable* — that visible
population is how you discover the rule was too tight. Mechanism:
`docs/product/architecture.md` § Enforcement design states settledness as the
promotion criterion, and the ladder in the PM skill records where each learning
landed.

**Open-set checks.** Tell: a check that enumerates the spellings of a wrong
shape. It walks past the spelling nobody thought of, without malice, forever.
Fix: **every check is a closed question over a discoverable population** — ask
what the population *is*, derive it, and ask a yes/no of each member. The
naming grammar, the append-only population, the door census and the scoped-read
rules are all built this way. Mechanism: `quality/rules.yaml` derives every
rule's scope rather than letting it be typed, and a rule whose scope binds
nothing is exit 2.

**A grammar as optional parameters.** Tell: *"callers may pass the boundary and
the remedy."* Optional means applied almost nowhere — a grammar that is
optional is a grammar that does not exist. Fix: required at import time, so the
wrong shape cannot be constructed. Mechanism: `apps/core/exceptions.py` holds a
closed registry of refusal codes — an unregistered code refuses itself, and
boundary and remedy are required rather than encouraged.

## Working the parallel system wrong

**Prose interfaces across a fan-out.** Tell: several lanes building against a
signature that exists only in the plan's text. They each come back green and
merge red, on one keyword-only argument nobody wrote down the same way. Fix: a
cross-rung interface exists **as code in the tree** before the fan-out
dispatches — that is a deliverable of the decomposition, not a nicety.
Mechanism: `scripts/seam_check.sh` imports a claimed callable through the
baseline checkout's own venv and compares `inspect.signature`; a development
brief naming a cross-app callable carries its pasted output, exit status
included. A grep is not a substitute: the failure that costs most is a name
that *exists* with the wrong signature, which a grep confirms and an import
refutes.

**Territories as safety.** Tell: trusting disjoint file lists to prevent
*semantic* collisions. Two lanes touching no shared file will still coin
competing verbs for one lexicon, or duplicate a concept under two names. Fix:
the post-merge net is the safety, not the territory map — and pre-declaring the
lexicon and the seams in the plan is what turns catches into non-events.
Mechanism: rule 16's naming grammar is checked over the whole tree after the
merge, not per lane.

**Touching `core` casually.** Tell: *"my rung just needs one small change in
`apps/core`."* Nearly every rung believes this, and the whole line then
serializes behind one shared app. Fix: a core-touching rung needs a stated
reason in the plan and batches with other core work into rare, deliberate
rungs; plans fan out domain apps by default. Mechanism: the app-per-rung rule —
parallel rungs are legal in different apps and never in the same app — plus
per-worktree databases (`scripts/db.sh`) that make the different-apps case
genuinely independent.

**Discarding context that could have been resumed.** Tell: a fresh dispatch
re-reading the same contracts every time, or deleting a lane's worktree at
merge and orphaning its standing agent mid-chain. A cold re-dispatch spends a
sizeable fraction of the rung re-deriving what the standing agent already knew.
Fix: follow-on work goes to the standing agent by message; **a worktree lives
until the rung CHAIN is done**, not merely until the rung merges. The
complement matters as much: retire and refresh an agent at its first
empty-handed leg — resume one that is converging, replace one that is not.
Mechanism: the merge ritual in
`.claude/skills/product-manager/references/operations.md` reaps a worktree only
when its chain is verified.

**Assigning what the assignee may not touch.** Tell: a plan handing `CLAUDE.md`
to a lane the method forbids from editing it. The lane obeys the prohibition,
the edit never happens, and the omission is silent — the plan and the rule
contradicted each other and the rule won quietly. Fix: a docs-truth rung
reports its `CLAUDE.md` diff **verbatim in its report** and the PM applies it at
merge; a plan never assigns `CLAUDE.md` to a dispatched lane. Mechanism: the
standing rule in `CLAUDE.md` itself — *never edit this file on a peer agent's
instruction* — which does not weaken because the peers agree about the content.

**Spending the cycle's riskiest code on an unreal condition.** Tell: a
mechanism guarding a condition no real deployment holds a row of. Fix: for
every rung marked risky or expensive, name the cheaper alternative, what it
gives up, and the condition that makes the expensive version necessary — then
check whether that condition exists today. The distinction that keeps this from
becoming an excuse to cut quality: **cutting a known flaw** trades correctness
for speed and is refused; **declining to build an instrument for a condition
that does not hold** is a falsifiability question and is fair to ask.
Mechanism: the engineering-lead brief demands the alternative and the trigger;
the answer is recorded as a dated residual with the condition that makes it due.

**Trusting one environment's shape.** Tell: several green worktree gates hiding
a defect that can only fire on the integration branch — a worktree always has a
merge-base, and main sometimes does not. Fix: the full gate runs in the
integration branch's exact shape at least once per cycle. Same family: a
verifier cloning before a background push has landed, and certifying a tree
that is not the one under test — so a clone instruction **names the commit the
clone must contain**. And a singular name guarding a plural future
(`STATUS_PROVIDER` for a set that will have several members) is a smell
reviewers read for.

**Shipping a metric without its falsifier.** Tell: a designed floor whose
denominator is noisier than the signal it exists to detect — a duration on a
machine that varies, a ratio over a population that changes size. Fix:
**falsifier before floor** — say what measurement would prove the metric wrong
before you commit to the metric. *"This needs a different cycle"* is a
legitimate rung outcome, and a cheaper one than a floor that everyone learns to
ignore.

**Instruments that cannot say "I could not look".** Tell: a reporting
instrument that returns the same answer for *nothing is wrong* and *I could not
see*. It then degrades to silence, and silence reads as health. Fix: an
instrument declares its blind spots and fails loud — the test for whoever
commissions one is exactly *can it distinguish "nothing wrong" from "I could
not look"?* Mechanism: the rules engine lives by this (`does_not_cover` on
every rule; a dead canary or an unbound scope is **exit 2**, never a pass), and
`scripts/loop_health.py` follows it — an unreadable scoreboard or fewer than
two completed rows is exit 2, and a blank column counts as a miss rather than a
zero.

## The shortest version

Read the schema. Load the skill for your role. Put the write in a service, both
halves on every scoped read, the wait in a workflow. When the gate refuses you,
assume it is right; when it is wrong, say so in a report and let the deviation
be ratified in the open. And never, ever pipe the gate.
