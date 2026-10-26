#!/usr/bin/env python3
"""Commit-to-frame over the socket door per widget touch, beside the load drive (ADR perf-1)."""

# does-not-cover: an environment override of the join bound (the door mode reads its default).

from __future__ import annotations

import argparse
import ast
import asyncio
import base64
import http.client
import json
import math
import os
import re
import socket
import ssl
import struct
import sys
import time
import urllib.parse
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol, TextIO

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quality.could_not_look import CouldNotLook as Refused  # noqa: E402

BASE_PY = ROOT / "config" / "settings" / "base.py"
ACTIVITIES_PY = ROOT / "apps" / "events" / "activities.py"
API = "/api/v1"
SOCKET_PATH = "/ws/events/"
PROBE_NAME = "realtime-lag probe"
STAMP = "%Y%m%dT%H%M%SZ"
WIDGET_TOUCHED = "example.widget.touched"
RELAY_SCHEDULE = "events.reconcile-outbox"
FORMULA_ORM = "frame sent - commit, per socket per press; nearest-rank p50 and p95 over every frame"
FORMULA_DOOR = (
    "frame received - press sent (an upper bound on commit-to-frame), per socket per press; "
    "nearest-rank p50 and p95 over every frame"
)
FORMULA_COMMIT = (
    "frame received (wall clock) - the frame's own occurred_at (stamped at emit inside the "
    "transaction, so an upper bound by the service's remaining work before COMMIT), per socket "
    "per press; nearest-rank p95 over every frame"
)
FORMULA_DOOR_TRIP = (
    "the touch's own round trip: POST sent - answer read, per press; nearest-rank p95 over every "
    "press"
)
FORMULA_ORM_TRIP = (
    "the in-process touch's round trip: service call started - returned after its commit, per "
    "press; nearest-rank p95 over every press"
)
CLOCK_UNDECLARED = (
    "undeclared: no box clock offset was handed to the probe, so p95_commit_ms carries the two "
    "clocks' unread skew"
)
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def nearest_rank(samples: list[float], percentile: int) -> float:
    """The nearest-rank percentile of a non-empty list of samples."""
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(percentile / 100 * len(ordered)) - 1)]


def declared_socket_caps(base_py: str | os.PathLike[str]) -> tuple[int, int]:
    """SF-SOCKET-1's per-credential and per-tenant join bounds, read by name out of settings."""
    text = open(base_py, encoding="utf-8").read()
    caps = []
    for name in ("REALTIME_MAX_SOCKETS_PER_CREDENTIAL", "REALTIME_MAX_SOCKETS_PER_TENANT"):
        found = re.search(rf'env\.int\(\s*"{name}",\s*default=(\d+)\s*\)', text)
        if not found:
            raise Refused(f"could not find {name}'s default in {base_py}")
        caps.append(int(found.group(1)))
    return caps[0], caps[1]


def declared_relay_seconds(activities_py: str | os.PathLike[str]) -> int:
    """`RECONCILE_EVERY` in seconds: the relay sweep a frame the dispatch missed waits for."""
    tree = ast.parse(open(activities_py, encoding="utf-8").read())
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "RECONCILE_EVERY"
            and isinstance(node.value, ast.Call)
        ):
            units = {"seconds": 1, "minutes": 60, "hours": 3600}
            return sum(
                int(ast.literal_eval(k.value)) * units[str(k.arg)] for k in node.value.keywords
            )
    raise Refused(f"could not find RECONCILE_EVERY in {activities_py}")


class Socket(Protocol):
    async def frame(self, deadline: float) -> tuple[float, float, dict[str, Any]] | None: ...
    async def close(self) -> None: ...


class Transport(Protocol):
    async def call(
        self, method: str, path: str, *, token: str, tenant: str, body: object = None
    ) -> tuple[int, dict[str, Any]]: ...
    async def socket(self, *, token: str, tenant: str, within: float) -> Socket: ...


