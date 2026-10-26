"""The registry carries the status, and `CODE_STATUS` is derived from it.

**ADR core-23** (numbered core-19 in the lead's validation pass, where the id
collided with the live ADR core-19 for the rate-limit headers — see this
module's report). `register_refusal` gains `status=`, and the code→number table
`config/api.py` publishes the document off stops being a hand-maintained append
block: every registered code that declared a number is in it, by derivation.

**What the append block cost.** Rule 47 asks a NEW refusal code for its
`CODE_STATUS` line in the rung that declares it, because `_document_operation`
looks each declared code up in that table and silently drops one it has no
number for — the code is registered, refusable, and absent from
`x-refusal-codes`. That is one config/ edit per code, in a template whose first
law is that registration is by discovery and never by editing `config/`. Three
peer rungs in a row paid it.

**`status` is OPTIONAL, and the absence is load-bearing rather than lax.** Two
populations declare no number and must not be made to:

* `invalid_arguments` (`apps/core/mcp.py`) is a MACHINE-door code. The MCP door
  has no status codes at all — a tool answers a refusal as one line of text —
  so a number there would be a fact invented to satisfy a table.
* house rule 47's own canary (`quality/canary/47/*.py`) registers
  `canary_unpublished` and declares it on a route precisely so that it is
  registered, refusable and unpublishable **by construction**. A registry that
  forced a status on every code would cure the disease the instrument carries,
  and a canary that cannot fire is exit 2.

So the drop path rule 47 patrols is preserved exactly — it moved from "no line
in `config/api.py`" to "no `status=` at the declaring site", which is one line
in the app that owns the refusal and no edit under `config/` at all.
"""

from __future__ import annotations

from typing import Any

import pytest

from apps.core.exceptions import (
    CODE_STATUSES,
    REFUSALS,
    DomainError,
    Forbidden,
    Remedy,
    declared_by,
    declaring_app,
    envelope_codes,
    register_refusal,
)
from config.api import CODE_STATUS, REFUSAL_FOR_STATUS, STATUS_FOR, status_for

# --- Criterion 2: the template's published codes, DERIVED and floored ---------
#
# This used to be `PRE_RUNG_CODE_STATUS`, a fourth hand-typed code→number table
# beside the registry, `STATUS_FOR` and `REFUSAL_FOR_STATUS` — appended to by
# every rung that registered a code. It is now what the registry says the
# template's own modules published (`_template_statuses`), held by a FLOOR so a
# code that silently drops out of `x-refusal-codes` still reds, while a code that
# joins is admitted by its own `status=` and by nothing typed here (the move ADR
# platform-partition-1 D4 made for the exports census).

#: How many codes the template's own modules publish with a number, at least.
#: Pinned from the line `test_the_template_publishes_at_least_its_floor` prints
#: ("template codes published: N") on the tree that retired the typed table; it
#: only ever falls by a human reading that line.
TEMPLATE_PUBLISHED_FLOOR = 33


def _template_apps() -> set[str]:
    """The template's own apps: the platform partition's boundary, read, never typed here.

    `quality/partition.yaml`'s `platform_apps` is the record of which apps the
    template ships (a product's apps are, by construction, not in it). Read
    as data so this pin and the partition cannot disagree about the boundary.
    """
    import yaml

    from config.settings.base import BASE_DIR

    data = yaml.safe_load((BASE_DIR / "quality" / "partition.yaml").read_text())
    return set(data["platform_apps"])


def _is_template_code(code: str) -> bool:
    """Declared by a template app, or outside `apps/` altogether (`config`, the engine)."""
    app = declaring_app(code)
    return app == "" or app in _template_apps()


def _template_statuses() -> dict[str, int]:
    """Every code a TEMPLATE module declared with a number, and the number."""
    return {
        code: status
        for code, status in CODE_STATUS.items()
        if not code.startswith("canary_") and _is_template_code(code)
    }


def test_the_template_publishes_at_least_its_floor() -> None:
    """A derived census of the template's published codes, above a printed floor.

    `canary_` is the tree's own prefix for a code that exists only inside an
    instrument or a fixture (`canary_unpublished` is house rule 47's), so it is
    never counted as the template's. Each number is a refusal's: 4xx or 5xx.
    """
    published = _template_statuses()
    print(f"template codes published: {len(published)}")
    assert len(published) >= TEMPLATE_PUBLISHED_FLOOR, sorted(published)
    assert all(400 <= status < 600 for status in published.values()), published


