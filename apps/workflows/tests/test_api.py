"""The run ledger's REST door: what it shows, whose it is, and what replay refuses.

Every row here is made the way a person makes one — `POST /api/v1/widgets/`
starts `WidgetOnboardingWorkflow` and `record_run` writes the ledger row inside
that request's transaction — so what is under test is the ledger a product
actually accumulates, not a row a test invented. `record_run` is called directly
only where a test needs a row in a state a happy path does not produce (a failed
one, an ancient one, one with no recorded starter).

Nothing here dials Temporal. The visibility row is written in the caller's
transaction; the client call is an `on_commit` hook, and a non-transactional
test never commits, so the hook never runs. That is not a gap being papered
over: the reset RPC itself is proven separately, against the live dev server,
and what these tests own is the door and the row.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import User
from apps.core.actor import Actor, actor_for
from apps.core.audit import AuditEntry
from apps.core.exceptions import Conflict, Forbidden, NotFound
from apps.core.models import Organization, Tenant
from apps.workflows.models import WorkflowRun
from apps.workflows.services import HISTORY_RETENTION, record_run, workflow_id

pytestmark = pytest.mark.django_db

JSON = "application/json"
RUNS_URL = "/api/v1/runs/"
WIDGETS_URL = "/api/v1/widgets/"

# Measured, not guessed, at ten runs and then again at thirty. The ten, in the
# order they run: the session row + the user row (session authentication) + the
# membership read `TenantMiddleware` resolves the tenant from + the membership
# read `resolve_org` resolves the acting ORG from + 1 SAVEPOINT
# (ATOMIC_REQUESTS) + THE THREE `authz.require` resolves `workflow_run.read`
# from inside `list_runs` + the page + 1 RELEASE SAVEPOINT.
# `started_by` is `select_related`, which is the point of the pin — drop it and
# this number grows with the page.
# ADR core-18 took the COUNT off this pin: the default list issues none any
# more — `has_more` comes from fetching one row more than asked for.
# `?include_count=true` puts it back, and costs exactly one more (eleven).
#
# **8 -> 10, and the arithmetic is +3 and -1** (PR4.i.3). The +3 is the read key
# resolved at the acting hat — memberships, grants, role deltas — which is what
# ADR core-27 costs every read door once per actor; the -1 is the single
# membership read the retired `may_read_the_ledger` predicate used to make, which
# the three statements subsume. The three are memoized on the actor, so a second
# question in the same request is free; a request builds one actor, which is why
# ten is what a request pays rather than what a loop pays.
LIST_QUERY_BUDGET = 10


def _make_widget(api: Client, owner: User, name: str) -> str:
    """One widget over the human door, which starts one durable run."""
    response = api.post(WIDGETS_URL, data={"name": name}, content_type=JSON)
    assert response.status_code == 201, response.content
    return str(response.json()["id"])


def _failed_run(
    *, tenant: Tenant, user: User | None, key: str, started_at: Any = None
) -> WorkflowRun:
    """A run row in the one state a happy path cannot leave behind."""
    run = record_run(
        tenant=tenant,
        workflow_id=workflow_id(tenant=tenant, app="example", noun="widget", key=key),
        workflow_type="WidgetOnboardingWorkflow",
        input_digest="d" * 64,
        user=user,
    )
    run.status = WorkflowRun.Status.FAILED
    run.error = "the activity said no"
    run.run_id = f"execution-{key}"
    run.finished_at = timezone.now()
    if started_at is not None:
        run.started_at = started_at
    run.save()
    return run


# --- the read door -----------------------------------------------------------


def test_a_run_started_over_rest_is_visible_in_the_ledger(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """B-WF-1: the persona can see their own work. Absent, the ledger is admin-only.

    The widget POST is the whole set-up: a person did a thing, the thing waits
    for a person, and the ledger is how they find out what happened to it.
    """
    api.force_login(owner)
    widget_id = _make_widget(api, owner, "Onboarding one")

    response = api.get(RUNS_URL)
    assert response.status_code == 200, response.content
    body = response.json()
    assert len(body["items"]) == 1
    row = body["items"][0]
    assert row["type"] == "WidgetOnboardingWorkflow"
    assert row["workflow_id"].endswith(f":example:widget:{widget_id}")
    assert row["status"] == WorkflowRun.Status.RUNNING
    assert row["started_by_id"] == str(owner.pk)
    assert row["started_by_email"] == owner.email
    assert row["input_digest"] != ""


def test_another_tenants_runs_are_absent(
    api: Client, tenant: Tenant, other_tenant: Tenant, owner: User, stranger: User
) -> None:
    """The test that cannot pass vacuously: two tenants, one door, one answer."""
    _failed_run(tenant=tenant, user=owner, key="mine")
    theirs = _failed_run(tenant=other_tenant, user=stranger, key="theirs")

    api.force_login(owner)
    response = api.get(f"{RUNS_URL}?mine=false")
    assert response.status_code == 200
    ids = [row["id"] for row in response.json()["items"]]
    assert str(theirs.pk) not in ids

    detail = api.get(f"{RUNS_URL}{theirs.pk}/")
    assert detail.status_code == 404
    assert detail.json()["code"] == "not_found"


def test_the_list_is_mine_by_default_and_widens_on_request(
    api: Client, tenant: Tenant, owner: User, member: User
) -> None:
    """`mine` is the door's default because it is the question people arrive with.

    Absent: a person opening the ledger to find out what happened to *their*
    sync meets the whole company's work and gives up.
    """
    ours = _failed_run(tenant=tenant, user=owner, key="ours")
    theirs = _failed_run(tenant=tenant, user=member, key="colleague")

    api.force_login(owner)
    mine = api.get(RUNS_URL).json()
    assert [row["id"] for row in mine["items"]] == [str(ours.pk)]

    wide = api.get(f"{RUNS_URL}?mine=false").json()
    assert {row["id"] for row in wide["items"]} == {str(ours.pk), str(theirs.pk)}

    # A colleague's run is readable one at a time too — what being yours gates
    # is replay, not sight.
    assert api.get(f"{RUNS_URL}{theirs.pk}/").status_code == 200


def test_a_run_with_no_recorded_starter_belongs_to_nobody(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """B-WF-3: rows written before `started_by` existed are unknown, not mine.

    The `input_digest` convergence pattern, asserted rather than assumed: an old
    row never conflicts with anything, is readable through the tenant door, and
    is nobody's own run — which is why the next test cannot replay it.
    """
    orphan = _failed_run(tenant=tenant, user=None, key="from-before")
    assert orphan.started_by_id is None

    api.force_login(owner)
    assert [row["id"] for row in api.get(RUNS_URL).json()["items"]] == []
    wide = api.get(f"{RUNS_URL}?mine=false").json()
    assert [row["id"] for row in wide["items"]] == [str(orphan.pk)]
    assert wide["items"][0]["started_by_email"] == ""


def test_the_list_holds_its_query_budget(
    api: Client, tenant: Tenant, owner: User, django_assert_num_queries: Any
) -> None:
    """Rule 5: the pin is what makes `started_by`'s N+1 fail the gate."""
    for index in range(10):
        _failed_run(tenant=tenant, user=owner, key=f"seed-{index}")

    api.force_login(owner)
    with django_assert_num_queries(LIST_QUERY_BUDGET):
        assert api.get(RUNS_URL).status_code == 200

    for index in range(20):
        _failed_run(tenant=tenant, user=owner, key=f"more-{index}")
    with django_assert_num_queries(LIST_QUERY_BUDGET):
        assert api.get(RUNS_URL).status_code == 200


