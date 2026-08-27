"""A published example is a promise a client can paste back. This holds it.

One wrong example was reported — `MeasuredOut`'s `{"value": "value", …}`
does not validate against `MeasuredOut` — and the fix for one example is one
line. What is here instead is the **closed question underneath it**: every
component schema in the live API document carries an example (rule 41's census
counts them), and until now nothing anywhere checked that any of them was a
document its own schema would accept.

**Derived, never listed.** The population is the OpenAPI document's own
components joined to the `ninja.Schema` subclasses in this process by name — so
a schema added in any app is in the population on the day it is added, with no
edit here. Three component names resolve to no `Schema` subclass at all
(`Refusal`, `RefusalRemedy` and `PeriodKind` are hand-built or enum nodes) and
one name is ambiguous across modules; those are reported as SKIPPED and counted,
because a population that quietly shrank would make this test pass by measuring
less.

**The residue is a named ratchet, not an allow-list.** Four schemas were already
failing when this test was written, all in apps outside this module's own
territory and two of them under work happening concurrently. Editing them here would be
the collision the schema discipline exists to refuse, so each is named with its
owning app and its defect, the count may shrink and may never grow, and the day
an app fixes one it removes its own line. That is rule 31's per-app ratchet
shape, applied to the same kind of backlog.

**This module is one of two, and it is the cheap one.** Validation is half the
promise; the other half is that the DOOR takes what the document publishes, and
that half cannot be asked without sending anything.
`test_published_examples_at_the_door.py` is where every request-body example is
submitted to the operation that accepts it. The split is by cost
and by question: nothing here touches a database, and everything there needs a
seeded world.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import pytest
from ninja import Schema

from apps.core.schemas import MeasuredBasisOut, MeasuredOut
from config.api import api

#: The schemas whose published example does not validate against them, each
#: with the app that owns it and what is wrong. **This may shrink and may never
#: grow.** A new name here is a new defect and the assertion below names it.
#:
#: * `apps/connections` — `CredentialsIn.credentials` is `min_length=1`, and the
#:   synthesised example is `{}`. A constraint on the SHAPE of a mapping, which
#:   is the one class the format-aware synthesiser cannot answer: it knows what
#:   a value of a given format looks like, not how many entries a product's
#:   credential blob needs. `apps/connections` declares this one.
#:
#: **Three left this list.** `QuietHoursIn`, `PreferenceOut` and
#: `PagedPreferenceOut` published the field NAME as the example for a
#: `format: "time"` field — `"start"` for a time — so a caller who copied the
#: document got a 422. `apps/core/api/docs.py` now synthesises format-aware
#: values and the three validate against their own schemas.
KNOWN_INVALID_EXAMPLES: frozenset[str] = frozenset({"CredentialsIn"})

#: A floor under the population, for the same reason rule 31 floors its own: a
#: join that stopped resolving would take the failures to zero and read as a
#: pass. Measured at 115 the day this landed; it rises as the API grows.
CHECKED_FLOOR = 100


def _descendants(klass: type) -> set[type]:
    found: set[type] = set()
    for subclass in klass.__subclasses__():
        found.add(subclass)
        found |= _descendants(subclass)
    return found


def _schemas_by_name() -> dict[str, list[type[Schema]]]:
    found: dict[str, list[type[Schema]]] = {}
    for model in _descendants(Schema):
        found.setdefault(model.__name__, []).append(model)
    return found


@pytest.fixture(scope="module")
def document() -> dict[str, Any]:
    schema: dict[str, Any] = api.get_openapi_schema()
    return schema


def _verdicts(document: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    """`(valid, invalid, skipped)` component names, from the live document."""
    by_name = _schemas_by_name()
    valid: list[str] = []
    invalid: list[str] = []
    skipped: list[str] = []
    for name, node in sorted(document["components"]["schemas"].items()):
        candidates = by_name.get(name, [])
        if len({candidate.__module__ for candidate in candidates}) != 1:
            skipped.append(name)
            continue
        if "example" not in node:
            skipped.append(name)
            continue
        try:
            candidates[0].model_validate(node["example"])
        except Exception:  # noqa: BLE001 - any refusal is the finding
            invalid.append(name)
        else:
            valid.append(name)
    return valid, invalid, skipped


def test_every_published_example_validates_against_its_own_schema(
    document: dict[str, Any],
) -> None:
    """The closed question this module is for, asked of the whole document.

    A caller reading `/api/v1/docs` copies the example and sends it. When the
    example is not a value the schema accepts, the copy is refused and the
    document was the thing that was wrong — the worst shape a contract can have,
    because the client has no reason to doubt it.
    """
    valid, invalid, _skipped = _verdicts(document)
    new = sorted(set(invalid) - KNOWN_INVALID_EXAMPLES)
    assert new == [], (
        f"these schemas publish an example they would themselves refuse: {new}. "
        "Declare a realistic value with `apps.core.schemas.example(...)` on the "
        "field that fails; the synthesised placeholder is shaped right and is not "
        "always a legal value."
    )
    assert len(valid) >= CHECKED_FLOOR, (
        f"only {len(valid)} component examples were checked, below the floor of "
        f"{CHECKED_FLOOR}. The join from component name to schema class has stopped "
        "resolving, which takes the failures to zero and reads as a pass."
    )


def test_the_known_backlog_may_shrink_and_never_grow(document: dict[str, Any]) -> None:
    """The ratchet's other half: a fixed schema leaves the list.

    Without this, a name stays here after its app has fixed it and the next
    reader believes there is still a defect there. Same discipline as rule 31's
    per-app ratchets, and the same reason.
    """
    _valid, invalid, _skipped = _verdicts(document)
    healed = sorted(KNOWN_INVALID_EXAMPLES - set(invalid))
    assert healed == [], (
        f"these schemas no longer publish an invalid example: {healed}. "
        "Remove them from KNOWN_INVALID_EXAMPLES in this file."
    )


# --- the echoed names, by id, with the app that owns each ---------------------


#: Every field whose published example is the FIELD'S OWN NAME with its
#: punctuation rubbed out — `"chat_handle": "chat handle"`. **This may shrink
#: and may never grow**, and the test below holds both ends of it.
#:
#: `apps/core/api/docs.py::example_for` ends in a fall-through: no declared
#: example, no format entry, no name entry, no suffix — so it renders the title
#: as words and publishes that. It is the right last resort (a shape is better
#: than nothing) and it is not an example: `"status": "status"` is the ABSENCE
#: of one wearing the shape of one, and a reader who copies it learns only what
#: the field is called.
#:
#: Teaching the synthesiser about formats and kind-shaped names took this
#: population from 44 to 4. What was missing was any tooth over the
#: remainder, so the next echo would have arrived unremarked. This is that
#: tooth, and writing it corrected the count: **the booked 4 were the SCALARS**,
#: and three more echo inside a one-item list (`['email domains']`), which the
#: scalar reading skipped. Seven, not four — and the three the count missed are
#: the ones a caller feels, because `SsoConnectionIn`'s door refuses them
#: (`test_published_examples_at_the_door.py::DECLARED_REFUSALS`).
#:
#: Each line names the app that owns the field, because the fix is a
#: `Field(json_schema_extra=example(...))` beside the declaration and belongs to
#: whoever owns that file — never to a table here.
KNOWN_ECHOED_EXAMPLES: dict[str, str] = {
    "ConnectionOut.last_error": (
        "apps/connections — what the last delivery attempt complained about. A "
        "real one is a sentence ('502 from the provider'); the document says "
        "'last error'."
    ),
    "PolicyStepOut.escalate_when": (
        "apps/comms — the condition that moves a policy to its next step. This "
        "is a VOCABULARY field and the echo hides that there is a vocabulary."
    ),
    "RecipientOut.chat_handle": (
        "apps/comms — a handle on a chat platform. The shape a product uses "
        "(`@ada`, a Slack member id) is the app's to say."
    ),
    "RecipientPatch.chat_handle": (
        "apps/comms — the same field on the write side; two schemas, one "
        "declaration to make, and both lines go when it is made."
    ),
    "SsoConnectionIn.email_domains": (
        "apps/accounts — the domains that route to this IdP. The echo is inside "
        "a list, which is why the first count missed it, and its own door "
        "refuses the published example: \"'email domains' is not an email "
        'domain".'
    ),
    "SsoConnectionOut.email_domains": (
        "apps/accounts — the read side of the same field, same declaration."
    ),
    "SsoConnectionPatch.email_domains": (
        "apps/accounts — and the patch side. One `example(...)` retires all three."
    ),
}


def _title_echo(field: str, spec: Mapping[str, Any]) -> str:
    """What the synthesiser's last resort would publish for this property.

    Deliberately a re-implementation of `docs.example_for`'s final two lines
    rather than a call into it: this test asks whether the FALL-THROUGH was
    reached, and calling the function that decides that would answer with
    whatever the function decided. Two independent spellings of one rule is how
    a census stays able to disagree with the thing it censuses.
    """
    title = str(spec.get("title") or field or "value")
    return re.sub(r"[^A-Za-z0-9 ]", " ", title).strip().lower() or "value"


def _echoed(document: Mapping[str, Any]) -> dict[str, Any]:
    """`Schema.field` -> the echoed value, over the whole published document.

    A one-item list counts, and that is not a nicety: `list[str]` fields get
    their item synthesised the same way, and `['email domains']` teaches a
    reader exactly as little as `'email domains'` does — it just hid from the
    first count.
    """
    found: dict[str, Any] = {}
    for name, node in sorted(document["components"]["schemas"].items()):
        properties = node.get("properties")
        example = node.get("example")
        if not isinstance(properties, Mapping) or not isinstance(example, Mapping):
            continue
        for field, spec in properties.items():
            if field not in example or not isinstance(spec, Mapping):
                continue
            value = example[field]
            scalar = value[0] if isinstance(value, list) and len(value) == 1 else value
            if isinstance(scalar, str) and scalar == _title_echo(field, spec):
                found[f"{name}.{field}"] = value
    return found


def test_no_published_example_is_the_field_name_wearing_a_costume(
    document: dict[str, Any],
) -> None:
    """The synthesiser's last resort is a shape, not an example — and it is censused.

    The equality holds the ratchet from both ends in one assertion: a NEW field
    that falls through to its own name fails here naming itself, and a field
    that has been given a real example fails until its line comes out. Without
    the second half a fixed field keeps a line that tells the next reader there
    is still a defect there. Both ends were planted and both fired before this
    landed — `WebhookEndpointOut.description` stripped of its example, and
    `RecipientOut.chat_handle` given one.

    DOES NOT COVER — declared, and the first plant is what measured it.
    `example_for` consults a node's `default` BEFORE it reaches the fall-through,
    so a field declared `str = Field(default="")` publishes `""` and can never
    echo. That is an EMPTY example rather than a wrong one — a different and
    milder defect, and the one rule 41's `undeclared_example_fields` ratchet
    already counts. This census is about the fall-through: the case where the
    document shows a reader something that looks like data and is the field's
    own label.
    """
    echoed = _echoed(document)

    new = sorted(set(echoed) - set(KNOWN_ECHOED_EXAMPLES))
    assert not new, (
        "these fields publish their own name as their example: "
        + ", ".join(f"{field} = {echoed[field]!r}" for field in new)
        + ". Declare a real value with `Field(json_schema_extra=example(...))` "
        "beside the field, or teach `apps/core/api/docs.py` the format or the "
        "name if the whole class of field deserves it."
    )

    healed = sorted(set(KNOWN_ECHOED_EXAMPLES) - set(echoed))
    assert not healed, (
        f"these fields publish a real example now: {healed}. Remove them from "
        "KNOWN_ECHOED_EXAMPLES in this file."
    )


# --- the measured number's own example, arithmetic and all --------------------


#: The additive grammar this tooth can evaluate, and no more. A formula using
#: anything else is refused rather than skipped, so a future example that
#: multiplies makes somebody extend this deliberately instead of silently
#: dropping out of the check.
_ADDITIVE = re.compile(r"^\s*([A-Za-z_][\w]*)(\s*[-+]\s*[A-Za-z_][\w]*)*\s*$")


def _evaluate(formula: str, inputs: dict[str, Decimal]) -> Decimal:
    assert _ADDITIVE.match(formula), (
        f"this tooth evaluates `a + b - c` and nothing else; {formula!r} needs it "
        "extended on purpose."
    )
    tokens = re.findall(r"[A-Za-z_][\w]*|[-+]", formula)
    total = inputs[tokens[0]]
    for sign, name in zip(tokens[1::2], tokens[2::2], strict=True):
        total = total + inputs[name] if sign == "+" else total - inputs[name]
    return total


def test_the_measured_examples_validate_and_the_arithmetic_is_honest(
    document: dict[str, Any],
) -> None:
    """`MeasuredOut`'s whole contract is that the basis explains the value.

    A hand-written example that validates but whose subtraction does not come
    out is a worse instrument than a placeholder, because it teaches the reader
    that the basis is decoration. So this recomputes it rather than comparing
    two strings somebody typed next to each other.
    """
    components = document["components"]["schemas"]
    measured = MeasuredOut.model_validate(components["MeasuredOut"]["example"])
    basis = MeasuredBasisOut.model_validate(components["MeasuredBasisOut"]["example"])

    assert measured.value == _evaluate(measured.basis.formula, measured.basis.inputs)
    assert basis.inputs, "an empty `inputs` explains nothing; that was the defect"
    assert measured.basis.model_dump() == basis.model_dump(), (
        "the two examples describe different sums, so a reader checking the "
        "nested one against the standalone one gets two answers."
    )


# --- the copy-paste drive ------------------------------------------------------


def test_a_published_example_can_be_PASTED_INTO_ITS_OWN_DOOR(
    document: dict[str, Any],
) -> None:
    """Validation is half the promise; the other half is that the door takes it.

    The shape this covers is an example that VALIDATES and is then refused by
    the door it documents — schema-valid, vocabulary-dead. This drives the narrower and
    sharper half of it: a request body whose example is copied verbatim out of
    the document and sent, which is what a caller actually does.

    `QuietHoursIn` is the named first customer and the reason this exists. Its
    `start`/`end` are `format: "time"` fields, the synthesiser had no entry for
    that format, and it fell through to echoing the field name — so the
    published example carried `"start": "start"` and a caller who pasted it got
    a **422**. That is the worst documentation defect there is: the client has
    no reason to doubt the document.

    DOES NOT COVER — declared: one body, driven through the schema rather than
    over HTTP. The general census (every example against its own door, sent for
    real) landed as its own tooth in
    `test_published_examples_at_the_door.py`, sequenced behind this fix because
    a tooth built on a dirty baseline records the dirt as the baseline. This
    stays as the named first customer's own pin: it is the one example whose
    422 was measured, and a schema-level assertion about it survives any change
    to how the door census seeds its world.
    """
    from apps.comms.schemas import QuietHoursIn

    example = document["components"]["schemas"]["QuietHoursIn"]["example"]

    # Pasted, not adapted: exactly the bytes the document publishes.
    body = QuietHoursIn.model_validate(example)

    assert body.start is not None, "the pasted example carries no start time"
    assert body.end is not None
    assert str(body.start) == example["start"], (
        "the value the schema parsed is not the value the document showed"
    )
