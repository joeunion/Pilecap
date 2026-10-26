"""The engine's one app predicate: a directory under `apps/` without `apps.py` is apps_root's."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

#: Reached through `importlib` for the reason `test_drawer_seam.py` states (mypy --strict).
_GATE = importlib.import_module("quality.gate")
_CHECKS = importlib.import_module("quality.checks")

TAILED = '''"""A module contract line.

A second line past the contract.
"""


def _app_label(nodeid: str) -> str:
    """A function contract line.

    A tail line.
    """
    return nodeid
'''


def _tree(root: Path, nonapp: str = "zz_nonapp") -> Path:
    """Two real apps and one directory that holds no `apps.py`, each defining `_app_label`."""
    for rel, text in (
        ("apps/__init__.py", ""),
        ("apps/core/apps.py", ""),
        ("apps/core/service.py", TAILED),
        ("apps/acme/apps.py", ""),
        ("apps/acme/selectors.py", TAILED),
        (f"apps/{nonapp}/x.py", TAILED),
    ):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def _members(result: Any, rel: str) -> set[str]:
    return {str(f.klass).split(".", 1)[0] for f in result.findings if str(f.path) == rel}


def test_rule_91_counts_a_non_app_directory_under_the_apps_root(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    result = _CHECKS.comment_doctrine(root, _GATE.RULES_BY_ID["91"])
    assert _members(result, "apps/zz_nonapp/x.py") == {"apps_root"}
    assert _members(result, "apps/acme/selectors.py") == {"acme"}


def test_rule_84_reads_no_private_twin_in_a_non_app_directory(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    result = _CHECKS.road_uniqueness(root, {"id": "84", "ratchets": {}})
    twins = [f for f in result.findings if f.klass == "private_twin"]
    assert [str(f.path) for f in twins] == ["apps/core/service.py"], twins
    assert "(acme, core)" in str(twins[0].msg) and "zz_nonapp" not in str(twins[0].msg)


def test_unmeasured_app_offers_no_recording_for_a_non_app_directory(tmp_path: Path) -> None:
    root = _tree(tmp_path, nonapp="zz_harness")
    hit = _GATE.Finding("apps/zz_harness/x.py", 1, "a forged finding", "zz_harness.module-tail")
    assert _GATE.unmeasured_app("zz_harness.module-tail", [hit], root=root) is None


def test_a_real_app_is_still_attributed_to_itself(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    assert "acme" not in (_GATE.PLATFORM_APPS or ())
    hit = _GATE.Finding("apps/acme/selectors.py", 1, "a forged finding", "acme.module-tail")
    assert _GATE.unmeasured_app("acme.module-tail", [hit], root=root) == "acme"
    result = _CHECKS.road_uniqueness(root, {"id": "84", "ratchets": {}})
    assert any(f.klass == "private_twin" and "acme" in str(f.msg) for f in result.findings)
