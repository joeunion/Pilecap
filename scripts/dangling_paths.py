"""Print every path, `path::symbol` or `path:line` in a file's prose that the root does not hold.

does-not-cover: a code line, a path built by concatenation, a root-level name with no `/`.
does-not-cover: a symbol outside Python (top-level, or `Cls.member`) and shell (`name()`).
does-not-cover: a symbol a module serves from its own `__getattr__` (unjudged, never refused).
does-not-cover: a drawer, a `zzz_` plant path, a `.gitignore`d path (excused, never judged).
does-not-cover: a Markdown fence whose opening line says `example` (deliberately not this tree).
does-not-cover: `CHANGELOG.md` below its first released heading (history keeps its words).
does-not-cover: a canary fixture under `quality/canary/` (wrong by design, never judged).
does-not-cover: a path under a top-level directory the root does not hold (never read as a path).
does-not-cover: a name after a placeholder (`<`, `{` …); only the directory before it is judged.
does-not-cover: a Markdown worked example: its `<!-- worked example` marker to the next `#`/`##`.
does-not-cover: a `--measured` file, a directory above a `--trimmed` path (the product grows both).
does-not-cover: whether a non-blank cited line is the RIGHT line — `path:line` proves presence only.
does-not-cover: a `:line` in an `example` fence, below CHANGELOG's first release, past a `<`.
does-not-cover: a `:line` into a file that is not UTF-8 text (unjudged, never refused).
"""

from __future__ import annotations

import ast
import fnmatch
import io
import mimetypes
import os
import re
import subprocess
import sys
import tokenize
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quality.could_not_look import tool_said  # noqa: E402

USAGE = (
    "usage: dangling_paths.py <root> (<nul-list> | --ship) [--trimmed <nul-list>]"
    " [--measured <nul-list>] [--sites-file <f>] [--noun <words>]\n"
    "       dangling_paths.py <root> --rewrite-lines <file> [--write]"
)
# The root's own classifier, asked once per tracked path; NUL-separated SHIP paths on stdout.
SHIP_SH = (
    '. scripts/archaeology_lib.sh || exit 2; git ls-files -z | while IFS= read -r -d "" f; do '
    '[ -f "$f" ] && [ "$(bucket_for_path "$f")" = SHIP ] && printf "%s\\0" "$f"; done; exit 0'
)
PLACEHOLDER = set("<*{$[(%…")
# The gate's plant namespace: a `zzz_` directory exists only while a self-test holds it.
PLANT = re.compile(r"(?:^|/)zzz_")
CANARY = re.compile(r"^quality/(?:local/)?canary/")
HASH_TYPES = {".sh", ".bash", ".toml", ".cfg", ".ini", ".txt", ".dockerignore", ".gitignore", ""}
SLASH_TYPES = {".ts", ".tsx", ".js", ".mjs", ".cjs", ".css"}
YAML_TYPES = {".yaml", ".yml"}
MD_TYPES = {".md"}
RELEASED = re.compile(r"^## \[(?!Unreleased\])")
# The ledger skeletons' worked-example marker (`scripts/publish.sh` § R7); a `#`/`##` ends it.
WORKED = re.compile(r"^<!-- worked example")
EXAMPLE_END = re.compile(r"^##? ")
YAML_KEY = re.compile(r"^(\s*(?:-\s+)?)([a-z_]+):")
YAML_PROSE_KEYS = {
    "statement",
    "doc",
    "does_not_cover",
    "reason",
    "memo",
    "why",
    "note",
    "description",
}
# The product's drawers (`quality/djb/rituals/divergence.py::DRAWER_GLOBS`): never shipped.
DRAWER = re.compile(r"(?:^|/)local(?:/|$)|\.local\.md$|^apps/conftest_local\.py$")
#: A cited line that holds only one of these says nothing: the memo's "lands on the closer" class.
CLOSERS = {")", "]", "}", "),", "],", "},", '"""', "'''"}


