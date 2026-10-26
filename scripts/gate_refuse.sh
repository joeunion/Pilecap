#!/usr/bin/env bash
# The one refusal seam: a callee's cause, carried to the banner that names it.
#
# THE DEFECT IT ANSWERS. A dozen banners in `scripts/check.sh` end in
# `— see above.` and nothing else. That sentence is a pointer, and it is only
# worth anything to a reader who still HAS the "above" — a terminal that has not
# scrolled, a log nobody truncated, a leg whose callee actually printed. In a
# transcript that reaches anyone else — a report, a paste, a harness tail, a
# verifier reading the last forty lines of a killed run — "see above" names a
# cause it has not proven, which is the one thing the enforcement grammar here
# says a message may never do. Measured by the consumer's builders as the single
# most expensive red to read (DX-LEAD, "refusals that hid the cause").
#
# THE SHAPE. One global, `GATE_LAST_REFUSAL`, holding the FIRST `!!` line of the
# most recent refusal, set by the `gate_refuse` helper every sourced callee uses in
# place of its own first `echo "!! …" >&2`. The text it prints is byte-identical
# to what it printed before — drives assert those sentences and a reword would
# break them silently — and the only new thing is that the line is also
# REMEMBERED. Each banner then prints `cause: ${GATE_LAST_REFUSAL}` as its second
# line, so the refusal says why where the reader is standing.
#
# WHY THE FIRST `!!` LINE AND NOT THE WHOLE BLOCK. A refusal here is a headline
# plus a paragraph of remedy; the headline is the cause and the paragraph is the
# fix. Carrying the paragraph would put the whole refusal on the screen twice.
# The declared cost: a callee whose real cause is on its third line still says
# its first (build-contract.md, lane B's blind spots).
#
# THE SUBSHELL RULE, AND IT IS THE WHOLE OF REVIEW F7. A callee invoked under
# `$(...)` runs in a SUBSHELL: it can print, and every assignment it makes —
# this global included — dies with the subshell. So a substitution's caller
# CANNOT read the cause out of the global; it must capture the child's stderr to
# a FILE (`2>"$err"`, never into the substitution, which would fold the refusal
# into the value being computed) and hand that file to `gate_refuse_from_file`, which
# replays it where it would have appeared and takes the first `!!` line as the
# cause. `loop_scope__closure` (quality/djb/scope.py) is the worked example: its
# unknown-label refusal is written by an embedded Python reader that cannot call
# a shell function at all, so the file IS the only channel.
#
# AND A BANNER WITH NO CAUSE IS A REFUSAL, NOT A BLANK. `gate_cause` fills an
# empty global with a sentence saying so, because `cause:` followed by nothing
# reads as "there was no cause" rather than "nobody recorded one" — and the
# second is broken enforcement. The population that legitimately reaches it
# today is the banners whose callee is a separate PROCESS (a python census, a
# `./scripts/sweep.sh` assertion) or a library outside this seam: they are named
# in docs/product/build-contract.md rather than left for a reader to discover.
#
# A LIBRARY, NOT AN INSTRUMENT: sourced, never executed, mode 644 like every
# other `scripts/*.sh` library here, and it starts nothing, forks nothing and
# reads no file it was not handed.
#
# ---------------------------------------------------------------------------
# AND ONE DIGEST, FOR THE SAME REASON THE CAUSE LIVES HERE: the gate's two
# sourced libraries both need a SHA-256 and this is the one file both of them
# already source. `sha256_of` is below, with the machine argument in its own
# header.

#: Set once, and read by every library below this one to decide whether it still
#: needs to source this file. Re-sourcing is harmless; sourcing it twice per leg
#: is noise.
GATE_REFUSE_SOURCED=1

#: The first `!!` line of the most recent refusal, without its `!! ` leader.
#: Empty means nobody has refused yet, or the last refusal happened in a
#: subshell and its caller did not carry it out (the F7 rule above).
: "${GATE_LAST_REFUSAL:=}"

#: Set by `gate_cause` when it had to invent the cause, cleared when it did not.
#: A reader wanting to count the banners whose callee records nothing has this
#: rather than a string comparison against a sentence that may be reworded.
: "${GATE_CAUSE_UNRECORDED:=}"

