#!/usr/bin/env bash
# THIS FILE IS EXECUTED, AND IT IS BASH — not POSIX sh, and not zsh. The
# argument, measured on this tree, is `scripts/rung_start.sh`'s header. It is
# not decoration here: this drive was written against a `case "$f" in $pat)`
# glob that MATCHES under bash and silently does not under zsh, and the first
# green reading of a sibling change came from a zsh subshell.
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
# drives: .gitignore .secrets.baseline apps/example/api.py apps/example/models.py frontend/openapi.json frontend/scripts/pin_client.sh frontend/src/api/generated/schema.d.ts manage.py quality/budgets.yaml quality/gate.py scripts/backup.sh scripts/budget_notes.sh scripts/fe_gate.sh scripts/gate_ledger.sh scripts/pm_fold.sh scripts/pm_merge.sh scripts/pm_push.sh scripts/rung_start.sh scripts/rung_tidy.sh scripts/sweep.sh scripts/tests/test_gate_lease.sh
# THE FOLD'S REFUSAL DRIVE. `scripts/pm_fold.sh` COMMITS, UNATTENDED, from
# inside `pm_push.sh --bank` and `pm_merge.sh --bank`, into the tree the gate's
# verdict is about to vouch for. Every one of its teeth was proven once, by
# hand, on the day it was written — which is the state `scripts/backup.sh`,
# `scripts/sweep.sh` and `scripts/pm_merge.sh` were each in before their own
# drives existed.
#
# IT BUILDS ITS OWN REPOSITORIES. Each case runs against a throwaway git repo
# under `mktemp -d`, carrying a COPY of the real `pm_fold.sh` and STUB
# generators, so nothing in this checkout is folded and no real generator is
# run. It needs no docker, no database, no `uv`, no network and no Node.
#
# THE STUBS ARE THE POINT, not a shortcut. The real generators are `npx` +
# Node + a schema export (~a minute, and a could-not-look on any machine
# without Node); what this drive asserts is the FOLD'S OWN behaviour around
# whatever a generator did — which paths it may commit, which it refuses, what
# it does with a stamp that always moves, and what it does with a sentence the
# engine may have reworded. `scripts/pm_fold.sh` makes both generators
# overridable (`DJB_FOLD_PIN_CLIENT`, `DJB_FOLD_UV`) for exactly this reason,
# the same reason `scripts/fe_gate.sh` makes `FE_FRONTEND_DIR` and `FE_PNPM`
# overridable and for the same declared purpose: a mechanism whose every live
# run takes one branch is a mechanism nothing has proven can take the others.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * WHETHER THE REAL GENERATORS ARE RIGHT. `frontend/scripts/pin_client.sh`
#     has its own header and its own exit contract; detect-secrets and
#     `quality/gate.py::check_budgets` are covered by the gate's own legs. This
#     drive asserts the fold's contract WITH them, through stubs.
#   * THE ENGINE'S SENTENCE ACTUALLY BEING THE ONE IT PARSES. Case
#     `budget_sentence_moved` proves the cross-check FIRES when the sentence
#     moves; it cannot prove today's sentence is today's. That pairing is
#     `quality/gate.py`'s own canary population's job.
#   * A REAL GATE BEHIND `--bank`. `pm_push.sh --bank` IS run end to end, in a
#     checkout this drive builds, with its own `pm-push` worktree and its own
#     bare remote — but the gate it runs is a STUB that records what a verdict
#     would key on (using the REAL `gate_measured_tree`) and exits 0. So the
#     ordering property is measured and the ~8-minute run is not entered.
#     Nothing here says the real gate would have been green.
#   * `pm_merge.sh` END TO END. Its placement is asserted structurally, from
#     line numbers DERIVED at run time and compared, never typed; only
#     `pm_push.sh` is driven all the way through. The asymmetry is deliberate —
#     pm_merge `exec`s its gate, so an end-to-end case would have to stub the
#     thing the `exec` replaces this process with — and it is named rather than
#     left to be noticed.
set -euo pipefail

cd "$(dirname "$0")/../.."

# The preamble is not optional: it neutralises an inherited GIT_DIR that would
# aim every fixture `git init` / `commit` / `reset` below at the REAL
# repository. That is not hypothetical — it is the measured incident
# `scripts/tests/drive_preamble.sh` is made of.
[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_pm_fold: scripts/tests/drive_preamble.sh is missing. Refusing to run:" >&2
    echo "   without it an inherited GIT_DIR aims every fixture git command at the real" >&2
    echo "   repository. Exit 2, nothing asserted." >&2
    exit 2
}
# shellcheck source=scripts/tests/drive_preamble.sh
. scripts/tests/drive_preamble.sh
DRIVE_OPTED_IN_TO_FINISH=1

ROOT="$(pwd -P)"
FOLD_SRC="$ROOT/scripts/pm_fold.sh"
PUSH_SRC="$ROOT/scripts/pm_push.sh"
MERGE_SRC="$ROOT/scripts/pm_merge.sh"
LEDGER_SRC="$ROOT/scripts/gate_ledger.sh"
# THE REFUSAL SEAM `gate_ledger.sh` SOURCES. The library opens with
# `. "${BASH_SOURCE[0]%/*}/gate_refuse.sh"`, so any scratch repository that
# hand-copies the ledger has to carry this file beside it or the stub gate dies
# at that line — measured: five reds in
# case_a_stale_client_cannot_bank_green_through_pm_push the night the seam
# landed, all of them the nested `pm_push --bank` exiting 1. The library is
# deliberately intolerant of an absent seam, so the copy list is what stays
# honest; the population is pinned by
# case_every_fixture_that_copies_a_seam_library_copies_the_seam in
# scripts/tests/test_gate_lease.sh.
REFUSE_SRC="$ROOT/scripts/gate_refuse.sh"
# The budget sentence reader `pm_fold.sh` sources, and `rung_tidy.sh` beside it.
NOTES_SRC="$ROOT/scripts/budget_notes.sh"

[ -x "$FOLD_SRC" ] || drive_cannot_look "no executable ${FOLD_SRC} to drive"
[ -r "$NOTES_SRC" ] ||
    drive_cannot_look "no ${NOTES_SRC} — pm_fold.sh sources it and refuses without it, so every fixture below would refuse for this drive's reason"

PASSED=0
FAILED=0
CURRENT=""

ok() {
    PASSED=$((PASSED + 1))
    echo "  ok       ${CURRENT} — $1"
}

bad() {
    FAILED=$((FAILED + 1))
    echo "  FAILED   ${CURRENT} — $1"
}

holds() {
    local label="$1" want="$2" got="$3"
    if [ "$want" = "$got" ]; then
        ok "$label"
    else
        bad "${label} — wanted '${want}', got '${got}'"
    fi
}

says() {
    local label="$1" needle="$2" file="$3"
    if grep -qF -- "$needle" "$file"; then
        ok "$label"
    else
        bad "${label} — does not say \"${needle}\""
        sed 's/^/           | /' "$file"
    fi
}

says_not() {
    local label="$1" needle="$2" file="$3"
    if grep -qF -- "$needle" "$file"; then
        bad "${label} — says \"${needle}\" and should not"
        sed 's/^/           | /' "$file"
    else
        ok "$label"
    fi
}

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-test-pm-fold.XXXXXX")"
drive_require_scratch WORK "$WORK"
drive_at_exit "rm -rf '$WORK'"

# The transcript lives OUTSIDE every fixture. Written inside one it is an
# untracked file, and the fold's own clause 1 then refuses every single case as
# "a dirty tree" — the fixture's own test harness becoming the thing under
# test.
OUT="$WORK/transcript.txt"

CASE_N=0

# make_repo <name> — a throwaway checkout carrying all four derived files, one
# innocent non-derived file to be the stray victim, and stub generators.
#
# The stubs are steered by optional files the case writes into the fixture:
#   pin.act      what frontend/scripts/pin_client.sh should do
#                ("noop" | "drift" | "fail")
#   secrets.act  what `uv run detect-secrets scan` should do
#                ("stamp" | "shift" | "fail")
#   budget.out   verbatim stdout for `uv run python <budget reader>`
# Those three, and bin/, are put in .git/info/exclude so the fold's OWN census
# cannot see them — a steering file counted as a stray would make every case
# exit 2 for the harness's reason instead of the case's.
make_repo() {
    CASE_N=$((CASE_N + 1))
    REPO="$WORK/repo-${CASE_N}-$1"
    drive_require_scratch REPO "$REPO"
    mkdir -p "$REPO/scripts" "$REPO/frontend/scripts" "$REPO/frontend/src/api/generated" \
        "$REPO/quality" "$REPO/src" "$REPO/bin"

    cp "$FOLD_SRC" "$REPO/scripts/pm_fold.sh"
    chmod +x "$REPO/scripts/pm_fold.sh"
    # THE SENTENCE READER, COPIED BESIDE IT. `pm_fold.sh` sources
    # `scripts/budget_notes.sh` for step (d) — the same parser
    # `scripts/rung_tidy.sh` reads the other two shapes with — and it refuses at
    # exit 2 when the file is not there. A fixture that copied the script and
    # not the library would red every case in this drive for the harness's
    # reason: measured, 82 failed assertions on the first run of this change.
    # It is the same class `test_gate_lease.sh::case_every_fixture_that_copies_a
    # _seam_library_copies_the_seam` censuses one seam over.
    cp "$NOTES_SRC" "$REPO/scripts/budget_notes.sh"

    # The non-derived victim. A destructive demonstration creates its own
    # victim; this is the fold's.
    echo "a file no fold has any business touching" >"$REPO/src/oops.txt"

    printf '{\n  "openapi": "3.1.0",\n  "paths": {}\n}\n' >"$REPO/frontend/openapi.json"
    printf 'export type paths = Record<string, never>;\n' \
        >"$REPO/frontend/src/api/generated/schema.d.ts"

    # STAMPLESS, because that is what a committed baseline looks like in this
    # tree: `detect-secrets scan` writes `"generated_at"` on every run
    # whether or not anything moved, so two lanes that both re-scan conflict on
    # that one line and nothing else. The fold STRIPS the stamp before it
    # compares and before it commits, so the committed file never carries one —
    # and this fixture is the committed shape, not the scanner's output shape.
    # The `uv` stub below still WRITES a stamp, because the real scanner does.
    cat >"$REPO/.secrets.baseline" <<'BASELINE'
{
  "version": "1.5.0",
  "results": {}
}
BASELINE

    # Two sections, and one key carrying `::` — every `out_schema_fields` key in
    # the real file does, and the parser's "find the LAST `: N`" rule is the
    # only reason such a key splits correctly.
    cat >"$REPO/quality/budgets.yaml" <<'BUDGETS'
service_function_length:
  apps/alpha/services.py: 40 # provenance: the comment that must survive
  apps/beta/services.py: 55

out_schema_fields:
  apps/alpha/schemas.py::ThingOut: 9
BUDGETS

    echo "print('nothing')" >"$REPO/manage.py"

    # --- the stubs ----------------------------------------------------------
    cat >"$REPO/frontend/scripts/pin_client.sh" <<STUB
#!/usr/bin/env bash
set -euo pipefail
act="\$(cat "$REPO/pin.act" 2>/dev/null || echo noop)"
case "\$act" in
fail)
    echo "stub pin_client: the generator could not produce a client" >&2
    exit 1
    ;;
