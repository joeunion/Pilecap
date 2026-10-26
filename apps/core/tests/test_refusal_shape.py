"""One refusal shape: every registered refusal's body is a `RefusalOut`.

The population is CLOSED and walked, never listed: every `DomainError` subclass
the mounted product imports (`apps.core.exceptions._refusal_classes`), each
built and composed by the one `wire_refusal`, each body validated by the one
schema. A refusal class whose body stopped being that shape — a fifth key typed
over a common one, a remedy that is a sentence — fails by name.

Also pinned here: the document's `Refusal` component and `BulkRefusalOut` are the
same shape (`RefusalOut`'s fields), so the published contract, a bulk item's
refusal and the sent body are one declaration and not three.
"""

from __future__ import annotations

import inspect
import sys
from typing import Any
from uuid import UUID

import pytest

from apps.core.exceptions import (
    REFUSALS,
    WIRE_COMMON_KEYS,
    Blocker,
    DomainError,
    _refusal_classes,
    declared_by,
    wire_refusal,
)
from apps.core.schemas import BulkRefusalOut, RefusalOut

#: What a refusal class whose constructor demands a keyword gets, by the keyword's
#: name. A class demanding one not here fails `test_every_registered_refusal_is_one_shape`
#: naming it — the table grows by a visible line, never by a skip.
SAMPLE_ARGUMENTS: dict[str, Any] = {
    "noun": "widget",
    "blocking": (
        Blocker(noun="widget_entry", door="route:widget_entries-list", label="Its entries"),
    ),
    "current_version": 3,
    "merged_into": UUID("00000000-0000-0000-0000-000000000001"),
}


def _shipped(module: str) -> bool:
    """A module the product ships — not a test's, not a fixture namespace never imported."""
    return module in sys.modules and ".tests." not in module and "<locals>" not in module


def _mounted_classes() -> list[type[DomainError]]:
    """Every refusal class the mounted product ships — the two doors' modules loaded first.

    A class a TEST defined (a fixture subclass inside a test function) is not the
    product's and is left out, as is a code a test registered from a namespace it
    invented: the registry is process-wide, and other tests write fixtures into it.
    """
    import config.api  # noqa: F401 — the HTTP door's classes and every app's routers
    import config.mcp  # noqa: F401 — the machine door's

    return [
        cls
        for cls in _refusal_classes()
        if _shipped(cls.__module__) and "<locals>" not in cls.__qualname__
    ]


def _built(cls: type[DomainError]) -> DomainError:
    demanded = {
        name: SAMPLE_ARGUMENTS[name]
        for name, parameter in inspect.signature(cls).parameters.items()
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY
        and parameter.default is inspect.Parameter.empty
    }
    return cls(**demanded)


def test_every_registered_refusal_is_one_shape() -> None:
    classes = _mounted_classes()
    shipped_codes = {
        code for code in REFUSALS if _shipped(declared_by(code)) and not code.startswith("canary_")
    }
    assert {cls.code for cls in classes} >= shipped_codes, (
        "a registered code has no class the mount imports"
    )
    for cls in classes:
        body = wire_refusal(_built(cls))
        shaped = RefusalOut.model_validate(body)
        assert shaped.code == cls.code
        assert set(body) - WIRE_COMMON_KEYS == set(_built(cls).wire_extra), cls.__name__
        assert body["remedies"], f"{cls.__name__}: a refusal with no remedy is a dead end"


def test_the_document_and_the_bulk_item_are_the_same_shape() -> None:
    """The `Refusal` component IS `RefusalOut`'s JSON Schema; a bulk item's refusal is the same."""
    from apps.core.api.docs import refusal_component

    ref = "#/components/schemas/{model}"
    published = refusal_component()
    shape = RefusalOut.model_json_schema(ref_template=ref)
    defs = shape.pop("$defs")
    component = published["Refusal"]
    assert component["properties"].keys() == shape["properties"].keys()
    for name, spec in shape["properties"].items():
        expected = dict(spec)
        if name == "code":
            expected["enum"] = sorted(REFUSALS)
        assert component["properties"][name] == expected, name
    assert component["required"] == shape["required"] == ["detail", "code"]
    assert published["RefusalRemedyOut"] == defs["RefusalRemedyOut"]
    assert component["properties"]["remedies"]["items"] == {
        "$ref": "#/components/schemas/RefusalRemedyOut"
    }
    assert published["RefusalRemedy"] == {"$ref": "#/components/schemas/RefusalRemedyOut"}
    assert "null" not in str(component["properties"]["errors"])

    assert issubclass(BulkRefusalOut, RefusalOut)
    for mode in ("validation", "serialization"):
        bulk = BulkRefusalOut.model_json_schema(ref_template=ref, mode=mode)
        assert (
            bulk["properties"]
            == RefusalOut.model_json_schema(ref_template=ref, mode=mode)["properties"]
        ), mode
    assert "errors" not in component["example"]
    assert "errors" not in BulkRefusalOut.model_json_schema()["example"]


def test_the_schema_round_trips_the_wire_body() -> None:
    """Validated and dumped, a body is the body `wire_refusal` composed — `errors` and all."""
    from apps.core.exceptions import Forbidden, Invalid

    bare = wire_refusal(Forbidden())
    assert "errors" not in bare
    assert RefusalOut.model_validate(bare).model_dump() == bare
    named = wire_refusal(Invalid({"name": ["Required."]}))
    assert RefusalOut.model_validate(named).model_dump() == named


@pytest.mark.parametrize("code", ["no_acting_scope", "invalid_signature", "unavailable"])
def test_the_new_codes_are_in_the_registry(code: str) -> None:
    """`introspect`'s `refusals` lists each (RED on the baseline: `index(...)` → `null`)."""
    assert code in REFUSALS
    assert REFUSALS[code].boundary == "door"
