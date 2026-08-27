"""`introspect` is what agents read instead of guessing, so it is tested.

If this drifts, every agent downstream starts guessing again.
"""

from __future__ import annotations

import hashlib
import json
import re
from io import StringIO
from typing import Any

import pytest
from django.conf import settings
from django.core.management import call_command

from apps.core.management.commands.introspect import _redact

pytestmark = pytest.mark.django_db

# The address shape a `repr()` leaves behind, written out here rather than
# imported from `apps/test_gate_liveness.py` for the same reason it is written
# out there: a normalisation applied somewhere else must not be able to
# satisfy this silently. Re-asserted in this file because the models section
# grew, and a section that grows is a section that can grow a `repr()`.
ADDRESS = re.compile(r"0x[0-9a-fA-F]+")


def _document() -> str:
    out = StringIO()
    call_command("introspect", stdout=out)
    return out.getvalue()


@pytest.fixture
def payload() -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(_document())
    return parsed


def test_it_emits_valid_json_with_a_section_per_door(payload: dict[str, Any]) -> None:
    assert set(payload) == {
        "apps",
        "models",
        "urls",
        "routes",
        "tools",
        "consumers",
        "workflows",
        "activities",
        "bridge",
        "policies",
        "events",
        "refusals",
        "settings",
    }
    # Every app the tree contains is reported, whichever apps the tree contains:
    # `INSTALLED_APPS` is discovered, so a new app must appear here on its own.
    discovered = {name.removeprefix("apps.") for name in settings.LOCAL_APPS}
    assert discovered <= set(payload["apps"])
    assert {"core", "accounts"} <= discovered


def test_it_reports_the_machine_door(payload: dict[str, Any]) -> None:
    assert "ping" in {tool["name"] for tool in payload["tools"]}


def test_it_reports_the_durable_work(payload: dict[str, Any]) -> None:
    assert "EchoWorkflow" in {workflow["name"] for workflow in payload["workflows"]}
    assert "mark_run_finished" in {activity["name"] for activity in payload["activities"]}


def test_it_reports_the_bridge_registry(payload: dict[str, Any]) -> None:
    """The names the platform apps filled from ready(), read off the live registry.

    The bridge is the one dependency an agent cannot find by reading imports —
    that is its whole design — so the command that reports what the mounts
    found reports it too. Names only asserted for the apps this tree
    ships; a new registration must appear here without anyone editing a list.
    """
    from apps.core import bridge

    by_name = {row["name"]: row["provider"] for row in payload["bridge"]}
    assert set(by_name) == set(bridge.registered())
    assert bridge.START_WORKFLOW_ON_COMMIT in by_name
    assert bridge.EMIT in by_name
    assert bridge.REALTIME_PUSH in by_name
    for provider in by_name.values():
        assert provider.startswith("apps.")


def test_it_reports_the_sockets_it_found(payload: dict[str, Any]) -> None:
    """The shape of the section, not its current emptiness.

    Asserting `== []` would have made the first app to declare a consumer edit
    core's tests to add its own — a shared file, for a change in another app.
    What matters is that each entry is read from the router and carries what a
    reader needs.
    """
    assert isinstance(payload["consumers"], list)
    for entry in payload["consumers"]:
        assert set(entry) >= {"pattern", "consumer"}
        assert entry["pattern"]
        assert entry["consumer"]


def test_it_reports_the_custom_user_model(payload: dict[str, Any]) -> None:
    labels = {f"{model['app']}.{model['name']}" for model in payload["models"]}
    assert "accounts.User" in labels
    assert payload["settings"]["AUTH_USER_MODEL"] == "accounts.User"

    user = next(m for m in payload["models"] if f"{m['app']}.{m['name']}" == "accounts.User")
    assert "apps.core.models.BaseModel" in user["bases"]
    fields = {field["name"]: field for field in user["fields"]}
    assert fields["email"]["unique"] is True
    assert fields["id"]["type"] == "UUIDField"


def test_it_reports_the_token_door(payload: dict[str, Any]) -> None:
    patterns = {route["pattern"] for route in payload["routes"]}
    assert "/api/v1/tokens/" in patterns
    assert "/api/v1/tokens/{token_id}/" in patterns


