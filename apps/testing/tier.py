"""The `--loop` tier: a slow tier DERIVED, never a hand-marked list."""

from __future__ import annotations

import ast
import importlib.util
import pathlib
import re
import tokenize
from collections.abc import Callable
from typing import Any, NamedTuple, TypeVar

import pytest

import apps

# --- the `--loop` tier: a slow tier DERIVED, never a hand-marked list --------
#
# WHAT THIS IS FOR. The per-rung gate runs one pytest pass over the whole suite;
# the full gate at push runs two. A builder pays the whole suite on every
# iteration, and the measurement behind this tier says where that time
# actually goes: the tests that talk to a REAL ORGAN — the compose MinIO, a real
# time-skipping Temporal server, the compose Meilisearch — are a minority of the
# suite and a plurality of its wall clock. `--loop` skips them; **the full gate
# runs everything, unchanged**, so nothing is dropped, only deferred from
# loop-time to push-time. That trade is a declared blind spot, and is the
# point of the tier, not a side effect of it.
#
# THE POPULATION IS DERIVED, NEVER TYPED. A hand-marked list of slow tests is
# the drift class the whole rules engine exists against: it is right on the day
# it is written and wrong on the day somebody adds a test. So a test is in the
# slow tier IFF it REACHES an organ, and reach is computed two ways because this
# tree opts into its organs two ways:
#
#   1. BY FIXTURE CLOSURE. A fixture that hands a test a real organ declares
#      itself with `@organ("<kind>")` (`apps/files/tests/conftest.py::bucket`,
#      `apps/exports/tests/conftest.py::archive_bucket`,
#      `apps/search/tests/conftest.py::live_label`). A test reaches the organ if
#      that fixture is anywhere in its closure — `name2fixturedefs` is the
#      CLOSURE, so a fixture that requests `bucket` three levels down is caught
#      without anybody saying so.
#
#   2. BY MODULE SOURCE, for Temporal ONLY, and this is a finding rather than a
#      preference. There is NO Temporal organ fixture in this tree to reach:
#      `_no_dialling_temporal` below refuses the client factory for every test,
#      and a test that genuinely needs a server starts its own
#      `WorkflowEnvironment.start_time_skipping()` INSIDE ITS OWN BODY and
#      monkeypatches the factory at it (see that fixture's docstring). The opt-in
#      is a call site, not a fixture, in 21 modules across nine apps — two of
#      them importing it inside the test function rather than at module scope. So
#      the derivation reads the module's own source for the entry point's name.
#      It is still derived from the tree and still needs no list; it is coarser
#      (a whole module joins, not one test) and it over-includes a module that
#      merely NAMES the symbol, which errs toward running more in `--loop`.
#
# THE FLOORS ARE THE CANARY. Every failure mode of a derivation like this one is
# silent: a private pytest attribute renamed, a decorator dropped in a merge, a
# module read that started failing — each leaves a tier that deselects nothing
# or, worse, everything, and a green `--loop` that vouches for less than it says.
# So the derivation asserts a floor per organ kind before it deselects a single
# test, and an unmet floor is a hard refusal, never a quiet pass. An underived
# population is not an empty one — the same doctrine `secrets_scan.sh` states for
# the same reason.

#: The attribute `@organ(...)` leaves on a fixture function. Read off
#: `FixtureDef.func`, so it survives `@pytest.fixture` in either decorator order.
DJB_ORGAN_ATTRIBUTE = "__djb_organ__"

#: The organ with no fixture to reach — see (2) above.
DJB_TEMPORAL_ORGAN = "temporal"

#: The one call that starts a real time-skipping Temporal server. A test module
#: that names it is treated as reaching Temporal.
DJB_TEMPORAL_ENTRY_POINT = "WorkflowEnvironment"

#: The declared floor per organ kind: how many collected tests must be derived
#: as reaching it before this tier is allowed to deselect anything. One each,
#: deliberately — a floor tuned to today's count would redden on the next
#: legitimate deletion, and what has to be caught is a derivation that stopped
#: seeing the KIND at all.
DJB_ORGAN_FLOORS: dict[str, int] = {"minio": 1, "meili": 1, DJB_TEMPORAL_ORGAN: 1}
# --- the ALWAYS-ON set: cross-app tripwires, derived ------------------------
#
# WHAT THIS IS FOR. `quality/djb/scope.py` derives a SCOPE — the apps the active rung
# changed, plus the reverse-transitive `depends_on` closure over them — and
# `--loop` deselects everything outside it. That narrowing is sound for a test
# that lives inside one app and reads one app. It is NOT sound for a test that
# quantifies over the whole tree: a census that walks `get_app_configs()` and
# asserts something of every app is broken by a change in ANY app, including one
# no scope will ever contain. Deselecting those is how a scope stops being a
# narrowing and starts being a hole.
#
# So a module that READS A WHOLE POPULATION runs unconditionally, whatever the
# scope is. The population is DERIVED by the same source-reach technique the
# organ tier above already uses (`_module_organs`), for the same reason: a
# hand-marked list of cross-app tests is right on the day it is written and
# wrong on the day somebody adds a census.
#
# TWO PREDICATES WERE REJECTED and are recorded here so nobody re-tries them:
#
#   * "a module that imports two or more apps" — that is IMPORT TOPOLOGY, not
#     population reach. Half the suite imports `apps.core` beside its own app
#     and reaches no population at all; the predicate would make the always-on
#     set most of the tree and the scope worth nothing.
#   * "a module that imports `config.api`" — the same class, one hop narrower.
#     Reaching the router registry is not reaching the app registry, and the
#     modules it catches are mostly ordinary door tests that a scope already
#     covers through their own app.
#
# THE FLOORS COME IN TWO LAYERS, and the second layer is the point.
#
#   LAYER 1, per REACH KIND: at least one module must derive as reaching each
#   kind. This catches the whole derivation going blind — a renamed token, a
#   source read that started failing.
#
#   LAYER 2, per NAMED POPULATION: each named population must still hold the
#   number of members this tree has. Layer 1 alone is satisfied by EITHER of two
#   populations that share a reach kind, so either one can empty completely
#   while the floor stays green — a masking gap inside the floors themselves,
#   which is the one place nobody re-reads. Measured on this tree: five modules
#   derive `app_registry` reach and nine derive `model_registry`, and the
#   `lifecycle_registry_walkers` population is a subset of both — so
#   `app_registry >= 1` would survive the total disappearance of every lifecycle
#   walker. Naming the population and its count is what makes emptying one
#   member a floor failure rather than an arithmetic coincidence.
#
# WHAT A LAYER-2 FLOOR IS NOT: an identity check. It counts members; it cannot
# see a census gutted in place. The full gate's canary self-test and review are
# the cover for that, and no instrument here pretends otherwise.
#
# THE FLOORS ASSERT BEFORE ANYTHING IS DESELECTED. An unmet floor is a
# `pytest.UsageError`, which pytest reports as exit 4 and `scripts/check.sh`
# maps to exit 2; raised inside an xdist worker during collection it surfaces as
# INTERNALERROR and exit 3, which that same mapping treats identically. An
# underived population is not an empty one.
#
# THE SENTINEL BLOCK BELOW IS READ BY `quality/djb/scope.py`. It digests exactly
# these bytes into the loop ledger's key, so changing which tests are
# unconditional invalidates every banked `--loop` verdict rather than silently
# letting one vouch for a selection it never saw. Moving a declaration out of
# the block is therefore not a refactor — it is a verdict that stops being keyed
# on its own rules.

