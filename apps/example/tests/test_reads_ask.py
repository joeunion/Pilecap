"""Reads are permissions, in `example`: every selector asks, and both doors agree.

The app's half of ADR core-27. `test_authz_sweep.py` beside this file drives the
WRITE algebra (what a role holds); this drives the READ SEAM — that each public
selector actually asks, that the answer a refused caller gets is the same on
every door, and that the flat product still reads everything it read.

**The grammar under test, in one line** (§C8, reach before capability): a row
outside the hat's subtree is `not_found`, a row inside it without `<kind>.read`
is `forbidden`, and a list without the key is `forbidden` because a list has no
row to hide. The ORDER is asserted by the two exception types rather than
described — a `get_` that asked the capability before the scoped fetch would
answer `forbidden` where this expects `not_found`.

**The population is derived, not listed.** `test_every_door_selector_asks_or_says_why`
reads this app's `selectors.py` with `inspect`, keeps every public `get_`/`list_`
whose return annotation resolves to a model with an authorization kind, and
requires each one to take `actor` or to carry the `# read-open:` valve with its
reason. A hand-written list of five names would go stale the first time a
selector is added, which is the failure the rule 54 (d) census exists to prevent
and which a test may not reintroduce.

Raw `Grant` rows, because the services that hand permissions out are P4's and
the criteria say a raw create is legal until they land.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

import pytest
from django.db import models
from django.test import Client
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.authz import kind_of, refusal_sentence, require
from apps.core.exceptions import Forbidden, NotFound
from apps.core.mcp import SCOPE_KEY, Principal
from apps.core.models import Grant, Membership, Organization, Tenant
from apps.core.services import add_membership, create_organization, root_organization
from apps.example import selectors as example_selectors
from apps.example.api import widget_stats
from apps.example.mcp import register
from apps.example.models import Widget, WidgetEntry, WidgetPolicy
from apps.example.selectors import (
    get_governing_widget_policy,
    get_widget,
    list_widget_entries,
    list_widget_policies,
    list_widgets,
)
from apps.example.services import create_widget, create_widget_policy, record_widget_entry

pytestmark = pytest.mark.django_db

JSON = "application/json"
PASSWORD = "reads-ask-pass-1234"  # pragma: allowlist secret
LIST_URL = "/api/v1/widgets/"

#: The valve rule 54 (d) reads for a selector nobody's door calls. Spelled here
#: so the derivation below looks for the same string the gate looks for.
READ_OPEN = "# read-open:"


# --- the world ----------------------------------------------------------------


@dataclass(frozen=True)
class Reads:
    """`root -> a -> a1` and a sibling `b`, with one of each row in each branch.

    The reader is a `member` at **A**, so their hat covers `a` and `a1` and never
    `b`. Every case below is one of three cells: a row in `b` (outside), a row in
    `a1` (inside), and the list at the hat.
    """

    tenant: Tenant
    root: Organization
    a: Organization
    a1: Organization
    b: Organization
    reader: User
    reader_membership: Membership
    inside_widget: Widget
    outside_widget: Widget
    inside_policy: WidgetPolicy
    inside_entry: WidgetEntry

    def actor(self) -> Actor:
        """A fresh actor at A — fresh because the memo's TTL is the instance."""
        return actor_for(user=self.reader, tenant=self.tenant, org=self.a)


