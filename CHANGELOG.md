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
git merge v1.1.0
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

[Unreleased]: ../../compare/v1.1.0...HEAD
[1.1.0]: ../../compare/v1.0.0...v1.1.0
[1.0.0]: ../../tree/v1.0.0