# >>> always-on-derivation >>>
#: Reach kind -> the source tokens that mean "this module reads that whole
#: population". Tokens, not imports: some readers reach the registry inside a
#: test body rather than at module scope, exactly as the Temporal organ
#: derivation above found.
DJB_REACH_TOKENS: dict[str, tuple[str, ...]] = {
    "app_registry": ("get_app_configs",),
    "model_registry": ("get_models(",),
    "introspect_registry": ("management.commands.introspect",),
    "absent_world": ("DJB_DISABLED_APPS",),
    "door_parity": ("DOOR_PAIR",),
    # THE DOOR REGISTRY: the two documents every door publishes, rendered
    # whole. `get_openapi_schema(` is the REST door's document over EVERY
    # mounted router — the call, not a receiver name, because the walkers spell
    # the receiver five ways (`api`, `the_api`, `ninja_api`, `mounted`,
    # `contract`) and no narrower token catches every one of them. `_list_tools(`
    # is the MCP door's whole catalogue as a test reads it: the helper that
    # returns every tool's published `outputSchema`. The bare wire method
    # `tools/list` was measured and rejected — the modules that spell it are
    # auth and throttle probes that ask for the list and read none of it. A
    # module that reads either document reads a route or a tool that ANY app
    # can add, rename or reshape, so a change in an app no scope pairs with it
    # can move its answer. Derived from what
    # `apps/core/tests/test_door_schema_parity.py` actually reads (both
    # documents, compared), never from a list of modules. The import of
    # `config.api` stays rejected (above): importing the router is not reading
    # the document it renders.
    "door_registry": ("get_openapi_schema(", "_list_tools("),
}

#: LAYER 1. One each, deliberately: what has to be caught here is a derivation
#: that stopped seeing the KIND at all. A kind a product declares in its drawer
#: (`DJB_REACH_KINDS`, below) is floored at one the same way, by
#: `_reach_floors`: a declared kind nothing reads is a token with a typo in it.
DJB_REACH_FLOORS: dict[str, int] = {kind: 1 for kind in DJB_REACH_TOKENS}

#: The populations INSIDE a reach kind whose tokens name two different
#: documents. Layer 1 over `door_registry` is satisfied by either half, so
#: either half could empty while it stayed green — the masking gap the LAYER 2
#: comment below names. Each token set here is one named population.
DJB_REACH_POPULATIONS: dict[str, tuple[str, ...]] = {
    "openapi_document_readers": ("get_openapi_schema(",),
    "mcp_catalogue_readers": ("_list_tools(",),
}

