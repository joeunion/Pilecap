"""A document's archive road, and the subject a document is attached to.

Two things the family seam gives this app, driven through the door a caller uses.

**The archive road** (house rule 74). A document is `Archivable`: the scoped read
leaves an archived document out of every list, `?show=archived` is the one reader
of the archived cut, `?show=all` reads both, and the document stays readable by id
— READ-ONLY. It still signs a download link (archiving takes a document out of the
working set; it never retracts the versions somebody already cited, and the bytes
stay in the bucket), and every other write on it refuses `archived`. Archive and
restore are a pair, each idempotent, each emitting once, and each an
administrator's press at the document's own node — a member is refused, a sibling
branch's administrator never learns the document exists, and the product acting
for itself is refused too.

**The attach subject.** A document may be filed against a subject — `<kind>:<id>`,
any noun that declares `files` among its `attachments`. The subject is resolved
through `core.verbs.resolve_subject` BEFORE anything else, so a subject in a
sibling branch, a subject that does not exist and a kind nobody registered are one
answer (`404 not_found`), and the document lands in the SUBJECT'S organization. The
list reads `?subject=` the same way: the subject is resolved first, so a pointer
to a row the caller cannot reach answers `404` rather than an empty page that would
confirm nothing and a full page that would confirm too much.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from apps.accounts.services import create_user
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.exceptions import Forbidden
from apps.core.models import Membership
from apps.core.services import add_membership
from apps.events.models import Event
from apps.example.models import Widget
from apps.example.services import create_widget
from apps.files.models import FileVersion, StoredFile
from apps.files.selectors import get_file
from apps.files.services import archive_file, create_file, record_stored

if TYPE_CHECKING:  # pragma: no cover - typing only
    from django.test import Client

    from apps.accounts.models import User

    from .conftest import World

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/files/"
DETAIL_URL = "/api/v1/files/{}/"
ARCHIVE_URL = "/api/v1/files/{}/archive/"
RESTORE_URL = "/api/v1/files/{}/restore/"
VERSIONS_URL = "/api/v1/files/{}/versions/"
DOWNLOAD_URL = "/api/v1/files/{}/download-url/"
JSON = "application/json"
DIGEST = "beadbead" * 8
PASSWORD = "correct-horse-battery-staple"  # pragma: allowlist secret


def _filed(world: World, org: Any, *, filename: str) -> StoredFile:
    """One document filed at a node of the tree by the owner, through the service."""
    return create_file(
        tenant=world.tenant,
        actor=actor_for(user=world.owner, tenant=world.tenant, org=org),
        filename=filename,
        content_type="application/pdf",
        size_bytes=1024,
        purpose="upload",
    ).file


def _stored(world: World, file: StoredFile) -> FileVersion:
    """Version 1 of a document taken to `stored`, the way a finalize takes it."""
    row = FileVersion.objects.for_tenant(world.tenant).get(file=file, version=1)
    return record_stored(
        tenant=world.tenant,
        actor=actor_for(user=world.owner, tenant=world.tenant, org=file.organization),
        version=row,
        sha256=DIGEST,
        size_bytes=1024,
    )


def _post(api: Client, url: str, body: dict[str, Any], org: Any) -> Any:
    return api.post(url, data=json.dumps(body), content_type=JSON, headers={"X-Org": org.slug})


@pytest.fixture
def document(world: World, named_bucket: str, recorded_workflow_starts: None) -> StoredFile:
    """A document filed at the region, measured, and a live neighbour beside it."""
    filed = _filed(world, world.region, filename="region-contract.pdf")
    _stored(world, filed)
    _filed(world, world.region, filename="region-neighbour.pdf")
    return filed


@pytest.fixture
def sibling_admin(world: World) -> User:
    """An administrator of the SIBLING branch — who must never learn a region document exists."""
    user = create_user(email="sibling-admin@acme.com", password=PASSWORD)
    add_membership(
        user=user,
        tenant=world.tenant,
        organization=world.sibling,
        is_default=True,
        role=Membership.Role.ADMIN,
        actor=world.owner_actor,
    )
    return user


# --- the road over the wire ------------------------------------------------------


def test_restore_brings_an_archived_document_back_to_the_list(
    api: Client, world: World, document: StoredFile
) -> None:
    """The restore half of the road. *Absent (the baseline):* no `file-restore` route."""
    api.force_login(world.region_admin)
    archived = _post(api, ARCHIVE_URL.format(document.pk), {}, world.region)
    assert archived.status_code == 200, archived.content

    restored = _post(api, RESTORE_URL.format(document.pk), {}, world.region)

    assert restored.status_code == 200, restored.content
    body = restored.json()
    assert body["archived_at"] is None
    assert body["archived_by"] is None
    listed = api.get(LIST_URL, headers={"X-Org": world.region.slug}).json()
    assert str(document.pk) in {row["id"] for row in listed["items"]}
    names = list(
        Event.objects.for_tenant(world.tenant)
        .filter(name__in=("files.file.archived", "files.file.restored"))
        .order_by("created_at")
        .values_list("name", flat=True)
    )
    assert names == ["files.file.archived", "files.file.restored"]

    again = _post(api, RESTORE_URL.format(document.pk), {}, world.region)
    assert again.status_code == 200, again.content
    assert Event.objects.for_tenant(world.tenant).filter(name="files.file.restored").count() == 1, (
        "a repeated restore must not put a second event on the spine"
    )


def test_archive_keeps_its_first_date_and_names_who_pressed_it(
    api: Client, world: World, document: StoredFile
) -> None:
    """`archived_by` is the pressing person; a second press changes neither field."""
    api.force_login(world.region_admin)

    first = _post(api, ARCHIVE_URL.format(document.pk), {}, world.region)
    api.force_login(world.owner)
    second = _post(api, ARCHIVE_URL.format(document.pk), {}, world.root)

    assert first.status_code == 200, first.content
    assert second.status_code == 200, second.content
    assert first.json()["archived_by"]["id"] == str(world.region_admin.pk)
    assert second.json()["archived_at"] == first.json()["archived_at"]
    assert second.json()["archived_by"] == first.json()["archived_by"]
    assert Event.objects.for_tenant(world.tenant).filter(name="files.file.archived").count() == 1


def test_the_list_cuts_by_show_and_refuses_the_archived_switch_naming_show(
    api: Client, world: World, document: StoredFile
) -> None:
    """`?show=live|archived|all`, default live; `?archived=` is not a second way to ask."""
    archive_file(tenant=world.tenant, actor=world.owner_actor, file=document)
    api.force_login(world.owner)

    def ids(query: str) -> set[str]:
        answered = api.get(f"{LIST_URL}{query}")
        assert answered.status_code == 200, answered.content
        return {row["id"] for row in answered.json()["items"]}

    live, archived, everything = ids(""), ids("?show=archived"), ids("?show=all")
    assert str(document.pk) not in live
    assert archived == {str(document.pk)}
    assert everything == live | {str(document.pk)}
    assert ids("?show=live") == live

    for query in ("?show=x", "?archived=true"):
        refused = api.get(f"{LIST_URL}{query}")
        assert refused.status_code == 400, (query, refused.content)
        assert refused.json()["code"] == "invalid"
        assert "show" in refused.json()["errors"], refused.json()


def test_an_archived_document_reads_by_id_read_only(
    api: Client, world: World, document: StoredFile
) -> None:
    """Readable and still signing a link; every other write is `409 archived`."""
    archive_file(tenant=world.tenant, actor=world.owner_actor, file=document)
    api.force_login(world.owner)

    fetched = api.get(DETAIL_URL.format(document.pk))
    assert fetched.status_code == 200, fetched.content
    assert fetched.json()["archived_at"] is not None

    link = _post(api, DOWNLOAD_URL.format(document.pk), {}, world.root)
    assert link.status_code == 200, link.content

    replaced = _post(
        api,
        VERSIONS_URL.format(document.pk),
        {"content_type": "application/pdf", "size_bytes": 99},
        world.root,
    )
    assert replaced.status_code == 409, replaced.content
    assert replaced.json()["code"] == "archived"


def test_archive_then_read_through_the_selector_answers_the_archived_row(
    world: World, document: StoredFile
) -> None:
    """The site a hand-written `archived_at` filter used to own, read after the mixin.

    Once `StoredFile` declares `Archivable`, `for_tenant` hides an archived row
    FIRST — so a `get_` that did not widen would answer `not_found` for a document
    whose id the caller legitimately holds.
    """
    archive_file(tenant=world.tenant, actor=world.owner_actor, file=document)

    read = get_file(
        tenant=world.tenant, file_id=document.pk, org=world.root, actor=world.owner_actor
    )

    assert read.pk == document.pk
    assert read.archived_at is not None


def test_restore_is_an_administrators_press_at_the_documents_own_node(
    api: Client, world: World, document: StoredFile, sibling_admin: User
) -> None:
    """A member is refused `forbidden`; a sibling branch's admin gets `not_found`."""
    archive_file(tenant=world.tenant, actor=world.owner_actor, file=document)

    api.force_login(world.plain_member)
    member = _post(api, RESTORE_URL.format(document.pk), {}, world.region)
    assert member.status_code == 403, member.content
    assert member.json()["code"] == "forbidden"

    api.force_login(sibling_admin)
    stranger = _post(api, RESTORE_URL.format(document.pk), {}, world.sibling)
    assert stranger.status_code == 404, stranger.content
    assert stranger.json()["code"] == "not_found"

    document.refresh_from_db()
    assert document.archived_at is not None


