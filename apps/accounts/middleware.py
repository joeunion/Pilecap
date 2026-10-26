"""Idle logoff: a session-cookie request slides the window; a ping, a bearer, the clock do not."""

from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from apps.core.time import now

#: The session key holding the epoch second of the last slide.
TOUCHED_KEY = "accounts.touched_at"
#: At most one slide write a minute; the effective idle bound is 840–900 s at the default 900.
TOUCH_SECONDS = 60


def stamp(request: HttpRequest) -> None:
    """Record this instant as the session's last slide."""
    request.session[TOUCHED_KEY] = int(now().timestamp())


# Blind spot: an unstamped session reads last_login, which a later sign-in elsewhere moves.
class IdleSessionMiddleware:
    """Slide an authenticated session's expiry, at most once per `TOUCH_SECONDS`."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            touched = request.session.get(TOUCHED_KEY)
            if touched is None and user.last_login is not None:
                touched = user.last_login.timestamp()
            if touched is None or now().timestamp() - touched >= TOUCH_SECONDS:
                stamp(request)
        return self.get_response(request)
