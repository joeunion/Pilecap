"""Every `# noqa` that silences a ruff `S` (bandit) finding says why, at the valve floor."""

# does-not-cover: whether the reason is TRUE — a reviewer reads it; this proves one exists.
# does-not-cover: a file `git ls-files` does not name — untracked Python is not scanned.

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from quality.reason_floor import MIN_REASON

pytestmark = pytest.mark.drives("pyproject.toml")

ROOT = Path(__file__).resolve().parents[2]
#: A noqa naming codes, then optionally ` — reason` (or ` - reason`) up to the next comment.
NOQA = re.compile(r"#\s*noqa:\s*(?P<codes>[A-Z]+\d+(?:\s*,\s*[A-Z]+\d+)*)(?P<rest>[^#]*)")
SEPARATOR = re.compile(r"^\s*(?:—|-{1,2})\s*")


def security_noqas(text: str) -> list[tuple[int, str, str]]:
    """Each line's `S` noqa as (line, codes, reason); reason is "" when the separator is missing."""
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        for match in NOQA.finditer(line):
            codes = match["codes"]
            if not re.search(r"\bS\d{3}\b", codes):
                continue
            rest = match["rest"]
            lead = SEPARATOR.match(rest)
            found.append((number, codes, rest[lead.end() :].strip() if lead else ""))
    return found


def tracked_python(root: Path = ROOT) -> list[Path]:
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "*.py"],
        capture_output=True,
        check=True,
    )
    return [root / name for name in listed.stdout.decode().split("\0") if name]


def excused(root: Path = ROOT) -> list[tuple[str, int, str, str]]:
    rows = []
    for path in tracked_python(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = str(path.relative_to(root))
        rows += [(rel, line, codes, reason) for line, codes, reason in security_noqas(text)]
    return rows


#: The plants spell the valve at runtime so this file's own census reads none of them.
VALVE = "# " + "noqa"


@pytest.mark.parametrize(
    ("line", "short"),
    [
        (f"x = 1  {VALVE}: S105", True),
        (f"x = 1  {VALVE}: S105 — short", True),
        (f"x = 1  {VALVE}: E501, S603  # pragma: allowlist secret", True),
        (f"x = 1  {VALVE}: S105 — the setting NAME the guard refuses", False),
        (f"x = 1  {VALVE}: BLE001, S110 - cleanup must not mask the reading", False),
        (f"x = 1  {VALVE}: E501", None),
    ],
)
def test_the_reader_tells_a_reason_from_a_bare_valve(line: str, short: bool | None) -> None:
    found = security_noqas(line)
    if short is None:
        assert found == []
        return
    [(_, _, reason)] = found
    assert (len(reason) < MIN_REASON) is short, reason


def test_every_security_noqa_carries_a_reason() -> None:
    bare = [
        f"{rel}:{line}  noqa: {codes}  reason={reason!r}"
        for rel, line, codes, reason in excused()
        if len(reason) < MIN_REASON
    ]
    assert not bare, (
        f"{len(bare)} `S` noqa without a reason of {MIN_REASON}+ characters "
        "(`# noqa: S<id> — <what the literal or call is>`):\n" + "\n".join(bare)
    )


def test_the_count_is_said(capsys: pytest.CaptureFixture[str]) -> None:
    rows = excused()
    lines = len({(rel, line) for rel, line, _, _ in rows})
    with capsys.disabled():
        print(f"\nsecurity noqa census: {lines} excused lines in {len({r[0] for r in rows})} files")
    assert lines > 0, "the census read no `S` noqa at all — the reader is blind"
