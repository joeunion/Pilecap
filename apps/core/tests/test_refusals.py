# census: cross-app population=apps/*/api.py,apps/*/mcp.py for HttpError and refusal dicts
"""The refusal registry: every code declared, once, with a boundary and a remedy.

A `code` is the half of a refusal a client branches on and an audit row is
queried by — a published contract that used to be a string somebody typed. The
registry makes it a declaration, and `DomainError.__init_subclass__` makes the
declaration mandatory **at import**, which is the same moment `@service` and the
app registry decide: a refusal that is only checked when it is first raised is
checked in production, on the unhappy path.

The tests below say the four things that make that worth having:

1. an unregistered code cannot become a class;
2. `code=` is gone from the constructors — a refusal's code is its class's, not
   its caller's;
3. every registered refusal carries a boundary from the closed set and a remedy
   somebody can act on;
4. the registry has exactly one writer, and it is not the dict.

The next section is **the door audit**, the registry check's other half. A registry of every
code the product can refuse with is worth nothing if a door quietly publishes a
code beside it, so the doors are scanned: every `HttpError(` a door raises is a
status and a message, and no door builds a body with a `code` key. There are
exactly two translators, `config/api.py` and `config/mcp.py`, and both read the
code off a registered refusal.

The last section is **the layer in front of the doors**. That work found and
declared one hole: `apps/core/idempotency.py` is a middleware, it answers before
any door is reached, and it published two codes (`idempotency_key_reuse`,
`in_progress`) that the registry had never heard of. Both are registered now, at
`boundary="door"`, and the question is kept closed the way the door one is: the
middleware's emittable codes are read back off its own call sites and held
against `EMITTABLE` and the registry, so a third code cannot arrive by being
typed.
"""

from __future__ import annotations

import ast
import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from apps.core import idempotency
from apps.core.exceptions import (
    BOUNDARIES,
    REFUSALS,
    Conflict,
    DomainError,
    Forbidden,
    Invalid,
    NotFound,
    RateLimited,
    Refusal,
    Remedy,
    refusal_for,
    refusal_message,
    register_refusal,
    wire_refusal,
)
from apps.core.tests.tree_census import source_tree

# The vocabulary the template ships with. A product adds to this; nothing
# removes from it, because every one of the six is raised somewhere in `apps/`
# and `config/api.py` maps five of them to a status code.
#: The five class codes the vocabulary ships with. The sixth, the base's `error`,
#: was retired: nothing raised it, `handler500` never composed through it, and the
#: base now declares no code and cannot be raised (`DomainError.__init__`).
SEEDED = ("not_found", "conflict", "forbidden", "invalid", "rate_limited")


# --- The seed ----------------------------------------------------------------


def test_the_class_codes_are_registered_with_a_boundary_and_a_remedy() -> None:
    for code in SEEDED:
        refusal = refusal_for(code)
        assert refusal is not None, f"{code} is raised in this tree and not declared"
        assert refusal.boundary in BOUNDARIES
        assert refusal.remedy.strip()


def test_every_shipped_exception_class_names_a_registered_code() -> None:
    """The other direction: no class refuses with a code the registry has not got."""
    for cls in (NotFound, Conflict, Forbidden, Invalid, RateLimited):
        assert cls.code in REFUSALS, cls
    # The base is not a refusal: it carries no code the registry could hold.
    assert DomainError.code not in REFUSALS


def test_the_boundary_says_which_layer_decided() -> None:
    """Not decoration — it is the first question anyone debugging a refusal asks.

    `not_found` is the scoped read coming back empty, `forbidden` is `authz`,
    and `rate_limited` is the edge: no service in this tree raises it, the door
    does (`config/api.py` maps ninja's `Throttled` onto it).
    """
    assert REFUSALS["not_found"].boundary == "selector"
    assert REFUSALS["forbidden"].boundary == "policy"
    assert REFUSALS["rate_limited"].boundary == "door"
    assert REFUSALS["invalid"].boundary == "service"


# --- an unregistered code cannot become a class -----------------------------


