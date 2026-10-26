# Publication manifest — what ships, what trims, what becomes a skeleton

**`scripts/publish.sh` is this file executed**, and `quality/tests/test_publish.py`
drives it. `docs/product/adrs/` is where decisions live, one file per id (ADR docs-1); this
file governs which of them reach a published artifact.

## The census discipline (the design's spine)

The manifest is **a census by rule over `git ls-files`, never a hand list of
paths**: every tracked path must match **exactly one** bucket rule below.
`publish.sh` implements the census and **exits 2** when any tracked path
matches no rule or two rules — a file class added later fails loudly instead
of shipping by accident or vanishing silently (the
closed-question-over-a-discoverable-population discipline). Untracked residue
(`.rung/`, gate-verdict ledgers, worktree droppings, `.env`) never exports
**by construction**: the export is the ship-set of `git ls-files` into a
fresh `git init` — nothing untracked can ride.

Two invariants outrank any per-file preference:

1. **Anything the gate reads ships verbatim.** The artifact must pass the
   FULL gate from a fresh clone, so every gate-consumed file — `quality/**`
   whole, `docs/product/instruments.md` (the goalpost census pins
   instruments == rows), the scripts, the hooks — ships byte-identical.
   **The learning layer is the product OF the history and ships**:
   rules.yaml's paid-for canaries, negatives, floors, MOVE-TRIGGER
   annotations and `does_not_cover` clauses, budgets' measured ceilings.
   *Criterion (falsifiable): the published `quality/**` and
   `instruments.md` are byte-identical to the source repository's at the
   publish sha — trimming that touches them is a defect, and the diff is
   the evidence.*
2. **No decision is lost at publish.** Every ADR id cited in any ship-list
   file resolves to its file `docs/product/adrs/<id>.md` (the directory
   ships) — the link-census, run by `publish.sh` against the artifact; a
   citation resolving only into `cycles/` is exit 1 with the id and the
   citing file named. The same holds for ordinary pointers: a **path or
   link** that resolves into a trimmed location is a violation.

## R0 · the reserved paths (checked BEFORE any bucket is assigned)

**The drawers are the product's, and the template ships none.** A product
extends the system layer by declaring beside it rather than by editing it: an
extensible template directory has a `local/` sibling the template's own reader
discovers, and a per-product list has a `.local.md` sibling beside the template
document it extends. The whole value of that convention is that a release
CANNOT conflict with one — absent is byte-identical behaviour — and that value
holds for exactly as long as no release claims the name.

| reserved | who owns it | at a merge |
|---|---|---|
| `**/local/**` — a `local/` directory segment anywhere | the product, always | no conflict by construction: the template has no such path to conflict with |
| `*.local.md` — a per-product list beside its template original | the product, always | the same |
| `apps/conftest_local.py` — the product's pytest fixtures drawer | the product, always | the same |

**A tracked path matching either is exit 2, named, before the bucket census
runs.** Not exit 1: a reserved name claimed by the template makes the census's
own ground false, and every leg after it is then reasoning about a partition
that no longer holds. It runs first because a reserved path would otherwise
bucket, ship and verify perfectly well — `scripts/local/legs/x.sh` is bucket
SHIP under R3's glob and published CLEAN before this rule existed. The bucket
rules are not wrong; the path is, and nothing was reading the path.

**THE THIRD ROW IS AN EXACT PATH, NOT A GLOB, AND THE EXCEPTION IS THE
POINT.** A `conftest.py` sibling is collected by pytest BY NAME inside the
package it belongs to, so the fixtures drawer cannot be spelled `apps/local/…`
without leaving the directory pytest looks in — the convention bends to the
tool rather than the tool to the convention. It is kept in the same list as
the two globs because that list is the ONE reader of "what is reserved"
(`reserved_paths` in `scripts/publish.sh`), and a reserved path recorded
anywhere else is a second list that agrees today. It was found by a reviewer
rather than by this census: R3 and R1 ship `scripts/**` and `apps/**` whole,
so before R0 named them a tracked drawer of either shape shipped in silence.

