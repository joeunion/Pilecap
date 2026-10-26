#!/usr/bin/env python3
"""Reconcile a ClickStack to the derived alert census. THE ONLY IMPORTER.

    export CLICKSTACK_URL=http://localhost:8080          # the sink's UI/API
    export CLICKSTACK_ADMIN_EMAIL=alerts@example.invalid
    export CLICKSTACK_ADMIN_PASSWORD=...                 # generated, never typed
    export SLACK_WEBHOOK_URL=...                         # FROM THE SLOT, see below
    export DJB_DEPLOY_NAMESPACE=...                      # this deployment's namespace
    python3 deploy/observability/alerts/apply.py

WHAT IT DOES, and why it is a reconciler rather than a one-shot import.
`census.py` says what the alert set IS; `definitions.json` says what shape each
member takes. This walks that product and makes the ClickStack match it:
one delivery webhook, one saved search per member, one alert per member. It is
idempotent — running it twice changes nothing — because the honest test of
"config-as-code" is that re-applying is the normal case: after a redeploy,
after a volume loss, after somebody clicked something in the UI.

THE DESTINATION IS NEVER IN THE TREE, AND NEITHER IS THE COORDINATE THAT NAMES
IT. `definitions.json` names the Secrets Manager SLOT as a SHAPE
(`{namespace}/<env>/env`, key `SLACK_WEBHOOK_URL`, ADR deploy-3a), and
`DJB_DEPLOY_NAMESPACE` fills it — required, refused when unset, never guessed.
This script reads the delivery VALUE from the environment, where the box
already puts it: `provision.sh secrets-fetch` writes `deploy/.env` under the
instance role, and `set -a; . deploy/.env` is how every other deployment step
gets its values. On a laptop the same variable holds the dummy receiver's URL.
The repository holds the slot name; the box holds the value; nothing holds a
session.

NOTHING IN THE DELIVERY PATH IS A SESSION. This script is a deployment step — it
runs once, on the box, from the runbook, and then it is over. What it leaves
behind is rows in ClickStack's own store; the thing that fires at 3am is
ClickStack's `check-alerts` task, which runs every minute inside the sink
container and posts to the URL. Nothing in that path is a process anybody has
to be logged in to. `docs/runbooks/alerts.md` § "Two Slack paths" says which
path is NOT this one and why.

AUTHENTICATION. ClickStack's config API is session-authenticated. On a fresh
volume there is no team at all, so this REGISTERS the operator account from
`CLICKSTACK_ADMIN_EMAIL`/`_PASSWORD` and keeps the session cookie; on an
existing volume it logs in with the same pair. Both credentials come from the
environment for the same reason the webhook URL does. They are the sink's
operator account, not a person's.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import census as census_module  # noqa: E402

DEFINITIONS = Path(__file__).resolve().parent / "definitions.json"

#: Where the sink answers. `localhost` rather than `127.0.0.1` on purpose:
#: ClickStack scopes its session cookie to the hostname it was reached on, and
#: a login on one spelling is not a session on the other.
DEFAULT_URL = "http://localhost:8080"

REQUIRED_ENV = ("CLICKSTACK_ADMIN_EMAIL", "CLICKSTACK_ADMIN_PASSWORD")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Stop at the redirect instead of following it.

    ClickStack's password login answers 302 to the FRONTEND's url, which on a
    box is a name this script may not be able to reach and on a laptop is a port
    nothing is listening on — so following it turns a successful login into
    `Connection refused` and hides the `Set-Cookie` that was the whole point.
    The 3xx itself is the success, and its headers carry the session.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        return None


class Sink:
    """The smallest possible client for ClickStack's config API."""

    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        # The session cookie is carried by hand rather than by `http.cookiejar`,
        # and that is not laziness. ClickStack sets `connect.sid` with
        # `Domain=localhost`, and cookiejar's RFC 2965 domain rules REJECT a
        # domain with no embedded dot — so the login succeeds, the cookie is
        # silently dropped, and the very next call is a 401 that looks like bad
        # credentials. One header in, one header out, no policy to lose.
        self.cookie: str | None = None
        self.opener = urllib.request.build_opener(_NoRedirect)

    def request(self, method: str, path: str, payload: dict | None = None) -> object:
        url = f"{self.base}/api{path}"
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(url, data=data, method=method)  # noqa: S310 — base is the operator's https ClickStack URL; no file: scheme reaches it
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if self.cookie:
            request.add_header("Cookie", self.cookie)
        try:
            with self.opener.open(request, timeout=30) as response:
                self._remember(response.headers.get_all("Set-Cookie"))
                body = response.read().decode()
        except urllib.error.HTTPError as error:
            # A 3xx arrives here because redirects are not followed; it is a
            # success and it is where the login's session cookie lives.
            if 300 <= error.code < 400:
                self._remember(error.headers.get_all("Set-Cookie"))
                return None
            detail = error.read().decode()[:400]
            raise SystemExit(f"{method} {url} -> {error.code}: {detail}") from None
        if not body:
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return body

    def _remember(self, headers: list[str] | None) -> None:
        for header in headers or []:
            if header.startswith("connect.sid="):
                self.cookie = header.split(";", 1)[0]

    def authenticate(self, email: str, password: str) -> None:
        installation = self.request("GET", "/installation")
        exists = bool(isinstance(installation, dict) and installation.get("isTeamExisting"))
        if exists:
            self.request("POST", "/login/password", {"email": email, "password": password})
            print(f"[auth] logged in as {email}")
        else:
            self.request(
                "POST",
                "/register/password",
                {
                    "email": email,
                    "password": password,
                    "confirmPassword": password,
                    "name": "alerts",
                },
            )
            print(f"[auth] registered the operator account {email} (fresh volume)")

    @staticmethod
    def unwrap(payload: object) -> list:
        """ClickStack answers `{"data": [...]}` on some routes and `[...]` on others."""
        if isinstance(payload, dict) and "data" in payload:
            payload = payload["data"]
        return list(payload) if isinstance(payload, list) else []


