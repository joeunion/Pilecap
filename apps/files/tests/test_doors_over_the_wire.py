"""The two doors answering one question, compared **on the wire** (house rule 46).

House rule 17 diffs two registries and proves the capability exists on both sides.
It cannot see the two doors DISAGREE about it, and both times they did in this
tree the finding came from a test of exactly this shape and from nothing else —
one case (REST renders a response by field name, the MCP transport renders
`structuredContent` by alias: one row, two key sets, every value equal) and another
(one consumer, one person, one `X-Org`, two credentials, two different sets of frames).

So this drives both doors through the one real ASGI application —
`config.asgi.build_application()`, the object `scripts/serve.sh` hands uvicorn —
over `httpx`, and compares `response.json()` against `result["structuredContent"]`,
**key set exact and then whole**. Nothing here calls a tool function: a tool
function returns a `StoredFileOut`, and the class of bug this exists for lives in
the serializer between that object and the client.

This app's subject gives the module a claim the worked example does not have: one
of the two shapes carries a **credential**. A presigned URL is signed with a
timestamp, so two issuances a second apart are two different strings and a naive
equality would be flaky — and a test that dropped the field to make the comparison
pass would be blind to the exact bug that matters, which is one door signing a
different KEY from the other. So `download_url` is compared the way
`apps/exports/tests/test_doors_over_the_wire.py` compares its own: split, and the
PATH asserted equal, which is the half that says which object the caller is being
sent to.

`transaction=True` because the MCP transport runs a tool body on a worker thread
with its own database connection, which cannot see an uncommitted row.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest

from apps.accounts.services import issue_token
from apps.core.actor import actor_for
from apps.core.tests.test_mcp import MCP_HEADERS, PROTOCOL_VERSION, running
from apps.files.models import FileVersion, StoredFile
from apps.files.services import create_file, record_stored
from apps.files.tests.conftest import World

#: House rule 46. The door pair this module answers for `apps/files`, read by the
#: gate off this module-level assignment. This app is born with its pair answered
#: — its two doors landed in one rung, so it has never been in the backlog
#: `rules.yaml` records and the number it would have started at is the number it
#: stays at: none owed.
DOOR_PAIR = ("rest", "mcp")

LIST_URL = "/api/v1/files/"
DETAIL_URL = "/api/v1/files/{}/"
DOWNLOAD_URL = "/api/v1/files/{}/download-url/"
MCP_URL = "/mcp"
JSON = "application/json"

DIGEST = "beadbead" * 8

# The wire shape at each level, written out rather than derived from the schemas —
# a pin taken from the thing it pins cannot fail. This is the REST contract
# and both doors are held to it, so a rename that reaches the wire has to change
# these lines in the diff.
DOCUMENT_KEYS = frozenset(
    {
        "id",
        "organization_id",
        "filename",
        "purpose",
        "current_version",
        "uploaded_by_id",
        "archived_at",
        "created_at",
        "updated_at",
    }
)
PAGE_KEYS = frozenset({"items", "has_more", "next_cursor", "count"})
DOWNLOAD_KEYS = frozenset(
    {
        "file_id",
        "version",
        "version_id",
        "download_url",
        "expires_in",
        "content_type",
        "size_bytes",
        "sha256",
    }
)


#: **RETIRED.** This module used to name the fields whose PRECISION the
#: two doors disagreed about, so every other key could be compared exactly while
#: these were compared by their moment. `config/mcp.py` now puts every
#: machine-door answer out through the HTTP door's own encoder, so the two doors
#: write the same bytes and there is no exception left to name.


def assert_same_document(*, over_mcp: dict[str, Any], over_rest: dict[str, Any]) -> None:
    """Two renderings of one document, value for value — **timestamps included**.

    Key by key rather than one dict equality, so a failure names the field a
    client would have to reconcile rather than printing two documents.
    """
    for key in over_rest:
        assert over_mcp[key] == over_rest[key], f"the two doors disagree about {key}"


def _rpc(method: str, params: dict[str, Any], request_id: int) -> dict[str, Any]:
    """One JSON-RPC request body, spelled the way a real MCP client spells it."""
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


@pytest.fixture
def seeded(
    recorded_workflow_starts: None, world: World, named_bucket: str
) -> tuple[StoredFile, FileVersion]:
    """One document with one measured version, written the way production writes them.

    `recorded_workflow_starts` first in the signature, and it is load-bearing: the
    commit is real in a `transaction=True` test, so the `emit` inside
    `record_stored` would otherwise dial a Temporal server this module has no
    reason to start.
    """
    acting = actor_for(user=world.owner, tenant=world.tenant, org=world.root)
    ticket = create_file(
        tenant=world.tenant,
        actor=acting,
        filename="invoice-2026-08.pdf",
        content_type="application/pdf",
        size_bytes=1024,
        purpose="invoice",
    )
    stored = record_stored(
        tenant=world.tenant,
        actor=acting,
        version=ticket.version,
        sha256=DIGEST,
        size_bytes=1024,
    )
    return ticket.file, stored


@pytest.fixture
def bearer(seeded: tuple[StoredFile, FileVersion], world: World) -> str:
    """A token scoped exactly to this section — minted in a SYNC fixture.

    Every ORM call this module makes happens out here rather than in the test body:
    an `async def` test runs with a live event loop in its thread, and Django
    refuses a synchronous query there. That is a property of the harness rather
    than of the doors, so it is arranged once and never worked around.
    """
    _, plaintext = issue_token(
        user=world.owner,
        tenant=world.tenant,
        name="door-parity",
        scopes=["files:read", "files:write"],
        actor=actor_for(user=world.owner, tenant=world.tenant),
    )
    return plaintext


@pytest.fixture
def read_only_bearer(seeded: tuple[StoredFile, FileVersion], world: World) -> str:
    """A token that may look and may not touch. The ceiling probe's subject."""
    _, plaintext = issue_token(
        user=world.owner,
        tenant=world.tenant,
        name="files-read",
        scopes=["files:read"],
        actor=actor_for(user=world.owner, tenant=world.tenant),
    )
    return plaintext


