# ADR gate-7

**ADR gate-7 · the gate reads the product's declarations; the product never imports the gate.**

**Context.** `quality/` is excluded from the image (`.dockerignore:43`) with three data files re-added one line at a time, each with its reason. Three function-level imports in `apps/core/management/commands/declare.py` and seven string imports under `apps/core/scaffold/` reach `quality.*`; two `ignore_imports` wildcards (`pyproject.toml:419,:501`) tell import-linter not to look. In the other direction 24 gate modules import `apps.core.roads` (stdlib-only by design) and one chain reaches `django.db` through a single constant (`apps/core/reach.py:11 → lifecycle.py:89`), so `python -m quality.gate --rules` needs the venv. Nothing in the contracts says which direction is legal, and the container ships three commands that cannot import.

**Decision.** (1) `apps.core.roads`, `apps.core.reach` and a new `apps.core.reason_floor` (holding `MIN_REASON`) are **declaration leaves**: standard library plus `yaml`, pinned by a test that imports them with Django absent. The gate may import a leaf; a leaf imports nothing above it. (2) The product never imports the gate, enforced by an import-linter `forbidden` contract `apps → quality` whose only exemptions are the modules a `DEV_ONLY` tuple on `CoreConfig` names (`scaffold/**`, `declare`, `newapp`, `scaffold` commands); a census (the `quality_reader` spellings of `apps/testing/tier.py:659`) proves every quality-reading module is on the list, `.dockerignore` excludes exactly the list, and a test imports every surviving `apps/**` module with `quality/` off the path. (3) The relocation of the dev-only modules under `quality/` is a 2.6 row with the `DEV_ONLY` list as its seam; the two wildcards are deleted in this ADR's rung.

**Consequences.** `--rules` runs on bare Python; the image's `manage.py` is honest about what it carries; an undeclared edge in either direction is exit 1 at `--fast` (`import-linter` leg) and the census names the module. A product that trims `apps/core/roads.py` breaks a leaf pin, not the gate's import graph silently. `ratchet_floors` stay on the `AppConfig` (ADR gate-6, ADR platform-partition-1).

**Rejected.** A third root package for three names (P1, P11; `pilecap`'s init is Django-bound). Moving `road` into `quality/` (the image excludes it). The relocation in 2.5.0 (the dogfood re-runs that road; `quality.*`'s rule-91 floor would rise — a raise is the owner's). Moving `ratchet_floors` to a central file (partition-closure §5).

**Trigger to revisit.** The `DEV_ONLY` list grows past the scaffold and the three commands — a fourth kind of dev-only module means the boundary wants a directory, and E lands then.

*Owner's signature:* Joe (owner), 2026-10-23 — "1. sign. 2. sign. 3. yes to both. 4. go. 5. we can cut it as the candidate, then run the same exercise with the fable 5 senior devs for critique" (the owner's words on the five decisions as the PM put them, `cycles/2026-10-23-critique-fixes.md § Rulings`), landed by the PM's rung CQ-DOCS-M0 in the owner's words, dated.

## As built (2026-10-23)

The signed text above is unchanged. What the build found that the draft did not say, from the
two commits that built A + D (`fed197fce`, then `c3c1d22cc` and `4f6205b7c`):

- **Two Django-dragging chains, not one.** The draft named the `reach.py → lifecycle.py` chain.
  The second was found once the first was cut: `quality/engine/world.py → quality/worlds.py →
  config/settings/discovery.py`, whose module-level `ImproperlyConfigured` import pulled in
  `django.core`. That import now sits inside the discovery refusal path, so the module loads
  without Django.
- **Five leaves, not three.** `apps.core.roads`, `apps.core.reach`, `apps.core.reason_floor`
  (new; it holds `MIN_REASON`, and `lifecycle` and `reach` both import it), `apps.core.lexicon`
  and `config.settings.discovery`. The pin is the `LEAVES` tuple in `quality.tests.test_leaves`.
  Under `python -I -P` with Django blocked, each leaf imports and loads nothing beyond the
  standard library, `yaml` and the other leaves. `apps.core.lifecycle` is the negative: it must
  fail the same probe. `python -m quality.gate --rules` on a bare interpreter has two pins in
  `quality.tests.test_engine_cli`. One runs on a system `python3` and skips, giving the reason,
  when none has `yaml`. The other runs in the venv with Django blocked.
- **The `forbidden` contract `quality → apps`** lives in `pyproject.toml`. Its `ignore_imports`
  allow-list admits five classes, each with a one-line reason: the leaves; the scaffold's fence
  grammar (dev-only, Django-free today); the lazy readers that import the product inside a
  function under Django in the venv; the SDK census reading the `pilecap` facade; and the
  gate's own tests. A planted `quality → apps.core.models` edge is BROKEN and named. A planted
  edge to a leaf is KEPT.
- **The `DEV_ONLY` list and its seam.** `CoreConfig.DEV_ONLY` names five paths: the
  `apps/core/scaffold` tree, plus the `declare`, `newapp`, `roads` and `scaffold` management
  commands. `roads` is the fourth command the draft did not count: it reaches the engine through
  `importlib` with a computed module name. `.dockerignore` excludes exactly those five, each with
  its reason line. Once the command files are excluded, Django could only answer "Unknown
  command", so the seam is `CoreConfig.refuse_outside_checkout`. `manage.py` calls it before
  Django's command line, and in the image each dev-only command exits 2 with the declared
  refusal, never `ImportError`. The census reads the `quality_reader` spellings off the source
  by `ast`. A re-included `quality/` data file counts as a data read, not a gate read. The census
  holds two exemptions by name, and an exemption that goes stale is itself a failure. The
  `apps → quality` contract allows two edges and no wildcard: the `declare` command, and the
  apps' own tests.
- **`ratchet_floors` stay on each `AppConfig`.** A floor is the member's own declaration, never a
  central file a product must edit (ADR platform-partition-1, ADR gate-6). The move the draft
  rejected stays rejected.
- **The trigger, as built.** Relocating the `DEV_ONLY` modules under `quality/` is release 2.6's
  work, and the `DEV_ONLY` list is its seam. The signed trigger reads "the scaffold and the
  three commands". As built, the list holds the scaffold and four commands, and `roads` is the
  same kind as the other three (a command that reads the gate). Only a module of a different
  kind trips the trigger.