class InProcessSocket:
    """One websocket held open on an ASGI application; each frame stamped as it is sent."""

    def __init__(self, application: Any, headers: list[tuple[bytes, bytes]]) -> None:
        self.scope: dict[str, Any] = {
            "type": "websocket",
            "path": SOCKET_PATH,
            "raw_path": SOCKET_PATH.encode(),
            "query_string": b"",
            "headers": headers,
            "subprotocols": [],
            "client": ("127.0.0.1", 0),
            "server": ("localhost", 80),
        }
        self._application = application
        self._inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._outbox: asyncio.Queue[tuple[float, float, dict[str, Any]]] = asyncio.Queue()
        self._task: asyncio.Task[Any] | None = None

    async def _send(self, message: dict[str, Any]) -> None:
        await self._outbox.put((time.perf_counter(), time.time(), message))

    async def open(self, within: float) -> None:
        """Offer the connection; `Refused` (exit 2) unless the door accepts it."""
        self._task = asyncio.create_task(self._application(self.scope, self._inbox.get, self._send))
        await self._inbox.put({"type": "websocket.connect"})
        _, _, answer = await asyncio.wait_for(self._outbox.get(), within)
        if answer["type"] != "websocket.accept":
            raise Refused(f"the socket door refused the probe: {answer!r}")

    async def frame(self, deadline: float) -> tuple[float, float, dict[str, Any]] | None:
        """The next text frame and when it was sent (perf, wall), or `None` past `deadline`."""
        while (left := deadline - time.perf_counter()) > 0:
            try:
                stamp, wall, message = await asyncio.wait_for(self._outbox.get(), left)
            except TimeoutError:
                return None
            if message["type"] == "websocket.close":
                raise Refused(f"the socket closed mid-run: {message!r}")
            if message["type"] == "websocket.send" and message.get("text"):
                return stamp, wall, json.loads(message["text"])
        return None

    async def close(self) -> None:
        """Hang up and let the consumer finish its disconnect."""
        await self._inbox.put({"type": "websocket.disconnect", "code": 1000})
        if self._task is not None:
            await asyncio.wait([self._task])


