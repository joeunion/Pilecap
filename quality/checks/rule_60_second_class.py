"""Rule 60's SECOND CLASS: the drawers table is the rule's one reader."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from quality.checks._hub import CheckResult, _read
from quality.worlds import SKIP_PARTS

# --- rule 60's SECOND CLASS: the drawers table is the rule's one reader -------
#
# THE TABLE IS THE RULE'S TEXT. `build-contract.md` § "The drawers" holds one
# fenced ```drawers``` block, five ` | `-separated fields per row, and this is
# the only thing that reads it. Class (a) below asks "did a product edit a
# template-owned file"; this class asks the question that makes the answer
# survivable — "was there anywhere else that edit could have gone" — and it
# asks it of the TEMPLATE's own tree, which is why it runs on a checkout with
# no base at all, where class (a) is skipped by construction.
#
# THREE DIRECTIONS, and each is a different way the convention rots:
#   1. A DRAWER NOBODY WROTE DOWN. A template-owned file opens a `local/` path
#      with no row here. The seam exists and works, and the one document that
#      is meant to list every one of them does not know about it — so the
#      product edits the template instead, which is the whole failure.
#   2. A ROW WITH NO READER. The row promises a drawer the tree does not open:
#      a rung that landed the documentation and not the discovery, or a reader
#      deleted under a row nobody re-read.
#   3. A ROW WITH NO CASE. The row names no drive case that plants one item and
#      proves the reader ran it, or names one its drive does not define. That
#      is the third class's subject (`quality/engine/selftest.py::drawers_leg`, at
#      `python -m quality.gate --selftest`), and a
#      row that loses its case takes the proof with it in silence.
#
# A `held` ROW IS A RESERVED NAME, NOT A DRAWER: `—` for reader and case,
# printed as held, and checked in the one direction that can catch a lie — if
# a template-owned file DOES open it, the row is stale and says so.
_DRAWERS_DOC = "docs/product/build-contract.md"

#: The trees a reader can live in, and the suffixes a reader can be written in.
#: A reader is CODE. Prose naming a drawer is not a reader — the template's own
#: documents name every drawer somewhere, and reading them here would let the
#: documentation satisfy the rule the documentation is the subject of.
_DRAWER_READER_TREES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("scripts", (".sh", ".py")),
    ("quality", (".py",)),
    (".github/workflows", (".yml", ".yaml")),
    ("deploy", (".sh", ".py", ".yaml", ".in")),
)
#: The one reader outside those trees: pytest collects a `conftest.py` sibling
#: BY NAME, so the fixtures drawer cannot live under a `local/` directory and
#: its reader cannot live anywhere but the door and the harness behind it.
_DRAWER_READER_EXTRA = ("apps/conftest.py", "apps/testing/*.py")

#: `<segments>/local/<member>` — a path with a `local/` component, which is the
#: whole convention (ADR platform-extension-1). Anchored on a non-path
#: character so `"$ROOT/scripts/local/fold.d"` yields the path and not the
#: interpolation around it; what leading junk survives is trimmed by
#: `_drawer_literal`, which keeps only what starts at a real top-level tree.
_DRAWER_LITERAL = re.compile(r"(?<![\w/.@-])((?:[A-Za-z0-9_.-]+/)+local/[A-Za-z0-9_.@-]+)")
#: The other two shapes the convention takes, neither with a `local/` segment:
#: a `.local.md` sibling beside a template document, and the fixtures drawer's
#: one exact path (spelled dotted as often as slashed).
_DRAWER_LOCAL_MD = re.compile(r"(?<![\w/.@-])([A-Za-z0-9_./-]*[A-Za-z0-9_-]\.local\.md)")
_DRAWER_CONFTEST = re.compile(r"(?<![\w.])apps[./]conftest_local(?:\.py)?(?![\w])")
_DRAWER_CONFTEST_PATH = "apps/conftest_local.py"

#: Where a path can start. A literal whose first segment is none of these is an
#: interpolation (`$REPO/scripts/local/fold.d`) trimmed back to the path inside
#: it; one with no such segment at all is not a path this reader can resolve,
#: and is dropped rather than guessed at.
_DRAWER_TREE_ROOTS = ("scripts", "quality", "docs", "apps", "deploy", ".github", "config")


def _drawer_literal(raw: str) -> str:
    """One matched literal, trimmed back to the repository-relative path in it."""
    parts = raw.split("/")
    for index, part in enumerate(parts):
        if part in _DRAWER_TREE_ROOTS:
            return "/".join(parts[index:])
    return ""


def _drawer_reader_files(root: Path) -> list[Path]:
    """Every file that could OPEN a drawer — code, in the template's own trees.

    The drawers themselves are excluded: a product's own leg naming a product's
    own drawer is the convention working, not a reader the template owes a row.
    """
    out: list[Path] = []
    for sub, suffixes in _DRAWER_READER_TREES:
        base = root / sub
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in suffixes:
                continue
            parts = path.relative_to(root).parts
            if "local" in parts or SKIP_PARTS & set(parts):
                continue
            out.append(path)
    for pattern in _DRAWER_READER_EXTRA:
        out.extend(path for path in sorted(root.glob(pattern)) if path.is_file())
    return out


def drawer_literals_opened(root: Path) -> dict[str, list[str]]:
    """Every drawer path the template's own code names → the files that name it.

    DERIVED FROM THE TREE, never typed: a list beside the table would make the
    table agree with itself.
    """
    found: dict[str, set[str]] = {}
    for path in _drawer_reader_files(root):
        rel = str(path.relative_to(root))
        text = _read(path)
        if not text:
            continue
        hits: set[str] = set()
        for match in _DRAWER_LITERAL.finditer(text):
            literal = _drawer_literal(match.group(1))
            if literal:
                hits.add(literal)
        for match in _DRAWER_LOCAL_MD.finditer(text):
            hits.add(match.group(1))
        if _DRAWER_CONFTEST.search(text):
            hits.add(_DRAWER_CONFTEST_PATH)
        for literal in hits:
            found.setdefault(literal, set()).add(rel)
    return {literal: sorted(files) for literal, files in sorted(found.items())}


@dataclass(frozen=True)
class DrawerRow:
    """One row of the fenced `drawers` block, as written."""

    line: int
    state: str
    what: str
    drawer: str
    reader: str
    case: str

    @property
    def prefix(self) -> str:
        """The path this row COVERS.

        A row writes the MEMBER (`scripts/local/legs/<name>.sh`), because a
        member is what a product creates; the drawer is the directory around
        it, reached by dropping every placeholder component. A row with no
        placeholder names one exact path and covers exactly it.
        """
        kept: list[str] = []
        for part in self.drawer.split("/"):
            if "<" in part:
                break
            kept.append(part)
        return "/".join(kept)


def drawer_rows(text: str) -> tuple[list[DrawerRow], list[tuple[int, str]]]:
    """Every row of every fenced ```drawers``` block, and the malformed ones.

    EVERY block, not the first: a rung that appends a second one has appended
    to the rule's text, and a reader taking only the first would be reading a
    table that is no longer the whole table. It is also the only shape this
    rule's own canary can take — the plant harness appends, so a canary row
    arrives as a fence at the foot of the file.
    """
    rows: list[DrawerRow] = []
    bad: list[tuple[int, str]] = []
    inside = False
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not inside:
            inside = stripped == "```drawers"
            continue
        if stripped.startswith("```"):
            inside = False
            continue
        if not stripped:
            continue
        fields = [f.strip() for f in stripped.split("|")]
        if len(fields) != 5:
            bad.append((number, f"{len(fields)} ` | `-separated field(s), not 5"))
            continue
        state, what, drawer, reader, case = fields
        if state not in ("live", "held"):
            bad.append((number, f"the state field is {state!r}, neither `live` nor `held`"))
            continue
        rows.append(DrawerRow(number, state, what, drawer, reader, case))
    return rows, bad


def _drawer_symbol_absent(root: Path, spec: str) -> str:
    """`<file>::<symbol>` — why it is not in this tree, or `""` when it is."""
    file_part, _, symbol = spec.partition("::")
    if not file_part or not symbol:
        return f"{spec!r} is not spelled `<file>::<symbol>`"
    target = root / file_part
    if not target.is_file():
        return f"{file_part} is not in this tree"
    if symbol not in _read(target):
        return f"{file_part} does not carry {symbol!r}"
    return ""


def _drawer_case_absent(root: Path, spec: str) -> str:
    """`<drive>::<case>` — why the drive does not DEFINE that case, or `""`.

    Defined, never merely mentioned: a case name in a comment is what a rename
    leaves behind, and it is exactly the state the third class would then fail
    on with nothing here to say why.
    """
    file_part, _, case = spec.partition("::")
    if not file_part or not case:
        return f"{spec!r} is not spelled `<drive>::<case>`"
    target = root / file_part
    if not target.is_file():
        return f"{file_part} is not in this tree"
    text = _read(target)
    if file_part.endswith(".py"):
        found = re.search(rf"^def {re.escape(case)}\(", text, re.M)
    else:
        found = re.search(rf"^{re.escape(case)}\(\) \{{", text, re.M)
    return "" if found else f"{file_part} defines no case {case!r}"


def drawers_table_findings(root: Path, out: CheckResult) -> None:
    """Rule 60's class (b). Counts `drawer_rows` and `drawer_literals`."""
    doc = root / _DRAWERS_DOC
    if not doc.is_file():
        out.hit(
            _DRAWERS_DOC,
            0,
            "rule 60's drawers table is not in this tree, so every drawer is unlisted "
            "and nothing can say which reader opens which. That is enforcement broken, "
            "not a tree with no drawers.",
            klass="drawers",
        )
        return
    rows, malformed = drawer_rows(_read(doc))
    for line, why in malformed:
        out.hit(
            _DRAWERS_DOC,
            line,
            f"this row of the `drawers` block is unreadable — {why}. A row is "
            "`<live|held> | <what a product extends> | <drawer> | <reader> | <case>`, "
            "and a `held` row writes `—` for the last two.",
            klass="drawers",
        )
    out.count("drawer_rows", len(rows))

    live = [row for row in rows if row.state == "live"]
    held = [row for row in rows if row.state == "held"]
    for row in live:
        reader_why = _drawer_symbol_absent(root, row.reader)
        if reader_why:
            out.hit(
                _DRAWERS_DOC,
                row.line,
                f"the drawer `{row.drawer}` names the reader `{row.reader}` and "
                f"{reader_why} — a drawer nothing opens is a promise. Either the reader "
                "moved and this row did not, or the row landed ahead of the rung that "
                "was to build it, in which case the row is `held` until it does.",
                klass="drawers",
            )
        elif row.prefix and row.prefix not in _read(root / row.reader.partition("::")[0]):
            out.hit(
                _DRAWERS_DOC,
                row.line,
                f"the drawer `{row.drawer}` names the reader `{row.reader}`, and that "
                f"file never spells `{row.prefix}` — so whatever that symbol reads, it "
                "is not this drawer. One reader per drawer, and this row is how a "
                "product finds it.",
                klass="drawers",
            )
        case_why = _drawer_case_absent(root, row.case)
        if case_why:
            out.hit(
                _DRAWERS_DOC,
                row.line,
                f"the drawer `{row.drawer}` names the case `{row.case}` and {case_why} — "
                "a drawer no case plants into is a drawer nobody proves runs. "
                "`python -m quality.gate --selftest` runs exactly the cases this column "
                "names (quality/engine/selftest.py::drawers_leg), "
                "so a row that loses its case loses the proof and says nothing.",
                klass="drawers",
            )

    prefixes = [(row.prefix, row) for row in live if row.prefix]
    held_prefixes = [(row.prefix, row) for row in held if row.prefix]
    opened = drawer_literals_opened(root)
    out.count("drawer_literals", len(opened))
    # A `.local.md` drawer is as often spelled by BASENAME as by path — a
    # reader holding it as a `Path` prints `CENSUS_LOCAL.name` in every message
    # it writes — so a bare basename resolves against the rows rather than
    # reading as a second, unlisted drawer.
    basenames = {p.rsplit("/", 1)[-1]: p for p, _ in prefixes if "/" in p}
    for literal, openers in opened.items():
        if any(literal == p or literal.startswith(p + "/") for p, _ in prefixes):
            continue
        if "/" not in literal and literal in basenames:
            continue
        stale = next(
            (r for p, r in held_prefixes if literal == p or literal.startswith(p + "/")), None
        )
        for opener in openers:
            if stale is not None:
                out.hit(
                    opener,
                    1,
                    f"`{opener}` opens `{literal}`, whose row in {_DRAWERS_DOC}'s `drawers` "
                    f"block is marked `held` (line {stale.line}) — a reserved name, not a "
                    "built drawer. It is live: give the row its reader and its case, or "
                    "stop opening it.",
                    klass="drawers",
                )
                continue
            out.hit(
                opener,
                1,
                f"`{opener}` opens the drawer `{literal}`, and no row of {_DRAWERS_DOC}'s "
                "fenced `drawers` block names it. A template folder that runs a list of "
                "things ships with its drawer AND with the row that says where the drawer "
                "is and what opens it — a seam nobody can find is a seam a product edits "
                "the template instead of using. Add the row: `live | <what a product "
                f"extends> | {literal}/<name> | <file>::<symbol> | <drive>::<case>`.",
                klass="drawers",
            )


