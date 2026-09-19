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

Nothing yet.

## [2.1.0] — The loop runs where it is fast, and a read is a permission

**A major, by this file's own definition, twice over.** The per-rung gate no
longer runs on the laptop by default — it runs on a throwaway cloud machine
cut from an image baked from `main`, and a laptop `--loop` refuses until
somebody types who is asking and why. And the authorization model changed
under every door: a `<kind>.read` key is held or withheld like any other
verb, a role is a set of keys rather than a rank, and a tenant-wide
configuration row is written at the tenant's root rather than at whatever
hat the caller wore. Items 1-4 of the list below are load-bearing and go
together; items 5-8 apply to a product that has the thing they name; item 9
is optional. Everything past the list is machinery a product inherits
untouched or can ignore.

What the release is for: every measurement in the loop is a function of its
inputs and is reused when those inputs have not moved — a drive's verdict, a
house rule's scan, a pytest pass, a deploy act — and the one whole run per
wave happens on a machine nobody else is using. The motivation is one dated
row in `docs/product/readouts.md` § COST BASELINE: on 2026-09-17 the pytest
leg of one `--loop` took 248 s on a quiet laptop and 906 s on a contended one,
while a box ran `setup.sh` and the *whole* suite in 20 s + 136 s. The pipeline
is now measured rather than typed (`scripts/loop_metrics.py`), a stage deploy
is six keyed acts that each say whether they ran (`deploy/stage.sh`), and the
identity platform gained a reconciler, a verified-domain gate, and three house
rules that keep one router and one writer per fact.

Append after the sentence ending "…three house rules that keep one router
and one writer per fact." (the paragraph currently ends there):

> And a product can now sign people in on its own host. `DJB_SIGN_IN_DOOR=ours`
> puts every interactive step — the password, the second factor, the
> enrolment, the invited person's first password, the passkey, and the OIDC
> hand-back to whatever app sent them — on one page of ours at
> `/accounts/login/`, drawn over Zitadel's Session API through one seam
> (`apps/accounts/signin.py`) that opens a session, reads the answer
> fail-closed and closes it on the way out. The identity platform still holds
> every credential and decides what a sign-in requires; what moved is who draws
> the screen. The hosted page is the whole-deployment alternative and stays
> the default: a product that sets nothing sees the page it had, byte for byte.

Also amend the first paragraph's framing sentence — "items 9 and 10 are optional" —
to "items 9 and 10 are optional", since the door is opt-in.

---

### What a product does at the merge

Items 1-4 are one change. The gate script, the ledger, the lease, the pytest
runner's options and the hook are one mechanism split across files, exactly as
they were at 2.0.0; take them together or take none of them.

1. **Run `./scripts/setup.sh` again, first.** The lockfile gained three dev
   packages the gate now hands pytest on every scoped run (`pytest-split`,
   `pytest-cov`, `coverage` — each argued in `pyproject.toml` beside its
   line), and the script itself changed shape: its first step now creates a
   local `main` on a checkout that has none (a `git clone --branch <tag>`
   lands detached, and every scope tool in the tree reads `refs/heads/main`
   by name — `scripts/setup.sh` prints the one-line move to the tip if you
   want it), and every step prints its own elapsed time with a `setup: total`
   on the last line. **Migrate in the same breath**, and read item 6 before
   you do: `core.0018_roles_are_keys` refuses a role value nothing declares,
   and `accounts.0009_ssodomain_verified_at` leaves every existing SSO domain
   claim unverified, which means it routes nobody until an operator verifies
   it.
2. **Take the gate wholesale, again.** `scripts/check.sh`,
   `scripts/loop_tier.sh`, `scripts/gate_ledger.sh`, `scripts/gate_lease.sh`,
   `scripts/db.sh`, `scripts/pm_push.sh`, `scripts/githooks/pre-push` and
   `apps/conftest.py` moved together: two new pytest options
   (`--djb-impact-select`, `--djb-changed`) are defined in the conftest and
   passed by the loop; the lease exports the worker share the conftest
   clamps to; the ledger's `--loop` key grew a field. Resolve each file's
   conflict in favour of the template and re-apply local edits on top. Expect
   every banked verdict in every checkout to re-measure exactly once: the
   full row's declared leg set changed and the loop row's environment
   fingerprint now folds the effective value of every name the suite reads.
   Then commit the three derived files the gate reads and never writes during
   a run — `scripts/pytest_durations.json` (from
   `./scripts/check.sh --leg pytest-x2 --store-durations`),
   `scripts/gate_member_durations.json` (from the bare
   `./scripts/check.sh --store-durations`, a timed full gate that banks
   nothing), and `scripts/test_impact.json` (written by the first bank on
   boxes, item 3 — until it exists the loop keeps the closure scope it has
   today and says so).
3. **Decide where your per-rung gate runs, because the laptop is no longer
   the default.** `./scripts/check.sh --loop` on a machine that is not a
   verifier box refuses with exit 2 — above the lease, the lock and the slot,
   so nothing is paid — and prints the recipe. Either way is legal; both are
   typed, neither is silent:
   - **Boxes.** Put `DJB_DEPLOY_NAMESPACE` in the environment file (the same
     slot `deploy/provision.sh` already requires). The owner runs
     `deploy/iam/verifier_bootstrap.sh` once with `DJB_DEPLOY_NAMESPACE`,
     `DJB_VERIFIER_ACCOUNT` and `DJB_VERIFIER_REGION` in the shell (bare, it
     prints the whole plan and exits 2; `--confirm` creates one IAM identity,
     its policy, the boxes' instance role and an egress-only security group,
     all named from the namespace, and checks the two account prerequisites
     it cannot make), then `aws configure --profile <namespace>-verifier` by
     hand. Every builder's shell carries `DJB_VERIFIER_REGION` (no default,
     never inherited from the profile) and the Session Manager plugin. Then
     `./scripts/verifier_box.sh bake` once per `main` you want measured — the
     recipe is printed by `bake --plan` before any money is spent. Nothing
     about the account, the region or the image lands in the tree; the other
     slots and their defaults are the header of `scripts/verifier_box.sh`.
   - **No boxes.** `DJB_LOOP_HERE="<rung-id>: <reason>" ./scripts/check.sh
     --loop`. The reason prints in the run's banner and beside its banked
     verdict; a value that is not `<who>: <why>` is itself exit 2. `--fast`
     (the pre-commit hook), `--census`, the full gate and CI are untouched.
4. **Take `.github/workflows/ci.yml` whole and move your required status
   check to the job called `verdict`.** CI no longer runs one gate; it asks
   the gate for its units (`./scripts/check.sh --list-legs`), runs one
   `--leg <unit>` per runner with the suite split `k/N` under one seed, and
   composes a verdict. The YAML names no leg and no unit — the listing does.
   Keep the `AWS_*` keys in the workflow's `env:` block (a new `--fast` leg
   reds when a credential the settings read is missing there), and declare
   any `DJB_*` key you add to the workflow in
   `scripts/tests/drive_preamble.sh`'s two lists or the preamble drive reds.
5. **If you have a hierarchy, read the permission changes as a product
   change, not a gate change.** A custom role reads nothing until its
   collection names reads (add `"*.read"` or the kinds you mean); a fourth
   role value is declared in a `roles.py` before you migrate; a stored row
   under a renamed key is inert until `manage.py rename_permission <old>
   <new>` moves it (the table is under **Migrating**); and **a branch
   administrator can no longer write the tenant's shared configuration** —
   message templates, delivery policies, suppression surges, connections
   and their credentials, SSO connections and domain claims are written at
   the tenant's root now, and a hat below the root gets 403 with the key's
   own sentence where it got 201 before. A product whose every membership
   sits at the root observes nothing; the flat-product census in
   `apps/core/tests/flat_product_baseline.json` is the proof.
6. **If you run customer SSO, verify every live claim once.**
   `manage.py verify_sso_domain --tenant <slug> --domain <domain>` per claim,
   after the migration; `SsoDomain.verified_at` is the only thing sign-in
   routes on now. A claim on a public mail provider is refused at the door
   (`SSO_REFUSED_MAIL_DOMAINS`, a courtesy list; setting the variable
   replaces the shipped list rather than extending it).
