#!/usr/bin/env python3
"""The scripted OAuth client — a verification instrument.

    uv run python scripts/oauth_demo.py
    uv run python scripts/oauth_demo.py --no-browser

**Prerequisite, on the server rather than here: `ZITADEL_MCP_AUDIENCE` must be
set in the server's `.env`** — the Zitadel project id, or the API application's
client id, whichever this instance's tokens actually carry in `aud`. Empty is
not "accept any audience", it is **the OAuth door is off**: the resource server
in `apps/accounts/oauth.py` has nothing to check a token against and refuses
every one, so leg 5 below answers 401 no matter what this client sends.
(`--project-id` is the other half of the same pair and lives here, because it is
what asks Zitadel to *put* that audience in the token.)

**What it proves, and why a script rather than a test.** Every other proof
here drives an in-process stub issuer: real RS256, real JWKS, real HTTP,
but keys we minted. That proves our verifier. It cannot prove that *Zitadel's*
tokens carry the claims our verifier demands — that the audience Zitadel puts in
`aud` is the one `ZITADEL_MCP_AUDIENCE` names, that the `sub` in an access token
is the same `sub` the browser login stored on `User.zitadel_sub`, that the
issuer string matches to the character. Those are facts about somebody else's
software, and the only instrument that can read them is a real client doing the
real dance against the real instance.

**It is a third-party client, and it holds no privilege.** House rule 27 is not
merely respected here, it is the point: this script never names `ZITADEL_PAT`
and could not use one. It authenticates **as the dev person**, through the
hosted login page, with a public client that has no secret — exactly what an
assistant on somebody else's laptop has. If this works, a stranger's client
works; if it needed the management API, it would have proved nothing.

## The five legs, in order, each printed as it happens

1. **protected-resource metadata** — `/.well-known/oauth-protected-resource` on
   *our* server (RFC 9728). This is the leg that makes the rest discoverable:
   the client is told nothing out of band except our base URL.
2. **authorization-server metadata** — the issuer named by leg 1, asked for its
   own `/.well-known/openid-configuration`; that is where the authorize and
   token endpoints come from. Neither is hard-coded here.
3. **authorization code + PKCE** — the browser leg. A code verifier is minted,
   its S256 challenge travels in the authorize URL, and the verifier is sent to
   the token endpoint at the end. A public client's entire security rests on
   this: without PKCE, anybody who can see the redirect can spend the code.
4. **token exchange** — code + verifier → access token, and the access token's
   claims are printed (decoded, *not* verified — verifying is the server's job
   and doing it here would be a second implementation to disagree with).
5. **the door** — `initialize`, `tools/list`, and **one write** through `/mcp`
   with `Authorization: Bearer <access token>`. The write is the criterion: a
   read could be answered by a door that authenticated nobody.

## Two ways to complete the browser leg

By default a browser is opened and a loopback listener catches the redirect.
`--no-browser` prints the URL, waits, and takes the redirect pasted back — which
is what a headless machine, or an agent driving this for a human, needs. Both
end at the same place; the listener is a convenience, never the proof.

The redirect URI is `http://127.0.0.1:8080/callback`, one of the two
`zitadel_seed` registers for the native client. A loopback redirect is what
RFC 8252 says a native client uses, and it is why no secret is needed: the code
comes back to a socket only this process is listening on.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import os
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser
from typing import Any

import httpx

# The pre-registered native client from `manage.py zitadel_seed` — the DCR hedge
# (ADR ident-3). A public client: no secret, PKCE instead. Overridable so the
# script survives a reseeded instance without an edit.
DEFAULT_CLIENT_ID = "387144673136803846"

# One of the two loopback URIs `zitadel_seed` registers. Fixed rather than
# ephemeral because Zitadel matches the redirect URI exactly and a wildcard port
# is a thing not every authorization server allows.
REDIRECT_URI = "http://127.0.0.1:8080/callback"

# `openid` for a subject, `profile email` so the person is recognisable in the
# console, and — the load-bearing one — `urn:zitadel:iam:org:project:id:<id>:aud`
# is how Zitadel is *told* to put a project in the access token's audience.
# Without an audience scope Zitadel mints a token whose `aud` names only the
# client, and our resource server refuses it, correctly.
BASE_SCOPES = ("openid", "profile", "email", "offline_access")

MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_HEADERS = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
}

METADATA_PATH = "/.well-known/oauth-protected-resource"


def say(leg: str, outcome: str, detail: str = "") -> None:
    """One line per leg. Plain, because a human reads this output once and acts.

    Not `core.log`: this is a standalone client that runs outside Django, has no
    settings module loaded, and its readers are a person at a terminal and a
    report. House rule 19 governs application code under `apps/` and `config/`.
    """
    line = f"[{outcome:<4}] {leg}"
    if detail:
        line = f"{line}\n         {detail}"
    print(line, flush=True)


def die(leg: str, detail: str) -> None:
    """Stop at the first leg that fails, saying which and why, verbatim.

    A demo that limps past a failed leg produces an output nobody can read: the
    interesting line is buried under consequences of it.
    """
    say(leg, "FAIL", detail)
    sys.exit(1)


# --- reading a JSON-RPC result honestly ---------------------------------
#
# A tool that **refuses** does not answer with a JSON-RPC error. MCP puts a
# refusal in the *result*: `isError: true` beside the content the tool wrote, and
# the transport is perfectly happy — 200, `jsonrpc: 2.0`, no `error` member. So a
# client that only branches on the envelope reads a refusal as an answer, which
# is exactly what this script did at the first live run: it printed
#
#     [OK  ] mcp tools/call create_widget
#            widget id=None name=None
#
# over a refusal for missing membership. **An instrument that smiles at a
# refusal proves nothing** — worse than nothing, because the verification leg
# it certifies is the one leg nobody re-checks by hand.


def refusal_detail(result: dict[str, Any]) -> str:
    """Everything a refused result says, joined into one readable line.

    Three places carry it, and which one is filled depends on how far down the
    refusal came from, so all three are read and de-duplicated rather than
    guessed at:

    * `content` — where `tool_call` in `apps/core/mcp.py` puts
      `refusal_message(wire_refusal(exc))`: `<code>: <detail>`, then the same
      remedies a screen would offer;
    * `structuredContent` — a refusal rendered as the REST body's shape,
      `{detail, code}` (`config/mcp.py`'s door-level refusals use it);
    * `error` — a tool that nested a JSON-RPC-shaped error inside its result.

    Falls back to the whole result verbatim, because a refusal we cannot parse
    is still a refusal and the operator needs to see it.
    """
    parts: list[str] = []
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("text"):
            parts.append(str(block["text"]))
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        code = structured.get("code")
        detail = structured.get("detail") or structured.get("message")
        if code and detail:
            parts.append(f"{code}: {detail}")
        elif code or detail:
            parts.append(str(code or detail))
    if result.get("error"):
        parts.append(json.dumps(result["error"]))
    unique = list(dict.fromkeys(part for part in parts if part))
    return "\n         ".join(unique) if unique else json.dumps(result)


def refusal_in(result: dict[str, Any]) -> str | None:
    """The refusal this result carries, or `None` if it carries an answer.

    `isError` is the flag the protocol defines and the one our door sets. The
    other two arms are for a result that is error-*shaped* without it — a nested
    `error`, or a `{code, detail}` body — because the cost of reading a refusal
    as an answer is a false pass and the cost of the extra arms is nothing.
    """
    if result.get("isError"):
        return refusal_detail(result)
    if result.get("error"):
        return refusal_detail(result)
    structured = result.get("structuredContent")
    if isinstance(structured, dict) and structured.get("code"):
        if structured.get("detail") or structured.get("message"):
            return refusal_detail(result)
    return None


def check_result(leg: str, result: dict[str, Any]) -> dict[str, Any]:
    """The one seam every JSON-RPC result passes through. Returns it, or dies.

    A function rather than three inline checks so that the refusal path can be
    driven directly — `apps/accounts/tests/test_oauth_demo_instrument.py` plants
    a refusal here and asserts this exits nonzero, which is the only way to
    regression-test an instrument short of arranging a live refusal.
    """
    refusal = refusal_in(result)
    if refusal is not None:
        die(leg, f"the tool REFUSED and the call was not made: {refusal}")
    return result


# --- PKCE ---------------------------------------------------------------------


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def pkce_pair() -> tuple[str, str]:
    """A verifier and its S256 challenge (RFC 7636).

    43-128 characters of unreserved alphabet; `token_urlsafe(64)` lands inside
    it. The challenge is the SHA-256 of the **ASCII of the verifier**, which is
    the detail that makes a hand-rolled PKCE fail with an opaque
    `invalid_grant`.
    """
    verifier = secrets.token_urlsafe(64)
    challenge = b64u(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def decode_segment(token: str, index: int) -> dict[str, Any]:
    """Read a JWT segment **without verifying it**.

    Printing what the token says is the whole reason this exists — it is how a
    human sees that `aud` really does name the resource. Verification is the
    server's, in `apps/accounts/oauth.py`, and a second implementation here
    would be a second thing to be wrong.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    raw = parts[index]
    padded = raw + "=" * (-len(raw) % 4)
    try:
        decoded: dict[str, Any] = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, json.JSONDecodeError):
        return {}
    return decoded


