#!/usr/bin/env python3
"""The alert census — DERIVED from the declarations, never typed.

    python3 deploy/observability/alerts/census.py            # human, for a report
    python3 deploy/observability/alerts/census.py --json     # machine, for apply.py

WHY THIS FILE EXISTS AT ALL. ADR obs-2 closed the alert question: the alert set
is not a list somebody keeps up to date, it is

    { per transition pair } ∪ { per declared spike } ∪ { two trace alerts } ∪ { two prober alerts }

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

#: Every kind a census member can be; `definitions.json` holds one shape per kind.
KINDS: tuple[str, ...] = ("transition", "recovery", "spike", "probe", "traces")

#: The keys of `definitions.json` that are not a kind's shape.
NOT_SHAPES = frozenset({"webhook"})

#: A server span: one per request at every door (the Django instrumentor's span).
SERVER_SPANS = "SpanKind = 'Server'"

#: The request's method and status under both HTTP semconvs (the instrumentor exports the old keys).
METHOD = (
    "if(SpanAttributes['http.request.method'] != '', "
    "SpanAttributes['http.request.method'], SpanAttributes['http.method'])"
)
STATUS = (
    "toUInt16OrZero(if(SpanAttributes['http.response.status_code'] != '', "
    "SpanAttributes['http.response.status_code'], SpanAttributes['http.status_code']))"
)
READS = f"{METHOD} IN ('GET', 'HEAD')"

#: Under this many server spans a class's p95 reads 0 (`deploy/load/drive.py` MIN_WINDOW_SAMPLES).
MIN_SPANS = 20

#: The p95 budgets the acceptable tier sets, reads and writes (`Duration` is ns).
READ_BUDGET_MS = 500
WRITE_BUDGET_MS = 1000

#: 5xx per 5 min that page: 0.5% of eight closed-loop clients at >= 1 req/s for 300 s.
ERROR_COUNT = 12

#: The deployment-wide trace alerts, named like the probes: every door is their population.
TRACES: tuple[dict, ...] = (
    {
        "key": "latency",
        "select": (
            f"if(count() >= {MIN_SPANS}, quantile(0.95)(Duration / if({READS}, "
            f"{READ_BUDGET_MS * 1_000_000}, {WRITE_BUDGET_MS * 1_000_000})), 0) "
            "AS p95_over_budget"
        ),
        "where_sql": SERVER_SPANS,
        "group_by": f"if({READS}, 'read', 'write') AS class",
        "threshold": 1,
        "window": "5m",
        "summary": (
            f"the p95 of server spans is at or over budget for reads ({READ_BUDGET_MS} ms) "
            f"or writes ({WRITE_BUDGET_MS} ms) inside 5m; the value is p95 over budget "
            f"per class, and a class under {MIN_SPANS} spans reads 0"
        ),
    },
    {
        "key": "error_rate",
        "select": "count() AS server_errors",
        "where_sql": f"{SERVER_SPANS} AND {STATUS} >= 500",
        "group_by": "",
        "threshold": ERROR_COUNT,
        "window": "5m",
        "summary": (
            f"{ERROR_COUNT} or more server spans answered 5xx inside 5m; a count, not a "
            "ratio, so a busy deployment reaches it at a smaller share than a quiet one"
        ),
    },
)

#: The name an app's `events.py` declares its spikes under.
SPIKES_NAME = "SPIKES"

#: The four keys every spike declares, and nothing else.
SPIKE_FIELDS = ("key", "threshold", "window", "reason")

#: The windows ClickStack's alert check accepts as an `interval`.
SPIKE_WINDOWS = ("1m", "5m", "15m", "30m", "1h", "6h", "12h", "1d")

#: The logger methods whose first argument is the key the sink indexes as `event`.
LOG_LEVELS = frozenset({"debug", "info", "warning", "error", "critical", "exception"})

#: Characters a reason may not carry: the sink compiles it with handlebars, then as JSON.
REASON_FORBIDDEN = ('"', "\\", "{", "}")
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


def declared_spikes(root: Path) -> dict[str, list[tuple[int, object]]]:
    """Every app's `SPIKES` entries as `(line, literal)`, by app label, read by AST."""
    found: dict[str, list[tuple[int, object]]] = {}
    for events_file in sorted((root / "apps").glob("*/events.py")):
        tree = ast.parse(events_file.read_text(encoding="utf-8"), filename=str(events_file))
        for node in tree.body:
            if isinstance(node, ast.AnnAssign):
                targets, value = [node.target], node.value
            elif isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            else:
                continue
            if not any(isinstance(t, ast.Name) and t.id == SPIKES_NAME for t in targets):
                continue
            entries: list[tuple[int, object]] = []
            for item in value.elts if isinstance(value, (ast.Tuple, ast.List)) else [value]:
                try:
                    entries.append((item.lineno, ast.literal_eval(item)))
                except ValueError:
                    entries.append((item.lineno, None))
            found[events_file.parent.name] = entries
    return found


