# Changelog

What changed in **the template's system layer** — the part a product inherits
and, one day, wants to pull again.

## How a product takes a release

**Releases are commits, not downloads.** Each version is ONE squashed commit on
the template's default branch, tagged `v<TEMPLATE_VERSION>`, and its tree is the
whole template at that version rather than a delta. A product adds the template
as a remote once and merges the tag it wants:

```sh
git remote add template <the template's repository>   # once
git fetch template --tags
git merge v2.0.0
```

**Intermediate releases cost nothing.** The chain is linear and every release
commit carries the entire tree, so a product sitting on `v1.0.0` merges
`v1.4.0` directly and never walks the versions in between. A product cloned
from the template shares its root commit, so the merge base always exists and
the merge is an ordinary one: files nobody edited locally fast-forward in
silence, and a file a product has changed comes back as a normal conflict in
that file alone. That is the whole reason a release is a commit — re-cloning
would throw away every local change; merging adjudicates them one file at a
time.

`TEMPLATE_VERSION` records which release a checkout is on. There is
deliberately **no sync tooling** beyond that (`docs/product/architecture.md`);
the trigger for building `scripts/template_sync.sh` is three products existing.

So an entry here answers one question — *would somebody who cloned this last
month want to pull this, and what would it change under them?* — and nothing
else. No counts of anything, no status: those go stale without this file
changing, which is the failure mode `CLAUDE.md` names.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html), where a
**major** is a change a product cannot take without editing its own code, a
**minor** adds something a product can ignore, and a **patch** fixes something
that was already meant to work.

## [Unreleased]

## [2.0.0] — A rung costs minutes

**A major, by this file's own definition.** The versioning note above calls a
major *a change a product cannot take without editing its own code*, and this
release is exactly that: the list below is not a set of nice-to-haves, it is
what a product has to do for its gate to run at all afterwards. Items 1-3 are
load-bearing and go together; item 4 applies only to a product that has a
`frontend/`; item 5 is genuinely optional. Everything past the list is
machinery a product either inherits untouched or can ignore.

What the release is for: the per-rung gate runs the tests a change can
actually reach instead of most of the suite, a red prints its own remedy and
its own escape hatch, a wait says who it is waiting for, the ledger a cold
reader starts from is a generated index rather than a third of a megabyte, and
a long list of instruments that used to pass while seeing nothing now refuse
instead.

### What a product does at the merge

Items 1-3 are one change, not a list of three. The gate script, the pytest
runner it hands its scope options to, and whatever is currently deciding your
test scope are one mechanism split across files; move one and leave the others
and a product has no working per-rung gate at all. Take them together or take
none of them.

1. **Take `scripts/check.sh` wholesale.** Every region of the gate script
   moved — the mode parser, the scope derivation, the leg helpers, both pytest
   legs, the self-test leg, the refusal banners, the verdict. Resolve this
   file's conflict in favour of the template's version and re-apply local
   edits on top; merging it hunk by hunk is the slowest way to take this
   release.
2. **Fold `apps/conftest.py` in the same breath — item 1 does not work
   without it.** The gate script now hands pytest `--djb-tests-only=<label>`
   and `--djb-changed-test=<path>` on every scoped run
   (`scripts/check.sh:1937-1940`, `scripts/loop_tier.sh:962-965`), and those
   options are defined in `apps/conftest.py`. Take the new gate script and
   leave the old conftest in place and pytest exits immediately on an
   unrecognised option — not a narrower run, not a red test, but no per-rung
   gate at all, on every invocation. `conftest.py` also carries the worker clamp and its printed
   escape (`DJB_PYTEST_UNCAPPED`). Fold `pyproject.toml` with it, where
   `[tool.pytest.ini_options] addopts` loses `-p no:cacheprovider`.
3. **Retire any local fork of the loop scope.** The closure over `depends_on`
   and the tests-only rule are the platform's now, in `scripts/loop_tier.sh`
   and `apps/conftest.py`. A product carrying its own scope-selection flag
   deletes it and takes these instead — two derivations of *which tests does
   this change reach* is exactly the drift the mechanism exists to prevent,
   and the forked flag is not what the new gate script passes.
4. **If you have a `frontend/`, you have acquired a gate leg and four house
   rules.** `--loop` now runs `scripts/fe_gate.sh` over it, and rules 50-53
   scan it. Expect the first run after the merge to find things; budget for
   it. `pnpm` must be on `PATH` when the leg has work to do, or the leg is
   exit 2 — could-not-look, never a pass. A repository with no `frontend/`
   directory pays nothing: the leg prints `ABSENT` and exits 0, all four rules
   print their skip, and every one of their floors derives to zero. The rules
   in one line each: **50** no credential-shaped name holds a quoted literal;
   **51** imports flow one way down the layer chain; **52** no `index` file
   re-exports another module; **53** every design token declared has a reader
   and every token read is declared. Each takes a `// rule-5<n>: <reason>` on
   the flagged line or in the comment block directly above it, and a reason
   under twelve characters is itself a finding.
