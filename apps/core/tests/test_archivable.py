"""`Archivable`: the mixin, its two refusals, and the read discipline it brings.

The noun is built HERE, in the test, and torn down with it — `isolate_apps`
plus a `schema_editor` table inside the test's transaction, the shape
`test_inheritance.py` uses — so core proves its own primitive against a model
shaped exactly like the one a product writes, without shipping a table nothing
in the template uses and without a migration.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from django.db import connection, models

from apps.accounts.models import User
from apps.core.models import (
    Archivable,
    Organization,
    OrgScopedModel,
    Tenant,
    archivable_models,
    is_archivable,
)
from apps.core.tests.isolation import isolated_apps
from apps.core.time import now
from apps.example.models import WidgetEntry


@dataclass
class Built:
    shelf: Any
    plain: Any


@pytest.fixture
def built(db: None) -> Iterator[Built]:
    with isolated_apps("apps.core", "apps.accounts") as registry:
        # The mixin's `archived_by` names the user model by its settings STRING,
        # which an isolated registry resolves only if the model is in it.
        assert registry is not None
        registry.register_model("accounts", User)

        class ZzzShelf(OrgScopedModel, Archivable):
            """A noun that leaves the book by being archived."""

            label = models.CharField(max_length=50)

            class Meta:
                app_label = "core"

        class ZzzPlain(OrgScopedModel):
            """The same shape, undeclared."""

            label = models.CharField(max_length=50)

            class Meta:
                app_label = "core"

        with connection.schema_editor() as editor:
            editor.create_model(ZzzShelf)
            editor.create_model(ZzzPlain)
        # No table teardown: the DDL ran inside the transaction pytest-django
        # wraps this test in, and Postgres rolls it back with everything else.
        yield Built(ZzzShelf, ZzzPlain)


def _shelf(built: Built, tenant: Tenant, org: Organization, label: str, **extra: Any) -> Any:
    return built.shelf.objects.create(tenant=tenant, organization=org, label=label, **extra)


# --- A1.1 · the mixin and its two refusals -----------------------------------


@isolated_apps("apps.core", "apps.accounts")
def test_the_mixin_brings_two_columns_and_the_marker() -> None:
    class ZzzA(OrgScopedModel, Archivable):
        class Meta:
            app_label = "core"

    at = ZzzA._meta.get_field("archived_at")
    by = ZzzA._meta.get_field("archived_by")
    assert isinstance(at, models.DateTimeField) and at.null
    assert isinstance(by, models.ForeignKey) and by.null
    assert by.remote_field.on_delete is models.PROTECT
    assert by.remote_field.related_name == "+"
    assert is_archivable(ZzzA)
    assert ZzzA in archivable_models(registry=ZzzA._meta.apps)


@isolated_apps("apps.core", "apps.accounts")
def test_the_mixin_listed_before_the_scoped_base_is_refused() -> None:
    with pytest.raises(TypeError) as caught:

        class ZzzA(Archivable, OrgScopedModel):
            class Meta:
                app_label = "core"

    assert "lists `Archivable` before its scoped base" in str(caught.value)
    assert "class Noun(OrgScopedModel, Archivable)" in str(caught.value)


@isolated_apps("apps.core", "apps.accounts")
def test_archivable_beside_append_only_is_refused_naming_d8() -> None:
    with pytest.raises(TypeError) as caught:

        class ZzzLedger(OrgScopedModel, Archivable):
            append_only = True

            class Meta:
                app_label = "core"

    assert "They are disjoint (D8)" in str(caught.value)
    assert "`append_only = True` and `Archivable`" in str(caught.value)


# --- A1.2 · for_tenant hides; two widenings; nothing else moves --------------


def test_for_tenant_leaves_archived_rows_out(
    built: Built, tenant: Tenant, root_org: Organization, owner: User
) -> None:
    live = _shelf(built, tenant, root_org, "live")
    gone = _shelf(built, tenant, root_org, "gone", archived_at=now(), archived_by=owner)

    read = built.shelf.objects.for_tenant(tenant)
    assert [row.pk for row in read] == [live.pk]
    assert {row.pk for row in read.including_archived()} == {live.pk, gone.pk}
    assert [row.pk for row in read.archived_only()] == [gone.pk]
    assert gone.is_archived and not live.is_archived


def test_the_widenings_are_legal_before_the_scope_and_keep_the_tenant(
    built: Built,
    tenant: Tenant,
    other_tenant: Tenant,
    root_org: Organization,
    other_root_org: Organization,
    owner: User,
) -> None:
    mine = _shelf(built, tenant, root_org, "mine", archived_at=now())
    _shelf(built, other_tenant, other_root_org, "theirs", archived_at=now())

    widened_first = built.shelf.objects.including_archived().for_tenant(tenant)
    assert [row.pk for row in widened_first] == [mine.pk]
    only_first = built.shelf.objects.archived_only().for_tenant(tenant)
    assert [row.pk for row in only_first] == [mine.pk]
    # The hat still narrows a widened read, exactly as it narrowed the live one.
    through_hat = built.shelf.objects.for_tenant(tenant).visible_to(root_org)
    assert [row.pk for row in through_hat.including_archived()] == [mine.pk]
    assert list(built.shelf.objects.for_tenant(None).including_archived()) == []


def test_both_widenings_refuse_on_a_model_that_did_not_declare(
    built: Built, tenant: Tenant
) -> None:
    with pytest.raises(TypeError, match="has not declared `Archivable`"):
        built.plain.objects.for_tenant(tenant).including_archived()
    with pytest.raises(TypeError, match="has not declared `Archivable`"):
        built.plain.objects.archived_only()


def test_archived_only_then_including_archived_refuses(built: Built, tenant: Tenant) -> None:
    with pytest.raises(TypeError, match="second answer to one question"):
        built.shelf.objects.for_tenant(tenant).archived_only().including_archived()


def test_an_or_combined_read_refuses_to_guess(built: Built, tenant: Tenant) -> None:
    left = built.shelf.objects.for_tenant(tenant).filter(label="a")
    right = built.shelf.objects.for_tenant(tenant).filter(label="b")
    with pytest.raises(TypeError, match="OR-combined"):
        (left | right).including_archived()


def test_a_non_archivable_models_read_is_byte_identical(tenant: Tenant) -> None:
    """The hide costs a model that did not declare the mixin NOTHING — not a clause.

    `for_tenant` on an undeclared model is the same SQL `filter(tenant=…)`
    builds, which is exactly what `for_tenant` was before the mixin existed
    (the baseline's body was `return self.filter(tenant=tenant)`). `WidgetEntry`
    is the witness because it is append-only and so can never adopt the mixin.
    """
    scoped = str(WidgetEntry.objects.for_tenant(tenant).query)
    assert scoped == str(WidgetEntry.objects.filter(tenant=tenant).query)
    assert "archived_at" not in scoped