7. **If you have swapped issuers or re-seeded Zitadel since people signed
   in, unlink them once.** The join between a person and their identity is
   keyed on the subject, not the address: a sign-in whose subject differs
   from the one on file is refused, never merged, and
   `manage.py unlink_identity --all --yes --reason "<why>"` is what clears
   the standing subjects so the next sign-in records the new one. Two more
   identity facts change under you: `createsuperuser` no longer opens
   `/admin/` (`manage.py grant_staff --email <address>` is the one road to
   `is_staff`, and the admin's login URL is not a password door), and the
   next `zitadel_seed` **removes** any redirect URI you registered by hand in
   the console on the template's browser client — declare it in settings or
   lose it.
8. **If you have your own `consumers.py` or your own `emit()` sites, expect
   two new house rules to find things.** A consumer extends
   `TenantEventsConsumer` and its pattern is wrapped in `token_auth(...)`
   (rule 58); an event about an org-scoped kind carries `organization_id`
   in its payload, and every event noun an app declares is mapped in that
   app's `EVENT_KINDS` (rule 59). `django-conventions` carries the wrong and
   right forms.
9. **Optional: stage from the checkout.** `deploy/stage.sh <user@box> --env
   <name>` runs the six acts a stage deploy is, keyed on their inputs, and
   needs the image for the tree already in the registry (the bank builds and
   pushes it under the tree tag from its acceptance box; CI's `images` job
   builds only a tag the registry lacks; the registry is derived from
   `deploy/provision.sh`, never written to a file). A product that keeps
   walking the runbook by hand loses nothing.

Add as item 10, after the stage item:

10. **Optional: sign people in on your own host.** Leave `DJB_SIGN_IN_DOOR`
    unset and nothing moves — `hosted` is the default, `/accounts/login/`
    serves the page it served before, and the seed declares nothing to the
    identity platform. To take `ours`: set `DJB_SIGN_IN_DOOR=ours` and make
    sure `PUBLIC_BASE_URL` is the origin a browser actually reaches (it is
    the base of the login-v2 declaration, the invite link, the passkey
    relying-party id and the CSP's redirect origins, all four), then run
    `manage.py zitadel_seed` once — it writes
    `loginVersion.loginV2.baseUri = <PUBLIC_BASE_URL>/accounts` on the
    deployment's OIDC clients and grants the machine credential the
    `IAM_LOGIN_CLIENT` role the finalize needs; `zitadel_audit` judges both
    from then on. Keep `APPEND_SLASH` on (the platform composes
    `{baseUri}/login` with no trailing slash and the 301 is what carries the
    request into the door). The road back is `hosted` plus one more seed run,
    which clears the declaration. Everything else is derived. Read the
    **Migrating** items on the door before you flip it.

---

### Changed

- **The per-rung gate runs on a verifier box.** `./scripts/check.sh --loop`
  refuses (exit 2, printing the four-line recipe) on a machine that is not
  one; a box is told by a marker the image carries — never by an environment
  variable and never by a hostname — and `CI` is exempt as at the pipe guard.
  The valve is `DJB_LOOP_HERE="<who>: <why>"`, the sanction's own grammar.
  (`scripts/check.sh`, `docs/product/build-contract.md` § Interfaces.)
- **The pre-push wall knows a box from a forge.** A push whose destination is
  a verifier box (`DJB_PUSH_DESTINATION=verifier-box` **and** a remote that is
  `scripts/verifier_box.sh`'s own scratch probe — both, so the declaration
  alone can never open `origin`) is exempt from the *measurement* and never
  from the identity check, because the box's own run is the measurement. The
  hook prints one sentinel on every run — `pre-push: wall
  <honoured|box-exempt|refused|measuring> <tree>` — so a caller can tell a
  wall that passed a tree from a checkout that has no wall at all, and the
  wrapper refuses a push whose dry run printed no sentinel. Also kept from
  the previous draft: the hook reads every pushed ref from stdin, honours a
  banked verdict for the pushed tree, and **refuses a plain `git push` whose
  pushed tree is not this checkout's tree** rather than measuring a tree
  nobody is pushing; a banked full row is honoured only when its legs field
  covers the set `scripts/check.sh` declares today, and says which leg is
  missing when it does not. (`scripts/githooks/pre-push`,
  `scripts/gate_ledger.sh`.)
- **The bank runs on boxes, in parallel legs, and this laptop measures
  nothing.** `./scripts/pm_push.sh --bank --on-boxes N` is the third wired
  ritual form: it folds, reads `./scripts/check.sh --list-legs`, brings up one
  box per unit with the suite unit split across boxes, fetches every shard's
  log and status, and composes ONE ordinary full row (`caller=pm-bank
  sanction=push-wall boxes=<N> shards=<labels>`) that the hook honours through
  the lookup it already does. The composition refuses rather than judges —
  exit 2 with no row for a shard that could not look, a lost log, a reclaimed
  box, a foreign tree, or a leg set that does not cover the declared one;
  exit 1 naming each red shard. A detach that came back 255 (the tunnel a few
  seconds behind the agent) gets exactly one more go after
  `DJB_BANK_DETACH_RETRY_SECONDS`; any other status is not retried. **A shard
  never buys an on-demand machine on its own**: the bank sets
  `DJB_VERIFIER_BANK_SHARD` around each launch, which turns the wrapper's
  Spot-to-on-demand fallback into a refusal that prints the Spot code and the
  hour it declined to buy; `DJB_VERIFIER_ON_DEMAND_OK="<reason>"` is the
  valve and the reason prints in the bank's table. The market each box is
  *actually* on is read back from the cloud and kept in the table, because
  afterwards the boxes are gone and the table is all there is. Every box
  comes down on green, red, exit 2 and on a signal. The plain
  `./scripts/pm_push.sh --bank` with no `--on-boxes` is unchanged and remains
  the unsharded whole-suite two-pass belt. (`scripts/pm_push.sh`,
  `scripts/tests/test_pm_push.sh`.)
- **The `--loop` runs the tests a change can reach, from a map, when it can.**
  `scripts/test_impact.json` says for every collected test which source files
  it executed; when every file the rung changed has been *seen* by the map the
  loop runs those tests plus the always-on set and prints what it selected
  and what it did not; the closure scope is derived, printed and not run. Five
  ways it stands down, each printed: a changed file the map has never
  recorded (every template, fixture, migration and new module, by
  construction), an absent or unreadable map, a map from a tree this
  checkout cannot account for, a seeded census the map holds no test from,
  and `DJB_LOOP_NO_IMPACT`. Each falls back to the closure scope — a slower
  run and never a wrong one. The map's sha is last in the loop key as
  `map=`, so a verdict banked under one map is never reused under another;
  `--mine` and `--pr` are not narrowed. **The map is a projection and never
  truth**: its owner is the bank's acceptance box, one extra machine outside
  the composition that runs the whole suite twice — once under coverage
  contexts — and inverts the result; the bank fetches the file into the
  working tree, prints `git add scripts/test_impact.json` and commits nothing.
  Its status is composed nowhere: a measurement may not refuse a claim every
  shard passed. (`scripts/test_impact.py`, `scripts/loop_tier.sh`,
  `apps/conftest.py`, `scripts/pm_push.sh`.)
- **The pytest slot, the bank and the worker count are one number.** A typed
  `DJB_GATE_SLOT_WORKERS` at or below the slot's share is the share, above it
  is exit 2 naming both; the lease exports the resolved share so
  `apps/conftest.py` clamps nothing inside a gate. A local `--bank` takes every
  free slot and says so; a waiting loop names the bank holding them. The
  collector census expects the number pytest actually created, so a clamp can
  no longer read as dead collectors. (`scripts/gate_lease.sh`,
  `scripts/check.sh`, `apps/conftest.py`.)
- **The db-pin leg asks whether the database exists, under `--loop` and full.**
  An absent database is exit 2 naming the pin's provenance and the remedy
  (`./scripts/setup.sh`, with the pinned name when there is one); `--fast`
  says it did not check and needs no stack. (`scripts/db.sh`.)
- **A verifier's clone gets its own venv before the seed, and the verifier's
  one consult is predicted.** `scripts/verify_start.sh` runs `uv sync
  --frozen` in the clone (skip it with `--no-sync`, which says the seed cannot
  hit), then prints exactly one of `consult: EXPECTED HIT <key>` or `consult:
  WILL RUN (<why>)` — a seeded row for the tree, the union equal to the branch
  tip — so the verifier can compare the builder's `fold:` and `banked:` report
  lines against what the clone will actually do. (`scripts/verify_start.sh`,
  `.claude/skills/rung-execution/SKILL.md`.)
- **The house-rules engine memoises per rule, keyed on what can change that
  rule's verdict.** Each rule's scan is keyed on its own text, its scope, the
  kind walk, the hard-coded reads, its doc anchor and the engine under
  `quality/` — blobs from the measured tree, never the working tree — and only
  the `check:` call is remembered; overrides, ratchets, floors and the Django
  leg run every time. It lives beside the gate ledger in the git common dir
  and is never committed; `DJB_RULES_NO_MEMO=1` scans everything and says so;
  a rule whose check boots Django or shells out declares `memo: {no:
  <reason>}` in `quality/rules.yaml` and a bare `no` is refused as YAML-false.
  The memo pays on the second and later reads of one tree — the hook, the
  loop, the consult and the push all measure one tree. (`quality/gate.py`,
  `quality/rules.yaml`.)
- **The selftest leg runs every drive before it decides, and a drive's verdict
  is reused when its inputs have not moved.** Every `scripts/tests/test_*.sh`
  declares `# drives: <path>…` in its first forty lines (paths a body only
  cites go on `# cites:`); the key is the declared blobs from the measured
  tree, the drive file, the preamble and the machine's own claim, and a body
  that spells a path neither line covers is exit 2 — could-not-look, never a
  silent reuse. The engine's own canary self-test banks the same kind of row
  (`house-rules-engine`), keyed on `python -m quality.gate
  --selftest-inputs`. `DJB_SELFTEST_NO_REUSE=1` runs everything and still
  banks. The leg's exit is composed at the end — 2 if anything could not
  look, else 1 naming every red drive, else 0 — and it shards by drive index
  for CI. **On a box the machine half of the key is the image id**, so two
  boxes cut from one image honour each other's rows and a laptop row never
  matches a box; drive rows — and only drive rows — travel with the push and
  come home with the harvest. (`scripts/check.sh`,
  `scripts/gate_ledger.sh`, `scripts/tests/drive_preamble.sh`,
  `scripts/verifier_box.sh`.)
- **The `--loop` carries an always-on leg derived from a committed
  measurement.** Every full-only member whose recorded seconds in
  `scripts/gate_member_durations.json` are under the floor runs at every
  scope, each consulted against its banked drive verdict first; every
  exclusion prints its reason, a member the file names that the gate does not
  have is exit 2, and the file is rewritten only by `./scripts/check.sh
  --store-durations`. A pytest module that walks the whole tree declares
  `# census: cross-app <reason>` at column zero and is always-on; with
  `population=<glob>,…` it runs only when a changed file falls inside the
  globs; `apps/test_census_markers.py` catches a marker with no walk behind
  it and a walker with no marker, over pytest's own collection. A rung that
  changes any app's `policies.py` or `roles.py` seeds the vocabulary census
  into its scope through the `CENSUS_SEEDED_BY` marker, so a sweep can no
  longer deselect the test that judges it. (`scripts/check.sh`,
  `apps/conftest.py`, `scripts/loop_tier.sh`.)
- **CI runs the gate's units, not a gate.** `.github/workflows/ci.yml` derives
  its matrix from `./scripts/check.sh --list-legs`, mints one seed for every
  row, runs `--leg <unit> [--shard k/N]` per runner with `--pr --base <sha>`
  on a pull request and nothing on `main`, and composes a `verdict` job. The
  suite is sharded, so the second pass's idempotency claim narrows to *within
  a shard*; group membership is a function of the seed and CI mints a fresh
  one per run, so a cross-shard leak surfaces within a few runs rather than
  never — declared in `docs/product/build-contract.md`. (`.github/workflows/ci.yml`.)
- **Four `--fast` censuses ask a closed question of a document.** `adr-census`
  and `dangling-docs` now run per rung over the active rung's changed files as
  well as at publication; `loop-names` reds when `scripts/check.sh` reads a
  `LOOP_*` name nothing assigns; `ci-env` reds when a credential the settings
  read from the environment is missing from the workflow's `env:` block, and
  skips with a printed line where there is no workflow. One library, sourced
  by the gate, the publisher and their drive. (`scripts/docs_legs.sh`,
  `scripts/tests/test_fast_censuses.sh`.)
- **Permissions are one shape, `<kind>.<verb>`.** Every first-party model is a
  kind with `create/read/update/delete` derived (`authz_kind` renames it,
  `authz_kind_of` folds a child under its aggregate's kind, `None` with a
  reason opts out — class attributes, no field, no migration); every other
  verb is declared on a kind in `ACTION_PROSE`; `tenant.own` is reserved and
  matched by no pattern; a role is a set of patterns over that vocabulary,
  and `owner` holds all of it. `admin` and `member` are declared in
  `apps/core/roles.py` — the file in `core` a product edits or deletes — and an
  app may declare its own roles in its `roles.py`; `core.Role`,
  `core.RolePermission` and `core.Grant` carry custom roles, deltas and
  per-person grants, and `Membership.role` keeps its string value as the
  role's key. The vocabulary is computed at import and never stored, and
  `manage.py introspect` prints all of it (`policies`, `roles`, and
  `authz_kind` on every model row). The template keys that were renamed are
  under **Migrating** — the table is derived from `renamed_permissions()`,
  which unions every app's `RENAMED_PERMISSIONS`, and an old key keeps
  answering at `require` time for one release. A product's own `require`
  keys must fit the shape or carry `# authz-kind:` / `# authz-key:` with a
  reason (rule 13 says which line); `ROLE_RANK`, `rank`, `effective_role`,
  `actor_role`, `membership_for` and `Membership.is_privileged` are deprecated
  until v3.0. (`apps/core/authz.py`, `apps/core/roles.py`,
  `apps/core/models.py`, `docs/product/architecture.md` ADR core-25.)
- **Resolution is one walk, and withhold wins.** `allows` resolves the node
  the key is about (an organization is its own node, a row its
  `organization`, no object the acting hat, no hat the tenant-wide union),
  unions the memberships on the chain with their roles' collections and allow
  grants, subtracts withholds, ANDs the declared predicate, and `require`
  raises `Forbidden` with the key's own sentence. `effective_permissions`,
  `holds` and `where_of` are the public names; the actor memoises the three
  tables' rows for the request, so a second `require` costs nothing more and
  `Actor.forget_permissions()` is the one invalidation. Reach is asked before
  capability everywhere: a row outside your subtree is `not_found`, never
  `forbidden`, and rule 26 now reds the inverted order. `may_administer` is
  gone — its keys are held by the declared `admin` at the node the object
  names. (`apps/core/authz.py`, `apps/core/actor.py`.)
- **`POST /memberships/` and `create_membership` refuse a `member` adding a
  `member`** — the contract always said so; the wall speaks first, the
  capability second, the ceiling third.
- **Reads are permissions.** Every `<kind>.read` is held by `owner`, by `admin`
  (`*`), by `member` (`*.read`), and by whatever a custom role includes or a
  grant allows; a membership with no role reads nothing; a read outside your
  subtree is `not_found`, inside it without the key `forbidden`; the Django
  admin's changelist shows its 403 page rather than an empty list; a socket
  computes its read set once at connect and hears only the kinds it holds,
  and a narrowing that lands mid-request closes the socket rather than
  leaving it listening. A product that customised nothing observes no change
  (the flat-product census is the proof). **A custom role reads nothing until
  its collection names reads**, and **a DECLARED role is the half that
  surprises people**: a role declared with write-only patterns reads no kind
  after this release, because a declaration is a collection too. The fix is
  one pattern, `"*.read"` (or the kinds you mean), in the `roles.py`
  declaration or in `create_role` / `set_role_collection`'s `permissions`.
  The one declared residual: the selectors in `apps/accounts` do not ask yet
  (`user.read`, `sso_connection.read` close no door today); rule 54 carries
  them as a counted ratchet and the sweep follows the identity lane.
  (`apps/core/authz.py`, `apps/core/selectors.py`, `apps/realtime/consumers.py`,
  ADR core-27.)
- **Sight is the hat's; configuration is the root's.** A tenant-wide kind —
  one whose row names no branch: connections and inbound webhooks, webhook
  endpoints and deliveries, message templates and delivery policies, roles
  and grants, workflow runs, SSO connections — is **read at the acting hat**
  and **written at the tenant's root**. So in a hierarchical product a member
  of one branch holding `*.read` sees the tenant's shared configuration, and
  an administrator of one branch reads it and cannot change it; no secret
  rides any of those reads, because no `Out` carries one. A tenant that wants
  a branch blind to one kind withholds `<kind>.read` on that branch's
  memberships — one row, the same mechanism as every other narrowing. This is
  a v2.1 STOPGAP and says so: each hat-scoped read site carries a dated
  `# hat-scoped: <reason>` valve that rule 55 counts (the four read sites in
  `core` sit in the rule's ratchet instead, by the owner's ruling that the
  rule gains no read clause), and the successor is universal homing — the
  proposal of 2026-09-17 in the platform's `docs/product/proposals/` — where
  every record has one home. (`quality/rules.yaml` rule 55, `apps/*/selectors.py`.)
- **A read withhold refuses a write that reads on the way.** `send()` fetches
  the template, the delivery policy and the channel preference with the
  caller's actor, so a person holding `message.send` with one of those reads
  withheld gets 403 with the READ's sentence and no message goes out; an
  export archives only the kinds its requester can read at build time and
  names what it omitted in `manifest.json`; a file version asks the
  document's key; search intersects the requested kinds with the readable
  ones before the engine is asked. Read this as the general shape rather than
  one service's quirk. (`apps/comms/services.py`,
  `apps/exports/activities.py`, `apps/files/services.py`,
  `apps/search/selectors.py`.)
- **`device.create` (the rename of `device.register`) admits every
  membership**, which is the reach the old word already had.
- **A product's own `get_`/`list_` selectors over a kind are red under rule
  54 (d)/(e)**, fixed per selector by one keyword-only `actor` plus
  `require(actor, "<kind>.read", …)`, or by one `# read-open:` /
  `# read-kind:` marker for a machine read. **The marker must open a comment
  line** — a docstring sentence that mentions it is prose, not a valve — and
  both are counted on the rule's own status line. Rule 54 (a) now also reads
  every `POLICIES` and `DEFAULT_ROLES` key against the vocabulary, and rule 24
  names the six permission services as the only writers of grant and delta
  rows. (`quality/rules.yaml` rules 13, 24, 54.)
- **Tenant-wide kinds are asked at the root, and the SSO surface is one of
  them.** `sso_connection.create/update/disable` and `sso_domain.verify` ask
  at the tenant's root; before, an administrator of any leaf could rename,
  re-domain, enforce or delete the tenant's identity provider. A token pinned
  to a suspended or closed tenant resolves nowhere on every door, and a
  membership's node is checked against the tenant before the memo — every
  tenant's root shares one path, so a foreign root used to resolve as yours.
  (`apps/accounts/services.py`, `apps/core/middleware.py`,
  `apps/core/authz.py`, `quality/rules.yaml` rule 55.)
- **A tenant that goes dark hangs up.** `suspend_tenant` and `close_tenant`
  kick every socket in the tenant on commit; `resume_tenant` kicks nobody;
  a `@service` that writes a non-active status without calling the kick is
  a red under rule 36's new status-writer census. A socket joins the
  person's own group first, before the subtree and the read set, so a
  narrowing that commits during `connect` is delivered after it returns
  rather than lost in the window. (`apps/core/services.py`,
  `apps/realtime/bridge.py`, `apps/realtime/consumers.py`.)
- **`core` says what happened, through the bridge.** `apps/core/events.py`
  declares the role, membership and grant events and `services.py` emits each
  inside the transaction of the write it describes, without importing the app
  that owns the outbox. (ADR core-26.)
- **The identity join is keyed on the subject, and refusals write nothing.**
  A sign-in whose subject differs from the one on file is refused, never
  merged; a deactivated person meets one sentence at every door before any
  row is written; pending invitations are accepted at sign-in, after the
  subject is recorded. `manage.py unlink_identity --email <address>` or
  `--all --yes`, always with `--reason`, clears the standing subject, deletes
  the platform-provider social rows and nothing else, closes sockets on
  commit and audits under `accounts.unlink_zitadel_identity`; the permission
  is `user.unlink`. (`apps/accounts/adapter.py`,
  `apps/accounts/services.py`,
  `apps/accounts/management/commands/unlink_identity.py`,
  `apps/accounts/tests/test_refusals_write_nothing.py`.)
- **A domain claim routes nothing until verified.** `SsoDomain.verified_at`,
  set only by `verify_sso_domain` (an operator's audited act, permission
  `sso_domain.verify`, at the root); `for_domain` honours verified rows only;
  a claim still reserves the name; `SsoConnectionOut` gains
  `verified_domains`. (`apps/accounts/models.py`,
  `apps/accounts/management/commands/verify_sso_domain.py`, ADR ident-10.)
- **The admin's login URL is not a password door.** `/admin/login/` sends an
  anonymous person to sign in, a staff member into the admin, a signed-in
  non-staff person to a 403 page, and answers a POST with 405 — no backend is
  consulted; `manage.py grant_staff --email <address> [--as <superuser>]` is
  the one road to `is_staff`, an audited service that refuses an inactive
  account. (`apps/accounts/admin.py`, `config/urls.py`,
  `apps/accounts/management/commands/grant_staff.py`.)
- **The seed reconciles the browser client, and says what it did.**
  `zitadel_seed` writes the browser client's redirect URIs, post-logout URIs
  and `devMode` from settings on every run — restoring a console edit,
  following a `PUBLIC_BASE_URL` change, and **clearing a URI no longer
  declared** — and prints `updated` beside `created` and `exists`; the
  closing warning now tells a second checkout on one project how to get the
  secret without rotating it out from under the first. (`apps/accounts/management/commands/zitadel_seed.py`,
  `apps/accounts/zitadel.py`.)
- **The audit judges more and says what it cannot.** `zitadel_audit` gains
  three verdict words beside `agrees` and `DRIFT`: `unreadable` (a surface it
  could not look at), `observed` (a surface it reads and does not judge — the
  console's own settings), `foreign` (a fact owned by somebody else, named —
  the instance's SMTP sender). It now judges the browser client's URIs and
  `devMode`, the project's and applications' existence (two projects of one
  name is drift naming both), and the `.env` copies `ZITADEL_CLIENT_ID` and
  `ZITADEL_MCP_AUDIENCE` against the live ids — a mismatch is drift with the
  remedy in words; unset is not a difference. Exit 0 agree · 1 drift · never
  2; the closing line still begins `Zitadel agrees with every row` when it
  does. (`apps/accounts/management/commands/zitadel_audit.py`.)
- **The two 401 envelopes agree.** REST and MCP answer a presented-but-invalid
  bearer with one sentence declared once (`BEARER_NOT_VALID`), and `/mcp`
  offers only the remedies it can act on. Status and code are unchanged; a
  client asserting the old REST sentence for a revoked token breaks.
  (`apps/accounts/auth.py`, `config/mcp.py`.)
- **The workforce door has an OFF road.** An empty `GOOGLE_WORKSPACE_DOMAINS`
  beside a live Google identity provider now *deactivates* that provider on
  the next workforce sync or reconcile — never deletes it. What a run
  observed rides in its run key, so a re-ask of the same intent over a
  changed live row is a new run. (`apps/accounts/activities.py`,
  `apps/accounts/services.py`.)
- **`record_run` has a fifth answer.** `reask_after_failure=True` re-opens a
  failed or cancelled run under the same id with an audited receipt naming
  what it closed and the previous error; a completed run stays `Conflict`;
  the default is unchanged, so every existing start site is byte-identical.
  (`apps/workflows/services.py`, `apps/core/bridge.py`.)
- **The tenant root has a memo.** `root_organization` remembers the root for
  the request and `resolve_org` fills it when the hat is the root; a query
  budget pinned over a door that resolves the root may drop by one.
  (`apps/core/models.py`, `apps/core/services.py`.)
- **The gate's three bookkeeping refusals now print an offer.** A `budget:`
  line, the frontend leg's CLIENT SUSPECT state and a bank's BASELINE SHIFTED
  each name `./scripts/rung_tidy.sh` with the flag that applies what the
  instrument already computed, through the writer that owns it; it never
  commits and never runs the gate. (`scripts/rung_tidy.sh`,
  `scripts/budget_notes.sh`, `scripts/rung_start.sh`.)
- **The primer's first ten minutes are the README's.** `CLAUDE.md`'s
  authority table points at `README.md` § "Quickstart, from a fresh clone",
  the primer's step 0 points there too, and `README.md` gained "What you
  get", "Who it is for" and "What it is not" for a reader who has not decided
  yet. (`README.md`, `.claude/skills/platform-primer/SKILL.md`.)
- **Skills.** `django-conventions` carries the socket law (rule 58);
  `rung-execution` carries the box recipe and the `fold:`/`banked:` report
  lines; `product-manager` and its dispatch briefs carry batched builds and
  verification, the watcher rule, the box clause and explore-then-codify
  against a real external system.

- **The login version is a declaration per application, through the one
  door, and `None` is the clear.** `ensure_application_login_version` writes
  `loginVersion.loginV2.baseUri` on an OIDC client with the full-body PUT the
  other writers use, and a `None` removes the key from the live object — the
  road back that turns the door from a one-way flip into a setting. The seed
  passes what `declared_login_base_uri()` answers for the door (`None` under
  `hosted`, so a shared instance is stamped by no checkout); `zitadel_audit`
  judges the live `loginVersion` on every OIDC client the seed made, and a
  value the console set that the deployment did not declare is `DRIFT`;
  `zitadel_reconcile` repairs it both ways through the seed road. The
  instance-wide flag (`ZITADEL_LOGIN_V2_REQUIRED` in `compose.yaml`) stays
  `false` and is never the mechanism. (`apps/accounts/zitadel.py`,
  `apps/accounts/management/commands/zitadel_seed.py`,
  `apps/accounts/management/commands/zitadel_audit.py`.)
- **The machine credential's `IAM_LOGIN_CLIENT` role is declared, judged and
  repaired.** Finalizing an OIDC auth request from our page needs that
  instance-member role and `IAM_OWNER` does not carry it; `zitadel_seed`
  grants it additively through `ensure_instance_member_role`, the audit's
  `login client` section says who holds it or names the finalize that will
  fail without it, and the reconciler carries it as its fifth kind. (`apps/accounts/zitadel.py`,
  `apps/accounts/management/commands/zitadel_reconcile.py`.)
- **The entrance shell styles forms, and the sign-in page is a switch over
  frames.** `templates/account/base_entrance.html`'s one inline token block
  gained the form primitives — a labelled field, a password field with Show,
  a code field, an alert note with its remedy line, a chip row — still with
  no fetch. `templates/account/login.html` picks one file from
  `templates/account/frames/` by the `frame` the view hands it and renders
  today's page byte for byte when handed none; an unknown frame name raises
  the file it looked for rather than drawing a plausible screen, and the
  door picks each frame's `<title>` (`FRAME_TITLES` in
  `apps/accounts/views.py`, censused against the directory). The set of
  legal frames is the directory, and `apps/accounts/tests/test_entrance_frames.py`
  is its census.
- **The seed, the reconciler, the audit, `zitadel_first_admin`, the
  invitation link and the sign-out page branch on the door.** `invite_url`
  points at our page under `ours` and at the platform's credential page under
  `hosted`, with the platform's own query on both (`?userID=…&code=…`) so an
  operator comparing two links sees one tail; `zitadel_first_admin` prints
  the link the door serves and counts the steps the door has (two under
  `ours` — setting the password signs them in on the same page-load; three
  under `hosted`); `templates/account/logout.html` says what happens to the
  session under each door. (`apps/accounts/zitadel.py`,
  `apps/accounts/management/commands/zitadel_first_admin.py`.)
- **The production CSP admits the declared clients' redirect origins under
  `ours`, and only then.** The `form-action` derivation in
  `config/settings/production.py` already admitted the hop OUT to the
  platform's authorize endpoint; it now also admits the hop BACK — the 302
  our page answers after the finalize, towards the browser client's and the
  MCP clients' registered redirect URIs — read from `zitadel_seed`'s own
  constants, never a hand list, and empty under `hosted` because no form of
  ours is ever submitted into that chain there. The failure it closes is
  invisible from the server: every headless drive passes while a browser
  silently declines the redirect.
- **The welcome page names the next act on a fresh deployment.** When no
  tenant exists yet, the "None resolved" branch prints `manage.py
  bootstrap_tenant --email <the signed-in address>`; a person with no
  membership on a live deployment still reads the sentence they read before.
  (`apps/core/templates/core/welcome.html`, `apps/core/views.py`.)
- **The identity mechanism tests read the declared shape.** The tests that
  asserted the template's own spelling — the entrance marker, the posture
  writer, the branding sections, the first-admin link — now read
  `IDENTITY_SHAPE` or the tree's own function, so a product that declared
  `DJB_IDENTITY_SHAPE` runs them green rather than skipping them; only the
  tests that assert a surface you replaced skip. (`apps/accounts/tests/`,
  `apps/core/tests/test_welcome.py`.)
- **`quality/rules.yaml` rule 27 admits the sign-in seam and the measurement
  kit as request-path importers of `zitadel.py`**, each with its `# rule-27:`
  reason on the import line; rule 11's module list for `accounts` gains
  `signin`, `views` and `qr`. A product carrying its own copy of the rule
  file takes the template's.

---

### Added

- **`scripts/verifier_box.sh` — one throwaway cloud machine per verification,
  from this laptop.** `up --for <rung>` launches a box from the newest image
  baked from `main` (Spot, falling back to on-demand and saying so, with a
  hard lifetime the box enforces on itself and an idle reaper inside the
  image so teardown needs no session), pushes the rung's tree over SSH through
  Session Manager into a parked checkout with the fork point carried as a
  ref, and hands back an id. `loop <id> --log <name>` runs the per-rung gate
  there; `leg <id> --unit <unit> [--shard k/N]` runs one unit; `wait`,
  `fetch`, `harvest` and `harvest-drives` bring the verdict, the artefacts and
  the drive rows home; `run <id> -- <cmd>` is any other command; `down <id>`
  or `--all-mine` takes boxes down; `pool --want N` keeps warm ones;
  `census` lists every box of this namespace with its market, image, owner,
  expiry and the pool's hourly rate, exit 1 on an overdue box; `bake
  [--plan|--keep|--prune]` makes the image, printing the recipe before
  spending anything. The agent stays here: only the clone, the stack and the
  gate move. No key pair, no ingress rule, no credential on the box, and
  every name is derived from `DJB_DEPLOY_NAMESPACE`, so two products in one
  account never see each other's machines. Exit 0 did it · 1 a finding · 2
  refused or could not look; a remote status passes through unchanged.
  (`scripts/verifier_box.sh`, `deploy/verifier/bake.sh`,
  `deploy/verifier/user-data.yaml.in`, `deploy/verifier/idle_reaper.sh`,
  `deploy/iam/verifier_bootstrap.sh`, `deploy/iam/verifier-ops-policy.json`,
  `scripts/tests/test_verifier_box.sh`, `scripts/tests/test_verifier_image.sh`.)
- **`./scripts/check.sh --list-legs`, `--leg <unit> [--shard k/N]
  [--store-durations]`, and the bare `--store-durations`.** The gate prints
  its own legs grouped into the units one runner can be handed, and runs one
  unit under the full gate's exit contract with no lease, no lock, no
  verdict and no sanction; a suite unit shards `k/N` balanced by
  `scripts/pytest_durations.json`, a shard that collects nothing is exit 2,
  and `DJB_GATE_PYTEST_SEED` types the seed every shard of one run must
  share. The bare `--store-durations` is the full gate run to be timed,
  rewriting `scripts/gate_member_durations.json` and banking nothing. The
  table in `docs/product/build-contract.md` is a copy; the listing is the
  authority and a drive asserts they agree. (`scripts/check.sh`,
  `scripts/tests/test_list_legs.sh`, `scripts/tests/test_shard_census.sh`.)
- **`scripts/loop_metrics.py` — the pipeline measured, never typed.** It reads
  the dispatch ledger's stamps (`sent · done · met · merged · pushed ·
  staged`, one clock), the bank and loop logs, and prints the cost-baseline
  row to paste: the per-rung and per-wave clocks that together are the
  pipeline time, and the inner loop by change class. A malformed stamp is
  exit 2 naming the row and the field; an unstamped row is counted and named,
  never dropped; there is no exit 1, because it judges nothing. It has no
  shebang on purpose and is run through the checkout's own interpreter.
  (`scripts/loop_metrics.py`, `scripts/tests/test_loop_metrics.sh`.)
- **`deploy/stage.sh` — from a green tree to a healthy stage box, keyed.** Six
  acts, each printing `stage: [i/6] <act> — ran: <what>` or `— skipped:
  <input> unchanged`: `ship` when the tree tag moved · `secrets` when the ship
  ran · `login` when `up` will run · `up` when the tag or an image digest
  moved · `release` when a migration leaf, `deploy/observability/` or a digest
  moved (passing `--without-alerts` when observability did not) · `readyz`
  always. `--dry-run` says what would run and touches nothing; a docs-only
  delta is `nothing to deploy`, exit 0; a dirty tree, a box with no `TREE`
  marker or a registry without this tree's image is exit 2 before anything
  is shipped; an act that ran and failed is exit 1 naming it, and the
  recovery is `deploy/release.sh` from the top. It does not build, does not
  roll back and does not decide. Its drive is the first under `deploy/tests/`
  the gate runs. (`deploy/stage.sh`, `deploy/tests/test_stage.sh`.)
- **`manage.py zitadel_reconcile` — the audit's other half.** It reads through
  the audit's own section functions (one read, not two), prints the same
  lines, then per finding `would ask` (`--dry-run`), `asked`, `left <why>` or
  `blind`; every repair is a service ask that starts the sync workflow on
  commit, the one declared exception being the `applications` kind, which
  runs the seed and says so. `--kind`, `--tenant`, `--as <email>` narrow and
  attribute. Exit 0 asked or nothing to ask · 1 a delta still open · 2 could
  not look. **Its docstring is the ownership table**: every identity fact's
  authority, copy, settlement, staleness and repair kind, including the ones
  nothing repairs. Two projects bearing the declared name are refused, never
  renamed. (`apps/accounts/management/commands/zitadel_reconcile.py`, ADR
  ident-2 as amended.)
- **`DJB_IDENTITY_SHAPE` — a product declares what it replaced, and the tests
  that assert the template's surface skip.** Six keys, `key=value;…`, closed
  vocabularies where there is one, refused at settings import for an unknown
  key, an empty value or a value outside the vocabulary; a tree that declares
  nothing runs everything. The mechanism tests underneath keep running.
  (`config/settings/base.py`, `apps/core/tests/template_shape.py`,
  `.env.example`.)
- **The roles and grants doors.** Routes on `roles_router` for listing,
  creating, updating and deleting roles, replacing a role's collection,
  listing and setting a membership's grants, reading a membership's effective
  permissions with each key's sentence and where it came from, and listing
  the vocabulary — with an MCP twin for each, described by the same contract.
  Six services own the writes (`create_role`, `update_role`,
  `set_role_collection`, `delete_role`, `create_grant`, `delete_grant`); a
  refusal lists the missing permissions' sentences, never keys, and deleting
  a role somebody holds is 409. (`apps/core/api.py`, `apps/core/mcp.py`,
  `apps/core/services.py`, `apps/core/schemas.py`.)
- **`manage.py rename_permission <old> <new>`** — moves stored grant and delta
  rows across every tenant, refusing any pair the rename table does not
  declare and any successor outside the vocabulary; see **Migrating**.
  (`apps/core/management/commands/rename_permission.py`.)
- **Six house rules, 54 to 59.** **54** the vocabulary is one shape (kinds
  derived, declarations name declared things, no role by value, every public
  read asks). **55** a permission whose kind names no node is asked at a node
  the caller resolved, never at the hat by default. **56** home-realm
  discovery is one question with one answer — `for_domain` from the selectors
  and `claim` from the services, nowhere else. **57** which subject signs in
  as which person is written by `record_zitadel_identity` and cleared by
  `unlink_zitadel_identity`, and nowhere else. **58** nobody names their own
  group and nobody mounts an open socket. **59** an org-scoped event carries
  its branch, and an org-less kind names none. Each with its canaries and
  negatives under `quality/canary/5<n>/` and `quality/negative/5<n>/`, each
  with a valve or a declared reason there is none, and each printed by
  `python -m quality.gate --explain <id>`. (`quality/rules.yaml`,
  `quality/checks.py`.)
- **Per-app authorization sweeps as tests.** Every swept app carries
  `tests/test_authz_sweep.py` with a derived `authz_baseline.json`,
  `tests/test_reads_ask.py` over a population derived from the AST, and a
  door-pair case asserting both doors refuse a withheld read with the same
  words; `apps/core/tests/flat_product_baseline.json` is the flat-product
  census the release keeps promising. (`apps/*/tests/`.)
- **`DEFAULT_ROLES` is a declaration, not a rung.** No app declares one yet;
  the member-admitting predicates that stand in for it say so in their
  docstrings, and rule 54 reads every `DEFAULT_ROLES` entry it finds.
  (`apps/*/policies.py`.)
- **`scripts/tests/fixtures/collection_world/`** — a planted world of apps for
  the scope and shard drives, so a selection rule is proven over a
  collection the test built rather than the tree it happens to run in.
- **Two proposals for the owner, written and not decided**, kept in the
  platform's `docs/product/proposals/` (not shipped): universal homing
  (2026-09-17 — every record has one home, the successor to the hat-scoped
  stopgap) and the caching seam (2026-09-16).

- **`SIGN_IN_DOOR` — one setting, two doors, no third state.** From
  `DJB_SIGN_IN_DOOR`, `ours|hosted`, default `hosted`; any other value is
  `ImproperlyConfigured` at import rather than the other door. Our view is
  mounted at `/accounts/login/` one line ahead of allauth in `config/urls.py`
  (route name `sign-in`; allauth's `account_login` still reverses to the same
  path). Under `hosted` GET renders the page it always did and POST is still
  refused; under `ours` GET renders the sign-in frame and POST carries a closed
  `action` vocabulary — an unknown action is 400, never a re-rendered form.
  `?next=` rides in the server-side ceremony and only a same-origin value
  survives; a foreign one is dropped. Every example env file carries the line
  commented with `hosted`. (`config/settings/base.py`, `config/urls.py`,
  `apps/accounts/views.py`.)
- **`apps/accounts/signin.py` — the sign-in check as a seam over the Session
  API.** Every entry point returns one `SignIn` whose `outcome` and `step` are
  members of closed enums, so the page is a switch over a finite set. Four
  fail-closed rules: a 2xx is not a verified anything (the verdict is read off
  `factors.<kind>.verifiedAt`, never a status); an answer the seam cannot read
  is an outage, never a pass; a 401/403/429 is about OUR credential and is an
  outage, never the person's fault; a factor kind the seam cannot answer is
  never satisfied and never a hand-off. A 404 carrying no Zitadel error id is
  a route the build does not have and reads as an outage (503), while a judged
  404 still carries one and stays a refusal. Two clocks — `ZITADEL_SIGNIN_TIMEOUT`
  bounds one call, `ZITADEL_SIGNIN_DEADLINE` bounds the whole check on a
  monotonic start consulted before every call. `SIGNIN_THROTTLE_PER_MINUTE`
  is this product's own per-address limit in front of the platform's account
  lockout, and the sixth try never asks Zitadel. Every session the seam opens
  it closes, at every exit including the person's own *Never mind*; the
  ceremony's keys are a closed set deleted at every exit; no address, password,
  code, token or enrolment secret reaches a log line, and a test drives the
  whole ceremony to prove it. It writes no row and imports no model, and one
  door reaches it. (`apps/accounts/signin.py`, `apps/accounts/tests/test_signin.py`.)
- **The second factor on our page.** After the password, a person with a
  factor enrolled meets *One more step*: a code from an authenticator app, or
  an emailed code — the chips are drawn from what the platform says is
  enrolled intersected with what this deployment can deliver, so the emailed
  chip appears only with SMTP configured on the instance, and when that
  sender belongs to somebody else the face names whose mail to expect. A
  wrong code reads the refused sentence and the form stays with the typed
  address in it; *Never mind* ends the ceremony and says nothing was changed.
  An organisation that forces a factor sends an unenrolled person to *Set up
  two-factor*: a QR drawn in-tree from the TOTP URI (`apps/accounts/qr.py` —
  an encoder with no I/O and no dependency, because a hosted image service
  would be handed every person's enrolment secret in a query string), the
  secret as text, the code field, and *Not now* only when the organisation's
  `mfaInitSkipLifetime` allows it. Every failure sentence from the design's
  table has a case, none names a tenant, a connection, an error id or whether
  an account exists, and "MFA", "2FA", "U2F" and "WebAuthn" appear on no face.
  (`apps/accounts/views.py`, `templates/account/frames/one_more_step.html`,
  `templates/account/frames/set_up_two_factor.html`.)
- **Passkeys, from a static file.** `apps/accounts/static/accounts/signin.js`
  is the entrance's only script — served from this origin because the
  production CSP is `script-src 'self'`, and it fetches nothing; it toggles
  Show on the password field, reveals *Sign in with a passkey* only where the
  browser can run WebAuthn, and runs the ceremony the door handed it. The
  affordance is drawn at all only where the deployment's host is a legal
  relying-party id (`signin.passkey_road_open`): an IP literal is not one, so
  the template's own `PUBLIC_BASE_URL=http://127.0.0.1:8000` withholds it
  rather than drawing a button no browser can complete; `localhost` and any
  real hostname open the road. A passkey enrolled on the platform's own pages
  is bound to the platform's relying party and reads its own sentence
  (`passkey_elsewhere`) rather than an outage; the platform's 500 for a person
  with no passkey is read as "no passkey here", never as an outage.
  (`apps/accounts/signin.py`, `templates/account/frames/sign_in.html`.)
- **The invite road on our page.** The invitation mail's link and
  `zitadel_first_admin`'s printed link open *Choose your password* under
  `ours`: the address shown is read back from the platform's user record,
  never from the URL; the password rule sentence is the organisation's own
  complexity policy read at render, not a number typed here; the expiry is the
  platform's invite-code lifetime. `signin.set_invited_password` is the one
  place the two platform calls happen in order — `verify_invite_code`, then
  `set_first_password` — because the platform's password write takes no code
  at all and the verify is this seam's own check. Setting the password signs
  the person in on the same page-load and lands them on `LOGIN_REDIRECT_URL`,
  never on the platform's console. Three failure states (`invite_gone`,
  `invite_weak` with the policy's own reason as one sentence, `invite_refused`
  with the sign-in form under it), and no platform error id reaches the page.
  (`apps/accounts/signin.py`, `apps/accounts/zitadel.py`,
  `templates/account/frames/choose_your_password.html`.)
