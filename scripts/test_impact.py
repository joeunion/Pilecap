"""The test-impact map: which source files each test EXECUTED, written from one
acceptance run's per-test coverage contexts.

    .venv/bin/python scripts/test_impact.py write --coverage <db>
                                                  --collected <nodeids file>
                                                  --out scripts/test_impact.json
                                                  [--root <checkout>] [--tree <sha>]

THERE IS NO SHEBANG, DELIBERATELY: `python3` off PATH is some other
environment's interpreter — on a Linux verifier box it is the system 3.9, where
this file's syntax is a `SyntaxError` reported as a finding about the coverage
database. Every caller invokes it through the checkout's own interpreter
(`checkout_python`, scripts/gate_refuse.sh), and a file with no shebang cannot
be invoked any other way by accident.

WHY IT EXISTS. The inner loop runs a DEPENDENCY CLOSURE: change a file in one
app and every test of every app that declares it runs. The closure is correct
and it is enormous, and the thing that would replace it is a fact nobody
records — which tests actually execute the lines of the file that changed. One
acceptance run per wave records it: `pytest --cov-context=test` switches
coverage's context at every test, so every measured line carries the nodeid that
executed it, and this file inverts that into nodeid -> source files. The map is
a PROJECTION and never truth (principle 9): the tree is authoritative, the map
is one run's measurement of it, and every reader of the map owes a fallback for
the day it is stale.

THE CENSUS, and it is the whole point of the file. A map is only usable for
SELECTION, and a selection is only safe if the population it selects from is
closed. So every collected nodeid ends up in exactly one of two places:

  * `tests`    — the checkout-relative source files it executed, sorted.
  * `unmapped` — a REASON, in words, for why there are none.

Never neither, never both, and never an empty list. An empty list is the one
answer that is silently wrong: a test whose only read of the tree is
`read_text()` or `ast.parse` executes no measured source line, and `[]` reads
downstream as "this test touches nothing" — so it is never selected again, for
any change, forever. A reason can be acted on; an empty list cannot.

AND A COLLECTED TEST THE DATABASE NEVER SAW IS COULD-NOT-LOOK. A nodeid the
collection has and coverage has no context for is not a test that touched
nothing: it is a run that did not measure it (a shard that did not reach it, a
worker whose data was not combined, a database from another tree). Writing the
map anyway would publish a census with a hole in it, so it is exit 2 naming the
nodeid and NO FILE IS WRITTEN.

EXIT 0 with a map · EXIT 2 could not look. There is no exit 1: this writer
judges nothing, it measures.

DETERMINISTIC BY CONSTRUCTION (principle 16: a map regenerated twice is one
file). `generated.at` is the coverage database's own modification time rather
than the clock, so two writes over one database are byte-identical and a
re-run costs no diff. Keys are sorted and every entry is ONE LINE, because the
file is tracked and a person reads its diff in a pull request.

WHAT IT DOES NOT COVER, declared rather than discovered:

 1. A SUBPROCESS. A test that shells out — `manage.py`, a shell drive, a
    container — executes those lines in another process under no context, so
    the map never records them. Such a test is mapped by what its own process
    executed, which for a pure subprocess driver is its own module and nothing
    else.
 2. WHAT IS NOT PYTHON. Templates, fixtures, `.env`, YAML, migrations' data and
    every asset a test reads by path are invisible to coverage. A reader that
    selects from this map owes a fallback for a changed file the map has never
    recorded; that fallback, and not this file, is where those live.
 3. WHETHER THE ATTRIBUTION IS RIGHT. A file touched through a fixture defined
    in another module is attributed to the TEST, which is correct for selection
    and wrong for blame. This file makes no blame claim.
 4. A TEST THAT WAS COLLECTED AND DID NOT RUN, which is MEASURED rather than
    theorised: `coverage` materialises a context row only when a line is added
    under it, so a test skipped at setup (a `skipif` mark, a module-level
    `pytest.skip`) leaves no context at all and is indistinguishable here from
    a test the run never reached. Both are exit 2. That is the safe direction —
    a map with a hole in it is worse than no map — and it means an acceptance
    run whose suite SKIPS anything writes no map until the skip is either gone
    or fed to this writer as a declared population, which it has no input for
    today. (A test skipped from INSIDE its body has already executed its own
    module's lines and is mapped normally.)
 5. A TEST THAT RAN AND WAS NOT COLLECTED. A context in the database whose
    nodeid is not in the collected list is NAMED in the census output as
    vanished and is not in the map: it is a deleted test, a renamed one, or a
    database from another run, and the writer cannot tell those apart.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
from typing import Any

# THE REASON, SPELLED ONCE. It is asserted verbatim by the drive and read by a
# person looking at the map, so it lives in one place and is quoted from here.
NO_SOURCE_REASON = "no source line recorded — reads the tree by path (read_text/ast) or is pure"


MapDoc = dict[str, Any]


class CannotLook(Exception):
    """An input this writer cannot read. Exit 2, and nothing is written."""


def nodeid_of_context(context: str) -> str:
    """`<nodeid>|<phase>` -> `<nodeid>`.

    pytest-cov's `--cov-context=test` names every context for the test AND the
    phase it was in (`|setup`, `|run`, `|teardown`), and all three phases are
    the same test for selection. The empty context — coverage's own, for lines
    executed at import before any test — is not a test and is dropped by the
    caller.
    """
    return context.rsplit("|", 1)[0] if "|" in context else context


def read_collected(path: str) -> list[str]:
    """The nodeids `pytest --collect-only -q` printed, in order, deduplicated.

    Its output is the nodeids, a blank line, and a summary ("1234 tests
    collected in 5.67s") that is not one — plus whatever warnings the session
    emitted. A line is a nodeid when it carries `::` and starts at column zero;
    pytest indents nothing it collected.
    """
    if not os.path.isfile(path):
        raise CannotLook(f"no collected list at {path}")
    seen: set[str] = set()
    out: list[str] = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line or line != line.lstrip() or "::" not in line:
                continue
            if line in seen:
                continue
            seen.add(line)
            out.append(line)
    if not out:
        raise CannotLook(
            f"the collected list is empty ({path} names no test). A --collect-only that "
            "lost its collector exits 0 printing nothing, and a map written from it would "
            "say, truthfully and uselessly, that no test reaches any file"
        )
    return out


def read_contexts(db_path: str, root: str) -> tuple[dict[str, set[str]], set[str], int]:
    """(nodeid -> checkout-relative files, every nodeid the database saw, files outside root).

    The second return value is what tells "executed nothing" from "was never
    measured" apart, and the whole census turns on the difference.
    """
    if not os.path.isfile(db_path):
        raise CannotLook(f"no coverage database at {db_path}")
    try:
        from coverage import CoverageData
    except ImportError as exc:  # pragma: no cover - the dev group carries it
        raise CannotLook(
            f"this interpreter has no 'coverage' ({exc}). It arrives with pytest-cov, "
            "pyproject.toml dev group; run ./scripts/setup.sh"
        ) from exc

    data = CoverageData(basename=db_path)
    try:
        data.read()
    except Exception as exc:  # noqa: BLE001 - any unreadable database is one answer
        raise CannotLook(
            f"{db_path} is not a coverage database this version can read: {exc}"
        ) from exc

    seen_nodeids: set[str] = set()
    for context in data.measured_contexts():
        if context:
            seen_nodeids.add(nodeid_of_context(context))

    by_test: dict[str, set[str]] = {}
    outside = 0
    root = os.path.realpath(root)
    for measured in data.measured_files():
        rel = relative_to(measured, root)
        if rel is None:
            outside += 1
            continue
        contexts = data.contexts_by_lineno(measured) or {}
        for names in contexts.values():
            for context in names:
                if not context:
                    continue
                by_test.setdefault(nodeid_of_context(context), set()).add(rel)
    return by_test, seen_nodeids, outside


def relative_to(path: str, root: str) -> str | None:
    """`path` under `root`, checkout-relative with forward slashes, else None.

    A file outside the checkout — the interpreter's own library, a site package
    a test imported — is not a thing any change to this repository can move, so
    it is not part of the map. It is COUNTED rather than dropped silently.
    """
    real = os.path.realpath(path)
    if real == root:
        return None
    prefix = root.rstrip(os.sep) + os.sep
    if not real.startswith(prefix):
        return None
    return real[len(prefix) :].replace(os.sep, "/")


def derive_tree(root: str) -> str:
    """`tree:<sha>` for the tree this map was measured on, or `-`.

    A dash rather than a guess: a reader compares this against its own tree to
    decide whether the map is stale, and a wrong sha there is worse than no sha.

    `tree:` IS PART OF THE VALUE, and it is `scripts/check.sh:1681`'s idiom for
    the same measured reason: it says what the forty characters after it are —
    a git TREE sha, not a commit — and it keeps `detect-secrets`' Hex High
    Entropy String plugin from reading a public tree sha as a credential. The
    plugin takes the whole quoted value and asks whether it is hex, JSON has no
    comment to hang a `pragma: allowlist secret` on, and a bare sha here reds
    the `--loop` secrets leg on every rung that re-measures. Measured on this
    file's own first real map, exactly as it was measured on
    `gate_member_durations.json`'s.
    """
    try:
        out = subprocess.run(
            ["git", "-C", root, "rev-parse", "HEAD^{tree}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "-"
    sha = out.stdout.strip()
    return f"tree:{sha}" if out.returncode == 0 and sha else "-"


def label_tree(sha: str) -> str:
    """A typed `--tree` carries the same `tree:` label the derived one does."""
    return sha if sha == "-" or sha.startswith("tree:") else f"tree:{sha}"


def render(doc: MapDoc) -> str:
    """The map's bytes: sorted keys, ONE LINE PER ENTRY.

    `json.dumps(indent=2)` puts every element of every list on its own line,
    which turns a map of a few thousand tests into a hundred thousand lines and
    a diff nobody reads. This renders the two dictionaries by hand so that a
    wave-to-wave diff is one line per test that changed.
    """
    lines = ["{"]
    generated = doc["generated"]
    lines.append('  "generated": {')
    keys = sorted(generated)
    for i, key in enumerate(keys):
        comma = "," if i < len(keys) - 1 else ""
        lines.append(f"    {json.dumps(key)}: {json.dumps(generated[key])}{comma}")
    lines.append("  },")
    for name in ("tests", "unmapped"):
        body = doc[name]
        tail = "," if name == "tests" else ""
        if not body:
            lines.append(f"  {json.dumps(name)}: {{}}{tail}")
            continue
        lines.append(f"  {json.dumps(name)}: {{")
        entries = sorted(body)
        for i, nodeid in enumerate(entries):
            comma = "," if i < len(entries) - 1 else ""
            lines.append(f"    {json.dumps(nodeid)}: {json.dumps(body[nodeid])}{comma}")
        lines.append(f"  }}{tail}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def build(args: argparse.Namespace) -> tuple[MapDoc, list[str], int]:
    """(the map, the vanished nodeids, the files outside the checkout)."""
    root = os.path.realpath(args.root)
    collected = read_collected(args.collected)
    by_test, seen, outside = read_contexts(args.coverage, root)

    missing = [n for n in collected if n not in seen and n not in by_test]
    if missing:
        first = missing[0]
        raise CannotLook(
            f"{first} collected, no context"
            + (f" (and {len(missing) - 1} more)" if len(missing) > 1 else "")
            + ".\n   A nodeid the collection has and the coverage database does not is not a\n"
            "   test that touched nothing: it is a run that did not measure it — a shard\n"
            "   that did not reach it, a worker whose data was never combined, a database\n"
            "   from another tree, or a test that never ran (a skip at setup records no\n"
            "   context). A map written over that hole would be a census that lies."
        )

    tests: dict[str, list[str]] = {}
    unmapped: dict[str, str] = {}
    for nodeid in collected:
        files = sorted(by_test.get(nodeid, ()))
        if files:
            tests[nodeid] = files
        else:
            unmapped[nodeid] = NO_SOURCE_REASON

    collected_set = set(collected)
    vanished = sorted(n for n in seen if n not in collected_set)

    at = datetime.datetime.fromtimestamp(os.path.getmtime(args.coverage), tz=datetime.UTC).replace(
        microsecond=0
    )
    doc = {
        "generated": {
            "at": at.isoformat(),
            "pytest": len(collected),
            "tree": label_tree(args.tree) if args.tree else derive_tree(root),
        },
        "tests": tests,
        "unmapped": unmapped,
    }
    return doc, vanished, outside


def cmd_write(args: argparse.Namespace) -> int:
    doc, vanished, outside = build(args)
    body = render(doc)

    out = os.path.abspath(args.out)
    parent = os.path.dirname(out)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    # WRITTEN WHOLE, THEN MOVED. A reader that arrives mid-write reads a
    # truncated map and reports it as a corrupt one; the tracked file is either
    # the old map or the new one and never half of either.
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(body)
    os.replace(tmp, out)

    n_files = len({f for files in doc["tests"].values() for f in files})
    print(
        f"test_impact: {len(doc['tests'])} tests mapped · "
        f"{len(doc['unmapped'])} unmapped · {n_files} files"
    )
    print(f"  map        {out}")
    print(
        f"  generated  tree={doc['generated']['tree']} at={doc['generated']['at']} "
        f"pytest={doc['generated']['pytest']}"
    )
    if outside:
        print(
            f"  outside    {outside} measured file(s) are not under {os.path.realpath(args.root)}"
        )
    if vanished:
        print(f"  vanished   {len(vanished)} context(s) name no collected test:")
        for nodeid in vanished:
            print(f"               {nodeid}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="test_impact.py",
        description="Write the test-impact map from one run's per-test coverage contexts.",
        allow_abbrev=False,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    writer = sub.add_parser("write", help="write the map", allow_abbrev=False)
    writer.add_argument("--coverage", required=True, help="the combined .coverage database")
    writer.add_argument("--collected", required=True, help="`pytest --collect-only -q` output")
    writer.add_argument("--out", required=True, help="where the map is written")
    writer.add_argument("--root", default=".", help="the checkout every path is relative to")
    writer.add_argument("--tree", default="", help="the tree it was measured on (else derived)")
    args = parser.parse_args(argv)

    try:
        return cmd_write(args)
    except CannotLook as exc:
        print(f"!! test_impact: could not look — {exc}", file=sys.stderr)
        print("   No map was written. A census with a hole in it is not a census,", file=sys.stderr)
        print("   and the loop keeps its closure scope until one can be measured.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
