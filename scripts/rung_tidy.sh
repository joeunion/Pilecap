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
# THE RUNG TIDY. The bookkeeping the loop already PRESCRIBES, applied by one
# command instead of by a builder reading three different instruments' advice
# and doing it from memory.
#
#   ./scripts/rung_tidy.sh               every subject this checkout has
#   ./scripts/rung_tidy.sh --budgets     the ceilings a red house-rules leg named
#   ./scripts/rung_tidy.sh --client      the committed client and document
#   ./scripts/rung_tidy.sh --secrets     the secret baseline
#   ./scripts/rung_tidy.sh --help
#
# Exit: 0 applied, or nothing to apply · 1 a subject it could not apply cleanly
# · 2 could not look (a refusal, or a subject whose tool is absent). 2 outranks
# a pass, here as everywhere in this repository.
#
# ---------------------------------------------------------------------------
# WHY IT EXISTS, and it is a measurement rather than a convenience. Three of
# this gate's refusals END IN A PIECE OF BOOKKEEPING that the refusal itself
# describes in prose and nobody automates:
#
#   * a `budget:` line names the exact number to paste into quality/budgets.yaml
#   * the fe leg's CLIENT SUSPECT state names the generator to re-run
#   * a bank's `BASELINE SHIFTED` leaves the next rung's baseline behind main's
#
# Each of those is a builder turn — read the advice, find the file, find the
# key, type the number, re-run — and each one is a turn spent on a mechanical
# transformation of something the instrument already computed. The offers now
# printed at those three sites (`scripts/check.sh`'s house-rules leg,
# `scripts/fe_gate.sh`'s suspect block, `scripts/pm_fold.sh`'s shifted baseline)
# name THIS command, so a builder who meets one never has to go looking for what
# to do about it.
#
# ---------------------------------------------------------------------------
# WHAT IT IS NOT, and each of these is a refusal rather than an omission:
#
#   IT OWNS NO WRITER OF ITS OWN. Every subject below is applied THROUGH the
#   instrument that already owns it — `frontend/scripts/pin_client.sh --write`
#   for the client, `scripts/pm_fold.sh --only secrets --no-commit` for the
#   baseline, and for the budgets the fold's own sentence reader
#   (`scripts/budget_notes.sh`, sourced by both). The baseline is the sharpest
#   case: `detect-secrets scan --baseline` over a partial path set DROPS the
#   result line of every file it was not handed, exits 0 and prints nothing, so
#   this tree has exactly ONE legal baseline writer and a second invocation
#   anywhere is the incident
#   (`scripts/tests/test_secrets_baseline_guard.sh`). This script therefore does
#   not name that command at all — it invokes the script that does.
#
#   IT NEVER COMMITS AND NEVER STAGES. What it writes lands in the WORKING TREE,
#   in the rung's own diff, where a reviewer reads it. A budget raise in
#   particular is a decision, and the whole reason the gate refuses on one is
#   that a human should see it — a tidy that committed it would be the tidy
#   undoing the rule it serves.
#
#   IT NEVER RUNS THE GATE. Gate discipline is the builder's
#   (`.claude/skills/rung-execution/SKILL.md` §3), and a tidy that measured
#   would be a tidy nobody can afford to run twice.
#
#   IT REFUSES A PIPE (exit 2). `scripts/rung_start.sh`'s detection and its CI
#   exemption, deliberately identical and for the same reason: a pipe replaces
#   this script's exit status with the filter's, and the exit status is the
#   verdict.
#
# ---------------------------------------------------------------------------
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * WHETHER A RAISE IS LEGITIMATE. It applies the number the engine printed
#     into the working tree so the rung's diff carries it. Whether the function
#     should have grown is a reviewer's question, and this script has no opinion.
#   * `npx`'s FIRST-RUN NETWORK. `scripts/gen_client.sh` fetches a pinned
#     `openapi-typescript` through `npx`; a machine that has never fetched it
#     needs a network the first time. That is the generator's contract, carried
#     through, and a failure there is its exit status and its words.
#   * A SUBJECT THIS CHECKOUT DOES NOT HAVE. It is `skipped — <reason>` at exit
#     0, printed. A product with no `frontend/` has no client to tidy, and a
#     silent skip is indistinguishable from a pass.
#   * WHETHER THE TIDIED TREE PASSES. That is `./scripts/check.sh --loop`, and
#     it is the builder's to run afterwards.
set -euo pipefail

