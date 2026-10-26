"""PR4.f — **every door selector over a document asks, and the issuance asks first.**

Phase R makes a read a permission (ADR core-27). For this app that lands in
three places:

1. **The five door selectors** — `list_files`, `get_file`, `list_versions`,
   `get_version`, `get_downloadable_version` — ask `file.read`, inside
   `selectors.py`, so no door can forget (§C6). A VERSION asks the DOCUMENT's
   key, because `FileVersion.authz_kind_of` says a version has no kind of its
   own; rule 54 (e) is the census of that and this is the drive.
2. **Both doors say the same words** (rule 46's named case, in
   `test_doors_over_the_wire.py` where the pair is declared).
3. **The issuance refuses before it signs.** A presigned URL is a credential;
   minting one for somebody who may not read the document and then discarding
   it would be a credential that briefly existed. `get_downloadable_version`
   asks on its first line.

And the WRITE side's order, which the sweep also moved: six services here took
a model instance and asked the capability BEFORE reach, so a caller handing in a
row from a branch they cannot see learned it exists. Reach answers first now.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from django.test import Client

from apps.core.actor import Actor, actor_for
from apps.core.authz import refusal_sentence
from apps.core.exceptions import Forbidden, NotFound
from apps.core.models import Grant, Membership
from apps.files import selectors
from apps.files.models import FileVersion, StoredFile
from apps.files.services import create_file

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.accounts.models import User
    from apps.core.tests.permissions_world import World

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/files/"
DETAIL_URL = "/api/v1/files/{}/"
VERSIONS_URL = "/api/v1/files/{}/versions/"
DOWNLOAD_URL = "/api/v1/files/{}/download-url/"


def _withhold(*, world: World, user: User, permission: str) -> Grant:
    """Take one key away from one person, the way a deployment would.

    A `withhold` beats everything — "forbid overrides permit" — so this is the
    smallest world in which an ordinary person is refused a read: nothing about
    the role, the hat or the document changes, and the only difference between
    the two halves of every test below is this one row.
    """
    membership = Membership.objects.filter(tenant=world.tenant).get(user=user)
    return Grant.objects.create(
        tenant=world.tenant,
        membership=membership,
        permission=permission,
        effect=Grant.Effect.WITHHOLD,
    )


def _acting(world: World, user: User, org: Any) -> Actor:
    """A FRESH actor, built after whatever the test changed.

    The `world` fixture acts as these people while it builds, which warms their
    permission memos — one actor, one fetch (PR0), exactly as intended. A
    `Grant` written afterwards is invisible to an actor that already resolved,
    which is right for a request in flight and wrong for a test pretending to be
    the next one. Every door builds its actor per request; so does every case
    here.
    """
    return actor_for(user=user, tenant=world.tenant, org=org)


def _file_at(world: World, org: Any, *, filename: str = "note.pdf") -> StoredFile:
    """One document filed at a named node, through the real service."""
    ticket = create_file(
        tenant=world.tenant,
        actor=actor_for(user=world.user(world.owner), tenant=world.tenant, org=org),
        filename=filename,
        content_type="application/pdf",
        size_bytes=1024,
        purpose="upload",
    )
    return ticket.file


# --- 1 · the population, derived rather than listed ---------------------------


# --- 2 · the order: reach before capability -----------------------------------


def test_a_read_outside_the_subtree_is_not_found_and_inside_without_the_key_is_forbidden(
    world: World, named_bucket: str
) -> None:
    """**PR4.f.1.** The two exception types, in that order, ARE the criterion.

    The region's admin, with `file.read` withheld:

    * a document in the SIBLING branch → `NotFound`. The scoping answered first,
      and a `Forbidden` there would tell them the document exists.
    * one inside their own subtree → `Forbidden`, with the key's own sentence.
    * the list at their own hat → `Forbidden`.

    *Absent (the baseline):* the row and the page, for all three.
    """
    inside = _file_at(world, world.a1, filename="inside.pdf")
    beside = _file_at(world, world.b, filename="beside.pdf")
    _withhold(world=world, user=world.user(world.admin_at_a), permission="file.read")
    acting = _acting(world, world.user(world.admin_at_a), world.a)

    with pytest.raises(NotFound):
        selectors.get_file(tenant=world.tenant, file_id=beside.pk, org=world.a, actor=acting)
    with pytest.raises(Forbidden) as forbidden:
        selectors.get_file(tenant=world.tenant, file_id=inside.pk, org=world.a, actor=acting)
    assert str(forbidden.value.detail) == refusal_sentence("file.read")
    with pytest.raises(Forbidden):
        selectors.list_files(tenant=world.tenant, org=world.a, actor=acting)


def test_with_the_key_the_same_person_reads_both(world: World, named_bucket: str) -> None:
    """The other half of the pair: no withhold, and nothing moved.

    Without this the test above proves only that a refusal happens somewhere,
    not that the withhold is what caused it.
    """
    inside = _file_at(world, world.a1, filename="inside.pdf")
    acting = _acting(world, world.user(world.admin_at_a), world.a)

    found = selectors.get_file(tenant=world.tenant, file_id=inside.pk, org=world.a, actor=acting)
    assert found.pk == inside.pk
    assert selectors.list_files(tenant=world.tenant, org=world.a, actor=acting).count() == 1


def test_a_version_asks_the_documents_key_and_not_one_of_its_own(
    world: World, named_bucket: str
) -> None:
    """**PR4.f.1.** `authz_kind_of` resolved, driven rather than asserted.

    A `FileVersion` has no kind of its own, so the three version selectors ask
    `file.read` — the DOCUMENT's key — and a withhold of that one key closes all
    three. If a version had ever acquired a `file_version.*` vocabulary of its
    own, this would pass while `file.read` was withheld, which is precisely the
    drift rule 54 (e) exists to refuse.

    *Absent (the baseline):* the version list and both `get_`s answer.
    """
    document = _file_at(world, world.a, filename="versioned.pdf")
    _withhold(world=world, user=world.user(world.admin_at_a), permission="file.read")
    acting = _acting(world, world.user(world.admin_at_a), world.a)

    for call, arguments in (
        (selectors.list_versions, {}),
        (selectors.get_version, {"version": 1}),
        (selectors.get_downloadable_version, {"version": None}),
    ):
        with pytest.raises(Forbidden) as refused:
            call(tenant=world.tenant, file=document, org=world.a, actor=acting, **arguments)
        assert str(refused.value.detail) == refusal_sentence("file.read"), call.__name__


def test_a_withheld_read_issues_no_url(world: World, named_bucket: str) -> None:
    """**PR4.f.** The issuance refuses BEFORE it signs. Nothing is minted.

    A presigned URL is a credential. `get_downloadable_version` asks `file.read`
    on its first line, so the refusal happens where the version is resolved and
    `issue_download_url` is never reached — there is no URL to discard, and none
    in a log, and none in an audit row.

    The audit trail is the instrument, because "no URL was minted" is otherwise
    a claim about the inside of a function: an issuance writes a `file.read`
    audit entry, and there is none.

    *Absent (the baseline):* a signed URL, and the audit row that goes with it.
    """
    from apps.core.audit import AuditEntry

    document = _file_at(world, world.a, filename="secret.pdf")
    _withhold(world=world, user=world.user(world.admin_at_a), permission="file.read")
    acting = _acting(world, world.user(world.admin_at_a), world.a)
    before = AuditEntry.objects.count()

    with pytest.raises(Forbidden):
        selectors.get_downloadable_version(
            tenant=world.tenant, file=document, version=None, org=world.a, actor=acting
        )

    assert AuditEntry.objects.count() == before, "something was audited; an issuance happened"


# --- 3 · the wire, and the plain member -------------------------------------


def test_the_plain_member_still_reads_everything(
    api: Client, world: World, named_bucket: str
) -> None:
    """**PR4.f.2, the flat-product half.** A product that customised nothing.

    `member` holds `*.read` by declaration, so the list, the detail and the
    version list answer 200 for an ordinary member exactly as they did before
    Phase R. This is the non-vacuity line under every refusal in this module.
    """
    document = _file_at(world, world.a, filename="ordinary.pdf")
    api.force_login(world.user(world.clerk))
    headers = {"X-Org": world.a.slug}

    listed = api.get(LIST_URL, headers=headers)
    assert listed.status_code == 200, listed.content
    assert [one["id"] for one in listed.json()["items"]] == [str(document.pk)]

    assert api.get(DETAIL_URL.format(document.pk), headers=headers).status_code == 200
    assert api.get(VERSIONS_URL.format(document.pk), headers=headers).status_code == 200


# --- 4 · reach before capability, on the WRITE side --------------------------


def test_a_foreign_document_is_not_found_and_never_forbidden(
    world: World, named_bucket: str
) -> None:
    """**Rule 26's order, on this app's six sites.**

    Every one of them takes a `StoredFile` or a `FileVersion` INSTANCE, which is
    the shape the order exists for: a caller who resolved a row elsewhere hands
    it straight in, and all six asked their key FIRST until this sweep — so the
    refusal said *that document is real and it is not yours*. `NotFound` says
    neither.

    The actor is the region's admin; the document is in the SIBLING branch,
    where they hold nothing. Reach is what they fail, so reach is what answers.

    *Absent (the baseline):* `Forbidden` from all six, each with its own key's
    sentence — the leak.
    """
    from apps.files import services

    beside = _file_at(world, world.b, filename="beside.pdf")
    version = FileVersion.objects.for_tenant(world.tenant).get(file=beside, version=1)
    acting = _acting(world, world.user(world.admin_at_a), world.a)
    common: dict[str, Any] = {"tenant": world.tenant, "actor": acting}

    with pytest.raises(NotFound):
        services.add_version(**common, file=beside, content_type="application/pdf", size_bytes=1)
    with pytest.raises(NotFound):
        services.confirm_upload(**common, version=version, idempotency_key="k")
    with pytest.raises(NotFound):
        services.issue_download_url(**common, file=beside, version=version)
    with pytest.raises(NotFound):
        services.archive_file(**common, file=beside)
    with pytest.raises(NotFound):
        services.store_bytes(
            **common,
            filename="x.pdf",
            content_type="application/pdf",
            content=b"x",
            purpose="upload",
            file=beside,
        )
    with pytest.raises(NotFound):
        services.store_stream(
            **common,
            filename="x.pdf",
            content_type="application/pdf",
            body=_Rewindable(),
            purpose="upload",
            file=beside,
        )


class _Rewindable:
    """The smallest thing `store_stream` will accept as a body. **Never read.**

    The refusal under test happens before a byte is streamed, so this exists
    only so the call is well-formed: if it is ever actually read, the test has
    stopped measuring the thing it is named after.
    """

    def read(self, size: int = -1) -> bytes:  # pragma: no cover - refused first
        raise AssertionError("the body was read; the refusal did not come first")

    def seek(self, offset: int, whence: int = 0) -> int:  # pragma: no cover - refused first
        raise AssertionError("the body was seeked; the refusal did not come first")

    def seekable(self) -> bool:  # pragma: no cover - refused first
        return True

    def tell(self) -> int:  # pragma: no cover - refused first
        return 0


def test_a_document_inside_the_subtree_gets_the_wall_and_not_a_not_found(
    world: World, named_bucket: str
) -> None:
    """The other half: reach passes, so the CAPABILITY wall is what answers.

    Without this the case above would pass on services that had simply started
    refusing everybody `NotFound`, which is the failure mode a reordering is
    most likely to introduce. A plain member may file and may replace; what they
    may not do is archive.
    """
    from apps.files import services

    inside = _file_at(world, world.a, filename="inside.pdf")
    acting = _acting(world, world.user(world.clerk), world.a)

    with pytest.raises(Forbidden) as refused:
        services.archive_file(tenant=world.tenant, actor=acting, file=inside)
    assert str(refused.value.detail) == refusal_sentence("file.archive")