#: LAYER 2. Named populations and the number of MODULES this tree holds for
#: each — every one of these integers was DERIVED by collecting this suite,
#: never chosen — and the floor is an EQUALITY: a population BELOW its number
#: lost a member (a deletion, or a derivation going blind), and a population
#: ABOVE it gained one no declaration names. Both refuse, naming the members.
#: A legitimate deletion or addition reddens them and that is the trade: the
#: alternative is a floor that cannot tell a deletion from a derivation going
#: blind, and — the one-sided `<` this replaced — a floor that stays green while
#: its population grows past it, so the NEXT member moved aside is invisible.
#: Measured: four populations sat above their floors with no red, and
#: `apps_root_modules` went 3 → 4 → 5 → 6 with every join found later by a
#: drive's moved-aside case, never at the commit that joined.
#:
#: THE DERIVATION IS A COMMAND, NOT A WORD — pasted here because "derived" was
#: once true of four of these and false of the fifth for long enough that a
#: reader had no way to tell which. It counts MODULES over the WHOLE collection:
#: the populations are built in `pytest_collection_modifyitems` below BEFORE
#: anything is deselected, so the scope a run was asked for does not move these
#: numbers. Two of the seven are a path shape and five are tokens declared above
#: (`DJB_REACH_TOKENS`, `DJB_REACH_POPULATIONS`), matched as FIXED strings in the
#: module's CODE (`_code_of`: docstrings and comments blanked), so the `grep`s
#: below over-count a module that spells a token only in prose:
#:
#:   uv run pytest --collect-only -q | sed -n 's/::.*//p' | sort -u > /tmp/m
#:   grep -c '^apps/test_[^/]*\.py$'      /tmp/m                      # apps_root_modules
#:   xargs grep -lF 'DOOR_PAIR'         < /tmp/m | wc -l              # door_parity_census
#:   xargs grep -lF 'DJB_DISABLED_APPS' < /tmp/m | wc -l              # absent_world_consumers
#:   xargs grep -lF 'management.commands.introspect' < /tmp/m | wc -l # introspect_registry_readers
#:   grep -c 'tests/test_lifecycle\.py$'  /tmp/m                      # lifecycle_registry_walkers
#:   xargs grep -lF 'get_openapi_schema(' < /tmp/m | wc -l            # openapi_document_readers
#:   xargs grep -lF '_list_tools('     < /tmp/m | wc -l              # mcp_catalogue_readers
#:
#: RUN 2026-09-28 on a verifier box (aarch64 Linux), tree
#: b81706ae09bb0bc33e07650bb0cc62aeeaa57348, N = 4824 items collected over 328
#: modules → 6 · 17 · 4 · 7 · 9 · 20 · 2. The joiners since the 2026-09-27 run
#: (tree 88f17ef8: 5 · 14 · 3 · 7 · 8 · 18 · 2), each named with the change
#: that added it, because a number re-derived without its member is the shape
#: this paragraph exists to end:
#:
#:   door_parity_census 14 → 17: apps/djb_imports/tests/test_doors_over_the_wire.py
#:     (the imports app), apps/djb_notes/tests/test_doors_over_the_wire.py (the
#:     notes app), apps/djb_tags/tests/test_doors_over_the_wire.py (the tags app).
#:   absent_world_consumers 3 → 4: apps/core/tests/test_resource_first_urls.py —
#:     joined by a DOCSTRING sentence carrying the fixed-string token, not by a
#:     reader of the absent world; counted, as the property above says.
#:   lifecycle_registry_walkers 8 → 9: apps/djb_imports/tests/test_lifecycle.py.
#:   openapi_document_readers 18 → 20: apps/files/tests/test_archive_road.py,
#:     apps/djb_imports/tests/test_api.py.
#:   apps_root_modules 5 → 6: apps/test_absent_relative_imports.py — the fourth
#:     re-derivation of this one population (3 → 4 test_census_markers.py,
#:     4 → 5 test_retry_floor.py), and the reason it is now declared BY MEMBER.
#:   openapi_document_readers 20 → 21 (after that run, by the change that made
#:     a family refusal's published remedy the one the wire sends):
#:     apps/core/tests/test_remedies_published_equal_wire.py.
#:   apps_root_modules 6 → 7 (after that run, by the change that made a
#:     template-only test declared rather than deleted): apps/test_template_only.py
#:     — the census of `@pytest.mark.template_only`, an apps-root module because
#:     the marker's honour is this file's and this file belongs to no app.
#:   door_parity_census 17 → 18 (after that run, by the worked customer surface):
#:     apps/example_portal/tests/test_doors_over_the_wire.py — the portal's
#:     (rest, mcp) pair, driven at the customer host and the staff host.
#:   absent_world_consumers 4 → 5 (the same change): apps/core/tests/test_surfaces.py
#:     — its undeclared-tree case reads the world `DJB_DISABLED_APPS=example`
#:     makes (the example and what depends on it switched off).
#:   openapi_document_readers 21 → 22 (the wall for a narrowed role):
#:     apps/example_portal/tests/test_wall.py — the census held against the
#:     wire, each door's body read off the published document.
#:   openapi_document_readers 22 → 23: apps/files/tests/test_api.py.
#:   absent_world_consumers 5 → 6 (the one discovery walk): apps/core/tests/test_discovery.py
#:     — a planted app switched off through `DJB_DISABLED_APPS` is not walked.
#:   introspect_registry_readers 7 → 8 (the one mount reader):
#:     apps/core/tests/test_mount_reader.py — one cut to the mount reader reds
#:     `introspect`'s routes beside the other readers.
#:   door_parity_census 18 → 15, absent_world_consumers 6 → 3 (code only): left
#:     connections'/search's test_reads_ask.py, core's test_permissions_doors.py,
#:     test_index.py, test_resource_first_urls.py, test_surfaces.py.
#:   door_parity_census 15 → 16: apps/accounts/tests/test_doors_over_the_wire.py.
#:   door_parity_census 16 → 17: apps/example/tests/test_golden_verbs_parity.py.
#: **A rung that adds or removes a member of any population here changes its
#: declaration in the same commit, and names the member in this paragraph** (a
#: product: its drawer, below); the equality refuses the commit that forgot.
#:
#: WHERE IT IS ASSERTED, and where it is not. Over a collection of the WHOLE
#: tree — every run whose pytest arguments are the `apps` test path or none —
#: whichever branch below that run takes. A collection narrowed BY PATH (a
#: drive collecting a fixture world, a hand run over one directory) is not the
#: tree's population, so layer 2 asserts nothing there; layer 1 still does.
DJB_POPULATION_FLOOR_MEMBERS: dict[str, tuple[str, ...]] = {
    # CLOSED BY A PATH SHAPE (`apps/test_*.py`), so its members can be named and
    # a refusal can say WHICH one joined or left. The six token populations are
    # open — a fixed-string match over the collection — and keep integers: a
    # hand list of a population that is found rather than declared is the list
    # that goes stale first.
    "apps_root_modules": (
        "apps/test_absent_relative_imports.py",
        "apps/test_absent_world.py",
        "apps/test_census_markers.py",
        "apps/test_gate_liveness.py",
        "apps/test_retry_floor.py",
        "apps/test_template_only.py",
        "apps/test_temporal_guard.py",
    ),
}
DJB_POPULATION_FLOORS: dict[str, int] = {
    "apps_root_modules": len(DJB_POPULATION_FLOOR_MEMBERS["apps_root_modules"]),
    "door_parity_census": 17,
    "absent_world_consumers": 3,
    "introspect_registry_readers": 8,
    "lifecycle_registry_walkers": 9,
    "openapi_document_readers": 23,
    "mcp_catalogue_readers": 2,
}

# THE DRAWER DECLARES A PRODUCT'S MEMBERS; IT NEVER EDITS THE TEMPLATE'S. The
# declarations above are the TEMPLATE's populations and a product cannot change
# them: this file is template-owned and a fold overwrites it. A product with a
# seventh apps-root module declares it in its fixtures drawer, by NAME for a
# population the template declares by member and by COUNT for the others:
#
#     # apps/conftest_local.py
#     DJB_POPULATION_FLOOR_MEMBERS = {"apps_root_modules": ("apps/test_<acme>.py",)}
#     DJB_POPULATION_FLOOR_ADDENDS = {"door_parity_census": 2}
#
# The members asserted are the template's UNION the drawer's; the number
# asserted is that union's size plus any addend. It is the
# `DRAWER_RATCHET_PARTS` shape in `quality/gate.py`: the two halves are kept
# apart so the refusal can say which number lives in which file, because a
# reader told "floor 7" looks for a 7 written in neither. An addend on a
# member-declared population is still legal — it is how a drawer written
# before members existed keeps working — and it counts members the refusal
# then cannot name, which is why a member list is the better declaration.
#
# ONE READER, `_population_floors`, and nothing else reads either declaration.
# `test_loop_scope.sh` plants drawer rows and proves the refusal names the
# drawer's half — a declaration no reader reads would otherwise be a comment.
#
# RAISES ONLY. An addend is a non-negative integer and a member is a path, for
# a population the template declares; a negative addend would let a drawer
# silence the canary the floor is, and a name the template does not declare is
# a typo that would otherwise raise nothing. Each is a refusal naming the
# drawer, never a silent skip. A declared member path the tree lacks is refused
# at the floor, naming the file.
DJB_POPULATION_FLOOR_DRAWER = "apps/conftest_local.py"

#: The remedy every layer-2 refusal prints, in one place.
DJB_POPULATION_FLOOR_REMEDY = (
    "Raise the declaration and its paragraph in the same commit (lower them for a "
    "member that left), naming the member, in apps/testing/tier.py; a product: "
    f"DJB_POPULATION_FLOOR_MEMBERS / DJB_POPULATION_FLOOR_ADDENDS in {DJB_POPULATION_FLOOR_DRAWER}."
)


class PopulationFloor(NamedTuple):
    """One named population's declaration, as `_population_floors` read it."""

    template: int
    addend: int
    members: frozenset[str] | None


