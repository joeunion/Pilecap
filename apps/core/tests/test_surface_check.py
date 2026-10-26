"""House rule 85: every surface declaration is a closed question over the tree.

`check_surfaces` (`djb.E085`) reads each app's `surfaces.py` through the one
discovery walk and asks every field of every declaration whether the tree
declares what it names — the families off `families()`, the roles off
`role_declarations()`, the acts off the vocabulary's verbs and `ROADS`, the
screens off the face's route table through house rule 71's reader — and every
`SURFACE_HOSTS` key whether a surface answers to it. The two collisions are the
seam's own refusals (`core.surfaces.union`), reported one declaration at a
time. The worlds below are scratch declarations handed to the check in place of
the walk's answer — never a file in the tree — and every member they name that
must exist is read off the tree's own populations, so none is typed here.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from apps.core import discovery, surfaces
from apps.core.api.mount import route_table_paths
from apps.core.api.scopes import families
from apps.core.authz import role_declarations, vocabulary
from apps.core.checks import check_surfaces
from apps.core.surfaces import ALL, STAFF, Surface

E085 = "djb.E085"
#: The worked customer surface's shape (`apps/example_portal/surfaces.py`), with
#: every member drawn from this tree: the families, role, act and screens exist.
WORKED_SHAPE: dict[str, Any] = {"tenant_rule": "membership"}


def _app(label: str) -> SimpleNamespace:
    return SimpleNamespace(label=label)


def _declared(monkeypatch: pytest.MonkeyPatch, *found: tuple[str, dict[str, Surface]]) -> None:
    """Hand the check this world in place of the walk's answer for `surfaces.py` alone.

    Every other module — `policies.py`, `roles.py`, the renames the vocabulary
    builds from when its cache is cold — is answered by the real walk, so the
    planted world narrows the one population the check is asked about.
    """
    world = [(_app(label), declaration) for label, declaration in found]
    walk = discovery.declared

    def planted(module: str, attribute: str, **kwargs: Any) -> list[tuple[Any, dict[Any, Any]]]:
        if module == surfaces.DECLARATION_MODULE:
            return world
        return walk(module, attribute, **kwargs)

    monkeypatch.setattr(discovery, "declared", planted)


def _messages() -> list[str]:
    found = check_surfaces()
    assert all(message.id == E085 for message in found), found
    return [message.msg for message in found]


def _resolving(**changed: Any) -> Surface:
    """A declaration in the worked shape whose every field resolves, then `changed`."""
    screens = sorted(route_table_paths() or ())
    fields: dict[str, Any] = {
        "families": set(families()[:2]),
        "acts": {"read"} & {p.verb for p in vocabulary().values()},
        "roles": set(sorted(role_declarations())[:1]),
        "screens": {next(p for p in screens if "[" in p)},
        **WORKED_SHAPE,
    }
    fields.update(changed)
    return Surface(**fields)


def test_this_tree_answers_every_question() -> None:
    assert check_surfaces() == []


def test_an_undeclared_tree_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    _declared(monkeypatch)
    assert _messages() == []


def test_a_declaration_whose_every_field_resolves_is_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worked = _resolving()
    assert worked.families and worked.acts and worked.roles and worked.screens
    _declared(monkeypatch, ("portal", {"customer": worked}))
    assert _messages() == []


def test_a_family_no_tag_declares_names_the_family_and_the_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _declared(monkeypatch, ("portal", {"customer": _resolving(families={"frobnicate"})}))
    (message,) = _messages()
    assert "apps/portal/surfaces.py" in message
    assert "its families name 'frobnicate'" in message


@pytest.mark.parametrize(
    ("field", "word"),
    [("roles", "nobody"), ("acts", "polish"), ("screens", "/nowhere/[id]")],
)
def test_every_other_field_names_what_its_population_lacks(
    monkeypatch: pytest.MonkeyPatch, field: str, word: str
) -> None:
    _declared(monkeypatch, ("portal", {"customer": _resolving(**{field: {word}})}))
    (message,) = _messages()
    assert f"its {field} name {word!r}" in message


def test_the_total_value_is_never_a_finding(monkeypatch: pytest.MonkeyPatch) -> None:
    total = Surface(ALL, ALL, ALL, "addressed", ALL)
    _declared(monkeypatch, ("portal", {STAFF: total}))
    assert _messages() == []


def test_two_apps_declaring_one_key_are_refused_in_the_seam_s_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worked = _resolving()
    _declared(monkeypatch, ("portal_a", {"customer": worked}), ("portal_b", {"customer": worked}))
    (message,) = _messages()
    assert "'customer' is declared twice" in message
    assert "apps/portal_a/" in message and "apps/portal_b/" in message


def test_every_collision_is_reported_not_only_the_first(monkeypatch: pytest.MonkeyPatch) -> None:
    worked = _resolving()
    _declared(
        monkeypatch,
        ("portal_a", {"customer": worked, "partner": worked}),
        ("portal_b", {"customer": _resolving(roles=set())}),
    )
    found = _messages()
    assert len(found) == 2, found
    assert "is admitted by two surfaces, 'customer' and 'partner'" in found[0]
    assert found[0].startswith("apps/portal_a/surfaces.py: ")
    assert "'customer' is declared twice" in found[1]
    assert found[1].startswith("apps/portal_b/surfaces.py: ")


def test_a_key_whose_first_declaration_was_refused_is_still_declared_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refused declaration still claims its key, so the second app is named on the FIRST pass.

    `portal_a`'s `partner` is refused for its role (the role is `customer`'s);
    `portal_b` declares `partner` too. Had the refused one claimed nothing,
    `portal_b`'s would be accepted silently and the key collision would surface
    only after somebody fixed the first finding.
    """
    worked = _resolving()
    _declared(
        monkeypatch,
        ("portal_a", {"customer": worked, "partner": worked}),
        ("portal_b", {"partner": _resolving(roles=set())}),
    )
    found = _messages()
    assert len(found) == 2, found
    assert "is admitted by two surfaces, 'customer' and 'partner'" in found[0]
    assert found[0].startswith("apps/portal_a/surfaces.py: ")
    assert "'partner' is declared twice" in found[1]
    assert found[1].startswith("apps/portal_b/surfaces.py: ")
    assert "apps/portal_a/" in found[1] and "apps/portal_b/" in found[1]


