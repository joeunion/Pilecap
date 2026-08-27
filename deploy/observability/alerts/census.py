#!/usr/bin/env python3
"""The alert census — DERIVED from the declarations, never typed.

    python3 deploy/observability/alerts/census.py            # human, for a report
    python3 deploy/observability/alerts/census.py --json     # machine, for apply.py

WHY THIS FILE EXISTS AT ALL. ADR obs-2 closed the alert question: the alert set
is not a list somebody keeps up to date, it is

    { one alert per declared transition-event pair } ∪ { the two prober alerts }

THE TWO HALVES ARE DERIVED DIFFERENTLY AND THAT IS DELIBERATE (ADR obs-2 as
amended). The event half is read out of `apps/*/events.py` by AST and
grows without an edit here. The probe half is NAMED EXPLICITLY, below, because
its two members are not events at all: they are the two questions the sink
cannot be asked to answer about itself — is the app up (`/readyz`), and is the
sink still accepting (the collector's own export failures). Nothing under
`apps/` declares either, so there is nothing to derive them from; naming them is
the honest form, and naming them HERE is what keeps the census closed.

and "declared" means declared in `apps/<app>/events.py`, which is already the
one place an event name may be born (house rule 16, `apps/events/events.py`'s
`declared_names()`). A hand-kept alert list is the exact failure class the
owner's scar names: the SECOND fallback circuit ships, nobody remembers to add
its alert, and the first person to know it degraded is a user. So the census is
computed here, from the same files the gate reads, and the runbook points the
next circuit's author at this one place.

THE GRAMMAR, stated so the next pair's author knows what makes a pair.

A **transition pair** is two names declared in one app's `events.py` that share
their first two segments — `<app>.<noun>` — where exactly one of them ends in a
verb from `RECOVERY_VERBS`. That one is the RECOVERED half; the other is the
DEGRADED half. Today the tree holds exactly one:

    comms.suppression.surged   /   comms.suppression.recovered

and search-2's planned `search.engine.degraded` / `search.engine.recovered`
joins it with no edit to this file — which is the whole point.

`RECOVERY_VERBS` is deliberately a **closed one-element tuple**. The
announce-on-transition ruling says "degraded/recovered";
`apps/comms/events.py` spells the recovery half `recovered`. A pair that spells
its recovery `restored` or `closed` would be invisible here — so the set is
named, tiny, and documented in `docs/runbooks/alerts.md` as the ONE line to
change if a future circuit picks a different word. An unpaired degradation name
is reported as a WARNING rather than silently skipped, because a circuit that
can be raised and never lowered is the alarm somebody silences.

NO DJANGO. This reads the files with `ast`, not by importing them, for two
reasons: it must run on a box where `manage.py` needs a database that may be
the thing that is down, and it must run in CI and in a shell with nothing
installed. The cost is that a name assembled at runtime would be invisible —
which is not a shape `events.py` is allowed to have (house rule 16: names only,
constants only), and is stated here as this file's declared blind spot.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

#: The verb that ends the RECOVERED half of a transition pair. Closed, tiny and
#: documented: see the module docstring and `docs/runbooks/alerts.md`.
RECOVERY_VERBS: tuple[str, ...] = ("recovered",)

#: The number of segments in `<app>.<noun>.<past-verb>` (house rule 16).
NAME_SEGMENTS = 3

#: The hard-dependency half of the census (ADR obs-2, clause 2). Outages are
#: /readyz's, never events — the ruling's scope boundary, held here in code.
#: The prober (`prober.sh`, the `readyz-prober` service in `deploy/compose.yaml`)
#: writes exactly these two names into the sink; the alert counts the failures.
PROBE_FAILED_EVENT = "probe.readyz.failed"
PROBE_OK_EVENT = "probe.readyz.ok"

#: The SECOND non-event alert (ADR obs-2 as amended). It is not a
#: ClickStack alert at all: the prober watches the collector's
#: `otelcol_exporter_send_failed_*` / `enqueue_failed_*` counters and POSTs the
#: notification to the webhook ITSELF, because the one alert that cannot ride
#: the sink is the one that says the sink stopped accepting. It appears in this
#: census — with `delivered_by: prober` rather than `delivered_by: clickstack` —
#: so the alert surface stays ONE closed list; `apply.py` skips it, because
#: there is nothing to create in a ClickStack for an alert ClickStack never
#: sees.
SINK_DEAF_EVENT = "probe.sink.deaf"
SINK_RECOVERED_EVENT = "probe.sink.recovered"


def repo_root(start: Path | None = None) -> Path:
    """Where `apps/` lives, found rather than assumed.

    The same reasoning as `deploy/grants.sql.py`'s `django_root()`: this file is
    run from a checkout, from `/deploy` inside a container, and from whatever
    third arrangement somebody has. `DJB_ROOT` overrides.
    """
    import os

    override = os.environ.get("DJB_ROOT")
    if override:
        return Path(override)
    here = (start or Path(__file__).resolve()).parent
    for candidate in [here, *here.parents]:
        if (candidate / "apps").is_dir() and (candidate / "manage.py").is_file():
            return candidate
    raise SystemExit(
        "Could not find the repository root (a directory holding both `apps/` "
        "and `manage.py`). Set DJB_ROOT."
    )


def declared_names(root: Path) -> dict[str, list[str]]:
    """Every `apps/<app>/events.py`'s uppercase string constants, by app label.

    The same population `apps/events/events.py::declared_names()` builds from
    the live app registry, read statically. A module with no such constants is
    skipped, exactly as it is there.
    """
    found: dict[str, list[str]] = {}
    for events_file in sorted((root / "apps").glob("*/events.py")):
        label = events_file.parent.name
        tree = ast.parse(events_file.read_text(encoding="utf-8"), filename=str(events_file))
        names: list[str] = []
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    names.append(node.value.value)
        if names:
            found[label] = sorted(set(names))
    return found


def transition_pairs(names_by_app: dict[str, list[str]]) -> tuple[list[dict], list[str]]:
    """The declared transition pairs, and the unpaired degradation names.

    Returns `(pairs, warnings)`. A pair is a dict with `app`, `noun`,
    `degraded`, `recovered` — everything the alert templates interpolate.
    """
    pairs: list[dict] = []
    warnings: list[str] = []
    for label, names in names_by_app.items():
        by_prefix: dict[str, list[str]] = {}
        for name in names:
            segments = name.split(".")
            if len(segments) != NAME_SEGMENTS:
                continue
            by_prefix.setdefault(".".join(segments[:2]), []).append(name)
        for prefix, members in sorted(by_prefix.items()):
            recovered = [n for n in members if n.rsplit(".", 1)[-1] in RECOVERY_VERBS]
            degraded = [n for n in members if n not in recovered]
            if not recovered:
                continue
            if len(recovered) != 1 or len(degraded) != 1:
                warnings.append(
                    f"{prefix}: expected exactly one degraded name and one recovery "
                    f"name, found degraded={degraded} recovered={recovered} — "
                    f"no alert derived. Fix the declaration or widen RECOVERY_VERBS."
                )
                continue
            pairs.append(
                {
                    "app": label,
                    "noun": prefix.split(".", 1)[1],
                    "prefix": prefix,
                    "degraded": degraded[0],
                    "recovered": recovered[0],
                }
            )
    return pairs, warnings


def census(root: Path) -> dict:
    """The whole closed census: the pairs, the probe, and the alert list."""
    names_by_app = declared_names(root)
    pairs, warnings = transition_pairs(names_by_app)
    # ONE DECLARED PAIR IS TWO ALERTS, and the vocabulary keeps them apart.
    #
    # A "transition pair" stays what it always was: two names declared together
    # in one `apps/<app>/events.py`. That count is a fact about the PRODUCT and
    # this file must not inflate it — "Transition pairs declared: 1" means one
    # circuit can be raised and lowered, and it would be a lie to print 2
    # because the alert surface grew.
    #
    # What changed (ADR obs-2 as amended) is how many ALERTS one pair
    # yields: two, because ClickStack cannot express "open on A, close on B".
    # Its OK notification means "the query window stopped matching", not "the
    # circuit recovered" — so `<x>.recovered` reaches the sink and, on its own,
    # fires nothing at all. The recovered half therefore has its own watcher,
    # and `ALERTS =` counts alerts rather than pairs.
    alerts = []
    for pair in pairs:
        alerts.append(
            {
                "kind": "transition",
                "key": f"transition:{pair['prefix']}",
                "name": f"{pair['prefix']} degraded",
                "delivered_by": "clickstack",
                **pair,
            }
        )
        alerts.append(
            {
                "kind": "recovery",
                "key": f"recovery:{pair['prefix']}",
                "name": f"{pair['prefix']} recovered",
                "delivered_by": "clickstack",
                **pair,
            }
        )
    alerts.append(
        {
            "kind": "probe",
            "key": "probe:readyz",
            "name": "readyz outage",
            "delivered_by": "clickstack",
            "failed_event": PROBE_FAILED_EVENT,
            "ok_event": PROBE_OK_EVENT,
        }
    )
    alerts.append(
        {
            "kind": "probe",
            "key": "probe:sink-deaf",
            "name": "sink deaf",
            # The one member ClickStack never learns about, and the field says
            # so rather than a reader having to know. `apply.py` reconciles the
            # `clickstack` members only.
            "delivered_by": "prober",
            "failed_event": SINK_DEAF_EVENT,
            "ok_event": SINK_RECOVERED_EVENT,
        }
    )
    return {
        "derived_from": sorted(f"apps/{label}/events.py" for label in names_by_app),
        "recovery_verbs": list(RECOVERY_VERBS),
        "transition_pairs": pairs,
        "alerts": alerts,
        "warnings": warnings,
    }


def render(result: dict) -> str:
    lines = [
        "ALERT CENSUS (derived, closed — ADR obs-2)",
        "",
        "Read from: " + ", ".join(result["derived_from"]),
        "Recovery verbs: " + ", ".join(result["recovery_verbs"]),
        "",
        f"Transition pairs declared: {len(result['transition_pairs'])}",
    ]
    for pair in result["transition_pairs"]:
        lines.append(f"  {pair['degraded']}  ->  {pair['recovered']}")
    probes = [alert for alert in result["alerts"] if alert["kind"] == "probe"]
    pairs = len(result["transition_pairs"])
    total = len(result["alerts"])
    deaf = "N consecutive windows of lost telemetry; delivered by the prober's own POST"
    lines += [
        "",
        f"Probes: {len(probes)}",
        f"  {PROBE_FAILED_EVENT} (N consecutive /readyz failures; delivered by ClickStack)",
        f"  {SINK_DEAF_EVENT} ({deaf})",
        "",
        # Pairs x 2: the degraded half and the recovered half are separate
        # alerts because the sink cannot close one on the other (obs-2 as
        # amended). The pair count is still the PRODUCT's declaration.
        f"ALERTS = {pairs} pair(s) x 2 + {len(probes)} probes = {total}",
    ]
    for alert in result["alerts"]:
        lines.append(f"  [{alert['kind']}] {alert['name']}  (delivered by {alert['delivered_by']})")
    if result["warnings"]:
        lines += ["", "WARNINGS:"]
        lines += [f"  {warning}" for warning in result["warnings"]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="machine-readable census")
    parser.add_argument("--root", default=None, help="repository root (default: found)")
    args = parser.parse_args(argv)
    root = Path(args.root) if args.root else repo_root()
    result = census(root)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render(result))
    # A warning is a finding, not a failure: the census still prints, and the
    # exit code says one was raised so a runbook step can notice it.
    return 3 if result["warnings"] else 0


if __name__ == "__main__":
    sys.exit(main())