def _population_floors() -> dict[str, PopulationFloor]:
    """Each named population's declaration: the template's half and the drawer's.

    The ONE reader of `DJB_POPULATION_FLOOR_ADDENDS` and
    `DJB_POPULATION_FLOOR_MEMBERS` in the fixtures drawer. `addend` is the
    drawer's whole half — its extra members plus its addend — so the number
    asserted is always `template + addend`; `members` is the declared member
    set (template's union drawer's) for a population declared by member, and
    `None` for one declared by count. No drawer is the template's floors,
    unchanged.
    """
    template_members = {
        name: frozenset(paths) for name, paths in DJB_POPULATION_FLOOR_MEMBERS.items()
    }
    extra: dict[str, frozenset[str]] = {}
    addends: dict[str, int] = {}
    drawer = _fixtures_drawer()
    declared = getattr(drawer, "DJB_POPULATION_FLOOR_ADDENDS", None) if drawer else None
    if declared is not None:
        where = f"{DJB_POPULATION_FLOOR_DRAWER}'s DJB_POPULATION_FLOOR_ADDENDS"
        if not isinstance(declared, dict):
            raise pytest.UsageError(
                f"{where} is a {type(declared).__name__}, not a dict of population name to addend."
            )
        for name, addend in declared.items():
            if name not in DJB_POPULATION_FLOORS:
                raise pytest.UsageError(
                    f"{where} names {name!r}, which is not a population apps/testing/tier.py "
                    f"declares ({', '.join(sorted(DJB_POPULATION_FLOORS))}) — an addend for "
                    "no population raises nothing, so it is refused rather than ignored."
                )
            if isinstance(addend, bool) or not isinstance(addend, int) or addend < 0:
                raise pytest.UsageError(
                    f"{where}[{name!r}] is {addend!r} — an addend is a non-negative integer: "
                    "a drawer raises a floor by its own members and never lowers the template's."
                )
            addends[name] = addend
    named = getattr(drawer, "DJB_POPULATION_FLOOR_MEMBERS", None) if drawer else None
    if named is not None:
        where = f"{DJB_POPULATION_FLOOR_DRAWER}'s DJB_POPULATION_FLOOR_MEMBERS"
        if not isinstance(named, dict):
            raise pytest.UsageError(
                f"{where} is a {type(named).__name__}, not a dict of population name to paths."
            )
        for name, paths in named.items():
            if name not in template_members:
                raise pytest.UsageError(
                    f"{where} names {name!r}, which apps/testing/tier.py does not declare by "
                    f"member ({', '.join(sorted(template_members))}); a population "
                    "declared by count takes DJB_POPULATION_FLOOR_ADDENDS."
                )
            if not isinstance(paths, (tuple, list)) or not all(
                isinstance(path, str) and path.startswith("apps/") for path in paths
            ):
                raise pytest.UsageError(
                    f"{where}[{name!r}] is {paths!r} — members are a tuple of repo-relative "
                    "paths under apps/."
                )
            extra[name] = frozenset(paths) - template_members[name]
    floors: dict[str, PopulationFloor] = {}
    for name, number in DJB_POPULATION_FLOORS.items():
        mine = extra.get(name, frozenset())
        members = template_members[name] | mine if name in template_members else None
        floors[name] = PopulationFloor(number, len(mine) + addends.get(name, 0), members)
    return floors


def _population_floor_text(name: str, floor: PopulationFloor, derived: set[str]) -> str | None:
    """One population's refusal, or `None` when it holds its declaration exactly.

    Says the declared number, which half of it lives in which file, the
    derived count, and — the part an integer could never say — WHICH members:
    every derived member by path when the population is above its number, and
    for a population declared by member, the undeclared ones that joined and
    the declared ones that left (naming a file the tree lacks as such).
    """
    template, addend, members = floor
    total = template + addend
    missing = sorted(members - derived) if members is not None else []
    if len(derived) == total and not missing:
        return None
    if not addend:
        head = f"{name} (floor {total} in apps/testing/tier.py, derived {len(derived)} module(s))"
    else:
        head = (
            f"{name} (floor {total} = {template} in apps/testing/tier.py + {addend} in "
            f"{DJB_POPULATION_FLOOR_DRAWER}, derived {len(derived)} module(s))"
        )
    notes: list[str] = []
    if len(derived) > total:
        notes.append(
            f"ABOVE its declaration — the derived members are {', '.join(sorted(derived))}"
        )
    if members is not None:
        joined = sorted(derived - members)
        if joined and len(derived) != total:
            notes.append(f"not declared: {', '.join(joined)}")
    for path in missing:
        present = (DJB_REPO_ROOT / path).exists()
        notes.append(
            f"declared but not collected: {path}"
            + ("" if present else " (the tree has no such file)")
        )
    return head + ("" if not notes else " — " + "; ".join(notes))


# THE DRAWER DECLARES A REACH KIND; IT NEVER EDITS ONE. `DJB_REACH_TOKENS`
# above is the TEMPLATE's registries, and a product's own registry reader —
# a census over something the product registers, spelled with a call the
# template has never heard of — was always-on only if somebody edited this
# template-owned file, which the next fold overwrites. So the product declares
# the kind in its fixtures drawer, in the template's own shape:
#
#     # apps/conftest_local.py
#     DJB_REACH_KINDS = {"acme_registry": ("list_widgets(",)}
#
# and a module whose source carries `list_widgets(` is always-on, printed in
# the banner as `derived: acme_registry`, and floored at one like every kind:
# a declared kind nothing reads is a token with a typo in it.
#
# ONE READER, `_reach_tokens`. ADDS ONLY: a drawer kind that reuses a template
# kind's name is refused naming both files, because it would silently replace
# the template's tokens rather than add to them.
#
# AND THE DRAWER'S KEYS ARE A CLOSED SET. Every module-level name in the drawer
# spelled `DJB_*` is a declaration to one of the readers in this file, and a
# name no reader reads is a typo that would otherwise declare nothing, which
# reads exactly like a product with nothing to declare. So `_fixtures_drawer`
# refuses one, naming it, before any reader looks. Fixtures and helpers in the
# drawer are not `DJB_*` and are untouched by this.
DJB_REACH_KINDS_KEY = "DJB_REACH_KINDS"

#: Every `DJB_*` name the drawer may declare, and the one reader of each.
DJB_DRAWER_KEYS: dict[str, str] = {
    "DJB_POPULATION_FLOOR_ADDENDS": "_population_floors",
    "DJB_POPULATION_FLOOR_MEMBERS": "_population_floors",
    DJB_REACH_KINDS_KEY: "_reach_tokens",
}


def _drawer_unknown_keys(drawer: Any) -> list[str]:
    """The `DJB_*` names a drawer declares that no reader in this file reads."""
    return sorted(
        name for name in drawer.__dict__ if name.startswith("DJB_") and name not in DJB_DRAWER_KEYS
    )


def _fixtures_drawer() -> Any | None:
    """The fixtures drawer module, or `None` when the product has none.

    The ONE place the drawer is opened for a declaration, so the closed-key
    refusal cannot be skipped by whichever reader happens to run first.
    """
    # rule-88: the drawer is a test module beside the harness, never an installed app
    if importlib.util.find_spec("apps.conftest_local") is None:
        return None
    drawer = importlib.import_module("apps.conftest_local")
    unknown = _drawer_unknown_keys(drawer)
    if unknown:
        raise pytest.UsageError(
            f"{DJB_POPULATION_FLOOR_DRAWER} declares {', '.join(unknown)}, which no "
            f"reader in apps/testing/tier.py reads (the drawer's keys: "
            f"{', '.join(sorted(DJB_DRAWER_KEYS))}). A declaration nobody reads "
            "declares nothing and reads exactly like a drawer with nothing to "
            "declare, so it is refused rather than ignored."
        )
    return drawer