def log_sites(root: Path, label: str) -> dict[str, list[str]]:
    """Every `log.<level>("<key>"` call in the app outside its tests, as key -> file:line sites."""
    sites: dict[str, list[str]] = {}
    app = root / "apps" / label
    for module in sorted(app.rglob("*.py")):
        relative = module.relative_to(app)
        if "tests" in relative.parts or "migrations" in relative.parts:
            continue
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            func = node.func
            if not (isinstance(func.value, ast.Name) and func.value.id == "log"):
                continue
            if func.attr not in LOG_LEVELS or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                where = f"apps/{label}/{relative.as_posix()}:{node.lineno}"
                sites.setdefault(first.value, []).append(where)
    return sites


def spikes(root: Path) -> tuple[list[dict], list[str]]:
    """The declared spikes that can trip, and a warning per one that cannot."""
    derived: list[dict] = []
    warnings: list[str] = []
    for label, entries in declared_spikes(root).items():
        sites = log_sites(root, label)
        for line, entry in entries:
            at = f"apps/{label}/events.py:{line}"
            if not isinstance(entry, dict) or sorted(entry) != sorted(SPIKE_FIELDS):
                warnings.append(
                    f"{at}: a spike is a literal dict of exactly {', '.join(SPIKE_FIELDS)} "
                    f"— no alert derived."
                )
                continue
            key, threshold, window, reason = (entry[field] for field in SPIKE_FIELDS)
            segments = key.split(".") if isinstance(key, str) else []
            problem = None
            if len(segments) != NAME_SEGMENTS or not all(
                s.replace("_", "").isalnum() for s in segments
            ):
                problem = f"key {key!r} is not <app>.<noun>.<verb>"
            elif segments[0] != label:
                problem = f"key {key!r} is not this app's; an app declares spikes over its own keys"
            elif not isinstance(threshold, int) or isinstance(threshold, bool) or threshold < 1:
                problem = f"threshold {threshold!r} is not a whole number of at least 1"
            elif window not in SPIKE_WINDOWS:
                problem = (
                    f"window {window!r} is not one the sink checks ({', '.join(SPIKE_WINDOWS)})"
                )
            elif not isinstance(reason, str) or not reason.strip():
                problem = "reason is empty"
            elif any(mark in reason for mark in REASON_FORBIDDEN):
                problem = "reason carries a quote, a backslash or a brace"
            elif key not in sites:
                problem = f'no log.<level>("{key}") call in apps/{label}/ writes this key'
            if problem:
                warnings.append(f"{at}: {problem} — no alert derived.")
                continue
            derived.append(
                {
                    "app": label,
                    "log_key": key,
                    "threshold": threshold,
                    "window": window,
                    "reason": reason,
                    "where": "log",
                    "declared_at": at,
                    "emitted_at": sites[key],
                }
            )
    return derived, warnings


def shape_problems(definitions: dict) -> list[str]:
    """Every kind with no shape in `definitions.json`, and every shape of no kind."""
    shapes = {key for key in definitions if not key.startswith("_") and key not in NOT_SHAPES}
    problems = [
        f"kind {kind!r} has no shape in definitions.json" for kind in KINDS if kind not in shapes
    ]
    problems += [
        f"definitions.json shape {shape!r} is not a census kind ({', '.join(KINDS)})"
        for shape in sorted(shapes - set(KINDS))
    ]
    return problems


def fill(template: object, fields: dict) -> object:
    """A shape with every string in it formatted from one census row."""
    if isinstance(template, str):
        return template.format(**fields)
    if isinstance(template, dict):
        return {k: fill(v, fields) for k, v in template.items() if not k.startswith("_")}
    if isinstance(template, list):
        return [fill(item, fields) for item in template]
    return template


def census(root: Path) -> dict:
    """The whole closed census: the pairs, the probe, and the alert list."""
    names_by_app = declared_names(root)
    pairs, warnings = transition_pairs(names_by_app)
    declared, spike_warnings = spikes(root)
    warnings = warnings + spike_warnings
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
    for spike in declared:
        alerts.append(
            {
                "kind": "spike",
                "key": f"spike:{spike['log_key']}",
                "name": f"{spike['log_key']} spike",
                "delivered_by": "clickstack",
                **spike,
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
    for trace_alert in TRACES:
        alerts.append(
            {
                "kind": "traces",
                **trace_alert,
                "key": f"traces:{trace_alert['key']}",
                "name": trace_alert["key"],
                "where": "traces",
                "delivered_by": "clickstack",
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
        "spikes": declared,
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
    lines += ["", f"Spikes declared: {len(result['spikes'])}"]
    for spike in result["spikes"]:
        lines.append(
            f"  {spike['log_key']} >= {spike['threshold']} in {spike['window']} "
            f"(where=log; {len(spike['emitted_at'])} call site(s); {spike['declared_at']})"
        )
    traces = [alert for alert in result["alerts"] if alert["kind"] == "traces"]
    lines += ["", f"Trace alerts (deployment-wide, over server spans): {len(traces)}"]
    for alert in traces:
        lines.append(f"  {alert['name']} >= {alert['threshold']} in {alert['window']}")
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
        f"ALERTS = {pairs} pair(s) x 2 + {len(result['spikes'])} spike(s) "
        f"+ {len(traces)} trace alert(s) + {len(probes)} probes = {total}",
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
