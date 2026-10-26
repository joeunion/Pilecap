# census: cross-app population=apps/*/policies.py,apps/*/roles.py platform apps' POLICIES and roles
"""The committed flat baseline IS what its own writer writes on this tree.

`apps/core/tests/flat_product_baseline.json` is DERIVED — its header carries
the command that made it (`_command`) and the tree it was made on
(`_baseline`). A document that its writer would no longer produce is a
document nobody re-derived: the census beside it (`test_resolution.py`) then
compares this tree against an older one and has to excuse the difference.

So this runs the writer's own function — `flat_product_census()` — in-process,
inside the test transaction, and diffs it against the committed document: the
population first (keys added, keys removed), then every cell. Any difference
prints the keys, and the remedy is the header's own command.

DOES NOT COVER: whether a moved cell is RIGHT — that is the census test's and
each app's sweep's question; this one says only that the document is current.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings

from apps.core import authz
from apps.core.tests import permissions_world
from apps.core.tests.permissions_world import (
    BASELINE_COMMAND,
    BASELINE_SHA,
    declared_action_keys,
    drift,
    flat_product_census,
    flat_roles,
    read_action_keys,
)

DOCUMENT = Path(str(settings.BASE_DIR)) / "apps/core/tests/flat_product_baseline.json"


def test_the_document_is_what_its_writer_writes_on_this_tree(db: None) -> None:
    committed = json.loads(DOCUMENT.read_text())
    moved = drift(committed, flat_product_census())
    assert moved == [], (
        f"flat_product_baseline.json is not what its writer derives on this tree "
        f"({len(moved)} lines):\n    "
        + "\n    ".join(moved)
        + f"\n  Re-derive it with the header's own command: {BASELINE_COMMAND}"
    )


def test_a_product_apps_keys_and_roles_are_outside_the_census(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Planted: the two worked apps read as a product's, so their keys and role leave the census."""
    before = set(declared_action_keys()) | set(read_action_keys())
    assert {"widget.create", "widget.read"} <= before and "customer" in flat_roles()
    platform = permissions_world.platform_labels() - {"example", "example_portal"}
    monkeypatch.setattr(permissions_world, "platform_labels", lambda: platform)
    after = set(declared_action_keys()) | set(read_action_keys())
    kinds = {"widget", "widget_entry", "widget_policy", "portal_request"}
    assert not {key for key in after if key.split(".", 1)[0] in kinds}
    assert after < before and "customer" not in flat_roles()


def test_the_header_names_its_writer_and_its_tree() -> None:
    """The provenance travels in the document, and it is the writer's own."""
    committed = json.loads(DOCUMENT.read_text())
    assert committed["_baseline"] == BASELINE_SHA
    assert committed["_command"] == BASELINE_COMMAND
    assert "write_flat_product_baseline" in committed["_command"]


def test_the_diff_names_an_added_a_removed_and_a_moved_key() -> None:
    """The canary: each shape of drift is printed, by key."""
    committed = {
        "roles": ["owner"],
        "answers": {"a.keep": {"owner": True}, "a.gone": {"owner": True}},
    }
    derived = {
        "roles": ["owner"],
        "answers": {"a.keep": {"owner": False}, "a.new": {"owner": True}},
    }
    assert drift(committed, derived) == [
        "added    a.new",
        "removed  a.gone",
        "moved    a.keep · owner: True -> False",
    ]
    assert drift(committed, committed) == []
    # The residue is read the same way: a key that joined a role's residue grew
    # it, a key that left was swept — both are a document to re-derive.
    swept = {**committed, "residue": {"member": ["a.keep", "a.gone"]}}
    grown = {**committed, "residue": {"member": ["a.keep", "a.new"]}}
    assert drift(swept, grown) == ["residue  member grew: a.new", "residue  member swept: a.gone"]


def test_a_role_a_declared_surface_names_holds_no_residue(db: None) -> None:
    """The wall: a surface's role holds exactly its declaration, so its residue is `[]`.

    Read off the COMMITTED document — the platform roles' lists beside it are the
    consolidation's sweep count, down-only, and the writer-diff above is what
    holds them to the tree. On the template the population is the portal's
    `customer` (the sibling below pins that one surface is declared); the
    negative — a role no surface names still holds the residue — is planted in
    `test_vocabulary.py`, because the platform roles' lists are meant to empty.
    """
    from apps.core import surfaces

    committed = json.loads(DOCUMENT.read_text())
    residue: dict[str, list[str]] = committed["residue"]
    walled = {
        role
        for role in residue
        if surfaces.named(surfaces.surface_for_role(role).roles) is not None
    }
    assert {role: residue[role] for role in walled} == {role: [] for role in walled}


