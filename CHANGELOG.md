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
the trigger for building a `template_sync.sh` under `scripts/` is three products existing.

So an entry here answers one question — *would somebody who cloned this last
month want to pull this, and what would it change under them?* — and nothing
else. No counts of anything, no status: those go stale without this file
changing, which is the failure mode `CLAUDE.md` names.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html), where a
**major** is a change a product cannot take without editing its own code, a
**minor** adds something a product can ignore, and a **patch** fixes something
that was already meant to work. Where that reading and the owner disagree the
owner names the number, and did here: 2.1.1 is a patch by the owner's word —
the drawers below are additive and a product that wants none of them may merge
and ignore every one, but the release exists because the first real fold of
2.1.0 was not the thing it was meant to be, and the number says that rather
than advertising the drawers.

## [2.5.0] — A product built only on the SDK pays for none of the platform's tests and touches none of it — proven from zero

### SDK

- added: 518 names — quality/sdk_surface.json is the record

### Changed — the late landings of 2026-10-24, met by a product on its first day

- **`newapp` and every `scaffold` write regenerate the derived blocks** of `docs/product/architecture.md` (the app map) and print `wrote: … — commit it with the app`; a product's first commit passes the hook from zero — the proof from zero was red on the tree before this (`apps/core/scaffold/arms/_common.py`, `quality/docs_derived.py`).
- **The proof from zero runs nightly and at the release, not on every merge**: `publish.sh --release` dispatches the proof on the source commit — the proof clones `publish.sh --to`'s EXPORT of that commit (what a product clones), pulls the stack as CI's gate does (logged in to the one rationed mirror, ECR Public's, when the repository carries `AWS_ECR_ROLE_ARN`; anonymously otherwise, as a fork does — the road the clean-room drives prove from a real address), runs `setup.sh` twice, and its record (`proof-from-zero/3`) is keyed by the export tree the release consults by — and waits for a green record before anything is tagged; a source with no proof workflow, or a commit not on origin, is refused (`.github/workflows/proof-from-zero.yml` — the template's own workflow, which R14 trims from a product's clone — and `quality/djb/rituals/publish.py`).
- **CI measures once per PR and narrows what a diff reaches**: the PR-side consult honours a PR's own green run; the selftest and app-test units narrow by the diff's closure and print why, and fail closed when the map cannot vouch (`quality/djb/scope.py`, `quality/djb/ledger.py`); `scripts/ci_cost.py` prints the runner-minutes per merged PR, all-in.
- **The dispatch ledger is derived and landing is one command**: `scripts/ledger_derive.py` prints the dispatch table from briefs, reports and pull requests; `scripts/pm_land.sh <pr>` merges, reaps the worktree and its database, strikes and books the queue rows a report names (`quality/djb/rituals/land.py`, `scripts/queue_index.py --strike/--book`).

### Changed — the clean-room fixes of 2026-10-25: two developer drives and a DX survey, met before the tag was pushed

- **`setup.sh` reuses a running stack honestly** (#245): the one-shot organs are read from compose's `service_completed_successfully` edges in ONE `ps -a`; a refused image pull prints Docker's first line and the remedy (`docker logout <host>` for an expired stored login); the reuse line names the stack from compose's rendered `name:` and published ports, or is could-not-look — never `<unnamed>` as fact (`scripts/setup.sh`, `scripts/ci_stack.sh::compose_once_members`).
- **A fresh clone of the release commits** (#248): the derived ledger's hook step prints "no cycle yet" and exits 0 on a tree with no `docs/product/reports/` (`scripts/ledger_derive.py`).
- **CI's narrowing never reaches a spawned gate** (#247, #248): `quality/djb/env.py::STEERS` is the one list of steering names — the test harness strips them before every test, the proof's child environment derives from it, and the drive preamble's shell copy is held equal to it by a test (`quality/tests/fixtures/env_strip.py`, `quality/djb/rituals/proof_from_zero.py`, `scripts/tests/drive_preamble.sh`); the gate itself reads the narrowing PLAN it was handed, never the steering names.
- **`build_server()` refuses an MCP tool that would answer without a structured result** (#248): a tool whose return type is a class of this tree with no output schema is refused at boot by name, so the door's `structuredContent` no longer depends on import order (`apps/core/mcp.py::refuse_unstructured_results`, called from `config/mcp.py`).
- **The proof from zero proves the export, not the source** (#249): the proof line above; records before `proof-from-zero/3` are counted and never honoured.
- **Twelve day-one refusals say the tool's own cause** (#251): the README's Quickstart declares before it tests, and an undeclared clone's `quality/tests` refuses in one line naming `declare` (`apps/testing/template_only.py`); the frozen-lockfile leg tells pnpm's lockfile-drift family from a fetch failure and prints pnpm's line (`scripts/fe_gate.sh`); `tool_said` and its shell twin `gate_tool_said` quote the tool's last lines under every could-not-look of the first day — `setup.sh`'s sign-in door, the drive doors, `declare`, the gate legs, five `git ls-files` sites (`quality/could_not_look.py`, `scripts/gate_refuse.sh`); `provision.sh up` never starts the compose-run door; `teardown.sh` stops with AWS's line on a probe it cannot read instead of skipping a deletion; **`publish.sh --release` on a product tree is refused once, at the top**, naming the template's ritual and the product's road `deploy/release.sh` (`quality/djb/rituals/publish.py`); shipped pages say whose path a trimmed citation names.

### Fixed before the tag — the third clean-room drive and its code review, 2026-10-26

- **`scaffold child` lands a two-word child** (#255): the child golden's prose (docstrings, strings, comments) says the child in words, so `GerminationTest` is titled `Record a ledger germination test` while its names stay `germination_test`. Every additive shape also refuses before any write when a route it adds would carry a title house rule 41 refuses (`apps/core/scaffold/arms/child.py::prose_held`, `apps/core/scaffold/arms/_common.py::refuse_titles`).
- **`feature.sh` is green only when the checkout is migrated and the app's own tests pass** (#255): the road is makemigrations · tidy · `--fast` · `migrate --noinput` · `test.sh apps/<app>` (the loop runs the tests itself), and a `green:` line before `next:` says what green vouches for; the one-path steps 5–6 say the same (`quality/djb/rituals/feature.py`).
- **Rule 16 knows the irregular pasts, and the scaffold conjugates through the same table** (#255): one lexicon, `quality/engine/lexicon.py::IRREGULAR_PAST`, read by rule 16 and by the `verb`/`event` shapes, so `lend` writes `lent`; rule 16 admits every tabled form and refuses an `-ed` spelling of a tabled verb (`lended` → "its past is `lent`"), with a canary and a negative (`quality/checks/rule_16.py`, `apps/core/scaffold/arms/_common.py::past_tense`).
- **`scaffold verb` adopts the line `scaffold event` wrote** (#255): after an `event` of the same verb, `verb` takes that exact `events.py` line (`adopted:`) instead of refusing it, and refuses only the same string under another constant; `--list` and `shapes.md` say `event` writes `events.py` alone (`apps/core/scaffold/arms/verb.py::adopts_event`).
- **The workflow shape copies the door that ends its wait** (#255): the approve service, `POST /{id}/approve/` with its route, the MCP twin `approve_<noun>`, the `<noun>.approve` policy lines and the approval tests are fenced `workflow onboard`, so a scaffolded approval wait is signalled from a door; a copy's approve bar is an administrator at the row's node (`may_archive`), and `drive_doors.sh` presses `<noun>-approve` over REST and the run ends approved (`apps/example/services.py`, `apps/core/scaffold/arms/workflow.py::APPROVE_REWRITES`).
- **Every flag a scaffold ARM reads is on its page** (#255): a census holds each scaffold arm's parser flags to its shape's listed grammar; it found `verb … --transition <from>-><to>` and `workflow … --before <d>`, both now listed in `--list`, `shapes.md` and the developer's hand (`apps/core/scaffold/shapes.py`, `apps/core/tests/test_scaffold.py::test_every_flag_an_arm_reads_is_in_its_shapes_listed_arguments`). The top-level `scaffold` command's own flags (`--role`, `--permissions`, `--families`, read for `surface` and `role`) are not yet censused and are on no page — booked for 2.5.1.

### Changed — rules 91 and 98 say what they are: ratchets over recorded debt

- **Rules 91 (`a-comment-is-the-contract-line`) and 98 (`the-harness-fits-its-budget`) are ratchets over the debt the template shipped with, and the explain reader now says so in their own figures** — "a ratchet over recorded debt: <N> lines across <m> members, down-only since <sha>; a standard for NEW files", summed from the floors (`debt:` on the rule). They bind a new file in full: a file of a recorded member that `quality/ratchet_population.yaml` does not list is judged at zero, and `newapp` and `scaffold` record no rule-91 floor for what they write — a new tail is a line to delete. The recorded debt falls by a step every release: `./scripts/publish.sh --release` refuses a release whose summed floors did not fall from the previous release's line below — by max(5 % of the remaining sum, 2,000 lines) for a minor, by one line for a patch — and the line below is the first baseline. A minor also ships only after the five-lens critique re-read of its own export (`.claude/skills/product-manager/references/critique-brief.md`); a patch is advised. **At the merge:** nothing to do — a product app whose rule-91 floor it recorded itself is judged as a whole, as before.

ratchet-debt: 91=71538 98=3090

### Added — the measured envelope

- **The acceptable tier, measured:** the ship line is `docs/runbooks/capacity.md` § 9's entry dated 2026-10-23 at sha `60b4bc6c820c` (the production shape: one ladder, the 2-hour soak at half its knee, the 50-socket run under that load and idle); `scripts/envelope.sh <sha>` is the road that takes it.

### Added — the bank's bodies in Python

- **`DJB_BANK_CHECKOUT`** names the checkout whose `quality.djb.box.bank` `pm_push.sh`'s 26 `bank_boxes_*` wrapper lines run (then `$ROOT`, then `$PWD`); a product never sets it — a drive that copies `pm_push.sh` out of the checkout does.

### Added — the operator's list of domain claims that route nobody

- **`manage.py sso_domains --unverified`** lists every tenant's email-domain
  claim no operator has verified, each with the `manage.py verify_sso_domain
  --tenant <slug> --domain <domain>` line that makes it route. The operator
  step at the merge: a deployment whose claims predate
  `accounts.0009_ssodomain_verified_at` (ADR ident-10) runs it once and
  verifies each live claim; until then those claims route nobody — fail
  closed, by the owner's ruling of 2026-10-21. Read-only; no audit row.

### Changed — the gate, the box client and the rituals are Python; the valve grammar's verdicts

- **The gate is Python.** `./scripts/check.sh` is a shim onto `python -m
  quality.djb gate`; every mode, flag, refusal and exit status is the
  package's (`quality/djb/`), the spellings unchanged. A checkout with no
  `.venv` is exit 2, except `--list-legs`, which runs on any `python3`.
- **The verifier-box client is a package.** `scripts/verifier_box.sh` and
  `scripts/verify_start.sh` are shims onto `quality/djb/box/` and
  `quality/djb/rituals/verify_start.py`; subcommands and flags unchanged.
- **The PM rituals are Python.** `pm_merge.sh`, `pm_push.sh`, `pm_fold.sh`,
  `pm_main_loop.sh`, `publish.sh`, `rung_tidy.sh` and `divergence_census.sh`
  are shims onto `quality.djb.rituals.<module>`. A product drive that sourced
  one of them for a function calls the module instead.
- **A dated valve is enforced.** A valve whose reason ends `— until
  <YYYY-MM-DD>` past today is exit 2 naming its line; a future date prints
  its own `until <date>` line under the standing section's `dated:` count; a
  valve whose reason names a plan coordinate is a violation naming the id. A
  valve whose trigger is a sentence is unchanged.
- **The prose bound.** `quality/rules.yaml` `prose: prose_over_code:` records
  prose lines over code lines, in thousandths, for `scripts/`, `quality/djb/`,
  `quality/tests/` and `deploy/`; every plain engine run prints them with the
  worst three files per root, and a root past its number is a violation with
  the line to paste. A product's `local/` drawers are not measured.
- **Rule 84's `exit2_helper` is held, not zero,** at its survivors in the
  shell bootstrap family, declared with its trigger (2.6).

### Changed — one audit row per door call, the core tool names, the ceiling's words

- **One `AuditEntry` per door call (ADR core-29).** `emit`, `record_event`,
  `enqueue_dispatch` and `record_run` are `@service(witness=False)`: under a
  service that writes a row they write none, so one archive over REST is one
  row, not five. Called straight from a door they still write theirs. A
  product's own service takes `witness=False` only for the same shape.
- **Three core MCP tools take their derived names** (ADR api-2):
  `set_flags` → `update_flags`, `set_grant` → `update_grant`,
  `set_role_permissions` → `update_role_permissions`. An MCP client calling the
  old names is refused; rename the call.
- **The hand-out wall names keys, not ranks.** "your own effective role there
  is …" is gone: a refused grant or take-back names the sentences of the keys
  the actor is short of, and the route documentation speaks keys at a node.
- **A workflow is handed the retry floor in its argument.** The reader is
  `apps.core.retry.retry_floor_seconds` (was `apps.workflows.client`); no
  workflow module reads settings. A product workflow built on a settings read
  through `imports_passed_through` moves the number into its argument.
- **Moved:** the Temporal header names to `apps.core.headers`; the test fake
  `FakeScheduleServer` to `apps.core.tests.fakes`; the socket bearer header to
  `apps.core.tests.wire.socket_bearer`. The re-exports at
  `apps.workflows.determinism` and `apps.workflows.context.current_actor` are
  deleted — import `apps.core.determinism` and `apps.core.context`.
- **Added:** the tenant admin's suspend, resume and close actions.
- **djb_imports: `purge_imports` takes the one purge signature** (ADR core-22): `(*, before, tenant: None) -> Swept`, no `actor`; its audit row is the system's, as every other sweep's is. A caller passing `actor=` drops it.
- **connections: three route descriptions say what the code does.** On
  `GET /connections/`, `GET /connections/{id}/` and
  `POST /connections/{id}/credentials/`, `last_error` is the reason given at
  revocation, not a provider's error, and `status` is `connected` or
  `revoked`. `error` is still a reserved `status` value, and nothing sets it.
  No field or status code changed.
- **comms: a Twilio status callback on a `{tenant}` staff host** is built
  with the connection's tenant. Before this it raised `ValueError`.
- **Eleven reads take rule 16's names** (no route, tool, schema or event
  moves). Selectors: `accounts.selectors.realm_for_email` →
  `get_realm_for_email`, `sso_enforced_for` → `get_enforcing_connection_for`,
  `workforce_domains` → `get_workforce_domains`; `events.selectors.endpoints_for`
  → `list_endpoints_for`, `dead_lettered` → `list_dead_letters`,
  `outbox_to_replay` → `list_outbox_to_replay`, `undispatched` →
  `list_undispatched_outbox`; `search.selectors.search` → `get_search_page`.
  Moved: `accounts.selectors.is_workforce_email` → `accounts.policies`;
  `accounts.services.tenants_this_user_alone_owns` →
  `accounts.selectors.list_tenants_this_user_alone_owns`;
  `core.services.pending_invitations_for` →
  `core.selectors.list_pending_invitations_for`. A product importing the old
  name renames the import.
- **accounts: a connection's sign-in link on a `{tenant}` staff host** is
  built with the connection's tenant (`get_platform_login_url` takes
  `tenant=`). Before this it raised `ValueError`. **The identity home's event
  refuses in production with no event bus registered** (`BridgeNotRegistered`),
  as core's own events do, instead of logging that it went unpublished.
- **The test world gains its clerk.** `apps.core.tests.permissions_world.build_world()`
  now carries `clerk` (a `member` at A and nowhere else) and `World.user(who)`;
  a product test counting the world's memberships or a role's holders counts one
  more. `BranchWorld` and `build_branch_world` are aliases of `World` and
  `build_world` for this release; import the plain names.

### What a product on the direct Google road does at the merge

**The direct-allauth Google provider is removed; the workforce's Google is an
identity provider inside Zitadel, and the domain wall is the platform door's.**
A product whose login page shows a "Continue with Google" button beside
Zitadel's today — `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` and
`GOOGLE_WORKSPACE_DOMAINS` set — loses that button at the merge. Its staff
keep signing in through Google by materialising the same three values as a
Google IdP inside Zitadel FIRST, so the button moves onto Zitadel's hosted
page before the direct one goes. And one rule changes for everybody: **the
platform door mints a new person only at a workforce domain or on an
invitation** — an empty `GOOGLE_WORKSPACE_DOMAINS` admits no stranger at all.

**The consumer's own order, as they gave it**: *staging
reconcile → a walker-proven Google sign-in → production → the fold; their
owner approves the identity change first.*

**The template's steps, on each environment — two before the fold, one after:**

1. **Reconcile the provider.** With the three `GOOGLE_*` values set and the
   worker up, run `uv run python manage.py zitadel_reconcile` (or the
   workforce door alone: `uv run python manage.py sync_workforce_idp`). It
   asks `SyncIdentityConfigWorkflow` for the workforce provider; the worker's
   activity creates an org-level Google IdP named `Workforce Google` in
   Zitadel, idempotently. Then `uv run python manage.py zitadel_audit` must
   print the green shape:

   ```
   agrees      workforce — idp <id>, domains <your domains> (enforced by this deployment's sign-in door at sign-up, not in Zitadel — ADR ident-6)
   ```

   Observably: Zitadel's hosted login page now offers Google beside the
   username and password; the direct button on this deployment's own page is
   still there. Nothing on this side has changed.
2. **Take the release.** The direct button goes; one door remains. A person
   who signed in by the direct road signs in through Zitadel's Google button
   and is **joined, not duplicated**: their row holds no Zitadel subject yet,
   so the door's existing rule — the subject resolves the person, the address
   only introduces one, and only while nothing already speaks for either —
   links the Zitadel subject to the account at their verified address. Their
   memberships, roles and history are the same row's.

3. **Retire the direct road's links, after a staff sign-in through Zitadel's
   Google button is proven.** Every person the direct road created still holds
   an allauth `SocialAccount(provider="google")`. With the provider no longer
   installed, each is **a row no provider serves**: it signs nobody in, the
   connections page under `/accounts/3rdparty/` leaves it out without saying
   so, and any code that asks it for its provider account
   (`SocialAccount.get_provider_account()`) gets an error. Printing one still
   works — `str()` of the row is the person's address.
   Run `uv run python manage.py retire_direct_google_links --dry-run`, then
   without `--dry-run`. It deletes the `google` rows only when EVERY holder
   already carries a Zitadel identity. Otherwise it exits 2 naming the people
   who have not signed in through Zitadel yet, and deletes nothing: each of
   them signs in once, and you run it again. Green shape:

   ```
   retired      <n> direct Google link(s)
   ```

**Why the order.** Merge first and reconcile second, and nothing is lost — but
the deployment has a login page with no Google door for the minutes between.
Retire before everybody has crossed, and the command refuses rather than guess.

**Two things to know after the fold.** A person the direct road created is a
`User` row and keeps signing in; a NEW person from outside the workspace
domains, with no invitation and no customer's claimed domain, is refused at
sign-up with *"That account is not part of this organisation"* and writes no
row (`accounts.platform.refused reason=domain_not_allowed`). **A disabled
customer connection counts as no connection**: it resolves nothing, so a NEW
person from that customer's domain meets the same wall and is refused, and
nothing is written — where before they landed as an account with no
membership. People who already have an account still sign in. And the release
deletes no identity row of yours: the direct road's `SocialAccount` rows stay
until step three removes them.

### What a product does at the merge

Each part below is read from the tree it names. **The base the census reads**
is first, because every step after it compares against that base. **The fold
map** is how a product reads what its rule numbers became. **The roads** are
the one new collision class and the one new ratchet. **The modified seam** is
the step per file class for a template-owned file both sides changed. **Your
own drives** meet a sentinel that is now on. **The member floors** of the
comment rules move into each app. **The old schedules** are one operator
paragraph for a long-lived deployment. What one app's merge asks — the
realm re-seed, the direct Google road, the platform schemas' new names — is
under that app in **What a client and a product see, by app**. The road
assumes a product already on 2.2.x or later, whose divergences are named
`divergence:` lines the divergence census reads.

#### The base the census reads

The collision census and the clone a verifier makes both compare your tree
against the release you merged, and a product's CI checkout and a box push
carry no `template` remote. So the fold step WRITES the drawer
`scripts/local/template-base` — one line, the release's commit sha — and
commits it; it is the one base declaration that survives a clone, a CI
checkout and a box push. **The drawer holds the release's commit sha (the
tag's commit), never the tag name**, because the tag is not fetchable by a
product's CI or clones and not pushable past the product's own wall. Read the
sha where the tag is fetched — a laptop with the `template` remote, after
`git fetch template --tags` — with `git rev-parse '<tag>^{commit}'`, then
commit the drawer. Typed where the tag does not resolve, `git rev-parse`
echoes its own argument, and a redirect puts that unresolved string in the
drawer, which the census then refuses as a base. Two lines of CI a product
owns meet the same release:

- **The identity shape is declared in the tracked drawer**: `declare` writes
  `identity_shape: platform_apps=own` into `quality/local/rules.yaml` the day
  the product has an app of its own under `apps/`, and the census reads the
  drawer when `DJB_IDENTITY_SHAPE` is unset — so a product's CI needs nothing
  set (the ignored `.env` line alone never reached CI; IDENT-1, DF-62).
- **A product whose derive drive predates the walls must hand
  `DJB_MEMBER_WALLS_OUT` to the legs block**, or every legs case fails at the
  block's `mkdir` before the gate runs (`.github/workflows/ci.yml` names it
  under `runner.temp`; supply it in the drive beside `GITHUB_OUTPUT`, outside
  the scratch checkout).

#### The fold map

Run it with BOTH files, every time. Its one-argument form refuses at exit 2,
correctly and at length, because it cannot tell which side is the release's;
a fold note that says only "run the fold map" lands on that refusal. The
FIRST file is your product's own rules before the merge — the previous rules
are yours, not the tag's — and the second is the release's. Before the merge,
from the product's checkout, with the tag fetched:

```sh
git show HEAD:quality/rules.yaml > /tmp/prev-rules.yaml
git show v2.5.0:quality/rules.yaml > /tmp/next-rules.yaml
uv run python -m quality.gate --fold-map /tmp/prev-rules.yaml /tmp/next-rules.yaml
```

`HEAD` is your pre-merge commit, so the map sees every rule of yours. Only a
product with no rules of its own may take the tag it is on in that first line
(`git show v2.4.1:quality/rules.yaml`), because there the two files are one
and the map has nothing of yours to place. It prints one line per rule, matched by name and never by
number, and exits 0 with the map or 2 could-not-look. Skip it and a rule of
yours that shares a number with a template rule is read as the template's.

#### The roads

A **road** is the one mechanism that does a job this platform does exactly
one way; each carries a marker where it lives, and `manage.py roads` reads
them off the tree.

1. **Before the merge, the collision census reads roads too.** Take the census
   and its classifier from the tag, as [2.4.1]'s rename road says, and run
   `./scripts/divergence_census.sh --against <tag>`. A marker of yours naming
   a job a release road marks is a `collision: road <job>` line naming both
   files, exit 2, with the remedy under it: adopt the platform's road (call
   it, and delete yours), or keep yours and DECLARE it with a comment line
   directly above your marker, `rule-84` followed by a colon and why your
   road stays. A declared one prints `kept:` beside the release's and is not
   counted. `./scripts/divergence_census.sh --roads` prints your checkout's
   own markers, one line each. Skip it and the merged tree fails house rule
   84 at your first gate, naming both roads.
2. **After the merge, read the door.** `uv run python manage.py roads` prints
   every job with its road, its contract and a worked example, the platform's
   and yours in two partitions; `roads <job>` prints one, and
   `roads --json` is the `roads/1` document a brief cites. Step zero writes
   it to `.rung/roads.json` in every rung worktree.
3. **Record your own copies once.** Rule 84 also counts, by shape, the copies
   no marker names — private helpers defined in two apps, shell functions that
   print a could-not-look banner and exit 2 outside the one refusal seam,
   discovery walks, hand-typed reason floors. Your first gate prints, per
   class over the template's recorded number, the line to paste into
   `quality/local/rules.yaml` under `ratchets:` and `"84":`, stamped
   `recorded-at <sha> [fold]`. Paste it as printed; the number is added to the
   template's and moves down only. Skip it and every gate is red on a backlog
   that was already yours.

#### The modified seam

The files a release MODIFIES that your product also changed are where every
hand conflict of a fold lands. The rule, per path: a template-owned file with
no `divergence:` line is yours to take whole from the tag
(`git checkout <tag> -- <path>`); a file WITH one takes its side by class.

1. **The gate and its rituals take the tag's side, then re-apply your named
   divergences** — the rule blocks of `quality/rules.yaml`, `quality/checks/`,
   `scripts/check.sh`, `scripts/gate_ledger.sh`, `scripts/pm_push.sh`,
   `.github/workflows/ci.yml`, `.github/workflows/nightly-proof.yml`,
   `quality/tests/test_ci_derive.py` and `deploy/release.sh`. Take the file
   whole, then apply each named hunk from `git diff <tag you were on>
   ORIG_HEAD -- <path>` by hand. A hunk-by-hunk merge of a file this long is
   how a fold carried `gate_ledger.sh`'s CI-verdict section twice, the later
   copy reading a different record format. Your own rules, checks, legs, drives
   and CI steps belong in the drawers (`docs/product/build-contract.md`, the
   `drawers` block), which a fold never touches. Then run the fold map above.
2. **A template service or its test under `apps/` takes the REVERSE: keep
   your side, apply the tag's hunks** — `git diff <tag you were on> <tag> --
   <path>` through `git apply --3way`, or by hand for a short hunk. A
   whole-file take of a template service drops the guard your product added
   to it: the measured instance is a product's system-only guard on
   `archive_emptied_file` in `apps/files/services.py`, gone after a
   whole-file take, with nothing red. Then read `git diff <tag> -- <path>`:
   it must show exactly your named hunks. An empty diff on a path you named
   is a divergence the merge lost.
3. **Prove it.** `./scripts/divergence_census.sh` (no `--against`) exit 0 —
   every divergence still named — and `./scripts/check.sh --loop` exit 0.

#### Your own drives

The drive preamble's finished-sentinel is now on by default: a product drive
in `scripts/local/drives/` that sources `scripts/tests/drive_preamble.sh` and
exits 0 without calling `drive_finished` — green until now — exits 2
(`DIED BEFORE REPORTING`) on any bash. The remedy is one line,
`drive_finished`, immediately after the drive's summary line (or
`DRIVE_OPTED_IN_TO_FINISH=0` after the source line, with a comment saying
why).

#### The member floors: rule 91

House rule 91 counts comment lines past the contract line in four classes per
member (`docstring-tail`, `module-tail`, `block-tail`, `narrative`), recorded
at the measured count and down-only. The per-member floors of rules 86–89 and
91 now live with the member: a template app's in its `AppConfig.ratchet_floors`
(keyed `"<rule>.<class>"`), the platform's other members' in
`quality/ratchet_floors.yaml`; `quality/rules.yaml` keeps no member number. A
product app's finding in one of these classes prints the line to paste into
ITS OWN `apps.py`, never into a drawer; a drawer row for an app class on these
rules is refused with the same line.

#### The old schedules: a long-lived deployment deletes eleven ids by hand, once

Every platform sweep and reconcile is now declared through
`apps.core.schedules` (`platform_schedule`, `daily_purge`), under house rule
18's `platform:` shape, one id for the schedule and the run it starts. The old
ids are keyed by the task queue, so they cannot be `legacy_ids` constants and
the worker does not remove them: **a deployment whose worker ran an earlier
release deletes each old schedule once** — in the Temporal UI, or
`temporal schedule delete --schedule-id <old id>` — or both schedules run and
each sweep or probe runs twice. A fresh deployment has nothing to do. Old →
new, per app (`<queue>` is the deployment's task queue):

| App | Old id | New id |
|---|---|---|
| `connections` | `connections-purge-inbound-webhooks:<queue>` | `platform:connections:purge:<queue>` |
| `core` | `system:core:integrations:<queue>` | `platform:core:integrations:<queue>` |
| `djb_imports` | `imports-purge-expired:<queue>` | `platform:djb_imports:purge:<queue>` |
| `events` | `events-purge-expired:<queue>` | `platform:events:purge:<queue>` |
| `events` | `events-reconcile-outbox:<queue>` | `platform:events:reconcile:<queue>` |
| `exports` | `exports-purge-expired:<queue>` | `platform:exports:purge:<queue>` |
| `files` | `files-sweep-pending-uploads:<queue>` | `platform:files:sweep-pending:<queue>` |
| `search` | `system:search:reconcile:<queue>` | `platform:search:reconcile:<queue>` (the run it starts kept its `platform:` id) |
| `workflows` | `workflows-reconcile-runs:<queue>` | `platform:workflows:reconcile:<queue>` |
| `workflows` | `workflows-purge-finished-runs:<queue>` | `platform:workflows:purge-runs:<queue>` |
| `workflows` | `workflows-purge-expired-sessions:<queue>` | `platform:workflows:purge-sessions:<queue>` |

### What a client and a product see, by app

Apps in the platform partition's order (`quality/partition.yaml`). One change
reaches every app with a door, and it is said once here:

- **A request that resolved no tenant (or no acting organisation) is
  `403 no_acting_scope`**, with the registry's remedies, on every route and
  MCP tool of `connections`, `djb_imports`, `djb_notes`, `djb_tags`, `events`
  (webhook endpoints, deliveries, dead letters), `example`, `example_portal`,
  `exports`, `files`, `search`, `usage` and `workflows` (the run ledger). It
  was a bare `403 forbidden` with a sentence — or, on some reads, an empty
  answer; the per-app lines below name those. Every route that publishes its
  refusal set now lists `no_acting_scope`.

#### `accounts`

- **`zitadel_first_admin` prints staff-surface links** — its three links are
  built by `absolute_url(…, surface=STAFF)`. They differ from before only
  where `staff` is bound to a host other than the public base URL's.
- **The identity declarations and the MCP door's resource URLs read
  `core.surfaces.surface_base_urls()[0]`** — the value they read before, on
  every surface shape; nothing declared to the identity platform moves.
- **Operator refusal messages say "the deployment's public base URL"** where
  they named the setting — rule 84 counts the name in prose.
- **`RealmOut`'s published description lost a planning coordinate** (the
  document and the client moved by that one line).
- **Four membership reads go through the fail-closed manager**
  (`for_tenant(t)` / `.of(user)`); every answer is the same row set.

##### The direct Google road is retired: what a product on it does at the merge

**The direct-allauth Google provider is removed; the workforce's Google is an
identity provider inside Zitadel, and the domain wall is the platform door's.**
A product whose login page shows a "Continue with Google" button beside
Zitadel's today — `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` and
`GOOGLE_WORKSPACE_DOMAINS` set — loses that button at the merge. Its staff
keep signing in through Google by materialising the same three values as a
Google IdP inside Zitadel FIRST, so the button moves onto Zitadel's hosted
page before the direct one goes. And one rule changes for everybody: **the
platform door mints a new person only at a workforce domain or on an
invitation** — an empty `GOOGLE_WORKSPACE_DOMAINS` admits no stranger at all.

**The consumer's own order, as they gave it**: *staging
reconcile → a walker-proven Google sign-in → production → the fold; their
owner approves the identity change first.*

**The template's steps, on each environment — two before the fold, one after:**

1. **Reconcile the provider.** With the three `GOOGLE_*` values set and the
   worker up, run `uv run python manage.py zitadel_reconcile` (or the
   workforce door alone: `uv run python manage.py sync_workforce_idp`). It
   asks `SyncIdentityConfigWorkflow` for the workforce provider; the worker's
   activity creates an org-level Google IdP named `Workforce Google` in
   Zitadel, idempotently. Then `uv run python manage.py zitadel_audit` must
   print the green shape:

   ```
   agrees      workforce — idp <id>, domains <your domains> (enforced by this deployment's sign-in door at sign-up, not in Zitadel — ADR ident-6)
   ```

   Observably: Zitadel's hosted login page now offers Google beside the
   username and password; the direct button on this deployment's own page is
   still there. Nothing on this side has changed.
2. **Take the release.** The direct button goes; one door remains. A person
   who signed in by the direct road signs in through Zitadel's Google button
   and is **joined, not duplicated**: their row holds no Zitadel subject yet,
   so the door's existing rule — the subject resolves the person, the address
   only introduces one, and only while nothing already speaks for either —
   links the Zitadel subject to the account at their verified address. Their
   memberships, roles and history are the same row's.

3. **Retire the direct road's links, after a staff sign-in through Zitadel's
   Google button is proven.** Every person the direct road created still holds
   an allauth `SocialAccount(provider="google")`. With the provider no longer
   installed, each is **a row no provider serves**: it signs nobody in, the
   connections page under `/accounts/3rdparty/` leaves it out without saying
   so, and any code that asks it for its provider account
   (`SocialAccount.get_provider_account()`) gets an error. Printing one still
   works — `str()` of the row is the person's address.
   Run `uv run python manage.py retire_direct_google_links --dry-run`, then
   without `--dry-run`. It deletes the `google` rows only when EVERY holder
   already carries a Zitadel identity. Otherwise it exits 2 naming the people
   who have not signed in through Zitadel yet, and deletes nothing: each of
   them signs in once, and you run it again. Green shape:

   ```
   retired      <n> direct Google link(s)
   ```

**Why the order.** Merge first and reconcile second, and nothing is lost — but
the deployment has a login page with no Google door for the minutes between.
Retire before everybody has crossed, and the command refuses rather than guess.

**Two things to know after the fold.** A person the direct road created is a
`User` row and keeps signing in; a NEW person from outside the workspace
domains, with no invitation and no customer's claimed domain, is refused at
sign-up with *"That account is not part of this organisation"* and writes no
row (`accounts.platform.refused reason=domain_not_allowed`). **A disabled
customer connection counts as no connection**: it resolves nothing, so a NEW
person from that customer's domain meets the same wall and is refused, and
nothing is written — where before they landed as an account with no
membership. People who already have an account still sign in. And the release
deletes no identity row of yours: the direct road's `SocialAccount` rows stay
until step three removes them.

##### Every tenant gets a realm of its own: the re-seed

Each tenant now signs in at its own realm, an organisation at the identity
platform. The realm is made when the tenant is created, the platform's
project is granted to it, and it carries its own login policy. The
deployment's existing organisation stays the **staff realm**. There is no
migration road. A deployment with no production users takes the release and
runs three commands, in this order:

```sh
uv run python manage.py migrate
uv run python manage.py zitadel_seed
uv run python manage.py zitadel_reconcile
```

- **`migrate`** takes the `accounts` leaf. `0011` moves every
  `User.zitadel_sub` into the identity join as a staff-realm row, and its
  reverse writes them back. The column stays until a later release drops it.
  **`0012` is a no-op forward on a database that never rolled back**; it
  matters only to a rollback: its reverse records a tenant-realm person's realm
  and tenant in `User.zitadel_sub`, so a round trip to `0010` and back keeps
  them in their realm. A `staff` row a rollback through `0011` alone left
  beside a realm row is retired by `zitadel_reconcile`, printed.
- **`zitadel_seed`** records the staff realm and turns the project check on,
  so a realm the project was not granted to cannot sign in. It asserts
  `IAM_OWNER` on the credential, and registers a browser callback for every
  surface in `SURFACE_HOSTS`.
- **`zitadel_reconcile`** homes every tenant that has no realm, through the
  same run `create_tenant` starts. `manage.py zitadel_audit` then prints
  `n of n tenants homed` on its orgs line, both numbers counted from your
  own tenants.

Who sees it:

- **A connection with `enforced` on.** `enforced` is now the tenant realm's
  login policy: the password is off and the provider is required.
  `SsoConnectionOut.enforced` reads `true` only once that policy has landed,
  and `sync_state` sits beside it. Switching `enforced` on before the
  connection's provider has reached the identity platform is refused with
  `409 enforced_without_provider`.
- **Code that read `User.zitadel_sub`** reads the identity join instead:
  `SsoIdentity` rows with no connection, one per realm a person holds a
  subject in. The one writer is `services.record_identity`, which replaces
  `record_zitadel_identity`.
- **Code that read the `created` flag of an identity result.**
  `IdentityConfigApplied.created`, `InvitedIdentity.created` and
  `InvitedPersonProvisioned.created` are gone: the realm port's answers never
  say whether a call made a thing or found it, so each read `false` on a
  thing just made — a value that is always false is a lie on the wire. A
  product that needs "was it created" reads it at the activity, where the
  identity client's own `Resource.created` (`apps/accounts/zitadel.py`) is in
  hand, and logs it there.
- **An invitation's set-your-password link follows the sign-in door.** Under
  `SIGN_IN_DOOR=ours` it is the surface's own entrance, on the host of the
  surface the invited role belongs to — a customer's mail lands on the
  customer host. Under `hosted`, the default, it is Zitadel's own page on
  Zitadel's host, carrying Zitadel's `userID` and `code` and nothing of ours;
  the person's realm is read when they sign in.
- **The identity-home drive needs Zitadel and Mailpit.**
  `quality/tests/test_identity_home.py` drives a real worker, a real Zitadel
  and a second host, so the self-test unit's needs carry `zitadel,mailpit`
  and CI starts both for that unit. A product's own CI that lists the
  template's units takes the line as it is; one that pins its own services
  starts the two beside them, or the drive reads could-not-look.

#### `comms`

- **No `comms.message.*` event carries `recipient_email`, and no
  `comms.recipient.*` event carries `email`, `display_name`, `phone` or
  `chat_handle`** — `MessageOut` and `RecipientOut` mark them `personal`: the
  message events name the contact by `recipient_id`, `archived`/`restored` carry
  `id`, `user_id`, `organization_id`, `created_at` and the archive pair; the
  doors still answer every field. No `v` moves; a replay of a row stored before
  this still carries them.
- **`GET /messages/{id}/engagement/` publishes its `400 invalid`** — the
  refusal the route always answered and the document never listed.
- **The SMS status callback URL is built on the `staff` surface's host**
  through `absolute_url`, where it read the public base URL by hand. With
  `staff` bound to another host, a message sent before the deploy fails its
  callback signature after it (fail-closed; in-flight messages only).
- **Eleven keys (`device.create`, `device.retire` among them) are declared to
  `member`** in `apps/comms/policies.py`'s `DEFAULT_ROLES`. Every `allows`
  answer is unchanged; what moves is under `core` below.

- **`GET /api/v1/recipients/` refuses `?archived=`** in the declared sentence
  of the archive family (`core`'s retired-query line below); comms' own wording
  ("no longer accepted") is gone.

#### `connections`

- **`record_failure` is gone** — nothing called it. `Connection.Status.ERROR`
  has no writer; it had none in production before.

- **The inbound webhook receiver's `401` carries a code**, `invalid_signature`
  with its remedy, where it was `unauthenticated` with the sentence "Invalid
  signature."; the route's published refusals now list it.
- **An inbound webhook to a connection id that names nothing (or a revoked
  connection) is `401 invalid_signature`**, byte-equal to a bad signature,
  where it was `404 not_found` — which told a sender the id did not exist.
- **The OAuth callback's spent or foreign `state` is `400 invalid` naming
  `state`** in `errors`, where it was a `400` with a sentence alone.

#### `core`

- **A field that names a person is marked `personal` on its `Out`, and no
  event carries one.** `core.schemas.personal()` sits beside `example()`
  (`Field(json_schema_extra=personal(example("dana@example.com")))`); the doors
  keep answering the field and OpenAPI shows `x-personal: true` on it;
  `event_payload` strips every marked field at any depth, by the `Out`'s
  declarations; `events.emit` refuses a payload its `Out` marks with the field
  put back. Marked in core: `MembershipOut.user_email` and `ArchivedByOut.name`
  — an event of an archived row carries `archived_by` as `{"id"}` alone (`name` was `null` in the template; a
  product whose user carries `full_name` published it). No `v` moves; a replay
  of a row stored before this still carries the field. `MembershipEventOut` is
  gone — `core.membership.updated`'s keys are unchanged.
- **Core's six hand-out events carry the row as the doors answer it, at
  `v: 1`.** Each payload is the row's `Out` through `event_payload`; no `v`
  moves, because no product has consumed the old shape yet (ADR core-26).
  - `core.role.created`, `core.role.updated`, `core.role.deleted` carry
    `RoleOut`: `key` (it was `role_key`), `name`, `description`, `kind`,
    `permissions`, `default_permissions`, `added`, `removed`,
    `is_default_for_new_members`, `created_at`, `updated_at`. `updated`
    carries the whole role on a rename and on a collection change alike;
    `deleted` carries the role as it stood before the delete.
  - `core.membership.updated` carries `MembershipOut` less its `personal`
    field (`user_email`): `id`
    (it was `membership_id`), `user_id`, `organization_id`, `role`,
    `is_default`, `created_at`, `updated_at` — no `user_email` (principle 18);
    a subscriber reads the person through the API, and a replay of a row
    stored before this carries `user_email`.
  - `core.grant.created` and `core.grant.deleted` carry `GrantOut`: `id`,
    `membership_id`, `organization_id`, `permission`, `sentence`, `effect`,
    `created_at`; `deleted` carries the grant as it stood.
  - **`tenant_id` is no longer a payload key** on any of the six; the event
    itself belongs to the tenant.
  - **A subscriber** reading `role_key`, `tenant_id` or (on the membership
    name) `membership_id` reads `key`, the event's tenant and `id`.
    **A replay** re-sends a stored event as it was emitted: an event of these
    six names recorded before this release still carries the old flat keys
    under the same `v: 1`, so a subscriber that replays history reads both
    shapes.
  - `events.endpoint.registered`, the seventh event whose payload moved this
    release, is the `events` bullet below.

- **`DELETE /roles/{key}/` no longer lists `invalid`** — a key the tenant
  did not make has no `Role` row, so the route answers `not_found`; the 404
  bullet says so. `MeasuredOut`'s description moved by a comment trim.

- **Declaring a key to `member` moves two published answers, for every key
  this release declares** (comms 11, workflows 3, example and the two `djb_`
  nouns 20, exports, files and imports 8). The token mint's
  `effective_scopes` echo now names the family's write scope — a member
  minting `widgets:write` sees it echoed; the token could already do the
  write, authority is unchanged. And the role editor's take-away is now
  effective: an owner removing such a key from `member` stored nothing before
  and the member kept it; now it stores an exclusion and the member is
  refused. Default answers and a tenant's stored rows are unchanged.

##### A retired query parameter

**A list that no longer takes a query parameter declares it once, beside
`PREFIX` and `TAGS`, and every reader defers to that declaration.** The
grammar is `RETIRED_QUERY: dict[str, RetiredQuery]` in the app's `api.py`,
keyed by the retired name — `RetiredQuery(instead=<the live parameter>,
reason=<the one sentence a caller reads>)`, from `apps/core/api/query.py`; a
module with nothing retired declares nothing, as with `TAGS`. The list route
calls `refuse_retired_query(request, RETIRED_QUERY)` first: `400 invalid`
naming the live parameter, in the declared sentence. The two template lists
that retired `?archived=` in favour of `?show=` — files' `GET /api/v1/files/`
and comms' `GET /api/v1/recipients/` — declare the archive family's one value,
`ARCHIVED_SWITCH`, so the refusal is one sentence now: comms' wording ("no
longer accepted") moved to files' ("`archived` is not a parameter of this
list …").

Who sees it:

- **A product with a strict-query seam** — one that refuses any query
  parameter a route does not take — calls
  `apps.core.api.query.retired_query_of(operation)` before refusing, and lets
  the route answer the parameters it names (`manage.py roads retired_query`).
  A seam that does not ask it answers `?archived=` in its own words, and the
  template's archive tests on those two lists, which assert the declared
  sentence, go red on your tree.
- **The published document** carries each retired parameter on each list
  that takes its successor, as a query parameter with `deprecated: true` and
  the sentence as its description. A generated client gains an optional,
  deprecated `archived` on those two lists' query types; it is refused if
  sent, so a screen never sends it.

##### Surfaces: a second audience on the same records

**A product answers at several hosts with one set of records**: staff at one
host, customers at another, one database, one set of services, different
doors and roles at each. A host's SURFACE is declared by the app that owns
the audience — `apps/<label>/surfaces.py` exporting `SURFACES`, found by
discovery — and bound to a host by the environment, `SURFACE_HOSTS` (deploy:
`SURFACE_ADDRESSES`, from which `deploy/provision.sh` derives the rest). The
worked second surface is the template's own: `apps/example_portal` declares
`customer` (the `widgets` and `portal_requests` families, the `read` act, the
`customer` role, the tenant chosen by the person's one membership), with its
noun `PortalRequest` and its face at `frontend/src/screens/customer/` and
`frontend/src/app/(customer)/`.

**A product that declares no surface is what it was.** The platform's
`staff` surface is implicit and total, and with `SURFACE_HOSTS` unset every
admitted host is that surface — nothing new is refused and nothing on the
wire moves. A product on one host folds and declares nothing.

Who sees it:

- **Every audit row carries `surface`** beside `door` (one expand-only
  `core` leaf; existing rows read `staff`), and so does the actor and every
  log line's bound context.
- **A role a declared surface admits holds exactly what its declaration
  says.** A predicate that says "any member" grants it nothing; the
  platform's own roles keep the un-swept residue until the consolidation's
  sweep, and the flat census's `residue` section is that count. A product
  whose surface role relied on a residue key declares the pattern in the
  role's `roles.py`.
- **Every link the system sends is built for its surface**
  (`manage.py roads absolute_url`, with `roads surface_for_role`): a
  customer's invitation lands on the customer host. House rule 85 holds a
  declaration to the tree, and house rule 84's `hand_url` class counts a link
  built from `PUBLIC_BASE_URL` outside that builder — your first gate prints
  its ratchet line with the other classes'.
- **The face asks which surface it is on** (`GET /api/v1/surface/`) and draws
  that surface's pages; a staff page at a customer host is the face's own
  seat with `noindex`, a customer page at the staff host a server 404.
- **A deployment with a second host** lists every name in
  `SURFACE_ADDRESSES` — each `host` or `key=host`, `SITE_ADDRESS` always the
  staff surface, an unkeyed second name the `customer` one — and
  `provision.sh env-file` writes `SURFACE_HOSTS` and the Caddy site block's
  names from it; a hand edit of the list re-runs `provision.sh surfaces
  <file>`. A `{tenant}` host is refused at the edge (it would need a wildcard
  certificate). The derivation runs on the box's system Python, 3.7 or later.
- **Sessions are per host.** A person who is staff on one host and a
  customer on another signs in twice; a passkey enrolled on one host is not
  offered on the other.

#### `djb_imports`, `djb_notes`, `djb_tags`

- **No `djb_notes.note.*` event carries `author_email`** — `DjbNoteOut` marks
  it `personal`: `created`, `updated`, `archived`, `restored` and `moved` name
  the author by `author_id` alone; the doors still answer it. No `v` moves; a
  replay of a row stored before this still carries it. An erased author's
  address now survives in no event payload.

##### The platform schemas' names

**Every schema class of `djb_notes`, `djb_tags` and `djb_imports` carries the
platform's word, `Djb`, as those apps' labels, tables and mounts already do.**
Two classes of one name in the one OpenAPI document do not both survive: the
document keeps ONE component, the last-discovered class's, and describes the
other app's routes with it. So a product with its own `NoteOut` had the
platform's `/api/v1/djb_notes/` routes described by the product's fields, with
nothing red. Now the platform's names cannot meet a product's. The map, old →
new, per app:

| App | Old | New |
|---|---|---|
| `djb_notes` | `NoteFilter` · `NoteIn` · `NotePatch` · `NoteOut` · `NotePage` | `DjbNoteFilter` · `DjbNoteIn` · `DjbNotePatch` · `DjbNoteOut` · `DjbNotePage` |
| `djb_tags` | `TagIn` · `TagPatch` · `TagOut` · `TagPage` · `TagLinkIn` · `TagLinkOut` · `TagLinkPage` | `DjbTagIn` · `DjbTagPatch` · `DjbTagOut` · `DjbTagPage` · `DjbTagLinkIn` · `DjbTagLinkOut` · `DjbTagLinkPage` |
| `djb_imports` | `ImportIn` · `ImportFilter` · `ImportCountsOut` · `ImportOut` · `ImportStagedOut` · `ImportPage` · `ImportRowOut` · `ImportRowPage` | `DjbImportIn` · `DjbImportFilter` · `DjbImportCountsOut` · `DjbImportOut` · `DjbImportStagedOut` · `DjbImportPage` · `DjbImportRowOut` · `DjbImportRowPage` |
House rule 91 counts comment lines past the contract line in four classes per
member (`docstring-tail`, `module-tail`, `block-tail`, `narrative`), recorded
at the measured count and down-only. The per-member floors of rules 86–89 and
91 now live with the member: a template app's in its `AppConfig.ratchet_floors`
(keyed `"<rule>.<class>"`), the platform's other members' in
`quality/ratchet_floors.yaml`; `quality/rules.yaml` keeps no member number. A
product app's finding in one of these classes prints the line to paste into
ITS OWN `apps.py`, never into a drawer; a drawer row for an app class on these
rules is refused with the same line.
#### Rule 92, rule 47's bullets, and the engine's blind spots

House rule 92: every `transaction.on_commit(` registration under `apps/` sits
inside a function marked `@road(...)` (rule 84), or carries `# rule-92:
<reason>`; the template's own unmarked sites are a recorded, down-only backlog.
A product's new registration outside a marked seam is a red. Rule 47 now reads
a route's docstring refusal bullets (`* `<status> <code>``) against its
`x-refusal-codes`: a bullet the document does not publish is a finding
(`@also_refuses(...)` naming the code, or drop the bullet). Rule 49 reads a
service on `core.schedules.daily_purge`'s one sweep signature (`(*, before:
datetime, tenant: None) -> Swept`) as ADR core-22's absence 1 without a list
entry. Rule 89 no longer reads a linter's `noqa:` codes or a
`does-not-cover:` line; rule 9 reads `from apps.core import determinism` as
the admitted seam; rule 84's `exit2_helper` reads no heredoc text. The
house-rules leg runs its unmemoised scans across processes and its runners on
threads (`DJB_RULES_WORKERS=1` scans in order, in one process); the self-test
prints the append fixtures whose names lean on their plant site's imports.
#### A long-lived deployment's old imports-sweep schedule

The names the document derives follow: `PagedNoteOut` is `PagedDjbNoteOut`,
and so for every paginated `Out`. Who sees it:

- **A product that imports a platform schema class by name** re-spells the
  import — `from apps.djb_tags.schemas import TagOut` is
  `from apps.djb_tags.schemas import DjbTagOut`, as `apps/example/schemas.py`
  now reads.
- **A product whose generated client aliases a platform component** —
  `components["schemas"]["NoteOut"]` — regenerates the client
  (`./frontend/scripts/pin_client.sh --write`) and points the alias at the
  new name. The alias keeps its own word: the worked face's `Note`, `Tag`,
  `ImportRun` and `ImportRow` now read `DjbNoteOut`, `DjbTagOut`,
  `DjbImportOut` and `DjbImportRowOut`.
- **A product whose OWN schema is named `Note*`, `Tag*` or `Import*`** no
  longer collides and may keep its name. A rename made to dodge the collision
  (a `FieldNote*`, say) stands or reverts at the product's choice.

What does not move: the REST bodies, the MCP tool results, the routes and
their `url_name`s, the tool names and the refusals are byte-identical, and so
is every MCP tool's output schema at its root but for its name. What does:
the document's component names, the generated types, and, in each MCP tool's
published output schema, both the `title` (the class's name) and the `$defs`
names of every nested schema it reaches — a non-platform tool included where
its `Out` nests a platform one (`get_widget`'s `TagOut` is `DjbTagOut`,
through `WidgetDetailOut.tags`).
Each of those apps' `schemas.py`, and `apps/example/schemas.py`, carries
a `rule-17` valve saying so, because house rule 17's breaking-`Out` clause
reads a renamed class as a removed one.

##### What a client of notes, tags and imports sees

- **An import run that broke records `run_failed`** in `failure` — `code`,
  `detail`, `remedies` — where it recorded `{"detail": …}` alone. **A cancelled
  run records no refusal**: `failure` is `{}` and `cancelled_at` is set.
- **`list_tags(show=...)` refuses an unknown cut** below the door as both
  doors already did, `invalid` naming `show`.

#### `events`

- **`events.endpoint.registered` carries `WebhookEndpointOut` at `v: 1`.**
  `endpoint_id` is gone; `id`, `url`, `is_active`, `event_names`,
  `description`, `created_at` and `updated_at` are there (still no secret).
  No `v` moves, because no product has consumed the old shape yet. A replay
  re-sends a stored event as it was emitted, so a stored row still carries
  `endpoint_id` under the same `v: 1`.
- **`POST /dead-letters/{id}/replay/` publishes its `400 invalid`** — the
  refusal for a delivery that was never given up on, which the route always
  answered and the document never listed.
- **The webhook routes' MCP read tools** (`list_endpoints`, `get_endpoint`,
  `list_deliveries`, `list_dead_letters`) answer `no_acting_scope` where they
  answered `forbidden`.
- **The dispatch workflow's argument carries the retry floor.**
  `DispatchEventWorkflow` is started with `DispatchEvent(event_id,
  retry_floor)`: the deployment's `TEMPORAL_RETRY_INITIAL_INTERVAL_SECONDS`,
  read on the Django side, so the workflow module reads no settings. A dispatch
  recorded before the upgrade and resumed after it hashes a different
  argument; the relay counts it `unresolved`, and `manage.py replay_events`
  re-dispatches it.

#### `example`, `example_portal`

- **No `example.widget.*` event carries `owner_email` or `owner_name`** —
  `WidgetOut` marks both `personal` (the worked example of `core`'s mark):
  `created`, `updated`, `deleted`, `onboarded`, `archived`, `restored`,
  `moved`, `duplicated` and `merged` name the owner by `owner_id` alone; the
  doors still answer both fields. No `v` moves; a replay of a row stored before
  this still carries them.
- **No `example_portal.portal_request.*` event carries `requester_email`** —
  `PortalRequestOut` marks it `personal`: `submitted` and `moved` name the
  customer by `requester_id` alone; the doors still answer it. No `v` moves; a
  replay of a row stored before this still carries it.
- **A widget outside the acting hat is `not_found` on update, delete and
  onboard** — the three services ask `may_be_named` before the capability,
  where they reached the row first.
- **`POST /widgets/{id}/duplicate/` and `GET /widgets/{id}/merge/` publish
  their `400 invalid`** — refusals the routes always answered.
- **Twenty keys across `example`, `djb_notes` and `djb_tags` are declared to
  `member`** in each app's `DEFAULT_ROLES`. Every `allows` answer is
  unchanged; what moves is under `core` below.

- **The worked example's two doors call one capability function each.**
  Every widget route and its MCP twin resolve the caller and call one
  keyword-only `(tenant, actor, …)` function in `apps/example/api.py` that
  returns the `Out` — the shape a product copies from the golden fences. Who
  sees it: a caller with no membership. The REST door's no-tenant refusal is
  the registered `403 no_acting_scope` body (it was `forbidden`, its `detail`
  and remedies), and the machine door's list tools answer it too where they answered `forbidden`;
  `GET /api/v1/widgets/policies/governing/` publishes `no_acting_scope` among
  its refusals. The `example.widget.moved`, `.merged` and `.onboarded` payloads
  carry the same keys, now built from an event `Out` each. A product that
  copied the example's `_acting` replaces it with `apps.core.api.acting`.
- **The worked portal's doors resolve the caller through `acting`.**
  `/api/v1/portal-requests/` and its three MCP twins refuse a request that
  resolved no tenant with `403 no_acting_scope`, and both doors read the widget a
  request names through the example's selector and leave the reach fence to
  `submit_portal_request` — the door-side `named_widget` is gone. A product that
  copied the portal replaces `named_widget` with its noun's own `get_<noun>`.

#### `exports`, `files`

- **`GET /files/{id}/versions/` publishes its `400 invalid`** — the refusal
  for an ordering the list does not accept, which the route always answered.
- **Eight keys across `exports`, `files` and `djb_imports` are declared to
  `member`.** `file.archive` and `file.restore` are among them while
  `may_archive` still refuses every member: `introspect` shows a member
  holding two keys no member can use. Every `allows` answer is unchanged.

- **The files and exports reads** answered a request with no tenant or hat an
  empty page or `forbidden`; they answer `no_acting_scope` now.
- **`GET /api/v1/files/` refuses `?archived=`** in the archive family's
  declared sentence (`core`'s retired-query line above).
- **`?subject=` on the files list and `subject` on a filing judge the kind
  first:** a kind that takes no files is `400 invalid` naming `subject` even
  when its row is out of reach, where it was `404 not_found` — the order every
  other attachment owner already answered in.

#### `search`

- **`GET /api/v1/search/` and `GET /api/v1/search/kinds/`** refuse a request
  with no tenant with `no_acting_scope` (it was `forbidden`), and their MCP
  twins `search_query` and `list_search_kinds` now refuse it too —
  `search_query` used to answer an empty page.

#### `usage`

- **`GET /api/v1/usage/`** answers a request with no tenant with
  `no_acting_scope` (it was a bare `forbidden` body). An `X-Org` that does not
  resolve was already refused by the addressing law before the route ran
  (`addressing_header_not_honoured`); the route's own copy of that check is
  gone.

#### `workflows`

- **`workflow_run.signal`, `.replay` and `.cancel` are declared to `member`**
  in `apps/workflows/policies.py`'s `DEFAULT_ROLES`. Every `allows` answer is
  unchanged — `member` held the three keys before, undeclared. The token
  mint's `effective_scopes` echo is not: a member's declared write keys backed
  `auth, tokens, users` and now back `auth, runs, tokens, users`, so a member
  minting a token with `runs:write` sees it echoed. Authority is unchanged.
- **The run ledger's replay and cancel** answered a request with no tenant a
  bare `403`, and its reads `forbidden`; every run-ledger route and tool
  answers `no_acting_scope` now.
- **A start whose on-commit hook meets a caller's bug raises out of the commit**
  (`apps.workflows.services.CALLER_BUGS` — an unbound correlation chain, a
  `TypeError` building the start, …) instead of being logged and swallowed; a
  Temporal that cannot be reached is still logged, swept by the reconciler, and
  never takes the hooks behind it down. A process that calls services below a
  door now fails where it used to leave a run that never started.
- **`purge_finished_runs` and `purge_dispatched_outbox` take `tenant=None` and
  answer a `Swept`** — the one sweep signature (`apps.core.schedules.daily_purge`).

### Added — the dispatch ledger's shape check

- **`scripts/ledger_check.py --check` is a `--fast` leg (`ledger-check`), beside
  the queue index.** It reads `docs/product/in-flight.md` § "Dispatch ledger"
  and the archive's `### … — pruned` stages through `scripts/loop_metrics.py`'s
  row and stamps reader. Every armed row has seven cells and is at most 1,200
  characters, and the live table is at most 16 KB. Every returned row carries a
  `stamps:` cell whose stage stamps are dated, and a report pointer; a `TRAIN-`
  or `PM-` row instead carries its merge sha once it lands. A closed
  spend-per-rung row carries its number. Archived rows sent before the arming
  date are history and are not judged. Exit 0 clean, 1 each refused row named,
  2 could not look.
- **The pre-commit hook's docs-only admission runs the check** when a staged
  path is the live ledger or the archive, and refuses the commit on exit 1 or 2.
  The rest of the docs-only path is unchanged.

### Added — the roads index

- **A road declares itself once, where it lives.** In importable Python,
  `@road("<job>", example="<path>::<symbol>")` from `apps.core.roads` on the
  function or class, or `ROAD = road("<job>", example=...)` after a module's
  imports for a module that IS the road; the contract is the docstring's first
  line, and a target with no docstring is refused at import. In shell, a
  comment line directly above the function (or in a script's first 40 lines)
  that opens with `road:` and reads `<job> — <contract> · example:
  <path>::<symbol>`. A job key is one lowercase word or `noun_verb`, never a
  file name or a medium. The example must resolve to a real definition.
- **The door: `uv run python manage.py roads`.** One block per job — the road's
  import path, its partition (platform or product, from
  `quality/partition.yaml`'s `platform_apps`), its carrier, its contract and
  its example; `roads <job>` prints one; `roads --json` prints the `roads/1`
  document (`roads[]`, `kept[]` for a product's declared second roads,
  `unmarked` for the counted copies by class). It is an instrument: exit 0
  printed, exit 2 could-not-look (a road that does not import, an example that
  does not resolve, two unvalved markers for one job); it never exits 1.
- **House rule 84, one road per job.** A second marker for one job is refused,
  the finding naming both and the first standing, unless the second carries
  the rule's valve on the line above it (counted, and printed by the door as
  `kept`). A road is unconditional: a marker under an `if` (a
  `TYPE_CHECKING` block included), `try` or `with`, or inside a function, is
  refused. The same check counts unmarked copies by shape as ratchet classes,
  down-only. `python -m quality.gate --explain 84` prints the classes, their
  numbers and a remedy each.
- **The fold's eighth collision class.** `divergence_census.sh --against
  <tag>` reads the release's markers and yours as text and names a product
  road for a job the release now marks, with the two remedies on the line.
- **Step zero dumps the index.** `scripts/rung_start.sh` writes
  `manage.py roads --json` to `.rung/roads.json` beside the schema dump.

### Changed

- **The gate sorts by bytes, never by locale.** The `--loop` scope's changed set
  and the environment fingerprint's distribution list are ordered the way
  Python orders strings (`LC_ALL=C`), where the shell gate ordered them under the
  caller's locale: under `en_US.UTF-8` `list_legs_ci.txt` sorted before
  `list_legs.txt` and `aiohttp_retry` before `aiohttp`. Who sees it: a checkout
  whose loop verdicts were banked under a non-C locale — its first `--loop` after
  the merge is a miss (the key moved), and every one after it reuses as before.
- **`admin.LogEntry` declares its lifecycle: `unbounded`, retained whole.** The
  owner retains every admin log (2026-10-08), so `erase_user` never touches
  `django_admin_log` by declaration rather than by silence; `apps.core.lifecycle`
  declares it, and rule 31's `admin` class has nothing left to count.

- **The verifier box client's owner tag no longer reads the dispatch ledger.**
  `python -m quality.djb.box` defaults the owner to `DJB_VERIFIER_OWNER`, else
  `git config user.name`, else `unknown` said on stderr; it never opens a docs
  file for it, so a ledger commit stays docs-only. `scripts/verifier_box.sh`
  still reads the ledger until the cutover.

- **`frontend/pnpm-lock.yaml` takes the patched release of every package
  `pnpm audit --audit-level moderate` named, and the audit answers clean.**
  `brace-expansion` moves per major — `1.1.18` → `1.1.21`, `2.1.4` → `2.1.7`,
  `5.0.9` → `5.0.12` (floors `>=1.1.21`, `>=2.1.7`, `>=5.0.12`; GHSA-q2hr-2g5m-vwhr,
  GHSA-qhr7-859c-m2p7, GHSA-6j4f-fj2g-mc7p); `js-yaml` `4.3.1` leaves the lock and
  every consumer resolves `4.3.2` (floor `>=4.3.2`; GHSA-2883-xcg3-v3hh), which
  takes `@redocly/openapi-core` `1.34.19` → `1.34.20` because `1.34.19` pins
  `js-yaml` to exactly `4.3.1` and `1.34.20` is the same dependency set on
  `4.3.2`; `undici` `8.10.1` → `8.10.2` (floor `>=8.10.2`; the advisories published
  against `undici <8.10.2`). These are transitive — reached through `eslint`,
  `eslint-config-next`, `openapi-typescript` and `jsdom` — so none of them changes
  `package.json` and no override is taken; the generated client is
  byte-identical. Who sees it: a product whose own `pnpm audit` or supply-chain
  check reads the frontend lock. At the fold, take this lock byte-for-byte, or
  re-resolve the same names to the same versions; a product carrying its own
  `pnpm.overrides` for any of these reconciles them major by major.
  `next` is the direct dependency that moves: `package.json`'s exact pin goes
  `16.3.3` → `16.3.8` (floor `>=16.3.6`; GHSA-vcvr-r3jv-pc5j), which takes its own
  `@next/env` and `@next/swc-*` binaries with it, and `eslint-config-next` stays
  at `16.3.3`; a product that pins `next` itself moves that pin to the same line.
  The Python lock moves the same way: `uv.lock` takes `urllib3` `2.7.0` → `2.8.0`
  (fix version `2.8.0`; CVE-2026-97687, CVE-2026-97688, CVE-2026-97689), which
  `pip-audit` named, and nothing else in the lock or `pyproject.toml` moves.

- **The supply-chain leg's dead-weight check reads the index, so a product
  still carrying v2.4.1's oauthlib override is red at that leg now.**
  `django-allauth` 65.19.6 declares an `oauthlib` that admits the patched 4.x,
  so this release takes 65.19.6 and deletes `[tool.uv] override-dependencies`
  and the exception record that justified it. The remedy for a product is the
  same two moves: upgrade `django-allauth` and delete the override. The
  trigger stays in `scripts/check.sh` as the guard against putting the
  override back; with none declared it judges nothing.

- **A product's own breakpoint reads `<length> — <reason>`.** House rule 78's
  drawer — a fenced `breakpoints` block in
  `docs/product/design/patterns.local.md` — takes any number of lines, each a
  CSS length (`rem`, `px` or `em`) and its reason after an em dash. A bare
  value gains a dash and a reason at the fold; a line without one is a
  finding on the drawer's own line. A width query in the legacy `min-`/`max-`
  form is now a FORM finding whose sentence names the range syntax every
  width query takes (`(width <op> <length>)`) and says whether the value is
  declared; whether the book's boundary is inclusive is the book's sentence.

- **`quality/gate.py`'s module docstring is its contract line and four
  invariants.** The usage block, the scope-kind, override and ratchet
  narration and the self-test's reasons left the code: the flags are the
  sentence an unknown flag is refused with (`python -m quality.gate --nope`);
  a rule's scope kind, valve and ratchet are `python -m quality.gate
  --explain <id>`; the exit codes, the preflight, the runner boundary and the
  plant-into-the-real-tree refusal are the four lines that stayed. Nothing a
  command prints changed.

- **The house-rules engine is a package: `quality/gate.py` is its door and
  `quality/engine/` holds the eleven modules behind it.** `python -m
  quality.gate`, every flag and `from quality import gate` answer as before;
  `--rules` and every `--explain` print the same bytes. A product test that
  sets an attribute on `quality.gate` now sets it on the door and the engine
  never reads it: a shared dict or list is changed in place, and a path or
  string is set on its home (`gate.world_module()`). A `# drives:` line or a
  cite naming `quality/gate.py::<name>` names the engine module that defines
  it.

### Known

- **A change to the published document must regenerate the client in the
  same change** — `./frontend/scripts/pin_client.sh --write` — because the
  per-rung loop does not yet run the client pin: only the full gate at push
  does, and a document moved without its client reads green until then.
- **Three questions about the face are open, for the design owner**: the
  off-surface seat's plainer look beside the refusal panel's; whether the
  boot question's could-not-look panel, drawn before any surface is known,
  takes the staff surface (as it does today) or a value of its own; and the
  client seam's wording when the backend is unreachable — through the face's
  proxy that arrives as a 500 with no body of ours and reads as "the server
  refused", where only a thrown fetch reaches the honest sentence.

## [2.4.1] — A release's new platform apps do not collide with a product's own, and a product with an earlier archive has a road into the seam

**A product's first fold of 2.4.0 stopped at the merge, three ways at once:
the release's new platform app `notes` carried the label and the table of an
app the product already owned, so the tag could not merge into it; the seam's
files landed where the product's own hand-built archive already sat; and seven
modify/delete conflicts arrived in face files the release had modified and the
product had moved.** 2.4.1 gives the three platform apps 2.4.0 added names no
product spells — `djb_notes`, `djb_tags`, `djb_imports`, and everything that
derives from the label or the kind — so a product that owns a `notes`, `tags`
or `imports` app merges the tag with no add/add conflict in it and renames
nothing. It adds the collision census a fold runs before the merge, which
refuses by name every label, table, index, unique constraint, authorization
kind, REST mount and router tag a release's app shares with one of the
product's own, and prints the road for the product's side; a house rule that
refuses two apps on one path or one tag at `check`; the road a product with a
pre-seam archive takes into the seam; and the face's rename map, measured.
2.4.1 is a patch by the owner's word, on the hotfix road: it renames names on
the wire, which the reading above would call more than a patch, and it is a
patch because it makes 2.4.0 the thing it was meant to be — platform apps a
product can merge — before any product took it. **The wire changes are named
plainly, and each has a reader.** The three apps' REST paths moved under
`/api/v1/djb_notes/`, `/api/v1/djb_tags/`, `/api/v1/djb_tag_links/` and
`/api/v1/djb_imports/`, and their scope families and router tags to
`djb_notes`, `djb_tags` and `djb_imports`: a client regenerated from the tag
sees the paths, and a token asking for `notes:read` while nothing here serves
`notes` is refused and told `djb_notes:read`. The names derived from the label
or the kind moved with them — the OpenAPI operation ids a regenerated client
sees, the event names an outbox subscriber sees, the MCP tool names an MCP
client sees, the policy keys a grant or a role spells, the url_names and the
archived-refusal remedies a face resolves, the audit actions an audit reader
filters on and the import runs' workflow ids. The map under *What a product
does at the merge* lists every one with its count. No product took 2.4.0, so
none of them was written against.

### What a product does at the merge

Four parts, each read from the tree it names. **The map** is what moved
between 2.4.0 and 2.4.1 and who sees it. **The rename road** is what a
product does when the collision census names one of its own apps. **The
pre-seam road** is for a product that built archive by hand before 2.4.0.
**The face's rename map** is measured, and it is empty.

#### The map, 2.4.0 → 2.4.1

The three platform apps 2.4.0 added take the `djb_` namespace: their labels,
modules, tables, index and constraint names, authorization kinds, REST mounts
and router tags carry it, and every name derived from those moved with them. Read off
`uv run python manage.py introspect` on the two trees and
`frontend/openapi.json` at each tag.

| what | 2.4.0 | 2.4.1 |
|---|---|---|
| labels | `notes`, `tags`, `imports` | `djb_notes`, `djb_tags`, `djb_imports` |
| modules | `apps.notes`, `apps.tags`, `apps.imports` | `apps.djb_notes`, `apps.djb_tags`, `apps.djb_imports` |
| tables | `notes_note`; `tags_tag`, `tags_taglink`; `imports_import`, `imports_importrow` | `djb_notes_note`; `djb_tags_tag`, `djb_tags_taglink`; `djb_imports_import`, `djb_imports_importrow` |
| index and constraint names (13) | `note_recency`, `note_subject_recency`, `note_subject_kind_not_empty`; `tag_recency`, `tags_tag_slug_per_tenant`, `taglink_recency`, `taglink_subject`, `tags_taglink_one_per_subject`; `import_recency`, `import_one_live_run_per_digest`, `import_unique_idempotency_key_per_organization`, `importrow_recency`, `importrow_one_row_per_line` | each is `<table>_<suffix>`: `djb_notes_note_recency`, `djb_notes_note_subject_recency`, `djb_notes_note_subject_kind_not_empty`; `djb_tags_tag_recency`, `djb_tags_tag_slug_per_tenant`, `djb_tags_taglink_recency`, `djb_tags_taglink_subject`, `djb_tags_taglink_one_per_subject`; `djb_imports_import_recency`, `djb_imports_import_one_live_run_per_digest`, `djb_imports_import_unique_idempotency_key_per_organization`, `djb_imports_importrow_recency`, `djb_imports_importrow_one_row_per_line` |
| authorization kinds (4) | `note`, `tag`, `tag_link`, `import` (an `ImportRow` is authorized under its run's kind) | `djb_note`, `djb_tag`, `djb_tag_link`, `djb_import` (an `ImportRow` resolves to `djb_import`) |
| policy keys (22) | `note.{archive,create,delete,read,restore,update}`, `tag.{archive,create,delete,read,restore,update}`, `tag_link.{create,delete,read,update}`, `import.{apply,cancel,create,delete,read,update}` | the same verbs under `djb_note.`, `djb_tag.`, `djb_tag_link.`, `djb_import.` |
| url_names (21) | `note-{list,create,detail,update,archive,restore}`, `tag-{list,create,detail,rename,archive,restore}`, `tag_links-list`, `tag_link-{create,delete}`, `import-{list,create,detail,apply,cancel}`, `import_rows-list` | the same, each with `djb_` in front: `djb_note-archive`, `djb_tag_links-list`, `djb_import_rows-list` … |
| MCP tool names (21) | `list_notes`, `create_note`, `get_note`, `update_note`, `archive_note`, `restore_note`; `list_tags`, `create_tag`, `get_tag`, `rename_tag`, `archive_tag`, `restore_tag`; `list_tag_links`, `create_tag_link`, `delete_tag_link`; `list_imports`, `create_import`, `get_import`, `apply_import`, `cancel_import`, `list_import_rows` | the noun takes `djb_`: `list_djb_notes`, `archive_djb_note`, `create_djb_tag_link`, `list_djb_import_rows` … |
| OpenAPI operation ids (21) | `apps_notes_api_<function>`, `apps_tags_api_<function>`, `apps_imports_api_<function>` | `apps_djb_notes_api_<function>`, `apps_djb_tags_api_<function>`, `apps_djb_imports_api_<function>` |
| event names (16) | `notes.note.{created,updated,archived,restored,moved}`, `tags.tag.{created,renamed,archived,restored}`, `tags.tag_link.{created,deleted,moved}`, `imports.import.{staged,previewed,applied,failed}` | the label in front, the noun unchanged: `djb_notes.note.created`, `djb_tags.tag_link.moved`, `djb_imports.import.applied` … |
| archived-refusal remedies in the OpenAPI document (4) | `route:note-restore` (in the description and as the `destination`), `route:tag-restore`, `route:tag_link-restore` | `route:djb_note-restore` (twice), `route:djb_tag-restore`, `route:djb_tag_link-restore` |
| audit actions | `<label>.<service>`: `notes.create_note` … | `djb_notes.create_note` … |
| workflow ids | `<tenant>:imports:import:<run>-check` and `-apply`; the purge schedule's `platform:imports:purge:<queue>` | `<tenant>:djb_imports:import:<run>-check` and `-apply`; `platform:djb_imports:purge:<queue>` |
| REST paths (15) | `/api/v1/notes/…`, `/api/v1/tags/…`, `/api/v1/tag-links/…`, `/api/v1/imports/…` | `/api/v1/djb_notes/…`, `/api/v1/djb_tags/…`, `/api/v1/djb_tag_links/…`, `/api/v1/djb_imports/…` |
| scope families and router tags (3) | `notes`, `tags`, `imports` | `djb_notes`, `djb_tags`, `djb_imports` — recorded in `SANCTIONED_RENAMES` (`apps/core/api/frozen_families.py`), so a token holding an old key is refused and told the new one |
| rule 32 valve entries | `notes`, `tags`, `imports` | `djb_notes`, `djb_tags`, `djb_imports` |
| reverse accessors (Python, not the wire) | `FileVersion.imports`, `User.imports_requested`, `User.imports_applied`; the scoped bases' `%(app_label)s_%(class)s_set`: `Tenant.notes_note_set`, `Organization.tags_taglink_set` … on every model of the three | `FileVersion.djb_imports`, `User.djb_imports_requested`, `User.djb_imports_applied`; `Tenant.djb_notes_note_set`, `Organization.djb_tags_taglink_set` … |

**What did not move:** the attachment kinds a noun declares and a list reads
with `?subject=` — `attachments = ("notes", "files", "tags")`,
`?subject=<kind>:<id>` — the `Out` schemas, the verbs of the MCP tool names,
the shape of the url_names and tool names (`<noun>-<verb>`,
`<verb>_<noun>`), and every OTHER app's mount and family. The instruments are
the OpenAPI document's `paths` at the two tags (15 keys moved, every other key
and every other path's body byte-identical) and the two `introspect` dumps
(21 route and URL patterns moved, every name the same; the 21 tools differ
only in their descriptions — the derived scope line, and three docstrings
that spell a path; models, events, policies,
refusals, roles, consumers and workflows byte-identical).

**These are wire changes, and each one has a reader.** A client regenerated
from the tag sees the 15 path keys and the 21 operation ids. A token minted on
a 2.4.0 checkout with `notes:read` is refused, and the refusal names
`djb_notes:read`. A subscriber to the outbox sees the
16 event names. An MCP client sees the 21 tool names. A policy file, a role or
a grant that spells a key sees the 22 policy keys. A face that resolves a page
by url_name sees the 21 url_names, and a face that draws a `route:` remedy
sees the four. An audit reader sees the actions, and a Temporal search by id
sees the import runs' ids. **Nobody who took a tag is affected: no product
took 2.4.0**, so every name above changes before anything was written against
it. A product's OWN nouns are untouched — their kinds, keys, url_names and
tools are their own words.

#### The rename road

The collision census prints `remedy: rename YOURS` under a `collision:` line
and points here. Each step says what you see if you skip it.

1. **Take the census from the tag, then run it against the tag.** `git fetch
   template --tags`; then, as [2.1.1]'s item 1 says, take the census AND its
   classifier from the tag you are folding — `git show
   <tag>:scripts/divergence_census.sh > scripts/divergence_census.sh` and
   `git show <tag>:scripts/archaeology_lib.sh > scripts/archaeology_lib.sh`
   — and run `./scripts/divergence_census.sh --against <tag>` before the
   merge. It reads the release's apps and yours for seven name classes —
   label, table, index, unique constraint, authorization kind, REST mount,
   router tag — plus a label, mount or tag of yours under the template's
   reserved `djb_` prefix, and prints one `collision:` line per pair with the
   remedy under it, then `collisions: labels=… tables=… indexes=…
   constraints=… kinds=… reserved=… mounts=… tags=…`. Any pair is
   exit 2 whatever the divergence half said. It writes nothing and fetches
   nothing. Skip it and the merge succeeds: the collision arrives one step
   later, as a `migrate` that dies on a relation that already exists or a
   start-up that refuses one authorization kind claimed by two models.
2. **A `kind` line is fixed on your model, in one line, and is its own
   step.** Type `authz_kind = "<its own word>"` on the class the census named
   (`apps/core/authz.py` derives a kind from the class name unless the class
   types one). The release's kind is the platform contract every product's
   grants are written against, so it is never the one that moves. Your
   model's policy keys become `<word>.<verb>`, and rule 74 then asks for its
   url_names as `<word>-<verb>` (`python -m quality.gate --explain 74`), which
   renames its MCP tools with them. The tenant rows that spell the old keys
   move BEFORE the merge, while the old word is still only yours: declare each
   pair in your app's `RENAMED_PERMISSIONS`, deploy, run
   `manage.py rename_permission --declared`, and retire the pairs before the
   tag lands, because after it the old word is the release's. Skip it and
   the vocabulary cannot be derived at all: start-up refuses, naming both
   models that `both claim the authorization kind`.
3. **A `label` or `reserved prefix` line: move the app.** `git mv
   apps/<label> apps/<yours>_<label>` and set `name =
   "apps.<yours>_<label>"` in its `apps.py`. Type no `label =`: Django's
   label is then the last segment of `name`, so the directory IS the label,
   and the mount, the tables and the census all read one word. Never choose a
   name that starts `djb_`. Skip it and the merge lands two
   apps with one label, which Django refuses at start.
4. **Every reference to the old label.** Every `depends_on` that names it
   (house rule 7 refuses an import an app has not declared), every `from
   apps.<label>` import — `git grep -ln 'apps\.<label>\b'` is the list — and
   every migration that names the app by label: its own chain's
   `dependencies` tuples, and every other app's `("<label>", "<migration>")`
   dependency and `"<label>.<Model>"` reference. Skip the migrations and the
   next `migrate` dies on a dependency on an app that does not exist.
5. **Your routes' paths.** An `api.py` with no `PREFIX` is mounted under its
   LABEL (`config/api.py`'s discovery), so a moved app moves its URLs. To keep
   the path a client already calls, add `PREFIX = "<label>"` to the moved
   app's `api.py`; the release's platform apps mount under `djb_` words a
   product never spells, so the old path is yours to keep. Skip it and every
   client of the app answers 404.
6. **The tables.** A table's default name is `<label>_<model>`, so the moved
   app's models now name tables that do not exist, and `django_migrations`
   holds its chain under the old label. Two ways, one per case:
   - **The census named a table** — rename it. Keep the moved chain; once per
     database, before `migrate`, run `UPDATE django_migrations SET app =
     '<yours>_<label>' WHERE app = '<label>'` (the one step no migration can
     carry, because Django reads that table to decide what to run); then add a
     migration to the app whose `migrations.RunSQL("ALTER TABLE <old> RENAME
     TO <new>", reverse_sql="ALTER TABLE <new> RENAME TO <old>")` renames each
     table, the automatic many-to-many tables included. The chain's state
     already names the new tables, so the SQL brings the database to where the
     state is and `makemigrations` reports no change. **A renamed table keeps
     the index names Django generated for it**, and Django builds those from
     the table's name — `<table>_<columns>_<digest of the table and columns>`
     (`_create_index_name` in `django/db/backends/base/schema.py`) — so every
     foreign key's index on a moved table (`<old table>_tenant_id_<hash>` on
     each tenant-scoped model) still carries the OLD table's name, and the
     release's `CreateModel` for that table computes byte-identical names.
     Rename each one in the same migration:
     `ALTER INDEX <generated name> RENAME TO <name carrying the new table>`,
     with the reverse. List them with `SELECT indexname FROM pg_indexes WHERE
     tablename = '<new table>'` after the table rename (the names that still
     start with the old table's are the ones), or read the names the release
     will try to create with `manage.py sqlmigrate <release app> 0001` on the
     merged tree. The primary key's constraint and the id sequence need
     nothing: Postgres picks a free name when the release creates its own.
     This bites a later release, never 2.4.1 itself — the three apps it adds
     are under `djb_`, which no product label may use. Skip it and the
     release's migration dies on `relation "<old table>_tenant_id_<hash>"
     already exists`.
   - **The census named the label and no table** — keep the tables. Delete
     the moved chain's migration files (keep `__init__.py`), type `db_table =
     "<old table>"` in each model's `Meta`, let `makemigrations
     <yours>_<label>` write one `0001_initial`, point every other app's
     dependency on the old chain at `("<yours>_<label>", "0001_initial")`, and
     `migrate <yours>_<label> --fake-initial`. Django fakes an initial
     migration only when every table its `CreateModel`s name already exists.
     Without the `db_table` it creates a second, empty set of tables beside
     your data, or dies on an index name the old tables already hold.

   Either way, then `UPDATE django_content_type SET app_label =
   '<yours>_<label>' WHERE app_label = '<label>'`. Skip it and every row that
   points at a content type by id points at the old label's, while Django
   makes a new, empty one.
7. **An `index` or `constraint` line: rename yours.** Index and unique
   constraint names are global to the schema. Shadow `Meta.indexes` on the
   model in house rule 37's form, with the inherited recency composite
   re-added under a name that carries your table (`apps/djb_tags/models.py`'s
   `TagLink` is the worked shape), and let `makemigrations` write the
   `RenameIndex`. A unique constraint has no rename operation: `makemigrations`
   writes a remove and an add, which rebuilds its index. Do this after step
   6's `migrate`, so the rename runs against the names your database holds.
   Skip it and the release's migration dies on `relation "<name>" already
   exists`.
8. **What else your label carried.** A product's own event names
   (`<label>.<noun>.<verb>`), audit actions (`<label>.<service>`) and
   operation ids (the module path) follow the label, exactly as the map above
   shows for the template's three. Tell your outbox subscribers and your
   client, and regenerate the client with `frontend/scripts/pin_client.sh
   --write`. A workflow id takes `app=` as a string your code spells, so it
   moves only where you move it; a run already started keeps its id.
9. **The mounts and the tags, which the census reads and `check` refuses.**
   Step 1's census prints a `collision: mount <segment>` or `collision: tag
   <key>` line for each first path segment or router tag of yours that the
   release also serves, with the remedy on your side — `remedy: mount YOURS
   elsewhere — PREFIX = "<its own word>" in your api.py (or the route path's
   first segment, when PREFIX is ""); the release's mount is the platform's`
   and `remedy: tag YOURS with a word of its own — Router(tags=["<its own
   word>"]) and the matching TAGS key; a tag is a scope family, and one key
   across two apps is one token ceiling that reaches both`. After the merge,
   `manage.py check` refuses one path pattern bound by two apps, or one tag key
   declared by two (`djb.E083`, house rule 83). A path of yours is the census's
   business only when it collides with a CORE app's mount — the platform apps
   that keep their words (`connections`, `exports`, `files`, `search`,
   `widgets`) and the root-mounted segments the census lists for the release —
   never a `djb_` one, which a product does not spell. Skip it and the
   release's `djb_` routes still answer beside yours with nothing colliding;
   a core collision you skipped answers with whichever app was discovered
   first, and `check` refuses the deployment. The step is now a check you run,
   not a comparison you make by hand.
10. **`manage.py fold_migrations` is not part of this road.** It grafts an
    arriving template chain onto your leaf in an app you SHARE with the
    template (`core`, `accounts` — `apps/core/management/commands/fold_migrations.py`
    says so at its head). An app you renamed receives no template migration,
    because the release's app carries its own name.
11. **Prove it.** `./scripts/check.sh --loop` exit 0, then the census again:
    `./scripts/divergence_census.sh --against <tag>` prints `collisions: none
    against <tag>`. Then merge.

#### The pre-seam road

For a product that built archive by hand, on its own nouns, before 2.4.0.
The seam's files are read from the release diff,
`git diff --name-status v2.3.0 v2.4.0 -- apps`; for 2.4.1 read the same
command with `v2.4.1`, which adds the three platform apps under their `djb_`
names. Each step says what you see if you skip it.

- **The seam's NON-TEST files 2.4.0 adds:** `apps/core/verbs.py`,
  `apps/core/blockers.py`, `apps/core/bulk.py`, `apps/core/concurrency.py`,
  `apps/core/migrations/0019_audit_trail_reads_a_rows_history.py`,
  `apps/comms/migrations/0010_recipient_archived_by.py`,
  `apps/files/merge_repointers.py`,
  `apps/files/migrations/0002_archivable_and_subject.py`,
  `apps/example/archive_blockers.py`, `apps/example/restore_blockers.py`,
  `apps/example/importers.py`,
  `apps/example/migrations/0012_widget_and_policy_archivable.py` and
  `apps/example/migrations/0013_widget_copies_folds_and_external_ref.py`.
- **Its TESTS:** 31 new modules under `apps/core/tests/` (among them
  `test_archivable.py`, `attach_world.py`, `isolation.py`, `doors.py`),
  `apps/comms/tests/test_allowed_acts.py`, `apps/comms/tests/test_archive.py`,
  `apps/files/tests/attach_specimen.py`,
  `apps/files/tests/test_archive_road.py`,
  `apps/files/tests/test_iter_object.py`, 14 under `apps/example/tests/`,
  `apps/exports/tests/test_archived_rows.py` and
  `apps/test_absent_relative_imports.py`. Both lists, exactly, are
  `git diff --name-only --diff-filter=A v2.3.0 v2.4.0 -- apps` without the
  three platform apps.
- **It MODIFIES** 34 files in `core`, 14 in `comms`, 19 in `files`, 20 in
  `example`, and ten more across `accounts`, `events`, `exports`, `usage`,
  `workflows` and `apps/conftest.py`.

1. **Before the merge, name every hand-built archive file under a PLATFORM
   app** in `docs/product/architecture.md` as `divergence: <path> — pre-seam
   archive, retired noun by noun`, so the divergence census ([2.1.1]'s item
   1) is exit 0. An add/add conflict on `apps/core/verbs.py`,
   `apps/core/tests/test_archivable.py` or `apps/comms/tests/test_archive.py`
   means your product wrote a file at a template-owned path. Skip it and the
   census is exit 1 on paths you meant to keep, and the merge's conflicts are
   the first place you learn which.
2. **At the merge, take the seam's core and the seam's tests WHOLE from the
   tag** — `git checkout <tag> -- <path>` for every path in the two lists
   above — and never hunk-merge a template test into a production app. Those
   tests measure the template's seam; a product's edits to them are a drive
   that proves nothing about a product noun. Move your own implementation of
   the same file out first — to your nouns' apps or the `local/` drawer — so
   nothing of it is lost. "Whole" is right for a template-owned path only:
   the census's ownership reading is the arbiter, and a path it calls
   `product` is yours to merge. Skip it and the seam runs with your edits in
   it, green on your tree and wrong about the template's.
3. **Prove the recipe on this tree before touching a noun:**
   `scripts/tests/test_golden_copy.sh --verb archive` exit 0. It copies the
   fenced blocks onto a throwaway noun, migrates it, runs the checks and the
   copied test, and drops it. Exit 1 is a case that failed on this tree — a
   tree the recipe does not land on; exit 2 is could-not-look (no venv, no
   database, an unknown verb), never a pass. Either way exit 0 is the bar, and
   the noun work waits for it. Skip it and the first noun meets the tree's
   defect and reads it as its own.
4. **Adopt noun by noun, one commit each, from the fence** —
   `.claude/skills/django-conventions/SKILL.md` § 16, "Adopt archive in one
   commit". Declare `Archivable` and keep the hand-built pair beside the
   seam's until step 5. Skip the one-commit rule and a noun is half on each
   road, which rule 74 refuses without saying which half is yours.
5. **"The noun's road is green" is three exits:** `uv run python manage.py
   check --tag djb` exit 0 with no rule 74 finding naming the noun
   (`python -m quality.gate --explain 74`), the noun's own
   `pytest apps/<noun app>` green, and `./scripts/check.sh --loop` exit 0.
   Then retire the hand-built pair — its service, route, tool and test — in
   the same commit, and strike the `divergence:` line. Skip the retirement and
   the noun answers two archive roads that disagree.
6. **A noun that gains its archive door before its face draws the verb**
   records `door-without-road` at the fold, with the client regenerated, and
   lowers it in the face rung that draws archive ([2.4.0]'s item 9); the road
   is never valved. Skip it and rule 77 reds the face at the fold, because the
   committed `frontend/openapi.json` carries a door the face's road does not
   draw.

#### The face's rename map

`git diff -M50% --name-status v2.3.0 v2.4.0 -- frontend/src` on the released
repository prints **no `R` row and no `D` row**: 2.4.0 moved and deleted
nothing under `frontend/src`. It added 29 files and modified ten:
`frontend/src/api/generated/schema.d.ts`, `frontend/src/copy/dialog.ts`,
`frontend/src/copy/lexicon.ts`, `frontend/src/primitives/README.md`,
`frontend/src/primitives/dialog.tsx`, `frontend/src/screens/refusal-panel.tsx`,
`frontend/src/screens/routes.ts`, `frontend/src/screens/state.test.ts`,
`frontend/src/screens/state.ts` and
`frontend/src/screens/welcome/welcome-screen.tsx`. So the rename map has no
rows. A modify/delete conflict on one of these is one side modifying and the
other deleting: the RELEASE modified a file your PRODUCT moved. The road for
a moved one: `git show v2.4.0:<old path> > <old path>` is not the answer — it
resurrects the file you moved. Apply the release's hunks to the file at its
NEW path — `git diff v2.3.0 v2.4.0 -- <old path>`, its paths rewritten to the
new one, through `git apply --3way`, or by hand for a short hunk — then
`git rm <old path>` to settle the conflict as deleted. A later release that
does move files prints rows here, and this sentence becomes a table.

### Added

- **The collision census, before the merge.** `scripts/divergence_census.sh
  --against <tag>` reads the release's apps at the tag and the product's own
  apps in its working tree through one parser, and compares seven name
  classes: labels, tables, index names (a `models.Index` and every subclass of
  it), unique-constraint names, authorization kinds, REST mounts and router
  tags. Each pair is one `collision:` line with its remedy under it, any pair
  is exit 2 whatever the divergence half concluded, and the trailer counts
  each class. The schema's names are read from migrations, because a
  migration says what exists and an abstract model creates nothing. Without
  `--against` it says the collisions were not measured and runs as before; a
  ref it cannot resolve is exit 2 naming the fetch.
- **The `djb_` promise.** The template's platform apps take their names under
  `djb_`, the prefix the tree already uses for what it derives and a product
  never names, and the census refuses a product label, mount or tag under that
  prefix on a line of its own. So a platform app a later release adds under
  `djb_` cannot collide with a product that folded clean — not only these
  three.
- **House rule 83, `djb.E083`: one app per path pattern, one app per tag.** A
  Django system check refuses a path pattern bound by two api modules, and a
  tag key declared or carried by two apps, both read off the live mount and
  tag discovery. django-ninja refuses neither: two modules on one path answer
  on the wire with the one discovered first while the document describes the
  other, and one tag across two apps is one token ceiling reaching both. No
  valve; the finding names both apps. ADR mounts-1 in
  `docs/product/architecture.md` records the decision and what was rejected.
- **Erasure is pinned on a note's author.** `apps/djb_notes/tests/test_erasure.py`
  erases a person who wrote a note, live and archived: the erasure completes,
  the note keeps its author and its body, and a reader sees the erased
  address. The one place the original address survives is the note's own
  events, a declared retention.

### Changed

- **The three platform apps are `djb_notes`, `djb_tags` and `djb_imports`** —
  label, module, tables, index and constraint names, authorization kinds,
  REST mounts, router tags and scope families, and every name derived from
  those. The map under *What a product does at the merge* is the list, and
  the paragraph under it says who sees each wire change. Four kinds moved —
  `djb_note`, `djb_tag`, `djb_tag_link`, `djb_import` — and an import row
  resolves to `djb_import`, as it resolved to its run's kind before. The
  attachment kinds a noun declares (`notes`, `files`, `tags`) and
  `?subject=<kind>:<id>` did not move.
- **The scope-family freeze knows a released departure.** The three old
  families are recorded in `SANCTIONED_RENAMES`
  (`apps/core/api/frozen_families.py`) as `Released` departures: no token
  outside this repository held them, so the words are given back. A
  product's own app may tag `notes` and owns `notes:read` outright; only while
  nothing serves the old word is a token asking for it told its successor.

### Fixed

- **A platform app's index and unique-constraint names carry its table.**
  Those names are global to the schema, and the scoped base names every
  recency index `<class>_recency`, so a product's own `Note` already held
  `note_recency` and the relabelled app's `migrate` would have died on it one
  step after a clean merge. Every hand-named index and constraint of the three
  apps is `<table>_<suffix>`.

### Known

- **Every app not renamed here still names its recency index
  `<class>_recency`** from the scoped base, so a product model whose class
  name equals a template model's (`Recipient`, `Membership`, `StoredFile` …)
  collides on that index. The census shows it as an `index` pair before the
  merge; the base's own fix, for every app, is a later release's.
- **A template developer's existing database keeps orphans** under the old
  labels: the tables `notes_note` and the rest, their `django_content_type` and
  `django_migrations` rows, and audit rows whose actions carry the old label.
  Harmless and dev-only — a fresh checkout derives a fresh database — and
  `manage.py remove_stale_contenttypes` plus a `DROP TABLE` the developer types
  clear them.
- **A product whose erasure deletes `User` rows meets `PROTECT`** on a note's
  `author` and `archived_by`, by design: it anonymises instead, as the
  template's erasure does, or decides first what becomes of that person's
  notes.
- **The collision census reads text.** A bare `RemoveIndex(` with no
  `migrations.` in front is read as a creation — a false pair, loud, never a
  silent one; a hand-written operation that places another `name=` before the
  call's own is misread; a `PREFIX`, route path or `tags=` list that is
  computed, or a router assembled in a file the census does not read, is
  invisible; a name changed after its creation is read by its old name; models
  outside `apps/` are not read. Rule 83 sees the assembled mounts, but only
  after the merge, when both apps are installed.
- **Rule 83 compares path patterns as strings**, not as the paths they match:
  a literal segment shadowed by another router's parameter (`/x/links/` beside
  `/x/{id}/`) is declared, not caught.
- **The archived tag link's remedy names a route that does not exist**
  (`route:djb_tag_link-restore`; a tag link is deleted, never restored). It
  did so under its old name too, and it is booked.
- **Attach owners are the platform's three.** A registry a product's own app
  joins to own an attachment kind is a later release's work.

## [2.4.0] — Every verb a noun needs is a mechanism it adopts, and the gate refuses the noun until it has the road

**A product met one cost this release closes: every verb its nouns needed —
archive, move, a version on update, bulk, history, duplicate, merge, import,
notes and files and tags — was invented by hand, per noun, and each noun
learned the rules late.** One product built archive alone across twelve apps
at three-quarters of a builder session each, and learned twice, late, that an
archived face reads and that the system actor is exempt; this template's own
first adoption by hand went green inside its app in ten minutes and never
green as a whole, because a new refusal code reds a table in `apps/core` a
product may not edit. 2.4.0 ships the noun-verb family: nine verbs as one seam
in `apps/core` that a noun adopts by declaring a marker, both doors for every
verb with the MCP twin derived, a house rule that refuses a noun carrying a
marker without the whole road it demands, the pattern book's grammar for the
face with four source-text rules under it, three platform apps that own
attachments and the import road, and — as a strategy — a golden example of
every verb on the scaffold noun and its worked face, fenced so that a product
copies the text between the fences and nothing else, proved by two drives that
copy it out, migrate it, judge it and drop it. The rest is what the same work
found, fixed: the loop now runs the drives a shell change reaches, a
population floor is an equality that names its members, and a plant may not
wear a name the tree serves. 2.4.0 is a minor by the owner's word, on the
precedent of the last two: rules 74 to 82 red a product until it adopts the
family — a noun that declares nothing pays nothing, and a noun that declares
a marker gets a red gate that names each road it lacks, never a wrong answer.
**Two changes on the wire are named plainly.** `Importer.natural_key` now
takes the actor — `natural_key(*, tenant, actor, row)` — so the preview looks
where the apply will write; a consumer importer written to the old signature
fails at preview. And a product's archive and restore routes take no body:
`invalid_body` left the eight archive and restore routes the template ships,
and a client that still sends `{}` is answered exactly as before. Three more
are additions a client may meet: `merge_survivor` (409) on deleting a survivor
that carries merged losers, where the database's protect used to surface as
`conflict`; `?archived=true` on a list answers `400` naming `show`, the
family's one parameter; and a noun may declare `act_doors` for a verb whose
door is mounted under another name.

### What a product does at the merge

1. **Adopt the family per noun, one verb per commit, from the golden
   example.** Each verb's recipe is a section of
   `.claude/skills/django-conventions/SKILL.md` § 16 ("Adopt archive in one
   commit" and its eight siblings), and the text a product copies is the block
   between `# golden: <verb> begin` and `# golden: <verb> end` in
   `apps/example/**` (a fence may name several verbs — `# golden: archive version move begin` — for a block they share). Prove the copy before you
   adopt it: `scripts/tests/test_golden_copy.sh --verb archive` (or any of
   the nine) copies the fenced blocks onto a throwaway noun, migrates it, runs
   the system checks and the copied test, and drops it;
   `scripts/tests/test_golden_copy.sh --all` runs the nine in one go.
2. **The gate names every road a marker demands.** A noun declaring
   `Archivable`, `Versioned`, `Movable`, `bulk_verbs`, `Mergeable`,
   `Duplicable`, `attachments` or an `importers.py` key is refused at
   `manage.py check --tag djb` until it carries the routes, keys, `Out` shapes
   and parameters `apps/core/verbs.py`'s `ROADS` table lists (`python -m quality.gate --explain 74`); no comment suppresses it. A noun that should
   not carry a road does not declare its marker.
3. **Declare `attachments` on the noun, inside its fence** —
   `attachments = ("notes", "files", "tags")` — and read notes, files and
   tag links through the three platform doors with `?subject=<kind>:<id>`. A
   noun that lists `tags` answers `tags` on its detail; there are no per-noun
   attachment routes.
4. **A `Duplicable` noun declares `Duplicate(copies=…, resets=…)` over every
   editable field, and its service fills every reset** —
   `duplicate_row(..., fill={...})` refuses a missing key — while the copy is
   cleaned under `invalid` before its one save. **Its key constraint is the
   model's own**, declared in `Meta` and checked by `core.E001`, so a fresh
   noun with constraints migrates from scratch.
5. **A `Mergeable` noun requires `Archivable`, re-points every foreign key
   into it through its owning app's `merge_repointers.py` or keeps it on the
   loser in `merge_keeps` with a reason**, previews a merge at
   `GET /<nouns>/{id}/merge/?into=`, and refuses `merge_survivor` on
   deleting a survivor with losers.
6. **A `Versioned` noun requires `version` in its update, move and merge
   bodies** and refuses `stale_version` with `current_version` and the
   remedy `self:reread`; every write on it lists `updated_at` (`python -m quality.gate --explain 76`).
7. **An archivable noun's other writes call `require_live`, and its archived
   rows are reached only through `.including_archived()` and
   `.archived_only()`** (`python -m quality.gate --explain 81`, `python -m quality.gate --explain 82`). The system actor is refused by the noun's
   `@refuses_system` policy pair; a workflow's maintenance act gets its own
   service and audit action.
8. **Record rule 63's classes at the fold.** Rule 63 now declares a ratchet
   class per finding class its runner emits, at `0` on the template; a
   product whose face has a backlog records the numbers the refusal prints
   under `ratchets:` in `quality/local/rules.yaml` and ratchets them down by
   territory, as rules 64 to 71 already work.
9. **Draw a face's road once, in `road.ts`, equal to the wire both ways**
   (`python -m quality.gate --explain 77`). When a noun gains a door before
   its face draws the verb, record `door-without-road` at the fold with the
   client regenerated — the rule reads the committed `frontend/openapi.json`
   — and lower it in the face rung; never valve the road. Construct every act
   from `frontend/src/screens/verbs.ts`, spell one word per verb in the
   noun's copy module, and keep the code's verb table equal to the book's
   fenced `verb-table` block (rules 78 to 80). Prove a copied face with
   `scripts/tests/test_golden_face.sh --verb archive` or
   `scripts/tests/test_golden_face.sh --all`; it judges the planted noun's
   findings only and prints what it saw on the real face without judging it.
10. **A `scripts/check.sh --loop` now pays for what a shell change reaches.**
    The always-on leg's third source, `touched`, runs every drive whose
    `# drives:` line covers a tracked shell file that changed since the fold
    point (a banked verdict is reused when the bytes match), and `sweep` runs
    on any shell change; an `apps/**`-only rung prints `touched 0` and pays
    nothing, and an edit to `scripts/check.sh` selects every drive that names
    it.
11. **Every population floor in `apps/conftest.py` is an equality.** A member
    above a floor is a `UsageError` naming the population and the undeclared
    member, and the apps-root population is declared by member name; a product
    declares its own members in `DJB_POPULATION_FLOOR_MEMBERS` and its counts
    in `DJB_POPULATION_FLOOR_ADDENDS` in `apps/conftest_local.py`. A drawer
    that under-declares goes red at the fold and at the full gate with the
    members named — the remedy is the sentence the refusal prints.
12. **A plant never carries a name the tree serves, or it says so.** The
    plant-collision census runs at the self-test's head and as the
    `plant-collisions` leg of `scripts/check.sh --loop` (`python -m quality.gate --plant-collisions`): every service, route, url_name, tool
    and event name under `quality/canary/**`, `quality/negative/**` and
    `scripts/tests/fixtures/**` is read against what the tree serves, and a
    collision is exit 2 unless the plant declares it on its first line —
    `# collides: <name> — <why it is the form under test>`. A test module
    that isolates a registry uses `apps.core.tests.isolation.isolated_apps`;
    a bare `isolate_apps` is refused.
13. **CI's self-test shards install the frontend toolchain** by the fe leg's
    own function, on every row of the legs job, so a drive that reads
    `frontend/` looks where the train measures. The workflow is
    template-owned; a product's CI steps stay in `scripts/local/ci/`.
14. **A new platform app touches five pinned shared surfaces** — rule 32's
    label paths, `FROZEN_FAMILIES`, `quality/partition.yaml`'s
    `platform_apps`, rule 41's example budget rows, rules 42/54's ratchet
    class — and `platform_apps` is held closed by a `@template_shape` census
    a product retires with `platform_apps=own`.

### Added

- **The family's seam in `apps/core`.** `core.verbs` (the declared markers per
  model, `allowed_acts(actor, row)` as the server's answer per row — offered
  only where a door exists — `resolve_subject`, `require_live`, the `ROADS`
  table), `core.blockers` (a closed walk over each app's
  `<verb>_blockers.py`), `core.bulk.run_bulk` (ordered per-item outcomes in
  one transaction on both doors, a refusal audit row per refused item, a retry
  converges), `core.concurrency` (`version_of`, `require_version`), the
  refusal grammar with `wire_extra` carried byte for byte on REST and MCP, and
  the `Repointer` and `Importer` dataclasses.
- **Nine verbs on the worked noun and its face.** `Widget` is `Archivable`,
  `Versioned`, `Movable`, bulk-archivable, historied, `Duplicable`,
  `Mergeable`, an attach subject and an import kind; `frontend/src/screens/widget/`
  draws every road — the archive band and the *Archived* cut, the edit sheet
  whose lost race is answered by *Reload*, the move sheet, the selection bar
  and its per-batch band, the History card, the duplicate band, the merge
  chooser and its one confirm, the Notes and Files cards and the tag row, and
  the import page that walks choose, checking, previewed, importing and
  imported. Every block a product copies is fenced by verb.
- **Three platform apps.** `apps/notes` (a note against any noun declaring
  notes; only its author edits), `apps/tags` (a tenant-wide word and its
  org-scoped link; `create_tag_link` idempotent), `apps/imports` (stage, check,
  preview, apply; idempotent by the file's digest and per row; `Import` purged
  after thirty days). Each is registered by discovery, each answers REST and
  MCP byte for byte, and the two attach owners plus the files app each declare
  the `"*"` merge repointer.
- **Rules 74 to 82.** 74 a noun carrying a marker carries the marker's whole
  road; 75 no model is both append-only and archivable; 76 a versioned write
  moves `updated_at`; 77 a noun face's road equals its wire; 78 a family act
  is constructed, never spelled; 79 one word per verb; 80 the verb table
  equals the book's; 81 the archive's widenings are the only widenings; 82 a
  write on an archivable row calls `require_live`. Each ships with canaries,
  negatives and — for 77 to 80 and 82 — ratchet classes at zero.
- **The ratchet headroom reader.** For every rule that declares `ratchets:`,
  a class recorded above its count on the tree is a red naming the file to
  lower it in, judged on the template's own shape only and said aloud on any
  other; before it, a recorded number above a count was a note for every
  rule.
- **The golden drives.** `scripts/tests/test_golden_copy.sh` copies a verb's
  fenced blocks onto a throwaway noun under `DJB_DISABLED_APPS=example`, reads
  the road's last route from the road itself, refuses a fragment that lands
  after a `return` in the copy, prints its census on a failing step, and
  proves its own self-case against an empty scratch source rather than the
  real app; `scripts/tests/test_golden_face.sh` copies the worked face one verb
  at a time against a planted wire, runs rules 77 to 80, the typecheck and the
  face census on the copy, learns a fence a block several verbs own jointly
  (`// golden: bulk+merge begin`, copied only when every listed verb is in
  the copy), and reds its negative on rule 77.
- **The pattern book's verb grammar.** The five seats, the fenced `verb-table`
  block, one press unless there is no one-press undo (merge's one confirm,
  import's preview), the refusal under the act's row with a `route:` remedy
  drawn as a live door through the route table, the landing rule for a
  restored cut row, and a face's own token-only stylesheet with one
  breakpoint in range syntax.
- **`?can=<key>` on the organizations list** narrows it to the nodes the
  actor may move a row into, on both doors; page-level `allowed_acts` carries
  `create`; `?show=live|archived|all` on every archivable list; the per-row
  history road (`<noun>_history-list`) over the audit rows, on one
  concurrently built index.

### Changed

- **`Importer.natural_key(*, tenant, actor, row)`** — the actor is new, and the
  preview resolves under the acting hat exactly as the apply does.
- **Archive and restore take no body** on every noun the template ships; the
  `?archived=` boolean the two hand-built halves took answers `400` naming
  `show`.
- **`@refuses` narrows exactly as shipped and `@also_refuses(*codes)` widens**
  the derived set; the refusal pin is partitioned, so a product's own code is
  admitted by its declaration while the template's table stays typed.
- **An event payload never carries a per-viewer field.** `allowed_acts` rides
  the two viewer doors; the outbox payload is the `Out` minus
  `PER_VIEWER_FIELDS`, and `emit` refuses a payload carrying one at any depth.
  Existing payloads are byte-identical to what shipped before.
- **The tenant export keeps archived rows** for every archivable noun the
  census carries, with `archived_at` and `archived_by`.
- **The population floors are equalities** and the always-on leg runs the
  drives a shell change reaches — both a price a rung now pays and the
  refusal prints.

### Fixed

- **A hand `archived_at` filter after `for_tenant` answered live rows only**
  with no error — the manager hides first; the two hand-built adopters now
  use the widenings and rule 81 holds the shape closed.
- **A test registry left the real user model's relations rewritten** for
  every module collected after it, under one seed in twelve — an isolation
  helper clears the cache on exit, a teardown guard names the module that
  breaks it, and a census refuses the bare form.
- **The duplicate seam saved before the service could fill a non-null
  field**, a unique constraint over copied fields was a 500, and a duplicable
  noun with constraints could not migrate from scratch.
- **A repointer refused a mergeable noun that takes no attachments**, and a
  merge's blocker door was composed by hand rather than read off the mount.
- **The golden-copy drive's self-case appended its fixture into a copy of the
  real app** and died the day the app grew the same fence; its non-vacuity
  step deleted a route by a hand template the history road did not fit; a
  fenced line landed after a `return` as dead code and went green; a failing
  step died under `pipefail` before printing its census.
- **Three train reds in one day followed seven green loops each**: a drive
  that changed in the rung and whose self-case no loop ran; a population one
  above a floor no loop re-measured; a canary named after the example's
  future that the example grew into. Each is now an instrument.
- **The ratchet headroom reader judged a consumer-shaped clone against the
  template's rows** and exited 2 under enforcement broken with no rule line
  carrying it; it now reads the judged shape once.
- **The golden face drive could not look on CI** — no shard installed the
  toolchain every verifier box had — and once it could, it read the whole
  frontend as a second gate with a stricter opinion; it judges its copy.
- **Six stale valves came out** once rules 41 and 17 learned the family's
  shapes (the second hop into `core.verbs`, imported bases); one valve stays
  with its reason corrected, because rule 41's reach stops one hop short of a
  service's own helper.
- **A refusal's sentence carried a machine token**, and three refusals
  published a remedy the wire did not send; the registry now holds each remedy
  with a noun slot that the class and the published document fill from one
  declaration.
- **The selftest leg's drive** clears every `DJB_SELFTEST_*` it did not set;
  the loop's subshell case reads its pid without `BASHPID`, so the Mac loop
  runs end to end again.
- **A second approve appended a second ledger line** on the worked noun; the
  contract says it changes nothing, and now it does not.
- **`membership_for` reads the memberships the actor already caches**, so
  every adopter's list is flat in rows on both doors.

### Known

- **A narrowed self-test can be short and say nothing**: a rule whose canaries
  ride another rule's plant reports short when run alone.
- **The self-test leg's partition is blind to its heaviest members**: a member
  whose duration row is written under another name, or never written, is
  predicted at the median.
- **Main's post-merge run re-measures a tree the pull request's run already
  banked.**
- **The verifier box's loop does not forward the no-cache switch.**
- **The loop is blind to the residence census**: rules 81 and 82 each keep
  one form in the probe scaffold so the recorded backlog stands, and no loop
  runs the census that would say so.
- **Rule 41's narrowed self-test is not self-contained**, and its reach stops
  one hop short of a service's own module-local helper — the one valve kept.
- **A rule that reads the committed contract document is blind to a door
  until the fold** regenerates the client; the ratchet row is recorded at the
  fold for that reason.
- **Rule 6 reads a migration's file name** for the word it refuses.
- **A ratchet refusal sends the template's own writer to the drawer** rather
  than to the template's file.
- **An input a verifier box has and a CI shard does not is invisible to every
  loop** until each drive declares what it needs and the shard installs
  exactly that; the frontend toolchain was the first.
- **Seven wire gaps the worked face found while drawing the last verbs** —
  from the merge preview's sentence to the import run's progress — are the
  next cycle's; the face draws what the wire gives.
- **A merge to a tenant-wide survivor re-lands links at the merging actor's
  hat**, and the tenant-wide one-per-pair constraint answers `conflict` to a
  second branch's press.
- **A hard-deleted attach subject leaves orphans** until a purge reacts to
  its deleted event; the first product that hard-deletes a subject is the
  trigger.
- **Restore-a-version is not built**: the audit rows carry no field values,
  so history shows what was sent, never what differed.
- **The history clause's population is deliberately narrower than "any
  marker"**: an archive-only noun owes no history route.
- **A fragment after a call that never returns** (`assert False`,
  `sys.exit`) is not seen by the golden drive's placement step.

## [2.3.0] — A product's first face meets a floor it set, and a train pays for one measurement

**A product met two failures this release closes: two verifiers passed a
face that broke a written design rule, because the rule had no test to fail;
and a train was measured two or three times per tree, the push to main
re-running every leg on bytes CI had already measured.** 2.3.0 puts an
instrument under every design rule a face is held to and makes the pattern
book the one place those rules are written; it measures a train once, on CI,
and lets the push to main consult that verdict instead of measuring again;
and it adds a deploy road that promotes to production only what staging
proved and a nightly proof has vouched for. The rest is what the same work
found, fixed. 2.3.0 is a minor by the owner's word, on the precedent above.
Under the literal convention three items lean major: rules 61 and 62 red a
product's compose and workflow files until they are edited, rules 63–73 red
an existing `frontend/src/` until it adopts the floor, and the test store's
credential moved to one authority. None is a wire break — no app, model,
migration, service, door, event or workflow was added or changed — and the
two command changes are refusals that print their remedy. The house rules
red a product until it adopts the floor — the owner's ruling of 2026-09-26;
a product that merges and does nothing gets a red gate that names each site,
never a wrong answer.

### What a product does at the merge

1. **Every `image:` in your `compose.yaml` and `deploy/compose.yaml` carries
   `@sha256:<64 hex>`** of a multi-arch index from `docker.io`, `ghcr.io` or
   `docker.hyperdx.io`, or `# pin-exception: <reason>` on or above the line
   (`python -m quality.gate --explain 61`). To re-pin, edit the digest and
   transcribe `docker buildx imagetools inspect <ref>` showing both
   architectures; no tool does this for you yet.
2. **In every workflow job, each `run:` step after
   `aws-actions/configure-aws-credentials` sets `AWS_ACCESS_KEY_ID`,
   `AWS_SECRET_ACCESS_KEY` and `AWS_SESSION_TOKEN` in its own `env:`** (an
   empty value is a pin) or carries `# creds: <reason>`
   (`python -m quality.gate --explain 62`).
3. **Delete every NON-EMPTY `AWS_*` value your workflow `env:` supplies
   for a key `config/settings/test.py` pins.** That file is the one
   authority for the test store's credential, and the ci-env census reds a
   key with two authorities, naming the settings line and each workflow
   line by `file:line`. The EMPTY pins rule 62 asks for stay: an empty
   value clears a name and supplies nothing, and the census prints each one
   as a pin, not a supply.
4. **Before your first rung under `frontend/src/` — or at the merge, if
   your tree already has one — run the DESIGN stage:**
   write entries in `docs/product/design/patterns.local.md` in the book's
   six-part form, each naming an instrument that exists. Rules 63–73 red
   every off-scale stylesheet size, gap and motion, a missing focus ring, a
   disabled control, a toast or spinner, a second dialog, an unrowed page, an
   off-lexicon label and a machine token in copy until you adopt the floor. A
   finding in a `.css` file has no valve; the remedy is a token.
5. **The template's `ci.yml` — template-owned; a product's CI steps go in
   `scripts/local/ci/`, `docs/product/build-contract.md` § "The drawers" —
   asks the gate for its units**
   (`scripts/check.sh --list-legs --ci`), runs pytest one pass, consults
   before measuring a push to main, publishes a `gate-verdict-<attempt>`
   record, and adds `deploy-staging` (skipped with a notice unless
   `vars.DJB_STAGE_TARGET` and `vars.AWS_DEPLOY_ROLE_ARN` are set) and
   `deploy-prod` (by dispatch; it refuses without its variables).
6. **`.github/workflows/ci.yml` and `.github/workflows/nightly-proof.yml`
   are template-owned** — an edit to either is a divergence. Every other
   workflow file is yours.
7. **Push a train from a `pm/*` branch as `scripts/pm_push.sh --pr`** with
   `DJB_GATE_SANCTION="<who>: <why>"`, bank its CI run with
   `scripts/pm_push.sh --ci-verdict`, then a plain `pm_push.sh` fast-forwards
   main and is honoured without measuring again. `scripts/pm_push.sh --bank`
   remains the fallback, and CI re-measures what it pushes.
8. **`scripts/gate_member_durations.ci.json` is a derived file** your fold
   rewrites from your latest green CI run; never edit it by hand.
9. **A production deploy now refuses (exit 2, nothing touched) unless it is
   typed in full** —
   `deploy/stage.sh <box> --env prod --sanction '<who>: <why>' --staging <dest> --nightly <dir>`
   — with staging's `TREE` on this tree, staging's readyz answering 200, and
   a green nightly no older than 24 h.
10. **`scripts/verifier_box.sh loop` refuses a box holding another tree** —
    run `scripts/verifier_box.sh push` with the box's id first. A rung that
    changes only `TEMPLATE_VERSION` or a `*.md` now runs the tests that quote
    it, and the full bank's pytest runs once more under the least-privilege
    grants role.
11. **Your shell drives' red members print up to ten FAILED lines, and a
    killed member's transcript reaches the shard log;** the merge line splits
    "not recorded by any loop" from "red or absent".
12. **A product test module that reads a registry no token names is made
    always-on by declaring a reach kind** in `apps/conftest_local.py` —
    `DJB_REACH_KINDS = {"<kind>": ("<token>(",)}`. An unknown `DJB_*` key in
    that drawer is a `UsageError`; a drawer kind that reuses a template
    kind's name is refused, naming both files; and a declared kind that no
    module reads fails its floor of one.

### Added

- **The pattern book, its drawer and the DESIGN stage.**
  `docs/product/design/patterns.md` holds one shape per element class, the
  scales every face is held to and the instrument index; a product's entries
  go in `patterns.local.md` beside it. Rule 63 refuses an entry whose
  instrument does not exist and a face that declares no entry.
- **Rules 64–73, the floor.** Stylesheet sizes, gaps and motion on the
  scales; a focus ring on every pressable class; nothing disabled; no toast,
  spinner or shimmer; one dialog primitive
  (`frontend/src/primitives/dialog.tsx`) whose foot carries no dismiss word;
  every page in the route table (`frontend/src/screens/routes.ts`); every
  label a lexicon row (`frontend/src/copy/lexicon.ts`); no machine token in
  copy. The scaffold adopts the floor.
- **Rules 61 and 62.** Every compose image is pinned by digest or carries a
  reason; every workflow step after the AWS credentials action pins or
  justifies the credential it inherits.
- **Trains measure once.** `scripts/check.sh --list-legs --ci` prints the
  units CI runs; a member-walls table is measured on CI and the fold rewrites
  it; CI's run publishes a `ci:` verdict that the push to main consults, and
  `scripts/pm_push.sh --ci-verdict` banks it locally.
- **Deploy by promotion.** `deploy-staging` runs on a push to main;
  `deploy-prod` runs by dispatch and deploys only the tree staging proved; a
  migrate wall runs before the swap and psql runs by digest; the deploy
  runbook gains its CI part and both OIDC `sub` spellings.
- **The nightly proof.** `.github/workflows/nightly-proof.yml` runs the
  whole suite twice under one seed (`scripts/pm_push.sh --proof`) as a
  record the production deploy and the bank read; a green night on another
  tree is said rather than taken.
- **A drawer-declared reach kind** (`DJB_REACH_KINDS` in
  `apps/conftest_local.py`), and the door-registry reach kind with its own
  floor.

### Changed

- **A production deploy refuses** without its sanction, the staging tree, a
  staging readyz of 200 and a green nightly no older than 24 h; a dispatch
  never cancels one already in flight, and every environment not listed as
  staging is treated as production.
- **CI's pytest runs one pass**; the `ci:` row says `pytest-x2/1`, and the
  second whole pass is the nightly's record.
- **The test store's credential has one authority**,
  `config/settings/test.py`; a workflow `env:` that sets it too is red.

### Fixed

- **A queryset write through a binding or a helper is seen by rule 20**, and
  the full bank's pytest runs once more under the least-privilege grants
  role.
- **The loop tells the truth about what it ran.** A changed
  `TEMPLATE_VERSION` or `*.md` seeds the modules that quote it; a dead run's
  re-take is remembered and every write is renamed into place; a rule that
  could not look says so; a stale map id is named; no reader ends a pipeline
  in `grep -q`; the verifier-box drive's fork point falls back to
  `origin/main`; two tests fix their own clock.
- **`scripts/verifier_box.sh loop` refuses a stale box by name**, a red
  member's FAILED lines reach the log, the drives line splits the unrecorded
  from the red, a killed member's transcript reaches the log, `wait` prints
  every RED block, and an ignored signal is said.
- **The publish census places the pattern book** (the design directory is
  shipped), and the divergence census owns the book as the template's, so a
  product's edit to it is a divergence and its drawer is not.

### Known

- **The re-pin road has no instrument.** A digest re-pin is transcribed by
  hand from `docker buildx imagetools inspect`; nothing checks that the new
  index carries both architectures.
- A sign-in door test's passkey case failed once on a throwaway tree and has
  passed on every run since; it is recorded and waits for a second sighting.
- A verifier box's owner tag is read from the checkout's ledger header, which
  a worktree carries as a stale copy, so the tag can name a session that has
  ended.
- Rules 67 and 68 each hold the walk that decides which classes are
  pressable, rather than sharing one.
- A loop over a verifier box whose test databases predate it is not refused
  yet.
- No census yet refuses a test that writes under `apps/`.
- The front end's tier B and tier C instruments are not in this release.
- An inbound webhook whose signature fails writes no receipt saying why; a
  sign-in door test that asserts a number is absent from the whole page can
  meet it inside a random CSRF token; the bank's acceptance box can be
  reclaimed by Spot at the end of a run; a ten-box bank still takes far
  longer than its tests; and a product extends the allowed upload content
  types only by editing a template constant.
- The always-on leg — the leg a `--loop` runs — still loses a killed
  member's transcript and leaves its capture file, because its runner has no
  kill trap; the selftest leg's fix is the road, and it lands as the next
  instrument change.
- Rule 70 fires on `Done` as an act label in a dialog's foot — a valve, by
  design.
- Rule 69's `loader` word catches data-loading hooks such as `useLoader` — a
  valve, by design.

## [2.2.1] — A fresh clone and CI pull the files store again

MinIO archived its open-source project and withdrew every public image, so
the release `compose.yaml` pinned no longer pulls from any registry: a fresh
clone's `./scripts/setup.sh` stopped at its pull step, and every CI leg died
at `docker compose up`. One fix, a patch: the pin moves, the release does not.

### What a product does at the merge

1. **If your CI sets `AWS_ECR_ROLE_ARN`, grant that role the
   `ecr-public-login` policy before your next run** — the command is
   `docs/runbooks/deploy.md` step 5b. Without it the new login step fails and
   every leg is red before the stack starts. A CI with no such variable pulls
   anonymously, and can hit ECR Public's anonymous data limit under a full
   matrix.
2. **If your `compose.yaml` carries your own MinIO pin**, keep it or take this
   one; `scripts/tests/test_setup_env.sh` asserts this one by digest.

### Fixed

- **The files store pulls again, on a laptop, a fresh clone and CI.**
  `compose.yaml`'s `minio` service names the same release from the owner's ECR
  Public mirror, pinned by digest, with `platform: linux/arm64` — the only
  architecture any surviving copy holds. A Mac or an arm64 host runs it
  natively and pulls it anonymously. CI's `legs` job, on amd64 runners,
  registers the arm64 QEMU handler and logs in to ECR Public before the pull,
  and `scripts/tests/test_setup_env.sh` refuses a compose-up job that does
  neither. After that login the CI legs still talk to the compose store with
  its own credential: the gate step re-pins the store's key pair and empties
  `AWS_SESSION_TOKEN` over the AWS credentials the login exports, and the
  same test refuses a gate step that inherits them.

## [2.2.0] — A product merges the tag and banks green the same day

**At its last fold a product needed three template releases to reach a green
bank, skipped template drives it could not pass by name, and lost a bank to
a hang the template caused.** Each was a form, a drive or an instrument that
was live only on the template's own shape. This release closes that class:
the template's bank now judges every rule's forms on a consumer-shaped tree,
a plant that could land on a product's own file is refused before anything
is planted, and a cancelled activity no longer dies holding the import lock
a test worker needs. The rest is what the same fold found, fixed. 2.2.0 is a
minor by the owner's word, on the precedent above: the census changes what a
drawer may declare and the bank now judges every rule on a consumer-shaped
tree, so each gets a version boundary and a note below rather than riding in
as a patch.

### What a product does at the merge

1. **A plant in your drawer declared `mode: create` sits under a
   `zzz_canary` directory**, beneath the layer it proves, or carries
   `namespace_exempt: <reason> (MOVE-TRIGGER <date>)` naming why that path
   can never be a product's. Anything else is refused at exit 2 before
   anything is planted, naming the rule, the fixture and the path, with
   both remedies printed; `python -m quality.gate --explain <id>` prints the
   reserved segment once. Exempt without a declaration: a `mode: default`
   plant (it creates only where nothing is) and anything under
   `apps/example/`. A declaration is refused as vacuous under `zzz_canary`,
   on a `default`, or under `apps/example/` — remove it. Two more refusals
   come with the census: a plant `mode: absent` naming a path neither your
   tree nor any form plants is could-not-look on its rule's line, never a
   silent no-op; and a canary may not declare `needs_shape:` (only a
   negative may declare the shape it needs). A declaration on a plant that
   creates nothing (`append`, `replace`, `absent`) is refused as exempting
   nothing.
2. **Nothing to type for the bank's widened reach.** The template's bank
   now judges every rule's forms on a consumer-shaped tree — a root page, a
   token sheet, `frontend/app/env.ts`, a barrel with its drawer ratchet and
   a base declared through the `template` remote — so a release that reaches
   you has been measured on that shape. The shapes drive is safe on your
   checkout: it tags a synthetic release name, and plants each product file
   only where your tree has none. One behaviour to know: rule 60's
   base-planting forms are now COULD NOT LOOK (exit 2) on any tree with an
   uncommitted edit to a template-owned path, a product's tree included,
   unless your `architecture.md` names the path as a divergence, in which
   case it is subtracted, not refused — commit or stash before running the
   self-test. This supersedes 2.1.6 item 3's "on the template's own tree
   only".
3. **A cancelled synchronous activity now runs to its declared timeout
   instead of being interrupted mid-thread, and a worker's shutdown waits
   for in-flight activities up to that timeout.** Your own activities are
   held to the same by a census over `discovered_activities()`: add
   `no_thread_cancel_exception=True` to each synchronous `@activity.defn`,
   or the test names the function (an `async def` activity is cancelled as
   a task, and the census leaves it out). The worker derives its shutdown
   window from the timeouts your workflows declare at their call sites, so
   a timeout there that is not a module constant, a dotted attribute or a
   literal `timedelta(...)` makes `build_worker` refuse with
   `ImproperlyConfigured`, naming the `file:line` — declare it as a
   module-level constant.
4. **A leg that rewrites a tracked file declares it in the
   `derived-tree-paths` block of its own file.** A `--loop` that finds a
   tracked path changed during the run that no declaration covers banks
   nothing, exit 2, and names every path with the arm that named it. A hand
   edit during a `--loop` is now the same exit 2 (it was exit 0 with no
   row): the run cannot tell your edit from a leg's re-take. A refused run
   remembers the bytes it refused, so re-running on the same bytes is
   refused again and `touch` clears nothing. What clears a path: commit it
   or `git checkout --` it, change its bytes, or — for a leg that re-takes
   it on every run — declare it in that leg's block.
5. **A module under `apps/` or `config/` that quotes a docs path it never
   opens says so on one line** — `# names, never reads: <path> — <why>` —
   or the docs-only push road refuses the push, naming the quote at its
   `file:line`. Test modules are where the quotes usually are, but the
   declaration is read for any module in those two trees.
6. **`setup.sh` now writes the derived database name over an unmarked
   `DATABASE_NAME` pin in `.env`, and prints what it overrode and where the
   value came from.** A `# pinned` line directly above the pin keeps it,
   and the marker now survives setup's rebuild of `.env` (before this
   release the rebuild dropped it).
7. `compose.yaml` (shared, adjudicated by hand — build-contract.md's
   ownership table): take the `shm_size` line into your `db` service, or
   keep your own if larger; an override file that redefines `db` inherits
   it unless it sets its own. Your running stack keeps 64 MB until you run
   `docker compose up -d db` with nothing running against it.
8. **Your gate units' rows live in your `build-contract.local.md`**, and
   the listing case reads the template's table and that sibling as one. Once
   you have a drive of your own, your sibling carries the whole `selftest`
   row, so a fold that adds or drops a template drive reds that case until
   you re-paste the row — the red prints the exact row. Spell the file bare
   in prose: the dangling-docs census exempts only
   `docs/product/instruments.local.md`.
9. **Remove the named skips you carry for template drive cases —
   twenty-six of them now run on your tree.** On a product's tree (one whose
   `quality/local/rules.yaml` declares `rule_id_namespace`), three
   `test_gate_explain` cases are the template's own — the namespaced-id
   refusal, the no-product-rules wall and the self fold-map. They skip with
   a counted, reasoned line (`K skipped` on the drive's summary line, the
   reasons under it), in the same sentence the Python suite's template-only
   skip prints, and a skip never changes the exit code. The other 26 cases
   a product used to skip by name now derive their expectation from the
   tree (the rule listing counts the drawer, the no-drawer baselines point
   at an absent drawer, the buildx step is found by what it runs), so
   remove those named skips at this fold. Three cases that depend on your
   tree's content (a barrel with rule-52 findings; backlog lines) may still
   need your named skip. A drive's own `skipped` count that means "this
   machine cannot pose the case" is a different kind of skip and stays.
10. **Your drawer's fixtures are excluded from ruff; its runners are not.**
    `quality/local/canary/**` and `quality/local/negative/**` are now
    excluded from ruff like the template's own fixtures; your drawer's
    runners (`quality/local/runners/*.py`) are real code and stay linted.
    `pyproject.toml` is shared and adjudicated by hand, so if you already
    carry your own exclude, keep the union; if you added it as a declared
    divergence, you can drop that line. The exclusion applies to the hook's
    `ruff check .` form: an editor that passes a filename without
    `--force-exclude` still lints it.
11. **Rule 60 now sees your edits under the template's platform apps, so
    expect it red at your first gate after the fold.** Rule 60's census has
    been blind to edits under the template's platform apps (`apps/<name>/**`
    for each name in `quality/partition.yaml`'s `platform_apps`), because it
    matched a one-name-per-line list space-delimited. From 2.2.0 it sees
    them. Every path you changed there since your base will therefore report
    as an UNNAMED divergence, and rule 60 will be red (exit 1) at your first
    gate after the fold. It stays red until each path is declared in your
    `docs/product/architecture.md` as `divergence: <path> — <reason>`,
    moved into a drawer, or upstreamed. Nothing in your tree changed, only
    what the census can see.

### Added

- **The plant-namespace census.** Every `mode: create` plant, template or
  drawer, sits under the one reserved segment, in `apps/example/`, or
  declares `namespace_exempt: <reason> (MOVE-TRIGGER <date>)`; the
  self-test's head counts the population, and `--explain` prints the
  reserved segment.
- **The whole-run shapes drive.** Under a sharded bank the drive runs the
  engine's whole self-test on the consumer-shaped tree as a shard-balanced
  member of its own; on a laptop `--loop` or `--fast` it never does.
- **`needs_clean_tree:` on a rule 60 form** — a closed word declaring the
  clean tree the form needs; a tree that is not clean is could-not-look,
  never a lowered floor.
- **A drawer-raised population floor.** `DJB_POPULATION_FLOOR_ADDENDS` in
  `apps/conftest_local.py` adds to a typed floor such as
  `apps_root_modules`; one reader, beside the floors.
- **The `derived-tree-paths` clause for legs** — the declaration a fold
  step already used, now read for a leg that re-takes a tracked file.
- **The docs-only quote declaration** — `# names, never reads: <path> —
  <why>` in any module under `apps/` or `config/`.
- **The `.local.md` unit-table sibling** — `build-contract.local.md`, read
  with the template's table by the listing case.
- **The sync-activity census** — every synchronous callable in
  `discovered_activities()` declares `no_thread_cancel_exception=True`;
  an `async def` activity is outside the question by design.
- **A drawer's fixtures are excluded from ruff.** `pyproject.toml`'s ruff
  `extend-exclude` gains `quality/local/canary` and `quality/local/negative`
  — a product's deliberately wrong fixtures, excluded as the template's
  own are; the drawer's runners stay linted.
- **The counted `template_only` skip for drive cases.** A case that asserts
  a property only the template's own tree has opens with `template_only
  "<why>"` (`scripts/tests/drive_preamble.sh`): it runs on the template,
  and on a tree that declares `rule_id_namespace` it skips, counted on the
  drive's summary line with its reason, never changing the exit code. A
  case that calls it with no reason, or on a tree whose namespace the
  engine cannot read, is could-not-look.

### Fixed

- **A cancelled synchronous activity could die owning importlib's module
  lock and hang a test worker.** The exception Temporal delivers
  into a running thread on cancellation could land inside an import; it is
  no longer delivered, and `build_worker`'s shutdown now waits up to the
  longest declared activity timeout instead of cancelling everything at
  zero seconds — which was also wrong in production, where a stop signal
  cancelled running deliveries instantly.
- **The two-pass verdict quotes pytest's own summary.** It had also quoted
  captured-log lines that happen to begin `ERROR`, and it no longer claims
  the two passes had an identical worker assignment: the seed fixes the
  collection order, and the assignment is timing-dependent.
- **The fork point travels with a verify clone.** The clone records the
  fold point it was built on, the box push prefers a recorded fork point
  over its own derivation and refuses rather than pushing an empty one, and
  the verifier-box territory case reads the carried point first and skips,
  counted and named, on a change that does not own that territory.
- **One `.env` pin resolver** for `setup.sh`, `rung_start.sh` and the
  db-pin leg, where there were three decision tables that disagreed; the
  pin note no longer lands in `./scripts/check.sh --list-legs`, whose
  output is the unit table.
- **A drive's key is decided at the hook.** The fast tier keys every drive
  a change touches and refuses in the self-test leg's own sentence, naming
  every uncovered path in one line rather than the first.
- **`shm_size` on the compose db service.** Docker's default 64 MB
  `/dev/shm` fills with Postgres's cumulative-statistics area as databases
  accumulate, and then new connections and queries start failing;
  `compose.yaml` carries the value and the reason.
- **Twenty-six template drive cases no longer assert the template's shape
  on a product's tree.** Each typed an expectation only the template's own
  tree meets, so a product skipped it by name; each now derives it from the
  tree it runs on — the rule listing counts the drawer's rules, the
  no-drawer baselines point at a drawer that is absent, and the buildx
  step is found by what it runs rather than where it sits.
- **Two drive readers no longer red the sweep's presence probe.** Two lines
  that ended a `pipefail` pipeline in `grep -q` stopped reading at the
  first match, so the pipeline could fail under the writer; they now read
  to the end of their input, with the output redirected.
- **The divergence census sees a product's edits under the platform apps.**
  Its platform-app test matched a one-name-per-line list as if it were
  space-delimited and never matched, so every edit under a platform app
  was owned `product` and rule 60 was blind to it; the match is now
  newline-delimited, and a drive case with the real `partition.yaml`
  proves a committed edit under `apps/core/` is a divergence (item 11
  above says what that means at your fold).
- **The self-test's riders.** A census exit 1 is labelled a finding, not a
  cause it has not proven, and the closing line counts a form not
  producible on this shape; the shapes drive reports an engine that judged
  nothing as its own exit 2; a whole run is never reused from a banked
  green, and the drive's key covers a product's `frontend/`; the COULD NOT
  BANK sentence names each path's arm and the escapes that actually clear
  it.

## [2.1.7] — A form declares the shape it needs, and the bank judges the consumer's shape

**A product whose base is declared through the `template` remote, or whose
frontend has its own root page, still had a self-test that exited 2 on its
own tree after 2.1.6.** Rule 51 planted a form onto `frontend/src/app/page.tsx`,
which every Next product has, and rule 60's no-base control fired on a base the
remote declares. This patch moves the one and has the other say it cannot be
produced on that shape.

### What a product does at the merge

1. If a plan in your drawer (`quality/local/rules.yaml`) spells a plant
   `mode:` outside `create · append · replace · default · absent`, change it —
   2.1.6 refuses any other word at exit 2 before anything is planted. `write`,
   the word a product's plan was found carrying, maps to `create` on a path
   your tree does not have and to `replace` on a path it has.
2. Nothing else to type. `python -m quality.gate --selftest` on your tree now
   exits 0 where 2.1.6 exited 2 on rule 51's plant and rule 60's no-base
   control, and its second line names a remote-declared base as
   `v<version> (from the 'template' remote, derived from TEMPLATE_VERSION)`.

### Fixed

- **The engine's self-test plants rule 51's forms where no product's own file
  can be, reads a template base declared through the `template` remote as the
  shape it is and spells that base on its second line, takes `--rule <id>` for
  a narrowed run, and a drive at the bank now judges rules 51 and 60 on a
  consumer-shaped tree.** Rule 51's `create` forms plant under a `zzz_canary`
  directory beneath the layer each proves, so a product's own
  `frontend/src/app/page.tsx` is never refused as a plant site. A form may
  declare the shape it needs (`needs_shape: template` — no base declared);
  on a tree that declares a base anyway, through the `template` remote or
  `DJB_TEMPLATE_BASE`, which a plant cannot take away, the form is printed on
  its rule's line as `not producible on this shape`, with what the tree
  declares, and counted at the foot — never read as a control that fired.
  `python -m quality.gate --selftest --rule <id>` (repeatable) judges only the
  named rules' forms and says it is not the gate's verdict; the gate's own
  selftest leg never takes it.

## [2.1.6] — The engine's self-test judges every form on a consumer's shape

**A product that folded the template had a self-test that could not pass on
its own tree.** The engine's canaries and negatives were live only on the
template's own shape: a paid backlog, a real barrel or a declared base turned
a canary dead or a control loud, and the selftest leg carries the engine, so a
folded product's full gate exited 2 by construction. This patch judges every
form by the change it makes, keeps a plant off a product's own files, and
reports a refused instrument as what it is.

### What a product does at the merge

1. Nothing new to type. `python -m quality.gate --selftest` on your tree
   reads your declared base, says which shape it judged on its second line,
   and exits 0 where 2.1.5 exited 2 on the two dead canaries and the three
   firing controls.
   **Corrected 2026-09-22:** not true on every product. A drawer plan that
   spells a plant `mode:` outside the vocabulary is refused at exit 2 — map
   it as item 1 of the next release says (`write` is `create` on a new path
   and `replace` on a path the tree has); and on a tree whose base is declared
   through the `template` remote, or which has its own
   `frontend/src/app/page.tsx`, this release's self-test still exits 2 —
   fixed in the release after this one.
2. The twelve template-only drive cases named at 2.1.5 still skip as named
   divergences, and one more joins them: the loop-scope case that moves an
   `apps/test_*.py` aside expects the template's typed count of those
   modules; a product with one more has no drawer to raise it yet.
3. On the template's own tree only: commit before running the self-test
   (the last sentence of the entry below says why).

### Fixed

- **The engine's self-test now judges every planted form by the change it
  makes, refuses to plant over a file that exists, reports a refused
  instrument as could-not-look, and holds rule 60's controls on a tree that
  declares a template base.** On a folded product, `python -m quality.gate
  --selftest` read a canary as dead when the product had paid down a backlog
  or kept a real barrel, overwrote the product's own files and declared base
  while planting, and scored a refused runner as dead canaries and silent
  negatives. Each form is now judged on the findings it adds to the tree
  as it stands; a plant onto an existing path is refused unless the plan says
  `mode: replace` (the vocabulary is `create · append · replace · default ·
  absent`); a form nobody could judge is printed on its rule's line as
  `COULD NOT LOOK (<cause>)` and counted at the foot; and the transcript says
  which template base it judged against before the first plant. Nothing for
  a product to do at the merge. On the template's own tree, commit before
  running the self-test: an uncommitted edit to a template-owned file now
  reads as a false-positive regression on rule 60's drawer control, naming
  that file, because the control plants the checkout's own `HEAD` as the base;
  on a product's tree the same edit is already in the unplanted reading and is
  subtracted.

## [2.1.5] — The self-test drives run on a consumer-shaped tree

**Every template drive is measured by the bank on the PRODUCT's tree**, and
until this patch none had ever been run on one: a tree with populated
drawers, extra gate units, a declared rule namespace, named divergences and
no bank output. The first product's bank found the class; this patch fixes
the six causes it read and builds the world the template now measures
itself against. A `quality/**` or `scripts/**` fold's gate is the FULL one,
on a box, BEFORE the merge — the product that folded 2.1.4 ran `--loop` only
and met the self-test at its bank.

### What a product does at the merge

1. Nothing new to type. A drive that could not key on your tree keys; the
   drawer's proof cases plant in a scratch checkout, never your drawer; the
   self-test unit runs your LEGS only under the `local` unit, never under
   `selftest`. Delete any `# cites:` line you added to a template drive for a
   drawer path, and any `divergence:` line naming one of those drives.
2. Twelve template cases still assert template-only properties on a product
   tree (the queue carries them under the consumer-shaped class): skip them as a
   named divergence on the drive until the next patch.
3. Builders: `.claude/agents/builder.md` ships and pins Claude Opus 5.5; a PM
   session on Claude Code 2.1.280 or newer dispatches `subagent_type: builder`.

### Added

- **Agent definitions ship with the method.** `.claude/agents/` holds the
  dispatched roles' definitions — `.claude/agents/builder.md` pins the model a
  builder runs on — and the publication classifier now places
  `.claude/agents/**` in bucket R5 beside `.claude/skills/**`
  (`scripts/archaeology_lib.sh`, `docs/product/publication-manifest.md`), so a
  product inherits the definitions with the skills instead of `publish.sh
  --census` refusing the release with `could not place a path`.
### Fixed

- **The drawer cases no longer refuse the tree that uses the drawer.** Four
  self-test cases planted their fixture at the tree's OWN `quality/local/` and
  opened with "already exists in this checkout — this case plants one and will
  not overwrite yours", so the cases that prove the drawer reader works could
  only run where there was no drawer. On the first consumer's tree the
  `test_gate_explain.sh` case exited 2 and the house-rules engine's selftest
  read that as `DRAWER BROKEN … it cleared nothing` — the seam a product
  depends on, unproven on exactly the trees that depend on it. Each case now
  plants in a scratch CHECKOUT of its own (the engine derives its root from
  its own file and honours no override, so another tree means another copy of
  the engine), with any committed product drawer removed from that clone
  first. A product sees the four cases hold; the template's own run is
  unchanged.
- **A reserved drawer path is judged on every tree, so the template's bank
  catches what a product's would.** The drive-keying floor skipped any path a
  drive spells that the measured tree does not carry — right for a plant name
  inside a throwaway clone, wrong for a drawer: `scripts/local/legs` is absent
  on the template and present on every product that uses the seam, so ten
  drives here spelled one, keyed clean, and seven of them exited 2 with
  `could not key` on a consumer. A path matching a reserved drawer glob is now
  judged as if it existed, with the globs read from their one home
  (`DRAWER_GLOBS` in `scripts/divergence_census.sh`); the ten drives declare
  their drawer paths on a `# cites:` line. A product that hits the refusal
  adds one token to one header.
- **A derived output the release does not ship keys as `absent`, not as a
  refusal.** `scripts/test_impact.json` is the bank's own output and is
  trimmed from the release, so on a fresh product it does not exist — and
  three drives DECLARE it, so `drive_key` refused, so the bank could not go
  green, so the map was never written. A deadlock, on every consumer's first
  bank. A declared path named in the fold's `FOLD_ABSORBED_PATHS` now keys as
  `absent` when the tree has none; the path stays in the key, so the day the
  map appears every verdict banked without it misses. Every other declared
  path that expands to nothing still refuses.
- **The leg-sequence cases no longer assert the template's shape about a
  product's gate.** `test_list_legs.sh` typed the three announced leg
  sequences and compared a product's run against them, so a populated
  `scripts/local/legs/` — which makes the gate announce `local-legs`, grow
  `FULL_LEGS` by one `local:<name>` per leg and declare a unit per local unit
  — reded five cases on a tree where the gate was right. The baseline stays
  the template's; what the drawer adds is now read through the gate's own
  local-legs reader. Two more of the same class went with it: the shard
  census left a product's real drives unstubbed in its clone, and its member
  reader's name class had no `:`, so `local:<name>` drives were invisible to
  it.
- **The deploy-layer gap is derived, not typed.** `test_verifier_box.sh` and
  `test_verifier_image.sh` each typed `7` for the drives under `deploy/tests/`
  that no moment invokes. A product is licensed to grow that directory, so the
  case read "wanted 7" on a tree where nothing was wrong. The number is now
  derived two independent ways and the two compared, with the plant arms
  relative to it — and the mirrored-helper comparison the second twin's own
  comment promised is now performed, over both helpers.
- **The publication drive keys again.** Its new agent-definition case spells
  `.claude/agents`, `.claude/skills` and `CLAUDE.md` and its header declared
  none of them, so the self-test could not key the drive and the bank exited
  2. All three are now on its `# cites:` line: the drive plants its own
  copies in a fixture and never reads the real tree's.

## [2.1.4] — A template-only test skips on a product

One test. `test_fold_map.py`'s self-map case asserted that this tree's fixtures
are all where the release ships them — true of the template's own tree and
false by construction on any product that has folded, so it was red on every
consumer forever. It now skips, with the reason, when the tree declares a
`rule_id_namespace`. Nothing else changes; a product that skipped it as a named
divergence deletes the line at this fold.

### Fixed

- **A template-only test no longer reds every product's suite.** The case that
  maps this tree's `quality/rules.yaml` onto itself and asserts there is
  nothing to do
  (`apps/core/tests/test_fold_map.py::test_this_template_tree_maps_onto_itself_with_nothing_to_do`)
  asserted a property only the TEMPLATE's own tree has: a folded product
  carries drawer rules and a drawer fixture tree, and `--fold-map` walks
  `quality/local/canary` and `quality/local/negative` on the same three keys
  it walks the template's trees on — so the FIXTURES section has content by
  construction and the assertion was red on every consumer, forever. The case
  now skips when the tree declares `rule_id_namespace:`, with one reason
  string naming that declaration, read through the engine's own drawer parse
  rather than a second reader of `quality/local/rules.yaml`. A product that
  has folded sees one skip saying why; the template runs it unchanged.

## [2.1.3] — The drawer holds what the first fold found it could not

**A second patch from the same fold.** Every item is a place the first product
to fold 2.1.2 put a rule, a count or a fixture where the release told it to and
met a refusal the drawer could not answer — or an instrument that answered
cleanly in the wrong direction. Nothing here changes what the template does at
run time.

### What a product does at the merge

1. **The fold map takes the release's own rules file as its second argument**
   (2.1.2's item 2 is corrected in place below): after `git merge` the tree's
   `quality/rules.yaml` is the merge result, and the map now refuses it, exit
   2, naming the pair. `--template-tree <dir>` makes the FIXTURES section
   release-true; without it the section says it is a lower bound.
2. **A product rule whose subject is not under `apps/`, `config/` or
   `frontend/` declares its own kind** under `scope_kinds:` in
   `quality/local/rules.yaml` (the fifth key) and names it in `kind:`; a root
   may be a directory or a file. A drawer rule that names a template `check:`
   runs in-process as before and needs no kind.
3. **A backlog on a template rule's own finding class lives in the drawer** —
   `ratchets:` accepts a class the template rule declares; the red prints the
   paste line; the drawer's count ADDS to the template's.
4. **A directory the engine plants is claimed by its `ENGINE_FIXTURES` entry**;
   a product that patched `unclaimed_fixture_directories` deletes the patch.

### Fixed

- **A product rule may be about the product's own files.** `quality/local/rules.yaml`
  takes a fifth key, `scope_kinds:`, in the same shape `quality/rules.yaml` writes
  its two — `roots:`, `suffixes:`, `comment:`, optional `skip_dirs:`/`needs_tree:` —
  and the engine reads the union. The template declares `py` (apps, config) and
  `js` (frontend) and nothing else, so a product rule whose subject was a ledger,
  a doc, a `.env.example` or a canary under `quality/local/` had no kind it could
  name and its runner's every finding was refused: *findings[0].path
  'docs/product/queue.md' is outside the roots this rule declares (apps, config)*.
  That refusal stands — a runner may still only report about what it was pointed
  at — and now names the drawer key as the remedy when the rule is the product's.
  A product kind may not reuse a template kind's name (refused, naming both
  files); a root may be any directory **or file** this tree carries — a file
  root's walk is itself, in all four readers, `--selftest-inputs` included; a
  root that names nothing, or that git does not carry, is refused in the
  drawer's own file rather than four readers later. **The walk is the union and
  the attribution is not**: a `rule-<id>` valve counts only where that rule's
  own kind reaches, so a product kind rooted at `docs/` with `comment: "#"`
  cannot turn every `# rule-13:` shaped line of prose into an override of a
  template rule it does not own.
- **A product's backlog for a template rule's own finding class has a home.**
  `ratchets:` in the drawer accepted only app-keyed classes on a template rule,
  so a product folding rules 50–53 — which ratchet per FINDING class (`literal`,
  `api-reach`, `barrel`, `consumed-undeclared`) — was told its class `literal`
  was *not a directory under apps/*. Those rules now declare their classes at
  `0` (a measurement, ADR gate-6 (b)), the drawer may name any class a template
  rule declares, and the drawer's count is **added** to the template's rather
  than replacing it — so a product records its own backlog and still cannot
  erase a template ceiling from a file the template never reads. A name that is
  neither an app nor a declared class is refused with the sentence it always
  had, now listing the classes that rule does declare. A finding class over its
  ceiling now prints the `recorded-at <sha> [fold]` line to paste — it never did,
  because `unmeasured_app` answers `None` for a class that names no app — and a
  summed ceiling's finding is homed at the file the number lives in and says
  `(template n + drawer m)`.
- **A fixture directory the ENGINE plants into can be claimed.** `ENGINE_FIXTURES`
  claimed a fixture FILE, but the directory census built `claimed` from rule ids
  alone — so a directory the engine plants into whose name is no rule's id was
  *a fixture directory no rule claims*, exit 2, with nothing a reader could
  declare to clear it. The census now claims the directories its engine fixtures
  sit in. The template had not met it only because its one engine fixture sits
  inside rule 50's directory.
- **`--fold-map` takes the TEMPLATE side as an argument, and refuses to guess
  it off a merged tree.** The first consumer measured the 2.1.2 instrument in
  the wrong direction: § [2.1.2] item 2 sent them here AFTER `git merge`, and
  on that tree `quality/rules.yaml` is the merge result — their names at their
  numbers — not the release's. Same previous file, measured on their worktree:
  the merged file as the template side printed `unchanged; nothing to
  renumber` rule after rule, UNMATCHED empty, exit 0 — a clean-looking map
  that renames TEMPLATE rules into the product's namespace and leaves PRODUCT
  rules on template integers, the exact failure the map exists to prevent; the
  release's own file printed twelve renames and twenty-seven fixture findings.
  **Nothing in the output distinguished the two.** So the grammar is now
  `--fold-map <previous rules.yaml> [<template rules.yaml>] [--template-tree <dir>]`,
  the header line names the path it used as the template side and whether it
  was GIVEN or TAKEN from the tree, and with no second argument two teeth
  refuse (exit 2, naming the pair and printing the two-argument remedy) the
  states in which the tree's file is not a release file: (a) the tree's
  `quality/rules.yaml` is not the same rule set as the previous file — a name
  at a different id, or a name in one and not the other, either direction; (b)
  `quality/local/rules.yaml` already namespaces a rule whose name the template
  side still carries at a bare integer. *(a) is the whole comparison rather
  than "the same name at a different number" on purpose: that half is the
  HEALTHY case — a template rule at a drifted number is exactly a shared name
  at two ids — and the consumer's own measured run contained no such pair.*
  The FIXTURES section declares itself a **lower bound** whenever the fixture
  bytes came from this tree, because a rules.yaml cannot carry bytes;
  `--template-tree <dir>` (a `git worktree` or `git archive` of the tag) is
  what makes it complete. `quality/gate.py` (`fold_map_lines`,
  `_fold_map_template_side_problems`, `_fold_map_drawer_pairs`,
  `_fold_map_remedy`), driven by `apps/core/tests/test_fold_map.py` and
  `scripts/tests/test_gate_explain.sh`; § [2.1.2] item 2 is corrected in
  place.

## [2.1.2] — The fold's instruments, from the first consumer's fold

**A patch, and everything in it was measured on the first product to fold
2.1.1.** Nothing here changes what the template does at run time; every item
is a place where the fold told a product the wrong thing, or nothing, and the
product found out by hand. The divergence census now runs on the tree you are
folding FROM and refuses honestly when it cannot; the three places that named
a product's fixture home named the template's tree instead; and there was no
instrument for the one question item 7 of 2.1.1 hinges on — which of your
rules are actually yours.

### What a product does at the merge

1. **On the tree you are on, before the merge:** take BOTH census files from
   the tag you are folding, then run the census — `git show v2.1.2:scripts/divergence_census.sh > scripts/divergence_census.sh`
   and the same for `scripts/archaeology_lib.sh`; the census refuses, exit 2,
   naming both if only one was taken.
2. **Before renaming any rule — and HAND IT THE RELEASE'S OWN rules.yaml, as a
   second argument.** Take both files first:
   `git show <your pre-merge sha>:quality/rules.yaml > /tmp/before.yaml` and
   `git show v<the release you are folding>:quality/rules.yaml > /tmp/template-rules.yaml`,
   then `python -m quality.gate --fold-map /tmp/before.yaml /tmp/template-rules.yaml`.
   **The second path is not optional in practice: after `git merge`, the tree's
   own `quality/rules.yaml` IS THE MERGE RESULT — your names at your numbers —
   not the release's, so a map built against it renames the template's rules
   into your namespace and leaves yours on template integers.** The reader
   refuses (exit 2) rather than printing that map, and the header line now
   names the path it used as the template side. Add
   `--template-tree <a git worktree or git archive of the tag>` for the
   FIXTURES section at full strength; without it that section says in its own
   header that it is a lower bound, because the fixture BYTES can only be read
   off a tree and with no tree named that tree is yours.
   The map decides by NAME which rules are the template's (renumber to its
   number) and which are yours (`<ns>-<n>`, into the drawer), names all five
   places an id lives, and lists every fixture file the template ships that
   sits under one of your ids — DELETE those, never `git mv` a template
   fixture directory.
3. Then 2.1.1's items 3–16 as written, with its items 1, 2 and 7 corrected
   below.

### Fixed

- **The divergence census runs on the tree you are folding FROM, and a run that
  died no longer reads as a clean one.** Three defects the first consumer's
  pre-merge run found, all in `scripts/divergence_census.sh`. (1) The census
  reads `$RULES_FOR`, the no-fork idiom `scripts/archaeology_lib.sh` gained in
  the same release — so run against the PREVIOUS release's library, which only
  echoes, it died `RULES_FOR: unbound variable` mid-classification. It now
  probes the pairing with one call before it classifies anything and refuses,
  exit 2, naming BOTH files to take and saying that the tag is the release you
  are merging. It names no version: this refusal only ever fires on a tree that
  has not merged yet, so the checkout's own `TEMPLATE_VERSION` there is the
  release you are already on — the one whose library is the problem — and a
  derivation that hands you the wrong tag with total confidence is worse than a
  blank you can fill in. (2) That death
  EXITED 0: on GNU bash 3.2 a `set -u` death reaches `trap … EXIT` with
  `$? = 0`, so a census that had classified nothing reported a clean tree. The
  census now carries the authorship exit guard `scripts/pm_fold.sh` already
  had — every end it authors goes through one function, and an end nobody
  authored is exit 2 whatever the status says, naming what it means. (3) The
  reserved-drawer count was derived with `set --`, which GLOBS: on any tree
  that actually has the drawers, the three patterns expanded against the
  filesystem and the count read 6 instead of 3 — and house rule 60's
  `drawer_globs` floor reads that number, so the floor was being satisfied by
  the tree rather than by the list, silently and in the passing direction. The
  count is now taken with pathname expansion off.

- **A product's own house-rule fixtures live in the DRAWER, and the three
  places that teach the shape said otherwise.** `quality/gate.py::fixture_home`
  plants a drawer rule's fixtures from `quality/local/{canary,negative}/<id>/`;
  the engine's header, `quality/rules.yaml`'s header and 2.1.1's own release
  note all named the same two kind directories with the `local/` segment left
  out — which is the TEMPLATE's own fixture tree, and it holds integer ids
  only. (The wrong string is not spelled here on purpose: the census below
  reads prose, and a release note quoting the defect would be the defect.) A product that believed the prose planted
  its canaries where the engine never looks — and a canary that is never
  planted never fires, which is a dead canary reading as a pass. The sentences
  now name the drawer, and `apps/core/tests/test_drawer_fixture_home.py`
  derives the path from `LOCAL_CANARY_DIR` and reds if any of them drifts
  again.
### Added

- **`python -m quality.gate --fold-map <previous rules.yaml>`** — the fourth
  reader, and the instrument a product folding a release runs BEFORE it renames
  a rule. It reads the product's pre-merge `quality/rules.yaml` and the
  template's current one, matches every rule **by NAME** (never by number — the
  number is what drifted), and prints one paste block per rule: `TEMPLATE
  <old n> → <new n>` or `PRODUCT <old n> → <ns>-<old n>`, naming all five
  places an id is written, the fifth being the `djb.Wnnn` registration in
  `apps/core/checks.py`, and whose fixtures are given back by DELETE rather
  than by a `git mv` that would nest two rules' directories. Its FIXTURES
  section is keyed on CONTENT rather than on the id — exact bytes, then
  whitespace-normalised bytes, then the basename as a `NAME MATCH — read it:` —
  over everything the template's plans name, `extra_files:` included, so a
  template fixture that rode into a drawer under a DIFFERENT number is found
  even after a reformatter has been through it. Exit 0 with the map · exit 2 if
  either file cannot be read or a rule carries no `name:`. Driven by `apps/core/tests/test_fold_map.py`
  and by four cases in `scripts/tests/test_gate_explain.sh`. (HOTFIX-RULEMAP-1.)

## [2.1.1] — A product folds the template without a hand-patch

**A patch, and what it patches is the fold itself.** 2.1.0 shipped correctly
and then met its first real consumer, who merged it and came back having edited
template-owned files in order to do so: gate legs added to `scripts/check.sh`,
house rules to `quality/rules.yaml`, fixtures to `apps/conftest.py`, derived
paths to `scripts/pm_fold.sh`, environment names to
`scripts/tests/drive_preamble.sh`, lifecycle classes to `scripts/lifecycle.sh`,
deploy jobs to `.github/workflows/ci.yml`. Not one of those was the product
doing something wrong. Each was a template folder that runs a LIST of things
and had no way to be handed one more item — so the only way to add one was to
edit our file, which the next release then conflicts with, or fast-forwards
over with the product's work silently gone.

**Every such folder now has a drawer.** A drawer is a `local/` sibling of the
template directory it extends — `scripts/local/legs/`, `quality/local/`,
`scripts/local/fold.d/`, `scripts/local/lifecycle.d/`,
`scripts/local/drives/`, `scripts/local/env_keys`, `scripts/local/ci/`,
`docs/product/instruments.local.md`, `apps/conftest_local.py` — discovered by
path by the one reader that already owns that list, never written by the
template and never shipped by a release. They obey three laws, and the laws are
the same for every one of them. **Absent is byte-identical**: the leg listing,
the self-test transcript, the instrument census, the collected test set and the
workflow are the bytes they were on a tree that has never heard of a drawer,
and that is asserted by `cmp` and by `diff` rather than by this paragraph.
**Present is discovered**: no registry to edit, no import to add, no template
file to touch — the reader finds the path. **Malformed is exit 2, naming the
file**: a leg with no executable bit, a drive with no preamble, a fold step
that wrote a path it did not declare, a lifecycle file carrying a function, a
name one of ours already has — never a silently smaller gate.

The rest of the release is the other half of the same fold. Which files are
ours is a table now rather than a convention, and a read-only census tells you
which of them you have edited. An arriving migration chain grafts onto your own
leaf with one command instead of by hand. An event noun nobody classified costs
you a gate finding carrying the line to paste, instead of a rolled-back write
and a 500. And the corrections are here too: a rename table that was missing
four of its rows, two release-note claims that named flags the tree does not
have, and a house rule that was proving itself through an ingredient app a
product is allowed to delete.

### What a product does at the merge

Items 1 and 2 are for every product. Items 3 to 8 are the things a merge, a
gate run or your own apps raise — each says what you see if you skip it, which
is how you tell whether it is yours. Items 9 to 12 are the drawers: nothing to
do unless you have the edit one of them replaces. Items 13 to 16 are a line
each.

1. **Before you merge: `./scripts/divergence_census.sh`.** Give it a base —
   `DJB_TEMPLATE_BASE=<ref>`, one line in `scripts/local/template-base`, or a
   git remote named `template` — and it lists every template-owned path whose
   content is not the base's, with its ±lines and the commit that last touched
   it. It writes nothing, fetches nothing and moves no ref. Exit 1 on a
   divergence your own `architecture.md` does not name, printing the
   `divergence: <path> — <reason>` line to paste; exit 0 once every one is
   named. **On the previous release's tree, take the census AND its classifier
   from the tag you are folding — not the one you are on — before you run
   either**: `git show <tag>:scripts/divergence_census.sh >
   scripts/divergence_census.sh` and `git show
   <tag>:scripts/archaeology_lib.sh > scripts/archaeology_lib.sh`. The two ship
   together and the census reads an idiom the older library does not set;
   taking one of them refuses, exit 2, naming the other.
   Skip it and the merge tells you the same thing one conflict at a
   time, while you are in the middle of resolving them. House rule 60 is the
   gate's reading of the same census, and it SKIPS with a printed line only
   where no base is declared — declare one and a template-owned file you have
   edited is a gate finding on your own tree, not a surprise at the next
   release. The same rule also reads the `drawers` table, so a drawer whose
   reader or whose drive case you removed is a finding too.
   (X01 24f2975c, X7 591c461a.)

2. **`./scripts/setup.sh`, then `./scripts/check.sh --fast`.** Three measured
   files no longer arrive at all: `scripts/test_impact.json`,
   `scripts/pytest_durations.json` and `scripts/gate_member_durations.json` are
   trimmed from the release, so there is no conflict in them and no
   `git checkout --ours` to remember — yours stay yours, untouched. A tree
   holding none of them measures instead of guessing, and says so in its own
   banner: `scripts/test_impact.json is absent … closure scope` is
   measure-not-stale, not a warning to clear. **Correction, measured at the
   first real fold: a product that has ever banked DOES get a conflict in two
   of them** — 2.1.0 shipped `scripts/pytest_durations.json` and
   `scripts/gate_member_durations.json`, 2.1.1 trims them, and the product had
   edited both, so they arrive as modify/delete (`UD`); resolve by `git add`-ing
   both, because your own measurements stand and they are your inputs now.
   `scripts/test_impact.json` is silent only if you had already deleted it.
   (E14 23abf726.)

3. **A `max_migration.txt` conflict in a template app → `uv run python
   manage.py fold_migrations <app> --dry-run`, then the same command without
   it.** Once per conflicted app. It renumbers the whole ARRIVING chain past
   your leaf, rewrites its in-app dependencies, and leaves cross-app and
   `swappable_dependency(...)` entries alone. Merge the tag, never rebase onto
   it — under a stopped rebase HEAD is the upstream, so the top of the conflict
   block is our leaf and a fold would renumber YOUR chain; the command refuses
   that case by name. Skipped, you are renumbering by hand against `dlm.E005`
   and two leaves. One declared gap: a dependency from ANOTHER app onto a
   migration the fold renumbered is left as written and raises
   `NodeNotFoundError` naming both ends at the next `migrate` — fold that app
   too, or repoint the one dependency. (D2 a93d302f, D2F f52170ff.)

4. **`uv run python manage.py rename_permission --table`** prints the table of
   every rename the tree declares, one row per pair with the declaring app in
   the first column; **`--declared`** moves every one of them across every
   tenant in a single pass and is idempotent — a second run rewrites nothing
   and says so. Skipped, a grant stored under an old key is inert: it names a
   word no door answers, and nothing at all tells you. (E3 408a5e35, E3F
   817d0a83.)

5. **`uv run python -m quality.gate --explain 59`** prints one paste line per
   undecided event noun, per app. Skipped, you get one gate finding per noun
   instead — and at runtime the socket stays closed to that noun while the
   write it announces still COMMITS. (C1 30b7cbb1, C0 365ec134.)

6. **`uv run python -m quality.gate --explain 54`** lists every read this tree
   asks for: the selector, the key it asks, where that key resolves, who is
   refused, the one line that opens it, and every door that reaches it. The
   hat-less caller at `GET /api/v1/memberships/mine/` is one row.
   (C3 f05f031b.)

7. **Rule ids: write `rule_id_namespace: <ns>` and
   `template_rule_ids_through: <n>` into `quality/local/rules.yaml`**, and
   rename your own rules to `<ns>-<n>` in four places — the id, the fixture
   directory, the valve and the check tag — `git mv`-ing the fixture
   directories as you go — into `quality/local/{canary,negative}/<ns>-<n>/`,
   the drawer, which is where the engine plants a drawer rule's fixtures from.
   **Do the `git mv` LAST, and check what it carried.** The merge lands this
   release's own new fixtures into `quality/{canary,negative}/<n>/` as clean
   adds before you move anything, so a `git mv` of a directory you also own
   takes the template's files into your drawer with it: after moving, run
   `git checkout v<version> -- quality/canary/<n> quality/negative/<n>` for
   every template id you moved through, and read the drawer for files the tag
   also ships. The first consumer moved thirteen template files that way —
   house rule 60's whole plan among them — and found them only because ruff
   complained. Skipped, the engine exits 2 with `duplicate id`, or
   with `product rule ids are <ns>-<n>`; and either key written into the
   template-owned `quality/rules.yaml` is refused by name, with the line that
   says where to move it. (D1 0d0e7fdf, X3 11c583c4.)

   **Before you rename anything, run
   `uv run python -m quality.gate --fold-map <your pre-merge quality/rules.yaml>`**
   — `git show <your pre-merge sha>:quality/rules.yaml > /tmp/previous-rules.yaml`
   produces the file. It decides which rules are yours **by NAME**, never by
   number, because the number is the thing that drifted: it matches every rule
   in your previous file against the template's current one and prints one
   paste block per rule — `TEMPLATE <old n> → <new n>` for a rule of ours you
   were carrying at another number, `PRODUCT <old n> → <ns>-<old n>` for one of
   your own. Both directions of the mistake are silent without it: a TEMPLATE
   rule parked under your namespace stops being folded — the next release
   improves our copy and you keep the old one forever — and a PRODUCT rule left
   on a template integer collides again at the next release. The first consumer
   moved four of our browser rules into their drawer as `<ns>-58..61` before
   noticing.

   **There is a FIFTH place a rule id is written, and item 7's four do not name
   it.** A rule declaring `django_check_ids:` has that id REGISTERED in
   `apps/core/checks.py` (rule 54 → `djb.W054`), and `consistency()` refuses a
   declared id the file does not carry — `django check id … not present in
   apps/core/checks.py`. So a renumber that stops at the id, the fixture
   directory, the valve and the check tag reds there. The map prints that place
   per rule, out of the rule's own declaration, keeping the letter and the width
   it was written with (an `E` re-spelled as a `W` is a registration nothing
   carries).

   **And the fixtures move between DIFFERENT numbers, which no id-keyed census
   can see** — the class, widened. The map's FIXTURES section is keyed on
   CONTENT, in **three keys**, each file reported under the first that hits:
   the exact sha; then the same bytes with **whitespace normalised**, because a
   reformatter between two folds is the commonest single edit there is (of the
   thirteen template fixtures that reached the first consumer's drawer, the
   ones a formatter had touched were invisible to an exact sha); then the
   **basename**, which survives any edit and therefore prints `NAME MATCH —
   read it:` rather than a verdict. The population is every file under your
   `quality/{canary,negative}/<n>/` and `quality/local/{canary,negative}/<ns>-<n>/`,
   against everything the template's own plans name — `extra_files:` included,
   which is where 52 of this tree's 469 fixture files live, house rule 60's own
   plan among them. `quality/negative/50/vendored_valve.js` rode into the first
   consumer's drawer as `…/<ns>-58/vendored_valve.js` exactly this way.
   **And the remedy for a template rule's fixtures is DELETE, not `git mv`**:
   after the fold `quality/canary/<old>/` also holds the template's own rule
   `<old>` plan and `quality/canary/<new>/` already exists, so a move nests one
   directory in the other or carries another rule's files into its home. The
   block names the files the template ships at the new id so you can see what
   you are deleting against. The reader exits 0 with the map and 2 if either file cannot be
   read or a rule carries no `name:`; it never guesses. On this template,
   mapped against its own `rules.yaml`, it prints one unchanged line per rule
   and no fixture at all. (HOTFIX-RULEMAP-1.)

8. **A ratchet red on one of YOUR apps now prints the line that records it —
   `<app>.<class>: <n>  # recorded-at <sha> [fold]` — and it goes under
   `ratchets:` in `quality/local/rules.yaml`**, never in ours, which a fold
   overwrites. Skipped, exit 1 stands and nothing anywhere says the grammar,
   the stamp, or that recording it was allowed. (D3 62600447, X3 11c583c4.)

9. **Gate legs: `scripts/local/legs/<name>.sh`**, executable, carrying the
   `# >>> leg v1 >>>` header block. The listing emits a unit called `local`;
   CI, the bank and the per-rung gate take it with no other edit. Malformed is
   exit 2 at the listing, naming the file and the field. (X2 8bc83a01.)

10. **Fold steps: `scripts/local/fold.d/<step>.sh`** — executable, declaring
    every path it writes in the `derived-tree-paths` sentinel block; a path it
    wrote and did not declare is the fold's exit 2, naming the step, with
    nothing committed. **Lifecycle classes:
    `scripts/local/lifecycle.d/<class>.sh`** — declaration-only; a function
    definition or a bare command in one is exit 2, because this drawer is
    sourced by every broom and by the gate itself. (X4 34411469.)

11. **Fixtures: `apps/conftest_local.py`** — loaded iff the module exists. A
    drawer that raises on import is a loud error naming the file, never a
    silent absence that reads as `fixture not found` in every test you have;
    and a drawer fixture whose name ours already carries loses, silently.
    (X8 78b6fe1c.)

12. **Drives, instrument rows, drive environment and CI steps:
    `scripts/local/drives/`, `docs/product/instruments.local.md`,
    `scripts/local/env_keys` and `scripts/local/ci/`.** The 2.1.0 instruction
    to edit `scripts/tests/drive_preamble.sh`'s two lists is RETIRED: move your
    names into the env-keys drawer and take our file whole at the fold. A
    drawer drive is not keyed and not banked — it runs on every gate, and both
    consults print that rather than passing over it. (X5 71852d82.)

13. **Keep `if user.zitadel_sub == cleaned: return user`** if the merge offers
    that line as a conflict. Resolved away, every person in the deployment is
    locked out at their SECOND sign-in; eight tests red by name if you do.
    (C2 1e5f95e9.)

14. **Regenerate the API client against your own tree, and look at your CI
    cache key.** Both are under **Migrating** below: `frontend/openapi.json`
    ships correct for the release and is stale for you the moment your apps are
    in the schema, and a `cache: pnpm` on `setup-node` under the sharded matrix
    has every shard writing one entry.

15. **The ops policy version, and it is the owner's own hand:
    `./deploy/iam/verifier_bootstrap.sh --confirm`** publishes
    `ec2:DescribeSpotInstanceRequests`. Until it is run, a reclaimed verifier
    box prints `status unreadable (…)` rather than naming the reclaim.
    (B-R1 3077615d, B-R2 be49d4b8.)

16. **Nothing to do — delete the divergence, if you were carrying one.** The
    measured-tree push comparison (A1 03f2fe6e); the documented full-gate
    durations mode, the frontend leg's change-aware skip under `--leg`, and the
    drive registry (A3 d39a2f90); the wrapper's footprint case, its base-ref
    reader and the tag fetch (A2 36fc5c30, A2F2 f67ba14a).

### Changed

- **`scripts/test_impact.json` is committed by the FOLD, not by hand.** The
  acceptance box writes the test-impact map into the working tree at the end of
  a bank and no fold step can regenerate it, so it joins `scripts/pm_fold.sh`'s
  typed derived list as the one entry clause 1 tolerates ALREADY DIRTY — an
  `absorbed` line at the top of the run, `fold: acceptance map absorbed` as the
  subject. The exemption is its own typed literal and a checked subset of the
  derived list: a DELETED map is still a dirty tree, and work beside an
  absorbed path is still refused. **What it buys**: a hand commit put the map
  in the next docs-only push's delta, which made `scripts/tests/test_pm_push.sh`
  (116 s) a derived reader of every ledger push.

- **The `selftest` unit's shards are balanced by DURATION, not by index.**
  `./scripts/check.sh --leg selftest --shard k/N` used to give drive *i* to
  shard *i % N*, which balances the count of drives and says nothing about
  their price — and the drives differ by two orders of magnitude (one bank:
  one shard 1457 s while the other five units were done by minute 9, the
  arithmetic sum of its drives run one at a time). The assignment is now an
  **LPT partition** — heaviest member first, into whichever shard is lightest
  — over the walls recorded in `scripts/gate_member_durations.json`, read
  through the always-on leg's own reader, with a member the table does not
  name taking the median of the rows that do. It is deterministic for a table
  and an N (every box computes the whole partition and reads its own row out
  of it), every member still lands in exactly one shard, and the
  house-rules engine's own self-test is now a member like any other rather
  than a stated shard 0. **Each shard prints what it holds**: member count,
  predicted seconds, the table it read and that table's machine — which
  matters, because a table measured on one machine can be an order of
  magnitude out on another. **With no durations table the split falls back to
  the index round-robin and says so**: the file is a hint, and its absence
  means unmeasured, never a refusal. Nothing about a verdict changes — the
  same drives run, in a different partition — and `--list-legs` is
  byte-identical.

- **Rule ids are two namespaces, so a product's house rules stop colliding with
  the template's at every fold** (ADR gate-5). Only the template mints
  plain integers. A product declares `rule_id_namespace: <ns>` once, top-level
  in `quality/local/rules.yaml` — its own drawer, below — beside
  `template_rule_ids_through: <n>` — the highest
  integer the template release it folded had minted, which is how the engine
  tells a template rule from a product rule that typed an integer — and names
  its own rules `<ns>-<n>` in **four** places: the id, the fixture directory
  (`quality/local/{canary,negative}/<ns>-<n>/` — in the drawer, which is where
  the engine plants a drawer rule's fixtures from; the template's own tree
  `quality/{canary,negative}/<n>/` holds integer ids only), the valve
  (`# rule-<ns>-<n>: <reason>`) and the check tag (`<ns>.Wnnn`, where the template's are `djb.…`). The engine
  refuses every other shape by name, refuses a fixture directory no rule claims
  — including one under a namespace the tree never declared — and counts the
  self-test residence census over TEMPLATE ids only, so
  `selftest_residence_backlog` is a template fact a product folds and never
  retypes and a product's own rules are counted against zero. **A template tree
  carries neither key and nothing about it changes**: the self-test prints the
  number a product should record, and adding a template rule still costs one
  rule body. Adopting it is once, by hand: rename the ids, `git mv` the fixture
  directories, write the two keys into `quality/local/rules.yaml`. (Declaring
  either key in the template-owned `quality/rules.yaml` is refused by name,
  with the line that says where to move it.)

- **A product's own house rules live in `quality/local/`, so `quality/rules.yaml`
  stops being a file two people own.** The engine loads
  `quality/local/rules.yaml` BESIDE the template's at the one loader, with the
  fixtures under `quality/local/{canary,negative}/<id>/` and check-v1 runners
  under `quality/local/runners/`. Four top-level keys and no more —
  `rule_id_namespace`, `template_rule_ids_through` (both of which now live HERE
  rather than in the template's file), `rules:` and `ratchets:` — and anything
  else is exit 2 naming the key and the file, because every other key
  configures the engine rather than a rule. A drawer rule is a rule end to end:
  it passes `consistency()`, plants its canary through the REAL scope and must
  fire, keeps its negative silent, binds its floors, is suppressed and COUNTED
  by `# rule-<ns>-<n>:`, and both readers tag it `[local]`. Its `check:`
  resolves through ONE resolver — a name in the template's registry, re-scoped,
  or `quality/local/runners/<name>.py` speaking check-v1 — so a product never
  edits `quality/checks.py`; neither is exit 2 naming both places it looked,
  and a runner that answers with nothing is REFUSED rather than read as a clean
  tree. `ratchets:` is `rule id → class → count`, the product-owned home for
  per-app backlogs a product's apps had nowhere to record, and a class naming
  an app inside `quality/partition.yaml`'s `platform_apps` (as `<app>` or
  `<app>.<kind>`) is refused — the drawer records a product's backlog, never
  raises the template's ceiling. A drawer canary may plant only into a product
  app or `apps/example`. The drawer's non-rule keys fold into the engine digest
  and each drawer rule keys its own memo, so an edit re-keys exactly what it
  changed. **A tree with no drawer is byte-identical** — the listing, the
  self-test's numbers and `--selftest-inputs` are the bytes they were.

- **A house-rule ratchet class for one of YOUR apps now says how to record
  itself** (ADR gate-6). Per-app ratchet classes (`quality/rules.yaml`
  `ratchets:`) name only the apps this template ships, and a class with no
  entry is a ceiling of zero — the right answer for a template app, and an
  unreadable one for yours: the hook refused and nothing anywhere said the
  grammar, the stamp, or that recording it was allowed at all. A class keyed on
  an app OUTSIDE `quality/partition.yaml`'s `platform_apps` with no entry is
  now **unmeasured**: still a violation (green-because-unrecorded is not a
  pass), and the header the findings arrive under is the exact line to paste —
  `acme.read: 1  # recorded-at <sha> [fold]`, into `quality/local/rules.yaml`'s
  `ratchets:` under `"<rule id>":` — with the sha of the tree it was true at. Recording is the one time a number here may arrive from nothing and
  it belongs to the fold; after it the class moves DOWN only, by a person's
  hand, exactly as every other ratchet does. A class you recorded at `0` is a
  measurement and is untouched, template apps stay zero by absence, and the
  plant scaffold is never offered a recording. Rules 54 and 55 also gained a
  `remedies:` block — one fix form per finding class, printed by
  `python -m quality.gate --explain 54`, and every finding of a rule that has
  one now ends `fix form: --explain <id>`.

- **Two speed changes a product inherits and can override.** The test
  database now runs with `synchronous_commit` off on its own connections —
  a test's COMMIT stops waiting for the disk, which is legitimate for a
  database that is dropped at the end of the run and is nothing a product
  configures. And Temporal's retry backoff starts from one declared place,
  `TEMPORAL_RETRY_INITIAL_INTERVAL_SECONDS` in `config/settings/base.py`,
  rather than from a number repeated in each workflow — the test settings
  lower it, a floor test refuses a policy that would retry faster than the
  setting allows, and a product that wants a different interval changes one
  line instead of hunting for the literals.

- **A documentation-only push no longer costs a whole bank.** When every path
  changed since the last MEASURED tree is on one declared list — `docs/**`,
  `README.md`, `CLAUDE.md`, `.claude/skills/**`, `scripts/test_impact.json`
  (`CHANGELOG.md` and `TEMPLATE_VERSION` are deliberately OUT: pytest reads
  them, so a release still pays one bank) — `pm_push.sh --bank` runs only the
  readers those paths are DECLARED to have — a drive that reads a doc without
  naming it on its own declaration line is not run, and the next non-docs push
  is the belt — on the machine you are sitting at, and
  banks the same row a bank banks. Before either arm, so no lease, no pytest
  slot and no verifier box. Anything else is the full bank exactly as before
  and prints why, ending in "full bank"; a reader that goes red is a red tree
  and no row. Nothing a product wrote changes: the pre-push hook, the row
  grammar and the ledger's lookup are untouched.

### Added

- **Which files are the template's, and which are yours — per path, and now in
  the tree rather than in your head.** `docs/product/build-contract.md`
  § Ownership is the table: **template-owned** (a product edit is a
  divergence), **product-owned** (no conflict by construction) and **shared**
  (one file each, adjudicated by hand at a merge). Template-owned today:
  `scripts/**` less `scripts/local/**`, `quality/**` less `quality/local/**`,
  `.github/workflows/ci.yml`, `.claude/skills/**`, `config/**`, `manage.py`,
  the platform apps named in `quality/partition.yaml` less
  `apps/core/roles.py`, `CLAUDE.md`, `docs/runbooks/**`, `docs/standards.md`,
  and six standing documents under `docs/product/`. The row ENUMERATES, so
  anything it does not name — your apps, your ledgers, your `README.md`, your
  own `architecture.md`, a second workflow beside `ci.yml` — is yours. The
  decision behind it is ADR platform-extension-1, PROPOSED in
  `docs/product/architecture.md`.

- **`scripts/divergence_census.sh` — which template-owned files has this
  product edited?** Read-only: it writes nothing, fetches nothing and moves no
  ref. Give it a base — `DJB_TEMPLATE_BASE=<ref>`, a line in
  `scripts/local/template-base`, or a git remote named `template` (then the
  tag `v$(cat TEMPLATE_VERSION)` is derived for you) — and it lists every
  template-owned path whose content is not the base's, with its ±lines and the
  commit that last touched it. **Exit 0** when nothing diverged, or when every
  divergence is named in your own `architecture.md` as
  `divergence: <path> — <reason>`; **exit 1** on one that is not, printing the
  line to add; **exit 2** when it could not look. Run it at every fold, before
  the merge rather than during it. House rule 60 is the gate's reading of the
  same census, and it SKIPS with a printed line where no base is declared.

- **The drawers are reserved, so a release can never conflict with one.**
  `publish.sh`'s census now exits 2, naming the path, on any tracked file
  matching `**/local/**` or `*.local.md`. The template ships no drawer, which
  is what makes a `local/` sibling of a template directory a safe place to put
  your own legs, rules, fold steps, drives and instrument rows. The readers
  that discover those drawers are in this release, above and below; the
  reservation came first, because a name a release claims cannot be taken back.

- **Gate legs have a home: `scripts/local/legs/<name>.sh`.** A product's own
  checks — a typecheck, a licence scan, a visual baseline, a census over its own
  files — used to be added by editing `scripts/check.sh`, which is the file a
  release changes most. A drawer leg is an executable script carrying one header
  block, opened by `# >>> leg v1 >>>` and closed by `# <<< leg <<<`, whose
  fields are the whole contract: `unit:` (the runner it is handed — `local` is
  the drawer's own, any other name MAKES a unit, and a name this gate already
  declares is refused rather than silently joined), `needs:` (the organs it
  assumes, a declaration nothing acts on), `tier:` (`fast`, `loop` or `full` —
  the cheapest mode that runs it, and every mode above runs it too),
  `two-means:` (`broken` or `finding`, because a tool that exits 2 for
  diagnostics present and one that exits 2 for broken plumbing cannot share a
  reading), and optionally `touches:`, `inputs:` and `env:` — path prefixes that
  narrow it under the scoped modes and content and variable names that join its
  reuse key, so a product leg's verdict is reused on exactly the terms ours are.
  The listing names the unit; CI, the bank and the per-rung gate take it with no
  other edit anywhere. Every malformation is exit 2 AT THE LISTING, naming the
  file and the field — no `-x` bit, an unknown field, an unparsable value, a
  name colliding with a leg or a drive this gate already has — never a silently
  smaller gate. What it does not cover is declared: a check that must run INSIDE
  the pytest process is a fixture, not a leg, and its drawer is
  `apps/conftest_local.py` below.

- **Fold steps and lifecycle classes have homes:
  `scripts/local/fold.d/<step>.sh` and `scripts/local/lifecycle.d/<class>.sh`.**
  Both were files a product could only extend by editing ours. **A fold step**
  is executable and is run from the checkout root at the bank, and it DECLARES
  every path it writes in the same `derived-tree-paths` sentinel block the
  gate's own tree reader already parses. That declaration is load-bearing rather
  than decorative: the fold partitions the whole of the working tree against the
  typed list plus what each step declared about itself, so a step that wrote a
  path it did not name is the fold's exit 2, naming the step, with nothing
  committed. Its name is its basename, it joins the closed list `--only` takes,
  and a name colliding with one of the template's own steps is refused — a
  product shadowing the secrets step would be a product silently replacing the
  tree's one legal baseline writer. **A lifecycle class** is
  declaration-only: comments, blank lines and `lc_class` calls, and nothing
  else, read BEFORE it is sourced and sourced only if it is what it claims to
  be. That is not tidiness — this drawer is sourced by every broom, by the
  gate's own census and by the pre-push hook, so a function definition in it
  would silently override a built-in everywhere at once and a bare command would
  simply run inside all three. The claim column is a `glob:` pattern for the
  same reason. What the drawer does NOT give a product is a new lifecycle KIND:
  a kind nothing scans has no enumerator, an enumerator is code, and a product
  that needs one needs a platform rung rather than a silent empty census.

- **A product's drives, instrument rows, drive environment and CI steps have
  homes: `scripts/local/drives/`, `docs/product/instruments.local.md`,
  `scripts/local/env_keys` and `scripts/local/ci/`.** Four more drawers on the
  convention `scripts/local/legs/` already runs on: declare beside the template
  rather than editing it, and a release can never conflict with a path the
  template does not ship. **A drive** is `scripts/local/drives/test_<name>.sh`,
  `+x` and sourcing `scripts/tests/drive_preamble.sh` — it joins the selftest
  leg through the same one reader as the template's own two drive homes, runs
  in the same shard walk, and is named
  `local:<name>` on the verdict row, in `--list-legs`'s `composed-of` and in
  the leg's transcript, so you can tell your members from ours. **It is not
  banked and not reused: a drawer drive RUNS ON EVERY GATE**, and both consults
  print that rather than passing over it — the template's drive key is built
  from a `drive_preamble.sh` sitting BESIDE the drive, which `scripts/tests/`
  and `deploy/tests/` have and a drawer does not. **An instrument
  row** goes in `instruments.local.md`, the same five-column table read beside
  `instruments.md`, so your own executables stop owing rows in a file you do
  not own (a path may be in exactly one of the two). **`scripts/local/env_keys`**
  is one variable NAME per line and is the inverse of the preamble's own strip:
  a name there is KEPT when a drive scrubs its environment, and it joins the
  declared-inherited list the workflow-environment census reads — so **the
  v2.1.0 instruction to edit `drive_preamble.sh`'s two lists is retired**; move
  your names into the drawer and take the template's file whole at the fold.
  **`scripts/local/ci/*.sh`** run in name order in ONE optional `ci.yml` job
  (`local`, `needs: verdict`), which is where your deploy and publish steps go;
  there is deliberately no `ci.local.yml`, because GitHub composes nothing and
  a second workflow is a second copy of the whole setup. Absent, all four cost
  nothing — the listing, the leg's transcript, the instrument census and the
  workflow are byte-identical to a tree that has never heard of a drawer, which
  is asserted by `cmp` and by `diff` rather than by this paragraph. Malformed,
  each is exit 2 naming the file: a drawer drive with no preamble or no `+x`, a
  name a template drive or one of your legs already carries, an `env_keys` line
  that is not an identifier, a path with a row in both instrument documents, a
  CI step with no `+x`. `docs/product/build-contract.md`'s fenced `drawers`
  block is the list of every drawer and the one reader that opens it.

- **A product's pytest fixtures have a home: `apps/conftest_local.py`.**
  `apps/conftest.py` is template-owned, and it used to be the only place a
  fixture every app's tests need could live — so the first product built on
  this template put 609 lines of its own into it. Now the root conftest
  declares `pytest_plugins = ["apps.conftest_local"]` **iff** that module
  exists. Write one and its fixtures are available to every test in the tree;
  write none and nothing changes — no module, no declaration, the collected set
  identical to the byte. Two things to know before you fill it. A plugin is
  loaded for the whole session, so an `autouse=True` fixture in your drawer
  runs inside the PLATFORM's tests as well as your own — which is why the
  drawer is a member of the platform partition's boundary class and writing
  one does invalidate a banked verdict, the same as editing the template's
  conftest would. And on a name clash the template's conftest wins silently:
  a drawer fixture sharing a name with one of ours is ignored with no warning.
  The template never ships a drawer. The guard is
  `importlib.util.find_spec`, not a `try: import … except ImportError`,
  deliberately: a drawer that exists and raises on import is a loud error
  naming `apps/conftest_local.py`, never a silent absence that reads as
  `fixture not found` in every test you have.

- **House rule 60 now ENFORCES the drawers instead of describing them, and
  `docs/product/build-contract.md`'s fenced `drawers` block is what it
  reads.** The block grew from a list into the rule's text: five
  ` | `-separated fields a row — `live`/`held`, what a product extends, the
  drawer, **the one reader** that opens it, and **the one drive case** that
  plants a single item and proves the reader ran it — with every drawer this
  template ships in it (legs, drives, house rules, fold steps, lifecycle
  classes, drive environment, CI steps, the instrument census, pytest fixtures
  and the divergence census's own template base), plus two `held` rows that
  reserve `scripts/local/hooks/` and `deploy/verifier/local/bake.d/` against
  the rungs that will build them. Three things are now findings rather than
  gaps nobody could see: **a drawer this tree's own code opens with no row**
  (the population is derived from the `local/` paths the template's code
  spells — never typed beside the table), **a row whose reader is not in the
  tree**, and **a row whose case its drive does not define**. And at
  `--selftest` the engine RUNS every one of those cases — one plant per
  drawer, through the drive that already owns the property — so a reader that
  opens its drawer and throws the members away is exit 2 naming the drawer and
  the reader, printed with the census's measured seconds against its recorded
  ceiling. Adding a drawer now means adding a reader AND a case AND the row,
  and deleting any one of the three is a red.

- **The eight drives the `drawers` table names take `--case <name>`,** running
  exactly that case and nothing else (`--list` still names them; an unknown
  name is exit 2, never a silent run of nothing). They are
  `test_local_legs.sh`, `test_selftest_leg.sh`, `test_gate_explain.sh`,
  `test_pm_fold.sh`, `test_sweep.sh`, `test_drive_preamble.sh`,
  `test_scripts_census.sh` and `test_divergence_census.sh` — the drawer
  readers' own drives, and no others. It is the seam rule 60's drawer census
  runs the drawers through, and it is how anyone re-runs one property of a
  nine-minute drive while holding it in their head.

- **`manage.py fold_migrations <app>` grafts an arriving template migration
  chain onto your own leaf.** A product that added migrations to `core` or
  `accounts` used to reparent each release's chain by hand, because
  `rebase_migration` moves exactly ONE migration and cannot see an ancestor a
  previous fold renumbered (ADR core-28). The command reads the conflict in
  `max_migration.txt`, renumbers the whole ARRIVING chain past your leaf,
  rewrites its in-app dependencies (a renamed ancestor resolved by the stem
  after `NNNN_` — `0008_identity_branding` → your `0010_identity_branding`),
  leaves cross-app and `swappable_dependency(...)` entries alone, and rewrites
  `max_migration.txt`. `--dry-run` prints the plan and moves nothing. It exits
  2, naming the migration, on an arriving migration already applied locally, a
  stem that resolves to nothing or to two, a `max_migration.txt` with no
  conflict in it, or **a stopped `git rebase`** — under a rebase HEAD is the
  upstream, so the top of the conflict block is the template's leaf and a fold
  would renumber your own chain. Template migration files stay Django-native —
  this is the product's tool, run at the fold, and
  `git checkout -- <app>/migrations && git clean -f <app>/migrations` undoes a
  run (both halves: a rename leaves the new filename untracked, so a checkout
  alone gives you the old chain and the grafted copies side by side).
  **One declared gap:** a dependency from ANOTHER app onto a migration the fold
  renumbered is left as written, and Django's loader raises `NodeNotFoundError`
  naming both ends at the next `migrate` — loud, never wrong; fold that app too,
  or repoint the one dependency by hand.

- **The release census reads the release note it is about to ship.** Two legs,
  both release-mode only, both over the exported artifact rather than the source
  tree. **`changelog`** asserts the artifact's `CHANGELOG.md` carries a
  `## [<version>]` section for the version the tag is derived from — a tag with
  nothing to read behind it asks a consumer to merge a tree on trust.
  **`changelog-flags`** then reads that section and nothing else: every
  backticked span carrying both a `--flag` token and a script name is a CLAIM,
  and the flag must be a literal in the script the span names. A span with a
  flag and no script is COUNTED and printed rather than judged — inferring the
  script from the surrounding prose would be naming a cause the instrument has
  not proven — and older sections are never read, because a flag renamed since
  2.0.0 makes that entry a true record of 2.0.0 and correcting it would be
  rewriting history to please an instrument. Its blind spot is declared on the
  body: it reads text presence, not an arm, so a flag spelled only inside a
  string the script prints about a DIFFERENT script satisfies it. Three measured
  files also left the release in the same pass — `scripts/test_impact.json`,
  `scripts/pytest_durations.json` and `scripts/gate_member_durations.json` are
  trimmed rather than shipped, because a measurement of our suite on our machine
  is not a fact about your tree, and every reader of all three already treats
  absence as *measure*.

- **`.gitattributes`, carrying one line: `CHANGELOG.md merge=union`.** This
  file is append-only under `## [Unreleased]`, so two lanes that both append
  change one region and git's default is a conflict somebody resolves by
  typing both sides back in — seven of them in one cycle here. Union is git's
  own built-in driver and needs no definition: two appends merge clean and both
  survive. It is a merge driver and **not a judge** — it can interleave two
  halves of one wrapped bullet — and the thing that still refuses that is the
  release leg `changelog-flags`, at exit 2, before a tag. Both directions are
  driven by `scripts/tests/test_pm_merge.sh`. A product inherits the line; a
  code file never gets one, because union over code is two halves of a function
  silently concatenated.


### Fixed

- **Two release-note claims that named something the tree does not have.**
  Both were found by reading the scripts rather than the prose, and both are
  corrected here rather than in the section that carried them — a shipped
  section is the record of the tree it shipped, and an instrument is never the
  reason one is rewritten.
  - **`--plan` belongs to `deploy/verifier/bake.sh`, not to the box wrapper's
    `bake` subcommand.** `./scripts/verifier_box.sh bake` takes `--prune` and
    `--keep` (its usage header is the authority); the recipe-only run is
    `deploy/verifier/bake.sh --plan`, and the wrapper's own refusal prints that
    command for you when the image build needs looking at. Typing the flag at
    the wrapper is an unknown argument, not a dry run.
  - **A product that declared `login_page=own` does NOT skip the entrance-frame
    tests.** Skipping is the `template_shape` mark's doing, the mark is legal
    only in the modules `apps/core/tests/template_shape.py` declares, and
    `apps/accounts/tests/test_entrance_frames.py` is not one of them and
    carries no mark. The frame census runs for every product; a product that
    replaced the login page still owns the frames it kept, and extends that
    census in the same commit when it adds one.

- **An event noun nobody declared no longer costs you the write — it costs you
  one gate finding with the line to paste.** This supersedes the second half of
  v2.1.0's Migrating item 8. Before: `emit()` asked which authorization kind an
  event is about, and a noun that is no kind and has no `EVENT_KINDS` entry
  raised **inside your service's transaction** — so the write the event was
  about rolled back and the door answered 500. A product folding v2.1.0 met
  this as a wall of unrelated red (six service tests on one app, all of them
  rolled-back writes rather than dropped frames). Now: the write **commits**,
  the event row is written, the dispatch is enqueued, and
  `events.emit.kind_undecided` is logged at ERROR. The refusal moved to the two
  places that cost nothing at runtime — the **socket** drops every frame of an
  undecided noun (it already did), and the **gate** refuses the tree once per
  undecided noun, at the constant's own line in your `events.py`, ending in the
  `EVENT_KINDS` line to paste:

  ```
  "<noun>": "<kind>",  # draft: apps/<x>/services.py:<n>'s payload <Model>Out names <Model>
  ```

  — or, where the walk cannot resolve the emit site's payload to a schema with
  a model behind it:

  ```
  "<noun>": ?,  # no payload names an Out: a kind, or None with the reason
  ```

  **What to do with it:** paste the line into that app's `EVENT_KINDS`, confirm
  the kind is the one whose `<kind>.read` should govern who hears the event
  (the draft is a proposal derived from the emit site's payload, never a
  ruling — a `?` means the walk could not resolve one and you must decide), and
  run `./scripts/check.sh --fast`. `uv run python -m quality.gate --explain 59`
  prints the rule, its floors and its declared blind spots. The two refusals
  `emit()` still makes are unchanged: an org-scoped noun whose payload names no
  branch, and an org-less noun whose payload names one. The amendment, its
  rejected alternatives and its reversal are in
  `docs/product/architecture.md` § rule 59, signed 2026-09-21.

- **Rule 59 no longer proves itself through the metering ingredient.** Two of
  its self-test forms — the hand-built body that omits the branch, and the
  honest helper hop that is its control — were planted into
  `apps/usage/services.py` and leaned on `apps/usage/events.py`'s `EVENT_KINDS`
  for the noun they announce. A product that ships without the metering
  ingredient therefore got a **dead canary and a vacuous negative** out of a
  rule that was working perfectly: exit 2, on a tree that had done nothing
  wrong. Both forms now plant into `apps/example/services.py` on
  `WIDGET_CREATED` / `WidgetOut`, the same org-scoped shape in the app whose
  whole job is to hold one of everything. Two consequences a product sees in
  its own diff: the self-test's residence backlog is **19**, because rule 59's
  whole canary plan now lives in one optional app and it joins that census
  (the number and its reason are on the line in `quality/rules.yaml`); and the
  rule's `none_mappings` floor is **0**, because the 1 it carried rested on a
  single site in `apps/search` — another ingredient — and a floor one removable
  app supplies is unbound rather than binding. The class it was guarding keeps
  its own canary, which plants a `None` mapping every run and must fire.

- **§ [2.1.0]'s Migrating rename table gained the four `apps/accounts` rows it
  was missing, and it is now a command's output.** The section told a reader
  the table was derived from `renamed_permissions()` and it was not: it carried
  twenty-five of the twenty-nine pairs the tree declares, so an operator who
  followed it left every stored row under `accounts.user.deactivate`,
  `accounts.user.erase`, `identity_platform.configure` and
  `sso_identity.provision` naming a word nothing answers. The table is
  corrected where it stands and the section's prose is untouched — a shipped
  section is the record of the tree it shipped. It is now the output of
  `manage.py rename_permission --table`, which prints the union of every app's
  `RENAMED_PERMISSIONS` with the declaring app in the first column, and
  `apps/core/tests/test_vocabulary.py` refuses a pair declared by an app inside
  `quality/partition.yaml`'s `platform_apps` and absent from the note. The
  command also gained `--declared`, which moves every declared pair in one pass
  across every tenant and is idempotent — a second run rewrites nothing and
  says so.

### Migrating

- **A `max_migration.txt` conflict in a template app → run
  `uv run python manage.py fold_migrations <app>`** (add `--dry-run` first to
  read the plan), once per conflicted app, instead of renumbering by hand. Merge
  the tag, never rebase onto it — the command refuses a stopped rebase, because
  HEAD is the upstream there. To undo a run:
  `git checkout -- <app>/migrations && git clean -f <app>/migrations`.

- **A red naming a ratchet class of one of your own apps → paste the line the
  red prints.** The finding carries `<app>.<class>: <n>  # recorded-at <sha>
  [fold]`; put it in **`quality/local/rules.yaml`, your own drawer**, under its
  top-level `ratchets:`, under `"<rule id>":` — the rule the red names.
  `quality/rules.yaml` is template-owned and a fold overwrites it, so a count
  recorded there is a count that disappears at the next release. Do it at the fold
  that brought the app in, and shrink the number from there — it may not go up
  again without a person's diff. Nothing changes for a class you have already
  recorded, at zero or above.

- **Take `docs/product/architecture.md`'s house-rules section whole at the
  fold.** That file is PRODUCT-owned — your decisions, your divergence notes —
  and it is also where every house rule's `doc:` anchor points: a file and a
  phrase the engine's own consistency check requires to be present. Two rules
  changed their text in this release (the read rule grew a census, the event
  rule's refusal moved out of your service's transaction), so their anchors
  moved with them. Resolve that section to your older copy and the engine
  reports `rule <n>: doc docs/product/architecture.md no longer states the rule
  (anchor '…' missing)` — exit 2, enforcement broken, which outranks a pass and
  is not something a valve can quiet. Take our section, keep your own sections
  around it.

- **`--explain 54` now lists every read this tree asks for, the door that
  reaches it and the one line that opens it.** v2.1.0's Migrating item on rule
  54 (d)/(e) said a product's own `get_`/`list_` selectors are fixed by "one
  keyword-only `actor` plus `require(actor, "<kind>.read", …)`, or one
  `# read-open:` / `# read-kind:` marker" — and named no selector and no door,
  so the first product to meet the hard read rule at its own door
  (`GET /api/v1/memberships/mine/` answering *You may not read this
  membership.* to a hat-less caller) had to rebuild the list by reading
  `apps/core/authz.py` and then every `selectors.py` in the tree. Run
  `uv run python -m quality.gate --explain 54` and the `census (this tree):`
  block is that list: one line per selector in clause (d)'s population, each
  naming the file and line, the model and kind it hands back, the key it asks
  and **where that key resolves** (the row's own node, the acting hat, or the
  tenant-wide union when the caller has no hat — which is the case that 403s),
  who gets refused, the exact opening, and every door that reaches it. A
  selector that asks NOTHING is listed too and says so: it refuses nobody
  today, and it is the row that surprises you the day you grant somebody a
  narrow role. The census READS — it is rule 54's own walker, rule 55's
  third-argument classifier and rule 42's door walk, printed, with no fourth
  derivation to disagree with `allows()` — and it prints its own blind spots
  on its last line (a predicate, a grant written at runtime, which hat a given
  request resolves, and a selector a door reaches through a helper).
  (`quality/checks.py::reads_census`, `quality/rules.yaml` rule 54.)

- **Nothing signs in twice, and now eight tests say so — one of them across
  the two doors.** `accounts.services.record_zitadel_identity` returns early
  when the subject it is handed is the one the account already holds
  (`if user.zitadel_sub == cleaned: return user`). That line is what makes
  every login after the first a no-op instead of a `Conflict`, and a merge
  that resolved it away would lock every person in the deployment out at
  their SECOND sign-in — the account is theirs, the subject is theirs, and
  the door answers *That identity is already linked to a different account*.
  **Take the early return.** The instrument, if the merge is resolved wrong,
  is eight reds by name: `test_rp_login::test_a_second_login_reuses_the_user`,
  `::test_a_second_sign_in_does_not_double_join`,
  `::test_a_known_subject_signs_in_even_when_its_address_moved`,
  `test_signin_door::test_ours_records_the_subject_once`,
  `::test_a_later_next_cannot_repoint_a_proven_password`,
  `test_identity_join::test_the_same_subject_is_a_no_op_and_still_audited`,
  `test_identity_ledger::test_the_row_count_tracks_the_call_count_including_the_no_op`,
  and the new
  `test_signin_door::test_a_person_signs_in_again_through_the_other_door`,
  which is the one none of the other seven could see: they each drive ONE
  door twice, and this one drives a person through the hosted page and then
  through the deployment's own form, both orders. That the two doors name one
  person with one string is no longer assumed either — `manage.py
  zitadel_measure`'s new `M12 subject-is-session-user-id` opens one session
  and reads both halves off it (`factors.user.id` and an id_token's `sub`),
  and no id_token is `could not` rather than a pass.

- **If your verifier boxes are capped below the account's real limit, write
  the ceiling once: `./scripts/verifier_box.sh ceiling <n>`.** The cap now
  lives in a file outside every checkout and is shared by every lane on the
  machine, instead of being an environment variable each agent exports for
  itself — so a raise is typed once and everybody gets it. With no argument the
  command prints what is in force and where it came from; a value that is not a
  positive whole number is refused and the file is not written. Nothing to do
  if you never hit the cap: absent, the wrapper behaves exactly as it did.

- **Regenerate the API client against YOUR tree: `./scripts/gen_client.sh`, then
  `frontend/scripts/pin_client.sh --write`.** `frontend/openapi.json` and the
  TypeScript client under it are DERIVED from the schema a tree exports, and the
  copy a release ships is derived from ours. It is exactly right for the release
  and wrong for you the moment one of your own apps is in the schema — and the
  staleness is silent, because a generated client two schema changes old still
  compiles. There is deliberately no release leg for it: on the tag the file and
  the export agree to the byte, so a leg would be green on every tree we can
  measure and red only on yours. Our own bank regenerates it at the fold, which
  is why it stays true here and cannot stay true for you by itself.

- **If your CI's `setup-node` step carries `cache: pnpm`, give it a per-shard
  key or move the install into the `derive` job.** 2.1.0's workflow stopped
  running one gate: it asks the gate for its units, runs one `--leg <unit>` per
  runner with the suite split `k/N`, and composes a verdict. A single cache key
  under that matrix is written by every shard of the same run at once. Our own
  `ci.yml` has no `cache:` on that step, which is why nothing here reds, and
  there is no instrument for it: the file the problem lives in is yours, and an
  instrument over a product's own workflow is one this template may not write.

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
   **SUPERSEDED by [Unreleased], and left standing above rather than rewritten
   because it is what the 2.1.0 tag actually shipped.** Both halves of that
   last sentence instruct an edit to a TEMPLATE-OWNED file — the workflow's
   `env:` block and `drive_preamble.sh`'s lists — which the ownership table
   now makes a divergence you record rather than a step you take. Until the
   drawers those two grow in land (2.2.0: `scripts/local/env_keys`, and one
   optional CI step that runs `scripts/local/ci_env.sh` when it exists), do the
   edit AND write the line — `divergence: .github/workflows/ci.yml — our AWS
   keys, until the env-keys drawer lands` — in your own `architecture.md`, so
   `scripts/divergence_census.sh` reads it as the deliberate thing it is.
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
  | accounts | `accounts.user.deactivate` | `user.deactivate` |
  | accounts | `accounts.user.erase` | `user.erase` |
  | accounts | `identity_platform.configure` | `deployment.configure` |
  | accounts | `sso_identity.provision` | `sso_identity.create` |
  | comms | `device.register` | `device.create` |
  | comms | `message_engagement.record` | `message_engagement.create` |
  | comms | `preference.set` | `channel_preference.update` |
  | comms | `suppression_surge.record` | `suppression_surge.create` |
  | core | `membership.revoke` | `membership.delete` |
  | core | `organization.rename` | `organization.update` |
  | core | `tenant.configure` | `tenant.update` |
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

[2.5.0]: ../../compare/v2.4.1...v2.5.0
[2.4.1]: ../../compare/v2.4.0...v2.4.1
[2.4.0]: ../../compare/v2.3.0...v2.4.0
[2.3.0]: ../../compare/v2.2.1...v2.3.0
[2.2.1]: ../../compare/v2.2.0...v2.2.1
[2.2.0]: ../../compare/v2.1.7...v2.2.0
[2.1.7]: ../../compare/v2.1.6...v2.1.7
[2.1.6]: ../../compare/v2.1.5...v2.1.6
[2.1.5]: ../../compare/v2.1.4...v2.1.5
[2.1.4]: ../../compare/v2.1.3...v2.1.4
[2.1.3]: ../../compare/v2.1.2...v2.1.3
[2.1.2]: ../../compare/v2.1.1...v2.1.2
[2.1.1]: ../../compare/v2.1.0...v2.1.1
[2.1.0]: ../../compare/v2.0.0...v2.1.0
[2.0.0]: ../../compare/v1.1.0...v2.0.0
[1.1.0]: ../../compare/v1.0.0...v1.1.0
[1.0.0]: ../../tree/v1.0.0