#: The sentence `gate_cause` prints when the callee recorded nothing. Held as a
#: constant so the drives assert the shipped text rather than a copy of it.
GATE_CAUSE_NONE='(the callee set none — a refusal that could not say why is broken enforcement)'

# gate_refuse <text...> — print a refusal's FIRST line and remember it.
#
# Prints `!! <text>` on stderr, exactly as the `echo` it replaces did, and
# records `<text>` as this run's last cause. The remaining lines of a refusal
# stay ordinary `echo`s: they are the remedy, not the cause.
gate_refuse() {
    GATE_LAST_REFUSAL="$*"
    echo "!! $*" >&2
    return 0
}

# ---------------------------------------------------------------------------
# THE THREE WORDS, AND THE EXIT IS THE WORD.
#
#   ok              exit 0 — looked, and it is as claimed     (`gate_ok`)
#   RED             exit 1 — looked, and it is wrong          (`gate_finding`)
#   COULD NOT LOOK  exit 2 — never got as far as judging      (`gate_die`)
#
# A `!!` banner is the third word's and only the third's: every `!!` this tree
# prints is followed by exit 2, and a script that LOOKED and found something
# wrong says RED and exits 1. That is CLAUDE.md's "2 outranks a pass" made a
# shape — a leg that wanted exit 2 to mean "finding" gets no valve; it exits 1.
# `quality/tests/test_refusal_seam.py` reads every `!!` under `scripts/` and
# `deploy/` and names the one that is not.
#
# THE TRAILER is the per-script sentence that says what was NOT done ("Nothing
# was merged and the working tree was not touched.") — an argument, because the
# drives assert each script's own, and a script names it once in a variable
# rather than typing it at every call. Empty is legal: a refusal whose headline
# already says it.

#: Set by `gate_die` immediately before it exits, so an EXIT trap can tell a
#: refusal the script authored from a shell that died under it (pm_fold's guard
#: reads it). Never set by anything else.
: "${GATE_DIED:=}"

# gate_die <trailer> <headline> [<line>...] — refuse: could not look, exit 2.
#
# Prints the headline through `gate_refuse` (so it is this run's recorded cause),
# then each further line and then each line of the trailer indented three
# spaces, all on stderr, and exits 2. Never returns.
# road: could_not_look — `!!` is exit 2 and nothing else means it · example: quality/tests/test_refusal_seam.py::test_gate_die_is_exit_2_with_its_trailer
gate_die() {
    local trailer=${1-}
    [ "$#" -gt 0 ] && shift
    [ "$#" -gt 0 ] || set -- "(gate_die was handed no headline — a refusal that could not say why is broken enforcement)"
    gate_refuse "$1"
    shift
    gate__indented "$@"
    [ -z "$trailer" ] || gate__indented "$trailer"
    GATE_DIED=1
    exit 2
}

# gate_finding <headline> [<line>...] — the one exit-1 word: looked, and it is wrong.
#
# Prints `RED: <headline>` and each further line indented, on stderr, and exits
# 1. Never `!!`: that leader belongs to exit 2 alone.
gate_finding() {
    [ "$#" -gt 0 ] || set -- "(gate_finding was handed no headline)"
    echo "RED: $1" >&2
    shift
    gate__indented "$@"
    exit 1
}

# gate__indented <text>... — every line of every argument, three spaces in, on
# stderr: the body of a refusal or a finding. Private to the two above.
gate__indented() {
    local text line
    for text in "$@"; do
        while IFS= read -r line; do
            printf '   %s\n' "$line" >&2
        done <<<"$text"
    done
    return 0
}

# gate_ok <text...> — the exit-0 word, printed; returns 0 and exits nothing.
gate_ok() {
    echo "ok: $*"
    return 0
}

