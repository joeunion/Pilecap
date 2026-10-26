# Tests — the worked forms

The long form of `django-conventions` §12.

**A schedule test asserts about its own ids, never the discovered set.**
`ensure_schedules()` returns the **cross-app** result of discovery. A test
asserting `ensured == [...]` is asserting about every other app's schedules
and breaks the day a sibling app declares one — a green suite turned red by a
module it never mentions. Assert **containment** of your own ids
(`assert "ensure_purge_schedule" in ensured`), never equality with the set.
Same reasoning as `INSTALLED_APPS` being derived: discovery is what lets one
agent per app run in parallel, and a test that pins the discovered set takes
that back.

```python
def test_orders(): assert Order.objects.filter(status="nope").count() == 0   # wrong — cannot fail

# right — the property, through the door a user uses, with the tenant sibling
# (fixtures from apps/conftest.py: api, tenant, other_tenant, owner, stranger, nomad, root)
@pytest.mark.django_db
def test_list_orders_is_scoped_to_tenant(api, tenant, other_tenant, owner, stranger):
    mine = services.create_order(tenant=tenant, actor=actor_for(user=owner, tenant=tenant),
                                 customer=customer(tenant), lines=[line()])
    services.create_order(tenant=other_tenant, actor=actor_for(user=stranger, tenant=other_tenant),
                          customer=customer(other_tenant), lines=[line()])
    api.force_login(owner)                         # owner's default membership is `tenant`
    resp = api.get("/api/v1/orders/")
    assert resp.status_code == 200
    assert [o["id"] for o in resp.json()["items"]] == [str(mine.pk)]   # items + has_more + next_cursor

@pytest.mark.django_db
def test_list_orders_query_budget(api, owner, django_assert_num_queries, seeded_orders):
    api.force_login(owner)
    with django_assert_num_queries(LIST_QUERY_BUDGET):     # measured at seeded scale; the comment says how
        api.get("/api/v1/orders/")            # and one more with ?include_count=true: the count is a choice

@pytest.mark.django_db(transaction=True)        # the activity writes from another thread, on another connection
@pytest.mark.asyncio
async def test_onboard_waits_for_confirmation(tenant, owner):
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = attach_interceptors(env.client)                  # apps.workflows.client: the tenant has to ride along
        async with build_worker(client, queue="t"):               # the real discovery, not a hand-built list
            run = await start_workflow(workflow="OnboardTenant", arg=OnboardIn(email="a@b.c"),
                                       tenant=tenant, user=owner, id="onboard-1", client=client, task_queue="t")
            handle = client.get_workflow_handle(run.workflow_id)  # NOT auto-skipping — see below
            await handle.signal("confirm")                        # this test finishes because the signal preempts
            result = await handle.result()                        # the wait, not because the clock moved
            assert result.confirmed_at is not None
```

**Auto-skip rides only on a handle `start_workflow` RETURNED.** The environment
installs a client interceptor whose `start_workflow` re-classes the handle it
returns into a `_TimeSkippingWorkflowHandle`
(`temporalio/testing/_workflow.py:600-605`), and it is *that* class's `result()`
that unlocks time skipping (`:610-620`). A handle you build yourself with
`client.get_workflow_handle(...)` — which is what you must do when the run was
started by a service's on-commit hook, as it is here — is a plain
`WorkflowHandle`: awaiting its `result()` moves no clock at all. The snippet
above survives only because the signal arrives before the seven-day timer
matters; take the signal away and it waits seven real days.

The tree's worked example is the shape to copy when nothing preempts the wait —
`apps/example/tests/test_workflows.py:101-105` says it in its own comment and
advances the clock explicitly, in day-sized steps rather than one leap, because
the timer is created a moment after the first activity finishes and a single
jump can land before it exists:

```python
handle = client.get_workflow_handle(onboarding_id(tenant, widget), result_type=WidgetOnboarded)
for _ in range(APPROVAL_DAYS + 3):
    if (await handle.describe()).status is not WorkflowExecutionStatus.RUNNING:
        break
    await env.sleep(timedelta(days=1))          # the clock the hand-built handle does not move for you
result = await handle.result()
```

## The standing rules, and the door and scoping siblings