# --- it refuses to be piped --------------------------------------------------
if [ -z "${CI:-}" ] && { [ -p /dev/fd/1 ] || [ -p /dev/stdout ]; }; then
    echo "!! rung_tidy refuses pipes — run it bare or redirect to a file." >&2
    echo "   The exit status is the verdict, and a filter replaces it." >&2
    exit 2
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd -P)" || {
    echo "!! rung_tidy: could not reach the checkout this script lives in." >&2
    exit 2
}
cd "$ROOT"

[ -r "$ROOT/scripts/budget_notes.sh" ] || {
    echo "!! rung_tidy: scripts/budget_notes.sh is not in this checkout." >&2
    echo "   The budgets subject reads the engine's sentences through it, and so does" >&2
    echo "   scripts/pm_fold.sh. Nothing was applied." >&2
    exit 2
}
# shellcheck source=scripts/budget_notes.sh
. "$ROOT/scripts/budget_notes.sh"

usage() {
    cat <<'USAGE'
usage: rung_tidy.sh [--budgets] [--client] [--secrets] [-h]

  Applies the bookkeeping the gate's own refusals prescribe. With no flag it
  does every subject this checkout has; a subject that is not here is
  `skipped`, printed, at exit 0.

  --budgets  Write the ceilings quality/gate.py's `budget:` lines named into
             quality/budgets.yaml — the RAISE and the NEW SUBJECT, which are
             the two shapes that end in a pasteable line. A LOWERING note is
             left alone: it is the fold's, under its clause 3.
  --client   Regenerate the committed client and document through
             frontend/scripts/pin_client.sh --write. Never gen_client.sh
             directly, and this script never spells `npx`.
  --secrets  Re-scan .secrets.baseline through scripts/pm_fold.sh --only
             secrets --no-commit, so the tree's ONE legal baseline writer stays
             the one legal baseline writer.

  It never commits, never stages and never runs the gate.

exit: 0 applied, or nothing to apply · 1 a subject it could not apply cleanly
      · 2 refused, or could not look (2 outranks a pass).
USAGE
}

WANT_BUDGETS=""
WANT_CLIENT=""
WANT_SECRETS=""
ANY_FLAG=""

while [ $# -gt 0 ]; do
    case "$1" in
    -h | --help)
        usage
        exit 0
        ;;
    --budgets)
        WANT_BUDGETS=1
        ANY_FLAG=1
        shift
        ;;
    --client)
        WANT_CLIENT=1
        ANY_FLAG=1
        shift
        ;;
    --secrets)
        WANT_SECRETS=1
        ANY_FLAG=1
        shift
        ;;
    *)
        # Not a usage nit: a mistyped flag falling through to a silently
        # different run is enforcement misfiring, and that is an exit 2.
        echo "!! rung_tidy takes --budgets, --client and --secrets; got '$1'." >&2
        usage >&2
        exit 2
        ;;
    esac
done

if [ -z "$ANY_FLAG" ]; then
    WANT_BUDGETS=1
    WANT_CLIENT=1
    WANT_SECRETS=1
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-rung-tidy.XXXXXX")" || {
    echo "!! rung_tidy: could not make a scratch directory. Nothing was applied." >&2
    exit 2
}
trap 'rm -rf "$WORK"' EXIT

# THE VERDICT, COMPOSED THE WAY EVERY OTHER INSTRUMENT HERE COMPOSES ONE:
# 2 outranks 1 outranks 0, and a subject never lowers what another subject
# already raised.
STATUS=0
raise_to() { [ "$1" -le "$STATUS" ] || STATUS="$1"; }

skipped() {
    echo "tidy $1: skipped — $2"
}

echo "== rung_tidy · ${ROOT}"
echo ""

