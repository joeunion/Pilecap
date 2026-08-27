#!/usr/bin/env bash
# The `--loop` secret scan, narrowed to THE ACTIVE RUNG'S OWN CHANGES.
# Sourced by scripts/check.sh and by scripts/tests/test_secrets_scan.sh.
# BASH ONLY, for the reason gate_ledger.sh states: sourced into an interactive
# zsh, `local path` ties to $PATH and every helper dies silently.
#
# NOT EXECUTABLE, AND THAT IS THE DECLARATION, not an oversight: this file
# reports no verdict of its own. It hands a file list and one sentence to
# whoever sourced it, and the caller owns the exit status. It is a library
# beside gate_ledger.sh and db.sh, not an instrument beside them.
#
# ---------------------------------------------------------------------------
# WHY IT EXISTS. detect-secrets moved from the push-side supply-chain
# leg into `--loop`, so a builder meets a false positive in-rung — where the
# string is still in their head and `# pragma: allowlist secret` costs a
# minute — instead of at the end of a full gate with a merge already made and a
# PM waiting. That argument is untouched and stands. What was never measured
# was the price: the retro that ordered the move assumed ~1s, and a
# measurement found **~40s of wall clock on every single per-rung gate**.
# Measured in a worktree of 864 tracked files: 19s warm, 28s on a cold page
# cache, ~99% of it user CPU either way — so it is the scan itself, not `uv`
# start-up and not `xargs` batching, and it scales with the tree rather than
# with the change. That is why the PM's ruling — what this file implements —
# narrows the scope:
#
#   THE `--loop` COPY SCANS ONLY WHAT THE ACTIVE RUNG CHANGED. The full-tree scan
#   stays at push, in the supply-chain leg where it has always been. The
#   builder still meets their own false positive in-rung, because a false
#   positive a rung produces is by definition in a file that rung touched.
#
# WHAT THIS DELIBERATELY STOPS SEEING, said plainly so nobody mistakes a green
# `--loop` for a clean tree: a secret in a file the active rung did not touch.
# That is not a hole — it is the push-side scan's job, it still runs there over
# `git ls-files`, and a secret in an untouched file was not put there by this
# rung. The two scans are different questions and the banners say which is
# which.
#
# WHAT NEITHER SCAN SEES: an untracked, never-staged file. The push-side scan
# reads `git ls-files`, which is tracked files only, so a file nobody has added
# has never been in scope. Narrowing to `git diff` against the index and HEAD
# keeps the two in step on purpose — a `--loop` leg that reddened on a scratch
# file the push scan would never look at is a false-positive machine, which is
# the exact cost this whole change exists to remove.
# ---------------------------------------------------------------------------

# Set by secrets_scan_changed_files: one human sentence naming what was
# compared against what. The leg prints it. If this is empty after a call, the
# derivation did not get far enough to say — which is a could-not-look.
SECRETS_SCAN_BASIS=""