# --- the loopback listener ----------------------------------------------------


class _Catcher(http.server.BaseHTTPRequestHandler):
    """Catches exactly one redirect and hands its query back."""

    received: dict[str, list[str]]

    def log_message(self, *args: Any) -> None:
        """Silence — the server's own stderr logging would interleave with the legs."""

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's name
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != urllib.parse.urlparse(REDIRECT_URI).path:
            self.send_response(404)
            self.end_headers()
            return
        type(self).received.update(urllib.parse.parse_qs(parsed.query))
        body = b"<html><body><h1>Authorized.</h1><p>Return to the terminal.</p></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def catch_redirect(*, timeout: float) -> dict[str, list[str]]:
    """Serve until the redirect arrives or the wait runs out.

    The socket is bound **before** the browser opens (the caller's ordering), so
    a very fast human cannot beat the listener to it.
    """
    received: dict[str, list[str]] = {}
    handler = type("_BoundCatcher", (_Catcher,), {"received": received})
    parsed = urllib.parse.urlparse(REDIRECT_URI)
    server = http.server.HTTPServer((parsed.hostname or "127.0.0.1", parsed.port or 8080), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout
    try:
        while not received and time.monotonic() < deadline:
            time.sleep(0.2)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    return received


def paste_redirect() -> dict[str, list[str]]:
    """`--no-browser`: take the whole redirect URL the human pasted back."""
    print("\nPaste the full URL your browser landed on, then Enter:", flush=True)
    pasted = input("> ").strip()
    return urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query)


