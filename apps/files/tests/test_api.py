"""The HTTP half: the sixth door meets the house floor.

Scoped, filtered, ordered, paginated, pinned; strict on the way in; both tenancy
siblings present, because "another tenant's documents are absent" and "a sibling
branch's documents are absent" are two different claims and only the second one is
about the hierarchy.

And the two things this app's door has that no other has:

* **every "there are no bytes here" answer is `not_found`** — a document in
  another tenant, a version that does not exist, a version still uploading, and a
  document that has never had one finish are one answer on purpose, because a
  door that signs URLs must never be an oracle telling somebody their neighbour's
  document exists. The refusals are driven here in all four shapes;
* **issuance is audited against the VERSION**, not against the document, so the
  audit assertions read `input` rather than `object_id` and check the version by
  primary key.

Nothing in this module needs a real object store: `named_bucket` configures a
bucket NAME, and `presign_put`/`presign_get` are local HMAC computations over it.
What the store actually does with a URL — expiry, tampering, the belt — is
`test_presign_matrix.py`, which pays for MinIO because its subject IS the store.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from apps.core.actor import actor_for
from apps.core.audit import AuditEntry
from apps.files.models import FileVersion, StoredFile
from apps.files.services import archive_file, create_file, record_stored

if TYPE_CHECKING:  # pragma: no cover - typing only
    from django.test import Client

    from .conftest import World

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/files/"
DETAIL_URL = "/api/v1/files/{}/"
VERSIONS_URL = "/api/v1/files/{}/versions/"
CONFIRM_URL = "/api/v1/files/{}/versions/{}/confirm/"
DOWNLOAD_URL = "/api/v1/files/{}/download-url/"
ARCHIVE_URL = "/api/v1/files/{}/archive/"
JSON = "application/json"

#: Measured, not guessed, at seeded scale. The page itself plus the middleware and
#: session work an authenticated request pays: the list issues no `COUNT` (ADR
#: core-18 — `has_more` comes from fetching one row more than asked for), and
#: `select_related("organization", "uploaded_by")` is what keeps the two relations
#: `StoredFileOut` walks off the per-row path. Removing either would move this
#: number, which is the point.
#:
#: **7 → 10 in Phase R, and the three are named.** `file.read` is asked at the
#: hat inside `selectors.list_files`, and resolving what one person holds at one
#: node reads exactly three tables — their memberships in the tenant, the grants
#: on those memberships, the role-delta rows for the role keys — once per actor.
#: Once, not once per key: the actor carries the memo (PR0).
#:
#: **10 → 17 for `allowed_acts`, and the seven are named** (`ActsPagination`,
#: `core.verbs.with_allowed_acts`, measured on this fixture's three documents at
#: three nodes). The paginator resolves its own actor from the request, so the
#: collection the route's `file.read` memoized is read again — memberships,
#: grants, role keys (3). **17 → 13:** the four membership reads that followed —
#: one per NODE the page's rows sat at, and one at the hat for the list's own
#: `create` — were `membership_for` asking afresh, and it reads the actor's memo
#: now; and no row is offered `update` or `delete`, which have no door here. It
#: grows with nothing: not the nodes, not the rows.
LIST_QUERY_BUDGET = 13

#: The same for one document's version history. One statement more than the
#: document list, and the extra one is the document itself: the route resolves the
#: parent through the scoped selector before it lists anything, because a version
#: list for a document this hat cannot see has to answer `not_found` rather than
#: an empty page.
#:
#: **8 → 11 in Phase R, and it is the SAME three, once.** The route asks
#: `file.read` twice — once resolving the document, once listing its versions,
#: because a version is authorized as its document — and pays for one: the memo
#: is the actor's, so the second `require` reads no table. A door that had lost
#: the memo would be at 14 here and this number is what would say so.
VERSION_LIST_QUERY_BUDGET = 11

DIGEST = "beadbead" * 8


def _file_at(world: World, org: Any, *, filename: str, purpose: str = "upload") -> StoredFile:
    """One document filed at a named node of the tree, through the real service."""
    ticket = create_file(
        tenant=world.tenant,
        actor=actor_for(user=world.owner, tenant=world.tenant, org=org),
        filename=filename,
        content_type="application/pdf",
        size_bytes=1024,
        purpose=purpose,
    )
    return ticket.file


def _stored(world: World, file: StoredFile, *, version: int = 1) -> FileVersion:
    """Take one of a document's versions all the way to `stored`, measured.

    Through `record_stored` rather than by updating the row, so the status flip,
    the promotion, the meter and the event are the ones production writes — and so
    a test asserting that a download link exists is asserting over a version that
    became downloadable the way real ones do.
    """
    row = FileVersion.objects.for_tenant(world.tenant).get(file=file, version=version)
    return record_stored(
        tenant=world.tenant,
        actor=actor_for(user=world.owner, tenant=world.tenant, org=file.organization),
        version=row,
        sha256=DIGEST,
        size_bytes=1024,
    )


@pytest.fixture
def documents(world: World, named_bucket: str, recorded_workflow_starts: None) -> list[StoredFile]:
    """Three documents across the tree: one at the root, one at the region, one below."""
    return [
        _file_at(world, world.root, filename="root-invoice.pdf"),
        _file_at(world, world.region, filename="region-invoice.pdf", purpose="contract"),
        _file_at(world, world.branch, filename="branch-notes.txt"),
    ]


# --- the list -----------------------------------------------------------------


def test_the_list_answers_in_the_cursor_envelope(
    api: Client, world: World, documents: list[StoredFile]
) -> None:
    """ADR core-18's envelope, and `count` null until somebody asks for it."""
    api.force_login(world.owner)

    response = api.get(LIST_URL)

    assert response.status_code == 200, response.content
    body = response.json()
    assert set(body) == {"items", "has_more", "next_cursor", "count", "allowed_acts"}
    assert body["count"] is None, "a total costs a second statement; it is opt-in"
    assert len(body["items"]) == 3
    assert body["items"][0]["current_version"] == 0, "nothing has finished uploading yet"


