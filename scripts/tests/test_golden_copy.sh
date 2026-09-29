#!/usr/bin/env bash
# THIS FILE IS EXECUTED, AND IT IS BASH — not POSIX sh, and not zsh.
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
# drives: apps/ config/ quality/ templates/ manage.py pyproject.toml scripts/archaeology_lib.sh scripts/gate_refuse.sh scripts/tests/fixtures/golden_copy/
# cites: scripts/setup.sh scripts/check.sh scripts/tests/test_golden_face.sh .env
# THE GOLDEN-COPY DRIVE — every noun-verb family verb ships a worked example a
# product COPIES, and this is the instrument that proves the copy works.
#
#   test_golden_copy.sh --verb <verb>   copy the worked example's blocks for <verb>
#   test_golden_copy.sh --all           every family verb, one after another, in one run
#   test_golden_copy.sh [--self]        the drive's own self-case — the default, and
#                                       what the gate runs (a registered drive is
#                                       invoked bare)
#   test_golden_copy.sh --list          the cases, without running them
#
# WHAT A GOLDEN BLOCK IS. The worked example lives on the scaffold noun, `Widget`,
# in `apps/example`. Every block a product copies to adopt a verb — the model's
# adoption, the service pair, both doors, the schema, the tests — is fenced
# `# golden: <verb> begin` … `# golden: <verb> end`, and the copy is the text
# between the fences and NOTHING ELSE. A block that only works beside the
# unfenced code around it is not a block anybody can copy.
#
# THE FENCE NAMES A VERB LIST. `# golden: archive version move begin` opens one
# block for all three verbs at once — the form for a block two or more verbs
# share (the noun's imports, its class line, its detail route), where a stack
# of single-verb lines per verb would cost a marker line per verb per block. A
# case's copy takes a fence when ITS verb is in the list; a block one verb owns
# keeps the one-verb form. Every word in a list must be a verb this drive knows
# (the roads plus the non-road verbs below): a typo'd verb is exit 2 naming the
# file and line, never a block that silently belongs to nobody.
#
# THE VERBS are `core.verbs.ROADS`' keys — read from the table, never typed —
# and two that are NOT roads: `attach` (a noun declaring `attachments`) and
# `import` (an app declaring `importers.py`). A road's copy is proved
# non-vacuous by deleting its last route (step 5); a verb that is not a road
# has no route of its own to delete, so it CARRIES ITS OWN CUT — `import`
# deletes the copy's `gadget-create` (house rule 74's importer clause: an
# import is creates), `attach` drops `tags` from the copy's detail `Out` (the
# attach clause: a noun taking tags answers them). `--all` runs the roads in
# the table's order, then the non-road verbs.
#
# WHAT THE DRIVE DOES with `--verb <verb>`, in a scratch copy of this checkout's
# tracked tree (never in the checkout — a transient app in the tree a gate is
# measuring, or a peer's pytest is collecting, would be an app in both):
#
#   1. collects every `golden: <verb>` block under `apps/example/**`, file by
#      file, and writes each file's blocks to the same relative path in a
#      throwaway product app, `apps/zzz_golden/` — sited OUTSIDE the platform
#      partition's `platform_apps` (re-read from `quality/partition.yaml` at drive
#      time: a product app, as the adopter's would be);
#   2. applies THE ONE RENAME — the noun, `Widget`→`Gadget`, `widget`→`gadget`
#      (which carries `widgets`→`gadgets`) — and RELOCATES the app the blocks name
#      (`apps.example`→`apps.zzz_golden`, and the `example.` label an event name
#      starts with), because a copied block lives in the adopter's app, not in
#      the example's; a `relocated:` line names each moved label and how many
#      times it moved, so a reader sees the relocation rather than trusting it,
#      and each `copied <file> (<n> lines) from <src>:<begin>-<end>, …` line
#      names the source fence of every block, in the order they were joined;
#   2b. checks every fragment LANDS LIVE in the copy: the extractor joins a
#      file's blocks in file order, so a fragment can land after the previous
#      block's `return` — dead code the copied test never reaches. An AST walk
#      over every copied module (the module, every function and class body,
#      every `if`/`for`/`while`/`with`/`try`/`match` body) refuses a statement
#      that follows a `return`/`raise`/`continue`/`break` in the same block,
#      naming the copied `file:line` and the source fence it came from. On the
#      COPY and not the source, because the copy is what a product receives and
#      two fragments that each read fine where they are fenced can land wrong.
#      Cost: one `ast.parse` per copied file. A copied module that does not
#      parse is exit 2 — a copy that does not parse is not a copy that works;
#   3. checks the copy is COPYABLE: the archaeology census's patterns (no queue
#      id, no rung token, no private name) over the copied text;
#   4. `makemigrations zzz_golden`, `manage.py check --tag djb` (rules 17 and 74
#      over `Gadget`, and every other registry rule), and the copied
#      `tests/test_golden_<verb>.py` against a test database of its own — ALL
#      under `DJB_DISABLED_APPS=example`: the example app is optional, so the
#      copy is built in a world where it is not installed, and a fenced block
#      that reaches back into the example by any spelling the relocation missed
#      fails to import rather than passing by luck;
#   5. NON-VACUOUS BY CONSTRUCTION: deletes the copied road's LAST route — the
#      last name the road's own `Road.url_names("gadget")` answers, never a
#      template of this file's (archive: `gadget-restore`; history:
#      `gadget_history-list`) — and expects rule 74 red: a copy the rule
#      cannot tell from a half-built one is a copy nobody proved. A verb that
#      is not a road makes its own cut (above) and expects the same red, naming
#      the route its clause reads;
#   6. drops the app, its migrations and its tables — the scratch tree and the
#      test database both — and prints the cleanup census: no `apps/zzz_golden/`
#      in the checkout, no migration, no database left behind.
#
# A VERB WITH NO FENCED BLOCK IS EXIT 2, never a pass: the example that would be
# copied does not exist yet, and "nothing to copy" is not "the copy works".
#
# `--self` is the drive proving ITSELF, and it is what the gate's selftest leg
# runs: it plants the fixture blocks under `scripts/tests/fixtures/golden_copy/`
# into an EMPTY scratch source — a directory the fixture alone populates, with
# none of `apps/example` in it — and runs the whole cycle over that source.
# THE POPULATION: the self-case runs on a tree whose example app carries a real
# fence, and it must hold there as it held before any fence existed — so its
# world cannot contain the real fence (appending the fixture to a copy of the
# example once gave the copy two `Gadget`s the day the example was fenced).
# An empty source rather than a copy with its fences stripped: stripping is a
# second fence parser that must agree with the first, a malformed or new verb's
# fence it misses is the same collision back, and an empty directory has nothing
# to miss. What the copy of the example used to prove for free — that text
# OUTSIDE a fence is never copied — is planted on purpose: every planted file
# opens with an unfenced decoy line that breaks the copy if it is carried over,
# and the drive asserts the copy does not carry it. It cannot go green
# vacuously — the plant is its own — and it does not wait for the real example.
# The placement step (2b) has its own canary and negative in the same fixture
# tree: `<verb>/services.py` carries a fenced `require_live(...)` after a
# `return`, and a second, CANARY source planted from `<verb>/` as it is must red
# on exactly that line; the BUILD source takes `negative/<verb>/services.py` in
# its place — the clean file the copy actually builds from, on which the step
# must stay silent. The VERB LIST has its own two: `<verb>/models.py` is fenced
# `archive version` (a two-verb fence the archive copy must take) and
# `<verb>/events.py` carries a block fenced for `version` ALONE whose one line
# breaks the copy if it is carried (a list the archive copy must leave); and
# `typo/models.py`, planted into a third scratch source, names a verb no road
# and no case has — the extractor must refuse it, naming the word.
# WHAT THE SELF-CASE DOES NOT PROVE: anything about the real worked example —
# that its fenced blocks are complete, self-sufficient, or copy cleanly. That is
# `--verb <verb>`'s, and only the real case vouches for the example.
#
# Exit 0 every case held · 1 a case failed · 2 could not look (no venv, no
# database, no tar, an unknown verb or flag, a verb with no fenced block).
#
# DOES NOT COVER — declared: whether the worked example is GOOD, only that its
# fenced text is self-sufficient; a block that copies cleanly and teaches the
# wrong shape passes. The face's half is `test_golden_face.sh`'s. A hand edit a
# copy needed beyond the rename and the relocation shows up as a red here —
# which is the finding, not a flake. The placement step sees dead code only
# where it FOLLOWS a terminal statement: a fragment that lands inside an
# unreachable branch (`if False:`), and a fragment whose meaning changes by
# ORDER without dead code (two blocks that must land in one order and land in
# file order), are the copied test's to catch, and nothing else here sees them.
# Nor does it see a fragment after a call that NEVER RETURNS — `assert False`,
# `sys.exit(...)`, any `NoReturn` callee — which is dead code the AST cannot
# tell from a call that comes back: planted, the placement step stays silent.
# A verb list's words are checked against the verbs this drive knows, never
# against whether the block is right for every verb it names — a block fenced
# for a verb it does not belong to is a copy that builds or does not, which is
# the red that verb's own case prints.

