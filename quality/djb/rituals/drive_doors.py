"""The doors drive: a noun and each child it records on REST and MCP; the noun held to its event."""

# does-not-cover: a noun whose create needs a body beyond its schema's published examples.
# does-not-cover: the socket and the webhook — they carry the event's envelope around the payload.
# does-not-cover: a personal field below the top level — `x-personal` marks are read flat.
# does-not-cover: a run parked on a signal or a timer writes later; the drive reads before it does.
# does-not-cover: a verb whose effect is only an event reads `no field moved`, like a no-op would.

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import stat
import subprocess
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from quality.could_not_look import CouldNotLook, tool_said

ROOT = Path(__file__).resolve().parents[3]
OPENAPI = "/api/v1/openapi.json"
MCP_URL = "/mcp"
MCP_HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}
PROTOCOL_VERSION = "2025-06-18"
PERSONAL = "x-personal"
PAGES = 5
NOUN = re.compile(r"^[A-Z][A-Za-z0-9]*$")
TOKEN_PREFIX = "drive-doors"  # noqa: S105 — the name prefix of the drive's minted test tokens
SETTLE_SECONDS = 30.0
SETTLE_POLL = 0.25
PROBE_SECONDS = 3.0
RESTART = "./scripts/kill_mine.sh --kill, then ./scripts/serve.sh"
CLOSED, PARKED, BUSY = "closed", "parked", "busy"
USAGE = """\
usage: drive_doors.sh <Noun> [--preflight] [--base <url>] [--tenant <slug>] [--email <person>]

  On the running stack with the worker up (./scripts/serve.sh, ./scripts/worker.sh)
  and the seeded tenant (manage.py seed): create a <Noun> over REST from its
  published examples, patch one field, list it with a filter on REST and on its MCP
  twin, and read the event the patch recorded. Each write's runs settle first —
  closed, or parked on a signal or a timer — so a run's own write is never a
  disagreement. Each child the noun records (`<noun>_<child>-record`) is recorded
  under the row and listed on REST and its MCP twin. Each verb it mounts is
  pressed once and what moved is read back. Before any token, the server must
  serve this checkout's database and the seed rows exist (`--preflight` stops
  there). A token per run, `drive-doors-<utc stamp>`, revoked at the end. Prints
  every body, then `doors agree: <Noun> · <child>… · verbs: <verb>…` or the
  first key where two parted.

exit: 0 doors agree · 1 two doors disagree · 2 refused, or could not look.
"""


class CouldNotDrive(CouldNotLook):
    """Exit 2: the stack, the seed or the published document could not be driven."""


def out(text: str = "") -> None:
    print(text, flush=True)