def test_the_signed_door_refusal_is_published_at_403() -> None:
    """The signed receiver's refusal, registered by `config.api`'s mount, publishes 403."""
    assert _template_statuses()["signed_door_takes_no_address"] == 403
    assert declared_by("signed_door_takes_no_address") == "apps.connections.api"


def test_a_product_code_is_admitted_by_its_own_declaration() -> None:
    """A code registered from a product app publishes with NO edit to this table.

    The declaration is made from a module that stands where a product's would —
    `apps.zzz_product.exceptions` — and the template pin above stays green.
    """
    namespace: dict[str, Any] = {"__name__": "apps.zzz_product.exceptions"}
    exec(  # noqa: S102 - a declaration made FROM a product module's namespace
        "from apps.core.exceptions import Remedy, register_refusal\n"
        "register_refusal(code='zzz_product_held', boundary='service',\n"
        "    remedy='Nothing - a fixture.', fact='A product code with its number.',\n"
        "    remedies=(Remedy('Read the registry', 'introspect:refusals'),), status=409)\n",
        namespace,
    )
    assert declaring_app("zzz_product_held") == "zzz_product"
    assert not _is_template_code("zzz_product_held")
    assert CODE_STATUS["zzz_product_held"] == 409
    assert "zzz_product_held" not in _template_statuses()


def test_the_template_codes_are_declared_by_template_modules() -> None:
    """The partition is not vacuous: every typed code has a template declarer."""
    for code in _template_statuses():
        assert _is_template_code(code), (code, declared_by(code))
    assert declared_by("stale_version") == "apps.core.exceptions"


def test_the_three_tables_are_one() -> None:
    """(a) the registry's numbers = (b) the class fallback = (c) the bare-status table.

    `REFUSAL_FOR_STATUS` and `STATUS_FOR` are derived from `CODE_STATUSES` at
    import (`apps.core.exceptions.bare_status_refusals`), so this pins the
    derivation rather than two typed tables agreeing: every bare status's class
    answers that number by its own declaration, and the class fallback is the
    same classes at the same numbers.
    """
    for status, cls in REFUSAL_FOR_STATUS.items():
        assert REFUSALS[cls.code].status == status, (status, cls.__name__)
        assert CODE_STATUSES[cls.code] == status
    assert set(STATUS_FOR) == set(REFUSAL_FOR_STATUS.values())
    for cls, status in STATUS_FOR.items():
        assert REFUSALS[cls.code].status == status, f"{cls.__name__} ({cls.code})"
        assert REFUSAL_FOR_STATUS[status] is cls


def test_no_published_number_is_a_hole() -> None:
    """Every number a template code answers has a refusal a BARE status maps to.

    RED on the baseline: `REFUSAL_FOR_STATUS` had no 503 while two codes declared
    it, so `HttpError(503, …)` fell through to ninja's codeless `{"detail": …}`.
    """
    holes = sorted(set(_template_statuses().values()) - set(REFUSAL_FOR_STATUS))
    assert holes == [], holes


@pytest.mark.parametrize("status", sorted({400, 401, 403, 404, 405, 409, 422, 429, 503}))
def test_a_bare_status_answers_with_a_registered_code(status: int) -> None:
    """A door that said only a number gets a body a client can branch on.

    Through ninja's own exception dispatch (`api.on_exception`), so the handler
    that runs is the one a route's `raise HttpError(…)` reaches. The negative is
    the baseline's 503: `{"detail": "x"}`, no `code`.
    """
    import json

    from django.test import RequestFactory
    from ninja.errors import HttpError

    from config.api import api

    request = RequestFactory().get("/api/v1/organizations/")
    answered = api.on_exception(request, HttpError(status, "A door said only a number."))
    body = json.loads(answered.content)
    assert answered.status_code == status
    assert body["code"] in REFUSALS, body
    assert REFUSALS[body["code"]].status == status, body
    if status == 503:
        assert body["code"] == "unavailable", body


def test_the_wire_reads_the_registry_first() -> None:
    """`status_for` answers off the declaration, not off the class tree.

    The two agree today (the test above pins that). This asserts WHICH is
    consulted, because a new code whose class subclasses `Forbidden` and whose
    registration says `418` must not answer 403 on the wire while the document
    says 418.
    """
    register_refusal(
        code="canary_status_wins",
        boundary="door",
        remedy="Nothing — a fixture inside this test module.",
        fact="A registered code whose declared status differs from its base class's.",
        remedies=(Remedy("Read the registry", "introspect:refusals"),),
        status=418,
    )

    class TeapotShaped(Forbidden):
        code = "canary_status_wins"

    assert status_for(TeapotShaped()) == 418
    assert CODE_STATUS["canary_status_wins"] == 418