set -euo pipefail

cd "$(dirname "$0")/../.."

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_golden_copy: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It carries the only thing keeping this drive's work inside its own" >&2
    echo "   scratch directory. Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh
DRIVE_OPTED_IN_TO_FINISH=1

ROOT=$(pwd -P)
APP=zzz_golden
FIXTURES="$ROOT/scripts/tests/fixtures/golden_copy"
# The self-case's unfenced decoy: a line planted OUTSIDE every fence, which a
# copy that carried it would carry by name.
DECOY="golden-copy-unfenced-decoy"
# The self-case's block fenced for ANOTHER verb alone, which the archive copy
# must leave behind — the verb list's negative half.
OTHER_VERB_DECOY="golden-copy-other-verb-decoy"

PASSED=0
FAILED=0

pass() {
    PASSED=$((PASSED + 1))
    echo "  ok   $*"
}

fail() {
    FAILED=$((FAILED + 1))
    echo "  FAIL $*" >&2
}

MODE=""
VERB=""
case "${1:-}" in
--verb)
    MODE=verb
    VERB="${2:-}"
    [ -n "$VERB" ] || drive_cannot_look "--verb takes the family verb to copy (archive, …)"
    [ "$#" -eq 2 ] || drive_cannot_look "--verb <verb> takes nothing after the verb"
    ;;
--all)
    MODE=all
    [ "$#" -eq 1 ] || drive_cannot_look "--all takes nothing after it"
    ;;
"" | --self)
    MODE=self
    VERB=archive
    [ "$#" -le 1 ] || drive_cannot_look "--self takes nothing after it"
    ;;
--list)
    echo "  case_self_a_two_verb_fence_is_taken_by_the_verb_it_names"
    echo "  case_self_a_block_fenced_for_another_verb_is_not_copied"
    echo "  case_self_a_typo_d_verb_in_a_fence_is_refused"
    echo "  case_duplicate_the_copy_declares_what_a_duplicate_carries"
    echo "  case_merge_the_copy_keeps_its_ledger_and_the_fk_census_is_clean"
    echo "  case_attach_the_copy_without_tags_on_its_detail_reds_rule_74"
    echo "  case_import_the_copy_without_its_create_route_reds_rule_74"
    echo "  case_all_every_verb_in_one_run"
    echo "  case_self_plants_a_fenced_block_and_the_copy_builds_checks_and_passes"
    echo "  case_self_plants_into_an_empty_source_whose_only_fences_are_the_fixture"
    echo "  case_self_text_outside_a_fence_is_not_copied"
    echo "  case_the_copy_without_its_last_route_reds_rule_74"
    echo "  case_the_cleanup_census_leaves_nothing"
    echo "  case_a_verb_with_no_fenced_block_is_exit_2"
    echo "  case_the_copy_builds_where_the_example_is_not_installed"
    echo "  case_self_a_fragment_after_return_reds_placement"
    echo "  case_self_the_clean_fixture_places_every_fragment_live"
    exit 0
    ;;