def test_ordering_is_an_allow_list(api: Client, tenant: Tenant, owner: User) -> None:
    """`?ordering=started_by__password` is a read across a join, and it is refused."""
    _failed_run(tenant=tenant, user=owner, key="ordered")
    api.force_login(owner)
    refused = api.get(f"{RUNS_URL}?ordering=started_by__password")
    assert refused.status_code == 400
    assert refused.json()["code"] == "invalid"


# --- replay: the state table, enumerated (B-WF-2) -----------------------------


def test_replay_resets_a_failed_run_of_my_own(
    api: Client, tenant: Tenant, owner: User, recorded_workflow_starts: None
) -> None:
    """FAILED + own → the row is back to RUNNING and the reset is dispatched.

    The new Temporal execution id arrives from the RPC and is written by the
    on-commit hook, so the row's `run_id` is deliberately empty at the moment
    this door answers: the ledger says "asked for, not yet assigned" rather
    than carrying the id of the execution being replaced.
    """
    run = _failed_run(tenant=tenant, user=owner, key="failed-mine")
    AuditEntry.objects.all().delete()

    api.force_login(owner)
    response = api.post(f"{RUNS_URL}{run.pk}/replay/", content_type=JSON)
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["status"] == WorkflowRun.Status.RUNNING
    assert body["error"] == ""
    assert body["finished_at"] is None
    assert body["run_id"] == ""

    run.refresh_from_db()
    assert run.status == WorkflowRun.Status.RUNNING
    assert run.finished_at is None

    entry = AuditEntry.objects.for_tenant(tenant).get(action="workflows.start_replay")
    assert (entry.door, entry.outcome, entry.actor_user_id) == ("rest", "ok", owner.pk)


