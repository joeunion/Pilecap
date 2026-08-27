"""The other half of the promise: the door TAKES the example it publishes.

`test_published_examples.py` asks whether a published example is a document its
own schema would accept. That closes one of the two shapes the defect has. The
other shape is this: an example that **validates and is then refused
by the door that publishes it** — schema-valid, vocabulary-dead. The usage
report's example named a meter no deployment declared; it validated against
`UsageReportOut` perfectly, and the read door answered `400`. Nothing in the
validity census could ever have seen that, because nothing in it sends anything.

So this module sends them. For every component the live document uses as a
**request body**, and for every **`Filter`** the routers use as a query, the
published example is submitted to the operation that accepts it, over HTTP,
signed in, against a seeded world — which is what a caller reading
`/api/v1/docs` actually does with it.

**Why a sibling module rather than more of `test_published_examples.py`.** The
validity census is a pure document read: no database, no client, no world, and
it runs in milliseconds on every rung. This one needs a tenant, a tree, a person,
a dozen rows and a savepoint per request. Folding it in would put
`pytest.mark.django_db` over the cheap tests too and blur two teeth that answer
two different questions into one file whose name claims one of them. The two
point at each other instead: that module's copy-paste drive names this one.

**The population is derived, from two joins.** Bodies come off the document:
every operation with a `requestBody` whose `$ref` resolves to a component
carrying an `example`. Filters cannot come off the document — ninja FLATTENS a
`Query[XFilter]` into individual query parameters, so the `XFilter` component is
published (with its example) and referenced by no operation at all, which is
exactly the kind of orphan a document-only census reads straight past. So they
come off the routers: the query model's `filters` annotation names the class,
and `get_openapi_operation_id` joins that operation to its published path. A new
`In` or `Filter` on a new route is driven on the day it lands, with no list here
to edit — and a new PATH PARAMETER this module has no seed for is a hard failure
naming it, never a silently skipped route, because a route that quietly stopped
being driven is exactly how a census comes to measure less and read as a pass.

**What the seeded world is allowed to contain.** The caller's own rows, named
the way the examples name them: a template called `welcome`, a policy called
`dunning`, a document with two versions. It never invents PLATFORM VOCABULARY —
no event name, meter, channel or `kind` is seeded into existence — because that
vocabulary is exactly what that defect is made of, and a world that seeded it
would answer the question by assuming it.

**Isolation.** Each example is sent inside its own savepoint, which is rolled
back before the next one. Without it the drive tests its own order rather than
the examples: `POST /recipients/` then `PATCH /recipients/{id}/` with the same
published email is a uniqueness conflict that no caller pasting one example
would ever meet, and three of the first run's failures were exactly that.

**The verdict, and what "accepted" means.** `2xx` is accepted. Everything else
is a refusal, and every refusal is either a defect or a declared reason — one
table, `DECLARED_REFUSALS`, which may shrink and may never grow. The equality
holds both ends: a new refusal fails naming the schema, and a refusal that has
been fixed fails until its line is removed.

**DOES NOT COVER — declared.**

* `Out`-shaped examples. An `Out` cannot be submitted to anything: it is what a
  door answers with, so there is no door to hand it to. Their whole check is
  validation (`test_published_examples.py`). That defect's own instance was an `Out`
  example whose KEY was then fed to a query parameter by hand — a hop no
  mechanism can follow, which is why usage closed that one by deriving the key
  from the registry rather than by being caught here, and why the plant that
  proved this module used an `In` schema.
* Query parameters that are not a `Filter`. A route's loose `?since=` or
  `?period=` is declared inline and carries no component example to drive, so
  there is nothing published to hold to account. `Filter` schemas ARE driven —
  see below.
* The MCP door. The same examples reach `inputSchema` on the machine door and
  are not driven through `call_tool` here. Rule 46's door-pair tests are where
  that belongs, and this is named in this module rather than assumed.
* A value one door accepts and a LATER operation refuses. `ConnectionIn`'s
  example names the provider `stripe`, which `POST /connections/` takes (201)
  and `POST /connections/{id}/oauth/start/` then has no adapter for. Each
  example is judged by the door that publishes it, which is the promise being
  made; the cross-operation claim is a different (and much larger) one.
* Whether the answer is the RIGHT one. A `201` here means the door took the
  example, not that what it created is what the example described.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import pytest
from django.db import transaction
from django.test import Client
from ninja import FilterSchema

from apps.accounts.models import User
from apps.accounts.services import create_sso_connection, create_user
from apps.core.actor import actor_for
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import add_membership, create_organization
from apps.example.models import Widget, WidgetPolicy
from apps.example.services import create_widget, create_widget_policy
from apps.files import storage
from apps.files.models import FileVersion, StoredFile
from config.api import api as the_api

pytestmark = pytest.mark.django_db

JSON = "application/json"

#: A literal handed to `create_user`, long enough to clear Django's validators
#: and nothing else. Allow-listed for the same reason `apps/conftest.py`
#: allow-lists its own: it is exactly what the scanner is right to look at, and
#: exactly what a reader should be able to see is fake.
PASSWORD = "a-long-enough-password-for-validators"  # pragma: allowlist secret

#: A floor under the POPULATION, for the same reason the validity census has
#: one: a join that stopped resolving would drive nothing, refuse nothing, and
#: read as a pass. Measured at 56 operations the day this landed — 42 bodies
#: and 14 filters.
DRIVEN_FLOOR = 48

#: And a floor under how many of them the doors really TOOK. The equality over
#: `DECLARED_REFUSALS` alone could be satisfied by a drive where everything
#: 404s on a path parameter, which would prove nothing at all. Measured at 49.
ACCEPTED_FLOOR = 42

#: Every published example this deployment's own door does not take, with the
#: app that owns it and why. **This may shrink and may never grow**, and the
#: assertion below holds both ends of it.
#:
#: Two kinds of line live here and the prose says which is which:
#:
#: * a DEFECT — the example is wrong, and the owning app fixes it and deletes
#:   its line;
#: * a REASON — the refusal is about something a published example cannot carry
#:   (an opaque credential minted per row), and the line stays until the shape
#:   of the operation changes.
DECLARED_REFUSALS: dict[str, str] = {
    "CredentialsIn": (
        "apps/connections — DEFECT, and the same one the validity census already "
        "names: `credentials` is `min_length=1` and the synthesised example is "
        "`{}`, so the body is refused as `invalid_body` before any service sees "
        "it. A constraint on the SHAPE of a mapping is the one class the "
        "format-aware synthesiser cannot answer; `apps/connections` declares a "
        "realistic blob with `apps.core.schemas.example(...)`."
    ),
    "InvitationAcceptIn": (
        "REASON, not a defect: `token` is an opaque credential minted per "
        "invitation and mailed to one person. No published example can carry a "
        "live one, and a document that showed a real token would be the defect. "
        "The `404` is the right answer to a token that is not a token, and the "
        "example's SHAPE is what the document is promising here."
    ),
    "SsoConnectionIn": (
        "apps/accounts — DEFECT: `email_domains` publishes `['email domains']`, "
        "the synthesiser's echo of the field name inside a list, and the service "
        "refuses it (\"'email domains' is not an email domain\"). The echo census "
        "in `test_published_examples.py` names this one and its two siblings; "
        "this is what the echo costs a caller who pastes it."
    ),
    "SsoConnectionPatch": (
        "apps/accounts — DEFECT, the same echo as `SsoConnectionIn` and named "
        "separately because the two schemas are fixed separately: `email_domains` "
        "publishes `['email domains']` and the service refuses it. A `Patch` "
        "carrying the same wrong example is the second copy of one defect, which "
        "is why the echo census counts fields rather than schemas."
    ),
    "WidgetEntryIn": (
        "apps/example — DEFECT: `kind` publishes `'inspection'`, which is not "
        "one of `WidgetEntry.Kind`'s choices, so the write is refused as "
        "`invalid` naming the field. `kind` is a CLOSED vocabulary and the "
        "synthesiser had no way to know it — the model's own choices are where "
        "the example should come from."
    ),
}


# --- the seeded world ---------------------------------------------------------


@dataclass(frozen=True)
class World:
    """One tenant shaped like a customer, with a row for every id an example names.

    Everything here is the CALLER'S OWN data — rows a person pasting an example
    would already have, under the names the examples use. Nothing here declares
    a meter, an event name, a channel or a `kind`: platform vocabulary is what
    that defect is made of, and seeding it would answer the question by assuming it.
    """

    client: Client
    tenant: Tenant
    owner: User
    root_org: Organization
    branch: Organization
    other_branch: Organization
    newcomer: User
    membership: Membership
    recipient_id: str
    widget: Widget
    widget_policy: WidgetPolicy
    template_name: str
    policy_name: str
    connection_id: str
    sso_connection: Any
    endpoint_id: str
    document: StoredFile
    pending_document: StoredFile


@pytest.fixture
def world(settings: Any, tenant: Tenant, owner: User, root_org: Organization) -> World:
    """The world the examples are pasted into.

    **The comms and connections rows are made THROUGH THE DOORS, and that is a
    layering fact rather than a flourish.** `apps/core` sits at the bottom of the
    fixed layers (`pyproject.toml`, "The fixed layers hold"), and the contract
    reaches test modules too: a `core` test that imported `comms.services` would
    drag `comms -> accounts | events | workflows | connections` into `core`'s
    import graph, and import-linter breaks the build naming every chain. It did,
    on this module's first full gate. The fix is not an exemption — it is that a
    census OF the doors has no business reaching behind them. Everything a door
    can make is made by posting to it; only what no door can make (a document
    with a CONFIRMED version, which is a workflow) is built from rows.

    `AWS_STORAGE_BUCKET_NAME` is named and **no bucket is created**: the file
    routes reached here only MINT presigned URLs, which is a local HMAC over a
    name (`apps/files/tests/conftest.py::named_bucket` makes the same argument
    for the same reason). Naming it keeps this module out of the organ tier — it
    stays in `--loop`, where a builder pasting a new example finds out in the
    same minute.
    """
    settings.AWS_STORAGE_BUCKET_NAME = storage.derived_bucket_name()
    actor = actor_for(user=owner, tenant=tenant, org=root_org)
    client = Client(raise_request_exception=False)
    client.force_login(owner)

    branch = create_organization(
        tenant=tenant, actor=actor, parent=root_org, name="Seeded north", slug="seeded-north"
    )
    other_branch = create_organization(
        tenant=tenant, actor=actor, parent=root_org, name="Seeded south", slug="seeded-south"
    )
    newcomer = create_user(email="newcomer@example.com", password=PASSWORD)
    joiner = create_user(email="joiner@example.com", password=PASSWORD)
    membership = add_membership(
        user=joiner, tenant=tenant, organization=branch, role="member", actor=actor
    )

    # The examples name a template `welcome` and a policy `dunning`; both are the
    # caller's own rows, so the world has them under those names — posted, not
    # created, for the reason in this fixture's docstring.
    _through_the_door(client, "/api/v1/templates/", {"name": "welcome", "body": "Hello."})
    template = _through_the_door(
        client,
        "/api/v1/templates/",
        {"name": "invoice-reminder", "body": "Due soon.", "subject": "Reminder"},
    )
    policy = _through_the_door(
        client,
        "/api/v1/delivery-policies/",
        {"name": "dunning", "steps": [{"channel": "email", "template": "welcome"}]},
    )
    recipient = _through_the_door(client, "/api/v1/recipients/", {"email": "ada@example.com"})
    connection = _through_the_door(
        client, "/api/v1/connections/", {"provider": "example", "name": "Seeded connection"}
    )
    endpoint = _through_the_door(
        client, "/api/v1/webhook-endpoints/", {"url": "https://seeded.example/hook"}
    )

    return World(
        client=client,
        tenant=tenant,
        owner=owner,
        root_org=root_org,
        branch=branch,
        other_branch=other_branch,
        newcomer=newcomer,
        membership=membership,
        recipient_id=str(recipient["id"]),
        widget=create_widget(tenant=tenant, actor=actor, name="Seeded widget"),
        widget_policy=create_widget_policy(
            tenant=tenant, actor=actor, name="Seeded policy", body="Two approvals."
        ),
        template_name=str(template["name"]),
        policy_name=str(policy["name"]),
        connection_id=str(connection["id"]),
        sso_connection=create_sso_connection(
            tenant=tenant,
            actor=actor,
            name="Seeded IdP",
            issuer="https://idp.example.com",
            client_id="djb",
            client_secret="not-a-real-secret-value",  # pragma: allowlist secret
            email_domains=["example.com"],
        ),
        endpoint_id=str(endpoint["endpoint"]["id"]),
        document=_document(tenant=tenant, org=root_org, owner=owner, stored=2),
        pending_document=_document(tenant=tenant, org=root_org, owner=owner, stored=0),
    )


def _through_the_door(client: Client, path: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST one row into being and hand back what the door answered with.

    A hard failure rather than a skip when the door refuses: a world that half
    built itself would send the examples somewhere they could not land, and the
    404s would read as the examples' fault.
    """
    response = client.post(path, data=json.dumps(body), content_type=JSON)
    assert 200 <= response.status_code < 300, (
        f"the seeded world could not be built: POST {path} answered "
        f"{response.status_code} {response.content!r}"
    )
    answer: dict[str, Any] = response.json()
    return answer


