#!/usr/bin/env python3
"""The committed load drive — one fixed request mix, one stepped ladder, one knee.

    ./deploy/load/drive.py prepare --base-url URL --tenant SLUG
    ./deploy/load/drive.py run     --base-url URL --tenant SLUG --sha SHA [--utilization FILE]
    ./deploy/load/drive.py soak    --base-url URL --tenant SLUG --concurrency N --minutes M
    ./deploy/load/drive.py judge|baseline … --processes web=1,worker=2 · processes --compose J

(`smoke` takes run's two flags.) `DRIVE_TOKEN` in the environment is the bearer
token every call carries — never a flag: a token on a command line is in a history.

WHY IT IS COMMITTED, WHICH IS THE WHOLE POINT. LOAD-1's envelope document is falsifiable only if
somebody else can re-run the same ladder against the same sha and get the same shape — that
requirement is LOAD-1's own, stated in its cycle plan, and the platform repository is the archive
of record for those plans. A drive assembled in a terminal and thrown away produces numbers nobody
can reproduce and therefore nobody can contradict. So the mix, the ladder, the seeds and the knee's
DEFINITION are all in this file, in source, above the code that uses them — and the machine-
readable output carries a copy of every one of them, so a JSON file found later still says what it
was measured with.

WHAT IT MEASURES, AND THE ONE THING IT DOES NOT. It measures the DOORS: the latency and status of
HTTP calls to `/api/v1/...` under a closed-loop concurrency ladder. It does NOT measure which
component saturated first — that is read off ClickStack at the knee this run names, and it is
LOAD-1b's half. This script's job is to produce a knee that is a readable fact rather than an
eyeballed graph, and to say exactly how it decided.

------------------------------------------------------------------------------
THE MIX IS DECLARED, NOT EMERGENT
------------------------------------------------------------------------------
`MIX` below is the request blend, weight by weight, with each operation's kind
(read or write) beside it. A tenant's working day is mostly reads with a steady
minority of writes, so the declared blend is 9 read : 3 write. Changing it is a
source edit that shows up in a diff and in every output file's manifest — which
is the property a mix built from flags does not have.

------------------------------------------------------------------------------
THE KNEE IS DEFINED BEFORE THE RUN, IN THIS FILE
------------------------------------------------------------------------------
The knee is **the first ladder step whose p95 is SUSTAINED above 1000 ms**, and
"sustained" is not a feeling:

  * the step's window is cut into `WINDOWS` equal sub-windows;
  * sub-window 0 is discarded as warm-up (connections, caches, JIT of nothing
    in particular — the point is that it is discarded by rule, not by taste);
  * p95 is computed per remaining sub-window over DOOR samples only;
  * the step is `over` when EVERY remaining sub-window's p95 exceeds the
    threshold. One spike in one window is not a knee.

A sub-window holding fewer than `MIN_WINDOW_SAMPLES` samples cannot support a
p95 at all, so the step's verdict is `undetermined` — never `under`. A run whose
knee search hit an `undetermined` step BEFORE finding a knee reports the knee as
`undetermined` and exits 2. This is the instrument census's first question
(`docs/product/instruments.md`): could-not-look never reads as nothing-wrong.

------------------------------------------------------------------------------
WHAT THIS INSTRUMENT CANNOT SEE — declared here rather than discovered later
------------------------------------------------------------------------------
1. WHICH COMPONENT SATURATED, unless told. `run --utilization` joins the box's own
   samples (`deploy/load/utilization.sh`: host CPU, pg_stat_activity, Redis
   clients) to the knee step and writes them as the envelope line's fourth part;
   without that file the part says `not_sampled`. RDS, pool depth and worker
   backlog stay unread — the sampler's `does_not_cover` line names them.
2. THE SHA IS OPERATOR-DECLARED, NOT MEASURED. No door on this platform
   publishes the commit it is serving — `/healthz` answers `{"status": "ok"}`
   and `/readyz` answers organ booleans (`apps/core/health.py::healthz`, `::readyz`). So
   `--sha` is copied into the manifest verbatim as a CLAIM, labelled as one.
   What proves the box serves that sha is the deploy runbook's own proof set,
   not this script.
3. THE CLIENT'S PATH AND CPU. Latency here includes the path from wherever this
   runs to the box. A drive from a coffee shop measures the coffee shop. The
   manifest records the client host so two runs can be compared for it, and it
   does not correct for it. Off-box (`scripts/envelope.sh`), the client's CPU is
   the line's `client_cpu`, so a knee the client caused is a column, not a guess.
4. CLOSED LOOP, NO THINK TIME. Each worker issues its next request the instant
   the last one returns. That is the standard shape for finding a knee and it
   is NOT a model of real users; it overstates offered load per user and
   understates queue build-up under bursty arrival.
5. THE WRITE OPERATIONS LEAVE ROWS BEHIND. Measuring a write path means
   writing. Everything created carries `RUN_LABEL` in a field a human can see
   (`purpose` on documents, the recipient's email local part), and `run
   --archive-created` archives the documents it made. Messages and their
   deliveries are not withdrawable and are not withdrawn.
6. STORAGE LEGS ARE NOT DOOR LEGS. A file upload is three calls: mint a ticket
   (door), PUT the bytes at object storage (NOT ours), confirm (door). The PUT
   and the download GET are recorded with `door=false` and are EXCLUDED from
   every p95 the knee is computed on, because a slow S3 is not a slow platform.
   They are in the CSV so the exclusion is auditable rather than invisible.

------------------------------------------------------------------------------
FIXTURES, AND WHY `prepare` REFUSES RATHER THAN TRIMS
------------------------------------------------------------------------------
The mix names a recipient, a template and a pool of stored documents. `prepare`
builds them through the doors, idempotently, from `SEED` — same seed, same
names, so a second `prepare` adopts what the first made. If it cannot build the
whole set it exits 2 naming what is missing and the remedy. It never drops an
operation from the mix and runs the rest: a mix silently reduced to what the
environment happened to support is the anecdote this file exists not to
produce.

The commonest refusal is a document that never reaches `stored`, which means the confirm workflow
had no worker (`./scripts/worker.sh` on a laptop; the `worker` service on a box). That is an
environment fact and the message says so.
"""

from __future__ import annotations

import argparse
import ast
import csv
import glob
import http.client
import json
import math
import os
import platform
import random
import re
import socket
import ssl
import sys
import threading
import time
import urllib.parse
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# --- the constants a re-run has to match, all of them in one screen -----------

#: Every random choice this drive makes descends from here. Two runs with the
#: same seed, the same ladder and the same fixtures issue the same operations in
#: the same order per worker.
SEED = 20260825

#: How runs and the rows they leave behind are recognisable afterwards.
RUN_LABEL = "loadtest"

#: The knee threshold, in milliseconds. The cycle plan fixes it at 1s.
KNEE_P95_MS = 1000.0

#: Sub-windows per ladder step. Window 0 is warm-up and is discarded.
WINDOWS = 4

#: Below this many door samples a sub-window cannot support a p95, and the step
#: is `undetermined` rather than `under`.
MIN_WINDOW_SAMPLES = 20

#: The ladder. Stepped concurrency, doubling, so a knee is bracketed within a
#: factor of two by four steps rather than crawled up to.
LADDER: tuple[int, ...] = (1, 2, 4, 8, 16, 32, 64)

#: Seconds per ladder step. Long enough for four sub-windows to each hold more
#: than `MIN_WINDOW_SAMPLES` at the bottom of the ladder.
STEP_SECONDS = 60

#: The smoke ladder: enough to exercise every operation in the mix and prove the
#: script runs end to end, and far too little to support a knee. `smoke`
#: therefore reports `undetermined` by construction and says why.
SMOKE_LADDER: tuple[int, ...] = (1, 2)
SMOKE_STEP_SECONDS = 6

#: A throttled client waits as told (`Retry-After`), or this long when the answer names no wait.
THROTTLE_PAUSE_SECONDS = 1.0

#: Each credential is paced to this share of the `auth` throttle's rate, read from settings.
CREDENTIAL_PACE = 0.95

#: Per-request timeout. A request still running at this point is a failure with
#: `status=0`, not a very slow success.
TIMEOUT_SECONDS = 30.0

#: A soak is judged per window of this many seconds, and each window owes `MIN_WINDOW_SAMPLES`.
SOAK_WINDOW_SECONDS = 300.0

#: A soak whose last window's p95 exceeds this multiple of its first's is `drifting`.
SOAK_DRIFT_RATIO = 1.5

#: An envelope line above this error rate is marked INVALID for naming a knee (capacity.md § 1).
ENVELOPE_ERR_BOUND_PCT = 5.0

#: THE 2.5.0 BAR (load-acceptable plan § Rulings 1), every step up to it judged; never an exit.
BAR_CLIENTS = 8
BAR_P95_MS = 1000.0
BAR_ERR_PCT = 0.5

#: The bar is judged only on the shape it was declared for (N2339); any other line says why not.
BAR_TOPOLOGY = "web-box-organs-box-drive-off-box"
BAR_MIN_CREDENTIALS = 4

#: A ladder above one client under one credential measures the credential, never a knee (§ 1).
ONE_CREDENTIAL_MARK = "INVALID: one credential above one client"

#: The § 9 heading and end marker `judge --restamp` rewrites between; nothing else is touched.
RECORDED_HEAD = re.compile(r"^## \d+ · Recorded knees$")
RECORDED_END = "<!-- recorded-knees end -->"
RECORDED_LINE = re.compile(r"^(\s*- `)(metric=[^`]*)(`)$")

#: A soak window above this door error rate (a fraction) is not steady; `--err-bound` overrides.
SOAK_ERR_MAX = BAR_ERR_PCT / 100

#: Each organ database's connection bound, as `deploy/env.staging.example`'s arithmetic states it.
ORGAN_DB_BOUNDS: dict[str, int] = {"temporal": 16, "temporal_visibility": 8, "zitadel": 22}

#: The services whose declared pool sizes, times their processes, sum to a soak's `pg_total` budget.
POOL_SERVICES: tuple[str, ...] = ("web", "worker")

#: Where the pool sizes are declared; the soak reads them, never a copy.
SETTINGS_BASE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "config", "settings", "base.py"
)

#: Where the relay is declared: a soak's outbox may grow by one `RECONCILE_BATCH` and no more.
EVENTS_ACTIVITIES = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "apps", "events", "activities.py"
)

#: How many documents `prepare` stores for the download operation to draw from.
DOWNLOAD_POOL = 5

#: The bytes an upload uploads. Small on purpose: this drive is measuring the
#: doors under concurrency, not the network's throughput to object storage.
UPLOAD_BYTES = 4096

#: The search terms, fixed. Whether they match is not the measurement — the
#: round trip through the engine is — but they are drawn from what `prepare`
#: files so that the common case is a query with hits rather than an empty one.
SEARCH_TERMS: tuple[str, ...] = (
    RUN_LABEL,
    "invoice",
    "contract",
    "statement",
    "report",
    "zzqx",  # deliberately matches nothing: the empty-result path is a path
)