def held(root: Path) -> set[str]:
    """The paths the root holds: tracked and unignored in a checkout, every file elsewhere."""
    if (root / ".git").exists():
        out = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
            ],
            capture_output=True,
            check=True,
        ).stdout.decode()
        return {p for p in out.split("\0") if p and (root / p).exists()}
    found: set[str] = set()
    for base, _dirs, files in os.walk(root):
        for f in files:
            found.add(Path(base, f).relative_to(root).as_posix())
    return found


def path_re(tops: set[str]) -> re.Pattern[str]:
    """A path that opens with one of the root's top-level directories."""
    alt = "|".join(re.escape(t) for t in sorted(tops, key=len, reverse=True))
    return re.compile(
        rf"(?<![\w./~@-])(?:\./)?((?:{alt})/(?:[\w.-]+/)*(?:[\w-]+(?:\.[\w-]+)*)?/?)"
        r"(?:::([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)|:(\d+)(?:-(\d+))?(?![\w-]))?"
    )


def py_prose(text: str) -> list[tuple[int, str]]:
    """Comment lines and docstring lines of one Python module."""
    lines: list[tuple[int, str]] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                lines.append((tok.start[0], tok.string))
        tree = ast.parse(text)
    except (SyntaxError, tokenize.TokenError, ValueError):
        return [(i, ln) for i, ln in enumerate(text.splitlines(), 1) if ln.lstrip().startswith("#")]
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                doc = body[0].value
                if isinstance(doc.value, str):
                    src = text.splitlines()[doc.lineno - 1 : doc.end_lineno]
                    lines.extend((doc.lineno + k, ln) for k, ln in enumerate(src))
    return lines


def comment_tail(line: str, marker: str) -> str | None:
    """The comment part of one line, or None when it has none."""
    s = line.lstrip()
    if s.startswith(marker):
        return s
    if marker == "#":
        m = re.search(r"(?:^|\s)#\s", line)
        return line[m.start() :] if m else None
    if marker == "//":
        if s.startswith(("*", "/*")):
            return s
        m = re.search(r"(?:^|\s)//\s", line)
        return line[m.start() :] if m else None
    return None


def yaml_prose(rows: list[str]) -> list[tuple[int, str]]:
    """YAML comments, and the values of the keys that hold sentences rather than plants."""
    out: list[tuple[int, str]] = []
    under: int | None = None
    for i, ln in enumerate(rows, 1):
        indent = len(ln) - len(ln.lstrip())
        if under is not None and ln.strip() and indent <= under:
            under = None
        m = YAML_KEY.match(ln)
        if under is not None:
            out.append((i, ln))
        elif m and m.group(2) in YAML_PROSE_KEYS:
            out.append((i, ln))
            under = len(m.group(1))
        else:
            tail = comment_tail(ln, "#")
            if tail is not None:
                out.append((i, tail))
    return out


def prose(rel: str, text: str) -> list[tuple[int, str]]:
    """The live prose lines of one file, numbered from 1."""
    suffix = Path(rel).suffix
    name = Path(rel).name
    rows = text.splitlines()
    if suffix == ".py":
        return py_prose(text)
    if suffix in MD_TYPES:
        out: list[tuple[int, str]] = []
        fence: str | None = None
        worked = False
        for i, ln in enumerate(rows, 1):
            if name == "CHANGELOG.md" and RELEASED.match(ln):
                break
            s = ln.lstrip()
            if s.startswith(("```", "~~~")):
                if fence is None:
                    fence = "example" if "example" in s.lower() else "live"
                else:
                    fence = None
                continue
            if fence is None and WORKED.match(ln):
                worked = True
            elif worked and fence is None and EXAMPLE_END.match(ln):
                worked = False
            if fence != "example" and not worked:
                out.append((i, ln))
        return out
    if suffix in YAML_TYPES:
        return yaml_prose(rows)
    marker = "//" if suffix in SLASH_TYPES else "#"
    if suffix not in SLASH_TYPES and suffix not in HASH_TYPES and name != "Dockerfile":
        return []
    found = []
    for i, ln in enumerate(rows, 1):
        tail = comment_tail(ln, marker)
        if tail is not None:
            found.append((i, tail))
    return found


