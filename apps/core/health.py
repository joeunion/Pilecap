"""Liveness and readiness — the two questions an orchestrator asks.

They are deliberately different questions, and conflating them is the classic
way to turn one slow dependency into a full outage:

* **`/healthz` — liveness. "Is this process alive?"** It touches nothing. No
  database, no cache, no Temporal. A liveness probe that checked the database
  would restart every web container in the fleet the moment Postgres failed
  over — which removes the only thing that could have served the cached and
  static parts of the product, and delays recovery by however long a cold start
  takes. The honest answer to "is this process alive" is that it answered.

* **`/readyz` — readiness. "Should traffic be sent here?"** This one does check:
  a `SELECT 1`, a cache round-trip, a channel-layer round-trip, a Temporal
  connection, and — where the deployment has one — a `HEAD` on its
  object-storage bucket. A member that
  fails comes back `false` and the whole response is **503**, so a load balancer
  stops sending requests to a replica that cannot serve them — without killing
  it, so it rejoins by itself when the dependency comes back. `checks()` owns
  the membership, including what is deliberately *not* a member.

**Neither is authenticated, and that is deliberate.** Both are mounted outside
`/api/v1/` — plain Django views in `config/urls.py`, not ninja routes — which
is what keeps them out of the API's `auth=`, out of its throttles, and out of
the `Idempotency-Key` middleware (which only inspects writes under `/api/`).
A probe has no credential to present: kubelet, an ALB target group and a
compose healthcheck all speak unauthenticated HTTP, and gating liveness behind
a token means a rotation outage looks exactly like a dead fleet. What they give
away is bounded on purpose — `/healthz` says nothing; `/readyz` says which named
dependencies this replica reaches, and under DEBUG only `database`, its configured name.
No versions, no hostnames, no error strings: an unreachable database is `false`,
never a connection string in a stack trace.

House rule 3 is about routes on the API. These are not on it; the reason they
are open is recorded here, and the tests assert both the openness and the
absence of any detail beyond the booleans `checks()` names.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable

from django.conf import settings
from django.core.cache import cache
from django.db import connection, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse

from apps.core.asyncdb import run_async
from apps.core.log import get_logger

log = get_logger("apps.core.health")

# How long a readiness check may take before it counts as a failure. Short on
# purpose: a probe that waits ten seconds for Temporal has already failed at the
# job it exists to do, which is to answer faster than the probe's own timeout.
READY_TIMEOUT_SECONDS = 2.0

# The HTTP answer for "this replica is not ready". 503 and not 500: nothing is
# broken about the code, and `Retry-After` semantics are what a balancer wants.
NOT_READY = 503


def check_database() -> bool:
    """One round trip to Postgres, on the connection the app actually uses."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        return bool(cursor.fetchone() == (1,))


def check_cache() -> bool:
    """A write and a read back through the cache.

    Through Django's cache API rather than a raw `PING`, because what this
    replica needs to know is whether *the connection it will actually use*
    works — a configured URL, a chosen database, a serialiser and a pool. A
    `PING` on a second connection proves the server is up and proves nothing
    about the app's route to it.

    **It was called `check_redis` and reported as `redis`, and that name was a
    claim it could not keep**. One Redis server, two routes: the cache
    rides `CACHE_URL` (database 1) and the channel layer rides `REDIS_URL`
    (database 0) — `config/settings/base.py` splits them on purpose, so that a
    `cache clear` does not throw away every socket group. A member called
    `redis` therefore said "Redis" and measured one of the two. Measured directly:
    `REDIS_URL` at a dead port answered `"redis": true, 200` while every
    websocket in the deployment was dead. The member below covers exactly what
    it is named after, and `check_channel_layer` covers the other route.
    """
    key = f"healthcheck:{uuid.uuid4()}"
    cache.set(key, "ok", 10)
    try:
        return bool(cache.get(key) == "ok")
    finally:
        cache.delete(key)