def test_include_count_is_what_puts_the_total_on_the_wire(
    api: Client, world: World, documents: list[StoredFile]
) -> None:
    api.force_login(world.owner)

    body = api.get(LIST_URL, {"include_count": "true"}).json()

    assert body["count"] == 3


def test_another_tenants_documents_are_absent(
    api: Client,
    world: World,
    neighbour: Any,
    documents: list[StoredFile],
    named_bucket: str,
) -> None:
    """The tenancy sibling every list test in this repository owes."""
    create_file(
        tenant=neighbour.tenant,
        actor=neighbour,
        filename="globex-secret.pdf",
        content_type="application/pdf",
        size_bytes=10,
        purpose="upload",
    )
    api.force_login(world.owner)

    body = api.get(LIST_URL).json()

    assert len(body["items"]) == 3
    assert "globex-secret.pdf" not in {one["filename"] for one in body["items"]}


def test_a_branch_admin_sees_its_own_subtree_and_nothing_above_it(
    api: Client, world: World, documents: list[StoredFile]
) -> None:
    """The hierarchy sibling, which the tenancy one cannot see.

    The region's admin sees the region's document and the branch's beneath it, and
    does not see the root's — even though all three are in one tenant and all three
    are that tenant's own documents.
    """
    api.force_login(world.region_admin)

    body = api.get(LIST_URL, headers={"X-Org": world.region.slug}).json()

    names = {one["filename"] for one in body["items"]}
    assert names == {"region-invoice.pdf", "branch-notes.txt"}
    assert "root-invoice.pdf" not in names


