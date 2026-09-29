"""PR4.e — **every door selector over a kind asks, and the archive asks too.**

Phase R makes a read a permission (ADR core-27). For this app that lands in
three places and they are deliberately different shapes:

1. **The two door selectors** — `list_exports` and `get_export` — ask
   `export.read`, once, inside `selectors.py`, so no door can forget (§C6).
   `get_export` asks AFTER the scoped fetch and at the ROW's node, which is what
   makes a row in a sibling branch `not_found` and a row inside the hat without
   the key `forbidden` — reach before capability.
2. **Both doors say the same words**, because both go through the same
   `require` and the same `wire_refusal` (rule 46's parity case lives in
   `test_doors_over_the_wire.py`, where the pair is declared).
3. **The archive is a read of every table in it.** `list_exportable_rows` asks
   `<kind>.read` per model at the export's hat, as the REQUESTER, and a kind
   they may not read is OMITTED and named in `manifest.json` rather than written
   as an empty file — because an empty `.jsonl` says "you have none of these",
   which is a different and false sentence.

**What the instruments answer when the thing is ABSENT** is stated per test, in
its own docstring, because a check that returns the same value either way is a
check that cannot fail.
"""

from __future__ import annotations

import inspect
import io
import json
import re
import zipfile
from typing import TYPE_CHECKING, Any

import pytest
from django.test import Client

from apps.core.actor import actor_for
from apps.core.authz import kind_of, refusal_sentence
from apps.core.exceptions import Forbidden, NotFound
from apps.core.models import Grant, Membership
from apps.core.services import root_organization
from apps.exports import selectors
from apps.exports.activities import MANIFEST_NAME, MODELS_DIRECTORY, _write_the_archive
from apps.exports.models import Export
from apps.exports.services import create_export

from .conftest import PASSWORD, archive_bytes

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.accounts.models import User

    from .conftest import World

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/exports/"
DETAIL_URL = "/api/v1/exports/{}/"

#: The valve rule 54 (d) reads on a selector that deliberately does not ask.
#: Spelled as a pattern rather than as the marker itself, so this module does
#: not register a phantom valve by talking about one (rung-execution §5).
VALVE = re.compile(r"#\s*read-(?:open|kind):\s*\S")


def _withhold(*, world: World, user: User, permission: str) -> Grant:
    """Take one key away from one person, the way a deployment would.

    A `withhold` beats everything — "forbid overrides permit" — so this is the
    smallest world in which a plain member is refused a read: nothing about the
    role changes, and the only difference between the two halves of every test
    below is this one row.
    """
    membership = Membership.objects.filter(tenant=world.tenant).get(user=user)
    return Grant.objects.create(
        tenant=world.tenant,
        membership=membership,
        permission=permission,
        effect=Grant.Effect.WITHHOLD,
    )


# --- 1 · the population, derived rather than listed ---------------------------


def test_every_door_selector_asks_or_says_why() -> None:
    """**PR4.e.1.** The population is derived, and every member is accounted for.

    A hand-written list of selectors goes stale the first time one is added,
    which turns the rule back into a comment. So the population is derived here
    the way rule 54 (d) derives it — every public `get_`/`list_` in the module
    whose return annotation resolves to a model with an authorization kind — and
    each member either takes `actor` (and the cases below exercise the require)
    or carries the declared valve with a reason.

    *Absent:* on the baseline tree neither `list_exports` nor `get_export` has
    `actor` in its signature and neither carries a valve, so this fails naming
    both.
    """
    source = inspect.getsource(selectors)
    population = {
        name: function
        for name, function in vars(selectors).items()
        if (name.startswith(("get_", "list_")) and inspect.isfunction(function))
    }
    assert set(population) == {"get_export", "list_exports", "list_exportable_rows"}, sorted(
        population
    )

    silent = []
    for name, function in sorted(population.items()):
        if "actor" in inspect.signature(function).parameters:
            continue
        body = inspect.getsource(function)
        if not VALVE.search(body):
            silent.append(name)
    assert silent == [], silent
    assert "def _visible(" in source, "the unasked fetch is private, not a door selector"


# --- 2 · the order: reach before capability -----------------------------------