def test_the_product_acting_for_itself_may_not_archive_a_document(
    world: World, document: StoredFile
) -> None:
    """`may_archive` refuses the system actor: a workflow does not archive on its own say-so."""
    robot: Actor = system_actor(world.tenant, world.region)

    with pytest.raises(Forbidden):
        archive_file(tenant=world.tenant, actor=robot, file=document)

    document.refresh_from_db()
    assert document.archived_at is None


# --- the attach subject ------------------------------------------------------------


@pytest.fixture
def widgets(world: World) -> tuple[Widget, Widget]:
    """A widget at the branch (under the region) and one at the sibling branch."""
    here = create_widget(
        tenant=world.tenant,
        actor=actor_for(user=world.owner, tenant=world.tenant, org=world.branch),
        name="Branch widget",
    )
    there = create_widget(
        tenant=world.tenant,
        actor=actor_for(user=world.owner, tenant=world.tenant, org=world.sibling),
        name="Sibling widget",
    )
    return here, there


@pytest.fixture
def widgets_take_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """Declare `files` among `Widget.attachments` for one test, whatever the tree says."""
    declared = getattr(Widget, "attachments", ())
    monkeypatch.setattr(Widget, "attachments", (*declared, "files"), raising=False)


@pytest.fixture
def widgets_take_no_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """Declare `Widget.attachments` WITHOUT `files` for one test, whatever the tree says.

    Subtractive: `files` taken out and every other attachment the tree declares
    kept, undone by `monkeypatch`.
    """
    declared = getattr(Widget, "attachments", ())
    kept = tuple(kind for kind in declared if kind != "files")
    monkeypatch.setattr(Widget, "attachments", kept, raising=False)