def test_archived_documents_leave_the_list_and_stay_readable_by_id(
    api: Client, world: World, documents: list[StoredFile]
) -> None:
    """The two halves of ADR files-2's "archived excluded", which are not in tension.

    Archiving takes a document out of the working set. It does not un-say that the
    document exists to somebody who already has its id, and a `404` there would
    read as "this never existed" about a row that plainly did.
    """
    archived = documents[0]
    archive_file(tenant=world.tenant, actor=world.owner_actor, file=archived)
    api.force_login(world.owner)

    listed = api.get(LIST_URL).json()
    assert str(archived.pk) not in {one["id"] for one in listed["items"]}
    assert len(listed["items"]) == 2

    fetched = api.get(DETAIL_URL.format(archived.pk))
    assert fetched.status_code == 200, fetched.content
    assert fetched.json()["archived_at"] is not None


def test_the_purpose_filter_is_exact_and_the_filename_filter_is_not(
    api: Client, world: World, documents: list[StoredFile]
) -> None:
    """Two different matches, because the two fields are two different kinds of thing.

    `purpose` is a label somebody chose from their own small vocabulary, so a
    substring match would make `?purpose=contract` quietly mean
    `contract-amendment` too. `filename` is what a person remembers half of.
    """
    api.force_login(world.owner)

    assert len(api.get(LIST_URL, {"purpose": "contract"}).json()["items"]) == 1
    assert api.get(LIST_URL, {"purpose": "contr"}).json()["items"] == []
    assert len(api.get(LIST_URL, {"filename": "invoice"}).json()["items"]) == 2


def test_an_ordering_this_list_does_not_accept_is_refused(
    api: Client, world: World, documents: list[StoredFile]
) -> None:
    """Refused with the registry's envelope rather than quietly ignored."""
    api.force_login(world.owner)

    response = api.get(LIST_URL, {"ordering": "current_version"})

    assert response.status_code == 400, response.content
    assert response.json()["code"] == "invalid"


def test_the_list_query_budget(
    api: Client, world: World, documents: list[StoredFile], django_assert_num_queries: Any
) -> None:
    """The pin that turns a lost `select_related` into a failure, not a slow page."""
    api.force_login(world.owner)

    with django_assert_num_queries(LIST_QUERY_BUDGET):
        assert api.get(LIST_URL).status_code == 200


# --- the versions -------------------------------------------------------------


def test_the_version_list_shows_what_we_measured_and_what_we_have_not(
    api: Client, world: World, documents: list[StoredFile]
) -> None:
    """`null` and `""` while a version is pending, which is the honest answer.

    A zero size would read as a measurement of an empty object, and an empty object
    is a real thing somebody can upload.
    """
    api.force_login(world.owner)

    body = api.get(VERSIONS_URL.format(documents[0].pk)).json()

    assert [one["version"] for one in body["items"]] == [1]
    assert body["items"][0]["status"] == "pending"
    assert body["items"][0]["size_bytes"] is None
    assert body["items"][0]["sha256"] == ""


def test_the_version_list_query_budget(
    api: Client, world: World, documents: list[StoredFile], django_assert_num_queries: Any
) -> None:
    api.force_login(world.owner)

    with django_assert_num_queries(VERSION_LIST_QUERY_BUDGET):
        assert api.get(VERSIONS_URL.format(documents[0].pk)).status_code == 200


# --- filing, replacing, confirming --------------------------------------------


def test_filing_a_document_answers_with_a_ticket_and_a_signed_url(
    api: Client, world: World, named_bucket: str
) -> None:
    """201, the document, its first version, and somewhere to PUT the bytes.

    The URL is asserted to be a real signature over a real key rather than merely
    present: an `upload_url` that carried no `X-Amz-Signature` would be a link
    every client would follow and every store would refuse.
    """
    api.force_login(world.owner)

    response = api.post(
        LIST_URL,
        data=json.dumps(
            {
                "filename": "invoice-2026-08.pdf",
                "content_type": "application/pdf",
                "size_bytes": 41238,
                "purpose": "invoice",
            }
        ),
        content_type=JSON,
    )

    assert response.status_code == 201, response.content
    body = response.json()
    assert set(body) == {"file", "version", "upload_url", "expires_in"}
    assert body["file"]["current_version"] == 0
    assert body["version"]["version"] == 1
    assert body["version"]["status"] == "pending"
    assert body["expires_in"] == 900
    assert "X-Amz-Signature=" in body["upload_url"]
    assert "if-none-match" in body["upload_url"].lower(), "the overwrite belt is signed in"


