"""What the two probe endpoints promise.

The properties, not the mechanisms: liveness answers without a database,
readiness reports one boolean per dependency, a failing dependency turns the
whole answer into a 503 with that member `false`, and neither endpoint asks for
a credential or leaks anything past those booleans.

The last section is about the membership itself — which organs are in the
report, and which one is kept out on purpose.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.conf import settings
from django.test import Client, override_settings
from django.urls import reverse

from apps.core import health


def test_healthz_answers_without_a_database(api: Client) -> None:
    """No `django_db` mark on purpose: touching the database here would fail.

    That absence is the test. `/healthz` is liveness — it must answer while
    Postgres is unreachable, because restarting every replica is the wrong
    response to a database failover.
    """
    response = api.get(reverse("healthz"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthz_needs_no_credential(api: Client) -> None:
    """Anonymous, no session, no bearer token, no `X-Tenant`."""
    assert api.get("/healthz").status_code == 200


@pytest.mark.django_db
def test_readyz_reports_every_dependency(api: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redis and Temporal are not running under pytest; the database is."""
    monkeypatch.setattr(health, "check_temporal", lambda: True)

    response = api.get(reverse("readyz"))

    assert response.status_code == 200
    assert response.json() == {
        "db": True,
        "cache": True,
        "channel_layer": True,
        "temporal": True,
    }


