"""The HTTP door onto imports, driven through the mounted API.

Staged, checked, previewed, refused — over the wire, with the real services,
the real files seam's services and the real planted importer. The object store
is the one thing doubled (`conftest.memory_store`). The apply's run is proved on
a real worker in `test_workflows.py`; here the press itself is proved.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pytest
from django.urls import reverse

from apps.core.actor import actor_for
from apps.core.models import Grant, Membership, Organization
from apps.core.services import create_organization
from apps.djb_imports.models import MAX_IMPORT_ROWS, Import, ImportRow
from apps.djb_imports.services import create_import
from apps.djb_imports.tests.conftest import FIVE_ROWS_ONE_BAD, stored_csv
from apps.example.models import Widget
from apps.workflows.models import WorkflowRun

if TYPE_CHECKING:  # pragma: no cover - typing only
    from django.test import Client

    from apps.accounts.models import User
    from apps.core.actor import Actor
    from apps.core.models import Tenant

pytestmark = pytest.mark.django_db

JSON = "application/json"
LIST_URL = reverse("api:djb_import-list")
CREATE_URL = reverse("api:djb_import-create")

#: Measured on the box at seeded scale (three runs, then nine): the page, the
#: session and the hat, `djb_import.read` resolved once at the hat (three tables,
#: memoised on the actor), and the `select_related` that keeps the three
#: relations `ImportOut` walks off the per-row path. Flat across the two scales.
LIST_QUERY_BUDGET = 10
ROWS_QUERY_BUDGET = 11


def _detail(run: Import) -> str:
    return reverse("api:djb_import-detail", kwargs={"import_id": run.pk})


def _rows(run: Import) -> str:
    return reverse("api:djb_import_rows-list", kwargs={"import_id": run.pk})


def _apply(run: Import) -> str:
    return reverse("api:djb_import-apply", kwargs={"import_id": run.pk})


def _cancel(run: Import) -> str:
    return reverse("api:djb_import-cancel", kwargs={"import_id": run.pk})


def _stage(api: Client, file_id: Any, **extra: Any) -> Any:
    body = {"kind": "widget", "file_id": str(file_id), **extra}
    return api.post(CREATE_URL, data=json.dumps(body), content_type=JSON)


@pytest.fixture
def staged(owner_actor: Actor, memory_store: dict[str, bytes], planted_importer: None) -> Import:
    """One run over the five-row file, staged by the owner at the root."""
    version = stored_csv(owner_actor, FIVE_ROWS_ONE_BAD)
    assert owner_actor.tenant is not None
    run, _ = create_import(
        tenant=owner_actor.tenant, actor=owner_actor, kind="widget", file_version=version
    )
    return run


# --- IM.1 · staging, and staging the same bytes again -------------------------


def test_staging_a_file_answers_201_checking(
    api: Client,
    owner: User,
    owner_actor: Actor,
    memory_store: dict[str, bytes],
    planted_importer: None,
) -> None:
    """IM.1: a staged file is a run in `checking`, with its check started on commit."""
    version = stored_csv(owner_actor, FIVE_ROWS_ONE_BAD)
    api.force_login(owner)

    response = _stage(api, version.file_id)

    assert response.status_code == 201, response.content
    body = response.json()
    assert body["status"] == "checking"
    assert body["created"] is True
    assert body["file_name"] == "widgets.csv"
    assert body["digest"] == version.sha256
    runs = WorkflowRun.objects.filter(
        workflow_id__endswith=f":djb_imports:import:{body['id']}-check"
    )
    assert runs.count() == 1, "the check is recorded to start on the stage's commit"


def test_the_same_file_again_is_the_same_run(
    api: Client,
    owner: User,
    owner_actor: Actor,
    memory_store: dict[str, bytes],
    planted_importer: None,
) -> None:
    """IM.1: the same bytes again → 200, the same id, `created: false`, one run."""
    first_version = stored_csv(owner_actor, FIVE_ROWS_ONE_BAD)
    # A SECOND document with the same bytes: recognised by digest, not by name.
    second_version = stored_csv(owner_actor, FIVE_ROWS_ONE_BAD, filename="copy.csv")
    api.force_login(owner)

    first = _stage(api, first_version.file_id)
    again = _stage(api, second_version.file_id)

    assert first.status_code == 201, first.content
    assert again.status_code == 200, again.content
    assert again.json()["id"] == first.json()["id"]
    assert again.json()["created"] is False
    assert Import.objects.count() == 1
    assert WorkflowRun.objects.filter(workflow_id__contains=":djb_imports:import:").count() == 1


def test_a_failed_run_does_not_hold_the_bytes(api: Client, owner: User, staged: Import) -> None:
    """A cancelled (failed) run releases its digest: staging again makes a new run."""
    api.force_login(owner)
    assert api.post(_cancel(staged)).status_code == 200
    assert staged.file_version is not None

    again = _stage(api, staged.file_version.file_id)

    assert again.status_code == 201, again.content
    assert again.json()["id"] != str(staged.pk)


def test_an_unknown_kind_is_invalid(
    api: Client, owner: User, owner_actor: Actor, memory_store: dict[str, bytes]
) -> None:
    version = stored_csv(owner_actor, FIVE_ROWS_ONE_BAD)
    api.force_login(owner)

    response = api.post(
        CREATE_URL,
        data=json.dumps({"kind": "gadget", "file_id": str(version.file_id)}),
        content_type=JSON,
    )

    assert response.status_code == 400, response.content
    assert response.json()["code"] == "invalid"
    assert "kind" in response.json()["errors"]


def test_a_document_nobody_here_can_see_is_not_found(
    api: Client,
    owner: User,
    stranger_actor: Actor,
    memory_store: dict[str, bytes],
    planted_importer: None,
) -> None:
    """Another tenant's document answers exactly as a missing one."""
    theirs = stored_csv(stranger_actor, FIVE_ROWS_ONE_BAD)
    api.force_login(owner)

    response = _stage(api, theirs.file_id)

    assert response.status_code == 404, response.content