# secrets_scan_changed_files <outfile>
#
# Writes the NUL-separated paths the `--loop` scan should read into <outfile>
# and sets SECRETS_SCAN_BASIS to the sentence describing them. Operates on the
# repository containing the current working directory.
#
# Exit: 0 the set was derived (it may legitimately be EMPTY) · 2 git could not
# answer, which is could-not-look and outranks a pass everywhere in the gate.
secrets_scan_changed_files() {
    local out=$1
    local base head branch raw committed_n
    SECRETS_SCAN_BASIS=""
    : >"$out" || return 2

    if ! git rev-parse --git-dir >/dev/null 2>&1; then
        echo "!! the secret scan could not read a git directory here — the changed-file" >&2
        echo "   set is derived from git and from nothing else." >&2
        return 2
    fi

    raw=$(mktemp "${TMPDIR:-/tmp}/djb-secrets-raw.XXXXXX") || return 2

    head=$(git rev-parse -q --verify HEAD 2>/dev/null || true)
    if [ -z "$head" ]; then
        # An unborn HEAD: nothing is committed, so every staged file is new and
        # all of them are this change. `git diff HEAD` cannot be asked here at
        # all, so the honest answer is the index itself.
        git ls-files -z >>"$raw" 2>/dev/null || true
        # The pragma is this leg meeting its own false positive, in-rung, which
        # is the entire point: a shell variable whose NAME contains
        # "secret" holding one English sentence is not a credential.
        SECRETS_SCAN_BASIS="an unborn HEAD — nothing is committed yet, so every staged file is new and all of them were scanned" # pragma: allowlist secret
        secrets_scan__finish "$raw" "$out"
        return $?
    fi

    # THE MERGE-BASE IS TAKEN AGAINST THE LOCAL `refs/heads/main`, spelled in
    # full. Two reasons, both learned the hard way elsewhere in this file's
    # neighbourhood: `main` unqualified is ambiguous the moment a path called
    # `main` exists, and a linked worktree keeps its refs in the COMMON git
    # dir — so `refs/heads/main` resolves from every worktree of this checkout
    # family, which is where every rung actually runs. No network, no
    # `origin/main`: a fetch is not this leg's business and an unfetched remote
    # must never be able to redden a per-rung gate.
    base=""
    if git rev-parse -q --verify refs/heads/main >/dev/null 2>&1; then
        base=$(git merge-base HEAD refs/heads/main 2>/dev/null || true)
    fi
    branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo HEAD)

    if [ -z "$base" ]; then
        SECRETS_SCAN_BASIS="no local refs/heads/main to fork from — ONLY this checkout's uncommitted changes were scanned, and nothing committed was"
    elif [ "$base" = "$head" ]; then
        # Two different situations, one arithmetic: the merge-base with main IS
        # this HEAD. Either we are ON main, or we are on a branch that has not
        # committed anything of its own yet. In both, there is no committed
        # rung to diff, and the working tree is the whole of the change.
        if [ "$branch" = "main" ]; then
            SECRETS_SCAN_BASIS="on main itself (the merge-base IS this HEAD) — ONLY this checkout's uncommitted changes were scanned, and no committed history was"
        else
            SECRETS_SCAN_BASIS="branch '$branch' has committed nothing yet (the merge-base with main IS this HEAD) — ONLY this checkout's uncommitted changes were scanned"
        fi
    else
        # `--diff-filter=d` (lower case: EXCLUDE deleted) is how a rung that
        # removed a file does not hand detect-secrets a path that is not there.
        # The existence filter below is the belt to this file's braces — a path
        # can be present in one half of the union and gone in the other.
        git diff --name-only -z --diff-filter=d "$base" HEAD >>"$raw" 2>/dev/null || {
            rm -f "$raw"
            echo "!! the secret scan could not diff HEAD against the merge-base $base." >&2
            return 2
        }
        committed_n=$(secrets_scan__count "$raw")
        SECRETS_SCAN_BASIS="$committed_n file(s) committed on '$branch' since the merge-base with main ($(git rev-parse --short "$base" 2>/dev/null || echo "$base")), plus this checkout's uncommitted changes"
    fi

    # The uncommitted half, in every case above: HEAD against the index AND the
    # working tree, so a staged new file and an unstaged edit are both this
    # rung's business the moment they exist.
    git diff --name-only -z --diff-filter=d HEAD >>"$raw" 2>/dev/null || {
        rm -f "$raw"
        echo "!! the secret scan could not diff the working tree against HEAD." >&2
        return 2
    }

    secrets_scan__finish "$raw" "$out"
}

# Dedupe, then keep only paths that are actually readable files right now. A
# rename shows its destination, a deletion was filtered above, and a path that
# is somehow neither is dropped rather than handed to a tool that would exit
# non-zero on it and call it a finding.
secrets_scan__finish() {
    local raw=$1 out=$2 f
    : >"$out"
    while IFS= read -r -d '' f; do
        [ -n "$f" ] || continue
        [ -f "$f" ] || continue
        printf '%s\0' "$f"
    done < <(sort -zu <"$raw") >"$out"
    rm -f "$raw"
    return 0
}

secrets_scan__count() {
    local n=0 f
    while IFS= read -r -d '' f; do
        n=$((n + 1))
    done <"$1"
    printf '%s' "$n"
}

# secrets_scan_loop
#
# The `--loop` leg body: derive, SAY WHAT WAS DERIVED, and scan it. The
# printing is not decoration — a narrowed scan that prints nothing reads
# exactly like a full one, and the whole risk of this change is a reader
# believing a green leg vouched for the tree when it vouched for six files.
#
# Exit: 0 clean (INCLUDING "nothing changed, so nothing was scanned") · 1 a
# finding · 2 the set could not be derived.
secrets_scan_loop() {
    local list n rc
    list=$(mktemp "${TMPDIR:-/tmp}/djb-secrets-list.XXXXXX") || return 2

    if ! secrets_scan_changed_files "$list"; then
        rm -f "$list"
        return 2
    fi
    n=$(secrets_scan__count "$list")

    echo "  basis: ${SECRETS_SCAN_BASIS}"
    if [ "$n" = "0" ]; then
        echo "  NOTHING WAS SCANNED: the active rung has changed no file that git knows about."
        echo "  A leg that looked at nothing is not the same claim as a clean tree — the"
        echo "  FULL-TREE scan over \`git ls-files\` runs at push, in the supply-chain leg."
        rm -f "$list"
        return 0
    fi

    echo "  scanning $n changed file(s) against .secrets.baseline."
    echo "  NOT scanned here: every file the active rung did not touch, and every untracked,"
    echo "  never-staged file. The full-tree scan at push is what covers the first;"
    echo "  nothing has ever covered the second, there or here."
    # `|| rc=$?` and not `set +e`: this function is sourced into a caller whose
    # errexit state is its own business, and a helper that switches it back on
    # unasked is how a later `set -e` arrives somewhere nobody wrote it.
    rc=0
    xargs -0 uv run detect-secrets-hook --baseline .secrets.baseline <"$list" || rc=$?
    rm -f "$list"
    return "$rc"
}
