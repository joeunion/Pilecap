"""A duplicate key's constraint is the MODEL's, declared in its `Meta` — never the field's.

The `(tenant, duplicated_from, duplicate_key)` partial unique constraint is what
makes a repeated press answer the first copy. It used to be ADDED by the key
field as it was contributed to a class — and a migration renders its model
states into classes too, so a state that did not hold the constraint yet (a
`CreateModel` the autodetector split an `AddConstraint` out of, which a circular
foreign key forces) rendered into a model that did: the table was created with
the constraint, and the `AddConstraint` after it failed `DuplicateTable` on a
fresh database. A product's first new duplicable noun is exactly that migration.

So the state is the truth: the field adds nothing, the noun declares
`duplicate_key_constraint()` in its own `Meta`, and a duplicable noun that did
not is a system-check error naming the line to add — `makemigrations` runs the
checks, so the omission is refused before a migration is written.
"""

from __future__ import annotations

import pytest
from django.apps import apps as django_apps
from django.db import models
from django.db.migrations.state import ModelState, ProjectState

from apps.accounts.models import User
from apps.core.models import (
    DUPLICATE_KEY_CHECK_ID,
    Duplicable,
    Duplicate,
    OrgScopedModel,
    duplicate_key_constraint,
)
from apps.core.tests.isolation import isolated_apps

KEY_SUFFIX = "_duplicate_key"


def _keys(model: type[models.Model]) -> list[str]:
    return [c.name for c in model._meta.constraints if c.name.endswith(KEY_SUFFIX)]


@isolated_apps("apps.core", "apps.accounts")
def test_the_declared_constraint_names_itself_after_the_model() -> None:
    class ZzzPlate(OrgScopedModel, Duplicable):
        duplicate = Duplicate(copies=("label",))
        label = models.CharField(max_length=20)

        class Meta(OrgScopedModel.Meta):
            app_label = "core"
            constraints = [duplicate_key_constraint()]

    (declared,) = [c for c in ZzzPlate._meta.constraints if c.name.endswith(KEY_SUFFIX)]
    assert declared.name == "core_zzzplate_duplicate_key"
    assert isinstance(declared, models.UniqueConstraint)
    assert declared.fields == ("tenant", "duplicated_from", "duplicate_key")
    assert declared.condition == ~models.Q(duplicate_key="")
    assert [e.id for e in ZzzPlate.check() if e.id == DUPLICATE_KEY_CHECK_ID] == []


@isolated_apps("apps.core", "apps.accounts")
def test_a_duplicable_noun_without_the_constraint_is_a_check_error_naming_the_line() -> None:
    class ZzzBarePlate(OrgScopedModel, Duplicable):
        duplicate = Duplicate(copies=("label",))
        label = models.CharField(max_length=20)

        class Meta(OrgScopedModel.Meta):
            app_label = "core"

    # The field brought nothing of its own.
    assert _keys(ZzzBarePlate) == []
    found = [e for e in ZzzBarePlate.check() if e.id == DUPLICATE_KEY_CHECK_ID]
    assert len(found) == 1, [e.id for e in ZzzBarePlate.check()]
    assert "duplicate_key_constraint()" in found[0].msg
    assert "ZzzBarePlate" in found[0].msg


def test_a_migration_state_without_the_constraint_renders_a_model_without_it(
    db: None,
) -> None:
    """The mechanism the fresh-database migrate died of, in-process.

    A `CreateModel` whose constraint the autodetector moved to a later
    `AddConstraint` is a model STATE without it. Rendered, it must be a model
    without it — the table `CreateModel` builds is the rendered class's, and a
    constraint the class invented is one the `AddConstraint` then creates twice.
    """
    with isolated_apps("apps.core", "apps.accounts") as registry:
        assert registry is not None
        registry.register_model("accounts", User)

        class ZzzStencilPlate(OrgScopedModel, Duplicable):
            duplicate = Duplicate(copies=("label",))
            label = models.CharField(max_length=20)

            class Meta(OrgScopedModel.Meta):
                app_label = "core"
                constraints = [duplicate_key_constraint()]

        state = ModelState.from_model(ZzzStencilPlate)
    assert [c.name for c in state.options["constraints"]] == ["core_zzzstencilplate_duplicate_key"]
    state.options["constraints"] = []

    project = ProjectState.from_apps(django_apps)
    project.add_model(state)
    rendered = project.apps.get_model("core", "zzzstencilplate")

    assert _keys(rendered) == []


@pytest.mark.parametrize("app_label", ["example"])
def test_the_worked_example_declares_its_key_in_its_meta(app_label: str) -> None:
    """Every real duplicable noun carries the constraint by declaration, and checks clean."""
    duplicable = [
        model
        for model in django_apps.get_app_config(app_label).get_models()
        if getattr(model, "duplicable", False)
    ]
    assert duplicable, "the worked example declares no duplicable noun — this measures nothing"
    for model in duplicable:
        assert _keys(model) == [f"{model._meta.app_label}_{model._meta.model_name}{KEY_SUFFIX}"]
        assert [e.id for e in model.check() if e.id == DUPLICATE_KEY_CHECK_ID] == []