def _drawer_reach_kinds(drawer: Any | None) -> dict[str, tuple[str, ...]]:
    """The reach kinds a drawer declares, validated; `{}` when it declares none."""
    if drawer is None:
        return {}
    declared = getattr(drawer, DJB_REACH_KINDS_KEY, None)
    if declared is None:
        return {}
    where = f"{DJB_POPULATION_FLOOR_DRAWER}'s {DJB_REACH_KINDS_KEY}"
    if not isinstance(declared, dict):
        raise pytest.UsageError(
            f"{where} is a {type(declared).__name__}, not a dict of reach kind to source tokens."
        )
    kinds: dict[str, tuple[str, ...]] = {}
    for kind, tokens in declared.items():
        if not isinstance(kind, str) or not kind:
            raise pytest.UsageError(f"{where} names {kind!r} — a reach kind is a non-empty name.")
        if kind in DJB_REACH_TOKENS:
            raise pytest.UsageError(
                f"{where} declares {kind!r}, which apps/testing/tier.py already declares in "
                "DJB_REACH_TOKENS — a drawer adds a reach kind and never replaces the "
                "template's, so name the product's kind something the template does not."
            )
        if (
            not isinstance(tokens, (tuple, list))
            or not tokens
            or not all(isinstance(token, str) and token for token in tokens)
        ):
            raise pytest.UsageError(
                f"{where}[{kind!r}] is {tokens!r} — a reach kind is a non-empty tuple of "
                "non-empty source tokens; an empty one would derive no reader and floor "
                "nothing."
            )
        kinds[kind] = tuple(tokens)
    return kinds


#: The merged kinds, read once per session: a 4000-item collection asks per module.
_DJB_REACH_TOKENS_MERGED: list[dict[str, tuple[str, ...]]] = []


def _reach_tokens() -> dict[str, tuple[str, ...]]:
    """The template's reach kinds plus the drawer's — the ONE reader of `DJB_REACH_KINDS`."""
    if not _DJB_REACH_TOKENS_MERGED:
        _DJB_REACH_TOKENS_MERGED.append(
            {**DJB_REACH_TOKENS, **_drawer_reach_kinds(_fixtures_drawer())}
        )
    return _DJB_REACH_TOKENS_MERGED[0]


def _reach_floors() -> dict[str, int]:
    """LAYER 1 over every kind in force: the template's floors, and one per drawer kind."""
    return {**{kind: 1 for kind in _reach_tokens()}, **DJB_REACH_FLOORS}


# THE THIRD WAY IN, AND IT IS A DECLARATION RATHER THAN A DERIVATION.
#
# Everything above derives always-on from what a module READS through a Django
# registry. A census that walks the SOURCE TREE BY PATH reads no registry at
# all: `apps/core/tests/test_settings.py` parses `config/settings/base.py`,
# `apps/files/tests/test_storage_fence.py` rglobs every `*.py` under `apps/`,
# `apps/workflows/tests/test_services.py` does the same three times. No token
# above can see any of them, so a scope that does not contain their app
# deselects them — and a change in the app the census exists to police is
# exactly the change no scope will ever pair with the census. That is not a
# narrowing, it is a hole.
#
# So the module SAYS SO ITSELF, at column zero inside its first
# `DJB_CENSUS_MARKER_LINES` lines, in the marker grammar this tree already uses
# for `# drives:` in `scripts/tests/`:
#
#     <marker> <one line saying what population it walks>
#
# THE REASON IS MANDATORY AND ITS ABSENCE IS COULD-NOT-LOOK, never a silently
# unmarked module. The whole value of a declaration over a derivation is that a
# reader can DISAGREE with it, and a bare marker is a claim nobody can dispute.
#
# WHY A DECLARATION AT ALL, when everything else here is derived: the walk is
# spelled in an open set of ways, so the derivation below can only ever be a
# hand list of tokens — and a hand list is right on the day it is written. The
# marker is the half a human writes; `apps/test_census_markers.py` is the half
# that re-derives it, in BOTH directions, so neither half can go quiet alone.
DJB_CENSUS_MARKER = "# census: cross-app"

#: How far into a module the marker is looked for. A header, not a haystack: a
#: declaration buried at line 400 is not a declaration anybody reads.
DJB_CENSUS_MARKER_LINES = 40

# THE POPULATION: THE HALF OF THE DECLARATION A LOOP CAN ACT ON.
#
# A marker alone says "run me at every scope", and that is the right answer for
# a census and the wrong PRICE for every loop that could not possibly have moved
# what the census walks: fifteen marked modules ride on every scope today, and a
# rung that edited one template pays for the module that parses
# `config/settings/base.py` exactly as a rung that edited the settings does.
#
# So the declaration may also say WHICH FILES IT IS ABOUT, in the same line and
# immediately after the marker:
#
#     <marker> population=<glob>[,<glob>] <one line saying what it walks>
#
# The globs are checkout-relative, comma-joined, and shaped like `# drives:`
# (`scripts/gate_ledger.sh`) — `apps/**/*.py`, `config/settings/base.py`,
# `templates/**/*.html`. A census WITH a population runs whenever any changed
# file the caller named (`--djb-changed`) is inside any of its globs, and at
# every scope when the caller named none. A census with NO population runs
# always, exactly as it did before this grammar existed, and the banner SAYS SO
# — the silent default is the one a reader cannot audit.
#
# TWO REFUSALS, BOTH COULD-NOT-LOOK, for the reason the missing reason already
# is one: a `population=` with no globs after it, and a population whose globs
# match NOTHING on this tree (`_census_population_or_refuse`). A glob with a typo
# in it would otherwise deselect its census from every loop forever, and the
# only symptom of that is a green one.
#
# WHAT IT IS NOT: a claim anybody checked. Whether a declared population is the
# RIGHT population is a reviewer's finding, exactly as the reason is — which is
# why both live in the module's first lines, where a reviewer has one place to
# look. `apps/test_census_markers.py` re-derives that the globs resolve, never
# that they are the ones the walk needed.
DJB_CENSUS_POPULATION = "population="

#: The source tokens that mean "this module walks the source tree" — the
#: population the marker exists for, and the population the REVERSE census in
#: `apps/test_census_markers.py` re-derives the marked set from.
#:
#: A HAND LIST OF AN OPEN SET, legal only because of that reverse half: a
#: walker spelled with a fifth token escapes both halves identically, which is
#: this rule's declared blind spot. The day a miss names a fifth token is the
#: day it joins this tuple — and joining it changes these bytes, which moves the
#: loop ledger's key, which is the property the sentinels exist for.
DJB_WALK_TOKENS: tuple[str, ...] = (
    "source_tree(",
    ".rglob(",
    'glob("apps/',
    "glob('apps/",
    "pkgutil.iter_modules(",
)