# --- IM.4 · a member lacking the noun's create -------------------------------


def test_a_member_lacking_the_kinds_create_is_refused_at_stage(
    api: Client,
    tenant: Tenant,
    member: User,
    member_actor: Actor,
    memory_store: dict[str, bytes],
    planted_importer: None,
) -> None:
    """IM.4: `widget.create` withheld → 403 at stage, and no run exists."""
    version = stored_csv(member_actor, FIVE_ROWS_ONE_BAD)
    Grant.objects.create(
        tenant=tenant,
        membership=Membership.objects.get(user=member, tenant=tenant),
        permission="widget.create",
        effect=Grant.Effect.WITHHOLD,
    )
    api.force_login(member)

    response = _stage(api, version.file_id)

    assert response.status_code == 403, response.content
    assert response.json()["code"] == "forbidden"
    assert Import.objects.count() == 0


def test_a_member_holding_the_kinds_create_may_stage(
    api: Client,
    member: User,
    member_actor: Actor,
    memory_store: dict[str, bytes],
    planted_importer: None,
) -> None:
    """The other direction of the same bar: a plain member stages freely."""
    version = stored_csv(member_actor, FIVE_ROWS_ONE_BAD)
    api.force_login(member)

    assert _stage(api, version.file_id).status_code == 201


# --- IM.2 · the preview: every row judged, nothing written -------------------


def test_the_preview_counts_refuses_row_three_and_writes_no_widget(
    api: Client,
    owner: User,
    tenant: Tenant,
    staged: Import,
    run_check: Callable[[Import], Import],
) -> None:
    """IM.2: 5 rows, row 3 invalid → previewed, create 4 / refused 1, no noun row."""
    widgets_before = Widget.objects.for_tenant(tenant).count()

    run_check(staged)
    api.force_login(owner)
    body = api.get(_detail(staged)).json()

    assert body["status"] == "previewed"
    assert body["counts"] == {"create": 4, "update": 0, "unchanged": 0, "refused": 1}
    assert body["apply_writes"] == 4
    refused = api.get(_rows(staged), {"outcome": "refused"}).json()["items"]
    assert [row["row_no"] for row in refused] == [3]
    assert refused[0]["outcome_preview"] == "refused"
    assert refused[0]["outcome"] == ""
    assert refused[0]["refusal"]["code"] == "invalid"
    assert "name" in refused[0]["refusal"]["errors"], refused[0]["refusal"]
    assert Widget.objects.for_tenant(tenant).count() == widgets_before == 0, (
        "the dry run wrote a widget"
    )


