#!/usr/bin/env bash
# THIS FILE IS EXECUTED, AND IT IS BASH — not POSIX sh, and not zsh. The
# shebang above is honoured by `./this`; `sh this` and `zsh this` IGNORE it,
# and neither of them fails where the mistake was made. The argument, measured
# on this tree, is `scripts/rung_start.sh`'s header.
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
# drives: .gitignore .secrets.baseline frontend/openapi.json frontend/src/api/generated/schema.d.ts quality/budgets.yaml quality/gate.py scripts/budget_notes.sh scripts/check.sh scripts/fe_gate.sh scripts/pm_fold.sh scripts/rung_start.sh scripts/rung_tidy.sh scripts/tests/test_fast_censuses.sh scripts/tests/test_pm_fold.sh scripts/tests/test_secrets_baseline_guard.sh
#
# THE TIDY'S DRIVE. `scripts/rung_tidy.sh` WRITES into a checkout — a budget
# ceiling, a generated client, a secret baseline — so every one of its claims is
# a claim about somebody's working tree, and the three most dangerous things it
# could do are all silent: apply a number no sentence named, grow a SECOND
# `detect-secrets scan --baseline` writer, or go quiet when the engine's
# sentence moves and report "nothing to do" over a tree that is refusing.
#
#   ./scripts/tests/test_rung_tidy.sh          run every case
#   ./scripts/tests/test_rung_tidy.sh --list   name them and stop
#
# IT BUILDS ITS OWN CHECKOUTS, and it plants nothing in this tree. Each case
# runs against a throwaway git repository under `mktemp -d` carrying COPIES of
# `rung_tidy.sh`, `budget_notes.sh` and `pm_fold.sh` and STUB tools, so nothing
# here is tidied and no real generator is run.
#
# THE STUBS ARE THE POINT, not a shortcut, and the argument is
# `scripts/tests/test_pm_fold.sh`'s verbatim: the real tools are `npx` + Node +
# a schema export and a full-tree detect-secrets scan, and what this drive
# asserts is THE TIDY'S OWN behaviour around whatever those did — which command
# it reaches for, what it writes, what it refuses, and what it says. The live
# half is the builder's report, which records a real `--budgets` against the
# real engine in a scratch clone.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   1. THE REAL GENERATORS AND THE REAL SCANNER. Stubbed, above. Whether
#      `pin_client.sh` produces a correct client is its own header's claim and
#      `frontend/`'s drives'; whether detect-secrets finds a secret is
#      `scripts/tests/test_secrets_baseline_guard.sh`'s, which prints the
#      installed version beside every verdict.
#   2. A NESTED `./scripts/check.sh`. The per-checkout gate lock refuses one
#      (`gate_lock_refuse_if_held`), so the house-rules OFFER is driven by
#      EXTRACTING the leg body from `scripts/check.sh` between its
#      `# >>> leg-body: house-rules >>>` sentinels and sourcing that with a
#      shimmed engine on PATH. A missing sentinel is could-not-look and never a
#      case that quietly stopped driving anything.
#   3. WHETHER A RAISE IS LEGITIMATE. The tidy applies the number the engine
#      printed into the working tree so a reviewer sees it; nothing here has an
#      opinion about whether the function should have grown.
#   4. THE ENGINE'S SENTENCE ACTUALLY BEING THE ONE IT PARSES.
#      `case_a_reworded_engine_sentence_is_could_not_look` proves the
#      cross-check FIRES when the sentence moves; it cannot prove today's
#      sentence is today's. That pairing is `quality/gate.py`'s own canary
#      population's job — the same blind spot, in the same words, that
#      `test_pm_fold.sh` declares one caller over.
set -euo pipefail

cd "$(dirname "$0")/../.."

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_rung_tidy: scripts/tests/drive_preamble.sh is missing. Refusing to run:" >&2
    echo "   without it an inherited GIT_DIR aims every fixture git command at the real" >&2
    echo "   repository. Exit 2, nothing asserted." >&2
    exit 2
}
# shellcheck source=scripts/tests/drive_preamble.sh
. scripts/tests/drive_preamble.sh
DRIVE_OPTED_IN_TO_FINISH=1

