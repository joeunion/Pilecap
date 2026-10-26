"""The queue's index/detail split: the round trip, the consistency check and the two ratchets."""

# does-not-cover: whether `--check` is called at all — the gate's registration, not this module's.
# does-not-cover: the real migration's content — the real pair is round-tripped, never read.
# does-not-cover: a one-digit fixture id — the fixture ids are four digits, invisible to citations.

from __future__ import annotations

import builtins
import importlib.util
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from quality.tests.fixtures.capture import Captured

pytestmark = pytest.mark.drives(
    "scripts/queue_index.py",
    "docs/product/queue.md",
    "docs/product/queue-detail.md",
    "docs/product/skeletons/queue*",
)

ROOT = Path(__file__).resolve().parents[2]
GEN = ROOT / "scripts" / "queue_index.py"
#: Template-only and never a `.md` literal: the artifact's pointer scan would read one as dangling.
SKELETONS = ROOT / "docs/product/skeletons"
#: The fixture ids' letter, held apart: an id spelled whole in this text is a plan coordinate.
N = "N"
#: Four-digit fixture ids: the citation census reads one to three digits.
FIXTURE = f"""# Queue — the fixture

> Order lives here. Every other document defers to this one on ordering.

## ROW STATUS — how to read this file

> A struck id is closed and carries WHY in the strike itself.

## Live

| # | What | Holder | Evidence | Band |
|---|---|---|---|---|
| 1 | a table row whose first cell is not an id, so it is not a row | PM | — | floor |

## The first section

- **{N}9001 (MED shape, fixture): the first open row** — it states what is false. Holder: the drive
- **~~{N}9002~~ CLOSED (merged 0000000, fixture): the struck row** — closed with its artifact.
| {N}9003 | **a table row that IS a row** | PM | fixture | band |

## The second section

- **{N}9004 (LOW, fixture): a second open row, held by nobody.** Holder: nobody
- **{N}9001 ADDENDUM (the same id, a second row line — the declared population): the addendum**

## The end
"""


def long_row(ident: str) -> str:
    return f"- **{ident} (MED, fixture): a report-shaped row** {'x' * 1600}\n"


@dataclass
class World:
    """The fixture queue in a scratch directory, and the generator run inside it."""

    dir: Path
    capture: Callable[..., Captured]

    @property
    def queue(self) -> Path:
        return self.dir / "queue.md"

    @property
    def detail(self) -> Path:
        return self.dir / "queue-detail.md"

    def run(self, *argv: str) -> tuple[int, str]:
        ran = self.capture([sys.executable, str(GEN), *argv], cwd=self.dir)
        return ran.rc, ran.text() if ran.path.stat().st_size else ""

    def check(self) -> tuple[int, str]:
        return self.run("--check", "queue.md", "queue-detail.md")

    def split(self) -> None:
        rc, out = self.run("--split", "queue.md", "queue-detail.md")
        assert rc == 0, f"the fixture would not split — every case is built on it: {out}"

    def sub(self, path: Path, pattern: str, repl: str) -> None:
        """One regex substitution per matching line; the anchor must be found."""
        text = path.read_text()
        new, n = re.subn(pattern, repl, text, flags=re.MULTILINE)
        assert n, f"the edit's anchor is not in {path.name}: {pattern!r}"
        path.write_text(new)

    def drop(self, path: Path, keep: Callable[[str], bool]) -> None:
        lines = path.read_text().splitlines(keepends=True)
        kept = [line for line in lines if keep(line)]
        assert kept != lines, f"the drop matched nothing in {path.name}"
        path.write_text("".join(kept))

    def append(self, path: Path, text: str) -> None:
        with path.open("a") as sink:
            sink.write(text)


@pytest.fixture
def world(scratch: Path, capture: Callable[..., Captured]) -> World:
    home = scratch / "world"
    home.mkdir()
    (home / "queue.md").write_text(FIXTURE)
    return World(home, capture)


def recorded(path: Path, key: str) -> str:
    return next(line for line in path.read_text().splitlines() if line.startswith(f"{key}: "))


