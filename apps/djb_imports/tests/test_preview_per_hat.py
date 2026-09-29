"""The preview and the apply find a file's rows at ONE hat — the run's.

An import is staged at the acting hat and applied there: the apply finds the
existing row by its natural key at that hat and creates when there is none. So
the preview — the dry run a person reads before pressing apply — has to look in
the same place, or it promises `update` for a line the apply will `create` (or
refuse). `Importer.natural_key` is asked with the actor wearing the run's hat,
and the worked example's `apply` asks the same function; this test drives both
through the REAL example importer (no plant), at two hats, over one tenant
holding a row at each.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from apps.accounts.models import User
from apps.core.actor import Actor, actor_for
from apps.core.models import Organization, Tenant
from apps.core.services import create_organization
from apps.djb_imports.models import Import, ImportRow
from apps.djb_imports.selectors import get_importer
from apps.djb_imports.services import apply_import_row, create_import
from apps.djb_imports.tests.conftest import stored_csv
from apps.example.models import Widget
from apps.example.services import create_widget

pytestmark = pytest.mark.django_db

#: What each settled outcome means the preview should have said.
PROMISED = {"created": "create", "updated": "update", "unchanged": "update"}

#: One line keyed to the root's widget, one to the branch's — named apart from
#: both, so a line the apply creates never meets the name-per-owner uniqueness.
FILE = "external_ref,name,notes\r\nCRM-ROOT,Root line,changed\r\nCRM-A,Branch line,changed\r\n"


def _stage_check_apply(
    actor: Actor, run_check: Callable[[Import], Import]
) -> list[tuple[str, str, Any, Any]]:
    """Stage FILE at the actor's hat, preview it, apply every row as the activity does."""
    assert actor.tenant is not None and actor.org is not None
    version = stored_csv(actor, FILE)
    run, _ = create_import(tenant=actor.tenant, actor=actor, kind="widget", file_version=version)
    run_check(run)
    # The apply activity's person: the presser, wearing the RUN's hat.
    person = actor_for(user=actor.user, tenant=actor.tenant, kind="agent", org=run.organization)
    settled = []
    for row in ImportRow.objects.filter(run=run).order_by("row_no"):
        preview, previewed_id = str(row.outcome_preview), row.object_id
        done = apply_import_row(tenant=actor.tenant, actor=person, row=row)
        settled.append((preview, str(done.outcome), previewed_id, done.object_id))
    return settled


@pytest.fixture
def two_hats(
    tenant: Tenant, root_org: Organization, owner: User, owner_actor: Actor
) -> tuple[Actor, Actor]:
    """The owner at the root and at a branch, and one widget keyed at each."""
    branch = create_organization(
        tenant=tenant, parent=root_org, name="Branch A", slug="branch-a", actor=owner_actor
    )
    at_branch = actor_for(user=owner, tenant=tenant, org=branch)
    create_widget(
        tenant=tenant, actor=owner_actor, name="Root's own", notes="", external_ref="CRM-ROOT"
    )
    create_widget(
        tenant=tenant, actor=at_branch, name="Branch's own", notes="", external_ref="CRM-A"
    )
    return owner_actor, at_branch


@pytest.mark.parametrize("hat", ["root", "branch"])
def test_the_preview_promises_what_the_apply_does_at_that_hat(
    two_hats: tuple[Actor, Actor],
    hat: str,
    memory_store: dict[str, bytes],
    run_check: Callable[[Import], Import],
) -> None:
    at_root, at_branch = two_hats
    actor = at_root if hat == "root" else at_branch

    settled = _stage_check_apply(actor, run_check)

    for preview, outcome, previewed_id, applied_id in settled:
        assert outcome in PROMISED, settled
        assert PROMISED[outcome] == preview, (hat, settled)
        if preview == "update":
            assert previewed_id == applied_id, (hat, settled)
    # Each hat finds ITS row and creates the other hat's line at itself.
    assert sorted(p for p, *_ in settled) == ["create", "update"], (hat, settled)


def test_natural_key_is_asked_with_the_hat(two_hats: tuple[Actor, Actor], tenant: Tenant) -> None:
    at_root, at_branch = two_hats
    importer = get_importer("widget")
    assert importer is not None
    row = importer.row.model_validate({"external_ref": "CRM-A", "name": "x", "notes": ""})

    found_at_branch = importer.natural_key(tenant=tenant, actor=at_branch, row=row)
    found_at_root = importer.natural_key(tenant=tenant, actor=at_root, row=row)

    assert found_at_branch is not None
    assert found_at_branch.pk == Widget.objects.get(external_ref="CRM-A").pk
    assert found_at_root is None
