#!/usr/bin/env python3
"""The committed load drive — one fixed request mix, one stepped ladder, one knee.

    ./deploy/load/drive.py prepare --base-url URL --tenant SLUG
    ./deploy/load/drive.py run     --base-url URL --tenant SLUG --sha SHA
    ./deploy/load/drive.py smoke   --base-url URL --tenant SLUG

`DRIVE_TOKEN` in the environment is the bearer token every call carries. It is
never a flag, because a token on a command line is a token in a shell history.

WHY IT IS COMMITTED, WHICH IS THE WHOLE POINT. LOAD-1's envelope document is
falsifiable only if somebody else can re-run the same ladder against the same
sha and get the same shape — that requirement is LOAD-1's own, stated in its
cycle plan, and the platform repository is the archive of record for those
plans. A drive assembled in a terminal and thrown away produces numbers nobody
can reproduce and therefore nobody can contradict. So the mix, the ladder, the
seeds and the knee's DEFINITION are all in this file, in source, above the code
that uses them — and the machine-readable output carries a copy of every one of
them, so a JSON file found later still says what it was measured with.

WHAT IT MEASURES, AND THE ONE THING IT DOES NOT. It measures the DOORS: the
latency and status of HTTP calls to `/api/v1/...` under a closed-loop
concurrency ladder. It does NOT measure which component saturated first — that
is read off ClickStack at the knee this run names, and it is LOAD-1b's half.
This script's job is to produce a knee that is a readable fact rather than an
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
1. WHICH COMPONENT SATURATED. Nothing here reads app-box CPU, RDS CPU/IOPS,
   pool depth, worker backlog or Redis. The knee is a wall-clock fact about the
   doors; naming the first-saturating component is a ClickStack read at the
   step this run names, and the resize-axis rule requires that evidence
   separately (the cycle plan's `LOAD-1 — criteria`).
2. THE SHA IS OPERATOR-DECLARED, NOT MEASURED. No door on this platform
   publishes the commit it is serving — `/healthz` answers `{"status": "ok"}`
   and `/readyz` answers organ booleans (`apps/core/health.py:300-310`). So
   `--sha` is copied into the manifest verbatim as a CLAIM, labelled as one.
   What proves the box serves that sha is the deploy runbook's own proof set,
   not this script.
3. THE CLIENT IS THE LAPTOP. Latency here includes the path from wherever this
   runs to the box. A drive from a coffee shop measures the coffee shop. The
   manifest records the client host so two runs can be compared for it, and it
   does not correct for it.
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

The commonest refusal is a document that never reaches `stored`, which means
the confirm workflow had no worker (`./scripts/worker.sh` on a laptop; the
`worker` service on a box). That is an environment fact and the message says so.
"""

from __future__ import annotations

import argparse
import csv
import http.client
import json
import math
import os
import platform
import random
import ssl
import sys
import threading
import time
import urllib.parse
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

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

#: Per-request timeout. A request still running at this point is a failure with
#: `status=0`, not a very slow success.
TIMEOUT_SECONDS = 30.0

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


# --- the wire ----------------------------------------------------------------


@dataclass(frozen=True)
class Reply:
    """One HTTP round trip, as measured."""

    status: int  # 0 means the request never produced a status
    body: bytes
    ms: float
    error: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self) -> dict:
        return json.loads(self.body.decode("utf-8"))


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
                    host, port, timeout=self._timeout, context=ssl.create_default_context()
                )
            else:
                conn = http.client.HTTPConnection(host, port, timeout=self._timeout)
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
            return Reply(response.status, payload, (time.perf_counter() - started) * 1000.0)
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
        return self.pool.call(method, url, headers=headers, body=body)

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


