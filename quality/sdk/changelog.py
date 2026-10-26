"""The CHANGELOG's `### SDK` section, derived from the surface against the previous release's."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from quality.could_not_look import CouldNotLook, exit_could_not_look
from quality.sdk.census import ROOT
from quality.sdk.surface import (
    SURFACE,
    changed_fields,
    current,
    cutting_from_unreleased,
    load,
    previous,
    qualified,
)

HEADING = "### SDK"
UNRELEASED = "Unreleased"
WRITE = "python -m quality.sdk --changelog --write"


def derive(prev: Mapping[str, Any], cur: Mapping[str, Any]) -> list[str]:
    """The section's lines: what was added, deprecated, removed, and which bases migrate."""
    before, now = prev.get("names") or {}, cur.get("names") or {}
    deps, was = cur.get("deprecations") or {}, prev.get("deprecations") or {}
    added = sorted(set(now) - set(before))
    removed = sorted(set(before) - set(now) - set(deps))
    migration = sorted(
        f"{name}.{f}"
        for name, new in now.items()
        if new.get("migration") and name in before
        for f in changed_fields(before[name], new)
    )
    lines = [HEADING, ""]
    if added and not before:
        lines.append(f"- added: {len(added)} names — {SURFACE} is the record")
    elif added:
        lines.append(f"- added: {', '.join(added)}")
    lines += [
        f"- deprecated: {name} ({e['kind']}, until v{e['until']}) → {qualified(name, e['instead'])}"
        for name, e in sorted(deps.items())
        if name not in was
    ]
    if removed:
        lines.append(f"- removed: {', '.join(removed)}")
    if migration:
        lines.append(f"- migration: {', '.join(migration)}")
    if len(lines) == 2:
        lines.append("- unchanged")
    return lines


def section_name(root: Path) -> str:
    """The section in progress: `Unreleased` while it is headed, else the version being cut."""
    return UNRELEASED if cutting_from_unreleased(root) else current(root)


def bounds(lines: list[str], name: str) -> tuple[int, int, int]:
    """(the release heading's line, the `### SDK` start or -1, its end) in CHANGELOG.md."""
    head = next((i for i, line in enumerate(lines) if line.startswith(f"## [{name}]")), -1)
    if head < 0:
        raise CouldNotLook(f"CHANGELOG.md has no `## [{name}]` section")
    end = next((i for i in range(head + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    start = next((i for i in range(head + 1, end) if lines[i] == HEADING), -1)
    if start < 0:
        return head, -1, -1
    stop = next((i for i in range(start + 1, end) if lines[i].startswith(("### ", "## "))), end)
    return head, start, stop


def main(argv: Sequence[str], root: Path | None = None) -> int:
    """`--changelog` prints the section; `--check` refuses a hand edit; `--write` rewrites it."""
    parser = argparse.ArgumentParser(prog="python -m quality.sdk --changelog")
    parser.add_argument("--changelog", action="store_true", required=True)
    act = parser.add_mutually_exclusive_group()
    act.add_argument("--check", action="store_true", help="exit 1 when the section differs")
    act.add_argument("--write", action="store_true", help="rewrite the section in CHANGELOG.md")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(list(argv))
    home = (args.root or root or ROOT).resolve()
    try:
        name = section_name(home)
        tag, prev, line = previous(home, before="" if name == UNRELEASED else name)
        derived = derive(prev, load((home / SURFACE).read_text(), SURFACE))
        lines = (home / "CHANGELOG.md").read_text().split("\n")
        head, start, stop = bounds(lines, name)
    except (CouldNotLook, OSError) as exc:
        exit_could_not_look(str(exc))
    print(f"changelog: ## [{name}] · {line}")
    filed = [ln for ln in lines[start:stop] if ln.strip()] if start >= 0 else []
    wanted = [ln for ln in derived if ln.strip()]
    if args.check:
        if filed != wanted:
            print(f"changelog: the `{HEADING}` section of ## [{name}] is not the derived one —")
            print(f"   it is written by `{WRITE}`, never by hand.")
            return 1
        print(f"changelog: `{HEADING}` of ## [{name}] is the derived one")
        return 0
    if args.write:
        block = [*derived, ""]
        if start < 0:
            lines[head + 1 : head + 2] = ["", *block]
        else:
            lines[start:stop] = block
        (home / "CHANGELOG.md").write_text("\n".join(lines))
        print(f"changelog: wrote `{HEADING}` under ## [{name}]")
        return 0
    print("\n".join(derived))
    return 0