@pytest.mark.django_db
def test_readyz_is_503_when_a_member_fails(api: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    """One failing dependency, and the whole replica stops taking traffic."""
    monkeypatch.setattr(health, "check_temporal", lambda: False)

    response = api.get(reverse("readyz"))

    assert response.status_code == 503
    assert response.json() == {
        "db": True,
        "cache": True,
        "channel_layer": True,
        "temporal": False,
    }


@pytest.mark.django_db
def test_readyz_turns_a_raising_check_into_false(
    api: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dependency that blows up is unready, not a 500 — and says nothing more.

    The body is exactly the three booleans: a public endpoint that echoed a
    connection error would hand a host, a port and often a username to anyone
    who asked.
    """

    def explode() -> bool:
        raise ConnectionRefusedError(
            "postgres://djb:djb@10.0.0.7:5432/secrets"  # pragma: allowlist secret
        )

    monkeypatch.setattr(health, "check_database", explode)
    monkeypatch.setattr(health, "check_temporal", lambda: True)

    response = api.get(reverse("readyz"))
    body: dict[str, Any] = response.json()

    assert response.status_code == 503
    assert body == {"db": False, "cache": True, "channel_layer": True, "temporal": True}
    assert "10.0.0.7" not in response.content.decode()


@pytest.mark.django_db
def test_readyz_needs_no_credential_and_no_tenant(
    api: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anonymous, and with no membership there is no tenant — still answered.

    The API refuses an anonymous request; these two are outside it, which is the
    whole reason they are mounted at the root.
    """
    monkeypatch.setattr(health, "check_temporal", lambda: True)

    assert api.get("/readyz").status_code == 200


@pytest.mark.django_db
def test_the_probes_are_outside_the_versioned_api(api: Client) -> None:
    """Nothing under `/api/v1/` answers these, and the API still refuses anonymity.

    Together these are the claim in the docstring of `config/urls.py`: the
    probes inherit none of the API's machinery because they are not on it.
    """
    assert api.get("/api/v1/healthz").status_code == 404
    assert api.get("/api/v1/widgets/").status_code == 401


@pytest.mark.django_db
def test_readiness_survives_every_dependency_being_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`readiness()` never raises, whatever the world is doing."""

    def explode() -> bool:
        raise RuntimeError("down")

    for name in ("check_database", "check_cache", "check_channel_layer", "check_temporal"):
        monkeypatch.setattr(health, name, explode)

    assert health.readiness() == {
        "db": False,
        "cache": False,
        "channel_layer": False,
        "temporal": False,
    }


@pytest.mark.django_db
def test_database_check_is_a_real_round_trip() -> None:
    assert health.check_database() is True


def test_cache_check_round_trips_through_the_cache(db: None) -> None:
    """Under pytest the cache is locmem; the property is the round trip, not Redis."""
    assert health.check_cache() is True


def test_channel_layer_check_round_trips_through_the_layer(db: None) -> None:
    """Under pytest the layer is in-memory; the property is the round trip.

    Which is the honest shape either way: what this member reports is whether
    THIS replica can send and receive on the layer it is configured with, and
    the configuration is not this check's business.
    """
    assert health.check_channel_layer() is True


# --- The object-storage organ, and the one that is deliberately absent -------
#
# CP0 (cycle P6) put MinIO in `compose.yaml` and object storage in `checks()`;
# it put Meilisearch in `compose.yaml` and deliberately NOT in `checks()`. Both
# halves of that decision are asserted here, because an absence that nobody
# tests is an absence that comes back as a one-line "consistency" fix.

_A_BUCKET = "djb-uploads"


def test_object_storage_is_not_a_member_until_a_bucket_is_named() -> None:
    """No bucket means the local filesystem, and a disk is not a thing to reach.

    `config/settings/base.py` makes naming a bucket the whole switch to S3. A
    `storage: true` that only ever meant "we are writing to a local directory"
    would be a member that cannot fail — coverage-shaped, covering nothing.
    """
    assert settings.AWS_STORAGE_BUCKET_NAME == ""
    assert "storage" not in health.checks()


@override_settings(AWS_STORAGE_BUCKET_NAME=_A_BUCKET)
def test_object_storage_joins_readiness_when_a_bucket_is_named() -> None:
    assert health.checks()["storage"] is health.check_object_storage


@pytest.mark.django_db
@override_settings(AWS_STORAGE_BUCKET_NAME=_A_BUCKET)
def test_an_unreachable_bucket_stops_traffic(api: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    """A bucket this replica cannot reach is a replica that cannot serve uploads."""
    monkeypatch.setattr(health, "check_temporal", lambda: True)
    monkeypatch.setattr(health, "check_object_storage", lambda: False)

    response = api.get(reverse("readyz"))

    assert response.status_code == 503
    assert response.json() == {
        "db": True,
        "cache": True,
        "channel_layer": True,
        "temporal": True,
        "storage": False,
    }


@pytest.mark.django_db
@override_settings(AWS_STORAGE_BUCKET_NAME=_A_BUCKET)
def test_a_bucket_that_refuses_is_false_and_says_nothing_more(
    api: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An S3 error carries an endpoint, a bucket and often a key. None of it leaks."""

    def explode() -> bool:
        # An invented credential-bearing endpoint, and the point of the test is
        # that it does NOT come back out of `/readyz`. The pragma is here for
        # the same reason the Postgres URL above carries one: the scanner sees
        # a basic-auth URL and cannot tell a fixture from a leak.
        leak = "http://minioadmin:hunter2@10.0.0.9:9000/djb-uploads"  # pragma: allowlist secret
        raise ConnectionRefusedError(leak)

    monkeypatch.setattr(health, "check_temporal", lambda: True)
    monkeypatch.setattr(health, "check_object_storage", explode)

    response = api.get(reverse("readyz"))

    assert response.status_code == 503
    assert response.json()["storage"] is False
    assert "10.0.0.9" not in response.content.decode()


def test_search_is_deliberately_not_a_readiness_member() -> None:
    """ADR search-2: Meilisearch down is slower and plainer search, never an outage.

    A `meili` member would pull every replica in the fleet out of the load
    balancer because search got worse — a designed degradation converted into a
    self-inflicted outage. The membership set is asserted exactly, in both of
    its shapes, so a future dependency cannot join `/readyz` without this test
    saying so out loud.
    """
    assert set(health.checks()) == {"db", "cache", "channel_layer", "temporal"}

    with override_settings(AWS_STORAGE_BUCKET_NAME=_A_BUCKET):
        assert set(health.checks()) == {"db", "cache", "channel_layer", "temporal", "storage"}


# --- The member that claimed more than it covered ------------------------------


def test_the_cache_and_the_channel_layer_are_two_ROUTES_and_so_two_members() -> None:
    """The finding underneath the rename, asserted rather than remembered.

    One Redis server, two databases, two clients, two settings — and a single
    member called `redis` measured the first and spoke for both. This pins the
    premise: if a product ever pointed both at one URL through one client, the
    two members would stop being two facts and somebody should say so here
    rather than discovering it during an outage.

    Read from `config.settings.base` rather than from the live `settings`:
    `config/settings/test.py` replaces both with in-process backends, so the
    running configuration cannot state a premise about two Redis databases. The
    premise lives in the base module and is asserted there.
    """
    from config.settings import base

    assert base.CACHE_URL != base.REDIS_URL
    assert base.CACHES["default"]["LOCATION"] == base.CACHE_URL
    assert base.REDIS_CHANNEL_LAYER["CONFIG"]["hosts"][0]["address"] == base.REDIS_URL
    assert {"cache", "channel_layer"} <= set(health.checks())


@pytest.mark.django_db
def test_a_dead_channel_layer_stops_traffic_while_the_cache_is_fine(
    api: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A permanent regression pin.

    This exact world — cache reachable, channel layer not — used to answer
    `{"redis": true}` and **200**, so a deployment whose every websocket was
    dead stayed in the load balancer. The socket door has no fallback to degrade
    to, which is what puts it on the other side of the Meilisearch line.
    """
    monkeypatch.setattr(health, "check_temporal", lambda: True)
    monkeypatch.setattr(health, "check_channel_layer", lambda: False)

    response = api.get(reverse("readyz"))
    body: dict[str, Any] = response.json()

    assert response.status_code == 503
    assert body["cache"] is True
    assert body["channel_layer"] is False


def test_no_readiness_member_is_named_after_a_server_rather_than_a_route() -> None:
    """The naming rule the pair states, held closed.

    `redis` named the server; `cache` and `channel_layer` name what was
    measured. A member back under a server's name is the defect returning under
    a different spelling, so the vendor names are refused here by name.
    """
    vendors = {"redis", "postgres", "postgresql", "meili", "meilisearch", "s3", "minio"}
    with override_settings(AWS_STORAGE_BUCKET_NAME=_A_BUCKET):
        assert set(health.checks()) & vendors == set()


def test_the_storage_check_is_bounded_by_the_probe_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """boto3's defaults are a 60-second connect and retries on top.

    Left alone they would hold `/readyz` open long past the timeout of whatever
    asked — a slow bucket becoming a hung replica instead of an unready one. The
    client is built with the probe's own budget and no retries, and this reads
    the config off the client the function actually builds.
    """
    import boto3

    captured: dict[str, Any] = {}

    class _Client:
        def head_bucket(self, **kwargs: object) -> None:
            return None

    def fake_client(service: str, **kwargs: Any) -> _Client:
        captured.update(kwargs)
        captured["service"] = service
        return _Client()

    monkeypatch.setattr(boto3, "client", fake_client)

    with override_settings(AWS_STORAGE_BUCKET_NAME=_A_BUCKET):
        assert health.check_object_storage() is True

    assert captured["service"] == "s3"
    config = captured["config"]
    assert config.connect_timeout == health.READY_TIMEOUT_SECONDS
    assert config.read_timeout == health.READY_TIMEOUT_SECONDS
    assert config.retries == {"max_attempts": 0}