def logs_source_id(sink: Sink) -> str:
    """The Logs source every alert here reads. Never created here.

    Nothing under `alerts/` creates a source. Sources are the sink's shared
    furniture, owned by `deploy/observability/` outside this directory, and an
    alert route that quietly redefined where logs live would be a second answer
    to a settled question.
    """
    sources = Sink.unwrap(sink.request("GET", "/sources"))
    for source in sources:
        kind = str(source.get("kind", "")).lower()
        name = str(source.get("name", "")).lower()
        if kind == "log" or kind == "logs" or "log" in name:
            return str(source.get("id") or source.get("_id"))
    raise SystemExit(
        "No Logs source in this ClickStack. Bring the sink up and let it seed "
        "its default sources (or run the observability import) first."
    )


def traces_source_id(sink: Sink) -> str:
    """The Traces source the `traces` kind reads. Never created here, like the Logs one."""
    for source in Sink.unwrap(sink.request("GET", "/sources")):
        if str(source.get("kind", "")).lower() in ("trace", "traces"):
            return str(source.get("id") or source.get("_id"))
    raise SystemExit(
        "No Traces source in this ClickStack. Bring the sink up and let it seed "
        "its default sources first."
    )


def ensure_traces_dashboard(
    sink: Sink, shape: dict, members: list[dict], webhook_id: str, namespace: str
) -> None:
    """One dashboard holding one tile per `traces` member, each tile's alert embedded."""
    name = shape["dashboard"]["name"].format(namespace=namespace)
    source_id = traces_source_id(sink)
    tiles = []
    for row, member in enumerate(members):
        config = census_module.fill(shape["tile"], member)
        if not config.get("groupBy"):
            config.pop("groupBy", None)
        alert = census_module.fill(shape["alert"], member)
        alert.pop("source")
        alert["threshold"] = float(alert["threshold"])
        alert["channel"] = {"type": "webhook", "webhookId": webhook_id}
        config.update(source=source_id, alert=alert)
        tiles.append(
            {"id": member["name"], "x": 0, "y": row * 4, "w": 12, "h": 4, "config": config}
        )
    payload = {"name": name, "tiles": tiles, "tags": shape["dashboard"]["tags"]}
    listed = sink.request("GET", "/dashboards")
    found = next((d for d in Sink.unwrap(listed) if d.get("name") == name), None)
    if found is None:
        created = sink.request("POST", "/dashboards", payload) or {}
        print(f"[dashboard] created {name} ({created.get('id') or created.get('_id')})")
    else:
        dashboard_id = str(found.get("id") or found.get("_id"))
        sink.request("PATCH", f"/dashboards/{dashboard_id}", payload)
        print(f"[dashboard] updated {name} ({dashboard_id})")
    for tile in tiles:
        print(f"[alert]  tile {tile['id']} on {name}")


