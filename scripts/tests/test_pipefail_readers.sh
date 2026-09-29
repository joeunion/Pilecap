#!/usr/bin/env bash
# THIS FILE IS EXECUTED, AND IT IS BASH — not POSIX sh, and not zsh. The
# shebang above is honoured by `./this`; `sh this` and `zsh this` IGNORE it,
# and neither of them fails where the mistake was made.
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
# drives: deploy/ docs/product/instruments.md scripts/
# The drive for THE READER THAT LEAVES EARLY — every `producer | head`-shaped
# pipeline in a script that runs under `set -o pipefail`, and the two forms that
# survive one.
#
#   ./scripts/tests/test_pipefail_readers.sh          run every case
#   ./scripts/tests/test_pipefail_readers.sh --list   name them and stop
#
# THE CLASS, in four lines, because it is the kind of defect that passes every
# test anyone writes for it:
#
#     set -o pipefail
#     first="$(producer | head -1)"
#
# `head -1` reads its line and CLOSES the pipe. If the producer had already
# finished writing — anything under the kernel's pipe buffer, 64 KiB on Linux
# and on macOS — it exited 0 long before, and the pipeline is 0. If the producer
# was still writing, it takes SIGPIPE, the pipeline's status becomes 141, and
# under `set -e` the script DIES at a line that read the value it wanted
# correctly. So the same line is green on every small input anybody drove it
# with and fatal on the big one, in production, once.
#
# THE TWO FORMS THAT SURVIVE, and the cases below prove each keeps the value:
#
#   { producer || true; } | head -1      the producer's death is swallowed
#                                        INSIDE the pipeline, so pipefail sees
#                                        only the reader's own 0.
#   whole="$(producer)"                  no pipe at all: the producer runs to
#   first="${whole%%$'\n'*}"             completion, its status is honest, and
#                                        the slice is a parameter expansion.
#
# THE SIBLING CENSUS, so neither of us is read as the whole answer.
# `scripts/tests/test_sweep.sh::case_a_presence_probe_survives_a_long_scan`
# censuses a DIFFERENT shape of the same class — a reader that short-circuits its
# own producer at the TAIL of a pipeline, keyed per site with a reasoned census
# row — and it is the sharper instrument where it looks. This file's grep is the
# three named reader shapes across the scripts whose exit status is a verdict.
# Neither subsumes the other, and each found a site the other did not.
#
# A THIRD disposition is legal and is not a rewrite: a reader that reads to EOF
# (`sed -n '1,5p'`, `cut`, `awk` with no `exit`) never closes the pipe early, so
# it never orphans the producer. Replacing an early-exit reader with an EOF one
# is the fix, not an evasion of the census — the class is the EARLY EXIT.
#
# AND A FOURTH SHAPE, WHICH IS NOT THE EARLY EXIT AND IS IN THE CENSUS ANYWAY.
# `producer | tee file` reads to EOF, so it orphans nothing and the paragraph
# above forgives it — but it still takes the pipeline's exit status away from
# the producer, which is the OTHER half of what the class costs. On a line
# whose status is a verdict, the loss is the same loss:
#
#     GATE_SKIP_DJANGO_LEG=1 uv run python -m quality.gate … | tee "$OUT"
#     GATE_RC=${PIPESTATUS[0]}
#
# was a gate leg, and `PIPESTATUS[0]` is a second reading of a status the shell
# had already made ambiguous rather than a reason the pipe was safe: the leg's
# `$?` meant `tee`. The fix is the same as everywhere else here — redirect to
# the file, read `$?`, then `cat` it — and the cost is that the leg stops
# streaming, which is written down at the site. The census carries `tee` so the
# next one is a red rather than a reading, and the DISPOSITIONS are unchanged:
# a comment, the valve with a reason, or a `{ producer || true; }` producer.
#
# WHAT IS UNDER DRIVE:
#   the CLASS    — the old form loses the status under a padded producer, and
#                  both replacement forms keep the value and the status
#   the CENSUS   — no early-exit reader follows a pipe in any script whose exit
#                  status is a verdict somebody acts on
#   the SITES    — two of the gate's own rewritten lines are READ OUT OF
#                  `scripts/check.sh` and run against a padded input, so the
#                  case measures the shipped line rather than a copy of it
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   1. THE CENSUS IS FOUR READER SHAPES — `| head`, `| grep -m`, an `awk`
#      that calls `exit`, and `| tee`. `sed -n '1p;q'`, a `read -r` that
#      returns, a `while … break` and any other early return from a loop
#      reading a pipe are the same class and are NOT in the grep. The valve
#      comment is where the next shape gets recorded when somebody finds it.
#   2. THE ASSERTED POPULATION IS THE SCRIPTS, AND THE DRIVES NAMED IN
#      `asserted_drives` — NOT EVERY DRIVE. `scripts/*.sh`, `deploy/*.sh` and
#      the hooks are asserted to zero: those are the files whose exit status
#      becomes a verdict, a merge, a release or a backup, and a SIGPIPE there is
#      a ritual that stopped halfway. A drive joins them when a SIGPIPE in it
#      has been paid for: the `--loop` scope drive read a passing case as
#      could-not-look on a CI runner whose collection log was bigger than the
#      builders' (`sort -u | head -1` over the log), and the db-template drive
#      carried the same `sort | head -1` shape — both are asserted now. Every
#      OTHER drive under `scripts/tests/` and `deploy/tests/` is PRINTED and not
#      asserted — a drive that dies of this fails loudly and is re-run, and
#      several of those files belong to lanes that are open. The notice is
#      derived from the directory, never typed, so the count cannot go stale
#      silently; closing it is a rung of its own and
#      `docs/product/instruments.md` carries the row.
#   3. It proves the two REWRITTEN gate lines survive a padded producer. It does
#      not prove the gate's surrounding logic is right — the counts-file
#      comparison and the pass-2 classifier have their own drives.
#   4. The padding is 200,000 bytes, comfortably past a 64 KiB pipe buffer on
#      both platforms this tree runs on. A kernel with a pipe buffer larger than
#      that would make the control case green and it would say so by failing.
set -euo pipefail