# =============================================================================
# BUDGETS
# =============================================================================
tidy_budgets() {
    local claimed recognised
    if [ ! -f "$ROOT/quality/budgets.yaml" ]; then
        skipped budgets "no quality/budgets.yaml in this checkout — there are no ceilings to write"
        return 0
    fi
    if ! command -v uv >/dev/null 2>&1; then
        echo "!! tidy budgets: quality/budgets.yaml is here and there is no uv on PATH." >&2
        echo "   The numbers this writes are the ENGINE'S own, read by running it. Without" >&2
        echo "   the interpreter there is nothing to read and this is a could-not-look," >&2
        echo "   never an empty set of ceilings." >&2
        raise_to 2
        return 0
    fi

    local rc=0
    budget_notes_collect uv "$WORK" || rc=$?
    if [ "$rc" != "0" ]; then
        cat "$WORK/budget.out" >&2
        echo "!! tidy budgets: the budgets check exited ${rc} (output above)." >&2
        echo "   A tidy cannot write a ceiling it could not measure." >&2
        raise_to 2
        return 0
    fi

    # THE SHAPE GUARD, and the cross-check, are `scripts/pm_fold.sh`'s — the
    # same two, on the same output, for the same reason. A parser that reads a
    # sentence that is no longer printed reports "nothing to do", which looks
    # exactly like a clean tree, and this caller is as blind to that as the
    # other one unless it asks the engine what it wrote.
    if [ "$(budget_notes_summary_lines "$WORK/budget.out")" != "1" ]; then
        echo "!! tidy budgets: the budgets check did not print exactly one summary line." >&2
        echo "   This reader reads the engine's own sentences; a run whose shape it does" >&2
        echo "   not recognise is a could-not-look, never an empty set." >&2
        raise_to 2
        return 0
    fi
    claimed="$(budget_notes_claimed "$WORK/budget.out" problems)"
    if [ -z "$claimed" ]; then
        echo "!! tidy budgets: the summary line did not name a problem count." >&2
        raise_to 2
        return 0
    fi

    budget_notes_pastables "$WORK/budget.out" "$WORK/pastables.tsv"
    budget_notes_lowerings "$WORK/budget.out" "$WORK/lowerings.tsv"
    recognised="$(budget_notes_count "$WORK/pastables.tsv")"

    if [ "$recognised" != "$claimed" ]; then
        cat "$WORK/budget.out" >&2
        echo "!! tidy budgets: the budgets check wrote ${claimed} problem(s) and this reader" >&2
        echo "   recognised ${recognised} pasteable line(s). The engine's sentence has moved" >&2
        echo "   and scripts/budget_notes.sh has not — could-not-look, never a tidy that" >&2
        echo "   applied some of them." >&2
        raise_to 2
        return 0
    fi

    # A LOWERING IS PRINTED AND LEFT ALONE. It is the fold's, under clause 3,
    # and it is committed at the bank under its own subject. Saying so here is
    # what stops the next reader wondering why the tidy went quiet about a line
    # the engine clearly printed.
    local lowered
    lowered="$(budget_notes_count "$WORK/lowerings.tsv")"
    if [ "$lowered" != "0" ]; then
        while IFS="$(printf '\t')" read -r sect key val; do
            [ -n "$sect" ] || continue
            echo "  budget lowering ${sect}.${key} -> ${val}: left for the fold (clause 3)"
        done <"$WORK/lowerings.tsv"
    fi

    if [ "$recognised" = "0" ]; then
        echo "tidy budgets: nothing to do"
        return 0
    fi

    # THE APPLY. Whole-file buffered, comment-preserving, and it writes a
    # SCRATCH file that is only copied over the real one after the report is
    # read — a partial rewrite is never left behind. A RAISE rewrites the number
    # on the line the key already has; a NEW SUBJECT is appended at the END of
    # its section, after the last non-blank line the section owns.
    #
    # THE END OF THE SECTION AND NOT THE LAST ENTRY LINE, and that distinction
    # was found rather than reasoned: every entry in this repository's
    # `quality/budgets.yaml` carries a provenance comment run BELOW it, so
    # inserting after the last `  key: value` line drops a new ceiling into the
    # middle of the previous entry's argument. Measured on the real file, in a
    # scratch clone, against the real engine, before this was written.
    local apply_rc=0
    awk -v REC="$WORK/pastables.tsv" -v REPORT="$WORK/applied.txt" '
        BEGIN {
            n = 0
            while ((getline rec < REC) > 0) {
                if (rec == "") continue
                split(rec, a, "\t")
                n++; S[n] = a[1]; K[n] = a[2]; V[n] = a[3]; HIT[n] = 0
            }
        }
        { L[NR] = $0; SECT[NR] = sect }
        /^[A-Za-z_][A-Za-z0-9_]*:[ \t]*$/ {
            sect = $0; sub(/:[ \t]*$/, "", sect); SECT[NR] = sect; HDR[sect] = NR
        }
        # The last NON-BLANK line the section owns, comments included.
        /[^ \t]/ { if (sect != "") LAST[sect] = NR }
        END {
            # RAISES first: in place, on the line the key already has.
            for (i = 1; i <= NR; i++) {
                for (j = 1; j <= n; j++) {
                    if (HIT[j]) continue
                    if (SECT[i] != S[j]) continue
                    pfx = "  " K[j] ": "
                    if (substr(L[i], 1, length(pfx)) != pfx) continue
                    tail = substr(L[i], length(pfx) + 1)
                    cm = ""
                    p = index(tail, "#")
                    if (p > 0) {
                        old = substr(tail, 1, p - 1)
                        # The gap between the value and the `#` is carried
                        # across byte for byte: re-spacing it would put churn a
                        # reviewer must read past into the one diff whose whole
                        # purpose is to be read.
                        gap = old
                        sub(/^[^ \t]*/, "", gap)
                        cm = gap substr(tail, p)
                    } else { old = tail }
                    sub(/[ \t]+$/, "", old)
                    if (old !~ /^[0-9]+$/) {
                        printf "UNREADABLE %s %s %s %s\n", S[j], K[j], old, V[j] > "/dev/stderr"
                        bad = 1
                    }
                    L[i] = pfx V[j] cm
                    printf "%s\t%s\t%s\t%s\n", S[j], K[j], old, V[j] > REPORT
                    HIT[j] = 1
                }
            }
            # NEW SUBJECTS: one insertion point per section, kept in the order
            # the engine printed them.
            for (j = 1; j <= n; j++) {
                if (HIT[j]) continue
                at = LAST[S[j]]
                if (at == 0) at = HDR[S[j]]
                if (at == 0) {
                    printf "NOSECTION %s %s\n", S[j], K[j] > "/dev/stderr"
                    bad = 1
                    continue
                }
                INS[at] = INS[at] "  " K[j] ": " V[j] "\n"
                printf "%s\t%s\t%s\t%s\n", S[j], K[j], "none", V[j] > REPORT
                HIT[j] = 1
            }
            for (i = 1; i <= NR; i++) {
                print L[i]
                if (INS[i] != "") printf "%s", INS[i]
            }
            if (bad) exit 4
        }
    ' "$ROOT/quality/budgets.yaml" >"$WORK/budgets.new" 2>"$WORK/budgets.err" || apply_rc=$?

    if [ "$apply_rc" != "0" ]; then
        cat "$WORK/budgets.err" >&2
        echo "!! tidy budgets: a line the engine named could not be applied (above)." >&2
        echo "   UNREADABLE is a ceiling standing in quality/budgets.yaml that is not a" >&2
        echo "   number; NOSECTION is a section the engine names and the file does not" >&2
        echo "   have. Either way this run cannot say what it would have written, so" >&2
        echo "   quality/budgets.yaml was NOT modified." >&2
        raise_to 2
        return 0
    fi

    cp "$WORK/budgets.new" "$ROOT/quality/budgets.yaml"
    echo "tidy budgets: ${recognised} ceiling(s) written from the lines the engine printed"
    while IFS="$(printf '\t')" read -r sect key old new; do
        [ -n "$sect" ] || continue
        echo "  budget applied: ${sect}.${key} ${old} → ${new}"
    done <"$WORK/applied.txt"
    return 0
}