class WireSocket:
    """One RFC 6455 client socket, standard library only; each frame stamped as it is read."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._reader = reader
        self._writer = writer

    async def _send(self, opcode: int, payload: bytes) -> None:
        mask = os.urandom(4)
        head = bytes([0x80 | opcode])
        size = len(payload)
        if size < 126:
            head += bytes([0x80 | size])
        elif size < 1 << 16:
            head += bytes([0x80 | 126]) + struct.pack("!H", size)
        else:
            head += bytes([0x80 | 127]) + struct.pack("!Q", size)
        self._writer.write(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))
        await self._writer.drain()

    async def _read(self) -> tuple[bool, int, bytes]:
        first, second = await self._reader.readexactly(2)
        size = second & 0x7F
        if size == 126:
            (size,) = struct.unpack("!H", await self._reader.readexactly(2))
        elif size == 127:
            (size,) = struct.unpack("!Q", await self._reader.readexactly(8))
        mask = await self._reader.readexactly(4) if second & 0x80 else b""
        data = await self._reader.readexactly(size)
        if mask:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        return bool(first & 0x80), first & 0x0F, data

    async def frame(self, deadline: float) -> tuple[float, float, dict[str, Any]] | None:
        """The next text message and when its last byte arrived (perf, wall), or `None`."""
        parts: list[bytes] = []
        while (left := deadline - time.perf_counter()) > 0:
            try:
                fin, opcode, data = await asyncio.wait_for(self._read(), left)
            except TimeoutError:
                return None
            except (asyncio.IncompleteReadError, OSError) as exc:
                raise Refused(f"the socket dropped mid-run: {type(exc).__name__}: {exc}") from exc
            if opcode == 0x8:
                code = struct.unpack("!H", data[:2])[0] if len(data) >= 2 else None
                raise Refused(f"the socket closed mid-run (code {code})")
            if opcode == 0x9:
                await self._send(0xA, data)
                continue
            if opcode in (0x1, 0x0):
                parts.append(data)
                if fin:
                    stamp, wall = time.perf_counter(), time.time()
                    return stamp, wall, json.loads(b"".join(parts).decode("utf-8"))
        return None

    async def close(self) -> None:
        """Send a close frame and drop the connection."""
        try:
            await self._send(0x8, struct.pack("!H", 1000))
            self._writer.close()
            await self._writer.wait_closed()
        except (OSError, ssl.SSLError):
            pass


class WireDoors:
    """The REST door over `http.client` and the socket door over `WireSocket`, at `--base-url`."""

    def __init__(self, base_url: str, *, ca_bundle: str, resolve: dict[str, str]) -> None:
        parts = urllib.parse.urlsplit(base_url)
        self.secure = parts.scheme == "https"
        self.host = parts.hostname or "localhost"
        self.port = parts.port or (443 if self.secure else 80)
        self.address = resolve.get(self.host, self.host)
        self.context = ssl.create_default_context(cafile=ca_bundle or None) if self.secure else None

    def _call(self, method: str, path: str, token: str, tenant: str, body: object) -> Any:
        conn: http.client.HTTPConnection
        if self.context is not None:
            conn = http.client.HTTPSConnection(
                self.host, self.port, timeout=30, context=self.context
            )
        else:
            conn = http.client.HTTPConnection(self.host, self.port, timeout=30)
        address = self.address
        conn._create_connection = lambda where, *a, **k: socket.create_connection(  # type: ignore[attr-defined]
            (address, where[1]), *a, **k
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Tenant": tenant,
            "Accept": "application/json",
        }
        payload = None
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        try:
            conn.request(method, path, body=payload, headers=headers)
            response = conn.getresponse()
            raw = response.read()
        except (OSError, http.client.HTTPException) as exc:
            raise Refused(f"{method} {path} did not answer: {type(exc).__name__}: {exc}") from exc
        finally:
            conn.close()
        try:
            return response.status, (json.loads(raw) if raw else {})
        except ValueError:
            return response.status, {"raw": raw[:200].decode("latin-1")}

    async def call(
        self, method: str, path: str, *, token: str, tenant: str, body: object = None
    ) -> tuple[int, dict[str, Any]]:
        result: tuple[int, dict[str, Any]] = await asyncio.to_thread(
            self._call, method, path, token, tenant, body
        )
        return result

    async def socket(self, *, token: str, tenant: str, within: float) -> Socket:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(
                    self.address,
                    self.port,
                    ssl=self.context,
                    server_hostname=self.host if self.context is not None else None,
                ),
                within,
            )
        except (OSError, TimeoutError) as exc:
            raise Refused(f"the socket door did not answer: {type(exc).__name__}: {exc}") from exc
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {SOCKET_PATH} HTTP/1.1\r\nHost: {self.host}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
            f"Authorization: Bearer {token}\r\nX-Tenant: {tenant}\r\n\r\n"
        )
        writer.write(request.encode("latin-1"))
        await writer.drain()
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), within)
        status = head.split(b"\r\n", 1)[0].decode("latin-1")
        if " 101 " not in f"{status} ":
            writer.close()
            raise Refused(f"the socket door refused the probe: {status}")
        return WireSocket(reader, writer)


def occurred_epoch(frame: dict[str, Any]) -> float:
    """The frame's own `occurred_at` as epoch seconds; `Refused` when it carries none."""
    raw = frame.get("occurred_at")
    try:
        return datetime.fromisoformat(str(raw)).timestamp()
    except ValueError as exc:
        raise Refused(f"a {WIDGET_TOUCHED} frame carried no readable occurred_at: {raw!r}") from exc


async def heard(socket: Socket, *, widget_id: str, deadline: float) -> tuple[float, float] | None:
    """When this widget's next touched frame reached the socket and its lag since `occurred_at`."""
    while (arrived := await socket.frame(deadline)) is not None:
        stamp, wall, frame = arrived
        payload = frame.get("payload") or {}
        if frame.get("name") == WIDGET_TOUCHED and payload.get("id") == widget_id:
            return stamp, (wall - occurred_epoch(frame)) * 1000
    return None


@dataclass
class Measured:
    """Milliseconds: press to frame and `occurred_at` to frame per frame, the press's own trip."""

    lags: list[float] = field(default_factory=list)
    commits: list[float] = field(default_factory=list)
    trips: list[float] = field(default_factory=list)


