#!/usr/bin/env bash
# THIS FILE IS EXECUTED, AND IT IS BASH — not POSIX sh, and not zsh. The
# shebang above is honoured by `./this`; `sh this` and `zsh this` IGNORE it,
# and neither of them fails where the mistake was made. The argument in full is
# `scripts/tests/test_secrets_scan.sh`'s, at the top of that file, with the
# three measured answers-that-look-like-the-tree's-fault. Two tests, because on
# macOS `/bin/sh` IS bash and only POSIX MODE tells the two apart.
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
# drives: .claude/skills/rung-execution/SKILL.md .secrets.baseline apps/core/services.py pyproject.toml quality/checks.py scripts/archaeology_lib.sh scripts/pm_fold.sh scripts/rung_tidy.sh scripts/secrets_scan.sh scripts/tests
# The drive for THE BASELINE-REWRITE HAZARD — who is allowed to write
# `.secrets.baseline`, and what happens when a partial file set meets it.
#
#   ./scripts/tests/test_secrets_baseline_guard.sh          run every case
#   ./scripts/tests/test_secrets_baseline_guard.sh --list   name them and stop
#
# IT IS A SEPARATE FILE FROM `test_secrets_scan.sh` ON PURPOSE. That drive's
# subject is WHICH FILES the narrowed `--loop` scan is handed — a derivation
# over branches, merge-bases, renames and deletions. This drive's subject is
# WHAT THE BASELINE FILE LOOKS LIKE AFTERWARDS, which is a different question
# about a different artifact, and keeping them in two files keeps two lanes
# able to touch one each.
#
# ---------------------------------------------------------------------------
# THE HAZARD, AND WHAT MEASUREMENT DID TO THE STORY IT ARRIVED WITH.
#
# The hazard came in from the sibling platform as: *`detect-secrets-hook` run
# by hand over a partial file set REWRITES the baseline, dropping every result
# line for files it did not scan* — 77 result lines lost, reproduced twice,
# reverted by hand. That is a real and nasty shape: a baseline that silently
# narrows is a scanner that stops seeing, and nothing anywhere goes red.
#
# MEASURED HERE, on detect-secrets 1.5.0 (the version this checkout resolves;
# `pyproject.toml` pins the open range `detect-secrets>=1.5.0`, which is why
# case 1 PRINTS the version beside every verdict below rather than assuming
# one), THE SUBCOMMAND IN THAT SENTENCE IS THE WRONG ONE:
#
#   * `detect-secrets-hook --baseline B <partial paths>`  PRESERVES the result
#     lines of every file it was not handed. `SecretsCollection.trim` says so
#     in its own docstring — "for non-matching files, only the files in `self`
#     will be kept ... we cannot infer based on incomplete information" — and
#     its second loop is that sentence in code: a baseline file absent from the
#     scanned filelist falls through to `result[filename] = self[filename]`.
#     A file that WAS scanned and came back clean is dropped, which is correct
#     and is not this hazard.
#
#   * `detect-secrets scan --baseline B <partial paths>`  DROPS THEM. Measured
#     on a victim built by case 3 below: a baseline holding 4 entries across
#     3 files, re-scanned with one path named, comes back holding 1 entry
#     across 1 file. Exit 0. Nothing printed. That is the 77 lines.
#
# So the hazard is REAL on our installed version and it is REACHED BY A
# DIFFERENT COMMAND than the one the report named. Both halves matter, and
# both are cases here — case 2 pins the preserving behaviour (the day an
# upgrade changes `trim`, it goes red) and case 3 pins the dropping behaviour
# (which is what proves case 2's assertion is capable of failing at all: the
# same cmp harness, on the same victim, one subcommand apart, sees a drop).
#
# WHY THAT DISTINCTION IS NOT ACADEMIC HERE. This tree runs BOTH commands:
#
#   scripts/secrets_scan.sh   `detect-secrets-hook --baseline .secrets.baseline`
#                             over the active rung's changed files — a PARTIAL
#                             set, on every single `--loop` gate. The safe one.
#   scripts/pm_fold.sh        `detect-secrets scan --baseline .secrets.baseline`
#                             — the dropping one, and it is safe ONLY because
#                             it names NO PATHS: a full-tree re-scan writes the
#                             whole baseline back, which is its job. Append one
#                             path to that line and it becomes the hazard.
#
# That is the whole shape of the guard: cases 4 and 5 pin the leg to the
# preserving subcommand and pin the fold's line to naming no paths, because
# the distance between our one legal baseline writer and the incident is a
# single argument.
#
# WHAT THIS DRIVE DOES NOT COVER, declared rather than discovered:
#
#   * A BY-HAND INVOCATION IN SOMEBODY'S TERMINAL. Nothing here can see one,
#     and nothing here pretends to. That half is documented practice —
#     `.claude/skills/rung-execution/SKILL.md` §3 — consistent with this
#     house's guardrail posture, and it is the hazard's own declared blind
#     spot rather than a gap this drive left.
#   * THE TOOL'S BEHAVIOUR AGAINST A BASELINE THAT HOLDS RESULT LINES, ON THIS
#     TREE. It cannot be measured here, because this tree's baseline holds
#     none — and that emptiness is itself load-bearing: measured on 1.5.0,
#     `pre_commit_hook.main` returns 0 at `if not args.baseline: return 0`
#     before the baseline-modification block, and an empty `SecretsCollection`
#     is falsy. So the loop leg cannot rewrite this tree's baseline TODAY for a
#     structural reason, and the day one result line lands the write path goes
#     live on every gate. Case 4 prints that count rather than assuming it, and
#     case 2's victim is the tripwire that carries the reachable write path.
#   * WHETHER THE TRACKED `.secrets.baseline` SURVIVES A REAL `--loop` RUN.
#     Case 4 runs the loop's exact invocation line, at this checkout's root,
#     against the REAL baseline's CONTENT — but with `--baseline` pointed at a
#     copy in this drive's scratch, so the only thing it does not reach is the
#     write target itself. A drive that proved the point by letting the write
#     land on the tracked file would be the incident, performed nightly, inside
#     the gate that measures the tree by its hash.
#   * WHICH FILES THE LEG DERIVES. `test_secrets_scan.sh` is that drive, in
#     both directions, and this one deliberately re-proves none of it.
#   * A SECOND CHECKOUT, A CI RUNNER, OR ANY TREE BUT THIS ONE. Case 4's pin
#     is over this checkout's baseline as it stands; a different tree with
#     result lines in its baseline is a different measurement, and the victim
#     cases exist precisely because this tree's baseline carries none.
# ---------------------------------------------------------------------------

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_secrets_baseline_guard: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It carries the only thing keeping this drive's git commands inside its" >&2
    echo "   own scratch directory. Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh

DRIVE_OPTED_IN_TO_FINISH=1

PASSED=0
FAILED=0

cannot_look() {
    echo "!! test_secrets_baseline_guard: $*" >&2
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
    # A mistyped flag is never a silently different run.
    echo "!! unknown argument '$1': test_secrets_baseline_guard.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

command -v git >/dev/null 2>&1 || cannot_look "no git on PATH"
command -v uv >/dev/null 2>&1 || cannot_look "no uv on PATH — the scanner cannot be resolved"
command -v python3 >/dev/null 2>&1 || cannot_look "no python3 on PATH — every baseline reader below and the stamp strip are python"
[ -f scripts/secrets_scan.sh ] || cannot_look "scripts/secrets_scan.sh is not in this tree"
[ -f scripts/pm_fold.sh ] || cannot_look "scripts/pm_fold.sh is not in this tree"
[ -f .secrets.baseline ] || cannot_look ".secrets.baseline is not in this tree — there is no baseline to guard"

ROOT="$PWD"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-baseline-drive.XXXXXX")" || cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'rm -rf "$WORK"'

# The two executables, resolved ONCE through `uv` from this checkout, then
# called by absolute path. The victim cases run with the working directory
# inside a throwaway repository, where `uv run` has no project to resolve and
# would either fail or — worse — resolve somebody else's.
DS_HOOK=""
DS_SCAN=""
DS_VERSION=""
resolve_scanner() {
    local probe
    probe="$(cd "$ROOT" && uv run python -c '
import shutil
from detect_secrets.__version__ import VERSION
print(shutil.which("detect-secrets-hook") or "")
print(shutil.which("detect-secrets") or "")
print(VERSION)
' 2>"${WORK}/resolve.log")" || {
        sed 's/^/     | /' "${WORK}/resolve.log" >&2
        cannot_look "could not resolve detect-secrets through uv in ${ROOT}"
    }
    DS_HOOK="$(printf '%s\n' "$probe" | sed -n 1p)"
    DS_SCAN="$(printf '%s\n' "$probe" | sed -n 2p)"
    DS_VERSION="$(printf '%s\n' "$probe" | sed -n 3p)"
}
resolve_scanner

# --- the assertions ----------------------------------------------------------
CURRENT=""
OUT=""
RC=0
N=0

ok() {
    echo "  ok       ${CURRENT} — $1"
    PASSED=$((PASSED + 1))
}
bad() {
    echo "  FAILED   ${CURRENT} — $1"
    [ -n "$OUT" ] && [ -f "$OUT" ] && sed 's/^/             | /' "$OUT" | tail -20
    FAILED=$((FAILED + 1))
}