def test_an_unregistered_code_refuses_the_class_at_import() -> None:
    """The mechanism, driven the way an import drives it: a class body.

    `type()` is what `class X(Conflict): ...` does underneath, and it runs
    `__init_subclass__` at exactly the same moment — so this is the import-time
    failure, provoked inside a test rather than by adding a broken module to
    the tree.
    """
    with pytest.raises(TypeError) as raised:
        type("Unregistered", (Conflict,), {"code": "nobody_declared_this"})

    message = str(raised.value)
    # It names the code that is missing...
    assert "nobody_declared_this" in message
    # ...and the call that fixes it, with the argument names spelled out, so the
    # person reading the traceback does not have to go and find the module.
    assert "register_refusal" in message
    assert "boundary=" in message and "remedy=" in message
    # Per ADR core-5, the declaration grew two
    # required arguments, and the traceback that tells somebody how to fix a
    # missing declaration has to name all four or it teaches half the grammar.
    assert "fact=" in message and "remedies=" in message
    for boundary in BOUNDARIES:
        assert boundary in message


def test_a_subclass_that_inherits_its_parents_code_is_fine() -> None:
    """The common case: a better name for the same refusal, costing nothing.

    `apps.accounts.services.SsoRefused` is exactly this shape — a `Conflict`
    with its own docstring and its parent's code — so the rule cannot make the
    ordinary subclass expensive.
    """

    class SomethingSpecific(Conflict):
        default_detail = "Said better, refused the same."

    assert SomethingSpecific.code == "conflict"
    assert SomethingSpecific().detail == "Said better, refused the same."


def test_a_registered_code_makes_the_class_legal() -> None:
    register_refusal(
        code="test_registered_first",
        boundary="service",
        remedy="Nothing — this code exists to prove the registration is what unlocks it.",
        fact="Nothing happened; this refusal exists only inside a test.",
        remedies=(Remedy("Read the registry", "introspect:refusals"),),
    )

    class Registered(Conflict):
        code = "test_registered_first"

    assert Registered("no").code == "test_registered_first"
    assert Registered("no").refusal == REFUSALS["test_registered_first"]


# --- `code=` is gone from the constructors -----------------------------------


@pytest.mark.parametrize("cls", [DomainError, NotFound, Conflict, Forbidden])
def test_a_refusal_refuses_a_code_keyword(cls: type[DomainError]) -> None:
    """A code belongs to a class, not to a call site.

    A per-instance `code=` meant two raises of the same class could answer a
    client differently, and no registry could ever be complete — which is the
    whole reason it is gone. Nothing in `apps/` or `config/` passed it.
    """
    with pytest.raises(TypeError):
        cls("refused", code="made_up")  # type: ignore[call-arg]


def test_invalid_refuses_a_code_keyword() -> None:
    with pytest.raises(TypeError):
        Invalid({"name": ["Too short."]}, code="made_up")  # type: ignore[call-arg]


def test_rate_limited_refuses_a_code_keyword_and_keeps_retry_after() -> None:
    with pytest.raises(TypeError):
        RateLimited("slow down", code="made_up")  # type: ignore[call-arg]
    assert RateLimited("slow down", retry_after=30).retry_after == 30


# --- The registry has one writer ---------------------------------------------


def test_the_registry_is_read_only_from_outside() -> None:
    """`register_refusal` is the only writer, and that is enforced, not asked for."""
    with pytest.raises(TypeError):
        REFUSALS["smuggled"] = Refusal(  # type: ignore[index]
            code="smuggled",
            boundary="door",
            remedy="Never.",
            fact="Never.",
            remedies=(Remedy("Never", "never:never"),),
        )
    assert "smuggled" not in REFUSALS


def test_a_refusal_row_cannot_be_edited_in_place() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        REFUSALS["not_found"].remedy = "something else"  # type: ignore[misc]


def test_registering_the_same_meaning_twice_is_a_no_op() -> None:
    """A module imported twice is not an error; two meanings under one code is."""
    first = register_refusal(
        code="test_idempotent",
        boundary="door",
        remedy="Retry the declaration; it changes nothing.",
        fact="Nothing happened twice.",
        remedies=(Remedy("Carry on", "self:nowhere"),),
    )
    again = register_refusal(
        code="test_idempotent",
        boundary="door",
        remedy="Retry the declaration; it changes nothing.",
        fact="Nothing happened twice.",
        remedies=(Remedy("Carry on", "self:nowhere"),),
    )
    assert first == again

    with pytest.raises(ValueError, match="already registered"):
        register_refusal(
            code="test_idempotent",
            boundary="service",
            remedy="A different meaning under the same contract.",
            fact="Nothing happened twice.",
            remedies=(Remedy("Carry on", "self:nowhere"),),
        )