async def measure(
    *,
    open_socket: Callable[[int], Awaitable[Socket]],
    press: Callable[[], Awaitable[tuple[float, float]]],
    widget_id: str,
    sockets: int,
    events: int,
    within: float,
) -> Measured:
    """Every frame's two lags and every press's round trip; `Refused` on any miss."""
    held = [await open_socket(n) for n in range(sockets)]
    measured = Measured()
    lags = measured.lags
    try:
        for n in range(1, events + 1):
            pressed, trip_ms = await press()
            measured.trips.append(trip_ms)
            deadline = time.perf_counter() + within
            arrivals = await asyncio.gather(
                *(heard(s, widget_id=widget_id, deadline=deadline) for s in held)
            )
            missed = sum(1 for a in arrivals if a is None)
            if missed:
                raise Refused(
                    f"{missed} of {sockets} sockets missed press {n} within {within}s; "
                    f"{len(lags)} of {sockets * events} frames arrived "
                    "(is the worker up on this checkout's task queue?)"
                )
            lags.extend((a[0] - pressed) * 1000 for a in arrivals if a is not None)
            measured.commits.extend(a[1] for a in arrivals if a is not None)
    finally:
        for s in held:
            await s.close()
    return measured


def report(
    measured: Measured, *, options: argparse.Namespace, basis: dict[str, Any], out: TextIO
) -> None:
    """The `realtime=` line, or the one `value`/`basis`/`instrument` JSON line."""
    lags = measured.lags
    value = {
        "p95_commit_ms": Decimal(f"{nearest_rank(measured.commits, 95):.1f}"),
        "p95_door_ms": Decimal(f"{nearest_rank(measured.trips, 95):.1f}"),
        "p50_ms": Decimal(f"{nearest_rank(lags, 50):.1f}"),
        "p95_ms": Decimal(f"{nearest_rank(lags, 95):.1f}"),
        "max_ms": Decimal(f"{max(lags):.1f}"),
    }
    relay = basis["relay_poll_seconds"]
    basis = {
        "events": options.events,
        "sockets": options.sockets,
        "frames": len(lags),
        "path": "dispatch",
        "fallback": f"relay every {relay}s" if relay else "relay (interval unread)",
        "load": options.load,
        "client": options.client,
        "formula_commit": FORMULA_COMMIT,
        "clock": options.clock or CLOCK_UNDECLARED,
        **basis,
    }
    instrument = (
        f"deploy/load/realtime_lag.py --sockets {options.sockets} --events {options.events}"
    )
    if options.json:
        line = {
            "value": {key: str(number) for key, number in value.items()},
            "basis": basis,
            "instrument": instrument,
        }
        print(json.dumps(line, sort_keys=True), file=out)
        return
    print(
        f"realtime=p95_commit_ms={value['p95_commit_ms']} p95_ms={value['p95_ms']} "
        f"p95_door_ms={value['p95_door_ms']} p50_ms={value['p50_ms']} max_ms={value['max_ms']} "
        f"sockets={options.sockets} events={options.events} load={options.load} "
        f"client={options.client} path=dispatch relay_poll_seconds={relay} "
        f"basis={len(lags)}-frames-over-{options.sockets}-sockets-x-{options.events}-presses "
        f"clock={options.clock or 'undeclared'}",
        file=out,
    )


def read_credentials(path: str) -> list[tuple[str, str]]:
    """`--credentials`: a JSON list of `{"tenant", "token"}`, every one in one tenant."""
    try:
        rows = [(str(c["tenant"]), str(c["token"])) for c in json.loads(Path(path).read_text())]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise Refused(f"could not read the credentials in {path}: {type(exc).__name__}") from exc
    if not rows or len({tenant for tenant, _ in rows}) != 1:
        raise Refused(f"{path} names no credential, or credentials in more than one tenant")
    return rows