# --- the legs -----------------------------------------------------------------


def protected_resource(client: httpx.Client, base_url: str) -> dict[str, Any]:
    """Leg 1 — RFC 9728, from our own server. Unauthenticated, necessarily."""
    url = f"{base_url}{METADATA_PATH}"
    try:
        response = client.get(url)
    except httpx.HTTPError as error:
        die("protected-resource metadata", f"{url}: {error!r}")
    if response.status_code != 200:
        die("protected-resource metadata", f"{url}: HTTP {response.status_code} {response.text}")
    document: dict[str, Any] = response.json()
    servers = document.get("authorization_servers") or []
    if not servers:
        die("protected-resource metadata", f"names no authorization server: {document}")
    say(
        "protected-resource metadata",
        "OK",
        f"resource={document.get('resource')}  authorization_server={servers[0]}",
    )
    return document


def authorization_server(client: httpx.Client, issuer: str) -> dict[str, Any]:
    """Leg 2 — the AS's own metadata, from the issuer leg 1 named."""
    url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
    try:
        response = client.get(url)
    except httpx.HTTPError as error:
        die("authorization-server metadata", f"{url}: {error!r}")
    if response.status_code != 200:
        die("authorization-server metadata", f"{url}: HTTP {response.status_code} {response.text}")
    document: dict[str, Any] = response.json()
    for required in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not document.get(required):
            die("authorization-server metadata", f"no {required} in {document}")
    say(
        "authorization-server metadata",
        "OK",
        f"issuer={document.get('issuer')}  token_endpoint={document['token_endpoint']}",
    )
    return document