def _filing(subject: str) -> dict[str, Any]:
    return {
        "filename": "attached.pdf",
        "content_type": "application/pdf",
        "size_bytes": 10,
        "subject": subject,
    }


def test_a_document_filed_against_a_subject_lands_in_the_subjects_organization(
    api: Client,
    world: World,
    named_bucket: str,
    widgets: tuple[Widget, Widget],
    widgets_take_files: None,
) -> None:
    """Filed under the region's hat against a branch widget: it lands at the BRANCH."""
    here, _there = widgets
    _filed(world, world.region, filename="unattached.pdf")
    api.force_login(world.region_admin)

    created = _post(api, LIST_URL, _filing(f"widget:{here.pk}"), world.region)

    assert created.status_code == 201, created.content
    document = created.json()["file"]
    assert document["organization_id"] == str(world.branch.pk)
    assert document["subject"] == f"widget:{here.pk}"

    listed = api.get(f"{LIST_URL}?subject=widget:{here.pk}", headers={"X-Org": world.region.slug})
    assert listed.status_code == 200, listed.content
    assert [row["id"] for row in listed.json()["items"]] == [document["id"]]


def test_a_subject_in_a_sibling_branch_is_not_found_on_both_reads_and_writes(
    api: Client,
    world: World,
    named_bucket: str,
    widgets: tuple[Widget, Widget],
    widgets_take_files: None,
) -> None:
    """Not `forbidden`: a refusal that told the two apart would confirm the row exists."""
    _here, there = widgets
    api.force_login(world.region_admin)

    created = _post(api, LIST_URL, _filing(f"widget:{there.pk}"), world.region)
    listed = api.get(f"{LIST_URL}?subject=widget:{there.pk}", headers={"X-Org": world.region.slug})

    assert created.status_code == 404, created.content
    assert created.json()["code"] == "not_found"
    assert listed.status_code == 404, listed.content
    assert listed.json()["code"] == "not_found"
    assert not StoredFile.objects.filter(tenant=world.tenant, filename="attached.pdf").exists()


