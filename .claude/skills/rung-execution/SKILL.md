---
name: rung-execution
description: >-
  Load FIRST, at the start of every development rung, before touching the tree
  — then load django-conventions before writing any Python. This skill is how a
  rung is EXECUTED here: the baseline check, the born-to-standard checklist,
  the gate discipline, red-first, the report contract, and when to stop and
  flag instead of edit. It exists so a dispatch brief can shrink to territory +
  criteria pointer + what is unusual; everything execution-generic lives here.
  NOT how to write the code (django-conventions), NOT what to build or whether
  it is done (the PM's and the field test's). Every claim cites its rule id or
  the ledger row that paid for it.
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
and **dumps `introspect` to `.rung/introspect.json`**. Each step prints what it
did and how long it took, and the total is on the last line.

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
was written against**. That half is still yours: **a brief naming a baseline sha
that is neither HEAD nor main → flag it and hold**; do not guess which tree the
criteria were written against.

If the instrument is unavailable or exits 2 for a reason you cannot clear, the
equivalent by hand is `git log -1 --oneline HEAD` against
`git log -1 --oneline main`, and `git reset --hard main` only if you are behind
**and have not committed yet** — that clause is what the commits-ahead refusal
mechanises.

Then orient: load `.claude/skills/django-conventions/SKILL.md` before writing
any Python; read the criteria from where the brief points (verbatim, not from
memory); for any rung touching models, schemas, routes, tools, consumers,
workflows or settings, **read the dump step zero already wrote** —
`.rung/introspect.json`, current as of the reset baseline — or re-run
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
- **Scope families by the codified pattern** (django-conventions §6, beside
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
  the field, never silently dropped (django-conventions §6; the MCP door is
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

## 3 · The gate

- **`./scripts/check.sh --loop` is your per-rung gate.** The full gate runs
  once at the PM's push; do not run it by hand — with two exceptions where it
  uniquely binds: rungs touching `quality/**` (the canary self-test is their
  point) and rungs touching dependencies (the supply-chain leg).
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
  proof into exit 2. Commit first, then run; a hook-bypassed commit made for
  this reason states it in the commit message and is covered by the clean
  gate that follows.
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
- **Secrets are met immediately.** The `--loop` secrets leg scans your
  changed files; a false positive gets `# pragma: allowlist secret` with the
  reason, now, while the string is still in your head — never deferred to
  push.
- `./scripts/test.sh` exits with pytest's own status and is never piped
  either. A red order replays with `--randomly-seed=<the printed seed>`.

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
  A WIP commit that skips hooks is legal only under genuinely unstable
  conditions, only if the tree is fully gated afterwards, and only reported
  with your deviations.
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
   commit sha, plus the baseline sha from step zero (and the reset, if any).
2. **Red-first evidence, pasted** — the red and the green, per §2.
3. **Per-criterion status** — each criterion from the brief, met/not-met, with
   the artifact that proves it (a test, a wire response, a file:line). A
   claim with no artifact is a hypothesis wearing a status.
4. **DEVIATIONS — all of them, none silent**: every departure from the brief,
   the conventions, or this file, with the reason — the worked forms:
   self-reporting one `--no-verify` and the manual `--fast` that covered it,
   or self-reporting a `git add -A` with the staged set verified.
5. **Things DISPROVED in the brief**, with evidence (§4 — encouraged).
6. **Declared blind spots** — what your work does not cover and what could go
   wrong that your tests would not catch; this becomes the ledger row's
   frontier clause.
7. **Lexicon delta** — any addition to the declared vocabularies (a service
   verb, an event name, a tag, a refusal code, a rules.yaml allow-list line),
   so the PM can propagate it.
8. **The cleanup census** — everything you created that outlives the report is
   a leak: stacks down, `_perf`/`_hp` worlds dropped, only your worktree and
   its database left for the merge ritual.

A template with the section headers is in `references/worked-examples.md`.
