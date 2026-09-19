"""P7.2 — the `comms` Phase-W sweep, measured rather than argued.

Three things live here and they are deliberately different shapes:

* **`comms_census(...)`** — `allows(actor, key, obj)` over every key this app
  owns × the three template roles × four row states, as plain JSON-shaped data.
  It is the same function on both trees: `authz_baseline.json` beside this file
  was written by running it on the sweep's own baseline tree, and
  `test_the_apps_authorization_matrix_equals_the_baseline` re-runs it here and
  compares. A baseline DERIVED by one function beats a baseline typed from
  somebody's reading of the old code.
* **`test_the_apps_policies_read_no_role`** — the sweep's own property. A
  predicate answers "may this person do this to THAT row", never "what role are
  they" (rule 54 (c), architect §C7's code half).
* **`test_no_comms_predicate_reads_the_row`** — the belt under the census's one
  simplification, declared below.

## What the row dimension is, and the belt under it

`allows` can only be reached by `obj` in two ways: `where_of(actor, obj)` reads
`obj.organization` to decide the NODE the question is asked at, and the app's
own predicate may read the row itself. **No comms predicate reads the row** —
before the sweep they read the actor's membership row and after
it the three survivors return a constant — so the node is the whole of what a
row can change here, and the census varies the node with one real org-scoped
row per node rather than minting a row of all eight kinds three times over.

That is a simplification and it is not left to trust:
`test_no_comms_predicate_reads_the_row` fails the moment any predicate in this
app's `POLICIES` touches its `obj` parameter, which is exactly the day this
census would start measuring an approximation instead of the leg.
"""

from __future__ import annotations

import ast
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings

from apps.accounts.services import create_user
from apps.comms.services import create_recipient
from apps.conftest import PASSWORD
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.authz import allows, renamed_permissions, vocabulary
from apps.core.models import Organization, Tenant
from apps.core.services import add_membership, create_organization, create_tenant, root_organization

pytestmark = pytest.mark.django_db

#: The three roles the sweep's matrix asks about — the platform role and the
#: template's two declarations. A product that declared others would widen this
#: and re-derive its own baseline.
SWEEP_ROLES: tuple[str, ...] = ("owner", "admin", "member")

#: The four row states, named for what they are rather than for the node they
#: happen to use. `none` is the ABSTRACT cell — "may this person do this kind of
#: thing here at all" — and the other three are the three answers `where_of`
#: can give: the acting hat, a node under it, and a node the hat does not cover.
ROW_STATES: tuple[str, ...] = (
    "none",
    "row_at_the_hat",
    "row_below_the_hat",
    "row_in_a_sibling_branch",
)

#: The tree `authz_baseline.json` was derived on, and the command that derived
#: it — carried INTO the document so the file says how to re-make itself.
BASELINE_SHA = "4f4fbc69"
BASELINE_COMMAND = (
    "uv run python manage.py shell -c "
    '"from apps.comms.tests.test_authz_sweep import write_authz_baseline as w; '
    "w('apps/comms/tests/authz_baseline.json')\" — run IN PLACE on the rung's own "
    "baseline tree (4f4fbc69, the tree `rung_start.sh` reset to, before a byte of "
    "the rung was written), which IS the baseline rather than a scratch clone of it"
)

BASELINE_PATH = "apps/comms/tests/authz_baseline.json"


# --- the world ------------------------------------------------------------------


@dataclass(frozen=True)
class SweepWorld:
    """`root → A → A1` and a sibling `B`, with all three hats AT A.

    The hats are at `A` and not at the root on purpose: a sibling branch is only
    outside somebody's reach when their hat does not cover it, and a matrix
    whose three people all act as the root would have had no outside cell at all.
    """

    tenant: Tenant
    root: Organization
    a: Organization
    a1: Organization
    b: Organization
    actors: dict[str, Actor]
    rows: dict[str, Any]


