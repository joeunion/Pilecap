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
declares what it replaced, once, in `DJB_IDENTITY_SHAPE` — the block below
that parses it is the authority on the seven keys and their
vocabularies — and the tests that assert the replaced shape skip.

**The skips carry ONE fixed prefix** (`PREFIX` below) so they are countable:
`pytest -rs | grep -c` is the whole instrument, and a reviewer reading a run
sees how much of the suite a declaration turned off rather than a scattering of
individually-worded skips.

**A key outside the seven is a `ValueError` at import**, not a skip and not a
silent pass. A mark is a claim about a closed population; a mark naming a key
nobody declares is a test that can never run again and nothing would say so.

This module is a fixture-support module, not a test module — the tests ABOUT it
are `apps/core/tests/test_template_shape.py`, which is also where the census
that reads every `@template_shape(` in the tree lives.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured

# --- What a product kept of the template's identity SHAPE --------------------
# The identity suite pins two different kinds of thing, and until this
# declaration existed it could not tell them apart. A **mechanism** is a
# property every product must hold whatever page it draws — the login policy has
# one writer and the audit compares it; a credential appears in no log line; an
# absent intent is not drift. A **shape** is an assertion about the template's
# own example surface — the marker string its entrance shell carries, which
# command writes the posture, whether it kept the template's `compose.yaml`,
# whether sign-in lands on the shipped `/welcome/`. A product that replaced a
# shape and then read a red suite learned nothing; a product that deleted those
# tests lost the mechanisms with them.
#
# So a product declares, once, what it replaced — `key=value;key=value`, in
# `DJB_IDENTITY_SHAPE` (its `.env`, or the environment the suite runs in) or in
# the tracked drawer's `identity_shape:` (`manage.py declare` writes both, so CI
# needs nothing; the two disagreeing is a refusal naming both) — and
# the tests that assert the replaced shape SKIP, with one fixed prefix so the
# skips are countable. **It is the test suite's vocabulary and lives here, with
# the suite's shape mark** (not in `apps/conftest.py`, which imports apps above
# `core` and so cannot be imported by `core`'s or `accounts`' tests): no
# deployment reads it, so a typo in it can stop a test run and
# never a deployment (principle 14 — it controls neither release nor a
# customer's behaviour; it says which of the template's example surfaces this
# tree still has). A test reads it by importing the parsed shape and its
# defaults from this module. **The platform's own tree
# declares nothing and runs all of them**, which is why the defaults below ARE
# the template's shape.
#
# The seven keys, each with the tests it governs:
#
# * `entrance_marker` — the CSS custom property the entrance shell's token block
#   declares. SKIPS `test_entrance_chain.py::test_the_shell_fetches_nothing` and
#   `::test_the_shell_declares_both_themes`. READ BY the re-keyed shell census
#   in the same module and by `test_welcome.py::test_it_extends_the_entrance_shell`.
# * `login_page` — `template` if `/accounts/login/` is the shipped chooser,
#   `own` if the product draws its own. SKIPS the five provider-chooser cases in
#   `test_entrance_chain.py` (`no_provider_keeps_the_operator_sentence`,
#   `one_provider_is_one_action_and_no_chooser`, `one_provider_names_the_hosted_hop`,
#   `two_providers_bring_the_chooser_back`, `the_count_is_the_population_and_not_a_setting`).
#   READ BY the census note in `apps/core/tests/test_template_shape.py`.
# * `template_files` — `kept` if this tree still ships the template's
#   `compose.yaml`, `.env.example` and `frontend/src/tokens/tokens.css`, `own` if
#   it replaced them. SKIPS the file-content censuses:
#   `test_entrance_chain.py::test_the_two_copies_of_the_shipped_accent_agree`,
#   the three in `test_zitadel_posture.py`, and the two settings-derivation
#   censuses in `test_identity_branding.py`.
# * `posture_writer` — the management command that closes the registration and
#   lockout posture. SKIPS the six cases in `test_zitadel_posture.py` that assert
#   `zitadel_seed`'s own identity and wording. READ BY the re-keyed idempotence
#   cases in the same module.
# * `branding_writer` — the management command that writes the hosted screen's
#   intent row. SKIPS `test_identity_branding.py::test_the_first_call_creates_and_activates`
#   and `::test_an_agreeing_screen_is_reported_as_agreeing`. READ BY the re-keyed
#   audit-section cases in the same module.
# * `landing` — `template` if a completed sign-in lands on the shipped
#   `/welcome/`, `own` if the product named its own. SKIPS
#   `test_welcome.py::test_the_named_mechanism_has_a_reader`.
# * `platform_apps` — `template` if the apps under `apps/` are exactly the
#   template's platform app set (`quality/partition.yaml`'s `platform_apps`),
#   `own` once the product has added an app of its own. SKIPS
#   `test_template_shape.py::test_the_platform_app_set_is_every_app_in_the_tree`,
#   the census that refuses a template app the partition forgot — on a product
#   tree its own apps are SUPPOSED to sit outside that list.
#
# An unknown key, a value outside a closed vocabulary, or an empty value is
# `ImproperlyConfigured` **when this module loads**, at collection: a typo in a declaration that
# quietly ran every test would be worse than no declaration at all, because the
# reds it produced would look like defects.
#
# **ONE TEST IN THE PLATFORM'S OWN SUITE READS THE DECLARATION ITSELF.**
# `apps/core/tests/test_template_shape.py::
# test_the_platform_declares_nothing` asserts that THIS tree declared nothing — its subject is the
# environment, which is why it reads the ambient value where every other case in
# that module is pinned. It wears `template_only`: a product tree (one declaring
# `rule_id_namespace:`) skips it with one sentence; the template runs it. Never
# delete it and never widen it to accept any declaration — then nothing is left
# that would notice the platform quietly declaring something.
# It is the only case in that module that behaves this way, and the module names
# it in a constant so the exception stays a population of one.
IDENTITY_SHAPE_DEFAULTS: dict[str, str] = {
    "entrance_marker": "--entrance-tokens",
    "login_page": "template",
    "template_files": "kept",
    "posture_writer": "zitadel_seed",
    "branding_writer": "zitadel_brand",
    "landing": "template",
    "platform_apps": "template",
}