**It reads TRACKED paths only.** The export is `git archive HEAD`, so an
untracked drawer in a maintainer's own checkout ships nothing and is nobody's
business. The other half of the promise — that a product's edit to a
template-OWNED path is a divergence it records rather than a surprise at the
merge — is `scripts/divergence_census.sh`, and the per-path ownership table
both of them read is `docs/product/build-contract.md` § Ownership.

## Bucket rules (every tracked path matches exactly one)

| rule | paths | bucket | why |
|---|---|---|---|
| R1 | `apps/**` · `config/**` · `manage.py` · `pilecap/**` | SHIP | the system-and-project layers a product grows in, and `pilecap/**`, the SDK facade that re-exports the platform apps to them; the platform partition's app set is read from THIS rule's export census **once, at the freeze build**, into `quality/partition.yaml` — one census read twice, because a LIVE derivation from R1 is impossible (`partition-closure.md` §2 carries the argument) |
| R2 | `quality/**` · `docs/product/instruments.md` | SHIP (byte-identical clause) | invariant 1 — the learning layer and the gate's own inputs |
| R3 | `scripts/**` · `deploy/**` · `perf/**` · `compose.yaml` · `compose/**` · `Dockerfile` · `.dockerignore` · `.devcontainer/**` · `.github/**` | SHIP | instruments and posture-as-code; every executable already owes its `instruments.md` row |
| R4 | `pyproject.toml` · `uv.lock` · `.python-version` · `.env.example` · `.gitignore` · `.editorconfig` · `.gitattributes` · `.secrets.baseline` · `vendor/**` · `templates/**` | SHIP | the pinned environment and vendored assets (the Scalar manifest's checksum posture rides along). `.gitattributes` is here rather than with R3's instruments because it is checkout POSTURE the way `.gitignore` is — git reads it, nothing in this tree executes it — and it ships for the same reason: a consumer whose lanes append to `CHANGELOG.md` has the same seven hand resolutions per cycle without it |
| R5 | `.claude/skills/**` · `.claude/agents/**` · `CLAUDE.md` · `README.md` · `docs/runbooks/**` · `docs/standards.md` | SHIP | the method, the map, the operator procedures — **`.claude/agents/**` is the method too**: an agent definition pins the model and the tools a dispatched role runs with (`.claude/agents/builder.md` pins the builder's), so a consumer inheriting the skills without the definitions inherits half a team, and the two directories ship together as one glob each — and, at the last path, the portable account of the method written FOR OTHER TEAMS, which is guidance of the same class and belongs where a browsing stranger lands rather than under `docs/product/` (those are the decisions THIS repository is built on) or `docs/runbooks/` (operations). **The path, not a glob:** R5 gains this one file, so the next guidance-class file at `docs/*.md` still fails unplaced and is decided rather than absorbed |
| R6 | `TEMPLATE_VERSION` · `CHANGELOG.md` | SHIP | the template-updates mechanism: `TEMPLATE_VERSION` names the release a checkout is on and the release TAG is derived from it; `CHANGELOG.md` is what a consumer reads before merging that tag, and release mode refuses to publish a version the file has no section for (§ Release mode) |
| R7 | `docs/product/<ledger>.md` for the eleven ledgers below | SKELETON | ships as a committed skeleton + one marked worked example each |
| R8 | `docs/product/cycles/**` · `briefs/**` · `archive/**` · `retro/**` · `drafts/**` · `proposals/**` · `docs/product/surveys/**` · `docs/product/reports/**` · the dated `pm-handoff-*.md` handoffs | TRIM | the build's archaeology (the consolidation surveys and the agents' rung reports included); the source repository keeps it as the archive of record |
| R8S | two named files inside `cycles/` and the README inside `briefs/` (dispositions table below) | SHIP | the format-teaching files in two otherwise-trimmed directories |
| R9 | the remaining `docs/product/*.md` (dispositions table below) · `docs/product/design/*` · `docs/product/adrs/*` | per-file | the one genuinely mixed directory; its two globs are the design directory, the pattern book's home, and the ADR directory, the decision log — the class named, never the instance |
| R10 | `docs/product/skeletons/**` | SKELETON-SOURCE | the directory holding the committed skeletons; consumed at export and never shipped at its own path, and a skeleton naming no ledger is exit 2 — the export would otherwise ignore it in silence |
| R11 | `frontend/**` | SHIP | the client layer: the one-journey worked example, its lockfile, the committed OpenAPI document and the generated client the byte-pin compares. It ships for the same reason `apps/example` does — a rule that never fired anywhere is decoration by the engine's own doctrine, and the standing subjects of every frontend rule (the byte-pin, `SurfaceState` in anger, the rendered census's live scan) need a tree to be proven against. **One glob, because the directory is one artefact**; `.gitignore` decides which of its files are build output and the census then never sees them |
| R12 | `scripts/test_impact.json` · `scripts/pytest_durations.json` · `scripts/gate_member_durations.json` | TRIM | the three MEASURED files — a test-impact map keyed on a tree that exists only here, and two timing files measured on this platform's own boxes over this platform's own suite. They are measurements, not instruments: in a product's tree they are a claim the product never made, cannot check and would have to resolve as a conflict at every fold. **Every reader already treats absence as "measure it yourself", and says so on its own line.** Each is cited by its own SENTENCE with today's line beside it, never by the line alone — these three files move every cycle, and a bare line number is the citation form this repository has already watched go stale: (a) `impact` in `quality/djb/scope.py` answers `<map> is absent or unreadable — closure scope. A tree whose acceptance box has never written a map is a tree, not a broken read.` (`quality/djb/scope.py:659` today); (b) the always-on leg, `quality/djb/legs/always_on.py::measured`, prints `always-on (measured): no durations file — the first --store-durations writes it` (`quality/djb/legs/always_on.py:173` today); (c) `quality/djb/legs/pytest_x2.py::split_args` resolves the pytest durations path ONLY under `--shard` or `--store-durations`, so an ordinary run never opens it, and a shard run without one prints `durations: none — unbalanced split` (`quality/djb/legs/pytest_x2.py:464` today). So trimming costs a consumer one measured run of their own and buys them a clean modify/delete at every future merge. Shipping them EMPTY was rejected: an empty durations file is still a claim about a suite, and it still conflicts with the product's copy |
| R13 | `docs/sdk/**` | SHIP | the product developer's reference — generated by `python -m quality.sdk --reference` from the facade and the goldens, and the one place a product developer reads (the owner's reading rule for a product developer is `docs/sdk/**` only). It ships whole for the same reason R5's method does: a consumer inheriting the platform without the map to it inherits half of it. **One glob, because the directory is one artefact**; it collides with no other rule's paths |
| R14 | three files under the workflows directory: `proof-from-zero.yml` · `nightly-proof.yml` · `mirror-images.yml` | TRIM | the platform proves itself; a product's repository proves the product. The three are the template's own self-proofs (a proof from zero, its nightly, the image mirror), and in a product they fire on every merge, every night and every `compose.yaml` push at the product's cost; `ci.yml` is the product's gate and stays R3. **An arm of R3 before its glob, in R12's one `case`**, for R12's reason |

