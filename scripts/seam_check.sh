#!/usr/bin/env bash
# THIS FILE IS EXECUTED, AND IT IS BASH — not POSIX sh, and not zsh. The
# shebang above is honoured by `./this`; `sh this` and `zsh this` IGNORE it,
# and neither of them fails where the mistake was made. Measured on this tree:
#
#   zsh scripts/queue_cited.sh   exit 2 blaming the TREE ("this is not a
#                                checkout root") for zsh's word-splitting
#   zsh scripts/kill_mine.sh     an ordinary-looking census of nothing
#   sh  scripts/sweep.sh         "lifecycle.sh: line 152: syntax error"
#
# A wrong shell here does not crash. It ANSWERS, and the answer looks like the
# tree's fault.
#
# TWO TESTS, because on macOS `/bin/sh` IS bash: BASH_VERSION is set under
# `sh x.sh` and only POSIX MODE tells the two apart (SHELLOPTS carries
# `posix`). On Linux `/bin/sh` is dash and the first test is the one that
# fires. Neither test alone covers both machines.
#
# A SOURCED library must never carry this. There the interpreter is the
# caller's ON PURPOSE and an `exit` would kill the caller's shell — the
# argument is scripts/db.sh's, at scripts/db.sh:50-57, and it is why db.sh is
# the one executable in this tree deliberately without a belt.
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
# The SEAM PRE-FLIGHT. Verify a dispatch brief's cross-app callables
# EXIST, in the baseline tree, with the parameters the brief quotes — before an
# agent is dispatched against them.
#
#   ./scripts/seam_check.sh 'apps.files.storage:delete_object(*, tenant, key)'
#   ./scripts/seam_check.sh --claims docs/scratch/f2b.claims --verbose
#   ./scripts/seam_check.sh --root /path/to/baseline/checkout 'apps.x.y:z()'
#
# Exit: 0 every claim proven · 1 a claim is FALSE · 2 could not look.
# 2 outranks a pass, everywhere in this repository and here.
#
# ---------------------------------------------------------------------------
# WHY IT EXISTS. A rung was once dispatched against a brief naming
# four `apps/files` seams that the baseline tree did not have in the shape the
# brief claimed. A builder verified all four, held, and the rung sat ~3h
# serialized behind a re-dispatch. Every one was knowable from the baseline tree AT BRIEF
# TIME. This is one second of that knowledge, spent before the dispatch instead
# of three hours after it.
#
# THE PM REFUSES ITSELF THE DISPATCH WITHOUT IT: a development brief naming
# cross-app callables carries this check's pasted output. That is a standing
# rule in `.claude/skills/product-manager/references/dispatch-briefs.md`, NOT a
# gate leg — the gate measures the tree, and a brief is not in the tree
# (cycle V1's plan, "the velocity cycle", lines 242-243).
#
# WHAT IT IS NOT. It is not a grep with extra steps. `scripts/seam_check.py`'s
# header argues the import-not-grep line in full; the short form is that a grep
# answers a question about TEXT and goes green on a name with the WRONG
# SIGNATURE, which is precisely one of the four gaps that held up an earlier dispatch.
#
# WHAT IT CANNOT SEE, in one line so a pasted run carries it: existence and the
# parameter NAMES a fragment lists, and nothing else — no behaviour, no
# semantics, no types, no order, no defaults, and no opinion about whether the
# seam is the RIGHT one. The footer of every green run says so again.
# ---------------------------------------------------------------------------

set -euo pipefail

SELF_DIR=$(cd "$(dirname "$0")" && pwd)