# --- the round trip ------------------------------------------------------------------


def test_the_split_reproduces_the_original_bytes(world: World) -> None:
    world.split()
    rc, _ = world.run("--unsplit", "queue-detail.md", "rebuilt.md")
    assert rc == 0
    assert (world.dir / "rebuilt.md").read_text() == FIXTURE


def test_rows_appended_after_the_snapshot_still_reproduce(world: World) -> None:
    world.append(
        world.queue,
        f"- **{N}9005 (LOW, appended after the snapshot): a row the builder never saw** Holder:"
        " the PM\n"
        f"- **~~{N}9006~~ CLOSED (merged 1111111, appended after the snapshot): another**\n"
        f"| {N}9007 | **a third, as a table row** | PM | appended | band |\n",
    )
    original = world.queue.read_bytes()
    world.split()
    assert world.run("--unsplit", "queue-detail.md", "rebuilt.md")[0] == 0
    assert (world.dir / "rebuilt.md").read_bytes() == original
    assert world.check()[0] == 0


def test_a_fresh_split_checks_clean(world: World) -> None:
    world.split()
    rc, out = world.check()
    assert rc == 0
    assert "rows" in out
    assert "!!" not in out


def test_an_id_that_carries_two_rows_gets_two_anchors(world: World) -> None:
    world.split()
    anchors = world.detail.read_text().splitlines()
    assert f"### {N}9001" in anchors and f"### {N}9001 (2)" in anchors
    assert "queue-detail.md#n9001-2" in world.queue.read_text()


# --- the consistency check -------------------------------------------------------------


def test_an_index_row_with_no_anchor_is_exit_1_naming_the_id(world: World) -> None:
    world.split()
    world.drop(world.detail, lambda line: line != f"### {N}9004\n")
    rc, out = world.check()
    assert rc == 1
    assert f"{N}9004" in out and "NO anchor" in out


def test_an_anchor_with_no_index_row_is_exit_1_naming_the_id(world: World) -> None:
    world.split()
    world.drop(world.queue, lambda line: "queue-detail.md#n9004" not in line)
    rc, out = world.check()
    assert rc == 1
    assert f"{N}9004" in out and "NO index row" in out


def test_a_head_that_is_not_a_prefix_is_exit_1_naming_the_id(world: World) -> None:
    world.split()
    world.sub(
        world.queue,
        rf"^(- \*\*{N}9004 .*\*\* · ).*( → queue-detail\.md#n9004)$",
        r"\1a paraphrase nobody wrote\2",
    )
    rc, out = world.check()
    assert rc == 1
    assert f"{N}9004" in out and "not the row's own text" in out


def test_a_struck_row_indexed_open_is_exit_1_naming_the_id(world: World) -> None:
    world.split()
    world.sub(world.queue, rf"^- \*\*~~{N}9002~~ · struck", f"- **{N}9002 · open")
    rc, out = world.check()
    assert rc == 1
    assert f"{N}9002" in out


def test_a_duplicate_anchor_is_exit_1(world: World) -> None:
    world.split()
    world.sub(world.detail, rf"^### {N}9003$", f"### {N}9003\n### {N}9003")
    rc, out = world.check()
    assert rc == 1
    assert "DUPLICATE ANCHOR" in out


def test_an_absent_record_is_exit_2_and_judges_nothing(world: World) -> None:
    world.split()
    world.detail.unlink()
    rc, out = world.check()
    assert rc == 2
    assert "is absent while" in out and "Nothing was judged" in out
    assert "rows ·" not in out


def test_a_pre_split_tree_is_a_named_absence_not_a_pass(world: World) -> None:
    rc, out = world.check()
    assert rc == 0
    for said in (
        "PRE-SPLIT",
        "nothing was checked",
        ".venv/bin/python scripts/queue_index.py --split",
    ):
        assert said in out
    assert "long rows of" not in out