# Count the result ENTRIES and name the FILES a baseline holds. Both, because
# they fail differently: entries going down is the drop, and the file list is
# what makes the failure message say WHICH file went quiet.
baseline_files() {
    python3 -c '
import json, sys
with open(sys.argv[1]) as fh:
    print(" ".join(sorted(json.load(fh)["results"])))
' "$1"
}
baseline_entries() {
    python3 -c '
import json, sys
with open(sys.argv[1]) as fh:
    print(sum(len(v) for v in json.load(fh)["results"].values()))
' "$1"
}

# Build a throwaway repository holding three files with real, distinct secrets
# and one without, scan it FULL, and leave the baseline staged. Staged because
# `detect-secrets-hook` refuses outright when the baseline it was handed is
# unstaged-modified (`raise_exception_if_baseline_file_is_unstaged`) — measured:
# without the `git add` the hook prints "Your baseline file is unstaged" and
# exits 1 without ever reaching the code this drive is about, which reads from
# outside exactly like a preserved baseline.
#
# It is its OWN VICTIM, and that is the point: a demonstration that destroys
# something needs to have made the thing it destroys. Nothing below ever names
# this checkout's `.secrets.baseline` as a write target.
VICTIM=""
build_victim() {
    VICTIM="${WORK}/victim${N}"
    drive_require_scratch VICTIM "${VICTIM:-}"
    mkdir -p "$VICTIM" || cannot_look "could not make the victim repository"
    git -C "$VICTIM" init -q . || cannot_look "could not init the victim repository"
    git -C "$VICTIM" config user.email drive@example.invalid
    git -C "$VICTIM" config user.name drive
    # Three AWS-shaped key ids, one per file, differing in the final character
    # so each hashes distinctly and a drop names exactly one file. They are the
    # drive's SUBJECT: a victim baseline with no result lines in it cannot show
    # a result line being dropped, which is the whole measurement.
    #
    # THE PREFIX IS ASSEMBLED AT RUNTIME AND THAT IS NOT CLEVERNESS. House rule
    # 23's own scanner is a raw regex over `scripts/**` with no pragma path
    # (`quality/checks.py`, `_SECRET_PATTERNS`), and `detect-secrets` reads file
    # text too — so a drive about the secret scanners, written with the literal
    # in it, reddens both of them for its own fixtures. Splitting the token is
    # `scripts/archaeology_lib.sh`'s idiom in `archaeology_patterns` (`_at=icus`
    # and its siblings), used here for its reason: a file that must TALK about a
    # censused string keeps the string out of its own text rather than teaching
    # the census to look away. Nothing is suppressed and no valve is spent — the
    # scanners are right, and there is simply no key id in this file to find.
    local _k=AKI
    printf 'aws_key = "%sAIOSFODNN7EXAMPLE"\n' "$_k" >"${VICTIM}/alpha.py"
    printf 'aws_key = "%sAIOSFODNN7EXAMPLF"\n' "$_k" >"${VICTIM}/beta.py"
    printf 'aws_key = "%sAIOSFODNN7EXAMPLG"\n' "$_k" >"${VICTIM}/gamma.py"
    printf 'ordinary = 1\n' >"${VICTIM}/delta.py"
    git -C "$VICTIM" add -A
    git -C "$VICTIM" commit -qm base
    (cd "$VICTIM" && "$DS_SCAN" scan >.secrets.baseline) ||
        cannot_look "the full scan of the victim repository failed"
    git -C "$VICTIM" add .secrets.baseline
    cp "${VICTIM}/.secrets.baseline" "${VICTIM}/baseline.before"
}

case_the_installed_scanner_names_its_own_version() {
    CURRENT="installed version"
    N=$((N + 1))
    OUT=""
    # `pyproject.toml` pins a RANGE (`detect-secrets>=1.5.0`), so every verdict
    # in this file is a verdict about one resolved version and says which. A
    # version this drive could not read is could-not-look, not a pass — the
    # cases below would otherwise be asserting about an unnamed tool.
    echo "             | detect-secrets ${DS_VERSION}"
    echo "             | hook  ${DS_HOOK}"
    echo "             | scan  ${DS_SCAN}"
    if [ -z "$DS_VERSION" ] || [ -z "$DS_HOOK" ] || [ -z "$DS_SCAN" ]; then
        bad "the installed scanner did not name itself — every verdict below would be about an unknown tool"
        return
    fi
    case "$DS_VERSION" in
    [0-9]*.[0-9]*) ok "detect-secrets ${DS_VERSION}, and every verdict below is about that version" ;;
    *) bad "'${DS_VERSION}' is not a version this drive recognises" ;;
    esac
}