# --- Criterion 1: a new code costs no edit under config/ ----------------------


def test_a_new_code_reaches_the_table_with_no_edit_under_config() -> None:
    """The headline. Registration is discovery here too.

    The falsifier on the baseline: `register_refusal` took no `status`, and this
    code would have reached `CODE_STATUS` only by somebody appending a line to
    `config/api.py`.
    """
    register_refusal(
        code="canary_new_status",
        boundary="service",
        remedy="Nothing — a fixture inside this test module.",
        fact="A code declared with its number, in the app that owns it.",
        remedies=(Remedy("Read the registry", "introspect:refusals"),),
        status=409,
    )

    assert CODE_STATUS["canary_new_status"] == 409
    assert REFUSALS["canary_new_status"].status == 409


def test_a_code_that_declares_no_number_stays_out_of_the_table() -> None:
    """Rule 47's drop path, preserved — and the machine door's code with it.

    `invalid_arguments` is the live member: registered, refusable at the MCP
    door, and carrying no HTTP status because that door has none. A derivation
    that invented a number for it would be publishing a fact nobody declared.
    """
    import apps.core.mcp  # noqa: F401  -- the module whose import registers it

    assert REFUSALS["invalid_arguments"].status is None
    assert "invalid_arguments" not in CODE_STATUS
    with pytest.raises(KeyError):
        CODE_STATUS["invalid_arguments"]


@pytest.mark.parametrize("status", [0, 200, 399, 600, "403", 403.0, True])
def test_a_status_that_is_not_a_refusal_number_is_refused_at_import(status: Any) -> None:
    """A declaration is checked at the tier every other malformed one is.

    4xx and 5xx only: a refusal that answered 200 would be a success wearing a
    refusal's clothes, and a string or a float is the shape a table lookup
    silently mis-keys on.
    """
    with pytest.raises(ValueError, match="status"):
        register_refusal(
            code="canary_bad_status",
            boundary="door",
            remedy="Nothing — a fixture inside this test module.",
            fact="A status outside the refusal range.",
            remedies=(Remedy("Read the registry", "introspect:refusals"),),
            status=status,
        )


# --- Criterion 3's derivation: the replay boundary is the registry's ----------


def test_envelope_codes_is_every_door_code_and_is_not_a_hand_list() -> None:
    """The replay boundary, derived. See `apps/core/idempotency.py` for WHY.

    Asserted as a derivation over the live registry rather than against a frozen
    set, because a frozen set here would be the hand list ADR core-23 rejected:
    a code registered `boundary="door"` next month has to join it by being
    registered, and by nothing else.
    """
    codes = envelope_codes()
    assert codes == {code for code, row in REFUSALS.items() if row.boundary == "door"}
    # The population is not empty and not everything — a derivation that
    # answered either would pass an equality test against itself.
    assert "page_token_missing" in codes
    assert "rate_limited" in codes
    assert "conflict" not in codes
    assert "not_found" not in codes


def test_a_refusal_declared_at_the_door_joins_the_boundary_by_being_declared() -> None:
    register_refusal(
        code="canary_door_boundary",
        boundary="door",
        remedy="Nothing — a fixture inside this test module.",
        fact="A door refusal declared after the module was imported.",
        remedies=(Remedy("Read the registry", "introspect:refusals"),),
        status=403,
    )
    assert "canary_door_boundary" in envelope_codes()


# --- Criterion 8: one composer still stands ----------------------------------


def test_the_status_never_reaches_the_wire_body() -> None:
    """`wire_refusal` is unchanged: the number is the status LINE, not a field.

    A status in the registry is a fact about the code that `config/api.py`
    speaks; putting it in the body would be the second grammar house rule 14 and
    ADR core-5 both exist to prevent, and the MCP door — which has no statuses —
    would then render a number it cannot honour.
    """
    from apps.core.exceptions import refusal_message, wire_refusal

    body = wire_refusal(Forbidden("Something went wrong."))
    assert set(body) <= {"detail", "code", "errors", "remedies"}
    assert "status" not in body
    assert "status" not in refusal_message(body)


def test_the_base_is_not_a_refusal_and_error_is_retired() -> None:
    """The registered catch-all `error` had no raiser; the base now refuses to be one.

    Every refusal is a registered subclass — `__init_subclass__` refuses a class
    whose code is unregistered at import, and the base itself declares no code,
    so constructing it is a `TypeError` naming the subclasses to raise instead.
    """
    assert "error" not in REFUSALS
    with pytest.raises(TypeError, match="registered subclass"):
        DomainError("Something went wrong.")