@pytest.fixture
def reads(tenant: Tenant, owner: User) -> Reads:
    root = root_organization(tenant=tenant)
    system = system_actor(tenant=tenant)
    a = create_organization(tenant=tenant, parent=root, name="A", slug="a", actor=system)
    a1 = create_organization(tenant=tenant, parent=a, name="A1", slug="a1", actor=system)
    b = create_organization(tenant=tenant, parent=root, name="B", slug="b", actor=system)

    reader = create_user(email="reader@example.com", password=PASSWORD)
    reader_membership = add_membership(
        user=reader,
        tenant=tenant,
        organization=a,
        role=Membership.Role.MEMBER,
        is_default=True,
        actor=system,
    )
    resident = create_user(email="resident@example.com", password=PASSWORD)
    add_membership(
        user=resident, tenant=tenant, organization=a1, role=Membership.Role.MEMBER, actor=system
    )
    neighbour = create_user(email="neighbour@example.com", password=PASSWORD)
    add_membership(
        user=neighbour, tenant=tenant, organization=b, role=Membership.Role.MEMBER, actor=system
    )

    inside_actor = actor_for(user=resident, tenant=tenant, org=a1)
    outside_actor = actor_for(user=neighbour, tenant=tenant, org=b)
    inside_widget = create_widget(tenant=tenant, actor=inside_actor, name="Inside")
    outside_widget = create_widget(tenant=tenant, actor=outside_actor, name="Outside")
    inside_policy = create_widget_policy(
        tenant=tenant, actor=system_actor(tenant, a1), name="Inside policy", body="{}"
    )
    inside_entry = record_widget_entry(
        tenant=tenant, actor=inside_actor, widget=inside_widget, kind="note", note="inside"
    )
    return Reads(
        tenant=tenant,
        root=root,
        a=a,
        a1=a1,
        b=b,
        reader=reader,
        reader_membership=reader_membership,
        inside_widget=inside_widget,
        outside_widget=outside_widget,
        inside_policy=inside_policy,
        inside_entry=inside_entry,
    )


def withhold(membership: Membership, permission: str) -> Grant:
    """A raw `withhold` row. Legal until P4 lands the hand-out services."""
    return Grant.objects.create(
        tenant=membership.tenant,
        membership=membership,
        permission=permission,
        effect=Grant.Effect.WITHHOLD,
    )


# --- PR4.a.1 · the population, derived from the module ------------------------


def _returned_model(function: Callable[..., Any]) -> type[models.Model] | None:
    """The model a selector's RETURN ANNOTATION names, or `None`.

    The same derivation rule 54 (d)/(e) uses, and read the same way it reads it:
    off the ANNOTATION TEXT. `typing.get_type_hints` cannot be used here and the
    reason is worth writing down — Django's `QuerySet.__class_getitem__` returns
    the class itself, so `ScopedQuerySet[Widget]` EVALUATES to `ScopedQuerySet`
    and the model is erased. A resolver that trusted it would have found two of
    this app's five selectors and reported the other three as outside the
    population, which is a census going quietly blind.

    A bare model, or the first name inside a generic over one. Anything else —
    a dataclass, a `list[UUID]`, an unannotated return — is outside the
    population by annotation, which is the trade an annotation-reading rule
    makes and which the rule declares.
    """
    raw = function.__annotations__.get("return")
    if not isinstance(raw, str):
        return None
    names = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", raw)
    namespace = vars(inspect.getmodule(function) or example_selectors)
    for name in names:
        candidate = namespace.get(name)
        if isinstance(candidate, type) and issubclass(candidate, models.Model):
            return candidate
    return None


def door_selectors() -> dict[str, Callable[..., Any]]:
    """Every public `get_`/`list_` in this app's `selectors.py` over a kind."""
    found: dict[str, Callable[..., Any]] = {}
    for name, function in vars(example_selectors).items():
        if name.startswith("_") or not (name.startswith(("get_", "list_"))):
            continue
        if not inspect.isfunction(function):
            continue
        if function.__module__ != example_selectors.__name__:
            continue
        model = _returned_model(function)
        if model is None or kind_of(model) is None:
            continue
        found[name] = function
    return found


def test_every_door_selector_asks_or_says_why() -> None:
    """Each one takes `actor`, or carries the valve with its reason (rule 54 (d)).

    **The instrument answers something when the thing is absent**: the population
    is derived and asserted non-empty first, so a derivation that stopped finding
    selectors — a renamed module, a changed annotation style — reds here instead
    of passing over an empty set. Five is what this app publishes today, and the
    names are asserted, so an added read has to arrive with its `actor`.
    """
    selectors = door_selectors()
    assert sorted(selectors) == [
        "get_governing_widget_policy",
        "get_widget",
        "list_widget_entries",
        "list_widget_policies",
        "list_widgets",
    ], sorted(selectors)

    for name, function in sorted(selectors.items()):
        signature = inspect.signature(function)
        source = inspect.getsource(function)
        assert "actor" in signature.parameters or READ_OPEN in source, name
        if "actor" in signature.parameters:
            parameter = signature.parameters["actor"]
            assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, name
            assert parameter.default is inspect.Parameter.empty, (
                f"{name}: `actor` has a default, so a caller that forgets it reads "
                "for free — which is the hole the keyword exists to close"
            )