drift)
    printf '{\n  "openapi": "3.1.0",\n  "paths": {"/api/v1/things": {}}\n}\n' \
        >"$REPO/frontend/openapi.json"
    printf 'export type paths = { "/api/v1/things": unknown };\n' \
        >"$REPO/frontend/src/api/generated/schema.d.ts"
    echo "stub pin_client: wrote a regenerated contract"
    ;;
stray)
    echo "a generator wrote here and nobody asked it to" >"$REPO/src/side-effect.txt"
    echo "stub pin_client: wrote a side effect"
    ;;
straydir)
    mkdir -p "$REPO/brandnew/deeper"
    echo "x" >"$REPO/brandnew/deeper/output.txt"
    echo "stub pin_client: wrote into a directory that did not exist"
    ;;
noop) echo "stub pin_client: the committed contract is already current" ;;
esac
STUB
    chmod +x "$REPO/frontend/scripts/pin_client.sh"

    # `uv`: a shim answering the two shapes pm_fold.sh calls it with —
    # `uv run python manage.py introspect`, `uv run detect-secrets scan ...`,
    # and `uv run python <the generated budget reader>`.
    cat >"$REPO/bin/uv" <<STUB
#!/usr/bin/env bash
set -euo pipefail
case "\$*" in
*"manage.py introspect"*)
    echo '{"stub": "introspect"}'
    ;;
*"detect-secrets scan"*)
    act="\$(cat "$REPO/secrets.act" 2>/dev/null || echo stamp)"
    case "\$act" in
    fail)
        echo "stub detect-secrets: refused" >&2
        exit 1
        ;;
    shift)
        cat >"$REPO/.secrets.baseline" <<'B'
{
  "version": "1.5.0",
  "results": {"src/oops.txt": [{"type": "Secret Keyword"}]},
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

    # `/.rung/` is a TRACKED .gitignore line here, exactly as it is in the real
    # tree, because that is the fold's own precondition for writing the schema
    # dump at all — and `case_an_unignored_rung_dir_is_skipped` is the case that
    # removes it.
    printf '/.rung/\n' >"$REPO/.gitignore"

    git -C "$REPO" init -q
    git -C "$REPO" config user.email drive@example.invalid
    git -C "$REPO" config user.name "fold drive"
    git -C "$REPO" config commit.gpgsign false
    printf 'bin/\npin.act\nsecrets.act\nbudget.out\nmeasured-tree.txt\n.wt/\n' \
        >"$REPO/.git/info/exclude"
    git -C "$REPO" add -A
    git -C "$REPO" commit -q -m "base"
    BEFORE_HEAD="$(git -C "$REPO" rev-parse HEAD)"
    BEFORE_TREE="$(git -C "$REPO" rev-parse "HEAD^{tree}")"
}

# run_fold [extra args...] — runs the fixture's fold with the stub toolchain on
# PATH and the transcript captured outside the fixture. Never piped: the exit
# status is the whole point, and this drive exists partly to assert it.
run_fold() {
    set +e
    (
        cd "$REPO" || exit 2
        PATH="$REPO/bin:$PATH" \
            DJB_FOLD_PIN_CLIENT="$REPO/frontend/scripts/pin_client.sh" \
            DJB_FOLD_UV="uv" \
            ./scripts/pm_fold.sh "$@"
    ) >"$OUT" 2>&1
    RC=$?
    set -e
}

# ---------------------------------------------------------------------------
# CLAUSE 1 — a dirty tree is refused
# ---------------------------------------------------------------------------
case_dirty_tree_is_refused() {
    CURRENT="a dirty tree is refused"
    make_repo dirty
    echo "somebody's unsaved work" >>"$REPO/src/oops.txt"
    run_fold
    holds "exit 2" 2 "$RC"
    says "names the checkout's uncommitted changes" "has uncommitted changes" "$OUT"
    says "says a fold folds a COMMITTED tree" "A fold folds a COMMITTED tree" "$OUT"
    says "says nothing was committed" "Nothing was regenerated and nothing was committed" "$OUT"
    holds "HEAD did not move" "$BEFORE_HEAD" "$(git -C "$REPO" rev-parse HEAD)"
}

# ---------------------------------------------------------------------------
# CLAUSE 4 — unknown flags, including the WIRING'S OWN flags
# ---------------------------------------------------------------------------
case_unknown_flag_is_refused() {
    CURRENT="an unknown flag is refused"
    make_repo flag
    run_fold --fold-everything
    holds "--fold-everything: exit 2" 2 "$RC"
    says "--fold-everything: names the argument" "unknown argument '--fold-everything'" "$OUT"
    holds "--fold-everything: HEAD did not move" "$BEFORE_HEAD" "$(git -C "$REPO" rev-parse HEAD)"

    # A flag that LOOKS like the wiring's own flag is still not this script's.
    run_fold --no-fold
    holds "--no-fold: exit 2" 2 "$RC"
    says "--no-fold: names the argument" "unknown argument '--no-fold'" "$OUT"
    says "--no-fold: says whose flag it is" "belong to pm_push.sh and" "$OUT"

    run_fold --bank
    holds "--bank: exit 2" 2 "$RC"
    says "--bank: names the argument" "unknown argument '--bank'" "$OUT"

    run_fold --help
    holds "--help: exit 0" 0 "$RC"
    says "--help: prints the four clauses" "The four clauses" "$OUT"
    holds "--help: HEAD did not move" "$BEFORE_HEAD" "$(git -C "$REPO" rev-parse HEAD)"
}

# ---------------------------------------------------------------------------
# CLAUSE 4 — a piped stdout. The STATUS is asserted, not only the sentence:
# the whole defect this guard closes is a pipe replacing the exit status.
# ---------------------------------------------------------------------------
case_piped_stdout_is_refused() {
    CURRENT="a piped stdout is refused"
    make_repo pipe
    set +e
    (
        cd "$REPO" || exit 2
        PATH="$REPO/bin:$PATH" ./scripts/pm_fold.sh 2>&1 | cat
        exit "${PIPESTATUS[0]}"
    ) >"$OUT" 2>&1
    RC=$?
    set -e
    holds "exit 2" 2 "$RC"
    says "says it refuses pipes" "pm_fold refuses pipes" "$OUT"
    holds "HEAD did not move" "$BEFORE_HEAD" "$(git -C "$REPO" rev-parse HEAD)"
}

# ---------------------------------------------------------------------------
# CLAUSE 2 — TOOTH ONE. A generator's side effect outside the derived list.
# ---------------------------------------------------------------------------
case_out_of_list_write_is_exit_2() {
    CURRENT="an out-of-list write is exit 2 naming the file"
    make_repo stray
    echo "stray" >"$REPO/pin.act"
    run_fold
    holds "exit 2" 2 "$RC"
    says "says the fold went outside the list" "modified a file OUTSIDE the derived list" "$OUT"
    says "NAMES the stray path" "src/side-effect.txt" "$OUT"
    says "says nothing was committed" "NOTHING WAS COMMITTED" "$OUT"
    holds "HEAD did not move" "$BEFORE_HEAD" "$(git -C "$REPO" rev-parse HEAD)"
    # THE EVIDENCE IS LEFT IN THE TREE. A refusal that cleaned up after itself
    # would leave the reader nothing to read.
    if [ -f "$REPO/src/side-effect.txt" ]; then
        ok "the evidence is still in the tree"
    else
        bad "the stray file was cleaned up — the evidence is gone"
    fi
}

# `-uall` is load-bearing: a stray inside a WHOLLY untracked directory is
# hidden behind the directory name without it, and a stray this census cannot
# name is a stray it cannot refuse on.
case_stray_inside_an_untracked_directory_is_named() {
    CURRENT="a stray inside an untracked directory is NAMED, not hidden behind it"
    make_repo stray_dir
    echo "straydir" >"$REPO/pin.act"
    run_fold
    holds "exit 2" 2 "$RC"
    says "names the FILE, not just the directory" "brandnew/deeper/output.txt" "$OUT"
    holds "HEAD did not move" "$BEFORE_HEAD" "$(git -C "$REPO" rev-parse HEAD)"
}

# ---------------------------------------------------------------------------
# THE NOTHING-TO-FOLD PATH, and the generated_at STRIP that makes it reachable
# at all: the scan writes a stamp on every run, so without the strip the
# fold would find a shift every time and this path would never be taken.
# ---------------------------------------------------------------------------
case_nothing_to_fold_makes_no_commit() {
    CURRENT="nothing to fold makes no commit"
    make_repo nothing
    run_fold
    holds "exit 0" 0 "$RC"
    says "says NOTHING TO FOLD" "NOTHING TO FOLD" "$OUT"
    says "says every derived file already agrees" "already agrees with this checkout" "$OUT"
    holds "HEAD did not move" "$BEFORE_HEAD" "$(git -C "$REPO" rev-parse HEAD)"
    holds "the tree is clean" "" "$(git -C "$REPO" status --porcelain)"
}