def _document(*, tenant: Tenant, org: Organization, owner: User, stored: int) -> StoredFile:
    """A filed document with `stored` finished versions and one pending after them.

    Built with the manager and `full_clean()` rather than through the service,
    which is the pair the house service style already uses (`with as_invalid():
    row.full_clean()`) — so the landing gate really runs — and which keeps the
    world off the storage seam entirely.
    """
    file = StoredFile(
        tenant=tenant,
        organization=org,
        filename="invoice-2026-08.pdf",
        purpose=StoredFile.Purpose.UPLOAD,
        uploaded_by=owner,
        current_version=stored,
    )
    file.full_clean()
    file.save()
    for number in range(1, stored + 2):
        finished = number <= stored
        version = FileVersion(
            tenant=tenant,
            organization=org,
            file=file,
            version=number,
            key=storage.version_key(tenant=tenant, file_pk=file.pk, version=number),
            content_type="application/pdf",
            uploaded_by=owner,
            status=FileVersion.Status.STORED if finished else FileVersion.Status.PENDING,
            # `fileversion_stored_is_measured`: a row that says STORED carries
            # the evidence of what was stored, so a finished one gets both.
            size_bytes=41238 if finished else None,
            sha256=("a" * 64) if finished else "",
        )
        version.full_clean()
        version.save()
    return file


