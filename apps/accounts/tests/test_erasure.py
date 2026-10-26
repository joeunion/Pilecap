"""What erasing a person promises — and what it refuses.

The row survives, the person does not, the audit trail stays readable, and a
tenant is never left without an owner.
"""

from __future__ import annotations

import pytest
from django.test import Client
from mcp.server.mcpserver.exceptions import ToolError

from apps.accounts.models import ApiToken, User
from apps.accounts.selectors import list_tenants_this_user_alone_owns
from apps.accounts.services import (
    ERASED_EMAIL_DOMAIN,
    authenticate_token,
    erase_user,
    issue_token,
)
from apps.accounts.tests.test_user_doors import tool
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.audit import AuditEntry
from apps.core.exceptions import Conflict, Forbidden, NotFound, refusal_message
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import add_membership, root_organization, set_role
from apps.core.tests.mcp_context import context_for

pytestmark = pytest.mark.django_db

# `owner_actor` is asked for **first** wherever it appears below, and that is not
# style. `apps/conftest.py`'s `owner` fixture calls `add_membership` without a
# role, and `add_membership` makes the *first* membership of a tenant its owner;
# so if `member` is built first, `owner` comes out a plain member and every
# authorization assertion here inverts. Fixture order deciding a role is a trap
# worth naming rather than tripping over twice.


@pytest.fixture
def second_owner(tenant: Tenant, member: User) -> User:
    """Somebody else who owns the tenant, so `owner` is no longer the only one."""
    set_role(
        tenant=tenant,
        membership=Membership.objects.get(user_id=member.pk, tenant=tenant),
        role=Membership.Role.OWNER,
        # R1-F4.2: `set_role` asks `may_be_named` first, and a hatless system
        # actor names no node. The hat is the root, which is where this
        # membership sits.
        actor=system_actor(tenant=tenant, org=root_organization(tenant=tenant)),
    )
    return member


# --- What is erased ----------------------------------------------------------


def test_the_person_is_gone_and_the_row_is_not(
    tenant: Tenant, owner: User, member: User, owner_actor: Actor
) -> None:
    membership_before = Membership.objects.get(user_id=member.pk, tenant=tenant)

    erased = erase_user(user=member, actor=owner_actor, tenant=tenant)

    erased.refresh_from_db()
    assert erased.pk == member.pk
    assert erased.email.startswith("erased+")
    assert erased.email.endswith(f"@{ERASED_EMAIL_DOMAIN}")
    assert "member@example.com" not in erased.email
    assert not erased.has_usable_password()
    assert erased.is_active is False
    assert erased.is_staff is False
    assert erased.is_superuser is False
    # The membership stays: it is what makes the audit trail readable, and the
    # account cannot be used regardless.
    assert Membership.objects.filter(pk=membership_before.pk).exists()


def test_every_token_stops_working(owner_actor: Actor, tenant: Tenant, member: User) -> None:
    """A machine that was acting as this person stops acting as them."""
    _token, plaintext = issue_token(
        user=member, tenant=tenant, name="integration", actor=actor_for(user=member, tenant=tenant)
    )
    assert authenticate_token(plaintext=plaintext) is not None

    erase_user(user=member, actor=owner_actor, tenant=tenant)

    assert authenticate_token(plaintext=plaintext) is None
    assert ApiToken.objects.filter(user_id=member.pk, revoked_at__isnull=True).count() == 0


def test_two_erasures_do_not_collide_on_the_unique_email(
    owner_actor: Actor, tenant: Tenant, member: User, admin_member: User
) -> None:
    """`email` is unique; a fixed placeholder would make the second erasure fail."""
    first = erase_user(user=member, actor=owner_actor, tenant=tenant)
    second = erase_user(user=admin_member, actor=owner_actor, tenant=tenant)

    assert first.email != second.email
    assert User.objects.filter(email__endswith=f"@{ERASED_EMAIL_DOMAIN}").count() == 2


