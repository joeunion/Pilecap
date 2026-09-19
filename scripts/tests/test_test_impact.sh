#!/usr/bin/env bash
# THIS FILE IS EXECUTED, AND IT IS BASH — not POSIX sh, and not zsh. The
# shebang above is honoured by `./this`; `sh this` and `zsh this` IGNORE it,
# and neither of them fails where the mistake was made. A wrong shell here
# does not crash; it ANSWERS, and the answer looks like the tree's fault.
#
# TWO TESTS, because on macOS `/bin/sh` IS bash: BASH_VERSION is set under
# `sh x.sh` and only POSIX MODE tells the two apart (SHELLOPTS carries
# `posix`). On Linux `/bin/sh` is dash and the first test is the one that
# fires. Neither test alone covers both machines.
[ -n "${BASH_VERSION:-}" ] || {
    echo "${0##*/}: must run under bash — not sh, not zsh. Try \`bash ${0}\`." >&2
    exit 2
}
case ":${SHELLOPTS:-}:" in
*:posix:*)
    echo "${0##*/}: bash is in POSIX mode — which is what \`sh ${0}\` does on a" >&2
    echo "  machine whose /bin/sh is bash. Try \`bash ${0}\`." >&2
    exit 2
    ;;
esac
# drives: scripts/test_impact.py scripts/test_impact.json
# cites: manage.py pyproject.toml scripts/check.sh scripts/pm_push.sh scripts/setup.sh scripts/tests/test_drive_preamble.sh scripts/tests/test_pm_push.sh
# The drive for `scripts/test_impact.py` — the writer that turns one acceptance
# run's per-test coverage contexts into the TEST-IMPACT MAP.
#
#   ./scripts/tests/test_test_impact.sh          run every case
#   ./scripts/tests/test_test_impact.sh --list   name them and stop
#
# WHY IT EXISTS. The map answers one question — which source files did this
# test execute — and something downstream will SELECT tests from the answer.
# That turns every silent hole in the writer into a test nobody runs. Two holes
# are silent by construction and both look exactly like an answer:
#
#   * A TEST WITH AN EMPTY LIST. A test whose only read of the tree is
#     `read_text()` or `ast.parse` executes no measured source line. Written as
#     `[]` it reads downstream as "this test touches nothing" and is never
#     selected again, for any change, forever. So an empty executed set is
#     `unmapped` WITH A REASON and never an empty list — a declared blind spot
#     is a thing a reader can act on; an empty list is not.
#   * A TEST THE MAP NEVER SAW. A nodeid the collection has and the coverage
#     database does not is not a test that touched nothing: it is a run that
#     did not measure it. Writing the map anyway would publish a census with a
#     hole in it, so it is could-not-look (exit 2) and NO FILE IS WRITTEN.
#
# The census the cases below hold the writer to is a closed question over a
# discoverable population: every collected nodeid is in `tests` or in
# `unmapped`, never neither and never both.
#
# IT BUILDS ITS OWN VICTIMS. Every case writes its coverage database, its
# collected list and its output under `mktemp -d` and destroys them at exit.
# Nothing here runs pytest, touches this checkout's `scripts/test_impact.json`,
# needs docker, a database or a network. Sub-second.
#
# THE COVERAGE DATABASE IS BUILT THROUGH `coverage`'s OWN API, not by hand-
# written SQL, so a schema change upstream moves the fixture with the subject
# instead of leaving a fixture that no longer resembles what pytest writes. The
# ONE exception is the empty context — a context row with no line rows — which
# `CoverageData` will not create because it only materialises a context id when
# lines are added to it. That row is the whole of the first hole above, so the
# fixture inserts it directly and says so here rather than leaving the branch
# unreachable.
#
# THE INTERPRETER IS THIS CHECKOUT'S, NEVER `python3` OFF PATH. The subject is a
# python file this repository ships and pins at the version the venv holds; on a
# verifier box the system `python3` is 3.9 and this drive would report the
# interpreter's syntax error as a finding about the file it was driving.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * WHETHER THE MAP IS TRUE. Whether `--cov-context=test` attributed a line to
#     the right test is coverage's and pytest-cov's business; this drive feeds
#     the writer a database and asserts what it makes of it.
#   * WHAT A TEST REACHES THROUGH A SUBPROCESS. A test that shells out to
#     `manage.py` executes those lines in another process, which this map never
#     records. That is the subject's declared blind spot and it is declared in
#     the subject's own docstring; nothing here can see it.
#   * THE ACCEPTANCE BOX. Whether `scripts/pm_push.sh --bank --on-boxes` runs
#     the two passes, keeps the box out of the composed verdict and fetches the
#     file is `scripts/tests/test_pm_push.sh`'s business, not this drive's.
#   * REGISTRATION. Whether `scripts/check.sh` invokes this drive at all is the
#     gate's own business and is asserted in `test_drive_preamble.sh`.
set -euo pipefail