case_the_hook_over_a_partial_set_preserves_the_files_it_did_not_scan() {
    CURRENT="hook, partial set"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    build_victim

    local before_files before_entries after_files after_entries
    before_files="$(baseline_files "${VICTIM}/baseline.before")"
    before_entries="$(baseline_entries "${VICTIM}/baseline.before")"
    if [ "$before_entries" -lt 3 ]; then
        bad "the victim baseline holds ${before_entries} entries; this case needs at least 3 to see a drop"
        return
    fi

    # THE SHIPPED SHAPE, not an approximation of it: the leg feeds a
    # NUL-separated list through `xargs -0` into `detect-secrets-hook
    # --baseline <b>` (scripts/secrets_scan.sh, `secrets_scan_loop`), so that is
    # the invocation here — one path in the list, a partial set by construction.
    # The one thing this victim has that this checkout does not is a baseline
    # with result lines in it, which is what makes the write path reachable and
    # this assertion a measurement rather than a short-circuit.
    RC=0
    printf '%s\0' 'alpha.py' >"${WORK}/vlist${N}"
    (cd "$VICTIM" && xargs -0 "$DS_HOOK" --baseline .secrets.baseline <"${WORK}/vlist${N}") >"$OUT" 2>&1 || RC=$?
    after_files="$(baseline_files "${VICTIM}/.secrets.baseline")"
    after_entries="$(baseline_entries "${VICTIM}/.secrets.baseline")"

    if [ "$after_files" = "$before_files" ] && [ "$after_entries" = "$before_entries" ]; then
        ok "exit ${RC}; ${after_entries} entries across [${after_files}] survived a scan of alpha.py alone"
    else
        bad "the hook narrowed the baseline: [${before_files}] / ${before_entries} entries became [${after_files}] / ${after_entries}"
        return
    fi

    if cmp -s "${VICTIM}/baseline.before" "${VICTIM}/.secrets.baseline"; then
        ok "the baseline file is byte-identical — the hook wrote nothing at all"
    else
        # Not a failure on its own: a rewrite that PRESERVES every result is a
        # line-number or stamp refresh, which is the hook's documented job. It
        # is said out loud because a silently rewritten baseline is the thing
        # this whole file exists to make visible.
        ok "the baseline file was rewritten but every result survived — a stamp/line-number refresh, not a narrowing"
    fi
}

case_the_scan_subcommand_over_a_partial_set_drops_them() {
    CURRENT="scan --baseline, partial set"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    build_victim

    # THE POSITIVE CONTROL, and the reason it is a case rather than a comment:
    # the case above asserts that nothing was lost. An assertion that nothing
    # was lost is worth exactly as much as the harness's ability to notice a
    # loss — so the same harness, on the same victim, one subcommand apart, is
    # made to SEE one. If this case ever goes green-by-preservation, the case
    # above stopped being evidence on the same day.
    local before_files before_entries after_files after_entries
    before_files="$(baseline_files "${VICTIM}/baseline.before")"
    before_entries="$(baseline_entries "${VICTIM}/baseline.before")"

    RC=0
    (cd "$VICTIM" && "$DS_SCAN" scan --baseline .secrets.baseline alpha.py) >"$OUT" 2>&1 || RC=$?
    after_files="$(baseline_files "${VICTIM}/.secrets.baseline")"
    after_entries="$(baseline_entries "${VICTIM}/.secrets.baseline")"

    echo "             | before [${before_files}] ${before_entries} entries"
    echo "             | after  [${after_files}] ${after_entries} entries · exit ${RC}"

    if [ "$after_entries" -lt "$before_entries" ]; then
        ok "exit ${RC} and SILENT: ${before_entries} entries became ${after_entries} — the hazard, on detect-secrets ${DS_VERSION}"
    else
        bad "the drop did NOT happen. Either detect-secrets ${DS_VERSION} fixed it — in which case the hook case above lost its positive control and the doctrine line in rung-execution's SKILL.md is now over-strict — or this harness can no longer see a narrowing, in which case NOTHING in this file is evidence."
    fi
}

