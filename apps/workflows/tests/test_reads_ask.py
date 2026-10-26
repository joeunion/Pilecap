"""The run ledger's read is a permission over `workflow_run` (PR4.i, ADR core-27).

**What moved, in one line.** `list_runs` and `get_run` have authorized since the
ledger's first rung — this app was the one place in the tree where a read asked
anything at all — but the word they asked with was `workflowrun.read`: a key with
no kind, because the model derives `workflow_run` and the key was typed before
the vocabulary had a shape. Nothing a tenant wrote about the rows could reach
it: `workflowrun` named no kind, so `admin`'s `("*",)` and `member`'s `("*.read",)`
matched a word with no row behind it, a `RolePermission` exclude on the derived
key was inert, and a `Grant` withhold of `workflow_run.read` was a row the check
never read. That is the red the sweep's report pastes: the withhold was written
and the ledger answered anyway.

Now the key IS the kind's, so all three layers compose — and `workflowrun.read`
still answers as an alias for one release.

**The grammar, and the order** (§C8, reach before capability): another tenant's
run is `not_found` and always was — the scoped fetch answers before a capability
is consulted, so a caller cannot map another tenant by reading which ids refuse
differently. A run inside the tenant, without the key, is `forbidden`. A list
without the key is `forbidden`, because a list has no row to hide. The ORDER is
asserted by the two exception types rather than described: `get_run` now fetches
FIRST and asks second, which is the change PR4.i makes to the grammar and not to
the answer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from django.core.management import call_command
from django.test import Client
from mcp.server.mcpserver.exceptions import ToolError

from apps.accounts.models import User
from apps.core.actor import actor_for, system_actor
from apps.core.authz import allows, refusal_sentence
from apps.core.exceptions import Forbidden, NotFound
from apps.core.models import Grant, Membership, Organization, Tenant
from apps.core.services import root_organization
from apps.core.tests.mcp_context import context_for
from apps.core.tests.mcp_context import tool as mcp_tool
from apps.workflows.mcp import register
from apps.workflows.models import WorkflowRun
from apps.workflows.selectors import get_run, list_runs
from apps.workflows.services import _starter_actor, record_run, workflow_id

pytestmark = pytest.mark.django_db

RUNS_URL = "/api/v1/runs/"

#: The key the ledger is read under: the derived read of the row it hands back.
#: A literal, deliberately — a test that imported `READ_ACTION` could not tell a
#: rename from a selector that quietly stopped asking.
READ_KEY = "workflow_run.read"


def _run(*, tenant: Tenant, user: User | None, key: str) -> WorkflowRun:
    return record_run(
        tenant=tenant,
        workflow_id=workflow_id(tenant=tenant, app="example", noun="widget", key=key),
        workflow_type="WidgetOnboardingWorkflow",
        input_digest="d" * 64,
        actor=_starter_actor(tenant=tenant, user=user),
    )


def withhold(membership: Membership, permission: str) -> Grant:
    """A `withhold` row — the narrowing a tenant's administrator writes."""
    return Grant.objects.create(
        tenant=membership.tenant,
        membership=membership,
        permission=permission,
        effect=Grant.Effect.WITHHOLD,
    )


@dataclass(frozen=True)
class Ledger:
    """One tenant with a run of the reader's own and one of a colleague's, plus
    a run in a second tenant — the three cells §C8 distinguishes."""

    tenant: Tenant
    root: Organization
    reader: User
    membership: Membership
    mine: WorkflowRun
    theirs: WorkflowRun
    elsewhere: WorkflowRun


@pytest.fixture
def ledger(
    tenant: Tenant, owner: User, member: User, other_tenant: Tenant, stranger: User
) -> Ledger:
    root = root_organization(tenant=tenant)
    membership = Membership.objects.get(user=member, tenant=tenant)
    return Ledger(
        tenant=tenant,
        root=root,
        reader=member,
        membership=membership,
        mine=_run(tenant=tenant, user=member, key="mine"),
        theirs=_run(tenant=tenant, user=owner, key="theirs"),
        elsewhere=_run(tenant=other_tenant, user=stranger, key="elsewhere"),
    )


def tool(name: str) -> Callable[..., Any]:
    """The function this app's `register` binds to `name`."""
    return mcp_tool(name, register=register)