def test_the_erasure_is_audited(owner_actor: Actor, tenant: Tenant, member: User) -> None:
    """The most sensitive write in the product leaves the loudest row.

    **This test used to assert the MECHANISM and now asserts the property**
    (AUDIT-2, ADR core-22). Its old line was `input["user"] == "[redacted]"`,
    with a comment saying the allow-list is what keeps the erased address out
    of the row. The allow-list is no longer what does that — since core-22's
    criterion 4, `redact` renders a `models.Model` argument as
    `<app_label>.<Model>:<pk>` whatever the parameter is called, because a
    refused call has no return value for `object_id` to be taken from and a
    trail that cannot name what a refusal was about is half a trail.

    **What is protected is unchanged, and it is the address.** `_plain` carries
    a label and a primary key and no column of the row, so the erased person's
    email was never in `input` and still is not. The pk was already in this
    very row twice over — `object_id` above, and `actor_user_id` when the
    person erases themselves — so nothing here is newly disclosed by naming it
    a third time.

    The assertions below say both halves out loud, so a future change that put
    a real value back into `input` fails on the second one rather than on a
    string comparison whose meaning had drifted.
    """
    address_before = member.email
    erased = erase_user(user=member, actor=owner_actor, tenant=tenant)

    entry = AuditEntry.objects.for_tenant(tenant).get(action="accounts.erase_user")
    assert entry.outcome == "ok"
    assert entry.object_id == erased.pk
    assert entry.actor_user_id == owner_actor.user.pk if owner_actor.user else None
    assert entry.input["user"] == f"{User._meta.label}:{erased.pk}", "the row NAMES the person"
    assert address_before not in str(entry.input), "and never says who they were"
    assert erased.email not in str(entry.input), "nor what they were renamed to"


# --- What it refuses ---------------------------------------------------------


def test_erasing_the_only_owner_is_refused(tenant: Tenant, owner: User) -> None:
    """Including — especially — when it is the owner erasing themselves.

    A tenant with no owner is a tenant nobody can invite into, change a role
    in, or close, and nobody finds out until they try.
    """
    acting = actor_for(user=owner, tenant=tenant)

    with pytest.raises(Conflict) as refusal:
        erase_user(user=owner, actor=acting, tenant=tenant)

    assert tenant.slug in str(refusal.value)
    owner.refresh_from_db()
    assert owner.is_active is True
    assert owner.email == "owner@example.com"


def test_erasing_an_owner_is_allowed_once_somebody_else_owns_it(
    tenant: Tenant, owner: User, second_owner: User
) -> None:
    """The refusal is about the tenant, not about the role."""
    assert list_tenants_this_user_alone_owns(user=owner) == []

    acting = actor_for(user=second_owner, tenant=tenant)
    erased = erase_user(user=owner, actor=acting, tenant=tenant)

    assert erased.is_active is False


def test_a_plain_member_may_not_erase_anybody(
    tenant: Tenant, member_actor: Actor, admin_member: User
) -> None:
    with pytest.raises(Forbidden):
        erase_user(user=admin_member, actor=member_actor, tenant=tenant)

    admin_member.refresh_from_db()
    assert admin_member.is_active is True


def test_an_owner_cannot_erase_somebody_in_another_tenant(
    tenant: Tenant, owner_actor: Actor, stranger: User, other_tenant: Tenant
) -> None:
    """`NotFound`, not `Forbidden`: a 403 here would confirm the account exists."""
    with pytest.raises(NotFound):
        erase_user(user=stranger, actor=owner_actor, tenant=tenant)

    stranger.refresh_from_db()
    assert stranger.is_active is True