- **The OIDC hand-back finishes on our page.** With login v2 declared, the
  platform's authorize endpoint sends the browser to `/accounts/login/?authRequest=…`;
  the view reads the request (`read_auth_request`), runs the ceremony, and
  either hands the verified session back (`finalize_auth_request`) and 302s to
  the client's registered redirect URI, or refuses it with the platform's
  own reason enum (`refuse_auth_request`). The browser relying party's own
  round trip through allauth's callback and the MCP native client both land
  this way, so a product's assistant connector signs in on the product's page.
  An expired, answered or unknown auth request reads `request_gone` and names
  the app that sent them; a client asking `prompt=create` reads `no_sign_up`
  with the sign-in form under it, because there is no registration door here.
  A callback whose scheme is not http(s) is a 503, not a 500. **One declared
  exception to "every session this module opens, it closes":** a session that
  was finalized into an auth request is left to the platform's own lifetime,
  because the client spends its code after our page has answered — closing it
  first made every token exchange fail; the ceremony is still deleted and the
  token never leaves the process. The ADR amendment is proposed, not signed.
  (`apps/accounts/views.py`, `apps/accounts/zitadel.py`,
  `apps/accounts/tests/test_rp_login.py`.)
- **`manage.py zitadel_measure` — ask the pinned identity platform what it
  actually answers.** Every constant in `apps/accounts/zitadel.py` marked
  MEASURED is a claim about somebody else's product that nothing re-asked, and
  the suite may not dial. This instrument prints one line per fact with four
  verdicts — `ok`, `DIFFERS`, `could not`, `unmeasured` — and exits 0 agreed
  · 1 at least one `DIFFERS` · 2 at least one `could not`, with 2 outranking
  1 because a disagreement beside an unreadable surface may be that surface's
  artefact. It builds its own victims (one organisation and one human under a
  printed prefix, deleted before it returns) and announces them before the
  first create so a run that dies mid-flight has already said what it left.
  Its blind spots print beside the verdict on every run. It is the tripwire
  for a platform bump: run it, and read the lines that moved. (`apps/accounts/management/commands/zitadel_measure.py`,
  `docs/product/instruments.md`.)