*)
    # A mistyped flag is never a silently different run.
    echo "!! unknown argument '${1:-}': test_golden_copy.sh takes nothing (the self-case), --self, --verb <verb>, --all or --list" >&2
    exit 2
    ;;
esac

PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || drive_cannot_look "no virtualenv at .venv — run ./scripts/setup.sh; the copy is built and checked with this checkout's own interpreter"
command -v tar >/dev/null 2>&1 || drive_cannot_look "no tar on PATH — the scratch tree is copied with it"

# The family's verbs are `core.verbs.ROADS`' keys, and a road's route names are
# what its OWN `Road.url_names(noun)` answers — read here, by importing the
# table, so an unknown verb is refused before anything is copied and no step
# below rebuilds a url_name from a template of its own. (A road's route is a
# bare verb or a `{noun}`-shaped name; a hand template that knew only the first
# shape asked the history copy for a route no road names.) The noun is the
# copy's, `gadget` — the one rename applied to the example's `widget`. One line
# per road: `road <verb> <url_name>…`, in the table's order.
ROAD_TABLE=$(
    export DJANGO_SETTINGS_MODULE=config.settings.test
    export DJB_DISABLED_APPS=example
    "$PY" - <<'PY'
import django

django.setup()
from apps.core.verbs import ROADS

for verb, road in ROADS.items():
    print("road", verb, " ".join(road.url_names("gadget")))
PY
) || drive_cannot_look "apps/core/verbs.py's ROADS table would not import"
ROAD_VERBS=$(awk '$1 == "road" { printf "%s ", $2 }' <<<"$ROAD_TABLE")
ROAD_VERBS="${ROAD_VERBS% }"
[ -n "$ROAD_VERBS" ] || drive_cannot_look "apps/core/verbs.py's ROADS table names no road"
# The verbs that are NOT roads — each carries its own cut (the header says
# which). This list and the table above are the whole vocabulary a fence may
# name; `--all` runs them in this order.
NON_ROAD_VERBS="attach import"
KNOWN_VERBS="$ROAD_VERBS $NON_ROAD_VERBS"

# golden_road — for $VERB: ROAD_URL_NAMES (what the step-5 cut reads), and
# LAST_URL_NAME, the route the cut deletes (empty for `attach`, whose cut is a
# field). An unknown verb is could-not-look.
golden_road() {
    local line
    case "$VERB" in
    import)
        ROAD_URL_NAMES="not a road — its cut is gadget-create (the importer clause)"
        LAST_URL_NAME="gadget-create"
        CUT_SAYS="$LAST_URL_NAME"
        return 0
        ;;
    attach)
        ROAD_URL_NAMES="not a road — its cut is tags on gadget-detail's Out (the attach clause)"
        LAST_URL_NAME=""
        CUT_SAYS="tags on its detail Out"
        return 0
        ;;
    esac
    line=$(awk -v verb="$VERB" '$1 == "road" && $2 == verb' <<<"$ROAD_TABLE")
    [ -n "$line" ] ||
        drive_cannot_look "'${VERB}' is not a family verb: apps/core/verbs.py's ROADS has no road by that name, and it is none of the non-road verbs (${NON_ROAD_VERBS}) (or the table would not import)"
    ROAD_URL_NAMES="${line#road "$VERB" }"
    [ -n "$ROAD_URL_NAMES" ] && [ "$ROAD_URL_NAMES" != "$line" ] ||
        drive_cannot_look "the '${VERB}' road names no route — there is no last route to delete"
    LAST_URL_NAME="${ROAD_URL_NAMES##* }"
    CUT_SAYS="$LAST_URL_NAME"
}
if [ "$MODE" != "all" ]; then
    golden_road
fi

# The throwaway app is a PRODUCT app: re-derived here, never assumed.
if grep -Eq "^[[:space:]]*-[[:space:]]*${APP}[[:space:]]*$" quality/partition.yaml; then
    drive_cannot_look "quality/partition.yaml lists '${APP}' in platform_apps — the copy must land in a product app, outside the partition"
fi

# The database the copy's test runs against: its own, named here, dropped at exit.
GOLDEN_DB="djb_golden_$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"

golden_env() {
    export DJANGO_SETTINGS_MODULE=config.settings.test
    export DATABASE_NAME="$GOLDEN_DB"
    export DATABASE_URL=""
    # The worked example is OUT of the world the copy is proved in: it is the one
    # optional app (`ExampleConfig.optional`), and a copy that only built because
    # the original sat beside it is not a copy a product can make.
    export DJB_DISABLED_APPS=example
}

# Every database whose name carries this run's, as `name` lines, or exit 2.
golden_databases() {
    (
        golden_env
        cd "$ROOT"
        "$PY" - "$GOLDEN_DB" <<'PY'
import sys

import django

django.setup()
from django.db import connection

with connection._nodb_cursor() as cursor:
    cursor.execute("SELECT datname FROM pg_database WHERE datname LIKE %s", [f"%{sys.argv[1]}%"])
    for (name,) in cursor.fetchall():
        print(name)
PY
    )
}

golden_drop_databases() {
    (
        golden_env
        cd "$ROOT"
        "$PY" - "$GOLDEN_DB" <<'PY' || true
import sys

import django

django.setup()
from django.db import connection

with connection._nodb_cursor() as cursor:
    cursor.execute("SELECT datname FROM pg_database WHERE datname LIKE %s", [f"%{sys.argv[1]}%"])
    for (name,) in cursor.fetchall():
        cursor.execute(f'DROP DATABASE IF EXISTS "{name}"')
PY
    )
}

