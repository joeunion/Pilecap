"""The mark a test wears when what it asserts is the TEMPLATE's shape.

The identity suite pins two different kinds of thing. A **mechanism** is a
property every product must hold whatever page it draws: the login policy has
one writer and the audit compares it; a credential appears in no log line; an
absent intent is not drift. A **shape** is an assertion about this template's
own example surface: the marker string its entrance shell carries, which command
writes the posture, whether it still ships the template's `compose.yaml`,
whether a completed sign-in lands on the shipped `/welcome/`.

A product that replaced a shape and then read a red suite learned nothing, and a
product that deleted those tests lost the mechanisms with them. So a product
declares what it replaced, once, in `DJB_IDENTITY_SHAPE` — the settings block
beside `ZITADEL_*` in `config/settings/base.py` is the authority on the six keys
and their vocabularies — and the tests that assert the replaced shape skip.

**The skips carry ONE fixed prefix** (`PREFIX` below) so they are countable:
`pytest -rs | grep -c` is the whole instrument, and a reviewer reading a run
sees how much of the suite a declaration turned off rather than a scattering of
individually-worded skips.

**A key outside the six is a `ValueError` at import**, not a skip and not a
silent pass. A mark is a claim about a closed population; a mark naming a key
nobody declares is a test that can never run again and nothing would say so.

This module is a fixture-support module, not a test module — the tests ABOUT it
are `apps/core/tests/test_template_shape.py`, which is also where the census
that reads every `@template_shape(` in the tree lives.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from django.conf import settings

#: The one prefix every shape skip carries. Fixed, and deliberately loud: the
#: number of lines carrying it is the size of what a declaration turned off.
PREFIX = "IDENTITY SHAPE:"

#: The modules a shape mark may appear in. A mark somewhere else is a mark
#: outside the population this mechanism was designed for, and the census in
#: `test_template_shape.py` says so rather than letting the set grow quietly.
IDENTITY_SHAPE_MODULES: tuple[str, ...] = (
    "apps/accounts/tests/test_entrance_chain.py",
    "apps/accounts/tests/test_zitadel_posture.py",
    "apps/accounts/tests/test_identity_branding.py",
    "apps/accounts/tests/test_first_admin_command.py",
    "apps/core/tests/test_welcome.py",
)


def template_shape(key: str, *, shape: Mapping[str, str] | None = None) -> pytest.MarkDecorator:
    """Skip this test when the product declared a different value for `key`.

    The comparison is against `IDENTITY_SHAPE_DEFAULTS` — the template's own
    shape — and not against "the key is present", because a product is free to
    declare the template's value explicitly and must then still run the test.

    **`shape` exists for the tests ABOUT this mechanism, and it is keyword-only
    so a real mark cannot grow one by accident.** A mark passes nothing and gets
    the tree's declaration, which is the whole point of a mark. A test of the
    HELPER passes an explicit shape, because reading the ambient declaration
    there would make the platform's own test of the mechanism red on the first
    product that declares anything — this mechanism's divergence class
    re-entering through the test that polices it. Measured: with
    `login_page=own` set, three cases in `test_template_shape.py` went red on a
    tree that had done nothing wrong.
    """
    defaults: dict[str, str] = settings.IDENTITY_SHAPE_DEFAULTS
    if key not in defaults:
        raise ValueError(
            f"template_shape({key!r}): not one of the six declared keys "
            f"({', '.join(defaults)}). A mark naming a key nobody declares is a "
            "test that can never run again."
        )
    declared: Mapping[str, str] = settings.IDENTITY_SHAPE if shape is None else shape
    value: str = declared[key]
    return pytest.mark.skipif(
        value != defaults[key],
        reason=f"{PREFIX} {key}={value}",
    )