**R12 is an arm of R3, not a rule beside it**, for R8S's reason exactly: the
two live in ONE `case` in `archaeology_lib.sh` with R12's arm first, so
first-match partitions them by construction and the census's double-match
refusal still proves it. Two blocks would make every R12 path match twice and
exit 2.

**R12 is the one HAND LIST in the bucket rules, and it names what re-derives
it.** `test_r12_is_the_measured_files_the_readers_default_to` in
`quality/tests/test_archaeology.py` reads the three readers' own constants —
`pytest_x2.DURATIONS`, `registry.WALLS_HOMES` and `scope.MAP_PATH` — and reds
when that set and this row's set differ. A fourth measured file is therefore a
red at the test, never a silent ship.

**R8S is an arm of R8, not a rule beside it.** It and R8's glob live in ONE
`case` in `publish.sh`, so first-match separates them and the census's
double-match refusal still proves the population is partitioned. Two blocks
would make every R8S path match twice and exit 2.

**R8's last clause is a GLOB, not a filename.** A rule that spelled a trimmed
path would make a shipped file cite a pointer the artifact cannot resolve —
the dangling-pointer leg's own class. Name the class, never the instance.

## docs/product — per-file dispositions (R7/R8S/R9, complete over today's tree)

| file | bucket | note |
|---|---|---|
| `docs/product/cycles/README.md` | SHIP (R8S) | the directory's own contract — what a plan holds, what it must NOT hold (status), and that order lives in `queue.md`. Several shipped files send a first PM to `cycles/`, and a home whose contract was trimmed is a pointer at an empty room |
| `docs/product/cycles/EXAMPLE-cycle-plan.md` | SHIP (R8S) | the plan template as a worked example — invented product (orders, a clerk), marked EXAMPLE in its own second line, and named by the README as the thing to delete when the first real plan is written. Format teaching, not archaeology; it cites no ADR id and no `docs/` pointer, so it adds nothing to either link leg |
| `briefs/README.md` under `docs/product/` | SHIP (R8S) | the briefs directory's own contract — what a dispatch brief holds and that it travels in the rung's branch; the briefs themselves are R8, the build's archaeology |
| `architecture.md` | SHIP | the current state: the stack, the doors, the gate, the house rules |
| `adrs-ingredients.md` | SHIP | the ingredients' design record (no ADR home) |
| `adrs/*` | SHIP | the decision log: one file per ADR id, the census resolves by filename |
| `api-editorial-standard.md` | SHIP | system layer |
| `build-contract.md` | SHIP | the ownership map |
| `operating-protocol.md` | SHIP | the method |
| `scale-envelope.md` | SHIP | platform scale doctrine |
| `instruments.md` | SHIP | invariant 1 (gate-read) |
| `north-star.md` | SKELETON | the file a product fills first — CLAUDE.md's own sentence |
| `queue.md` | SKELETON + one row-shape | the GENERATED index half of the pair — a clone inherits the two-file shape, not this platform's rows |
| `queue-detail.md` | SKELETON + one row-shape | the record half. It is the same ledger, split: shipping the live file would hand every product this platform's whole construction history, and `queue.md` alone would hand it an index over rows it does not have. `scripts/queue_index.py --check` is green on the skeleton pair the day the clone is made, because the skeleton index is GENERATED from the skeleton record with the live paths |
| `readouts.md` | SKELETON + one cycle-row | |
| `misses.md` | SKELETON + one promoted entry | |
| `in-flight.md` | SKELETON (the empty contract) | |
| `goal-posts.md` | SKELETON + one worked pillar row | a product proves its own pillars; the register's format is the value |
| `design-agreements.md` | SKELETON + one marked ruling | owner-taste rulings are product-layer; the format and one worked example ship |
| `pilot-readiness.md` | SKELETON + one gate-shaped row | the product-manager skill's mandated state-read names it, so a cloned product must find it present; the dated content a first builder must not inherit does not survive the skeleton |
| `rep-day.md` | SKELETON + one job-with-cost row | same reason: named by the state-read, dated in substance |
| `threat-model.md` | SKELETON + the one worked noun row | the platform's door, boundary, noun and HIPAA rows are kept — they describe what the product inherits — and the `Widget` row is the marked worked example a product replaces with its own noun; `scripts/threat_census.py` is green on the skeleton the day the clone is made |
| `publication-manifest.md` (this file) | SHIP | a product inherits the manifest so it can publish its own derivatives |
| `partition-closure.md` | SHIP | the platform partition, its input closure, the discovery-digest key and the four always-run nets; the freeze build cites it |
| `design/*` (today: `design/patterns.md`) | SHIP | the pattern book — the form every element-class entry takes, the floor the house rules hold every face to, and the instrument index; template-owned (`build-contract.md`'s ownership table), so a product reads it and writes its own entries in the drawer beside it, `patterns.local.md`, which the template never tracks. A GLOB for R8's reason: the directory is the class |

## Skeleton mechanics (decided, with the rejection)

Skeletons are **committed files** in the source repository —
`docs/product/skeletons/<name>.md` — and `publish.sh` substitutes each for
its live ledger at export. Each skeleton is the ledger's contract header
plus its ONE worked example, chosen once and committed, marked
`<!-- worked example — replace with your product's first real entry -->`.
*Rejected:* deriving skeletons by trimming the live ledgers at export time —
a parser over prose, non-deterministic as the ledgers churn, and the
worked example would silently change every publish. A committed skeleton is
reviewable, stable, and makes `publish.sh` idempotent by construction. A
generated ledger's skeleton is produced by its generator, never typed, and
pinned by the generator's check (`quality/tests/test_queue_index.py`).

**The substitution set is DERIVED, not listed.** A ledger with a committed
`docs/product/skeletons/<name>.md` is substituted from it; a ledger without
one must ALREADY be in skeleton form, which `publish.sh` proves by requiring
the marker. Both states are legal and neither is a second copy of the other —
writing a skeleton file for a ledger that is already skeletal would be exactly
the second-copy-that-agrees-today miss the census exists to refuse. Adding a
skeleton file is therefore the whole act of converting one; a
`docs/product/skeletons/` file naming a NON-ledger is exit 2.

## publish.sh — the design

- **Derivation:** apply the bucket rules to `git ls-files` at HEAD; census
  refusal per above (exit 2 on unmatched/double-matched).
- **Export:** copy the ship-set into a fresh `git init` in a SCRATCH target
  (no source history); substitute skeletons per R7; commit as that scratch
  artifact's single initial commit. This is the verification world, and it is
  what every drive runs against. Publishing to the real repository is § Release
  mode below, which reuses this export whole and adds one commit.
- **Idempotent, falsifiably:** two runs at the same source sha produce the
  same exported TREE HASH (`git rev-parse HEAD^{tree}` on the artifact) —
  printed by the instrument itself, the claim being its own line.
- **Verification legs, in the run:** `file-set`, proving the artifact is
  EXACTLY the census's ship-set (exit 2 on any disagreement — a census and an
  export that differ mean one is not the derivation it claims to be);
  `adr-census`, invariant 2 over the artifact; `dangling-docs`, invariant 2 for
  ordinary pointers, requiring every `docs/**.md` path spelled in the
  artifact to resolve inside it; the full-tree secret scan over the ARTIFACT
  (rule 23 — the trim itself can surface what history hid); and the
  byte-identical check for R2. A fresh clone of the artifact is then driven
  through `setup.sh`, the FULL gate and the primer walkthrough.
