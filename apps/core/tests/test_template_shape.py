# census: cross-app population=apps/**/test_*.py for the template-shape marks
"""The declaration refuses what it cannot mean, and the marks are a census.

Three groups, and they answer three different questions.

**Does a bad declaration fail loudly?** `DJB_IDENTITY_SHAPE` is typed by a human
into a `.env`, once, and then never looked at again. A typo that quietly ran
every test would be worse than no declaration at all: the reds it produced would
read as defects in the product. So an unknown key, a value outside a closed
vocabulary, and an empty value are each `ImproperlyConfigured` **when the
suite loads**, driven here through `apps.conftest.identity_shape`, the one
parser.

**Is every mark a real mark?** The marks are a closed population: seven keys, six
modules. A mark naming a seventh key is a test that can never run again, and a
mark in a seventh module is the mechanism growing somewhere nobody decided it
should. Both are read out of the tree by `ast`, not asserted from a list.

**Is the declaration documented where it is read?** The seven keys are only useful
if a product can find out what declaring one turns off, and the place a person
looks is the block that reads the variable — in `template_shape.py`, beside the
mark it governs.

Nothing here declares anything itself: the platform's own tree runs all of it
with `DJB_IDENTITY_SHAPE` unset (I1.7), which is why every assertion below about
"the default" is also an assertion that this tree is still the template.
"""

from __future__ import annotations

import ast
import warnings
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from apps.core.tests.template_shape import (
    IDENTITY_SHAPE,
    IDENTITY_SHAPE_DEFAULTS,
    IDENTITY_SHAPE_MODULES,
    PREFIX,
    declared_shape,
    identity_shape,
    template_shape,
)
from apps.core.tests.tree_census import source_tree

BASE_DIR = Path(str(settings.BASE_DIR))
SHAPE_MODULE = BASE_DIR / "apps" / "core" / "tests" / "template_shape.py"

#: The first line of the settings block, and therefore the left edge of the
#: window the documentation census reads. Anchored on the block's own header
#: rather than on a character count backwards from a mention, so the window
#: cannot be satisfied by prose that belongs to a different setting.
BLOCK_HEADER = "# --- What a product kept of the template's identity SHAPE"

#: The template's own shape, spelled here so this module is the second opinion
#: on `apps/core/tests/template_shape.py` rather than a mirror of it. A default
#: that moves without this list moving is a product-visible change, and
#: `CHANGELOG.md`'s MINOR rule is what it is for.
TEMPLATE_SHAPE: dict[str, str] = {
    "entrance_marker": "--entrance-tokens",
    "login_page": "template",
    "template_files": "kept",
    "posture_writer": "zitadel_seed",
    "branding_writer": "zitadel_brand",
    "landing": "template",
    "platform_apps": "template",
}


# --- the declaration refuses what it cannot mean -----------------------------


def test_the_six_keys_and_their_defaults_are_what_this_template_ships() -> None:
    """The population, pinned. A seventh key is a deliberate act, not a drift.

    The DEFAULTS are a module constant, so they say the same thing on every
    checkout. **The RESOLVED shape is parsed from an EMPTY declaration
    instead**, because asserting the ambient `IDENTITY_SHAPE` here reds on the
    first product that declares anything — the divergence class this whole
    mechanism exists to end, re-entering through the test that polices it. What
    is pinned is the mechanism: declare nothing, get the template's seven.
    """
    assert IDENTITY_SHAPE_DEFAULTS == TEMPLATE_SHAPE
    assert identity_shape("") == TEMPLATE_SHAPE


def test_an_unknown_key_refuses() -> None:
    """A typo in a key is the commonest way to declare nothing and think you did."""
    with pytest.raises(ImproperlyConfigured) as refusal:
        identity_shape("login_pages=own")

    assert "login_pages" in str(refusal.value)


@pytest.mark.parametrize(
    "declaration",
    ["login_page=mine", "template_files=x", "landing=theirs", "platform_apps=mine"],
)
def test_an_illegal_enum_value_refuses(declaration: str) -> None:
    """Four of the seven are closed questions with two answers; a third is a typo."""
    with pytest.raises(ImproperlyConfigured) as refusal:
        identity_shape(declaration)

    key, _, value = declaration.partition("=")
    assert key in str(refusal.value)
    assert value in str(refusal.value)


@pytest.mark.parametrize("declaration", ["login_page=", "entrance_marker=", "posture_writer= "])
def test_an_empty_value_refuses(declaration: str) -> None:
    """Empty is not "leave it alone" — leaving the key out is.

    The distinction matters because `key=` is exactly what a half-finished edit
    leaves behind, and present-but-empty defeating a default is a twice-evidenced
    class in the settings module (`test_settings.py`'s third `PRODUCT_BASE_URL`
    branch is the other instance).
    """
    with pytest.raises(ImproperlyConfigured) as refusal:
        identity_shape(declaration)

    assert "empty value" in str(refusal.value)


