"""Rule 91's census: what is contract, what is a tail, what is narration."""

# does-not-cover: the engine's ratchet verdict end to end — `test_engine_explain.py` runs it.

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from quality.checks.rule_91 import comment_census, comment_doctrine

pytestmark = pytest.mark.drives("quality/checks/rule_91.py", "quality/rules.yaml")

ROOT = Path(__file__).resolve().parents[2]

ROUTE = '''\
from ninja import Router

router = Router()


@router.post("/{widget_id}/touch/", url_name="widget-touch")
def touch_widget_route(request, widget_id):
    """Touch a widget

    Mark one widget as seen now.
    """
'''


def _rule_91() -> dict[str, Any]:
    doc = yaml.safe_load((ROOT / "quality/rules.yaml").read_text())
    return next(r for r in doc["rules"] if str(r["id"]) == "91")


def _narrative() -> re.Pattern[str]:
    phrases = [str(p) for p in _rule_91()["narrative"]]
    return re.compile("|".join(f"(?:{p})" for p in phrases), re.IGNORECASE)


def _census(tmp_path: Path, text: str) -> dict[str, tuple[int, int]]:
    path = tmp_path / "api.py"
    path.write_text(text)
    return comment_census(path, _narrative())


def test_a_routes_title_and_one_description_line_carry_no_tail(tmp_path: Path) -> None:
    assert _census(tmp_path, ROUTE) == {}


def test_a_routes_second_description_line_is_a_tail(tmp_path: Path) -> None:
    text = ROUTE.replace("seen now.\n", "seen now.\n    Takes no body.\n")
    assert _census(tmp_path, text)["docstring-tail"][0] == 1


def test_a_plain_functions_description_line_is_still_a_tail(tmp_path: Path) -> None:
    text = ROUTE.replace('@router.post("/{widget_id}/touch/", url_name="widget-touch")\n', "")
    assert _census(tmp_path, text)["docstring-tail"][0] == 1


@pytest.mark.parametrize(
    "line",
    [
        "House rule 46, applied to the read gate Phase R added.",
        "The declaration the owners' tests used to plant.",
        "The aggregate is covered by its read key (§0c).",
    ],
)
def test_a_narrated_archaeology_line_is_narrative(tmp_path: Path, line: str) -> None:
    census = _census(tmp_path, f'def check():\n    """{line}"""\n')
    assert census["narrative"][0] == 1


TAILED = 'def f() -> None:\n    """Return nothing.\n\n    A tail.\n    """\n'


def _recorded_tree(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    """A member recorded over old.py and gone.py, with new.py and a clean kept.py beside them."""
    for rel, text in (
        ("apps/__init__.py", ""),
        ("apps/acme/apps.py", ""),
        ("apps/acme/old.py", TAILED),
        ("apps/acme/new.py", TAILED),
        ("apps/acme/kept.py", '"""Clean."""\n'),
    ):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    (tmp_path / "population.yaml").write_text(
        "acme:\n  - apps/acme/old.py\n  - apps/acme/kept.py\n  - apps/acme/gone.py\n"
    )
    return tmp_path, {**_rule_91(), "population": "population.yaml"}


def test_a_new_file_of_a_recorded_member_is_judged_in_the_class_with_no_floor(
    tmp_path: Path,
) -> None:
    root, rule = _recorded_tree(tmp_path)
    by_path = {(str(f.path), f.klass) for f in comment_doctrine(root, rule).findings}
    assert ("apps/acme/old.py", "acme.docstring-tail") in by_path
    assert ("apps/acme/new.py", "acme.new-file") in by_path
    assert not any(path == "apps/acme/new.py" and k != "acme.new-file" for path, k in by_path)


def test_a_recorded_path_with_no_tail_or_no_file_is_a_line_to_delete(tmp_path: Path) -> None:
    root, rule = _recorded_tree(tmp_path)
    stale = [
        f.msg for f in comment_doctrine(root, rule).findings if f.klass == "acme.stale-population"
    ]
    assert len(stale) == 2
    assert any("apps/acme/kept.py" in m and "carries no counted line" in m for m in stale)
    assert any("apps/acme/gone.py" in m and "is not on this tree" in m for m in stale)


def test_a_member_the_population_does_not_list_is_judged_whole(tmp_path: Path) -> None:
    root, rule = _recorded_tree(tmp_path)
    (root / "population.yaml").write_text("other: []\n")
    klasses = {f.klass for f in comment_doctrine(root, rule).findings}
    assert klasses == {"acme.docstring-tail"}


def test_the_floor_holds_the_recorded_tail_and_refuses_the_new_one(tmp_path: Path) -> None:
    from quality.engine.run import apply_ratchets

    root, rule = _recorded_tree(tmp_path)
    (root / "population.yaml").write_text("acme:\n  - apps/acme/old.py\n")
    findings = comment_doctrine(root, rule).findings
    failing = apply_ratchets({"id": "91", "ratchets": {"acme.docstring-tail": 1}}, findings)
    header, *rest = failing
    assert [(str(f.path), f.klass) for f in rest] == [("apps/acme/new.py", "acme.new-file")]
    assert "is judged at zero: DELETE the 1 line(s)" in header.msg
    assert "RECORD IT" not in header.msg


def test_the_tree_records_a_population_for_every_member_it_floors() -> None:
    from quality.checks.rule_91 import read_population
    from quality.engine.world import RULES_BY_ID

    rule = RULES_BY_ID["91"]
    home, population = read_population(ROOT, rule)
    assert home and (ROOT / home).is_file()
    floored = {str(k).partition(".")[0] for k, n in (rule.get("ratchets") or {}).items() if n}
    assert floored and floored <= set(population)