- **Target:** a public GitHub **template repo**, cut from this source once and
  extended by release commits after that (§ Release mode); the source
  repository keeps its full history as the archive of record. Repeatable
  because the template keeps evolving — publish is a command, never a
  hand-copy.
- **House discipline:** owns its exit codes, refuses a piped stdout, owes
  its `docs/product/instruments.md` row.

## Release mode — the child-commit publish (owner's ruling, 2026-08-30)

**A release is a forward commit.** `./scripts/publish.sh --release <dir>` runs
the census, the export and every verification leg above against a scratch
artifact exactly as the default mode does, and then writes ONE squashed commit
into `<dir>` — a clone of the published repository — as a **child of its tip**,
tagged `v<TEMPLATE_VERSION>`. `--to` keeps its meaning: it names the scratch
artifact, never the published repository.

**Consumers merge the tag they want.** Each release commit carries the WHOLE
tree rather than a delta, and the chain is linear, so a product on `v1.0.0`
merges `v1.4.0` directly and skips every intermediate for free. A product
cloned from the published repository shares its root commit, so a merge base
always exists: inherited files nobody touched merge silently and a locally
edited file arrives as an ordinary conflict in that file alone. Cadence and
batch size stay the platform's — the consumer's cost does not grow with them.

**The release commit's tree IS the census-verified tree, and that is
asserted.** The artifact's objects are fetched into the published repository
and `git commit-tree` is handed the very hash the export printed; the new
commit's tree is then read back and compared. Unequal is exit 2 with both
hashes named and no tag written. This is why the idempotence line is now
doubly load-bearing: it is both the repeatability claim and the release
commit's identity.