case_the_fold_restores_on_no_shift_from_a_stampless_file() {
    CURRENT="a stamp-only scan of a stampless baseline is not a shift"
    make_repo stamp
    STAMP_BEFORE="$(git -C "$REPO" show HEAD:.secrets.baseline)"
    echo "stamp" >"$REPO/secrets.act" # the stub writes a stamp and nothing else
    run_fold
    holds "exit 0" 0 "$RC"
    says "says only the stamp differed" "only the generated_at stamp the scan writes" "$OUT"
    says "says NOTHING TO FOLD" "NOTHING TO FOLD" "$OUT"
    holds "HEAD did not move" "$BEFORE_HEAD" "$(git -C "$REPO" rev-parse HEAD)"
    # RESTORED BYTE FOR BYTE, which is the whole keep-behavior: without it every
    # fold commits churn forever.
    holds "the baseline was restored byte-for-byte" "$STAMP_BEFORE" "$(cat "$REPO/.secrets.baseline")"
    # And what was restored carries NO stamp — the committed shape.
    holds "the restored file carries no stamp" "0" \
        "$(grep -c '"generated_at"' "$REPO/.secrets.baseline" || true)"
}

case_the_fold_commits_a_stampless_baseline_on_a_real_shift() {
    CURRENT="a real shift is committed, and the committed file carries no stamp"
    make_repo shift
    echo "shift" >"$REPO/secrets.act" # the stub adds a result AND writes a stamp
    run_fold
    holds "exit 0" 0 "$RC"
    says "says the baseline SHIFTED" "BASELINE SHIFTED" "$OUT"
    holds "HEAD moved" "1" "$([ "$BEFORE_HEAD" != "$(git -C "$REPO" rev-parse HEAD)" ] && echo 1 || echo 0)"
    holds "the subject" "fold: baseline shifted" "$(git -C "$REPO" log -1 --format=%s)"
    holds "exactly one path in the commit" ".secrets.baseline" \
        "$(git -C "$REPO" show --name-only --format= HEAD | grep -c . >/dev/null && git -C "$REPO" show --name-only --format= HEAD | tr '\n' ' ' | sed 's/ *$//')"
    holds "the tree is clean afterwards" "" "$(git -C "$REPO" status --porcelain)"
    # THE CRITERION: the scanner wrote a stamp, and what reached the
    # commit does not carry one. Read out of the COMMIT, not the worktree.
    holds "the committed baseline carries no stamp" "0" \
        "$(git -C "$REPO" show HEAD:.secrets.baseline | grep -c '"generated_at"' || true)"
    # And the shift itself survived the strip — a strip that also ate the
    # results would pass the line above and prove nothing.
    holds "the shift survived the strip" "1" \
        "$(git -C "$REPO" show HEAD:.secrets.baseline | grep -c 'src/oops.txt' || true)"
    # Still valid JSON. The trailing comma a line-delete leaves behind is the
    # way this strip fails, and it fails silently until something parses it.
    holds "the committed baseline is valid JSON" "VALID" \
        "$(git -C "$REPO" show HEAD:.secrets.baseline |
            python3 -c 'import json,sys; json.load(sys.stdin); print("VALID")' 2>&1 | tail -1)"
}

# A stamp count this strip is not built for is a could-not-look, never a silent
# pass — the declared second-always-moving-field blind spot, with a tooth on it.
# BOTH directions: zero stamps after the scan (the format moved) and two (a
# second always-moving field arrived).
case_an_unrecognised_stamp_shape_is_refused() {
    CURRENT="a baseline whose stamp shape moved is could-not-look"
    make_repo stamp_shape
    cat >"$REPO/bin/uv" <<STUB
#!/usr/bin/env bash
set -euo pipefail
case "\$*" in
*"manage.py introspect"*) echo '{"stub": "introspect"}' ;;
*"detect-secrets scan"*)
    cat >"$REPO/.secrets.baseline" <<'B'
{
  "version": "1.6.0",
  "results": {},
  "produced_at": "2026-06-06T06:06:06Z"
}
B
    ;;
*python*) echo "### budget-check: notes=0 problems=0" ;;
esac
STUB
    chmod +x "$REPO/bin/uv"
    run_fold
    holds "zero stamps: exit 2" 2 "$RC"
    says "zero stamps: names the count the scan wrote" "generated_at line(s)" "$OUT"
    says "zero stamps: says the format has moved" "format has moved under this strip" "$OUT"
    holds "zero stamps: HEAD did not move" "$BEFORE_HEAD" "$(git -C "$REPO" rev-parse HEAD)"

    # TWO stamps — a second always-moving field, which is the header's declared
    # blind spot arriving. Same refusal, and it is a case rather than a comment
    # because a strip built on "pop one key" would sail straight through it.
    make_repo stamp_shape_two
    cat >"$REPO/bin/uv" <<STUB
#!/usr/bin/env bash
set -euo pipefail
case "\$*" in
*"manage.py introspect"*) echo '{"stub": "introspect"}' ;;
*"detect-secrets scan"*)
    cat >"$REPO/.secrets.baseline" <<'B'
{
  "version": "1.6.0",
  "results": {},
  "generated_at": "2026-06-06T06:06:06Z",
  "plugins": {"generated_at": "2026-06-06T06:06:06Z"}
}
B
    ;;
*python*) echo "### budget-check: notes=0 problems=0" ;;
esac
STUB
    chmod +x "$REPO/bin/uv"
    run_fold
    holds "two stamps: exit 2" 2 "$RC"
    says "two stamps: names the count the scan wrote" "2 generated_at line(s)" "$OUT"
    holds "two stamps: HEAD did not move" "$BEFORE_HEAD" "$(git -C "$REPO" rev-parse HEAD)"
}

# THE MIGRATION PATH, and it is the reason the strip is not a one-time edit to
# the tracked file. A baseline that arrives carrying a stamp — a revert, a
# hand-resolved merge, a clone from before the strip — is stripped and committed,
# even when the RESULTS did not move. Without this branch the fold restores the
# stamped bytes forever and the conflict class comes straight back.
case_a_committed_stamp_is_stripped_even_when_nothing_shifted() {
    CURRENT="a stamped committed baseline is stripped, results unmoved"
    make_repo stamped_commit
    cat >"$REPO/.secrets.baseline" <<'BASELINE'
{
  "version": "1.5.0",
  "results": {},
  "generated_at": "2026-01-01T00:00:00Z"
}
BASELINE
    git -C "$REPO" add .secrets.baseline
    git -C "$REPO" commit -q -m "a baseline from before the strip"
    BEFORE_HEAD="$(git -C "$REPO" rev-parse HEAD)"
    echo "stamp" >"$REPO/secrets.act" # the results do NOT move
    run_fold
    holds "exit 0" 0 "$RC"
    says "says the always-moving fields were removed" "the always-moving fields were removed" "$OUT"
    says "and names the counts it found" "(1 generated_at, 0 line_number)" "$OUT"
    holds "HEAD moved" "1" "$([ "$BEFORE_HEAD" != "$(git -C "$REPO" rev-parse HEAD)" ] && echo 1 || echo 0)"
    holds "the committed baseline carries no stamp" "0" \
        "$(git -C "$REPO" show HEAD:.secrets.baseline | grep -c '"generated_at"' || true)"
    holds "the tree is clean afterwards" "" "$(git -C "$REPO" status --porcelain)"
}

# THE CLASS ITSELF, driven rather than asserted. Two
# lanes that each re-scan the baseline conflict on the stamp and on nothing
# else. The control below is the half that makes this one evidence: it plants
# the stamp back and shows the same two lanes conflicting.
case_two_lanes_baselines_merge_clean_without_the_stamp() {
    CURRENT="two lanes' stampless baselines merge clean"
    _two_lane_merge stampless
    holds "merge exit 0" 0 "$MERGE_RC"
    says_not "no conflict marker in the merged file" "<<<<<<<" "$MERGE_FILE"
    holds "both lanes' results survived the merge" "yes yes" \
        "$(grep -q 'aaa_top.md' "$MERGE_FILE" && echo -n 'yes ' || echo -n 'no '
            grep -q 'zzz_bottom.md' "$MERGE_FILE" && echo 'yes' || echo 'no')"
}

# THE OTHER ALWAYS-MOVING FIELD, driven the same way and for the same reason.
# `line_number` is the half the CONSUMER pays: this tree's own baseline records
# zero results, so nothing here moves it, while a product with real results
# rewrites every recorded line whenever anything is inserted above a secret.
#
# THE PLANT IS THE REAL MECHANISM AND NOT A TRANSCRIPTION OF IT. Both lanes run
# the FOLD, against a stub scanner that computes real line numbers off the
# tracked file — so the baselines being merged are the ones the fold actually
# wrote. The two lanes insert their filler THIRTY LINES APART so the SOURCE file
# merges cleanly on its own: a case whose source file also conflicted would be
# naming the wrong cause. Measured on the baseline bytes before this change,
# with the numbers kept: `git merge` exit 1, two conflicted regions in
# `.secrets.baseline`, both of them a `"line_number": N` line, and no other file
# conflicted.
case_two_lanes_baselines_merge_clean_without_line_numbers() {
    CURRENT="two lanes' numberless baselines merge clean"
    _two_lane_fold_merge
    holds "merge exit 0" 0 "$MERGE_RC"
    says_not "no conflict marker in the merged file" "<<<<<<<" "$MERGE_FILE"
    holds "the merged baseline carries no line numbers" "0" \
        "$(grep -c '"line_number"' "$MERGE_FILE" || true)"
    # BOTH LANES' RESULTS SURVIVED. A merge that resolved the conflict by
    # losing a result would be a baseline that stopped looking for a secret.
    holds "both lanes' results survived the merge" "yes yes" \
        "$(grep -q 'mmm_keys.md' "$MERGE_FILE" && printf 'yes ' || printf 'no '
            grep -q 'nnn_other.md' "$MERGE_FILE" && echo 'yes' || echo 'no')"
}