# =============================================================================
# CLIENT
# =============================================================================
tidy_client() {
    local pin="$ROOT/frontend/scripts/pin_client.sh"
    local doc="$ROOT/frontend/openapi.json"
    local client="$ROOT/frontend/src/api/generated/schema.d.ts"

    if [ ! -f "$doc" ] && [ ! -f "$client" ]; then
        skipped client "neither frontend/openapi.json nor the generated client is in this checkout"
        return 0
    fi
    if [ ! -x "$pin" ]; then
        echo "!! tidy client: the committed contract is here but ${pin} is not executable." >&2
        echo "   A committed client this run cannot regenerate is a client nobody can say" >&2
        echo "   is current — could-not-look, never a clean tidy." >&2
        raise_to 2
        return 0
    fi

    # The BEFORE bytes, so `regenerated <n> file(s)` is a measurement rather
    # than a guess about what the generator did.
    local before_doc="$WORK/before.openapi.json" before_client="$WORK/before.schema.d.ts"
    [ ! -f "$doc" ] || cp "$doc" "$before_doc"
    [ ! -f "$client" ] || cp "$client" "$before_client"

    # THROUGH THE PIN, never through the generator and never through `npx`.
    # `frontend/scripts/pin_client.sh` is the contract: it points the one
    # generator at a scratch directory and copies the bytes in, because
    # generating straight into `src/api/generated/` plants a `.gitignore`
    # holding `*` over the very file the pin exists to keep committed. Its exit
    # codes carry through unchanged — 2 is the generator's could-not-look (no
    # npx, no Node), 1 is a checkout that cannot export a schema.
    local rc=0
    "$pin" --write >"$WORK/pin.log" 2>&1 || rc=$?
    sed 's/^/  | /' "$WORK/pin.log"
    if [ "$rc" = "2" ]; then
        echo "!! tidy client: the client generator could not look (exit 2, its output above)." >&2
        echo "   That is scripts/gen_client.sh's own code for an absent toolchain — npx or" >&2
        echo "   Node is not on PATH. The OpenAPI document it exports is complete; what is" >&2
        echo "   missing is the thing that reads it." >&2
        raise_to 2
        return 0
    fi
    if [ "$rc" != "0" ]; then
        echo "!! tidy client: the client generator exited ${rc} (its output above)." >&2
        echo "   1 is a checkout that cannot export a schema — a finding in this tree, not" >&2
        echo "   in the generator." >&2
        raise_to 1
        return 0
    fi

    local moved=0
    cmp -s "$before_doc" "$doc" 2>/dev/null || moved=$((moved + 1))
    cmp -s "$before_client" "$client" 2>/dev/null || moved=$((moved + 1))
    if [ "$moved" = "0" ]; then
        echo "tidy client: nothing to do"
    else
        echo "tidy client: regenerated ${moved} file(s)"
    fi
    return 0
}