def ensure_webhook(sink: Sink, spec: dict, url: str) -> str:
    # `?service=` because ClickStack's list route validates a query parameter;
    # we only ever create the one service, so asking for it is also the narrower
    # question.
    listed = sink.request("GET", f"/webhooks?service={spec['service']}")
    existing = {w.get("name"): w for w in Sink.unwrap(listed)}
    found = existing.get(spec["name"])
    payload = {
        "name": spec["name"],
        "service": spec["service"],
        "url": url,
        "description": f"Alert delivery. URL from slot: {spec['url_slot']}",
        "body": spec["body"],
    }
    if found is None:
        created = sink.request("POST", "/webhooks", payload)
        webhook_id = str((created or {}).get("data", {}).get("_id"))
        print(f"[webhook] created {spec['name']} ({webhook_id})")
        return webhook_id
    webhook_id = str(found.get("_id") or found.get("id"))
    sink.request("PUT", f"/webhooks/{webhook_id}", payload)
    print(f"[webhook] updated {spec['name']} ({webhook_id})")
    return webhook_id


def ensure_saved_search(sink: Sink, spec: dict, source_id: str, fields: dict) -> str:
    name = spec["name"].format(**fields)
    existing = {s.get("name"): s for s in Sink.unwrap(sink.request("GET", "/saved-search"))}
    payload = {
        "name": name,
        "select": spec["select"].format(**fields),
        "where": spec["where"].format(**fields),
        "whereLanguage": spec["whereLanguage"],
        "orderBy": spec["orderBy"],
        "source": source_id,
        "tags": ["alerts"],
    }
    found = existing.get(name)
    if found is None:
        created = sink.request("POST", "/saved-search", payload)
        body = created.get("data", created) if isinstance(created, dict) else {}
        search_id = str(body.get("id") or body.get("_id"))
        print(f"[search] created {name} ({search_id})")
        return search_id
    search_id = str(found.get("id") or found.get("_id"))
    sink.request("PATCH", f"/saved-search/{search_id}", payload)
    print(f"[search] updated {name} ({search_id})")
    return search_id


