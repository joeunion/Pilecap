"""PR4.b — a read of this app's rows is a permission (ADR core-27, architect §C6).

Four properties, and the first is the one that survives the next model somebody
adds: the POPULATION is derived, never listed. `inspect` walks this app's public
`get_`/`list_` names, resolves each return annotation to a model, and asks the
registry for its kind — which is the same derivation rule 54 (d) performs, asked
here where a criterion can read the answer.

The other three drive the property over the doors: outside the acting hat's
subtree a read is `not_found` and inside it without the key it is `forbidden`
(the §C8 grammar, reach before capability), both doors say it in the same words,
and **a plain member still reads everything** — the flat-product half, per app.

`transaction=True` is deliberately NOT set: nothing here runs a tool body on a
worker thread. The door-parity case that does lives in
`test_doors_over_the_wire.py`, which owns that harness.
"""

from __future__ import annotations

import ast
import inspect
import json
from typing import Any
from uuid import uuid4

import pytest
from django.db import models
from django.test import Client

from apps.accounts.models import User
from apps.comms import selectors
from apps.comms.models import Channel
from apps.comms.services import register_device, send
from apps.comms.tests.conftest import make_recipient, make_template
from apps.core.actor import Actor, actor_for
from apps.core.authz import kind_of
from apps.core.exceptions import Forbidden, NotFound
from apps.core.models import Grant, Membership, Organization, Tenant
from apps.core.services import create_organization, root_organization

pytestmark = pytest.mark.django_db

JSON = "application/json"

#: The machine reads, and the sentence each one's valve has to carry. Written out
#: here rather than derived from the source so that adding a fourth valve is a
#: line in this list, in the diff, where a reviewer sees it — the population
#: below is derived and this is the declared exception to it.
VALVED = {
    "get_message_by_provider_id": "a provider's signed status webhook",
    "get_device_by_token_hash": "the upsert read behind `register_device`",
    "list_devices": "the push transport's own read",
}

#: The read key each door selector asks for. Also written out, for the same
#: reason and a sharper one: this is the OTHER half of clause (e) — that a read
#: asks for the kind of the row it hands back rather than for a word that means
#: something else — and deriving it from the code under test would be a pin that
#: cannot fail.
DOOR_READS = {
    "list_messages": "message.read",
    "get_message": "message.read",
    "list_engagements": "message_engagement.read",
    "get_device": "device.read",
    "list_recipients": "recipient.read",
    "get_recipient": "recipient.read",
    "list_templates": "message_template.read",
    "get_template": "message_template.read",
    "get_template_by_id": "message_template.read",
    "list_policies": "delivery_policy.read",
    "get_policy": "delivery_policy.read",
    "list_preferences": "channel_preference.read",
    "get_preference": "channel_preference.read",
}


def _public_reads() -> dict[str, str]:
    """Every public `get_`/`list_` in this app's selectors whose rows have a kind.

    **Read by AST, and that is not a stylistic choice.** The obvious form —
    `typing.get_type_hints` on each function — cannot see a list's row type at
    all: Django's `QuerySet.__class_getitem__` returns the class itself, so
    `ScopedQuerySet[Message]` EVALUATES to `ScopedQuerySet` and the parameter is
    gone by the time a hint is resolved. Every one of this app's seven `list_`
    selectors would drop out of the population silently and their missing
    `require`s would go unnoticed, which is the exact shape of blindness this
    case exists to prevent. Rule 54 (d) reads the same annotations the same way
    and for the same reason (its own text says "this half NEVER IMPORTS"), so
    this is the rule's derivation asked where a criterion can read the answer.

    A read annotated with a dataclass or a `list[UUID]` is outside the population
    by annotation, which is the trade the rule makes and this case inherits whole.
    """
    from pathlib import Path

    from django.conf import settings

    import apps.comms.models as comms_models

    source = (Path(settings.BASE_DIR) / "apps/comms/selectors.py").read_text()
    found: dict[str, str] = {}
    for node in ast.parse(source).body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name.startswith("_") or not node.name.startswith(("get_", "list_")):
            continue
        for named in ast.walk(node.returns) if node.returns is not None else []:
            if not isinstance(named, ast.Name):
                continue
            model = getattr(comms_models, named.id, None)
            if isinstance(model, type) and issubclass(model, models.Model) and kind_of(model):
                found[node.name] = ast.get_source_segment(source, node) or ""
                break
    return found