def test_replay_refuses_a_colleagues_run_as_not_found(
    api: Client, tenant: Tenant, owner: User, member: User
) -> None:
    """Same tenant, somebody else's run. `not_found`, and the row does not move.

    Absent: a `forbidden` here would confirm that a run exists under that id,
    which is the fact the ownership wall is keeping.
    """
    run = _failed_run(tenant=tenant, user=member, key="failed-theirs")

    api.force_login(owner)
    response = api.post(f"{RUNS_URL}{run.pk}/replay/", content_type=JSON)
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"

    run.refresh_from_db()
    assert run.status == WorkflowRun.Status.FAILED


def test_replay_refuses_another_tenants_run_as_not_found(
    api: Client, tenant: Tenant, other_tenant: Tenant, owner: User, stranger: User
) -> None:
    """The other half of the one answer: not-there and not-yours are the same."""
    theirs = _failed_run(tenant=other_tenant, user=stranger, key="failed-elsewhere")

    api.force_login(owner)
    response = api.post(f"{RUNS_URL}{theirs.pk}/replay/", content_type=JSON)
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"

    theirs.refresh_from_db()
    assert theirs.status == WorkflowRun.Status.FAILED


def test_replay_refuses_a_run_with_no_recorded_starter(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """A NULL starter is unknown, so the run is nobody's — including the asker's."""
    orphan = _failed_run(tenant=tenant, user=None, key="failed-orphan")

    api.force_login(owner)
    response = api.post(f"{RUNS_URL}{orphan.pk}/replay/", content_type=JSON)
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_replay_refuses_a_running_run(api: Client, tenant: Tenant, owner: User) -> None:
    """RUNNING → conflict. Replaying a live execution is asking for two of it."""
    api.force_login(owner)
    widget_id = _make_widget(api, owner, "Still going")
    run = WorkflowRun.objects.for_tenant(tenant).get(workflow_id__endswith=widget_id)
    assert run.status == WorkflowRun.Status.RUNNING

    response = api.post(f"{RUNS_URL}{run.pk}/replay/", content_type=JSON)
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"
    assert "still running" in response.json()["detail"]


def test_replay_refuses_a_completed_run(api: Client, tenant: Tenant, owner: User) -> None:
    """COMPLETED → conflict, in `record_run`'s own words. That quadrant, quoted."""
    run = _failed_run(tenant=tenant, user=owner, key="finished")
    run.status = WorkflowRun.Status.COMPLETED
    run.error = ""
    run.save(update_fields=["status", "error", "updated_at"])

    api.force_login(owner)
    response = api.post(f"{RUNS_URL}{run.pk}/replay/", content_type=JSON)
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"
    assert "a new job, not a repeat of that one" in response.json()["detail"]


def test_replay_refuses_a_run_past_the_history_retention(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """FAILED + history expired → conflict, and it says the record is gone.

    Decided from the row's own clock rather than from an RPC, so the caller is
    refused at the door instead of by a hook nobody is watching an hour later.
    """
    ancient = _failed_run(
        tenant=tenant,
        user=owner,
        key="ancient",
        started_at=timezone.now() - HISTORY_RETENTION - timedelta(days=1),
    )

    api.force_login(owner)
    response = api.post(f"{RUNS_URL}{ancient.pk}/replay/", content_type=JSON)
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"
    assert "no longer kept" in response.json()["detail"]
    # Plain language, per the 2026-08-23 ruling: a caller is not told about a
    # namespace, a retention policy or the execution engine's name.
    assert "Temporal" not in response.json()["detail"]

    ancient.refresh_from_db()
    assert ancient.status == WorkflowRun.Status.FAILED


def test_replay_refuses_an_id_that_is_not_a_run(api: Client, tenant: Tenant, owner: User) -> None:
    """A guessed id answers exactly as a colleague's does."""
    api.force_login(owner)
    response = api.post(f"{RUNS_URL}{uuid4()}/replay/", content_type=JSON)
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


# --- The same key twice --------------------------------------------------------------


def test_the_same_idempotency_key_replays_the_first_answer(
    api: Client, tenant: Tenant, owner: User, recorded_workflow_starts: None
) -> None:
    """Over the one write route this door has.

    The second POST is answered from the stored response — which is visible in
    `Idempotent-Replayed` — rather than by asking Temporal for a second reset of
    a run that is now RUNNING and would have been a conflict.
    """
    run = _failed_run(tenant=tenant, user=owner, key="idempotent")
    api.force_login(owner)
    headers = {"idempotency-key": "replay-once"}

    first = api.post(f"{RUNS_URL}{run.pk}/replay/", content_type=JSON, headers=headers)
    assert first.status_code == 200, first.content

    second = api.post(f"{RUNS_URL}{run.pk}/replay/", content_type=JSON, headers=headers)
    assert second.status_code == 200
    assert second.json() == first.json()
    assert second.headers.get("Idempotent-Replayed") == "true"


# --- Cancel, wall by wall --------------------------------------------------------
#
# The four walls are `start_replay`'s, in `start_replay`'s order, so the tests
# below are its state table with the states swapped round: replay is legal only
# from FAILED and cancel is legal only from RUNNING. What is NOT shared is the
# fifth thing: an accepted cancel writes nothing, so every one of these asserts
# on the row afterwards as well as on the status code.


def _running_run(*, tenant: Tenant, user: User | None, key: str) -> WorkflowRun:
    """A row in the one state a cancel is legal from. `record_run` leaves it there."""
    return record_run(
        tenant=tenant,
        workflow_id=workflow_id(tenant=tenant, app="example", noun="widget", key=key),
        workflow_type="WidgetOnboardingWorkflow",
        input_digest="c" * 64,
        user=user,
    )


def test_cancel_accepts_a_running_run_of_my_own_and_stamps_nothing(
    api: Client, tenant: Tenant, owner: User, recorded_workflow_starts: None
) -> None:
    """The rung's whole shape in one test: accepted, and the row does not move.

    A door that answered `cancelled` here would be the ledger asserting an
    outcome because somebody asked for one. The row says `running` because the
    run IS running — Temporal has been asked to stop it and has not yet — and
    the contract sentence tells the caller to poll.

    Absent: a synchronous close, which reads as a stronger door and is a lie
    the moment a workflow ignores the cancel and completes.
    """
    api.force_login(owner)
    widget_id = _make_widget(api, owner, "Something to stop")
    run = WorkflowRun.objects.for_tenant(tenant).get(workflow_id__endswith=widget_id)
    assert run.status == WorkflowRun.Status.RUNNING
    AuditEntry.objects.all().delete()

    response = api.post(f"{RUNS_URL}{run.pk}/cancel/", content_type=JSON)
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["id"] == str(run.pk)
    assert body["status"] == WorkflowRun.Status.RUNNING
    assert body["finished_at"] is None
    assert body["error"] == ""

    run.refresh_from_db()
    assert run.status == WorkflowRun.Status.RUNNING
    assert run.finished_at is None
    assert run.error == ""

    entry = AuditEntry.objects.for_tenant(tenant).get(action="workflows.cancel_run")
    assert (entry.door, entry.outcome, entry.actor_user_id) == ("rest", "ok", owner.pk)


def test_cancel_refuses_a_colleagues_run_as_not_found(
    api: Client, tenant: Tenant, owner: User, member: User
) -> None:
    """The ownership wall, in its 404-shape. `forbidden` would be an oracle.

    Absent: a `403` here tells the asker that a run exists under that id and
    that somebody else in their tenant started it — which is the fact the
    tenant wall was already keeping.
    """
    run = _running_run(tenant=tenant, user=member, key="cancel-theirs")

    api.force_login(owner)
    response = api.post(f"{RUNS_URL}{run.pk}/cancel/", content_type=JSON)
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
    assert response.json() == api.post(f"{RUNS_URL}{uuid4()}/cancel/", content_type=JSON).json()

    run.refresh_from_db()
    assert run.status == WorkflowRun.Status.RUNNING


def test_cancel_refuses_another_tenants_run_as_not_found(
    api: Client, tenant: Tenant, other_tenant: Tenant, owner: User, stranger: User
) -> None:
    """The tenant wall, and it gives the same answer the ownership wall does."""
    theirs = _running_run(tenant=other_tenant, user=stranger, key="cancel-elsewhere")

    api.force_login(owner)
    response = api.post(f"{RUNS_URL}{theirs.pk}/cancel/", content_type=JSON)
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"

    theirs.refresh_from_db()
    assert theirs.status == WorkflowRun.Status.RUNNING


def test_cancel_refuses_a_run_with_no_recorded_starter(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """A NULL starter is unknown, so the run is nobody's — including the asker's."""
    orphan = _running_run(tenant=tenant, user=None, key="cancel-orphan")

    api.force_login(owner)
    response = api.post(f"{RUNS_URL}{orphan.pk}/cancel/", content_type=JSON)
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


@pytest.mark.parametrize(
    "status",
    [WorkflowRun.Status.COMPLETED, WorkflowRun.Status.FAILED, WorkflowRun.Status.CANCELLED],
)
def test_cancel_refuses_every_state_that_is_not_running(
    api: Client, tenant: Tenant, owner: User, status: str
) -> None:
    """The state wall, over the whole non-RUNNING population and naming each one.

    Parametrised over the states rather than written once for `failed`, because
    the criterion is that the conflict *names the status* — and a single case
    would prove the sentence exists without proving it varies.
    """
    run = _failed_run(tenant=tenant, user=owner, key=f"cancel-{status}")
    run.status = status
    run.save(update_fields=["status", "updated_at"])

    api.force_login(owner)
    response = api.post(f"{RUNS_URL}{run.pk}/cancel/", content_type=JSON)
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"
    assert f"already {status}" in response.json()["detail"]
    # Plain language, per the 2026-08-23 ruling: no engine, no namespace.
    assert "Temporal" not in response.json()["detail"]


def test_a_member_of_no_tenant_cannot_cancel(api: Client, nomad: User, tenant: Tenant) -> None:
    """Fails closed at the door: a write with no resolved tenant is refused."""
    run = _running_run(tenant=tenant, user=None, key="cancel-nomad")
    api.force_login(nomad)
    response = api.post(f"{RUNS_URL}{run.pk}/cancel/", content_type=JSON)
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_an_unauthenticated_caller_cannot_cancel(api: Client, tenant: Tenant, owner: User) -> None:
    """Rule 3 over the new route: the router's `auth=` covers it too."""
    run = _running_run(tenant=tenant, user=owner, key="cancel-anon")
    assert api.post(f"{RUNS_URL}{run.pk}/cancel/", content_type=JSON).status_code == 401


def test_a_read_scoped_token_cannot_cancel_and_a_write_scoped_one_can(
    api: Client, tenant: Tenant, owner: User, recorded_workflow_starts: None
) -> None:
    """ADR ident-7 over the new route, and nothing was annotated to get it.

    The scope is DERIVED from the operation's tag (`runs`) and its method
    (POST → write), so this route was born inside the ceiling with no line
    written anywhere. What this pins is that the derivation actually reached it:
    a read token is refused naming `runs:write`, and a token that carries it
    goes through.
    """
    from apps.accounts.services import issue_token

    run = _running_run(tenant=tenant, user=owner, key="cancel-scoped")
    _, narrow = issue_token(
        user=owner,
        tenant=tenant,
        name="read-only",
        scopes=["runs:read"],
        actor=actor_for(user=owner, tenant=tenant),
    )
    _, wide = issue_token(
        user=owner,
        tenant=tenant,
        name="can-write",
        scopes=["runs:write"],
        actor=actor_for(user=owner, tenant=tenant),
    )

    refused = api.post(
        f"{RUNS_URL}{run.pk}/cancel/",
        content_type=JSON,
        headers={"authorization": f"Bearer {narrow}"},
    )
    assert refused.status_code == 403, refused.content
    assert refused.json()["code"] == "insufficient_scope"
    assert "runs:write" in refused.json()["detail"]

    accepted = api.post(
        f"{RUNS_URL}{run.pk}/cancel/",
        content_type=JSON,
        headers={"authorization": f"Bearer {wide}"},
    )
    assert accepted.status_code == 200, accepted.content
    assert accepted.json()["status"] == WorkflowRun.Status.RUNNING


def test_the_same_idempotency_key_replays_the_first_cancel(
    api: Client, tenant: Tenant, owner: User, recorded_workflow_starts: None
) -> None:
    """Over the second write route this door has."""
    run = _running_run(tenant=tenant, user=owner, key="cancel-idempotent")
    api.force_login(owner)
    headers = {"idempotency-key": "cancel-once"}

    first = api.post(f"{RUNS_URL}{run.pk}/cancel/", content_type=JSON, headers=headers)
    assert first.status_code == 200, first.content

    second = api.post(f"{RUNS_URL}{run.pk}/cancel/", content_type=JSON, headers=headers)
    assert second.status_code == 200
    assert second.json() == first.json()
    assert second.headers.get("Idempotent-Replayed") == "true"


# --- The walls at the SERVICE, and the ORDER they stand in --------------------------
#
# The door tests above prove each wall answers; only a service test can prove
# they are consulted in the right ORDER, and the order is the refusal grammar.
# Each of the three below is a case where two walls would both refuse and only
# one of them is allowed to be the one that speaks.


def test_the_tenant_wall_speaks_before_the_policy_wall(
    tenant: Tenant, other_tenant: Tenant, stranger: User, nomad: User, root_org: Organization
) -> None:
    """A run elsewhere, asked for by somebody with no standing anywhere.

    Both the tenant wall and the policy wall would refuse. It must be the tenant
    wall: `Forbidden` here would say "that run exists and you are not allowed
    to touch it", which is the existence oracle the scoping was closing.
    """
    from apps.core.actor import actor_for
    from apps.workflows.services import cancel_run

    theirs = _running_run(tenant=other_tenant, user=stranger, key="order-elsewhere")
    outsider = actor_for(user=nomad, tenant=tenant, org=root_org)

    with pytest.raises(NotFound):
        cancel_run(tenant=tenant, actor=outsider, run_id=theirs.pk)


def test_the_policy_wall_speaks_before_the_ownership_wall(
    tenant: Tenant, nomad: User, root_org: Organization
) -> None:
    """A run in this tenant, asked for by somebody with no membership in it.

    They are not the starter either, so the ownership wall would also refuse —
    with `NotFound`. It must be the policy wall, because "you have no standing
    to stop jobs here" is a true and actionable thing to say to somebody who is
    not in the tenant, and hiding it behind a 404 would send them looking for a
    run id that was never the problem.
    """
    from apps.core.actor import actor_for
    from apps.workflows.services import cancel_run

    ours = _running_run(tenant=tenant, user=None, key="order-no-membership")
    outsider = actor_for(user=nomad, tenant=tenant, org=root_org)

    with pytest.raises(Forbidden):
        cancel_run(tenant=tenant, actor=outsider, run_id=ours.pk)


def test_the_ownership_wall_speaks_before_the_state_wall(
    tenant: Tenant, owner: User, owner_actor: Actor, member: User
) -> None:
    """A colleague's run that is ALSO in a state a cancel could not touch.

    The state wall would refuse with a `Conflict` naming `completed` — which
    tells the asker that a run exists under that id and how it ended. It must be
    the ownership wall's `NotFound`, indistinguishable from a guessed id.
    """
    from apps.workflows.services import cancel_run

    theirs = _running_run(tenant=tenant, user=member, key="order-theirs-and-done")
    theirs.status = WorkflowRun.Status.COMPLETED
    theirs.finished_at = timezone.now()
    theirs.save(update_fields=["status", "finished_at", "updated_at"])

    with pytest.raises(NotFound):
        cancel_run(tenant=tenant, actor=owner_actor, run_id=theirs.pk)

    # And the same row, asked for by the person who started it, reaches the
    # state wall — which is what makes the assertion above about ORDER rather
    # than about one wall being unreachable.
    mine = _running_run(tenant=tenant, user=owner, key="order-mine-and-done")
    mine.status = WorkflowRun.Status.COMPLETED
    mine.finished_at = timezone.now()
    mine.save(update_fields=["status", "finished_at", "updated_at"])
    with pytest.raises(Conflict):
        cancel_run(tenant=tenant, actor=owner_actor, run_id=mine.pk)


def test_no_workflow_id_is_built_anywhere_on_the_cancel_path(
    tenant: Tenant, owner: User, owner_actor: Actor, recorded_workflow_starts: None
) -> None:
    """Rule 18 from the other side: the STORED id is used, never a fresh one.

    A cancel that minted an id would ask Temporal to stop an execution that
    does not exist and would answer `200` while the job carried on. The row's
    own `workflow_id` is the only id on this path, and `workflow_id()` is not
    called at all.
    """
    from apps.workflows import services as workflow_services

    run = _running_run(tenant=tenant, user=owner, key="no-minting")

    def refuse(**_kwargs: Any) -> str:
        raise AssertionError("cancel_run built a workflow id instead of reading the row's")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(workflow_services, "workflow_id", refuse)
    try:
        answered = workflow_services.cancel_run(tenant=tenant, actor=owner_actor, run_id=run.pk)
    finally:
        monkey.undo()

    assert answered.workflow_id == run.workflow_id


@pytest.mark.django_db(transaction=True)
def test_an_accepted_cancel_asks_temporal_for_exactly_that_execution(
    tenant: Tenant, owner: User, owner_actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hook fires on commit and names the run it is stopping.

    `transaction=True` because the whole subject is the `on_commit` hook, which
    a non-transactional test never reaches. The client is replaced rather than
    dialled: what is under test is which execution the service asked about, not
    Temporal's behaviour, which the harness test one module over drives for
    real.
    """
    from apps.workflows import client as client_module
    from apps.workflows.services import cancel_run

    run = _running_run(tenant=tenant, user=owner, key="cancel-dispatch")
    WorkflowRun.objects.filter(pk=run.pk).update(run_id="execution-under-way")
    asked: list[tuple[str, str | None]] = []

    class FakeHandle:
        def __init__(self, workflow_id: str, run_id: str | None) -> None:
            self.workflow_id = workflow_id
            self.run_id = run_id

        async def cancel(self) -> None:
            asked.append((self.workflow_id, self.run_id))

    class FakeClient:
        def get_workflow_handle(self, workflow_id: str, run_id: str | None = None) -> Any:
            return FakeHandle(workflow_id, run_id)

    async def connect() -> Any:
        return FakeClient()

    monkeypatch.setattr(client_module, "get_client", connect)
    cancel_run(tenant=tenant, actor=owner_actor, run_id=run.pk)

    assert asked == [(run.workflow_id, "execution-under-way")]
    run.refresh_from_db()
    assert run.status == WorkflowRun.Status.RUNNING


# --- Two transitions on one row -------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_two_replays_of_one_run_yield_one_success_and_one_refusal(
    tenant: Tenant, owner: User, owner_actor: Actor, recorded_workflow_starts: None
) -> None:
    """Driven rather than argued: real threads, real rows, one lock.

    Two people (or one person and their retrying client) pressing replay at the
    same moment both read a FAILED row. Without `select_for_update` both write
    RUNNING and both ask Temporal to reset the same execution; with it, the
    second waits, then meets a row that is already RUNNING and is refused.

    Absent: a replay door that silently double-runs, which the criterion names
    as worse than no door at all.
    """
    from threading import Thread

    from django.db import connection

    from apps.core.exceptions import Conflict
    from apps.workflows.services import start_replay

    run = _failed_run(tenant=tenant, user=owner, key="raced")
    outcomes: list[str] = []

    def attempt() -> None:
        try:
            start_replay(tenant=tenant, actor=owner_actor, run_id=run.pk)
            outcomes.append("ok")
        except Conflict:
            outcomes.append("conflict")
        finally:
            # Each thread borrowed its own connection and there is no request
            # cycle out here to hand it back.
            connection.close()

    threads = [Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(outcomes) == ["conflict", "ok"], outcomes
    run.refresh_from_db()
    assert run.status == WorkflowRun.Status.RUNNING


def test_an_unauthenticated_caller_gets_nothing(api: Client, tenant: Tenant) -> None:
    """Rule 3: the router's `auth=` is not decoration."""
    assert api.get(RUNS_URL).status_code == 401


def test_a_member_of_no_tenant_reads_an_empty_ledger(api: Client, nomad: User) -> None:
    """Fails closed: no membership resolves no tenant, and no tenant reads nothing.

    A `403` would be the wrong answer and a row would be worse: `for_tenant(None)`
    is the wall, and `require` is what refuses the *action* to somebody with no
    standing at all.
    """
    api.force_login(nomad)
    response = api.get(RUNS_URL)
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_the_ledger_never_shows_a_platform_run(
    api: Client, tenant: Tenant, owner: User, other_tenant: Tenant
) -> None:
    """ADR workflows-3 through this door: `for_tenant` cannot reach the null population.

    Asserted rather than argued, because "by construction" is exactly the kind
    of claim that stops being true when somebody adds a `Q(tenant__isnull=True)`
    for a good local reason.
    """
    platform = record_run(
        tenant=None,
        workflow_id="platform:accounts:identity:sync",
        workflow_type="SyncWorkforceIdentity",
        user=owner,
    )
    api.force_login(owner)
    wide = api.get(f"{RUNS_URL}?mine=false").json()
    assert str(platform.pk) not in [row["id"] for row in wide["items"]]
    assert api.get(f"{RUNS_URL}{platform.pk}/").status_code == 404


def test_a_superseded_row_changes_hands(tenant: Tenant, owner: User, member: User) -> None:
    """`_reopen`'s fourth quadrant carries `started_by` with it.

    Absent: the first person keeps a replay door onto work that is now somebody
    else's, and the ledger answers "yours" about a run they did not start.
    """
    key = workflow_id(tenant=tenant, app="example", noun="widget", key="supersede")
    first = record_run(
        tenant=tenant,
        workflow_id=key,
        workflow_type="WidgetOnboardingWorkflow",
        input_digest="a" * 64,
        user=owner,
    )
    first.status = WorkflowRun.Status.COMPLETED
    first.finished_at = timezone.now()
    first.save(update_fields=["status", "finished_at", "updated_at"])

    second = record_run(
        tenant=tenant,
        workflow_id=key,
        workflow_type="WidgetOnboardingWorkflow",
        input_digest="b" * 64,
        user=member,
    )
    assert second.pk == first.pk
    assert second.started_by_id == member.pk


def test_the_actor_fixture_is_not_what_the_door_uses(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """A run started by a *service* call is still the caller's own run.

    The door and the service agree about who started something because both
    thread the same user; this is the seam said out loud so a future refactor
    that drops `user=` from a starter fails here rather than in six months.
    """
    from apps.example.services import create_widget

    widget = create_widget(tenant=tenant, actor=owner_actor, name="Service made")
    run = WorkflowRun.objects.for_tenant(tenant).get(workflow_id__endswith=str(widget.pk))
    assert run.started_by_id == owner.pk

    api.force_login(owner)
    assert str(run.pk) in [row["id"] for row in api.get(RUNS_URL).json()["items"]]