def test_a_record_beside_an_ungenerated_index_is_exit_2(world: World) -> None:
    world.split()
    assert world.run("--unsplit", "queue-detail.md", "queue.md")[0] == 0
    rc, out = world.check()
    assert rc == 2
    assert "half-migrated" in out and "Nothing was judged" in out


def test_an_unreadable_record_is_exit_2(world: World) -> None:
    world.split()
    world.detail.chmod(0)
    try:
        rc, out = world.check()
    finally:
        world.detail.chmod(0o644)
    assert rc == 2
    assert "Nothing was judged" in out


def test_a_hand_edit_to_the_index_is_exit_1_with_the_remedy(world: World) -> None:
    world.split()
    world.sub(world.queue, r"^## The second section", "## The second section, renamed by hand")
    rc, out = world.check()
    assert rc == 1
    for said in ("is NOT what scripts/queue_index.py generates", "Remedy", "--index"):
        assert said in out


# --- the two ratchets ------------------------------------------------------------------


def test_an_index_over_its_ceiling_is_exit_1_with_both_remedies(world: World) -> None:
    world.split()
    world.sub(world.queue, r"^CEILING: .*", "CEILING: 64")
    rc, out = world.check()
    assert rc == 1
    for said in ("over its recorded ceiling", "Remedy 1", "Remedy 2"):
        assert said in out


def test_the_ceiling_ratchets_down_by_machine(world: World) -> None:
    world.split()
    world.sub(
        world.queue,
        r"^CEILING: .*",
        "CEILING: 10000000 raised by hand, reason: the fixture says so",
    )
    assert world.run("--index", "queue.md", "queue-detail.md")[0] == 0
    line = recorded(world.queue, "CEILING")
    assert int(line.split()[1]) < 10000, f"the ceiling did not ratchet down: {line}"


def test_the_ceiling_is_never_raised_by_machine(world: World) -> None:
    world.split()
    before = recorded(world.queue, "CEILING")
    for i in range(1, 10):
        ident = f"{N}91{i}0"
        world.append(world.detail, f"### {ident}\n{long_row(ident)}")
    assert world.run("--index", "queue.md", "queue-detail.md")[0] == 0
    assert recorded(world.queue, "CEILING") == before
    rc, out = world.check()
    assert rc == 1
    assert "over its recorded ceiling" in out


def test_the_long_row_census_refuses_a_count_above_its_floor(world: World) -> None:
    world.append(world.queue, long_row(f"{N}9101"))
    world.split()
    assert recorded(world.queue, "LONGROWS").startswith("LONGROWS: 1")
    world.append(world.detail, f"### {N}9102\n{long_row(N + '9102')}")
    assert world.run("--index", "queue.md", "queue-detail.md")[0] == 0
    rc, out = world.check()
    assert rc == 1
    for said in ("rows over 1500 characters", "the recorded floor is 1", f"{N}9102"):
        assert said in out


def test_the_long_row_census_ratchets_down_by_machine(world: World) -> None:
    world.append(world.queue, long_row(f"{N}9101"))
    world.split()
    world.drop(
        world.detail,
        lambda line: line != f"### {N}9101\n" and not line.startswith(f"- **{N}9101 "),
    )
    assert world.run("--index", "queue.md", "queue-detail.md")[0] == 0
    assert recorded(world.queue, "LONGROWS").startswith("LONGROWS: 0")


def test_a_line_the_citation_census_would_misread_is_exit_1(world: World) -> None:
    world.split()
    world.sub(world.queue, rf"^- \*\*{N}9004 · ([^*]*)\*\* · ", rf"- **{N}9004** · \1 · ")
    assert re.search(rf"^- \*\*{N}9004\*\* · open · ", world.queue.read_text(), re.MULTILINE), (
        "the plant did not take — the index line shape changed and this canary aims at nothing"
    )
    rc, out = world.check()
    assert rc == 1
    assert "queue-citation parser reads" in out and "rows out of the generated" in out


# --- the refusals ------------------------------------------------------------------------