def test_an_unknown_field_in_the_body_is_refused_naming_it(
    api: Client, world: World, named_bucket: str
) -> None:
    """`StrictIn`: a misspelled field is a refusal, never a silent drop.

    The failure this closes is the worst shape a platform whose callers are agents
    can have — a healthy `201` for a request that did not do what it said.
    """
    api.force_login(world.owner)

    response = api.post(
        LIST_URL,
        data=json.dumps(
            {
                "filename": "x.pdf",
                "content_type": "application/pdf",
                "size_bytes": 1,
                "purposes": "invoice",
            }
        ),
        content_type=JSON,
    )

    assert response.status_code == 422, response.content
    body = response.json()
    assert body["code"] == "invalid_body"
    assert "purposes" in json.dumps(body["errors"])
    assert not StoredFile.objects.for_tenant(world.tenant).exists()


def test_the_same_idempotency_key_files_one_document(
    api: Client, world: World, named_bucket: str
) -> None:
    """The identical request twice is one document, and the first answer twice.

    The replay is byte-identical — including the `upload_url`, which is the part
    that matters: a second signature for the same key would be a second write
    credential handed out for one act.
    """
    api.force_login(world.owner)
    payload = json.dumps(
        {"filename": "once.pdf", "content_type": "application/pdf", "size_bytes": 10}
    )
    headers = {"Idempotency-Key": "file-once"}

    first = api.post(LIST_URL, data=payload, content_type=JSON, headers=headers)
    second = api.post(LIST_URL, data=payload, content_type=JSON, headers=headers)

    assert first.status_code == 201, first.content
    assert second.status_code == 201, second.content
    assert first.json() == second.json()
    assert StoredFile.objects.for_tenant(world.tenant).count() == 1
    assert FileVersion.objects.for_tenant(world.tenant).count() == 1


def test_every_write_route_honours_the_idempotency_key(
    api: Client, world: World, documents: list[StoredFile], recorded_workflow_starts: None
) -> None:
    """Across ALL FOUR writes, not just the first one.

    The guard is `core.idempotency`'s middleware and it is uniform over every
    `POST` under `/api/`, so one drive would have been evidence about the
    middleware. What this is evidence about is that **this app's four write routes
    are inside that population** — a route that answered outside `/api/`, or with a
    status the record refuses to replay, would silently opt out and nothing else in
    the suite would say so.

    The assertion is the same in all four: the second answer is byte-identical to
    the first, and the world afterwards has one of whatever the first call made.
    """
    document = documents[0]
    api.force_login(world.owner)
    versions_before = FileVersion.objects.for_tenant(world.tenant).count()

    calls = {
        "file-create": (
            LIST_URL,
            json.dumps({"filename": "twice.pdf", "content_type": "text/plain", "size_bytes": 5}),
        ),
        "version-add": (
            VERSIONS_URL.format(document.pk),
            json.dumps({"content_type": "application/pdf", "size_bytes": 7}),
        ),
        "upload-confirm": (
            CONFIRM_URL.format(document.pk, 1),
            json.dumps({"idempotency_key": "confirm-twice"}),
        ),
        "file-archive": (ARCHIVE_URL.format(document.pk), "{}"),
    }

    for route, (url, payload) in calls.items():
        headers = {"Idempotency-Key": f"key-for-{route}"}
        first = api.post(url, data=payload, content_type=JSON, headers=headers)
        second = api.post(url, data=payload, content_type=JSON, headers=headers)
        assert first.status_code < 400, f"{route}: {first.status_code} {first.content!r}"
        assert second.status_code == first.status_code, route
        assert second.json() == first.json(), f"{route} did not replay its first answer"
        assert second.headers.get("Idempotent-Replayed") == "true", (
            f"{route} ran a second time instead of replaying — it is outside the "
            "middleware's population, or its answer was not replayable"
        )

    # One new document and one new version, from four calls made twice each.
    # `including_archived()`: the archive call above took one of them out of the
    # working set, and this counts documents, not the working set.
    assert (
        StoredFile.objects.for_tenant(world.tenant).including_archived().count()
        == len(documents) + 1
    )
    assert FileVersion.objects.for_tenant(world.tenant).count() == versions_before + 2