cd "$(dirname "$0")/../.."

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_test_impact: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It carries the scratch guards and the finished-sentinel. Refusing to" >&2
    echo "   run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh
DRIVE_OPTED_IN_TO_FINISH=1

PASSED=0
FAILED=0
CURRENT=""

cannot_look() {
    echo "!! test_test_impact: $*" >&2
    echo "   Nothing was asserted. A driver that could not run its cases has not" >&2
    echo "   cleared them." >&2
    exit 2
}

case "${1:-}" in
"") ;;
--list)
    grep -n '^case_[A-Za-z0-9_]*() {' "$0" | sed 's/() {.*//; s/^/  /'
    exit 0
    ;;
*)
    # A mistyped flag is never a silently different run.
    echo "!! unknown argument '$1': test_test_impact.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

DRIVE_PY="$PWD/.venv/bin/python"
[ -x "$DRIVE_PY" ] ||
    cannot_look "this checkout has no .venv/bin/python, and the python file this drive
   runs is written at the version that venv holds. Run ./scripts/setup.sh first"
SUBJECT="$PWD/scripts/test_impact.py"
[ -f "$SUBJECT" ] ||
    cannot_look "scripts/test_impact.py is not a file in this tree — there is nothing to drive"
"$DRIVE_PY" -c 'import coverage' 2>/dev/null ||
    cannot_look "this checkout's venv has no 'coverage', which is what writes the databases
   every fixture here is built from (it arrives with pytest-cov, pyproject.toml
   dev group). Run ./scripts/setup.sh first"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-test-impact-drive.XXXXXX")" ||
    cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'chmod -R u+rwX "$WORK" 2>/dev/null || true; rm -rf "$WORK"'

# --- assertions ---------------------------------------------------------------
OUT=""
RC=0
N=0
DIR=""

ok() {
    echo "  ok       ${CURRENT} — $1"
    PASSED=$((PASSED + 1))
}
bad() {
    echo "  FAILED   ${CURRENT} — $1"
    if [ -n "$OUT" ] && [ -f "$OUT" ]; then sed 's/^/             | /' "$OUT" | tail -25; fi
    FAILED=$((FAILED + 1))
}
exits() {
    if [ "$RC" -eq "$1" ]; then
        ok "exit ${RC}"
    else
        bad "wanted exit $1, got ${RC}"
    fi
}
says() {
    if grep -qF -- "$1" "$OUT"; then
        ok "says \"$1\""
    else
        bad "does not say \"$1\""
    fi
}
says_not() {
    if grep -qF -- "$1" "$OUT"; then
        bad "says \"$1\" and must not"
    else
        ok "does not say \"$1\""
    fi
}
holds() {
    local what="$1" want="$2" got="$3"
    if [ "$want" = "$got" ]; then
        ok "${what} = ${got}"
    else
        bad "${what}: wanted '${want}', got '${got}'"
    fi
}

# --- the world ----------------------------------------------------------------
#
# A FAKE CHECKOUT with one app, four test modules and one service module, and a
# coverage database whose contexts are the four shapes the census has to tell
# apart:
#
#   test_executes          lines inside the root          -> mapped
#   test_pure              lines only OUTSIDE the root    -> unmapped, empty set
#   test_reads_by_path     a context row with no lines    -> unmapped, empty set
#   test_gone              in the database, NOT collected -> vanished, named
#
# The first three are the collected population; `test_gone` is not, which is
# what makes "a test that vanished between the collection and the map" a state
# this drive can see rather than a sentence.
fresh() {
    CURRENT="$1"
    N=$((N + 1))
    DIR="${WORK}/case${N}"
    mkdir -p "$DIR/root/apps/alpha/tests"
    : >"$DIR/root/apps/alpha/services.py"
    : >"$DIR/root/apps/alpha/tests/test_services.py"
    "$DRIVE_PY" - "$DIR/root" "$DIR/coverage.db" <<'PY'
import sqlite3
import sys

from coverage import CoverageData

root, db = sys.argv[1], sys.argv[2]
data = CoverageData(basename=db)
data.set_context("apps/alpha/tests/test_services.py::test_executes|run")
data.add_lines(
    {
        f"{root}/apps/alpha/services.py": [1, 2, 3],
        f"{root}/apps/alpha/tests/test_services.py": [1, 5],
    }
)
data.set_context("apps/alpha/tests/test_pure.py::test_pure|run")
data.add_lines({"/opt/elsewhere/lib.py": [7]})
data.set_context("apps/alpha/tests/test_gone.py::test_gone|run")
data.add_lines({f"{root}/apps/alpha/services.py": [2]})
data.write()

# THE EMPTY CONTEXT, inserted directly. See the header: `CoverageData` will not
# create a context row until lines are added under it, and a context with no
# lines is exactly the state the first hole is about.
con = sqlite3.connect(db)
con.execute(
    "insert into context (context) values (?)",
    ("apps/alpha/tests/test_reads.py::test_reads_by_path|run",),
)
con.commit()
con.close()
PY
    collected_list \
        "apps/alpha/tests/test_services.py::test_executes" \
        "apps/alpha/tests/test_pure.py::test_pure" \
        "apps/alpha/tests/test_reads.py::test_reads_by_path"
}