ROOT="$(pwd -P)"
TIDY_SRC="$ROOT/scripts/rung_tidy.sh"
NOTES_SRC="$ROOT/scripts/budget_notes.sh"
FOLD_SRC="$ROOT/scripts/pm_fold.sh"
CHECK_SRC="$ROOT/scripts/check.sh"
FE_SRC="$ROOT/scripts/fe_gate.sh"

PASSED=0
FAILED=0
CURRENT=""
OUT=""
RC=0
N=0
REPO=""

cannot_look() {
    echo "!! test_rung_tidy: $*" >&2
    echo "   Nothing was asserted. A driver that could not run its cases has not" >&2
    echo "   cleared them." >&2
    exit 2
}

case "${1:-}" in
"") ;;
--list)
    grep -n '^case_' "$0" | sed 's/() {.*//; s/^/  /'
    exit 0
    ;;
*)
    echo "!! unknown argument '$1': test_rung_tidy.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

command -v git >/dev/null 2>&1 || cannot_look "no git on PATH"
command -v python3 >/dev/null 2>&1 || cannot_look "no python3 on PATH — the fold's baseline strip is a JSON rewrite"
[ -x "$TIDY_SRC" ] || cannot_look "scripts/rung_tidy.sh is not an executable file in this tree — there is nothing to drive"
[ -r "$NOTES_SRC" ] || cannot_look "scripts/budget_notes.sh is not in this tree — the tidy and the fold both read it"
[ -x "$FOLD_SRC" ] || cannot_look "scripts/pm_fold.sh is not executable — the secrets subject invokes it"
[ -r "$CHECK_SRC" ] || cannot_look "scripts/check.sh is not in this tree — the house-rules offer is read out of it"
[ -r "$FE_SRC" ] || cannot_look "scripts/fe_gate.sh is not in this tree — the client offer is read out of it"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-test-rung-tidy.XXXXXX")" ||
    cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'chmod -R u+rwX "$WORK" 2>/dev/null || true; rm -rf "$WORK"'

ok() {
    PASSED=$((PASSED + 1))
    echo "  ok       ${CURRENT} — $1"
}
bad() {
    FAILED=$((FAILED + 1))
    echo "  FAILED   ${CURRENT} — $1"
    if [ -n "$OUT" ] && [ -f "$OUT" ]; then
        sed 's/^/             | /' "$OUT"
    fi
}
holds() {
    if [ "$2" = "$3" ]; then ok "$1"; else bad "${1} — wanted '${2}', got '${3}'"; fi
}
exits() {
    if [ "$RC" -eq "$1" ]; then ok "exit ${RC}"; else bad "wanted exit $1, got ${RC}"; fi
}
says() {
    if grep -qF -- "$1" "$OUT"; then ok "says \"$1\""; else bad "does not say \"$1\""; fi
}
says_not() {
    if grep -qF -- "$1" "$OUT"; then bad "says \"$1\" and must not"; else ok "does not say \"$1\""; fi
}

# extract_block <file> <open-sentinel> <close-sentinel> <dest>
#
# Cited by SENTINEL and never by line number: `scripts/check.sh` moves under its
# own citations routinely, and a drive that read a line range would go on
# sourcing whatever had drifted into it.
extract_block() {
    awk -v o="$2" -v c="$3" '
        index($0, o) { on = 1; next }
        index($0, c) { on = 0 }
        on { print }
    ' "$1" >"$4"
    [ -s "$4" ] ||
        cannot_look "the block between '${2}' and '${3}' in ${1} is empty — the sentinels moved, and a drive that sourced nothing would report a pass"
}

