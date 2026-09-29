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
# drives: frontend/ quality/ docs/product/design/ scripts/archaeology_lib.sh scripts/gate_refuse.sh
# cites: scripts/tests/test_golden_copy.sh scripts/check.sh
# THE GOLDEN-FACE DRIVE — the face half of the golden examples: every block of
# the worked face a product COPIES to draw a family verb is proved to copy.
#
#   test_golden_face.sh --verb <verb>   copy the worked face's blocks for <verb>
#   test_golden_face.sh --negative      the drive's own negative (below)
#   test_golden_face.sh [--all]         every verb's case, then the negative —
#                                       the default, and what the gate runs (a
#                                       registered drive is invoked bare)
#   test_golden_face.sh --list          the cases, without running them
#
# WHAT A GOLDEN BLOCK IS. The worked face lives on the scaffold noun, `Widget`,
# in `frontend/src/screens/widget/` and its words in `frontend/src/copy/widget.ts`.
# Every block a product copies is fenced `// golden: <verb> begin` … `end`
# (`/* … */` in a stylesheet, `{/* … */}` inside JSX), and the face's base —
# the list and the record with no family verb on them — is fenced `face`. The
# copy for a verb is the face's base AND the verb's blocks, and nothing else: a
# line inside ANOTHER verb's fence is left behind even where it sits inside the
# base (that is what lets a product take one verb and not the others); a line
# fenced for two verbs (stacked, one fence line per verb) goes with either —
# the OR form. A JOINT fence, `// golden: bulk+merge begin`, holds a block two
# verbs own TOGETHER (the selection bar's Merge needs the bar AND the
# confirm): it goes only with a copy that holds every verb it lists — the AND
# form — so each single verb's case leaves it behind and `--all`'s joint case
# (every verb at once) takes it. A joint list names two or more distinct
# family verbs, or it is exit 2.
#
# WHAT THE DRIVE DOES with `--verb <verb>`, in a scratch world copied from this
# checkout's tracked `frontend/`, `quality/` and the pattern book (never in the
# checkout — a planted face in the tree a gate measures would be a face every
# census reads):
#
#   1. collects the base's and the verb's blocks from every fenced file under
#      the worked face and its copy module, applies THE ONE RENAME
#      (`Widget`→`Gadget`, `widget`→`gadget`, `WIDGET`→`GADGET`, which carries
#      `widgets`→`gadgets`), and writes each file to the renamed path in the
#      world — `screens/gadget/`, `copy/gadget.ts` — naming each file it copied
#      and how many lines;
#   2. plants THE WIRE the copy is proved against: the worked noun's schemas
#      and its list, detail and THIS verb's doors, renamed the same way, in the
#      world's `frontend/openapi.json` (the client's types are generated once,
#      from every verb's doors, by the pinned `openapi-typescript`) — so the
#      copy meets a backend that serves exactly the verb it adopted;
#   3. checks the copy is COPYABLE: the archaeology census's patterns (no queue
#      id, no rung token, no private name) over the copied text;
#   4. runs house rules 77-80's runners in the world (the road equals the wire
#      both ways; the acts constructed; one word per verb; the table the book's)
#      and wants no finding; type-checks the world's client (`tsc --noEmit`) —
#      the copy compiles on its own; and runs the verb face census over it,
#      which must name the `gadget` face (a census that never saw the copy has
#      not measured it).
#
# WHAT THIS DRIVE DOES NOT JUDGE: THE REAL FACE'S FINDINGS. The world holds the
# worked face beside its copy, so the runners and `tsc` also report on
# `screens/widget/` and `copy/widget.ts`. Those are the GATE's to judge — house
# rule 77's ratchet row records them, the fe leg type-checks the tree — and a
# copy drive that judged the whole `frontend/` would be a second gate with a
# stricter opinion. So a finding or a `tsc` error whose path is on the worked
# face is printed as "seen on the real face, not judged: <n>" and never fails a
# case. Everything else is judged: the copy's paths, and any finding on a shared
# file (the verb table, the wire) or with no path at all. `tsc` still checks the
# whole world project (the copy imports the shared screens and the client, so a
# file list would not be smaller); its report is SPLIT per error by path, and an
# exit that prints no error it can read is judged, never passed over.
#
# `--negative` is the drive proving it CAN fail: the archive case's copy with
# `merge` added to its road, against a wire that serves no merge door for the
# copied noun — rule 77 must red on exactly that verb. The wire is planted per
# case, so the negative holds whatever doors the worked noun grows.
#
# A VERB WITH NO FENCED BLOCK IS EXIT 2, never a pass: the example that would be
# copied does not exist, and "nothing to copy" is not "the copy works".
#
# Exit 0 every case held · 1 a case failed · 2 could not look (no node_modules,
# no python, an unknown verb or flag, a malformed fence, a verb with no block).
#
# DOES NOT COVER — declared: whether the worked face is GOOD, only that its
# fenced text is self-sufficient against the wire it adopts; the RENDERED face
# (the browser drive and the mirror pass); the routes a product adds (the
# worked face's walk pages are dev-only and are not copied — a product draws
# its own route and its row in the route table, so the import page's door
# resolves through the template's row in the copied world); the owners' doors
# attach and import ride (the world's document carries them unrenamed, and
# rule 77 judges neither verb). The copy is checked by the rules' runners and
# the census, not by the whole fe suite.