@pytest.mark.parametrize(
    ("code", "boundary", "remedy"),
    [
        ("Not Snake Case", "service", "..."),
        ("9_leading_digit", "service", "..."),
        ("", "service", "..."),
        ("test_bad_boundary", "somewhere", "..."),
        ("test_no_remedy", "service", "   "),
    ],
)
def test_a_malformed_declaration_is_refused(code: str, boundary: Any, remedy: str) -> None:
    """The registry is only worth reading if every row in it is complete."""
    with pytest.raises(ValueError):
        register_refusal(
            code=code,
            boundary=boundary,
            remedy=remedy,
            fact="A fact, so the row fails for the reason under test.",
            remedies=(Remedy("Somewhere", "self:somewhere"),),
        )


# --- The door half: no door invents a code -----------------------------------
#
# The registry is only the *product's* refusal vocabulary if the doors do not
# quietly grow a second one beside it. A door that hand-built
# `{"detail": ..., "code": "..."}` would be publishing a code no registry knows,
# no `introspect` reports and no audit row can be grouped by — and it would do
# it from the one layer that is allowed to name a status, so nothing above would
# ever see it. The doors' job is to *translate* what a service raised, and there
# are exactly two translators: `config/api.py` and `config/mcp.py`.
#
# DOES NOT COVER — declared, not discovered later: this scan is over the door
# modules (`api.py`, `mcp.py`), and the section below it covers exactly one
# module in front of them, `apps/core/idempotency.py`, by name. The registry declared the
# middleware as a residual; this section closed it — both of its codes are registered at
# `boundary="door"` and its call sites are read back — so what is left outside
# is narrower and still real:
#
# * **any other middleware.** The scan below names one module. A second
#   middleware that built `{"detail": …, "code": …}` would be invisible here,
#   because there is no rule that says "every entry in `MIDDLEWARE` is scanned";
#   there is one such module in this tree today and the test would have to be
#   pointed at a new one deliberately.
# * **the unhandled-exception envelope.** `config/api.py` answers a genuine
#   crash, and what a 500 carries is that module's business rather than the
#   registry's. Outside this section's closed question, declared here so it is not
#   mistaken for covered.
# * **remedy prose.** Every registered refusal is asserted to *have* a remedy,
#   never to have a good one. A remedy that says nothing useful passes.

DOOR_FILES = ("api.py", "mcp.py")


def _door_modules() -> list[Path]:
    found = sorted(
        path
        for name in DOOR_FILES
        for path in (Path(__file__).resolve().parents[2]).glob(f"*/{name}")
    )
    assert found, "no door modules found — the scan would pass vacuously"
    return found


def _http_error_calls(source: Path) -> list[tuple[int, ast.Call]]:
    tree = source_tree(source)
    calls: list[tuple[int, ast.Call]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else None
        if name is None and isinstance(node.func, ast.Attribute):
            name = node.func.attr
        if name == "HttpError":
            calls.append((node.lineno, node))
    return calls


def _dicts_with_a_code_key(source: Path) -> list[int]:
    tree = source_tree(source)
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Dict)
        and any(isinstance(key, ast.Constant) and key.value == "code" for key in node.keys)
    ]


def test_no_door_module_builds_a_body_with_a_code_key() -> None:
    """The closed question, kept closed.

    Two translators own the envelope — `config/api.py` for REST and
    `config/mcp.py` for the machine door — and both read `exc.code` off a
    registered refusal. A door that wrote one out by hand would be a second,
    undeclared vocabulary.
    """
    offences = {
        str(path): lines for path in _door_modules() if (lines := _dicts_with_a_code_key(path))
    }
    assert offences == {}, f"a door is building its own refusal body: {offences}"


