"""The fifth door meets the house floor.

Scoped, filtered, ordered, paginated, pinned; strict on the way in; both
tenancy siblings present, because "another tenant's rows are absent" and "a
sibling branch's rows are absent" are two different claims and only the second
one is about the hierarchy.

And the one thing this app's door has that no other has: **two bars behind one
verb**. Exporting your own subtree needs nothing but membership, because it is
data you can already page through; exporting the whole tenant needs
administrator rights at its root. Both directions are driven here, over the
wire, because a permission that is only ever asserted in the affirmative is a
permission nobody has proved refuses.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

import pytest

from apps.core.actor import actor_for
from apps.exports.models import Export
from apps.exports.services import create_export

if TYPE_CHECKING:  # pragma: no cover - typing only
    from django.test import Client

    from apps.accounts.models import User
    from apps.core.models import Tenant

    from .conftest import World

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/exports/"
DETAIL_URL = "/api/v1/exports/{}/"
DOWNLOAD_URL = "/api/v1/exports/{}/download/"
JSON = "application/json"

#: Measured, not guessed, at seeded scale. The page itself plus the middleware
#: and session work an authenticated request pays: the list issues no `COUNT`
#: (ADR core-18 — `has_more` comes from fetching one row more than asked for),
#: and `select_related` is what keeps the two relations `ExportOut` walks off
#: the per-row path. Removing either would move this number, which is the point.
LIST_QUERY_BUDGET = 7


@pytest.fixture
def exports(world: World, recorded_workflow_starts: None) -> list[Export]:
    """Three exports across the tree: one at the root, two under the region."""
    return [
        create_export(tenant=world.tenant, actor=world.owner_actor),
        create_export(tenant=world.tenant, actor=world.region_actor, idempotency_key="a"),
        create_export(
            tenant=world.tenant,
            actor=actor_for(user=world.owner, tenant=world.tenant, org=world.branch),
        ),
    ]


# --- the list -----------------------------------------------------------------


def test_the_list_answers_in_the_cursor_envelope(
    api: Client, world: World, exports: list[Export]
) -> None:
    """ADR core-18's envelope, and `count` null until somebody asks for it."""
    api.force_login(world.owner)

    response = api.get(LIST_URL)

    assert response.status_code == 200, response.content
    body = response.json()
    assert set(body) == {"items", "has_more", "next_cursor", "count"}
    assert body["count"] is None, "a total costs a second statement; it is opt-in"
    assert len(body["items"]) == 3
    assert body["items"][0]["status"] == Export.Status.PENDING


def test_include_count_is_what_puts_the_total_on_the_wire(
    api: Client, world: World, exports: list[Export]
) -> None:
    api.force_login(world.owner)

    body = api.get(LIST_URL, {"include_count": "true"}).json()

    assert body["count"] == 3


def test_another_tenants_exports_are_absent(
    api: Client, world: World, neighbour: Tenant, stranger: User, exports: list[Export]
) -> None:
    """The tenancy sibling every list test in this repository owes."""
    from apps.core.services import root_organization

    create_export(
        tenant=neighbour,
        actor=actor_for(user=stranger, tenant=neighbour, org=root_organization(tenant=neighbour)),
    )
    api.force_login(world.owner)

    body = api.get(LIST_URL).json()

    assert len(body["items"]) == 3
    assert {one["tenant_id"] for one in body["items"]} == {str(world.tenant.pk)}


def test_a_branch_admin_sees_its_own_subtree_and_nothing_above_it(
    api: Client, world: World, exports: list[Export]
) -> None:
    """The hierarchy sibling, which the tenancy one cannot see.

    The region's admin sees the region's export and the branch's beneath it, and
    does not see the root's — even though all three are in one tenant and all
    three are that tenant's own exports.
    """
    api.force_login(world.region_admin)

    body = api.get(LIST_URL, headers={"X-Org": world.region.slug}).json()

    slugs = {one["organization_slug"] for one in body["items"]}
    assert slugs == {"region", "branch"}
    assert "acme" not in slugs


def test_the_status_filter_is_exact(api: Client, world: World, exports: list[Export]) -> None:
    """A word from a closed vocabulary, so a substring match would be a trap."""
    api.force_login(world.owner)

    assert len(api.get(LIST_URL, {"status": "pending"}).json()["items"]) == 3
    assert api.get(LIST_URL, {"status": "pend"}).json()["items"] == []
    assert api.get(LIST_URL, {"status": "completed"}).json()["items"] == []