def test_the_deployment_itself_can_erase_a_user_with_no_tenant(nomad: User) -> None:
    """A person who belongs to nowhere still gets erased, by a system actor —
    **and it is audited now** (ADR core-8).

    This test used to end `assert not AuditEntry.objects.filter(...).exists()`,
    and its docstring called that "the residual named in `erase_user`'s
    docstring": `AuditEntry.tenant` was not nullable, so `@service` skipped the
    row and the deployment's own erasures were logged and never audited. That is
    the pre-fix absence that was closed, and re-pointing it here is where the
    closure is visible rather than assumed.

    The row lands in the **platform population**: `tenant` NULL, read through
    `for_platform()`, and reachable through no tenant's ledger — the fence is
    pinned next door in `apps/core/tests/test_platform_population.py`.
    """
    erased = erase_user(user=nomad, actor=system_actor(), tenant=None)

    assert erased.is_active is False
    assert erased.email.endswith(f"@{ERASED_EMAIL_DOMAIN}")
    entry = AuditEntry.objects.for_platform().get(action="accounts.erase_user")
    assert entry.tenant_id is None
    assert not AuditEntry.objects.for_tenant(None).filter(action="accounts.erase_user").exists()


def test_a_user_in_two_tenants_is_erased_once_and_blocks_on_either(
    tenant: Tenant, other_tenant: Tenant, member: User
) -> None:
    """The orphan check looks at every tenant, not just the acting one."""
    add_membership(
        user=member,
        tenant=other_tenant,
        role=Membership.Role.OWNER,
        actor=system_actor(tenant=other_tenant),
    )

    assert [one.slug for one in list_tenants_this_user_alone_owns(user=member)] == [
        other_tenant.slug
    ]
    with pytest.raises(Conflict):
        erase_user(user=member, actor=system_actor(), tenant=tenant)


# --- The refusal offers a way out that actually leads out ---------------
#
# The detail said "make somebody else an owner first". The `remedies` — the
# registered defaults for `conflict` — said "re-read the row and retry against
# what is true now" and "send an Idempotency-Key to get the first answer back".
# Both are excellent advice about a race, and both are false here: nothing has
# changed underneath the caller, and retrying refuses identically forever. A
# remedy that cannot change the answer is worse than none, because it sends the
# caller round a loop — and an assistant reads these out loud.


def test_the_last_owner_refusal_offers_the_way_out_it_names(
    tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """Contextual remedies at the raise site, agreeing with the sentence beside them."""
    from apps.core.exceptions import REFUSALS, wire_refusal

    with pytest.raises(Conflict) as refused:
        erase_user(user=owner, actor=owner_actor, tenant=tenant)

    body = wire_refusal(refused.value)
    assert body["code"] == "conflict"
    assert "Make somebody else an owner first" in body["detail"]

    offered = [remedy["label"] for remedy in body["remedies"]]
    assert any("owner" in label for label in offered), offered
    # The contextual list REPLACES the registry's rather than joining it: the
    # generic advice was not merely incomplete here, it was wrong.
    registered = [remedy.label for remedy in REFUSALS["conflict"].remedies]
    assert not set(offered) & set(registered), (offered, registered)
    assert not any("Idempotency-Key" in remedy["destination"] for remedy in body["remedies"])


def test_both_doors_say_the_same_thing_about_the_last_owner(
    api: Client, tenant: Tenant, owner: User, root_org: Organization
) -> None:
    """E9, door-relative: the tool's message IS the REST body, rendered.

    String-compared through `refusal_message` over the REST fields rather than
    against a golden body pinned here — a frozen string would go stale the day
    somebody improves the sentence, and would be asserting about the test rather
    than about the two doors agreeing.
    """
    api.force_login(owner)
    rest = api.post(f"/api/v1/users/{owner.pk}/erase/")
    assert rest.status_code == 409, rest.content

    with pytest.raises(ToolError) as machine:
        tool("erase_user")(context_for(owner, tenant, root_org), user_id=owner.pk)

    assert str(machine.value) == refusal_message(rest.json())
    assert User.objects.get(pk=owner.pk).is_active is True
