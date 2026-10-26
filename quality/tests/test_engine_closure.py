"""The engine's declared closure: what its digest keys, and every module its code reaches."""

# does-not-cover: an import whose module name is computed at run time — the walk reads literals.

from __future__ import annotations

import re
from pathlib import Path

import pytest

from quality import tree as T
from quality.engine import memo

pytestmark = pytest.mark.drives("quality/engine/memo.py")

ROOT = Path(__file__).resolve().parents[2]

_IMPORT = re.compile(r"^\s*(?:from|import)\s+(quality(?:\.\w+)+)(?:\s+import\s+([\w, ]+))?", re.M)
_QUOTED = re.compile(r"[\"'](quality(?:\.\w+)+)[\"']")


def _refs(text: str) -> list[str]:
    out = [m.group(1) for m in _QUOTED.finditer(text)]
    for m in _IMPORT.finditer(text):
        out.append(m.group(1))
        out += [f"{m.group(1)}.{n.strip()}" for n in (m.group(2) or "").split(",") if n.strip()]
    return out


def test_the_engine_imports_nothing_outside_its_declared_closure() -> None:
    names = frozenset(T.read_tree(ROOT).blobs)
    closure = set(memo.engine_closure(names))
    assert {p for p in names if p.startswith("quality/engine/")} <= closure
    outside = []
    for path in sorted(p for p in closure if p.endswith(".py")):
        if path.startswith(memo._PLANTED):
            continue
        for dotted in _refs((ROOT / path).read_text(encoding="utf-8", errors="replace")):
            found = memo.module_path(dotted, names)
            if found and found not in closure:
                outside.append(f"{path}: {dotted}")
    assert outside == [], "a module the engine's code reaches is not in the key it banks on"
    assert "quality/rules.yaml" not in closure, "a rule's own yaml keys that rule alone"
    assert not [p for p in closure if p.startswith("quality/tests/test_")]


def test_a_planted_import_joins_the_key_and_an_unreached_module_does_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = {
        "quality/engine/zzz_plant.py": "from quality.djb import scope\n",
        "quality/djb/scope.py": "X = 1\n",
        "quality/djb/other.py": "Y = 2\n",
        "quality/tests/test_x.py": "Z = 3\n",
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    monkeypatch.setattr(memo, "ROOT", tmp_path)
    monkeypatch.setattr(memo, "_CLOSURE", {})
    blobs = {rel: "1" * 40 for rel in files}
    closure = memo.engine_closure(frozenset(blobs))
    assert closure == ["quality/djb/scope.py", "quality/engine/zzz_plant.py"], closure
    digest = memo._engine_digest_of(blobs)
    assert memo._engine_digest_of({**blobs, "quality/djb/scope.py": "2" * 40}) != digest
    assert memo._engine_digest_of({**blobs, "quality/djb/other.py": "2" * 40}) == digest
    assert memo._engine_digest_of({**blobs, "quality/tests/test_x.py": "2" * 40}) == digest