#: The CA bundle every HTTPS connection verifies against; `main` sets it once.
CA_BUNDLE: list[str | None] = [None]

#: `--resolve NAME:ADDRESS`, as a map; `main` fills it once.
RESOLVE: dict[str, str] = {}


# --- the wire ----------------------------------------------------------------


@dataclass(frozen=True)
class Reply:
    """One HTTP round trip, as measured."""

    status: int  # 0 means the request never produced a status
    body: bytes
    ms: float
    error: str = ""
    retry_after: float = 0.0

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self) -> dict:
        return json.loads(self.body.decode("utf-8"))


class Pacer:
    """One credential's door calls, spaced so the credential stays under its throttle's rate."""

    def __init__(self, per_second: float) -> None:
        self.interval = 1.0 / per_second
        self.next = 0.0
        self.lock = threading.Lock()

    def wait(self) -> None:
        with self.lock:
            now = time.perf_counter()
            at = max(now, self.next)
            self.next = at + self.interval
        if at > now:
            time.sleep(at - now)


#: The pacers by token, and the rate each paces to; `main` sets the rate once.
PACERS: dict[str, Pacer] = {}
PACE_PER_SECOND: list[float] = [0.0]
_PACERS_LOCK = threading.Lock()


def pacer_for(token: str) -> Pacer | None:
    if not PACE_PER_SECOND[0]:
        return None
    with _PACERS_LOCK:
        return PACERS.setdefault(token, Pacer(PACE_PER_SECOND[0]))


def declared_auth_rate(base_py: str | os.PathLike[str]) -> float:
    """The `auth` throttle's default rate in calls per second, read out of the settings source."""
    text = open(base_py, encoding="utf-8").read()
    found = re.search(
        r'"auth": env\.str\("THROTTLE_AUTH_RATE", default="(\d+)/(sec|min|hour)"\)', text
    )
    if not found:
        _die(f"could not find the auth throttle's default rate in {base_py}")
    assert found is not None  # noqa: S101 — narrows Optional for mypy; a None is a bug, not input
    per = {"sec": 1.0, "min": 60.0, "hour": 3600.0}[found.group(2)]
    return int(found.group(1)) / per


def _dial(address: str) -> Callable[..., socket.socket]:
    """A `create_connection` dialling `address`; TLS and `Host` keep the connection's name."""

    def create(where: tuple[str, int], *args: Any, **kwargs: Any) -> socket.socket:
        return socket.create_connection((address, where[1]), *args, **kwargs)

    return create


