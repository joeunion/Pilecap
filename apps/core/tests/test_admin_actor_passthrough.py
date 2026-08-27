"""The admin door builds an actor — and every service it calls must be handed it.

**AUDIT-3's rider, and the reason it is a rider rather than a rule.** ADR
core-22 asserts that the admin seam is present: `ServiceModelAdmin.acting`
resolves a request-shaped `Actor` and `ContextMiddleware` stamps `door="admin"`,
so an admin write is attributed with no work by the subclass. That assertion is
what the L3 check found true, and it is why the conditional absence (vi) was
deleted rather than kept.

A single counter-example makes an asserted seam false. `TenantAdmin.call_service`
overrode the base — which passes `actor=actor, tenant=tenant` — with a two-keyword
call that dropped both, so the one service the admin can reach through that class
was called by a door that knew who was asking and did not say. **And rule 49
declaredly cannot see it**: that rule reads SIGNATURES, and every signature here
was already correct; what was wrong was a call site. `does_not_cover` names this
class as its worked example, and this module is the other half of that division
of labor.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from apps.core.actor import Actor, actor_for, system_actor
from apps.core.admin import ServiceModelAdmin, TenantAdmin
from apps.core.audit import AuditEntry
from apps.core.exceptions import Forbidden
from apps.core.models import Membership, Tenant
from apps.core.services import create_tenant

pytestmark = pytest.mark.django_db


def test_create_tenant_takes_a_required_actor() -> None:
    """The service can be told who is asking, and cannot be left to guess.

    `create_tenant` itself stays UNAUDITED — ADO-5, unchanged, and
    `test_bootstrap.py` holds that line. The actor is not here to make a row
    for this call; it is here because the call writes somebody's first
    membership, and that row was landing as `system` for an act a person
    performed.
    """
    parameters = inspect.signature(create_tenant).parameters

    assert "actor" in parameters
    assert parameters["actor"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["actor"].default is inspect.Parameter.empty


def test_a_human_caller_is_refused_rather_than_laundered_into_system(
    owner: Any, tenant: Tenant
) -> None:
    """The observable half of the drop — and it is a REFUSAL, not an attribution.

    **This is where the rider's stated outcome met the tree, and the tree won.**
    The brief asked for an admin-created tenant's row to carry `actor_user ==
    the staff member`. It cannot, and the reason is structural rather than
    incidental: `create_tenant(owner=...)` writes the tenant's first
    `Membership` through `add_membership`, and the escalation wall measures the
    granter's effective role **at the node being granted on** — which for a
    tenant that did not exist one statement ago is `None`, for everybody, for
    ever. `_refuse_escalation`'s own docstring already named this case: "the
    tenant's own creation" is one of its system altitudes.

    So the first membership is the system altitude by construction. What the
    drop actually cost was not attribution — it was **laundering**:
    `create_tenant` hard-coded `system_actor(tenant=tenant)`, so ANY caller,
    however identified, had its act rewritten as the product's own before the
    wall ever saw it. Forwarding the caller's actor means a human caller now
    gets the wall's real answer instead of a fabricated altitude. That is the
    hole this rider closed, and it is the same hole ADR core-22's L1 ruling
    took away everywhere else.
    """
    acting = actor_for(user=owner, tenant=tenant)

    with pytest.raises(Forbidden, match="you may not grant one there"):
        create_tenant(name="Rider Co", slug="rider-co", owner=owner, actor=acting)

    assert not Tenant.objects.filter(slug="rider-co").exists(), "and nothing was written"


def test_a_system_caller_still_files_the_membership_as_system(owner: Any) -> None:
    """The other direction, so the fix is a pass-through and not a rename.

    `manage.py seed` and `create_first_tenant` are the product setting itself
    up. They pass `system_actor(...)` explicitly and the row says `system` —
    the named audited altitude, which is what absence (ii) means and what the
    re-keyed wall reads.
    """
    made = create_tenant(name="Shell Co", slug="shell-co", owner=owner, actor=system_actor())

    row = AuditEntry.objects.for_tenant(made).filter(action="core.add_membership").get()
    assert row.actor_kind == AuditEntry.Kind.SYSTEM
    assert row.actor_user_id is None
    assert Membership.objects.filter(tenant=made, user=owner).exists()


def test_tenant_admin_forwards_the_actor_the_door_resolved() -> None:
    """The call site itself, read rather than driven — and here is why.

    Driving it would prove less. `TenantAdmin`'s change form carries no `owner`
    field, so a tenant created through the admin today writes no membership and
    therefore no audit row at all — there is nothing for a wire test to look at,
    which is a second finding and not this test's subject. What IS checkable,
    and what actually broke, is whether the override forwards what `acting()`
    resolved: the base `call_service` passes `actor=` and `tenant=`, and this
    subclass dropped both.

    Read off the source rather than the signature, because the defect was a
    keyword that was never passed on — invisible to any signature check,
    including rule 49's, which is why `does_not_cover` names this class.
    """
    source = inspect.getsource(TenantAdmin.call_service)

    assert "actor=actor" in source, (
        "TenantAdmin.call_service drops the actor the admin door resolved; "
        "the base class passes it and this override must too"
    )
    assert "actor: Actor" in inspect.getsource(ServiceModelAdmin.call_service)


def test_the_admin_seam_still_resolves_a_request_shaped_actor(rf: Any, owner: Any) -> None:
    """The assertion ADR core-22 makes about the door, pinned where it is made.

    If `acting()` ever stopped returning a real actor, every subclass above
    would forward `None` correctly and the trail would go quiet with every test
    still green. This is the tripwire under the assertion the ADR rests on.
    """
    request = rf.post("/admin/core/tenant/add/")
    request.user = owner

    actor, _tenant = TenantAdmin(Tenant, admin_site=None).acting(request)  # type: ignore[arg-type]

    assert isinstance(actor, Actor)
    assert actor.user_id == owner.pk