#: Read kind -> the source tokens a census marker may stand on: marker evidence, never a way in.
#: A reader is always-on only by its own marker; `apps/test_census_markers.py` counts the rest.
DJB_DECLARED_READS: dict[str, tuple[str, ...]] = {
    "quality_reader": ('import_module("quality.', '"quality" /', "from quality"),
    "policy_reader": ("authz.policies(",),
}
# <<< always-on-derivation <<<

#: Per-module reach verdicts, cached beside the organ verdicts and for the same
#: reason: a 2600-test collection reads each module once.
_DJB_MODULE_REACH: dict[str, frozenset[str]] = {}

#: Per-module membership of the populations INSIDE a reach kind, filled by the
#: same read as `_DJB_MODULE_REACH` so a module's source is read once.
_DJB_MODULE_REACH_POPULATIONS: dict[str, frozenset[str]] = {}

_FixtureFunction = TypeVar("_FixtureFunction", bound=Callable[..., Any])

#: Set by `pytest_collection_modifyitems`, printed by
#: `pytest_report_collectionfinish`. The tier choice is PRINTED ON EVERY RUN: a
#: silent tier choice is an unfalsifiable one, and a reader who cannot see which
#: tier ran cannot tell a fast green from a whole-suite green.
_DJB_TIER_REPORT: list[str] = []

#: Per-module source verdicts, so a 2600-test collection reads each module once.
_DJB_MODULE_ORGANS: dict[str, frozenset[str]] = {}


def organ(name: str) -> Callable[[_FixtureFunction], _FixtureFunction]:
    """Declare that this fixture hands its test a REAL organ.

    The declaration lives on the fixture — the one place that knows — and the
    population of tests it reaches is derived from it. Adding an organ fixture
    anywhere under `apps/` puts every test that reaches it into the slow tier
    with no list to edit and no other file to touch.
    """

    def declare(func: _FixtureFunction) -> _FixtureFunction:
        setattr(func, DJB_ORGAN_ATTRIBUTE, name)
        return func

    return declare


def _module_organs(path: str) -> frozenset[str]:
    """The organs a test MODULE reaches by its own source (see (2) above)."""
    cached = _DJB_MODULE_ORGANS.get(path)
    if cached is not None:
        return cached
    try:
        source = pathlib.Path(path).read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - a module pytest just imported
        raise pytest.UsageError(
            f"the --loop tier could not read {path} to derive its organ reach ({exc}). "
            "An underived population is not an empty one: nothing was classified, "
            "so this is neither a fast tier nor a full one."
        ) from exc
    organs: frozenset[str] = frozenset()
    if DJB_TEMPORAL_ENTRY_POINT in source:
        organs = frozenset({DJB_TEMPORAL_ORGAN})
    _DJB_MODULE_ORGANS[path] = organs
    return organs


def _item_organs(item: pytest.Item) -> frozenset[str]:
    """Every organ this item reaches, by fixture closure and by module source."""
    organs: set[str] = set()
    # `_fixtureinfo` is pytest's own per-item fixture CLOSURE. It is private, and
    # that is why the floors below exist: if a future pytest renames it, this
    # returns nothing for everything, the floors go unmet and the tier refuses
    # rather than silently running the fast half of nothing.
    info: Any = getattr(item, "_fixtureinfo", None)
    name2fixturedefs: Any = getattr(info, "name2fixturedefs", None)
    if isinstance(name2fixturedefs, dict):
        for defs in name2fixturedefs.values():
            if not defs:
                continue
            # The LAST definition is the one this item resolves — a fixture name
            # overridden closer to the test wins, exactly as pytest resolves it.
            declared = getattr(getattr(defs[-1], "func", None), DJB_ORGAN_ATTRIBUTE, None)
            if isinstance(declared, str):
                organs.add(declared)
    path = getattr(item, "path", None)
    if path is not None:
        organs |= _module_organs(str(path))
    return frozenset(organs)


def _app_label(nodeid: str) -> str | None:
    """`apps/<label>/…` -> `<label>`; anything else -> no app.

    `apps/test_temporal_guard.py` and `apps/test_gate_liveness.py` sit at the
    root and belong to no app, so they are never anybody's own app.
    """
    parts = nodeid.split("/")
    if len(parts) >= 3 and parts[0] == "apps":
        return parts[1]
    return None


def _module_of(nodeid: str) -> str:
    """`apps/<x>/tests/test_<y>.py::test_z[p]` -> `apps/<x>/tests/test_<y>.py`.

    The populations below are counts of MODULES, so the split has to happen in
    one place: counting `::`-qualified nodeids instead multiplies a population
    by its parametrisation and turns a floor into a number nobody can predict.
    """
    return nodeid.split("::")[0]


def _module_reach(path: str) -> frozenset[str]:
    """The whole-population reach kinds this test MODULE has, by its own source.

    The same tolerant-read failure mode as `_module_organs`, and the same
    answer: a module pytest has just imported and this cannot read is a refusal,
    never an empty answer.
    """
    cached = _DJB_MODULE_REACH.get(path)
    if cached is not None:
        return cached
    try:
        source = pathlib.Path(path).read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - a module pytest just imported
        raise pytest.UsageError(
            f"the --loop scope could not read {path} to derive its cross-app reach "
            f"({exc}). An underived population is not an empty one: nothing was "
            "classified, so this is neither a scoped run nor a whole one."
        ) from exc
    code = _code_of(source)
    reach = frozenset(
        kind for kind, tokens in _reach_tokens().items() if any(token in code for token in tokens)
    )
    _DJB_MODULE_REACH[path] = reach
    _DJB_MODULE_REACH_POPULATIONS[path] = frozenset(
        name
        for name, tokens in DJB_REACH_POPULATIONS.items()
        if any(token in code for token in tokens)
    )
    return reach


def _code_of(source: str) -> str:
    """The module's source with every bare string statement and `#` comment blanked.

    Why-not the raw source: a token in prose reads nothing, and a prose trim must not move a floor.
    """
    try:
        tree = ast.parse(source)
        comments = [
            tok.start
            for tok in tokenize.generate_tokens(iter(source.splitlines(keepends=True)).__next__)
            if tok.type == tokenize.COMMENT
        ]
    except (SyntaxError, tokenize.TokenError):
        return source
    lines = source.splitlines(keepends=True)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            for index in range(node.lineno - 1, node.end_lineno or node.lineno):
                lines[index] = "\n"
    for row, col in comments:
        line = lines[row - 1]
        if line != "\n":
            lines[row - 1] = line[:col] + "\n"
    return "".join(lines)