def build_sweep_world() -> SweepWorld:
    """Every node, person and row through a service. No raw writes."""
    suffix = uuid.uuid4().hex[:8]
    tenant = create_tenant(name=f"Sweep {suffix}", slug=f"sweep-{suffix}", actor=system_actor())
    system = system_actor(tenant=tenant)
    root = root_organization(tenant=tenant)
    a = create_organization(tenant=tenant, parent=root, name="A", slug="a", actor=system)
    a1 = create_organization(tenant=tenant, parent=a, name="A1", slug="a1", actor=system)
    b = create_organization(tenant=tenant, parent=root, name="B", slug="b", actor=system)

    actors: dict[str, Actor] = {}
    for role in SWEEP_ROLES:
        user = create_user(email=f"{role}-{suffix}@example.com", password=PASSWORD)
        add_membership(user=user, tenant=tenant, organization=a, role=role, actor=system)
        actors[role] = actor_for(user=user, tenant=tenant, org=a)

    rows = {
        "row_at_the_hat": create_recipient(
            tenant=tenant,
            actor=system_actor(tenant=tenant, org=a),
            email=f"at-hat-{suffix}@example.com",
        ),
        "row_below_the_hat": create_recipient(
            tenant=tenant,
            actor=system_actor(tenant=tenant, org=a1),
            email=f"below-{suffix}@example.com",
        ),
        "row_in_a_sibling_branch": create_recipient(
            tenant=tenant,
            actor=system_actor(tenant=tenant, org=b),
            email=f"sibling-{suffix}@example.com",
        ),
    }
    return SweepWorld(tenant=tenant, root=root, a=a, a1=a1, b=b, actors=actors, rows=rows)


# --- the census -----------------------------------------------------------------


def comms_keys() -> list[str]:
    """Every key this app owns, DERIVED — the four verbs per comms kind plus
    whatever `apps/comms/policies.py` declares. Never a hand list: a hand list
    is a second opinion about the vocabulary and it goes stale in silence.
    """
    return sorted(action for action, word in vocabulary().items() if word.app == "comms")


def comms_census(
    keys: Sequence[str],
    actors: Mapping[str, Actor],
    rows: Mapping[str, Any],
) -> dict[str, dict[str, dict[str, bool]]]:
    """`allows(actor, key, obj)` for every key × every role × every row state."""
    return {
        str(key): {
            role: {
                state: bool(allows(actor, str(key), None if state == "none" else rows[state]))
                for state in ROW_STATES
            }
            for role, actor in sorted(actors.items())
        }
        for key in sorted(keys)
    }


Census = Mapping[str, Mapping[str, Mapping[str, bool]]]

#: How one cell of the census is addressed in `accepted_deltas` and in every
#: failure message: `<key>/<role>/<state>`. One spelling, so a reason in the
#: document and a line in a report name the same thing.
CELL = "{key}/{role}/{state}"


def cell_answer(census: Census, address: str) -> bool:
    """The one answer a `<key>/<role>/<state>` address names."""
    key, role, state = address.split("/")
    return bool(census[key][role][state])


def moved_cells(expected: Census, actual: Census) -> list[str]:
    """Every cell whose answer differs, as sorted addresses.

    Addresses rather than lines, because the matrix test compares this list to
    `accepted_deltas` **exactly** — count and shape, the `files` sweep's form
    (`apps/files/tests/test_authz_sweep.py`) — and a list carrying before/after
    text could never be compared to anything.
    """
    return sorted(
        CELL.format(key=key, role=role, state=state)
        for key in expected
        for role in expected[key]
        for state in ROW_STATES
        if expected[key][role][state] != actual[key][role][state]
    )


def comms_authz_matrix() -> dict[str, Any]:
    """The whole baseline document: the keys, the roles, the states, the answers."""
    world = build_sweep_world()
    return {
        "_": (
            "DERIVED, never typed. Every cell is `allows(actor, key, obj)` for the comms "
            "app's own keys on a tenant shaped root -> A -> A1 with a sibling B, three "
            "people hatted at A, one per template role, and one Recipient row per node. "
            "The test re-runs the same census on this tree and asserts equality; a moved "
            "answer prints (key, role, state, before, after)."
        ),
        "_baseline": BASELINE_SHA,
        "_command": BASELINE_COMMAND,
        "roles": list(SWEEP_ROLES),
        "row_states": list(ROW_STATES),
        "accepted_deltas": {},
        "answers": comms_census(comms_keys(), world.actors, world.rows),
    }