def symbols(path: Path, member: bool) -> set[str] | None:
    """The names a Python or shell file defines; None when the language is not judged."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if path.suffix == ".py":
        try:
            body = ast.parse(text).body
        except SyntaxError:
            return None
        names: set[str] = set()
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
                if member and isinstance(node, ast.ClassDef):
                    for sub in node.body:
                        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            names.add(f"{node.name}.{sub.name}")
                        elif isinstance(sub, (ast.Assign, ast.AnnAssign)):
                            tg = sub.targets if isinstance(sub, ast.Assign) else [sub.target]
                            names |= {f"{node.name}.{t.id}" for t in tg if isinstance(t, ast.Name)}
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                tg = node.targets if isinstance(node, ast.Assign) else [node.target]
                names |= {t.id for t in tg if isinstance(t, ast.Name)}
        return None if "__getattr__" in names else names
    if path.suffix in {".sh", ".bash"}:
        fn = re.findall(r"^\s*(?:function\s+)?([A-Za-z_][\w]*)\s*\(\)", text, re.M)
        var = re.findall(
            r"^\s*(?:readonly\s+|export\s+|declare\s+-\w+\s+)?([A-Za-z_]\w*)=", text, re.M
        )
        return set(fn) | set(var)
    return None


def ignored(root: Path) -> list[tuple[str, bool]]:
    """The root's `.gitignore` patterns, each with whether it is anchored; negations are dropped."""
    try:
        rows = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    pats = []
    for r in rows:
        r = r.strip()
        if r and not r.startswith(("#", "!")):
            body = r.rstrip("/")
            pats.append((body.lstrip("/"), "/" in body))
    return pats


def is_ignored(path: str, pats: list[tuple[str, bool]]) -> bool:
    """True when the path, or a directory above it, matches one of the patterns."""
    parts = path.split("/")
    for k in range(1, len(parts) + 1):
        prefix = "/".join(parts[:k])
        for pat, anchored in pats:
            if fnmatch.fnmatchcase(prefix if anchored else parts[k - 1], pat):
                return True
    return False


class Judge:
    """One root's held paths, directories and symbol tables."""

    def __init__(self, root: Path, trimmed: set[str], measured: set[str]) -> None:
        self.root = root
        self.measured = measured
        self.trimmed_dirs = {
            "/".join(p.split("/")[:k]) for p in trimmed for k in range(1, p.count("/") + 1)
        }
        self.excused = 0
        self.have = held(root)
        self.dirs = {
            "/".join(p.split("/")[:k]) for p in self.have for k in range(1, p.count("/") + 1)
        }
        self.rx = path_re({d for d in self.dirs if "/" not in d})
        known = {Path(p).suffix for p in self.have} | set(mimetypes.types_map)
        self.exts = {e[1:] for e in known | HASH_TYPES | SLASH_TYPES | YAML_TYPES | MD_TYPES if e}
        self.pats = ignored(root)
        self.cache: dict[str, set[str] | None] = {}
        self.texts: dict[str, list[str] | None] = {}

    def names(self, rel: str) -> set[str] | None:
        """The symbols one held file defines, read once."""
        if rel not in self.cache:
            self.cache[rel] = symbols(self.root / rel, member=True)
        return self.cache[rel]

    def rows(self, rel: str) -> list[str] | None:
        """One held file's lines, read once; None when it is not UTF-8 text."""
        if rel not in self.texts:
            try:
                self.texts[rel] = (self.root / rel).read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                self.texts[rel] = None
        return self.texts[rel]

    def line_verdict(self, rel: str, first: int, last: int | None) -> str | None:
        """None when every cited line is inside the file and says something; else the predicate."""
        rows = self.rows(rel)
        if rows is None:
            return None
        span = f"{rel}:{first}" + (f"-{last}" if last is not None else "")
        end = first if last is None else last
        if first < 1 or end < first:
            return f"{span} is no line range"
        if end > len(rows):
            return f"{span} cites past {rel}'s end (it has {len(rows)} lines)"
        for n in sorted({first, end}):
            said = rows[n - 1].strip()
            if not said:
                return f"{span} lands on a blank line ({rel}:{n})"
            # A range may END on its block's closer; a single line or a range's start may not.
            if said in CLOSERS and n == first:
                shown = said.replace("{", "{{").replace("}", "}}")
                return f"{span} lands on a bare closer `{shown}` ({rel}:{n})"
        return None

    def verdict(
        self, spelled: str, sym: str | None, line: tuple[int, int | None] | None = None
    ) -> str | None:
        """None when the spelling resolves or is excused; else the finding's predicate."""
        bare = spelled.rstrip("/")
        if DRAWER.search(bare) or PLANT.search(bare) or is_ignored(bare, self.pats):
            return None
        if bare not in self.have and bare not in self.dirs:
            if bare in self.measured or bare in self.trimmed_dirs:
                self.excused += 1
                return None
        if bare not in self.have and bare not in self.dirs:
            stem, dot, attr = bare.rpartition(".")
            if f"{bare}.py" in self.have:
                bare = f"{bare}.py"
            elif (
                dot
                and "/" not in attr
                and attr not in self.exts
                and f"{stem}.py" in self.have
                and sym is None
            ):
                bare, sym = f"{stem}.py", attr
            else:
                return f"{spelled} does not exist in {{noun}}"
        if line is not None and bare in self.have:
            return self.line_verdict(bare, *line)
        if sym is None or bare not in self.have:
            return None
        names = self.names(bare)
        if names is not None and sym not in names:
            return f"{bare}::{sym} is defined nowhere in {bare}"
        return None