class Pool:
    """One worker's persistent connections, one per origin.

    A load driver that opens a fresh TCP+TLS connection per request measures the
    handshake as much as the door — over HTTPS that is most of a small request's
    latency, and it is not what a knee search is looking for. Real clients keep
    connections; so does this. A connection that errors is closed and dropped,
    so the next call reconnects rather than reusing a socket in an unknown
    state.
    """

    def __init__(self, timeout: float) -> None:
        self._timeout = timeout
        self._cafile = CA_BUNDLE[0]
        self._conns: dict[tuple[str, str, int], http.client.HTTPConnection] = {}

    def _origin(self, url: str) -> tuple[tuple[str, str, int], str]:
        parts = urllib.parse.urlsplit(url)
        scheme = parts.scheme or "http"
        host = parts.hostname or "localhost"
        port = parts.port or (443 if scheme == "https" else 80)
        path = parts.path or "/"
        if parts.query:
            path = f"{path}?{parts.query}"
        return (scheme, host, port), path

    def _conn(self, key: tuple[str, str, int]) -> http.client.HTTPConnection:
        conn = self._conns.get(key)
        if conn is None:
            scheme, host, port = key
            if scheme == "https":
                conn = http.client.HTTPSConnection(
                    host,
                    port,
                    timeout=self._timeout,
                    context=ssl.create_default_context(cafile=self._cafile),
                )
            else:
                conn = http.client.HTTPConnection(host, port, timeout=self._timeout)
            if host in RESOLVE:
                conn._create_connection = _dial(RESOLVE[host])  # type: ignore[attr-defined]
            self._conns[key] = conn
        return conn

    def drop(self, key: tuple[str, str, int]) -> None:
        conn = self._conns.pop(key, None)
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass

    def close(self) -> None:
        for key in list(self._conns):
            self.drop(key)

    def call(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> Reply:
        key, path = self._origin(url)
        started = time.perf_counter()
        try:
            conn = self._conn(key)
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            payload = response.read()
            wait = response.getheader("Retry-After") or ""
            return Reply(
                response.status,
                payload,
                (time.perf_counter() - started) * 1000.0,
                retry_after=float(wait) if wait.replace(".", "", 1).isdigit() else 0.0,
            )
        except (OSError, http.client.HTTPException) as exc:  # TimeoutError is an OSError
            self.drop(key)
            return Reply(
                0, b"", (time.perf_counter() - started) * 1000.0, f"{type(exc).__name__}: {exc}"
            )


class Doors:
    """The platform's REST door, with this drive's identity on every call."""

    def __init__(self, base_url: str, token: str, tenant: str, org: str, pool: Pool) -> None:
        self.base = base_url.rstrip("/")
        self.pool = pool
        self.identity = Credential(tenant=tenant, token=token, org=org)
        self.told_to_wait = 0.0
        self._auth = {
            "Authorization": f"Bearer {token}",
            "X-Tenant": tenant,
            "Accept": "application/json",
        }
        if org:
            self._auth["X-Org"] = org

    def api(
        self, method: str, path: str, *, payload: object | None = None, params: dict | None = None
    ) -> Reply:
        url = f"{self.base}/api/v1{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
        headers = dict(self._auth)
        body: bytes | None = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        pacer = pacer_for(self.identity.token)
        if pacer is not None:
            pacer.wait()
        reply = self.pool.call(method, url, headers=headers, body=body)
        if reply.status == 429:
            self.told_to_wait = max(self.told_to_wait, reply.retry_after or THROTTLE_PAUSE_SECONDS)
        return reply

    def storage_put(self, url: str, content_type: str, blob: bytes) -> Reply:
        headers = {
            "Content-Type": content_type,
            "If-None-Match": "*",
            "Content-Length": str(len(blob)),
        }
        return self.pool.call("PUT", url, headers=headers, body=blob)

    def storage_get(self, url: str) -> Reply:
        return self.pool.call("GET", url)


# --- what the drive measures --------------------------------------------------


@dataclass(frozen=True)
class Sample:
    """One measured call. `door` is what the knee is allowed to see."""

    op: str
    leg: str
    door: bool
    status: int
    ms: float
    at: float  # seconds since this ladder step began
    error: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def throttled(self) -> bool:
        """A 429 is the platform's own back-off: neither an error nor a door sample."""
        return self.status == 429


@dataclass(frozen=True)
class Fixtures:
    """What `prepare` built, and what `run` reads back out of the manifest."""

    tenant: str
    org: str
    recipient_id: str
    template: str
    file_ids: tuple[str, ...]

    def as_json(self) -> dict:
        return {
            "tenant": self.tenant,
            "org": self.org,
            "recipient_id": self.recipient_id,
            "template": self.template,
            "file_ids": list(self.file_ids),
        }

    @staticmethod
    def from_json(raw: dict) -> Fixtures:
        return Fixtures(
            tenant=str(raw["tenant"]),
            org=str(raw.get("org", "")),
            recipient_id=str(raw["recipient_id"]),
            template=str(raw["template"]),
            file_ids=tuple(str(x) for x in raw["file_ids"]),
        )


@dataclass(frozen=True)
class Credential:
    """One client's identity: the bearer it carries and the tenant it sends."""

    tenant: str
    token: str
    org: str = ""


@dataclass
class Created:
    """Documents this run filed, with who filed them, so `--archive-created` can put them away."""

    file_ids: list[tuple[str, Credential]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, file_id: str, by: Credential) -> None:
        with self.lock:
            self.file_ids.append((file_id, by))


# --- the operations -----------------------------------------------------------


def op_usage_report(d: Doors, rng: random.Random, fx: Fixtures, made: Created) -> list[Sample]:
    """A tenant asking what it has consumed this month."""
    period = rng.choice(("month", "day"))
    r = d.api("GET", "/usage/", params={"period": period})
    return [Sample("usage.report", "GET /usage/", True, r.status, r.ms, 0.0, r.error)]


def op_usage_meters(d: Doors, rng: random.Random, fx: Fixtures, made: Created) -> list[Sample]:
    """The meter vocabulary — a small, cacheable, very common read."""
    r = d.api("GET", "/meters/", params={"limit": 50})
    return [Sample("usage.meters", "GET /meters/", True, r.status, r.ms, 0.0, r.error)]


def op_search_query(d: Doors, rng: random.Random, fx: Fixtures, made: Created) -> list[Sample]:
    """A search across every registered kind — the engine leg."""
    term = rng.choice(SEARCH_TERMS)
    r = d.api("GET", "/search/", params={"q": term, "limit": 20})
    return [Sample("search.query", "GET /search/", True, r.status, r.ms, 0.0, r.error)]


def op_files_list(d: Doors, rng: random.Random, fx: Fixtures, made: Created) -> list[Sample]:
    """The document working set, paged — the commonest list in the product."""
    r = d.api("GET", "/files/", params={"limit": 50})
    return [Sample("files.list", "GET /files/", True, r.status, r.ms, 0.0, r.error)]


def op_files_upload(d: Doors, rng: random.Random, fx: Fixtures, made: Created) -> list[Sample]:
    """File a document: mint a ticket (door), PUT the bytes (NOT ours), confirm (door)."""
    name = f"{RUN_LABEL}-{uuid.UUID(int=rng.getrandbits(128), version=4)}.bin"
    payload = {
        "filename": name,
        "content_type": "application/octet-stream",
        "size_bytes": UPLOAD_BYTES,
        "purpose": RUN_LABEL,
    }
    ticket = d.api("POST", "/files/", payload=payload)
    out = [
        Sample("files.upload", "POST /files/", True, ticket.status, ticket.ms, 0.0, ticket.error)
    ]
    if not ticket.ok:
        return out
    body = ticket.json()
    file_id = str(body["file"]["id"])
    version = int(body["version"]["version"])
    made.add(file_id, d.identity)

    blob = bytes(rng.getrandbits(8) for _ in range(64)) * (UPLOAD_BYTES // 64)
    put = d.storage_put(str(body["upload_url"]), "application/octet-stream", blob)
    out.append(Sample("files.upload", "PUT <storage>", False, put.status, put.ms, 0.0, put.error))
    if not put.ok:
        return out

    confirm = d.api(
        "POST",
        f"/files/{file_id}/versions/{version}/confirm/",
        payload={"idempotency_key": f"{RUN_LABEL}-{file_id}-{version}"},
    )
    out.append(
        Sample(
            "files.upload",
            "POST /files/{id}/versions/{n}/confirm/",
            True,
            confirm.status,
            confirm.ms,
            0.0,
            confirm.error,
        )
    )
    return out


def op_files_download(d: Doors, rng: random.Random, fx: Fixtures, made: Created) -> list[Sample]:
    """Read a document: issue a link (door), then fetch the bytes (NOT ours)."""
    file_id = rng.choice(fx.file_ids)
    issued = d.api("POST", f"/files/{file_id}/download-url/", payload={})
    out = [
        Sample(
            "files.download",
            "POST /files/{id}/download-url/",
            True,
            issued.status,
            issued.ms,
            0.0,
            issued.error,
        )
    ]
    if not issued.ok:
        return out
    got = d.storage_get(str(issued.json()["download_url"]))
    out.append(Sample("files.download", "GET <storage>", False, got.status, got.ms, 0.0, got.error))
    return out


def op_comms_send(d: Doors, rng: random.Random, fx: Fixtures, made: Created) -> list[Sample]:
    """Send one transactional message to the fixture recipient."""
    payload = {
        "recipient_id": fx.recipient_id,
        "template": fx.template,
        "channel": "email",
        "context": {"run": RUN_LABEL, "n": rng.randrange(1_000_000)},
    }
    r = d.api("POST", "/messages/", payload=payload)
    return [Sample("comms.send", "POST /messages/", True, r.status, r.ms, 0.0, r.error)]


@dataclass(frozen=True)
class Operation:
    name: str
    weight: int
    kind: str
    run: Callable[[Doors, random.Random, Fixtures, Created], list[Sample]]
    describes: str


#: THE MIX. Weight by weight, kind by kind. 9 read : 3 write.
MIX: tuple[Operation, ...] = (
    Operation("usage.report", 3, "read", op_usage_report, "this month's consumption"),
    Operation("usage.meters", 1, "read", op_usage_meters, "the meter vocabulary"),
    Operation("search.query", 3, "read", op_search_query, "a query across every kind"),
    Operation("files.list", 2, "read", op_files_list, "the document working set"),
    Operation("files.upload", 1, "write", op_files_upload, "ticket + storage PUT + confirm"),
    Operation("files.download", 1, "read", op_files_download, "link issue + storage GET"),
    Operation("comms.send", 1, "write", op_comms_send, "one transactional message"),
)


def kind_of(op: str) -> str:
    """An operation's declared kind by its name; `unknown` for a name outside the mix."""
    return next((o.kind for o in MIX if o.name == op), "unknown")


_READ_WEIGHT = sum(o.weight for o in MIX if o.kind == "read")
_WRITE_WEIGHT = sum(o.weight for o in MIX if o.kind == "write")


def mix_manifest() -> dict:
    return {
        "read_weight": _READ_WEIGHT,
        "write_weight": _WRITE_WEIGHT,
        "operations": [
            {"name": o.name, "weight": o.weight, "kind": o.kind, "describes": o.describes}
            for o in MIX
        ],
    }


# --- statistics ---------------------------------------------------------------


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile. No interpolation, so a p95 is always a sample."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


@dataclass
class StepResult:
    index: int
    concurrency: int
    seconds: float
    samples: list[Sample]

    #: Exceptions raised by the DRIVER itself, not answers from the platform.
    faults: list[str] = field(default_factory=list)

    #: Wall-clock seconds at the step's origin, so the box's samples can be joined to it.
    started_epoch: float = 0.0

    # filled by `judge`
    verdict: str = "undetermined"  # under | over | undetermined | driver_fault
    reason: str = ""
    window_p95: list[float] = field(default_factory=list)
    window_counts: list[int] = field(default_factory=list)

    @property
    def door_samples(self) -> list[Sample]:
        return [s for s in self.samples if s.door and not s.throttled]

    @property
    def throttled(self) -> int:
        return sum(1 for s in self.samples if s.throttled)

    def judge(self) -> None:
        """Apply the sustained-p95 definition declared at the top of this file."""
        if self.faults:
            # Outranks every other verdict, including `over`: a step some of whose
            # operations never ran did not measure the declared mix, so its p95
            # is a number about a different experiment.
            self.verdict = "driver_fault"
            distinct = sorted(set(self.faults))
            self.reason = (
                f"the driver itself raised {len(self.faults)} time(s) "
                f"({len(distinct)} distinct); this step did not measure the "
                f"declared mix. First: {distinct[0]}"
            )
            return
        door = self.door_samples
        width = self.seconds / WINDOWS
        self.window_p95 = []
        self.window_counts = []
        for w in range(1, WINDOWS):  # window 0 is warm-up, discarded by rule
            lo, hi = w * width, (w + 1) * width
            in_window = [s.ms for s in door if lo <= s.at < hi]
            self.window_counts.append(len(in_window))
            self.window_p95.append(percentile(in_window, 0.95))
        thin = [n for n in self.window_counts if n < MIN_WINDOW_SAMPLES]
        if thin:
            self.verdict = "undetermined"
            self.reason = (
                f"a measured sub-window held {min(self.window_counts)} door samples, "
                f"below MIN_WINDOW_SAMPLES={MIN_WINDOW_SAMPLES}; no p95 can be supported"
            )
            return
        if all(p > KNEE_P95_MS for p in self.window_p95):
            self.verdict = "over"
            self.reason = f"every measured sub-window p95 exceeded {KNEE_P95_MS:.0f} ms"
        else:
            self.verdict = "under"
            self.reason = f"at least one sub-window p95 was at or below {KNEE_P95_MS:.0f} ms"

    def summary(self) -> dict:
        door = [s.ms for s in self.door_samples]
        reads = [s.ms for s in self.door_samples if kind_of(s.op) == "read"]
        writes = [s.ms for s in self.door_samples if kind_of(s.op) == "write"]
        errors = [s for s in self.samples if not s.ok and not s.throttled]
        door_errors = [s for s in self.door_samples if not s.ok]
        return {
            "step": self.index,
            "concurrency": self.concurrency,
            "seconds": round(self.seconds, 3),
            "requests_total": len(self.samples),
            "requests_door": len(door),
            "errors_total": len(errors),
            "errors_door": len(door_errors),
            "throttled": self.throttled,
            "error_rate_door": round(len(door_errors) / len(door), 6) if door else None,
            "door_rps": round(len(door) / self.seconds, 3) if self.seconds else None,
            "p50_ms": round(percentile(door, 0.50), 2) if door else None,
            "p90_ms": round(percentile(door, 0.90), 2) if door else None,
            "p95_ms": round(percentile(door, 0.95), 2) if door else None,
            "p95_read_ms": round(percentile(reads, 0.95), 2) if reads else None,
            "p95_write_ms": round(percentile(writes, 0.95), 2) if writes else None,
            "p99_ms": round(percentile(door, 0.99), 2) if door else None,
            "max_ms": round(max(door), 2) if door else None,
            "window_p95_ms": [None if math.isnan(p) else round(p, 2) for p in self.window_p95],
            "window_door_samples": self.window_counts,
            "driver_faults": len(self.faults),
            "started_epoch": self.started_epoch,
            "verdict": self.verdict,
            "reason": self.reason,
        }

    def by_operation(self) -> list[dict]:
        rows: list[dict] = []
        legs = sorted({(s.op, s.leg, s.door) for s in self.samples})
        for op, leg, door in legs:
            these = [s for s in self.samples if s.op == op and s.leg == leg]
            ms = [s.ms for s in these]
            statuses: dict[int, int] = {}
            for s in these:
                statuses[s.status] = statuses.get(s.status, 0) + 1
            rows.append(
                {
                    "step": self.index,
                    "concurrency": self.concurrency,
                    "op": op,
                    "leg": leg,
                    "door": door,
                    "requests": len(these),
                    "errors": sum(1 for s in these if not s.ok and not s.throttled),
                    "throttled": sum(1 for s in these if s.throttled),
                    "p50_ms": round(percentile(ms, 0.50), 2),
                    "p95_ms": round(percentile(ms, 0.95), 2),
                    "p99_ms": round(percentile(ms, 0.99), 2),
                    "max_ms": round(max(ms), 2),
                    "statuses": json.dumps(dict(sorted(statuses.items()))),
                }
            )
        return rows


# --- the box's samples, the envelope line, the soak ----------------------------


def read_utilization(path: str) -> list[dict[str, Any]]:
    """The sampler's JSON lines, each with a `ts`; an unreadable line is could-not-look."""
    rows: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                if not raw.strip():
                    continue
                row = json.loads(raw)
                float(row["ts"])
                rows.append(row)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        _die(
            f"could not read the utilization samples in {path}",
            f"{type(exc).__name__}: {exc}",
            "The utilization part is read from the box, never inferred; re-sample and re-run.",
        )
    return rows


def read_utilization_files(paths: Sequence[str]) -> list[dict[str, Any]]:
    """Every box's sampler lines, in the order the files were named."""
    return [row for path in paths for row in read_utilization(path)]


#: The CPU columns a line carries, by the box each sampler ran on.
CPU_KEYS: tuple[str, ...] = ("host_cpu", "organs_cpu", "client_cpu")


def _knee_step(steps: Sequence[dict[str, Any]], knee: dict[str, Any]) -> dict[str, Any]:
    """The step summary a knee names, or the last step a ladder reached."""
    index = knee.get("step")
    if isinstance(index, int) and 0 <= index < len(steps):
        return steps[index]
    return steps[-1]


def utilization_part(
    steps: Sequence[dict[str, Any]], knee: dict[str, Any], util: Sequence[dict[str, Any]]
) -> tuple[str, bool]:
    """The envelope line's fourth part at the knee step, and whether the boxes were seen there."""
    step = _knee_step(steps, knee)
    lo = float(step["started_epoch"])
    hi = lo + float(step["seconds"])
    inside = [u for u in util if lo <= float(u["ts"]) < hi]
    if not inside:
        return f"undetermined(no utilization sample inside step {step['step']}'s window)", False
    fields: list[str] = []
    for key in CPU_KEYS:
        seen = [float(u[key]) for u in inside if key in u]
        if seen:
            fields.append(f"{key}={percentile(seen, 0.95):.1f}")
        elif key != "organs_cpu":
            fields.append(f"{key}=not_sampled")
    pg = [u for u in inside if "pg_total" in u]
    if pg:
        fields.append(f"pg_total={max(int(u['pg_total']) for u in pg)}")
        fields.append(f"pg_active={max(int(u['pg_active']) for u in pg)}")
    idle_tx = [int(u["idle_in_tx"]) for u in inside if u.get("idle_in_tx") is not None]
    if idle_tx:
        fields.append(f"idle_in_tx={max(idle_tx)}")
    return ",".join(fields), True


def _clean(value: str) -> str:
    return value.replace(",", "-").replace("|", "-").replace(" ", "-") or "unstated"


def _ms(value: float | None) -> str:
    return "none" if value is None else f"{value:.0f}"


def bar_unjudged(*, topology: str, credentials: int) -> str:
    """Why a line's shape cannot judge the bar, or `""` on the shape the bar was declared for."""
    why = []
    if topology != BAR_TOPOLOGY:
        why.append(f"topology={_clean(topology)} is not {BAR_TOPOLOGY}")
    if credentials < BAR_MIN_CREDENTIALS:
        why.append(f"credentials={credentials} is below {BAR_MIN_CREDENTIALS}")
    return "; ".join(why)


def judge_bar(steps: Sequence[dict[str, Any]], *, topology: str, credentials: int) -> str:
    """`met`, `unmet(<the bar, the step, the value>)` up to `BAR_CLIENTS`, or `unjudged(<why>)`."""
    why = bar_unjudged(topology=topology, credentials=credentials)
    if why:
        return f"unjudged({why})"
    upto = [s for s in steps if int(s["concurrency"]) <= BAR_CLIENTS]
    for s in upto:
        conc = s["concurrency"]
        if s["verdict"] in ("undetermined", "driver_fault"):
            return f"unmet({s['verdict']} at conc-{conc})"
        p95 = s["p95_ms"]
        if p95 is None or p95 >= BAR_P95_MS:
            return f"unmet(p95_ms={_ms(p95)} at conc-{conc}; the bar is < {BAR_P95_MS:.0f})"
        err = round((s["error_rate_door"] or 0.0) * 100, 2)
        if err >= BAR_ERR_PCT:
            return f"unmet(err={err} at conc-{conc}; the bar is < {BAR_ERR_PCT:g}%)"
    if not any(int(s["concurrency"]) == BAR_CLIENTS for s in upto):
        last = steps[-1]["concurrency"] if steps else 0
        return f"unmet(conc-{BAR_CLIENTS} never ran; the ladder stopped at conc-{last})"
    return "met"


def _pacer_word(pace: float) -> str:
    return f"{pace:g}/s" if pace else "off"


def paced_instrument(instrument: str, pacer: str) -> str:
    """The instrument naming its pacer, so two pacings never share one string (capacity.md § 1)."""
    return instrument if " pacer=" in instrument else f"{instrument} pacer={pacer}"


def one_credential_loop(*, credentials: int, concurrency: int) -> bool:
    """A ladder above one client under one credential: capacity.md § 1's loop, never a knee."""
    return credentials == 1 and concurrency > 1


def envelope_line(
    *,
    steps: Sequence[dict[str, Any]],
    knee: dict[str, Any],
    utilization: str,
    instrument: str,
    size: str,
    scale: str,
    topology: str,
    client: str = "",
    credentials: Sequence[Credential] = (),
    pace: float = 0.0,
) -> str:
    """The four-part line `docs/runbooks/capacity.md` § 1 defines at the knee step, and the bar."""
    summary = _knee_step(steps, knee)
    concurrency = summary["concurrency"]
    rate = summary["error_rate_door"] or 0.0
    err_pct = round(rate * 100, 2)
    p95 = summary["p95_ms"] or 0.0
    found = knee.get("verdict") == "found"
    claim = f"knee=conc-{concurrency}" if found else f"knee={knee.get('verdict', 'none')}"
    tenants = len({c.tenant for c in credentials})
    conditions = (
        f"size={_clean(size)},scale={_clean(scale)},concurrency={concurrency},"
        f"err={err_pct},throttled={summary['throttled']},pacer={_pacer_word(pace)},"
        f"topology={_clean(topology)},"
        f"client={_clean(client)},tenants={tenants},credentials={len(credentials)}"
    )
    line = (
        f"metric=p95_ms={p95:.0f} p95_read_ms={_ms(summary.get('p95_read_ms'))}"
        f" p95_write_ms={_ms(summary.get('p95_write_ms'))} {claim}"
        f" | instrument={paced_instrument(instrument, _pacer_word(pace))} | "
        f"conditions={conditions} | utilization={utilization}"
        f" | bar={judge_bar(steps, topology=topology, credentials=len(credentials))}"
    )
    if found and err_pct > ENVELOPE_ERR_BOUND_PCT:
        line += f" | validity=INVALID(err above {ENVELOPE_ERR_BOUND_PCT:g}%)"
    top = max(int(s["concurrency"]) for s in steps)
    if one_credential_loop(credentials=len(credentials), concurrency=top):
        line += f" | validity={ONE_CREDENTIAL_MARK}"
    return line


def restamp_line(line: str) -> str:
    """A recorded envelope line in the current form; one that names no `pacer=` is the old era."""
    fields = line.split(" | ")
    parts = dict(f.partition("=")[::2] for f in fields)
    conditions = dict(
        pair.split("=", 1) for pair in parts.get("conditions", "").split(",") if "=" in pair
    )
    pacer = conditions.get("pacer")
    if pacer is None or "instrument" not in parts:
        return line
    credentials = int(conditions.get("credentials", "0"))
    why = bar_unjudged(topology=conditions.get("topology", ""), credentials=credentials)
    out = []
    for f in fields:
        key, _, value = f.partition("=")
        if key == "instrument":
            f = f"instrument={paced_instrument(value, pacer)}"
        elif key == "bar" and why:
            f = f"bar=unjudged({why})"
        out.append(f)
    mark = f"validity={ONE_CREDENTIAL_MARK}"
    loop = one_credential_loop(credentials=credentials, concurrency=int(conditions["concurrency"]))
    if loop and mark not in out:
        out.append(mark)
    return " | ".join(out)


def restamp_recorded(text: str) -> tuple[str, list[str]]:
    """§ 9's recorded lines through `restamp_line`, and one report line per envelope line."""
    lines, report, inside = text.split("\n"), [], False
    for n, line in enumerate(lines):
        if RECORDED_HEAD.match(line):
            inside = True
        elif line == RECORDED_END:
            inside = False
        found = RECORDED_LINE.match(line) if inside else None
        if found is None:
            continue
        new = restamp_line(found.group(2))
        verdict = "restamped" if new != found.group(2) else "kept"
        report.append(f"{verdict} :{n + 1} {new.split(' | ', 1)[0]}")
        lines[n] = f"{found.group(1)}{new}{found.group(3)}"
    return "\n".join(lines), report


def judge_baseline(census: str, *, app_db: str, budget: int) -> tuple[bool, list[str]]:
    """capacity.md § 7's pre-spend gate over § 2a's census: every database at or under its bound."""
    bounds = {app_db: budget, **ORGAN_DB_BOUNDS}
    held: dict[str, int] = {}
    lines: list[str] = []
    for raw in census.splitlines():
        if not raw.strip():
            continue
        cells = raw.split("|")
        if len(cells) < 3 or not cells[2].strip().isdigit():
            return False, [
                f"could not look: the census row {raw!r} is not datname|usename|held|..."
            ]
        held[cells[0]] = held.get(cells[0], 0) + int(cells[2])
    ok = True
    for datname, count in sorted(held.items()):
        bound = bounds.get(datname)
        if bound is None:
            ok = False
            lines.append(
                f"{datname}: {count} held by a principal nothing declares — stop and report"
            )
        elif count > bound:
            ok = False
            lines.append(f"{datname}: {count} held, above its bound {bound}")
        else:
            lines.append(f"{datname}: {count} held, bound {bound}")
    return ok, lines


def declared_pool_budget(base_py: str | os.PathLike[str], processes: Mapping[str, int]) -> int:
    """`_POOL_MAX_SIZE_BY_SERVICE` × each service's process count, summed, read off the settings."""
    tree = ast.parse(open(base_py, encoding="utf-8").read())
    for node in ast.walk(tree):
        target: ast.expr | None = node.target if isinstance(node, ast.AnnAssign) else None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        value = getattr(node, "value", None)
        if isinstance(target, ast.Name) and target.id == "_POOL_MAX_SIZE_BY_SERVICE" and value:
            sizes = ast.literal_eval(value)
            missing = [name for name in processes if name not in sizes]
            if missing:
                _die(f"no declared pool size for {', '.join(missing)} in {base_py}")
            return sum(int(sizes[name]) * count for name, count in processes.items())
    _die(f"could not find _POOL_MAX_SIZE_BY_SERVICE in {base_py}")
    raise AssertionError("unreachable")


def compose_processes(rendered_json: str | os.PathLike[str]) -> dict[str, int]:
    """Each `POOL_SERVICES` name's process count off `docker compose config --format json`."""
    with open(rendered_json, encoding="utf-8") as fh:
        services = json.load(fh).get("services", {})
    missing = [name for name in POOL_SERVICES if name not in services]
    if missing:
        _die(f"the rendered compose in {rendered_json} has no {', '.join(missing)} service")
    return {
        name: int((services[name].get("deploy") or {}).get("replicas", 1)) for name in POOL_SERVICES
    }


def parse_processes(text: str) -> dict[str, int]:
    """`web=1,worker=2` as a mapping; anything else is refused."""
    found: dict[str, int] = {}
    for part in text.split(","):
        name, _, count = part.partition("=")
        if not name or not count.isdigit() or int(count) < 1:
            _die(f"--processes takes service=count pairs like web=1,worker=2, got '{text}'")
        found[name] = int(count)
    return found


def format_processes(processes: Mapping[str, int]) -> str:
    """The `--processes` spelling of a mapping, in its own order."""
    return ",".join(f"{name}={count}" for name, count in processes.items())


def declared_outbox_slack(activities_py: str | os.PathLike[str]) -> int:
    """`RECONCILE_BATCH`: the stranded rows one relay pass (every `RECONCILE_EVERY`) resumes."""
    tree = ast.parse(open(activities_py, encoding="utf-8").read())
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "RECONCILE_BATCH"
        ):
            return int(ast.literal_eval(node.value))
    _die(f"could not find RECONCILE_BATCH in {activities_py}")
    raise AssertionError("unreachable")


#: The soak table's CPU columns: the web box's and the organs box's, each window's (median, max).
SOAK_CPU_KEYS: tuple[str, ...] = ("host_cpu", "organs_cpu")


def _cpu_reading(inside: Sequence[dict[str, Any]], key: str) -> tuple[float, float] | None:
    """One box's CPU over a window as (nearest-rank median, max); `None` where unsampled."""
    seen = [float(u[key]) for u in inside if u.get(key) is not None]
    return (percentile(seen, 0.5), max(seen)) if seen else None


def _cpu_cell(reading: object) -> str:
    """A window's CPU reading as `<median>/<max>`, or `-` where nothing was read."""
    if not isinstance(reading, (tuple, list)):
        return "-"
    return f"{float(reading[0]):.1f}/{float(reading[1]):.1f}"


@dataclass
class SoakResult:
    verdict: str  # steady | drifting | unsteady | undetermined
    reasons: list[str]
    windows: list[dict[str, Any]]


def judge_soak(
    samples: Sequence[Sample],
    seconds: float,
    origin_epoch: float,
    util: Sequence[dict[str, Any]],
    *,
    budget: int,
    outbox_slack: int,
    err_bound: float = SOAK_ERR_MAX,
) -> SoakResult:
    """Judge a soak per `SOAK_WINDOW_SECONDS` window: err, p95, `pg_clients`, `outbox_pending`."""
    windows: list[dict[str, Any]] = []
    for w in range(int(seconds // SOAK_WINDOW_SECONDS)):
        lo, hi = w * SOAK_WINDOW_SECONDS, (w + 1) * SOAK_WINDOW_SECONDS
        these = [s for s in samples if lo <= s.at < hi]
        door = [s for s in these if s.door and not s.throttled]
        inside = [u for u in util if origin_epoch + lo <= float(u["ts"]) < origin_epoch + hi]
        pg = [int(u["pg_total"]) for u in inside if "pg_total" in u]
        clients = [u for u in inside if u.get("pg_clients") is not None]
        at_total = max(
            (u for u in clients if "pg_total" in u), key=lambda u: int(u["pg_total"]), default=None
        )
        at_clients = max(clients, key=lambda u: int(u["pg_clients"]), default=None)
        outbox = [int(u["outbox_pending"]) for u in inside if u.get("outbox_pending") is not None]
        backlog = [int(u["worker_backlog"]) for u in inside if u.get("worker_backlog") is not None]
        idle_tx = [int(u["idle_in_tx"]) for u in inside if u.get("idle_in_tx") is not None]
        windows.append(
            {
                "window": w,
                "door_samples": len(door),
                "err": round(sum(1 for s in door if not s.ok) / len(door), 6) if door else None,
                "p95_ms": round(percentile([s.ms for s in door], 0.95), 2) if door else None,
                "throttled": sum(1 for s in these if s.throttled),
                "pg_total": max(pg) if pg else None,
                "pg_clients": int(at_clients["pg_clients"]) if at_clients else None,
                "pg_other": (
                    str(at_total.get("pg_other", ""))
                    if at_total
                    and at_clients
                    and int(at_total["pg_total"]) != int(at_clients["pg_clients"])
                    else None
                ),
                "pg_by_app": str(at_clients.get("pg_by_app", "")) if at_clients else None,
                "outbox_pending": max(outbox) if outbox else None,
                "worker_backlog": max(backlog) if backlog else None,
                "idle_in_tx": max(idle_tx) if idle_tx else None,
                **{key: _cpu_reading(inside, key) for key in SOAK_CPU_KEYS},
            }
        )
    if not windows:
        return SoakResult("undetermined", ["the soak held no whole window"], windows)
    thin = [w["window"] for w in windows if w["door_samples"] < MIN_WINDOW_SAMPLES]
    if thin:
        reason = f"window(s) {thin} held fewer than MIN_WINDOW_SAMPLES={MIN_WINDOW_SAMPLES}"
        return SoakResult("undetermined", [reason], windows)
    unseen = [w["window"] for w in windows if w["pg_clients"] is None]
    if unseen:
        reason = (
            f"window(s) {unseen} hold no pg_clients sample — pg_clients is read, never inferred"
        )
        return SoakResult("undetermined", [reason], windows)
    no_outbox = [w["window"] for w in windows if w["outbox_pending"] is None]
    if no_outbox:
        reason = f"window(s) {no_outbox} hold no outbox_pending sample — read, never inferred"
        return SoakResult("undetermined", [reason], windows)
    breaches = [
        f"err: window {w['window']}: err={w['err']:.2%} above {err_bound:.2%}"
        for w in windows
        if w["err"] > err_bound
    ] + [
        f"pg_clients: window {w['window']}: pg_clients={w['pg_clients']} above the declared pool"
        f" budget {budget}"
        for w in windows
        if w["pg_clients"] > budget
    ]
    grew_from, grew_to = windows[0]["outbox_pending"], windows[-1]["outbox_pending"]
    if grew_to > grew_from + outbox_slack:
        breaches.append(
            f"outbox: outbox_pending grew {grew_from} -> {grew_to}, above one relay pass"
            f" (RECONCILE_BATCH={outbox_slack})"
        )
    first, last = windows[0]["p95_ms"], windows[-1]["p95_ms"]
    drift = (
        [f"last window p95 {last} ms is above {SOAK_DRIFT_RATIO}x the first's {first} ms"]
        if last > SOAK_DRIFT_RATIO * first
        else []
    )
    if breaches:
        return SoakResult("unsteady", breaches + drift, windows)
    if drift:
        return SoakResult("drifting", drift, windows)
    return SoakResult(
        "steady",
        ["every window held err, pg_clients and outbox_pending inside their bounds"],
        windows,
    )


# --- driving ------------------------------------------------------------------


def _pick(rng: random.Random) -> Operation:
    total = sum(o.weight for o in MIX)
    draw = rng.randrange(total)
    for op in MIX:
        draw -= op.weight
        if draw < 0:
            return op
    return MIX[-1]


def _worker(
    worker_id: int,
    step_index: int,
    args: argparse.Namespace,
    cred: Credential,
    fx: Fixtures,
    made: Created,
    deadline: float,
    origin: float,
    out: list[Sample],
    faults: list[str],
    lock: threading.Lock,
) -> None:
    # The seed is a pure function of (SEED, step, worker): a re-run of one step
    # issues the same operations in the same order per worker.
    rng = random.Random((SEED, step_index, worker_id).__hash__() ^ SEED)  # noqa: S311 — a seeded load schedule, reproducible by design; not crypto
    pool = Pool(TIMEOUT_SECONDS)
    doors = Doors(args.base_url, cred.token, cred.tenant, cred.org or fx.org, pool)
    local: list[Sample] = []
    mine: list[str] = []
    try:
        while time.perf_counter() < deadline:
            op = _pick(rng)
            at = time.perf_counter() - origin
            # A DRIVER fault is not a slow platform and must never be reported as
            # one. Before this existed, an operation raising (a response field
            # this script had guessed wrong, found on the very first smoke) killed
            # the worker thread, printed a traceback that scrolled past, and left
            # the step reporting `undetermined — too few samples`: the driver's
            # own bug wearing the instrument's could-not-look. Faults are now
            # caught, counted and named, and any fault makes the step LOUD.
            try:
                produced = op.run(doors, rng, fx, made)
            except Exception as exc:  # noqa: BLE001 — the driver's own faults, named
                mine.append(f"{op.name}: {type(exc).__name__}: {exc}")
                continue
            if doors.told_to_wait:
                time.sleep(max(0.0, min(doors.told_to_wait, deadline - time.perf_counter())))
                doors.told_to_wait = 0.0
            for sample in produced:
                local.append(
                    Sample(
                        sample.op,
                        sample.leg,
                        sample.door,
                        sample.status,
                        sample.ms,
                        at,
                        sample.error,
                    )
                )
    finally:
        pool.close()
        with lock:
            out.extend(local)
            faults.extend(mine)


def run_step(
    index: int,
    concurrency: int,
    seconds: float,
    args: argparse.Namespace,
    creds: Sequence[Credential],
    fixtures: dict[str, Fixtures],
    made: Created,
) -> StepResult:
    """`concurrency` closed-loop clients for `seconds`; client `w` carries `creds[w % N]`."""
    samples: list[Sample] = []
    faults: list[str] = []
    lock = threading.Lock()
    origin = time.perf_counter()
    started_epoch = time.time()
    deadline = origin + seconds
    threads = [
        threading.Thread(
            target=_worker,
            args=(
                w,
                index,
                args,
                creds[w % len(creds)],
                fixtures[creds[w % len(creds)].tenant],
                made,
                deadline,
                origin,
                samples,
                faults,
                lock,
            ),
            name=f"drive-s{index}-w{w}",
            daemon=True,
        )
        for w in range(concurrency)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=seconds + TIMEOUT_SECONDS + 30)
    elapsed = time.perf_counter() - origin
    step = StepResult(
        index, concurrency, elapsed, samples, faults=faults, started_epoch=started_epoch
    )
    step.judge()
    return step


# --- preparing ----------------------------------------------------------------


def _die(message: str, *lines: str) -> None:
    print(f"!! drive: {message}", file=sys.stderr)
    for line in lines:
        print(f"   {line}", file=sys.stderr)
    raise SystemExit(2)


def _expect(reply: Reply, what: str) -> dict:
    if not reply.ok:
        body = reply.body.decode("utf-8", "replace")[:400]
        _die(
            f"could not {what} (status {reply.status})",
            reply.error or body,
            "Nothing was prepared. Fix the environment and re-run `prepare`.",
        )
    return reply.json()


def prepare(args: argparse.Namespace, cred: Credential) -> Fixtures:
    pool = Pool(TIMEOUT_SECONDS)
    doors = Doors(args.base_url, cred.token, cred.tenant, cred.org, pool)
    rng = random.Random(SEED)  # noqa: S311 — a seeded load schedule, reproducible by design; not crypto
    try:
        template = f"{RUN_LABEL}-notice"
        found = doors.api("GET", f"/templates/{template}/")
        if found.status == 404:
            _expect(
                doors.api(
                    "POST",
                    "/templates/",
                    payload={
                        "name": template,
                        "subject": f"{RUN_LABEL} notice",
                        "body": "Load drive notice for {{ run }}, sequence {{ n }}.",
                        "channel": "email",
                        "category": "transactional",
                    },
                ),
                f"create the template {template!r}",
            )
            print(f"   template   {template} created")
        elif found.ok:
            print(f"   template   {template} adopted")
        else:
            _expect(found, f"read the template {template!r}")

        email = f"{RUN_LABEL}+drive@example.invalid"
        listed = _expect(
            doors.api("GET", "/recipients/", params={"email": email, "limit": 1}),
            "list recipients",
        )
        items = listed["items"] if isinstance(listed, dict) else listed
        if items:
            recipient_id = str(items[0]["id"])
            print(f"   recipient  {email} adopted")
        else:
            made_r = _expect(
                doors.api(
                    "POST",
                    "/recipients/",
                    payload={"email": email, "display_name": "Load drive"},
                ),
                f"create the recipient {email!r}",
            )
            recipient_id = str(made_r["id"])
            print(f"   recipient  {email} created")

        file_ids = _prepare_files(doors, rng, args)
        print(f"   documents  {len(file_ids)} stored and readable")
        return Fixtures(cred.tenant, cred.org, recipient_id, template, tuple(file_ids))
    finally:
        pool.close()


def _prepare_files(doors: Doors, rng: random.Random, args: argparse.Namespace) -> list[str]:
    """Store `DOWNLOAD_POOL` documents, and REFUSE if any never reaches `stored`."""
    existing = _expect(
        doors.api("GET", "/files/", params={"purpose": RUN_LABEL, "limit": DOWNLOAD_POOL}),
        "list documents",
    )
    items = existing["items"] if isinstance(existing, dict) else existing
    ready = [str(i["id"]) for i in items if int(i.get("current_version", 0)) > 0]
    if len(ready) >= DOWNLOAD_POOL:
        return ready[:DOWNLOAD_POOL]

    pending: list[tuple[str, int]] = []
    for n in range(DOWNLOAD_POOL - len(ready)):
        ticket = _expect(
            doors.api(
                "POST",
                "/files/",
                payload={
                    "filename": f"{RUN_LABEL}-pool-{n}.bin",
                    "content_type": "application/octet-stream",
                    "size_bytes": UPLOAD_BYTES,
                    "purpose": RUN_LABEL,
                },
            ),
            "file a pool document",
        )
        file_id = str(ticket["file"]["id"])
        version = int(ticket["version"]["version"])
        blob = bytes(rng.getrandbits(8) for _ in range(64)) * (UPLOAD_BYTES // 64)
        put = doors.storage_put(str(ticket["upload_url"]), "application/octet-stream", blob)
        if not put.ok:
            _die(
                f"object storage refused the pool upload (status {put.status})",
                put.error or put.body.decode("utf-8", "replace")[:400],
                "The presigned PUT is signed for Content-Type and If-None-Match: *.",
            )
        _expect(
            doors.api(
                "POST",
                f"/files/{file_id}/versions/{version}/confirm/",
                payload={"idempotency_key": f"{RUN_LABEL}-pool-{file_id}-{version}"},
            ),
            "confirm a pool upload",
        )
        pending.append((file_id, version))

    deadline = time.monotonic() + 120
    waiting = list(pending)
    while waiting and time.monotonic() < deadline:
        still: list[tuple[str, int]] = []
        for file_id, version in waiting:
            versions = _expect(
                doors.api("GET", f"/files/{file_id}/versions/"), "read a document's versions"
            )
            rows = versions["items"] if isinstance(versions, dict) else versions
            stored = any(
                int(v["version"]) == version and str(v["status"]) == "stored" for v in rows
            )
            if stored:
                ready.append(file_id)
            else:
                still.append((file_id, version))
        waiting = still
        if waiting:
            time.sleep(2.0)

    if waiting:
        _die(
            f"{len(waiting)} pool document(s) never reached `stored` within 120s",
            "Confirming starts a workflow that fetches and measures the object; a",
            "version stuck at `pending` means NOTHING IS RUNNING THE WORKFLOW.",
            "Laptop: ./scripts/worker.sh . Box: the `worker` service in deploy/compose.yaml.",
            "The mix is not reduced to what this environment supports; fix it and re-run.",
        )
    return ready[:DOWNLOAD_POOL]


def archive_created(args: argparse.Namespace, made: Created) -> int:
    pool = Pool(TIMEOUT_SECONDS)
    done = 0
    try:
        for file_id, by in made.file_ids:
            doors = Doors(args.base_url, by.token, by.tenant, by.org, pool)
            if doors.api("POST", f"/files/{file_id}/archive/").ok:
                done += 1
    finally:
        pool.close()
    return done


# --- output -------------------------------------------------------------------


def write_outputs(out_dir: str, manifest: dict, steps: list[StepResult]) -> tuple[str, str, str]:
    os.makedirs(out_dir, exist_ok=True)
    stamp = manifest["run_id"]

    json_path = os.path.join(out_dir, f"drive-{stamp}.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=False)
        fh.write("\n")

    steps_csv = os.path.join(out_dir, f"drive-{stamp}-steps.csv")
    rows = [s.summary() for s in steps]
    with open(steps_csv, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    ops_csv = os.path.join(out_dir, f"drive-{stamp}-operations.csv")
    op_rows = [r for s in steps for r in s.by_operation()]
    with open(ops_csv, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(op_rows[0].keys()))
        writer.writeheader()
        for row in op_rows:
            writer.writerow(row)

    return json_path, steps_csv, ops_csv


def print_ladder(steps: list[StepResult]) -> None:
    print()
    print("  step  conc   door rps    p50     p95     p99   err%  verdict")
    print("  ----  ----  ---------  ------  ------  ------  ----  -------")
    for s in steps:
        d = s.summary()
        rate = d["error_rate_door"]
        print(
            f"  {d['step']:>4}  {d['concurrency']:>4}  "
            f"{(d['door_rps'] or 0):>9.2f}  "
            f"{(d['p50_ms'] or 0):>6.0f}  {(d['p95_ms'] or 0):>6.0f}  "
            f"{(d['p99_ms'] or 0):>6.0f}  "
            f"{(rate * 100 if rate is not None else 0):>4.1f}  {d['verdict']}"
        )


# --- the commands -------------------------------------------------------------


def _token() -> str:
    token = os.environ.get("DRIVE_TOKEN", "").strip()
    if not token:
        _die(
            "DRIVE_TOKEN is not set",
            "Mint one and export it (never pass a token as a flag):",
            "  uv run python manage.py issue_token --email you@example.com \\",
            "      --name load-drive --tenant <slug> --scope '*'",
        )
    return token


def read_credentials(path: str) -> list[Credential]:
    """`--credentials`: a JSON list of `{"tenant", "token"[, "org"]}`; anything else is exit 2."""
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        creds = [
            Credential(tenant=str(c["tenant"]), token=str(c["token"]), org=str(c.get("org", "")))
            for c in raw
        ]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        _die(f"could not read the credentials in {path}", f"{type(exc).__name__}: {exc}")
    if not creds or any(not c.tenant or not c.token for c in creds):
        _die(f"{path} names no credential, or one without a tenant or a token")
    return creds


def credentials_for(args: argparse.Namespace) -> list[Credential]:
    """The clients' credentials: `--credentials`, else `DRIVE_TOKEN` under `--tenant`."""
    if getattr(args, "credentials", ""):
        return read_credentials(args.credentials)
    if not args.tenant:
        _die("name the tenant: --tenant <slug>, or --credentials <file>")
    return [Credential(tenant=args.tenant, token=_token(), org=args.org)]


def _fixtures_path(args: argparse.Namespace) -> str:
    return os.path.join(args.out, "fixtures.json")


def read_fixtures(path: str) -> dict[str, Fixtures]:
    """`fixtures.json` by tenant; a file one tenant's `prepare` wrote reads as that one."""
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    if "by_tenant" in raw:
        return {t: Fixtures.from_json(fx) for t, fx in raw["by_tenant"].items()}
    fx = Fixtures.from_json(raw)
    return {fx.tenant: fx}


def prepare_all(args: argparse.Namespace, creds: Sequence[Credential]) -> dict[str, Fixtures]:
    """`prepare` once per tenant the credentials name, under that tenant's first credential."""
    fixtures: dict[str, Fixtures] = {}
    for cred in creds:
        if cred.tenant not in fixtures:
            print(f"   tenant     {cred.tenant}")
            fixtures[cred.tenant] = prepare(args, cred)
    os.makedirs(args.out, exist_ok=True)
    with open(_fixtures_path(args), "w", encoding="utf-8") as fh:
        json.dump({"by_tenant": {t: fx.as_json() for t, fx in fixtures.items()}}, fh, indent=2)
        fh.write("\n")
    return fixtures


def resolve_ca_bundle(named: str, paths: object) -> tuple[str | None, str]:
    """The bundle to verify against: the one named, the interpreter's own, else certifi's."""
    if named:
        if not os.path.isfile(named):
            _die(f"--ca-bundle {named} is not a file")
        return named, f"CA bundle {named} (named by --ca-bundle)"
    cafile = getattr(paths, "cafile", None)
    capath = getattr(paths, "capath", None)
    if (cafile and os.path.isfile(cafile)) or (
        capath and os.path.isdir(capath) and os.listdir(capath)
    ):
        return None, "CA bundle: this interpreter's own"
    try:
        import certifi
    except ImportError:
        _die(
            f"this interpreter has no CA bundle (cafile={cafile}, capath={capath}) "
            "and certifi is not importable",
            "Pass --ca-bundle <pem>, or run under `uv run python` (the venv has certifi).",
        )
    where = str(certifi.where())
    return where, f"CA bundle: this interpreter has none (cafile={cafile}); using certifi's {where}"


def _manifest(
    args: argparse.Namespace,
    fixtures: dict[str, Fixtures],
    creds: Sequence[Credential],
    ladder: Sequence[int],
    seconds: float,
    run_id: str,
) -> dict:
    return {
        "run_id": run_id,
        "started_at": datetime.now(UTC).isoformat(),
        "base_url": args.base_url,
        "sha_claimed": args.sha,
        "sha_is": "OPERATOR-DECLARED, NOT MEASURED — no door publishes the commit it serves",
        "client_host": platform.node(),
        "client_python": platform.python_version(),
        "seed": SEED,
        "ladder": list(ladder),
        "step_seconds": seconds,
        "timeout_seconds": TIMEOUT_SECONDS,
        "knee_definition": {
            "threshold_p95_ms": KNEE_P95_MS,
            "windows_per_step": WINDOWS,
            "warmup_windows_discarded": 1,
            "min_window_samples": MIN_WINDOW_SAMPLES,
            "statement": (
                "the first ladder step where p95 over DOOR samples exceeds the "
                "threshold in EVERY measured sub-window; a sub-window below "
                "min_window_samples makes the step undetermined, never under"
            ),
            "door_only": (
                "object-storage legs (the upload PUT, the download GET) are "
                "excluded from every p95 — a slow store is not a slow platform"
            ),
        },
        "mix": mix_manifest(),
        "fixtures": {t: fx.as_json() for t, fx in fixtures.items()},
        "clients": {
            "credentials": len(creds),
            "tenants": sorted({c.tenant for c in creds}),
            "assignment": "client w carries credential w mod credentials",
        },
        "bar": {
            "clients": BAR_CLIENTS,
            "p95_ms_below": BAR_P95_MS,
            "err_pct_below": BAR_ERR_PCT,
            "statement": "every step up to the bar's clients judged; an observation, never an exit",
        },
        "resolve": dict(RESOLVE),
        "credential_pace_per_second": PACE_PER_SECOND[0],
    }


def command_prepare(args: argparse.Namespace) -> int:
    creds = credentials_for(args)
    tenants = sorted({c.tenant for c in creds})
    print(f"== drive prepare · {args.base_url} · tenants {', '.join(tenants)}")
    prepare_all(args, creds)
    print(f"== READY · fixtures written to {_fixtures_path(args)}")
    return 0


def command_run(
    args: argparse.Namespace,
    ladder: Sequence[int],
    seconds: float,
    sink: dict | None = None,
) -> int:
    creds = credentials_for(args)
    path = _fixtures_path(args)
    fixtures = read_fixtures(path) if os.path.exists(path) and not args.reprepare else {}
    if fixtures and {c.tenant for c in creds} <= set(fixtures):
        print(f"== drive · fixtures adopted from {path}")
    else:
        print(f"== drive · preparing fixtures ({args.base_url})")
        fixtures = prepare_all(args, creds)

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    manifest = _manifest(args, fixtures, creds, ladder, seconds, run_id)
    print(
        f"== drive run {run_id} · sha(claimed) {args.sha} · ladder {list(ladder)}"
        f" · {seconds:g}s/step · seed {SEED}"
    )
    print(
        f"   mix {_READ_WEIGHT} read : {_WRITE_WEIGHT} write over "
        f"{len(MIX)} operations; knee = first step with sustained p95 > "
        f"{KNEE_P95_MS:.0f} ms"
    )
    print(
        f"   {len(creds)} credential(s) across {len({c.tenant for c in creds})} tenant(s);"
        f" the bar: {BAR_CLIENTS} clients at p95 < {BAR_P95_MS:.0f} ms, err < {BAR_ERR_PCT:g}%"
    )

    made = Created()
    steps: list[StepResult] = []
    knee: dict | None = None
    for index, concurrency in enumerate(ladder):
        print(f"   step {index} · concurrency {concurrency} · {seconds:g}s ...", flush=True)
        step = run_step(index, concurrency, seconds, args, creds, fixtures, made)
        steps.append(step)
        if step.verdict == "driver_fault":
            print(f"      DRIVER FAULT — {step.reason}", file=sys.stderr)
            for line in sorted(set(step.faults)):
                print(f"        {line}", file=sys.stderr)
            knee = {
                "step": index,
                "concurrency": concurrency,
                "verdict": "driver_fault",
                "reason": step.reason,
                "faults": sorted(set(step.faults)),
            }
            break
        if step.verdict == "undetermined":
            print(f"      UNDETERMINED — {step.reason}")
            knee = {
                "step": index,
                "concurrency": concurrency,
                "verdict": "undetermined",
                "reason": step.reason,
            }
            break
        if step.verdict == "over":
            knee = {
                "step": index,
                "concurrency": concurrency,
                "verdict": "found",
                "reason": step.reason,
            }
            break

    manifest["steps"] = [s.summary() for s in steps]
    manifest["operations"] = [r for s in steps for r in s.by_operation()]
    if knee is None:
        manifest["knee"] = {
            "verdict": "not_reached",
            "reason": (
                f"no step in the ladder sustained p95 above {KNEE_P95_MS:.0f} ms; "
                f"the knee is above concurrency {ladder[-1]} and this run does not name it"
            ),
        }
    else:
        manifest["knee"] = knee

    status_util = 0
    if steps:
        part, seen = "not_sampled", True
        if getattr(args, "utilization", None):
            part, seen = utilization_part(
                manifest["steps"], manifest["knee"], read_utilization_files(args.utilization)
            )
            status_util = 0 if seen else 2
        manifest["instrument"] = paced_instrument(
            f"deploy/load/drive.py run --ladder {','.join(str(c) for c in ladder)}"
            f" --step-seconds {seconds:g} --seed {SEED}",
            _pacer_word(PACE_PER_SECOND[0]),
        )
        manifest["conditions"] = {
            "size": getattr(args, "size", ""),
            "scale": getattr(args, "scale", ""),
            "topology": getattr(args, "topology", ""),
            "client": getattr(args, "client", ""),
        }
        manifest["bar"]["verdict"] = judge_bar(
            manifest["steps"], topology=manifest["conditions"]["topology"], credentials=len(creds)
        )
        manifest["envelope_line"] = envelope_line(
            steps=manifest["steps"],
            knee=manifest["knee"],
            utilization=part,
            instrument=manifest["instrument"],
            credentials=creds,
            pace=PACE_PER_SECOND[0],
            **manifest["conditions"],
        )

    json_path, steps_csv, ops_csv = write_outputs(args.out, manifest, steps)
    print_ladder(steps)
    print()
    verdict = manifest["knee"]["verdict"]
    print(f"== KNEE · {verdict} — {manifest['knee'].get('reason', '')}")
    if verdict == "found":
        print(
            f"   first sustained p95 > {KNEE_P95_MS:.0f} ms at step "
            f"{knee['step']}, concurrency {knee['concurrency']}"
        )
    if "envelope_line" in manifest:
        print(f"== ENVELOPE · {manifest['envelope_line']}")
    print(f"   {json_path}")
    print(f"   {steps_csv}")
    print(f"   {ops_csv}")

    if args.archive_created and made.file_ids:
        done = archive_created(args, made)
        print(f"   archived {done}/{len(made.file_ids)} documents this run filed")

    if sink is not None:
        sink["steps"] = steps
        sink["manifest"] = manifest

    # 0 the ladder ran and was judged · 1 the DRIVER is broken · 2 could-not-look.
    if verdict == "driver_fault":
        return 1
    if verdict == "undetermined" or status_util:
        return 2
    return 0


def _adopt_fixtures(args: argparse.Namespace, creds: Sequence[Credential]) -> dict[str, Fixtures]:
    path = _fixtures_path(args)
    if not os.path.exists(path):
        _die(f"no fixtures at {path}", "Run `prepare` (or `run`) first; a soak never prepares.")
    fixtures = read_fixtures(path)
    missing = sorted({c.tenant for c in creds} - set(fixtures))
    if missing:
        _die(f"{path} holds no fixtures for {', '.join(missing)}", "Run `prepare` first.")
    return fixtures


def command_soak(args: argparse.Namespace) -> int:
    """Hold N clients for M minutes and judge each window: `steady`, `drifting`, `unsteady`."""
    creds = credentials_for(args)
    fixtures = _adopt_fixtures(args, creds)
    if not args.processes and not args.defer_judgement:
        _die("a judged soak needs --processes (scripts/envelope.sh reads it off compose config)")
    budget = declared_pool_budget(args.settings, parse_processes(args.processes or "web=1"))
    seconds = args.minutes * 60.0
    print(
        f"== drive soak · concurrency {args.concurrency} · {args.minutes:g} min · "
        f"{SOAK_WINDOW_SECONDS:g}s windows · pool budget "
        f"{f'{budget} ({args.processes})' if args.processes else 'judged later'} · "
        f"err bound {args.err_bound:g}%"
    )
    made = Created()
    step = run_step(0, args.concurrency, seconds, args, creds, fixtures, made)
    if step.faults:
        print(f"!! DRIVER FAULT — {sorted(set(step.faults))[0]}", file=sys.stderr)
        return 1
    util = read_utilization_files(args.utilization) if args.utilization else []
    os.makedirs(args.out, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    with open(os.path.join(args.out, f"soak-{stamp}-samples.json"), "w", encoding="utf-8") as fh:
        json.dump(
            {
                "concurrency": args.concurrency,
                "minutes": args.minutes,
                "seconds": step.seconds,
                "started_epoch": step.started_epoch,
                "samples": [[s.at, s.ms, s.status, s.door] for s in step.samples],
            },
            fh,
        )
        fh.write("\n")
    if args.defer_judgement:
        print(f"== SOAK · deferred — `judge` reads soak-{stamp}-samples.json")
        return 0
    return _print_soak(args, step.samples, step.seconds, step.started_epoch, util, budget, stamp)


def _print_soak(
    args: argparse.Namespace,
    samples: Sequence[Sample],
    seconds: float,
    origin: float,
    util: Sequence[dict[str, Any]],
    budget: int,
    stamp: str,
) -> int:
    """Judge the soak's windows, print the table and the line, write `soak-<stamp>.json`."""
    slack = declared_outbox_slack(args.activities)
    result = judge_soak(
        samples,
        seconds,
        origin,
        util,
        budget=budget,
        outbox_slack=slack,
        err_bound=args.err_bound / 100,
    )
    print()
    print(
        "  window  door   err%     p95  throttled  pg_total  pg_clients  outbox  backlog"
        "  host_cpu(med/max)  organs_cpu(med/max)"
    )
    for w in result.windows:
        err = "-" if w["err"] is None else f"{w['err'] * 100:.2f}"
        print(
            f"  {w['window']:>6}  {w['door_samples']:>4}  {err:>5}  {w['p95_ms'] or 0:>6.0f}"
            f"  {w['throttled']:>9}  {_or_dash(w['pg_total']):>8}"
            f"  {_or_dash(w.get('pg_clients')):>10}"
            f"  {_or_dash(w['outbox_pending']):>6}  {_or_dash(w['worker_backlog']):>7}"
            f"  host_cpu={_cpu_cell(w.get('host_cpu'))}"
            f"  organs_cpu={_cpu_cell(w.get('organs_cpu'))}"
            + (f"  pg_other={w['pg_other'] or '-'}" if w.get("pg_other") is not None else "")
        )
    line = soak_line(result, args.concurrency, args.minutes, budget, args.err_bound)
    print(f"== SOAK · {line}")
    for reason in result.reasons:
        print(f"   {reason}")
    with open(os.path.join(args.out, f"soak-{stamp}.json"), "w", encoding="utf-8") as fh:
        json.dump(
            {
                "line": line,
                "verdict": result.verdict,
                "reasons": result.reasons,
                "windows": result.windows,
                "budget": budget,
            },
            fh,
            indent=2,
        )
        fh.write("\n")
    return 2 if result.verdict == "undetermined" else 0


def _or_dash(value: object) -> str:
    """A table cell or a line field: the value, or `-` where nothing was read."""
    return "-" if value is None else str(value)


def soak_line(
    result: SoakResult, concurrency: int, minutes: float, budget: int, err_bound_pct: float
) -> str:
    """The SOAK line: the verdict, the bounds it was judged on, and which of them broke."""
    ws = result.windows
    pg = [w["pg_total"] for w in ws if w["pg_total"] is not None]
    clients = [w["pg_clients"] for w in ws if w.get("pg_clients") is not None]
    named = max(
        (w for w in ws if w.get("pg_other") is not None), key=lambda w: w["pg_total"], default=None
    )
    other = f"pg_other={named['pg_other'] or '-'} " if named else ""
    errs = [w["err"] for w in ws if w["err"] is not None]
    backlog = [w["worker_backlog"] for w in ws if w["worker_backlog"] is not None]
    idle_tx = [w["idle_in_tx"] for w in ws if w.get("idle_in_tx") is not None]
    cpu_max = {
        key: max((float(w[key][1]) for w in ws if w.get(key) is not None), default=None)
        for key in SOAK_CPU_KEYS
    }
    outbox = (
        f"{_or_dash(ws[0]['outbox_pending'])}/{_or_dash(ws[-1]['outbox_pending'])}" if ws else "-"
    )
    line = (
        f"soak={result.verdict} concurrency={concurrency} minutes={minutes:g} "
        f"pool_budget={budget} max_pg_clients={max(clients, default='-')} "
        f"max_pg_total={max(pg, default='-')} "
        f"{other}"
        f"max_idle_in_tx={max(idle_tx, default='-')} outbox_pending={outbox} "
        f"err_max={f'{max(errs) * 100:.2f}' if errs else '-'} err_bound={err_bound_pct:g} "
        f"max_worker_backlog={max(backlog, default='-')}"
    )
    for key, peak in cpu_max.items():
        line += f" max_{key}={'-' if peak is None else f'{peak:.1f}'}"
    broken = sorted({r.split(":", 1)[0] for r in result.reasons} & {"err", "pg_clients", "outbox"})
    if result.verdict == "unsteady" and broken:
        line += f" broken={','.join(broken)}"
    if result.verdict == "unsteady" and "pg_clients" in broken:
        held = max(ws, key=lambda w: w.get("pg_clients") or 0)
        line += f" pg_by_app={held['pg_by_app'] or '-'}"
    return line


def command_smoke(args: argparse.Namespace) -> int:
    """A tiny end-to-end run whose ONE assertion is that the whole mix reaches a door.

    A smoke's `undetermined` knee is the DESIGNED outcome — six-second windows
    cannot hold `MIN_WINDOW_SAMPLES` — so exit 2 from the ladder is expected
    here and is not the verdict. What IS the verdict: every operation in `MIX`
    produced at least one 2xx. That is the assertion the first smoke of this
    script failed (`files.download` read a response field that does not exist),
    and a smoke that only checked "it ran" would have passed it.
    """
    print("== drive smoke · a tiny ladder, deliberately too short to support a knee.")
    print("   It proves this script runs end to end against a base URL and that every")
    print("   operation in the mix reaches its door. It is NOT an envelope.")
    args.sha = args.sha or "(smoke — no sha claimed)"
    sink: dict = {}
    status = command_run(args, SMOKE_LADDER, SMOKE_STEP_SECONDS, sink=sink)
    if status == 1:
        return 1

    steps: list[StepResult] = sink.get("steps", [])
    answered = {s.op for step in steps for s in step.samples if s.ok}
    missing = [o.name for o in MIX if o.name not in answered]
    print()
    if missing:
        print(
            f"== SMOKE FAILED · {len(missing)} operation(s) never got a 2xx: {', '.join(missing)}",
            file=sys.stderr,
        )
        print(
            "   The mix names a door this environment did not answer. Read the operations CSV.",
            file=sys.stderr,
        )
        return 1
    print(
        f"== SMOKE PASSED · all {len(MIX)} operations in the mix answered 2xx "
        f"({', '.join(sorted(answered))})"
    )
    return 0


def _newest(out: str, pattern: str) -> str | None:
    found = sorted(glob.glob(os.path.join(out, pattern)))
    return found[-1] if found else None


def command_judge(args: argparse.Namespace) -> int:
    """The ENVELOPE and SOAK lines of a run whose samplers ran on other boxes, from their files."""
    if args.restamp:
        return command_restamp(args.restamp)
    if not (args.out and args.utilization):
        _die("`judge` reads --out and --utilization, or rewrites --restamp <chapter>")
    util = read_utilization_files(args.utilization)
    run_path = _newest(args.out, "drive-*Z.json")
    if run_path is None:
        _die(
            f"no drive-*.json in {args.out}", "`judge` reads what `run` wrote; it measures nothing."
        )
    with open(run_path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    tenants = manifest["clients"]["tenants"]
    count = int(manifest["clients"]["credentials"])
    creds = [Credential(tenant=tenants[i % len(tenants)], token="") for i in range(count)]
    part, seen = utilization_part(manifest["steps"], manifest["knee"], util)
    status = 0 if seen else 2
    line = envelope_line(
        steps=manifest["steps"],
        knee=manifest["knee"],
        utilization=part,
        instrument=manifest["instrument"],
        credentials=creds,
        pace=float(manifest.get("credential_pace_per_second") or 0.0),
        **manifest["conditions"],
    )
    print(f"== ENVELOPE · {line}")
    soak_path = _newest(args.out, "soak-*-samples.json")
    if soak_path is not None:
        with open(soak_path, encoding="utf-8") as fh:
            soak = json.load(fh)
        samples = [
            Sample("soak", "", bool(door), int(status_), float(ms), float(at))
            for at, ms, status_, door in soak["samples"]
        ]
        if not args.processes:
            _die("a soak is judged against --processes (envelope.sh reads it off compose config)")
        budget = declared_pool_budget(args.settings, parse_processes(args.processes))
        args.concurrency, args.minutes = soak["concurrency"], soak["minutes"]
        stamp = os.path.basename(soak_path)[len("soak-") : -len("-samples.json")] + "-judged"
        rc = _print_soak(args, samples, soak["seconds"], soak["started_epoch"], util, budget, stamp)
        status = max(status, rc)
    return status


def command_restamp(path: str) -> int:
    """Rewrite a chapter's recorded lines into the current form, in place, and say what moved."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    new, report = restamp_recorded(text)
    if not report:
        _die(f"no recorded envelope line in {path}", "`--restamp` reads § 9's `metric=` lines.")
    if new != text:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(new)
    moved = sum(1 for r in report if r.startswith("restamped"))
    print(f"== RESTAMP · {moved} restamped, {len(report) - moved} kept · {path}")
    for line in report:
        print(f"   {line}")
    return 0


def command_baseline(args: argparse.Namespace) -> int:
    """capacity.md § 7's pre-spend gate: exit 0 every database inside its bound, 2 otherwise."""
    try:
        with open(args.census, encoding="utf-8") as fh:
            census = fh.read()
    except OSError as exc:
        _die(f"could not read the census in {args.census}", str(exc))
    budget = declared_pool_budget(args.settings, parse_processes(args.processes))
    ok, lines = judge_baseline(census, app_db=args.app_db, budget=budget)
    print(f"== BASELINE · {'clean' if ok else 'DIRTY — the run is void before it starts'}")
    for line in lines:
        print(f"   {line}")
    return 0 if ok else 2


def command_processes(args: argparse.Namespace) -> int:
    """Print the `--processes` a rendered compose declares, for the soak's pool budget."""
    print(format_processes(compose_processes(args.compose)))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="drive.py", description="The committed load drive (LOAD-1)."
    )
    subs = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--base-url", required=True, help="e.g. https://staging.example.invalid")
        p.add_argument("--tenant", default="", help="the X-Tenant slug DRIVE_TOKEN drives as")
        p.add_argument("--credentials", default="", help="a JSON list of {tenant, token}")
        p.add_argument("--org", default="", help="the X-Org slug; omit for the default org")
        p.add_argument("--out", default="deploy/load/out", help="where results are written")
        p.add_argument("--ca-bundle", default="", help="a PEM to verify TLS against")
        p.add_argument(
            "--resolve", action="append", default=[], help="NAME:ADDRESS, dialled for NAME"
        )

    def soak_bounds(p: argparse.ArgumentParser) -> None:
        p.add_argument("--processes", default="", help="web=1,worker=2 — off compose config")
        p.add_argument("--settings", default=SETTINGS_BASE, help="where the pool is declared")
        p.add_argument(
            "--activities", default=EVENTS_ACTIVITIES, help="where the relay is declared"
        )
        p.add_argument(
            "--err-bound", type=float, default=BAR_ERR_PCT, help="a window's err bound, in percent"
        )

    p_prepare = subs.add_parser("prepare", help="build the fixture set the mix needs")
    common(p_prepare)

    p_run = subs.add_parser("run", help="drive the full ladder and name the knee")
    common(p_run)
    p_run.add_argument("--sha", required=True, help="the commit the target is serving (a CLAIM)")
    p_run.add_argument("--ladder", default="", help=f"comma-separated; default {list(LADDER)}")
    p_run.add_argument("--step-seconds", type=float, default=STEP_SECONDS)
    p_run.add_argument("--reprepare", action="store_true", help="rebuild fixtures first")
    p_run.add_argument("--archive-created", action="store_true", help="archive documents made")
    p_run.add_argument(
        "--utilization", action="append", default=[], help="a box sampler's JSON lines"
    )
    p_run.add_argument("--size", default="", help="the box class, for the line's conditions")
    p_run.add_argument("--scale", default="prepared", help="the dataset scale, likewise")
    p_run.add_argument("--topology", default="", help="e.g. compose-one-host, likewise")
    p_run.add_argument("--client", default="", help="the drive box's class, likewise")

    p_soak = subs.add_parser("soak", help="hold N clients for M minutes, judged per window")
    common(p_soak)
    p_soak.add_argument("--concurrency", type=int, required=True)
    p_soak.add_argument("--minutes", type=float, required=True)
    p_soak.add_argument(
        "--utilization", action="append", default=[], help="a box sampler's JSON lines"
    )
    p_soak.add_argument(
        "--defer-judgement",
        action="store_true",
        help="write the samples; `judge` gives the verdict",
    )
    soak_bounds(p_soak)

    p_judge = subs.add_parser("judge", help="the lines of a run whose samplers were elsewhere")
    p_judge.add_argument("--out", default="", help="the run's output directory")
    p_judge.add_argument("--utilization", action="append", default=[])
    p_judge.add_argument(
        "--restamp", default="", help="rewrite a chapter's § 9 lines into the current form"
    )
    soak_bounds(p_judge)

    p_base = subs.add_parser("baseline", help="the pre-spend census gate (capacity.md § 7)")
    p_base.add_argument("--census", required=True, help="§ 2a's rows, psql -A -t")
    p_base.add_argument("--app-db", required=True, help="the app's database name")
    p_base.add_argument("--processes", required=True, help="web=1,worker=2 — off compose config")
    p_base.add_argument("--settings", default=SETTINGS_BASE, help="where the pool is declared")

    p_proc = subs.add_parser("processes", help="the pool's processes off a rendered compose")
    p_proc.add_argument("--compose", required=True, help="`docker compose config --format json`")

    p_smoke = subs.add_parser("smoke", help="a tiny local end-to-end run of the same code")
    common(p_smoke)
    p_smoke.add_argument("--sha", default="")
    p_smoke.add_argument("--reprepare", action="store_true")
    p_smoke.add_argument("--archive-created", action="store_true")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "judge":
        return command_judge(args)
    if args.command == "baseline":
        return command_baseline(args)
    if args.command == "processes":
        return command_processes(args)
    for pair in args.resolve:
        name, sep, address = pair.partition(":")
        if not (sep and name and address):
            _die(f"--resolve takes NAME:ADDRESS, got {pair!r}")
        RESOLVE[name] = address
    CA_BUNDLE[0], said = resolve_ca_bundle(args.ca_bundle, ssl.get_default_verify_paths())
    print(f"   {said}")
    PACE_PER_SECOND[0] = CREDENTIAL_PACE * declared_auth_rate(SETTINGS_BASE)
    print(f"   each credential paced to {PACE_PER_SECOND[0]:g}/s ({CREDENTIAL_PACE:g} of auth)")
    if args.command == "soak":
        return command_soak(args)
    if args.command == "prepare":
        return command_prepare(args)
    if args.command == "smoke":
        return command_smoke(args)
    ladder = tuple(int(x) for x in args.ladder.split(",") if x.strip()) or LADDER
    return command_run(args, ladder, args.step_seconds)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