def write_authz_baseline(path: str) -> str:
    """Derive the matrix and write it as the JSON document, sorted and stable.

    It writes the FILE rather than printing it: `manage.py shell` prints a
    banner of its own on stdout and a redirect would bake it into the document —
    a baseline nobody can re-derive byte for byte is a baseline that stops being
    checked. `permissions_world.write_flat_product_baseline`'s reason, one app
    over.
    """
    target = Path(path)
    target.write_text(
        json.dumps(comms_authz_matrix(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return str(target)


# --- P7.2.2 · the matrix equals the baseline -------------------------------------


def test_the_apps_authorization_matrix_equals_the_baseline() -> None:
    """Every answer comms gave on the baseline tree, unchanged — bar the recorded few.

    **The population first, then the cells.** A comparison that only printed
    moved answers would be silent about the one failure it cannot express: a key
    that LEFT the vocabulary. Its cells do not move, they stop existing. So the
    key sets are compared first, and a key gone from this tree is legal only
    when this app renamed it (`RENAMED_PERMISSIONS`, which keeps the old word
    answering) or when the document records the retirement by name.

    **`accepted_deltas` is the sweep's own confession, and it is keyed by CELL.**
    `<key>/<role>/<state>`, one entry per moved answer with its own reason — the
    shape `apps/files/tests/test_authz_sweep.py` uses, adopted here so a sweep
    that moves four cells cannot list one key and be excused for all twelve of
    its cells. The moved list is compared to that set **exactly**: a cell that
    moved and is not listed is a red, and a cell listed that did not move is a
    red too (the next test says why that half matters).
    """
    document = json.loads((Path(settings.BASE_DIR) / BASELINE_PATH).read_text())
    expected: dict[str, dict[str, dict[str, bool]]] = document["answers"]
    accepted: dict[str, str] = document["accepted_deltas"]

    assert document["roles"] == list(SWEEP_ROLES)
    assert document["row_states"] == list(ROW_STATES)
    # The floor names the population and its size, not merely "at least one":
    # a census that silently stopped deriving one half cannot pass this.
    #
    # THIRTY-NINE, AND IT WAS FORTY-THREE. The document is re-derived whenever a
    # sweep's accepted deltas have become landed history — otherwise the list of
    # excuses grows forever and the baseline stops being a picture of anything.
    # The four that left are the words P7.2 renamed (`RENAMED_PERMISSIONS`):
    # once the rename is on main they are no longer separate entries in
    # `vocabulary()`, they answer through their successors, and their cells stop
    # existing rather than moving — which is exactly the failure the key-set
    # comparison below exists to catch, and why it runs before the cells.
    assert len(expected) == 39, len(expected)
    assert sum(len(cells) for cells in expected.values()) == 39 * len(SWEEP_ROLES)

    world = build_sweep_world()
    actual = comms_census(sorted(expected), world.actors, world.rows)

    live = set(comms_keys())
    renames = renamed_permissions()
    removed = sorted(key for key in expected if key not in live)
    unexplained = [
        key
        for key in removed
        if key not in renames and not any(cell.startswith(f"{key}/") for cell in accepted)
    ]
    assert unexplained == [], unexplained

    moved = moved_cells(expected, actual)
    detail = [
        f"{cell}: {cell_answer(expected, cell)} -> {cell_answer(actual, cell)}" for cell in moved
    ]
    assert moved == sorted(accepted), {"moved": detail, "accepted": sorted(accepted)}


def test_a_flipped_cell_is_red() -> None:
    """**The census, driven.** One flipped answer in a COPY of the document, and
    the comparison above reports exactly that cell.

    Without this, the equality test could be comparing a document against itself
    — the shape that reads green while proving nothing, and it is the shape a
    census keyed on the tree it was derived from falls into most easily. The
    victim is built here: a dict copied in memory, never the committed file
    (rung-execution §2, a destructive demonstration creates its own victim).
    """
    document = json.loads((Path(settings.BASE_DIR) / BASELINE_PATH).read_text())
    expected: dict[str, dict[str, dict[str, bool]]] = document["answers"]

    key, role, state = "message_template.create", "admin", "none"
    flipped = {
        name: {actor: dict(cells) for actor, cells in roles.items()}
        for name, roles in expected.items()
    }
    flipped[key][role][state] = not flipped[key][role][state]

    world = build_sweep_world()
    actual = comms_census(sorted(expected), world.actors, world.rows)
    assert moved_cells(flipped, actual) == [f"{key}/{role}/{state}"]


def test_every_accepted_delta_names_a_cell_that_actually_moved() -> None:
    """An accepted delta nobody exercises is a hole somebody widened by hand.

    The list is a confession, not a permission slip: a cell listed there that
    answers today exactly as it did on the baseline has no business being
    listed, and the entry would then be silently excusing a future move. The
    exact comparison in the matrix test is what enforces that half; this one
    checks the entries are addressable and reasoned.
    """
    document = json.loads((Path(settings.BASE_DIR) / BASELINE_PATH).read_text())
    expected: dict[str, dict[str, dict[str, bool]]] = document["answers"]
    accepted: dict[str, str] = document["accepted_deltas"]

    for cell, reason in accepted.items():
        parts = cell.split("/")
        assert len(parts) == 3, f"{cell} is not a <key>/<role>/<state> cell address"
        key, role, state = parts
        assert role in SWEEP_ROLES and state in ROW_STATES, cell
        assert key in expected, f"{key} is accepted but was never in the baseline"
        assert len(reason) >= 24, f"{cell}'s accepted delta needs a reason, not a shrug"


# --- P7.2.2 · the predicates read no role ----------------------------------------

#: The words that mean "how much authority does this person have", read off the
#: rung's own criterion. `grep -cE` over `apps/comms/policies.py` is the pasted
#: form; this is the same question asked where it cannot go stale.
ROLE_BY_VALUE = (
    "is_privileged",
    "ADMIN_RANK",
    "rank(",
    "effective_role",
    "actor_role",
    "ROLE_RANK",
)


def test_the_apps_policies_read_no_role() -> None:
    """A predicate answers "may this person do this to THAT row", never "what role".

    A role is DATA a tenant owns; a rank table beside it is a second opinion no
    tenant can edit (rule 54 (c), architect §C7). The count is zero rather than
    a ratchet because the sweep took this app all the way there.
    """
    source = (Path(settings.BASE_DIR) / "apps/comms/policies.py").read_text()
    hits = [line for line in source.splitlines() if any(word in line for word in ROLE_BY_VALUE)]
    assert hits == [], hits


def test_no_comms_predicate_reads_the_row() -> None:
    """The belt under the census's row dimension. See this module's docstring.

    Every predicate this app registers takes `(actor, obj)` and must not read
    `obj`: the moment one does, the census's one-Recipient-per-node carrier
    stops standing in for a row of the key's own kind, and this test is the day
    that becomes visible rather than the day somebody notices a green matrix
    proving nothing.
    """
    from apps.comms import policies as comms_policies

    tree = ast.parse((Path(settings.BASE_DIR) / "apps/comms/policies.py").read_text())
    predicate_names = {
        function.__name__
        for function in comms_policies.POLICIES.values()
        if hasattr(function, "__name__")
    }
    assert predicate_names, "the app registers no predicate — the census has nothing to stand on"

    offenders: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name not in predicate_names:
            continue
        parameters = [argument.arg for argument in node.args.args]
        if len(parameters) < 2:
            continue
        row = parameters[1]
        for inner in ast.walk(node):
            if isinstance(inner, ast.Name) and inner.id == row and isinstance(inner.ctx, ast.Load):
                offenders.append(f"{node.name} reads {row}")
                break
    assert offenders == [], offenders


# --- P7.2.1 · the keys fit the pattern ------------------------------------------


def test_every_comms_key_conforms_and_the_renames_answer() -> None:
    """The app's names leave rule 54 (a)'s ratchet, and the old words still answer.

    A rename is not a deletion: `RENAMED_PERMISSIONS` keeps the retired word
    resolving to its successor, so a product still calling `device.register`
    is told exactly what it was told before — the whole reason a rename costs
    zero words.
    """
    from apps.comms import policies as comms_policies

    words = vocabulary()
    non_conforming = [action for action in comms_keys() if not words[action].conforms]
    assert non_conforming == [], non_conforming

    renames = renamed_permissions()
    for old, new in comms_policies.RENAMED_PERMISSIONS.items():
        assert renames[old] == new
        assert new in words
        assert old in words[new].renamed_from
