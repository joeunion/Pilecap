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
    REFUSALS,
    DomainError,
    Forbidden,
    Remedy,
    envelope_codes,
    register_refusal,
)
from config.api import CODE_STATUS, STATUS_FOR, status_for

# --- Criterion 2: wire identity, against the pre-rung table -------------------
#
# The mapping `config/api.py` published on the baseline tree (7a2da23), read off
# a live import and frozen here. It is the whole point of the rung that this
# table did not change: what changed is who computes it.

PRE_RUNG_CODE_STATUS: dict[str, int] = {
    "addressing_header_not_honoured": 403,
    "conflict": 409,
    "database_unavailable": 503,
    "error": 500,
    "forbidden": 403,
    "idempotency_key_reuse": 409,
    "in_progress": 409,
    "insufficient_scope": 403,
    "invalid": 400,
    "invalid_body": 422,
    "invalid_cursor": 400,
    "method_not_allowed": 405,
    "not_found": 404,
    "page_token_missing": 403,
    "rate_limited": 429,
    "search_unavailable": 503,
    "session_required": 403,
    "unauthenticated": 401,
}


def test_the_derived_table_is_the_table_that_was_typed() -> None:
    """Every code the hand-appended block published, at the same number.

    Equality and not containment in the direction that matters: a code the
    append block published and the derivation does not is a code that has just
    dropped out of `x-refusal-codes`, which is the exact defect rule 47 exists
    to notice.
    """
    for code, status in PRE_RUNG_CODE_STATUS.items():
        assert CODE_STATUS.get(code) == status, code

    # And nothing joined it either, which is the other half of "identical". The
    # `canary_` prefix is the tree's own convention for a code that exists only
    # inside an instrument or a fixture (`canary_unpublished` is house rule 47's,
    # planted into the real scope at self-test time); everything else in the live
    # table is a code this product can actually make.
    product_codes = {code for code in CODE_STATUS if not code.startswith("canary_")}
    assert product_codes == set(PRE_RUNG_CODE_STATUS)


def test_the_registry_and_the_class_table_never_disagree() -> None:
    """`STATUS_FOR` is now the fallback for a code that declared no number.

    It stays because a registered code without a status still has to become a
    number at the HTTP door (rule 47's canary is a `Forbidden`), and it is held
    against the registry here so the two cannot drift into answering one code
    two ways — the wire from the class tree, the document from the registry.
    """
    for cls, status in STATUS_FOR.items():
        registered = REFUSALS[cls.code]
        assert registered.status == status, f"{cls.__name__} ({cls.code})"


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

    body = wire_refusal(DomainError("Something went wrong."))
    assert set(body) <= {"detail", "code", "errors", "remedies"}
    assert "status" not in body
    assert "status" not in refusal_message(body)