golden_databases >/dev/null ||
    drive_cannot_look "no database answers — the copy's own test needs the compose Postgres (docker compose up -d db)"
drive_at_exit golden_drop_databases

# golden_extract <source apps/example> <destination app dir> <label>
# Exit 0 copied · 3 no fenced block for the verb · 2 a malformed fence.
# <label> prefixes the source path each `copied` line names its fences by
# (`apps/example/` for the real example, empty for a planted source), and that
# line — `copied <file> (<n> lines) from <src>:<begin>-<end>, …`, one span per
# block in the order the blocks were joined — is what the placement step maps a
# copied line back to its source fence with.
golden_extract() {
    "$PY" - "$1" "$2" "$VERB" "$APP" "${3:-}" "$KNOWN_VERBS" <<'PY'
import pathlib
import re
import sys

source, destination, verb, app = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3], sys.argv[4]
label = sys.argv[5]
known = set(sys.argv[6].split())
# A fence names a LIST of verbs: `# golden: archive version begin` is a begin
# for each verb it names. A line is this verb's fence when the verb is in it.
fence = re.compile(r"^\s*#\s*golden:\s*([a-z][a-z ]*?)\s+(begin|end)\s*$")


def fence_of(path: pathlib.Path, number: int, line: str) -> str | None:
    """`begin` / `end` when the line is a fence naming this verb; refuses an unknown word."""
    match = fence.match(line)
    if match is None:
        return None
    named = match.group(1).split()
    unknown = sorted(set(named) - known)
    if unknown:
        sys.exit(
            f"!! {path.relative_to(source)}:{number}: `golden: {match.group(1)} {match.group(2)}` "
            f"names {', '.join(unknown)}, which is no verb this drive knows ({' '.join(sorted(known))})"
        )
    return match.group(2) if verb in named else None

# THE ONE RENAME, and the relocation the copy's new home needs.
RENAMES = (
    ("apps.example", f"apps.{app}"),
    ("apps/example/", f"apps/{app}/"),
    ('"example.', f'"{app}.'),
    ("Widget", "Gadget"),
    ("widget", "gadget"),
)

copied = {}
spans = {}
moved = {old: 0 for old, _ in RENAMES}
for path in sorted(source.rglob("*.py")):
    if "__pycache__" in path.parts:
        continue
    blocks, fences, inside, start = [], [], None, 0
    for number, line in enumerate(path.read_text().splitlines(), 1):
        kind = fence_of(path, number, line)
        if kind == "begin":
            if inside is not None:
                sys.exit(f"!! {path.relative_to(source)}:{number}: a `golden: {verb} begin` inside another — fences do not nest")
            inside, start = [], number
        elif kind == "end":
            if inside is None:
                sys.exit(f"!! {path.relative_to(source)}:{number}: `golden: {verb} end` with no begin")
            blocks.append("\n".join(inside))
            fences.append((start, number))
            inside = None
        elif inside is not None:
            inside.append(line)
    if inside is not None:
        sys.exit(f"!! {path.relative_to(source)}:{start}: `golden: {verb} begin` never ends")
    if blocks:
        text = "\n\n\n".join(blocks) + "\n"
        for old, new in RENAMES:
            moved[old] += text.count(old)
            text = text.replace(old, new)
        copied[path.relative_to(source)] = text
        spans[path.relative_to(source)] = ", ".join(
            f"{label}{path.relative_to(source)}:{b}-{e}" for b, e in fences
        )

if not copied:
    sys.exit(3)

# Every moved label, said: the app's dotted and slashed names and the event
# names' label (the relocation), then the noun (the one rename).
print(
    "relocated: "
    + " · ".join(f"{old} → {new} ×{moved[old]}" for old, new in RENAMES)
)

destination.mkdir(parents=True)
(destination / "__init__.py").write_text("")
(destination / "apps.py").write_text(
    "from django.apps import AppConfig\n\n\n"
    f"class {''.join(part.title() for part in app.split('_'))}Config(AppConfig):\n"
    f'    name = "apps.{app}"\n'
    '    depends_on: tuple[str, ...] = ("core", "accounts", "events")\n'
)
(destination / "migrations").mkdir()
(destination / "migrations" / "__init__.py").write_text("")
for relative, text in copied.items():
    target = destination / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    init = target.parent / "__init__.py"
    if not init.exists():
        init.write_text("")
    target.write_text(text)
    print(f"copied {relative} ({text.count(chr(10))} lines) from {spans[relative]}")
PY
}