- **The client's socket close-frame seam.** `frontend/src/api/socket-close.ts`
  is the one module that knows a close code is a number; the vocabulary is
  `apps/realtime/schemas.py`'s and is held in place by a census test that
  reads that module and asserts set-equality both ways. Two observable states
  render on `/states` with one act each (a plain link to sign in): a handshake
  rejection (what a real browser sees as 1006 with no reason, because the
  socket door closes before it accepts) and a post-accept close because the
  credential was withdrawn. No automatic reconnect — the person's click is the
  retry. The codes the wire never delivers to a browser are marked so, with
  the reason, rather than rendered. (`frontend/src/api/socket-close.ts`,
  `frontend/src/copy/refusals.ts`, `frontend/src/app/states/`.)

---

### Fixed

- **Docs-only `--loop` reuse rests only on a verdict measured on a committed
  tree.** A `--loop` verdict is keyed on the measured working tree, which is
  routinely dirty, so a banked row could name a head whose committed bytes
  nothing had measured; the reuse now refuses unless the row's tree is its
  head's committed tree, and every miss prints how many paths changed since
  the banked head and whether they were docs-only. (`scripts/gate_ledger.sh`.)
- **The `--loop` key stands on the environment the suite actually reads.**
  The fingerprint folds the effective value of every name
  `quality/partition.py::suite_environment_names()` returns — process
  environment over `.env` — so a bent variable is a different key rather than
  a reused verdict. (`scripts/gate_ledger.sh`, `quality/partition.py`.)