def snake(noun: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", noun).lower()


@dataclass
class Document:
    raw: dict[str, Any]
    ops: dict[str, tuple[str, str, dict[str, Any]]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for path, methods in self.raw.get("paths", {}).items():
            for method, op in methods.items():
                if isinstance(op, dict) and op.get("x-url-name"):
                    self.ops[str(op["x-url-name"])] = (method.upper(), path, op)

    def op(self, url_name: str) -> tuple[str, str, dict[str, Any]]:
        if url_name not in self.ops:
            raise CouldNotDrive(f"the published document mounts no `{url_name}` operation")
        return self.ops[url_name]

    def schema(self, ref_or_schema: Mapping[str, Any]) -> dict[str, Any]:
        ref = ref_or_schema.get("$ref")
        if not ref:
            return dict(ref_or_schema)
        found: dict[str, Any] = self.raw["components"]["schemas"][str(ref).rsplit("/", 1)[1]]
        return found

    def body_schema(self, op: Mapping[str, Any]) -> dict[str, Any]:
        content = op.get("requestBody", {}).get("content", {}).get("application/json", {})
        return self.schema(content.get("schema", {}))

    def answer_schema(self, op: Mapping[str, Any]) -> dict[str, Any]:
        for status, answer in sorted(op.get("responses", {}).items()):
            if str(status).startswith("2"):
                content = answer.get("content", {}).get("application/json", {})
                return self.schema(content.get("schema", {}))
        return {}


def example(prop: Mapping[str, Any]) -> Any:
    if "example" in prop:
        return prop["example"]
    examples = prop.get("examples")
    return examples[0] if isinstance(examples, list) and examples else None


def is_text(prop: Mapping[str, Any]) -> bool:
    kinds = [prop, *prop.get("anyOf", [])]
    return any(
        k.get("type") == "string" and not ({"format", "enum", "pattern"} & set(k)) for k in kinds
    )


def marked(value: Any, prop: Mapping[str, Any], mark: str) -> Any:
    """A text example made this run's own, inside its `maxLength`."""
    if not isinstance(value, str) or not is_text(prop):
        return value
    room = int(prop.get("maxLength", 10_000))
    return f"{value} {mark}"[:room]


def create_body(schema: Mapping[str, Any], mark: str) -> dict[str, Any]:
    """Every required property at its published example, text made this run's own."""
    props: dict[str, Any] = schema.get("properties", {})
    body: dict[str, Any] = {}
    for name in schema.get("required", []):
        value = example(props.get(name, {}))
        if value is None:
            raise CouldNotDrive(f"the create body's `{name}` publishes no example to send")
        body[name] = marked(value, props[name], mark)
    return body


def patch_body(
    schema: Mapping[str, Any], row: Mapping[str, Any], avoid: set[str], mark: str
) -> dict[str, Any]:
    """One optional text field at its example, and the row's `version` when the Patch takes one."""
    props: dict[str, Any] = schema.get("properties", {})
    chosen = next(
        (
            name
            for name, prop in props.items()
            if name not in avoid
            and name != "version"
            and is_text(prop)
            and example(prop) is not None
        ),
        None,
    )
    if chosen is None:
        raise CouldNotDrive("the Patch publishes no text field with an example to change")
    body = {chosen: marked(example(props[chosen]), props[chosen], f"patched {mark}")}
    if "version" in props:
        body["version"] = row.get("version")
    return body


def list_filter(op: Mapping[str, Any], sent: Mapping[str, Any]) -> dict[str, Any]:
    """The list's query parameters that name a field the create sent, at the value it sent."""
    names = {str(p.get("name")) for p in op.get("parameters", []) if p.get("in") == "query"}
    return {name: value for name, value in sent.items() if name in names}


def personal_keys(schema: Mapping[str, Any], document: Document) -> set[str]:
    """The top-level properties the published `Out` marks personal."""
    props: dict[str, Any] = document.schema(schema).get("properties", {})
    return {name for name, prop in props.items() if prop.get(PERSONAL)}


def item_schema(page: Mapping[str, Any], document: Document) -> dict[str, Any]:
    items = page.get("properties", {}).get("items", {}).get("items", {})
    return document.schema(items)


def structured(answer: httpx.Response) -> dict[str, Any]:
    """A `tools/call` answer's `structuredContent`, from JSON or one `data:` frame."""
    text = answer.text
    if "text/event-stream" in answer.headers.get("content-type", ""):
        frames = [ln[5:].strip() for ln in text.splitlines() if ln.startswith("data:")]
        text = frames[-1] if frames else "{}"
    said: dict[str, Any] = json.loads(text)
    result = said.get("result") or {}
    if said.get("error") or result.get("isError"):
        raise CouldNotDrive(f"the MCP door refused: {json.dumps(said)[:300]}")
    content: dict[str, Any] = result.get("structuredContent") or {}
    return content


def rpc(method: str, params: dict[str, Any], request_id: int) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


async def mcp(
    client: httpx.AsyncClient, headers: dict[str, str], name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """`initialize`, then one `tools/call`; its `structuredContent`."""
    hello = {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "drive-doors", "version": "1"},
    }
    said = await client.post(MCP_URL, headers=headers, json=rpc("initialize", hello, 1))
    if said.status_code != 200:
        raise CouldNotDrive(f"the MCP handshake answered {said.status_code}: {said.text[:200]}")
    called = await client.post(
        MCP_URL, headers=headers, json=rpc("tools/call", {"name": name, "arguments": arguments}, 2)
    )
    if called.status_code != 200:
        raise CouldNotDrive(f"`{name}` answered {called.status_code}: {called.text[:200]}")
    return structured(called)


async def twin(client: httpx.AsyncClient, headers: dict[str, str], op: Mapping[str, Any]) -> str:
    """The MCP tool publishing this operation's contract: its title is the operation's summary."""
    said = await client.post(MCP_URL, headers=headers, json=rpc("tools/list", {}, 3))
    text = said.text
    if "text/event-stream" in said.headers.get("content-type", ""):
        text = next(ln[5:] for ln in reversed(text.splitlines()) if ln.startswith("data:"))
    tools = json.loads(text).get("result", {}).get("tools", [])
    summary = str(op.get("summary", ""))
    named = [t["name"] for t in tools if str(t.get("description", "")).split("\n")[0] == summary]
    if len(named) != 1:
        raise CouldNotDrive(f"no one MCP tool publishes `{summary}` — found {named or 'none'}")
    return str(named[0])


def find(items: Sequence[Mapping[str, Any]], row_id: str) -> dict[str, Any] | None:
    return next((dict(i) for i in items if str(i.get("id")) == row_id), None)


@dataclass
class Pressed:
    path: str
    tool: str
    answer: dict[str, Any]
    moved: list[str]


@dataclass
class Drive:
    bodies: dict[str, dict[str, Any]] = field(default_factory=dict)
    event: str = ""
    personal: set[str] = field(default_factory=set)
    noun: str = ""
    children: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    document: Document | None = None
    row_id: str = ""
    pressed: dict[str, Pressed] = field(default_factory=dict)
    not_pressed: list[str] = field(default_factory=list)


EventReader = Callable[[str], Awaitable[tuple[str, dict[str, Any]]]]
RunRef = tuple[str, str]


@dataclass
class Runs:
    """The runs this drive's writes started, and how far along each one is."""

    started: Callable[[], Awaitable[list[RunRef]]]
    probe: Callable[[RunRef], Awaitable[str]]
    bound: float = SETTLE_SECONDS


def run_state(raw: Any) -> str:
    """`closed`, `parked` (running, nothing scheduled: a signal or a timer) or `busy`."""
    from temporalio.api.enums.v1 import WorkflowExecutionStatus

    if (
        raw.workflow_execution_info.status
        != WorkflowExecutionStatus.WORKFLOW_EXECUTION_STATUS_RUNNING
    ):
        return CLOSED
    pending = (
        raw.pending_activities,
        raw.pending_children,
        raw.pending_nexus_operations,
        raw.HasField("pending_workflow_task"),
    )
    return BUSY if any(pending) else PARKED


async def settle(runs: Runs) -> list[RunRef]:
    """Poll until every run the drive started is closed or parked; could-not-look past the bound."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + runs.bound
    while True:
        refs = await runs.started()
        busy = [ref for ref in refs if await runs.probe(ref) == BUSY]
        if not busy:
            return refs
        if loop.time() >= deadline:
            workflow_id, run_id = busy[0]
            raise CouldNotDrive(
                f"run {workflow_id} (run id {run_id or 'none yet'}) did not settle within "
                f"{runs.bound:g} s — next: ./scripts/worker.sh"
            )
        await asyncio.sleep(SETTLE_POLL)


async def listed(
    client: httpx.AsyncClient,
    head: dict[str, str],
    path: str,
    narrowed: dict[str, Any],
    row_id: str,
) -> dict[str, Any] | None:
    """`row_id`'s item on a REST list under `narrowed`, paging up to `PAGES` pages."""
    query: dict[str, Any] = dict(narrowed)
    for _ in range(PAGES):
        page = (await client.get(path, headers=head, params=query)).json()
        found = find(page.get("items", []), row_id)
        if found is not None or not page.get("next_cursor"):
            return found
        query = {**narrowed, "cursor": page["next_cursor"]}
    return None


async def drive_child(
    client: httpx.AsyncClient,
    head: dict[str, str],
    document: Document,
    record: str,
    parent: tuple[str, str],
) -> dict[str, dict[str, Any]]:
    """One child row recorded under the noun's row, listed on REST and on its MCP twin."""
    method, path, op = document.op(record)
    word, row_id = parent
    sent = {**create_body(document.body_schema(op), ""), f"{word}_id": row_id}
    made = await client.request(method, path, headers=head, json=sent)
    if made.status_code not in (200, 201):
        raise CouldNotDrive(f"{method} {path} answered {made.status_code}: {made.text[:300]}")
    recorded: dict[str, Any] = made.json()
    child_id = str(recorded["id"])
    listing = next(
        (o for m, p, o in document.ops.values() if m == "GET" and p == path),
        None,
    )
    if listing is None:
        raise CouldNotDrive(f"the published document lists nothing at GET {path} beside `{record}`")
    narrowed = list_filter(listing, sent)
    found = await listed(client, head, path, narrowed, child_id)
    if found is None:
        raise CouldNotDrive(f"GET {path} with {narrowed or 'no filter'} never listed {child_id}")
    machine = {**head, **MCP_HEADERS}
    tool = await twin(client, machine, listing)
    told = await mcp(client, machine, tool, dict(narrowed))
    over_mcp = find(told.get("items", []), child_id)
    if over_mcp is None:
        raise CouldNotDrive(f"MCP `{tool}` with {narrowed or 'no filter'} never listed {child_id}")
    return {
        f"rest {path}?{'&'.join(f'{k}=…' for k in narrowed)}": found,
        f"mcp {tool}": over_mcp,
        f"rest {method} {path}": recorded,
    }


async def drive(
    client: httpx.AsyncClient, token: str, noun: str, read_event: EventReader, runs: Runs
) -> Drive:
    """Create, settle, patch, settle, list on both doors and read the event; the bodies."""
    head = {"authorization": f"Bearer {token}", "accept": "application/json"}
    published = await client.get(OPENAPI, headers=head)
    if published.status_code != 200:
        raise CouldNotDrive(f"{OPENAPI} answered {published.status_code}")
    document = Document(published.json())
    word = snake(noun)
    mark = f"drive-{secrets.token_hex(3)}"
    method, path, create = document.op(f"{word}-create")
    sent = create_body(document.body_schema(create), mark)
    made = await client.request(method, path, headers=head, json=sent)
    if made.status_code not in (200, 201):
        raise CouldNotDrive(f"{method} {path} answered {made.status_code}: {made.text[:300]}")
    row = made.json()
    row_id = str(row["id"])
    await settle(runs)
    if f"{word}-detail" in document.ops:
        _, path, _ = document.op(f"{word}-detail")
        again = await client.get(re.sub(r"\{[^}]+\}", row_id, path), headers=head)
        if again.status_code == 200:
            row = again.json()
    method, path, update = document.op(f"{word}-update")
    path = re.sub(r"\{[^}]+\}", row_id, path)
    change = patch_body(document.body_schema(update), row, set(sent), mark)
    patched = await client.request(method, path, headers=head, json=change)
    if patched.status_code != 200:
        raise CouldNotDrive(f"{method} {path} answered {patched.status_code}: {patched.text[:300]}")
    await settle(runs)
    _, path, listing = document.op(f"{word}-list")
    narrowed = list_filter(listing, sent)
    found = await listed(client, head, path, narrowed, row_id)
    if found is None:
        raise CouldNotDrive(f"GET {path} with {narrowed or 'no filter'} never listed {row_id}")
    machine = {**head, **MCP_HEADERS}
    tool = await twin(client, machine, listing)
    told = await mcp(client, machine, tool, dict(narrowed))
    over_mcp = find(told.get("items", []), row_id)
    if over_mcp is None:
        raise CouldNotDrive(f"MCP `{tool}` with {narrowed or 'no filter'} never listed {row_id}")
    event_name, payload = await read_event(row_id)
    result = Drive(event=event_name, noun=noun, document=document, row_id=row_id)
    result.bodies = {
        f"rest {path}?{'&'.join(f'{k}=…' for k in narrowed)}": found,
        f"mcp {tool}": over_mcp,
        f"rest PATCH {sorted(k for k in change if k != 'version')}": patched.json(),
        f"event {event_name}": dict(payload),
    }
    result.personal = personal_keys(
        item_schema(document.answer_schema(listing), document), document
    )
    for record in sorted(n for n in document.ops if re.fullmatch(rf"{word}_[a-z0-9_]+-record", n)):
        result.children[record.removesuffix("-record")] = await drive_child(
            client, head, document, record, (word, row_id)
        )
    return result


def family_words() -> frozenset[str]:
    """The noun-verb family's road names and verbs (`core.verbs.ROADS`): not the noun's own."""
    from apps.core.verbs import ROADS

    return frozenset({*ROADS, *(verb for road in ROADS.values() for verb in road.grants)})


def declared_verbs(
    document: Document, word: str, family: frozenset[str]
) -> list[tuple[str, tuple[str, str, dict[str, Any]]]]:
    """`(verb, op)` per `POST …/{id}/<verb>/` mounted as `<word>-<verb>`, family verbs aside."""
    found = []
    for name, (method, path, op) in document.ops.items():
        verb = name.removeprefix(f"{word}-")
        if (
            name.startswith(f"{word}-")
            and method == "POST"
            and verb not in family
            and re.search(rf"/\{{[^}}]+\}}/{re.escape(verb)}/$", path)
        ):
            found.append((verb, (method, path, op)))
    return sorted(found)


def verb_body(
    schema: Mapping[str, Any], row: Mapping[str, Any]
) -> tuple[dict[str, Any] | None, list[str]]:
    """A verb's body from its required examples and the row's `version`; else what lacks one."""
    props: dict[str, Any] = schema.get("properties", {})
    body: dict[str, Any] = {}
    needs: list[str] = []
    for name in schema.get("required", []):
        value = row.get("version") if name == "version" else example(props.get(name, {}))
        if value is None:
            needs.append(name)
        body[name] = value
    if "version" in props:
        body["version"] = row.get("version")
    return (None, needs) if needs else (body, [])


async def press_verbs(
    client: httpx.AsyncClient, token: str, result: Drive, runs: Runs, family: frozenset[str]
) -> None:
    """Press each declared verb once on REST, settle, and read back which fields it moved."""
    document = result.document
    if document is None:
        raise CouldNotDrive("the drive kept no published document to read the verbs from")
    head = {"authorization": f"Bearer {token}", "accept": "application/json"}
    machine = {**head, **MCP_HEADERS}
    word = snake(result.noun)
    verbs = declared_verbs(document, word, family)
    if not verbs:
        return
    _, detail, _ = document.op(f"{word}-detail")
    detail = re.sub(r"\{[^}]+\}", result.row_id, detail)

    async def read() -> dict[str, Any]:
        answered = await client.get(detail, headers=head)
        if answered.status_code != 200:
            raise CouldNotDrive(f"GET {detail} answered {answered.status_code}")
        row: dict[str, Any] = answered.json()
        return row

    for verb, (method, path, op) in verbs:
        before = await read()
        body, needs = verb_body(document.body_schema(op), before)
        if body is None:
            result.not_pressed.append(f"{verb} (needs {', '.join(needs)})")
            continue
        tool = await twin(client, machine, op)
        url = re.sub(r"\{[^}]+\}", result.row_id, path)
        sent = body if "requestBody" in op else None
        answered = await client.request(method, url, headers=head, json=sent)
        if answered.status_code >= 500:
            raise CouldNotDrive(
                f"{method} {url} answered {answered.status_code}: {answered.text[:300]}"
            )
        if answered.status_code >= 300:
            code = answered.json().get("code", "") if answered.content else ""
            result.not_pressed.append(f"{verb} (answered {answered.status_code} {code})".strip())
            continue
        await settle(runs)
        after = await read()
        moved = sorted(
            k
            for k in before.keys() | after.keys()
            if k != "allowed_acts" and before.get(k) != after.get(k)
        )
        result.pressed[verb] = Pressed(url, tool, answered.json(), moved)


def say_verbs(result: Drive) -> None:
    """Each pressed verb's answer and the fields it moved; each verb not pressed, and why."""
    for verb, pressed in result.pressed.items():
        out(f"== rest POST {pressed.path}")
        out(json.dumps(pressed.answer, indent=2, sort_keys=True, default=str))
        moved = f"moved {', '.join(pressed.moved)}" if pressed.moved else "no field moved"
        out(f"-- pressed {verb} (mcp {pressed.tool}): {moved}")
    for why in result.not_pressed:
        out(f"-- not pressed: {why}")


def verdict(result: Drive) -> str:
    """`doors agree: <Noun> · <child>… · verbs: <pressed>…`."""
    named = [result.noun or "the noun", *result.children]
    if result.pressed:
        named.append(f"verbs: {', '.join(result.pressed)}")
    return f"doors agree: {' · '.join(named)}"


def judge(result: Drive) -> str | None:
    """Why the doors disagree — the four-doors driver's first differing key — or None."""
    from pydantic import Field, create_model

    from apps.core.schemas import personal
    from apps.core.tests.doors import assert_four_doors

    rest, over_mcp, patched, payload = result.bodies.values()
    fields: dict[str, Any] = {
        key: (Any, Field(default=None, json_schema_extra=personal())) for key in result.personal
    }
    published = create_model("PublishedOut", **fields)
    try:
        assert_four_doors(rest=rest, mcp=over_mcp, event_payload=payload, out=published)
        assert_four_doors(rest=patched, mcp=rest, event_payload=payload, out=published)
    except AssertionError as parted:
        return str(parted)
    from apps.core.tests.doors import first_difference

    for child, bodies in result.children.items():
        rest, over_mcp, recorded = bodies.values()
        if (split := first_difference(rest, over_mcp)) is not None:
            return f"{child} — REST and MCP disagree for one viewer — {split}"
        if (split := first_difference(rest, recorded)) is not None:
            return f"{child} — the list is not the row the record answered — {split}"
    return None


def report(result: Drive) -> int:
    """The four bodies, then `doors agree` or the first key two of them parted on."""
    shown = [result.bodies, *result.children.values()]
    for title, body in ((title, body) for bodies in shown for title, body in bodies.items()):
        out(f"== {title}")
        out(json.dumps(body, indent=2, sort_keys=True, default=str))
    say_verbs(result)
    why = judge(result)
    if why is None:
        out(verdict(result))
        return 0
    out(f"doors disagree: {why}")
    return 1


def live_event_reader(tenant: Any, owner: Any) -> Callable[[str], tuple[str, dict[str, Any]]]:
    """The newest event naming this row, through the events selector, as `(name, payload)`."""
    from apps.core.actor import actor_for
    from apps.events.selectors import list_events

    def read(row_id: str) -> tuple[str, dict[str, Any]]:
        actor = actor_for(user=owner, tenant=tenant)
        rows = list_events(tenant=tenant, actor=actor).filter(payload__id=row_id)
        event = rows.order_by("-created_at").first()
        if event is None:
            raise CouldNotDrive(f"no event recorded naming {row_id}")
        return str(event.name), dict(event.payload)

    return read


def live_runs(tenant: Any, owner: Any, since: datetime) -> Runs:
    """The owner's runs started since `since`, probed on this checkout's Temporal."""
    from asgiref.sync import sync_to_async
    from temporalio.client import Client
    from temporalio.service import RPCError, RPCStatusCode

    from apps.workflows.client import get_client
    from apps.workflows.models import WorkflowRun

    def started() -> list[RunRef]:
        rows = WorkflowRun.objects.for_tenant(tenant).filter(
            started_by=owner, started_at__gte=since
        )
        return [(str(w), str(r)) for w, r in rows.values_list("workflow_id", "run_id")]

    held: list[Client] = []

    async def probe(ref: RunRef) -> str:
        if not held:
            try:
                held.append(await get_client())
            except Exception as gone:  # the SDK's connect error is a bare RuntimeError
                raise CouldNotDrive(f"Temporal answered no connect ({gone})") from gone
        try:
            described = await held[0].get_workflow_handle(ref[0], run_id=ref[1] or None).describe()
        except RPCError as missing:
            if missing.status == RPCStatusCode.NOT_FOUND:
                return BUSY
            raise
        return run_state(described.raw_description)

    return Runs(started=sync_to_async(started), probe=probe)


@dataclass
class DriveToken:
    name: str
    plaintext: str
    revoked_stale: list[str]


def open_token(tenant: Any, owner: Any) -> DriveToken:
    """Revoke the owner's leftover drive tokens, then mint this run's `drive-doors-<utc stamp>`."""
    from apps.core.tests.wire import bearer

    stale = [close_token(tenant, owner, t.name) for t in leftover_tokens(owner)]
    name = f"{TOKEN_PREFIX}-{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}"
    return DriveToken(name, bearer(user=owner, tenant=tenant, name=name), stale)


def leftover_tokens(owner: Any) -> list[Any]:
    from apps.accounts.models import ApiToken

    return list(
        ApiToken.objects.filter(
            user=owner, name__startswith=TOKEN_PREFIX, revoked_at__isnull=True
        ).order_by("created_at")
    )


def close_token(tenant: Any, owner: Any, name: str) -> str:
    """Revoke the owner's token `name`; answers the name."""
    from apps.accounts.models import ApiToken
    from apps.accounts.services import revoke_token
    from apps.core.actor import actor_for

    token = ApiToken.objects.get(user=owner, name=name)
    revoke_token(token=token, tenant=token.tenant, actor=actor_for(user=owner, tenant=tenant))
    return name


def base_url(root: Path) -> str:
    """This checkout's own serve address (`serve.sh --print-port`)."""
    done = subprocess.run(
        ["./scripts/serve.sh", "--print-port"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    port = done.stdout.strip()
    if done.returncode != 0 or not port.isdigit():
        raise CouldNotDrive(
            f"./scripts/serve.sh --print-port named no port{tool_said(done.stderr)}"
        )
    return f"http://127.0.0.1:{port}"


def setup_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
    import django

    django.setup()


def served_database(base: str) -> str:
    """The database the server at `base` names on `/readyz`; could-not-drive when none answers."""
    port = httpx.URL(base).port
    try:
        answered = httpx.get(f"{base}/readyz", timeout=PROBE_SECONDS)
    except httpx.TransportError as gone:
        raise CouldNotDrive(
            f"nothing serves at {base} ({type(gone).__name__}) — the server is not "
            "running — next: ./scripts/serve.sh and ./scripts/worker.sh in another shell"
        ) from gone
    try:
        said = answered.json()
    except ValueError:
        said = {}
    name = said.get("database") if isinstance(said, dict) else None
    if not isinstance(name, str) or not name:
        raise CouldNotDrive(
            f"the server on :{port} names no database on /readyz (it answered "
            f"{answered.status_code}; only a DEBUG server names one) — next: {RESTART}"
        )
    return name


def checkout_database() -> str:
    """This checkout's database, as its settings name it (`scripts/db.sh` exported it)."""
    setup_django()
    from django.conf import settings

    return str(settings.DATABASES["default"]["NAME"])


def seed_rows(tenant_slug: str, email: str) -> tuple[Any, Any]:
    """`manage.py seed`'s tenant and person; could-not-drive when either is absent."""
    from django.db import OperationalError

    from apps.accounts.models import User
    from apps.core.models import Tenant

    try:
        tenant = Tenant.objects.filter(slug=tenant_slug).first()
        owner = User.objects.filter(email=email).first()
    except OperationalError as gone:
        raise CouldNotDrive(
            f"this checkout's database answered no query ({type(gone).__name__}) "
            f"— next: ./scripts/setup.sh{tool_said(str(gone))}"
        ) from gone
    if tenant is None or owner is None:
        raise CouldNotDrive(
            f"no seed rows (no tenant `{tenant_slug}` or no person `{email}`) "
            "— next: uv run python manage.py seed"
        )
    return tenant, owner


def preconditions(base: str, tenant_slug: str, email: str) -> tuple[Any, Any, str]:
    """A server answering, on this checkout's database, and the seed rows — in that order."""
    served = served_database(base)
    derived = checkout_database()
    if served != derived:
        raise CouldNotDrive(
            f"the server on :{httpx.URL(base).port} serves {served}; this checkout derives "
            f"{derived} — next: {RESTART}"
        )
    tenant, owner = seed_rows(tenant_slug, email)
    return tenant, owner, served


def preflight(base: str, tenant_slug: str, email: str) -> int:
    """`--preflight`: the three preconditions, no token and no request beyond `/readyz`."""
    _, _, served = preconditions(base, tenant_slug, email)
    out(
        f"preflight: the server on :{httpx.URL(base).port} serves {served}, this checkout's "
        f"database; tenant {tenant_slug} and {email} are seeded"
    )
    return 0


def live(noun: str, base: str, tenant_slug: str, email: str) -> int:
    """The drive against the running stack, its preconditions met before a token is minted."""
    tenant, owner, _ = preconditions(base, tenant_slug, email)
    from asgiref.sync import sync_to_async

    token = open_token(tenant, owner)
    for name in token.revoked_stale:
        out(f"-- revoked `{name}`, a token an earlier drive left behind")

    async def run() -> Drive:
        reader, family = live_event_reader(tenant, owner), family_words()
        runs = live_runs(tenant, owner, datetime.now(UTC))
        async with httpx.AsyncClient(base_url=base, timeout=30) as client:
            try:
                await client.get(OPENAPI)
            except httpx.TransportError as gone:
                raise CouldNotDrive(
                    f"nothing serves at {base} ({type(gone).__name__}) — the server is not "
                    "running — next: ./scripts/serve.sh and ./scripts/worker.sh in another shell"
                ) from gone
            result = await drive(client, token.plaintext, noun, sync_to_async(reader), runs)
            await press_verbs(client, token.plaintext, result, runs, family)
            return result

    try:
        return report(asyncio.run(run()))
    finally:
        out(f"-- revoked `{close_token(tenant, owner, token.name)}`, this drive's token")


def piped() -> bool:
    if os.environ.get("CI"):
        return False
    try:
        return stat.S_ISFIFO(os.fstat(1).st_mode)
    except OSError:
        return False


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> int:
    """`drive_doors.sh <Noun>`: 0 doors agree · 1 they disagree · 2 refused or could not look."""
    words = list(sys.argv[1:] if argv is None else argv)
    if any(w in ("-h", "--help") for w in words):
        sys.stdout.write(USAGE)
        return 0
    if piped():
        print(
            "!! drive_doors.sh refuses pipes — run it bare or redirect to a file.", file=sys.stderr
        )
        return 2
    options = {"--base": "", "--tenant": "acme", "--email": "owner@example.com"}
    positional: list[str] = []
    checking = "--preflight" in words
    words = [w for w in words if w != "--preflight"]
    while words:
        word = words.pop(0)
        if word in options and words:
            options[word] = words.pop(0)
        elif word.startswith("--"):
            print(f"!! drive_doors.sh: {word} is no option\n{USAGE}", file=sys.stderr)
            return 2
        else:
            positional.append(word)
    if len(positional) != 1 or not NOUN.match(positional[0]):
        print(f"!! drive_doors.sh takes one PascalCase noun\n{USAGE}", file=sys.stderr)
        return 2
    try:
        base = options["--base"] or base_url(root)
        asked = " --preflight" if checking else ""
        out(f"== drive_doors {positional[0]}{asked} · {base} · tenant {options['--tenant']}")
        if checking:
            return preflight(base, options["--tenant"], options["--email"])
        return live(positional[0], base, options["--tenant"], options["--email"])
    except CouldNotDrive as stuck:
        out(f"could not drive: {stuck}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