def test_replacing_adds_a_version_beside_the_old_one(
    api: Client, world: World, documents: list[StoredFile]
) -> None:
    """The replace verb: version 2 arrives, version 1 is exactly where it was."""
    document = documents[0]
    api.force_login(world.owner)

    response = api.post(
        VERSIONS_URL.format(document.pk),
        data=json.dumps({"content_type": "application/pdf", "size_bytes": 99}),
        content_type=JSON,
    )

    assert response.status_code == 201, response.content
    assert response.json()["version"]["version"] == 2
    versions = api.get(VERSIONS_URL.format(document.pk)).json()["items"]
    assert [one["version"] for one in versions] == [2, 1]
    document.refresh_from_db()
    assert document.current_version == 0, "promotion waits for the bytes to be measured"


def test_replacing_an_archived_document_is_refused_archived(
    api: Client, world: World, documents: list[StoredFile]
) -> None:
    """Archiving is what stops new versions arriving; this is that fence, at the door."""
    document = documents[0]
    archive_file(tenant=world.tenant, actor=world.owner_actor, file=document)
    api.force_login(world.owner)

    response = api.post(
        VERSIONS_URL.format(document.pk),
        data=json.dumps({"content_type": "application/pdf", "size_bytes": 99}),
        content_type=JSON,
    )

    assert response.status_code == 409, response.content
    assert response.json()["code"] == "archived"


def test_confirming_answers_202_and_starts_one_run(
    api: Client, world: World, documents: list[StoredFile], recorded_workflow_starts: None
) -> None:
    """202, still `pending`, and a verification run started once for that version.

    The `202` is the contract: nothing is stored because the platform has not been
    round and looked yet, and a `200` here would be a door claiming a fact it does
    not have.
    """
    from apps.workflows.models import WorkflowRun

    document = documents[0]
    api.force_login(world.owner)

    response = api.post(
        CONFIRM_URL.format(document.pk, 1),
        data=json.dumps({"idempotency_key": "upload-9f3c1"}),
        content_type=JSON,
    )

    assert response.status_code == 202, response.content
    assert response.json()["status"] == "pending"
    runs = WorkflowRun.objects.for_tenant(world.tenant).filter(type="FinalizeUpload")
    assert runs.count() == 1


def test_confirming_with_a_blank_key_is_refused(
    api: Client, world: World, documents: list[StoredFile]
) -> None:
    """A confirm with no key is a caller who has not thought about their own retries."""
    api.force_login(world.owner)

    response = api.post(
        CONFIRM_URL.format(documents[0].pk, 1),
        data=json.dumps({"idempotency_key": "   "}),
        content_type=JSON,
    )

    assert response.status_code == 400, response.content
    assert response.json()["code"] == "invalid"


# --- the refusal grammar ---------------------------------------------------------