# --- PR4.a.1/.2 · the grammar, at the selector --------------------------------


def _list(kind: str) -> Callable[..., Any]:
    return {
        "widget": list_widgets,
        "widget_policy": list_widget_policies,
        "widget_entry": list_widget_entries,
    }[kind]


@pytest.mark.parametrize("kind", ["widget", "widget_policy", "widget_entry"])
def test_a_list_without_the_key_is_forbidden_and_says_the_keys_own_sentence(
    reads: Reads, kind: str
) -> None:
    """A list has no row to hide, so the only honest answers are the page and 403.

    Then the withhold is lifted and the same call answers, which is what stops
    this from being a test that would pass with the selectors refusing everybody.
    """
    key = f"{kind}.read"
    withhold(reads.reader_membership, key)

    with pytest.raises(Forbidden) as refused:
        _list(kind)(tenant=reads.tenant, org=reads.a, actor=reads.actor())
    assert str(refused.value.args[0]) == refusal_sentence(key)

    Grant.objects.filter(membership=reads.reader_membership, permission=key).delete()
    assert _list(kind)(tenant=reads.tenant, org=reads.a, actor=reads.actor()) is not None


def test_a_widget_outside_the_subtree_is_not_found_and_inside_without_the_key_is_forbidden(
    reads: Reads,
) -> None:
    """Reach before capability, asserted by the two exception TYPES (§C8).

    *Outside* is `not_found` and always was — the scoped fetch answers before a
    capability is ever consulted, so a caller cannot map a branch they hold
    nothing on by reading which ids refuse differently. *Inside without the key*
    is `forbidden`, which is what every capability has answered on every door
    since day one and what makes the read gate visible rather than inconclusive.
    """
    withhold(reads.reader_membership, "widget.read")

    with pytest.raises(NotFound):
        get_widget(
            tenant=reads.tenant,
            widget_id=reads.outside_widget.pk,
            org=reads.a,
            actor=reads.actor(),
        )

    with pytest.raises(Forbidden) as refused:
        get_widget(
            tenant=reads.tenant,
            widget_id=reads.inside_widget.pk,
            org=reads.a,
            actor=reads.actor(),
        )
    assert str(refused.value.args[0]) == refusal_sentence("widget.read")

    Grant.objects.filter(membership=reads.reader_membership, permission="widget.read").delete()
    assert (
        get_widget(
            tenant=reads.tenant,
            widget_id=reads.inside_widget.pk,
            org=reads.a,
            actor=reads.actor(),
        ).pk
        == reads.inside_widget.pk
    )
    with pytest.raises(NotFound):
        get_widget(
            tenant=reads.tenant,
            widget_id=reads.outside_widget.pk,
            org=reads.a,
            actor=reads.actor(),
        )


def test_the_governing_policy_asks_at_the_hat_and_not_at_the_ancestor(reads: Reads) -> None:
    """The one `get_` in this app that asks with `obj=None`, and why it must.

    `get_governing_widget_policy` resolves UPWARD: the row it returns lives on an
    ancestor node, where the caller holds nothing at all (ADR core-3, §A5c —
    config resolves upward, visibility never does). Asking `widget_policy.read`
    at the ROW would therefore refuse exactly the population the function exists
    to serve, so it asks at the acting hat instead.

    Driven here as the pair it is: a reader at A1 resolves a policy set at A1's
    own node and one set ABOVE it at A, and the `withhold` at the hat is what
    turns both into `forbidden` — not the node the row happens to live on.
    """
    system = system_actor(reads.tenant, reads.a)
    above = create_widget_policy(tenant=reads.tenant, actor=system, name="At A", body="{}")

    at_a1 = actor_for(user=reads.reader, tenant=reads.tenant, org=reads.a1)
    resolved = get_governing_widget_policy(tenant=reads.tenant, org=reads.a1, actor=at_a1)
    assert resolved.pk == reads.inside_policy.pk

    # The row an ANCESTOR owns, resolved by the same call from a node that owns
    # nothing: the ask cannot have been at the row, or this could not answer.
    at_b = actor_for(user=reads.reader, tenant=reads.tenant, org=reads.a)
    assert get_governing_widget_policy(tenant=reads.tenant, org=reads.a, actor=at_b).pk == above.pk

    withhold(reads.reader_membership, "widget_policy.read")
    with pytest.raises(Forbidden) as refused:
        get_governing_widget_policy(
            tenant=reads.tenant,
            org=reads.a1,
            actor=actor_for(user=reads.reader, tenant=reads.tenant, org=reads.a1),
        )
    assert str(refused.value.args[0]) == refusal_sentence("widget_policy.read")