# golden_placement <copied app dir> <golden_extract's output>
# Exit 0 every fragment lands live · 1 a fragment follows a terminal statement ·
# 2 a copied module does not parse, or the `copied` lines cannot be mapped.
#
# THE CHECK RUNS ON THE COPY, NOT THE SOURCE: the extractor joins a file's
# blocks in file order (`"\n\n\n".join(blocks)`), so a fragment that reads fine
# where it is fenced can land, in the copy, after the previous block's `return`
# — dead code the copied test never reaches, and nothing else here would say
# so. One `ast.parse` per copied module; every statement list the tree holds
# (the module, each function and class body, each `if`/`for`/`while`/`with`/
# `try`/`match` body, `else`, `finally` and handler) is read, and a statement
# that follows a `return`/`raise`/`continue`/`break` in the same list is a
# finding naming the copied `file:line` and the source fence it came from.
golden_placement() {
    "$PY" - "$1" "$2" "$APP" <<'PY'
import ast
import pathlib
import re
import sys

root, report, app = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
line_re = re.compile(r"^copied (\S+) \((\d+) lines\) from (.+)$")
span_re = re.compile(r"^(\S+):(\d+)-(\d+)$")
TERMINAL = {ast.Return: "return", ast.Raise: "raise", ast.Continue: "continue", ast.Break: "break"}

walked, findings = 0, []
for entry in report.splitlines():
    match = line_re.match(entry)
    if match is None:
        continue
    relative, total, spans = match.group(1), int(match.group(2)), []
    for span in match.group(3).split(", "):
        parsed = span_re.match(span)
        if parsed is None:
            print(f"!! the copied line for {relative} names a fence span it cannot read: {span!r}")
            sys.exit(2)
        spans.append((parsed.group(1), int(parsed.group(2)), int(parsed.group(3))))
    # Where each block starts in the copy: blocks are joined by two blank lines,
    # and an empty block still occupies one (empty) line.
    starts, at = [], 1
    for _, begin, end in spans:
        starts.append(at)
        at += max(end - begin - 1, 1) + 2
    if at - 2 - 1 != total:
        print(f"!! {relative}: the fence spans account for {at - 3} lines, the copy has {total}")
        sys.exit(2)
    target = root / relative
    try:
        text = target.read_text()
        tree = ast.parse(text, filename=str(target))
    except (OSError, SyntaxError, ValueError) as error:
        print(f"!! apps/{app}/{relative} does not parse — a copy that does not parse is not a copy that works: {error}")
        sys.exit(2)
    walked += 1
    lines = text.splitlines()

    def origin(number: int) -> str:
        for (source, begin, end), start in reversed(list(zip(spans, starts))):
            if number >= start:
                return f"from {source}:{begin}-{end} (its line {begin + 1 + number - start})"
        return "from no fence"

    for node in ast.walk(tree):
        for _, value in ast.iter_fields(node):
            if not (isinstance(value, list) and value and all(isinstance(item, ast.stmt) for item in value)):
                continue
            for before, statement in zip(value, value[1:]):
                word = TERMINAL.get(type(before))
                if word is None:
                    continue
                findings.append(
                    (
                        relative,
                        statement.lineno,
                        f"dead: apps/{app}/{relative}:{statement.lineno} · {origin(statement.lineno)} · "
                        f"follows `{word}` at :{before.lineno} in the same block — a fenced fragment after "
                        f"`{word}` in the same block is dead code in the copy: "
                        f"{lines[statement.lineno - 1].strip()}",
                    )
                )
                break

if walked == 0:
    print("!! no `copied` line to walk — the placement step was handed no copy")
    sys.exit(2)
for _, _, finding in sorted(findings):
    print(finding)
if findings:
    sys.exit(1)
print(f"walked {walked} copied module(s) with ast.parse; no fragment follows a return/raise/continue/break")
PY
}

