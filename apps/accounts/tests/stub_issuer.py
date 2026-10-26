"""An OpenID Connect issuer, in this process, signing real JWTs.

**The suite's IdP** (ADR ident-5). `config/settings/test.py` points
`ZITADEL_ISSUER` at a port nothing may listen on, so no test can reach a real
Zitadel by accident; a test that needs an identity provider starts one of these
instead, on an ephemeral loopback port, and points the provider settings at it.

It is deliberately **not** a mock of allauth. allauth reaches an issuer over
`requests` — the discovery document, the token endpoint, the JWKS, the userinfo
endpoint — so a stub that patched those calls would prove our settings and
nothing else. This serves real HTTP on a real socket and signs real RS256
tokens with a real 2048-bit key, so the code under test is allauth's actual
protocol implementation: its state handling, its PKCE verifier round trip, its
`jwt.decode` with issuer, audience and expiry all enforced.

The signing is done with `cryptography` directly rather than through a JWT
library, for two reasons. It is the one direct dependency that can already do
it — `pyjwt` arrives here transitively through
`django-allauth[socialaccount]`, and the MCP door's validator promotes it — and
producing a token whose signature is deliberately **wrong** is one line when you
hold the primitive and a fight when you hold a library built to stop you.

## What it records

Every request lands in `requests`, and the token exchange's form body lands in
`token_requests`. That is what makes "the flow carried PKCE" provable at the far
end rather than only in the redirect: the verifier a client sends to `/token` is
the half an interceptor never sees.

## What it cannot prove

allauth **skips id_token signature verification on the authorization-code
flow**, deliberately and correctly: the token came back over a direct connection
to the issuer, which OpenID Connect Core §3.1.3.7 says is sufficient
(`allauth/socialaccount/providers/openid_connect/views.py`,
`verify_signature = not self.did_fetch_access_token`). Issuer, audience and
expiry *are* enforced there. So the signature path is exercised against the same
verifier by calling it the way a **resource server** does — which is exactly the
call the MCP door's bearer validation makes, against this same JWKS.
"""

from __future__ import annotations

import base64
import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

# The key id the JWKS publishes and every token header names. A fixed string
# because `lookup_kid_jwk` matches on it, and a mismatch is the failure that
# looks like a signature failure and is not.
KID = "stub-issuer-key"

# Generated once per process. A 2048-bit RSA keygen is ~100ms, which is fine
# once and not fine per test.
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)

