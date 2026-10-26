"""ASGI entry point — the whole product, every door.

Three protocols meet here and nothing else routes them:

* **http** — `/mcp` goes to the MCP server, everything else to Django (and so
  to `/api/`, `/admin/`, `/accounts/`).
* **websocket** — the consumers every app declared, behind Django's auth stack
  and the ASGI tenant middleware.
* **lifespan** — handed to the MCP app, whose Streamable HTTP transport starts
  its session manager there. Django itself has no lifespan to run.

Discovery: an app contributes sockets by exposing `websocket_urlpatterns` in
`consumers.py`. There are none yet, and an empty router is correct rather than
an error — the mount is laid so that the first app to add one edits no shared
file.
"""

from __future__ import annotations

import os
from typing import Any

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

from django.core.asgi import get_asgi_application  # noqa: E402

django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from apps.core.asgi_middleware import TenantMiddlewareASGI  # noqa: E402
from apps.core.discovery import declared  # noqa: E402
from config.mcp import MCP_PATH, build_http_app  # noqa: E402


def discovered_websocket_urlpatterns() -> list[Any]:
    """Every installed `apps.*.consumers.websocket_urlpatterns`, in app order."""
    patterns: list[Any] = []
    for _config, declared_patterns in declared(
        "consumers", "websocket_urlpatterns", predicate=lambda value: isinstance(value, list)
    ):
        patterns.extend(declared_patterns)
    return patterns


def build_application() -> ProtocolTypeRouter:
    """Assemble the whole ASGI application.

    This is a function rather than a module-level expression because the MCP
    transport's session manager may be started exactly once per instance: a test
    that runs the lifespan needs its own application, and a server needs one
    too.
    """
    mcp_app = build_http_app()

    async def http_router(scope: dict[str, Any], receive: Any, send: Any) -> None:
        """One HTTP entry point, two applications behind it."""
        path = scope.get("path", "")
        if path == MCP_PATH or path.startswith(f"{MCP_PATH}/"):
            await mcp_app(scope, receive, send)
            return
        await django_asgi_app(scope, receive, send)

    return ProtocolTypeRouter(
        {
            "http": http_router,
            "websocket": AuthMiddlewareStack(
                TenantMiddlewareASGI(URLRouter(discovered_websocket_urlpatterns()))
            ),
            "lifespan": mcp_app,
        }
    )


application = build_application()