# --- PR4.b.1 · every door read asks, and every machine read says why -------------


def test_every_door_selector_asks_or_says_why() -> None:
    """The population is derived; each member either takes an actor or is valved.

    A read that takes no `actor` and carries no `# read-open:` is a read every
    door inherits for free — which is the whole of what ADR core-27 closes.
    """
    population = _public_reads()
    # The floor names the population and its size rather than "at least one":
    # a derivation that silently stopped resolving annotations would otherwise
    # pass this vacuously.
    assert len(population) == len(DOOR_READS) + len(VALVED), sorted(population)
    assert set(population) == set(DOOR_READS) | set(VALVED), sorted(population)

    for name, source in sorted(population.items()):
        function = getattr(selectors, name)
        takes_actor = "actor" in inspect.signature(function).parameters
        if name in VALVED:
            assert not takes_actor, f"{name} is valved and should not take an actor"
            assert "# read-open:" in source, f"{name} is valved with no sentence"
            assert VALVED[name] in source, f"{name}'s valve does not say what it says"
            continue
        assert takes_actor, f"{name} asks nobody"
        assert inspect.signature(function).parameters["actor"].default is inspect.Parameter.empty, (
            f"{name}'s actor has a default — a read that fails open the first time "
            "a caller forgets is the defect this sweep closed"
        )
        assert f'require(actor, "{DOOR_READS[name]}"' in source, (
            f"{name} must ask for {DOOR_READS[name]}"
        )


def test_the_valved_list_has_no_door_behind_it() -> None:
    """`list_devices`' valve claims no route or tool reaches it. This is that claim.

    The other two valves are pre-auth by construction — a webhook's lookup and an
    upsert's read — but `list_devices` is valved because its only caller is the
    push transport acting as the system, and that is a fact about the tree which
    stops being true the day somebody puts a route in front of it.
    """
    from pathlib import Path

    from django.conf import settings

    for module in ("apps/comms/api.py", "apps/comms/mcp.py"):
        tree = ast.parse((Path(settings.BASE_DIR) / module).read_text())
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        # The prose in `mcp.py` NAMES `list_devices` while explaining why there
        # is no tool for it, so the claim is about calls and not about the text.
        assert "list_devices" not in called, module


# --- the world these properties are driven in -----------------------------------


class ReadsWorld:
    """`root → A` and a sibling `B`, one member hatted at A, one row per kind."""

    def __init__(self, tenant: Tenant, owner_actor: Actor) -> None:
        self.tenant = tenant
        root = root_organization(tenant=tenant)
        self.a = create_organization(
            tenant=tenant, parent=root, name="A", slug="reads-a", actor=owner_actor
        )
        self.b = create_organization(
            tenant=tenant, parent=root, name="B", slug="reads-b", actor=owner_actor
        )
        self.owner_at_a = actor_for(user=owner_actor.user, tenant=tenant, org=self.a)
        self.owner_at_b = actor_for(user=owner_actor.user, tenant=tenant, org=self.b)

        self.template = make_template(actor=owner_actor, name="reads-receipt")
        self.inside = make_recipient(actor=self.owner_at_a, email="inside@example.com")
        self.outside = make_recipient(actor=self.owner_at_b, email="outside@example.com")
        self.device_inside = register_device(
            tenant=tenant,
            actor=self.owner_at_a,
            recipient=self.inside,
            platform="ios",
            push_token="reads-token-inside",
        )
        self.device_outside = register_device(
            tenant=tenant,
            actor=self.owner_at_b,
            recipient=self.outside,
            platform="ios",
            push_token="reads-token-outside",
        )
        self.message_inside = send(
            recipient=self.inside,
            context={"name": "Inside"},
            tenant=tenant,
            actor=self.owner_at_a,
            template="reads-receipt",
        )
        self.message_outside = send(
            recipient=self.outside,
            context={"name": "Outside"},
            tenant=tenant,
            actor=self.owner_at_b,
            template="reads-receipt",
        )


@pytest.fixture
def world(tenant: Tenant, owner_actor: Actor, recorded_workflow_starts: None) -> ReadsWorld:
    return ReadsWorld(tenant, owner_actor)