case_the_loop_shaped_invocation_leaves_this_baseline_byte_identical() {
    CURRENT="loop-shaped invocation, real baseline"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"

    # THE PIN criterion 2 asks for. The `--loop` leg IS a partial-set hook
    # invocation with `--baseline` (scripts/secrets_scan.sh, `secrets_scan_loop`),
    # so this runs that invocation's exact line — same binary, same flag, same
    # `xargs -0` feed, working directory at this checkout's root, against the
    # REAL baseline's content — and asserts the result is byte-identical.
    #
    # `--baseline` points at a COPY in this drive's scratch. That is the one
    # deviation from the shipped line and it is the write target only: if the
    # day comes that an upgrade starts rewriting, this case goes red on the
    # copy instead of the tracked file, which is the difference between a
    # tripwire and the incident.
    #
    # WHAT THIS CASE IS WORTH DEPENDS ON A NUMBER IT PRINTS, and pretending
    # otherwise would make it one of the green instruments that lie. Measured
    # on detect-secrets 1.5.0: `pre_commit_hook.main` reaches its baseline-
    # modification block only past `if not args.baseline: return 0`, and
    # `args.baseline` is a `SecretsCollection` — WHICH IS FALSY WHEN EMPTY. So
    # while this tree's `.secrets.baseline` carries ZERO result entries (it
    # does today), the hook returns 0 before `should_update_baseline` is ever
    # called and byte-identity here is STRUCTURAL, not a verdict about `trim`.
    # Proven by plant: a copy of this tree's baseline edited to claim version
    # 1.4.0 — the one condition that forces an unconditional rewrite — comes
    # back byte-identical anyway, because the short-circuit is upstream of it.
    #
    # The substantive tripwire on the tool therefore lives in the victim case
    # above, whose baseline HAS results and so does reach the write path. This
    # case pins the SHIPPED LINE, and it stops being merely structural the day
    # a result line lands in this tree's baseline — which is why it prints the
    # count instead of assuming it.
    local copy list
    copy="${WORK}/baseline${N}.json"
    list="${WORK}/list${N}"
    cp "$ROOT/.secrets.baseline" "$copy" || {
        bad "could not copy this checkout's baseline"
        return
    }

    # The file set: the active rung's own changes, derived by the shipped
    # function, because that is the set the leg really hands over. An empty set
    # is legitimate (a rung that has changed nothing), and the leg's own answer
    # to it is to scan nothing — which would make this case vacuous, so it
    # falls back to a fixed pair of tracked files and SAYS it did.
    local basis_note derive_rc=0
    (
        cd "$ROOT" || exit 2
        # shellcheck source=scripts/secrets_scan.sh
        . scripts/secrets_scan.sh
        secrets_scan_changed_files "$list"
    ) >"$OUT" 2>&1 || derive_rc=$?
    if [ "$derive_rc" -ne 0 ] || [ ! -s "$list" ]; then
        printf '%s\0%s\0' 'scripts/secrets_scan.sh' 'scripts/pm_fold.sh' >"$list"
        basis_note="a fixed pair of tracked files (the rung's own change set was empty or underivable)"
    else
        basis_note="the active rung's own changed files, derived by the shipped function"
    fi
    echo "             | set: ${basis_note}"
    echo "             | $(tr '\0' ' ' <"$list")"

    RC=0
    (cd "$ROOT" && xargs -0 "$DS_HOOK" --baseline "$copy" <"$list") >>"$OUT" 2>&1 || RC=$?

    if [ "$RC" -ne 0 ] && [ "$RC" -ne 3 ]; then
        bad "the loop-shaped invocation exited ${RC} — a finding or a broken scanner, and this case cannot speak about the baseline until that is cleared"
        return
    fi
    if cmp -s "$ROOT/.secrets.baseline" "$copy"; then
        local live_entries
        live_entries="$(baseline_entries "$ROOT/.secrets.baseline")"
        if [ "$live_entries" = "0" ]; then
            ok "exit ${RC}; byte-identical — but this tree's baseline holds 0 result entries, so the hook short-circuits at \`if not args.baseline: return 0\` and never reaches the write path. STRUCTURAL, not a verdict about the tool: the victim case above is the tripwire that is."
        else
            ok "exit ${RC}; the baseline is byte-identical after a real partial-set invocation on detect-secrets ${DS_VERSION}, with ${live_entries} result entries live — the write path was reachable and nothing moved"
        fi
    else
        bad "THE LOOP LEG MUTATED THE BASELINE on detect-secrets ${DS_VERSION}. This is the guard's trigger: secrets_scan.sh must invoke against a tempfile copy, or strip-and-compare (the generated_at pattern at scripts/pm_fold.sh's step (c)). The delta:
$(diff "$ROOT/.secrets.baseline" "$copy" | sed 's/^/             | /' | head -40)"
    fi
}