def test_every_http_error_a_door_raises_is_a_status_and_a_message() -> None:
    """The audit, as an assertion rather than a note.

    `HttpError(status, message)` is the whole of what a door may raise directly:
    ninja renders it as `{"detail": message}`, with **no code**, which is what
    keeps the code column honest — an edge refusal that has no registered code
    does not pretend to have one. Anything richer than two positional arguments
    is a door inventing an envelope.
    """
    for path in _door_modules():
        for lineno, call in _http_error_calls(path):
            where = f"{path}:{lineno}"
            assert not call.keywords, f"{where}: HttpError takes a status and a message"
            assert len(call.args) == 2, f"{where}: HttpError takes a status and a message"
            status, message = call.args
            assert isinstance(status, ast.Constant) and isinstance(status.value, int), where
            assert isinstance(message, (ast.Constant, ast.JoinedStr)), where


def test_the_door_scan_would_catch_one(tmp_path: Path) -> None:
    """The canary: a scan that cannot fail is not a scan."""
    planted = tmp_path / "api.py"
    planted.write_text(
        "from ninja.errors import HttpError\n\n"
        "def route():\n"
        '    raise HttpError(409, {"detail": "no", "code": "invented_here"})\n',
        encoding="utf-8",
    )
    assert _dicts_with_a_code_key(planted) == [4]
    (lineno, call), *rest = _http_error_calls(planted)
    assert (lineno, rest) == (4, [])
    assert not isinstance(call.args[1], (ast.Constant, ast.JoinedStr))


# --- the layer in front of the doors ------------------------------------
#
# The middleware answers before any door runs, and it answers with the same
# `{detail, code}` envelope a door does — so its codes are refusals, and the
# only remaining question was where they were declared. They are declared
# beside the code that emits them, and this section is what keeps the set from
# growing quietly: the call sites are read back off the module, resolved to the
# rows they name, and held against both `EMITTABLE` and the registry.

MIDDLEWARE = Path(idempotency.__file__)


def _refusal_call_arguments(source: Path) -> list[tuple[int, ast.expr]]:
    """Every `_refusal_response(...)` call in a module, and the code it would emit.

    Static rather than dynamic on purpose: a call site only reached on the
    unhappy path of a race is a call site no test run visits, and "the codes
    this module can emit" is a property of the source, not of one execution.
    """
    tree = source_tree(source)
    calls: list[tuple[int, ast.expr]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == "_refusal_response"):
            continue
        where = f"{source}:{node.lineno}"
        assert not node.keywords, (
            f"{where}: _refusal_response takes a detail, a refusal and a status"
        )
        assert len(node.args) == 3, (
            f"{where}: _refusal_response takes a detail, a refusal and a status"
        )
        calls.append((node.lineno, node.args[1]))
    return calls


def test_the_two_edge_codes_are_registered_at_the_boundary_that_decided_them() -> None:
    """`boundary="door"` — both are decided in front of every door.

    Not `service`: no service is reached. The middleware claims the key, and
    either the fingerprint disagrees with the first request under it or the
    first request has not finished. A person debugging one of these should be
    reading this middleware, and the boundary is what sends them there.
    """
    for code in ("idempotency_key_reuse", "in_progress"):
        registered = refusal_for(code)
        assert registered is not None, f"{code} reaches clients and is not declared"
        assert registered.boundary == "door"
        assert registered.remedy.strip()


def test_every_code_the_middleware_can_emit_is_a_registered_row() -> None:
    """The class closed — enumerated, not spot-checked.

    Every `_refusal_response(...)` in the module names a module-level `Refusal`, that row
    is in `EMITTABLE`, and `EMITTABLE` is the registry's own rows rather than
    look-alikes. A third code cannot arrive by being typed at a call site: it
    would be a string, or a name that resolves to nothing, or a row nobody
    registered, and each of those fails here.
    """
    calls = _refusal_call_arguments(MIDDLEWARE)
    assert len(calls) >= 2, "the middleware's refusals moved — this scan is now vacuous"

    emitted: set[str] = set()
    for lineno, argument in calls:
        where = f"{MIDDLEWARE}:{lineno}"
        assert isinstance(argument, ast.Name), (
            f"{where}: a refusal is a declared row from EMITTABLE, not an expression"
        )
        row = getattr(idempotency, argument.id, None)
        assert isinstance(row, Refusal), f"{where}: {argument.id} is not a Refusal"
        assert row in idempotency.EMITTABLE, f"{where}: {row.code} is not in EMITTABLE"
        assert REFUSALS.get(row.code) == row, f"{where}: {row.code} is not the registered row"
        emitted.add(row.code)

    # Both directions: nothing emitted is undeclared, and nothing declared is
    # dead. A row left in EMITTABLE that no call site names is a contract this
    # product publishes and cannot produce.
    assert emitted == {row.code for row in idempotency.EMITTABLE}