def authorize(
    *,
    metadata: dict[str, Any],
    client_id: str,
    scopes: list[str],
    no_browser: bool,
    timeout: float,
) -> str:
    """Leg 3 — the browser leg, ending in an authorization code."""
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "login",
        }
    )
    url = f"{metadata['authorization_endpoint']}?{query}"
    say("authorization request", "OPEN", url)

    if no_browser:
        returned = paste_redirect()
    else:
        # Bind first, then open: a redirect that arrives before the listener is
        # up is a connection refused and a confusing failure.
        holder: dict[str, dict[str, list[str]]] = {}
        listener = threading.Thread(
            target=lambda: holder.setdefault("q", catch_redirect(timeout=timeout)),
            daemon=True,
        )
        listener.start()
        time.sleep(0.3)
        webbrowser.open(url)
        print(f"\nWaiting up to {int(timeout)}s for the redirect...", flush=True)
        listener.join(timeout=timeout + 5)
        returned = holder.get("q", {})

    if not returned:
        die("authorization code", "no redirect arrived before the wait ran out")
    if "error" in returned:
        die("authorization code", f"{returned.get('error')}: {returned.get('error_description')}")
    # The state check is not decoration: it is what stops a code from a
    # different flow — or one an attacker induced — being spent as this one's.
    if returned.get("state", [""])[0] != state:
        die("authorization code", "the returned state does not match the one sent")
    code = returned.get("code", [""])[0]
    if not code:
        die("authorization code", f"no code in the redirect: {returned}")
    say("authorization code", "OK", f"code={code[:12]}... state verified")
    return f"{code}\n{verifier}"


def exchange(
    client: httpx.Client, *, metadata: dict[str, Any], client_id: str, code: str, verifier: str
) -> dict[str, Any]:
    """Leg 4 — code + verifier → tokens. No client secret: this is a public client."""
    try:
        response = client.post(
            str(metadata["token_endpoint"]),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": client_id,
                "code_verifier": verifier,
            },
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
    except httpx.HTTPError as error:
        die("token exchange", repr(error))
    if response.status_code != 200:
        die("token exchange", f"HTTP {response.status_code} {response.text}")
    payload: dict[str, Any] = response.json()
    access = str(payload.get("access_token") or "")
    if not access:
        die("token exchange", f"no access_token in {payload}")
    claims = decode_segment(access, 1)
    say(
        "token exchange",
        "OK",
        f"access_token={access[:16]}...  aud={claims.get('aud')}  sub={claims.get('sub')}"
        f"  iss={claims.get('iss')}",
    )
    if not claims:
        say(
            "token shape",
            "WARN",
            "the access token is opaque, not a JWT — the resource server needs a JWT; "
            "check the client's token type in Zitadel (it must be 'JWT', not 'Bearer')",
        )
    return payload


def rpc(method: str, params: dict[str, Any] | None = None, request_id: int = 1) -> dict[str, Any]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        body["params"] = params
    return body


