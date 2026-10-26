#!/usr/bin/env python3
"""The dummy destination: an HTTP request logger that stands in for Slack.

    python3 dummy_receiver.py            # listens on 0.0.0.0:9099
    curl http://localhost:9099/_log      # the requests it has received, as JSON

WHY IT EXISTS. Performing the alert route for real fires it at a real Slack
webhook, inside whatever window the person holding that webhook has. If a
definition is wrong, that window is spent debugging a definition. This
container is the cheap insurance: it accepts exactly what Slack's incoming
webhook accepts (a POST with a JSON body carrying `text`), answers 200, and
writes every request it received to a file so a criterion can COUNT them. One
bad definition found here costs a container; found against the real
destination it costs the window.

WHAT IT IS NOT. It is not a Slack emulator and it does not validate Block Kit.
It proves the POST LEAVES ClickStack with the right body — not that Slack
accepts it. That takes the real destination, and it is a declared blind spot
rather than one implied away.

WHY STDLIB ONLY, AND WHY NO IMAGE. `python:3.12-alpine` with this file bind
mounted: no Dockerfile, no build step, nothing in the registry, and the file a
reviewer reads is the file that runs. It is laptop furniture, and laptop
furniture that needs a build is furniture nobody re-creates six months later.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("DUMMY_PORT", "9099"))
LOG_PATH = os.environ.get("DUMMY_LOG", "/var/log/dummy/requests.jsonl")

_lock = threading.Lock()


def _record(entry: dict) -> None:
    line = json.dumps(entry, sort_keys=True)
    with _lock:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    print(line, flush=True)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _reply(self, code: int, body: bytes, content_type: str = "text/plain") -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # `do_POST` and `do_GET` are BaseHTTPRequestHandler's own spelling, not ours.
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8", "replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        text = parsed.get("text") if isinstance(parsed, dict) else None
        # The open/close discriminator the criteria count on. ClickStack's
        # generic-webhook template renders `hdx_state=ALERT` when an alert
        # opens and `hdx_state=OK` when it resolves; the body template in
        # definitions.json puts it there on purpose so this file (and a human
        # reading Slack) can tell the two apart without parsing prose.
        state = "unknown"
        if isinstance(text, str):
            for token in text.split():
                if token.startswith("hdx_state="):
                    state = token.split("=", 1)[1]
        _record(
            {
                "at": datetime.now(UTC).isoformat(),
                "path": self.path,
                "state": state,
                "valid_json": parsed is not None,
                "text": text,
                "raw": None if parsed is not None else raw[:2000],
            }
        )
        # Slack answers `ok` with 200 to an incoming webhook. Same here, so a
        # non-2xx never becomes a difference between the dummy and the real
        # destination (ClickStack logs and drops a non-ok response).
        self._reply(200, b"ok")

    def do_GET(self) -> None:
        if self.path.rstrip("/") in ("/_log", "/_log.json"):
            try:
                with open(LOG_PATH, encoding="utf-8") as handle:
                    entries = [json.loads(line) for line in handle if line.strip()]
            except FileNotFoundError:
                entries = []
            body = json.dumps(entries, indent=2).encode()
            self._reply(200, body, "application/json")
            return
        if self.path.rstrip("/") in ("", "/_health"):
            self._reply(200, b"ok")
            return
        self._reply(404, b"not found")

    def log_message(self, fmt: str, *args: object) -> None:
        # Silence the default access log: the JSONL record above is the
        # artifact, and two logs of one event is one log too many.
        return


def main() -> int:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)  # noqa: S104 — a test double inside its container; the port map is the wall
    print(
        json.dumps({"event": "dummy.receiver.started", "port": PORT, "log": LOG_PATH}),
        flush=True,
    )
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