# --- the fixture checkout -----------------------------------------------------
#
# A throwaway git repository carrying all three subjects and stub tools. The
# steering files live in `.git/info/exclude` so the FOLD's own footprint census
# cannot see them: a steering file counted as a stray would make every case
# exit 2 for the harness's reason instead of the case's.
fixture_repo() {
    N=$((N + 1))
    REPO="${WORK}/repo-${N}-$1"
    drive_require_scratch REPO "${REPO:-}"
    mkdir -p "$REPO/scripts" "$REPO/quality" "$REPO/bin" \
        "$REPO/frontend/scripts" "$REPO/frontend/src/api/generated"

    cp "$TIDY_SRC" "$REPO/scripts/rung_tidy.sh"
    chmod +x "$REPO/scripts/rung_tidy.sh"
    cp "$NOTES_SRC" "$REPO/scripts/budget_notes.sh"
    cp "$FOLD_SRC" "$REPO/scripts/pm_fold.sh"
    chmod +x "$REPO/scripts/pm_fold.sh"

    # Two sections, and one key carrying `::` — every `out_schema_fields` key in
    # the real file does, and the reader's "find the LAST `: N`" rule is the
    # only reason such a key splits correctly. The provenance comment BELOW an
    # entry is the real file's shape too, and it is what makes the new-subject
    # insertion point a real question rather than a formality.
    cat >"$REPO/quality/budgets.yaml" <<'BUDGETS'
service_function_length:
  apps/alpha/services.py: 40 # provenance: the comment that must survive
  # and its second line, which a naive insertion lands in the middle of
  apps/beta/services.py: 55

out_schema_fields:
  apps/alpha/schemas.py::ThingOut: 9
BUDGETS

    printf '{\n  "openapi": "3.1.0",\n  "paths": {}\n}\n' >"$REPO/frontend/openapi.json"
    printf 'export type paths = Record<string, never>;\n' \
        >"$REPO/frontend/src/api/generated/schema.d.ts"

    cat >"$REPO/.secrets.baseline" <<'BASELINE'
{
  "version": "1.5.0",
  "results": {}
}
BASELINE

    # --- the stubs -----------------------------------------------------------
    # `pin_client.sh`, steered by `pin.act`: noop | write | nonpx | fail.
    cat >"$REPO/frontend/scripts/pin_client.sh" <<STUB
#!/usr/bin/env bash
set -euo pipefail
act="\$(cat "$REPO/pin.act" 2>/dev/null || echo noop)"
case "\$act" in
nonpx)
    echo "npx was not found, so the TypeScript client was not generated." >&2
    exit 2
    ;;
fail)
    echo "stub pin_client: this checkout cannot export a schema" >&2
    exit 1
    ;;
write)
    printf '{\n  "openapi": "3.1.0",\n  "paths": {"/api/v1/things": {}}\n}\n' \
        >"$REPO/frontend/openapi.json"
    printf 'export type paths = { "/api/v1/things": unknown };\n' \
        >"$REPO/frontend/src/api/generated/schema.d.ts"
    echo "wrote $REPO/frontend/src/api/generated/schema.d.ts"
    echo "wrote $REPO/frontend/openapi.json"
    echo "Commit both. They are one artefact of one commit of this checkout."
    ;;
noop)
    echo "the committed client and document are byte-identical to a fresh generation"
    ;;
esac
STUB
    chmod +x "$REPO/frontend/scripts/pin_client.sh"

    # `uv`: the two shapes the tidy and the fold call it with —
    # `uv run python <the generated budget reader>` and
    # `uv run detect-secrets scan --baseline .secrets.baseline`.
    cat >"$REPO/bin/uv" <<STUB
#!/usr/bin/env bash
set -euo pipefail
case "\$*" in
*"detect-secrets scan"*)
    act="\$(cat "$REPO/secrets.act" 2>/dev/null || echo stamp)"
    case "\$act" in
    shift)
        cat >"$REPO/.secrets.baseline" <<'B'
{
  "version": "1.5.0",
  "results": {"src/oops.txt": [{"type": "Secret Keyword", "line_number": 7}]},
  "generated_at": "2026-06-06T06:06:06Z"
}
B
        ;;
    stamp)
        cat >"$REPO/.secrets.baseline" <<'B'
{
  "version": "1.5.0",
  "results": {},
  "generated_at": "2026-06-06T06:06:06Z"
}
B
        ;;
    esac
    ;;
