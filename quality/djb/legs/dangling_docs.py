"""The `dangling-docs` leg: every `docs/` pointer the rung's changed files spell exists."""

# Invariant: standard library only — the registry imports every leg under the system python.
# does-not-cover: the paths class's own blind spots — `scripts/dangling_paths.py`'s docstring.

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import cast

from quality.could_not_look import CouldNotLook, tool_said
from quality.djb.legs._library import library_leg
from quality.djb.legs._run import CAUSE
from quality.djb.registry import Leg

ARGV = (("source", "scripts/docs_legs.sh", "docs_dangling_docs_loop"),)
#: A markdown path under `docs/`, wherever it is spelled.
DOCS_REF = re.compile(r"docs/[A-Za-z0-9._/-]+\.md")
#: The product-owned drawers this template documents and never ships: one exact path each.
DRAWERS = ("docs/product/instruments.local.md", "docs/product/design/patterns.local.md")
#: The platform's record: trimmed from every artifact by class, so a pointer into it is excused.
ARCHIVE = "docs/product/archive/"
#: The checkout this leg lives in: its `scripts/dangling_paths.py` is the paths class's reader.
HOME = Path(__file__).resolve().parents[3]
#: The buckets no artifact holds at their own path (`scripts/archaeology_lib.sh::bucket_for_rule`).
UNSHIPPED = ("TRIM", "SKELETON-SOURCE")
#: Re-derived by the export over the artifact's own files: its paths are entries, never pointers.
REDERIVED = (".secrets.baseline",)
#: Each argument's bucket, one per line, by the manifest's own classifier.
BUCKETS_SH = (
    '. "$0/scripts/archaeology_lib.sh" || exit 2\n'
    'for p in "$@"; do printf "%s\\n" "$(bucket_for_path "$p")"; done'
)


@dataclass
class Scan:
    """One whole-set scan: the findings, one line each, and what was read and set aside."""

    findings: list[str] = field(default_factory=list)
    sites: int = 0
    path_sites: int = 0
    drawers: int = 0
    archived: int = 0
    excused: int = 0
    notes: list[str] = field(default_factory=list)


def existing(root: Path, files: Sequence[str]) -> list[str]:
    """The listed paths that name a regular file under `root`, relative as given."""
    return [f for f in files if f and (root / f).is_file()]


def read_list(path: Path) -> list[str]:
    """A NUL-separated list on disk; `CouldNotLook` when it cannot be read."""
    try:
        return path.read_bytes().decode().split("\0")
    except (OSError, UnicodeDecodeError) as exc:
        raise CouldNotLook(f"the file list {path} could not be read: {exc}") from exc


def pointers(root: Path, files: Sequence[str]) -> list[tuple[str, str]]:
    """Every distinct (file, `docs/…md` spelling) in the set, in `LC_ALL=C sort -u` order."""
    seen: set[str] = set()
    for rel in files:
        if rel in REDERIVED:
            continue
        try:
            data = (root / rel).read_bytes()
        except OSError as exc:
            raise CouldNotLook(f"the pointer scan could not read {rel}: {exc}") from exc
        if b"\0" in data:
            continue
        for match in DOCS_REF.finditer(data.decode("latin-1")):
            seen.add(f"{rel}:{match.group(0)}")
    rows = sorted(seen, key=lambda row: row.encode("latin-1"))
    return [(row.split(":", 1)[0], row.split(":", 1)[1]) for row in rows]