def check_channel_layer() -> bool:
    """A message sent and received back on the layer the sockets actually use.

    The other half of the same check, and it is a **readiness member rather than a
    declared blind spot** because of the test `checks()` applies to everything
    it holds: does the deployment degrade, or does a door go dark? Meilisearch
    degrades — search gets slower and plainer and answers (ADR search-2), which
    is why a `meili` member would convert a designed degradation into a
    self-inflicted outage. The channel layer has no such fallback: with it
    unreachable, `apps/realtime`'s consumer cannot join a tenant group and cannot
    receive a push, so the socket door is not slower, it is shut. A replica that
    cannot serve one of its four doors is a replica traffic should go elsewhere
    — which is the whole of what 503 means here.

    A send and a receive back, for the same reason the cache check writes and
    reads rather than pinging: what matters is the app's own route through its
    own configured layer, and `get_channel_layer()` is the same call
    `apps/realtime` makes. The channel name is unique per probe, so two replicas
    probing at once never read each other's message.

    Imported inside the function, exactly as `check_temporal` imports the
    Temporal SDK: a process that serves no sockets does not pay for the import
    on module load.
    """
    from channels.layers import get_channel_layer

    async def round_trip() -> bool:
        layer = get_channel_layer()
        if layer is None:
            return False
        channel = f"healthcheck.{uuid.uuid4().hex}"
        await layer.send(channel, {"type": "healthcheck.ping"})
        message = await layer.receive(channel)
        return bool(message.get("type") == "healthcheck.ping")

    async def probe() -> bool:
        return await asyncio.wait_for(round_trip(), timeout=READY_TIMEOUT_SECONDS)

    return run_async(probe)


def check_temporal() -> bool:
    """A real connection to the Temporal frontend, with a short timeout.

    A fresh connection rather than the app's cached client: a cached handle that
    was built an hour ago answers "yes" about an hour-old fact. `Client.connect`
    performs the gRPC handshake and a system-capabilities call, so this is a
    genuine reachability check and not a DNS lookup.

    Imported inside the function so that a process which never runs a workflow
    does not pay for the SDK import on module load — and so `core` keeps
    importing nothing above it: the *client* configuration lives in
    `apps.workflows`, but the two settings a connection needs are read here, the
    way every app reads its own configuration.
    """
    from temporalio.client import Client

    async def connect() -> bool:
        await asyncio.wait_for(
            Client.connect(
                str(settings.TEMPORAL_ADDRESS),
                namespace=str(settings.TEMPORAL_NAMESPACE),
            ),
            timeout=READY_TIMEOUT_SECONDS,
        )
        return True

    return run_async(connect)


def check_object_storage() -> bool:
    """A `HEAD` on the configured bucket, with the credentials the app uses.

    Only ever called when a bucket is named — see `checks()` for who decides
    that — so there is no "not configured" branch here to read as a pass.

    `head_bucket` rather than a list or a probe object: it is the cheapest call
    S3 has that proves reachability *and* that this credential may see this
    bucket, and it writes nothing. A readiness probe that uploaded a canary
    object would be a probe that fills a bucket with rubbish at the probe
    interval, forever.

    boto3 is imported inside the function for the reason `check_temporal`
    imports the Temporal SDK inside its own: a process that never touches
    object storage should not pay for the import at module load, and `core`
    keeps importing nothing above it.

    The timeouts and `max_attempts=0` are not decoration. boto3's defaults are
    a 60-second connect and several retries, which would hold this view open
    far past `READY_TIMEOUT_SECONDS` and past whatever timeout the probe that
    called it has — turning a slow bucket into a hung replica rather than an
    unready one.
    """
    # boto3 and botocore ship no `py.typed` marker. These two imports carried a
    # per-site `# type: ignore[import-untyped]` until the storage seam landed and
    # took the `[[tool.mypy.overrides]]` entry with it, as expected; a `strict` mypy
    # reports an ignore it no longer needs, so the two moved together.
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        endpoint_url=settings.AWS_S3_ENDPOINT_URL,
        region_name=settings.AWS_S3_REGION_NAME or None,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID or None,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY or None,
        config=Config(
            connect_timeout=READY_TIMEOUT_SECONDS,
            read_timeout=READY_TIMEOUT_SECONDS,
            retries={"max_attempts": 0},
        ),
    )
    client.head_bucket(Bucket=settings.AWS_STORAGE_BUCKET_NAME)
    return True


