"""The reader that leaves a pipe early: the class under pipefail, and its one shell census."""

# narrowed: case_the_pass_two_summary_is_capped_and_complete — pytest_x2.summary_of, no pipe
# deleted: case_the_scope_banner_reads_the_first_counts_file_under_a_padded_list — dies with the shim  # noqa: E501
# pin: test_scope.py::test_the_pre_run_counts_agree_with_the_reconciliation (a sorted read)
# does-not-cover: an early return the five shapes do not spell — the valve records the next shape.
# does-not-cover: a shape built at run time; a string spelling the shape is a site.
# does-not-cover: a joined site with two readers, one braced — it reads as braced.
# does-not-cover: a site rewritten while another opens — the count holds, the named list shows.
# does-not-cover: a kernel whose pipe buffer exceeds the 200,000-byte padding — the controls red.

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from quality.djb.legs import pytest_x2
from quality.tests.fixtures.capture import Captured

pytestmark = pytest.mark.drives("scripts/**/*.sh", "deploy/**/*.sh", "scripts/githooks/*")

ROOT = Path(__file__).resolve().parents[2]
#: The recorded count of open sites; only ever lowered, to the number the census prints.
PIPEFAIL_OPEN_RECORDED = 5
#: Sized for the residue once the drives go (76 tracked shell files when it was set).
POPULATION_FLOOR = 60
_READER = r"(head|grep\s+-m|awk[^|]*exit|tee(\s|$))"
_QUIET = r"grep\s+(-[A-Za-z]*q[A-Za-z]*|--quiet)"
SITE_RE = re.compile(rf"[|]\s*{_READER}|(^|[^|])[|]\s*{_QUIET}")
BRACED_RE = re.compile(rf"[|][|] true; [}}]\s*[|]\s*({_READER}|{_QUIET})")
_END_BLOCK = re.compile(r"END\s*[{][^}]*[}]")
_SHEBANG = re.compile(r"^#!.*sh(\s|$)")
PAD = (
    "padded() { printf 'MATCH\\n'; head -c 200000 /dev/zero | tr '\\0' x; }\n"
    "lines() { printf 'HEAD-OF-LIST\\n'; awk 'BEGIN { for (i = 1; i <= 20000; i++) "
    'print "filler" i }\'; }\n'
)


@dataclass(frozen=True)
class Census:
    """One census over a tree: its files, every site, those disposed of, and the open ones."""

    files: int
    sites: int
    disposed: int
    open: tuple[str, ...]

    @property
    def verdict(self) -> list[str]:
        return sorted("site " + ":".join(s.split(":", 2)[:2]) for s in self.open)


def pipe_files(root: Path) -> list[str]:
    """Every tracked `.sh`, `githooks/` hook, or file whose first line is a shell shebang."""
    listed = subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True, text=True)
    assert listed.returncode == 0, f"git ls-files did not answer in {root}: {listed.stderr}"
    found = []
    for rel in listed.stdout.splitlines():
        path = root / rel
        if not path.is_file():
            continue
        if rel.endswith(".sh") or "/githooks/" in rel:
            found.append(rel)
            continue
        with path.open(errors="replace") as source:
            if _SHEBANG.match(source.readline().rstrip("\n")):
                found.append(rel)
    return found


def pipe_sites(root: Path, files: list[str]) -> list[str]:
    """`path:line:text` per site; comments dropped, a `|` or `\\` line joined to the next."""
    sites: list[str] = []
    for rel in files:
        buf, start = "", 0
        lines = (root / rel).read_text(errors="replace").splitlines()
        for number, line in enumerate(lines, start=1):
            if re.match(r"^\s*#", line):
                continue
            if not buf:
                buf, start = line, number
            else:
                buf += re.sub(r"^\s+", " ", line)
            if re.search(r"(\||\\)\s*$", buf):
                continue
            if SITE_RE.search(buf):
                sites.append(f"{rel}:{start}:{buf}")
            buf = ""
        if buf and SITE_RE.search(buf):
            sites.append(f"{rel}:{start}:{buf}")
    return sites


def site_is_disposed(text: str) -> bool:
    """The valve with a reason, a braced producer, or no reader left once END and `||` are out."""
    if "pipefail-ok:" in text and text.split("pipefail-ok:", 1)[1].lstrip():
        return True
    if BRACED_RE.search(text):
        return True
    rest = text
    while block := _END_BLOCK.search(rest):
        rest = rest.replace(block.group(0), "", 1)
    rest = rest.replace("||", " or ")
    return rest != text and not SITE_RE.search(rest)