def ensure_alert(sink: Sink, spec: dict, search_id: str, webhook_id: str, fields: dict) -> None:
    name = spec["name"].format(**fields)
    payload = {
        "source": spec["source"],
        "savedSearchId": search_id,
        "channel": {"type": "webhook", "webhookId": webhook_id},
        # A spike's shape spells its declared window and count as fields to fill.
        "interval": str(spec["interval"]).format(**fields),
        "threshold": int(str(spec["threshold"]).format(**fields)),
        "thresholdType": spec["thresholdType"],
        "name": name,
        "message": spec["message"].format(**fields),
    }
    # KEYED ON THE SAVED SEARCH, not on the alert's name. `GET /alerts` does
    # not return `name` at all (it returns the saved search's), so a name key
    # never matches and every re-run creates a duplicate. The census is one
    # alert per saved search, so the saved search's id IS the identity.
    existing = Sink.unwrap(sink.request("GET", "/alerts"))
    for alert in existing:
        if str(alert.get("savedSearchId")) == search_id:
            alert_id = str(alert.get("id") or alert.get("_id"))
            sink.request("PUT", f"/alerts/{alert_id}", payload)
            print(f"[alert]  updated {name} ({alert_id})")
            return
    sink.request("POST", "/alerts", payload)
    print(f"[alert]  created {name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=os.environ.get("CLICKSTACK_URL", DEFAULT_URL))
    parser.add_argument("--dry-run", action="store_true", help="print the census and stop")
    args = parser.parse_args(argv)

    definitions = json.loads(DEFINITIONS.read_text(encoding="utf-8"))
    # THE NAMESPACE IS CONFIGURATION AND HAS NO DEFAULT (the grammar of the
    # `DJB_ZONE_ID` refusal in deploy/dns.sh). The alert bundle's name and
    # the slot this script tells an operator to fill are both this deployment's own coordinates, and
    # `definitions.json` deliberately spells neither. Resolved BEFORE the
    # `--dry-run` return, so a dry run is the free way to read what a real run
    # would reconcile — and so the refusal is reachable without a sink.
    namespace = os.environ.get("DJB_DEPLOY_NAMESPACE", "")
    if not namespace:
        print(
            "REFUSING: DJB_DEPLOY_NAMESPACE is not in the environment. It is this "
            "deployment's namespace — the alert bundle is named for it and the "
            "delivery URL's Secrets Manager slot is under it. There is no default: "
            "a guessed namespace reconciles a bundle in somebody else's sink and "
            "points an operator at somebody else's secret. It is a slot in this "
            "environment's env file (deploy/env.staging.example); on a box "
            "`set -a; . deploy/.env; set +a` exports it."
        )
        return 2
    webhook = definitions["webhook"]
    webhook["name"] = webhook["name"].format(namespace=namespace)
    webhook["url_slot"] = webhook["url_slot"].format(namespace=namespace)
    print(f"[webhook] bundle {webhook['name']}, slot {webhook['url_slot']}")
    print()

    problems = census_module.shape_problems(definitions)
    if problems:
        print("REFUSING: the census kinds and definitions.json's shapes disagree:")
        print("\n".join(f"  {problem}" for problem in problems))
        return 2

    result = census_module.census(census_module.repo_root())
    print(census_module.render(result))
    print()
    if result["warnings"]:
        print("REFUSING: the census raised a warning; fix the declaration first.")
        return 3
    if args.dry_run:
        return 0

    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    webhook_env = definitions["webhook"]["url_env"]
    if not os.environ.get(webhook_env):
        missing.append(webhook_env)
    if missing:
        print(
            "REFUSING: these are not in the environment: "
            + ", ".join(missing)
            + f"\nThe delivery URL comes from the slot {definitions['webhook']['url_slot']}; "
            "on a box, `set -a; . deploy/.env; set +a` after `provision.sh secrets-fetch`."
        )
        return 2

    sink = Sink(args.url)
    sink.authenticate(os.environ["CLICKSTACK_ADMIN_EMAIL"], os.environ["CLICKSTACK_ADMIN_PASSWORD"])
    source_id = logs_source_id(sink)
    webhook_url = os.environ[webhook_env]
    # Host and length, never the value: a webhook URL is a bearer credential and
    # this line goes into reports (the secrets doctrine's "slot and length").
    host = webhook_url.split("/")[2] if "://" in webhook_url else "?"
    print(f"[webhook] destination from ${webhook_env}: {len(webhook_url)} chars, host {host}")
    webhook_id = ensure_webhook(sink, definitions["webhook"], webhook_url)

    # ONE MEMBER OF THE CENSUS IS NOT CLICKSTACK'S, AND IT IS SKIPPED HERE
    # RATHER THAN LEFT OUT OF THE CENSUS. The deaf-sink alert is delivered by
    # the prober's own POST (ADR obs-2 as amended) — a sink cannot
    # be asked to announce that it stopped accepting. Leaving it out of
    # `census.py` would make the alert surface two lists; leaving it in and
    # trying to create it here would make `apply.py` build a ClickStack alert
    # over rows that, by construction, are exactly the rows that never arrive.
    # So the census carries it, the census names its deliverer, and this loop
    # reconciles the deliverer it owns.
    applied = 0
    traces: list[dict] = []
    for member in result["alerts"]:
        if member.get("delivered_by") != "clickstack":
            print(
                f"[skip] {member['name']}: delivered by {member.get('delivered_by')}, "
                "not by this sink (deploy/observability/alerts/prober.sh)"
            )
            continue
        # One shape per kind (`census.KINDS`); `traces` rides one dashboard, not a saved search.
        kind = member["kind"]
        if kind not in census_module.KINDS:
            print(
                f"REFUSING: census member {member['name']!r} has kind {kind!r}, "
                f"which definitions.json declares no shape for. The census and the "
                f"shapes have to be edited together."
            )
            return 2
        if kind == "traces":
            traces.append(member)
            applied += 1
            continue
        shape = definitions[kind]
        search_id = ensure_saved_search(sink, shape["saved_search"], source_id, member)
        ensure_alert(sink, shape["alert"], search_id, webhook_id, member)
        applied += 1

    if traces:
        ensure_traces_dashboard(sink, definitions["traces"], traces, webhook_id, namespace)

    print(f"\nApplied {applied} alerts. Re-run is a no-op.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
