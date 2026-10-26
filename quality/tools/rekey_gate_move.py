"""Re-key the cites the split of `quality/gate.py` makes false, run from the moved tree's root."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path.cwd()
DOOR = "quality/gate.py"
PKG = ROOT / "quality" / "engine"


def defined(path: Path) -> set[str]:
    """The top-level names a module binds."""
    names: set[str] = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names |= {t.id for t in targets if isinstance(t, ast.Name)}
    return names


class Rekey:
    """One re-keying pass over the moved tree, against the door's old text."""

    def __init__(self, old: list[str]) -> None:
        self.old = old
        self.modules = sorted(PKG.glob("*.py"))
        self.home: dict[str, str] = {}
        for m in self.modules:
            for name in defined(m):
                self.home.setdefault(name, m.relative_to(ROOT).as_posix())
        self.changed: list[str] = []
        self.refused: list[str] = []

    def _write(self, rel: str, text: str, new: str) -> None:
        if new != text:
            (ROOT / rel).write_text(new, encoding="utf-8")
            self.changed.append(rel)

    def symbol_cites(self, rel: str) -> None:
        """`quality/gate.py::<sym>` becomes the engine module that defines <sym>."""
        text = (ROOT / rel).read_text(encoding="utf-8")

        def swap(m: re.Match[str]) -> str:
            sym = m.group(1)
            if sym not in self.home:
                self.refused.append(f"{rel}: {DOOR}::{sym} is defined in no engine module")
                return m.group(0)
            return f"{self.home[sym]}::{sym}"

        self._write(rel, text, re.sub(rf"{re.escape(DOOR)}::(\w+)", swap, text))

    def line_cites(self, rel: str) -> None:
        """`quality/gate.py:<n>[-<m>]` becomes the file and line now holding that old text."""
        text = (ROOT / rel).read_text(encoding="utf-8")
        files = [ROOT / DOOR, *self.modules]
        lines = {f: f.read_text(encoding="utf-8").splitlines() for f in files}

        def swap(m: re.Match[str]) -> str:
            start, end = int(m.group(1)), int(m.group(2) or m.group(1))
            want = self.old[start - 1]
            hits = [(f, i) for f in files for i, ln in enumerate(lines[f], 1) if ln == want]
            if len(hits) > 1 and hits[0][0] == ROOT / DOOR:
                hits = hits[:1]
            if len(hits) != 1:
                self.refused.append(
                    f"{rel}: {m.group(0)} ({want.strip()!r}) is at {len(hits)} places"
                )
                return m.group(0)
            f, i = hits[0]
            span = f"-{i + end - start}" if end != start else ""
            return f"{f.relative_to(ROOT).as_posix()}:{i}{span}"

        self._write(rel, text, re.sub(rf"{re.escape(DOOR)}:(\d+)(?:-(\d+))?", swap, text))

    def drives_line(self, rel: str) -> None:
        """A `# drives:` line naming the door names every engine module too."""
        text = (ROOT / rel).read_text(encoding="utf-8")
        if "quality/engine/" in text:
            return
        engine = " ".join(m.relative_to(ROOT).as_posix() for m in self.modules)
        new = re.sub(
            rf"^(# drives:.*?\s){re.escape(DOOR)}(\s|$)",
            lambda m: f"{m.group(1)}{DOOR} {engine}{m.group(2)}",
            text,
            count=1,
            flags=re.M,
        )
        if new == text:
            self.refused.append(f"{rel}: no `# drives:` line naming {DOOR}")
            return
        self._write(rel, text, new)


def main(argv: list[str]) -> int:
    """Re-key every reader the move names; 0 when each cite found one home, 2 otherwise."""
    if len(argv) != 1:
        print(f"usage: python {DOOR.replace('gate', 'tools/rekey_gate_move')} <old gate.py>")
        return 2
    if not list(PKG.glob("*.py")):
        print("!! quality/engine/ holds no module: run the split first", file=sys.stderr)
        return 2
    run = Rekey(Path(argv[0]).read_text(encoding="utf-8").splitlines())
    for m in run.modules:
        run.symbol_cites(m.relative_to(ROOT).as_posix())
    run.symbol_cites("docs/product/build-contract.md")
    run.line_cites("docs/product/instruments.md")
    for rel in run.changed:
        print(f"re-keyed: {rel}")
    for why in run.refused:
        print(f"!! {why}", file=sys.stderr)
    return 2 if run.refused else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
