"""Surfaces: the declaration, the resolver, the door gate, the boot question, the URL seam.

A surface is a host and what it exposes (`apps.core.surfaces`). The world these
tests build is the smallest product with two faces: the implicit total `staff`
surface at `localhost`, and a scratch `customer` surface at
`customer.localhost` exposing the `widgets` family alone, offering the `read`
act alone, admitting the `customer` role alone, and choosing the tenant by the
person's one membership. The scratch declaration is planted in the union the
discovery walk would have produced (`surfaces.union`) and the `customer` role
beside the declared ones through `authz`'s own walk — never a file in the tree.

The undeclared tree is proved too, because it is the promise every product
that declares nothing relies on: one total staff surface, byte-identical links.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from django.apps import apps as django_apps
from django.conf import settings
from django.core import mail as django_mail
from django.core.exceptions import ImproperlyConfigured
from django.test import Client, RequestFactory
from django.urls import reverse

from apps.accounts.models import User
from apps.core import authz, bridge, mail, surfaces
from apps.core.actor import actor_for, system_actor
from apps.core.models import Organization, Tenant
from apps.core.services import INVITE_LANDING_URL, add_membership, invite_member
from apps.core.surfaces import (
    ALL,
    IMPLICIT_STAFF,
    STAFF,
    Surface,
    absolute_url,
    request_host,
    resolve_surface,
    surface_for_role,
    union,
)
from apps.core.tests.settings_env import PRODUCTION_ENVIRONMENT, _settings_module
from apps.core.tests.unclaimed import unclaimed_surface
from apps.core.verbs import allowed_acts
from apps.core.verbs import declared as discover
from apps.example.services import create_widget
from config.settings.discovery import discover_apps, switched_off
from quality.partition import platform_apps

pytestmark = pytest.mark.django_db

STAFF_HOST = "localhost"
CUSTOMER_HOST = "customer.localhost"
HOSTS = {STAFF: STAFF_HOST, "customer": CUSTOMER_HOST}
CUSTOMER = Surface(
    families={"widgets"},
    acts={"read"},
    roles={"customer"},
    tenant_rule="membership",
    screens=set(),
)
NOT_EXPOSED = "surface_does_not_expose"
#: The worked customer surface: the one app that declares the `customer` role.
PORTAL_APP = "apps.example_portal"


def _declarer(label: str) -> SimpleNamespace:
    return SimpleNamespace(label=label)


@pytest.fixture
def customer_role(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The `customer` role — the REAL declaration, `apps/example_portal/roles.py`, and no other.

    Where the portal is installed its role is already discovered and nothing is
    planted. Where it is switched off (a world without the worked example) the
    same declaration is planted through `authz`'s walk under the portal's own
    name — one source for the role in both worlds, never a scratch copy.
    """
    if django_apps.is_installed(PORTAL_APP):
        authz.reset_policies()
        yield
        authz.reset_policies()
        return
    real = authz._declarations
    declared = import_module(f"{PORTAL_APP}.roles").ROLES

    def with_a_customer(module: str, attribute: str) -> Any:
        found: list[Any] = list(real(module, attribute))
        if module == "roles":
            portal = SimpleNamespace(name=PORTAL_APP, label=PORTAL_APP.rpartition(".")[2])
            found.append((portal, {"customer": declared["customer"]}))
        return found

    authz.reset_policies()
    monkeypatch.setattr(authz, "_declarations", with_a_customer)
    yield
    authz.reset_policies()


@pytest.fixture
def two_faces(settings: Any, monkeypatch: pytest.MonkeyPatch, customer_role: None) -> Surface:
    """The customer surface declared and both hosts bound. Answers the customer surface."""
    declared = union([(_declarer("zzz_probe_portal"), {"customer": CUSTOMER})])
    monkeypatch.setattr(surfaces, "_declared", declared)
    settings.SURFACE_HOSTS = dict(HOSTS)
    settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, CUSTOMER_HOST, "nowhere.localhost"]
    return declared["customer"]


@pytest.fixture
def customer(tenant: Tenant, owner: User, root_org: Organization, customer_role: None) -> User:
    """A customer's person: one membership, role `customer`, at the tenant's root."""
    person = User.objects.create_user(email="customer@example.com")
    add_membership(
        user=person,
        tenant=tenant,
        organization=root_org,
        role="customer",
        is_default=True,
        actor=actor_for(user=owner, tenant=tenant, org=root_org),
    )
    return person


def _as(user: User | None) -> Client:
    client = Client()
    if user is not None:
        client.force_login(user)
    return client


# --- the declaration is a closed question -------------------------------------