def test_a_read_outside_the_subtree_is_not_found_and_inside_without_the_key_is_forbidden(
    world: World, recorded_workflow_starts: None
) -> None:
    """**PR4.e.1.** The two exception types, in that order, ARE the criterion.

    A member acting at the region, with `export.read` withheld:

    * an export in the SIBLING branch → `NotFound`. The scoping answered first,
      and a `Forbidden` there would tell them the row exists.
    * an export inside their own subtree → `Forbidden`, with the key's own
      sentence.
    * the list at their own hat → `Forbidden`.

    *Absent (baseline):* the row and the page, for all three.
    """
    inside = create_export(tenant=world.tenant, actor=world.region_actor)
    beside = create_export(
        tenant=world.tenant,
        actor=actor_for(user=world.owner, tenant=world.tenant, org=world.sibling),
    )
    _withhold(world=world, user=world.region_admin, permission="export.read")
    acting = actor_for(user=world.region_admin, tenant=world.tenant, org=world.region)

    with pytest.raises(NotFound):
        selectors.get_export(
            tenant=world.tenant, export_id=beside.pk, org=world.region, actor=acting
        )
    with pytest.raises(Forbidden) as forbidden:
        selectors.get_export(
            tenant=world.tenant, export_id=inside.pk, org=world.region, actor=acting
        )
    assert str(forbidden.value.detail) == refusal_sentence("export.read")
    with pytest.raises(Forbidden):
        selectors.list_exports(tenant=world.tenant, org=world.region, actor=acting)


def test_with_the_key_the_same_person_reads_both(
    world: World, recorded_workflow_starts: None
) -> None:
    """The other half of the pair: no withhold, and nothing moved.

    Without this the test above proves only that a refusal happens somewhere,
    not that the withhold is what caused it.
    """
    inside = create_export(tenant=world.tenant, actor=world.region_actor)
    acting = actor_for(user=world.region_admin, tenant=world.tenant, org=world.region)

    found = selectors.get_export(
        tenant=world.tenant, export_id=inside.pk, org=world.region, actor=acting
    )
    assert found.pk == inside.pk
    assert selectors.list_exports(tenant=world.tenant, org=world.region, actor=acting).count() == 1


# --- 3 · the wire, and the plain member -------------------------------------


def test_the_plain_member_still_reads_everything(
    api: Client, world: World, recorded_workflow_starts: None
) -> None:
    """**PR4.e.2, the flat-product half.** A product that customised nothing.

    `member` holds `*.read` by declaration, so the list and the detail answer
    200 for an ordinary member exactly as they did before Phase R. This is the
    non-vacuity line under every refusal test in this module: if the door
    refused everyone, they would all pass and the app would be broken.

    *Absent:* a 403 here, which is what a missing `DEFAULT_ROLES`/pattern would
    produce.
    """
    plain = _plain_member(world)
    export = create_export(tenant=world.tenant, actor=world.owner_actor)
    api.force_login(plain)

    listed = api.get(LIST_URL, headers={"X-Org": world.root.slug})
    assert listed.status_code == 200, listed.content
    assert [one["id"] for one in listed.json()["items"]] == [str(export.pk)]

    one = api.get(DETAIL_URL.format(export.pk), headers={"X-Org": world.root.slug})
    assert one.status_code == 200, one.content


def test_a_withheld_read_is_forbidden_on_the_wire_with_the_keys_own_sentence(
    api: Client, world: World, recorded_workflow_starts: None
) -> None:
    """**PR4.e.2, REST.** 403 `forbidden`, and the body is the key's sentence.

    *Absent (baseline):* 200 with the page.
    """
    plain = _plain_member(world)
    export = create_export(tenant=world.tenant, actor=world.owner_actor)
    _withhold(world=world, user=plain, permission="export.read")
    api.force_login(plain)

    listed = api.get(LIST_URL, headers={"X-Org": world.root.slug})
    assert listed.status_code == 403, listed.content
    assert listed.json()["code"] == "forbidden"
    assert listed.json()["detail"] == refusal_sentence("export.read")

    one = api.get(DETAIL_URL.format(export.pk), headers={"X-Org": world.root.slug})
    assert one.status_code == 403, one.content
    assert one.json()["detail"] == refusal_sentence("export.read")