**Refusals (all exit 2, all before anything is written):** a target that is
not a repository root, is bare, has a detached HEAD, has no commits, or has a
dirty working tree; a target carrying **no release tag at all** (there is then
nothing to compare the tip against, and guessing what is already published is
the one thing this refuses to do — tag the published tip once and re-run); a
target whose **tip is not its last release**, naming both shas (somebody
committed onto the published branch by hand, or the clone is behind); and a
target that **already carries this version's tag**, because a released tree
never changes. A run with violations prints the release step and commits
nothing.

**Bumping `TEMPLATE_VERSION` is the whole act of declaring a release.**
Release mode reads that one file to decide what it is publishing, and three
separate gates key on the value it finds: the tag it writes is
`v<TEMPLATE_VERSION>`, the already-released refusal above is a check for that
same tag on the target, and leg `changelog` below refuses unless the
artifact's `CHANGELOG.md` carries a `## [<TEMPLATE_VERSION>]` section. One
typed value, three readers, no second place to keep it in step — so a release
is declared by bumping the file rather than by weakening a refusal, and a
version published once can never quietly be published again over a different
tree. The value itself is not repeated here: `cat TEMPLATE_VERSION` is what
knows, and `CHANGELOG.md`'s top entry is what says why it moved.

**Leg `changelog` (release mode, exit 1):** the artifact's `CHANGELOG.md` must
carry a `## [<version>]` section for the version being released. A tag with no
entry behind it asks a consumer to merge a tree on trust — a diff answers
"what changed" and never "would I want this, and what does it change under
me", which is the question `CHANGELOG.md`'s own header says an entry answers.

