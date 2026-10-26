"""Print every line of a shipped page that names what the export lacks or a future the tree passed.

does-not-cover: `CHANGELOG.md` below its first released heading (history keeps its words).
does-not-cover: `docs/product/adrs/**` — the decision log, where a context may speak of a future.
does-not-cover: `cycles/README.md`, the EXAMPLE plan and `briefs/README.md` (R8S, format teaching).
does-not-cover: a Markdown fence whose opening line says `example` (deliberately not this tree).
does-not-cover: the ledger skeletons themselves (bucket SKELETON, never SHIP) and a quality fixture.
does-not-cover: a skeleton ledger named as the source of rows the export does not carry (a reading).
does-not-cover: a page that is not Markdown; a future spoken in words none of the classes holds.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

USAGE = "usage: current_state_census.py <root> (--ship | <nul-list>)"
#: The manifest's executed form; a root without it cannot say what ships.
MANIFEST = "scripts/archaeology_lib.sh"
#: This census's own checkout, whose classifier judges a list a caller already selected.
HOME = Path(__file__).resolve().parents[1]
if str(HOME) not in sys.path:
    sys.path.insert(0, str(HOME))

from quality.could_not_look import CouldNotLook  # noqa: E402

#: The root's own classifier, asked once per tracked Markdown path; NUL-separated SHIP paths.
SHIP_SH = (
    '. scripts/archaeology_lib.sh || exit 2; git ls-files -z -- "*.md" | '
    'while IFS= read -r -d "" f; do '
    '[ -f "$f" ] && [ "$(bucket_for_path "$f")" = SHIP ] && printf "%s\\0" "$f"; done; exit 0'
)
#: One bucket per NUL-separated path on stdin, one per line on stdout.
BUCKET_SH = (
    ". scripts/archaeology_lib.sh || exit 2; "
    'while IFS= read -r -d "" f; do printf "%s\\n" "$(bucket_for_path "$f")"; done; exit 0'
)
#: Paths the census never reads, by class (the module docstring says why each).
UNREAD = re.compile(
    r"^(?:docs/product/adrs/|docs/product/(?:cycles|briefs)/|quality/(?:local/)?(?:canary|negative|tests/fixtures)/)"
)
RELEASED = re.compile(r"^## \[(?!Unreleased\])")
CODE = re.compile(r"^[ \t]*(```|~~~)")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
#: A heading under which a future is the section's subject.
EXEMPT_HEADING = re.compile(r"Blind spots|Triggers|What this does not cover|Not yet", re.I)
PLANNED_OPEN = re.compile(r"^\s*<!-- planned -->\s*$")
PLANNED_CLOSE = re.compile(r"^\s*<!-- /planned -->\s*$")
LEDGER_ID = re.compile(r"\bN\d{3,4}\b|\b[A-Z]{2,}-[A-Z]+-\d\b")
FUTURE = re.compile(
    r"\b(?:when|until|once)\s+(?:[\w.'`()-]+\s+){0,3}?[\w.'`()-]+\s+lands?\b"
    r"|\bwill land\b|\bis planned\b|\(planned\)|\bunbuilt\b|\bnot yet built\b|\bdeferred to\b",
    re.I,
)
#: A future dated by the release that answers it (`deferred to 2.6`) is a trigger, not a claim.
RELEASE = re.compile(r"\b(?:in|to|for|until|by|at)\s+v?\d+\.\d+(?:\.\d+)?\b")
#: A concrete repository path spelled in prose; a placeholder or a bare directory is not judged.
SPELLED = re.compile(r"(?<![\w/.-])((?:\.?[\w-]+/)+[\w.-]+\.[A-Za-z]{1,5})(?![\w/])")
BARE_MD = re.compile(r"`([\w.-]+\.md)`")
DRAWER = re.compile(r"\.local\.md$|(?:^|/)local/")


@dataclass(frozen=True)
class Finding:
    """One refused line: where, which class, and the line as written."""

    path: str
    line: int
    kind: str
    text: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}  {self.kind}  {self.text.strip()}"


def _bash(root: Path, script: str, stdin: bytes = b"") -> str:
    """`script` run by bash at `root`; a non-zero exit is could-not-look."""
    done = subprocess.run(["bash", "-c", script], cwd=root, input=stdin, capture_output=True)
    if done.returncode != 0:
        raise CouldNotLook(
            f"the classifier exited {done.returncode}: {done.stderr.decode().strip()}"
        )
    return done.stdout.decode()


def ship_pages(root: Path) -> list[str]:
    """The root's SHIP-bucket Markdown, by its own `bucket_for_path`, minus the unread classes."""
    return [f for f in _bash(root, SHIP_SH).split("\0") if f and not UNREAD.match(f)]