def _module_reach_populations(path: str) -> frozenset[str]:
    """The `DJB_REACH_POPULATIONS` this module belongs to — read with its reach."""
    _module_reach(path)
    return _DJB_MODULE_REACH_POPULATIONS.get(path, frozenset())


#: Per-module census DECLARATIONS, cached beside the reach ones and for the same
#: reason. `("", ())` is a real answer here (this module declares nothing), which
#: is why the cache is checked with `is not None` rather than for truthiness.
_DJB_MODULE_CENSUS: dict[str, tuple[str, tuple[str, ...]]] = {}


def _module_census_reason(path: str) -> str:
    """The reason a module DECLARES for being a cross-app census; `""` unmarked."""
    return _module_census_declaration(path)[0]


def _module_census_population(path: str) -> tuple[str, ...]:
    """The globs a marked module DECLARES it is about; `()` when it names none.

    `()` is "no population — always", not "an empty population": the second is a
    refusal and it is made in `_module_census_declaration` below.
    """
    return _module_census_declaration(path)[1]


def _module_census_declaration(path: str) -> tuple[str, tuple[str, ...]]:
    """The reason and the population a module DECLARES; `("", ())` unmarked.

    The grammar is the sentinel block's: the marker at column zero, inside the
    first `DJB_CENSUS_MARKER_LINES` lines, followed by whitespace, an optional
    `population=<glob>[,<glob>]`, and a reason.

    THREE REFUSALS, AND ALL THREE ARE COULD-NOT-LOOK RATHER THAN AN EMPTY
    ANSWER — the same rule its two neighbours state, for the same reason. A
    module pytest has just imported and this cannot read is a refusal; a marker
    with NO reason is a refusal too, because the alternative is treating an
    unreadable declaration as an absent one, which is how a census silently
    stops being always-on at the moment somebody half-wrote its marker; and a
    `population=` with no globs after it is the same failure one clause along.
    The fourth refusal — a population that names nothing on the tree — needs a
    tree and is therefore `_census_population_or_refuse`'s, not this one's.
    """
    cached = _DJB_MODULE_CENSUS.get(path)
    if cached is not None:
        return cached
    try:
        head = pathlib.Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise pytest.UsageError(
            f"the --loop scope could not read {path} to derive its census declaration "
            f"({exc}). An underived population is not an empty one: a module this "
            "could not read would be deselected as if it had declared nothing."
        ) from exc
    reason = ""
    globs: tuple[str, ...] = ()
    for line in head[:DJB_CENSUS_MARKER_LINES]:
        if not line.startswith(DJB_CENSUS_MARKER):
            continue
        rest = line[len(DJB_CENSUS_MARKER) :]
        if rest and not rest[0].isspace():
            # `<marker>lication` is a different word, not this marker.
            continue
        reason = rest.strip()
        if reason.startswith(DJB_CENSUS_POPULATION):
            # THE POPULATION COMES FIRST AND IT IS ONE WORD. Anything after the
            # first whitespace is the reason, whole — a population is a machine's
            # half of the line and a sentence is a reader's, and putting the
            # machine's half first is what keeps the sentence from having to be
            # parsed at all.
            spec, _, reason = reason[len(DJB_CENSUS_POPULATION) :].partition(" ")
            globs = tuple(part for part in spec.split(",") if part)
            reason = reason.strip()
            if not globs:
                raise pytest.UsageError(
                    f"{path} declares an EMPTY POPULATION. The grammar is "
                    f"`{DJB_CENSUS_MARKER} {DJB_CENSUS_POPULATION}<glob>[,<glob>] "
                    "<reason>` — see the sentinel block in apps/testing/tier.py. A "
                    "population nobody can match against is not a narrowing, it is "
                    "a census that would be deselected by every scope, so this "
                    "refuses rather than reading it as an absent population."
                )
        if not reason:
            raise pytest.UsageError(
                f"{path} declares itself a cross-app census and gives NO REASON. "
                "The grammar is the marker at column zero followed by one line "
                "saying what population the module walks — see the sentinel block "
                "in apps/testing/tier.py. A declaration nobody can disagree with is "
                "not a declaration, so this refuses rather than reading the line "
                "as an absent marker."
            )
        break
    _DJB_MODULE_CENSUS[path] = (reason, globs)
    return reason, globs


def _assert_the_floors(
    reached_kinds: dict[str, set[str]], populations: dict[str, set[str]], whole: bool
) -> None:
    """Both layers of floors, or a `pytest.UsageError` naming what is wrong.

    LAYER 1 always (a reach kind nothing reads is a derivation gone blind,
    whatever was collected); LAYER 2 only over the whole tree
    (`_collects_the_whole_tree`) and as an EQUALITY with its members named
    (`_population_floor_text`). Raised before anything is deselected.
    """
    unmet_reach = sorted(
        f"{kind} (floor {floor}, derived {len(reached_kinds.get(kind, ()))} module(s))"
        for kind, floor in _reach_floors().items()
        if len(reached_kinds.get(kind, ())) < floor
    )
    unmet_population: list[str] = []
    if whole:
        for name, floor in sorted(_population_floors().items()):
            text = _population_floor_text(name, floor, populations.get(name, set()))
            if text is not None:
                unmet_population.append(text)
    if not unmet_reach and not unmet_population:
        return
    raise pytest.UsageError(
        "the --loop scope's always-on derivation is not answering, so "
        "NOTHING was deselected. "
        + ("LAYER 1 (reach kind): " + "; ".join(unmet_reach) + ". " if unmet_reach else "")
        + (
            "LAYER 2 (named population): "
            + "; ".join(unmet_population)
            + ". "
            + DJB_POPULATION_FLOOR_REMEDY
            + " "
            if unmet_population
            else ""
        )
        + "A scope narrows the suite to the active rung's apps and leans on the "
        "always-on set for everything that quantifies over the whole tree. "
        "A derivation that stopped seeing a kind reads exactly like a tree "
        "that no longer has one, an EMPTIED population reads exactly like a "
        "smaller suite, and a GROWN one is a member no declaration names — so "
        "this refuses instead of running a tier nobody can trust. The "
        "declaration and the floors are the sentinel block in apps/testing/tier.py; "
        "the scope that asked for this is quality/djb/scope.py."
    )


# --- the population: matching it, resolving it, and saying what it did -------

#: The checkout, for resolving a declared population against a real tree.
#: `apps/__init__.py` -> the directory above `apps`, the same arithmetic
#: `apps/test_census_markers.py::REPO_ROOT` does.
DJB_REPO_ROOT = pathlib.Path(apps.__file__).resolve().parents[1]