def test_every_route_answers_not_found_for_another_tenants_document(
    api: Client, world: World, neighbour: Any, named_bucket: str, recorded_workflow_starts: None
) -> None:
    """**The whole door, one refusal.** Not-there and not-yours are the same answer.

    Driven over every route that names a document, because the grammar is only
    worth anything if it holds on all of them: one route that answered `403` would
    be the oracle the other five were built to avoid, and it would be the one an
    attacker used.
    """
    theirs = create_file(
        tenant=neighbour.tenant,
        actor=neighbour,
        filename="globex.pdf",
        content_type="application/pdf",
        size_bytes=10,
        purpose="upload",
    ).file
    api.force_login(world.owner)
    body = json.dumps({"content_type": "application/pdf", "size_bytes": 1})

    answers = {
        "detail": api.get(DETAIL_URL.format(theirs.pk)),
        "versions": api.get(VERSIONS_URL.format(theirs.pk)),
        "add-version": api.post(VERSIONS_URL.format(theirs.pk), data=body, content_type=JSON),
        "confirm": api.post(
            CONFIRM_URL.format(theirs.pk, 1),
            data=json.dumps({"idempotency_key": "k"}),
            content_type=JSON,
        ),
        "download-url": api.post(DOWNLOAD_URL.format(theirs.pk), data="{}", content_type=JSON),
        "archive": api.post(ARCHIVE_URL.format(theirs.pk), data="{}", content_type=JSON),
    }

    for where, response in answers.items():
        assert response.status_code == 404, f"{where}: {response.status_code} {response.content!r}"
        assert response.json()["code"] == "not_found", where


def test_a_sibling_branchs_document_is_not_found_either(
    api: Client, world: World, documents: list[StoredFile]
) -> None:
    """The hierarchy half of the same claim, which the tenancy half cannot see.

    The region's admin and the root document are in ONE tenant. Answering
    `403 forbidden` here would say "there is a document at this id and you may not
    have it", which is precisely the fact the scoping was hiding.
    """
    api.force_login(world.region_admin)

    response = api.post(
        DOWNLOAD_URL.format(documents[0].pk),
        data="{}",
        content_type=JSON,
        headers={"X-Org": world.region.slug},
    )

    assert response.status_code == 404, response.content
    assert response.json()["code"] == "not_found"


def test_asking_for_bytes_that_have_not_landed_is_not_found(
    api: Client, world: World, documents: list[StoredFile]
) -> None:
    """Three ways to have no bytes, one answer — the anti-oracle, driven.

    A document whose only version is still pending, and a version number that does
    not exist at all, answer identically. A caller can therefore learn "there is
    nothing to fetch" and nothing else.
    """
    document = documents[0]
    api.force_login(world.owner)

    current = api.post(DOWNLOAD_URL.format(document.pk), data="{}", content_type=JSON)
    pending = api.post(
        DOWNLOAD_URL.format(document.pk), data=json.dumps({"version": 1}), content_type=JSON
    )
    absent = api.post(
        DOWNLOAD_URL.format(document.pk), data=json.dumps({"version": 9}), content_type=JSON
    )

    assert current.status_code == pending.status_code == absent.status_code == 404
    assert current.json() == pending.json() == absent.json(), "byte-equal, or it is an oracle"


# --- issuance, and the audit row it is for ------------------------------------


def test_issuing_a_link_audits_the_version_it_signed_for(
    api: Client, world: World, documents: list[StoredFile], django_assert_num_queries: Any
) -> None:
    """One audit row per issuance, naming the version and the door.

    The version and not merely the document, because a document has many versions
    and "somebody was given a link to this document" does not answer which bytes
    they were given. `input` is where it lands — the service returns a ticket rather
    than a model, so `object_id` is empty by construction and `LOG_KEYS` carries the
    two rows instead.
    """
    document = documents[0]
    stored = _stored(world, document)
    api.force_login(world.owner)

    response = api.post(DOWNLOAD_URL.format(document.pk), data="{}", content_type=JSON)

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["version"] == 1
    assert body["version_id"] == str(stored.pk)
    assert body["expires_in"] == 300
    assert body["sha256"] == DIGEST
    assert "X-Amz-Signature=" in body["download_url"]

    rows = list(
        AuditEntry.objects.for_tenant(world.tenant).filter(action="files.issue_download_url")
    )
    assert len(rows) == 1, "one issuance, one row"
    assert rows[0].door == "rest"
    assert rows[0].outcome == "ok"
    assert rows[0].input["version"] == f"files.FileVersion:{stored.pk}"
    assert rows[0].input["file"] == f"files.StoredFile:{document.pk}"