def _member_at(world: ReadsWorld, person: User, org: Organization) -> Actor:
    """The template's plain member, acting as one branch of the tenant.

    **No second membership.** The `member` fixture already holds one at the root,
    which covers every node below it, so adding another at `A` would make this
    person two memberships — and a `withhold` written against one of them would
    leave the other still holding the key, which is the shape that makes a
    permission test pass for the wrong reason.
    """
    return actor_for(user=person, tenant=world.tenant, org=org)


def _withhold(tenant: Tenant, actor: Actor, person: User, permission: str) -> None:
    """One `withhold` grant on this person's membership, then forget the memo.

    The memo rides on the `Actor` (PR0) and is the actor's own rows, so a grant
    written after a read in the same test would otherwise be invisible to it —
    which would make this case pass for the wrong reason on the day the withhold
    stopped working.

    `tenant` and `person` are passed rather than read off the actor because
    `Actor.user` is an `AbstractBaseUser | None` and `Actor.tenant` a
    `Tenant | None`: narrowing them here would be two asserts about a fixture
    that cannot be otherwise.
    """
    Grant.objects.create(
        tenant=tenant,
        membership=Membership.objects.get(user=person, tenant=tenant),
        permission=permission,
        effect=Grant.Effect.WITHHOLD,
    )
    actor.forget_permissions()


# --- PR4.b.1 · not_found outside, forbidden inside -------------------------------


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("get_message", "message.read"),
        ("get_recipient", "recipient.read"),
        ("get_device", "device.read"),
    ],
)
def test_a_read_outside_the_subtree_is_not_found_and_inside_without_the_key_is_forbidden(
    world: ReadsWorld, member: User, name: str, key: str
) -> None:
    """Reach before capability (§C8): the fetch answers first, always.

    Parametrised over the ORG-SCOPED `get_`s, which are the only ones with an
    outside at all — a `MessageTemplate` and a `DeliveryPolicy` are the tenant's
    house style and name no branch, so their reads have a `forbidden` case and
    no `not_found` one, and saying that here is cheaper than a parametrisation
    that pretends otherwise.
    """
    acting = _member_at(world, member, world.a)
    rows = {
        "get_message": (world.message_inside, world.message_outside, "message_id"),
        "get_recipient": (world.inside, world.outside, "recipient_id"),
        "get_device": (world.device_inside, world.device_outside, "device_id"),
    }
    inside, outside, argument = rows[name]
    read = getattr(selectors, name)

    # Inside the subtree, holding the key: the ordinary answer.
    assert (
        read(tenant=world.tenant, org=world.a, actor=acting, **{argument: inside.pk}).pk
        == inside.pk
    )

    # Outside it, holding the key: `not_found`, because the scoped fetch missed.
    with pytest.raises(NotFound):
        read(tenant=world.tenant, org=world.a, actor=acting, **{argument: outside.pk})

    # Inside it, WITHOUT the key: `forbidden`. The difference between these two
    # refusals is the whole grammar — a 403 on the row in B would have told this
    # member that somebody else's row exists.
    _withhold(world.tenant, acting, member, key)
    with pytest.raises(Forbidden):
        read(tenant=world.tenant, org=world.a, actor=acting, **{argument: inside.pk})
    # And the one outside is STILL `not_found`: reach is answered first.
    with pytest.raises(NotFound):
        read(tenant=world.tenant, org=world.a, actor=acting, **{argument: outside.pk})


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("list_messages", "message.read"),
        ("list_recipients", "recipient.read"),
        ("list_templates", "message_template.read"),
        ("list_policies", "delivery_policy.read"),
    ],
)
def test_a_list_without_the_key_is_forbidden_rather_than_empty(
    world: ReadsWorld, member: User, name: str, key: str
) -> None:
    """A list has no row to hide, so an empty page would be a lie about the tenant.

    *Absent:* before the read sweep every one of these returned a page to anybody
    with a membership — `grep -c 'require(actor' apps/comms/selectors.py` was 0.
    """
    acting = _member_at(world, member, world.a)
    listed = getattr(selectors, name)
    arguments: dict[str, Any] = {"tenant": world.tenant, "actor": acting}
    if name in {"list_messages", "list_recipients"}:
        arguments["org"] = world.a

    assert listed(**arguments).count() >= 0  # the page, before the withhold

    _withhold(world.tenant, acting, member, key)
    with pytest.raises(Forbidden):
        listed(**arguments).count()