def test_a_clause_that_is_not_a_pair_refuses() -> None:
    """`;` is the separator and `=` is the pair; a missing `=` is neither."""
    with pytest.raises(ImproperlyConfigured) as refusal:
        identity_shape("login_page")

    assert "key=value" in str(refusal.value)


def test_a_legal_declaration_is_read_and_the_rest_keep_the_template_default() -> None:
    """A partial declaration is legal: a product replaced one surface, not six."""
    shape = identity_shape("login_page=own;landing=own")
    assert shape["login_page"] == "own"
    assert shape["landing"] == "own"
    assert shape["posture_writer"] == "zitadel_seed"


def test_an_empty_declaration_is_the_template_shape() -> None:
    """Both spellings of "I did not declare anything" land on the same dict."""
    assert identity_shape("") == TEMPLATE_SHAPE
    assert identity_shape(" ; ") == TEMPLATE_SHAPE


def test_declaring_the_template_value_explicitly_still_runs_the_test() -> None:
    """The comparison is against the VALUE, never against "the key is present"."""
    shape = identity_shape("login_page=template")
    assert shape["login_page"] == IDENTITY_SHAPE_DEFAULTS["login_page"]


# --- the marks are a census, read out of the tree ----------------------------


def _marks_in_the_tree() -> list[tuple[str, str, str]]:
    """Every `@template_shape("<key>")` in `apps/`, as (path, test name, key).

    Parsed rather than grepped, for the reason `test_settings.py`'s identity
    census gives about its own population: a decorator split over two lines is
    invisible to a line-oriented reader, and that is exactly the mark somebody
    will write once the argument gets long.
    """
    found: list[tuple[str, str, str]] = []
    for path in sorted((BASE_DIR / "apps").rglob("test_*.py")):
        tree = source_tree(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                callee = decorator.func
                name = callee.id if isinstance(callee, ast.Name) else None
                if name != "template_shape":
                    continue
                argument = decorator.args[0] if decorator.args else None
                key = (
                    argument.value
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
                    else ""
                )
                found.append((str(path.relative_to(BASE_DIR)), node.name, key))
    return found


def test_every_mark_names_a_key_and_lives_in_an_identity_shape_module(capsys: Any) -> None:
    """The population, both halves — and the count a reviewer reads.

    A mark naming a seventh key is a test that can never run again (and
    `template_shape` raises on it at import, which is the belt); a mark in a
    module outside the declared six is the mechanism spreading somewhere nobody
    decided it should, which nothing else in the tree would notice.

    The note at the end is decision 7's answer to the vacuous-suite question:
    when a product draws its own login page but keeps the template's branding
    writer, the branding suite still passes and proves nothing on that tree,
    because the hosted screen it is about is never shown. No test can know
    whether a deployment ever shows it, so the honest instrument is a note where
    a reviewer is already reading counts.

    **And it goes out as a WARNING, not through `capsys.disabled()`.** The gate
    runs pytest under xdist, where a worker's stdout never reaches the run's log
    — so the note a reviewer was supposed to read printed into a buffer nobody
    opens, and `grep -c` over a `--loop` log returned 0 on exactly the tree the
    note was written for. pytest's warnings summary is forwarded from the worker
    to the controller and printed by default, with no `-r` flag to remember.
    It is emitted ONLY when this tree declares a divergence: on the platform's
    own tree there is nothing to tell a reviewer, and a warning on every run
    forever is how a signal becomes furniture.
    """
    marks = _marks_in_the_tree()
    assert marks, "the census found no shape marks at all — it stopped looking"

    unknown = [(path, name, key) for path, name, key in marks if key not in TEMPLATE_SHAPE]
    assert unknown == [], "shape marks naming a key that is not one of the seven"

    outside = sorted({path for path, _, _ in marks} - set(IDENTITY_SHAPE_MODULES))
    assert outside == [], "shape marks outside the declared identity-shape modules"

    per_module = {
        module: sum(1 for path, _, _ in marks if path == module)
        for module in IDENTITY_SHAPE_MODULES
    }
    summary = [
        f"{PREFIX} {len(marks)} marks over {len(TEMPLATE_SHAPE)} keys",
        *(f"{PREFIX}   {count:>2}  {module}" for module, count in per_module.items()),
    ]
    if (
        IDENTITY_SHAPE["login_page"] != TEMPLATE_SHAPE["login_page"]
        and IDENTITY_SHAPE["branding_writer"] == TEMPLATE_SHAPE["branding_writer"]
    ):
        summary.append(
            f"{PREFIX}   note: the hosted screen's branding road is held in reserve "
            "on a product that draws its own page"
        )

    with capsys.disabled():
        print("\n" + "\n".join(summary))

    if IDENTITY_SHAPE != IDENTITY_SHAPE_DEFAULTS:
        warnings.warn("\n".join(summary), UserWarning, stacklevel=2)


def test_the_marks_are_where_this_rung_put_them() -> None:
    """Per-module counts, so a mark that quietly moves module is a red.

    The counts are the whole of I1.4's instrument (`grep -c '@template_shape('`),
    written as a test so that it is measured on every run rather than on the day
    somebody remembers to grep.
    """
    marks = _marks_in_the_tree()
    per_module = {
        module: sum(1 for path, _, _ in marks if path == module)
        for module in IDENTITY_SHAPE_MODULES
    }
    assert per_module == {
        "apps/accounts/tests/test_entrance_chain.py": 8,
        "apps/accounts/tests/test_zitadel_posture.py": 9,
        "apps/accounts/tests/test_identity_branding.py": 4,
        "apps/accounts/tests/test_first_admin_command.py": 0,
        "apps/core/tests/test_welcome.py": 1,
        "apps/core/tests/test_template_shape.py": 1,
    }
    assert len(marks) == 23


def test_a_mark_naming_a_key_outside_the_six_refuses_at_import() -> None:
    """The belt behind the census: the decorator itself will not be built."""
    with pytest.raises(ValueError) as refusal:
        template_shape("login_pages")

    assert "login_pages" in str(refusal.value)


def test_a_differing_value_skips_and_an_agreeing_one_does_not() -> None:
    """The mark's own mechanism, both directions, against an EXPLICIT shape.

    **Both shapes are built here.** The earlier form read the ambient
    declaration for the agreeing branch and then moved the live value with the
    `settings` fixture for the differing one — which made this case a report on
    the checkout rather than on the helper, and red on any tree that declared
    anything. Handing `template_shape` the shape asks "what does the mechanism
    do with THIS value", and that has one answer everywhere.

    `skipif`'s condition is positional, so it reads out of `args`; the reason —
    the countable half — is the keyword.
    """
    agreeing = template_shape("login_page", shape=TEMPLATE_SHAPE)
    assert agreeing.args[0] is False
    assert agreeing.kwargs["reason"] == f"{PREFIX} login_page=template"

    differing = template_shape("login_page", shape=TEMPLATE_SHAPE | {"login_page": "own"})

    assert differing.args[0] is True
    assert differing.kwargs["reason"] == f"{PREFIX} login_page=own"

    # The seventh key retires the same way: a product that added its own app.
    retired = template_shape("platform_apps", shape=TEMPLATE_SHAPE | {"platform_apps": "own"})
    assert retired.args[0] is True
    assert retired.kwargs["reason"] == f"{PREFIX} platform_apps=own"


# --- the keys are documented where the setting is read -----------------------


def test_the_keys_are_documented_where_the_setting_is_read() -> None:
    """One sentence per key, in the settings block, naming what it turns off.

    Not "documented somewhere": documented where a person looking at
    `DJB_IDENTITY_SHAPE` in a `.env` will land, which is the block in
    `apps/core/tests/template_shape.py` that reads it. A key added to the dict and not to the
    prose is a key a product can declare and cannot find out the meaning of.

    **The window is the BLOCK — its own header line to the dict it documents —
    and not "4000 characters back from the first mention".** That reach was
    about a hundred lines of unrelated settings prose, so a backticked key name
    anywhere in it satisfied the assertion: the verifier planted `landing` some
    3000 characters above the block, deleted the real sentence, and the test
    passed. A window that can be satisfied from outside the thing it is
    measuring is not measuring it.
    """
    text = SHAPE_MODULE.read_text()
    start = text.index(BLOCK_HEADER)
    end = text.index("IDENTITY_SHAPE_DEFAULTS", start)
    assert start < end, "the block header must come before the dict it documents"
    block = text[start:end]

    undocumented = [key for key in TEMPLATE_SHAPE if f"`{key}`" not in block]
    assert undocumented == [], f"declared and not documented in the block: {undocumented}"

    assert block.count("SKIPS") >= len(TEMPLATE_SHAPE) - 1


def test_the_env_example_ships_the_declaration_commented() -> None:
    """A tree that declares nothing runs everything, so the line ships commented.

    `_env_example()` in `test_settings.py` parses the file the way
    `cp .env.example .env` then reading it would, and this key must NOT appear
    in that parse: an uncommented line would hand every clone the template's own
    shape as an explicit declaration, which is a different (and noisier) thing
    from not declaring.
    """
    from apps.core.tests.test_settings import _env_example

    assert "DJB_IDENTITY_SHAPE" not in _env_example()

    text = (BASE_DIR / ".env.example").read_text()
    assert "# DJB_IDENTITY_SHAPE=" in text
    for key, value in TEMPLATE_SHAPE.items():
        assert f"{key}={value}" in text


# --- where the declaration is read from --------------------------------------

DRAWER_OWN = "rule_id_namespace: acme\nidentity_shape: platform_apps=own\n"


def test_the_tracked_drawer_declares_when_the_environment_is_silent() -> None:
    """A product's CI carries no `.env`; the drawer it commits is the declaration."""
    assert declared_shape("", DRAWER_OWN) == TEMPLATE_SHAPE | {"platform_apps": "own"}


def test_the_environment_alone_still_declares() -> None:
    assert declared_shape("platform_apps=own", None) == TEMPLATE_SHAPE | {"platform_apps": "own"}


def test_no_declaration_anywhere_is_the_template() -> None:
    assert declared_shape("", None) == TEMPLATE_SHAPE
    assert declared_shape("", "rule_id_namespace: acme\n") == TEMPLATE_SHAPE


def test_an_agreeing_environment_and_drawer_are_one_declaration() -> None:
    assert declared_shape("platform_apps=own", DRAWER_OWN)["platform_apps"] == "own"


def test_a_disagreeing_environment_and_drawer_refuse_naming_both() -> None:
    """Each was typed by a human (I1.7); neither silently wins."""
    with pytest.raises(ImproperlyConfigured) as refusal:
        declared_shape("platform_apps=template", DRAWER_OWN)
    said = str(refusal.value)
    assert "platform_apps=template" in said and "platform_apps=own" in said
    assert "quality/local/rules.yaml" in said


def test_a_drawer_shape_is_held_to_the_same_grammar() -> None:
    with pytest.raises(ImproperlyConfigured) as refusal:
        declared_shape("", "identity_shape: login_pages=own\n")
    assert "login_pages" in str(refusal.value)


# --- the template's platform app set -----------------------------------------


@template_shape("platform_apps")
def test_the_platform_app_set_is_every_app_in_the_tree() -> None:
    """Every app under `apps/` is one the partition names, and nothing else is.

    `quality/partition.yaml`'s `platform_apps` is the record of the template's
    own apps: the partition's skip key closes over them, and the refusal pin
    (`test_refusal_status.py::_template_apps`) reads the same list to decide
    which codes are the template's. An app merged into the template and
    forgotten there is silently classed a PRODUCT's — its tests always run and
    its refusal codes leave the typed pin. No marker both trees share can tell a
    forgotten template app from a product's, so the question is asked as a
    SHAPE: on the template's own tree the two sets are equal.

    A product retires it by the mark's protocol — `platform_apps=own` in
    `DJB_IDENTITY_SHAPE` the day it adds its first app — because on a product
    tree its own apps are SUPPOSED to sit outside the template's list (the
    lockfile's header says so: the live registry is a superset).
    """
    from quality.partition import platform_apps

    tree = {path.name for path in (BASE_DIR / "apps").iterdir() if (path / "apps.py").exists()}
    listed = set(platform_apps())
    assert listed == tree, (
        f"in the tree and absent from platform_apps: {sorted(tree - listed)}; "
        f"listed and absent from the tree: {sorted(listed - tree)}. A template app goes "
        "in quality/partition.yaml in the commit that adds it."
    )


#: THE ONE DELIBERATELY ENVIRONMENT-DERIVED TEST IN THIS MODULE, named here so
#: the exception is a declared population of exactly one rather than a habit.
#: Every other case above answers the same on every checkout; this one answers
#: about the checkout, because that is its subject. The settings block in
#: `config/settings/base.py` carries the same sentence, for the reader who meets
#: the red before they meet this file.
PLATFORM_ONLY_PIN = "test_the_platform_declares_nothing"


@pytest.mark.template_only(
    reason="its subject is the environment, and a product's declaration says this "
    "checkout is no longer the template's own tree"
)
def test_the_platform_declares_nothing() -> None:
    """The platform's own tree declares nothing — THE ONE DELIBERATE EXCEPTION.

    Reason, in one line: this assertion's SUBJECT is the environment, so reading
    the ambient declaration here is the point rather than the defect.

    Neither `config/settings/test.py` nor any settings module sets a shape, so
    the suite this assertion runs in is the one that runs every marked test. A product that
    declares reads a skip count; the platform reads none.

    A product declares by design, so the case wears `template_only`: skipped
    with one sentence on a tree that declares `rule_id_namespace:`, live on the
    template. Never delete it and never widen it to accept any declaration —
    then nothing is left that notices the platform quietly declaring something.
    """
    test_settings = (BASE_DIR / "config" / "settings" / "test.py").read_text()
    assert "IDENTITY_SHAPE" not in test_settings
    assert IDENTITY_SHAPE == IDENTITY_SHAPE_DEFAULTS