def test_a_bound_host_key_nobody_declared_is_named(
    monkeypatch: pytest.MonkeyPatch, settings: Any
) -> None:
    _declared(monkeypatch, ("portal", {"customer": _resolving()}))
    settings.SURFACE_HOSTS = {STAFF: "localhost", "customer": "c.localhost", "nowhere": "n.local"}
    (message,) = _messages()
    assert "binds the surface 'nowhere'" in message


def test_the_route_table_reader_reads_a_dynamic_segment_as_the_table_spells_it(
    settings: Any, tmp_path: Path
) -> None:
    table = tmp_path / "frontend/src/kit/routes.ts"
    table.parent.mkdir(parents=True)
    table.write_text(
        "export const ROUTE_TABLE = [\n"
        '    { path: "/requests", job: "List.", surfaces: ["customer"] },\n'
        '    // { path: "/commented-out", job: "Not a row." },\n'
        '    { path: "/requests/[id]", job: "Read one.", surfaces: ["customer"] },\n'
        "];\n"
    )
    settings.BASE_DIR = tmp_path
    assert route_table_paths() == frozenset({"/requests", "/requests/[id]"})


def test_a_screen_declared_on_a_tree_with_no_route_table_says_so(
    monkeypatch: pytest.MonkeyPatch, settings: Any, tmp_path: Path
) -> None:
    worked = _resolving()
    settings.BASE_DIR = tmp_path
    _declared(monkeypatch, ("portal", {"customer": worked}))
    (message,) = _messages()
    assert "this tree has no route table" in message