set -euo pipefail

cd "$(dirname "$0")/../.."

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_golden_face: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It carries the only thing keeping this drive's work inside its own" >&2
    echo "   scratch directory. Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh
DRIVE_OPTED_IN_TO_FINISH=1

ROOT=$(pwd -P)
VERBS="archive version move bulk history duplicate merge attach import"

MODE=all
VERB=""
case "${1:-}" in
"" | --all) MODE=all ;;
--verb)
    MODE=verb
    VERB="${2:-}"
    [ -n "$VERB" ] || drive_cannot_look "--verb takes the family verb to copy (one of: ${VERBS})"
    [ "$#" -eq 2 ] || drive_cannot_look "--verb <verb> takes nothing after the verb"
    case " $VERBS " in
    *" $VERB "*) ;;
    *) drive_cannot_look "'${VERB}' has no face case here (the cases: ${VERBS})" ;;
    esac
    ;;
--negative) MODE=negative ;;
--list)
    for verb in $VERBS; do
        echo "  case_the_${verb}_copy_holds_the_rules_the_types_and_the_census"
    done
    echo "  case_the_all_copy_holds_the_rules_the_types_and_the_census (every verb at once: the joint fences' blocks)"
    echo "  case_the_joint_fence_copies_only_with_every_verb"
    echo "  case_a_malformed_joint_fence_is_exit_2"
    echo "  case_the_copy_road_naming_merge_against_a_wire_without_it_reds_rule_77"
    echo "  case_the_cleanup_census_leaves_nothing"
    exit 0
    ;;
*)
    echo "!! unknown argument '${1:-}': test_golden_face.sh takes nothing (every case), --all, --verb <verb>, --negative or --list" >&2
    exit 2
    ;;
esac

FE="$ROOT/frontend"
[ -x "$FE/node_modules/.bin/tsc" ] && [ -x "$FE/node_modules/.bin/vitest" ] && [ -x "$FE/node_modules/.bin/openapi-typescript" ] ||
    drive_cannot_look "frontend/node_modules has no tsc, vitest or openapi-typescript — run ./scripts/setup.sh (pnpm install --frozen-lockfile); the copy is type-checked and censused with this checkout's own toolchain"