def test_an_ordering_this_list_does_not_accept_is_refused(
    api: Client, world: World, exports: list[Export]
) -> None:
    """Refused with the registry's envelope rather than quietly ignored."""
    api.force_login(world.owner)

    response = api.get(LIST_URL, {"ordering": "artifact_key"})

    assert response.status_code == 400, response.content
    assert response.json()["code"] == "invalid"


def test_the_list_query_budget(
    api: Client, world: World, exports: list[Export], django_assert_num_queries: Any
) -> None:
    """The pin that turns a lost `select_related` into a failure, not a slow page."""
    api.force_login(world.owner)

    with django_assert_num_queries(LIST_QUERY_BUDGET):
        assert api.get(LIST_URL).status_code == 200


# --- asking for one -----------------------------------------------------------


def test_a_member_may_export_their_own_organization(api: Client, world: World) -> None:
    """The free half: no role bar, because the walk reads what they already can."""
    api.force_login(world.region_admin)

    response = api.post(
        LIST_URL,
        data=json.dumps({"scope": "organization"}),
        content_type=JSON,
        headers={"X-Org": world.region.slug},
    )

    assert response.status_code == 201, response.content
    body = response.json()
    assert body["scope"] == "organization"
    assert body["organization_slug"] == "region"
    assert body["status"] == "pending"
    assert body["download_url"] is None and body["download_path"] is None


def test_a_branch_admin_may_not_export_the_whole_tenant(api: Client, world: World) -> None:
    """The bar, refused. An admin of one branch does not own the whole customer.

    Reused rather than restated: `accounts.policies.administers_the_whole_tenant`
    is the same predicate erasure stands behind, so if that ceiling ever moves
    it moves once.
    """
    api.force_login(world.region_admin)

    response = api.post(
        LIST_URL,
        data=json.dumps({"scope": "tenant"}),
        content_type=JSON,
        headers={"X-Org": world.region.slug},
    )

    assert response.status_code == 403, response.content
    assert response.json()["code"] == "forbidden"
    assert not Export.objects.for_tenant(world.tenant).exists(), "nothing was created"


def test_the_root_owner_may_export_the_whole_tenant(api: Client, world: World) -> None:
    """The other side of the same bar, so neither direction is assumed."""
    api.force_login(world.owner)

    response = api.post(LIST_URL, data=json.dumps({"scope": "tenant"}), content_type=JSON)

    assert response.status_code == 201, response.content
    assert response.json()["scope"] == "tenant"


def test_a_scope_this_api_does_not_have_is_refused(api: Client, world: World) -> None:
    api.force_login(world.owner)

    response = api.post(LIST_URL, data=json.dumps({"scope": "everything"}), content_type=JSON)

    assert response.status_code == 400, response.content
    assert response.json()["code"] == "invalid"
    assert "scope" in response.json()["errors"]


def test_an_unknown_field_in_the_body_is_a_refusal_naming_it(api: Client, world: World) -> None:
    """Strict bodies: silence cannot be told from success on the way in."""
    api.force_login(world.owner)

    response = api.post(
        LIST_URL,
        data=json.dumps({"scope": "organization", "include_models": ["example.Widget"]}),
        content_type=JSON,
    )

    assert response.status_code == 422, response.content
    body = response.json()
    assert body["code"] == "invalid_body"
    assert "include_models" in json.dumps(body["errors"])
    assert not Export.objects.for_tenant(world.tenant).exists()


def test_a_body_field_cannot_place_the_export_in_another_branch(api: Client, world: World) -> None:
    """There is no `organization` on `ExportIn`, and its absence is the enforcement."""
    api.force_login(world.region_admin)

    response = api.post(
        LIST_URL,
        data=json.dumps({"scope": "organization", "organization": world.root.slug}),
        content_type=JSON,
        headers={"X-Org": world.region.slug},
    )

    assert response.status_code == 422, response.content
    assert response.json()["code"] == "invalid_body"


# --- reading one, and fetching it ----------------------------------------------


def test_an_export_in_another_tenant_is_not_found(
    api: Client, world: World, neighbour: Tenant, stranger: User
) -> None:
    """Not-there and not-yours are one answer."""
    from apps.core.services import root_organization

    theirs = create_export(
        tenant=neighbour,
        actor=actor_for(user=stranger, tenant=neighbour, org=root_organization(tenant=neighbour)),
    )
    api.force_login(world.owner)

    response = api.get(DETAIL_URL.format(theirs.pk))

    assert response.status_code == 404, response.content
    assert response.json()["code"] == "not_found"