def test_the_template_declares_one_surface_customer_in_example_portal(db: None) -> None:
    """The pinned shape: ONE declared surface, `customer`, in `example_portal`; staff total.

    The template ships one worked second surface (`apps/example_portal`), so the
    tree declares exactly that one beside the implicit total `staff` — every
    family, every act, every screen, the tenant by header. Every role the
    document names belongs to `staff` except the one the portal declares, which
    belongs to its surface. A product that switches the example off is the flat
    product with no surface declared (`test_surfaces.py` holds that world).
    """
    from apps.core import surfaces
    from apps.core.discovery import declared as discover

    surfaces.forget_declarations()
    try:
        declared = dict(surfaces.declared())
    finally:
        surfaces.forget_declarations()
    declarers = _platform_surface_declarers(
        {
            str(key): config.label
            for config, found in discover(
                surfaces.DECLARATION_MODULE, surfaces.DECLARATION_ATTRIBUTE
            )
            for key in found
        }
    )
    assert declarers == {"customer": "example_portal"}
    assert set(declared) - _product_surfaces() == {surfaces.STAFF, "customer"}
    assert declared[surfaces.STAFF] == surfaces.IMPLICIT_STAFF
    committed = json.loads(DOCUMENT.read_text())
    belongs = {role: surfaces.surface_for_role(role).key for role in committed["roles"]}
    assert {role for role, key in belongs.items() if key != surfaces.STAFF} == {"customer"}
    assert belongs["customer"] == "customer"


def _platform_surface_declarers(declarers: dict[str, str]) -> dict[str, str]:
    """`declarers` (surface key → declaring app) kept to the platform's apps."""
    platform = permissions_world.platform_labels()
    return {key: label for key, label in declarers.items() if label in platform}


def _product_surfaces() -> set[str]:
    """The surface keys an app outside the platform's partition declares."""
    from apps.core import surfaces
    from apps.core.discovery import declared as discover

    platform = permissions_world.platform_labels()
    return {
        str(key)
        for config, found in discover(surfaces.DECLARATION_MODULE, surfaces.DECLARATION_ATTRIBUTE)
        if config.label not in platform
        for key in found
    }


def _undocumented(answers: Any) -> list[str]:
    """The platform's declared policy keys `answers` holds no row for, sorted."""
    return sorted(set(permissions_world.platform_keys(authz.policies())) - set(answers))


def test_the_document_answers_every_declared_policy_key() -> None:
    """Every key a platform app's `POLICIES` declares is a row of the document's `answers`."""
    committed = json.loads(DOCUMENT.read_text(encoding="utf-8"))
    missing = _undocumented(committed["answers"])
    assert missing == [], f"declared and absent from the document: {missing}"


def _noun_baseline(root: Path) -> Path:
    path = root / "apps/gizmoes/tests/gear_authz_baseline.json"
    path.parent.mkdir(parents=True)
    return path


def test_a_missing_noun_baseline_is_red_naming_the_command_that_writes_it(
    tmp_path: Path, settings: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.BASE_DIR = tmp_path  # type: ignore[attr-defined]  # pytest-django's settings proxy
    monkeypatch.delenv("DJB_BASELINE_WRITE", raising=False)
    path = _noun_baseline(tmp_path)
    with pytest.raises(pytest.fail.Exception) as red:
        permissions_world.settle_baseline(path, {"roles": ["owner"], "answers": {}})
    assert str(red.value) == (
        "baseline missing: apps/gizmoes/tests/gear_authz_baseline.json — run "
        "DJB_BASELINE_WRITE=1 uv run pytest apps/gizmoes/tests/test_noun_authz.py once from "
        "your checkout and commit the file it writes"
    )
    assert not path.exists()


def test_the_write_variable_writes_the_noun_baseline_and_says_so(
    tmp_path: Path,
    settings: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings.BASE_DIR = tmp_path  # type: ignore[attr-defined]  # pytest-django's settings proxy
    monkeypatch.setenv("DJB_BASELINE_WRITE", "1")
    path = _noun_baseline(tmp_path)
    derived = {"roles": ["owner"], "answers": {"a.keep": {"owner": True}}}
    assert permissions_world.settle_baseline(path, derived) == []
    assert json.loads(path.read_text()) == derived
    assert capsys.readouterr().out == (
        "baseline written: apps/gizmoes/tests/gear_authz_baseline.json — read it, commit it; "
        "a later change in a role's answer is a finding here\n"
    )


def test_a_moved_noun_baseline_names_its_file_by_its_path_and_the_write_road(
    db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.example.tests import test_noun_authz as sweep

    monkeypatch.setattr(sweep, "settle_baseline", lambda path, derived: ["moved    planted"])
    with pytest.raises(AssertionError) as red:
        sweep.test_every_role_answers_every_widget_key_as_the_baseline_says()
    said = str(red.value).splitlines()
    assert said[0] == "apps/example/tests/widget_authz_baseline.json moved (1 lines):"
    assert said[2].strip() == (
        "A change you meant: re-run this test with DJB_BASELINE_WRITE=1, read the diff, commit it."
    )


def test_a_product_apps_keys_and_surfaces_are_outside_the_documents_pins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Planted: the worked apps read as a product's, their keys and surface leave both pins."""
    committed = json.loads(DOCUMENT.read_text(encoding="utf-8"))
    answers = {key: row for key, row in committed["answers"].items() if key != "widget.create"}
    assert "widget.create" in _undocumented(answers)
    assert _platform_surface_declarers({"customer": "example_portal"}) == {
        "customer": "example_portal"
    }
    platform = permissions_world.platform_labels() - {"example", "example_portal"}
    monkeypatch.setattr(permissions_world, "platform_labels", lambda: platform)
    assert "widget.create" not in _undocumented(answers)
    assert _platform_surface_declarers({"customer": "example_portal"}) == {}
    assert "customer" in _product_surfaces()
