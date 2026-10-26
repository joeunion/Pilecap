# The platform partition and its input closure

**Status: DESIGN, ratified for the freeze dispatch. The build stays gated on
the freeze** (the standing ruling: a closure tuned against a moving core ships
subtly wrong). This file SHIPS; its manifest row is in `publication-manifest.md`.

Rules applied, by id: house rule 7 (the import side), the architect
checklist's closed-question line (every enumeration below is derived or
pinned, never a hand list of an open set), its instrument line (every
instrument declares `does_not_cover` and exits 2 when it cannot look), house
rule 18's freeze pattern (`FROZEN_FAMILIES` as the worked shape for a
written-down record), the gate's ledger semantics (`scripts/check.sh`,
`scripts/gate_ledger.sh` — exit 0/1/2, 2 outranks a pass).

---

## 1 · What the partition buys, and what a driven audit proved

A cloned product pays the platform's whole pytest suite on every full gate,
forever, even when nothing it did could have changed a platform verdict. The
partition's dividend: **the platform portion of the pytest suite is skipped
when a banked green verdict exists whose key still matches everything that
portion reads.** Product tests always run. The house-rules legs always run
over the whole tree — the partition is the **pytest suite only**.

A driven audit found four hazards against the design's own criteria, and this
design is shaped around them:

1. **The discovery loophole is real and worse than predicted.** A planted
   product app (`apps/<orders>/` with a `TAGS` dict) produced a **false red on
   three in-closure tests** — `apps/accounts/tests/test_scopes.py` ×2 and
   `apps/core/tests/test_contract_docs.py` ×1 — through
   `apps/core/api/frozen_families.py::FROZEN_FAMILIES`. Not a stale green: a red the
   clone cannot clear without editing in-closure files, so the closure hash
   moves on the product's first door. §5 answers it.
2. **The closure cannot derive from the manifest's ship-set rule** — that rule
   globs `apps/**` whole, product apps included; the manifest has no
   platform/product line. §2 designs the derivation that can actually be
   built.
3. **The criteria's enumeration missed two boundary files** —
   `apps/conftest.py` (the shared fixture module on the `apps` package; the
   criteria's phrase "root conftest" named it wrongly — there is no repo-root
   conftest in the closure's sense) and `compose.yaml` (read at test time:
   `apps/search/tests/test_chaos_drill.py::_pinned_image` reads its
   Meilisearch pin off disk, and `test_health` / `test_settings` /
   `test_presign_matrix` read it too; the postgres/redis/temporal pins are
   the same class — they are the services the suite actually runs against).
   §3 enumerates both.