# _two_lane_fold_merge — a scratch repository whose committed baseline holds two
# results in one file; lane A inserts ten lines at the top of that file, lane B
# three lines thirty lines further down AND a secret in an unrelated file; both
# lanes FOLD; lane A merges lane B. Sets MERGE_RC, MERGE_LOG, MERGE_FILE. Its
# own victim, built here, never this checkout's.
_two_lane_fold_merge() {
    local R
    CASE_N=$((CASE_N + 1))
    R="$WORK/fold-merge-${CASE_N}"
    drive_require_scratch R "$R"
    mkdir -p "$R/scripts" "$R/bin"
    cp "$FOLD_SRC" "$R/scripts/pm_fold.sh"
    chmod +x "$R/scripts/pm_fold.sh"
    cp "$NOTES_SRC" "$R/scripts/budget_notes.sh"

    # The stub scanner: detect-secrets' own output shape, with REAL line
    # numbers read off the tracked files, because the whole subject of this case
    # is what happens to those numbers.
    cat >"$R/bin/uv" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
case "$*" in
*"detect-secrets scan"*)
    python3 - . <<'PYSCAN'
import hashlib
import json
import os
import sys

root = sys.argv[1]
results = {}
for name in sorted(os.listdir(root)):
    if not name.endswith(".md"):
        continue
    entries = []
    with open(os.path.join(root, name)) as fh:
        for i, line in enumerate(fh, 1):
            if "PLANTED-KEY" in line:
                entries.append({
                    "type": "Secret Keyword",
                    "filename": name,
                    "hashed_secret": hashlib.sha1(line.strip().encode()).hexdigest(),
                    "is_verified": False,
                    "line_number": i,
                })
    if entries:
        results[name] = entries
with open(".secrets.baseline", "w") as fh:
    fh.write(json.dumps(
        {"version": "1.5.0", "results": results,
         "generated_at": "2026-06-06T06:06:06Z"}, indent=2) + "\n")
PYSCAN
    ;;
esac
STUB
    chmod +x "$R/bin/uv"

    python3 - "$R" <<'PYSEED'
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
(root / "mmm_keys.md").write_text(
    "".join("body line %d\n" % i for i in range(1, 41))
    + "alpha PLANTED-KEY one\nalpha PLANTED-KEY two\n"
)
(root / "nnn_other.md").write_text("nothing here yet\n")
(root / ".secrets.baseline").write_text('{\n  "version": "1.5.0",\n  "results": {}\n}\n')
PYSEED

    git -C "$R" init -q
    git -C "$R" symbolic-ref HEAD refs/heads/main
    git -C "$R" config user.email drive@example.invalid
    git -C "$R" config user.name "fold drive"
    git -C "$R" config commit.gpgsign false
    printf 'bin/\n' >"$R/.git/info/exclude"
    git -C "$R" add -A
    git -C "$R" commit -q -m base
    _fold_in "$R"

    git -C "$R" checkout -q -b lane-a main
    python3 - "$R" <<'PYLANEA'
import pathlib
import sys

p = pathlib.Path(sys.argv[1]) / "mmm_keys.md"
lines = p.read_text().splitlines(True)
p.write_text("".join(["filler-a\n"] * 10 + lines))
PYLANEA
    git -C "$R" commit -q -am "lane A: ten lines at the top"
    _fold_in "$R"

    git -C "$R" checkout -q -b lane-b main
    python3 - "$R" <<'PYLANEB'
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
p = root / "mmm_keys.md"
lines = p.read_text().splitlines(True)
p.write_text("".join(lines[:30] + ["filler-b\n"] * 3 + lines[30:]))
with open(root / "nnn_other.md", "a") as fh:
    fh.write("beta PLANTED-KEY three\n")
PYLANEB
    git -C "$R" commit -q -am "lane B: three lines far from lane A's, and an unrelated file"
    _fold_in "$R"

    git -C "$R" checkout -q lane-a
    MERGE_LOG="$WORK/fold-merge-${CASE_N}.log"
    MERGE_FILE="$R/.secrets.baseline"
    set +e
    git -C "$R" merge --no-edit lane-b >"$MERGE_LOG" 2>&1
    MERGE_RC=$?
    set -e
}

# _fold_in <repo> — the fixture's own fold, with the stub toolchain on PATH.
_fold_in() {
    set +e
    (cd "$1" && PATH="$1/bin:$PATH" DJB_FOLD_UV=uv ./scripts/pm_fold.sh) >>"$OUT" 2>&1
    set -e
}

# ---------------------------------------------------------------------------
# --ONLY AND --NO-COMMIT. `scripts/rung_tidy.sh --secrets` is the caller these
# exist for, and the property that matters is that the tree's ONE legal baseline
# writer is still this file: the tidy invokes the fold rather than growing a
# second scan line of its own.
# ---------------------------------------------------------------------------
case_only_secrets_no_commit_rescans_and_stages_nothing() {
    CURRENT="--only secrets --no-commit rescans, and stages nothing"
    make_repo only_secrets
    echo "shift" >"$REPO/secrets.act"
    run_fold --only secrets --no-commit
    holds "exit 0" 0 "$RC"
    says "says which steps it skipped" "--only secrets does not name this step" "$OUT"
    says "the scan ran" "BASELINE SHIFTED" "$OUT"
    says "and it says nothing was committed" "pm_fold: --no-commit" "$OUT"
    holds "HEAD did not move" "$BEFORE_HEAD" "$(git -C "$REPO" rev-parse HEAD)"
    holds "nothing is staged" "" "$(git -C "$REPO" diff --cached --name-only)"
    holds "the working tree shows only the baseline" " M .secrets.baseline" \
        "$(git -C "$REPO" status --porcelain)"
    holds "the rewritten baseline carries no stamp" "0" \
        "$(grep -c '"generated_at"' "$REPO/.secrets.baseline" || true)"
    holds "the rewritten baseline carries no line numbers" "0" \
        "$(grep -c '"line_number"' "$REPO/.secrets.baseline" || true)"
    # The step list is CLOSED. A typo that fell through to "select nothing"
    # would be a fold that ran no step in the voice of a clean tree.
    run_fold --only secretz --no-commit
    holds "an unknown step name is exit 2" 2 "$RC"
    says "names the step it does not know" "--only names 'secretz'" "$OUT"
    # And --no-commit alone is a refusal: a WHOLE fold that commits nothing
    # leaves a tree the next bank keys its verdict on and nobody wrote down.
    run_fold --no-commit
    holds "--no-commit without --only is exit 2" 2 "$RC"
    says "says why" "legal only with --only" "$OUT"
}

case_the_stamp_is_what_conflicted() {
    CURRENT="the stamp is what conflicted (the control)"
    _two_lane_merge stamped
    holds "merge exit 1" 1 "$MERGE_RC"
    says "git called it a conflict" "CONFLICT (content): Merge conflict in .secrets.baseline" "$MERGE_LOG"
    says "the conflict hunk is the stamp" "generated_at" "$MERGE_FILE"
    # And it is ONLY the stamp: the two result blocks are far apart and merge
    # on their own, so there is exactly ONE conflicted region. A control that
    # conflicted for a second reason would not be naming the cause the case
    # above removes.
    holds "exactly one conflicted region" "1" "$(grep -c '^<<<<<<<' "$MERGE_FILE" || true)"
    holds "both lanes' results still merged around it" "yes yes" \
        "$(grep -q 'aaa_top.md' "$MERGE_FILE" && printf 'yes ' || printf 'no '
            grep -q 'zzz_bottom.md' "$MERGE_FILE" && echo 'yes' || echo 'no')"
}

# _two_lane_merge <stamped|stampless> — a scratch repository whose `main` holds
# a baseline in the named shape; branch `x` adds a result block at the top of
# `results`, branch `y` one at the bottom; `x` merges `y`. Sets MERGE_RC,
# MERGE_LOG and MERGE_FILE. Its own victim, built here, never this checkout's.
MERGE_RC=0
MERGE_LOG=""
MERGE_FILE=""
_two_lane_merge() {
    local mode="$1" R
    CASE_N=$((CASE_N + 1))
    R="$WORK/merge-${CASE_N}-${mode}"
    drive_require_scratch R "$R"
    mkdir -p "$R"
    git -C "$R" init -q -b main .
    git -C "$R" config user.email drive@example.invalid
    git -C "$R" config user.name "fold drive"
    git -C "$R" config commit.gpgsign false

    if [ "$mode" = stamped ]; then
        cat >"$R/.secrets.baseline" <<'B'
{
  "version": "1.5.0",
  "results": {
    "middle.md": [
      {
        "type": "Secret Keyword",
        "hashed_secret": "1111111111111111111111111111111111111111",
        "is_verified": false,
        "line_number": 1
      }
    ]
  },
  "generated_at": "2026-01-01T00:00:00Z"
}
B
    else
        cat >"$R/.secrets.baseline" <<'B'
{
  "version": "1.5.0",
  "results": {
    "middle.md": [
      {
        "type": "Secret Keyword",
        "hashed_secret": "1111111111111111111111111111111111111111",
        "is_verified": false,
        "line_number": 1
      }
    ]
  }
}
B
    fi
    git -C "$R" add .secrets.baseline
    git -C "$R" commit -q -m base

    local lane
    for lane in x y; do
        git -C "$R" checkout -q -b "$lane" main
        python3 - "$R/.secrets.baseline" "$lane" "$mode" <<'PY'
import json, sys

path, lane, mode = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path) as fh:
    data = json.load(fh)
entry = [{
    "type": "Secret Keyword",
    "hashed_secret": ("2" if lane == "x" else "3") * 40,
    "is_verified": False,
    "line_number": 1,
}]
results = data["results"]
# One lane writes at the top of `results`, the other at the bottom, so the two
# result hunks are far apart and git merges them on its own. Whatever is left
# is the stamp, or nothing.
if lane == "x":
    data["results"] = {"aaa_top.md": entry, **results}
else:
    data["results"] = {**results, "zzz_bottom.md": entry}
if mode == "stamped":
    # The scanner rewrites this on EVERY run, so two lanes that both re-scanned
    # carry two different values here by construction.
    data["generated_at"] = "2026-09-11T00:00:00Z" if lane == "x" else "2026-09-12T00:00:00Z"
with open(path, "w") as fh:
    fh.write(json.dumps(data, indent=2) + "\n")
PY
        git -C "$R" commit -q -am "lane ${lane}"
    done

    git -C "$R" checkout -q x
    MERGE_LOG="$WORK/merge-${CASE_N}-${mode}.log"
    MERGE_FILE="$R/.secrets.baseline"
    set +e
    git -C "$R" merge --no-edit y >"$MERGE_LOG" 2>&1
    MERGE_RC=$?
    set -e
}