# --- PR4.i.1 · the selectors ask for the kind they hand back ------------------


def test_a_read_outside_the_tenant_is_not_found_and_inside_without_the_key_is_forbidden(
    ledger: Ledger,
) -> None:
    """Three cells, and the order between the first two is the criterion.

    **The red this closes:** before the sweep the withhold below was written and
    every one of these calls answered — `workflowrun.read` named no kind, so the
    grant row was resolved against a word `effective_permissions` had nothing to
    say about and the selector's `require` passed on the predicate alone.

    Then the withhold is lifted and all three answer, which is what stops this
    from passing with the selectors refusing everybody.
    """
    withhold(ledger.membership, READ_KEY)

    def acting() -> Any:
        """A FRESH actor each time — the memo's lifetime is the instance."""
        return actor_for(user=ledger.reader, tenant=ledger.tenant, org=ledger.root)

    with pytest.raises(NotFound):
        get_run(tenant=ledger.tenant, actor=acting(), run_id=ledger.elsewhere.pk)

    with pytest.raises(Forbidden) as refused:
        get_run(tenant=ledger.tenant, actor=acting(), run_id=ledger.theirs.pk)
    assert str(refused.value.args[0]) == refusal_sentence(READ_KEY)

    with pytest.raises(Forbidden) as refused_list:
        list_runs(tenant=ledger.tenant, actor=acting(), mine=False)
    assert str(refused_list.value.args[0]) == refusal_sentence(READ_KEY)

    Grant.objects.filter(membership=ledger.membership, permission=READ_KEY).delete()
    assert get_run(tenant=ledger.tenant, actor=acting(), run_id=ledger.theirs.pk) is not None
    assert list_runs(tenant=ledger.tenant, actor=acting(), mine=False).exists()
    with pytest.raises(NotFound):
        get_run(tenant=ledger.tenant, actor=acting(), run_id=ledger.elsewhere.pk)


def test_the_scoped_fetch_answers_before_the_capability(ledger: Ledger) -> None:
    """PR4.i's one change to `get_run`: fetch first, ask second, with `obj=run`.

    Driven as a DIFFERENCE rather than asserted about the source: the same
    person, the same withhold, two ids — one in the tenant and one outside it —
    and the two refusals are different classes. A `get_` that asked before its
    scoped fetch would answer `Forbidden` for both, which is the existence
    oracle §C8 exists to close, and it would still look like a working read gate
    from every door.
    """
    withhold(ledger.membership, READ_KEY)
    acting = actor_for(user=ledger.reader, tenant=ledger.tenant, org=ledger.root)

    with pytest.raises(NotFound):
        get_run(tenant=ledger.tenant, actor=acting, run_id=ledger.elsewhere.pk)
    with pytest.raises(Forbidden):
        get_run(tenant=ledger.tenant, actor=acting, run_id=ledger.mine.pk)


def test_the_system_actor_reads_the_ledger(ledger: Ledger) -> None:
    """`system` passes at step 1, so the reconciler and the purge sweep are untouched.

    Asserted with a withhold on the reader in place, so the pass is the actor
    kind and not an accident of there being nothing to refuse.
    """
    withhold(ledger.membership, READ_KEY)
    system = system_actor(tenant=ledger.tenant, org=ledger.root)

    assert list_runs(tenant=ledger.tenant, actor=system, mine=False).count() == 2
    assert get_run(tenant=ledger.tenant, actor=system, run_id=ledger.theirs.pk) is not None


def test_the_plain_member_still_reads_everything(api: Client, ledger: Ledger) -> None:
    """**A product that customised nothing observes no change** (principle 13).

    `member` is declared `("*.read",)`, so the derived `workflow_run.read` is a
    key it holds and the door answers exactly what it answered before the key
    moved — the whole tenant's ledger on `?mine=false`, which is the question
    ADR workflows-6 says a ledger exists for.
    """
    api.force_login(ledger.reader)

    listed = api.get(f"{RUNS_URL}?mine=false")
    detail = api.get(f"{RUNS_URL}{ledger.theirs.pk}/")

    assert listed.status_code == 200, listed.content
    assert {row["id"] for row in listed.json()["items"]} == {
        str(ledger.mine.pk),
        str(ledger.theirs.pk),
    }
    assert detail.status_code == 200, detail.content