def test_the_system_actor_reads_everything_the_scope_shows(reads: Reads) -> None:
    """`system` passes at step 1, so the onboarding activities are untouched.

    Asserted with a withhold on the reader in place, so the pass is the actor
    KIND and not an accident of there being nothing to refuse.
    """
    for kind in ("widget", "widget_policy", "widget_entry"):
        withhold(reads.reader_membership, f"{kind}.read")
    system = system_actor(reads.tenant, reads.a1)
    assert list_widgets(tenant=reads.tenant, org=reads.a1, actor=system).exists()
    assert list_widget_policies(tenant=reads.tenant, org=reads.a1, actor=system).exists()
    assert list_widget_entries(tenant=reads.tenant, org=reads.a1, actor=system).exists()
    assert (
        get_widget(
            tenant=reads.tenant, widget_id=reads.inside_widget.pk, org=reads.a1, actor=system
        ).pk
        == reads.inside_widget.pk
    )


def test_widget_stats_asks_widget_read(reads: Reads) -> None:
    """The aggregate is covered by the read key of the kind it counts (§0c (1)).

    `/widgets/stats/` returns a `MeasuredOut` and not a row, so it is outside the
    selector census by annotation — and it counts widgets, so a caller who may
    not read widgets must not be able to count them either. It asks through the
    one selector both doors already read through, which is why this is one
    assertion and not a second gate.
    """
    withhold(reads.reader_membership, "widget.read")
    with pytest.raises(Forbidden) as refused:
        widget_stats(tenant=reads.tenant, org=reads.a, actor=reads.actor())
    assert str(refused.value.args[0]) == refusal_sentence("widget.read")


# --- PR4.a.2 · the flat product observes nothing ------------------------------


def test_the_plain_member_still_reads_everything(api: Client, reads: Reads) -> None:
    """Principle 13: a product that customised nothing sees the answers it saw.

    The member holds `("*.read",)` by declaration, so every list route in this
    app answers 200 with no permission row anywhere. This is the half that would
    catch a flip that refused everybody — a seam test whose every case is a
    refusal cannot tell "asks correctly" from "asks and always says no".
    """
    api.force_login(reads.reader)
    for url in (
        LIST_URL,
        f"{LIST_URL}stats/",
        f"{LIST_URL}policies/",
        f"{LIST_URL}entries/",
    ):
        response = api.get(url, headers={"X-Org": reads.a.slug})
        assert response.status_code == 200, (url, response.content)


# --- PR4.a.2 · both doors, the same words -------------------------------------


@dataclass
class _FakeRequest:
    scope: dict[str, Any]


@dataclass
class _FakeRequestContext:
    request: _FakeRequest


def context_for(user: User, tenant: Tenant, org: Organization) -> Context[Any]:
    """The context a tool sees, with the principal the middleware would have left."""
    scope = {SCOPE_KEY: Principal(user=user, tenant=tenant, org=org)}
    return Context(
        request_context=cast(Any, _FakeRequestContext(request=_FakeRequest(scope=scope)))
    )


def tool(name: str) -> Callable[..., Any]:
    server: MCPServer[Any] = MCPServer(name="test", version="1")
    register(server)
    found: Callable[..., Any] = cast(Any, server._tool_manager._tools[name]).fn  # noqa: SLF001
    return found