def test_the_preview_says_update_for_a_row_that_already_exists(
    api: Client,
    owner: User,
    owner_actor: Actor,
    memory_store: dict[str, bytes],
    planted_importer: None,
    run_check: Callable[[Import], Import],
) -> None:
    """The natural-key lookup: a row whose widget exists would update it."""
    from apps.example.services import create_widget

    assert owner_actor.tenant is not None
    create_widget(tenant=owner_actor.tenant, actor=owner_actor, name="Alpha")
    version = stored_csv(owner_actor, "name,notes\nAlpha,changed\nZulu,new\n")
    run, _ = create_import(
        tenant=owner_actor.tenant, actor=owner_actor, kind="widget", file_version=version
    )

    checked = run_check(run)

    assert checked.counts == {"create": 1, "update": 1, "unchanged": 0, "refused": 0}
    alpha = ImportRow.objects.get(run=run, row_no=1)
    assert alpha.outcome_preview == "update" and alpha.object_id is not None


def test_the_rows_list_is_paged_and_ordered_by_line(
    api: Client, owner: User, staged: Import, run_check: Callable[[Import], Import]
) -> None:
    run_check(staged)
    api.force_login(owner)

    body = api.get(_rows(staged), {"limit": 2}).json()

    assert set(body) == {"items", "has_more", "next_cursor", "count"}
    assert [row["row_no"] for row in body["items"]] == [1, 2]
    assert body["has_more"] is True


# --- IM.4 · the whole file refused -------------------------------------------


@pytest.mark.parametrize(
    ("content", "content_type", "complaint"),
    [
        (b"\x89PNG\r\n\x1a\n\x00\x00\x00", "image/png", "file"),
        (b"\xff\xfe\x00n\x00a", "text/csv", "file"),
        ("title,body\nA,b\n", "text/csv", "header"),
        ("name,notes,colour\nA,b,red\n", "text/csv", "header"),
        ("", "text/csv", "header"),
    ],
    ids=["not-csv", "not-utf8", "no-header-match", "unknown-column", "empty"],
)
def test_a_file_refused_whole_fails_with_import_invalid(
    api: Client,
    owner: User,
    owner_actor: Actor,
    memory_store: dict[str, bytes],
    planted_importer: None,
    run_check: Callable[[Import], Import],
    content: str | bytes,
    content_type: str,
    complaint: str,
) -> None:
    """IM.4: not CSV / no header match → `failed`, `failure.code` `import_invalid`."""
    assert owner_actor.tenant is not None
    version = stored_csv(owner_actor, content, content_type=content_type)
    run, _ = create_import(
        tenant=owner_actor.tenant, actor=owner_actor, kind="widget", file_version=version
    )

    run_check(run)
    api.force_login(owner)
    body = api.get(_detail(run)).json()

    assert body["status"] == "failed"
    assert body["failure"]["code"] == "import_invalid"
    assert complaint in body["failure"]["errors"], body["failure"]
    assert body["failure"]["remedies"], "the registered remedies travel with it"
    assert not ImportRow.objects.filter(run=run).exists()


def test_more_than_ten_thousand_rows_is_refused_whole(
    api: Client,
    owner: User,
    owner_actor: Actor,
    tenant: Tenant,
    memory_store: dict[str, bytes],
    planted_importer: None,
    run_check: Callable[[Import], Import],
) -> None:
    """IM.4: 10,001 rows → `failed` with `import_invalid`; nothing previewed."""
    lines = "".join(f"Widget {n},\n" for n in range(MAX_IMPORT_ROWS + 1))
    version = stored_csv(owner_actor, "name,notes\n" + lines)
    run, _ = create_import(tenant=tenant, actor=owner_actor, kind="widget", file_version=version)

    checked = run_check(run)

    assert checked.status == Import.Status.FAILED
    assert checked.failure["code"] == "import_invalid"
    assert "file" in checked.failure["errors"]
    assert not ImportRow.objects.filter(run=run).exists()