def test_a_refused_issuance_leaves_no_audit_row_and_no_url(
    api: Client, world: World, neighbour: Any, named_bucket: str
) -> None:
    """The other half: nothing was issued, so nothing claims one was.

    The row would be worse than useless — an audit trail that recorded issuances
    that never happened would make the count of "who has a link to this" wrong in
    the direction that matters.
    """
    theirs = create_file(
        tenant=neighbour.tenant,
        actor=neighbour,
        filename="globex.pdf",
        content_type="application/pdf",
        size_bytes=10,
        purpose="upload",
    ).file
    api.force_login(world.owner)

    response = api.post(DOWNLOAD_URL.format(theirs.pk), data="{}", content_type=JSON)

    assert response.status_code == 404
    assert "download_url" not in response.json()
    for tenant in (world.tenant, neighbour.tenant):
        assert (
            not AuditEntry.objects.for_tenant(tenant)
            .filter(action="files.issue_download_url")
            .exists()
        )


def test_a_link_issued_for_an_old_version_still_names_that_version(
    api: Client, world: World, documents: list[StoredFile], recorded_workflow_starts: None
) -> None:
    """Version pinning, at the door: v1's link stays v1's after v2 is promoted.

    Asserted on the KEY inside the signed URL rather than on the ordinal alone,
    because the ordinal is what the door says and the key is what the store will
    serve. If promotion ever re-pointed a version's key, this is where it would
    show.
    """
    document = documents[0]
    first = _stored(world, document)
    api.force_login(world.owner)
    api.post(
        VERSIONS_URL.format(document.pk),
        data=json.dumps({"content_type": "application/pdf", "size_bytes": 2048}),
        content_type=JSON,
    )
    second = _stored(world, document, version=2)
    document.refresh_from_db()
    assert document.current_version == 2

    pinned = api.post(
        DOWNLOAD_URL.format(document.pk), data=json.dumps({"version": 1}), content_type=JSON
    ).json()
    current = api.post(DOWNLOAD_URL.format(document.pk), data="{}", content_type=JSON).json()

    assert pinned["version"] == 1
    assert first.key in pinned["download_url"]
    assert current["version"] == 2
    assert second.key in current["download_url"]


# --- archiving -----------------------------------------------------------------


def test_archiving_takes_a_role_and_a_member_is_refused(
    api: Client, world: World, documents: list[StoredFile]
) -> None:
    """The bar `policies.py` puts on archive, driven in the refusing direction.

    A permission that is only ever asserted in the affirmative is a permission
    nobody has proved refuses — and this one is `403 forbidden` rather than
    `404 not_found` on purpose: the member CAN see the document, so pretending it
    is not there would be a lie they can disprove in the next request.
    """
    document = _file_at(world, world.region, filename="region-only.pdf")
    api.force_login(world.plain_member)

    response = api.post(
        ARCHIVE_URL.format(document.pk),
        data="{}",
        content_type=JSON,
        headers={"X-Org": world.region.slug},
    )

    assert response.status_code == 403, response.content
    assert response.json()["code"] == "forbidden"
    document.refresh_from_db()
    assert document.archived_at is None


def test_an_administrator_may_archive_and_doing_it_twice_is_quiet(
    api: Client, world: World, documents: list[StoredFile]
) -> None:
    """The affirmative half, and the retry: one event, one timestamp, no refusal."""
    from apps.events.models import Event

    document = _file_at(world, world.region, filename="region-only.pdf")
    api.force_login(world.region_admin)
    headers = {"X-Org": world.region.slug}

    first = api.post(ARCHIVE_URL.format(document.pk), data="{}", content_type=JSON, headers=headers)
    second = api.post(
        ARCHIVE_URL.format(document.pk), data="{}", content_type=JSON, headers=headers
    )

    assert first.status_code == 200, first.content
    assert second.status_code == 200, second.content
    assert first.json()["archived_at"] == second.json()["archived_at"]
    events = Event.objects.for_tenant(world.tenant).filter(name="files.file.archived")
    assert events.count() == 1, "a retried archive must not put a second event on the spine"