# ---------------------------------------------------------------------------
# THE CONTRACT — criterion 9's closure. A stale committed client is FOLDED at
# the bank, under a named commit, or refused. Never a silent green.
# ---------------------------------------------------------------------------
case_contract_drift_is_one_commit_of_derived_paths() {
    CURRENT="a planted contract drift is one commit of derived paths only"
    make_repo contract
    echo "drift" >"$REPO/pin.act"
    run_fold
    holds "exit 0" 0 "$RC"
    holds "the subject" "fold: contract regenerated" "$(git -C "$REPO" log -1 --format=%s)"
    holds "exactly the two contract paths" \
        "frontend/openapi.json frontend/src/api/generated/schema.d.ts" \
        "$(git -C "$REPO" show --name-only --format= HEAD | sort | tr '\n' ' ' | sed 's/ *$//')"
    # THE BODY carries the provenance of the tree it folded.
    BODY="$(git -C "$REPO" log -1 --format=%b)"
    printf '%s\n' "$BODY" >"$WORK/body.txt"
    says "body carries the pre-fold TREE" "Pre-fold tree: ${BEFORE_TREE}" "$WORK/body.txt"
    says "body carries the pre-fold HEAD" "Pre-fold HEAD: ${BEFORE_HEAD}" "$WORK/body.txt"
    says "body says a ceiling is never raised" "ceiling is never raised here" "$WORK/body.txt"
    holds "the tree is clean afterwards" "" "$(git -C "$REPO" status --porcelain)"
    # `.rung/introspect.json` was written and is NOT in the commit: gitignored
    # by the real tree, and here invisible because the fixture never tracks it.
    if [ -f "$REPO/.rung/introspect.json" ]; then
        ok "the schema dump was regenerated"
    else
        bad "the schema dump was not regenerated"
    fi
    says_not "the schema dump is NOT in the commit" ".rung/introspect.json" \
        <(git -C "$REPO" show --name-only --format= HEAD)
}

# THE FOLD MUST NOT MANUFACTURE ITS OWN VICTIM. Found by this drive on its
# first run: with `/.rung/` absent from .gitignore the schema dump is a stray,
# the census refuses at exit 2, and the fold is stopped by the one file it wrote
# on purpose. The step now declines instead, with the reason printed.
case_an_unignored_rung_dir_is_skipped() {
    CURRENT="an un-ignored .rung/ makes the schema step decline, not manufacture a stray"
    make_repo rung_unignored
    git -C "$REPO" rm -q --cached .gitignore >/dev/null
    rm -f "$REPO/.gitignore"
    git -C "$REPO" commit -q -m "a checkout that does not ignore .rung/"
    BEFORE_HEAD="$(git -C "$REPO" rev-parse HEAD)"
    run_fold
    holds "exit 0, not a self-inflicted exit 2" 0 "$RC"
    says "says why it declined" "is NOT git-ignored in this checkout" "$OUT"
    says_not "and no stray was refused on" "modified a file OUTSIDE the derived list" "$OUT"
    if [ -f "$REPO/.rung/introspect.json" ]; then
        bad "it wrote the dump anyway"
    else
        ok "and it did not write the dump"
    fi
    holds "HEAD did not move" "$BEFORE_HEAD" "$(git -C "$REPO" rev-parse HEAD)"
}

case_a_failed_generator_commits_nothing() {
    CURRENT="a failed generator commits nothing"
    make_repo genfail
    echo "fail" >"$REPO/pin.act"
    run_fold
    holds "exit 2" 2 "$RC"
    says "names the generator's exit" "the client generator exited 1" "$OUT"
    says "says nothing was committed" "Nothing was committed" "$OUT"
    holds "HEAD did not move" "$BEFORE_HEAD" "$(git -C "$REPO" rev-parse HEAD)"
}

# ---------------------------------------------------------------------------
# CLAUSE 3 — TOOTH TWO. The fold never raises a ceiling.
# ---------------------------------------------------------------------------
# Both NON-lowering engine shapes, fed verbatim in the wording
# `quality/gate.py::check_budgets` actually prints them in. Neither carries the
# lowering sentence, so both are UNRECOGNISED rather than recognised-and-declined
# — which is the stronger property: there is no branch in which a raise is read.
case_a_budget_raise_is_never_applied() {
    CURRENT="a budget RAISE is never applied"
    make_repo raise
    BUDGETS_BEFORE="$(cat "$REPO/quality/budgets.yaml")"
    cat >"$REPO/budget.out" <<'ENGINE'
budget: service_function_length apps/alpha/services.py — do_thing (lines 10-99) grew to 91, past the recorded ceiling 40 — shrink it, or raise the ceiling in quality/budgets.yaml in a diff a reviewer sees. The line to paste, verbatim:
  apps/alpha/services.py: 91
budget: out_schema_fields has no recorded ceiling for apps/gamma/schemas.py::NewOut (measured 4) — a new subject fails until a human measures it and commits the number. The line to paste under `out_schema_fields:` in quality/budgets.yaml:
  apps/gamma/schemas.py::NewOut: 4
### budget-check: notes=0 problems=2
ENGINE
    run_fold
    holds "exit 0" 0 "$RC"
    says "says a raise stays a human diff" "raise is a decision that stays a human diff" "$OUT"
    holds "budgets.yaml is byte-identical" "$BUDGETS_BEFORE" "$(cat "$REPO/quality/budgets.yaml")"
    says "says NOTHING TO FOLD" "NOTHING TO FOLD" "$OUT"
    holds "HEAD did not move" "$BEFORE_HEAD" "$(git -C "$REPO" rev-parse HEAD)"
}

case_a_budget_lowering_is_applied_and_committed() {
    CURRENT="a budget lowering is applied and committed"
    make_repo lower
    cat >"$REPO/budget.out" <<'ENGINE'
budget note: service_function_length apps/alpha/services.py — do_thing (lines 10-40) measured 31, below its ceiling 40 — a human may commit the lower number:
  apps/alpha/services.py: 31
budget note: out_schema_fields apps/alpha/schemas.py::ThingOut — ThingOut (lines 3-12) measured 6, below its ceiling 9 — a human may commit the lower number:
  apps/alpha/schemas.py::ThingOut: 6
### budget-check: notes=2 problems=0
ENGINE
    run_fold
    holds "exit 0" 0 "$RC"
    holds "the subject" "fold: 2 budgets lowered" "$(git -C "$REPO" log -1 --format=%s)"
    NEW="$REPO/quality/budgets.yaml"
    says "the plain key was lowered" "  apps/alpha/services.py: 31" "$NEW"
    # THE PROVENANCE COMMENT SURVIVES. A YAML round-trip would throw away every
    # comment in that file, and those comments are why a ceiling is readable.
    says "the trailing comment survived" "31 # provenance: the comment that must survive" "$NEW"
    # THE `::` KEY. The parser finds the LAST `: N`, which is the only reason
    # this splits correctly at all.
    says "the :: key was lowered" "  apps/alpha/schemas.py::ThingOut: 6" "$NEW"
    says "the untouched sibling is untouched" "  apps/beta/services.py: 55" "$NEW"
    holds "only budgets.yaml is in the commit" "quality/budgets.yaml" \
        "$(git -C "$REPO" show --name-only --format= HEAD | tr '\n' ' ' | sed 's/ *$//')"
}

case_a_lowering_for_an_absent_key_is_refused() {
    CURRENT="a lowering naming a key the file lacks is refused"
    make_repo miss
    BUDGETS_BEFORE="$(cat "$REPO/quality/budgets.yaml")"
    cat >"$REPO/budget.out" <<'ENGINE'
budget note: service_function_length apps/ghost/services.py — vanish (lines 1-2) measured 2, below its ceiling 9 — a human may commit the lower number:
  apps/ghost/services.py: 2
### budget-check: notes=1 problems=0
ENGINE
    run_fold
    holds "exit 2" 2 "$RC"
    says "names the miss" "MISS service_function_length apps/ghost/services.py" "$OUT"
    says "says applying the rest would be worse" "how a floor stops being a floor" "$OUT"
    holds "budgets.yaml is byte-identical" "$BUDGETS_BEFORE" "$(cat "$REPO/quality/budgets.yaml")"
    holds "HEAD did not move" "$BEFORE_HEAD" "$(git -C "$REPO" rev-parse HEAD)"
}

# TOOTH TWO, OWNED RATHER THAN BORROWED. Every case above proves the fold does
# not read a RAISE — the raise shapes carry no lowering sentence, so there is no
# branch that recognises them. This case is the other half, and it is the one
# the FOLD-1 verifier found open (their plant B3): a note carrying the LOWERING
# sentence verbatim, and a number ABOVE the ceiling the file already records.
# Until this case existed the fold applied whatever number the note printed and
# committed it as "1 budgets lowered", exit 0 — the property was real only
# because `quality/gate.py` happened to compare before printing. A note is an
# INPUT, and inputs are not trusted: the fold now reads the current ceiling out
# of the file it is rewriting and refuses anything that is not strictly lower.
case_a_lowering_note_above_the_ceiling_is_refused() {
    CURRENT="a lowering note carrying a HIGHER number is refused"
    make_repo above
    BUDGETS_BEFORE="$(cat "$REPO/quality/budgets.yaml")"
    cat >"$REPO/budget.out" <<'ENGINE'
budget note: service_function_length apps/alpha/services.py — do_thing (lines 10-40) measured 900, below its ceiling 40 — a human may commit the lower number:
  apps/alpha/services.py: 900
### budget-check: notes=1 problems=0
ENGINE
    run_fold
    holds "exit 2" 2 "$RC"
    says "prints section, key, old and new" \
        "service_function_length apps/alpha/services.py: 40 -> 900" "$OUT"
    says "says the fold never raises a ceiling" "never raises a ceiling" "$OUT"
    says_not "does not report it as a lowering" "ceiling(s) lowered" "$OUT"
    holds "budgets.yaml is byte-identical" "$BUDGETS_BEFORE" "$(cat "$REPO/quality/budgets.yaml")"
    holds "HEAD did not move" "$BEFORE_HEAD" "$(git -C "$REPO" rev-parse HEAD)"

    # EQUAL IS NOT LOWER. `quality/gate.py` prints its sentence under
    # `value < ceiling`, so a note whose number equals the ceiling can only be
    # crafted — which is exactly the population this guard is for.
    CURRENT="a lowering note carrying the SAME number is refused"
    make_repo equal
    BUDGETS_BEFORE="$(cat "$REPO/quality/budgets.yaml")"
    cat >"$REPO/budget.out" <<'ENGINE'
budget note: service_function_length apps/alpha/services.py — do_thing (lines 10-40) measured 40, below its ceiling 40 — a human may commit the lower number:
  apps/alpha/services.py: 40
### budget-check: notes=1 problems=0
ENGINE
    run_fold
    holds "exit 2" 2 "$RC"
    says "prints section, key, old and new" \
        "service_function_length apps/alpha/services.py: 40 -> 40" "$OUT"
    holds "budgets.yaml is byte-identical" "$BUDGETS_BEFORE" "$(cat "$REPO/quality/budgets.yaml")"
    holds "HEAD did not move" "$BEFORE_HEAD" "$(git -C "$REPO" rev-parse HEAD)"

    # THE RAISE BRANCH'S OWN SENTENCE, asserted here so the split below cannot
    # quietly move it. Exit 4 has two reasons and one of them keeps this text.
    says "the raise branch keeps its own sentence" \
        "not BELOW the ceiling" "$OUT"
}