# refuse_if_piped <name> [<why>...] — exit 2 when stdout is a pipe.
#
# A pipe replaces the caller's exit status with the filter's, and in every
# script that calls this the exit status IS the verdict. A TTY or a file
# redirect keeps it. CI is exempt, in this one place, because GitHub Actions
# captures every step's stdout through a pipe. Called at the top level of the
# script, so `/dev/fd/1` is the script's own stdout.
# road: pipe_guard — a script whose exit status is the verdict refuses a piped stdout, exit 2 · example: quality/tests/test_refusal_seam.py::test_a_piped_stdout_is_refused_with_the_one_sentence
refuse_if_piped() {
    local name=${1:-this script}
    [ "$#" -gt 0 ] && shift
    if [ -z "${CI:-}" ] && { [ -p /dev/fd/1 ] || [ -p /dev/stdout ]; }; then
        gate_die "" "${name} refuses pipes — run it bare or redirect to a file." "The exit status is the verdict, and a filter replaces it." "$@"
    fi
    return 0
}

# gate_refuse_reset — forget the last cause.
#
# Called by a caller immediately BEFORE the guarded call, so that a banner can
# never print a cause belonging to some earlier, already-handled refusal. Every
# refusal in this tree is followed by its caller exiting, so a stale cause is
# not reachable today; this is what keeps that true when it stops being.
gate_refuse_reset() {
    GATE_LAST_REFUSAL=""
    GATE_CAUSE_UNRECORDED=""
    return 0
}

# gate_refuse_from_file <path> — the F7 form: carry a SUBSHELL callee's cause out.
#
# Replays the captured stderr where it would have been printed (so "see above"
# still has its above), then takes the first `!!` line as the cause — falling
# back to the first non-blank line for a callee that refused without the
# leader. An unreadable or empty capture leaves the cause EMPTY on purpose:
# `gate_cause` then says nobody recorded one, which is true.
gate_refuse_from_file() {
    local path=${1:-} line=""
    if [ -n "$path" ] && [ -s "$path" ]; then
        cat "$path" >&2
        line=$(sed -n '/^[[:space:]]*!!/{s/^[[:space:]]*!![[:space:]]*//;p;q;}' "$path")
        if [ -z "$line" ]; then
            line=$(sed -n '/[^[:space:]]/{s/^[[:space:]]*//;p;q;}' "$path")
        fi
    fi
    GATE_LAST_REFUSAL="$line"
    return 0
}

# gate_capture <varname> <command> [args...] — the F7 form, as one call.
#
# Runs the callee with its stdout captured into the named variable and its stderr
# captured to a file, replays that file where it would have appeared, and on a
# non-zero status takes its first `!!` line as the cause. Same contract as
# writing `out=$(callee 2>"$err")` by hand, and the reason to have it as a
# function is that the hand form is four lines with a temp file to clean up and
# an easy way to fold stderr into the value by mistake.
#
# The callee's exit status is this function's. A machine with no writable temp
# directory loses the cause and keeps the status — `gate_cause` then says nobody
# recorded one, which is exactly what happened.
gate_capture() {
    local __var=$1 __err="" __out="" __rc=0
    shift
    __err=$(mktemp "${TMPDIR:-/tmp}/djb-gate-capture.XXXXXX") || __err=""
    if [ -n "$__err" ]; then
        __out=$("$@" 2>"$__err") || __rc=$?
        if [ "$__rc" != "0" ]; then
            gate_refuse_from_file "$__err"
        elif [ -s "$__err" ]; then
            cat "$__err" >&2
        fi
        rm -f "$__err"
    else
        __out=$("$@") || __rc=$?
    fi
    printf -v "$__var" '%s' "$__out"
    return "$__rc"
}

# gate_tool_said <file> — the tool's own last lines, on stderr, under a refusal.
#
# The shell twin of `quality/could_not_look.py::tool_said`, pinned alike by
# `quality/tests/test_refusal_seam.py::test_the_tool_said_twins_say_it_alike`:
# the last five non-blank lines of what the tool printed, each
# `   the tool said: <line>` and cut at 300 characters; nothing for a file that
# is empty or absent.
gate_tool_said() {
    [ -s "${1:-}" ] || return 0
    grep -v '^[[:space:]]*$' "$1" | tail -n 5 | cut -c1-300 | sed 's/^/   the tool said: /' >&2
}

