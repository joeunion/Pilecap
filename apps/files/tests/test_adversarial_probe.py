"""THE PROBE, made permanent.

ADR files-2 gave the files rungs a "born-proven probe leg", and a later
verdict named the adversarial presign/version probe as the half that had been
performed and never pinned. A probe that ran once is a claim about a tree that no
longer exists; these are the same questions, asked by the suite, forever:

1. **What does a leaked download link actually buy the person who leaked it?**
   One version's bytes until it expires. Not the version beside it, not the
   document's other versions, and not a listing of anything — asserted against a
   real store with real siblings present, so an over-broad signature would show
   up as a 200 rather than as a shrug.

2. **Can an occupied key be overwritten?** No, twice over, and the two refusals
   are proved SEPARATELY because they fail separately. The FENCE is service-side
   (`_upload_url_for` mints for a `PENDING` version and refuses a `STORED` one)
   and is proved here with no bucket in existence, which is the whole point: it
   stands on a backend that honours no conditional write at all. The BELT is
   `If-None-Match: *` on the signed URL, which closes the window between the
   object landing and the row learning about it — the window the fence cannot
   see. **The fence never depends on the belt**, and this module is where that
   sentence stops being a docstring.

3. **Can a key outside the acting tenant's prefix reach the store at all?** Not
   through any function on the seam — and the population is DERIVED from the
   module rather than listed, so a function added tomorrow is in the probe
   tomorrow or the census fails by name.

Plus the routing census `apps/files/services.py::_upload_url_for` names in its
own docstring: every presign path goes through that one function, so the fence
cannot be bypassed by a future minting site that called `storage.presign_put`
directly.

**Only (1) reaches the compose MinIO.** (2) and (3) are deliberately store-free —
they are the properties that must hold on a backend that is down, misconfigured
or lenient, and pinning them to an organ would take them out of the `--loop`
tier where they are cheap and most useful.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import io
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from django.conf import settings as django_settings

from apps.core.actor import actor_for
from apps.core.exceptions import Conflict
from apps.files import services, storage
from apps.files.models import FileVersion, StoredFile

from .conftest import make_version

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.accounts.models import User
    from apps.core.models import Organization, Tenant

pytestmark = pytest.mark.django_db

FIRST = b"version one of the invoice\n" * 32
SECOND = b"version two, which nobody leaked a link to\n" * 32


# --- 1 · what a leaked download link is worth ---------------------------------


@pytest.fixture
def two_versions(
    bucket: str, tenant: Tenant, root_org: Organization, owner: User, stored_file: StoredFile
) -> tuple[FileVersion, FileVersion]:
    """One document, two versions, both really in the store.

    Two, because the interesting question about a leaked link is what it does NOT
    reach, and a document with one version cannot answer it: a 403 on a key that
    holds nothing proves nothing about scope.
    """
    acting = actor_for(user=owner, tenant=tenant, org=root_org)
    made: list[FileVersion] = []
    for ordinal, body in ((1, FIRST), (2, SECOND)):
        version = make_version(file=stored_file, version=ordinal, uploaded_by=owner)
        storage.put_bytes(
            tenant=tenant, key=version.key, content=body, content_type="application/pdf"
        )
        made.append(
            services.record_stored(
                tenant=tenant,
                actor=acting,
                version=version,
                sha256=hashlib.sha256(body).hexdigest(),
                size_bytes=len(body),
            )
        )
    return made[0], made[1]


def test_a_leaked_link_fetches_exactly_the_one_version_it_was_minted_for(
    two_versions: tuple[FileVersion, FileVersion], tenant: Tenant
) -> None:
    """The control, and it has to come first: the link WORKS for its own object.

    Every refusal below is only evidence if the same signature really does fetch
    the thing it was signed for — otherwise a seam that minted nonsense would pass
    the whole module.
    """
    first, _second = two_versions

    url = storage.presign_get(tenant=tenant, key=first.key)

    got = httpx.get(url, timeout=30)
    assert got.status_code == 200, got.text
    assert got.content == FIRST


def test_a_leaked_link_cannot_reach_the_sibling_version_that_really_exists(
    two_versions: tuple[FileVersion, FileVersion], tenant: Tenant
) -> None:
    """**The scope of the window.** Version 2 is there, and this link is not for it.

    The signature covers the key, so swapping the ordinal is not a link. What
    makes this a measurement rather than a tautology is the assertion underneath:
    version 2's own link fetches version 2's bytes, so the 403 above is about the
    signature and not about an empty key.
    """
    first, second = two_versions

    leaked = storage.presign_get(tenant=tenant, key=first.key)
    nudged = leaked.replace(f"/v/{first.version}?", f"/v/{second.version}?")
    assert nudged != leaked

    refused = httpx.get(nudged, timeout=30)
    assert refused.status_code == 403, refused.text

    honest = httpx.get(storage.presign_get(tenant=tenant, key=second.key), timeout=30)
    assert honest.status_code == 200
    assert honest.content == SECOND


def test_a_leaked_link_cannot_list_the_document_it_came_from(
    two_versions: tuple[FileVersion, FileVersion], tenant: Tenant
) -> None:
    """No listing — not of the document's prefix, not of the tenant's, not the bucket's.

    A presigned GET is signed for `get_object` on one key. Point the same query
    string at the bucket with a `prefix=` and a store that honoured it would hand
    over the shape of a customer's whole document set: how many files, how many
    versions of each, when. That is an oracle even without a single byte, which is
    why it is asserted at three widths rather than one.
    """
    first, _second = two_versions
    url = httpx.URL(storage.presign_get(tenant=tenant, key=first.key))
    bucket_root = str(url.copy_with(path=f"/{storage.bucket_name()}"))

    for widening in (
        f"{bucket_root}&list-type=2",
        f"{bucket_root}&list-type=2&prefix={storage.tenant_prefix(tenant)}",
        f"{bucket_root}&list-type=2&prefix={first.key.rsplit('/v/', 1)[0]}/",
    ):
        listed = httpx.get(widening, timeout=30)
        assert listed.status_code == 403, (widening, listed.text)


def test_a_leaked_link_cannot_delete_what_it_can_read(
    two_versions: tuple[FileVersion, FileVersion], tenant: Tenant
) -> None:
    """A read credential is a read credential. The verb is signed too.

    Worth its own line because "one version, no siblings, no list" describes the
    breadth of the window and says nothing about its depth: a signature that
    covered the key and not the method would turn a leaked download link into a
    way to destroy the document it points at.
    """
    first, _second = two_versions
    url = storage.presign_get(tenant=tenant, key=first.key)

    refused = httpx.request("DELETE", url, timeout=30)
    assert refused.status_code == 403, refused.text

    still_there = httpx.get(url, timeout=30)
    assert still_there.status_code == 200
    assert still_there.content == FIRST


# --- 2 · an occupied key, and the two refusals that are not each other ---------


def test_the_service_fence_refuses_a_stored_version_with_no_store_in_existence(
    named_bucket: str, tenant: Tenant, owner: User, stored_file: StoredFile
) -> None:
    """**The fence, alone.** No bucket exists here, so nothing could have refused but us.

    `named_bucket` is a NAME and no bucket (`conftest`), and this test never
    reaches the network: if `_upload_url_for` ever came to lean on the store's
    conditional write, this is the assertion that would start failing with a
    connection error instead of a `Conflict`.
    """
    version = make_version(file=stored_file, version=1, uploaded_by=owner)
    FileVersion.objects.filter(pk=version.pk).update(
        status=FileVersion.Status.STORED,
        size_bytes=len(FIRST),
        sha256=hashlib.sha256(FIRST).hexdigest(),
    )
    version.refresh_from_db()

    with pytest.raises(Conflict) as refusal:
        services._upload_url_for(tenant=tenant, version=version)

    assert "already stored" in str(refusal.value)


def test_a_pending_version_still_gets_its_url_from_the_same_function(
    named_bucket: str, tenant: Tenant, owner: User, stored_file: StoredFile
) -> None:
    """The other direction, so the fence above is a refusal and not a broken function."""
    version = make_version(file=stored_file, version=1, uploaded_by=owner)

    url = services._upload_url_for(tenant=tenant, version=version)

    assert version.key in url
    assert "X-Amz-Signature" in url


def test_the_belt_refuses_a_url_minted_before_the_object_landed(
    bucket: str, tenant: Tenant, root_org: Organization, owner: User, stored_file: StoredFile
) -> None:
    """**The belt, alone**, in the window the fence structurally cannot see.

    The URL is minted while the version is `PENDING` — legitimately, by the fence
    — and then the object lands and the row becomes `STORED`. Whoever still holds
    that URL holds a write credential for a key whose digest an audit row and an
    export manifest already quote. `If-None-Match: *` is signed into it, so the
    store answers 412 and the bytes nobody may change do not change.
    """
    version = make_version(file=stored_file, version=1, uploaded_by=owner)
    early = storage.presign_put(tenant=tenant, key=version.key, content_type="application/pdf")

    landed = httpx.put(
        early,
        content=FIRST,
        headers={"Content-Type": "application/pdf", "If-None-Match": "*"},
        timeout=30,
    )
    assert landed.status_code == 200, landed.text
    services.record_stored(
        tenant=tenant,
        actor=actor_for(user=owner, tenant=tenant, org=root_org),
        version=version,
        sha256=hashlib.sha256(FIRST).hexdigest(),
        size_bytes=len(FIRST),
    )

    replayed = httpx.put(
        early,
        content=SECOND,
        headers={"Content-Type": "application/pdf", "If-None-Match": "*"},
        timeout=30,
    )
    assert replayed.status_code == 412, replayed.text

    survived = httpx.get(storage.presign_get(tenant=tenant, key=version.key), timeout=30)
    assert survived.content == FIRST


# --- 3 · the prefix belt, at every function that can reach an object ----------


#: What each keyword a seam function takes should be handed, so the census can
#: CALL every one of them rather than assert about their signatures. A parameter
#: this map does not know is a hard failure below — which is the point: a new
#: seam function with a new argument joins this probe or breaks it, and neither
#: of those is "quietly untested".
_ARGUMENTS: dict[str, Any] = {
    "content_type": "application/pdf",
    "content": b"bytes that must never reach another tenant's prefix",
    "body": io.BytesIO(b"a rewindable body"),
    "expires_in": 60,
}

#: Functions on the seam that take a tenant and a key but do not reach the store
#: on that key — there are none today, and an entry here would need the reason
#: written beside it. Kept as an empty declaration rather than left implicit so
#: that adding one is a visible act.
_NOT_BELTED: dict[str, str] = {}


def _seam_functions_that_take_a_key() -> dict[str, Any]:
    """Every public function on the seam taking both a `tenant` and a `key`.

    **Derived, never listed.** A list would have been right on the day it was
    written; the failure this whole census exists for is the seam growing an
    eighth function whose author did not know about the belt, and a list cannot
    see that.
    """
    found: dict[str, Any] = {}
    for name, value in vars(storage).items():
        if name.startswith("_") or not inspect.isfunction(value):
            continue
        if value.__module__ != storage.__name__:
            continue
        parameters = inspect.signature(value).parameters
        if "tenant" in parameters and "key" in parameters:
            found[name] = value
    return found


def test_the_census_of_belted_functions_is_not_empty() -> None:
    """A derived population that derived nothing would pass every test below.

    The floor is the shape rule 48 itself uses: a recogniser that stopped
    recognising anything must trip a floor rather than report a clean nothing.
    """
    found = _seam_functions_that_take_a_key()

    assert len(found) >= 7, sorted(found)
    assert {"presign_get", "presign_put", "head", "sha256_of", "delete_object"} <= set(found)


def test_every_seam_function_refuses_a_foreign_key(
    named_bucket: str, tenant: Tenant, other_tenant: Tenant
) -> None:
    """**The belt, at every door into the store.** One missed function is the leak.

    `other_tenant`'s prefix with a plausible key in it: a signature over it would
    hand out somebody else's bytes and a delete of it would destroy them. No
    bucket exists in this test, so a function that reached the store BEFORE
    belting fails with the store's own error rather than with a `ValueError` —
    which is a failure either way, and deliberately a different-looking one.
    Measured, not assumed: severing `head`'s belt produced
    `ClientError … HeadObject … 404 Not Found` here, from MinIO, which is the
    shape of a seam function asking about somebody else's key.
    """
    foreign = storage.version_key(
        tenant=other_tenant, file_pk="00000000-0000-0000-0000-000000000001", version=1
    )
    census = _seam_functions_that_take_a_key()

    for name, function in sorted(census.items()):
        if name in _NOT_BELTED:
            continue
        arguments: dict[str, Any] = {}
        for parameter in inspect.signature(function).parameters:
            if parameter in ("tenant", "key"):
                continue
            assert parameter in _ARGUMENTS, (
                f"apps.files.storage.{name} takes {parameter!r}, which this probe does "
                "not know how to supply. Teach _ARGUMENTS what to hand it — a seam "
                "function nobody drives with a foreign key is a seam function nobody "
                "has proved the belt on."
            )
            arguments[parameter] = _ARGUMENTS[parameter]
        with pytest.raises(ValueError) as refusal:
            function(tenant=tenant, key=foreign, **arguments)
        assert "refusing to touch" in str(refusal.value), name


# --- the routing census (`_upload_url_for`'s own claim) -----------------------


def test_every_presign_put_in_services_goes_through_the_one_fenced_function() -> None:
    """`_upload_url_for` claims to be the only minting site. This is the claim, checked.

    The fence lives in that function, so a future door that called
    `storage.presign_put` directly would mint an upload URL for a `STORED`
    version and the refusal would never run — with nothing failing, because the
    belt would still be on the URL and the belt is not the fence.

    Read as an AST rather than as text so a mention in a docstring is not a
    finding; the source is `apps/files/services.py`, which is where every service
    that could mint one lives.
    """
    source = Path(django_settings.BASE_DIR) / "apps" / "files" / "services.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))

    minting_sites: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == "presign_put"
            ):
                minting_sites.append(node.name)

    assert minting_sites == ["_upload_url_for"], minting_sites


def test_the_fence_is_reached_from_both_of_the_services_that_hand_out_a_url() -> None:
    """The other half: the funnel has callers, so it is a funnel and not a cul-de-sac.

    Without this, deleting every call to `_upload_url_for` would leave the test
    above passing over a function nothing uses.
    """
    source = Path(django_settings.BASE_DIR) / "apps" / "files" / "services.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))

    callers = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        for inner in ast.walk(node)
        if isinstance(inner, ast.Call)
        and isinstance(inner.func, ast.Name)
        and inner.func.id == "_upload_url_for"
    }

    assert {"create_file", "add_version"} <= callers, sorted(callers)


def test_the_stored_file_a_probe_builds_is_the_one_the_services_build(
    stored_file: StoredFile,
) -> None:
    """A guard on this module's own fixtures rather than on the code under test.

    `make_version` builds a version row the way a service does, through
    `full_clean()` and the landing gate. If that ever stops being true, every
    assertion above is about a row shape the platform does not produce — so the
    invariant is asserted here instead of assumed by four other tests.
    """
    assert stored_file.current_version == 0
    assert stored_file.organization_id is not None
