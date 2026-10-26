"""Every door reads the client's address, through the one proxy the deployment declares."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from django.conf import settings as django_settings
from uvicorn.config import Config

from apps.accounts.tests.test_signin_door import (  # noqa: F401 — fixtures, by name
    WRONG_PASSWORD,
    door,
    ours,
)
from apps.core import mcp

COMPOSE = Path(django_settings.BASE_DIR) / "deploy" / "compose.yaml"
LOGIN_URL = "/accounts/login/"
#: The stack's network as `provision.sh env-file` writes it, and Caddy's address on it.
STACK, CADDY = "10.213.7.0/24", "10.213.7.5"
FIRST, SECOND, OUTSIDER = "203.0.113.9", "198.51.100.7", "192.0.2.44"


def deployed_trust() -> str | None:
    """What `deploy/compose.yaml` hands uvicorn: the stack's network, or None (the default)."""
    composed = yaml.safe_load(COMPOSE.read_text())
    declared = (composed["services"]["web"].get("environment") or {}).get("FORWARDED_ALLOW_IPS")
    if declared is None:
        return None
    network = composed.get("networks", {}).get("default", {}).get("ipam", {}).get("config", [{}])
    names = {
        re.sub(r"[:?}].*", "", str(v)).lstrip("${") for v in (declared, network[0].get("subnet"))
    }
    assert len(names) == 1, f"web trusts {declared!r}; the network is {network!r}"
    return STACK


def as_uvicorn_wraps(app: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """`app` behind the middleware uvicorn loads, holding the trust the deployment declares."""
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    config = Config(app, forwarded_allow_ips=deployed_trust(), log_config=None)
    config.load()
    return config.loaded_app


async def sign_in(client: httpx.AsyncClient, address: str, forwarded: str) -> int:
    """One wrong-password try for `address`, from the client `forwarded` names."""
    page = await client.get(LOGIN_URL, headers={"x-forwarded-for": forwarded})
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.text)
    assert token is not None, page.text[:400]
    answered = await client.post(
        LOGIN_URL,
        data={
            "action": "password",
            "email": address,
            "password": WRONG_PASSWORD,
            "csrfmiddlewaretoken": token.group(1),
        },
        headers={"x-forwarded-for": forwarded},
    )
    return answered.status_code


@pytest.mark.usefixtures("door", "ours")
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_two_clients_through_one_proxy_are_two_throttle_buckets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config.asgi import build_application

    app = as_uvicorn_wraps(build_application(), monkeypatch)
    transport = httpx.ASGITransport(app=app, client=(CADDY, 44321))
    limit = int(django_settings.SIGNIN_THROTTLE_PER_MINUTE)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        spent = [await sign_in(client, f"walk-{n}@yourco.test", FIRST) for n in range(limit)]
        assert 429 not in spent, spent
        assert await sign_in(client, f"walk-{limit}@yourco.test", FIRST) == 429
        assert await sign_in(client, "someone-else@yourco.test", SECOND) != 429


def captured_client(app_scope: list[dict[str, Any]]) -> Any:
    """An ASGI app that records the scope it was handed and answers 204."""

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        app_scope.append(scope)
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    return app


@pytest.mark.asyncio
async def test_the_proxy_is_believed_and_nobody_else_is(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, Any]] = []
    app = as_uvicorn_wraps(captured_client(seen), monkeypatch)
    for peer in (CADDY, OUTSIDER):
        transport = httpx.ASGITransport(app=app, client=(peer, 44321))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await client.post("/mcp/", headers={"x-forwarded-for": FIRST})
    assert [s["client"][0] for s in seen] == [FIRST, OUTSIDER]

    subjects: list[Any] = []
    monkeypatch.setattr(mcp, "refusal", lambda *, subject: subjects.append(subject))
    mcp._refusal_for(seen[0])
    assert subjects[0].META["REMOTE_ADDR"] == FIRST