# golden_cycle <source apps/example> <label> — the whole copy → check → drop cycle.
golden_cycle() {
    local source="$1" label="${2:-}" world rc log copied placed
    world=$(mktemp -d "${TMPDIR:-/tmp}/djb-golden.XXXXXX")
    drive_require_scratch world "$world"
    drive_at_exit "rm -rf '$world'"
    log="$world.log"
    drive_at_exit "rm -f '$log'"

    git ls-files -z | tar --null -T - -cf - | tar -xf - -C "$world"
    [ ! -f .env ] || cp .env "$world/.env"

    set +e
    copied=$(golden_extract "$source" "$world/apps/$APP" "$label" 2>&1)
    rc=$?
    set -e
    if [ "$rc" = "3" ]; then
        echo "!! test_golden_copy: no \`golden: ${VERB}\` block in apps/example — the worked example" >&2
        echo "   that a product would copy for this verb has not been fenced yet, and nothing to" >&2
        echo "   copy is not a copy that works." >&2
        exit 2
    fi
    [ "$rc" = "0" ] || drive_cannot_look "the fences could not be read: ${copied}"
    echo "$copied" | grep -v '^relocated: ' | sed 's/^/       /'
    echo "$copied" | grep '^relocated: ' || true

    # 2b · placement: every fenced fragment lands live IN THE COPY — none follows
    # a return/raise/continue/break in the same block (golden_placement's comment
    # says why the copy and not the source). A copied module that does not parse
    # is could-not-look.
    set +e
    placed=$(golden_placement "$world/apps/$APP" "$copied" 2>&1)
    rc=$?
    set -e
    case "$rc" in
    0)
        if [ "$MODE" = "self" ]; then
            pass "case_self_the_clean_fixture_places_every_fragment_live: ${placed}"
        else
            echo "       placement: ${placed}"
        fi
        ;;
    1)
        fail "a fenced fragment lands after a terminal statement in the copy:"
        echo "$placed" | sed 's/^/       /' >&2
        ;;
    *) drive_cannot_look "the placement walk could not read the copy: ${placed}" ;;
    esac
    [ -f "$world/apps/$APP/tests/test_golden_${VERB}.py" ] ||
        fail "the copy carries no tests/test_golden_${VERB}.py — a worked example ships the test that proves it"
    if [ "$MODE" = "self" ]; then
        if grep -rq "$DECOY" "$world/apps/$APP"; then
            fail "the copy carries the unfenced decoy — text outside a fence was copied"
        else
            pass "the copy carries none of the text planted outside the fences (the decoy stayed behind)"
        fi
        if grep -rq "$OTHER_VERB_DECOY" "$world/apps/$APP"; then
            fail "case_self_a_block_fenced_for_another_verb_is_not_copied: the ${VERB} copy carries a block fenced for another verb alone"
        elif grep -rq "$OTHER_VERB_DECOY" "$source"; then
            pass "case_self_a_block_fenced_for_another_verb_is_not_copied: the block fenced \`version\` alone stayed behind"
        else
            fail "case_self_a_block_fenced_for_another_verb_is_not_copied: the planted source carries no block fenced for another verb — the case asserted nothing"
        fi
        if grep -rEq "golden: ${VERB} [a-z]+ begin" "$source" && grep -rq "golden-copy-two-verb-fence" "$world/apps/$APP"; then
            pass "case_self_a_two_verb_fence_is_taken_by_the_verb_it_names: a \`${VERB} version\` fence was copied into the ${VERB} copy"
        else
            fail "case_self_a_two_verb_fence_is_taken_by_the_verb_it_names: no two-verb fence in the planted source, or its block is not in the copy"
        fi
    fi

    # 3 · copyable: the archaeology census's own patterns, over the copied text.
    set +e
    (
        . scripts/archaeology_lib.sh
        cd "$world"
        archaeology_scan_files $(find "apps/$APP" -name '*.py' -not -path '*/migrations/*')
    ) >"$log" 2>&1
    rc=$?
    set -e
    if [ "$rc" = "0" ] && ! grep -q "archaeology-census:" "$log"; then
        pass "the copied blocks are copyable (the archaeology census reads nothing in them)"
    else
        fail "the copied blocks carry what a product must not inherit:"
        sed 's/^/       /' "$log" >&2
    fi

    # 4 · build, check, prove — in the scratch world, against its own database,
    # with the example app NOT installed (asked of the world, not assumed).
    set +e
    (golden_env && cd "$world" && "$PY" -c "import django, sys
django.setup()
from django.apps import apps
sys.exit(3 if apps.is_installed('apps.example') else 0 if apps.is_installed('apps.$APP') else 4)") >"$log" 2>&1
    rc=$?
    set -e
    if [ "$rc" = "0" ]; then
        pass "the copy's world has apps.$APP installed and apps.example NOT (DJB_DISABLED_APPS=example)"
    else
        fail "the copy's world is not the one it claims (exit $rc: 3 the example is installed, 4 the copy is not):"
        sed 's/^/       /' "$log" >&2
        return 0
    fi

    set +e
    (golden_env && cd "$world" && "$PY" manage.py makemigrations "$APP") >"$log" 2>&1
    rc=$?
    set -e
    if [ "$rc" = "0" ] && [ -f "$world/apps/$APP/migrations/0001_initial.py" ]; then
        pass "makemigrations $APP made 0001_initial"
    else
        fail "makemigrations $APP (exit $rc):"
        sed 's/^/       /' "$log" >&2
        return 0
    fi

    set +e
    (golden_env && cd "$world" && "$PY" manage.py check --tag djb) >"$log" 2>&1
    rc=$?
    set -e
    if [ "$rc" = "0" ]; then
        pass "manage.py check --tag djb is clean with Gadget in the registry (rules 17 and 74 over the copy)"
    else
        fail "manage.py check --tag djb over the copy (exit $rc):"
        sed 's/^/       /' "$log" >&2
    fi

    set +e
    (golden_env && cd "$world" &&
        "$PY" -m pytest "apps/$APP/tests/test_golden_${VERB}.py" -q -p no:randomly -p no:cacheprovider) >"$log" 2>&1
    rc=$?
    set -e
    if [ "$rc" = "0" ]; then
        pass "the copied test_golden_${VERB}.py passes on Gadget ($(grep -Eo '[0-9]+ passed' "$log" | tail -1))"
    else
        fail "the copied test_golden_${VERB}.py (exit $rc):"
        tail -60 "$log" | sed 's/^/       /' >&2
    fi

    # The verb's own case: what its copy must declare, beyond building.
    golden_case "$world/apps/$APP"

    # 5 · non-vacuous: the road's last route deleted from the copy reds rule 74 —
    # or, for a verb that is not a road, the verb's own cut (`golden_cut`).
    local named
    set +e
    named=$(golden_cut "$world/apps/$APP" 2>&1)
    rc=$?
    (golden_env && cd "$world" && "$PY" manage.py check --tag djb) >"$log" 2>&1
    local checked=$?
    set -e
    if [ "$rc" = "0" ] && [ "$checked" = "1" ] && grep -q "djb.E074" "$log" &&
        grep -q "${named}" "$log"; then
        pass "the copy without ${CUT_SAYS} reds rule 74 (djb.E074 names ${named})"
    else
        fail "the copy without ${CUT_SAYS} did not red rule 74 (edit exit $rc: ${named}; check exit $checked):"
        # `|| true`, legibility only: a log with no matching line is grep's exit
        # 1, and under pipefail that ended the run here — before the drop, the
        # census and the summary. The `fail` above already set the exit.
        grep -E "djb\.|Error|error" "$log" | head -20 | sed 's/^/       /' >&2 || true
    fi

    # 6 · drop: the scratch world and every database this run made.
    rm -rf "$world" "$log"
    golden_drop_databases
}

# golden_cut <copied app dir> — step 5's edit for $VERB; prints the name the
# rule-74 red must carry. A road (and `import`, whose clause reads the create
# route) deletes the one decorator naming its route; `attach` drops `tags` from
# the copy's detail `Out`, the one field the attach clause reads. It runs in a
# command substitution, so what the pass line says was cut (`CUT_SAYS`) is set
# by `golden_road`, in the caller's shell.
golden_cut() {
    local app_dir="$1"
    if [ "$VERB" = "attach" ]; then
        "$PY" - "$app_dir/schemas.py" <<'PY' || return 1
import ast
import pathlib
import sys

# The `tags` field of the copy's DETAIL `Out` — the whole statement, however
# many lines its `Field(...)` spans — and nothing else.
path = pathlib.Path(sys.argv[1])
text = path.read_text()
found = [
    statement
    for node in ast.walk(ast.parse(text))
    if isinstance(node, ast.ClassDef) and node.name.endswith("DetailOut")
    for statement in node.body
    if isinstance(statement, ast.AnnAssign)
    and isinstance(statement.target, ast.Name)
    and statement.target.id == "tags"
]
if len(found) != 1:
    sys.exit(f"expected exactly one `tags` field on the copy's detail Out; found {len(found)}")
lines = text.splitlines(keepends=True)
start, end = found[0].lineno, found[0].end_lineno or found[0].lineno
path.write_text("".join(lines[: start - 1] + lines[end:]))
PY
        echo "gadget-detail"
        return 0
    fi
    "$PY" - "$app_dir/api.py" "${LAST_URL_NAME}" <<'PY' || return 1
import pathlib
import sys

path, url_name = pathlib.Path(sys.argv[1]), sys.argv[2]
lines = path.read_text().splitlines(keepends=True)
kept = [line for line in lines if f'url_name="{url_name}"' not in line]
if len(kept) != len(lines) - 1:
    sys.exit(f"expected exactly one decorator naming {url_name}; found {len(lines) - len(kept)}")
path.write_text("".join(kept))
PY
    echo "${LAST_URL_NAME}"
}