- **The partition leg is green on `main`.** The settings tests read the
  settings module's own `_env_file` rather than rebuilding a path beside it.
  (`apps/core/tests/test_settings.py`.)
- **A could-not-look is never downgraded by the exit census**, and the
  gate-explain drive never plants over a path a product owns: it refuses an
  existing target, removes only what it created, and reports what moved.
  (`scripts/tests/test_gate_explain.sh`.)
- **Drives are honest on Linux.** A `pipefail` tail that ate a verdict, a
  `stat` whose flags are BSD's, a nested run whose reds were swallowed, and
  the `mktemp` template GNU refuses — each found by the first sharded CI run
  or the first box and fixed where it was wrong, with a drive census that
  lifts every name the workflow exports and asserts it is stripped or
  declared. (`scripts/tests/drive_preamble.sh`, `scripts/verifier_box.sh`,
  `scripts/tests/test_sweep.sh`, `scripts/tests/test_pipefail_readers.sh`.)
- **Seven ratchet classes that had headroom above their real count read as
  dead canaries**; each now sits at its count, and an owned child's
  declaration is read through one seam by the census and the registry alike.
  (`quality/rules.yaml`, `quality/checks.py`.)
- **The grants list rendered a 500 on any non-empty page**, and a reserved
  key at role creation now says "reserved". (`apps/core/api.py`.)