5. **Optional, and the only optional item here: wire
   `./scripts/check.sh --pr --base <sha>` into CI.** Skipping it breaks
   nothing — the mode simply goes unused. The template's own
   `.github/workflows/ci.yml` does not call it either. A product that wants a
   pull-request gate adds that one step, handing it the base sha its CI
   already knows.

### Added

- **A frontend gate leg.** `--loop` now sources `scripts/fe_gate.sh` and runs
  it over `frontend/`, in four printed states: `ABSENT` (no such directory —
  exit 0, nothing runs, which is what this template itself is), `UNTOUCHED`
  (the directory exists and the change did not reach it — exit 0, the package
  manager is never invoked), `CLIENT SUSPECT` (the change did not touch
  `frontend/` but did touch the contract the committed client is generated
  from — `config/api.py`, `config/urls.py`, `apps/*/api.py`,
  `apps/*/schemas.py`, `apps/core/exceptions.py` — so the leg names those
  files and points at `./frontend/scripts/pin_client.sh`, exit 0), and the
  full run (`pnpm install --frozen-lockfile` then the declared `test` script).
  A lockfile that no longer satisfies the manifest, or a failing test, is exit
  1; a touched `frontend/` with no `pnpm` on `PATH`, no `package.json` or no
  lockfile is exit 2 — could-not-look, never a pass. `FE_FRONTEND_DIR` and
  `FE_PNPM` override the directory and the binary.
  (`scripts/fe_gate.sh`, `scripts/tests/test_fe_leg.sh`.)
- **Four house rules over the browser tree, 50 to 53**, each skipping with a
  printed line and a zero floor on a repository that has no `frontend/`.
  **50** — no binding or property with a credential-shaped name (`secret`,
  `token`, `credential`, `password`, an api/private/signing/access key; names
  ending `hash` excluded) holds a quoted literal; the value comes from the
  build environment. **51** — imports flow one way down
  `copy <- tokens <- primitives <- components <- screens <- app`, with
  journeys above app and the generated API client reachable only from the top
  two, the one exception being a type-only import of the client's document
  shapes. **52** — no file whose stem is `index` re-exports another module;
  import from the module that defines the thing. **53** — every custom
  property declared under `frontend/src/tokens/**` is read somewhere, and
  every `var(--name)` read names a declared one; the second direction is the
  one that fails open to a browser default. Each takes
  `// rule-5<n>: <reason>` on the flagged line or in the comment block
  immediately above it, and a reason under twelve characters is itself a
  finding. (`quality/rules.yaml`, `quality/runners/js_secrets.py`,
  `js_ingredient_boundary.py`, `js_no_barrel.py`, `js_token_consumer.py`, and
  the planted corpora under `quality/canary/50..53/` and
  `quality/negative/50..53/` that prove each rule can still fire and still
  stays quiet on the shapes it must not flag.)
- **`.claude/skills/fe-conventions/SKILL.md`** — the client-side twin of the
  Django conventions skill: the pinned stack, the layer contract, the surface
  state, the four laws of the client seam, the paid-for wrong forms, the
  browser drive and its screenshot report contract, and what deliberately does
  not transfer from the backend rules.
