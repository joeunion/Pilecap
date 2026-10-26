"""The idle logoff over the session door: a request slides the window, silence ends it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from django.conf import settings
from django.contrib.sessions.models import Session
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.middleware import TOUCH_SECONDS, TOUCHED_KEY
from apps.accounts.models import User

pytestmark = pytest.mark.django_db

PROBE_URL = "/api/v1/auth/sso-connections/"
T0 = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


class Clock:
    """A frozen `timezone.now` the test moves by hand."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.at = T0
        monkeypatch.setattr(timezone, "now", lambda: self.at)

    def to(self, seconds: int) -> None:
        self.at = T0 + timedelta(seconds=seconds)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    return Clock(monkeypatch)


def session_row(api: Client) -> Session:
    return Session.objects.get(session_key=api.cookies[settings.SESSION_COOKIE_NAME].value)


def session_writes(captured: CaptureQueriesContext) -> list[str]:
    return [
        query["sql"]
        for query in captured.captured_queries
        if "django_session" in query["sql"] and not query["sql"].startswith("SELECT")
    ]


def get(api: Client, url: str) -> tuple[Any, list[str]]:
    with CaptureQueriesContext(connection) as captured:
        response = api.get(url)
    return response, session_writes(captured)


def test_a_request_slides_the_window_once_a_minute_and_silence_ends_it(
    api: Client, owner: User, clock: Clock
) -> None:
    idle = settings.SESSION_IDLE_SECONDS
    api.force_login(owner)
    assert session_row(api).expire_date == T0 + timedelta(seconds=idle)

    clock.to(30)
    response, writes = get(api, PROBE_URL)
    assert response.status_code == 200
    assert writes == [], "a request inside the touch interval writes nothing"
    assert session_row(api).expire_date == T0 + timedelta(seconds=idle)

    slid = TOUCH_SECONDS + 1
    clock.to(slid)
    response, writes = get(api, PROBE_URL)
    assert response.status_code == 200
    assert len([sql for sql in writes if sql.startswith("UPDATE")]) == 1
    assert session_row(api).expire_date == T0 + timedelta(seconds=slid + idle)

    clock.to(slid + 30)
    response, writes = get(api, PROBE_URL)
    assert response.status_code == 200
    assert writes == [], "the stamp the slide wrote holds the next minute"

    clock.to(slid + idle + 1)
    refused = api.get(PROBE_URL)
    assert refused.status_code == 401, refused.content
    assert refused.json()["code"] == "unauthenticated"
    page = api.get(reverse("welcome"))
    assert page.status_code == 302
    assert page["Location"] == f"{settings.LOGIN_URL}?next={reverse('welcome')}"
    key = api.cookies[settings.SESSION_COOKIE_NAME].value
    assert not Session.objects.filter(session_key=key, expire_date__gt=timezone.now()).exists()


def test_the_slide_records_its_instant_in_the_session(
    api: Client, owner: User, clock: Clock
) -> None:
    api.force_login(owner)
    clock.to(TOUCH_SECONDS + 1)
    api.get(PROBE_URL)

    assert session_row(api).get_decoded()[TOUCHED_KEY] == int(clock.at.timestamp())


def test_an_anonymous_request_makes_no_session(api: Client) -> None:
    before = Session.objects.count()
    assert api.get(PROBE_URL).status_code == 401
    assert api.get(reverse("welcome")).status_code == 302
    assert Session.objects.count() == before


def test_a_bearer_call_slides_nothing(api: Client, owner: User, clock: Clock) -> None:
    from apps.accounts.services import issue_token
    from apps.core.actor import actor_for

    tenant = owner.memberships.get().tenant
    _, plaintext = issue_token(
        user=owner, tenant=tenant, name="cli", actor=actor_for(user=owner, tenant=tenant)
    )
    before = Session.objects.count()
    clock.to(TOUCH_SECONDS + 1)
    response, writes = get(Client(headers={"Authorization": f"Bearer {plaintext}"}), PROBE_URL)
    assert response.status_code == 200, response.content
    assert writes == []
    assert Session.objects.count() == before


def test_the_adapters_login_stamps_the_window(owner: User, clock: Clock) -> None:
    from importlib import import_module

    from django.test import RequestFactory

    from apps.accounts.adapter import AccountAdapter

    request = RequestFactory().get("/")
    request.session = import_module(settings.SESSION_ENGINE).SessionStore()
    AccountAdapter(request).login(request, owner)

    assert request.session[TOUCHED_KEY] == int(T0.timestamp())
