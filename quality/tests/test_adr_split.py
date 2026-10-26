"""`scripts/adr_split.py` moves each block verbatim, is idempotent, and refuses an unparsable id."""

# does-not-cover: the pointer files for cited-without-block ids — they need the publication census.

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
# Assembled, never spelled: this shipped file's own ids would be read by the ADR census.
_A = "ADR" + " "

ARCH = """# architecture

## The doors

Every door calls services.

**@zzz-1 · a decision.** *Context*: one.

*Amended* — the amendment rides the block.

**@zzz-2 · another.** rejected: x · trigger to revisit: y
Concurrency: read-modify-write stays.

| Area | Ruling |
|---|---|
| Pool | **@zzz-3 · context:** a cell tail · **decision:** it moves |
| Mail | the ruling stays. **The wall (@zzz-4):** a mid-cell tail |

### The @home

- **@zzz-5 (a list entry)** · context: indented
  continuation · trigger to revisit: never
- **@zzz-5 (the same id again)** · both stand

After the list, current state.
""".replace("@", _A)


def _splitter() -> ModuleType:
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        return importlib.import_module("adr_split")
    finally:
        sys.path.remove(str(ROOT / "scripts"))


adr_split = _splitter()


def test_every_block_moves_verbatim_and_the_rest_stays() -> None:
    kept, blocks, _ = adr_split.split(ARCH, "arch.md")
    by_id: dict[str, list[str]] = {}
    for b in blocks:
        by_id.setdefault(b.id, []).append(b.text)
    assert sorted(by_id) == ["zzz-1", "zzz-2", "zzz-3", "zzz-4", "zzz-5"]
    for texts in by_id.values():
        for text in texts:
            assert text in ARCH, text
    assert "*Amended* — the amendment rides the block." in by_id["zzz-1"][0]
    assert len(by_id["zzz-5"]) == 2
    assert "Concurrency: read-modify-write stays." in kept
    assert "After the list, current state." in kept
    assert f"| Pool | {_A}zzz-3 |" in kept
    assert f"| Mail | the ruling stays. ({_A}zzz-4) |" in kept
    assert f"{_A}zzz-1 ·" not in kept and f"- **{_A}zzz-5" not in kept
    assert len(kept) + sum(len(t) for t in sum(by_id.values(), [])) <= len(ARCH) + 40


def test_an_unparsable_id_is_refused(tmp_path: Path) -> None:
    (tmp_path / "docs/product").mkdir(parents=True)
    (tmp_path / "docs/product/architecture.md").write_text("**ADR Not-An-Id · x**\n")
    (tmp_path / "docs/product/adrs-ingredients.md").write_text("# ingredients\n")
    assert adr_split.main(["--root", str(tmp_path)]) == 2


def test_a_second_run_moves_nothing() -> None:
    kept, blocks, _ = adr_split.split(ARCH, "arch.md")
    again, more, _ = adr_split.split(kept, "arch.md")
    assert blocks and not more and again == kept