*python*)
    if [ -f "$REPO/budget.out" ]; then
        cat "$REPO/budget.out"
    else
        echo "### budget-check: notes=0 problems=0"
    fi
    ;;
esac
STUB
    chmod +x "$REPO/bin/uv"

    printf '/.rung/\n' >"$REPO/.gitignore"
    git -C "$REPO" init -q
    git -C "$REPO" config user.email drive@example.invalid
    git -C "$REPO" config user.name "tidy drive"
    git -C "$REPO" config commit.gpgsign false
    printf 'bin/\npin.act\nsecrets.act\nbudget.out\n' >"$REPO/.git/info/exclude"
    git -C "$REPO" add -A
    git -C "$REPO" commit -q -m "base"
}

# run_tidy <label> [args...] — the fixture's tidy, with the stub toolchain on
# PATH and the transcript captured OUTSIDE the fixture (written inside one it is
# an untracked file, and the fold's clause 1 then refuses the secrets subject
# for the harness's reason instead of the case's).
run_tidy() {
    CURRENT="$1"
    shift
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    set +e
    (cd "$REPO" && PATH="$REPO/bin:$PATH" ./scripts/rung_tidy.sh "$@") >"$OUT" 2>&1
    RC=$?
    set -e
}

# =============================================================================

# Runs THIS TREE'S OWN FILE: the pipe refusal fires before the script derives a
# root, so it needs no fixture at all.
case_a_piped_stdout_is_refused() {
    CURRENT="a piped stdout is refused"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    # The pipe is the point. `cat` is the filter whose exit status would
    # otherwise become the verdict, and PIPESTATUS is how this driver reads the
    # status the pipe would have swallowed.
    set +e
    "$TIDY_SRC" --budgets 2>&1 | cat >"$OUT"
    RC=${PIPESTATUS[0]}
    set -e
    exits 2
    says "refuses pipes"
    says "The exit status is the verdict"
}

case_an_unknown_argument_is_refused() {
    CURRENT="an unknown argument is refused"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    set +e
    "$TIDY_SRC" --force >"$OUT" 2>&1
    RC=$?
    set -e
    exits 2
    says "got '--force'"
    says_not "tidy budgets"
}

# --- A.1 · the budgets --------------------------------------------------------

case_budgets_applies_the_printed_lines_and_only_those() {
    fixture_repo budgets_apply
    # The engine's two PASTEABLE shapes, verbatim in the wording
    # `quality/gate.py::check_budgets` prints them in: a RAISE over a key the
    # file already has, and a NEW SUBJECT it does not.
    cat >"$REPO/budget.out" <<'ENGINE'
budget: service_function_length apps/alpha/services.py — do_thing (lines 10-99) grew to 91, past the recorded ceiling 40 — shrink it, or raise the ceiling in quality/budgets.yaml in a diff a reviewer sees. The line to paste, verbatim:
  apps/alpha/services.py: 91
budget: out_schema_fields has no recorded ceiling for apps/gamma/schemas.py::NewOut (measured 4) — a new subject fails until a human measures it and commits the number. The line to paste under `out_schema_fields:` in quality/budgets.yaml:
  apps/gamma/schemas.py::NewOut: 4
### budget-check: notes=0 problems=2
ENGINE
    run_tidy "budgets applies the printed lines, and only those" --budgets
    exits 0
    says "budget applied: service_function_length.apps/alpha/services.py 40 → 91"
    says "budget applied: out_schema_fields.apps/gamma/schemas.py::NewOut none → 4"

    local after="$REPO/quality/budgets.yaml"
    holds "the raise landed on the key's own line" \
        "  apps/alpha/services.py: 91 # provenance: the comment that must survive" \
        "$(grep '^  apps/alpha/services.py: ' "$after")"
    holds "the new subject landed in its own section" "1" \
        "$(grep -c '^  apps/gamma/schemas.py::NewOut: 4$' "$after" || true)"
    # A CEILING NO SENTENCE NAMED IS UNTOUCHED. This is the half that says the
    # tidy applied the printed lines AND ONLY THOSE.
    holds "the untouched key is byte-identical" "  apps/beta/services.py: 55" \
        "$(grep '^  apps/beta/services.py: ' "$after")"
    holds "the section's provenance comment survived" "1" \
        "$(grep -c 'the comment that must survive' "$after" || true)"
    # NOTHING STAGED, NOTHING COMMITTED — the tidy's standing promise.
    holds "nothing is staged" "" "$(git -C "$REPO" diff --cached --name-only)"
    holds "the change is in the working tree" " M quality/budgets.yaml" \
        "$(git -C "$REPO" status --porcelain)"
}