# THE CHECKOUT'S OWN INTERPRETER, never the first python3 on PATH: the fences
# are read, the wire planted and the rules' runners run with the one python
# this checkout was set up with.
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || drive_cannot_look "no virtualenv at .venv — run ./scripts/setup.sh; the fences are read, the wire planted and the runners run with this checkout's own interpreter"
command -v tar >/dev/null 2>&1 || drive_cannot_look "no tar on PATH — the world is copied with it"

FAILED=0
pass() { echo "  ok    $*"; }
fail() {
    echo "  FAILED $*" >&2
    FAILED=1
}

SCRATCH=$(mktemp -d "${TMPDIR:-/tmp}/djb-golden-face.XXXXXX")
drive_require_scratch SCRATCH "$SCRATCH"
drive_at_exit "rm -rf '$SCRATCH'"
WORLD="$SCRATCH/world"
mkdir -p "$WORLD"

# ---------------------------------------------------------------------------
# THE ONE READER OF THE FENCES, AND THE ONE PLANTER OF THE WIRE — one python
# program, three subcommands, so the fence grammar is written once.
HELPER="$SCRATCH/golden_face.py"
cat >"$HELPER" <<'PY'
import json
import re
import sys
from pathlib import Path

FENCE = re.compile(r"^\s*(?://|\{?/\*)\s*golden:\s*(\S+)\s+(begin|end)\s*(?:\*/\}?)?\s*$")
SOURCES = ("frontend/src/screens/widget", "frontend/src/copy/widget.ts")
BASE = "face"
#: The worked noun's doors each verb adopts, as (method, path suffix) under the collection.
DOORS = {
    "archive": [("post", "/{widget_id}/archive/"), ("post", "/{widget_id}/restore/")],
    "version": [("patch", "/{widget_id}/")],
    "move": [("post", "/{widget_id}/move/")],
    "bulk": [("post", "/bulk/")],
    "history": [("get", "/{widget_id}/history/")],
    "duplicate": [("post", "/{widget_id}/duplicate/")],
    "merge": [("post", "/{widget_id}/merge/"), ("get", "/{widget_id}/merge/")],
    # Attach and import ride their OWNERS' doors (notes, files, tags; imports),
    # which the world's document already carries unrenamed: the noun plants no
    # operation of its own for them. What rule 77 reads as the noun's door is
    # planted per case in `wire` — the detail's `tags` (attach) and the noun
    # among the importers' kinds (import).
    "attach": [],
    "import": [],
}
COLLECTION = "/api/v1/widgets"
READS = [("get", "/"), ("get", "/{widget_id}/")]


def rename(text):
    return text.replace("Widget", "Gadget").replace("widget", "gadget").replace("WIDGET", "GADGET")


def files(root):
    out = []
    for source in SOURCES:
        path = root / source
        if path.is_file():
            out.append(path)
        elif path.is_dir():
            out.extend(sorted(p for p in path.rglob("*") if p.is_file()))
    return out