def test_a_subject_kind_that_takes_no_files_is_refused_naming_subject(
    api: Client,
    world: World,
    named_bucket: str,
    widgets: tuple[Widget, Widget],
    widgets_take_no_files: None,
) -> None:
    """`400 invalid` naming `subject` — on the filing and on the list alike."""
    here, _there = widgets
    api.force_login(world.region_admin)

    for answered in (
        _post(api, LIST_URL, _filing(f"widget:{here.pk}"), world.region),
        _post(api, LIST_URL, _filing("widget"), world.region),
        api.get(f"{LIST_URL}?subject=widget:{here.pk}", headers={"X-Org": world.region.slug}),
    ):
        assert answered.status_code == 400, answered.content
        assert answered.json()["code"] == "invalid"
        assert "subject" in answered.json()["errors"], answered.json()


# --- the merge re-point ---------------------------------------------------------------


def test_the_repointer_moves_what_it_counted_to_the_survivor_and_its_node(
    world: World,
    named_bucket: str,
    widgets_take_files: None,
) -> None:
    """A planted merge: every document filed against the loser — archived ones too —
    now names the survivor and lives at the survivor's node, versions beside it; the
    dry-run count equals what moved; a second run moves nothing."""
    from apps.core.verbs import hook

    at_branch = actor_for(user=world.owner, tenant=world.tenant, org=world.branch)
    loser = create_widget(tenant=world.tenant, actor=at_branch, name="Loser")
    survivor = create_widget(
        tenant=world.tenant,
        actor=actor_for(user=world.owner, tenant=world.tenant, org=world.region),
        name="Survivor",
    )
    filed = [
        create_file(
            tenant=world.tenant,
            actor=at_branch,
            filename=f"attached-{n}.pdf",
            content_type="application/pdf",
            size_bytes=10,
            purpose="upload",
            subject=f"widget:{loser.pk}",
        ).file
        for n in (1, 2)
    ]
    archive_file(tenant=world.tenant, actor=world.owner_actor, file=filed[1])
    ours = [value for config, value in hook("merge_repointers") if config.label == "files"]
    assert len(ours) == 1
    repointer = ours[0]["*"]

    counted = repointer.count(tenant=world.tenant, loser=loser)
    moved = repointer.repoint(
        tenant=world.tenant, actor=world.owner_actor, loser=loser, survivor=survivor
    )

    assert counted == moved == 2
    rows = StoredFile.objects.filter(pk__in=[one.pk for one in filed])
    assert {row.subject_id for row in rows} == {survivor.pk}
    assert {row.organization_id for row in rows} == {world.region.pk}
    versions = FileVersion.objects.filter(file__in=rows)
    assert {row.organization_id for row in versions} == {world.region.pk}
    assert repointer.count(tenant=world.tenant, loser=loser) == 0
    assert (
        repointer.repoint(
            tenant=world.tenant, actor=world.owner_actor, loser=loser, survivor=survivor
        )
        == 0
    )