case_a_lowering_is_left_to_the_fold() {
    fixture_repo budgets_lowering
    cat >"$REPO/budget.out" <<'ENGINE'
budget note: service_function_length apps/alpha/services.py — do_thing (lines 10-30) measured 21, below its ceiling 40 — a human may commit the lower number:
  apps/alpha/services.py: 21
### budget-check: notes=1 problems=0
ENGINE
    cp "$REPO/quality/budgets.yaml" "${WORK}/lowering.before"
    run_tidy "a lowering is left for the fold" --budgets
    exits 0
    says "left for the fold (clause 3)"
    says "tidy budgets: nothing to do"
    says_not "budget applied:"
    if cmp -s "${WORK}/lowering.before" "$REPO/quality/budgets.yaml"; then
        ok "quality/budgets.yaml is byte-identical — a lowering moves no ceiling here"
    else
        bad "the tidy lowered a ceiling, which is the fold's job under clause 3"
    fi
}

# THE INSTRUMENT-ABSENT CASE. A clean tree has to be distinguishable from a tree
# nothing looked at, and `cmp` is the distinction.
case_budgets_with_nothing_to_do_is_byte_identical() {
    fixture_repo budgets_clean
    cp "$REPO/quality/budgets.yaml" "${WORK}/clean.before"
    run_tidy "a clean budgets.yaml is nothing to do, byte for byte" --budgets
    exits 0
    says "tidy budgets: nothing to do"
    if cmp -s "${WORK}/clean.before" "$REPO/quality/budgets.yaml"; then
        ok "quality/budgets.yaml is byte-identical"
    else
        bad "a tidy with nothing to do rewrote the file"
    fi
    holds "the tree is clean" "" "$(git -C "$REPO" status --porcelain)"
}

# THE CROSS-CHECK, WHICH IS THE WHOLE REASON THE READER IS ONE FILE. A reworded
# engine sentence makes the parser recognise nothing while the engine's own
# count says otherwise; without this the tidy would report "nothing to do",
# which looks exactly like a clean tree.
case_a_reworded_engine_sentence_is_could_not_look() {
    fixture_repo budgets_reworded
    cat >"$REPO/budget.out" <<'ENGINE'
budget: service_function_length apps/alpha/services.py — do_thing grew to 91, past the recorded ceiling 40. Here is the line you should paste:
  apps/alpha/services.py: 91
### budget-check: notes=0 problems=1
ENGINE
    cp "$REPO/quality/budgets.yaml" "${WORK}/reworded.before"
    run_tidy "a reworded engine sentence is could-not-look" --budgets
    exits 2
    says "wrote 1 problem(s) and this reader"
    says "recognised 0 pasteable line(s)"
    says "COULD NOT LOOK"
    if cmp -s "${WORK}/reworded.before" "$REPO/quality/budgets.yaml"; then
        ok "quality/budgets.yaml was not modified"
    else
        bad "a could-not-look still wrote to the file"
    fi
}

# --- A.2 · the client ---------------------------------------------------------

