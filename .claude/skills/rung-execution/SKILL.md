---
name: rung-execution
description: >-
  Load FIRST, at the start of every development rung, before touching the tree —
  then django-conventions before any Python, fe-conventions before any client
  code. This skill is how a rung is EXECUTED here: the baseline check, the
  born-to-standard checklist, the gate discipline, red-first, the report
  contract, and when to stop and flag instead of edit. It exists so a dispatch
  brief can shrink to territory + criteria pointer + what is unusual; everything
  execution-generic lives here. NOT how to write the code (django-conventions,
  fe-conventions), NOT what to build or whether it is done (the PM's and the
  field test's). Every claim cites its rule id or the ledger row that paid for it.
---

# Executing a rung

You are one of several agents building in parallel against one schema. Your
brief gives you a territory (an app, a file set), a criteria pointer, and
whatever is unusual about your rung. Everything else — how to start, how to
prove, how to gate, how to report — is this file.

## 0 · Step zero: run the instrument

Before reading anything else, before touching the tree, one command:

```bash
./scripts/rung_start.sh > "$PWD/rung_start-<rung>.log" 2>&1   # YOUR rung's id; *.log is ignored
echo $?
```

It does, unconditionally and in order: **resets this worktree to main**
(printing the sha before and after, and SAYING SO when they differ),
**provisions the venv**, **creates and migrates this checkout's own database**,
**creates this checkout's own object-storage bucket**, and **dumps `introspect`
to `.rung/introspect.json`** — the schema dump, which is data this tree's own
instrument wrote and NOT a scratch area (scratch lives outside the checkout;
§5). Each step prints what it did and how long it took, and the total is on the
last line.

**When your brief names a baseline sha, type it** — `--expect <sha>` takes a
COMMIT or a TREE (a brief cites whichever it has; a commit is resolved to its
tree and the run says which it was handed), compares it against the baseline
step 1 is about to land on, and REFUSES with exit 2 before the venv, the
database or the dump if they differ. That is the half of §0 that used to be
prose only — see *what it cannot do* below — and the flag composes with
`--resume`, where the baseline compared against is HEAD rather than main.

**Exit 0 ready · 1 a step ran and failed · 2 refused, or a step it could not
verify.** Read the status; it is the verdict. In particular it **refuses and
resets nothing** when the tree is dirty or the branch has commits main does not
have — so re-running it mid-rung is safe, and a refusal is never something to
work around by resetting by hand.

Then record in your report: the baseline sha it printed **before**, the sha
**after**, and whether it reset. Take the shas from its output, not from
memory.

### Why it exists, and what it cannot do

The four steps above were four hand steps, done from memory, by every builder,
every rung — 30–50% of a short rung's wall clock, and hand steps done
from memory are also hand steps *skipped* from memory. Step one skipped is a
rung built against a tree the criteria never saw: a whole batch of builders
have been cut from a stale main this way at once, and more the following
wave before the pattern was caught.

**Your worktree will very likely arrive stale, and that is not your bad luck.**
Worktree branches are created from `origin/main`, which moves only on a push,
while this loop merges into local `main` continuously — so every worktree
spawned between two pushes starts behind, sometimes by dozens of commits. The
instrument prints that gap under `-- THE POOL` whenever it holds. **The lever is
outside this repository** (the harness's choice of base, or a push after each
merge); step 1 is the belt, not the fix, and a green run means *this* checkout
is current, never that the next one will be.

The instrument has no opinion about **whether main's tip is the tree your brief
was written against** — unless you tell it. **A brief naming a baseline sha that
is neither HEAD nor main → flag it and hold**; do not guess which tree the
criteria were written against. `--expect <sha>` is how you make that judgment
the machine's instead of your own: hand it the sha the brief named and the run
either says `MATCH` or refuses, before anything is installed or written.

If the instrument is unavailable or exits 2 for a reason you cannot clear, the
equivalent by hand is `git log -1 --oneline HEAD` against
`git log -1 --oneline main`, and `git reset --hard main` only if you are behind
**and have not committed yet** — that clause is what the commits-ahead refusal
mechanises.

Then orient: load `.claude/skills/django-conventions/SKILL.md` before writing
any Python; read the criteria from where the brief points (verbatim, not from
memory); for any rung touching models, schemas, routes, tools, consumers,
workflows or settings, **read the dump step zero already wrote** (its path is on
step 5's own line, current as of the reset baseline) — or re-run
`uv run python manage.py introspect` yourself if the tree has moved since. The
schema is read, never guessed. And **re-verify the brief's cited evidence**: check
that the file:line a defect row cites still says what the row claims. Stale
rows have dispatched rungs against defects fixed cycles earlier; the
builder's verify-first discipline is the only net, and finding the row
stale is a finding, not a wasted rung.

## 1 · Born to standard

New code meets the house rules at birth — never "make it pass later". The
checklist, each item with its rule id and its worked example in the tree
(excerpts in `references/worked-examples.md`):

- **Models born lifecycle-declared** (rule 31). Every concrete model declares
  how its data dies — `PURGED` naming the reached sweep, `BOUNDED`,
  `UNBOUNDED`/`APPEND_ONLY` with a reason and a dated trigger. The teaching
  text is `apps/example/models.py`. A model you own carries
  `lifecycle: ClassVar[Lifecycle] = Lifecycle(...)` on the class; the
  `lifecycle.py` `register()` hook is ONLY for third-party tables — the
  registry refuses a second opinion about a model that declares its own.
- **Routes born with contract docstrings** (rule 41). First line is the title
  (short phrase, no Markdown, no full stop); description below it; never a
  hand-written `summary=`/`description=`; no maintainer archaeology in the
  contract (no queue-row references, `_underscore` names, `@service`,
  `manage.py`). One tag per operation, declared in the app's `TAGS`.
- **Refusals declared and reaching the document** (rule 47). Every refusal a
  route can answer is in its `@refuses(...)` set; every code is registered in
  `core.exceptions`; a NEW code declares `status=` at its own
  `register_refusal` site (ADR core-23 — `CODE_STATUS` is derived from the
  registry; there is no table to append) or it silently drops from
  `x-refusal-codes`.
- **Door pairs born with the parity test** (rule 46). An app with a REST door
  beside an `mcp.py` owes a `tests/` module with `DOOR_PAIR = ("rest", "mcp")`
  proving the two doors answer identically over the wire — the worked example
  is `apps/example/tests/test_doors_over_the_wire.py`. Rule 17 proves a
  capability exists on both doors; only this test sees them answering
  differently.
- **MCP surfaces ceilinged** (rule 45). A new dispatch surface arrives with
  its token-ceiling guard in front of it — the wall arrives with the first
  door, not after the first leak.
- **Scope families by the codified pattern** (django-conventions §6 →
  `references/api-door.md`, beside
  `Router(tags=[...])`). Scope keys, display names and the derived surfaces
  (llms.txt, mint refusals, MCP twins, footers) all move together; a frozen
  family is renamed by refusal-and-successor, never by shim.
- **Periodic work as `ScheduleDeclaration`s** in the app's `SCHEDULES` — never
  a cron entry, a thread or a hand-made Schedule object. Every workflow class
  satisfies rule 28 by one of its two patterns: its `@workflow.run` reaches
  the finish seam (a `*_finish` method or the `mark_run_finished` activity)
  LAST, or it declares `owns_no_run = True` (the schedule-started population
  that owns no row). Worked example: `apps/example/workflows.py`.
- **Strict bodies.** Every `In`/`Patch` schema refuses unknown fields through
  the one seam in `config/api.py` — an unknown field is `invalid_body` naming
  the field, never silently dropped (django-conventions §6, wrong form and right
  form in its `references/api-door.md`; the MCP door is
  strict the same way).
- **Migrations inside the rung** (rule 22). `uv run python manage.py
  makemigrations <your-app>`; expand/contract — no non-nullable AddField
  without a default, no RunPython without a reverse, no drop while the name is
  referenced; commit the migration and `max_migration.txt` with the code.
  **Never `makemigrations --merge`** — a conflict means another rung touched
  your app: stop and report an ordering failure; do not patch it.

## 2 · Red-first is the default

Prove the defect exists before closing it. Run the demonstration on the
baseline tree, **paste the red into your report** (the failing output, the
wrong wire response — not a description of it), then build, then show the same
probe green. A criterion that never went red is a criterion that may be unable
to fail.

Where feasible, **plant-verify both directions**: remove or sever the guard
and show the distinct failures appear; restore it byte-identical and show them
gone. A destructive demonstration creates its own victim — a scratch row, a
planted file, a decoy — never found state, whatever the brief says about how
safe it looks.

### Authoring the drive: two ways a green instrument lies

Both of these go green while proving nothing, which is why they are written
down here rather than left to the drive author's judgment.

**Measure the leg you actually ship.** A drive that exercises a *serial
approximation* of a parallel leg has measured its approximation, not the leg —
and it is green either way, because the approximation genuinely passes.
Evidence, from the sibling platform's F1: under a real `-n 5` run the xdist
workers collected, a controller-only guard suppressed every write, and the
banner the drive existed to prove **printed 0 times** — while the serial drive
beside it had been green throughout. So the drive runs the leg in the shape the
gate runs it (`-n $GATE_SLOT_WORKERS` — this box's cores split by the number of
pytest slots, NEVER `-n auto`, and the leg prints the number and why on every
run — two passes, worker-scoped fixtures, whatever the leg declares), or it says
**in its own text** which half of the shipped leg it does
not reach. *Prose today; **VEL-1** promotes it where its instrument lands — its
always-on floor criterion requires the drive to prove one end-to-end **on the
real `-n` invocation**, and names this line as the thing it is enforcing.*

**Floors name populations, not reach kinds, wherever two members share a
kind.** A floor written as `registry >= 1` is satisfied by *either* member of a
two-member population, so either member can go blind while the floor stays
green — a masking gap **inside the floors themselves**, which is the one place
nobody re-reads. Evidence: the sibling's declared blind-spot 0 — two
populations both satisfying a single `>= 1` reach-kind floor, each able to
empty without the floor noticing. The form that holds names the population and
its count (*both scope derivations bind*, *all N registered drives ran*), so
emptying one member is a floor failure rather than an arithmetic coincidence.
*Prose today; **VEL-1** promotes it where its instruments land — its always-on
floor criterion builds the floors in **two layers, per reach kind AND per named
population wherever two members share a kind**, which is this line made
executable; its canonical-scope field is one such population (same tree, two
scopes → two keys, and a wider scope never reusing a narrower verdict).*

### Authoring the drive: traps an honest drive still pays

These red a drive that is doing everything right, which is why they are written
down rather than re-discovered: each one cost a builder part of a rung.

**A drive cannot run a nested `./scripts/check.sh` inside a gate.** The
per-checkout gate lock refuses it (`gate_lock_refuse_if_held`), so a drive that
shells out to the gate to prove a leg goes red for the lock and not for the
property. A drive invokes the **leg body** — the sourced function the leg calls
— never the gate around it. (Paid by B2's builder, 2026-09-12.)

**`mktemp … 2>/dev/null` trips the portability census.** That census
(`mktemp_selfline` in `scripts/check.sh`) reads the LAST bare word of the line
as the template, so a trailing redirect becomes the template it judges and the
line reds with no X's in sight. Write the redirect **before** the template, or
not at all. (Paid by the same builder, the same night.)

**A criterion of the form "X refuses in production" needs a production
environment, and it is a module-local dict — never a new settings key.** The two
worked forms in this tree are `PRODUCTION_ENVIRONMENT` in
`apps/core/tests/test_settings.py` and in
`apps/workflows/tests/test_machinery_lifetime.py`: the minimum set of
environment variables `config.settings.production` refuses to start without,
with throwaway real-shaped values and a `# pragma: allowlist secret` on each
one, loaded around an import of the production settings module. Copy the nearer
of the two; do not invent a third spelling, and do not add a settings key so a
test can find one.

## 3 · The gate

- **Your one `--loop` runs ON A VERIFIER BOX, not on this machine** (owner,
  2026-09-18: the laptop carries editing; every measurement leaves it). The
  recipe, from your worktree, with `AWS_PROFILE`, `DJB_DEPLOY_NAMESPACE` and
  `DJB_VERIFIER_REGION` exported, each command's output to its own file under
  your mktemp dir (the wrapper refuses pipes):

  ```bash
  git commit …                                   # the push sends HEAD
  ./scripts/verifier_box.sh up --for <rung>       # the id is on the `instance ` line — never a grep for i-…
  ./scripts/verifier_box.sh loop <id> --log loop-<rung>
  ./scripts/verifier_box.sh wait <id> loop-<rung>  # blocks; run it in the background
  ./scripts/verifier_box.sh down <id>             # ALWAYS, before you report; then `census` shows none of yours
  ```

  The wait prints the verdict and the `banked:` lines; the `tree=` there
  must equal your `git rev-parse HEAD^{tree}` — paste both. A `--loop` on
  this machine refuses and prints that recipe unless `DJB_LOOP_HERE=<who and
  why>` is typed; the reason lands beside the verdict. A drive your rung
  rewrites may also run on the box: `./scripts/verifier_box.sh run <id> --
  "cd /home/verifier/src && bash scripts/tests/test_x.sh"` — ONE quoted
  string; the wrapper joins its arguments with spaces and the box's shell
  re-parses them, so no `$VAR`, no `\n`, no unquoted pipes.
  `./scripts/verifier_box.sh pool --want N` exists and `up` claims a warm box
  when there is one; measured worth is ≤ 3 min a rung, so it is the PM's choice
  for a wave, never a builder's step.
- **`./scripts/check.sh --loop` is your per-rung gate.** The full gate runs
  once at the PM's push; do not run it by hand — with two exceptions where it
  uniquely binds: rungs touching `quality/**` (the canary self-test is their
  point) and rungs touching dependencies (the supply-chain leg).
- **Two narrower runs exist for the two questions that used to cost a whole
  tier**, and both say in their own output what they did not look at:

  ```bash
  ./scripts/check.sh --census > "$PWD/census-<rung>.log" 2>&1   # the instrument census, alone
  echo $?
  ./scripts/check.sh --loop --mine > "$PWD/mine-<rung>.log" 2>&1   # your app's inner loop
  echo $?
  ```

  **`--census`** runs the instrument census and nothing else — no lease, no
  lock, no pytest slot, no leg banner, and it exits with the census's own
  status. It is the leg that reds when a rung added an instrument and has not
  written its row in `docs/product/instruments.md`, and asking for that answer
  used to mean a whole `--fast`. Run it while you still have the paragraph in
  your head, not after the commit message is written.

  **`--loop --mine`** is the per-rung gate with the `depends_on` closure NOT
  walked: your touched apps run in full, the always-on cross-app tripwires run
  as they do at every scope, and nothing else is selected. It is an inner-loop
  run, and it is honest only because it says so — **a `--mine` green is a claim
  about one app**, it prints that, it neither consults nor banks a loop verdict,
  and a regression it cannot see is one in a DEPENDANT of your app. So: `--mine`
  between boundaries if you like; the ordinary `--loop` at your last boundary,
  after the fold, and that is the one whose `banked:` key goes in your report.
- **A by-hand full gate TYPES ITS SANCTION, and the valve COVERS the two
  exceptions above** — it does not close them. The gate now refuses an
  unsanctioned full run (exit 2, taking no lease and no slot): a full run is the
  most expensive thing on the machine and every other full gate queues behind
  it, so an unaccountable one spends everybody's minutes and not only its own.
  In a rung worktree the sanction is the whole ceremony, and it is one line:

  ```bash
  DJB_GATE_SANCTION="<your rung id>: quality/** rung — the canary self-test is the point" \
    ./scripts/check.sh > "$PWD/gate-<rung>.log" 2>&1
  ```

  The shape is `<rung-id>: <reason>` and it is checked — an empty or shapeless
  value is exit 2, never a silent default. What you type is printed in the
  gate's header and written into the verdict row (`sanction=`), so the
  population of hand-run fulls is readable afterwards instead of inferred.
  `--fast` and `--loop` are untouched by the valve and need no sanction, ever.
  `--bank` is the PM's ritual flag, legal only from the primary checkout or
  `pm-push` — from a rung worktree it exits 2 and points you at the line above.
- **A `quality/**` rung COMMITS before its full gate** — the canary self-test
  refuses a dirty plant path, so an uncommitted tree turns the rung's own
  proof into exit 2. Commit first, through the hook, then run.
- **COMMIT THROUGH THE HOOK. Both bypass forms are forbidden by name —
  `--no-verify` and `core.hooksPath` — and it is the OPTION that is refused,
  never a particular value:** not `/dev/null`, not an empty directory, not a
  path that does not exist (which unhooks SILENTLY, and reads in the log
  exactly like a hook that ran). **A red
  hook is a boundary to fix at, never a gate to step around**: the hook runs
  `--fast`, so its red is the same red the gate will print at push, found at
  the cheapest moment anyone will ever find it — and the three times it was
  stepped around in one cycle, the hook had caught a real defect at least once.
  When the hook genuinely cannot run — an environment that has no venv yet, a
  tool the checkout has not provisioned — the route is **fold main, then run
  `--fast` by hand and paste it**, and that is the only form; it goes in your
  DEVIATIONS with the reason, per §6.
- **Run it unpiped, redirected to a file, and read the file:**

  ```bash
  ./scripts/check.sh --loop > "$PWD/gate-<rung>.log" 2>&1   # YOUR rung's id, in YOUR worktree
  echo $?
  ```

  The exit status is the verdict: **0 clean · 1 violations · 2 enforcement
  broken**. The gate refuses a piped stdout with exit 2 by design; `| tail`
  replaces its exit status with `tail`'s. **Never filter the output of
  anything whose exit status you intend to trust** — greping a log for "ok" is
  how a red run reads as green.

  **Name it `*.log` and nothing else.** That suffix is ignored (`.gitignore`),
  and being ignored is what lets the run bank its verdict: the gate keys a
  verdict on the working tree measured through `git add -A`, so a log file the
  gate can read is a file that GROWS WHILE THE GATE RUNS — start and end
  disagree, and a green ~8-minute full run prints "no verdict recorded — the
  tree changed while the gate ran" and vouches for nothing, so the PM's push
  measures the whole thing again. A `gate.out`, a `gate.txt` or a `check-log`
  in your worktree still does exactly that.
- **Every log you write carries YOUR agent or rung id and lives in YOUR
  worktree** — `"$PWD/gate-<rung>.log"`, `"$PWD/serve-<rung>.log"` — never a
  bare `gate.log`, `serve.log` or `worker.log` in the shared scratchpad, because
  those are the exact names every skill here prescribes, so five lanes writing
  them write ONE file: a cross-lane verifier once read another agent's
  structlog out of its own `serve.log` and spent the time proving those
  requests had never touched its database. A verifier's log path is its own
  by construction or it is nobody's.
- **Exit 2 means the enforcement is broken, not your code.** Stop and report
  it; do not work around it.
- **When a refusal prints `offer:`, run the offer — do not do it by hand.**
  Three of this gate's refusals end in a piece of bookkeeping the refusal
  itself describes, and each now names the one command that applies it:
  `./scripts/rung_tidy.sh --budgets` (a red house-rules leg carrying a
  `budget:` line), `--client` (the fe leg's `CLIENT SUSPECT` state),
  `--secrets` (a bank whose fold printed `BASELINE SHIFTED`, read at the start
  of the next rung). The tidy applies each subject THROUGH the instrument that
  already owns it, writes into the working tree, and stages and commits
  nothing — so the change lands in your own diff, which is where a budget raise
  belongs. It never runs the gate, and its `--secrets` subject goes through the
  fold, which folds a COMMITTED tree: run that one at a boundary.
- **Secrets are met immediately.** The `--loop` secrets leg scans your
  changed files; a false positive gets `# pragma: allowlist secret` with the
  reason, now, while the string is still in your head — never deferred to
  push. House rule 23's own scanner is a separate raw regex over `apps/`,
  `config/` and `scripts/` with no pragma path, so a fixture that must carry a
  key-shaped string keeps it out of the file's text — assembled at runtime,
  `scripts/archaeology_lib.sh`'s idiom in `archaeology_patterns` — rather than
  spending a `# rule-23:` valve on it.
- **`.secrets.baseline` HAS ONE LEGAL WRITER, AND IT IS NOT YOU.** The fold's
  full-tree re-scan writes it (`scripts/pm_fold.sh`, step (c), which strips the
  `generated_at` stamp so the committed file never carries one — the scanner
  rewrites that line on every run, so a committed stamp is a line every two
  lanes conflict on); every other invocation in the tree reads it. That is not tidiness, it is a measured
  hazard: `detect-secrets scan --baseline .secrets.baseline <paths>` — the
  fold's own command with paths appended — DROPS the result line of every file
  it was not handed, exits 0, and prints nothing. The sibling platform lost 77
  result lines to it twice and reverted both by hand (2026-09-02 intake); it
  reproduces on our installed version, and both directions are pinned in
  `scripts/tests/test_secrets_baseline_guard.sh`, which prints the version each
  verdict belongs to. The per-rung leg is safe because it runs the OTHER
  subcommand — `detect-secrets-hook --baseline`, which preserves what it did
  not scan — so **never point `--baseline` at the tracked file from a terminal,
  and never over a subset.** Nothing mechanical stops you: rule 23 sees a
  secret in the tree, never a baseline that quietly stopped looking for one.
  If you need to try something against the baseline, copy it first and aim at
  the copy; that is the same reason a destructive demonstration builds its own
  victim (§2).
- **Two `--loop` setup facts a finisher paid to learn; neither is a defect.**
  (1) A plant or measurement fixture must be **ruff-format-clean**, or
  `--loop` stops at the ruff leg and the pytest leg never measures it — the
  plant then proves nothing and the run looks like a code failure. (2) An
  untracked executable *inside* the checkout reds `--loop` at the instrument
  census (`scripts/goalpost_scan.py`, `tracked_and_new()`) **by design**: see
  the one scratch location, next.
- **THERE IS ONE SCRATCH LOCATION, AND IT IS OUTSIDE THE CHECKOUT: your
  session's scratchpad.** Every probe, clone, plant harness, throwaway script,
  intermediate file and captured output that is not a `*.log` your report cites
  goes there — never beside the tree it measures, and never in a new directory
  inside the checkout invented for the purpose. The checkout is what the gate
  MEASURES: an untracked executable in it reds the instrument census by design
  (above), an untracked file in it moves the tree the verdict is keyed on, and a
  scratch directory in it is a thing the next builder has to decide about. The
  two exceptions are named and neither is scratch: the `*.log` files this
  section tells you to write in YOUR worktree, and the schema dump step zero
  writes (§0) — output an instrument produced, not a place to work.
- **Fold main at your last boundary, `--loop` after the fold, paste the key.**
  The verifier's consult is one `--loop` in its own clone, and that clone is
  the UNION of your branch and main — so a verdict banked on a tree that never
  saw main's tip banks a key nobody will hit. Fold, run `--loop` once, and
  paste the `banked:` key it printed (`LOOP_VERDICT_KEY`) into your report so
  the verifier can compare keys when it misses. A commit made *after* that run
  moves the tree and the consult reads `miss(tree)` — the correct outcome, and
  an avoidable one. **Folding main is `git merge main` in your worktree** —
  never `scripts/pm_fold.sh`, which is the PM's post-merge fold of derived
  files and has nothing to do with this. §6 fixes the two lines your report
  owes about it, and `verify_start.sh` prints the fold point it will be
  compared against.
- **Rung duration discipline.** Run
  **targeted tests between boundaries** — `uv run pytest
  apps/<x>/tests/test_<y>.py`, the file you are changing, not the suite. **And
  no `-n` between boundaries** — this box's cores are already split into pytest
  slots that the gates hold, so `-n auto` from a builder's own run takes every
  one of them (and mints a test database per worker); `scripts/test.sh` refuses
  it and a typed number above the slot share is clamped with a printed line. Run
  the `--loop` **once at the end of the rung**, and once at any boundary you
  hand over (commit-at-boundaries stands). And amendments arrive
  **at boundaries unless blocking**: the PM holds a non-blocking amendment for
  your next boundary, and you do not stop mid-leg for one. The worked example
  is the c1 rider of 2026-09-07 — the finisher holding it took it at its own
  report boundary rather than mid-leg, and nothing waited on the difference.
  **And `pm_push.sh --bank` takes EVERY pytest slot for its run**: a `--loop`
  that arrives waits, naming the bank, for roughly the bank's pytest wall, and
  `DJB_GATE_SLOT_MAX_WAIT` refuses (exit 2, could-not-look — a re-run, never a
  red tree) a loop that queued past the ceiling. `--loop --mine` and targeted
  `pytest` between boundaries are how a builder keeps moving while a bank holds
  the box. **Unless the push is documentation only** — when every path changed
  since the last MEASURED tree is on the declared list
  (`GATE_DOCS_ONLY_PATHS`, `docs/**`, `README.md`, `CLAUDE.md`,
  `.claude/skills/**`, `scripts/test_impact.json`; `CHANGELOG.md` and
  `TEMPLATE_VERSION` are deliberately OUT because pytest reads them), the bank
  runs only the readers those paths have, takes no slot and no box, and banks
  an ordinary row in seconds; anything else, including a docs path a module
  under `apps/` really opens, is the full bank as before and says so
  (`docs/product/build-contract.md` § "The docs-only push path"). **The
  refusal names `file:line`, so it is a thing you can go and look at** — today
  a commit touching the build contract itself pays a full bank, because a test
  asserts that file's name in an assert's quoted string, and the road says which test
  rather than leaving you to guess why your documentation push cost 25
  minutes.
- `./scripts/test.sh` exits with pytest's own status and is never piped
  either. A red order replays with `--randomly-seed=<the printed seed>`.

## 3+ · When the deliverable is a screen

A rung whose output is rendered rather than returned changes nothing about §2,
§3 or §6 — it *specialises* them, and this section is the whole of the
specialisation. How the client itself is written is
`.claude/skills/fe-conventions/SKILL.md`; load it the way a rung touching
`apps/` loads `django-conventions`.

**Screen red-first is a RENDERED fact, never a sentence.** A wire criterion
goes red as a failing assertion; a screen criterion goes red the same way, and
the red is one of exactly two shapes:

- **absent** — the route or the state does not exist. The rendered check
  reports the not-found, and *that report* is the red you paste.
- **the undesigned default** — the route exists and renders the framework's
  or the browser's own answer: the unstyled error page, the user-agent blue,
  the raw JSON, the spinner that never resolves. This is the shape that gets
  waved through, because a page that renders looks like a page that works.

Both are shown **by running the rendered check**, never by describing them.
"The screen currently has no empty state" is prose; the empty state rendered
at a named route with seeded data that produces zero rows, captured, is
evidence. **A screen criterion whose red was only asserted in words did not go
red** — it is a criterion that may be unable to fail, which is exactly what §2
exists to prevent, and a rendered surface is where that failure is easiest to
miss.

**The rendered check is an instrument, not a look.** It answers three closed
questions — hydration completed, the console is clean, computed styles resolve
to real values — and it fails loud when it cannot look, like every other
instrument here: a browser that would not start is could-not-look (exit 2),
never a pass on the pixels nobody saw. Its mechanics, and its declared blind
spots, live in `fe-conventions`; where a product has not built it yet, say so
and report what you ran instead, rather than letting prose stand in for a
render.

### The screenshot report contract

A screenshot is evidence of **rendering**, and of nothing else. It never
replaces a wire assertion, and a report that leans on one to claim behaviour
has swapped an instrument for a photograph. What a screen rung's report owes,
on top of §6:

1. **Pairs, never singles.** The same route at the same viewport, red and
   green. One image proves a page exists; two prove the rung changed it.
2. **Every image names its four coordinates** — the route, the viewport, the
   surface state it is in, and the seeded data behind it. An unlabelled
   screenshot is unfalsifiable: nobody can re-take it.
3. **The console output is pasted, not summarised.** "Console clean" is a
   claim; the empty capture is the artifact. A warning you decided was
   harmless is reported as a warning you decided was harmless.
4. **Files carry your rung id and live in YOUR worktree** — the §3 log rule,
   unchanged and for the same reason: `screenshot-<rung>-<route>-<state>.png`,
   never a bare `screenshot.png`. Five lanes writing the house's default name
   write one file, and the one that survives is not yours.
5. **Every image earns its criterion, and the criterion sets the count.** The
   set a criterion claims IS its coverage: a criterion over four authored
   surface states owes four images, and shipping three of them is a gap, not
   economy. What is banned is the image that proves nothing — a contact sheet
   of everything the rung happened to look at is not a report; it is a place
   for a reviewer to lose the images that mattered.

**The partition, so the two skills cannot pull against each other.** This
section owns the report **shape**: what an image must carry, what a set of them
is for, and where the files live. The **drive-side** additions are
`fe-conventions`' — the per-state coverage floor, the hydration output, the
seeded-world captions — and that skill defers here for shape. Where they look
like they disagree, the shape rule above is the one to follow and the apparent
disagreement is a finding, not a judgment call.

### Which gate a screen rung runs

Unchanged: `./scripts/check.sh --loop` is still your per-rung gate (§3). Two
of §3's clauses apply to screen rungs more often than to any other kind, and
both are cited here rather than restated — **§3 is the authority and this
section adds nothing to it**:

- **A rung that touches the package manifest or its lockfile is a dependency
  rung — and it says which tooth it is standing on.** §3 names dependency
  rungs as one of its two full-gate cases because of the supply-chain leg, and
  that leg's population is the Python one today. A product whose leg has not
  yet grown a client-side half therefore has **no supply-chain tooth for the
  full gate to bind on**, and running it buys the rung nothing: `--loop` is
  your gate, and the exclusivity law in the dispatch contract is the whole of
  the protection — say so rather than implying a leg looked. When the leg does
  gain that population, §3's dependency case covers it unchanged: run it the
  way **§3's typed-sanction bullet** says, which is the ceremony in full, and
  this line adds nothing to it.
- **A screen rung that also plants canaries or fixtures under `quality/**`
  commits before that full run**, per §3's commit-before-full-gate bullet, for
  the reason stated there — the self-test refuses a dirty plant path.

Neither clause is new and neither is widened here. If what you need is not one
of those two cases, `--loop` is your gate and the full gate is the PM's.

## 4 · Territory, and when to stop

Your territory is the brief's file set. The escalation pattern:

- **An out-of-territory need → FLAG AND HOLD.** Name the file, the exact
  change, and why your criteria need it; put it in your report (or hand it up
  mid-rung if it blocks you) and do not make the edit. A rung that needed a
  test fixed outside its territory has flagged instead of editing before —
  that is the model. The one exception is a change the brief itself sanctions
  by naming the exact line, spelled out in the dispatch.
- **A migration conflict** is an ordering failure, reported, never merged
  (§1).
- **A classifier or permission denial** is reported as its own line — what was
  refused, verbatim — never worked around or retried into silence; a retro
  cannot audit what left no artifact.
- **A brief claim your evidence disproves** — say so, with the evidence, and
  proceed on the truth where the criteria still make sense; hold where they
  do not. Disproving the brief is encouraged and has repeatedly been a
  rung's most valuable output — brief errors disproved with evidence, or a
  whole dispatch caught as stale before any work went into it.

## 5 · Standing safety

- **Stage explicit paths; never `git add -A`.** The staged set is the claim.
- **Commit at every rung or leg boundary** — a commit is not "proven", it is
  "this is what I wrote"; a killed session then loses minutes, not the rung.
  **Every one of those commits goes through the hook** (§3): a boundary commit
  the hook reds is a boundary with a defect in it, and stopping there is the
  cheapest the defect will ever be.
- **Your worktree, your database.** `./scripts/setup.sh` (which sources
  `scripts/db.sh`) derives and prepares this checkout's own Postgres database;
  nothing you run touches another agent's tree or data.
- **Run anything long in the background with output to a file**; read the
  file when it finishes. A stream stall then costs the rendering, not the
  work.
- **Kill only your own children** — by pid, `pkill -P`, or
  `scripts/kill_mine.sh`; never by name. `pkill -f pytest` has killed other
  agents' gates twice.
- **No mutation scripts with relative paths in the shared scratchpad** —
  absolute worktree-pinned paths or direct tool edits only; a relative-path
  script run from one agent's tree has applied its edit to a different tree
  before.
- **Do not spell a censused marker in prose.** Guards count marker-shaped
  strings wherever they appear, docstrings included: never mention `shell:` in
  the Remedy docstring, and in general a sentence that spells a marker is a
  phantom registration — prose spelling the marker gets counted just like real
  code, and must be reworded instead.

## 6 · The report contract

First line: **still working** · **done, stopping** · **stuck on X**. Then:

1. **`git branch --show-current` output** — pasted, never a remembered name
   (a misnamed branch has made a merge silently fail before) — and the final
   commit sha, plus the baseline sha from step zero (and the reset, if any),
   and the `banked:` key your last `--loop` printed (`LOOP_VERDICT_KEY`) — the
   verifier's consult compares keys when it misses, and cannot without yours.
   **Two of those are lines with a fixed spelling, and a report without them is
   one the verifier sends back**:

   ```
   fold: main@<sha> merged at <commit>
   banked: tree <sha> key <loop key>
   ```

   The first names the main you folded and the commit that folded it; the
   second is the last `--loop`'s own banner, verbatim. They are spelled rather
   than described because they are **read by arithmetic**: `verify_start.sh`
   prints the clone's `fold point   <sha>`, and a fold sha that does not equal
   it is a finding — a rung that folded, edited and never re-folded, or never
   folded at all — caught before a minute of verification is spent on it. And
   **no commit after the fold except ones that last `--loop` measured**: the
   measured tree reads through `git add -A` (`scripts/gate_ledger.sh`), so
   committing bytes the loop already saw keeps the key, while writing new ones
   moves it and costs the verifier the whole suite.
2. **Red-first evidence, pasted** — the red and the green, per §2.
3. **Per-criterion status** — each criterion from the brief, met/not-met, with
   the artifact that proves it (a test, a wire response, a file:line). A
   claim with no artifact is a hypothesis wearing a status.
4. **DEVIATIONS — all of them, none silent**: every departure from the brief,
   the conventions, or this file, with the reason — the worked forms:
   self-reporting a commit the hook could not run on, with the fold and the
   manual `--fast` that covered it pasted (§3 — the bypass options themselves
   are forbidden, so what is being reported is a hook that could not run, never
   a hook that was told not to), or self-reporting a `git add -A` with the
   staged set verified.
5. **Things DISPROVED in the brief**, with evidence (§4 — encouraged).
6. **Declared blind spots** — what your work does not cover and what could go
   wrong that your tests would not catch; this becomes the ledger row's
   frontier clause.
7. **Lexicon delta** — any addition to the declared vocabularies (a service
   verb, an event name, a tag, a refusal code, a rules.yaml allow-list line),
   so the PM can propagate it.
8. **The cleanup census** — everything you created that outlives the report is
   a leak: stacks down, `_perf`/`_hp` worlds dropped, only your worktree and
   its database left for the merge ritual. **A timer, a wait or a poller you
   started is part of that census** — killed and counted before the done
   report, because one left running fires after you have stopped and delivers
   a duplicate done-notification for a rung nobody is still building. And the
   census has nothing to count if you never left the turn:
   **Never end a turn while a run of yours is in flight** — wait on it bounded
   in the foreground (a Monitor, a bounded wait), never sleep-poll and never
   yield on the promise that a detached run will report itself; a turn that
   ends with a run detached is a rung sitting idle until the watchdog (two
   strikes in one hour, 2026-09-07: GQ-1F and VEL-1F).

A template with the section headers is in `references/worked-examples.md`.