# Four of the seven are CLOSED: they are a question about this tree with two
# answers. The other three name a product's own string — a marker, a command —
# and have no vocabulary to check beyond "not empty".
IDENTITY_SHAPE_VOCABULARY: dict[str, tuple[str, ...]] = {
    "login_page": ("template", "own"),
    "template_files": ("kept", "own"),
    "landing": ("template", "own"),
    "platform_apps": ("template", "own"),
}


def identity_shape(declaration: str) -> dict[str, str]:
    """Parse `key=value;…` over the seven keys, refusing anything else by name."""
    shape = dict(IDENTITY_SHAPE_DEFAULTS)
    for clause in declaration.split(";"):
        clause = clause.strip()
        if not clause:
            continue
        key, separator, value = clause.partition("=")
        key, value = key.strip(), value.strip()
        if not separator:
            raise ImproperlyConfigured(
                f"DJB_IDENTITY_SHAPE: {clause!r} is not `key=value`. "
                f"The keys are {', '.join(IDENTITY_SHAPE_DEFAULTS)}."
            )
        if key not in IDENTITY_SHAPE_DEFAULTS:
            raise ImproperlyConfigured(
                f"DJB_IDENTITY_SHAPE: {key!r} is not one of the seven keys "
                f"({', '.join(IDENTITY_SHAPE_DEFAULTS)})."
            )
        if not value:
            raise ImproperlyConfigured(
                f"DJB_IDENTITY_SHAPE: {key!r} was declared with an empty value. "
                "Leave the key out to keep the template's default "
                f"({IDENTITY_SHAPE_DEFAULTS[key]!r})."
            )
        allowed = IDENTITY_SHAPE_VOCABULARY.get(key)
        if allowed is not None and value not in allowed:
            raise ImproperlyConfigured(
                f"DJB_IDENTITY_SHAPE: {key}={value!r} is not one of {', '.join(allowed)}."
            )
        shape[key] = value
    return shape


DRAWER = Path(__file__).resolve().parents[3] / "quality" / "local" / "rules.yaml"


def declared_shape(environment: str, drawer: str | None) -> dict[str, str]:
    """The shape the environment or the drawer's text declares; both, disagreeing, refuse."""
    from quality.engine.rules import identity_shape_in

    tracked = identity_shape_in(drawer)
    if not environment.strip() or tracked is None:
        return identity_shape(environment.strip() or tracked or "")
    typed, held = identity_shape(environment), identity_shape(tracked)
    if typed != held:
        raise ImproperlyConfigured(
            f"DJB_IDENTITY_SHAPE={environment.strip()} and quality/local/rules.yaml's "
            f"identity_shape: {tracked} "
            "disagree; each is a human's declaration, so neither wins — make them one."
        )
    return held


IDENTITY_SHAPE: dict[str, str] = declared_shape(
    os.environ.get("DJB_IDENTITY_SHAPE", ""),
    DRAWER.read_text() if DRAWER.is_file() else None,
)


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
    # The seventh key's one mark: the template's platform app set, which a
    # product's first app of its own retires by declaring `platform_apps=own`.
    "apps/core/tests/test_template_shape.py",
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
    defaults: dict[str, str] = IDENTITY_SHAPE_DEFAULTS
    if key not in defaults:
        raise ValueError(
            f"template_shape({key!r}): not one of the seven declared keys "
            f"({', '.join(defaults)}). A mark naming a key nobody declares is a "
            "test that can never run again."
        )
    declared: Mapping[str, str] = IDENTITY_SHAPE if shape is None else shape
    value: str = declared[key]
    return pytest.mark.skipif(
        value != defaults[key],
        reason=f"{PREFIX} {key}={value}",
    )
