"""Planted: the first resource this server has ever held, and no wall in front of it.

`resources/read` is a dispatch surface of its own — its own manager, its own
validation, its own path through the transport — and the token ceiling
(`install_ceiling_gate`) is installed on `tools/call` and nowhere else. Nothing
is exposed by that today because nothing is registered; the moment something is,
a bearer whose ceiling reaches nothing here is answered about the request
instead of refused, which is exactly the shape closed one surface over.

This is the FIRST registration, which is the moment the rule exists for.
"""

from typing import Any


def register(server: Any) -> None:
    @server.resource("widget://catalogue")
    def widget_catalogue() -> str:
        return "every widget this tenant can see"