def test_it_reports_the_widget_route_with_the_auth_it_declares(payload: dict[str, Any]) -> None:
    patterns = {route["pattern"] for route in payload["routes"]}
    assert "/api/v1/widgets/" in patterns

    listing = next(
        route
        for route in payload["routes"]
        if route["pattern"] == "/api/v1/widgets/" and route["methods"] == ["GET"]
    )
    assert listing["name"] == "api:widget-list"
    assert listing["view"] == "apps.example.api.list_widgets_route"
    # The order is the property, not an accident of how `API_AUTH` was typed:
    # ninja stops at the first authenticator that answers, and the cookie one
    # raises 403 on a failed CSRF check rather than declining — so the token
    # has to be tried first or the machine door cannot POST at all
    # (`apps/accounts/auth.py`).
    assert listing["auth"] == ["ApiTokenAuth", "SessionCookieAuth"]
    assert listing["paginated"] is True


# House rule 3's allow-list lives in `quality/rules.yaml` (rule 3,
# `allow_unauthenticated`) and nowhere else: **the only legitimate
# `auth=None` is a signature-verifying inbound webhook receiver**
# (`architecture.md`, house rule 3). These tests defer to it through
# `apps.core.checks` — the same loader the `djb` system check enforces it with
# — so the test, the check and the file cannot drift apart.


def test_every_route_it_reports_declares_auth(payload: dict[str, Any]) -> None:
    from apps.core.checks import unauthenticated_url_names

    assert payload["routes"]
    allowed = unauthenticated_url_names()
    for route in payload["routes"]:
        if route["name"] in allowed:
            continue
        assert route["auth"], route["pattern"]


def test_the_allow_listed_routes_are_the_only_unauthenticated_ones(
    payload: dict[str, Any],
) -> None:
    """The other half, and the one that fails when somebody adds a second.

    Stated as an equality so that a new `auth=None` anywhere in the tree is a
    failure here, and so that deleting the receiver without deleting its
    rules.yaml entry is one too.
    """
    from apps.core.checks import unauthenticated_url_names

    unauthenticated = {route["name"] for route in payload["routes"] if not route["auth"]}
    assert unauthenticated == unauthenticated_url_names()


def test_it_reports_the_widget_owner_relation(payload: dict[str, Any]) -> None:
    widget = next(m for m in payload["models"] if f"{m['app']}.{m['name']}" == "example.Widget")
    owner = next(field for field in widget["fields"] if field["name"] == "owner")
    assert owner["type"] == "ForeignKey"
    assert owner["related_model"] == "accounts.User"


def test_it_never_prints_a_secret(payload: dict[str, Any]) -> None:
    blob = json.dumps(payload)
    assert settings.SECRET_KEY not in blob
    for banned in ("SECRET_KEY", "PASSWORD", "TOKEN", "API_KEY"):
        assert banned not in blob
    # The database slice is engine and name; credentials never leave the box.
    assert set(payload["settings"]["DATABASES"]["default"]) == {"ENGINE", "NAME"}


def test_redaction_survives_nesting() -> None:
    redacted = _redact(
        {
            "SAFE": "keep me",
            "AWS_SECRET_ACCESS_KEY": "sensitive",  # pragma: allowlist secret
            "nested": [
                {"api_token": "sensitive"},  # pragma: allowlist secret
                {"PASSWORD": "sensitive"},  # pragma: allowlist secret
            ],
        }
    )
    assert redacted["SAFE"] == "keep me"
    assert redacted["AWS_SECRET_ACCESS_KEY"] == "[redacted]"
    assert redacted["nested"][0]["api_token"] == "[redacted]"
    assert redacted["nested"][1]["PASSWORD"] == "[redacted]"


def test_the_policies_section_reports_the_discovered_registry(
    payload: dict[str, Any],
) -> None:
    """What an agent reads instead of guessing at a role name.

    An opaque predicate is reported as one: the callable is named, `roles` is
    `null`, and `decided_by` says which of the two shapes this row is so that
    the `null` is never read as "unknown".
    """
    actions = {row["action"]: row for row in payload["policies"]}
    assert "widget.update" in actions
    assert actions["widget.update"]["policy"].startswith("apps.example.policies.")
    assert actions["widget.update"]["decided_by"] == "predicate"
    assert actions["widget.update"]["roles"] is None


def test_no_row_carries_a_role_default_that_never_applies(payload: dict[str, Any]) -> None:
    """The column that was wrong on every row, not just the loud one.

    `core.authz.allows` consults the policy and returns; the `is_read` role
    default is reached only when NO policy names the action. Every row in this
    section is an action a policy names, so a `member_default` here described
    the rows that are not in the table. It is gone, and this is what keeps it
    from coming back by somebody restoring a "helpful" column.
    """
    assert payload["policies"], "the section is empty; this test would pass vacuously"
    for row in payload["policies"]:
        assert set(row) == {"action", "policy", "decided_by", "roles"}, row
        assert row["decided_by"] in {"declaration", "predicate"}