def _body_seeds(world: World) -> dict[str, str]:
    """What a caller substitutes into a pasted body: the ids of their own rows.

    Keyed on the FIELD NAME, so a new body field called `recipient_id` is
    substituted the day it lands. A field this does not know is left exactly as
    the document published it — which is the point for everything that is not an
    identifier.
    """
    return {
        "recipient_id": world.recipient_id,
        "organization_id": str(world.branch.pk),
        "organization_slug": str(world.root_org.slug),
        "parent_id": str(world.root_org.pk),
        "new_parent_id": str(world.other_branch.pk),
        "user_id": str(world.newcomer.pk),
        "policy_id": str(world.widget_policy.pk),
        "widget_id": str(world.widget.pk),
    }


def _path_seeds(world: World) -> dict[str, str]:
    """A path parameter's value, by parameter name. See `_PATH_OVERRIDES`."""
    return {
        "organization_id": str(world.branch.pk),
        "membership_id": str(world.membership.pk),
        "recipient_id": world.recipient_id,
        "connection_id": world.connection_id,
        "endpoint_id": world.endpoint_id,
        "widget_id": str(world.widget.pk),
        "file_id": str(world.document.pk),
    }


def _path_overrides(world: World) -> dict[str, dict[str, str]]:
    """Where the parameter NAME is not enough to say which row is meant.

    `{name}` is three different resources and `{connection_id}` is two, so these
    are keyed on the operation's own path. A path that moves fails here by name
    rather than being driven against the wrong row, which is the same trade the
    ratchet makes: loud and editable beats derived and wrong.
    """
    return {
        "/api/v1/flags/{name}/": {"name": "beta-banner"},
        "/api/v1/templates/{name}/versions/": {"name": world.template_name},
        "/api/v1/delivery-policies/{name}/versions/": {"name": world.policy_name},
        "/api/v1/auth/sso-connections/{connection_id}/": {
            "connection_id": str(world.sso_connection.pk)
        },
        # The confirm route needs a version that is still PENDING, which the
        # two-version document's is not.
        "/api/v1/files/{file_id}/versions/{version}/confirm/": {
            "file_id": str(world.pending_document.pk),
            "version": "1",
        },
    }


