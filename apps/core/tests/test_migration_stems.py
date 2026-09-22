# census: cross-app population=apps/*/migrations/*.py every migration filename in the tree
"""Every migration's stem is unique within its app — the fold's precondition.

`manage.py fold_migrations` (ADR core-28) grafts an arriving template chain onto
a product's own leaf, and it has to survive a dependency that names an ancestor
an EARLIER fold already renumbered: the release after next depends on
`("accounts", "0010_default_role_is_a_key")` while the product's tree now spells
that migration `0012_default_role_is_a_key`. The only thing a renumbering
preserves is the stem — the part after `NNNN_` — so the stem is the handle, and
resolving by it is a closed question only while no app ships two migrations with
the same stem.

**This module is that precondition, measured rather than assumed.** The command
refuses at runtime when a stem resolves to two migrations (it says so, by name,
and moves nothing), so a duplicate in a PRODUCT's own tree is handled. What this
test buys is the other half: the TEMPLATE never ships one, so a product folding
a release never meets the refusal because of us. A release that renamed
`0018_roles_are_keys` into a second migration with the same stem would make
every downstream fold that touches the app unresolvable, and the first anybody
would hear of it is a consumer's fold three weeks later.

**DOES NOT COVER — declared.** A product's own migrations, deliberately: this
walks the tree it is run in, so in the template it measures the template and in
a product it measures both. It says nothing about whether a stem is a GOOD name,
and nothing about cross-app collisions (a stem is only ever resolved within one
app, so two apps sharing one is not a collision at all).
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings

ROOT = Path(settings.BASE_DIR)

#: `0012_default_role_is_a_key` -> `("0012", "default_role_is_a_key")`. The same
#: shape `fold_migrations` splits by; spelled again here rather than imported so
#: this precondition does not depend on the thing it is a precondition for.
_NUMBERED = re.compile(r"^(\d+)_(.+)$")


def duplicate_stems(names: list[str]) -> dict[str, list[str]]:
    """`{stem: [the migrations that share it]}` for every stem named more than once.

    A pure function over names so the detector itself can be driven with a
    planted duplicate (below) without writing a file into a real migrations
    directory — the tree is the census's subject, not its fixture.
    """
    by_stem: dict[str, list[str]] = {}
    for name in names:
        match = _NUMBERED.match(name)
        if match is None:
            continue
        by_stem.setdefault(match.group(2), []).append(name)
    return {stem: sorted(shared) for stem, shared in by_stem.items() if len(shared) > 1}


def _migration_names_by_app() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for directory in sorted(ROOT.glob("apps/*/migrations")):
        if not directory.is_dir():
            continue
        found[directory.parent.name] = sorted(
            path.stem for path in directory.glob("[0-9]*.py") if path.is_file()
        )
    return found


def test_no_app_ships_one_migration_stem_twice() -> None:
    collisions = {
        f"{app}.{stem}": shared
        for app, names in _migration_names_by_app().items()
        for stem, shared in duplicate_stems(names).items()
    }
    assert not collisions, (
        "two migrations in one app share a stem, and a stem is the only handle a fold has "
        "on an ancestor an earlier fold renumbered (ADR core-28): "
        + "; ".join(f"{key} -> {', '.join(names)}" for key, names in sorted(collisions.items()))
        + ". Rename one of them before the release ships."
    )


def test_the_walk_found_every_apps_migrations() -> None:
    """The floor: a census that walked nothing passes vacuously.

    Named as a POPULATION rather than a count — every app that has a migrations
    directory contributed at least one name — so an app going blind is a failure
    here rather than a number nobody re-derives.
    """
    directories = {path.parent.name for path in ROOT.glob("apps/*/migrations") if path.is_dir()}
    assert directories, "no app under apps/ has a migrations directory — the walk found nothing"
    walked = _migration_names_by_app()
    assert set(walked) == directories
    empty = sorted(app for app, names in walked.items() if not names)
    assert not empty, f"these apps have a migrations directory and no migrations in it: {empty}"


def test_the_detector_sees_a_planted_duplicate() -> None:
    """The falsifier, on the detector rather than on the tree.

    `apps/core` really ships `0018_roles_are_keys`; a release that also shipped
    `0099_roles_are_keys` is the failure this module exists for, and it is driven
    here as a planted pair of NAMES. Planting the file itself would mean writing
    into `apps/core/migrations/` — found state, and the one directory a rung must
    never leave a stray file in.
    """
    assert duplicate_stems(["0017_x", "0018_roles_are_keys"]) == {}
    assert duplicate_stems(["0018_roles_are_keys", "0099_roles_are_keys"]) == {
        "roles_are_keys": ["0018_roles_are_keys", "0099_roles_are_keys"]
    }