# collected_list <nodeid...> — the shape `pytest --collect-only -q` prints: the
# nodeids, a blank line, and a summary line that is not one.
collected_list() {
    local id
    : >"$DIR/collected.txt"
    for id in "$@"; do printf '%s\n' "$id" >>"$DIR/collected.txt"; done
    {
        echo ""
        echo "$# tests collected in 0.42s"
    } >>"$DIR/collected.txt"
}

write_map() {
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    "$DRIVE_PY" "$SUBJECT" write \
        --coverage "$DIR/coverage.db" \
        --collected "$DIR/collected.txt" \
        --root "$DIR/root" \
        --out "$DIR/root/scripts/test_impact.json" "$@" >"$OUT" 2>&1 || RC=$?
}

# jq is not a dependency of this repository. The map is JSON and the questions
# asked of it are small, so the checkout's own interpreter answers them.
mapq() {
    "$DRIVE_PY" - "$DIR/root/scripts/test_impact.json" "$1" <<'PY'
import json
import sys

path, query = sys.argv[1], sys.argv[2]
with open(path) as fh:
    doc = json.load(fh)
if query == "n_tests":
    print(len(doc["tests"]))
elif query == "n_unmapped":
    print(len(doc["unmapped"]))
elif query == "n_total":
    print(len(doc["tests"]) + len(doc["unmapped"]))
elif query == "generated_keys":
    print(",".join(sorted(doc["generated"])))
elif query == "top_keys":
    print(",".join(sorted(doc)))
elif query.startswith("files:"):
    print(",".join(doc["tests"].get(query[6:], ["<absent>"])))
elif query.startswith("reason:"):
    print(doc["unmapped"].get(query[7:], "<absent>"))
elif query.startswith("in_tests:"):
    print("yes" if query[9:] in doc["tests"] else "no")
elif query.startswith("in_unmapped:"):
    print("yes" if query[12:] in doc["unmapped"] else "no")
else:
    raise SystemExit(f"unknown query {query}")
PY
}

# =============================================================================
# a.1 — every collected test is mapped or declared, and an empty executed set
#       is a DECLARATION rather than an empty list
# =============================================================================
case_every_collected_test_is_mapped_or_declared() {
    fresh every_collected_test_is_mapped_or_declared
    mkdir -p "$DIR/root/scripts"
    write_map
    exits 0
    [ -f "$DIR/root/scripts/test_impact.json" ] || {
        bad "no map was written"
        return
    }
    holds "tests" 1 "$(mapq n_tests)"
    holds "unmapped" 2 "$(mapq n_unmapped)"
    holds "tests + unmapped == collected" 3 "$(mapq n_total)"
    holds "the executing test's files" \
        "apps/alpha/services.py,apps/alpha/tests/test_services.py" \
        "$(mapq 'files:apps/alpha/tests/test_services.py::test_executes')"
    holds "the read_text test is declared, not empty" "yes" \
        "$(mapq 'in_unmapped:apps/alpha/tests/test_reads.py::test_reads_by_path')"
    holds "the pure test is declared, not empty" "yes" \
        "$(mapq 'in_unmapped:apps/alpha/tests/test_pure.py::test_pure')"
    holds "the read_text test carries the reason" \
        "no source line recorded — reads the tree by path (read_text/ast) or is pure" \
        "$(mapq 'reason:apps/alpha/tests/test_reads.py::test_reads_by_path')"
    holds "no collected test is in both halves" "no" \
        "$(mapq 'in_tests:apps/alpha/tests/test_pure.py::test_pure')"
    holds "the map's top-level keys" "generated,tests,unmapped" "$(mapq top_keys)"
    holds "the generated block" "at,pytest,tree" "$(mapq generated_keys)"
    says "1 tests mapped"
    says "2 unmapped"
    # THE TEST THAT VANISHED. It is in the coverage database and not in the
    # collection, so it is in neither half of the map — and the census NAMES it
    # rather than dropping it, because a context nobody collected is either a
    # deleted test or a database from another run.
    says "apps/alpha/tests/test_gone.py::test_gone"
    says "vanished"
}