def test_a_withheld_read_is_forbidden_on_the_rest_door_and_the_twin_says_the_same(
    api: Client, reads: Reads
) -> None:
    """E9: the MCP message IS the REST body, rendered — string-compared.

    The over-the-wire half of this claim, with a real bearer token and the real
    ASGI application, is `test_doors_over_the_wire.py`'s rule-46 case; this is
    the same claim at the door functions, where it can be parametrised cheaply
    over the list and the detail.

    A row in a sibling branch stays 404 on both doors — the §C8 half Phase R does
    not touch — which is asserted here so that "the two doors agree" covers the
    answer they give for a row the caller could never have reached.
    """
    withhold(reads.reader_membership, "widget.read")
    sentence = refusal_sentence("widget.read")
    api.force_login(reads.reader)

    listed = api.get(LIST_URL, headers={"X-Org": reads.a.slug})
    assert listed.status_code == 403, listed.content
    body = listed.json()
    assert body["code"] == "forbidden"
    assert body["detail"] == sentence

    detail = api.get(
        f"{LIST_URL}{reads.inside_widget.pk}/",
        headers={"X-Org": reads.a.slug},
    )
    assert detail.status_code == 403, detail.content
    assert detail.json()["detail"] == sentence

    outside = api.get(
        f"{LIST_URL}{reads.outside_widget.pk}/",
        headers={"X-Org": reads.a.slug},
    )
    assert outside.status_code == 404, outside.content

    ctx = context_for(reads.reader, reads.tenant, reads.a)
    with pytest.raises(ToolError) as refused_list:
        tool("list_widgets")(ctx=ctx)
    assert sentence in str(refused_list.value)

    with pytest.raises(ToolError) as refused_get:
        tool("get_widget")(ctx=ctx, widget_id=reads.inside_widget.pk)
    assert sentence in str(refused_get.value)


# --- PR4.a.3 · a write door pays the read once --------------------------------


def test_a_write_door_pays_the_read_once(
    api: Client, reads: Reads, django_assert_num_queries: Any
) -> None:
    """+3 and not +6: the memo answers the second `require` for free (PR0).

    A write door here fetches through `get_widget` — which asks `widget.read` at
    the row's node — and then calls a service, which asks `widget.update`. So a
    write asks TWICE, and the thing that has to stay true is that resolution
    happens ONCE per actor instance: three statements for the first ask
    (memberships in the tenant, the grants on them, the role deltas for the roles
    on the chain), zero for every one after it.

    Measured at the seam rather than at the whole request on purpose. A pin over
    the PATCH counts the session row, the savepoints, the hat lookup, the audit
    row and the outbox write as well, and a number that large moves for reasons
    that have nothing to do with this claim — it would be a pin nobody could read
    a failure out of. The two blocks below are the claim itself, and the wire
    assertion after them is what says the door they belong to still answers.

    **What differs if this is false**: the second block reds with three more
    statements, which is the `+6 on every write` the memo landed to prevent.
    """
    owner_of_it = actor_for(user=reads.reader, tenant=reads.tenant, org=reads.a)
    mine = create_widget(tenant=reads.tenant, actor=owner_of_it, name="Mine")

    # A FRESH actor: the memo's TTL is the instance, and reusing the one that
    # created the row would measure a cache that a real request never inherits.
    acting = actor_for(user=reads.reader, tenant=reads.tenant, org=reads.a)
    with django_assert_num_queries(READ_SEAM_QUERIES):
        widget = get_widget(tenant=reads.tenant, widget_id=mine.pk, org=reads.a, actor=acting)
    with django_assert_num_queries(0):
        require(acting, "widget.update", widget)

    api.force_login(reads.reader)
    response = api.patch(
        f"{LIST_URL}{mine.pk}/",
        data='{"name": "Renamed"}',
        content_type=JSON,
        headers={"X-Org": reads.a.slug},
    )
    assert response.status_code == 200, response.content
    assert response.json()["name"] == "Renamed"


# The scoped fetch, plus the three statements resolution costs the first time an
# actor instance is asked anything. Measured on this tree, not guessed; the
# three are `memberships_in`, the grants on those memberships, and the role
# deltas for the role keys on the chain (`apps/core/authz.py`).
READ_SEAM_QUERIES = 4
