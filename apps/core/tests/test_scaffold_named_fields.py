# census: cross-app population=apps/core/scaffold/arms/*.py drives filter+search on a tree copy
"""`scaffold filter` and `scaffold search` render their copied tests from the field they name."""

# does-not-cover: one combination of shapes; a field type the renderer has no pair for falls
# does-not-cover: to `FIELD_TYPES`' own samples, and a kind added there later is not re-driven.
# does-not-cover: a search field list that names `name` after its first place (the label moves).

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import pytest

from apps.core.scaffold.arms._common import FIELD_TYPES
from apps.core.scaffold.arms.filter import GOLDEN_FILTER, filter_lines
from apps.core.tests.tree_census import source_text

ROOT = Path(__file__).resolve().parents[3]
APP, NOUN = "rotas", "Shift"
#: The shapes the combined noun takes, in the order a developer ran them (round 3, R3-DF-9).
STEPS = (
    ("newapp", APP),
    ("scaffold", "noun", APP, NOUN),
    ("scaffold", "field", APP, NOUN, "hours:decimal?"),
    ("scaffold", "enum", APP, NOUN, "status", "DRAFT,PUBLISHED,WORKED"),
    ("scaffold", "filter", APP, NOUN, "status=exact"),
    ("scaffold", "field", APP, NOUN, "role:str?"),
    ("scaffold", "search", APP, NOUN, "role"),
    ("scaffold", "stat", APP, NOUN, "count"),
    ("scaffold", "verb", APP, NOUN, "publish"),
)
SEARCHED = "apps/rotas/tests/test_search_adoption.py"
#: The five copied search tests that read the golden's `name`/`notes` while the vector held `role`.
SEARCH_TESTS = (
    "test_the_generated_column_is_never_stale_because_nothing_writes_it",
    "test_an_updated_shift_reindexes_from_the_row_and_not_from_the_payload",
    "test_the_shift_list_still_answers_from_postgres_when_the_index_is_down",
    "test_the_declared_weights_rank_the_fallback_the_way_they_rank_the_index",
    "test_the_fallback_keeps_both_walls_it_was_handed",
)
FILTER_TEST = "test_the_status_filter_narrows_alike_on_both_doors"
#: Each scaffold step's own ceiling, and the module's: eight copies, a migration each, one run.
STEP_CEILING = 600
pytestmark = [pytest.mark.product_drive, pytest.mark.timeout(1800)]


@dataclass(frozen=True)
class Product:
    """The scaffolded tree, the environment its commands ran in, and its copied tests' run."""

    root: Path
    env: dict[str, str]
    outcomes: dict[str, str]
    said: str
    wall: float
    returncode: int = -1

    def run(self, *argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 — argv list built here from constants and paths; `python`, no shell
            [sys.executable, "manage.py", *argv],
            cwd=self.root,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=STEP_CEILING,
        )


def _outcomes(junit: Path) -> dict[str, str]:
    """Each test case's name and `passed`, `failed`, `error` or `skipped`, from a JUnit file."""
    out: dict[str, str] = {}
    for case in ET.parse(junit).iter("testcase"):  # noqa: S314 — the junit file this test's own pytest run just wrote
        said = {child.tag for child in case}
        out[f"{case.get('classname')}.{case.get('name')}"] = next(
            (tag for tag in ("failure", "error", "skipped") if tag in said), "passed"
        ).replace("failure", "failed")
    return out