case_a_stampless_baseline_is_accepted_by_the_installed_scanner() {
    CURRENT="stampless baseline, installed scanner"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"

    # THE COMMITTED SHAPE, and what has to be true for it to be safe.
    # `detect-secrets scan` rewrites `"generated_at"` on every run whether or not
    # anything moved, so a committed baseline carrying one differs on its last
    # line between every two branches that re-scanned — measured here as
    # `ea56096 fold: baseline shifted` and on the sibling product as three merges
    # hand-resolved in one night. `scripts/pm_fold.sh` step (c) therefore strips
    # the stamp before it commits, and this checkout's baseline carries none.
    #
    # That is only safe while the INSTALLED scanner does not need the field. It
    # does not — `detect_secrets/core/baseline.py` writes it in
    # `format_for_output` and reads it nowhere — but a structural claim about a
    # pinned RANGE (`detect-secrets>=1.5.0`) is a claim about whichever version
    # resolved today, so it is DRIVEN here rather than cited, against its own
    # victim, with the version printed beside the verdict.
    local stamps
    stamps="$(grep -c '"generated_at"' "$ROOT/.secrets.baseline" || true)"
    if [ "$stamps" = "0" ]; then
        ok "this checkout's committed baseline carries no generated_at stamp — the one line two lanes would conflict on"
    else
        bad "this checkout's committed baseline carries ${stamps} generated_at line(s). Every lane that re-scans rewrites that line, so every pair of lanes conflicts on it: scripts/pm_fold.sh step (c) is supposed to strip it before committing."
        return
    fi

    build_victim

    # The victim's own baseline, stripped the way the fold strips it — a JSON
    # rewrite, because `"generated_at"` is the LAST key the scanner writes and
    # deleting the line textually leaves the comma above it and stops being JSON.
    if ! python3 - "${VICTIM}/.secrets.baseline" <<'PY' >>"$OUT" 2>&1
import json
import sys

with open(sys.argv[1]) as fh:
    data = json.load(fh)
data.pop("generated_at", None)
with open(sys.argv[1], "w") as fh:
    fh.write(json.dumps(data, indent=2) + "\n")
PY
    then
        bad "could not strip the stamp from the victim baseline"
        return
    fi
    cp "${VICTIM}/.secrets.baseline" "${VICTIM}/baseline.before"
    git -C "$VICTIM" add .secrets.baseline

    local vstamps
    vstamps="$(grep -c '"generated_at"' "${VICTIM}/.secrets.baseline" || true)"
    if [ "$vstamps" != "0" ]; then
        bad "the stripped victim baseline still carries ${vstamps} stamp(s) — this case cannot speak"
        return
    fi

    # (1) A CLEAN file: the hook must exit 0 and say nothing.
    RC=0
    (cd "$VICTIM" && "$DS_HOOK" --baseline .secrets.baseline delta.py) >>"$OUT" 2>&1 || RC=$?
    if [ "$RC" = "0" ]; then
        ok "detect-secrets ${DS_VERSION}: exit 0 over a clean file with no stamp in the baseline"
    else
        bad "the hook exited ${RC} over a CLEAN file against a stampless baseline on detect-secrets ${DS_VERSION} — the field's absence is not tolerated, and the fold's strip (pm_fold.sh step (c)) must go back to restoring instead"
        return
    fi

    # (2) A KEY-SHAPED file the baseline has never seen: the hook must still
    #     FIND it. A scanner that tolerates a stampless baseline by going quiet
    #     would pass (1) and be worthless, which is why (2) is not optional.
    #     The prefix is assembled at runtime for build_victim's reason.
    local _k=AKI
    printf 'aws_key = "%sAIOSFODNN7EXAMPLZ"\n' "$_k" >"${VICTIM}/epsilon.py"
    RC=0
    (cd "$VICTIM" && "$DS_HOOK" --baseline .secrets.baseline epsilon.py) >>"$OUT" 2>&1 || RC=$?
    if [ "$RC" != "0" ]; then
        ok "detect-secrets ${DS_VERSION}: exit ${RC} over a key-shaped file — a stampless baseline still finds secrets"
    else
        bad "the hook exited 0 over a file carrying a key-shaped string. Against a stampless baseline the scanner has stopped looking, and every fold since is a baseline that vouches for nothing."
        return
    fi

    # (3) And it wrote nothing. `cmp` silent, both invocations later.
    if cmp -s "${VICTIM}/baseline.before" "${VICTIM}/.secrets.baseline"; then
        ok "the stampless baseline is byte-identical after both invocations — the hook did not re-stamp it"
    else
        bad "the hook rewrote the stampless baseline on detect-secrets ${DS_VERSION}. If it puts the stamp back, the fold's strip is being undone by the per-rung leg and the conflict class returns. The delta:
$(diff "${VICTIM}/baseline.before" "${VICTIM}/.secrets.baseline" | sed 's/^/             | /' | head -20)"
    fi
}

