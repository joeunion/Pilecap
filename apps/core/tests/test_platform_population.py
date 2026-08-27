"""The audit trail's platform population — ADR core-8, mirroring workflows-3.

`@service` used to write its row only when the `tenant` it was handed was not
None, so every action the *deployment* takes rather than a customer — erasing
somebody who belongs nowhere, syncing workforce identity, revoking a Zitadel
credential that is no workspace's — was logged and never audited. The one
compliance-shaped trail had a hole exactly where the compliance actions are.

`AuditEntry.tenant` is nullable now, and **null is a declared population rather
than a loosening**. That distinction is the whole rung, so it is what this
module measures, one property per test:

* the flip writes a row where nothing was written before, and the **old
  predicate is reconstructed here** so the change is demonstrated rather than
  asserted (A11: the pre-fix absence, in the tree, still failing);
* `for_tenant(t)` returns no null row, for any `t`, and `for_tenant(None)` is
  still empty — "unresolved" and "the deployment's own" stay different facts;
* the admin changelist, which is `for_tenant` underneath, shows none of them
  under any staff hat;
* `for_platform()` reads them, and is the only thing that does;
* **rule 20 is unchanged over the widened population**: a null-tenant row is
  exactly as unrewritable and undeletable as a tenanted one;
* a service that declares no `tenant` at all is still not audited — the
  population widened, it did not become everything.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from django.contrib import admin
from django.test import RequestFactory

from apps.core.actor import Actor, system_actor
from apps.core.audit import AuditEntry, AuditImmutable
from apps.core.models import Tenant
from apps.core.service import service

pytestmark = pytest.mark.django_db


@service
def purge_the_deployment(*, tenant: Tenant | None, actor: Actor | None = None) -> str:
    """A stand-in for the real members of the population, declared once here.

    Module level rather than inside each test because `@service` reads the
    signature at *decoration* time (that is the point of ADR core-8's flip), and
    a decorator whose input is a fixture would measure the fixture.
    """
    return "purged"


@service
def record_housekeeping(*, note: str) -> str:
    """The other side of the line: a service that is about no tenant at all."""
    return note


# --- The flip, and the absence it replaced ------------------------------------


def test_a_declared_tenant_of_none_is_audited_into_the_platform_population(
    db: None,
) -> None:
    """The row that previously did not exist."""
    AuditEntry.objects.all().delete()

    purge_the_deployment(tenant=None, actor=system_actor())

    entry = AuditEntry.objects.for_platform().get()
    assert entry.action == "core.purge_the_deployment"
    assert entry.tenant_id is None
    assert entry.outcome == AuditEntry.Outcome.OK


def test_the_predicate_this_rung_replaced_would_have_written_nothing() -> None:
    """**A11: the pre-fix absence, reconstructed rather than remembered.**

    The old branch was `"tenant" in kwargs and tenant is not None`. Asserting
    "there is a row now" only proves the new behaviour; it does not prove the
    row is *new*. So the old predicate is spelled out here and evaluated against
    the same call, and it answers False — which is the hole, still visible, in
    the one place a future reader will look for it.

    It also pins the second half of the flip: the new predicate reads the
    **declaration**, so a service that never mentions a tenant is still outside
    the population. Presence-in-kwargs would have been a third answer again —
    `sync_workforce_identity_config(actor=...)` relies on its default and would
    have stayed unaudited, which is a member of the very hole the ADR names.
    """
    call = {"tenant": None, "actor": system_actor()}
    old = "tenant" in call and call["tenant"] is not None
    assert old is False

    def declares(fn: Any) -> bool:
        return any(
            p.name == "tenant" and p.kind is inspect.Parameter.KEYWORD_ONLY
            for p in inspect.signature(fn).parameters.values()
        )

    assert declares(purge_the_deployment.__wrapped__) is True  # type: ignore[attr-defined]
    assert declares(record_housekeeping.__wrapped__) is False  # type: ignore[attr-defined]


def test_a_service_that_declares_no_tenant_is_still_not_audited(db: None) -> None:
    """The population widened; it did not become everything."""
    AuditEntry.objects.all().delete()

    record_housekeeping(note="tidying")

    assert AuditEntry.objects.count() == 0


def test_a_platform_failure_is_audited_too(db: None) -> None:
    """The error row follows the success row into the population.

    A trail that records what the deployment did and not what it tried is half a
    trail, and the failing half is the one an incident review opens first.
    """
    from apps.core.exceptions import Invalid

    AuditEntry.objects.all().delete()

    @service
    def refuse_the_deployment(*, tenant: Tenant | None) -> None:
        raise Invalid({"tenant": ["the deployment refuses"]})

    with pytest.raises(Invalid):
        refuse_the_deployment(tenant=None)

    entry = AuditEntry.objects.for_platform().get()
    assert entry.outcome == AuditEntry.Outcome.ERROR
    assert entry.tenant_id is None


# --- The fence: for_tenant can never see it -----------------------------------


def test_for_tenant_returns_no_platform_row_for_any_tenant(
    tenant: Tenant, other_tenant: Tenant, owner_actor: Actor
) -> None:
    """Every tenant door is `for_tenant` underneath, so this is all of them."""
    AuditEntry.objects.all().delete()

    purge_the_deployment(tenant=None, actor=system_actor())
    purge_the_deployment(tenant=tenant, actor=owner_actor)

    for each in (tenant, other_tenant):
        rows = AuditEntry.objects.for_tenant(each).filter(action="core.purge_the_deployment")
        assert all(row.tenant_id is not None for row in rows)
    assert AuditEntry.objects.for_tenant(tenant).count() == 1
    assert AuditEntry.objects.for_tenant(other_tenant).count() == 0


def test_for_tenant_none_is_still_empty(db: None) -> None:
    """**The distinction the whole ADR rests on.**

    `for_tenant(None)` means "a door failed to resolve a tenant" and answers
    nothing; `for_platform()` means "the deployment's own" and answers those
    rows. Collapsing the two would have made every unresolved read a window onto
    the platform's trail — fail-open, wearing a feature's name.
    """
    AuditEntry.objects.all().delete()

    purge_the_deployment(tenant=None, actor=system_actor())

    assert AuditEntry.objects.for_platform().count() == 1
    assert AuditEntry.objects.for_tenant(None).count() == 0


def test_the_admin_changelist_shows_no_platform_row_under_any_hat(db: None) -> None:
    """`AuditEntryAdmin` inherits the scoped `get_queryset`, so it is blind too.

    Driven through the registered admin rather than through a URL because the
    claim is about the queryset the changelist is built from — and the same
    argument as `test_admin.py`'s: no acting tenant resolves to None, and a
    scoped read of None is empty. A staff hat that *does* resolve a tenant is
    covered by the test above, which is the same `for_tenant` call.
    """
    AuditEntry.objects.all().delete()
    purge_the_deployment(tenant=None, actor=system_actor())
    assert AuditEntry.objects.for_platform().count() == 1

    request = RequestFactory().get("/admin/")
    request.user = None  # type: ignore[assignment]
    site_admin = admin.site._registry[AuditEntry]

    assert site_admin.get_queryset(request).count() == 0


# --- Rule 20, unchanged over the widened population ---------------------------


def test_a_platform_row_cannot_be_changed(db: None) -> None:
    AuditEntry.objects.all().delete()
    purge_the_deployment(tenant=None, actor=system_actor())
    entry = AuditEntry.objects.for_platform().get()

    entry.action = "something.else"
    with pytest.raises(AuditImmutable):
        entry.save()

    entry.refresh_from_db()
    assert entry.action == "core.purge_the_deployment"


def test_a_platform_row_cannot_be_deleted(db: None) -> None:
    AuditEntry.objects.all().delete()
    purge_the_deployment(tenant=None, actor=system_actor())
    entry = AuditEntry.objects.for_platform().get()

    with pytest.raises(AuditImmutable):
        entry.delete()

    assert AuditEntry.objects.filter(pk=entry.pk).exists()


def test_append_only_is_declared_on_the_model_not_on_the_tenant() -> None:
    """Why the two tests above are not a coincidence of this particular row.

    Rule 20 reads `append_only` off the class (ADR core-6), and `save()`/
    `delete()` in `apps/core/audit.py` never look at `tenant`. Widening which
    rows may exist could not have narrowed what may be done to one, and this is
    where that reasoning is written down rather than inferred.
    """
    from apps.core.models import append_only_models, is_append_only

    assert is_append_only(AuditEntry)
    assert AuditEntry in append_only_models()
    assert "tenant" not in inspect.getsource(AuditEntry.save)
    assert "tenant" not in inspect.getsource(AuditEntry.delete)


# --- for_platform is the mirror of for_tenant, spelled differently ------------


def test_for_platform_mirrors_the_run_ledgers_shape() -> None:
    """The same word, the same arity, on both models — ADR core-8's "shape for shape".

    A second platform population that spelled its read path differently would be
    two conventions, and the next model would have to pick one.
    """
    from apps.workflows.models import WorkflowRun

    audit = inspect.signature(AuditEntry.objects.for_platform)
    runs = inspect.signature(WorkflowRun.objects.for_platform)
    assert list(audit.parameters) == list(runs.parameters) == []