@pytest.fixture(scope="module")
def product(tmp_path_factory: pytest.TempPathFactory) -> Product:
    """The tracked tree copied whole as a product, the combined noun scaffolded, its tests run."""
    if shutil.which("tar") is None:
        pytest.skip("no tar on PATH — the tracked tree is copied with it")
    started = time.monotonic()
    root = tmp_path_factory.mktemp("named") / "tree"
    root.mkdir()
    copied = subprocess.run(  # noqa: S603 — `bash -c` over a pipeline this test writes; no caller input
        ["bash", "-c", f"git ls-files -z | tar --null -T - -cf - | tar -xf - -C {str(root)!r}"],  # noqa: S607 — `bash` resolved on PATH, as the gate's own legs run it
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert copied.returncode == 0, copied.stderr
    if (ROOT / ".env").is_file():
        shutil.copy(ROOT / ".env", root / ".env")
    (root / "quality/local").mkdir(parents=True, exist_ok=True)
    (root / "quality/local/rules.yaml").write_text(
        "rule_id_namespace: zzzk6n\nservice_verbs:\n  - publish\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "DJB_"))}
    env.update(
        DJANGO_SETTINGS_MODULE="config.settings.test",
        DATABASE_NAME=f"djb_named_{secrets.token_hex(3)}",
        DATABASE_URL="",
    )
    tree = Product(root, env, {}, "", 0.0)
    walls: list[str] = []
    for argv in STEPS:
        began = time.monotonic()
        done = tree.run(*argv)
        assert done.returncode == 0, (argv, done.stdout + done.stderr)
        walls.append(f"{' '.join(argv[:2])} {round(time.monotonic() - began, 1)} s")
    junit = root.parent / "copied.xml"
    ran = subprocess.run(  # noqa: S603 — argv list built here from constants and paths; `python`, no shell
        [sys.executable, "-m", "pytest", f"apps/{APP}", "-p", "no:randomly", "-q"]
        + ["-p", "no:cacheprovider", "--tb=short", f"--junitxml={junit}"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=STEP_CEILING,
    )
    outcomes = _outcomes(junit) if junit.is_file() else {}
    said = "\n".join([*walls, ran.stdout + ran.stderr])
    wall = round(time.monotonic() - started, 1)
    return Product(root, env, outcomes, said, wall, ran.returncode)


def _outcome(product: Product, test: str) -> str:
    """The one outcome of the copied test called `test`, or `absent`/`ambiguous`."""
    said = [v for k, v in product.outcomes.items() if k.rsplit(".", 1)[-1] == test]
    return said[0] if len(said) == 1 else ("absent" if not said else "ambiguous")


def _red(product: Product) -> list[str]:
    return sorted(name for name, outcome in product.outcomes.items() if outcome != "passed")


def test_filter_tests_use_the_fields_type(product: Product) -> None:
    """The enum filter's rows are two of its members, set after a create that never took them."""
    copied = (product.root / f"apps/{APP}/tests/test_mcp.py").read_text()
    assert 'STATUS_FINDS: dict[str, Any] = {"status": Shift.Status.DRAFT}' in copied
    assert 'STATUS_MISSES: dict[str, Any] = {"status": Shift.Status.PUBLISHED}' in copied
    assert "Shift.objects.filter(pk=found.pk).update(**STATUS_FINDS)" in copied
    assert "Shift.objects.filter(pk=missed.pk).update(**STATUS_MISSES)" in copied
    assert '"status": "First"' not in copied and '"status": "Second"' not in copied
    schemas = (product.root / f"apps/{APP}/schemas.py").read_text()
    assert 'default=None, json_schema_extra=example("draft")' in schemas
    assert _outcome(product, FILTER_TEST) == "passed", product.said[-3000:]


@pytest.mark.parametrize(
    ("kind", "lookup", "finds"),
    [
        ("date", "lte", 'DUE_LTE_FINDS: dict[str, Any] = {"due": date(2026, 11, 2)}'),
        ("int", "gte", 'DUE_GTE_FINDS: dict[str, Any] = {"due": 5}'),
        ("decimal", "exact", 'DUE_FINDS: dict[str, Any] = {"due": Decimal("1.50")}'),
    ],
)
def test_a_typed_filters_rows_are_its_types_own_pair(kind: str, lookup: str, finds: str) -> None:
    """A date, an int or a decimal filter's rows are that type's samples, never two words."""
    golden = next(line for line in GOLDEN_FILTER if line.startswith("NAME_FINDS"))
    said = filter_lines(golden, "due", lookup, kind)
    assert said == finds
    assert any(sample in said for sample in FIELD_TYPES[kind].python)


def test_search_tests_name_the_declared_fields(product: Product) -> None:
    """Every copied row and document key says `role`, and the five tests that read `name` pass."""
    copied = (product.root / SEARCHED).read_text()
    assert 'role="Hydraulic sprocket"' in copied and 'role="Pneumatic flange"' in copied
    assert 'document["role"] == "Bench press #4"' in copied
    assert 'upserted[-1]["role"] == "New name"' in copied
    assert 'document["name"]' not in copied and 'document["notes"]' not in copied
    assert "== [in_the_name.pk]" in copied and ".rank > " not in copied
    assert {name: _outcome(product, name) for name in SEARCH_TESTS} == dict.fromkeys(
        SEARCH_TESTS, "passed"
    ), product.said[-3000:]
    from apps.core.scaffold.arms.search import searched_rows

    row = '        tenant=tenant, actor=owner_actor, name="Flange assembly", notes="unrelated text"'
    two = searched_rows(row, ("role", "summary"))
    assert two.strip() == (
        'tenant=tenant, actor=owner_actor, name="Flange assembly", role="Flange assembly", '
        'summary="unrelated text", notes="unrelated text"'
    )


@pytest.mark.parametrize(
    "argv",
    [
        ("scaffold", "filter", APP, NOUN, "shade=exact"),
        ("scaffold", "search", APP, NOUN, "shade"),
    ],
)
def test_an_unknown_field_is_refused(product: Product, argv: tuple[str, ...]) -> None:
    """A field the noun does not declare is exit 2 naming the field shape, and nothing moves."""
    app = product.root / "apps" / APP
    before = {p: source_text(p) for p in sorted(app.rglob("*.py"))}
    done = product.run(*argv)
    assert done.returncode == 2, done.stdout + done.stderr
    assert f"{NOUN} has no shade — scaffold field first" in done.stderr
    assert {p: source_text(p) for p in sorted(app.rglob("*.py"))} == before


def test_a_combined_noun_copies_green(product: Product, capsys: pytest.CaptureFixture[str]) -> None:
    """Every copied test passes: R3-DF-9's `FILTER_TEST` and `SEARCH_TESTS`, R2-DF-7 #22–#23."""
    with capsys.disabled():
        print(f"\ncombined drive: {len(product.outcomes)} copied tests, wall {product.wall} s")
        print("\n".join(product.said.splitlines()[: len(STEPS)]))
    assert product.outcomes, product.said[-3000:]
    assert _red(product) == [], product.said[-3000:]
    assert product.returncode == 0, product.said[-3000:]