# THE OTHER MEMBER OF EXIT 4, and it had the wrong sentence. A ceiling that is
# not a number is could-not-look, not a free pass: the comparison has to read
# the old value, a hand-edited line it cannot read is a line it cannot say is
# being lowered, and "cannot say" is exit 2 here as everywhere. What it is NOT
# is "a lowering note carried a number that is not BELOW the ceiling" — the
# fold printed that for every exit-4 member, including this one, which is a
# message naming a cause it has not proven. The status and the byte-identity
# were right throughout; only the sentence was wrong, and a refusal with the
# right code and the wrong sentence is a refusal nobody can act on.
case_an_unreadable_ceiling_says_it_cannot_compare() {
    CURRENT="a ceiling that is not a number is could-not-look"
    make_repo unreadable
    printf 'service_function_length:\n  apps/alpha/services.py: forty\n' \
        >"$REPO/quality/budgets.yaml"
    git -C "$REPO" add quality/budgets.yaml
    git -C "$REPO" commit -q -m "a ceiling nobody can compare against"
    BEFORE_HEAD="$(git -C "$REPO" rev-parse HEAD)"
    BUDGETS_BEFORE="$(cat "$REPO/quality/budgets.yaml")"
    cat >"$REPO/budget.out" <<'ENGINE'
budget note: service_function_length apps/alpha/services.py — do_thing (lines 10-40) measured 31, below its ceiling 40 — a human may commit the lower number:
  apps/alpha/services.py: 31
### budget-check: notes=1 problems=0
ENGINE
    run_fold
    holds "exit 2" 2 "$RC"
    says "names the ceiling it could not read" \
        "the ceiling standing in the file is \"forty\"" "$OUT"
    # THE `new` VALUE. The reason line named section, key and the text found and
    # stopped there, so the one number a reader needs to judge the note — the
    # number the note wanted to write — was missing from the only line that
    # names the subject.
    says "the reason line carries the number the note carried" \
        "the ceiling standing in the file is \"forty\", which is not a number -> 31" "$OUT"
    says "says it cannot tell lowering from raising" \
        "so the fold cannot tell lowering from raising and refuses to guess" "$OUT"
    says_not "does not claim a number that is not BELOW a ceiling" \
        "not BELOW the ceiling" "$OUT"
    says_not "does not report it as a lowering" "ceiling(s) lowered" "$OUT"
    holds "budgets.yaml is byte-identical" "$BUDGETS_BEFORE" "$(cat "$REPO/quality/budgets.yaml")"
    holds "HEAD did not move" "$BEFORE_HEAD" "$(git -C "$REPO" rev-parse HEAD)"
}

# THE APPLY REWRITES A NUMBER, NOT A LINE. The ceiling lines in the real
# `quality/budgets.yaml` carry provenance comments, and a step that re-spaces
# them puts churn a reviewer has to read past into the one diff whose whole
# purpose is to be read. The victim here is planted by this case — a ceiling
# line whose comment sits three spaces out — because found state proves nothing.
case_an_inline_comment_keeps_its_own_spacing() {
    CURRENT="a lowering changes the number and nothing else on the line"
    make_repo spacing
    cat >"$REPO/quality/budgets.yaml" <<'BUDGETS'
service_function_length:
  apps/alpha/services.py: 40   # provenance: three spaces out, and it stays there
  apps/beta/services.py: 55

out_schema_fields:
  apps/alpha/schemas.py::ThingOut: 9
BUDGETS
    git -C "$REPO" add quality/budgets.yaml
    git -C "$REPO" commit -q -m "a ceiling line whose comment is aligned"
    BEFORE_HEAD="$(git -C "$REPO" rev-parse HEAD)"
    cp "$REPO/quality/budgets.yaml" "$WORK/spacing-before.yaml"

    cat >"$REPO/budget.out" <<'ENGINE'
budget note: service_function_length apps/alpha/services.py — do_thing (lines 10-40) measured 31, below its ceiling 40 — a human may commit the lower number:
  apps/alpha/services.py: 31
### budget-check: notes=1 problems=0
ENGINE
    run_fold
    holds "exit 0" 0 "$RC"
    holds "the subject" "fold: 1 budgets lowered" "$(git -C "$REPO" log -1 --format=%s)"

    # EXACTLY ONE CHANGED TOKEN, asserted two ways: one changed line in the
    # whole file, and that line reproduced from the original by substituting the
    # number alone — byte for byte, gap included.
    CHANGED="$(diff "$WORK/spacing-before.yaml" "$REPO/quality/budgets.yaml" |
        grep -c '^[<>]' || true)"
    holds "exactly one line differs (one < and one >)" 2 "$CHANGED"
    BEFORE_LINE="$(grep -F 'apps/alpha/services.py:' "$WORK/spacing-before.yaml")"
    AFTER_LINE="$(grep -F 'apps/alpha/services.py:' "$REPO/quality/budgets.yaml")"
    holds "only the number token changed" "${BEFORE_LINE/ 40 / 31 }" "$AFTER_LINE"
    says "the three-space gap before the comment survived" \
        "31   # provenance: three spaces out" "$REPO/quality/budgets.yaml"
}

# THE NOTE-COUNT CROSS-CHECK. Without it a reworded engine message degrades
# silently to a green no-op fold, which looks exactly like a clean tree.
case_a_moved_sentence_is_refused_not_read_as_nothing() {
    CURRENT="a moved engine sentence is refused, not read as nothing to lower"
    make_repo moved
    cat >"$REPO/budget.out" <<'ENGINE'
budget note: service_function_length apps/alpha/services.py — do_thing (lines 10-40) measured 31, below its ceiling 40 — a person may record the smaller value:
  apps/alpha/services.py: 31
### budget-check: notes=1 problems=0
ENGINE
    run_fold
    holds "exit 2" 2 "$RC"
    says "names both counts" "wrote 1 note(s) and this parser recognised 0" "$OUT"
    says "says the sentence has moved" "sentence has moved and this file has not" "$OUT"
    holds "HEAD did not move" "$BEFORE_HEAD" "$(git -C "$REPO" rev-parse HEAD)"
}

case_a_missing_summary_line_is_refused() {
    CURRENT="a budget run with no summary line is could-not-look"
    make_repo nosummary
    printf 'something the engine printed and this parser does not know\n' >"$REPO/budget.out"
    run_fold
    holds "exit 2" 2 "$RC"
    says "names the summary count" "printed 0 summary line(s), not exactly one" "$OUT"
    holds "HEAD did not move" "$BEFORE_HEAD" "$(git -C "$REPO" rev-parse HEAD)"
}

# ---------------------------------------------------------------------------
# THE COMBINED SUBJECT — the ` · ` join, which is the commit shape criterion 8
# names.
# ---------------------------------------------------------------------------
case_the_combined_subject_joins_with_the_separator() {
    CURRENT="a fold of everything joins its parts with ' · '"
    make_repo combined
    echo "drift" >"$REPO/pin.act"
    echo "shift" >"$REPO/secrets.act"
    cat >"$REPO/budget.out" <<'ENGINE'
budget note: service_function_length apps/alpha/services.py — do_thing (lines 10-40) measured 31, below its ceiling 40 — a human may commit the lower number:
  apps/alpha/services.py: 31
### budget-check: notes=1 problems=0
ENGINE
    run_fold
    holds "exit 0" 0 "$RC"
    holds "the subject" "fold: contract regenerated · baseline shifted · 1 budgets lowered" \
        "$(git -C "$REPO" log -1 --format=%s)"
    holds "all four derived paths, and nothing else" \
        ".secrets.baseline frontend/openapi.json frontend/src/api/generated/schema.d.ts quality/budgets.yaml" \
        "$(git -C "$REPO" show --name-only --format= HEAD | sort | tr '\n' ' ' | sed 's/ *$//')"
    holds "the tree is clean afterwards" "" "$(git -C "$REPO" status --porcelain)"
}

# ---------------------------------------------------------------------------
# CRITERION 5 — THE ORDERING PROPERTY, driven rather than argued: after the
# fold, the tree the gate's ledger keys a verdict on IS the fold commit's tree.
# That equality is the whole reason the fold runs before the gate.
# ---------------------------------------------------------------------------
case_the_folded_tree_is_the_tree_a_verdict_keys_on() {
    CURRENT="the fold commit's tree is the tree the ledger would key a verdict on"
    make_repo keyed
    [ -r "$LEDGER_SRC" ] || {
        bad "no readable ${LEDGER_SRC} — cannot ask what a verdict keys on"
        return 0
    }
    echo "drift" >"$REPO/pin.act"
    run_fold
    holds "exit 0" 0 "$RC"
    POST_TREE="$(git -C "$REPO" rev-parse "HEAD^{tree}")"
    MEASURED="$(
        cd "$REPO" &&
            . "$LEDGER_SRC" >/dev/null 2>&1 &&
            gate_measured_tree
    )"
    holds "gate_measured_tree == the fold commit's tree" "$POST_TREE" "$MEASURED"
    holds "and it is NOT the pre-fold tree" "1" \
        "$([ "$MEASURED" != "$BEFORE_TREE" ] && echo 1 || echo 0)"
}

