"""The signed receiver names a sent bearer or addressing header with its own refusal."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import Client, override_settings
from django.urls import path

from apps.connections.api import SIGNATURE_HEADER, SIGNATURE_PREFIX
from apps.connections.models import Connection, InboundWebhook
from apps.connections.tests.conftest import WEBHOOK_SECRET
from apps.core.exceptions import CODE_STATUSES, REFUSALS, Forbidden
from apps.core.middleware import declare_signed_door
from apps.core.models import Tenant
from config.api import api as mounted_api

pytestmark = pytest.mark.django_db

CODE = "signed_door_takes_no_address"
JSON = "application/json"
BODY = b'{"event": "thing.happened"}'

# The URLconf copy: the same API under another prefix, so no path string can find the receiver.
urlpatterns = [path("renamed-mount/", mounted_api.urls)]


def _signed() -> dict[str, str]:
    digest = hmac.new(WEBHOOK_SECRET.encode(), BODY, hashlib.sha256).hexdigest()
    return {SIGNATURE_HEADER: SIGNATURE_PREFIX + digest}


def _post(client: Client, url: str, extra: dict[str, str]) -> Any:
    return client.post(url, data=BODY, content_type=JSON, headers={**_signed(), **extra})


def _url(connection: Connection, prefix: str = "/api/v1/") -> str:
    return f"{prefix}connections/{connection.pk}/webhook/"


def test_the_code_is_registered_with_its_fact() -> None:
    refusal = REFUSALS[CODE]
    assert refusal.fact == (
        "this door takes no bearer and no addressing header — the signature is the "
        "credential; send the signed bytes bare"
    )
    destinations = [remedy.destination for remedy in refusal.remedies]
    assert destinations[:2] == ["header:Authorization", "header:X-Tenant"]
    assert "header:X-Org" in destinations
    assert refusal.status == 403
    assert CODE_STATUSES[CODE] == 403


@pytest.mark.parametrize("header", ["Authorization", "X-Tenant", "X-Org"])
def test_a_bearer_or_address_on_the_signed_door_is_named(
    api: Client, tenant: Tenant, connection: Connection, header: str
) -> None:
    value = {"Authorization": "Bearer a-habitual-token", "X-Tenant": tenant.slug}.get(
        header, "root"
    )
    refused = _post(api, _url(connection), {header: value})

    body = json.loads(refused.content)
    assert refused.status_code == 403, body
    assert body["code"] == CODE, body
    assert header in body["detail"], body
    assert {r["destination"] for r in body["remedies"]} >= {f"header:{header}"}, body
    assert not InboundWebhook.objects.for_tenant(tenant).exists()

    bare = _post(api, _url(connection), {})
    assert bare.status_code == 202, json.loads(bare.content)


@override_settings(ROOT_URLCONF=__name__)
def test_the_signed_door_is_declared_not_matched_by_path(
    api: Client, tenant: Tenant, connection: Connection
) -> None:
    url = _url(connection, prefix="/renamed-mount/")
    refused = _post(api, url, {"X-Tenant": tenant.slug})

    assert refused.status_code == 403
    assert json.loads(refused.content)["code"] == CODE
    assert _post(api, url, {}).status_code == 202


def test_a_route_off_the_rule_3_allow_list_cannot_be_declared_signed() -> None:
    with pytest.raises(ImproperlyConfigured, match="allow_unauthenticated"):
        declare_signed_door(url_name="api:connection-list", refusal=lambda sent: Forbidden())


_FRESH_PROCESS = """
import json, uuid, django
django.setup()
from django.test import Client
from django.test.utils import setup_test_environment
setup_test_environment()
url = f"/api/v1/connections/{uuid.uuid4()}/webhook/"
answer = Client().post(url, data=b"{}", content_type="application/json",
                       headers={"Authorization": "Bearer x"})
print(json.dumps({"status": answer.status_code, "body": answer.content.decode()}))
"""


def test_the_first_request_in_a_fresh_process_is_refused() -> None:
    import subprocess
    import sys

    from django.conf import settings

    env = {**os.environ, "DJANGO_SETTINGS_MODULE": settings.SETTINGS_MODULE}
    ran = subprocess.run(  # noqa: S603 — argv list built here from constants and paths; `python`, no shell
        [sys.executable, "-c", _FRESH_PROCESS],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(settings.BASE_DIR),
        timeout=120,
        check=False,
    )
    assert ran.returncode == 0, ran.stderr[-2000:]
    answer = json.loads(ran.stdout.strip().splitlines()[-1])
    assert answer["status"] == 403, answer
    assert json.loads(answer["body"])["code"] == CODE, answer