def run_doors(options: argparse.Namespace, transport: Transport | None, out: TextIO) -> None:
    """The door mode: a probe widget made over REST, `--sockets` bearer sockets, REST presses."""
    per_credential, per_tenant = declared_socket_caps(options.settings_py)
    creds = read_credentials(options.credentials)
    tenant = creds[0][0]
    if options.sockets > per_credential * len(creds) or options.sockets > per_tenant:
        raise Refused(
            f"--sockets {options.sockets} over {len(creds)} credential(s) is above the join bound "
            f"(REALTIME_MAX_SOCKETS_PER_CREDENTIAL={per_credential}, "
            f"REALTIME_MAX_SOCKETS_PER_TENANT={per_tenant}); name more credentials"
        )
    if transport is None:
        if not options.base_url:
            raise Refused("the door mode needs --base-url")
        resolve = dict(pair.split(":", 1) for pair in options.resolve)
        transport = WireDoors(options.base_url, ca_bundle=options.ca_bundle, resolve=resolve)
    doors = transport
    presser = creds[0][1]

    async def go() -> Measured:
        status, made = await doors.call(
            "POST",
            f"{API}/widgets/",
            token=presser,
            tenant=tenant,
            body={"name": f"{PROBE_NAME} {time.strftime(STAMP, time.gmtime())}-{os.getpid()}"},
        )
        if status not in (200, 201) or "id" not in made:
            raise Refused(f"POST {API}/widgets/ answered {status}: {made}")
        widget_id = str(made["id"])

        async def open_socket(n: int) -> Socket:
            return await doors.socket(
                token=creds[n % len(creds)][1], tenant=tenant, within=options.within
            )

        async def press() -> tuple[float, float]:
            pressed = time.perf_counter()
            status, body = await doors.call(
                "POST", f"{API}/widgets/{widget_id}/touch/", token=presser, tenant=tenant
            )
            if status != 200:
                raise Refused(f"the touch answered {status}: {body}")
            return pressed, (time.perf_counter() - pressed) * 1000

        return await measure(
            open_socket=open_socket,
            press=press,
            widget_id=widget_id,
            sockets=options.sockets,
            events=options.events,
            within=options.within,
        )

    measured = asyncio.run(go())
    basis = {
        "formula": FORMULA_DOOR,
        "formula_door": FORMULA_DOOR_TRIP,
        "relay_poll_seconds": declared_relay_seconds(options.activities_py),
        "tenant": tenant,
        "credentials": len(creds),
    }
    report(measured, options=options, basis=basis, out=out)