**Leg `changelog-flags` (release mode, exit 1):** every `<script> --flag` the
section claims must be a literal in the script it names, and a thin wrapper
(an `exec … -m <module> "$@"` line) is read through to the module it execs.

**THE ROOT RE-CUT DOOR IS CLOSED.** A target carrying release tags is refused
with the door-closed sentence in every mode that exports. Re-cutting the root
of a published repository destroys the merge base every consumer shares: their
next pull would see the whole template as new work and conflict with every
local patch they carry. The scratch mode is untouched — a fresh or
previously-stamped directory still exports normally, which is how the drives
run.

**And so the per-publish census is load-bearing FOREVER.** History that cannot
be re-cut cannot be cleaned up later. A private name, a dangling pointer, a
lost decision or a secret that reaches a release commit is in every consumer's
history the moment they merge it. Every leg above used to be a wall in front of
a mistake that could be undone by re-cutting; none of them is that any more,
and that is the reason none of them may be weakened for convenience.

## Blind spots (this design's own, declared)

- The census covers TRACKED files; a load-bearing untracked file (none
  known) would be invisible — the fresh-clone gate drive is the belt.
- Skeleton content quality is review's, not the census's — a skeleton that
  drifts from its live ledger's contract is caught only when a product
  trips on it.
- **Both link legs match single lines; a path that WRAPS across a line
  break is invisible to them.** A comment block that spells `docs/product/`
  at one line's end and the rest of a trimmed path at the next line's start
  is a dangling pointer wearing a line break, and the regex cannot see it.
  Declared rather than patched: a wrap-tolerant scanner over arbitrary prose
  is a parser with its own false-positive surface, and the known instances
  are cheaper to fix than the class is to automate. The trigger to build the
  joining scanner is a SECOND wrapped instance found.
- **Release mode judges the release's SHAPE, never its prose.** Leg
  `changelog` proves a section for the version exists; whether the entry
  answers the file's own question honestly is a reviewer's judgment, the same
  class as skeleton content above.
- **Release mode pushes nothing.** It writes a commit and a tag in a local
  clone and prints the push command. Whether the published repository's remote
  is the intended one, and whether the tag reaches it, are outside every leg
  here — deliberately, because a leg that pushed would make a refusal
  unrecoverable.
- **The closed door is recognised by release TAGS.** A published repository
  that carries none is invisible to the door-closed refusal, and only the
  destruction guard's weaker "not empty and unstamped" refusal stands in
  front of it. That is the whole reason release mode refuses an untagged
  target rather than inventing a version for it: the one act that arms both
  guards is tagging the published tip, and it is asked for by name.