# ---------------------------------------------------------------------------
# END TO END, THROUGH `pm_push.sh --bank`, IN A CHECKOUT THIS CASE BUILT.
#
# THE CLAIM UNDER TEST is the compounding half of the same class: nothing in `check.sh` or
# `fe_gate.sh` compares the committed generated client to a fresh regeneration,
# so a STALE CONTRACT ONCE BANKED GREEN AND SILENTLY. This case
# plants exactly that and asserts it cannot any more.
#
# IT CREATES ITS OWN VICTIM, which is the destructive-demonstration rule and is
# not negotiable here of all places: this is the ritual the PM runs. The
# checkout, its `pm-push` worktree, its bare remote and its gate are all built
# by this case, under `mktemp -d`. The gate is a STUB — it records what a
# verdict WOULD key on, using the REAL `gate_measured_tree` out of
# `scripts/gate_ledger.sh`, and exits 0 — so the ~8-minute run is never entered
# and the tree-equality claim is still measured with the real function.
case_a_stale_client_cannot_bank_green_through_pm_push() {
    CURRENT="a stale client cannot bank green through pm_push --bank"
    make_repo bank
    [ -r "$LEDGER_SRC" ] || {
        bad "no readable ${LEDGER_SRC} — cannot ask what a verdict keys on"
        return 0
    }
    cp "$PUSH_SRC" "$REPO/scripts/pm_push.sh"
    chmod +x "$REPO/scripts/pm_push.sh"
    cp "$LEDGER_SRC" "$REPO/scripts/gate_ledger.sh"
    [ -r "$REFUSE_SRC" ] || {
        bad "no readable ${REFUSE_SRC} — the ledger library sources it and would die at that line"
        return 0
    }
    cp "$REFUSE_SRC" "$REPO/scripts/gate_refuse.sh"

    cat >"$REPO/scripts/check.sh" <<STUB
#!/usr/bin/env bash
set -euo pipefail
cd "$REPO"
# shellcheck source=/dev/null
. "$REPO/scripts/gate_ledger.sh" >/dev/null 2>&1
gate_measured_tree >"$REPO/measured-tree.txt"
echo "stub check.sh: a verdict for \$(cat "$REPO/measured-tree.txt")"
STUB
    chmod +x "$REPO/scripts/check.sh"

    BARE="$WORK/remote-${CASE_N}.git"
    drive_require_scratch BARE "$BARE"
    git init -q --bare "$BARE"

    git -C "$REPO" add -A
    git -C "$REPO" commit -q -m "the wiring, the stub gate and the ledger library"
    git -C "$REPO" remote add origin "$BARE"
    git -C "$REPO" push -q origin HEAD:refs/heads/main
    git -C "$REPO" worktree add -q --detach "$REPO/.wt/pm-push" HEAD
    PRE_BANK_HEAD="$(git -C "$REPO" rev-parse HEAD)"
    PRE_BANK_TREE="$(git -C "$REPO" rev-parse "HEAD^{tree}")"

    bank() {
        set +e
        (
            cd "$REPO" || exit 2
            PATH="$REPO/bin:$PATH" \
                DJB_FOLD_PIN_CLIENT="$REPO/frontend/scripts/pin_client.sh" \
                DJB_FOLD_UV="uv" \
                DJB_PUSH_REMOTE=origin DJB_PUSH_BRANCH=main DJB_PUSH_WORKTREE=pm-push \
                ./scripts/pm_push.sh "$@"
        ) >"$OUT" 2>&1
        RC=$?
        set -e
    }

    # ---- the stale contract, banked -------------------------------------
    echo "drift" >"$REPO/pin.act"
    bank --bank
    holds "the bank+push exited 0" 0 "$RC"
    says "the fold ran inside the bank block" "folding" "$OUT"
    holds "a NAMED fold commit is HEAD" "fold: contract regenerated" \
        "$(git -C "$REPO" log -1 --format=%s)"
    says "and the bank says it banked the POST-FOLD head" "banking the POST-FOLD HEAD" "$OUT"

    POST_HEAD="$(git -C "$REPO" rev-parse HEAD)"
    POST_TREE="$(git -C "$REPO" rev-parse "HEAD^{tree}")"

    # THE ORDERING PROPERTY, read back from what the gate recorded rather than
    # argued: the verdict keys on the tree the fold LEFT, not the one it found.
    holds "the verdict keys on the FOLD COMMIT's tree" "$POST_TREE" \
        "$(cat "$REPO/measured-tree.txt")"
    holds "and NOT on the pre-fold tree" "1" \
        "$([ "$(cat "$REPO/measured-tree.txt")" != "$PRE_BANK_TREE" ] && echo 1 || echo 0)"

    # AND THE PUSH CARRIES THE TREE THAT WAS VOUCHED FOR.
    holds "the remote tip is the post-fold HEAD" "$POST_HEAD" \
        "$(git -C "$BARE" rev-parse refs/heads/main)"
    holds "and not the pre-fold HEAD" "1" \
        "$([ "$(git -C "$BARE" rev-parse refs/heads/main)" != "$PRE_BANK_HEAD" ] && echo 1 || echo 0)"

    # ---- and the other direction: --no-fold is LOUD, never silent --------
    echo "drift" >"$REPO/pin.act"
    printf '{"stale": true}\n' >"$REPO/frontend/openapi.json"
    git -C "$REPO" add -- frontend/openapi.json
    git -C "$REPO" commit -q -m "plant a stale contract by hand"
    STALE_HEAD="$(git -C "$REPO" rev-parse HEAD)"
    bank --bank --no-fold
    holds "--bank --no-fold: exit 0" 0 "$RC"
    says "it SAYS the derived files were not regenerated" \
        "THE DERIVED FILES WERE NOT REGENERATED" "$OUT"
    says "and says a red gate would be the flag's doing" "that is THIS FLAG and not the tree" "$OUT"
    holds "no fold commit was made" "$STALE_HEAD" "$(git -C "$REPO" rev-parse HEAD)"
    # The point of the pair: skipping the fold is REACHABLE, and it is never
    # reachable QUIETLY.
    holds "the contract is still stale" '{"stale": true}' \
        "$(cat "$REPO/frontend/openapi.json")"

    git -C "$REPO" worktree remove --force "$REPO/.wt/pm-push" >/dev/null 2>&1 || true
}

# ---------------------------------------------------------------------------
# A CHECKOUT WITH NONE OF THE FOUR THINGS is a reader looking at the wrong
# tree, not a tree with nothing to fold.
# ---------------------------------------------------------------------------
case_a_checkout_with_nothing_to_fold_at_all_is_could_not_look() {
    CURRENT="a checkout with none of the four things is could-not-look"
    make_repo barren
    git -C "$REPO" rm -q -r --cached frontend quality .secrets.baseline manage.py >/dev/null
    rm -rf "$REPO/frontend" "$REPO/quality" "$REPO/.secrets.baseline" "$REPO/manage.py"
    git -C "$REPO" commit -q -m "strip everything a fold folds"
    BEFORE_HEAD="$(git -C "$REPO" rev-parse HEAD)"
    run_fold
    holds "exit 2" 2 "$RC"
    says "says it is the wrong tree" "a reader looking at the wrong tree" "$OUT"
    holds "HEAD did not move" "$BEFORE_HEAD" "$(git -C "$REPO" rev-parse HEAD)"
}

# ---------------------------------------------------------------------------
# THE EXIT GUARD IS THE REAL SCRIPT'S OWN LINES. On GNU bash 3.2 a `set -u`
# death hands the EXIT trap a status of 0, so a run that died part-way exits 0
# and reads to `pm_push --bank` as a clean fold. This asserts the guard is
# present in the shape the header claims AND that it actually fires — by
# extracting the real region and planting an unbound variable in it.
# ---------------------------------------------------------------------------
case_the_exit_guard_is_the_real_scripts_own() {
    CURRENT="the exit guard is the real script's own lines, and it fires"
    OPEN="$(grep -c '^# >>> exit-guard >>>$' "$FOLD_SRC" || true)"
    CLOSE="$(grep -c '^# <<< exit-guard <<<$' "$FOLD_SRC" || true)"
    holds "exactly one guard region" "1|1" "${OPEN}|${CLOSE}"
    ENDS="$(grep -c '^ *FOLD_REACHED_THE_END=1$' "$FOLD_SRC" || true)"
    # Four completion arms: --help, NOTHING TO FOLD, --no-commit, and the last
    # line. The count is asserted rather than the shape because the whole claim
    # of the guard is that EVERY path out of this script sets one — an arm
    # added and not counted here is an arm nobody checked.
    holds "four completion arms" 4 "$ENDS"

    awk '/^# >>> exit-guard >>>$/{p=1;next} /^# <<< exit-guard <<<$/{p=0} p' \
        "$FOLD_SRC" >"$WORK/guard.sh"
    {
        echo '#!/usr/bin/env bash'
        echo 'set -euo pipefail'
        cat "$WORK/guard.sh"
        echo 'echo "${A_NAME_NOBODY_SET}"'
        echo 'FOLD_REACHED_THE_END=1'
    } >"$WORK/guard-probe.sh"
    chmod +x "$WORK/guard-probe.sh"
    set +e
    "$WORK/guard-probe.sh" >"$OUT" 2>&1
    RC=$?
    set -e
    holds "the extracted guard exits 2 on a set -u death" 2 "$RC"
    says "and it says DIED part-way" "DIED part-way" "$OUT"
    says "and it says nothing printed is a verdict" "NOTHING THIS RUN PRINTED IS A VERDICT" "$OUT"
}