def joint(name, number, rel):
    """A JOINT fence's verbs (`bulk+merge`), or None for a single-verb one; exit 2 on a malformed list."""
    if "+" not in name:
        return None
    parts = name.split("+")
    if len(parts) < 2 or any(part not in DOORS for part in parts) or len(set(parts)) != len(parts):
        print(
            f"!! {rel}:{number}: `golden: {name}` is not a joint fence — it lists two or more "
            f"distinct family verbs joined by `+` (the verbs: {' '.join(DOORS)})",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return set(parts)


def extract(root, world, verb):
    """Copy the base and `verb`'s blocks — or, for `all`, every verb's at once.

    A line inside single-verb fences goes with ANY of them (the OR form: the
    fences stack); a line inside a JOINT fence (`bulk+merge`) goes only with a
    copy that holds EVERY verb the fence lists (the AND form), so a single
    verb's copy leaves it behind and the joint copy takes it.
    """
    wanted = set(DOORS) if verb == "all" else {verb}
    copied = 0
    for path in files(root):
        rel = path.relative_to(root)
        lines = path.read_text(encoding="utf-8").splitlines()
        open_fences = []
        kept = []
        fenced_here = False
        for number, line in enumerate(lines, start=1):
            m = FENCE.match(line)
            if m:
                fenced_here = True
                name, edge = m.group(1), m.group(2)
                joint(name, number, rel)
                if edge == "begin":
                    open_fences.append((name, number))
                else:
                    if not any(n == name for n, _ in open_fences):
                        print(f"!! {rel}:{number}: `golden: {name} end` closes no open `{name}` fence", file=sys.stderr)
                        return 2
                    for i in range(len(open_fences) - 1, -1, -1):
                        if open_fences[i][0] == name:
                            del open_fences[i]
                            break
                continue
            names = {n for n, _ in open_fences}
            joints = [joint(n, number, rel) for n in names if "+" in n]
            verbs = {n for n in names if "+" not in n} - {BASE}
            if joints:
                keep = all(j <= wanted for j in joints) and (not verbs or bool(verbs & wanted))
            else:
                keep = bool(verbs & wanted) or (BASE in names and not verbs)
            if keep:
                kept.append(line)
        if open_fences:
            name, number = open_fences[-1]
            print(f"!! {rel}:{number}: `golden: {name} begin` is never closed", file=sys.stderr)
            return 2
        if not fenced_here or not kept:
            continue
        target = world / rename(str(rel))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rename("\n".join(kept)) + "\n", encoding="utf-8")
        print(f"copied {rename(str(rel))} ({len(kept)} lines) from {rel}")
        copied += 1
    if copied == 0:
        return 3
    return 0


def verb_blocks(root, verb):
    """How many fences open for `verb` in the worked face — a verb with none has nothing to copy."""
    count = 0
    for path in files(root):
        for line in path.read_text(encoding="utf-8").splitlines():
            m = FENCE.match(line)
            if m and m.group(1) == verb and m.group(2) == "begin":
                count += 1
    return count


def wire(root, world, verb):
    document = json.loads((root / "frontend/openapi.json").read_text(encoding="utf-8"))
    paths = document["paths"]
    schemas = document["components"]["schemas"]
    for name in [n for n in schemas if "Widget" in n]:
        schemas[rename(name)] = json.loads(rename(json.dumps(schemas[name])))
    wanted = list(READS)
    for case in (DOORS if verb == "all" else {verb: DOORS[verb]}):
        wanted.extend(DOORS[case])
    # The attach door is the noun's detail answering `tags`: only the attach
    # case (and the client's one generation, `all`) keeps it on the copy's
    # detail; every other case's copy adopts no attach.
    detail = schemas.get(rename("WidgetDetailOut")) or {}
    if verb not in ("attach", "all"):
        (detail.get("properties") or {}).pop("tags", None)
    # The import door is the noun among the importers' kinds: the import case
    # (and `all`) plants the copied noun there.
    if verb in ("import", "all"):
        kind = ((schemas.get("ImportIn") or {}).get("properties") or {}).get("kind") or {}
        if "enum" in kind and rename("widget") not in kind["enum"]:
            kind["enum"] = [*kind["enum"], rename("widget")]
    planted = 0
    for method, suffix in wanted:
        source = COLLECTION + suffix
        operation = (paths.get(source) or {}).get(method)
        if operation is None:
            print(f"!! the worked noun's wire has no `{method.upper()} {source}` to plant", file=sys.stderr)
            return 2
        target = rename(source)
        paths.setdefault(target, {})[method] = json.loads(rename(json.dumps(operation)))
        planted += 1
    out = world / "frontend/openapi.json"
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"planted the gadget wire: {planted} operation(s) — " + ", ".join(f"{m.upper()} {rename(COLLECTION + s)}" for m, s in wanted))
    return 0


def on_the_real_face(path, prefix=""):
    """Whether `path` lies in the worked face the copy was taken FROM — the gate's to judge, not this drive's."""
    path = str(path or "")
    return any(path == prefix + source or path.startswith(prefix + source + "/") for source in SOURCES)