def test_a_declared_permissions_roles_reach_the_instrument(payload: dict[str, Any]) -> None:
    """The narrowing seam, made visible where agents look.

    `apps/usage/policies.py` declares who may read a tenant's bill as DATA —
    all roles by default — and the predicate consults the declaration. Before
    this, `introspect` printed the bound method's name and nothing else, so a
    product that narrowed the declaration to owners changed what the API does
    and changed nothing an instrument could see.

    Asserted against `ROLE_RANK` rather than a typed list of three strings: the
    declaration itself is derived from the role vocabulary, and a hand-written
    expectation here would be the second spelling of it.
    """
    from apps.core.authz import ROLE_RANK

    row = next(r for r in payload["policies"] if r["action"] == "usage.read_report")
    assert row["decided_by"] == "declaration"
    assert row["roles"] == sorted(ROLE_RANK)


def test_the_events_section_exists_and_is_names_only(payload: dict[str, Any]) -> None:
    """The events app is a later rung; the section is laid so it fills itself in.

    Names, never subscribers: what listens is data (`WebhookEndpoint` rows) and
    the realtime bridge, so there is nothing else here to report.
    """
    assert isinstance(payload["events"], list)
    for row in payload["events"]:
        assert set(row) == {"app", "constant", "name"}
        assert row["name"].count(".") >= 2


def test_the_refusals_section_reports_the_registry(payload: dict[str, Any]) -> None:
    """What this product can say no with, read from the live registry.

    The question an agent otherwise answers by grepping for `raise`. Stated as
    an equality against `core.exceptions.REFUSALS` so that a product declaring a
    further code sees it here without editing `introspect`, and so that a
    section that quietly stopped reporting one is a failure rather than a
    shorter list.
    """
    from apps.core.exceptions import BOUNDARIES, REFUSALS

    rows = {row["code"]: row for row in payload["refusals"]}
    assert set(rows) == set(REFUSALS)

    # The floor: eight codes reach clients from this tree — the six class codes,
    # and the two the idempotency middleware answers with in front of every
    # door — so a registry smaller than eight is a registry that lost one.
    assert len(rows) >= 8
    assert {
        "error",
        "not_found",
        "conflict",
        "forbidden",
        "invalid",
        "rate_limited",
        "idempotency_key_reuse",
        "in_progress",
    } <= set(rows)

    # AMENDED (ADR core-5): a registry row is four fields now. `fact` is what
    # is true, said to whoever is refused; `remedies`
    # is what they can do about it, structured so a screen and an assistant
    # render the same offer. `remedy` stays what it was — the developer's
    # advice, reported here and never on the wire.
    for code, row in rows.items():
        assert set(row) == {"code", "boundary", "fact", "remedies", "remedy"}
        assert row["boundary"] in BOUNDARIES, code
        assert row["remedy"].strip(), code
        assert row["fact"].strip(), code
        assert row["remedies"], code
        for remedy in row["remedies"]:
            assert set(remedy) == {"label", "destination"}, code
            assert remedy["label"].strip() and remedy["destination"].strip(), code


def test_the_refusals_section_carries_the_remedy_the_wire_does_not(
    payload: dict[str, Any],
) -> None:
    """The asymmetry is the point: advice here, the composed body there.

    `introspect` is the machine door onto the product for whoever is building
    against it; the remedy names policy files and headers, which is exactly the
    prose a client must never receive (`config/api.py`, and `test_api_errors`).

    AMENDED: the *client-facing* half of the same row — the fact and the
    remedies — is reported here too and does reach the wire.
    Both halves in one place, honestly labelled, is what makes the asymmetry
    readable instead of accidental.
    """
    not_found = next(row for row in payload["refusals"] if row["code"] == "not_found")
    assert "for_tenant" in not_found["remedy"]
    assert not_found["boundary"] == "selector"
    # The fact is the one this code exists to say out loud, and it says it
    # without naming a selector or a file.
    assert "not-there" in not_found["fact"] and "not-yours" in not_found["fact"]
    assert "for_tenant" not in not_found["fact"]
    assert [remedy["destination"] for remedy in not_found["remedies"]] == [
        "header:X-Tenant",
        "header:X-Org",
    ]


# --- the values a field may hold -----------------------------------------------