- **A branch member's read of the tenant's shared configuration used to
  reach for the root** in the events and connections selectors; the root form
  is gone and the reads ask at the hat with a dated valve.
  (`apps/events/selectors.py`, `apps/connections/selectors.py`.)
- **The sign-in page's no-provider sentence claimed `setup.sh` writes the
  client id**; it now says what to paste and where.
  (`apps/accounts/templates/account/login_doors.html`.)
- **A bake box now receives the first push**, a failed bake takes its own box
  down and says when it cannot, the push's proxy command survives git's
  shell, a tunnel under the throughput floor is refused by name rather than
  stalled through, the bake's base image can be pinned so two field tests a
  day apart are one experiment, and the bake parks the checkout before
  `setup.sh` derives the database name from the branch it is standing on.
  (`scripts/verifier_box.sh`, `deploy/verifier/bake.sh`.)
- **The reverse `depends_on` walk and the tests-only rule** are unchanged
  from 2.0.0; what changed is what runs around them.

- **`deploy/release.sh` refuses a stale pin before act 1.** When
  `deploy/.env`'s `DJB_IMAGE_TAG` names a different tree than the box holds,
  the release is refused (exit 2, no container started, no digest pinned)
  naming both tags, the env file and `./deploy/provision.sh up`; before, every
  one-off ran on the image the env file named and the release printed 7/7
  having migrated this tree's schema through that tree's code. An absent pin
  compares nothing — compose's own `:?` refuses that one.
  (`deploy/release.sh`, `deploy/tests/test_release.sh`.)
