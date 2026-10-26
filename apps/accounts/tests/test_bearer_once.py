"""A keyed bearer write resolves its token once: the door reads the answer the scope seam cached."""

from __future__ import annotations

from typing import Any

import pytest
from django.test import Client

from apps.accounts import auth as accounts_auth
from apps.accounts.models import User
from apps.accounts.services import authenticate_token, issue_token
from apps.core.actor import actor_for
from apps.core.models import Tenant

pytestmark = pytest.mark.django_db


def test_a_keyed_bearer_write_authenticates_its_token_once(
    owner: User, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, plaintext = issue_token(
        user=owner, tenant=tenant, name="keyed", actor=actor_for(user=owner, tenant=tenant)
    )
    calls: list[str] = []

    def counted(**kwargs: Any) -> Any:
        calls.append(kwargs["plaintext"])
        return authenticate_token(**kwargs)

    monkeypatch.setattr(accounts_auth, "authenticate_token", counted)
    monkeypatch.setattr("apps.accounts.services.authenticate_token", counted)
    made = Client().post(
        "/api/v1/widgets/",
        {"name": "W"},
        content_type="application/json",
        headers={"authorization": f"Bearer {plaintext}", "idempotency-key": "once-1"},
    )
    assert made.status_code == 201, made.content
    assert calls == [plaintext]