# golden_case <copied app dir> — what each verb's copy must DECLARE, beyond
# building, checking and passing its own test. A verb with nothing to add here
# adds nothing: the four cycle steps are the whole case.
golden_case() {
    local app_dir="$1"
    case "$VERB" in
    duplicate)
        if grep -q "duplicate = Duplicate(" "$app_dir/models.py"; then
            pass "case_duplicate: the copy declares what a duplicate carries (Gadget.duplicate)"
        else
            fail "case_duplicate: the copy's models.py declares no \`duplicate = Duplicate(...)\`"
        fi
        ;;
    merge)
        # The ledger the copy carries is kept on the loser, said by name — and
        # step 4's `check --tag djb` is rule 74's FK census over the copy.
        if grep -q "merge_keeps" "$app_dir/models.py" && grep -q '"entries"' "$app_dir/models.py" &&
            grep -q "class GadgetEntry" "$app_dir/models.py"; then
            pass "case_merge: the copy declares merge_keeps for its copied ledger (GadgetEntry.entries); the FK census is step 4's check"
        else
            fail "case_merge: the copy carries its ledger without declaring it in merge_keeps"
        fi
        ;;
    attach)
        if grep -Eq "attachments: ClassVar\[tuple\[str, \.\.\.\]\] = \(" "$app_dir/models.py"; then
            pass "case_attach: the copy declares its attachments"
        else
            fail "case_attach: the copy's models.py declares no attachments"
        fi
        ;;
    import)
        if [ -f "$app_dir/importers.py" ] && grep -q "IMPORTERS" "$app_dir/importers.py"; then
            pass "case_import: the copy carries importers.py and its IMPORTERS"
        else
            fail "case_import: the copy carries no importers.py declaring IMPORTERS"
        fi
        ;;
    esac
}

# golden_plant <empty scratch source> <build | canary> — each fixture under
# `$VERB/` written to the same relative path, behind one unfenced decoy line (text
# outside a fence, which the copy must leave behind); nothing of apps/example is
# in the source, so the real fence cannot be either. For `build`, a file under
# `negative/$VERB/` replaces the fixture at its path.
golden_plant() {
    local source="$1" kind="$2" fixture relative from
    while IFS= read -r fixture; do
        relative="${fixture#"$FIXTURES/$VERB/"}"
        from="$fixture"
        if [ "$kind" = "build" ] && [ -f "$FIXTURES/negative/$VERB/$relative" ]; then
            from="$FIXTURES/negative/$VERB/$relative"
        fi
        mkdir -p "$(dirname "$source/$relative")"
        {
            echo "raise ImportError(\"${DECOY}: text outside a fence was copied\")"
            echo
            cat "$from"
        } >"$source/$relative"
    done < <(find "$FIXTURES/$VERB" -name '*.py' | sort)
}

# golden_canary_case <canary source> — the placement step's own canary: the
# canary source's copy must red, naming the copied services.py line that follows
# a `return` and the source fence it came from — exactly one such line.
golden_canary_case() {
    local source="$1" scratch out placed rc
    scratch=$(mktemp -d "${TMPDIR:-/tmp}/djb-golden-canary.XXXXXX")
    drive_require_scratch scratch "$scratch"
    drive_at_exit "rm -rf '$scratch'"
    set +e
    out=$(golden_extract "$source" "$scratch/apps/$APP" "" 2>&1)
    rc=$?
    set -e
    [ "$rc" = "0" ] || drive_cannot_look "the canary's fences could not be read (exit $rc): ${out}"
    set +e
    placed=$(golden_placement "$scratch/apps/$APP" "$out" 2>&1)
    rc=$?
    set -e
    if [ "$rc" = "1" ] && [ "$(grep -c '^dead: ' <<<"$placed")" = "1" ] &&
        grep -Eq "^dead: apps/${APP}/services\.py:[0-9]+ · from services\.py:[0-9]+-[0-9]+ .*require_live\(" <<<"$placed"; then
        pass "case_self_a_fragment_after_return_reds_placement: the canary's copy reds — ${placed#dead: }"
    else
        fail "case_self_a_fragment_after_return_reds_placement: the canary's copy did not red the placement step on its one dead line (exit $rc):"
        echo "$placed" | sed 's/^/       /' >&2
    fi
    rm -rf "$scratch"
}