def test_an_undeclared_tree_is_one_total_staff_surface() -> None:
    """The real walk over this tree with the worked example switched off: staff is all there is.

    The template declares one surface — the worked customer face, which depends
    on the example — so the undeclared product is this tree under
    `DJB_DISABLED_APPS=example`: the apps that switches off
    (`discovery.switched_off`, the example and what depends on it) are left out
    of the walk, and nothing else declares a surface.
    """
    platform = set(platform_apps())
    everything = [
        (config, found)
        for config, found in discover(surfaces.DECLARATION_MODULE, surfaces.DECLARATION_ATTRIBUTE)
        if config.label in platform
    ]
    off = switched_off(discover_apps(Path(settings.BASE_DIR) / "apps"), ["example"])
    assert {config.label for config, _ in everything} <= off
    assert dict(
        union([(config, found) for config, found in everything if config.label not in off])
    ) == {STAFF: IMPLICIT_STAFF}
    assert IMPLICIT_STAFF.families is ALL and IMPLICIT_STAFF.acts is ALL
    assert IMPLICIT_STAFF.roles is ALL and IMPLICIT_STAFF.screens is ALL
    assert IMPLICIT_STAFF.tenant_rule == "addressed"


def test_two_apps_declaring_one_key_are_refused_naming_both() -> None:
    with pytest.raises(ImproperlyConfigured) as refused:
        union(
            [
                (_declarer("portal_a"), {"customer": CUSTOMER}),
                (_declarer("portal_b"), {"customer": CUSTOMER}),
            ]
        )
    assert "apps/portal_a/" in str(refused.value)
    assert "apps/portal_b/" in str(refused.value)


def test_two_surfaces_naming_one_role_are_refused_naming_both() -> None:
    partner = Surface(
        families={"widgets"}, acts=ALL, roles={"customer"}, tenant_rule="host", screens=ALL
    )
    with pytest.raises(ImproperlyConfigured) as refused:
        union([(_declarer("portal"), {"customer": CUSTOMER, "partner": partner})])
    assert "'customer'" in str(refused.value) and "'partner'" in str(refused.value)


def test_a_declaration_names_sets_and_one_of_three_tenant_rules() -> None:
    with pytest.raises(ValueError, match="tenant_rule"):
        Surface(families=ALL, acts=ALL, roles=ALL, tenant_rule="header", screens=ALL)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="families"):
        Surface(families="widgets", acts=ALL, roles=ALL, tenant_rule="host", screens=ALL)  # type: ignore[arg-type]


def test_a_product_that_declares_staff_narrows_it_and_nothing_is_added() -> None:
    narrow = Surface(
        families={"widgets"}, acts=ALL, roles={"admin"}, tenant_rule="addressed", screens=ALL
    )
    declared = union([(_declarer("portal"), {STAFF: narrow})])
    assert set(declared) == {STAFF}
    assert declared[STAFF].families == frozenset({"widgets"})
    assert declared[STAFF].key == STAFF


# --- the resolver is one road, and it fails closed ----------------------------


def test_with_no_hosts_bound_every_host_is_staff(settings: Any) -> None:
    settings.SURFACE_HOSTS = {}
    assert resolve_surface("anything.example.com:8443") == IMPLICIT_STAFF


def test_an_exact_host_is_its_surface(two_faces: Surface) -> None:
    assert resolve_surface("customer.localhost:8000") == two_faces
    assert resolve_surface("LOCALHOST").key == STAFF  # type: ignore[union-attr]