def test_exactly_ten_thousand_rows_is_taken(
    owner_actor: Actor,
    tenant: Tenant,
    memory_store: dict[str, bytes],
    planted_importer: None,
    run_check: Callable[[Import], Import],
) -> None:
    """The boundary's other side: the limit itself is allowed."""
    lines = "".join(f"Widget {n},\n" for n in range(MAX_IMPORT_ROWS))
    version = stored_csv(owner_actor, "name,notes\n" + lines)
    run, _ = create_import(tenant=tenant, actor=owner_actor, kind="widget", file_version=version)

    checked = run_check(run)

    assert checked.status == Import.Status.PREVIEWED
    assert checked.count_create == MAX_IMPORT_ROWS


def test_a_quoted_field_may_span_lines_and_a_bom_is_dropped(
    owner_actor: Actor,
    tenant: Tenant,
    memory_store: dict[str, bytes],
    planted_importer: None,
    run_check: Callable[[Import], Import],
) -> None:
    """The parser is `csv` over a streamed decoder, not a line split."""
    text = '﻿name,notes\r\nAlpha,"two\r\nlines"\r\n'
    version = stored_csv(owner_actor, text)
    run, _ = create_import(tenant=tenant, actor=owner_actor, kind="widget", file_version=version)

    run_check(run)

    row = ImportRow.objects.get(run=run)
    assert row.data == {"name": "Alpha", "notes": "two\r\nlines"}


# --- the press: apply and cancel ---------------------------------------------


def test_apply_moves_a_previewed_run_to_importing_and_starts_the_apply(
    api: Client, owner: User, staged: Import, run_check: Callable[[Import], Import]
) -> None:
    run_check(staged)
    api.force_login(owner)

    response = api.post(_apply(staged))

    assert response.status_code == 200, response.content
    assert response.json()["status"] == "importing"
    assert response.json()["applied_by_id"] == str(owner.pk)
    assert (
        WorkflowRun.objects.filter(
            workflow_id__endswith=f":djb_imports:import:{staged.pk}-apply"
        ).count()
        == 1
    )
    again = api.post(_apply(staged))
    assert again.status_code == 200 and again.json()["status"] == "importing"


def test_apply_before_the_preview_is_a_conflict(api: Client, owner: User, staged: Import) -> None:
    api.force_login(owner)

    response = api.post(_apply(staged))

    assert response.status_code == 409, response.content
    assert response.json()["code"] == "conflict"


def test_apply_on_a_file_refused_whole_answers_import_invalid(
    api: Client,
    owner: User,
    owner_actor: Actor,
    tenant: Tenant,
    memory_store: dict[str, bytes],
    planted_importer: None,
    run_check: Callable[[Import], Import],
) -> None:
    """The refusal the run failed with is the one the press gets, status and all."""
    version = stored_csv(owner_actor, "title\nA\n")
    run, _ = create_import(tenant=tenant, actor=owner_actor, kind="widget", file_version=version)
    run_check(run)
    api.force_login(owner)

    response = api.post(_apply(run))

    assert response.status_code == 400, response.content
    assert response.json()["code"] == "import_invalid"
    assert "header" in response.json()["errors"]


def test_cancel_ends_a_preview_and_a_second_cancel_is_the_same_answer(
    api: Client, owner: User, staged: Import, run_check: Callable[[Import], Import]
) -> None:
    run_check(staged)
    api.force_login(owner)

    first = api.post(_cancel(staged))
    again = api.post(_cancel(staged))

    assert first.status_code == 200, first.content
    assert first.json()["status"] == "failed"
    assert first.json()["cancelled_at"] is not None
    assert again.json() == first.json()
    assert api.post(_apply(staged)).status_code == 409


def test_cancel_after_the_press_is_a_conflict(
    api: Client, owner: User, staged: Import, run_check: Callable[[Import], Import]
) -> None:
    run_check(staged)
    api.force_login(owner)
    api.post(_apply(staged))

    assert api.post(_cancel(staged)).status_code == 409


