"""THE CONTRACTION, second of three: the reference receiver after v1 is gone.

The executable half of the published contract — the receiver a subscriber
copies. After the contraction it reads one header, through the house verifier,
and the hand-rolled v1 HMAC beside it is gone with the scheme it checked.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from typing import Any

from apps.events import activities, receivers


class Handler(BaseHTTPRequestHandler):
    secret = ""
    received: list[dict[str, Any]] = []

    def do_POST(self) -> None:  # noqa: N802 - http.server's spelling
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        offered_v2 = self.headers.get(activities.SIGNATURE_V2_HEADER, "")
        verified_v2 = receivers.signature_v2_matches(
            secret=self.secret, body=raw, signature=offered_v2
        )
        self.received.append({"verified_v2": verified_v2, "signature_v2": offered_v2})
        self.send_response(200 if verified_v2 else 400)
        self.end_headers()