def test_the_repoint_stamps_updated_at_on_every_row_it_moves(
    world: World,
    named_bucket: str,
    widgets_take_files: None,
) -> None:
    """A re-pointed document — and each version that follows it — reads as CHANGED.

    A queryset `.update()` skips `auto_now`, so a repointer that did not name the
    stamp left `updated_at` where it was and a client syncing on it never saw the
    document move. *Red on the baseline:* both stamps stood still.
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.files.services import move_attached_files

    at_branch = actor_for(user=world.owner, tenant=world.tenant, org=world.branch)
    loser = create_widget(tenant=world.tenant, actor=at_branch, name="Loser")
    survivor = create_widget(
        tenant=world.tenant,
        actor=actor_for(user=world.owner, tenant=world.tenant, org=world.region),
        name="Survivor",
    )
    filed = create_file(
        tenant=world.tenant,
        actor=at_branch,
        filename="attached.pdf",
        content_type="application/pdf",
        size_bytes=10,
        purpose="upload",
        subject=f"widget:{loser.pk}",
    ).file
    long_ago = timezone.now() - timedelta(days=30)
    StoredFile.objects.filter(pk=filed.pk).update(updated_at=long_ago)
    FileVersion.objects.filter(file=filed).update(updated_at=long_ago)

    moved = move_attached_files(
        tenant=world.tenant, actor=world.owner_actor, loser=loser, survivor=survivor
    )

    assert moved == 1
    row = StoredFile.objects.get(pk=filed.pk)
    assert row.subject_id == survivor.pk
    assert row.updated_at > long_ago, "the re-pointed document's updated_at stood still"
    stamps = set(FileVersion.objects.filter(file=filed).values_list("updated_at", flat=True))
    assert stamps and all(stamp > long_ago for stamp in stamps), stamps


def test_the_attach_specimen_files_against_its_subject_through_the_service(
    world: World,
    widgets: tuple[Widget, Widget],
    widgets_take_files: None,
) -> None:
    """The hook core's conformance tests import: a document filed against the row,
    landed at the SUBJECT'S node — no bucket fixture, because the specimen names one."""
    from apps.files.tests.attach_specimen import attach

    here, _there = widgets
    document = attach(tenant=world.tenant, actor=world.region_actor, subject=here)

    assert isinstance(document, StoredFile)
    assert (document.subject_kind, document.subject_id) == ("widget", here.pk)
    assert document.organization_id == world.branch.pk
    assert StoredFile.objects.for_tenant(world.tenant).filter(pk=document.pk).exists()


# --- the press takes no body ---------------------------------------------------------


#: What the two presses publish they can refuse with — pinned from the baseline
#: document, so dropping the body could not quietly move a refusal in or out.
#: `invalid_body` left with the body: a press that takes none cannot earn it.
_EVERY_PRESS = (
    "addressing_header_not_honoured",
    "database_unavailable",
    "forbidden",
    "insufficient_scope",
    "not_found",
    "rate_limited",
    "unauthenticated",
)
ARCHIVE_REFUSALS = frozenset({*_EVERY_PRESS, "archive_blocked"})
RESTORE_REFUSALS = frozenset({*_EVERY_PRESS, "restore_blocked"})