# =============================================================================
# SECRETS
# =============================================================================
tidy_secrets() {
    if [ ! -f "$ROOT/.secrets.baseline" ]; then
        skipped secrets "no .secrets.baseline in this checkout — there is no baseline to bring level"
        return 0
    fi
    local fold="${DJB_TIDY_FOLD:-$ROOT/scripts/pm_fold.sh}"
    if [ ! -x "$fold" ]; then
        echo "!! tidy secrets: ${fold} is not executable." >&2
        echo "   It is the tree's ONE legal baseline writer and this script deliberately" >&2
        echo "   owns no second one. Could-not-look." >&2
        raise_to 2
        return 0
    fi

    local before="$WORK/before.secrets.baseline"
    cp "$ROOT/.secrets.baseline" "$before"

    local rc=0
    "$fold" --only secrets --no-commit >"$WORK/fold.log" 2>&1 || rc=$?
    sed 's/^/  | /' "$WORK/fold.log"
    if [ "$rc" != "0" ]; then
        echo "!! tidy secrets: the fold exited ${rc} (its output above)." >&2
        echo "   The fold never answers 1, so this is a refusal or a could-not-look — a" >&2
        echo "   dirty tree is the usual cause, and the fold folds a COMMITTED tree" >&2
        echo "   whichever flags it was handed. Commit the boundary and re-run." >&2
        raise_to 2
        return 0
    fi

    if cmp -s "$before" "$ROOT/.secrets.baseline"; then
        echo "tidy secrets: nothing to do"
    else
        echo "tidy secrets: the baseline was re-scanned and rewritten, stampless and numberless"
    fi
    return 0
}

[ -z "$WANT_BUDGETS" ] || tidy_budgets
[ -z "$WANT_CLIENT" ] || tidy_client
[ -z "$WANT_SECRETS" ] || tidy_secrets

echo ""
case "$STATUS" in
0) echo "rung_tidy: DONE. Nothing was staged and nothing was committed — the changes above are in the working tree, for the caller's own diff." ;;
1) echo "rung_tidy: A SUBJECT COULD NOT BE APPLIED CLEANLY (above). Nothing was staged and nothing was committed." >&2 ;;
*) echo "rung_tidy: COULD NOT LOOK (above). Nothing was staged and nothing was committed." >&2 ;;
esac
exit "$STATUS"
