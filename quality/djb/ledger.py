"""The verdict ledger: one row grammar that round-trips, one writer, and the replay of it."""

# does-not-cover: a drive key's machine half — a row carries its first 12 hex and never the input.
# does-not-cover: what a loop key's scope SELECTED; the replay re-derives keys, not selections.

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import itertools
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from quality.could_not_look import CouldNotLook, tool_said
from quality.djb import env as djb_env

#: The checkout this module runs from: the shell decider it ports is read here, never from a tree.
HOME = Path(__file__).resolve().parents[2]
#: The shell library whose declarations this module reads until it is the shim.
DECIDER = "scripts/gate_ledger.sh"

SCHEMA = "v1"
KINDS = ("full", "drive", "partition", "loop", "intent", "run")
#: Rows stamped before this are tolerated outside the grammar (`GATE_LEDGER_GRAMMAR_FROM`).
GRAMMAR_FROM = "2026-10-02"
ROW_RE = re.compile(
    r"^v1 [^ ]+ (full|drive|partition|loop|intent|run) "
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z( [^ =]+)?( [a-z][a-z_-]*=[^ ]*)*$"
)
STAMP_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
SANCTION_KINDS = ("push-wall", "ci-verdict", "docs-only", "bank", "typed", "ci")

LOOP_SCHEMA = "loop-v1"
LOOP_KEY_RE = re.compile(r"^loop-v1:[0-9a-f]{64}$")
#: The canonical scope's fields, in the order `loop_tier.sh` writes them.
SCOPE_FIELDS = ("mode", "own", "scope", "always", "tests", "seeded", "alwayson", "map")

DRIVE_SCHEMA = "drive-v1"
DRIVE_MARKER_LINES = 40
#: The module the `--loop` drives session runs every drive through (`DRIVE_JUDGE_ENTRY`).
DRIVE_JUDGE_ENTRY = "quality/tests/test_drives.py"
DRIVE_PREAMBLE = "scripts/tests/drive_preamble.sh"
_GLOB = re.compile(r"[*?\[]")
_SOURCE_LINE = re.compile(r"^[ \t]*\.[ \t]+(scripts/[A-Za-z0-9_./-]*\.sh)")
#: The gate's package and its leg runner, whose `LIBRARIES` a shim `check.sh` sources in its stead.
GATE_PACKAGE = "quality/djb/"
GATE_RUNNER = "quality/djb/legs/_run.py"
_LIBRARY_LINE = re.compile(r'^    "(scripts/[A-Za-z0-9_./-]*\.sh)",$')
_QUALITY_IMPORT = re.compile(r"^[ \t]*(?:from|import) (quality(?:\.[A-Za-z0-9_]+)*)\b(.*)$")


class MalformedRow(ValueError):
    """A line that is not a row of the one grammar."""


class Refused(ValueError):
    """The writer's refusal: nothing was recorded."""


class Mismatch(Exception):
    """The replay's finding: a recorded value its inputs do not re-derive."""


class Row(NamedTuple):
    """One ledger line: `<schema> <key> <kind> <stamp>` and its fields; a bare one is `("", t)`."""

    schema: str
    key: str
    kind: str
    stamp: str
    fields: tuple[tuple[str, str], ...]

    def get(self, name: str) -> str | None:
        """The first value of the field `name`, or None."""
        return next((v for n, v in self.fields if n == name), None)


def _field(token: str) -> tuple[str, str]:
    name, eq, value = token.partition("=")
    return (name, value) if eq and name else ("", token)


def parse(line: str) -> Row:
    """The row `line` holds; `MalformedRow` when it is not one."""
    tokens = line.split(" ")
    if len(tokens) < 4:
        raise MalformedRow(f"fewer than four fields: {line[:120]!r}")
    schema, key, kind, stamp = tokens[:4]
    if schema != SCHEMA:
        raise MalformedRow(f"schema {schema!r} is not {SCHEMA}: {line[:120]!r}")
    if kind not in KINDS:
        raise MalformedRow(f"kind {kind!r} is not one of {' '.join(KINDS)}: {line[:120]!r}")
    return Row(schema, key, kind, stamp, tuple(_field(t) for t in tokens[4:]))


def format(row: Row) -> str:
    """The one line `row` is."""
    tail = (f"{n}={v}" if n else v for n, v in row.fields)
    return " ".join([row.schema, row.key, row.kind, row.stamp, *tail])


def in_grammar(line: str) -> bool:
    """Whether `line` is in the strict grammar `GATE_LEDGER_ROW_RE` states."""
    return ROW_RE.match(line) is not None


def pre_grammar(line: str) -> bool:
    """Whether `line` is a row stamped before the strict grammar was enforced."""
    tokens = line.split(" ")
    return tokens[0] == "intent=ci" or (
        tokens[0] == SCHEMA and len(tokens) > 3 and tokens[3][:10] < GRAMMAR_FROM
    )


def ledger_path(root: Path) -> Path:
    """`DJB_GATE_LEDGER` if absolute, else `<common dir>/djb-gate-verdicts`; relative: `Refused`."""
    named = djb_env.read("DJB_GATE_LEDGER")
    if named:
        if not named.startswith("/"):
            raise Refused(f"DJB_GATE_LEDGER='{named}' is relative — refusing it")
        return Path(named)
    return Path(_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")) / (
        "djb-gate-verdicts"
    )


def rows(path: Path) -> Iterator[tuple[int, str]]:
    """`(line number, line)` for every line of the ledger at `path`; nothing when there is none."""
    if not path.exists():
        return
    with path.open(encoding="utf-8", errors="surrogateescape") as lines:
        for n, line in enumerate(lines, 1):
            yield n, line.rstrip("\n")


def last(path: Path, kind: str, key: str) -> Row | None:
    """The last row of `kind` keyed `key`, or None."""
    found = None
    for _, line in rows(path):
        tokens = line.split(" ", 3)
        if len(tokens) > 2 and tokens[1] == key and tokens[2] == kind:
            found = line
    return parse(found) if found is not None else None


def encode(value: str) -> str:
    """One token: `%`, tab and space percent-encoded (`gate_ledger_enc`)."""
    return value.replace("%", "%25").replace("\t", "%09").replace(" ", "%20")


def decode(value: str) -> str:
    """The words `encode` made one token of (`gate_sanction_decode`)."""
    return value.replace("%20", " ").replace("%09", "\t").replace("%25", "%")


class Sanction(NamedTuple):
    """Why a full gate ran: `<kind>:<who>:<reason>`, one field of an enum with the valves' floor."""

    kind: str
    who: str
    reason: str

    def check(self) -> Sanction:
        """This sanction, or `Refused` naming the kind, the who, the newline or the floor."""
        if self.kind not in SANCTION_KINDS:
            raise Refused(
                f"a sanction of kind '{self.kind}' is not one of: {' '.join(SANCTION_KINDS)}"
            )
        if not self.who or ":" in self.who or "\n" in self.who:
            raise Refused(f"a sanction's who ('{self.who}') is empty or holds a colon or a newline")
        if "\n" in self.reason:
            raise Refused("a sanction's reason holds a newline — one row is one line")
        from quality.reason_floor import MIN_REASON

        if self.kind == "typed" and len(self.reason) < MIN_REASON:
            raise Refused(
                f"the sanction's reason is {len(self.reason)} character(s): '{self.reason}' — "
                f"a typed sanction's reason is at least {MIN_REASON} characters"
            )
        if not self.reason:
            raise Refused(f"a sanction of kind '{self.kind}' carries no reason")
        return self

    def field(self) -> str:
        """The row's one `sanction=` token."""
        return f"sanction={self.kind}:{encode(self.who)}:{encode(self.reason)}"

    @classmethod
    def typed(
        cls, value: str, variable: str = "DJB_GATE_SANCTION", shape: str = "<rung-id>: <reason>"
    ) -> Sanction:
        """`<variable>`'s `<who>: <reason>`, checked (`gate_sanction_typed`)."""
        if not re.match(r"^[^:]+: .+$", value):
            raise Refused(f'{variable} is not "{shape}": {value!r}')
        who, _, reason = value.partition(": ")
        return cls("typed", who, reason).check()

    @classmethod
    def parse(cls, value: str) -> Sanction:
        """The sanction a row's `sanction=` value records, checked."""
        kind, _, rest = value.partition(":")
        who, sep, reason = rest.partition(":")
        if not sep:
            raise Refused(f"sanction {value!r} has no who and reason")
        return cls(kind, decode(who), decode(reason)).check()


def sanction_check(value: str) -> None:
    """`Refused` unless `value` is a recorded sanction of the enum that clears the floor."""
    Sanction.parse(value)


def append(
    kind: str,
    key: str,
    fields: Iterable[str],
    *,
    path: Path,
    stamp: str | None = None,
    idempotent: bool = False,
    caller: str | None = None,
) -> Row:
    """Write one row through the one grammar; `Refused` names why nothing was recorded."""
    if kind not in KINDS:
        raise Refused(f"'{kind}' is not a ledger kind ({' '.join(KINDS)}) — nothing recorded")
    if not key or any(c.isspace() for c in key):
        raise Refused(f"the key '{key}' is empty or holds whitespace — nothing recorded")
    stamp = stamp or _utc_now()
    if not STAMP_RE.match(stamp):
        raise Refused(f"the stamp '{stamp}' is not UTC YYYY-MM-DDTHH:MM:SSZ — nothing recorded")
    tokens = list(fields)
    for token in tokens:
        if not token or any(c.isspace() for c in token):
            raise Refused(
                f"a {kind} field is empty or holds whitespace ('{token}') — nothing recorded"
            )
        name, value = _field(token)
        if name == "sanction":
            sanction_check(value)
    refusal = _full_refusal(tokens, caller) if kind == "full" else None
    if refusal is not None:
        raise Refused(f"{refusal} — nothing recorded")
    line = " ".join([SCHEMA, key, kind, stamp, *tokens])
    row = parse(line)
    if idempotent and any(existing == line for _, existing in rows(path)):
        return row
    with path.open("a", encoding="utf-8") as out:
        out.write(line + "\n")
    return row


def _utc_now() -> str:
    import time

    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _git(root: Path, *argv: str, env: dict[str, str] | None = None, raw: bool = False) -> str:
    done = subprocess.run(
        ["git", "-C", str(root), *argv], capture_output=True, text=not raw, env=env, check=False
    )
    if done.returncode != 0:
        err = done.stderr if isinstance(done.stderr, str) else done.stderr.decode(errors="replace")
        raise Mismatch(f"git {' '.join(argv)} failed: {err.strip()}")
    out = done.stdout if isinstance(done.stdout, str) else done.stdout.decode(errors="replace")
    return out.strip()


_BLOBS: dict[str, bytes] = {}
_BATCH: dict[str, subprocess.Popen[bytes]] = {}