# The members of a readiness report, in the order they are reported. A product
# that adds a dependency adds it here, and both the endpoint and its test pick
# it up without either being edited.
def checks() -> dict[str, Callable[[], bool]]:
    """The readiness checks, resolved at call time.

    Resolved rather than frozen in a module-level dict so that a test can
    replace one function — `monkeypatch.setattr(health, "check_cache", ...)` —
    and have the endpoint see the replacement. A dict built at import time would
    hold the original three forever, and the 503 path would be untestable
    without starting a broken Redis.

    **Object storage is a member only when this deployment has one.** Naming a
    bucket is the whole switch to S3 (`config/settings/base.py`); with no bucket
    the default storage is the local filesystem, which is not a thing this
    replica can be unable to *reach*. So the member appears exactly when there
    is a remote organ to report on, rather than sitting in every report as a
    permanent `true` — a member that cannot fail is a member that reads as
    coverage while covering nothing, which is the same mistake the boundary
    comment in `config/settings/guards.py` refuses. A production readyz with no
    `storage` member is therefore itself the signal that no bucket is
    configured.

    **Meilisearch is deliberately NOT here** (ADR search-2, and the comment on
    the `meilisearch` service in `compose.yaml`). Search degrades to Postgres
    full-text when the engine is unreachable — slower and plainer, never dead —
    so a `meili` member would take a designed degradation and convert it into a
    self-inflicted outage: every replica in the fleet pulled out of the load
    balancer because search got worse. `test_health.py` asserts the membership
    set exactly, so this absence cannot be undone by accident.

    **And its sibling clause, which was missing: `cache` and
    `channel_layer` are two members because they are two routes.** Both ride
    Redis; they ride *different databases on it* (`CACHE_URL` is 1, `REDIS_URL`
    is 0) through different clients, and until 2026-08-24 one member called
    `redis` covered the first and claimed both. The rule the Meilisearch
    paragraph states is what decides membership — degradation stays out, a dark
    door comes in — and the rule this pair states is what decides NAMING: a
    member is named after what it measured, never after the server it reached
    through. Where the two members would have been one, the honest report is
    two.
    """
    members: dict[str, Callable[[], bool]] = {
        "db": check_database,
        "cache": check_cache,
        "channel_layer": check_channel_layer,
        "temporal": check_temporal,
    }
    if settings.AWS_STORAGE_BUCKET_NAME:
        members["storage"] = check_object_storage
    return members


def readiness() -> dict[str, bool]:
    """Every dependency, each `true` or `false`. Never raises.

    A check that raises is a check that failed, and the exception is logged
    rather than returned: the body of a public, unauthenticated endpoint is not
    the place a connection string belongs.
    """
    report: dict[str, bool] = {}
    for name, check in checks().items():
        try:
            report[name] = bool(check())
        except Exception:
            log.warning("core.readyz.check_failed", check=name)
            report[name] = False
    return report


# --- The two views -----------------------------------------------------------
# Plain Django views, mounted at the root in `config/urls.py`. See the module
# docstring for why they are open and why they are not ninja routes.


# A no-op under ADR perf-2; it keeps both views off the database if `ATOMIC_REQUESTS` returns.
@transaction.non_atomic_requests
def healthz(request: HttpRequest) -> HttpResponse:
    """Liveness. 200, always, as long as this process can still answer."""
    return JsonResponse({"status": "ok"})


@transaction.non_atomic_requests
def readyz(request: HttpRequest) -> HttpResponse:
    """Readiness: 200 with every member `true`, else 503 with the failing one `false`."""
    report = readiness()
    status = 200 if all(report.values()) else NOT_READY
    named = {"database": settings.DATABASES["default"]["NAME"]} if settings.DEBUG else {}
    return JsonResponse({**report, **named}, status=status)
