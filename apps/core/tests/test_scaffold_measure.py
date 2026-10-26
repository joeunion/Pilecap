"""`scaffold stat|enum|verb`: a stat measures a field, an enum forgives case, a verb steps."""

# does-not-cover: a measured field retyped after the stat is written — the copy is theirs.
# does-not-cover: `past_tense` itself — the lexicon owns it; the inference only reads it.

from __future__ import annotations

import io
import os
import secrets
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.scaffold import copier
from apps.core.scaffold.arms._common import newapp_stubs
from apps.core.tests.platform_tree import platform_tree

ROOT = Path(__file__).resolve().parents[3]
LABEL, NOUN = "gizmoes", "Gear"
HOURS = "    hours = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)\n"


@pytest.fixture(autouse=True)
def _the_platforms_frozen_families(monkeypatch: pytest.MonkeyPatch) -> None:
    """The cases scaffold onto the platform's tree: no product drawer's family is frozen."""
    from apps.core.api import frozen_families

    monkeypatch.setattr(frozen_families, "FROZEN_FAMILIES", frozen_families.CORE_FAMILIES)


def _scaffold(*argv: str, **options: Any) -> str:
    """`manage.py scaffold <argv>`'s standard output."""
    out = io.StringIO()
    call_command("scaffold", *argv, stdout=out, **options)
    return out.getvalue()


def _refused(*argv: str, **options: Any) -> str:
    """The exit-2 refusal `manage.py scaffold <argv>` answers."""
    with pytest.raises(CommandError) as refused:
        _scaffold(*argv, **options)
    assert refused.value.returncode == 2, str(refused.value)
    return str(refused.value)


def _planted(tmp_path: Path, settings: Any, *, hours: bool = True) -> Path:
    """A product tree holding `scaffold noun gizmoes Gear`'s copy, written without its migration."""
    root = platform_tree(tmp_path, "zzzm1e")
    for rel in ("quality/budgets.yaml", "apps/conftest_local.py"):
        if (root / rel).is_symlink():
            (root / rel).unlink()
            (root / rel).write_text((ROOT / rel).read_text())
    app = root / "apps" / LABEL
    copy = copier.from_golden(ROOT, copier.index(ROOT)["noun"], LABEL, NOUN).files
    for rel, text in {**newapp_stubs(LABEL), **copy}.items():
        (app / rel).parent.mkdir(parents=True, exist_ok=True)
        (app / rel).write_text(text)
    if hours:
        models = app / "models.py"
        text = models.read_text()
        meta = "    class Meta(OrgScopedModel.Meta):\n"
        assert text.count(meta) == 1, "the planted noun's Meta moved"
        models.write_text(text.replace(meta, HOURS + "\n" + meta))
    settings.BASE_DIR = root
    return root


# --- criterion 2 · an existing field may be measured; a key that is a field may not ---------------


def test_an_existing_field_may_be_measured(tmp_path: Path, settings: Any) -> None:
    root = _planted(tmp_path, settings)
    planned = _scaffold("stat", LABEL, NOUN, "total=sum:hours", "--dry-run")
    assert f"apps/{LABEL}/api.py" in planned, planned
    assert not (root / "apps" / LABEL / "api.py").read_text().count("def gear_stats(")
    assert f"apps/{LABEL}/api.py" in _scaffold("stat", LABEL, NOUN, "mean=avg:hours", "--dry-run")


@pytest.mark.parametrize(
    ("spec", "says"),
    [
        ("hours", "already has a `hours` — a measure names a new key; to measure the field"),
        ("hours=sum:hours", "already has a `hours`"),
        ("name", "already has a `name`"),
        ("total=sum:weight", "has no `weight` field"),
        ("total=sum:name", "`name` is a str field — sum and avg measure an int or decimal"),
        ("total=sum", "names no field"),
        ("total=count:hours", "a count names no field"),
        ("total=max:hours", "no measure"),
    ],
)
def test_a_key_that_is_a_field_is_still_refused(
    tmp_path: Path, settings: Any, spec: str, says: str
) -> None:
    _planted(tmp_path, settings)
    assert says in _refused("stat", LABEL, NOUN, spec, "--dry-run")