# --- the population, off the live document ------------------------------------


@dataclass(frozen=True)
class Operation:
    """One route, and the component whose published example it accepts.

    `carried` says HOW the example travels — as the JSON body, or as the query
    string a `Filter` becomes. The two are one population because they make one
    promise: this is a thing you may send here.
    """

    schema: str
    method: str
    path: str
    params: tuple[str, ...]
    example: Any
    carried: str = "body"

    def __str__(self) -> str:
        return f"{self.schema} ({self.method.upper()} {self.path}, in the {self.carried})"


def _filter_operations() -> list[Operation]:
    """Every `Filter` component with an example, joined to the route that takes it.

    Off the ROUTERS rather than off the document, and that is the finding this
    function is: ninja flattens `Query[XFilter]` into individual query
    parameters, so the document publishes `XFilter` with an example and no
    operation anywhere references it. Fourteen components in this tree are in
    that position. A census that read only the document would have called the
    `Filter` half empty and declared a blind spot over a population that exists.

    The join is exact rather than heuristic: `get_openapi_operation_id` is the
    same function that wrote the document's `operationId`, so an operation found
    here is matched to its published path by identity and never by guessing which
    route has the right query-parameter names (`PolicyFilter`'s single `name`
    would match several).
    """
    document: dict[str, Any] = the_api.get_openapi_schema()
    components: dict[str, Any] = document["components"]["schemas"]
    published: dict[str, tuple[str, str]] = {
        operation["operationId"]: (method, path)
        for path, operations in document["paths"].items()
        for method, operation in operations.items()
        if isinstance(operation, dict) and operation.get("operationId")
    }

    found: list[Operation] = []
    for bound in the_api._get_bound_routers():
        for view in bound.path_operations.values():
            for operation in view.operations:
                route = published.get(the_api.get_openapi_operation_id(operation))
                if route is None:
                    continue
                for model in operation.models:
                    for field in getattr(model, "model_fields", {}).values():
                        annotation = field.annotation
                        if not isinstance(annotation, type) or not issubclass(
                            annotation, FilterSchema
                        ):
                            continue
                        node = components.get(annotation.__name__)
                        if not isinstance(node, dict) or "example" not in node:
                            continue
                        method, path = route
                        found.append(
                            Operation(
                                schema=annotation.__name__,
                                method=method,
                                path=path,
                                params=(),
                                example=node["example"],
                                carried="query",
                            )
                        )
    return found