def test_a_choice_field_reports_the_values_it_may_hold(payload: dict[str, Any]) -> None:
    """The gap this closes: an instrument that did not report choices.

    A criterion asked that "introspect shows the choice" and there was no
    choices section anywhere in the document — so the only way to answer "what
    may this column hold" was to open `models.py`, which is the guessing this
    command exists to end. `WorkflowRun.status` is the motivating field: a
    deliberate stop closes as `cancelled` and NOT as `failed` (ADR
    workflows-7), and that distinction was invisible from here.

    Two assertions on purpose. The **floor** names `cancelled` in this file, so
    a regression that dropped it is a failure here rather than a shorter list
    nobody reads. The **equality against the model's own declaration** is what
    keeps the instrument honest as the model moves: a fifth status appears here
    without anyone editing this test, and an instrument that stopped reporting
    one fails even if the four below survive.
    """
    from apps.workflows.models import WorkflowRun

    run = next(m for m in payload["models"] if f"{m['app']}.{m['name']}" == "workflows.WorkflowRun")
    status = next(field for field in run["fields"] if field["name"] == "status")

    values = [choice["value"] for choice in status["choices"]]
    assert "cancelled" in values, "a deliberate stop is not a failure — ADR workflows-7"
    assert {"running", "completed", "failed", "cancelled"} <= set(values)

    # The model is the authority; this is the instrument agreeing with it,
    # values AND labels, in the order the model declared them.
    assert [(choice["value"], choice["label"]) for choice in status["choices"]] == [
        (value, str(label)) for value, label in WorkflowRun.Status.choices
    ]


def test_choices_are_data_and_a_field_without_them_says_nothing(
    payload: dict[str, Any],
) -> None:
    """A list of `{value, label}`, never a repr, and absent where there is none.

    The shape is the half a downstream reader depends on: `choices` is JSON
    data it can iterate, so nobody has to parse `[('running', 'Running'), ...]`
    out of a string. The absence is the other half — the key appears only on a
    field that declares choices, which is why the document did not grow a
    `"choices": null` line for every column in the tree.
    """
    seen = 0
    for model in payload["models"]:
        for field in model["fields"]:
            if "choices" not in field:
                continue
            seen += 1
            assert isinstance(field["choices"], list) and field["choices"]
            for choice in field["choices"]:
                assert set(choice) == {"value", "label"}
                assert isinstance(choice["label"], str) and choice["label"]
                assert isinstance(choice["value"], (str, int, float, bool))

    assert seen, "no field in the whole tree reported choices — the section is dead"

    # A field with nothing declared carries no key at all, rather than a null.
    user = next(m for m in payload["models"] if f"{m['app']}.{m['name']}" == "accounts.User")
    email = next(field for field in user["fields"] if field["name"] == "email")
    assert "choices" not in email


def test_the_document_carries_no_memory_address_now_that_models_grew(
    payload: dict[str, Any],
) -> None:
    """The no-memory-address invariant, re-asserted at the section that just changed.

    Choices come off the model as whatever the declaration held — routinely a
    lazy translation proxy for a label, whose `repr()` is exactly the
    `<... 0x...>` shape once taken out of the `urls` section. `str()` at the
    source is what keeps that out; this is the guard that would catch it coming
    back, and it reads the WHOLE document rather than the models section for
    the same reason `test_gate_liveness` does.
    """
    document = json.dumps(payload)
    found = ADDRESS.findall(document)
    assert not found, (
        f"introspect emitted {len(found)} memory address(es) ({sorted(set(found))[:3]}): the "
        "document is not comparable across processes."
    )


def test_two_invocations_of_an_unchanged_tree_are_sha_identical() -> None:
    """The stability claim, stated as the thing anyone downstream actually does.

    A reader holds a sha of this document and asks whether the tree moved. That
    question is only answerable if an unchanged tree answers the same bytes
    twice — which is a claim about ORDERING (nothing here iterates a set, and
    `sort_keys=False` means every section's order is the one its builder chose)
    as much as about addresses.

    Two calls in ONE process is what this can prove directly; the cross-process
    half is carried by the address guard above, because a memory address is the
    only thing in this document that was ever per-process. Both halves together
    are the QB-R3 property: emit nothing unstable at source, so nobody
    downstream normalises anything before comparing.
    """
    first = hashlib.sha256(_document().encode()).hexdigest()
    second = hashlib.sha256(_document().encode()).hexdigest()
    assert first == second, "two runs of an unchanged tree produced two different documents"