def _blob(root: Path, sha: str) -> bytes:
    """The bytes of blob `sha`, read through one `git cat-file --batch` per root and kept."""
    if sha in _BLOBS:
        return _BLOBS[sha]
    batch = _BATCH.get(str(root))
    if batch is None or batch.poll() is not None:
        batch = subprocess.Popen(
            ["git", "-C", str(root), "cat-file", "--batch"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        _BATCH[str(root)] = batch
    assert batch.stdin is not None and batch.stdout is not None  # noqa: S101 — narrows Optional for mypy; Popen with PIPE always sets both
    batch.stdin.write(f"{sha}\n".encode())
    batch.stdin.flush()
    head = batch.stdout.readline().split()
    if len(head) != 3 or head[1] != b"blob":
        raise Mismatch(f"blob {sha} is not in this repository")
    data = bytes(batch.stdout.read(int(head[2])))
    batch.stdout.read(1)
    _BLOBS[sha] = data
    return data


def sha256_hex(data: bytes) -> str:
    """The lower-case hex SHA-256 of `data` (`sha256_of`'s answer)."""
    return hashlib.sha256(data).hexdigest()


# --- the loop key ---------------------------------------------------------------------------------


def loop_key(tree: str, env: str, scope: str) -> str:
    """`loop-v1:<sha256>` over the key tree, the environment fingerprint and the canonical scope."""
    text = f"tree={tree}\nenv={env}\nscope={scope}\n"
    return f"{LOOP_SCHEMA}:{sha256_hex(text.encode())}"


def scope_candidates(recorded: str, vocabulary: frozenset[str]) -> Iterator[str]:
    """Every canonical scope the recorded one (` ` and newline written as `_`) can have been."""
    names = "|".join(SCOPE_FIELDS)
    parts = re.split(rf"_(?=(?:{names})=)", recorded)
    choices: list[list[str]] = []
    for part in parts:
        name, eq, value = part.partition("=")
        if not eq or value in ("", "-") or "_" not in value:
            choices.append([part])
            continue
        choices.append([f"{name}={v}" for v in _value_candidates(value, vocabulary)])
    for combo in itertools.islice(itertools.product(*choices), 4096):
        yield " ".join(combo)


def _value_candidates(value: str, vocabulary: frozenset[str]) -> list[str]:
    pieces = re.split(r"_(?=apps/)|(?<=\.py)_", value)
    per: list[list[str]] = []
    for piece in pieces:
        if "/" in piece:
            per.append([piece])
        else:
            words = _segmentations(piece, vocabulary)
            per.append(words or _every_split(piece))
    return [" ".join(c) for c in itertools.islice(itertools.product(*per), 1024)]


def _segmentations(piece: str, vocabulary: frozenset[str]) -> list[str]:
    bits = piece.split("_")
    out: list[str] = []

    def walk(i: int, acc: list[str]) -> None:
        if i == len(bits):
            out.append(" ".join(acc))
            return
        for j in range(i + 1, len(bits) + 1):
            word = "_".join(bits[i:j])
            if word in vocabulary:
                walk(j, [*acc, word])

    walk(0, [])
    return out


def _every_split(piece: str) -> list[str]:
    gaps = [m.start() for m in re.finditer("_", piece)][:10]
    out = []
    for mask in range(1 << len(gaps)):
        chars = list(piece)
        for bit, at in enumerate(gaps):
            if mask >> bit & 1:
                chars[at] = " "
        out.append("".join(chars))
    return out


def app_vocabulary(root: Path) -> frozenset[str]:
    """Every app label `apps/<label>/apps.py` has named in this repository's history, or none."""
    try:
        listed = _git(root, "log", "--all", "--format=", "--name-only", "--", "apps/*/apps.py")
    except Mismatch:
        return frozenset()
    return frozenset(p.split("/")[1] for p in listed.splitlines() if p.count("/") == 2)


# --- the docs-only decider ------------------------------------------------------------------------


def decider_value(name: str, home: Path = HOME) -> str:
    """The single-quoted value the decider assigns to `name` (`quality.loop_key.decider_value`)."""
    from quality.loop_key import decider_value as read

    return read(name, home)


def docs_only_paths(home: Path = HOME) -> tuple[str, ...]:
    """The declared docs-only list (`GATE_DOCS_ONLY_PATHS`)."""
    return tuple(decider_value("GATE_DOCS_ONLY_PATHS", home).split())


def docs_only_derived(home: Path = HOME) -> tuple[str, ...]:
    """The fold's derived files admitted by derivation (`GATE_DOCS_ONLY_DERIVED`)."""
    return tuple(decider_value("GATE_DOCS_ONLY_DERIVED", home).split())


def docs_only_admits(
    path: str, from_: str = "", to: str = "", *, root: Path, home: Path = HOME
) -> bool:
    """Whether the declared list admits `path`, or its derivation admits it between two trees."""
    from quality.loop_key import admitted, excluded_patterns

    if admitted(path, docs_only_paths(home), excluded_patterns(home)):
        return True
    if path not in docs_only_derived(home) or not from_ or not to:
        return False
    if path == SECRETS_BASELINE:
        return _baseline_unmoved(root, path, from_, to)
    lines = _changed_lines(root, path, from_, to)
    if lines is None:
        return False
    if path == "quality/budgets.yaml":
        return _lowers(lines)
    return _walls_moved(lines) or _walls_rows(lines)


#: The scanner's baseline: derived when its findings only moved (CI-THIRD-1 1.2).
SECRETS_BASELINE = ".secrets.baseline"


def _baseline_unmoved(root: Path, path: str, from_: str, to: str) -> bool:
    """Whether the baseline changed only by stamp, `line_number` or a finding's file."""
    import json

    def findings(rev: str) -> tuple[dict[str, object], list[str]] | None:
        done = subprocess.run(
            ["git", "-C", str(root), "show", f"{rev}:{path}"],
            capture_output=True,
            text=True,
            check=False,
        )
        try:
            data = json.loads(done.stdout) if done.returncode == 0 else None
        except ValueError:
            return None
        if not isinstance(data, dict) or not isinstance(data.get("results", {}), dict):
            return None
        data.pop("generated_at", None)
        found = []
        for entries in data.pop("results", {}).values():
            for entry in entries if isinstance(entries, list) else [None]:
                if not isinstance(entry, dict):
                    return None
                kept = {k: v for k, v in entry.items() if k not in ("line_number", "filename")}
                found.append(json.dumps(kept, sort_keys=True))
        return data, sorted(found)

    old, new = findings(from_), findings(to)
    return old is not None and old == new


def _changed_lines(
    root: Path, path: str, from_: str, to: str
) -> tuple[list[str], list[str]] | None:
    done = subprocess.run(
        ["git", "-C", str(root), "diff", "-U0", "--no-color", from_, to, "--", path],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        return None
    old: list[str] = []
    new: list[str] = []
    head = re.compile(r"^(---|\+\+\+|@@|diff |index |new file|deleted file)")
    for line in done.stdout.splitlines():
        if head.match(line):
            continue
        if line.startswith("-"):
            old.append(line[1:])
        elif line.startswith("+"):
            new.append(line[1:])
    return (old, new) if old or new else None


def _walls_moved(lines: tuple[list[str], list[str]]) -> bool:
    old, new = lines
    if not old or len(old) != len(new):
        return False
    digits = re.compile(r"[0-9]+")
    return all(digits.sub("0", a) == digits.sub("0", b) for a, b in zip(old, new, strict=True))


_WALLS_NUMBER = r'"[^"]+": -?[0-9]+(\.[0-9]+)?'
_WALLS_ROW = re.compile(
    rf'^\s*"[^"]+": (-?[0-9]+(\.[0-9]+)?|\{{{_WALLS_NUMBER}(, {_WALLS_NUMBER})*\}}),?$'
)
_WALLS_STAMP = re.compile(r'^\s*"[^"]+": "(run:[0-9]+ )?tree:[0-9a-f]{40}",?$')


def _walls_rows(lines: tuple[list[str], list[str]]) -> bool:
    """Whether every changed line is a member row, added, removed or renumbered, or a stamp."""
    old, new = lines
    return all(_WALLS_ROW.match(line) or _WALLS_STAMP.match(line) for line in (*old, *new))


def _lowers(lines: tuple[list[str], list[str]]) -> bool:
    old, new = lines
    if not old or len(old) != len(new):
        return False
    number = re.compile(r": [0-9]+")
    for a, b in zip(old, new, strict=True):
        ma, mb = number.search(a), number.search(b)
        if ma is None or mb is None:
            return False
        if a[: ma.start()] != b[: mb.start()] or a[ma.end() :] != b[mb.end() :]:
            return False
        if not int(mb.group()[2:]) < int(ma.group()[2:]):
            return False
    return True


def changed_between(root: Path, from_: str, to: str) -> list[str]:
    """Every path that differs between two trees or commits (`changed_between`)."""
    return [
        p for p in _git(root, "diff", "--name-only", "--no-renames", from_, to).splitlines() if p
    ]


def docs_only_delta(
    root: Path, from_: str, to: str, prose: frozenset[str] | None, *, home: Path = HOME
) -> list[tuple[str, str]]:
    """`("docs"|"code", path)` per changed path: docs when admitted and prose (None: no census)."""
    out = []
    for p in changed_between(root, from_, to):
        docs = docs_only_admits(p, from_, to, root=root, home=home) and (
            prose is None or p in prose
        )
        out.append(("docs" if docs else "code", p))
    return out


# --- the docs-only road's plan: the source, the delta, the readers ------------------------------

#: How far back the source walk and the claims reader look; the shell passes its own as `--depth`.
DOCS_ONLY_DEPTH = 60
#: The drives the road may select as readers, by their own `# drives:` line.
DOCS_ONLY_DRIVES = "scripts/tests"
#: The roots whose quotes refuse the road unless the module declares a non-read.
DOCS_ONLY_DECLARING_ROOTS = ("apps", "config")


class DocsOnlyRefused(CouldNotLook):
    """The road's refusal: the sentence ends in "full bank", and the caller measures."""


class DocsOnlyPlan(NamedTuple):
    """What the road reuses: the measured source, its legs and proof, the delta's size, readers."""

    source: str
    legs: str
    proof: str
    n: int
    readers: tuple[str, ...]


def docs_only_claims(
    root: Path, head: str = "HEAD", base: str = "", *, depth: int | None = None
) -> list[tuple[str, str]]:
    """`(commit, path)` per `[docs-only]` subject on the first-parent line whose own diff is not."""
    span = [f"{base}..{head}"] if base else [f"--max-count={depth or DOCS_ONLY_DEPTH}", head]
    try:
        commits = _git(root, "rev-list", "--first-parent", *span).splitlines()
    except Mismatch:
        commits = []
    lies = []
    for c in filter(None, commits):
        try:
            subject = _git(root, "log", "-1", "--format=%s", c)
            _git(root, "rev-parse", "--verify", "--quiet", f"{c}^")
        except Mismatch:
            continue
        if "[docs-only]" not in subject:
            continue
        try:
            paths = _git(root, "diff-tree", "--no-commit-id", "-r", "--name-only", f"{c}^", c)
        except Mismatch:
            paths = ""
        for p in filter(None, paths.splitlines()):
            if not docs_only_admits(p, f"{c}^", c, root=root):
                lies.append((c, p))
    return lies


def docs_only_source(
    root: Path, head: str, *, depth: int | None = None, say: Callable[[str], None] | None = None
) -> tuple[str, str, str]:
    """`(M, legs, proof)`: the nearest first-parent ancestor's honoured row, `from=` followed."""
    depth = depth or DOCS_ONLY_DEPTH
    say = say or _stderr
    try:
        walk = _git(root, "rev-list", "--first-parent", "--skip=1", f"--max-count={depth}", head)
    except Mismatch:
        walk = ""
    walked = 0
    for c in filter(None, walk.splitlines()):
        walked += 1
        try:
            tree = measured_tree_of(root, c)
        except Mismatch:
            continue
        notes: list[str] = []
        row = consult(root, tree, say=notes.append)
        if row is None:
            if notes:
                say("\n".join(notes))
                raise DocsOnlyRefused(
                    "docs-only? no — the nearest banked ancestor's row is not honoured — full bank"
                )
            continue
        hops = 0
        while frm := row_field(format(row), "from"):
            hops += 1
            if not re.fullmatch(r"[0-9a-f]+", frm) or hops > 4:
                raise DocsOnlyRefused(
                    "docs-only? no — the nearest banked ancestor's row names a source this reader"
                    " cannot follow — full bank"
                )
            followed = consult(root, frm, say=lambda _: None)
            if followed is None:
                raise DocsOnlyRefused(
                    f"docs-only? no — the nearest banked ancestor's row names from={frm}, which"
                    " carries no honoured row of its own — full bank"
                )
            row, tree = followed, frm
        line = format(row)
        legs = line.split()[4] if len(line.split()) > 4 else ""
        proof = line.rsplit(" leak-proof=", 1)[1] if " leak-proof=" in line else ""
        return tree, legs, proof
    raise DocsOnlyRefused(
        f"docs-only? no — no honoured full row on any of the last {depth} first-parent ancestors"
        f" (walked {walked}) — full bank"
    )


def docs_only_nonread_covers(path: Path, needle: str) -> bool:
    """Whether the module's own non-read declaration names `needle`, or a path it is the base of."""
    from quality import loop_key

    text = loop_key._text(path)
    if text is None:
        return False
    mark = decider_value("GATE_DOCS_ONLY_NONREAD")
    return loop_key._covers(loop_key.declarations(text, mark), needle)


def docs_only_stale_nonreads(root: Path) -> list[str]:
    """`<file>:<line> <path>` per non-read under apps/ or config/ its module never quotes."""
    from quality import loop_key

    mark = decider_value("GATE_DOCS_ONLY_NONREAD")
    stale = []
    for path in loop_key.reader_files(root, DOCS_ONLY_DECLARING_ROOTS):
        text = loop_key._text(path)
        if text is None or mark not in text:
            continue
        quoted = {t for line in text.splitlines() for t in loop_key.quoted_tokens(line)}
        rel = path.relative_to(root).as_posix()
        for number, d in loop_key.declarations(text, mark):
            if d not in quoted and d.rsplit("/", 1)[-1] not in quoted:
                stale.append(f"{rel}:{number} {d}")
    return stale


def docs_only_drives(root: Path, paths: Iterable[str]) -> list[str]:
    """Every drive whose own `# drives:` line names one of `paths` or a directory above one."""
    wanted = list(paths)
    found = set()
    for drive in sorted((root / DOCS_ONLY_DRIVES).glob("test_*.sh")):
        if not drive.is_file():
            continue
        text = drive.read_text(encoding="utf-8", errors="replace")
        for token in _drives_line(text):
            declared = token[:-1] if token.endswith("/") else token
            if any(p == declared or p.startswith(f"{declared}/") for p in wanted):
                found.add(drive.relative_to(root).as_posix())
                break
    return sorted(found)


def docs_only_literal_reads(root: Path, needles: Iterable[str]) -> list[tuple[str, str]]:
    """`(file:line, needle)` per quote of a needle, from the loop key's one census."""
    from quality import loop_key

    wanted = frozenset(needles)
    if not wanted:
        return []
    mark = decider_value("GATE_DOCS_ONLY_NONREAD")
    return [(q.site, q.needle) for q in loop_key.quotes(root, wanted, mark)]


def docs_only_plan(
    root: Path, head: str, *, depth: int | None = None, say: Callable[[str], None] | None = None
) -> DocsOnlyPlan:
    """The reuse a docs-only delta earns, derived and decided; runs nothing (`DocsOnlyRefused`)."""
    say = say or _stderr
    try:
        tree = measured_tree_of(root, head)
    except Mismatch:
        raise DocsOnlyRefused(f"docs-only? no — {head} resolves to no tree — full bank") from None
    try:
        measured = measured_tree(root)
    except Mismatch:
        measured = ""
    if measured != tree:
        raise DocsOnlyRefused(
            f"docs-only? no — the measured WORKING tree ({measured or 'unreadable'}) is not HEAD's"
            f" measured tree ({tree}), so there is an uncommitted byte in the delta the row would"
            " key on — full bank"
        )
    source, legs, proof = docs_only_source(root, head, depth=depth, say=say)
    try:
        delta = changed_between(root, source, tree)
    except Mismatch:
        delta = []
    if not delta:
        raise DocsOnlyRefused(
            f"docs-only? no — HEAD's tree IS the source tree {source}, so there is nothing to"
            " reuse and a row already stands — full bank"
        )
    needles: list[str] = []
    for p in delta:
        if re.search(r"\s", p):
            raise DocsOnlyRefused(
                "docs-only? no — a changed path carries whitespace and this reader cannot name"
                " it — full bank"
            )
        if not docs_only_admits(p, root=root):
            raise DocsOnlyRefused(f"docs-only? no — {p} is not a docs-only path — full bank")
        needles += [p, p.rsplit("/", 1)[-1]]
    try:
        hits = docs_only_literal_reads(root, needles)
    except CouldNotLook as cannot:
        say(f"!! COULD NOT LOOK: {cannot}")
        raise DocsOnlyRefused(
            "docs-only? no — the literal-read census could not look — full bank"
        ) from None
    engine = False
    for site, needle in hits:
        file = site.split(":", 1)[0]
        if file.startswith(tuple(f"{r}/" for r in DOCS_ONLY_DECLARING_ROOTS)):
            if docs_only_nonread_covers(root / file, needle):
                continue
            raise DocsOnlyRefused(
                f"docs-only? no — {needle} is quoted at {site} and nothing declares the quote a"
                " non-read — full bank"
            )
        if file.startswith("quality/"):
            engine = True
    for stale in docs_only_stale_nonreads(root):
        where, declared = stale.split(" ", 1)
        raise DocsOnlyRefused(
            f"docs-only? no — {where} declares {declared} a non-read and the module never quotes"
            " it — a stale declaration — full bank"
        )
    readers = ["static", *(["full-house-rules"] if engine else []), *docs_only_drives(root, delta)]
    return DocsOnlyPlan(source, legs, proof, len(delta), tuple(readers))


# --- the drive key's parts ------------------------------------------------------------------------


# --- the loop key's tree: the prose the census leaves out ----------------------------------------

#: The census whose `--prose` paths the loop key leaves out (rule 90; `LOOP_KEY_PROSE_OWNER`).
PROSE_OWNER = "quality/loop_key.py"
#: The prose cache's bound in days; a write evicts what is older (`LOOP_KEY_PROSE_MAX_AGE_DAYS`).
PROSE_MAX_AGE_DAYS = 14
#: How many header lines a drive's `# drives:` line is read from (`DRIVE_MARKER_LINES`).
DRIVE_MARKER_LINES = 40


class KeyCannot(CouldNotLook):
    """The loop key could not look; the message is the cause, and there is no key."""


def _prose_cache(top: Path, tree: str) -> Path:
    common = Path(_git(top, "rev-parse", "--git-common-dir"))
    return (common if common.is_absolute() else top / common) / "djb-loop-key-prose" / tree


def loop_key_prose(top: Path, tree: str) -> list[str] | None:
    """The paths the loop key leaves out (`loop_key_prose`); None where there is no census."""
    if not (top / PROSE_OWNER).is_file():
        return None
    cache = _prose_cache(top, tree) if tree else None
    if cache is not None and cache.is_file():
        return [p for p in cache.read_text().splitlines() if p]
    py = top / ".venv/bin/python"
    if not os.access(py, os.X_OK):
        raise KeyCannot(f"{PROSE_OWNER} has no interpreter at {py} — no loop key")
    done = subprocess.run(
        [str(py), "-m", "quality.loop_key", "--prose"], cwd=top, capture_output=True, text=True
    )
    if done.returncode != 0:
        raise KeyCannot(
            f"python -m quality.loop_key --prose exited {done.returncode} — no loop key"
            f"{tool_said(done.stderr)}"
        )
    prose = done.stdout.splitlines()
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        staged = cache.with_name(f"{cache.name}.{os.getpid()}")
        staged.write_text("".join(f"{p}\n" for p in prose))
        staged.replace(cache)
        bound = time.time() - (PROSE_MAX_AGE_DAYS + 1) * 86400
        for entry in cache.parent.iterdir():
            if entry.is_file() and entry.stat().st_mtime <= bound:
                entry.unlink(missing_ok=True)
    return [p for p in prose if p]


def _drives_line(text: str) -> list[str]:
    for line in text.splitlines()[:DRIVE_MARKER_LINES]:
        found = re.match(r"^#[ \t]*drives:(.*)$", line)
        if found:
            return found.group(1).split()
    return []


def loop_key_keep(root: Path, tree: str, prose: Iterable[str]) -> list[str]:
    """The prose a drive in `tree` reaches by a directory or glob entry (`loop_key_keep`)."""
    dirs = set(_git(root, "ls-tree", "-r", "-d", "--name-only", tree).splitlines())
    drives = [
        e
        for e in listing(root, tree)
        if e.path.startswith(("scripts/tests/", "deploy/tests/"))
        and re.search(r"/test_[^/]*\.sh$", e.path)
    ]
    patterns = []
    for entry in drives:
        text = _blob(root, entry.blob).decode("utf-8", errors="replace")
        for word in _drives_line(text):
            if word.endswith("/") or "*" in word or word in dirs:
                patterns.append(_to_re(word))
    return sorted({p for p in prose if p and any(rx.match(p) for rx in patterns)})


def loop_key_tree(root: Path, tree: str) -> str:
    """The loop key's tree: `tree` less the prose and the derived paths (`loop_key_tree`)."""
    if not tree:
        raise KeyCannot("no tree — no loop key")
    prose = loop_key_prose(root, tree)
    if prose:
        keep = set(loop_key_keep(root, tree, prose))
        prose = [p for p in prose if p not in keep]
    if not prose:
        return tree
    with tempfile.TemporaryDirectory(prefix="djb-loop-key-index.") as scratch:
        env = dict(djb_env.environ(), GIT_INDEX_FILE=str(Path(scratch) / "index"))
        try:
            _git(root, "read-tree", tree, env=env)
        except Mismatch as error:
            raise KeyCannot(f"tree {tree} would not read — no loop key") from error
        for path in [*derived_tree_paths(root), *prose]:
            _git(root, "rm", "-r", "-f", "--cached", "-q", "--ignore-unmatch", "--", path, env=env)
        return _git(root, "write-tree", env=env)


class Entry(NamedTuple):
    """One `git ls-tree -r` line: the blob and its path."""

    blob: str
    path: str


def listing(root: Path, tree: str) -> list[Entry]:
    """The measured tree's files, `git ls-tree -r <tree>`."""
    out = []
    for line in _git(root, "ls-tree", "-r", tree).splitlines():
        meta, _, path = line.partition("\t")
        out.append(Entry(meta.split()[2], path))
    return out


def _to_re(pattern: str) -> re.Pattern[str]:
    out = []
    p = pattern.rstrip("/") if pattern.endswith("/") else pattern
    i = 0
    while i < len(p):
        ch = p[i]
        if ch == "*":
            if p[i + 1 : i + 2] == "*":
                out.append(".*")
                i += 1
            else:
                out.append("[^/]*")
        else:
            out.append(re.escape(ch))
        i += 1
    body = "".join(out)
    return re.compile(rf"^{body}(?:$|/)")


def expand(entries: list[Entry], pattern: str) -> list[str]:
    """`<blob> <path>` per file the declared `pattern` covers, sorted (`drive__expand`)."""
    rx = _to_re(pattern)
    return sorted(f"{e.blob} {e.path}" for e in entries if rx.match(e.path))


def _shell_glob(entries: list[Entry], word: str) -> list[str]:
    if not _GLOB.search(word):
        return [word]
    dirs = {str(Path(e.path).parent) for e in entries}
    every = {e.path for e in entries} | {d for d in dirs if d != "."}
    depth = word.count("/")
    hits = sorted(
        p
        for p in every
        if p.count("/") == depth
        and fnmatch.fnmatchcase(p, word)
        and not p.split("/")[-1][:1] == "."
    )
    return hits or [word]


def judge_paths(root: Path, entries: list[Entry]) -> list[Entry]:
    """The judge: its entry, the modules and fixtures beside it, and their `quality.*` imports."""
    folder = DRIVE_JUDGE_ENTRY.rsplit("/", 1)[0] + "/"
    have = {
        e
        for e in entries
        if e.path == DRIVE_JUDGE_ENTRY
        or (
            e.path.startswith(folder)
            and e.path.endswith(".py")
            and (
                not re.search(r"(^|/)test_[^/]*\.py$", e.path)
                or e.path.startswith(folder + "fixtures/")
            )
        )
    }
    if not any(e.path == DRIVE_JUDGE_ENTRY for e in have):
        return []
    by_path = {e.path: e for e in entries}
    todo = list(have)
    while todo:
        wanted: set[str] = set()
        for entry in todo:
            for module in _quality_imports(_blob(root, entry.blob).decode(errors="replace")):
                parts = module.split(".")
                for n in range(1, len(parts) + 1):
                    wanted.add("/".join(parts[:n]) + "/__init__.py")
                wanted.add("/".join(parts) + ".py")
        todo = [by_path[p] for p in sorted(wanted) if p in by_path and by_path[p] not in have]
        have.update(todo)
    return sorted(have, key=lambda e: e.path)


def _quality_imports(text: str) -> Iterator[str]:
    for line in text.splitlines():
        found = _QUALITY_IMPORT.match(line)
        if not found:
            continue
        module, rest = found.groups()
        yield module
        if line.lstrip().startswith("from "):
            words = rest.split()
            if words[:1] == ["import"]:
                for i, w in enumerate(words[1:], 1):
                    w = re.sub(r"[(),]", "", w)
                    if re.match(r"^[A-Za-z_]", w) and words[i - 1] != "as":
                        yield f"{module}.{w}"


def judge_digest(root: Path, entries: list[Entry]) -> str:
    """The SHA-256 of `judge_paths`' `<blob> <path>` lines, or `absent`; kept per listing."""
    seen = "".join(f"{e.blob} {e.path}\n" for e in entries if e.path.startswith("quality/"))
    if seen not in _JUDGE:
        paths = judge_paths(root, entries)
        _JUDGE[seen] = (
            sha256_hex("".join(f"{e.blob} {e.path}\n" for e in paths).encode())
            if paths
            else "absent"
        )
    return _JUDGE[seen]


_JUDGE: dict[str, str] = {}


def _header_line(text: str, key: str) -> str | None:
    rx = re.compile(rf"^#[ \t]*{key}:")
    for line in text.splitlines()[:DRIVE_MARKER_LINES]:
        if rx.match(line):
            return line
    return None


def _absorbed(root: Path, entries: list[Entry]) -> frozenset[str]:
    """The fold's typed ABSORBED list at this tree: the module's tuple, else the shell's string."""
    by_path = {e.path: e for e in entries}
    module = by_path.get("quality/djb/rituals/fold.py")
    if module is not None:
        text = _blob(root, module.blob).decode(errors="replace")
        found = re.search(r"^ABSORBED_PATHS = \(([^)]*)\)", text, re.MULTILINE)
        if found:
            return frozenset(re.findall(r'"([^"]+)"', found.group(1)))
    fold = by_path.get("scripts/pm_fold.sh")
    if fold is None:
        return frozenset()
    text = _blob(root, fold.blob).decode(errors="replace")
    found = re.search(r"^FOLD_ABSORBED_PATHS='([^']*)'", text, re.MULTILINE)
    return frozenset(found.group(1).split()) if found else frozenset()


def drive_parts(
    root: Path, tree: str, drive: str, entries: list[Entry] | None = None
) -> dict[str, str]:
    """Every key part of `drive` at `tree` but the machine's, label to full digest (`drive_key`)."""
    entries = listing(root, tree) if entries is None else entries
    by_path = {e.path: e for e in entries}
    if drive not in by_path:
        raise Mismatch(f"the drive {drive} is not in tree {tree}")
    text = _blob(root, by_path[drive].blob).decode(errors="replace")
    marker = _header_line(text, "drives")
    if marker is None:
        raise Mismatch(f"{drive} has no `# drives:` line at {tree}")
    decls = marker.split("drives:", 1)[1].split()
    if {"scripts/check.sh", "scripts/", "scripts"} & set(decls) and "scripts/check.sh" in by_path:
        check = _blob(root, by_path["scripts/check.sh"].blob).decode(errors="replace")
        sourced = sorted({m.group(1) for m in map(_SOURCE_LINE.match, check.splitlines()) if m})
        if not sourced and GATE_RUNNER in by_path:
            runner = _blob(root, by_path[GATE_RUNNER].blob).decode(errors="replace")
            libraries = {m.group(1) for m in map(_LIBRARY_LINE.match, runner.splitlines()) if m}
            sourced = [GATE_PACKAGE, *sorted(libraries)]
        decls += sourced
    preamble = (
        drive.rsplit("/", 1)[0] + "/drive_preamble.sh" if "/" in drive else "drive_preamble.sh"
    )
    if preamble not in by_path:
        preamble = DRIVE_PREAMBLE
    parts = {
        drive: sha256_hex(_blob(root, by_path[drive].blob)),
        preamble: sha256_hex(_blob(root, by_path[preamble].blob)),
        DRIVE_JUDGE_ENTRY.rsplit("/", 1)[0] + "/": judge_digest(root, entries),
    }
    absorbed = _absorbed(root, entries)
    words = sorted({w for d in decls for w in _shell_glob(entries, d)})
    for d in words:
        lines = expand(entries, d)
        if not lines:
            if d in absorbed:
                parts[d] = "absent"
                continue
            raise Mismatch(f"{drive}: the declared path {d} expands to nothing at {tree}")
        parts[d] = sha256_hex(("\n".join(lines) + "\n").encode())
    return parts


def recorded_parts(row: Row) -> dict[str, str]:
    """A drive row's `parts=` as label to recorded digest prefix."""
    out = {}
    for pair in (row.get("parts") or "").split(","):
        label, _, digest = pair.rpartition(":")
        if label:
            out[label] = digest
    return out


# --- the measured tree of a commit ----------------------------------------------------------------

#: The key's sentinel word; the fold's blocks name it as the one they must not be.
GATE_SENTINEL = "derived-tree-paths"
#: The product's R0 drawer (build-contract.md:263): declarable while nothing tracks it.
R0_DRAWER = "docs/product/local/"
TREE_DECL_BEGIN = f">>> {GATE_SENTINEL} >>>"
TREE_DECL_END = f"<<< {GATE_SENTINEL} <<<"


def measured_tree_of(root: Path, rev: str) -> str:
    """The tree a verdict about `rev` is keyed on: `rev`'s tree less the declared derived paths."""
    derived = derived_tree_paths(root)
    if not derived:
        return _git(root, "rev-parse", f"{rev}^{{tree}}")
    with tempfile.TemporaryDirectory(prefix="djb-measured-of.") as scratch:
        env = dict(djb_env.environ(), GIT_INDEX_FILE=str(Path(scratch) / "index"))
        _git(root, "read-tree", rev, env=env)
        return _subtract_and_write(root, env, derived)


def measured_tree(root: Path) -> str:
    """The tree a verdict about the WORKING state is keyed on: `add -A`'s tree less the derived."""
    with tempfile.TemporaryDirectory(prefix="djb-measured.") as scratch:
        env = dict(djb_env.environ(), GIT_INDEX_FILE=str(Path(scratch) / "index"))
        unborn = (
            subprocess.run(
                ["git", "-C", str(root), "rev-parse", "-q", "--verify", "HEAD"],
                capture_output=True,
                check=False,
            ).returncode
            != 0
            and subprocess.run(
                ["git", "-C", str(root), "symbolic-ref", "-q", "HEAD"],
                capture_output=True,
                check=False,
            ).returncode
            == 0
        )
        _git(root, "read-tree", "--empty" if unborn else "HEAD", env=env)
        _git(root, "add", "-u", env=env)
        others = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-o", "--exclude-standard", "-z"],
            capture_output=True,
            env=env,
            check=False,
        )
        if others.returncode != 0:
            raise Mismatch("git ls-files -o --exclude-standard failed")
        # An untracked path unlinked after its listing is skipped by `--remove`, never fatal.
        listed = b"".join(p.rstrip(b"/") + b"\0" for p in others.stdout.split(b"\0") if p)
        added = subprocess.run(
            ["git", "-C", str(root), "update-index", "--add", "--remove", "-z", "--stdin"],
            input=listed,
            capture_output=True,
            env=env,
            check=False,
        )
        if added.returncode != 0:
            raise Mismatch("git update-index --add --remove failed")
        return _subtract_and_write(root, env, derived_tree_paths(root))


def _subtract_and_write(root: Path, env: dict[str, str], derived: list[str]) -> str:
    for p in derived:
        _git(root, "rm", "-r", "-f", "--cached", "-q", "--ignore-unmatch", "--", p, env=env)
    return _git(root, "write-tree", env=env)


def derived_tree_paths(root: Path) -> list[str]:
    """The paths a `derived-tree-paths` block declares in the scanned sources; none on any doubt."""
    return declared_paths(root).paths


def _git_or_empty(root: Path, *argv: str) -> str:
    """`git <argv>`'s stdout stripped, or '' when it exits non-zero."""
    done = subprocess.run(["git", *argv], cwd=root, capture_output=True, text=True, check=False)
    return done.stdout.strip() if done.returncode == 0 else ""


# --- the declaration reader: one parser, two sentinel pairs (the fold's and the key's) -------


@dataclass
class Declared:
    """What a reader made of the sentinel blocks: the paths, its notes, and whether it refused."""

    paths: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    refused: bool = False


def _decl_sources(root: Path, patterns: Sequence[str]) -> list[Path]:
    found: list[Path] = []
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            if path.name.startswith(".") or not path.is_file() or not os.access(path, os.R_OK):
                continue
            found.append(path)
    return found


def _decl_comment(line: str) -> bool:
    return line.lstrip(" \t")[:1] in ("#", "*")


def declared_paths(
    root: Path,
    begin: str = TREE_DECL_BEGIN,
    end: str = TREE_DECL_END,
    sources: Sequence[str] | None = None,
) -> Declared:
    """The paths a sentinel block declares in `sources`; refused, with notes, on any doubt."""
    if sources is None:
        sources = decider_value("GATE_TREE_DECL_SOURCES").split()
    answer = Declared()
    named: list[str] = []
    scanned = _decl_sources(root, sources)
    for path in scanned:
        on = False
        who = str(path)
        for number, line in enumerate(path.read_text(errors="replace").splitlines(), start=1):
            if _decl_comment(line) and begin in line:
                on = True
                continue
            if _decl_comment(line) and end in line:
                on = False
                continue
            if not on:
                continue
            body = re.sub(r"^[ \t]*[#*][ \t]*", "", line).strip(" \t")
            if not body:
                continue
            name = re.split(r"[ \t]", body, maxsplit=1)[0]
            rest = body[len(name) :].lstrip(" \t")
            if not rest.startswith("—"):
                answer.notes.append(
                    f"  note: a {GATE_SENTINEL} declaration could not be read — "
                    f"{who}:{number} is inside the block and is not `<path> — <reason>`"
                )
                answer.refused = True
                continue
            named.append(name)
        if on:
            answer.notes.append(
                f"  note: a {GATE_SENTINEL} declaration could not be read — "
                f"{who} opened a declaration and never closed it"
            )
            answer.refused = True
    for name in named:
        shaped = (
            name
            and not name.startswith("/")
            and ".." not in name
            and re.match(r"^[A-Za-z0-9_]", name)
            and re.fullmatch(r"[A-Za-z0-9._/-]+", name)
        )
        if not shaped:
            answer.notes.append(
                f"  note: a {GATE_SENTINEL} declaration names '{name}', "
                "which is not one repository-relative subtree"
            )
            answer.refused = True
            continue
        if _git_or_empty(root, "ls-files", "--", name) or f"{name}/".startswith(R0_DRAWER):
            answer.paths.append(name)
            continue
        answer.notes.append(
            f"  note: a {GATE_SENTINEL} declaration names '{name}', which nothing tracks"
        )
        answer.refused = True
    inside = {p.relative_to(root).as_posix() for p in scanned}
    for stray in _git_or_empty(root, "grep", "-I", "-l", "-F", "-e", begin).splitlines():
        if not stray or stray in inside:
            continue
        try:
            text = (root / stray).read_text(errors="replace")
        except OSError:
            continue
        if any(_decl_comment(line) and begin in line for line in text.splitlines()):
            answer.notes.append(
                f"  note: declaration at {stray} is not in a source the reader scans — "
                "nothing excluded"
            )
    if answer.refused:
        answer.notes.append(
            "  note: so NOTHING is excluded — the verdict key measures the WHOLE tree, which"
        )
        answer.notes.append(
            "        costs a re-measure and is never a hit on an exclusion nobody could verify."
        )
        answer.paths = []
        return answer
    answer.paths = sorted(set(answer.paths))
    return answer


# --- the writer's surface: the full row, the consult, the intent, the run log ---------------------

#: The callers that bank nothing: a `full` row from one is refused (G3b.4's belt and braces).
NO_BANK_CALLERS = ("pr", "leg", "shard", "store-durations")
#: The closed caller vocabulary a row's `caller=` holds (`GATE_CALLER_KINDS`).
CALLER_KINDS = ("push-wall", "quality-rung", "pm-bank", "main-loop", "unstated")
#: The one unit a single pass is sanctioned for (`GATE_ONEPASS_UNIT`).
ONEPASS_UNIT = "pytest-x2"
#: The default legacy tolerance's last day (`GATE_LEDGER_LEGACY_UNTIL`).
LEGACY_UNTIL = "2026-11-15"
_PROOF_GREEN = re.compile(r"^(acceptance:[A-Za-z0-9-]+|ci:[1-9][0-9]*) rc=0$")
_PROOF_NIGHTLY = re.compile(
    r"^(nightly:[0-9]{8}T[0-9]{6}Z tree=[0-9a-f]{12} rc=(0|[1-9][0-9]*)"
    r"|nightly:stale:[0-9]{8}T[0-9]{6}Z|nightly:none)$"
)
_PROOF_ANY = re.compile(
    r"^((acceptance:[A-Za-z0-9-]+|ci:[1-9][0-9]*) (rc=0|rc=[1-9][0-9]*)"
    r"|nightly:[0-9]{8}T[0-9]{6}Z tree=[0-9a-f]{12} (rc=0|rc=[1-9][0-9]*)"
    r"|nightly:stale:[0-9]{8}T[0-9]{6}Z|nightly:none)$"
)


class Unreadable(CouldNotLook):
    """The ledger could not be read: a consult that cannot look answers nothing (exit 2)."""


def _stderr(line: str) -> None:
    print(line, file=sys.stderr)


def caller_kind(value: str | None, say: Callable[[str], None] = _stderr) -> str:
    """The caller kind `value` names, one of `CALLER_KINDS`; unknown is `unstated`, said."""
    if not value:
        return "unstated"
    if value in CALLER_KINDS:
        return value
    say(
        f"  note: DJB_GATE_CALLER='{value}' is not one of: {' '.join(CALLER_KINDS)}"
        " — recording 'unstated'"
    )
    return "unstated"


def _full_refusal(tokens: list[str], caller: str | None) -> str | None:
    named = next((v for n, v in map(_field, tokens) if n == "caller"), None)
    for who in (caller, named):
        if who in NO_BANK_CALLERS:
            return f"a full row from caller '{who}' — {' '.join(NO_BANK_CALLERS)} bank nothing"
    if not any(_field(t)[0] == "sanction" for t in tokens):
        return "a full row with no sanction= — a full row carries one, always"
    return None


def record_full(
    root: Path,
    *,
    tree: str,
    legs: str,
    caller: str,
    sanction: Sanction,
    waited: int = 0,
    took: int = 0,
    wall: int | None = None,
    proof: str = "",
    path: Path | None = None,
    stamp: str | None = None,
) -> Row:
    """The one `full` writer (`gate_ledger_record`): legs, caller, sanction, cost, wall, proof."""
    if caller in NO_BANK_CALLERS:
        raise Refused(
            f"a full row from caller '{caller}' — {' '.join(NO_BANK_CALLERS)} bank nothing"
            " — nothing recorded"
        )
    proof = " ".join(proof.split())
    if proof and not _PROOF_ANY.match(proof):
        raise Refused(f"leak-proof={proof} will not parse — nothing recorded")
    fields = [legs or "-", f"caller={caller_kind(caller)}", sanction.check().field()]
    fields += [f"waited={int(waited)}", f"took={int(took)}"]
    if wall is not None:
        fields.append(f"wall={int(wall)}")
    if proof:
        fields += f"leak-proof={proof}".split(" ")
    return append("full", tree, fields, path=path or ledger_path(root), stamp=stamp, caller=caller)


def _lines(path: Path, kind: str) -> list[str]:
    try:
        return [line for _, line in rows(path) if line.split()[:3][::2] == [SCHEMA, kind]]
    except OSError as exc:
        raise Unreadable(f"the ledger {path} could not be read: {exc}") from exc


def _last_line(path: Path, kind: str, key: str) -> str | None:
    found = None
    for line in _lines(path, kind):
        tokens = line.split()
        if tokens[:1] == [SCHEMA] and len(tokens) > 2 and tokens[1] == key:
            found = line
    return found


def full_legs(root: Path) -> list[str]:
    """The legs a `full` row must cover to be honoured here: the template's, then the drawer's."""
    gate = root / "scripts" / "check.sh"
    if not gate.is_file():
        return []
    text = gate.read_text(encoding="utf-8", errors="replace")
    value = next(
        (ln[len("FULL_LEGS=") :] for ln in text.splitlines() if ln.startswith("FULL_LEGS=")), None
    )
    if value is None:
        return registry_members(root)
    if not value.startswith("$("):
        found = [leg for leg in value.split(",") if leg]
    else:
        found = []
        body = re.compile(r"^[ \t]*gate_run_body [a-z0-9-]+ [A-Za-z0-9_]+ [a-z0-9-]+ ")
        for line in text.splitlines():
            if body.match(line):
                words = line.strip().split()
                if words[3] != "-" and words[1] not in found:
                    found.append(words[1])
    from quality.djb import registry

    try:
        drawer = registry.local_legs(registry.drawer(root, 0))
    except registry.RegistryError as exc:
        raise CouldNotLook(f"the product-leg drawer would not read ({exc})") from exc
    return [*found, *(g.name for g in drawer if g.name not in found)]


def registry_members(root: Path) -> list[str]:
    """Every member of the registry's units in listing order; [] where no leg package is."""
    if not (root / GATE_PACKAGE / "legs").is_dir():
        return []
    from quality.djb import registry

    try:
        table = registry.load(root)
    except registry.RegistryError as exc:
        raise CouldNotLook(f"the leg registry would not validate ({exc})") from exc
    return list(dict.fromkeys(m for _, members in table.rows for m in members))


def covers(root: Path, line: str, say: Callable[[str], None] = _stderr) -> bool:
    """Whether a `full` row's legs cover this gate's declared set (`gate_ledger_lookup`'s judge)."""
    required = full_legs(root)
    if not required:
        return True
    rowlegs = line.split()[4] if len(line.split()) > 4 else ""
    proof = line.split(" leak-proof=", 1)[1] if " leak-proof=" in line else ""
    proofgreen = bool(_PROOF_GREEN.match(proof))
    if not proofgreen and _PROOF_NIGHTLY.match(proof):
        proofgreen = True
        if not proof.endswith(" rc=0"):
            say(f"note: leak-proof={proof} is honoured REPORT-ONLY: the row's one-pass suite")
            say("  rests on no green nightly. The deploy to prod refuses without one no")
            say("  older than 24 h; this push does not.")
    proofused = False
    members = [m for m in rowlegs.split(",") if m]
    for leg in required:
        covered = onepass = unsanctioned = False
        for member in members:
            if member == leg:
                covered = True
                break
            if member == f"{leg}/1":
                if leg == ONEPASS_UNIT:
                    onepass = True
                    if proofgreen:
                        covered = proofused = True
                else:
                    unsanctioned = True
                break
            if re.match(rf"^{re.escape(leg)}/([2-9]|[1-9][0-9])", member):
                covered = True
                break
        if covered:
            continue
        say("note: a banked row for this tree names legs that do not cover this gate's")
        if onepass:
            say(
                f"  declared set — missing '{leg}' — the row ran ONE pass and carries no green"
                f" leak proof (leak-proof={proof or 'none'})."
            )
            say("  The second pass is the leak proof; on a sharded bank it runs on the")
            say("  acceptance box and the row names it, and on the CI road the row names")
            say("  the green run (ci:<run id> rc=0). Not honoured — measuring.")
        elif unsanctioned:
            say(
                f"  declared set — missing '{leg}' — the row ran ONE pass of a leg that is not"
                f" '{ONEPASS_UNIT}', and one pass is sanctioned for that unit alone"
                f" (leak-proof={proof or 'none'})."
            )
            say("  The acceptance box's proof is a whole-suite two-pass pytest run; it")
            say("  vouches for pytest and for nothing else. Not honoured — measuring.")
        else:
            say(f"  declared set (missing '{leg}'), so it is not honoured — measuring.")
        return False
    if proof and not proofused:
        say("note: leak-proof ignored: the row ran two passes over every leg this gate")
        say(f"  declares, so nothing in it rested on the proof (leak-proof={proof}).")
    return True


def consult(
    root: Path, tree: str, *, path: Path | None = None, say: Callable[[str], None] = _stderr
) -> Row | None:
    """The last `full` row for `tree` whose legs cover this gate (`gate_has_green`), or None."""
    if not tree:
        return None
    try:
        where = path or ledger_path(root)
    except (Refused, Mismatch) as exc:
        raise Unreadable(str(exc)) from exc
    line = _last_line(where, "full", tree)
    if line is None or not covers(root, line, say):
        return None
    return parse(line)


def row_field(line: str, name: str) -> str:
    """The last `name=` value on a row, or "" (`gate_docs_only_row_field`)."""
    found = ""
    for token in line.split():
        if token.startswith(f"{name}="):
            found = token[len(name) + 1 :]
    return found


def legacy_live(today: str | None = None) -> bool:
    """Whether pre-grammar stores are still read (`gate_ledger_legacy_live`)."""
    until = djb_env.read("DJB_GATE_LEDGER_LEGACY_UNTIL") or LEGACY_UNTIL
    return (today or time.strftime("%Y-%m-%d", time.gmtime())) < until


# --- the loop rows' readers: the merge, the main loop and the verifier's consult ------------------


def loop_rows(path: Path) -> list[str]:
    """Every loop row in the one grammar, the retired store's first while legacy lives."""
    found = []
    retired = path.parent / "djb-loop-verdicts"
    if legacy_live() and retired.is_file():
        for line in retired.read_text(errors="surrogateescape").splitlines():
            words = line.split()
            if len(words) > 2 and words[0] == LOOP_SCHEMA and words[2] == "loop":
                found.append(" ".join([SCHEMA, *words[1:]]))
    for _, line in rows(path):
        words = line.split()
        if len(words) > 2 and words[2] == "loop":
            if words[0] == SCHEMA:
                found.append(line)
            elif words[0] == LOOP_SCHEMA and legacy_live():
                found.append(" ".join([SCHEMA, *words[1:]]))
    return found


def loop_tree_row(root: Path, tree: str, lines: Iterable[str]) -> str:
    """The last loop line naming `tree` or its loop-key tree (`loop_ledger_tree_row`), or ''."""
    if not tree:
        return ""
    try:
        key_tree = loop_key_tree(root, tree)
    except (CouldNotLook, Mismatch):
        print(
            f"  note: the loop key's prose census could not look — matching tree={tree} alone",
            file=sys.stderr,
        )
        key_tree = ""
    found = ""
    for line in lines:
        words = line.split()
        if len(words) < 3 or words[0] != SCHEMA or words[2] != "loop":
            continue
        fields = dict(w.partition("=")[::2] for w in words[4:] if "=" in w)
        recorded, recorded_key = fields.get("tree", ""), fields.get("key-tree", "")
        hit = f"tree={tree}" in words[4:]
        if not hit and key_tree:
            hit = recorded_key == key_tree or (not recorded_key and recorded == key_tree)
        if hit:
            found = line
    return found


def ancestors(root: Path, head: str, depth: int) -> list[str]:
    """The first-parent line below `head`, each commit's second parents after it."""
    done = subprocess.run(
        ["git", "-C", str(root), "rev-list", "--first-parent", "--parents"]
        + [f"--max-count={depth + 1}", head],
        capture_output=True,
        text=True,
        check=False,
    )
    found = []
    for n, line in enumerate(done.stdout.splitlines() if done.returncode == 0 else []):
        words = line.split()
        if n > 0 and words:
            found.append(words[0])
        found.extend(words[2:])
    return found


# --- the intent row and the run log ---------------------------------------------------------------

#: How old a CI intent may be and still vouch, in seconds (`GATE_INTENT_MAX_AGE`).
INTENT_MAX_AGE = 900


def ci_stamp(epoch: int) -> str:
    """`YYYYMMDDTHHMMSSZ` for a UTC epoch (`gate_ci_stamp_of`)."""
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(epoch))


def intent_record(
    root: Path,
    *,
    tree: str,
    commit: str,
    branch: str,
    sanction: str | Sanction,
    now: int | None = None,
    path: Path | None = None,
) -> Row:
    """An intent row for a train branch's CI run; a typed string or a `Sanction` (R10.1)."""
    if not (re.match(r"^[0-9a-f]{40}$", tree) and re.match(r"^[0-9a-f]{40}$", commit)):
        raise Refused("an intent names a 40-hex tree and commit — nothing recorded")
    if not branch.startswith("pm/") or branch == "pm/" or any(c.isspace() for c in branch):
        raise Refused(
            f"an intent vouches for a pm/* branch only, not '{branch}' — nothing recorded"
        )
    field = (
        sanction.check() if isinstance(sanction, Sanction) else Sanction.typed(sanction)
    ).field()
    at = int(time.time()) if now is None else now
    fields = ["run=pending", f"commit={commit}", f"branch={branch}"]
    fields += [f"at={ci_stamp(at)}", f"epoch={at}", field]
    return append("intent", tree, fields, path=path or ledger_path(root))


def intent_lookup(
    root: Path,
    tree: str,
    *,
    now: int | None = None,
    path: Path | None = None,
    say: Callable[[str], None] = _stderr,
) -> Row | None:
    """The fresh pending intent row for `tree` (`gate_ledger_intent_lookup`), or None."""
    line = _last_line(path or ledger_path(root), "intent", tree)
    if line is None or " run=pending " not in line:
        return None
    epoch = row_field(line, "epoch")
    if not epoch.isdigit():
        return None
    age = (int(time.time()) if now is None else now) - int(epoch)
    window = int(djb_env.read("DJB_GATE_INTENT_MAX_AGE") or INTENT_MAX_AGE)
    if age < -CI_SKEW or age > window:
        say(
            f"note: the CI intent row for tree {tree} is {age} s old (the window is {window} s)"
            " — not honoured."
        )
        return None
    return parse(line)


def run_note(
    root: Path,
    tree: str,
    state: str,
    *,
    caller: str,
    wall: int | None = None,
    path: Path | None = None,
) -> Row:
    """One run-log row: how a gate run on `tree` ended (`gate_run_note`)."""
    fields = [f"state={state}", f"caller={caller_kind(caller)}"]
    if wall is not None:
        fields.append(f"wall={int(wall)}")
    return append("run", tree or "unknown-tree", fields, path=path or ledger_path(root))


def run_lookup(root: Path, tree: str, *, path: Path | None = None) -> str | None:
    """How the last run on `tree` ended, the retired `djb-gate-runs` read while legacy lives."""
    where = path or ledger_path(root)
    found = _last_line(where, "run", tree)
    if found is None and legacy_live():
        retired = where.parent / "djb-gate-runs"
        if retired.is_file():
            for line in retired.read_text(encoding="utf-8", errors="replace").splitlines():
                t = line.split()
                if (
                    len(t) >= 4
                    and t[0] == SCHEMA
                    and t[1] == tree
                    and re.match(r"^[0-9]{4}-", t[2])
                ):
                    found = " ".join([SCHEMA, t[1], "run", t[2], f"state={t[3]}", *t[4:]])
    if found is None:
        return None
    return row_field(found, "state") or None


def last_wall(root: Path, *, path: Path | None = None) -> int | None:
    """The last `full` row's `wall=` seconds (`gate_run_announce`'s duration), or None."""
    found = None
    for line in _lines(path or ledger_path(root), "full"):
        for token in line.split()[5:]:
            if re.match(r"^wall=[0-9]+$", token):
                found = int(token[5:])
    return found


# --- the CI record: `gate-verdict/1` --------------------------------------------------------------

CI_SCHEMA = "gate-verdict/1"
CI_ARTIFACT = "gate-verdict"
CI_RECORD = "gate_verdict.txt"
CI_MAX_AGE = 86400
CI_SKEW = 600
CI_NAMES = (
    "schema",
    "at",
    "commit",
    "tree",
    "legs",
    "shards",
    "scope",
    "rc",
    "run",
    "attempt",
    "where",
)
_CI_SHAPES = {
    "commit": (r"^[0-9a-f]{40}$", "is not 40 hex"),
    "tree": (r"^[0-9a-f]{40}$", "is not 40 hex"),
    "legs": (
        r"^[A-Za-z0-9:_.-]+(/1)?(,[A-Za-z0-9:_.-]+(/1)?)*$",
        "is not a comma list of units, each optionally '/1'",
    ),
    "shards": (r"^(0|[1-9][0-9]*)$", "is not a decimal"),
    "scope": (r"^(whole|pr)$", "is neither whole nor pr"),
    "rc": (r"^(0|[1-9][0-9]*)$", "is not a decimal with no leading zero"),
    "run": (r"^[1-9][0-9]*$", "is not a run id"),
    "attempt": (r"^[1-9][0-9]*$", "is not an attempt number"),
}
#: The optional twelfth field: the lane the run measured (`scope.CI_LANES`); absent is pre-lane.
CI_LANE = "lane"
_CI_LANE_SHAPE = re.compile(r"^(docs|loop|full)$")
#: Field 13, after the lane: did the selftest unit run; withheld vouches by induction (gate-1).
CI_SELFTEST = "selftest"
_CI_SELFTEST_SHAPE = re.compile(r"^(ran|narrowed|withheld)$")
#: Field 14, after the selftest word: pytest-x2 ran whole or narrowed to its `--pr` scope.
CI_PYTEST = "pytest"
_CI_PYTEST_SHAPE = re.compile(r"^(whole|narrowed)$")


class CiRecord(NamedTuple):
    """One parsed `gate-verdict/1` line."""

    at: str
    epoch: int
    commit: str
    tree: str
    legs: str
    shards: str
    scope: str
    rc: str
    run: str
    attempt: str
    lane: str = ""
    selftest: str = ""
    pytest: str = ""


def ci_epoch(stamp: str) -> int | None:
    """The UTC epoch of a `YYYYMMDDTHHMMSSZ` stamp that round-trips, or None (`gate_ci_epoch`)."""
    import calendar

    if not re.match(r"^[0-9]{8}T[0-9]{6}Z$", stamp):
        return None
    try:
        epoch = calendar.timegm(time.strptime(stamp, "%Y%m%dT%H%M%SZ"))
    except ValueError:
        return None
    return epoch if ci_stamp(epoch) == stamp else None


def ci_parse(line: str) -> CiRecord:
    """The record `line` is; `Refused` naming why it is not one (`gate_ci_record_parse`)."""
    if not line or re.search(r"[\t\n\r]", line) or line != line.strip(" ") or "  " in line:
        raise Refused("the line is empty or is not eleven fields one space apart")
    toks = line.split(" ")
    lane = selftest = pytest = ""
    if len(toks) == len(CI_NAMES) + 3:
        last = toks.pop()
        if not last.startswith(f"{CI_PYTEST}="):
            raise Refused(f"field 14 is '{last}' where the grammar has '{CI_PYTEST}=' or nothing")
        pytest = last[len(CI_PYTEST) + 1 :]
        if not _CI_PYTEST_SHAPE.match(pytest):
            raise Refused(f"{CI_PYTEST}='{pytest}' is neither whole nor narrowed")
    if len(toks) == len(CI_NAMES) + 2:
        last = toks.pop()
        if not last.startswith(f"{CI_SELFTEST}="):
            raise Refused(f"field 13 is '{last}' where the grammar has '{CI_SELFTEST}=' or nothing")
        selftest = last[len(CI_SELFTEST) + 1 :]
        if not _CI_SELFTEST_SHAPE.match(selftest):
            raise Refused(f"{CI_SELFTEST}='{selftest}' is none of ran, narrowed, withheld")
    if len(toks) == len(CI_NAMES) + 1:
        last = toks.pop()
        if not last.startswith(f"{CI_LANE}="):
            raise Refused(f"field 12 is '{last}' where the grammar has '{CI_LANE}=' or nothing")
        lane = last[len(CI_LANE) + 1 :]
        if not _CI_LANE_SHAPE.match(lane):
            raise Refused(f"{CI_LANE}='{lane}' is none of docs, loop, full")
    if len(toks) != len(CI_NAMES):
        raise Refused(f"{len(toks)} fields where the grammar has 11 ({' '.join(CI_NAMES)})")
    got: dict[str, str] = {}
    for i, (name, tok) in enumerate(zip(CI_NAMES, toks), 1):  # noqa: B905 — the floor is 3.9
        if not tok.startswith(f"{name}="):
            raise Refused(f"field {i} is '{tok}' where the grammar has '{name}='")
        got[name] = tok[len(name) + 1 :]
    if got["schema"] != CI_SCHEMA:
        raise Refused(f"schema='{got['schema']}', not {CI_SCHEMA}")
    epoch = ci_epoch(got["at"])
    if epoch is None:
        raise Refused(f"at='{got['at']}' is not a UTC YYYYMMDDTHHMMSSZ stamp")
    for name, (shape, why) in _CI_SHAPES.items():
        if not re.match(shape, got[name]):
            raise Refused(f"{name}='{got[name]}' {why}")
    if got["where"] != "ci":
        raise Refused(f"where='{got['where']}', not ci")
    return CiRecord(
        at=got["at"],
        epoch=epoch,
        commit=got["commit"],
        tree=got["tree"],
        legs=got["legs"],
        shards=got["shards"],
        scope=got["scope"],
        rc=got["rc"],
        run=got["run"],
        attempt=got["attempt"],
        lane=lane,
        selftest=selftest,
        pytest=pytest,
    )


def ci_record(
    commit: str,
    tree: str,
    legs: str,
    shards: str,
    scope: str,
    rc: str,
    run: str,
    attempt: str,
    at: str | None = None,
    lane: str | None = None,
    selftest: str | None = None,
    pytest: str | None = None,
) -> str:
    """The one `gate-verdict/1` line a CI run writes; `Refused` when it would not parse."""
    stamp = at or ci_stamp(int(time.time()))
    line = (
        f"schema={CI_SCHEMA} at={stamp} commit={commit} tree={tree} legs={legs} shards={shards}"
        f" scope={scope} rc={rc} run={run} attempt={attempt} where=ci"
    )
    if lane is not None:
        line += f" {CI_LANE}={lane}"
    if selftest is not None:
        line += f" {CI_SELFTEST}={selftest}"
    if pytest is not None:
        line += f" {CI_PYTEST}={pytest}"
    try:
        ci_parse(line)
    except Refused as exc:
        raise Refused(f"the CI record would not parse, so NONE was written: {exc}") from exc
    return line


def ci_legs_expand(legs: str, listing: str) -> str:
    """A record's units expanded to members through `--list-legs`; `Refused` naming the unit."""
    table = {}
    for row in listing.splitlines():
        cols = row.split("\t")
        if len(cols) >= 4:
            table[cols[0]] = cols[3]
    out: list[str] = []
    for item in [i for i in legs.split(",") if i]:
        unit = item[:-2] if item.endswith("/1") else item
        one = unit != item
        members = table.get(unit, "")
        if not members:
            raise Refused(
                f"the record names unit '{unit}', which this checkout's listing does not declare"
            )
        if one and ONEPASS_UNIT not in members.split(","):
            raise Refused(
                f"the record ran unit '{unit}' at one pass, and one pass is sanctioned for"
                f" {ONEPASS_UNIT} alone"
            )
        for m in [m for m in members.split(",") if m]:
            if one and m == ONEPASS_UNIT:
                m = f"{ONEPASS_UNIT}/1"
            if m not in out:
                out.append(m)
    return ",".join(out)


def ci_judge(
    root: Path, line: str, run: str, attempt: str, listing: str, *, now: int | None = None
) -> str:
    """The legs a record vouches for here; `Refused` says why not (`gate_ci_record_judge`)."""
    try:
        rec = ci_parse(line)
    except Refused as exc:
        raise Refused(
            f"run {run}'s record will not parse ({exc}) — an unreadable record banked would be"
            f" a guess: {line or '<empty>'}"
        ) from exc
    if rec.run != run:
        raise Refused(
            f"run {run}'s record names run={rec.run} — a record for another run is not this"
            " run's verdict"
        )
    if rec.attempt != attempt:
        raise Refused(
            f"run {run}'s latest attempt is {attempt} and its record says attempt={rec.attempt}"
            " — a record from another attempt is not the latest verdict"
        )
    if rec.lane and rec.lane != "full":
        raise Refused(
            f"run {run} ran the {rec.lane} lane — only the full lane vouches for a tree, and a"
            f" {rec.lane} record is never offered as a full verdict"
        )
    if rec.scope != "whole":
        raise Refused(
            f"run {run} ran NARROWED (scope={rec.scope}) — a narrowed run vouches for no tree"
        )
    if rec.rc != "0":
        raise Refused(
            f"run {run} attempt {attempt} is RED (rc={rec.rc}) — a red run is not a verdict"
        )
    age = (int(time.time()) if now is None else now) - rec.epoch
    if -age > CI_SKEW:
        raise Refused(
            f"run {run}'s record is stamped IN THE FUTURE — at={rec.at}, {-age} s ahead of this"
            f" clock (the skew allowed is {CI_SKEW} s)"
        )
    if age > CI_MAX_AGE:
        raise Refused(
            f"run {run}'s record is OLDER THAN 24 h — at={rec.at}, {age // 3600} h ago; re-run it"
            " or push again"
        )
    has = subprocess.run(
        ["git", "-C", str(root), "cat-file", "-e", f"{rec.commit}^{{commit}}"],
        capture_output=True,
        check=False,
    )
    if has.returncode != 0:
        raise Refused(
            f"run {run} measured commit {rec.commit[:12]}, which this checkout does not have —"
            " fetch it first"
        )
    try:
        derived = measured_tree_of(root, rec.commit)
    except Mismatch:
        derived = ""
    if derived != rec.tree:
        raise Refused(
            f"run {run} measured tree {rec.tree[:12]}, and commit {rec.commit[:12]}'s measured"
            f" tree is {derived[:12]} — the run measured bytes the commit does not carry (main"
            " moved under the pull request: fold main in and push again)"
        )
    ancestor = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", rec.commit, "HEAD"],
        capture_output=True,
        check=False,
    )
    if ancestor.returncode != 0:
        raise Refused(
            f"run {run} measured {rec.commit[:12]}, which is neither HEAD nor an ancestor of it —"
            " a row for a tree this line of history does not contain would misattribute it"
        )
    expanded = ci_legs_expand(rec.legs, listing)
    if rec.selftest == "withheld":
        expanded = ci_legs_expand(",".join(filter(None, (rec.legs, "selftest"))), listing)
    have = expanded.split(",")
    for leg in full_legs(root):
        if leg in have or (f"{leg}/1" in have and leg == ONEPASS_UNIT):
            continue
        raise Refused(
            f"run {run}'s units do not cover this gate's full leg set — missing '{leg}'"
            f" (units: {rec.legs})"
        )
    return expanded


