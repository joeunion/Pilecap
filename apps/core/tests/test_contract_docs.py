"""ADR api-1: the OpenAPI document is the contract, and the contract is complete.

House rule 41 is the census that keeps it that way, and it runs off the live
document. These tests prove the *properties* the census is asserting about —
that the prose comes from the docstring and only from the docstring, that the
refusals come from the registry and only from the registry, that the headers a
caller has to know about are documented once, and that an unmatched path under
the API answers in the API's own words rather than in Django's HTML.

Nothing here re-lists the routes. The document is read whole and asserted over,
so a route added in any app is in scope from the moment it is discovered — which
is the difference between a contract standard and a checklist somebody maintains.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings
from django.test import Client

from apps.accounts.models import User
from apps.core.api.docs import (
    DOOR_LEVEL_REFUSALS,
    TITLE_MAX_LENGTH,
    contract_half,
    contract_of,
    declared_refusals,
    description_of,
    example_census,
    example_for,
    mechanical_tells,
    overview,
    refuses,
    title_faults,
    title_of,
    with_door_level,
    workshop_half,
)
from apps.core.checks import _bound_operations
from apps.core.exceptions import REFUSALS, Forbidden
from apps.core.idempotency import HEADER as IDEMPOTENCY_HEADER
from apps.core.idempotency import REPLAYED_HEADER
from apps.core.middleware import ORG_HEADER, TENANT_HEADER
from apps.core.models import Membership, Tenant
from config.api import api

WRITE_METHODS = {"post", "put", "patch"}


@pytest.fixture(scope="module")
def document() -> dict[str, Any]:
    """The document as `scripts/gen_client.sh` and `/api/v1/docs` both read it."""
    rendered: dict[str, Any] = json.loads(json.dumps(api.get_openapi_schema()))
    return rendered


def operations(document: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (path, method, operation)
        for path, item in document["paths"].items()
        for method, operation in item.items()
        if method in {"get", "post", "put", "patch", "delete"}
    ]


# --- the docstring is the documentation ---------------------------------------


def test_the_contract_half_is_everything_above_the_divider() -> None:
    doc = """First line.

        A second paragraph a caller is owed.

        ---
        Why it was built this way.
        """
    assert contract_half(doc) == "First line.\n\nA second paragraph a caller is owed."
    assert workshop_half(doc) == "Why it was built this way."
    assert title_of(contract_half(doc)) == "First line."
    assert description_of(contract_half(doc)) == "A second paragraph a caller is owed."


def test_a_docstring_with_no_divider_is_all_contract() -> None:
    assert contract_half("Just this.") == "Just this."
    assert workshop_half("Just this.") == ""


def test_a_route_with_no_docstring_has_no_contract() -> None:
    def undocumented() -> None: ...

    assert contract_of(undocumented) == ""


def test_every_operation_carries_a_summary_and_a_description(document: dict[str, Any]) -> None:
    for path, method, operation in operations(document):
        where = f"{method.upper()} {path}"
        assert operation.get("summary"), f"{where} has no summary"
        assert operation.get("description"), f"{where} has no description"


def test_every_summary_is_the_title_line_of_its_own_docstring() -> None:
    """The derivation, asserted: a title that could be edited alone would be.

    Since 2026-08-24 the two halves no longer overlap — `summary` is the
    docstring's first line and `description` is everything below it — so this
    reads the docstring itself rather than the description's first line.
    """
    for _prefix, operation in _bound_operations():
        contract = contract_of(operation.view_func)
        where = f"{operation.view_func.__module__}.{operation.view_func.__name__}"
        assert operation.summary == title_of(contract), f"{where} drifted from its docstring"
        assert operation.description == description_of(contract), f"{where} drifted"


def test_no_title_is_a_sentence(document: dict[str, Any]) -> None:
    """The owner's screenshot, as an assertion.

    A navigation sidebar shows summaries. One carrying Markdown reaches the
    reader as those characters; one carrying a full stop reads as prose in a
    column of names; one past the cap is truncated by whoever renders it.
    """
    for path, method, operation in operations(document):
        faults = title_faults(str(operation["summary"]))
        assert not faults, f"{method.upper()} {path}: {faults}"


def test_no_contract_half_publishes_maintainer_archaeology() -> None:
    """The plain-language clause, over the live registry rather than over source.

    The four tells are shapes, and they are the cheap half of the plain-language
    bar; the rest is review's, and rule 41 declares it as a blind spot.
    """
    for _prefix, operation in _bound_operations():
        tells = mechanical_tells(contract_of(operation.view_func))
        assert not tells, f"{operation.url_name}: {tells}"


def test_the_declared_example_census_is_at_or_below_its_ratchet(
    document: dict[str, Any],
) -> None:
    """The ratchet, read the way the gate reads it — out of `rules.yaml`.

    A test rather than a second number: the ceiling lives in one file, and this
    asserts the tree is inside it without keeping a copy of it. The title cap is
    checked the same way, because it is stated in three places by design.
    """
    import yaml

    path = Path(settings.BASE_DIR) / "quality" / "rules.yaml"
    rules = yaml.safe_load(path.read_text())
    scope = next(rule for rule in rules["rules"] if str(rule["id"]) == "41")["scope"]
    _declared, undeclared = example_census(document["components"]["schemas"])
    assert len(undeclared) <= int(scope["undeclared_example_fields"])
    assert int(scope["title_max_length"]) == TITLE_MAX_LENGTH


def test_an_array_of_a_component_is_that_components_business(document: dict[str, Any]) -> None:
    """The third road into `_is_shape`, and the ratchet it un-inflated.

    A `$ref` is another component. So is a nullable branch holding one. So is
    **an array whose `items` is one** — and that road was missing, which put
    every ninja-synthesised `Paged<X>.items` into the undeclared backlog. Nobody
    can declare an example on those: `@paginate` builds the class at mount time
    by re-annotating `items`, and a pydantic subclass that re-annotates a field
    gets a fresh `FieldInfo`, so an example on `core.schemas.ListPage.items` is
    dropped and there is no third place to put one.

    A ratchet whose backlog contains entries nobody can remove had stopped being
    about anything, and rule 41's own scope had booked the fix twice as a raise
    it did not want to make. This asserts the fix rather than the number: no
    array-of-`$ref` field is in either half of the census.
    """
    schemas = document["components"]["schemas"]
    declared, undeclared = example_census(schemas)
    counted = set(declared) | set(undeclared)
    arrays = {
        f"{name}.{field}"
        for name, node in schemas.items()
        if isinstance(node, dict)
        for field, spec in (node.get("properties") or {}).items()
        if isinstance(spec, dict)
        and spec.get("type") == "array"
        and isinstance(spec.get("items"), dict)
        and "$ref" in spec["items"]
    }
    assert arrays, "no array-of-$ref field was found; this pass proves nothing"
    assert "PagedWidgetOut.items" in arrays
    assert not (arrays & counted), (
        "these array-of-component fields are still counted as scalars in the example "
        f"census: {sorted(arrays & counted)}"
    )


def test_the_documents_top_level_keys_are_the_declared_census(
    document: dict[str, Any],
) -> None:
    """Rule 41's `djb.E042`, driven from the test side as well as the check side.

    Set equality both ways against `openapi_top_level_keys` in `rules.yaml`. The
    check is the enforcement; this is the assertion that the census is about the
    live document and not about a list somebody once typed.
    """
    from apps.core.checks import declared_top_level_keys

    declared = declared_top_level_keys()
    assert declared, "rule 41 declares no top-level keys; djb.E042 is watching nothing"
    assert set(document) == set(declared)
    assert all(reason.strip() for reason in declared.values())


def test_servers_ships_empty_and_says_so(document: dict[str, Any]) -> None:
    """The deliberate absence, asserted rather than shipped silently.

    A template has no deploy URL. An invented one would be worse than nothing
    because a client would try it — so `servers` is `[]`, and the reason for that
    is recorded in `quality/rules.yaml` under rule 41 where a product cloning
    this tree will meet it. This is the assertion that reason points at.
    """
    from apps.core.checks import declared_top_level_keys

    assert document["servers"] == []
    assert "empty" in declared_top_level_keys()["servers"].lower()


def test_a_vanished_top_level_key_is_a_fault_too(document: dict[str, Any]) -> None:
    """The other direction, which the live mount can never demonstrate.

    The document the mount builds is always complete, so the arm that catches a
    DECLARED key going missing has no natural victim — it gets a planted one: the
    live document minus `servers`. Without this the branch is unreachable code
    that reads as covered.
    """
    from apps.core.checks import top_level_key_faults

    assert top_level_key_faults(document) == []

    without = {key: value for key, value in document.items() if key != "servers"}
    faults = top_level_key_faults(without)
    assert len(faults) == 1 and "'servers'" in faults[0] and "no longer carries" in faults[0]

    surplus = {**document, "x-canary-undeclared": {}}
    faults = top_level_key_faults(surplus)
    assert len(faults) == 1 and "x-canary-undeclared" in faults[0]
    assert "does not declare" in faults[0]


def test_a_declared_example_beats_the_synthesised_one(document: dict[str, Any]) -> None:
    """The seam, end to end: what a field declared is what the document shows."""
    organization = document["components"]["schemas"]["OrganizationOut"]
    assert organization["properties"]["slug"]["example"] == "northern-branch"
    assert organization["example"]["slug"] == "northern-branch"
    # And synthesis still covers everything nobody declared, so no field is bare.
    assert organization["example"]["id"]


def test_every_operation_appears_in_exactly_one_section(document: dict[str, Any]) -> None:
    """One operation, one place in the navigation.

    A renderer lists an operation under every tag it carries. `accounts` had a
    parent router tagged `accounts` over three tagged children, ninja
    accumulates a nested router's tags downward, and the result was all eleven
    of that app's operations printed twice — once in their own section and once
    under an umbrella heading that was a copy of the other three.

    The second half of the same finding is asserted here too: no tag is left
    declared with nothing under it, because an empty heading is a heading
    somebody clicks. That half has no house rule (rule 41 says so), which is
    exactly why it has a test.
    """
    carried: set[str] = set()
    for path, method, operation in operations(document):
        tags = operation.get("tags") or []
        assert len(tags) == 1, f"{method.upper()} {path} carries {tags}"
        carried.add(tags[0])
    declared = {tag["name"] for tag in document["tags"]}
    assert declared == carried, f"declared but carried by nothing: {sorted(declared - carried)}"


def test_every_tag_carries_a_display_name(document: dict[str, Any]) -> None:
    """A wire name is a slug a client turns into a namespace; a person reads the
    display name."""
    for tag in document["tags"]:
        assert tag.get("x-displayName"), f"tag {tag['name']!r} has no display name"


# --- refusals come off the registry -------------------------------------------


def test_every_operation_enumerates_at_least_one_refusal(document: dict[str, Any]) -> None:
    for path, method, operation in operations(document):
        refusals = [
            code
            for body in operation["responses"].values()
            for code in (body.get("x-refusal-codes") or ())
        ]
        assert refusals, f"{method.upper()} {path} documents no refusal at all"


def test_every_enumerated_code_is_in_the_registry(document: dict[str, Any]) -> None:
    """WA-1-3: the docs cannot teach a refusal the wire never speaks."""
    for path, method, operation in operations(document):
        for body in operation["responses"].values():
            for code in body.get("x-refusal-codes") or ():
                assert code in REFUSALS, f"{method.upper()} {path} documents unregistered {code!r}"


def test_a_refusal_response_carries_the_registrys_own_fact_and_remedies(
    document: dict[str, Any],
) -> None:
    body = document["paths"]["/api/v1/widgets/{widget_id}/"]["get"]["responses"]["404"]
    registered = REFUSALS["not_found"]
    assert registered.fact in body["description"]
    for remedy in registered.remedies:
        assert remedy.label in body["description"]
        assert remedy.destination in body["description"]


def test_the_refusal_body_is_a_component_with_the_registrys_codes(
    document: dict[str, Any],
) -> None:
    refusal = document["components"]["schemas"]["Refusal"]
    assert refusal["properties"]["code"]["enum"] == sorted(REFUSALS)
    assert refusal["required"] == ["detail", "code"]


def test_a_collection_route_does_not_claim_a_404_it_cannot_make(
    document: dict[str, Any],
) -> None:
    """A list that documented a 404 teaches a client to handle one that never comes.

    The derivation reads the door's shape: a route that names no row — no path
    parameter, no body carrying an id — cannot answer `not_found`. The one that
    can says so with `@refuses(...)`, which is the valve, and this test is what
    keeps the valve from being the default.

    **A `@paginate`d collection is the third case, and it is derived rather than
    listed** (ADR core-18). A `?cursor=` names a walk, a walk belongs to one
    tenant, and a cursor minted in another answers `not_found` like every other
    row that tenant cannot reach — so a paginated list documents a 404 it
    genuinely can make. Recognised here by the cursor parameter, off the same
    document, so the exemption cannot drift from the population: no route name
    is written down for it.
    """
    for path, method, operation in operations(document):
        if "{" in path or "requestBody" in operation:
            continue
        codes = {
            code
            for body in operation["responses"].values()
            for code in (body.get("x-refusal-codes") or ())
        }
        if "not_found" not in codes:
            continue
        if any(parameter["name"] == "cursor" for parameter in operation.get("parameters", ())):
            assert "invalid_cursor" in codes, (
                f"{method.upper()} {path} pages but does not document its cursor refusal"
            )
            continue
        assert path in {
            # Both address one row without naming it: the governing policy is
            # resolved from the acting hat, the connection from the stored state.
            "/api/v1/widgets/policies/governing/",
            "/api/v1/connections/oauth/callback/",
        }, f"{method.upper()} {path} documents a 404 it cannot make"


def test_every_paginated_list_documents_the_cursor_refusals(document: dict[str, Any]) -> None:
    """The census, closed both ways (ADR core-18; criterion 5's successor).

    Every operation that takes a `?cursor=` documents `invalid_cursor` and
    `not_found`, and no operation anywhere still declares `page` or `page_size`.
    Read off the exported document rather than off a list of route names, so an
    app that adds a list next week is covered without anybody editing this — and
    so the hard cut is checked where a client actually reads the contract.
    """
    paginated = [
        (path, method, operation)
        for path, method, operation in operations(document)
        if any(parameter["name"] == "cursor" for parameter in operation.get("parameters", ()))
    ]
    assert paginated, "no operation takes a cursor — the census found nothing to check"

    for path, method, operation in operations(document):
        names = {parameter["name"] for parameter in operation.get("parameters", ())}
        assert not names & {"page", "page_size"}, (
            f"{method.upper()} {path} still declares a retired pagination parameter"
        )

    for path, method, operation in paginated:
        codes = {
            code
            for body in operation["responses"].values()
            for code in (body.get("x-refusal-codes") or ())
        }
        assert {"invalid_cursor", "not_found"} <= codes, f"{method.upper()} {path}"


def test_refuses_declares_and_replaces(document: dict[str, Any]) -> None:
    @refuses("conflict", "not_found")
    def route() -> None: ...

    assert declared_refusals(route) == ("conflict", "not_found")

    def undeclared() -> None: ...

    assert declared_refusals(undeclared) is None


def test_refuses_is_additive_over_the_doors_own_refusals() -> None:
    """What a route says about ITSELF cannot omit what the door does.

    `@refuses(...)` corrects the shape derivation, which is a claim about what
    this route's services do. It is not a claim about the addressing middleware,
    the token ceiling or the throttle — those run above the view, on every
    request, and a route author cannot decline them by not mentioning them.
    """
    declared = ("conflict", "not_found")

    composed = with_door_level(declared, authenticated=True)

    # Declared first, so what the route says about itself reads ahead of what
    # the mount adds — and nothing the route declared is dropped.
    assert composed[: len(declared)] == declared
    assert set(DOOR_LEVEL_REFUSALS) <= set(composed)

    # An UNAUTHENTICATED operation earns only the throttle: it presented no
    # credential, so there is no addressing header to dishonour. Getting this
    # wrong would document a refusal the two `auth=None` routes can never make.
    open_door = with_door_level(declared, authenticated=False)
    assert "rate_limited" in open_door
    assert "addressing_header_not_honoured" not in open_door

    # And `insufficient_scope` is NEVER added by the door, at either kind. It is
    # earned by being reachable with a ceilinged token, which is not the same
    # fact as being authenticated — a session-only route has no ceiling to fall
    # short of, and `POST /api/v1/tokens/` writes `@refuses(...)` precisely to
    # suppress it. The first version of this set included it and silently
    # re-added the code that route had removed on purpose.
    assert "insufficient_scope" not in composed
    assert "insufficient_scope" not in open_door


def test_every_authenticated_operation_publishes_the_addressing_refusal(
    document: dict[str, Any],
) -> None:
    """A gap the census once missed, held closed at the document.

    All eight `@refuses(...)` routes answer `403 addressing_header_not_honoured`
    and published contracts that did not say so, because declaring replaced the
    derivation wholesale — and rule 41's census could not see it, since it reads
    the published document and the document was internally consistent and wrong.

    Derived from the document rather than from a list of the eight: a ninth
    route that grows a `@refuses(...)` tomorrow is in this assertion tomorrow.
    The two exceptions are named because they are the two `auth=None` routes,
    and naming them is what stops the assertion being loosened to hide a third.
    """
    unauthenticated = {
        "POST /api/v1/auth/realm/",
        "POST /api/v1/connections/{connection_id}/webhook/",
    }
    missing: list[str] = []
    checked = 0
    for path, operations in document["paths"].items():
        for method, operation in operations.items():
            if not isinstance(operation, dict) or "responses" not in operation:
                continue
            codes: set[str] = set()
            for response in operation["responses"].values():
                for code in (response or {}).get("x-refusal-codes") or []:
                    codes.add(code)
            if not codes:
                continue
            where = f"{method.upper()} {path}"
            if where in unauthenticated:
                assert "addressing_header_not_honoured" not in codes, (
                    f"{where} takes no credential, so it can never dishonour an "
                    "addressing header; documenting one teaches a caller to handle "
                    "a refusal that cannot arrive."
                )
                continue
            checked += 1
            if "addressing_header_not_honoured" not in codes:
                missing.append(where)

    assert checked, "no authenticated operation was found; this census proves nothing"
    assert missing == [], (
        f"these authenticated operations do not publish the addressing refusal "
        f"their own middleware can answer with: {missing}"
    )


# --- the prose about permissions, against the wire ------------------------------


def _privileged_role_words() -> set[str]:
    """What this tree calls privileged, asked of the model rather than listed.

    `Membership.is_privileged` is the declaration; every role value is put to it
    and the ones that come back true are the words a docstring spells. A list
    written here would be right today and wrong the morning after a fourth role.
    """
    return {value for value in Membership.Role.values if Membership(role=value).is_privileged}


#: The shape of a sentence that tells a caller *they* are the one being refused.
#: Deliberately NOT the tell rule 41's census uses — that one keys on the refusal
#: CODE, and this is the belt for the wordings it cannot see ("Only an owner or
#: an administrator of the tenant may call this", which names no code at all).
_PERSONAL_REFUSAL = re.compile(
    r"\b(you are not|you do not|you must|you cannot|you may not|only an?|unless you)\b",
    re.IGNORECASE,
)


def _promises_a_role(description: str) -> bool:
    """Whether this prose tells the reader a privileged role is required.

    Chunk by chunk — a bullet or a paragraph — because both halves have to meet
    in one of them. "Reading is not role-gated: ... registering and pausing are
    the owner-or-administrator acts" names a privileged role and refuses the
    reader nothing, and reading those two sentences as a promise would make the
    only way to explain a permission be to stop explaining it.
    """
    words = _privileged_role_words()
    chunks: list[str] = []
    current: list[str] = []
    for line in description.splitlines():
        stripped = line.strip()
        if stripped.startswith("* ") or not stripped:
            if current:
                chunks.append(" ".join(current))
            current = [stripped] if stripped.startswith("* ") else []
            continue
        current.append(stripped)
    if current:
        chunks.append(" ".join(current))
    for chunk in chunks:
        if not _PERSONAL_REFUSAL.search(chunk):
            continue
        # `admin` reaches `administrator`; `owner` reaches `owners`. A docstring
        # writes English, not choice values.
        if any(re.search(rf"\b{re.escape(w)}[a-z]*\b", chunk, re.IGNORECASE) for w in words):
            return True
    return False


@pytest.mark.django_db
def test_a_plain_member_meets_what_every_published_read_promises(
    client: Client, member: User, tenant: Tenant, document: dict[str, Any]
) -> None:
    """A drive generalized off the events tag to the whole document.

    The finding it exists for: "403 forbidden — you are not an owner or an
    administrator of the tenant" had been pasted onto reads that check no role,
    because `derived_refusals` gives every authenticated route a `forbidden` and
    somebody transcribed that superset as though it were a decision. Nothing
    caught it — the code is registered, the code IS reachable when no tenant
    resolves, the document renders, the tests pass. The only wrong thing was the
    sentence, and a sentence is what nothing was reading.

    So this drives the document instead of reading it. Every GET it publishes,
    as a plain member of the tenant, and the wire is compared with the prose:

    * **200** — the member got in, so the prose may not claim a role stopped
      anybody.
    * **403** at the authorization refusal — a role really did stop them, so the
      prose must say so.
    * anything else (a 404 for an id nothing seeded, a 400 for a parameter this
      route wanted) is INCONCLUSIVE, and is counted rather than quietly passed:
      a drive whose conclusive half fell to nothing would read exactly like a
      clean one, which is the failure mode this drive exists to catch in the
      prose itself.

    The population is derived from the live document, so a read added in any app
    tomorrow is in this test the moment it is mounted, and rule 41's census is
    the other half of the pair: it reads the CODE the prose names and this reads
    the WORDS, which is why it catches a promise the census's tell never sees.

    **WHICH ARM IS LIVE, said out loud.** Measured 2026-08-25: twenty reads
    answer 200 and NONE answers 403 — no published read in this tree is
    role-gated today. So the second arm
    is carried for the read that grows one, and today it proves nothing. What
    keeps the FIRST arm from going quiet — an empty role vocabulary makes
    `_promises_a_role` answer False about everything — is the test below, which
    plants the false line and the corrected one and asserts the predicate can
    still tell them apart.

    **AND THE TWELVE IT CANNOT REACH.** A read that addresses a row by id
    answers 404 here, because nothing seeds a recipient, a template or a
    connection for it — this file belongs to `core`, and seeding every app's
    rows from it would be `core` importing the whole tree to ask one question.
    Those twelve are counted and named in the failure message rather than
    silently passed, and they are exactly why rule 41's census exists beside
    this: the census reached `list_preferences_route`'s false promise from the
    source, and this drive would have answered 404 and shrugged.
    """
    client.force_login(member)
    reads = [
        (path, operation)
        for path, item in document["paths"].items()
        for method, operation in item.items()
        if method == "get"
    ]
    assert reads, "the document publishes no reads at all"

    stand_in = "00000000-0000-4000-8000-000000000000"
    conclusive = 0
    inconclusive: list[str] = []
    for path, operation in sorted(reads):
        url = re.sub(r"\{[^}]+\}", stand_in, path)
        response = client.get(url)
        description = operation.get("description") or ""
        if response.status_code == 200:
            conclusive += 1
            assert not _promises_a_role(description), (
                f"GET {path} answered a plain member 200 and its prose tells them a "
                "privileged role is required. The sentence reads as a permission wall "
                "and there is none"
            )
            continue
        if response.status_code == 403 and response.json().get("code") == Forbidden.code:
            conclusive += 1
            assert _promises_a_role(description), (
                f"GET {path} refused a plain member with {Forbidden.code!r} and its prose "
                "never says a role is what stopped them"
            )
            continue
        inconclusive.append(f"{path} -> {response.status_code}")

    # Measured 2026-08-25: 20 of the 32 published reads answer a plain
    # member conclusively; the other twelve address a row by an id nothing
    # seeded here and answer 404, or want a query parameter and answer 422.
    # A floor, not a pin — a read added tomorrow raises it, and a drive that
    # quietly stopped reaching the doors falls through it.
    assert conclusive >= 20, f"only {conclusive} reads answered conclusively: {inconclusive}"


def test_the_role_promise_predicate_tells_the_false_line_from_the_corrected_one() -> None:
    """The drive's own canary: the predicate above, planted both ways.

    Without this, the whole drive degrades silently. `_promises_a_role` answers
    False about every string the moment `_privileged_role_words()` comes back
    empty — a role renamed, `is_privileged` rewritten to read a flag — and
    twenty routes would go on passing an assertion that had stopped asking
    anything. The three strings are the real ones: the false sentence found in
    the wild, the corrected sentence written in its place, and the wording
    rule 41's census cannot see at all, which is the whole reason this belt
    exists beside it.
    """
    assert _privileged_role_words(), "the role vocabulary is empty; the drive above is blind"

    pasted = (
        "Refusals you can get here:\n\n"
        "* `403 forbidden` — you are not an owner or an administrator of the\n"
        "  tenant, or the request resolved no tenant.\n"
    )
    assert _promises_a_role(pasted)

    corrected = (
        "Refusals you can get here:\n\n"
        "* `403 insufficient_scope` — the token you sent does not carry the scope\n"
        "  this read needs. Reading is not role-gated: any member of the tenant may\n"
        "  see where its events go. Registering, updating, pausing, resuming and\n"
        "  re-keying an endpoint are the owner-or-administrator acts.\n"
    )
    assert not _promises_a_role(corrected), (
        "explaining which acts DO need a role must not read as a promise that this "
        "one does — otherwise the only way to pass is to explain nothing"
    )

    # Names no refusal code, so the census's tell never sees it. This one does.
    assert _promises_a_role(
        "**Only an owner or an administrator of the tenant may call this.** It is the\n"
        "strictest permission in this API.\n"
    )


# --- the headers, documented once ---------------------------------------------


def test_the_acting_headers_are_documented_on_authenticated_operations(
    document: dict[str, Any],
) -> None:
    operation = document["paths"]["/api/v1/widgets/"]["get"]
    names = {p["name"] for p in operation["parameters"] if p["in"] == "header"}
    assert {TENANT_HEADER, ORG_HEADER} <= names
    for parameter in operation["parameters"]:
        if parameter["name"] == ORG_HEADER:
            assert "downwards" in parameter["description"]


def test_a_write_documents_the_idempotency_key_and_the_replay_header(
    document: dict[str, Any],
) -> None:
    operation = document["paths"]["/api/v1/widgets/"]["post"]
    names = {p["name"] for p in operation["parameters"] if p["in"] == "header"}
    assert IDEMPOTENCY_HEADER in names
    assert REPLAYED_HEADER in operation["responses"]["201"]["headers"]


def test_a_read_does_not_claim_to_take_an_idempotency_key(document: dict[str, Any]) -> None:
    operation = document["paths"]["/api/v1/widgets/"]["get"]
    names = {p["name"] for p in operation["parameters"] if p["in"] == "header"}
    assert IDEMPOTENCY_HEADER not in names


# --- the overview, the tags and the examples ----------------------------------


def test_the_document_opens_with_the_overview(document: dict[str, Any]) -> None:
    description = document["info"]["description"]
    assert description == overview()
    for landmark in ("POST /tokens/", "X-Org", "Idempotency-Key", "/mcp", "/api/v1/"):
        assert landmark in description


def test_the_versioning_promise_says_when_it_starts(document: dict[str, Any]) -> None:
    """The guide may not contradict the changelog.

    `## Versioning` promises that within a version a field is never removed from
    a response — and `/v1/` broke exactly that once, deliberately, when list
    responses moved from page numbers to cursors, on the empty-consumer-register
    licence. The sentence is right as the *go-forward*
    promise and was wrong as a statement about the past, which is the cheapest
    kind of documentation defect to leave lying around: nobody notices until an
    integrator reads both pages and concludes one of them is lying.

    Asserted as a landmark rather than as a wording match, for the reason the
    overview test beside it gives: the prose is review's and the *structure* is
    the checkable half. What this pins is that the promise carries a date, that
    the date sits inside `## Versioning` and not somewhere a reader will miss
    it, and that the exception it dates is the one that actually happened.
    """
    description = document["info"]["description"]
    section = description.split("## Versioning", 1)[1]
    assert "never removed from a response" in section
    assert "2026-08-24" in section, "the promise is undated, so it reads as retroactive"
    assert "cursor" in section.lower(), "the dated footnote does not name what it excepts"


def test_the_overview_is_a_shelf_of_guides(document: dict[str, Any]) -> None:
    """The guides half of the 2026-08-24 ruling, as far as it can be asserted.

    What is checkable is that the overview is SECTIONED — each concept its own
    `##` heading, so a renderer that builds a navigation out of
    `info.description` shows them as separate entries — and that the contents
    line links each one by the anchor its heading generates. Whether they are
    good guides is review's, and rule 41 says so.
    """
    description = document["info"]["description"]
    headings = [line[3:].strip() for line in description.splitlines() if line.startswith("## ")]
    assert len(headings) >= 6, headings
    for heading in headings:
        anchor = heading.lower().replace(" ", "-")
        assert f"(#{anchor})" in description, f"{heading!r} is not linked from the contents"
    # Every heading is a guide, never an operation: a section named for one
    # route would be a worse copy of that route's own docstring.
    assert not any(heading.startswith(("GET ", "POST ", "/api")) for heading in headings)


# --- the five guides -----------------------------------------------------------
#
# THE PATTERN IS THE ONE ABOVE, AND IT IS DELIBERATE: structure is pinned and
# prose is free. A test that matched sentences would fail every time somebody
# improved a paragraph, so nobody would improve a paragraph. What is asserted
# here is that each guide EXISTS on the shelf, that it is reachable from the
# contents line, and that the facts inside it which are true somewhere else in
# the tree agree with that somewhere else — the tolerance, the header names, the
# retry schedule, the machine door's path, the scope families. Whether a guide
# is a *good* guide is review's, and rule 41 says so.

#: The five guides on the shelf, by heading. Written down because
#: the ruling is that these five exist — a shelf that lost one would otherwise
#: still be "a shelf of guides" and pass the test above.
GUIDE_HEADINGS = (
    "Quickstart",
    "Authentication",
    "Connecting an agent",
    "Consuming webhooks",
    "Changelog and deprecation policy",
)

#: How a scope family is listed in the two-planes bullets. Anchored at the start
#: of a line so a family named inside a sentence — `POST /auth/realm` sits in
#: one of the bullets — is not read as a second entry.
PLANE_ENTRY = re.compile(r"^\* `([a-z][a-z0-9_-]*)` — ", re.MULTILINE)


def overview_section(description: str, heading: str) -> str:
    """One `## heading` section of the overview, up to the next `## ` heading."""
    marker = f"\n## {heading}\n"
    assert marker in description, f"the overview has no {heading!r} section"
    body = description.split(marker, 1)[1]
    return body.split("\n## ", 1)[0]


def flat(text: str) -> str:
    """The same prose with every run of whitespace collapsed to one space.

    A landmark is a phrase, and a phrase in a hard-wrapped paragraph has a
    newline in the middle of it wherever the line happened to end. Matching on
    the wrapped form would make every one of these tests a hostage to
    re-flowing a paragraph — which is the opposite of "structure pinned, prose
    free": the wording would be free to change and the LINE BREAKS would not.
    """
    return " ".join(text.split())


def test_every_guide_is_on_the_shelf_and_reachable(document: dict[str, Any]) -> None:
    """The five guides, each a `##` section and each linked from the contents.

    The shelf test above proves the overview is sectioned; this one proves that
    these particular five are the sections, because "sectioned" is a property a
    shelf keeps after somebody deletes the webhook guide.
    """
    description = document["info"]["description"]
    headings = [line[3:].strip() for line in description.splitlines() if line.startswith("## ")]
    for guide in GUIDE_HEADINGS:
        assert guide in headings, f"{guide!r} is not a section of the overview"
        anchor = guide.lower().replace(" ", "-")
        assert f"(#{anchor})" in description, f"{guide!r} is not linked from the contents"


#: A route named in the guides, as a reader meets it: backticked, a verb and a
#: path. The path is relative to the version segment — `POST /tokens/` — because
#: an app never writes the version segment and neither does a guide.
#: Read off the UNWRAPPED prose (see `flat`): a hard-wrapped paragraph puts a
#: newline inside `GET /dead-letters/` as readily as between two sentences, and a
#: pattern that missed those would check only the routes that happened to fit on
#: one line.
OVERVIEW_ROUTE = re.compile(r"`(GET|POST|PUT|PATCH|DELETE) (/[^`\s]+)`")


def wildcarded(path: str) -> str:
    """A path with its parameter names blanked, so `{id}` matches `{token_id}`."""
    return re.sub(r"\{[^}]*\}", "{}", path)


def test_every_route_the_guides_name_is_a_live_route(document: dict[str, Any]) -> None:
    """A guide that teaches a URL the mount does not serve is worse than no guide.

    Found by driving the quickstart against a running server: step 1
    said `POST /auth/realm`, the route is `/auth/realm/`, and the spelling
    without the slash is one this tree DELETED — so the very first instruction a
    stranger follows answered a refusal. Nothing caught it, because every test
    over the overview read it as prose.

    So it is read as a set of claims instead: every backticked verb-and-path in
    the guides is looked up in the document, with parameter names blanked so
    `{id}` and `{token_id}` are the same slot. The version segment is derived
    from the document rather than typed, because `config/urls.py` owns it and a
    guide that wrote it down would be the second place it lives.
    """
    paths = sorted(document["paths"])
    assert paths, "the document serves nothing — this test would pass vacuously"
    prefix = "/" + "/".join(paths[0].strip("/").split("/")[:2]) + "/"

    live = {(method.upper(), wildcarded(path)) for path, method, _ in operations(document)}
    named = OVERVIEW_ROUTE.findall(flat(document["info"]["description"]))
    assert len(named) >= 12, f"the guides name almost no routes: {named}"

    for method, path in named:
        full = path if path.startswith(prefix) else prefix + path.lstrip("/")
        assert (method, wildcarded(full)) in live, (
            f"the guides teach `{method} {path}`, which this deployment does not serve"
        )


def test_the_quickstart_is_the_first_hour_and_teaches_a_narrow_token(
    document: dict[str, Any],
) -> None:
    """Guide 1. Sign in, mint a SCOPED token, read a list, follow an id.

    The one fact worth pinning beyond the four steps is the pair that makes a
    narrow token cheap to ask for: that the write scope covers the read, and
    that a scope only ever narrows. A quickstart that skipped them is a
    quickstart that teaches `["*"]`.
    """
    section = flat(overview_section(document["info"]["description"], "Quickstart"))
    assert "/accounts/login/" in section, "step 1 does not say where to sign in"
    assert "POST /tokens/" in section, "step 2 does not name the mint"
    assert "scopes" in section, "step 2 does not ask for a scope list"
    assert "narrowest" in section, "the quickstart does not teach asking narrow"
    assert "write scope includes the read" in section
    assert "effective_scopes" in section, "nothing tells the reader to check what stuck"
    assert "next_cursor" in section, "step 3 does not show the list envelope"
    assert "`id`" in section, "step 4 does not follow an id"
    # It is FIRST: an agent embedding this overview reads it as the opening
    # section, and `/llms.txt`'s own nesting test depends on the same ordering.
    headings = [
        line[3:].strip()
        for line in document["info"]["description"].splitlines()
        if line.startswith("## ")
    ]
    assert headings[0] == "Quickstart", headings


def test_the_webhook_guide_states_the_schedule_the_dispatcher_actually_keeps() -> None:
    """Guide 2, pinned to the constants that decide it — from the TEST side only.

    `apps/core/api/docs.py` sits below `apps/events` and may not import it
    (house rule 7, and the note at the foot of that module about which
    direction the arrows point). So the prose states the numbers and this test
    is what holds them to the dispatch workflow's own retry policy: change the
    policy and the guide is wrong here, in this file, rather than in front of a
    subscriber six weeks later.
    """
    from apps.events.activities import SIGNATURE_V2_HEADER
    from apps.events.receivers import SIGNATURE_V2_TOLERANCE
    from apps.events.workflows import (
        DELIVERY_ATTEMPT_TIMEOUT,
        DELIVERY_DEADLINE,
        DELIVERY_RETRY,
    )

    section = flat(overview_section(overview(), "Consuming webhooks"))

    assert SIGNATURE_V2_HEADER in section
    assert f"**{int(SIGNATURE_V2_TOLERANCE.total_seconds() // 60)} minutes** of your own clock" in (
        section
    )
    assert f"**{int(DELIVERY_ATTEMPT_TIMEOUT.total_seconds())} seconds** to answer" in section
    assert f"**{DELIVERY_RETRY.maximum_attempts} attempts**" in section

    # The policy types both intervals as optional; a dispatch policy that had
    # dropped one is a finding of its own, so it is asserted rather than coerced.
    first, longest = DELIVERY_RETRY.initial_interval, DELIVERY_RETRY.maximum_interval
    assert first is not None and longest is not None, "the dispatch policy names no intervals"
    assert f"**{int(first.total_seconds())} seconds** later" in section, (
        "the first retry interval does not match the dispatch policy"
    )
    assert f"**{int(longest.total_seconds() // 60)} minutes** between" in section
    assert f"**{int(DELIVERY_DEADLINE.total_seconds() // 3600)} hour**" in section

    # The seconds inside the worked verifier are the same tolerance, spelled the
    # way a reader would paste it.
    assert f"> {int(SIGNATURE_V2_TOLERANCE.total_seconds())}" in section


def test_the_webhook_guide_teaches_both_schemes_and_teaches_only_our_outbound() -> None:
    """Guide 2, the other half: both verifiers, idempotency, dead letters — and
    the boundary.

    Inbound freshness — a timestamp check on webhooks somebody sends US — has
    not landed. A guide that promised it would be promising on behalf of a rung
    that does not exist, so the section is asserted to be about deliveries we
    send: it registers an endpoint, it verifies what arrives, it replays what we
    gave up on.
    """
    from apps.events.activities import SIGNATURE_PREFIX

    section = flat(overview_section(overview(), "Consuming webhooks"))

    assert "X-Signature-V2" in section and "X-Signature: " in section
    assert section.count("hmac.compare_digest") == 2, "one of the two verifiers is not shown"
    assert SIGNATURE_PREFIX in section, "the v1 prefix a subscriber compares against is missing"
    assert "hash the bytes you received" in section.lower()

    assert "X-Event-Id" in section
    assert "stable across retries and replays" in section
    assert "dead-letter" in section.lower()
    assert "/dead-letters/" in section
    assert "POST /webhook-endpoints/" in section
    assert "GET /event-types/" in section, "the guide points at a retired catalogue path"
    assert "Testing locally" in section

    # The boundary: this guide is about what we SEND. The inbound receiver has
    # its own freshness rung and this must not speak for it.
    lowered = section.lower()
    assert "webhooks we send you" in lowered
    for promise in ("send us", "sending us", "inbound webhook"):
        assert promise not in lowered, f"the outbound guide promises something about {promise!r}"


def test_the_authentication_guide_splits_every_family_into_exactly_one_plane() -> None:
    """Guide 3, and the closed question: the two planes ARE the scope families.

    Set-consistency against the live vocabulary rather than against a list kept
    here — so a family added by any app next week fails this test **by name**,
    which is the whole point. A guide that quietly stopped covering a section of
    the API would otherwise go on reading as if it covered all of them.
    """
    from apps.core.api.scopes import families

    section = overview_section(overview(), "Authentication")
    assert "### The two planes" in section

    planes = section.split("### The two planes", 1)[1]
    prose = flat(planes)
    assert "**The everyday plane**" in planes and "**The administrative plane**" in planes
    everyday, administrative = planes.split("**The administrative plane**", 1)
    everyday = everyday.split("**The everyday plane**", 1)[1]

    named_everyday = set(PLANE_ENTRY.findall(everyday))
    named_administrative = set(PLANE_ENTRY.findall(administrative))
    live = set(families())

    assert live, "no family exists — this test would pass vacuously"
    assert not named_everyday & named_administrative, (
        f"placed in both planes: {sorted(named_everyday & named_administrative)}"
    )
    assert named_everyday | named_administrative == live, (
        f"in no plane: {sorted(live - named_everyday - named_administrative)}; "
        f"named but not a family: {sorted((named_everyday | named_administrative) - live)}"
    )
    assert named_everyday and named_administrative, "one of the two planes is empty"

    # Roles are the split, and the guide has to say so — a reader who thinks the
    # token decides will mint a wider one and still be refused.
    assert "decided by your role" in prose


def test_the_changelog_guide_absorbs_the_versioning_promise(
    document: dict[str, Any],
) -> None:
    """Guide 4: the policy, and the promise it must not contradict.

    The dated footnote is asserted where it has always been asserted — inside
    a heading named Versioning — and that heading now lives INSIDE this guide
    rather than beside it, because a changelog policy and a versioning promise
    printed as two sibling sections is exactly how a document comes to say two
    things about one subject.
    """
    raw = overview_section(document["info"]["description"], "Changelog and deprecation policy")
    assert "### Versioning" in raw, "the versioning promise was not absorbed"
    section = flat(raw)
    assert "openapi.json" in section, "nothing tells a reader how to watch for changes"
    assert "/api/v1/" in section
    assert "/v2/" in section
    assert "2026-08-24" in section, "the dated exception did not come with it"
    assert "never removed from a response" in section
    # The policy half: what may appear without warning, said as an instruction.
    assert "without notice" in section
    assert "ignores fields it does not recognise" in section


def test_the_agent_guide_points_at_the_machine_door_and_explains_refuse_not_hide() -> None:
    """Guide 5, with the door's path pinned to the door's own constant.

    `/mcp` is imported here and not in `docs.py`: the arrow between those two
    modules points one way and the module says why at length. A test is above
    both of them and may read either.
    """
    from apps.core.mcp import MCP_PATH

    section = flat(overview_section(overview(), "Connecting an agent"))

    assert MCP_PATH in section, "the guide does not name the machine door"
    assert "/llms.txt" in section, "the map is not offered"
    assert "list_widgets" in section, "there is no worked example"
    assert "insufficient_scope" in section
    assert "does not shrink" in section, "refuse-not-hide is not explained"
    assert "no agent of its own" in section, "the posture is not stated"


def test_no_guide_leaked_into_an_operations_description(document: dict[str, Any]) -> None:
    """Rule 41's machinery, from the guides' side: guides live in the overview.

    An operation's prose is its own docstring and nothing else. A section
    heading appearing in one would mean a guide had been pasted into a route —
    the second copy of the contract this whole module exists to prevent.
    """
    for path, method, operation in operations(document):
        description = str(operation.get("description", ""))
        offenders = [line for line in description.splitlines() if line.startswith("## ")]
        assert not offenders, f"{method.upper()} {path} carries overview headings: {offenders}"
        for guide in GUIDE_HEADINGS:
            assert f"## {guide}" not in description, f"{method.upper()} {path} embeds {guide!r}"


def test_the_overview_module_names_nothing_above_its_own_layer() -> None:
    """The guides quote `apps.events` and `apps.core.mcp`; `docs.py` must not.

    Every fact in the guides that some other module owns is pinned in THIS file,
    where an import upward is legal. `apps/core/api/docs.py` is below both and
    import-linter holds the layer — this asserts the same thing at the one place
    a guide-writing rung would be tempted to break it, so the failure names the
    reason instead of naming a contract.
    """
    import ast

    from apps.core.api import docs as docs_module

    tree = ast.parse(Path(docs_module.__file__).read_text())
    named: list[str] = []
    for node in tree.body:  # module scope ONLY — a deferred read is the fix
        if isinstance(node, ast.ImportFrom):
            named.append(node.module or "")
        elif isinstance(node, ast.Import):
            named.extend(alias.name for alias in node.names)
    above = [
        module
        for module in named
        if module.startswith(("apps.", "config."))
        and not module.startswith(("apps.core.exceptions", "apps.core.idempotency"))
        and not module.startswith("apps.core.middleware")
    ]
    assert above == [], f"apps/core/api/docs.py imports upward at module scope: {above}"


def test_every_tag_an_operation_carries_is_described(document: dict[str, Any]) -> None:
    described = {tag["name"]: tag.get("description", "") for tag in document["tags"]}
    for path, method, operation in operations(document):
        for tag in operation.get("tags") or []:
            assert described.get(tag), f"{method.upper()} {path} carries undescribed tag {tag!r}"


def test_every_schema_carries_an_example(document: dict[str, Any]) -> None:
    for name, schema in document["components"]["schemas"].items():
        assert "example" in schema, f"schema {name} has no example"


def test_an_example_is_shaped_like_the_schema_it_came_from(document: dict[str, Any]) -> None:
    widget = document["components"]["schemas"]["WidgetOut"]
    assert set(widget["example"]) == set(widget["properties"])


def test_a_self_referential_schema_does_not_loop() -> None:
    """The recursion guard: a node that points at its own kind stops at `null`."""
    components = {
        "Node": {
            "type": "object",
            "properties": {"parent": {"$ref": "#/components/schemas/Node"}},
        }
    }
    assert example_for(components["Node"], components, seen=frozenset({"Node"})) == {"parent": None}


# --- one docstring, two doors -------------------------------------------------


def test_every_mcp_twin_renders_its_rest_routes_own_words() -> None:
    """WA-1-2: a capability is explained once, or the doors have begun to drift.

    Read out of the two live registries, not out of a table: a route added to
    any app is in scope the moment the mount discovers it.
    """
    from apps.core.checks import _VERB_TOOLS, _bound_operations, _twin_tools

    tools = _twin_tools()
    compared = 0
    for _prefix, operation in _bound_operations():
        view = operation.view_func
        url_name = str(operation.url_name or "")
        noun, _, verb = url_name.rpartition("-")
        candidates = [t.format(noun=noun) for t in _VERB_TOOLS.get(verb, ())] or [
            f"{verb}_{noun}",
            f"{noun}_{verb}",
        ]
        for name in candidates:
            tool = tools.get(name)
            if tool is None:
                continue
            assert str(tool.description or "") == contract_of(view), (
                f"MCP tool {name!r} and REST route {url_name!r} describe one capability "
                "with two texts"
            )
            compared += 1
            break
    # The floor: a test that compared nothing would pass for the wrong reason.
    assert compared >= 30, f"only {compared} twin pairs compared — the pairing has come apart"


# --- an unmatched path under the API answers in JSON ---------------------------


@pytest.mark.django_db
def test_an_unmatched_path_under_the_api_answers_json(client: Client) -> None:
    response = client.get("/api/v1/nope")
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/json")
    body = response.json()
    assert body["code"] == "not_found"
    assert body["detail"]
    assert body["remedies"]


@pytest.mark.django_db
def test_the_json_404_covers_a_deep_path_and_every_verb(client: Client) -> None:
    for method, path in (
        ("get", "/api/v1/widgets/nope/deeper/still"),
        ("post", "/api/v1/nope"),
        ("delete", "/api/v1/nope"),
        ("patch", "/api/v1/nope"),
    ):
        response = getattr(client, method)(path)
        assert response.status_code == 404
        assert response["Content-Type"].startswith("application/json")
        assert response.json()["code"] == "not_found"


@pytest.mark.django_db
def test_a_registered_route_still_answers_for_itself(client: Client) -> None:
    """The catch-all is mounted after the API and can shadow nothing."""
    assert client.get("/api/v1/docs").status_code == 200
    unauthorized = client.get("/api/v1/widgets/")
    assert unauthorized.status_code == 401
    assert unauthorized["Content-Type"].startswith("application/json")


@pytest.mark.django_db
def test_outside_the_api_django_still_answers_for_itself(client: Client) -> None:
    """The JSON 404 is the API's, not the site's — a product's own 404 page stands."""
    response = client.get("/definitely-not-the-api")
    assert response.status_code == 404
    assert not response["Content-Type"].startswith("application/json")


# --- the two doors' modules pull at each other, and must not tie -------------


@pytest.mark.parametrize("module", ["apps.core.mcp", "apps.core.api.docs", "config.api"])
def test_the_door_modules_import_in_any_order(module: str) -> None:
    """Neither door's module may need the other to be finished first.

    House rule 41 pulls these two toward each other from both sides:
    `apps/core/mcp.py` imports `contract_of` from `apps/core/api/docs.py` so a
    tool renders its REST twin's docstring, and `docs.py` wants `MCP_PATH` so
    `/llms.txt` can name the machine door. Both at module scope is a cycle that
    **cannot be satisfied in either direction** — whichever of the two Python
    reaches first is the one left half-initialised when the other asks it for a
    name.

    It reached main once, and how it got there is the point: one rung added the
    import to `mcp.py`, another added the one to `docs.py`, each against a
    baseline where the other did not exist. Both gates were green and the MERGE
    of the two would not import at all. A test inside an already-running process
    cannot see this — the modules are in `sys.modules` by then — so each entry
    point is driven in an interpreter of its own.
    """
    proc = subprocess.run(
        [sys.executable, "-c", f"import django; django.setup(); import {module}"],
        capture_output=True,
        text=True,
        env={**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.test"},
        cwd=str(settings.BASE_DIR),
        check=False,
    )
    assert proc.returncode == 0, (
        f"importing {module} first fails:\n{proc.stdout}\n{proc.stderr[-2000:]}"
    )