def findings(path, seen=None):
    """Print the findings this drive judges; write the real face's to `seen`. Exit 1 when any is judged."""
    reply = json.loads(Path(path).read_text(encoding="utf-8"))
    judged, passed_over = [], []
    for finding in reply.get("findings", []):
        text = f"{finding.get('path')}:{finding.get('line')}: [{finding.get('klass')}] {finding.get('msg')}"
        (passed_over if seen is not None and on_the_real_face(finding.get("path")) else judged).append(text)
    for text in judged:
        print(text)
    if seen is not None:
        Path(seen).write_text("".join(f"{text}\n" for text in passed_over), encoding="utf-8")
    return 1 if judged else 0


TSC_ERROR = re.compile(r"^(\S[^(]*)\(\d+,\d+\): error TS\d+:")


def tsc_errors(log, seen):
    """Split `tsc --noEmit`'s report (paths relative to frontend/) into the judged errors and the real face's.

    An error is a line `path(line,col): error TSn: …` and the indented lines under
    it; an error with no path (a configuration error) is judged, never passed over.
    """
    blocks = []
    for line in Path(log).read_text(encoding="utf-8").splitlines():
        m = TSC_ERROR.match(line)
        if m or not blocks or not line[:1].isspace():
            blocks.append([m.group(1) if m else None, [line]])
        else:
            blocks[-1][1].append(line)
    judged, passed_over = [], []
    for where, lines in blocks:
        if not any(part.strip() for part in lines):
            continue
        (passed_over if where and on_the_real_face("frontend/" + where) else judged).append("\n".join(lines))
    for text in judged:
        print(text)
    Path(seen).write_text("".join(f"{text}\n" for text in passed_over), encoding="utf-8")
    return 1 if judged else 0


def add_merge(world):
    road = world / "frontend/src/screens/gadget/road.ts"
    text = road.read_text(encoding="utf-8")
    grown, n = re.subn(r"(verbs:\s*\[)", r'\1\n        "merge",', text, count=1)
    if n != 1:
        print("!! the copied road has no `verbs: [` to grow", file=sys.stderr)
        return 2
    road.write_text(grown, encoding="utf-8")
    return 0


if __name__ == "__main__":
    command, *args = sys.argv[1:]
    if command == "extract":
        sys.exit(extract(Path(args[0]), Path(args[1]), args[2]))
    if command == "blocks":
        print(verb_blocks(Path(args[0]), args[1]))
        sys.exit(0)
    if command == "wire":
        sys.exit(wire(Path(args[0]), Path(args[1]), args[2]))
    if command == "findings":
        sys.exit(findings(args[0], args[1] if len(args) > 1 else None))
    if command == "tsc":
        sys.exit(tsc_errors(args[0], args[1]))
    if command == "add-merge":
        sys.exit(add_merge(Path(args[0])))
    sys.exit(2)
PY

T0=$(date +%s)

# THE WORLD: this checkout's TRACKED frontend, quality and pattern book, as the
# working tree holds them; node_modules is the checkout's, one link per entry,
# so nothing a run writes (a cache, a build info) lands in the checkout's own.
git ls-files -z -- frontend quality docs/product/design scripts/archaeology_lib.sh scripts/gate_refuse.sh |
    tar --null -T - -cf - | tar -xf - -C "$WORLD"
mkdir -p "$WORLD/frontend/node_modules"
for entry in "$FE/node_modules"/* "$FE/node_modules"/.bin "$FE/node_modules"/.pnpm "$FE/node_modules"/.modules.yaml; do
    [ -e "$entry" ] || continue
    ln -s "$entry" "$WORLD/frontend/node_modules/${entry##*/}"
done

