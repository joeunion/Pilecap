"""`core.verbs.duplicate_row`: save-as-new, by the noun's own declaration.

`copies` carry across, `resets` fall back to the model's default, the copy lands
at the acting hat, owned children copy only when named, an append-only child
never copies, and a repeated press with one key answers the first copy — the
`(tenant, duplicated_from, duplicate_key)` partial unique constraint every
duplicable noun declares in its own `Meta` (`duplicate_key_constraint()`). Nouns planted
(`isolated_apps` + a `schema_editor` table inside the test's transaction).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError, connection, models, transaction

from apps.accounts.models import User
from apps.core.exceptions import Invalid
from apps.core.models import (
    Archivable,
    Duplicable,
    Duplicate,
    Organization,
    OrgScopedModel,
    Tenant,
    duplicate_key_constraint,
    is_duplicable,
)
from apps.core.services import create_organization
from apps.core.tests.isolation import isolated_apps
from apps.core.verbs import duplicate_fields, duplicate_row


@dataclass
class Planted:
    stencil: Any
    part: Any
    log: Any


@pytest.fixture
def planted(db: None) -> Iterator[Planted]:
    with isolated_apps("apps.core", "apps.accounts") as registry:
        assert registry is not None
        registry.register_model("accounts", User)

        class ZzzStencil(OrgScopedModel, Archivable, Duplicable):
            """A noun a person copies to start from."""

            duplicate = Duplicate(copies=("name", "shade", "parts"), resets=("used_at",))
            name = models.CharField(max_length=50)
            shade = models.CharField(max_length=20, blank=True, default="")
            used_at = models.DateTimeField(null=True, blank=True)

            class Meta:
                app_label = "core"
                constraints = [duplicate_key_constraint()]

        class ZzzPart(OrgScopedModel):
            """An owned, MUTABLE child: copies when the declaration names it."""

            derive_org_from = "stencil"
            stencil = models.ForeignKey(ZzzStencil, on_delete=models.CASCADE, related_name="parts")
            label = models.CharField(max_length=20)

            class Meta:
                app_label = "core"

        class ZzzUseLog(OrgScopedModel):
            """An APPEND-ONLY child: the source's history, never the copy's."""

            append_only = True
            derive_org_from = "stencil"
            stencil = models.ForeignKey(ZzzStencil, on_delete=models.CASCADE, related_name="uses")

            class Meta:
                app_label = "core"

        with connection.schema_editor() as editor:
            for model in (ZzzStencil, ZzzPart, ZzzUseLog):
                editor.create_model(model)
        yield Planted(ZzzStencil, ZzzPart, ZzzUseLog)


@pytest.fixture
def branch(tenant: Tenant, root_org: Organization, owner_actor: Any) -> Organization:
    return create_organization(
        tenant=tenant, parent=root_org, name="Branch A", slug="branch-a", actor=owner_actor
    )


def _stencil(planted: Planted, tenant: Tenant, org: Organization) -> Any:
    source = planted.stencil.objects.create(
        tenant=tenant, organization=org, name="Invoice", shade="blue", used_at="2026-01-01T00:00Z"
    )
    planted.part.objects.create(tenant=tenant, organization=org, stencil=source, label="head")
    planted.part.objects.create(tenant=tenant, organization=org, stencil=source, label="foot")
    planted.log.objects.create(tenant=tenant, organization=org, stencil=source)
    return source


def _duplicate(tenant: Tenant, row: Any, org: Organization, key: str = "") -> tuple[Any, bool]:
    with transaction.atomic():
        return duplicate_row(tenant=tenant, row=row, organization=org, idempotency_key=key)


def test_the_marker_and_the_classified_population(planted: Planted) -> None:
    assert is_duplicable(planted.stencil)
    assert duplicate_fields(planted.stencil) == ["name", "shade", "used_at"]


def test_copies_carry_resets_fall_back_and_the_copy_lands_at_the_hat(
    planted: Planted, tenant: Tenant, root_org: Organization, branch: Organization
) -> None:
    source = _stencil(planted, tenant, root_org)

    copy, created = _duplicate(tenant, source, branch)

    assert created is True
    assert copy.pk != source.pk
    assert (copy.name, copy.shade) == ("Invoice", "blue")
    assert copy.used_at is None
    assert copy.organization_id == branch.pk
    assert copy.duplicated_from_id == source.pk
    assert copy.archived_at is None


def test_owned_children_copy_when_named_and_the_ledger_never_does(
    planted: Planted, tenant: Tenant, root_org: Organization, branch: Organization
) -> None:
    source = _stencil(planted, tenant, root_org)

    copy, _ = _duplicate(tenant, source, branch)

    parts = planted.part.objects.for_tenant(tenant).filter(stencil=copy)
    assert sorted(parts.values_list("label", flat=True)) == ["foot", "head"]
    assert set(parts.values_list("organization_id", flat=True)) == {branch.pk}
    # The source keeps its own two parts and its ledger; the copy has no ledger.
    assert planted.part.objects.for_tenant(tenant).filter(stencil=source).count() == 2
    assert planted.log.objects.for_tenant(tenant).filter(stencil=copy).count() == 0
    assert planted.log.objects.for_tenant(tenant).filter(stencil=source).count() == 1


def test_naming_an_append_only_child_in_copies_is_refused(
    planted: Planted,
    monkeypatch: pytest.MonkeyPatch,
    tenant: Tenant,
    root_org: Organization,
) -> None:
    source = _stencil(planted, tenant, root_org)
    monkeypatch.setattr(planted.stencil, "duplicate", Duplicate(copies=("name", "uses")))
    with pytest.raises(ImproperlyConfigured, match="append-only child"):
        _duplicate(tenant, source, root_org)


def test_a_repeated_key_answers_the_first_copy(
    planted: Planted, tenant: Tenant, root_org: Organization
) -> None:
    source = _stencil(planted, tenant, root_org)

    first, made = _duplicate(tenant, source, root_org, key="press-1")
    again, made_again = _duplicate(tenant, source, root_org, key="press-1")
    other, made_other = _duplicate(tenant, source, root_org, key="press-2")
    keyless_a, _ = _duplicate(tenant, source, root_org)
    keyless_b, _ = _duplicate(tenant, source, root_org)

    assert (made, made_again, made_other) == (True, False, True)
    assert again.pk == first.pk
    assert other.pk != first.pk
    assert keyless_a.pk != keyless_b.pk  # no key, no promise: each press is a copy


def test_the_partial_unique_constraint_is_the_guarantee(
    planted: Planted, tenant: Tenant, root_org: Organization
) -> None:
    names = {constraint.name for constraint in planted.stencil._meta.constraints}
    assert "core_zzzstencil_duplicate_key" in names
    source = _stencil(planted, tenant, root_org)
    _duplicate(tenant, source, root_org, key="press-1")
    with pytest.raises(IntegrityError), transaction.atomic():
        planted.stencil.objects.create(
            tenant=tenant,
            organization=root_org,
            name="racer",
            duplicated_from=source,
            duplicate_key="press-1",
        )


# --- a noun with an owner and a unique name: `fill`, and a clash that refuses ---
#
# The stencil above has no owner and no uniqueness, which is why the seam's first
# real noun could not be copied at all: a NOT NULL owner in `resets` failed the
# copy's one save, and a unique constraint over copied fields collided with the
# source on it — both as a database error, which a door answers 500. This badge
# is that noun's shape, planted: the owner FK and the uniqueness the worked
# example carries.


@pytest.fixture
def badges(db: None) -> Iterator[Any]:
    with isolated_apps("apps.core", "apps.accounts") as registry:
        assert registry is not None
        registry.register_model("accounts", User)

        class ZzzBadge(OrgScopedModel, Archivable, Duplicable):
            """A noun a person owns, named uniquely per owner."""

            duplicate = Duplicate(copies=("shade",), resets=("name", "owner"))
            name = models.CharField(max_length=50)
            owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
            shade = models.CharField(max_length=20, blank=True, default="")

            class Meta(OrgScopedModel.Meta):
                app_label = "core"
                constraints = [
                    models.UniqueConstraint(
                        fields=["tenant", "owner", "name"], name="zzzbadge_unique_name_per_owner"
                    ),
                    duplicate_key_constraint(),
                ]

        with connection.schema_editor() as editor:
            editor.create_model(ZzzBadge)
        yield ZzzBadge


def _badge(model: Any, tenant: Tenant, org: Organization, owner: Any) -> Any:
    return model.objects.create(
        tenant=tenant, organization=org, owner=owner, name="Gold", shade="amber"
    )


def test_a_reset_owner_with_no_fill_is_invalid_naming_it_never_a_500(
    badges: Any, tenant: Tenant, root_org: Organization, owner: User
) -> None:
    source = _badge(badges, tenant, root_org, owner)

    with pytest.raises(Invalid) as refused:
        _duplicate(tenant, source, root_org)

    assert "owner" in refused.value.errors
    assert badges.objects.for_tenant(tenant).count() == 1


def test_fill_sets_what_resets_before_the_one_save(
    badges: Any, tenant: Tenant, root_org: Organization, owner: User, member: User
) -> None:
    source = _badge(badges, tenant, root_org, owner)

    with transaction.atomic():
        copy, created = duplicate_row(
            tenant=tenant,
            row=source,
            organization=root_org,
            fill={"owner": member, "name": "Copy of Gold"},
        )

    assert created is True
    assert (copy.owner_id, copy.name, copy.shade) == (member.pk, "Copy of Gold", "amber")
    assert copy.duplicated_from_id == source.pk


def test_a_copy_that_clashes_on_a_unique_is_invalid_and_nothing_is_written(
    badges: Any, tenant: Tenant, root_org: Organization, owner: User
) -> None:
    source = _badge(badges, tenant, root_org, owner)
    fill = {"owner": owner, "name": "Copy of Gold"}
    with transaction.atomic():
        duplicate_row(tenant=tenant, row=source, organization=root_org, fill=fill)

    with pytest.raises(Invalid):
        with transaction.atomic():
            duplicate_row(tenant=tenant, row=source, organization=root_org, fill=fill)

    assert badges.objects.for_tenant(tenant).count() == 2


def test_fill_names_only_what_resets(
    badges: Any, tenant: Tenant, root_org: Organization, owner: User
) -> None:
    source = _badge(badges, tenant, root_org, owner)
    with pytest.raises(TypeError, match="shade"):
        with transaction.atomic():
            duplicate_row(tenant=tenant, row=source, organization=root_org, fill={"shade": "red"})
    with pytest.raises(TypeError, match="nickname"):
        with transaction.atomic():
            duplicate_row(tenant=tenant, row=source, organization=root_org, fill={"nickname": "x"})