# gate_cause — make sure there IS a cause to print, and say when there was not.
#
# Called immediately before a banner prints `cause: ${GATE_LAST_REFUSAL}`. If
# the callee recorded nothing, the global is filled with `$GATE_CAUSE_NONE` and
# `GATE_CAUSE_UNRECORDED` is set. The banner's own branch exits 2 either way —
# every site that prints this line is a could-not-look — so this function
# changes what the reader is told and never what the gate decides.
gate_cause() {
    GATE_CAUSE_UNRECORDED=""
    if [ -z "${GATE_LAST_REFUSAL:-}" ]; then
        GATE_LAST_REFUSAL="$GATE_CAUSE_NONE"
        GATE_CAUSE_UNRECORDED=1
    fi
    return 0
}

# ---------------------------------------------------------------------------
# THE DIGEST, AND THE MACHINE IS THE ARGUMENT.
#
# sha256_of [<path>] — the SHA-256 of a file (or of stdin, with no argument) as
# 64 bare hex digits on stdout, and nothing else. Exit 0 derived · 1 could not
# derive, which every caller here turns into could-not-look and never into an
# empty answer.
#
# WHY IT EXISTS. `shasum -a 256` is a Perl script that ships with macOS and is
# NOT on a minimal Linux, which spells the same digest `sha256sum`. Every site
# in this family spelled `shasum -a 256` because every site was written on a
# Mac. The first off-box gate run measured the cost: on Amazon Linux 2023
# `quality/djb/scope.py` printed `shasum: command not found`, the loop ledger's
# distribution census derived nothing, and the run's verdict cell read
# `miss(no-ledger)` — a gate that could not key its own verdict, on a machine
# where nothing was wrong except the name of a program.
#
# NO CACHE, DELIBERATELY. `command -v` is a shell builtin over an already-built
# hash table, and the sites here are counted in single digits per run; against
# that, a cached tool name is a lie the moment anything moves PATH — which is
# exactly what the drives that prove this branch do, in-process.
#
# THE PIPELINE'S STATUS IS THE LAST COMMAND'S, WHICH IS WHY THE SHAPE IS
# CHECKED. `shasum … | awk '{print $1}'` exits 0 with an EMPTY answer when
# `shasum` was never found, so a `||` fallback written across such a pipeline is
# dead code that nobody notices — `scripts/publish.sh` carried exactly that, and
# on Linux it would have named its export directory with an empty hash rather
# than fall back. So the answer is validated as 64 hex digits before it is
# returned, and an unvalidatable one is exit 1.
#
# Not routed through here: `scripts/db.sh` keeps its one ladder (`db_digest_tool`), sourced where this seam is not
# (db.sh's header); `deploy/provision.sh` reaches it through db.sh.
sha256_of() {
    local digest=""
    case "$#" in
    0) digest=$(sha256_of__stdin) || return 1 ;;
    1)
        [ -r "$1" ] || return 1
        digest=$(sha256_of__stdin <"$1") || return 1
        ;;
    *) return 1 ;;
    esac
    # 64 lower-case hex, or it is not a digest and this did not answer.
    case "$digest" in
    '' | *[!0-9a-f]*) return 1 ;;
    esac
    [ "${#digest}" = "64" ] || return 1
    printf '%s\n' "$digest"
    return 0
}

# sha256_of__stdin — the tool, resolved per call, reading stdin. Not called
# directly by anything but `sha256_of`, which owns the validation.
sha256_of__stdin() {
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 | awk '{print $1}'
    elif command -v sha256sum >/dev/null 2>&1; then
        sha256sum | awk '{print $1}'
    else
        return 1
    fi
}