def census(root: Path) -> Census:
    files = pipe_files(root)
    sites = pipe_sites(root, files)
    open_ = tuple(s for s in sites if not site_is_disposed(s.split(":", 2)[2]))
    return Census(len(files), len(sites), len(sites) - len(open_), open_)


def ratchet(found: Census, recorded: int) -> tuple[bool, str]:
    """Green at or under `recorded` (naming the lower number to record), red over it naming all."""
    if len(found.open) > recorded:
        named = "\n".join(f"             OPEN {s}" for s in found.open)
        return False, f"open sites grew to {len(found.open)}, over the recorded {recorded}\n{named}"
    if len(found.open) < recorded:
        return True, f"record it: PIPEFAIL_OPEN_RECORDED={len(found.open)}"
    return True, ""


@pytest.fixture
def sh(capture: Callable[..., Captured]) -> Callable[[str], tuple[int, str]]:
    """Run `body` under bash with the padded producers defined; its exit and its output."""

    def run(body: str) -> tuple[int, str]:
        ran = capture(["bash", "-c", PAD + body])
        return ran.rc, ran.text()

    return run


@pytest.fixture
def plant(scratch_repo: Callable[..., Path]) -> Callable[[str, dict[str, str]], Path]:
    """A scratch repository holding `files`, committed, so the census reads its `ls-files`."""

    def build(name: str, files: dict[str, str]) -> Path:
        root = scratch_repo(name)
        for rel, body in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(body)
        commit(root)
        return root

    return build


def commit(root: Path) -> None:
    for argv in (["add", "."], ["commit", "-q", "-m", "plant"]):
        done = subprocess.run(["git", "-C", str(root), *argv], capture_output=True, text=True)
        assert done.returncode == 0, f"the plant tree would not commit: {done.stderr}"


# --- the class -----------------------------------------------------------------


def test_the_old_form_discards_the_match_under_pipefail(sh: Callable[..., tuple[int, str]]) -> None:
    rc, out = sh("set -o pipefail; v=$(padded | head -1); s=$?; printf '%s %s' \"$v\" $s")
    value, status = out.split()
    assert value == "MATCH", "the reader did not even get the line it wanted"
    assert status != "0", "the padded producer did not fail the pipeline — pipe buffer too large?"


def test_the_rewritten_form_keeps_the_match(sh: Callable[..., tuple[int, str]]) -> None:
    rc, out = sh(
        "set -o pipefail; v=$({ padded || true; } | head -1); s=$?; printf '%s %s' \"$v\" $s"
    )
    assert out == "MATCH 0"


def test_the_whole_read_then_slice_form_keeps_the_match(sh: Callable[..., tuple[int, str]]) -> None:
    rc, out = sh(
        "set -o pipefail; whole=$(padded) || exit $?; printf '%s' \"${whole%%$'\\n'*}\"; exit 0"
    )
    assert (rc, out) == (0, "MATCH")


def test_an_eof_reader_keeps_the_producers_own_status(sh: Callable[..., tuple[int, str]]) -> None:
    rc, out = sh("set -o pipefail; v=$(padded | sed -n '1p'); s=$?; printf '%s %s' \"$v\" $s")
    assert out == "MATCH 0"
    rc, out = sh(
        "set -o pipefail; v=$({ printf 'MATCH\\n'; exit 3; } | sed -n '1p'); s=$?; printf '%s' $s"
    )
    assert out == "3", "a genuinely failing producer into an EOF reader lost its status"


def test_a_quiet_reader_at_the_tail_answers_absent_for_a_line_that_is_there(
    sh: Callable[..., tuple[int, str]],
) -> None:
    rc, out = sh("set -o pipefail; lines | grep -q '^HEAD-OF-LIST$'; printf 'quiet=%s' $?")
    assert out != "quiet=0", "a quiet reader answered 0 — the producer fits the pipe buffer here"
    rc, out = sh("set -o pipefail; lines | grep '^HEAD-OF-LIST$' >/dev/null; printf 'eof=%s' $?")
    assert out == "eof=0"


def test_a_tee_at_a_pipeline_tail_takes_the_status_over(
    sh: Callable[..., tuple[int, str]], scratch: Path
) -> None:
    sink = scratch / "tee-sink.log"
    rc, out = sh(
        f"set +o pipefail; {{ printf 'MATCH\\n'; exit 3; }} | tee {sink} >/dev/null; "
        "printf 'without=%s' $?"
    )
    assert out == "without=0", "without pipefail the producer's 3 should reach the caller as 0"
    blocked = scratch / "no-such-dir" / "sink.log"
    rc, out = sh(
        f"set -o pipefail; {{ printf 'MATCH\\n'; exit 0; }} | tee {blocked} "
        ">/dev/null 2>&1; printf 'with=%s' $?"
    )
    assert out != "with=0", "under pipefail a tee that cannot write should fail the pipeline"
    rc, out = sh(
        f"set -o pipefail; ( printf 'MATCH\\n'; exit 3 ) >{sink} 2>&1; s=$?; cat {sink}; exit $s"
    )
    assert (rc, out.strip()) == (3, "MATCH")