def _operations() -> list[Operation]:
    document: dict[str, Any] = the_api.get_openapi_schema()
    components: dict[str, Any] = document["components"]["schemas"]
    found: list[Operation] = []
    for path, operations in document["paths"].items():
        for method, operation in operations.items():
            if not isinstance(operation, dict):
                continue
            body = operation.get("requestBody")
            if not isinstance(body, dict):
                continue
            schema = body.get("content", {}).get(JSON, {}).get("schema", {})
            reference = schema.get("$ref") if isinstance(schema, dict) else None
            if not isinstance(reference, str):
                continue
            name = reference.rsplit("/", 1)[-1]
            node = components.get(name)
            if not isinstance(node, dict) or "example" not in node:
                continue
            found.append(
                Operation(
                    schema=name,
                    method=method,
                    path=path,
                    params=tuple(
                        parameter["name"]
                        for parameter in operation.get("parameters", [])
                        if isinstance(parameter, dict) and parameter.get("in") == "path"
                    ),
                    example=node["example"],
                )
            )
    return found + _filter_operations()


def _address(operation: Operation, world: World) -> str:
    """The path, with this world's ids in it. An unknown parameter is a failure."""
    overrides = _path_overrides(world).get(operation.path, {})
    seeds = _path_seeds(world)
    path = operation.path
    for parameter in operation.params:
        value = overrides.get(parameter) or seeds.get(parameter)
        assert value is not None, (
            f"{operation} takes a path parameter `{parameter}` this module has no seed "
            "for, so the example could not be sent to it. Add it to `_path_seeds` (or "
            "to `_path_overrides` when the name alone does not say which row is meant) "
            "— a route that is quietly not driven is how this census comes to measure "
            "less and still read as a pass."
        )
        path = path.replace("{" + parameter + "}", value)
    return path


def _pasted(operation: Operation, world: World) -> Any:
    """The published example with this world's ids substituted, and nothing else."""
    example = operation.example
    if not isinstance(example, dict):
        return example
    seeds = _body_seeds(world)
    return {field: seeds.get(field, value) for field, value in example.items()}