case_client_regenerates_via_pin_client() {
    fixture_repo client_write
    echo "write" >"$REPO/pin.act"
    run_tidy "the client is regenerated through pin_client.sh --write" --client
    exits 0
    # THE PIN'S OWN BANNER IS IN THE TIDY'S OUTPUT: what proves the tidy went
    # through the pin rather than reimplementing it is the pin speaking.
    says "Commit both. They are one artefact of one commit of this checkout."
    says "tidy client: regenerated 2 file(s)"
    holds "both derived paths moved in the working tree" \
        "frontend/openapi.json frontend/src/api/generated/schema.d.ts" \
        "$(git -C "$REPO" status --porcelain | awk '{print $2}' | sort | tr '\n' ' ' | sed 's/ *$//')"
    holds "nothing is staged" "" "$(git -C "$REPO" diff --cached --name-only)"

    # AND THE SCRIPT INVOKES NEITHER THE GENERATOR NOR `npx`. `pin_client.sh:36`
    # is the contract — generating straight into `src/api/generated/` plants a
    # `.gitignore` holding `*` over the very file the pin keeps committed — and
    # a second caller reaching past it is how that rule stops being one.
    #
    # AN INVOCATION, NOT A MENTION, and the distinction is load-bearing here in
    # BOTH directions: the tidy's own could-not-look is REQUIRED to name npx
    # (`case_no_npx_is_could_not_look` asserts it), so a census that counted
    # every occurrence would make the two criteria contradict each other. What
    # is being detected is a CALL, and a call is a command at the head of a
    # command — comments stripped first, then the name must sit at the start of
    # a line or after `;`, `&`, `|` or `$(`, with an argument behind it. The
    # same shape `scripts/tests/test_fast_censuses.sh`'s bare-python3 census
    # uses, and for the same stated reason.
    OUT=""
    CURRENT="the client is regenerated through pin_client.sh --write"
    local strays
    strays="$(sed 's/#.*//' "$TIDY_SRC" |
        grep -nE '(^|[;&|]|\$\()[[:space:]]*("?\$?\{?[A-Za-z_/.$][A-Za-z0-9_/.${}-]*)?gen_client\.sh|(^|[;&|]|\$\()[[:space:]]*npx[[:space:]]' || true)"
    if [ -z "$strays" ]; then
        ok "rung_tidy.sh's code invokes neither gen_client.sh nor npx"
    else
        bad "rung_tidy.sh reaches past the pin: ${strays}"
    fi
    # THE CENSUS IS NOT VACUOUS: the same reader over a planted call must fire,
    # or a green above is a grep that stopped matching rather than a script that
    # stopped calling.
    local planted="${WORK}/planted-npx.sh"
    { cat "$TIDY_SRC"; printf 'npx --yes openapi-typescript@7.9.1 x --output y\n'; } >"$planted"
    if sed 's/#.*//' "$planted" |
        grep -E '(^|[;&|]|\$\()[[:space:]]*npx[[:space:]]' >/dev/null; then
        ok "the census fires on a planted npx call — it is looking"
    else
        bad "a planted npx call is invisible to this census: it proves nothing about the real file"
    fi
}

case_no_npx_is_could_not_look() {
    fixture_repo client_nonpx
    echo "nonpx" >"$REPO/pin.act"
    run_tidy "a generator with no npx is could-not-look, naming npx" --client
    exits 2
    says "npx was not found"
    says "could not look (exit 2"
    says "COULD NOT LOOK"
    says_not "tidy client: regenerated"
}

# --- A.4 · the secrets subject owns no writer ---------------------------------

case_secrets_goes_through_the_fold_and_stages_nothing() {
    fixture_repo secrets_shift
    echo "shift" >"$REPO/secrets.act"
    run_tidy "the secrets subject re-scans through the fold and stages nothing" --secrets
    exits 0
    says "tidy secrets: the baseline was re-scanned and rewritten"
    # The FOLD's own voice, in the tidy's output: proof it was invoked rather
    # than reimplemented.
    says "pm_fold: --no-commit"
    says "BASELINE SHIFTED"
    holds "only the baseline moved" " M .secrets.baseline" \
        "$(git -C "$REPO" status --porcelain)"
    holds "nothing is staged" "" "$(git -C "$REPO" diff --cached --name-only)"
    holds "HEAD did not move" "base" "$(git -C "$REPO" log -1 --format=%s)"
    # THE NORMAL FORM, both fields: the scan's stamp and the line numbers that
    # move whenever anything is inserted above a recorded secret.
    holds "the rewritten baseline carries no stamp" "0" \
        "$(grep -c '"generated_at"' "$REPO/.secrets.baseline" || true)"
    holds "the rewritten baseline carries no line numbers" "0" \
        "$(grep -c '"line_number"' "$REPO/.secrets.baseline" || true)"
}