# --- the census ------------------------------------------------------------------


def test_every_site_in_the_tree_is_disposed_of() -> None:
    found = census(ROOT)
    assert found.files >= POPULATION_FLOOR, (
        f"the census reached {found.files} tracked shell files, under the floor of"
        f" {POPULATION_FLOOR} — it read a fraction of the tree and proves nothing"
    )
    green, said = ratchet(found, PIPEFAIL_OPEN_RECORDED)
    assert green, said
    print(
        f"open sites: {len(found.open)} (recorded {PIPEFAIL_OPEN_RECORDED}) — {found.files} files,"
        f" {found.sites} sites, {found.disposed} disposed of on the line {said}"
    )
    for site in found.verdict:
        print(f"  open     {site[5:]}")


def test_a_planted_head_in_a_copy_of_a_script_is_named(
    plant: Callable[..., Path],
) -> None:
    subject = "scripts/db.sh"
    root = plant("head", {subject: (ROOT / subject).read_text()})
    assert not any(v.startswith(f"site {subject}:") for v in census(root).verdict)
    with (root / subject).open("a") as sink:
        sink.write('first="$(git ls-files | head -1)"\n')
    at = f"{subject}:{len((root / subject).read_text().splitlines())}"
    commit(root)
    found = census(root)
    assert f"site {at}" in found.verdict
    green, said = ratchet(found, 0)
    assert not green, "one open site over a recorded 0 did not red"
    assert f"OPEN {at}:" in said
    green, said = ratchet(found, 2)
    assert green, said
    assert "PIPEFAIL_OPEN_RECORDED=1" in said


def test_the_reader_sees_every_shape_and_the_continuation(plant: Callable[..., Path]) -> None:
    root = plant(
        "shapes",
        {
            "scripts/planted.sh": "#!/usr/bin/env bash\n"
            "a=$(printf x | head -1)\n"
            "b=$(printf x | grep -m1 x)\n"
            "c=$(printf x | awk '/x/ { print; exit }')\n"
            'printf x | tee "$f"\n'
            "if printf x | grep -q x; then :; fi\n",
            "scripts/tests/planted_continuation.sh": "#!/usr/bin/env bash\n"
            'if printf "%s" "$body" |\n'
            "    grep -qE NEEDLE; then :; fi\n",
            "scripts/negatives.sh": "#!/usr/bin/env bash\n"
            'if grep -q NEEDLE "$file"; then :; fi\n'
            'if grep -qF -- "$1" "$ERR" || grep -qF -- "$1" "$OUT"; then :; fi\n'
            'scan | awk "/NEEDLE/ { f = 1 } END { print f }"\n'
            'x=$(scan) || head=""\n'
            "scan | awk '/NEEDLE/ { f = 1 } END { exit !f }'\n"
            "# a comment naming | head -1 is prose\n",
        },
    )
    assert census(root).verdict == [
        "site scripts/planted.sh:2",
        "site scripts/planted.sh:3",
        "site scripts/planted.sh:4",
        "site scripts/planted.sh:5",
        "site scripts/planted.sh:6",
        "site scripts/tests/planted_continuation.sh:2",
    ]


def test_the_valve_and_the_brace_dispose_and_an_empty_valve_does_not(
    plant: Callable[..., Path],
) -> None:
    root = plant(
        "valve",
        {
            "scripts/valved.sh": "#!/usr/bin/env bash\n"
            "a=$(printf x | head -1) # pipefail-ok: one byte, far under any pipe buffer\n"
            "b=$({ printf x || true; } | head -1)\n"
            "c=$(printf x | head -1) # pipefail-ok:\n"
            "d=$({ printf x || true; } | sort | head -1)\n",
        },
    )
    assert census(root).verdict == ["site scripts/valved.sh:4", "site scripts/valved.sh:5"]


def test_the_pass_two_summary_is_capped_and_complete() -> None:
    log = "".join(
        f"FAILED apps/example/tests/test_padding.py::test_case_{i:06d} - AssertionError\n"
        for i in range(5000)
    )
    summary = pytest_x2.summary_of(log)
    assert len(summary) == 20
    assert "test_case_000000" in summary[0]