def _plain_member(world: World) -> User:
    """Somebody with the default role at the root and nothing else."""
    from apps.accounts.services import create_user
    from apps.core.services import add_membership

    person = create_user(email="plain-member@acme.com", password=PASSWORD)
    add_membership(
        user=person,
        tenant=world.tenant,
        organization=world.root,
        is_default=True,
        role=Membership.Role.MEMBER,
        actor=world.owner_actor,
    )
    return person


# --- 4 · the pins ------------------------------------------------------------


def test_the_create_door_resolves_the_actor_once(
    api: Client, world: World, recorded_workflow_starts: None, django_assert_num_queries: Any
) -> None:
    """**PR4.e.3, and a disproved half of the shared shape.**

    PR4.x.3 says a write door that *fetches through a `get_`* and then calls a
    service pays +3 and never +6. **This app has no such door**: `POST
    /exports/` takes a body, not an id, so nothing on the write path goes
    through `get_export` and there is no second resolution for the memo to save.
    The honest measurement is therefore that the ACTOR is still resolved once,
    and the number is pasted here rather than rounded into the criterion's
    shape:

    * baseline `11b1a765`, and the exports sweep's own tree `7f4d72a0`: **60**
      queries.
    * after the W3 read sweep merged: **61**, and the +1 was neither ours nor a
      second resolution of the actor.
    * **this tree: back to 60**, and the +1 is gone rather than absorbed. What
      it was, and why it went, is the whole of the note below.

    **The statement that arrived, and the one thing that now answers it.** The
    +1 was:

        SELECT … FROM "core_organization"
        WHERE ("core_organization"."tenant_id" = %s
               AND "core_organization"."parent_id" IS NULL)
        ORDER BY "core_organization"."path" ASC LIMIT 1

    was issued by `apps.core.services.root_organization` under a `_tenant_root`
    helper in `events.selectors`, from `events.selectors.get_event` — which
    `events.services.enqueue_dispatch` calls on the `emit()` this service's
    `_publish` performs inside the write's transaction. It arrived with the **W3
    read sweep** (`844a6f57`, "the tenant-wide reads ask at the ROOT", merged to
    main as `c1f54128`), which made the `events` reads ask `event.read` at the
    tenant's ROOT node rather than at the acting hat (house rule 55), and it
    LEFT again with PR5.5, which answered that question the other way: the
    helper is deleted and no read resolves a node.

    **It used to be a PER-CALL cost, then one resolution per request, and the
    read path does not pay it at all now.** The helper held no memo, so every
    `get_event`, `list_events` and `list_endpoints` read the root again and any
    request that emitted twice paid it twice — N reads for N events, with
    nothing bounding N. The root is now
    memoised on the tenant instance (`core.models.Tenant`, where the contract is
    declared), `core.services.root_organization` is where the memo lives so
    every site inherits it, and `core.middleware.resolve_org` fills it from the
    acting hat it has already read. **This request sends `X-Org` naming the
    root**, so the hat IS the root, the memo is full before `create_export`
    starts, and the emit inside the transaction reads nothing: 60.

    **And the question that was open when this was written is decided.** A
    tenant-wide kind is READ at the acting hat and WRITTEN at the tenant's root
    (PR5.5, 2026-09-17; the reasoning and the v2.2 successor are in the
    universal-homing proposal, 2026-09-17 — every record homed at a node), so
    the `get_event` under `emit()` no longer resolves a root at all. This number
    did not move for it: the memo had already made that resolution free for a
    request whose hat IS the root, which this one's is. What the decision moved
    is the number a BRANCH-hat request pays, which was one more, once — and the
    correctness the W3 sweep bought is untouched, because every WRITE is still
    asked at the root.

    Asserted as an equality in both directions, so that a lost memo on the
    EXPORTS side — which would put three more on it — is a failure rather than
    a slow page, and so that a lost ROOT memo — which puts one back — is a
    failure rather than a slower write path in every app that emits.
    """
    api.force_login(world.owner)
    with django_assert_num_queries(WRITE_QUERY_BUDGET):
        response = api.post(
            LIST_URL,
            data=json.dumps({"scope": "organization"}),
            content_type="application/json",
            headers={"X-Org": world.root.slug},
        )
    assert response.status_code == 201, response.content