case_the_loop_leg_names_the_preserving_subcommand() {
    CURRENT="secrets_scan.sh's subcommand"
    N=$((N + 1))
    OUT=""

    # A pin on the LINE, not on the behaviour: case 2 and case 3 measured that
    # the two subcommands differ, and this is what keeps the leg on the right
    # side of that difference when somebody edits it.
    if grep -q 'detect-secrets-hook --baseline' scripts/secrets_scan.sh; then
        ok "the leg invokes \`detect-secrets-hook --baseline\` — the subcommand that preserves unscanned files"
    else
        bad "scripts/secrets_scan.sh no longer invokes \`detect-secrets-hook --baseline\`. If it now invokes \`detect-secrets scan --baseline\` over the rung's changed files, every result line for every untouched file is dropped on every gate, silently — case 3 above is that measurement."
    fi

    if grep -q 'detect-secrets scan --baseline' scripts/secrets_scan.sh; then
        bad "scripts/secrets_scan.sh names \`detect-secrets scan --baseline\`, which over a partial path set is the narrowing measured in case 3. The per-rung leg is a partial set BY DESIGN."
    else
        ok "the leg does not name \`detect-secrets scan --baseline\` anywhere"
    fi
}

# baseline_stray_writers <scripts-dir> — every file in that directory, other
# than `pm_fold.sh`, that INVOKES the full-tree baseline writer. One per line,
# silent when there are none.
#
# A COMMENT IS NOT AN INVOCATION, and neither is a BANNER: `pm_fold.sh` echoes
# the command it is about to run so the operator can read it, and
# `scripts/rung_tidy.sh`'s header ARGUES the one-legal-writer doctrine by naming
# the command it deliberately does not run. Both classes are stripped by the
# command word at the head of the line, which is the only thing that tells an
# invocation from a mention without parsing bash.
#
# THE DIRECTORY IS AN ARGUMENT SO THE CENSUS CAN BE AIMED AT A VICTIM. Nothing
# else about it moved.
baseline_stray_writers() {
    local dir="$1" f out=""
    for f in "$dir"/*.sh; do
        [ -f "$f" ] || continue
        case "$f" in
        */pm_fold.sh) continue ;;
        esac
        if grep -n 'detect-secrets scan --baseline' "$f" |
            grep -qvE '^[0-9]+:[[:space:]]*(#|echo |printf )'; then
            out="${out}${f}
"
        fi
    done
    printf '%s' "$out"
}