- **A console-declared login version passed the audit.** `zitadel_audit`
  did not read `loginVersion`, so a login-v2 declaration set by hand on the
  deployment's browser client — which sends every authorize to a host nobody
  configured — reported `agrees with every row` and the seed reported
  `exists`. The audit now judges the value on every OIDC client the seed
  owns, `zitadel_reconcile --kind applications` clears one the deployment did
  not declare, and the measurement kit checks the redirect for real.
  (`apps/accounts/management/commands/zitadel_audit.py`.)

---

### Migrating

- **A stored row under an old key is INERT from this release until you move
  it.** `resolve_renamed` keeps an old key ANSWERING at `require` time, so
  nothing breaks the day the rename lands; what it does not do is rewrite a
  tenant's own rows. A `Grant` or a `RolePermission` written under an old key
  stays under it, `check --deploy` reports it as a key naming nothing
  (`djb.W054`), and `manage.py rename_permission <old> <new>` is what moves it —
  across every tenant at once, refusing any pair the rename table does not
  declare and any successor outside the vocabulary. **The table, derived from
  `renamed_permissions()`:**

  | app | old key | new key |
  |---|---|---|
  | core | `membership.revoke` | `membership.delete` |
  | core | `organization.rename` | `organization.update` |
  | core | `tenant.configure` | `tenant.update` |
  | comms | `device.register` | `device.create` |
  | comms | `message_engagement.record` | `message_engagement.create` |
  | comms | `preference.set` | `channel_preference.update` |
  | comms | `suppression_surge.record` | `suppression_surge.create` |
  | events | `webhook_endpoint.create` | `endpoint.create` |
  | events | `webhook_endpoint.delete` | `endpoint.delete` |
  | events | `webhook_endpoint.read` | `endpoint.read` |
  | events | `webhook_endpoint.update` | `endpoint.update` |
  | exports | `export.request` | `export.create` |
  | files | `file_version.create` | `file.create` |
  | files | `file_version.delete` | `file.delete` |
  | files | `file_version.read` | `file.read` |
  | files | `file_version.update` | `file.update` |
  | files | `stored_file.create` | `file.create` |
  | files | `stored_file.delete` | `file.delete` |
  | files | `stored_file.read` | `file.read` |
  | files | `stored_file.update` | `file.update` |
  | usage | `usage.read_report` | `usage_entry.read` |
  | workflows | `workflow.signal` | `workflow_run.signal` |
  | workflows | `workflowrun.cancel` | `workflow_run.cancel` |
  | workflows | `workflowrun.read` | `workflow_run.read` |
  | workflows | `workflowrun.replay` | `workflow_run.replay` |

- **`core.0018_roles_are_keys` refuses a role value nothing declares.**
  `Membership.role` and `Invitation.role` lose their `choices` and become
  64-character keys, the three permission tables are created, and the
  migration censuses every row before it finishes: a value that is not
  `owner`, not a key an app declares in a `roles.py`, not a `core.Role` row the
  tenant owns, and not empty stops `migrate` naming the tenant, the value and
  the count. A product that added a fourth enum value **declares it in a
  `roles.py` first** — one file, no data — and then migrates. The refusal is
  the point: after this migration the column would accept the value and it
  would resolve to no permissions at all, which is a person silently losing
  every capability they had. Reversing drops the three tables and every
  custom role and grant with them.
- **`accounts.0009_ssodomain_verified_at` adds a nullable column and touches
  no row — which is the migration that changes behaviour.** Every existing
  claim is unverified afterwards and routes nobody; run
  `manage.py verify_sso_domain --tenant <slug> --domain <domain>` for each
  live claim, once. A product's own tests that build an `SsoConnection` and
  expect routing call `verify_sso_domain(...)` or use the platform's
  fixtures.
- **`manage.py check` now refuses a vocabulary it cannot derive** (`djb.E025`):
  two models claiming one `authz_kind`, an `authz_kind_of` naming a foreign key
  that is not `CASCADE`, one role key declared by two apps, a rename onto a key
  nothing declares, two roles marked as the default. These were 500s at the
  first `require()` before. Every one of them reports as a `(djb.E025)` line
  naming both parties, from plain `check`, `check --tag djb` and
  `check --deploy` alike — never as a traceback: every check in the pass that
  reads the vocabulary asks through one guard and goes quiet while the
  derivation is impossible, because Django's check registry is a set and no
  check can be registered "first".
- **`manage.py check --deploy` reports stored roles and permissions that name
  nothing** (`djb.W054`) — a warning per tenant and value, over memberships,
  pending invitations, grants and role deltas. It never stops a deploy.
- **After an issuer swap or a Zitadel re-seed**, `manage.py unlink_identity
  --all --yes --reason "<why>"` before anybody signs in again; a sign-in
  whose subject differs from the one on file is refused, never merged.
- **`is_staff` is granted, not inherited from `createsuperuser`**:
  `manage.py grant_staff --email <address>` for each person who needs
  `/admin/`. `scripts/setup.sh`'s closing guidance names that road
  (`zitadel_first_admin` before `seed`, then `grant_staff`); a password
  `createsuperuser` sets opens nothing, because no door here authenticates by
  password.
- **Two new environment slots, both optional**, documented in `.env.example`:
  `DJB_IDENTITY_SHAPE` (a test-suite declaration; leave it unset to run every
  identity test) and `SSO_REFUSED_MAIL_DOMAINS` (replaces the shipped list of
  consumer mail domains no tenant may claim). Neither is read in production
  paths beyond the claim's own validation.
