#!/usr/bin/env python3
"""One HTTP client for the ClickStack (HyperDX) API. `export.py` and `import.py`
are the two commands; this is the part they share.

WHY THIS EXISTS AT ALL. The saved searches and dashboards in this directory are
the observability posture, and a posture that lives in one container's Mongo
volume dies with the container (ADR obs-2's own reason for config-as-code). This
module is what makes the round trip a command rather than a memory.

THE ONE PORTABILITY RULE: **nothing here stores a HyperDX object id.** A fresh
ClickStack has a fresh team, fresh connections and fresh sources, all with new
Mongo ObjectIds, so an export that recorded `"source": "6a8a..."` would import
into a sink where that id means nothing and every saved search would come back
pointing at no data. The exported JSON names its source (`"sourceName": "Logs"`)
and `import.py` resolves the name against the target's own `/api/sources` at
import time. That is the whole difference between an export and a backup.

AUTHENTICATION, both walls, in one place:

  * the deployment's `o11y.` name is behind Caddy's basic auth (deploy/Caddyfile,
    the environments contract) — `DJB_O11Y_USER` / `DJB_O11Y_PASSWORD`;
  * HyperDX itself has a session login — `DJB_O11Y_EMAIL` / `DJB_O11Y_PASSWORD_HDX`.

HyperDX sets its session cookie with `Domain=localhost`, which a cookie jar will
not carry to `o11y.localhost`; the cookie is therefore held and sent by hand.

`DJB_O11Y_CONNECT` is `curl --resolve`, and it is here because the laptop stack
needs it: macOS resolves `o11y.localhost` for curl but Python's `getaddrinfo`
refuses a multi-label `.localhost` name outright, so the socket is opened at the
address this names while the `Host` header and the TLS SNI stay the real name —
which is what Caddy routes on. A real environment has real DNS and leaves it
unset.

  export DJB_O11Y_BASE=https://o11y.localhost:8453
  export DJB_O11Y_CONNECT=127.0.0.1:8453          # laptop stacks only
  export DJB_O11Y_USER=observer DJB_O11Y_PASSWORD=...
  export DJB_O11Y_EMAIL=you@example.com DJB_O11Y_PASSWORD_HDX=...
  python3 deploy/observability/hyperdx/import.py
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import socket
import ssl
from typing import Any
from urllib.parse import urlsplit

__all__ = ["Client", "HdxError", "client_from_env"]


class HdxError(RuntimeError):
    pass


class _Plain(http.client.HTTPConnection):
    """Keep `self.host` for the `Host` header; open the socket somewhere else."""

    def __init__(self, *args: Any, dial: tuple[str, int], **kwargs: Any) -> None:
        self._dial = dial
        super().__init__(*args, **kwargs)

    def connect(self) -> None:
        self.sock = socket.create_connection(self._dial, self.timeout, self.source_address)


class _Tls(http.client.HTTPSConnection):
    """As `_Plain`, and the TLS SNI stays the name too.

    Caddy refuses a handshake whose SNI names none of its sites and routes the
    request on the `Host` header, so both have to remain `o11y.<name>` while the
    socket goes wherever `DJB_O11Y_CONNECT` points.
    """

    def __init__(self, *args: Any, dial: tuple[str, int], **kwargs: Any) -> None:
        self._dial = dial
        super().__init__(*args, **kwargs)

    def connect(self) -> None:
        sock = socket.create_connection(self._dial, self.timeout, self.source_address)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class Client:
    """The ClickStack API, over the deployment's own edge."""

    def __init__(
        self,
        base: str,
        wall_user: str,
        wall_password: str,
        email: str,
        password: str,
        *,
        insecure: bool = False,
        connect: str = "",
    ) -> None:
        parts = urlsplit(base.rstrip("/"))
        if parts.scheme not in ("http", "https"):
            raise HdxError(f"DJB_O11Y_BASE must be http(s), not {parts.scheme!r}")
        self._tls = parts.scheme == "https"
        self._authority = parts.netloc  # what Caddy routes on
        self._prefix = parts.path
        self._name = parts.hostname or "localhost"
        self._port = parts.port or (443 if self._tls else 80)
        host, _, port = connect.partition(":")
        self._dial = (host or self._name, int(port) if port else self._port)
        self._wall = base64.b64encode(f"{wall_user}:{wall_password}".encode()).decode()
        self._insecure = insecure
        self._sid: str | None = None
        self._login(email, password)

    # --- plumbing ------------------------------------------------------------

    def _connection(self) -> http.client.HTTPConnection:
        if not self._tls:
            return _Plain(self._name, self._port, timeout=30, dial=self._dial)
        ctx = ssl._create_unverified_context() if self._insecure else ssl.create_default_context()
        return _Tls(self._name, self._port, timeout=30, context=ctx, dial=self._dial)

    def _request(self, method: str, path: str, body: Any | None = None) -> tuple[int, bytes, Any]:
        payload = None if body is None else json.dumps(body).encode()
        headers = {"Host": self._authority, "Authorization": f"Basic {self._wall}"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if self._sid:
            headers["Cookie"] = f"connect.sid={self._sid}"
        conn = self._connection()
        try:
            conn.request(method, f"{self._prefix}{path}", body=payload, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            return resp.status, data, resp.headers
        finally:
            conn.close()

    def _login(self, email: str, password: str) -> None:
        # A 302 to /search is the success shape.
        status, data, headers = self._request(
            "POST", "/api/login/password", {"email": email, "password": password}
        )
        cookie = headers.get("Set-Cookie", "") if headers else ""
        if "connect.sid=" not in cookie:
            raise HdxError(
                f"login did not set a session cookie (status {status}, body {data[:200]!r}) — "
                "wrong email or password, or first-run setup not done?"
            )
        self._sid = cookie.split("connect.sid=", 1)[1].split(";", 1)[0]

    def _json(self, method: str, path: str, body: Any | None = None) -> Any:
        status, data, _ = self._request(method, path, body)
        if status >= 400:
            raise HdxError(f"{method} {path} -> {status}: {data[:400]!r}")
        return json.loads(data or b"null")

    def get(self, path: str) -> Any:
        return self._json("GET", path)

    def post(self, path: str, body: Any) -> Any:
        return self._json("POST", path, body)

    def delete(self, path: str) -> None:
        self._json("DELETE", path)

    # --- the two name/id maps ------------------------------------------------

    def sources_by_name(self) -> dict[str, str]:
        return {s["name"]: s["id"] for s in self.get("/api/sources")}

    def sources_by_id(self) -> dict[str, str]:
        return {s["id"]: s["name"] for s in self.get("/api/sources")}


def client_from_env() -> Client:
    missing = [
        name
        for name in (
            "DJB_O11Y_BASE",
            "DJB_O11Y_USER",
            "DJB_O11Y_PASSWORD",
            "DJB_O11Y_EMAIL",
            "DJB_O11Y_PASSWORD_HDX",
        )
        if not os.environ.get(name)
    ]
    if missing:
        raise SystemExit(f"!! observability: set {', '.join(missing)} (see this file's docstring)")
    return Client(
        base=os.environ["DJB_O11Y_BASE"],
        wall_user=os.environ["DJB_O11Y_USER"],
        wall_password=os.environ["DJB_O11Y_PASSWORD"],
        email=os.environ["DJB_O11Y_EMAIL"],
        password=os.environ["DJB_O11Y_PASSWORD_HDX"],
        # A laptop stack's certificate is Caddy's internal CA. On a box it is
        # Let's Encrypt's and this is off.
        insecure=os.environ.get("DJB_O11Y_INSECURE", "") == "1",
        connect=os.environ.get("DJB_O11Y_CONNECT", ""),
    )