def test_a_source_that_already_carries_an_anchor_is_refused(world: World) -> None:
    world.append(world.queue, f"\n### {N}9010\n")
    rc, out = world.run("--split", "queue.md", "queue-detail.md")
    assert rc == 2
    assert "already carries an anchor-shaped line" in out
    assert not world.detail.exists(), "it wrote the record anyway"


def test_split_refuses_when_the_record_already_exists(world: World) -> None:
    world.split()
    kept = world.detail.read_bytes()
    rc, out = world.run("--split", "queue.md", "queue-detail.md")
    assert rc == 2
    assert "already exists" in out
    assert world.detail.read_bytes() == kept


def test_index_refuses_a_queue_that_was_never_split(world: World) -> None:
    rc, out = world.run("--index", "queue.md", "queue-detail.md")
    assert rc == 2
    assert "Nothing was written" in out


def test_an_unknown_flag_is_exit_2(world: World) -> None:
    rc, out = world.run("--pretend-this-is-a-flag")
    assert rc == 2
    assert "unknown argument" in out and "Nothing was judged" in out


def _check_opens(monkeypatch: pytest.MonkeyPatch, home: Path) -> list[tuple[str, str]]:
    """Every file `--check` opens in-process on `home`'s pair, by path and mode; no child."""
    spec = importlib.util.spec_from_file_location("queue_index_under_test", GEN)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    opened: list[tuple[str, str]] = []
    real_open = builtins.open

    def recorded_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        opened.append((str(file), mode))
        return real_open(file, mode, *args, **kwargs)

    def no_child(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"--check started a process: {args[:1]}")

    with monkeypatch.context() as patched:
        patched.chdir(home)
        patched.setattr(builtins, "open", recorded_open)
        patched.setattr(subprocess, "Popen", no_child)
        rc = module.main(["--check", "docs/product/queue.md", "docs/product/queue-detail.md"])
    assert rc == 0, opened
    return opened