- **A rule can now be enforced by a runner written in another language.**
  `quality/check_v1.py` is the protocol: the engine invokes the runner as a
  subprocess and it answers only *what did you see* — a closed JSON reply of
  files scanned plus findings — while every verdict semantic (overrides,
  ratchets, floors, the 0/1/2) stays on the engine side. Every way a runner
  can fail to be believed is its own named refusal and all of them are exit 2:
  absent, not executable, crashed, timed out, unparseable reply, unknown key,
  wrong protocol, a finding outside the roots it declared. The one thing it
  refuses to do is read a crashed runner as "no findings".
  (`quality/check_v1.py`, `quality/runners/__init__.py`,
  `quality/runners/_kindscope.py`, and the deliberately malformed replies in
  `quality/runners/fixtures/` that are the seam's own canaries.)
- **A rule can declare the tree it needs, and get a legal skip when it is
  absent.** `quality/worlds.py` gains a second world axis — which trees this
  checkout holds, beside which apps — and a three-way verdict per rule: tree
  absent is a printed skip, tree present with its toolchain absent is
  could-not-look and exit 2, both present is a run. A rule's floors derive to
  zero for an absent tree, so a product without that tree gets a quiet legal
  skip instead of a permanently unbound gate. One list of vendored directories
  to ignore is read by the engine and every runner from the same place.
- **The queue ledger is an index over a detail file.** `scripts/queue_index.py`
  splits the one ledger in two — the detail file keeps every row verbatim
  under a stable anchor, and the index is *generated*: the preamble and the
  headings verbatim, one line per row carrying its head and a link. A cold
  reader reads the index; the file that had grown past a third of a megabyte
  is no longer the first thing anyone opens. `--split` migrates once,
  `--index` regenerates, `--check` is a `--fast` leg, and `--unsplit`
  reproduces the pre-split file byte for byte, which is the exit. `--check`
  judges anchor uniqueness and placement, a one-to-one match between anchors
  and index rows, each row's head and status, and whole-index equality with
  its own regeneration; it also carries a byte ceiling that ratchets down on
  its own and only ever up by hand. A repository that has not split yet gets a
  printed named absence and exit 0; a half-migrated one is exit 2. **Edit the
  detail file and re-run `--index`** — hand-editing the generated index is a
  red. (`scripts/queue_index.py`, `scripts/tests/test_queue_index.sh`.)
- **`./scripts/pm_fold.sh`** — one command that regenerates the files nobody
  should be hand-editing and commits them alone: the generated OpenAPI
  document and client types, the secrets baseline, the budget ceilings. It
  refuses a dirty tree, refuses with exit 2 if anything outside that typed
  list moved, and **never raises a ceiling** — it applies only the numbers the
  gate itself printed under its lowering sentence, counts them, and re-checks
  each one against the ceiling in the file it is rewriting. The push and merge
  rituals run it before the gate (`./scripts/pm_push.sh --bank`,
  `./scripts/pm_merge.sh --bank`), so what is banked is what is committed;
  `--no-fold` opts out, prints a loud banner saying the derived files were not
  regenerated, and is itself refused outside `--bank`.
  (`scripts/pm_fold.sh`, `scripts/pm_push.sh`, `scripts/pm_merge.sh`,
  `scripts/tests/test_pm_fold.sh`, `scripts/tests/test_pm_merge.sh`.)
- **A reviewer's clone starts with the loop verdicts already in it.**
  `scripts/verify_start.sh` gains a seed step that copies the source
  checkout's banked `--loop` rows into the clone, schema-checking each line,
  counting the ones it skipped and naming the absence when there is no ledger
  to copy — then proves it wrote nothing back to the source. The clone also
  gets a real local `main` at the verified sha, because a clone that had main
  only as a remote ref was being refused downstream. And a source checkout
  whose only dirt is under `docs/product/` no longer blocks the clone: the
  dirty paths are printed by name and the clone is taken from the commit.
  (`scripts/verify_start.sh`, `scripts/tests/test_verify_start.sh`.)
- **Twenty engineering first principles in `CLAUDE.md`** — the defaults every
  design, decomposition and review is held to, from *complexity is
  intentional* and *prefer the established technology* through idempotency,
  observability, single state ownership and the one that governs the rest:
  an exception is deliberate, written down, and approved by a human.
- **`./scripts/check.sh --pr --base <sha>`** — the full gate, same legs in the
  same order under the same lease and slot, with both pytest passes narrowed
  to the closure of what `<sha>...HEAD` changed and the organ tier not
  applied. It **banks no verdict**, because a narrowed run vouches for no
  tree. A base git cannot resolve, a base that is not an ancestor of HEAD, a
  dirty tree, an app label the declarations cannot account for or an unmet
  always-on floor are all exit 2, above the lease — never a smaller run.
  (`scripts/check.sh`, `scripts/loop_tier.sh`,
  `scripts/secrets_scan.sh`'s base-ref, `scripts/tests/test_loop_scope.sh`.)
- **`./scripts/check.sh --loop --mine`** — the per-rung gate with one
  narrowing: your touched apps run in full and the reverse `depends_on`
  closure is *not* walked. It prints that it is an inner-loop run and it
  neither consults nor banks a loop verdict, because a green `--mine` is a
  claim about one app. (`scripts/check.sh`, `scripts/loop_tier.sh`.)
- **`./scripts/check.sh --census`** — the instrument census alone: no lease,
  no lock, no pytest slot, no leg banner, exiting with the census's own
  status. It is the leg that reds when you added an executable and have not
  written its row, and asking for that answer used to cost a whole `--fast`.
  (`scripts/check.sh`.)
- **`manage.py newapp <label>`** — the app generator, Django's `startapp` with
  this house's template. It emits the canonical file set and nothing else, an
  `apps.py` carrying `depends_on`, and a door-parity stub that skips until a
  door exists; the result is green under `--fast` with nothing but the label
  filled in, and a label that would red is refused rather than generated.
  (`apps/core/management/commands/newapp.py` and `management/app_template/`.)
- **A red now prints its own paperwork.** Every rule violation ends in four
  keys — `doc:` where the rule is written down, `valve:` how a legitimate
  exception is recorded (and `valve: none` with the reason where nothing can
  excuse it), `blind:` the first sentence of what the rule cannot see, and
  `next:` the command that prints the rest. Every rule in `quality/rules.yaml`
  owns a `valve:` entry and the gate refuses a rule that has lost one.
  (`quality/gate.py`, `quality/rules.yaml`,
  `scripts/tests/test_gate_explain.sh`.)
- **`python -m quality.gate --rules` and `--explain <id>`** — the rule set is
  now readable from the tool that runs it: `--rules` lists every rule that
  exists today, `--explain <id>` prints one in full. `CLAUDE.md` points at the
  first of those instead of carrying a hand-maintained list that went stale
  without the file changing, and the rules whose `doc:` anchor pointed into
  that list now point at `docs/product/architecture.md`, which numbers them.
  (`quality/gate.py`, `quality/rules.yaml`, `CLAUDE.md`.)
- **`./scripts/rung_start.sh --expect <commit-or-tree>`** — hand the one-command
  worktree setup the baseline you were told to build against and it compares
  before installing anything, refusing with exit 2 if the tree differs. It
  takes a commit or a tree sha and says which it was handed.
  (`scripts/rung_start.sh`, `scripts/tests/test_rung_start.sh`.)
- **A wait says who it is waiting for, and how long it waited is recorded.**
  The full-gate lease and the pytest-slot semaphore name the holding run in
  their wait lines, both pytest passes print a heartbeat while they run
  against a nominal taken from this checkout's last measured time, and the
  verdict rows gain `waited=` and `took=`. Runs that were queueing correctly
  had been killed as "hung", because queueing correctly looked like nothing.
  (`scripts/gate_lease.sh`, `scripts/gate_ledger.sh`, `scripts/check.sh`,
  `scripts/tests/test_gate_lease.sh`, `scripts/tests/test_loop_ledger.sh`.)
- **`scripts/gate_refuse.sh`, the one refusal seam** — a sourced callee records
  the first line of its refusal, and every in-process banner that used to end
  in "see above" now prints `cause:` as its second line. "See above" is worth
  nothing in a transcript that reached anyone else. A banner whose callee
  recorded nothing says so, and is exit 2. (Also `scripts/secrets_scan.sh`,
  `scripts/loop_tier.sh`, `scripts/gate_lease.sh`, `scripts/archaeology_lib.sh`,
  and the drives that assert those sentences —
  `scripts/tests/test_secrets_scan.sh`, `scripts/tests/test_loop_scope.sh`,
  `scripts/tests/test_gate_lease.sh`.)
- **A shell drive that ships unwired is now a red, not a promise.** Every
  drive under `scripts/tests/` must be invoked by a line in `scripts/check.sh`,
  and `scripts/tests/test_drive_preamble.sh` proves it — its census lists the
  directory, greps the gate script for its `./scripts/tests/test_*.sh`
  invocation lines, and fails naming any drive present in the first set and
  absent from the second. A second case pins that a drive belonging to the
  self-test leg is invoked *below* that leg's banner rather than merely
  somewhere in the file. The registration blocks marked
  `# >>> drive: <name> >>>` are the form a drive with its own setup takes;
  they are a subset, not the census's subject. New drives arrive with this
  release, each named for what it measures: the loop scope and the loop
  verdict ledger, the rule reader, the drive census itself, the early-exit
  pipe class, the fold, the queue index, the secrets baseline, the
  clone-to-running setup, the history census and the frontend leg. Which
  drives exist is `ls scripts/tests/`, and which the gate runs is the census
  above — neither is repeated here, because a list in prose is the half that
  goes stale.
- **`deploy/tests/test_compose_floor.sh`** — the properties both compose files
  must carry, asserted over the *rendered* file rather than its source text:
  the volumes a stateful service needs, log rotation on every service, the
  privilege split, retention. Hand-run, like everything under `deploy/tests/`,
  which the gate prints as a declared gap.
- **A leg can declare the tracked paths it derives**, and those paths are
  dropped from the verdict key while the files stay tracked — so a green run
  that rewrote a machine-dependent artefact still vouches for the tree it
  measured instead of banking nothing. Legal only where nothing measured reads
  them back; an unreadable declaration excludes nothing. The pre-push hook
  reads the key through the same function, so there is one key and no second
  opinion. (`scripts/gate_ledger.sh`, `scripts/githooks/pre-push`.)
- **Container log rotation and workflow-history retention in the deployment
  compose.** Every service takes a shared logging anchor, and the workflow
  namespace is registered with a 30-day retention instead of the image's own
  24 hours — which had been deleting the inputs, results and failed attempts
  of every execution a day after it closed, invisibly, because a laptop runs a
  dev server that never shows it. (`deploy/compose.yaml`,
  `deploy/env.staging.example`.)
- **Where a product's edge census belongs, written down.** A tripwire over the
  edge — proxy routes, load-balancer rules, the prefixes the front door
  answers on — goes at `apps/test_<edge>.py`, a module at the `apps/` root
  belonging to no app, which is always-on *by construction* under `--loop`,
  `--loop --mine` and `--pr`. `deploy/tests/` is the wrong home and silently
  so: pytest collects only `testpaths`, so a census there is green because
  nothing ran it. (`docs/product/build-contract.md`.)

### Changed

- **`scripts/setup.sh` now reconciles `.env` against `.env.example` instead of
  leaving an existing file alone.** It rewrites the file in the example's own
  order, keeping every value you had at the example's position, appending keys
  the example does not know about under a marked heading, collapsing duplicate
  keys last-wins, and dropping comments the example does not own. It prints
  **key names and counts, never values**, and keeps the previous file as
  `.env.previous` with owner-only permissions. The reason is measurable: the
  loop verdict's environment fingerprint hashes every line in order, so `.env`
  drift alone was turning a one-second verdict reuse into a full re-measure.
- **`scripts/db.sh` declares `DATABASE_NAME` as derived-per-checkout**, in a
  machine-read block the verdict ledger reads, so a key that is *supposed* to
  differ between two checkouts stops making their environments look different.
  With no declaration at all the whole file is still hashed — a missed reuse,
  never an unverifiable hit. (`scripts/db.sh`,
  `scripts/tests/test_db_zsh.sh`.)
- **`./scripts/sweep.sh --assert-none` stops reporting this checkout's own
  live working set as a leak** — but only on all three of: the resource is
  owned by this checkout's derived base, its class is declared non-disposable,
  and there is positive evidence of use right now (open sessions on the
  database, pollers on the queue). Each exemption prints its owner, its
  declaration and its evidence; an owned resource nobody is using is still a
  finding.
- **The publication census classifies once, and derives its own rule list.**
  The bucket rules and the six history-scan patterns moved into
  `scripts/archaeology_lib.sh`, shared by the release census and the per-rung
  leg so the two can no longer drift; the printed per-rule table reads its
  ids out of the classifier itself rather than a typed constant that had
  already gone one row stale. A new rule puts the client layer (`frontend/`)
  in the shipped set. (`scripts/publish.sh`, `scripts/archaeology_lib.sh`,
  `scripts/tests/test_publish.sh`.)
- **The full gate's skip key sees two things it used to miss.** The partition
  — the mechanism that lets a product-only change skip the platform's own
  tests — gains an **import census** that reports any platform test importing
  a product app (the import half of a coupling it could previously only catch
  as a file read), derived from the apps the lockfile does not claim rather
  than from a hand list, and proven by a planted scratch tree because on this
  template the live population is empty. It also declares `templates/**` a
  closure class, since a platform test walks that directory and asserts about
  the set it finds. (`quality/partition.py`, `quality/partition.yaml`.)
- **`scripts/goalpost_scan.py` prints its own blind spot on every run**,
  clean or not: a script with no execute bit, invoked as `bash x.sh` or
  `python x.py`, is not in the population it censuses. It was in the source
  and not in the output, so a reader of a green log could not know.
- **The method skills say the template ships a default front end** — it
  previously said it shipped none — and that the reviewer's one consult is a
  single `./scripts/check.sh --loop` in their own clone, redirected to a log,
  run exactly once, with a typed cell recording whether it hit or missed and
  why. Reviewers are also told to reproduce a baseline in a scratch clone
  rather than by stashing, to paste `file:line` from their own run, and to
  site a planted-miss demonstration in an app outside the change's closure.
  (`.claude/skills/product-manager/SKILL.md`,
  `.claude/skills/product-manager/references/dispatch-briefs.md`,
  `.claude/skills/platform-primer/references/walkthrough.md`.)
- **The per-rung gate stops running the whole closure for a test-only
  change.** A rung whose changed files under an app are all inside
  `apps/<x>/tests/**` now runs those test trees and the modules that import
  them, rather than seeding the full reverse-`depends_on` closure — which, for
  any change that reached a central app, was most of the suite. The scope is
  printed before the run, every run, with what it will not see; the cost is
  declared rather than implied. (`scripts/loop_tier.sh`, `apps/conftest.py`,
  `scripts/check.sh`, `scripts/tests/test_loop_tier.sh`,
  `docs/product/build-contract.md`.)
- **pytest's cache is back.** `-p no:cacheprovider` is gone from
  `pyproject.toml`'s `addopts`, so `--lf`, `--ff` and `--sw` work again.
  Without the plugin pytest does not refuse those flags — it accepts them and
  silently collects everything, which is the worst shape a narrowing flag can
  have. Both reasons the option looked necessary were checked rather than
  assumed: the cache directory is ignored, and the verdict key cannot see an
  ignored path.
- **`./scripts/test.sh` refuses `-n auto`, and a typed `-n` above one slot's
  share is clamped.** This box's cores are already split into pytest slots the
  gates hold, so `-n auto` from a personal run takes every one of them and
  mints a test database per worker. The clamp prints what it did and names the
  escape, `DJB_PYTEST_UNCAPPED=1`, which prints its own line too — a ceiling
  with no visible way past it gets worked around in the dark.
  (`scripts/test.sh`, `apps/conftest.py`.)
- **A loop-verdict miss explains itself in two lines**, with the tree, the
  environment components and the ledger census behind `DJB_LOOP_VERBOSE=1` —
  named on the key line, so the flag is discoverable from the output rather
  than from the source. (`scripts/check.sh`,
  `scripts/tests/test_loop_ledger.sh`.)
- **The history census moved from `--loop` to `--fast`**, so the pre-commit
  hook catches a shipped file carrying build archaeology at the cheapest
  moment anyone will find it, and the per-rung gate carries one copy fewer.
  (`scripts/check.sh`, `scripts/tests/test_archaeology_loop.sh`.)
- **`--force-foreign` without `--roots` is refused, exit 2.** A
  derivation-shaped database with no visible checkout is an absence of
  evidence, never a licence to drop it; narrowing with `--only` does not lift
  the refusal, and a database some worktree has checked out is never foreign
  even when that worktree lives outside the roots. An unrooted sweep had
  destroyed a four-figure number of databases in a week.
  (`scripts/sweep.sh`, `scripts/db_sweep.sh`, `scripts/tests/test_sweep.sh`,
  and `.claude/skills/product-manager/references/operations.md`, which
  prescribed the unrooted form.)
- **The object-storage image is pinned at a registry that still serves it**,
  and `scripts/setup.sh` now pulls the stack before starting it: a failed pull
  is exit 2 naming the image and the registry, rather than a start that
  discovers the same thing halfway through, or a health wait counting to 180
  against a container that was never going to exist. A healthy stack is still
  reused without pulling anything. (`compose.yaml`, `scripts/setup.sh`,
  `scripts/tests/test_setup_env.sh`.)
- **The function-length budget's subject is a function, not a file.** A
  `services.py` with no top-level function records no subject: a longest
  function of zero is a placeholder, not a measurement somebody took. The
  doctrine is unchanged — a new subject still fails until a person measures it
  — and this is what lets a generated app be green on arrival.
  (`quality/gate.py`, `quality/budgets.yaml`.)
- **The identity service in the deployment compose runs unprivileged.** Its
  initialisation and setup are root one-shots that must complete successfully
  before the serving container starts, and the serving container holds service
  credentials rather than the database master credential for its whole life.
  The laptop compose is deliberately unchanged. (`deploy/compose.yaml`.)
- **The two long skills are short again.** `django-conventions` and
  `django-architect` are each an imperative `SKILL.md` under 500 lines plus
  on-demand `references/*.md`, byte-preserving — the rules did not change,
  their loading cost did. The arrival primer's reading order is split into
  what to READ and what to merely KNOW-WHERE-IT-IS, and every citation that
  pointed into the old section numbering was re-pointed.
  (`.claude/skills/django-conventions/`, `.claude/skills/django-architect/`,
  `.claude/skills/platform-primer/SKILL.md`,
  `.claude/skills/product-manager/references/dispatch-briefs.md`.)
- **The rung-execution skill states four rules it used to leave to judgment:**
  one redirect form for every run whose exit status you intend to trust; both
  hook-bypass forms forbidden by name, because the option is refused and not
  merely a particular value of it; a drive runs the leg in the shape the gate
  runs it, at `-n $GATE_SLOT_WORKERS` and never `-n auto`; and there is one
  scratch location, outside the checkout, because the checkout is what the
  gate measures. (`.claude/skills/rung-execution/SKILL.md`.)

### Fixed

- **A pipeline whose reader exits early no longer kills its own producer.**
  Under `set -o pipefail`, `producer | head -1` closes the pipe on the first
  match and orphans the producer with status 141 as soon as its output passes
  the kernel's 64 KiB pipe buffer — green on every file anyone had driven it
  with, and a hard failure on the first one big enough. The class is now
  censused across the scripts, and every site is rewritten to read whole and
  slice, or to an EOF reader, or carries a valve saying why it is safe.
  (`scripts/check.sh`, `scripts/pm_merge.sh`, `scripts/publish.sh`,
  `scripts/backup.sh`, `scripts/setup.sh`, `scripts/archaeology_lib.sh`,
  `deploy/release.sh`, `deploy/provision.sh`, `deploy/teardown.sh`,
  `scripts/tests/test_pipefail_readers.sh`,
  `scripts/tests/test_pm_merge.sh`.)
- **A test collector that dies is exit 2, not a green run that measured
  nothing.** Every collector writes its own counts; a missing file means one
  never reached the end of collecting, and the gate now says so and judges
  nothing rather than reporting the suite that happened to survive.
  (`scripts/check.sh`.)
- **The secrets baseline no longer carries a timestamp**, and the one step
  allowed to write it strips the stamp before committing it. The scanner rewrote
  that line on every run, so the committed file was a line every two branches
  conflicted on — and the conflict looked like a secrets finding. The
  stampless file is accepted by the installed scanner, which prints its
  version beside the verdict. (`.secrets.baseline`, `scripts/pm_fold.sh`,
  `scripts/tests/test_secrets_baseline_guard.sh`,
  `scripts/tests/test_pm_fold.sh`,
  `.claude/skills/rung-execution/SKILL.md`.)
- **The observability sink's two data paths had no named volume** — in both
  compose files. Only its metadata directory was declared; the column store
  and its server logs sat in anonymous volumes, which a `down -v`, a prune or
  a recreate with renewed anonymous volumes takes away without naming what it
  took. (`compose.yaml`, `deploy/compose.yaml`.)
- **The drives' repository tripwire stops reddening on a colleague's ordinary
  commit.** Git refs are shared across every worktree of a repository, so a
  peer's commit moved a ref under a running drive. A ref some other worktree
  has checked out is now excused — and every excuse is printed with its
  reason, on the green path too. A new ref with no worktree, a moved ref with
  no worktree and a vanished ref are all still red.
  (`scripts/tests/drive_preamble.sh`, `scripts/tests/test_drive_preamble.sh`.)
- **The runbook drive plants its own probe instead of relying on whatever
  happened to be there.** Its terminator case now creates the execution it
  measures, tagged with the tenant prefix, so the positive half holds on a
  product that pins its own task queue and actually runs a worker; the drive
  also prints how many pollers it found. (`scripts/tests/test_runbook_recipes.sh`.)
- **Dangling in-file citations repaired** — comments that pointed at a rung or
  a finding by a coordinate that resolves nowhere outside the source
  repository now say the thing itself. (`quality/hotpaths.py`.)
- **A drive's planted names derive from its own checkout**, so two checkouts
  running the sweep drive at once no longer collide on a constant and both
  stay green. (`scripts/tests/test_sweep.sh`.)
- **The gate's usage header and its parser are checked against each other**,
  both ways, instead of agreeing by care. A header naming a mode the parser
  refuses sends a reader to an exit 2; a mode the header omits is a mode
  nobody finds. Both were true of that file before.
  (`scripts/check.sh`, `scripts/tests/test_gate_lease.sh`.)
- **A fixture that copies a library copies the seam that library sources.**
  Every case in one drive was exiting 1 on a missing file the night the
  refusal seam landed, and the population is now pinned by a census rather
  than by the copy list staying honest on its own.
  (`scripts/tests/test_publish.sh`, `scripts/tests/test_gate_lease.sh`,
  `scripts/tests/test_secrets_scan.sh`.)

### Known, queued

Blind spots a consumer inherits with this release. Each is declared rather
than patched, and each is on the list to close.

- The drive population's own early-exit pipe readers are **printed, not
  asserted** — the census over the drives reports what it found and nothing
  fails on it.
- The self-test leg **stops at its first red drive**, so a later drive's cases
  never ran and a green-after-fix run is the only way to learn what they would
  have said.
- A verifier's seeded loop verdict **cannot hit before its environment is
  synced**, so the first consult in a fresh clone measures rather than reuses.
- A collector that dies **inside a full gate** is still pytest's exit 0 there;
  the counts floor above guards the per-rung leg.
- **Object-storage buckets have no broom.** Every other derived resource —
  databases, worktrees, task queues — has a sweep; per-checkout buckets
  accumulate until somebody removes them by hand.
- **Four in-process banners stand behind a callee outside the refusal seam** —
  three separate processes and one sourced helper — and print the
  callee-recorded-nothing sentence by design until those callees join it.
- **The usage-header check cannot quote another tool's flag**: a header
  sentence naming a flag that belongs to a different command reads to the
  census as a mode of this one.
- **The database-pin leg does not assert the database exists** — it compares
  the pinned name against the derivation and stops there.
- **An uncommitted `frontend/` stops a banked verdict applying, and says
  nothing about why.** The verdict key is the content the gate could read, and
  an untracked tree is content, so the key moves and the green no longer hits
  — correct, intended, and indistinguishable from any other miss in the
  output. A product that grows its client directory before committing it will
  see verdict reuse go away with no line naming the cause.
- **The frontend leg's own drive needs a real package manager to run at all.**
  Four of its cases drive the genuine frozen-lockfile refusal rather than a
  shim of it, so `pnpm` missing from `PATH` is could-not-look for the whole
  drive — exit 2 before a single case, never a quiet partial pass. Honest, and
  it means a box without the toolchain cannot clear that drive's other five
  cases either.

## [1.1.0] — Trust and throughput

**A minor.** Nothing here asks a product to change its own code. Every item is
either a machine a product can ignore or a defect repaired in machinery it was
already relying on, so the merge should touch only files a product has not
edited itself. If you clone the template and run the loop, this is the drop
that makes the loop cost less and lie less.

### Added

- **The quality gate takes a slot before it runs tests.** Two per-rung gates
  in two checkouts on one machine used to run their test passes fully
  concurrently, each asking for every core; a machine running several at once
  spent multiples of the wall-clock a single gate needs, and killed some
  outright. A counting semaphore now holds a gate at the door until a slot is
  free, announces which run it is waiting for, and refuses out loud rather
  than waiting forever. Set `DJB_GATE_SLOTS` to override the derived count.
- **Banking a full-gate verdict now requires the caller to say who it is.** A
  full gate outside the push ritual refuses unless the run is sanctioned by an
  explicitly typed reason, which is then printed in the gate's header and
  recorded beside the verdict. A green verdict in the ledger is now traceable
  to a person and a purpose instead of appearing from nowhere.
- **`scripts/verify_start.sh`** — one command that puts a verifier on a
  branch merged with the main line, with its own derived database, refusing to
  start from a dirty tree and refusing to finish with stray untracked files.
- **`scripts/rung_start.sh --resume`** — re-establish a checkout's
  environment part-way through a piece of work, without resetting the work.
  The existing refusals are unchanged; a dirty tree is still refused.
- **`scripts/publish.sh --release`** — the mechanism this very entry is
  delivered by. A product that publishes its own derivative template inherits
  it: one squashed release commit per publish, a child of the published tip,
  tagged from `TEMPLATE_VERSION`, with the release commit's tree asserted
  equal to the tree the publication census verified. The old behaviour of
  re-cutting a published repository's root is now refused, because re-cutting
  destroys the merge base every consumer shares.
- **The identity-platform audit prints what it cannot see** beside its
  verdict, instead of declaring that blind spot only in its source. It also
  reads an organisation's login policy and the instance's mail settings and
  reports them as observed — never judged, because nothing in the template
  claims to own those two surfaces yet.
- **The loop-health report flags an oversized in-flight ledger**, naming the
  size and the rule, rather than letting the file a cold reader is told to
  read first grow past being readable.

### Changed

- **Container images are built once and promoted by digest.** The image is
  built in CI, for both common architectures, and pushed only after the gate
  has passed; deploys pin and promote that digest rather than rebuilding.
  Products that were building an image in more than one place get one build
  site and an identical artifact in every environment.
- **The `DATABASE_NAME` pin marker moved to its own comment line.** The
  previous inline form was read one way by the shell and another by the
  settings loader — the loader took the trailing comment as part of the
  database name. Any script that touches a `.env` rewrites the pin to the new
  grammar, and the old form is now refused with the two-line fix printed.
- **CI derives its gate database name** the same way every checkout does,
  instead of pinning a fixed one. The census that checks a checkout has not
  left stray databases behind was passing in CI without looking at anything.

### Fixed

- **`scripts/db.sh` under `zsh`.** `zsh` ties the name `path` to `PATH`, so a
  local variable of that name corrupted the shell's own executable lookup: a
  database create reported success while creating nothing. The name is gone
  and the tied-name population is audited.
- **The secret scanner stops flagging passwordless-auth constants.** Four
  reproduced shapes were false positives that a product would have had to
  baseline by hand, one file at a time, teaching it to baseline findings.
- **Idempotent retries no longer replay a refusal the caller has already
  fixed.** A client that received a 4xx, corrected its request and retried
  under the same idempotency key used to receive the cached refusal forever.
  Refusals below the server-error band are now re-evaluated; the replay
  guarantee that matters — a successful write is never done twice — is
  unchanged.
- **The quality gate's self-test survives a disabled app.** Turning an
  optional app off used to kill a large share of the rules' canaries, because
  floors and censuses were pinned to numbers that counted members the disabled
  app contributed. They now derive from the enabled population, and the test
  suite honours the same switch. A product that removes the example app gets a
  gate that still works.
- **Function budgets stop measuring docstrings.** A budget that counted a
  function's documentation as its length punished writing any, which is the
  opposite of what the ratchet is for. Budgets were re-measured in the same
  change.
- **One seam for paginated routes.** The rule that requires pagination, the
  generated API document and the schema introspection command each used to
  read the decorator population their own way, so a fix for one left the other
  two blind. They now read one seam.
- **The workflow recipe drive terminates the executions it starts**, on pass,
  failure or interruption. Against a shared workflow server it was leaving
  every run it opened running, and the leak was invisible to the census
  because the census only ever looked at schedules. The census now looks at
  open executions too.
- **The restore drill says when it died.** It printed a sentinel on success
  and nothing at all on death, so an interrupted drill and a drill that had
  not finished yet were indistinguishable.
- **Several checks now say what they saw and what the cheap way out is**, so
  a red line names its own remedy instead of sending a reader to the source.
- **The Django conventions skill stopped contradicting itself** about which
  form of view is the house form.

## [1.0.0] — Initial release

The template as first published: the agent team, the method, the quality gate
and the guardrails, with the ledgers shipped as skeletons for a product to
fill.

<!--
The link references below are RELATIVE on purpose. This file ships to every
product cloned from the template, and a relative reference resolves against
whichever repository is serving it — so a product's own copy points at its own
history rather than at ours, and the template names no account of its own in a
file a stranger inherits.
-->

[Unreleased]: ../../compare/v2.0.0...HEAD
[2.0.0]: ../../compare/v1.1.0...v2.0.0
[1.1.0]: ../../compare/v1.0.0...v1.1.0
[1.0.0]: ../../tree/v1.0.0