def test_downloading_an_export_that_has_not_finished_is_not_found(
    api: Client, world: World, exports: list[Export]
) -> None:
    """ "There is no file here" and "there is no such export" are one answer."""
    api.force_login(world.owner)

    response = api.get(DOWNLOAD_URL.format(exports[0].pk))

    assert response.status_code == 404, response.content
    assert response.json()["code"] == "not_found"


def test_a_finished_export_is_handed_over_as_a_signed_link_that_really_fetches_it(
    api: Client, world: World, recorded_workflow_starts: None, archive_bucket: str
) -> None:
    """The always-works door: a `302` to the archive, over the caller's own credential.

    **This test used to assert a `200` and a streamed body.** XPr moved the
    archive onto the files seam, where ADR files-2 rules that bytes never travel
    through Django, and applied XP-1's OWN ratified either/or — *"a presigned
    `download_url` where the backend signs, and an authenticated `/download`
    stream otherwise"* — to its first branch, because `files.storage` refuses a
    deployment that has named no bucket and the *otherwise* has no world left to
    describe. The moved assertion is the change, said out loud, rather than a
    contract that drifted.

    What is asserted instead is STRICTLY MORE than the old test: the redirect is
    followed to the object store and the bytes that come back are checked to be
    the archive. The old one proved Django could stream a file; this one proves
    a client with nothing but this URL ends up holding the zip.
    """
    import urllib.request

    from apps.exports.activities import _write_the_archive
    from apps.exports.services import finish_export

    export = create_export(tenant=world.tenant, actor=world.owner_actor, scope=Export.Scope.TENANT)
    version, manifest = _write_the_archive(export=export, hat=world.root, actor=world.owner_actor)
    finish_export(
        tenant=world.tenant,
        actor=world.owner_actor,
        export=export,
        version=version,
        manifest=manifest,
    )
    api.force_login(world.owner)

    response = api.get(DOWNLOAD_URL.format(export.pk))

    assert response.status_code == 302, response.content
    signed = response["Location"]
    assert str(version.key) in signed, "the redirect points at THIS archive"
    assert "X-Amz-Signature=" in signed, "and it carries its own credential"

    # Followed, because a redirect nobody can follow is a 404 with better
    # manners. This is the one place the whole door is measured end to end.
    with urllib.request.urlopen(signed) as fetched:  # noqa: S310 - a URL we just minted
        fetched_bytes = fetched.read()
    assert fetched_bytes[:2] == b"PK", "that is a zip"
    assert len(fetched_bytes) == version.size_bytes
    assert hashlib.sha256(fetched_bytes).hexdigest() == version.sha256, (
        "the bytes a client fetches are not the bytes we recorded a digest for"
    )

    # And the read shape says where to get it — BOTH ways now, and a client
    # reading `download_url or download_path` is right as it always was.
    body = api.get(DETAIL_URL.format(export.pk)).json()
    assert body["download_url"] is not None
    assert str(version.key) in body["download_url"]
    assert body["download_path"] == DOWNLOAD_URL.format(export.pk)
    assert body["artifact_bytes"] == version.size_bytes
    assert body["manifest"]["rows"] == manifest["rows"]
    assert body["expires_at"] > body["created_at"]


def test_a_neighbour_cannot_fetch_this_tenants_archive(
    api: Client,
    world: World,
    neighbour: Tenant,
    stranger: User,
    recorded_workflow_starts: None,
    archive_bucket: str,
) -> None:
    """The scoping holds at the door that hands over the link, which is the one that matters.

    **A redirect is a hand-over of a bearer credential**, which is precisely why
    the refusal is asserted here rather than assumed from the detail route: a
    door that answered `302` to a stranger would have leaked a URL that fetches
    another tenant's whole database with no credential of ours in front of it.
    """
    from apps.exports.activities import _write_the_archive
    from apps.exports.services import finish_export

    export = create_export(tenant=world.tenant, actor=world.owner_actor, scope=Export.Scope.TENANT)
    version, manifest = _write_the_archive(export=export, hat=world.root, actor=world.owner_actor)
    finish_export(
        tenant=world.tenant,
        actor=world.owner_actor,
        export=export,
        version=version,
        manifest=manifest,
    )
    api.force_login(stranger)

    response = api.get(DOWNLOAD_URL.format(export.pk))

    assert response.status_code == 404, response.content


def test_the_routes_require_a_credential(api: Client, world: World) -> None:
    """`auth=` is on the router; nothing here is reachable signed out."""
    assert api.get(LIST_URL).status_code == 401
    assert api.post(LIST_URL, data="{}", content_type=JSON).status_code == 401
