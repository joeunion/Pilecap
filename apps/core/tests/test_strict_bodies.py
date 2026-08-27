"""Request bodies are STRICT, and the refusal is the one envelope (SB-1).

The owner's ruling of 2026-08-24, both halves, held here:

1. **An unknown field in a request body is a refusal, never silently dropped.**
   The measured instance is FT-1′ F6: `POST /webhook-endpoints/` with
   `event_types` (the wrong name for `event_names`) answered **201** and handed
   back a signing secret for an endpoint subscribed to *nothing*. A healthy
   status for a request that did not do what it said is the worst failure shape
   a BYO-agent platform has — the agent has no signal at all, and the silence
   is discovered weeks later as "the webhooks never fired".

2. **The validation refusal joins the envelope.** pydantic's own shape —
   `{"detail": [{"loc", "msg", "type"}]}`, a list, no `code` — was the one
   other shape `django-conventions` §6 blessed. It is now recomposed by the one
   mapper into the registered grammar: a `code` (`invalid_body`), a
   plain-language sentence, the field errors under `errors`, and remedies.

**The census is derived, never a hand list.** `_request_body_components()`
reads the live OpenAPI document and follows every `requestBody` `$ref`
transitively through `components/schemas`. What it asserts is
`additionalProperties: false` — what pydantic renders `extra="forbid"` as, and
the only form of the fact a generated client ever sees. A new `In`/`Patch`
schema that does not inherit `core.schemas.StrictIn` fails **by name**, on
the day it is added, without anybody editing a list here.

**Declared blind spots.**

* The census is scoped to what the *document* uses as a request body. A schema
  that no route accepts is not held to strictness, because nothing can send it.
* `FilterSchema` and query parameters are deliberately out of scope: this
  ruling is about bodies. A stray `?event_types=` is a different (and much
  more visible) failure, and ninja's own query handling is not the seam here.
* The MCP door's argument validation is not measured here, and it is **not
  strict**: an unknown argument to a tool is dropped exactly as an unknown body
  field used to be (measured in phase 1 — a call with a misspelled argument and
  the same call without it are indistinguishable), and the tool schemas the
  server publishes carry no `additionalProperties: false`. That is a real hole
  in the same shape as F6, on the other door, and it is a rung rather than a
  line: `apps/core/mcp.py` and the tool registration are not this module's, and
  a fix belongs beside them.
* `apps/accounts/**` was excluded from phase 1's sweep because a parallel rung
  owned those files. Phase 2 swept it; `PENDING_ACCOUNTS_SWEEP` below is now
  empty, and the pair of tests that kept it honest is still here.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.core.exceptions import REFUSALS
from apps.core.models import Tenant
from apps.core.schemas import StrictIn
from config.api import api as the_api

pytestmark = pytest.mark.django_db

ENDPOINTS_URL = "/api/v1/webhook-endpoints/"
JSON = "application/json"

#: The code the recomposed validation refusal carries. Named here so the tests
#: below read as a contract rather than as a string literal repeated nine times.
#:
#: There is no `ENVELOPE_KEYS` beside it any more. Phase 1 carried one, because
#: the refusal census that owns that property lives in `apps/accounts/tests/
#: test_refusal_envelope.py` and those files belonged to another rung at the
#: time; phase 2 folded the validation class into `assert_one_envelope` there
#: and deleted the copy. Two sets naming the same four keys is one edit away
#: from being two different contracts.
VALIDATION_CODE = "invalid_body"


# --- The census: every body the document accepts is strict --------------------


#: **Empty, and that is the whole point of it.**
#:
#: Phase 1 could not sweep `apps/accounts/**` — a parallel rung owned those
#: files — so its four request bodies (`RealmIn`, `SsoConnectionIn`,
#: `SsoConnectionPatch`, `TokenIn`) were named here instead of being quietly
#: skipped, and the list was held from BOTH ends: `test_every_request_body_...`
#: refuses anything lax that is not named here, so nothing could join it
#: quietly, and `test_the_pending_list_does_not_go_stale` refuses a name that
#: has since become strict, so the sweep could not land and leave the exemption
#: standing. Phase 2 swept them; the second test is what made emptying this
#: mandatory rather than tidy.
#:
#: It stays as an empty frozenset rather than being deleted, because the pair of
#: tests around it is the mechanism — the next time a rung has to leave part of
#: the tree lax for a merge window, this is where it says so, and the same two
#: tests make it temporary again.
PENDING_ACCOUNTS_SWEEP: frozenset[str] = frozenset()


def _request_body_components() -> dict[str, dict[str, Any]]:
    """Every component the document uses as a request body, with its definition.

    **Derived off the finished document**, which is deliberately not the same
    thing as "off the schema classes". The document is what a client generates
    from, and `additionalProperties: false` is how a body's strictness reaches
    that client — a schema that were strict in Python and silent in the document
    would still hand every generated client a lax type. Reading the document is
    reading what was published.

    The walk follows `$ref`s **transitively** through `components/schemas`, so a
    schema nested inside a body (`PolicyIn.steps: list[PolicyStepIn]`) is in the
    population too: an unknown field one level down is exactly as silent as one
    at the top.
    """
    document = the_api.get_openapi_schema()
    components: dict[str, Any] = document.get("components", {}).get("schemas", {})
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                name = ref.rsplit("/", 1)[-1]
                if name not in found:
                    found.add(name)
                    walk(components.get(name))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for operations in document.get("paths", {}).values():
        for operation in operations.values():
            if not isinstance(operation, dict):
                continue
            body = operation.get("requestBody")
            if body:
                walk(body)
    return {name: components.get(name, {}) for name in found}


def _lax_request_bodies() -> set[str]:
    """The ones that would still drop an unknown field on the floor."""
    return {
        name
        for name, definition in _request_body_components().items()
        # `extra="forbid"` is exactly what pydantic renders as this key, so the
        # document says the thing the Python means. `is not False` rather than a
        # truth test: absent and `true` are both lax, and they are both wrong.
        if definition.get("additionalProperties") is not False
    }


def test_every_request_body_the_document_accepts_is_strict() -> None:
    """The ruling's first half, as a property of the whole published document.

    A new `In` or `Patch` schema that inherits `ninja.Schema` directly fails
    here **by name**, on the day it is added, which is the thing a hand list
    could never do.
    """
    population = _request_body_components()
    assert population, "the document declares no request bodies at all — the census is blind"
    # The census must be looking at real bodies, not at an empty walk that
    # happens to have nothing to complain about.
    assert "WebhookEndpointIn" in population, sorted(population)

    lax = sorted(_lax_request_bodies() - PENDING_ACCOUNTS_SWEEP)
    assert not lax, (
        "these request bodies silently drop unknown fields — inherit "
        "`apps.core.schemas.StrictIn` (SB-1, the owner's ruling of "
        f"2026-08-24): {lax}"
    )


def test_the_pending_list_does_not_go_stale() -> None:
    """The other end of the exemption: a name that is strict may not linger here.

    It did its job. Phase 2 swept `apps/accounts/**` and all four names became
    strict at once; this test went red naming every one of them, and stayed red
    until the list was emptied. The exemption could not outlive its reason
    because a test, not a memory, was holding the second end.
    """
    still_lax = _lax_request_bodies()
    healed = sorted(PENDING_ACCOUNTS_SWEEP - still_lax)
    assert not healed, (
        "these request bodies are strict now, so they are not pending any more — "
        f"take them out of PENDING_ACCOUNTS_SWEEP: {healed}"
    )


def test_the_base_itself_forbids_extras() -> None:
    """The one seam, checked directly, so the census cannot pass vacuously."""
    assert StrictIn.model_config.get("extra") == "forbid"

    class Probe(StrictIn):
        name: str

    with pytest.raises(Exception) as raised:
        Probe(name="ok", nmae="typo")  # type: ignore[call-arg]
    assert "nmae" in str(raised.value)


# --- FT-1′ F6: the typo that used to answer 201 -------------------------------


def test_a_misspelled_field_is_refused_rather_than_dropped(
    api: Client, owner: User, tenant: Tenant
) -> None:
    """The repro, at the door.

    Previously: **201**, a signing secret, and an endpoint subscribed to
    nothing — `event_types` was not a field, so it was dropped and
    `event_names` took its `[]` default, which means "every event" here only
    because the create route reads an empty list that way. The subscriber's
    intent ("these two events") reached no column at all and no answer said so.
    """
    api.force_login(owner)
    response = api.post(
        ENDPOINTS_URL,
        data=json.dumps(
            {
                "url": "https://subscriber.example/hook",
                "event_types": ["example.widget.created"],
            }
        ),
        content_type=JSON,
    )

    assert response.status_code == 422, response.content
    body = response.json()
    assert body["code"] == VALIDATION_CODE, body
    # The unknown field is named, and the message says what is wrong with it —
    # not "extra_forbidden", which is pydantic's word for the rule rather than
    # an answer to the person holding the refusal.
    assert "event_types" in body["errors"], body
    assert any(
        "not part of this operation" in message for message in body["errors"]["event_types"]
    ), body


def test_the_correct_field_still_creates_the_endpoint(
    api: Client, owner: User, tenant: Tenant
) -> None:
    """The complementary case: strictness refuses the typo, not the caller."""
    api.force_login(owner)
    response = api.post(
        ENDPOINTS_URL,
        data=json.dumps(
            {
                "url": "https://subscriber.example/hook",
                "event_names": ["example.widget.created"],
            }
        ),
        content_type=JSON,
    )
    assert response.status_code == 201, response.content
    assert response.json()["endpoint"]["event_names"] == ["example.widget.created"]


# --- The 422 joins the envelope ------------------------------------------------


def _probe(api: Client, body: Any) -> Any:
    return api.post(ENDPOINTS_URL, data=json.dumps(body), content_type=JSON)


#: The shapes pydantic can refuse. **The ENVELOPE property for every one of
#: them is held by the refusal census** — `apps/accounts/tests/
#: test_refusal_envelope.py`, where SB-1 folded the validation class in beside
#: every other refusal class and `assert_one_envelope` is the one assertion. It
#: is not repeated here, because two copies of one property is how the two come
#: to disagree about what the envelope is.
#:
#: What is left here is the half that belongs to strictness rather than to the
#: envelope: whether the refusal says the RIGHT THING about the request — the
#: caller's own field name, and a sentence a person can act on without knowing
#: what pydantic is.
VALIDATION_PROBES: tuple[tuple[str, Any], ...] = (
    # An unknown field — the F6 shape.
    ("an unknown field", {"url": "https://s.example/h", "event_types": ["a"]}),
    # A missing required field.
    ("a missing field", {"description": "no url at all"}),
    # A field of the wrong type.
    ("the wrong type", {"url": "https://s.example/h", "event_names": "not-a-list"}),
    # Several at once — the answer carries every field, not the first.
    ("several at once", {"event_names": 7, "nonsense": True}),
    # Not an object at all.
    ("not an object", ["url"]),
)


def _body_parameter_names() -> set[str]:
    """What every route in this tree calls its body parameter, off the mount.

    `payload`, everywhere, today — but derived rather than typed, because the
    property being tested is "the ROUTE's word for it never reaches a caller"
    and a product that named its parameter something else would need that
    property just as much. ninja builds one model per parameter source; the
    body model's fields ARE the view's body parameter names.
    """
    names: set[str] = set()
    for bound in the_api._get_bound_routers():
        for path_view in bound.path_operations.values():
            for operation in path_view.operations:
                for model in operation.models:
                    if getattr(model, "__ninja_param_source__", "") == "body":
                        names.update(model.model_fields)
    return names


@pytest.mark.parametrize(("what", "body"), VALIDATION_PROBES, ids=[p[0] for p in VALIDATION_PROBES])
def test_every_validation_refusal_names_fields_in_plain_language(
    api: Client, owner: User, tenant: Tenant, what: str, body: Any
) -> None:
    """Whatever pydantic refused, the answer is in the caller's own vocabulary.

    `errors` is keyed on names the caller SENT — not on `loc` paths, not on the
    view's body-parameter name — and every message is a sentence rather than a
    validator's rule name. Both halves matter to an agent correcting its own
    request: it searches its request for the key, and it acts on the sentence.

    **This is not a hypothetical guard: it caught one.** A body that is not an
    object at all makes ninja report `loc == ("body", "payload")`, and the first
    draft of the mapper kept that last segment "so it names something rather
    than nothing" — publishing `payload`, the view's parameter name, to a caller
    who has never seen the view. It answers `body` now.
    """
    route_words = _body_parameter_names()
    assert route_words, "no body parameters found, so this test cannot fail"

    api.force_login(owner)
    response = _probe(api, body)

    assert response.status_code == 422, (what, response.content)
    payload = response.json()
    assert payload["code"] == VALIDATION_CODE, payload

    errors = payload["errors"]
    assert isinstance(errors, dict) and errors, payload
    for field, messages in errors.items():
        assert isinstance(field, str) and field, payload
        # The route's own vocabulary is not the caller's, at any depth.
        for segment in field.split("."):
            assert segment not in route_words, (what, field, payload)
        # And Django's non-field key is a framework's word, not a request's.
        assert "__all__" not in field, (what, field, payload)
        assert messages and all(isinstance(m, str) and m.strip() for m in messages), payload

    detail = payload["detail"]
    assert isinstance(detail, str) and detail.strip(), payload


# --- the sentence reads as English on both arms -------------------------------


#: The stem of the unknown-field sentence, up to the word the COUNT decides.
#: Named once so the two arms below assert against one sentence rather than
#: against two hand-typed copies of it — the shape that let the singular arm go
#: ungrammatical for a whole phase while the plural arm read fine.
UNKNOWN_STEM = "This operation has no"

#: And the half neither arm may change. This is a PROSE fix: the count decides
#: one word and nothing else about the refusal moves — not this tail, not the
#: `code`, not the status, not `errors`, not `remedies`.
UNKNOWN_TAIL = "so the request was refused rather than carried out without it. Nothing was changed."


def _unknown_field_detail(api: Client, owner: User, body: Any) -> str:
    """The `detail` sentence for a body whose ONLY failures are unknown fields.

    Through the door rather than against `_validation_sentence`, because the
    sentence a caller reads is the one that survived the composer, the handler
    and JSON — and because a unit call could not have caught the envelope
    moving underneath it, which is the other half of what these two arms pin.
    """
    api.force_login(owner)
    response = _probe(api, body)
    assert response.status_code == 422, response.content
    payload = response.json()
    assert payload["code"] == VALIDATION_CODE, payload
    # The prose fix moves the sentence and nothing around it.
    assert set(payload) == {"detail", "code", "errors", "remedies"}, payload
    assert payload["remedies"] == [
        {"label": "Read the failing fields and resend", "destination": "field:errors"},
        {"label": "Read the shape this operation accepts", "destination": "docs:openapi"},
    ], payload
    detail = payload["detail"]
    assert isinstance(detail, str), payload
    assert detail.endswith(UNKNOWN_TAIL), detail
    return detail


def test_one_unknown_field_is_named_in_a_sentence_that_reads(
    api: Client, owner: User, tenant: Tenant
) -> None:
    """The singular arm: "has no field called `x`", never "has no a field called `x`".

    The refusal is the ONE thing a caller who typed `event_types` for
    `event_names` ever sees about it, and it is read by people and by agents
    correcting their own request. A sentence that stumbles at the exact word
    that names the failure is the API saying "I did not proof-read the only
    line you get" — cheap to fix, and it costs credibility everywhere else the
    envelope claims to be plain language.

    The MCP twin (`apps/core/mcp.py::_argument_sentence`) already drops the
    article on its own singular for this reason, and says so in a comment. The
    doors say the same thing the same way now.
    """
    detail = _unknown_field_detail(api, owner, {"url": "https://s.example/h", "event_types": ["a"]})

    assert "no a field" not in detail, detail
    assert f"{UNKNOWN_STEM} field called `event_types`, " in detail, detail


def test_several_unknown_fields_keep_the_plural(api: Client, owner: User, tenant: Tenant) -> None:
    """The other arm, pinned so the fix cannot be "delete the branch".

    `subject` exists to make the sentence agree with the count, and the count is
    still two here: both names, in the order they were sent, under one plural
    noun. A fix that hard-coded the singular would read "has no field called
    `event_types`, `kind`" and pass the arm above.
    """
    detail = _unknown_field_detail(
        api, owner, {"url": "https://s.example/h", "event_types": ["a"], "kind": "x"}
    )

    assert f"{UNKNOWN_STEM} fields called `event_types`, `kind`, " in detail, detail


def test_the_document_does_not_carry_a_second_copy_of_the_sentence() -> None:
    """The document's twin of this refusal is the registry's `fact`, not the sentence.

    Rule 41's shape: what the document publishes about a refusal is written out
    of the registry, so document and wire cannot come to disagree about it. The
    runtime `detail` is composed per request — it names THIS request's fields —
    and has no business being quoted in a static description. This is what keeps
    the fix a one-place fix: had the sentence been pasted into a route
    description, correcting the wire would have left the document ungrammatical
    and nothing would have said so.

    The absence is asserted on the sentence's own stem rather than on any
    fragment of it: `has no field` alone appears in an unrelated tag
    description ("every other read of an endpoint has no field for it"), and a
    guard that failed on prose it was never about is a guard somebody deletes.

    `ensure_ascii=False` because the registry's prose carries em dashes, and the
    default rendering escapes them to `\\u2014` — a substring test against the
    escaped form would fail on prose that IS present, which is the same false
    negative in the other direction.
    """
    document = json.dumps(the_api.get_openapi_schema(), ensure_ascii=False)

    assert UNKNOWN_STEM not in document, "the refusal sentence has grown a second home"
    assert REFUSALS[VALIDATION_CODE].fact in document, "the document lost the registry's fact"


def test_the_validation_code_is_registered_with_a_fact_and_remedies() -> None:
    """The code is a published contract, and the registry is where it is said."""
    refusal = REFUSALS[VALIDATION_CODE]
    assert refusal.boundary == "door"
    assert refusal.fact.strip()
    assert refusal.remedy.strip()
    assert refusal.remedies


def test_the_validation_code_is_distinct_from_the_services_own_invalid() -> None:
    """`invalid` is what a SERVICE raises; `invalid_body` is what the DOOR did.

    They are two different facts and two different fixes — one says a business
    rule did not hold, the other says the request never reached a service at
    all — so they are two codes, and a client can tell them apart.
    """
    assert VALIDATION_CODE != "invalid"
    assert REFUSALS[VALIDATION_CODE].fact != REFUSALS["invalid"].fact