def test_a_tenant_pattern_host_is_its_surface_and_names_the_tenant(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    by_host = Surface(
        families={"widgets"}, acts=ALL, roles={"customer"}, tenant_rule="host", screens=ALL
    )
    declared = union([(_declarer("portal"), {"customer": by_host})])
    monkeypatch.setattr(surfaces, "_declared", declared)
    settings.SURFACE_HOSTS = {STAFF: STAFF_HOST, "customer": "{tenant}.customer.localhost"}

    resolved = resolve_surface("acme.customer.localhost")
    assert resolved == declared["customer"]
    assert surfaces.tenant_from_host("acme.customer.localhost", declared["customer"]) == "acme"
    assert resolve_surface("customer.localhost") is None


def test_an_unbound_host_resolves_nowhere(two_faces: Surface) -> None:
    assert resolve_surface("nowhere.localhost") is None


# --- the host, read the way every door reads it --------------------------------


@pytest.mark.parametrize("forwarded", [False, True])
@pytest.mark.parametrize(
    "sent",
    [
        {"Host": "customer.localhost:3500"},
        {"Host": "127.0.0.1:8000", "X-Forwarded-Host": "customer.localhost:3500"},
        {"Host": "localhost", "X-Forwarded-Host": "customer.localhost"},
    ],
)
def test_the_socket_and_machine_doors_read_the_host_the_http_door_reads(
    settings: Any, forwarded: bool, sent: dict[str, str]
) -> None:
    """`request_host` over a scope's headers answers what `get_host()` answers for it."""
    settings.USE_X_FORWARDED_HOST = forwarded
    settings.ALLOWED_HOSTS = ["*"]
    http = RequestFactory().get("/", headers=sent).get_host()
    asgi = request_host([(name.lower().encode(), value.encode()) for name, value in sent.items()])
    assert asgi == http


def test_a_forwarded_host_is_ignored_unless_a_proxy_of_ours_sets_it(settings: Any) -> None:
    forged = [(b"host", b"localhost"), (b"x-forwarded-host", b"customer.localhost")]
    settings.USE_X_FORWARDED_HOST = False
    assert request_host(forged) == "localhost"
    settings.USE_X_FORWARDED_HOST = True
    assert request_host(forged) == "customer.localhost"
    assert request_host([(b"host", b"localhost")]) == "localhost"
    assert request_host([]) == ""


def test_the_port_is_stripped_where_the_host_is_matched(two_faces: Surface) -> None:
    """The face's proxy forwards `customer.localhost:3500`; the match strips the port once."""
    assert resolve_surface("customer.localhost:3500") == two_faces


@pytest.mark.parametrize("forwarded", [False, True])
def test_the_http_door_honours_a_forwarded_host_only_with_the_setting(
    two_faces: Surface, settings: Any, forwarded: bool
) -> None:
    settings.USE_X_FORWARDED_HOST = forwarded
    body = (
        _as(None)
        .get(
            "/api/v1/surface/", HTTP_HOST=STAFF_HOST, HTTP_X_FORWARDED_HOST=f"{CUSTOMER_HOST}:3500"
        )
        .json()
    )
    assert body["surface"] == ("customer" if forwarded else STAFF)


def test_the_forwarded_host_is_trusted_on_the_laptop_stack_alone() -> None:
    """On under `local`, where the face's rewrite is the one proxy; off in `base`, `production`."""
    with _settings_module("config.settings.base") as base:
        assert getattr(base, "USE_X_FORWARDED_HOST", False) is False
    with _settings_module("config.settings.production", **PRODUCTION_ENVIRONMENT) as production:
        assert getattr(production, "USE_X_FORWARDED_HOST", False) is False
    with _settings_module("config.settings.local") as local:
        assert local.USE_X_FORWARDED_HOST is True


def test_a_bound_key_nobody_declared_is_refused(settings: Any) -> None:
    partner = unclaimed_surface("partner")
    settings.SURFACE_HOSTS = {STAFF: STAFF_HOST, partner: "partner.localhost"}
    with pytest.raises(ImproperlyConfigured, match=f"'{partner}'"):
        resolve_surface(STAFF_HOST)


def test_an_unbound_host_is_refused_at_the_door(two_faces: Surface, owner: User) -> None:
    response = _as(owner).get("/api/v1/widgets/", HTTP_HOST="nowhere.localhost")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "surface_unknown_host"
    assert body["remedies"]
    assert "customer" not in response.content.decode()


# --- the door gate: a family this surface does not expose is not there --------


def test_a_customer_is_refused_a_family_the_surface_does_not_expose(
    two_faces: Surface, tenant: Tenant, owner: User, root_org: Organization, customer: User
) -> None:
    widget = create_widget(
        tenant=tenant, actor=actor_for(user=owner, tenant=tenant, org=root_org), name="W"
    )
    url = f"/api/v1/djb_notes/?subject=widget:{widget.pk}"

    refused = _as(customer).get(url, HTTP_HOST=CUSTOMER_HOST)
    exposed = _as(customer).get("/api/v1/widgets/", HTTP_HOST=CUSTOMER_HOST)
    staff = _as(owner).get(url, HTTP_HOST=STAFF_HOST)

    assert refused.status_code == 404, refused.content
    body = refused.json()
    assert body["code"] == NOT_EXPOSED
    assert {r["destination"] for r in body["remedies"]} == {"docs:openapi", "surface:customer"}
    assert "djb_notes" not in refused.content.decode()
    assert exposed.status_code == 200, exposed.content
    assert [row["id"] for row in exposed.json()["items"]] == [str(widget.pk)]
    assert staff.status_code == 200, staff.content


def test_the_host_is_asked_before_the_credential(two_faces: Surface) -> None:
    """An anonymous caller on a customer host meets not-found, never sign-in-first."""
    response = _as(None).get("/api/v1/djb_notes/", HTTP_HOST=CUSTOMER_HOST)
    assert response.status_code == 404
    assert response.json()["code"] == NOT_EXPOSED


def test_the_document_at_a_host_describes_that_surface_alone(two_faces: Surface) -> None:
    customer_paths = set(
        _as(None).get("/api/v1/openapi.json", HTTP_HOST=CUSTOMER_HOST).json()["paths"]
    )
    staff_paths = set(_as(None).get("/api/v1/openapi.json", HTTP_HOST=STAFF_HOST).json()["paths"])

    assert "/api/v1/widgets/" in customer_paths
    assert not {path for path in customer_paths if path.startswith("/api/v1/djb_notes/")}
    assert {path for path in staff_paths if path.startswith("/api/v1/djb_notes/")}
    assert customer_paths < staff_paths


def test_a_face_is_offered_only_the_acts_its_surface_offers(
    two_faces: Surface, tenant: Tenant, owner: User, root_org: Organization
) -> None:
    staff = actor_for(user=owner, tenant=tenant, org=root_org)
    widget = create_widget(tenant=tenant, actor=staff, name="W")
    at_the_customer_host = dataclasses.replace(staff, surface="customer")

    assert allowed_acts(staff, widget)
    # `read` is the surface's one act and is never an act on a row that exists.
    assert allowed_acts(at_the_customer_host, widget) == ()


# --- the boot question --------------------------------------------------------


def test_the_boot_question_on_an_undeclared_tree(settings: Any) -> None:
    settings.SURFACE_HOSTS = {}
    body = _as(None).get("/api/v1/surface/", HTTP_HOST=STAFF_HOST).json()
    assert body == {"surface": STAFF, "screens": "*", "tenant_rule": "addressed"}


def test_the_boot_question_at_two_hosts(two_faces: Surface) -> None:
    staff = _as(None).get(reverse("surface"), HTTP_HOST=STAFF_HOST)
    customer = _as(None).get(reverse("surface"), HTTP_HOST=CUSTOMER_HOST)

    assert staff.status_code == customer.status_code == 200
    assert staff.json() == {"surface": STAFF, "screens": "*", "tenant_rule": "addressed"}
    assert customer.json() == {"surface": "customer", "screens": [], "tenant_rule": "membership"}


# --- the URL seam -------------------------------------------------------------


def test_with_no_hosts_bound_a_link_is_the_one_it_always_was(settings: Any) -> None:
    settings.SURFACE_HOSTS = {}
    path = reverse(INVITE_LANDING_URL)
    assert absolute_url(path=path, surface=STAFF) == f"{settings.PUBLIC_BASE_URL}{path}"
    assert absolute_url(path=path, surface=surface_for_role("member")) == (
        f"{settings.PUBLIC_BASE_URL}{path}"
    )


def test_a_role_belongs_to_the_surface_that_names_it(two_faces: Surface) -> None:
    assert surface_for_role("customer") == two_faces
    assert surface_for_role("member").key == STAFF
    assert surface_for_role("admin").key == STAFF


def _invitation_mail(
    monkeypatch: pytest.MonkeyPatch, *, tenant: Tenant, owner: User, role: str | None
) -> str:
    """Invite, then send the message the start was handed, and read it back from the outbox."""
    started: list[dict[str, Any]] = []

    def record(**kwargs: Any) -> None:
        started.append(kwargs)

    monkeypatch.setitem(bridge._registry, bridge.START_WORKFLOW_ON_COMMIT, record)
    invite_member(
        tenant=tenant, email="newcomer@example.com", role=role, actor=system_actor(tenant=tenant)
    )
    (message,) = [call["arg"]["message"] for call in started if "message" in call["arg"]]
    mail.send_now(
        to=message["to"],
        subject=message["subject"],
        template=message["template"],
        context=message["context"],
    )
    return str(django_mail.outbox[-1].body)


def test_a_customer_invitation_lands_on_the_customer_host(
    two_faces: Surface, settings: Any, monkeypatch: pytest.MonkeyPatch, tenant: Tenant, owner: User
) -> None:
    settings.PUBLIC_BASE_URL = "https://localhost"
    path = reverse(INVITE_LANDING_URL)

    body = _invitation_mail(monkeypatch, tenant=tenant, owner=owner, role="customer")

    assert f"https://customer.localhost{path}" in body
    staff_body = _invitation_mail(monkeypatch, tenant=tenant, owner=owner, role="member")
    assert f"https://localhost{path}" in staff_body


def test_a_staff_invitation_with_no_hosts_bound_is_the_link_it_always_was(
    settings: Any, monkeypatch: pytest.MonkeyPatch, tenant: Tenant, owner: User
) -> None:
    settings.SURFACE_HOSTS = {}
    body = _invitation_mail(monkeypatch, tenant=tenant, owner=owner, role=None)
    assert f"{settings.PUBLIC_BASE_URL}{reverse(INVITE_LANDING_URL)}" in body


def test_a_link_for_a_surface_with_no_host_is_refused_while_others_are_bound(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    declared = union([(_declarer("portal"), {"customer": CUSTOMER})])
    monkeypatch.setattr(surfaces, "_declared", declared)
    settings.SURFACE_HOSTS = {STAFF: STAFF_HOST}
    with pytest.raises(ImproperlyConfigured, match="'customer'"):
        absolute_url(path="/x/", surface="customer")