def test_a_missing_consent_row_is_still_a_read_somebody_has_to_hold(
    world: ReadsWorld, member: User
) -> None:
    """`get_preference` answers `None` for "consented to nothing", and that is DATA.

    A row that is not there has no node of its own, so the question is asked at
    the acting hat. Asking only when a row turned up would have made "this person
    has agreed to nothing" the one consent answer a withheld reader could still
    get — which is the half of the table that matters most.
    """
    acting = _member_at(world, member, world.a)
    assert (
        selectors.get_preference(
            tenant=world.tenant,
            recipient=world.inside,
            channel=Channel.SMS,
            org=world.a,
            actor=acting,
        )
        is None
    )

    _withhold(world.tenant, acting, member, "channel_preference.read")
    with pytest.raises(Forbidden):
        selectors.get_preference(
            tenant=world.tenant,
            recipient=world.inside,
            channel=Channel.SMS,
            org=world.a,
            actor=acting,
        )


# --- PR4.b.2 · the flat product observes nothing ---------------------------------

LIST_ROUTES = (
    "/api/v1/messages/",
    "/api/v1/recipients/",
    "/api/v1/templates/",
    "/api/v1/delivery-policies/",
)


def test_the_plain_member_still_reads_everything(
    api: Client, tenant: Tenant, member: User, root_org: Organization
) -> None:
    """Principle 13, per app: a product that customised nothing sees no change.

    `member` is declared `("*.read",)`, so every derived `<kind>.read` the read
    sweep started asking for is one the template's own role already holds. The four
    list doors answer 200 for a plain member exactly as they did before.

    *Absent:* a 403 on any of these is the regression this case exists for.
    """
    api.force_login(member)
    for route in LIST_ROUTES:
        response = api.get(route, headers={"X-Tenant": tenant.slug, "X-Org": root_org.slug})
        assert response.status_code == 200, (route, response.status_code, response.content)


def test_a_withheld_member_is_refused_over_the_wire_with_the_sentence(
    api: Client, tenant: Tenant, member: User, root_org: Organization
) -> None:
    """And the refusal a person reads is prose, never the action name (E9).

    The REST half of rule 46's parity case; the MCP twin of this exact refusal is
    `test_doors_over_the_wire.py`'s, driven over a real transport.
    """
    membership = Membership.objects.get(user=member, tenant=tenant)
    Grant.objects.create(
        tenant=tenant,
        membership=membership,
        permission="message.read",
        effect=Grant.Effect.WITHHOLD,
    )
    api.force_login(member)

    response = api.get(
        "/api/v1/messages/", headers={"X-Tenant": tenant.slug, "X-Org": root_org.slug}
    )

    assert response.status_code == 403, response.content
    body = json.loads(response.content)
    assert body["code"] == "forbidden", body
    assert "message.read" not in json.dumps(body), body
    assert body["detail"] == "You may not read this message.", body


def test_a_read_of_a_kind_this_app_does_not_own_is_not_what_it_asks(
    world: ReadsWorld, member: User
) -> None:
    """Clause (e): a read asks for ITS OWN kind, not for a word that means another.

    Withholding `message.read` must not close the recipient book, and withholding
    `recipient.read` must not close the message log. The two are separate keys
    precisely so a product can hand out one and not the other, and a selector
    that reached for the nearest key would collapse that.
    """
    acting = _member_at(world, member, world.a)
    _withhold(world.tenant, acting, member, "message.read")

    assert selectors.list_recipients(tenant=world.tenant, org=world.a, actor=acting).count() >= 1
    with pytest.raises(Forbidden):
        selectors.list_messages(tenant=world.tenant, org=world.a, actor=acting).count()


def test_the_machine_reads_still_answer_with_no_actor_at_all(world: ReadsWorld) -> None:
    """The three valves, driven rather than asserted about.

    Each takes no `actor` keyword, which is what makes them valves — and a test
    that only read the signature would not notice the day one of them started
    raising because a caller underneath it began to ask.
    """
    assert (
        selectors.get_device_by_token_hash(
            tenant=world.tenant, push_token_hash="nothing-like-this", org=world.a
        )
        is None
    )
    assert list(selectors.list_devices(tenant=world.tenant, org=world.a)) == [world.device_inside]
    with pytest.raises(NotFound):
        selectors.get_message_by_provider_id(
            tenant=world.tenant, provider_message_id=str(uuid4()), org=world.a
        )