# THE CANARY. A census that has never fired is a census nobody can distinguish
# from a grep that stopped matching — and this one guards the single most
# expensive silent failure in the tree, a second baseline writer narrowing the
# file on every run. The victim is this case's OWN: a scratch copy of
# `scripts/`, with the writer planted in the copy of `rung_tidy.sh`, because a
# destructive demonstration never uses found state and never writes into the
# checkout it is measuring.
case_a_planted_second_writer_in_rung_tidy_is_caught() {
    CURRENT="a planted second writer is caught"
    N=$((N + 1))
    OUT=""
    local victim="${WORK}/stray-scripts-${N}"
    mkdir -p "$victim"
    local f
    for f in scripts/*.sh; do
        [ -f "$f" ] || continue
        cp "$f" "$victim/"
    done
    if [ ! -f "$victim/rung_tidy.sh" ]; then
        bad "scripts/rung_tidy.sh is not in this tree, so the census has nothing to be aimed at — this case cannot speak"
        return
    fi

    # THE CONTROL FIRST: the real files, copied, unplanted. A canary that fires
    # on the unplanted copy is a canary firing for the copy's reason.
    local before
    before="$(baseline_stray_writers "$victim")"
    if [ -z "$before" ]; then
        ok "the copied scripts/ has no stray writer — the control is clean"
    else
        bad "the copied scripts/ already names a stray writer, so the plant below proves nothing:
$(printf '%s' "$before" | sed 's/^/             | /')"
        return
    fi

    printf '\nuv run detect-secrets scan --baseline .secrets.baseline apps/core/services.py\n' \
        >>"$victim/rung_tidy.sh"
    local after
    after="$(baseline_stray_writers "$victim")"
    case "$after" in
    *rung_tidy.sh*)
        ok "the planted writer in rung_tidy.sh is named by the census — it is looking at the new file"
        ;;
    *)
        bad "a planted \`scan --baseline\` in rung_tidy.sh is INVISIBLE to the stray census. The census walks scripts/*.sh, so a new script there is in its population by construction — unless it has stopped matching."
        ;;
    esac
}

case_the_fold_is_the_only_baseline_writer_and_names_no_paths() {
    CURRENT="one legal writer"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"

    # THE ONE-LEGAL-WRITER DOCTRINE, as far as a check can reach it. The fold's
    # full-tree re-scan is the writer; what makes it safe is that its line ends
    # at the baseline and names NO PATHS. One path appended and it becomes the
    # incident, so the shape of that line is what is pinned.
    # A comment is not an invocation, and neither is a BANNER: `pm_fold.sh:439`
    # echoes the command it is about to run so the operator can read it, and the
    # closing quote of that echo is not a path argument. Both classes are
    # stripped by the command word at the head of the line, which is the only
    # thing that tells an invocation from a mention without parsing bash.
    local fold_lines
    fold_lines="$(grep -n 'detect-secrets scan --baseline' scripts/pm_fold.sh |
        grep -vE '^[0-9]+:[[:space:]]*(#|echo |printf )' || true)"
    if [ -z "$fold_lines" ]; then
        bad "scripts/pm_fold.sh no longer runs \`detect-secrets scan --baseline\` — the tree's one legal baseline writer is gone, and the practice line in rung-execution's SKILL.md now points at nothing"
        return
    fi
    printf '%s\n' "$fold_lines" | sed 's/^/             | /'

    local offenders=""
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        # Everything after the baseline argument on that line, with a trailing
        # `|| SOMETHING` (the fold's own status capture) and comments removed.
        case "$line" in
        *'detect-secrets scan --baseline .secrets.baseline'*)
            local tail_of
            tail_of="${line#*detect-secrets scan --baseline .secrets.baseline}"
            tail_of="${tail_of%%|*}"
            tail_of="${tail_of%%#*}"
            # Nothing but whitespace may follow. A path here is the hazard.
            case "$tail_of" in
            *[![:space:]]*) offenders="${offenders}${line}
" ;;
            esac
            ;;
        *)
            offenders="${offenders}${line}
" # a form this pin does not recognise is reported, never waved through
            ;;
        esac
    done <<<"$fold_lines"

    if [ -z "$offenders" ]; then
        ok "the fold's re-scan names no paths — a full-tree rewrite, which is what makes the one legal writer legal"
    else
        bad "the fold's re-scan now carries path arguments, which is the narrowing measured in case 3 aimed at the tracked baseline:
$(printf '%s' "$offenders" | sed 's/^/             | /')"
    fi

    # And nobody ELSE in the root of scripts/ writes the baseline that way.
    # Root only, and not recursive: `scripts/tests/` is where the drives live
    # and this file itself names the string in every case above.
    #
    # THE CENSUS BODY MOVED INTO `baseline_stray_writers` AND THE ASSERTIONS DID
    # NOT. A census that can only ever be pointed at the real `scripts/` is a
    # census nothing can prove is looking — it goes green on a tree with a
    # second writer in it exactly as it goes green on a tree without one, and
    # the two are indistinguishable from here. `case_a_planted_second_writer_in
    # _rung_tidy_is_caught` below points the SAME function at a scratch copy of
    # `scripts/` with a writer planted in `rung_tidy.sh`, which is the only form
    # of that proof that does not write into this checkout.
    local strays=""
    strays="$(baseline_stray_writers scripts)"
    if [ -z "$strays" ]; then
        ok "no other script in scripts/ writes the baseline through \`detect-secrets scan --baseline\`"
    else
        bad "a second baseline writer appeared in scripts/, and the doctrine says there is one:
$(printf '%s' "$strays" | sed 's/^/             | /')"
    fi
}

case_the_installed_scanner_names_its_own_version
case_the_hook_over_a_partial_set_preserves_the_files_it_did_not_scan
case_the_scan_subcommand_over_a_partial_set_drops_them
case_the_loop_shaped_invocation_leaves_this_baseline_byte_identical
case_a_stampless_baseline_is_accepted_by_the_installed_scanner
case_the_loop_leg_names_the_preserving_subcommand
case_the_fold_is_the_only_baseline_writer_and_names_no_paths
case_a_planted_second_writer_in_rung_tidy_is_caught

echo "test_secrets_baseline_guard: ${PASSED} passed · ${FAILED} failed · detect-secrets ${DS_VERSION}"
drive_finished
if [ "$FAILED" -gt 0 ]; then
    echo "!! the baseline-rewrite guard did not hold. A baseline that silently narrows is a" >&2
    echo "   scanner that stopped looking: every result line it loses is a secret nothing" >&2
    echo "   will ever flag again, and no leg anywhere goes red for it." >&2
    exit 1
fi
exit 0