# =============================================================================
# a.2 — a collected test the coverage database never saw is could-not-look
# =============================================================================
case_a_collected_test_with_no_context_is_could_not_look() {
    fresh a_collected_test_with_no_context_is_could_not_look
    mkdir -p "$DIR/root/scripts"
    collected_list \
        "apps/alpha/tests/test_services.py::test_executes" \
        "apps/alpha/tests/test_pure.py::test_pure" \
        "apps/alpha/tests/test_reads.py::test_reads_by_path" \
        "apps/alpha/tests/test_orphan.py::test_orphan"
    write_map
    exits 2
    says "!! test_impact: could not look — apps/alpha/tests/test_orphan.py::test_orphan collected, no context"
    if [ -f "$DIR/root/scripts/test_impact.json" ]; then
        bad "a map was written over a census with a hole in it"
    else
        ok "no file was written"
    fi
}

# =============================================================================
# a.3 — the same database twice is the same bytes twice
# =============================================================================
case_the_map_is_deterministic() {
    fresh the_map_is_deterministic
    mkdir -p "$DIR/root/scripts"
    write_map
    exits 0
    cp "$DIR/root/scripts/test_impact.json" "$DIR/first.json"
    write_map
    exits 0
    if cmp -s "$DIR/first.json" "$DIR/root/scripts/test_impact.json"; then
        ok "two writes over one database are byte-identical"
    else
        bad "two writes over one database differ: $(diff "$DIR/first.json" "$DIR/root/scripts/test_impact.json" | head -5)"
    fi
    # ONE LINE PER ENTRY, so a diff between two waves is readable. The map is
    # data a person reads in a pull request, not only a file a program loads.
    holds "one line per test entry" 1 \
        "$(grep -c 'test_services.py::test_executes' "$DIR/root/scripts/test_impact.json")"
    if grep -q '^    "apps/alpha/tests/test_services.py::test_executes": \["apps/alpha/services.py", "apps/alpha/tests/test_services.py"\],\?$' \
        "$DIR/root/scripts/test_impact.json"; then
        ok "a test's file list is on one line"
    else
        bad "a test's file list is not on one line: $(grep -n 'test_executes' "$DIR/root/scripts/test_impact.json" | head -3)"
    fi
}

# =============================================================================
# the three inputs it cannot proceed without — each named, each exit 2
# =============================================================================
case_a_missing_input_is_could_not_look() {
    fresh a_missing_input_is_could_not_look
    mkdir -p "$DIR/root/scripts"

    mv "$DIR/coverage.db" "$DIR/coverage.db.away"
    write_map
    exits 2
    says "!! test_impact: could not look — no coverage database at"
    mv "$DIR/coverage.db.away" "$DIR/coverage.db"

    mv "$DIR/collected.txt" "$DIR/collected.away"
    write_map
    exits 2
    says "!! test_impact: could not look — no collected list at"
    mv "$DIR/collected.away" "$DIR/collected.txt"

    # AN EMPTY COLLECTION IS NEVER AN EMPTY MAP. A `--collect-only` that lost
    # its collector exits 0 printing nothing, and a map written from it would
    # say, truthfully and uselessly, that no test reaches any file.
    collected_list
    write_map
    exits 2
    says "!! test_impact: could not look — the collected list is empty"

    if [ -f "$DIR/root/scripts/test_impact.json" ]; then
        bad "a map was written from an input it could not read"
    else
        ok "no file was written by any of the three"
    fi
}

# =============================================================================
# a mistyped subcommand is never a silently different run
# =============================================================================
case_an_unknown_subcommand_is_refused() {
    fresh an_unknown_subcommand_is_refused
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    "$DRIVE_PY" "$SUBJECT" wrote --coverage "$DIR/coverage.db" >"$OUT" 2>&1 || RC=$?
    if [ "$RC" -eq 0 ]; then
        bad "a mistyped subcommand ran something"
    else
        ok "exit ${RC} — a mistyped subcommand ran nothing"
    fi
    says_not "tests mapped"
}

# =============================================================================
CASES="
case_every_collected_test_is_mapped_or_declared
case_a_collected_test_with_no_context_is_could_not_look
case_the_map_is_deterministic
case_a_missing_input_is_could_not_look
case_an_unknown_subcommand_is_refused
"

echo "== test_impact: the writer of the test-impact map"
for c in $CASES; do
    "$c"
done

echo ""
echo "  ${PASSED} passed, ${FAILED} failed"
drive_finished
[ "$FAILED" = "0" ] || exit 1
exit 0