def test_the_alias_answers_for_a_caller_and_the_command_is_what_moves_a_row(
    ledger: Ledger,
) -> None:
    """**Which half of a rename the alias buys, driven — and which half it does not.**

    *Disproved while the sweep was being built*, and worth a case of its own because the
    criteria's phrase "the old word keeps answering" reads as though it covered
    both: `resolve_renamed` maps a key at `require` TIME, so a CALLER still
    saying `workflowrun.read` is answered as `workflow_run.read`. A tenant's
    stored `Grant` row saying the old word is NOT — `effective_permissions`
    matches rows by their literal string — so a withhold written before the sweep
    goes quietly inert on the day the sweep lands.

    That is the platform's own design and it is written down
    (`core.services.rename_permission_rows`: *"What it does not do is move the
    tenant's own rows … This is the one writer that moves them"*). It is driven
    here because it is the cost of the rename that a reader would otherwise
    assume away: a deployment carrying grants on these four keys must run
    `manage.py rename_permission` after the sweep, and until it does, a person
    somebody had narrowed reads the ledger again.

    Three states, in order: the caller's old word answers · the stale ROW does
    not bite · the command moves it and it does.
    """
    acting = actor_for(user=ledger.reader, tenant=ledger.tenant, org=ledger.root)

    # (1) the caller's half: the old word and the new one are one question.
    assert allows(acting, "workflowrun.read") is allows(acting, READ_KEY) is True

    # (2) the row's half: a withhold written before the sweep is INERT.
    withhold(ledger.membership, "workflowrun.read")
    assert list_runs(
        tenant=ledger.tenant,
        actor=actor_for(user=ledger.reader, tenant=ledger.tenant, org=ledger.root),
        mine=False,
    ).exists()

    # (3) ...until the operator runs the command that exists for exactly this.
    call_command("rename_permission", "workflowrun.read", READ_KEY)

    with pytest.raises(Forbidden):
        list_runs(
            tenant=ledger.tenant,
            actor=actor_for(user=ledger.reader, tenant=ledger.tenant, org=ledger.root),
            mine=False,
        )


# --- PR4.i.2 · both doors, the same words -------------------------------------


def test_a_withheld_run_read_is_forbidden_on_both_doors(api: Client, ledger: Ledger) -> None:
    """One refusal, composed once, rendered by two doors (E9, rule 46).

    Both sides are compared against `refusal_sentence(READ_KEY)` rather than
    against each other, so a door that grew a friendlier wording of its own
    fails here instead of passing by symmetry.

    Driven with a session at the HTTP door and a bearer at the machine door,
    because the credential kinds are population members: the token's ceiling is
    unset, so what refuses it is the READ key and nothing else.
    """
    withhold(ledger.membership, READ_KEY)
    sentence = refusal_sentence(READ_KEY)
    api.force_login(ledger.reader)

    listed = api.get(f"{RUNS_URL}?mine=false")
    assert listed.status_code == 403, listed.content
    assert listed.json()["code"] == "forbidden"
    assert listed.json()["detail"] == sentence

    detail = api.get(f"{RUNS_URL}{ledger.theirs.pk}/")
    assert detail.status_code == 403, detail.content
    assert detail.json()["detail"] == sentence

    ctx = context_for(ledger.reader, ledger.tenant, ledger.root)
    with pytest.raises(ToolError) as refused_list:
        tool("list_runs")(ctx=ctx, mine=False)
    with pytest.raises(ToolError) as refused_get:
        tool("get_run")(ctx=ctx, run_id=ledger.theirs.pk)

    for said in (str(refused_list.value), str(refused_get.value)):
        assert "forbidden" in said, said
        assert sentence in said, said

    # ...and a run in another tenant is still 404 on both doors: the §C8 half
    # the read key does not touch.
    assert api.get(f"{RUNS_URL}{ledger.elsewhere.pk}/").status_code == 404
    with pytest.raises(ToolError) as outside:
        tool("get_run")(ctx=ctx, run_id=ledger.elsewhere.pk)
    assert "not_found" in str(outside.value), str(outside.value)
