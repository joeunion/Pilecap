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
#:
#: 13 -> 11: rule 5 dropped the two plants into
#: `quality/perf-realtime-measurement.md` and `quality/perf-ledgers-measurement.md`
#: (see `TOTAL_PLANTS` above).
OUTSIDE_APPS_PLANTS = 11

#: Measured once, then re-measured every time a rule arrived. Rule 43 added
#: five product-app plants across three entries. Rule 44 added six — four in the
#: scaffold, two in `config/`, and NONE in a product app, the reason its
#: test-module negative went to `apps/zzz_canary/tests/test_probe.py` rather than
#: beside the real `apps/core/tests/test_method_refusal.py` it is modelled on.
#: Rule 41's tag clause added five, ALL in the scaffold: the
#: unbacked promise is two files and the kept promise is three, and the product
#: apps gained none — a route that promises a role is a shape the probe app can
#: hold as well as a real one. Rules 45, 46 and 47 added
#: eighteen plants — ten in the scaffold, five in the worked example, and THREE
#: in real product apps, each of which is a fact ABOUT a real app that the
#: scaffold cannot carry (a one-door app growing a second door; an app already
#: at its recorded ratchet taking on another debt; the module that installs the
#: tools ceiling, stripped of it). Each carries its dated trigger and each
#: trigger names a HEALTHY condition — the day the app grows the door, the day
#: the debt is paid — never "the day this app stays broken", the rule adopted
#: when rule 5's last real-app plant was retired.
#: Rule 31 arrived with three canaries and four negatives, and
#: rule 20's static tightening added one of each — ten plants, ALL TEN into the
#: worked example and NONE into a product app. They cannot live in the scaffold
#: for a mechanical reason worth recording: rule 31 reads the LIVE app registry
#: through a Django boot, and `apps/zzz_canary` is scaffolded only for the
#: batched `via: django` probe — an `ast`-planted model there would not be in
#: `INSTALLED_APPS` and so would not be in `get_models()` at all. The worked
#: example is an installed app that the template promises will keep every shape
#: a rule needs to see, which is exactly what a lifecycle declaration is.
#: The reason this file exists.
#: Re-measured when rule 37 added seven plants, all seven in
#: the worked example — the tenant-blind index shapes it refuses are model
#: Meta edits, and the example app is where a refusable Meta lives without a
#: product app staying ill (the rule above). Scaffold and product unchanged.
#: Pinned by the PM as the merge-reconciliation commit after five server-side
#: 529s killed the builder at exactly this line; the numbers are the census's
#: own measured output, not a hand count (ratio 0.823 against the 0.80 floor).
#: Re-measured when rule 33 arrived with three canaries and four
#: negatives — five into the worked example, ONE into `config/settings/base.py`
#: (the excepted reader, planted in the tree the exception names) and ONE into a
#: real product app, `apps/search/selectors.py`. That last one is the class
#: rules 45–47 recorded: the fence's allow-list names the chokepoint by path, so an
#: allow-listed import proved anywhere else would be proving something about a
#: module the rule does not talk about.
#: Re-measured when rule 11 gained ONE negative, in the scaffold —
#: `apps/zzz_canary/search.py`, proving that the filename the search registry's
#: discovery seam requires of every adopting app (`registry.DECLARATION_MODULE`)
#: is canonical everywhere rather than recorded per app. It belongs in the
#: scaffold and nowhere else: the fact under proof is that ANY app may carry
#: this file, which is exactly what a probe app can hold and what a plant into
#: a real app would muddle with that app's own reasons for having one. Example,
#: product and outside all unchanged; scaffold 92 -> 93.
#: Re-measured when rule 48 (the storage wall) arrived: ten plants — EIGHT into
#: the worked example, across four module shapes (`services.py`, `api.py`,
#: `selectors.py`, `activities.py`), because the wall has four clauses and a
#: fifth door and none of them may read as one file's habit; ONE into
#: `config/settings/base.py` (the excepted reader, planted in the tree the
#: exception names — rule 33's own shape); and ONE into a real product app,
#: `apps/core/health.py`. That last is the rules 45–47 class again and rule 33's
#: precedent exactly: the fence's allow-list names the readiness probe BY PATH, because
#: `core` cannot import `files` (house rule 7) and a probe that could not reach
#: the organ could not report on it — so an allow-listed import proved in the
#: scaffold would be proving something about a module the rule does not talk
#: about. Its trigger is the healthy one: the day `core` no longer needs its own
#: client. Scaffold unchanged at 93; example 179 -> 187; outside 12 -> 13;
#: product 47 -> 48.
#:
#: **Rule 49 moved example 187 -> 195 and the total 343 -> 351.**
#: Eight plants, all into `apps/example/services.py` and none anywhere else,
#: which is the shape a signature rule should have: what rule 49 reads is a
#: `@service`'s declaration, and the worked example is where services are
#: planted. Four canaries (an audited write with no actor; the same with a
#: DEFAULTED actor; a defaulted tenant; and an already-allow-listed name
#: carrying a defaulted actor, which must fire anyway) and four negatives (the
#: conformant pair; required-but-NULLABLE, which is `revoke_token`'s shape and
#: must stay silent; the re-keyed wall's `kind == "system"` spelling, which is
#: the fix and must never read as the defect; and a `@service` outside the
#: audited population entirely). Scaffold unchanged at 93, product unchanged at
#: 48, outside unchanged at 13 — the rule needs no scaffold model and no real
#: product app, because it reads signatures rather than a registry.
#:
#: Outside 13 -> 11 and the total 351 -> 349: rule 5 dropped a canary and a
#: negative that plant into `quality/perf-realtime-measurement.md` and
#: `quality/perf-ledgers-measurement.md` — the citation-doc verification they
#: proved was retired along with the docs it read.
TOTAL_PLANTS = 349
SCAFFOLD_PLANTS = 93
EXAMPLE_PLANTS = 195

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
PRODUCT_APP_PLANT_ENTRIES = 46
PRODUCT_APP_PLANT_FILES = 48

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

    Derived exactly as `quality/checks.py::_app_dirs` derives it, so
    `apps/gadget` and `apps/gizmos` (which rule 16's canaries CREATE and
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
    the engine's instruments into somebody's product code.
    """
    total = len(_plants())
    safe = sum(
        1
        for _rid, _kind, _index, _fixture, plant_at in _plants()
        if plant_at.startswith("apps/") and plant_at.split("/")[1] in EXEMPT_APPS
    )

    assert safe / total >= 0.80, f"{safe} of {total}"
