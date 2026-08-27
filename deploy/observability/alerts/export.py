#!/usr/bin/env python3
"""Read the LIVE alert config back out of a ClickStack, and diff it against the census.

    python3 deploy/observability/alerts/export.py                    # print
    python3 deploy/observability/alerts/export.py --out exported.json

This is the honesty instrument for `apply.py`, and it is what makes A1s-4's
portability claim checkable rather than asserted: export, drop the ClickStack
volume, `apply.py` again, export again, compare. If the two exports differ in
anything but ids and timestamps, the definitions were not portable and somebody
had hand-edited the running sink.

It also answers the question a reviewer will ask about any config-as-code
scheme — "is what is running actually what is in the tree?" — by listing every
alert the sink holds and marking the ones the census does NOT account for. An
alert somebody added in the UI is not a crime, but it is a fact the census
should know about, and a surface nobody can enumerate is the surface that rots.

The destination URL is printed as HOST and LENGTH, never as a value: a webhook
URL is a bearer credential and this output goes into reports.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import census as census_module  # noqa: E402
from apply import DEFAULT_URL, REQUIRED_ENV, Sink  # noqa: E402

#: Fields that legitimately differ between two ClickStacks holding the same
#: definitions, stripped before the comparison so a diff MEANS something.
#:
#: Two kinds, and both are named rather than waved at. **Identity**: every
#: `*_id`/reference is a Mongo ObjectId minted when the row was created, so a
#: fresh volume necessarily has different ones — comparing them would make the
#: portability check unpassable by construction. **Runtime state**: `history`,
#: `state` and `lastValues` are what the alert has DONE, not what it IS; a
#: sink that has been watching for an hour has a history and a fresh one does
#: not, and neither fact says anything about the definitions.
#:
#: Everything else — the query, the select, the threshold, the interval, the
#: webhook body, the message — is compared, and a difference there is a real
#: failure of A1s-4.
VOLATILE = {
    # identity
    "_id",
    "id",
    "team",
    "source",
    "savedSearch",
    "savedSearchId",
    "webhookId",
    "createdBy",
    # bookkeeping
    "createdAt",
    "updatedAt",
    "__v",
    # runtime state
    "state",
    "history",
    "lastValues",
}


def strip(obj: object) -> object:
    if isinstance(obj, dict):
        return {k: strip(v) for k, v in sorted(obj.items()) if k not in VOLATILE}
    if isinstance(obj, list):
        return [strip(item) for item in obj]
    return obj


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=os.environ.get("CLICKSTACK_URL", DEFAULT_URL))
    parser.add_argument("--out", default=None, help="write the export here")
    args = parser.parse_args(argv)

    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        print("REFUSING: not in the environment: " + ", ".join(missing))
        return 2

    sink = Sink(args.url)
    sink.authenticate(os.environ["CLICKSTACK_ADMIN_EMAIL"], os.environ["CLICKSTACK_ADMIN_PASSWORD"])

    definitions = json.loads((Path(__file__).resolve().parent / "definitions.json").read_text())
    # `?service=` is REQUIRED by ClickStack's list route (it 400s without it),
    # and the service we deliver through is the one `definitions.json` declares.
    service = definitions["webhook"]["service"]
    webhooks = Sink.unwrap(sink.request("GET", f"/webhooks?service={service}"))
    searches = Sink.unwrap(sink.request("GET", "/saved-search"))
    alerts = Sink.unwrap(sink.request("GET", "/alerts"))

    for webhook in webhooks:
        url = str(webhook.get("url", ""))
        webhook["url"] = (
            f"<{len(url)} chars, host {url.split('/')[2]}>" if "://" in url else "<unset>"
        )

    export = {
        "webhooks": strip(webhooks),
        "saved_searches": strip(searches),
        "alerts": strip(alerts),
    }

    # THE IDENTITY IS THE SAVED SEARCH'S NAME, not the alert's. ClickStack's
    # `GET /alerts` does not return the alert's own `name` at all — it returns
    # the saved search it hangs off, nested. Comparing on a field the API never
    # sends back is how a census check reports "nothing matches" for ever, so
    # the comparison uses the one name both ends can see. The census is one
    # alert per saved search, so this is the same statement either way.
    # Only the members THIS SINK delivers. The deaf-sink alert is in the census
    # and is delivered by the prober's own POST (ADR obs-2 as amended
    # amended), so expecting it here would report a permanent
    # "MISSING FROM THE SINK" for an alert that is working exactly as designed —
    # a false red is how a portability check stops being read.
    result = census_module.census(census_module.repo_root())
    expected = set()
    for member in result["alerts"]:
        if member.get("delivered_by") != "clickstack":
            continue
        # One shape per kind — `transition`, `recovery`, `probe` — looked up the
        # same way apply.py looks it up, so the two cannot drift into expecting
        # different sets. A kind with no shape would silently drop a member from
        # `expected` and report the live alert as NOT IN THE CENSUS, which is a
        # false red in the direction that gets a check ignored.
        kind = member["kind"]
        if kind not in ("transition", "recovery", "probe"):
            print(f"REFUSING: census member {member['name']!r} has unknown kind {kind!r}.")
            return 2
        shape = definitions[kind]
        expected.add(shape["saved_search"]["name"].format(**member))
    live = {str((alert.get("savedSearch") or {}).get("name")) for alert in alerts}

    print(json.dumps(export, indent=2, sort_keys=True))
    print()
    print(f"census expects {len(expected)}: {sorted(expected)}")
    print(f"sink holds     {len(live)}: {sorted(live)}")
    if live - expected:
        print(f"NOT IN THE CENSUS (added by hand?): {sorted(live - expected)}")
    if expected - live:
        print(f"MISSING FROM THE SINK: {sorted(expected - live)}")
    if args.out:
        Path(args.out).write_text(json.dumps(export, indent=2, sort_keys=True), encoding="utf-8")
        print(f"written to {args.out}")
    return 0 if live == expected else 1


if __name__ == "__main__":
    sys.exit(main())