# --- reading: scoped, both siblings, pinned ----------------------------------


@pytest.fixture
def branches(tenant: Tenant, owner_actor: Actor, root_org: Organization) -> tuple[Any, Any]:
    region = create_organization(
        tenant=tenant, parent=root_org, name="Region", slug="region", actor=owner_actor
    )
    sibling = create_organization(
        tenant=tenant, parent=root_org, name="Sibling", slug="sibling", actor=owner_actor
    )
    return region, sibling


def _stage_at(owner: User, tenant: Tenant, org: Any, text: str) -> Import:
    acting = actor_for(user=owner, tenant=tenant, org=org)
    run, _ = create_import(
        tenant=tenant, actor=acting, kind="widget", file_version=stored_csv(acting, text)
    )
    return run


def test_the_list_answers_in_the_cursor_envelope(api: Client, owner: User, staged: Import) -> None:
    api.force_login(owner)

    body = api.get(LIST_URL).json()

    assert set(body) == {"items", "has_more", "next_cursor", "count"}
    assert [item["id"] for item in body["items"]] == [str(staged.pk)]


def test_another_tenants_imports_are_absent(
    api: Client,
    owner: User,
    staged: Import,
    stranger_actor: Actor,
) -> None:
    """The tenancy sibling."""
    assert stranger_actor.tenant is not None
    create_import(
        tenant=stranger_actor.tenant,
        actor=stranger_actor,
        kind="widget",
        file_version=stored_csv(stranger_actor, "name\nGlobex\n"),
    )
    api.force_login(owner)

    items = api.get(LIST_URL).json()["items"]

    assert [item["id"] for item in items] == [str(staged.pk)]


def test_a_sibling_branchs_imports_are_absent(
    api: Client,
    owner: User,
    tenant: Tenant,
    branches: tuple[Any, Any],
    memory_store: dict[str, bytes],
    planted_importer: None,
) -> None:
    """The hierarchy sibling: acting at the region, the sibling's run is not listed or found."""
    region, sibling = branches
    mine = _stage_at(owner, tenant, region, "name\nRegional\n")
    theirs = _stage_at(owner, tenant, sibling, "name\nSiblings\n")
    api.force_login(owner)

    items = api.get(LIST_URL, headers={"X-Org": region.slug}).json()["items"]

    assert [item["id"] for item in items] == [str(mine.pk)]
    assert api.get(_detail(theirs), headers={"X-Org": region.slug}).status_code == 404
    assert api.get(_rows(theirs), headers={"X-Org": region.slug}).status_code == 404


def test_the_list_query_budget(
    api: Client,
    owner: User,
    owner_actor: Actor,
    tenant: Tenant,
    memory_store: dict[str, bytes],
    planted_importer: None,
    django_assert_num_queries: Any,
) -> None:
    """Flat at seeded scale × 3: a lost `select_related` fails here."""
    for scale in (3, 9):
        while Import.objects.count() < scale:
            _stage_at(owner, tenant, owner_actor.org, f"name\nRow {Import.objects.count()}\n")
        api.force_login(owner)
        with django_assert_num_queries(LIST_QUERY_BUDGET):
            assert api.get(LIST_URL).status_code == 200


def test_the_rows_query_budget(
    api: Client,
    owner: User,
    staged: Import,
    run_check: Callable[[Import], Import],
    django_assert_num_queries: Any,
) -> None:
    run_check(staged)
    api.force_login(owner)

    with django_assert_num_queries(ROWS_QUERY_BUDGET):
        assert api.get(_rows(staged)).status_code == 200


def test_the_published_kind_enum_is_the_declared_importers(planted_importer: None) -> None:
    """`ImportIn.kind`'s values are derived from `IMPORTERS` when the document is built."""
    from config.api import api as mounted

    document = json.loads(json.dumps(mounted.get_openapi_schema()))

    kind = document["components"]["schemas"]["ImportIn"]["properties"]["kind"]
    assert kind["enum"] == ["widget"]