# golden_typo_case — a fence naming a verb no road and no case has is refused by
# the extractor, naming the word: `typo/` planted into its own scratch source.
golden_typo_case() {
    local source scratch out rc
    source=$(mktemp -d "${TMPDIR:-/tmp}/djb-golden-typo-src.XXXXXX")
    drive_require_scratch source "$source"
    drive_at_exit "rm -rf '$source'"
    scratch=$(mktemp -d "${TMPDIR:-/tmp}/djb-golden-typo.XXXXXX")
    drive_require_scratch scratch "$scratch"
    drive_at_exit "rm -rf '$scratch'"
    [ -f "$FIXTURES/typo/models.py" ] || drive_cannot_look "no typo fixture at scripts/tests/fixtures/golden_copy/typo/models.py"
    cp "$FIXTURES/typo/models.py" "$source/models.py"
    set +e
    out=$(golden_extract "$source" "$scratch/apps/$APP" "" 2>&1)
    rc=$?
    set -e
    if [ "$rc" != "0" ] && [ "$rc" != "3" ] && grep -q "verison" <<<"$out" &&
        grep -q "no verb this drive knows" <<<"$out"; then
        pass "case_self_a_typo_d_verb_in_a_fence_is_refused: ${out#!! }"
    else
        fail "case_self_a_typo_d_verb_in_a_fence_is_refused: the extractor did not refuse a fence naming \`verison\` (exit $rc):"
        echo "$out" | sed 's/^/       /' >&2
    fi
    rm -rf "$source" "$scratch"
}

golden_census() {
    local left
    if [ ! -e "$ROOT/apps/$APP" ]; then
        pass "census: no apps/$APP in the checkout"
    else
        fail "census: apps/$APP exists in the checkout after the drive"
    fi
    left=$(git status --porcelain --untracked-files=all -- apps | grep -c "$APP" || true)
    if [ "$left" = "0" ]; then
        pass "census: no $APP migration or module anywhere under apps/"
    else
        fail "census: $left path(s) under apps/ still name $APP"
    fi
    left=$(golden_databases | wc -l | tr -d ' ')
    if [ "$left" = "0" ]; then
        pass "census: no database (and so no table) named for this run's $GOLDEN_DB remains"
    else
        fail "census: $left database(s) named for $GOLDEN_DB remain"
    fi
}

if [ "$MODE" = "all" ]; then
    echo "test_golden_copy: --all (${KNOWN_VERBS}) · app ${APP} · database ${GOLDEN_DB}"
else
    echo "test_golden_copy: --${MODE} ${VERB} (road: ${ROAD_URL_NAMES}) · app ${APP} · database ${GOLDEN_DB}"
fi

case "$MODE" in
verb)
    golden_cycle "$ROOT/apps/example" "apps/example/"
    ;;
all)
    # Every verb, one cycle each, in one run: the complete worked example. A
    # verb whose cycle fails is counted and the next one still runs; a verb with
    # no fenced block is exit 2 as it is under `--verb`, because nothing to copy
    # is not a copy that works.
    ALL_RAN=""
    for VERB in $KNOWN_VERBS; do
        golden_road
        echo "test_golden_copy: --all · ${VERB} (road: ${ROAD_URL_NAMES})"
        golden_cycle "$ROOT/apps/example" "apps/example/"
        ALL_RAN="${ALL_RAN} ${VERB}"
    done
    pass "case_all_every_verb_in_one_run: ran${ALL_RAN} — $(wc -w <<<"$ALL_RAN" | tr -d ' ') verb(s)"
    ;;
self)
    [ -d "$FIXTURES/$VERB" ] || drive_cannot_look "no self-case fixtures at scripts/tests/fixtures/golden_copy/$VERB"
    # TWO PLANTS, from one fixture tree. The CANARY source takes every file under
    # `$VERB/` as it is — its `services.py` carries a fenced `require_live(...)`
    # after a `return`, which the placement step must red on. The BUILD source
    # takes the same files with each `negative/$VERB/<path>` in that path's
    # place — the clean negative the copy actually builds from, and the one the
    # placement step must stay silent on.
    SOURCE=$(mktemp -d "${TMPDIR:-/tmp}/djb-golden-src.XXXXXX")
    drive_require_scratch SOURCE "$SOURCE"
    drive_at_exit "rm -rf '$SOURCE'"
    CANARY=$(mktemp -d "${TMPDIR:-/tmp}/djb-golden-canary-src.XXXXXX")
    drive_require_scratch CANARY "$CANARY"
    drive_at_exit "rm -rf '$CANARY'"
    golden_plant "$SOURCE" build
    golden_plant "$CANARY" canary
    PLANTED=$(find "$FIXTURES/$VERB" -name '*.py' | wc -l | tr -d ' ')
    NEGATIVES=$(cd "$FIXTURES" && find "negative/$VERB" -name '*.py' 2>/dev/null | sort | tr '\n' ' ')
    [ "$PLANTED" != "0" ] || drive_cannot_look "the self-case planted no fenced block"
    [ -n "$NEGATIVES" ] || drive_cannot_look "no clean negative under scripts/tests/fixtures/golden_copy/negative/$VERB — the build would copy the placement canary"
    # A fence line naming this verb anywhere in its list.
    OPENS="golden:( [a-z]+)* ${VERB}( [a-z]+)* begin"
    FENCED=$(grep -rlE "$OPENS" "$SOURCE" | wc -l | tr -d ' ')
    CANARY_FENCED=$(grep -rlE "$OPENS" "$CANARY" | wc -l | tr -d ' ')
    REAL=$(grep -rlE "$OPENS" apps/example | wc -l | tr -d ' ')
    if [ "$FENCED" = "$PLANTED" ] && [ "$CANARY_FENCED" = "$PLANTED" ]; then
        pass "self-case: planted ${PLANTED} fenced fixture file(s) into each of two empty scratch sources — the only fences in them (apps/example carries ${REAL} real one(s), none of them here): the BUILD source with ${NEGATIVES% } in its path's place (the clean negative the copy builds from), the CANARY source with ${VERB}/ as it is (the placement case's)"
    else
        fail "self-case: the scratch sources carry ${FENCED} (build) and ${CANARY_FENCED} (canary) fenced file(s) for ${PLANTED} planted — something besides the fixture is in them"
    fi
    golden_canary_case "$CANARY"
    golden_typo_case
    golden_cycle "$SOURCE"
    ;;
esac
golden_census

echo "test_golden_copy: ${PASSED} passed · ${FAILED} failed"
drive_finished
[ "$FAILED" = "0" ] || exit 1
exit 0
