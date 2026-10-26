"""Where the gate's canaries and negatives are planted, as a census.

**A canary planted into a product app dies the day that app grows the healthy
feature.** Rule 5's two `apps/events` plants proved it — a later rung gave
`apps/events` a REST door with proper query pins, both forms went silent, and
the full gate went exit 2 on a dead canary. Nothing about the rule or the tree
was wrong; the plant site was.

Rule 5's own repair was to move to the gate's scaffold app and to write a
**dated move-trigger** beside the one plant it deliberately kept in a real app.
That last plant is gone too, retired on the rule below: its trigger's condition
was "the day `apps/realtime` gets healthier", and an instrument may not depend on a patient
staying ill. Rule 5 now plants entirely in the scaffold, and what the move kept
is the DISTINCTION the real-app plant was carrying — `_app_is_pinned` is False
two ways, and the moved fixture plants the "tests exist and pin nothing" half.
The remaining question the hand-up left open was *which other rules do this* —
and it was open because nobody had counted. This module is the count, and it is
derived from `quality/rules.yaml` rather than typed, so a rung that adds a plant
is in the population the moment it lands.

**What is pinned and what is derived.** The buckets and the per-app numbers are
derived from the file. What is typed here is the JUDGEMENT: the set of
product-app plants somebody has looked at, and the totals. A new plant into a
real app fails `test_the_product_app_plants_are_the_pinned_set` and the builder
either moves it to the scaffold or adds it here with a trigger — which is the
whole mechanism, and is the same shape as a ratchet.

**Blind spot, declared.** The trigger check is mechanical: a dated
`MOVE-TRIGGER` line in the contiguous comment block directly above the entry.
It cannot tell a trigger that names the real condition from one that names a
plausible-sounding condition, and it does not know whether the condition has
already been met. That is review's, and the surveyor's.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from django.conf import settings

#: The two exempt buckets. `zzz_canary` is the gate's own scaffold — created by
#: the plant, deleted by `restore()`, so nobody can grow a feature in it. The
#: worked example is exempt because it is the ONE app the template promises will
#: keep every shape a rule needs to see; a plant there dies only if the worked
#: example stops being worked, which is a louder failure than a silent canary.
EXEMPT_APPS = {"zzz_canary", "example"}

#: Plants outside `apps/` altogether. They are not product apps and cannot be
#: absorbed by a feature: `config/urls.py` is the resolver rule 3's third clause
#: is ABOUT, `perf/seed.py` is the fixture contract rule 5's stamp is about, and
#: one `quality/` file (`quality/budgets.yaml`) is the engine's own data.
#: `config/api.py` and `config/mcp.py` are the mounts rule 44 is ABOUT — a wrap
#: of a library's private lives where the mounting happens.
#: Pinned from the bucket walk's `outside`; rule 97's 3 drawer removals are 3 of it.
OUTSIDE_APPS_PLANTS = 205

#: Pinned from this module's bucket walk:
#: `{'scaffold': 375, 'example': 267, 'product': 83, 'outside': 205, ...}`.
TOTAL_PLANTS = 932
SCAFFOLD_PLANTS = 375
EXAMPLE_PLANTS = 267

#: The judgement: every plant into a real product app, by rule and site. Each
#: one carries a dated MOVE-TRIGGER beside it in `quality/rules.yaml`; the test
#: below reads them back rather than trusting this list to be honest about it.
PRODUCT_APP_PLANTS = {
    ("1", "negatives", "apps/accounts/services.py"),
    ("4", "canaries", "apps/events/services.py"),
    ("4", "negatives", "apps/workflows/services.py"),
    ("7", "canaries", "apps/events/selectors.py"),
    ("7", "canaries", "apps/realtime/consumers.py"),
    ("8", "canaries", "apps/events/admin.py"),
    ("10", "canaries", "apps/realtime/consumers.py"),
    ("10", "negatives", "apps/realtime/consumers.py"),
    ("18", "canaries", "apps/workflows/services.py"),
    ("20", "canaries", "apps/events/services.py"),
    ("24", "canaries", "apps/events/services.py"),
    ("55", "canaries", "apps/accounts/services.py"),
    ("56", "canaries", "apps/accounts/adapter.py"),
    ("56", "canaries", "apps/accounts/api.py"),
    ("56", "negatives", "apps/accounts/adapter.py"),
    ("56", "negatives", "apps/accounts/selectors.py"),
    ("56", "negatives", "apps/accounts/services.py"),
    ("57", "canaries", "apps/accounts/adapter.py"),
    ("57", "canaries", "apps/accounts/services.py"),
    ("57", "negatives", "apps/accounts/adapter.py"),
    ("57", "negatives", "apps/accounts/oauth.py"),
    ("57", "negatives", "apps/accounts/services.py"),
    ("24", "negatives", "apps/events/services.py"),
    ("25", "negatives", "apps/workflows/activities.py"),
    ("26", "canaries", "apps/comms/services.py"),
    ("27", "canaries", "apps/accounts/services.py"),
    ("27", "negatives", "apps/accounts/activities.py"),
    ("35", "canaries", "apps/core/audit.py"),
    ("35", "canaries", "apps/events/selectors.py"),
    ("35", "canaries", "apps/realtime/selectors.py"),
    ("35", "negatives", "apps/core/audit.py"),
    ("35", "negatives", "apps/events/selectors.py"),
    ("36", "canaries", "apps/realtime/bridge.py"),
    ("36", "negatives", "apps/realtime/bridge.py"),
    # Rule 36's status-writer class (P20 R4-F3). `apps/core/services/tenants.py` holds
    # `suspend_tenant` and `close_tenant` — the only two services in the tree
    # that put a tenant beyond use — and a scaffold copy would be proving the
    # recogniser against a tenant nobody can suspend. The trigger is the
    # healthy one, written beside the entries: the day a second app learns to
    # darken a tenant.
    ("36", "canaries", "apps/core/services/tenants.py"),
    ("36", "negatives", "apps/core/services/tenants.py"),
    # Rule 58's three (P20 R4-F1). The JOIN half and the MOUNT half both have
    # to be demonstrated where the seam is: `apps/realtime/consumers.py` is
    # the one consumer this template has, and a scaffold consumer would be
    # proving the rule against a door nothing mounts. The whole-plant canary —
    # the fifteenth app's open consumer — lives in the worked example instead,
    # which is where a SECOND app growing a socket door can be shown at all.
    ("58", "canaries", "apps/realtime/consumers.py"),
    ("58", "negatives", "apps/realtime/consumers.py"),
    ("40", "canaries", "apps/core/exceptions.py"),
    ("40", "canaries", "apps/realtime/consumers.py"),
    ("40", "negatives", "apps/accounts/auth.py"),
    ("40", "negatives", "apps/connections/client.py"),
    ("40", "negatives", "apps/core/asgi_middleware.py"),
    ("40", "negatives", "apps/core/exceptions.py"),
    ("40", "negatives", "apps/core/middleware.py"),
    ("42", "canaries", "apps/comms/services.py"),
    # Rule 43's three declared census sites. Every one of them is a site
    # this rule's own `scope` names, which is why none of them can move to the
    # scaffold: a signer, a reference receiver and a contract with no product
    # behind them would be a census of a tree that does not exist.
    ("43", "canaries", "apps/events/api.py"),
    ("43", "canaries", "apps/events/receivers.py"),
    ("43", "negatives", "apps/events/activities.py"),
    ("43", "negatives", "apps/events/api.py"),
    ("43", "negatives", "apps/events/tests/test_signed_delivery.py"),
    # Rules 45 and 46's three. Each is a fact about a REAL app that the scaffold
    # cannot stand in for, and each trigger is the app getting HEALTHIER:
    #   rule 45 — the module that installs the tools ceiling, planted over
    #     WITHOUT it. A plant can create or append and never delete, so standing
    #     in for `apps/core/mcp.py` is the only way to show the guard gone.
    #   rule 46 — `apps/connections` is the one-door app; giving it a machine
    #     door is the debt being taken on, and the scaffold has no history to
    #     cross.
    #   rule 46 — `apps/accounts` is already AT its recorded ratchet; the
    #     scaffold has no entry to exceed.
    ("45", "canaries", "apps/core/mcp.py"),
    ("46", "canaries", "apps/accounts/consumers.py"),
    ("46", "canaries", "apps/connections/mcp.py"),
    # Rule 33's one. Its allow-list names `apps/search/selectors.py` by
    # PATH — it is the chokepoint the whole fence exists to funnel through — so
    # an allow-listed import proved in the scaffold would be proving something
    # about a module the rule does not talk about. The trigger is the healthy
    # one: it moves the day the chokepoint moves.
    ("33", "negatives", "apps/search/selectors.py"),
    # Rule 25's two. Its allow-list stopped being path-only when ADR
    # comms-9 pinned the vendor SDKs to `apps/comms/providers*`: the canary is
    # the SDK reached from a comms module that is NOT the exempt one, and the
    # negative is the exemption itself proved where the allow-list names it.
    # Neither can move to the scaffold — both are statements about THIS app's
    # boundary — and both triggers are the same healthy one: the day the vendor
    # transports move out of `providers.py`.
    ("25", "canaries", "apps/comms/services.py"),
    ("25", "negatives", "apps/comms/providers.py"),
    # Rule 48's one (the storage wall). Same class as rule 33's above,
    # and for a sharper reason: the allow-list names `apps/core/health.py` by
    # PATH because `core` CANNOT import `files` — that is an upward import house
    # rule 7 refuses — so the readiness probe holds the only legitimate second
    # boto3 client in the tree. Proving that exemption anywhere else would be
    # proving something about a module the rule does not name. The trigger is
    # healthy: the day `core` no longer needs its own client to report on the
    # organ.
    ("48", "negatives", "apps/core/health.py"),
    # Rule 17's four (R6's, recorded by R7 — see `TOTAL_PLANTS`). The move
    # detection reads a GIT DIFF, so showing a class LEAVE a module needs a
    # module git already knows: `apps/zzz_canary` is created by the plant and
    # tracked by nothing, so there is no scaffold file a class could leave.
    # `mode: create` over `apps/workflows/schemas.py` is what stands in for the
    # deletion, because a plant may create or append and never remove. The
    # arrival lands in a second real app for the same reason — the check
    # searches `apps/*/schemas.py`, and both ends of a move have to be somewhere
    # it looks.
    ("17", "canaries", "apps/workflows/schemas.py"),
    ("17", "canaries", "apps/realtime/schemas.py"),
    ("17", "negatives", "apps/workflows/schemas.py"),
    ("17", "negatives", "apps/realtime/schemas.py"),
    ("17", "canaries", "apps/core/schemas.py"),
    ("17", "negatives", "apps/core/schemas.py"),
    # Rule 83's two canaries: a second app on the platform's path and on its
    # tag, which the probe app cannot be for one path while rule 32 owns its
    # `PREFIX` — each is a real api module by construction.
    ("83", "canaries", "apps/events/api.py"),
    ("83", "canaries", "apps/usage/api.py"),
    # Rule 85's one-key-two-apps canary: a surface key collides only across two
    # apps, and the probe is one — the second declarer is a real app's own
    # `surfaces.py`, created for the length of the run.
    ("85", "canaries", "apps/usage/surfaces.py"),
}

#: Three counts, and rule 43 is what pulled them apart — before it all three
#: were 37 and the bucket census asserted against the ENTRY constant, which passed
#: only because no entry then planted more than one product-app FILE. Rule 43's
#: contraction negative plants three, and the assertion failed on a number that
#: had been two things wearing one name.
#:   * the SET above dedupes (rule, kind, site) — several rules plant two forms
#:     into one module;
#:   * the ENTRY count is what the move-trigger check walks, one comment block
#:     per entry;
#:   * the FILE count is what the bucket census counts.
#:
#: 46 -> 48 and 48 -> 52 (P15 R7, recording R6's arrears): rule 17's move
#: detection is TWO entries — a canary and a negative — and each plants TWO
#: files, a source and an arrival, which is exactly the split these two counts
#: exist to keep apart.
#:
#: 59 -> 67 and 63 -> 71 (P20 R4-F): rules 36, 58 and 59's product-app plants,
#: eight entries across four files — the two operator services in `core`, the
#: one consumer in `realtime`, and the one org-scoped emit site in `usage`.
#:
#: 67 -> 65 and 71 -> 69 (2026-09-21): rule 59's two `apps/usage` plants left
#: for the worked example. Both counts fall by the same two because the pair was
#: one entry per file — the split the two numbers exist for does not bite here,
#: and each is written out rather than derived from the other for that reason.
#:
#: 65 -> 67 and 69 -> 71 (the family's closing clauses): rule 17's
#: imported-base canary and negative, one entry and one file each, into
#: `apps/workflows/schemas.py` — the tracked module holding one `*Out`.
#:
#: 67 -> 69 and 71 -> 73 (2026-09-29): rule 83's two canaries, one entry and
#: one file each, into `apps/events/api.py` and `apps/usage/api.py`.
#:
#: 69 -> 71 and 73 -> 75 (2026-09-30): rule 83's display-title and schema-name
#: canaries, one entry and one file each, both into `apps/usage/api.py`.
#:
#: 71 -> 73 and 75 -> 77 (2026-09-30): rule 17's rename reading — a renamed
#: canary and a renamed negative, one entry and one file each, into
#: `apps/workflows/schemas.py` (the move pair's module); printed `product
#: entries 73` beside the bucket line above.
#:
#: 73 -> 74 and 77 -> 78 (2026-09-30): rule 85's one-key-two-apps canary, one
#: entry and one file, a `surfaces.py` in `apps/usage/` (created for the run); the
#: move-trigger test printed `74 == 73` and the bucket walk `'product': 78`.
#:
#: 74 -> 77 and 78 -> 81 (2026-10-02): rule 17's published-schema reading — a
#: canary (the JSON type moves) and two negatives (a re-spelling, a narrowing),
#: one entry and one file each, into `apps/workflows/schemas.py`; the
#: move-trigger test printed `77 == 74` and the bucket walk `'product': 81`.
PRODUCT_APP_PLANT_ENTRIES = 79
PRODUCT_APP_PLANT_FILES = 83

#: A trigger is DATED and says the word. Both halves matter: a condition with no
#: date is a note somebody wrote once, and a date with no condition is a
#: timestamp.
TRIGGER = re.compile(r"MOVE-TRIGGER\s+(\d{4}-\d{2}-\d{2})")

ROOT = Path(settings.BASE_DIR)
RULES_PATH = ROOT / "quality" / "rules.yaml"


def _rules() -> list[dict[str, Any]]:
    return list(yaml.safe_load(RULES_PATH.read_text())["rules"])


def _real_app_names() -> set[str]:
    """Every app that really exists in this tree — a directory with an apps.py.

    Derived exactly as `quality/checks/_hub.py::_app_dirs` derives it, so
    `gadget` and `gizmos` under `apps/` (which rule 16's canaries CREATE and
    `restore()` removes) are outside the population without being named.
    """
    return {d.name for d in (ROOT / "apps").iterdir() if (d / "apps.py").exists()}


def _plants() -> list[tuple[str, str, int, str, str]]:
    """(rule id, kind, entry index, fixture, plant_at) for every planted file."""
    out: list[tuple[str, str, int, str, str]] = []
    for rule in _rules():
        rid = str(rule["id"])
        for kind in ("canaries", "negatives"):
            for index, entry in enumerate(rule.get(kind) or []):
                for one in [entry, *(entry.get("extra_files") or [])]:
                    out.append((rid, kind, index, str(entry["fixture"]), str(one["plant_at"])))
    return out


def _product_plants() -> set[tuple[str, str, str]]:
    real = _real_app_names()
    return {
        (rid, kind, plant_at)
        for rid, kind, _index, _fixture, plant_at in _plants()
        if plant_at.startswith("apps/") and plant_at.split("/")[1] in real - EXEMPT_APPS
    }


# --- the census ----------------------------------------------------------------


def test_the_plant_population_is_the_measured_one() -> None:
    """The totals, by bucket. A plant added anywhere moves one of these.

    Not a floor and not a ceiling: an equality, because the point of the census
    is that somebody looked. A rung that adds a canary — which is a good thing —
    edits one number here, in the same commit, and a reviewer sees the shape of
    what moved.
    """
    real = _real_app_names()
    buckets = {"scaffold": 0, "example": 0, "product": 0, "outside": 0, "made-by-a-plant": 0}
    for _rid, _kind, _index, _fixture, plant_at in _plants():
        if not plant_at.startswith("apps/"):
            buckets["outside"] += 1
            continue
        app = plant_at.split("/")[1]
        if app == "zzz_canary":
            buckets["scaffold"] += 1
        elif app == "example":
            buckets["example"] += 1
        elif app in real:
            buckets["product"] += 1
        else:
            buckets["made-by-a-plant"] += 1

    assert sum(buckets.values()) == TOTAL_PLANTS, buckets
    assert buckets["scaffold"] == SCAFFOLD_PLANTS
    assert buckets["example"] == EXAMPLE_PLANTS
    assert buckets["outside"] == OUTSIDE_APPS_PLANTS
    assert buckets["product"] == PRODUCT_APP_PLANT_FILES


def test_the_product_app_plants_are_the_pinned_set() -> None:
    """The judgement, re-derived and compared.

    A new plant into a real product app fails here, and the builder has two
    honest ways out: move it to the gate's scaffold (the repair rule 5 made), or
    add it here and write the dated trigger the next test demands.
    """
    assert _product_plants() == PRODUCT_APP_PLANTS


def test_every_product_app_plant_carries_a_dated_move_trigger() -> None:
    """Each entry's own comment block says when it has to move, and since when.

    Read out of the file's text rather than its parsed form, because a comment
    is not data to YAML — which is exactly why this is worth a test: prose
    beside an entry is the one part of `rules.yaml` nothing else checks.
    """
    lines = RULES_PATH.read_text().splitlines()
    real = _real_app_names()
    starts = {}
    order = []
    for number, line in enumerate(lines):
        found = re.match(r'  - id: "([^"]+)"', line)
        if found:
            starts[found.group(1)] = number
            order.append(found.group(1))
    bounds = {
        rid: (starts[rid], starts[order[k + 1]] if k + 1 < len(order) else len(lines))
        for k, rid in enumerate(order)
    }

    missing: list[str] = []
    checked = 0
    for rule in _rules():
        rid = str(rule["id"])
        first, last = bounds[rid]
        for kind in ("canaries", "negatives"):
            head = next(
                (i for i in range(first, last) if lines[i].rstrip() == f"    {kind}:"), None
            )
            if head is None:
                continue
            end = last
            for i in range(head + 1, last):
                if re.match(r"    \w", lines[i]):
                    end = i
                    break
            entry_lines = [i for i in range(head + 1, end) if lines[i].startswith("      - ")]
            for index, entry in enumerate(rule.get(kind) or []):
                sites = [str(one["plant_at"]) for one in [entry, *(entry.get("extra_files") or [])]]
                if not any(
                    site.startswith("apps/") and site.split("/")[1] in real - EXEMPT_APPS
                    for site in sites
                ):
                    continue
                checked += 1
                at = entry_lines[index]
                block = []
                while at - 1 >= first and lines[at - 1].strip().startswith("#"):
                    at -= 1
                    block.append(lines[at])
                if not TRIGGER.search("\n".join(block)):
                    missing.append(f"rule {rid} {kind}[{index}] {entry['fixture']}")

    assert checked == PRODUCT_APP_PLANT_ENTRIES
    assert not missing, missing


def test_the_scaffold_is_where_most_of_the_engine_plants() -> None:
    """The direction of travel, asserted rather than hoped for.

    Every plant that CAN live in the gate's own scaffold should, and today the
    scaffold and the worked example carry more than four fifths of them. This is
    a floor on that ratio: it may rise and a rung that drops it below has moved
    the engine's instruments into somebody's product code. "Safe" means
    cannot-live-in-a-product-app (the safe-set ruling of 2026-09-02): the
    exempt apps plus every site outside apps/ entirely.
    """
    total = len(_plants())
    # Safe-set ruling, 2026-09-02: safe = cannot-live-in-a-product-app. Outside
    # `apps/` (config/, quality/, perf/, frontend/) no feature can absorb a
    # plant; inside `apps/`, only the two exempt apps are safe, and a
    # directory made by a plant counts UNSAFE — the formula fails closed on
    # anything it cannot classify.
    safe = sum(
        1
        for _rid, _kind, _index, _fixture, plant_at in _plants()
        if not plant_at.startswith("apps/") or plant_at.split("/")[1] in EXEMPT_APPS
    )

    assert safe / total >= 0.80, f"{safe} of {total}"