case_the_tidy_names_no_baseline_writer_of_its_own() {
    CURRENT="the tidy owns no baseline writer"
    OUT=""
    # CODE ONLY, comments stripped first: this script's header ARGUES the class
    # by naming the command, and a guard a comment can trip is a guard that
    # teaches people to stop writing comments. The same disposal
    # `test_secrets_baseline_guard.sh` makes one file over.
    local hits
    hits="$(sed 's/#.*//' "$TIDY_SRC" | grep -n 'detect-secrets' || true)"
    if [ -z "$hits" ]; then
        ok "rung_tidy.sh's code never names detect-secrets at all — it invokes the one writer"
    else
        bad "rung_tidy.sh names detect-secrets in code: ${hits}"
    fi
    if grep -q 'pm_fold.sh}' "$TIDY_SRC" && grep -q -- '--only secrets --no-commit' "$TIDY_SRC"; then
        ok "the secrets subject invokes scripts/pm_fold.sh --only secrets --no-commit"
    else
        bad "the secrets subject no longer goes through the fold — a second writer is the only other way to do this"
    fi
}

case_an_absent_subject_is_skipped_and_says_why() {
    fixture_repo absent
    rm -rf "$REPO/frontend"
    rm -f "$REPO/quality/budgets.yaml"
    # COMMITTED, not just deleted: the secrets subject goes through the fold,
    # and the fold folds a COMMITTED tree whichever flags it was handed. A
    # fixture that left the deletions uncommitted would be measuring clause 1
    # rather than the skip.
    git -C "$REPO" add -A
    git -C "$REPO" commit -q -m "a checkout with neither budgets nor a frontend"
    run_tidy "an absent subject is skipped, printed, at exit 0"
    exits 0
    says "tidy budgets: skipped — no quality/budgets.yaml"
    says "tidy client: skipped — neither frontend/openapi.json"
    # The subject that IS here still ran.
    says "tidy secrets:"
}

# --- A.6 · the three offers ---------------------------------------------------

# PLANT 1 · the house-rules leg. The leg body is EXTRACTED from
# scripts/check.sh between its sentinels and sourced with a shimmed engine,
# because a drive cannot run a nested gate (blind spot 2).
_run_house_rules_leg() { # <engine-exit> <engine-output-file>
    N=$((N + 1))
    local dir="${WORK}/hr${N}"
    mkdir -p "$dir/bin"
    extract_block "$CHECK_SRC" '# >>> leg-body: house-rules >>>' \
        '# <<< leg-body: house-rules <<<' "$dir/body.sh"
    cp "$2" "$dir/engine.out"
    cat >"$dir/bin/uv" <<STUB
#!/usr/bin/env bash
cat "$dir/engine.out"
exit $1
STUB
    chmod +x "$dir/bin/uv"
    OUT="${WORK}/out-hr${N}.log"
    RC=0
    set +e
    (
        set +u
        MODE=--loop
        # shellcheck disable=SC1090
        . "$dir/body.sh"
        PATH="$dir/bin:$PATH" gate_leg_house_rules
    ) >"$OUT" 2>&1
    RC=$?
    set -e
}