def test_archive_and_restore_take_no_body_and_still_answer_an_empty_one(
    api: Client, world: World, document: StoredFile
) -> None:
    """A bodiless press is the press (*red on the baseline:* `422 invalid_body`), and a
    client still sending `{}` is answered exactly as before — no wire break."""
    api.force_login(world.region_admin)
    hat = {"X-Org": world.region.slug}

    archived = api.post(ARCHIVE_URL.format(document.pk), headers=hat)
    assert archived.status_code == 200, archived.content
    assert archived.json()["archived_at"] is not None
    restored = api.post(RESTORE_URL.format(document.pk), headers=hat)
    assert restored.status_code == 200, restored.content
    assert restored.json()["archived_at"] is None

    for url in (ARCHIVE_URL, RESTORE_URL):
        answered = _post(api, url.format(document.pk), {}, world.region)
        assert answered.status_code == 200, answered.content


def test_the_published_presses_take_no_body_and_keep_their_refusals() -> None:
    """The document says it too: no `requestBody`, and the same `x-refusal-codes`."""
    from config.api import api as the_api

    paths = the_api.get_openapi_schema()["paths"]
    for verb, pinned in (("archive", ARCHIVE_REFUSALS), ("restore", RESTORE_REFUSALS)):
        operation = paths[f"/api/v1/files/{{file_id}}/{verb}/"]["post"]
        assert "requestBody" not in operation, verb
        published = {
            code
            for body in (operation.get("responses") or {}).values()
            if isinstance(body, dict)
            for code in (body.get("x-refusal-codes") or ())
        }
        assert published == pinned, (verb, sorted(published))


def test_the_repoint_says_moved_once_per_document_and_nothing_on_a_repeat(
    api: Client,
    world: World,
    named_bucket: str,
    widgets_take_files: None,
) -> None:
    """`files.file.moved` per re-pointed document — archived ones too — each payload the
    document as the read doors render it minus the per-viewer acts, `subject` naming
    the survivor; the repeat moves nothing and says nothing. *Red on the baseline:*
    no event at all."""
    from apps.files.services import move_attached_files

    at_branch = actor_for(user=world.owner, tenant=world.tenant, org=world.branch)
    loser = create_widget(tenant=world.tenant, actor=at_branch, name="Loser")
    survivor = create_widget(
        tenant=world.tenant,
        actor=actor_for(user=world.owner, tenant=world.tenant, org=world.region),
        name="Survivor",
    )
    filed = [
        create_file(
            tenant=world.tenant,
            actor=at_branch,
            filename=f"attached-{n}.pdf",
            content_type="application/pdf",
            size_bytes=10,
            purpose="upload",
            subject=f"widget:{loser.pk}",
        ).file
        for n in (1, 2)
    ]
    archive_file(tenant=world.tenant, actor=world.owner_actor, file=filed[1])
    said = Event.objects.for_tenant(world.tenant).filter(name="files.file.moved")
    assert said.count() == 0

    moved = move_attached_files(
        tenant=world.tenant, actor=world.owner_actor, loser=loser, survivor=survivor
    )

    assert moved == 2
    payloads = {row["id"]: row for row in said.values_list("payload", flat=True)}
    assert set(payloads) == {str(one.pk) for one in filed}
    api.force_login(world.owner)
    for one in filed:
        payload = payloads[str(one.pk)]
        # The document as the REST door renders it, minus the one per-viewer field.
        read = api.get(DETAIL_URL.format(one.pk), headers={"X-Org": world.root.slug})
        assert read.status_code == 200, read.content
        rendered = {k: v for k, v in read.json().items() if k != "allowed_acts"}
        assert "allowed_acts" not in payload
        assert payload["subject"] == f"widget:{survivor.pk}"
        assert payload["organization_id"] == str(world.region.pk)
        assert {k: v for k, v in payload.items() if k != "v"} == rendered

    again = move_attached_files(
        tenant=world.tenant, actor=world.owner_actor, loser=loser, survivor=survivor
    )
    assert again == 0
    assert said.count() == 2, "a repeat re-point must say nothing"