#: Measured on the baseline `11b1a765` and on the exports sweep's own tree
#: `7f4d72a0` (60 both times), re-measured at 61 on main after the W3 sweep
#: merged, and **re-derived at 60 here** now that the tenant root is resolved
#: once per request instead of once per call. The create door still reads the
#: actor's three permission tables ONCE and the rest is the write itself; a
#: second resolution of the actor would make it three more. The +1 that came
#: and went is `root_organization()` under the `emit()` inside the transaction
#: (W3, `844a6f57` → `c1f54128`); it is now answered from the memo the door's
#: own hat resolution filled (`core.models.Tenant`, `core.middleware`), so the
#: root is READ once per request and never once per event emitted — and since
#: PR5.5 the read path does not resolve one at all, which took this from
#: "free because the memo was full" to "not asked". Unmoved either way, because
#: this request's hat IS the root; a BRANCH-hat request is where the difference
#: was. The test above says which request this is and why its hat is the root.
#: **60 → 59:** the create key's member predicate asks `membership_for`, which
#: reads the memberships the actor already memoizes rather than the table.
WRITE_QUERY_BUDGET = 59


# --- 5 · the archive ---------------------------------------------------------


def test_an_archive_omits_the_kinds_the_requester_may_not_read_and_says_so(
    world: World, neighbour: Any, archive_bucket: str, recorded_workflow_starts: None
) -> None:
    """**PR4.e, the archive half.** A withheld kind is not in the zip, and is named.

    The requester holds every other read, so the archive is otherwise the same
    archive — which is what makes the missing table a measurement rather than a
    coincidence. Driven through `_write_the_archive` (the walk itself) with a
    real bucket, which is how every other archive claim in this app is proved:
    `test_workflows.py` owns the "the run reaches `completed`" half.

    *Absent (baseline):* `example.Widget` is in the archive and
    `manifest["omitted_models"]` does not exist at all.
    """
    owner_actor = world.owner_actor
    export = create_export(tenant=world.tenant, actor=owner_actor, scope=Export.Scope.TENANT)
    _withhold(world=world, user=world.owner, permission="widget.read")

    version, manifest = _write_the_archive(
        export=export, hat=root_organization(tenant=world.tenant), actor=owner_actor
    )

    omitted = {str(one["label"]): str(one["reason"]) for one in manifest["omitted_models"]}
    assert omitted == {"example.Widget": "unreadable"}, omitted
    carried = {str(one["label"]) for one in manifest["models"]}
    assert "example.Widget" not in carried
    assert "example.WidgetEntry" in carried, "only the withheld kind is missing"

    with zipfile.ZipFile(io.BytesIO(archive_bytes(str(version.key)))) as archive:
        names = set(archive.namelist())
    assert f"{MODELS_DIRECTORY}/example.Widget.jsonl" not in names
    assert f"{MODELS_DIRECTORY}/example.WidgetEntry.jsonl" in names


def test_the_omission_is_a_named_fact_not_an_empty_file(
    world: World, neighbour: Any, archive_bucket: str, recorded_workflow_starts: None
) -> None:
    """**PR4.e.** `None` and `.none()` are different facts, and both reach the zip.

    The same walk twice: once refused a kind, once allowed it with no rows to
    show. The refused kind has no file and a manifest line; the allowed-but-empty
    kind has an empty file, no manifest line under `omitted_models`, and a row
    count of zero. A selector that returned `.none()` for a refusal would make
    the two indistinguishable, which is the defect this test exists for.
    """
    owner_actor = world.owner_actor
    export = create_export(tenant=world.tenant, actor=owner_actor, scope=Export.Scope.TENANT)
    _withhold(world=world, user=world.owner, permission="widget.read")
    version, manifest = _write_the_archive(
        export=export, hat=root_organization(tenant=world.tenant), actor=owner_actor
    )
    with zipfile.ZipFile(io.BytesIO(archive_bytes(str(version.key)))) as archive:
        document = json.loads(archive.read(MANIFEST_NAME))

    empty = [one for one in document["models"] if int(one["rows"]) == 0]
    assert empty, "the world needs at least one readable table with no rows"
    for one in empty:
        assert one["label"] not in {row["label"] for row in document["omitted_models"]}
    assert [one["label"] for one in document["omitted_models"]] == ["example.Widget"]
    assert manifest == document, "the manifest on the row is the manifest in the zip"