case_each_refusal_offers_its_own_flag() {
    # --- plant 1: a red house-rules leg whose output carries a budget line ---
    local eng="${WORK}/engine-budget.out"
    cat >"$eng" <<'ENGINE'
  x rule 12: apps/alpha/services.py:3: something else entirely
  x budget: service_function_length apps/alpha/services.py — do_thing (lines 10-99) grew to 91, past the recorded ceiling 40 — shrink it, or raise the ceiling in quality/budgets.yaml in a diff a reviewer sees. The line to paste, verbatim:
  apps/alpha/services.py: 91
ENGINE
    CURRENT="plant 1 — a budget red offers --budgets at the house-rules leg"
    _run_house_rules_leg 1 "$eng"
    exits 1
    says "offer: ./scripts/rung_tidy.sh --budgets"
    # The engine's own output is still printed WHOLE. An offer that replaced the
    # reason would be an offer nobody can check.
    says "x rule 12: apps/alpha/services.py:3: something else entirely"

    # --- plant 2: the fe leg's suspect state --------------------------------
    CURRENT="plant 2 — the fe leg's suspect state offers --client"
    N=$((N + 1))
    local fedir="${WORK}/fe${N}" list="${WORK}/fe-changed${N}"
    mkdir -p "$fedir"
    printf 'apps/alpha/schemas.py\0docs/product/queue.md\0' >"$list"
    OUT="${WORK}/out-fe${N}.log"
    RC=0
    set +e
    (
        set +u
        FE_FRONTEND_DIR="$fedir"
        # shellcheck disable=SC1090
        . "$FE_SRC"
        FE_FRONTEND_DIR="$fedir" fe_leg_run "$list"
    ) >"$OUT" 2>&1
    RC=$?
    set -e
    exits 0
    says "CLIENT SUSPECT"
    says "offer: ./scripts/rung_tidy.sh --client"
    # The four-line advice it replaced named three different things to do and
    # left the builder to pick; every one of them went looking for which.
    says_not "assert it with ./frontend/scripts/pin_client.sh, regenerate"

    # --- plant 3: the fold's shifted baseline -------------------------------
    fixture_repo offer_shift
    echo "shift" >"$REPO/secrets.act"
    CURRENT="plant 3 — a shifted baseline names --secrets"
    N=$((N + 1))
    OUT="${WORK}/out-fold${N}.log"
    RC=0
    set +e
    (cd "$REPO" && PATH="$REPO/bin:$PATH" ./scripts/pm_fold.sh --only secrets --no-commit) >"$OUT" 2>&1
    RC=$?
    set -e
    exits 0
    says "BASELINE SHIFTED"
    says "./scripts/rung_tidy.sh --secrets"
}

# THE NEGATIVE HALF, and it is what keeps the offer readable: an offer printed
# under every red is an offer nobody reads under the one it is for.
case_a_green_leg_offers_nothing() {
    local eng="${WORK}/engine-green.out"
    printf '  all rules pass\n' >"$eng"
    CURRENT="a green house-rules leg prints no offer"
    _run_house_rules_leg 0 "$eng"
    exits 0
    says "all rules pass"
    says_not "offer:"

    local red="${WORK}/engine-red-nobudget.out"
    printf '  x rule 12: apps/alpha/services.py:3: a red that is not a budget\n' >"$red"
    CURRENT="a red with no budget line prints no offer"
    _run_house_rules_leg 1 "$red"
    exits 1
    says "a red that is not a budget"
    says_not "offer:"
}

echo "== test_rung_tidy — driving scripts/rung_tidy.sh and the three offers"
echo "   scratch: ${WORK}"

case_a_piped_stdout_is_refused
case_an_unknown_argument_is_refused
case_budgets_applies_the_printed_lines_and_only_those
case_a_lowering_is_left_to_the_fold
case_budgets_with_nothing_to_do_is_byte_identical
case_a_reworded_engine_sentence_is_could_not_look
case_client_regenerates_via_pin_client
case_no_npx_is_could_not_look
case_secrets_goes_through_the_fold_and_stages_nothing
case_the_tidy_names_no_baseline_writer_of_its_own
case_an_absent_subject_is_skipped_and_says_why
case_each_refusal_offers_its_own_flag
case_a_green_leg_offers_nothing

echo ""
echo "== ${PASSED} passed, ${FAILED} failed"
drive_finished
[ "$FAILED" -eq 0 ] || exit 1
exit 0