def buckets(root: Path, paths: list[str]) -> dict[str, str]:
    """Each path's bucket by the root's classifier, in one shell."""
    if not paths:
        return {}
    got = _bash(root, BUCKET_SH, "".join(f"{p}\0" for p in paths).encode()).splitlines()
    return dict(zip(paths, got, strict=True))


def basenames(root: Path) -> dict[str, list[str]]:
    """Every tracked (or, outside a checkout, present) Markdown file, by basename."""
    if (root / ".git").exists():
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--", "*.md"], capture_output=True
        ).stdout.decode()
        files = [f for f in out.split("\0") if f]
    else:
        files = [str(p.relative_to(root)) for p in root.rglob("*.md")]
    found: dict[str, list[str]] = {}
    for f in files:
        found.setdefault(f.rsplit("/", 1)[-1], []).append(f)
    return found


def lines(root: Path, rel: str) -> list[tuple[int, str, bool]]:
    """`(number, text, future_exempt)` for every line the census judges in one page."""
    try:
        raw = (root / rel).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise CouldNotLook(f"{rel}: {exc}") from exc
    judged: list[tuple[int, str, bool]] = []
    stack: list[tuple[int, str]] = []
    fence = example = planned = False
    for n, text in enumerate(raw, 1):
        if rel == "CHANGELOG.md" and RELEASED.match(text):
            break
        if CODE.match(text):
            if not fence:
                example = "example" in text
            fence = not fence
            continue
        if fence and example:
            continue
        if not fence:
            if PLANNED_OPEN.match(text):
                planned = True
                continue
            if PLANNED_CLOSE.match(text):
                planned = False
                continue
            heading = HEADING.match(text)
            if heading:
                depth = len(heading.group(1))
                stack = [h for h in stack if h[0] < depth] + [(depth, heading.group(2))]
        exempt = planned or any(EXEMPT_HEADING.search(h) for _, h in stack)
        judged.append((n, text, exempt))
    return judged


def scan(root: Path, pages: list[str], judge: Path) -> list[Finding]:
    """Every refused line across `pages`, in page order."""
    names = basenames(root)
    read = {rel: lines(root, rel) for rel in pages}
    spelled = sorted(
        {m.group(1) for got in read.values() for _, t, _ in got for m in SPELLED.finditer(t)}
    )
    bucket = buckets(judge, [p for p in spelled if p.startswith("docs/")])
    findings: list[Finding] = []
    for rel, got in read.items():
        for n, text, exempt in got:
            if LEDGER_ID.search(text):
                findings.append(Finding(rel, n, "ledger-id", text))
            trimmed = any(bucket.get(p) == "TRIM" for p in SPELLED.findall(text)) or any(
                buckets_of(names, b, bucket, judge) == {"TRIM"}
                for b in BARE_MD.findall(text)
                if not DRAWER.search(b)
            )
            if trimmed:
                findings.append(Finding(rel, n, "trimmed-path", text))
            if not exempt and FUTURE.search(text) and not RELEASE.search(text):
                findings.append(Finding(rel, n, "future-tense", text))
    return findings


def buckets_of(
    names: dict[str, list[str]], base: str, cache: dict[str, str], root: Path
) -> set[str]:
    """The buckets a bare basename resolves to; none at all reads as TRIM (the export lacks it)."""
    found = names.get(base, [])
    unknown = [f for f in found if f not in cache]
    cache.update(buckets(root, unknown))
    return {cache[f] for f in found} or {"TRIM"}


def main(argv: list[str]) -> int:
    """Read the pages, print the refused lines; 1 when any, 2 when it could not look."""
    args = list(argv)
    ship = "--ship" in args
    if ship:
        args.remove("--ship")
    if len(args) != (1 if ship else 2):
        print(USAGE, file=sys.stderr)
        return 2
    root = Path(args[0])
    judge = root if ship else HOME
    if not (judge / MANIFEST).is_file():
        print(
            f"current-state: could not look — no manifest at {judge}: {MANIFEST}", file=sys.stderr
        )
        return 2
    try:
        if ship:
            pages = ship_pages(root)
        else:
            listed = [p for p in Path(args[1]).read_bytes().decode().split("\0") if p]
            pages = [
                p
                for p in listed
                if p.endswith(".md") and not UNREAD.match(p) and (root / p).is_file()
            ]
        findings = scan(root, pages, judge)
    except (OSError, CouldNotLook) as exc:
        print(f"current-state: could not look — {exc}", file=sys.stderr)
        return 2
    for f in findings:
        print(f)
    print(
        f"  current-state: {len(pages)} page(s) read · {len(findings)} line(s) refused",
        file=sys.stderr,
    )
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
