"""The presign refusal MATRIX, and the two stories, **driven over the doors**.

An earlier lane proved these properties at the SERVICE and STORAGE level:
`test_storage.py` signs, expires and tampers with URLs it minted itself.
A later verdict recorded the gap that leaves and this module is what closes it —
*"the presign refusal matrix was never driven through a door"*. The difference is
not pedantry: everything between a caller and `storage.presign_get` is a place a
key can be resolved wrong, a scope can be widened, or a refusal can be dressed
into something that leaks. A property proved one layer down is a property about
that layer.

So every row here starts at an HTTP request or a `tools/call` and ends at the
object store, with nothing of ours in between:

* **foreign tenant** — the door refuses, mints nothing, audits nothing, and the
  seam behind it would refuse to sign that key anyway;
* **expired** — a link this deployment's `FILES_DOWNLOAD_URL_TTL` made short is
  refused by MinIO in MinIO's own words, un-re-dressed;
* **wrong key** — the same link with one path segment changed is refused by
  MinIO, because the signature covers the key.

And the two stories the same lane never drove end to end: **download** (file it,
PUT the bytes, confirm, issue, fetch, digest-check) and **archive** (out of the
list, still readable, bytes still reachable, nothing new admitted).

**These tests reach the real MinIO in `compose.yaml`.** That makes them organ
tests (`apps/conftest.py`'s derivation, through the `bucket` fixture), which is
the honest cost: a matrix about what a store does with a signature cannot be
proved against a store that is not there.

**One link in the download chain is stood in for and it is named rather than
hidden.** `confirm` starts `FinalizeUpload`, and a Temporal worker is not running
here — so after the door has answered `202`, this module measures the object with
`storage.sha256_of` and records it with `services.record_stored`, which are *the
two calls the activity makes*, in that order (`activities.py::verify_object`,
`::record_stored`). What is not proved here is the workflow wiring, which has its
own `test_workflows.py`.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from apps.core.actor import actor_for
from apps.core.audit import AuditEntry
from apps.files import storage
from apps.files.models import FileVersion, StoredFile
from apps.files.services import create_file, record_stored

if TYPE_CHECKING:  # pragma: no cover - typing only
    from django.test import Client

    from apps.core.tests.permissions_world import World

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/files/"
DETAIL_URL = "/api/v1/files/{}/"
VERSIONS_URL = "/api/v1/files/{}/versions/"
CONFIRM_URL = "/api/v1/files/{}/versions/{}/confirm/"
DOWNLOAD_URL = "/api/v1/files/{}/download-url/"
ARCHIVE_URL = "/api/v1/files/{}/archive/"
JSON = "application/json"

BODY = b"the bytes a customer actually uploaded\n" * 512
DIGEST = hashlib.sha256(BODY).hexdigest()

#: The two headers a presigned PUT is signed for. Sent by every client that means
#: to succeed; omitting either is a signature mismatch rather than a lenient
#: upload, which `test_storage.py` proves in its own right.
UPLOAD_HEADERS = {"Content-Type": "application/pdf", "If-None-Match": "*"}


def _file_over_the_door(api: Client, *, filename: str = "invoice-2026-08.pdf") -> dict[str, Any]:
    """Step one of the story: ask the door for a document and somewhere to put it."""
    response = api.post(
        LIST_URL,
        data=json.dumps(
            {
                "filename": filename,
                "content_type": "application/pdf",
                "size_bytes": len(BODY),
                "purpose": "invoice",
            }
        ),
        content_type=JSON,
    )
    assert response.status_code == 201, response.content
    return dict(response.json())


def _finalize(world: World, version_id: str) -> FileVersion:
    """The two calls `FinalizeUpload`'s activities make, in order, with no worker.

    Named in the module docstring as the one stood-in link. Measured by
    `storage.sha256_of` — the platform's own instrument, reading the object back
    out of the store — so what gets recorded here is what got recorded there, and a
    store that had truncated the upload would be caught exactly as it would in
    production.
    """
    version = FileVersion.objects.for_tenant(world.tenant).get(pk=version_id)
    measured = storage.sha256_of(tenant=world.tenant, key=version.key)
    return record_stored(
        tenant=world.tenant,
        actor=actor_for(
            user=world.user(world.owner), tenant=world.tenant, org=version.organization
        ),
        version=version,
        sha256=measured.sha256,
        size_bytes=measured.size_bytes,
    )


@pytest.fixture
def a_stored_document(
    api: Client, world: World, bucket: str, recorded_workflow_starts: None
) -> tuple[StoredFile, FileVersion]:
    """The download story's first four steps, as fixture: file, PUT, confirm, measure.

    A fixture rather than a helper inside each test because four of the rows below
    all need a document whose bytes are really in the store, and re-driving the
    upload in each of them would make the module a test of the upload with several
    endings.
    """
    api.force_login(world.user(world.owner))
    ticket = _file_over_the_door(api)

    put = httpx.put(ticket["upload_url"], content=BODY, headers=UPLOAD_HEADERS, timeout=30)
    assert put.status_code == 200, put.text

    confirmed = api.post(
        CONFIRM_URL.format(ticket["file"]["id"], 1),
        data=json.dumps({"idempotency_key": "story-1"}),
        content_type=JSON,
    )
    assert confirmed.status_code == 202, confirmed.content

    version = _finalize(world, ticket["version"]["id"])
    document = StoredFile.objects.for_tenant(world.tenant).get(pk=ticket["file"]["id"])
    return document, version


# --- the download story, end to end -------------------------------------------


def test_the_download_story_end_to_end_over_the_door(
    api: Client, world: World, a_stored_document: tuple[StoredFile, FileVersion]
) -> None:
    """File it, upload it, confirm it, ask the door for it, and get the bytes back.

    The digest is the assertion that matters. Every earlier step could be right
    while the door signed a link to the wrong object — a neighbour's key, an old
    version's key, a key built from a stale row — and the only way to find that out
    is to fetch what the link points at and compare it to what was sent.

    The size is checked too, and separately: a store that served a truncated object
    would have a different digest, but a platform that RECORDED a truncated size
    while serving the whole object would not, and `size_bytes` is what the customer
    is metered on.
    """
    document, version = a_stored_document

    document.refresh_from_db()
    assert document.current_version == 1, "the measured version is the current one"
    assert version.sha256 == DIGEST
    assert version.size_bytes == len(BODY)

    issued = api.post(DOWNLOAD_URL.format(document.pk), data="{}", content_type=JSON)
    assert issued.status_code == 200, issued.content
    body = issued.json()
    assert body["version"] == 1
    assert body["sha256"] == DIGEST

    fetched = httpx.get(body["download_url"], timeout=30)

    assert fetched.status_code == 200, fetched.text
    assert fetched.content == BODY
    assert hashlib.sha256(fetched.content).hexdigest() == body["sha256"], (
        "the door published a digest that is not the digest of what its own link served"
    )


@pytest.fixture
def uploaded_for_the_machine(
    world: World, bucket: str, recorded_workflow_starts: None
) -> tuple[str, str]:
    """A document with its bytes really in the store, and a token to ask about it.

    **A SYNC fixture, and that is the load-bearing part.** The test below is
    `async def`, which means it runs with a live event loop in its thread, and
    Django refuses a synchronous query there. So every row this module needs is
    written out here — which is a property of the harness rather than of the doors,
    arranged once instead of worked around with `sync_to_async` inside the test.
    """
    from apps.accounts.services import issue_token

    acting = actor_for(user=world.user(world.owner), tenant=world.tenant, org=world.root)
    ticket = create_file(
        tenant=world.tenant,
        actor=acting,
        filename="machine.pdf",
        content_type="application/pdf",
        size_bytes=len(BODY),
        purpose="invoice",
    )
    put = httpx.put(ticket.upload_url, content=BODY, headers=UPLOAD_HEADERS, timeout=30)
    assert put.status_code == 200, put.text
    measured = storage.sha256_of(tenant=world.tenant, key=ticket.version.key)
    record_stored(
        tenant=world.tenant,
        actor=acting,
        version=ticket.version,
        sha256=measured.sha256,
        size_bytes=measured.size_bytes,
    )
    _, plaintext = issue_token(
        user=world.user(world.owner),
        tenant=world.tenant,
        name="machine-download",
        scopes=["*"],
        actor=actor_for(user=world.user(world.owner), tenant=world.tenant),
    )
    return str(ticket.file.pk), plaintext


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_machine_doors_link_really_serves_the_bytes_too(
    uploaded_for_the_machine: tuple[str, str],
) -> None:
    """The same last step, through `tools/call` — the machine door's link is usable.

    `test_doors_over_the_wire.py` proves the two doors sign the same PATH. That is
    the disagreement test and it would still pass if BOTH doors signed something
    the store refuses. So this fetches the bytes from a link an MCP client asked
    for, over the real ASGI application, and compares them to what was uploaded.
    """
    from apps.core.tests.test_mcp import MCP_HEADERS, PROTOCOL_VERSION, running
    from config.asgi import build_application

    file_id, plaintext = uploaded_for_the_machine
    application = build_application()
    headers = {**MCP_HEADERS, "authorization": f"Bearer {plaintext}"}
    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "files-story", "version": "1"},
                    },
                },
            )
            called = await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "issue_download_url",
                        "arguments": {"file_id": file_id},
                    },
                },
            )

    answered = called.json()
    assert "error" not in answered, answered
    link = answered["result"]["structuredContent"]

    fetched = httpx.get(link["download_url"], timeout=30)

    assert fetched.status_code == 200, fetched.text
    assert fetched.content == BODY
    assert link["sha256"] == DIGEST


# --- the archive story, end to end --------------------------------------------


def test_the_archive_story_end_to_end_over_the_door(
    api: Client, world: World, a_stored_document: tuple[StoredFile, FileVersion]
) -> None:
    """Archive it, and watch exactly four things happen and one thing not happen.

    Out of the list; still readable by id; **the bytes still fetchable**; nothing
    new admitted. The third is the one worth driving over the wire rather than
    asserting about a column: `StoredFile.lifecycle` says out loud that archiving
    is soft and THE OBJECTS STAY IN THE BUCKET, and a test that only checked
    `archived_at` would let that sentence rot into a false claim the day somebody
    "helpfully" deleted on archive. Here the residual is a fetched body.
    """
    document, version = a_stored_document
    api.force_login(world.user(world.owner))

    archived = api.post(ARCHIVE_URL.format(document.pk), data="{}", content_type=JSON)
    assert archived.status_code == 200, archived.content
    assert archived.json()["archived_at"] is not None

    listed = api.get(LIST_URL).json()
    assert str(document.pk) not in {one["id"] for one in listed["items"]}

    fetched_row = api.get(DETAIL_URL.format(document.pk))
    assert fetched_row.status_code == 200, fetched_row.content

    issued = api.post(DOWNLOAD_URL.format(document.pk), data="{}", content_type=JSON)
    assert issued.status_code == 200, issued.content
    bytes_back = httpx.get(issued.json()["download_url"], timeout=30)
    assert bytes_back.status_code == 200
    assert bytes_back.content == BODY, "archive is soft; the objects stay in the bucket"

    refused = api.post(
        VERSIONS_URL.format(document.pk),
        data=json.dumps({"content_type": "application/pdf", "size_bytes": 1}),
        content_type=JSON,
    )
    assert refused.status_code == 409, refused.content


# --- the matrix: foreign tenant ------------------------------------------------


def test_a_foreign_tenants_document_is_refused_and_its_key_cannot_be_signed(
    api: Client, world: World, neighbour: Any, a_stored_document: tuple[StoredFile, FileVersion]
) -> None:
    """Row one, both layers: the door refuses, and the seam could not have obliged.

    The door's `404` is the visible half and `test_api.py` drives it across every
    route. What this adds is the half a `404` cannot demonstrate on its own — that
    behind the refusal there is no world in which a link to that key gets minted
    for the wrong tenant. `storage.refuse_foreign_key` is that belt, and asserting
    it HERE, beside the door refusal, is what makes the pair a matrix row rather
    than two unrelated facts.

    Nothing is audited, because nothing was issued. An audit trail that recorded
    issuances which never happened would make "who has a link to this" wrong in the
    direction that matters.
    """
    document, version = a_stored_document
    api.force_login(world.user(world.owner))
    api.logout()
    api.force_login(neighbour.user)

    refused = api.post(DOWNLOAD_URL.format(document.pk), data="{}", content_type=JSON)

    assert refused.status_code == 404, refused.content
    assert refused.json()["code"] == "not_found"
    assert "download_url" not in refused.json()

    with pytest.raises(ValueError, match="tenant"):
        storage.presign_get(tenant=neighbour.tenant, key=version.key)

    assert (
        not AuditEntry.objects.for_tenant(neighbour.tenant)
        .filter(action="files.issue_download_url")
        .exists()
    )


# --- the matrix: expired -------------------------------------------------------


def test_an_expired_link_is_refused_by_the_store_in_its_own_words(
    api: Client,
    world: World,
    a_stored_document: tuple[StoredFile, FileVersion],
    settings: Any,
) -> None:
    """Row two, and it proves the TTL knob at the same time.

    `FILES_DOWNLOAD_URL_TTL` is set to one second and the DOOR reports
    `expires_in: 1` — which is the whole of that fix asserted from the outside:
    the setting reaches the signature and the number the caller is told comes from
    the call that signed it. Previously the pair were constants and an
    operator tuning `AWS_QUERYSTRING_EXPIRE` changed neither.

    Then the link is used, late, and **MinIO refuses it** — a `403` with the
    store's own body, not ours. There is nothing of this platform in that request
    path to dress it, which is the design being proved rather than described, and
    it is why the schema docstring's remedy is "ask again" rather than "look for a
    longer link".
    """
    document, _version = a_stored_document
    settings.FILES_DOWNLOAD_URL_TTL = 1
    api.force_login(world.user(world.owner))

    issued = api.post(DOWNLOAD_URL.format(document.pk), data="{}", content_type=JSON)
    assert issued.status_code == 200, issued.content
    body = issued.json()
    assert body["expires_in"] == 1, "the door reports the TTL it actually signed with"
    assert "X-Amz-Expires=1&" in body["download_url"] or body["download_url"].endswith(
        "X-Amz-Expires=1"
    ), body["download_url"]

    time.sleep(1.5)
    refused = httpx.get(body["download_url"], timeout=30)

    assert refused.status_code == 403, refused.text
    assert "AccessDenied" in refused.text or "Expired" in refused.text, refused.text
    assert "remedies" not in refused.text, "this refusal is the store's, un-re-dressed"


def test_the_default_ttl_is_what_the_deployment_configures(
    api: Client, world: World, a_stored_document: tuple[StoredFile, FileVersion], settings: Any
) -> None:
    """The other direction of the same knob: turn it up, and the signature follows.

    One-sided evidence would be weak here — a door hard-coded to report whatever it
    was handed would pass the test above. Two values, two signatures, and the
    number in the URL moving with the setting is what says the knob is wired to the
    thing it claims to govern.
    """
    document, _version = a_stored_document
    api.force_login(world.user(world.owner))

    settings.FILES_DOWNLOAD_URL_TTL = 60
    short = api.post(DOWNLOAD_URL.format(document.pk), data="{}", content_type=JSON).json()
    settings.FILES_DOWNLOAD_URL_TTL = 1800
    long = api.post(DOWNLOAD_URL.format(document.pk), data="{}", content_type=JSON).json()

    assert short["expires_in"] == 60
    assert long["expires_in"] == 1800
    assert "X-Amz-Expires=60" in short["download_url"]
    assert "X-Amz-Expires=1800" in long["download_url"]


# --- the matrix: wrong key -----------------------------------------------------


def test_a_link_whose_key_was_edited_is_refused_by_the_store(
    api: Client, world: World, a_stored_document: tuple[StoredFile, FileVersion]
) -> None:
    """Row three: the signature covers the key, so a nudged path is not a link.

    The threat is precise and it is the one a keyspace like `t/<tenant>/f/<file>/v/1`
    invites: somebody who has been given a legitimate link can *see the shape of
    the keyspace in it*, and the next thing they try is the neighbouring version,
    then the neighbouring document. Both are edited here and both are refused
    before a byte moves — by the store, with the store's own words, because SigV4
    covers the path and there is nothing of ours in the way to be persuaded.
    """
    document, version = a_stored_document
    api.force_login(world.user(world.owner))
    issued = api.post(DOWNLOAD_URL.format(document.pk), data="{}", content_type=JSON).json()
    link = issued["download_url"]
    assert version.key in link

    another_version = link.replace(version.key, version.key[:-1] + "2", 1)
    another_document = link.replace(str(document.pk), "0" * len(str(document.pk)), 1)

    for tampered, what in (
        (another_version, "a sibling version"),
        (another_document, "a sibling document"),
    ):
        refused = httpx.get(tampered, timeout=30)
        assert refused.status_code == 403, f"{what}: {refused.status_code} {refused.text}"

    still_works = httpx.get(link, timeout=30)
    assert still_works.status_code == 200, "the untampered link is the control"
    assert still_works.content == BODY