def test_a_third_code_is_refused_at_the_moment_it_would_reach_a_client() -> None:
    """The runtime half, because a `Refusal` can be built by hand.

    `Refusal` is an ordinary frozen dataclass, so typing the argument buys
    nothing on its own — a hand-made row is still a row. What closes the set is
    membership of `EMITTABLE`, checked where it matters: on the way out.
    """
    invented = Refusal(
        code="invented_at_the_edge",
        boundary="door",
        remedy="Nothing — this row exists to prove the middleware will not emit it.",
        fact="Nothing — see above.",
        remedies=(Remedy("Nowhere", "self:nowhere"),),
    )
    assert invented.code not in REFUSALS

    with pytest.raises(ValueError, match="invented_at_the_edge"):
        idempotency._refusal_response("no", invented, 409)


def test_the_middleware_scan_would_catch_one(tmp_path: Path) -> None:
    """The canary: a scan that cannot fail is not a scan.

    The shape it has to catch is the one the middleware had before this section closed it — a bare
    string at the call site, which is a code no registry knows and `introspect`
    cannot report.
    """
    planted = tmp_path / "idempotency.py"
    planted.write_text(
        "def refuse():\n"
        '    return _refusal_response("That key was used elsewhere.", "invented_here", 409)\n',
        encoding="utf-8",
    )
    (lineno, argument), *rest = _refusal_call_arguments(planted)
    assert (lineno, rest) == (2, [])
    assert not isinstance(argument, ast.Name)


# --- ADR core-5: fact, remedies, and one composer for two doors ----------
#
# The registry held `(code, boundary, remedy)`, and `remedy` was internal by
# construction — advice for whoever was *holding* the refusal. What a refused
# CALLER got was `{detail, code, errors?}`: prose and a token, and no way out.
# ADR core-5 adds the two halves the grammar was missing and refuses a
# declaration without them at the same tier an unregistered code is refused at.
#
# DOES NOT COVER — declared: the *content* of a fact or a remedy. A label that
# lies ("Add funds", pointing at the wrong page) passes every assertion here;
# destination validation is product-side by the amendment's own boundary, and
# arrives with the first product nav manifest.


def test_every_registered_refusal_has_a_fact_and_structured_remedies() -> None:
    """The population half: all eight, not a spot check.

    Eight is the floor and the whole set — the six domain codes plus the two
    the idempotency middleware emits in front of the doors. No ninth is expected,
    so a ninth arriving here is news either way.
    """
    assert len(REFUSALS) >= 8
    for code, refusal in REFUSALS.items():
        assert refusal.fact.strip(), f"{code} can only say no"
        assert refusal.remedies, f"{code} is a dead end with a status code on it"
        for remedy in refusal.remedies:
            assert isinstance(remedy, Remedy)
            assert remedy.label.strip() and remedy.destination.strip()


def test_the_not_found_fact_says_the_not_there_is_not_yours_truth() -> None:
    """The one fact the grammar exists for.

    `not_found` is the refusal that lies by omission unless it says this out
    loud: a row in another tenant, or under a hat the caller is not wearing,
    answers exactly as a row that never existed. The `remedy` said it to a
    developer; nobody said it to the caller, who was left concluding the row
    is gone. Now the registry does, in the field a client is allowed to read.
    """
    fact = REFUSALS["not_found"].fact.lower()
    assert "another tenant" in fact
    assert "not-there" in fact and "not-yours" in fact
    assert "one answer" in fact