def call_mcp(
    client: httpx.Client,
    *,
    base_url: str,
    access_token: str,
    tenant: str,
    org: str,
) -> None:
    """Leg 5 — the door itself, with somebody else's token.

    `initialize`, then `tools/list`, then **one write**. The write is what the
    criterion asks for: `create_widget` goes through the same service the REST
    door calls, so an audit row lands with `door=mcp` inside the transaction.
    """
    headers = {**MCP_HEADERS, "authorization": f"Bearer {access_token}"}
    if tenant:
        headers["X-Tenant"] = tenant
    if org:
        headers["X-Org"] = org
    url = f"{base_url}/mcp"

    def post(leg: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            response = client.post(url, headers=headers, json=body)
        except httpx.HTTPError as error:
            die(leg, repr(error))
        if response.status_code != 200:
            # The 401 body and its `WWW-Authenticate` are the useful half of a
            # refusal here, so both go out verbatim rather than as a status.
            challenge = response.headers.get("www-authenticate", "")
            die(leg, f"HTTP {response.status_code} {response.text}\n         {challenge}")
        payload = response.json()
        if "error" in payload:
            die(leg, json.dumps(payload["error"]))
        result: dict[str, Any] = payload.get("result", {})
        # The envelope was fine; the tool still may have refused.
        return check_result(leg, result)

    initialized = post(
        "mcp initialize",
        rpc(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "oauth_demo", "version": "1"},
            },
        ),
    )
    say("mcp initialize", "OK", f"serverInfo={initialized.get('serverInfo')}")

    listing = post("mcp tools/list", rpc("tools/list", {}, request_id=2))
    names = sorted(tool["name"] for tool in listing.get("tools", []))
    say("mcp tools/list", "OK", f"{len(names)} tools: {', '.join(names)}")

    name = f"oauth-demo {time.strftime('%Y-%m-%d %H:%M:%S')}"
    written = post(
        "mcp tools/call create_widget",
        rpc(
            "tools/call",
            {"name": "create_widget", "arguments": {"name": name, "notes": "written by OAuth"}},
            request_id=3,
        ),
    )
    structured = written.get("structuredContent", {})
    # The belt behind `check_result`: the write leg is the criterion, and a write
    # that produced no id did not happen whatever the result called itself. This
    # is the literal shape a false pass took — `widget id=None name=None`,
    # printed as OK — so it is asserted rather than formatted.
    if not structured.get("id"):
        die(
            "mcp tools/call create_widget",
            f"the call returned no widget id, so nothing was written: {json.dumps(written)}",
        )
    say(
        "mcp tools/call create_widget",
        "OK",
        f"widget id={structured.get('id')} name={structured.get('name')}",
    )
    print(
        "\nThe audit row for that write is door=mcp, actor_kind=agent, with the "
        "OAuth user. Read it with:\n"
        '  uv run python manage.py shell -c "from apps.core.models import AuditEntry; '
        "e=AuditEntry.objects.order_by('-created_at').first(); print(e.action, e.context)\"",
        flush=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        # The prerequisite that is not a flag, printed where somebody reading
        # `--help` before a first run will see it. It is set on the
        # *server*, so no argument here can substitute for it.
        epilog=(
            "PREREQUISITE (server side): ZITADEL_MCP_AUDIENCE must be set in the "
            "server's .env — empty means the OAuth door is OFF, not open, so leg 5 "
            "answers 401 whatever this client sends."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("PUBLIC_BASE_URL", "http://127.0.0.1:8000"),
        help="Where this product is running (default: PUBLIC_BASE_URL or http://127.0.0.1:8000).",
    )
    parser.add_argument(
        "--client-id",
        default=os.environ.get("ZITADEL_MCP_CLIENT_ID", DEFAULT_CLIENT_ID),
        help="The pre-registered native client from `manage.py zitadel_seed`.",
    )
    parser.add_argument(
        "--project-id",
        default=os.environ.get("ZITADEL_PROJECT_ID", ""),
        help=(
            "The Zitadel project id, added as an audience scope so the access "
            "token's `aud` names this resource. Without it Zitadel mints a token "
            "for the client alone and the resource server refuses it — correctly."
        ),
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Print the authorize URL and read the redirect URL back from stdin.",
    )
    parser.add_argument(
        "--tenant", default="", help="Sent as `X-Tenant`; omit to let memberships decide."
    )
    parser.add_argument("--org", default="", help="Sent as `X-Org`: the acting hat.")
    parser.add_argument("--timeout", type=float, default=180.0, help="Seconds to wait for consent.")
    args = parser.parse_args()

    base_url = str(args.base_url).rstrip("/")
    scopes = list(BASE_SCOPES)
    if args.project_id:
        scopes.append(f"urn:zitadel:iam:org:project:id:{args.project_id}:aud")

    print(f"OAuth demo against {base_url}\n", flush=True)
    with httpx.Client(timeout=httpx.Timeout(30.0), follow_redirects=False) as client:
        resource = protected_resource(client, base_url)
        issuer = str(resource["authorization_servers"][0])
        metadata = authorization_server(client, issuer)
        code, verifier = authorize(
            metadata=metadata,
            client_id=str(args.client_id),
            scopes=scopes,
            no_browser=bool(args.no_browser),
            timeout=float(args.timeout),
        ).split("\n")
        tokens = exchange(
            client,
            metadata=metadata,
            client_id=str(args.client_id),
            code=code,
            verifier=verifier,
        )
        call_mcp(
            client,
            base_url=base_url,
            access_token=str(tokens["access_token"]),
            tenant=str(args.tenant),
            org=str(args.org),
        )
    print("\nAll legs passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