4. **The soundness premise was misattributed.** The import-linter layers
   contract names only the fixed layers, is non-exhaustive by construction
   (`pyproject.toml` §[tool.importlinter]: "Only the FIXED layers are named
   here, and deliberately so"), and does not constrain platform→product
   imports. The real instrument is house rule 7 — whose `does_not_cover`
   exempts **imports inside tests**, exactly where the partition's inputs
   live. §6 re-bases soundness and declares the residual.

---

## 2 · The boundary, and its own derivation

**The platform set is a written-down record, not a live derivation:
`quality/partition.yaml` (the lockfile), created by the freeze build.** At the
freeze, the build runs the publication manifest's own export census
(`publish.sh`'s ship-set derivation over `git ls-files`; the closure and the
manifest are one census read twice) and writes the app labels found under
`apps/` into the lockfile. From that commit on, the lockfile is a record of
the past, kept in a diff a human reads — the `FROZEN_FAMILIES` pattern,
applied to apps: *written down rather than derived, and that is the point.* A
live derivation would agree with whatever a clone's tree said the moment it
said it, which is exactly the thing the boundary exists to remember.

At today's tree the population the freeze will record is the twelve apps:
`accounts, comms, connections, core, events, example, exports, files,
realtime, search, usage, workflows` — **stated here as evidence the census
ran, never as the mechanism.** The lockfile is the mechanism; this paragraph
goes stale the day the template grows an app, and nothing reads it.

**The fail-safe direction is the design's load-bearing choice: an app not in
the lockfile is outside the partition, and its tests ALWAYS run.** There is
no equality pin between the lockfile and the live app registry, on either
side, ever — in a clone the live registry is *supposed* to be a superset. A
platform app the template adds and forgets to list costs speed (its tests run
every time), never soundness (nothing about it is ever skipped). A product
app is simply never listed, which is the definition working. The only
directional check is cheap and loud: **a lockfile entry naming an app the
registry cannot find is exit 2** — a closure that claims territory it cannot
see may not bank a verdict about it.

Why not the alternatives this design rejects: §9.

---

## 3 · The input closure, file-class by file-class

The closure is the set of tree paths whose content the platform partition's
outcome depends on through the filesystem. It is enumerated **by class, with
the member list derived per class at hash time** (globs over `git ls-files`,
never a hand list of files), and the lockfile carries the class list. An
enumerated class that matches nothing, or a matched file that cannot be read,
is **exit 2** — the closure never silently narrows.

| # | file-class | members (derivation) | why it is an input |
|---|---|---|---|
| C1 | platform app code | `apps/<p>/**` for every `<p>` in the lockfile — including each app's `tests/` and `tests/conftest.py` | the partition's own tests and the code under them |
| C2 | the `apps`-package boundary files | `apps/__init__.py`, `apps/conftest.py`, `apps/testing/**`, `apps/conftest_local.py`, `apps/test_gate_liveness.py`, `apps/test_temporal_guard.py` | `apps/conftest.py` is the fixture module every platform test loads, and `apps/testing/**` the harness package behind it (and every product test too — it sits ON the boundary: a product that edits it invalidates the partition, which is correct, because it changed machinery the banked verdict ran on; a product extends fixtures in its own app's `tests/conftest.py`, which pytest scopes by directory ancestry and the platform tests never load). The two top-level test modules are platform tests outside any app directory |
| C3 | `config/**` | all of it | settings (including `config/settings/test.py`, which neutralizes the environment the criteria worried about, and `config/settings/discovery.py`, which derives `INSTALLED_APPS`), the mounts, the URL map, the one exception mapper |
| C4 | dependency truth | `pyproject.toml`, `uv.lock` | dependency behavior, and the pytest configuration itself — `DJANGO_SETTINGS_MODULE = "config.settings.test"`, addopts, the randomization policy — lives in `pyproject.toml` |
| C5 | `compose.yaml` | the one file | read at test time (confirmed: the chaos drill's `_pinned_image` regexes the Meilisearch pin out of it; `test_health`, `test_settings`, `test_presign_matrix` read it) — and its postgres/redis/temporal/meilisearch pins name the services the suite runs against, which is the same class of input whether or not a test reads the text |
| C6 | `manage.py` | the one file | the ship-set rule's third member; the entry point test paths shell through |
| C7 | gate data a partition test reads as data | `quality/rules.yaml` | `apps/core/tests/test_plant_sites.py` censuses the canary/negative plant sites out of it. A product that grows a `rules.yaml` allow-list entry (rule 3/17/25 exemptions live there) invalidates the partition — rare, and honest |

**The one enumerated exclusion — the product-append ledger.** The build moves
`FROZEN_FAMILIES` and `SANCTIONED_RENAMES` out of `apps/core/api/scopes.py`
into a data module, `apps/core/api/frozen_families.py`, which `scopes.py`
imports and re-exports unchanged. That module is **excluded from C1 by name
in the lockfile, with this reason recorded beside the exclusion**: it is the
one platform file whose *design* says a product appends to it in the commit
that ships a family ("a key joins this list in the commit that ships it" —
`scopes.py`'s own words). In-closure, that append moves the closure hash and
the discovery-loophole finding recurs; out-of-closure, the append reaches the
partition through the discovery digest (§4) instead — the family it freezes is
itself a digest member, so the re-run it triggers is the same re-run the new
family already triggered. Nothing else is excluded, and a second exclusion is
a design change, not an edit.

**Non-file inputs, enumerated:**

- **The environment.** `config/settings/test.py` (C3) is the neutralization
  seam — it pins what tests may see. The declared escapes: `DATABASE_NAME`
  (the one derivation override `scripts/db.sh` honors) and anything
  `config/settings/` reads from the environment that `test.py` does not pin.
  The build criterion: the partition tool records the names of the
  environment variables the settings actually read (the `guards.py` /
  `discovery.py` read-set) and refuses to bank a verdict when one of them is
  set to a non-default at run time, listing it — banked green under a bent
  environment is the stale-green class with no diff at all.
- **The running services.** The compose pins are in-closure (C5); the live
  daemons' state is not and cannot be. Residual, declared: a service upgraded
  in place without a pin change is invisible. Mitigation: the pins are the
  doctrine (`scripts/db.sh`, one compose stack) and drift from them is
  operator error the chaos drill's read-never-respell pattern already
  polices.
- **The virtualenv.** `uv.lock` is in-closure; a venv that drifts from the
  lock is invisible to any file hash. Residual, declared — it is the first
  of the two residuals the always-run nets are the belt for (§7).
- **The shared test-DB migration-interaction blind spot stays DECLARED**,
  with rule 22 and rung territory as the mitigations. Same class: a
  hand-written migration that alters schema without touching `models.py`
  changes what the model-registry digest cannot see.
- **The wall clock and the OS.** Declared, unmitigated, same as every other
  suite in this tree.

---

## 4 · The skip key: closure hash + discovery digest

The mechanism is **one more consumer of the gate-ledger pattern**
(`scripts/gate_ledger.sh`: a verdict banked under a key; a later run consults
the ledger and does not re-measure a green it can prove is still about this
tree). The partition's key has **two parts**, and both must match:

**Part 1 — the closure hash.** SHA-256 over the sorted `(path, blob-hash)`
pairs of every file the closure classes match (§3). Any in-closure edit moves
it. Computed from `git ls-files -s` over the class globs plus the working-tree
state of the named singletons — the same tree-honesty discipline the full
gate's ledger already has.

**Part 2 — the discovery digest.** The closure's files are not the
partition's whole input: platform behavior reaches through discovery —
`INSTALLED_APPS` derived from the `apps/*` walk, the mounts walking every
app's `api.py`/`mcp.py`, the search registry walking `search.py`, lifecycle
and integrations and SCHEDULES registering the same way — so platform tests
quantified over those populations change outcome while no closure file
changes. The digest closes exactly that hole: **a canonical serialization,
hashed, of every discovered population, read through the same walks the
platform reads them and serialized from the loaded registry** — not from a
second, hand-kept list of conventional filenames (rejected in §9: a file-name
list re-derives by hand what discovery already derives, and goes stale the
day a new seam lands). The digest's sections, which are the seam census:

| section | what is serialized |
|---|---|
| apps | installed app labels + each `AppConfig`'s `depends_on` and `optional` |
| REST | the OpenAPI document, canonically serialized (paths, operations, tags, schemas, docstring-derived summaries/descriptions — the whole contract surface) |
| MCP | the tool registry: names, argument/output schemas, descriptions |
| models | every registered model: label, fields with types, the scoped base it inherits, `append_only`, `derive_org_from`, `InheritedDownward` |
| events | every app's declared event names — the tree has no payload versions to serialize, and `quality/partition.yaml`'s own note says so: serialized as it is, not as it was hoped |
| search | the declared kinds and their `Searchable` shapes |
| lifecycle | the discovered lifecycle providers and what each declares |
| integrations | the declared integrations population — key, title, declaring module, probe class; never probe `status`, which moves with the machine and not the tree |
| schedules | the discovered SCHEDULES entries |
| scope families | `families()` and the frozen ledger (`frozen_families.py` — the §3 exclusion re-enters the key here) |
| policies | the discovered `policies.py` population — every action name mapped to its predicate's dotted identity, plus the declared `ACTION_PROSE` keys |
| meters | every app's declared `meters.py` names, by app label |
| sockets | the discovered `consumers.py` websocket URL patterns — the route and its name; the fifth door |

**Thirteen sections, and the live list is `quality/partition.yaml`'s** — this
table predicts it, and a disagreement between the two is a bug in this file.
The design's first draft named ten; the build's own AST seam census (below)
found three walks no section covered — policies, meters, sockets — and they
joined the digest in the build commit. That is the census doing on its first
run exactly what this section promises it will do for every future seam.

The seam census is a **closed question over a discoverable population**: the
build criterion pins it with an AST census over the platform apps — every
platform module that performs the discovery walk shape
(`importlib.util.find_spec` / `import_module` over `f"{config.name}.…"`) must
belong to a digest section, exit 1 naming the walk when one does not, so a
future discovery seam joins the digest in the commit that lands it or the
gate says so. `does_not_cover`, declared: a discovery seam written in a shape
the AST census does not recognize — the checklist's instrument line, honored
by stating it.

**The decision table — what invalidates what:**

| the edit | closure hash | digest | consequence |
|---|---|---|---|
| product `services.py`, `selectors.py`, its own tests, its migrations¹ | unchanged | unchanged | **skip — the dividend, and it is sound**: no platform test reads any of it — *checked*, both halves: `partition.py::read_census` (a path a platform test builds) and `partition.py::import_census` (a module a platform test imports)² |
| product adds an app, a route, a tool, a model, a kind, an event, a lifecycle/integration/schedule entry, a policy action (`policies.py`), a meter (`meters.py`) or a socket route (`consumers.py`) — or edits a door's docstring or schema | unchanged | **moves** | **one honest re-run**, then re-banked under the new digest |
| any in-closure file | **moves** | — | full partition re-run, re-banked |
| the environment bends (a read env var set non-default) | — | — | verdict runs but is **not banked**, reason printed |

¹ a migration that changes what the model registry shows changes the digest
through the models section next time apps load; one that changes schema
without touching the registry is the declared §3 residual.

² **Row 1's sentence is a CHECKED rule, not a claim this file makes on the
code's behalf.** It used to be prose, and prose is what a skip is worth when
nobody is measuring it: a platform test that reaches into a product app makes
row 1 false for that tree, silently, because a product-only edit moves neither
key part while changing that test's answer. Two censuses close it, both in
`quality/partition.py`, both run by `selftest` and therefore on **every path
that can take the skip** — `decide()` calls `selftest()` before it ever consults
the ledger, so an instrument gating a skip is never behind the skip:

- **`read_census`** — the file-read half. A path a platform test BUILDS
  (`BASE_DIR / "x" / "y"`) must be a closure member. It is what found C8 at the
  freeze, and what found C9 afterwards (`templates/**`, which
  `apps/accounts/tests/test_entrance_chain.py` walks with `rglob`).
- **`import_census`** — the import half. No platform test module may import
  `apps.<product>`, the product set DERIVED as every app directory carrying an
  `apps.py` that `partition.yaml`'s `platform_apps` does not claim. The source
  is the sibling platform's own import-census ruling (road (a)), where the
  class was measured live rather than hypothesised.

**`import_census` is born non-vacuous, and that is load-bearing on this tree.**
Every app here is a platform app, so the derived product population is EMPTY and
a green from the live census asserts over nothing. `canary_import_census` (§8.4)
is what makes it falsifiable: it plants a real product app and a platform test
importing it into a temporary tree, drives the real census over it, and requires
the finding — a canary that does not fire is exit 2, not a pass. Its negative is
the always-legal direction, a product test importing a platform module, and that
stays silent because a product app's tests are not in the platform test
population at all.

**The declared residue, shared honestly with the sibling platform's blind spot
1: BEHAVIORAL coupling.** An import census sees names, so a platform test that
reaches a product app without naming it is invisible to it — through a database
row the product's migrations created, a fixture the product registered, a
registry entry discovered at run time, or an event payload consumed by shape.
So is an import assembled at run time from a computed string. That residue is
stated in `quality/partition.yaml`'s `does_not_cover`, which `selftest` prints
on every run that relies on it.

**Siting a plant, for anyone writing a drive against this table** (doctrine
line from the planted-miss siting ruling; prose now — PART-1's §8.4 canary is
where it is already enforced, and it is cited as the worked example below):

> **A platform-app plant is invisible to a skipped partition.** A drive that
> plants a deliberate miss — a canary, a fixture, a scratch module — and then
> asks whether the suite notices, must site that plant where the suite it is
> measuring will actually look. Plant it in a platform app and a SKIPPED
> partition never runs the test that would have found it, so the drive measures
> the skip rather than the miss and reports a false green. **A planted-miss
> drive therefore sites its plant in a product app outside the touched
> closure** — the population row 1 of this table calls `skip`, which is the same
> population `partition.py::product_paths` hands pytest under a skip. **And on
> THIS template's tree, where every app is a platform app, there is no such
> app to site it in: the drive CREATES a throwaway product app** (a directory
> with an `apps.py`, absent from `platform_apps`) and sites the plant there.
> The qualifying condition — which apps are product apps — is **re-derived from
> `quality/partition.yaml` at drive time**, by
> `partition.py::product_app_labels`, and is never a hand list: a hand list is a
> record of what was true when somebody typed it, and the whole hazard here is a
> drive that is measuring a world that has moved.

*Evidence, first-hand and in this tree:* `canary_import_census` (§8.4) is
exactly that drive. Its check's live population is empty — `platform_apps`
names all thirteen app labels — so the canary could not be sited in any existing
app and had to build a scratch product app in a temporary tree to have anything
to find. Without it the import census would have shipped green over an empty
quantifier, which is the failure this line exists to prevent. The sibling
platform's own import-census ruling reached the same place from the other side:
it could measure its class live because its tree HAS product apps, and ours
does not.

*(An earlier draft of row 1 listed `policies.py` as a skip. A doorless plant
carrying only a `policies.py` entry moved the digest, because the policies
section serializes exactly that population — the table was stale, not the
code. It now predicts what the code does, which is the only job a predictive
table has.)*

**The honest boundary statement:** the dividend ends at the **registration
surface, per edit, and re-banks**. A product's everyday iteration — business
logic, its own tests, its selectors and policies — never pays for the
platform suite. An edit to what the product *publishes into the shared
contract* (a door, a model, a declared population member) buys exactly one
platform re-verdict, which is the platform re-checking a contract that
genuinely changed — the system working, not the dividend failing. After §5's
dispositions, that re-run is **green on a healthy product** — healthy meaning
it declares what the dispositions require: the freeze append (D1), the plane
on its families (D2), examples on its own schema fields (D5).

**Exit semantics, inherited whole:** 0 skip-or-green · 1 violations · 2
enforcement broken. Exit 2, specifically: an unmatchable closure class, an
unreadable closure member, a lockfile app the registry cannot find, a digest
section that cannot serialize, a canary that fails to fire (§8), a ledger row
whose key cannot be parsed. 2 outranks a pass, and a mistyped invocation is
never a silent full run — the gate's own clause, one more consumer.

---

## 5 · The discovery hazard: the census, and the dispositions

The design promised a census of **registry-quantified assertions in the
platform partition** — every test whose assertion quantifier ranges over a
discovered population, so that a product app changes its outcome with no
closure edit. This census has now been run. Method: a sweep of
`apps/*/tests/**` and `apps/conftest.py` for the discovery read shapes
(`get_app_configs` / `INSTALLED_APPS` / `get_models`, `families()` /
`vocabulary()` / `FROZEN_FAMILIES`, the OpenAPI document fixture, the MCP
`tools/list` walk, the search/lifecycle/integrations/SCHEDULES registries,
and gate data read as test input), then per-file confirmation of what the
quantifier actually ranges over. `does_not_cover`, declared: a test that
quantifies over a discovered population through a read shape not in that
list — the build's AST seam census (§4) is the standing check that keeps
this census's method from going stale.

**The census** (population · where quantified · disposition):

| seam | quantified assertions (files; representative tests) | disposition |
|---|---|---|
| **scope families** (`TAGS` in every installed app's `api.py`) | `apps/accounts/tests/test_scopes.py` — the freeze pins (`test_the_frozen_census_is_the_whole_live_vocabulary` :335, `test_every_frozen_family_key_is_still_live` :329, `test_the_vocabulary_is_every_section_crossed_with_read_and_write` :81, `test_every_published_operation_derives_its_scope` :390); `apps/core/tests/test_contract_docs.py` — the two-planes overview census (:913, asserts every live family appears in exactly one documented plane); `apps/comms/tests/test_devices.py`; `apps/core/tests/test_mcp_scopes.py` (`test_every_registered_tool_derives_its_scope` :278 and the twinless census :292–:336) | **the three worked dispositions below** (D1–D3); the derivation tests (:390, :278) stay globally quantified — a product route/tool that cannot derive its scope is a true red — and are digest-covered |
| **the OpenAPI document** (the mount's walk over every app's `api.py`) | `apps/core/tests/test_contract_docs.py` (~40 "every operation…" assertions: editorial standard, refusal enumeration, pagination documentation, example ratchet); `apps/core/tests/test_resource_first_urls.py` (ADR api-2 over the whole document); `apps/core/tests/test_door_schema_parity.py` | **keep globally quantified, digest-covered**: these are the house contract's pytest-side teeth and product routes SHOULD be held to them; a red here on a product route is a true red the product clears in its own `api.py` (out-of-closure). The digest's REST section covers docstring content, so the skip never goes stale on them |
| **the MCP tool registry** (`tools/list`) | `apps/core/tests/test_mcp.py`, `test_mcp_arguments.py`, `test_mcp_throttling.py`, `test_mcp_scopes.py`; per-app `test_mcp.py` files (app-scoped quantifiers — already partition-safe) | keep globally quantified, digest-covered (MCP section) |
| **the model registry** (`get_models()`) | `apps/accounts/tests/test_erasure_residue.py` (the whole-schema PII sweep — the table list is derived, its docstring's own design); `apps/exports/tests/test_census.py` (`dispositions()` derived + `test_the_census_at_this_tree_is_pinned` :226 — a hand-pinned EXPECTED set, and its own :245 test proves a planted scoped model breaks the pin); `apps/core/tests/test_append_only_belt.py` (the declared `append_only` population) | erasure sweep and append-only belt: **keep globally quantified, digest-covered** — a product model the erasure misses or a product ledger that can be updated is a true red, cleared in the product's own `lifecycle.py` / model (out-of-closure). The exports pin: **D4 below** |
| **app registry / INSTALLED_APPS** | `apps/core/tests/test_optional_apps.py`, `test_settings.py`, `test_introspect.py`, `test_index.py` (every href derived from the live URL conf — derived on both sides, green by construction under growth) | keep, digest-covered (apps section) |
| **lifecycle registry** (`apps/<x>/lifecycle.py` walk) | `apps/core/tests/test_lifecycle.py` + per-app `test_lifecycle.py` | keep, digest-covered (lifecycle section) |
| **integrations census** | `apps/core/tests/test_integrations.py`, `apps/files/tests/test_integrations.py` (the no-surface-holds-a-list tooth) | keep, digest-covered (integrations section) |
| **search registry** (`apps/<x>/search.py` walk) | `apps/search/tests/test_registry_validation.py` (boot refusals), `test_kinds_vocabulary.py` (:196 route-doc kinds vs declarable kinds; :213 catalogue-derived-not-listed) | keep, digest-covered (search section) |
| **SCHEDULES** | `apps/workflows/tests/test_reconciler.py` (the reconciler's census over discovered schedules) | keep, digest-covered (schedules section) |
| **gate data as test input** | `apps/core/tests/test_plant_sites.py` (the plant-site census over `quality/rules.yaml`) | quantifies over closure file C7, not over discovery — in-closure, no disposition needed |

**The five worked dispositions — the false reds this design's audit drove,
each killed by mechanism or named with its out-of-closure clearing path:**

- **D1 — the freeze census moves out of the closure** (§3's exclusion).
  `test_the_frozen_census_is_the_whole_live_vocabulary` keeps its exact
  meaning: a product that ships a family and does not freeze it goes red **by
  name, on the honest re-run the new family's digest change already
  triggered** — and now clears it by appending to
  `apps/core/api/frozen_families.py`, an out-of-closure edit. The false red
  becomes the designed red, and the closure hash no longer moves on the
  product's first door.
- **D2 — the two-planes overview census becomes declaration-rendered.** Today
  the overview's plane assignments live in in-closure prose, so a product
  family can join no plane without an in-closure edit. The build moves the
  plane to the family's own declaration — each `TAGS` entry carries
  `plane: "everyday" | "administrative"` beside the display name it already
  carries — and the overview renders the planes from the registry. The census
  test keeps asserting exactly what it asserts (every live family in exactly
  one plane, neither plane empty) and now holds by construction for a product
  that declares, red-by-name for one that does not, cleared in the product's
  own `api.py`. The same property the whole platform claims: *an app that
  grows a tagged router grows the vocabulary with no file outside that app
  edited* — extended to the documentation of that vocabulary.
- **D3 — `test_the_vocabulary_is_every_section_crossed_with_read_and_write`**
  (:81) already computes both sides from discovery (families vs the
  document's tag walk) and stays green under healthy growth; a mismatch is a
  true red (a `TAGS` key with no mounted router, or the reverse — the planted
  `apps/<orders>/` with a bare TAGS dict is precisely this shape, and the red
  is the test doing its job on a malformed app). No change; recorded so the
  census is complete.
- **D4 — the exports pin scopes its population to the lockfile.**
  `test_the_census_at_this_tree_is_pinned` exists to pin *the platform's own
  tree* ("Pinned is a property of THIS TREE" — its own docstring), so its
  quantifier gains the boundary the prose always meant:
  `dispositions()` restricted to lockfile apps == EXPECTED. The derived-side
  tests (`test_the_census_is_the_registry_minus_the_exclusions`,
  `test_the_population_is_every_model_carrying_a_tenant`) stay global —
  product models must join the archive census, and do, derived. A product
  pins its own tree in its own test if it wants the same discipline (the
  skeleton pattern: the format is the value).
- **D5 — the example-census ratchet holds a product to full declaration.**
  A follow-up verification drove a **third** clearing edit beyond D1/D2's
  two: `test_the_declared_example_census_is_at_or_below_its_ratchet`
  (`apps/core/tests/test_contract_docs.py:161`) reads its ceiling out of
  `quality/rules.yaml` (rule 41's `undeclared_example_fields` — in-closure,
  C7), so a product schema field with no declared example lands on top of the
  platform's grandfathered backlog and tips the count over the ceiling on the
  honest re-run its own route already triggered. **The clearing path is
  out-of-closure:** declare `example` on your own fields, in your own
  `schemas.py` — the red clears from the product's seat and no in-closure
  file moves, so soundness holds. The honest note, stated rather than dressed
  up: this holds a product to **100% example declaration from its first
  field** while the platform itself ships a large grandfathered backlog — and
  a ceiling in a central in-closure file is exactly the shape the generalized
  rule below names. It stands, for now, on the one property that distinguishes
  it from the defect class: the product's clearing edit is its own
  declaration, never an edit to the central file. The day a product
  legitimately needs a grandfathered backlog of its own, the rule below
  already prescribes the only two acceptable moves — scope the quantifier to
  the lockfile population, or move the ceiling out-of-closure so it re-enters
  the skip key through the digest — and a review refuses anything else.

**The generalized rule, for every future platform assertion (doctrine, cited
into the architect checklist at the build):** a platform test that needs a
per-member fact about a discovered population sources that fact from **the
member's own declaration**, never from a central in-closure file; a central
ledger that products must append to (a freeze census, an accepted-exemption
list) either lives out-of-closure as a data module that re-enters the skip
key through the digest, or the assertion scopes its quantifier to the
lockfile population. An in-closure file a product must edit to stay green is
the defect class this design's audit drove, and it is now a named shape a
review can refuse.

---

## 6 · Soundness, re-based

**What was claimed:** the partition's soundness rests on the import-linter
layers contract — platform never imports product. **What is true, confirmed:**
the layers contract names only
`workflows|events|connections|realtime → accounts → core`, is non-exhaustive
by design, and says nothing about product apps; the forbidden contract only
bars `apps → config`. House rule 7 (`depends_on` vs the real import graph) is
the real static instrument, and its `does_not_cover` exempts imports inside
tests — where the partition's inputs live.

**What actually holds the boundary, in order of strength:**

1. **The closure itself.** Platform test files and platform app code are
   in-closure; they cannot come to read product code without an in-closure
   edit, which moves the hash. This is the strongest holder and it needs no
   import analysis at all — it is the reason the partition can be sound while
   rule 7 exempts tests.
2. **Template-tree absence.** A platform module or test that statically
   imported a product module would `ImportError` in the template's own CI,
   where no product app exists. Platform→product static imports are
   impossible to ship, not merely forbidden.
3. **House rule 7**, for the non-test halves: a platform `apps.py` cannot
   grow a product entry in `depends_on` without an in-closure edit, and an
   undeclared import is rule 7's own violation.
4. **The discovery digest** (§4), for the channel none of the above can see:
   platform behavior *reading* product declarations through the registry
   walks — the live loophole the driven audit found. The digest does not
   prevent the read; it makes the read's input part of the skip key, which is
   what soundness requires of an input.

**The declared residual, in full:** venv-vs-lock drift (§3); the live state
of the compose services (§3); a hand migration that changes schema invisibly
to the model registry (§3); an environment variable the settings read that
the run-time check's read-set derivation misses; a discovery seam written in
a shape the AST seam census does not recognize (§4); and the import-linter
contracts, which continue to hold exactly what they held — the fixed layers
and the config direction — and are **no longer cited as the partition's
foundation anywhere**. The first two are what §7's nets are the belt for;
the rest are declared blind spots with their mitigations named where they are
declared.

---

## 7 · The four always-run frozen nets — named in this shipping file

The nets run on **every** full gate, banked verdict or not. This file ships,
and the build lands the enumeration executably (an `ALWAYS_RUN` tuple in the
partition tool, with a census test pinning every listed path to an existing
collected module — a listed net that collects zero tests is exit 2, the
liveness clause).

All four are in `apps/accounts/tests/`, inside the platform partition, and
each is kept always-run because it is the belt for the two residuals no file
closure can hold — **venv-vs-lock drift and defects in the skip machinery
itself** — applied at the highest-consequence surface the platform has: the
credential doors, where a silent regression is an incident, not a bug.

| net | what it catches that a skipped partition cannot |
|---|---|
| `test_auth_over_the_wire.py` | the wire truth of `API_AUTH` under the **real ASGI stack** — real `CsrfViewMiddleware`, real session cookie, real bearer path. Its founding defect (a bearer `POST` answering 403 "CSRF check Failed" while every test was green) arrived through dependency behavior, not through any file this repo edits — the venv-drift class, live at the front door |
| `test_a9_matrix.py` | the twenty-two enumerated identity properties as a countable matrix. It is the regression net over the identity *engine* — the layer most coupled to installed dependency versions (allauth, jwt) and least visible in any diff of ours |
| `test_rp_login.py` | the browser door driven end-to-end against a real in-process OpenID Connect issuer: allauth's actual state store, PKCE verifier, token exchange, `jwt.decode` with issuer/audience/expiry enforced. Protocol-level behavior that changes under a dependency bump the lock records but a drifted venv does not honor |
| `test_mcp_oauth.py` | the machine door as an OAuth 2.1 resource server over real Streamable HTTP — the same class as `rp_login` for the door agents use, where nobody human is watching the failure happen |

**The honest finding:** none of the four is shaped to catch the discovery
hazard — and **no fifth net should be**. A net runs tests; the discovery
hazard lives in the *decision not to run*, and a net quantified over the
registries would catch a product's false red only after the product shipped
its door, while telling us nothing about the skip key's health on the trees
where nothing was planted. The hazard is answered where it lives: in the key
(§4's digest) and in the canary that proves the key moves (§8), which fires
at self-test time on every run — strictly earlier, and about the machinery
rather than about one lucky plant. The four stand as named; their job was
never this one.

---

## 8 · The canary set

House canary discipline, inherited: planted through the real scope at
self-test time; a canary that does not fire is **exit 2, not a pass**;
negatives stay silent; `does_not_cover` is stated where the canary is
declared. The partition tool self-tests before its first real decision on
every run that would consult the ledger.

1. **The born-with clause, per file-class.** For each closure class in §3,
   the self-test perturbs one member (an overlay copy — never the working
   tree) and recomputes: the closure hash **must** differ. Any class whose
   perturbation fails to move the hash is exit 2 by name. This is "an
   in-closure edit that fails to invalidate = exit 2", made total over the
   classes rather than sampled.
2. **The planted product app.** The self-test materializes a scratch app
   (`apps.py` + an `api.py` carrying a `TAGS` dict — exactly the shape the
   discovery-loophole finding drove) into an overlay, computes the discovery
   digest with and without it in a subprocess registry, and requires: the
   digest **differs**, and the skip decision with the plant present is
   **refused** against a verdict banked without it. A digest that fails to
   see the plant is exit 2 — the partition may not claim a planted product
   app is provably unread when its own instrument cannot tell the difference.
3. **The negative.** A perturbation outside the closure and outside every
   discovery seam (a scratch file under a product-shaped path that no walk
   discovers, e.g. a `services.py` body edit in the overlay app *after*
   banking with it present) moves neither key part. **A negative that fires
   is a finding, not a pass**: the closure has silently over-reached and the
   dividend is gone — printed loudly, exit 1.
4. **The stale-ledger forge.** The self-test writes a ledger row whose key
   mismatches the current tree in each part separately (closure moved, digest
   moved) and requires the skip refused both times; a forged row with an
   unparseable key is exit 2.

`does_not_cover`, declared for the set: the canaries prove the *instrument*
(hash and digest move when they must); they do not prove the banked verdict
was honest when it was banked — that is the full run's own job — and they do
not exercise the §6 residuals (venv drift, live service state), which is
§7's declared territory.

---

## 9 · Rejected alternatives

- **Derive the platform set from the manifest's ship-set rule at run time** —
  *rejected:* it cannot: that rule globs `apps/**` whole, product apps
  included, and the manifest has no platform/product line; a clone applying
  it would call its own apps platform. The manifest's census is the
  lockfile's **source at the freeze** (one census read twice), never its live
  derivation. *Trigger to revisit:* the manifest ever grows a
  platform/product distinction of its own — then the lockfile derives from
  it and the freeze step collapses.
- **A `platform = True` marker on `AppConfig`** — *rejected:* it puts the
  boundary in code the product owns and edits (any product can type the
  marker, and discovery would believe it — the partition would then *skip on
  the product's own say-so*); it duplicates what a one-file record says
  better; and it makes the platform set a live derivation again, which §2
  rejects on principle. *Trigger:* never for the boundary; a marker may
  someday serve documentation, which is a different job.
- **Pull the discovery inputs' FILES into the closure** (product
  `api.py`/`models.py`/etc. hashed into part 1) — *rejected as the mechanism,
  absorbed as the insight:* a file-name list of "conventionally discovered
  files" re-derives discovery by hand — the general hand-list-of-an-open-set
  failure shape — and goes stale the day a seam lands; hashing product file
  *content* also invalidates on comment edits the registry never sees. The
  digest (§4) is this alternative done at the right layer: the discovered
  *population*, read through the real walks, joins the key instead of the
  files.
- **Whole `apps/**` in the closure** — *rejected:* dividend-eating in full;
  every product commit invalidates and the skip never fires. It is what a
  clone has today, which is the problem statement.
- **An exhaustive import-linter contract naming every app** — *rejected:*
  its own pyproject comment already rejects it (a shared file edited by
  every rung that adds an app — the collision the discovery design removed),
  and import contracts cannot see the discovery channel at all, which is the
  channel that matters (§6).
- **A fifth always-run net quantified over the registries** — *rejected:*
  §7's honest finding — it fires after the hazard ships instead of proving
  the machinery before it decides, and it taxes every run to catch what the
  self-test canary catches earlier and closer to the cause.
- **Per-app freeze ledgers** (each app freezing its own families beside its
  `TAGS`) — *rejected:* a vanished app deletes its own memory, and the
  freeze census exists precisely to outlive the thing it remembers. The
  central ledger stays; it moves out of the closure instead (§3, D1).
- **No partition at all** (the honest fallback if the residual were ruled
  unacceptable) — *rejected while the dividend holds:* the full suite's cost
  in a clone is paid on every gate forever, and §6's residuals are belted
  (§7) and declared rather than silent. *Trigger to revisit:* an incident in
  which a banked skip masked a real platform regression that the canaries,
  the digest and the nets all missed — one such incident reopens this whole
  file.

---

## 10 · Provenance citations in the shipped artifact

A published tree can carry bare provenance citations — an id that names *why
a line exists and what was paid to learn it* — at sites that resolve nowhere
in the shipped artifact once the archive that would resolve them trims. The
lesson each citation points at is not lost: it survives in shipped form
(`rules.yaml`'s paid-for canaries and negatives, the skills' recorded miss
shapes, the ledger skeletons' worked examples), which is the manifest's own
design for how history reaches a product.

**Current policy:** a shipped artifact carries **no bare provenance
citations at all** — the export census (`scripts/publish.sh`) refuses one on
sight. An earlier ruling tolerated a bare id as a harmless, self-labeling
loose end, on the reasoning that a citation with no shipped target is
provenance, not contract, and that the citation itself modeled the discipline
it named. That reasoning is superseded: a stranger reading the shipped
artifact cannot tell a live citation from a dead one without leaving the
tree, and a check that refuses the pattern outright is cheaper to trust than
a rule a reader has to hold in their head. What still holds from the earlier
ruling: a path or link that resolves into a trimmed location remains a
violation regardless — that was never in question.

---

## 11 · What the freeze build must deliver (the criteria, for the dispatch)

One rung, mechanism territory (`quality/` + `scripts/` + the named app-file
moves), no product code. Cites: the checklist's closed-question, instrument,
and reader lines; rules 7, 18 (the freeze pattern), the gate's exit
semantics.

1. `quality/partition.yaml` written from the manifest census at the freeze
   (§2), with the closure classes (§3), the one recorded exclusion, and the
   seam census (§4). *Absent:* the partition tool exits 2 naming the missing
   lockfile.
2. The partition tool (`quality/partition.py` or the build's equivalent under
   `quality/`), computing both key parts, consulting/banking through
   `scripts/gate_ledger.sh`, self-testing §8's canaries before its first
   decision. *Absent/broken:* exit 2 per §4's enumerated causes; a canary
   that fails to fire is exit 2 at self-test, never a skip.
3. `scripts/check.sh`: the full gate's pytest leg consults the partition
   ledger and prints, on every run, whether the platform portion ran or was
   skipped and under which key — the leg never lets "which happened" be
   inferred. `--loop` is untouched (its tiering already scopes by rung app).
4. The D1–D2–D4 moves (§5): `frozen_families.py` extracted and excluded;
   `plane` into `TAGS` with the overview rendering from the registry; the
   exports pin scoped to the lockfile. Each with its census test still
   passing and — for D1 and D2 — a driven probe showing the product-shaped
   edit that clears the red is out-of-closure. *Absent:* the planted
   `apps/<orders>/` still false-reds the trio, which is the regression drive
   the freeze build must run.
5. The AST seam census (§4) as a partition self-check: every discovery walk
   in platform apps belongs to a digest section, exit 1 naming the stray.
6. The `ALWAYS_RUN` tuple (§7) with its liveness pin (a listed net that
   collects zero tests = exit 2).
7. The environment read-set check (§3's non-file inputs): a bent environment
   runs but does not bank, printed.
8. Whoever builds does not decide done: a separate verifier re-drives the
   planted-app regression (the §8.2 canary run for real, plus the D1/D2
   clearing edits driven from a product-shaped seat) and the born-with
   perturbation for at least two closure classes of the verifier's own
   choosing.

**Blind-spot list for the build (honest):** the digest's canonical
serialization must be stable across Python/dependency versions or every
`uv.lock` bump re-runs the partition spuriously (acceptable — in-closure
anyway — but the serialization must not depend on dict ordering or repr
details that vary within one tree state, which the twice-computed self-test
only partially proves); the overlay-plant canary loads the app registry in a
subprocess, and a settings cache or sys.path subtlety could make the plant
invisible for a reason the exit-2 clause would catch but not explain — the
build should print the digest section that failed to move; the lockfile's
fail-safe direction means a template-side platform app omitted from the
lockfile silently always-runs — cheap, but nothing names it, so the build's
template-side CI may add a one-line advisory (not a gate rule: a clone must
never fail on the superset that is its normal state).

---

## 12 · Where this file lives

`docs/product/partition-closure.md` — **SHIP** (row added to the manifest's
per-file dispositions in this commit). It ships because this design is
SHIP-LIST (the cloned products' dividend) and because the four nets'
enumeration and the partition's residuals must be readable in the artifact
that carries the mechanism. At the freeze build, the ADR line for the
cross-app decisions here (the `frozen_families.py` extraction, the `TAGS`
plane, the exports pin scope) lands in `architecture.md` per its ADR-home
rule, citing this file.
