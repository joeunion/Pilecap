"""Every `scripts/gate_ledger.sh` function has a caller, or says who calls it from outside."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER = "scripts/gate_ledger.sh"
#: Where a caller may live: the tree's code, never its prose.
SCOPE = ("scripts", "quality", ".github", "deploy", "apps")
DEF = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\(\) \{")
WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
ENTRY = re.compile(r"^#\s*entry:\s*\S")
DOES_NOT_COVER = (
    "a call whose name is built at runtime (concatenation, `eval`, a `$fn` dispatch) reads as"
    " no call and is reported an orphan; a non-call spelling on a code line (an `echo` of the"
    " name) counts as one; a caller outside SCOPE is seen only through its `# entry:` marker;"
    " and the census is one hop, so a function only an orphan calls counts as called"
)


def definitions(lines: list[str]) -> dict[str, tuple[int, int, bool]]:
    """Each function's (first line, last line, carries an `# entry:` marker in its header)."""
    found: dict[str, tuple[int, int, bool]] = {}
    for i, line in enumerate(lines):
        match = DEF.match(line)
        if not match:
            continue
        end = i
        if not line.rstrip().endswith("}"):
            while end < len(lines) and not lines[end].startswith("}"):
                end += 1
        head = i - 1
        entry = False
        while head >= 0 and lines[head].startswith("#"):
            entry = entry or bool(ENTRY.match(lines[head]))
            head -= 1
        found[match.group(1)] = (i, end, entry)
    return found


def code_lines(path: Path) -> list[str]:
    """The file's lines, comment lines blanked so a mention in prose is not a call."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (IsADirectoryError, FileNotFoundError):
        return []
    return ["" if line.lstrip().startswith("#") else line for line in text.splitlines()]


def orphans(root: Path) -> list[str]:
    """The functions no code line in `SCOPE` names outside their own body, unmarked."""
    lines = (root / LEDGER).read_text(encoding="utf-8").splitlines()
    defs = definitions(lines)
    names = set(defs)
    called: set[str] = {name for name, (_, _, entry) in defs.items() if entry}
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--", *SCOPE],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\0")
    me = Path(__file__).resolve().relative_to(ROOT).as_posix()
    for rel in filter(None, tracked):
        if rel == me:
            continue
        for k, line in enumerate(code_lines(root / rel)):
            for name in names.intersection(WORD.findall(line)) - called:
                if rel == LEDGER and defs[name][0] <= k <= defs[name][1]:
                    continue
                called.add(name)
    return sorted(names - called)


def test_every_ledger_function_has_a_caller() -> None:
    found = orphans(ROOT)
    assert not found, (
        f"{len(found)} function(s) in {LEDGER} have no caller outside their own body"
        f" under {', '.join(SCOPE)} — delete them, or mark an outside caller"
        f" with `# entry: <who>` above the definition: {', '.join(found)}"
        f" (does_not_cover: {DOES_NOT_COVER})"
    )


def test_the_census_sees_a_planted_orphan(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "scripts").mkdir()
    (tmp_path / LEDGER).write_text(
        "lonely_fn() {\n    echo hi\n}\n"
        "# used_fn — named by a caller below\n"
        "used_fn() {\n    used_fn_inner\n}\n"
        "# entry: an operator at a prompt\n"
        "marked_fn() { :; }\n"
        "# used_fn_inner — only used_fn calls it\n"
        "used_fn_inner() { :; }\n"
    )
    (tmp_path / "scripts" / "caller.sh").write_text("# lonely_fn in prose is no call\nused_fn\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "scripts"], check=True)
    assert orphans(tmp_path) == ["lonely_fn"]
