"""The world core's attachment conformance tests are measured against.

**The population is every `"*"` repointer app, discovered** — each app whose
`merge_repointers.py` answers for every noun (`core.verbs.hook`), which is
exactly the set of polymorphic attach owners a merge must carry. Each of them
ships `apps/<label>/tests/attach_specimen.py::attach(*, tenant, actor,
subject)`, the one hook core can call to plant "something attached to this row"
without knowing what that something is. An owner without one FAILS by name
(`specimen_of`); it is never skipped, because a skipped owner is an owner whose
promises nobody measured.

**The subjects are planted** (`isolated_apps` + a `schema_editor` table inside
the test's transaction, the `test_archivable.py` shape) and registered as kinds
for the length of a test, so the conformance does not lean on any product noun:
`ZzzCase`, org-scoped and archivable (the merge's two records), and
`ZzzNotebook`, TENANT-scoped (the landing law's second case). Both declare every
attach owner's word in `attachments`. `ZzzBareCase` declares none — the noun a
repointer must pass over as a no-op counted 0 (a mergeable noun need not take
every attachment the tree has an owner for).
"""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from django.db import connection, models

from apps.accounts.models import User
from apps.core import authz
from apps.core.actor import Actor, actor_for
from apps.core.models import Archivable, Organization, OrgScopedModel, Tenant, TenantScopedModel
from apps.core.services import create_organization
from apps.core.tests.isolation import isolated_apps
from apps.core.verbs import Repointer, hook


def star_owners() -> list[tuple[str, Repointer]]:
    """`(app label, its "*" repointer)` for every app that answers for every noun."""
    found: list[tuple[str, Repointer]] = []
    for config, declared in hook("merge_repointers"):
        entry = declared.get("*")
        if isinstance(entry, Repointer):
            found.append((config.label, entry))
    return found


def specimen_of(label: str) -> Callable[..., Any]:
    """`apps/<label>/tests/attach_specimen.py::attach`, or a FAILURE naming the app."""
    module_name = f"apps.{label}.tests.attach_specimen"
    if importlib.util.find_spec(module_name) is None:
        pytest.fail(
            f"apps/{label} answers for every noun in its merge_repointers.py and ships no "
            f'apps/{label}/tests/attach_specimen.py — every "*" repointer app ships '
            "`attach(*, tenant, actor, subject)` so core can measure its promises.",
            pytrace=False,
        )
    attach: Callable[..., Any] | None = getattr(
        importlib.import_module(module_name), "attach", None
    )
    if attach is None or not callable(attach):
        pytest.fail(
            f"apps/{label}/tests/attach_specimen.py exports no callable `attach`.",
            pytrace=False,
        )
    return attach


@dataclass
class World:
    tenant: Tenant
    root: Organization
    branch_a: Organization
    branch_b: Organization
    owner_at_root: Actor
    owner_at_a: Actor
    owner_at_b: Actor
    case: Any
    notebook: Any
    bare: Any


#: Every attach owner's word, declared on both planted subjects.
ATTACH_WORDS = ("notes", "files", "tags")


@pytest.fixture(name="attach_world")
def attach_world_fixture(
    db: None,
    monkeypatch: pytest.MonkeyPatch,
    tenant: Tenant,
    root_org: Organization,
    owner: User,
    owner_actor: Actor,
) -> Iterator[World]:
    with isolated_apps("apps.core", "apps.accounts") as registry:
        assert registry is not None
        registry.register_model("accounts", User)

        class ZzzCase(OrgScopedModel, Archivable):
            """An org-scoped record that takes every attachment."""

            attachments = ATTACH_WORDS
            name = models.CharField(max_length=50)

            class Meta:
                app_label = "core"

        class ZzzNotebook(TenantScopedModel):
            """A TENANT-WIDE record that takes every attachment — it has no branch."""

            attachments = ATTACH_WORDS
            name = models.CharField(max_length=50)

            class Meta:
                app_label = "core"

        class ZzzBareCase(OrgScopedModel, Archivable):
            """An org-scoped record that takes NO attachment — a repointer's no-op."""

            attachments: tuple[str, ...] = ()
            name = models.CharField(max_length=50)

            class Meta:
                app_label = "core"

        with connection.schema_editor() as editor:
            editor.create_model(ZzzCase)
            editor.create_model(ZzzNotebook)
            editor.create_model(ZzzBareCase)
        kinds = dict(authz.kind_registry())
        for model in (ZzzCase, ZzzNotebook, ZzzBareCase):
            kind = authz.kind_of(model)
            assert kind is not None
            kinds[kind] = model
        monkeypatch.setattr(authz, "_kinds", kinds)
        branch_a = create_organization(
            tenant=tenant, parent=root_org, name="Branch A", slug="branch-a", actor=owner_actor
        )
        branch_b = create_organization(
            tenant=tenant, parent=root_org, name="Branch B", slug="branch-b", actor=owner_actor
        )
        yield World(
            tenant=tenant,
            root=root_org,
            branch_a=branch_a,
            branch_b=branch_b,
            owner_at_root=owner_actor,
            owner_at_a=actor_for(user=owner, tenant=tenant, org=branch_a),
            owner_at_b=actor_for(user=owner, tenant=tenant, org=branch_b),
            case=ZzzCase,
            notebook=ZzzNotebook,
            bare=ZzzBareCase,
        )


def owners_ids() -> list[str]:
    """The parametrize ids: every `"*"` owner's label, read when the module is collected."""
    return [label for label, _ in star_owners()]