def _gh(root: Path, sink: Path, name: str, *argv: str, gh: str = "gh") -> tuple[int, str]:
    """`(rc, stdout)` of one `gh` call, its answer and errors kept as `<sink>/<name>.out|.err`."""
    err = sink / f"{name}.err"
    try:
        with err.open("w") as errors:
            done = subprocess.run(
                [gh, *argv],
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=errors,
                stdin=subprocess.DEVNULL,
                text=True,
                check=False,
            )
    except OSError:
        return 127, ""
    (sink / f"{name}.out").write_text(done.stdout)
    return done.returncode, done.stdout


#: The job that writes a CI run's record; the run may still be running later jobs when it is done.
CI_RECORD_JOB = "gate-verdict"


def ci_fetch(root: Path, run: str, sink: Path) -> tuple[int, str]:
    """`(0, attempt)` with the record downloaded; `(1|2, why)` (`gate_ci_fetch`)."""
    if shutil.which("gh") is None:
        return 2, "no `gh` on PATH — the record is a workflow artifact and `gh` is its one reader"
    sink.mkdir(parents=True, exist_ok=True)
    rc, view = _gh(
        root,
        sink,
        f"gh-run-view-{run}",
        "run",
        "view",
        run,
        "--json",
        "status,attempt,jobs",
        "--jq",
        f'"\\(.status) \\(.attempt) \\([.jobs[] | select(.name == "{CI_RECORD_JOB}")'
        ' | .status][0] // "")"',
    )
    if rc != 0:
        return (
            2,
            f"`gh run view {run}` did not answer ({sink}/gh-run-view-{run}.err) — no such run,"
            " or gh is failing",
        )
    view = view.strip()
    st, attempt, job = [*view.split(), "", "", ""][:3]
    if not re.match(r"^[1-9][0-9]*$", attempt) or not st:
        return 2, f"`gh run view {run}` answered '{view}', which names no status and attempt"
    if st != "completed" and job != "completed":
        return (
            1,
            f"run {run} has not completed its {CI_RECORD_JOB} job (run status '{st}', attempt"
            f" {attempt}) — that job writes the record",
        )
    name = ci_artifact_name(attempt)
    shutil.rmtree(sink / f"record-{run}", ignore_errors=True)
    log = sink / f"gh-run-download-{run}.log"
    with log.open("w") as out:
        done = subprocess.run(
            ["gh", "run", "download", run, "--name", name, "--dir", str(sink / f"record-{run}")],
            cwd=root,
            stdout=out,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    if done.returncode != 0:
        said = log.read_text(errors="replace")
        if "no valid artifacts found" in said or "no artifact matches" in said:
            return 1, (
                f"run {run} attempt {attempt} (the latest) carries no {name} artifact — a run that"
                " published no record measured nothing this reader can see"
            )
        return 2, (
            f"`gh run download {run} --name {name}` failed for a reason that is not a missing"
            f" artifact ({log})"
        )
    rec = sink / f"record-{run}" / CI_RECORD
    if not rec.is_file() or rec.stat().st_size == 0:
        return 1, f"run {run}'s {name} artifact is present and holds no {CI_RECORD}"
    return 0, attempt


def ci_artifact_name(attempt: str) -> str:
    """The artifact one attempt of a CI run publishes: its name carries the attempt."""
    return f"{CI_ARTIFACT}-{attempt}"


# --- the nightly leak proof: the one writer and the one reader ----------------------------------

NIGHTLY_SCHEMA = "leak-proof/1"
NIGHTLY_RECORD = "leak_proof.txt"
NIGHTLY_FIELDS = (
    "at", "commit", "tree", "seed", "pass1", "pass2", "map", "rc", "run", "attempt", "where"
)  # fmt: skip
_NIGHTLY_NAMES = ("schema", *NIGHTLY_FIELDS)


class NightlyUnreadable(CouldNotLook):
    """A nightly record that was handed in and cannot be read; the message is the whole sentence."""


def nightly_line(fields: Sequence[str]) -> str:
    """The `leak-proof/1` record of eleven fields, or `Refused` with the notes the shell printed."""
    if len(fields) != len(NIGHTLY_FIELDS):
        raise Refused(f"note: gate_nightly_line takes 11 fields; got {len(fields)}.")
    at, commit, tree, seed, p1, p2, map_, rc, run, attempt, where = fields
    status, decimal = r"(0|[1-9][0-9]*|-)", r"(0|[1-9][0-9]*)"
    if (
        ci_epoch(at) is None
        or not re.fullmatch(r"[0-9a-f]{40}", commit)
        or not re.fullmatch(r"[0-9a-f]{40}", tree)
        or not re.fullmatch(r"[0-9]+", seed)
        or not all(re.fullmatch(status, v) for v in (p1, p2, map_))
        or not re.fullmatch(r"[012]", rc)
        or not re.fullmatch(decimal, run)
        or not re.fullmatch(decimal, attempt)
        or where not in ("nightly", "acceptance")
    ):
        said = " ".join(f"{n}={v}" for n, v in zip(NIGHTLY_FIELDS, fields, strict=True))
        raise Refused(
            f"note: the leak-proof record would not parse, so NONE was written:\n  {said}"
        )
    if where == "nightly" and "0" in (run, attempt):
        raise Refused(
            "note: a where=nightly record names the workflow run that wrote it;"
            f" run={run} attempt={attempt} name none."
        )
    return f"schema={NIGHTLY_SCHEMA} " + " ".join(
        f"{n}={v}" for n, v in zip(NIGHTLY_FIELDS, fields, strict=True)
    )


def nightly_read(directory: str, now: int | None = None) -> str:
    """The bank row's form of a nightly record: `nightly:<at> tree= rc=`, `:stale:<at>`, `:none`."""
    if not directory:
        return "nightly:none"
    where = Path(directory)
    if not where.is_dir():
        raise NightlyUnreadable(f"nightly: unreadable — {directory} is not a directory")
    record = where / NIGHTLY_RECORD
    if not record.is_file() or record.stat().st_size == 0:
        raise NightlyUnreadable(
            f"nightly: unreadable — {directory} holds no {NIGHTLY_RECORD} (or an empty one)"
        )
    text = record.read_text(encoding="utf-8", errors="surrogateescape")
    line = next((ln for ln in text.splitlines() if ln.split()), "")
    found: dict[str, str] = {}
    for token in line.split():
        if "=" not in token:
            raise NightlyUnreadable(f"nightly: unreadable — '{token}' is not name=value: {line}")
        name, value = token.split("=", 1)
        if name not in _NIGHTLY_NAMES:
            raise NightlyUnreadable(
                f"nightly: unreadable — '{name}=' is not a field of leak-proof/1: {line}"
            )
        if found.get(name):
            raise NightlyUnreadable(f"nightly: unreadable — '{name}=' appears twice: {line}")
        found[name] = value
    got = {n: found.get(n, "") for n in _NIGHTLY_NAMES}
    epoch = ci_epoch(got["at"])
    if (
        got["schema"] != NIGHTLY_SCHEMA
        or got["where"] != "nightly"
        or not re.fullmatch(r"[0-9a-f]{40}", got["commit"])
        or not re.fullmatch(r"[0-9a-f]{40}", got["tree"])
        or not re.fullmatch(r"0|[1-9][0-9]*", got["rc"])
        or not re.fullmatch(r"[1-9][0-9]*", got["run"])
        or not re.fullmatch(r"[1-9][0-9]*", got["attempt"])
        or not all(got[n] for n in ("seed", "pass1", "pass2", "map"))
        or epoch is None
    ):
        raise NightlyUnreadable(
            "nightly: unreadable — the record is not leak-proof/1 (schema, stamp, hex, rc, run,"
            f" attempt, where or a missing field): {line}"
        )
    age = (int(time.time()) if now is None else now) - epoch
    if -age > CI_SKEW:
        raise NightlyUnreadable(
            f"nightly: unreadable — at={got['at']} is {-age} s in the future of this clock"
        )
    if age > CI_MAX_AGE:
        return f"nightly:stale:{got['at']}"
    return f"nightly:{got['at']} tree={got['tree'][:12]} rc={got['rc']}"


PROOF_SCHEMA = "proof-from-zero/3"
#: The schema before the export: its `tree=` is the SOURCE's tree, so no reader honours it.
PROOF_SCHEMA_SOURCE = "proof-from-zero/2"
PROOF_RECORD = "proof_from_zero.txt"
PROOF_SDK = r"[0-9][0-9A-Za-z.+-]*"
PROOF_FIELDS = (
    "at", "source", "tree", "features", "lane", "tax", "touched", "loop_s", "refused",
    "sanctioned", "sdk", "rule96", "valves", "scaffold", "drive", "reference", "rc", "run", "where",
)  # fmt: skip


def proof_line(fields: Sequence[str]) -> str:
    """The `proof-from-zero/3` record of nineteen fields, or `Refused` naming what failed."""
    if len(fields) != len(PROOF_FIELDS):
        raise Refused(
            f"note: the proof record takes {len(PROOF_FIELDS)} fields; got {len(fields)}."
        )
    at, source, tree, features, lane, tax, touched, loop_s, refused, sanctioned = fields[:10]
    sdk, rule96, valves, scaffold, drive, reference, rc, run, where = fields[10:]
    count = int(features) if re.fullmatch(r"[1-9]", features) else 0
    each = (
        (lane, r"docs|loop|full|-"),
        (tax, r"[0-9]+(\.[0-9]+)?(\+\?)?|\?|-"),
        (touched, r"[0-9]+|-"),
        (loop_s, r"[0-9]+|-"),
        (drive, r"agree|disagree|unlooked|-"),
    )
    if (
        ci_epoch(at) is None
        or not re.fullmatch(r"[0-9a-f]{40}", source)
        or not re.fullmatch(r"[0-9a-f]{40}", tree)
        or not count
        or any(
            len(value.split(",")) != count
            or not all(re.fullmatch(shape, v) for v in value.split(","))
            for value, shape in each
        )
        or not re.fullmatch(r"[0-3]", refused)
        or not re.fullmatch(r"[01]", sanctioned)
        or not re.fullmatch(rf"{PROOF_SDK}|-", sdk)
        or rule96 not in ("green", "red", "-")
        or not re.fullmatch(r"[0-9]+|-", valves)
        or not re.fullmatch(r"[0-9]+", scaffold)
        or int(scaffold) > count
        or not re.fullmatch(r"[0-9]+|-", reference)
        or not re.fullmatch(r"[012]", rc)
        or not re.fullmatch(r"0|[1-9][0-9]*", run)
        or where not in ("ci", "local")
    ):
        said = " ".join(f"{n}={v}" for n, v in zip(PROOF_FIELDS, fields, strict=True))
        raise Refused(f"note: the proof record would not parse, so NONE was written:\n  {said}")
    return f"schema={PROOF_SCHEMA} " + " ".join(
        f"{n}={v}" for n, v in zip(PROOF_FIELDS, fields, strict=True)
    )


NIGHTLY_WORKFLOW = "nightly-proof.yml"
NIGHTLY_ARTIFACT = "nightly-leak-proof"
NIGHTLY_BRANCH = "main"
NIGHTLY_TEETH = (
    "report-only: this bank is honoured; the deploy to prod refuses without a green nightly ≤ 24 h"
)


def nightly_fetch(sink: Path, gh: str = "gh") -> tuple[int, str]:
    """`(0, "<run> <attempt> <dir>")`: the LATEST completed nightly downloaded; `(1|2, why)`."""
    # The latest, never the latest green: a red night is the thing to say.
    if shutil.which(gh) is None:
        return 2, (
            f"no `{gh}` on PATH — the nightly's record is a workflow artifact and `gh` is its"
            " one reader"
        )
    try:
        sink.mkdir(parents=True, exist_ok=True)
    except OSError:
        return 2, f"could not make {sink} to download the record into"
    here = Path.cwd()
    rc, run = _gh(
        here, sink, "gh-nightly-list", "run", "list", "--workflow", NIGHTLY_WORKFLOW,
        "--branch", NIGHTLY_BRANCH, "--status", "completed", "--limit", "1",
        "--json", "databaseId", "--jq", ".[0].databaseId // empty", gh=gh,
    )  # fmt: skip
    run = run.rstrip("\n")
    if rc != 0:
        return 2, (
            f"`gh run list --workflow {NIGHTLY_WORKFLOW}` did not answer"
            f" ({sink}/gh-nightly-list.err)"
        )
    if not run:
        return 1, f"no completed {NIGHTLY_WORKFLOW} run on {NIGHTLY_BRANCH}"
    if not re.fullmatch(r"[1-9][0-9]*", run):
        return 2, f"`gh run list` answered '{run}', which is not a run id"
    rc, view = _gh(
        here, sink, "gh-nightly-view", "run", "view", run, "--json", "status,attempt",
        "--jq", '"\\(.status) \\(.attempt)"', gh=gh,
    )  # fmt: skip
    if rc != 0:
        return 2, f"`gh run view {run}` did not answer ({sink}/gh-nightly-view.err)"
    view = view.rstrip("\n")
    st, attempt = view.split(" ", 1)[0], view.rsplit(" ", 1)[-1]
    if not re.fullmatch(r"[1-9][0-9]*", attempt) or st != "completed":
        return 2, f"`gh run view {run}` answered '{view}', not a completed run and its attempt"
    where = sink / f"nightly-{run}"
    shutil.rmtree(where, ignore_errors=True)
    log = sink / "gh-nightly-download.log"
    try:
        with log.open("w") as out:
            done = subprocess.run(
                [gh, "run", "download", run, "--name", NIGHTLY_ARTIFACT, "--dir", str(where)],
                stdout=out,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                check=False,
            )
        failed = done.returncode != 0
    except OSError:
        failed = True
    if failed:
        said = log.read_text(errors="replace") if log.is_file() else ""
        if "no valid artifacts found" in said or "no artifact matches" in said:
            return (
                1,
                f"nightly run {run} (attempt {attempt}) carries no {NIGHTLY_ARTIFACT} artifact",
            )
        return 2, (
            f"`gh run download {run} --name {NIGHTLY_ARTIFACT}` failed for a reason that is not a"
            f" missing artifact ({log})"
        )
    # The latest attempt's record or none: the artifact name carries no attempt.
    record = where / NIGHTLY_RECORD
    if record.is_file() and record.stat().st_size > 0:
        text = record.read_text(encoding="utf-8", errors="surrogateescape")
        line = next((ln for ln in text.splitlines() if ln.split()), "")
        said = next((t[len("attempt=") :] for t in line.split() if t.startswith("attempt=")), "")
        if said != attempt:
            return 1, (
                f"nightly run {run}'s record says attempt={said or '<none>'} and the latest"
                f" attempt is {attempt} — an earlier attempt's record is not the run's"
            )
    return 0, f"{run} {attempt} {where}"


def nightly_source(sink: Path, bank: str = "", gh: str = "gh") -> tuple[str, str]:
    """`(form, line)`: a bank row's `leak-proof=` under `--leak-proof nightly`, and its one line."""
    # Never refuses: the bank honours every form and the teeth are at prod (report-only).
    rc, got = nightly_fetch(sink, gh=gh)
    if rc != 0:
        why = f"could not look: {got}" if rc == 2 else got
        return "nightly:none", (
            f"WARNING: leak-proof: no nightly leak proof ({why}) — nightly:none; {NIGHTLY_TEETH}"
        )
    run, attempt, directory = got.split(" ", 2)
    try:
        form = nightly_read(directory)
    except NightlyUnreadable as cannot:
        return "nightly:none", (
            f"WARNING: leak-proof: no nightly leak proof (run {run}'s record is unreadable:"
            f" {cannot}) — nightly:none; {NIGHTLY_TEETH}"
        )
    if form.startswith("nightly:stale:"):
        return form, (
            f"WARNING: leak-proof: the latest nightly (run {run}, attempt {attempt}) is older"
            f" than 24 h — {form}; {NIGHTLY_TEETH}"
        )
    if form.endswith(" rc=0"):
        night = form.split(" tree=", 1)[1].split(" ", 1)[0]
        note = ""
        if bank and night != bank[:12]:
            note = f" (measured {night}, not this bank's {bank[:12]}: report-only)"
        return form, f"leak-proof: nightly run {run} attempt {attempt} green — {form}{note}"
    return form, (
        f"WARNING: leak-proof: the latest nightly (run {run}, attempt {attempt}) is RED"
        f" ({form.rsplit(' ', 1)[-1]}) — {form}; {NIGHTLY_TEETH}"
    )


def ci_consult(
    root: Path,
    sha: str,
    events: Sequence[str] = ("pull_request",),
    *,
    docs_road: bool = False,
    selftest: bool = False,
    pr: str = "",
) -> tuple[str, str]:
    """`(line, run)`: the consult's one line and the honoured run id, or "" (`gate_ci_consult`)."""
    line, run = _ci_consult(root, sha, events, "", selftest, pr)
    if run or not docs_road or "could not look" in line:
        return line, run
    if pr:
        return (line, "") if NOT_OF_PR in line else _ci_pr_road(root, sha, line, pr, selftest)
    said, run = _ci_docs_road(root, sha, line, DOCS_ROAD_DEPTH, selftest)
    return (said, run) if run else _ci_head_road(root, sha, line, selftest)


def _ci_pr_road(root: Path, head: str, line: str, pr: str, selftest: bool) -> tuple[str, str]:
    """`line`, or pull request `pr`'s head honoured over its own run of a docs-only parent."""
    try:
        mine, carried = measured_tree(root), measured_tree_of(root, head)
    except Mismatch:
        return line, ""
    if mine != carried:
        return (
            f"consult: measure — main moved under pull request #{pr} (this checkout measures"
            f" {mine[:12]}, its head {head[:12]} carries {carried[:12]}) — the merge is measured",
            "",
        )
    return _ci_docs_road(root, head, line, DOCS_ROAD_DEPTH, selftest, pr)


def _ci_head_road(root: Path, sha: str, line: str, selftest: bool) -> tuple[str, str]:
    """`line`, or the pushed tree honoured as a pull request head's own docs-road honour."""
    try:
        mine = measured_tree(root)
    except Mismatch:
        return line, ""
    sink = Path(tempfile.mkdtemp(prefix="djb-ci-consult."))
    rc, heads = _gh(
        root,
        sink,
        "gh-api-pulls",
        "api",
        f"repos/{{owner}}/{{repo}}/commits/{sha}/pulls",
        "--jq",
        ".[].head.sha",
    )
    for h in heads.split() if rc == 0 else []:
        if not re.match(r"^[0-9a-f]{40}$", h) or h == sha:
            continue
        try:
            if measured_tree_of(root, h) != mine:
                continue
        except Mismatch:
            continue
        said, run = _ci_docs_road(root, h, line, DOCS_ROAD_DEPTH, selftest)
        if run:
            return said, run
    return line, ""


PROOF_WORKFLOW = "proof-from-zero.yml"
PROOF_ARTIFACT = "proof-from-zero"


def proof_consult(root: Path, tree: str, gh: str = "gh") -> tuple[str, str]:
    """`(line, run)`: a completed run whose green record names the export tree `tree`, or why."""
    if not re.match(r"^[0-9a-f]{40}$", tree):
        return f"proof-consult: prove — could not look (a 40-hex export tree; got '{tree}')", ""
    return _proof_scan(root, gh, f"tree {tree[:12]}", lambda fields: fields["tree"] == tree)


def proof_consult_source(root: Path, sha: str, gh: str = "gh") -> tuple[str, str]:
    """`(line, run)`: a green record whose `source=` has `sha`'s tree here — before any export."""
    if not re.match(r"^[0-9a-f]{40}$", sha):
        return f"proof-consult: prove — could not look (a 40-hex sha; got '{sha}')", ""
    try:
        tree = _git(root, "rev-parse", f"{sha}^{{tree}}")
    except Mismatch:
        return f"proof-consult: prove — could not look ({sha[:12]} has no tree here)", ""

    def same_source(fields: dict[str, str]) -> bool:
        try:
            return _git(root, "rev-parse", f"{fields['source']}^{{tree}}") == tree
        except Mismatch:
            return False

    return _proof_scan(root, gh, f"source tree {tree[:12]}", same_source)


def _proof_scan(
    root: Path, gh: str, key: str, honoured: Callable[[dict[str, str]], bool]
) -> tuple[str, str]:
    """The completed proof runs' records, newest first: the first green one `honoured` keeps."""
    if shutil.which(gh) is None:
        return "proof-consult: prove — could not look (no `gh` on PATH)", ""
    sink = Path(tempfile.mkdtemp(prefix="djb-proof-consult."))
    rc, runs = _gh(
        root,
        sink,
        "gh-proof-runs",
        "api",
        f"repos/{{owner}}/{{repo}}/actions/workflows/{PROOF_WORKFLOW}/runs?status=completed"
        "&per_page=30",
        "--jq",
        ".workflow_runs[].id",
        gh=gh,
    )
    if rc != 0:
        return f"proof-consult: prove — could not look (`gh api` did not answer: {sink})", ""
    sourced = 0
    for run in [r for r in runs.split() if re.match(r"^[1-9][0-9]*$", r)]:
        got = sink / f"proof-{run}"
        done = subprocess.run(
            [gh, "run", "download", run, "--name", PROOF_ARTIFACT, "--dir", str(got)],
            cwd=root,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            check=False,
        )
        record = got / PROOF_RECORD
        if done.returncode != 0 or not record.is_file():
            continue
        line = next((ln for ln in record.read_text(errors="replace").splitlines() if ln), "")
        fields = dict(tok.split("=", 1) for tok in line.split(" ") if "=" in tok)
        sourced += fields.get("schema") == PROOF_SCHEMA_SOURCE
        try:
            proof_line([fields[name] for name in PROOF_FIELDS])
        except (KeyError, Refused):
            continue
        if fields.get("schema") == PROOF_SCHEMA and fields["rc"] == "0" and honoured(fields):
            return f"proof-consult: honoured run={run} tree={fields['tree']}", run
    older = f"; {sourced} {PROOF_SCHEMA_SOURCE} record(s) key a source tree, never an export"
    return (
        f"proof-consult: prove — no completed run of {PROOF_WORKFLOW} published a green"
        f" {PROOF_SCHEMA} record of {key}{older if sourced else ''} ({sink})",
        "",
    )


#: The PR consult's refusal of a head outside its pull request: no road walks past it.
NOT_OF_PR = "is not a commit of pull request"
#: A run's id and the pull requests it ran for: the PR consult honours its own runs alone.
_RUNS_OF_PR = '.workflow_runs[] | "\\(.id) \\([.pull_requests[].number | tostring] | join(","))"'


def _of(pr: str, numbers: list[str]) -> bool:
    """Whether a run's `<n>,<n>` pull request list names `pr`."""
    return pr in ",".join(numbers).split(",")


#: How many docs-only merges in a row the push consult follows back to a measured one.
DOCS_ROAD_DEPTH = 8


def _ci_docs_road(
    root: Path, sha: str, line: str, depth: int, selftest: bool = False, pr: str = ""
) -> tuple[str, str]:
    """`line`, or this tree honoured over its first parent's record and a docs-only delta."""
    try:
        parent = _git(root, "rev-parse", f"{sha}^1")
        changed = _git(root, "diff", "--name-only", parent, sha).split()
        ptree, mytree = measured_tree_of(root, parent), measured_tree_of(root, sha)
    except Mismatch:
        return line, ""
    if not changed or not all(docs_only_admits(p, parent, sha, root=root) for p in changed):
        return line, ""
    events = ("pull_request",) if pr else ("pull_request", "push")
    pline, prun = _ci_consult(root, parent, events, ptree, selftest, pr)
    if not prun and depth > 1 and "could not look" not in pline:
        pline, prun = _ci_docs_road(root, parent, pline, depth - 1, selftest, pr)
    if not prun:
        return line, ""
    attempt = pline.split(" attempt=", 1)[1].split(" ", 1)[0]
    since = pline.split(" docs-only-since=", 1)[1].split(" ", 1)[0] if "since=" in pline else ptree
    said = f"run={prun} attempt={attempt} docs-only-since={since} tree={mytree}"
    return f"consult: honoured {said}", prun


def _ci_consult(
    root: Path,
    sha: str,
    events: Sequence[str],
    tree: str,
    selftest: bool = False,
    pr: str = "",
) -> tuple[str, str]:
    """`ci_consult` over one commit against `tree` (else this checkout's); `pr`: its runs only."""
    if not re.match(r"^[0-9a-f]{40}$", sha):
        return (
            f"consult: measure — could not look (the consult takes a 40-hex sha; got '{sha}')",
            "",
        )
    if pr and not re.match(r"^[1-9][0-9]*$", pr):
        return (
            f"consult: measure — could not look (a pull request is a number; got '{pr}')",
            "",
        )
    if shutil.which("gh") is None:
        return "consult: measure — could not look (no `gh` on PATH)", ""
    sink = Path(tempfile.mkdtemp(prefix="djb-ci-consult."))
    try:
        mytree = tree or measured_tree(root)
    except Mismatch:
        return (
            "consult: measure — could not look (this checkout's measured tree would not read)",
            "",
        )
    if pr:
        rc, heads = _gh(
            root,
            sink,
            "gh-api-pr-commits",
            "api",
            f"repos/{{owner}}/{{repo}}/pulls/{pr}/commits?per_page=100",
            "--paginate",
            "--jq",
            ".[].sha",
        )
        if rc == 0 and sha not in heads.split():
            return (
                f"consult: measure — {sha[:12]} {NOT_OF_PR} #{pr} — only"
                " this pull request's own runs are honoured",
                "",
            )
        heads = ""
    else:
        rc, heads = _gh(
            root,
            sink,
            "gh-api-pulls",
            "api",
            f"repos/{{owner}}/{{repo}}/commits/{sha}/pulls",
            "--jq",
            ".[].head.sha",
        )
    if rc != 0:
        return (
            f"consult: measure — could not look (`gh api` for the pull requests of {sha[:12]} did"
            f" not answer: {sink}/gh-api-{'pr-commits' if pr else 'pulls'}.err)",
            "",
        )
    workflow = djb_env.read("DJB_CI_WORKFLOW") or "ci.yml"
    found: list[int] = []
    for h in [sha, *heads.split()]:
        if not re.match(r"^[0-9a-f]{40}$", h):
            continue
        for event in events:
            # Invariant: a push run is asked of `sha` alone; a PR head is never pushed to main.
            if event != "pull_request" and h != sha:
                continue
            rc, out = _gh(
                root,
                sink,
                f"gh-api-runs-{event}-{h[:12]}",
                "api",
                f"repos/{{owner}}/{{repo}}/actions/workflows/{workflow}/runs?event={event}"
                f"&head_sha={h}",
                "--jq",
                _RUNS_OF_PR if pr else ".workflow_runs[].id",
            )
            if rc != 0:
                return (
                    f"consult: measure — could not look (`gh api` for the runs of {h[:12]} did not"
                    f" answer: {sink}/gh-api-runs-{event}-{h[:12]}.err)",
                    "",
                )
            if pr:
                out = " ".join(
                    w[0] for w in (ln.split() for ln in out.splitlines()) if w and _of(pr, w[1:])
                )
            found += [
                int(r) for r in out.split() if re.match(r"^[1-9][0-9]*$", r) and int(r) not in found
            ]
    if not found:
        return (
            f"consult: measure — no candidate (no {' or '.join(events)} run of {workflow} for"
            f" {sha[:12]} or a pull request associated with it; gh's answers:"
            f" {sink}/gh-api-runs-*.out)",
            "",
        )
    listed = subprocess.run(
        ["./scripts/check.sh", "--list-legs"],
        cwd=root,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    if not listed.stdout:
        return (
            "consult: measure — could not look (./scripts/check.sh --list-legs would not answer;"
            " the record's units cannot be read without it)",
            "",
        )
    first = ""
    for run in [str(r) for r in sorted(found, reverse=True)]:
        rc, attempt = ci_fetch(root, run, sink)
        if rc != 0:
            first = first or (f"could not look ({attempt})" if rc == 2 else attempt)
            continue
        text = (sink / f"record-{run}" / CI_RECORD).read_text(errors="replace")
        line = next((ln for ln in text.splitlines() if ln.split()), "")
        try:
            ci_judge(root, line, run, attempt, listed.stdout)
        except Refused as exc:
            first = first or str(exc)
            continue
        rec = ci_parse(line)
        if rec.tree != mytree:
            first = first or (
                f"run {run} measured tree {rec.tree[:12]} and this checkout measures {mytree[:12]}"
                " — the pushed bytes are not the bytes the run measured"
            )
            continue
        if selftest and rec.selftest in ("withheld", "narrowed"):
            first = first or (
                f"run {run} {rec.selftest} the selftest unit — it never measured this tree whole"
            )
            continue
        said = f" {CI_SELFTEST}={rec.selftest}" if rec.selftest else ""
        said += f" {CI_PYTEST}={rec.pytest}" if rec.pytest else ""
        return f"consult: honoured run={run} attempt={attempt}{said} tree={mytree}", run
    return f"consult: measure — {first}", ""


# --- the durations table: one file, one column per machine ----------------------------------------

#: The template's walls table and the product drawer's (`GATE_MEMBER_WALLS_*`).
WALLS_TEMPLATE = "scripts/gate_member_durations.json"
WALLS_DRAWER = "scripts/local/gate_member_durations.ci.json"
#: The walls table's two second-level sections: per engine rule, per gate-tests module.
RULES, MODULES = "rules", "modules"

_WALLS_ORDER = {
    "box": ["box", "ubuntu-latest", "darwin"],
    "darwin": ["darwin", "ubuntu-latest"],
    "ubuntu-latest": ["ubuntu-latest", "darwin"],
}


def _walls_column(label: object) -> str:
    text = str(label or "")
    return "darwin" if text.startswith("Darwin") else text


def _walls_read(
    homes: Iterable[Path], say: Callable[[str], None]
) -> tuple[dict[str, dict[str, int]], dict[str, str]]:
    import json

    walls: dict[str, dict[str, int]] = {}
    ats: dict[str, str] = {}
    for home in homes:
        try:
            doc = json.loads(home.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as exc:
            say(f"note: the walls table {home} would not read ({exc}) — it adds nothing")
            continue
        members = doc.get("members") or {}
        if isinstance(doc.get("measured_at"), dict):
            ats.update(doc["measured_at"])
            for name, row in members.items():
                if isinstance(row, dict):
                    for m, v in row.items():
                        walls.setdefault(name, {})[m] = v
        else:
            column = _walls_column(doc.get("machine"))
            ats[column] = doc.get("measured_at", "")
            for name, v in members.items():
                walls.setdefault(name, {})[column] = v
    return walls, ats


def durations(
    root: Path,
    machine: str,
    *,
    only: bool = False,
    homes: Sequence[Path] | None = None,
    say: Callable[[str], None] = _stderr,
) -> dict[str, int]:
    """Each member's seconds by `machine`'s column order (`gate_member_walls_view`)."""
    order = [machine] if only else _WALLS_ORDER.get(machine, [machine])
    walls, _ = _walls_read(homes or [root / WALLS_TEMPLATE, root / WALLS_DRAWER], say)
    out: dict[str, int] = {}
    for name in sorted(walls):
        for m in order:
            if m in walls[name]:
                out[name] = int(walls[name][m])
                break
    return out


def store_durations(home: Path, machine: str, at: str, seconds: Mapping[str, int]) -> None:
    """Replace `machine`'s column of the table at `home` (`gate_member_walls_write`)."""
    if not seconds:
        raise Refused("no member's seconds to store — the table is unchanged")
    walls, ats = _walls_read([home], _stderr)
    for row in walls.values():
        row.pop(machine, None)
    for name, secs in seconds.items():
        walls.setdefault(name, {})[machine] = int(secs)
    _walls_write(home, {n: r for n, r in walls.items() if r}, {**ats, machine: at})


def store_duration(home: Path, member: str, seconds: int, machine: str) -> None:
    """Set one member's seconds in `machine`'s column, every other cell kept."""
    walls, ats = _walls_read([home], _stderr)
    walls.setdefault(member, {})[machine] = int(seconds)
    _walls_write(home, walls, ats)


def store_rule_walls(home: Path, machine: str, at: str, seconds: Mapping[str, float]) -> None:
    """Replace `machine`'s column of the table's per-rule section (`rules`), members kept."""
    if not seconds:
        raise Refused("no rule's seconds to store — the table is unchanged")
    walls, ats = _walls_read([home], _stderr)
    rules, rules_at = _rules_read(home)
    for row in rules.values():
        row.pop(machine, None)
    for rid, secs in seconds.items():
        rules.setdefault(rid, {})[machine] = round(float(secs), 1)
    kept = {r: row for r, row in rules.items() if row}
    _walls_write(home, walls, ats, rules=(kept, {**rules_at, machine: at}))


def store_module_walls(home: Path, machine: str, at: str, seconds: Mapping[str, float]) -> None:
    """Replace `machine`'s column of the table's per-module section (`modules`), the rest kept."""
    if not seconds:
        raise Refused("no module's seconds to store — the table is unchanged")
    walls, ats = _walls_read([home], _stderr)
    modules, modules_at = _rules_read(home, MODULES)
    for row in modules.values():
        row.pop(machine, None)
    for name, secs in seconds.items():
        modules.setdefault(name, {})[machine] = round(float(secs), 1)
    kept = {m: row for m, row in modules.items() if row}
    _walls_write(home, walls, ats, modules=(kept, {**modules_at, machine: at}))


def rule_durations(homes: Sequence[Path], machine: str, section: str = RULES) -> dict[str, float]:
    """Each id's seconds from the tables' `section` (rules or modules), by column order."""
    order = _WALLS_ORDER.get(machine, [machine])
    out: dict[str, float] = {}
    for home in homes:
        rules, _ = _rules_read(home, section)
        for rid, row in rules.items():
            hit = next((row[m] for m in order if m in row), None)
            if hit is not None:
                out[rid] = hit
    return out


def module_durations(homes: Sequence[Path], machine: str) -> dict[str, float]:
    """Each test module's seconds from the tables' per-module sections, by column order."""
    return rule_durations(homes, machine, MODULES)


def _rules_read(
    home: Path, section: str = RULES
) -> tuple[dict[str, dict[str, float]], dict[str, str]]:
    """The table's `section` and its own `<section>_at`; empty when it has none."""
    import json

    try:
        doc = json.loads(home.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, {}
    rules = doc.get(section) if isinstance(doc, dict) else None
    at = doc.get(f"{section}_at") if isinstance(doc, dict) else None
    if not isinstance(rules, dict):
        return {}, {}
    found = {
        str(r): {str(m): float(v) for m, v in row.items() if isinstance(v, (int, float))}
        for r, row in rules.items()
        if isinstance(row, dict)
    }
    return found, ({str(k): str(v) for k, v in at.items()} if isinstance(at, dict) else {})


def _walls_write(
    home: Path,
    walls: Mapping[str, Mapping[str, int]],
    ats: Mapping[str, str],
    *,
    rules: tuple[Mapping[str, Mapping[str, float]], Mapping[str, str]] | None = None,
    modules: tuple[Mapping[str, Mapping[str, float]], Mapping[str, str]] | None = None,
) -> None:
    # Invariant: a write keeps every section the file already holds and was not handed.
    sections = (
        (RULES, rules if rules is not None else _rules_read(home, RULES), _rule_order),
        (MODULES, modules if modules is not None else _rules_read(home, MODULES), str),
    )
    out = ["{", '  "schema": "member-walls/2",', '  "measured_at": {']
    keys = sorted(ats)
    out += [
        f'    "{k}": "{ats[k]}"' + ("," if i < len(keys) - 1 else "") for i, k in enumerate(keys)
    ]
    out += ["  },", '  "members": {']
    names = sorted(walls)
    for i, n in enumerate(names):
        cols = ", ".join(f'"{m}": {walls[n][m]}' for m in sorted(walls[n]))
        out.append(f'    "{n}": {{{cols}}}' + ("," if i < len(names) - 1 else ""))
    for label, (section, section_at), order in sections:
        if not section:
            continue
        out += ["  },", f'  "{label}_at": {{']
        at_keys = sorted(section_at)
        out += [
            f'    "{k}": "{section_at[k]}"' + ("," if i < len(at_keys) - 1 else "")
            for i, k in enumerate(at_keys)
        ]
        out += ["  },", f'  "{label}": {{']
        ids = sorted(section, key=order)
        for i, r in enumerate(ids):
            cols = ", ".join(f'"{m}": {section[r][m]:.1f}' for m in sorted(section[r]))
            out.append(f'    "{r}": {{{cols}}}' + ("," if i < len(ids) - 1 else ""))
    out += ["  }", "}"]
    home.parent.mkdir(parents=True, exist_ok=True)
    tmp = home.with_name(f"{home.name}.write.{os.getpid()}")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.replace(tmp, home)


def _rule_order(rid: str) -> tuple[int, int, str]:
    """Numeric ids in number order, then every other id by its spelling."""
    return (0, int(rid), "") if rid.isdigit() else (1, 0, rid)


# --- the replay -----------------------------------------------------------------------------------


@dataclass
class Replay:
    """What the replay re-derived, by kind and outcome; `first` names the first mismatch."""

    root: Path
    counts: dict[str, int] = field(default_factory=dict)
    first: str = ""
    _vocabulary: frozenset[str] | None = None
    _listings: dict[str, list[Entry]] = field(default_factory=dict)

    def tally(self, what: str) -> None:
        """Count one outcome."""
        self.counts[what] = self.counts.get(what, 0) + 1

    def vocabulary(self) -> frozenset[str]:
        """The app labels a recorded scope is segmented against, read once."""
        if self._vocabulary is None:
            self._vocabulary = app_vocabulary(self.root)
        return self._vocabulary

    def entries(self, tree: str) -> list[Entry] | None:
        """The listing of `tree`, or None when this repository does not hold it."""
        if tree not in self._listings:
            try:
                self._listings[tree] = listing(self.root, tree)
            except Mismatch:
                return None
        return self._listings[tree]


def replay_row(row: Row, state: Replay) -> None:
    """Re-derive the key and docs-only admission `row` records; `Mismatch` on a difference."""
    if row.kind == "loop":
        _replay_loop(row, state)
    elif row.kind == "drive":
        _replay_drive(row, state)
    sanction = row.get("sanction") or ""
    if sanction.startswith("docs-only:"):
        _replay_docs_only(row, sanction, state)
    reuse = row.get("reuse")
    if reuse:
        _replay_reuse(row, reuse, state)


def _replay_loop(row: Row, state: Replay) -> None:
    tree, env, scope = row.get("key-tree") or row.get("tree"), row.get("env"), row.get("scope")
    if not LOOP_KEY_RE.match(row.key):
        raise Mismatch(f"the loop key {row.key} is not loop-v1:<64 hex>")
    if tree in (None, "unstated") or env in (None, "unstated") or scope is None:
        state.tally("loop: inputs not recorded")
        return
    if any(loop_key(tree, env, c) == row.key for c in scope_candidates(scope, state.vocabulary())):
        state.tally("loop: key re-derived")
        return
    raise Mismatch(f"no reading of scope= with tree={tree} env={env} derives {row.key}")


def _replay_drive(row: Row, state: Replay) -> None:
    tree, name = row.get("tree"), next((v for n, v in row.fields if not n), None)
    recorded = recorded_parts(row)
    if not tree or not name or not recorded:
        state.tally("drive: inputs not recorded")
        return
    entries = state.entries(tree)
    drive = next((p for p in recorded if p.endswith(f"/test_{name}.sh")), None)
    if entries is None or drive is None:
        state.tally("drive: tree not in this repository")
        return
    if not any(e.path == drive for e in entries):
        state.tally("drive: the drive file is outside its tree (a synthesized drive)")
        return
    derived = drive_parts(state.root, tree, drive, entries)
    for label, prefix in recorded.items():
        if label == "machine":
            continue
        if label not in derived:
            raise Mismatch(f"part {label} is recorded and {drive} at {tree} derives no such part")
        if not derived[label].startswith(prefix):
            raise Mismatch(f"part {label} recorded {prefix}, derived {derived[label][:12]}")
    # The composition grew under one schema tag: a part the row predates is counted, not a mismatch.
    missing = set(derived) - set(recorded)
    state.tally("drive: parts re-derived" + (" (the row predates a part)" if missing else ""))
    if DRIVE_JUDGE_ENTRY.rsplit("/", 1)[0] + "/" in missing:
        state.tally("drive: the row predates the judge part")


def _sanction_words(sanction: str) -> dict[str, str]:
    reason = sanction.split(":", 2)[2].replace("%20", " ").replace("%09", "\t").replace("%25", "%")
    return dict(w.split("=", 1) for w in reason.split() if "=" in w)


def _replay_docs_only(row: Row, sanction: str, state: Replay) -> None:
    words = _sanction_words(sanction)
    source = words.get("from")
    if not source or state.entries(source) is None or state.entries(row.key) is None:
        state.tally("docs-only: trees not in this repository")
        return
    paths = changed_between(state.root, source, row.key)
    if "paths" in words and int(words["paths"]) != len(paths):
        raise Mismatch(f"paths={words['paths']} recorded, {len(paths)} changed {source}..{row.key}")
    refused = [p for p in paths if not docs_only_admits(p, source, row.key, root=state.root)]
    if refused:
        raise Mismatch(f"the decider does not admit {refused} between {source} and {row.key}")
    state.tally("docs-only: admission re-derived")


def _replay_reuse(row: Row, reuse: str, state: Replay) -> None:
    tree = row.get("tree") or ""
    if state.entries(reuse) is None or state.entries(tree) is None:
        state.tally("reuse: trees not in this repository")
        return
    refused = [
        p
        for p in changed_between(state.root, reuse, tree)
        if not docs_only_admits(p, reuse, tree, root=state.root)
    ]
    if refused:
        raise Mismatch(f"reuse={reuse}: the decider does not admit {refused} on the way to {tree}")
    state.tally("reuse: admission re-derived")


def replay(path: Path, root: Path, say: Callable[[str], None] = print) -> int:
    """Round-trip and re-derive every row at `path`; 0 all agree · 2 at the first mismatch."""
    state = Replay(root)
    n = 0
    for n, line in rows(path):
        try:
            row = parse(line)
        except MalformedRow as exc:
            say(f"ledger replay: {path}:{n} does not parse — {exc}")
            return 2
        if format(row) != line:
            say(f"ledger replay: {path}:{n} does not round-trip: {line[:160]}")
            return 2
        state.tally("grammar: strict" if in_grammar(line) else "grammar: pre-grammar row")
        if not in_grammar(line) and not pre_grammar(line):
            say(f"ledger replay: {path}:{n} is outside the grammar and not a pre-grammar row")
            return 2
        try:
            replay_row(row, state)
        except Mismatch as exc:
            say(f"ledger replay: MISMATCH at {path}:{n} ({row.kind} {row.key}): {exc}")
            return 2
    say(f"ledger replay: {n} rows in {path}, every one round-trips")
    for what in sorted(state.counts):
        say(f"  {state.counts[what]:6d}  {what}")
    return 0


# --- the bank arm: the one fold every bank door runs before it measures --------------------------

#: The fold a bank door runs, relative to the checkout it banks.
FOLD = "scripts/pm_fold.sh"
#: The `--no-fold` notice under the door's name, byte for byte the shell's.
NO_FOLD_NOTICE = (
    "{who}: ** --no-fold — THE DERIVED FILES WERE NOT REGENERATED. **\n"
    "  The contract, the secret baseline and the budget floors are whatever is committed.\n"
    "  If the gate reddens on a stale client or a budget, that is THIS FLAG and not the tree."
)
FOLDING = (
    "{who}: folding {root} before the gate — {fold}\n"
    "  It regenerates the derived files and commits AT MOST the paths on its own typed list;\n"
    "  anything it modifies outside that list is its own exit 2, with nothing committed."
)
NO_FOLD_AT = "!! {who}: no executable fold at {fold} — pass --no-fold to go without one."
FOLD_EXITED = (
    "{who}: THE FOLD EXITED {rc} — 2 is could-not-fold (a dirty tree, a generator that failed,"
    " a file\n   modified outside the derived list); its output above names which."
)


def _say(text: str, *, err: bool = False) -> None:
    print(text, file=sys.stderr if err else sys.stdout, flush=True)


def bank_arm(root: Path, *, who: str, no_fold: bool, nothing: str) -> int:
    """The no-fold notice, or the fold (refusals end on `nothing`): 0 · the fold's exit · 2."""
    if no_fold:
        _say(NO_FOLD_NOTICE.format(who=who))
        return 0
    fold = Path(f"{root}/{FOLD}")
    if not (fold.is_file() and os.access(fold, os.X_OK)):
        _say(f"{NO_FOLD_AT.format(who=who, fold=fold)}\n   {nothing}", err=True)
        return 2
    _say(FOLDING.format(who=who, root=root, fold=fold))
    rc = subprocess.run([str(fold)], check=False).returncode
    if rc != 0:
        _say(f"{FOLD_EXITED.format(who=who, rc=rc)}\n   {nothing}", err=True)
    return rc


def _docs_only_verb(verb: str, args: argparse.Namespace) -> int:
    """The shell's docs-only functions, answered for `gate_ledger_cli`: lines on stdout."""
    root = Path.cwd()
    depth = int(args.depth) if getattr(args, "depth", "").isdigit() else None
    if verb == "docs-only-claims":
        print(
            "".join(
                f"{c} {p}\n" for c, p in docs_only_claims(root, args.head, args.base, depth=depth)
            ),
            end="",
        )
        return 0
    if verb == "docs-only-drives":
        print("".join(f"{d}\n" for d in docs_only_drives(root, args.paths)), end="")
        return 0
    if verb == "docs-only-stale-nonreads":
        print("".join(f"{s}\n" for s in docs_only_stale_nonreads(root)), end="")
        return 0
    if verb == "docs-only-nonread-covers":
        return 0 if docs_only_nonread_covers(root / args.file, args.needle) else 1
    try:
        if verb == "docs-only-source":
            source, legs, proof = docs_only_source(root, args.head, depth=depth)
            print(f"source={source}\nlegs={legs}\nproof={proof}")
            return 0
        plan = docs_only_plan(root, args.head, depth=depth)
    except DocsOnlyRefused as no:
        print(f"why={no}")
        return 1
    print(f"source={plan.source}\nlegs={plan.legs}\nproof={plan.proof}\nn={plan.n}")
    print(f"readers={','.join(plan.readers)}")
    return 0


def _nightly_verb(args: argparse.Namespace) -> int:
    """`nightly-line <11 fields>`: the record on stdout, 0 · the notes on stderr, 2."""
    try:
        print(nightly_line(args.fields))
    except Refused as no:
        print(no, file=sys.stderr)
        return 2
    return 0


_CI_VERBS = (
    "nightly-read",
    "ci-artifact-name",
    "measured-tree",
    "measured-tree-of",
    "ci-consult",
    "selftest-consult",
    "proof-consult",
    "ci-record",
)


def _ci_verb(verb: str, args: argparse.Namespace) -> int:
    """The CI workflow's and the deploy script's verbs: the answer on stdout, a refusal 2."""
    root = Path.cwd()
    try:
        if verb == "ci-artifact-name":
            print(ci_artifact_name(args.attempt))
        elif verb == "nightly-read":
            print(nightly_read(args.directory))
        elif verb == "measured-tree":
            print(measured_tree(root))
        elif verb == "measured-tree-of":
            print(measured_tree_of(root, args.rev))
        elif verb == "ci-consult":
            print(ci_consult(root, args.sha, docs_road=True, pr=args.pr)[0])
        elif verb == "proof-consult":
            print(proof_consult_source(root, args.sha)[0])
        elif verb == "selftest-consult":
            events = ("pull_request", "push")
            print(ci_consult(root, args.sha, events, docs_road=True, selftest=True)[0])
        else:
            commit, tree, legs, shards, scope, rc, run, attempt = args.fields
            line = ci_record(
                commit,
                tree,
                legs,
                shards,
                scope,
                rc,
                run,
                attempt,
                lane=args.lane or None,
                selftest=args.closure or None,
                pytest=args.pytest or None,
            )
            if args.out:
                (Path(args.out) / CI_RECORD).write_text(f"{line}\n", encoding="utf-8")
            print(line)
    except (Refused, Mismatch, CouldNotLook) as no:
        print(no, file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    """`replay`, `bank-arm`, and the shell decider's docs-only, nightly and CI verbs."""
    parser = argparse.ArgumentParser(prog="python -m quality.djb.ledger")
    sub = parser.add_subparsers(dest="verb", required=True)
    one = sub.add_parser("replay", help="round-trip and re-derive every row")
    one.add_argument("ledger", nargs="?", default="")
    arm = sub.add_parser("bank-arm", help="the no-fold notice, or the fold a bank door runs")
    arm.add_argument("who")
    arm.add_argument("root")
    arm.add_argument("no_fold", choices=("0", "1"))
    arm.add_argument("nothing")
    for verb in ("docs-only-plan", "docs-only-source", "docs-only-claims"):
        walk = sub.add_parser(verb)
        walk.add_argument("head")
        if verb == "docs-only-claims":
            walk.add_argument("base", nargs="?", default="")
        walk.add_argument("--depth", default="")
    sub.add_parser("docs-only-drives").add_argument("paths", nargs="*")
    sub.add_parser("docs-only-stale-nonreads")
    covers_ = sub.add_parser("docs-only-nonread-covers")
    covers_.add_argument("file")
    covers_.add_argument("needle")
    sub.add_parser("nightly-line").add_argument("fields", nargs="*")
    sub.add_parser("nightly-read").add_argument("directory", nargs="?", default="")
    sub.add_parser("ci-artifact-name").add_argument("attempt")
    sub.add_parser("measured-tree")
    sub.add_parser("measured-tree-of").add_argument("rev")
    consult = sub.add_parser("ci-consult")
    consult.add_argument("sha")
    consult.add_argument("--pr", default="", help="a pull request's head: its own runs only")
    sub.add_parser("selftest-consult").add_argument("sha")
    sub.add_parser("proof-consult").add_argument("sha")
    record = sub.add_parser("ci-record", help="the gate-verdict/1 line; --out writes it there")
    record.add_argument("--out", default="")
    record.add_argument("--lane", default="", help="the lane the run measured: docs, loop, full")
    record.add_argument(
        "--closure", default="", help="how the selftest unit ran: ran, narrowed, withheld"
    )
    record.add_argument("--pytest", default="", help="how pytest-x2 ran: whole, narrowed")
    record.add_argument("fields", nargs=8)
    for verb in ("nightly-fetch", "nightly-source"):
        night = sub.add_parser(verb)
        night.add_argument("sink")
        if verb == "nightly-source":
            night.add_argument("bank", nargs="?", default="")
        night.add_argument("--gh", default="gh")
    args = parser.parse_args(argv)
    if args.verb in _CI_VERBS:
        return _ci_verb(args.verb, args)
    if args.verb == "bank-arm":
        return bank_arm(
            Path(args.root), who=args.who, no_fold=args.no_fold == "1", nothing=args.nothing
        )
    if args.verb.startswith("docs-only-"):
        return _docs_only_verb(args.verb, args)
    if args.verb == "nightly-line":
        return _nightly_verb(args)
    if args.verb == "nightly-fetch":
        rc, said = nightly_fetch(Path(args.sink), gh=args.gh)
        print(said)
        return rc
    if args.verb == "nightly-source":
        print("\n".join(nightly_source(Path(args.sink), args.bank, gh=args.gh)))
        return 0
    root = Path.cwd()
    try:
        path = Path(args.ledger) if args.ledger else ledger_path(root)
    except Refused as exc:
        print(f"ledger replay: {exc}", file=sys.stderr)
        return 2
    return replay(path, root)


if __name__ == "__main__":
    sys.exit(main())