cd "$(dirname "$0")/../.."

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_pipefail_readers: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It carries the only thing keeping this drive's scratch work inside its" >&2
    echo "   own scratch directory. Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh

# Section 5 of the preamble: on macOS's bash 3.2 a `set -u` death hands the EXIT
# trap a status of 0, so a drive that never reached its own summary reports
# success. Opting in makes that could-not-look instead.
DRIVE_OPTED_IN_TO_FINISH=1

PASSED=0
FAILED=0

cannot_look() {
    echo "!! test_pipefail_readers: $*" >&2
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
    echo "!! unknown argument '$1': test_pipefail_readers.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

[ -f scripts/check.sh ] || cannot_look "scripts/check.sh is not in this tree — the shipped lines have no home"

ROOT="$PWD"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-pipefail-drive.XXXXXX")" || cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'rm -rf "$WORK"'

CURRENT=""
ok() {
    echo "  ok       ${CURRENT} — $1"
    PASSED=$((PASSED + 1))
}
bad() {
    echo "  FAILED   ${CURRENT} — $1"
    FAILED=$((FAILED + 1))
}

# THE PADDED PRODUCER, and it is one function so every case pads identically.
# 200,000 bytes with no newline in them, behind one line that says MATCH: a
# reader taking the first line has everything it wanted and the producer is
# still mid-write.
pad_bytes=200000
padded_producer() {
    printf 'MATCH\n'
    head -c "$pad_bytes" /dev/zero | tr '\0' x
}

# The census grep, written once and read by two cases. FOUR reader shapes, and
# the fourth is a different failure by the same route — see the header.
CENSUS_RE='\| *(head|grep -m|awk[^|]*exit|tee([[:space:]]|$))'

# The drives that are ASSERTED to zero beside the scripts — see blind spot 2.
# Typed, because joining is a decision about a drive, and each one is a drive
# whose SIGPIPE was paid for; a name here that is not a file is a FAILED
# assertion in the census case, never a quiet skip.
asserted_drives() {
    printf '%s\n' \
        scripts/tests/test_loop_scope.sh \
        scripts/tests/test_db_template.sh
}

# The population whose exit status is a verdict, a merge, a release or a backup,
# derived from the directories and never typed — and then the asserted drives.
gated_population() {
    local f
    for f in scripts/*.sh deploy/*.sh .githooks/* githooks/*; do
        [ -f "$f" ] || continue
        printf '%s\n' "$f"
    done
    asserted_drives
}

# The population that is printed and not asserted — see blind spot 2. Every
# drive in the directories EXCEPT the asserted ones, which the census reads.
drive_population() {
    local f asserted
    asserted="$(asserted_drives)"
    for f in scripts/tests/test_*.sh deploy/tests/test_*.sh; do
        [ -f "$f" ] || continue
        case $'\n'"${asserted}"$'\n' in
        *$'\n'"${f}"$'\n'*) continue ;;
        esac
        printf '%s\n' "$f"
    done
}

# A census hit is DISPOSED OF if it is a comment, if it carries the valve with a
# reason, or if the producer is braced with its own `|| true`.
hit_is_disposed() {
    local text="$1"
    case "$text" in
    *'pipefail-ok:'*) return 0 ;;
    esac
    # Leading whitespace stripped, then a comment line is prose about the class,
    # not an instance of it — `scripts/gate_ledger.sh` argues the class in a
    # comment that names the shape.
    local stripped="${text#"${text%%[![:space:]]*}"}"
    case "$stripped" in
    '#'*) return 0 ;;
    esac
    # `{ producer || true; } | reader` — and the brace must close DIRECTLY before
    # the reader's pipe. `{ grep … || true; } | sort -u | head -1` braces grep,
    # but the producer `head` orphans is `sort`, which is unbraced: that line
    # took SIGPIPE on a CI runner while this test read it as disposed.
    local braced_reader='\|\| true; \}[[:space:]]*\|[[:space:]]*(head|grep -m|awk[^|]*exit|tee([[:space:]]|$))'
    [[ "$text" =~ $braced_reader ]] && return 0
    return 1
}

# --- the class ---------------------------------------------------------------

case_the_old_form_discards_the_match_under_pipefail() {
    CURRENT=case_the_old_form_discards_the_match_under_pipefail
    local out rc=0
    out="$(
        set +e
        set -o pipefail
        padded_producer | head -1
        exit $?
    )" || rc=$?
    if [ "$out" != "MATCH" ]; then
        bad "the reader did not even get the line it wanted — got '${out}'"
        return
    fi
    if [ "$rc" = "0" ]; then
        bad "the padded producer did not fail the pipeline; this platform's pipe buffer
             may be larger than ${pad_bytes} bytes, and the class cannot be shown"
        return
    fi
    ok "value 'MATCH' read, pipeline status ${rc} — the line every caller trusts, with a status that kills the script"
}

case_the_rewritten_form_keeps_the_match() {
    CURRENT=case_the_rewritten_form_keeps_the_match
    local out rc=0
    out="$(
        set +e
        set -o pipefail
        { padded_producer || true; } | head -1
        exit $?
    )" || rc=$?
    if [ "$out" != "MATCH" ]; then
        bad "wanted 'MATCH', got '${out}'"
        return
    fi
    if [ "$rc" != "0" ]; then
        bad "wanted status 0, got ${rc}"
        return
    fi
    ok "'MATCH' at status 0 under the same padding that killed the old form"
}

case_the_whole_read_then_slice_form_keeps_the_match() {
    CURRENT=case_the_whole_read_then_slice_form_keeps_the_match
    local out rc=0
    out="$(
        set +e
        set -o pipefail
        local_whole="$(padded_producer)" || exit $?
        printf '%s' "${local_whole%%$'\n'*}"
        exit 0
    )" || rc=$?
    if [ "$out" != "MATCH" ]; then
        bad "wanted 'MATCH', got '${out:0:40}'"
        return
    fi
    if [ "$rc" != "0" ]; then
        bad "wanted status 0, got ${rc}"
        return
    fi
    ok "'MATCH' at status 0 with no pipe at all — the producer ran to completion"
}

case_an_eof_reader_keeps_the_producers_own_status() {
    CURRENT=case_an_eof_reader_keeps_the_producers_own_status
    # The third disposition: an EOF reader never closes the pipe early, so the
    # producer's status reaches pipefail intact — which is the POINT. A producer
    # that really failed still reds.
    local out rc=0
    out="$(
        set +e
        set -o pipefail
        padded_producer | sed -n '1p'
        exit $?
    )" || rc=$?
    if [ "$out" != "MATCH" ] || [ "$rc" != "0" ]; then
        bad "a padded producer into an EOF reader: wanted 'MATCH' at 0, got '${out:0:40}' at ${rc}"
        return
    fi
    rc=0
    out="$(
        set +e
        set -o pipefail
        { printf 'MATCH\n'; exit 3; } | sed -n '1p'
        exit $?
    )" || rc=$?
    if [ "$rc" != "3" ]; then
        bad "a genuinely failing producer into an EOF reader: wanted status 3, got ${rc}"
        return
    fi
    ok "EOF reader: padded producer is 0, a failing producer is still 3 — the status is not swallowed"
}

case_a_tee_at_a_pipeline_tail_takes_the_status_over() {
    CURRENT=case_a_tee_at_a_pipeline_tail_takes_the_status_over
    # THE FOURTH SHAPE, AND IT IS NOT THE EARLY EXIT. `tee` reads to EOF, so it
    # orphans nothing and no padding is used here. What it does is stand
    # BETWEEN a producer and the status its caller acts on, and it costs in two
    # opposite directions depending on one shell option that the line itself
    # does not set — which is the whole argument for a rule rather than a
    # judgment at each site.
    local sink="${WORK}/tee-sink.log" rc=0 out

    # (1) WITHOUT pipefail: the producer's failure is the reader's success.
    rc=0
    out="$(
        set +e
        set +o pipefail
        { printf 'MATCH\n'; exit 3; } | tee "$sink" >/dev/null
        exit $?
    )" || rc=$?
    if [ "$rc" != "0" ]; then
        bad "without pipefail a tee'd producer exiting 3 should report 0; got ${rc}"
        return
    fi
    ok "without pipefail: a producer exiting 3 reaches its caller as 0 — the status is the reader's"

    # (2) WITH pipefail, the loss runs the other way: the READER's failure is
    # now the pipeline's, so a green producer is reported as a red and the
    # caller blames the subject. An unwritable sink is the cheapest way to make
    # `tee` fail, and it is built here rather than found.
    local blocked="${WORK}/no-such-dir/sink.log"
    rc=0
    out="$(
        set +e
        set -o pipefail
        { printf 'MATCH\n'; exit 0; } | tee "$blocked" >/dev/null 2>&1
        exit $?
    )" || rc=$?
    if [ "$rc" = "0" ]; then
        bad "under pipefail a tee that cannot write its sink should fail the pipeline; got 0, so this half of the shape is not reproducing on this platform"
        return
    fi
    ok "with pipefail: a producer exiting 0 into a tee that cannot write reports ${rc} — the red names the subject and the fault is the reader's"

    # (3) THE FIX, the one the gate house-rules leg and `setup.sh` now ship:
    # redirect, read `$?`, then print. Both directions gone, same transcript,
    # same file. A SUBSHELL and not a brace group for the producer: `exit` in
    # a brace group is this command substitution own exit, so the `cat` would
    # never run and the case would read an empty capture — the two pipelines
    # above get a subshell for free, because each segment of a pipeline is one.
    rc=0
    out="$(
        set +e
        set -o pipefail
        ( printf 'MATCH\n'; exit 3 ) >"$sink" 2>&1
        shipped_rc=$?
        cat "$sink"
        exit $shipped_rc
    )" || rc=$?
    if [ "$out" != "MATCH" ] || [ "$rc" != "3" ]; then
        bad "redirect-then-cat: wanted 'MATCH' at status 3, got '${out}' at ${rc}"
        return
    fi
    ok "redirect-then-cat: the same output and the producer's own 3, with no second process in the status"
}

# --- the census --------------------------------------------------------------

case_no_early_exit_reader_follows_a_pipe_under_pipefail() {
    CURRENT=case_no_early_exit_reader_follows_a_pipe_under_pipefail
    local files hits=0 bad_hits=0 line file lineno text
    files="$(gated_population)"
    if [ -z "$files" ]; then
        bad "the gated population is empty — the census would pass by looking at nothing"
        return
    fi
    while IFS= read -r file; do
        [ -n "$file" ] || continue
        [ -r "$file" ] || {
            bad "the asserted population names ${file} and it is not a readable file — the census would pass by not looking"
            return
        }
        # `grep -n` into an EOF reader: the whole file's hits are wanted.
        while IFS= read -r line; do
            [ -n "$line" ] || continue
            lineno="${line%%:*}"
            text="${line#*:}"
            hits=$((hits + 1))
            if hit_is_disposed "$text"; then
                echo "           disposed  ${file}:${lineno}"
                continue
            fi
            bad_hits=$((bad_hits + 1))
            echo "           EARLY EXIT ${file}:${lineno}  ${text}"
        done < <(grep -nE "$CENSUS_RE" "$file" || true)
    done <<<"$files"
    if [ "$bad_hits" -gt 0 ]; then
        bad "${bad_hits} of ${hits} census hit(s) in the gated population still put an early-exit
             reader after a pipe. Rewrite as { producer || true; } | reader, read the whole
             and slice it, or use an EOF reader — and if the line is genuinely safe say so
             with the valve and its reason on the line."
        return
    fi
    ok "${hits} census hit(s) across the gated population, every one disposed of"
}

case_the_undriven_population_is_printed_rather_than_silent() {
    CURRENT=case_the_undriven_population_is_printed_rather_than_silent
    local files file line named=0 missing=0
    files="$(drive_population)"
    if [ -z "$files" ]; then
        bad "no drives found at all — the notice would be silent for the wrong reason"
        return
    fi
    echo "           THE DECLARED GAP. These are the same class in files this census does"
    echo "           NOT assert to zero (blind spot 2): a drive that dies of it fails loudly"
    echo "           and is re-run, and several of these files belong to open lanes."
    while IFS= read -r file; do
        [ -n "$file" ] || continue
        [ -r "$file" ] || { missing=$((missing + 1)); continue; }
        while IFS= read -r line; do
            [ -n "$line" ] || continue
            named=$((named + 1))
            echo "           gap  ${file}:${line%%:*}"
        done < <(grep -nE "$CENSUS_RE" "$file" || true)
    done <<<"$files"
    if [ "$missing" -gt 0 ]; then
        bad "${missing} file(s) the derivation named could not be read — the notice is derived from the directory and must be able to read what it names"
        return
    fi
    ok "${named} site(s) named in the undriven population, derived from the directory and printed"
}

# --- the shipped lines, run against a padded input ---------------------------

# Read ONE line out of a script by an anchor, so the case measures the line the
# gate ships rather than a copy of it that can drift.
shipped_line() {
    local anchor="$1" found
    found="$(grep -nE "$anchor" "${ROOT}/scripts/check.sh" || true)"
    found="${found%%$'\n'*}"
    [ -n "$found" ] || return 1
    printf '%s' "${found#*:}"
}

case_the_pass_two_summary_is_capped_and_complete() {
    CURRENT=case_the_pass_two_summary_is_capped_and_complete
    local line plant rc=0 got count
    line="$(shipped_line '^[[:space:]]*summary=')" || {
        bad "no 'summary=' line in scripts/check.sh — the pass-2 classifier's summary is gone"
        return
    }
    plant="${WORK}/pass2.log"
    # Well past a 64 KiB pipe buffer: 5,000 FAILED lines of ~75 bytes each.
    local i=0
    {
        while [ "$i" -lt 5000 ]; do
            printf 'FAILED apps/example/tests/test_padding.py::test_case_%06d - AssertionError\n' "$i"
            i=$((i + 1))
        done
    } >"$plant"
    got="$(
        exec 2>"${WORK}/pass2.err"
        set +e
        set -o pipefail
        out="$plant"
        eval "$line"
        shipped_rc=$?
        printf '%s' "$summary"
        exit $shipped_rc
    )" || rc=$?
    if [ "$rc" != "0" ]; then
        bad "the shipped summary line died with status ${rc} on a padded log — this is the class, in the gate"
        return
    fi
    count="$(printf '%s\n' "$got" | grep -c 'test_case_' || true)"
    if [ "$count" != "20" ]; then
        bad "wanted 20 summary lines, got ${count}"
        return
    fi
    case "$got" in
    *test_case_000000*) ;;
    *)
        bad "the first failure is missing from the summary"
        return
        ;;
    esac
    ok "the shipped line capped 5,000 failures at 20, kept the first, and exited 0"
}

case_the_scope_banner_reads_the_first_counts_file_under_a_padded_list() {
    CURRENT=case_the_scope_banner_reads_the_first_counts_file_under_a_padded_list
    local line rc=0 got listing i=0
    line="$(shipped_line '^[[:space:]]*LOOP_COUNT_FIRST=')" || {
        bad "no 'LOOP_COUNT_FIRST=' line in scripts/check.sh — the counts-file comparison is gone"
        return
    }
    # A counts directory listing well past the pipe buffer: 2,000 paths of
    # ~70 bytes. A wide `-n` with long app paths reaches this honestly.
    local nth=""
    listing="${WORK}/counts/counts-worker-000000-collected-items-and-nodeids.txt"
    while [ "$i" -lt 2000 ]; do
        printf -v nth '%06d' "$i"
        listing="${listing}"$'\n'"${WORK}/counts/counts-worker-${nth}-collected-items-and-nodeids.txt"
        i=$((i + 1))
    done
    got="$(
        exec 2>"${WORK}/counts.err"
        set +e
        set -o pipefail
        LOOP_COUNT_FILES="$listing"
        eval "$line"
        shipped_rc=$?
        printf '%s' "$LOOP_COUNT_FIRST"
        exit $shipped_rc
    )" || rc=$?
    if [ "$rc" != "0" ]; then
        bad "the shipped LOOP_COUNT_FIRST line died with status ${rc} on a padded listing — this is the class, in the gate"
        return
    fi
    if [ "$got" != "${WORK}/counts/counts-worker-000000-collected-items-and-nodeids.txt" ]; then
        bad "wanted the first path, got '${got:0:70}'"
        return
    fi
    ok "the shipped line took the first of 2,001 paths and exited 0"
}

# --- run ----------------------------------------------------------------------

case_the_old_form_discards_the_match_under_pipefail
case_the_rewritten_form_keeps_the_match
case_the_whole_read_then_slice_form_keeps_the_match
case_an_eof_reader_keeps_the_producers_own_status
case_a_tee_at_a_pipeline_tail_takes_the_status_over
case_no_early_exit_reader_follows_a_pipe_under_pipefail
case_the_undriven_population_is_printed_rather_than_silent
case_the_pass_two_summary_is_capped_and_complete
case_the_scope_banner_reads_the_first_counts_file_under_a_padded_list

echo "test_pipefail_readers: ${PASSED} passed · ${FAILED} failed"
drive_finished
if [ "$FAILED" -gt 0 ]; then
    echo "!! a pipeline whose reader leaves early is green on every small input and" >&2
    echo "   fatal on the first big one. The value is right and the status kills the" >&2
    echo "   script, so nothing about it shows up until it matters." >&2
    exit 1
fi
exit 0