- **Every hand-registered redirect URI on the template's browser client is
  cleared by the next `zitadel_seed`, `setup.sh` or `zitadel_reconcile`
  run.** Declare it through settings first. And an empty
  `GOOGLE_WORKSPACE_DOMAINS` beside a live Google provider deactivates that
  provider on the next sync — set the variable before you take the release if
  the provider is meant to stay.
- **Query budgets pinned over doors that resolve the tenant root may drop by
  one** (`quality/budgets.yaml`); `./scripts/rung_tidy.sh --budgets` applies
  the numbers the gate prints.
- **The image is built at the bank, once, from the banked tree**, after the
  row is written and the drive rows harvested, and pushed under the tree tag
  by the bank's acceptance box under its own role (`scripts/pm_push.sh --bank
  --on-boxes N`; the tag is single-architecture, the box's own); CI's `images`
  job now skips a tag already in the registry. The box role's registry grant
  is rendered and printed by `deploy/iam/verifier_bootstrap.sh` step 3b for a
  human to attach — until then the push is printed as refused and the verdict
  stands. `deploy/stage.sh`'s refusal names the bank's image step first.
- **The bank's second pytest pass moves to the acceptance box.** Each shard
  runs its group once (`--leg pytest-x2 --shard k/P --passes 1`; the `--leg`
  banner says `pytest-x2/1`), the acceptance box runs the whole suite twice
  under one seed and writes a proof, and the composed row carries it as
  `leak-proof=acceptance:<box> rc=0` — a one-pass row without a green proof
  is never honoured by the wall. The one-pass exemption is pinned to the
  pytest unit by name. The ADR gate-1 amendment is in `architecture.md`,
  marked proposed until signed.
- **`DJB_SIGN_IN_DOOR` unset is `hosted`, and `hosted` is byte-identical.**
  `/accounts/login/` serves the page it served, POST is still refused, the
  seed declares no login version, the invite link is the platform's, the
  sign-out sentence is unchanged, and the whole identity suite runs under the
  default with nothing skipped. `.env.example`, `deploy/env.staging.example`
  and `deploy/env.prod.example` carry the line commented.
- **Taking `ours` is a setting plus one seed run, and the seed is what
  declares.** `manage.py zitadel_seed` (or `./scripts/setup.sh`, which runs
  it) writes the login-v2 base URI on the browser client and the MCP clients
  and grants `IAM_LOGIN_CLIENT` to the machine credential; until it has run,
  the platform still sends people to its own page and the finalize is
  refused. `zitadel_audit` reports both facts from then on, and
  `zitadel_reconcile` repairs both. Flipping back to `hosted` and seeding once
  more clears the declaration — `None` is the clear, and the console is never
  needed.
- **`PUBLIC_BASE_URL` does four jobs under `ours`.** It is the base of the
  declared login URI, of the invite link, of the passkey relying-party id and
  of the CSP's admitted redirect origins. A value that is not the origin a
  browser reaches breaks all four the same way: the platform redirects to a
  host nobody serves, the mail links to it, the passkey affordance is withheld
  (an IP literal is not a relying-party id — `localhost` is the one name the
  specification exempts), and the browser declines the finalize's redirect
  while every server log shows it leaving.
- **`APPEND_SLASH` stays on.** The platform composes `{baseUri}/login` with no
  trailing slash and our route is `/accounts/login/`; Django's 301 is what
  carries the auth request into the door, and a deployment that turned the
  setting off would lose every OIDC sign-in and nothing else. A test pins it.
- **The CSP's redirect origins are derived, not typed.** Under `ours`
  `form-action` admits the origins of the redirect URIs `zitadel_seed`
  registers, read from the seed's own constants; a product that changed those
  constants or `PUBLIC_BASE_URL` changes the header with them. There is nothing
  to add to the settings, and a hand list beside it would be the drift the
  derivation exists to prevent.
- **Three settings ride with the door, defaults only.**
  `ZITADEL_SIGNIN_TIMEOUT` (one call), `ZITADEL_SIGNIN_DEADLINE` (the whole
  check) and `SIGNIN_THROTTLE_PER_MINUTE` (one address's tries before this
  product refuses without asking the platform) are read from the environment
  with their defaults in `config/settings/base.py`; a staging box behind a
  slow link raises the clocks there. They are not in the example env files. They ship commented at their defaults in `.env.example` and the two deploy example files.
- **The frames are restyled inside the token block, and the set is a
  census.** A product changes the look of every frame in
  `templates/account/base_entrance.html`'s one inline block, where the
  primitives live; the words are the frames' own files under
  `templates/account/frames/`. The legal frame names are the files in that
  directory and `apps/accounts/tests/test_entrance_frames.py` counts them —
  a product adding a frame extends that census in the same commit, and a
  product that declared `login_page=own` in `DJB_IDENTITY_SHAPE` skips the
  frame tests as before.
- **What appears on the factor step is the platform's decision, not a
  setting.** The chips are the enrolled kinds this deployment can deliver: an
  emailed code needs SMTP configured on the platform instance (the audit's
  SMTP section says whose it is, and a foreign sender is named on the face);
  a texted code needs a provider the platform has; *Not now* on enrolment
  appears only when the organisation's login settings allow a skip. There is
  no setting of ours for any of it.
- **`zitadel_first_admin` prints a different walk under `ours`.** Two steps —
  the link sets the password and signs the person in on the same page-load,
  then `bootstrap_tenant` — where `hosted` still prints three. A product's
  own runbook that copied the three-step text updates it or points at the
  command's output.
- **The invitation link's shape.** Under `ours` `invite_url` emits
  `<PUBLIC_BASE_URL>/accounts/login/?userID=…&code=…` — the platform's own
  parameter names on our page. A product test that pinned the hosted URL
  reads `invite_url` instead; the template's own tests already do.
- **A platform bump runs the kit.** After changing the pinned Zitadel image
  in `compose.yaml`, `manage.py zitadel_measure` against the new build; a
  `DIFFERS` line names the fact and the field that moved, a `could not` says
  what it could not look at, and the printed tally keeps the four counts
  apart so an unmeasured item is never read as agreement. It leaves one
  deactivated throwaway application per real run of the login-version check;
  nothing prunes it.
- **A frontend that consumed `refusals.ts` gains a socket-close state kind.**
  `SocketCloseState` and `SOCKET_CLOSE_COPY` are new members; nothing existing
  is renamed. The census test reads `apps/realtime/schemas.py` from the
  Python tree, so a product that trimmed the backend from its frontend
  checkout sees that one test unable to look.

---

- **The seventh frame is `link_expired`, and it has no form.** An OIDC
  hand-back whose auth request no longer exists renders it; a product that
  restyles the frames keeps the set at seven (`test_entrance_frames.py`'s
  census reads the directory).
- **The words are pinned against the design, with the divergences declared.**
  `test_every_frame_sentence_matches_the_design` compares every sentence the
  door can say and every frame's copy with the design's table; the nine
  deliberate divergences are a declared list a product edits knowingly.
- **Forgot your password? asks the platform to send its own mail.** Under
  `ours` the sign-in page's reset road takes an address, asks the identity
  platform once to mail its reset link, and says where that link lands (the
  platform's own page — a mail carries no application context, so the
  per-application login version cannot move it); a known and an unknown address
  read the same bytes and leave on the same clock.
- **ADR ident-12 records the session rule and its one exception.** Every session
  our door opens is closed at every exit — except a session a finalize answered
  with a callback, which the client spends afterwards on its own connection;
  the amendment is marked proposed until signed. Comments that cite
  "ident-10" for this rule are the domain-claim ADR's number and are a booked
  correction.
- **Zitadel facts the wave measured, written where they are read:** the
  enrolment confirm is `/totp/verify` (no underscore); the emailed sign-in code
  is eight digits and the app's six; the session create answers no `factors`
  block; a user read spells `isVerified` where a search row spells
  `isEmailVerified`; org-level policies travel on the query. The fakes carry the
  measured shapes, and `zitadel_measure` reports them.


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
   and the forked flag is not what the new gate script passes. A fork that
   keeps a refusal block reading a `LOOP_*` name this release no longer sets
   does not fail where it reads it — it fails minutes later at the pytest
   banner, under `set -u`, naming a variable nobody has heard of; `./scripts/check.sh
   --fast` carries a `loop-names` leg that answers it at the commit, and the
   same question by hand is one line: every `LOOP_*` name `scripts/check.sh`
   READS must be assigned by `scripts/check.sh`, `scripts/loop_tier.sh` or
   `scripts/gate_ledger.sh` — the three files a `--loop` sources into one
   shell — with defaulted reads (`${LOOP_X:-…}`) excluded, because those
   substitute rather than die.
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

[Unreleased]: ../../compare/v2.1.0...HEAD
[2.1.0]: ../../compare/v2.0.0...v2.1.0
[2.0.0]: ../../compare/v1.1.0...v2.0.0
[1.1.0]: ../../compare/v1.0.0...v1.1.0
[1.0.0]: ../../tree/v1.0.0