# The client's types, generated ONCE from the wire every verb's case plants
# (a case's own wire changes which doors rule 77 reads, never a type).
"$PY" "$HELPER" wire "$ROOT" "$WORLD" all >"$SCRATCH/wire-all.log" 2>&1 ||
    { cat "$SCRATCH/wire-all.log" >&2; drive_cannot_look "the gadget wire could not be planted"; }
(cd "$WORLD/frontend" && node_modules/.bin/openapi-typescript openapi.json --output src/api/generated/schema.d.ts) >"$SCRATCH/gen.log" 2>&1 ||
    { cat "$SCRATCH/gen.log" >&2; drive_cannot_look "openapi-typescript could not generate the planted wire's client"; }
echo "world: frontend, quality and the pattern book copied; the gadget client generated ($(($(date +%s) - T0))s)"

# seen_on_the_real_face <instrument> <file> — the real face's findings are the
# gate's (rule 77's ratchet row records them), not this drive's: printed with
# their count so a reader knows they exist, never judged here.
seen_on_the_real_face() {
    local n
    [ -s "$2" ] || return 0
    n=$(grep -cE '^(frontend|src)/' "$2" || true)
    echo "  seen on the real face, not judged: ${n} (${1})"
    sed 's/^/       · /' "$2"
}

# golden_case <verb> — steps 1-4 for one verb, in the one world.
golden_case() {
    local verb=$1 t0 rc judged_rc rule log
    t0=$(date +%s)
    echo "case: ${verb}"
    [ "$verb" = "all" ] || [ "$("$PY" "$HELPER" blocks "$ROOT" "$verb")" != "0" ] ||
        drive_cannot_look "the worked face fences no '${verb}' block — there is nothing to copy, and nothing to copy is not a copy that works"
    rm -rf "$WORLD/frontend/src/screens/gadget" "$WORLD/frontend/src/copy/gadget.ts"

    # 1 · the copy.
    set +e
    "$PY" "$HELPER" extract "$ROOT" "$WORLD" "$verb" >"$SCRATCH/extract-$verb.log" 2>&1
    rc=$?
    set -e
    cat "$SCRATCH/extract-$verb.log"
    case "$rc" in
    0) ;;
    3) drive_cannot_look "the '${verb}' copy wrote no file" ;;
    *) drive_cannot_look "the worked face's fences do not read (above)" ;;
    esac

    # 2 · the wire this verb adopts.
    "$PY" "$HELPER" wire "$ROOT" "$WORLD" "$verb" || drive_cannot_look "the '${verb}' wire could not be planted"

    # 3 · copyable.
    set +e
    (
        . scripts/archaeology_lib.sh
        cd "$WORLD"
        archaeology_scan_files $(find frontend/src/screens/gadget frontend/src/copy/gadget.ts -type f)
    ) >"$SCRATCH/archaeology-$verb.log" 2>&1
    rc=$?
    set -e
    if [ "$rc" = "0" ] && ! grep -q "archaeology-census:" "$SCRATCH/archaeology-$verb.log"; then
        pass "the ${verb} copy is copyable (the archaeology census reads nothing in it)"
    else
        fail "case_the_${verb}_copy — the copied text carries what a product must not inherit:"
        sed 's/^/       /' "$SCRATCH/archaeology-$verb.log" >&2
    fi

    # 4 · rules 77-80, the types, the census.
    for rule in road acts words table; do
        log="$SCRATCH/rule-$rule-$verb.json"
        (cd "$WORLD" && "$PY" "quality/runners/js_verb_${rule}.py" frontend) >"$log" 2>"$log.err" ||
            { cat "$log.err" >&2; drive_cannot_look "quality/runners/js_verb_${rule}.py did not run in the world"; }
        if "$PY" "$HELPER" findings "$log" "$log.seen" >"$log.txt"; then
            pass "js_verb_${rule}.py: no finding over the ${verb} copy"
        else
            fail "case_the_${verb}_copy — js_verb_${rule}.py found:"
            sed 's/^/       /' "$log.txt" >&2
        fi
        seen_on_the_real_face "js_verb_${rule}.py" "$log.seen"
    done
    set +e
    (cd "$WORLD/frontend" && node_modules/.bin/tsc --noEmit -p .) >"$SCRATCH/tsc-$verb.log" 2>&1
    rc=$?
    "$PY" "$HELPER" tsc "$SCRATCH/tsc-$verb.log" "$SCRATCH/tsc-$verb.seen" >"$SCRATCH/tsc-$verb.judged"
    judged_rc=$?
    set -e
    if [ "$rc" = "0" ]; then
        pass "the ${verb} copy type-checks against the planted wire (tsc --noEmit)"
    elif [ "$judged_rc" = "0" ] && [ -s "$SCRATCH/tsc-$verb.seen" ]; then
        pass "the ${verb} copy type-checks against the planted wire (tsc --noEmit; every error it printed is on the real face)"
    elif [ "$judged_rc" = "1" ]; then
        fail "case_the_${verb}_copy — the copy does not compile on its own:"
        sed 's/^/       /' "$SCRATCH/tsc-$verb.judged" | head -40 >&2
    else
        fail "case_the_${verb}_copy — tsc exited ${rc} and its report did not read as errors (judged, not passed over):"
        sed 's/^/       /' "$SCRATCH/tsc-$verb.log" | head -40 >&2
    fi
    seen_on_the_real_face "tsc" "$SCRATCH/tsc-$verb.seen"
    set +e
    (cd "$WORLD/frontend" && node_modules/.bin/vitest run --reporter=verbose src/screens/verb-face-census.test.tsx) >"$SCRATCH/census-$verb.log" 2>&1
    rc=$?
    set -e
    if [ "$rc" = "0" ] && grep -q "the 'gadget' face's road" "$SCRATCH/census-$verb.log"; then
        pass "the verb face census holds over the ${verb} copy ($(grep -c "the 'gadget' face's road" "$SCRATCH/census-$verb.log") gadget test(s) run)"
    elif [ "$rc" = "0" ]; then
        fail "case_the_${verb}_copy — the census ran and never named the gadget face: it did not measure the copy"
    else
        fail "case_the_${verb}_copy — the verb face census reds over the copy:"
        grep -E "×|FAIL|AssertionError|Error|expected" "$SCRATCH/census-$verb.log" | head -40 | sed 's/^/       /' >&2
    fi
    echo "case ${verb}: $(($(date +%s) - t0))s"
}