def run_orm(options: argparse.Namespace, out: TextIO) -> None:
    """The in-process mode: ORM presses, sockets signed in by session on the ASGI app."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
    import django

    django.setup()
    from asgiref.sync import async_to_sync
    from django.conf import settings
    from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
    from django.contrib.sessions.backends.base import SessionBase
    from django.db import transaction
    from django.utils.module_loading import import_string

    from apps.core import context
    from apps.core.asyncdb import run_db
    from apps.core.discovery import declared_by
    from apps.example.models import Widget
    from apps.example.services import create_widget, touch_widget
    from pilecap import Actor
    from pilecap.accounts import User
    from pilecap.tenancy import Membership, Tenant

    per_credential = int(settings.REALTIME_MAX_SOCKETS_PER_CREDENTIAL)
    if options.sockets > per_credential:
        raise Refused(
            f"--sockets {options.sockets} is above REALTIME_MAX_SOCKETS_PER_CREDENTIAL="
            f"{per_credential} for the one member this mode signs in; use --credentials"
        )
    tenants = Tenant.objects.order_by("created_at")
    tenant = (
        tenants.filter(slug=options.tenant.strip().lower()).first()
        if options.tenant
        else tenants.first()
    )
    if tenant is None:
        raise Refused(f"No tenant {options.tenant or '(none exists)'}.")
    memberships = Membership.objects.for_tenant(tenant).select_related("user", "organization")
    if options.email:
        user = User.objects.filter(email=options.email.strip().lower()).first()
        member = memberships.of(user).first() if user is not None else None
    else:
        member = memberships.filter(role="owner").order_by("created_at").first()
    if member is None:
        raise Refused(f"No member to sign in as in {tenant.slug}.")
    actor = Actor(
        user=member.user, token=None, kind="human", tenant=tenant, org=member.organization
    )
    widget = (
        Widget.objects.for_tenant(tenant)
        .visible_to(actor)
        .filter(organization=actor.org)
        .order_by("-created_at")
        .first()
    ) or create_widget(tenant=tenant, actor=actor, name=PROBE_NAME)
    session: SessionBase = import_string(f"{settings.SESSION_ENGINE}.SessionStore")()
    session[SESSION_KEY] = member.user._meta.pk.value_to_string(member.user)
    session[BACKEND_SESSION_KEY] = settings.AUTHENTICATION_BACKENDS[0]
    session[HASH_SESSION_KEY] = member.user.get_session_auth_hash()
    session.save()
    headers = [
        (b"cookie", f"{settings.SESSION_COOKIE_NAME}={session.session_key}".encode()),
        (b"x-tenant", tenant.slug.encode()),
    ]

    def press_once() -> tuple[float, float]:
        started = time.perf_counter()
        committed: list[float] = []

        def stamp_commit() -> None:
            committed.append(time.perf_counter())

        with transaction.atomic():
            # rule-92: the probe's commit stamp, registered first so it runs first
            transaction.on_commit(stamp_commit)
            touch_widget(tenant=tenant, actor=actor, widget=widget)
        return committed[0], (time.perf_counter() - started) * 1000

    async def open_socket(n: int) -> Socket:
        held = InProcessSocket(import_string(settings.ASGI_APPLICATION), headers)
        await held.open(options.within)
        return held

    async def press() -> tuple[float, float]:
        stamp: tuple[float, float] = await run_db(press_once)
        return stamp

    try:
        with context.bound(
            request_id=context.new_id(),
            correlation_id=context.new_correlation_id(),
            actor_kind="system",
            door="shell",
            command="realtime_lag",
        ):
            measured = async_to_sync(measure)(
                open_socket=open_socket,
                press=press,
                widget_id=str(widget.pk),
                sockets=options.sockets,
                events=options.events,
                within=options.within,
            )
    finally:
        session.delete()
    relay = None
    for declaration in declared_by("events", "activities", "SCHEDULES") or ():
        if declaration.name == RELAY_SCHEDULE:
            spec = declaration.schedule(settings.TEMPORAL_TASK_QUEUE).spec
            relay = int(spec.intervals[0].every.total_seconds())
    basis = {
        "formula": FORMULA_ORM,
        "formula_door": FORMULA_ORM_TRIP,
        "relay_poll_seconds": relay,
        "channel_layer": str(settings.CHANNEL_LAYERS["default"]["BACKEND"]),
        "tenant": tenant.slug,
    }
    report(measured, options=options, basis=basis, out=out)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="realtime_lag.py", description=__doc__.splitlines()[0])
    parser.add_argument("--events", type=int, default=20, help="How many presses to time.")
    parser.add_argument(
        "--sockets", type=int, default=1, help="Sockets that must each hear every press."
    )
    parser.add_argument(
        "--within", type=float, default=60.0, help="Seconds for every frame of a press."
    )
    parser.add_argument("--json", action="store_true", help="One value/basis/instrument line.")
    parser.add_argument(
        "--load", default="idle", help="What load the line was taken under, e.g. conc-8."
    )
    parser.add_argument(
        "--client", default="in-process", help="Where the probe ran, e.g. drive-box."
    )
    parser.add_argument(
        "--clock",
        default="",
        help="The boxes' clock offsets as declared, e.g. web=+0.000012s,drive=-0.000034s.",
    )
    parser.add_argument(
        "--tenant", default=None, help="In-process: tenant slug; the oldest when omitted."
    )
    parser.add_argument(
        "--email", default=None, help="In-process: the member; the tenant's first owner."
    )
    parser.add_argument(
        "--credentials", default="", help="Door mode: a JSON list of {tenant, token}."
    )
    parser.add_argument("--base-url", default="", help="Door mode: where the doors answer.")
    parser.add_argument(
        "--ca-bundle", default="", help="Door mode: the PEM the edge's certificate chains to."
    )
    parser.add_argument(
        "--resolve", action="append", default=[], help="Door mode: host:address, repeatable."
    )
    parser.add_argument("--settings-py", default=str(BASE_PY), help=argparse.SUPPRESS)
    parser.add_argument("--activities-py", default=str(ACTIVITIES_PY), help=argparse.SUPPRESS)
    return parser


def run(argv: Sequence[str], out: TextIO, transport: Transport | None = None) -> None:
    """Parse, then the door mode when credentials are named, else the in-process mode."""
    options = build_parser().parse_args(argv)
    if options.events < 1 or options.sockets < 1:
        raise Refused("--events and --sockets must each be at least 1.")
    if options.credentials:
        run_doors(options, transport, out)
    else:
        run_orm(options, out)


def main(argv: Sequence[str], out: TextIO = sys.stdout, transport: Transport | None = None) -> int:
    """Exit 0 measured · 2 could not look, its sentence on stderr."""
    try:
        run(argv, out, transport)
    except Refused as exc:
        print(f"!! realtime_lag COULD NOT LOOK: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