@dataclass(frozen=True)
class Verdict:
    """What the door said to one pasted example."""

    operation: Operation
    status: int
    code: str | None
    detail: str

    @property
    def accepted(self) -> bool:
        return 200 <= self.status < 300

    def __str__(self) -> str:
        return f"{self.operation} -> {self.status} {self.code or ''} {self.detail}".strip()


def _drive(world: World) -> list[Verdict]:
    """Send every published example to its own door, one at a time.

    `raise_request_exception=False` because an example that makes the door raise
    is a finding this census has to be able to REPORT — `DeviceIn` is one today —
    and a client that re-raises turns that finding into a collected error whose
    message names pytest's plumbing instead of the schema.
    """
    client = world.client
    verdicts: list[Verdict] = []
    for operation in _operations():
        address = _address(operation, world)
        pasted = _pasted(operation, world)
        with transaction.atomic():
            if operation.carried == "query":
                # A `Filter` travels as the query string ninja flattened it into,
                # and `None` means "did not ask" rather than "asked for null".
                query = urlencode(
                    {field: value for field, value in pasted.items() if value is not None}
                )
                response = client.generic(operation.method.upper(), f"{address}?{query}")
            else:
                response = client.generic(
                    operation.method.upper(),
                    address,
                    data=json.dumps(pasted),
                    content_type=JSON,
                )
            # Rolled back before the next example, so the drive tests the
            # examples rather than its own order.
            transaction.set_rollback(True)
        code: str | None = None
        detail = ""
        if response.headers.get("Content-Type", "").startswith(JSON):
            payload = response.json()
            if isinstance(payload, dict):
                code = payload.get("code")
                detail = str(payload.get("detail", ""))[:200]
        verdicts.append(
            Verdict(operation=operation, status=response.status_code, code=code, detail=detail)
        )
    return verdicts


# --- the tooth ----------------------------------------------------------------


def test_every_published_example_is_taken_by_the_door_that_publishes_it(world: World) -> None:
    """The promise's tooth. A caller pastes the example and sends it; the door takes it.

    This is the half of the promise validation cannot reach. `MessageIn`'s
    example validates against `MessageIn` and is refused by `POST /messages/`;
    `WidgetEntryIn`'s `kind` is a legal string and not a legal choice;
    `DeviceIn`'s push token is a legal string that crashes the encrypted-field
    round trip. None of those is visible to a schema, and all three are visible
    the moment somebody sends one.

    The equality below holds the ratchet from both ends at once: a schema that
    starts being refused fails here naming itself, and a schema that has been
    fixed fails until its line comes out of `DECLARED_REFUSALS`.
    """
    verdicts = _drive(world)
    assert len(verdicts) >= DRIVEN_FLOOR, (
        f"only {len(verdicts)} published examples were driven, below the floor of "
        f"{DRIVEN_FLOOR}. The join from operation to component example has stopped "
        "resolving, which drives nothing, refuses nothing and reads as a pass."
    )

    refused = {verdict.operation.schema: verdict for verdict in verdicts if not verdict.accepted}
    new = sorted(set(refused) - set(DECLARED_REFUSALS))
    assert not new, (
        "these schemas publish an example their own door refuses:\n  "
        + "\n  ".join(str(refused[name]) for name in new)
        + "\nAn example a caller cannot paste is a contract that is wrong in the one "
        "place a client has no reason to doubt. Fix the example where the schema is "
        "declared, or declare the reason in `DECLARED_REFUSALS` with the app that "
        "owns it."
    )

    healed = sorted(set(DECLARED_REFUSALS) - set(refused))
    assert not healed, (
        f"these schemas are taken by their own door now: {healed}. Remove them from "
        "`DECLARED_REFUSALS` — a line that outlives its defect tells the next reader "
        "there is still one there."
    )


def test_the_drive_actually_reaches_the_services_behind_the_doors(world: World) -> None:
    """The census cannot pass by refusing everything into the declared table.

    A drive where every example 404s on a path parameter would satisfy the
    equality above and prove nothing, so the count of examples the doors really
    TOOK carries its own floor.
    """
    accepted = [verdict for verdict in _drive(world) if verdict.accepted]
    assert len(accepted) >= ACCEPTED_FLOOR, (
        f"only {len(accepted)} examples were accepted by their doors, below the floor "
        f"of {ACCEPTED_FLOOR}. Either the seeded world stopped resolving or a great many "
        "examples went wrong at once; both are findings rather than a pass."
    )