def buckets(refs: Sequence[str]) -> dict[str, str]:
    """Each path's publication bucket by this checkout's classifier; `CouldNotLook` if it fails."""
    if not refs:
        return {}
    try:
        done = subprocess.run(
            ["bash", "-c", BUCKETS_SH, str(HOME), *refs],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise CouldNotLook(f"the bucket classifier could not run: {exc}") from exc
    rows = done.stdout.splitlines()
    if done.returncode != 0 or len(rows) != len(refs):
        raise CouldNotLook(
            f"the bucket classifier exited {done.returncode} with {len(rows)} of {len(refs)}"
            f" answers: {done.stderr.strip()}"
        )
    return dict(zip(refs, rows, strict=True))


def paths_reader() -> ModuleType:
    """`scripts/dangling_paths.py` of this checkout, imported by path where it lives."""
    path = HOME / "scripts" / "dangling_paths.py"
    spec = importlib.util.spec_from_file_location("djb_dangling_paths", path)
    if spec is None or spec.loader is None:
        raise CouldNotLook(f"the paths reader {path} could not be loaded")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except (OSError, SyntaxError) as exc:
        raise CouldNotLook(f"the paths reader {path} could not be loaded: {exc}") from exc
    return module


def dangling_docs(
    root: Path,
    files: Sequence[str],
    noun: str,
    trimmed: Sequence[str] = (),
    measured: Sequence[str] = (),
) -> Scan:
    """Both classes over the whole set: every `docs/` pointer, then every repository path."""
    scan = Scan()
    archive = {p for p in trimmed if p.startswith(ARCHIVE)}
    present = existing(root, files)
    rows = pointers(root, present)
    scan.sites = len(rows)
    held = sorted({ref for _, ref in rows if (root / ref).is_file()})
    bucket = buckets([ref for ref in held if not ref.startswith(ARCHIVE)])
    for rel, ref in rows:
        if bucket.get(ref) in UNSHIPPED:
            scan.findings.append(
                f"dangling-docs: {ref} is trimmed from every artifact ({bucket[ref]})"
                f" — spelled in {rel}"
            )
            continue
        if (root / ref).is_file():
            continue
        if ref in DRAWERS:
            scan.drawers += 1
            continue
        if ref in archive:
            scan.archived += 1
            continue
        scan.findings.append(f"dangling-docs: {ref} does not exist in {noun} — spelled in {rel}")
    if scan.drawers:
        scan.notes.append(
            f"  {scan.drawers} pointer(s) exempt: {DRAWERS[0]} and {DRAWERS[1]} are product-owned"
            " drawers this template documents and never ships (publish.sh R0)"
        )
    if scan.archived:
        scan.notes.append(
            f"  {scan.archived} pointer(s) excused: {ARCHIVE} is the platform's record, trimmed"
            " from every artifact by class"
        )
    reader = paths_reader()
    run = cast(
        Callable[..., tuple[int, list[str], int]],
        reader.scan,
    )
    try:
        sites, found, excused = run(root, present, noun, set(trimmed), set(measured) | archive)
    except (OSError, subprocess.CalledProcessError) as exc:
        said = tool_said(getattr(exc, "stderr", None))
        raise CouldNotLook(f"dangling-paths: could not look — {exc}{said}") from exc
    scan.path_sites = sites
    scan.findings.extend(found)
    scan.excused = excused
    if excused:
        scan.notes.append(
            f"  {excused} path spelling(s) excused: a measured file, a trimmed directory or"
            " an archive file"
        )
    return scan


def main(argv: Sequence[str] | None = None) -> int:
    """`<root> <nul-list> [--trimmed f] [--measured f] [--noun n] [--sites-file f]`: 0 · 2."""
    args = list(sys.argv[1:] if argv is None else argv)
    opts: dict[str, str] = {}
    for flag in ("--trimmed", "--measured", "--noun", "--sites-file"):
        if flag in args:
            at = args.index(flag)
            opts[flag] = args[at + 1]
            del args[at : at + 2]
    if len(args) != 2:
        print(
            "usage: dangling_docs <root> <nul-list> [--trimmed f] [--measured f]", file=sys.stderr
        )
        return 2
    root = Path(args[0])
    noun = opts.get("--noun", "the artifact")
    try:
        files = read_list(Path(args[1]))
        trimmed = read_list(Path(opts["--trimmed"])) if "--trimmed" in opts else []
        measured = read_list(Path(opts["--measured"])) if "--measured" in opts else []
        scan = dangling_docs(root, files, noun, trimmed, measured)
    except CouldNotLook as cannot:
        print(f"!! dangling-docs: {cannot}", file=sys.stderr)
        return 2
    for line in scan.findings:
        print(line)
    for note in scan.notes:
        print(note, file=sys.stderr)
    if "--sites-file" in opts:
        Path(opts["--sites-file"]).write_text(f"{scan.sites} {scan.path_sites}\n")
    return 0


LEG = Leg(
    "dangling-docs",
    "static",
    "every docs/ pointer spelled in THE ACTIVE RUNG'S CHANGED FILES exists in the tree, no changed "
    "SHIP page names a ledger id, a trimmed path or a passed future, and every derived block in "
    "the tree is current — publish.sh's whole-artifact scan stays the belt",
    library_leg(
        "docs_dangling_docs_loop",
        (
            "!! the dangling-docs leg COULD NOT LOOK — see above. The changed-file set, the",
            "   pointer scan, the current-state census or a derived block's input was",
            "   unreadable. Nothing was judged.",
            CAUSE,
        ),
    ),
    "adr-census",
    argv=ARGV,
)


if __name__ == "__main__":
    raise SystemExit(main())