# golden_negative — the archive copy's road naming merge, against a wire without it.
golden_negative() {
    local log="$SCRATCH/rule-road-negative.json"
    echo "case: negative"
    rm -rf "$WORLD/frontend/src/screens/gadget" "$WORLD/frontend/src/copy/gadget.ts"
    "$PY" "$HELPER" extract "$ROOT" "$WORLD" archive >/dev/null || drive_cannot_look "the archive copy could not be made for the negative"
    "$PY" "$HELPER" wire "$ROOT" "$WORLD" archive >/dev/null || drive_cannot_look "the archive wire could not be planted for the negative"
    "$PY" "$HELPER" add-merge "$WORLD" || drive_cannot_look "the negative could not grow the copied road"
    (cd "$WORLD" && "$PY" quality/runners/js_verb_road.py frontend) >"$log" ||
        drive_cannot_look "quality/runners/js_verb_road.py did not run for the negative"
    "$PY" "$HELPER" findings "$log" "$log.seen" >"$log.txt" || true
    seen_on_the_real_face "js_verb_road.py" "$log.seen"
    if grep -q "declares \`merge\` and \`frontend/openapi.json\` serves no \`merge\` door for \`gadget\`" "$log.txt" &&
        [ "$(wc -l <"$log.txt" | tr -d ' ')" = "1" ]; then
        pass "the copy's road naming merge against a wire without it reds rule 77, on that verb alone: $(cat "$log.txt")"
    else
        fail "case_the_copy_road_naming_merge_against_a_wire_without_it_reds_rule_77 — rule 77 did not red on merge alone:"
        sed 's/^/       /' "$log.txt" >&2
    fi
}