# ---------------------------------------------------------------------------
# THE TWO WIRINGS.
#
# `--no-fold` outside `--bank` — BOTH DIRECTIONS, BOTH SCRIPTS. This is the
# sibling product's defect fixed at intake: their pm_push STRIPS the flag before
# any parser can see it and consults it only inside the bank block, so a plain
# `pm_push.sh --no-fold` is an ordinary push with the flag accepted, inert, and
# nothing printed. One semantic here, and both scripts agree on it.
#
# The refusals are reached with no repository at all, which is deliberate: both
# scripts refuse the combination BEFORE they resolve a checkout, so the case
# proves the refusal is at the argument rather than a side effect of some later
# guard.
# ---------------------------------------------------------------------------
case_no_fold_outside_bank_is_refused_by_both_scripts() {
    CURRENT="--no-fold outside --bank refuses loudly, in both scripts"

    set +e
    (cd "$WORK" && "$PUSH_SRC" --no-fold) >"$OUT" 2>&1
    RC=$?
    set -e
    holds "pm_push --no-fold: exit 2" 2 "$RC"
    says "pm_push: says it needs --bank" "--no-fold is only meaningful with --bank" "$OUT"
    says "pm_push: says why the flag would be inert" "there is nothing here for --no-fold to skip" "$OUT"
    says "pm_push: points at the sibling script" "scripts/pm_merge.sh refuses the same combination" "$OUT"

    set +e
    (cd "$WORK" && "$MERGE_SRC" some-branch --no-fold) >"$OUT" 2>&1
    RC=$?
    set -e
    holds "pm_merge --no-fold: exit 2" 2 "$RC"
    says "pm_merge: says it needs --bank" "--no-fold is only meaningful with --bank" "$OUT"
    says "pm_merge: points at the sibling script" "scripts/pm_push.sh refuses the same combination" "$OUT"

    # THE OTHER DIRECTION: WITH --bank the flag is accepted, and the run gets
    # past the argument parser to fail on something else entirely. Asserted as
    # "it did not die at the flag", which is the only claim reachable without
    # running an ~8-minute gate.
    set +e
    (cd "$WORK" && "$MERGE_SRC" some-branch --bank --no-fold) >"$OUT" 2>&1
    set -e
    says_not "pm_merge --bank --no-fold: NOT refused at the flag" \
        "--no-fold is only meaningful with --bank" "$OUT"
}

# THE PLACEMENT, structurally. Line numbers are DERIVED here and compared, never
# typed: the sibling product's own handoff cited a registration site that was
# ~410 lines stale within a day, which is exactly what a typed line number buys.
case_the_fold_sits_where_the_ordering_requires() {
    CURRENT="the fold sits where the ordering requires, in both scripts"

    line_of() { grep -n -- "$2" "$1" | head -1 | cut -d: -f1; }

    P_FOLD="$(line_of "$PUSH_SRC" 'FOLD="$ROOT/scripts/pm_fold.sh"')"
    P_CLEAN="$(line_of "$PUSH_SRC" 'pm_push --bank: ${ROOT} has uncommitted changes')"
    P_GATE="$(line_of "$PUSH_SRC" '"$GATE" --bank || BANK_RC=$?')"
    P_RESOLVE="$(line_of "$PUSH_SRC" 'could not re-read HEAD after the fold')"
    if [ -n "$P_FOLD" ] && [ -n "$P_CLEAN" ] && [ -n "$P_GATE" ] && [ -n "$P_RESOLVE" ]; then
        holds "pm_push: the fold is before the cleanliness check" "1" \
            "$([ "$P_FOLD" -lt "$P_CLEAN" ] && echo 1 || echo 0)"
        holds "pm_push: the fold is before the banked gate" "1" \
            "$([ "$P_FOLD" -lt "$P_GATE" ] && echo 1 || echo 0)"
        holds "pm_push: the SHA is re-resolved after the fold, before the gate" "1" \
            "$([ "$P_FOLD" -lt "$P_RESOLVE" ] && [ "$P_RESOLVE" -lt "$P_GATE" ] && echo 1 || echo 0)"
    else
        bad "pm_push: could not locate all four anchors (fold=${P_FOLD} clean=${P_CLEAN} gate=${P_GATE} resolve=${P_RESOLVE})"
    fi

    M_PROOF="$(line_of "$MERGE_SRC" 'pm_merge: MERGED. Proof of merge')"
    M_FOLD="$(line_of "$MERGE_SRC" 'pm_merge: folding the merged tree before the gate')"
    M_GATE="$(line_of "$MERGE_SRC" 'exec "$GATE" "$GATE_TIER"')"
    if [ -n "$M_PROOF" ] && [ -n "$M_FOLD" ] && [ -n "$M_GATE" ]; then
        holds "pm_merge: the fold is after the proof of merge" "1" \
            "$([ "$M_PROOF" -lt "$M_FOLD" ] && echo 1 || echo 0)"
        holds "pm_merge: the fold is before the exec'd gate" "1" \
            "$([ "$M_FOLD" -lt "$M_GATE" ] && echo 1 || echo 0)"
    else
        bad "pm_merge: could not locate all three anchors (proof=${M_PROOF} fold=${M_FOLD} gate=${M_GATE})"
    fi

    if grep -q "THE MERGE ABOVE IS ALREADY MADE" "$MERGE_SRC"; then
        ok "pm_merge: a nonzero fold states that the merge is already made"
    else
        bad "pm_merge: a nonzero fold does not state that the merge is already made"
    fi
}

# ---------------------------------------------------------------------------
# The fe leg's contract-surface disclosure. The state that used to be
# `untouched` over a change that stales the client.
# ---------------------------------------------------------------------------
case_the_fe_leg_names_a_client_suspect() {
    CURRENT="the fe leg names a client suspect instead of printing UNTOUCHED"
    FE_SRC="$ROOT/scripts/fe_gate.sh"
    [ -r "$FE_SRC" ] || {
        bad "no readable ${FE_SRC}"
        return 0
    }
    FEDIR="$WORK/fe-suspect"
    mkdir -p "$FEDIR"
    printf '{"name":"x"}\n' >"$FEDIR/package.json"

    printf 'apps/example/api.py\0docs/product/queue.md\0' >"$WORK/changed-suspect.lst"
    printf 'apps/example/models.py\0docs/product/queue.md\0' >"$WORK/changed-plain.lst"

    set +e
    (
        # shellcheck source=scripts/fe_gate.sh
        . "$FE_SRC"
        FE_FRONTEND_DIR="$FEDIR"
        fe_leg_run "$WORK/changed-suspect.lst"
        echo "STATE=$FE_LEG_STATE RC=$?"
    ) >"$OUT" 2>&1
    set -e
    says "a contract-surface change is a SUSPECT" "CLIENT SUSPECT" "$OUT"
    says "and it names the file" "apps/example/api.py" "$OUT"
    says "and it stays exit 0 (a disclosure, not a finding)" "STATE=suspect RC=0" "$OUT"
    says_not "and it does NOT print the old reassurance" "UNTOUCHED (fast path)" "$OUT"

    set +e
    (
        # shellcheck source=scripts/fe_gate.sh
        . "$FE_SRC"
        FE_FRONTEND_DIR="$FEDIR"
        fe_leg_run "$WORK/changed-plain.lst"
        echo "STATE=$FE_LEG_STATE RC=$?"
    ) >"$OUT" 2>&1
    set -e
    says "a NON-contract change is still UNTOUCHED" "UNTOUCHED (fast path)" "$OUT"
    says "and still exit 0" "STATE=untouched RC=0" "$OUT"
}

# ---------------------------------------------------------------------------

usage() {
    cat <<'USAGE'
scripts/tests/test_pm_fold.sh — the fold's refusal drive.

  ./scripts/tests/test_pm_fold.sh          run every case
  ./scripts/tests/test_pm_fold.sh --list   name the cases and stop

Exit: 0 every case held · 1 a case did not hold · 2 could not look.
USAGE
}

CASES="
case_dirty_tree_is_refused
case_unknown_flag_is_refused
case_piped_stdout_is_refused
case_out_of_list_write_is_exit_2
case_stray_inside_an_untracked_directory_is_named
case_nothing_to_fold_makes_no_commit
case_the_fold_restores_on_no_shift_from_a_stampless_file
case_the_fold_commits_a_stampless_baseline_on_a_real_shift
case_a_committed_stamp_is_stripped_even_when_nothing_shifted
case_an_unrecognised_stamp_shape_is_refused
case_two_lanes_baselines_merge_clean_without_the_stamp
case_the_stamp_is_what_conflicted
case_two_lanes_baselines_merge_clean_without_line_numbers
case_only_secrets_no_commit_rescans_and_stages_nothing
case_contract_drift_is_one_commit_of_derived_paths
case_an_unignored_rung_dir_is_skipped
case_a_failed_generator_commits_nothing
case_a_budget_raise_is_never_applied
case_a_budget_lowering_is_applied_and_committed
case_a_lowering_for_an_absent_key_is_refused
case_a_lowering_note_above_the_ceiling_is_refused
case_an_unreadable_ceiling_says_it_cannot_compare
case_an_inline_comment_keeps_its_own_spacing
case_a_moved_sentence_is_refused_not_read_as_nothing
case_a_missing_summary_line_is_refused
case_the_combined_subject_joins_with_the_separator
case_the_folded_tree_is_the_tree_a_verdict_keys_on
case_a_stale_client_cannot_bank_green_through_pm_push
case_a_checkout_with_nothing_to_fold_at_all_is_could_not_look
case_the_exit_guard_is_the_real_scripts_own
case_no_fold_outside_bank_is_refused_by_both_scripts
case_the_fold_sits_where_the_ordering_requires
case_the_fe_leg_names_a_client_suspect
"

case "${1:-}" in
"") ;;
--list)
    printf '%s' "$CASES" | while IFS= read -r c; do
        [ -n "$c" ] || continue
        echo "$c"
    done
    exit 0
    ;;
-h | --help)
    usage
    exit 0
    ;;
*)
    echo "!! test_pm_fold: unknown argument '${1}'. Try --help." >&2
    exit 2
    ;;
esac

echo "test_pm_fold: driving ${FOLD_SRC} and its two wirings"
echo ""
while IFS= read -r c; do
    [ -n "$c" ] || continue
    "$c"
done <<EOF
$CASES
EOF

echo ""
# >>> summary: passed and failed, separately >>>
# TWO NUMBERS, NEVER ONE. "24 of 25" is a sentence a reader completes wrongly;
# a failed count that is its own number is a number a reader cannot round off.
# Cited by this sentinel rather than by line number — `instruments.md`'s
# citation of this line was stale by 134 lines, and this file grows a case
# every time the fold does.
echo "test_pm_fold: ${PASSED} passed, ${FAILED} failed"
# <<< summary: passed and failed, separately <<<
drive_finished
[ "$FAILED" = "0" ] || exit 1
exit 0