def _census_glob_regex(glob: str) -> str:
    """One checkout-relative glob as an anchored regex over a POSIX path.

    `fnmatch` is not this, and the difference is the whole reason for the eight
    lines: its `*` crosses `/`, so `apps/*/services.py` would match
    `apps/core/<sub>/services.py` and a population would silently be wider than
    the one its author wrote. Here `*` is one segment's worth, `**` is any
    number of whole segments, and a trailing `**` is everything below.
    """
    segments = glob.split("/")
    out = ["^"]
    for index, segment in enumerate(segments):
        last = index == len(segments) - 1
        if segment == "**":
            out.append(".*" if last else "(?:[^/]+/)*")
            continue
        out.append(
            "".join(
                "[^/]*" if char == "*" else "[^/]" if char == "?" else re.escape(char)
                for char in segment
            )
        )
        if not last:
            out.append("/")
    out.append("$")
    return "".join(out)


def _census_glob_matches(glob: str, path: str) -> bool:
    """Whether one checkout-relative path is inside one declared glob."""
    return re.match(_census_glob_regex(glob), path.lstrip("./")) is not None


def _census_verdict(module: str, globs: tuple[str, ...], changed: frozenset[str]) -> str | None:
    """`None` when this census still runs; the SENTENCE saying why not when it does not.

    Two ways to be kept and they are not the same claim: a census with no
    population is unconditional (the grammar's default, printed by
    `_census_banner`), and a caller that named no changed files narrows nothing
    at all — the `--djb-scope-narrow` rule, which is that nothing narrows unless
    somebody asked.
    """
    if not globs or not changed:
        return None
    if any(_census_glob_matches(glob, path) for glob in globs for path in changed):
        return None
    return f"{module}: population {','.join(globs)} does not contain the change — deselected"


#: Resolved populations, keyed on the module and the root they were resolved
#: against: the check walks the tree, and a per-item walk over fifteen modules
#: is the difference between a banner and a cost.
_DJB_CENSUS_RESOLVED: dict[tuple[str, str], tuple[str, ...]] = {}


def _census_population_or_refuse(path: str, root: pathlib.Path) -> tuple[str, ...]:
    """The module's population, REFUSING one whose globs name nothing on this tree.

    An underived population is not an empty one — the rule the reach and the
    reason derivations above both make. Read as "no files", a glob with a typo in
    it deselects its census from every loop forever and the only symptom is a
    green one.
    """
    key = (path, str(root))
    cached = _DJB_CENSUS_RESOLVED.get(key)
    if cached is not None:
        return cached
    globs = _module_census_population(path)
    # `next(..., None)` rather than a list: the question is whether the glob
    # reaches ANYTHING, and `apps/**/*.py` over this tree is four thousand paths.
    missing = [glob for glob in globs if next(iter(root.glob(glob)), None) is None]
    if missing:
        raise pytest.UsageError(
            f"{path} declares population {','.join(missing)}, which names NOTHING "
            f"under {root}. An underived population is not an empty one: read as "
            "an empty set, this census would be deselected by every scope forever "
            "and the only symptom would be a green loop. Fix the glob, or drop the "
            "`population=` clause and let the census run always."
        )
    _DJB_CENSUS_RESOLVED[key] = globs
    return globs


#: The counts-file field that carries one always-on module and its way in.
DJB_ALWAYS_ON_FIELD = "always_on_module"
#: The counts-file field carrying `_impact_selection`'s line.
DJB_IMPACT_FIELD = "impact"

#: The seeded census's own declaration, at column zero — the line
#: `quality/djb/scope.py`'s `loop_scope__census_modules` greps for.
DJB_CENSUS_SEEDED_BY = "CENSUS_SEEDED_BY"

_DJB_MODULE_SEEDS: dict[str, bool] = {}


def _module_seeds_a_census(path: str) -> bool:
    """Whether the module declares `CENSUS_SEEDED_BY` at column zero."""
    cached = _DJB_MODULE_SEEDS.get(path)
    if cached is not None:
        return cached
    try:
        lines = pathlib.Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:  # pragma: no cover - a module pytest just imported
        raise pytest.UsageError(
            f"the --loop scope could not read {path} to tell a seeded census from an "
            f"edited module ({exc}). An underived population is not an empty one."
        ) from exc
    seeds = any(line.startswith(DJB_CENSUS_SEEDED_BY) for line in lines)
    _DJB_MODULE_SEEDS[path] = seeds
    return seeds


def _way_in(nodeid: str, reach: frozenset[str]) -> str:
    """How an always-on module got in, in `_is_always_on`'s own order.

    `structural` (it belongs to no app, so no scope can hold it), `derived:
    <kind>[,<kind>]` (it reads a whole registry), or `declared` (it carries the
    census marker). The fourth way, `seeded`, is not unconditional and is named
    where the kept set is known.
    """
    if _app_label(nodeid) is None:
        return "structural"
    if reach:
        return "derived: " + ",".join(sorted(reach))
    return "declared"


def _always_on_headline(ways: dict[str, str], derived: int, dropped: int) -> str:
    """The one line that heads the list, and says how it differs from `derived`.

    TWO NUMBERS WOULD OTHERWISE SIT UNDER ONE LABEL: the derivation's module
    count is taken BEFORE the fast tier, and the list is what RAN after it —
    an organ-reaching census outside the rung's own apps is dropped whole there,
    and a seeded census joins after the derivation. The line names both moves.
    """
    seeded = sum(1 for way in ways.values() if way == "seeded")
    parts = [f"{derived} derived before the tier"]
    if dropped:
        parts.append(
            f"{dropped} dropped whole by the fast tier (organ-reaching, outside the own apps)"
        )
    if seeded:
        parts.append(f"{seeded} seeded by the change")
    return f"always-on: {len(ways)} modules ran — " + ", ".join(parts)


def _always_on_banner(ways: dict[str, str], derived: int, dropped: int) -> list[str]:
    """`always-on: <n> modules …`, then every module with its way in, one line each.

    An always-on set nobody can enumerate is one nobody audits — and a count
    alone cannot say WHICH module a scope kept, or why, which is the question a
    reader has when a cross-app census did or did not run.
    """
    return [f"  {_always_on_headline(ways, derived, dropped)}"] + [
        f"    {module} {way}" for module, way in sorted(ways.items())
    ]


def _census_banner(declared: dict[str, tuple[str, ...]], changed: frozenset[str]) -> list[str]:
    """What the run SAYS about the declared censuses it narrowed.

    An always-on set nobody can enumerate is one nobody audits — the argument
    `scripts/check.sh`'s own declared-census listing is printed for. This is the
    narrowing half of that: how many declarations there are, how many of them
    are bounded by a population, how many survived this run's changed files, and
    the module-by-module sentence for every one that did not.
    """
    deselected = sorted(
        sentence
        for module, globs in declared.items()
        if (sentence := _census_verdict(module, globs, changed)) is not None
    )
    unbounded = sorted(module for module, globs in declared.items() if not globs)
    lines = [
        f"  declared censuses: {len(declared)} declared, "
        f"{len(declared) - len(unbounded)} with a population, "
        f"{len(declared) - len(deselected)} selected"
    ]
    if unbounded:
        lines.append("  (no population — always): " + ", ".join(unbounded))
    lines += [f"  {sentence}" for sentence in deselected]
    return lines