# --- criterion 3 · an enum forgives case and says so ----------------------------------------------


def test_lower_case_values_are_upper_cased_and_said(tmp_path: Path, settings: Any) -> None:
    _planted(tmp_path, settings)
    said = _scaffold("enum", LABEL, NOUN, "stage", "draft,published,worked", "--dry-run")
    assert "values: DRAFT, PUBLISHED, WORKED (upper-cased from your input)" in said.splitlines()
    upper = _scaffold("enum", LABEL, NOUN, "stage", "DRAFT,PUBLISHED,WORKED", "--dry-run")
    assert "upper-cased" not in upper
    for bad in ("draft,pub-lished,worked", "draft,published,averyveryverylongvalue"):
        assert "at most 20 characters" in _refused("enum", LABEL, NOUN, "stage", bad, "--dry-run")


# --- criterion 4 · a verb can be the enum's next step ---------------------------------------------


def _enumed(tmp_path: Path, settings: Any, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`_planted` with `enum gizmoes Gear stage DRAFT,APPROVED,CLOSED` and no migration."""
    from apps.core.scaffold.arms._common import Arms

    root = _planted(tmp_path, settings, hours=False)
    monkeypatch.setattr(Arms, "migrate", lambda self, root, label, name: None)
    _scaffold("enum", LABEL, NOUN, "stage", "DRAFT,APPROVED,CLOSED")
    return root


def test_a_transition_verb_is_the_enums_step(
    tmp_path: Path, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _enumed(tmp_path, settings, monkeypatch)
    said = _scaffold("verb", LABEL, NOUN, "approve", "--dry-run")
    assert "step: stage DRAFT→APPROVED through `transition_gear` (inferred from `approved`)" in (
        said.splitlines()
    ), said
    explicit = _scaffold("verb", LABEL, NOUN, "confirm", "--dry-run", transition="APPROVED->CLOSED")
    assert "step: stage APPROVED→CLOSED through `transition_gear`" in explicit.splitlines()
    _scaffold("verb", LABEL, NOUN, "approve")
    services = (root / "apps" / LABEL / "services.py").read_text()
    body = services[services.index("def approve_gear(") :].split("\n\n\n")[0]
    assert "transition_gear(" in body and "stage=Gear.Stage.APPROVED" in body, body
    assert "updated_at" not in body, body
    tests = (root / "apps" / LABEL / "tests/test_services.py").read_text()
    assert "pytest.raises(Conflict)" in tests[tests.index("def test_the_approve_steps") :]


def test_a_non_adjacent_step_is_refused(
    tmp_path: Path, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enumed(tmp_path, settings, monkeypatch)
    for step in ("DRAFT→CLOSED", "CLOSED→APPROVED", "DRAFT→DRAFT", "DRAFT→GONE"):
        said = _refused("verb", LABEL, NOUN, "confirm", "--dry-run", transition=step)
        assert "is not one step of `stage`" in said and "DRAFT→APPROVED" in said, said
    assert "is no `FROM→TO`" in _refused(
        "verb", LABEL, NOUN, "confirm", "--dry-run", transition="DRAFT"
    )


def test_a_transition_on_a_noun_with_no_transitioned_enum_is_refused(
    tmp_path: Path, settings: Any
) -> None:
    _planted(tmp_path, settings)
    said = _refused("verb", LABEL, NOUN, "confirm", "--dry-run", transition="DRAFT→ACTIVE")
    assert "carries no transitioned enum" in said, said
    plain = _scaffold("verb", LABEL, NOUN, "approve", "--dry-run")
    assert "step:" not in plain, plain


# --- criterion 1 · the copies, built and passing, on a throwaway tree -----------------------------


@dataclass
class World:
    """The tracked tree copied whole and namespaced; the commands it runs and their output."""

    root: Path
    env: dict[str, str]

    def run(self, *argv: str) -> str:
        done = subprocess.run(  # noqa: S603 — argv list built here from constants and paths; `python`, no shell
            [sys.executable, *argv], cwd=self.root, env=self.env, capture_output=True, text=True
        )
        assert done.returncode == 0, (argv, (done.stdout + done.stderr)[-6000:])
        return done.stdout

    def passed(self, *argv: str) -> set[str]:
        """The copied tests under `argv` that passed, by name; any failure fails the call."""
        said = self.run("-m", "pytest", *argv, "-v", "-p", "no:randomly", "-p", "no:cacheprovider")
        return {
            line.split("::")[-1].split(" ")[0] for line in said.splitlines() if " PASSED" in line
        }


def _world(tmp_path: Path) -> World:
    """The tracked tree in `tmp_path`, namespaced, `.env` beside it, its own database name."""
    if shutil.which("tar") is None:
        pytest.skip("no tar on PATH — the tracked tree is copied with it")
    root = tmp_path / "tree"
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
    (root / "quality/local/rules.yaml").write_text("rule_id_namespace: zzzm1w\n")
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.test",
        "DATABASE_NAME": f"djb_measure_{secrets.token_hex(3)}",
        "DATABASE_URL": "",
    }
    return World(root, env)


STATS = (
    "test_stats_query_count_does_not_grow_with_rows",
    "test_the_stats_basis_moves_with_the_rows_it_measures",
    "test_the_two_doors_agree_on_a_measured_number_and_its_basis",
)


@pytest.mark.full_gate
def test_sum_and_avg_render_from_the_named_field(tmp_path: Path) -> None:
    world = _world(tmp_path)
    for label, noun, field, measure in (
        ("rotas", "Shift", "hours:decimal?", "total=sum:hours"),
        ("households", "Chore", "minutes:int?", "mean=avg:minutes"),
    ):
        world.run("manage.py", "newapp", label)
        world.run("manage.py", "scaffold", "noun", label, noun)
        world.run("manage.py", "scaffold", "field", label, noun, field)
        world.run("manage.py", "scaffold", "stat", label, noun, measure)
    shifts = (world.root / "apps/rotas/api.py").read_text()
    assert 'Sum("hours")' in shifts and 'formula="sum(hours)"' in shifts, shifts
    chores = (world.root / "apps/households/api.py").read_text()
    assert 'Sum("minutes")' in chores and 'formula="sum(minutes) / rows"' in chores, chores
    for label in ("rotas", "households"):
        passed = world.passed(f"apps/{label}/tests", "-k", "stats or measured")
        assert set(STATS) <= passed, (label, sorted(passed))


@pytest.mark.full_gate
def test_the_transition_verbs_copied_tests_pass(tmp_path: Path) -> None:
    world = _world(tmp_path)
    world.run("manage.py", "newapp", "rotas")
    world.run("manage.py", "scaffold", "noun", "rotas", "Shift")
    said = world.run(
        "manage.py", "scaffold", "enum", "rotas", "Shift", "stage", "draft,approved,closed"
    )
    assert "values: DRAFT, APPROVED, CLOSED (upper-cased from your input)" in said, said
    world.run("manage.py", "scaffold", "verb", "rotas", "Shift", "approve")
    world.run(
        "manage.py", "scaffold", "verb", "rotas", "Shift", "confirm", "--transition=APPROVED→CLOSED"
    )
    passed = world.passed("apps/rotas/tests", "-k", "approve or confirm")
    for verb, start, end in (("approve", "draft", "approved"), ("confirm", "approved", "closed")):
        for case in (
            f"test_the_{verb}_steps_stage_from_{start}_to_{end}_once",
            f"test_a_{verb}_answers_the_shift_at_{end}",
            f"test_the_{verb}_tool_answers_the_shift_at_{end}",
            f"test_a_{verb}_is_one_body_on_rest_mcp_and_the_outbox",
        ):
            assert case in passed, (case, sorted(passed))