@pytest.fixture
def unscoped_bearer(seeded: tuple[StoredFile, FileVersion], world: World) -> str:
    """A token with no ceiling at all — the other half of the ceiling probe.

    Without it the probe proves only that SOMETHING refused, not that the ceiling
    is what refused: a route broken for every token would pass a one-sided test.
    """
    _, plaintext = issue_token(
        user=world.owner,
        tenant=world.tenant,
        name="files-unscoped",
        scopes=["*"],
        actor=actor_for(user=world.owner, tenant=world.tenant),
    )
    return plaintext


async def _initialize(client: httpx.AsyncClient, headers: dict[str, str], who: str) -> None:
    answered = await client.post(
        MCP_URL,
        headers=headers,
        json=_rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": who, "version": "1"},
            },
            1,
        ),
    )
    assert answered.status_code == 200, answered.text


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_put_the_same_document_on_the_wire(
    bearer: str, seeded: tuple[StoredFile, FileVersion]
) -> None:
    """One document, two doors: one key set, one body — on the row and on the page.

    Both, because they are two different renderings and only one of them is
    `StoredFileOut` by itself: the list goes through `@paginate` at the HTTP door
    and through `cursor_page` + `FilePage` at the machine one, which is exactly the
    seam where an envelope can come apart while every row inside it agrees.
    """
    from config.asgi import build_application

    document, _version = seeded
    application = build_application()
    credential = {"authorization": f"Bearer {bearer}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(
                DETAIL_URL.format(document.pk), headers={**credential, "accept": JSON}
            )
            listed_over_http = await client.get(LIST_URL, headers={**credential, "accept": JSON})

            headers = {**MCP_HEADERS, **credential}
            await _initialize(client, headers, "files-door-parity")
            called = await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc(
                    "tools/call",
                    {"name": "get_file", "arguments": {"file_id": str(document.pk)}},
                    2,
                ),
            )
            listed = await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc("tools/call", {"name": "list_files", "arguments": {}}, 3),
            )

    assert over_http.status_code == 200, over_http.text
    rest_body = over_http.json()
    answered = called.json()
    assert "error" not in answered, answered
    over_mcp = answered["result"]["structuredContent"]

    # (1) the REST body first, against the written-out contract: whatever the two
    # doors are made to agree on, they agree on *this*. Without this half a future
    # fix could reconcile them by moving REST, which is the one direction that
    # breaks a client.
    assert set(rest_body) == DOCUMENT_KEYS
    assert "key" not in rest_body, "where the bytes live is never on the wire"

    # (2) the two doors. Key sets first, because that is what actually diverged
    # before and because an equality failure on nested dicts says far less
    # than a key-set failure does.
    assert set(over_mcp) == set(rest_body), (
        "The two doors describe the same document with different keys. "
        f"Only on MCP: {sorted(set(over_mcp) - set(rest_body))}; "
        f"only on REST: {sorted(set(rest_body) - set(over_mcp))}. "
        "A `Field(alias=...)` on a read schema does this: the MCP transport "
        "serialises `structuredContent` by alias and REST renders by field name."
    )
    assert_same_document(over_mcp=over_mcp, over_rest=rest_body)

    # (3) the page, which is a second rendering and a second chance to disagree.
    # The envelope is compared whole and the rows one by one, because a page that
    # agreed about `has_more` while disagreeing about a row would pass a shallow
    # equality and be exactly the bug this module exists for.
    rest_page = listed_over_http.json()
    over_mcp_page = listed.json()["result"]["structuredContent"]
    assert set(rest_page) == PAGE_KEYS
    assert set(over_mcp_page) == set(rest_page)
    for key in set(rest_page) - {"items"}:
        assert over_mcp_page[key] == rest_page[key], f"the envelopes disagree about {key}"
    assert len(rest_page["items"]) == 1, "the agreement above is not two empty lists"
    assert len(over_mcp_page["items"]) == len(rest_page["items"])
    for mine, theirs in zip(over_mcp_page["items"], rest_page["items"], strict=True):
        assert set(mine) == DOCUMENT_KEYS
        assert_same_document(over_mcp=mine, over_rest=theirs)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_issue_the_same_link_for_the_same_version(
    bearer: str, seeded: tuple[StoredFile, FileVersion]
) -> None:
    """The app's own shape: same version, same key, same lifetime, two doors.

    Everything but the URL is compared whole. The URL is compared by its PATH,
    because the query string carries a signature over the moment it was made — two
    issuances milliseconds apart are legitimately two strings, and the thing that
    must never differ is **which object the caller is being sent to**.
    """
    from config.asgi import build_application

    document, version = seeded
    application = build_application()
    credential = {"authorization": f"Bearer {bearer}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.post(
                DOWNLOAD_URL.format(document.pk),
                headers={**credential, "accept": JSON, "content-type": JSON},
                json={},
            )

            headers = {**MCP_HEADERS, **credential}
            await _initialize(client, headers, "files-download-parity")
            called = await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc(
                    "tools/call",
                    {"name": "issue_download_url", "arguments": {"file_id": str(document.pk)}},
                    2,
                ),
            )

    assert over_http.status_code == 200, over_http.text
    rest_body = over_http.json()
    answered = called.json()
    assert "error" not in answered, answered
    over_mcp = answered["result"]["structuredContent"]

    assert set(rest_body) == DOWNLOAD_KEYS
    assert set(over_mcp) == set(rest_body)
    for key in set(rest_body) - {"download_url"}:
        assert over_mcp[key] == rest_body[key], key
    assert rest_body["version_id"] == str(version.pk)
    assert urlsplit(over_mcp["download_url"]).path == urlsplit(rest_body["download_url"]).path
    assert version.key in urlsplit(rest_body["download_url"]).path


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_refuse_a_document_neither_can_see_identically(
    bearer: str, seeded: tuple[StoredFile, FileVersion]
) -> None:
    """One refusal, two doors, and it is `not_found` at both.

    A document id that names nothing is the cheapest way to drive the grammar over
    the wire, and it is the same code path a foreign tenant's id takes — that
    equivalence is what `test_api.py` proves row by row. What THIS module adds is
    that the two doors say it the same way: a machine door that answered
    `forbidden` where the human door said `not_found` would be an oracle available
    to exactly the callers this platform hands tokens to.
    """
    from config.asgi import build_application

    application = build_application()
    credential = {"authorization": f"Bearer {bearer}"}
    nowhere = "00000000-0000-4000-8000-000000000000"

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.post(
                DOWNLOAD_URL.format(nowhere),
                headers={**credential, "accept": JSON, "content-type": JSON},
                json={},
            )

            headers = {**MCP_HEADERS, **credential}
            await _initialize(client, headers, "files-refusal-parity")
            called = await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc(
                    "tools/call",
                    {"name": "issue_download_url", "arguments": {"file_id": nowhere}},
                    2,
                ),
            )

    assert over_http.status_code == 404, over_http.text
    rest_body = over_http.json()
    assert rest_body["code"] == "not_found"
    assert "download_url" not in rest_body

    said = str(called.json())
    assert "not_found" in said, said
    assert "forbidden" not in said, "the machine door must not tell not-there from not-yours"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_refuse_the_same_narrow_token(
    read_only_bearer: str, unscoped_bearer: str, seeded: tuple[StoredFile, FileVersion]
) -> None:
    """The ceiling probe at the machine door, beside the one at the human door.

    A `files:read` token is refused on a WRITE at both doors, and both name
    `files:write` — an agent that is told "no" without the name of what to ask for
    cannot tell its human what to mint. The refusals are worded by two different
    composers (`config/api.py` and `core.mcp.tool_call`), which is exactly why the
    property is asserted on both rather than on one.

    And the unscoped token passes the same call, in the same run, which is what
    makes this a probe of the CEILING rather than of the route.
    """
    from config.asgi import build_application

    application = build_application()
    body = {"filename": "x.pdf", "content_type": "application/pdf", "size_bytes": 10}
    narrow = {"authorization": f"Bearer {read_only_bearer}"}
    wide = {"authorization": f"Bearer {unscoped_bearer}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            refused_http = await client.post(
                LIST_URL, headers={**narrow, "accept": JSON, "content-type": JSON}, json=body
            )
            allowed_http = await client.post(
                LIST_URL, headers={**wide, "accept": JSON, "content-type": JSON}, json=body
            )

            narrow_headers = {**MCP_HEADERS, **narrow}
            await _initialize(client, narrow_headers, "files-ceiling")
            refused_mcp = await client.post(
                MCP_URL,
                headers=narrow_headers,
                json=_rpc("tools/call", {"name": "create_file", "arguments": body}, 2),
            )

            wide_headers = {**MCP_HEADERS, **wide}
            await _initialize(client, wide_headers, "files-ceiling-wide")
            allowed_mcp = await client.post(
                MCP_URL,
                headers=wide_headers,
                json=_rpc("tools/call", {"name": "create_file", "arguments": body}, 2),
            )

    assert refused_http.status_code == 403, refused_http.text
    refused_body = refused_http.json()
    assert refused_body["code"] == "insufficient_scope"
    assert "files:write" in refused_body["detail"]
    assert allowed_http.status_code == 201, allowed_http.text

    said = str(refused_mcp.json())
    assert "insufficient_scope" in said, said
    assert "files:write" in said, said
    answered = allowed_mcp.json()
    assert "error" not in answered, answered
    assert answered["result"]["structuredContent"]["version"]["version"] == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_issuing_over_the_wire_is_audited_as_the_machine_door(
    bearer: str, seeded: tuple[StoredFile, FileVersion]
) -> None:
    """The audit door, and it can only be proved HERE.

    `door` is bound by the ASGI middleware (`config/mcp.py`) and not by `tool_call`,
    so a tool invoked as a function records an empty door — correctly, because
    nothing came through a door. The criterion is that BOTH rows exist and say which
    door they came through; the `door=rest` half is `test_api.py`'s and this is the
    other, driven over the real transport.

    The audit read happens through `run_db`, off the event loop: an `async def` test
    has a live loop in its thread and Django refuses a synchronous query there. That
    is the harness, not the doors.
    """
    from apps.core.asyncdb import run_db
    from apps.core.audit import AuditEntry
    from config.asgi import build_application

    document, version = seeded
    application = build_application()
    credential = {"authorization": f"Bearer {bearer}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            headers = {**MCP_HEADERS, **credential}
            await _initialize(client, headers, "files-audit-door")
            called = await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc(
                    "tools/call",
                    {"name": "issue_download_url", "arguments": {"file_id": str(document.pk)}},
                    2,
                ),
            )

    assert "error" not in called.json(), called.json()

    def rows() -> list[tuple[str, str, str]]:
        return [
            (entry.door, str(entry.input.get("version", "")), str(entry.input.get("file", "")))
            for entry in AuditEntry.objects.filter(action="files.issue_download_url")
        ]

    recorded = await run_db(rows)

    assert recorded == [
        ("mcp", f"files.FileVersion:{version.pk}", f"files.StoredFile:{document.pk}")
    ]