def test_a_declaration_without_a_fact_is_refused_at_import() -> None:
    """`ValueError`, at the moment the module is imported.

    Provoked here inside a test the way `test_an_unregistered_code_refuses_the
    _class_at_import` provokes its own — the call is what an import runs, so
    this IS the import-time failure, without adding a broken module to a tree
    the gate then has to be told to ignore.
    """
    with pytest.raises(ValueError, match="fact"):
        register_refusal(
            code="test_factless",
            boundary="service",
            remedy="Somebody wrote the internal advice and stopped there.",
            remedies=(Remedy("Somewhere", "self:somewhere"),),
        )
    assert "test_factless" not in REFUSALS


@pytest.mark.parametrize(
    "remedies",
    [
        "Just retry it.",
        ["Just retry it."],
        (Remedy("", "self:nowhere"),),
        (Remedy("A label", "  "),),
        (),
        None,
    ],
)
def test_an_unstructured_or_absent_remedy_is_refused_at_import(remedies: Any) -> None:
    """The other half of the fact-and-remedies requirement, and the miss it is against.

    "Grammar as optional parameters" is how a three-move shape becomes a
    one-move shape with two fields nobody fills: a sentence where a `Remedy`
    should be, or nothing at all, and the next door composes its own. Both are
    a `ValueError` here, at import, where somebody is still reading.
    """
    with pytest.raises(ValueError):
        register_refusal(
            code="test_unstructured_remedy",
            boundary="service",
            remedy="Internal advice, which is not the same thing.",
            fact="Something is true about this refusal.",
            remedies=remedies,
        )
    assert "test_unstructured_remedy" not in REFUSALS


def test_a_raise_site_may_override_the_registry_remedies() -> None:
    """Contextual remedies replace the generic ones rather than joining them.

    A raise site that knows the invoice already holding the number can say so,
    and the reason the override is total is that it exists *because* the
    generic answer was not good enough here — appending would leave the worse
    offer on the screen underneath the better one.
    """
    contextual = (Remedy("Open the invoice that holds this number", "invoice:7"),)
    exc = Conflict("Invoice 7 already has that number.", remedies=contextual)
    assert exc.remedies == contextual
    assert wire_refusal(exc)["remedies"] == [
        {"label": "Open the invoice that holds this number", "destination": "invoice:7"}
    ]
    # ...and the registry itself is untouched: an override is per-raise.
    assert REFUSALS["conflict"].remedies != contextual
    assert Conflict().remedies == REFUSALS["conflict"].remedies


def test_a_raise_site_cannot_smuggle_a_string_in_as_a_remedy() -> None:
    with pytest.raises(ValueError, match="not a Remedy"):
        NotFound("gone", remedies=["go somewhere else"])  # type: ignore[list-item]


def test_the_composer_builds_the_body_and_the_message_from_it() -> None:
    """At the unit: one composer, and the message is rendered FROM it.

    The message is not built from the exception a second time. That is the
    whole mechanism: `refusal_message` reads `wire_refusal`'s output, so "the
    assistant said what the screen said" holds by construction rather than by
    two modules agreeing to stay in step.
    """
    exc = Invalid({"name": ["Too short."]})
    body = wire_refusal(exc)
    assert body["code"] == "invalid"
    assert body["detail"] == "Too short."
    assert body["errors"] == {"name": ["Too short."]}

    message = refusal_message(body)
    assert message.startswith("invalid: Too short.")
    assert "(name: Too short.)" in message
    for remedy in REFUSALS["invalid"].remedies:
        assert f"{remedy.label} [{remedy.destination}]" in message


def test_the_composer_never_puts_the_internal_remedy_or_the_fact_on_the_wire() -> None:
    """The no-internal-detail-on-the-wire property, restated over the composer itself.

    Asserted on `wire_refusal` rather than on one door's response, because the
    composer is now the only thing that could leak it — and it is the thing
    every door renders through.
    """
    for code, refusal in REFUSALS.items():
        exc: DomainError = type(f"Probe_{code}", (DomainError,), {"code": code})("no")
        body = wire_refusal(exc)
        assert set(body) <= {"detail", "code", "errors", "remedies"}
        rendered = json.dumps(body)
        assert refusal.remedy not in rendered
        assert refusal.fact not in rendered