def cited(judge: Judge, rel: str, text: str, noun: str) -> tuple[int, list[str]]:
    """One file's sites and findings: each path, `path::symbol` and `path:line` its prose spells."""
    sites = 0
    findings: list[str] = []
    for lineno, ln in prose(rel, text):
        for m in judge.rx.finditer(ln):
            spelled, sym = m.group(1), m.group(2)
            last = int(m.group(4)) if m.group(4) else None
            line = (int(m.group(3)), last) if m.group(3) else None
            nxt = ln[m.end() : m.end() + 1]
            if nxt and nxt in PLACEHOLDER:
                # A placeholder ends the spelling; the directory before it is still a claim.
                spelled, sym, line = spelled[: spelled.rfind("/") + 1], None, None
                if spelled.count("/") < 2:
                    continue
            if spelled.endswith(".") or "..." in spelled:
                continue
            sites += 1
            bad = judge.verdict(spelled, sym, line)
            if bad is not None:
                findings.append(
                    f"dangling-paths: {bad.format(noun=noun)} — spelled in {rel}:{lineno}"
                )
    return sites, findings


def scan(
    root: Path, files: list[str], noun: str, trimmed: set[str], measured: set[str]
) -> tuple[int, list[str], int]:
    """The sites read, the findings one line each, and the spellings excused by class."""
    judge = Judge(root, trimmed, measured)
    sites = 0
    findings: list[str] = []
    for rel in files:
        if CANARY.match(rel):
            continue
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        found, said = cited(judge, rel, text, noun)
        sites += found
        findings += said
    return sites, findings, judge.excused


def enclosing(path: Path, line: int) -> str | None:
    """The `name` or `Cls.member` a Python file defines around `line`; None when it has none."""
    try:
        body = ast.parse(path.read_text(encoding="utf-8")).body
    except (OSError, UnicodeDecodeError, SyntaxError):
        return None
    for node in body:
        start = min([node.lineno, *(d.lineno for d in getattr(node, "decorator_list", []))])
        if not start <= line <= (node.end_lineno or node.lineno):
            continue
        if isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    first = min([sub.lineno, *(d.lineno for d in sub.decorator_list)])
                    if first <= line <= (sub.end_lineno or sub.lineno):
                        return f"{node.name}.{sub.name}"
            return node.name
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node.name
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            tg = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [t.id for t in tg if isinstance(t, ast.Name)]
            return names[0] if len(names) == 1 else None
        return None
    return None