@pytest.fixture
def read_withheld(world: World) -> Any:
    """One `withhold` row on the token holder's own membership. **`file.read`, gone.**

    A withhold beats everything — "forbid overrides permit" — and it beats it
    for an owner too, which is what makes this the smallest world in which a
    perfectly ordinary credential is refused at both doors. Nothing about the
    role, the hat or the document changes: the only difference between this test
    and its neighbours is this row.
    """
    from apps.core.models import Grant, Membership

    membership = Membership.objects.filter(tenant=world.tenant).get(user=world.owner)
    return Grant.objects.create(
        tenant=world.tenant,
        membership=membership,
        permission="file.read",
        effect=Grant.Effect.WITHHOLD,
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_both_doors_refuse_the_same_withheld_read_with_the_same_words(
    bearer: str, seeded: tuple[StoredFile, FileVersion], read_withheld: Any
) -> None:
    """**PR4.f.2 — rule 46's named case for Phase R.**

    A read is a permission now (ADR core-27), so there is a new refusal on both
    doors, and a new refusal is exactly where two doors come apart: one composes
    a body and the other stringifies an exception. Both go through
    `core.exceptions.wire_refusal`, and this says so — the code AND the sentence,
    not just the status.

    The door driven is the ISSUANCE, deliberately: it is the one that mints a
    credential, so it is the one where "refused, and nothing was signed" matters
    most. Read beside the `not_found` case above, the pair is the whole claim —
    a document neither door can SEE is `not_found` at both, and one they can see
    but may not READ is `forbidden` at both, and the two stay different from
    each other in the same way at each door.

    *Absent (the baseline):* 200 at both, each carrying a signed `download_url`.
    """
    from apps.core.authz import refusal_sentence
    from config.asgi import build_application

    document, _version = seeded
    application = build_application()
    credential = {"authorization": f"Bearer {bearer}"}
    sentence = refusal_sentence("file.read")

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.post(
                DOWNLOAD_URL.format(document.pk),
                headers={**credential, "accept": JSON, "content-type": JSON},
                json={},
            )

            headers = {**MCP_HEADERS, **credential}
            await _initialize(client, headers, "files-read-parity")
            called = await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc(
                    "tools/call",
                    {"name": "issue_download_url", "arguments": {"file_id": str(document.pk)}},
                    2,
                ),
            )

    assert over_http.status_code == 403, over_http.text
    rest_body = over_http.json()
    assert rest_body["code"] == "forbidden"
    assert rest_body["detail"] == sentence
    assert "download_url" not in rest_body, "a URL was minted for a refused reader"

    said = str(called.json())
    assert "forbidden" in said, said
    assert sentence in said, said
    # Not `"download_url" not in said`: the TOOL is called `issue_download_url`
    # and its name is in its own error line. What must be absent is a signed
    # link, and a signed link is a URL.
    assert "http" not in said, "a URL was minted for a refused reader"