def test_the_check_reads_the_real_pair_once_and_starts_nothing(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = ROOT / "docs/product/queue.md"
    assert "\nCEILING: " in real.read_text(), "this checkout's queue is not a generated index"
    product = world.dir / "docs/product"
    product.mkdir(parents=True)
    shutil.copy(real, product / "queue.md")
    shutil.copy(ROOT / "docs/product/queue-detail.md", product / "queue-detail.md")
    rc, out = world.run("--check", "docs/product/queue.md", "docs/product/queue-detail.md")
    assert rc == 0, out
    assert "rows" in out
    pair = [("docs/product/queue.md", "r"), ("docs/product/queue-detail.md", "r")]
    assert _check_opens(monkeypatch, world.dir) == pair, "--check runs on every commit"
    assert world.run("--unsplit", "docs/product/queue-detail.md", "pre.md")[0] == 0
    world.run("--split", "pre.md", "rebuilt-detail.md")
    assert (world.dir / "rebuilt-detail.md").read_bytes() == (
        product / "queue-detail.md"
    ).read_bytes()


# --- the shipped skeleton ---------------------------------------------------------------


def _product_from_skeletons(world: World) -> Path:
    """The two committed skeletons at the paths a fresh product meets them."""
    product = world.dir / "docs/product"
    product.mkdir(parents=True)
    shutil.copy(SKELETONS / "queue.md", product / "queue.md")
    shutil.copy(SKELETONS / "queue-detail.md", product / "queue-detail.md")
    return product


@pytest.mark.template_only(reason="the skeleton sources exist only in the template")
def test_the_shipped_skeleton_index_is_its_generators_output(world: World) -> None:
    product = _product_from_skeletons(world)
    rc, out = world.run("--index", "docs/product/queue.md", "docs/product/queue-detail.md")
    assert rc == 0, out
    assert (product / "queue.md").read_bytes() == (SKELETONS / "queue.md").read_bytes(), (
        "the shipped queue skeleton is not the generator's output over its detail"
    )


@pytest.mark.template_only(reason="the skeleton sources exist only in the template")
def test_a_fresh_products_first_check_passes(world: World) -> None:
    _product_from_skeletons(world)
    rc, out = world.run("--check", "docs/product/queue.md", "docs/product/queue-detail.md")
    assert rc == 0, out
    assert "!!" not in out


# --- the two writes: strike and book ------------------------------------------------------

FILES = ("--files", "queue.md", "queue-detail.md")
SHA = "0123456789abcdef0123456789abcdef01234567"  # pragma: allowlist secret — a fixture commit sha


def report(world: World, body: str) -> Path:
    path = world.dir / "report.md"
    path.write_text(
        f"# A report\n\nIts prose.\n\n{body}\n## After the block\n\n- **(LOW): beyond it**\n"
    )
    return path


def test_strike_rewrites_the_head_and_the_index_round_trips(world: World) -> None:
    world.split()
    rc, out = world.run("--strike", f"{N}9004", "--sha", SHA, "--artifact", "reports/x.md", *FILES)
    assert rc == 0, out
    head = f"- **~~{N}9004~~ SHIPPED (01234567, reports/x.md) (LOW, fixture)"
    assert head in world.detail.read_text()
    assert f"- **~~{N}9004~~ · struck" in world.queue.read_text()
    assert f"struck {N}9004 at 01234567" in out
    assert world.check()[0] == 0


def test_strike_twice_is_a_no_op(world: World) -> None:
    world.split()
    argv = ("--strike", f"{N}9004", "--sha", SHA, "--artifact", "reports/x.md", *FILES)
    assert world.run(*argv)[0] == 0
    detail, index = world.detail.read_bytes(), world.queue.read_bytes()
    rc, out = world.run(*argv)
    assert rc == 0 and f"already struck {N}9004" in out
    assert (world.detail.read_bytes(), world.queue.read_bytes()) == (detail, index)


def test_strike_of_an_id_with_no_anchor_is_exit_1_and_nothing_written(world: World) -> None:
    world.split()
    detail = world.detail.read_bytes()
    rc, out = world.run("--strike", f"{N}9004", f"{N}9099", "--sha", SHA, "--artifact", "r", *FILES)
    assert rc == 1 and f"{N}9099 has no anchor" in out
    assert world.detail.read_bytes() == detail


def test_book_assigns_the_next_anchor_and_round_trips(world: World) -> None:
    world.split()
    path = report(
        world,
        f"## Rows\nships: {N}9004   # closed\nbooks:\n"
        "- **(MED gate / the first, the drive 2026-10-24):** evidence `a.py:1`.\n"
        "- **(LOW hygiene / the second):** wraps\n  onto a second line.\n",
    )
    rc, out = world.run("--book", str(path), *FILES)
    assert rc == 0, out
    assert f"booked {N}9005–{N}9006 ← {path}" in out
    text = world.detail.read_text()
    inbox = text.index("## Inbox — booked by machine, the PM orders")
    first = f"### {N}9005\n- **{N}9005 (MED gate / the first, the drive 2026-10-24):** evidence"
    assert text.index(first) > inbox
    assert f"- **{N}9006 (LOW hygiene / the second):** wraps onto a second line." in text
    assert f"Booked from `{path}`." in text
    assert "beyond it" not in text
    assert f"- **{N}9006 · open · LOW" in world.queue.read_text()
    assert world.check()[0] == 0
    again = world.detail.read_bytes()
    rc, out = world.run("--book", str(path), *FILES)
    assert rc == 0 and "booked none" in out and world.detail.read_bytes() == again


def test_book_refuses_a_long_row(world: World) -> None:
    world.split()
    detail = world.detail.read_bytes()
    path = report(world, f"## Rows\nships: none\nbooks:\n- **(MED, long):** {'x' * 1500}\n")
    rc, out = world.run("--book", str(path), *FILES)
    assert rc == 1 and "over 1500" in out
    assert world.detail.read_bytes() == detail


def test_book_from_a_report_with_no_rows_block_is_exit_2(world: World) -> None:
    world.split()
    rc, out = world.run("--book", str(report(world, "")), *FILES)
    assert rc == 2 and "the report contract names the block" in out