- pytest-django + pytest-asyncio; `@pytest.mark.django_db` (`transaction=True`
  only when the code under test commits — `on_commit` hooks and activities on
  another connection need it). Set-up through the shared fixtures in
  `apps/conftest.py` or `services.create_*`, not raw `Model.objects.create`.
- **Test vocabulary a `core` or `accounts` test imports never lives in
  `apps/conftest.py`.** That conftest imports `accounts` and `workflows` at
  module level, so a `core` test importing from it breaks the layers contract
  in `pyproject.toml` ("The fixed layers hold: platform above accounts above
  core"). Put it in a module at the lowest layer that reads it — the worked
  example is `apps/core/tests/template_shape.py::identity_shape` (the
  `DJB_IDENTITY_SHAPE` parser), beside the `@template_shape` mark it serves.
- **Test the property, not the mechanism.** "The signal fired" is a mechanism;
  "the receipt row exists" is a property. **No test that cannot fail.**
- **REST through the mounted API** with the pytest-django `client`, so
  `TenantMiddleware` runs and `request.tenant` is real.
  `ninja.testing.TestClient(router)` skips middleware — only for a router with
  no tenant dependence, and say so. Assert status code **and** body.

- **MCP** tools are called as functions with a fake `Context` whose
  `request_context.request.scope[SCOPE_KEY]` is a `Principal(user, tenant)`
  (`apps.core.mcp`); assert the output equals the REST route's for the same row
  (door parity).
- **Sockets** with `apps.realtime.tests.websocket` — the in-repo raw-ASGI
  client, **not** `channels.testing.WebsocketCommunicator`, whose package
  `__init__` imports `daphne` and this repository serves with uvicorn:
  connect as a user, emit through a service, assert the push arrives; connect
  as a user in another tenant, assert it does not.
- **Workflows** under `WorkflowEnvironment.start_time_skipping()`, the worker
  from `apps.workflows.client.build_worker` (the real discovery) on a client with
  `attach_interceptors` applied, so the tenant rides along (a seven-day wait
  takes milliseconds — on a handle `start_workflow` returned, or on `env.sleep`
  when you built the handle yourself; the snippet above says why);
  decision logic with fake activities; activities awaited
  directly against the database. Never point a test at the dev server.
- **An org-scoped model needs the sibling test, not just the second-tenant
  one.** "Another tenant's rows are absent" no longer proves the scoping: build
  a small tree (root → seller A → sub A1, root → seller B) and assert that A1
  sees only its own, A sees A's and A1's, A cannot see B, A1 cannot see A, and
  that switching `X-Org` on one person who is a member of both changes the set.
  `apps/example/tests/test_network.py` is the worked example. Actor fixtures
  name their hat (`actor_for(user=…, tenant=…, org=…)`) for the same reason they
  name their role: an actor with `org=None` reads nothing, so a test that forgot
  would pass or fail for a reason it never stated.
- **A test that reads a paginated door to assert about a whole POPULATION owes
  `assert body["has_more"] is False`, or it walks the cursor.** A list route
  answers one page — `API_PAGE_SIZE`, 50 by default
  (`config/settings/base.py::API_PAGE_SIZE`) — and `{items, has_more, next_cursor, count}`
  is the whole envelope (`apps/core/api/pagination.py:203`, `:661`). A test that
  derives a population from `body["items"]` and never looks at `has_more` is
  asserting about the first 50 rows while claiming to assert about all of them:
  it passes, and then it goes quietly vacuous on the 51st row somebody adds —
  no failure, no red, just a claim that stopped being true. Assert the flag
  when you expect one page (`apps/core/tests/test_pagination.py:167` is the
  worked line), and walk `next_cursor` when you do not
  (`test_pagination.py:110-120`, the `_walk` helper, is the worked loop — note
  its hop bound, so a broken walk fails rather than hangs). The same applies to a test
  pinning a whole response body: `apps/core/tests/test_resource_first_urls.py`
  pins `"has_more": false` inside the bodies it fixes, which is what makes those
  pins mean what they say.

- One query pin per list route at seeded scale × k. `settings` via the
  `settings` fixture, never by mutating `django.conf.settings`. Tests live in
  `apps/<name>/tests/`, one module per surface (`test_api.py`, `test_mcp.py`,
  `test_workflows.py`, `test_services.py`).