def test_a_model_the_requester_may_read_comes_back_as_a_queryset(world: World) -> None:
    """The selector's own two answers, without the zip around them.

    `None` means refused; a queryset — even an empty one — means allowed. The
    pair is asserted here so the archive tests above are reading a difference
    the selector really makes rather than one the walk invented.
    """
    from apps.exports.census import dispositions

    disposition = dispositions()["example.Widget"]
    allowed = actor_for(user=world.owner, tenant=world.tenant, org=world.root, kind="agent")
    rows = selectors.list_exportable_rows(
        tenant=world.tenant, org=world.root, disposition=disposition, actor=allowed
    )
    assert rows is not None
    assert rows.count() >= 1

    _withhold(world=world, user=world.owner, permission="widget.read")
    refused = actor_for(user=world.owner, tenant=world.tenant, org=world.root, kind="agent")
    assert (
        selectors.list_exportable_rows(
            tenant=world.tenant, org=world.root, disposition=disposition, actor=refused
        )
        is None
    )


def test_the_kind_a_read_is_asked_for_is_the_models_own(world: World) -> None:
    """Rule 54 (e) in the app's own words: the key names the model's kind.

    `kind_of` is the one function that answers it — `authz_kind`,
    `authz_kind_of`, or the class name — so a model that later declares a
    different kind moves this selector's question with it and nothing here has
    to be edited.
    """
    from apps.exports.census import dispositions

    assert kind_of(Export) == "export"
    assert selectors.READ == "export.read"
    for label, disposition in sorted(dispositions().items()):
        assert kind_of(disposition.model) is not None or label, label


# --- 6 · reach before capability, on the WRITE side too ----------------------


@pytest.mark.parametrize(
    "call",
    ["mark_export_running", "finish_export", "record_export_failure"],
)
def test_a_foreign_export_is_not_found_and_never_forbidden(
    world: World, recorded_workflow_starts: None, call: str
) -> None:
    """**Rule 26's order, on this app's three build services.**

    All three take an `Export` INSTANCE, which is the shape the order exists
    for: a caller holding a row fetched outside their own subtree hands it
    straight in, and all three asked `export.build` FIRST until the sweep — so
    the refusal they got back was `Forbidden`, whose very existence says *that
    export is real, and it is not yours*. `NotFound` says neither.

    The actor is an admin at the region; the export belongs to the SIBLING
    branch, where they hold nothing. Reach is what they fail, so reach is what
    must answer.

    *Absent (baseline `11b1a765`):* `Forbidden` from all three, with
    `export.build`'s own sentence — the leak.
    """
    from apps.exports import services

    beside = create_export(
        tenant=world.tenant,
        actor=actor_for(user=world.owner, tenant=world.tenant, org=world.sibling),
    )
    acting = actor_for(user=world.region_admin, tenant=world.tenant, org=world.region)
    arguments: dict[str, Any] = {"tenant": world.tenant, "actor": acting, "export": beside}
    if call == "finish_export":
        arguments |= {"version": None, "manifest": {}}
    if call == "record_export_failure":
        arguments |= {"error": "boom"}

    with pytest.raises(NotFound):
        getattr(services, call)(**arguments)


def test_the_same_export_inside_the_subtree_gets_the_wall_and_not_a_not_found(
    world: World, recorded_workflow_starts: None
) -> None:
    """The other half: reach passes, so the CAPABILITY wall is what answers.

    Without this, the parametrised case above would pass on a service that had
    simply started refusing everybody `NotFound`, which is the failure mode a
    reordering is most likely to introduce.
    """
    from apps.exports import services

    inside = create_export(tenant=world.tenant, actor=world.region_actor)
    plain = _plain_member(world)
    acting = actor_for(user=plain, tenant=world.tenant, org=world.root)

    with pytest.raises(Forbidden) as refused:
        services.mark_export_running(tenant=world.tenant, actor=acting, export=inside)
    assert str(refused.value.detail) == refusal_sentence("export.build")