# golden_fences — the fence grammar's own proof, over a fixture face: a JOINT
# fence (`bulk+merge`) is left behind by a single verb's copy and taken by the
# joint copy; a malformed joint list is exit 2 (could not read the fences).
golden_fences() {
    local fixture="$SCRATCH/fence-fixture" out="$SCRATCH/fence-world" rc
    echo "case: fences"
    rm -rf "$fixture" "$out"
    mkdir -p "$fixture/frontend/src/screens/widget" "$out"
    cat >"$fixture/frontend/src/screens/widget/fence.ts" <<'TS'
// golden: face begin
export const base = 1;
// golden: face end
// golden: bulk begin
export const bulkOnly = 2;
// golden: bulk+merge begin
export const bothBulkAndMerge = 3;
// golden: bulk+merge end
// golden: bulk end
TS
    "$PY" "$HELPER" extract "$fixture" "$out" bulk >/dev/null || drive_cannot_look "the fence fixture's bulk copy could not be made"
    if grep -q bulkOnly "$out/frontend/src/screens/gadget/fence.ts" && ! grep -q bothBulkAndMerge "$out/frontend/src/screens/gadget/fence.ts"; then
        pass "a joint fence (bulk+merge) is left behind by the bulk copy alone"
    else
        fail "case_the_joint_fence_copies_only_with_every_verb — the bulk copy took the joint block, or lost its own"
    fi
    rm -rf "$out" && mkdir -p "$out"
    "$PY" "$HELPER" extract "$fixture" "$out" all >/dev/null || drive_cannot_look "the fence fixture's joint copy could not be made"
    if grep -q bothBulkAndMerge "$out/frontend/src/screens/gadget/fence.ts"; then
        pass "a joint fence (bulk+merge) is taken by the joint copy, which holds every verb"
    else
        fail "case_the_joint_fence_copies_only_with_every_verb — the joint copy left the joint block behind"
    fi
    for malformed in "bulk+" "bulk+nothing" "merge+merge"; do
        printf '// golden: %s begin\nexport const x = 1;\n// golden: %s end\n' "$malformed" "$malformed" >"$fixture/frontend/src/screens/widget/fence.ts"
        set +e
        "$PY" "$HELPER" extract "$fixture" "$out" bulk >"$SCRATCH/fence-malformed.log" 2>&1
        rc=$?
        set -e
        if [ "$rc" = "2" ] && grep -q "is not a joint fence" "$SCRATCH/fence-malformed.log"; then
            pass "a malformed joint list (${malformed}) is exit 2, naming the fence"
        else
            fail "case_a_malformed_joint_fence_is_exit_2 — '${malformed}' answered ${rc}"
        fi
    done
}

# golden_census — nothing of the copy anywhere but the scratch world.
golden_census() {
    local left=""
    for path in frontend/src/screens/gadget frontend/src/copy/gadget.ts; do
        [ ! -e "$ROOT/$path" ] || left="$left $path"
    done
    if [ -z "$left" ]; then
        pass "cleanup census: no gadget face in the checkout (frontend/src/screens/gadget, frontend/src/copy/gadget.ts absent); the world at ${SCRATCH} is removed at exit"
    else
        fail "case_the_cleanup_census_leaves_nothing — the checkout carries:${left}"
    fi
}

case "$MODE" in
all)
    for verb in $VERBS; do
        golden_case "$verb"
    done
    golden_case all
    golden_fences
    golden_negative
    ;;
verb) golden_case "$VERB" ;;
negative) golden_negative ;;
esac
golden_census

echo "test_golden_face: $([ "$FAILED" = "0" ] && echo "every case held" || echo "a case FAILED (above)") ($(($(date +%s) - T0))s)"
drive_finished
exit "$FAILED"