usage() {
    cat <<'USAGE'
usage: seam_check.sh [--root DIR] [--settings MODULE] [--claims FILE] [--verbose] [CLAIM ...]

  CLAIM         module.path:callable(fragment)   — the fragment may be empty
                module.path:Class.method(fragment)
  --claims FILE one claim per line; `#` starts a comment; `-` reads stdin
  --root DIR    the checkout to import FROM (default: this script's checkout)
  --settings M  DJANGO_SETTINGS_MODULE for claims under apps/ or config/
  --verbose     also print each PROVEN claim with the signature it resolved to

exit: 0 all proven · 1 a claim is false · 2 could not look (2 outranks a pass)
USAGE
}

die() {
    # Exit 2 everywhere in this repository is COULD NOT LOOK. Here that means
    # "no claim was judged" — and a run that judged nothing must never be
    # readable as a run that found nothing wrong.
    echo "!! $*" >&2
    echo "   Nothing was checked; no claim was judged." >&2
    exit 2
}

# --- it refuses to be piped --------------------------------------------------
# Detection and the CI exemption are check.sh's, deliberately identical
# (scripts/check.sh:63-66) and for the same reason: a pipe replaces this
# script's exit status with the filter's, and the exit status IS the verdict.
# A PM redirecting to a file to paste the output into a brief is the intended
# path and keeps it.
if [ -z "${CI:-}" ] && { [ -p /dev/fd/1 ] || [ -p /dev/stdout ]; }; then
    echo "!! seam_check refuses pipes — run it bare or redirect to a file." >&2
    echo "   The exit status is the verdict, and a filter replaces it." >&2
    exit 2
fi

ROOT=""
SETTINGS="config.settings.local"
VERBOSE=()
CLAIMS=()

read_claims_file() {
    local src=$1 line
    if [ "$src" = "-" ]; then
        src=/dev/stdin
    elif [ ! -r "$src" ]; then
        die "--claims $src: no such readable file."
    fi
    while IFS= read -r line || [ -n "$line" ]; do
        line=${line%%#*}
        # Trim, without `xargs` (which would eat the quotes a fragment needs).
        line=${line#"${line%%[![:space:]]*}"}
        line=${line%"${line##*[![:space:]]}"}
        [ -n "$line" ] || continue
        CLAIMS+=("$line")
    done <"$src"
}

while [ $# -gt 0 ]; do
    case "$1" in
    -h | --help)
        usage
        exit 0
        ;;
    --root)
        [ $# -ge 2 ] || die "--root needs a directory."
        ROOT=$2
        shift 2
        ;;
    --settings)
        [ $# -ge 2 ] || die "--settings needs a module path."
        SETTINGS=$2
        shift 2
        ;;
    --claims)
        [ $# -ge 2 ] || die "--claims needs a file (or - for stdin)."
        read_claims_file "$2"
        shift 2
        ;;
    --verbose | -v)
        VERBOSE=(--verbose)
        shift
        ;;
    -*)
        # Not a usage nit: a mistyped flag falling through to a silently
        # different run is enforcement misfiring, and that is an exit 2
        # (scripts/check.sh:71-76).
        echo "!! unknown option '$1'." >&2
        usage >&2
        exit 2
        ;;
    *)
        CLAIMS+=("$1")
        shift
        ;;
    esac
done

# --- the root, and its interpreter -------------------------------------------
if [ -z "$ROOT" ]; then
    ROOT=$(cd "$SELF_DIR/.." && pwd)
fi
[ -d "$ROOT" ] || die "--root $ROOT is not a directory."
ROOT=$(cd "$ROOT" && pwd)

# THE BASELINE CHECKOUT'S OWN VENV, and no fallback (the lead's line in the V1
# plan). Importing `apps.files.storage` under a DIFFERENT tree's interpreter
# would report that tree's dependencies, and a wrong answer with a real
# traceback is worse than no answer: an absent venv is COULD NOT LOOK.
PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
    die "$ROOT has no .venv/bin/python — the claims are imported through the BASELINE
   CHECKOUT'S OWN venv and through no other. Run \`uv sync\` (or ./scripts/setup.sh)
   in that checkout first."
fi
[ -r "$SELF_DIR/seam_check.py" ] || die "$SELF_DIR/seam_check.py is missing — that file is this
   script's body."

if [ ${#CLAIMS[@]} -eq 0 ]; then
    # A CHECK OF NOTHING IS NOT A PASS. An empty claim set is overwhelmingly a
    # mistyped invocation, and exiting 0 on it is how a brief comes to carry a
    # green that vouches for no claim at all.
    echo "!! no claims were given." >&2
    usage >&2
    exit 2
fi

cd "$ROOT"

# The settings modules refuse to load without a database name, by design
# (config/settings/base.py). `scripts/db.sh` is the house seam that derives
# this checkout's own name, and a DATABASE_NAME already in the environment wins
# over the derivation (db.sh rule 1) — both of which are true here unchanged.
#
# NOTHING IS CONNECTED TO. `django.setup()` populates the app registry and
# opens no connection, so the derived name only has to EXIST as a string; the
# database it names need not. That is why this check runs against a checkout
# whose database was never created, which is the state a brief-writing PM's
# baseline checkout is usually in.
if [ -r "$ROOT/scripts/db.sh" ]; then
    set +u
    # shellcheck disable=SC1091
    . "$ROOT/scripts/db.sh" || die "$ROOT/scripts/db.sh could not be sourced."
    set -u
fi

SEAM_CHECK_TREE=$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo "(not a git checkout)")
export SEAM_CHECK_TREE

# `exec`, so that nothing in this file can run after the verdict and nothing
# can mask the worker's exit status — pm_push.sh's property, for pm_push.sh's
# reason.
exec "$PY" "$SELF_DIR/seam_check.py" \
    --root "$ROOT" --settings "$SETTINGS" ${VERBOSE[@]+"${VERBOSE[@]}"} -- "${CLAIMS[@]}"