_DIVERGENCE_CENSUS = "quality/djb/rituals/divergence.py"


def template_owned_files_carry_no_product_edits(root: Path, rule: dict) -> CheckResult:
    """Rule 60. A template-owned file carries no product edits.

    THE CHECK IS THE CENSUS, not a second reading of it. `quality/djb/
    rituals/divergence.py` owns "which paths does the template own" (derived
    through the publication bucket rules, so there is one classifier in this
    tree and not two) and "which of them is not the declared base's". This
    function runs it and turns its rows into findings, and that is deliberately
    all it does: a Python copy of the ownership table would be the second
    opinion the whole census discipline exists to refuse, and it would disagree
    with the hand-run census the first week somebody edited one of them.

    THE STDOUT GOES TO A FILE, NEVER A PIPE. The census refuses a piped stdout
    (exit 2) for the reason every instrument here does — a pipe replaces the
    exit status, and the exit status is the verdict — so `capture_output=True`
    would measure the refusal rather than the tree. The temporary file is the
    same discipline a builder types.

    SKIPPED IS NOT CLEAN, AND IT SAYS SO. `--if-declared` is the gate's form:
    a tree with no declared base has nothing to compare against, which is the
    TEMPLATE's own shape — it has no template — and the census prints a SKIP
    line and exits 0. The floors below still bind, because the owned set is
    derived whether or not a base exists: a classifier that stopped seeing
    `scripts/` is a floor failure here even on a tree that never compares
    anything.

    TWO CLASSES, ONE RULE, AND THE SECOND ONE RUNS FIRST. Class (a) is the
    census above — a product edit in a template-owned file. Class (b) is
    `drawers_table_findings`: the table in `build-contract.md` against the
    drawers this tree's own code opens. They are one rule because they are one
    decision (the statement's two sentences), and the ORDER matters: class (b)
    is about the template's own tree and must still be measured when class (a)
    is skipped for want of a base — which is the state this repository is
    permanently in, and the state every product is in before its first fold.
    """
    out = CheckResult()
    drawers_table_findings(root, out)
    script = root / _DIVERGENCE_CENSUS
    if not script.is_file():
        out.hit(
            _DIVERGENCE_CENSUS,
            0,
            "rule 60's census is not in this tree at all, so nothing was compared "
            "against anything. That is enforcement broken and not a clean "
            "partition; the floors below say so as exit 2.",
            klass="census",
        )
        return out

    with tempfile.NamedTemporaryFile("w+", prefix="djb-rule60-", suffix=".log") as sink:
        proc = subprocess.run(
            [sys.executable, "-m", "quality.djb.rituals.divergence", "--if-declared"],
            cwd=root,
            stdout=sink,
            stderr=subprocess.STDOUT,
            check=False,
        )
        sink.flush()
        sink.seek(0)
        report = sink.read()

    if proc.returncode == 2:
        out.hit(
            _DIVERGENCE_CENSUS,
            0,
            "rule 60's census could not look (exit 2). A tree nobody compared is "
            "not a tree with no divergences. Output:\n" + report.strip()[-1500:],
            klass="census",
        )
        return out

    for line in report.splitlines():
        stripped = line.strip()
        if stripped.startswith("census: "):
            for field in stripped[len("census: ") :].split():
                key, _, value = field.partition("=")
                if key == "owned" and value.isdigit():
                    out.count("template_owned_paths", int(value))
                elif key == "drawers" and value.isdigit():
                    out.count("drawer_globs", int(value))
            continue
        if not stripped.startswith("divergence: "):
            continue
        # `divergence: <path> · <±lines> · <last commit>` — the census's own
        # row, split on its own separator. A `named-divergence:` row does not
        # reach here: a divergence the product's architecture.md names is a
        # decision, and the census prints it under a different noun for exactly
        # that reason.
        #
        # THE SEPARATOR IS REQUIRED, and a live drive is what taught it. The
        # refusal's closing block prints the LINE TO ADD, one per unnamed path,
        # and that line is `divergence: <path> — <reason>` by construction —
        # it has to be, it is meant to be copied. Read on the prefix alone,
        # the reader took each of those as a second row and filed a finding
        # against a path named `<path> — <why this product needs it>`: a
        # citation printed with total confidence, at a file that does not
        # exist. The ROW carries ` · `; the instruction never can.
        body = stripped[len("divergence: ") :]
        if " · " not in body:
            continue
        path = body.split(" · ", 1)[0].strip()
        if not path:
            continue
        out.hit(
            path,
            1,
            f"`{path}` is template-owned and its content is not the declared base's, "
            "and the product's own docs/product/architecture.md does not name it. A "
            "divergence is a decision, not a defect — record it as "
            f"`divergence: {path} — <reason>` in that file, or move the change into "
            "the local/ drawer beside it, which the template never ships and so can "
            "never conflict with. The per-path table is docs/product/build-contract.md "
            "§ Ownership.",
            klass="divergence",
        )
    return out