# ---------------------------------------------------------------------------
# THE INTERPRETER, AND THE MACHINE IS AGAIN THE ARGUMENT.
#
# checkout_python [<checkout root>] — the path to the interpreter THIS checkout
# owns, on stdout. Exit 0 found · 1 there is none, which every caller turns into
# a named could-not-look and never into a run on whatever `python3` happened to
# be first on PATH. The root defaults to `.` (every gate leg runs from the
# checkout root, and `check.sh` refuses elsewhere).
#
# WHY IT EXISTS. `python3` off PATH is SOME OTHER environment's Python. On this
# Mac it is 3.12 or 3.13 and the difference never showed; on Amazon Linux 2023
# it is the system's 3.9, and the first off-box gate run died there —
# `scripts/queue_index.py`, which this repository writes and pins at 3.12,
# reached `zip(expected, got, strict=True)` and got `TypeError: zip() takes no
# keyword arguments` while `.venv/bin/python` two directories away was 3.12.14.
# The leg went red on the interpreter and said `the queue index is not what
# queue_index.py generates`, which is the wrong finding about the wrong file.
#
# `uv run python` IS NOT THE FALLBACK, and that is the settled answer here
# rather than a new one: `loop_scope__python` (quality/djb/scope.py) and
# `loop_env_reads` (scripts/gate_ledger.sh) both name the venv and refuse
# without it, because `uv run` re-resolves on paths that must stay cheap and in
# a checkout with no venv it would SYNC one — minutes of surprise side effect
# inside a leg that reads a markdown table. An unprovisioned checkout is
# could-not-look, and it costs nothing real: every other leg of this gate runs
# under `uv run`, so a checkout with no venv cannot run the suite either and
# this is never the first thing its owner meets.
#
# THE RULE THIS SERVES, stated so the census that enforces it can be read: a
# PYTHON FILE THIS REPOSITORY SHIPS runs on this interpreter. An inline
# `python3 -c` or heredoc program — the millisecond clocks, a `json.load`, a
# `datetime` arithmetic — is stdlib on any Python 3 and stays as it is, guarded
# by its own `command -v python3` where its absence would matter.
checkout_python() {
    local root="${1:-.}" py
    py="${root%/}/.venv/bin/python"
    [ -x "$py" ] || return 1
    printf '%s\n' "$py"
    return 0
}

# ---------------------------------------------------------------------------
# THE ONE CLOCK. clock_ms — milliseconds since the epoch on the best clock this host has; clock_fmt <ms> — `<n.nn>s`.
# GATE_CLOCK names the rung of the ladder, chosen once at source (bash 5 · GNU date · perl · python3 · whole seconds);
# `seconds` is whole-second resolution, which every caller's footer declares.
if [ -z "${GATE_CLOCK:-}" ]; then
    if [ -n "${EPOCHREALTIME:-}" ]; then
        GATE_CLOCK=bash5
    elif case "$(date +%s%3N 2>/dev/null || echo x)" in '' | *[!0-9]*) false ;; *) true ;; esac; then
        GATE_CLOCK=gnudate
    elif command -v perl >/dev/null 2>&1; then
        GATE_CLOCK=perl
    elif command -v python3 >/dev/null 2>&1; then
        GATE_CLOCK=python3
    else
        GATE_CLOCK=seconds
    fi
fi
clock_ms() {
    case "$GATE_CLOCK" in
    bash5)
        local us=${EPOCHREALTIME/./}
        printf '%s' "${us%???}"
        ;;
    gnudate) date +%s%3N ;;
    perl) perl -MTime::HiRes=time -e 'printf "%.0f", time()*1000' ;;
    python3) python3 -c 'import time; print(int(time.time()*1000))' ;;
    *) printf '%s000' "$(date +%s)" ;;
    esac
}
# clock_s — whole seconds since the epoch, for arithmetic on ages and deadlines.
clock_s() {
    date +%s
}
clock_fmt() {
    awk -v ms="$1" 'BEGIN { printf "%.2fs", ms / 1000 }'
}

# ---------------------------------------------------------------------------
# THE ONE READING OF "WHAT CHANGED". tree_dirt [<dir>] [<git status arg>…] — `git status --porcelain` of the checkout
# at <dir> (default `.`), one entry per line, empty when clean; `-uall` and a pathspec are the callers' own questions.
tree_dirt() {
    local dir="${1:-.}"
    [ "$#" -eq 0 ] || shift
    git -C "$dir" status --porcelain "$@"
}
# tree_is_dirty [<dir>] — exit 0 when the checkout carries a change git sees, 1 when it is clean.
tree_is_dirty() {
    [ -n "$(tree_dirt "${1:-.}")" ]
}
# changed_between <a> <b> [<pathspec>…] — the paths that differ in the cwd's repository, a rename as both its paths;
# <b> `-` is the working tree. `--diff-filter=U` and `secrets_scan_changed_files`' `-z --diff-filter=d` are other questions.
changed_between() {
    local a=$1 b=$2
    shift 2
    if [ "$b" = "-" ]; then
        git diff --name-only --no-renames "$a" -- "$@"
    else
        git diff --name-only --no-renames "$a" "$b" -- "$@"
    fi
}