# A second key, never published in the JWKS. Signing with it produces a token
# that is well-formed in every way except the one under test.
_WRONG_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def b64u(raw: bytes) -> str:
    """base64url, unpadded — the only encoding a JWT uses."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _int_to_b64u(value: int) -> str:
    return b64u(value.to_bytes((value.bit_length() + 7) // 8, "big"))


def sign_jwt(claims: dict[str, Any], *, key: rsa.RSAPrivateKey | None = None) -> str:
    """A real RS256 JWT over these claims.

    `key` defaults to the one the JWKS publishes. Passing `_WRONG_KEY` (see
    `wrongly_signed`) produces the negative case: a token that parses, carries
    the right `kid`, and whose signature does not verify against the key that
    `kid` names.
    """
    header = {"alg": "RS256", "typ": "JWT", "kid": KID}
    signing_input = f"{b64u(json.dumps(header).encode())}.{b64u(json.dumps(claims).encode())}"
    signature = (key or _KEY).sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input}.{b64u(signature)}"


def wrongly_signed(claims: dict[str, Any]) -> str:
    """The same claims, signed with a key the JWKS does not publish."""
    return sign_jwt(claims, key=_WRONG_KEY)


def jwks() -> dict[str, Any]:
    """The public half, in the shape `allauth.socialaccount.internal.jwtkit` reads."""
    numbers = _KEY.public_key().public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": KID,
                "n": _int_to_b64u(numbers.n),
                "e": _int_to_b64u(numbers.e),
            }
        ]
    }


class StubIssuer:
    """One running issuer: its URL, its claims, and what it was asked."""

    def __init__(self) -> None:
        self.base_url = ""
        self.client_id = "stub-client-id"
        # What the next id_token and userinfo response will assert. A test
        # changes these before driving the callback; that is the whole knob.
        self.subject = "zitadel-subject-1"
        self.email = "person@example.com"
        self.email_verified = True
        # The realm the person lives in, as the platform names it when the
        # authorize asked `urn:zitadel:iam:user:resourceowner` — MEASURED on the
        # pinned build (2026-09-30): an unconfined authorize carrying that scope
        # answers these three claims in the id_token AND the userinfo, and one
        # without it answers none. `None` is the platform that was not asked.
        self.resource_owner: dict[str, str] | None = None
        # Overrides for the negative cases, each `None` when not under test.
        self.audience_override: str | None = None
        self.expires_in: int = 300
        self.sign_with_wrong_key = False
        # Everything it was asked, in order.
        self.requests: list[tuple[str, str]] = []
        self.token_requests: list[dict[str, list[str]]] = []

    # --- the documents it serves -------------------------------------------

    def discovery(self) -> dict[str, Any]:
        return {
            "issuer": self.base_url,
            "authorization_endpoint": f"{self.base_url}/authorize",
            "token_endpoint": f"{self.base_url}/token",
            "userinfo_endpoint": f"{self.base_url}/userinfo",
            "jwks_uri": f"{self.base_url}/jwks",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "scopes_supported": ["openid", "profile", "email"],
            "code_challenge_methods_supported": ["S256"],
            # `client_secret_post` on purpose: allauth's `basic_auth` property
            # reads this list, and posting the credentials in the form body is
            # what lets a test assert on them.
            "token_endpoint_auth_methods_supported": ["client_secret_post"],
        }

    def claims(self) -> dict[str, Any]:
        now = int(time.time())
        return {
            "iss": self.base_url,
            "aud": self.audience_override or self.client_id,
            "sub": self.subject,
            "email": self.email,
            "email_verified": self.email_verified,
            "iat": now,
            # Deliberately no `jti`: allauth blacklists one per issuer to stop
            # replay, and a fixed jti would make the *second* login in a test
            # fail as a replay of the first.
            "exp": now + self.expires_in,
            **self._resource_owner_claims(),
        }

    def _resource_owner_claims(self) -> dict[str, str]:
        if self.resource_owner is None:
            return {}
        return {
            f"urn:zitadel:iam:user:resourceowner:{field}": value
            for field, value in self.resource_owner.items()
        }

    def id_token(self) -> str:
        claims = self.claims()
        return wrongly_signed(claims) if self.sign_with_wrong_key else sign_jwt(claims)

    def userinfo(self) -> dict[str, Any]:
        return {
            "sub": self.subject,
            "email": self.email,
            "email_verified": self.email_verified,
            **self._resource_owner_claims(),
        }


class _Handler(BaseHTTPRequestHandler):
    issuer: StubIssuer

    def log_message(self, *args: Any) -> None:
        """Silence. The server's own stderr logging is noise in a test run."""

    def _send(self, body: dict[str, Any], status: int = 200) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's name
        path = urlparse(self.path).path
        self.issuer.requests.append(("GET", path))
        if path == "/.well-known/openid-configuration":
            self._send(self.issuer.discovery())
        elif path == "/jwks":
            self._send(jwks())
        elif path == "/userinfo":
            self._send(self.issuer.userinfo())
        else:
            self._send({"error": "not_found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's name
        path = urlparse(self.path).path
        self.issuer.requests.append(("POST", path))
        length = int(self.headers.get("Content-Length", "0"))
        form = parse_qs(self.rfile.read(length).decode())
        if path != "/token":
            self._send({"error": "not_found"}, status=404)
            return
        self.issuer.token_requests.append(form)
        self._send(
            {
                "access_token": "stub-access-token",
                "token_type": "Bearer",
                "expires_in": self.issuer.expires_in,
                "id_token": self.issuer.id_token(),
            }
        )


@contextmanager
def running_issuer() -> Iterator[StubIssuer]:
    """Start one on an ephemeral loopback port; stop it whatever happens.

    Port 0 so parallel test processes cannot collide, and `127.0.0.1` so the
    socket is unreachable from anywhere but this machine.
    """
    issuer = StubIssuer()
    handler = type("_BoundHandler", (_Handler,), {"issuer": issuer})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    issuer.base_url = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield issuer
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