@dataclass
class Created:
    """Documents this run filed, so `--archive-created` can put them away."""

    file_ids: list[str] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, file_id: str) -> None:
        with self.lock:
            self.file_ids.append(file_id)


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
    made.add(file_id)

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

    # filled by `judge`
    verdict: str = "undetermined"  # under | over | undetermined | driver_fault
    reason: str = ""
    window_p95: list[float] = field(default_factory=list)
    window_counts: list[int] = field(default_factory=list)

    @property
    def door_samples(self) -> list[Sample]:
        return [s for s in self.samples if s.door]

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
        errors = [s for s in self.samples if not s.ok]
        door_errors = [s for s in self.door_samples if not s.ok]
        return {
            "step": self.index,
            "concurrency": self.concurrency,
            "seconds": round(self.seconds, 3),
            "requests_total": len(self.samples),
            "requests_door": len(door),
            "errors_total": len(errors),
            "errors_door": len(door_errors),
            "error_rate_door": round(len(door_errors) / len(door), 6) if door else None,
            "door_rps": round(len(door) / self.seconds, 3) if self.seconds else None,
            "p50_ms": round(percentile(door, 0.50), 2) if door else None,
            "p90_ms": round(percentile(door, 0.90), 2) if door else None,
            "p95_ms": round(percentile(door, 0.95), 2) if door else None,
            "p99_ms": round(percentile(door, 0.99), 2) if door else None,
            "max_ms": round(max(door), 2) if door else None,
            "window_p95_ms": [None if math.isnan(p) else round(p, 2) for p in self.window_p95],
            "window_door_samples": self.window_counts,
            "driver_faults": len(self.faults),
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
                    "errors": sum(1 for s in these if not s.ok),
                    "p50_ms": round(percentile(ms, 0.50), 2),
                    "p95_ms": round(percentile(ms, 0.95), 2),
                    "p99_ms": round(percentile(ms, 0.99), 2),
                    "max_ms": round(max(ms), 2),
                    "statuses": json.dumps(dict(sorted(statuses.items()))),
                }
            )
        return rows


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
    token: str,
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
    rng = random.Random((SEED, step_index, worker_id).__hash__() ^ SEED)
    pool = Pool(TIMEOUT_SECONDS)
    doors = Doors(args.base_url, token, fx.tenant, fx.org, pool)
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
    token: str,
    fx: Fixtures,
    made: Created,
) -> StepResult:
    samples: list[Sample] = []
    faults: list[str] = []
    lock = threading.Lock()
    origin = time.perf_counter()
    deadline = origin + seconds
    threads = [
        threading.Thread(
            target=_worker,
            args=(w, index, args, token, fx, made, deadline, origin, samples, faults, lock),
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
    step = StepResult(index, concurrency, elapsed, samples, faults=faults)
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


def prepare(args: argparse.Namespace, token: str) -> Fixtures:
    pool = Pool(TIMEOUT_SECONDS)
    doors = Doors(args.base_url, token, args.tenant, args.org, pool)
    rng = random.Random(SEED)
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
        return Fixtures(args.tenant, args.org, recipient_id, template, tuple(file_ids))
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


def archive_created(args: argparse.Namespace, token: str, made: Created) -> int:
    pool = Pool(TIMEOUT_SECONDS)
    doors = Doors(args.base_url, token, args.tenant, args.org, pool)
    done = 0
    try:
        for file_id in made.file_ids:
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


def _manifest(
    args: argparse.Namespace, fx: Fixtures, ladder: Sequence[int], seconds: float, run_id: str
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
        "fixtures": fx.as_json(),
    }


def command_prepare(args: argparse.Namespace) -> int:
    token = _token()
    print(f"== drive prepare · {args.base_url} · tenant {args.tenant}")
    fx = prepare(args, token)
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, "fixtures.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(fx.as_json(), fh, indent=2)
        fh.write("\n")
    print(f"== READY · fixtures written to {path}")
    return 0


def command_run(
    args: argparse.Namespace,
    ladder: Sequence[int],
    seconds: float,
    sink: dict | None = None,
) -> int:
    token = _token()
    path = os.path.join(args.out, "fixtures.json")
    if os.path.exists(path) and not args.reprepare:
        with open(path, encoding="utf-8") as fh:
            fx = Fixtures.from_json(json.load(fh))
        print(f"== drive · fixtures adopted from {path}")
    else:
        print(f"== drive · preparing fixtures ({args.base_url})")
        fx = prepare(args, token)
        os.makedirs(args.out, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(fx.as_json(), fh, indent=2)
            fh.write("\n")

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    manifest = _manifest(args, fx, ladder, seconds, run_id)
    print(
        f"== drive run {run_id} · sha(claimed) {args.sha} · ladder {list(ladder)}"
        f" · {seconds:g}s/step · seed {SEED}"
    )
    print(
        f"   mix {_READ_WEIGHT} read : {_WRITE_WEIGHT} write over "
        f"{len(MIX)} operations; knee = first step with sustained p95 > "
        f"{KNEE_P95_MS:.0f} ms"
    )

    made = Created()
    steps: list[StepResult] = []
    knee: dict | None = None
    for index, concurrency in enumerate(ladder):
        print(f"   step {index} · concurrency {concurrency} · {seconds:g}s ...", flush=True)
        step = run_step(index, concurrency, seconds, args, token, fx, made)
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
    print(f"   {json_path}")
    print(f"   {steps_csv}")
    print(f"   {ops_csv}")

    if args.archive_created and made.file_ids:
        done = archive_created(args, token, made)
        print(f"   archived {done}/{len(made.file_ids)} documents this run filed")

    if sink is not None:
        sink["steps"] = steps
        sink["manifest"] = manifest

    # 0 the ladder ran and was judged · 1 the DRIVER is broken · 2 could-not-look.
    if verdict == "driver_fault":
        return 1
    if verdict == "undetermined":
        return 2
    return 0


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="drive.py", description="The committed load drive (LOAD-1)."
    )
    subs = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--base-url", required=True, help="e.g. https://staging.example.invalid")
        p.add_argument("--tenant", required=True, help="the X-Tenant slug to drive as")
        p.add_argument("--org", default="", help="the X-Org slug; omit for the default org")
        p.add_argument("--out", default="deploy/load/out", help="where results are written")

    p_prepare = subs.add_parser("prepare", help="build the fixture set the mix needs")
    common(p_prepare)

    p_run = subs.add_parser("run", help="drive the full ladder and name the knee")
    common(p_run)
    p_run.add_argument("--sha", required=True, help="the commit the target is serving (a CLAIM)")
    p_run.add_argument("--ladder", default="", help=f"comma-separated; default {list(LADDER)}")
    p_run.add_argument("--step-seconds", type=float, default=STEP_SECONDS)
    p_run.add_argument("--reprepare", action="store_true", help="rebuild fixtures first")
    p_run.add_argument("--archive-created", action="store_true", help="archive documents made")

    p_smoke = subs.add_parser("smoke", help="a tiny local end-to-end run of the same code")
    common(p_smoke)
    p_smoke.add_argument("--sha", default="")
    p_smoke.add_argument("--reprepare", action="store_true")
    p_smoke.add_argument("--archive-created", action="store_true")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "prepare":
        return command_prepare(args)
    if args.command == "smoke":
        return command_smoke(args)
    ladder = tuple(int(x) for x in args.ladder.split(",") if x.strip()) or LADDER
    return command_run(args, ladder, args.step_seconds)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