def rewrite_lines(root: Path, rel: str, write: bool) -> int:
    """`--rewrite-lines`: propose `path::name` for every Python `path:line` inside a definition."""
    judge = Judge(root, set(), set())
    target = root / rel
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        said = tool_said(getattr(exc, "stderr", None))
        print(f"dangling-paths: could not look — {exc}{said}", file=sys.stderr)
        return 2
    rows = text.splitlines(keepends=True)
    named = stayed = 0
    for lineno, ln in prose(rel, text):
        for m in judge.rx.finditer(ln):
            if m.group(3) is None:
                continue
            spelled, first = m.group(1), int(m.group(3))
            name = enclosing(root / spelled, first) if spelled.endswith(".py") else None
            if name is None or (root / spelled).is_file() is False:
                stayed += 1
                why = "not Python" if not spelled.endswith(".py") else "no definition holds it"
                print(f"{rel}:{lineno}: {m.group(0)} stays — {why}")
                continue
            named += 1
            print(f"{rel}:{lineno}: {m.group(0)} -> {spelled}::{name}")
            if write:
                rows[lineno - 1] = rows[lineno - 1].replace(m.group(0), f"{spelled}::{name}", 1)
    if write:
        target.write_text("".join(rows), encoding="utf-8")
    print(f"  {named} proposed as path::name, {stayed} stay path:line", file=sys.stderr)
    return 0


def ship_list(root: Path) -> list[str]:
    """The root's SHIP bucket, by its own `scripts/archaeology_lib.sh::bucket_for_path`."""
    out = subprocess.run(
        ["bash", "-c", SHIP_SH], cwd=root, capture_output=True, check=True
    ).stdout.decode()
    return [f for f in out.split("\0") if f]


def main(argv: list[str]) -> int:
    """Read the list, scan, print the findings; 0 clean · 1 a finding · 2 it could not look."""
    args = list(argv)
    sites_file = noun = None
    lists: dict[str, set[str]] = {"--trimmed": set(), "--measured": set()}
    for flag in lists:
        if flag in args:
            k = args.index(flag)
            lists[flag] = {p for p in Path(args[k + 1]).read_bytes().decode().split("\0") if p}
            del args[k : k + 2]
    if "--sites-file" in args:
        k = args.index("--sites-file")
        sites_file = args[k + 1]
        del args[k : k + 2]
    if "--noun" in args:
        k = args.index("--noun")
        noun = args[k + 1]
        del args[k : k + 2]
    if "--rewrite-lines" in args:
        k = args.index("--rewrite-lines")
        write = "--write" in args
        rest = [a for a in args[:k] + args[k + 2 :] if a != "--write"]
        if k + 1 >= len(args) or len(rest) != 1:
            print(USAGE, file=sys.stderr)
            return 2
        return rewrite_lines(Path(rest[0]), args[k + 1], write)
    ship = "--ship" in args
    if ship:
        args.remove("--ship")
    if len(args) != (1 if ship else 2):
        print(USAGE, file=sys.stderr)
        return 2
    root = Path(args[0])
    try:
        raw = ship_list(root) if ship else Path(args[1]).read_bytes().decode().split("\0")
        files = [f for f in raw if f and (root / f).is_file()]
        sites, findings, excused = scan(
            root, files, noun or "the artifact", lists["--trimmed"], lists["--measured"]
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        said = tool_said(getattr(exc, "stderr", None))
        print(f"dangling-paths: could not look — {exc}{said}", file=sys.stderr)
        return 2
    for f in findings:
        print(f)
    if excused:
        print(
            f"  {excused} path spelling(s) excused: a measured file or a trimmed directory",
            file=sys.stderr,
        )
    if sites_file:
        Path(sites_file).write_text(f"{sites}\n", encoding="utf-8")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
